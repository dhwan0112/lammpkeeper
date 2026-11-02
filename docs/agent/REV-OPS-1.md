# REV-OPS-1 — readline history handling in hosted/standalone shells

Split into two PRs. This file is extended by part 2.

## Part 1 — inline hosted command loses the menu history (P2)

### Problem
`lkpr> post info` goes through `LkprShell._enter` inline branch. Creating the
child shell runs `HostedShellMixin._setup_history`, which clears the
process-global readline buffer and loads `~/.lammps-post_history`. Nothing
restored the menu buffer, so unsaved menu entries were lost and `postloop`
then saved the *post* history into `~/.lkpr_history`.

### Decision
Snapshot the in-memory menu history before child construction/dispatch and
restore it in `finally`, including when the child raises.

### Fix
`lammpkeeper/shell.py`: `_snapshot_history` / `_restore_history`, used by the
inline branch of `_enter`. Entry order and unsaved entries are preserved.

### Evidence (measured; isolated HOME, Python 3.11)
- Before (fix stashed): `python -m pytest -q tests/test_history.py` → `2 failed, 4 passed`;
  buffer was `['post_a', 'post_b']` (and `[..., 'child_cmd']` for the raising child)
  instead of `['menu_old', 'menu_unsaved']`.
- After: same command → `6 passed`.
New tests: `test_inline_hosted_command_keeps_menu_history`,
`test_inline_hosted_command_restores_menu_history_when_child_raises`
(skip with reason `readline not available` where readline is missing).

### Limits
- The child's own new history from an inline command is not persisted to its file
  (previously it was not either; only `_run` saves child history).
- Snapshot restores text entries only (readline has no public API for timestamps).

## Part 2 — bounded startup read and standalone callback isolation

### Problem
- `_setup_history` and `LkprShell._load_history` read the whole history file;
  `set_history_length` only bounded writes, so a 5000-line file lived fully in memory.
- Every standalone shell registered an atexit hook on each setup and all
  instances wrote the one process-global readline buffer, so with two
  instances each file received the last-loaded instance's commands.

### Decision
Bound the loaded buffer after loading, via readline entries (safe w.r.t. readline
escaping; no custom tail reader). Give each instance ownership semantics and an
isolated exit hook.

### Fix
- `hosted.load_history_bounded(path)`: clear, read, keep the newest `HISTORY_LENGTH`
  entries; used by hosted shells and `LkprShell._load_history`.
- Buffer owner tracking: when a new standalone shell takes the buffer, the previous
  owner's entries are parked on it; at exit a non-owner writes its parked entries
  (live buffer swapped out and restored), the owner writes the live buffer.
- `_atexit_callback` registered once per instance (`_run_exit_save`), which catches
  `Exception`, prints a one-line stderr warning and never raises.

### Evidence (measured; isolated HOME, Python 3.11, readline = GNU)
- Before (lammpkeeper/ stashed): `python -m pytest -q tests/test_history.py` →
  `5 failed, 6 passed` (startup bound x2, two-instance isolation, failing callback,
  and the round-trip test which fails on the missing `load_history_bounded` import).
  Log: /tmp/opencode/ops1b_before.log (run with the code still unfixed).
- After: same command → `11 passed`.
- `test_no_history_env_leaves_home_untouched` still passes.

### Limits
- readline still parses the entire file once at startup (transient cost); only
  the resident buffer is bounded. A tail reader was not written to avoid
  re-implementing readline's file format.
- GNU readline's history file has no newline escape: a multi-line entry is split on
  reload. This predates this change and is not claimed fixed; the round-trip test
  covers backslash/Unicode/quote entries only.
- Entries typed in a non-owner instance after it lost the buffer are not tracked
  (all typing goes to the global buffer, owned by the latest instance). This
  matches real use of one standalone shell per process.
