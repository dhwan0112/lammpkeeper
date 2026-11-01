# ADR-0005: Explicit run metadata and conservative force-field classification

- **Status:** accepted (2026-11-01, maintainer approved in session; PR #47)
- **Date:** 2026-10-28
- **Deciders:** 김동환 (maintainer)
- **Backlog:** GEN-2
- **Baseline:** drafted on `b9bd503` (PR #24); refreshed on `f752337` (PR #46), 2026-11-01

## Context

ADR-0001 accepts a strangler migration and explicit metadata before heuristics.
ADR-0002 separates system-owned species from force-field presets; ADR-0003 owns
box/PBC geometry. GEN-2 must preserve those boundaries while removing shape-based
force-field classification when explicit LAMMPS evidence exists.

The old GEN-2 backlog mentions a run manifest as a physics-metadata source.
This conflicts with ADR-0001's accepted answer: units, atom_style, pair_style,
pair_coeff, timestep and boundary stay in LAMMPS files. The proposal follows
ADR-0001 rather than expanding the optional manifest schema.

Source inspection of `lammps_post/cli.py` shows existing preload flags for dump,
log and data, but none for input scripts. A usable explicit metadata path must
work in both interactive and one-shot workflows. Existing shell/session paths
and their compatibility adapters need transactional integration, not merely a
different guessed force-field label.

Baseline full verification measured **444/0/0** on merged main. That proves only
the existing collected checks, not generic FF classification or reduced-unit
analysis correctness.

### Changes on main since drafting (refresh 2026-11-01)

The proposal text below is unchanged except where noted here. Relevant merged work:

- REV-SESSION-1 (#39) already validates `set dt` (finite, > 0) and `set surface_z`
  before state changes. The manual-override section below builds on that; it no
  longer needs to add the numeric check, only the separate override record,
  provenance and lifetime.
- REV-SESSION-2 (#40) gates spin analysis on canonical ACE type channels and
  skips it visibly in `analyze all` otherwise. A `generic` force field from this
  ADR makes spin not applicable, consistent with that guard.
- REV-IO-6 (#43) validates input `boundary` words and dump boundary flags. PBC
  stays owned by ADR-0003; this ADR does not change that.
- EXEC-1/EXEC-2/UI-1 (#29, #30, #46) expose only `thermo.summary`, whose units
  come from the log (`unit_source` in provenance). When a later operation exposes
  trajectory analyses, it must report the resolved metadata and whether each field
  is explicit, guessed or unresolved, from the model proposed here. No change to
  the existing `thermo.summary` v1 contract is proposed.
- Total collected checks on main after #46: native **589/0/0**.

## Options

1. **Do nothing:** retain warned shape heuristics. Lowest immediate migration
   risk, but explicit EAM/LJ runs can still inherit unrelated domain assumptions;
   does not satisfy GEN-2.
2. **Recommended: immutable explicit metadata with compatibility adapters.**
   Introduce a small provenance-bearing model and conservative classifier, route
   managed source changes through it, then adapt into legacy `ff_info`. Preserve
   supported Fe-O numbers while exposing unresolved facts and generic pair styles.
   Costs new contract and lifecycle tests; avoids a simultaneous domain extraction.
3. **Full registry/domain/units overhaul now:** migrate prep defaults and all
   analyses along with classification. Higher coupling and reproducibility risk;
   combines GEN-2/4/7/9 and generated-input gates. Defer.

## Decision (accepted 2026-11-01)

### Ownership and additive layout

- Add `lammpkeeper/io/metadata.py` for an immutable `RunMetadata` value object
  and explicit metadata resolution. It stores optional pair-style text, atom
  style, units, timestep in native time units, and per-field source provenance.
  Unknown is explicit (`None`), not a fabricated physical value. Retain original
  source values alongside normalized values needed for comparisons.
- Keep the bounded pair-style classifier in the existing input parser for this
  step; defer the complete `forcefields/` registry to a separately scoped change.
  Classify without assigning atom labels, masses, species groups, slab geometry
  or site defaults. Domain-specific compatibility mappings stay in the existing
  approved mapping adapter. This minimizes layout changes while adding only the
  generic provenance/resolution model under `io`.
- Do not move legacy parser functions or generic numeric kernels in this item.
  Keep public imports and existing returned dictionary keys usable through an
  adapter; add provenance/status fields rather than remove keys.
- PBC/box and species remain owned by their existing accepted models. The new
  object must not independently override either of those authorities.

### Evidence and classification

- Use parsed LAMMPS input commands as trajectory metadata, and keep supported
  explicit log declarations in a separate log-owned record. Merely loading a log
  does not prove it belongs to the trajectory and cannot change its FF/time.
  A data-file
  style hint may supply atom_style only when unambiguous; a charge column or
  number of atom types is not explicit pair-style evidence.
- Resolve fields independently within each source context. Reject contradictory
  declarations within a trajectory's selected input before application. Independent
  log and trajectory sources may coexist: a consumer combining log and input
  metadata must reject explicit disagreements with source/value diagnostics, in
  either load order. Never silently choose the last loaded file. Missing evidence
  is not a contradiction. This preserves log-owned thermo semantics.
- An explicit pair style always disables shape-based FF classification, including
  an unknown, hybrid or unsupported style. Preserve its raw identity and classify
  it as `generic` unless a recognized family is unambiguous. EAM and LJ may use
  descriptive families or `generic`, but never ACE/ReaxFF/HDNNP from atom columns.
- Preserve existing recognized Fe-O aliases in the compatibility layer. A generic
  family gets no Fe/O labels, spin interpretation, oxygen presets or FF-specific
  dt defaults. Explicit species and numeric type IDs remain system-owned.
- Match the first pair-style token against explicit supported names/aliases,
  never arbitrary substrings. Initially recognize `pace`/`ace`, `reaxff`/`reax/c`,
  and `hdnnp`/`n2p2`; supported accelerator suffix aliases must be enumerated and
  tested. Hybrid styles remain generic in this bounded step. Do not interpret
  a potential filename or arbitrary token containing `ace` as proof of ACE.
- Observed capabilities such as charge and velocity columns remain independent
  of FF classification. A `q` column does not prove ReaxFF, and selecting a
  ReaxFF family does not prove charge data is present.
- If pair-style evidence is wholly absent, retain the existing warned heuristic
  for legacy compatibility, explicitly marking guessed fields/provenance. A
  heuristic must not replace explicit units or a declared timestep.
- Do not execute LAMMPS expressions, shell commands or arbitrary includes as part
  of metadata evaluation. Unsupported unresolved/changing declarations must be
  visible and must not become an invented single constant for analysis.

### Units and time

- Support the existing physical unit styles `metal` and `real` with explicit
  conversion to `dt_fs` only when units and timestep are established. Validate
  timestep as finite and positive; do not round an unsupported value into validity.
- Do not invent an LJ time-to-femtosecond scale or relabel reduced units as Å/fs.
  Recognize the explicit pair style before reporting unsupported `units lj` for
  physical-unit consumers. A clear units rejection satisfies the safety contract;
  generic reduced-unit RDF/MSD support is outside this proposal.
- Missing explicit timestep in a generic run remains unresolved. Consumers that
  require physical time must fail with actionable metadata requirements; loading
  metadata must not silently supply an ACE/ReaxFF dt. Existing warned legacy
  dump-only compatibility is tested separately from explicit generic handling.
- The same unresolved-time rule applies to recognized explicit FF families:
  an explicit pair style without a timestep cannot activate a family dt default.
  Guessed units must never convert an explicit native timestep into confirmed fs.
  Limit legacy inferred time to the compatibility path with no explicit pair-style,
  units or timestep declarations. Any partial explicit time metadata outside that
  path stays unresolved until both units and timestep are established, or a valid
  separately labelled manual fs override is supplied in a supported unit context.
- Variable timestep / multiple run segments are not represented as one guessed
  `dt_fs`. Reuse established log timeline handling where supported; otherwise
  reject affected time-based analysis visibly rather than claim time support.
  For input metadata, differing repeated timestep values or unresolved timestep
  expressions reject application with a source diagnostic in this bounded step;
  equal repeated finite values are allowed. Never treat the last declaration as
  a trajectory-wide interval without evidence.

### Session and public interface

- Route source load, replacement and unload through a candidate resolution step.
  Validate before publishing metadata, species, box or new results. A rejected
  candidate retains the previously usable session and diagnoses the conflict.
- Recompute derived effective metadata from remaining sources on unload; never
  keep a stale explicit classification from an absent file. Managed effective
  metadata changes invalidate dependent cached numeric results and plots.
- Preserve ADR-0002's manual type-override expiration and transactional behavior;
  FF classification alone cannot reinterpret the same numeric atom types.
- Preserve `set dt` and `set forcefield` as explicit temporary user overrides,
  stored separately from raw source facts and shown as manual in status output.
  `set dt` accepts only finite positive fs in supported physical-unit contexts;
  it cannot establish an LJ conversion. Add `generic` to the existing FF choices.
  Warn on an override differing from resolved evidence; do not use overrides to
  reconcile contradictory raw files. Successful input/data/dump load, replacement
  or unload expires these overrides visibly, while log/manifest-only changes
  retain them; failed transactions restore them and `unload all` clears them.
  This lifetime is a proposed behavioral clarification requiring approval and
  a CHANGELOG entry, not an implicit side effect of dictionary overlays.
- Add an optional `--input PATH` preload flag using the existing input-load path,
  before trajectory analyses. No flag removal/rename. Include CLI help and a
  CHANGELOG entry. Existing input loading/batch workflows remain valid.
- Report explicit versus guessed versus unresolved fields and their sources in
  metadata/status output. Never advertise unsupported unit conversions as ready.

## Consequences and implementation order

1. After approval, add model/classifier and independent synthetic tests without
   routing existing callers yet. Test made-up labels, sparse types and explicit
   EAM/LJ styles with adversarial charge columns/type counts.
2. Adapt parsed fields into the model; retain old parser imports and schema.
   Test partial metadata, aliases, unknown/hybrid styles, unresolved values,
   conflicts and unsupported units. No source file rewrites.
3. Integrate session resolution/cache lifecycle and CLI input preload. Test input/
   dump/log load-order permutations, replacement, unload and rollback, including
   absent timestep and explicit generic metadata defeating domain guesses.
4. Prove supported Fe-O outputs unchanged using existing goldens and collected
   reference tests. Do not rebaseline expected values. Distinguish legacy guessed
   compatibility from explicitly sourced metadata in test labels and diagnostics.
5. Full isolated-HOME native/NumPy/default verification with named optional skips;
   document failures and unsupported cases, then normal feature PR shipping.

No public API removal or compatibility-shim deletion is proposed. No generated
prep/job inputs, structures, fixtures, mappings, physics goldens, HPC/site changes
or thesis tag changes are authorized by acceptance of this ADR.

## Approval requested

Approve the additive metadata module and bounded in-place classifier, explicit-field conflict and
rollback policy, conservative generic/no-domain-default behavior, bounded
metal/real time conversion with visible LJ limitations, separate log provenance,
manual override lifetimes and additive `--input`.
Accepted by the maintainer on 2026-11-01 with the decisions as written.
