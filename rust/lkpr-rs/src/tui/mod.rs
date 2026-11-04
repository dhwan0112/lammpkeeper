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
//! exit path (normal quit, Ctrl-C, SIGTERM, SIGHUP, the terminal hanging
//! up, panic).

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
    // A panic on this thread must not leave the terminal in raw mode on the
    // alternate screen: restore first, then report as usual. A worker thread
    // that panics is reported to the reducer by the client (the screen stays
    // up and shows it), so nothing is printed over the screen for it.
    let default_hook = std::panic::take_hook();
    let screen_thread = std::thread::current().id();
    std::panic::set_hook(Box::new(move |info| {
        if std::thread::current().id() == screen_thread {
            restore();
            default_hook(info);
        }
    }));
    let result = event_loop(&mut terminal, &mut app, &tx, &rx);
    restore();
    drop(terminal);
    settle(&mut app, &rx);
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

/// A terminal I/O error as the `terminal_error` failure.
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
        if input_ready(libc::STDIN_FILENO, POLL).map_err(terminal_error)? {
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

/// Wait up to `timeout` for input on the terminal `fd`, reporting a hang-up
/// as an error instead of handing it to crossterm. On a tty whose terminal
/// has gone (window closed, ssh dropped, pty master closed) `poll` reports
/// readable and every `read` returns 0 bytes; crossterm 0.29's inner read
/// loop only leaves on a parsed event or `EWOULDBLOCK`, so one `event::poll`
/// or `event::read` on such a tty spins at 100% CPU and never returns to the
/// loop above, where the SIGHUP flag and the backend are handled. Checking
/// `POLLHUP`/`POLLERR` first keeps crossterm off a hung-up tty; the event
/// that made `fd` readable is then read without blocking.
fn input_ready(fd: libc::c_int, timeout: Duration) -> std::io::Result<bool> {
    let mut fds = libc::pollfd {
        fd,
        events: libc::POLLIN,
        revents: 0,
    };
    let millis = libc::c_int::try_from(timeout.as_millis()).unwrap_or(libc::c_int::MAX);
    // SAFETY: `fds` is one valid pollfd that outlives the call, and 1 is its length.
    let ready = unsafe { libc::poll(&mut fds, 1, millis) };
    if ready < 0 {
        let err = std::io::Error::last_os_error();
        return if err.kind() == std::io::ErrorKind::Interrupted {
            Ok(false)
        } else {
            Err(err)
        };
    }
    if ready == 0 {
        return Ok(false);
    }
    if fds.revents & (libc::POLLHUP | libc::POLLERR | libc::POLLNVAL) != 0 {
        return Err(std::io::Error::new(
            std::io::ErrorKind::ConnectionAborted,
            "the terminal hung up",
        ));
    }
    Ok(true)
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
        KeyCode::Up => Key::Up,
        KeyCode::Down => Key::Down,
        KeyCode::PageUp => Key::PageUp,
        KeyCode::PageDown => Key::PageDown,
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

/// After the terminal is back: whatever is still in flight (SIGTERM, SIGHUP
/// or Ctrl-C while checking, the terminal gone mid-run, a key handled in the
/// leaving iteration) is asked to stop here, whether or not the reducer
/// already did, and the supervisor is waited for, bounded, instead of
/// leaving a backend unattended. A backend that ignores the SIGINT is forced
/// by `supervise` within its grace.
fn settle(app: &mut App, rx: &mpsc::Receiver<Msg>) {
    app.stop();
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
    while app.busy() && Instant::now() < limit {
        match rx.recv_timeout(POLL) {
            Ok(msg) => app.apply(msg),
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(mpsc::RecvTimeoutError::Disconnected) => return,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A fresh (read, write) pipe pair.
    fn pipe() -> (libc::c_int, libc::c_int) {
        let mut fds = [0; 2];
        // SAFETY: `fds` is a valid array of two ints for pipe(2) to fill.
        assert_eq!(unsafe { libc::pipe(fds.as_mut_ptr()) }, 0);
        (fds[0], fds[1])
    }

    #[test]
    /// A pipe with nothing written times out, becomes ready once a byte is
    /// written, and reports the writer's close as a hang-up.
    fn input_ready_distinguishes_data_timeout_and_hang_up() {
        let (reader, writer) = pipe();
        let short = Duration::from_millis(10);
        assert!(!input_ready(reader, short).unwrap(), "nothing written yet");
        // SAFETY: `writer` is the open write end and the buffer is one byte.
        assert_eq!(unsafe { libc::write(writer, b"q".as_ptr().cast(), 1) }, 1);
        assert!(input_ready(reader, short).unwrap(), "a byte is waiting");
        // SAFETY: closing the write end we own.
        assert_eq!(unsafe { libc::close(writer) }, 0);
        // The byte is still readable, but the far end is gone: report the
        // hang-up rather than letting crossterm spin on an endless EOF.
        let err = input_ready(reader, short).unwrap_err();
        assert_eq!(err.kind(), std::io::ErrorKind::ConnectionAborted);
        assert_eq!(err.to_string(), "the terminal hung up");
        // SAFETY: closing the read end we own.
        assert_eq!(unsafe { libc::close(reader) }, 0);
        let err = input_ready(reader, short).unwrap_err();
        assert_eq!(
            err.kind(),
            std::io::ErrorKind::ConnectionAborted,
            "POLLNVAL"
        );
    }
}
