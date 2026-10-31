# Evaluation setup

Each case stages a small synthetic `log.lammps` through `place-files.sh`. These
are synthetic Skill inputs, separate from the scientific regression fixtures.
Run staging from a fresh evaluation directory so existing user data is preserved.

Provide the executor with an explicit Python path containing an installed
LammpKeeper backend, a fresh working directory, isolated HOME and an output
directory. Use identical environments and task prompts for paired Skill/no-Skill
runs. The Skill run reads the canonical SKILL.md; the baseline does not read Skill
files or graders. Neither executor should inspect expected outcomes.

Save commands, exit statuses, summary and execution evidence. Grade against the
four case assertions after execution; compare original input bytes separately.
Correct scientific values and structured execution evidence are distinct checks:
a parser-based baseline can obtain correct numbers yet omit request identity,
backend envelope or provenance required by the execution-evidence assertion.

The initial six runs and static review are documented in `docs/agent/AGENT-1.md`
at the repository root. One run per configuration does not establish reliability
or automatic trigger accuracy. Backend computation times are not agent duration.
