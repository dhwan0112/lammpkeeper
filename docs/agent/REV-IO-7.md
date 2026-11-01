# REV-IO-7: post can load prep-written inputs (LAMMPS math in `parse_input`)

Status: fixed and verified at `97d30ad` (see Verification).
Branch: `fix/rev-io-7-prep-input-load` from main `84db3b4` (after REV-PREP-7, PR #52).
Approval: on 2026-11-01 the maintainer approved the plan: REV-PREP-7 first, then this parser change in its own PR.

## Problem (measured)

- **Failure.** `parse_input` evaluated equal-style variables with arithmetic only. `load input` of prep's own ACE input therefore failed: `cannot resolve numeric expression 'round(500/0.00025)'`.
- **How it fails.** It raises at the immediate `${ox_steps}` substitution inside a later variable definition.
- **Measured run.** `lammps_post --input ace_oxidation.in --batch` on main `2314436` exits 1 with `cannot resolve numeric expression 'round(50/0.00025)'`.
- **ReaxFF inputs loaded, but not cleanly.** Their `round()` step variables were dropped without a message from `z_variables`.

## Change

`lammps_post/parsers.py` `_resolve_numeric` now evaluates a bounded subset of LAMMPS formulas with LAMMPS semantics. All rules below were taken from `src/variable.cpp` (develop) and docs.lammps.org/variable.html.

**Supported:**
- **Functions:**
  - `round` uses LAMMPS `MYROUND`, which rounds halves up: `round(-2.5) = -2`, `round(0.5) = 1`. Python rounds halves to even.
  - `floor`, `ceil` and `abs`.
  - `ternary(c,a,b)`, which is lazy: only the chosen branch is evaluated.
- **Comparisons:** `< <= > >= == !=` give 1 or 0.
- **Modulo:** `%` is C `fmod`. Python's `%` gives `-7%3 = 2`; LAMMPS gives `-1`.

**Rejected with a reason (raises, no guess):**
- **`-a^b` without parentheses.** LAMMPS reads it as `(-a)^b`; Python as `-(a^b)`.
- **`a^b^c` without parentheses.** LAMMPS reads it as `(a^b)^c`; Python as `a^(b^c)`.
- **Chained comparisons.** Python chains them; LAMMPS evaluates pairwise and gives `==` a lower precedence.
- **Special functions** (`sum`, `min`, `max`, `ave`, `trap`, `slope`, `sort`, `rsort`). In LAMMPS these take one vector argument (`c_ID`, `f_ID` or `v_name`), so a scalar `min(a,b)` aborts LAMMPS (REV-PREP-7). The error message suggests `ternary()`.
- **Any other function** (for example `sqrt`), wrong arity and keyword arguments.
- **Unchanged rules:** length, node count, exponent and finiteness bounds, division by zero, and unknown or cyclic variables.

The parser stays a bounded static evaluator. Group, region, compute, fix, atom and other runtime functions remain unsupported and raise.

## Tests (failing first)

New collected module `tests/test_input_math.py` (4 tests), registered in `tests/run.py`:

| Test | Before the fix | After |
| --- | --- | --- |
| LAMMPS function semantics | fail (`KeyError`: the variable was not resolved) | pass |
| Comparisons, `%` and `^` precedence | fail | pass |
| Ambiguous or unsupported forms raise | fail (the wrong message, or accepted) | pass |
| Real prep ACE, ReaxFF2010 and ReaxFF2015 output loads | fail (`round(50/0.00025)`) | pass |

The last test checks that each prep output loads with explicit dt 0.25 fs and the right family, and that `ox_steps`, `ox_dense` and `ox_remain` are correct.

**Independent oracle.** Every expected value in the first two tests was evaluated in real LAMMPS 22Jul2025 (throwaway venv, script `/tmp/opencode/io7-oracle.py`): **28 formulas, 0 mismatches**. The same run shows that LAMMPS gives `-2^2 = 4` and `2^3^2 = 64`. Python gives -4 and 512, which is why those forms are rejected.

Related modules also pass (measured): 94 tests across `test_input_math`, `test_audit_parsers`, `test_run_metadata`, `test_session_metadata`, `test_audit_prep`, `test_boundary_flags` and `test_audit_integration`, 0 failed.

## End-to-end (measured)

`lammps_post --input <prep ACE>/ace_oxidation.in --batch` with `info`:
- **Before:** exit 1, as above.
- **After:** exit 0. Timestep `0.25 fs (explicit)`, `pair_style 'pace product' [explicit]`, `dt_fs 0.25 [explicit]`.

## Not in scope

- `run ${var}` lines are still recorded in `config['runs']` only when they are literal integers. `runs` has no consumer.
- LAMMPS logical operators (`&&`, `||`, `!`) and the other math functions remain unsupported. They raise visibly.

## Verification (measured, `97d30ad`, worktree untouched during runs)

| Run | Tests | post | prep | Evidence |
| --- | --- | --- | --- | --- |
| Native full verifier | 645 passed, 0 failed, 0 skipped | PASS | PASS | `/tmp/opencode/io7-native/20261101T204852-97d30ad-full` |
| Forced-NumPy full verifier | 636 passed, 0 failed, 9 skipped | PASS | PASS | `/tmp/opencode/io7-numpy/20261101T204852-97d30ad-full` |

- The 9 skips in the forced-NumPy run are the named native-parity tests.
- Each run has 4 more tests than REV-PREP-7's runs: the new `test_input_math` module.
