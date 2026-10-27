# Changelog

All notable changes to LammpKeeper (`lkpr`) are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Changes since the last tagged state, grouped by migration stage
(see `MIGRATION.md`). No version has been released from this section yet;
REL-0 tagged the historical thesis baseline `cdf5c38` as `v1.2.0-thesis`
on 2026-10-26; that tag predates the unreleased fixes below.

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
