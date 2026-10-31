# REV-SESSION-1 — physical shell overrides

Status: implemented; parent verification pending.

## Scope and context

Prior-work review 2026-10-29, finding S1. The public shell accepted
`set surface_z nan|inf`, `set dt -1|nan` and analyses then published plausible
results (OAR `[0,0]` or `[1,1]`, MSD time `[0,-0.1]` or `[0,nan]`) with
`last_command_ok` true and zero command failures.

## Contract

- `surface_z` must be finite (any sign). `dt` and `mass` must be finite and
  strictly positive.
- Validation runs before any state publication or cache invalidation, through
  the private helper `LammpsPostShell._finite_value`. Invalid input raises
  `ValueError`, so `onecmd` counts a failure and batch/one-shot exit nonzero.
- A rejected value leaves the previous value, the manual-surface flag and all
  cached results unchanged.
- The interactive surface prompt (`_require_surface_z`) applies the same check.
- Valid values behave exactly as before.

## Other numeric `set` keys

- `mass`: physical (density input); validated as above.
- Out of scope, display-only and not physical results: `dpi`, `fontsize`,
  `linewidth`, `markersize`, `grid_alpha`, `figsize`, `z_focus`. They never
  feed an analysis number, so rejecting them is a plotting-robustness change
  and not a physical-validity fix.

## Evidence (measured)

- New tests on unmodified `shell.py`: 5 failed, 1 passed (the valid-value guard).
- After the fix: `test_session_overrides` 6 passed, 0 failed, 0 skipped.
- Modules test_session_overrides, test_audit_workflow, test_species_session,
  test_triclinic_session, test_charge_integrity_session, test_lkpr_cli,
  test_msd: 104 passed, 0 failed, 0 skipped.
- Full verifier not run by the implementation worker.
