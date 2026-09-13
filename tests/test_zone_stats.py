"""Assertions on bids.sqft and the zone_stats table. Run: python tests/test_zone_stats.py"""
import os, sys, sqlite3

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "site", "data", "bids.sqlite")

def check(cond, msg):
    if not cond:
        print(f"FAIL: {msg}")
        sys.exit(1)
    print(f"  ok: {msg}")

def main():
    check(os.path.isfile(DB), "bids.sqlite exists")
    conn = sqlite3.connect(DB)

    cols = {r[1] for r in conn.execute("PRAGMA table_info(bids)")}
    check("sqft" in cols, "bids has a sqft column")

    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    check("zone_stats" in tables, "zone_stats table exists")

    zcols = [r[1] for r in conn.execute("PRAGMA table_info(zone_stats)")]
    expected = (["bid", "z", "sqft"] + [f"lc{i}_sqft" for i in range(9)]
                + ["comp", "ht", "cht"])
    check(zcols == expected, f"zone_stats columns are {expected} (got {zcols})")

    # Zone indices are 0-4 only; the channel zone (5) must be excluded.
    zs = [r[0] for r in conn.execute("SELECT DISTINCT z FROM zone_stats ORDER BY z")]
    check(zs == [0, 1, 2, 3, 4], f"zone indices are 0-4 (got {zs})")

    # Measured from the existing zones table: indices 0-4 hold 89,319 rows
    # (30849 + 29505 + 27668 + 360 + 937). Most BIDs have no HMZ zone, so this
    # is well below the 5 x 30,850 upper bound.
    n_zs = conn.execute("SELECT COUNT(*) FROM zone_stats").fetchone()[0]
    check(n_zs == 89319, f"zone_stats has 89319 rows (got {n_zs})")

    # Every BID must contribute at least one scored zone, or its sqft would be 0.
    orphan = conn.execute(
        "SELECT COUNT(*) FROM bids WHERE bid NOT IN (SELECT bid FROM zone_stats)").fetchone()[0]
    check(orphan == 0, f"every BID has at least one scored zone (got {orphan} orphans)")

    # No NULL areas, and no negative areas.
    bad = conn.execute(
        "SELECT COUNT(*) FROM zone_stats WHERE sqft IS NULL OR sqft < 0").fetchone()[0]
    check(bad == 0, f"no null/negative zone sqft (got {bad})")

    bad_bid = conn.execute(
        "SELECT COUNT(*) FROM bids WHERE sqft IS NULL OR sqft <= 0").fetchone()[0]
    check(bad_bid == 0, f"no null/zero bids.sqft (got {bad_bid})")

    # bids.sqft must equal the sum of its zone areas (within float tolerance).
    drift = conn.execute("""
        SELECT COUNT(*) FROM (
          SELECT b.bid, b.sqft AS bs, SUM(s.sqft) AS zs
          FROM bids b JOIN zone_stats s ON s.bid = b.bid
          GROUP BY b.bid
          HAVING ABS(bs - zs) > 1.0
        )""").fetchone()[0]
    check(drift == 0, f"bids.sqft equals SUM(zone_stats.sqft) per BID (got {drift} mismatches)")

    # Landcover areas should sum to the zone area, but 193 of 89,319 zones fall short.
    # Cause is upstream and pre-existing: preprocess_dashboard.py maps landcover through a
    # 9-class LC_INDEX and silently drops any class outside those nine, while the zone's
    # total_sqft denominator still counts the dropped area. preprocess_dashboard.py is out
    # of scope (spec section 11), so this is tolerated, not fixed. The bound still catches a
    # real regression in our area math: if the multiplication broke, the count would jump.
    lcsum = " + ".join(f"lc{i}_sqft" for i in range(9))
    lc_bad = conn.execute(f"""
        SELECT COUNT(*) FROM zone_stats
        WHERE sqft > 0 AND ABS(({lcsum}) - sqft) > 0.02 * sqft""").fetchone()[0]
    check(lc_bad <= 200, f"landcover shortfall confined to known upstream cases (got {lc_bad}, expect 193)")

    lc_area = conn.execute(f"""
        SELECT COALESCE(SUM(sqft),0) FROM zone_stats
        WHERE sqft > 0 AND ABS(({lcsum}) - sqft) > 0.02 * sqft""").fetchone()[0]
    total_area = conn.execute("SELECT SUM(sqft) FROM zone_stats").fetchone()[0]
    pct = lc_area / total_area * 100
    check(pct < 1.0, f"affected area under 1% of total (got {pct:.3f}%)")
    print(f"  info: landcover shortfall affects {lc_bad} zones, {pct:.3f}% of area")

    # comp is a conifer-deciduous index in [-1, 1].
    c_bad = conn.execute(
        "SELECT COUNT(*) FROM zone_stats WHERE comp < -1.001 OR comp > 1.001").fetchone()[0]
    check(c_bad == 0, f"comp within [-1,1] (got {c_bad} outliers)")

    # cht: forest-area-weighted canopy height (CanopyHeight, falling back to
    # ForestHeight -- Height_for_M per preprocess_dashboard.py:349), recomputed from
    # the polygon-level source over Forest polygons only. See build_client_site.py's
    # compute_zone_canopy_height() for the three replicated upstream rules.
    #
    # It must be NULL exactly where lc0_sqft (the existing Forest-area sentinel used
    # everywhere else, e.g. the comp heatmap's "no forest" band) is 0 -- with a documented
    # handful of exceptions: a zone upstream counts as having Forest area (lc0_sqft > 0)
    # but every Forest polygon in it is missing BOTH CanopyHeight and ForestHeight, so no
    # height value exists to average. Measured at build time: 4 such zones.
    KNOWN_NO_HEIGHT_DATA_EXCEPTIONS = 4
    mismatch = conn.execute("""
        SELECT COUNT(*) FROM zone_stats
        WHERE (cht IS NULL) != (lc0_sqft IS NULL OR lc0_sqft = 0)""").fetchone()[0]
    check(mismatch <= KNOWN_NO_HEIGHT_DATA_EXCEPTIONS,
          f"cht is NULL exactly where lc0_sqft is 0, aside from up to "
          f"{KNOWN_NO_HEIGHT_DATA_EXCEPTIONS} documented no-height-data zones "
          f"(got {mismatch} mismatches)")

    cht_bounds = conn.execute(
        "SELECT MIN(cht), MAX(cht), COUNT(*) FROM zone_stats WHERE cht IS NOT NULL").fetchone()
    cht_min, cht_max, cht_n = cht_bounds
    check(cht_n > 0, "at least one zone has a non-null cht")
    # Generously wide plausibility bound (not a tight assumption): real canopy heights
    # in this watershed don't exceed ~250 ft (giant conifers) and shouldn't go far
    # negative. A handful of zones carry a small negative ForestHeight in the source
    # data itself (a pre-existing upstream data-quality artifact, not introduced by
    # this aggregation) so the floor allows for that rather than assuming 0.
    check(-10 <= cht_min and cht_max <= 250,
          f"cht values within a plausible range (got min={cht_min:.4f}, max={cht_max:.4f})")
    print(f"  info: cht range over {cht_n} populated zones: min={cht_min:.4f} ft, max={cht_max:.4f} ft")

    # Total acres sanity check for the whole watershed.
    acres = conn.execute("SELECT SUM(sqft)/43560.0 FROM bids").fetchone()[0]
    check(1000 < acres < 500000, f"total acres plausible (got {acres:,.0f})")
    print(f"  info: total riparian acres = {acres:,.0f}")

    conn.close()
    print("\nAll zone_stats checks passed.")

if __name__ == "__main__":
    main()
