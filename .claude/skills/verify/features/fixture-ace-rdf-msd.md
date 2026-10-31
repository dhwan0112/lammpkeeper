# ACE fixture RDF/MSD snapshot

Running the standard trajectory analyses on the committed ACE Fe3O4 fixture must
give the same numbers it gave at `baseline_commit`: the Fe_up-O g(r) peak and the
Fe_up and O MSD endpoints. These keys are `snapshot` kind. A PASS means the
output is unchanged since that commit; it is not evidence that the numbers are
physically right.

## Sub-features

- `snapshot-rdf-window` `compute_rdf` averages the last 20 frames (steps 3400-3587 in this fixture), checked as a `fixture` key from the dump's TIMESTEP headers.
- `snapshot-rdf-peak` the Fe_up-O g(r) peak bin is at 1.875 A (tolerance half a bin, 0.015 A) with height 55.81309067093663 (rel 1e-8).
- `snapshot-msd-feup` MSD(Fe_up) over all 350 frames with pbc (True, True, True) ends at 0.07462399282798773 A^2 (rel 1e-8).
- `snapshot-msd-o` MSD(O) ends at 0.04990725287878125 A^2 (rel 1e-8).

## How to get to it (user POV)

- `lkpr post --dump tests/fixtures/ace_examples/regular_MD/traj.dump` then `rdf Fe_up-O` (default `--frames 20`) and `analyze msd` in the shell.
- From Python, `compute_rdf(frames, col_idx, type_a=1, type_b=3, z_pbc=True)` and `analyze_msd(frames, col_idx, species_type=1|3, dt_fs=state.dt_fs, pbc=(True, True, True))`.

## Driving it with verify_refs.py

Preconditions:

- `HOME="$LKPR_HOME"` is a disposable directory; doctor reports `fixture: present`.
- The check loads the full 350-frame fixture and runs two whole-trajectory MSDs (about 5 s).

- **Run the check.** `HOME="$LKPR_HOME" python3 .claude/skills/verify/scripts/verify_refs.py --only fixture-ace-rdf-msd`. Output ends with `PASS fixture-ace-rdf-msd — all 5 reference keys within tolerance (1 fixture, 4 snapshot; snapshot keys are a regression check against baseline_commit a974563, not a correctness proof)`.
- **Inspect a key.** In `results.json`, `keys.rdf_frames_timestep_range.measured` is `[3400, 3587]` and every snapshot key's `max|diff|` is at the 1e-16 level.
- **Proof.** Quote the `PASS fixture-ace-rdf-msd` line including its snapshot wording.

## Gotchas

- `compute_rdf` defaults to the **last** `max_frames` = 20 frames. In this fixture those are the tail of the final `minimize` + `box/relax` phase (run_md.lammps), where the structure is a relaxed crystal: the Fe_up-O first peak occupies a single 0.03 A bin (neighbouring bins are exactly 0) and the relaxed distances 1.8828-1.8849 A sit 0.005 A below the 1.89 bin edge. The first 20 frames (1200 K NPT) would give a broad peak with its maximum at 1.845 A instead. The shell prints `last N frames` while computing, but the plot legend and the returned dict show only the count.
- `analyze_msd` does not subtract affine cell motion. The run is NPT with the box moving between 16.737 and 17.182 A; for a solid this adds a box-scaling component to the MSD plateau that in this fixture is the same size as the endpoint itself (about 0.37 A displacement for an atom near x = 16). The endpoints are therefore snapshots of the implementation, not diffusion measurements.
- The shell's dt_fs heuristic (0.25 fs) differs from the fixture's actual timestep (1 fs). The MSD values do not depend on dt_fs; the time axis and any diffusion coefficient do.
- Both fixture POSCARs give type 2 the manganese mass 54.938045 (phonopy filled masses from the element symbol); the repository writer uses the iron mass 55.845. Positions, and so these snapshots, are unaffected.
- A changed number here is a finding to investigate, not a reason to edit the JSON. A deliberate re-baseline records a new `baseline_commit` and the reason in `source`.
