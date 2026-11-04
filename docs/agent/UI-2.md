# UI-2: Rust TUI for the shared execution contract — design record

Status: **proposed (2026-11-04), awaiting maintainer approval before any code.**
Roadmap §8 step 1 and ADR-0004 ("before UI-2, confirm mappings to the shared
lifecycle") require this record first. Base: main `30f8533`.

## Scope

An interactive terminal front end, `lkpr-rs tui`, that drives the existing
`python -m lammpkeeper run` contract: choose input and environment → confirm
capabilities → run → watch lifecycle events → read the result → cancel.
It reuses the UI-1 process client. It adds no scientific operation, no
competing analysis kernel, no persistent worker and no Python embedding
(ADR-0004). Python-only `lkpr` and the Python API stay unchanged.

Not in scope: porting the prep/post shells, MCP (AGENT-2), Windows/macOS,
remote/HPC, plots inside the terminal, any operation the backend does not
publish in `--capabilities`.

## Facts this design rests on (measured on `30f8533`)

| Fact | Where |
| --- | --- |
| Backend operations: `thermo.summary` v1 only | `lkpr exec --capabilities` |
| Run protocol: request JSON on stdin; final job snapshot JSON on stdout; with `--events`, lifecycle events as JSON lines on **stderr** | `lammpkeeper/jobs.py:669-723` |
| Lifecycle states: `created`, `running`, then one of `succeeded`, `failed`, `cancelled`, `timed_out`; at most four events, each `{sequence, state, elapsed_seconds}` | `jobs.py:51, 371-377` |
| Snapshot fields: `job_id`, `request_id`, `operation`, `operation_version`, `state`, `interpreter`, `handshake`, `error`, `backend_response`, `cleanup{status,reaped,error}`, `diagnostics{handshake,execution}`, `events` | `jobs.py:316-322` |
| UI-1 client: `backend::spawn` (stdin bytes, stdout piped, **stderr inherited**), `backend::supervise` (deadline, SIGINT forwarding, SIGTERM/SIGKILL after grace, bounded stdout 16 MiB, `Forced::{Unresponsive,OutputTooLarge}`, `stdout_held_open`) | `rust/lkpr-rs/src/backend.rs` |
| UI-1 exit codes 0/1/2/130; human table from `print_summary`, raw snapshot with `--json` | `rust/lkpr-rs/src/main.rs` |
| Toolchain: rustc 1.98.1, `rust-version = "1.98"`; dependencies `serde_json`, `libc`; no async runtime | `rust/lkpr-rs/Cargo.toml`, `docs/agent/UI-1.md` |
| Crates available in the local cargo cache (offline build possible): `ratatui 0.30.2` (MSRV 1.88), `crossterm 0.29.0` (MSRV 1.63); no PTY test crate | `~/.cargo/registry/cache` |

## Decisions proposed

| Topic | Decision | Reason |
| --- | --- | --- |
| Where | Same crate, new subcommand `lkpr-rs tui`; modules `src/tui/{app,view,client}.rs` | One binary, one `cargo install`, UI-1 client reused directly. A second crate would duplicate `backend.rs` or force a library split before it is needed. |
| Library | `ratatui` 0.30 + `crossterm` 0.29; std threads + `mpsc`, no tokio | Both cached and widely used; UI-1 already avoids an async runtime. `rust-version` stays 1.98. |
| Terminal support | POSIX terminals with ANSI + alternate screen; 80×24 minimum, reflow above; `TERM=dumb` and non-TTY stdin/stdout refuse with usage error (exit 2) pointing to `thermo-summary` | Measured platform is Linux x86_64 only (UI-1). A TUI on a non-TTY would corrupt piped output. |
| Backend stderr | `client` spawns with stderr **piped** (new option; CLI keeps inherited stderr). A reader thread classifies each line: JSON object with `sequence`+`state` → lifecycle event; anything else → diagnostics text, control characters stripped before display | Events are the only progress source. Uncaptured stderr would draw over the alternate screen. Sanitising closes AUDIT-20261104 E-7 for the TUI path. |
| Progress | Event list with elapsed seconds and a spinner while `running`. **No percentage** | Events are state transitions, not progress (roadmap §8). |
| Request identity | Every run sends a complete request with a fresh `request_id` (UUID); the Result screen shows only a snapshot whose `request_id` equals the current run's. Changing any input field, starting a new run, or cancelling clears the Result screen | No stale success (ADR-0004, roadmap §8 step 5). No cache sharing between runs is assumed. |
| Cancel | `Ctrl-C` or `c` on the Running screen forwards SIGINT to the backend process group (existing `backend` path) and waits for the terminal snapshot; shows `cancelled` only when the backend says so. `Forced::Unresponsive`/`OutputTooLarge`/`stdout_held_open` are shown as those failures, never as cancelled | UI-1 cancellation contract reused unchanged. |
| Result | Same table as `print_summary` (values as received, `arbitrary_precision`), unit system, warnings, `cleanup.status`, `interpreter`, `handshake` versions, `elapsed_seconds`; `s` writes the raw snapshot JSON to a user-named file; `--json` is not a TUI mode | Values, units and provenance identical to the CLI. |
| Errors | `error.code` + message, `diagnostics.execution` tail, exit path back to Setup | Visible failure, no silent repair. |
| Terminal recovery | `std::panic::set_hook` restores the terminal (leave alternate screen, disable raw mode, show cursor) before the default hook; the same restore runs on normal exit and after `Ctrl-C`; SIGTERM to `lkpr-rs tui` restores and exits 1 | Roadmap §8 step 6. |
| Keys | Tab/Shift-Tab move between fields; Enter confirms/starts; `c` cancel; `s` save snapshot; `q`/Esc back or quit (quit on Running asks to cancel first); `?` shows this key list | Small fixed set; documented in `--help`. |

### Screen state model

```text
Setup ──Enter──▶ Check ──ok──▶ Confirm ──Enter──▶ Running ──terminal──▶ Result
  ▲                │ fail                         │ c / Ctrl-C            │ Enter
  └────────────────┴──────── Error ◀──────────────┴───────────────────────┘
```

| Screen | State held | Backend call |
| --- | --- | --- |
| Setup | python path (`--python` → `LKPR_PYTHON` → empty, never PATH-guessed), log file, operation (list from capabilities; one entry today), timeout seconds | none |
| Check | capabilities handshake result or failure | `python -m lammpkeeper exec --capabilities` (as `doctor`) |
| Confirm | resolved request shown verbatim | none |
| Running | `request_id`, start instant, events received so far, diagnostics tail | `python -m lammpkeeper run --python P --timeout S --events` with request on stdin |
| Result / Error | terminal snapshot bound to `request_id` | none |

The reducer `App::apply(Msg) -> ()` is a pure function of UI keys and
client messages (`Event`, `Diagnostic`, `Finished(Outcome, snapshot)`), so it
is unit-testable without a terminal. Rendering reads the state only.

## Threads

- UI thread: crossterm event poll (≤ 50 ms), reducer, draw.
- Per run: one supervisor thread calling the UI-1 `supervise` logic (deadline,
  signals, stdout collection) and one stderr reader thread; both send `Msg` over
  `mpsc`. The UI never blocks on the backend; the backend never blocks on the UI
  (stderr is drained continuously, stdout bounded as in UI-1).

## Compatibility

- `lkpr-rs doctor` and `thermo-summary` keep their behaviour, exit codes and
  inherited stderr; `backend::spawn` gains a stderr-mode parameter with the old
  default.
- No change to Python packages, wheel, `lkpr`, tests under `tests/` except the
  additive Rust parity test.
- Python-only installs: unchanged; without cargo the Rust tests stay skipped.

## Verification plan (done when)

- `cargo test`: reducer tests (every transition, stale-snapshot rejection,
  cancel while running, forced outcomes), `ratatui::backend::TestBackend`
  snapshot renders of each screen at 80×24 and 120×40, stderr classifier tests
  (event line, log line, binary garbage, over-long line).
- Fake-backend process tests (existing `tests/cli.rs` pattern): success,
  malformed JSON, backend crash, slow backend + cancel, backend that writes
  events but never exits (unresponsive), output too large.
- Parity: for the AGENT-1 evaluation logs, the Result screen's table text
  equals `lkpr-rs thermo-summary` output and the saved snapshot equals
  `thermo-summary --json` byte for byte.
- Terminal recovery: automated check needs a PTY crate that is not available
  offline; unless the maintainer allows fetching `portable-pty`, this is a
  recorded **manual** check (normal quit, Ctrl-C on each screen, induced panic,
  SIGTERM) with the terminal state inspected afterwards, labelled as manual.
- Non-TTY: `lkpr-rs tui < /dev/null | cat` exits 2 with the usage message and
  writes nothing else to stdout.
- `cargo clippy -D warnings`, `cargo fmt --check`; Python full verifier
  unchanged (no Python change expected beyond `tests/test_rust_cli.py`).
- Development log in this file; BACKLOG/roadmap status updated only with the
  measured results.

## Open decisions for the maintainer

1. Same binary (`lkpr-rs tui`, recommended) or a separate crate.
2. Whether a second backend operation should be exposed alongside UI-2 so the
   TUI has more than `thermo.summary`. If yes, it is a separate item following
   roadmap §10 (candidates: a dump load/summary or density profile; each needs
   its open REV items checked first). UI-2 itself does not wait for it.
3. PTY test: allow fetching `portable-pty` (network) for an automated terminal
   recovery test, or accept the recorded manual check.
4. Whether `lkpr-rs tui` should also save the diagnostics tail with the
   snapshot when `s` is pressed (proposed: yes, as a second file).

Nothing in this record is implemented. Approval of this record authorises the
single implementation branch `ui-2/tui` under roadmap §3; the completion claim
still depends on the verification above.
