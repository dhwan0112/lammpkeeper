# REV-ANALYSIS-1 — selected charge integrity

## Scope and context

Work begins from `84ee8d1` after the 2026-10-29 prior-work review. The backlog
prioritizes scientific/input integrity before GEN-2. This item addresses
F-ANALYSIS-1 only: nonfinite selected charges must not produce plausible
oxidation fractions or invalid means that are reported as successful analyses.

## Contract

- Reject NaN, positive infinity and negative infinity in charges actually used
  by charge evolution, charge-z profiles and oxidation fractions.
- Evolution/OR apply the existing species union and optional inclusive region
  before validating. Do not remove bad values and reduce the denominator.
- Profiles validate metal charges in participating bins. Count-only oxygen and
  unrelated species do not require finite charge; retain upper-bound exclusion
  and metal precedence for overlapping type selections.
- Preserve finite arithmetic, empty selections and missing-charge behavior.
  Unrestricted scalar charge analyses need neither coordinates nor a box.
- Errors identify the analysis and frame. Failed retries invalidate only the
  attempted shell cache. Batch/one-shot entry points report analysis failure.
  Cancelling interactive profile frame selection preserves its previous cache;
  cancellation does not constitute an attempted recomputation.

## Baseline evidence (measured)

- Archived `84ee8d1`, full verifier in mlff with forced NumPy:
  **438 passed, 0 failed, 6 native-only skips**; required analysis summary,
  plots, prep artifacts and job-script syntax passed.
  Evidence: `/tmp/opencode/lkpr-charge-baseline/20261029T171051-nogit-full`.
- The same archived source with a freshly built native extension passed
  **444 tests, 0 failures, 0 skips**, plus the required CLI/prep checks.
  Evidence: `/tmp/opencode/lkpr-charge-baseline-native/20261029T171531-nogit-full`.
- Parent's two session regressions failed before the fix. A real one-shot
  `post --analyze charge` with selected `q=nan` printed a NaN mean and zero
  oxidized atoms, then exited zero. The invalid result was also retained in the
  shell cache rather than rejected.
- Direct analysis regressions: **6 passed, 7 failed** before the fix, then
  **13 passed**. Expanded parent session tests against the archived old source:
  **1 passed, 3 failed** (the pass preserves interactive cancellation).
- Final focused coverage adds a missing-timestep static-profile case: **18
  passed, 0 failed, 0 skipped** across the direct and session modules. Errors
  report an unknown timestep when a static profile provides no time metadata.

## Impact review and limits

Independent source review approved the bounded validation/callsite changes.
Two review findings were resolved with tests: preserve a previous profile when
the user cancels frame selection, and report invalid static-profile charges
without assuming timestep metadata exists.

Affected call paths are direct analysis APIs, shell `analyze charge`,
`analyze charge_z`, `analyze or`, automatic plot computation, shared/sequential
analyze-all and CLI dispatch. Existing shell/CLI exception handling supplies
visible failure; cache invalidation prevents failed retries from retaining a
previous result as current. Valid inputs retain their existing physical meaning:
OR is a partial-charge threshold proxy, not a kinetic rate or formal oxidation
state assignment.

This item adds no minimum-image operation or positional normalization: scalar
charge statistics are independent of PBC and cell shape. Existing slab-only
guards still apply to explicit spatial selections and profiles. Populations
are selected independently per frame, not tracked as an MSD cohort; the
denominator remains the complete selected population. Units, charge thresholds,
species conventions, time conversion and profile binning are unchanged.

Missing-z region requests (REV-ANALYSIS-2), nonfinite spatial coordinates
(REV-ANALYSIS-5), threshold/time parameter validation, general source-cache
provenance, and GEN-2 metadata are separate items. No fixture, golden, accepted
ADR, generated structure, LAMMPS input or job script is changed. No real HPC job
is part of this task.

## Verification procedure

Use mlff Python `/home/kim/miniconda3/envs/mlff/bin/python` with isolated HOME
and `TMPDIR=/tmp/opencode`. Full verification uses
`.cursor/skills/verify-lkpr/scripts/verify.sh full`; NumPy mode additionally sets
`LKPR_NO_NATIVE=1`. The native copy is at
`/tmp/opencode/lkpr-charge-native.epo12p/source`, with the extension built from
the current unchanged Rust sources using Cargo's locked dependencies. The
changed executable/test file hashes are retained in its sibling
`final-source-hashes.json` and match the working tree.

Pytest is supplied from the isolated target `/tmp/opencode/parse1-pytest.pMknwy`
with third-party plugin autoload disabled and `LKPR_SLOW=1`. No system package,
project environment or repository binary artifact is installed/changed.

Initial final-verifier attempts exceeded the shell's 120-second timeout; those
interrupted runs are not counted as passes. Final runs use a 600-second limit.
MDAnalysis is unavailable; no real LAMMPS/HPC execution or visual plot-quality
review is claimed. The verifier's separate known evidence-retention/collision
issues remain tracked in REV-VERIFY-*; this work does not close them.

## Final verification (2026-10-29, measured)

- Native full verifier: **462 passed, 0 failed, 0 skipped**; required analysis
  summary, all expected plots, prep artifacts and job-script syntax passed.
  Evidence: `/tmp/opencode/lkpr-charge-final-native2/20261029T173334-nogit-full`.
- Forced NumPy full verifier: **456 passed, 0 failed, 6 skipped**; the same
  required CLI/prep checks passed. Skips are exclusively native-only tests
  (dump reader, boundary, slab, two species-metadata checks and triclinic IO).
  Evidence: `/tmp/opencode/lkpr-charge-final-fallback2/20261029T173334-84ee8d1-full`.
- Native pytest: **462 passed**, including slow goldens; 79 existing/expected
  metadata and analysis warnings were reported, with no test failure.
- All changed Python files parse with Python 3.9 grammar. `git diff --check`
  passes; fixtures, goldens, ADRs and generated-input/template sources are
  unchanged. Native artifacts remain outside the repository.

## Next bounded target

REV-ANALYSIS-2 remains open: an explicit charge/OR region must not silently
become a global calculation when the z column is missing. Handle it in its own
branch/PR with failing-first tests and preserve the unrestricted scalar path.
GEN-2 remains gated by its proposed ADR and the outstanding integrity review.
