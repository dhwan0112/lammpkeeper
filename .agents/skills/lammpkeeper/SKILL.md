---
name: lammpkeeper
description: Use LammpKeeper (lkpr) to summarize existing LAMMPS thermo logs with reproducible JSON results, explicit Python environments, warnings and local job diagnostics. Use for lkpr capability discovery, log statistics and supervised analysis requests. Do not use this workflow to generate LAMMPS inputs, submit HPC jobs or invent unsupported trajectory analyses.
compatibility: Requires filesystem and process tools, Python >=3.9 with LammpKeeper and NumPy installed, or a configured source checkout. Supervised lkpr run requires POSIX process groups and non-reaping waitid. No MCP server is required.
---

# LammpKeeper: inspect, execute, verify, report

Use the shared Python execution backend, not terminal-table scraping or a second
implementation of the statistics. The current operation is `thermo.summary` v1.
Keep the user's original input unchanged. Preserve request, stdout JSON, stderr
events/diagnostics and exit status in a new task output directory so the result
can be checked later. Do not overwrite previous evidence.

## 1. Establish the environment and supported operation

Use the Python executable selected by the user, preserving its venv symlink.
When none is given, identify the configured project/environment interpreter;
if the choice is ambiguous, ask which environment to use. Do not silently switch
interpreters after failure or install missing dependencies as a fallback.
Run with an explicit working directory and quote paths containing spaces:

```bash
"/path/to/environment/bin/python" -m lammpkeeper exec --capabilities
```

Save discovery stdout/stderr and exit status. Require exit 0, `status: succeeded`,
protocol 1, and the requested operation/version in `result.operations`. Record
`provenance.python_executable` and package/Python/NumPy versions. Discovery is
not an analysis result. Read the advertised schema/bounds before constructing a
request. The backend currently exposes summary statistics only: no RDF/MSD,
plotting, pressure conversion, persistent jobs or generated output artifacts.
If the user requests an unsupported operation, explain the capability gap rather
than substituting another calculation or inventing a command.

## 2. Prepare one explicit request

Resolve the log path against the selected working directory. Prefer an absolute
input path to avoid ambiguity when the request file is stored elsewhere. Write
valid JSON using a serializer rather than interpolating shell text into JSON:

```json
{
  "protocol_version": 1,
  "request_id": "thermo-summary-001",
  "operation": "thermo.summary",
  "operation_version": 1,
  "input": {"log": "/absolute/path/to/log.lammps"},
  "parameters": {}
}
```

Versions are integer tokens, not `true` or `1.0`. No extra parameters are accepted.
`input.log` is relative to execution cwd if not absolute, not to the request file.
There are no species, force-field or unit overrides for this operation. An input
file or parser diagnostic does not authorize repairing/dropping rows to make a
failed analysis succeed.

## 3. Execute and retain machine-readable evidence

For supervised local work, prefer:

```bash
"/path/to/environment/bin/python" -m lammpkeeper run \
  --request "/task/output/request.json" \
  --python "/path/to/environment/bin/python" --timeout 60 --events \
  > "/task/output/job.json" 2> "/task/output/events.jsonl"
```

Capture the process exit status even on failure. Use a tool timeout longer than
the job timeout plus cleanup allowance; a host tool timeout is not evidence of
backend success or confirmed cleanup. Each command waits for its own job. For
non-POSIX environments or a deliberately synchronous request, use:

```bash
"/path/to/environment/bin/python" -m lammpkeeper exec \
  --request "/task/output/request.json" \
  > "/task/output/response.json" 2> "/task/output/diagnostics.txt"
```

Do not auto-fallback from a failed `run` to `exec`; first report the failure and
its cause. File input allows closed stdin. For `--request -`, send one bounded
JSON request and close stdin. This workflow invokes no interactive shell/history.

## 4. Validate before presenting numbers

For `run`, check exit 0, `job_schema_version: 1`, `state: succeeded`, and
`cleanup.status: complete`, `cleanup.reaped: true`, `cleanup.error: null`.
Then inspect `backend_response`, not discovery metadata or a stale previous job.
For `exec`, inspect the response directly and require exit 0 and success.
In either response check:

- protocol/operation versions and request identity match what was submitted;
- `error` is null, sample count is positive, and statistics are finite;
- `warnings`, per-column `units`, `unit_system` and provenance are retained;
- `artifacts` is `[]`. The saved JSON/events are execution evidence, not backend
  scientific artifacts. Never claim a CSV/plot/trajectory file was generated.

On failure, report the error code/message, warnings and source diagnostics;
do not present partial statistics as success. For supervised work also report
cleanup health independently of the primary state: `failed` or `incomplete`
cleanup does not prove child termination even if state says cancelled/timed_out.
Ctrl-C returns 130; an incomplete-cleanup observation can remain nonterminal.

## 5. Interpret the summary within its contract

`statistics` contains min/max/mean/population standard deviation (`ddof=0`)
for available `step,temp,pe,ke,etotal,press,vol`, in native numeric units.
Metal pressure is bar and energy eV; real pressure is atm and energy kcal/mol.
If units are missing, leave dependent labels unresolved/null and explicitly say
so. Do not borrow units from another file or infer metal units from filenames.

Report `sample_count` as parser-selected rows. The parser may omit minimization
or incompatible tables, coalesce identical boundaries, or use optimizer-only
fallback. Include its warnings; do not call every result an MD-only average.
These are descriptive sample statistics, not elapsed-time averages, uncertainty
estimates, proof of equilibration or proof that a simulation completed.

Step guards validate parsed float64 values, not original textual integer
precision; do not claim exact source-step recovery. Input identity is a before/
after stat fingerprint, not a content hash or immutable snapshot guarantee.
Keep `mtime_ns`, inode and device strings intact in copied evidence.

## 6. Report succinctly

State success/failure, operation, input and selected Python. For success provide
sample count and the requested statistics with returned units. Include material
warnings/limits, cleanup health (when supervised), and paths to request/result/
event evidence. Distinguish measured results from inference. Explain missing
capabilities instead of claiming the rest of the roadmap is implemented.

For same-process status/cancellation, retain the `LocalJob` handle and use
`snapshot()`, `cancel()`, `wait()`. A job UUID alone cannot be looked up by a later
CLI command; there is no durable status/cancel API or MCP adapter yet.

Read [host setup](references/hosts.md) for Claude Code, Codex and OpenCode V2
discovery paths and which integrations have actually been exercised.
