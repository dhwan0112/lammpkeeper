# REV-PREP-7: generated ACE input aborts in LAMMPS (two-argument min/max)

Status: fixed and verified at `30d138d` (see Verification).
Branch: `fix/rev-prep-7-ace-step-clamp` from main `2314436`.
Approval: on 2026-11-01 the maintainer approved this change to generated LAMMPS inputs (AGENTS.md §8 gate), with REV-IO-7 to follow in a separate PR.

## Finding (measured)

The parent found this while reproducing REV-IO-7. Since `7f42305` (AUDIT-20261027, 2026-10-27), prep has written these lines into every ACE input:

```
variable ox_dense  equal min(${ox_steps},max(0,round(${DENSE_PS}/${dt})))
variable ox_remain equal max(0,${ox_steps}-${ox_dense})
```

- **Not valid LAMMPS.** In LAMMPS, `min()` and `max()` are *special functions* that take exactly one global-vector argument (`c_ID`, `f_ID` or `v_name`). Scalar two-argument min/max does not exist.
  - The math functions are listed on docs.lammps.org/variable.html. `Variable::special_function` raises "Invalid special function" when `narg != 1`.
  - The same check is in the `stable_2Aug2023_update3`, `stable_29Aug2024_update1`, `stable` and `develop` sources.
- **Measured.**
  - Tool: LAMMPS 22Jul2025 (PyPI `lammps` wheel and `mpich`, in a throwaway venv under `/tmp/opencode/lmp-venv`; no system package).
  - Input: only the variable lines of prep's ACE input.
  - Result: `ERROR: Variable ox_dense: Invalid special function min() in variable formula`.
  - When: the error comes at the `ox_remain` definition, because its immediate `${ox_dense}` substitution evaluates `ox_dense`. That is while LAMMPS reads the input, before any MD.
- **Impact:**
  - Every ACE job generated since 2026-10-27 aborts at startup. It fails loudly, with no wrong numbers, but wastes a queue slot.
  - The thesis tag `cdf5c38` used `round()` only and is valid.
  - ReaxFF inputs use only `round()` and evaluate correctly in the same LAMMPS (`eq_steps = ox_steps = 800000`).
- **Why tests missed it.** `test_ace_dense_stage_is_configured_clamped_and_exact_in_steps` evaluated the formulas with *Python's* `min`/`max`.

## Change

`lammps_pre/templates.py`: the clamp is now written with the LAMMPS math function `ternary(x,y,z)` (3 arguments). The semantics are unchanged:

```
variable ox_dense_req equal round(${DENSE_PS}/${dt})
variable ox_dense_pos equal ternary(${ox_dense_req}>0,${ox_dense_req},0)
variable ox_dense     equal ternary(${ox_steps}<${ox_dense_pos},${ox_steps},${ox_dense_pos})
variable ox_remain    equal ternary(${ox_steps}-${ox_dense}>0,${ox_steps}-${ox_dense},0)
```

- `run ${ox_dense}` and `run ${ox_remain}` are unchanged, as are the index variables. `-var OX_PS ...` overrides still recompute the stages.
- The ReaxFF template is unchanged.
- The two new helper variables (`ox_dense_req`, `ox_dense_pos`) are the only other change to the ACE input.

## Tests (failing first)

- New: `test_audit_prep.test_generated_equal_variables_use_only_lammps_math_functions`.
  - Every equal-style formula in the ACE, ReaxFF2010 and ReaxFF2015 inputs may call only LAMMPS math functions, with LAMMPS arity.
  - Before the fix it failed with `('ace', 'min(${ox_steps},max(0,round(${DENSE_PS}/${dt})))', 'min')`.
- Updated: `test_ace_dense_stage_is_configured_clamped_and_exact_in_steps`.
  - It now evaluates with LAMMPS function semantics (round half up as in `MYROUND`, `ternary`) and offers no `min`/`max`.
  - Before the fix it failed (`KeyError 'ox_dense_req'`, the new variable). After the fix all 17 `test_audit_prep` tests pass.

## Real-LAMMPS cross-check (measured, not part of the suite)

- **Variable blocks.** `/tmp/opencode/p7-lmp-check.py` renders the ACE input and runs its variable lines in LAMMPS 22Jul2025.
  - Coverage: 7 generation pairs `(OX_PS, DENSE_PS)` × 5 runtime `-var OX_PS` overrides (none, 0, 0.00075, 7, 1000).
  - Comparison: `ox_steps`, `ox_dense` and `ox_remain` against the intended clamp `steps = R(OX/dt)`, `dense = min(steps, max(0, R(DENSE/dt)))`, `remain = max(0, steps - dense)`, with LAMMPS rounding.
  - Branch: **35 cases, all equal**.
  - Main `2314436`: the same script stops at the first case with the `min()` error.
- **Whole generated ACE input.** It was run with `-var NPROC_X 1 -var NPROC_Y 1`, in the prep output directory.
  - LAMMPS now gets past every variable, region, group and `read_data` line.
  - It stops at `pair_style pace product`, because ML-PACE is not in the wheel. A real ACE run still needs an ML-PACE build; none was available here, and no HPC job was run.

## Not in scope

- REV-IO-7: post's parser does not support LAMMPS math functions such as `round()`. It follows in a separate PR.

## Verification (measured, `30d138d`, worktree untouched during runs)

| Run | Tests | post | prep | Evidence |
| --- | --- | --- | --- | --- |
| Native full verifier | 641 passed, 0 failed, 0 skipped | PASS | PASS | `/tmp/opencode/p7-native/20261101T204244-30d138d-full` |
| Forced-NumPy full verifier | 632 passed, 0 failed, 9 skipped | PASS | PASS | `/tmp/opencode/p7-numpy/20261101T204244-30d138d-full` |

- The 9 skips in the forced-NumPy run are the named native-parity tests.
- The prep smoke step regenerates the ACE input with the new template.
