# WRIA 1 Client Dashboard — Build Notes & Design Choices

**Built:** September 2026
**Location:** `U:\GIS\GIS\Projects\2024xxx\D202401511_WRIA_1_Riparian_Needs_Assessment\05_Code\Final_Build`
**Deploy target:** GitHub Pages, linked from ArcGIS Online webmap popups — live at
`https://esassoc.github.io/wria1_riparian/` (repo `https://github.com/esassoc/wria1_riparian`)
**Data vintage:** May 2026 run — 30,850 BIDs, 177,016 riparian acres

---

## 1. What this is

A simplified, client-facing fork of the internal WRIA 1 Riparian Data Explorer. It keeps the
three interactive tools and replaces the fifteen internal summary-statistics tabs with a
single Summary Stats page that responds live to whatever filter is set on the BID Query tab.

**Four tabs:** BID Query (landing) → Summary Stats → Bank Explorer → Scoring Lab.

Deliberately excluded: the Methodology tab, the Model Reference tab, and all fifteen
analytical summary tabs.

## 2. Files

| Path | What it is |
|---|---|
| `client_dashboard.html` | The forked source. **The only file you hand-edit.** |
| `build_client_site.py` | Build script. Owns the SQLite schema. Run it after any edit. |
| `BID_Scores_Calculated_20260914_circaspect.csv` | Build input (`SCORES_CSV`). The aspect-corrected rescore of `BID_Scores_Calculated_20260507.csv`; see §11, Fix 3. S-track score components (`rpsn`/`sols`/`slps`/`rpsf`/`rpsa`), joined onto every BID by `build_client_site.py`. |
| `BID_ZID_LC_20260501.csv` | **Not a build input any more.** Source for `data_cache/lc_derived_20260501.json` only; needed solely for `--refresh-lc-cache`; git-ignored. Zone-level landcover and canopy-height source; also rebuilds `waterbody_bids` (see §11, Fix 2) and feeds the canopy-height clamp (§11, Fix 3). ~433 MB - never copied into `site/`. |
| `data_overrides/fish_access_override.csv` | Build input. A small, auditable, committed CSV (`bid,fish_gis,fish_scoring`) applied at build time so `tier`/`fish` in the shipped dashboard correct 104 banks against the GIS-authoritative layer (see §11, Fix 1). Regenerate with `tools/make_fish_override.py` whenever the source files are refreshed. |
| `data_overrides/aspect_override.csv` | Build input. Committed CSV (`BID,asp,af`) supplying the circular-mean bank aspect and north factor, overriding the upstream JSON (see §11, Fix 3). Optional: absent, the build uses upstream values. |
| `tools/aspect_circular_zonal.py` | Circular zonal statistics of aspect per BID, straight off `aspect1.tif`. Generates the aspect override and the rescore input. |
| `tools/rescore_aspect.py` | Replays the solar/slope/wetland/CI chain with the corrected north factor. Validates against the stored scores before writing. |
| `tools/make_fish_override.py` | One-off generator for `fish_access_override.csv` (not part of the build itself). Diffs `TP_Split_JOIN_20260507.csv`'s `Fish_simple` against the current `fish` column in the shipped `site/data/bids.<hash>.sqlite.gz` (unpacked via `tests/db_helpers.py`). |
| `site/` | Build output. This is what gets pushed to Pages. Never hand-edit. |
| `tests/test_build_output.py` | Asserts the built site is correct and leaks nothing internal. |
| `tests/test_visual_polish.py` | Asserts the September 2026 visual-polish contract holds: no brand leaks, no abbreviations, no dead code, no emoji, no mojibake. |
| `tests/test_zone_stats.py` | Asserts the area and zone-composition data reconciles. |
| `tests/ground_truth.py` | Prints expected values for browser-side spot checks. |
| `tests/run_all.py` | Runs every `tests/test_*.py` script (`ground_truth.py` is a reference printer, not a test, and is not run); the one command to run after a build. |
| `tests/db_helpers.py` | Shared helper that unpacks the shipped `bids.<hash>.sqlite.gz` to a temp file and returns a connection. Used by the tests and by `tools/make_fish_override.py`. |
| `data_cache/lc_derived_20260501.json` | Committed cache of everything the build needs out of `BID_ZID_LC_20260501.csv`. Regenerate with `python build_client_site.py --refresh-lc-cache`. |
| `vendor/` + `vendor/MANIFEST.json` | Committed, pinned third-party scripts (React, ReactDOM, prop-types, Recharts, sql.js + wasm) with their sha256s. Copied into `site/vendor/` by the build; both copies are hash-checked. |
| `tools/fetch_vendor.py` | Re-downloads `vendor/` from the pinned upstream URLs and rewrites `MANIFEST.json`. Only needed when a vendor version changes. |
| `package.json` / `package-lock.json` | Node dev dependencies (Tailwind CLI, Babel) used only at build time. `npm install` once per machine. |
| `tailwind.config.js` | Tailwind content/theme config for the build-time CSS compile. |
| `tools/tailwind.in.css` | Tailwind entry stylesheet compiled into the page's inline `<style id="tw">`. |
| `tools/precompile.mjs` | Babel JSX -> JS precompile step (replaces the in-browser Babel runtime). |
| `.github/workflows/pages.yml` | GitHub Actions workflow that publishes `site/` to Pages on any push to `main` touching `site/**`. |
| `.gitattributes` | Marks `vendor/*` and `site/vendor/*` binary-exact (`-text`) so a Windows clone cannot CRLF-rewrite them and break the sha256 checks. |
| `docs/` | Spec, implementation plan, verification record. |
| `.superpowers/sdd/progress.md` | Full task-by-task build log, every bug found and fixed. |

