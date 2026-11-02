# Changelog

All notable changes to LammpKeeper (`lkpr`) are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Changes since the last tagged state, grouped by migration stage
(see `MIGRATION.md`). No version has been released from this section yet;
REL-0 tagged the historical thesis baseline `cdf5c38` as `v1.2.0-thesis`
on 2026-10-26; that tag predates the unreleased fixes below.

### Wrapped positions are half-open and idempotent (REV-GEOM-1)

- `lammpkeeper.core.geometry.wrap_positions` never returns a point on the
  upper periodic face, and wrapping its result again changes nothing (before:
  -1e-17 became 1.0, then 0.0). Already-wrapped points keep their exact values.
  Tilted cells allow a small documented rounding tolerance when the result is
  converted back to fractions.

### Prep reads Masses in conventional data files (REV-PREP-4)

- The prep data-file inspector now reads a `Masses` section followed by a
  blank line, as LAMMPS and prep's own writer lay it out. Before, it reported
  no masses for such files. Generated structures are unchanged.

### Plot redo/edit accept the plot names users type (REV-UI-2)

- `plot redo charge` (and `spin`, `oar`, `penetration`, `dissociation`,
  `charge_z`) now finds the recipe saved by `plot charge`; the stored key
  names (`charge_evolution`, …) keep working and saved defaults stay readable.

### Far-unwrapped RDF coordinates are exact or rejected (REV-ANALYSIS-6)

- `compute_rdf` rejects periodic coordinates more than 2^45 box lengths from
  the box origin, on both pair backends alike. Below that, the SciPy path now
  finds every pair the fallback path counts; before, far-unwrapped coordinates
  could lose pairs on the SciPy path only. Ordinary results are unchanged.

### pair_coeff species maps use exact style names (REV-IO-9)

- In hybrid inputs, only sub-styles with an exact LAMMPS name from the
  ADR-0005 table (pace, pace/kk, reaxff, reax/c, hdnnp, ...) provide a species
  map. Names that only contain such a word (`ace`, `n2p2`, `mypace`) no
  longer do. Real LAMMPS inputs and prep inputs map as before.

### Thermo steps beyond 2^53 are rejected (REV-IO-5)

- `parse_log` rejects a thermo Step that is not a whole number below 2^53 in
  absolute value. Larger counters cannot be stored exactly as float64:
  2^53 and 2^53+1 used to become the same value with zero elapsed steps and
  no warning. Ordinary logs are unchanged.

### Short or long dump rows are rejected (REV-IO-3)

- Every atom row must have exactly the header's number of columns, on the
  native and NumPy readers alike, even when only some columns are requested.
  Before, a short row could pass when only its first columns were read.

### Dump changes during reading are detected (REV-IO-2)

- A dump file that is appended to, truncated, replaced or deleted while it is
  being read now stops the read with an error, before any changed frame or new
  atom type is used. Before, an appended frame could add a new atom type
  silently. Unchanged files read exactly as before.

### CLI flag and display-setting failures are reported (REV-UI-4)

- `lammps_post --dpi/--theme/--save-format` with a bad value now exits 1 with
  a one-line error instead of a traceback; `--dpi 0` is rejected, not ignored.
- An explicit `--find` that finds nothing exits 1 (interactive `find` is
  unchanged).
- `--batch` together with `--analyze` or `--plot` is now a usage error
  (exit 2); before, the batch script was silently skipped.
- `set dpi|fontsize|linewidth|markersize|grid_alpha|figsize|z_focus` reject
  nonfinite, non-positive, out-of-range or reversed values without changing
  the session.

### Parser edge cases fail or work visibly (REV-IO-8)

- `parse_log` rejects a thermo header pair that maps to the same quantity
  (for example `Temp` with `c_temp_mobile`, or `Press` with `Pressure`) and
  names both columns; before, the last column silently replaced the first.
- Density profiles accept frames that carry only a typed cell, and warn when
  an explicit z range meets an empty trajectory.
- The indexed dump reader recognises a frame only at an exact `ITEM: TIMESTEP`
  line, as the streaming reader does.

### Menu history kept across inline commands (REV-OPS-1)

- `lkpr` menu: running an inline `prep <cmd>` or `post <cmd>` no longer
  replaces the menu's in-memory command history with the child shell's
  history (which `postloop` then saved into the menu history file). The menu
  buffer is snapshotted before the child is built and restored afterwards,
  also when the child raises.

