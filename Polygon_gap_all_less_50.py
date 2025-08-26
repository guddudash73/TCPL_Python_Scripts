#.. TCPL_Polygon gap calculation tool <50m (v1.0)

import arcpy, os, math, time, uuid

arcpy.env.overwriteOutput = True
try:
    arcpy.env.addOutputsToMap = False
except:
    pass

LAYER_NAMES = ["AgricultureSurfaces", "HydrographySurfaces", "PhysiographySurfaces", "VegetationSurfaces"]
THRESHOLD_M = 50.0
MIN_AREA_M2 = 10.0
XY_TOL_M = 0.001
OUT_NAME = "polygon_gap_less_50"

RADIUS_M = THRESHOLD_M / 2.0

def msg(s):
    arcpy.AddMessage(s)
    try:
        print(s)
    except:
        pass

def all_layers():
    mxd = arcpy.mapping.MapDocument("CURRENT")
    for lyr in arcpy.mapping.ListLayers(mxd):
        yield lyr

def find_layer(name):
    for lyr in all_layers():
        if lyr.supports("DATASOURCE") and lyr.name.lower() == name.lower():
            return lyr
    for lyr in all_layers():
        if lyr.supports("DATASOURCE") and name.lower() in lyr.name.lower():
            return lyr
    return None

def gdb_of_fc(fc_path):
    p1 = os.path.dirname(fc_path)
    if p1.lower().endswith(".gdb"):
        return p1
    p2 = os.path.dirname(p1)
    if p2.lower().endswith(".gdb"):
        return p2
    return p1

def get_scratch_gdb(fallback_fc):
    try:
        sg = arcpy.env.scratchGDB
        if sg and arcpy.Exists(sg):
            return sg
    except:
        pass
    return gdb_of_fc(fallback_fc)

def unique_name(prefix, ws):
    return arcpy.CreateUniqueName("%s_%s" % (prefix, uuid.uuid4().hex[:8]), ws)

def ensure_metric_projected(in_fc, proj_ws):
    d = arcpy.Describe(in_fc)
    sr = d.spatialReference
    if sr and sr.type == "Projected" and sr.linearUnitName and sr.linearUnitName.lower().startswith("meter"):
        return in_fc, sr
    ext = d.Extent
    center_pt = arcpy.Point((ext.XMin + ext.XMax) / 2.0, (ext.YMin + ext.YMax) / 2.0)
    center_geom = arcpy.PointGeometry(center_pt, sr)
    center_wgs = center_geom.projectAs(arcpy.SpatialReference(4326))
    lon = center_wgs.firstPoint.X
    lat = center_wgs.firstPoint.Y
    zone = int(math.floor((lon + 180.0) / 6.0) + 1)
    epsg = (32600 if lat >= 0 else 32700) + zone
    utm = arcpy.SpatialReference(epsg)
    out_fc = unique_name("tmp_proj", proj_ws)
    msg("  Projecting to UTM Zone %d (EPSG:%d) in %s" % (zone, epsg, proj_ws))
    arcpy.Project_management(in_fc, out_fc, utm)
    return out_fc, utm

def create_out_fc(out_dataset, template_sr):
    out_fc = os.path.join(out_dataset, OUT_NAME)
    if arcpy.Exists(out_fc):
        arcpy.Delete_management(out_fc)
    arcpy.CreateFeatureclass_management(out_dataset, OUT_NAME, "POLYGON", spatial_reference=template_sr)
    arcpy.AddField_management(out_fc, "SourceLayer", "TEXT", field_length=40)
    arcpy.AddField_management(out_fc, "ParentOID", "LONG")
    arcpy.AddField_management(out_fc, "threshold_m", "DOUBLE")
    arcpy.AddField_management(out_fc, "area_m2", "DOUBLE")
    arcpy.AddField_management(out_fc, "method", "TEXT", field_length=20)
    return out_fc

def get_dataset_path(fc_path):
    parent = os.path.dirname(fc_path)
    return parent

def get_fid_field_name(fc):
    for f in arcpy.ListFields(fc):
        if f.name.upper().startswith("FID_"):
            return f.name
    return None

