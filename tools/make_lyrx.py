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
    poles = flat_map(src, "COMP_POLES")
    nf = re.search(r"NOFOREST_FILL\s*=\s*'(#[0-9A-Fa-f]{6})'\s*,\s*"
                   r"NOFOREST_STROKE\s*=\s*'(#[0-9A-Fa-f]{6})'", src)
    return {"lc": [(k, c) for k, c, _ in lc], "ramp": ramp, "poles": poles,
            "nofor": nf.group(1), "nofor_stroke": nf.group(2),
            "faint": theme["faint"], "line2": theme["line2"]}


def comp_color(v, poles):
    """Port of the page's compColor. Diverging, with |v| < 0.1 reported as Mixed:
    the ramp only reaches 20% saturation across that central band, so mixed forest
    still reads as forest rather than as a weak conifer or deciduous tint."""
    a = min(1.0, abs(v))
    if a == 0:
        return poles["mid"]
    t = a * 2 if a < 0.1 else 0.2 + 0.8 * (a - 0.1) / 0.9
    return lerp_hex(poles["mid"], poles["conifer"] if v > 0 else poles["deciduous"], t)


# Composition classes. Breaks are symmetric about the Mixed band the dashboard defines
# (|value| < 0.1); each class is coloured at its own midpoint through comp_color.
COMP_BREAKS = [
    (-0.6, "-1.00 to -0.60  strongly deciduous", -0.80),
    (-0.3, "-0.60 to -0.30  deciduous", -0.45),
    (-0.1, "-0.30 to -0.10  slightly deciduous", -0.20),
    (0.1, "-0.10 to 0.10  mixed", 0.00),
    (0.3, " 0.10 to 0.30  slightly conifer", 0.20),
    (0.6, " 0.30 to 0.60  conifer", 0.45),
    (1.0, " 0.60 to 1.00  strongly conifer", 0.80),
]


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