### Empty and ragged tables (REV-UI-1)

- `print_table`: an empty `rows` list now renders the header (and rule on the
  plain path) instead of raising `TypeError` on the plain path. Rows whose
  length differs from the headers now raise `ValueError` before anything is
  printed, on both the Rich and plain paths; Rich used to pad them silently.
  All in-repo callers build rows matching their headers.

### Verifier fails when evidence cannot be retained (REV-VERIFY-3)

- `verify-lkpr` (`verify.sh`): failures to retain required evidence
  (`post-summary.txt` copy, `outputs.txt`, `doctor.txt`, final `summary.txt`)
  now record `FAIL evidence` and exit nonzero; a post step that leaves no
  `summary.txt` also fails. The exit status is decided from the in-memory
  results instead of re-reading `summary.txt`. Before, a denied evidence copy
  still exited 0.

### Verifier stops when temporary directories cannot be created (REV-VERIFY-1)

- `verify-lkpr` (`verify.sh`): if a temporary HOME or work directory cannot be
  created, the verifier now stops with `FAIL setup` and exit 2 before any work.
  Before, a failed `mktemp` left `HOME` empty and paths such as `$WORK/post.commands`
  resolved to `/`.

### Clearer execution diagnostics (REV-EXEC-3)

- `lammpkeeper exec`: when the log changes while a parse fails, the
  `input_changed` message now also names the original error; a failed run no
  longer reports a validated `unit_source`; above 64 warnings the last entry
  states how many were omitted instead of replacing a real warning.
- `lkpr run` reads a finished backend's output to the end (up to 2 s), so a
  large valid response is no longer cut off and misreported as invalid JSON.
  A stdout still held open by an escaped process fails with a message saying so.

### Failed exports and pressure plots fail the command (REV-UI-3)

- `export csv|latex` with no cached data, no pandas, no exportable columns, an
  unknown format or bad usage now fails the command, so `--batch` and one-shot
  runs exit 1. Nothing is created when an export fails.
- `export summary [filename]` follows its help text: no name writes
  `summary.txt` in the output directory, a name is used as given. Before, a
  name not ending in `.txt` was silently replaced by `summary.txt`.
- `plot pressure` on a log without Press or Pxx/Pyy/Pzz fails; `plot all`
  skips that plot with a notice.
- Follow-up: `export summary <path>` again creates the output directory on a
  fresh session, as before (a REV-UI-3 regression found by REV-VERIFY-3).

### Analysis parameters are validated (REV-ANALYSIS-8)

- Charge evolution, oxidation rate, OAR, penetration (summary, trend and
  profile), O2 detection, spin evolution, MSD and the charge-z profile now
  reject invalid parameters with a ValueError naming the parameter, before
  reading any frame: nonfinite or non-positive `dt_fs`, nonfinite surface
  heights or charge thresholds, reversed or nonfinite `z_range`, and
  non-positive or non-integer `z_bins`/`window`. Before, several of these
  returned zeros or NaN without an error. Valid results are unchanged.

### `lkpr run` cancels its job when it fails after start (REV-EXEC-2)

- An error inside `lkpr run` after the job had started (for example a failing
  `--events` write) was reported as a request that never started, while the
  job and its children kept running until the timeout. The job is now
  cancelled and cleaned up, its real state is reported, and the exit code is 1.

### RDF no longer overrides a dump's periodic z (REV-ANALYSIS-9)

- `compute_rdf(..., pbc=None)` applied the legacy `z_pbc=False` default even to
  frames whose Box declares periodic z (for example a `pp pp pp` dump), so
  direct API callers silently got slab geometry. It now raises and asks for an
  explicit `pbc=`. The shell already passed the dump's flags and is unchanged.
  ADR-0003 is amended accordingly.

### Reference checks cannot pass by omission (VERIFY-REF-2)

- `.claude/skills/verify/scripts/verify_refs.py` reports a missing reference
  file, a malformed or empty reference, an unknown or invalid tolerance entry,
  and a measured value the reference does not list as a named ERROR (exit 1).
  Before, a missing file silently disabled its check and an empty reference
  passed.

### RDF reports where its count is complete (REV-ANALYSIS-7)

