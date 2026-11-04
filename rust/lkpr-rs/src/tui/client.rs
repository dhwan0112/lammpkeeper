//! Backend client of the TUI: runs the capability probe and the job on
//! threads with the UI-1 supervisor (`backend::supervise_with`), reads the
//! backend's piped stderr line by line, and reports to the reducer over a
//! channel. The backend never blocks on the screen (stderr is drained
//! continuously, stdout is bounded as in UI-1) and the screen never blocks on
//! the backend.

use super::app::{Event, Line, Msg, Probe, Save, Start, DIAGNOSTICS_TAIL};
use crate::backend::{self, StderrMode};
use crate::{deadline_after, interpret, run_args, text, visible, DOCTOR_TIMEOUT};
use serde_json::Value;
use std::collections::VecDeque;
use std::fs::OpenOptions;
use std::io::{BufRead, BufReader, Read, Write};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::atomic::Ordering;
use std::sync::mpsc::{self, Sender};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

/// Longest stderr line kept; the rest of a longer line is dropped and the
/// line is marked.
pub const LINE_MAX: usize = 4096;
/// How long the probe waits for the stderr reader after the backend exited
/// before reporting without the tail.
const TAIL_WAIT: Duration = Duration::from_millis(500);

/// Run `work` on a new thread and send what it returns; if the thread
/// panics instead, send `on_panic(message)` so the reducer is never left
/// waiting for an answer that cannot come. (The TUI's panic hook prints
/// nothing for worker threads; the message is what the screen shows.)
fn spawn_guarded(
    tx: Sender<Msg>,
    work: impl FnOnce() -> Msg + Send + 'static,
    on_panic: impl FnOnce(String) -> Msg + Send + 'static,
) {
    thread::spawn(move || {
        let msg = match catch_unwind(AssertUnwindSafe(work)) {
            Ok(msg) => msg,
            Err(payload) => {
                let why = payload
                    .downcast_ref::<&str>()
                    .map(|s| (*s).to_string())
                    .or_else(|| payload.downcast_ref::<String>().cloned())
                    .unwrap_or_else(|| "unknown panic".to_string());
                on_panic(format!(
                    "internal_error: the backend thread panicked: {why}"
                ))
            }
        };
        let _ = tx.send(msg);
    });
}

/// `exec --capabilities` on a thread; the answer (or the failure with the
/// backend's stderr tail) is sent as [`Msg::Probed`].
pub fn probe(probe: Probe, tx: Sender<Msg>) {
    let id = probe.id;
    let on_panic = move |why| Msg::Probed {
        probe: id,
        result: Err(why),
    };
    spawn_guarded(
        tx,
        move || {
            let args = ["-m", "lammpkeeper", "exec", "--capabilities"]
                .map(String::from)
                .to_vec();
            let result = match backend::spawn(&probe.python, &args, None, StderrMode::Piped) {
                Err(err) => Err(format!(
                    "python_not_found: cannot start {:?}: {err}",
                    probe.python
                )),
                Ok(mut child) => {
                    let stderr = child.stderr.take().expect("stderr is piped");
                    let (tail_tx, tail_rx) = mpsc::channel();
                    thread::spawn(move || {
                        read_lines(stderr, |line| {
                            let _ = tail_tx.send(line);
                        })
                    });
                    let cancel = probe.cancel.clone();
                    let outcome =
                        backend::supervise_with(child, Instant::now() + DOCTOR_TIMEOUT, &|| {
                            cancel.load(Ordering::SeqCst)
                        });
                    interpret(&probe.python, &outcome).map_err(|failure| {
                        let mut tail = VecDeque::new();
                        while let Ok(line) = tail_rx.recv_timeout(TAIL_WAIT) {
                            if let Line::Diagnostic(text) = line {
                                if tail.len() == DIAGNOSTICS_TAIL {
                                    tail.pop_front();
                                }
                                tail.push_back(text);
                            }
                        }
                        if tail.is_empty() {
                            failure.message
                        } else {
                            let tail = tail.into_iter().collect::<Vec<_>>().join("\n");
                            format!("{}\nbackend stderr:\n{tail}", failure.message)
                        }
                    })
                }
            };
            Msg::Probed {
                probe: probe.id,
                result,
            }
        },
        on_panic,
    );
}