To rebuild:

```bash
cd "U:/GIS/GIS/Projects/2024xxx/D202401511_WRIA_1_Riparian_Needs_Assessment/05_Code/Final_Build"
npm install            # prerequisite, once per machine
python build_client_site.py
python tests/run_all.py
```

Build inputs consumed automatically by `build_client_site.py` (no separate step needed):
`BID_Scores_Calculated_20260914_circaspect.csv`, `data_cache/lc_derived_20260501.json`,
`data_overrides/fish_access_override.csv`, and `data_overrides/aspect_override.csv`. `BID_ZID_LC_20260501.csv` is **not** among them —
it is read only under `--refresh-lc-cache`, to regenerate that cache. Only regenerate the fish
override by hand, and only when `TP_Split_JOIN_20260507.csv` or the scoring CSV is refreshed:

```bash
python tools/make_fish_override.py
```

Site output is ~6.6 MB (one gzipped SQLite ~5.0 MB, self-hosted vendor scripts ~1.3 MB, and `index.html` ~0.24 MB). **Never run a bundler** — this ships as a multi-file site only.

## 3. Fork, not shared source

`client_dashboard.html` is a one-time copy of `MD/dashboard.html` with ~30 panels deleted.
The internal dashboard and its `esassoc/wria1rip` deployment are untouched.

The trade-off: a fix to BID Query, Bank Explorer or Scoring Lab must now be applied in both
places. The fork is treated as frozen-at-copy, not continuously synced. This was chosen
because the client build is a genuinely different product and build-time stripping of a
7,000-line file by pattern matching is brittle.

Source went from 7,096 lines to ~3,700.

## 4. The Summary Stats page

A pinned Query Summary block plus seven collapsible sections. Only Restoration Metrics opens
by default, and a collapsed section runs **no queries at all** — that is what keeps the page
fast.

**Pinned Query Summary:** five KPI tiles (reaches, acres, mean RP Final, mean Composite
Index, mean Area-Weighted Percentile), each showing the WRIA-wide value beneath in grey.
Then six 100%-stacked acre bars — Priority Tier, Salmon-bearing, Temperature impairment,
SR Zone, Owner, Zoning — each with a thin ghost bar beneath and the acre total at the right.

**The seven sections** (27 charts total):

| Section | Contents |
|---|---|
| Restoration Metrics | RP Final and Composite Index histograms; composition by buffer zone by tier (toggles to a 9-class landcover stack); mean RP/CI by tier |
| Fish / Salmon | Salmon species presence; composition and canopy height by buffer zone, salmon-bearing vs not; mean RP/CI by fish class |
| Impairment | 303(d) rates for temperature/fecal/sediment; temperature-impaired acres by category; composition by buffer zone impaired vs not; mean RP/CI by category |
| River Context | Acres by stream size; composition by buffer zone by stream size; mean RP/CI by stream size and by SR Zone |
| Administrative | Acres by owner; composition by buffer zone by owner; mean RP/CI by owner and by zoning |
| Solar | Solar push distribution; acres by aspect class; mean RP/CI by solar band; slope push distribution |
| Wetland | Wetland push distribution; acres by wetland connection; mean RP/CI by connection |

### The ghost baseline

Every chart draws the WRIA-wide series behind the selection at 25% opacity, same chart type
and axes. When the selection *is* the whole watershed the ghosts are suppressed and the page
says "Showing all reaches — run a query on the BID Query tab to compare a subset against the
WRIA average", because otherwise the ghost would sit exactly under the solid series.

## 5. Design choices worth knowing

### Partition vs rate — the distinction that governs every bar chart

Some categories divide the selection up (every reach is in exactly one tier, has exactly one
owner). Those are **partitions**, and their bars are shown as a share of the whole, summing
to 100%.

Others overlap. A reach can be temperature- *and* fecal-impaired; it can host Coho *and*
Chinook. Those are **independent rates**, and each is shown against the selection's total
acreage rather than against each other.

This matters more than it sounds. Normalising the nine salmon species against one another
was wrong because their acreages sum to 197,331 against a real total of 177,016 — a share of
that overlapping sum means nothing. Likewise the three 303(d) parameters: normalising them
forced three independent rates to sum to 100% and roughly tripled each one.

