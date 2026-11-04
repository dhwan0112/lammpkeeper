//! Draw the TUI state. Rendering reads `App` only; every backend string it
//! shows has passed `visible`/`text` already, so nothing here can carry a
//! control sequence onto the screen.

use super::app::{App, Field, Screen};
use crate::{text, OPERATION, OPERATION_VERSION, PROTOCOL_VERSION};
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Modifier, Style};
use ratatui::text::{Line, Span, Text};
use ratatui::widgets::{Block, Borders, Clear, Paragraph, Wrap};
use ratatui::Frame;

/// Smallest screen that is drawn; below it only a notice is shown.
pub const MIN_WIDTH: u16 = 80;
pub const MIN_HEIGHT: u16 = 24;
const SPINNER: [char; 4] = ['|', '/', '-', '\\'];

/// Draw the whole frame: title, the current screen body, footer, and the
/// help overlay when open; a too-small terminal gets a notice instead.
pub fn draw(frame: &mut Frame, app: &App) {
    let area = frame.area();
    if area.width < MIN_WIDTH || area.height < MIN_HEIGHT {
        let notice = format!(
            "lkpr-rs tui needs a terminal of at least {MIN_WIDTH}x{MIN_HEIGHT} \
             (this one is {}x{}). Enlarge the window to continue, or press Ctrl-C \
             to leave (during a run the first Ctrl-C only cancels it).",
            area.width, area.height
        );
        frame.render_widget(Paragraph::new(notice).wrap(Wrap { trim: false }), area);
        return;
    }
    let [header, body, footer] = Layout::vertical([
        Constraint::Length(1),
        Constraint::Min(1),
        Constraint::Length(2),
    ])
    .areas(area);
    frame.render_widget(
        Paragraph::new(title(app)).style(Style::new().add_modifier(Modifier::REVERSED)),
        header,
    );
    let block = Block::default()
        .borders(Borders::ALL)
        .title(format!(" {} ", screen_name(app.screen)));
    let inner = block.inner(body);
    frame.render_widget(block, body);
    let width = inner.width as usize;
    let lines = match app.screen {
        Screen::Setup => setup(app),
        Screen::Check => check(app),
        Screen::Confirm => confirm(app),
        Screen::Running => running(app, inner.height as usize, width),
        Screen::Result => result(app),
        Screen::Error => error(app, inner.height as usize, width),
    };
    // Confirm, Result and Error can be longer than the body; Up/Down move
    // them (the reducer bounds the offset by an estimate, this is the truth).
    let scroll = app.scroll.min(lines.len().saturating_sub(1) as u16);
    frame.render_widget(
        Paragraph::new(Text::from(lines))
            .wrap(Wrap { trim: false })
            .scroll((scroll, 0)),
        inner,
    );
    frame.render_widget(Paragraph::new(footer_text(app)), footer);
    if let Some(name) = &app.save {
        dialog(
            frame,
            area,
            "save snapshot as (Enter writes, Esc closes)",
            name,
        );
    }
    if app.help {
        help(frame, area);
    }
}

/// Title line naming the operation, protocol and current screen.
fn title(app: &App) -> String {
    format!(
        " lkpr-rs tui  {OPERATION} v{OPERATION_VERSION}  protocol v{PROTOCOL_VERSION}  {}",
        match app.screen {
            Screen::Setup => "1/5 setup",
            Screen::Check => "2/5 check",
            Screen::Confirm => "3/5 confirm",
            Screen::Running => "4/5 running",
            Screen::Result => "5/5 result",
            Screen::Error => "error",
        }
    )
}

/// Display name of a screen.
fn screen_name(screen: Screen) -> &'static str {
    match screen {
        Screen::Setup => "Setup",
        Screen::Check => "Check",
        Screen::Confirm => "Confirm",
        Screen::Running => "Running",
        Screen::Result => "Result",
        Screen::Error => "Error",
    }
}

/// Spinner glyph for the current tick.
fn spinner(app: &App) -> char {
    SPINNER[(app.ticks / 3) as usize % SPINNER.len()]
}

/// An unstyled line.
fn plain(text: impl Into<String>) -> Line<'static> {
    Line::from(text.into())
}

/// A bold line.
fn bold(text: impl Into<String>) -> Line<'static> {
    Line::from(Span::styled(
        text.into(),
        Style::new().add_modifier(Modifier::BOLD),
    ))
}

