"""Static assertions for the visual polish pass. Run: python tests/test_visual_polish.py"""
import os, re, sys

SITE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "site")
HTML = open(os.path.join(SITE, "index.html"), encoding="utf-8").read()

def check(cond, msg):
    if not cond:
        print(f"FAIL: {msg}"); sys.exit(1)
    print(f"  ok: {msg}")

def absent(needle, msg=None):
    check(needle not in HTML, msg or f"'{needle}' absent from shipped page")

def present(needle, msg=None):
    check(needle in HTML, msg or f"'{needle}' present in shipped page")

def check_no_mojibake():
    """A JS escape written as JSX *text* (outside any string literal) ships as the literal
    six characters and renders as garbage. This has happened four times during this plan
    (middots in the header/footer, an em-dash in BID Query, guillemets in the pager), and
    it is invisible to every other check here because the page legitimately contains such
    escapes inside JS string literals. Element text content is the tell: a backslash-u run
    sitting between > and < with no quote around it."""
    bs = chr(92)
    pat = re.compile(r">[^<>\"']*" + re.escape(bs) + r"u[0-9A-Fa-f]{4}[^<>\"']*<")
    hits = [m.group(0)[:80] for m in pat.finditer(HTML)]
    check(not hits, f"no escape sequences rendered as element text (found {len(hits)}: {hits[:3]})")


