import arcpy, os, math, re

arcpy.env.overwriteOutput = True
try:
    arcpy.env.addOutputsToMap = False
except:
    pass

TARGET_NAMES = {"river_c", "ditch_c"}
RADIUS_M     = 200.0
BUF_EPS      = 0.001
OUT_BASENAME = "river_gap_less_200"

def _norm(s):
    s = s.lower()
    s = re.sub(r"[\s\-]+", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    return s

def _find_layers():
    mxd = arcpy.mapping.MapDocument("CURRENT")
    hits = []
    for lyr in arcpy.mapping.ListLayers(mxd):
        if lyr.supports("DATASOURCE") and _norm(lyr.name) in TARGET_NAMES:
            hits.append(lyr)
    if not hits:
        raise RuntimeError("No target layers found: %s" % ", ".join(sorted(TARGET_NAMES)))
    return hits

def _metric_sr(desc):
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

layers     = _find_layers()
first_desc = arcpy.Describe(layers[0])
src_sr     = first_desc.spatialReference
out_path   = first_desc.path if getattr(first_desc, "path", None) else os.path.dirname(first_desc.catalogPath)
is_gdb     = out_path.lower().endswith(".gdb")
out_name_l = OUT_BASENAME if is_gdb else OUT_BASENAME + ".shp"
out_name_p = OUT_BASENAME + "_midpts" if is_gdb else OUT_BASENAME + "_midpts.shp"
out_fc_l   = os.path.join(out_path, out_name_l)
out_fc_p   = os.path.join(out_path, out_name_p)
metric_sr  = _metric_sr(first_desc)

features = []
for lyr in layers:
    d = arcpy.Describe(lyr)
    oid_name = d.OIDFieldName
    with arcpy.da.SearchCursor(lyr, [oid_name, "SHAPE@"]) as cur:
        for oid, gsrc in cur:
            try:
                gm = gsrc.projectAs(metric_sr) if d.spatialReference.name != metric_sr.name else gsrc
            except:
                gm = gsrc
            try:
                length_m = gm.length
                mid_m = gm.positionAlongLine(length_m/2.0, False)
            except:
                continue
            features.append({"oid": int(oid), "geom_src": gsrc, "geom_m": gm, "mid_m": mid_m})

for fc in [out_fc_l, out_fc_p]:
    if arcpy.Exists(fc):
        arcpy.Delete_management(fc)

arcpy.CreateFeatureclass_management(out_path, out_name_l, "POLYLINE", None, "DISABLED", "DISABLED", src_sr)
arcpy.CreateFeatureclass_management(out_path, out_name_p, "POINT",    None, "DISABLED", "DISABLED", src_sr)

if not features:
    try:
        mxd = arcpy.mapping.MapDocument("CURRENT")
        df  = arcpy.mapping.ListDataFrames(mxd)[0]
        arcpy.mapping.AddLayer(df, arcpy.mapping.Layer(out_fc_l), "TOP")
        arcpy.mapping.AddLayer(df, arcpy.mapping.Layer(out_fc_p), "TOP")
        arcpy.RefreshTOC(); arcpy.RefreshActiveView()
    except:
        pass
    raise SystemExit

keep_set = set()
n = len(features)
for i in range(n):
    gi = features[i]["geom_m"]
    mi = features[i]["mid_m"]
    oi = features[i]["oid"]
    hit = False
    for j in range(n):
        if i == j:
            continue
        gj = features[j]["geom_m"]
        try:
            dist = gj.distanceTo(mi)
        except:
            continue
        if dist <= RADIUS_M + BUF_EPS:
            hit = True
            break
    if hit:
        keep_set.add(oi)

if keep_set:
    with arcpy.da.InsertCursor(out_fc_l, ["SHAPE@"]) as ic:
        for rec in features:
            if rec["oid"] in keep_set:
                ic.insertRow([rec["geom_src"]])

with arcpy.da.InsertCursor(out_fc_p, ["SHAPE@"]) as ip:
    for rec in features:
        try:
            mid_src = rec["mid_m"].projectAs(src_sr) if metric_sr.name != src_sr.name else rec["mid_m"]
        except:
            mid_src = rec["mid_m"]
        ip.insertRow([mid_src])

try:
    mxd = arcpy.mapping.MapDocument("CURRENT")
    df  = arcpy.mapping.ListDataFrames(mxd)[0]
    arcpy.mapping.AddLayer(df, arcpy.mapping.Layer(out_fc_l), "TOP")
    arcpy.mapping.AddLayer(df, arcpy.mapping.Layer(out_fc_p), "TOP")
    arcpy.RefreshTOC(); arcpy.RefreshActiveView()
except:
    pass

print "Output lines:", out_fc_l
print "Output midpoints:", out_fc_p
print "Matched layers:", ", ".join([lyr.name for lyr in layers])
print "Features read:", len(features)
print "Kept (midpoint <= %sm):" % RADIUS_M, len(keep_set)
print "Done."
