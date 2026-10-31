# REV-SESSION-3 — stale cached results after the dump changed

Status: implemented; parent verification pending.

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
