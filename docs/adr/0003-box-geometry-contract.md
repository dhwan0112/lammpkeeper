# ADR-0003: Box metadata and restricted-triclinic geometry

- **Status:** accepted (2026-10-28; maintainer approved the recommended contract)
- **Date:** 2026-10-28
- **Deciders:** 김동환 (maintainer). Agents may draft; only the maintainer accepts.
- **Backlog:** GEN-3
- **Baseline:** main `5189289fbc657f9b3e59f942974ceb32d4e3f2c3`

## Context

ADR-0001 accepts an `io.Box` model and NumPy core geometry, but not their exact
public API, compatibility migration or supported trajectory conventions.

Source inspection and two independent read-only reviews establish:

- Dump/data readers currently reject triclinic geometry. Frames and indices
  expose orthogonal `(3,2)` bounds; native code parses atom rows, not geometry.
- RDF/MSD/O2 use Cartesian-axis wrapping. Several slab/z/plot consumers assume
  orthogonal bounds without an independent typed-cell guard.
- GEN-1 depends on shared header validation, lazy species evidence and atomic
  session load/unload; geometry normalization must not bypass those contracts.
- Legacy `parse_data_file` has a three-item return. `parse_data_species` calls it
  for validation, so replacing only one shell reader would not enable tilted data.
- Existing synthetic tests require loud rejection of unsupported retained tilt,
  general cells and legacy reader inputs. Frozen fixtures/goldens are untouched.

A separate calculation measured a fractional-rounding counterexample with basis
rows `a=(1,0,0), b=(.4,1,0), c=(0,0,1)` and fractional delta `(.49,.49,0)`.
The Cartesian delta is `(.686,.49,0)`: rounding each fractional component selects
norm `0.8430278761701774`; independent Cartesian image enumeration finds the
shorter `d-a` with norm `0.5819759445200463`. Even a modest restricted tilt makes
naive fractional rounding insufficient. This is an algorithm probe, not dynamics.

Evidence: `lammps_post/parsers.py`, `analysis.py`, `state.py`, `shell.py`;
`tests/test_audit_parsers.py`, `test_audit_analysis.py`, `test_msd.py`,
`test_periodicity.py`, `test_species_metadata.py`, `test_species_session.py`.
Project slash commands are unavailable; these are manual architecture/physics
reviews, not claims that `/architect` or `/interrogate` ran.

LAMMPS format references consulted on 2026-10-28 (release docs, 30Sep2026):
- https://docs.lammps.org/Howto_triclinic.html
- https://docs.lammps.org/dump.html

## Options

### A. Keep rejecting all triclinic inputs

Preserves current compatibility and Fe-O results, but leaves GEN-3 open.

### B. Add a typed opt-in path with bounded support (recommended)

Add Box metadata and exact periodic geometry. Enable restricted-triclinic dump
and data reading through additive APIs, route the shell through them, and support
RDF plus constant-cell triclinic MSD. Keep legacy reader defaults and orthogonal
arithmetic unchanged. Guard unsupported consumers rather than passing bare bounds.

### C. Replace all bounds arrays and support general/deforming cells at once

A broad API and physics change: every consumer and displacement convention must
be reconsidered together. It exposes published Fe-O reproducibility and is not
necessary for the GEN-3 completion check. Defer this larger extension.

## Decision

Adopt **B**. The maintainer approved the recommended API, limited support scope,
compatibility strategy and explicit rejection policy on 2026-10-28.

### 1. Immutable Box and conventions

```python
from lammpkeeper.io import Box

Box(lo, hi, tilt=(0.0, 0.0, 0.0), pbc=None)
Box.from_dump_bounds(bounds, tilt=(0.0, 0.0, 0.0), pbc=None)
cell.lo, cell.hi, cell.tilt, cell.lengths
cell.bounds         # physical lo/hi, shape (3,2); not an enclosing AABB
cell.matrix         # basis vectors as rows, shape (3,3)
cell.volume
cell.is_orthogonal
cell.pbc            # three booleans, or None for unresolved metadata
cell.with_pbc(flags) # a new immutable Box; do not mutate cached metadata
```

- Implement `lammpkeeper/io/box.py`, export `Box` from `io/__init__.py`, and add
  the package to setuptools. No element/FF/domain literals or legacy imports.
- `lo/hi` are finite length-three true restricted-cell parameters with strictly
  positive lengths. Tilt is finite `(xy,xz,yz)`. Validate rather than flatten.