- `compute_rdf` results gain `r_max` and `r_complete`. `r_complete` is half the
  shortest periodic lattice vector; beyond it the nearest-image count misses
  pairs and g(r) is too low (measured 15–38 % low in a 10 Å cube at 6 Å). A
  cutoff above it now warns; RDF plots shade that range and CSV/LaTeX exports
  add an `r_complete` header line. g values are unchanged.
- New `lammpkeeper.core.geometry.unique_image_radius(cell)`.

### Backend error codes cannot fake a cleanup failure (REV-EXEC-1)

- `lkpr run` reported a cleanup failure, and dropped the backend response,
  whenever the backend's own error code was `cleanup_failed`. Cleanup status
  now comes only from the supervisor's own cleanup step.

### Post loads prep-written inputs (REV-IO-7)

- `parse_input()` evaluates the LAMMPS math functions `round` (half up, as in
  LAMMPS), `floor`, `ceil`, `abs` and `ternary`, comparisons and `%` (C
  `fmod`) in equal-style variables, so `load input` / `--input` accepts prep's
  ACE and ReaxFF inputs. Formulas that Python and LAMMPS would read
  differently (`-a^b`, `a^b^c`, `a<b<c`) and LAMMPS special functions such as
  two-argument `min`/`max` raise with a reason instead of being guessed.

### Generated ACE input runs in LAMMPS again (REV-PREP-7)

- Since 2026-10-27 the ACE input clamped the dense oxidation stage with
  two-argument `min()`/`max()`, which LAMMPS rejects while reading the input,
  so generated ACE jobs aborted before MD. The clamp now uses `ternary()`, with
  the same step counts (checked in LAMMPS 22Jul2025). `-var OX_PS`/`DENSE_PS`
  overrides still recompute the stages. ReaxFF inputs are unchanged.

### Whole-code audit fixes (AUDIT-20261101)

- Thermo plots without a log-declared timestep now use a manual `set dt` before
  the input's timestep, like every other time axis. A log that declares its own
  timestep keeps it.
- `parse_input()` expands `${var}` in `units`, `atom_style` and `pair_style`;
  an unresolvable substitution raises. Before, `pair_style ${ff}` was recorded
  as an explicit `generic` force field.
- `lkpr-rs` reports `output_too_large` even when the backend exits in the poll
  in which it overflowed (it was reported as invalid output), stores nothing
  after the first dropped chunk, exits 1 with `output_write_failed` when `--json`
  output cannot be written, and `doctor` exits 130 after Ctrl-C.
- `/verify-lkpr` full mode records a named SKIP for plots when matplotlib is
  missing (they were omitted silently).
- `tests/test_rust_cli.py` finds the binary through cargo, so a custom
  `CARGO_TARGET_DIR` works.
- The `lkpr run` Ctrl-C test no longer fails when the test runner was started
  as a background job, which ignores SIGINT (REV-TEST-3).

### Session uses explicit run metadata (GEN-2b; ADR-0005)

- An explicit `pair_style` replaces the dump force-field guess. EAM, LJ, hybrid
  and unrecognized styles are `generic`: no Fe/O labels, no spin analysis, no
  force-field timestep default. The legacy `parse_input()['forcefield']` key now
  uses the same exact-token classifier (hybrid/EAM inputs report `generic`).
- When an input declares only part of `pair_style`/`units`/`timestep`, the
  timestep stays unresolved: time-dependent analyses fail with an actionable
  error and `set dt <fs>` resolves it. Time-independent analyses still run.
  Units the input does not declare are shown as unresolved (or guessed from a
  loaded dump), never silently assumed `metal`.
- `set dt` and `set forcefield` (now also `generic`) are manual overrides shown
  in `info`; they expire with a warning on input/data/dump load or unload and are
  cleared by `unload all`. `info` lists each metadata field as explicit, guessed
  or unresolved with its source.
- `lammps_post --input PATH` preloads a LAMMPS input before other files.
- `parse_input()` rejects contradictory repeated `pair_style` or `atom_style`.
  Log/input unit and timestep conflicts name both sources and values.
- Fe-O sessions from prep-style ACE/ReaxFF inputs and the committed fixture give
  identical metadata and analysis numbers to before; no golden changed.

### Explicit run metadata model (GEN-2a; ADR-0005)

