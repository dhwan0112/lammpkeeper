# REV-ANALYSIS-6: RDF candidate wrap at extreme image counts

Status: fixed and verified at `2e49191` (see Verification).

## Problem (measured on unmodified code, base `a6d21b0`)
Atom A at x=0, atom B at x=1e16+2, box x in [0.5, 10.5], `r_max` 4,
`pbc=(True, False, False)`. The SciPy path returned all-zero g. The row-wise
fallback counted the pair. Cause: `_rdf_candidate_pairs` wrapped with `x % L` after
`x - lo`. Both are inexact once |x|/L nears 2**53, so cKDTree never nominated the
pair. A random fuzz (300 frames, up to ~3e13 box lengths out, mixed in-box atoms)
gave **1 SciPy/fallback mismatch** on unmodified code.

## Decision
Reject beyond a documented bound, and make nomination safe inside it.

- Bound: periodic coordinates must satisfy |x - lo|/L <= 2**45. This is the
  `_MAX_IMAGE` limit of `lammpkeeper.core.geometry`. Unwrapped trajectories a few
  hundred box lengths out are far inside it. 2**45 (3.5e13) box lengths is not a
  physical input. The message style matches core:
  `periodic image coefficients exceed the 2**45 geometry limit`.
- The check runs in `compute_rdf` before backend selection, so both backends
  accept and reject the same frames, and the ValueError names the timestep.
  `_rdf_candidate_pairs` runs the same check, so pair detection (its other caller)
  is also loud.
- Inside the bound, two exact steps remove the loss. (1) Reduce `x` and `lo`
  separately with `np.fmod` (exact), then combine small numbers, instead of
  `(x - lo) % L`. (2) Widen the nomination radius by `16 * eps * max|coordinate|`.
  The recomputed distance `pos_b - pos_a` rounds at ulp(|x|). Without the widening
  the candidates could miss a pair the fallback bins. Distances are still
  recomputed with the old formula, so binning is unchanged.

Option (b) alone (exact reduction, no limit) was not chosen. The fallback itself
cannot resolve positions at 2**53 box lengths, so accepting them would only
report quantisation noise.

## Change
- `lammps_post/analysis.py`: new `_check_rdf_image_range`; guard call in
  `compute_rdf`; `_rdf_candidate_pairs` uses the check, fmod reduction and padded radius.
- `tests/test_rdf_extreme_wrap.py`: 5 tests.

## Evidence
Failing-first (unmodified `analysis.py` from `a6d21b0` swapped in, new test module):
`test_measured_case_rejected_identically` FAIL,
`test_beyond_image_limit_rejected_identically` FAIL, other 3 PASS (they are
regression guards: moderate and near-limit unwrapping, nonperiodic axis unlimited).
With the fix: **5 passed**.

Fuzz (300 frames, magnitudes 1 to 10**13.5 box lengths): unmodified **1**
mismatch, fixed **0**.

Byte identity for ordinary input: 100 random frames (half in/near box, half
unwrapped up to 300 box lengths), `pbc` periodic-z and slab, SciPy path:
pickled g arrays of old and new code are `cmp`-identical.

Full suite (`LKPR_SLOW=1 python tests/run.py`, isolated HOME, new module not yet registered): **729 passed, 0 failed, 0 skipped**. New module run alone: 5 passed.

## Not changed
`BACKLOG.md`, `CHANGELOG.md`, `tests/run.py` registration, goldens, fixtures,
triclinic path (already limited by core.geometry), nonperiodic axes (no limit).

## Verification (measured, `2e49191`, worktree untouched during runs)

| Run | Tests | post | prep | Evidence |
| --- | --- | --- | --- | --- |
| Native full verifier | 734 passed, 0 failed, 0 skipped | PASS | PASS | `/tmp/opencode/an6-native/20261102T221715-2e49191-full` |
| Forced-NumPy full verifier | 723 passed, 0 failed, 11 skipped | PASS | PASS | `/tmp/opencode/an6-numpy/20261102T221715-2e49191-full` |
| Reference checks | 6/6 PASS, exit 0 | | | `/tmp/opencode/an6-refs/` |

The forced-NumPy skips are the named native-parity tests.
