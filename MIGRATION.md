# LammpKeeper (`lkpr`) — Migration Notes

Consolidation of the two independent CLIs (`lammps-pre`, `lammps-post`) under a
single entry point `lkpr` with `prep` / `post` subcommands.

**Original dispatcher goal:** unify the entry point *without changing any numeric
or physical behavior*. That Stage-1 constraint describes the initial integration,
not all subsequent work: shared modules and documented correctness fixes have
since landed. The accepted generalization target is ADR-0001; the current work
order and completion evidence live in `docs/agent/BACKLOG.md`.

---

## Current status (DOC-2, 2026-10-28)

- The dispatcher and shared `common/display.py` / `common/mapping.py` are in use;
  the full ADR-0001 package layout is a target, not the current module layout.
- Step C completed deterministic canonical ACE type resolution and explicit dump
  element labels. GEN-1 adds the system-owned `core.SpeciesMap` under the approved
  ADR-0002 contract; its integration/evidence is recorded below. Force-field,
  units and timestep inference still has warned paths tracked under GEN-2.
- PHYS-1/2, PHYS-3/5, PHYS-4, the whole-code audit (PR #15) and the synthetic
  slab integration reference (TEST-3, PR #17) are complete. Their documented
  corrections are not value-preserving refactors of the original thesis state.
- The unchanged `v1.2.0-thesis` tag preserves `cdf5c38`; approved MSD/RDF golden
  corrections are recorded separately in the backlog and audit report.
- Source indentation is **4 spaces throughout**. The old split-style/3-space
  instruction was inaccurate and is not a current convention.
- Real LAMMPS/HPC execution is deferred. The old run report below is historical,
  not a claim that the current code or this environment was run on LAMMPS.

## Audit correction note (2026-10-27)

The historical validation statements below describe the limited checks performed
at the time; they do not certify the full RDF, parser or geometry implementation.
The whole-code audit reproduced same-species RDF undercounting, final-frame
normalization dependence, unsafe cell interpretation and workflow cache errors.
The maintainer requested all audit findings be corrected under
`AUDIT-20261027` (see `docs/agent/BACKLOG.md`). This is an in-place correctness
repair, not a module-layout change or a new architecture decision.

The explicitly approved RDF rebaseline normalizes each frame by its own
N_a*N_b/V, then averages frame RDFs equally. An independent full A-B pair matrix
on the last 20 reference frames gives peak 55.8130906709 instead of
55.8132059165. These frames include minimization and remain regression data, not
an equilibrium or kinetics validation. Fixtures and the thesis tag stay unchanged.
Real LAMMPS/HPC execution remains deferred; local generated-script tests cannot
certify dynamics or scheduler/site behavior.

## Synthetic slab coverage (TEST-3)

A reusable generated `pp pp ff` toy reference now checks serialized parsing,
metadata/load order, shared/cached processing and analytic RDF/MSD/O2/penetration
answers. `tests/synthetic_slab.py` creates the 16-atom/six-frame dump only in
runtime output directories; committed fixtures and goldens stay unchanged.
`docs/agent/TEST-3.md` gives the independent expectations and explicit limits.
This establishes synthetic slab-path integration, not material dynamics, a real
LAMMPS run or the undecided non-Fe GEN-8 reference system. The historical bulk
fixture and historical verification claims below retain their original scope.

## System-owned species (GEN-1; ADR-0002)

The maintainer approved ADR-0002 on 2026-10-28 before implementation. Generic
label/type-set storage and resolution move into `lammpkeeper.core.SpeciesMap`;
`common/mapping.py` keeps canonical presets, display conventions and legacy
imports. Repeated labels form unions; sparse IDs are preserved, not renumbered.

Explicit type-label sources follow ADR-0001: input → data Masses comments → dump
→ user fallback. Optional JSON manifests provide groups/provenance rather than
duplicate LAMMPS physics metadata. Conflicting explicit labels warn and reject
application, instead of silently selecting one. Pending manifest references
cannot construct an active map. This reconciles the old contradictory GEN-1
backlog order; it does not change the accepted ADR-0001.

The migration is additive: existing selection helpers route through the generic
model, parser contracts remain compatible, and source/group loading uses managed
cache invalidation. `docs/agent/GEN-1.md` records implementation/verification
status and the optional manifest interface. FF classification remains GEN-2,
triclinic support GEN-3, domain extraction GEN-4 and full package moves GEN-9.

## Stage 1 — dispatcher-only (historical)

Minimal, non-destructive. No files were moved; no analysis/physics code changed.

### What was added
| File | Purpose |
|------|---------|
| `lammpkeeper/__init__.py` | package + single `VERSION` |
| `lammpkeeper/cli.py` | top-level `lkpr` router (`main`) |
| `lammpkeeper/__main__.py` | `python -m lammpkeeper` support |
| `pyproject.toml` | packaging; `lkpr = "lammpkeeper.cli:main"`; extras `[prep]`/`[post]`/`[all]` |

### What was changed (minimal, backward-compatible)
- `lammps_pre/cli.py` — `def main():` → `def main(argv=None):`, and
  `parser.parse_args()` → `parser.parse_args(argv)`.
- `lammps_post/cli.py` — same two-line change.

Because `argv` defaults to `None` and `parser.parse_args(None)` reads `sys.argv`,
every existing invocation behaves **exactly** as before.

### How dispatch works
`lkpr <command> <args...>` forwards `<args...>` **verbatim** to the existing
sub-CLI:

```
lkpr prep --ff ace --temp 500 --o2 100 --write ./out/
      └── lammps_pre.cli.main(['--ff','ace','--temp','500','--o2','100','--write','./out/'])

lkpr post --log log.lammps --plot thermo --theme publication
      └── lammps_post.cli.main(['--log','log.lammps','--plot','thermo','--theme','publication'])
```

The top-level parser owns only `lkpr -h` and `lkpr --version`; it does **not**
re-declare subcommand flags, so each subcommand keeps its own argparse
definitions, help text, `--version` string, and exit behavior unchanged.

### Backwards compatibility (unchanged, still works)
- `python -m lammps_pre ...` / `python lammps-pre.py ...`
- `python -m lammps_post ...` / `python lammps-post.py ...`

### Decisions made to preserve behavior
- **No file moves / no import rewrites in Stage 1.** Shared display/mapping
  extraction followed in Stage 2. The wider package reorganization is now tracked
  by ADR-0001 / GEN-9, not an already completed Stage-1 change.
- **Flags are namespaced under subcommands**, so the pre-existing flag
  differences are not conflicts (e.g. prep `--write` vs post `--output`,
  prep `--ff` vs post `--format`). They are left as-is; harmonizing them is a
  Stage-2 decision and would be flagged before any change.
- **Indentation correction (DOC-2):** all Python packages use 4 spaces, including
  `lammpkeeper/`. The former 3-space/split-style note was incorrect; no source
  reformatting is part of this documentation correction.

---

## Stage 2 — refactoring (incremental, each step regression-verified)

Steps A/B were guarded by before/after baselines and were value-preserving
extractions. Step C also repaired type resolution and changed dump metadata.
Later PHYS/audit fixes intentionally corrected behavior with their own regression
and approval records; they are not covered by the original no-change claim.

### Completed

**Step A — `common/display.py`.** `display.py` was byte-identical in both
packages. Moved to the single source of truth; both package modules are now
re-export shims. Verified: rendered display API and CLI snapshots
(`post --find`, no-data error, `--help`) byte-identical before/after; object
identity `lammps_pre.display.C is lammps_post.display.C is
lammpkeeper.common.display.C`.

**Step B — `common/mapping.py`.** Single source of truth for the per-force-field
`type↔element↔label` convention, replacing three independent copies:
`lammps_pre.state.FF_PRESETS` (forward), `lammps_post.parsers.detect_forcefield`
(reverse: ACE element dict, ReaxFF/HDNNP fallbacks), and
`lammps_post.analysis.analyze_spin_evolution` (hardcoded ACE types 1/2/3).
This Step-B extraction was value-preserving and did **not at that time** alter
post's atom-count heuristic. Step C subsequently fixed canonical ACE reverse
mapping; remaining force-field/metadata inference is tracked under GEN-2.

Regression record (fixture `regular_MD/traj.dump`, 448 atoms, 350 frames, ACE
element-path; numpy-only). Canonical fingerprint of prep `FF_PRESETS` atom_types,
post `ff_info`/`_guess_o_type`, RDF(Fe↑–O), MSD(O), MSD(Fe↑), and spin —
**identical before/after** (44 KB canonical blob byte-for-byte; TOTAL sha256
`6a3b93bc…`). This historical comparison exercised the deterministic element
path, not the count heuristic (Rule 3) or slab z-PBC / 2D-MSD paths; it did not
verify those paths. Later PHYS/audit and TEST-3 checks have their own scope and
evidence, rather than retroactively extending this Step-B result.

### Regression suite (`tests/`)

The original four modules below grew into the collected suite listed in
`tests/run.py`. Tests include behavior assertions, independent synthetic oracles
and approved regression goldens; goldens detect change, not physical correctness.
Run with an isolated HOME to avoid reading/writing personal shell history:

```bash
HOME="$(mktemp -d)" python tests/run.py             # no pytest required; NumPy core
HOME="$(mktemp -d)" LKPR_SLOW=1 python tests/run.py # also RDF/MSD goldens/oracle
HOME="$(mktemp -d)" pytest tests/                  # if pytest is installed
```

Original suite inventory (not an exhaustive current list):

- `test_mapping.py` — canonical tables + prep/post value preservation.
- `test_display.py` — single-source object identity + rendering.
- `test_lkpr_cli.py` — dispatcher routing + verbatim delegation (sub-versions).
- `test_regression_numeric.py` — ACE fixture ff_info/spin/RDF/MSD fingerprints.

Later modules cover ID tracking, species groups, periodic geometry, parser and
workflow failures, prep safety, actual plot artists and the serialized slab
reference. Optional dependencies produce explicit named skips. The TEST-3 report
records **261 passed, 0 failed, 0 skipped** in the rich environment on test
sources `39f0e95`; that is a dated snapshot, not a fixed suite-size guarantee.

**Step C — deterministic type resolution.** Closes the reverse-map fragility the
end-to-end run exposed. Three separate places were *guessing* which atom type is
oxygen; all three now read the convention from `common/mapping.py`.

*prep* (`135270f`) writes the convention into the trajectory instead of leaving
it implicit in the input script:

```
dump        traj all custom N ... id type element x y z vx vy vz
dump_modify traj sort id element Fe Mn O format float %12.6f
```

LAMMPS accepts this, and the dump now labels types 1/2/3 as Fe/Mn/O. The element
list and `pair_coeff` both come from `mapping.element_order('ace')`, so they
cannot drift apart.

*post* (`45e7d73`) replaced the canonical ACE oxygen-type guess. This was not
removal of all force-field/metadata heuristics; other fallback branches remain
and now warn visibly (GEN-2).

| Before Step C | After Step C (historical transition) |
|-----|-----|
| Rule 3 guessed O = "the rarest type, if under 20% of the most common" | uses fixed ACE slots for the three-observed-type case; other count-fallback cases remain |
| Rule 2 returned element-keyed `atom_types` | type-keyed, like every other rule |
| element-only dumps numbered elements alphabetically | canonical element→type from `mapping` |

Why the heuristic had to go: its premise — "O atoms are far fewer than Fe" — is
false for the bulk magnetite these ACE runs target. Fe₃O₄ is Fe:O = 3:4, so **O
is the most abundant species**; the committed example fixture is Fe 64 / Mn 128 /
O 256. Under spin polarization the rarest type becomes the *minority Fe*, and the
guess relabelled Fe_up as O — 400/3600/400 gave `{2:Fe_up, 3:Fe_down, 1:O}`,
silently corrupting every O-based analysis. The element-keyed `atom_types` was
the same class of bug: callers index by numeric type behind `isinstance(t, int)`
guards, so element keys fell through to a "Fe is type 1" fallback that dropped
Fe_down from surface detection.

The Step-C verification record reported a byte-identical generated data file
and spin / RDF / MSD / O₂-dissociation fingerprints from an otherwise identical
LAMMPS run, with only an added dump column. On the committed fixture the physics
hashes were unchanged at that step; `ff_info` alone was re-baselined for its
representation change. The recorded **16 passing tests** in NumPy-only and full
environments are historical, not the current suite count. Subsequent approved
physics corrections have separate golden records.

### Historical end-to-end report with a real LAMMPS run

This preserved report describes an earlier `lkpr prep` → **LAMMPS** → `lkpr post`
cycle. Its numeric observations and environment are historical evidence, not a
fresh run or a validation of the current checkout. No LAMMPS/HPC execution was
performed for DOC-2; current local checks replay trajectories or generate/test
scripts without launching a simulation. The later RDF/parser/geometry audit
found defects outside the scope of the checks recorded here.

**Setup.** LAMMPS 22 Jul 2025 (`REAXFF`, `ML-PACE`, `ML-HDNNP` built in);
`lkpr` installed as a real console script (`pip install -e .`) into a venv over
the conda `mlff` env (ase, scipy, pandas, matplotlib, MDAnalysis, rich present).
Fe(100) 4×4×8 slab, 4 O₂, 800 K, `p p f`, seed 12345 — same defaults as
production, only smaller and shorter.

| Check | Result |
|-------|--------|
| `lkpr prep` → LAMMPS-valid inputs (ReaxFF-2010) | ✅ ran to completion, 12 ps oxidation, 502 frames |
| `lkpr prep` → LAMMPS-valid inputs (ACE) | ✅ data/regions/script accepted; stages 0–2 ran (see MC note below) |
| `lkpr post --analyze all --plot all` (ReaxFF) | ✅ 14 analyses, 16 figures |
| `lkpr post --analyze all --plot all` (ACE) | ✅ 12 analyses, 14 figures |
| units / atom_style per FF, read back from the generated script | ✅ reaxff = real+charge, ace = metal+atomic |
| prep forward map == post reverse map (real dumps) | ✅ reaxff `{1:Fe,2:O}`, ace `{1:Fe_up,2:Fe_down,3:O}` |
| dt / time axis agreement (prep preset vs post detection) | ✅ 0.25 fs both, units agree |
| Legacy entry points still work | ✅ `python -m lammps_pre/-post`, `lammps-pre.py`, `lammps-post.py` |
| Regression suite under the **full** dependency set | ✅ 13 passed (same golden hashes as numpy-only) |

**LAMMPS confirms the ACE spin convention.** The `pace` pair style echoed
`type #1(Fe) → ACE species #1`, `#2(Mn) → #2`, `#3(O) → #3`, and the runtime
`set … type/fraction` produced real type-2 atoms (counts `{1:41, 2:87, 3:8}`).
`post` read that label-less dump back as `{1:Fe_up, 2:Fe_down, 3:O}` and
reported an Fe_up fraction of 0.320 = 41/128 exactly.

**Physics checks on the real ReaxFF oxidation** (not just "no exception"):
O₂ dissociation 4 → 1 (6 O atoms dissociated) — matched atom-by-atom against
raw O–O distances; QEq total charge conserved to 0.000000 e; Fe positive
(max +0.455 e) / O negative (mean −0.738 e); Fe⁰=124 / Fe²⁺=4 / Fe³⁺=0,
consistent with the reported "oxidized Fe (q>0.3) = 4". The historical report
compared the RDF peak (1.57 Å) with a direct bonded-distance mean (1.53 Å).
That limited comparison did **not** establish RDF counting or normalization
correctness; the later audit corrected both and added an independent pair-matrix
oracle. Peak location and the mean of a selected bond population are also not
identical observables.

*Observation (pre-existing, not caused by this work):* those Fe–O bonds are
short versus the literature (~1.9–2.1 Å). The repo's own production result
(`lammps/Runs/reaxff2010/o2_100/800K/final_reaxff2010_800K.data`, 2000 Fe +
200 O) shows the same thing — Fe–O mean 1.600 Å, Fe–Fe 2.379 Å — against
1.571 Å / 2.371 Å in the historical run. The report interpreted this as
agreement with that production setup. Similar short distances alone do not
validate the force field, establish their cause, or certify dynamics; this
observation is retained as a historical question, not a current physics claim.

### Issues found by the historical end-to-end run — status as of DOC-2

1. **Cross-force-field coordinates — corrected.** The original run found an
   identical Fe slab but an ACE O₂ band and box top 2.0 Å above ReaxFF. The old
   `z_wall_lower = z_nve_top + rc + 0.9` coupled placement to the force-field
   cutoff (ACE 7.0 Å versus ReaxFF 5.0 Å). Current builders instead use the shared
   `state.wall_cutoff`; `tests/test_fair_comparison.py` checks identical Fe/O₂
   coordinates, cell, box and wall for all three prep presets. This corrects the
   stated initialization invariant. The old report's suggestion of a negligible
   dynamics effect was an inference, not a measured bound on physical impact.

2. **Canonical ACE reverse mapping — corrected** (`135270f`, `45e7d73`).
   See Stage-2 Step C above. This does not resolve all generic species/force-field
   inference; remaining warned heuristics are GEN-1 / GEN-2 work.

3. **Missing MC package — historical environment limitation, not rechecked.**
   The old report's `/home/kdh/chemistry/lammps/install/bin/lmp` lacked **MC**,
   so `fix atom/swap` aborted the ACE run. The report used a modified copy with
   that fix commented out; it did not establish a full unmodified ACE run.
   Enabling `PKG_MC` was the suggested remedy. Neither that path nor a current
   HPC binary's capabilities have been verified in the present environment.

4. **Short ACE oxidation duration — corrected in the audit (PR #15).** The
   former `ox_dense = round(50.0/dt)` / `ox_remain = round((OX_PS-50)/dt)` could
   emit a negative remaining count below 50 ps. Current templates clamp the
   configured dense stage to total oxidation steps and the remainder to zero.
   `tests/test_audit_prep.py` independently evaluates short/zero duration
   expressions and step totals. This is generated-script validation, not a new
   LAMMPS execution or potential/dynamics check.

5. **Additional prep presets — still not implemented.** Prep offers `ace`,
   `reaxff2010` and `reaxff2015`; post's `hdnnp` detection is not a prep preset.
   HDNNP/CHGNet generation would require separate force-field/recipe work, not a
   doc correction. Registry/general prep direction is recorded in ADR-0001 and
   GEN-7; no new preset or force-field convention is decided here.

### Remaining work (ADR-0001 / backlog, not a new design decision)

- The GEN-1 species-map path above is distinct from explicit force-field
  metadata (GEN-2) and registry/general prep work (GEN-7), which remain future
  work. They replace the old standalone `forcefields.py` suggestion; prep and
  post still use different FF names.
- Shared data/box/units contracts belong to the accepted `io` direction. The old
  `lammps_data.py` / `units.py` suggestions were not implemented module names.
  Prep `ps_to_steps` and post `dt_fs` derivation remain different operations;
  current input/log parsing supports `metal` / `real` and rejects unsupported
  styles, but this is not a complete general units model.
- The old planned `dump_modify element Fe Mn O` fix is **already complete** in
  Step C, not pending work. Canonical mapping is shared; cross-FF initialization
  is covered by the corrected fair-comparison tests described above.
- A shared parent parser for `--batch` / subcommand `--version` was only a
  suggestion, not an accepted API change. Explicit prep/post arguments still
  forward verbatim; unified interactive routing is also implemented.
- Full package moves and deprecation shims remain GEN-9, after the incremental
  generic paths. This note does not approve layout, flag or public API changes.

### Invariants and verification limits — current interpretation

- **Canonical mapping:** ACE prep now writes explicit `element` labels using
  `mapping.element_order`, and canonical ACE post/spin helpers share the mapping
  convention. ACE type 1 = Fe_up, type 2 = Fe_down (Mn proxy), type 3 = O.
  Species-group analysis can select both Fe channels (PHYS-4), now through the
  GEN-1 generic map; a warned FF/count fallback is still not explicit metadata.
- **PBC and supported boxes:** shell analyses use dump/input per-axis flags.
  Synthetic MSD/O₂/RDF checks and TEST-3 cover periodic x/y and nonperiodic z;
  slab handling is not an unconditional "z off" assumption. Direct analysis APIs
  retain legacy defaults when PBC is omitted; supply it explicitly. Triclinic
  dump/data boxes are rejected, not silently flattened or correctly handled;
  fractional-coordinate support remains GEN-3.
- **Atom identity and numerics:** MSD follows the initial atom-ID cohort and
  sums all three Cartesian displacement components; PBC controls unwrapping,
  not a projection onto periodic axes. The approved MSD and RDF fixes have
  independent oracles and separate golden records. A diffusion fit requires a
  justified dimensionality and physically appropriate sampling; optimizer frames
  and toy wall jumps do not establish material diffusion.
- **RDF and molecule semantics:** current RDF includes selected nonzero-distance
  intramolecular O–O pairs; there is **no molecular exclusion**. The old note
  listing "RDF O₂ intramolecular exclusion" did not describe an implemented
  feature. O₂ detection is deterministic shortest-first cutoff pairing (default
  1.8 Å), not bond order or proof of chemical dissociation. Charge-state labels
  likewise use domain thresholds, not an independent oxidation-state measurement.
- **Scope of evidence:** the historical real-run report, current replay goldens,
  synthetic analytic tests and generated-script checks answer different
  questions. None substitutes for deferred current LAMMPS/HPC validation or the
  maintainer-selected non-Fe GEN-8 reference.
