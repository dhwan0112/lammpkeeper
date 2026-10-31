# REV-ANALYSIS-3 — density profile option validation

Status: implemented (`aba2c1f`) and fully verified by the parent; publication in progress.

## Scope

Branch `fix/rev-analysis-3-density-options`, implemented on `main` `9b40f04` and
rebased (unpublished, no force-push) onto `6bf1a3d` (PR #36). Addresses
F-ANALYSIS-3: `compute_density_profile(z_range=(1, 1), n_bins=2)` returned
centers `[1, 1]` and density `[NaN, inf]` with NumPy warnings.

## Contract and implementation

A private helper `_density_options` runs before any frame iteration and before
histogram normalization. It raises `ValueError` naming the option for:

- `n_bins` that is not an integer type (bool, float even if integral, string,
  None), or is zero, negative or nonfinite;
- an explicit `z_range` that is not two real numbers (wrong length, bool,
  string), has a nonfinite endpoint, or has `zlo >= zhi`.

Validation applies equally to empty trajectories. `z_range=None` with no frames
now raises a descriptive `ValueError` instead of a `TypeError` on `None`.

Automatic range: it is the union of box z bounds, computed as before. Zero or
nonfinite box lengths are already rejected by the shared orthogonal-box guard
(`box lengths must be finite and positive`) before the range exists, so a
degenerate automatic range cannot occur for accepted frames; a defensive check
raises a clear error if it ever did. Normal numeric results are unchanged.

Shell: no `shell.py` change. `analyze density` and shared-pass jobs already turn
the `ValueError` into a failed command (`last_command_ok` False,
`command_failures` incremented, `RuntimeError` aggregate for shared jobs); the
shell passes no user `z_range`/`n_bins`, so invalid options arise only from
embedding callers. A test confirms propagation and that no cache entry is stored.

## Tests (measured)

`tests/test_density_options.py`, nine tests with arbitrary type IDs (7, 9) and
hand-computed densities. Against the unmodified `analysis.py`: **2 passed,
7 failed** (the two passes are the analytic-values test and the zero-thickness
box pin, which already held). After the fix: **9 passed**. Combined with
`test_audit_analysis`, `test_slab_reference`, `test_triclinic_analysis` and
`test_regression_numeric` (`LKPR_SLOW=1`): **54 passed, 0 failed, 0 skipped**.

## Limits

Only the analysis function is validated. Nonfinite atom z values, `species_type`
and other review items are separate. Fixtures and goldens are unchanged. The
full verifier has not been run here.

## Parent verification (2026-11-01, measured)

- Failing-first reproduced independently by the parent on the rebased branch:
  the new module against main's `analysis.py` gave **2 passed, 7 failed**; with
  the fix **9 passed, 0 failed**.
- Native full verifier: **531 passed, 0 failed, 0 skipped**; post analyses/real
  plots and prep artifacts/script syntax passed. Evidence:
  `/tmp/opencode/ra3-native/20261101T013004-aba2c1f-full`. The run started a
  moment before commit `7066061`, so it records HEAD `aba2c1f` with three dirty
  files; those were the test registration, BACKLOG and CHANGELOG edits committed
  unchanged as `7066061`, and the log shows all nine new tests ran.
- Forced NumPy: **525 passed, 0 failed, 6 skipped** (known native-only checks).
  Evidence: `/tmp/opencode/ra3-numpy/20261101T013006-7066061-full`.
- Native extension: existing ignored build, not rebuilt. Pytest, MDAnalysis and
  HPC were not run.
