# REV-RS-2: lkpr-rs human mode reports write failures and shows control characters escaped

Status: fixed and verified (PR #87).
Branch: `fix/rev-rs-2-human-output` from `679e9bf` (REV-RS-1 branch head; rebased onto main after PR #86).
Source: AUDIT-20261104 findings E-3 (P3, `println!` panic on a closed or full stdout) and E-7 (P3, backend text printed unsanitised).

## Problem

E-3: the human-mode report (`doctor` lines, `print_summary`, `print_table`,
`--help`, `--version`) used `println!`, and the final error line used
`eprintln!`. Rust ignores SIGPIPE, so a closed pipe (`| head -0`) or a full
disk (`/dev/full`) made `println!` panic with "failed printing to stdout" and
exit 101 after the job had already run. `--json` was fixed in AUDIT-20261101
through `print_raw` (`output_write_failed`, exit 1); human mode was not.
Measured on `679e9bf`: `thermo-summary` with stdout on `/dev/full` panicked at
`library/std/src/io/stdio.rs:1166` and exited 101.

E-7: every backend string (error messages that quote log content, warnings,
captured stderr, paths, column names) reached the terminal unchanged, so a
crafted log could inject terminal escape sequences, and a column name with a
line feed could add a table row.

## Change

- `Report` collects the human-mode lines in memory; `doctor`, `summary`
  (was `print_summary`) and `table` (was `print_table`) append to it and the
  caller writes it once through `print_raw`, which already maps a write error
  to `output_write_failed` (exit 1). `--help` and `--version` go through
  `print_raw` too. `exit_with` writes the error line with `writeln!` and
  ignores a stderr write error: there is nowhere left to report it, and the
  exit status must stay 1 or 2, not become a panic's 101.
- `visible(text)` escapes control characters: `\n`, `\r`, `\t` by name and
  every other `char::is_control()` character (C0, DEL, C1) as `\u{..}`.
  `text()` applies it to every backend string, column names go through it
  directly, and captured stderr (`diagnostics.handshake/execution`) goes
  through `visible_block`, which keeps line feeds as line breaks. `--json`
  output is the backend's bytes, unchanged. A diagnostics value that is not a
  string is no longer printed (before, a number would have been); the schema
  defines it as a string.

Decisions recorded here (user asked for no questions):

- Escape, not strip: a user reading `parse_error: bad\u{1b}[2Jline` learns
  what the log contained; silently dropping bytes would hide it.
- Scope is `char::is_control()` (Unicode category Cc). Bidirectional
  overrides and zero-width characters are left alone; they are not terminal
  commands, and the Python CLI prints them too.
- The backend's own stderr is inherited by the child process and is not
  routed through `lkpr-rs` (ADR-0004: Python owns what it prints directly);
  the escaping covers what `lkpr-rs` itself formats.
- Human mode with a closed pipe now exits 1 with `output_write_failed: Broken
  pipe`; the same as `--json`. Scripts that only wanted the first lines should
  use `--json` and a JSON tool, or accept the status.

## Verification

- `rust/lkpr-rs/tests/cli.rs`: `human_mode_write_failure_is_not_success`
  (thermo-summary and `--help` on `/dev/full` exit 1 with
  `output_write_failed`, no "panicked"; a usage error with stderr on
  `/dev/full` exits 2) and `human_mode_makes_backend_control_characters_visible`
  (ESC, CR and BEL in error message, warning and execution stderr appear as
  `\u{1b}`, `\r`, `\u{7}`; stderr block keeps its line break; `--json`
  byte-for-byte). Both fail on `679e9bf`: the first with the stdio panic
  above (exit 101), the second because raw ESC bytes reach stdout.
- `src/main.rs` unit test `backend_text_is_made_visible`: `visible`,
  `visible_block`, `text`, and a column named `T\nemp` producing one escaped
  table row (three report lines).
- `cargo test --offline`: 5 unit + 19 integration tests pass; `cargo fmt
  --check` and `cargo clippy --all-targets` clean.

| Suite | Result |
|---|---|
| `cargo test --offline` | 24 passed, 0 failed |
| `tests/test_rust_cli.py` (`HOME` fresh, `/usr/bin/python3`) | 7 PASS, 0 FAIL |

Not changed: E-4 (a backend descendant holding stdout after the leader exits
is reported, not killed) is a design choice recorded in the audit and left as
is.
