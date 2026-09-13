"""Print expected values for the browser-side stats assertions."""
import os, sqlite3
DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "site", "data", "bids.sqlite")

import glob, gzip, tempfile
def open_db():
    gz = glob.glob(os.path.join(os.path.dirname(DB), "bids.*.sqlite.gz"))[0]
    tmp = os.path.join(tempfile.gettempdir(), "bids_test_unpacked.sqlite")
    with gzip.open(gz, "rb") as g, open(tmp, "wb") as out:
        out.write(g.read())
    return sqlite3.connect(tmp)

c = open_db()
print("ALL   n, acres, rpf, ci:", c.execute(
    "SELECT COUNT(*), ROUND(SUM(sqft)/43560.0,2), ROUND(AVG(rpsf),4),"
    " ROUND(AVG(rpsf*rpsa/100.0),4) FROM bids").fetchone())
print("P1    n, acres:", c.execute(
    "SELECT COUNT(*), ROUND(SUM(sqft)/43560.0,2) FROM bids WHERE tier='P1'").fetchone())
print("byTier:", c.execute(
    "SELECT tier, COUNT(*), ROUND(SUM(sqft)/43560.0,2) FROM bids"
    " GROUP BY tier ORDER BY SUM(sqft) DESC").fetchall())
print("compByZone(all):", c.execute(
    "SELECT z, ROUND(SUM(comp*lc0*sqft)/SUM(lc0*sqft),4), ROUND(SUM(ht*sqft)/SUM(sqft),3)"
    " FROM zones WHERE z <= 4 GROUP BY z ORDER BY z").fetchall())
print("lcByZone z=0 forest frac:", c.execute(
    "SELECT ROUND(SUM(lc0*sqft)/SUM(sqft),4) FROM zones WHERE z=0").fetchone())
print("salmon Coho n, acres:", c.execute(
    "SELECT COUNT(*), ROUND(SUM(sqft)/43560.0,2) FROM bids"
    " WHERE sps LIKE '%Coho%'").fetchone())
c.close()
