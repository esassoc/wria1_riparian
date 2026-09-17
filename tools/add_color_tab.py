#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Add (or rebuild) a "Colors" tab in Field_Definitions.xlsx.

Every colour the dashboard uses, tied to the attribute and value it belongs to, with a
painted swatch so the sheet is usable at a glance.

The palette is PARSED OUT OF client_dashboard.html rather than retyped, so this cannot
drift from what ships. The two continuous ramps (composition, and the Restoration
Priority map ramp) are regenerated in Python from the same lerp formula the page uses,
and sampled at fixed stops.

Columns: Group | Attribute / field | Value | Hex | Swatch | Notes

Usage:
    python tools/add_color_tab.py [--xlsx Field_Definitions.xlsx] [--dry-run]
"""
import argparse
import os
import re

HTML = "client_dashboard.html"
SHEET = "Colors"


# --------------------------------------------------------------------------- parsing
def _block(src, name):
    """Body of `const <name> = ...` up to its matching close bracket.

    Handles object literals, array literals and `new Set([...])` alike: it opens on
    whichever of { or [ comes first after the name and matches brackets from there.
    """
    m = re.search(r"const\s+%s\s*=\s*(?:new\s+\w+\s*\()?\s*([\{\[])" % re.escape(name), src)
    if not m:
        raise SystemExit(f"ABORT: could not find const {name} in {HTML}")
    open_ch = m.group(1)
    close_ch = "}" if open_ch == "{" else "]"
    i = m.end() - 1
    depth = 0
    for j in range(i, len(src)):
        if src[j] == open_ch:
            depth += 1
        elif src[j] == close_ch:
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    raise SystemExit(f"ABORT: unbalanced brackets reading const {name}")


PAIR = re.compile(r"""['"]?([A-Za-z0-9_ /()+.\-]+?)['"]?\s*:\s*['"](#[0-9A-Fa-f]{6})['"]""")


def flat_map(src, name):
    """{key: hex} from a flat JS object literal. Keys are stripped: the optional-quote
    group in PAIR would otherwise carry the source indentation into the key."""
    return {k.strip(): v for k, v in PAIR.findall(_block(src, name))}


def lerp_hex(a, b, t):
    """Port of the page's lerpHex. Uses floor(x + 0.5), matching JavaScript's
    Math.round (half away from zero); Python's round() is banker's rounding and
    produces an off-by-one channel on exact .5 stops."""
    import math
    A = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    B = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join("%02x" % int(math.floor(A[i] + (B[i] - A[i]) * t + 0.5))
                         for i in range(3)).upper()


def build_rows(src):
    """[(group, attribute, value, hex, note)] in sheet order."""
    theme = flat_map(src, "THEME")                      # top-level scalars only
    lc = re.findall(r"\{\s*key:\s*'([^']+)',\s*color:\s*'(#[0-9A-Fa-f]{6})'"
                    r"(?:,\s*texture:\s*'([^']*)')?\s*\}", _block(src, "LC9"))
    poles = flat_map(src, "COMP_POLES")
    tier = flat_map(src, "TIER_COLORS")
    srz = flat_map(src, "SR_ZONE_COLORS")
    mgr = flat_map(src, "MANAGER_CAT_COLORS")
    zon = flat_map(src, "ZONING_COLORS")
    bfw = flat_map(src, "BFW_COLORS")
    spp = flat_map(src, "SPECIES_COLORS")
    icat = flat_map(src, "ICAT_COLORS")
    dom = flat_map(src, "DOMAIN_COLORS")
    dom_lbl = flat_map_text(src, "DOMAIN_LABELS")
    light = set(re.findall(r"'(#[0-9A-Fa-f]{6})'", _block(src, "LIGHT_CHIP_COLORS")))
    nf = re.search(r"NOFOREST_FILL\s*=\s*'(#[0-9A-Fa-f]{6})'\s*,\s*NOFOREST_STROKE\s*=\s*'(#[0-9A-Fa-f]{6})'", src)

    SECT_NAME = {"rest": "Restoration Metrics", "fish": "Fish / Salmon", "imp": "Impairment",
                 "riv": "River Context", "adm": "Administrative", "mod": "Site Modifiers"}
    UI_NOTE = {
        "ground": "page background", "surface": "card background", "surface2": "alternate card",
        "ink": "primary text", "ink2": "secondary text", "muted": "labels, axis text",
        "faint": "the neutral 'other / no' fill used across every category",
        "line": "borders", "line2": "grid lines, and the 'No data' heatmap cell",
        "accent": "primary accent", "accentInk": "accent text", "accentTint": "accent fill",
        "accentTint2": "accent fill, stronger", "attn": "attention / warning",
        "attnTint": "attention fill", "ghost": "WRIA-wide ghost baseline series",
    }

    def lightnote(h, extra=""):
        n = "needs dark text on this fill" if h.upper() in {c.upper() for c in light} else ""
        return "; ".join(x for x in (extra, n) if x)

    rows = []
    for k, note in UI_NOTE.items():
        if k in theme:
            rows.append(("Theme / interface", "(UI)", k, theme[k], note))

    for key in SECT_NAME:
        m = re.search(r"%s:\s*\{\s*hue:\s*'(#[0-9A-Fa-f]{6})',\s*tint:\s*'(#[0-9A-Fa-f]{6})'" % key,
                      _block(src, "THEME"))
        if m:
            rows.append(("Section hues", "(Summary Stats section)", SECT_NAME[key] + " - hue", m.group(1), ""))
            rows.append(("Section hues", "(Summary Stats section)", SECT_NAME[key] + " - tint", m.group(2), "panel background"))

    for k, h in tier.items():
        rows.append(("Priority Tier", "Priority_Tier", k, h, lightnote(h)))

    for key, color, tex in lc:
        note = f"texture overlay: {tex}" if tex else ""
        rows.append(("Landcover (9 class)", "Landcover", key, color, lightnote(color, note)))

    rows.append(("Composition ramp", "Composition", "Deciduous pole (-1)", poles["deciduous"], "value -1 = all deciduous"))
    rows.append(("Composition ramp", "Composition", "Midpoint (0, Mixed)", poles["mid"], "same hex as the Forest landcover class, so mixed forest still reads as forest"))
    rows.append(("Composition ramp", "Composition", "Conifer pole (+1)", poles["conifer"], "value +1 = all conifer"))
    for v in (-1.0, -0.75, -0.5, -0.25, -0.1, 0.0, 0.1, 0.25, 0.5, 0.75, 1.0):
        a = min(1.0, abs(v))
        t = a * 2 if a < 0.1 else 0.2 + 0.8 * (a - 0.1) / 0.9
        hexv = poles["mid"] if v == 0 else lerp_hex(poles["mid"], poles["conifer"] if v > 0 else poles["deciduous"], t)
        note = "|value| < 0.1 is reported as Mixed" if abs(v) <= 0.1 else ""
        rows.append(("Composition ramp", "Composition", f"value {v:+.2f}", hexv, note))
    if nf:
        rows.append(("Composition ramp", "Composition", "No forest in zone", nf.group(1),
                     "deliberately outside the ramp and off every landcover hue"))
        rows.append(("Composition ramp", "Composition", "No forest - border", nf.group(2), ""))
    rows.append(("Composition ramp", "Composition", "No data (zone absent)", theme["line2"],
                 "distinct from 'No forest': the zone is not in the selection at all"))

    for lo, hi, attr, group in [(None, None, "SR_Zone", "Salmon Recovery Zone")]:
        for k, h in srz.items():
            rows.append((group, attr, k, h, lightnote(h)))
    for k, h in mgr.items():
        rows.append(("Manager Category", "Manager_Category", k, h, lightnote(h)))
    for k, h in zon.items():
        rows.append(("Zoning Group", "Zoning_Group", k, h, lightnote(h)))
    for k, h in bfw.items():
        rows.append(("Bankfull Width Class", "BFW_class", k, h, lightnote(h)))
    for k, h in spp.items():
        rows.append(("Salmon species", "salmon_species", k, h, lightnote(h)))
    ICAT_MEAN = {"1": "meets standards", "2": "waters of concern", "3": "insufficient data",
                 "4A": "impaired, cleanup plan in place", "4B": "impaired, other control plan",
                 "4C": "impaired, not by a pollutant", "5": "impaired, needs a cleanup plan"}
    for k, h in icat.items():
        rows.append(("303(d) category", "Temp/Fecal/Sediment 305bCatCode", k, h,
                     lightnote(h, ICAT_MEAN.get(k, ""))))

    rows.append(("Fish access", "Fish_simple", "fish", sections_hue(src, "fish"), "section hue for Fish / Salmon"))
    rows.append(("Fish access", "Fish_simple", "gradient", theme["faint"], "the neutral fill; no documented fish use"))
    rows.append(("Yes / No flags", "salmon_present, Chinook", "Y", sections_hue(src, "fish"), ""))
    rows.append(("Yes / No flags", "salmon_present, Chinook", "N", theme["faint"], ""))
    rows.append(("Yes / No flags", "is_hmz / HMZBID", "Y", sections_hue(src, "riv"), ""))
    rows.append(("Yes / No flags", "is_hmz / HMZBID", "N", theme["faint"], ""))
    rows.append(("Yes / No flags", "temp_impaired", "Temperature impaired", sections_hue(src, "imp"), ""))
    rows.append(("Yes / No flags", "temp_impaired", "Not impaired", theme["faint"], ""))

    m = re.search(r"wt:\s*\{([^}]*)\}", _block(src, "CATEGORY_COLORS"))
    if m:
        for k, h in PAIR.findall(m.group(1)):
            rows.append(("Water type", "water_type", k, h, ""))

    for k, h in dom.items():
        rows.append(("Scoring Lab domain bands", "(RP score scale)", dom_lbl.get(k, k), h,
                     lightnote(h, "not a landcover class")))

    for pct in range(0, 101, 10):
        rows.append(("Restoration Priority map ramp", "RP_S_final", f"{pct}",
                     lerp_hex(theme["accentTint"], theme["ink"], pct / 100.0),
                     "sequential single-hue ramp used by the map's Restoration Priority mode"))
    return rows


def flat_map_text(src, name):
    return {k.strip(): v for k, v in
            re.findall(r"'([^']+)':\s*'([^']*)'", _block(src, name))}


def sections_hue(src, key):
    m = re.search(r"%s:\s*\{\s*hue:\s*'(#[0-9A-Fa-f]{6})'" % key, _block(src, "THEME"))
    return m.group(1)


# --------------------------------------------------------------------------- write
def main():
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill, Border, Side

    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", default="Field_Definitions.xlsx")
    ap.add_argument("--html", default=HTML)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    src = open(a.html, encoding="utf-8").read()
    rows = build_rows(src)
    print(f"parsed {len(rows)} colour rows from {a.html}")
    bad = [r for r in rows if not re.fullmatch(r"#[0-9A-Fa-f]{6}", r[3] or "")]
    if bad:
        raise SystemExit(f"ABORT: {len(bad)} rows have a bad hex, e.g. {bad[:3]}")

    wb = openpyxl.load_workbook(a.xlsx)
    if SHEET in wb.sheetnames:
        del wb[SHEET]
        print(f"  replaced the existing {SHEET} tab")
    ws = wb.create_sheet(SHEET)

    hdr = ["Group", "Attribute / field", "Value", "Hex", "Swatch", "Notes"]
    ws.append(hdr)
    thin = Side(style="thin", color="FFBFBFBF")
    for c in range(1, len(hdr) + 1):
        ws.cell(1, c).font = Font(bold=True)

    prev = None
    for group, attr, value, hexv, note in rows:
        ws.append([group if group != prev else "", attr, value, hexv.upper(), "", note])
        r = ws.max_row
        cell = ws.cell(r, 5)
        cell.fill = PatternFill(start_color="FF" + hexv.lstrip("#").upper(),
                                end_color="FF" + hexv.lstrip("#").upper(), fill_type="solid")
        cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
        ws.cell(r, 4).font = Font(name="Consolas")
        prev = group

    for r in range(1, ws.max_row + 1):
        for c in range(1, 7):
            ws.cell(r, c).alignment = Alignment(vertical="top", wrap_text=(c == 6))
    for letter, width in zip("ABCDEF", (30, 32, 34, 11, 10, 62)):
        ws.column_dimensions[letter].width = width
    ws.freeze_panes = "A2"

    groups = []
    for g, *_ in rows:
        if g not in groups:
            groups.append(g)
    print("  groups: " + ", ".join(f"{g} ({sum(1 for r in rows if r[0] == g)})" for g in groups))

    if a.dry_run:
        print("  dry run, not saving")
        return
    tmp = a.xlsx + ".tmp"
    wb.save(tmp)
    try:
        os.replace(tmp, a.xlsx)
        print(f"wrote {a.xlsx} (tabs: {', '.join(wb.sheetnames)})")
    except PermissionError:
        alt = os.path.splitext(a.xlsx)[0] + "_filled.xlsx"
        os.replace(tmp, alt)
        print(f"{a.xlsx} is locked (open in Excel) -- wrote {alt} instead.")


if __name__ == "__main__":
    main()