Charts of overlapping rates are labelled "% of selected acres". Charts of partitions are
labelled "Share of selected acres by …".

### Buffer zone filter semantics

The Buffer Zones chips gate the **zone-level charts only** — they do not change which reaches
are selected. Deselect HMZ and you still have 30,850 reaches; those zones simply stop
contributing to the composition and landcover aggregates, and drop off those charts' axes.

A buffer zone is a slice *within* a reach, not a property of one, so filtering reaches by it
would be the wrong operation. (These chips were inert in the internal dashboard; they are
wired up here.)

### One scoring track: the S-curve columns

The pipeline produces two parallel score sets — linear (`rpf`, `rpa`) and S-curve (`rpsf`,
`rpsa`). **This build surfaces only the S-curve columns**, everywhere, under the labels
"RP Final" and "Area RP Percentile".

The internal dashboard mixed them: BID Query filtered and tabled the linear pair while the
Composite Index was computed from the S-curve pair. Because the two differ by only 0.85 on
average, it read as rounding rather than as two different metrics. Three consequences, all
now resolved:

- The table contradicted itself — on 27,512 of 30,850 rows the displayed Composite Index was
  not the product of the two columns beside it. It now is, exactly.
- Filtering "RP Final" to 50–55 left 25% of the plotted distribution outside that band. Now
  zero.
- The Summary Stats KPI read 56.3 where the table averaged 55.2 for the same rows. They now
  agree.

Bank Explorer's reach-context bars had the same split — headline RP from one column, sibling
comparison bars from the other — and were aligned too.

The linear columns remain in the database, unused.

### Composite Index

`CI = RP Final × Area RP Percentile ÷ 100`. Both inputs are S-curve, so the table is now
self-checking: multiply the two columns, divide by 100, and you get the third.

## 6. Data layer additions

Two things were added to the SQLite the build produces. `preprocess_dashboard.py` was **not**
touched — both derive from data already in `bid_explorer_data.json`.

- **`bids.sqft`** — total area per BID. Drives the acres KPI and every area-weighted figure.
  Acres = sqft ÷ 43,560.
- **`zone_stats` table (superseded 2026-09-13, see §14).** Originally a separate 89,319-row
  table, one per BID × buffer zone (indices 0–4; the channel zone excluded), storing landcover
  as area so weighted composition was a plain `SUM(lcN_sqft)/SUM(sqft)`. The September 2026
  performance pass (Task 2) folded it into the `zones` table below — same rows, same
  area-based composition query, no separate table any more.

As of the September 2026 performance pass, `zones` is a single numeric table (18 columns,
proportions not JSON) that serves both Bank Explorer's point lookups and Summary Stats'
aggregates — see §14 for the exact schema. The old `zones.data` JSON-blob table it replaced is
gone.

## 7. Performance

Apply-to-render is **14–16 ms**, about 30× inside the 500 ms budget. Two things do that
work: collapsed sections render nothing and therefore query nothing, and every statistic is
a `GROUP BY` in SQLite rather than JavaScript over 30,850 objects.

The page uses React **production** builds throughout: `client_dashboard.html` itself loads
`vendor/react.production.min.js` and `vendor/react-dom.production.min.js`, so there is no
dev-to-prod swap anywhere in the build.

## 8. URLs and AGOL integration

The deep-link contract is frozen:

```
https://<pages-url>/#bid/<BID_ID>
```

for example `#bid/AC334_4`. That opens Bank Explorer directly on that bank. Use it in webmap
popups. Clicking a BID in the query result list opens the same URL in a new browser tab.

## 9. Known characteristics (not defects)

- **~~The aspect chart never shows a north class.~~ FIXED 2026-09-14** — see
  "Aspect correction" in section 11 below.
- **193 of 89,319 zones have landcover summing short of their zone area** (0.46% of total
  area). `preprocess_dashboard.py` maps landcover through a fixed 9-class index and drops
  anything outside it, while the denominator still counts it. Upstream and pre-existing;
  bounded by a test assertion so a real regression would still fail.
- **Recharts prints `defaultProps` deprecation warnings** to the console. Library noise.

## 10. Reference figures

Any change that moves these needs explaining:

| | |
|---|---|
| BIDs | 30,850 |
| Riparian acres | 177,016 |
| Tiers | P1 670 · P2 2,652 · P3 6,989 · P4 2,954 · P5 17,585 |
| Temperature impaired | 2,471 |
| Fecal impaired | 3,667 |
| Sediment impaired | 100 |
| Salmon-bearing | 7,457 |
| P1 acreage | 6,900 |
| Fish access (fish / gradient) | 12,907 / 17,943 |
| Waterbody BIDs (in-channel) | 1,224 |

