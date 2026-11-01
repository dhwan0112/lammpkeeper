# UI-1 — additive Rust CLI

Status: design approved by the maintainer on 2026-11-01 (all decisions below,
unchanged); implemented, reviewed and fully verified;
[PR #46](https://github.com/dhwan0112/lammpkeeper/pull/46). Branch: `gen/ui-1-rust-cli` from main `28e6532`.

ADR-0004 (accepted) sets the direction: Rust owns terminal interaction, Python
owns scientific execution, and the Rust prototype ships under a distinct,
explicitly chosen name. ADR-0004 leaves "prototype executable/distribution
names" to be settled before UI-1, and `INTERFACE-ROADMAP.md` §7 step 1 requires
a design record approved before implementation. This file is that record.

## Proposed decisions

| Decision | Proposal | Reason |
| --- | --- | --- |
| Executable | `lkpr-rs` | Distinct from the Python `lkpr`; no PATH collision or replacement. |
| Crate | standalone `rust/lkpr-rs/` (package `lkpr-rs`, `publish = false`) | Keeps the PyO3 extension in `native/` independent; no Cargo workspace coupling. |
| Backend call | spawn `<python> -m lammpkeeper run --request - --python <python> --timeout T` | Reuses the EXEC-2 supervisor (state, deadline, cancellation, cleanup). Rust does not reimplement job state or science. |
| Diagnostics | `lkpr-rs doctor --python PATH` runs `<python> -m lammpkeeper exec --capabilities` | Reports interpreter, backend version, protocol and operation versions; fails clearly when missing or incompatible. |
| First operation | `lkpr-rs thermo-summary --python PATH --log FILE [--json] [--timeout S]` | Only `thermo.summary` v1 exists in the backend. |
| Output | Human-readable table by default; `--json` prints the backend job snapshot unchanged | Machine mode must not reformat values, units, warnings or provenance. |
| Python selection | `--python`, else `LKPR_PYTHON`, else fail (no PATH guessing) | ADR-0004: explicit environment, no silent fallback or auto-install. |
| Ctrl-C | Forward SIGINT to the `lkpr run` process, wait for its terminal snapshot, exit 130 | `lkpr run` already turns SIGINT into owned cancellation and cleanup. A kill is not reported as cancellation. |
| Unresponsive backend | After timeout + bounded grace, SIGTERM then SIGKILL the `lkpr run` process; report `supervisor_unresponsive`, never `cancelled`/`succeeded` | Visible failure instead of a hang or a false terminal state. |
| Exit codes | 0 succeeded; 1 failed/timed out/invalid; 2 usage error; 130 interrupted | Matches `lkpr run` (0/1/130) plus usage. |
| JSON numbers | `serde_json` with `arbitrary_precision`; integers kept as received, signed-integer strings untouched, `NaN`/`Infinity` rejected | Lossless pass-through; the backend already forbids nonfinite JSON. |
| Dependencies | `serde_json` (with `arbitrary_precision`; `preserve_order` added in review) and `libc` (signals); hand-written argument parsing; `Cargo.lock` committed | Small audit surface; no TUI or async runtime in UI-1. |
| Toolchain | `rust-version` set to the oldest toolchain actually tested (initially the installed stable, 1.98.1) | Only measured toolchains are claimed. |
| Platforms | Linux x86_64 (POSIX) only, as measured | EXEC-2 supervisor is POSIX-only; nothing else is claimed. |
| Distribution | Build from source: `cargo install --path rust/lkpr-rs`; not in the Python wheel; not on crates.io | Rust stays optional; Python-only installs unchanged. |

## Verification plan (done when)

- Parity: direct Python `execute_request`, `lkpr exec`, `lkpr run` and
  `lkpr-rs thermo-summary --json` give identical values, units, warnings and
  error codes for the same log, including a malformed-row log and an
  unresolved-units log (the AGENT-1 eval inputs).
- Failure cases: interpreter path with spaces, missing interpreter, interpreter
  without `lammpkeeper`, incompatible protocol/operation version, malformed
  backend JSON, large output, backend crash, timeout, Ctrl-C (SIGINT to the Rust
  process; supervisor and grandchildren gone afterwards, exit 130), unresponsive
  backend (reported `supervisor_unresponsive`).
- Exact integers: a step near 2**53 and signed-integer strings round-trip
  unchanged through `--json`.
- Installed binary (`cargo install` into a temporary root) with a Python venv
  outside the checkout (installed wheel), and with Rust absent the Python
  `lkpr` and full verifier are unchanged.
- Rust tests: `cargo test` (unit + integration with a fake backend);
  `cargo clippy -D warnings` if available. Full Python verifier still passes.

## Out of scope

TUI (UI-2), MCP (AGENT-2), new scientific operations, Python embedding,
Windows/macOS claims, persistent jobs, remote/HPC execution, replacing `lkpr`.

## Implementation (2026-11-01)

Commit `468cac9`. Files:

- `rust/lkpr-rs/Cargo.toml`, `Cargo.lock` — standalone crate; dependencies
  `serde_json` (features `arbitrary_precision`, `preserve_order`; the latter keeps
  the backend's column order and pulls `indexmap` transitively) and `libc`.
- `rust/lkpr-rs/src/backend.rs` — starts the backend in its own process group,
  feeds stdin, reads stdout on a thread (16 MiB cap), forwards one SIGINT on
  Ctrl-C, and as a last resort SIGTERM/SIGKILLs the backend's group.
- `rust/lkpr-rs/src/main.rs` — strict argument parsing, explicit Python
  selection, `doctor` and `thermo-summary`, human table / verbatim `--json`.
- `rust/lkpr-rs/tests/cli.rs` — 11 process tests with fake backends at first
  implementation; 13 after review (see Verification), 15 after the 2026-11-01
  audit (overflow-then-exit and `--json` write failure).
- `tests/test_rust_cli.py` — 7 tests with the real Python backend, registered in
  `tests/run.py`; they build the binary with cargo and skip visibly without it.

Choices made during implementation, within the approved design:

- Deadlines: the backend gets `--timeout T`; `lkpr-rs` forces termination only
  after `T + 15 s`, or 10 s after forwarding Ctrl-C. Then SIGTERM, 2 s, SIGKILL.
  A forced stop prints `supervisor_unresponsive` and states that the backend's
  child processes were not confirmed cleaned up.
- The backend runs in its own process group so a terminal Ctrl-C reaches only
  `lkpr-rs`, which forwards exactly one SIGINT. A second SIGINT could interrupt
  `lkpr run` during its own cleanup.
- stderr is inherited (diagnostics stay visible); stdout carries only the
  backend JSON in `--json` mode.
- In the test helper, rustup is pointed at the real `~/.cargo`/`~/.rustup` when
  HOME is isolated, because rustup finds its toolchains through HOME.

Known limits: SIGTERM/SIGKILL sent to `lkpr-rs` itself is not forwarded; the
backend then stops at its own timeout. A Ctrl-C in the first moments, before
Python has installed its SIGINT handling, can end `lkpr run` with a traceback
instead of a snapshot; `lkpr-rs` then reports `invalid_backend_output` and still
exits 130. Running from inside the checkout lets any
Python import `lammpkeeper` from the working directory, so `doctor` there does not
prove the package is installed; the installed-binary check below runs outside it.

## Independent review and fixes

A read-only review of `main.rs`/`backend.rs` (no other files) found four issues;
the parent fixed three and documented the fourth (early Ctrl-C, above):

1. `--timeout 1e30` panicked (exit 101) in `Duration::from_secs_f64`. Now
   `Duration::try_from_secs_f64` + `checked_add`; too large is a usage error
   (exit 2). Unit test extended with `1e30` and `1e300`.
2. The request was written to stdin before the supervision loop, so a backend
   that never reads stdin could block `lkpr-rs` forever with no deadline and no
   Ctrl-C forwarding. Now written from a thread. New test
   `ctrl_c_works_while_the_backend_never_reads_a_large_request` (100 KB request,
   above the 64 KiB pipe buffer).
3. After a forced stop, a group member that survived SIGTERM could keep stdout
   open and hang the reader join. `terminate` now detects leader exit with
   `waitid(WNOWAIT)` (the unreaped leader keeps the group id reserved) and always
   SIGKILLs the group before reaping; the stdout wait after exit is bounded (5 s)
   and reported as `backend_stdout_held_open`. New test
   `stdout_held_open_after_exit_is_reported_not_waited_forever`; the
   unresponsive-backend test now uses a grandchild that ignores SIGTERM.
   (EXEC-2's own children use separate pipes — `jobs.py` `stdout=PIPE` — so this
   only matters for broken or foreign backends.)

Fail-before evidence with the pre-review `backend.rs` (`468cac9`): the two new
tests failed (lkpr-rs still running after the 20 s guard) and the updated
unresponsive test hung until killed at 60 s. With the fixes all pass.

## Verification (measured)

- `cargo test` (debug, rustc 1.98.1, Linux x86_64), after the review fixes:
  unit **4 passed**, process tests **13 passed** (~15 s; includes the 15 s
  deadline case).
  `cargo clippy --all-targets -- -D warnings` and `cargo fmt --check` clean.
- Mutation check: with SIGINT forwarding disabled,
  `ctrl_c_is_forwarded_once_and_reports_interruption` fails.
- Real backend (`tests/test_rust_cli.py`, expanded Python 3.12): **7 passed**.
  Without cargo on PATH: **7 skipped** with "cargo not installed".
  Covers: `--json` backend response identical to direct `execute_request`,
  `lkpr exec` and `lkpr run` for the three AGENT-1 eval logs (success,
  unresolved units, malformed row), same exit codes; human table numbers and
  warnings equal the backend's; steps 9007199254740990/…991 and `mtime_ns`
  strings exact in `--json`; venv-style interpreter symlink in a spaced path;
  real Python without `lammpkeeper` (`-I -S`) fails with
  `invalid_backend_output`; Ctrl-C on a FIFO-blocked real job gives exit 130,
  `cancelled`, and no surviving backend process; `--timeout 2` gives `timed_out`
  with complete cleanup and no forced stop.
- Installed check (`/tmp/opencode/ui1-installed-check.sh`): `cargo install
  --locked` into a temporary root, lammpkeeper wheel installed into a venv in a
  spaced path, run from outside the checkout with no PYTHONPATH: `doctor` ok,
  table printed, `--json` backend response identical to the venv's `lkpr exec`.
- Full Python verifier (expanded Python 3.12, isolated HOME), which includes
  `tests/test_rust_cli.py`:
  - pre-review `ab0884e`: native **589/0/0**, forced NumPy **580/0/9**;
  - final `154770d`: native **589 passed, 0 failed, 0 skipped**, forced NumPy
    **580 passed, 0 failed, 9 skipped** (six known native-only checks plus three
    REV-IO-4 native-comparison tests). Post analyses/real plots and prep passed.
    Evidence: `/tmp/opencode/ui1b-native/20261101T113120-154770d-full`,
    `/tmp/opencode/ui1b-numpy/20261101T113121-154770d-full`.
- Installed check rerun on the final code: passed.

Not tested: other OSes, older Rust toolchains, Python 3.9 runtime, MDAnalysis,
pytest, real HPC.
