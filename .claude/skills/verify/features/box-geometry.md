# Box geometry

`lammpkeeper.io.Box` is the cell model every frame carries. Built from LAMMPS
enclosing dump bounds, it must recover the physical edge lengths by removing the
tilt, report shear as non-orthogonality, and keep volume = lx * ly * lz.

## Sub-features

- `box-orthogonal` enclosing bounds (0,10) (0,10) (0,30) give volume 3000 A^3 and `is_orthogonal` True.
- `box-tilted` enclosing bounds (0,12) (0,10) (0,30) with tilt (2, 0, 0) give physical lengths 10, 10, 30, volume 3000 A^3 and `is_orthogonal` False.
- `box-enclosing` enclosing bounds (0,10) (0,10) (0,30) with tilt (2, 0, 0) shrink to lengths 8, 10, 30 and volume 2400 A^3, pinning the enclosing-bounds convention.

## How to get to it (user POV)

- Any dump or data file load; the frame's `cell` is a `Box`.
- From Python, `lammpkeeper.io.Box.from_dump_bounds(bounds, tilt=(xy, xz, yz), pbc=None)`.

## Driving it with verify_refs.py

Preconditions:

- NumPy importable; no fixture needed.

- **Run the check.** `HOME="$LKPR_HOME" python3 .claude/skills/verify/scripts/verify_refs.py --only box-geometry`. Output ends with `PASS box-geometry — all 7 reference keys within tolerance (7 analytic)`.
- **Proof.** Quote the `PASS box-geometry` line.

## Gotchas

- `from_dump_bounds` takes LAMMPS enclosing dump bounds (`xlo_bound = xlo + min(0, xy, xz, xy+xz)`, `xhi_bound = xhi + max(...)`). Feeding it physical bounds plus a tilt silently shrinks the cell; the first draft of this check made exactly that mistake and reported volume 2400 for a "3000" cell. Data-file bounds are already physical and go through `read_data_file`.
- Volume tolerances are rel 1e-12 (relaxed from 1e-14 on 2026-10-31 for portability); today the products are exact.
- Volume invariance under shear holds for any tilt; only `xy` is exercised here. `xz` and `yz` are candidates if a triclinic reference is added.
