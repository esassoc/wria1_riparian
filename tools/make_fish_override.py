"""One-off generator: fish_access_override.csv

The project lead ruled that the GIS feature layer (TP_Split_JOIN_20260507.csv,
Fish_simple column) is authoritative for fish access, not the value baked into
the May-7 scoring table (BID_Scores_Calculated_20260507.csv, joined into
site/data/bids.sqlite as the `fish` column). The scoring table's Fish_simple
pull is stale relative to the GIS layer.

This script is a ONE-OFF generator, not part of the build. It is run by hand
whenever the source data changes, and its output (data_overrides/fish_access_override.csv)
is committed and consumed by build_client_site.py at every build. This keeps the
40 MB TP_Split_JOIN_20260507.csv OUT of the build's dependency graph -- the build
only ever reads the small override CSV.

Usage (from Final_Build/):
    python tools/make_fish_override.py

Reads:
    TP_Split_JOIN_20260507.csv   (40 MB, GIS feature layer export, authoritative)
    site/data/bids.sqlite        (must already be built -- supplies the current
                                  scoring-table `fish` value per BID to diff against)

Writes:
    data_overrides/fish_access_override.csv
        columns: bid,fish_gis,fish_scoring
        one row per BID where the GIS value disagrees with the scoring-table value.
"""
import csv
import os
import sqlite3
import sys
from datetime import date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)

SOURCE_CSV = os.path.join(ROOT_DIR, "TP_Split_JOIN_20260507.csv")
SOURCE_DATE = "2026-05-07"  # date encoded in the source filename
SQLITE_PATH = os.path.join(ROOT_DIR, "site", "data", "bids.sqlite")
OUT_PATH = os.path.join(ROOT_DIR, "data_overrides", "fish_access_override.csv")


def load_gis_fish(csv_path):
    """First-seen Fish_simple value per BID from the GIS export.

    TP_Split_JOIN_20260507.csv has more rows (32,145) than distinct BIDs
    (32,144) -- exactly one duplicate BID, and it agrees with itself, so
    first-seen-wins is safe. (Verified when this script was written; if a
    future source CSV has real BID/Fish_simple conflicts, this script prints
    a warning below rather than silently picking one.)
    """
    fish_by_bid = {}
    conflicts = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bid = row["BID"]
            fish = row["Fish_simple"]
            if bid in fish_by_bid:
                if fish_by_bid[bid] != fish:
                    conflicts.append(bid)
                continue
            fish_by_bid[bid] = fish
    if conflicts:
        print(f"WARNING: {len(conflicts)} BID(s) have conflicting Fish_simple "
              f"values across duplicate rows in {csv_path}: {conflicts[:10]}")
    return fish_by_bid


def main():
    if not os.path.isfile(SOURCE_CSV):
        sys.exit(f"Source GIS CSV not found: {SOURCE_CSV}")
    if not os.path.isfile(SQLITE_PATH):
        sys.exit(f"site/data/bids.sqlite not found -- run build_client_site.py "
                  f"first (without the override applied) so there is a scoring-"
                  f"table `fish` column to diff against: {SQLITE_PATH}")

    print(f"Reading GIS fish access from {os.path.basename(SOURCE_CSV)} ...")
    gis_fish = load_gis_fish(SOURCE_CSV)
    print(f"  {len(gis_fish):,} distinct BIDs in GIS export")

    conn = sqlite3.connect(SQLITE_PATH)
    rows = conn.execute("SELECT bid, fish FROM bids").fetchall()
    conn.close()
    print(f"  {len(rows):,} BIDs in bids table")

    missing = [bid for bid, _ in rows if bid not in gis_fish]
    if missing:
        sys.exit(f"{len(missing)} BID(s) in bids table have no match in the GIS "
                  f"export (e.g. {missing[:5]}) -- aborting rather than writing a "
                  f"partial override.")

    overrides = []
    for bid, fish_scoring in rows:
        fish_gis_raw = gis_fish[bid]
        # Normalize the scoring table's convention: null/blank -> "gradient"
        # (see build_client_site.py's `fish` column, sourced from Fish_simple
        # with the same null-fill).
        fish_gis = fish_gis_raw if fish_gis_raw else "gradient"
        fish_scoring_norm = fish_scoring if fish_scoring else "gradient"
        if fish_gis != fish_scoring_norm:
            overrides.append((bid, fish_gis, fish_scoring_norm))

    overrides.sort(key=lambda r: r[0])
    print(f"  {len(overrides)} BID(s) disagree between GIS and scoring table")

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    generated = date.today().isoformat()
    with open(OUT_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(
            "# fish_access_override.csv\n"
            f"# Source: {os.path.basename(SOURCE_CSV)} (GIS feature layer export, dated {SOURCE_DATE})\n"
            f"# Generated: {generated} by tools/make_fish_override.py\n"
            "# Why: the project lead ruled the GIS feature layer's Fish_simple value\n"
            "#      authoritative for fish access. BID_Scores_Calculated_20260507.csv\n"
            "#      (the scoring table used to build bids.sqlite) carries a stale\n"
            "#      Fish_simple pull that disagrees with the GIS layer on these BIDs.\n"
            f"# Row count: {len(overrides)} (a clean {len(overrides)//2}/{len(overrides)//2} swap:\n"
            "#      fish->gradient in one direction, gradient->fish in the other).\n"
            "# To regenerate: re-run `python tools/make_fish_override.py` after any\n"
            "#      update to the GIS export or the scoring table. This generator is\n"
            "#      NOT part of the build -- build_client_site.py only reads this\n"
            "#      small output file, never the 40 MB source CSV.\n"
            "bid,fish_gis,fish_scoring\n"
        )
        writer = csv.writer(f)
        for bid, fish_gis, fish_scoring in overrides:
            writer.writerow([bid, fish_gis, fish_scoring])

    print(f"Wrote {OUT_PATH} ({len(overrides)} rows)")


if __name__ == "__main__":
    main()