Tier and fish-access figures above are **post-correction** (September 2026 data corrections,
see section 12). Pre-correction figures — still visible in older docs/reports and in
`BID_Scores_Calculated_20260507.csv` directly — were P1 670 · P2 2,655 · P3 6,991 · P4 2,954 ·
P5 17,580, and waterbody BIDs 1,220.

## 11. Data corrections (September 2026) — dashboard deliberately differs from the scoring CSV

Three approved corrections are applied at build time. Two of them make `tier` and `fish` in
the shipped dashboard **deliberately differ** from `BID_Scores_Calculated_20260507.csv`.
Anyone diffing the two will see 104 banks disagree on fish access and 95 disagree on tier —
this is expected and intentional, not a data bug.

### Fish access override (Fix 1)

The project lead ruled the **GIS feature layer** (`TP_Split_JOIN_20260507.csv`, the
`Fish_simple` column) authoritative for fish access, not the May-7 scoring table's
`Fish_simple` pull, which is stale relative to the GIS layer.

- **Why:** the scoring CSV's fish-access value was pulled at an earlier point than the GIS
  layer and has drifted out of sync on a subset of banks.
- **How:** `tools/make_fish_override.py` (a one-off script, not part of the build) diffs the
  GIS layer against `site/data/bids.sqlite` and writes `data_overrides/fish_access_override.csv`
  — a small, auditable, committed CSV (`bid,fish_gis,fish_scoring`), so the build never depends
  on the 40 MB GIS export directly. `build_client_site.py` applies it after the `bids` table is
  populated, then **recomputes `tier` for every bank** from the corrected `fish` value using the
  exact ladder in `preprocess_dashboard.py`'s `assign_tier()` (reimplemented in
  `build_client_site.py`'s `assign_tier()`, guarded by a mandatory 100%-reproduction check
  against the unmodified data before any override is applied).
- **Affected banks:** exactly **104** disagree on fish access (a clean 52/52 swap —
  `fish → gradient` on 52 banks, `gradient → fish` on the other 52). Because fish access feeds
  the tier ladder, this re-tiers **95** banks (some of the 104 don't change tier, because
  Chinook-in-Nooksack banks are already tiered on chinook/temperature alone, independent of
  `fish`).
- **Tier counts, before → after:**

  | Tier | Before | After |
  |---|---|---|
  | P1 | 670 | 670 |
  | P2 | 2,655 | 2,652 |
  | P3 | 6,991 | 6,989 |
  | P4 | 2,954 | 2,954 |
  | P5 | 17,580 | 17,585 |

  Total stays 30,850; fish-bearing stays 12,907 and gradient-accessible 17,943 (the swap is
  symmetric).
- **Permanent fix:** re-run the full scoring/preprocessing pipeline with the corrected
  fish-access layer feeding `Fish_simple` from the start, so `BID_Scores_Calculated_*.csv`
  itself carries the right value and this override becomes unnecessary. Until then, regenerate
  `fish_access_override.csv` with `python tools/make_fish_override.py` any time either source
  file is refreshed.

### Waterbody `waterbody_bids` NaN-groupby fix (Fix 2)

`preprocess_dashboard.py` (read-only, under RF_Test) builds `waterbody_bids` via
`groupby(["BID", "Landcover"])`, and pandas drops NaN group keys by default. Four BIDs whose
waterbody rows all have a blank `Landcover` value vanished entirely from the upstream JSON as a
result: **L667_2, L677_2, L684_1, L105_2** (all `Zone == "lake"`). `build_client_site.py` now
builds `waterbody_bids` directly from `BID_ZID_LC_20260501.csv` with a plain-dict accumulation
that has no such NaN special case, retaining all 1,224 waterbody BIDs (up from 1,220).

### Negative canopy height clamp (Fix 3)

A couple of Forest polygons carry a negative `ForestHeight` in the source data
(`BID_ZID_LC_20260501.csv`), which propagated into what was `zone_stats.cht` (previous
minimum: −0.39 ft; the column now lives in the merged `zones` table, see §14) — physically
impossible for a canopy height. Approved by the project lead: the forest-area-weighted `cht`
value is clamped to 0 at the point it's computed in `build_client_site.py`. This is a
**display-layer clamp over a source-data artifact**, not a fix to the source data. 5
(BID, zone) rows were clamped in the September 2026 build.

### Aspect correction (2026-09-14) — Fix 3

`AspectMEANBID` came from ArcGIS Zonal Statistics MEAN over `aspect1.tif` (1.5 ft, derived
from `dtm_resample.tif`). It carried **two independent errors**:

1. **Aspect is circular, and it was averaged linearly.** mean(10°, 350°) = 180°, not 0°.
   Every bank's value collapsed toward south: the field spanned only 25.9°–327.6°, with
   14,992 of 30,850 banks in the south class and **zero in north**.
