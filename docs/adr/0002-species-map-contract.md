# ADR-0002: SpeciesMap contract and explicit species metadata

- **Status:** accepted (2026-10-28; maintainer approved the recommended contract)
- **Date:** 2026-10-28
- **Deciders:** 김동환 (maintainer). Agents may draft; only the maintainer accepts.
- **Backlog:** GEN-1
- **Baseline:** main `3f28be9b7a73bfdebf6628d1ea5340704ffa7a91`

## Context

Source inspection establishes the following facts; runtime behavior has not been
newly measured for this proposal:

- ADR-0001 accepts a generic `core.SpeciesMap`, incremental migration, optional
  JSON manifests and preservation of Fe-O regression results. It does not fix a
  concrete class API or species-conflict continuation policy.
- ADR-0001's metadata order is manifest → input → data `Masses` comments → dump
  columns → user. GEN-1's backlog instead puts input after data and dump. This
  discrepancy must be reconciled explicitly, not resolved incidentally in code.
- `lammpkeeper/common/mapping.py` already validates repeated labels, named groups,
  canonical preset aliases and unknown selections. Existing PHYS-4 consumers use
  these helpers; there is no generic `lammpkeeper/core/` package yet.
- `SessionState.atom_types` exposes mutable `ff_info['atom_types']`. Shell metadata
  updates clear cached analyses and recompute only automatic surfaces. A map
  cached once at construction would become stale.
- `parse_input` exposes explicit `element_map` assignments, including supported
  hybrid/NULL mappings. `parse_data_file` returns a three-tuple and discards
  `Masses` comments. Dump elements are separate from numeric atom columns.
- FF/units/timestep inference remains GEN-2; moving domain analyses remains GEN-4.
  Neither is a prerequisite for replacing species-selection storage/resolution.

Evidence paths: `docs/adr/0001-general-purpose-architecture.md` (configuration
answer), `docs/agent/BACKLOG.md` (GEN-1), `lammpkeeper/common/mapping.py`,
`lammps_post/state.py`, `lammps_post/shell.py::_apply_input_config`,
`lammps_post/parsers.py::{parse_data_file,parse_input,detect_forcefield}`,
`tests/test_species_selection.py` and `tests/test_audit_workflow.py`.

The project `/architect` command is unavailable in this harness. Two independent
read-only reviews inspected API compatibility and metadata extraction separately;
this proposal records the manual architecture review, not a claimed command run.

## Options

### A. Keep the current FF-owned helper implementation

Lowest migration risk and no new API, but GEN-1 remains open. Generic explicit
labels work in some callers; species identity still lacks a system-owned model.
No change to Fe-O results or backwards compatibility; no architectural progress.

### B. Add the generic model with compatibility adapters (recommended)

Introduce the accepted core boundary, retain presets outside it, and migrate
existing selection helpers/callers through immutable snapshots. Explicit source
adapters preserve type IDs and report provenance/conflicts. Preserve current
Fe-O preset behavior, legacy imports and numerical schemas.

Follow ADR-0001's order, reconcile the contradictory backlog on approval, and
reject contradictory explicit species assignments after visible diagnostics.
This is stricter than warning-and-continuing, a policy ADR-0001 did not specify.

### C. Follow the backlog's data/dump-before-input order

Same generic model but a different authority order. It requires an approved
amendment to ADR-0001 and can change selections for existing input+dump sessions.
No demonstrated physical reason currently favors reversing the accepted order.
Tests/goldens would still have to remain unchanged for compatible Fe-O sources.

For either B or C, warning-and-continuing on conflicting species is an alternative
that needs explicit approval. It is not the recommended default for research
numbers: a valid-looking curve may then describe the wrong species.

## Decision

Adopt **B**. The maintainer approved the recommended API, authority order,
conflict rejection and optional manifest contract on 2026-10-28.

### 1. Generic public API and module boundary