/// `run --request - --events` on a thread. Every stderr line arrives as
/// [`Msg::Line`] while it runs; the end is [`Msg::Finished`].
pub fn start(start: Start, tx: Sender<Msg>) {
    let id = start.id;
    let on_panic = move |why| Msg::Finished {
        run: id,
        result: Err(why),
        interrupted: false,
    };
    let lines = tx.clone();
    spawn_guarded(
        tx,
        move || {
            let mut args = run_args(&start.python, start.timeout);
            args.push("--events".to_string());
            let (result, interrupted) =
                match backend::spawn(&start.python, &args, Some(&start.body), StderrMode::Piped) {
                    Err(err) => (
                        Err(format!(
                            "python_not_found: cannot start {:?}: {err}",
                            start.python
                        )),
                        false,
                    ),
                    Ok(mut child) => {
                        let stderr = child.stderr.take().expect("stderr is piped");
                        // `done` closes when the reader is through: Finished is
                        // held back, bounded, so the last lines land first.
                        let (done, drained) = mpsc::channel::<()>();
                        thread::spawn(move || {
                            read_lines(stderr, |line| {
                                let _ = lines.send(Msg::Line { run: id, line });
                            });
                            drop(done);
                        });
                        // Validated by the form; the fallback cannot be reached.
                        let deadline = deadline_after(start.timeout)
                            .unwrap_or_else(|| Instant::now() + DOCTOR_TIMEOUT);
                        let cancel = start.cancel.clone();
                        let outcome = backend::supervise_with(child, deadline, &|| {
                            cancel.load(Ordering::SeqCst)
                        });
                        let interrupted = outcome.interrupted;
                        let result = interpret(&start.python, &outcome)
                            .map(|value| (value, outcome.stdout))
                            .map_err(|failure| failure.message);
                        let _ = drained.recv_timeout(TAIL_WAIT);
                        (result, interrupted)
                    }
                };
            Msg::Finished {
                run: start.id,
                result,
                interrupted,
            }
        },
        on_panic,
    );
}

/// Read `stderr` line by line until it closes and classify each line. At
/// most [`LINE_MAX`] bytes of a line are kept (the rest is skipped and the
/// line marked), invalid UTF-8 is replaced, and control characters are made
/// visible, so a backend cannot draw on the screen or hide text in it.
fn read_lines(stderr: impl Read, mut each: impl FnMut(Line)) {
    let mut reader = BufReader::new(stderr);
    let mut buf = Vec::with_capacity(1024);
    loop {
        buf.clear();
        let n = match (&mut reader)
            .take(LINE_MAX as u64 + 1)
            .read_until(b'\n', &mut buf)
        {
            Ok(0) | Err(_) => break,
            Ok(n) => n,
        };
        let complete = buf.ends_with(b"\n");
        if complete {
            buf.pop();
            if buf.ends_with(b"\r") {
                buf.pop();
            }
        }
        let mut more = false;
        if buf.len() > LINE_MAX {
            buf.truncate(LINE_MAX);
            more = true;
        }
        // The limit was hit without a newline: the line goes on.
        let eof = !complete && n > LINE_MAX && !skip_line(&mut reader);
        let mut text = String::from_utf8_lossy(&buf).into_owned();
        if more {
            text.push_str(" [line truncated]");
        }
        each(classify(&text));
        if eof {
            break;
        }
    }
}

/// Discard the rest of the current line; false at end of input.
fn skip_line(reader: &mut impl BufRead) -> bool {
    let mut scratch = Vec::new();
    loop {
        scratch.clear();
        match (&mut *reader).take(65536).read_until(b'\n', &mut scratch) {
            Ok(0) | Err(_) => return false,
            Ok(_) if scratch.ends_with(b"\n") => return true,
            Ok(_) => {}
        }
    }
}

