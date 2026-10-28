# Changelog

All notable changes to LammpKeeper (`lkpr`) are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Changes since the last tagged state, grouped by migration stage
(see `MIGRATION.md`). No version has been released from this section yet;
REL-0 tagged the historical thesis baseline `cdf5c38` as `v1.2.0-thesis`
on 2026-10-26; that tag predates the unreleased fixes below.

### System-owned species selections (GEN-1; ADR-0002)

- Add immutable `lammpkeeper.core.SpeciesMap` for explicit labels, repeated-label
  unions and validated type-ID groups, independent of any force-field name.
  Existing mapping conversion helpers and canonical presets remain compatible;
  legacy species-selection helpers delegate to the generic model.
- Add explicit Masses-comment labels, lazy dump type-label consistency and
  optional schema-1 JSON manifest groups/provenance. Manifest loading is explicit;
  no prep output or automatic discovery is added.
- Resolve typed metadata from input, data comments and dump without renumbering
  sparse IDs. Contradictory explicit labels warn and reject application. Managed
  source/group changes invalidate cached results; unresolved manifest references
  remain pending and cannot produce an active species map. Only explicit numeric
  type evidence, not inferred/synthesized table keys, establishes group members.
- Preserve `set types` as an explicit warned manual analysis-label override,
  separately from automatic user fallback. Typed-source load/unload expires it
  visibly; manifest/log changes retain it and failed transactions roll back.
- Keep FF classification separate (GEN-2), preserve output keys/filenames and
  require existing Fe-O goldens to remain unchanged. No fixture or thesis tag
  modification, new force-field convention or LAMMPS/HPC validation is included.

### Documentation status cleanup (DOC-2)

- Distinguish current migration status from historical dispatcher, mapping and
  LAMMPS verification records; remove completed work from pending descriptions.
- Correct the four-space convention, document remaining warned metadata
  heuristics and clarify supported geometry/RDF semantics without claiming new
  physics or HPC validation. Update mapping and top-level CLI docstrings.
- Executable code, tests, fixtures, numeric goldens and accepted ADRs are unchanged.

### Serialized synthetic slab reference (TEST-3)

- Add a deterministic stdlib generator for a 16-atom, six-frame `pp pp ff` toy
  reference, generated in temporary directories rather than changing fixtures.
- Collected analytic checks cover x/y boundary pairs, nonperiodic z, ID-tracked
  MSD, RDF normalization, absorption/penetration counts and initial-cohort uptake.
- Exercise serialized readers, native/NumPy access paths, real SciPy RDF versus
  fallback, both shell load orders, cached/shared work and real CLI dispatch.
  Optional real PNG tests inspect curves and reject a false t50 annotation.
- The wall-jump probe is deliberately nonphysical, not a dynamics/chemistry or
  GEN-8 reference. Production code, mapping conventions and goldens are unchanged.

### Complete English source annotations (DOC-ALL)

- Add or clarify maintenance documentation in every tracked Python, Rust, Shell
  and TOML source/build file: 63 files, including tests and compatibility shims.
- Document all 58 Python modules and all 713 function/class definitions, including
  private/nested helpers; explain major logic, units, assumptions and failure paths.
- Preserve executable Python AST, Rust/Shell noncomment code and parsed TOML
  values. Generated templates, fixture snippets, mappings and goldens are unchanged.
- `docs/agent/COMMENT_COVERAGE.md` lists every file, coverage counts, scope and
  verification limits. Help/introspection docstrings intentionally become clearer;
  scientific algorithms, command semantics and output data do not change.

### Whole-code audit corrections (AUDIT-20261027)

- Input loading preserves canonical ACE analysis identities and invalidates
  dependent times, surfaces and cached results. Replacement/unload cannot retain
  another source's structure, performance, mass or box. Density, oxygen and
  charge analyses consistently honor explicit species unions.
- One-shot/batch failures return nonzero, batch quit stops execution, spaced paths
  load correctly, and noninteractive plots use explicit defaults without prompts.
  A requested plot without matplotlib fails instead of reporting empty success.
