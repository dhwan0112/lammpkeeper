# REV-RS-1: lkpr-rs rejects non-UTF-8 arguments and LKPR_PYTHON as usage errors

Status: fixed and verified (PR #86).
Branch: `fix/rev-rs-1-argv-utf8` from main `7ccaa1d`.
Source: AUDIT-20261104 finding E-2 (P3, panic exit 101 on non-UTF-8 argv).
ID note: `RS` is the review-follow-up area for `rust/lkpr-rs` (UI-1, ADR-0004).

## Problem

`main` collected `std::env::args()`, which panics when any argument is not valid
Unicode. Linux paths are arbitrary bytes, so `--log` or `--python` naming a
file with a non-UTF-8 name aborted with a panic message and exit 101, outside
the documented exit statuses 0/1/2/130. Measured on unmodified code:
`lkpr-rs thermo-summary --log $'run\xff.log' --python /bin/true` printed
`thread 'main' panicked at .../library/std/src/env.rs:878:51` and exited 101.

`select_python` read `std::env::var("LKPR_PYTHON")` and folded the
`NotUnicode` error into the "no Python environment selected" message, so a
non-UTF-8 value was reported as if the variable were unset.

## Change

- `utf8_args` collects `std::env::args_os()` and converts each argument with
  `OsString::into_string`; the first non-UTF-8 argument is a usage error
  (exit 2, usage text printed) naming its position and the lossy text:
  `argument 3 is not valid UTF-8: "run�.log"`. It runs before the
  `--help`/`--version` check, so no code path sees an `OsString`.
- `select_python` reads `std::env::var_os("LKPR_PYTHON")`: unset keeps the
  existing message; empty says `LKPR_PYTHON is empty`; non-UTF-8 says
  `LKPR_PYTHON is not valid UTF-8: "..."`. All three exit 2.
- The failure reporting at the end of `main` moved into `exit_with` so the
  argument error and the command result take the same path (including the
  Ctrl-C mapping to 130 for exit-1 failures).

Decision recorded here (user asked for no questions): non-UTF-8 paths stay
unsupported by `lkpr-rs` rather than threaded through as `OsString`. The log
path travels to the backend inside the JSON request, which carries text only,
and the interpreter path is echoed in every message; a clear usage error is the
honest behaviour for both. `lkpr run` itself (Python) accepts such paths
through its own argv if anyone needs them.

## Verification

- `rust/lkpr-rs/tests/cli.rs`: `non_utf8_arguments_are_usage_errors` (exit 2,
  message names argument 3, usage text present, no "panicked") and
  `non_utf8_or_empty_lkpr_python_is_named` (non-UTF-8 value named, not reported
  as unset; empty value named). Both fail on `7ccaa1d`: the first with the
  `std::env` panic above, the second with "no Python environment selected".
- `cargo test --offline`: 4 unit + 17 integration tests pass (15 + 2 new);
  `cargo fmt --check` and `cargo clippy --all-targets` clean.
- Python side `tests/test_rust_cli.py` (real backend, binary rebuilt by cargo):
  see the table below.

| Suite | Result |
|---|---|
| `cargo test --offline` | 21 passed, 0 failed |
| `tests/test_rust_cli.py` (`HOME` fresh, `/usr/bin/python3`) | 7 PASS, 0 SKIP, 0 FAIL |

Not changed: E-3 (human-mode `println!` on a closed or full stdout) and E-7
(unsanitised backend text in human mode) are separate items (REV-RS-2).
