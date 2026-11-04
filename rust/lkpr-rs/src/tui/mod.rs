//! `lkpr-rs tui` (UI-2): an interactive front end for the shared execution
//! contract. Setup → Check → Confirm → Running → Result/Error on one screen,
//! driving the same `exec --capabilities` and `run` backend commands as
//! `doctor` and `thermo-summary` (ADR-0004: Rust owns the terminal and child
//! supervision, Python owns the science).
//!
//! `app` is the pure state machine (keys and client messages in, screen
//! state and side-effect requests out), `view` draws it, `client` runs the
//! backend on threads and reports back over a channel; this module owns the
//! terminal: raw mode, the alternate screen, and their restoration on every
//! exit path (normal quit, Ctrl-C, SIGTERM, panic).

mod app;
mod client;
mod view;

use crate::backend;
use crate::{failure, usage_error, utf8, Failure, Options};
use app::{Action, App, Key, Msg};
use crossterm::event::{self, Event, KeyCode, KeyEventKind, KeyModifiers};
use crossterm::terminal::{
    disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen,
};
use crossterm::{cursor, execute};
use ratatui::backend::CrosstermBackend;
use ratatui::Terminal;
use std::io::{IsTerminal, Write};
use std::sync::mpsc;
use std::time::{Duration, Instant};

/// Longest wait for a key before the screen is refreshed (spinner, elapsed).
const POLL: Duration = Duration::from_millis(50);

/// Run the screen until it is left. Exit status: 0 for a normal quit, 130
/// for Ctrl-C, 1 for SIGTERM; usage error 2 without a usable terminal.
pub fn run(options: &Options) -> Result<u8, Failure> {
    require_terminal()?;
    // The form is prefilled like the CLI selects its environment (--python,
    // then LKPR_PYTHON, never PATH); empty is allowed here and asked for.
    let python = match &options.python {
        Some(python) => python.clone(),
        None => match std::env::var_os("LKPR_PYTHON") {
            Some(value) => utf8(value, "LKPR_PYTHON")?,
            None => String::new(),
        },
    };
    let timeout = options
        .timeout
        .map_or_else(|| app::DEFAULT_TIMEOUT.to_string(), |t| t.to_string());
    let mut app = App::new(python, options.log.clone().unwrap_or_default(), timeout);
    backend::install_sigterm_handler();
    let (tx, rx) = mpsc::channel();
    let mut terminal = enter()?;
    // A panic anywhere must not leave the terminal in raw mode on the
    // alternate screen: restore first, then report as usual.
    let default_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        restore();
        default_hook(info);
    }));
    let result = event_loop(&mut terminal, &mut app, &tx, &rx);
    restore();
    drop(terminal);
    settle(&app, &rx);
    result
}

/// A TUI on a pipe would corrupt the output and a dumb terminal cannot show
/// it: both are usage errors that point at the scriptable command.
fn require_terminal() -> Result<(), Failure> {
    let term = std::env::var_os("TERM");
    let dumb = term.as_deref().is_none_or(|t| t.is_empty() || t == "dumb");
    if !std::io::stdin().is_terminal() || !std::io::stdout().is_terminal() || dumb {
        return Err(usage_error(
            "tui needs an interactive terminal on stdin and stdout (TERM not dumb); \
             use thermo-summary for scripts and pipes",
        ));
    }
    Ok(())
}

fn terminal_error(err: std::io::Error) -> Failure {
    failure(format!("terminal_error: {err}"))
}

/// Raw mode, alternate screen, hidden cursor; undone by [`restore`].
fn enter() -> Result<Terminal<CrosstermBackend<std::io::Stdout>>, Failure> {
    enable_raw_mode().map_err(terminal_error)?;
    let mut out = std::io::stdout();
    if let Err(err) = execute!(out, EnterAlternateScreen, cursor::Hide) {
        let _ = disable_raw_mode();
        return Err(terminal_error(err));
    }
    Terminal::new(CrosstermBackend::new(out)).map_err(|err| {
        restore();
        terminal_error(err)
    })
}

