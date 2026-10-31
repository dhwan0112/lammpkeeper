# Analytic MSD

`analyze_msd` must return exact squared displacements on frames built by hand,
following atom IDs through type changes and accumulating minimum-image steps on
periodic axes. These are the identities a user relies on when reading a
diffusion curve.

## Sub-features

- `msd-shift` two atoms displaced by (1, 2, 2) give MSD [0, 9] and, with dt_fs 2 over 100 steps, time [0, 0.2] ps.
- `msd-type-swap` static atoms whose type labels swap give MSD [0, 0] for the initial type-1 cohort.
- `msd-periodic` one atom moving from x 9.5 to 0.5 in a 10 A periodic box gives MSD [0, 1].
- `msd-variable-box` one atom with x 9.5 -> 0.5 -> 6.5 while the x box length goes 10 -> 12 -> 8 gives MSD [0, 9, 1]: steps +3 and -2 under the documented current-frame-length minimum image. A first-frame-length implementation would give [0, 1, 9]. This pins the convention; it is not evidence of physical diffusion accuracy, and if unwrapping moves to fractional coordinates or dump unwrapped columns the expected value must be revised.

## How to get to it (user POV)

- In the post shell, `analyze msd` after loading a dump.
- From Python, `lammps_post.analysis.analyze_msd(frames, col_idx, species_type=..., dt_fs=..., pbc=...)`.

## Driving it with verify_refs.py

Preconditions:

- NumPy importable; no fixture needed.

- **Run the check.** `HOME="$LKPR_HOME" python3 .claude/skills/verify/scripts/verify_refs.py --only analytic-msd`. Output ends with `PASS analytic-msd — all 5 reference keys within tolerance (5 analytic)`.
- **Inspect a key.** In `results.json`, `keys.periodic_crossing_msd.measured` is `[0.0, 1.0]` and every `max|diff|` is 0 or at the 1e-16 level.
- **Proof.** Quote the `PASS analytic-msd` line.

## Gotchas

- Frames use the column map `{'id': 0, 'type': 1, 'x': 2, 'y': 3, 'z': 4}` and a 10 x 10 x 30 box. Changing the box or the step gap changes the time axis and the periodic case.
- The periodic case needs `pbc=(True, True, False)`; with x non-periodic the step is 9 A, not 1 A, and the check fails by design.
- Tolerances are 1e-12 because the inputs are exact float64 values; the regression suite uses looser float32 tolerances for a different reason.
- `analyze_msd` does not subtract affine cell motion. On NPT trajectories, especially solids, the MSD plateau carries a box-scaling component; in the ACE fixture that component (about 0.37 A for an atom near x = 16 when the box grows 16.79 -> 17.18 A) is the same size as the MSD endpoint itself. The variable-box case here tests only the unwrap convention.
- The shell's default dt_fs heuristic (0.25 fs) differs from the ACE fixture's real timestep (1 fs, `timestep 0.001` in metal units). MSD values are unaffected; the time axis and any diffusion coefficient are off by that factor.
