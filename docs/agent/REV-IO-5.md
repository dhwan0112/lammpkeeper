# REV-IO-5: thermo Step counters stay exact or are rejected

Status: fixed and verified at `c4269aa` (see Verification).
Branch: `fix/rev-io-5-thermo-step-precision` from main `94e562f`.

## Problem (measured on unmodified code)

`parse_log` stores thermo rows as float64, while LAMMPS steps are signed 64-bit integers. From 2^53 on, adjacent counters collapse to the same float.

A log with steps `9007199254740992` and `9007199254740993` parsed as follows:
- `step` was `[9007199254740992.0, 9007199254740992.0]`;
- elapsed steps were 0 and 0;
- `timeline_valid` was `True`.

That is a wrong time axis that looks valid. The execution layer (`application._steps`, EXEC-1) already rejected such parsed values for `thermo.summary`. The session, plots and every other caller of `parse_log` did not.

## Change

`lammps_post/parsers.py`, `parse_log`: every numeric thermo row of every block is checked as it is parsed. The Step value must be finite, integral and below 2^53 in absolute value; this is the same rule as `application._steps`. Otherwise `ValueError` names the file, the line, the Step token and the row.

- Steps up to 2^53 − 1 stay exact, and so do their differences.
- Exponent notation for an exact integral counter (`1e3`) is still accepted.
- A non-integral Step (`10.5`) or a non-finite one (`nan`, `inf`) is rejected. LAMMPS never prints those as counters.

## Tests

New `tests/test_thermo_steps.py` (4 tests), registered in `tests/run.py`.
- **Before the fix:** 2 of the 4 fail. Steps at and beyond ±2^53, `1e300`, `10.5`, `nan` and `±inf` were all accepted.
- **After the fix:** all 4 pass. The two tests that pass before as well pin unchanged behavior:
  - `2^53 − 3 … 2^53 − 1` keep exact elapsed steps `[0, 1, 2]`;
  - ordinary logs parse as before.
- **Related modules** (`LKPR_SLOW=1`): `test_log_integrity`, `test_parse_log_merge`, `test_execution_contract`, `test_jobs`, `test_audit_parsers`, `test_session_metadata`, `test_run_metadata`, `test_parser_edges`, `test_regression_numeric`, `test_audit_workflow` and `test_rust_cli` all pass.

## Not changed

- Thermo rows remain float64.
- The result schema and the `step` dtype are unchanged.
- The execution layer's own check stays as a second guard.

## Verification (measured, `c4269aa`, worktree untouched during runs)

| Run | Tests | post | prep | Evidence |
| --- | --- | --- | --- | --- |
| Native full verifier | 726 passed, 0 failed, 0 skipped | PASS | PASS | `/tmp/opencode/io5-native/20261102T205309-c4269aa-full` |
| Forced-NumPy full verifier | 715 passed, 0 failed, 11 skipped | PASS | PASS | `/tmp/opencode/io5-numpy/20261102T205309-c4269aa-full` |
| Reference checks | 6/6 PASS, exit 0 | | | `/tmp/opencode/io5-refs/` |

The forced-NumPy skips are the named native-parity tests.
