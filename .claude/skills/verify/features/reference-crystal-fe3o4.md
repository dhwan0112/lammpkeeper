# Reference crystal Fe3O4

The built-in magnetite cell in `lammps_post.references` is the comparison
standard users overlay on measured RDFs. Its geometry must reproduce the
analytic tetrahedral and octahedral Fe-O bond lengths of the Fd-3m (origin 2)
spinel at the declared lattice constant.

## Sub-features

- `crystal-cell` has a = 8.396 A, 24 Fe and 32 O in the 56-atom cell.
- `crystal-bonds` gives nearest Fe-O distances of a*sqrt(3)*(u-1/8) for 8 tetrahedral Fe and a*sqrt((1/2-u)^2+2(u-1/4)^2) for 16 octahedral Fe, with u = 0.2549.
- `crystal-coordination` counts 4 and 6 oxygen neighbours within 2.3 A for those two Fe groups.
- `crystal-rdf` makes `compute_reference_rdf('Fe3O4')` put its first two non-empty bins on those two distances.

## How to get to it (user POV)

- In the post shell, `plot rdf` with a reference overlay, or `references` to list phases.
- From Python, `from lammps_post.references import CRYSTAL_DB, compute_reference_rdf`.

## Driving it with verify_refs.py

Preconditions:

- NumPy importable; no fixture needed.

- **Run the check.** `HOME="$LKPR_HOME" python3 .claude/skills/verify/scripts/verify_refs.py --only reference-crystal-fe3o4`. Output ends with `PASS reference-crystal-fe3o4 — all 7 reference keys within tolerance (3 analytic, 4 external)`.
- **Inspect a key.** In `results.json`, `keys.nearest_fe_o_sorted.detail` shows `max|diff|` at the 1e-13 level against 8 x 1.889044585587 and 16 x 2.058681908002; `keys.rdf_first_two_nonzero_r.measured` is `[1.875, 2.055]`.
- **Proof.** Quote the `PASS reference-crystal-fe3o4` line.

## Gotchas

- The RDF comparison tolerance is one bin width (0.03 A) because `compute_reference_rdf` reports bin centres; the direct-distance check carries the tight 1e-12 tolerance.
- The direct distances are computed here by brute-force image enumeration, independent of production minimum-image code, so a shared bug in MIC would not hide.
- This proves ideal geometry only, not phase stability, magnetic order or any force-field relaxation.
- The constants a = 8.396 A and u = 0.2549 are repository constants (`lammps_post/references.py`); their literature citation is pending in `sources`. The analytic keys prove the cell is consistent with those constants, not that the constants are right.