def process_one_layer(src_fc, layer_label, out_fc, out_sr):
    msg("Processing: %s" % layer_label)
    if arcpy.Describe(src_fc).shapeType.upper() != "POLYGON":
        msg("  Skipped (not polygon): %s" % layer_label)
        return 0
    scratch_ws = get_scratch_gdb(src_fc)
    sel_fc = arcpy.CreateUniqueName("tmp_sel", "in_memory")
    arcpy.CopyFeatures_management(src_fc, sel_fc)
    sp_fc = arcpy.CreateUniqueName("tmp_sp", "in_memory")
    arcpy.MultipartToSinglepart_management(sel_fc, sp_fc)
    arcpy.RepairGeometry_management(sp_fc)
    metric_fc, metric_sr = ensure_metric_projected(sp_fc, scratch_ws)
    neg_fc = arcpy.CreateUniqueName("tmp_neg", "in_memory")
    try:
        arcpy.Buffer_analysis(metric_fc, neg_fc, "-%g Meters" % RADIUS_M, dissolve_option="NONE", method="PLANAR")
    except:
        neg_fc = arcpy.CreateUniqueName("tmp_neg_empty", "in_memory")
        arcpy.CreateFeatureclass_management("in_memory", os.path.basename(neg_fc), "POLYGON", spatial_reference=metric_sr)
    opened_fc = arcpy.CreateUniqueName("tmp_open", "in_memory")
    if int(arcpy.GetCount_management(neg_fc).getOutput(0)) > 0:
        arcpy.Buffer_analysis(neg_fc, opened_fc, "%g Meters" % RADIUS_M, dissolve_option="NONE", method="PLANAR")
    else:
        opened_fc = arcpy.CreateUniqueName("tmp_open_empty", "in_memory")
        arcpy.CreateFeatureclass_management("in_memory", os.path.basename(opened_fc), "POLYGON", spatial_reference=metric_sr)
    gap_tmp = arcpy.CreateUniqueName("tmp_gap", "in_memory")
    try:
        arcpy.Erase_analysis(metric_fc, opened_fc, gap_tmp)
    except:
        gap_tmp = arcpy.CreateUniqueName("tmp_gap_empty", "in_memory")
        arcpy.CreateFeatureclass_management("in_memory", os.path.basename(gap_tmp), "POLYGON", spatial_reference=metric_sr)
    if int(arcpy.GetCount_management(gap_tmp).getOutput(0)) > 0:
        if "area_m2" not in [f.name.lower() for f in arcpy.ListFields(gap_tmp)]:
            arcpy.AddField_management(gap_tmp, "area_m2", "DOUBLE")
        arcpy.CalculateField_management(gap_tmp, "area_m2", "!shape.area@SQUAREMETERS!", "PYTHON_9.3")
        if MIN_AREA_M2 > 0:
            gap_lyr = arcpy.MakeFeatureLayer_management(gap_tmp, "gap_lyr").getOutput(0)
            arcpy.SelectLayerByAttribute_management(gap_lyr, "NEW_SELECTION", "area_m2 >= %g" % MIN_AREA_M2)
            gap_clean = arcpy.CreateUniqueName("tmp_gap_clean", "in_memory")
            arcpy.CopyFeatures_management(gap_lyr, gap_clean)
            gap_tmp = gap_clean
    tagged = arcpy.CreateUniqueName("tmp_tag", "in_memory")
    try:
        arcpy.Identity_analysis(gap_tmp, metric_fc, tagged, "ONLY_FID")
    except:
        tagged = gap_tmp
    back_proj = unique_name("tmp_backproj", scratch_ws)
    arcpy.Project_management(tagged, back_proj, out_sr)
    fid_field = get_fid_field_name(back_proj)
    if fid_field and fid_field != "ParentOID":
        if "ParentOID" not in [f.name for f in arcpy.ListFields(back_proj)]:
            arcpy.AddField_management(back_proj, "ParentOID", "LONG")
        arcpy.CalculateField_management(back_proj, "ParentOID", "!%s!" % fid_field, "PYTHON_9.3")
    if "SourceLayer" not in [f.name for f in arcpy.ListFields(back_proj)]:
        arcpy.AddField_management(back_proj, "SourceLayer", "TEXT", field_length=40)
    if "threshold_m" not in [f.name for f in arcpy.ListFields(back_proj)]:
        arcpy.AddField_management(back_proj, "threshold_m", "DOUBLE")
    if "method" not in [f.name for f in arcpy.ListFields(back_proj)]:
        arcpy.AddField_management(back_proj, "method", "TEXT", field_length=20)
    if "area_m2" not in [f.name.lower() for f in arcpy.ListFields(back_proj)]:
        arcpy.AddField_management(back_proj, "area_m2", "DOUBLE")
        arcpy.CalculateField_management(back_proj, "area_m2", "!shape.area@SQUAREMETERS!", "PYTHON_9.3")
    arcpy.CalculateField_management(back_proj, "SourceLayer", "'%s'" % layer_label, "PYTHON_9.3")
    arcpy.CalculateField_management(back_proj, "threshold_m", THRESHOLD_M, "PYTHON_9.3")
    arcpy.CalculateField_management(back_proj, "method", "'Opening'", "PYTHON_9.3")
    if int(arcpy.GetCount_management(back_proj).getOutput(0)) > 0:
        arcpy.Append_management(back_proj, out_fc, "NO_TEST")
        return int(arcpy.GetCount_management(back_proj).getOutput(0))
    else:
        return 0

def main():
    arcpy.env.XYTolerance = "%g Meters" % XY_TOL_M
    first_found = None
    layer_map = {}
    for name in LAYER_NAMES:
        lyr = find_layer(name)
        if lyr and lyr.supports("DATASOURCE"):
            layer_map[name] = lyr
            if not first_found:
                first_found = lyr
    if not first_found:
        raise RuntimeError("None of the specified layers were found in the current map.")
    src_fc = layer_map[first_found.name].dataSource if first_found.name in layer_map else first_found.dataSource
    out_dataset = get_dataset_path(src_fc)
    out_sr = arcpy.Describe(src_fc).spatialReference
    msg("Output dataset: %s" % out_dataset)
    out_fc = create_out_fc(out_dataset, out_sr)
    total = 0
    for name in LAYER_NAMES:
        lyr = layer_map.get(name)
        if not lyr:
            msg("Skipping (not found): %s" % name)
            continue
        fc = lyr.dataSource
        count = process_one_layer(fc, name, out_fc, out_sr)
        msg("  Added %d parts from %s" % (count, name))
        total += count
    msg("Done. Created %s with %d polygon(s) where width < %.2f m." % (out_fc, total, THRESHOLD_M))

if __name__ == "__main__":
    main()
