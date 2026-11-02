# REV-UI-4 — CLI style flags, `--find` and `--batch` failures

Status: fixed and verified at `4a43a2c` (see Verification).

Audit 2026-11-01, P3. Tests: `tests/test_cli_flags.py` (7 tests).

## Part 1 — style flags and `--find` bypassed `onecmd`

**Problem (measured on main 196f597).** `cli.py` called `shell.do_set` and
`shell.do_find` directly. A bad value was not counted as a failure.
`--dpi 0` was skipped by `if args.dpi:`; the process exited 0
(`--dpi 0 --find <dir>` printed only "No LAMMPS files found", exit 0).
An empty `--find` also exited 0.

**Change.** Style flags run through `shell.onecmd('set ...')`. `--dpi` is tested
with `is not None`. A failed style flag exits 1 with the shell's one-line error.
`--find` runs through `onecmd('find <quoted arg>')`, and failures exit 1.

**Decisions.**
- An explicit `--find` with no match is a failure (exit 1). The CLI sets
  `shell.require_find_match = True`; `do_find` then raises `ValueError`.
  Interactive and batch `find` still print "No LAMMPS files found." and succeed.
- Style flags are checked before `--find`; a bad flag stops the run first.

## Part 2 — presentation settings accepted nonsense

**Problem (measured).** `set dpi 0`, `-1`; `fontsize 0`; `linewidth nan/-1`;
`grid_alpha 5`; `figsize 0 5`; `z_focus 5 1` and similar were all accepted.
`figsize` stored width before parsing height.

**Change.** Same pattern as REV-SESSION-1 (`_finite_value`); reject before
any state change. New helper `_positive_int`.

| Setting | Rule |
|---|---|
| `dpi`, `fontsize` | integer >= 1 (no truncation of `1.5`, no NaN/inf) |
| `linewidth`, `markersize` | finite, > 0 |
| `grid_alpha` | finite, within [0, 1] (both ends allowed) |
| `figsize W H` | both finite, > 0; both parsed before either is stored |
| `z_focus lo hi` | both finite, `lo < hi`; exactly two numbers |

`figsize` and `z_focus` with extra tokens (`set z_focus 1 2 3`) were
previously accepted and the third value ignored; now a usage error.
No upper bound is set for dpi/fontsize: the right limit is not physical,
and matplotlib reports unusable sizes itself.

## Part 3 — `--batch` with `--analyze`/`--plot`

**Problem (measured).** One-shot mode returned first, so the batch script was
never run and no message was printed.

**Decision.** Reject the combination: usage error, exit 2, message
`--batch cannot be combined with --analyze or --plot`, nothing runs. A fixed
order would be a guess, and a batch script can contain `analyze`/`plot` itself.

## Evidence (fail → pass)

Run in the worktree with isolated HOME, `LKPR_NO_HISTORY=1`, `MPLBACKEND=Agg`.
- Unmodified `lammps_post/` (measured): 5 of 7 tests FAIL (bad dpi flag, find
  no match, batch combination, presentation validation, valid-flag check).
  Two guard tests pass before and after by design (interactive `find`,
  valid presentation values).
- Modified: 7 of 7 PASS.
- Full fast suite (module not yet registered in run.py): 689 passed, 0 failed, 2 skipped (measured).

## Not changed

Flag names, `set` keys, theme/format handling (argparse `choices` already
validates), interactive `find` output, `--max-frames` (argparse `int`).

## Verification (measured, `4a43a2c`, worktree untouched during runs)

| Run | Tests | post | prep | Evidence |
| --- | --- | --- | --- | --- |
| Native full verifier | 711 passed, 0 failed, 0 skipped | PASS | PASS | `/tmp/opencode/ui4-native/20261102T194120-4a43a2c-full` |
| Forced-NumPy full verifier | 702 passed, 0 failed, 9 skipped | PASS | PASS | `/tmp/opencode/ui4-numpy/20261102T194120-4a43a2c-full` |
| Reference checks | 6/6 PASS, exit 0 | | | `/tmp/opencode/ui4-refs/` |

The forced-NumPy skips are the named native-parity tests.
