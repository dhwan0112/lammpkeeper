# AGENT-1 — portable structured-analysis Skill

Published implementation: `14ae464`, [PR #31](https://github.com/dhwan0112/lammpkeeper/pull/31).

## Foundation and scope

User-authorized merges completed in order: PR #28 (`d447a30`), #29 (`ed41c1f`),
#30 (`07983bd`). Merged main is byte-identical to verified EXEC-2 `75ab592`.
Implementation commits use Kim Donghwan <e1075536@u.nus.edu>; GitHub merge
commits display Donghwan Kim with the same email. PRs #26/#27 remain separate.

Canonical instructions live in `.agents/skills/lammpkeeper/SKILL.md`.
`.claude/skills/lammpkeeper` is a relative link to that directory. The workflow
discovers capabilities, selects an explicit Python environment, saves structured
requests/results/events, verifies outcome and cleanup, and reports native units
and parser warnings. It uses the existing scientific execution contract.

Evaluation scaffolds contain English comments explaining their staging purpose.
The Skill requires retained execution diagnostics and provenance. Runtime code,
scientific algorithms, dependencies and existing fixtures are unchanged.

## Host evidence (measured)

Moving this OpenCode session into the project advertised the new Skill. Loading
`lammpkeeper` through the Skill tool returned the canonical `.agents` path and
body. This proves discovery and explicit loading in this host; automatic trigger
accuracy was not measured. Claude's relative link resolves with identical bytes.
Claude Code and Codex live discovery/model execution remain untested. Their setup
notes cite host documentation in `references/hosts.md`.

## Paired evaluation design

Three fresh worker pairs use an installed verified backend in a real selected
venv with spaces in its path, isolated HOME and immutable synthetic inputs.
Each pair receives the same scientific task; one reads the frozen Skill and one
has no Skill. Four assertions per case cover result, units/diagnostics, structured
execution evidence and input preservation. Assertions are retained beside cases.

- Native real units: three samples, temperature mean 4 K and population standard
  deviation 1.63299316186 K; pressure mean 20 atm and deviation 8.16496580928 atm.
- Unresolved units: three selected rows, means 4 and 20; preserve unresolved units
  and the omitted minimization/incompatible block diagnosis.
- Malformed row: reject line 4's short numeric row with `invalid_input`; publish
  no partial successful summary and preserve the original input.

All six workers completed actual commands. Skill runs used supervised structured
execution and reported complete cleanup. Baselines obtained correct scientific
outcomes through legacy/parser paths; their structured-evidence fidelity is
graded separately. Exploratory errors remain in their command logs.

This is one run per case/configuration, not a statistical estimate of reliability.
Agent token totals and wall-clock durations were unavailable. Reported backend
durations cover different scopes and cannot establish speed or cost improvements.
No live Claude/Codex integration or HPC execution is inferred from these runs.

Evidence and static review are under
`/tmp/opencode/lkpr-agent1-evals/lammpkeeper-workspace/iteration-1/`.
Static review: `iteration-1/review.html` (generated with the official Skill
reviewer). Six grading records, timing availability records and benchmark JSON/
Markdown accompany the unchanged execution evidence.

### Evaluation results (measured)

| Case | Skill | Baseline |
| --- | --- | --- |
| Native units | 4/4 | 3/4 |
| Unresolved units | 4/4 | 3/4 |
| Malformed row | 4/4 | 1/4 |
| Total | 12/12 | 7/12 |

All six original inputs matched the synthetic sources byte-for-byte. Both
configurations obtained correct scientific outcomes and rejected the malformed
row without partial success. Baselines lacked structured request/response
identity and backend provenance. The malformed baseline additionally reported
legacy `ValueError` rather than `invalid_input`; its generic failure wording
also failed the strict operation-specific assertion. Accepting that honest legacy
failure would score the baseline **8/12**. Thus the observed difference concerns
execution-contract evidence, not improved numerical accuracy or safer row parsing.
Three assertions about values/preservation largely do not discriminate the two
approaches. Agent time/token totals remain unavailable, not zero.

## Final repository checks (measured)

Full verifier: **487 passed, 0 failed, 6 native-only skips**; post analysis/plots
and prep artifact/script checks passed. Evidence:
`/tmp/opencode/lkpr-agent1-full/20261030T200334-07983bd-full`.
All runtime, native and test files match the previously verified 493-pass native
snapshot byte-for-byte; all six skips were matched individually to its PASS
records (the named tests remain listed in EXEC-1's audit). Native was not rebuilt
for this instruction-only change. MDAnalysis remains unavailable; real HPC and
Python 3.9 runtime remain untested.

Official Skill quick-validation passed. All three scaffold scripts passed shell
syntax checks and staged byte-identical synthetic logs in isolated directories;
twelve grader files are present. The Claude symlink resolved with matching body
bytes. Diff whitespace checks passed. Unavailable pstack playbooks were not
claimed as executed; the repository verification script was run directly.

## Next slice

Independent static review found no contract blockers. Parent verified the six
grade records, original input bytes and generated review, and confirmed commit
identity. The maintainer explicitly requested commit, push and merge after these
checks. Publication is on `gen/agent-1-portable-skill`, based on merged main.

UI-1: additive Rust CLI using the same Python-owned execution contract and
environment diagnostics. TUI and optional MCP remain subsequent items.
