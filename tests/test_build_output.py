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
    for rel in ["index.html", "data/dashboard_data.json", "data/bids.sqlite"]:
        check(os.path.isfile(os.path.join(SITE, rel)), f"{rel} exists")

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

    html = html_text()
    check("data/bids.sqlite" in html, "index.html fetches data/bids.sqlite")
    check("data/dashboard_data.json" in html, "index.html fetches data/dashboard_data.json")
    check("bid_explorer_data.json" not in html, "no leftover bid_explorer_data.json fetch")

    conn = sqlite3.connect(os.path.join(SITE, "data", "bids.sqlite"))
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
    db_mb = os.path.getsize(os.path.join(SITE, "data", "bids.sqlite")) / 1e6
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
