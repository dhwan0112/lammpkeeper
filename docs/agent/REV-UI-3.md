# REV-UI-3: explicit output requests fail instead of exiting 0

Status: fixed; verification below.
Branch: `fix/rev-ui-3-export-failures` from main `c61419a`.
Sources: the prior-work review (PRIOR-WORK-REVIEW-20261029: `export csv missing` and a pressure plot from a Step/Temp log exit 0 with no artifact) and the 2026-11-01 audit additions.

## Problem (measured on unmodified code)

Several output requests printed a message and returned, so `--batch` and one-shot runs exited 0 without the requested file.

| Request | Old behavior |
| --- | --- |
| `export csv <missing>`, `export latex <missing>` | Printed "No cached data", exit 0 |
| Export with pandas missing | Printed only |
| Export of a result with no 1-D arrays | CSV printed a warning; LaTeX did nothing |
| Unknown format or bad usage | Printed only |
| `export summary` with no name | Usage message, although the help says `export summary [filename]` |
| `export summary notes.md` | Silently wrote `summary.txt` instead |
| `plot pressure` on a log without Press or Pxx/Pyy/Pzz | Printed hints, wrote nothing, exit 0 |

Two side effects:
- `makedirs` ran before the checks, so a failed export could leave an empty output directory.
- The CSV and LaTeX files were opened before their header lines were built, so a failure left a truncated file.

## Change (`lammps_post/shell.py`)

**Exports:**
- `do_export` raises `ValueError` for bad usage and unknown formats.
- `_export_csv` and `_export_latex` raise when pandas is missing (`RuntimeError`), when there is no cached data (`ValueError`) and when there are no 1-D array columns (`ValueError`). `onecmd` records each as a failure, so batch and one-shot runs exit 1.
- The full CSV or LaTeX text, header included, is built before the output directory or file is created.

**Summary:**
- `export summary [filename]` now matches the help text. With no name it writes `output_dir/summary.txt`; with a name it uses that name as given.
- This changes behavior: `export summary notes.md` now writes `notes.md`. Before, it wrote `summary.txt`.
- The default directory is created only after the summary text is built.

**Pressure plots:**
- A direct `plot pressure` (or redo) on a log with no pressure columns raises `ValueError` with a hint.
- `plot all` passes `_optional=True` and prints "Skipping pressure plot: …". That is a deliberate, visible skip.
- A log with Press but no stress components still gives the basic plot.

## Tests

**New module:** `tests/test_output_failures.py` (6 tests), registered in `tests/run.py`. All 6 fail on unmodified code. They cover:
- failed export requests, with nothing created, not even the output directory;
- missing pandas;
- no partial file after a header failure;
- valid exports and summary names;
- `plot pressure` failing while `plot all` skips;
- the real `--batch` CLI exiting 1 on `export csv missing`.

**Related modules:** 8 modules (`test_audit_integration`, `test_audit_workflow`, `test_rdf_cutoff`, `test_slab_reference`, `test_stale_cache`, `test_triclinic_session`, `test_lkpr_cli`, `test_skip_reporting`) pass with `LKPR_SLOW=1`. No existing expectation changed.

## Not changed

- The thermo and thermostat plots in `plot all` keep their current handling.
- Interactive prompts are unchanged.