/// Body of the Setup screen: the three fields with the focused one marked.
fn setup(app: &App) -> Vec<Line<'static>> {
    let mut lines = vec![
        plain("Fill in the run, then press Enter to check the backend."),
        plain(""),
    ];
    for field in Field::ALL {
        let focused = app.focus == field;
        let mut spans = vec![Span::raw(format!(
            "{:<11}{}",
            field.label(),
            if focused { "> " } else { "  " }
        ))];
        let style = if focused {
            Style::new().add_modifier(Modifier::BOLD)
        } else {
            Style::new()
        };
        spans.push(Span::styled(app.field(field).to_string(), style));
        if focused {
            spans.push(Span::styled(
                " ",
                Style::new().add_modifier(Modifier::REVERSED),
            ));
        }
        lines.push(Line::from(spans));
    }
    lines.push(plain(format!(
        "{:<11}  {OPERATION} v{OPERATION_VERSION} (the operation the backend publishes)",
        "operation"
    )));
    lines.push(plain(""));
    lines.push(plain(
        "python is the environment with lammpkeeper installed; it is never guessed from PATH.",
    ));
    lines.push(plain(
        "--python, --log, --timeout and LKPR_PYTHON prefill the fields. Ctrl-U clears a field.",
    ));
    if let Some(outcome) = &app.outcome {
        lines.push(plain(""));
        lines.push(plain(
            "Last result (editing a field or starting a run drops it):",
        ));
        if let Some(first) = outcome.report.lines().next() {
            lines.push(plain(format!("  {first}")));
        }
    }
    lines
}

/// Body of the Check screen while the capabilities probe runs.
fn check(app: &App) -> Vec<Line<'static>> {
    let python = app
        .probe
        .as_ref()
        .map_or_else(|| app.python.clone(), |p| p.python.clone());
    vec![
        plain(format!(
            "{} checking {python} -m lammpkeeper exec --capabilities",
            spinner(app)
        )),
        plain(""),
        plain("Esc cancels the check and returns to Setup."),
    ]
}

/// Body of the Confirm screen: backend provenance and support summary.
fn confirm(app: &App) -> Vec<Line<'static>> {
    let mut lines = Vec::new();
    if let Some(caps) = &app.capabilities {
        let p = &caps["provenance"];
        lines.push(plain(format!(
            "backend     lammpkeeper {}, Python {} ({}), NumPy {}",
            text(&p["package_version"]),
            text(&p["python_version"]),
            text(&p["python_executable"]),
            text(&p["numpy_version"])
        )));
        lines.push(plain(format!(
            "protocol    v{PROTOCOL_VERSION} supported; {OPERATION} v{OPERATION_VERSION} supported"
        )));
    }
    if let Some(run) = &app.run {
        lines.push(plain(format!("request_id  {}", run.request_id)));
        lines.push(plain(format!(
            "command     {} -m lammpkeeper run --request - --python {} --timeout {} --events",
            run.python, run.python, run.timeout
        )));
        lines.push(plain(""));
        lines.push(bold("request (sent on stdin):"));
        let pretty = serde_json::to_string_pretty(&run.request).unwrap_or_default();
        lines.extend(pretty.lines().map(|l| plain(format!("  {l}"))));
    }
    lines.push(plain(""));
    lines.push(plain("Enter starts the run; Esc returns to Setup."));
    lines
}

/// One screen row for `text`: cut to `width` cells (by chars, which is what
/// the terminals in scope use for one cell) with a trailing ellipsis, so
/// the row accounting of the tails stays exact however long a line is.
fn clip(text: &str, width: usize) -> String {
    if text.chars().count() <= width {
        return text.to_string();
    }
    let mut cut: String = text.chars().take(width.saturating_sub(1)).collect();
    cut.push('\u{2026}');
    cut
}

