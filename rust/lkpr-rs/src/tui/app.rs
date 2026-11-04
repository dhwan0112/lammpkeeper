//! Screen state of the TUI as a reducer: [`App::apply`] turns keys and client
//! messages into the next state and queues side effects ([`Action`]) for the
//! terminal loop to perform. Nothing here touches the terminal or a process,
//! so every transition is unit-testable.
//!
//! Identity rules (ADR-0004, roadmap §8): each run carries a fresh
//! `request_id`; a snapshot is shown only if it echoes the current run's id;
//! editing an input, starting a run or leaving the Result screen for a new
//! run drops the previous result. A forced termination is never shown as
//! `cancelled`: only the backend's own snapshot state is.

use super::client::fresh_request_id;
use crate::{
    check_snapshot, deadline_after, error_text, request, summary, supports, text, OPERATION,
    OPERATION_VERSION, PROTOCOL_VERSION,
};
use serde_json::Value;
use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Instant;

/// Diagnostics lines kept per run: the tail is shown and saved.
pub const DIAGNOSTICS_TAIL: usize = 200;
/// Lifecycle events listed per run; the protocol sends at most four, a
/// backend that keeps sending them is shown in the tail instead.
pub const EVENTS_MAX: usize = 64;
/// Backend timeout prefilled on the form, as `thermo-summary` defaults.
pub const DEFAULT_TIMEOUT: &str = "60";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Screen {
    Setup,
    Check,
    Confirm,
    Running,
    Result,
    Error,
}

/// Editable fields of the Setup screen, in Tab order.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Field {
    Python,
    Log,
    Timeout,
}

impl Field {
    pub const ALL: [Field; 3] = [Field::Python, Field::Log, Field::Timeout];

    pub fn label(self) -> &'static str {
        match self {
            Field::Python => "python",
            Field::Log => "log file",
            Field::Timeout => "timeout s",
        }
    }

    fn next(self) -> Field {
        match self {
            Field::Python => Field::Log,
            Field::Log => Field::Timeout,
            Field::Timeout => Field::Python,
        }
    }

    fn previous(self) -> Field {
        match self {
            Field::Python => Field::Timeout,
            Field::Log => Field::Python,
            Field::Timeout => Field::Log,
        }
    }
}

/// A key after translation from the terminal: only what the screens use.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Key {
    Char(char),
    Enter,
    Tab,
    BackTab,
    Backspace,
    Esc,
    CtrlC,
    CtrlU,
    Help,
    Up,
    Down,
    PageUp,
    PageDown,
}

/// One lifecycle event of the backend's `--events` stream. `elapsed` keeps
/// the backend's digits (see `text`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Event {
    pub sequence: u64,
    pub state: String,
    pub elapsed: String,
}

/// One classified line of backend stderr.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Line {
    Event(Event),
    Diagnostic(String),
}

/// Input of the reducer.
#[derive(Debug)]
pub enum Msg {
    Key(Key),
    Tick,
    /// SIGTERM reached the process: leave with status 1 once restored.
    Terminate,
    /// The capabilities probe `probe` ended.
    Probed {
        probe: u64,
        result: Result<Value, String>,
    },
    /// One stderr line of run `run`.
    Line {
        run: u64,
        line: Line,
    },
    /// Run `run` ended: the parsed snapshot with its raw bytes, or the
    /// failure named as the CLI names it.
    Finished {
        run: u64,
        result: Result<(Value, Vec<u8>), String>,
        interrupted: bool,
    },
    /// The snapshot file was written (message) or not (error).
    Saved(Result<String, String>),
}

/// Side effects the terminal loop performs for the reducer.
#[derive(Debug)]
pub enum Action {
    Probe(Probe),
    Start(Start),
    Save(Save),
}

/// A capabilities probe; `cancel` forwards SIGINT when set.
#[derive(Debug, Clone)]
pub struct Probe {
    pub id: u64,
    pub python: String,
    pub cancel: Arc<AtomicBool>,
}

/// A run to start: the encoded request and the backend timeout.
#[derive(Debug, Clone)]
pub struct Start {
    pub id: u64,
    pub python: String,
    pub body: Vec<u8>,
    pub timeout: f64,
    pub cancel: Arc<AtomicBool>,
}

/// Files to write for `s`: the raw snapshot, and the diagnostics tail when
/// there is one.
#[derive(Debug, Clone)]
pub struct Save {
    pub path: String,
    pub snapshot: Vec<u8>,
    pub diagnostics: String,
}

/// One backend run: Confirm shows it, Running tracks it, Result is bound to it.
#[derive(Debug)]
pub struct Run {
    pub id: u64,
    pub request_id: String,
    pub request: Value,
    pub python: String,
    pub timeout: f64,
    pub started: Option<Instant>,
    pub events: Vec<Event>,
    pub diagnostics: VecDeque<String>,
    pub cancel: Arc<AtomicBool>,
    pub cancel_requested: bool,
}

/// A terminal snapshot of the current run, with the CLI's report of it.
#[derive(Debug)]
pub struct Outcome {
    pub snapshot: Value,
    pub raw: Vec<u8>,
    pub interrupted: bool,
    pub report: String,
}

