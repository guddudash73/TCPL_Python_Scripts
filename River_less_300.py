# ArcMap 10.x — Export selected subtypes <300 m to road_less_300 (single clean output)
import arcpy, os
arcpy.env.overwriteOutput = True

LAYER_NAME   = "HydrographyCurves"          # TOC name
SUBTYPE_NAMES = ["RIVER_C", "DITCH_C"]  # <- add/remove names here
# Optional hard-coded codes if you know them; names (above) will be resolved first.
FALLBACK_CODES = [100314]  # ROAD_C known; others resolved via names

def get_src_fc_from_map(name):
    mxd = arcpy.mapping.MapDocument("CURRENT")
    for lyr in arcpy.mapping.ListLayers(mxd):
        if lyr.supports("DATASOURCE") and lyr.name.lower() == name.lower():
            return lyr.dataSource
    # fallback partial match
    for lyr in arcpy.mapping.ListLayers(mxd, "*{}*".format(name)):
        if lyr.supports("DATASOURCE"):
            return lyr.dataSource
    raise RuntimeError("Layer '{}' not found in the current map.".format(name))

def resolve_subtype_codes(fc, wanted_names, fallback_codes):
    """Return list of subtype codes for the given names (case-insensitive)."""
    codes = set()
    try:
        subtypes = arcpy.da.ListSubtypes(fc) or {}
        # subtypes: {code: {'Name': 'ROAD_C', ...}, ...}
        name_to_code = {}
        for code, props in subtypes.items():
            nm = (props.get('Name') or "").upper()
            if nm:
                name_to_code[nm] = code
        for nm in wanted_names:
            c = name_to_code.get(nm.upper())
            if c is not None:
                codes.add(int(c))
    except:
        pass
    # also include any fallback numeric codes provided
    for c in fallback_codes or []:
        try:
            codes.add(int(c))
        except:
            pass
    if not codes:
        raise RuntimeError("Could not resolve subtype codes for {}. "
                           "Check names or provide numeric codes."
                           .format(wanted_names))
    return sorted(codes)

# --- Resolve source and destination container
src_fc    = get_src_fc_from_map(LAYER_NAME)
src_desc  = arcpy.Describe(src_fc)
out_path  = src_desc.path                      # same container (feature dataset or GDB root)
out_name  = "river_less_300" 
out_fc    = os.path.join(out_path, out_name)

# Subtype field
subtype_field = src_desc.subtypeFieldName or "FCSubtype"
# Codes to filter
CODES = resolve_subtype_codes(src_fc, SUBTYPE_NAMES, FALLBACK_CODES)

# --- Create empty output beside the source (ensures SR compatibility)
if arcpy.Exists(out_fc):
    arcpy.Delete_management(out_fc)

try:
    container_sr = arcpy.Describe(out_path).spatialReference  # if out_path is a feature dataset
except:
    container_sr = None
sr_for_output = container_sr if container_sr and container_sr.name != "Unknown" else src_desc.spatialReference

arcpy.CreateFeatureclass_management(
    out_path=out_path,
    out_name=out_name,
    geometry_type=src_desc.shapeType,              # Polyline
    template=src_fc,                               # copy schema/fields/domains
    has_m="ENABLED" if src_desc.hasM else "DISABLED",
    has_z="ENABLED" if src_desc.hasZ else "DISABLED",
    spatial_reference=sr_for_output
)

# Build safe field lists present and editable in output
src_fields = {f.name: f for f in arcpy.ListFields(src_fc)}
out_fields = {f.name: f for f in arcpy.ListFields(out_fc)}
copy_fields = [n for n in src_fields
               if n in out_fields
               and n.upper() not in ("OBJECTID","GLOBALID","SHAPE","SHAPE_LENGTH","SHAPE_AREA")
               and out_fields[n].editable]

search_fields = ["SHAPE@", subtype_field] + copy_fields
insert_fields = ["SHAPE@"] + copy_fields

# --- Copy only wanted subtypes with GEODESIC length < 300 m
kept = 0
with arcpy.da.SearchCursor(src_fc, search_fields) as s_cur, \
     arcpy.da.InsertCursor(out_fc, insert_fields) as i_cur:
    for row in s_cur:
        geom = row[0]
        st_code = row[1]
        if geom and (st_code in CODES) and geom.getLength("GEODESIC", "METERS") < 300.0:
            # strip the subtype_field from the row when inserting (not in insert_fields)
            i_cur.insertRow([row[0]] + [row[2 + idx] for idx in range(len(copy_fields))])
            kept += 1

print("Source FC: {}".format(src_fc))
print("Used subtype codes: {}".format(CODES))
print("Output FC: {}".format(out_fc))
print("✅ Created '{}' with {} features (< 300 m from {})."
      .format(out_fc, kept, SUBTYPE_NAMES))
