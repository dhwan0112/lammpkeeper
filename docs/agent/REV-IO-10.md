# REV-IO-10: dump atom rows accept only ASCII space/tab/CR/LF/FF as separators

Status: fixed and verified (PR #83); review follow-up PR #85 (see Follow-up).
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
`ValueError` naming the file, timestep, row number and code point and stating
that columns are separated by spaces or tabs only (CR and FF inside a row are
line breaks for `splitlines` and fall to the row-count error, as before). The
fast path stays cheap: an all-ASCII block is cleared by `str.isascii` plus five
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
`compileall` with warnings as errors passed. The claim that `git diff --check`
passed was wrong: the test module ended with a blank line, which the review of
PR #83 found and PR #85 removed. The full verifier (`.claude/skills/verify`)
was not rerun on this host (no pandas, matplotlib, ASE).

## Follow-up (PR #85, from the code review of PR #83)

Findings and what changed:

- **C locale broke every access path.** `_read_layout` and `__iter__` opened
  the dump with the locale encoding while `read_frame` decoded the mmap'd bytes
  as UTF-8. Measured with `LC_ALL=C PYTHONUTF8=0 PYTHONCOERCECLOCALE=0`: all four
  access paths (the preflight runs in the constructor) raised
  `UnicodeDecodeError`, a `ValueError` subclass, instead of naming the row and
  code point. Both opens now pass `encoding='utf-8'`.
- **Row number counted only LF.** `_foreign_separator` now numbers rows on
  `str.splitlines` boundaries, as the width check does; a CR-terminated dump
  reported row 1 for every row before.
- **Misleading message.** "only space, tab, CR, LF and FF separate dump columns"
  became "dump columns are separated by spaces or tabs only"; CHANGELOG reworded.
- **Dead `_SEPARATORS`.** `_ODD_ASCII_SPACE` and `_FOREIGN_SPACE` are now derived
  from it (verified equal to the former literals over all code points). The
  `_BOUNDARY_TOKEN` comment that the first PR had displaced is back in place.
- **Tests.** Split per backend so a NumPy-only host records PASS for the NumPy
  tests and a named SKIP for native (before: SKIP for everything); native tests
  forbid the `np.loadtxt` fallback; `_dump`/`_backends` moved to `tests/_util.py`
  as `dump_frame`/`dump_backends` and `test_dump_comment_tokens.py` uses them
  (`test_parser_edges.py` keeps its variant, which prints a note instead of
  skipping). New tests `test_foreign_separator_rejected_under_c_locale`
  (subprocess with a C locale; failed before: `UnicodeDecodeError`) and
  `test_row_number_follows_splitlines` (failed before: `(1, nbsp)` for CR ends).
- **EOF blank line** removed; `git diff --check` on `30f8533..HEAD` is clean.
- **AUDIT-20261104.md** status line corrected (merged, E-1 fixed).

Verification (same host and interpreter):

| Mode | Result |
| --- | --- |
| `tests/run.py` native | 732 passed, 1 failed, 24 skipped |
| `tests/run.py` `LKPR_NO_NATIVE=1` | 719 passed, 1 failed, 37 skipped |

`test_dump_whitespace`: native 6 PASS; NumPy-only 4 PASS, 2 named SKIP (before: 2 PASS / 2 SKIP).
The one failure in both modes is still the pandas-dependent `test_stale_cache` case.

## Out of scope

The other parser items of AUDIT-20261104 (A-1 `ITEM: UNITS`/`ITEM: TIME`
headers, B-R1 unordered timesteps) and the `lkpr-rs` findings E-2..E-7.
