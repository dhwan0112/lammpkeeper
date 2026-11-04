# AUDIT-20261104-DOCS: comment and roadmap audit

Status: documentation only, verified (PR #96).
Branch: `audit/comments-roadmap-20261104` from main `faf078a` (PR #95).
Source: maintainer request of 2026-11-04 ("check all code comments/docstrings
and the roadmap") after the REV-REF-2/3/4 merges; AGENTS.md §5 and
[`COMMENT_COVERAGE.md`](COMMENT_COVERAGE.md) (every module, class and function
documented in English; every Rust `fn` preceded by a comment).

## Problem

1. **Comment drift.** Docstrings and comments in `lammps_post/` written for
   earlier revisions no longer matched the code: `cli.py` listed four modes
   (`--find` is a fifth and takes precedence) and claimed preload order did not
   matter for the final state without saying why; `parse_cif` did not mention
   the `ValueError` cases REV-REF-4 added; `_lattice_image_offsets` did not
   list its rejected inputs and `compute_reference_rdf` did not state its
   `None` return for an argument that is neither a str nor a dict; `parse_input`'s
   docstring omitted the conflicting-repeat and `pair_coeff` errors;
   `detect_forcefield` described a frames list that is never empty;
   `analyze_density_profile` and `analyze_penetration` named result keys that
   do not exist (`'depth'`) or described the `'window'`/`'total_atoms'` keys
   loosely; `state.py` `ff_info` comments listed the wrong forcefield names and
   did not say when `unit_system` stays `None` (ADR-0005); `shell.py` type lists
   for `plot`/`analyze` omitted `penetration_trend` and the batch-only types,
   `_analyze_all`/`_analyze_rdf` prompting rules were undocumented, and the
   plotting layout comments described the wrong panels or files.
2. **Missing documentation.** 33 test helpers (nested `run`, `iterate`,
   `indexed`, `lazy`, `_write` helpers and six whole tests) had no docstring;
   the 48 `fn`s of `rust/lkpr-rs/src/tui/*.rs` (UI-2), `Report::line`/`print`
   in `src/main.rs` and one test in `src/tui/mod.rs` had no comment.
3. **Roadmap drift.** `INTERFACE-ROADMAP.md` was last updated at `196f597`
   (PR #61): review table "25 done / 26 open", UI-2 still a candidate, the
   next-step list naming items merged since. `MIGRATION.md` said UI-2 was not
   started. `BACKLOG.md`: the REV-PLOT-2 row used a different format
   (`| REV-PLOT-2 | done (PR #92) |`, counted as open by any first-column
   scan), a blank line inside the review table before the REV-TEST-4 row split
   it into two tables, and the implementation-track paragraph pointed at the
   2026-11-02 checkpoint. `README.md` filed the warned dump-only heuristics
   under GEN-2 (completed 2026-11-01; the heuristics are the ADR-0005 fallback
   it kept) and pointed only at the 2026-10-28 review.
4. **Mislabelled legend.** `plot_penetration_trend` draws a median d/√t
   scaling guide whose legend said "√t fit"; the code comment beside it already
   said it is not a fit.
5. **Stale `help` text.** The `plot` lines said "from cached data", but
   `plot <type>` runs the missing analysis, `plot all` also makes the
   log/structure/snapshot plots, and `plot redo|edit|recipes` were not listed.

## Change

- `lammps_post/cli.py`, `__init__.py`, `parsers.py`, `references.py`,
  `analysis.py`, `state.py`, `plotting.py`, `shell.py`: docstrings and comments
  corrected as listed above; `__init__.py`'s package tree gains `references.py`;
  the `plotting.py` legend literal becomes `√t guide: d=A√t`; the `help` block
  for `plot` in `shell.py` is rewritten. No other string, statement or
  expression changed (see Verification).
- `tests/test_analysis_params.py`, `test_cell_validation.py`,
  `test_dump_whitespace.py`, `test_rdf_extreme_wrap.py`,
  `test_rdf_reference_pair.py`, `test_recipe_alias.py`,
  `test_reference_images.py`, `test_row_width.py`, `test_rust_cli.py`:
  docstrings for the 33 undocumented definitions.
- `rust/lkpr-rs/src/tui/{app,client,mod,view}.rs`, `src/main.rs`: `///`
  comments for 51 `fn`s, each written from the function body.
- `docs/agent/BACKLOG.md`: REV-PLOT-2 row in the shared format, the blank
  line inside the review table removed, implementation-track pointer and a
  2026-11-04 checkpoint (merged PRs #81–#95, table 49 done / 9 open, the
  untriaged `AUDIT-20261104.md` P2 findings, the follow-up below, the
  verification of this PR).
- `docs/agent/INTERFACE-ROADMAP.md`: base commit, UI-2 status, review-table
  counts, completed PRs 2026-11-02 to 11-04, the candidate list for the next
  step, a dated entry in 문서 정비 기록.
- `MIGRATION.md`, `README.md`, `docs/agent/COMMENT_COVERAGE.md`,
  `CHANGELOG.md`: as described in the CHANGELOG entry.
- **Not changed, recorded as follow-up:** `shell.py` `_export_summary` has an
  unreachable `elif isinstance(data, dict)` branch directly after an
  `if isinstance(data, dict)` test on the same value. Dead code; it is left for
  a shell change that carries a test, so this PR stays documentation only.

## Tests

No new tests. The change is documentation plus two user-visible strings that no
test or document pins (checked by searching `tests/`, `lammps_post/`, `docs/` and
`README.md` for "√t fit", "Generate plot from cached" and "All plots from
cached"). The existing suites were run in full.

## Verification

- `ast` comparison of every changed `.py` file against `origin/main` with
  docstrings stripped: identical for 15 of the 17 files; `plotting.py` differs
  only in the legend literal and `shell.py` only in the `help` text block for
  `plot` (symmetric difference of the non-docstring string constants).
- `python3 -m compileall -q lammps_post tests lammpkeeper`: clean.
- Docstring scan over `git ls-files '*.py'`: 119 files, 1765 function/class
  definitions (1884 with module docstrings), 0 missing. Rust `fn` scan over
  `git ls-files '*.rs'`: 197 `fn`s in 8 files, 0 without a preceding comment.
- `cargo fmt --check` and `cargo clippy --offline --all-targets -- -D warnings`:
  clean. `cargo test --offline`: 38 unit + 20 `tests/cli.rs` passed.
- Full runner (`HOME` isolated): native 769/0/26; NumPy (`LKPR_NO_NATIVE=1`)
  756/0/39.
- Pitfall measured while verifying: with `cargo test` started as a background
  `&` job of a non-interactive `sh`, `fake_backend_slow_then_cancelled` and
  `fake_probe_reports_capabilities_or_the_failure` fail after 10 s
  (`supervisor_unresponsive`). POSIX starts such jobs with SIGINT ignored and
  bash keeps the inherited ignore even with `trap ... INT`, so the fake backend
  never sees the cancel and the kill ladder runs out. The same two tests pass in
  0.6 s with SIGINT at its default (a foreground shell, or a wrapper that resets
  `SIGINT` to `SIG_DFL` before `cargo test`). Not a code defect; the BACKLOG
  checkpoint records it for the next person who runs the Rust tests detached.

Not verified: rendering of the changed docstrings by a documentation generator
(none is used); real LAMMPS/HPC execution (unchanged by this PR).

## Review round

Two independent read-only reviews of the diff (`worker-readonly` agents: Read,
Grep and Glob only, no commands).

- **Round 1 (`lammps_post/`, `docs/`; about 70 hunks):** one should-fix and four
  nits, all fixed before commit. The no-dump comment in
  `_get_available_analyses` overstated the list (`oar` and `penetration_trend`
  are ungated but offered only with a dump). INTERFACE-ROADMAP wrote `#69–#74`
  for the REV-IO items although #70 is REV-UI-4, and left the sync PRs
  #62/#75/#81 unlisted. The `detect_forcefield` note on `frames` ignored that
  rule 2 fires without a `type` column. This devlog overstated the
  `compute_reference_rdf` hunk. The figsize presets accept `none` as an alias
  of `reset` that `help` does not list (recorded as a code comment; the help
  text is unchanged). The reviewer confirmed the BACKLOG count (58 rows, 49
  done, 9 open), the untriaged AUDIT-20261104 list, and that the diff has no
  non-comment change beyond the two declared strings.
- **Round 2 (`rust/`, `tests/` hunks):** one should-fix and three nits, all
  fixed before commit. `save_key` said Enter writes "the snapshot and report"
  (it queues a save of the raw snapshot and the stderr tail); `done_key` listed
  scrolling, which `key()` consumes before dispatch; `_fake_reference` "records"
  nothing (the mock in `_driven` does); `Report::print` now mentions the
  trailing newline `print_raw` adds.
- Not read by either reviewer: the `app.rs` test helpers `fresh`/`keys`/`caps`/
  `snapshot`, `view.rs` `help`/`HELP` and its test helpers,
  `_brute_force_counts` internals, `test_rust_cli.py` lines 440–505,
  `_rdf_reference_pair` and `_unload_source`. Those comments were written from
  the code by the author; the scans and test runs check only presence and
  behaviour.
