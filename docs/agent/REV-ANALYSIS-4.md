# REV-ANALYSIS-4 — float32 positions in RDF cutoff

Status: implemented; parent verification pending. Branch `fix/rev-analysis-4-float32-rdf`.

## Defect (measured)
Two atoms (types 4 and 9), float32 x = -49.95 and 49.15 (represented
-49.95000076293945 and 49.150001525878906), box [-50, 50], `pbc=(True, False,
False)`, `r_max=0.8999958038330078`, `n_bins=1`. The exact rational MIC distance
of the represented values is 0.8999977111816406 > r_max, so g must be 0.
SciPy candidate path gave `[0.0]`; the forced row-wise fallback gave
`[327483.887...]`; the same positions cast to float64 gave `[0.0]`.

## Cause (inferred, confirmed by the fix)
Position arrays kept the input dtype, so the fallback's MIC subtraction and
cutoff comparison ran in float32 and rounding moved a pair across r_max.

## Fix
`compute_rdf` converts the selected positions to float64 once per frame
(`np.asarray(..., dtype=np.float64)`), so both backends use the represented
input values in float64. float64 inputs are unchanged (`asarray` is a no-op).

## Tests
`tests/test_rdf_precision.py` (5 tests): exact-Fraction oracle, SciPy == forced
fallback, float32 == float64 cast, inside-cutoff pair still counted, random
float32 frames. Before the fix: 3 failed, 2 passed (the two guards pass by
design). After: 5 passed. SciPy-dependent assertions skip visibly if absent.

## float64 bit-identity (measured)
Old and new `compute_rdf` compared with `tobytes()` equality on the committed
fixture (last 2 frames, type sets, both backends) and 40 random float64 frames
x 3 pbc masks x 2 selections x both backends: 484 comparisons, all identical.
No golden or slow RDF fingerprint changed.

## Out of scope: extreme-image float64 (separate cause)
Atom A at x=0, atom B at x=1e16+2 (float64), box x in [0.5, 10.5], r_max 2.1,
n_bins 3, `pbc=(True, False, False)`. Exact distance is 2 (1e16+2 mod 10 = 2),
so bin 2 is populated. Fallback gives `[0, 0, 36.63]` (correct here, by luck of
exact rounding); SciPy gives `[0, 0, 0]` because `_rdf_candidate_pairs` wraps
coordinates with `% L`, which is inexact once |x|/L approaches 2^53, so the pair
is never nominated. This is float64 range loss in the candidate stage, not
dtype; the float64 policy cannot fix it. Left unfixed; suggested follow-up:
reject (or route to an exact reduction) frames whose |coordinate|/L exceeds a
safe bound (about 2^40), loudly.

## Parent integration (2026-11-01, measured)

- Rebased (unpublished, no force-push) onto main `e4de18a` (PR #40);
  `lammps_post/analysis.py` on main is unchanged since the worker's base, so the
  old/new comparison below still applies. Registered `test_rdf_precision`;
  BACKLOG and CHANGELOG updated; the extreme-image case is now backlog item
  **REV-ANALYSIS-6** (P3).
- Failing-first reproduced by the parent with the final five tests: against
  main's `analysis.py` **2 passed, 3 failed**; with the fix **5 passed**. (The
  worker's "4 failed" count included the extreme-image test it later removed.)
- Float64 byte-identity rerun by the parent (`/tmp/opencode/ra4-equal.py`):
  **484** comparisons identical (fixture frames and random frames, SciPy and
  forced fallback, single-type and union selections).
- Full verifier results follow (started after this commit).