- Row-basis convention, with `L = hi-lo`:
  `H = [[Lx,0,0], [xy,Ly,0], [xz,yz,Lz]]`, `r = lo + s @ H`.
  Volume is `det(H)`; axes refer to lattice vectors a/b/c, not Cartesian masks.
- Arrays returned by properties cannot mutate the model. No implicit default to
  all-periodic: `pbc=None` means unknown. Transforms/volume may use unknown PBC;
  wrapping/MIC/unwrapping require resolved flags.
- `from_dump_bounds` inverts LAMMPS enclosing-bound corrections:
  `xlo = xlo_bound - min(0,xy,xz,xy+xz)`;
  `xhi = xhi_bound - max(0,xy,xz,xy+xz)`;
  `ylo = ylo_bound - min(0,yz)`; `yhi = yhi_bound - max(0,yz)`;
  z is unchanged. Validate the corrected lengths. Data-file lo/hi are already
  physical parameters and must not receive these dump corrections.
- General `abc origin` / rotated vector-form cells remain unsupported and raise.

### 2. Core geometry and exact nearest images

```python
from lammpkeeper.core.geometry import (
    to_fractional, to_cartesian, wrap_positions, minimum_image, unwrap_step)

to_fractional(positions, cell)
to_cartesian(fractional, cell)
wrap_positions(positions, cell)
minimum_image(displacements, cell)
unwrap_step(previous_wrapped, current_wrapped, previous_unwrapped, cell)
```

Geometry uses NumPy only; no species/FF names or simulation-engine abstraction.
Validate finite Cartesian arrays ending in dimension three. Wrapping changes
only periodic fractional components; images are integer combinations of the
periodic lattice rows, even when their Cartesian components are coupled.

For skew cells solve `min_n ||d - n @ B||`, where B contains the periodic rows
and `n` is integral. Fractional/least-squares rounding supplies an incumbent,
not the answer. Use a provably complete finite search, not a fixed 27-image
neighborhood. One valid bound is:

- Let c minimize `||d-c@B||` continuously, let `n0=round(c)`, and
  `R=||(c-n0)@B||`. The residual perpendicular to B is constant for every image.
- Every improving/tied integer coefficient satisfies
  `||n-c|| <= R/sigma_min(B)`. Enumerate the enclosing integer intervals with
  conservative outward numerical padding, then choose the shortest image.
- A QR branch-and-bound implementation with an equivalent completeness argument
  is also allowed. Validate conditioning and enforce a documented search-work
  limit; inability to guarantee/finish the search raises visibly. No truncated
  answer or fallback to fractional rounding is allowed.
- Document a deterministic triclinic equal-minimum tie rule. Do not use a broad
  near-equality tolerance that intentionally chooses a longer image; antisymmetry
  at exact ties is not promised. Preserve legacy `np.round` ties and arithmetic
  in a dedicated orthogonal path, without matrix inversion.

### 3. Additive reader APIs and coordinate scope

- Add keyword-only `box_model=False` to `DumpReader` and `parse_dump`. Defaults
  retain existing orthogonal-only behavior and return schemas. No old rejection
  tests are weakened to make the new path pass.
- In Box-aware mode preserve `frame['box']` / `LazyFrames.boxes` as physical
  `(3,2)` / `(N,3,2)` arrays, and add authoritative per-frame `frame['cell']`.
  Retain explicit tilt metadata so a legacy consumer cannot mistake them for a
  complete orthogonal description. When both a typed cell and compatibility
  bounds/tilt are supplied, they must agree; contradictory copies raise instead
  of choosing a convenient representation. Preserve metadata in streaming/indexed/
  native, cached/uncached and transformed/sliced access; no reconstruction from
  bare bounds.
- Recognize exactly restricted `xy xz yz` headers with valid row lengths/flags.
  Reject partial markers, extra unexplained values and general-cell formats.
  Changing trajectory boundary flags remains unsupported. Each frame owns its
  physical origin/shape; RDF may consume different cells frame by frame.
- First triclinic coordinate scope is complete literal Cartesian `x,y,z` only.
  `xs/ys/zs`, `xu/yu/zu`, scaled-unwrapped conversion and image-flag reconstruction
  are not implemented. Other coordinate columns may remain raw properties, but
  cannot silently substitute for x/y/z or be advertised as interpreted. A tilted
  dump without the supported family fails clearly. Orthogonal legacy property
  reading remains unchanged.
- Geometry validation precedes publication of new atom/species evidence. Preserve
  GEN-1 raw type IDs/labels, native-success checks, source-change detection,
  projection semantics and transactional failed-load behavior.
