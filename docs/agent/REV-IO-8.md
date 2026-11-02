# REV-IO-8: parser edge cases (2026-11-01 audit, P3)

Branch `fix/rev-io-8-parser-edges`, base `main` 8d29ae5. Tests:
`tests/test_parser_edges.py` (5 tests). All numbers below are *measured*.

## Case 1: `parse_log` header alias collisions

- **Problem.** The `NORM` map sends `Temp`/`Temperature`/`c_temp_mobile` to
  `temp`, `Press`/`Pressure` to `press`, `Vol`/`Volume` to `vol`, `PotEng`/`pe`
  to `pe`. A thermo table with two such columns (also a repeated raw header)
  wrote both into `result[key]`; the last column won silently. Reproduction on
  unmodified code: `Step Temp c_temp_mobile` parsed without error.
- **Change.** After the selected header is chosen, `parse_log` raises
  `ValueError` naming the file, the block index, both raw headers and the key.
  The message contains "alias collision" (the execution layer already pins that
  word in `test_execution_contract`).
- **Decision.** Raise, do not rename. Renaming would add keys and could shift
  which column plain `temp` means. Valid logs are unaffected: both committed
  fixture logs still parse (201 rows each) and the numeric goldens pass.
- **Scope note.** Only the selected (MD) header is checked in `parse_log`; other
  blocks stay in `raw_blocks` unnormalised, and the execution layer already
  checks those.

## Case 2: `compute_density_profile`

- **Problem.** The area and the automatic z range read `fr['box']`, although
  `_orthogonal_box` accepts a frame with only `cell`. Result: `KeyError: 'box'`
  after validation. A zero-frame call with an explicit `z_range` returned zeros
  with `n_frames=0` and no signal.
- **Change.** Both uses take the bounds returned by `_orthogonal_box`. An empty
  trajectory with an explicit range now emits `RuntimeWarning`
  ("Density profile: no frames ...").
- **Decisions.** Warn instead of raise: the explicit-range empty case is
  documented as legal in the docstring, and an existing test pins the
  empty/no-range `ValueError` only. Equality test: cell-only frame vs the same
  frame with `box`, for automatic and explicit range (`array_equal`).
  `_density_options` was not changed.

## Case 3: `DumpReader.index()` frame detection

- **Problem.** `index()` used `mm.find(b'ITEM: TIMESTEP')`, a substring search.
  Streaming needs a whole stripped line. Reproduction: an atom row
  `1 1 ITEM: TIMESTEP 1 2 3`: streaming raises `ValueError` while loading the
  frame; `index()` raised `ValueError` itself, from a bogus frame header.
  (The two paths disagreed on where and why.)
- **Change.** New helper `_find_frame_marker` accepts a hit only at a line start
  where the stripped line equals the marker; other hits are skipped.
  The index now has one frame, and `read_frame` fails on the bad row like
  streaming does.
- **Native parser.** `native/src/lib.rs` has no frame detection. It parses one
  atom block that Python passes in. No Rust change needed. The parity test runs
  streaming and index+`read_frame` on NumPy (`reader._native = None`) and on
  native (loaded `_dumpparse.abi3.so`); it prints a NOTE if native is missing.
- **Limit.** A row that is exactly `ITEM: TIMESTEP` cannot be a valid row (it
  has too few fields), so it is not a supported case.

## Evidence

Per-module command (`sh` wrapper in /tmp; isolated HOME, `LKPR_NO_HISTORY=1`):

    python -W ignore -c "import sys; sys.path.insert(0,'tests'); import test_parser_edges as t; ..."

- Unmodified `lammps_post/` (stash): 4 of 5 fail: `cell_only` (KeyError 'box'), `empty_trajectory` (no
  warning), `dump_index_and_stream` (stream error vs index-error),
  `colliding_headers` (collision accepted). `distinct_headers_keep_their_keys`
  passes both before and after, by design.
- Modified: 5 of 5 pass.
- `LKPR_SLOW=1 python tests/run.py` (module not yet registered): first run 669
  passed, 1 failed (`test_execution_contract.test_file_alias_collisions...`
  expected the word "collision"; fixed by the message text). Final: 670 passed,
  0 failed, 0 skipped; `test_regression_numeric` fast and slow pass.

## Not changed

Goldens, fixtures, Rust, `_density_options`, other analysis functions,
BACKLOG, CHANGELOG, `tests/run.py` (parent registers `test_parser_edges`).
