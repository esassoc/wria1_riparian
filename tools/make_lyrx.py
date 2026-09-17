#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generate ArcGIS Pro .lyrx files for the FinalWebMap hosting layers.

Writes four layer files into 02_DataOut\\20260908_ForWebMap_final\\LYRX:

    RP_S_Final.lyrx        BID_Scoring, graduated on RP_S_final
    Composite_Index.lyrx   BID_Scoring, graduated on CI_new
    Area_S_Percentile.lyrx BID_Scoring, graduated on RP_S_area_pctile
    Landcover.lyrx         Landcover, unique values on Landcover

Conventions are copied from the hand-made Zones_Waterbody.lyrx in the same folder:
CIM 3.7.0, a RELATIVE workspace (DATABASE=..\\FinalWebMap.gdb) so the folder stays
portable, fills at 65 alpha with a zero-width stroke of the same colour, and the same
layer-level flags. The example is read at run time and used as the template, so if it
is replaced these follow it.

Colours come from client_dashboard.html via tools/add_color_tab.py, so the layer files,
the dashboard and the Colors tab of Field_Definitions.xlsx cannot disagree.

Requires ArcGIS Pro's Python (arcpy) to build a correct data connection:
    "C:\\Program Files\\ArcGIS\\Pro\\bin\\Python\\Scripts\\propy.bat" tools/make_lyrx.py
"""
import argparse
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from add_color_tab import _block, flat_map, lerp_hex  # noqa: E402  (same palette source)

import re

PROJ = r"U:\GIS\GIS\Projects\2024xxx\D202401511_WRIA_1_Riparian_Needs_Assessment"
OUT_DIR = PROJ + r"\02_DataOut\20260908_ForWebMap_final\LYRX"
GDB = PROJ + r"\02_DataOut\20260908_ForWebMap_final\FinalWebMap.gdb"
TEMPLATE = os.path.join(OUT_DIR, "Zones_Waterbody.lyrx")
HTML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "client_dashboard.html")
ALPHA = 65          # matches Zones_Waterbody.lyrx

# Five equal classes over the 0-100 score range; the ramp is sampled at class midpoints.
BREAKS = [20.0, 40.0, 60.0, 80.0, 100.0]
MIDS = [10, 30, 50, 70, 90]


def rgb(hexv, alpha=ALPHA):
    h = hexv.lstrip("#")
    return [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha]


def color(hexv):
    return {"type": "CIMRGBColor",
            "colorSpace": {"type": "CIMICCColorSpace", "url": "sRGB IEC61966-2.1"},
            "values": rgb(hexv)}


def poly_symbol(hexv, stroke_hex=None, stroke_width=0):
    """Fill + stroke, shaped exactly like the example's symbols."""
    stroke = stroke_hex or hexv
    return {
        "type": "CIMSymbolReference",
        "symbol": {
            "type": "CIMPolygonSymbol",
            "symbolLayers": [
                {"type": "CIMSolidStroke", "enable": True, "capStyle": "Round",
                 "joinStyle": "Round", "lineStyle3D": "Strip", "miterLimit": 10,
                 "width": stroke_width, "height3D": 1, "anchor3D": "Center",
                 "color": color(stroke)},
                {"type": "CIMSolidFill", "enable": True, "color": color(hexv)},
            ],
            "angleAlignment": "Map",
        },
    }


def palette():
    src = open(HTML, encoding="utf-8").read()
    theme = flat_map(src, "THEME")
    lc = re.findall(r"\{\s*key:\s*'([^']+)',\s*color:\s*'(#[0-9A-Fa-f]{6})'"
                    r"(?:,\s*texture:\s*'([^']*)')?\s*\}", _block(src, "LC9"))
    ramp = [lerp_hex(theme["accentTint"], theme["ink"], m / 100.0) for m in MIDS]
    return {"lc": [(k, c) for k, c, _ in lc], "ramp": ramp,
            "faint": theme["faint"], "line2": theme["line2"]}


