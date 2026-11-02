# REV-VERIFY-1 — verifier must check `mktemp`

## Problem
`verify.sh` ran `TMPHOME="$(mktemp -d)"; WORK="$(mktemp -d)"` unchecked under
`set -uo pipefail` (no `-e`). A failed `mktemp` left the variable empty, so
`HOME` became empty and paths such as `$WORK/post_out` and
`$WORK/post.commands` resolved to `/post_out` and `/post.commands`. The
verifier then kept running tests and `post` against the wrong locations.

## Fix
- Both `mktemp -d` results are checked and asserted to be directories.
- On failure the script prints `FAIL setup — <cause>` to stderr, writes the same
  line to `$EVID/summary.txt` (evidence dir survives), and exits 2 before any
  doctor, test or post step.
- If the second `mktemp` fails, the EXIT trap removes the first directory.
  `cleanup` skips empty variables, so it can never `rm -rf ""`-style expand.

## Evidence (measured)
Test helper: `_run_verifier(..., stubs=, extra_env=, details=)` in
`tests/test_audit_verifier.py` puts a stub `mktemp` first on PATH
(fail always / fail on 2nd call) and logs every fake-interpreter call.
New tests: `test_verifier_refuses_to_run_when_mktemp_fails`,
`test_verifier_refuses_when_second_mktemp_fails_and_cleans_first`.

Run: `cd tests && python -c "import test_audit_verifier ..."` over all `test_*`
(Python 3.11, isolated HOME).

- Before fix: 2 failed, 8 ok. Stderr showed
  `verify.sh: line 88: /post.commands: Permission denied` — the verifier wrote
  to the filesystem root and ran on.
- After fix: 0 failed, 10 ok.

## Limits
- Only `mktemp` failure is covered; other host faults are REV-VERIFY-3.
- Stub covers the `mktemp` found via PATH; an absolute-path call would bypass it
  (the script uses PATH lookup).
- `tests/run.py` registration was not changed by this item.
