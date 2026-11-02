# REV-ANALYSIS-8 — analysis parameter validation

Status: implemented on branch `fix/rev-analysis-8-param-validation` (based on
`main` `124c3b4`). Not pushed.

## Problem (2026-11-01 audit, P2)

Several analysis APIs accepted invalid parameters and returned plausible zeros,
NaN or a wrong time axis. Measured on unmodified `analysis.py`, two-frame
synthetic system (`tests/test_analysis_params.py::_frames`):

| Call | Result before the fix |
|---|---|
| `analyze_charge_evolution(..., z_range=(5, 0))` | `n_total_fe [0 0]`, `avg [0 0]`, `frac_oxidized [0. 0.]` |
| `analyze_charge_evolution(..., z_range=(nan, 5))` | `n_total_fe [0 0]` |
| `compute_oar(frames, col, z_surf=nan)` | `oar [0. 0.]`, `n_absorbed [0 0]` |
| `compute_oar(..., dt_fs=-0.5)` | `time [-0. -0.2]` |
| `compute_oar(..., dt_fs=nan)` | `time [nan nan]` |
| `analyze_charge_z(frame, col, z_bins=0)` | empty `z` and `fe_count` arrays |
| `analyze_charge_z(..., z_bins=-2)` | `ValueError: Number of samples, -1, must be non-negative.` (wrong kind of message) |
| `analyze_charge_z(..., z_bins=2.5)` | `TypeError: 'float' object cannot be interpreted as an integer` |
| `analyze_penetration_trend(..., window=0)` | `ValueError: negative dimensions are not allowed` from deep inside the smoother (longer series: kernel `ones(0)/0`) |

## Change

Five small private helpers in `lammps_post/analysis.py`, one per kind:
`_finite_param` (finite real, optional `> 0`), `_dt_param` (finite and `> 0`),
`_range_param` (two finite reals, `lo < hi`), `_count_param` (positive integer)
and `_is_real` (bool and str are not numbers). Each public function calls them
as its first statement, so a bad value raises `ValueError` before any frame is
read. The message names the function and the parameter, for example
`OAR: z_surf must be a finite number, got nan`. Validated values are used as
plain floats/ints; `step * dt_fs / 1000` is arithmetically unchanged.

Functions and parameters checked:

- `dt_fs`: `analyze_charge_evolution`, `compute_or`, `compute_oar`,
  `analyze_penetration`, `analyze_penetration_trend`, `detect_o2_dissociation`,
  `analyze_spin_evolution`, `analyze_msd`, `analyze_penetration_profile`.
  (`compute_rdf` has no `dt_fs`; `compute_density_profile` has none.)
- `z_range`, `q_thr`: `analyze_charge_evolution`, `compute_or`.
- `z_surf` / `surface_z`: `compute_oar`, `analyze_penetration`,
  `analyze_penetration_trend`.
- `z_bins`: `analyze_charge_z`.
- `window`: `analyze_penetration_trend`.

## Validity decisions

- `dt_fs`: finite and strictly positive, same rule as `set dt` in the shell
  (REV-SESSION-1). Zero collapses the time axis; negative reverses it.
- `surface_z`, `z_surf`: any finite number. A plane below zero is a legal
  coordinate in a shifted box, so no sign restriction.
- `q_thr`: any finite number. It is a signed cutoff in `qs > q_thr`; a negative
  cutoff is a legitimate (if unusual) choice, and nothing in the code or its
  comments forbids it. Only NaN/inf (which make the count always zero or all
  atoms) are rejected. Not restricted to the default 0.3 e.
- `z_range`: two finite reals with `lo < hi`, as in REV-ANALYSIS-3. Inclusivity
  is unchanged (`z >= lo` and `z <= hi`). `lo == hi` is rejected as a
  zero-thickness slab that cannot be a deliberate region; this is the one
  judgment call. Lists and arrays of two numbers are accepted.
- `z_bins`, `window`: positive integers (Python or NumPy ints). bool, float even
  if integral, and str are rejected so a count is never guessed.
- `window=None` keeps the automatic window. A `window` larger than the series is
  already defined and visible (clamped to the series length and returned as
  `window`; the series is then returned unsmoothed). This is kept and pinned by
  a test.
- bool and str are rejected for every numeric parameter. `None` is rejected for
  `dt_fs`, `q_thr` and the surface plane (no hidden default).

## Evidence (measured)

- Tests: `tests/test_analysis_params.py`, 11 tests: six rejection tests
  (dt_fs × 9 functions × 9 values, surface plane, q_thr, z_range × 12 forms,
  z_bins, window) using a frame container that raises if read; five tests pin
  valid results to hand calculations.
- Against unmodified `analysis.py`: **5 passed, 6 failed** (the five passes are
  the valid-value pins, including the window clamp; the six rejection tests
  fail).
- After the fix: **11 passed, 0 failed**.
- Command: `cd <worktree> && HOME=$(mktemp -d /tmp/opencode/an8-home.XXXXXX)
  TMPDIR=/tmp/opencode LKPR_NO_HISTORY=1 PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg
  python -W ignore -c "import sys; sys.path.insert(0,'tests'); import
  test_analysis_params as t; [getattr(t,n)() for n in sorted(dir(t)) if
  n.startswith('test_')]"`.
- Full suite: see the implementer report (counts and skips).

## Not changed

`compute_rdf`, `compute_density_profile`, defaults, goldens, fixtures, shell,
`tests/run.py`, BACKLOG and CHANGELOG. Parent must register the module in
`tests/run.py` and update BACKLOG/CHANGELOG. Not validated here: `fe_type` /
`o_type` selections (already checked by `_type_ids`), `species_type`, `pbc`,
`surface_percentile` (already checked), `analyze_structure`'s compatibility
arguments.

## Verification (measured, `0ad491e`, worktree untouched during runs)

| Run | Tests | post | prep | Evidence |
| --- | --- | --- | --- | --- |
| Native full verifier | 681 passed, 0 failed, 0 skipped | PASS | PASS | `/tmp/opencode/an8-native/20261102T125743-0ad491e-full` |
| Forced-NumPy full verifier | 672 passed, 0 failed, 9 skipped | PASS | PASS | `/tmp/opencode/an8-numpy/20261102T125743-0ad491e-full` |
| Reference checks | 6/6 PASS, exit 0 | | | `/tmp/opencode/an8-refs/` |

The forced-NumPy skips are the named native-parity tests.
