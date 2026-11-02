# REV-IO-2 — dump changed during an active `DumpReader` iteration

Status: fixed; verification below.

Finding F-IO-2 in `docs/agent/REVIEW-20261028.md`. Branch `fix/rev-io-2-stream-mutation`, base `94e562f`.

## Problem (measured on unmodified code)
`DumpReader.__iter__` checked the source signature once, at entry. The code
comment said the file "must remain unchanged while the iterator is active".
Nothing enforced it. Reproduction (6 frames of 400 atoms, type 1; take one frame;
append a frame of type 2; drain the iterator):

- the iterator yielded the appended frame and `reader.type_ids` became `{1, 2}`;
- a fresh `DumpReader`/`_check_source()` rejects the same file;
- truncating at a frame boundary ended the pass silently as a short trajectory;
- replacing the file by rename or deleting it was not noticed.

`index()`, `read_frame()` and `LazyFrames` already re-check the source before
publishing (they were not changed).

## Change
`lammps_post/parsers.py`, `DumpReader` only. New `_check_stream_source()`: one
`os.stat`, compared with the construction-time signature
(dev, inode, size, mtime_ns, ctime_ns). A missing file (`OSError`) counts as changed.
`__iter__` calls it:

- after each frame body is read and **before** `_parse_block` (parsing publishes
  `type_ids`/`type_labels`), also for frames skipped by `stride`;
- at end of file, so a truncation cannot look like a complete trajectory.

Error: `ValueError("<path>: dump source changed during reading; create a new DumpReader/index/cache")`.
If a mutated file fails parsing first, the error is replaced by the same
"changed during reading" message (original error chained as `__cause__`).
Frames yielded before the change stay as they were. Atom-row parsing functions are untouched.

## Decisions
- Stat per frame, not per read or per line: ~3 µs per `os.stat` (measured),
  one per frame boundary. Hashing or re-reading was rejected as costly.
- Check after the read and before the parse, so no changed bytes reach type tracking.
- Same signature as REV-SESSION-3; same message prefix ("dump source changed").

## Limits
A stat check is not file locking. A rewrite that keeps the same size, mtime_ns
and ctime_ns is not detected. A change after the last stat but before the
consumer uses an already yielded frame is not detectable. Frames already yielded
are not retracted.

## Evidence
Environment: `. /tmp/opencode/io2-env.sh` (isolated HOME, `LKPR_NO_HISTORY=1`).

- Unmodified `parsers.py` (`git show 94e562f:lammps_post/parsers.py`) with
  `python tests/test_stream_mutation.py`: **3 passed, 6 failed**. Failing: append,
  strided append, truncate, replace by rename, touch, delete. Passing (guards
  that must not change): unchanged exact stream, fixture stream, index/read_frame/LazyFrames.
- With the fix: **9 passed, 0 failed** (native and `LKPR_NO_NATIVE=1`).
- Full suite on the fix, `LKPR_SLOW=1 python tests/run.py`: **711 passed, 0 failed, 0 skipped**
  (native extension available). `test_stream_mutation` is not in `tests/run.py` yet
  (parent registers it), so those 9 tests are not in the 711.
- Forced NumPy, hand-run of `test_dump_reader`, `test_audit_parsers`, `test_stream_mutation`,
  `test_species_metadata`, `test_parser_edges`: 48 passed, 0 failed, 3 skipped
  (named: native-half comparisons, "native dump parser unavailable").
- Unchanged-output check: SHA-256 over atoms, timestep, box and elements of all 350
  fixture frames is `472e9badbecb26ec...` on unmodified and fixed code, native and NumPy.

## Timings (measured, fixture `traj.dump`, 350 frames, full iteration, 5 runs)
| Path | Unmodified min / median | Fixed min / median |
|---|---|---|
| native | 0.838 / 0.894 s | 0.790 / 0.798 s |
| NumPy (`LKPR_NO_NATIVE=1`) | 0.887 / 0.951 s | 0.955 / 0.964 s |

Differences are within run-to-run noise (about +-8%, both signs). Direct cost:
`os.stat` is 2.9 µs; 350 frames add about 1 ms (~0.1%).

## Not changed
`index()`, `read_frame()`, `LazyFrames`/`_FrameStore` (already check the source), atom-row
parsing and projection, `tests/run.py`, BACKLOG, CHANGELOG, fixtures, goldens.