2. **Flat cells (ArcGIS code −1) were averaged as if −1 were a direction.** This pulled
   flat-dominated banks (mostly lake shores) toward 0°, i.e. a spurious near-maximum *north*
   boost. 141 banks are >50% flat; their median stored aspect is 8.4°, giving cos ≈ +0.99.
   Confirmed: `(n_sloped·mean_sloped + n_flat·(−1)) / n_total` reproduces the stored table
   to 0.0006° median.

Net effect on scoring: `aspect_north_factor = cos(AspectMEANBID)` averaged **−0.774 with
96.1% of banks penalised**, so the north-facing solar boost was suppressed almost everywhere.

**The fix.** `tools/aspect_circular_zonal.py` recomputes per-bank statistics directly from
the raster over `Reach_forReview.gdb\FinalReaches\TP_Split` (the BID source), excluding
flat and NoData cells, and reports the mean of sin and cos per bank. The replacement north
factor is **the cell-wise mean of cos(aspect)**, not cos(circular mean): it is immune to
wrap-around and degrades to ~0 (neutral) when a bank's aspects are genuinely scattered,
which is the honest answer for flat terrain. Runtime ~20 min for 32,145 banks.

`tools/rescore_aspect.py` then replays the downstream chain from `preprocess_dashboard.py`
(FC2 solar → slope → wetland → CI). It **validates first**: it replays the chain from the
original unrounded `AspectMEANBID` and aborts unless it reproduces the stored scores. It
does, exactly, for `aspect_north_factor` / `combined_solar` / `solar_risk`, and to one
rounding unit for the rest (`RP_norm` is only stored to 2 dp).

Result: north factor **−0.774 → +0.009**, banks penalised **96.1% → 48.9%**, and the
compass rose fills all eight sectors. `Priority_Tier` is unchanged by design — it is assigned
from Chinook / Nooksack / temperature / fish-bearing flags with no dependence on RP.

| | mean before | mean after | max up | max down |
|---|---:|---:|---:|---:|
| `solar_push` | 2.74 | 2.98 | +9.70 | −8.19 |
| `RP_final` | 58.19 | 58.40 | +8.74 | −7.38 |
| `RP_S_final` | 58.82 | 59.04 | +8.75 | −7.39 |
| `CI` | 31.48 | 31.69 | +8.10 | −6.50 |

**How it reaches the dashboard.** Two inputs, both regenerable:
- `data_overrides/aspect_override.csv` (committed) supplies `asp`/`af` per BID, overriding
  the upstream `bid_explorer_data.json`, which cannot be regenerated from here (read-only
  RF_Test tree). The build aborts if the override is present but misses any BID.
- `SCORES_CSV` now points at `BID_Scores_Calculated_20260914_circaspect.csv`, the rescored
  S-track. Reverting both lines restores the previous behaviour exactly.

**To regenerate:**
```
python tools/aspect_circular_zonal.py   --banks "..._Project\Reach_forReview.gdb" --layer TP_Split   --raster "..._Project\Rasters\Elevationspect1.tif"   --table  "..._Project\Reach_forReview.gdb" --table-layer AspectByBID   --out aspect_circular_by_bid_YYYYMMDD.csv

python tools/rescore_aspect.py   --scores BID_Scores_Calculated_20260507.csv   --aspect aspect_circular_by_bid_YYYYMMDD.csv   --source-gdb "..._Project\Reach_forReview.gdb" --source-layer TP_Split   --out-scores BID_Scores_Calculated_YYYYMMDD_circaspect.csv   --out-join   aspect_rescore_join_YYYYMMDD.csv
```
`--out-join` is the BID-join table for the hosted GIS layer (new and `_old` values side by
side, plus `RP_final_delta` / `CI_delta`). Requires `geopandas`, `pyogrio`, `rasterio`.

**Caveat worth carrying forward.** Even the circular mean is a weak descriptor here. The
mean resultant length (1 = all cells face one way, 0 = uniform) has a **median of 0.39**, and
opposite banks of the same reach come out only ~71° apart rather than 180°. At 1.5 ft on
bare earth, cell aspect reflects microtopography, not which way the bank faces. For a
channel-shading question the defensible source is **geometric**: reach bearing from the
flowline plus which side the bank sits on. `AspectResultantR` is carried in the join CSV so
low-confidence banks can be identified. This is a known limitation, not a blocker: the
correction removes two arithmetic errors and is strictly better than what it replaces.

## 12. Outstanding

- **Git is now set up (resolved 2026-09-13).** `Final_Build` is a git repository, pushed to
  `https://github.com/esassoc/wria1_riparian`; `site/` is committed and deployed to GitHub
  Pages by GitHub Actions on every push that touches `site/**`. See §14.
- **The knowledge-transfer doc** (`MD/WRIA1_Scoring_Weighting_KnowledgeTransfer.md`) lists
  three HTML deployments. This client build is a fourth and should be added when it ships.
- **Explanatory hover wording is still draft.** Every `TERMS` entry carries a source comment
  saying so (`// Explanatory hovers. Draft wording - confirm against the methods documentation
  before release.`, line ~317). Someone who owns the methods document needs to read each of
  the ~20 entries against it before this ships to the client — none of the wording has been
  checked against that source, only checked for internal consistency.

