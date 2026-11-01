//! Process-level tests of `lkpr-rs` against fake backends (shell scripts that
//! stand in for `python`). They exercise launch, transport, interruption and
//! forced-termination paths without needing Python or lammpkeeper. The real
//! backend is exercised by `tests/test_rust_cli.py` in the Python suite.

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use std::thread;
use std::time::{Duration, Instant};

/// Path of the `lkpr-rs` binary that Cargo built for these tests.
fn bin() -> &'static str {
    env!("CARGO_BIN_EXE_lkpr-rs")
}

/// A fresh temporary directory (with a space in its name) for one test.
fn tempdir(tag: &str) -> PathBuf {
    let base = std::env::var_os("TMPDIR")
        .map(PathBuf::from)
        .unwrap_or_else(std::env::temp_dir);
    let dir = base.join(format!("lkpr rs {tag} {}", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    dir
}

/// Write an executable fake interpreter script.
fn fake(dir: &Path, body: &str) -> PathBuf {
    let path = dir.join("fake python");
    fs::write(&path, format!("#!/bin/bash\n{body}\n")).unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
    path
}

/// Run `lkpr-rs` to completion with `LKPR_PYTHON` removed from its environment.
fn run(args: &[&str]) -> Output {
    Command::new(bin())
        .args(args)
        .env_remove("LKPR_PYTHON")
        .output()
        .unwrap()
}

/// Captured stderr as text, for assertion messages.
fn stderr(o: &Output) -> String {
    String::from_utf8_lossy(&o.stderr).into_owned()
}

/// True if the process no longer exists or is a zombie awaiting its reaper.
fn gone(pid: i32) -> bool {
    match fs::read_to_string(format!("/proc/{pid}/stat")) {
        Err(_) => true,
        Ok(stat) => stat
            .rsplit(") ")
            .next()
            .map(|s| s.starts_with('Z'))
            .unwrap_or(true),
    }
}

/// Poll for up to 3 s until `pid` is gone; false if it is still alive.
fn wait_gone(pid: i32) -> bool {
    let until = Instant::now() + Duration::from_secs(3);
    while Instant::now() < until {
        if gone(pid) {
            return true;
        }
        thread::sleep(Duration::from_millis(20));
    }
    false
}

/// Wait until a fake publishes its pid file; returns the pid.
fn await_pid(path: &Path) -> i32 {
    let until = Instant::now() + Duration::from_secs(10);
    while Instant::now() < until {
        if let Ok(text) = fs::read_to_string(path) {
            if let Ok(pid) = text.trim().parse() {
                return pid;
            }
        }
        thread::sleep(Duration::from_millis(10));
    }
    panic!("fake backend did not start: {}", path.display());
}

/// Without `--python` or `LKPR_PYTHON` the CLI refuses to guess (exit 2).
#[test]
fn requires_an_explicit_python_environment() {
    let o = run(&["doctor"]);
    assert_eq!(o.status.code(), Some(2), "{}", stderr(&o));
    assert!(stderr(&o).contains("LKPR_PYTHON"));
}

/// A nonexistent interpreter is a named `python_not_found` failure (exit 1).
#[test]
fn missing_interpreter_is_a_clear_failure() {
    let o = run(&["doctor", "--python", "/nonexistent/lkpr-python"]);
    assert_eq!(o.status.code(), Some(1));
    assert!(stderr(&o).contains("python_not_found"), "{}", stderr(&o));
}

/// The backend receives `-m lammpkeeper run` and the exact request JSON.
#[test]
fn passes_the_request_and_arguments_to_lkpr_run() {
    let dir = tempdir("args");
    let py = fake(
        &dir,
        &format!(
            "printf '%s\\n' \"$@\" > {argv:?}\ncat > {req:?}\n\
             echo '{{\"job_schema_version\":1,\"state\":\"failed\",\"error\":{{\"code\":\"x\",\"message\":\"y\"}}}}'",
            argv = dir.join("argv"),
            req = dir.join("request.json"),
        ),
    );
    let py = py.to_str().unwrap();
    let o = run(&[
        "thermo-summary",
        "--python",
        py,
        "--log",
        "my log.lammps",
        "--timeout",
        "5",
    ]);
    assert_eq!(o.status.code(), Some(1), "{}", stderr(&o));
    let argv = fs::read_to_string(dir.join("argv")).unwrap();
    let expected = format!("-m\nlammpkeeper\nrun\n--request\n-\n--python\n{py}\n--timeout\n5\n");
    assert_eq!(argv, expected);
    let request: serde_json::Value =
        serde_json::from_slice(&fs::read(dir.join("request.json")).unwrap()).unwrap();
    assert_eq!(request["protocol_version"], 1);
    assert_eq!(request["operation"], "thermo.summary");
    assert_eq!(request["operation_version"], 1);
    assert_eq!(request["input"]["log"], "my log.lammps");
    assert_eq!(request["parameters"], serde_json::json!({}));
}

/// `--json` forwards the backend snapshot bytes without re-encoding.
#[test]
fn json_mode_prints_backend_bytes_unchanged() {
    let dir = tempdir("verbatim");
    // Exact integers, a long mantissa and a signed-integer string must survive.
    let body = r#"{"job_schema_version":1,"state":"succeeded","n":9007199254740993,"x":1.632993161855452,"s":"-1793502750687555869"}"#;
    let py = fake(&dir, &format!("cat >/dev/null\nprintf '%s' '{body}'"));
    let o = run(&[
        "thermo-summary",
        "--python",
        py.to_str().unwrap(),
        "--log",
        "a",
        "--json",
    ]);
    assert_eq!(o.status.code(), Some(0), "{}", stderr(&o));
    assert_eq!(String::from_utf8(o.stdout).unwrap(), format!("{body}\n"));
}

/// `--json` output that cannot be written (here: `/dev/full`) fails with exit
/// 1 and `output_write_failed`; lost machine output must not exit 0.
#[test]
fn json_mode_write_failure_is_not_success() {
    let dir = tempdir("write fail");
    let body = r#"{"job_schema_version":1,"state":"succeeded"}"#;
    let py = fake(&dir, &format!("cat >/dev/null\nprintf '%s' '{body}'"));
    let full = fs::OpenOptions::new()
        .write(true)
        .open("/dev/full")
        .unwrap();
    let o = Command::new(bin())
        .args([
            "thermo-summary",
            "--python",
            py.to_str().unwrap(),
            "--log",
            "a",
            "--json",
        ])
        .env_remove("LKPR_PYTHON")
        .stdout(full)
        .output()
        .unwrap();
    assert_eq!(o.status.code(), Some(1), "{}", stderr(&o));
    assert!(stderr(&o).contains("output_write_failed"), "{}", stderr(&o));
}

/// Non-JSON, empty or crashed backend output fails instead of printing a result.
#[test]
fn malformed_or_crashed_backend_output_is_rejected() {
    let dir = tempdir("malformed");
    for body in [
        "cat >/dev/null; echo 'not json'",
        "cat >/dev/null; echo '[1]'",
        "kill -SEGV $$",
        "exit 0",
    ] {
        let py = fake(&dir, body);
        let o = run(&[
            "thermo-summary",
            "--python",
            py.to_str().unwrap(),
            "--log",
            "a",
        ]);
        assert_eq!(o.status.code(), Some(1), "{body}: {}", stderr(&o));
        assert!(
            stderr(&o).contains("invalid_backend_output"),
            "{body}: {}",
            stderr(&o)
        );
        assert!(
            o.stdout.is_empty(),
            "{body}: no partial result may be printed"
        );
    }
}

/// Valid JSON that is not a job snapshot is rejected.
#[test]
fn non_snapshot_json_is_rejected() {
    let dir = tempdir("nonsnapshot");
    let py = fake(&dir, "cat >/dev/null; echo '{\"state\":\"succeeded\"}'");
    let o = run(&[
        "thermo-summary",
        "--python",
        py.to_str().unwrap(),
        "--log",
        "a",
    ]);
    assert_eq!(o.status.code(), Some(1));
    assert!(stderr(&o).contains("job snapshot"), "{}", stderr(&o));
}

/// Output beyond the cap stops a still-running backend with `output_too_large`.
#[test]
fn oversized_output_stops_the_backend() {
    let dir = tempdir("large");
    let py = fake(&dir, "cat >/dev/null; head -c 20000000 /dev/zero; sleep 30");
    let start = Instant::now();
    let o = run(&[
        "thermo-summary",
        "--python",
        py.to_str().unwrap(),
        "--log",
        "a",
    ]);
    assert_eq!(o.status.code(), Some(1));
    assert!(stderr(&o).contains("output_too_large"), "{}", stderr(&o));
    assert!(start.elapsed() < Duration::from_secs(10));
}

/// `doctor` fails (exit 1) and says "NOT supported" for unknown protocol versions.
#[test]
fn incompatible_backend_versions_fail_doctor() {
    let dir = tempdir("incompatible");
    let caps = r#"{"status":"succeeded","result":{"protocol_versions":[2],"operations":{"thermo.summary":{"versions":[2]}}},"provenance":{"package_version":"9.9"}}"#;
    let py = fake(&dir, &format!("printf '%s' '{caps}'"));
    let o = run(&["doctor", "--python", py.to_str().unwrap()]);
    assert_eq!(o.status.code(), Some(1));
    assert!(
        stderr(&o).contains("incompatible_backend"),
        "{}",
        stderr(&o)
    );
    assert!(String::from_utf8_lossy(&o.stdout).contains("NOT supported"));
}

/// Output beyond the cap is detected even when the backend exits in the same
/// poll in which it overflowed (audit 2026-11-01): before the fix the stream
/// was kept with a hole in it and misreported as invalid output.
#[test]
fn oversized_output_is_detected_when_the_backend_exits_at_once() {
    let dir = tempdir("large exit");
    // One byte over the cap: the overflow is seen only on the last read,
    // after the backend has already written everything and exited.
    let py = fake(&dir, "cat >/dev/null; head -c 16777217 /dev/zero");
    for _ in 0..3 {
        let o = run(&[
            "thermo-summary",
            "--python",
            py.to_str().unwrap(),
            "--log",
            "a",
        ]);
        assert_eq!(o.status.code(), Some(1));
        assert!(stderr(&o).contains("output_too_large"), "{}", stderr(&o));
    }
}

/// Start lkpr-rs with a fake backend, wait for the fake to start, send SIGINT.
fn interrupt_run(py: &Path, pid_file: &Path) -> (Output, i32) {
    let child = Command::new(bin())
        .args([
            "thermo-summary",
            "--python",
            py.to_str().unwrap(),
            "--log",
            "a",
            "--timeout",
            "60",
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let fake_pid = await_pid(pid_file);
    // SAFETY: SIGINT to the lkpr-rs process we started.
    unsafe {
        libc::kill(child.id() as libc::pid_t, libc::SIGINT);
    }
    (child.wait_with_output().unwrap(), fake_pid)
}

/// Ctrl-C reaches `lkpr run` once; the CLI exits 130 with the final snapshot.
#[test]
fn ctrl_c_is_forwarded_once_and_reports_interruption() {
    let dir = tempdir("sigint");
    let pid_file = dir.join("pid");
    let count = dir.join("count");
    // Behaves like `lkpr run`: on SIGINT, publish a cancelled snapshot and exit 130.
    let py = fake(
        &dir,
        &format!(
            "cat >/dev/null\ntrap 'echo int >> {count:?}; \
             echo \"{{\\\"job_schema_version\\\":1,\\\"state\\\":\\\"cancelled\\\",\\\"error\\\":{{\\\"code\\\":\\\"cancelled\\\",\\\"message\\\":\\\"by owner\\\"}}}}\"; exit 130' INT\n\
             echo $$ > {pid:?}\nwhile true; do sleep 0.05; done",
            count = count,
            pid = pid_file,
        ),
    );
    let (o, fake_pid) = interrupt_run(&py, &pid_file);
    assert_eq!(o.status.code(), Some(130), "{}", stderr(&o));
    let out = String::from_utf8_lossy(&o.stdout);
    assert!(out.contains("cancelled"), "{out}");
    assert_eq!(
        fs::read_to_string(&count).unwrap(),
        "int\n",
        "exactly one SIGINT forwarded"
    );
    assert!(wait_gone(fake_pid));
}

/// A backend ignoring the forwarded Ctrl-C is killed and reported as forced.
#[test]
fn unresponsive_backend_after_ctrl_c_is_forced_and_not_called_cancelled() {
    let dir = tempdir("unresponsive");
    let pid_file = dir.join("pid");
    let grandchild = dir.join("grandchild");
    // Ignores SIGINT, exits at once on SIGTERM, and leaves a grandchild that
    // ignores SIGTERM and holds the stdout pipe: only a group SIGKILL stops it.
    let py = fake(
        &dir,
        &format!(
            "cat >/dev/null\ntrap '' INT\ntrap 'exit 0' TERM\n\
             bash -c 'trap \"\" TERM; exec sleep 300' & echo $! > {g:?}\necho $$ > {p:?}\nwait",
            g = grandchild,
            p = pid_file,
        ),
    );
    let start = Instant::now();
    let (o, fake_pid) = interrupt_run(&py, &pid_file);
    let elapsed = start.elapsed();
    assert_eq!(o.status.code(), Some(130), "{}", stderr(&o));
    let err = stderr(&o);
    assert!(
        err.contains("supervisor_unresponsive") && err.contains("after Ctrl-C"),
        "{err}"
    );
    assert!(!String::from_utf8_lossy(&o.stdout).contains("cancelled"));
    // INTERRUPT_GRACE (10 s) + KILL_GRACE (2 s) bound the wait.
    assert!(elapsed < Duration::from_secs(16), "{elapsed:?}");
    assert!(wait_gone(fake_pid));
    let g: i32 = fs::read_to_string(&grandchild)
        .unwrap()
        .trim()
        .parse()
        .unwrap();
    assert!(wait_gone(g), "process-group member must be stopped too");
}

/// A backend running past the deadline plus grace is killed with its group.
#[test]
fn backend_that_outlives_its_deadline_is_forced() {
    let dir = tempdir("deadline");
    let pid_file = dir.join("pid");
    let py = fake(
        &dir,
        &format!("cat >/dev/null\necho $$ > {pid_file:?}\nsleep 300"),
    );
    let start = Instant::now();
    // Backend timeout 0.1 s + DEADLINE_SLACK 15 s, then SIGTERM.
    let o = run(&[
        "thermo-summary",
        "--python",
        py.to_str().unwrap(),
        "--log",
        "a",
        "--timeout",
        "0.1",
    ]);
    let elapsed = start.elapsed();
    assert_eq!(o.status.code(), Some(1), "{}", stderr(&o));
    let err = stderr(&o);
    assert!(
        err.contains("supervisor_unresponsive") && !err.contains("after Ctrl-C"),
        "{err}"
    );
    assert!(
        elapsed >= Duration::from_secs(15) && elapsed < Duration::from_secs(20),
        "{elapsed:?}"
    );
    let pid: i32 = fs::read_to_string(&pid_file)
        .unwrap()
        .trim()
        .parse()
        .unwrap();
    assert!(wait_gone(pid));
}

/// Wait for a process with a hard limit, killing it on timeout (test guard).
fn wait_bounded(mut child: std::process::Child, limit: Duration) -> Output {
    let until = Instant::now() + limit;
    while Instant::now() < until {
        if child.try_wait().unwrap().is_some() {
            return child.wait_with_output().unwrap();
        }
        thread::sleep(Duration::from_millis(20));
    }
    let _ = child.kill();
    panic!("lkpr-rs did not finish within {limit:?}");
}

/// Ctrl-C is not blocked by a request write the backend never reads.
#[test]
fn ctrl_c_works_while_the_backend_never_reads_a_large_request() {
    let dir = tempdir("stdin");
    let pid_file = dir.join("pid");
    // Never reads stdin; a request larger than a pipe buffer must not block lkpr-rs.
    let py = fake(
        &dir,
        &format!(
            "trap 'echo \"{{\\\"job_schema_version\\\":1,\\\"state\\\":\\\"cancelled\\\"}}\"; exit 130' INT\n\
             echo $$ > {pid_file:?}\nwhile true; do sleep 0.05; done"
        ),
    );
    // Below the 128 KiB single-argument limit, above the 64 KiB pipe buffer.
    let long_log = "x".repeat(100_000);
    let child = Command::new(bin())
        .args([
            "thermo-summary",
            "--python",
            py.to_str().unwrap(),
            "--log",
            &long_log,
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    await_pid(&pid_file);
    // SAFETY: SIGINT to the lkpr-rs process we started.
    unsafe {
        libc::kill(child.id() as libc::pid_t, libc::SIGINT);
    }
    let o = wait_bounded(child, Duration::from_secs(20));
    assert_eq!(o.status.code(), Some(130), "{}", stderr(&o));
    assert!(String::from_utf8_lossy(&o.stdout).contains("cancelled"));
}

/// A grandchild holding stdout open after exit is reported, not waited on.
#[test]
fn stdout_held_open_after_exit_is_reported_not_waited_forever() {
    let dir = tempdir("heldopen");
    // Prints a complete snapshot, then leaves a background process holding stdout.
    let py = fake(
        &dir,
        "cat >/dev/null\necho '{\"job_schema_version\":1,\"state\":\"succeeded\"}'\n(sleep 30) 2>/dev/null &\nexit 0",
    );
    let child = Command::new(bin())
        .args([
            "thermo-summary",
            "--python",
            py.to_str().unwrap(),
            "--log",
            "a",
        ])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let start = Instant::now();
    let o = wait_bounded(child, Duration::from_secs(20));
    assert_eq!(o.status.code(), Some(1), "{}", stderr(&o));
    assert!(
        stderr(&o).contains("backend_stdout_held_open"),
        "{}",
        stderr(&o)
    );
    assert!(start.elapsed() < Duration::from_secs(10));
}
