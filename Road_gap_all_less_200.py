#...# ...TCPL calculate Gap by Buffer

import arcpy, os, math

arcpy.env.overwriteOutput = True
try:
    arcpy.env.addOutputsToMap = False
except:
    pass

LAYER_NAME    = "TransportationGroundCurves"
SUBTYPE_NAME  = "ROAD_C"
FALLBACK_CODE = 100152
EXTRA_CODES   = [100156, 100150]
RADIUS_M      = 200.0
BUF_EPS       = 0.001
OUT_NAME      = "road_gap_less_200"

def get_src_fc_from_map(name):
    mxd = arcpy.mapping.MapDocument("CURRENT")
    for lyr in arcpy.mapping.ListLayers(mxd):
        if lyr.supports("DATASOURCE") and lyr.name.lower() == name.lower():
            return lyr.dataSource
    for lyr in arcpy.mapping.ListLayers(mxd, "*%s*" % name):
        if lyr.supports("DATASOURCE"):
            return lyr.dataSource
    raise RuntimeError("Layer '%s' not found" % name)

def resolve_subtype_code(fc, wanted_name, fallback_code):
    try:
        for code, props in (arcpy.da.ListSubtypes(fc) or {}).items():
            nm = (props.get('Name') or props.get('SubtypeName') or "").upper()
            if nm == wanted_name.upper():
                return int(code)
    except:
        pass
    return int(fallback_code)

def pick_metric_sr(desc):
    try:
        sr = desc.spatialReference
        if sr and sr.type == "Projected" and "Meter" in (sr.linearUnitName or "Meter"):
            return sr
    except:
        pass
    ext = desc.extent
    lon = (ext.XMin + ext.XMax)/2.0
    lat = (ext.YMin + ext.YMax)/2.0
    zone = int(math.floor((lon + 180.0)/6.0) + 1)
    try:
        wkid = 32600 + zone if lat >= 0 else 32700 + zone
        return arcpy.SpatialReference(wkid)
    except:
        return arcpy.SpatialReference(3857)

src_fc   = get_src_fc_from_map(LAYER_NAME)
desc     = arcpy.Describe(src_fc)
src_sr   = desc.spatialReference
out_path = desc.path
out_fc   = os.path.join(out_path, OUT_NAME)

subtype_field = desc.subtypeFieldName or "FCSubtype"
road_code     = resolve_subtype_code(src_fc, SUBTYPE_NAME, FALLBACK_CODE)

accepted_codes = set([road_code] + EXTRA_CODES)

oid_name   = desc.OIDFieldName
metric_sr  = pick_metric_sr(desc)
attr_names = [f.name for f in arcpy.ListFields(src_fc) if f.type not in ("OID","Geometry","Raster")]

roads = []
with arcpy.da.SearchCursor(src_fc, [oid_name, "SHAPE@", subtype_field] + attr_names) as cur:
    for row in cur:
        if row[2] not in accepted_codes:
            continue
        soid  = int(row[0])
        gsrc  = row[1]
        attrs = list(row[3:])
        try:
            gm = gsrc.projectAs(metric_sr) if src_sr.name != metric_sr.name else gsrc
        except:
            gm = gsrc
        try:
            bm = gm.buffer(RADIUS_M + BUF_EPS)
        except:
            continue
        roads.append({"oid": soid, "geom_src": gsrc, "geom_m": gm, "buf_m": bm, "attrs": attrs})

if arcpy.Exists(out_fc):
    arcpy.Delete_management(out_fc)
arcpy.CreateFeatureclass_management(out_path, OUT_NAME, "POLYLINE",
                                    template=src_fc, spatial_reference=src_sr)

if not roads:
    try:
        mxd = arcpy.mapping.MapDocument("CURRENT")
        df  = arcpy.mapping.ListDataFrames(mxd)[0]
        arcpy.mapping.AddLayer(df, arcpy.mapping.Layer(out_fc), "TOP")
        arcpy.RefreshTOC(); arcpy.RefreshActiveView()
    except:
        pass
    raise SystemExit

keep_mutual   = set()
keep_onesided = set()

n = len(roads)
for i in range(n):
    gi = roads[i]["geom_m"]; bi = roads[i]["buf_m"]; oi = roads[i]["oid"]
    for j in range(i+1, n):
        gj = roads[j]["geom_m"]; bj = roads[j]["buf_m"]; oj = roads[j]["oid"]
        try:
            a_in_b = gi.within(bj)
            b_in_a = gj.within(bi)
        except:
            continue
        if a_in_b and b_in_a:
            keep_mutual.add(oi); keep_mutual.add(oj)
        elif a_in_b or b_in_a:
            keep_onesided.add(oi if a_in_b else oj)

final_keep = keep_mutual.union(keep_onesided)

if final_keep:
    insert_fields = ["SHAPE@"] + attr_names
    with arcpy.da.InsertCursor(out_fc, insert_fields) as ic:
        for rec in roads:
            if rec["oid"] in final_keep:
                ic.insertRow([rec["geom_src"]] + rec["attrs"])

try:
    mxd = arcpy.mapping.MapDocument("CURRENT")
    df  = arcpy.mapping.ListDataFrames(mxd)[0]
    arcpy.mapping.AddLayer(df, arcpy.mapping.Layer(out_fc), "TOP")
    arcpy.RefreshTOC(); arcpy.RefreshActiveView()
except:
    pass

print "Output:", out_fc
print "Accepted subtype codes:", sorted(list(accepted_codes))
print "Features read:", len(roads)
print "Kept (mutual):", len(keep_mutual), " | Kept (one-sided):", len(keep_onesided)
print "Final kept (union):", len(final_keep)
print "Done."