## 13. Visual system (September 2026 polish)

A ten-task pass (`.sdd/polish-task-1-brief.md` … `-10-brief.md`) rebuilt the client build's
look from scratch. This section is the map of what changed and where it lives, so a future
edit lands in the right place instead of re-deriving the system.

**No ESA branding.** The build originally used ESA's own palette (`esa-navy`, `esa-teal`, …
as literal Tailwind utility classes, plus Raleway/Overpass fonts and the ESA logo). All of it
is gone: this is a client deliverable, not an ESA-branded internal tool, and the client asked
for a look that reads as "their" watershed data, not a consulting firm's report template. A
temporary `esa` key lived in `tailwind.config` from Task 1 through Task 10 specifically so the
migration could happen call-site-by-call-site without anything rendering unstyled mid-plan;
Task 10 deleted that key once the last call sites were gone. `tests/test_visual_polish.py`
asserts both `esa-` and `esa:` are absent from the shipped page, and that none of the six old
ESA hex values (`#1193BA`, `#66CAD8`, `#004562`, `#002D42`, `#F9A134`, `#7F7B7A`) survive
anywhere, including inside dead code.

**Tokens.** Two parallel definitions, kept in sync by hand: the `:root` CSS custom properties
(`--ground`, `--surface`, `--ink`, `--accent`, `--attn`, `--ghost`, the six `--s-*` section
hues, `--lc-rail`/`--lc-cimp` for the two textures) used by plain CSS classes (`.card`,
`.chip`, `.btn`, …), and the `THEME` JS object (same values, camelCase keys, plus a nested
`THEME.sections` map) used by inline styles and chart code. There is no dark mode - light-only
was a deliberate call, not an oversight (see the design-decisions note from 2026-09-09).

**Canonical colour rule.** Every categorical value gets its colour from exactly one place -
the `CATEGORY_COLORS` registry (keyed by attribute, e.g. `CATEGORY_COLORS.tier`,
`CATEGORY_COLORS.srz`) - read through `colorOf(attr, value)`. A tier, an owner, a zoning
class: same colour in the map, the results table, a chip, and every chart, always. Nothing
picks a colour by array index or plot position.

**Dumbbell dots follow the canonical-colour rule too (September 2026 fix).** `KDumbbell`
(the "Mean Restoration Priority by <category>" charts) used to fill every dot in whatever
section hue its call site passed in, so e.g. Tier P1 read crimson on the filter chips, the map,
the results-table pill and the "Selected acres by group" stack bar, but teal in the tier
dumbbell specifically - the one chart where the section hue (Restoration Metrics' teal) won
out over the category's own colour. `KDumbbell` now takes an `attr` prop naming which
`CATEGORY_COLORS` registry entry governs its dots (`tier`, `fish`, `tcat`, `bfw`, `srz`, `mgr`,
`zon`), and the filled dot renders `canonicalColor(attr, r.rawKey ?? r.key, color)` - the
registry colour when one exists, falling back to the chart's section hue otherwise. The
connecting bar and the hollow WRIA dot are unchanged: the bar still encodes direction (section
hue when the selection beats the WRIA baseline, `THEME.ghost` when it doesn't) and the WRIA dot
stays `THEME.ghost` - only the filled dot's colour source changed. Three call sites rename a
row's key for display before it reaches the chart (fish access, the temperature-category chart,
Salmon Recovery Zone), so `toDumbbell` grew an optional `rawKeyFn` argument that maps a
display-renamed key back to the raw registry key without changing what the label shows. Two
dumbbells - solar-push band and wetland connection - carry no `attr` and keep falling back to
their section hue, because neither category has a canonical colour in the registry. See
`docs/VERIFICATION-polish.md` check 3 for the live-DOM confirmation (`#8E2440` in both the P1
stack-bar segment and the P1 dumbbell dot).

**Composition ramp.** `compColor(v)` interpolates between `COMP_POLES.deciduous` (brick, at
-1) through `COMP_POLES.mid` (at 0, "Mixed") to `COMP_POLES.conifer` (teal-green, at +1).
`COMP_POLES.mid` is deliberately the same hex as the Forest landcover colour (`#264914`) - the
UI even labels it "Mixed (0) = the Forest colour" wherever the scale appears. The collision
this fixes: the old ramp centred on a cream/yellow neutral that visually matched the
composition-neutral idea but had nothing to do with what a 0-composition zone actually looks
like on the ground (mostly-forest, evenly split conifer/deciduous), so a reader could not tell
"forest, evenly mixed" from "no forest, all cream ground cover" at a glance. Centring on the
Forest colour removes that ambiguity. This also drove the "no-yellow composition ramp" rule -
yellow is reserved for the landcover ramp's non-forest classes (see below), so the composition
ramp cannot use it without the two scales bleeding into each other.

**Landcover (`LC9`).** Four of the nine classes moved off the old all-green palette
(`Shrub/Woodland`, `Shrub`, `Ground/Herbaceous` now a tan-to-yellow non-forest ramp;
`Gravel/Abandoned Channel` now the blue-slate `#A6C8E0` called out in the design-decisions
note, instead of reading as another shade of green or grey). Two classes carry a texture in
addition to a fill colour, for the CVD/print/forced-colors case where colour alone cannot
carry identity: `Canopy over Impervious` (`.tx-cimp`, a fine dot stipple) and `Railway`
(`.tx-rail`, a cross-hatch). The CSS lives at `/* landcover textures */` near the top of the
`<style>` block; `lcTextureClass(i)` looks up which class index gets which texture class.

**Tier ramp.** `TIER_COLORS` (P1 maroon → P5 blue-grey) is five swatches, and P5 (`#8E9AA1`)
is deliberately desaturated - P5 is "no priority, gradient-accessible only," and reading as
the quietest swatch is the point. `dataviz`'s `validate_palette.js` flags P5 on the chroma
floor and contrast checks for exactly that reason (see `docs/VERIFICATION-polish.md` check
13) - the CVD-separation check, which is the one that actually matters for colour-blind
readers, passes with room to spare (ΔE 14.0/17.6, well above the 8 floor), and every place a
tier colour appears (`TierPill`, the results table) also shows the tier's literal text ("P1"…
"P5"), so identity never depends on the colour alone. This was accepted as-is rather than
changed in Task 10 - re-balancing an established tier ramp late in a ten-task plan risked
touching every panel that already renders it correctly.

