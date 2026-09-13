"""Assertions on the built client site. Run: python tests/test_build_output.py"""
import os, sys, csv, sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
FISH_OVERRIDE_CSV = os.path.join(ROOT, "data_overrides", "fish_access_override.csv")

def check(cond, msg):
    if not cond:
        print(f"FAIL: {msg}")
        sys.exit(1)
    print(f"  ok: {msg}")

def html_text():
    return open(os.path.join(SITE, "index.html"), encoding="utf-8").read()


def main():
    check(os.path.isdir(SITE), "site/ exists")
    import glob, re as _re
    check(os.path.isfile(os.path.join(SITE, "index.html")), "index.html exists")
    gz_files = glob.glob(os.path.join(SITE, "data", "bids.*.sqlite.gz"))
    check(len(gz_files) == 1, f"exactly one hashed bids.<hash>.sqlite.gz ships (found {gz_files})")
    check(not os.path.isfile(os.path.join(SITE, "data", "bids.sqlite")), "no raw bids.sqlite ships")
    gz_name = os.path.basename(gz_files[0])
    check(_re.fullmatch(r"bids\.[0-9a-f]{8}\.sqlite\.gz", gz_name), f"hashed name pattern ok ({gz_name})")

    with open(gz_files[0], "rb") as g:
        hdr = g.read(10)
    check(hdr[:2] == b"\x1f\x8b" and hdr[4:8] == b"\x00\x00\x00\x00",
          "gzip header MTIME is zero (deterministic bytes -> stable content hash)")

    gz_mb = os.path.getsize(gz_files[0]) / 1e6
    check(gz_mb < 7, f"gzipped DB under 7 MB (got {gz_mb:.2f} MB)")
    check(not os.path.isfile(os.path.join(SITE, "data", "dashboard_data.json")),
          "dashboard_data.json no longer ships (folded into the SQLite)")

    # Internal methodology figures belonged to the deleted Methodology tab and must
    # not be published to a client-facing URL (spec section 3).
    check(not os.path.isdir(os.path.join(SITE, "images")), "no images/ dir - the client site ships no images")
    check(not os.path.isdir(os.path.join(SITE, "js")),
          "no js/ dir - methods_citations.js is unreferenced after the panel cut")
    check("methods_citations" not in html_text(),
          "no methods_citations.js script tag in index.html")
    check("preprocess_dashboard.py" not in html_text(),
          "no internal build instructions leaked into the shipped page")
    check("react.development" not in html_text(),
          "React production build is used, not development")

    # --- Task 5: JSX and Tailwind are compiled at build time, not in the browser ---
    _shipped = html_text()
    check('type="text/babel"' not in _shipped, "shipped page has no in-browser Babel script block")
    check("babel.min.js" not in _shipped and "@babel/standalone" not in _shipped,
          "shipped page does not load Babel")
    check("cdn.tailwindcss.com" not in _shipped, "shipped page does not load the Tailwind runtime")
    check("tailwind.config" not in _shipped, "no inline tailwind.config in shipped page")
    check('<style id="tw">' in _shipped, "static Tailwind stylesheet inlined")
    check(".grid-cols-5{" in _shipped or ".grid-cols-5 {" in _shipped,
          "static stylesheet contains a utility the page uses")
    check(r".lg\:grid-cols-4{" in _shipped or r".lg\:grid-cols-4 {" in _shipped,
          "static stylesheet contains the responsive-variant utility the page uses")
    check("React.createElement(" in _shipped, "JSX compiled to React.createElement calls")
    _compiled = _shipped.split('<script>\n', 1)[-1].rsplit('\n</script>', 1)[0]
    check(_shipped.count('<script>\n') == 1 and "</script" not in _compiled,
          "compiled JS carries no stray </script> that would truncate the block")

    html = html_text()
    check(f"const DB_URL = 'data/{gz_name}'" in html, "DB_URL points at the hashed gz file")
    check(f'<link rel="preload" as="fetch" href="data/{gz_name}" crossorigin>' in html, "DB is preloaded")
    check('sql-wasm.wasm" crossorigin>' in html, "sql.js wasm is preloaded")
    check("DecompressionStream" in html, "page decompresses with DecompressionStream")
    check("data/bids.sqlite.gz'" not in html.replace(f"data/{gz_name}", ""), "no un-hashed gz reference remains")
    check("bid_explorer_data.json" not in html, "no leftover bid_explorer_data.json fetch")
    check("dashboard_data.json" not in html, "no dashboard_data.json fetch in the page")
    check("Date.now()" not in html, "no Date.now() cache-buster on data fetches")

    import gzip, tempfile
    tmp_db = os.path.join(tempfile.gettempdir(), "bids_test_unpacked.sqlite")
    with gzip.open(gz_files[0], "rb") as g, open(tmp_db, "wb") as out:
        out.write(g.read())
    conn = sqlite3.connect(tmp_db)
    n = conn.execute("SELECT COUNT(*) FROM bids").fetchone()[0]
    check(n == 30850, f"bids table has 30850 rows (got {n})")

    # S-track score-integrity columns (rpsn/sols/slps): must exist, be fully
    # populated, and the score-card arithmetic must close against rpsf.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(bids)").fetchall()}
    for c in ("rpsn", "sols", "slps"):
        check(c in cols, f"bids table has column {c}")

    non_null = conn.execute(
        "SELECT COUNT(*) FROM bids WHERE rpsn IS NOT NULL AND sols IS NOT NULL AND slps IS NOT NULL"
    ).fetchone()[0]
    check(non_null == 30850, f"rpsn/sols/slps are non-null on all 30850 rows (got {non_null})")

    for c in ("rp", "rpf", "sol", "slp", "rpa"):
        check(c not in cols, f"legacy linear column {c} is gone from bids")
    idx = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")]
    check(idx == [], f"no secondary indexes ship (found {idx})")
    long_dp = conn.execute(
        "SELECT COUNT(*) FROM bids WHERE ROUND(sols, 3) != sols OR ROUND(slps, 3) != slps").fetchone()[0]
    check(long_dp == 0, f"sols/slps rounded to 3 dp (got {long_dp} rows with more)")
    db_mb = os.path.getsize(tmp_db) / 1e6
    check(db_mb < 22, f"bids.sqlite under 22 MB raw (got {db_mb:.1f} MB)")

    rows = conn.execute("SELECT bid, rpsn, sols, slps, wet, rpsf FROM bids").fetchall()
    checked = 0
    worst_dev = 0.0
    bad = []
    for bid, rpsn, sols, slps, wet, rpsf in rows:
        total = rpsn + sols + slps + wet
        dev = abs(total - rpsf)
        checked += 1
        worst_dev = max(worst_dev, dev)
        clipped = total > 100 and abs(rpsf - 100) < 1e-6
        if dev > 0.05 and not clipped:
            bad.append((bid, total, rpsf, dev))
    print(f"  arithmetic check: {checked} rows checked, worst deviation {worst_dev:.4f}")
    check(not bad, f"rpsn+sols+slps+wet ~= rpsf on every row (first failures: {bad[:5]})")

    # --- Fix 1: fish-access override file exists, has the expected row count,
    # and every listed BID's `fish` in bids.sqlite matches the GIS value ---
    check(os.path.isfile(FISH_OVERRIDE_CSV), "data_overrides/fish_access_override.csv exists")
    with open(FISH_OVERRIDE_CSV, encoding="utf-8") as f:
        data_lines = [line for line in f if not line.startswith("#")]
    override_rows = list(csv.DictReader(data_lines))
    check(len(override_rows) == 104,
          f"fish_access_override.csv has 104 rows (got {len(override_rows)})")

    mismatches = []
    for row in override_rows:
        bid, fish_gis = row["bid"], row["fish_gis"]
        actual = conn.execute("SELECT fish FROM bids WHERE bid = ?", (bid,)).fetchone()
        if actual is None or actual[0] != fish_gis:
            mismatches.append((bid, fish_gis, actual))
    check(not mismatches,
          f"bids.fish matches the GIS override value for every listed BID "
          f"(first mismatches: {mismatches[:5]})")

    # --- Fix 1: recomputed tier counts match the corrected ("After") figures ---
    expected_tiers = {"P1": 670, "P2": 2652, "P3": 6989, "P4": 2954, "P5": 17585}
    actual_tiers = dict(conn.execute("SELECT tier, COUNT(*) FROM bids GROUP BY tier").fetchall())
    check(actual_tiers == expected_tiers,
          f"tier counts match corrected figures {expected_tiers} (got {actual_tiers})")

    # --- Task 3: Lab sample + solar percentiles live in the DB ---
    n_lab = conn.execute("SELECT COUNT(*) FROM lab_sample WHERE domain = 'D1_Forest'").fetchone()[0]
    check(n_lab == 3371, f"lab_sample has the 3371 D1_Forest sample polygons (got {n_lab})")
    import json as _json
    sps = _json.loads(conn.execute("SELECT value FROM lab_meta WHERE key = 'solar_push_stats'").fetchone()[0])
    for k in ("count", "mean", "std", "min", "p10", "p25", "p50", "p75", "p90", "max"):
        check(k in sps, f"solar_push_stats has {k}")
    check(sps["count"] == 30850, "solar_push_stats computed over all 30850 banks")
    mean_sols = conn.execute("SELECT AVG(sols) FROM bids").fetchone()[0]
    check(abs(sps["mean"] - mean_sols) < 0.001, f"solar_push_stats.mean matches AVG(sols) ({sps['mean']} vs {mean_sols:.4f})")
    check(sps["min"] <= sps["p50"] <= sps["max"], "solar percentiles are ordered")

    bad_meta = []
    for k, v in conn.execute("SELECT key, value FROM lab_meta"):
        try:
            _json.loads(v)
        except Exception:
            bad_meta.append(k)
    check(not bad_meta, f"every lab_meta.value is valid JSON (bad: {bad_meta})")
    keys = {r[0] for r in conn.execute("SELECT key FROM lab_meta")}
    check({"solar_push_stats", "generated", "source_meta"} <= keys, f"lab_meta has the three expected keys (got {sorted(keys)})")

    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("bcs", os.path.join(ROOT, "build_client_site.py"))
    _bcs = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_bcs)
    expected_gen = _bcs.derive_generated_stamp(_bcs.BID_JSON, _bcs.MAIN_JSON)
    gen = _json.loads(conn.execute("SELECT value FROM lab_meta WHERE key='generated'").fetchone()[0])
    check(gen == expected_gen,
          f"lab_meta.generated equals the input-derived stamp ({gen} vs expected {expected_gen}); "
          "a wall-clock value would differ")

    # --- Fix 2: waterbody_bids retains the 4 previously-dropped BIDs ---
    for bid in ("L667_2", "L677_2", "L684_1", "L105_2"):
        row = conn.execute("SELECT bid FROM waterbody_bids WHERE bid = ?", (bid,)).fetchone()
        check(row is not None, f"waterbody_bids retains previously-dropped BID {bid}")
    wb_count = conn.execute("SELECT COUNT(*) FROM waterbody_bids").fetchone()[0]
    check(wb_count == 1224, f"waterbody_bids has 1224 rows (got {wb_count})")

    # --- Fix 3: no negative canopy heights ship ---
    cht_min = conn.execute("SELECT MIN(cht) FROM zones WHERE cht IS NOT NULL").fetchone()[0]
    check(cht_min >= 0, f"zones.cht has no negative values (min={cht_min})")

    conn.close()
    print("\nAll build-output checks passed.")

if __name__ == "__main__":
    main()
