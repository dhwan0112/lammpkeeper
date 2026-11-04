# REV-REF-2: reference RDFs enumerate every periodic image inside the cutoff

Status: fixed and verified (PR #94).
Branch: `rev-ref-2/complete-images` from `4c578cc` (main after PR #93).
Source: BACKLOG REV-REF-2 (P2; F-REF-2 in `docs/agent/REVIEW-20261028.md`).

## Problem

`lammps_post/references.py::compute_reference_rdf` replicated the unit cell
into a fixed `supercell=(4, 4, 4)` and then applied a componentwise
minimum-image convention in the supercell basis. Any neighbour farther than
half the supercell width along a lattice direction was counted at most once
instead of twice (the image at exactly half the width is rounded one way), so
shells near the cutoff were incomplete. With the default 6 Å cutoff the
fourfold alpha-Fe supercell has half-side 5.733 Å, which is exactly the 2a
Fe-Fe shell: the reference reported coordination 3 there instead of 6, and 61
Fe-Fe neighbours inside 6 Å instead of 64. The docstring documented the
limitation but nothing enforced a safe cutoff/replication pair, and the
componentwise wrap is additionally wrong for oblique cells whose perpendicular
widths are smaller than their edge lengths.

## Change

`lammps_post/references.py`:

- `_lattice_image_offsets(cell, r_max)` returns the integer lattice
  translations that can bring a site pair closer than `r_max`. The bound is
  derived from the perpendicular widths `w_i = V / |a_j x a_k|`: a displacement
  `(f + n) @ cell` with `f` wrapped to [-0.5, 0.5] has length at least
  `(|n_i| - 1/2) w_i`, so every offset with `|n_i| <= ceil(r_max / w_i + 1/2)`
  is enumerated and nothing outside the box can contribute. This is exact for
  any cell shape. A singular cell, a non-finite cell or a non-positive `r_max`
  raises `ValueError`.
- `compute_reference_rdf` pairs every element-A site of the unit cell with
  every enumerated image of every element-B site and histograms the distances
  below `r_max`. No supercell is built and no minimum-image convention is
  applied; the `supercell` parameter is removed (nothing in the repository
  passed it). Normalisation (`N_A * shell volume * N_B / V`, both directions
  for identical elements, `r > 0.01 Å`) is unchanged, so bins that the old
  scheme populated completely keep their values.
- The docstring now states the completeness guarantee instead of the former
  caveats.

Cost: the built-in phases at 6 Å take 1-11 ms each; magnetite O-O at 12 Å
takes 13 ms.

## Tests

`tests/test_reference_images.py` (4 tests). The oracle is a direct Cartesian
image enumeration whose range is justified from the reciprocal lattice
(`w_i = 1 / |b_i|`, offsets up to `ceil(r_max / w_i) + 1` because the unwrapped
fractional difference lies in (-1, 1)), independent of the production bound.

- `test_alpha_fe_outer_shells_are_complete_at_the_default_cutoff`: the bcc
  shell table (8, 6, 12, 24, 8, 6 at a·√3/2, a, a·√2, a·√11/2, a·√3, 2a) is
  recovered per site from g(r) at the default 6 Å cutoff, total 64; at 7 Å
  the a·√19/2 shell has 24 neighbours. Before the change the 2a shell gave 3.
- `test_builtin_histograms_match_independent_image_enumeration`: every
  built-in phase and every ordered element pair (13 combinations) reproduces
  the brute-force count in every one of 200 bins.
- `test_cutoff_beyond_the_cell_and_skew_cells_stay_complete`: a 2 Å simple
  cubic cell at a 7 Å cutoff matches the lattice-vector shell table; a
  strongly oblique two-site cell matches the oracle for A-B, B-A and A-A.
- `test_offset_box_is_the_width_bound_and_singular_cells_are_rejected`: the
  offset box for `diag(2, 4, 13)` at 6 Å is ±4, ±2, ±1; shearing never shrinks
  it; a flat cell, a zero cell, `r_max = 0` and a NaN cell raise `ValueError`;
  unknown phase, absent element and non-string/non-dict input still return
  `None`.

## Verification

| Check | Result |
|---|---|
| `tests/test_reference_images.py` (4 tests) | pass |
| `test_audit_references_plots`, `test_cif_occupancy`, `test_rdf_reference_pair`, `test_verify_refs`, `test_symop_grammar`, `test_slab_reference` | pass (matplotlib skips only) |
| old scheme on main (4c578cc): alpha-Fe Fe-Fe per-site counts at the six shells | 8, 6, 12, 24, 8, 3 (total 61) |
| new scheme: same shells | 8, 6, 12, 24, 8, 6 (total 64) |
| `HOME=$(mktemp -d) /usr/bin/python3 tests/run.py` | 765 passed, 0 failed, 26 skipped (761/0/26 before) |
| same with `LKPR_NO_NATIVE=1` | 752 passed, 0 failed, 39 skipped (748/0/39 before) |

## Review round

An independent read-only review of the full diff found no correctness defects. It checked the
width bound (`|n_i| < r_max / w_i + |f_i|` with `|f_i| <= 1/2` whichever way `np.round` resolves an
exact half, so `ceil(r_max / w_i + 1/2)` covers it; `abs(det)` handles left-handed cells; the cross
product uses the other two rows), the broadcasting of the per-site distance block, the unchanged
normalisation (old counts, N_A and V were all 64x the unit-cell values), the independence and
sufficiency of the test oracle's reciprocal-lattice range, the bcc and simple-cubic shell tables and
their window separations (smallest gaps 0.21 Å and 0.29 Å against windows of ±0.06 Å and ±0.04 Å),
the integer recovery of counts from g(r), the 13 phase/pair combinations, and that nothing in the
repository still passes `supercell=`. The only remark was that the devlog placeholders were still
unfilled at review time; they are filled above. No code changes were needed after review.
