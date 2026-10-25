# ADR-0001: Evolve lkpr from a Fe-O oxidation tool into a general-purpose LAMMPS toolkit

- **Status:** accepted (2026-10-24)
- **Date:** 2026-10-20
- **Deciders:** 김동환 (maintainer)
- **Backlog:** REL-0, GEN-1 … GEN-9

## Context

The maintainer's goal is a general-purpose LAMMPS pre/post-processing tool. The
current code is built around one study (Fe oxidation, ACE / ReaxFF / HDNNP).
Measured on branch `parser-streaming` (2026-10-20):

- Lines containing `Fe` (`grep -c`): `analysis.py` 63, `plotting.py` 52,
  `references.py` 28, `shell.py` (post) 24. Raw occurrences (`grep -o | wc -l`) are 68 / 66 / 29 / 25.
  Lines containing `o_type`: `analysis.py` 20, `shell.py` 23.
- `parsers.detect_forcefield` infers the FF from data shape: a charge column → ReaxFF,
  ≥ 3 types → ACE, 2 types → HDNNP. Any other system is misclassified.
- `common/mapping.FORCE_FIELDS` ties a **force field name** to a fixed Fe/O type map.
  In general the type map belongs to the **system**, not the FF.
- `lammps_pre`: the builders only make Fe bcc slabs plus O₂. `FF_PRESETS` hardcodes
  potential files. The PBS template hardcodes NUS paths (`/app1/centos7/...`,
  `/hpctmp`, queue `colo-chmlu`).
- `parsers` ignores triclinic tilt factors. `units` handling covers `metal` / `real` only.
- Analyses assume slab `p p f` in places (MSD, O₂ minimum-image convention), and the
  only fixture is bulk `p p p`.

## Options

**A. Big-bang rewrite into a new package.** Clean design, but every Fe-O number has
to be re-validated at once. The thesis work is exposed to regressions. High risk.

**B. Strangler migration into a layered `lammpkeeper` package (chosen).**
Introduce generic layers next to the existing code, route callers through them one
by one, and prove the Fe-O outputs unchanged at each step. Delete the old paths at
the end. Slower, but every step can be verified.

**C. Keep lkpr Fe-O-specific and build generic features on external libraries**
(MDAnalysis, ASE, OVITO). Least code, but lkpr then never becomes the general tool.
The Fe-specific parts are also exactly where the bugs were found.

B can still *use* external libraries where they are equivalent (see Open questions).

## Decision

Option **B**, with this target layout:

```
lammpkeeper/
  io/          dump, log, data-file, input-script readers/writers; Box(lo, hi, tilt, pbc); units
  core/        SpeciesMap (label → set of types), geometry (MIC incl. triclinic, unwrap, periodic neighbors)
  analysis/    rdf, msd, density, coordination, molecules (bond/molecule tracking), thermo
  forcefields/ registry: ace_feo, reaxff2010, reaxff2015, hdnnp, + user-defined from config
  sites/       nus_pbs, slurm, local — scheduler header, modules, scratch policy
  domains/
    fe_oxidation/  OAR, penetration, charge states, spin, O₂ presets, Fe-O references, slab+O₂ recipe
  prep/ post/  CLIs and interactive shells (thin; call the layers above)
lammps_pre/, lammps_post/   compatibility shims until the next major version
```

Invariants of the migration:
1. **Reproducibility first.** REL-0 tags the commit whose numbers the thesis uses,
   before any GEN step lands.
2. Each GEN step is value-preserving on reference system #1 (Fe-O), except for
   documented bug fixes (PHYS-*) with re-baselined goldens.
3. Species, FF, units and PBC become explicit metadata. Heuristics remain only as a
   last resort that prints what it guessed.
4. Generality is proven by reference system #2 (non-Fe, GEN-8) and by
   made-up-label synthetic tests.

## Consequences

- Easier: adding a new system or FF means configuration plus a domain pack, with no
  edits to the generic code. Bugs in PBC and selection are fixed once, for everyone.
- Harder: more modules. Deprecation shims must be maintained for a while.
- Migration order: PHYS/TEST fixes → GEN-1 (SpeciesMap) → GEN-3 (Box/triclinic) →
  GEN-2 (explicit FF metadata) → GEN-4 (split domain pack) → GEN-5 (generic molecule
  tracking) → GEN-6 (sites) → GEN-7 (generic prep) → GEN-8 (second reference system) →
  GEN-9 (package moves + shims).

## Open questions (answered)

Answers recorded 2026-10-24 by the maintainer. The ADR was accepted the same day.

1. **Scope:** LAMMPS-only (the working assumption), or engine-agnostic later? The
   `io` layer boundary is the place where this would matter.
   - **Answer:** LAMMPS-only. No other MD engine is planned. The `io` layer does
     not need an engine abstraction.
2. **Configuration:** introduce a run manifest (e.g. `lkpr.toml`, written by prep and
   read by post) as the explicit-metadata source? Format and name?
   - **Answer:** yes, as a small **optional** manifest.
     - **Contents:** only what LAMMPS files cannot express: species groups (e.g.
       `Fe` = {Fe_up, Fe_down}), domain name, system parameters (surface z, fixed and
       thermostat layer bounds, molecule placement region), and provenance (lkpr
       version and commit, generation parameters, seed, hashes of the generated
       input and data files).
     - **Not duplicated:** units, boundary, atom_style, pair_style/pair_coeff,
       timestep, box and masses stay in the LAMMPS input and data files.
     - **Optional:** post must work without a manifest (trajectories not produced
       by lkpr prep). Lookup order: manifest → input script → data-file `Masses`
       comments → dump columns → user. A last-resort heuristic prints what it guessed.
     - **Conflicts:** if the manifest disagrees with the input or data file (or a
       hash does not match), warn visibly. Never pick one silently.
     - **Format:** JSON (stdlib; `tomllib` needs Python ≥ 3.11 and the project
       supports ≥ 3.9). File name to be fixed in the implementing item (working
       name `lkpr-run.json`).
3. **Build vs reuse:** own NumPy `core` geometry, or depend on MDAnalysis / ASE for
   neighbor search and triclinic handling (heavier dependencies, less code)?
   - **Answer:** build in-house where feasible (NumPy core; SciPy stays an optional
     accelerator). External libraries are acceptable only in optional extras and as
     independent cross-checks in tests.
4. **Distribution:** PyPI release, license, supported Python versions?
   - **Answer:** deferred. Does not block the GEN items. Revisit before sharing
     the code with the group or publishing it with a paper. Python ≥ 3.9 stays
     the floor for now.
5. **Second reference system** for GEN-8: which system, and from which source?
   - **Answer:** undecided. Candidates: SPC/E water, ~216 molecules (real units,
     `atom_style full`, bonds and molecules, kspace; literature RDF peaks and
     diffusion coefficient); Cu EAM slab (metal units, `p p f`, also covers
     TEST-3, but one element only); binary Kob-Andersen LJ A/B (lj units, made-up
     labels, no potential files). Agent recommendation: SPC/E water, unless a
     system from planned research is a better fit. The maintainer picks before
     GEN-8 starts.
