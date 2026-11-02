# REV-GEOM-1: wrap_positions face convention

Status: fixed and verified at `84f937d` (see Verification).
Branch: `fix/rev-geom-1-wrap-face` from main `a6d21b0`.

**Decision (maintainer, 2026-11-02):** strict [0, 1) and idempotent. The caveat recorded with the decision is that tilted cells do not guarantee exact rounding when converting back to Cartesian coordinates.

## Problem (measured on unmodified code)

`core.geometry.wrap_positions` in a unit orthogonal cell with PBC `(True, False, False)`:
- point `[-1e-17, .25, .5]` wrapped to `[1.0, .25, .5]`;
- wrapping that again gave `[0.0, .25, .5]`.

So the result could land on the upper face, and the function was not idempotent.

**Impact:**
- No RDF or MSD number is affected, because these are equivalent periodic positions.
- The function has no production caller today; only tests use it.

**A limit found while fixing it.** In a tilted cell, a point put exactly on a face can be rebuilt through the tilt and come back about 1e-17 outside [0, 1). A naive re-wrap loop then alternates between two positions one lattice vector apart. Measured on cell lo `(2, -3, 4)`, tilt `(0.7, -0.3, 1.2)`.

## Convention (implemented)

- **Produced fractions:** wrapping produces fractions in [0, 1) on periodic axes. `x - floor(x)` that rounds up to 1.0 is mapped to 0, the same face.
- **Already-wrapped points** are returned unchanged. That makes the function idempotent bit for bit.
- **Orthogonal cells:** `to_fractional(result)` is in [0, 1) exactly. A per-axis fix-up maps a rebuilt point that rounds onto the upper face to `lo`, which converts back to exactly 0.
- **Tilted cells:** `to_fractional(result)` lies in [-tol, 1 + tol), with `tol = 64 · eps · cond(periodic basis)` (below about 1e-12 for ordinary cells). There is no exact arithmetic, as recorded with the decision.
- **Shifts:** only lattice-vector shifts are applied.
- **Poor conditioning:** the existing 2^45 image limit and the conditioning limits still raise. If the result cannot meet the convention, the function raises instead of returning a value.

## Tests

New `tests/test_wrap_face.py` (3 tests), registered in `tests/run.py`. All 3 fail on unmodified code.
- The measured case gives 0.0 and is idempotent.
- Points within 8 ulps of every face, in orthogonal and tilted cells and every PBC subset, satisfy the convention and are idempotent. The shift is a lattice vector, and zero on non-periodic axes.
- Points already inside are returned with unchanged bits.

Extra fuzz, outside the suite: 40 random cells (random tilts, origins and lengths) × 7 PBC subsets × 300 near-face and far points. That is 280 cases with 0 violations.

The related modules (`test_box_geometry`, `test_box_model`, `test_triclinic_io`, `test_triclinic_analysis`, `test_triclinic_session`) pass.

## Not changed

`minimum_image`, `unwrap_step` and RDF/MSD image selection.

## Verification (measured, `84f937d`, worktree untouched during runs)

| Run | Tests | post | prep | Evidence |
| --- | --- | --- | --- | --- |
| Native full verifier | 749 passed, 0 failed, 0 skipped | PASS | PASS | `/tmp/opencode/gm1-native/20261102T223510-84f937d-full` |
| Forced-NumPy full verifier | 738 passed, 0 failed, 11 skipped | PASS | PASS | `/tmp/opencode/gm1-numpy/20261102T223510-84f937d-full` |
| Reference checks | 6/6 PASS, exit 0 | | | `/tmp/opencode/gm1-refs/` |

The forced-NumPy skips are the named native-parity tests.
