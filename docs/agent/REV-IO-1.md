# REV-IO-1 — reject malformed thermo records visibly

Status: implementation and full verification complete; publication in progress.
Baseline: merged main `6bfc87b05f23b9e6fe019636aed15edbbd30a646` (review PR #21).
Branch: `fix/rev-io-1-thermo-row-integrity`.

## Reproduction and bounded correction

The review reproduced this Step-headed table:

```text
run 20
Step Temp PotEng
0 300 -10
10 301
20 302 -12
Loop time of 1 on 1 procs
```

The old parser silently omitted source line 4, returned steps `[0,20]` and marked
the timeline valid. The parent first staged a regression in
`tests/pending_review_findings.py` and measured its failure:
`AssertionError: malformed thermo row disappeared without a diagnostic`.
After implementation the same staged regression passed. It was then moved into
`tests/test_log_integrity.py`, registered in `tests/run.py`, and the staging file
restored byte-for-byte. No old test/fixture/golden expectation changed.

`parse_log` now fails with `ValueError` when a numeric-leading record inside an
active Step-headed table has the wrong field count or a nonnumeric cell. The
error includes file path, one-based source line, header/expected numeric width,
and the offending row. The source file remains intact; the exception points to
its original evidence. No partial result dictionary or apparently valid truncated
history is returned, and no new result key or permissive/strict flag is added.

Validation occurs **before** stage/terminator keyword detection, so a corrupt
cell containing `minimize`, `Loop time`, `cg style`, `ERROR` or a stage label cannot
hide the malformed record. Every active table is checked, including optimizer
and shorter/incompatible layouts that would later be excluded from MD arrays.

This is deliberately bounded: numeric-leading means the first whitespace token
converts with Python `float`. Valid numeric formats, interleaved WARNING lines,
blanks, headers, existing text termination, EOF, stage/unit/timestep metadata,
reset counters and adjacent-block deduplication retain their established behavior.
Nonfinite float-convertible records retain their prior format acceptance; this
item is not general finite-value/physical validation. Nonnumeric-leading text is
not reclassified as corrupted data, and no support for every LAMMPS output mode
or arbitrary concurrent/malformed log structure is claimed. Existing explicit
LAMMPS ERROR handling is unchanged and is not repaired by this item.

## Collected regression coverage

The new module contains 12 collected tests:

- The original failing short-row reproduction.
- Short/long widths with real source line numbers, warning/blank gaps and paths
  containing spaces; full diagnostic evidence.
- Bad cells containing stage/terminator/error keywords.
- First/last/EOF records and signed/scientific/nonfinite-leading token shapes.
- Corrupted minimization and otherwise-unselected incompatible tables.
- Preserved signed/scientific/nonfinite numeric formats, warnings/blanks and EOF.
- Compatible block order, repeated headers, deduplication, source block IDs,
  accumulated elapsed MD steps and explicit units/timestep/wall times.
- Literal reset/minimization/incompatible histories and raw blocks.
- Numeric lines outside tables and existing text diagnostics.
- Real failed shell replacement preserving the old log object/path and cache.
- Real legacy preload and unified batch CLI failures returning nonzero with the
  diagnostic, not mocked parser or renderer success.

All new module/helper/test documentation is English; no generated input,
structure, job script, mapping, native binary, fixture, golden or thesis-tag
change is included. Other review items, including CIF occupancy and symlink
copyback, remain separate and open.

## Measured verification

Parent targeted command, isolated HOME:

```bash
HOME="$(mktemp -d /tmp/opencode/rev-io-1-target-home.XXXXXX)" \
  TMPDIR=/tmp/opencode LKPR_SLOW=1 PYTHONDONTWRITEBYTECODE=1 \
  /home/kim/opt/miniforge3/envs/chem/bin/python - <<'PY'
import sys
sys.path.insert(0, 'tests')
import run
run.MODULES = ['test_log_integrity', 'test_parse_log_merge',
               'test_audit_parsers', 'test_audit_integration',
               'test_regression_numeric']
raise SystemExit(run.main())
PY
```

**Measured: 31 passed, 0 failed, 0 skipped**, including actual Matplotlib integration
checks and unchanged slow RDF/MSD goldens. The staging repro separately failed
before the fix and passed afterward. `git diff --exit-code --
tests/pending_review_findings.py` and `git diff --check` passed.

A parent independent baseline comparison extracted only the old `parse_log`
function from `git show 6bfc87b:lammps_post/parsers.py`, executed it with NumPy and
warnings, then recursively compared **every output field/array/raw block and
warning message** against the new parser for both unchanged ACE logs:

- `regular_MD/log.lammps`: raw lengths `[1,11,201,150]` — identical.
- `spin_equilibration_MD/log.lammps`: `[1,11,201,137]` — identical.

This establishes value preservation for those replay files, not a solver or
physical-time validation. A separate read-only review traced parser state,
source-diagnostic precedence, fixture table boundaries, stage/time/dedup behavior
and shell publication/rollback; it found no actionable scoped regression. That
review did not execute tests. Local test-owner evidence is
`/tmp/opencode/rev-io-1-tests.md`; parent owns final integration checks.

### Full verifier matrix (measured by the parent)

All runs use isolated HOME and include the unchanged slow goldens. HEAD was
`6bfc87b` with the final parser/new-test/runner bytes in the working tree; later
source commits preserve those tested bytes.

| Environment/path | Result | Smoke |
| --- | --- | --- |
| Expanded Python 3.12.14 / NumPy 2.5.3 / native | **405 passed, 0 failed, 0 skipped** | post analyses + real plots and prep artifacts/script syntax passed |
| Same interpreter, `LKPR_NO_NATIVE=1` | **399 passed, 0 failed, 6 skipped** | same post/prep smoke passed |
| Default Python 3.14.4 / NumPy 2.3.5 / native | **389 passed, 0 failed, 16 skipped** | post passed; prep explicitly skipped without ASE |

```bash
PYTHON=/home/kim/opt/miniforge3/envs/chem/bin/python TMPDIR=/tmp/opencode \
  LKPR_VERIFY_DIR=/tmp/opencode/rev-io-1-rich PYTHONDONTWRITEBYTECODE=1 \
  bash .cursor/skills/verify-lkpr/scripts/verify.sh full
PYTHON=/home/kim/opt/miniforge3/envs/chem/bin/python LKPR_NO_NATIVE=1 \
  TMPDIR=/tmp/opencode LKPR_VERIFY_DIR=/tmp/opencode/rev-io-1-numpy \
  PYTHONDONTWRITEBYTECODE=1 bash .cursor/skills/verify-lkpr/scripts/verify.sh full
TMPDIR=/tmp/opencode LKPR_VERIFY_DIR=/tmp/opencode/rev-io-1-default \
  PYTHONDONTWRITEBYTECODE=1 bash .cursor/skills/verify-lkpr/scripts/verify.sh full
```

Local evidence directories:

- `/tmp/opencode/rev-io-1-rich/20261028T115610-6bfc87b-full`
- `/tmp/opencode/rev-io-1-numpy/20261028T115610-6bfc87b-full`
- `/tmp/opencode/rev-io-1-default/20261028T115610-6bfc87b-full`

The six forced-NumPy skips are exactly the native-only checks listed in
[`REVIEW-20261028.md#named-skips-and-unavailable-integrations`](REVIEW-20261028.md#named-skips-and-unavailable-integrations):
`test_dump_reader.test_native_parser_matches_loadtxt`,
`test_periodicity.test_native_boundary_metadata_matches_numpy_without_fallback`,
`test_slab_reference.test_slab_native_and_numpy_match_every_reader_access_path`,
`test_species_metadata.test_dump_native_metadata_parity_without_numpy_fallback`,
`test_species_metadata.test_dump_native_raw_type_ids_without_fallback`, and
`test_triclinic_io.test_box_aware_real_native_success_matches_numpy_without_fallback`.
Default-Python skips are the same four ASE/twelve Matplotlib tests individually
listed in that section; no new integrity test skips. The expanded run passes
all of them. Missing MDAnalysis/pytest paths remain unverified; optional package
absence is not itself a claim that an unlisted test skipped.

Parent source/coverage checks measured **74 Python modules / 992 definitions**,
all with English docstrings and Python 3.9 grammar accepted. Every pre-existing
test/fixture/golden file except additive runner registration is byte-identical
to baseline; the staged file is restored. The thesis tag still resolves to
`cdf5c38e975871debf64eb6d810e78a08165c381`. No lockfile, native binary, mapping or
generated protocol was changed. `git diff --check` passed.

Actual LAMMPS/HPC, native rebuild and exhaustive grammar/physics validation remain
unverified. Manual blast-radius/interrogation review is not a claim that unavailable
project slash commands executed. Other 23 review follow-ups remain open.
