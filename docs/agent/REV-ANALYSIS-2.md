# REV-ANALYSIS-2 — explicit charge-region integrity

## Scope

Started from `84ee8d1` on `fix/rev-analysis-2-missing-z`. REV-ANALYSIS-1's
selected-charge validation is in separate open PR #26 and is not part of this
branch. This item addresses F-ANALYSIS-2 only: an explicitly requested spatial
selection cannot silently fall back to a global population.

## Contract and implementation

`analyze_charge_evolution` and `compute_or` now raise a descriptive `ValueError`
if `z_range is not None` and `col_idx.get('z') is None`. The diagnostic identifies
the analysis, region parameter and missing column. Validation precedes frame
consumption, geometry inspection, mandatory type lookup and absent-q shortcuts.
Empty trajectories still reject an unrepresentable request. Without a region,
scalar charge calculations still require neither coordinates nor box metadata.

The two production shell callers currently do not pass `z_range`; no shell,
CLI, cache or plotting behavior is edited. With z present, existing slab guards
and absent-q compatibility remain intact. Inclusive endpoints, strict charge
threshold, species unions and selected-population denominators are unchanged.

## Reproduction and targeted checks (measured)

- Initial seven tests against original code: **3 passed, 4 failed, 0 skipped**.
  They reproduce silent global fallback, early iteration, and empty/missing-q
  cases that previously hid the invalid region request.
- After correction, plus a diagnostic-precedence test: **8 new tests pass**.
- Combined with unchanged triclinic analysis regressions: **24 passed, 0 failed,
  0 skipped**. Tests use arbitrary type IDs and independent population arithmetic.
- Independent read-only scope review confirmed validation ordering, preservation
  of unrestricted scalar/absent-q behavior and no required shell changes.

Targeted command (isolated HOME and TMPDIR):

```bash
TMPDIR=/tmp/opencode HOME="$(mktemp -d /tmp/opencode/region-tests.XXXXXX)" \
  /home/kim/miniconda3/envs/mlff/bin/python -c \
  'import sys; sys.path.insert(0,"tests"); import run; run.MODULES=["test_charge_region","test_triclinic_analysis"]; sys.exit(run.main())'
```

## Impact and scientific limits

No numerical algorithm, time conversion, PBC or cell geometry is changed.
Charge/OR populations remain instantaneous per-frame selections rather than
fixed ID cohorts; no atom is dropped to repair invalid input. OR remains a
partial-charge threshold proxy, not a kinetic rate or formal oxidation state.

Invalid range endpoints, nonfinite charges/coordinates, parameter validation,
GEN-2 and other review items remain separate. Fixtures, goldens, accepted ADRs,
generated structures, inputs and job scripts are unchanged. Real HPC work
remains deferred; no LAMMPS/HPC execution is claimed.

## Verification environment

mlff Python 3.11.15 with NumPy 2.4.3, SciPy, ASE and Matplotlib is used for full
verification. Native verification runs in an isolated source copy at
`/tmp/opencode/lkpr-region-native.2WwvbD/source`. Its native Rust source,
Cargo.toml and lockfile are byte-identical to the previously compiled isolated
artifact's inputs; no binary is committed. The changed analysis/test files
are copied from this branch. MDAnalysis is unavailable.

## Final verification (2026-10-30, measured)

- Native full verifier: **452 passed, 0 failed, 0 skipped**.
  Evidence: `/tmp/opencode/lkpr-region-final-native/20261030T124324-nogit-full`.
- Forced NumPy full verifier: **446 passed, 0 failed, 6 skipped**. Skips are
  native-only dump reader, boundary metadata, slab parity, two species-metadata
  checks and triclinic IO.
  Evidence: `/tmp/opencode/lkpr-region-final-fallback/20261030T124324-84ee8d1-full`.
- Both full verifier runs passed persisted analysis/plot checks, required prep
  artifacts and generated job-script syntax checks.
- Native pytest with slow tests enabled: **452 passed**, 77 warnings, 87.61 s.
- Python 3.9 grammar, changed executable/test source equality with the native
  snapshot, and `git diff --check` passed. Fixtures and goldens are unchanged.
- Independent final read-only review approved the implementation and tests
  without blockers. No numerical algorithm or architectural change was needed.

Counts are for this independent branch from main, excluding PR #26's eighteen
tests; they are not a reduction in coverage from that separate branch.

## Next item

REV-ANALYSIS-3: reject invalid density ranges/bin counts before histogram
normalization, in a separate branch/PR with independent finite-profile tests.
