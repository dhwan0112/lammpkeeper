# REV-ANALYSIS-7: RDF cutoff beyond the nearest-image limit

Status: fixed; verification below.
Branch: `fix/rev-analysis-7-rdf-half-box` from main `d552b7b`.

**Decision (maintainer, 2026-11-01):** warn, and report the limit in the result, plots and exports.
- The ADR-0003 / GEN-3 estimator is unchanged: RDF counts the nearest image only, and the caller chooses the cutoff.
- No result is rejected and no g value is changed.

## Problem (measured)

`compute_rdf` counts only the nearest periodic image of each pair. That count is complete only below `r_complete`, which is half the shortest nonzero periodic lattice vector.
- Two images of one atom closer than r differ by a lattice vector shorter than 2r, so below that limit no second image can be inside the cutoff.
- Beyond it, pairs are missed and g(r) is too low. Nothing reported this; the docstring only said "choose a suitable cutoff".

Example: 60 random atoms in a 10 Å periodic cube, `r_max = 6`, 12 bins. The comparison is against an independent count over all images with |n| ≤ 2.

| r (Å) | nearest image | all images |
| --- | --- | --- |
| 0.25 … 4.75 | identical | identical |
| 5.25 | 0.827 | 0.974 (15 % low) |
| 5.75 | 0.625 | 1.016 (38 % low) |

**Who is affected:**
- The shell default `r_max = 6` Å is affected in any periodic cell shorter than 12 Å.
- The committed ACE fixture and the RDF goldens are not affected: their boxes are large enough, and no golden changed.
- About 25 synthetic test calls use small cells beyond the limit. They now warn and are otherwise unchanged.

## Change

- **`lammpkeeper/core/geometry.py`:** new `unique_image_radius(cell)`, which returns half the shortest nonzero periodic lattice vector, or inf when no axis is periodic.
  - **Orthogonal cells:** exactly `min(L/2)` over the periodic axes.
  - **Tilted cells:** an exact Fincke–Pohst enumeration over the periodic rows. The plane-spacing bound was not used because it would flag valid cutoffs; for example a 10×10 cell with xy = 5 has limit 5.0 Å, not 4.47 Å.
  - It uses the same conditioning and node limits as `minimum_image`.
- **`lammps_post/analysis.py`:**
  - `compute_rdf` computes the limit for each contributing frame and returns `r_max` and `r_complete` (the smallest limit over the frames).
  - If `r_max > r_complete` it emits one `RuntimeWarning`. The warning names the limit, the timestep and the fix (`r_max <= r_complete`).
  - The legacy `z_pbc` switch is respected: with `z_pbc=True`, z limits the cutoff.
  - The fast path and the fallback path give the same limit, warning and g.
  - New helper `rdf_incomplete_from(data)`: returns the limit only when it is below `r_max`.
- **`lammps_post/plotting.py`:** when the range is incomplete, `plot_rdf` draws a dash-dot line at `r_complete` and shades the incomplete range. This applies to both the simple view and the reference-stack view.
- **`lammps_post/shell.py`:** CSV and LaTeX export headers add `r_complete: 5 Å; g(r) beyond counts nearest images only (undercounted)`. The line appears only when the range is incomplete, so complete exports are unchanged. The summary export lists `r_max` and `r_complete` with the other numeric fields.

## Tests

**New module:** `tests/test_rdf_cutoff.py` (6 tests), registered in `tests/run.py`.
- Tested against the unmodified analysis code, 4 of the 6 failed (`KeyError 'r_complete'`, missing export line).
- The exact-radius test checks the new helper against brute-force enumeration: 5 cells × all 8 PBC subsets.
- The all-image oracle test passes on both versions. It documents correct counts below the limit and the undercount above it.

**Changed expectation:** `test_species_selection.test_numeric_apis_keep_existing_return_keys_without_shell_metadata` pins the RDF return keys.
- It now includes `r_max` and `r_complete`.
- Justification, written in the test: they are numeric provenance, like `frame_window` (RDF-PROV-1), and you approved reporting the limit in the result.

**Related modules:** 14 modules (171 tests, with `LKPR_SLOW=1`) pass after that update. Before it, the schema test was the only failure.

## Not changed

- No g value, golden or fixture.
- Reference crystal RDFs (`references.py`, REV-REF-2) do not use `compute_rdf`.
