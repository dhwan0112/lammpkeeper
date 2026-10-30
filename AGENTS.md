# AGENTS.md — LammpKeeper (`lkpr`)

Instructions for coding agents (Cursor CLI/IDE, pstack, Codex, Claude Code).
Humans: see `docs/agent/CURSOR_GUIDE.ko.md`. Ready-made prompts: `docs/agent/PROMPTS.md`.

## 1. What this repo is — and where it is going

- **Today:** LAMMPS pre/post-processing written for Fe oxidation with ACE, ReaxFF
  and 4G-HDNNP. Much of the code assumes Fe/O, slabs and specific force fields.
- **Goal:** a **general-purpose LAMMPS pre/post-processing toolkit**. Any elements,
  any force field, bulk or slab, orthogonal or triclinic boxes, any HPC site.
  Fe-O oxidation becomes the **first domain pack** and the **reference validation
  case**. It does not disappear.
- It is research code: its numbers go into a thesis and papers. A wrong number is
  worse than a crash.
- Design record: `MIGRATION.md`. Architecture decisions: `docs/adr/`. Read both
  before any structural change.

## 2. Prime directives (in priority order)

1. **Physics correctness** > reproducibility of published Fe-O results > generality > speed > style.
2. **No silent wrong answers.** Unknown species, skipped frames, skipped tests,
   failed copies, unsupported box types: raise or warn visibly. Never fall back silently.
3. **Never make a test pass by changing its expected value** without a written
   physical justification (§7).
4. **Small, verifiable steps.** One backlog item = one branch = one PR, with a repro
   or regression test. No big-bang rewrites.

## 3. Architecture direction (target, reached incrementally — see ADR-0001)

| Layer | Owns | Must not contain |
|---|---|---|
| `io` | readers/writers: dump, log, data, input script; box (incl. triclinic tilt), PBC flags, units | analysis logic |
| `core` (system model) | species ↔ type map, species **groups** (one label → several types), units, PBC-aware geometry (MIC, unwrap, periodic neighbor search) | element names, FF names |
| `analysis` | generic analyses: RDF, MSD, density/z-profiles, coordination, molecule/bond tracking, thermo | domain constants |
| `domains/<name>` | domain packs, e.g. `fe_oxidation`: OAR, penetration, charge states, spin evolution, O₂ presets, Fe-O references | generic geometry code |
| `forcefields` | FF registry: units, atom_style, pair lines, element order, dt defaults | system-specific geometry |
| `sites` | HPC/scheduler profiles (PBS@NUS, Slurm, local): modules, scratch, paths | physics |

Rules while getting there:
- **No new element-name or FF-name literals in generic code.** They belong in a
  domain pack, the FF registry or user configuration. Existing ones are migrated
  item by item (BACKLOG `GEN-*`), never all at once.
- **Explicit beats inferred.** Species, FF, units and PBC come from explicit metadata
  (input script, data-file `Masses` comments, dump `element` column, a run
  manifest). A heuristic may only be the last resort, and it prints what it guessed.
- **New analyses take explicit parameters:** species sets (not single type ints),
  `pbc=(bool, bool, bool)`, cutoffs. Defaults for a domain live in its pack.
- **Strangler migration:** add the generic path, route callers through it, prove
  Fe-O results are unchanged (or changed only by a documented bug fix), then delete
  the old path. Keep legacy imports working with shims until a major version.

## 4. Environment and commands

- Python ≥ 3.9. Full dev install: `pip install -e .[all,dev]`. Name any missing
  optional modules and do not claim full coverage.
- Tests (always run with an isolated HOME; history files grow without bound, BACKLOG OPS-1):
  ```bash
  HOME="$(mktemp -d)" python tests/run.py               # fast
  HOME="$(mktemp -d)" LKPR_SLOW=1 python tests/run.py   # + RDF/MSD goldens
  ```
- `tests/run.py` still counts early-`return` skips as PASS (TEST-1). Until that is
  fixed, list the skipped tests.
- End-to-end check: `/verify-lkpr` (`.cursor/skills/verify-lkpr/`).
- Native parser: `native/build.sh` (optional; same results as NumPy). Never edit or
  commit `*.so`.
- Work items: `docs/agent/BACKLOG.md`. Failing-first repros:
  `tests/pending_review_findings.py`.

## 5. Code conventions

- **Logging and comments (maintainer, 2026-10-30):** preserve the existing
  English maintenance-comment coverage. Every new or materially changed class,
  function and test needs an intent/contract docstring; explain non-obvious
  scientific assumptions, state transitions and failure/cleanup branches inline.
  Keep development logs and backlog status current with measured verification,
  named skips, review decisions and evidence. Execution/lifecycle work must retain
  bounded diagnostic and state-event logs; machine stdout stays protocol-only.
- Indentation: **4 spaces everywhere** (PEP 8). This is what the code uses. The
  3-space note in `MIGRATION.md` is stale (DOC-2).
