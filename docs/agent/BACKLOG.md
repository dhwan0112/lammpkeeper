# Agent backlog

Single source of work items for agent sessions. **One item per session.**
Status: `open` → `in-progress (branch)` → `done (PR/commit)`. Priorities: P1 =
wrong results or data loss, P2 = misleading or fragile, P3 = docs or enabler.
Evidence labels follow pstack: *measured* / *inferred*.

Origin: Codex review + Claude cross-check, 2026-10-20 (branch `parser-streaming`).
Revised the same day after the first Cursor read-only audit (P0): MSD items merged,
forward dependencies removed, DOC-2 added.
Older open decisions live in `MIGRATION.md` → "Issues found by the end-to-end run".

## AUDIT-20261027 · P1 · Whole-code audit corrections — `done (PR #15, merged 2026-10-27)`

The maintainer requested all reported findings be fixed on 2026-10-27. This is
one bounded audit-remediation item, not the GEN architecture migration. Work is
split into independently tested source areas; no fixture or thesis tag changes,
real LAMMPS runs, HPC submissions or site-profile changes are authorized here.

- **Workflow:** preserve canonical ACE analysis labels on input load; invalidate
  dependent caches/surfaces/mass on load, unload and metadata changes; honor
  species unions throughout; reliable batch/one-shot failure and quit handling;
  paths with spaces and noninteractive plotting.
- **Analysis:** correct same-species and variable-N/V RDF normalization and all
  PBC axes; ID-aligned penetration histories without silent frame loss; honor
  surface percentile and species sets.
- **I/O:** log warnings/reset stages/minimization separation; data section/style
  integrity; input includes, variables and hybrid mappings; reject unsupported
  cells/units visibly; retain long labels and backend parity; bounded reader
  validation, identity precision and subscriber/cache lifetime regressions.
- **References/plots:** correct magnetite geometry, safe CIF symmetry handling,
  native pressure units, explicitly qualified slab scaling and valid uptake t50.
- **Prep:** refuse unsafe skew geometry, stale builds and failed oxygen placement;
  validate layers and processor grids; nonnegative ACE durations; isotropic O2
  initialization; exclusive failure archives and permission-preserving copyback.
- **Verification:** reject empty generated output and false success in the local
  verifier. Register all new regression modules in both execution paths.

**Golden gate:** maintainer explicitly approved the RDF-only rebaseline during
this session: `rdf_FeUp_O` hash `46e63f7e15ac805b` → `129e29ad92fc7d6f`,
conditional on matching the independent explicit-pair calculation. Peak
55.8132059165 → 55.8130906709; each frame uses its own N_a*N_b/V before
arithmetic averaging. MSD goldens, fixtures and `v1.2.0-thesis` remain unchanged.
This must be applied in a dedicated golden commit, not hidden in source fixes.

**Done when:** each reported case has a collected regression and independent
expected result; targeted fail-before/pass-after evidence is retained; full local
verification passes in the available rich and NumPy environments (explicit skips
listed). The maintainer explicitly approved feature-branch push and PR creation
after final verification in that session. Initial publication excluded merging;
the maintainer subsequently requested merge explicitly and PR #15 was merged
as `703185b`. Direct main pushes remain gated.

## DOC-ALL · P3 · English maintenance comments across every source file — `done (PR #16, merged 2026-10-27)`

Maintainer explicitly requested every code file, then selected **all files,
functions/classes and major logic** (not every execution line), in **English**.
The branch is based on verified audit PR #15 (`f62f0a4`), not a merge to main.

- Cover all 63 tracked Python/Rust/Shell/TOML source/build files; maintain an
  explicit inventory in `docs/agent/COMMENT_COVERAGE.md`. JSON configuration is
  data (comments are not legal JSON); fixtures, binaries, lockfiles, generated
  outputs and user-owned untracked files stay untouched.
- Explain contracts, units, identity/PBC assumptions, failure propagation and
  non-obvious branching; avoid comments that merely repeat an assignment.
- Add useful documentation to every function/class, including private/nested
  helpers and regression tests; lambdas are explained at their call sites.
- No executable changes, generated template-string changes or numeric rebaseline.
- **Done when:** inventory is complete, every Python function/class has a
  docstring, normalized executable Python AST / Rust-Shell noncomment lines /
  parsed TOML agree with the baseline, and full verification still passes in
  the rich, forced-NumPy and default environments with explicit skips.
- Maintainer explicitly approved push and a separate stacked PR based on audit
  PR #15 after verification. The subsequent explicit merge request was completed:
  PR #16 was retargeted to main after PR #15 and merged as `4db45c4`.

## REVIEW-20261028 · P3 · Whole-source re-review and English annotations — `done (PR #21; annotations only, runtime findings open)`