/// Body of the Running screen: elapsed time, listed events and the
/// diagnostics tail that fits the area.
fn running(app: &App, height: usize, width: usize) -> Vec<Line<'static>> {
    let Some(run) = &app.run else {
        return vec![plain("no run")];
    };
    let elapsed = run
        .started
        .map_or(0.0, |started| started.elapsed().as_secs_f64());
    let mut lines = vec![
        plain(format!("{} request_id {}", spinner(app), run.request_id)),
        plain(format!(
            "  elapsed {elapsed:.1} s   backend timeout {} s{}",
            run.timeout,
            if run.cancel_requested {
                "   CANCEL REQUESTED"
            } else {
                ""
            }
        )),
        plain(""),
        bold("events (state transitions reported by the backend; no percentage exists)"),
        plain(format!("  {:<5}{:<12}{}", "seq", "state", "elapsed s")),
    ];
    if run.events.is_empty() {
        lines.push(plain("  (none yet)"));
    }
    for event in &run.events {
        lines.push(plain(format!(
            "  {:<5}{:<12}{}",
            event.sequence, event.state, event.elapsed
        )));
    }
    lines.push(plain(""));
    // One line for the heading, the rest for the newest diagnostics.
    let room = height.saturating_sub(lines.len() + 1);
    lines.push(bold(format!(
        "backend stderr (last {} of {} lines)",
        run.diagnostics.len().min(room),
        run.diagnostics.len()
    )));
    let skip = run.diagnostics.len().saturating_sub(room);
    lines.extend(
        run.diagnostics
            .iter()
            .skip(skip)
            .map(|l| plain(format!("  {}", clip(l, width.saturating_sub(2))))),
    );
    lines
}

/// Body of the Result screen: the report of the final snapshot.
fn result(app: &App) -> Vec<Line<'static>> {
    let Some(outcome) = &app.outcome else {
        return vec![plain("no result")];
    };
    let s = &outcome.snapshot;
    let mut lines = vec![
        plain(format!(
            "request_id {}   job_id {}   elapsed {} s   timeout {} s",
            text(&s["request_id"]),
            text(&s["job_id"]),
            text(&s["elapsed_seconds"]),
            text(&s["timeout_seconds"])
        )),
        plain(format!(
            "interpreter {}",
            text(&s["interpreter"]["executable"])
        )),
        plain(""),
    ];
    lines.extend(outcome.report.lines().map(plain));
    if outcome.interrupted {
        lines.push(plain(""));
        lines.push(plain(
            "A cancel was requested during this run; the state above is the backend's own.",
        ));
    }
    lines.push(plain(""));
    lines.push(plain(
        "Enter returns to Setup; s saves the raw snapshot (and the stderr tail); q quits.",
    ));
    lines
}

/// Body of the Error screen: the problem plus any run diagnostics.
fn error(app: &App, height: usize, width: usize) -> Vec<Line<'static>> {
    let mut lines = vec![bold("the run did not produce a result")];
    if let Some(error) = &app.error {
        lines.extend(error.lines().map(|l| plain(l.to_string())));
    }
    if let Some(run) = app.run.as_ref().filter(|r| !r.diagnostics.is_empty()) {
        lines.push(plain(""));
        lines.push(bold("backend stderr tail"));
        let room = height.saturating_sub(lines.len() + 2);
        let skip = run.diagnostics.len().saturating_sub(room);
        lines.extend(
            run.diagnostics
                .iter()
                .skip(skip)
                .map(|l| plain(format!("  {}", clip(l, width.saturating_sub(2))))),
        );
    }
    lines.push(plain(""));
    lines.push(plain("Enter returns to Setup; q quits."));
    lines
}

/// Footer: the keys of the current screen, then the message or save prompt.
fn footer_text(app: &App) -> Text<'static> {
    let keys = match app.screen {
        Screen::Setup => "Tab/Shift-Tab field  Enter check  Ctrl-U clear  Esc quit  F1 keys",
        Screen::Check => "Esc cancel  ? keys",
        Screen::Confirm => "Enter run  Esc back  Up/Down scroll  ? keys",
        Screen::Running => "c or Ctrl-C cancel  ? keys",
        Screen::Result => "Enter setup  s save  q quit  Up/Down scroll  ? keys",
        Screen::Error => "Enter setup  q quit  Up/Down scroll  ? keys",
    };
    let message = app.message.clone().unwrap_or_default();
    Text::from(vec![
        Line::from(Span::styled(
            message,
            Style::new().add_modifier(Modifier::BOLD),
        )),
        plain(keys),
    ])
}

/// A one-line input box over the screen.
fn dialog(frame: &mut Frame, area: Rect, title: &str, value: &str) {
    let width = area.width.saturating_sub(8).max(20);
    let rect = Rect {
        x: area.x + (area.width - width) / 2,
        y: area.y + area.height / 2 - 1,
        width,
        height: 3,
    };
    frame.render_widget(Clear, rect);
    let block = Block::default()
        .borders(Borders::ALL)
        .title(format!(" {title} "));
    let line = Line::from(vec![
        Span::raw(value.to_string()),
        Span::styled(" ", Style::new().add_modifier(Modifier::REVERSED)),
    ]);
    frame.render_widget(Paragraph::new(line).block(block), rect);
}