#[derive(Debug)]
pub struct App {
    pub screen: Screen,
    pub python: String,
    pub log: String,
    pub timeout: String,
    pub focus: Field,
    pub help: bool,
    pub message: Option<String>,
    pub capabilities: Option<Value>,
    pub probe: Option<Probe>,
    pub run: Option<Run>,
    /// True from Start until the matching Finished.
    pub running: bool,
    pub outcome: Option<Outcome>,
    pub error: Option<String>,
    /// File name being edited for `s`.
    pub save: Option<String>,
    /// Set when the loop should leave, with the exit status.
    pub exit: Option<u8>,
    /// Rows scrolled on Confirm, Result and Error; reset on every screen change.
    pub scroll: u16,
    pub ticks: u64,
    actions: Vec<Action>,
    next_id: u64,
    /// Probes and runs started and not yet answered, whatever their id.
    in_flight: usize,
}

/// The timeout field, validated as `--timeout` is: finite, positive, and
/// with a representable supervisor deadline.
pub fn parse_timeout(field: &str) -> Result<f64, String> {
    let t = field.trim();
    let seconds: f64 = t
        .parse()
        .map_err(|_| format!("timeout: must be a number, got {t:?}"))?;
    if !seconds.is_finite() || seconds <= 0.0 {
        return Err(format!("timeout: must be finite and positive, got {t:?}"));
    }
    if deadline_after(seconds).is_none() {
        return Err(format!("timeout: too large, got {t:?}"));
    }
    Ok(seconds)
}

impl App {
    pub fn new(python: String, log: String, timeout: String) -> App {
        App {
            screen: Screen::Setup,
            python,
            log,
            timeout,
            focus: Field::Python,
            help: false,
            message: None,
            capabilities: None,
            probe: None,
            run: None,
            running: false,
            outcome: None,
            error: None,
            save: None,
            exit: None,
            scroll: 0,
            ticks: 0,
            actions: Vec::new(),
            next_id: 0,
            in_flight: 0,
        }
    }

    /// Side effects queued since the last call.
    pub fn take_actions(&mut self) -> Vec<Action> {
        std::mem::take(&mut self.actions)
    }

    /// A probe or a run is still in flight: started and not yet answered,
    /// even once it was cancelled or superseded on screen.
    pub fn busy(&self) -> bool {
        self.in_flight > 0
    }

    pub fn field(&self, field: Field) -> &str {
        match field {
            Field::Python => &self.python,
            Field::Log => &self.log,
            Field::Timeout => &self.timeout,
        }
    }

    fn field_mut(&mut self, field: Field) -> &mut String {
        match field {
            Field::Python => &mut self.python,
            Field::Log => &mut self.log,
            Field::Timeout => &mut self.timeout,
        }
    }

    fn id(&mut self) -> u64 {
        self.next_id += 1;
        self.next_id
    }

    pub fn apply(&mut self, msg: Msg) {
        let before = self.screen;
        self.dispatch(msg);
        if self.screen != before {
            self.scroll = 0;
        }
    }

    fn dispatch(&mut self, msg: Msg) {
        match msg {
            Msg::Tick => self.ticks = self.ticks.wrapping_add(1),
            Msg::Terminate => self.leave(1),
            // Nothing is read once the loop was asked to leave: a key in the
            // same iteration must not start work after everything was stopped.
            Msg::Key(key) => {
                if self.exit.is_none() {
                    self.key(key);
                }
            }
            Msg::Probed { probe, result } => {
                self.in_flight = self.in_flight.saturating_sub(1);
                self.probed(probe, result);
            }
            Msg::Line { run, line } => {
                if self.run.as_ref().is_some_and(|r| r.id == run) {
                    self.line(line);
                }
            }
            Msg::Finished {
                run,
                result,
                interrupted,
            } => {
                self.in_flight = self.in_flight.saturating_sub(1);
                self.finished(run, result, interrupted);
            }
            Msg::Saved(result) => match result {
                Ok(done) => {
                    self.save = None;
                    self.message = Some(done);
                }
                // Keep the name open so it can be corrected.
                Err(problem) => self.message = Some(problem),
            },
        }
    }

    fn key(&mut self, key: Key) {
        if key == Key::CtrlC {
            return self.ctrl_c();
        }
        if self.help {
            if matches!(
                key,
                Key::Help | Key::Esc | Key::Enter | Key::Char('?') | Key::Char('q')
            ) {
                self.help = false;
            }
            return;
        }
        if key == Key::Help {
            self.help = true;
            return;
        }
        if self.save.is_some() {
            return self.save_key(key);
        }
        if matches!(
            self.screen,
            Screen::Confirm | Screen::Result | Screen::Error
        ) {
            let step = match key {
                Key::Up => -1,
                Key::Down => 1,
                Key::PageUp => -10,
                Key::PageDown => 10,
                _ => 0,
            };
            if step != 0 {
                let limit = i64::from(self.scroll_limit());
                self.scroll = (i64::from(self.scroll) + step).clamp(0, limit) as u16;
                return;
            }
        }
        match self.screen {
            Screen::Setup => self.setup_key(key),
            Screen::Check => self.check_key(key),
            Screen::Confirm => self.confirm_key(key),
            Screen::Running => self.running_key(key),
            Screen::Result | Screen::Error => self.done_key(key),
        }
    }