```python
from lammpkeeper.core import SpeciesMap

SpeciesMap(label_types)
SpeciesMap.from_atom_types(atom_types, *, groups=None)
species.resolve(name)       # frozenset[int]
species.type_sets()         # fresh dict[str, frozenset[int]]

# No force-field name or chemical inference:
species = SpeciesMap.from_atom_types({2: 'A', 7: 'A', 9: 'B'},
                                     groups={'X': [2, 9]})
assert species.resolve('A') == frozenset({2, 7})
assert species.resolve('X') == frozenset({2, 9})
```

- Implementation: `lammpkeeper/core/species.py`; export from `core/__init__.py`.
  Include the new package in setuptools' explicit package list.
- The constructor accepts explicit label → iterable[type ID] selections. The
  factory accepts type ID → label and optional group label → iterable[type ID].
- Positive integral IDs only, excluding booleans; nonblank string names; nonempty
  memberships. An empty overall map is valid for an unloaded session.
- Repeated type labels form unions. Sparse IDs are preserved, not renumbered.
  Groups may overlap, but unknown IDs and conflicting redefinitions of an exact
  label are errors. The constructor's explicit union defines its known types;
  the factory validates group members against the supplied atom-type keys.
- Defensive snapshots and immutable memberships; returned dictionaries cannot
  mutate the map. Unknown names raise `ValueError` listing valid choices.
- No element/FF literals, chemical-mass inference, underscore-prefix inference,
  display translations or LAMMPS file I/O in the generic core.

`common/mapping.py` remains the preset/compatibility adapter: canonical tables,
scalar conversion helpers, conditional ACE group aliases and display names stay
there. Existing signatures, raw cache keys, filenames and spin conventions stay
unchanged. Its species-selection helpers delegate to `SpeciesMap`; their former
standalone generic validation/resolution is removed only after parity is proved.

### 2. Explicit sources and identity policy

- Preserve ADR-0001's order **per field**, not by replacing the whole system with
  one winning file. For type labels: input → data comments → dump → user fallback.
  A source may fill absent assignments; equal assignments agree. No numeric type
  is compacted or synthesized by the generic resolver.
- A manifest supplies groups/provenance, not duplicate type-element, units,
  boundary, pair-style or timestep metadata. The apparent manifest-first entry
  therefore does not override raw type identities in LAMMPS files.
- Compare explicit sources with explicit sources. Inferred preset/count labels
  cannot veto an explicit assignment; keep their inferred provenance visible.
- Conflicting explicit type labels are diagnosed with source, type ID and both
  values, then rejected. Do not partially apply metadata, return a plausible
  analysis, or silently retain an old cached result as a successful new one.
  Users must reconcile contradictory sources; no new confirmation/force flag is
  introduced in GEN-1. Ambiguous group definitions and invalid references error.
- Input adapters consume supported explicit parser mappings. Numeric pair
  coefficients are not species evidence; NULL holes retain their slot numbers.
  Expanding every pair-style grammar is not part of GEN-1.
- Recognize `Masses` label comments only as a single token (`# A`) or a single
  explicit `species=` token (`# species=A`). Preserve labels separately from
  numeric masses. Ambiguous free-text comments warn and provide no assignment;
  missing comments do not trigger mass-based chemical guesses.
- Dump labels remain arbitrary explicit strings, not automatically chemical
  elements. Require a consistent label per numeric type across consumed frames;
  atom IDs may change types without changing the type→label convention.
  Validate lazily as frames are consumed, rather than materializing a trajectory
  solely to build its map. An unlabelled type remains unresolved on the explicit
  path; any compatibility fallback must be visibly identified as inferred.
- Do not invent numeric types from element-only data in the generic model.
  Preserve existing element-only reader compatibility separately; its synthesized
  legacy types are not promoted to authoritative explicit numeric identity.
- Apply existing canonical proxy-to-analysis-label adaptation only at the preset
  boundary with the established matching-slot checks. Preserve raw source labels
  and provenance separately; do not report intentional preset display aliases as
  contradictory chemical metadata.

### 3. Manifest and session integration

- Optional, explicitly loaded JSON file; proposed conventional name
  `lkpr-run.json`. No automatic file discovery or prep writer in GEN-1.
