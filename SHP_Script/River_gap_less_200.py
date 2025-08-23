import arcpy, os, math, re

arcpy.env.overwriteOutput = True
try:
    arcpy.env.addOutputsToMap = False
except:
    pass

TARGET_NAMES = {"river_c", "ditch_c"}
RADIUS_M     = 200.0
BUF_EPS      = 0.001
OUT_BASENAME = "road_gap_less_200"

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

layers = _find_layers()
first_desc = arcpy.Describe(layers[0])
src_sr     = first_desc.spatialReference
out_path   = first_desc.path if getattr(first_desc, "path", None) else os.path.dirname(first_desc.catalogPath)
is_gdb     = out_path.lower().endswith(".gdb")
out_name   = OUT_BASENAME if is_gdb else OUT_BASENAME + ".shp"
out_fc     = os.path.join(out_path, out_name)
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
                bm = gm.buffer(RADIUS_M + BUF_EPS)
            except:
                continue
            features.append({"oid": int(oid), "geom_src": gsrc, "geom_m": gm, "buf_m": bm})

if arcpy.Exists(out_fc):
    arcpy.Delete_management(out_fc)
arcpy.CreateFeatureclass_management(out_path, out_name, "POLYLINE", None, "DISABLED", "DISABLED", src_sr)

if not features:
    try:
        mxd = arcpy.mapping.MapDocument("CURRENT")
        df  = arcpy.mapping.ListDataFrames(mxd)[0]
        arcpy.mapping.AddLayer(df, arcpy.mapping.Layer(out_fc), "TOP")
        arcpy.RefreshTOC(); arcpy.RefreshActiveView()
    except:
        pass
    raise SystemExit

keep_mutual, keep_onesided = set(), set()
n = len(features)
for i in range(n):
    gi = features[i]["geom_m"]; bi = features[i]["buf_m"]; oi = features[i]["oid"]
    for j in range(i+1, n):
        gj = features[j]["geom_m"]; bj = features[j]["buf_m"]; oj = features[j]["oid"]
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
    with arcpy.da.InsertCursor(out_fc, ["SHAPE@"]) as ic:
        for rec in features:
            if rec["oid"] in final_keep:
                ic.insertRow([rec["geom_src"]])

try:
    mxd = arcpy.mapping.MapDocument("CURRENT")
    df  = arcpy.mapping.ListDataFrames(mxd)[0]
    arcpy.mapping.AddLayer(df, arcpy.mapping.Layer(out_fc), "TOP")
    arcpy.RefreshTOC(); arcpy.RefreshActiveView()
except:
    pass

print "Output:", out_fc
print "Matched layers:", ", ".join([lyr.name for lyr in layers])
print "Features read:", len(features)
print "Kept (mutual):", len(keep_mutual), " | Kept (one-sided):", len(keep_onesided)
print "Final kept (union):", len(final_keep)
print "Done."
