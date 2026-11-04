//! `lkpr-rs`: additive Rust CLI for LammpKeeper (UI-1, ADR-0004).
//!
//! Science, validation and job lifecycle stay in Python: this binary runs
//! `<python> -m lammpkeeper exec --capabilities` (doctor) and
//! `<python> -m lammpkeeper run --request -` (thermo-summary), then prints a
//! readable summary or, with `--json`, the backend's JSON byte-for-byte.
//! It never guesses a Python environment and never replaces the `lkpr` command.

mod backend;

use serde_json::{json, Value};
use std::ffi::OsString;
use std::fmt::Display;
use std::io::Write;
use std::process::ExitCode;
use std::time::{Duration, Instant};

const USAGE: &str = "\
usage: lkpr-rs doctor --python PATH [--json]
       lkpr-rs thermo-summary --log FILE --python PATH [--timeout SECONDS] [--json]
       lkpr-rs --help | --version

The Python environment is required: --python PATH, or the LKPR_PYTHON
environment variable. It must have the lammpkeeper package installed.
Options, paths and LKPR_PYTHON must be valid UTF-8: they are echoed in
messages and sent to the backend as text.

doctor          check the Python backend, its versions and supported operations
thermo-summary  thermo column statistics of a LAMMPS log (operation thermo.summary v1)

--json          print the backend JSON unchanged (machine output on stdout)
--timeout       overall job timeout passed to the backend (default 60)

Exit status: 0 succeeded, 1 failed/timed out/backend problem, 2 usage error,
130 interrupted (Ctrl-C was forwarded to the backend as a cancellation).";

/// Protocol and operation versions this client understands.
const PROTOCOL_VERSION: u64 = 1;
const OPERATION: &str = "thermo.summary";
const OPERATION_VERSION: u64 = 1;
/// The supervisor waits this much longer than the backend's own timeout, so
/// the backend normally reports `timed_out` itself before being forced.
const DEADLINE_SLACK: Duration = Duration::from_secs(15);
/// Bound for the doctor capability probe.
const DOCTOR_TIMEOUT: Duration = Duration::from_secs(60);

/// Parsed command line. Only the options of the chosen command are accepted.
#[derive(Debug, Default)]
struct Options {
    command: String,
    python: Option<String>,
    log: Option<String>,
    timeout: Option<f64>,
    json: bool,
}

/// A failure with its exit status; usage errors exit 2, the rest 1.
struct Failure {
    code: u8,
    message: String,
}

/// Usage error (exit 2) that also prints the usage text.
fn usage_error(message: impl Into<String>) -> Failure {
    Failure {
        code: 2,
        message: format!("{}\n\n{USAGE}", message.into()),
    }
}

/// Runtime failure (exit 1): backend, environment or result problem.
fn failure(message: impl Into<String>) -> Failure {
    Failure {
        code: 1,
        message: message.into(),
    }
}

/// Parse arguments strictly: unknown options and repeated options are errors.
fn parse_args(args: &[String]) -> Result<Options, Failure> {
    let mut iter = args.iter();
    let command = match iter.next().map(String::as_str) {
        Some(c @ ("doctor" | "thermo-summary")) => c.to_string(),
        Some(other) => return Err(usage_error(format!("unknown command {other:?}"))),
        None => return Err(usage_error("missing command")),
    };
    let mut options = Options {
        command,
        ..Default::default()
    };
    while let Some(arg) = iter.next() {
        let mut value = |name: &str| {
            iter.next()
                .cloned()
                .ok_or_else(|| usage_error(format!("{name} needs a value")))
        };
        match arg.as_str() {
            "--python" if options.python.is_none() => options.python = Some(value("--python")?),
            "--json" if !options.json => options.json = true,
            "--log" if options.command == "thermo-summary" && options.log.is_none() => {
                options.log = Some(value("--log")?)
            }
            "--timeout" if options.command == "thermo-summary" && options.timeout.is_none() => {
                let text = value("--timeout")?;
                let seconds: f64 = text.parse().map_err(|_| {
                    usage_error(format!("--timeout must be a number, got {text:?}"))
                })?;
                // Mirror the backend rule: finite and strictly positive.
                if !seconds.is_finite() || seconds <= 0.0 {
                    return Err(usage_error(format!(
                        "--timeout must be finite and positive, got {text:?}"
                    )));
                }
                // The supervisor deadline must be representable (no overflow panic).
                if deadline_after(seconds).is_none() {
                    return Err(usage_error(format!("--timeout is too large, got {text:?}")));
                }
                options.timeout = Some(seconds);
            }
            other => {
                return Err(usage_error(format!(
                    "unexpected or repeated argument {other:?}"
                )))
            }
        }
    }
    Ok(options)
}

