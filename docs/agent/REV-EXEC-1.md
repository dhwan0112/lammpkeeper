# REV-EXEC-1: backend error code must not forge a cleanup failure

## Problem

`LocalJob._finish` treated any error with `code == 'cleanup_failed'` as a local
cleanup failure. It rewrote `cleanup` to `failed / reaped False` and dropped the
backend response. The envelope validator accepts any bounded string as a backend
error code. So a valid backend `failed` envelope with code `cleanup_failed`
made the snapshot report a cleanup failure that did not happen.

## Change

- `lammpkeeper/jobs.py`: removed the code-based rewrite from `_finish`, and the
  "Known gap (REV-EXEC-1)" comment. Replaced it with a short comment that
  states the rule.
- Why this is enough: the supervisor's own failures are already written to
  `self._data['cleanup']` by `_cleanup_child` before `_finish` runs. The
  rewrite only repeated that record. `_finish` still reads
  `cleanup['error']` (not the error code), so real cleanup failures still
  block a success and drop the backend response.
- `tests/test_jobs.py`: added
  `test_backend_error_code_cleanup_failed_does_not_forge_cleanup_failure`.
- No change to the snapshot schema, public API, or error codes.

## Evidence (measured)

Env: `HOME=$(mktemp -d /tmp/opencode/ex1-home.XXXXXX) TMPDIR=/tmp/opencode LKPR_NO_HISTORY=1 PYTHONDONTWRITEBYTECODE=1`, python from the `chem` env.

- Before the fix, only the new test, run with
  `python -W ignore -c "import sys; sys.path.insert(0,'tests'); import test_jobs as t; t.test_backend_error_code_cleanup_failed_does_not_forge_cleanup_failure()"`:
  `AssertionError` at the `cleanup == {'status': 'complete', ...}` line. The
  snapshot had `cleanup: {'status': 'failed', 'reaped': False, ...}` and
  `backend_response: None`.
- After the fix: all `test_*` functions in `tests/test_jobs.py` and
  `tests/test_execution_contract.py` ran with no failure (50 tests, `ok 50`).
- After the fix: `python tests/run.py` gave `644 passed, 0 failed, 2 skipped`.
  The skips are the opt-in `LKPR_SLOW=1` RDF/MSD golden and RDF oracle tests.

The existing tests for real cleanup failures
(`test_cancel_and_timeout_retain_cleanup_failure_without_stale_success`,
`test_cleanup_oserror_is_retained_in_snapshot_after_cancellation`) still pass.

## Not changed

- The backend validator still accepts any bounded string as an error code.
- The `cleanup_failed` code name is unchanged. A backend may still use it;
  it is now reported only as the backend's error.
- `LKPR_SLOW=1` goldens were not run.
- `BACKLOG.md` and `CHANGELOG.md` were not edited (outside this task's scope).

## Parent verification (measured, `ee5c21f`)

- The parent re-ran the new test against the original `jobs.py` and it failed: cleanup was forged to `failed` and `backend_response` was `None`. With the fix it passed.
- The parent confirmed that `_cleanup` is called only from `_cleanup_child`, which writes the failure record itself.
- Full `/verify-lkpr` results:

| Run | Tests | post | prep | Evidence |
| --- | --- | --- | --- | --- |
| Native | 646 passed, 0 failed, 0 skipped | PASS | PASS | `/tmp/opencode/ex1-native/20261102T033916-ee5c21f-full` |
| Forced NumPy | 637 passed, 0 failed, 9 skipped | PASS | PASS | `/tmp/opencode/ex1-numpy/20261102T033916-ee5c21f-full` |

The 9 skips in the forced-NumPy run are the named native-parity tests.