Requested after GEN-3 by the maintainer: re-review all work to date and retain
maintenance comments across all code. Baseline: merged main `75f5e66` (PR #20).

- Inventory all 78 tracked Python/Rust/Shell/TOML source/build files: 73 Python
  modules and 978 function/class definitions, including nested helpers/tests.
- Review contracts, major logic, scientific assumptions, provenance, lifecycle,
  failure paths and independent-oracle limitations. Keep comments in English;
  explain why rather than repeat every execution line.
- Strengthen missing/stale/unclear annotations without changing executable code,
  assertions/expectations, generated strings, fixtures, mappings or lockfiles.
  Existing adequate comments may remain; record every reviewed file explicitly.
- Record potential defects with source evidence and reproduction status; do not
  disguise runtime fixes or unsupported claims as annotation-only changes.
- **Done when:** exhaustive inventory/review, documented findings and English
  module/function/class coverage; normalized Python AST, Rust/Shell noncomment
  code and parsed TOML match the baseline; full verifier passes in expanded/native,
  forced NumPy and default environments with named skips. No actual LAMMPS/HPC,
  native rebuild, physics rebaseline or architectural approval is implied.
- **Measured result:** all 78 targets reviewed, English documentation present for
  all 73 modules and 978 definitions; 56 files strengthened, 22 adequate existing
  annotations retained. All baseline normalized semantics/settings preserved.
  Parent full verifier: expanded/native **393/0/0**, forced NumPy **387/0/6**
  native-only skips, default **377/0/16** ASE/Matplotlib skips. Expanded post/real
  plots and prep/script smoke pass. Exact commands, named skips, per-file inventory
  and known open defects: `docs/agent/REVIEW-20261028.md`.

### Review follow-ups — open, not fixed by annotations

Priorities below are review judgments. Concrete findings and parent/worker
reproduction status are distinguished in `docs/agent/REVIEW-20261028.md`.
These are separate future items (one per session/PR); no runtime fix, golden
change or human-gated generated input/structure/job change is approved by listing
one here. Reproduce under collected tests and show fail → pass before shipping.
The P1 input-integrity/data-loss risks deserve attention before further generality.

| Item | Priority / source finding | Done when |
| --- | --- | --- |
| REV-IO-1 · done (PR #22) | P1; F-IO-1, malformed thermo rows silently dropped | Complete: fail → pass; 12 collected regressions; numeric-leading bad rows reject with path/line/header/row before block selection; valid logs/goldens unchanged. Full verifier **405/0/0** native, **399/0/6** forced NumPy, **389/0/16** default. See `docs/agent/REV-IO-1.md`. |
| REV-REF-1 · done (PR #23) | P1; F-REF-1, CIF occupancy ignored | Complete: fail → pass; 20 new regressions; exact nominal-one occupancy and conservative disorder guards reject unsupported/ambiguous site metadata before filtering/expansion. Supported unit-site compatibility preserved, no weighting model. Full verifier **425/0/0** native, **419/0/6** forced NumPy, **408/0/17** default. See `docs/agent/REV-REF-1.md`. |
| REV-PREP-1 · done (PR #24) | P1; F-PREP-3, successful copyback follows output symlinks | Approved copy-behavior safety fix; no real HPC. Fail → pass; 19 new regressions; parent targeted **51/0/0**. Full verifier **444/0/0** native, **438/0/6** forced NumPy, **427/0/17** default. Full preflight preserves colliding links/targets through copyback, scratch, modes and solver status. Copyback-only limits and separate early logging risk: `docs/agent/REV-PREP-1.md`. |
| REV-ANALYSIS-1 · implemented, PR review pending (`fix/rev-analysis-1-charge-integrity`) | P2; F-ANALYSIS-1, nonfinite selected charges | Selected NaN/Inf rejects visibly; no atom dropping/denominator change; pure nonspatial path and finite results preserved. 18 new regressions; full native **462/0/0**, forced NumPy **456/0/6**, native pytest **462 passed**. See `docs/agent/REV-ANALYSIS-1.md`. |
| REV-ANALYSIS-2 | P2; F-ANALYSIS-2, missing-z region ignored | An explicit charge/OR region without a z column cannot silently become a global analysis; collected missing-column and valid-region tests pass. |
| REV-ANALYSIS-3 | P2; F-ANALYSIS-3, invalid density range/bins | Equal/reversed/nonfinite ranges and invalid bin counts fail before histogram normalization; valid analytic profiles/goldens unchanged. |
| REV-ANALYSIS-4 | P2; prior review, float32 RDF backend disagreement | In-box cutoff-edge pairs agree across SciPy/fallback using an independent exact represented-input oracle; no spurious pair or golden rebaseline. Parent reproduced 0 versus nonzero bin. |
| REV-ANALYSIS-5 | P2; prior review, nonfinite selected coordinates | OAR/penetration/density reject or visibly diagnose selected NaN/Inf z; no silent denominator dilution or missing density population. Parent reproduced OAR 0.5 and one-count density for `[1, NaN]`. |
| REV-IO-2 | P2; F-IO-2, active-stream mutation | Changing a source during iteration is detected before publishing changed-frame atoms/species; unchanged stream/index/cache behavior preserved. |
| REV-IO-3 | P2; F-IO-3, projection hides row corruption | Raw row width is validated before projection on NumPy and real native paths, including layouts without id/type/element. |
| REV-IO-4 | P2; prior review, dump comment parsing | Retained numeric `3#CORRUPTED` rejects without silent NumPy repair; native/NumPy agree on supported text labels containing `#`. |
| REV-IO-5 | P2; prior review, extreme thermo-step precision | Signed-64-bit step increments remain exact or reject visibly before a valid elapsed timeline is published; parent measured adjacent 2**53 counters collapsing to zero elapsed steps. |
| REV-IO-6 | P2; prior review, malformed PBC becomes authoritative | Invalid dump boundary tokens reject visibly; any documented single-letter compatibility maps consistently. Parent measured `p p f` becoming all nonperiodic and half-periodic flags accepted. |
| REV-REF-2 | P2; F-REF-2, incomplete default reference shells | Unsafe cutoff/replication raises or a justified complete-image policy recovers independent alpha-Fe outer coordination 6, not 3; no wrong-value rebaseline. |
| REV-REF-3 | P2; F-REF-3, malformed symmetry accepted | Unsupported/malformed operators and component counts reject visibly; valid built-in/P1 geometry independently preserved. |
| REV-REF-4 | P2; skew-reference MIC / invalid-cell limits | Explicitly validate/reject unsupported skew/cell cases or obtain approval for a bounded exact-geometry extension; never silently clip invalid geometry. |
| REV-PREP-2 | P2; F-PREP-2, boundary/protocol mismatch | With required generated-input approval, incompatible reflecting-z/placement boundary choices reject visibly; default protocol unchanged. |
| REV-PREP-3 | P2; F-PREP-1, ASE/manual reproducibility | Record dependency path and, only with generated-structure approval, define/test parity; preserve Fe/O relative coordinates and cross-FF equality. |
| REV-PLOT-1 | P2; F-SESSION-1, wrong RDF reference pair | Hyphenated/generic cached pairs select matching references per curve; no Fe-O fallback for unrelated pairs; real metadata and mock dispatch regressions. |
| REV-PLOT-2 | P2; negative-z/generic structure and threshold labels | Define domain-versus-generic plotting constraints, retain all intended z data and show the actual analysis threshold without inventing species. |
| REV-UI-1 | P2; F-CLI-1, empty fallback table | Header-only and empty tables render or reject deliberately on both Rich/plain paths; no TypeError from scalar max. |
| REV-UI-3 | P2; prior review, explicit output failures exit zero | Missing cached CSV export and unsupported requested pressure plot return failure in batch/one-shot; require intended artifact, distinguish deliberate plot-all skips. |
| REV-SESSION-1 | P2; prior review, invalid physical overrides | Reject nonfinite surface and nonfinite/nonpositive timestep before state/cache mutation; retain prior valid state. Parent reproduced successful finite OAR from NaN/Inf surfaces and negative/NaN MSD time. |
| REV-SESSION-2 | P2; prior review, spin ignores active species override | Respect the approved active spin selections or visibly reject noncanonical maps; preserve canonical FF conventions. Parent measured Fe_up={2} but spin counts type 1. |
| REV-SESSION-3 | P2; prior review, stale scientific cache publication | Detect/invalidate changed source before cached plot/export, or explicitly identify an immutable provenance-bound snapshot; parent measured stale actual Agg plot despite reader mutation rejection. |
| REV-VERIFY-1 | P2; F-VERIFY-2, unchecked temp creation | Fault-injected mktemp failures stop before empty-HOME/unisolated work; retained evidence and safe cleanup remain tested. |
| REV-UI-2 | P3; F-SESSION-2, recipe alias mismatch | Saved charge/spin/etc recipes are found by advertised redo/edit command names without breaking existing names. |
| REV-OPS-1 | P2/P3; F-CLI-2 plus prior-review hosted-inline loss | Bound startup reads and isolate standalone callbacks; first hosted inline child construction/dispatch must preserve outer unsaved/persisted history, including exceptions. Parent measured menu history replaced by post history on `post info`. |
| REV-VERIFY-2 | P3; F-VERIFY-1, evidence collisions | Concurrent same-second/SHA/mode runs retain independent logs/summaries; no cleanup of retained evidence. |
| REV-VERIFY-3 | P2; R-VERIFY-1, failed evidence retention still PASS | Fault-injected required evidence copy/write failures produce a nonzero verifier result; no PASS with missing retained `post-summary.txt`. Parent measured exit 0 after denied evidence copy during prior-work review; see `PRIOR-WORK-REVIEW-20261029.md`. |
| REV-GEOM-1 | P3; F-CORE-1, near-face wrapping | Decide/document a floating-point face convention and test strict range/idempotence where promised without changing physical image selection silently. |
| REV-TEST-1 | P3; F-CORE-2, finite oracle bounds | Independently justify finite image ranges; interiority alone is not a completeness argument; production geometry is not used as its own oracle. |
| REV-PREP-4 | P3; F-PREP-4, Masses inspection | Prep's metadata inspector reads conventional blank-separated Masses sections without changing structures/presets. |
| REV-REF-5 | P3; CIF case/seam behavior | Decide supported case-insensitive loop parsing and metric/seam deduplication limits with independent tiny-CIF tests and visible rejection outside scope. |
| REV-PREP-5 | P2; parent-reproduced in prior review, early logging symlink | After separate generated-script approval, prevent early `tee -a "$RUNLOG"` following a `run.log` symlink before copyback preflight; retain normal logging and scratch recovery. Parent measured target append with exit 0 and scratch removed. Not a copyback-preflight bypass. |
| REV-PREP-6 | P3; prior review, nondefault API O2 endpoints | After generated-structure/protocol approval, validate all gas endpoints against initial wall/integration regions. Parent measured accepted bond=3/vacuum=3.1 placing one O outside every static integration group; standard default bond not implicated. |

## Suggested order

**Independent prior-work review (2026-10-29, maintainer requested):** pause GEN-2
implementation and independently inspect prior Sol-authored work. Model authorship
is not established by Git, so current main source is reviewed as a conservative
superset, without assigning authorship. Track inventory, repros and known/new
findings in `docs/agent/PRIOR-WORK-REVIEW-20261029.md`. GEN-2 proposed ADR remains
on `gen/gen-2-explicit-metadata` (`e019dd7`), awaiting approval; this review does not
accept it or authorize unrelated fixes.
Review completed with **11 new reproduced items**, an additional hosted-inline
case under REV-OPS-1 and several reconfirmed known issues: **33 open review items**
in total; published as PR #25. Parent reran all priority probe groups; full baseline remains **444/0/0**.
Silent scientific/input defects and stale-result publication should be addressed
before generalization resumes. Detailed measured values and limitations are in
the review report; no runtime fix or golden change is part of this review.

**Scheduling update (maintainer, 2026-10-26):** defer actual HPC submissions,
site-dependent validation and HPC site-profile work (GEN-6) until early-to-mid
November 2026 or later, when the maintainer is available; this is not an
automatic restart date. HPC-1's local safety fix is done, but real-cluster
execution remains unverified. In the meantime prioritize local analysis,
synthetic regressions and replay of committed trajectories. No new HPC jobs or
site changes are part of this work.

**Shipping preference (maintainer, 2026-10-27):** routine verified feature work
should be completed through push, PR creation and merge, not left at a local
branch. Keep separate logical changes in separate PRs. Physics golden changes,
ADR decisions and other human gates still require their specific approvals;
failed verification or non-mechanical conflicts must be resolved before shipping.

**Review checkpoint (2026-10-28):** original P1 findings REV-IO-1 and REV-REF-1
are merged; REV-PREP-1 is fully verified and published as PR #24. After this item,
21 original follow-ups plus the separately recorded early-logging risk remain
open. Resume GEN-2 through the existing architecture gate in a separate session;
P2 scientific-ingestion/reference/display risks are not certified by resolving
P1. Continue recording per-item decisions, exact verification/skips and PR links.
Actual HPC/site work remains deferred as above.

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
- **Status:** done (PR #12, merged 2026-10-27 as `7839385`): PHYS-2 in
  `64a6084`; approved PHYS-1 golden rebaseline in dedicated commit `c9eeb37`.
  REL-0 is complete; no fixtures were modified. The maintainer approved both
  the numerical correction (after physical-context review) and subsequent
  push/merge. Final pre-ship verification again passed 99 tests with 2 ASE skips.
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

### PHYS-1 · P1 · Bulk MSD must unwrap all periodic axes — `done (PR #12; c9eeb37)`
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

### PHYS-2 · P1 · MSD reselects atoms by type each frame (ACE spin swaps) — `done (PR #12; 64a6084)`
- **Where:** `analysis.py::analyze_msd`.
- **Evidence (measured):** two static atoms with swapped types gave MSD 16.0 Å²
  before the fix and give zero afterwards. The spin fixture now uses all 337
  frames instead of silently skipping 305 population-changing frames.
- **Implementation:** select IDs at frame 0, then index by ID. Missing tracked
  IDs raise with timestep/ID details rather than hiding an unwrapping gap.
- **Repro:** collected in `tests/test_msd.py::test_msd_tracks_ids_through_type_swap`.

### PHYS-4 · P1 · ACE "Fe" resolves to Fe_down only; unknown species are silent — `done (0777de3)`
- **Status:** implemented in `0777de3` on `fix/phys-4-species-groups`.
  The maintainer requested PR/merge completion on 2026-10-27. O2 PR #13 is
  integrated before shipping, retaining both changelog sections and both
  registered test-module lists; source files merged automatically without
  numerical edits.
- **Combined verification (measured, 2026-10-27):** PHYS-4 plus merged O2 fixes:
  167 passed, 0 failed, 2 ASE skips; post `analyze all` passes, prep skipped.
  Forced NumPy mode: 165 passed, 0 failed, 4 skips (ASE plus native tests).
  All four new test modules are collected and all existing golden values and
  fixtures remain unchanged. Evidence:
  `/tmp/opencode/phys4-o2-integration/20261027T154831-1889ba9-full` and
  `/tmp/opencode/phys4-o2-fallback-tests.log`.
- **Scope (2026-10-27):** bug fix begun locally after MSD PR #12 merged. Add
  set-valued name resolution in `common/mapping.py`, retain canonical type/FF
  tables and all legacy mapping functions, route MSD/RDF shell selection through
  it, and add type-set RDF support without changing singleton numeric goldens.
  No module moves, new SpeciesMap architecture, fixture changes or HPC work.
  New group/display metadata must not rename public output files.
- **Reproduction (measured):** 32 new selection tests initially had 4 passes
  and 28 failures; 3 plot-plumbing tests had 1 pass and 2 failures. A synthetic
  `Fe` MSD returned 9 Å² (only the second channel) instead of the union's
  5 Å². An unknown species silently returned the all-atom 10/3 Å².
- **Implementation:** additive set-valued helpers in `common/mapping.py` merge
  explicitly repeated labels and declared groups, without guessing underscore
  prefixes. The canonical ACE preset adds the Fe union only while its member
  labels match the supplied system map. Custom labels take precedence; the
  original element slots, tables and conversion APIs are unchanged.
  MSD and RDF use these sets, reject unknown names/malformed arguments, and
  invalidate only the attempted target cache. RDF singleton selections preserve
  existing arithmetic and result keys. Display names and raw cache/file names
  remain separate; plot title/path tests use a fake backend, not real rendering.
- **Verification (measured, 2026-10-27):** targeted selection, plot-plumbing and
  legacy mapping suites: 46 passed. Full verify-lkpr: 139 passed, 0 failed,
  2 ASE skips; post `analyze all` passed, prep skipped (ASE absent). Forced
  NumPy mode: 137 passed, 0 failed, 4 skips (ASE plus native-only tests).
  Existing numeric goldens and all fixtures are unchanged. SciPy tree/fallback
  RDF equality covers disjoint, equal and partially overlapping type sets;
  a tiny disjoint-group system also checks analytic counts/normalization.
- **Fixture cross-check (measured):** `Fe` MSD changes from the erroneous
  Fe_down-only 0.04994240109073442 to the combined-cohort
  0.058169598336485516 Å², exactly matching direct selection `{1, 2}`.
  Individual Fe_up, Fe_down and O results are unchanged. Group Fe–O RDF matches
  independently flattened type labels with max error zero. Unknown `Fx` and
  malformed `Fe-O-bad` now raise instead of silently returning data.
- **Evidence (local):** `/tmp/opencode/phys4-before.json`, `phys4-after.json`,
  `phys4-target-after.log`, `phys4-label-before.log`, `phys4-fallback-tests.log`
  and `/tmp/opencode/phys4-verification/20261027T142711-7839385-full`.
- **Review follow-up (measured/static, separately labeled):** independent static
  review found malformed-option ordering could invalidate a default cache
  rather than the explicitly requested target, and custom groups could borrow
  an unrelated preset display name. Four added regressions failed before the
  fixes and pass after them; one additional precedence regression also passes.
  Option scanning now identifies an unambiguous requested target before error
  handling; distinct conflicting targets raise without erasing either cache.
  Preset display names require exact canonical type-set equality. Follow-up
  static review found no remaining blocker; executable full-suite results are
  the measured verification above. Native/NumPy fixture measurements also
  match exactly (`/tmp/opencode/phys4-after-fallback.json`).
- **Limits:** ASE, matplotlib, pandas, MDAnalysis and pytest are unavailable;
  no real plotting, real LAMMPS execution or HPC submission was verified. This
  selection fix does not change legacy RDF same-species normalization,
  last-frame population/volume normalization, x/y PBC assumptions, timestep
  inference or triclinic handling. Those must not be inferred validated from
  the selection regression results.
- **Where:** `shell.py::_analyze_msd` (`inv[v.split('_')[0]] = k`) and the RDF pair
  map (`for short in [n.split('_')[0], n]`).
- **Original evidence (inferred in review, reproduced above):** ACE `Fe` selected
  only type 2. `msd_Fe.png` and default `Fe-O` RDF were Fe_down-only; unknown MSD
  names became all atoms, and unknown RDF names silently became default types.
- **Resolution:** names now resolve through `common/mapping.py` to *sets* of
  types (`Fe` → {1, 2} for canonical ACE). Analysis functions accept type sets;
  unknown names raise errors listing valid names.
- **Done when:** tests cover `Fe`, `Fe_up`, `Fe_down`, `O`, and an unknown name, for
  both MSD and RDF. Labels say "Fe (all spins)" vs "Fe↑".

### PHYS-3 · P1 · O₂ detection misses pairs across periodic boundaries — `done (46ccd56)`
- **Completion:** periodic candidate/PBC fix in `46ccd56`, coupled global
  pairing fix in `d402599`. Shipped through PR #13 and merged on 2026-10-27
  as `4c2bd24`, following the maintainer's subsequent merge approval.
- **Scope (2026-10-27):** coupled PHYS-3/PHYS-5 fix on a separate branch from
  `main` after MSD PR #12. The original O2 branch excluded the separate PHYS-4
  changes; the following test counts describe that isolated verification.
  Initial approval covered verification/push; later approval completed PR #13.
  Use explicit per-axis PBC for periodic candidate search and MIC, preserve
  legacy slab defaults and output keys, support explicit type sets, and use
  deterministic global shortest-first pairing. No fixtures/goldens, module
  layout, LAMMPS inputs, job scripts or HPC sites are changed.
- **Reproduction (measured):** the 27 collected O2 regression tests initially
  reported 4 passed, 23 failed. The original boundary-straddling pair counted
  1 molecule at n=2 but 0 at n=21. The original four-atom chain counted 2 alone
  but 1 after adding 17 isolated atoms.
- **Implementation:** PHYS-3 commit `46ccd56` extends `_rdf_candidate_pairs`
  with optional explicit PBC; old RDF callers retain x/y plus optional-z
  semantics. The shell passes `_periodicity()` metadata and clears only the
  target dissociation cache before computation. Selected types may be an integer
  or type set; invalid settings/bounds/selected coordinates or IDs fail visibly.
  Empty selected frames are retained with zero counts/fractions, not dropped.
  PHYS-5 supplies one global shortest-first assignment after shared MIC and
  strict cutoff filtering for both backends. IDs or canonical coordinates
  provide deterministic tie order; instantaneous counts allow population/type
  changes and do not claim to track the same molecules through time.
- **Physical justification:** the chain's central 0.5 Å separation is shorter
  than its outer 1.0 Å separations. The documented shortest-first greedy rule
  therefore assigns the center pair and leaves two unpaired ends: 1 pair in
  both populations. This is a geometric consistency test, not a claim that the
  synthetic chain is chemically realistic or that greedy assignment maximizes
  molecule count. No golden values were replaced to make the tests pass.
- **Verification (measured, 2026-10-27):** 28 focused tests pass with no skips,
  including all 8 PBC combinations, actual periodic SciPy calls, forced brute
  force, strict cutoff/ties, row permutations, zero/singleton populations,
  read-only input arrays, mixed type groups and independent image enumeration
  plus greedy assignment on random systems of 7/33 atoms. Full verify-lkpr:
  127 passed, 0 failed, 2 ASE skips; post `analyze all` passes, prep skipped.
  Forced NumPy parser mode: 125 passed, 0 failed, 4 skips (ASE plus 2 native
  tests). SciPy candidate and forced-candidate-fallback outputs match; native
  and NumPy fixture measurement JSONs also match exactly.
- **Preservation (measured):** all existing RDF/MSD/metadata/spin goldens pass
  unchanged. The regular fixture still gives zero geometric O2 pairs in all
  350 frames with fingerprint `48f3a1644e01dcc9`, for both the legacy slab
  default and explicit full PBC. Fixtures, thesis tag, inputs and job scripts
  remain untouched; the lower isolated test total than PHYS-4 is because that
  separate branch was deliberately excluded, not because tests were removed.
- **Evidence (local):** `/tmp/opencode/o2-before.json`, `o2-after.json`,
  `o2-after-fallback.json`, `o2-target-after.log`, `o2-fallback-tests.log` and
  `/tmp/opencode/o2-verification/20261027T152104-46ccd56-full`.
- **Review:** independent read-only physics/callsite review found no blocker;
  runtime verification above was run independently by the orchestrator. A
  nonblocking reference-oracle limitation for no-ID coordinate tie keys was
  corrected, and an extra test now covers shifted periodic images and row
  permutations without IDs, against canonical-coordinate image enumeration.
- **Limits:** ASE, matplotlib, pandas, MDAnalysis and pytest unavailable; no
  real plot rendering, real LAMMPS execution or HPC submission verified. Shape
  validation rejects retained triclinic bounds, but cannot recover tilt already
  discarded upstream (GEN-3). Time-unit inference and MD/minimization stage
  interpretation remain separate issues; unpaired atoms are not certified
  chemically dissociated species.
- **Where:** `analysis.py::detect_o2_dissociation` (cKDTree without `boxsize`).
- **Evidence (measured):** before the fix the same boundary-straddling O₂ gave
  1 molecule at n_O = 2 and 0 at n_O = 21; after the fix both give 1.
- **Fix direction:** reuse `_rdf_candidate_pairs` (periodic tree, z handled per PBC).
  Apply MIC in z too when z is periodic.
- **Repro:** collected in
  `tests/test_o2_periodicity.py::test_o2_detected_across_x_boundary_on_tree_path`.

### PHYS-5 · P2 · O₂ pairing algorithm differs between n ≤ 20 and n > 20 — `done (d402599)`
- **Where:** same function. The old slow path did per-atom nearest-first while
  the tree path did global shortest-first; both now use the global rule.
- **Evidence (measured):** a 4-O chain previously gave 2 molecules alone and 1
  with 17 distant atoms added. Both now give 1, including forced fallback.
- **Implementation:** one deterministic global shortest-first assignment, backed
  by equality, independent image-reference, cutoff, tie and conservation tests.
- **Repro:** collected in
  `tests/test_o2_pairing.py::test_o2_count_independent_of_total_o_count`.
- **Coupling with PHYS-3:** keep PHYS-3's periodic candidate stage, and PHYS-3's repro
  must still pass. Shipping PHYS-3 and PHYS-5 as one PR (two commits) is acceptable.

### TEST-2 · Golden re-baseline rules (not a separate session)
- Applied inside the PR that changes the value (MSD PR; PHYS-3/5 if `o2` goldens
  are ever added). PHYS-4 extends shared name resolution and numeric type-set
  selection; existing goldens call `compute_rdf`/`analyze_msd` with type ints,
  so they must not move. If they do, stop and investigate.
- Each changed key: a dedicated `test(golden)` commit with reason, old/new summary
  values, an independent check, and a behaviour test (static-crystal MSD ≈ vibration
  only). **Human gate.**

### TEST-3 · P2 · No slab (`p p f`) reference case — `done (PR #17; source 39f0e95)`
- **Why:** the committed ACE trajectory is bulk. Existing small unit systems
  cover many slab paths, but there is no reusable, serialized slab reference
  exercised end to end through parsing, shell metadata and multiple analyses.
- **Scope:** a deterministic stdlib generator under `tests/` creates a 16-atom,
  six-frame `pp pp ff` dump and explicit units/timestep metadata in temporary
  directories. No `tests/fixtures/**`, production input, golden or runtime
  analysis implementation is changed. This is not the undecided GEN-8 system.
- **Known answers:** pairs straddle both x/y boundaries; two z-edge atoms are
  not periodic neighbors; fixed substrate MSD is zero; translation/adsorption
  and a deliberately nonphysical wall-jump probe have analytic displacements,
  counts, RDF bins and first-below-surface observations.
- **Done when:** the generator is reproducible and collected tests match
  independently enumerated images/counts and analytic values through serialized
  readers, both shell load orders, shared/uncached processing and available
  native/NumPy/SciPy paths. Optional rendered plots are checked when available.
  Full verification and existing Fe-O goldens pass unchanged; all skips are
  explicit. Real LAMMPS/HPC and equilibrium/kinetics certification remain excluded.
- **Measured result:** rich/native **261 passed, 0 failed, 0 skipped**;
  forced NumPy **258/0/3** (native-only skips); default Python **246/0/15**
  (four ASE and eleven Matplotlib skips). Required rich-environment CLI plots,
  prep artifacts and job syntax pass. Independent review and fault injection
  check false-pass risks. Full evidence and limits: `docs/agent/TEST-3.md`.

### DOC-1 · P3 · Spin docstring contradicts itself — `done (AUDIT-20261027)`
- **Where:** `analysis.py::analyze_spin_evolution`. "~1/3 → … 8 tetrahedral Fe↓ : 16
  octahedral Fe↑" — 16/24 is 2/3.
- **Done when:** the docstring states which ACE type is majority in the fixture
  (Fe 64 / Mn 128) and the reference for that assignment.
- **Completed in the audit correction:** docstring states type-1 Fe_up = 64,
  type-2 Fe_down (Mn proxy) = 128, references the shared convention/potential,
  and distinguishes measured fixture populations from a site/phase assignment.
  Plot guides show encoding-dependent 1/3 and 2/3 populations without claiming
  that a population ratio alone establishes magnetic order. Spin numbers and
  mapping conventions are unchanged.

### DOC-2 · P3 · Stale design docs and docstrings — `done (PR #18; source 382ceee)`
- **Evidence (measured, Cursor P0 audit):**
  - `MIGRATION.md` §"Stage 1 — dispatcher-only (current)": the branch is well past Stage 1.
  - "Planned" still lists the `dump_modify element` reverse-map fix, which is marked FIXED in Step C.
  - "Known invariants" still describes the atom-count O heuristic as the current path.
  - Its 3-space indentation note contradicts the code (4 spaces everywhere).
  - `common/mapping.py` docstring (about lines 18–19) calls the heuristic "still-open".
  - `lammpkeeper/cli.py` module docstring is half-updated (describes Stage 1 only).
- **Done when:** each stale passage is corrected or marked historical, with no
  behaviour change. Tests unchanged.
- **Correction scope (2026-10-28):** current status is separated from Stage-1/2
  and old LAMMPS run records; completed reverse-map/fair-comparison/short-run
  fixes are no longer pending. Four-space style, remaining warned count/FF
  inference, supported geometry and RDF/MSD semantics are explicit. CLI docs
  confirm unified shell/nonterminal routing and all three help subparsers;
  DOC-ALL had already removed much of the original Stage-1-only wording.
- **Measured static checks:** all 60 Python modules / 735 definitions retain
  Python 3.9 grammar and English docstrings; executable ASTs match main
  `625e070`, and non-docstring executable tokens match in both edited modules.
  Tests, fixtures, goldens, generated-template sources, build settings and
  accepted ADRs are unchanged. Independent review checked claims against source;
  its count-fallback wording finding was corrected without changing the parser.
- **Full verification on committed source `382ceee` (measured):** rich/native
  **261 passed, 0 failed, 0 skipped**; forced NumPy **258/0/3** (the three
  native-only checks); default Python **246/0/15** (four ASE and eleven
  Matplotlib checks). Rich/native and forced NumPy also pass required CLI
  analyses/plots, prep artifacts and job-script syntax. Default prep smoke
  explicitly skips without ASE. MDAnalysis/pytest execution and real
  LAMMPS/HPC remain unverified. Evidence directories (including named skips):
  `/tmp/opencode/lk-doc2-rich/20261028T003306-382ceee-full`,
  `/tmp/opencode/lk-doc2-fallback/20261028T003306-382ceee-full`,
  `/tmp/opencode/lk-doc2-default/20261028T003306-382ceee-full`.

---

## Phase 2: generalization (ADR-0001; each item opens with `/architect`)

Every GEN item must be **value-preserving on Fe-O** (same goldens) unless it
says otherwise, and must add made-up-label tests (`"A"`, `"B"`).

### GEN-1 · SpeciesMap: the system owns the type map — `done (PR #19; source 5ebcfed; ADR-0002 accepted)`
- **Starting point:** `common/mapping.FORCE_FIELDS` tied FF name → fixed Fe/O
  types; generic selections now live in `SpeciesMap`, with presets kept separate.
- **Target:** `core.SpeciesMap` with label → set of types, built from explicit
  sources in the ADR-0001/0002 order: manifest groups/provenance; type labels from
  input `pair_coeff` → data-file `Masses` comments → dump `element` → user fallback.
  Contradictory explicit labels warn and reject metadata application. ACE spin
  channels remain groups (`Fe` = {Fe_up, Fe_down}); `mapping.py` provides presets
  and legacy compatibility, not generic selection storage.
- **Done when:** PHYS-4 tests pass through `SpeciesMap`, and an `A`/`B` system
  resolves without any FF name.
- **Architecture approval (2026-10-28):** manual `/architect` equivalent and two
  independent read-only reviews exposed the former backlog/ADR precedence
  conflict. The maintainer approved the recommended contract in
  `docs/adr/0002-species-map-contract.md`: additive immutable API, ADR-0001 source
  order, explicit-conflict rejection, optional manifest groups/provenance and
  managed session lifetime. The target above now follows that approval; no
  numerical change, fixture edit or golden rebaseline was approved. A subsequent
  explicit approval preserves `set types` as a warned temporary manual analysis
  override, expiring on typed-source load/unload, not automatic user fallback.
- **Implemented:** immutable generic `SpeciesMap`; compatibility/preset adapters;
  Masses comments, lazy raw dump IDs/labels and schema-1 manifest groups/hash
  checks; source-owned transactional loading/unloading and active selection
  routing. A/B/X resolve without any FF argument. Explicit conflicts reject;
  unknown group references block analysis; source changes invalidate results.
- **Measured verification on committed sources `5ebcfed`:** rich/native
  **311 passed, 0 failed, 0 skipped**; forced NumPy **306/0/5** (native-only);
  default Python **296/0/15** (four ASE and eleven Matplotlib checks). Required
  rich/NumPy CLI plots, prep artifacts and script syntax pass. All existing
  tests/fixtures/goldens and numerical kernels stay unchanged. Pure-wheel core,
  legacy help and manifest group MSD pass; 65 modules / 831 definitions pass
  Python 3.9/docstrings. Full evidence, review findings and limits:
  `docs/agent/GEN-1.md`. Real LAMMPS/HPC, MDAnalysis and pytest remain unverified.

### GEN-2 · Explicit FF/system metadata instead of `detect_forcefield` heuristics — `open`
- **Now:** a charge column → ReaxFF; ≥ 3 types → ACE; 2 types → HDNNP.
- **Target:** read `pair_style` / `units` / `atom_style` from the input script or run
  manifest. The heuristic stays only as a last resort and prints what it guessed.
  Unknown FFs get `generic` with no domain defaults.
- **Done when:** a LJ or EAM trajectory is reported as such (or as `generic`), never
  as ACE/ReaxFF/HDNNP.

### GEN-3 · Box model with triclinic + PBC — `done (PR #20; ADR-0003 accepted)` (builds on PARSE-1)
- **Target:** `io.Box(lo, hi, tilt, pbc)`. Fractional transforms plus exact periodic
  lattice MIC/unwrap; fractional component rounding is not an exact skew-cell MIC.
  Until analyses support tilt, they raise an error on triclinic input instead of
  ignoring it.
- **Done when:** RDF and MSD of a synthetic triclinic cell match brute force over
  images, and orthogonal Fe-O goldens are unchanged.
- **Architecture approval (2026-10-28):** two independent read-only reviews and a
  measured fractional-rounding counterexample informed
  `docs/adr/0003-box-geometry-contract.md`. The maintainer approved immutable Box
  metadata, exact periodic-lattice MIC, additive opt-in readers, restricted
  Cartesian triclinic RDF and fixed-cell MSD, with unsupported consumers rejected
  visibly. No fixture/golden, generated prep/job/structure or FF mapping change
  was approved; completion requires the checks above.
- **Measured completion (2026-10-28):** exact image/RDF/MSD independent synthetic
  oracles and all unchanged Fe-O goldens pass. Parent full verifier: expanded
  environment/native **393 passed, 0 failed, 0 skipped**; forced NumPy **387/0/6**
  (native-only skips); default Python **377/0/16** (ASE/Matplotlib skips). Post
  analyses/real plots and prep artifact/script smoke pass in the expanded
  environment. External installed wheel: **81/0/1**, native-only skip. The five
  new modules add 82 tests. All 44 pre-existing tests/fixtures/golden files apart
  from runner registration remain byte-for-byte unchanged; thesis tag preserved.
  `docs/agent/GEN-3.md` records APIs, exact commands, named skips, evidence and
  unsupported scope. Real LAMMPS/HPC and MDAnalysis remain unverified; GEN-2 next.

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
