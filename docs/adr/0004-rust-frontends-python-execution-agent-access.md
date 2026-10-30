# ADR-0004: Rust frontends, Python execution, and shared agent access

- **Status:** accepted (2026-10-30)
- **Date:** 2026-10-30
- **Deciders:** 김동환 (maintainer)
- **Backlog:** ARCH-1, EXEC-1, EXEC-2, AGENT-1, UI-1, UI-2, AGENT-2
- **Relation:** extends ADR-0001 at the application boundary; does not supersede
  ADR-0001/0002/0003 or approve physical package moves

## Context

The maintainer requests a Rust CLI/TUI and interactive experience while keeping
Python compatibility essential for data handling, scientific packages and
existing environments. Claude, Codex and OpenCode should be able to invoke the
same workflows through skills or MCP without interpreting terminal screens.

Source-observed baseline: `lammpkeeper/cli.py` dispatches to existing Python
prep/post CLIs; `pyproject.toml` owns the `lkpr` console entry point and supports
Python >=3.9 with NumPy as the core dependency. `lammps_post/shell.py` currently
combines interaction, session management and analysis dispatch. The optional
`native/` Rust extension accelerates parsing; it is not a Rust frontend.

Inferred design risk: independently implementing workflows in a TUI and MCP
server would duplicate metadata resolution, validation and result lifetimes.
Different interfaces must not produce different scientific answers.

## Options

| Option | Cost and risk | Reproducibility, generality and compatibility |
| --- | --- | --- |
| Keep Python shells only; agents drive terminal text | Lowest initial cost; output parsing and interactive state remain fragile | Existing APIs survive, but automated use is weak and errors can be misread |
| Rewrite analysis and UI in Rust | Largest migration and scientific revalidation burden | Duplicates/replaces Python ecosystem behavior and threatens existing workflows |
| Embed Python in the Rust frontend immediately | Direct calls, but interpreter/ABI/environment packaging becomes tightly coupled | Can preserve kernels; conda/venv and optional native dependencies become harder to support |
| Rust frontends and agent adapters share Python execution (recommended) | Adds a versioned process boundary and lifecycle work | Reuses numerical kernels, retains Python-only use and permits incremental generic workflows |

## Decision

The maintainer requested continuation of the five-stage track on 2026-10-30,
after reviewing the ADR/roadmap proposal. This accepts the direction and starts
the first bounded vertical slice; later implementation stages retain their
individual compatibility, validation and scope gates.

### Responsibility boundaries

```text
Python API / existing CLI    Rust CLI / TUI    Skill / MCP adapter
            \                    |                  /
             shared Python application execution contract
                                  |
                existing scientific layers and domain operations
                                  |
             NumPy + optional packages / optional Rust acceleration
```

Python owns scientific computation, species/units/PBC resolution, validation,
workflow execution and result provenance. Rust owns terminal interaction,
presentation and child-process supervision. Adapters cannot infer new physical
defaults, silently repair invalid data or implement competing analysis kernels.
ADR-0001's scientific layers remain the target. Exact new module and Rust crate
paths must be specified and approved in the implementing design before moves.

The Python API remains first-class for notebooks, scripts and NumPy arrays;
in-process users are not forced through JSON or a Rust executable. Existing
imports, CLI flags, output names and batch failure semantics remain supported.
No Rust toolchain, MCP dependency or agent application becomes a Python-core
installation requirement. Scientific packages retain their current optional
dependency policy; this proposal does not replace the accepted geometry policy.

### Initial process and data boundary

Use an explicitly selected Python executable in the user's conda/venv or other
supported environment. Initial frontend calls use subprocesses, not embedded
Python. Interpreter selection must be deterministic and reported: explicit
configuration takes precedence over a documented environment/default lookup.
Never silently retry a different interpreter after import or execution failure.
Check executable, backend version, protocol version and optional capabilities
before starting a scientific task; do not install packages automatically.

Define a versioned JSON control contract before shipping either frontend or MCP.
Wire details and public command names are finalized in EXEC-1, not implied by
the illustrative diagram. The contract must include:

- Request ID, operation, input references, explicit parameters, output location
  and resolved metadata/provenance; distinguish user overrides from inference.
- Discovery of supported operations, parameter schemas, versions and optional
  capabilities. Reject unsupported protocol versions and invalid requests visibly.
- Results with explicit success/failure/cancelled state, stable error codes,
  readable diagnostics and warnings, summaries and artifact descriptors.
- Backend/package versions, input identity and resolved units/species/PBC needed
  to reproduce the operation. Input hashing cost/policy must be explicit; never
  label size/mtime as a content hash. Reuse existing provenance where applicable.
- Strict JSON: no NaN/Inf tokens. Missing/undefined scientific values need an
  explicit representation and diagnostic, never silent conversion to zero.
  Sparse type IDs and signed-64-bit atom/step identifiers must round-trip exactly;
  specify lossless wire encoding instead of relying on client floating-point JSON
  numbers. Array artifacts must be loadable without pickle.
- Machine output separated from human logs/ANSI prompts. Requests must work with
  closed stdin after submission and with no terminal attached. Specify framing
  and message size bounds; preserve caller working-directory/path semantics.

Keep trajectories and large arrays outside control messages. Return artifact
references with format, shape/dtype/units where relevant and ownership/lifetime.
Start with existing outputs and NumPy-compatible arrays; any new storage format
needs its own dependency and compatibility rationale. Existing outputs are not
renamed by this proposal. Avoid mandatory shared memory, Arrow or remote storage.