**Section hues.** Six hues (`THEME.sections.rest/fish/imp/riv/adm/mod`) tint the six
Summary Stats / BID Query filter-group categories the same way everywhere they appear -
the collapsible section's left rule, its icon tile, its filter-group stripe. `admin` and
`modifiers` sit close enough (ΔE 12.9, below the validator's 15-floor for a normal-vision
hard fail) to warrant a look before this ships broadly; noted here and in the verification
record rather than silently re-picked, since it wasn't in this task's scope to redesign an
established six-hue system that five prior tasks already built against.

**The SVG chart kit.** Summary Stats no longer uses Recharts. Eight custom SVG components
(`KHistogram`, `KDumbbell`, `KHeatmap`, `KHBars`, `KVBars`, `KRateTiles`, `KRose`, `KLcStack`)
replace it there. Recharts remained the right tool for BID Query's map/Restoration-Priority
scatter and a couple of Scoring Lab / Bank Explorer charts, so it is still loaded and still
prints its known `defaultProps` deprecation warnings on those three tabs - Summary Stats is
the one tab that must show *zero* console warnings, and does. The kit exists because Recharts
could not do two things Summary Stats needed: render 26 small multiples fast enough to keep
Apply-to-render inside budget with nothing pre-rendered off-screen, and give category labels
enough control to never clip (`fitLabel`/`CatLabel`, added in Task 5) - a fixed problem on the
Salmon Recovery Zone heatmap/dumbbell and the species bars at tablet width, both re-checked in
this task's verification pass.

**Applied-filters row.** BID Query and Summary Stats both show a row of removable chips
(`summarizeFilters(appliedFilters)`) naming exactly what is currently filtered - "Tier: P1",
"Salmon: yes" - so a user coming back to either tab never has to reconstruct what "the
selection" means from five collapsed filter groups.

