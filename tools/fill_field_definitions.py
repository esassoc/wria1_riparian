#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Fill Alias, Description and Values in Field_Definitions.xlsx.

Sheet layout produced:  A Field Name | B Alias | C Description | D Values

Sources, in order of authority
-----------------------------
1. `RF_Test\\MD\\Attr_Dict.xlsx` - the project's original attribute dictionary. It
   covers the 60 GIS-source fields. Its "Description" column is a short label, used
   here as the Alias; its "Detail" column is folded into the Description. The script
   READS it at run time and CHECKS every alias against it, so if that dictionary is
   updated the mismatch is reported rather than silently diverging.
2. The dashboard glossary (`TERMS` in client_dashboard.html) and
   `preprocess_dashboard.py` - for the 43 derived scoring fields, which Attr_Dict
   does not cover.

Values is generated from the layer itself so it cannot drift from the data:
  * all-null field        -> "Empty - no values populated"
  * <= DOMAIN_MAX values  -> the full domain with counts
  * unique key            -> says so, with examples
  * more                  -> top 10 with counts and the share they cover
  * numeric               -> range and median
Blank counts are appended wherever they occur.

Usage:
    python tools/fill_field_definitions.py [--dry-run]
"""
import argparse
import os

import numpy as np
import pandas as pd

PROJ = r"U:\GIS\GIS\Projects\2024xxx\D202401511_WRIA_1_Riparian_Needs_Assessment"
GDB = PROJ + r"\02_DataOut\20260908_ForWebMap_final\FinalWebMap.gdb"
LAYER = "BID_Scoring"
ATTR_DICT = r"U:\GIS\temp\CS\RS\Nook\RF_Test\MD\Attr_Dict.xlsx"   # read-only upstream
DOMAIN_MAX = 12
TOP_N = 10

# Sheet field name -> layer field name, for fields renamed on publication.
RENAMED = {
    "ManagerName": "PADUS_Manager", "Name": "HUC8Name", "JURNM": "COUNTY_NM",
    "LUD": "SC_LUD", "LUD_ZONING": "SC_ZONING", "ZONING": "WC_ZONING",
    "COMPREHENS": "WC_COMP", "SiteIndex200Year": "SPHT200BID", "HMZRID": "HMZBID",
    "SpringChinook": "SpringChinookRID", "FallChinook": "FallChinookRID",
    "Coho": "CohoRID", "SummerSteelhead": "SummerSteelheadRID",
    "WinterSteelhead": "WinterSteelheadRID", "FallChum": "FallChumRID",
    "PinkOddYear": "PinkOddYearRID", "Sockeye": "SockeyeRID",
    "DollyVBullT": "DollyVBullTRID",
}

# Extra wording appended to the generated Values text, where a code needs decoding.
# 303(d) categories are quoted from the dashboard glossary.
ICAT = ("  5 = impaired, needs a cleanup plan | 4A = impaired, plan in place | "
        "2 = waters of concern.")
VALUE_NOTES = {
    "Temp305bCatCode": ICAT, "Temp305bCatCodeConcat": ICAT,
    "Fecal305bCatCode": ICAT, "Fecal305bCatCodeConcat": ICAT,
    "Sediment305bCatCode": ICAT, "temp_impaired_cat": ICAT,
    "fecal_impaired_cat": ICAT, "sediment_impaired_cat": ICAT,
    "RID": "  Prefix: AC = active channel / mainstem, T = tributary, L = lake.",
}

# Aliases that deliberately depart from Attr_Dict, with the reason. Anything NOT
# listed here that differs is reported as drift to be looked at.
ALIAS_DEPARTURES = {
    "Fish_simple": "spelling: Attr_Dict has 'prescense'",
    "StreamLengthFtRID": "spelling: Attr_Dict has 'artifical'",
    "DollyVBullTRID": "abbreviation expanded from 'Dolly VBull'",
}

_SALMON = [("SpringChinookRID", "Spring Chinook"), ("FallChinookRID", "Fall Chinook"),
           ("CohoRID", "Coho"), ("SummerSteelheadRID", "Summer Steelhead"),
           ("WinterSteelheadRID", "Winter Steelhead"), ("FallChumRID", "Fall Chum"),
           ("PinkOddYearRID", "Pink Odd Year"), ("SockeyeRID", "Sockeye"),
           ("DollyVBullTRID", "Dolly Varden / Bull Trout")]

# layer field -> (Alias, Description)
# Aliases for the 60 GIS-source fields mirror Attr_Dict's short description and are
# checked against it at run time.
FIELDS = {
    # --- identity and geometry ------------------------------------------------
    "OBJECTID": ("Object ID", "ArcGIS internal row ID. Not analytical; can change on export."),
    "Shape": ("Shape", "Bank polygon geometry."),
    "RID": ("Reach ID", "Identifier of the parent stream reach. Groups the bank polygons "
                        "that belong to one reach. The prefix encodes reach type: AC = "
                        "active channel / mainstem, T = tributary, L = lake."),
    "BID": ("Bank ID", "Identifier of this bank polygon, formed as RID_[SPLIT_SEQ]. One row "
                       "per bank; the key for joining to the dashboard and scoring tables."),
    "SPLIT_SEQ": ("Ordering of split/bank", "Order of this split within its reach, numbered "
                  "from north-east to south-west by centroid location. Used to build the BID, "
                  "and it also sets Area_Mult."),
    "PositionWaterbody": ("Relative location of split/bank", "Whether the polygon is the "
                          "waterbody portion of the split or the bank around it. Waterbody "
                          "polygons are excluded from scoring, which is why the score fields "
                          "are blank on them."),
    "ManualStatus": ("Manual Status", "Manual review flag. Not populated in this release."),
    "Shape_Length": ("Shape Length", "Polygon perimeter, feet."),
    "Shape_Area": ("Shape Area", "Polygon area, square feet."),
    "centroid_x": ("Split centroid x coordinate", "Longitude of the split centroid, decimal degrees."),
    "centroid_y": ("Split centroid y coordinate", "Latitude of the split centroid, decimal degrees."),

    # --- reach description ----------------------------------------------------
    "SourceLayer": ("Simplified feature type", "Which source hydrography the reach came from: "
                    "nooksack, tributary, lake, or other river (another major river carrying a "
                    "polygon area)."),
    "Desc_simple": ("Feature type from 3DHP", "Feature type as carried in the USGS 3D Hydrography "
                    "Program source: Stream/river and Lake/pond are polygons, flowline is a line."),
    "GNIS_NAME": ("GNIS Name from 3DHP source layer", "Official USGS Geographic Names Information "
                  "System name of the waterbody. Blank on unnamed reaches."),
    "Fish_simple": ("Simplified fish presence", "Fish use of the reach. 'fish' = known or presumed "
                    "fish presence. 'gradient' = no documented fish use, but the reach is "
                    "theoretically accessible on gradient, so it is not ruled out. Gradient "
                    "reaches are capped at priority tier P5 by access, not by riparian condition."),

    # --- watershed and administrative ----------------------------------------
    "HUC8": ("WBD Huc 8 number", "USGS Watershed Boundary Dataset 8-digit code (subbasin). Sourced from Ecology."),
    "HUC8Name": ("WBD Huc 8 name", "Name of the HUC8 subbasin. Sourced from Ecology."),
    "HUC10": ("WBD Huc 10 number", "USGS Watershed Boundary Dataset 10-digit code (watershed). Sourced from Ecology."),
    "HUC10Name": ("WBD Huc 10 name", "Name of the HUC10 watershed. Sourced from Ecology."),
    "HUC12": ("WBD Huc 12 number", "USGS Watershed Boundary Dataset 12-digit code (subwatershed). Sourced from Ecology."),
    "HUC12Name": ("WBD Huc 12 name", "Name of the HUC12 subwatershed. Sourced from Ecology."),
    "WRIA_NR": ("WRIA number", "Water Resource Inventory Area number. Sourced from Ecology."),
    "WRIA_NM": ("WRIA name", "Water Resource Inventory Area name. Sourced from Ecology."),
    "COUNTY_NM": ("County name, by majority", "County containing most of the bank's area."),
    "CITY_UGA": ("City or UGA name, by majority", "City or Urban Growth Area containing most of "
                 "the bank's area. Blank outside both."),
    "CITY_NM": ("City name, by majority", "Incorporated city containing most of the bank's area. "
                "Blank in unincorporated areas."),
    "UGA_NM": ("UGA name, by majority", "Urban Growth Area containing most of the bank's area. "
               "Blank outside any UGA."),
    "CITY_DISSOLVE": ("City, dissolved", "Incorporated city, dissolved to one name per bank. "
                      "Blank in unincorporated areas."),
    "PADUS_Manager": ("Manager Name", "Land manager code, sourced from the USGS Protected Areas "
                      "Database of the United States. Blank where land is private or unrecorded."),
    "Manager_Category": ("Manager Category", "PADUS_Manager rolled up to a broad ownership class "
                         "for reporting."),
    "SC_LUD": ("Skagit County landuse", "Skagit County land use designation. Blank outside Skagit County."),
    "SC_ZONING": ("Skagit County zoning", "Skagit County zoning code. Blank outside Skagit County."),
    "WC_ZONING": ("Whatcom County zoning", "Whatcom County zoning code."),
    "WC_COMP": ("Whatcom County land use", "Whatcom County comprehensive plan land use designation."),
    "Zoning_Group": ("Zoning Group", "County zoning rolled up to a broad land use group, used for "
                     "the dashboard's zoning breakdowns."),

    # --- channel form ---------------------------------------------------------
    "BFW_MAX_ft": ("Maximum bankfull width of stream within a reach",
                   "Widest bankfull width on the reach, feet. Taken as the greater of the 3DHP "
                   "stream/river polygon width and the modelled bankfull width (Davies et al)."),
    "BFW": ("Bankfull Width", "Bankfull width used for size classification, feet. Identical to "
            "BFW_MAX_ft on every populated row; retained as the field BFW_class derives from."),
    "BFW_class": ("Bankfull Width Class", "Stream size class from bankfull width, narrowest to "
                  "widest: Headwater/Ditch 1-3 ft, Small Stream 4-10, Medium Stream 13-30, "
                  "Large Stream 33-59, Mainstem 62+."),
    "AcChannelSqFtRID": ("Area of active channel/mainstem polygon",
                         "Area of the reach's active channel or mainstem polygon, square feet."),
    "WaterSqFtRID": ("Area of water based on modeled BFW",
                     "Water area of the reach derived from the modelled bankfull width, square feet."),
    "StreamLengthFtRID": ("Length of artificial path", "Length of the reach's artificial flow path, feet."),
    "Levees": ("Presence of levee", "Whether a mapped levee is present on the reach."),
    "HMZBID": ("Split/bank includes HMZ", "Whether the bank includes any Historic Migration Zone, "
               "the ground the channel has occupied historically."),
    "is_hmz": ("Is HMZ", "Boolean form of HMZBID, used by the dashboard."),

    # --- terrain, solar, shade ------------------------------------------------
    "SlopeMEANBID": ("Mean slope of split/bank", "Mean ground slope across the whole bank polygon, percent."),
    "SlopeMEAN50ft": ("Average slope of first 50ft of a split/bank",
                      "Mean ground slope over the first 50 ft of the bank, percent. This is the "
                      "slope the scoring uses, not SlopeMEANBID. Null on waterbody splits."),
    "SPHT200BID": ("Site Potential Tree Height", "Height a site can grow trees to in 200 years, "
                   "feet, sourced from NRCS. The reference height for a fully recovered riparian "
                   "forest. Where NRCS had no data the value was set to 100 ft."),
    "SolarAcMEAN": ("Average solar risk of the entire active channel area (if applies to reach)",
                    "Mean modelled solar risk over the whole active channel, which includes the "
                    "water area and abandoned channel areas. This is the solar input the scoring uses."),
    "SolarBfwMEAN": ("Average solar risk of water area within a reach",
                     "Mean modelled solar risk over the water area, taken as the union of the "
                     "stream/river polygon and the modelled bankfull width."),
    "ShadeAcMEAN": ("Average shade provision to entire active channel within a reach",
                    "Mean modelled shade delivered to the whole active channel, percent."),
    "ShadeBfwMEAN": ("Average shade provision to water area within a reach",
                     "Mean modelled shade delivered to the water area, percent."),
    "AspectMEANBID": ("Average aspect of split/bank",
                      "SUPERSEDED - use AspectMEANBID_new. Mean bank aspect in degrees from ArcGIS "
                      "Zonal Statistics. Aspect is circular, and a plain mean of degrees collapses "
                      "toward 180 (south); the flat-cell code of -1 was also averaged in as if it "
                      "were a direction. Negative values are that artefact."),
    "aspect_north_factor": ("Aspect North Factor", "SUPERSEDED - use aspect_north_factor_new. "
                            "cos(AspectMEANBID), so it inherits both errors above."),
    "combined_solar": ("Combined Solar", "SUPERSEDED - use combined_solar_new. SolarAcMEAN weighted "
                       "by the old aspect_north_factor."),
    "AspectMEANBID_new": ("Bank Aspect, corrected", "Corrected mean bank aspect, degrees clockwise "
                          "from north. Circular mean over the bank's sloped cells, excluding flat "
                          "and no-data cells. Blank where a bank has no sloped cells."),
    "aspect_north_factor_new": ("Aspect North Factor, corrected",
                                "Corrected north-facing factor, -1 to +1: the cell-wise mean of "
                                "cos(aspect). +1 fully north-facing, -1 fully south-facing, 0 "
                                "neutral or scattered. A north-facing bank sits on the south side "
                                "of the channel and shades the water best through midday, so it "
                                "earns the solar boost."),
    "combined_solar_new": ("Combined Solar, corrected",
                           "SolarAcMEAN weighted by the corrected north factor: "
                           "SolarAcMEAN x (1 + 0.5 x aspect_north_factor_new)."),

    # --- water quality --------------------------------------------------------
    "Waterbody305b": ("Water Quality Atlas listed waterbody name",
                      "Name of the 303(d) / 305(b) listed waterbody. Sourced from Ecology. Blank "
                      "where the reach is not listed."),
    "Temp305bCatCode": ("Category of Temperature impairment associated with the majority of the reach area",
                        "Temperature 303(d) category covering most of the reach area. Sourced from Ecology."),
    "Temp305bCatCodeConcat": ("Concatenation of all categories of Temperature impairment within a reach",
                              "Every temperature 303(d) category present on the reach, comma-joined. "
                              "Sourced from Ecology."),
    "Fecal305bCatCode": ("Category of Fecal impairment associated with the majority of the reach area",
                         "Fecal coliform 303(d) category covering most of the reach area. Sourced from Ecology."),
    "Fecal305bCatCodeConcat": ("Concatenation of all categories of Fecal impairment within a reach",
                               "Every fecal coliform 303(d) category present on the reach, comma-joined. "
                               "Sourced from Ecology."),
    "Sediment305bCatCode": ("Category of Fine Sediment impairment associated with the majority of the reach area",
                            "Fine sediment 303(d) category covering most of the reach area. Sourced from Ecology."),
    "temp_impaired": ("Temperature Impaired", "Whether the reach carries a temperature 303(d) "
                      "listing. One of the four signals behind Priority_Tier."),
    "temp_impaired_cat": ("Temperature Impairment Category", "The 303(d) category behind temp_impaired."),
    "fecal_impaired": ("Fecal Impaired", "Whether the reach carries a fecal coliform 303(d) listing."),
    "fecal_impaired_cat": ("Fecal Impairment Category", "The 303(d) category behind fecal_impaired."),
    "sediment_impaired": ("Sediment Impaired", "Whether the reach carries a fine sediment 303(d) listing."),
    "sediment_impaired_cat": ("Sediment Impairment Category", "The 303(d) category behind sediment_impaired."),
    "any_impaired": ("Any Impairment", "Whether the reach is listed for temperature, fecal coliform "
                     "or fine sediment."),

    # --- salmon ---------------------------------------------------------------
    "SR_ZoneRID": ("Salmon Recovery Zone", "Salmon recovery zone assigned to the reach."),
    "SR_Zone": ("Salmon Recovery Zone, cleaned", "Salmon recovery zone, cleaned for reporting. Also "
                "supplies the 'in the Nooksack' test used by Priority_Tier."),
    "salmon_present": ("Salmon Present", "Whether any salmon species is documented on the reach."),
    "salmon_species": ("Salmon Species", "Semicolon-separated list of the salmon species documented "
                       "on the reach."),

    # --- scoring, linear track ------------------------------------------------
    "RP_norm": ("Restoration Priority, normalized", "Restoration Priority on the linear track, "
                "0-100: how much riparian function this bank could regain if restored, higher "
                "meaning more to gain. A distance-decay weighted mean of the buffer-zone landcover "
                "scores. Condition only - it ignores how much area the bank covers."),
    "RP_area_raw": ("Restoration Priority, area-weighted raw", "Area-weighted magnitude of the "
                    "linear score: the sum over buffer zones of zone weight x zone score x zone "
                    "area. Ranks total opportunity rather than intensity, so a large bank in fair "
                    "condition can outrank a small one in poor condition. Large and unbounded."),
    "Area_Mult": ("Area Multiplier", "Multiplier applied to both area-weighted scores, looked up "
                  "from SPLIT_SEQ: 1 -> 0.5, 2 -> 1.0, 3 to 5 -> 1.25, 6 and above -> 1.4."),
    "RP_area_adjusted": ("Restoration Priority, area-weighted adjusted",
                         "RP_area_raw x Area_Mult. The multiplier is the only difference."),
    "RP_area_pctile": ("Area percentile", "Percentile rank of RP_area_adjusted against all scored "
                       "banks in WRIA 1, 0-100."),
    "solar_risk": ("Solar Risk", "Percentile rank of combined_solar against all scored banks, 0-1. "
                   "Banks with no solar value fall back to 0.5."),
    "solar_push": ("Solar Push", "Points added to the base score for solar exposure: "
                   "solar_risk x 12 x (RP_norm/100)^1.2. The exponent means an already-poor bank "
                   "gains more than a good one."),
    "RP_solar_only": ("Restoration Priority, solar only", "RP_norm plus solar_push, clipped to "
                      "0-100. Diagnostic: the solar contribution before slope and wetland."),
    "slope_risk": ("Slope Risk", "Percentile rank of SlopeMEAN50ft against all scored banks, 0-1."),
    "slope_push": ("Slope Push", "Points added for erosion risk on steep banks: "
                   "slope_risk x 5 x (RP_norm/100)^1.2."),
    "wetland_push": ("Wetland Push", "Points added for a wetland connection, 0-5, proportional to "
                     "the wetland fraction of the bank. Wetlands can discharge warm water."),
    "RP_final": ("Restoration Priority, final", "Final Restoration Priority on the linear track: "
                 "RP_norm plus the solar, slope and wetland pushes, clipped to 0-100."),

    # --- scoring, S-curve track ----------------------------------------------
    "RP_S_norm": ("Restoration Priority S-curve, normalized",
                  "Restoration Priority on the S-curve track, 0-100. Same zone weighting as "
                  "RP_norm but over S-curve zone scores, which spread the middle of the range."),
    "RP_S_area_raw": ("Restoration Priority S-curve, area-weighted raw",
                      "Area-weighted magnitude of the S-curve score; same formula as RP_area_raw."),
    "RP_S_area_adjusted": ("Restoration Priority S-curve, area-weighted adjusted",
                           "RP_S_area_raw x Area_Mult."),
    "RP_S_area_pctile": ("Area percentile, S-curve", "Percentile rank of RP_S_area_adjusted against "
                         "all scored banks, 0-100. The magnitude half of the Composite Index."),
    "RP_S_final": ("Restoration Priority S-curve, final",
                   "Final S-curve Restoration Priority, 0-100. This is the headline score the "
                   "dashboard reports as Restoration Priority."),
    "CI_new": ("Composite Index", "RP_S_final x RP_S_area_pctile / 100. Favours banks that are both "
               "in poor condition and large. Note the zone scores enter both factors, so condition "
               "is weighted twice."),
    "zone_count": ("Zone Count", "How many of the five buffer zones have scored data for this bank. "
                   "Buffer zones are distance bands from the channel: 0-50 ft, 50-100, 100-300, "
                   "HMZ, and HMZ+300."),
    "Priority_Tier": ("Priority Tier", "Priority tier P1 (highest) to P5, combining four signals: "
                      "Chinook presence, location within the Nooksack, 303(d) temperature listing, "
                      "and fish access. Among fish-bearing reaches, P1 to P4 rank by how many of the "
                      "Chinook, Nooksack and temperature signals apply. Reaches without fish access "
                      "are capped at P5 by access, not by riparian condition, so a pristine reach "
                      "above a barrier and a bare one both land in P5. Independent of the "
                      "Restoration Priority score."),
}
for _f, _label in _SALMON:
    FIELDS[_f] = (f"Presence of {_label}",
                  f"Whether {_label} is present on the reach, based on upstream distribution "
                  f"points from the Statewide Washington Integrated Fish Distribution dataset, "
                  f"with input from WarthoGIS. Reach-level, so both banks share the value.")


def load_attr_dict(path):
    """{field: (short description, detail)} from the project's original dictionary."""
    import openpyxl
    if not os.path.isfile(path):
        return {}
    ws = openpyxl.load_workbook(path, data_only=True).active
    out = {}
    for row in list(ws.iter_rows(values_only=True))[1:]:
        if row and row[0]:
            out[str(row[0]).strip()] = ((row[1] or "").strip(), (row[2] or "").strip())
    return out


