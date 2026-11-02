# REV-UI-2 — `plot redo/edit` find recipes saved under normalized keys

Status: fixed; verification below.

Finding: F-SESSION-2 in `docs/agent/REVIEW-20261028.md`.

## Problem (measured)

Interactive plots save a recipe under a normalized title, not under the name
the user types. After `plot charge`, the recipe key is `charge_evolution`.
Then `plot redo charge` printed `No saved recipe for 'charge'`.
`plot redo charge_evolution` found the recipe but then failed with
`Unknown plot type: 'charge_evolution'`, because the dispatcher only knows
`charge`. The same defect hit every plot that saves through
`_iplot_common_opts`.

## Name table

| `plot <name>` (dispatch) | Stored recipe key |
|---|---|
| `charge` | `charge_evolution` |
| `charge_z` | `charge_z_distribution` |
| `oar` | `oxygen_absorption_rate` |
| `penetration` | `o_penetration` |
| `penetration_trend` | `penetration_trend` and `o_penetration_trend` |
| `dissociation` | `o2_dissociation` |
| `spin` | `spin_evolution` |
| `thermo`, `thermostat`, `pressure`, `rdf`, `penetration_profile` | same as dispatch name |

`or`, `density`, `msd`, `performance`, `structure`, `snapshot` save no recipe.

## Change

- `LammpsPostShell._RECIPE_KEYS` (one dict in `lammps_post/shell.py`) maps a
  dispatch name to its stored keys.
- `_resolve_recipe_name` accepts either the dispatch name or a stored key. It
  returns the dispatch name and the saved recipe.
- `plot redo`, `plot edit`, `plot save_defaults` and the redo-mode check in
  the dispatcher use it.
- Stored keys are not renamed. Old key names still work as input.

## Verification

New module: `tests/test_recipe_alias.py` (5 tests).

Command (env prefix: isolated `HOME`, `TMPDIR=/tmp/opencode`,
`LKPR_NO_HISTORY=1`, `MPLBACKEND=Agg`; python from the `chem` env):

    python -W ignore -c "import sys; sys.path.insert(0,'tests'); import test_recipe_alias as t; [getattr(t,n)() for n in sorted(dir(t)) if n.startswith('test_')]; print('ok')"

- Before (unmodified `shell.py` from a6d21b0): 3 of 5 fail
  (`test_charge_end_to_end_save_then_redo_writes_figure`,
  `test_redo_and_edit_accept_every_dispatch_name`,
  `test_stored_key_names_still_work`). The other 2 pass.
- After: 5 of 5 pass.
- Full fast suite (`tests/run.py` module list plus `test_recipe_alias`,
  appended in-process because `tests/run.py` is not edited here):
  732 passed, 0 failed, 2 skipped. Named skips, both `LKPR_SLOW=1 not set`:
  `test_regression_numeric.test_numeric_regression_rdf_msd_slow` and
  `test_audit_rdf_oracle.test_fixture_rdf_matches_explicit_per_frame_pair_normalization`.

The end-to-end test runs a real `plot charge` with prompts answered by their
defaults (this saves the recipe), clears the output directory, runs
`plot redo charge`, and checks that a PNG is written. The other tests replace
`_iplot_*` handlers with recorders, so they check routing, not rendering.

## Not changed

- Stored recipe keys and their contents.
- Batch and noninteractive plots still do not save a recipe for the
  `_iplot_common_opts` plots. Only an interactive run saves one.
- Batch redo still reads recipe values only where the handler already did.
  Some handlers (oar, spin, dissociation) use session defaults in batch mode.
- `plot recipes` still lists stored keys.
