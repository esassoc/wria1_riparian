"""One-off generator: data_overrides/reach_attr_override.csv

Why this exists
---------------
The upstream scoring pipeline (preprocess_dashboard.py, read-only under RF_Test) reads
bank attributes out of BID_ZID_LC_20260501.csv and keeps the FIRST row per bank. That
file carries two copies of several attributes: a zone-level copy (RID, Desc_simple,
Fish_simple, ...) taken from whichever reach each zone polygon touches, and a bank-level
copy (RID_1, Desc_simple_1, Fish_simple_1, ...) from the bank itself. At reach
boundaries the 50 ft zone polygon often touches the NEIGHBOURING reach, so the zone-level
copy varies within a bank and the first row can belong to another reach. The pipeline
read the zone-level copy.

Consequences in the shipped dashboard (fish access is handled by fish_access_override.csv):
  rid  - wrong on 243 banks: Bank Explorer groups them with the wrong reach, so the
         sibling list, "rank on reach" and the channel lookup are all wrong for them
  str  - the feature type shown as "Stream" is wrong on 38 banks
  wt   - water type is looked up from rid, so it is wrong on 44 banks

This script writes, for every bank where any of the three disagrees, the value taken
from the bank's OWN reach:
  rid  = the reach prefix of the BID (BID is RID_SPLITSEQ on every polygon), checked
         against the GIS layer's RID
  str  = the bank-level Desc_simple from the GIS layer export
  wt   = 'river' / 'lake' / '' from the waterbody polygons that belong to the bank's own
         reach -- the upstream rule, applied with the correct reach

Reads:   TP_Split_JOIN_20260507.csv, BID_ZID_LC_20260501.csv, and the UPSTREAM
         bid_explorer_data.json (RF_Test, read-only). It diffs against upstream, not
         against the shipped site, so it gives the same answer after the override has
         been applied and a rerun never silently empties it.
Writes:  data_overrides/reach_attr_override.csv  (committed; consumed by the build)

Usage (from Final_Build/):   python tools/make_reach_override.py
"""
import csv
import os
import sys
from datetime import date

import json

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GIS_CSV = os.path.join(ROOT, "TP_Split_JOIN_20260507.csv")
LC_CSV = os.path.join(ROOT, "BID_ZID_LC_20260501.csv")
OUT = os.path.join(ROOT, "data_overrides", "reach_attr_override.csv")
UPSTREAM_JSON = r"U:\GIS\temp\CS\RS\Nook\RF_Test\MD\bid_explorer_data.json"


def own_reach(bid):
    return bid.rsplit("_", 1)[0]


def main():
    gis = pd.read_csv(GIS_CSV, usecols=["BID", "RID", "Desc_simple"], low_memory=False)
    gis = gis.drop_duplicates("BID").set_index("BID")

    # Invariant the whole fix rests on: BID = RID + '_' + SPLIT_SEQ, so the reach
    # prefix of the BID IS the bank's reach. Check it against the GIS layer.
    bad = [b for b, r in gis.RID.items() if own_reach(b) != r]
    if bad:
        sys.exit(f"ABORT: {len(bad)} BIDs whose prefix is not their GIS RID, e.g. {bad[:5]}")

    # Water type, upstream rule, keyed by the waterbody polygon's OWN reach.
    lc = pd.read_csv(LC_CSV, usecols=["BID", "Zone"], encoding="utf-8-sig", low_memory=False)
    w = lc[lc.Zone.isin(["river", "lake"])]
    kinds = w.groupby(w.BID.map(own_reach)).Zone.agg(set)

    def wt_for(reach):
        z = kinds.get(reach)
        if not z:
            return ""
        return "river" if "river" in z else "lake"

    up = json.load(open(UPSTREAM_JSON, encoding="utf-8"))
    rows = []
    for bid in up["bids"]:
        a = up["attrs"].get(bid, {})
        rid, st, wt = a.get("rid"), a.get("str"), a.get("wt")
        reach = own_reach(bid)
        new_str = gis.Desc_simple.get(bid)
        if new_str is None or (isinstance(new_str, float)):
            sys.exit(f"ABORT: {bid} has no Desc_simple in {os.path.basename(GIS_CSV)}")
        new_wt = wt_for(reach)
        if (rid, st or "", wt or "") != (reach, new_str, new_wt):
            rows.append((bid, reach, new_str, new_wt, rid, st or "", wt or ""))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        f.write("# reach_attr_override.csv\n")
        f.write(f"# Generated: {date.today().isoformat()} by tools/make_reach_override.py\n")
        f.write("# Bank attributes corrected to the bank's OWN reach. See that script's docstring.\n")
        wr = csv.writer(f)
        wr.writerow(["bid", "rid", "str", "wt", "rid_was", "str_was", "wt_was"])
        wr.writerows(sorted(rows))

    n_rid = sum(1 for r in rows if r[1] != r[4])
    n_str = sum(1 for r in rows if r[2] != r[5])
    n_wt = sum(1 for r in rows if r[3] != r[6])
    print(f"wrote {OUT}: {len(rows)} banks  (rid {n_rid}, str {n_str}, wt {n_wt})")


if __name__ == "__main__":
    main()
