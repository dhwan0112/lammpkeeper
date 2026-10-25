# Agent backlog

Single source of work items for agent sessions. **One item per session.**
Status: `open` → `in-progress (branch)` → `done (PR/commit)`. Priorities: P1 =
wrong results or data loss, P2 = misleading or fragile, P3 = docs or enabler.
Evidence labels follow pstack: *measured* / *inferred*.

Origin: Codex review + Claude cross-check, 2026-10-20 (branch `parser-streaming`).
Revised the same day after the first Cursor read-only audit (P0): MSD items merged,
forward dependencies removed, DOC-2 added.
Older open decisions live in `MIGRATION.md` → "Issues found by the end-to-end run".

## Suggested order

**Phase 0, reproducibility:** REL-0
**Phase 1, trustworthy tests and correct physics:** TEST-1 → OPS-1 → HPC-1 → PARSE-1 → **MSD (PHYS-2 + PHYS-1, one PR)** → PHYS-4 → PHYS-3 → PHYS-5 → TEST-3 → DOC-1 → DOC-2

**Phase 2, generalization** (ADR-0001 accepted 2026-10-24): GEN-1 → GEN-3 → GEN-2 → GEN-4 → GEN-5 → GEN-6 → GEN-7 → GEN-8 → GEN-9

REL-0 is a hard prerequisite for every item that changes physics outputs (MSD,
PHYS-4, PHYS-3/5). TEST-1, OPS-1, HPC-1, PARSE-1 and DOC-2 do not change physics
outputs and may start before REL-0 is done.

Phase 1 comes first because generic code built on wrong PBC or selection logic
would spread the bugs to every system. Where a Phase 1 fix touches a GEN concept,
use the general form now: species *sets* and a `pbc` tuple. Avoid Fe-specific patches.

---

### REL-0 · P1 · Tag the thesis-reproducible state — `in-progress (prep done; tag = human)`
- **Why:** generalization will change internals. Thesis and paper numbers must stay
  reproducible from a fixed commit.
- **Prep (done 2026-10-20, Cursor):** `docs/reproducibility.md` draft (candidate
  `cdf5c38`, `parser-streaming` tip; verified `42 passed, 0 failed` in a detached
  worktree) and `CHANGELOG.md` (Keep a Changelog). Both are not yet committed.
- **Remaining (maintainer):** confirm the candidate is the commit whose numbers the
  thesis reports (or name another one and re-run the verification on it); create and
  push the tag; fill in the tag name/date in `docs/reproducibility.md`; commit both
  files.
- **Done when:** the tag exists on the remote, `docs/reproducibility.md` says
  "Tag created: yes", and checking the tag out reproduces the goldens on the fixture.

---

### TEST-1 · P2 · Test runner counts skips as PASS — `done (PR #3)`
- **Where:** `tests/run.py`, every `return  # skip` in `tests/test_*.py`.
- **Evidence (measured):** without ASE, 2 tests return early and are reported PASS
  (`42 passed, 0 failed`).
- **Fix direction:** add a `Skip` exception in `tests/_util.py`. Tests raise it (and
  call `pytest.skip` when pytest is present). The runner prints `SKIP name: reason`
  and the summary line becomes `N passed, M failed, K skipped`.
- **Done when:** with ASE uninstalled, the summary shows the skips by name, and the
  pytest output matches.
- **Review notes (2026-10-21):** `_util.skip()` decides "under pytest" by
  `'pytest' in sys.modules`. `os.environ.get('PYTEST_CURRENT_TEST')` is the robust
  signal (set by pytest only while a test runs). Optional follow-up before merge.

### OPS-1 · P1 · readline history files grow without bound — `done (PR #4)`
- Integration: retain the local clear-before-load fix alongside the remote
  2,000-line limit and opt-out; a regression test covers repeated standalone loads.