- Additive shell entry points `load manifest PATH` / `unload manifest`; no existing
  flag, command or import is renamed or removed. A Python file-reading adapter
  lives with current post parsers, not in the generic core.
- Initial schema: `schema_version: 1`, optional `species_groups` mapping names to
  positive integer type-ID lists, and optional `domain`, `system`, `provenance`
  records as allowed by ADR-0001. GEN-1 consumes groups/provenance; storing domain
  or system records does not enable a domain recipe or override physics settings.
- Manifest groups are explicit unions, not an automatic import of arbitrary
  LAMMPS groups such as thermostat/fixed-region selections. A well-formed
  manifest may load before its typed sources: retain it as **pending**, not as
  evidence that its referenced type IDs exist. Re-evaluate references after each
  managed load/unload/replacement. While any manifest group has unresolved IDs,
  constructing the active `SessionState.species_map` raises a clear error naming
  the group, IDs and source; analyses using that map cannot proceed. Do not
  silently omit pending groups or substitute a preset. Loading another typed
  source may resolve them without reloading the manifest. After source unload,
  previously resolved groups can become pending again, and prior numerical
  caches must be invalidated. Invalid group syntax or a conflicting definition
  is an immediate error, not pending metadata.
- Optional `provenance.file_hashes` is a mapping of manifest-relative file paths
  to SHA-256 hex digests. Retain the manifest path as the resolution base, reject
  malformed digests and missing explicitly referenced files, and check the actual
  file bytes. Hash mismatches warn and reject metadata application. Missing manifests are
  fine; explicitly requested missing/malformed files fail visibly. Do not accept
  duplicated LAMMPS identity/units fields as authoritative manifest data.
- Retain source-owned snapshots so unload/replacement recomputes surviving
  metadata in the same order, independent of load order. Keep groups owned by
  the loaded manifest until unload/replacement; contradictory explicit labels
  reject a transaction, while unresolved group references follow the pending
  rule above and block active map construction.
- Derive `SessionState.species_map` from current metadata on access initially,
  avoiding a long-lived map cache. Managed metadata changes validate first, then
  invalidate numerical/structure caches and automatic geometry through the
  existing path; preserve a manually selected surface.
- Direct mutation of legacy `ff_info` still exists for compatibility. A fresh map
  avoids stale selections, but does not promise automatic invalidation of prior
  numerical results after arbitrary dictionary mutation. Such mutation must not
  be advertised as a managed metadata-update API.
- Preserve `parse_data_file`'s existing three-tuple return and existing parser
  entry points. Add metadata extraction without changing that public contract.

## Consequences and migration checks

After approval, proceed incrementally within GEN-1:

1. Add the generic model and collected A/B/X tests independent of any FF name.
2. Route legacy group/selection helpers through it; run PHYS-4 parity before
   changing source loading. Keep domain presets/display logic outside core.
3. Add explicit metadata adapters, provenance/conflict checks and managed session
   load/unload integration. Test both source load orders and rollback/invalidation.
4. Prove source precedence, partial maps, repeated labels, sparse IDs, NULL holes,
   manifest groups, conflicting labels, invalid groups and hash failures. Exercise
   cross-frame consistency and both native/NumPy reader paths without fallback
   being misreported as native success.
5. Run all existing Fe-O goldens unchanged, TEST-3, `/verify-lkpr full`, package
   import checks and manual blast-radius/interrogation equivalents where project
   slash commands are unavailable. Explicitly list missing optional paths.

No fixture edits, rebaselines, new FF convention, physical algorithm change, real
LAMMPS/HPC run or GEN-8 reference choice is authorized by this proposal. GEN-2
retains FF classification work; GEN-4 retains domain extraction; GEN-9 retains
full package moves/removal. Existing compatibility APIs are not deprecated here.

Approval authorizes this incremental GEN-1 contract. ADR-0001 remains accepted
and unchanged; the contradictory backlog order is reconciled to it. Runtime
completion and numerical preservation still require the checks above.
