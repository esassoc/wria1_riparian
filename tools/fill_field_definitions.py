#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Fill the Description and Values columns of Field_Definitions.xlsx.

The sheet lists the published field names of FinalWebMap.gdb\\BID_Scoring; a handful
were renamed on publication, so ALIASES maps sheet name -> layer name.

Description comes from DESCRIPTIONS below (hand-written, sourced from
preprocess_dashboard.py and CLIENT_DASHBOARD_NOTES.md). Values is generated from the
layer itself so it never drifts from the data:

  * all-null field        -> "Empty - no values populated"
  * <= DOMAIN_MAX values  -> the full domain, with counts
  * more                  -> the 10 most common, with counts and the share they cover
  * numeric               -> range and median, plus blank count

Usage:
    python tools/fill_field_definitions.py [--xlsx Field_Definitions.xlsx] [--dry-run]
"""
import argparse
import os

import numpy as np
import pandas as pd

GDB = (r"U:\GIS\GIS\Projects\2024xxx\D202401511_WRIA_1_Riparian_Needs_Assessment"
       r"\02_DataOut\20260908_ForWebMap_final\FinalWebMap.gdb")
LAYER = "BID_Scoring"
DOMAIN_MAX = 12          # at or below this many distinct values, list them all
TOP_N = 10

# Sheet field name -> layer field name, for the fields renamed on publication.
ALIASES = {
    "ManagerName": "PADUS_Manager", "Name": "HUC8Name", "JURNM": "COUNTY_NM",
    "LUD": "SC_LUD", "LUD_ZONING": "SC_ZONING", "ZONING": "WC_ZONING",
    "COMPREHENS": "WC_COMP", "SiteIndex200Year": "SPHT200BID", "HMZRID": "HMZBID",
    "SpringChinook": "SpringChinookRID", "FallChinook": "FallChinookRID",
    "Coho": "CohoRID", "SummerSteelhead": "SummerSteelheadRID",
    "WinterSteelhead": "WinterSteelheadRID", "FallChum": "FallChumRID",
    "PinkOddYear": "PinkOddYearRID", "Sockeye": "SockeyeRID",
    "DollyVBullT": "DollyVBullTRID",
}

SALMON = ("Whether {} is documented anywhere on the parent reach. Reach-level, so both "
          "banks of a reach carry the same value.")

DESCRIPTIONS = {
    # --- identity and geometry -------------------------------------------------
    "OBJECTID": "ArcGIS internal row ID. Not analytical; can change on export.",
    "Shape": "Bank polygon geometry.",
    "RID": "Reach ID. Groups the bank polygons belonging to one stream reach.",
    "BID": "Bank ID, formed as RID + '_' + SPLIT_SEQ. One row per bank polygon; the key "
           "for joining to the dashboard and the scoring tables.",
    "SPLIT_SEQ": "Sequence number of this polygon within its reach. Forms the second half "
                 "of the BID and determines Area_Mult.",
    "PositionWaterbody": "Whether the polygon is riparian bank or in-channel water. "
                         "Waterbody polygons are excluded from scoring, which is why the "
                         "score fields are blank on them.",
    "ManualStatus": "Manual review flag. Not populated in this release.",
    "Shape_Length": "Polygon perimeter, feet.",
    "Shape_Area": "Polygon area, square feet.",
    "centroid_x": "Longitude of the bank centroid, decimal degrees.",
    "centroid_y": "Latitude of the bank centroid, decimal degrees.",

    # --- reach description -----------------------------------------------------
    "SourceLayer": "Which source hydrography layer the reach came from.",
    "Desc_simple": "Simplified feature type of the source reach.",
    "GNIS_NAME": "Official USGS place name of the stream. Blank on unnamed reaches.",
    "Fish_simple": "Fish access class of the reach: 'fish' where fish-bearing, "
                   "'gradient' where gradient-limited.",

    # --- watershed / admin -----------------------------------------------------
    "HUC8": "USGS 8-digit hydrologic unit code (subbasin).",
    "HUC8Name": "Name of the HUC8 subbasin.",
    "HUC10": "USGS 10-digit hydrologic unit code (watershed).",
    "HUC10Name": "Name of the HUC10 watershed.",
    "HUC12": "USGS 12-digit hydrologic unit code (subwatershed).",
    "HUC12Name": "Name of the HUC12 subwatershed.",
    "WRIA_NR": "Water Resource Inventory Area number.",
    "WRIA_NM": "Water Resource Inventory Area name.",
    "COUNTY_NM": "County the bank falls in.",
    "CITY_UGA": "City or Urban Growth Area containing the bank. Blank outside both.",
    "CITY_DISSOLVE": "Incorporated city, dissolved to one name per bank. Blank in "
                     "unincorporated areas.",
    "CITY_NM": "Incorporated city name. Blank in unincorporated areas.",
    "UGA_NM": "Urban Growth Area name. Blank outside any UGA.",
    "PADUS_Manager": "Land manager code from the USGS Protected Areas Database. Blank "
                     "where land is private or unrecorded.",
    "Manager_Category": "PADUS_Manager rolled up to a broad ownership class.",
    "SC_LUD": "Skagit County land use designation. Blank outside Skagit County.",
    "SC_ZONING": "Skagit County zoning code. Blank outside Skagit County.",
    "WC_ZONING": "Whatcom County zoning code.",
    "WC_COMP": "Whatcom County comprehensive plan designation.",
    "Zoning_Group": "County zoning rolled up to a broad land use group, used for the "
                    "dashboard's zoning breakdowns.",

    # --- channel form ----------------------------------------------------------
    "BFW_MAX_ft": "Maximum bankfull width measured on the reach, feet.",
    "BFW": "Bankfull width used for size classification, feet. Identical to BFW_MAX_ft "
           "on every populated row; kept as the field BFW_class is derived from.",
    "BFW_class": "Stream size class from bankfull width: Headwater/Ditch 1-3 ft, Small "
                 "Stream 4-10, Medium Stream 13-30, Large Stream 33-59, Mainstem 62+.",
    "AcChannelSqFtRID": "Active channel area of the reach, square feet.",
    "WaterSqFtRID": "Open water area of the reach, square feet. Equals AcChannelSqFtRID "
                    "on most reaches; the two differ on 2,439 of them.",
    "StreamLengthFtRID": "Length of the reach centerline, feet.",
    "Levees": "Whether a mapped levee is present on the reach.",
    "HMZBID": "Whether the bank intersects a mapped Historic Migration Zone.",
    "is_hmz": "Boolean form of HMZBID, used by the dashboard.",

    # --- terrain and solar -----------------------------------------------------
    "SlopeMEANBID": "Mean ground slope across the whole bank polygon, percent.",
    "SlopeMEAN50ft": "Mean ground slope within 50 ft of the channel, percent. This is the "
                     "slope the scoring uses, not SlopeMEANBID.",
    "SPHT200BID": "Site potential tree height at 200 years, feet. Used as the reference "
                  "height for a fully recovered riparian forest.",
    "SolarAcMEAN": "Mean modelled solar load reaching the active channel. Input to the "
                   "solar push.",
    "SolarBfwMEAN": "Mean modelled solar load over the bankfull channel.",
    "ShadeAcMEAN": "Mean modelled shade over the active channel, percent.",
    "ShadeBfwMEAN": "Mean modelled shade over the bankfull channel, percent.",
    "AspectMEANBID": "SUPERSEDED. Mean bank aspect in degrees from ArcGIS Zonal Statistics. "
                     "It is a linear mean of a circular quantity and it averaged the flat-cell "
                     "code of -1 as if it were a direction, so it is wrong for most banks. "
                     "Use AspectMEANBID_new. Negative values are the flat-cell artefact.",
    "aspect_north_factor": "SUPERSEDED. cos(AspectMEANBID), so it inherits both errors above. "
                           "Use aspect_north_factor_new.",
    "combined_solar": "SUPERSEDED. SolarAcMEAN weighted by the old aspect_north_factor. "
                      "Use combined_solar_new.",
    "AspectMEANBID_new": "Corrected bank aspect, degrees clockwise from north. Circular mean "
                         "of ground aspect over the bank's sloped cells, excluding flat and "
                         "no-data cells. Blank where the bank has no sloped cells.",
    "aspect_north_factor_new": "Corrected north-facing factor, -1 to +1: the cell-wise mean of "
                               "cos(aspect). +1 fully north-facing, -1 fully south-facing, 0 "
                               "neutral or scattered. This is what the solar weighting uses.",
    "combined_solar_new": "SolarAcMEAN weighted by the corrected north factor: "
                          "SolarAcMEAN x (1 + 0.5 x aspect_north_factor_new). A north-facing "
                          "bank shades the channel better, so it scores higher.",

    # --- impairment ------------------------------------------------------------
    "Waterbody305b": "Name of the 303(d) / 305(b) listed waterbody, where the reach is listed.",
    "Temp305bCatCode": "Worst temperature 303(d) category code on the reach.",
    "Temp305bCatCodeConcat": "All temperature category codes on the reach, comma-joined.",
    "Fecal305bCatCode": "Worst fecal coliform 303(d) category code on the reach.",
    "Fecal305bCatCodeConcat": "All fecal coliform category codes on the reach, comma-joined.",
    "Sediment305bCatCode": "Sediment 303(d) category code on the reach.",
    "temp_impaired": "Whether the reach is 303(d) temperature impaired (category 5 or 4A). "
                     "Feeds the priority tier.",
    "temp_impaired_cat": "Temperature impairment category behind temp_impaired.",
    "fecal_impaired": "Whether the reach is 303(d) fecal coliform impaired.",
    "fecal_impaired_cat": "Fecal coliform impairment category.",
    "sediment_impaired": "Whether the reach is 303(d) sediment impaired.",
    "sediment_impaired_cat": "Sediment impairment category.",
    "any_impaired": "Whether the reach is impaired for temperature, fecal coliform or sediment.",

    # --- salmon ----------------------------------------------------------------
    "SR_ZoneRID": "Salmon recovery zone assigned to the reach.",
    "SR_Zone": "Salmon recovery zone, cleaned. Used for the dashboard's zone breakdowns "
               "and for the Nooksack test in the priority tier.",
    "salmon_present": "Whether any salmon species is documented on the reach.",
    "salmon_species": "Semicolon-separated list of salmon species documented on the reach.",

    # --- scoring, linear track -------------------------------------------------
    "RP_norm": "Restoration Priority, linear track, 0-100. Distance-decay weighted mean of "
               "the five buffer-zone condition scores. Condition only; ignores how much area "
               "the bank covers.",
    "RP_area_raw": "Area-weighted magnitude of the linear score: the sum over buffer zones of "
                   "zone weight x zone score x zone area. Large, unbounded.",
    "Area_Mult": "Multiplier applied to both area-weighted scores, looked up from SPLIT_SEQ "
                 "(1 -> 0.5, 2 -> 1.0, 3-5 -> 1.25, 6+ -> 1.4).",
    "RP_area_adjusted": "RP_area_raw x Area_Mult. The only difference from RP_area_raw is "
                        "that multiplier.",
    "RP_area_pctile": "Percentile rank of RP_area_adjusted across all scored banks, 0-100.",
    "solar_risk": "Percentile rank of combined_solar across all scored banks, 0-1. Banks with "
                  "no solar value fall back to 0.5.",
    "solar_push": "Points added for solar exposure: solar_risk x 12 x (RP_norm/100)^1.2. The "
                  "exponent makes already-poor banks gain more.",
    "RP_solar_only": "RP_norm plus solar_push, clipped to 0-100. Diagnostic; shows the solar "
                     "contribution before slope and wetland.",
    "slope_risk": "Percentile rank of SlopeMEAN50ft across all scored banks, 0-1.",
    "slope_push": "Points added for erosion risk: slope_risk x 5 x (RP_norm/100)^1.2.",
    "wetland_push": "Points added for wetland connection, 0-5, proportional to the wetland "
                    "fraction of the bank.",
    "RP_final": "Final linear Restoration Priority: RP_norm plus the solar, slope and wetland "
                "pushes, clipped to 0-100.",

    # --- scoring, S-curve track ------------------------------------------------
    "RP_S_norm": "Restoration Priority, S-curve track, 0-100. Same zone weighting as RP_norm "
                 "but over S-curve zone scores, which spread the middle of the range.",
    "RP_S_area_raw": "Area-weighted magnitude of the S-curve score, same formula as "
                     "RP_area_raw.",
    "RP_S_area_adjusted": "RP_S_area_raw x Area_Mult.",
    "RP_S_area_pctile": "Percentile rank of RP_S_area_adjusted, 0-100. The magnitude half of "
                        "the Composite Index.",
    "RP_S_final": "Final S-curve Restoration Priority, 0-100. This is the headline score the "
                  "dashboard reports as Restoration Priority.",
    "CI_new": "Composite Index: RP_S_final x RP_S_area_pctile / 100. Combines condition with "
              "how much area is at stake, so a poor bank covering little ground ranks below a "
              "poor bank covering a lot.",
    "zone_count": "How many of the five buffer zones have scored data for this bank.",
    "Priority_Tier": "Priority tier P1 (highest) to P5. Assigned from Chinook presence, "
                     "whether the reach is in a Nooksack salmon recovery zone, fish access "
                     "and temperature impairment. First matching rule wins: P1 Chinook + "
                     "Nooksack + temperature impaired; P2 Chinook + Nooksack, or other "
                     "fish-bearing + impaired; P3 fish-bearing in Nooksack, or fish-bearing "
                     "elsewhere + impaired; P4 fish-bearing elsewhere, not impaired; P5 "
                     "gradient-accessible only. Independent of the Restoration Priority score.",
}
for _f, _label in [("SpringChinookRID", "Spring Chinook"), ("FallChinookRID", "Fall Chinook"),
                   ("CohoRID", "Coho"), ("SummerSteelheadRID", "Summer Steelhead"),
                   ("WinterSteelheadRID", "Winter Steelhead"), ("FallChumRID", "Fall Chum"),
                   ("PinkOddYearRID", "Pink salmon (odd year)"), ("SockeyeRID", "Sockeye"),
                   ("DollyVBullTRID", "Dolly Varden / Bull Trout")]:
    DESCRIPTIONS[_f] = SALMON.format(_label)


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
    ax = abs(x)
    if ax >= 1e7 or (ax < 1e-3 and ax > 0):
        return f"{x:.3g}"
    return f"{x:,.2f}".rstrip("0").rstrip(".") if not float(x).is_integer() else f"{int(x):,}"


def profile(s, n_rows):
    """Return the Values-cell text for one column."""
    nn = int(s.notna().sum())
    nulls = n_rows - nn
    if nn == 0:
        return "Empty - no values populated"
    nd = int(s.nunique(dropna=True))
    tail = f"  [{nulls:,} blank]" if nulls else ""

    numeric = pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)
    if numeric and nd > DOMAIN_MAX:
        q = s.dropna()
        return f"Numeric. {num(q.min())} to {num(q.max())}, median {num(q.median())}{tail}"

    vc = s.value_counts(dropna=True)
    if nd <= DOMAIN_MAX:
        body = " | ".join(f"{fmt_val(k)} ({v:,})" for k, v in vc.items())
        return f"Domain, {nd} value{'s' if nd != 1 else ''}: {body}{tail}"
    if nd == nn:
        # A key. A "top 10" of values that each occur once tells the reader nothing.
        ex = ", ".join(fmt_val(k) for k in s.dropna().head(3))
        return f"Unique identifier - {nd:,} values, no repeats. e.g. {ex}{tail}"
    top = vc.head(TOP_N)
    pct = 100 * top.sum() / nn
    cov = f"{pct:.0f}" if pct >= 10 else f"{pct:.1f}"
    body = " | ".join(f"{fmt_val(k)} ({v:,})" for k, v in top.items())
    return (f"{nd:,} distinct values. Top {len(top)} = {cov}% of populated rows: "
            f"{body}{tail}")


def main():
    import openpyxl
    from openpyxl.styles import Alignment, Font

    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default="Field_Definitions.xlsx")
    ap.add_argument("--gdb", default=GDB)
    ap.add_argument("--layer", default=LAYER)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    import geopandas as gpd
    df = gpd.read_file(a.gdb, layer=a.layer, engine="pyogrio", read_geometry=False)
    n_rows = len(df)
    print(f"{a.layer}: {n_rows:,} rows, {len(df.columns)} fields")

    wb = openpyxl.load_workbook(a.xlsx)
    ws = wb.active
    missing_desc, missing_data = [], []

    for r in range(2, ws.max_row + 1):
        raw = ws.cell(r, 1).value
        if not raw:
            continue
        sheet_name = str(raw).replace(" *", "").strip()
        col = ALIASES.get(sheet_name, sheet_name)

        desc = DESCRIPTIONS.get(col)
        if desc is None:
            missing_desc.append(sheet_name)
        else:
            if col != sheet_name:
                desc += f"  (source field: {col})"
            ws.cell(r, 2).value = desc

        if col in df.columns:
            ws.cell(r, 3).value = profile(df[col], n_rows)
        elif sheet_name in ("OBJECTID", "Shape"):
            ws.cell(r, 3).value = ("One per feature, not analytical" if sheet_name == "OBJECTID"
                                   else f"Polygon geometry, {n_rows:,} features")
        else:
            missing_data.append(sheet_name)

    for r in range(1, ws.max_row + 1):
        for c in (2, 3):
            ws.cell(r, c).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(r, 1).alignment = Alignment(vertical="top")
    for c in (1, 2, 3):
        ws.cell(1, c).font = Font(bold=True)
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 78
    ws.column_dimensions["C"].width = 96
    ws.freeze_panes = "A2"

    if missing_desc:
        print(f"  NO DESCRIPTION for {len(missing_desc)}: {missing_desc}")
    if missing_data:
        print(f"  NO DATA COLUMN for {len(missing_data)}: {missing_data}")
    if a.dry_run:
        print("  dry run, not saving")
        return

    # Write to a sibling temp then replace, so a half-written workbook can never
    # clobber the original. Falls back to a "_filled" copy when Excel holds a lock.
    tmp = a.xlsx + ".tmp"
    wb.save(tmp)
    try:
        os.replace(tmp, a.xlsx)
        print(f"wrote {a.xlsx}")
    except PermissionError:
        alt = os.path.splitext(a.xlsx)[0] + "_filled.xlsx"
        os.replace(tmp, alt)
        print(f"{a.xlsx} is locked (open in Excel) -- wrote {alt} instead.\n"
              f"Close the workbook and either rerun this script or rename {os.path.basename(alt)}.")


if __name__ == "__main__":
    main()
