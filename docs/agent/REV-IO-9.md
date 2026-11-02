# REV-IO-9: pair_coeff species maps use exact pair-style names

Status: fixed; verification below.
Branch: `fix/rev-io-9-hybrid-exact-alias` from main `94e562f`.
Decision: the maintainer approved on 2026-11-02 (§8 species-mapping convention) the use of exact names only, the same ADR-0005 table the classifier uses.

## Problem

`parse_input` made two species-mapping decisions by substring:

- **Which hybrid sub-styles carry a species map:** `any(name in substyle for name in ('pace', 'ace', 'reax', 'hdnnp', 'n2p2'))`.
- **Which styles take no potential file in `pair_coeff`:** `any(name in substyle for name in ('hdnnp', 'n2p2'))`.

ADR-0005's classifier (`classify_pair_style`, `_PAIR_STYLE_ALIASES`) accepts exact LAMMPS names only. Measured on unmodified code: `pair_style hybrid ace lj/cut 2.5` with `pair_coeff * * ace pot.file A B` produced `element_map {1: 'A', 2: 'B'}`, although `ace` is not a LAMMPS pair style.

## Change

Both decisions in `lammps_post/parsers.py` now look the name up in `_PAIR_STYLE_ALIASES`. A hybrid instance number (`pace 1` → `pace:1`) is removed before the lookup.

| Case | Behavior |
| --- | --- |
| Real LAMMPS names (`pace`, `pace/kk`, `reaxff`, `reax/c`, `hdnnp`, numbered `pace 1`) | Map exactly as before |
| Hybrid sub-styles that are not LAMMPS names (`ace`, `n2p2`, made-up `mypace`) | No longer create a species map |
| Non-hybrid `hdnnp` | Still takes elements only (no potential file) |
| Every other non-hybrid style | `file elements`, as LAMMPS reads `pair_coeff * * file elements` |
| Non-hybrid `pair_style n2p2` | Read with the general `file elements` rule; it is not a valid LAMMPS style, and LAMMPS rejects it |

Prep-generated inputs do not use hybrid styles and parse as before. `test_input_math` (real prep ACE and ReaxFF output) passes.

## Tests

New `tests/test_pair_coeff_mapping.py` (3 tests, made-up labels A and B), registered in `tests/run.py`.
- **Before the fix:** 2 of the 3 fail (non-LAMMPS hybrid names mapped; non-hybrid `n2p2` took no file). The third pins unchanged mapping for real LAMMPS sub-styles and passes before and after.
- **After the fix:** all 3 pass.
- **Related modules:** `test_run_metadata`, `test_session_metadata`, `test_audit_parsers`, `test_species_metadata`, `test_species_session`, `test_input_math`, `test_audit_workflow`, `test_audit_integration` and `test_fair_comparison` pass with `LKPR_SLOW=1`.
