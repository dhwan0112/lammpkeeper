# GEN-2b — session routing of explicit run metadata

Status: implemented, reviewed and fully verified by the parent;
[PR #49](https://github.com/dhwan0112/lammpkeeper/pull/49).
Branch: `gen/gen-2b-session-metadata` (base main `5dce7f0`, contains GEN-2a).
ADR-0005 steps 3–4. Tests: `tests/test_session_metadata.py` (24 tests, **not yet
registered in `tests/run.py`**, parent-owned).

## Behavior changes

1. `parse_input`: legacy `config['forcefield']` now comes from
   `classify_pair_style` (`ace`/`reaxff`/`hdnnp`/`generic`; `unknown` only with no
   `pair_style`). The substring logic (`'ace' in ps`, `'n2p2'`, ...) is removed.
   Explicit EAM/LJ/hybrid/unknown styles are `generic` (before: `unknown` or, for
   hybrid/filename substrings, a wrong Fe-O family).
2. `parse_input` rejects a repeated `pair_style` or `atom_style` with different
   values (ValueError with path and both values); equal repeats are allowed.
3. Session metadata is resolved by `SessionState.effective_metadata()` and
   published by `shell._publish_metadata()` into the legacy `ff_info` view plus
   `state.run_metadata` (evidence only). Input metadata first; with no input, the
   dump heuristic wrapped as `guessed`. An explicit `pair_style` always replaces
   the heuristic family, including `generic`.
4. Time rule: a guessed dt is used only if the input declares none of
   pair_style/units/timestep (or there is no input). Any partial declaration leaves
   `dt_fs` unresolved unless units+timestep (metal/real) give it, or `set dt`.
   Guessed units never confirm an explicit timestep.
5. `SessionState.dt_fs` raises `ValueError("timestep unresolved: load an input with
   units and timestep, or 'set dt <fs>' (...)")` when unresolved. Every time
   consumer reads this property (MSD, OAR, penetration, dissociation, charge, spin,
   profiles); RDF/density/structure never do. `dt_fs_or_none` is for display.
   `units lj` yields unresolved dt (no invented conversion).
6. Generic family: no heuristic Fe/O atom labels (only explicit labels), no spin,
   no dt default, no ACE/ReaxFF element-slot numbering of element-only dumps.
   Nothing indexes `FORCE_FIELDS['generic']`.
7. `_analysis_species` now uses the effective family (`state.ff`) instead of the
   parsed input's `forcefield`, so overrides and generic apply consistently.
8. Manual overrides `set dt` / `set forcefield` (choices now include `generic`) are
   stored in `state.manual_overrides`, separate from evidence; shown as `[manual]`
   in `info`; warn when they differ from resolved evidence; `set dt` is rejected for
   explicit non-metal/real units. They expire (with a RuntimeWarning) on successful
   input/data/dump load, replace or unload, survive log/manifest changes, are
   restored by the existing load/unload transaction on failure, and `unload all`
   clears them. `set forcefield` failure restores the exact earlier values.
9. Log/input unit or timestep disagreement in `_thermo_plot_metadata` now names
   both sources (paths) and values; load order is irrelevant.
10. `info` lists each metadata field with explicit/guessed/unresolved and source
    plus manual overrides; the dump load line shows the status of family and dt.
11. `lammps_post --input PATH` preloads an input before dump/log/data (help text).

## Fe-O invariance (measured, no rebaseline)

`/tmp/opencode/g2b-evidence/invariance.py` run on a `git archive` of main and on
the branch gives byte-identical JSON (`cmp`): prep-writer inputs for ACE,
ReaxFF2010, ReaxFF2015, the ACE fixture input/dump in both orders, dump-only
sessions, and the full `analyze all` cache. Findings: prep emits
`variable dt equal ...` / `timestep ${dt}`, which resolves to an explicit
timestep (ace 0.25 fs metal; reaxff 0.25 fs real). The full prep ACE input does
not load on main or the branch (`round()` in a variable is unsupported by the
static parser): pre-existing, unchanged, not fixed here.

## Pre-existing tests whose assertions ADR-0005 deliberately changes

`tests/test_run_metadata.py` (GEN-2a) pinned the legacy substring `forcefield`
key "until GEN-2b": `test_legacy_parse_input_values_unchanged` (eam etc. now
`generic`) and `test_legacy_forcefield_still_substring_based_until_gen2b`
(hybrid now `generic`). Not edited; the parent must update them.

## Residual limits

- No dump, no input: legacy session default (`unknown`, metal, 1.0 fs) is kept
  and labelled `guessed` ("legacy session default"); log-only thermo with an
  unconfirmed log dt still warns and uses it.
- `parse_input` still rejects `units lj`; lj is reachable only via an injected
  `RunMetadata` (tested that way).

## Parent integration (2026-11-01, measured)

- Reviewed the state/shell/cli/parser diff (effective metadata resolution,
  `dt_fs` raising when unresolved with `dt_fs_or_none` for display, override
  records, generic handling, `--input` loaded first).
- Two GEN-2a tests pinned pre-GEN-2b behavior on purpose ("until GEN-2b"). Per
  ADR-0005 the parent updated them, keeping main's literal `LEGACY` record and
  listing the three intended `forcefield` differences (`eam`, `filename_trap`,
  `hybrid` → `generic`); the substring test became
  `test_legacy_forcefield_key_is_exact_token_generic_aware`. No numeric value or
  golden changed.
- Fail-before reproduced by the parent: the new module on a `git archive` of
  main gives **0 passed, 24 failed**; on the branch `test_session_metadata` +
  `test_run_metadata` give **47 passed**.
- The single `test_jobs.test_cli_ctrl_c_cancels_owned_job_and_emits_final_snapshot`
  failure the worker saw once was not reproduced by the parent: **0/25** failures
  unloaded and **0/15** under eight busy CPU loops. Its message was not captured;
  if it recurs, record the traceback before changing the test.
- Parent confirmed the worker's side finding: prep's own `ace_oxidation.in` does
  not load in post (`round(...)` in a variable) on main and on this branch.
  Recorded as **REV-IO-7**; not part of GEN-2b.
- Registered `test_session_metadata`; BACKLOG, CHANGELOG and ADR-0005 updated.
- Independent read-only review (parent-commissioned) found, among minor notes:
  (1) units fell back to `'metal'` silently when the input declared other fields
  but not units and no dump was loaded; (2) `set dt` recorded its override before
  publication without rollback. Both fixed: `unit_system` is now `None` (shown
  "unresolved"; thermo plots without log units fail) and the dt path rolls back
  like `set forcefield`. Two new tests fail on `c5d6afb` and pass now. With a
  dump loaded, an undeclared unit is the heuristic's, labelled guessed.
  Also noted: thermo plots in partial-input sessions now raise on unresolved dt
  instead of assuming 1 fs — intended by ADR-0005 and covered by the CHANGELOG.
- Full verifier on `c5d6afb` is **not valid evidence**: the parent edited the
  worktree (review-fix tests and code) while it ran, so it imported a mixed
  tree; its two failures were the new review tests against unfixed code.
  Evidence kept for the record: `/tmp/opencode/g2b-native/20261101T125625-c5d6afb-full`.
- Final full verifier on `c6c3c2a`, worktree untouched during the runs:
  native **638 passed, 0 failed, 0 skipped**; forced NumPy **629 passed, 0 failed,
  9 skipped** (six known native-only checks plus three REV-IO-4 native-comparison
  tests). Post analyses/real plots and prep passed. Evidence:
  `/tmp/opencode/g2b2-native/20261101T130212-c6c3c2a-full`,
  `/tmp/opencode/g2b2-numpy/20261101T130214-c6c3c2a-full`. Native extension not
  rebuilt; pytest, MDAnalysis, Python 3.9 runtime and HPC not run.