def fmt_val(v):
    if isinstance(v, (bool, np.bool_)):
        return str(bool(v))
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        return str(int(v)) if float(v).is_integer() else f"{v:g}"
    s = str(v).strip()
    return s if s else "(blank string)"


def num(x):
    if abs(x) >= 1e7 or (0 < abs(x) < 1e-3):
        return f"{x:.3g}"
    return f"{int(x):,}" if float(x).is_integer() else f"{x:,.2f}"


def profile(s, n_rows):
    nn = int(s.notna().sum())
    nulls = n_rows - nn
    if nn == 0:
        return "Empty - no values populated"
    nd = int(s.nunique(dropna=True))
    tail = f"  [{nulls:,} blank]" if nulls else ""

    if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s) and nd > DOMAIN_MAX:
        q = s.dropna()
        return f"Numeric. {num(q.min())} to {num(q.max())}, median {num(q.median())}{tail}"

    vc = s.value_counts(dropna=True)
    if nd <= DOMAIN_MAX:
        body = " | ".join(f"{fmt_val(k)} ({v:,})" for k, v in vc.items())
        return f"Domain, {nd} value{'s' if nd != 1 else ''}: {body}{tail}"
    if nd == nn:
        ex = ", ".join(fmt_val(k) for k in s.dropna().head(3))
        return f"Unique identifier - {nd:,} values, no repeats. e.g. {ex}{tail}"
    top = vc.head(TOP_N)
    pct = 100 * top.sum() / nn
    cov = f"{pct:.0f}" if pct >= 10 else f"{pct:.1f}"
    body = " | ".join(f"{fmt_val(k)} ({v:,})" for k, v in top.items())
    return f"{nd:,} distinct values. Top {len(top)} = {cov}% of populated rows: {body}{tail}"


