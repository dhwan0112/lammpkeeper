# REV-IO-6 — validate dump and input boundary flags

Status: implemented, parent verification pending (branch `fix/rev-io-6-boundary-flags`).

## Problem (measured)
`_BOUNDARY_TOKEN = ^[pfsm]{1,2}$` accepted single letters and mixed faces, while
`pbc_from_boundary` treats only exact `pp` as periodic. With `box_model=True`,
`p p f` published `cell.pbc == (False, False, False)`, and `pf pp ff` and
`sp pp ff` published `(False, True, False)`, all without a warning. An input
script `boundary pp potato f` was returned verbatim.

## Rules used (assumption: LAMMPS `boundary`/`dump` docs, not re-fetched)
- Dump BOX BOUNDS: one two-letter token per axis (lo, hi) from p, f, s, m;
  `p` only as `pp`.
- Input `boundary`: three words, each one letter (both faces) or two letters;
  `p` must be on both faces or neither.

## Change (`lammps_post/parsers.py`)
- `parse_boundary_flags` raises `ValueError` naming the offending token(s) for
  wrong count/length, unknown letters, or `p` mixed with a non-p face. No flags
  (old dumps, or only `xy xz yz`) still returns `None`. Valid tokens map as
  before. `DumpReader._read_header` prefixes path and step. This applies for
  `box_model` True and False, streaming and indexed, since `reader.boundary`
  also feeds shell/state PBC.
- New `parse_input_boundary`: `parse_input` now rejects an invalid word, a wrong
  word count, or a bare `boundary` command with path and message. Valid
  single-letter styles (`p p f`) are unchanged. Previously a `boundary` line
  with fewer than four words was silently ignored; it now raises.

## Native parity
`native/src/lib.rs` has no boundary handling (0 matches); header and flags are
parsed in Python for both paths. No native change.

## Tests
`tests/test_boundary_flags.py` (7 tests). Before the fix: 3 failed, 4 passed
(the other 4 cover valid mappings, no-flags dumps and unchanged valid input).
After: 7 pass with native and with `LKPR_NO_NATIVE=1`.

## Parent integration (2026-11-01, measured)

- Rebased (unpublished, no force-push) onto main `214b975` (PR #42). Registered
  `test_boundary_flags`; BACKLOG and CHANGELOG updated.
- The parent checked the rules against the official LAMMPS `boundary` page
  (docs.lammps.org/boundary.html, release 30Sep2026): each of x, y, z is p, s, f
  or m, one or two letters, and "the p style must be applied to both faces of a
  dimension". This matches the validation; the worker's assumption is confirmed.
- Reviewed consequence: an input `boundary` that uses an unresolved variable
  (e.g. `${bx}`) now raises instead of being stored verbatim. Prep-generated
  inputs write literal styles and are unaffected.
- Failing-first reproduced by the parent: against main's `parsers.py`
  **4 passed, 3 failed**; with the fix **7 passed**.
- Full verifier results follow (started after this commit).
