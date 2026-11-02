# REV-VERIFY-3 — verifier evidence retention must be checked

## Problem
`verify.sh` did not check several evidence writes: `cp ... post-summary.txt`
(recorded after `PASS post`), `outputs.txt` writes, the `doctor.txt` redirect and
the final `tee summary.txt`. The exit status was decided by `grep '^FAIL'` on the
re-read `summary.txt`. A denied evidence copy therefore exited 0
(measured earlier, see `docs/agent/PRIOR-WORK-REVIEW-20261029.md`).

## Fix
- New `evidence_fail` records `FAIL evidence — <what>` (and echoes it to stderr).
- `post-summary.txt` copy is checked; a failed copy removes any partial file.
  If post ran but `summary.txt` is missing, that is also `FAIL evidence`.
- `outputs.txt` create/overwrite/append and the `doctor.txt` redirect are checked.
- Exit status comes from the in-memory `RESULTS` array. A failed `summary.txt`
  write adds a FAIL and exits 1.

## Evidence (measured)
New test `test_verifier_fails_when_post_summary_evidence_cannot_be_retained`
uses a `cp` stub that fails only for a destination ending in `post-summary.txt`
and delegates to `/bin/cp` otherwise. Run over all `test_*` functions in
`tests/test_audit_verifier.py` (Python 3.11, isolated HOME):

- Before fix: new test fails with exit code 0 and
  `PASS post — analyze all; required analyses persisted`, no FAIL line.
- After fix: 11 ok, 0 failed, including both positive controls
  (`..._accepts_complete_nonempty_smoke_outputs`, `..._quick_analysis_evidence_...`).

## Limits
- Only the `post-summary.txt` copy fault is injected by a test; the other
  checked writes (outputs.txt, doctor.txt, summary.txt) are not fault-tested.
- `PASS post` still appears next to `FAIL evidence`; the exit code is nonzero.
- `tests.log`/`post.log` redirects are not separately checked (a failure there
  already fails the tests/post step).