/// Supervisor deadline for a backend timeout, or None if it cannot be represented.
fn deadline_after(seconds: f64) -> Option<Instant> {
    let backend = Duration::try_from_secs_f64(seconds).ok()?;
    Instant::now().checked_add(backend.checked_add(DEADLINE_SLACK)?)
}

/// How to select the Python environment, for the usage errors below.
const SELECT_PYTHON_HINT: &str = "pass --python PATH or set LKPR_PYTHON";

/// Explicit environment only: --python, then LKPR_PYTHON. No PATH guessing.
/// An empty path from either source is a usage error, as is a non-UTF-8 one.
fn select_python(options: &Options) -> Result<String, Failure> {
    let path = match &options.python {
        Some(python) => python.clone(),
        // `var_os`, not `var`: a non-UTF-8 value is named as such instead of
        // being reported as "no environment selected" (REV-RS-1).
        None => utf8(
            std::env::var_os("LKPR_PYTHON").ok_or_else(|| {
                usage_error(format!(
                    "no Python environment selected: {SELECT_PYTHON_HINT}"
                ))
            })?,
            "LKPR_PYTHON",
        )?,
    };
    if path.is_empty() {
        return Err(usage_error(format!(
            "the Python environment path is empty: {SELECT_PYTHON_HINT}"
        )));
    }
    Ok(path)
}

/// `value` as a `String`, or a usage error naming `what` (for example
/// "argument 3" or "LKPR_PYTHON"). `lkpr-rs` requires UTF-8 because every
/// path is echoed in messages and sent to the backend as JSON text; the
/// message says so and names a remedy that fits any argument, a command
/// name as well as a path (REV-RS-1).
fn utf8(value: OsString, what: impl Display) -> Result<String, Failure> {
    value.into_string().map_err(|raw| {
        usage_error(format!(
            "{what} is not valid UTF-8: {:?}; lkpr-rs accepts only UTF-8 options, paths and \
             LKPR_PYTHON (for a file, use a UTF-8 name or a symlink with one)",
            raw.to_string_lossy()
        ))
    })
}

/// Command-line arguments after the program name, as UTF-8.
///
/// `std::env::args()` panics (exit 101) on a non-UTF-8 argument; Linux paths
/// are arbitrary bytes, so a `--log` or `--python` value can be one. Such an
/// argument is a usage error (exit 2) naming its position (REV-RS-1).
fn utf8_args() -> Result<Vec<String>, Failure> {
    std::env::args_os()
        .skip(1)
        .enumerate()
        .map(|(index, arg)| utf8(arg, format!("argument {}", index + 1)))
        .collect()
}

/// Run one backend command and require a JSON object on stdout.
///
/// Returns the parsed value with the raw bytes (for verbatim `--json` output)
/// and the supervisor outcome. Launch failures, forced termination and invalid
/// output become explicit failures instead of partial results.
fn run_backend(
    python: &str,
    args: Vec<String>,
    stdin: Option<&[u8]>,
    deadline: Instant,
) -> Result<(Value, backend::Outcome), Failure> {
    let child = backend::spawn(python, &args, stdin)
        .map_err(|err| failure(format!("python_not_found: cannot start {python:?}: {err}")))?;
    let outcome = backend::supervise(child, deadline);
    match outcome.forced {
        Some(backend::Forced::Unresponsive) => {
            return Err(failure(format!(
                "supervisor_unresponsive: the backend did not publish a result in time and \
                 was terminated by lkpr-rs{}; its child processes were not confirmed cleaned up",
                if outcome.interrupted {
                    " after Ctrl-C"
                } else {
                    ""
                }
            )))
        }
        Some(backend::Forced::OutputTooLarge) => {
            return Err(failure(format!(
                "output_too_large: the backend wrote more than {} bytes and was terminated",
                backend::MAX_STDOUT
            )))
        }
        None => {}
    }
    if outcome.stdout_held_open {
        return Err(failure(
            "backend_stdout_held_open: the backend exited but another process kept its \
             output open; no result was read",
        ));
    }
    match serde_json::from_slice::<Value>(&outcome.stdout) {
        Ok(value) if value.is_object() => Ok((value, outcome)),
        _ => {
            let status = outcome
                .status
                .map(|s| s.to_string())
                .unwrap_or_else(|| "unknown".to_string());
            Err(failure(format!(
                "invalid_backend_output: {python:?} -m lammpkeeper did not print one JSON object \
                 ({status}); check that lammpkeeper is installed in this environment \
                 (stderr above may say more)"
            )))
        }
    }
}