### Execution and lifecycle

Start with one bounded operation per invocation, using fresh explicit context.
Extract callable application operations from shell dispatch incrementally; do not
automate `onecmd` or scrape terminal text as the lasting service interface.
Reuse current validation and kernels rather than bypassing them. Application
operations must retain transactional source loading, metadata conflict rejection,
rollback and cache invalidation from ADR-0002/0003. A serialized request is not
a replacement run manifest or a new authority for inferred physical metadata.
Shell navigation/quit signals are distinct from operation success; retain the
existing post batch and prep fail-fast policies in their compatibility paths.
Artifact-producing operations verify their requested outputs before success.

The new backend must disable readline/history and interactive prompts. The TUI
initially owns configuration and sends a complete explicit request for each run;
it must not assume that separate workers share the existing shell's live caches.
Legacy interactive shells retain their sessions. Persistent backend sessions,
if later justified, need explicit ownership and restoration semantics.

Before interactive background work or asynchronous MCP tools, specify job IDs,
progress events, cancellation, timeout, child death and artifact finalization.
Failed/cancelled/interrupted work cannot publish stale results as current success.
Partial artifacts must be identified as incomplete; cancellation is not rollback
of arbitrary external side effects. Initial jobs are local, process-owned; no
implicit daemon, restart recovery or remote scheduler is promised. Durable jobs
and HPC submission require separately scoped contracts and existing human gates.

### Agent access

AGENT-1 supplies a portable workflow skill around the structured CLI: discover
capabilities, inspect inputs, choose explicit settings, run, inspect diagnostics
and verify artifacts. Host-specific discovery/install instructions are thin
wrappers; shared scientific instructions have one maintained source. Support
for each host is claimed only after that host's integration is exercised.

AGENT-2 adds a thin optional MCP adapter over the same application operations.
It exposes bounded inspect/run/status/result/cancel capabilities as supported by
the backend; exact tool names and schemas are finalized in that item. A skill
teaches workflow; MCP provides callable tools. Neither depends on a TUI session.
Initial transport is local stdio. Do not reuse MCP's stdio stream for backend
logs or invent a second analysis engine in the adapter.

### Distribution and compatibility

Keep the existing Python-owned `lkpr` command during the additive rollout. Ship
the Rust prototype under a distinct, explicitly chosen name; no PATH collision
or automatic replacement of the installed Python command. A later switch of
default executable requires a separate distribution/deprecation decision.

Python-only usage and the supported Python floor remain intact. Rust binaries,
Python backend and optional agent adapters may version independently, with an
explicit compatibility matrix and actionable mismatch errors. Packaging targets,
TUI libraries and any later embedding optimization remain implementation choices
requiring recorded evidence, not prerequisites for the scientific toolkit.

## Consequences and migration

Benefits: reuse of the scientific ecosystem, interface-independent validation,
direct Python access, and automation without terminal scraping. Costs: protocol
maintenance, process startup, environment diagnostics and cancellation semantics.
No performance improvement is claimed without measurement; large-data transfer
and repeated process startup must be profiled before adding persistent workers.

Order: approval → EXEC-1 → EXEC-2 → AGENT-1 / UI-1 → UI-2 / AGENT-2.
The roadmap and completion criteria are in `MIGRATION.md` and the backlog.
Existing scientific integrity work remains first priority. This track does not
require waiting for all GEN package moves or authorize them implicitly.

## Acceptance evidence and open decisions

### EXEC-1 implementation selection (2026-10-30)

The first bounded operation is `thermo.summary` version 1: the existing
`show thermo` column statistics, with no timeline, trajectory arrays, plotting
or species inference. Add `lammpkeeper/application.py` for the shared Python
operation and `lammpkeeper/execution.py` for the versioned JSON boundary.
Existing files are not moved. `lammpkeeper/cli.py` adds `exec`; the existing
post shell uses the shared application function for its numeric statistics.
This realizes the maintainer-approved track through an additive application
boundary rather than a package reorganization. The concrete bounded contract
and validation evidence are recorded in `docs/agent/EXEC-1.md`.

### Whole-track acceptance checks

- One reference operation agrees across direct Python, legacy CLI and structured
  execution on values, units, selection, diagnostics and failure status.
- Add synthetic non-Fe and existing Fe-O checks; unchanged fixtures/goldens.
- Exercise supported Python versions, an explicit environment path with spaces,
  missing optional dependencies, incompatible backend and protocol versions.
- Exercise installed-wheel use outside the checkout, Rust absent, failed artifact
  writes, source replacement/cache invalidation and PTY/non-TTY terminal recovery.
- Exercise invalid requests, malformed output, exact ID and nonfinite serialization, timeout,
  cancellation and subprocess failure without stale-success publication.
- Rust/MCP adapters pass the same contract cases; each host integration records
  what was actually tested. Headless operation and Python-only installation work.
- Before EXEC-1 implementation, settle operation/schema versioning, first
  reference operation and exact application module paths. Before UI-1, settle
  prototype executable/distribution names. Before EXEC-2, settle lifecycle
  schemas and cancellation granularity. Before UI-2/AGENT-2, confirm mappings
  to that shared lifecycle. No service/SLA or HPC support is implied.

Acceptance of this ADR authorizes its direction, not completion claims or the
removal of legacy interfaces. Each implementation item still requires its own
bounded branch, review and regression evidence.
