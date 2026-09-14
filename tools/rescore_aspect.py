#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Re-score the solar chain using a circular-mean aspect north factor.

Background
----------
`AspectMEANBID` was produced by ArcGIS Zonal Statistics MEAN over aspect1.tif. Two
independent errors are baked into it:

  1. Aspect is circular; a linear mean of degrees collapses toward 180 (south).
     Result: 95% of banks get a negative cos(aspect) and lose the north-facing boost.
  2. Flat cells are coded -1 by ArcGIS and were averaged AS IF -1 were a direction.
     Result: flat-dominated banks (lake shores) get a mean near 0 deg, i.e. a spurious
     near-maximum NORTH boost. Verified: recomputing the table mean as
     (n_sloped*mean_sloped + n_flat*(-1)) / n_total reproduces it to 0.0006 deg median.

`tools/aspect_circular_zonal.py` recomputes per-bank statistics from the raster,
excluding flat/NoData cells, and reports `north_factor` = mean of cos(aspect) over the
bank's sloped cells. That is the quantity the scoring wants: a cell-by-cell average of
"how north-facing", immune to wrap-around, and it degrades to ~0 (neutral) when a bank's
aspects are scattered, which is the honest answer for flat terrain.

What this script does
---------------------
Replays the downstream chain from preprocess_dashboard.py exactly, twice:

  A. VALIDATION: recompute every affected column from the ORIGINAL AspectMEANBID and
     compare to the values already in the scores CSV. If this does not reproduce, the
     chain here is wrong and the script aborts before writing anything.
  B. RESCORE: same chain with north_factor replaced by the circular value.

Affected columns (everything else is carried through unchanged):
    aspect_north_factor, combined_solar, solar_risk, solar_push,
    RP_solar_only, RP_final, RP_S_final, CI
Priority_Tier is NOT affected: it is assigned from Chinook / Nooksack / temperature /
fish-bearing flags, with no dependence on RP.

Outputs
-------
  --out-scores  full replacement for BID_Scores_Calculated_*.csv (same columns/order)
  --out-join    slim CSV to join on BID onto the hosted GIS layer
