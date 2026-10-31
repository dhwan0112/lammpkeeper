# EXEC-1 — shared thermo summary and structured execution

Published implementation: `8087bb7`, [PR #29](https://github.com/dhwan0112/lammpkeeper/pull/29),
originally stacked on PR #28; merged into main on 2026-10-30 as `ed41c1f`.

## Status and design decision

Implemented and verified on `gen/exec-1-structured-analysis`, based on the ARCH-1 proposal
branch (`9c0c048`, PR #28). The maintainer asked to continue the five-stage
Rust/Python/agent track on 2026-10-30; ADR-0004 acceptance is recorded here and
in the ADR. This is the first vertical slice, not the entire track.

Choose `thermo.summary` version 1, extracted from existing `show thermo`:
minimum, maximum, mean and population standard deviation for supported columns
`step`, `temp`, `pe`, `ke`, `etotal`, `press`, `vol`, in that order. Existing
parser block selection remains authoritative, including optimizer-only fallback.
The longest compatible header layout is used, incompatible/minimization blocks
may be excluded when MD blocks exist, and identical boundary records may be
coalesced. The response must report selected sample count and parser warnings;
it does not summarize every raw record indiscriminately. These are sample statistics,
not time-weighted estimates or a claim of equilibrium/material correctness.

RDF has an open float32 backend-parity finding; charge fixes are in separate
unmerged PRs #26/#27. Thermo summary avoids those dependencies and does not
infer species, units from trajectories, PBC, elapsed time or force fields.

## Application and interface boundary

- `lammpkeeper/application.py`: direct Python summary of a loaded log snapshot,
  plus a fresh-file operation using the existing `parse_log` reader.
- `lammpkeeper/execution.py`: strict JSON request validation, capability discovery
  and response envelope; no interactive shell construction or terminal scraping.
- `lammpkeeper/cli.py`: additive `exec` dispatch; prep/post argument forwarding,
  existing entry points, help/version and nonterminal behavior retained.
- `lammps_post/shell.py`: existing `show thermo` uses the same summary operation;
  valid tabular presentation and population-standard-deviation convention retained.

No new package hierarchy or module move is needed. NumPy remains the only core
scientific dependency. Python callers continue to use dictionaries/arrays in
process; they need no Rust binary or JSON round trip.

## Version 1 control contract

```json
{
  "protocol_version": 1,
  "request_id": "thermo-example",
  "operation": "thermo.summary",
  "operation_version": 1,
  "input": {"log": "/path/to/log.lammps"},
  "parameters": {}
}
```

Invocation for this slice:

```bash
/path/to/environment/bin/python -m lammpkeeper exec --capabilities
/path/to/environment/bin/python -m lammpkeeper exec --request request.json
/path/to/environment/bin/python -m lammpkeeper exec --request - < request.json
```

The interpreter is selected by the caller at process launch. Discovery reports
that actual interpreter and backend versions. Automatic environment selection
and process supervision are EXEC-2/Rust-client work; no fallback interpreter or
dependency installation is introduced here.

Requests are bounded to 1 MiB. Reject duplicate JSON keys, nonfinite JSON values,
unknown fields/parameters, wrong types and unsupported protocol/operation
versions. One invocation consumes one request and returns one strict JSON
response on stdout. Help text is separate from request execution. No prompts,
ANSI decoration or history writes belong in the machine path.

`request_id` is a nonblank string of at most 128 characters; the log path is a
nonblank string of at most 4096 characters and cannot contain NUL. Relative log
paths resolve against the caller's working directory, not the request file's
directory. Version fields require integer JSON tokens: `true` and `1.0` reject.
These lexical constraints are additional to the discovery JSON Schema.

Responses distinguish `succeeded` and `failed`, contain the request/operation
identity, result or structured error, warnings, provenance and `artifacts: []`.
Stable error categories distinguish invalid requests, unsupported versions,
invalid scientific input, input changes, I/O errors and internal failures.
Only small column statistics are inline; no trajectory arrays, individual atom
IDs, individual step arrays, output-file writing, asynchronous job/status/cancel
or daemon is advertised by v1. The skill and MCP adapter will use supported
capabilities rather than assuming those future operations exist.

Successful `result` has `sample_count`, ordered `statistics` keyed by the
supported column names (each with `min`, `max`, `mean`, `std`), `unit_system`
and per-column `units`. Standard deviation uses `ddof=0` and the same native
units as the corresponding column. A failure has `result: null` and
`error: {code, message}`; success has `error: null`. Exit codes are 0 for success
and 1 for failed requests. Diagnostics are capped at 1024 characters and warnings
at 64, with explicit notice when additional warnings are omitted.

Provenance contains Python/backend/NumPy versions, actual interpreter, parser
selection and parsed-step policies, unit source and input stat fingerprint.
Fingerprint fields include resolved path, byte size, and decimal-string
`mtime_ns`, inode and device values; the timestamp string preserves nanoseconds
in clients whose JSON numbers use double precision.

Direct Python use (no subprocess or wire encoding):

```python
from lammps_post.parsers import parse_log
from lammpkeeper.application import summarize_thermo, summarize_thermo_file

snapshot = parse_log("log.lammps")
summary = summarize_thermo(snapshot)
fresh_summary, warnings, fingerprint = summarize_thermo_file("log.lammps")
```

## Scientific and source-integrity limits

The summary preserves native numeric values. Known units come only from the
log parser's explicit `unit_system`; missing units remain unresolved with a
diagnostic. Pressure is not converted or normalized by a guessed slab thickness.
Unsupported/mixed unit styles retain existing parser rejection.

The shared summary checks supported arrays for matching lengths, nonempty
one-dimensional finite values, and finite calculated statistics. Duplicate or
alias-colliding supported headers must reject instead of silently selecting a
column. Inspect all retained raw-block Step values, including omitted blocks:
require finite integral parsed values with absolute value below 2**53.
This validates the parser's float64 representation, not original source tokens:
a textual fractional value may already have rounded to an integer. There is no
second application-level text parser to imply otherwise. REV-IO-5 remains open;
no exact source-step, elapsed-time or arbitrary trajectory-ID guarantee is made.

A direct Python/legacy-shell call summarizes its loaded snapshot; it does not
claim the source file is unchanged on disk. Fresh structured calls parse fresh
input and compare source identity before/after reading. Provenance labels a stat
fingerprint as such, not as a cryptographic content hash. This detects ordinary
replacement/change, not every adversarial or metadata-preserving mutation.

## Verification plan

Parent captured the original `show thermo` output on archived `84ee8d1` using
the unchanged Fe-O log before integration. Evidence:
`/tmp/opencode/lkpr-exec1-baseline.pu058zjy/show-thermo.txt`.
The original parser reports three excluded minimization/incompatible blocks;
the captured table is a formatting/parity reference, not a new scientific oracle.

- Independent synthetic column arithmetic, including non-Fe/generic logs.
- Existing Fe-O log equality across direct API, structured response and legacy
  table; no fixture or golden changes.
- Explicit metal/real and unresolved units; parser malformed-row failures;
  empty/nonfinite/overflow and unsafe-step rejection.
- Protocol errors, versions, duplicate keys, unknown fields, oversized input;
  execution with closed stdin, paths with spaces and isolated HOME.
- Loaded-snapshot semantics, fresh reads and source-change detection.
- Full project verifier after integration, with optional skips reported.

## Focused and integration checks (measured, 2026-10-30)

- Worker fail-before check: the shared application import did not exist.
  Final focused contract suite: **17 passed, 0 failed**. Tests are registered
  with both the dependency-free runner and pytest discovery.
- Independent source reviewer approved the bounded scientific/protocol behavior;
  exact timestamp serialization and schema lexical caveats were corrected before
  final verification. All new Python functions have English intent docstrings.
- Parent independently compared current legacy `show thermo` against archived
  main `84ee8d1`: **byte-identical** table. Both use the unchanged Fe-O log.
- Parent built a pure-Python wheel in an isolated snapshot and installed it into
  an isolated target. Outside the checkout, direct Python API, `python -m
  lammpkeeper exec` and the installed `lkpr` entry point passed. The explicit
  interpreter path and input paths contained spaces; stdin was closed. An
  independent real-unit log gave temperature mean 4 K and pressure mean 20 atm;
  no history files appeared. These were Python 3.11 tests, not a 3.9 runtime claim.
- Changed executable/test files are byte-identical to the final native snapshot;
  all parse using Python 3.9 grammar. No fixture/golden, native source or packaging
  dependency changed. MDAnalysis remains unavailable.

Parent evidence root: `/tmp/opencode/lkpr-exec1-final._poqs9rc`, including
`installed-check.json`, `check_installed.py`, wheel and captured legacy table.
Native checks reuse an isolated compiled artifact only after byte-checking its
Rust source, Cargo manifest and lockfile against this branch. No binary is
installed in or committed to the working repository.

## Full verification (measured, 2026-10-30)

- Native full verifier: **461 passed, 0 failed, 0 skipped**; post analysis/plots
  and prep artifacts/script syntax passed.
  Evidence: `/tmp/opencode/lkpr-exec1-full-native/20261030T172430-nogit-full`.
- Forced NumPy full verifier: **455 passed, 0 failed, 6 skipped**; the same
  post/prep checks passed. Skips: native dump reader, boundary metadata, slab
  parity, two species-metadata checks and triclinic IO.
  Evidence: `/tmp/opencode/lkpr-exec1-full-fallback/20261030T172410-9c0c048-full`.
- Native pytest with slow tests: **461 passed**, 79 warnings, 102.28 seconds.
- `git diff --check` passes. These counts exclude the separately unmerged
  PR #26/#27 regressions; no claim of combined-branch verification is made.

Verification used mlff Python 3.11.15 and isolated HOME/TMPDIR. Actual LAMMPS/HPC,
Python 3.9 runtime, Rust clients, MCP clients and agent-host integrations remain
unverified. Parent/worker reviewed application impact and scientific assumptions
directly; unavailable `/blast-radius` and `/interrogate` playbooks are not claimed
as executed.

## Native-only skip audit before EXEC-2 (2026-10-30, measured)

The maintainer asked to check all skipped tests before continuing. Parent matched
the six NumPy-mode skips to explicit PASS lines in the native full-run
`tests.log` (lines 46, 63, 331, 360, 361, 447), then reran precisely these six
functions in the verified native snapshot with isolated HOME:

| Module | Test | Native recheck |
| --- | --- | --- |
| `test_dump_reader` | `test_native_parser_matches_loadtxt` | PASS |
| `test_periodicity` | `test_native_boundary_metadata_matches_numpy_without_fallback` | PASS |
| `test_slab_reference` | `test_slab_native_and_numpy_match_every_reader_access_path` | PASS |
| `test_species_metadata` | `test_dump_native_metadata_parity_without_numpy_fallback` | PASS |
| `test_species_metadata` | `test_dump_native_raw_type_ids_without_fallback` | PASS |
| `test_triclinic_io` | `test_box_aware_real_native_success_matches_numpy_without_fallback` | PASS |

Recheck: **6 passed, 0 failed, 0 skipped**. The native module was asserted loaded
from `/tmp/opencode/lkpr-exec1-final._poqs9rc/source/lammps_post/_dumpparse.abi3.so`.
These tests were intentionally unavailable under forced NumPy, not unverified
failures. This does not add MDAnalysis, Python 3.9 runtime or real-HPC coverage.

## Next bounded work

EXEC-2 defines interpreter selection/handshake, supervised local work and lifecycle
events before AGENT-1/UI-1. Skill, Rust CLI/TUI and MCP retain their separate
backlog gates. Existing scientific-integrity and real-HPC deferral remain in effect.