- Generic species selections use `lammpkeeper.core.SpeciesMap` (ADR-0002).
  Canonical type ↔ element ↔ label presets and legacy adapters stay in
  `lammpkeeper/common/mapping.py`; do not put domain literals in core. ACE:
  `1 = Fe_up (Fe)`, `2 = Fe_down (Mn slot)`, `3 = O`.
- Legacy entry points keep working: `python -m lammps_pre|lammps_post`,
  `lammps-pre.py`, `lammps-post.py`.
- Core dependency is NumPy only. Heavy dependencies go in extras.
- Public API (CLI flags, importable functions, output file names) changes need a
  deprecation path and a `CHANGELOG` entry.

## 6. Physics invariants (each must be backed by a test)

- **PBC per dimension**, read from the input `boundary` or dump `BOX BOUNDS` flags.
  Never assume "z is non-periodic".
- **Triclinic boxes** are either handled correctly (MIC in fractional coordinates)
  or rejected loudly. Never ignore tilt factors silently.
- **Track atoms by ID** for per-atom time series. Types may change at runtime
  (e.g. ACE spin `atom/swap`, reactive MC).
- **Species groups:** a user label may map to several types (ACE `Fe` = {Fe_up,
  Fe_down}). Spin- or type-resolved results say so in their label.
- **Periodic neighbor search from the candidate stage.** Reuse
  `_rdf_candidate_pairs` until a `core` neighbor module exists.
- **Fast path == slow path.** Accelerated (scipy/native) and fallback paths give
  identical results. Test this equality.
- **Units:** derive `dt_fs` and the energy/length units from the run. An unsupported
  `units` style raises an error.
- **Fair comparison across force fields:** identical starting coordinates, differing
  only in format (MIGRATION.md, open issue 1).

## 7. Goldens and reference systems

- Goldens detect *change*, not *correctness*. Some currently lock in known-wrong
  values (e.g. `msd_FeUp`, PHYS-1).
- Re-baseline only in a **dedicated commit**:
  `test(golden): rebaseline <key> — <reason> (<BACKLOG-ID>)`. Include old/new
  summary values, the physical reason and an independent check. Leave a comment
  next to the golden.
- Fe-O ACE (`tests/fixtures/ace_examples/`) is reference system #1. Generality is
  proven by a **second, non-Fe reference system** (GEN-8) plus synthetic tests that
  use made-up labels (`"A"`, `"B"`, `"X"`), so hardcoded element names fail loudly.
- Never modify `tests/fixtures/**`.

## 8. Human gates — stop and ask first

- Accepting or changing an ADR. Any change to the module layout in §3.
- Changes to generated LAMMPS inputs, structures or job scripts beyond the BACKLOG
  safety fixes.
- Re-baselining goldens, changing fixtures, changing species/FF mapping conventions,
  renaming or removing CLI flags or public functions.
- `git push` to `main`, force-push, history rewrite, deleting files, installing
  system packages.

## 9. Using pstack in this repo

- Use `/poteto-mode <task> — done when <check>` for multi-step work. Skip it for
  one-line edits.
- Take tasks from `docs/agent/BACKLOG.md`, **one item per session**. Its *Done when*
  is the completion check.
- Playbook overrides:
  - **Bug fix:** the repro is a test under `tests/`. Start from
    `tests/pending_review_findings.py`. Move the test into a collected
    `test_*.py` module registered in `tests/run.py`. Show fail → pass.
  - **Refactoring / GEN items:** first run `/architect`. If a decision is not
    already in an ADR, write `docs/adr/NNNN-*.md` with status `proposed` and stop
    for approval. Then migrate with the strangler rule (§3) and prove Fe-O outputs
    are unchanged.
  - **Shipping / Opening a PR:** branch `fix/<id>-<slug>` or `gen/<id>-<slug>`, based
    on the branch the user names (default `main`). Push feature branches only.
    Merge PRs only when the user explicitly requests merging and the relevant
    verification passes; never merge unsolicited. The orchestrator performs
    remote actions directly, never a delegated worker. Direct pushes to `main`,
    force-pushes and history rewrites still require their separate human gates.
  - **Orchestrate / Autopilot / Benny:** do not use.
  - **Arena / Swarm:** only when explicitly asked (useful for comparing API designs).
- Before reporting done: run `/verify-lkpr`. For `io`/`analysis` changes, also run
  `/blast-radius`. For physics or architecture changes, run `/interrogate`.
- Label numeric claims as *measured*, *inferred* or *guessed*.
- When done, update the BACKLOG status. Update `MIGRATION.md` or an ADR if a design
  changed.

## 10. Commits

Conventional style: `fix(post): …`, `feat(core): …`, `refactor(io): …`, `test: …`,
`docs(adr): …`. Reference the backlog ID. One logical change per commit.
