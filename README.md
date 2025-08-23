# TCPL ArcMap Utilities

A small collection of ArcMap 10.x/ArcPy utilities to help you extract specific features from your geodatabase and analyze proximity between transportation lines.

> **Tested with:** ArcMap 10.x (ArcGIS Desktop)  
> **Language:** Python 2.7/ArcPy (ArcGIS Desktop runtime)  
> **Output location:** By default, each script writes its output *next to* the source feature class (same geodatabase / feature dataset).

---

## Table of Contents
- [Requirements](#requirements)
- [Getting Started](#getting-started)
- [Data Assumptions](#data-assumptions)
- [Scripts](#scripts)
  - [1) `Road_less_300.py`](#1-road_less_300py)
  - [2) `River_less_300.py`](#2-river_less_300py)
  - [3) `Road_gap_all_less.py`](#3-road_gap_all_lesspy)
- [Troubleshooting & Tips](#troubleshooting--tips)
- [FAQ](#faq)
- [License](#license)

---

## Requirements

- **ArcGIS Desktop (ArcMap 10.x)** with ArcPy available.
- Read/write access to the geodatabase(s) containing your layers.
- Your target layers exist in the current ArcMap document and are named as expected (configurable at the top of each script).

---

## Getting Started

1. Open your **MXD** in ArcMap.
2. Ensure the required layer exists in the Table of Contents (TOC) with the expected name:
   - Transportation: `TransportationGroundCurves`
   - Hydrography: `HydrographyCurves`
3. Open the **Python Window** in ArcMap or run the script from a custom toolbox tool.
4. (Optional) Edit the configuration constants at the top of each script (e.g., `LAYER_NAME`, `SUBTYPE_NAMES`, `FALLBACK_CODES`, thresholds).
5. Run the script. On success, the output feature class will be created in the **same container** as the source (e.g., the same feature dataset or the root of the source geodatabase).

---

## Data Assumptions

- Datasets are **polyline** feature classes with valid geometries.
- Feature classes use subtypes with names like `ROAD_C`, `CART_TRACK_C`, `TRAIL_C` (transportation) and `RIVER_C`, `DITCH_C` (hydro).
- Subtype codes are resolved by name when possible; one or more **fallback numeric codes** can be provided in each script.
- Length checks use **GEODESIC meters** (for the `< 300 m` filters) unless otherwise noted in the script comments.

---

## Scripts

### 1) `Road_less_300.py`

**What it does**  
Copies **roads, cart tracks, and trails** whose **geodesic length is < 300 m** from `TransportationGroundCurves` into a single output feature class named **`road_less_300`**. Subtype codes are resolved automatically from names (`ROAD_C`, `CART_TRACK_C`, `TRAIL_C`) with optional fallbacks.  

**Inputs**
- Layer (in current MXD): `TransportationGroundCurves` (configurable)
- Subtype names: `["ROAD_C", "CART_TRACK_C", "TRAIL_C"]` (configurable)
- Optional fallback codes: e.g., `[100152]` for `ROAD_C`

**Output**
- New feature class: `road_less_300` (created beside the source, schema copied from the input; M/Z preserved)

**How it works (under the hood)**
- Resolves subtype codes from names using `arcpy.da.ListSubtypes` (falls back to numeric codes if needed).
- Creates an empty output using the **input schema** and a compatible spatial reference.
- Iterates the input features, and inserts those whose **GEODESIC length** is `< 300.0` meters **and** whose subtype is in the accepted set.

**How to use**
1. Open your map containing `TransportationGroundCurves`.
2. If needed, edit `SUBTYPE_NAMES` / `FALLBACK_CODES` at the file top.
3. Run the script in ArcMap's Python Window.
4. Load/use `road_less_300` from your geodatabase.

**Customize**
- Change the input layer name via `LAYER_NAME`.
- Add/remove subtypes in `SUBTYPE_NAMES` or supply numeric codes in `FALLBACK_CODES`.
- Adjust the length threshold inside the main loop (`< 300.0`).

---

### 2) `River_less_300.py`

**What it does**  
Copies **river/ditch** polylines **shorter than 300 m** from `HydrographyCurves` into an output feature class named **`river_less_300`**. Subtype names default to `["RIVER_C", "DITCH_C"]` with optional fallback codes.  

**Inputs**
- Layer (in current MXD): `HydrographyCurves` (configurable)
- Subtype names: `["RIVER_C", "DITCH_C"]` (configurable)
- Optional fallback codes: e.g., `[100314]`

**Output**
- New feature class: `river_less_300` (created beside the source, schema copied from the input; M/Z preserved)

**How it works (under the hood)**
- Same pattern as `Road_less_300.py`: resolve subtype codes, create output with matching schema, copy only features whose **GEODESIC** length is `< 300.0` meters and whose subtype matches.

**How to use**
1. Open your map containing `HydrographyCurves`.
2. Edit `SUBTYPE_NAMES` / `FALLBACK_CODES` if your subtype configuration differs.
3. Run the script in ArcMap's Python Window.
4. Load/use `river_less_300` from your geodatabase.

**Customize**
- Change `LAYER_NAME` (e.g., if your hydro layer has a different TOC name).
- Adjust subtype filters and the `< 300 m` threshold.

---

### 3) `Road_gap_all_less.py`

**What it does**  
Finds **transportation lines** (roads, trails, cart tracks) whose **nearest neighbor is within ~200 m**, and writes the kept features to **`road_gap_less_200`**. It treats the accepted subtypes as one combined set and includes:  
- **Mutual pairs** (A is within 200 m of B **and** B within 200 m of A), and  
- **One‑sided** pairs (only one is within 200 m of the other).

**Inputs**
- Layer (in current MXD): `TransportationGroundCurves` (configurable)
- Primary subtype name: `"ROAD_C"` with fallback code `100152`
- Extra subtype numeric codes: `[100156, 100150]` (e.g., `TRAIL_C`, `CART_TRACK_C`)
- Radius: `200.0` meters (+ small epsilon buffer for robustness)

**Output**
- New feature class: `road_gap_less_200` (auto-added to the map on success)

**How it works (under the hood)**
- Resolves the road subtype code; merges with `EXTRA_CODES` to form one accepted set.
- Picks a **metric spatial reference** (prefers projected meters; otherwise chooses a UTM zone by centroid) and **projects** the geometry for buffering/within tests.
- Builds a 200 m buffer for each accepted feature, then does **pairwise tests** to collect features in either **mutual** or **one‑sided** “within buffer” relationships.
- Writes the union of those kept sets to the output and adds it to the map.

**How to use**
1. Open your map containing `TransportationGroundCurves`.
2. Optionally adjust `EXTRA_CODES`, `RADIUS_M`, and `OUT_NAME`.
3. Run the script in ArcMap's Python Window.
4. The output `road_gap_less_200` will appear in your TOC.

**Customize**
- Change accepted subtypes (by name or code).
- Change radius to suit your definition of “nearby.”
- Swap the proximity logic from `within(buffer)` to other spatial predicates if needed.

---

## Troubleshooting & Tips

- **Layer not found**: Check `LAYER_NAME` matches the TOC exactly, or use the partial‑match behavior already in the helper (scripts attempt `"*name*"` fallback).  
- **Subtype code resolution fails**: Make sure the feature class uses subtypes and that the names in `SUBTYPE_NAMES` match exactly (case‑insensitive). Provide numeric codes in `FALLBACK_CODES` if needed.
- **`ERROR 000732` / missing in_memory tables**: These scripts avoid in‑memory temp tables; if you see this from another run, re‑run the script fresh or restart ArcMap.
- **Unknown spatial reference**: Scripts try to use the container’s SR or the source’s SR; if still unknown, ensure your data has a defined SR.
- **Performance**: `Road_gap_all_less.py` does pairwise checks. For very large datasets consider pre‑filtering by extent, subtype, or using spatial indexing/near‑table workflows to reduce pairs.

---

## FAQ

**Q: Where do the outputs go?**  
A: In the **same geodatabase/feature dataset** as the source feature class. Output names: `road_less_300`, `river_less_300`, `road_gap_less_200` (configurable).

**Q: Can I change the length/proximity thresholds?**  
A: Yes. Update the numeric checks (e.g., `< 300.0`) or `RADIUS_M` in the scripts.

**Q: My subtype names are different**  
A: Edit `SUBTYPE_NAMES` (or `EXTRA_CODES`) to match your schema. You can also supply numeric fallback subtype codes.

**Q: Will the output keep all my input attributes?**  
A: Yes—each script creates the output using the input as a **template** and copies over editable, compatible fields.

---

## License

Add your preferred license here (e.g., MIT).

---

## Credits

Built for quick line‑feature filtering and proximity analysis in ArcMap/ArcPy.
