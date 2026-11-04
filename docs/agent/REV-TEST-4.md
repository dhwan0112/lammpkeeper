# REV-TEST-4: the stale-cache export test skips visibly without pandas

Status: fixed and verified (PR #90).
Branch: `rev-test-4/export-skip` from `37a0989` (main after PR #89).
Source: BACKLOG REV-TEST-4 (P3, found during UI-2 verification: the full runner had one environment-caused failure in both backend modes).

## Problem

`test_stale_cache.test_unchanged_source_plot_and_export_still_work` ran
`export csv msd_Fe` and asserted success. Every tabular export in
`lammps_post/shell.py` (`csv`, `latex`) goes through `_require_pandas`, so on
a host without pandas the command fails with `export csv needs pandas, which
is not installed` and the test failed instead of skipping like the other
pandas-dependent tests. Because the export assertions came first, the plot
half of the same test (which already skipped without matplotlib) was never
reached on such a host, and the runner's summary carried a permanent
"1 failed" that hid nothing today but would hide a real failure tomorrow.

## Change

- `tests/_util.py`: new `have_module(name)` import probe; `have_numpy()` now
  delegates to it. It is meant for `_util.require(...)`, never for a bare
  `return` (the runner only prints SKIP for `_util.Skip`).
- `tests/test_stale_cache.py`: the test is split in two.
  - `test_unchanged_source_export_still_works`: `require_numpy()`,
    `require(have_module('pandas'), 'pandas not installed (csv export)')`,
    then the unchanged `export csv` and cache assertions.
  - `test_unchanged_source_plot_still_works`: `require_numpy()`,
    `require(have_module('matplotlib'), 'matplotlib not installed (Agg plot
    save)')`, a fresh shell, `plot msd Fe`, the PNG assertion and the same
    cache assertions.
- BACKLOG row set to done; CHANGELOG entry under `[Unreleased]`.

## Decisions

- Skip, not a pandas-free export: `summary` is the only export that needs no
  pandas and it takes no result name, so it cannot stand in for the per-result
  CSV. Adding a pandas-free CSV writer would be product scope, not a test fix.
- Two tests instead of one skip: with one test, a missing pandas would also
  skip the plot check on a host that has matplotlib. Each half now depends on
  exactly the library it uses.
- `have_module` uses `__import__` so `_util.py` keeps its import list; the
  probe only reports `ImportError`, any other import failure still raises.
- The old test name stays in AUDIT-20261104, UI-2 and REV-IO-10 devlogs as a
  historical record of what failed then; nothing else references it.

## Verification

| Check | Result |
| --- | --- |
| `run_one.py test_stale_cache` (no pandas, no matplotlib on this host) | 6 PASS, `SKIP test_unchanged_source_export_still_works pandas not installed (csv export)`, `SKIP test_unchanged_source_plot_still_works matplotlib not installed (Agg plot save)` |
| `HOME=tmp /usr/bin/python3 tests/run.py` | 738 passed, 0 failed, 26 skipped (was 738/1/24 on main; native parser installed from `native/build.sh` output) |
| `LKPR_NO_NATIVE=1 HOME=tmp /usr/bin/python3 tests/run.py` | 725 passed, 0 failed, 39 skipped (was 725/1/37 on main: the failure became a skip, the plot half is the other new skip) |
| Old name left anywhere outside historical devlogs | `grep` finds it only in `docs/agent/{AUDIT-20261104,UI-2,REV-IO-10}.md` |

## Review round

Read-only review of the diff before merge; findings and their resolution are
listed below.

| # | Finding | Resolution |
| --- | --- | --- |
| 1 | Docstring said "every tabular export goes through pandas"; only `csv` and `latex` call `_require_pandas` | Reworded to "the csv and latex exports go through pandas" |
| 2 | Checked: `require` raises `_util.Skip` (runner prints SKIP), so neither new test can pass silently; `have_numpy`'s four callers in `test_engine.py` use it as a bool and get the same value; the original test's assertions are all kept (the plot test gains the cache checks) | No change |