def main():
    # --- Task 1: head, tokens, no dark mode ---
    present("fonts.googleapis.com/css2?family=Archivo", "Archivo loaded from Google Fonts")
    present("IBM+Plex+Sans", "IBM Plex Sans loaded"); present("IBM+Plex+Mono", "IBM Plex Mono loaded")
    present("--accent:#0F8B9F", "accent token declared")
    present("--ground:#F4F5F2", "ground token declared")
    absent("darkMode", "no Tailwind darkMode config")
    check(re.search(r"\bdark:", HTML) is None, "no dark: utility classes")
    absent(".dark body", "no .dark CSS")
    absent("{dark ? 'Light' : 'Dark'}", "no Dark/Light toggle")

    # --- Task 2: design system ---
    present("const THEME = {", "THEME object defined")
    present("const LC9 = [", "single LC9 landcover registry")
    absent("LAB_LC_FILLS = [", "old Lab landcover fills gone")
    absent("LAB_LC_TEXT", "per-class text colours gone")
    absent("COMP_RAMP", "old cream-centred composition ramp gone")
    present("function compColor(", "compColor defined")
    present("const TERMS = {", "TERMS map defined")
    # NOTE: SR_ZONE_COLORS (a colour map, contractual per the Task 2 brief and consumed
    # blindly by later tasks) must legitimately keep 'Lower NF Nooksack' as its raw key -
    # it is the stored SQL value. The abbreviation is only supposed to disappear from the
    # *display* layer, so assert the actual deliverable: SRZ_DISPLAY expands it.
    present("'Lower NF Nooksack': 'Lower North Fork Nooksack'",
            "SRZ_DISPLAY expands abbreviated SR zone names for display")
    for hexv in ("#2d6a4f", "#52b788", "#95d5b2", "#a7c957"):
        absent(hexv, f"old all-green LC colour {hexv} gone")

    # --- Task 3: shell ---
    for cp in ("\U0001F3D4", "\U0001F50E", "\U0001F4CA", "\U0001F332", "\U0001F52C", "⚡", "⬇", "\U0001F50D", "〰"):
        check(cp not in HTML, f"emoji U+{ord(cp):04X} absent")
    present("Water Resource Inventory Area", "footer glossary present")
    present("Historic Migration Zone", "HMZ expanded in glossary")
    absent("total polygons", "internal polygon counts gone from footer")
    absent("./logo.png", "no logo reference")
    present('className="tabs"', "new tab nav present")

    # --- Task 4: chart kit ---
    for fn in ("KHistogram", "KDumbbell", "KHeatmap", "KHBars", "KVBars", "KRateTiles", "KRose", "KLcStack"):
        present(f"function {fn}(", f"{fn} defined")
    for old in ("GhostHistogram", "GhostCatBars", "RPCIBars", "CompZoneLines", "LcZoneStack"):
        absent(f"function {old}(", f"{old} removed")
    present("mean: statsMean", "statsMean exported on window.__stats")

    # --- Task 5: summary stats ---
    present("function summarizeFilters(", "summarizeFilters defined")
    present("function defaultFilters(", "defaultFilters defined")
    present("function StatsSectionModifiers(", "Solar + Wetland merged into Site Modifiers")
    absent("function StatsSectionSolar(", "old Solar section gone")
    absent("function StatsSectionWetland(", "old Wetland section gone")
    present("Edit on BID Query", "edit link present on Summary Stats")
    present("WRIA baseline", "global legend chip present")
    absent("Showing all reaches &mdash;", "old em-dash note replaced")

    # --- Task 6: BID query rail ---
    present('className="bq"', "two-column BID Query layout present")
    present("Site Modifiers", "Site Modifiers filter group present")
    present("Show 3 more ranges", "range disclosure present")
    absent("Filter BIDs by multiple criteria simultaneously", "instruction banner removed")
    absent("Stream Region Zone", "SR zone renamed in filter group")
    absent("\\u26A1 Apply Filters", "emoji-free Apply button")

    # --- Task 7: map + table ---
    present("Color by tier", "map colour-by toggle present")
    absent("rgb(46,139,87)", "old green-yellow-purple RP gradient gone")
    absent("label: 'RP Final'", "table column renamed")
    absent("'Stream Region Zone'", "table column renamed to Salmon Recovery Zone")
    present("30 per page", "pager text present")

    # --- Task 8: bank explorer ---
    absent("Search for a BID by ID, stream name, or SR Zone", "Bank Explorer banner removed")
    absent("'Impaired' : 'OK'", "303(d) status reads Not listed, not OK")
    absent(">Cat {attr.", "Category spelled out in Bank Explorer")
    absent("p{pctile}", "percentile spelled out")
    present("Reach context", "reach context card present")
    present("Not listed", "303(d) wording present")

    # --- Task 9: scoring lab ---
    absent("Zone RP Contributions by Cover Type", "Lab table title uses full names")
    absent(">Sh/Wdlnd<", "Shrub/Woodland spelled out in Lab table")
    absent("Decay Wt", "Decay weight spelled out")
    absent("◀ Left Scenario", "arrow glyph headers gone")
    absent("↺ Reset", "glyph on Reset gone")
    present("Final Restoration Priority", "Final RP row renamed")

    # --- Task 9 correction: LAB_SOLAR/LAB_SLOPE are true watershed means, not range midpoints ---
    present("LAB_SOLAR = 2.77", "LAB_SOLAR set to true watershed mean solar push")
    present("LAB_SLOPE = 1.04", "LAB_SLOPE set to true watershed mean slope push")
    absent("LAB_SOLAR = 6", "old range-midpoint value for LAB_SOLAR gone")
    absent("LAB_SLOPE = 2.5", "old range-midpoint value for LAB_SLOPE gone")

    # --- Task 10: brand leaks, abbreviations, dead code, contract ---
    absent("Environmental Science Associates", "company name absent from shipped page (no ESA branding)")
    check(re.search(r"\bESA\b", HTML) is None, "standalone word 'ESA' absent from shipped page")
    for hexv in ("#1193BA", "#66CAD8", "#004562", "#002D42", "#F9A134", "#7F7B7A"):
        check(hexv.lower() not in HTML.lower(), f"ESA colour {hexv} absent")
    for word in ("Raleway", "Overpass", "Tahoma", "logo.png", "text-esa-", "accent-esa-", "esa-navy", "esa-teal"):
        absent(word, f"'{word}' absent")
    for abbr in ("SR Zone", "RP Final", "Sh/Wd", "Sh/Wdlnd", "Imperv<", "Cnpy/Imp", "Gravel/AC", "pctile", "Decay Wt", "Contrib<", "'Cat '", "p60"):
        absent(abbr, f"abbreviation '{abbr}' absent")
    for dead in ("function StatCard(", "function HistogramChart(", "function Formula(", "LAB_LC_TEXT", "CONTRIB_COLORS", "GHOST_OPACITY"):
        absent(dead, f"dead code '{dead}' removed")
    # Emoji, in BOTH forms: a literal character, and the JS escape sequence that renders at
    # runtime but survives a literal-character scan. Codepoints are numeric and the backslash
    # is built with chr(92), so no emoji and no escape ambiguity live in this file.
    # NOTE: U+25B2/U+25BC (up/down triangles) are deliberately NOT listed - they are the table
    # sort indicators and the KPI delta arrows, used on purpose in Tasks 5 and 7.
    bs = chr(92)
    for cpnum in (0x1F3D4, 0x1F50E, 0x1F4CA, 0x1F332, 0x1F52C, 0x26A1, 0x2B07, 0x1F50D, 0x3030):
        check(chr(cpnum) not in HTML, f"literal emoji U+{cpnum:04X} absent")
        esc = bs + ("u{%X}" % cpnum if cpnum > 0xFFFF else "u%04X" % cpnum)
        check(esc.lower() not in HTML.lower(),
              f"escaped emoji {esc} absent (renders at runtime, invisible to a literal scan)")
    check(HTML.count("window.open(window.location.pathname + '#bid/'") >= 1, "deep-link handler present")
    check(re.search(r"Methodology|MethodsSection|ModelReference|__db_for_test", HTML) is None, "no internal content")
    check(not os.path.isdir(os.path.join(SITE, "images")), "site/images/ does not exist")
    check(len(re.findall(r"bg-white rounded-lg shadow", HTML)) == 0, "no leftover Tailwind card recipe")

    # --- Task 11: composition heatmap fix (forest-area weighting, no-forest band) ---
    present("SUM(s.comp * s.lc0 * s.sqft)", "composition aggregate weighted by forest area (lc0 * sqft)")
    absent("SUM(s.comp * s.sqft)", "old total-area-weighted composition aggregate removed")
    present("no forest", "no-forest wording present (legend/tooltip)")

    # --- Tier disclosure / solar-push direction fixes ---
    absent("south-facing", "solar-push hover no longer names the penalised (south-facing) side")
    present("by fish access", "P5 access-cap wording present (tier hover / caption)")
    present("P1: Spring Chinook habitat in the Nooksack", "TIER_LABELS P1 mentions the Nooksack")
    present("P2: Spring Chinook habitat in the Nooksack", "TIER_LABELS P2 mentions the Nooksack")

    # --- Task 10 close-out (2026-09-13): dumbbell canonical colour, more dead code ---
    # The dumbbell's filled dot used to inherit whatever section hue its call site passed in,
    # so e.g. Tier P1 read crimson everywhere EXCEPT the "Mean Restoration Priority by tier"
    # dumbbell, where it read teal (the Restoration Metrics section hue). Approved fix:
    # thread an `attr` prop naming the CATEGORY_COLORS registry to look up per-dot, falling
    # back to the section hue only where no canonical colour exists (solar bands, wetland
    # connection, folded "Other" rows).
    absent("const CAT_COLORS = [", "dead code 'CAT_COLORS' (unused qualitative fallback array) removed")
    present("const canonicalColor = (attr, value, fallback) => {", "canonicalColor helper defined")
    present("function KDumbbell({ rows, color, height, attr })", "KDumbbell accepts an attr prop")
    present("const dotColor = canonicalColor(attr, r.rawKey ?? r.key, color)",
            "KDumbbell dot fill resolves the category's canonical colour first")
    present('fill={dotColor}', "KDumbbell filled dot uses the resolved canonical colour")
    for call in ('attr="tier"', 'attr="fish"', 'attr="tcat"', 'attr="bfw"', 'attr="srz"', 'attr="mgr"', 'attr="zon"'):
        present(f"<KDumbbell", f"KDumbbell present (context for {call})")
        check(HTML.count(call) >= 1, f"KDumbbell call site carries {call}")
    # Solar-push-band and wetland-connection dumbbells have no canonical colour registry entry
    # (approved fallback case) - they must NOT carry an attr, so they keep falling back to the
    # section hue via canonicalColor's fallback argument.
    present("<KDumbbell rows={toDumbbell(band(d.solQuint), w && band(w.solQuint))} color={S_MOD.hue} />",
            "solar-push-band dumbbell has no attr (falls back to section hue by design)")
    present("<KDumbbell rows={toDumbbell(d.wetCat, w && w.wetCat)} color={lerpHex(S_RIV.hue, '#ffffff', 0.2)} />",
            "wetland-connection dumbbell has no attr (falls back to section hue by design)")

    check_no_mojibake()
    print("\nAll visual-polish checks passed.")

if __name__ == "__main__":
    main()