/// Give the terminal back. Safe to call more than once and from the panic
/// hook: every step is independent and failures are ignored.
fn restore() {
    let _ = disable_raw_mode();
    let _ = execute!(std::io::stdout(), LeaveAlternateScreen, cursor::Show);
}

/// Draw, read one key (or time out), apply client messages, perform the
/// reducer's side effects, until the reducer asks to leave.
fn event_loop(
    terminal: &mut Terminal<CrosstermBackend<std::io::Stdout>>,
    app: &mut App,
    tx: &mpsc::Sender<Msg>,
    rx: &mpsc::Receiver<Msg>,
) -> Result<u8, Failure> {
    loop {
        terminal
            .draw(|frame| view::draw(frame, app))
            .map_err(terminal_error)?;
        if backend::terminated() {
            app.apply(Msg::Terminate);
        }
        // Raw mode turns the terminal's Ctrl-C into a key event; a SIGINT sent
        // by another process is treated as the same key, once.
        if backend::take_interrupt() {
            app.apply(Msg::Key(Key::CtrlC));
        }
        if event::poll(POLL).map_err(terminal_error)? {
            if let Event::Key(key) = event::read().map_err(terminal_error)? {
                if key.kind != KeyEventKind::Release {
                    if let Some(key) = translate(key.code, key.modifiers) {
                        app.apply(Msg::Key(key));
                    }
                }
            }
        }
        while let Ok(msg) = rx.try_recv() {
            app.apply(msg);
        }
        app.apply(Msg::Tick);
        for action in app.take_actions() {
            perform(action, app, tx);
        }
        if let Some(code) = app.exit {
            return Ok(code);
        }
    }
}

/// The subset of terminal keys the screens use.
fn translate(code: KeyCode, modifiers: KeyModifiers) -> Option<Key> {
    let control = modifiers.intersects(KeyModifiers::CONTROL | KeyModifiers::ALT);
    Some(match code {
        KeyCode::Char('c') if modifiers.contains(KeyModifiers::CONTROL) => Key::CtrlC,
        KeyCode::Char('u') if modifiers.contains(KeyModifiers::CONTROL) => Key::CtrlU,
        KeyCode::Char(_) if control => return None,
        KeyCode::Char(c) => Key::Char(c),
        KeyCode::Enter => Key::Enter,
        KeyCode::Tab => Key::Tab,
        KeyCode::BackTab => Key::BackTab,
        KeyCode::Backspace => Key::Backspace,
        KeyCode::Esc => Key::Esc,
        KeyCode::F(1) => Key::Help,
        _ => return None,
    })
}

/// Start a probe or a run on its thread; a save is synchronous and its
/// result goes straight back into the reducer.
fn perform(action: Action, app: &mut App, tx: &mpsc::Sender<Msg>) {
    match action {
        Action::Probe(probe) => client::probe(probe, tx.clone()),
        Action::Start(start) => client::start(start, tx.clone()),
        Action::Save(save) => app.apply(Msg::Saved(client::save(&save))),
    }
}

/// After the terminal is back: a backend still in flight (SIGTERM or Ctrl-C
/// while checking) had its cancel flag set by the reducer, so wait, bounded,
/// for the supervisor to finish with it instead of leaving it unattended. A
/// backend that ignores the SIGINT is forced by `supervise` within its grace.
fn settle(app: &App, rx: &mpsc::Receiver<Msg>) {
    if !app.busy() {
        return;
    }
    let _ = writeln!(
        std::io::stderr().lock(),
        "lkpr-rs: waiting for the backend to stop"
    );
    let limit = Instant::now()
        + backend::INTERRUPT_GRACE
        + backend::KILL_GRACE
        + backend::STDOUT_CLOSE_WAIT
        + Duration::from_secs(1);
    while Instant::now() < limit {
        match rx.recv_timeout(POLL) {
            Ok(Msg::Finished { .. } | Msg::Probed { .. }) => return,
            Ok(_) | Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(mpsc::RecvTimeoutError::Disconnected) => return,
        }
    }
}