- RDF respects all PBC axes, removes the extra same-species division by two, and
  averages per-frame normalized curves rather than using the last frame's N/V.
  The separately approved RDF-only golden update is independently checked by
  full pair matrices; MSD goldens and fixtures remain unchanged.
- Penetration profiles align the union of atom IDs with explicit NaN gaps,
  retain population-changing/empty samples and honor the surface percentile.
- Prep refuses unsupported odd-width (110)/(111) slabs instead of dropping
  lateral tilt. Fixed/NVT layer counts must be positive; zero-layer operation
  is not supported by the current region templates.
- Geometry changes invalidate previous builds, including direct Python state
  changes. Failed or incomplete O₂ placement cannot become a writable build.
- Random O₂ bond axes now sample uniform solid angle. This intentionally changes
  seeded gas coordinates; seeds remain reproducible and all force fields still
  share identical starting coordinates. No committed fixture was regenerated.
- ACE CPU overrides use compatible explicit or automatic processor grids. The
  configured dense dump stage is clamped to the requested oxidation duration;
  remaining run steps cannot be negative.
- Failed-job archives require exclusive directory creation. Existing archives
  and destination symlinks are preserved; failed archival retains scratch.
  Copyback preserves the destination directory's access mode.
- Dump/data readers reject unsupported triclinic cells instead of dropping
  tilt. Trajectory boundary changes, malformed structures, lossy numeric IDs
  and changed indexed/cached sources fail visibly; native/NumPy paths preserve
  long labels. Lazy views inherit reader limits unless explicitly overridden.
- Log parsing retains source blocks and reset-step histories, continues through
  warnings, and separates MD from optimizer iterations. New block identity and
  elapsed-MD-step metadata avoid treating minimization counters as physical time.
  Thermo plots consume those reconstructed MD increments, reject optimizer-only
  time axes, and use explicit log units/timestep even with an unrelated dump.
  Conflicting explicit log/input metadata or unconfirmed log-only units fail
  visibly. Repeated step counters cannot supply ambiguous slab box heights.
  The old fixture test requiring optimizer rows was replaced with source-block
  checks and a separate genuine-MD merge test, with the physical reason recorded.
- Input metadata handles quoted/commented/nested includes, safe consumed-variable
  arithmetic, redefinitions and hybrid/NULL species mappings. Missing includes,
  unresolved consumed metadata and unsupported units raise rather than guessing.
  Dump-only force-field/unit/timestep guesses are now explicitly warned.
- Correct the built-in magnetite reference to 24 Fe/32 O with eight tetrahedral
  and sixteen octahedral Fe sites. CIFs without explicit symmetry operations
  must establish P1; unsupported symmetry interpretation raises visibly.
- Pressure plots convert real-unit atm and metal-unit bar correctly. Optional
  slab scaling uses explicit per-sample Lz/thickness and states its stress
  allocation assumptions; absent/inconsistent geometry is visibly uncorrected.
- Adsorption t50 requires half the initial oxygen cohort to cross the surface,
  not half the eventually crossed subset. ID-union profile gaps remain gaps.
  Spin-fraction legends explicitly identify their different denominators.
- The local verifier refuses empty test runs, absent requested plot output,
  missing prep artifacts and logged prep errors even when process exit is zero.

### Species-group selection (PHYS-4)

- Post-processing resolves explicit species labels to sets of atom types.
  The canonical ACE `Fe` selection includes both spin channels; `Fe_up` and
  `Fe_down` remain individually selectable. Existing type/element mapping tables
  and legacy conversion functions are unchanged.
- Unknown MSD species, unknown RDF pair members and malformed selection options
  now raise errors listing valid choices instead of silently analyzing all atoms
  or substituting default types. Failed target selections do not leave stale
  cached curves available for plotting.
- RDF accepts integer type IDs or type sets. Singleton selections preserve the
  existing numeric results; no golden values or fixtures are re-baselined.
- Human-readable labels distinguish all-spin from spin-resolved results while
  retaining the existing cache keys and output file names.

### Periodic O₂ detection and consistent pairing (PHYS-3, PHYS-5)

