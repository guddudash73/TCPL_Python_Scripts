import arcpy, os, math, re

arcpy.env.overwriteOutput = True
try:
    arcpy.env.addOutputsToMap = False
except:
    pass

TARGET_NAMES   = {"road_c", "trail_c", "cart_track"}
NEAR_TOL_M     = 50.0
VERTEX_EPS_M   = 0.2
ENVELOPE_PAD_M = NEAR_TOL_M
OUT_BASENAME   = "snap_50"

def norm_name(s):
    s = s.lower()
    s = re.sub(r"[\s\-]+", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    return s

def list_target_layers():
    mxd = arcpy.mapping.MapDocument("CURRENT")
    hits = []
    for lyr in arcpy.mapping.ListLayers(mxd):
        if lyr.supports("DATASOURCE") and norm_name(lyr.name) in TARGET_NAMES:
            hits.append(lyr)
    if not hits:
        raise RuntimeError("None of the target layers found: %s" % ", ".join(sorted(TARGET_NAMES)))
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

def extent_hits_point_buffer(line_ext, px, py, r):
    return not (line_ext.XMin > px + r or line_ext.XMax < px - r or
                line_ext.YMin > py + r or line_ext.YMax < py - r)

layers = list_target_layers()
first_desc = arcpy.Describe(layers[0])
src_sr     = first_desc.spatialReference
out_path   = first_desc.path if getattr(first_desc, "path", None) else os.path.dirname(first_desc.catalogPath)
is_gdb     = out_path.lower().endswith(".gdb")
out_name   = OUT_BASENAME if is_gdb else OUT_BASENAME + ".shp"
out_fc     = os.path.join(out_path, out_name)
metric_sr  = pick_metric_sr(first_desc)

features = []
for lyr in layers:
    d = arcpy.Describe(lyr)
    oid_name = d.OIDFieldName
    with arcpy.da.SearchCursor(lyr, [oid_name, "SHAPE@"]) as cur:
        for oid, gsrc in cur:
            try:
                gm = gsrc.projectAs(metric_sr) if d.spatialReference and d.spatialReference.name != metric_sr.name else gsrc
            except:
                gm = gsrc
            features.append({"oid": int(oid), "geom_src": gsrc, "geom_m": gm, "ext": gm.extent})

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

flagged = set()

for rec in features:
    gi = rec["geom_m"]
    if gi is None or gi.pointCount < 2:
        continue
    p_start = gi.firstPoint
    p_end   = gi.lastPoint
    should_flag_this_feature = False
    for (px, py) in ((p_start.X, p_start.Y), (p_end.X, p_end.Y)):
        pt = arcpy.PointGeometry(arcpy.Point(px, py), metric_sr)
        snapped_any_neighbor = False
        near_any_neighbor = False
        for other in features:
            if other["oid"] == rec["oid"]:
                continue
            if not extent_hits_point_buffer(other["ext"], px, py, ENVELOPE_PAD_M):
                continue
            gj = other["geom_m"]
            try:
                d = pt.distanceTo(gj)
            except:
                continue
            if d <= NEAR_TOL_M:
                near_any_neighbor = True
                snapped_here = False
                for part in gj:
                    for v in part:
                        if v is None:
                            continue
                        try:
                            dv = arcpy.PointGeometry(v, metric_sr).distanceTo(pt)
                        except:
                            continue
                        if dv <= VERTEX_EPS_M:
                            snapped_here = True
                            break
                    if snapped_here:
                        break
                if snapped_here:
                    snapped_any_neighbor = True
                    break
        if not snapped_any_neighbor and near_any_neighbor:
            should_flag_this_feature = True
            break
    if should_flag_this_feature:
        flagged.add(rec["oid"])

if flagged:
    with arcpy.da.InsertCursor(out_fc, ["SHAPE@"]) as ic:
        for rec in features:
            if rec["oid"] in flagged:
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
print "Features scanned:", len(features)
print "Lines flagged (endpoint near <= %.1f m and NOT snapped to ANY vertex): %d" % (NEAR_TOL_M, len(flagged))
print "Done."
