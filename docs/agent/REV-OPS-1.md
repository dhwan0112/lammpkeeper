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