def class_breaks_renderer(field, ramp, label_fmt="{lo:g} - {hi:g}"):
    breaks = []
    lo = 0.0
    for hi, hexv in zip(BREAKS, ramp):
        breaks.append({
            "type": "CIMClassBreak",
            "label": label_fmt.format(lo=lo, hi=hi),
            "patch": "Default",
            "symbol": poly_symbol(hexv),
            "upperBound": hi,
        })
        lo = hi
    return {
        "type": "CIMClassBreaksRenderer",
        "barrierWeight": "High",
        "breaks": breaks,
        "classBreakType": "GraduatedColor",
        "classificationMethod": "Manual",
        "colorRamp": None,
        "field": field,
        "minimumBreak": 0.0,
        "numberFormat": {"type": "CIMNumericFormat", "alignmentOption": "esriAlignLeft",
                         "alignmentWidth": 0, "roundingOption": "esriRoundNumberOfDecimals",
                         "roundingValue": 1, "useSeparator": True},
        "showInAscendingOrder": True,
        "heading": field,
        "sampleSize": 10000,
        "defaultSymbolPatch": "Default",
        "defaultSymbol": poly_symbol("#EBEEEC", "#DDE2E0", 0.4),
        "defaultLabel": "No score (in-channel)",
        "polygonSymbolColorTarget": "Fill",
        "useDefaultSymbol": True,
        "normalizationType": "Nothing",
    }


def unique_value_renderer(field, heading, pairs, default_hex, default_label):
    return {
        "type": "CIMUniqueValueRenderer",
        "colorRamp": None,
        "defaultLabel": default_label,
        "defaultSymbol": poly_symbol(default_hex),
        "defaultSymbolPatch": "Default",
        "fields": [field],
        "groups": [{
            "type": "CIMUniqueValueGroup",
            "heading": heading,
            "classes": [{
                "type": "CIMUniqueValueClass",
                "label": key,
                "patch": "Default",
                "symbol": poly_symbol(hexv),
                "values": [{"type": "CIMUniqueValue", "fieldValues": [key]}],
                "visible": True,
            } for key, hexv in pairs],
        }],
        "useDefaultSymbol": True,
        "polygonSymbolColorTarget": "Fill",
    }