/// Text of a JSON value for display. Numbers keep their original digits
/// (arbitrary_precision), so nothing is re-rounded.
fn text(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        Value::Null => "-".to_string(),
        other => other.to_string(),
    }
}

/// Supported versions in a capabilities document, as (protocol ok, op ok).
fn supports(capabilities: &Value) -> (bool, bool) {
    let result = &capabilities["result"];
    let has = |list: &Value, v: u64| {
        list.as_array()
            .map(|items| items.iter().any(|x| x.as_u64() == Some(v)))
            .unwrap_or(false)
    };
    (
        has(&result["protocol_versions"], PROTOCOL_VERSION),
        has(
            &result["operations"][OPERATION]["versions"],
            OPERATION_VERSION,
        ),
    )
}

/// `doctor`: probe the backend's capabilities and report version support.
///
/// With `--json` the capabilities document is printed unchanged and an
/// incompatible backend still fails (exit 1) after printing it. A Ctrl-C during
/// the probe ends with 130 even if the backend answered.
fn doctor(options: &Options, python: &str) -> Result<u8, Failure> {
    let args = ["-m", "lammpkeeper", "exec", "--capabilities"]
        .map(String::from)
        .to_vec();
    let (caps, outcome) = run_backend(python, args, None, Instant::now() + DOCTOR_TIMEOUT)?;
    let succeeded = caps["status"] == "succeeded";
    let (protocol_ok, operation_ok) = supports(&caps);
    let ok = succeeded && protocol_ok && operation_ok;
    if options.json {
        print_raw(&outcome.stdout)?;
    } else {
        let p = &caps["provenance"];
        println!("python      {}", text(&p["python_executable"]));
        println!(
            "            Python {}, NumPy {}",
            text(&p["python_version"]),
            text(&p["numpy_version"])
        );
        println!("backend     lammpkeeper {}", text(&p["package_version"]));
        println!(
            "protocol    v{PROTOCOL_VERSION}: {}",
            if protocol_ok {
                "supported"
            } else {
                "NOT supported"
            }
        );
        println!(
            "operation   {OPERATION} v{OPERATION_VERSION}: {}",
            if operation_ok {
                "supported"
            } else {
                "NOT supported"
            }
        );
        if !succeeded {
            println!("error       {}", error_text(&caps["error"]));
        }
        println!(
            "status      {}",
            if ok { "ok" } else { "incompatible backend" }
        );
    }
    if !ok {
        return Err(failure(format!(
            "incompatible_backend: {python:?} does not offer protocol v{PROTOCOL_VERSION} \
             with {OPERATION} v{OPERATION_VERSION}"
        )));
    }
    Ok(if outcome.interrupted { 130 } else { 0 })
}

/// `code: message` of a backend error object, or `-` when there is none.
fn error_text(error: &Value) -> String {
    if error.is_null() {
        return "-".to_string();
    }
    format!("{}: {}", text(&error["code"]), text(&error["message"]))
}

/// Write backend stdout unchanged (plus a newline if it lacked one).
///
/// A write failure (for example a closed pipe) is a failure: machine output
/// that was not delivered must not exit 0.
fn print_raw(bytes: &[u8]) -> Result<(), Failure> {
    let mut out = std::io::stdout().lock();
    let mut write = || -> std::io::Result<()> {
        out.write_all(bytes)?;
        if !bytes.ends_with(b"\n") {
            out.write_all(b"\n")?;
        }
        out.flush()
    };
    write().map_err(|err| failure(format!("output_write_failed: {err}")))
}

