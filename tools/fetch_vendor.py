"""Download the pinned vendor scripts into vendor/ and write vendor/MANIFEST.json.
Run once (vendor/ is committed): python tools/fetch_vendor.py
Re-run only to change a pinned version; then update the URLs below."""
import os, sys, json, hashlib, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENDOR = os.path.join(ROOT, "vendor")

# Each pin is a list of candidate URLs, tried in order (cdnjs first where
# available, then a fallback CDN for the same pinned version), so a single
# CDN 404 does not block the fetch.
PINS = {
    "react.production.min.js": [
        "https://cdnjs.cloudflare.com/ajax/libs/react/18.3.1/umd/react.production.min.js",
        "https://unpkg.com/react@18.3.1/umd/react.production.min.js"],
    "react-dom.production.min.js": [
        "https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.3.1/umd/react-dom.production.min.js",
        "https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js"],
    "prop-types.min.js": [
        "https://cdnjs.cloudflare.com/ajax/libs/prop-types/15.8.1/prop-types.min.js",
        "https://unpkg.com/prop-types@15.8.1/prop-types.min.js"],
    "Recharts.js": [
        "https://unpkg.com/recharts@2.12.7/umd/Recharts.js",
        "https://cdn.jsdelivr.net/npm/recharts@2.12.7/umd/Recharts.js"],
    "sql-wasm.js": [
        "https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.3/sql-wasm.js",
        "https://unpkg.com/sql.js@1.10.3/dist/sql-wasm.js"],
    "sql-wasm.wasm": [
        "https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.3/sql-wasm.wasm",
        "https://unpkg.com/sql.js@1.10.3/dist/sql-wasm.wasm"],
}

# prop-types.min.js is a genuinely tiny file (1,722 bytes upstream in the npm
# package itself -- verified against the published tarball's sha256); every
# other pin is comfortably larger, so it gets the normal 10 KB floor.
MIN_BYTES = {"prop-types.min.js": 1_000}


def looks_valid(name, data):
    head = data[:512].lstrip()
    if name.endswith(".wasm"):
        return data[:4] == b"\x00asm"
    if head.startswith(b"<") or b"<!doctype" in head.lower() or b"<html" in head.lower():
        return False
    return True


def main():
    os.makedirs(VENDOR, exist_ok=True)
    manifest = {}
    for name, urls in PINS.items():
        data = None
        used_url = None
        for url in urls:
            print(f"  fetching {name} <- {url}")
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    data = r.read()
                used_url = url
                break
            except (urllib.error.HTTPError, urllib.error.URLError) as e:
                print(f"  WARN: {name} from {url} failed ({e}); trying next candidate")
                continue
        if data is None:
            print(f"FAIL: {name} could not be fetched from any candidate URL"); sys.exit(1)
        floor = MIN_BYTES.get(name, 10_000)
        if len(data) < floor:
            print(f"FAIL: {name} is only {len(data)} bytes -- wrong URL?"); sys.exit(1)
        if not looks_valid(name, data):
            print(f"FAIL: {name} from {used_url} does not look like a {'wasm' if name.endswith('.wasm') else 'JavaScript'} file (HTML error page?)"); sys.exit(1)
        with open(os.path.join(VENDOR, name), "wb") as f:
            f.write(data)
        manifest[name] = {"url": used_url, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    with open(os.path.join(VENDOR, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    total = sum(v["bytes"] for v in manifest.values())
    print(f"  wrote {len(manifest)} files, {total/1e6:.2f} MB, and MANIFEST.json")

if __name__ == "__main__":
    main()