- Add `lammpkeeper.io.RunMetadata`/`MetadataField`: pair style, force-field
  family, atom style, units, native timestep and femtosecond step, each marked
  explicit, guessed or unresolved with its source. `dt_fs` is derived only from
  explicit `metal`/`real` units plus an explicit timestep; no scale is invented.
- Add `lammps_post.parsers.classify_pair_style`: exact first-token matching
  against enumerated LAMMPS pair styles; hybrid and unknown styles are
  `generic`. `parse_input()` returns a new `metadata` key; existing keys keep
  their values (the shell switches to the new model in GEN-2b).
- `parse_input()` now raises when one input declares `timestep` more than once
  with different values (previously the last value silently won).

### Optional Rust CLI `lkpr-rs` (UI-1)

- Add `rust/lkpr-rs`, a separate binary that drives the Python backend through
  `python -m lammpkeeper exec --capabilities` (`doctor`) and `lkpr run`
  (`thermo-summary`). It prints a readable table or, with `--json`, the backend
  snapshot byte-for-byte. Python environment must be explicit (`--python` or
  `LKPR_PYTHON`). Ctrl-C is forwarded once as a cancellation (exit 130); an
  unresponsive backend is stopped and reported as `supervisor_unresponsive`,
  never as cancelled. The Python `lkpr` command and Python-only installs are
  unchanged; Rust is not required. Linux only, as tested.

### Stale cached results (REV-SESSION-3)

- `plot` and `export` no longer publish cached results after the loaded dump
  file was modified or deleted. The session cache is discarded and the command
  fails with a reload message, so batch and one-shot runs exit nonzero. An
  unchanged source costs one `os.stat`. Log/data-derived results are not
  covered by this check.

### Boundary flag validation (REV-IO-6)

- Invalid dump `BOX BOUNDS` flags (single letters, mixed `p` faces, unknown
  letters, wrong count) and invalid input-script `boundary` words now raise a
  `ValueError` naming the file and token. Previously `p p f` in a dump became
  fully nonperiodic and `pf` became nonperiodic without warning.
- Input `boundary` lines with fewer than three words, or with unresolved
  variables, are no longer silently ignored or stored verbatim; they raise.
  Valid single-letter input (`boundary p p f`) and flag-less old dumps are
  unchanged.

### Dump '#' tokens (REV-IO-4)

- The NumPy dump fallback no longer treats `#` in atom rows as a comment. A
  corrupted numeric token such as `3#CORRUPTED` now raises on every path instead
  of being read as `3`, and element labels containing `#` parse the same on the
  native and NumPy readers. Data, log and input file comments are unchanged.

### RDF float32 backend parity (REV-ANALYSIS-4)

- `compute_rdf` evaluates selected positions in float64 at their represented
  values, so the SciPy candidate path and the row-wise fallback agree at the
  cutoff edge for float32 input. Previously the fallback could count a pair
  beyond `r_max`. Float64 results are unchanged (byte-identical).

### Spin analysis species guard (REV-SESSION-2)

- `analyze spin` (and `plot spin` through its cache path) fails with an error
  naming the active and canonical selections when the active Fe_up/Fe_down
  differ from the canonical ACE type channels (Fe_up = type 1, Fe_down = type 2),
  for example after `set types 1=Fe_down 2=Fe_up`. Previously it counted fixed
  type channels under the overridden labels. `analyze all` skips spin with a
  visible notice in that case. Canonical results are unchanged.

### Physical shell settings validation (REV-SESSION-1)

- `set surface_z` rejects NaN/Inf; `set dt` and `set mass` reject NaN/Inf and
  values ≤ 0. A rejected value keeps the previous setting and cached results,
  counts as a command failure, and makes batch and one-shot runs exit nonzero.
  Previously `set surface_z nan` or `set dt -1` produced successful OAR/MSD
  results with meaningless planes or time axes.

### Nonfinite selected coordinates (REV-ANALYSIS-5)

- OAR, penetration summary/trend, density profiles, charge-z profiles and
  z-restricted charge evolution/OR raise `ValueError` naming the analysis,
  timestep and count when a selected atom has NaN/Inf z. Previously such atoms
  were silently counted as unabsorbed, outside the range or dropped. Unrelated
  species, empty selections and finite results are unchanged.

### Density option validation (REV-ANALYSIS-3)