- O₂ candidate search and minimum-image distances honor explicit per-axis PBC.
  The shell passes dump/input boundary metadata; direct calls keep the legacy
  slab default `(True, True, False)`. Candidate search reuses the periodic RDF
  helper; existing RDF callers and numeric goldens retain their behavior.
- Both accelerated and fallback O₂ paths use global shortest-first greedy
  pairing, with deterministic ID/coordinate tie-breaking. Adding distant atoms
  or changing backend no longer changes how a local group is paired. This is
  a distance-cutoff heuristic, not maximum matching or chemical bond order.
- The atom-type selector accepts an integer or a set of types. Invalid supplied
  bounds, PBC, cutoff, selected positions or selected IDs fail visibly; parsed
  triclinic geometry remains an existing separate limitation (GEN-3).
- Frames with no selected atoms now retain their time point with zero counts
  and zero fractions instead of silently disappearing. Output keys and file
  names are unchanged, and failed recomputation invalidates its target cache.

### MSD atom identity and bulk regression (PHYS-2, PHYS-1)

- MSD selects an initial cohort by atom type (an integer, a set of type IDs, or
  all initial atoms), then follows those atom IDs despite type changes and row
  reordering. Type changes no longer substitute atoms or silently drop frames.
- An absent `id` column, invalid/duplicate IDs or a missing tracked atom now
  raises a visible error. Skipping a missing sample can lose periodic crossings,
  so an apparently valid partial trajectory is not returned. Newly added atoms
  are reported and excluded from the fixed initial cohort. Failed recomputation
  invalidates the target MSD cache entry so an older curve is not plotted as
  the result of a failed attempt.
- The public `pbc` argument and slab default are unchanged; the shell already
  passes per-axis periodicity from dump/input metadata. Bulk fixture regressions
  now explicitly use the dump's `pp pp pp` flags rather than the slab default.
- Maintainer-approved golden rebaseline (2026-10-27): final Fe_up MSD changes
  from 17.4725703688831 to 0.074623992827988 Å² after removing false z-boundary
  jumps. O MSD and all other golden values are unchanged. Independent periodic
  image enumeration and analytic vibration/crossing tests support the correction.
  The final frame includes structural minimization, not equilibrium thermal
  motion. Time-axis inference and separation of MD/minimization remain separate
  issues; no fixtures or thesis-baseline tags were changed.

### HPC job-script safety (HPC-1)

- Generated PBS scripts check scratch creation, input staging and directory
  changes before launching LAMMPS.
- `LKPR_SCRATCH` optionally selects an absolute scratch path (the existing
  `/hpctmp/$USER/$JOBID` default is unchanged). Scratch must be a fresh directory;
  an existing directory or symlink is refused without modifying its contents.
- Results (including hidden files) must copy successfully before scratch is
  removed. Copy/archive failures report the retained scratch path and return a
  nonzero exit status rather than printing success.
- A failed LAMMPS run still returns its original failure status after a successful
  archive. LAMMPS inputs, structures and site configuration are unchanged.

### Dump boundary metadata verification (PARSE-1)

- Regression tests cover slab, fully periodic, mixed nonperiodic and absent
  boundary flags through streaming, indexed and cached readers. Boundary
  metadata remains on `DumpReader` / `LazyFrames.reader`; frame keys and analysis
  behavior are unchanged.
- Native/NumPy parity checks require successful native atom-block calls, rather
  than silently accepting the NumPy fallback as native coverage.

### Local/remote integration (PARSE-1, OPS-1, TEST-1)

- Dump readers expose `BOX BOUNDS` boundary flags. The post shell uses dump
  flags before input-script boundary settings and the surface heuristic when
  choosing MSD unwrap axes and RDF z periodicity. Fully periodic shell MSD
  results can therefore differ from the old slab-only unwrap behavior; atom-ID
  tracking and the approved golden rebaseline remain open (PHYS-1/2).
- Standalone shells clear shared readline history before loading their own
  file, alongside the 2,000-line limit and `LKPR_NO_HISTORY=1` support.
- The dependency-free runner includes both periodicity and remote history/skip
  tests; periodicity tests report missing NumPy as a skip.

### Stage 1 — unified entry point

#### Added

