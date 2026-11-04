# REV-IO-10: dump atom rows accept only ASCII space/tab/CR/LF/FF as separators

Status: fixed and verified (see Verification).
Branch: `fix/rev-io-10-dump-whitespace` from main `30f8533`.
Source: AUDIT-20261104 finding E-1 (P2, silent native/NumPy divergence).

## Problem

Three tokenizers touched a dump atom row and did not agree:

- the shared width check (`DumpReader._parse_block`, REV-IO-3) used `str.split()`,
- the NumPy reference used `np.loadtxt(..., delimiter=None)`,
- the native parser (`native/src/lib.rs`) split bytes on `is_ascii_whitespace()`.

`str.split()` and `np.loadtxt` split on Unicode whitespace (`str.isspace`): the
five ASCII separators plus VT (U+000B), FS–US (U+001C–U+001F), NEL, NBSP (U+00A0)
and the Unicode spaces (U+1680, U+2000–U+200A, U+2028/9, U+202F, U+205F, U+3000).
The native split knows only space, tab, CR, LF and FF. A row written with one of
the extra characters therefore passed the width check and was parsed twice with
different results. Measured on unmodified code with a six-column row whose
`type`/`x` separator was U+00A0 and `columns=('x','y','z')`: native returned
`[0.2, 0.3, 0.0]`, the NumPy fallback (`LKPR_NO_NATIVE=1`) returned
`[0.1, 0.2, 0.3]`, neither warned.

## Change

`lammps_post/parsers.py`: `_parse_block` decodes the block and runs
`_foreign_separator()` before `splitlines()`, the width check and either
backend. Any whitespace character outside space/tab/CR/LF/FF raises
`ValueError` naming the file, timestep, row number and code point. The fast
path stays cheap: an all-ASCII block is cleared by `str.isascii` plus five
substring tests (C level); the Unicode regex runs only on suspect blocks.

`native/src/lib.rs`: comment only. The byte split is now documented as exact
because Python guarantees the separator set; no Rust logic or rebuild.

Behaviour table:

| Row separator | Before | After |
| --- | --- | --- |
| space, tab | both backends agree | unchanged |
| CR/LF/FF inside a row | row-count error (`splitlines` boundary) | unchanged |
| VT, FS, GS, RS | row-count error with a misleading message | `U+000B as a separator` error |
| US (U+001F), NBSP, Unicode spaces | silent divergence | `U+00A0 as a separator` error |

LAMMPS writes single spaces only, so valid dumps are unaffected. The tracked
fixtures and goldens are unchanged.

## Tests

`tests/test_dump_whitespace.py` (registered in `tests/run.py`):

- `test_foreign_separator_rejected_on_every_path`: NBSP, EM SPACE, IDEOGRAPHIC
  SPACE, VT and US; full and projected columns; iteration, `read_frame`,
  `LazyFrames` and `parse_dump`; NumPy and native. **Failed before the fix**
  (`numpy/iter: nbsp separator accepted`), passes after.
- `test_tab_separated_rows_identical_on_both_backends`: tabs stay accepted and
  both backends return the written values.

Both tests report a named skip, not a pass, when the native module is absent.

## Verification

`/usr/bin/python3` 3.14, NumPy only, isolated HOME:

| Mode | Result |
| --- | --- |
| `tests/run.py` native | 728 passed, 1 failed, 24 skipped |
| `tests/run.py` `LKPR_NO_NATIVE=1` | 715 passed, 1 failed, 37 skipped |

The single failure in both modes is `test_stale_cache.test_unchanged_source_plot_and_export_still_work`,
which needs pandas (absent on this host); it fails identically on `main`.
`compileall` with warnings as errors and `git diff --check` pass. The full
verifier (`.claude/skills/verify`) was not rerun on this host (no pandas,
matplotlib, ASE).

## Out of scope

The other parser items of AUDIT-20261104 (A-1 `ITEM: UNITS`/`ITEM: TIME`
headers, B-R1 unordered timesteps) and the `lkpr-rs` findings E-2..E-7.
