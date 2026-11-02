# REV-IO-3 — dump atom rows must have the header's column width

Status: implemented locally on `fix/rev-io-3-row-width` (base `94e562f`); not pushed.
Finding: F-IO-3 in `docs/agent/REVIEW-20261028.md`.

## Problem (measured on unmodified code)
Header `ITEM: ATOMS x y z`, one row `1 2`, reader `columns=('x',)`:
- native `DumpReader`: returned `[[1.0]]`.
- NumPy (`reader._native = None`): returned `[[1.0]]`.
Only the projected fields were read, so a short row was accepted silently. A long
row was also accepted on layouts without `id`/`type`/`element`, because the
existing width check in `DumpReader._parse_block` ran only when those columns
made the reader split rows.

## Change
`lammps_post/parsers.py`, `DumpReader._parse_block` only. The raw width of every
row is now checked before any projection and before either backend runs. A bad
row raises `ValueError`:
`<file>: malformed atom block at step <t>: row <n> has <w> columns, expected <N>`
(`n` is 1-based inside the frame). All access paths share `_parse_block`:
iteration, `index()` + `read_frame`, `LazyFrames` and `parse_dump`.

## Decisions
- Python-side check, Rust unchanged. One shared check gives the same decision on
  both backends by construction, and needs no change to the `parse_block`
  signature (a stale `.so` stays compatible). `native/src/lib.rs` was not edited.
- Layouts with `id`/`type`/`element` already split rows, so the check reuses those
  lists (cost: one `len` per row). Other layouts split each row once.
- The old message ("wrong column count") had no row number; it was replaced.
  No test referenced it.

## Evidence
- Unmodified `parsers.py`, `tests/test_row_width.py` (2 tests): the bad-width test
  fails on both backends (a short row is accepted or rejected only with an
  unrelated NumPy message that has no row/expected width); the valid-row test passes.
- With the change, same module, native: 2 passed. `LKPR_NO_NATIVE=1`: 1 passed,
  1 named skip (`native parser not built`, raised after the NumPy half ran).
- Full suite with `test_row_width` registered temporarily in `tests/run.py`
  (not committed): `LKPR_SLOW=1 python tests/run.py` **713 passed, 0 failed, 0 skipped**;
  `LKPR_NO_NATIVE=1 LKPR_SLOW=1` **702 passed, 0 failed, 11 skipped**
  (6 native-only, 3 `test_dump_comment_tokens`, 2 `test_row_width`; all pass natively).
- Native `.so` rebuilt with `bash native/build.sh`; gitignored, not committed.

## Timing (measured, best of 7, `regular_MD/traj.dump`, 350 frames, iteration)
| path | before | after |
|---|---|---|
| native | 0.840 / 0.861 / 0.869 s | 0.844 / 0.858 / 0.856 s |
| NumPy | 0.896 / 0.918 / 0.900 s | 0.882 / 0.893 / 0.898 s |

No measurable change (fixture has `id type element`; rows were already split).
Worst case, layout `x y z` only, 200000 atoms, one frame:
native 0.172 -> 0.300 s, NumPy 0.254 -> 0.374 s (about 0.6 us per row). Real
dumps almost always carry `id`, so this layout is rare.
A Rust-side width check would remove that cost but changes the native API.

## Not changed
Rust parser, BACKLOG, CHANGELOG, `tests/run.py`, fixtures, goldens, data/log/input
parsers. Parent must register `test_row_width` in `tests/run.py`.