- **Where:** `lammpkeeper/shell.py` (`_HISTFILE`), `lammpkeeper/common/hosted.py`
  `_setup_history`; files `~/.lkpr_history`, `~/.lammps-pre_history`,
  `~/.lammps-post_history`.
- **Evidence (measured):** Codex saw ~687 MB per file. The Cursor audit on kramers
  counted ~28 M lines each in `~/.lammps-pre_history` and `~/.lammps-post_history`.
  No `readline.set_history_length` call exists. Every shell start reads the whole file.
- **Note:** shrinking the existing files is a human action (they live in HOME, outside
  the repo). The fix only prevents regrowth.
- **Fix direction:** `set_history_length(2000)` before writing. Honour
  `LKPR_NO_HISTORY=1` (skip read and write). Tests set it.
- **Done when:** a test writes 5,000 entries and the file holds ≤ 2,000 lines.
  `LKPR_NO_HISTORY=1` leaves HOME untouched.

### HPC-1 · P1 · Job script deletes scratch even when the copy back failed — `done (branch fix/hpc-1-job-script-safety-local; awaiting review/merge)`
- **Where:** `lammps_pre/templates.py` PBS template (section "4. Copy Results").
- **Evidence (measured, Codex):** injected `cp` failure → results lost, "Success"
  printed, exit 0. *(inferred)* The staging `cp`, `mkdir` and `cd` are also unchecked,
  and the `"$tdir"/*` glob skips dotfiles.
- **Fix direction:** see `.cursor/rules/hpc-job-scripts.mdc`. This is a safety-only
  change; the LAMMPS physics is untouched.
- **Done when:** a test generates the script, then runs it with stub `mpirun` and
  `cp` on PATH. On copy failure, scratch is kept, its path is printed and the exit
  code is nonzero. On success, scratch is removed and the exit code is 0.
  `bash -n` passes.
- **Implementation:** checked fresh scratch creation, staging and directory
  changes; copy hidden files with `cp -a`; one `COPY_OK` gate before checked
  cleanup. Copy failures retain scratch and its recovery path. An optional
  absolute `LKPR_SCRATCH` override keeps the default site path unchanged.
- **Verification (2026-10-25, measured):** 16 stubbed failure/success tests fail
  against `origin/main`'s old renderer and pass with the fix, including partial
  copies, archive/staging failures, stale/symlink scratch and cleanup failures.
  Full verification: 69 passed, 0 failed, 1 skipped (native extension absent);
  post analysis/plots and prep + `bash -n` passed. HPC tests also pass with
  Python `-S` (no optional packages). Real HPC/LAMMPS execution, ShellCheck
  (not installed), MDAnalysis and native parser paths were not verified.

### PARSE-1 · P3 · Dump parser discards `BOX BOUNDS` periodicity flags — `open`
- **Next session target (2026-10-25):** finish PARSE-1, starting from updated
  `main` on `fix/parse-1-boundary-parity`. HPC-1 is ready for review; a real
  HPC execution is still unverified and is not claimed by its local tests.
- **Scope:** boundary metadata and reader regression tests only. Verify `pp pp ff`,
  `pp pp pp`, mixed nonperiodic flags and absent flags; compare native and NumPy
  metadata/frame results on the same synthetic input. Build the optional native
  extension in an isolated checkout if feasible, never commit binary artifacts.
- **Completion gate:** explicit native/NumPy parity evidence plus full regression
  verification, or leave PARSE-1 open with the native verification blocker named.
  Keep fixtures and goldens unchanged. Do not fold in MSD ID tracking or a golden
  rebaseline; those remain the separate PHYS-2 + PHYS-1 PR gated by REL-0.
- Integration: local commit `0c0a21d` now exposes dump boundary flags and adds
  periodicity tests, including shell RDF/MSD routing. Native/NumPy parity still
  needs verification when the optional native extension is available. This does
  not close PHYS-1/2 (ID tracking and the approved MSD golden rebaseline).