- Add `lammps_post.parsers.read_data_file(filepath, *, pbc=None)` returning a
  structured dictionary with `atoms`, `cell` (Box), `masses`, `species` fields.
  Atom coordinates remain as stored; no data-image unwrapping is implied.
  Share validated extraction rather than calling the rejecting legacy parser.
  Keep `parse_data_file`'s existing three-tuple/default rejection and
  `parse_data_species` compatibility intact. Shell reads species and geometry
  together from the new API, avoiding duplicate incompatible validation.

### 4. Shell PBC and consumer policy

- Shell opts into the Box-aware dump/data APIs; no existing CLI flag is removed
  or renamed. Input/data/dump load/unload, rollback, transformed-frame cache
  invalidation and manual species override lifetime retain ADR-0002 behavior.
- PBC resolution remains dump flags → input boundary. Preserve legacy visible
  orthogonal fallback where applicable, but **do not infer triclinic PBC from a
  surface**. Unknown triclinic PBC blocks geometry analysis until explicit
  metadata is supplied. Do not freeze an input-derived mask into a stale Box.
- Typed-cell PBC and an explicitly supplied analysis mask must agree; contradictions
  raise. RDF may use Box PBC when its legacy `pbc=None` argument is omitted.
  Direct triclinic MSD callers supply a matching PBC mask because its existing
  signature retains the legacy slab default; shell supplies the resolved mask.
- Display true cell kind, physical parameters, tilt and resolved/unknown PBC in
  box inspection, not an invented orthogonal enclosing cell.
- Enable **RDF** with exact MIC and determinant volume, preserving ordered pair
  counting, equal per-frame normalization, species unions and output schema.
  Triclinic initially uses complete row-wise NumPy pairs; do not feed tilted
  lengths into orthogonal cKDTree boxsize. Existing orthogonal acceleration stays.
  Do not claim a separate accelerated triclinic backend was tested.
- Enable **MSD** for constant-origin, constant-matrix triclinic trajectories only.
  Preserve initial-cohort ID tracking. Reject triclinic deformation, cell flips,
  changing origin or PBC; do not invent an affine-motion/diffusion convention.
  Keep existing orthogonal variable-length behavior unchanged and documented.
- Wrapped-coordinate MSD assumes every true step lies strictly inside the
  periodic lattice Voronoi cell. Fractional components below one-half are not
  sufficient; wrapped samples alone cannot diagnose arbitrary aliasing. Available
  image/unwrapped fields are not a promise that this algorithm uses them.
- O2 pairing, density/coordination, slab penetration/OAR/charge-z, automatic
  surface interpretation, structure/slab normalization and geometry-dependent
  plot paths remain orthogonal-only for this increment. Guard them before bare
  bounds are used; unsupported requests fail visibly/nonzero, including batch
  `analyze all`. No partial cache is reported as complete. Pure charge/spin/thermo
  quantities may remain available where they do not invoke geometric/slab logic.
  RDF/MSD curve plots are geometry-independent; do not claim tilted-slab rendering.

### 5. Verification and preservation

After approval:

1. Add generic A/B/X Box/geometry tests: immutable data, bounds correction,
   determinant, transforms, periodic-vector masks, nonzero origins, out-of-cell
   points and all eight PBC subsets.
2. Use independently constructed Cartesian image enumeration for MIC and RDF,
   including the measured rounding counterexample, strong tilts, cutoff edges,
   same/overlapping species and changing instantaneous RDF cells. Test visible
   conditioning/work-limit failures, not silently skipped difficult cases.
3. Generate temporary wrapped fixed-cell triclinic trajectories from prescribed
   unwrapped coordinates; compare MSD to independent image walks/analytic values.
   Exercise shuffled IDs, type swaps and mixed PBC; reject unsupported changes.
4. Prove opt-in header/index/cache/native/NumPy parity and unsupported-consumer
   guards, plus GEN-1 transaction/metadata/group regressions and actual shell
   RDF/MSD dispatch. No fixture edits or new committed numeric trajectory.
5. Keep every existing test/golden expectation unchanged through the compatibility
   path. Orthogonal RDF/MSD fingerprints and TEST-3 outputs must remain unchanged;
   new supported behavior is tested through explicit typed cells/reader opt-in.
6. Run full verification with isolated HOME, explicit optional skips, package-wheel
   import smoke and manual blast-radius/interrogation checks. No LAMMPS/HPC run,
   potential evaluation or general physical validation is claimed.

Approval authorizes this incremental GEN-3 contract. Completion and numerical
preservation still require the checks above. No rebaseline, generated prep/job/
structure change, FF/species convention change or GEN-8 system choice is
authorized here.
