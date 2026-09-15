#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Circular zonal statistics of aspect per bank (BID) polygon.

Why this exists
---------------
`AspectMEANBID` in BID_Scores_Calculated_*.csv was produced by ArcGIS Zonal
Statistics (MEAN) over an aspect raster. Aspect is a circular quantity, and a
linear mean of degrees collapses toward 180 (e.g. mean(10, 350) = 180, not 0).
The stored table (Reach_forReview.gdb\\AspectByBID) keeps only MIN/MAX/MEAN/COUNT,
so the direction cannot be recovered from it. This script goes back to the
raster and computes, per bank polygon:

    cell_count          cells used (NoData and flat cells excluded)
    aspect_linear_mean  ordinary mean of degrees  -- reproduces AspectMEANBID, for checking
    mean_sin, mean_cos  mean of sin/cos of cell aspect
    aspect_circ_mean    circular mean = atan2(mean_sin, mean_cos), 0-360
    resultant_r         mean resultant length, 1 = all cells face the same way, 0 = uniform
    north_factor        = mean_cos. Drop-in replacement for cos(AspectMEANBID):
                        +1 north-facing, -1 south-facing, averaged cell by cell,
                        so it never suffers from the wrap-around problem.
    aspect_class_circ   8-point compass class of the circular mean

Optionally joins the original zonal table and reports the difference, so you
can confirm the linear mean is reproduced before trusting the circular one.

Usage
-----
    python tools/aspect_circular_zonal.py ^
        --banks "U:\\...\\Wria1BankGeometry.gdb" --layer BanksBID ^
        --raster "U:\\...\\Rasters\\Elevation\\aspect1.tif" ^
        --out aspect_circular_by_bid.csv ^
        [--table "U:\\...\\Reach_forReview.gdb" --table-layer AspectByBID] ^
        [--limit 500] [--workers 6]