- **Where:** `lammps_post/parsers.py` (both reader paths, around the `ITEM: BOX BOUNDS` reads).
- **Why:** this is the boundary source PHYS-1 and PHYS-3 need when no input script
  is loaded.
- **Done when:** frames (or reader metadata) expose `pbc=(True, True, False)` for
  `pp pp ff`. The fixture yields `(True, True, True)`. Both native and NumPy paths agree.

### MSD = PHYS-2 + PHYS-1 · one PR, two commits (PHYS-2 first), golden rebaseline inside
Both defects live in `analyze_msd`. The "correct" reference value below already
needs both fixes, so rebaselining after only one of them would churn the goldens.
Commit order in the PR: ① PHYS-2 (ID tracking) ② PHYS-1 (per-dimension unwrap)
③ `test(golden): rebaseline msd_* …` (human-approved, see TEST-2).

### PHYS-1 · P1 · MSD never unwraps z, even for `p p p` — `open`
- **Where:** `lammps_post/analysis.py::analyze_msd` (`for dim in range(2)`), and the
  caller in `shell.py::_analyze_msd`.
- **Evidence (measured):** fixture (bulk `p p p`), final Fe_up MSD = **17.47 Å²**
  currently, vs **0.07 Å²** with ID tracking + xyz unwrap. The O MSD is unaffected
  here (0.05 both). The 17.47 is locked into golden `msd_FeUp`.
- **Fix direction:** `pbc` / `z_pbc` argument, auto-detected like the RDF
  (input `boundary` → PARSE-1 flags → `surface_z` fallback). Print the choice.
- **Repro:** `tests/pending_review_findings.py::test_msd_unwraps_z_for_fully_periodic_box`.
- **Done when:** the repro passes. A synthetic `p p f` case in the same test module
  shows that z is *not* unwrapped when z is non-periodic (no dependency on TEST-3).
  The MSD goldens are re-baselined in the PR's dedicated commit (TEST-2 rules).

### PHYS-2 · P1 · MSD reselects atoms by type each frame (ACE spin swaps) — `open`
- **Where:** `analysis.py::analyze_msd`.
- **Evidence (measured):** two static Fe atoms with types swapped → MSD 16.0 Å².
  The spin fixture changes Fe_up 64 → 66, so those frames are silently skipped by
  the `len(cur_pos) != n_atoms` check.
- **Fix direction:** select IDs at frame 0, index by ID afterwards, warn if IDs go
  missing.
- **Repro:** `pending_review_findings.py::test_msd_tracks_ids_through_spin_swap`.

### PHYS-4 · P1 · ACE "Fe" resolves to Fe_down only; unknown species are silent — `open`
- **Where:** `shell.py::_analyze_msd` (`inv[v.split('_')[0]] = k`) and the RDF pair
  map (`for short in [n.split('_')[0], n]`).
- **Evidence (inferred from code, consistent with output):** in ACE, `Fe` → type 2.
  Batch MSD writes `msd_Fe.png` for Fe_down only. The default RDF `Fe-O` is
  Fe_down–O. `--species Fx` gives an all-atom MSD labelled "Fx". An unknown RDF pair
  silently becomes types 1/2.
- **Fix direction:** resolve names through `common/mapping.py` to *sets* of types
  (`Fe` → {1, 2} for ACE). Analysis functions accept type sets. Unknown name → error
  listing the valid names.
- **Done when:** tests cover `Fe`, `Fe_up`, `Fe_down`, `O`, and an unknown name, for
  both MSD and RDF. Labels say "Fe (all spins)" vs "Fe↑".

### PHYS-3 · P1 · O₂ detection misses pairs across periodic boundaries — `open`
- **Where:** `analysis.py::detect_o2_dissociation` (cKDTree without `boxsize`).
- **Evidence (measured):** the same boundary-straddling O₂ gives 1 molecule at
  n_O = 2 and 0 molecules at n_O = 21.
