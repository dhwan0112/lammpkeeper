# REV-RS-3: lkpr-rs stops the backend's process group when a straggler holds stdout

Status: fixed and verified (PR #88).
Branch: `fix/rev-rs-3-stdout-stragglers` from `22d4ff5` (main after PR #87).
Source: AUDIT-20261104 finding E-4 (P3, a backend that exits normally while a descendant holds stdout open leaves that descendant running).

## Problem

`backend::supervise` kills the backend's whole process group only on the
forced paths (output overflow, deadline). When the leader exited on its own,
`try_wait` reaped it and the loop broke; if a member of its group still held
the stdout pipe, `recv_timeout(STDOUT_CLOSE_WAIT)` expired after 5 s and
`backend_stdout_held_open` was reported (exit 1), but no signal was sent, so
the straggler kept running and the reader thread stayed blocked until it
exited. The comment on `terminate` ("killing the group even after the leader
exited stops members that could hold the stdout pipe") did not apply to this
path. Reproduced on the `22d4ff5` binary with a fake backend that leaves
`sleep 30` in the background: exit 1 after 5.03 s, holder still alive.

A straggler also inherits the CLI's stderr (`Stdio::inherit`), so when
`lkpr-rs` runs inside a pipeline the consumer's read of that stderr pipe is
blocked until the straggler exits, which the bounded report alone did not fix.

## Change

- `supervise` detects the exit without reaping it (`exited_unreaped`, waitid
  WNOWAIT, already used by `terminate`), so the leader's pid keeps the group
  id reserved while the group may still have members.
- When the pipe is still open after `STDOUT_CLOSE_WAIT`, the normal path
  calls the new `stop_group`: SIGTERM to the group, wait up to `KILL_GRACE`
  (2 s) for the pipe to close, then SIGKILL to the group. The leader is
  reaped afterwards. The forced paths already did this in `terminate` and are
  unchanged.
- The run is still a failure (exit 1); the message now reads
  `backend_stdout_held_open: the backend exited but another process kept its
  output open; the backend's process group was signalled and no result was read`.
- Docs: module header, `STDOUT_CLOSE_WAIT`, `Outcome::stdout_held_open`.

## Decisions

- Kill, not just report. The audit left it as a design choice; the orphan has
  no owner once `lkpr-rs` returns, the Python backend (EXEC-2) already gives
  its own children separate pipes, and the forced paths already kill the
  group, so a straggler on this path is a backend fault, not a feature.
- Still exit 1 even when the holder honours SIGTERM and the full stdout then
  arrives within the grace. The bytes are discarded: a result read only after
  signalling the backend's group could include output from the straggler, and
  the backend broke the contract either way. Nothing in the Python backend
  produces this situation in normal operation.
- Timing: at most `STDOUT_CLOSE_WAIT` + `KILL_GRACE` = 7 s after the backend
  exits, versus 5 s before. A Ctrl-C during that wait is recorded but not
  acted on, as before; the backend has already exited and the run fails
  regardless (review finding, no change).
- Out of scope: a holder that left the backend's process group or session
  (`setsid`, Python's `start_new_session=True`) is not reachable by a group
  signal; it stays reported as held open and keeps running. The message
  therefore says the group was signalled, not that every holder was stopped.
- `jobs.py` (the Python side) is consistent with this: `_cleanup` signals
  the job's group and `start_new_session=True` puts the LAMMPS child in its
  own session; the module docstring and the constants describe that
  behaviour, so no Python change is needed for E-4.

## Verification

| Check | Result |
|---|---|
| `cargo fmt`, `cargo clippy --offline --all-targets` | clean |
| `cargo test --offline` | 6 unit + 19 integration passed, 0 failed |
| `tests/cli.rs::stdout_held_open_after_exit_is_reported_and_the_holder_stopped` | passes in about 12 s for both holders (`exec sleep 20`; `trap '' TERM; exec sleep 20`): exit 1, message contains `process group was signalled`, elapsed under 15 s, each holder gone; the holders also inherit stderr, so `wait_with_output` returning proves a pipeline consumer is unblocked, and a surviving holder would make the elapsed time about 20 s |
| Same fake against the `22d4ff5` binary | exit 1 after 5.03 s with the old message; holder `sleep 30` still alive (the survivor the old test did not check) |

## Review round

One `worker-readonly` review of the PR diff: four nits. Applied: the message and docs say the group was *signalled* (a holder outside the group is out of reach, noted above); the test holders sleep 20 s and the bound is 15 s so a regression fails fast instead of hanging on the inherited stderr; the test removes its temp dirs. Not applied: polling Ctrl-C during the post-exit wait (no effect on the outcome).
| `HOME=$(mktemp -d) /usr/bin/python3 tests/run.py` module `test_rust_cli` | all PASS |
