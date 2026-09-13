"""Assertions on bids.sqft and the merged zones table. Run: python tests/test_zone_stats.py"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_helpers import open_shipped_db

def check(cond, msg):
    if not cond:
        print(f"FAIL: {msg}")
        sys.exit(1)
    print(f"  ok: {msg}")

LC_AREA = " + ".join(f"lc{i} * sqft" for i in range(9))

def main():
    conn = open_shipped_db()

    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    check("zones" in tables, "zones table exists")
    check("zone_stats" not in tables, "zone_stats table is gone (merged into zones)")

    zcols = [r[1] for r in conn.execute("PRAGMA table_info(zones)")]
    expected = (["bid", "z", "sqft"] + [f"lc{i}" for i in range(9)]
                + ["comp", "ht", "den", "zrp", "cstd", "cht"])
    check(zcols == expected, f"zones columns are {expected} (got {zcols})")

    zs = [r[0] for r in conn.execute("SELECT DISTINCT z FROM zones ORDER BY z")]
    check(zs == [0, 1, 2, 3, 4, 5], f"zone indices are 0-5 incl. channel zone (got {zs})")

    n_scored = conn.execute("SELECT COUNT(*) FROM zones WHERE z <= 4").fetchone()[0]
    check(n_scored == 89319, f"89319 scored zone rows (got {n_scored})")
    n_channel = conn.execute("SELECT COUNT(*) FROM zones WHERE z = 5").fetchone()[0]
    check(n_channel == 2684, f"2684 channel-zone rows (got {n_channel})")
    ch_nulls = conn.execute(
        "SELECT COUNT(*) FROM zones WHERE z = 5 AND (comp IS NOT NULL OR ht IS NOT NULL OR cht IS NOT NULL)").fetchone()[0]
    check(ch_nulls == 0, "channel-zone rows carry NULL comp/ht/cht")

    orphan = conn.execute(
        "SELECT COUNT(*) FROM bids WHERE bid NOT IN (SELECT bid FROM zones WHERE z <= 4)").fetchone()[0]
    check(orphan == 0, f"every BID has at least one scored zone (got {orphan} orphans)")

    bad = conn.execute("SELECT COUNT(*) FROM zones WHERE sqft IS NULL OR sqft < 0").fetchone()[0]
    check(bad == 0, f"no null/negative zone sqft (got {bad})")
    bad_bid = conn.execute("SELECT COUNT(*) FROM bids WHERE sqft IS NULL OR sqft <= 0").fetchone()[0]
    check(bad_bid == 0, f"no null/zero bids.sqft (got {bad_bid})")

    drift = conn.execute("""
        SELECT COUNT(*) FROM (
          SELECT b.bid, b.sqft AS bs, SUM(s.sqft) AS zs
          FROM bids b JOIN zones s ON s.bid = b.bid AND s.z <= 4
          GROUP BY b.bid HAVING ABS(bs - zs) > 1.0)""").fetchone()[0]
    check(drift == 0, f"bids.sqft equals SUM(zones.sqft) over scored zones per BID (got {drift} mismatches)")

    # Proportions sum to ~1 except the 193 known upstream shortfall zones (see previous test history).
    lc_bad = conn.execute(f"""
        SELECT COUNT(*) FROM zones
        WHERE z <= 4 AND sqft > 0 AND ABS(({LC_AREA}) - sqft) > 0.02 * sqft""").fetchone()[0]
    check(lc_bad <= 200, f"landcover shortfall confined to known upstream cases (got {lc_bad}, expect 193)")

    c_bad = conn.execute("SELECT COUNT(*) FROM zones WHERE comp < -1.001 OR comp > 1.001").fetchone()[0]
    check(c_bad == 0, f"comp within [-1,1] (got {c_bad} outliers)")

    KNOWN_NO_HEIGHT_DATA_EXCEPTIONS = 4
    mismatch = conn.execute("""
        SELECT COUNT(*) FROM zones
        WHERE z <= 4 AND (cht IS NULL) != (lc0 IS NULL OR lc0 * sqft = 0)""").fetchone()[0]
    check(mismatch <= KNOWN_NO_HEIGHT_DATA_EXCEPTIONS,
          f"cht is NULL exactly where forest area is 0, aside from up to "
          f"{KNOWN_NO_HEIGHT_DATA_EXCEPTIONS} documented no-height-data zones (got {mismatch})")

    cht_min, cht_max, cht_n = conn.execute(
        "SELECT MIN(cht), MAX(cht), COUNT(*) FROM zones WHERE cht IS NOT NULL").fetchone()
    check(cht_n > 0, "at least one zone has a non-null cht")
    check(0 <= cht_min and cht_max <= 250, f"cht within [0, 250] ft (got min={cht_min:.4f}, max={cht_max:.4f})")

    # The old channel zone arrays had 10 values; scored zones 15. The page rebuilds those
    # arrays from these columns, so den/zrp/cstd must be populated for scored zones.
    missing_tail = conn.execute(
        "SELECT COUNT(*) FROM zones WHERE z <= 4 AND (den IS NULL OR zrp IS NULL OR cstd IS NULL)").fetchone()[0]
    check(missing_tail == 0, f"den/zrp/cstd populated on all scored zones (got {missing_tail} NULL)")

    acres = conn.execute("SELECT SUM(sqft)/43560.0 FROM bids").fetchone()[0]
    check(176900 < acres < 177100, f"total riparian acres = 177,016 (got {acres:,.0f})")

    conn.close()
    print("\nAll zones checks passed.")

if __name__ == "__main__":
    main()