/// Readable report of a job snapshot. Values, units and warnings come from the
/// backend unchanged; this only arranges them.
fn print_summary(snapshot: &Value) {
    let state = text(&snapshot["state"]);
    let response = &snapshot["backend_response"];
    let result = &response["result"];
    if state == "succeeded" && result.is_object() {
        println!(
            "{OPERATION}  {state}  ({} samples, unit system: {})",
            text(&result["sample_count"]),
            text(&result["unit_system"])
        );
        let mut rows = vec![["column", "unit", "min", "max", "mean", "std"]
            .map(String::from)
            .to_vec()];
        if let Some(stats) = result["statistics"].as_object() {
            for (column, s) in stats {
                rows.push(vec![
                    column.clone(),
                    text(&result["units"][column]),
                    text(&s["min"]),
                    text(&s["max"]),
                    text(&s["mean"]),
                    text(&s["std"]),
                ]);
            }
        }
        print_table(&rows);
    } else {
        println!("{OPERATION}  {state}");
        println!("error    {}", error_text(&snapshot["error"]));
    }
    if let Some(warnings) = response["warnings"].as_array() {
        for w in warnings {
            println!("warning  {}", text(w));
        }
    }
    let cleanup = &snapshot["cleanup"];
    if cleanup["status"] != "complete" && cleanup["status"] != "not_required" {
        println!(
            "cleanup  {} ({})",
            text(&cleanup["status"]),
            error_text(&cleanup["error"])
        );
    }
    for phase in ["handshake", "execution"] {
        let diag = text(&snapshot["diagnostics"][phase]);
        if !diag.is_empty() && diag != "-" {
            println!("{phase} stderr:\n{diag}");
        }
    }
    let provenance = &response["provenance"];
    if provenance.is_object() {
        println!(
            "input    {}",
            text(&provenance["input_fingerprint"]["resolved_path"])
        );
        println!(
            "backend  lammpkeeper {}, Python {} ({}), NumPy {}",
            text(&provenance["package_version"]),
            text(&provenance["python_version"]),
            text(&provenance["python_executable"]),
            text(&provenance["numpy_version"])
        );
    }
}

/// Print rows as left-aligned columns; the first row is the header.
fn print_table(rows: &[Vec<String>]) {
    let widths: Vec<usize> = (0..rows[0].len())
        .map(|c| rows.iter().map(|r| r[c].chars().count()).max().unwrap_or(0))
        .collect();
    for row in rows {
        let line: Vec<String> = row
            .iter()
            .zip(&widths)
            .map(|(cell, w)| format!("{cell:<w$}"))
            .collect();
        println!("  {}", line.join("  ").trim_end());
    }
}

/// `thermo-summary`: run `thermo.summary` v1 through `lkpr run` and report it.
///
/// Exit status follows the snapshot state, except that a forwarded Ctrl-C
/// always returns 130, even if the job happened to finish first: the user
/// asked to stop, and scripts should see that.
fn thermo_summary(options: &Options, python: &str) -> Result<u8, Failure> {
    let log = options
        .log
        .as_ref()
        .ok_or_else(|| usage_error("thermo-summary needs --log FILE"))?;
    let timeout = options.timeout.unwrap_or(60.0);
    let request = json!({
        "protocol_version": PROTOCOL_VERSION,
        "request_id": format!("lkpr-rs-{}", std::process::id()),
        "operation": OPERATION,
        "operation_version": OPERATION_VERSION,
        "input": {"log": log},
        "parameters": {},
    });
    let body =
        serde_json::to_vec(&request).map_err(|e| failure(format!("cannot encode request: {e}")))?;
    let args = vec![
        "-m".to_string(),
        "lammpkeeper".to_string(),
        "run".to_string(),
        "--request".to_string(),
        "-".to_string(),
        "--python".to_string(),
        python.to_string(),
        "--timeout".to_string(),
        timeout.to_string(),
    ];
    let deadline = deadline_after(timeout).ok_or_else(|| usage_error("--timeout is too large"))?;
    let (snapshot, outcome) = run_backend(python, args, Some(&body), deadline)?;
    if snapshot["job_schema_version"] != 1 || !snapshot["state"].is_string() {
        return Err(failure("invalid_backend_output: the backend did not return a job snapshot (job_schema_version 1)"));
    }
    if options.json {
        print_raw(&outcome.stdout)?;
    } else {
        print_summary(&snapshot);
    }
    if outcome.interrupted {
        return Ok(130);
    }
    Ok(if snapshot["state"] == "succeeded" {
        0
    } else {
        1
    })
}