const HELP: &str = "\
Tab / Shift-Tab   next / previous field (Setup)
Enter             check the backend, start the run, or return to Setup
Ctrl-U            clear the field being edited
c or Ctrl-C       cancel the run (one SIGINT to the backend; its own final
                  state is shown, a forced stop is shown as a failure)
s                 save the raw snapshot JSON to a new file (Result screen);
                  the backend stderr tail goes to <file>.stderr.txt
Esc               back, or quit from Setup
q                 quit (except on Setup, where it is text)
Ctrl-C            quit from any screen but Running (exit status 130)
Up / Down         scroll the Confirm, Result and Error screens by a line,
PgUp / PgDn       by ten lines
F1 or ?           this list (? is text on Setup)

Every run sends a fresh request_id; a result is shown only for the current
request. No percentage is shown: the backend reports state transitions only.";

/// Draw the help overlay centred in `area`.
fn help(frame: &mut Frame, area: Rect) {
    let width = area.width.saturating_sub(4).clamp(40, 78);
    let height = (HELP.lines().count() as u16 + 2).min(area.height);
    let rect = Rect {
        x: area.x + (area.width - width) / 2,
        y: area.y + (area.height - height) / 2,
        width,
        height,
    };
    frame.render_widget(Clear, rect);
    let block = Block::default()
        .borders(Borders::ALL)
        .title(" keys (Esc closes) ");
    frame.render_widget(
        Paragraph::new(HELP).block(block).wrap(Wrap { trim: false }),
        rect,
    );
}

#[cfg(test)]
mod tests {
    use super::super::app::{Action, Event, Key, Line as StderrLine, Msg};
    use super::*;
    use ratatui::backend::TestBackend;
    use ratatui::Terminal;
    use serde_json::json;

    /// The screen as text lines, trailing spaces trimmed.
    fn render(app: &App, width: u16, height: u16) -> Vec<String> {
        let mut terminal = Terminal::new(TestBackend::new(width, height)).unwrap();
        terminal.draw(|frame| draw(frame, app)).unwrap();
        let buffer = terminal.backend().buffer();
        (0..height)
            .map(|y| {
                (0..width)
                    .map(|x| buffer[(x, y)].symbol().to_string())
                    .collect::<String>()
                    .trim_end()
                    .to_string()
            })
            .collect()
    }

    /// Whether any rendered line contains `needle`.
    fn has(lines: &[String], needle: &str) -> bool {
        lines.iter().any(|l| l.contains(needle))
    }

    /// Feed each key to the reducer in order.
    fn keys(app: &mut App, list: &[Key]) {
        for key in list {
            app.apply(Msg::Key(*key));
        }
    }

