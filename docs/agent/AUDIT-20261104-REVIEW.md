# AUDIT-20261104-REVIEW: review of PRs #97–#99, logging and documentation pass

Status: PR #100. Base main `96df725` (PR #99).
Requested by the maintainer on 2026-11-04 after PR #99: switch from new backlog items to a
whole review, logging and documentation pass.

## Scope

- Code review of the three AUDIT-20261104 fixes merged on 2026-11-04: REV-IO-11 (#97, dump
  `ITEM: UNITS`/`ITEM: TIME`), REV-IO-12 (#98, dump step-order warning) and REV-UI-6 (#99,
  z-range prompts). Diff `faf078a..96df725`, read in full by a read-only reviewer and
  re-checked by the parent.
- Mechanical checks: AST docstring scan of every tracked Python file, `//`/`///` scan of every
  tracked Rust `fn`, repeated `cargo test` runs to chase intermittent failures.
- Records: AUDIT-20261104 table and status, BACKLOG checkpoint, INTERFACE-ROADMAP counts,
  COMMENT_COVERAGE, docstrings and `help` text that describe the new behavior.

## Findings and fixes

No high or medium finding. Three low findings, all fixed with a failing-first test:

1. **Provenance warnings showed only once per Python session.** The step-order warning
   (REV-IO-12) and the heuristic-metadata warnings use `warnings.warn`; under the default filter
   Python shows a given message from a given line once. Loading the same dump again in the shell,
   after `unload`, printed nothing the second time. `LammpsPostShell.onecmd` now runs each command
   inside `warnings.catch_warnings()`, which resets the once-registry for that command without
   changing filters (an `error` filter set by a caller still raises; checked on Python 3.14.4).
   Test: `test_dump_step_order.test_reloading_the_same_dump_warns_again_in_the_shell`.
2. **The common plot options still parsed z-focus by hand.** REV-UI-6 moved the pressure,
   density, structure and snapshot prompts to `_parse_z_range`, but `_iplot_common_opts` (the z-focus
   question of the charge_z, oar, penetration, penetration_trend and dissociation plots) kept its own `:`/`,` split and ignored a negative bound or a typo
   silently. It now uses `_parse_z_range`; `full`, `full range`, `none`, `all` or an empty answer
   clear the focus, and a malformed answer keeps the current focus and prints the parser's message.
   Test: `test_z_range_prompt.test_common_opts_z_focus_parses_signed_ranges_and_warns_on_typos`.
3. **Blank line between a preamble item and its value: index path disagreed.** For
   `ITEM: UNITS\n\nmetal`, the stream path raised, while `_preamble_before` (index and lazy
   paths) read the blank line as the value position and skipped the item. It now walks back over
   blank lines and, when the first non-blank line is `ITEM: UNITS` or `ITEM: TIME`, validates it
   with the same `_accept_units`/`_parse_time` call, so every path raises the same error.
   Test: `test_dump_units_time.test_blank_line_between_item_and_value_raises_on_both_paths`.

All three tests fail against main's code (main's `shell.py`/`parsers.py` swapped in) and pass
here.

### Rust test flakes

`cargo test` in `rust/lkpr-rs` failed in about 4 of 17 runs on this host, in two ways:

- `tui::tests::input_ready_distinguishes_data_timeout_and_hang_up` (`unwrap_err` on `Ok(true)`):
  the test helper `pipe()` used `libc::pipe`, so the write end leaked into children forked by
  tests running in parallel and the reader never saw hang-up. The helper now uses
  `pipe2(O_CLOEXEC)`; the hang-up check polls until the error with a 5 s deadline; the POLLNVAL
  probe uses an fd number that is never open instead of the just-closed reader.
- `tui::client::tests::fake_*` (`Text file busy (os error 26)`): the helper wrote the fake
  backend script and executed it at once, while a child forked by another test could still hold
  the write fd. The helper now writes a source file and installs it with `install -m 755`, so the
  executed file is never open for writing in this process.

After the change: 0 failures in 13 consecutive runs.

## Documentation

- Docstrings: `DumpReader`, `parse_dump`, `DumpReader.index` (UNITS/TIME errors, step-order
  warning), `do_load`/`_load_source` (dump units as explicit evidence, rollback on conflict,
  step-order warning), `_preamble_before`, `onecmd`, `_iplot_common_opts`. A misaligned line in
  the `parse_dump` return description is fixed.
- `help`: the PLOTTING block states the z-range forms; `set figsize` lists every preset and
  `reset`, as the setter accepts.
- Comment scan: 122 Python files / 1822 definitions, 0 missing (before: 21 test definitions from
  #97–#99). Rust: 197 `fn`s in 8 files, 0 missing.
- `AUDIT-20261104.md`: P2 table marks E-1, A-1, B-R1, C-1 as fixed; triage progress line.
- `BACKLOG.md`: row and checkpoint. `INTERFACE-ROADMAP.md`: base commit, counts (53 done, 9 open),
  untriaged list B-1, B-2, C-2, D-1, D-2. `COMMENT_COVERAGE.md`: measurement. `REV-UI-6.md`:
  follow-up note.

## Verification

Full runner: native 798 passed / 0 failed / 26 skipped; NumPy (`LKPR_NO_NATIVE=1`)
785 / 0 / 39 (main: 795/0/26 and 782/0/39; +3 each). `cargo test --offline` 38 unit + 20 CLI
passed in 3 consecutive runs (plus the 13 flake-hunting runs above); `cargo fmt --check` and
`cargo clippy --all-targets -D warnings` clean. `git diff --check` and `compileall` clean.

## Not changed

- The unreachable `elif` in `shell.py` `_export_summary` (noted in the #96 checkpoint) stays for
  the next shell change with a test.
- Open AUDIT-20261104 P2 items B-1, B-2, C-2, D-1, D-2 and the open review rows are untouched.
