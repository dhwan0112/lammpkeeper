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

**Scheduling update (maintainer, 2026-10-26):** defer actual HPC submissions,
site-dependent validation and HPC site-profile work (GEN-6) until early-to-mid
November 2026 or later, when the maintainer is available; this is not an
automatic restart date. HPC-1's local safety fix is done, but real-cluster
execution remains unverified. In the meantime prioritize local analysis,
synthetic regressions and replay of committed trajectories. No new HPC jobs or
site changes are part of this work.

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

### REL-0 · P1 · Tag the thesis-reproducible state — `done (v1.2.0-thesis)`
- **Why:** generalization will change internals. Thesis and paper numbers must stay
  reproducible from a fixed commit.
- **Completed (2026-10-26, maintainer approved):** annotated tag `v1.2.0-thesis`
  created and pushed at `cdf5c38e975871debf64eb6d810e78a08165c381`.
  `docs/reproducibility.md` records the tag and verification limitations.
- **Verification (measured):** isolated checkout at the tagged commit, with
  `LKPR_SLOW=1` and isolated HOME, reports `42 passed, 0 failed`; RDF/MSD
  goldens pass. The historical runner counts three early-return skips as PASS
  (two ASE tests and one native-parser test). This freezes historical results,
  including known MSD defects; it is not a physics-correctness certification.
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

### HPC-1 · P1 · Job script deletes scratch even when the copy back failed — `done (PR #9)`
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
- **Integration verification (2026-10-26, measured):** combined with PARSE-1
  from PR #10; full native verification and pytest both passed all 72 tests.
  Forced NumPy mode passed 70 tests with 2 explicit native-test skips in both
  runners. Full analysis/plots and prep + `bash -n` passed in both modes; all
  three force-field job templates also passed `bash -n`. Evidence:
  `/tmp/opencode/parse1-native-9tj0Xnpf/evidence-combined` and
  `/tmp/opencode/lkpr-combined-fallback/20261026T134705-310566d-full`.
  Real HPC/LAMMPS execution remains unverified.

### PARSE-1 · P3 · Dump parser discards `BOX BOUNDS` periodicity flags — `done (branch fix/parse-1-boundary-parity)`
- **Implementation:** commit `0c0a21d` exposes dump boundary flags and adds
  shell RDF/MSD routing. Header metadata is shared by both atom-block backends
  and is available as `DumpReader.boundary` / `LazyFrames.reader.boundary`,
  converted to per-axis booleans by `pbc_from_boundary`.
- **Where:** `lammps_post/parsers.py` (both reader paths, around the `ITEM: BOX BOUNDS` reads).
- **Why:** this is the boundary source PHYS-1 and PHYS-3 need when no input script
  is loaded.
- **Done when:** frames (or reader metadata) expose `pbc=(True, True, False)` for
  `pp pp ff`. The fixture yields `(True, True, True)`. Both native and NumPy paths agree.
- **Verification (2026-10-25, measured):** slab, bulk, mixed nonperiodic and
  absent flags agree across streaming, indexed and cached/uncached access.
  Native parity uses float64/float32, generic A/B labels and numeric selections;
  it asserts successful compiled-extension calls and forbids NumPy fallback.
  The committed bulk fixture reports `(True, True, True)`.
- **Evidence:** an isolated source copy with Rust/Cargo 1.99.1 and mlff Python
  3.11.15 / NumPy 2.4.3 passed full verification (`56 passed, 0 failed, 0 skipped`)
  and pytest (`56 passed`). Forced NumPy mode passed both runners (`54 passed,
  2 skipped`, the two native tests). Full post analysis/plots and prep + `bash -n`
  passed in both modes. Evidence directories:
  `/tmp/opencode/parse1-final-native/20261025T204229-nogit-full` and
  `/tmp/opencode/parse1-final-fallback/20261025T204147-922e517-full`.
