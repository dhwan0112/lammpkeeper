# REV-UI-6: z-range prompts parse signed ranges and reject typos

Status: fixed and verified (PR #99).
Branch: `fix/z-range-prompt-parse` from main `8c6c16f`.
Source: AUDIT-20261104 finding C-1 (P2, silent loss of the slab correction).

## Problem

Four interactive prompts in `lammps_post/shell.py` parsed a z range with
`lo, hi = ans.split('-', 1)` under `except ValueError: pass`:

- `plot pressure`: slab z-range for the pressure correction.
- `plot density`, `plot structure`, `plot snapshot`: z-axis focus range.

A negative lower bound split on its own sign (`'-5-80'.split('-', 1)` gives
`['', '5-80']`), and `0:80` or `0 80` did not split at all. The prompt dropped
the answer without a message. For pressure the plot fell back to the
uncorrected box pressure and the recipe stored `slab_z_range None`. A saved
negative lower bound was offered back as the default `-5.0-80.0`, which failed
the same way. The z-focus prompts kept the auto crop.

## Change

- New module helper `_parse_z_range(text, what)`. It accepts `lo:hi`,
  `lo,hi`, `lo hi` and `lo-hi` with signed or exponent numbers, so `-5-80` is
  (-5, 80) and `-5.0--1.0` is (-5, -1). It requires finite bounds with
  lo < hi. Anything else raises `ValueError` naming the prompt and the
  accepted forms. Whitespace is tried as the separator first, so `0 -5` reads
  as (0, -5) and fails the order check instead of becoming (0, 5).
- All four prompts call the helper. `full`/`none`/`all` (and `n` for the
  slab prompt) keep their meaning. A malformed answer now fails the plot
  command before plotting or saving a recipe; the previous recipe is kept.
- Prompt defaults come from `_fmt_z_range(lo, hi)` = `f"{lo:g}:{hi:g}"`
  (`-5:80`), so every default the shell offers parses back. The old
  one-decimal/integer rounding could turn a valid narrow range into `0:0`
  (found in review: a detected surface at z = 0.3 gave the default `0:0`).
  The pressure prompt offers the `0:surface` slab only when the surface is
  above z = 0, otherwise `none`.
- `_iplot_common_opts` uses the same default formatter. Its parsing is
  unchanged: its optional display edits keep the previous crop on malformed
  input by design (documented in its comment).

## Tests

`tests/test_z_range_prompt.py`, 9 tests, registered in `tests/run.py`:

- parser: every separator, signed bounds, exponents; garbage, single value,
  three values, NaN/inf, reversed and empty ranges raise; `_fmt_z_range`
  round-trips narrow and signed ranges.
- pressure: `-5-80`, `0:80`, `0 80` reach `plot_pressure` and the recipe; a
  saved (-5, 80) recipe is offered as `-5:80` and parses back; a surface at
  z = 0.3 offers `0:0.3`, one at z = -3 offers `none`; a typo
  raises without plotting and keeps the old recipe; `none` stays bulk.
- snapshot and structure: `-10:30` reaches the backend; a typo raises before
  the backend is called. The density prompt uses the identical code.

Measured against main's `shell.py` (first 7 tests): 6 of 7 fail (the two parser tests at
import; `-5-80` gives `slab_z_range None`, the default offered is
`-5.0-80.0`, the typo is accepted, snapshot keeps the auto crop). Only
`none` → bulk passed before and after. The two formatter tests import
`_fmt_z_range` and cannot run on main.

## Verification

Full runner: native 795 passed / 0 failed / 26 skipped; NumPy (`LKPR_NO_NATIVE=1`)
782 / 0 / 39 (main: 786/0/26 and 773/0/39; +9 each).