    /// Ctrl-C cancels a run in progress; anywhere else it leaves (130), as
    /// the CLI reports an interruption.
    fn ctrl_c(&mut self) {
        if self.screen == Screen::Running {
            self.cancel();
        } else {
            self.leave(130);
        }
    }

    /// Leave with `code`; anything in flight is asked to stop so the loop
    /// can wait for it once the terminal is restored.
    fn leave(&mut self, code: u8) {
        self.stop();
        self.exit = Some(code);
    }

    /// Ask everything in flight to stop (one SIGINT each, forwarded by the
    /// supervisor). Called on leave and again by the loop before it waits,
    /// so a backend is never left running when the loop ended for another
    /// reason (terminal gone, a key handled in the leaving iteration).
    pub fn stop(&self) {
        if let Some(probe) = &self.probe {
            probe.cancel.store(true, Ordering::SeqCst);
        }
        if let Some(run) = &self.run {
            run.cancel.store(true, Ordering::SeqCst);
        }
    }

    /// Rows the current screen can be scrolled by: an upper estimate of its
    /// body lines (the view clamps again to what it draws).
    fn scroll_limit(&self) -> u16 {
        let lines = match self.screen {
            Screen::Confirm => self.run.as_ref().map_or(0, |run| {
                serde_json::to_string_pretty(&run.request)
                    .map_or(0, |pretty| pretty.lines().count())
                    + 8
            }),
            Screen::Result => self
                .outcome
                .as_ref()
                .map_or(0, |outcome| outcome.report.lines().count() + 8),
            Screen::Error => {
                self.error.as_ref().map_or(0, |error| error.lines().count())
                    + self.run.as_ref().map_or(0, |run| run.diagnostics.len())
                    + 6
            }
            Screen::Setup | Screen::Check | Screen::Running => 0,
        };
        u16::try_from(lines.saturating_sub(1)).unwrap_or(u16::MAX)
    }

    fn setup_key(&mut self, key: Key) {
        match key {
            Key::Tab => self.focus = self.focus.next(),
            Key::BackTab => self.focus = self.focus.previous(),
            Key::Char(c) if !c.is_control() => {
                self.field_mut(self.focus).push(c);
                self.inputs_changed();
            }
            Key::Backspace => {
                self.field_mut(self.focus).pop();
                self.inputs_changed();
            }
            Key::CtrlU => {
                self.field_mut(self.focus).clear();
                self.inputs_changed();
            }
            Key::Enter => self.start_check(),
            // `q` is text on this screen: paths contain it.
            Key::Esc => self.leave(0),
            _ => {}
        }
    }

    /// Any edit invalidates what was checked or computed for the old inputs.
    fn inputs_changed(&mut self) {
        self.message = None;
        self.capabilities = None;
        self.outcome = None;
        self.error = None;
        self.run = None;
    }

    /// Validate the form, then probe the backend (Check screen).
    fn start_check(&mut self) {
        let python = self.python.trim().to_string();
        if python.is_empty() {
            self.focus = Field::Python;
            self.message = Some(
                "python: enter the Python environment path (no PATH guessing; \
                 --python or LKPR_PYTHON prefills it)"
                    .to_string(),
            );
            return;
        }
        if self.log.trim().is_empty() {
            self.focus = Field::Log;
            self.message = Some("log file: enter the LAMMPS log path".to_string());
            return;
        }
        if let Err(problem) = parse_timeout(&self.timeout) {
            self.focus = Field::Timeout;
            self.message = Some(problem);
            return;
        }
        let probe = Probe {
            id: self.id(),
            python,
            cancel: Arc::new(AtomicBool::new(false)),
        };
        self.probe = Some(probe.clone());
        self.actions.push(Action::Probe(probe));
        self.in_flight += 1;
        self.message = None;
        self.screen = Screen::Check;
    }

    fn check_key(&mut self, key: Key) {
        match key {
            Key::Esc | Key::Char('q') => {
                if let Some(probe) = self.probe.take() {
                    probe.cancel.store(true, Ordering::SeqCst);
                }
                self.message = Some("check cancelled".to_string());
                self.screen = Screen::Setup;
            }
            Key::Char('?') => self.help = true,
            _ => {}
        }
    }

    fn probed(&mut self, id: u64, result: Result<Value, String>) {
        // A cancelled or superseded probe answers to nobody.
        let Some(probe) = self.probe.as_ref().filter(|p| p.id == id) else {
            return;
        };
        let python = probe.python.clone();
        self.probe = None;
        if self.screen != Screen::Check {
            return;
        }
        let caps = match result {
            Ok(caps) => caps,
            Err(problem) => return self.fail(problem),
        };
        let succeeded = caps["status"] == "succeeded";
        let (protocol_ok, operation_ok) = supports(&caps);
        if !(succeeded && protocol_ok && operation_ok) {
            let why = if succeeded {
                format!(
                    "protocol v{PROTOCOL_VERSION} {}, {OPERATION} v{OPERATION_VERSION} {}",
                    supported(protocol_ok),
                    supported(operation_ok)
                )
            } else {
                error_text(&caps["error"])
            };
            return self.fail(format!(
                "incompatible_backend: {python:?} does not offer protocol v{PROTOCOL_VERSION} \
                 with {OPERATION} v{OPERATION_VERSION} ({why})"
            ));
        }
        let timeout = match parse_timeout(&self.timeout) {
            Ok(timeout) => timeout,
            Err(problem) => return self.fail(problem),
        };
        let request_id = fresh_request_id();
        let request = request(&request_id, self.log.trim());
        self.run = Some(Run {
            id: self.id(),
            request_id,
            request,
            python,
            timeout,
            started: None,
            events: Vec::new(),
            diagnostics: VecDeque::new(),
            cancel: Arc::new(AtomicBool::new(false)),
            cancel_requested: false,
        });
        self.capabilities = Some(caps);
        self.outcome = None;
        self.screen = Screen::Confirm;
    }

