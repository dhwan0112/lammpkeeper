# Analytic RDF pair

`compute_rdf` on a single A-B pair must put its only non-empty bin on the true
pair distance, both for a pair inside the box and for a pair split across a
periodic face. This is the smallest input that proves binning and minimum image
together.

## Sub-features

- `rdf-isolated` A at (5, 5, 5) and B at (7, 5, 5) in a 20 A periodic box: one non-empty bin, centre within 0.015 A of 2.0 A.
- `rdf-wrapped` A at x 0.5 and B at x 19.5: one non-empty bin, centre within 0.015 A of 1.0 A.
- `rdf-binning` r_max 6.0 with 200 bins gives a 0.03 A bin width.

## How to get to it (user POV)

- In the post shell, `analyze rdf` after loading a dump.
- From Python, `lammps_post.analysis.compute_rdf(frames, col_idx, type_a, type_b, r_max=6.0, n_bins=200, pbc=...)`.

## Driving it with verify_refs.py

Preconditions:

- NumPy importable; no fixture needed.

- **Run the check.** `HOME="$LKPR_HOME" python3 .claude/skills/verify/scripts/verify_refs.py --only analytic-rdf-pair`. Output ends with `PASS analytic-rdf-pair — all 5 reference keys within tolerance (5 analytic)`.
- **Inspect a key.** In `results.json`, `keys.isolated_pair_peak_r.measured` is `1.995` (bin centre) and `keys.isolated_pair_nonzero_bins.measured` is `1`.
- **Proof.** Quote the `PASS analytic-rdf-pair` line.

## Gotchas

- The peak position is a bin centre, so the tolerance is half a bin (0.015 A), not an exact match.
- Only the peak position and bin count are checked. The peak height of a single pair depends on the normalisation convention and is not a reference here.
- `pbc=(True, True, True)` is required for the wrapped case; without it the pair is 19 A apart and falls outside `r_max`, leaving zero non-empty bins.
