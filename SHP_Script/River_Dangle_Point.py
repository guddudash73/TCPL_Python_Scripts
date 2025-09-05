import arcpy, os, math, re

arcpy.env.overwriteOutput = True
try:
    arcpy.env.addOutputsToMap = False
except:
    pass

TARGET_NAMES        = {"river_c", "ditch_c"}
NEAR_TOL_M          = 50.0
VERTEX_EPS_M        = 0.20
SEGMENT_EPS_M       = 0.20
PARALLEL_ANGLE_DEG  = 15.0
ENVELOPE_PAD_M      = NEAR_TOL_M
OUT_BASENAME        = "snap_50"

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
        if sr and sr.type == "Projected":
            unit = (sr.linearUnitName or "").lower()
            if ("meter" in unit) or ("metre" in unit):
                return sr
    except:
        pass
    try:
        wgs84 = arcpy.SpatialReference(4326)
        cen = arcpy.PointGeometry(desc.extent.centroid, desc.spatialReference).projectAs(wgs84)
        lon, lat = cen.firstPoint.X, cen.firstPoint.Y
        zone = int(math.floor((lon + 180.0)/6.0) + 1)
        wkid = 32600 + zone if lat >= 0 else 32700 + zone
        return arcpy.SpatialReference(wkid)
    except:
        return arcpy.SpatialReference(3857)

def extent_hits_point_buffer(line_ext, px, py, r):
    return not (line_ext.XMin > px + r or line_ext.XMax < px - r or
                line_ext.YMin > py + r or line_ext.YMax < py - r)

def unit_vec(dx, dy):
    m = math.hypot(dx, dy)
    if m == 0: return (0.0, 0.0)
    return (dx/m, dy/m)

def angle_deg(u, v):
    ux, uy = u; vx, vy = v
    dot = ux*vx + uy*vy
    if dot > 1.0: dot = 1.0
    if dot < -1.0: dot = -1.0
    return math.degrees(math.acos(dot))

def endpoints_and_dirs(geom):
    out = []
    for part in geom:
        pts = [p for p in part if p]
        n = len(pts)
        if n >= 2:
            dx = pts[1].X - pts[0].X
            dy = pts[1].Y - pts[0].Y
            out.append({"pt": pts[0], "dir": unit_vec(dx, dy)})
            dx2 = pts[-1].X - pts[-2].X
            dy2 = pts[-1].Y - pts[-2].Y
            out.append({"pt": pts[-1], "dir": unit_vec(dx2, dy2)})
    return out

def neighbor_dir_at(polyline, dist_along, delta):
    try:
        a = max(0.0, dist_along - delta)
        b = min(polyline.length, dist_along + delta)
        pa = polyline.positionAlongLine(a).firstPoint
        pb = polyline.positionAlongLine(b).firstPoint
        return unit_vec(pb.X - pa.X, pb.Y - pa.Y)
    except:
        return (0.0, 0.0)

def project_point_on_line(point_geom, polyline):
    try:
        qp, dalong, dfrom, _right = polyline.queryPointAndDistance(point_geom)
        return (qp, dalong, dfrom)
    except:
        dfrom = point_geom.distanceTo(polyline)
        return (None, None, dfrom)

layers = list_target_layers()
first_desc = arcpy.Describe(layers[0])
src_sr     = first_desc.spatialReference
out_path   = first_desc.path if getattr(first_desc, "path", None) else os.path.dirname(first_desc.catalogPath)
is_gdb     = (out_path or "").lower().endswith(".gdb")
out_name   = OUT_BASENAME if is_gdb else OUT_BASENAME + ".shp"
out_fc     = os.path.join(out_path, out_name)
metric_sr  = pick_metric_sr(first_desc)

features = []
for lid, lyr in enumerate(layers):
    d = arcpy.Describe(lyr)
    oid_name = d.OIDFieldName
    with arcpy.da.SearchCursor(lyr, [oid_name, "SHAPE@"]) as cur:
        for oid, gsrc in cur:
            if gsrc is None:
                continue
            try:
                same_sr = (d.spatialReference and metric_sr and
                           getattr(d.spatialReference, "factoryCode", None) == getattr(metric_sr, "factoryCode", None))
                gm = gsrc if same_sr else gsrc.projectAs(metric_sr)
            except:
                continue
            if gm is None or gm.pointCount < 2:
                continue
            features.append({
                "lid": lid,
                "layer_name": lyr.name,
                "oid": int(oid),
                "geom_src": gsrc,
                "geom_m": gm,
                "ext": gm.extent,
                "endpoints": endpoints_and_dirs(gm)
            })

