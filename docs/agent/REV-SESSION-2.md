# REV-SESSION-2 — spin analysis vs. the active species map

Status: implemented and fully verified by the parent;
[PR #40](https://github.com/dhwan0112/lammpkeeper/pull/40).

## Problem
With explicit canonical ACE input and `set types 1=Fe_down 2=Fe_up 3=O`, the
active `SpeciesMap` resolves `Fe_up = {2}`, but `analyze spin` still counted fixed
type 1 as up (`n_up=[2,2]`, `up_fraction=0.667` on the probe) and plots labelled
those counts Fe_up/Fe_down.

## Decision
`analyze_spin_evolution` (analysis.py) stays unchanged: it reads the canonical ACE
type channels from `label_to_type('ace')` (`Fe_up=1`, `Fe_down=2`, `O=3`;
mapping.py, confirmed). `_analyze_spin` in `lammps_post/shell.py` now compares the
active map's `Fe_up` and `Fe_down` selections with exactly those slots before
computing. Any difference (manual override, input/data labels, groups, missing
labels) raises `ValueError` naming the active selections and canonical slots; the
command fails (batch/one-shot exit nonzero) and no `spin` cache entry exists.
The old `spin` entry is dropped at entry, so a failed retry cannot be plotted.
Canonical sessions produce bit-identical results (tested against the kernel and
the committed fixture: 64 up / 128 down at frame 0).

## Rejected alternative
Honoring overrides (feeding the active Fe_up/Fe_down selections to the kernel)
would redefine spin semantics and the canonical convention (a species-mapping
human gate) and would need a kernel API change plus golden review. Not done.

## Cache invalidation (checked)
`set types` calls `_invalidate_metadata` -> `state.clear_cache()`, so a `spin`
result computed before a species change is already discarded; the plot path
(`_ensure_cache('spin', '_analyze_spin')`) then recomputes and hits the new check.
Tested; no new provenance system (REV-SESSION-3).

## Evidence
Tests: `tests/test_spin_species.py` (7). On unmodified code 4 failed, 3 passed
(swap, missing labels, stale-cache retry, batch exit code failed). With the fix
all pass.

## Parent integration (2026-11-01, measured)

- Rebased (unpublished, no force-push) onto main `d72a123` (PR #39, which also
  edits `shell.py` in the separate `set` handler). Registered
  `test_spin_species` in `tests/run.py`; BACKLOG and CHANGELOG updated.
- Failing-first reproduced by the parent on the rebased tree: the new module
  against main's `shell.py` gave **3 passed, 4 failed**; with the fix **7 passed**.
- The worker's one unexplained failure (98/1 when run from `tests/`) was traced
  by the parent to `test_audit_workflow.test_audit_cli_errors_spaces_and_batch_quit`:
  its subprocess `python -m lammps_post` needs the repository root as working
  directory (`No module named lammps_post`). The same test fails the same way on
  unmodified main code from `tests/`, and passes from the documented repo-root
  invocation. Pre-existing working-directory assumption, not caused by this item.
- **First full verifier on `0ea021e` failed (2 tests, both paths):**
  native **556 passed, 2 failed**, NumPy **550 passed, 2 failed, 6 skipped**.
  Evidence: `/tmp/opencode/rs2-native/20261101T014757-0ea021e-full`,
  `/tmp/opencode/rs2-numpy/20261101T014759-0ea021e-full`. Failures:
  `test_slab_reference.test_slab_shell_load_orders_and_shared_reads_preserve_analytic_answers`
  and `test_slab_reference.test_slab_one_shot_batch_exports_current_time_and_results`.
  The TEST-3 slab is dump-only with labels Fe/O and a guessed ACE force field,
  so `analyze all` scheduled spin; the new guard then raised inside the shared
  job runner and failed the whole command. Before this item, that spin job
  silently counted type 2 (O) as Fe_down.
- **Parent fix:** extracted the check into `_spin_channel_mismatch()`. Explicit
  `analyze spin` still raises. `analyze all` now schedules spin only for a
  canonical map and otherwise prints `Skipping spin: <reason>`, matching the
  existing surface-z skip notice. New test
  `test_analyze_all_skips_noncanonical_spin_visibly_and_keeps_canonical` fails on
  `0ea021e` and passes now (8 tests in the module). Targeted rerun with
  `LKPR_SLOW=1` of spin/slab/species-session/audit-workflow/numeric modules:
  **59 passed, 0 failed, 0 skipped**.
- Final full verifier on `306a196` (started after the fix commit):
  native **559 passed, 0 failed, 0 skipped**, forced NumPy **553 passed, 0
  failed, 6 skipped** (known native-only checks); post analyses/real plots and
  prep passed. Evidence: `/tmp/opencode/rs2b-native/20261101T015506-306a196-full`,
  `/tmp/opencode/rs2b-numpy/20261101T015507-306a196-full`. Native extension not
  rebuilt; pytest, MDAnalysis and HPC not run.
