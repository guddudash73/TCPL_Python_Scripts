import arcpy, os, math, re

arcpy.env.overwriteOutput = True
try:
    arcpy.env.addOutputsToMap = False
except:
    pass

TARGET_NAMES = {"road_c", "trail_c", "cart_track"}
RADIUS_M     = 300.0
BUF_EPS      = 0.001
OUT_BASENAME = "road_gap_less_300"

def norm_name(s):
    s = s.lower()
    s = re.sub(r"[\s\-]+", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    return s

def list_target_layers():
    mxd = arcpy.mapping.MapDocument("CURRENT")
    hits = []
    for lyr in arcpy.mapping.ListLayers(mxd):
        if lyr.supports("DATASOURCE"):
            if norm_name(lyr.name) in TARGET_NAMES:
                hits.append(lyr)
    if not hits:
        raise RuntimeError("None of the target layers found")
    return hits

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

layers = list_target_layers()
first_desc = arcpy.Describe(layers[0])
src_sr     = first_desc.spatialReference
if hasattr(first_desc, "path") and first_desc.path:
    out_path = first_desc.path
else:
    out_path = os.path.dirname(first_desc.catalogPath)
is_gdb = out_path.lower().endswith(".gdb")
out_name = OUT_BASENAME if is_gdb else OUT_BASENAME + ".shp"
out_fc = os.path.join(out_path, out_name)
metric_sr  = pick_metric_sr(first_desc)

roads = []
for lyr in layers:
    d = arcpy.Describe(lyr)
    oid_name = d.OIDFieldName
    with arcpy.da.SearchCursor(lyr, [oid_name, "SHAPE@"]) as cur:
        for oid, gsrc in cur:
            soid = int(oid)
            try:
                gm = gsrc.projectAs(metric_sr) if d.spatialReference.name != metric_sr.name else gsrc
            except:
                gm = gsrc
            try:
                bm = gm.buffer(RADIUS_M + BUF_EPS)
            except:
                continue
            roads.append({"oid": soid, "geom_src": gsrc, "geom_m": gm, "buf_m": bm})

if arcpy.Exists(out_fc):
    arcpy.Delete_management(out_fc)
arcpy.CreateFeatureclass_management(out_path, out_name, "POLYLINE", None, "DISABLED", "DISABLED", src_sr)

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
    with arcpy.da.InsertCursor(out_fc, ["SHAPE@"]) as ic:
        for rec in roads:
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
print "Features read:", len(roads)
print "Kept (mutual):", len(keep_mutual), " | Kept (one-sided):", len(keep_onesided)
print "Final kept (union):", len(final_keep)
print "Done."
