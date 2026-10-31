# REV-SESSION-3 — stale cached results after the dump changed

Status: implemented and fully verified by the parent;
[PR #44](https://github.com/dhwan0112/lammpkeeper/pull/44).

## Problem
Cached families were current on key presence (`_ensure_cache`, direct cache-hit
plot paths) and `SessionState.cache` has no source binding. Measured: load a dump,
`analyze msd --species Fe` (MSD [0, 1/3]); rewrite the file (one final x 4 -> 14);
`plot msd Fe` saved a PNG of the OLD MSD with no warning, while reading the loaded
reader raised "dump source changed" and a fresh reload gave 121/3.

## Decision (minimal; no provenance database, no snapshots)
`SessionState.verify_trajectory_source()` (state.py) calls the loaded reader's
existing stat-based `_check_source()` (dev, inode, size, mtime, ctime; one
`os.stat`, no file read). It runs only when the cache is non-empty and a reader
exists, at the entry of `do_plot` (except `plot recipes|save_defaults`, which
publish nothing), `do_export` (csv, latex, summary) and `_ensure_cache`.
On a changed **or deleted/unreadable** (`OSError`) source it clears the whole
cache (every family derives from the trajectory) and raises `ValueError` telling
the user to `load dump <file>` again. `onecmd` records the failure, so
batch/one-shot exit 1; no artifact is written. Unchanged sources are unaffected.

Out of scope (listed, not handled): log- and data-derived results (thermo,
data-file masses/atoms). Those loaders keep no source signature, so a comparable
check would need new state; in-memory frame lists (no reader) likewise. Also not
covered: a rewrite that restores identical size and mtime/ctime (stat limit, same
as the reader itself).

## Evidence
`tests/test_stale_cache.py` (7 tests; analytic MSD 1 vs 121 for one atom, real
Agg PNG save, FIFO-driven real batch CLI exit code 1). On unmodified code:
2 passed, 5 failed (changed plot, changed export csv/latex/summary, deleted
source, `_ensure_cache` reuse, batch exit code). With the fix: 7 passed. Related
modules (10, `LKPR_SLOW=1`): 102 passed, 0 failed, 0 skipped.

## Parent integration (2026-11-01, measured)

- Rebased (unpublished, no force-push) onto main `b86379b` (PR #43). Registered
  `test_stale_cache`; BACKLOG and CHANGELOG updated.
- Failing-first reproduced by the parent: against main's `shell.py`/`state.py`
  **2 passed, 5 failed**; with the fix **7 passed**.
- Parent review note: on a changed dump the whole session cache is cleared,
  including results derived only from a loaded log (for example performance or
  thermo summaries). That is conservative: those results are recomputed on
  demand from the still-loaded log; nothing stale is published.
- Full verifier on `4642821`: native **582 passed, 0 failed, 0 skipped**;
  forced NumPy **573 passed, 0 failed, 9 skipped** (six known native-only checks
  plus the three REV-IO-4 native-comparison tests). Post analyses/real plots and
  prep passed. Evidence: `/tmp/opencode/rs3-native/20261101T021835-4642821-full`,
  `/tmp/opencode/rs3-numpy/20261101T021837-4642821-full`. Native extension not
  rebuilt; pytest, MDAnalysis and HPC not run.