    /// An app on each screen in turn, by driving the reducer.
    fn screens() -> Vec<(Screen, App)> {
        let mut out = Vec::new();
        let fresh = || {
            App::new(
                "/opt/py/bin/python".into(),
                "/data/run.log".into(),
                "60".into(),
            )
        };
        out.push((Screen::Setup, fresh()));
        let mut app = fresh();
        keys(&mut app, &[Key::Enter]);
        out.push((Screen::Check, app));
        let caps = json!({"status": "succeeded",
            "result": {"protocol_versions": [1], "operations": {"thermo.summary": {"versions": [1]}}},
            "provenance": {"package_version": "0.3.0", "python_version": "3.12.1",
                "python_executable": "/opt/py/bin/python", "numpy_version": "2.1.0"}});
        let mut app = fresh();
        keys(&mut app, &[Key::Enter]);
        let probe = match app.take_actions().pop() {
            Some(Action::Probe(p)) => p.id,
            other => panic!("{other:?}"),
        };
        app.apply(Msg::Probed {
            probe,
            result: Ok(caps.clone()),
        });
        assert_eq!(app.screen, Screen::Confirm);
        let request_id = app.run.as_ref().unwrap().request_id.clone();
        let mut running = App::new(
            "/opt/py/bin/python".into(),
            "/data/run.log".into(),
            "60".into(),
        );
        keys(&mut running, &[Key::Enter]);
        let probe = match running.take_actions().pop() {
            Some(Action::Probe(p)) => p.id,
            other => panic!("{other:?}"),
        };
        running.apply(Msg::Probed {
            probe,
            result: Ok(caps),
        });
        out.push((Screen::Confirm, app));
        keys(&mut running, &[Key::Enter]);
        let run = match running.take_actions().pop() {
            Some(Action::Start(s)) => s.id,
            other => panic!("{other:?}"),
        };
        let request_id = running
            .run
            .as_ref()
            .unwrap()
            .request_id
            .clone()
            .max(request_id);
        for (sequence, state) in [(1, "created"), (2, "running")] {
            running.apply(Msg::Line {
                run,
                line: StderrLine::Event(Event {
                    sequence,
                    state: state.into(),
                    elapsed: "0.01".into(),
                }),
            });
        }
        for i in 0..40 {
            running.apply(Msg::Line {
                run,
                line: StderrLine::Diagnostic(format!("stderr line {i} \\u{{1b}}[0m")),
            });
        }
        keys(&mut running, &[Key::Char('c')]);
        // Clone the running state for the Result and Error screens.
        let snapshot = json!({"job_schema_version": 1, "request_id": request_id, "job_id": "j",
            "state": "succeeded", "elapsed_seconds": 1.25, "timeout_seconds": 60.0,
            "interpreter": {"executable": "/opt/py/bin/python"},
            "cleanup": {"status": "complete"},
            "backend_response": {"result": {"sample_count": 3, "unit_system": "metal",
                "units": {"Temp": "K", "PotEng": "eV"},
                "statistics": {"Temp": {"min": 1, "max": 3, "mean": 2, "std": 0.816},
                    "PotEng": {"min": -10.5, "max": -9.5, "mean": -10, "std": 0.4}}},
                "warnings": ["unit system assumed"]}});
        let mut result = App::new(
            "/opt/py/bin/python".into(),
            "/data/run.log".into(),
            "60".into(),
        );
        keys(&mut result, &[Key::Enter]);
        let probe = match result.take_actions().pop() {
            Some(Action::Probe(p)) => p.id,
            other => panic!("{other:?}"),
        };
        result.apply(Msg::Probed {
            probe,
            result: Ok(json!({"status": "succeeded",
                "result": {"protocol_versions": [1], "operations": {"thermo.summary": {"versions": [1]}}}})),
        });
        keys(&mut result, &[Key::Enter]);
        let run = match result.take_actions().pop() {
            Some(Action::Start(s)) => s.id,
            other => panic!("{other:?}"),
        };
        let mut snapshot = snapshot;
        snapshot["request_id"] = json!(result.run.as_ref().unwrap().request_id.clone());
        let mut error = App::new(
            "/opt/py/bin/python".into(),
            "/data/run.log".into(),
            "60".into(),
        );
        keys(&mut error, &[Key::Enter]);
        let probe = match error.take_actions().pop() {
            Some(Action::Probe(p)) => p.id,
            other => panic!("{other:?}"),
        };
        error.apply(Msg::Probed {
            probe,
            result: Err("python_not_found: cannot start \"/opt/py/bin/python\": No such file\nbackend stderr:\nnope".into()),
        });
        result.apply(Msg::Finished {
            run,
            result: Ok((snapshot, b"{}".to_vec())),
            interrupted: false,
        });
        assert_eq!(result.screen, Screen::Result);
        out.push((Screen::Running, running));
        out.push((Screen::Result, result));
        out.push((Screen::Error, error));
        out
    }

    #[test]
    /// Every screen renders at the minimum size and larger with its key
    /// content visible, and the footer names the keys.
    fn every_screen_renders_at_80x24_and_120x40() {
        for (screen, app) in screens() {
            assert_eq!(app.screen, screen);
            for (w, h) in [(80, 24), (120, 40)] {
                let lines = render(&app, w, h);
                assert_eq!(lines.len(), h as usize);
                assert!(has(&lines, "lkpr-rs tui"), "{screen:?} {w}x{h}: {lines:#?}");
                let expect: &[&str] = match screen {
                    Screen::Setup => &[
                        "python     >",
                        "/opt/py/bin/python",
                        "log file",
                        "timeout s",
                        "Enter check",
                    ],
                    Screen::Check => &[
                        "checking /opt/py/bin/python -m lammpkeeper exec --capabilities",
                        "Esc cancel",
                    ],
                    Screen::Confirm => &[
                        "lammpkeeper 0.3.0",
                        "request_id",
                        "\"operation\": \"thermo.summary\"",
                        "--events",
                        "Enter run",
                    ],
                    Screen::Running => &[
                        "CANCEL REQUESTED",
                        "created",
                        "running",
                        "stderr line 39",
                        "no percentage",
                        "c or Ctrl-C cancel",
                    ],
                    Screen::Result => &[
                        "thermo.summary  succeeded  (3 samples, unit system: metal)",
                        "PotEng  eV",
                        "warning  unit system assumed",
                        "elapsed 1.25 s",
                        "s save",
                    ],
                    Screen::Error => {
                        &["python_not_found", "backend stderr:", "nope", "Enter setup"]
                    }
                };
                for needle in expect {
                    assert!(
                        has(&lines, needle),
                        "{screen:?} {w}x{h} lacks {needle:?}: {lines:#?}"
                    );
                }
                assert!(
                    !lines.iter().any(|l| l.contains('\u{1b}')),
                    "{screen:?}: raw escape drawn"
                );
            }
        }
    }