/// Parse arguments, install the Ctrl-C handler and run the chosen command.
fn main() -> ExitCode {
    let args = match utf8_args() {
        Ok(args) => args,
        Err(err) => return exit_with(err),
    };
    match args.first().map(String::as_str) {
        Some("--help" | "-h") if args.len() == 1 => {
            println!("{USAGE}");
            return ExitCode::SUCCESS;
        }
        Some("--version") if args.len() == 1 => {
            println!("lkpr-rs {}", env!("CARGO_PKG_VERSION"));
            return ExitCode::SUCCESS;
        }
        _ => {}
    }
    backend::install_sigint_handler();
    let result = parse_args(&args).and_then(|options| {
        let python = select_python(&options)?;
        match options.command.as_str() {
            "doctor" => doctor(&options, &python),
            _ => thermo_summary(&options, &python),
        }
    });
    match result {
        Ok(code) => ExitCode::from(code),
        Err(err) => exit_with(err),
    }
}

/// Report a failure on stderr and map it to the exit status.
fn exit_with(err: Failure) -> ExitCode {
    eprintln!("lkpr-rs: {}", err.message);
    // A Ctrl-C that ended in a backend failure still reports interruption.
    ExitCode::from(if backend::interrupted() && err.code == 1 {
        130
    } else {
        err.code
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Owned argument vector from string literals.
    fn args(list: &[&str]) -> Vec<String> {
        list.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    /// All thermo-summary options parse, including a log path with a space.
    fn parses_thermo_summary_options() {
        let o = parse_args(&args(&[
            "thermo-summary",
            "--log",
            "a b.log",
            "--python",
            "/x/py",
            "--timeout",
            "5",
            "--json",
        ]))
        .ok()
        .unwrap();
        assert_eq!(o.log.as_deref(), Some("a b.log"));
        assert_eq!(o.python.as_deref(), Some("/x/py"));
        assert_eq!(o.timeout, Some(5.0));
        assert!(o.json);
    }

    #[test]
    /// Invalid, unknown and repeated options are usage errors (exit 2).
    fn rejects_bad_timeouts_unknown_and_repeated_options() {
        for bad in [
            &["thermo-summary", "--timeout", "0"][..],
            &["thermo-summary", "--timeout", "-1"],
            &["thermo-summary", "--timeout", "nan"],
            &["thermo-summary", "--timeout", "inf"],
            &["thermo-summary", "--timeout", "x"],
            &["thermo-summary", "--timeout", "1e30"],
            &["thermo-summary", "--timeout", "1e300"],
            &["thermo-summary", "--log", "a", "--log", "b"],
            &["doctor", "--log", "a"],
            &["doctor", "--frobnicate"],
            &["thermo-summary", "--python"],
            &["unknown"],
            &[],
        ] {
            let err = parse_args(&args(bad))
                .err()
                .unwrap_or_else(|| panic!("must fail: {bad:?}"));
            assert_eq!(err.code, 2, "{bad:?}");
        }
    }

    #[test]
    /// Displayed numbers keep their original JSON digits.
    fn number_text_keeps_original_digits() {
        // arbitrary_precision: exact integers and long decimals print unchanged.
        let v: Value =
            serde_json::from_str(r#"{"a": 9007199254740993, "b": 1.632993161855452, "c": -0.0}"#)
                .unwrap();
        assert_eq!(text(&v["a"]), "9007199254740993");
        assert_eq!(text(&v["b"]), "1.632993161855452");
        assert_eq!(text(&v["c"]), "-0.0");
    }

    #[test]
    /// Protocol and operation versions are both required by doctor.
    fn capability_versions_are_checked() {
        let ok = json!({"result": {"protocol_versions": [1], "operations": {"thermo.summary": {"versions": [1]}}}});
        assert_eq!(supports(&ok), (true, true));
        let bad = json!({"result": {"protocol_versions": [2], "operations": {"other": {"versions": [1]}}}});
        assert_eq!(supports(&bad), (false, false));
    }
}
