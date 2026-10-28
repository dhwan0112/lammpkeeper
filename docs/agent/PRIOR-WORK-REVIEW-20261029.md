# Independent prior-work review — 2026-10-29

Status: independent source review and parent reproduction complete; findings open.
No correctness certification or runtime fix claimed.
Baseline: `b9bd50333ad0b69a7274c89af850a56216d048c5` (merged PR #24).
Branch: `docs/prior-work-review-20261029`.
Published: [PR #25](https://github.com/dhwan0112/lammpkeeper/pull/25).

## Request and attribution boundary

The maintainer clarified that prior work **written by Sol** should be independently
reviewed by the current assistant, not that Sol should perform the review.
Git commit messages do not establish model authorship. To avoid omissions, review
the current production source as a superset of prior work, including merged
PRs #1–24 and their retained legacy code. Do not label individual files or commits
as Sol-authored without evidence. Deleted historical code is not current runtime.

GEN-2 implementation is paused. Its proposed ADR and work log remain preserved
on `gen/gen-2-explicit-metadata` at `e019dd7`; no acceptance is inferred from this
review request. This review branch starts from main and makes documentation-only
changes. Defect fixes require separately scoped regression/fix work.

## Independent work allocation

| Area | Inspection scope | Execution boundary |
| --- | --- | --- |
| Scientific kernels | core species/geometry, analysis, crystal references | synthetic independent numeric probes, isolated HOME |
| Readers/native | parsers, io, native source and parity contracts | disposable inputs; no native rebuild |
| Session/display | load/unload, metadata, cache lifecycle, CLI, plots, shared utilities | isolated sessions and real Agg when available |
| Preparation | builders, state, writers, templates, CLI | synthetic geometry and guarded local job stubs; no HPC/LAMMPS |
| Parent integration | test runner, verifier/build configuration, change/evidence inventory | independently reproduce material findings and review reports |

Workers cannot edit repository files or publish. The parent owns findings
integration, verification, roadmap and final review. Existing open findings in
BACKLOG.md must be distinguished from newly measured defects; passing historical
tests must not be used to dismiss a reproducer.

## Evidence rules

- Label numerical/behavioral findings as measured or source-inferred.
- Record path/line, exact probe command, observed result, expected contract,
  impact, and existing backlog linkage where applicable.
- Inventory inspected source and explicit exclusions. Do not substitute passing
  test totals for exhaustive semantic coverage or physical validation.
- Preserve fixtures, goldens, mappings, generated user files, thesis tag and
  user-owned `Claude outputs/`. No actual HPC execution, LAMMPS solver execution,
  package installation or architectural acceptance is part of this review.

## Progress

1. Read first-parent history through early repository integration and PRs #1–24.
2. Started four independent, non-overlapping source reviews; no Sol model was
   selected for reviewers. Parent inspected verifier, runner and package manifest.
3. All four scoped reviews completed. Parent read the reports and reproduction
   scripts, reran every priority probe group and inspected the relevant code.
   **11 new work items** were reproduced, plus a new hosted-history case within
   existing REV-OPS-1. Prior and fresh **444/0/0** runs remain baseline evidence,
   not evidence that these counterexamples are safe.

## Review conclusion and triage

All **32 production Python modules**, two legacy wrappers, the native source/
build configuration and verifier/package configuration received scoped source
inspection across the parent and reviewers. All 37 collected test modules ran
in the parent's full verifier. Associated test source/oracles were reviewed by
area, but not every test assertion or historical intermediate snapshot received
an exhaustive semantic audit. The 81-file inventory includes tests/build files;
it is not a claim of 81 independently proven implementations.

**11 new backlog items**: two scientific-kernel, three ingestion, three session,
one output-status, one nondefault prep API, one verifier-evidence issue. Most are
P2 correctness/automation risks; the unusual prep API input is triaged P3. These
priorities are judgments, not measured errors in the thesis or real materials.
No defect found here establishes that existing published Fe-O numbers changed.
Existing 22 items plus these 11 leave **33 open review items**; the newly observed
hosted-history case extends REV-OPS-1 rather than double-counting it.

Recommended order before further generalization: silent scientific/input errors
(selected-z validation, physical overrides, spin-map mismatch, RDF parity, dump
corruption/PBC) and stale-result publication first; output/evidence/history and
rare boundary/API cases next. Existing reference-shell and symmetry issues still
need their own fixes. GEN-2 remains paused at its separate architecture gate.

### New findings independently reproduced by parent

| Work item | Priority | Location | Measured counterexample / impact |
| --- | --- | --- | --- |
| REV-ANALYSIS-4 | P2 | `lammps_post/analysis.py:483–521` | Same in-box float32 pair: SciPy RDF bin 0, fallback bin 327483.8873423525. Exact represented-input MIC distance is outside cutoff. Optional backend changes pair membership. |
| REV-ANALYSIS-5 | P2 | `analysis.py:565–576,681–699,885–901` | Selected z `[1, NaN]`, surface 5: OAR and adsorption fraction 0.5 without warning; explicit-range density integrates to one of two selected records. Unknown location is silently treated as a valid denominator/out-of-range record. |
| REV-IO-4 | P2 | `lammps_post/parsers.py:582–611` | Retained numeric token `3#CORRUPTED` becomes 3 without warning, even after native rejection. NumPy's default comment parsing also rejects `A#site` where real native accepts it. |
| REV-IO-5 | P2, extreme-counter boundary | `parsers.py:1103,1169–1173,1267–1279` | Thermo steps `9007199254740992` and `9007199254740993` become equal float64 values; elapsed steps `[0,0]` while `timeline_valid=True`. No ordinary-counter fixture error claimed. |
| REV-IO-6 | P2, malformed-input boundary | `parsers.py:143–175,364–372` | Dump flags `p p f` become `(False,False,False)`; `pf pp ff` and `sp pp ff` are accepted as authoritative Booleans without warning. Invalid metadata should not silently establish PBC. |
| REV-SESSION-1 | P2 | `lammps_post/shell.py:1216–1224` | Public `set surface_z nan/inf` yields successful finite OAR 0/1; `set dt -1/nan` caches negative/nonfinite MSD time. Invalid settings are published instead of rejected transactionally. |
| REV-SESSION-2 | P2 | `shell.py:2039–2048`; `plotting.py:1126–1139` | Explicit ACE input plus `set types 1=Fe_down 2=Fe_up 3=O`: active Fe_up is `{2}` with one atom, but spin reports two up atoms (fixed type 1) and labels them up. Must honor approved semantics or reject noncanonical spin maps visibly. |
| REV-SESSION-3 | P2 | `shell.py:2579–2583,3174–3184`; `state.py:94–100` | After rewriting a loaded dump, cached MSD plotting succeeds with no warning at old value 1/3; the reader detects mutation, while reload yields 121/3. Cached publication bypasses source guard. |
| REV-UI-3 | P2 | `shell.py:3461–3471,2683–2689`; `plotting.py:605–612` | `export csv missing` in batch exits 0; requested pressure plot from a Step/Temp-only log exits 0 and creates no artifact. Explicit failed output requests look successful to automation. |
| REV-PREP-6 | P3, nondefault API | `lammps_pre/builders.py:238–248,274–285`; `templates.py:340–346,386–388` | Public state with bond 3 Å and vacuum 3.1 Å builds/writes successfully, but one oxygen lies below gas wall and above NVE top, outside all static integration groups. Default 1.21 Å bond/CLI behavior is not alleged defective. |
| REV-VERIFY-3 | P2 | `.cursor/skills/verify-lkpr/scripts/verify.sh:102,138–142` | Denied retained-summary copy still exits 0 and reports PASS; detailed parent-owned probe below. |

### Reproduction details and independent expectations

**RDF:** two types 4/9 at float32 x `-49.95`, `49.15`, y=z=0,
box `[-50,50]^3`, PBC `(True,False,False)`, cutoff
`0.8999958038330078`, one bin. Exact rational arithmetic on the represented
positions gives MIC distance `0.8999977111816406 > cutoff`. Both the tree path
and the same represented positions promoted to float64 yield zero; forcing only
candidate fallback invents a pair. The large normalized bin is for a two-atom
synthetic box, not an estimate of a real material's RDF error. Existing float64
parity tests do not cover the supported float32 input path.

**Dump corruption/PBC:** one ordinary dump row `1 1 A 1 2 3#CORRUPTED` under
`id type element x y z` is accepted by native-enabled and forced-NumPy readers.
For `A#site`, the native-success probe forbids NumPy fallback. Malformed periodic
flags were also read with `box_model=True`, proving publication in typed metadata.
No claim is made that genuine LAMMPS emits these corrupted flags.

**Thermo precision:** explicit `units metal`, `timestep 0.001`, `run 1`,
`Step Temp` and rows `9007199254740992 300` / `9007199254740993 301` produce a
zero increment. Integer subtraction independently establishes the increment 1.
This tests an extreme signed-64-bit counter boundary, not ordinary MD duration.

**Session:** the two-frame dump has two type-1 atoms, one type-2 and one type-3.
Spin's independent oracle counts the active `{2}` selection directly. For cache
mutation, only one Fe displacement changes from 1 to 11 Å, giving analytic MSD
`(0+0+1)/3` versus `(0+0+121)/3`. Actual Agg output is saved; its visual quality
is not certified. Invalid-setting outputs are measured command/cache behavior,
not an independent proof of the underlying kernels.

**Prep API:** a 4×4×8 slab, fixed/NVT layers 1/2, one O2, seed 1, vacuum 3.1,
bond 3.0 produces z `[20.805364302683696,18.113467619860234]`, gas-wall z 18.445,
NVE top 10.545. Build and writer success are measured. Missing integration follows
from the generated static region memberships; no solver was run. CLI does not
expose the bond setting, so scope and P3 triage are deliberately narrow.

### Existing findings independently reconfirmed

- REV-REF-2: default alpha-Fe reference gives coordination ≈3 at r=2a=5.733 Å;
  the independent BCC shell has six axial neighbors. No golden rebaseline.
- REV-REF-3: unsupported `x/2,y,z` on `[.2,.3,.4]` yields `[2.2,.3,.4]`, not a
  visible unsupported-operation error (nor algebraic x/2=.1).
- REV-IO-2: appending during active streaming publishes new frame/species even
  though the reader's subsequent source check rejects the changed file.
- REV-IO-3: projected x-only parsing accepts raw `1 2` under `x y z` on both
  backends; the native probe forbids fallback.
- REV-PREP-2: periodic-z boundary still renders a z-reflecting wall. Rendering
  measured; solver incompatibility is inferred, not a real HPC diagnostic.
- REV-PREP-3: identical settings/signature give different initial Fe positions
  with ASE versus manual builder while O positions and box agree.
- REV-PREP-4: prep's inspector returns empty masses for its own blank-separated
  Masses section (expected Fe/O masses remain in the generated file).
- REV-PREP-5 is now **parent-reproduced**, not only source-inferred: early `tee`
  appends to an unrelated `run.log` link target, job exits 0 and removes scratch.
  This is outside REV-PREP-1's explicitly bounded copyback-only contract.
- REV-UI-1/-2: empty plain table TypeError and saved-recipe alias mismatch persist.
- REV-OPS-1 extension: first hosted inline `post info` changes history from
  `['menu_old','menu_unsaved']` to `['post_old']` and saves that as menu history.
  Parent reproduced this separately from known standalone callback contamination.

### Positive checks (parent reran)

- 150 rank-one skew MIC cases match exact rational nearest-integer projection.
- 64 additional exact-integer image problems cover all eight PBC masks. Search
  bounds derive from rational inverse/dual-norm inequalities, not an unproved
  finite cube or production geometry. All minimum squared objectives agree.
- Four declared built-in motifs match independently generated ASE space groups
  for the supplied cell/site parameters (largest site mismatch ≈3.06e-15 Å).
  This checks motifs, not physical stability, reference RDF shells or energetics.
- CIF occupancy 0, .5 and exact near-one decimal reject; nominal-one uncertainty
  form `1.000(2)` retains two sites. No new occupancy bypass established.
- A triclinic cell serialized from eight explicit vertices has expected origin,
  mixed-sign tilts, matrix, PBC and volume 1680 on indexed/stream/native/NumPy paths.
- No new concrete SpeciesMap, bounded exact-MIC or fixed-cell triclinic-MSD defect
  was established. No new bounded-copyback bypass was established. These are
  scoped negative findings, not proofs that remaining inputs are all correct.

## Parent findings (measured)

### R-VERIFY-1 — failed evidence retention can still report PASS (P2)

- Location: `.cursor/skills/verify-lkpr/scripts/verify.sh:102,138–142`.
- The copy of `post-summary.txt` has no checked status, and the final exit is
  based only on earlier `RESULTS` entries. Losing retained evidence is not
  represented by a failed verification result.
- Parent fault-injected only `cp`, through the existing isolated fake-checkout
  verifier harness. Observed exit **0**, `PASS tests`, `PASS post`, `PASS prep`,
  stderr `injected retained-evidence copy failure`, and absent retained
  `post-summary.txt`. Synthetic placeholder artifacts validate the verifier
  decision only; they are not real scientific or rendering output.
- Command: `HOME="$(mktemp -d /tmp/opencode/prior-review-verifier.XXXXXX)" TMPDIR=/tmp/opencode PYTHONDONTWRITEBYTECODE=1 python /tmp/opencode/prior-review-verifier-probe.py`.
- New finding, distinct from existing REV-VERIFY-1 (temporary-directory failures)
  and REV-VERIFY-2 (same-second evidence collisions). Proposed work item:
  `REV-VERIFY-3`. Scope should check required evidence writes/copies and final
  summary publication before exit success, with a fault-injection regression.

## Inventory and mechanical checks

Parent measured **81 tracked source/build files**, **76 Python modules**,
**1052 documented definitions**, and **37 registered test modules**. All Python
files parse under Python 3.9 grammar; registration covers every tracked
`tests/test_*.py` module exactly once. English documentation presence is not
semantic correctness proof. Inventory: `/tmp/opencode/prior-review-inventory.json`.
The thesis tag still resolves to `cdf5c38e975871debf64eb6d810e78a08165c381`.

Parent inspection includes `tests/run.py`, `tests/_util.py`,
`tests/test_audit_verifier.py`, `.cursor/skills/verify-lkpr/scripts/verify.sh`,
`pyproject.toml`, top-level legacy wrappers and dependency-light package entrypoints.

### Fresh baseline verification

Command:

```bash
PYTHON=/home/kim/opt/miniforge3/envs/chem/bin/python TMPDIR=/tmp/opencode \
  LKPR_VERIFY_DIR=/tmp/opencode/prior-review-native PYTHONDONTWRITEBYTECODE=1 \
  bash .cursor/skills/verify-lkpr/scripts/verify.sh full
```

Measured **444 passed, 0 failed, 0 skipped**; post analyses/actual plots and prep
artifact/script syntax smoke passed. Evidence:
`/tmp/opencode/prior-review-native/20261029T000604-b9bd503-full`.
MDAnalysis and rich are absent from that interpreter; pytest execution is not
claimed. This passing baseline coexists with the independent failure-injection
finding above. No expected numeric values were modified.

### Offline distribution smoke

Command: `HOME="$(mktemp -d /tmp/opencode/prior-review-wheel-home.XXXXXX)" TMPDIR=/tmp/opencode PYTHONDONTWRITEBYTECODE=1 python /tmp/opencode/prior-review-wheel-check.py`.

Built a pure-Python wheel from Git HEAD in a disposable checkout with
`pip wheel --no-deps --no-build-isolation`, network disabled. All **32** production
Python modules were included, with no native binary. Extracted-wheel `lkpr`,
legacy prep/post module help and SpeciesMap/Box/parser imports passed away from
the source checkout. This checks wheel contents/imports, not a fresh dependency
installation or full numerical suite against the wheel.

### Historical annotation checks

Parent independently compared executable Python ASTs against each commit's
parent, stripping only module/class/function docstrings:

- `97215c6` (DOC-ALL): **58 changed Python files**, equal.
- `d3ab05a` (whole-source re-review): **51 changed Python files**, equal.

This supports the Python annotation-only claims, including unchanged generated
string payloads. It does not certify the pre-existing algorithms or every
historical revision, and is not an independent Rust semantic comparison.

## Parent reproduction commands and retained logs

Each command below was executed successfully by the parent after reading the
script. A zero probe exit means its observations/assertions reproduced; it does
**not** mean the defective production behavior satisfies the desired contract.
All files are disposable or retained under `/tmp/opencode`; no real HOME or HPC
resources were used.

```bash
HOME="$(mktemp -d /tmp/opencode/prior-parent-prep.XXXXXX)" \
  TMPDIR=/tmp/opencode PYTHONDONTWRITEBYTECODE=1 LKPR_NO_HISTORY=1 \
  PYTHONPATH=/home/kim/projects/lammpkeeper \
  /home/kim/opt/miniforge3/envs/chem/bin/python /tmp/opencode/sol-prep-audit-probes.py

HOME="$(mktemp -d /tmp/opencode/prior-parent-io.XXXXXX)" \
  TMPDIR=/tmp/opencode PYTHONDONTWRITEBYTECODE=1 \
  /home/kim/opt/miniforge3/envs/chem/bin/python /tmp/opencode/sol-review-io-probes.py \
  > /tmp/opencode/prior-parent-io.log 2>&1

HOME="$(mktemp -d /tmp/opencode/prior-parent-session.XXXXXX)" \
  TMPDIR="$(mktemp -d /tmp/opencode/prior-parent-session-tmp.XXXXXX)" \
  PYTHONDONTWRITEBYTECODE=1 LKPR_NO_HISTORY=1 MPLBACKEND=Agg \
  /home/kim/opt/miniforge3/envs/chem/bin/python /tmp/opencode/sol-session-probe.py \
  > /tmp/opencode/prior-parent-session.log 2>&1

HOME="$(mktemp -d /tmp/opencode/prior-parent-history.XXXXXX)" \
  TMPDIR=/tmp/opencode PYTHONDONTWRITEBYTECODE=1 LKPR_NO_HISTORY=0 \
  /home/kim/opt/miniforge3/envs/chem/bin/python /tmp/opencode/sol-session-history-probe.py

HOME="$(mktemp -d /tmp/opencode/prior-parent-physics.XXXXXX)" \
  TMPDIR=/tmp/opencode PYTHONPATH=/home/kim/projects/lammpkeeper \
  PYTHONDONTWRITEBYTECODE=1 /home/kim/opt/miniforge3/envs/chem/bin/python \
  /tmp/opencode/sol-physics-probes.py > /tmp/opencode/prior-parent-physics.log 2>&1
```

The `sol-*` artifact names describe the user's review request, **not reviewer
model selection or authorship attribution**. Detailed reviewer evidence/inventory:

- `/tmp/opencode/sol-review-physics.md`: all core, analysis and reference source;
  214 exact geometry probes, motif/occupancy checks and scientific findings.
- `/tmp/opencode/sol-review-io.md`: entire parsers, io and native source/build;
  worker targeted native **84/0/0**, forced NumPy **80/0/4** (four named native-only
  skips in that report). Parent reran the independent probe group, including
  instrumented real-native success and independent vertex serialization.
- `/tmp/opencode/sol-review-session.md`: entire shell/state/plot/CLI/shared
  implementations; worker targeted **114/0/0**. Parent reran actual Agg, command
  exit, history and cache/selection probes independently.
- `/tmp/opencode/sol-review-prep.md`: all nine prep source modules; worker guarded
  local tests **53/0/0**. Parent reran all five priority probes independently.

Worker targeted totals overlap the parent's full suite and are **not summed**
into a larger coverage count. Source/diff checks establish inspected runtime bytes
match `b9bd503` despite branch changes and concurrent documentation editing.

## Production inspection inventory

| Owner | Complete production source inventory |
| --- | --- |
| Physics reviewer | `lammpkeeper/core/{__init__,species,geometry}.py`; `lammps_post/{analysis,references}.py` |
| I/O reviewer | `lammps_post/parsers.py`; `lammpkeeper/io/{__init__,box}.py`; `native/{src/lib.rs,build.sh,Cargo.toml}`; lock metadata |
| Session reviewer | `lammps_post/{shell,state,plotting,cli,display,__main__}.py`; `lammpkeeper/{shell,cli}.py`; `lammpkeeper/common/{__init__,hosted,display,mapping}.py`; legacy post wrapper |
| Prep reviewer | `lammps_pre/{__init__,__main__,display,state,builders,writers,templates,shell,cli}.py` |
| Parent | `lammpkeeper/{__init__,__main__}.py`; `lammps_post/__init__.py`; both legacy wrappers; `pyproject.toml`; verifier; test runner/bootstrap/fault-injection harness; review integration and cited defect paths |

All 76 Python source/test modules were also grammar/documentation-checked. The
exhaustive tracked file list is `/tmp/opencode/prior-review-inventory.json`.

## Limits and next action

This is a current-source review plus historical annotation checks, not proof of
every previous revision or Sol authorship. No actual LAMMPS, external potentials,
MPI/scheduler/HPC, all-platform run, fresh dependency installation, MDAnalysis,
pytest execution, visual-quality certification or arbitrary CIF grammar proof.
The optional native binary was exercised but not rebuilt: correspondence to the
current Rust source is not established solely by parity tests. Its observed
SHA-256 was `944b5832c317b4181e4142e81188d95ff208352b31171b07246663c51ccadd22`.

Only documentation/backlog changes are included. The proposed GEN-2 branch is
preserved; no architecture decision is accepted. Fixes should proceed as separate
failing-first backlog items, with generated-structure/protocol and golden gates
retained. This review supplies defects to repair, not permission to change numeric
expectations or report the existing suite as exhaustive correctness evidence.

Final parent checks passed: `git diff --check`; exactly 33 unique open review
items plus three completed original P1 items; tracked runtime/test/fixture/golden
bytes unchanged from `b9bd503`; unchanged thesis tag; proposed GEN-2 branch still
at `e019dd7`. Since subsequent edits are documentation only, the successful fresh
full verifier is not rerun merely to change the evidence timestamp.