def build(out_path, fc, layer_name, renderer, template, arcpy):
    """Make a .lyrx for `fc`, then graft on the template's conventions + our renderer."""
    # SaveToLayerFile insists on a .lyrx extension, so the scratch file keeps one.
    tmp = os.path.join(os.path.dirname(out_path),
                       "_tmp_" + os.path.basename(out_path))
    if arcpy.Exists("mk_lyr"):
        arcpy.management.Delete("mk_lyr")
    arcpy.management.MakeFeatureLayer(fc, "mk_lyr")
    arcpy.management.SaveToLayerFile("mk_lyr", tmp, "ABSOLUTE")
    doc = json.load(open(tmp, encoding="utf-8-sig"))
    os.remove(tmp)

    tdoc = copy.deepcopy(template)
    tld = tdoc["layerDefinitions"][0]
    ld = doc["layerDefinitions"][0]

    # Keep arcpy's dataConnection (it knows about the Hosting feature dataset), but
    # take the template's RELATIVE workspace so the LYRX folder stays portable.
    dc = ld["featureTable"]["dataConnection"]
    dc["workspaceConnectionString"] = tld["featureTable"]["dataConnection"]["workspaceConnectionString"]
    dc["workspaceFactory"] = tld["featureTable"]["dataConnection"]["workspaceFactory"]

    for k in ("useSourceMetadata", "blendingMode", "allowDrapingOnIntegratedMesh",
              "layerType", "showLegends", "visibility", "displayCacheType",
              "maxDisplayCacheAge", "showPopups", "serviceLayerID", "refreshRate",
              "autoGenerateFeatureTemplates", "featureElevationExpression",
              "selectable", "featureCacheType", "scaleSymbols", "snappable"):
        if k in tld:
            ld[k] = tld[k]

    ld["name"] = layer_name
    ld["uRI"] = "CIMPATH=Map3/%s.json" % layer_name.replace(" ", "_")
    ld["renderer"] = renderer
    doc["layers"] = [ld["uRI"]]
    doc["version"] = template.get("version", doc.get("version"))
    doc["build"] = template.get("build", doc.get("build"))
    for k in ("rGBColorProfile", "cMYKColorProfile"):
        if k in template:
            doc[k] = template[k]

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--gdb", default=GDB)
    ap.add_argument("--template", default=TEMPLATE)
    a = ap.parse_args()

    try:
        import arcpy
    except ImportError:
        sys.exit("ABORT: needs ArcGIS Pro's Python. Run with propy.bat:\n"
                 '  "C:\\Program Files\\ArcGIS\\Pro\\bin\\Python\\Scripts\\propy.bat" '
                 "tools/make_lyrx.py")
    arcpy.env.overwriteOutput = True

    template = json.load(open(a.template, encoding="utf-8-sig"))
    print("template: %s (CIM %s)" % (os.path.basename(a.template), template.get("version")))
    pal = palette()
    print("palette:  ramp %s" % " ".join(pal["ramp"]))

    scoring = a.gdb + r"\Hosting\BID_Scoring"
    landcover = a.gdb + r"\Landcover"

    # Only symbolize landcover classes actually present, so the legend has no dead entries.
    present = {r[0] for r in arcpy.da.SearchCursor(landcover, ["Landcover"])}
    lc_pairs = [(k, c) for k, c in pal["lc"] if k in present]
    skipped = [k for k, _ in pal["lc"] if k not in present]

    jobs = [
        ("RP_S_Final.lyrx", scoring, "Restoration Priority (S-curve, final)",
         class_breaks_renderer("RP_S_final", pal["ramp"])),
        ("Composite_Index.lyrx", scoring, "Composite Index",
         class_breaks_renderer("CI_new", pal["ramp"])),
        ("Area_S_Percentile.lyrx", scoring, "Area Percentile (S-curve)",
         class_breaks_renderer("RP_S_area_pctile", pal["ramp"])),
        ("Landcover.lyrx", landcover, "Landcover",
         unique_value_renderer("Landcover", "Landcover", lc_pairs,
                               pal["faint"], "<all other values>")),
    ]

    os.makedirs(a.out_dir, exist_ok=True)
    for fname, fc, name, rend in jobs:
        p = build(os.path.join(a.out_dir, fname), fc, name, rend, template, arcpy)
        print("  wrote %-24s %7d bytes  <- %s" % (fname, os.path.getsize(p),
                                                  os.path.basename(fc)))
    if skipped:
        print("  landcover classes in the palette with no features here: %s" % ", ".join(skipped))

    # Read every file back the way ArcGIS would, and report what it sees.
    print("\nverifying:")
    for fname, _, _, _ in jobs:
        p = os.path.join(a.out_dir, fname)
        lf = arcpy.mp.LayerFile(p)
        for l in lf.listLayers():
            cim = l.getDefinition("V3")
            r = cim.renderer
            kind = type(r).__name__
            if kind == "CIMClassBreaksRenderer":
                cols = [[int(x) for x in b.symbol.symbol.symbolLayers[-1].color.values[:3]]
                        for b in r.breaks]
                print("  %-24s %-26s field=%-18s %d classes %s"
                      % (fname, kind, r.field, len(r.breaks), cols))
            else:
                n = sum(len(g.classes) for g in r.groups)
                print("  %-24s %-26s field=%-18s %d classes"
                      % (fname, kind, list(r.fields)[0], n))
            print("      source: %s | broken: %s" % (l.dataSource, l.isBroken))


if __name__ == "__main__":
    main()