if arcpy.Exists(out_fc):
    arcpy.Delete_management(out_fc)
arcpy.CreateFeatureclass_management(out_path, out_name, "POINT", None, "DISABLED", "DISABLED", src_sr)
arcpy.AddField_management(out_fc, "SRC_LAYER", "TEXT", field_length=64)
arcpy.AddField_management(out_fc, "SRC_OID",   "LONG")
arcpy.AddField_management(out_fc, "REASON",    "TEXT", field_length=32)

if not features:
    try:
        mxd = arcpy.mapping.MapDocument("CURRENT")
        df  = arcpy.mapping.ListDataFrames(mxd)[0]
        arcpy.mapping.AddLayer(df, arcpy.mapping.Layer(out_fc), "TOP")
        arcpy.RefreshTOC(); arcpy.RefreshActiveView()
    except:
        pass
    raise SystemExit

points_out = []

for rec in features:
    eplist = rec["endpoints"]
    if not eplist:
        continue

    for ep in eplist:
        ep_dir = ep["dir"]
        if ep_dir == (0.0, 0.0):
            continue
        px, py = ep["pt"].X, ep["pt"].Y
        pt_m = arcpy.PointGeometry(arcpy.Point(px, py), metric_sr)
        reason = None
        for other in features:
            if other["lid"] == rec["lid"] and other["oid"] == rec["oid"]:
                continue
            if not extent_hits_point_buffer(other["ext"], px, py, ENVELOPE_PAD_M):
                continue
            gj = other["geom_m"]
            try:
                d_line = pt_m.distanceTo(gj)
            except:
                continue
            if d_line > NEAR_TOL_M:
                continue
            snapped_to_vertex = False
            for part in gj:
                for v in part:
                    if v is None: continue
                    try:
                        if arcpy.PointGeometry(v, metric_sr).distanceTo(pt_m) <= VERTEX_EPS_M:
                            snapped_to_vertex = True
                            break
                    except:
                        continue
                if snapped_to_vertex:
                    break
            if snapped_to_vertex:
                continue
            qp, dalong, dperp = project_point_on_line(pt_m, gj)
            if dperp is not None and dperp <= SEGMENT_EPS_M:
                reason = "on_segment_no_snap"
                break
            if qp is not None and dalong is not None:
                delta = min(1.0, 0.1 * NEAR_TOL_M)
                n_dir = neighbor_dir_at(gj, dalong, delta)
                ang = angle_deg(ep_dir, n_dir)
                if (ang <= PARALLEL_ANGLE_DEG) or (abs(180.0 - ang) <= PARALLEL_ANGLE_DEG):
                    continue
                else:
                    reason = "non_parallel_close"
                    break
        if reason:
            try:
                pt_src = pt_m.projectAs(rec["geom_src"].spatialReference if rec["geom_src"].spatialReference else src_sr)
            except:
                pt_src = pt_m
            points_out.append({
                "pt_src": pt_src,
                "layer": rec["layer_name"],
                "oid": rec["oid"],
                "reason": reason
            })

if points_out:
    with arcpy.da.InsertCursor(out_fc, ["SHAPE@", "SRC_LAYER", "SRC_OID", "REASON"]) as ic:
        for p in points_out:
            ic.insertRow([p["pt_src"], p["layer"], p["oid"], p["reason"]])

try:
    mxd = arcpy.mapping.MapDocument("CURRENT")
    df  = arcpy.mapping.ListDataFrames(mxd)[0]
    arcpy.mapping.AddLayer(df, arcpy.mapping.Layer(out_fc), "TOP")
    arcpy.RefreshTOC(); arcpy.RefreshActiveView()
except:
    pass

print "Output:", out_fc
print "Matched layers:", ", ".join([lyr.name for lyr in layers])
print "Features scanned:", sum(1 for _ in features)
print "Problem endpoints (points) created:", len(points_out)
print "Done."