"""
import argparse
import sys

import numpy as np
import pandas as pd

# Constants copied verbatim from preprocess_dashboard.py (lines 55-62).
MAX_SOLAR_PUSH = 12
MAX_SLOPE_PUSH = 5
SLOPE_CURVE_EXP = 1.2
ASPECT_BOOST = 0.5
SOLAR_CURVE_EXP = 1.2

AFFECTED = ['aspect_north_factor', 'combined_solar', 'solar_risk', 'solar_push',
            'RP_solar_only', 'RP_final', 'RP_S_final', 'CI']

# Rounding applied by preprocess_dashboard.py when it writes the scores CSV
# (_round_map, ~line 1877). Needed so validation compares like with like.
ROUND = {'aspect_north_factor': 3, 'combined_solar': 1, 'solar_risk': 3, 'solar_push': 2,
         'RP_solar_only': 2, 'RP_final': 2, 'RP_S_final': 2, 'CI': 1}


def solar_chain(df, north_factor):
    """Replay FC2 solar -> slope -> wetland -> CI. Returns a dict of new columns.

    north_factor must already be filled (0.0 where aspect is unknown), matching
    `bid_df.loc[AspectMEANBID.isna(), 'aspect_north_factor'] = 0.0` upstream.
    """
    out = {}
    out['aspect_north_factor'] = nf = north_factor
    out['combined_solar'] = cs = df['SolarAcMEAN'] * (1 + ASPECT_BOOST * nf)

    # Percentile rank over the whole BID set, NaN kept then filled 0.5.
    risk = cs.rank(pct=True, na_option='keep').fillna(0.5)
    out['solar_risk'] = risk

    lvl = df['RP_norm'] / 100.0
    out['solar_push'] = push = risk * MAX_SOLAR_PUSH * lvl ** SOLAR_CURVE_EXP
    out['RP_solar_only'] = np.clip(df['RP_norm'] + push, 0, 100)

    # slope_push and wetland_push do not depend on aspect: reuse as stored.
    out['RP_final'] = np.clip(df['RP_norm'] + push + df['slope_push'] + df['wetland_push'], 0, 100)

    # S-curve variant: same solar_risk, different base.
    lvl_s = df['RP_S_norm'] / 100.0
    push_s = risk * MAX_SOLAR_PUSH * lvl_s ** SOLAR_CURVE_EXP
    slope_push_s = df['slope_risk'] * MAX_SLOPE_PUSH * lvl_s ** SLOPE_CURVE_EXP
    out['RP_S_final'] = rsf = np.clip(df['RP_S_norm'] + push_s + slope_push_s + df['wetland_push'], 0, 100)

    out['CI'] = (rsf * df['RP_S_area_pctile'] / 100.0).round(1)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--scores', required=True, help='BID_Scores_Calculated_*.csv')
    ap.add_argument('--aspect', required=True, help='Output of tools/aspect_circular_zonal.py')
    ap.add_argument('--source-gdb', required=True,
                    help='GDB holding the BID source layer, for UNROUNDED AspectMEANBID / SolarAcMEAN. '
                         'The scores CSV stores these rounded to 1 decimal, which alone shifts '
                         'combined_solar by up to 0.5 and makes validation ambiguous.')
    ap.add_argument('--source-layer', default='TP_Split')
    ap.add_argument('--out-scores', required=True)
    ap.add_argument('--out-join', required=True,
                    help='Full audit table: new and old values side by side plus deltas.')
    ap.add_argument('--out-join-update', default=None,
                    help='Slim GIS update table: BID plus ONLY the changed fields, each named '
                         '<existing field name>_new so it joins onto the hosted layer and maps '
                         'field-to-field with no renaming.')
    ap.add_argument('--factor', default='mean_cos', choices=['mean_cos', 'cos_circ_mean'],
                    help="mean_cos (default, recommended): cell-wise mean of cos(aspect). "
                         "cos_circ_mean: cos of the circular mean; ignores how scattered the bank is.")
    ap.add_argument('--tolerance-units', type=float, default=2.0,
                    help='Max allowed validation mismatch, in units of each column\'s own last '
                         'stored decimal place (default 2). RP_norm is only stored to 2dp, so a '
                         'push derived from it can legitimately differ by a unit or so.')
    a = ap.parse_args()

    import geopandas as gpd

    src = pd.read_csv(a.scores)
    asp = pd.read_csv(a.aspect)
    order = list(src.columns)
    print(f'scores: {len(src):,} BIDs, {len(order)} columns')
    print(f'aspect: {len(asp):,} BIDs, {(asp.cell_count == 0).sum()} with no sloped cells')

    missing = set(src.BID) - set(asp.BID)
    if missing:
        sys.exit(f'ABORT: {len(missing)} scored BIDs absent from the aspect table, e.g. {sorted(missing)[:5]}')

    print(f'reading unrounded inputs from {a.source_gdb} / {a.source_layer} ...')
    raw = gpd.read_file(a.source_gdb, layer=a.source_layer, engine='pyogrio', read_geometry=False,
                        columns=['BID', 'AspectMEANBID', 'SolarAcMEAN']).drop_duplicates('BID')
    absent = set(src['BID']) - set(raw['BID'])
    if absent:
        sys.exit(f'ABORT: {len(absent)} scored BIDs absent from {a.source_layer}, e.g. {sorted(absent)[:5]}')
    src = src.merge(raw.rename(columns={'AspectMEANBID': '_asp_raw', 'SolarAcMEAN': '_sol_raw'}),
                    on='BID', how='left')
    # Null SolarAcMEAN is legitimate (47 BIDs upstream): combined_solar stays NaN and
    # solar_risk falls back to 0.5, exactly as preprocess_dashboard.py does.
    n_null = int(src['_sol_raw'].isna().sum())
    if n_null:
        print(f'  note: {n_null} scored BIDs have no SolarAcMEAN; solar_risk falls back to 0.5 for them')
    # Use full-precision solar for the whole replay; the CSV copy is rounded to 1dp.
    src['SolarAcMEAN'] = src['_sol_raw']

    # ---------------------------------------------------------------- validation
    print('\nA. VALIDATION -- replaying the chain from the ORIGINAL (unrounded) AspectMEANBID')
    old_nf = np.cos(np.radians(src['_asp_raw'].astype(float)))
    old_nf = old_nf.where(src['_asp_raw'].notna(), 0.0)
    repro = solar_chain(src, old_nf)
    bad = False
    for c in AFFECTED:
        unit = 10.0 ** -ROUND[c]
        d = (pd.Series(repro[c]).round(ROUND[c]) - src[c]).abs()
        n_off = int((d > unit * 0.5).sum())
        flag = '' if d.max() <= unit * a.tolerance_units + 1e-9 else '  <-- MISMATCH'
        if flag:
            bad = True
        print(f'  {c:<20} max |diff| {d.max():.4f} = {d.max()/unit:.1f} rounding units, '
              f'{n_off:,}/{len(d):,} rows differ at all{flag}')
    if bad:
        sys.exit('\nABORT: the replayed chain does not reproduce the stored scores. '
                 'Do not trust the rescore until this is resolved.')
    print('  chain reproduces the stored scores to within stored precision -- safe to rescore')

    # ---------------------------------------------------------------- rescore
    print(f'\nB. RESCORE -- north factor from {a.factor}')
    col = 'mean_cos' if a.factor == 'mean_cos' else None
    j = src.merge(asp, on='BID', how='left', suffixes=('', '_asp'))
    if col:
        new_nf = j[col]
    else:
        new_nf = np.cos(np.radians(j['aspect_circ_mean']))
    new_nf = pd.Series(new_nf).fillna(0.0)          # unknown aspect -> neutral, as upstream
    new = solar_chain(src, new_nf)

    out = src.copy()
    for c in AFFECTED:
        out[c] = pd.Series(new[c]).round(ROUND[c])
    # AspectMEANBID itself is replaced by the circular mean so the column stays meaningful.
    out['AspectMEANBID'] = j['aspect_circ_mean'].round(1)
    out['SolarAcMEAN'] = out['SolarAcMEAN'].round(1)        # restore stored precision
    out = out[order]

    print(f'  north factor: old mean {old_nf.mean():+.3f} ({(old_nf < 0).mean():.1%} negative)'
          f' -> new mean {new_nf.mean():+.3f} ({(new_nf < 0).mean():.1%} negative)')
    for c in ['solar_push', 'RP_final', 'RP_S_final', 'CI']:
        d = out[c] - src[c]
        print(f'  {c:<12} mean {src[c].mean():7.2f} -> {out[c].mean():7.2f}   '
              f'change: mean {d.mean():+.2f}, median {d.median():+.2f}, '
              f'max up {d.max():+.2f}, max down {d.min():+.2f}')

    out.to_csv(a.out_scores, index=False)
    print(f'\nwrote {a.out_scores}')

    # ---------------------------------------------------------------- join table
    # Field names kept <= 31 chars and free of leading digits so they survive a join
    # into a file geodatabase / hosted feature layer unmangled.
    jn = pd.DataFrame({
        'BID': out['BID'],
        'AspectDeg_New': j['aspect_circ_mean'].round(1),      # circular mean; replaces AspectMEANBID
        'AspectDeg_Old': src['AspectMEANBID'],
        'AspectClass_New': j['aspect_class_circ'],
        'AspectR': j['resultant_r'].round(3),                 # 1 = cells agree, 0 = scattered
        'AspectCells': j['cell_count'],
        'NorthFactor_New': out['aspect_north_factor'],
        'NorthFactor_Old': src['aspect_north_factor'],
        'CombSolar_New': out['combined_solar'],
        'CombSolar_Old': src['combined_solar'],
        'SolarRisk_New': out['solar_risk'],
        'SolarRisk_Old': src['solar_risk'],
        'SolarPush_New': out['solar_push'],
        'SolarPush_Old': src['solar_push'],
        'RPfinal_New': out['RP_final'],
        'RPfinal_Old': src['RP_final'],
        'RPfinal_Delta': (out['RP_final'] - src['RP_final']).round(2),
        'RPSfinal_New': out['RP_S_final'],
        'RPSfinal_Old': src['RP_S_final'],
        'CI_New': out['CI'],
        'CI_Old': src['CI'],
        'CI_Delta': (out['CI'] - src['CI']).round(1),
    })

    # Banks present in the aspect recompute but never scored (waterbody / out-of-scope
    # BIDs the dashboard excludes) still get their corrected aspect, with the score
    # columns left blank, so this one file joins cleanly onto the full BID layer.
    extra = asp[~asp['BID'].isin(jn['BID'])]
    if len(extra):
        pad = pd.DataFrame({
            'BID': extra['BID'],
            'AspectDeg_New': extra['aspect_circ_mean'].round(1),
            'AspectClass_New': extra['aspect_class_circ'],
            'AspectR': extra['resultant_r'].round(3),
            'AspectCells': extra['cell_count'],
            # 0.0, not blank: a bank with no sloped cells has a neutral north factor,
            # matching how the scoring treats an unknown aspect.
            'NorthFactor_New': extra['mean_cos'].fillna(0.0).round(3),
        })
        jn = pd.concat([jn, pad], ignore_index=True)
        print(f'  + {len(extra):,} unscored BIDs carried with aspect only (no score columns)')

    jn = jn.sort_values('BID')
    jn.to_csv(a.out_join, index=False)
    print(f'wrote {a.out_join}  ({len(jn):,} rows, {len(jn.columns)} fields, join on BID)')

    # ------------------------------------------------- slim GIS update table
    # Only the fields the correction actually changes, each carrying the name it has
    # in the source scoring table (and therefore in the hosted layers derived from it)
    # with a _new suffix. Everything else in the scores is untouched by this fix:
    # RP_norm, the area track, slope_risk/slope_push, wetland_push, RP_S_norm and
    # Priority_Tier are all independent of aspect.
    if a.out_join_update:
        upd = pd.DataFrame({'BID': out['BID']})
        upd['AspectMEANBID_new'] = j['aspect_circ_mean'].round(1)
        for c in AFFECTED:
            upd[c + '_new'] = out[c]
        extra_u = asp[~asp['BID'].isin(upd['BID'])]
        if len(extra_u):
            # fillna(0.0) matches the scoring convention: a bank with no sloped cells has
            # a neutral north factor, not a missing one. AspectMEANBID_new stays blank
            # there, because "no direction" is the honest value for a bearing.
            pad_u = pd.DataFrame({'BID': extra_u['BID'],
                                  'AspectMEANBID_new': extra_u['aspect_circ_mean'].round(1),
                                  'aspect_north_factor_new': extra_u['mean_cos'].fillna(0.0).round(3)})
            upd = pd.concat([upd, pad_u], ignore_index=True)
        upd = upd.sort_values('BID')
        upd.to_csv(a.out_join_update, index=False)
        print(f'wrote {a.out_join_update}  ({len(upd):,} rows, {len(upd.columns)} fields: '
              f'{", ".join(upd.columns)})')


if __name__ == '__main__':
    main()
