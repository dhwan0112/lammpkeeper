# Every-source maintenance annotation — DOC-ALL

Status: annotation, semantic/coverage checks, selective independent review and
full runtime verification complete. Published as
[PR #16](https://github.com/dhwan0112/lammpkeeper/pull/16), originally stacked
on [audit PR #15](https://github.com/dhwan0112/lammpkeeper/pull/15). Both were
subsequently merged into main on 2026-10-27 at the maintainer's explicit request.
Baseline: `f62f0a4a5d57ade623144470e369bd238d57e435` (verified audit PR #15).
Original branch: `docs/all-source-comments`, based on the audit branch before
both PRs were merged into main.

This inventory records the completed PR #16 annotation snapshot, not a claim
that future roadmap additions do not add source files. TEST-3 subsequently adds
`tests/synthetic_slab.py` and `tests/test_slab_reference.py`, with English module,
function and nested-helper docstrings; their behavior/coverage is recorded in
`docs/agent/TEST-3.md`. The original annotation-only AST comparison still applies
to its original 63-file baseline, not newly added test logic.

## Agreed scope

The maintainer selected **every file, function/class and major logic**, rather
than a comment on every execution line, and selected **English**. All **63 tracked
Python/Rust/Shell/TOML source/build files** receive meaningful documentation.

- All **58 Python modules** have module documentation. All **713 function/class
  definitions**, including private and nested helpers and test definitions, have
  docstrings. Existing useful documentation is retained or clarified.
- Comments explain contracts, units, identities, PBC, provenance, lifecycle,
  mathematical normalization, failure paths and why a test's oracle is valid.
  They do not certify an untested scientific assumption or repeat every trivial
  assignment. Lambdas are explained at their surrounding call sites.
- Rust functions/output ownership, shell build/verification steps and TOML build
  configuration are annotated in their native comment syntax.
- No executable logic, assertion/expected value, canonical mapping, fixture,
  generated Bash/LAMMPS/string literal, binary or lockfile changes are included.
  JSON configuration such as `.cursor/cli.json` is data, not source code; comments
  would make it invalid JSON. User-owned untracked `Claude outputs/` is untouched.

## Complete file inventory

Counts are Python function/class definitions (nested definitions included), not
line counts. A dash means module-level/native/build configuration documentation.
Every listed file was checked and changed; there are **zero untouched targets**
and **zero missing Python module/function/class docstrings**.

### Shared entrypoints and utilities

| File | Definitions | Maintenance focus |
| --- | ---: | --- |
| `lammpkeeper/__init__.py` | — | dependency-light version ownership and current migration boundaries |
| `lammpkeeper/__main__.py` | — | module/console entrypoint and exit propagation |
| `lammpkeeper/cli.py` | 2 | verbatim routing, argparse ownership, interactive versus one-shot behavior |
| `lammpkeeper/common/__init__.py` | — | shared-module responsibilities, no eager optional imports |
| `lammpkeeper/common/display.py` | 14 | ANSI/Unicode cell width, Rich fallback, style versus error status |
| `lammpkeeper/common/hosted.py` | 9 | child navigation protocol and process-global bounded history |
| `lammpkeeper/common/mapping.py` | 8 | canonical slots versus analysis aliases, conflict rules |
| `lammpkeeper/shell.py` | 16 | persistent child state, lazy imports, history swapping, stop signals |
| `lammps-pre.py` | — | legacy delegation and failure ownership |
| `lammps-post.py` | — | legacy delegation and failure ownership |

### Post-processing

| File | Definitions | Maintenance focus |
| --- | ---: | --- |
| `lammps_post/__init__.py` | — | constants, units and compatibility version export |
| `lammps_post/__main__.py` | — | legacy module entrypoint |
| `lammps_post/display.py` | — | shared display re-export contract |
| `lammps_post/cli.py` | 1 | modes, quoting, failure status and batch stop |
| `lammps_post/state.py` | 13 | source ownership, cache invalidation, surfaces and species selection |
| `lammps_post/shell.py` | 98 | load/unload provenance, groups, shared jobs, recipes, plotting and exports |
| `lammps_post/parsers.py` | 63 | reader/index/cache snapshots, dtype identity, concurrency, formats, units and timelines |
| `lammps_post/analysis.py` | 20 | RDF ensemble/PBC, selection denominators, fixed/union IDs, NaN gaps and surface assumptions |
| `lammps_post/references.py` | 12 | lattice conventions, symmetry, CIF limitations and reference RDF interpretation |
| `lammps_post/plotting.py` | 25 | actual units/time axes, conditional slab pressure, uptake cohorts and rendering failures |

### Pre-processing

| File | Definitions | Maintenance focus |
| --- | ---: | --- |
| `lammps_pre/__init__.py` | — | constants, domain scope and version compatibility |
| `lammps_pre/__main__.py` | — | legacy module entrypoint |
| `lammps_pre/display.py` | — | shared display re-export |
| `lammps_pre/builders.py` | 6 | supported slab geometry, region partition, placement, isotropy and seed ownership |
| `lammps_pre/cli.py` | 2 | mode precedence, quoting and nonzero failures |
| `lammps_pre/shell.py` | 30 | mutation/build lifecycle, partial data preview, matrix and command dispatch |
| `lammps_pre/state.py` | 25 | geometry signature, FF presets, units, overrides and processor grid |
| `lammps_pre/templates.py` | 4 | source-side protocol/scratch documentation without altering generated strings |
| `lammps_pre/writers.py` | 8 | freshness guards, atom styles, masses/spin slots and artifact dependencies |

### Native/build/verification files

| File | Definitions | Maintenance focus |
| --- | ---: | --- |
| `native/src/lib.rs` | — | all three functions/output struct, ownership, bytes, UTF-8, precision and errors |
| `native/build.sh` | — | prerequisites, release build, ABI/module placement and failure handling |
| `native/Cargo.toml` | — | private crate, cdylib, PyO3 ABI floor and release flags |
| `pyproject.toml` | — | build backend, dependency extras, shared version and legacy packages |
| `.cursor/skills/verify-lkpr/scripts/verify.sh` | — | disposable paths versus retained evidence, optional probes and PASS/FAIL/SKIP status |

### Test infrastructure and regressions

| File | Definitions | Maintenance focus |
| --- | ---: | --- |
| `tests/_util.py` | 8 | explicit skips, capture isolation and fingerprint limits |
| `tests/conftest.py` | — | checkout-first pytest bootstrap |
| `tests/pending_review_findings.py` | — | intentionally uncollected staging, not false coverage |
| `tests/run.py` | 1 | explicit registration, deterministic execution, skips and failures |
| `tests/test_display.py` | 7 | width, formatting and shared implementation invariants |
| `tests/test_dump_reader.py` | 18 | layout/selection/cache/stream/native contracts and malformed input |
| `tests/test_engine.py` | 9 | shared-read lifecycle, errors and accelerated/fallback equality |
| `tests/test_fair_comparison.py` | 4 | identical coordinates versus format-only FF differences |
| `tests/test_history.py` | 12 | isolation, limits and opt-out behavior |
| `tests/test_job_script_safety.py` | 22 | guarded stubs, fault injection and recovery invariants |
| `tests/test_lkpr_cli.py` | 8 | routing, legacy versions and persistent hosted state |
| `tests/test_mapping.py` | 9 | canonical tables, proxy slots and explicit labels |
| `tests/test_msd.py` | 32 | analytic displacement, fixed-ID cohorts, PBC and errors |
| `tests/test_o2_pairing.py` | 17 | independent image oracle, global greedy rules and deterministic ties |
| `tests/test_o2_periodicity.py` | 22 | every PBC combination, real tree calls and metadata precedence |
| `tests/test_parse_log_merge.py` | 3 | source-block MD identity versus optimizer iterations |
| `tests/test_periodicity.py` | 15 | box flags, native parity and per-axis shell routing |
| `tests/test_regression_numeric.py` | 4 | fingerprints detect change, not physical correctness |
| `tests/test_skip_reporting.py` | 3 | skipped checks cannot inflate pass counts |
| `tests/test_species_plot_labels.py` | 13 | display metadata cannot rename cache/output identities |
| `tests/test_species_selection.py` | 47 | unions, conflicts, analytic counts and cache invalidation |
| `tests/test_audit_analysis.py` | 20 | exact RDF math, ideal gas, percentile and ID-union oracles |
| `tests/test_audit_integration.py` | 6 | MD time, pressure provenance, geometry ambiguity and missing renderer |
| `tests/test_audit_parsers.py` | 12 | all access/backend paths, identity precision and safe metadata evaluation |
| `tests/test_audit_prep.py` | 21 | independent geometry/isotropy and guarded copyback tests |
| `tests/test_audit_rdf_oracle.py` | 1 | full explicit pair matrices on unchanged fixture |
| `tests/test_audit_references_plots.py` | 15 | independent crystal geometry and real Agg artist checks |
| `tests/test_audit_verifier.py` | 9 | missing/partial artifacts and positive controls |
| `tests/test_audit_workflow.py` | 19 | dispatch mocks, cache provenance and selection math |

## Verification method

Baseline executable content was captured before annotation. The checks compare:

1. Every Python AST with only genuine module/class/function docstrings removed.
   All other string constants remain part of the comparison, including generated
   scripts, fixture snippets, error messages, output filenames and golden values.
2. Rust/Shell nonblank, non-full-line-comment source. Native changes use only
   full-line comments; shell commands and existing heredoc payloads stay intact.
3. Parsed TOML data, so no package/dependency/build value can change unnoticed.
4. Exhaustive Python 3.9 grammar and docstring coverage via `ast.walk`, and the
   baseline inventory against the changed-file set.

Measured pre-runtime checks: **63/63 semantic comparisons pass; 58/58 Python
modules and 713/713 definitions documented; no untouched target; `git diff
--check` and both shell `bash -n` checks pass.** Local check artifacts are
`/tmp/opencode/lk-comment-semantics.py`, `lk-comment-baseline.json` and
`lk-comment-inventory.json`.

Full verification after annotation (measured):

| Environment | Passed | Failed | Skipped | Smoke results |
| --- | ---: | ---: | ---: | --- |
| chem + native | 251 | 0 | 0 | required summaries, ten plots, five prep artifacts, job syntax PASS |
| chem, forced NumPy | 249 | 0 | 2 | same outputs PASS; two native-only checks explicitly skip |
| default Python | 237 | 0 | 14 | analyses and summaries PASS; ASE prep smoke explicitly skips |

The default skips are four ASE and ten real-Matplotlib tests, all executed in
chem. Missing MDAnalysis and pytest remain unverified; no native rebuild or real
LAMMPS/HPC execution was performed. Evidence:

- `/tmp/opencode/lk-comments-rich/20261027T191851-f62f0a4-full`
- `/tmp/opencode/lk-comments-fallback/20261027T191851-f62f0a4-full`
- `/tmp/opencode/lk-comments-default/20261027T191851-f62f0a4-full`

Selective independent documentation review found one overbroad subscriber
cancellation comment. It now distinguishes explicit close/shutdown (which can
interrupt backpressure) from a paused, still-open consumer (which can throttle
production). This final correction is a comment only; semantic/coverage checks
were repeated afterward. Review is not a proof that every scientific assumption
or future edge case is correct.

## Existing limitations surfaced while writing comments

These are **source-inferred follow-up questions**, not newly tested defect
reproductions and not changes in this documentation-only branch: the prep data
preview has limited Masses/section parsing; `use_scratch` is not consumed by the
current job template; configurable boundaries do not generalize the slab gas
placement recipe; interactive `--find`/reference-pair/recipe naming paths deserve
separate repros. Comments describe existing behavior rather than silently
repairing it or certifying it. Real LAMMPS/HPC, MDAnalysis and pytest execution
remain outside the verification available here.
