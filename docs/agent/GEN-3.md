# GEN-3 — Box metadata and restricted-triclinic geometry

Status: complete; [PR #20](https://github.com/dhwan0112/lammpkeeper/pull/20).
Baseline: merged main `5189289` (GEN-1).
Implementation branch: `gen/gen-3-box-pbc`; no package release is implied.

## Approved scope

The maintainer approved ADR-0003's recommended contract on 2026-10-28, after
independent geometry and I/O/consumer reviews. This is a bounded increment, not
support for every cell/coordinate/analysis combination.

| Path | Contract |
| --- | --- |
| Box metadata | immutable physical lo/hi, restricted `(xy,xz,yz)` tilts, lattice-vector PBC |
| Dump/data input | orthogonal or restricted triclinic; Cartesian x/y/z |
| RDF | exact nearest image, determinant volume, per-frame normalization |
| Triclinic MSD | fixed origin/matrix/PBC; initial atom-ID cohort |
| Other tilted geometry/slab consumers | visible rejection rather than flattened geometry |
| General rotated cells, scaled/unwrapped conversion, image reconstruction | not implemented |
| Existing orthogonal APIs/goldens | unchanged compatibility path |

No generated LAMMPS input, structure, job script, frozen fixture, numeric golden,
force-field convention, thesis tag or HPC site is changed. Synthetic cases are
analytic probes, not physical trajectories or the undecided GEN-8 reference.

## Why fractional rounding is not enough

Use row basis

```text
H = [[Lx,  0,  0],
     [xy, Ly,  0],
     [xz, yz, Lz]]
r = lo + fractional @ H
```

PBC selects lattice vectors a/b/c. A periodic b translation may alter Cartesian
x and y together; a nonperiodic Cartesian component is not a correct substitute
for a nonperiodic lattice direction.

An independent measured calculation on `a=(1,0,0), b=(.4,1,0), c=(0,0,1)`:

- Fractional delta `(.49,.49,0)` gives Cartesian `(.686,.49,0)`.
- Component rounding leaves it unchanged: norm `0.8430278761701774`.
- Subtracting a gives `(-.314,.49,0)`: norm `0.5819759445200463`.

The exact geometry path therefore searches integer combinations of periodic
vectors, with complete bounds/branch-and-bound and visible conditioning/work
limits. It does not silently use fractional rounding or a fixed 27-image search.
Orthogonal inputs retain their established component-wise arithmetic and ties.

The numerical geometry contract rejects condition numbers above `1e10`, singular
values outside `[1e-150,1e150]`, image coefficients above `2**45`, or searches
exceeding 50,000 integer nodes per displacement. These are supported numerical
limits, not physical cutoffs. Valid extreme-range Box metadata can still be
unsupported for a numerical analysis; it must raise rather than overflow.

A second independent probe exposed premature float64 residual cancellation for
`b=(.4,1,0)`, `d=(1e8,-4e7+.5799999,0)` with only b periodic. Exact rational
arithmetic on the represented input values measured
`||d-b||² - ||d||² = +1.9285048212580592e-07`: image zero is shorter. The corrected
implementation compares original-input image objectives using protected factored
differences and exact `Fraction` fallback for uncertain signs, then rounds the
chosen residual. Tests also emulate platforms without extended `longdouble`.

## Public model and compatibility

```python
from lammpkeeper.io import Box

cell = Box((-2, 3, 5), (8, 15, 25), tilt=(-3, 4, -2),
           pbc=(True, True, False))
assert cell.volume == 2400
```

`cell.bounds` is physical restricted lo/hi, **not** an enclosing Cartesian box.
The enclosing dump limits for this example are x `[-5,12]`, y `[1,15]`, z `[5,25]`;
using their widths would give the wrong volume. `Box.from_dump_bounds` applies
the documented LAMMPS correction, including the `xy+xz` corner. Data-file bounds
are already physical and must not be corrected twice.

Unknown `pbc=None` is valid metadata, not an all-periodic default. Resolve with
`cell.with_pbc(flags)` without mutating cached source metadata. Core wrapping/MIC
requires explicit flags. Geometry functions live in `lammpkeeper.core.geometry`;
Box/file models contain no species/domain logic.

Legacy `DumpReader`, `parse_dump` and `parse_data_file` defaults remain
orthogonal-only. New dump support uses `box_model=True`; the post shell opts into
that path. New frames retain physical `frame['box']` compatibility bounds and
carry authoritative `frame['cell']`. Inconsistent typed/legacy copies reject.
Raw retained tilt without a valid typed cell is not treated as supported geometry.
If present, the retained `triclinic` Boolean means nonzero geometric tilt, not
merely a restricted-format header; it must agree with the Box.

Indices are bound to source stat identity and the geometry/header contract.
Independent equal-offset/equal-bounds files with different tilts reproduced a
wrong-cell read before this guard was added. Foreign, stale, unbound and
incompatible indices now fail before payload parsing/species evidence. Compatible
readers of the same unchanged source may still share indices across projection,
dtype, native/NumPy backend and view limits.

```python
from lammps_post.parsers import parse_dump, read_data_file

frames, columns, col_idx = parse_dump('trajectory.dump', box_model=True)
data = read_data_file('structure.data', pbc=(True, True, False))
# data contains atoms, cell, masses and species without changing the old tuple API.
```

Box-aware restricted-triclinic input requires complete literal Cartesian x/y/z.
Other coordinate families are not silently substituted or unwrapped; image flags
are not used to reconstruct coarse-sampled motion. General `abc origin` or vector
cells remain rejected. Native and NumPy atom paths share the same Python geometry
scanner; native success must be demonstrated rather than inferred from fallback.

## Analysis and session semantics

RDF counts nearest images, not all repeated images, and retains the existing
ordered-pair/global-density convention without nonperiodic shell corrections.
Choose a physically suitable cutoff; a mathematically correct histogram does
not establish complete spherical sampling in a small or open cell. Triclinic
initial support uses complete NumPy pair search, not orthogonal cKDTree boxsize.
Orthogonal RDF still honors its legacy `z_pbc` switch when `pbc=None`, including
typed frames; explicit three-axis masks must agree with resolved Box metadata.

Wrapped-coordinate triclinic MSD assumes each true step is strictly within the
periodic lattice's Voronoi cell. Fractional components below half are not enough;
wrapped snapshots cannot reveal all aliasing. Cell deformation/origin changes,
flips and boundary changes reject; no affine-motion or diffusion convention is
invented. Existing orthogonal variable-length behavior remains legacy behavior.

The shell resolves PBC from dump flags then explicit input metadata. A tilted
cell cannot infer PBC from an automatic surface. Managed input changes must not
leave stale masks in cached Box objects. GEN-1 raw species provenance, manifest
groups, source transactions and warned manual `set types` lifetime are retained.

Unsupported O2, density, coordination and slab geometry/normalization requests
fail clearly, including batch `analyze all`; partial results are not reported as
a completed analysis. Unrestricted charge evolution/charge-threshold OR and
spin/thermo quantities remain geometry-independent; z-restricted charge/OR still
reject. Interactive pure curves do not compute a slab z-focus. RDF/MSD curve
plots do not claim arbitrary tilted-cell visualization.

## Verification

The following parent-run results are **measured**, not inferred. Full verification
uses isolated HOME and the unchanged slow RDF/MSD goldens. Runs recorded HEAD
`83b6a77` with the final session/runner/documentation changes present in the working
tree; subsequent source commits preserve those tested bytes. A separate repeat
on committed `a0c201c` also measured **393 passed, 0 failed, 0 skipped**, with post
analyses/real plots and prep artifacts/script syntax all passing. Only the
pre-existing untracked user directory was present when that repeat started.

| Environment / path | Tests | Post smoke | Prep smoke |
| --- | --- | --- | --- |
| Python 3.12.14, NumPy 2.5.3, real native parser | 393 passed, 0 failed, 0 skipped | analyses + real plots persisted | required artifacts + bash syntax passed |
| Same interpreter, `LKPR_NO_NATIVE=1` | 387 passed, 0 failed, 6 skipped | analyses + real plots persisted | passed |
| Default Python 3.14.4, NumPy 2.3.5, native | 377 passed, 0 failed, 16 skipped | analyses persisted | skipped: ASE absent |
| External pure-Python wheel, five GEN-3 modules | 81 passed, 0 failed, 1 skipped | actual generic CLI dispatch covered by new tests | help/import smoke only |

Commands (all from the checkout unless the wheel script is specified):

```bash
PYTHON=/home/kim/opt/miniforge3/envs/chem/bin/python TMPDIR=/tmp/opencode \
  LKPR_VERIFY_DIR=/tmp/opencode/gen3-final-rich PYTHONDONTWRITEBYTECODE=1 \
  bash .cursor/skills/verify-lkpr/scripts/verify.sh full
PYTHON=/home/kim/opt/miniforge3/envs/chem/bin/python LKPR_NO_NATIVE=1 \
  TMPDIR=/tmp/opencode LKPR_VERIFY_DIR=/tmp/opencode/gen3-final-numpy \
  PYTHONDONTWRITEBYTECODE=1 bash .cursor/skills/verify-lkpr/scripts/verify.sh full
TMPDIR=/tmp/opencode LKPR_VERIFY_DIR=/tmp/opencode/gen3-final-default \
  PYTHONDONTWRITEBYTECODE=1 bash .cursor/skills/verify-lkpr/scripts/verify.sh full
/home/kim/opt/miniforge3/envs/chem/bin/python /tmp/opencode/gen3-wheel-smoke.py
```

Local evidence directories (not repository artifacts):

- `/tmp/opencode/gen3-final-rich/20261028T102006-83b6a77-full`
- `/tmp/opencode/gen3-final-numpy/20261028T102013-83b6a77-full`
- `/tmp/opencode/gen3-final-default/20261028T102013-83b6a77-full`
- `/tmp/opencode/gen3-wheel-dggubkne/wheel.log`
- `/tmp/opencode/gen3-committed/20261028T102513-a0c201c-full`

The wheel was built from a separate source copy without `.so` files, installed
with `--no-deps --target` outside the checkout, and exercised from that install.
Imports were asserted to come from the installation, not the source tree. The
five new modules ran there, including actual CLI and real RDF/MSD rendering;
unified/legacy module help and the installed `lkpr` entry point also passed.
Artifact: `lammpkeeper-1.2.0-py3-none-any.whl`, SHA-256
`4578da1cf2e83404b58c0a4ec6f8dc143df1f41ed16505970d1ecd5d0e2004c3`.
This is a local install check, not a package release or native wheel claim.

### Explicit skipped tests

Forced NumPy skips exactly these six native-only checks (the native run passed
all six):

- `test_dump_reader.test_native_parser_matches_loadtxt`
- `test_periodicity.test_native_boundary_metadata_matches_numpy_without_fallback`
- `test_slab_reference.test_slab_native_and_numpy_match_every_reader_access_path`
- `test_species_metadata.test_dump_native_metadata_parity_without_numpy_fallback`
- `test_species_metadata.test_dump_native_raw_type_ids_without_fallback`
- `test_triclinic_io.test_box_aware_real_native_success_matches_numpy_without_fallback`

The external wheel skips only the final item because it deliberately contains no
native extension. Default-Python skips are these four ASE tests and twelve real
Matplotlib checks; the rich run passed all of them:

- `test_fair_comparison.test_all_force_fields_build_identical_coordinates`
- `test_fair_comparison.test_wall_does_not_depend_on_the_force_field`
- `test_audit_prep.test_even_width_surfaces_preserve_written_periodic_nearest_distance`
- `test_audit_prep.test_odd_width_skew_slabs_are_rejected`
- `test_audit_references_plots.test_normalized_spin_legend_states_different_denominators`
- `test_audit_references_plots.test_profile_later_arrivals_cannot_establish_initial_cohort_t50`
- `test_audit_references_plots.test_profile_union_nan_trajectories_and_present_population_metrics`
- `test_audit_references_plots.test_real_and_metal_pressure_artists_have_correct_units`
- `test_audit_references_plots.test_slab_pressure_missing_or_invalid_geometry_is_visibly_uncorrected`
- `test_audit_references_plots.test_slab_pressure_uses_per_frame_lz_over_thickness`
- `test_audit_references_plots.test_t50_requires_half_initial_population_and_correct_event_index`
- `test_audit_integration.test_log_only_and_mixed_source_plots_use_explicit_log_units_and_timestep`
- `test_audit_integration.test_optimizer_only_thermo_cannot_be_labeled_elapsed_md_time`
- `test_audit_integration.test_parsed_md_timeline_not_absolute_optimizer_or_reset_steps_is_plotted`
- `test_slab_reference.test_slab_profile_and_curves_render_without_false_half_uptake`
- `test_triclinic_session.test_triclinic_session_supported_curves_render_with_real_matplotlib`

MDAnalysis is absent in both environments; pandas is absent in the default one,
and rich is absent in the expanded one. No MDAnalysis integration or pytest
execution is claimed. The dependency-free runner reports explicit skips.

### Preservation and review

Parent checks measured all 44 pre-existing test/fixture/golden files (everything
under baseline `tests/` except the intentionally extended runner) byte-for-byte
unchanged. The thesis tag still resolves to
`cdf5c38e975871debf64eb6d810e78a08165c381`; it was not moved. The pre-existing
untracked `Claude outputs/` is untouched. Source grammar/docstring audit passed
for 14 changed Python files and 401 module/class/function docstrings, using
Python 3.9 AST grammar and English documentation. `git diff --check` passed.

Manual blast-radius review traced Box → core geometry → legacy parser opt-in →
session PBC/cache transforms → RDF/MSD/plots, with orthogonal slab/O2/species
regressions included in the full suite. Independent physics review checked exact
lattice images, protected comparisons, determinant normalization, ID cohorts,
constant-cell/aliasing restrictions and visible unsupported-consumer errors.
Follow-up regressions resolved the independent cancellation/index findings,
retained-flag disagreement, pure-OR overrestriction, lightweight legacy-state
guards and accidental spatial focus in pure plots. New synthetic checks include:

- Physical bounds versus independent Cartesian vertices and determinant volume.
- All PBC subsets, skew-rounding counterexamples, shifts outside nearby images,
  finite/conditioning/work-limit errors and immutable metadata.
- Independent pair enumeration and analytic ID-tracked wrapped trajectory walks.
- All reader access modes, projections, native/NumPy parity and source guards.
- Session PBC resolution, cache/transform eviction, rollback, GEN-1 contracts and
  unsupported-consumer rejection; actual generic RDF/MSD CLI dispatch.
- Every existing test/golden unchanged, full verifier with isolated HOME and named
  skips, Python 3.9/docstrings and a wheel built outside the checkout.

Project slash commands are unavailable; explicit architecture, blast-radius and
physics review checks are manual equivalents, not claimed command runs. Actual
verification uses the repository `verify-lkpr` script. No real LAMMPS/HPC,
potential evaluation, equilibrium/diffusion or GEN-8 material validation is claimed.
