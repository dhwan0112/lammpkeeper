# VERIFY-REF-1 and RDF-PROV-1 — reference-value verify skill and RDF frame window

Status: implemented by the maintainer; integrated and fully verified by the
agent; publication in progress.
Branch: `skills/verify-reference-checks` (maintainer commits `7367ab3`,
`a99318f`, `7cfc16a`, 2026-10-31), main merged in as `ee4c5d5`.

The maintainer wrote these three commits locally. On 2026-11-01 the maintainer
asked the agent to finish this in-progress work before continuing the roadmap.
The agent added only this log, BACKLOG rows, the CHANGELOG entry and the merge
with main. The agent did not change the maintainer's code, references or tests.

## VERIFY-REF-1 — `.claude/skills/verify`

A verification skill for the UI-less analysis code. `scripts/verify_refs.py`
runs the real code paths (post-shell load, `compute_rdf`, `analyze_msd`,
`analyze_spin_evolution`, `compute_reference_rdf`, `lammpkeeper.io.Box`) on small
inputs and compares numbers with `references/<check-id>.json` inside stated
tolerances. Evidence (`doctor.txt`, `results.json`, `summary.txt`) is written
outside the repository.

Every reference key has a `kind`:

| kind | PASS means |
| --- | --- |
| `analytic` | agreement with a closed-form identity |
| `external` | agreement with a cited literature/crystallographic value |
| `fixture` | agreement with the committed fixture aggregated without repo code |
| `snapshot` | unchanged since `baseline_commit` `a974563`; **not** a correctness proof |

Six checks: `analytic-msd`, `analytic-rdf-pair`, `box-geometry`,
`fixture-ace-bulk`, `fixture-ace-rdf-msd`, `reference-crystal-fe3o4`. The
feature files record fixture caveats found while measuring, including:
`compute_rdf` averages the last 20 frames (here the minimization tail),
`analyze_msd` does not subtract affine NPT cell motion, the heuristic
`dt_fs=0.25` differs from the run's 1 fs, and the phonopy POSCARs give type 2
the Mn mass while the repo writer uses Fe. These are recorded observations, not
fixes; the dt and FF heuristics remain GEN-2 work.

This skill does not replace `.cursor/skills/verify-lkpr` (full suite, post/prep
smoke). It adds reference-value checks; the second commit makes them the default
verification and runs test suites only on request.

## RDF-PROV-1 — RDF frame-window provenance

`compute_rdf` now also returns `frame_window`:
`{first_step, last_step, n_frames, selection}`, where `selection` is `'last'`
when the trajectory was truncated to its last `max_frames` frames, otherwise
`'all'`. `describe_frame_window()` renders it, e.g.
`last 20 frames (steps 3400–3587)`. g(r), `n_frames` and the default
last-20-frame selection are unchanged.

Visible output changes:

- RDF plot legend: `MD, last N frames (steps A–B)`; cached results without
  `frame_window` keep the old `MD (N frames)` label.
- `export csv` for an RDF result starts with a comment line
  `# frame_window: ...`; `export latex` starts with `% frame_window: ...`;
  `export summary` lists the frame window. Other results export as before.
  CSV/LaTeX files are now written as UTF-8 (the window uses an en dash).
- **Compatibility note:** a CSV reader that does not skip `#` comment lines
  (for example `pandas.read_csv` without `comment='#'`) will read the comment as
  the header row. No code in this repository reads exported CSVs back. This is
  an output-format change, recorded here and in CHANGELOG.

### Golden handling (AGENTS.md §7)

`tests/test_regression_numeric.py::test_numeric_regression_rdf_msd_slow` now
hashes only the numeric RDF fields `r, g, label, n_frames`, not the whole
returned dict, because `frame_window` is provenance metadata. The stored
fingerprint `GOLDEN_SLOW['rdf_FeUp_O']` is **unchanged** and still matches, so
this is not a re-baseline: the arithmetic result it protects is identical. The
return-key schema test now lists `frame_window`.

## Verification

Measured on merged tree `ee4c5d5` (expanded Python 3.12, isolated HOME):

- Skill reference checks (`verify_refs.py`, all six): **PASS** — analytic-msd
  5/5, analytic-rdf-pair 5/5, box-geometry 7/7, fixture-ace-bulk 13/13,
  fixture-ace-rdf-msd 5/5 (4 snapshot keys: regression only), reference-crystal-
  fe3o4 7/7.
- Native full verifier: **522 passed, 0 failed, 0 skipped**; post analyses/real
  plots and prep artifacts/script syntax passed. Evidence:
  `/tmp/opencode/vref-native/20261101T012250-ee4c5d5-full`.
- Forced NumPy: **516 passed, 0 failed, 6 skipped** (the known native-only
  checks, all PASS natively). Evidence:
  `/tmp/opencode/vref-numpy/20261101T012251-ee4c5d5-full`.
- The slow RDF golden passed with the unchanged stored fingerprint. Native
  extension was the existing ignored build (not rebuilt). Pytest, MDAnalysis
  and HPC were not run. The skill was run directly by the agent; Claude Code
  skill discovery was not tested.