- `compute_density_profile` raises `ValueError` for equal, reversed or nonfinite
  `z_range` endpoints and for non-integer, boolean, zero, negative or nonfinite
  `n_bins`, before reading frames. Previously it could return NaN/inf densities
  with NumPy warnings. An empty trajectory with no `z_range` now raises
  `ValueError` instead of `TypeError`. Valid profiles are unchanged.

### Reference-value verification and RDF frame window (VERIFY-REF-1, RDF-PROV-1)

- Add `.claude/skills/verify`: real-code reference checks with per-key kinds
  (`analytic`, `external`, `fixture`, `snapshot`) and stated tolerances. Snapshot
  passes are regression checks against `a974563`, not correctness proofs.
- `compute_rdf` also returns `frame_window` (first/last step, frame count,
  `last`/`all` selection); `describe_frame_window()` renders it. g(r) and the
  default last-20-frame average are unchanged.
- RDF plot legends name the averaged steps. RDF `export csv`/`latex`/`summary`
  record the window; CSV/LaTeX gain one leading comment line (`#`/`%`) and are
  written as UTF-8. CSV readers must skip `#` comments.
- The slow RDF golden test hashes only numeric fields; its stored fingerprint is
  unchanged (not a re-baseline).

### Load-tolerant job timeout test (REV-TEST-2)

- The overall-timeout lifecycle test no longer assumes two Python startups fit in
  0.3 s. Budgets leave over a second for startup, a missing phase sentinel reports
  the budget instead of `FileNotFoundError`, and the execution case now also
  rejects a per-phase deadline. Test-only; `lammpkeeper/jobs.py` is unchanged.

### Portable agent workflow (AGENT-1)

- Add a canonical LammpKeeper Skill for capability discovery, explicit Python
  selection, structured thermo summaries and retained execution/cleanup evidence.
- Link Claude project discovery to the same instructions; document Codex and
  OpenCode setup with measured host checks distinguished from untested support.
- Add three paired evaluation cases for native units, unresolved units and
  malformed input; retain graders and development evidence.

### Process-owned local execution (EXEC-2)

- Add a local Python supervisor and additive `lkpr run` entry point for explicit
  environment selection, capability handshake, state events and bounded
  timeout/cancellation cleanup. Reuse the existing structured scientific backend.
- Preserve interpreter symlinks and reject incompatible backends without silently
  switching environments. Local status belongs to the owning Python process;
  this is not a persistent daemon or remote scheduler.
- Record the native-only skip audit and the maintainer's standing requirement
  for English intent comments, execution diagnostics and development logs.

### Structured thermo-summary execution (EXEC-1)

- Add a shared Python application operation for existing thermo-summary
  statistics, reused by `show thermo` and an additive `lkpr exec` JSON interface.
- Provide versioned capability discovery and bounded strict-JSON requests with
  explicit outcomes, diagnostics, native-unit metadata and source provenance.
- Reject invalid summary data and ambiguous supported headers rather than
  publishing nonfinite or overwritten statistics. Parsed Step precision remains
  bounded; this does not resolve general source-token precision in REV-IO-5.
- Record ADR-0004 acceptance and the first vertical slice of the Python/Rust/
  agent roadmap. Job lifecycle, Rust frontends, skills and MCP remain separate
  implementation stages.

### Selected charge integrity (REV-ANALYSIS-1)

- Charge evolution, charge profiles and oxidation fractions reject selected
  NaN/Inf charges with a diagnostic instead of publishing invalid statistics
  or silently treating bad charges as unoxidized atoms.
- Validate only charges contributing to the requested species/region/profile;
  preserve unrelated species, count-only oxygen, empty selections and finite
  results. Unrestricted evolution/OR still need no spatial columns or box.
- A failed shell retry clears only the attempted charge result, and one-shot
  CLI analyses return failure for invalid selected charge input.

### Explicit charge-region integrity (REV-ANALYSIS-2)

- Charge evolution and oxidation fraction reject an explicit `z_range` without
  a `z` column before iterating frames, checking geometry or returning for
  absent charge data. A requested region no longer silently becomes global.
- Unrestricted scalar calculations still need neither z nor a box; valid
  inclusive regions, type unions, threshold comparisons and empty selections
  retain their previous results.

### Job result copyback safety (REV-PREP-1)

- Preflight every matching result path before any `cp -a` copyback; refuse
  colliding destination symlinks, including hidden/nested and dangling links,
  without removing links or writing their targets through copyback.