- **Limits / next gate:** no fixtures, goldens, frame keys or physics behavior
  changed. Boundary metadata describes the first frame, not changing boundaries
  in concatenated runs. Triclinic geometry remains GEN-3; real LAMMPS/HPC execution and
  MDAnalysis were not verified. PHYS-2 + PHYS-1 remain a separate MSD PR; REL-0
  maintainer confirmation/tagging and human approval of any golden rebaseline
  are still required before that physics-changing work.

### MSD = PHYS-2 + PHYS-1 · one PR, two commits (PHYS-2 first), golden rebaseline inside
- **Status:** done locally (`fix/msd-id-tracking`, 2026-10-27): PHYS-2 in
  `64a6084`; approved PHYS-1 golden rebaseline in dedicated commit `c9eeb37`.
  REL-0 is complete. No fixtures were modified and no push/PR/merge has been
  performed for this work. The maintainer approved the numerical correction
  after reviewing its physical interpretation and limitations.
- **Reproduction (measured):** the collected synthetic suite had 15 failures and
  10 passes before the fix, then 25 passes. Four follow-up cases bring the
  collected MSD module to 29 passes (37 with periodicity tests). The static type-swap case changes
  from a fictitious 16 Å² to zero; population changes no longer drop frames.
- **Implementation:** select an initial cohort by integer type or type set and
  track IDs thereafter. Missing tracked IDs, duplicate/invalid IDs, absent ID
  columns and invalid supplied bounds raise clear errors. Newly added IDs warn
  and are excluded. A missing sample is not skipped because an unknown periodic
  crossing cannot safely be reconstructed across the gap.
- **Verification (measured):** `/verify-lkpr full` script: 99 passed, 0 failed,
  2 skipped (ASE tests); post `analyze all` passes, prep is skipped (ASE absent).
  Forced NumPy mode: 97 passed, 0 failed, 4 skipped (same ASE tests plus 2 native
  tests). Native/NumPy fixture MSD measurements match exactly. Matplotlib,
  pandas, MDAnalysis and pytest are absent; plots and their paths are unverified.
  No real LAMMPS execution or HPC submission was performed.
- **Independent check (measured):** ID dictionaries plus brute-force periodic
  image enumeration reproduce the regular bulk cohort to max error
  4.17e-16 Å² and the spin-equilibration cohort to 6.81e-16 Å². The latter now
  uses 337/337 frames, compared with 32/337 before the fix (305 skipped).
  Analytic type-swap, vibration, bulk and slab behavior tests also pass.
