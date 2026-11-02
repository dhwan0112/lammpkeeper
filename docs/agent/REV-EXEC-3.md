# REV-EXEC-3: execution diagnostics

Status: fixed and verified at `1981f70` (see Verification).
Branch: `fix/rev-exec-3-diagnostics` (rebased onto main `5d5fe4a`).

**Decisions (parent, 2026-11-02):**
- **A descendant still holding stdout open DRAIN_WAIT (2 s) after the child exits fails the job** with `invalid_response`, even if the bytes already read form a complete response.
  - Such a process escaped the job's process group, so cleanup cannot confirm it. EXEC-2 requires unconfirmed cleanup to be visible, and the Rust CLI (UI-1) already reports a held-open stdout as a failure.
  - Before this change the job could succeed while the orphan kept running.
- **Normal jobs do not wait.** They reach EOF at once; the 2 s bound applies only in that leak case.

Env for all commands: `HOME=$(mktemp -d /tmp/opencode/ex3-home.XXXXXX) TMPDIR=/tmp/opencode LKPR_NO_HISTORY=1 PYTHONDONTWRITEBYTECODE=1`, chem python.

## (a) `summarize_thermo_file`: original error and `unit_source`

Problem: if parsing failed and the file's stat identity also changed, the
`finally` raised `InputChangedError` and the parse error was only implicit
context. `provenance['unit_source']` was set to `log.unit_system` before
validation, so a failed validation still claimed a unit source.

Change (`lammpkeeper/application.py`):
- `input_changed` stays the reported code. The original error is now chained
  (`raise ... from original`) and named in the message:
  `... no result published (original error: ValueError: <text up to 200 chars>)`.
- `unit_source` is set only after `summarize_thermo` succeeds. On failure it
  stays `unresolved` (the value `_base` sets).
- Audit "trade-off" comments replaced by comments that state the new rule.

Test change that needs justification: `test_warning_retention_and_diagnostic_bounds_on_failure`
used to expect `unit_source == 'log.unit_system'` on a NaN-validation failure.
It now expects `unresolved`. Reason: `unit_source` describes the unit source of a
validated result; no result was published, so no validated source exists. The log
text itself is unchanged and is still in the file.

Evidence (measured): new test
`test_input_changed_keeps_original_parse_error_visible_and_chained`.
Before (application.py/execution.py stashed): FAIL, message was only
`Log stat identity changed while parsing; no result published`. After: PASS.

Not changed: error codes; `_fingerprint` is still a stat identity, not a hash.

## (b) warning overflow notice

Problem: above 64 warnings the notice overwrote the 64th real warning and gave no count.

Change (`lammpkeeper/execution.py`): the list stays at `MAX_WARNINGS` (64)
entries: 63 real warnings plus a final `N additional warnings omitted (warning
count bound reached)`, with N = total - 63. At exactly 64 warnings nothing is
dropped and there is no notice. EXEC-1.md says "explicit notice when additional
warnings are omitted"; this still holds, so the doc is unchanged.

Evidence: `test_warning_overflow_notice_states_omitted_count_and_keeps_bound`
(new) and the updated `test_warning_retention_and_diagnostic_bounds_on_failure`
(69 warnings -> 63 real + `6 additional warnings omitted ...`). Before: both
FAIL. After: PASS. No test pinned the old notice text.

Not changed: `MAX_WARNINGS`, `MAX_DIAGNOSTIC`, the schema.

## (c) post-exit stdout drain

Problem: after the child exits, reading was capped at `TERMINATE_GRACE` (0.15 s).
A large legal response still in the pipe, plus any reader stall longer than
0.15 s, was truncated and reported as `Invalid backend JSON`.

Change (`lammpkeeper/jobs.py`):
- New `DRAIN_WAIT = 2.0`. After the child is reaped, stdout/stderr are read until
  EOF, for at most `DRAIN_WAIT`. The overall job deadline still applies on every pass.
- Once stdout reaches EOF, a still-open stderr is waited for only `TERMINATE_GRACE`
  (diagnostics only).
- If stdout is still open at the bound, the job fails with the existing code
  `invalid_response` and message `<phase> stdout still open 2s after child exit;
  output may be incomplete (a descendant may hold the pipe)`. A child killed by a
  signal still reports `child_crash` first.
- Behaviour change to note: a backend that leaves a descendant holding stdout open
  (outside the child's process group) now fails even if its response was complete.
  Before, that case succeeded when the bytes were all read in 0.15 s.
- `MAX_STREAM_BYTES`, codes and snapshot schema unchanged.

Evidence:
- Natural truncation could not be reproduced on this machine: the pump reads a
  full pipe in about 2 ms, so the old 0.15 s window was never missed in unstalled
  runs. The truncation was reproduced deterministically by injecting a stall.
- `test_large_legal_response_is_read_completely_after_child_exit`: the fake child
  enlarges its stdout pipe (`F_SETPIPE_SZ`), writes a ~900 KiB response and exits;
  `os.read` in the supervisor is stalled 0.5 s then 0.4 s (after reaping), then
  the test runs 20 unstalled repeats that must all succeed.
  Before: FAIL, `Invalid backend JSON: Expecting value: line 1 column 131073
  (char 131072)`. After: PASS.
- `test_stdout_held_open_after_exit_gets_accurate_bounded_diagnostic`: a grandchild
  started with `start_new_session` holds stdout. Before: FAIL (job `succeeded`).
  After: PASS, `invalid_response` with "stdout still open", cleanup `complete`,
  elapsed between `DRAIN_WAIT` and `DRAIN_WAIT + 5` s.
- All `test_*` in `tests/test_jobs.py` and `tests/test_execution_contract.py`: `ok 55`.
- `python tests/run.py`: `672 passed, 0 failed, 2 skipped` (the two `LKPR_SLOW=1` tests).

Not changed: `docs/agent/EXEC-2.md` still states a 0.15 s final pipe drain
(line 108); it should be updated by the maintainer (out of scope for this item).
`LKPR_SLOW=1` goldens not run.

## Verification (measured, `1981f70`, worktree untouched during runs)

| Run | Tests | post | prep | Evidence |
| --- | --- | --- | --- | --- |
| Native full verifier | 691 passed, 0 failed, 0 skipped | PASS | PASS | `/tmp/opencode/ex3-native/20261102T131052-1981f70-full` |
| Forced-NumPy full verifier | 682 passed, 0 failed, 9 skipped | PASS | PASS | `/tmp/opencode/ex3-numpy/20261102T131052-1981f70-full` |
| Reference checks | 6/6 PASS, exit 0 | | | `/tmp/opencode/ex3-refs/` |

The forced-NumPy skips are the named native-parity tests.
