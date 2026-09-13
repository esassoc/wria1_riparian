"""Download the pinned vendor scripts into vendor/ and write vendor/MANIFEST.json.
Run once (vendor/ is committed): python tools/fetch_vendor.py
Re-run only to change a pinned version; then update the URLs below."""
import os, sys, json, hashlib, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.path.join(ROOT, "vendor")
PINS = {
    "react.production.min.js":     "https://cdnjs.cloudflare.com/ajax/libs/react/18.3.1/umd/react.production.min.js",
    "react-dom.production.min.js": "https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.3.1/umd/react-dom.production.min.js",
    "prop-types.min.js":           "https://cdnjs.cloudflare.com/ajax/libs/prop-types/15.8.1/prop-types.min.js",
    "Recharts.js":                 "https://unpkg.com/recharts@2.12.7/umd/Recharts.js",
    "sql-wasm.js":                 "https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.3/sql-wasm.js",
    "sql-wasm.wasm":               "https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.3/sql-wasm.wasm",
}

# prop-types.min.js is a genuinely tiny file (1,722 bytes upstream in the npm
# package itself -- verified against the published tarball's sha256); every
# other pin is comfortably larger, so it gets the normal 10 KB floor.
MIN_BYTES = {"prop-types.min.js": 1_000}

def main():
    os.makedirs(VENDOR, exist_ok=True)
    manifest = {}
    for name, url in PINS.items():
        print(f"  fetching {name} <- {url}")
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
        floor = MIN_BYTES.get(name, 10_000)
        if len(data) < floor:
            print(f"FAIL: {name} is only {len(data)} bytes -- wrong URL?"); sys.exit(1)
        with open(os.path.join(VENDOR, name), "wb") as f:
            f.write(data)
        manifest[name] = {"url": url, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    with open(os.path.join(VENDOR, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    total = sum(v["bytes"] for v in manifest.values())
    print(f"  wrote {len(manifest)} files, {total/1e6:.2f} MB, and MANIFEST.json")

if __name__ == "__main__":
    main()
