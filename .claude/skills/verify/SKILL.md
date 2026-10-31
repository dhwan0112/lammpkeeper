---
name: verify
description: "Verification skill for LammpKeeper (lkpr), a UI-less LAMMPS pre/post-processing library and CLI. Runs the real analysis code on small reference inputs (the committed ACE Fe3O4 fixture, built-in reference crystals and hand-built frames) and compares the numbers with stored reference values inside stated tolerances. Use before reporting a numeric change as done, when asked to verify or check lkpr, or when a refactor touches parsers, RDF, MSD, spin, box or reference-crystal code."
---

# verify (lkpr)

lkpr has no UI. "Driving the app the way a user does" means loading a trajectory
through the post shell, running an analysis, and reading the numbers. This skill
proves those numbers against reference values the maintainer has confirmed, with
explicit tolerances. A hash match is not a proof here; a value inside tolerance
is, and what it proves depends on the key's `kind` (see Evidence).

Read `features/README.md` first, then the feature file for what you are verifying.
Reference values live in `references/<check-id>.json`; a check runs only when its
file exists. Every reference key has a `kind`: `analytic`, `external`, `fixture`
or `snapshot`. Features that still lack reference values are listed in
`features/README.md` under "Pending references" and are not run.

## Launch

There is no server. Launch means: use this checkout's code with an isolated HOME
(the shell writes history files; `tests/run.py` has the same rule) and the
NumPy-only core. From the repo root:

```bash
export LKPR_HOME="$(mktemp -d)"           # disposable HOME for this run
HOME="$LKPR_HOME" python3 .claude/skills/verify/scripts/verify_refs.py --doctor
```

Ready means the doctor prints `ok numpy`, `ok lammpkeeper 1.2.0 from <this repo>`,
`fixture: present` and a non-empty `reference files` list. Optional modules
(scipy, ase, matplotlib, pandas, MDAnalysis) may be MISSING; that only limits
what can be verified, and the report must say so.

## Doctor (read-only)

```bash
HOME="$LKPR_HOME" python3 .claude/skills/verify/scripts/verify_refs.py --doctor
```

Prints repo path, git branch and short SHA, dirty-file count, Python and module
availability, the fixture path, the active reference files and the compute
functions that are inactive because their reference file does not exist yet.
Run this first whenever a result looks off. A `MISSING lammpkeeper` line means
the script is not importing this checkout; fix the working directory before
trusting any number.

## Drive

Run every active check (about 5 s on this machine, dominated by loading the
350-frame fixture twice and the two full-trajectory MSDs):

```bash
HOME="$LKPR_HOME" python3 .claude/skills/verify/scripts/verify_refs.py
```

Run one check while iterating:

```bash
HOME="$LKPR_HOME" python3 .claude/skills/verify/scripts/verify_refs.py --only analytic-msd
HOME="$LKPR_HOME" python3 .claude/skills/verify/scripts/verify_refs.py --list     # ids, sources, status
```

What each check drives is in its feature file. The runner takes the same code
paths a user takes: `LammpsPostShell.do_load('dump <fixture>')`, then
`lammps_post.analysis.compute_rdf`, `analyze_msd`, `analyze_spin_evolution`,
`lammps_post.references.compute_reference_rdf` and `lammpkeeper.io.Box`. It never
imports test helpers and never changes files under `tests/`.

For the full regression suite and the CLI smoke run (`lkpr post --analyze all`,
`lkpr prep` with ASE) use the sibling Cursor skill
`bash .cursor/skills/verify-lkpr/scripts/verify.sh quick|full`. That script
checks that analyses run and files appear; this skill checks that the numbers
are right.

## Evidence

Every run writes to `${LKPR_VERIFY_DIR:-$HOME/.cache/lkpr-verify}/<timestamp>-<sha>-refs/`
(outside the repo):

- `doctor.txt`: the doctor report for that run.
- `results.json`: per check and per reference key, the measured value, the
  reference, the tolerance and the max deviation.
- `summary.txt`: one `PASS|FAIL|ERROR <check-id> — <reason>` line per check.

Proof standards: quote `summary.txt` and, for any FAIL, the failing key's
measured and reference values from `results.json`. A PASS certifies only the
listed keys inside their tolerances on the listed inputs. It is not a claim that
other inputs, optional paths or physical models are validated.

What a PASS means depends on the key's `kind`, which the summary line and every
`results.json` entry carry:

- `analytic`, `external`, `fixture`: agreement with an independent standard (a
  closed-form identity, a literature or crystallographic value, or a committed
  data file aggregated without this repository's code).
- `snapshot`: agreement with this repository's own output at `baseline_commit`.
  That is a regression check ("unchanged since that commit"); it is not evidence
  of physical correctness. Report snapshot PASSes with that wording.

Never make a check pass by editing a reference value; a re-baseline is a
separate, justified change (AGENTS.md §7) recorded in the JSON `source` field
and, for snapshots, in a new `baseline_commit`. If HOME was not isolated, say
so: the history file side effect lands in the real HOME.

Because `$HOME` is the disposable `LKPR_HOME`, set `LKPR_VERIFY_DIR` to a path you
keep (for example `LKPR_VERIFY_DIR=~/.cache/lkpr-verify`) or the evidence is
deleted with the HOME in cleanup.

## Cleanup

The runner starts no processes and writes nothing inside the repo. Remove only
the HOME you created:

```bash
rm -rf "$LKPR_HOME"
```

Evidence under `LKPR_VERIFY_DIR` survives. Do not delete it.

## Helpers

- `scripts/verify_refs.py` (executable): doctor, checks, evidence. `--help` lists
  options. Compute functions are keyed by check id inside the script; adding a
  check means adding a function and a `references/<id>.json` with
  `reference`, `tolerance` (per key: `abs` and/or `rel`), `kind` (per key:
  `analytic | external | fixture | snapshot`), `source`, `status` and, when any
  key is a snapshot, `baseline_commit`. A malformed file is reported as ERROR,
  never silently skipped; `--list` prints kinds and schema errors.
- `references/*.json`: the maintained reference values. `source` (and the
  optional per-key `sources`) names where each number comes from: the analytic
  formula with its constants, the literature or crystallographic fact, the data
  file aggregation, or the snapshot's baseline commit and environment.

## Not covered (say so when relevant)

- Real LAMMPS runs, HPC submission, and anything needing ASE, matplotlib, pandas
  or MDAnalysis.
- Physical correctness of the trajectory-level ACE fixture numbers (RDF peak
  height, MSD endpoints): they are `snapshot` regression keys only.
- Slab (`p p f`) and non-Fe systems: no committed fixture.
- Visual correctness of plots.

Keep the map honest with `/maintain-verification-skill` when analyses, fixtures or
reference constants change.
