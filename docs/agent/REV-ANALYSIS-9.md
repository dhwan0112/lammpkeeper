# REV-ANALYSIS-9: legacy `z_pbc` may not override a typed Box's PBC in RDF

Status: fixed and verified at `0ba91a2` (see Verification).
Branch: `fix/rev-analysis-9-rdf-box-pbc` from main `124c3b4`.

**Decision (maintainer, 2026-11-01):** raise on disagreement.
- This amends ADR-0003 and GEN-3, which had kept the legacy switch authoritative on purpose. The amendment is noted in ADR-0003, GEN-3 and MIGRATION.

## Problem

`compute_rdf(..., pbc=None)` applied `(True, True, z_pbc)`, with default `z_pbc=False`, to every orthogonal frame. It did so even when the frame's Box had resolved flags such as `pp pp pp`, so z was treated as non-periodic without any notice. MSD and pair detection already raise on the same disagreement.

- **Shell:** not affected. It passes the resolved mask as `pbc`.
- **Affected:** direct API calls such as `compute_rdf(frames, col, 1, 3)` on frames from a periodic dump.

## Change

`lammps_post/analysis.py`, `compute_rdf`: for an orthogonal Box with `pbc=None`, there are three cases.

| Box flags | Result |
| --- | --- |
| Resolved and different from `(True, True, z_pbc)` | `ValueError` naming the timestep, the legacy mask and the Box flags. It also says to pass `pbc=`. |
| Resolved and equal | Unchanged. |
| Unresolved (None) | Unchanged. |

- Legacy frames without a Box are unchanged.
- An explicit `pbc` that disagrees with the Box already raised; it still does.
- Both pair backends raise at the same point, before pair search.

## Tests

- **New:** `tests/test_rdf_box_pbc.py` (3 tests), registered in `tests/run.py`.
  - Before the fix, 2 of the 3 fail: the disagreement was accepted.
  - The third checks that matching, unresolved and Box-free frames still give the previous g exactly. It passes before and after.
- **Changed tests:** they pinned the old contract or used it incidentally.
  - `test_triclinic_analysis.test_typed_orthogonal_rdf_keeps_legacy_z_pbc_switch` is renamed `…_rejects_disagreeing_legacy_z_pbc`. It existed to protect the contract you approved changing. Now:
    - agreement equals the legacy result;
    - the z setting still matters on Box-free frames;
    - disagreement raises.
    - The docstring records the change.
  - `test_triclinic_analysis.test_typed_cell_triclinic_marker_is_a_boolean_geometry_claim` tests the triclinic marker. Its RDF call only has to succeed, so it now passes explicit flags that match the Box.
  - `test_periodicity.test_shell_msd_and_rdf_follow_dump_flags` is a shell routing test. The shell result is unchanged. The test's own "the other z setting gives a different g" check had applied the disagreeing setting to Box-carrying frames. It now runs that check on Box-free copies, and asserts that the Box-carrying call refuses the disagreeing setting.
- No expected numeric value changed.

**Related modules.** The parent ran 17 RDF/geometry/session modules with `LKPR_SLOW=1`. Before the test updates, the 3 tests above were the only failures. After the updates, all pass.

**Reference checks.** `verify_refs.py`: all 6 checks PASS. The fixture and golden calls use `z_pbc=True` on `pp pp pp` data, which agrees.

## Verification (measured, `0ba91a2`, after rebase onto main `08b4ea3`)

| Run | Tests | post | prep | Evidence |
| --- | --- | --- | --- | --- |
| Native full verifier | 669 passed, 0 failed, 0 skipped | PASS | PASS | `/tmp/opencode/an9-native/20261102T124259-0ba91a2-full` |
| Forced-NumPy full verifier | 660 passed, 0 failed, 9 skipped | PASS | PASS | `/tmp/opencode/an9-numpy/20261102T124259-0ba91a2-full` |
| Reference checks | 6/6 PASS, exit 0 | | | `/tmp/opencode/an9-refs/` |

The 9 skips in the forced-NumPy run are the named native-parity tests.