def main():
    import openpyxl
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter
    import geopandas as gpd

    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default="Field_Definitions.xlsx")
    ap.add_argument("--gdb", default=GDB)
    ap.add_argument("--layer", default=LAYER)
    ap.add_argument("--attr-dict", default=ATTR_DICT)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    df = gpd.read_file(a.gdb, layer=a.layer, engine="pyogrio", read_geometry=False)
    n_rows = len(df)
    print(f"{a.layer}: {n_rows:,} rows, {len(df.columns)} fields")

    ad = load_attr_dict(a.attr_dict)
    print(f"Attr_Dict: {len(ad)} entries from {os.path.basename(a.attr_dict)}")

    wb = openpyxl.load_workbook(a.xlsx)
    ws = wb.active

    # Insert the Alias column at B if it isn't already there.
    if str(ws.cell(1, 2).value or "").strip().lower() != "alias":
        ws.insert_cols(2)
        print("inserted a new column B for Alias")
    ws.cell(1, 1).value = "Field Name"
    ws.cell(1, 2).value = "Alias"
    ws.cell(1, 3).value = "Description"
    ws.cell(1, 4).value = "Values"

    no_def, no_data, drift = [], [], []
    for r in range(2, ws.max_row + 1):
        raw = ws.cell(r, 1).value
        if not raw:
            continue
        sheet_name = str(raw).replace(" *", "").strip()
        col = RENAMED.get(sheet_name, sheet_name)

        info = FIELDS.get(col)
        if info is None:
            no_def.append(sheet_name)
        else:
            alias, desc = info
            # Cross-check the alias against the project's own dictionary.
            if (col in ad and ad[col][0] and ad[col][0] != alias
                    and col not in ALIAS_DEPARTURES):
                drift.append((col, ad[col][0], alias))
            if col != sheet_name:
                desc += f"  (source field: {col})"
            ws.cell(r, 2).value = alias
            ws.cell(r, 3).value = desc

        if col in df.columns:
            ws.cell(r, 4).value = profile(df[col], n_rows) + VALUE_NOTES.get(col, "")
        elif sheet_name in ("OBJECTID", "Shape"):
            ws.cell(r, 4).value = ("One per feature, not analytical" if sheet_name == "OBJECTID"
                                   else f"Polygon geometry, {n_rows:,} features")
        else:
            no_data.append(sheet_name)

    for r in range(1, ws.max_row + 1):
        for c in range(1, 5):
            ws.cell(r, c).alignment = Alignment(wrap_text=(c >= 3), vertical="top")
        ws.cell(1, c).font = Font(bold=True)
    for c in range(1, 5):
        ws.cell(1, c).font = Font(bold=True)
    for letter, width in zip("ABCD", (26, 40, 78, 92)):
        ws.column_dimensions[letter].width = width
    ws.freeze_panes = "A2"

    if no_def:
        print(f"  NO DEFINITION for {len(no_def)}: {no_def}")
    if no_data:
        print(f"  NO DATA COLUMN for {len(no_data)}: {no_data}")
    if drift:
        print(f"  ALIAS DIFFERS FROM Attr_Dict for {len(drift)}:")
        for c, want, got in drift:
            print(f"     {c}: Attr_Dict {want!r} vs sheet {got!r}")
    else:
        checked = sum(1 for c in FIELDS if c in ad and ad[c][0])
        print(f"  all {checked} aliases agree with Attr_Dict, except "
              f"{len(ALIAS_DEPARTURES)} deliberate departures:")
        for c, why in ALIAS_DEPARTURES.items():
            print(f"     {c}: {why}")

    if a.dry_run:
        print("  dry run, not saving")
        return
    tmp = a.xlsx + ".tmp"
    wb.save(tmp)
    try:
        os.replace(tmp, a.xlsx)
        print(f"wrote {a.xlsx}")
    except PermissionError:
        alt = os.path.splitext(a.xlsx)[0] + "_filled.xlsx"
        os.replace(tmp, alt)
        print(f"{a.xlsx} is locked (open in Excel) -- wrote {alt} instead.\n"
              f"Close the workbook and rerun, or rename {os.path.basename(alt)} over it.")


if __name__ == "__main__":
    main()