- `lkpr` top-level CLI (`lammpkeeper/cli.py`, `lammpkeeper/__main__.py`):
  `lkpr prep ...` and `lkpr post ...` forward arguments verbatim to the
  existing `lammps_pre` / `lammps_post` CLIs. `lkpr -h` and
  `lkpr --version` are owned by the top-level parser; subcommand flags,
  help text and exit behaviour are unchanged.
- Packaging in `pyproject.toml`: console script `lkpr`, extras
  `[prep]` / `[post]` / `[all]` / `[dev]`.

#### Changed

- `lammps_pre.cli.main` and `lammps_post.cli.main` accept an optional
  `argv` argument (default `None`, i.e. `sys.argv` as before).

### Stage 2 — shared modules, deterministic types, regression suite

#### Added

- Regression suite under `tests/` (`tests/run.py`, pytest-compatible):
  mapping, display, CLI dispatch, fair-comparison and numeric golden
  tests on the ACE reference fixture.
- End-to-end verification record against a real LAMMPS run
  (prep → LAMMPS → post) in `MIGRATION.md`.

#### Changed

- Display helpers deduplicated into `lammpkeeper/common/display.py`;
  `lammps_pre.display` and `lammps_post.display` are re-export shims
  (same objects, byte-identical rendering).
- Type ↔ element ↔ label convention deduplicated into
  `lammpkeeper/common/mapping.py` (Stage 2 Step B).
- Deterministic ACE type resolution (Stage 2 Step C):
  - prep writes the element convention into trajectories
    (`dump_modify ... element Fe Mn O`), so post no longer reverse-maps
    ACE types from atom counts for the 3-type case;
  - post `atom_types` are type-keyed in every detection rule;
  - element-only dumps are numbered by the canonical element→type map,
    not alphabetically.
- prep places the O₂ wall at a shared (force-field-independent) cutoff,
  so ReaxFF and ACE builds start from identical coordinates.

#### Fixed

- ACE reverse-map heuristic could relabel Fe_up as O under spin
  imbalance (O is the majority species in Fe₃O₄); replaced by the fixed
  ACE type order (heuristic retained only for 4+ types).

### Post-processing performance and memory (parser-streaming)

#### Added

- Streaming dump reader (`DumpReader`, `LazyFrames`): frames are parsed
  from disk on access with a bounded cache; `analyze all` shares one
  read across all analyses when the trajectory does not fit the cache.
- Optional Rust (PyO3) atom-block parser under `native/`
  (`native/build.sh`); identical results to the NumPy `loadtxt` path,
  which remains the fallback and reference. Disable with
  `LKPR_NO_NATIVE=1`.
- `load dump` options `--cache-mb N` and `--all-columns`; unified
  interactive session (`lkpr` / `lkpr shell`) to enter and switch
  between prep and post without losing state.

#### Changed

- `load dump` keeps only the columns analyses read
  (`id type element x y z q`, float64) by default; `--all-columns`
  keeps the rest. The parsed-frame cache defaults to 128 MB and is
  all-or-nothing (larger trajectories stream).
- RDF candidate pairs use a periodic KD-tree; binned histograms are
  identical to the previous brute-force path.
- First-load output-directory prompt defaults to `./lammps-post_output`
  in the working directory instead of next to the data file.
- Single version source: `lammpkeeper.VERSION` (1.2.0), read by
  `lammps_pre`, `lammps_post` and `pyproject.toml`.
- Oxidation-analysis thresholds named in `lammps_post`
  (`Q_OXIDIZED_E`, `SURFACE_OFFSET_A`, `NEAR_SURFACE_A`,
  `O2_BOND_CUTOFF_A`); values unchanged.
- Terminal boxes (banners, panels, tables) measure visible width
  (ANSI codes = 0, wide CJK = 2), so right borders align.
- Indentation unified to 4 spaces (whitespace only).

#### Fixed

- Removed unused imports in the post shell, plotting and prep
  builders/writers.

## [1.2.0] — unreleased baseline

The pre-unification `lammps-post` version number, adopted as the single
project version. No tagged release exists yet; REL-0 will create the
first tag (`docs/reproducibility.md`).
