"""Open the shipped, gzipped dashboard database for tests and maintenance tools.

The build ships only site/data/bids.<hash>.sqlite.gz; this unpacks the newest one to a
temp file and returns a sqlite3 connection. Run nothing on import.
"""
import glob, gzip, os, sqlite3, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "site", "data")


def shipped_gz_path():
    paths = sorted(glob.glob(os.path.join(DATA_DIR, "bids.*.sqlite.gz")), key=os.path.getmtime)
    if not paths:
        raise FileNotFoundError(
            f"no bids.*.sqlite.gz under {DATA_DIR} -- run: python build_client_site.py")
    return paths[-1]


def open_shipped_db(tmp_name="bids_unpacked.sqlite"):
    gz = shipped_gz_path()
    tmp = os.path.join(tempfile.gettempdir(), tmp_name)
    with gzip.open(gz, "rb") as g, open(tmp, "wb") as out:
        out.write(g.read())
    return sqlite3.connect(tmp)
