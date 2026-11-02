# REV-EXEC-2: CLI error after job start must cancel the job

## Problem

In `lammpkeeper/jobs.py` `main()`, the final
`except (ValueError, OSError, UnicodeError, RecursionError)` also caught errors
raised after `start_job` returned (for example a failed stderr write while
emitting `--events`). It printed a `_submission_failure('invalid_request', ...)`
snapshot, which claims the request failed before submission. The real job, its
non-daemon worker thread and its children kept running until the job timeout.

## Change

- New helper `_cancel_owned_job(job)`: the Ctrl-C cancel-and-wait code moved out
  of `main()` unchanged (SIGINT ignored, `job.cancel()`, bounded wait, detached
  `cleanup_wait_timeout` observation if the wait expires). Ctrl-C and the new
  path now share it, so the bounded interval is the same.
- The wait loop in `main()` has its own `except` for those four error types. It
  sets `local_failure`, cancels the job through the helper, logs a warning, and
  reports the job's real snapshot. The outer handler is now reached only before a
  job exists, so errors there still give `invalid_request`.
- Exit code is 1 after a post-start local failure, even if the job happened to
  succeed first. Final event emission is skipped in that case (stderr may be the
  broken sink).
- `'options' in locals()` replaced by `options = None`.
- Removed the "Known gap (REV-EXEC-2)" comment; `main()` docstring updated.

## Design choices

- Error code: existing `transport_error` (already used for local supervisor
  failures). No new code. If the job ends `cancelled` because of our own cancel,
  `snapshot['error']` becomes `{'code': 'transport_error', 'message':
  'CLI failed after job start: <Type>: <text>'}` on the detached copy; `state`
  stays `cancelled` and `cleanup` is the job's real record.
- If the job had already finished on its own (succeeded, failed, timed out), its
  snapshot is returned untouched. Its genuine error (or none) is not overwritten,
  so a `succeeded` snapshot never carries an error. The local failure is then
  visible only in the nonzero exit code and the log warning.
- Snapshot schema, error code names and exit codes 0/1/130 are unchanged.

## Evidence (measured)

Env: `HOME=$(mktemp -d /tmp/opencode/ex2-home.XXXXXX) TMPDIR=/tmp/opencode LKPR_NO_HISTORY=1 PYTHONDONTWRITEBYTECODE=1`, chem python.

- Test: `test_cli_error_after_job_start_cancels_job_and_is_not_invalid_request`.
  A fake backend blocks in `signal.pause()`; `print` to stderr raises `OSError`
  when the `running` event is emitted.
- Before the fix (jobs.py stashed), run alone: `AssertionError` on
  `snapshot['state'] == 'cancelled'`. The snapshot was a pre-submission failure:
  `state: failed`, `error: {code: invalid_request, ...}`, `request_id: None`,
  `cleanup.status: not_required`.
- After the fix, same command: `ok`. State `cancelled`, error code
  `transport_error` with the OSError text, cleanup `complete`/reaped, child pid
  gone, return code nonzero.
- All `test_*` in `tests/test_jobs.py` and `tests/test_execution_contract.py`: `ok 51`.
- `python tests/run.py`: `651 passed, 0 failed, 2 skipped` (the two `LKPR_SLOW=1`
  golden/oracle skips).

## Not changed

- Errors raised while printing the final snapshot to stdout are still outside any
  handler (unchanged).
- Errors other than the four listed types in the wait loop are not caught
  (unchanged).
- `LKPR_SLOW=1` goldens not run. `BACKLOG.md` and `CHANGELOG.md` not edited.