- **Fix direction:** reuse `_rdf_candidate_pairs` (periodic tree, z handled per PBC).
  Apply MIC in z too when z is periodic.
- **Repro:** `pending_review_findings.py::test_o2_detected_across_x_boundary_on_tree_path`.

### PHYS-5 · P2 · O₂ pairing algorithm differs between n ≤ 20 and n > 20 — `open`
- **Where:** same function. The slow path does per-atom nearest-first; the tree path
  does global shortest-first.
- **Evidence (measured):** a 4-O chain gives 2 molecules alone and 1 molecule with 17
  distant O atoms added.
- **Fix direction:** one algorithm (global shortest-first) for both paths, plus an
  equality test.
- **Repro:** `pending_review_findings.py::test_o2_count_independent_of_total_o_count`.
- **Coupling with PHYS-3:** keep PHYS-3's periodic candidate stage, and PHYS-3's repro
  must still pass. Shipping PHYS-3 and PHYS-5 as one PR (two commits) is acceptable.

### TEST-2 · Golden re-baseline rules (not a separate session)
- Applied inside the PR that changes the value (MSD PR; PHYS-3/5 if `o2` goldens
  are ever added). PHYS-4 changes name resolution in `shell.py` only; the goldens call
  `compute_rdf`/`analyze_msd` with type ints, so they should not move. If they
  do, stop and investigate.
- Each changed key: a dedicated `test(golden)` commit with reason, old/new summary
  values, an independent check, and a behaviour test (static-crystal MSD ≈ vibration
  only). **Human gate.**

### TEST-3 · P2 · No slab (`p p f`) fixture — `open`
- **Why:** the fixture is bulk. The slab z handling in RDF/MSD/O₂/penetration is
  unverified (MIGRATION.md says so too).
- **Fix direction:** a small synthetic slab dump (≤ 200 atoms, ≤ 20 frames) generated
  by a script committed alongside it. Known answers: an O₂ crossing x/y, an atom
  near the z wall.

### DOC-1 · P3 · Spin docstring contradicts itself — `open`
- **Where:** `analysis.py::analyze_spin_evolution`. "~1/3 → … 8 tetrahedral Fe↓ : 16
  octahedral Fe↑" — 16/24 is 2/3.
- **Done when:** the docstring states which ACE type is majority in the fixture
  (Fe 64 / Mn 128) and the reference for that assignment.

### DOC-2 · P3 · Stale design docs and docstrings — `open`
- **Evidence (measured, Cursor P0 audit):**
  - `MIGRATION.md` §"Stage 1 — dispatcher-only (current)": the branch is well past Stage 1.
  - "Planned" still lists the `dump_modify element` reverse-map fix, which is marked FIXED in Step C.
  - "Known invariants" still describes the atom-count O heuristic as the current path.
  - Its 3-space indentation note contradicts the code (4 spaces everywhere).
  - `common/mapping.py` docstring (about lines 18–19) calls the heuristic "still-open".
  - `lammpkeeper/cli.py` module docstring is half-updated (describes Stage 1 only).
- **Done when:** each stale passage is corrected or marked historical, with no
  behaviour change. Tests unchanged.

---

## Phase 2: generalization (ADR-0001; each item opens with `/architect`)

Every GEN item must be **value-preserving on Fe-O** (same goldens) unless it
says otherwise, and must add made-up-label tests (`"A"`, `"B"`).

### GEN-1 · SpeciesMap: the system owns the type map — `open`
- **Now:** `common/mapping.FORCE_FIELDS` ties FF name → fixed Fe/O types.
- **Target:** `core.SpeciesMap` with label → set of types, built from explicit
  sources in priority order: run manifest → data-file `Masses` comments → dump
  `element` column → input `pair_coeff` element list → user. ACE spin channels become
  groups (`Fe` = {Fe_up, Fe_down}). `mapping.py` becomes a preset provider.
