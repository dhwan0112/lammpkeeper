# REV-PLOT-2: structure/snapshot plots resolve species exactly; charge plots label the real threshold

Status: fixed and verified (PR #92).
Branch: `rev-plot-2/structure-species-labels` from `cba30dc` (main after PR #91).
Source: BACKLOG REV-PLOT-2 (P2; retained-limit paragraph in
`docs/agent/REVIEW-20261028.md`, audit 2026-11-01).

## Problem

`lammps_post/plotting.py` had three domain assumptions baked into generic
plot code:

- `plot_structure` binned z from `0` to `z.max() + 5` in 2.87 Å steps, so
  atoms with negative z (slabs centred on the origin, cells with a negative
  lower bound, anything after `shift`) were silently dropped from both the
  type histogram and the O histogram.
- `plot_structure` chose the oxygen type by `'O' in name`, which also matches
  `Co`, `NO`, `Mo`, and so on, and when no name matched it took the type with
  the most atoms. The "Fe surface" guide was the highest z among all non-O
  atoms, so a generic A/B map labelled the largest type as oxygen and the
  other as Fe.
- `plot_snapshot` coloured Fe/O by substring as well and, when that failed,
  by "type 1 is Fe, type 2 is O"; every other type was not drawn at all.
- `plot_charge_evolution` and `plot_or` printed a fixed `q > 0.3` in the axis
  label and title even when the analysis had been run with another
  threshold (`set q_threshold`), so the figure contradicted the data it
  showed.

## Change

`lammps_post/plotting.py`:

- `resolve_plot_species(atom_types, species=None)` is the single place that
  decides which types are O and which are Fe for the structure and snapshot
  plots. An explicit `species` snapshot (the session species map) wins per
  name. Otherwise a type counts only when its label is one of the preset
  labels for that element across `FORCE_FIELDS` (`O`; `Fe`, `Fe_up`,
  `Fe_down`), compared exactly. String-keyed element maps (the legacy
  `{'Fe': 'Fe_up', ...}` shape) keep the sorted-element synthesized ids and
  also match on the element key. No substring match, no largest-type fallback,
  no positional fallback. It returns `(o_types, fe_types, labels)`.
- `plot_structure(..., species=None)`: bins are lattice-aligned 2.87 Å bins
  from `floor(z.min()/2.87)` (capped at 0) to `ceil((z.max()+5)/2.87)`, so
  non-negative data keep the exact legacy edges and negative z is covered.
  The O panel plots only resolved O types; without any it prints a warning,
  writes "no O species in the atom type map" into the panel and draws no
  histogram. The guide line is "Fe surface (z Å)" only when resolved Fe
  atoms exist; otherwise a supplied `z_surface` is drawn as a dashed
  "Surface guide (z Å)", and with neither there is no guide and no legend.
- `plot_snapshot(..., species=None)`: Fe and O groups are drawn only when
  resolved; every remaining type is drawn in grey with a legend entry naming
  the leftover labels (`other: Co`). When neither Fe nor O resolves, a
  warning says snapshots show atoms by type only.
- `plot_charge_evolution` and `plot_or` read `q_thr` from the result dict
  for the count-axis label, the normalized-fraction title and the OR title;
  a result without the key (a cache written before this change) keeps the
  `0.3` text, which is the only value such caches could have been computed
  with by default.

`lammps_post/analysis.py`: `analyze_charge_evolution` and `compute_or`
record `'q_thr': float(q_thr)` in their result dicts.

`lammps_post/shell.py`: `_plot_species()` returns
`state.species_map.type_sets()` (the same Fe/O selections every analysis
uses, including the ACE `Fe_up`+`Fe_down` union) or `None` with a warning
when no species map can be built; it is passed as `species=` to all
`plot_structure` and `plot_snapshot` calls (batch, interactive, explicit
indices).

`tests/test_plot_species_threshold.py` (new; recorder backend, no
matplotlib): resolver exactness (`Co`/`NO`/`A`/`B` never resolve, ACE
labels do, explicit selection wins, string-keyed maps), negative-z coverage
with the legacy edges preserved for non-negative data, O panel and Fe
surface from exact species, the no-O and no-Fe paths, the `q_thr` labels
including the legacy fallback, the recorded `q_thr` in both analyses, the
shell wiring (ACE `Fe Mn O` input gives `Fe={1,2}` to both plots) and the
snapshot grouping. `tests/test_charge_integrity.py`: the empty-trajectory
check pops the new `q_thr` key before asserting every array is empty.
`tests/run.py` registers the new module.

## Decisions

- Exact labels, not substrings or positions. Every heuristic the old code
  used produced a confident wrong figure on generic data; an absent species
  is now shown as absent (empty panel with a note, grey "other" points,
  warnings on stdout) rather than guessed. The session species map is
  preferred because it is what the analyses themselves used, so the plot and
  the numbers agree on which atoms are Fe.
- Bin edges stay multiples of the BCC lattice constant and the legacy
  `0, 2.87, ...` grid is unchanged for non-negative z, so existing figures of
  normal slabs are reproduced bin for bin; only atoms that used to vanish are
  added.
- `q_thr` is recorded in the result rather than passed separately, so cached
  results plotted later (and `plot redo`) still carry the cutoff they were
  computed with. Old caches without the key fall back to the default text.
- `plot_structure`'s left panel keeps drawing every type by its label; only
  the O panel and the surface guide depended on species identity.

## Verification

| Check | Result |
|---|---|
| `tests/test_plot_species_threshold.py` (9 tests) | pass |
| `test_species_plot_labels`, `test_audit_workflow`, `test_analysis_params`, `test_charge_integrity`, `test_charge_region`, `test_triclinic_session` | pass (1 matplotlib skip) |
| `HOME=$(mktemp -d) /usr/bin/python3 tests/run.py` | 755 passed, 0 failed, 26 skipped (746/0/26 before) |
| same with `LKPR_NO_NATIVE=1` | 742 passed, 0 failed, 39 skipped (733/0/39 before) |

## Review round

A read-only reviewer read the full diff against the preset tables, the
species map and every caller. It confirmed: `Co`/`NO` are outside the O
label set built from `FORCE_FIELDS`; the new bin edges equal the legacy
`np.arange(0, z.max() + 5, 2.87)` grid for non-negative data and cover the
lowest atom otherwise; the only non-test callers of `plot_structure` and
`plot_snapshot` are the five shell call sites, all of which pass `species=`;
the scalar `q_thr` key does not reach `export` (1-D arrays only) and is
handled by `export summary` (float values). It found no defects and asked
for the shell integration test to be run rather than read; that test is
part of the module and passes in both full runners.