    fn fail(&mut self, problem: String) {
        self.error = Some(problem);
        self.screen = Screen::Error;
    }

    fn confirm_key(&mut self, key: Key) {
        match key {
            Key::Enter => self.start_run(),
            Key::Esc | Key::Char('q') => {
                self.run = None;
                self.screen = Screen::Setup;
            }
            Key::Char('?') => self.help = true,
            _ => {}
        }
    }

    fn start_run(&mut self) {
        let Some(run) = self.run.as_mut() else {
            self.screen = Screen::Setup;
            return;
        };
        let body = match serde_json::to_vec(&run.request) {
            Ok(body) => body,
            Err(err) => return self.fail(format!("cannot encode request: {err}")),
        };
        run.started = Some(Instant::now());
        let start = Start {
            id: run.id,
            python: run.python.clone(),
            body,
            timeout: run.timeout,
            cancel: Arc::clone(&run.cancel),
        };
        self.actions.push(Action::Start(start));
        self.in_flight += 1;
        self.running = true;
        self.outcome = None;
        self.message = None;
        self.screen = Screen::Running;
    }

    fn running_key(&mut self, key: Key) {
        match key {
            Key::Char('c') => self.cancel(),
            Key::Esc | Key::Char('q') => {
                self.message = Some("a run is in progress: press c to cancel it first".to_string());
            }
            Key::Char('?') => self.help = true,
            _ => {}
        }
    }

    /// Ask the supervisor to forward one SIGINT; the screen then waits for
    /// the backend's own final snapshot (or the supervisor's forced outcome).
    fn cancel(&mut self) {
        if let Some(run) = self.run.as_mut() {
            run.cancel.store(true, Ordering::SeqCst);
            run.cancel_requested = true;
            self.message = Some(
                "cancel requested: SIGINT goes to the backend; waiting for its final snapshot"
                    .to_string(),
            );
        }
    }

    fn line(&mut self, line: Line) {
        let Some(run) = self.run.as_mut() else {
            return;
        };
        match line {
            Line::Event(event) if run.events.len() < EVENTS_MAX => run.events.push(event),
            Line::Event(event) => push_tail(
                &mut run.diagnostics,
                format!(
                    "event {} {} {} (beyond the {EVENTS_MAX} listed)",
                    event.sequence, event.state, event.elapsed
                ),
            ),
            Line::Diagnostic(text) => push_tail(&mut run.diagnostics, text),
        }
    }

    fn finished(&mut self, id: u64, result: Result<(Value, Vec<u8>), String>, interrupted: bool) {
        let Some(run) = self.run.as_ref().filter(|r| r.id == id) else {
            return;
        };
        self.running = false;
        if self.screen != Screen::Running {
            return;
        }
        let (snapshot, raw) = match result {
            Ok(done) => done,
            Err(problem) => return self.fail(problem),
        };
        if let Err(problem) = check_snapshot(&snapshot) {
            return self.fail(problem.message);
        }
        if snapshot["request_id"] != run.request_id.as_str() {
            return self.fail(format!(
                "stale_snapshot: the backend answered for request_id {} but this run is {}",
                text(&snapshot["request_id"]),
                run.request_id
            ));
        }
        let report = summary(&snapshot).0;
        self.outcome = Some(Outcome {
            snapshot,
            raw,
            interrupted,
            report,
        });
        if interrupted {
            self.message = Some(
                "cancel was requested; the state shown is the one the backend reported".to_string(),
            );
        }
        self.screen = Screen::Result;
    }

    fn done_key(&mut self, key: Key) {
        match key {
            Key::Char('s') if self.screen == Screen::Result => {
                self.save = Some(self.default_save_name());
                self.message = None;
            }
            Key::Enter | Key::Esc => {
                self.message = None;
                self.screen = Screen::Setup;
            }
            Key::Char('q') => self.leave(0),
            Key::Char('?') => self.help = true,
            _ => {}
        }
    }

    /// `<log file name>.snapshot.json` in the working directory.
    fn default_save_name(&self) -> String {
        let name = std::path::Path::new(self.log.trim())
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .filter(|n| !n.is_empty())
            .unwrap_or_else(|| "lkpr".to_string());
        format!("{name}.snapshot.json")
    }