**Explanatory hovers.** `Term id="…"` wraps a label in a dotted-underline span that shows a
`.term-pop` definition from the `TERMS` map on both mouse hover and keyboard focus (verified
on the Restoration Priority KPI, a tier pill, the "303(d) category" chart title, and "Buffer
zones" in the rail - see `docs/VERIFICATION-polish.md` check 12). Every `TERMS` entry is
still draft wording per the source comment at line ~317 - it has been checked for internal
consistency, not against the methods documentation, and that review is still outstanding
(carried into section 11 above).

**Full-name rule and the footer glossary.** Column headers, chart titles and filter labels
spell out what they mean ("Salmon Recovery Zone" not "SR Zone", "Final Restoration Priority"
not "RP Final", "Area percentile" not "pctile") - `tests/test_visual_polish.py` asserts a list
of retired abbreviations is absent from the shipped page, including from JS comments, not
just visible text. The three abbreviations that still have to exist somewhere (`WRIA`, `BID`,
`HMZ` - because they are either the product's own name or too long to use inline every time)
are expanded once, in the footer glossary.

**The BID Query rail.** Six collapsible `CollapsibleSection`s (Restoration Metrics, Fish /
Salmon, Impairment, River Context, Administrative, Site Modifiers), each tinted by its section
hue, holding the `FilterGroup` chip groups and range sliders. The `.bq` two-column layout
(rail + map/table) collapses to a single stacked column under the `lg` breakpoint - checked at
the tablet preset in this task's verification pass.

## 14. Build, data shape and deployment (2026-09-13)

1. **Repository.** `https://github.com/esassoc/wria1_riparian`. Live URL:
   `https://esassoc.github.io/wria1_riparian/`. Deep link pattern: `#bid/<BID_ID>`
   (e.g. `#bid/AC100_1`), used in ArcGIS Online webmap popups to open Bank Explorer directly
   on a bank.

2. **One-time setup on a new machine.**

   ```bash
   npm install
   ```

   `python tools/fetch_vendor.py` is **not** needed on a normal clone — `vendor/` (React,
   ReactDOM, prop-types, Recharts, sql.js + wasm) is committed. Only re-run it if a pinned
   vendor version changes.

3. **Rebuild + deploy.**

   ```bash
   python build_client_site.py
   python tests/run_all.py
   git add site
   git commit -m "..."
   git push
   ```

   The content hash in `site/data/bids.<hash>.sqlite.gz` is deterministic **per machine
   only** — it derives from the input files' mtimes, so a fresh clone rebuilds to a different
   hash even with identical data; always build and commit `site/` from the same checkout.

   The push triggers the `pages.yml` GitHub Actions workflow (path-filtered to `site/**`),
   which publishes `site/` to GitHub Pages. A commit that touches only docs, tests, or source
   outside `site/` does **not** trigger a Pages run.

4. **Inputs.**
   - `BID_Scores_Calculated_20260507.csv` — committed.
   - `data_cache/lc_derived_20260501.json` — committed; regenerate with
     `--refresh-lc-cache` only if the 432 MB `BID_ZID_LC_20260501.csv` changes.
   - `RF_Test\MD\bid_explorer_data.json` and `dashboard_data.json` — read-only, on the `U:`
     drive, never copied into this repo.

5. **Shipped schema** (from `build_client_site.py`'s `build_sqlite`, September 2026
   performance pass):

   ```sql
   CREATE TABLE bids (
       bid TEXT PRIMARY KEY,
       rid TEXT,
       wet REAL,
       tier TEXT, srz TEXT, fish TEXT, chk TEXT, mgr TEXT,
       bfw TEXT, bft REAL, hmz INTEGER, zon TEXT,
       cua TEXT, jur TEXT,
       ti INTEGER, tic TEXT,
       fi INTEGER, fic TEXT,
       si INTEGER, sic TEXT,
       ai INTEGER,
       sal INTEGER, sps TEXT,
       asp REAL, af REAL,
       str TEXT, ss INTEGER, zc INTEGER, pc INTEGER, dom TEXT, wt TEXT,
       cx REAL, cy REAL, pf REAL, ps REAL, ph REAL,
       mc REAL, mh REAL, rpsf REAL, rpsa REAL,
       sqft REAL, rpsn REAL, sols REAL, slps REAL
       -- (plus the 6 secondary indexes dropped in the Sep 2026 pass)
   );

   CREATE TABLE zones (
       bid TEXT NOT NULL, z INTEGER NOT NULL, sqft REAL,
       lc0 REAL, lc1 REAL, lc2 REAL, lc3 REAL, lc4 REAL,
       lc5 REAL, lc6 REAL, lc7 REAL, lc8 REAL,
       comp REAL, ht REAL, den REAL, zrp REAL, cstd REAL, cht REAL,
       PRIMARY KEY (bid, z)
   ) WITHOUT ROWID;

   CREATE TABLE waterbody_bids (
       bid TEXT PRIMARY KEY,
       rid TEXT,
       lc TEXT,    -- JSON-encoded array of 9 landcover proportions
       sqft INTEGER,
       wt TEXT     -- 'river' or 'lake'
   );

   CREATE TABLE lab_sample (
       m REAL, d REAL, c REAL, fh REAL, spth REAL, sqft REAL, domain TEXT, zone TEXT
   );

   CREATE TABLE lab_meta (key TEXT PRIMARY KEY, value TEXT);
   ```

   `lc0`…`lc8` on `zones` are **proportions** (0–1 fraction of that zone's area in each of
   the 9 landcover classes), not the raw area figures the pre-Sep-2026 `zone_stats` table
   stored — weighted composition for a selection is
   `SUM(lcN * sqft) / SUM(sqft)` rather than the old `SUM(lcN_sqft)/SUM(sqft)`.

6. **What no longer ships:** `dashboard_data.json` (replaced by `lab_sample`/`lab_meta` and
   the columns already on `bids`); the linear score columns `rp`, `rpf`, `rpa`, `sol`, `slp`
   (dropped — the client page never surfaced them, only the S-curve `rpsf`/`rpsa`/`sols`/
   `slps`); the six `bids` secondary indexes; the in-browser Babel and Tailwind runtimes
   (JSX and utility CSS are compiled at build time); the unpkg/cdnjs third-party script
   hosts (React, ReactDOM, prop-types, Recharts, sql.js now self-hosted under `vendor/`).
