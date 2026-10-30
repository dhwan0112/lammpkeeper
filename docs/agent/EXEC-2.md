# EXEC-2 — local process-owned execution lifecycle

Published implementation: `417672f`, [PR #30](https://github.com/dhwan0112/lammpkeeper/pull/30),
stacked on EXEC-1 PR #29 and awaiting merge.

## Status and scope

Implemented and verified on `gen/exec-2-local-job-lifecycle`, based on EXEC-1 `609185e`
(PR #29). Before starting, parent audited and reran all six native-only tests
skipped in forced-NumPy mode: **6 passed, 0 failed, 0 skipped**. The exact tests
and preceding full-run evidence are recorded in `EXEC-1.md`.

The maintainer requested continuation and reiterated that development/execution
logging and English code comments must always be maintained. New classes,
functions and tests carry intent/contract docstrings; nonobvious lifecycle,
transport and cleanup branches explain their invariants. This log records
design decisions, review findings and measured verification separately.

## Pre-implementation lifecycle decision

Add `lammpkeeper/jobs.py` as a Python application-side local supervisor, and
additive `lkpr run` routing in `lammpkeeper/cli.py`. No existing modules move.
The scientific backend remains EXEC-1 `thermo.summary`; the supervisor launches
the chosen Python environment and validates its capability/result envelopes.
It does not import a terminal shell or implement any statistics itself.

The initial supervisor requires POSIX process groups and non-reaping `waitid`
(`WNOWAIT`); embedding applications must not independently reap its children.
Keeping an exited leader waitable reserves its PID/group ID until group signaling
finishes, avoiding accidental signals to a reused process group.
This is a bounded ownership model for a live Python caller, not a persistent job
service. There is no cross-invocation status database, daemon, restart recovery,
scheduler submission or remote execution. Rust and MCP can later wrap this
contract without requiring a TUI or changing the scientific operation.

### Python API and state

`start_job(request, python=None, timeout=60.0, cwd=None)` creates a `LocalJob`.
Invalid submissions return a failed handle with structured diagnostics, rather
than falling back to another environment or starting scientific execution.
The request and caller working directory are frozen at submission. Each job has
a local UUID independent of its EXEC-1 request ID; concurrent jobs may use the
same request ID. The supervisor thread owns child processes and bounded I/O.

- `snapshot()` returns detached state, diagnostics, provenance and event history.
- `wait(timeout=None)` waits for terminal publication. Its timeout limits only
  the caller's wait and raises `TimeoutError`; it does not cancel the job.
- `cancel()` requests idempotent cancellation and returns the current snapshot
  without waiting; already-terminal jobs stay final.
- States: `created` → `handshaking` → `running` → `succeeded` / `failed` /
  `cancelled` / `timed_out`. Failure, timeout or cancellation can occur before
  `running`. Exactly one terminal transition is committed under synchronization.
- A cancellation accepted before terminal publication prevents success from
  being published; a completed terminal decision is immutable. The child is
  cleanup attempt finishes before terminal state is exposed; unsuccessful cleanup
  must remain explicitly visible in the snapshot. Failed/timed-out/cancelled jobs
  cannot expose a previously received success as a current scientific result.

Accept cancellation only before the overall deadline; such an accepted request
wins even if cleanup crosses the deadline. A cancellation attempted at/after the
deadline cannot replace timeout. Success may commit only before that deadline
and without accepted cancellation. Cleanup grace never makes late success valid.

The job timeout uses a single monotonic deadline covering handshake and execution,
including transport and response validation. It must be finite and positive;
booleans are invalid. Termination has an additional bounded grace interval so
cleanup can complete. A child's own group is terminated, then killed if needed,
and the direct child is reaped when the OS permits it. Failed signaling/reaping
must retain a visible cleanup error even when cancellation/timeout takes priority
as the terminal state. Descendants retaining pipe descriptors are handled with
bounded drain/cleanup waits. Parent SIGKILL, uninterruptible OS operations and
descendants deliberately escaping process groups are outside the ordinary cleanup
guarantee; a finite wait cannot guarantee forced reaping in those conditions.

### Environment and compatibility

Selection order: explicit `python` → `LKPR_PYTHON` → the caller's `sys.executable`.
Freeze inherited environment, PATH lookup, absolute launch path and deadline at
submission and reuse them for both children. Relative interpreter paths resolve
against the frozen submission cwd; `cwd=` controls backend execution/input paths.
Unset and empty values differ: an empty explicit/environment selection fails,
rather than falling back. Bare executable names use deterministic PATH lookup;
paths preserve the selected interpreter symlink, so venv identity is not lost
by resolving it to a base interpreter. No shell interpolation or automatic
package installation occurs. Record selection source, absolute launch path,
child-reported executable and versions. Preserve caller cwd/environment, with
backend history disabled.

First child: `python -m lammpkeeper exec --capabilities`. Before scientific
execution, require a valid success envelope, exit 0, protocol 1, envelope operation
`capabilities` version 1 and null request ID, with `thermo.summary` version 1
advertised in its result, and backend package version matching this supervisor.
The child Python/NumPy versions are recorded, not required to equal the parent's.
Actual execution provenance must match the handshake's package, interpreter,
Python and NumPy version fields. This is version/capability compatibility, not
proof of immutable binaries/source between two processes or an exact build hash.
No fallback environment is attempted after failure.

### Transport, result publication and logs

Second child: `python -m lammpkeeper exec --request -`, with the same bounded
EXEC-1 request written to stdin and stdin then closed. Drain stdout and stderr
concurrently to avoid pipe deadlocks. Bound each stream, request, retained
diagnostic and event history; oversize output cannot exhaust unbounded memory.
Each child stdout and stderr is limited to 1 MiB; either overflow fails transport.
Retain the first 1024 stderr characters per phase. Error messages are also bounded
to 1024 characters. At most four lifecycle transitions are retained without
dropping events. Cleanup uses 0.15 s TERM grace, 1 s reap wait and 0.15 s final
pipe drain, with 0.02 s polling granularity.
Require strict UTF-8 and exactly one JSON response document, rejecting duplicates,
nonfinite numbers, foreign request IDs/operations and incompatible schemas.

Success requires a valid `succeeded` backend response and exit 0. A genuine
backend failure requires `failed` with exit 1. Contradictions, malformed output,
crashes, timeouts or cancellations are supervisor failures, not scientific
success. Preserve useful bounded stderr and backend warnings. The current
operation writes no artifacts; this stage does not promise artifact persistence.

Every state transition is recorded with an ordered sequence and elapsed time.
These are lifecycle observations, not invented scientific percentage progress.
Use retained events for polling/diagnosis; CLI `--events` additionally streams
JSON state events to stderr. Machine stdout remains one final JSON snapshot.

Job snapshots use `job_schema_version: 1` and contain job/request identity,
state, frozen cwd/timeout, interpreter selection, handshake versions, bounded
per-phase diagnostics, events, error and validated `backend_response`. That
response is retained only for genuine backend success or exit-1 failure; local
transport errors, cancellation and timeout cannot publish it. Snapshot data is
detached from the caller and the supervisor's mutable state. Logging also uses
the module logger for lifecycle events; it does not configure an application's
global handlers or write protocol data to stdout.

Every snapshot also contains `cleanup: {status, reaped, error}`. Status is
`not_required` before any child, `pending` while cleanup is outstanding,
`complete` after confirmed cleanup, or `failed` with a bounded `cleanup_failed`
diagnostic. `reaped: false` means unconfirmed, not proof that a process is alive.
This separate diagnostic survives primary cancellation/timeout arbitration.
Signal failures do not bypass subsequent kill/reap attempts; failed cleanup is
not implicitly retried in a way that could erase its first diagnostic.

### CLI

The same-process Python handle is suitable for later UI/MCP adapters:

```python
import json
from lammpkeeper.jobs import start_job

with open("request.json", encoding="utf-8") as stream:
    request = json.load(stream)
job = start_job(request, python="/path/to/environment/bin/python", timeout=60)
current = job.snapshot()  # detached status/events; no blocking analysis call
final = job.wait()        # or job.cancel(), then job.wait() to inspect cleanup
```

Always inspect both terminal state and `cleanup.status`; a cancelled/timed-out
job with failed cleanup does not certify termination of every child. Only a
validated `succeeded` job publishes a successful backend response.

```bash
python -m lammpkeeper run --request request.json \
  --python '/path/to/environment/bin/python' --timeout 60 --events
```

`--request -` reads one bounded request from stdin. The CLI waits for its own job.
CLI request reading happens before job creation and is outside `--timeout`.
Filesystem lookup and process creation are synchronous OS operations that this
supervisor cannot forcibly interrupt; the deadline is enforced once control
returns, rather than promising an unconditional wall-clock bound.
Status and cancellation of an existing job are currently same-process Python
API operations, not separate durable CLI commands. Ordinary success exits 0;
failure/cancellation/timeout exit 1. Ctrl-C exits 130 after requesting cancellation
and bounded cleanup. Help remains human text.
If the Ctrl-C cleanup wait expires, stdout instead reports an honest nonterminal
observation with `cleanup_wait_timeout`, no backend response and no invented
terminal event. Cleanup status is `incomplete` unless a failure is already known.
The handler still returns 130; a non-daemon supervisor blocked in an
uninterruptible OS operation may delay actual interpreter exit. The observation
does not mutate the job's state or falsely claim completed cancellation.
Existing `exec`, prep/post and interactive commands retain their contracts.

## Validation plan

- Synthetic and Fe-O summary parity with EXEC-1; explicit interpreter/cwd paths
  containing spaces, venv symlink preservation and isolated installed-wheel use.
- Explicit/env/default precedence, empty/missing interpreter failures and no
  fallback; malformed/mismatched capabilities stop before analysis starts.
- Strict response identity, version, schema and exit-status consistency; errors,
  invalid UTF-8, duplicate keys, nonfinite values and excessive output.
- Concurrent pipe draining, whole-job deadline, handshake/run cancellation,
  SIGTERM escalation and descendants holding descriptors after leader exit.
- Frozen requests/cwd, detached snapshots, repeated cancel/wait, terminal race
  semantics, exactly one terminal event and concurrent equal request IDs.
- Nonterminal CLI, clean stdout/events separation, Ctrl-C, bounded diagnostics
  and no history writes. Full verifier after integration, explicit optional skips.
- All new functions/classes/tests have English intent docstrings; review comments
  on state publication, interpreter selection, transport and process ownership.

## Implementation review (2026-10-30)

The initial implementation passed **27 focused tests** and quick verification
**480 passed, 0 failed, 8 skipped** (six native-only checks and two opt-in slow
checks). This is interim evidence, not final acceptance. Independent source
review confirmed interpreter/environment freezing, strict transport identities,
deadline arbitration and reserved-leader cleanup, but found a blocker: cleanup
failure could be overwritten by cancellation/timeout. Parent independently
identified the same issue and requested explicit retained cleanup diagnostics,
fault-injection regressions and structured reporting if Ctrl-C cleanup waiting
expires. Final verification follows those corrections.

All three reviewer findings are now corrected: independently retained cleanup
health, structured Ctrl-C wait-expiry reporting, and ASCII decimal fingerprint
validation (only timestamp permits one initial minus). New fault-injection
regressions first reproduced **3 failures**, then the correction cases passed
**5/0**; the full jobs module passed **32 tests**. Tests use real cleanup followed
by injected failure or a no-process harness, rather than deliberately leaking
children. Independent final source review approved the corrections.

## Parent integration checks (measured)

- Built a pure-Python wheel in an isolated source snapshot and installed it into
  a real venv whose path contains spaces. From outside any checkout, a parent
  using the installed API launched that selected venv without PYTHONPATH-based
  source access. The venv interpreter symlink and child-reported identity were
  preserved through discovery and execution.
- Independent three-row real-unit log: temperature mean **4 K**, pressure mean
  **20 atm**, sample count **3**. Both API and CLI results agreed; ordered events
  were `created`, `handshaking`, `running`, `succeeded`, cleanup was confirmed,
  and subsequent cancel/wait left the terminal snapshot unchanged.
- An explicitly missing interpreter failed without fallback. CLI stdout was one
  JSON result; `--events` stderr exactly matched its recorded state events. stdin
  was closed and no history files appeared.
- All new function/class/test definitions have English docstrings, all changed
  Python files parse with Python 3.9 grammar, and executable/test files match the
  isolated native verification snapshot byte-for-byte. These are Python 3.11
  runtime checks, not a Python 3.9 runtime claim.

Evidence root: `/tmp/opencode/lkpr-exec2-integration.tbeqQm`, including
`check_installed.py`, `installed-check.json`, wheel, selected venv and source
snapshot. Native verification reuses the isolated extension only after matching
its Rust source, Cargo manifest and lockfile to this branch. No native binary
is installed in the working repository.

## Final verification (measured, 2026-10-30)

- Native full verifier: **493 passed, 0 failed, 0 skipped**; post analysis/plots
  and prep artifacts/script syntax passed.
  Evidence: `/tmp/opencode/lkpr-exec2-full-native/20261030T194553-nogit-full`.
- Forced NumPy full verifier: **487 passed, 0 failed, 6 skipped**; the same
  post/prep checks passed. Skips are the six native-only tests listed in EXEC-1's
  audit. Parent matched every skip to an explicit PASS in this final native
  run's `tests.log`, so none is left without native execution evidence.
  Evidence: `/tmp/opencode/lkpr-exec2-full-fallback/20261030T194534-609185e-full`.
- Native pytest with slow tests enabled: **493 passed**, 79 warnings, 180.40 s.
- `git diff --check`, snapshot equality, Python 3.9 syntax and new-definition
  docstring coverage passed. Fixtures, goldens, packaging dependencies and Rust
  sources are unchanged. No binaries are committed.

Runs used mlff Python 3.11.15, isolated HOME and `/tmp/opencode`. MDAnalysis is
unavailable. Python 3.9 runtime, non-POSIX platforms, real LAMMPS/HPC and external
agent/Rust/MCP clients remain unverified. Counts exclude separate unmerged
PRs #26/#27. Architecture/impact review was performed directly with independent
source review; unavailable `/architect`, `/interrogate` and `/blast-radius`
playbooks are not claimed as executed.

## Next stage

After verified EXEC-2, AGENT-1's portable skill and UI-1's additive Rust client
can independently use the execution boundary. UI-2 and AGENT-2 reuse the defined
lifecycle rather than inventing separate state or scientific semantics.