Requires: geopandas, pyogrio, shapely, rasterio, numpy, pandas.
Reads the .gdb through GDAL's OpenFileGDB driver; no ArcGIS licence needed.
"""
import argparse
import math
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']


def compass(deg):
    if deg is None or not np.isfinite(deg):
        return 'Flat/Unknown'
    return COMPASS[int(((deg + 22.5) % 360) // 45)]


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
_TLS = threading.local()   # one raster handle per worker thread
_RASTER_PATH = None


def _src():
    """Per-thread rasterio dataset. GDAL handles are not thread-safe, so each
    worker thread opens its own; reads release the GIL so threads scale well."""
    import rasterio
    s = getattr(_TLS, 'src', None)
    if s is None:
        s = _TLS.src = rasterio.open(_RASTER_PATH)
    return s


def _one(args):
    """args = (bid, geometry as GeoJSON-like mapping). Returns a dict."""
    import rasterio
    from rasterio.features import geometry_mask
    from rasterio.windows import from_bounds
    from shapely.geometry import shape

    bid, geom_mapping = args
    src = _src()
    geom = shape(geom_mapping)
    minx, miny, maxx, maxy = geom.bounds
    # Clip polygon bounds to the raster extent before building the window.
    rb = src.bounds
    minx, maxx = max(minx, rb.left), min(maxx, rb.right)
    miny, maxy = max(miny, rb.bottom), min(maxy, rb.top)
    out = dict(BID=bid, cell_count=0, aspect_linear_mean=np.nan, mean_sin=np.nan, mean_cos=np.nan,
               aspect_circ_mean=np.nan, resultant_r=np.nan, north_factor=np.nan)
    if minx >= maxx or miny >= maxy:
        return out
    win = from_bounds(minx, miny, maxx, maxy, src.transform).round_offsets().round_lengths()
    if win.width <= 0 or win.height <= 0:
        return out
    a = src.read(1, window=win)
    tr = src.window_transform(win)
    mask = geometry_mask([geom_mapping], out_shape=a.shape, transform=tr, invert=True, all_touched=False)
    v = a[mask]
    nd = src.nodata
    if nd is not None:
        v = v[v != nd]
    v = v[np.isfinite(v)]
    v = v[v >= 0]              # ArcGIS codes flat cells as -1; they have no aspect
    n = int(v.size)
    out['cell_count'] = n
    if n == 0:
        return out
    rad = np.radians(v.astype(np.float64))
    s, c = float(np.sin(rad).mean()), float(np.cos(rad).mean())
    out.update(
        aspect_linear_mean=float(v.mean()),
        mean_sin=s, mean_cos=c,
        aspect_circ_mean=math.degrees(math.atan2(s, c)) % 360.0,
        resultant_r=math.hypot(s, c),
        north_factor=c,
    )
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--banks', required=True, help='Path to .gdb (or .shp / .gpkg) holding the bank polygons')
    ap.add_argument('--layer', default=None, help='Layer name inside the .gdb (e.g. BanksBID)')
    ap.add_argument('--bid-field', default='BID')
    ap.add_argument('--raster', required=True, help='Aspect raster in degrees (0-360, flat = -1 or NoData)')
    ap.add_argument('--out', required=True, help='Output CSV')
    ap.add_argument('--table', default=None, help='Optional .gdb holding the original zonal table for a check')
    ap.add_argument('--table-layer', default='AspectByBID')
    ap.add_argument('--bid-override', default=None,
                    help='CSV of RID,SPLIT_SEQ,PositionWaterbody,new_BID used to re-key specific '
                         'polygons before processing. Exists because SPLIT_SEQ (and therefore BID) '
                         'collided on one reach; delete it once the source layer is fixed.')
    ap.add_argument('--pool-duplicate-bids', action='store_true',
                    help='Pool the cells of polygons that share a BID instead of failing. ArcGIS '
                         'Zonal Statistics does this implicitly, but it silently averages unrelated '
                         'polygons together, so it is opt-in here.')
    ap.add_argument('--limit', type=int, default=None, help='Process only the first N banks (testing)')
    ap.add_argument('--workers', type=int, default=max(2, (os.cpu_count() or 2)))
    a = ap.parse_args()

    import geopandas as gpd
    import rasterio
    from shapely.geometry import mapping

    t0 = time.time()
    with rasterio.open(a.raster) as src:
        ras_crs = src.crs
        print(f'raster: {src.width} x {src.height} cells, {src.res[0]:g} unit cells, nodata={src.nodata}, crs={ras_crs.to_string()[:60]}')

    print(f'reading banks from {a.banks} layer={a.layer} ...')
    cols = [a.bid_field]
    if a.bid_override:
        cols += ['RID', 'SPLIT_SEQ', 'PositionWaterbody']
    gdf = gpd.read_file(a.banks, layer=a.layer, engine='pyogrio', columns=cols)
    print(f'  {len(gdf):,} polygons, crs={gdf.crs.to_string()[:60]}')

    if a.bid_override:
        ov = pd.read_csv(a.bid_override, dtype={'RID': str, 'PositionWaterbody': str, 'new_BID': str})
        applied = 0
        for _, o in ov.iterrows():
            hit = ((gdf['RID'] == o['RID']) & (gdf['SPLIT_SEQ'] == int(o['SPLIT_SEQ']))
                   & (gdf['PositionWaterbody'] == o['PositionWaterbody']))
            n = int(hit.sum())
            if n != 1:
                sys.exit(f'ABORT: bid override row {dict(o)} matched {n} polygons, expected exactly 1')
            old = gdf.loc[hit, a.bid_field].iloc[0]
            if o['new_BID'] in set(gdf[a.bid_field]):
                sys.exit(f'ABORT: bid override would create a duplicate: {o["new_BID"]} already exists')
            gdf.loc[hit, a.bid_field] = o['new_BID']
            print(f'  bid override: {o["RID"]} seq {o["SPLIT_SEQ"]} '
                  f'({o["PositionWaterbody"]}) re-keyed {old} -> {o["new_BID"]}')
            applied += 1
        print(f'  applied {applied} bid override(s)')

    dup = gdf[a.bid_field][gdf[a.bid_field].duplicated(keep=False)]
    if len(dup) and not a.pool_duplicate_bids:
        sys.exit(f'ABORT: {dup.nunique()} BID(s) appear on more than one polygon: '
                 f'{sorted(set(dup))[:10]}. Fix the source layer (or supply --bid-override), '
                 'or pass --pool-duplicate-bids to average their cells together as ArcGIS '
                 'Zonal Statistics would.')
    if gdf.crs != ras_crs:
        print('  reprojecting polygons to raster CRS')
        gdf = gdf.to_crs(ras_crs)
    if a.limit:
        gdf = gdf.head(a.limit)

    work = [(row[a.bid_field], mapping(row.geometry)) for _, row in gdf.iterrows() if row.geometry is not None]
    print(f'processing {len(work):,} banks with {a.workers} workers ...')

    rows = []
    done = 0
    global _RASTER_PATH
    _RASTER_PATH = a.raster
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for r in ex.map(_one, work):
            rows.append(r)
            done += 1
            if done % 1000 == 0 or done == len(work):
                el = time.time() - t0
                print(f'  {done:,}/{len(work):,}  {el/60:.1f} min elapsed, ~{el/done*(len(work)-done)/60:.1f} min left', flush=True)

    df = pd.DataFrame(rows)

    # A BID can appear on more than one polygon (TP_Split has one: AC201_1). ArcGIS
    # Zonal Statistics treats same-value cells as ONE zone regardless of how many
    # polygons carry them, so collapse duplicates the same way: pool the cells by
    # weighting each polygon's mean sin/cos by its own cell count.
    if df['BID'].duplicated().any():
        dups = int(df['BID'].duplicated().sum())
        g = df.groupby('BID', sort=False)
        tot = g['cell_count'].transform('sum')
        w = np.where(tot > 0, df['cell_count'] / tot.replace(0, np.nan), 0.0)
        df['_s'], df['_c'], df['_lin'] = df['mean_sin'] * w, df['mean_cos'] * w, df['aspect_linear_mean'] * w
        agg = df.groupby('BID', as_index=False).agg(cell_count=('cell_count', 'sum'),
                                                    mean_sin=('_s', 'sum'), mean_cos=('_c', 'sum'),
                                                    aspect_linear_mean=('_lin', 'sum'))
        agg.loc[agg['cell_count'] == 0, ['mean_sin', 'mean_cos', 'aspect_linear_mean']] = np.nan
        agg['aspect_circ_mean'] = np.degrees(np.arctan2(agg['mean_sin'], agg['mean_cos'])) % 360.0
        agg['resultant_r'] = np.hypot(agg['mean_sin'], agg['mean_cos'])
        agg['north_factor'] = agg['mean_cos']
        print(f'  collapsed {dups} duplicate-BID polygon(s) by pooling their cells')
        df = agg

    df['aspect_class_circ'] = df['aspect_circ_mean'].map(compass)

    if a.table:
        print(f'checking against {a.table} / {a.table_layer} ...')
        tbl = gpd.read_file(a.table, layer=a.table_layer, engine='pyogrio', read_geometry=False)
        tbl = tbl.rename(columns={'MEAN': 'table_linear_mean', 'COUNT': 'table_count'})[[a.bid_field, 'table_linear_mean', 'table_count']]
        df = df.merge(tbl, on=a.bid_field, how='left')
        df['linear_diff_deg'] = (df['aspect_linear_mean'] - df['table_linear_mean']).abs()
        chk = df['linear_diff_deg'].dropna()
        print(f'  linear mean vs table: median |diff| {chk.median():.3f} deg, 95th pct {chk.quantile(.95):.3f}, max {chk.max():.2f} '
              f'(should be ~0; confirms the same cells were used)')
        ang = ((df['aspect_circ_mean'] - df['table_linear_mean'] + 180) % 360 - 180).abs().dropna()
        print(f'  |circular - linear|: median {ang.median():.1f} deg, 75th pct {ang.quantile(.75):.1f}, 90th pct {ang.quantile(.9):.1f}')

    df.to_csv(a.out, index=False, float_format='%.6g')
    ok = df['cell_count'] > 0
    print(f'wrote {a.out}: {len(df):,} banks, {(~ok).sum()} with no usable cells')
    print('compass classes by circular mean:')
    print(df.loc[ok, 'aspect_class_circ'].value_counts().reindex(COMPASS).fillna(0).astype(int).to_string())
    print(f'north_factor mean {df.loc[ok, "north_factor"].mean():+.3f}, share negative {(df.loc[ok, "north_factor"] < 0).mean():.1%}')
    print(f'resultant_r median {df.loc[ok, "resultant_r"].median():.2f}  (low = aspects scattered within the bank)')
    print(f'done in {(time.time()-t0)/60:.1f} min')


if __name__ == '__main__':
    main()