/// A JSON object with `sequence` and `state` is a lifecycle event; anything
/// else is diagnostics text.
pub fn classify(line: &str) -> Line {
    if let Ok(Value::Object(map)) = serde_json::from_str::<Value>(line) {
        let sequence = map.get("sequence").and_then(Value::as_u64);
        let state = map.get("state").and_then(Value::as_str);
        if let (Some(sequence), Some(state)) = (sequence, state) {
            return Line::Event(Event {
                sequence,
                state: visible(state),
                elapsed: map
                    .get("elapsed_seconds")
                    .map_or_else(|| "-".to_string(), text),
            });
        }
    }
    Line::Diagnostic(visible(line))
}

/// A fresh request id for one run: a random UUID (version 4) from
/// `/dev/urandom`, or a time- and pid-based one if that cannot be read. The
/// backend echoes it in the snapshot and the Result screen checks the echo.
pub fn fresh_request_id() -> String {
    let mut bytes = [0u8; 16];
    let random = std::fs::File::open("/dev/urandom")
        .and_then(|mut file| file.read_exact(&mut bytes))
        .is_ok();
    if !random {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_or(0, |d| d.as_nanos());
        let mixed = nanos ^ (u128::from(std::process::id()) << 96);
        bytes.copy_from_slice(&mixed.to_le_bytes());
    }
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    let hex = |range: std::ops::Range<usize>| -> String {
        bytes[range].iter().map(|b| format!("{b:02x}")).collect()
    };
    format!(
        "{}-{}-{}-{}-{}",
        hex(0..4),
        hex(4..6),
        hex(6..8),
        hex(8..10),
        hex(10..16)
    )
}

/// Write the raw snapshot to `path` (never over an existing file) and, when
/// there are diagnostics, their tail to `<path>.stderr.txt`. The snapshot
/// gets the trailing newline `--json` prints, so the files compare equal.
pub fn save(save: &Save) -> Result<String, String> {
    let aside = (!save.diagnostics.is_empty()).then(|| format!("{}.stderr.txt", save.path));
    // Refuse before writing anything when the second file is already taken,
    // so a refused save never leaves half of the pair behind.
    if let Some(aside) = aside.as_ref().filter(|a| std::path::Path::new(a).exists()) {
        return Err(format!("cannot create {aside}: it already exists"));
    }
    write_new(&save.path, &save.snapshot, true)?;
    let mut done = format!("saved {}", save.path);
    if let Some(aside) = aside {
        write_new(&aside, save.diagnostics.as_bytes(), false)
            .map_err(|problem| format!("{done}, but {problem}"))?;
        done.push_str(&format!(" and {aside}"));
    }
    Ok(done)
}