def composition_renderer(field, poles, nofor_hex, nofor_stroke, show_default=True):
    """Diverging graduated renderer for forest composition, -1 deciduous to +1 conifer.

    show_default=False when a definition query already excludes the null rows: keeping
    the default symbol would put a legend entry there that can never draw."""
    breaks = []
    for upper, label, mid in COMP_BREAKS:
        breaks.append({
            "type": "CIMClassBreak",
            "label": label,
            "patch": "Default",
            "symbol": poly_symbol(comp_color(mid, poles)),
            "upperBound": upper,
        })
    return {
        "type": "CIMClassBreaksRenderer",
        "barrierWeight": "High",
        "breaks": breaks,
        "classBreakType": "GraduatedColor",
        "classificationMethod": "Manual",
        "colorRamp": None,
        "field": field,
        "minimumBreak": -1.0,
        "numberFormat": {"type": "CIMNumericFormat", "alignmentOption": "esriAlignLeft",
                         "alignmentWidth": 0, "roundingOption": "esriRoundNumberOfDecimals",
                         "roundingValue": 2, "useSeparator": True},
        "showInAscendingOrder": True,
        "heading": "Composition",
        "sampleSize": 10000,
        "defaultSymbolPatch": "Default",
        "defaultSymbol": poly_symbol(nofor_hex, nofor_stroke, 0),
        # Composition is forest-only: 58% of landcover polygons have no value at all.
        "defaultLabel": "No forest composition (non-forest)",
        "polygonSymbolColorTarget": "Fill",
        "useDefaultSymbol": show_default,
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


def layer_def(fc, layer_name, renderer, template, arcpy, where=None):
    """Build one CIMFeatureLayer definition for `fc`, styled and optionally filtered."""
    tmp = os.path.join(OUT_DIR, "_tmp_layer.lyrx")   # SaveToLayerFile wants a .lyrx name
    if arcpy.Exists("mk_lyr"):
        arcpy.management.Delete("mk_lyr")
    arcpy.management.MakeFeatureLayer(fc, "mk_lyr", where or "")
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
    ld["uRI"] = "CIMPATH=Map3/%s.json" % re.sub(r"[^A-Za-z0-9_]", "_", layer_name)
    ld["renderer"] = renderer
    return ld


def wrap(doc_layers, template, out_path):
    """Write a .lyrx document around one or more layer definitions."""
    doc = {"type": "CIMLayerDocument",
           "version": template.get("version", "3.7.0"),
           "build": template.get("build", 1904),
           "layers": [doc_layers[0]["uRI"]],
           "layerDefinitions": doc_layers}
    for k in ("rGBColorProfile", "cMYKColorProfile"):
        if k in template:
            doc[k] = template[k]
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
    return out_path


def group_layer(name, children, template):
    """A CIMGroupLayer holding `children` (already-built layer definitions).

    This is what makes the two-layer TOC arrangement shippable as ONE file: the
    landcover draw and the composition draw arrive together, each with its own
    definition query, instead of having to be added and filtered by hand.
    """
    tld = template["layerDefinitions"][0]
    g = {
        "type": "CIMGroupLayer",
        "name": name,
        "uRI": "CIMPATH=Map3/%s.json" % re.sub(r"[^A-Za-z0-9_]", "_", name),
        "layerType": "Operational",
        "showLegends": True,
        "visibility": True,
        "displayCacheType": "Permanent",
        "maxDisplayCacheAge": 5,
        "layers": [c["uRI"] for c in children],
    }
    for k in ("blendingMode", "allowDrapingOnIntegratedMesh"):
        if k in tld:
            g[k] = tld[k]
    return g


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

    # Composition lives on the Landcover layer but only on forest polygons that have a
    # value. The two draws are therefore complementary, and each carries the definition
    # query that keeps them from overlapping -- the same arrangement as doing it by hand
    # in the table of contents.
    HAS_COMP = "Composition IS NOT NULL"
    NO_COMP = "Composition IS NULL"

    jobs = [
        ("RP_S_Final.lyrx", scoring, "Restoration Priority (S-curve, final)",
         class_breaks_renderer("RP_S_final", pal["ramp"]), None),
        ("Composite_Index.lyrx", scoring, "Composite Index",
         class_breaks_renderer("CI_new", pal["ramp"]), None),
        ("Area_S_Percentile.lyrx", scoring, "Area Percentile (S-curve)",
         class_breaks_renderer("RP_S_area_pctile", pal["ramp"]), None),
        ("Landcover.lyrx", landcover, "Landcover",
         unique_value_renderer("Landcover", "Landcover", lc_pairs,
                               pal["faint"], "<all other values>"), None),
        ("Landcover_no_composition.lyrx", landcover, "Landcover (no composition value)",
         unique_value_renderer("Landcover", "Landcover", lc_pairs,
                               pal["faint"], "<all other values>"), NO_COMP),
        ("Composition.lyrx", landcover, "Forest Composition",
         composition_renderer("Composition", pal["poles"],
                              pal["nofor"], pal["nofor_stroke"],
                              show_default=False), HAS_COMP),
    ]

    os.makedirs(a.out_dir, exist_ok=True)
    built = {}
    for fname, fc, name, rend, where in jobs:
        ld = layer_def(fc, name, rend, template, arcpy, where)
        p = wrap([ld], template, os.path.join(a.out_dir, fname))
        built[fname] = ld
        print("  wrote %-32s %7d bytes  <- %-12s %s"
              % (fname, os.path.getsize(p), os.path.basename(fc), where or ""))

    # One drop-in file holding both draws, in the order they belong in the TOC.
    kids = [copy.deepcopy(built["Composition.lyrx"]),
            copy.deepcopy(built["Landcover_no_composition.lyrx"])]
    grp = group_layer("Landcover + Forest Composition", kids, template)
    gpath = wrap([grp] + kids, template,
                 os.path.join(a.out_dir, "Landcover_with_Composition.lyrx"))
    print("  wrote %-32s %7d bytes  <- group of %d"
          % (os.path.basename(gpath), os.path.getsize(gpath), len(kids)))

    if skipped:
        print("  landcover classes in the palette with no features here: %s" % ", ".join(skipped))

    # Read every file back the way ArcGIS would, and report what it sees.
    print("\nverifying:")
    names = [j[0] for j in jobs] + ["Landcover_with_Composition.lyrx"]
    for fname in names:
        lf = arcpy.mp.LayerFile(os.path.join(a.out_dir, fname))
        print("  " + fname)
        for l in lf.listLayers():
            if l.isGroupLayer:
                print("      GROUP %-34s %d sublayer(s)" % (l.name, len(l.listLayers())))
                continue
            cim = l.getDefinition("V3")
            r = cim.renderer
            kind = type(r).__name__
            if kind == "CIMClassBreaksRenderer":
                detail = "field=%-18s %d classes" % (r.field, len(r.breaks))
            else:
                detail = "field=%-18s %d classes" % (list(r.fields)[0],
                                                     sum(len(g.classes) for g in r.groups))
            dq = l.definitionQuery or ""
            print("      %-34s %-22s %s" % (l.name[:34], detail, ("query: " + dq) if dq else ""))
            print("          broken: %s" % l.isBroken)


if __name__ == "__main__":
    main()
