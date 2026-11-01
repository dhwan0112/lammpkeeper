# VERIFY-REF-2: reference-schema and coverage checks in `verify_refs.py`

Date: 2026-11-02. Branch: `fix/verify-ref-2-schema` (from `main` d552b7b).
Script: `.claude/skills/verify/scripts/verify_refs.py`. Tests: `tests/test_verify_refs.py`.

## Problem (from the 2026-11-01 audit)

1. A compute id with no `references/<id>.json` was silently inactive. The run
   exited 0 and `--doctor` only listed the id as "inactive".
2. `spec_errors` accepted bad files:
   - `reference: {}` passed with "all 0 reference keys".
   - A spec with no `reference` key raised an uncaught `KeyError`.
   - Tolerance keys that match no reference key were ignored.
   - A non-dict `reference`, `kind` or `tolerance` was not rejected.
3. Keys that a compute function returns but the reference does not list were
   never compared and never reported.

## Change

- `MISSING_REFERENCE_ALLOWED` (dict, id -> reason) ships empty. A known compute
  id without a file and not on this list is an ERROR record
  ("missing reference file ... for a known compute function"), exit 1.
- New `load_specs()` reads the reference directory. It adds an ERROR stub for each
  missing id and for each unreadable or non-object JSON file, so one bad file
  does not hide the other checks. `--only <id>` now reaches a missing id (it
  was "unknown check id", exit 2).
- `spec_errors` never raises. It reports: non-object file; missing, non-object
  or empty `reference`; non-object `kind`; non-object `tolerance`; tolerance for
  an unknown key; a non-object tolerance entry; unknown tolerance fields (only
  `abs` and `rel`); negative, boolean or non-numeric tolerance values. The old
  kind and `baseline_commit` rules are unchanged.
- `run_check` sets `unlisted_measured_keys` (also in `results.json`) and turns
  the check into ERROR when it is not empty.
- `--doctor` lists missing references as `MISSING reference (ERROR)` and exits 2
  when any exist. It still ignores `--only`. A missing reference no longer makes
  the doctor fail by itself, so the normal run prints the named ERROR (before,
  an empty reference directory gave "doctor failed", exit 2).
- `--list` exits 1 when a file is missing, unreadable or has schema errors
  (it always exited 0 before).
- `SKILL.md` and `features/README.md` describe the enforced behavior.

## Decisions

- **Unlisted measured keys are an ERROR, not a WARN.** Measured: running the real
  checker showed all six references already list every measured key, so ERROR
  breaks nothing. A WARN would let a new measurement stay uncompared behind a
  green exit 0.
- Unknown tolerance fields and invalid tolerance values are also schema errors.
  This goes slightly beyond the audit list. It is the same typo class
  (`{"tol": 1e-3}` would leave the key at zero tolerance). All committed
  references validate (guard test).
- The allowlist is a code constant, not a JSON flag, so disabling a check shows
  up in review of the script.

## Evidence

All commands use `HOME=$(mktemp -d)`-style isolation (`LKPR_NO_HISTORY=1`).

Fail-first. The new module ran against the original script (stashed the script
change, kept the tests):

    python -W ignore -c "...import test_verify_refs...run every test_*..."
    original script: 12 FAIL, 2 PASS (guards), 14 tests
    new script:      14 PASS

The 2 guards that pass on the original are
`test_matching_measured_keys_still_pass_and_compare_unchanged` and
`test_well_formed_spec_has_no_errors`. They pin behavior that must not change.
`test_json_without_compute_function_still_errors` fails on the original only
because `load_specs` does not exist there.

Real checker:

    python .claude/skills/verify/scripts/verify_refs.py --evidence-dir /tmp/opencode/vr2-evidence
    exit 0, 6 PASS (analytic-msd, analytic-rdf-pair, box-geometry,
    fixture-ace-bulk, fixture-ace-rdf-msd, reference-crystal-fe3o4)

## Not changed

- `references/*.json`, tolerances and `_compare` semantics (one key's tolerance
  still applies to every nested value).
- Compute functions, the evidence layout, the exit codes 0 / 1 / 2 for a normal run.
- `tests/run.py`: the new module is not registered yet (the orchestrator adds
  `'test_verify_refs'` to `MODULES`). Until then `python tests/run.py` does not run it.
- Malformed `id` fields inside a JSON file (the file name stays the key for
  missing-file detection).
