# REV-ANALYSIS-5 — selected nonfinite z integrity

Status: implemented on `fix/rev-analysis-5-nonfinite-z` (based on
`fix/rev-analysis-3-density-options` @ `7066061`); parent verification pending.

## Problem (measured)

Orthogonal 10 A cube, selected oxygen z = `[1, NaN]`, surface z = 5, before the fix:
`compute_oar` gave `n_total=[2]`, `oar=[0.5]`; `analyze_penetration` gave
`frac_adsorbed=[0.5]`; `compute_density_profile(z_range=(0, 10), n_bins=10)`
integrated to 1 atom of 2. No warning in any case. A real dump with a literal
`nan` in the z column reaches the same code (DumpReader, native and NumPy).

## Contract

A NaN/Inf coordinate has an unknown location, so the atom is neither
"unabsorbed" nor "outside the range". Analyses raise `ValueError` naming the
analysis, the timestep and the number of nonfinite selected z values. Only atoms
that contribute are validated; unrelated species, empty selections and finite
results are unchanged. Shared helper: `_require_finite_z` (analysis.py).

## Functions changed

- `compute_oar`, `analyze_penetration`, `analyze_penetration_trend`: selected O z.
- `compute_density_profile`: selected species (all atoms when no species filter),
  both explicit and automatic range; checked before `np.histogram`.
- `analyze_charge_evolution`, `compute_or`: selected-type metals, only when
  `z_range` is given (checked before the slab filter, so a metal of unknown slab
  membership cannot shrink the denominator). Without `z_range` z is not read.
- `analyze_charge_z`: metal and count-only types (both consume z for binning).

## Functions deliberately left

- `analyze_penetration_profile`, `compute_rdf`, `analyze_msd`,
  `detect_o2_dissociation`: already reject nonfinite selected z/positions.
- `analyze_structure`: array-only per-type descriptive extents; a NaN z yields a
  NaN `z_min/z_max/z_mean` for that type (visible, no dilution or dropped count).
  Left unchanged to avoid altering its documented contract; reconsider with the
  structure plotting path if wanted.
- `state.py` surface/penetration helpers (`np.max` over selected z propagates
  NaN visibly) are outside this item's scope.
- Shell/CLI: no change; exceptions from analyses already surface as failed
  commands (REV-ANALYSIS-1 behavior).

## Evidence (measured)

- `tests/test_nonfinite_z.py` (14 tests) on unmodified `analysis.py`:
  **3 passed, 11 failed** (the 3 passes are regression guards: unrelated species,
  empty/finite frames, no-region charge paths). With the fix: **14 passed**.
- Combined run (`LKPR_SLOW=1`; test_nonfinite_z, test_density_options,
  test_charge_integrity, test_charge_region, test_audit_analysis,
  test_slab_reference, test_triclinic_analysis, test_o2_pairing,
  test_regression_numeric): **104 passed, 0 failed, 0 skipped**.
- The literal-`nan` dump test ran with the installed native extension present and
  with `reader._native = None` (NumPy path).