/// Write `bytes` to a file that must not exist yet (create_new), adding a
/// trailing newline when asked and one is missing.
fn write_new(path: &str, bytes: &[u8], newline: bool) -> Result<(), String> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|err| format!("cannot create {path}: {err}"))?;
    let mut write = || -> std::io::Result<()> {
        file.write_all(bytes)?;
        if newline && !bytes.ends_with(b"\n") {
            file.write_all(b"\n")?;
        }
        file.flush()
    };
    write().map_err(|err| format!("cannot write {path}: {err}"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::sync::atomic::AtomicBool;
    use std::sync::Arc;

    #[test]
    /// Event lines, log lines, binary garbage and over-long lines.
    fn classifies_stderr_lines() {
        assert_eq!(
            classify(r#"{"sequence": 2, "state": "running", "elapsed_seconds": 0.0123456789}"#),
            Line::Event(Event {
                sequence: 2,
                state: "running".into(),
                elapsed: "0.0123456789".into()
            })
        );
        assert_eq!(
            classify(r#"{"sequence": 1, "state": "created"}"#),
            Line::Event(Event {
                sequence: 1,
                state: "created".into(),
                elapsed: "-".into()
            })
        );
        for plain in [
            r#"{"state": "running"}"#,
            r#"{"sequence": "1", "state": "running"}"#,
            r#"[1, 2]"#,
            "Traceback (most recent call last):",
            "",
        ] {
            assert_eq!(
                classify(plain),
                Line::Diagnostic(plain.to_string()),
                "{plain}"
            );
        }
        assert_eq!(
            classify("x\u{1b}[31my\u{7}"),
            Line::Diagnostic("x\\u{1b}[31my\\u{7}".into())
        );
    }

    #[test]
    /// The reader splits on newlines, bounds each line, replaces invalid
    /// UTF-8 and reports the final unterminated line.
    fn reads_lines_bounded() {
        let long = "a".repeat(LINE_MAX + 10);
        let mut input = Vec::new();
        input.extend_from_slice(br#"{"sequence": 1, "state": "created", "elapsed_seconds": 0.0}"#);
        input.extend_from_slice(b"\n\x1b[2Jb\r\nc\xff\xffd\n");
        input.extend_from_slice(long.as_bytes());
        input.extend_from_slice(b"\nlast");
        let mut lines = Vec::new();
        read_lines(input.as_slice(), |line| lines.push(line));
        assert_eq!(lines.len(), 5, "{lines:?}");
        assert!(matches!(&lines[0], Line::Event(e) if e.state == "created"));
        assert_eq!(lines[1], Line::Diagnostic("\\u{1b}[2Jb".into()));
        assert_eq!(lines[2], Line::Diagnostic("c\u{fffd}\u{fffd}d".into()));
        let Line::Diagnostic(truncated) = &lines[3] else {
            panic!("{:?}", lines[3]);
        };
        assert!(truncated.ends_with(" [line truncated]"));
        assert_eq!(truncated.len(), LINE_MAX + " [line truncated]".len());
        assert_eq!(lines[4], Line::Diagnostic("last".into()));
    }

    #[test]
    /// A line longer than the skip buffer is still skipped to its end.
    fn skips_very_long_lines() {
        let input = format!("{}\nnext\n", "z".repeat(200_000)).into_bytes();
        let mut lines = Vec::new();
        read_lines(input.as_slice(), |line| lines.push(line));
        assert_eq!(lines.len(), 2);
        assert_eq!(lines[1], Line::Diagnostic("next".into()));
    }

    #[test]
    /// Request ids are UUID v4 shaped and differ between runs.
    fn request_ids_are_fresh_uuids() {
        let a = fresh_request_id();
        let b = fresh_request_id();
        assert_ne!(a, b);
        assert_eq!(a.len(), 36);
        assert_eq!(a.as_bytes()[14], b'4');
        assert!(matches!(a.as_bytes()[19], b'8' | b'9' | b'a' | b'b'));
        assert!(a.bytes().all(|c| c == b'-' || c.is_ascii_hexdigit()));
    }

    /// A fresh per-test directory under TMPDIR, named by `tag` and a counter.
    fn tempdir(tag: &str) -> PathBuf {
        static COUNTER: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
        let base = std::env::var_os("TMPDIR")
            .map(PathBuf::from)
            .unwrap_or_else(std::env::temp_dir);
        let n = COUNTER.fetch_add(1, Ordering::SeqCst);
        let dir = base.join(format!("lkpr tui {tag} {} {n}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    /// Write an executable bash script that stands in for the Python backend;
    /// returns its path.
    ///
    /// The executable is written by a separate `install` process, not by this
    /// test process. A write fd opened here is inherited by any child that a
    /// parallel test forks before its exec, and while that copy is open
    /// running the script fails with ETXTBSY ("Text file busy"), which made
    /// the fake-backend tests fail intermittently. `install` opens and closes
    /// the file in its own process, where no test thread can inherit it.
    fn fake(dir: &Path, body: &str) -> String {
        let source = dir.join("fake python.src");
        fs::write(&source, format!("#!/bin/bash\n{body}\n")).unwrap();
        let path = dir.join("fake python");
        let status = std::process::Command::new("install")
            .arg("-m")
            .arg("755")
            .arg(&source)
            .arg(&path)
            .status()
            .unwrap();
        assert!(status.success(), "install failed: {status}");
        path.to_str().unwrap().to_string()
    }

    #[test]
    /// `s` writes the snapshot with the CLI's trailing newline and the
    /// diagnostics beside it, and never overwrites.
    fn save_writes_new_files_only() {
        let dir = tempdir("save");
        let path = dir.join("snap.json").to_str().unwrap().to_string();
        let request = Save {
            path: path.clone(),
            snapshot: b"{\"a\": 1}".to_vec(),
            diagnostics: "warn\n".to_string(),
        };
        let done = save(&request).unwrap();
        assert!(
            done.contains(&path) && done.ends_with(".stderr.txt"),
            "{done}"
        );
        assert_eq!(fs::read(&path).unwrap(), b"{\"a\": 1}\n");
        assert_eq!(fs::read(format!("{path}.stderr.txt")).unwrap(), b"warn\n");
        let err = save(&request).unwrap_err();
        assert!(err.starts_with("cannot create"), "{err}");
        let quiet = Save {
            path: dir.join("quiet.json").to_str().unwrap().to_string(),
            snapshot: b"{}\n".to_vec(),
            diagnostics: String::new(),
        };
        assert!(!save(&quiet).unwrap().contains("stderr"));
        assert!(!dir.join("quiet.json.stderr.txt").exists());
        // The aside already taken: refused before the snapshot is written.
        let taken = dir.join("taken.json").to_str().unwrap().to_string();
        fs::write(format!("{taken}.stderr.txt"), b"old").unwrap();
        let err = save(&Save {
            path: taken.clone(),
            snapshot: b"{}".to_vec(),
            diagnostics: "x\n".to_string(),
        })
        .unwrap_err();
        assert!(
            err.contains("stderr.txt") && err.contains("already exists"),
            "{err}"
        );
        assert!(!Path::new(&taken).exists());
        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    /// A worker that panics still answers the reducer, with the panic text.
    fn a_panicking_worker_reports_instead_of_vanishing() {
        let (tx, rx) = mpsc::channel();
        spawn_guarded(
            tx,
            || panic!("boom {}", 7),
            |why| Msg::Finished {
                run: 3,
                result: Err(why),
                interrupted: false,
            },
        );
        match rx.recv_timeout(Duration::from_secs(5)).unwrap() {
            Msg::Finished {
                run: 3,
                result: Err(why),
                interrupted: false,
            } => assert!(
                why.contains("internal_error") && why.contains("boom 7"),
                "{why}"
            ),
            other => panic!("{other:?}"),
        }
        let (tx, rx) = mpsc::channel();
        spawn_guarded(tx, || Msg::Tick, |_| Msg::Terminate);
        assert!(matches!(
            rx.recv_timeout(Duration::from_secs(5)),
            Ok(Msg::Tick)
        ));
    }

    /// Drive `start` against a fake backend and collect its messages.
    fn run_fake(
        body: &str,
        timeout: f64,
        cancel_after: Option<Duration>,
    ) -> (Vec<Msg>, Arc<AtomicBool>) {
        let dir = tempdir(&format!("run {}", body.len()));
        let python = fake(&dir, body);
        let cancel = Arc::new(AtomicBool::new(false));
        let (tx, rx) = mpsc::channel();
        start(
            Start {
                id: 7,
                python,
                body: b"{\"request\": true}".to_vec(),
                timeout,
                cancel: Arc::clone(&cancel),
            },
            tx,
        );
        if let Some(after) = cancel_after {
            thread::sleep(after);
            cancel.store(true, Ordering::SeqCst);
        }
        let mut messages = Vec::new();
        loop {
            match rx.recv_timeout(Duration::from_secs(60)) {
                Ok(msg) => {
                    let done = matches!(msg, Msg::Finished { .. });
                    messages.push(msg);
                    if done {
                        break;
                    }
                }
                Err(err) => panic!("no Finished: {err} after {messages:?}"),
            }
        }
        fs::remove_dir_all(&dir).unwrap();
        (messages, cancel)
    }

    /// The final `Finished` message of run 7, as (result, interrupted).
    fn finished(messages: &[Msg]) -> (&Result<(Value, Vec<u8>), String>, bool) {
        match messages.last() {
            Some(Msg::Finished {
                run: 7,
                result,
                interrupted,
            }) => (result, *interrupted),
            other => panic!("{other:?}"),
        }
    }

    #[test]
    /// A backend that streams events and a snapshot: events and diagnostics
    /// arrive in order as lines, the snapshot bytes arrive unchanged.
    fn fake_backend_success_streams_events_and_snapshot() {
        let (messages, _) = run_fake(
            "cat >/dev/null\n\
             echo '{\"sequence\": 1, \"state\": \"created\", \"elapsed_seconds\": 0.0}' >&2\n\
             echo 'note from the backend' >&2\n\
             echo '{\"sequence\": 2, \"state\": \"running\", \"elapsed_seconds\": 0.01}' >&2\n\
             printf '{\"job_schema_version\": 1, \"state\": \"succeeded\", \"request_id\": \"r\"}'",
            5.0,
            None,
        );
        let lines: Vec<&Line> = messages
            .iter()
            .filter_map(|m| match m {
                Msg::Line { run: 7, line } => Some(line),
                _ => None,
            })
            .collect();
        assert_eq!(lines.len(), 3, "{messages:?}");
        assert!(matches!(lines[0], Line::Event(e) if e.sequence == 1 && e.state == "created"));
        assert_eq!(lines[1], &Line::Diagnostic("note from the backend".into()));
        assert!(matches!(lines[2], Line::Event(e) if e.sequence == 2 && e.elapsed == "0.01"));
        let (result, interrupted) = finished(&messages);
        let (value, raw) = result.as_ref().unwrap();
        assert_eq!(value["request_id"], "r");
        assert_eq!(
            raw,
            b"{\"job_schema_version\": 1, \"state\": \"succeeded\", \"request_id\": \"r\"}"
        );
        assert!(!interrupted);
    }

    #[test]
    /// Malformed JSON and a crash are named failures, with the exit status.
    fn fake_backend_malformed_output_and_crash_are_failures() {
        let (messages, _) = run_fake("cat >/dev/null; echo 'not json'", 5.0, None);
        let (result, _) = finished(&messages);
        let err = result.as_ref().unwrap_err();
        assert!(err.contains("invalid_backend_output"), "{err}");
        let (messages, _) = run_fake("echo boom >&2; exit 3", 5.0, None);
        let (result, _) = finished(&messages);
        let err = result.as_ref().unwrap_err();
        assert!(
            err.contains("invalid_backend_output") && err.contains("exit status: 3"),
            "{err}"
        );
        assert!(messages
            .iter()
            .any(|m| matches!(m, Msg::Line { line: Line::Diagnostic(t), .. } if t == "boom")));
    }

    #[test]
    /// Cancel reaches a slow backend as one SIGINT; its own snapshot is the
    /// result, with `interrupted` set.
    fn fake_backend_slow_then_cancelled() {
        let started = Instant::now();
        let (messages, cancel) = run_fake(
            "trap 'printf \"{\\\"job_schema_version\\\": 1, \\\"state\\\": \\\"cancelled\\\"}\"; exit 0' INT\n\
             cat >/dev/null\n\
             echo '{\"sequence\": 1, \"state\": \"running\", \"elapsed_seconds\": 0.0}' >&2\n\
             for i in $(seq 1 100); do sleep 0.1; done\n\
             printf '{\"job_schema_version\": 1, \"state\": \"succeeded\"}'",
            30.0,
            Some(Duration::from_millis(600)),
        );
        assert!(cancel.load(Ordering::SeqCst));
        let (result, interrupted) = finished(&messages);
        assert!(interrupted);
        let (value, _) = result.as_ref().unwrap();
        assert_eq!(value["state"], "cancelled", "{value}");
        assert!(
            started.elapsed() < Duration::from_secs(8),
            "{:?}",
            started.elapsed()
        );
    }

    #[test]
    /// A backend that writes events but never exits is forced at the
    /// deadline (timeout + slack) and reported as unresponsive.
    fn fake_backend_unresponsive_is_forced() {
        let started = Instant::now();
        let (messages, _) = run_fake(
            "trap '' INT TERM\n\
             cat >/dev/null\n\
             echo '{\"sequence\": 1, \"state\": \"running\", \"elapsed_seconds\": 0.0}' >&2\n\
             for i in $(seq 1 600); do sleep 0.1; done",
            0.5,
            None,
        );
        let (result, interrupted) = finished(&messages);
        let err = result.as_ref().unwrap_err();
        assert!(err.contains("supervisor_unresponsive"), "{err}");
        assert!(!interrupted);
        // 0.5 s timeout + 15 s slack + 2 s kill grace, well under 60 s.
        assert!(
            started.elapsed() < Duration::from_secs(25),
            "{:?}",
            started.elapsed()
        );
    }

    #[test]
    /// More than MAX_STDOUT bytes stop the backend; the failure names it.
    fn fake_backend_output_too_large() {
        let (messages, _) = run_fake(
            "cat >/dev/null; head -c 17000000 /dev/zero | tr '\\0' 'x'",
            30.0,
            None,
        );
        let (result, _) = finished(&messages);
        let err = result.as_ref().unwrap_err();
        assert!(err.contains("output_too_large"), "{err}");
    }

    #[test]
    /// The probe reports capabilities, and a failing probe carries the
    /// backend's stderr tail; a cancelled probe ends early.
    fn fake_probe_reports_capabilities_or_the_failure() {
        let dir = tempdir("probe");
        let python = fake(
            &dir,
            "echo 'probe says hi' >&2; printf '{\"status\": \"succeeded\", \"result\": {}}'",
        );
        let (tx, rx) = mpsc::channel();
        probe(
            Probe {
                id: 3,
                python: python.clone(),
                cancel: Arc::new(AtomicBool::new(false)),
            },
            tx,
        );
        match rx.recv_timeout(Duration::from_secs(30)).unwrap() {
            Msg::Probed { probe: 3, result } => assert_eq!(result.unwrap()["status"], "succeeded"),
            other => panic!("{other:?}"),
        }
        let python = fake(&dir, "echo 'ModuleNotFoundError: lammpkeeper' >&2; exit 1");
        let (tx, rx) = mpsc::channel();
        probe(
            Probe {
                id: 4,
                python,
                cancel: Arc::new(AtomicBool::new(false)),
            },
            tx,
        );
        match rx.recv_timeout(Duration::from_secs(30)).unwrap() {
            Msg::Probed { probe: 4, result } => {
                let err = result.unwrap_err();
                assert!(err.contains("invalid_backend_output"), "{err}");
                assert!(
                    err.ends_with("backend stderr:\nModuleNotFoundError: lammpkeeper"),
                    "{err}"
                );
            }
            other => panic!("{other:?}"),
        }
        let python = fake(&dir, "for i in $(seq 1 300); do sleep 0.1; done");
        let cancel = Arc::new(AtomicBool::new(true));
        let (tx, rx) = mpsc::channel();
        let started = Instant::now();
        probe(
            Probe {
                id: 5,
                python,
                cancel,
            },
            tx,
        );
        match rx.recv_timeout(Duration::from_secs(30)).unwrap() {
            Msg::Probed { probe: 5, result } => assert!(result.is_err()),
            other => panic!("{other:?}"),
        }
        assert!(
            started.elapsed() < Duration::from_secs(5),
            "{:?}",
            started.elapsed()
        );
        fs::remove_dir_all(&dir).unwrap();
    }
}