    #[test]
    /// The Result screen shows the CLI report line for line (parity with
    /// `thermo-summary`), and the Running screen's stderr tail keeps only
    /// what fits, newest last.
    fn result_matches_the_cli_report_and_tails_are_bounded() {
        let (_, result) = screens()
            .into_iter()
            .find(|(s, _)| *s == Screen::Result)
            .unwrap();
        let lines = render(&result, 120, 40);
        for line in result.outcome.as_ref().unwrap().report.lines() {
            let shown = lines
                .iter()
                .any(|l| l.trim_matches(|c| c == '│' || c == ' ') == line.trim());
            assert!(shown, "missing {line:?} in {lines:#?}");
        }
        let (_, running) = screens()
            .into_iter()
            .find(|(s, _)| *s == Screen::Running)
            .unwrap();
        let lines = render(&running, 80, 24);
        assert!(has(&lines, "stderr line 39"));
        assert!(!has(&lines, "stderr line 0 "), "{lines:#?}");
        assert!(has(&lines, "backend stderr (last"));
    }

    #[test]
    /// Overlays: the save dialog shows the name being typed, the help lists
    /// the keys, and a too-small terminal gets a notice instead of a layout.
    fn overlays_and_small_terminals() {
        let (_, mut result) = screens()
            .into_iter()
            .find(|(s, _)| *s == Screen::Result)
            .unwrap();
        keys(&mut result, &[Key::Char('s')]);
        let lines = render(&result, 80, 24);
        assert!(has(&lines, "save snapshot as"));
        assert!(has(&lines, "run.log.snapshot.json"), "{lines:#?}");
        keys(&mut result, &[Key::Esc, Key::Help]);
        let lines = render(&result, 80, 24);
        assert!(has(&lines, "keys (Esc closes)"));
        assert!(has(&lines, "fresh request_id"), "{lines:#?}");
        let lines = render(&result, 40, 10);
        assert!(has(&lines, "80x24") && has(&lines, "40x10"), "{lines:#?}");
        assert!(has(&lines, "Ctrl-C"), "{lines:#?}");
        assert!(!has(&lines, "Result"));
    }

    #[test]
    /// A diagnostic longer than the body is cut to one row with an ellipsis
    /// (so the tail never wraps past the border), and the scroll offset
    /// moves a long Confirm body up by whole rows.
    fn long_lines_are_clipped_and_scrolling_moves_the_body() {
        let (_, mut running) = screens()
            .into_iter()
            .find(|(s, _)| *s == Screen::Running)
            .unwrap();
        let id = running.run.as_ref().unwrap().id;
        let long = "x".repeat(300);
        running.apply(Msg::Line {
            run: id,
            line: StderrLine::Diagnostic(long.clone()),
        });
        let lines = render(&running, 80, 24);
        assert!(!has(&lines, &long));
        assert!(has(&lines, "\u{2026}"), "{lines:#?}");
        let rows = lines.iter().filter(|l| l.contains("xxxxxxxx")).count();
        assert_eq!(rows, 1, "{lines:#?}");

        let (_, mut confirm) = screens()
            .into_iter()
            .find(|(s, _)| *s == Screen::Confirm)
            .unwrap();
        let before = render(&confirm, 80, 24);
        keys(&mut confirm, &[Key::Down, Key::Down]);
        assert_eq!(confirm.scroll, 2);
        let after = render(&confirm, 80, 24);
        // Row 2 is the first body row (header, then the border).
        assert_eq!(after[2], before[4], "{before:#?}\n{after:#?}");
        assert_ne!(after[2], before[2]);
    }
}
