# REV-PREP-1 — refuse unsafe copyback destination symlinks

Status: implementation and full verification complete; publication in progress.
Baseline: merged main `2ad45edb5bb93cd53e15bf5b588f96dfe2184bd7` (PR #23).
Branch: `fix/rev-prep-1-copyback-symlinks`.

## Approval and bounded scope

The maintainer explicitly approved changing generated job-script copy behavior
on 2026-10-28 and requested continuing roadmap/log updates. Actual HPC execution
is **not** approved or performed here. Site defaults, module/compiler settings,
LAMMPS inputs, generated structures, species/FF conventions and numeric goldens
must remain unchanged. This item addresses the remaining P1 from the source review.

The failure is an existing destination output symlink: the successful-job
`cp -a` primitive follows it and overwrites a separate target. Failure-archive
exclusive creation does not protect successful copyback into the working tree.

## Progress / decision log

1. **Approval recorded:** user approved generated copy-behavior changes, not real
   HPC runs. Backlog item marked in progress on its own feature branch.
2. **Measured failing-first:** staged a full-rendered-script reproduction in
   `tests/pending_review_findings.py`. Only a disposable local job tree and fake
   MPI/LAMMPS/module commands ran. A `trajectory.out` symlink targeted a separate
   temporary file. Assertion failed: `copyback overwrote symlink target`.
3. **Implemented policy:** fail closed on colliding destination symlinks rather than
   delete/replace user links. Inspect all copyback paths before any result copy,
   including hidden/nested entries and dangling/relative links. On rejection,
   preserve scratch, name the unsafe path, return failure and never print success.
4. **Independent work:** a read-only reviewer examines shell lifecycle/boundaries;
   a non-overlapping test owner adds actual rendered-script adversarial cases.
   Parent owns the template, integration, roadmap/evidence and remote actions.

5. **Implemented:** recursive quoted Bash preflight checks `-L` before directory
   tests, including dangling links. Only real source/destination directory merges
   recurse; source symlinks are preserved by the unchanged `cp -a`. Complete the
   entire preflight before the single result-copy command. `COPY_OK` requires
   successful preflight and copy, retaining existing failure/cleanup semantics.
6. **Review follow-up:** reject named root links after removing trailing slash
   and `/.` spellings; positive real-directory cases use the same suffixes.
   Ancestors remain explicitly trusted, not a pathname-isolation guarantee.
7. **Integrated:** migrated the failing repro into `tests/test_copyback_safety.py`,
   restored staging byte-for-byte and registered the module. There are **19 new
   regressions**; unchanged job-safety/audit-prep checks plus new tests measured
   **51 passed, 0 failed, 0 skipped** under expanded Python. Every executed job
   uses disposable files, guarded removal, and fake MPI/solver/module commands.
8. **Full verification complete:** independently launched isolated-HOME expanded/
   native run measured **444/0/0**, forced NumPy **438/0/6** and default **427/0/17**
   (passed/failed/skipped). Expanded native/NumPy post analyses, real plots and prep
   syntax/artifacts passed. No actual scheduler or LAMMPS was invoked.
9. **Final scoped review:** the read-only reviewer found no actionable blocker
   after the named-root suffix repair, by code inspection only. Parent owns the
   independent execution evidence and final verification.

### Parent targeted verification command

```bash
HOME="$(mktemp -d /tmp/opencode/rev-prep-1-integrated.XXXXXX)" \
  TMPDIR=/tmp/opencode PYTHONDONTWRITEBYTECODE=1 \
  /home/kim/opt/miniforge3/envs/chem/bin/python - <<'PY'
import sys
sys.path.insert(0, 'tests')
import run
run.MODULES = ['test_copyback_safety', 'test_job_script_safety', 'test_audit_prep']
raise SystemExit(run.main())
PY
git diff --exit-code -- tests/pending_review_findings.py
git diff --check
```

Measured: **51/0/0**, restored staging and whitespace checks passed. An earlier
18-test-owner snapshot ran before implementation and correctly failed 11 new
collision regressions (37/11/2 default; 39/11/0 expanded), while all 32 old expanded
checks passed. That report is historical failing evidence, not final runtime
status: `/tmp/opencode/rev-prep-1-tests.md`. Parent reviewed the full new harness
and independently reran its checks after implementation and root-suffix additions.

## Full verification commands

```bash
PYTHON=/home/kim/opt/miniforge3/envs/chem/bin/python TMPDIR=/tmp/opencode \
  LKPR_VERIFY_DIR=/tmp/opencode/rev-prep-1-rich PYTHONDONTWRITEBYTECODE=1 \
  bash .cursor/skills/verify-lkpr/scripts/verify.sh full
PYTHON=/home/kim/opt/miniforge3/envs/chem/bin/python LKPR_NO_NATIVE=1 \
  TMPDIR=/tmp/opencode LKPR_VERIFY_DIR=/tmp/opencode/rev-prep-1-numpy \
  PYTHONDONTWRITEBYTECODE=1 bash .cursor/skills/verify-lkpr/scripts/verify.sh full
TMPDIR=/tmp/opencode LKPR_VERIFY_DIR=/tmp/opencode/rev-prep-1-default \
  PYTHONDONTWRITEBYTECODE=1 bash .cursor/skills/verify-lkpr/scripts/verify.sh full
```

The verifier internally creates an isolated HOME. Runs started at baseline HEAD
`2ad45ed` with final runtime/test/runner bytes in the working tree; commit
`36c2255` preserves those bytes. Native rebuild, pytest execution, MDAnalysis,
fresh wheel installation, actual HPC/site validation and LAMMPS physics runs
are not claimed.

Default evidence: `/tmp/opencode/rev-prep-1-default/20261028T162716-2ad45ed-full`.
Its 17 named ASE/Matplotlib skips are exactly the list in
[`REV-REF-1.md`](REV-REF-1.md#full-verifier-matrix-parent-measured) (the 16 original
named skips in the source review plus the CIF shell test); all **19** new copyback
checks run without optional packages. Post smoke passed; prep smoke skipped
without ASE.

### Measured full matrix

| Path | Passed | Failed | Skipped | Smoke |
| --- | ---: | ---: | ---: | --- |
| Expanded Python 3.12.14 / NumPy 2.5.3 / native | 444 | 0 | 0 | post analyses + real plots and prep artifacts/script syntax passed |
| Same interpreter, `LKPR_NO_NATIVE=1` | 438 | 0 | 6 | same post/prep smoke passed |
| Default Python 3.14.4 / NumPy 2.3.5 / native | 427 | 0 | 17 | post passed; prep skipped without ASE |

Additional retained evidence:

- `/tmp/opencode/rev-prep-1-rich/20261028T162716-2ad45ed-full`
- `/tmp/opencode/rev-prep-1-numpy/20261028T162716-2ad45ed-full`

Forced NumPy skips (all six pass in expanded/native):

- `test_dump_reader.test_native_parser_matches_loadtxt`
- `test_periodicity.test_native_boundary_metadata_matches_numpy_without_fallback`
- `test_slab_reference.test_slab_native_and_numpy_match_every_reader_access_path`
- `test_species_metadata.test_dump_native_metadata_parity_without_numpy_fallback`
- `test_species_metadata.test_dump_native_raw_type_ids_without_fallback`
- `test_triclinic_io.test_box_aware_real_native_success_matches_numpy_without_fallback`

All 19 new copyback regressions ran in every environment. Missing MDAnalysis and
pytest execution are not included in this passing count; these are named limits,
not silently counted successful integrations. Merged-main verification and PR
links will be recorded when available.

## Preservation evidence (parent measured)

- **76 modules / 1052 definitions**: Python 3.9 grammar accepted, English module/
  definition documentation present. All **37** collected modules registered once.
- Every old test, fixture and golden is byte-identical to baseline except additive
  runner registration; the temporary failing-first staging is fully restored.
- Every AST node in `templates.py` outside `render_run_script` is unchanged,
  including all generated LAMMPS input renderers. No physics code is altered.
- For ACE, ReaxFF 2010 and ReaxFF 2015, the rendered prefix through archive
  selection (site/staging/solver) and existing failure/cleanup tail are byte-
  identical. All three full rendered scripts pass `bash -n` and share the tested
  copyback tail. Only local stubbed jobs execute, never site/scheduler binaries.
- The thesis tag is unchanged at `cdf5c38e975871debf64eb6d810e78a08165c381`.
  User-owned `Claude outputs/` is untouched; no binary/native rebuild is included.

## Intended safety boundary

The working/scratch trees are trusted and stable during local preflight/copy.
A shell preflight is not a filesystem lock or an adversarial race-proof sandbox.
The original finding concerns pre-existing colliding symlinks; mount aliases,
hardlink semantics and arbitrary concurrent mutation are not certified by a
symlink predicate. No blanket claim that every job write is isolated follows
from copyback validation. Ordinary copy errors may still leave partial copies;
complete scratch must remain available whenever recovery fails.

**Separate open hazard (source-inferred):** `exec > >(tee -a "$RUNLOG")` starts
before copyback, and a preexisting `run.log` symlink can receive logging writes.
This item does not change early logging or claim whole-script link isolation.
It is tracked separately as `REV-PREP-5`, with generated-script approval needed
for its own repair. Copyback rejection cannot undo earlier solver/logging writes.

Documentation updates are maintained with the implementation: `BACKLOG.md`,
this work log, `CHANGELOG.md` and the review-resolution record. Full verification
will use isolated HOME and identify optional skips explicitly.
