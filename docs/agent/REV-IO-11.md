# REV-IO-11: dumps written with `dump_modify units yes` / `time yes` load

Status: fixed and verified (PR #97).
Branch: `fix/dump-units-time-header` from main `7f4d6e4`.
Source: AUDIT-20261104 finding A-1 (P2, visible crash; discards explicit units evidence).

## Problem

LAMMPS writes two optional items before `ITEM: TIMESTEP` (`DumpCustom::header_item`):

- `ITEM: UNITS` + the unit style when `dump_modify units yes` is set. It is
  written once per opened file, because `Dump::openfile()` resets `unit_count`,
  so appended or concatenated output repeats it.
- `ITEM: TIME` + the elapsed time (`{:.16}` format, in the unit style's time
  unit) before every frame when `dump_modify time yes` is set.

`DumpReader._read_layout` accepted only `ITEM: TIMESTEP` as the first non-blank
line, so such a dump failed with `invalid dump header: ITEM: UNITS` before any
frame was read. The stream path and the index path had the same limitation.
The format was checked against the LAMMPS `develop` sources (`dump_custom.cpp`,
`dump.cpp`) on 2026-11-04.

## Change

`lammps_post/parsers.py`:

- `_read_preamble` (text stream; layout preflight and `__iter__`) consumes the
  optional items before a frame marker. `_preamble_before` does the same for
  the mmap index: it walks back from each next `ITEM: TIMESTEP` over at most one
  key/value pair per item, never past the current block start, and the current
  frame's atom block now ends where the next frame's items begin.
- `DumpReader.units` is the unit style, or None. A later `ITEM: UNITS` must
  repeat it. A unit style that first appears after the first frame, a changed
  style, a value that is not one word, a duplicate item before one frame and a
  non-finite or non-numeric time raise `ValueError` naming the frame ordinal.
- A frame that carries `ITEM: TIME` gets a `'time'` key (float). Frames without
  it keep the exact old key set. `DumpIndex.times` and `LazyFrames.times` hold
  the per-frame time, NaN where absent. `DumpIndex.add` takes `time=None`.

`lammps_post/state.py`, `lammps_post/shell.py`:

- `SessionState._dump_units` is set from `reader.units` on `load dump` and
  cleared on `unload dump`.
- `effective_metadata` treats the dump's unit style as explicit evidence
  between the input and the heuristic. It replaces guessed units. Explicit input
  units that differ raise `Conflicting explicit units: dump ... (ITEM: UNITS),
  input ...`, and the load transaction rolls back, in either load order. With an
  explicit input timestep and no input units, dt becomes explicit through
  `derive_dt_fs` (unresolved for styles with no femtosecond conversion, e.g. lj).
- The load summary prints the units status (`real units [explicit]`). The
  thermo log/units conflict message names a dump source as `dump`, not `input`.

Behaviour table:

| Dump header | Before | After |
| --- | --- | --- |
| no optional items | loads | unchanged, same frame keys |
| `ITEM: UNITS` / `ITEM: TIME` | `invalid dump header` | loads on every path; `units`, `time`, `times` |
| units change or appear late | `invalid dump header` | named `ValueError` |
| dump units vs explicit input units differ | n/a | load rolls back with a conflict error |

## Tests

`tests/test_dump_units_time.py` (registered in `tests/run.py`), 13 tests. Every
reader test **failed before the fix** at `DumpReader(path)` with `invalid dump
header: ITEM: UNITS` or `ITEM: TIME`, except
`test_frames_without_time_keep_the_old_key_set` for the plain dump and
`test_units_item_without_timestep_is_still_invalid`, which guard unchanged
behaviour.

- Stream, `read_frame`, `LazyFrames` (cache 0 and large) and `parse_dump` give
  the same timesteps and times; `index.block_end` excludes the next frame's
  items; strided `LazyFrames.times`; CRLF files; Box-model frames; appended
  output with a repeated `ITEM: UNITS`.
- Errors on both stream and index paths for a changed or late unit style, NaN
  and text times, a duplicate `ITEM: TIME` or `ITEM: UNITS`, items after the
  last frame, and a multi-word unit style; blank lines between items agree.
- Session: dump units explicit and shown in the load summary; input timestep +
  dump units gives explicit dt; unload clears the evidence; conflicting input
  and dump units roll back in both load orders; lj units leave dt unresolved;
  a guessed dt is dropped when the dump units contradict the heuristic.

Verification: full runner native 782 passed / 0 failed / 26 skipped, NumPy
(`LKPR_NO_NATIVE=1`) 769 / 0 / 39.

## Follow-up

- B-2 (guessed `dt_fs` provenance) may use `times` to derive or cross-check dt
  from consecutive `ITEM: TIME` values. Not done here: a frame stride between
  dump writes makes the TIME difference `dt × dump interval`, which needs its
  own design.
- A-2 (stream and index paths disagree on blank lines after atom rows) is
  unchanged. Blank lines between the optional items, or between them and the
  marker, are skipped on both paths.
- With `max_frames`, the streaming path stops early and does not check the
  optional items of later frames; the index always scans every frame. This is
  the same as for every other header check (column layout, natoms).

## Review

A read-only review of the first diff found, and this PR fixes:

- A guessed dt was kept while the dump's explicit units contradicted the
  heuristic's unit guess (e.g. an ACE-like dump with `ITEM: UNITS lj`). The
  guessed dt is now unresolved with a note when the two differ.
- The index walk-back stopped at blank lines between items and after two
  items, and ignored items after the last frame, where the stream path skips
  blanks, raises on a third item as a duplicate, and raises at end of file. Both
  paths now agree.
- The frame-0 error cases only reach the constructor; the test now says so
  (every path runs the constructor's preflight).
