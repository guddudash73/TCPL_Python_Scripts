import arcpy, os, math, uuid

arcpy.env.overwriteOutput = True
try:
    arcpy.env.addOutputsToMap = False
except:
    pass

LAYER_NAME    = "TransportationGroundCurves"
SUBTYPE_NAME  = "ROAD_C"
FALLBACK_CODE = 100152
EXTRA_CODES   = [100156, 100150]

NEAR_TOL_M       = 50.0
VERTEX_EPS_M     = 0.2
ENVELOPE_PAD_M   = NEAR_TOL_M
OUT_NAME         = "snap_50"

def get_src_fc_from_map(name):
    mxd = arcpy.mapping.MapDocument("CURRENT")
    for lyr in arcpy.mapping.ListLayers(mxd):
        if lyr.supports("DATASOURCE") and lyr.name.lower() == name.lower():
            return lyr.dataSource
    for lyr in arcpy.mapping.ListLayers(mxd, "*%s*" % name):
        if lyr.supports("DATASOURCE"):
            return lyr.dataSource
    raise RuntimeError("Layer '%s' not found in the current map" % name)

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
    lon = (ext.XMin + ext.XMax) / 2.0
    lat = (ext.YMin + ext.YMax) / 2.0
    zone = int(math.floor((lon + 180.0)/6.0) + 1)
    try:
        wkid = 32600 + zone if lat >= 0 else 32700 + zone
        return arcpy.SpatialReference(wkid)
    except:
        return arcpy.SpatialReference(3857)

def extent_hits_point_buffer(line_ext, px, py, r):
    return not (line_ext.XMin > px + r or line_ext.XMax < px - r or
                line_ext.YMin > py + r or line_ext.YMax < py - r)

src_fc   = get_src_fc_from_map(LAYER_NAME)
desc     = arcpy.Describe(src_fc)
src_sr   = desc.spatialReference
out_path = desc.path
out_fc   = os.path.join(out_path, OUT_NAME)

subtype_field   = desc.subtypeFieldName or "FCSubtype"
road_code       = resolve_subtype_code(src_fc, SUBTYPE_NAME, FALLBACK_CODE)
accepted_codes  = set([road_code] + EXTRA_CODES)

oid_name   = desc.OIDFieldName
metric_sr  = pick_metric_sr(desc)
attr_names = [f.name for f in arcpy.ListFields(src_fc) if f.type not in ("OID","Geometry","Raster")]

roads = []
with arcpy.da.SearchCursor(src_fc, [oid_name, "SHAPE@", subtype_field] + attr_names) as cur:
    for row in cur:
        if row[2] not in accepted_codes:
            continue
        oid  = int(row[0])
        gsrc = row[1]
        attrs = list(row[3:])
        try:
            gm = gsrc.projectAs(metric_sr) if src_sr.name != metric_sr.name else gsrc
        except:
            gm = gsrc
        roads.append({"oid": oid, "geom_src": gsrc, "geom_m": gm, "ext": gm.extent, "attrs": attrs})

if arcpy.Exists(out_fc):
    arcpy.Delete_management(out_fc)
arcpy.CreateFeatureclass_management(out_path, OUT_NAME, "POLYLINE",
                                    template=src_fc, spatial_reference=src_sr)

flagged = set()

for i, ri in enumerate(roads):
    gi = ri["geom_m"]
    if gi is None or gi.pointCount < 2:
        continue
    p_start = gi.firstPoint
    p_end   = gi.lastPoint
    for (px, py) in ((p_start.X, p_start.Y), (p_end.X, p_end.Y)):
        near_any = False
        snapped_to_vertex = False
        pt = arcpy.PointGeometry(arcpy.Point(px, py), metric_sr)
        for j, rj in enumerate(roads):
            if rj["oid"] == ri["oid"]:
                continue
            if not extent_hits_point_buffer(rj["ext"], px, py, ENVELOPE_PAD_M):
                continue
            gj = rj["geom_m"]
            try:
                d = pt.distanceTo(gj)
            except:
                continue
            if d <= NEAR_TOL_M:
                near_any = True
                for part in gj:
                    for v in part:
                        if v is None:
                            continue
                        dv = arcpy.PointGeometry(v, metric_sr).distanceTo(pt)
                        if dv <= VERTEX_EPS_M:
                            snapped_to_vertex = True
                            break
                    if snapped_to_vertex:
                        break
                if near_any and not snapped_to_vertex:
                    break
        if near_any and not snapped_to_vertex:
            flagged.add(ri["oid"])

if flagged:
    insert_fields = ["SHAPE@"] + attr_names
    with arcpy.da.InsertCursor(out_fc, insert_fields) as ic:
        for rec in roads:
            if rec["oid"] in flagged:
                ic.insertRow([rec["geom_src"]] + rec["attrs"])

try:
    mxd = arcpy.mapping.MapDocument("CURRENT")
    df  = arcpy.mapping.ListDataFrames(mxd)[0]
    arcpy.mapping.AddLayer(df, arcpy.mapping.Layer(out_fc), "TOP")
    arcpy.RefreshTOC(); arcpy.RefreshActiveView()
except:
    pass

print("Output:", out_fc)
print("Accepted subtype codes:", sorted(list(accepted_codes)))
print("Features scanned:", len(roads))
print("Lines flagged (endpoint near <= %.1f m but not snapped to a vertex): %d" % (NEAR_TOL_M, len(flagged)))
print("Done.")