- Reject the named destination-root symlink even with trailing `/` or `/.`;
  preserve source symlinks as artifacts, normal overwrites/merges, destination
  root modes and exclusive failure archives. Failure keeps complete scratch,
  reports the unsafe path and preserves a nonzero solver status.
- This is copyback-only protection on trusted, stable path ancestors, not atomic
  copying, a sandbox or protection against races, hardlinks/mount aliases, or the
  existing earlier `run.log` logging symlink hazard. No actual HPC run is implied.

### CIF site occupancy integrity (REV-REF-1)

- Reject explicit non-unit/unknown/invalid CIF occupancy and unsupported coded
  disorder before site filtering or symmetry expansion. Use exact decimal
  nominal-one checks, not float rounding or tolerance; no partial-site weighting,
  uncertainty propagation or disorder-alternative selection is added.
- Guard mixed-case/reordered site headers, duplicate or ambiguous declarations,
  scalar/orphan constraints, malformed guarded row shapes and quoted/commented
  fields. Guarded labels beginning with `loop` cannot silently bypass validation.
- Preserve absent-occupancy unit-site compatibility, unweighted return schema,
  ordinary full-occupancy CIFs, built-in reference calculations and existing
  goldens. Disorder fields support only the unquoted not-applicable `.` marker;
  other codes are unsupported, not declared physically invalid. Other CIF/reference
  geometry, symmetry and shell-completeness findings remain separate.

### Thermo row integrity (REV-IO-1)

- Reject malformed numeric-leading records in any active Step-headed thermo
  table instead of silently dropping short/long rows or ending a table on a
  nonnumeric data cell. Errors identify source path, one-based line, active
  header/expected width and offending row; no partial history is returned.
- Check records before stage/terminator keyword matching and before excluding
  minimization/incompatible blocks. Failed shell/CLI loads preserve prior state
  and surface failure. Valid logs, result keys, metadata/timelines and Fe-O
  goldens are unchanged; this is bounded format validation, not finite-value or
  physical validation and not a repair of other review findings.

### Whole-source re-review and annotation refresh (REVIEW-20261028)

- Re-review all 78 Python/Rust/Shell/TOML source/build files after GEN-3;
  preserve English documentation for all 73 Python modules and 978 definitions.
  Strengthen annotations in 56 files and retain adequate documentation in 22.
- Clarify units/PBC, provenance/transactions, cache/reader lifetime, supported
  formats, reference/plot interpretation, seed ownership and test-oracle limits.
  Executable AST/noncomment code, settings, generated strings, fixtures, mappings
  and goldens are unchanged; this is not a runtime bug-fix or physics certification.
- Record pre-existing reproduced defects and separate follow-ups, notably silent
  thermo-row loss, unsupported CIF occupancy and destination-symlink copyback.
  See `docs/agent/REVIEW-20261028.md` and the open backlog; regression passes do
  not imply these newly identified gaps have been fixed.

### Restricted-triclinic geometry (GEN-3; ADR-0003)

- Add immutable `lammpkeeper.io.Box` with physical bounds, restricted tilts and
  explicit/unresolved lattice-vector PBC; add NumPy coordinate transforms,
  wrapping, exact nearest images and constant-cell step unwrapping in core.
- Add opt-in `box_model=True` dump reading and structured `read_data_file` while
  preserving legacy reader defaults and data tuples. Indexed cells retain their
  source/header contract; foreign/stale/incompatible indices reject before parsing.
- Support restricted-triclinic Cartesian RDF and constant-origin/matrix/PBC MSD.
  Closest-image selection uses complete bounded QR search, protected objective
  comparisons and exact-rational fallback, not component-wise fractional rounding.
  Unsupported conditioning, numeric scales or search work raise visibly.
- Route post sessions through typed cells, preserve PBC ownership across input
  changes/cache eviction and reject unsupported tilted slab/O₂/plot consumers.
  Geometry-independent charge/spin quantities remain separate. General rotated
  cells, scaled/unwrapped conversion, image reconstruction and deforming-cell
  triclinic MSD remain unsupported.
- Preserve orthogonal Fe-O goldens and the legacy RDF `z_pbc` override when no
  three-axis mask is given. No fixture, prep output, FF mapping or thesis tag
  change; synthetic checks do not constitute LAMMPS/HPC or material validation.
  Additive APIs require no legacy API removal or deprecation.

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
