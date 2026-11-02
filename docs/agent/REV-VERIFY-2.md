# REV-VERIFY-2 — verifier evidence directory collision

Status: fixed and verified at `3404ca0` (see Verification).

## Problem

Finding F-VERIFY-1 (`docs/agent/REVIEW-20261028.md`). `verify.sh` built the
evidence path `<root>/<YYYYmmddTHHMMSS>-<sha>-<mode>` and ran `mkdir -p` on it.
Two runs with the same root, SHA, mode and second shared one directory. Their
logs and `summary.txt` overwrote each other. A stale earlier directory with the
same name was also reused.

## Naming decision

- First run keeps the old name: `<stamp>-<sha>-<mode>`.
- On collision: `<stamp>-<n>-<sha>-<mode>`, n = 2, 3, ... (limit 1000).
- The name still ends in `-<sha>-<mode>`, so globs such as `*-<sha>-full` and
  existing citations of the old form keep working.
- The `evidence:` line prints the real directory.

## Change

`.cursor/skills/verify-lkpr/scripts/verify.sh`:

- A name is taken if the directory exists or if its claim file exists.
- The claim file is `<root>/.claims/<name>`, made with noclobber (`O_EXCL`).
  Only the run that creates it may create the directory.
- If every name is taken, or the root cannot be written, the script exits 2
  with a message. It never reuses, overwrites or deletes evidence.
- Why not `mkdir` alone: on this host `mkdir` is uutils coreutils 0.8.0. In a
  loop of 30 trials with 3 concurrent `mkdir` on one path, 3 trials reported
  success to two callers (measured). A first version using plain `mkdir` failed
  the concurrent test about 1 run in 6 for that reason.
- Claim files stay in the hidden `.claims/` directory (small, one per run).

`SKILL.md` describes the new naming. Tests are in
`tests/test_audit_verifier.py`; the `_run_verifier` helper gained `precreate`
and `runs` options.

## Evidence (measured)

Tests added:
`test_verifier_does_not_reuse_existing_evidence_directory` (pre-created
same-name and `-2` directories; expects `-3`, sentinel kept, evidence line
shows `-3`) and
`test_verifier_concurrent_same_second_runs_keep_independent_evidence` (3
concurrent runs, frozen `date`; expects 3 distinct directories, 3 summaries,
all exit 0).

Fail on unmodified `verify.sh` (a6d21b0), run with
`HOME=$(mktemp -d /tmp/opencode/vf2-home.XXXXXX) TMPDIR=/tmp/opencode LKPR_NO_HISTORY=1 PYTHONDONTWRITEBYTECODE=1 python -W ignore -c "import sys; sys.path.insert(0,'tests'); import test_audit_verifier as t; t.<test>()"`:

- reuse test: AssertionError, the sentinel `tests.log` was overwritten with the run's output.
- concurrent test: AssertionError, fewer than 3 summaries.

Pass on the fixed script: both tests print PASS. The whole module passes (14
tests). The concurrent test passed 48 of 48 repeated runs after the claim-file fix.

Other checks:

- `bash -n .cursor/skills/verify-lkpr/scripts/verify.sh`: no output.
- Real run: `PYTHON=/home/kim/opt/miniforge3/envs/chem/bin/python TMPDIR=/tmp/opencode LKPR_VERIFY_DIR=/tmp/opencode/vf2-evid bash .cursor/skills/verify-lkpr/scripts/verify.sh quick`
  exit 0; `PASS tests — 729 passed, 0 failed, 2 skipped`;
  `evidence: /tmp/opencode/vf2-evid/20261102T221103-a6d21b0-quick`.
- `python tests/run.py` (isolated HOME): exit 0, `729 passed, 0 failed, 2 skipped`.
  Named skips: `test_regression_numeric.test_numeric_regression_rdf_msd_slow` and
  `test_audit_rdf_oracle.test_fixture_rdf_matches_explicit_per_frame_pair_normalization`
  (both `LKPR_SLOW=1` not set).

## Not changed

- REV-VERIFY-1 and REV-VERIFY-3 behaviour (mktemp checks, evidence retention).
- No cleanup of old evidence or claim files. `BACKLOG.md`, `CHANGELOG.md`, `tests/run.py` untouched.
- Slow goldens (`LKPR_SLOW=1`) were not run.

## Parent review (2026-11-02)

- **Reproduced the `mkdir` finding.** `mkdir (uutils coreutils) 0.8.0` on this host reported success to two of three concurrent callers in 2 of 30 races. That is why the script claims names with a noclobber file and does not use `mkdir` alone.
- **Re-ran fail → pass on `test_audit_verifier`:** the original script gives 2 FAIL and 11 PASS; the fixed script gives 13 PASS.
- **Related risk, not changed.** The generated HPC job script (`lammps_pre/templates.py`, scratch and destination setup) also relies on exclusive `mkdir`. That is safe with GNU coreutils, the usual tool on HPC nodes, but not with a uutils `mkdir` like this host's. Changing generated job scripts needs maintainer approval (AGENTS.md §8), so this is recorded here and in BACKLOG (REV-PREP-8), not fixed.

## Verification (measured, `3404ca0`, worktree untouched during runs)

| Run | Tests | post | prep | Evidence |
| --- | --- | --- | --- | --- |
| Native full verifier | 751 passed, 0 failed, 0 skipped | PASS | PASS | `/tmp/opencode/vf2-native/20261102T224103-3404ca0-full` |
| Forced-NumPy full verifier | 740 passed, 0 failed, 11 skipped | PASS | PASS | `/tmp/opencode/vf2-numpy/20261102T224103-3404ca0-full` |
| Reference checks | 6/6 PASS, exit 0 | | | `/tmp/opencode/vf2-refs/` |

The forced-NumPy skips are the named native-parity tests.