- **Golden rebaseline (approved and applied 2026-10-27):** regular-fixture
  regressions now explicitly use dump `pp pp pp` metadata instead of the slab
  default. Only the `msd_FeUp` fingerprint changes:
  `msd_FeUp` final 17.4725703688831 → 0.074623992827988 Å², fingerprint
  `eb7f778ead75a17d` → `8a151e1c5051cb59`. `msd_O` remains
  0.049907252878781 Å² / `ce2e617b3ad32239`. The regular fixture does not change
  type membership; this golden correction is due to z periodicity (already
  supported since PR #8), not the new ID-tracking fix. The public slab default
  is preserved; the bulk regression's explicit PBC and golden were changed
  together in the dedicated human-approved commit.
- **Evidence (local):** `/tmp/opencode/msd-before.json`, `msd-after.json`,
  `msd-after-fallback.json`, `msd-after-target.log`, `msd-fallback-tests.log`
  and `/tmp/opencode/msd-verification/20261026T194236-ab492c2-full`.
  **Final approved-golden verification (2026-10-27, measured):** full script
  again reports 99 passed, 0 failed, 2 ASE skips; post `analyze all` passes and
  prep is skipped (ASE absent). Forced NumPy reports 97 passed, 0 failed,
  4 skips. Evidence: `/tmp/opencode/msd-golden-verification/20261027T010307-64a6084-full`
  and `/tmp/opencode/msd-golden-fallback-tests.log`.
- **Physical interpretation check (2026-10-27, measured/inferred):** regular
  trajectory frames span step 100 through 3587. The NPT MD ends at step 2100;
  later frames are zero-temperature box/position minimization, not elapsed MD
  time. Fe_up/O MSD at the MD endpoint is 0.1631937540 / 0.1544326557 Å²;
  the final relaxed endpoint is 0.0746239928 / 0.0499072529 Å² (RMS displacement
  0.273 / 0.223 Å). These are plausible localized displacements, not certified
  equilibrium 1200-K vibration amplitudes or evidence of diffusion. Four of the
  64 Fe_up IDs wrap across z; the uncorrected z contribution alone is
  17.41704714 Å² versus 0.01910076 Å² after MIC. MD displacement components
  between saved frames stay below 0.021 of the box length (whole saved series),
  consistent with the adjacent-frame MIC sampling assumption. NPT box changes
  and subsequent relaxation also contribute to the reference-relative MSD.
  Evidence: `/tmp/opencode/msd-physics-assessment.json`.
- **Time-axis warning (measured):** `run_md.lammps` specifies metal units and
  timestep 0.001 ps = 1 fs, whereas dump-only shell heuristics currently choose
  0.25 fs. This scales plotted time by a factor of four, not the MSD magnitude.
  Run-derived timestep handling remains separate work; a correct timestep must
  not be used to turn minimizer iteration numbers into physical time either.
- **Limits:** PHYS-4 name/group resolution, run-derived units and GEN-3 triclinic
  reader geometry remain separate work. This fix rejects malformed supplied
  bounds but cannot restore tilt already discarded by the existing parser.

The original plan combined both fixes before rebaselining. Per-axis unwrap and
shell routing subsequently landed in PR #8. This branch completes ID tracking
first (`64a6084`), then explicitly tests bulk PBC and rebaselines the golden
(`c9eeb37`), without duplicating the already merged unwrap implementation.

### PHYS-1 · P1 · Bulk MSD must unwrap all periodic axes — `done (c9eeb37; local)`
- **Where:** `lammps_post/analysis.py::analyze_msd` and the caller in
  `shell.py::_analyze_msd`.
- **Current state:** PR #8 introduced per-axis `pbc` and shell routing; collected
  behavior tests and the maintainer-approved bulk golden complete the item.
  The public slab default is preserved for callers that pass no metadata.
- **Evidence (measured):** the old bulk-fixture golden used the slab default and
  ended at **17.47 Å²**. Explicit xyz unwrap gives **0.074624 Å²** and is now
  recorded by `msd_FeUp`. O MSD is unaffected (0.049907 Å² in both cases).
- **Fix direction:** retain the explicit per-axis `pbc` argument. The shell
  prints its choice and currently prioritizes dump flags → input `boundary` →
  `surface_z` fallback, matching RDF. No deprecated `z_pbc` MSD alias is needed.
- **Repro:** collected in `tests/test_msd.py::test_msd_bulk_z_crossing_and_explicit_slab`;
  also covered by `tests/test_periodicity.py::test_msd_unwraps_z_only_when_periodic`.
- **Done when:** the repro passes. A synthetic `p p f` case in the same test module
  shows that z is *not* unwrapped when z is non-periodic (no dependency on TEST-3).
  The MSD goldens are re-baselined in the PR's dedicated commit (TEST-2 rules).

### PHYS-2 · P1 · MSD reselects atoms by type each frame (ACE spin swaps) — `done (64a6084; local)`
- **Where:** `analysis.py::analyze_msd`.
- **Evidence (measured):** two static atoms with swapped types gave MSD 16.0 Å²
  before the fix and give zero afterwards. The spin fixture now uses all 337
  frames instead of silently skipping 305 population-changing frames.
- **Implementation:** select IDs at frame 0, then index by ID. Missing tracked
  IDs raise with timestep/ID details rather than hiding an unwrapping gap.
- **Repro:** collected in `tests/test_msd.py::test_msd_tracks_ids_through_type_swap`.

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

### GEN-6 · HPC site profiles — `deferred (maintainer: early-to-mid November 2026 or later)` (after HPC-1)
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
