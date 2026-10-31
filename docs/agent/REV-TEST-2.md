# REV-TEST-2 — load-tolerant overall job timeout test

Status: implemented; full verification in progress.
Branch: `fix/rev-test-2-job-timeout-flake`, from main `f44f043` (PR #26 merged).
Requested by the maintainer on 2026-11-01: record the flaky test, then fix it.

## Finding

While re-verifying PR #27 after merging main, the full verifier failed once in
`test_jobs.test_overall_timeout_includes_handshake_and_execution_and_reaps`
(EXEC-2, unrelated to the charge-region change):

```text
FileNotFoundError: ... /execution.started
```

Evidence: `/tmp/opencode/ra2-native/20261101T000354-2ad6684-full` and
`/tmp/opencode/ra2b-native/20261101T001933-2916fde-full`.

The test gave the whole job 0.3 s and expected the execution child to start.
Reaching execution needs the handshake child and then the execution child, each
a fresh Python process. Measured with the unchanged fake interpreter
(`/tmp/opencode/rt2-measure.py`, 20 runs, unloaded): start→`execution.started`
**min 0.251 s, median 0.270 s, max 0.295 s**. The budget had almost no margin,
so on a slower or busier host the deadline expired during handshake and the
execution sentinel never existed. The handshake case has the same weakness: if
startup exceeds 0.3 s, `handshake.started` is not written either.

This is a test defect. The supervisor behaved correctly (it timed out at the
deadline and reported `timed_out`). `lammpkeeper/jobs.py` is not changed.

## Failing-first evidence (original test, measured)

- Unloaded, unpatched: **1/30** failures.
- Eight busy CPU loops on an 8-CPU host: **10/10** failures.
- A 0.1 s startup delay inserted into every fake child
  (`/tmp/opencode/rt2-startup-delay.py 0.1 3`): **3/3** `FileNotFoundError`.
- The original test also **did not detect** a mutant that restarts the deadline
  before the execution child (`/tmp/opencode/rt2-mutant.py`): one overall
  deadline was its stated contract, but the execution case had no slow
  handshake, so a per-phase timer still timed out within the old 3 s bound.

## Fix

- Handshake case: 1.5 s overall budget; the handshake pauses; elapsed must be in
  `[timeout, 3.5 s)`.
- Execution case: 3.0 s budget; the handshake sleeps 1.5 s, then execution
  pauses. One shared deadline stops near 3.0 s. A per-phase deadline cannot stop
  before about 1.5 s + startup + 3.0 s ≥ 4.5 s, so the bound `elapsed < 4.4 s`
  rejects it. About 1.2 s remains for both startups before the deadline and
  about 1.4 s for termination and reaping after it.
- A missing phase sentinel now fails with `"<phase> never started within <t> s"`
  instead of `FileNotFoundError`.
- The other assertions are kept: `timed_out` state and error code, no backend
  response, and the started child process is no longer alive.

The test now takes about 5 s instead of about 0.6 s.

## Verification after the fix (measured)

- 0.1 s and 0.3 s startup delays: **3/3** and **3/3** PASS.
- Eight busy CPU loops: **10/10** PASS (original: 0/10).
- Per-phase-deadline mutant: **killed**
  (`AssertionError: ('execution', 3.0, 4.896...)`); original test: survived.

Full verifier results are recorded below when complete.

## Limits

Timing tests on a shared host can still fail under extreme overload (for example
startup slower than about 1 s per child). The margins are now several times the
measured unloaded startup. No other `test_jobs` test uses a sub-second budget.
