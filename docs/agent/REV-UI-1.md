# REV-UI-1 — `print_table` with no rows / malformed rows

## Problem
`lammpkeeper/common/display.py::print_table` (plain path) computed
`max(visible_width(h), *(... for r in rows))`. With `rows=[]` that is
`max(int)` and raises `TypeError: 'int' object is not iterable`. A row shorter
than the headers raised a bare `IndexError`. The Rich path accepted both
silently (and could pad/misalign).

## Decision (maintainer)
- Empty `rows`: render header and rule with no body, identically on Rich and plain paths.
- Row length != header count: fail visibly with `ValueError` naming the row and the
  mismatch. No padding, no truncation (a wrong column is a wrong number).

## Fix
- Validate all rows up front (before any output, so no half-printed table).
- Plain widths use `max([header] + [cells])`, which is valid for empty rows.

## Evidence (measured)
Isolated HOME, `PYTHONPATH=<pytest dir>`, Python 3.11, rich installed.
- Before (fix stashed): `python -m pytest -q tests/test_display.py` →
  `2 failed, 6 passed`; `TypeError: 'int' object is not iterable` (empty rows),
  `IndexError: list index out of range` (short row).
- After: same command → `8 passed`.
New tests: `test_print_table_empty_rows_renders_header_only`,
`test_print_table_row_length_mismatch_raises_value_error` (both exercise
`{HAS_RICH, False}`).

## Limits
- Rows are materialised into lists (generators are accepted, consumed once).
- Callers that relied on lenient Rich padding with ragged rows now get `ValueError`;
  no in-repo caller was found passing ragged rows (not exhaustively proven beyond the fast suite).