    fn save_key(&mut self, key: Key) {
        let Some(name) = self.save.as_mut() else {
            return;
        };
        match key {
            Key::Char(c) if !c.is_control() => name.push(c),
            Key::Backspace => {
                name.pop();
            }
            Key::CtrlU => name.clear(),
            Key::Esc => self.save = None,
            Key::Enter => {
                let path = name.trim().to_string();
                if path.is_empty() {
                    self.message = Some("enter a file name, or Esc".to_string());
                    return;
                }
                let Some(outcome) = &self.outcome else {
                    self.save = None;
                    return;
                };
                let diagnostics = self.run.as_ref().map_or_else(String::new, |run| {
                    run.diagnostics
                        .iter()
                        .map(|line| format!("{line}\n"))
                        .collect()
                });
                self.actions.push(Action::Save(Save {
                    path,
                    snapshot: outcome.raw.clone(),
                    diagnostics,
                }));
            }
            _ => {}
        }
    }
}

fn supported(ok: bool) -> &'static str {
    if ok {
        "supported"
    } else {
        "NOT supported"
    }
}

/// Append to a tail that keeps the newest [`DIAGNOSTICS_TAIL`] lines.
fn push_tail(tail: &mut VecDeque<String>, text: String) {
    if tail.len() == DIAGNOSTICS_TAIL {
        tail.pop_front();
    }
    tail.push_back(text);
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn fresh() -> App {
        App::new("/py".to_string(), "run.log".to_string(), "5".to_string())
    }

    fn keys(app: &mut App, list: &[Key]) {
        for key in list {
            app.apply(Msg::Key(*key));
        }
    }

    fn caps() -> Value {
        json!({"status": "succeeded", "result": {"protocol_versions": [1],
            "operations": {"thermo.summary": {"versions": [1]}}}})
    }

    /// Enter on Setup starts a probe; answering it reaches Confirm with a
    /// fresh run. Returns the probe id.
    fn to_confirm(app: &mut App) -> u64 {
        keys(app, &[Key::Enter]);
        assert_eq!(app.screen, Screen::Check);
        let actions = app.take_actions();
        let Some(Action::Probe(probe)) = actions.first() else {
            panic!("no probe: {actions:?}");
        };
        assert_eq!(probe.python, "/py");
        let id = probe.id;
        app.apply(Msg::Probed {
            probe: id,
            result: Ok(caps()),
        });
        assert_eq!(app.screen, Screen::Confirm, "{:?}", app.error);
        id
    }

    /// Enter on Confirm starts the run; returns its id and the Start action.
    fn to_running(app: &mut App) -> (u64, Start) {
        keys(app, &[Key::Enter]);
        assert_eq!(app.screen, Screen::Running);
        let mut actions = app.take_actions();
        let Some(Action::Start(start)) = actions.pop() else {
            panic!("no start: {actions:?}");
        };
        (start.id, start)
    }

    fn snapshot(request_id: &str, state: &str) -> Value {
        json!({"job_schema_version": 1, "request_id": request_id, "state": state,
            "elapsed_seconds": 0.5, "cleanup": {"status": "complete"},
            "backend_response": {"result": {"sample_count": 2, "unit_system": "metal",
                "units": {"Temp": "K"},
                "statistics": {"Temp": {"min": 1, "max": 2, "mean": 1.5, "std": 0.5}}}}})
    }

    #[test]
    /// The whole happy path: Setup → Check → Confirm → Running → Result, with
    /// the request carrying a fresh id that the snapshot must echo.
    fn happy_path_binds_the_result_to_the_request_id() {
        let mut app = fresh();
        to_confirm(&mut app);
        let request_id = app.run.as_ref().unwrap().request_id.clone();
        assert_eq!(request_id.len(), 36);
        assert_eq!(app.run.as_ref().unwrap().request["request_id"], request_id);
        assert_eq!(app.run.as_ref().unwrap().request["input"]["log"], "run.log");
        let (id, start) = to_running(&mut app);
        assert!(app.running && app.busy());
        assert_eq!(start.timeout, 5.0);
        assert!(start.body.starts_with(b"{\"protocol_version\":1"));
        app.apply(Msg::Line {
            run: id,
            line: Line::Event(Event {
                sequence: 1,
                state: "created".into(),
                elapsed: "0.0".into(),
            }),
        });
        app.apply(Msg::Line {
            run: id,
            line: Line::Diagnostic("note".into()),
        });
        let raw = b"{\"raw\": true}".to_vec();
        app.apply(Msg::Finished {
            run: id,
            result: Ok((snapshot(&request_id, "succeeded"), raw.clone())),
            interrupted: false,
        });
        assert_eq!(app.screen, Screen::Result, "{:?}", app.error);
        assert!(!app.running);
        let outcome = app.outcome.as_ref().unwrap();
        assert_eq!(outcome.raw, raw);
        assert!(outcome
            .report
            .starts_with("thermo.summary  succeeded  (2 samples"));
        assert_eq!(app.run.as_ref().unwrap().events.len(), 1);
        assert_eq!(app.run.as_ref().unwrap().diagnostics.len(), 1);
    }

    #[test]
    /// A snapshot for another request id, a non-snapshot object and a client
    /// failure all land on Error, never on Result.
    fn stale_or_invalid_snapshots_are_errors() {
        for (result, needle) in [
            (
                Ok((snapshot("other", "succeeded"), Vec::new())),
                "stale_snapshot",
            ),
            (
                Ok((json!({"status": "succeeded"}), Vec::new())),
                "job_schema_version",
            ),
            (
                Err("supervisor_unresponsive: x".to_string()),
                "supervisor_unresponsive",
            ),
        ] {
            let mut app = fresh();
            to_confirm(&mut app);
            let (id, _) = to_running(&mut app);
            app.apply(Msg::Finished {
                run: id,
                result,
                interrupted: false,
            });
            assert_eq!(app.screen, Screen::Error);
            assert!(app.outcome.is_none());
            assert!(
                app.error.as_deref().unwrap().contains(needle),
                "{:?}",
                app.error
            );
            // Error goes back to Setup; q leaves with 0.
            keys(&mut app, &[Key::Enter]);
            assert_eq!(app.screen, Screen::Setup);
        }
    }

    #[test]
    /// Messages of an old run or probe are ignored once superseded.
    fn messages_of_superseded_runs_and_probes_are_ignored() {
        let mut app = fresh();
        let probe = to_confirm(&mut app);
        let (id, _) = to_running(&mut app);
        // Late answer of the finished probe: nothing changes.
        app.apply(Msg::Probed {
            probe,
            result: Err("late".into()),
        });
        assert_eq!(app.screen, Screen::Running);
        app.apply(Msg::Line {
            run: id + 100,
            line: Line::Diagnostic("foreign".into()),
        });
        assert!(app.run.as_ref().unwrap().diagnostics.is_empty());
        app.apply(Msg::Finished {
            run: id + 100,
            result: Err("foreign".into()),
            interrupted: false,
        });
        assert_eq!(app.screen, Screen::Running);
        assert!(app.running);
    }

    #[test]
    /// `c` and Ctrl-C while running set the run's cancel flag once and keep
    /// waiting; the state shown afterwards is the backend's, so a forced
    /// outcome is an error and a `cancelled` snapshot is a result.
    fn cancel_sets_the_flag_and_shows_what_the_backend_reports() {
        let mut app = fresh();
        to_confirm(&mut app);
        let (id, start) = to_running(&mut app);
        keys(&mut app, &[Key::Char('q')]);
        assert_eq!(app.screen, Screen::Running);
        assert!(app.message.as_deref().unwrap().contains("press c"));
        assert!(!start.cancel.load(Ordering::SeqCst));
        keys(&mut app, &[Key::CtrlC]);
        assert!(start.cancel.load(Ordering::SeqCst));
        assert!(app.run.as_ref().unwrap().cancel_requested);
        assert!(app.exit.is_none());
        keys(&mut app, &[Key::Char('c')]);
        assert_eq!(app.screen, Screen::Running);
        let request_id = app.run.as_ref().unwrap().request_id.clone();
        app.apply(Msg::Finished {
            run: id,
            result: Ok((snapshot(&request_id, "cancelled"), Vec::new())),
            interrupted: true,
        });
        assert_eq!(app.screen, Screen::Result);
        assert!(app.outcome.as_ref().unwrap().interrupted);
        assert!(app
            .outcome
            .as_ref()
            .unwrap()
            .report
            .starts_with("thermo.summary  cancelled"));

        let mut app = fresh();
        to_confirm(&mut app);
        let (id, _) = to_running(&mut app);
        keys(&mut app, &[Key::Char('c')]);
        app.apply(Msg::Finished {
            run: id,
            result: Err("supervisor_unresponsive: after Ctrl-C".into()),
            interrupted: true,
        });
        assert_eq!(app.screen, Screen::Error);
        assert!(!app.error.as_deref().unwrap().contains("cancelled"));
    }

    #[test]
    /// Form validation names the field and does not start a probe.
    fn setup_validates_before_checking() {
        let mut app = App::new(String::new(), String::new(), "x".to_string());
        keys(&mut app, &[Key::Enter]);
        assert_eq!(app.screen, Screen::Setup);
        assert!(app.message.as_deref().unwrap().starts_with("python:"));
        assert!(app.take_actions().is_empty());
        keys(&mut app, &[Key::Char('/'), Key::Char('p'), Key::Enter]);
        assert!(app.message.as_deref().unwrap().starts_with("log file:"));
        assert_eq!(app.focus, Field::Log);
        keys(&mut app, &[Key::Char('l'), Key::Enter]);
        assert!(app.message.as_deref().unwrap().starts_with("timeout:"));
        assert_eq!(app.focus, Field::Timeout);
        for bad in ["0", "-1", "nan", "inf", "1e300", ""] {
            keys(&mut app, &[Key::CtrlU]);
            for c in bad.chars() {
                keys(&mut app, &[Key::Char(c)]);
            }
            keys(&mut app, &[Key::Enter]);
            assert_eq!(app.screen, Screen::Setup, "{bad:?}");
        }
        keys(&mut app, &[Key::CtrlU, Key::Char('3'), Key::Enter]);
        assert_eq!(app.screen, Screen::Check);
        assert_eq!(app.take_actions().len(), 1);
    }

    #[test]
    /// Tab order, Backspace, Ctrl-U and the rule that an edit drops results.
    fn editing_moves_focus_and_drops_old_results() {
        let mut app = fresh();
        assert_eq!(app.focus, Field::Python);
        keys(&mut app, &[Key::Tab]);
        assert_eq!(app.focus, Field::Log);
        keys(&mut app, &[Key::Tab, Key::Tab]);
        assert_eq!(app.focus, Field::Python);
        keys(&mut app, &[Key::BackTab]);
        assert_eq!(app.focus, Field::Timeout);
        keys(&mut app, &[Key::Backspace, Key::Char('7')]);
        assert_eq!(app.timeout, "7");
        to_confirm(&mut app);
        let (id, _) = to_running(&mut app);
        let request_id = app.run.as_ref().unwrap().request_id.clone();
        app.apply(Msg::Finished {
            run: id,
            result: Ok((snapshot(&request_id, "succeeded"), Vec::new())),
            interrupted: false,
        });
        keys(&mut app, &[Key::Enter]);
        assert_eq!(app.screen, Screen::Setup);
        assert!(app.outcome.is_some());
        keys(&mut app, &[Key::Char('q')]);
        assert_eq!(app.timeout, "7q", "q is text on Setup");
        assert!(app.outcome.is_none() && app.capabilities.is_none() && app.run.is_none());
        assert!(app.exit.is_none());
    }

    #[test]
    /// An incompatible or failed probe is an error; Esc during the check
    /// cancels the probe and its late answer is dropped.
    fn probe_failures_and_cancellation() {
        let mut app = fresh();
        keys(&mut app, &[Key::Enter]);
        let actions = app.take_actions();
        let Some(Action::Probe(probe)) = actions.first() else {
            panic!("{actions:?}");
        };
        let bad = json!({"status": "succeeded", "result": {"protocol_versions": [2],
            "operations": {}}});
        app.apply(Msg::Probed {
            probe: probe.id,
            result: Ok(bad),
        });
        assert_eq!(app.screen, Screen::Error);
        let error = app.error.clone().unwrap();
        assert!(
            error.contains("incompatible_backend") && error.contains("NOT supported"),
            "{error}"
        );
        keys(&mut app, &[Key::Esc, Key::Enter]);
        let actions = app.take_actions();
        let Some(Action::Probe(probe)) = actions.first() else {
            panic!("{actions:?}");
        };
        let probe = probe.clone();
        keys(&mut app, &[Key::Esc]);
        assert_eq!(app.screen, Screen::Setup);
        assert!(probe.cancel.load(Ordering::SeqCst));
        app.apply(Msg::Probed {
            probe: probe.id,
            result: Ok(caps()),
        });
        assert_eq!(app.screen, Screen::Setup);
        assert!(app.run.is_none());
    }

    #[test]
    /// `s` opens the save dialog with a name derived from the log, Enter
    /// queues the files, and a write error keeps the dialog open.
    fn save_dialog_queues_the_snapshot_and_diagnostics() {
        let mut app = App::new("/py".into(), "/data/a b.log".into(), "5".into());
        to_confirm(&mut app);
        let (id, _) = to_running(&mut app);
        app.apply(Msg::Line {
            run: id,
            line: Line::Diagnostic("warn".into()),
        });
        let request_id = app.run.as_ref().unwrap().request_id.clone();
        app.apply(Msg::Finished {
            run: id,
            result: Ok((snapshot(&request_id, "succeeded"), b"{}".to_vec())),
            interrupted: false,
        });
        keys(&mut app, &[Key::Char('s')]);
        assert_eq!(app.save.as_deref(), Some("a b.log.snapshot.json"));
        keys(&mut app, &[Key::CtrlU, Key::Enter]);
        assert!(app.message.as_deref().unwrap().contains("file name"));
        keys(
            &mut app,
            &[Key::Char('o'), Key::Char('u'), Key::Char('t'), Key::Enter],
        );
        let actions = app.take_actions();
        let Some(Action::Save(save)) = actions.first() else {
            panic!("{actions:?}");
        };
        assert_eq!(save.path, "out");
        assert_eq!(save.snapshot, b"{}");
        assert_eq!(save.diagnostics, "warn\n");
        app.apply(Msg::Saved(Err("cannot create out: exists".into())));
        assert!(app.save.is_some());
        app.apply(Msg::Saved(Ok("saved out".into())));
        assert!(app.save.is_none());
        assert_eq!(app.message.as_deref(), Some("saved out"));
        keys(&mut app, &[Key::Char('s'), Key::Esc]);
        assert!(app.save.is_none());
        assert_eq!(app.screen, Screen::Result);
    }

    #[test]
    /// Leaving: Esc on Setup is 0, Ctrl-C outside a run is 130, SIGTERM is 1;
    /// a probe in flight is asked to stop.
    fn exit_codes_and_in_flight_cancellation() {
        let mut app = fresh();
        keys(&mut app, &[Key::Esc]);
        assert_eq!(app.exit, Some(0));

        let mut app = fresh();
        keys(&mut app, &[Key::Enter]);
        let actions = app.take_actions();
        let Some(Action::Probe(probe)) = actions.first() else {
            panic!("{actions:?}");
        };
        let probe = probe.clone();
        keys(&mut app, &[Key::CtrlC]);
        assert_eq!(app.exit, Some(130));
        assert!(probe.cancel.load(Ordering::SeqCst));
        assert!(app.busy());

        let mut app = fresh();
        app.apply(Msg::Terminate);
        assert_eq!(app.exit, Some(1));
    }

    #[test]
    /// Esc on Check cancels the probe but it stays counted until it answers;
    /// `stop` reaches a run even when nothing asked to leave; once the loop
    /// is leaving, keys do nothing.
    fn in_flight_work_is_counted_until_answered_and_keys_stop_at_exit() {
        let mut app = fresh();
        keys(&mut app, &[Key::Enter]);
        let actions = app.take_actions();
        let Some(Action::Probe(probe)) = actions.first() else {
            panic!("{actions:?}");
        };
        let probe = probe.clone();
        keys(&mut app, &[Key::Esc]);
        assert_eq!(app.screen, Screen::Setup);
        assert!(probe.cancel.load(Ordering::SeqCst));
        assert!(
            app.busy(),
            "a cancelled probe still has a child to wait for"
        );
        app.apply(Msg::Probed {
            probe: probe.id,
            result: Err("cancelled".to_string()),
        });
        assert!(!app.busy());
        assert_eq!(app.screen, Screen::Setup);

        let mut app = fresh();
        to_confirm(&mut app);
        let (id, start) = to_running(&mut app);
        app.stop();
        assert!(start.cancel.load(Ordering::SeqCst));
        app.apply(Msg::Terminate);
        keys(&mut app, &[Key::Enter, Key::Char('q')]);
        assert_eq!(app.exit, Some(1));
        assert!(app.take_actions().is_empty());
        assert!(app.busy());
        app.apply(Msg::Finished {
            run: id,
            result: Err("stopped".to_string()),
            interrupted: true,
        });
        assert!(!app.busy());
    }

    #[test]
    /// Up/Down and PageUp/PageDown scroll Confirm, Result and Error within
    /// their body, and a screen change resets the offset.
    fn scrolling_is_bounded_and_reset_per_screen() {
        let mut app = fresh();
        to_confirm(&mut app);
        keys(&mut app, &[Key::Up]);
        assert_eq!(app.scroll, 0);
        keys(&mut app, &[Key::Down, Key::Down, Key::PageDown]);
        assert!(app.scroll >= 2 && app.scroll <= 30, "{}", app.scroll);
        let (id, _) = to_running(&mut app);
        assert_eq!(app.scroll, 0);
        keys(&mut app, &[Key::Down]);
        assert_eq!(app.scroll, 0, "Running does not scroll");
        let request_id = app.run.as_ref().unwrap().request_id.clone();
        app.apply(Msg::Finished {
            run: id,
            result: Ok((snapshot(&request_id, "succeeded"), Vec::new())),
            interrupted: false,
        });
        assert_eq!(app.screen, Screen::Result);
        keys(&mut app, &[Key::PageDown, Key::PageDown, Key::PageDown]);
        let limit = app.scroll_limit();
        assert_eq!(app.scroll, limit);
        keys(
            &mut app,
            &[Key::PageUp, Key::PageUp, Key::PageUp, Key::PageUp],
        );
        assert_eq!(app.scroll, 0);
    }

    #[test]
    /// More events than the list holds go to the bounded tail as text.
    fn surplus_events_go_to_the_tail() {
        let mut app = fresh();
        to_confirm(&mut app);
        let (id, _) = to_running(&mut app);
        for i in 0..(EVENTS_MAX + 3) {
            app.apply(Msg::Line {
                run: id,
                line: Line::Event(Event {
                    sequence: i as u64,
                    state: "running".to_string(),
                    elapsed: "0.1".to_string(),
                }),
            });
        }
        let run = app.run.as_ref().unwrap();
        assert_eq!(run.events.len(), EVENTS_MAX);
        assert_eq!(run.diagnostics.len(), 3);
        assert!(run.diagnostics[0].starts_with("event 64 running 0.1"));
    }

    #[test]
    /// Help opens from any screen except as typed text on Setup, and closes.
    fn help_overlay() {
        let mut app = fresh();
        keys(&mut app, &[Key::Char('?')]);
        assert!(!app.help);
        assert!(app.python.ends_with('?'));
        keys(&mut app, &[Key::Help]);
        assert!(app.help);
        keys(&mut app, &[Key::Tab]);
        assert_eq!(app.focus, Field::Python, "keys go to the overlay");
        keys(&mut app, &[Key::Esc]);
        assert!(!app.help && app.exit.is_none());
    }

    #[test]
    /// The diagnostics tail is bounded.
    fn diagnostics_tail_is_bounded() {
        let mut app = fresh();
        to_confirm(&mut app);
        let (id, _) = to_running(&mut app);
        for i in 0..(DIAGNOSTICS_TAIL + 5) {
            app.apply(Msg::Line {
                run: id,
                line: Line::Diagnostic(i.to_string()),
            });
        }
        let tail = &app.run.as_ref().unwrap().diagnostics;
        assert_eq!(tail.len(), DIAGNOSTICS_TAIL);
        assert_eq!(tail.front().map(String::as_str), Some("5"));
    }
}