- **Done when:** PHYS-4 tests pass through `SpeciesMap`, and an `A`/`B` system
  resolves without any FF name.

### GEN-2 · Explicit FF/system metadata instead of `detect_forcefield` heuristics — `open`
- **Now:** a charge column → ReaxFF; ≥ 3 types → ACE; 2 types → HDNNP.
- **Target:** read `pair_style` / `units` / `atom_style` from the input script or run
  manifest. The heuristic stays only as a last resort and prints what it guessed.
  Unknown FFs get `generic` with no domain defaults.
- **Done when:** a LJ or EAM trajectory is reported as such (or as `generic`), never
  as ACE/ReaxFF/HDNNP.

### GEN-3 · Box model with triclinic + PBC — `open` (builds on PARSE-1)
- **Target:** `io.Box(lo, hi, tilt, pbc)`. MIC and unwrap in fractional coordinates.
  Until analyses support tilt, they raise an error on triclinic input instead of
  ignoring it.
- **Done when:** RDF and MSD of a synthetic triclinic cell match brute force over
  images, and orthogonal Fe-O goldens are unchanged.

### GEN-4 · Split generic analyses from the `fe_oxidation` domain pack — `open`
- **Move:** OAR, OR, penetration (+trend/profile), charge evolution/states
  (`Q_OXIDIZED_E`), spin evolution, Fe-O references and plot labels →
  `domains/fe_oxidation/`. Old import paths stay as shims.
- **Done when:** `grep -n "Fe\|'O'" lammpkeeper/analysis lammpkeeper/core` is empty
  (docstring examples excepted), and all Fe-O goldens are unchanged.

### GEN-5 · Generic molecule/bond tracking replaces O₂-specific detection — `open`
- **Target:** `analysis.molecules`: pairs/molecules from per-pair cutoffs (periodic
  search, single pairing algorithm). O₂ dissociation becomes a preset
  (`species=('O','O'), cutoff=1.8`) in the domain pack. Builds on PHYS-3 and PHYS-5.
- **Done when:** the presets reproduce PHYS-3/5 results, and an `A–B` diatomic test passes.

### GEN-6 · HPC site profiles — `open` (after HPC-1)
- **Target:** `sites/` profiles (`nus-pbs`, `slurm-generic`, `local`) own the
  scheduler header, modules, compiler env, scratch root and queue. Templates only
  contain the run logic.
- **Done when:** the `nus-pbs` output is byte-identical to today's script (after the
  HPC-1 fix), and the `slurm-generic` and `local` outputs pass `bash -n` and the
  stubbed failure-injection test.

### GEN-7 · Generic prep: structure sources and molecule placement — `open`
- **Target:** structure from an ASE builder / CIF / existing data file. Optional
  placement of N molecules of user-given species in a region. FF registry entries
  are data (units, atom_style, pair lines, element order, dt, masses), so a new FF
  needs no code. The Fe slab + O₂ setup becomes the `fe_oxidation` recipe.
- **Done when:** the Fe-O recipe output is byte-identical, and a non-Fe recipe (e.g.
  LJ argon box) produces a LAMMPS-valid input (checked with real LAMMPS by the maintainer).

### GEN-8 · Reference system #2 (non-Fe) — `open` (human picks the system)
- **Target:** a small committed fixture from a different chemistry or FF, with the
  script that produced it, plus behavior tests (RDF peak positions, MSD regime,
  molecule counts) with known answers.
- **Done when:** `/verify-lkpr full` runs on both reference systems.

### GEN-9 · Package layout + deprecation shims — `open` (last)
- **Target:** the ADR-0001 layout. `lammps_pre` / `lammps_post` become shims that
  emit `DeprecationWarning`. CHANGELOG entry, version bump.
- **Done when:** legacy entry points and imports still work (tests), and the new
  layout is documented in README.
