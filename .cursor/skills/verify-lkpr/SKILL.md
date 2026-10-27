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
   The collected suite includes the TEST-3 runtime-generated `pp pp ff` slab
   reference: serialized readers, metadata/shared jobs, independent analytic
   RDF/MSD/O2/penetration expectations and optional real rendering.
2. `python -m lammpkeeper post --dump <fixture> --analyze all --output <tmp>`.
   In full mode, `--plot all` as well. A second batch invocation persists a
   summary; every mode checks the expected fixture analyses, and full mode
   checks every expected plot (one arbitrary PNG is insufficient).
3. Full mode, if ASE is present: `python -m lammpkeeper prep --ff ace --temp 800 --o2 4 --slab 4x4x8 --write <tmp>`,
   then `bash -n` on every generated `*.sh` / `*.pbs`. At least one script and
   every expected nonempty data/input/region/XYZ artifact are required; logged
   failures cannot pass even when the process exit status is zero.
4. A test run with zero passes is a failure, not an empty success.

## Evidence

Everything is written to `${LKPR_VERIFY_DIR:-$HOME/.cache/lkpr-verify}/<timestamp>-<sha>/`,
outside the repo, and survives cleanup:
`doctor.txt`, `tests.log`, `post.log`, `post-batch.log`, `post-summary.txt`,
`prep.log`, `outputs.txt`, `summary.txt`.
Quote `summary.txt` and the test-count line in your report. The test count is the
`N passed, M failed` line.

## Cleanup

The script deletes its temporary HOME and work directories and leaves the evidence.
It exits nonzero if any step FAILs. A SKIP is not a pass. Report SKIPs explicitly.

## Not covered (say so when relevant)

- Real LAMMPS runs and HPC submission.
- Real material slab trajectories/dynamics: TEST-3 covers only an analytic toy
  `p p f` reference; the committed ACE trajectory used by the CLI drive is bulk.
- Visual correctness of figures (only that they are produced).
