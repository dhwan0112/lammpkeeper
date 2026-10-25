---
name: verify-lkpr
description: End-to-end verification for LammpKeeper. Runs the doctor check, the regression suite with an isolated HOME, a one-shot `lkpr post` on the ACE fixture and a `lkpr prep` smoke run, then keeps the evidence. Use before reporting any change as done, or when asked to verify, check or smoke-test lkpr.
---

# verify-lkpr

The project-local verification skill. pstack's playbooks call it at their
"prove it works" step. Maintain it with `/maintain-verification-skill`.

## Launch

```bash
bash .cursor/skills/verify-lkpr/scripts/verify.sh quick   # doctor + fast tests + post one-shot
bash .cursor/skills/verify-lkpr/scripts/verify.sh full    # + LKPR_SLOW goldens, plots, prep smoke
```

Use `full` before opening a PR, and `quick` while iterating.

## Doctor (read-only)

The script prints the Python version and which optional modules import
(numpy, scipy, ase, matplotlib, pandas, MDAnalysis). It also checks whether the
native parser `.so` exists, whether the fixture exists, and the git branch, HEAD
and dirty state. A missing optional module means that path is **not verified**.
Say so in the report.

## Drive

1. `python tests/run.py` (with `LKPR_SLOW=1` in full mode), using a throwaway HOME.
2. `python -m lammpkeeper post --dump <fixture> --analyze all --output <tmp>`.
   In full mode, `--plot all` as well.
3. Full mode, if ASE is present: `python -m lammpkeeper prep --ff ace --temp 800 --o2 4 --slab 4x4x8 --write <tmp>`,
   then `bash -n` on every generated `*.sh` / `*.pbs`.

## Evidence

Everything is written to `${LKPR_VERIFY_DIR:-$HOME/.cache/lkpr-verify}/<timestamp>-<sha>/`,
outside the repo, and survives cleanup:
`doctor.txt`, `tests.log`, `post.log`, `prep.log`, `outputs.txt`, `summary.txt`.
Quote `summary.txt` and the test-count line in your report. The test count is the
`N passed, M failed` line.

## Cleanup

The script deletes its temporary HOME and work directories and leaves the evidence.
It exits nonzero if any step FAILs. A SKIP is not a pass. Report SKIPs explicitly.

## Not covered (say so when relevant)

- Real LAMMPS runs and HPC submission.
- Slab `p p f` analysis paths (the fixture is bulk `p p p`; BACKLOG TEST-3).
- Visual correctness of figures (only that they are produced).
