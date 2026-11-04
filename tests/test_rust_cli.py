"""UI-1: the Rust CLI `lkpr-rs` against the real Python backend.

`lkpr-rs` only drives `python -m lammpkeeper exec|run`; these tests prove that
its output matches the Python paths exactly and that interruption, timeout and
environment errors end cleanly. Fake-backend transport cases live in
`rust/lkpr-rs/tests/cli.rs` (run with `cargo test`).

The binary comes from LKPR_RS_BIN, or is built with cargo into
`rust/lkpr-rs/target`. Without cargo every test skips visibly; a failed build is
a failure, not a skip. Linux/POSIX only, as measured.
"""
import contextlib
import json
import os
import re
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

import _util

ROOT = Path(_util.REPO_ROOT)
CRATE = ROOT / 'rust' / 'lkpr-rs'
EVALS = ROOT / '.agents' / 'skills' / 'lammpkeeper' / 'evals'
_BIN = []


def _binary():
    """Return the lkpr-rs path, building it once; skip visibly without cargo."""
    if _BIN:
        return _BIN[0]
    explicit = os.environ.get('LKPR_RS_BIN')
    if explicit:
        _BIN.append(explicit)
        return explicit
    cargo = shutil.which('cargo')
    _util.require(cargo is not None, 'cargo not installed (Rust CLI not built)')
    env = dict(os.environ)
    # Test runs isolate HOME, but rustup finds its toolchains via HOME. For a
    # rustup-installed cargo (~/.cargo/bin/cargo) point it at that user's homes.
    cargo_home = Path(cargo).resolve().parent.parent
    if 'RUSTUP_HOME' not in env and cargo_home.name == '.cargo':
        env.setdefault('CARGO_HOME', str(cargo_home))
        if (cargo_home.parent / '.rustup').is_dir():
            env['RUSTUP_HOME'] = str(cargo_home.parent / '.rustup')
    # Ask cargo where it put the binary: CARGO_TARGET_DIR or a configured
    # build.target-dir moves it away from rust/lkpr-rs/target/debug.
    build = subprocess.run([cargo, 'build', '--quiet', '--message-format=json',
                            '--manifest-path', str(CRATE / 'Cargo.toml')],
                           capture_output=True, text=True, timeout=600, env=env)
    assert build.returncode == 0, build.stderr
    paths = [msg['executable'] for msg in map(json.loads, build.stdout.splitlines())
             if msg.get('reason') == 'compiler-artifact' and msg.get('executable')
             and msg['target']['name'] == 'lkpr-rs']
    assert len(paths) == 1, f"cargo reported {len(paths)} lkpr-rs executables: {paths}"
    _BIN.append(paths[0])
    return paths[0]


@contextlib.contextmanager
def _home():
    """Isolated HOME/TMPDIR with a space in the path; history disabled."""
    with tempfile.TemporaryDirectory(prefix='lkpr rs ') as tmp:
        env = dict(os.environ, HOME=tmp, LKPR_NO_HISTORY='1', PYTHONPATH=str(ROOT))
        env.pop('LKPR_PYTHON', None)
        yield Path(tmp), env


def _rs(args, env, cwd, timeout=120):
    """Run lkpr-rs and return the completed process."""
    return subprocess.run([_binary(), *args], capture_output=True, text=True,
                          env=env, cwd=cwd, timeout=timeout)


def _request(log):
    """The EXEC-1 request lkpr-rs builds for thermo-summary."""
    return {'protocol_version': 1, 'request_id': 'r', 'operation': 'thermo.summary',
            'operation_version': 1, 'input': {'log': str(log)}, 'parameters': {}}


def _comparable(response):
    """Backend response without per-call identity (request id)."""
    return {k: v for k, v in response.items() if k != 'request_id'}


def test_json_output_matches_direct_python_and_lkpr_run():
    """Values, units, warnings and errors agree across all four entry points."""
    _util.require_numpy()
    from lammpkeeper.execution import execute_request
    for case in ('native-unit-summary', 'unresolved-units', 'malformed-row'):
        log = EVALS / case / 'files' / 'log.lammps'
        with _home() as (tmp, env):
            direct = execute_request(_request(log))
            exec_cli = subprocess.run([sys.executable, '-m', 'lammpkeeper', 'exec', '--request', '-'],
                                      input=json.dumps(_request(log)), capture_output=True,
                                      text=True, env=env, cwd=tmp, timeout=120)
            run_cli = subprocess.run([sys.executable, '-m', 'lammpkeeper', 'run', '--request', '-',
                                      '--python', sys.executable],
                                     input=json.dumps(_request(log)), capture_output=True,
                                     text=True, env=env, cwd=tmp, timeout=120)
            rs = _rs(['thermo-summary', '--python', sys.executable, '--log', str(log), '--json'],
                     env, tmp)
        rs_snapshot = json.loads(rs.stdout)
        run_snapshot = json.loads(run_cli.stdout)
        expected = _comparable(direct)
        assert _comparable(json.loads(exec_cli.stdout)) == expected, case
        assert _comparable(run_snapshot['backend_response']) == expected, case
        assert _comparable(rs_snapshot['backend_response']) == expected, case
        assert rs_snapshot['state'] == run_snapshot['state'], case
        succeeded = direct['status'] == 'succeeded'
        assert rs.returncode == run_cli.returncode == (0 if succeeded else 1), (case, rs.stderr)


def test_human_output_shows_backend_values_units_and_warnings():
    """The readable table prints the backend numbers and warnings unchanged."""
    _util.require_numpy()
    from lammpkeeper.execution import execute_request
    log = EVALS / 'unresolved-units' / 'files' / 'log.lammps'
    with _home() as (tmp, env):
        rs = _rs(['thermo-summary', '--python', sys.executable, '--log', str(log)], env, tmp)
    assert rs.returncode == 0, rs.stderr
    direct = execute_request(_request(log))
    for column, stats in direct['result']['statistics'].items():
        line = next(l for l in rs.stdout.splitlines() if l.split()[:1] == [column])
        for key in ('min', 'max', 'mean', 'std'):
            assert json.dumps(stats[key]) in line.split(), (column, key, line)
    for warning in direct['warnings']:
        assert 'warning  ' + warning in rs.stdout


def test_exact_large_steps_and_stat_strings_survive_json_mode():
    """Steps just below 2**53 and nanosecond stat strings pass through exactly."""
    _util.require_numpy()
    with _home() as (tmp, env):
        log = tmp / 'big steps.log'
        log.write_text('units metal\ntimestep 0.001\nrun 2\nStep Temp\n'
                       '9007199254740990 300\n9007199254740991 301\n')
        rs = _rs(['thermo-summary', '--python', sys.executable, '--log', str(log), '--json'],
                 env, tmp)
        assert rs.returncode == 0, rs.stderr
        assert '"min":9007199254740990.0' in rs.stdout and '"max":9007199254740991.0' in rs.stdout
        fingerprint = json.loads(rs.stdout)['backend_response']['provenance']['input_fingerprint']
        assert fingerprint['mtime_ns'] == str(log.stat().st_mtime_ns)


def test_interpreter_symlink_in_path_with_spaces():
    """A venv-style interpreter symlink in a spaced directory is used as selected."""
    _util.require_numpy()
    with _home() as (tmp, env):
        venv_bin = tmp / 'my env' / 'bin'
        venv_bin.mkdir(parents=True)
        python = venv_bin / 'python'
        python.symlink_to(sys.executable)
        env['LKPR_PYTHON'] = str(python)
        log = EVALS / 'native-unit-summary' / 'files' / 'log.lammps'
        rs = _rs(['thermo-summary', '--log', str(log), '--json'], env, tmp)
        assert rs.returncode == 0, rs.stderr
        snapshot = json.loads(rs.stdout)
        assert snapshot['interpreter']['executable'] == str(python)
        doctor = _rs(['doctor'], env, tmp)
        assert doctor.returncode == 0 and 'status      ok' in doctor.stdout, doctor.stdout


def test_python_without_lammpkeeper_fails_clearly():
    """A real interpreter that cannot import lammpkeeper is reported, not guessed around."""
    with _home() as (tmp, env):
        bare = tmp / 'bare python'
        # -I -S: no user/site packages and no cwd on sys.path, so no lammpkeeper.
        bare.write_text(f'#!/bin/sh\nexec {sys.executable} -I -S "$@"\n')
        bare.chmod(0o755)
        env.pop('PYTHONPATH')
        for args in (['doctor'], ['thermo-summary', '--log', 'x.log']):
            rs = _rs([*args, '--python', str(bare)], env, tmp)
            assert rs.returncode == 1, (args, rs.stdout, rs.stderr)
            assert 'invalid_backend_output' in rs.stderr and 'No module named' in rs.stderr, rs.stderr
            assert rs.stdout == '', args


def _descendants(pid):
    """All live descendant pids of pid, from /proc children lists."""
    found, stack = [], [pid]
    while stack:
        current = stack.pop()
        for task in Path(f'/proc/{current}/task').glob('*'):
            with contextlib.suppress(OSError):
                kids = [int(k) for k in (task / 'children').read_text().split()]
                found.extend(kids)
                stack.extend(kids)
    return found


def _stopped(pid, timeout=3.0):
    """True once pid is gone or a zombie awaiting its reaper."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1].split()[0]
        except (OSError, IndexError):
            return True
        if state == 'Z':
            return True
        time.sleep(0.02)
    return False


def _blocked_run(extra, env, tmp):
    """Start thermo-summary on a FIFO log so the real backend blocks in its read."""
    fifo = tmp / 'blocked log'
    os.mkfifo(fifo)
    proc = subprocess.Popen([_binary(), 'thermo-summary', '--python', sys.executable,
                             '--log', str(fifo), *extra],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env=env, cwd=tmp)
    # Wait until the scientific child (exec --request) exists under lkpr run.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        tree = _descendants(proc.pid)
        cmdlines = []
        for pid in tree:
            with contextlib.suppress(OSError):
                cmdlines.append(Path(f'/proc/{pid}/cmdline').read_bytes())
        if any(b'exec\x00--request' in c for c in cmdlines):
            return proc, tree
        time.sleep(0.05)
    proc.kill()
    raise AssertionError('backend did not reach execution')


def test_ctrl_c_cancels_through_the_backend_and_cleans_up():
    """SIGINT to lkpr-rs: cancelled snapshot, exit 130, no surviving backend process."""
    _util.require_numpy()
    with _home() as (tmp, env):
        proc, tree = _blocked_run(['--timeout', '60'], env, tmp)
        proc.send_signal(signal.SIGINT)
        out, err = proc.communicate(timeout=30)
        assert proc.returncode == 130, (out, err)
        assert 'cancelled' in out and 'Cancellation requested by owner' in out, out
        assert all(_stopped(pid) for pid in tree), tree


def test_backend_timeout_is_reported_and_cleaned_up():
    """The backend's own deadline ends the job as timed_out (exit 1), not forced."""
    _util.require_numpy()
    with _home() as (tmp, env):
        proc, tree = _blocked_run(['--timeout', '2', '--json'], env, tmp)
        out, err = proc.communicate(timeout=60)
        assert proc.returncode == 1, (out, err)
        snapshot = json.loads(out)
        assert snapshot['state'] == 'timed_out' and snapshot['error']['code'] == 'timed_out'
        assert snapshot['cleanup']['status'] == 'complete'
        assert 'supervisor_unresponsive' not in err
        assert all(_stopped(pid) for pid in tree), tree


def test_tui_without_a_terminal_is_a_usage_error():
    """`lkpr-rs tui` on pipes exits 2 with usage on stderr and nothing on stdout."""
    with _home() as (tmp, env):
        done = subprocess.run([_binary(), 'tui', '--python', sys.executable],
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              env=dict(env, TERM='xterm-256color'), cwd=tmp, timeout=60)
        assert done.returncode == 2, (done.stdout, done.stderr)
        assert done.stdout == ''
        assert 'interactive terminal' in done.stderr and 'thermo-summary' in done.stderr


def _tui_session(keys, env, cwd, term='xterm-256color'):
    """Run `lkpr-rs tui` on a pseudo-terminal, send `keys` (bytes, or a function
    of the Popen object returning bytes) once the alternate screen is entered
    (or at once when it never is), and return (returncode, bytes written to the
    terminal, stderr, termios before, after)."""
    import fcntl
    import pty
    import select
    import struct
    import termios
    master, slave = pty.openpty()
    try:
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
        before = termios.tcgetattr(slave)
        proc = subprocess.Popen([_binary(), 'tui', '--python', sys.executable],
                                stdin=slave, stdout=slave, stderr=subprocess.PIPE,
                                text=True, env=dict(env, TERM=term), cwd=cwd)
        screen = b''
        sent = False
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            exited = proc.poll() is not None
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                with contextlib.suppress(OSError):
                    screen += os.read(master, 65536)
            elif exited:
                break
            if not sent and (b'\x1b[?1049h' in screen or term == 'dumb'):
                os.write(master, keys(proc) if callable(keys) else keys)
                sent = True
        if proc.poll() is None:
            proc.kill()
        _, err = proc.communicate(timeout=30)
        after = termios.tcgetattr(slave)
        return proc.returncode, screen, err, before, after
    finally:
        os.close(master)
        os.close(slave)


def test_tui_restores_the_terminal_when_left():
    """Under a pseudo-terminal: Esc on Setup exits 0, Ctrl-C exits 130, SIGTERM
    and SIGHUP exit 1; all four enter and leave the alternate screen and undo
    raw mode; a dumb terminal is refused before anything is drawn."""
    import termios

    def sigterm(proc):
        proc.send_signal(signal.SIGTERM)
        return b''

    def sighup(proc):
        proc.send_signal(signal.SIGHUP)
        return b''

    with _home() as (tmp, env):
        for keys, code in ((b'\x1b', 0), (b'\x03', 130), (sigterm, 1), (sighup, 1)):
            rc, screen, err, before, after = _tui_session(keys, env, tmp)
            assert rc == code, (keys, rc, err)
            enter = screen.find(b'\x1b[?1049h')
            leave = screen.rfind(b'\x1b[?1049l')
            assert 0 <= enter < leave, screen[-200:]
            assert b'lkpr-rs tui' in screen and b'Setup' in screen, screen[:400]
            # ECHO and ICANON are back (raw mode cleared them); the whole
            # settings tuple is restored.
            lflag = after[3]
            assert lflag & termios.ECHO and lflag & termios.ICANON, lflag
            assert after == before, (before, after)
            assert err == '', err
        rc, screen, err, _, _ = _tui_session(b'\x1b', env, tmp, term='dumb')
        assert rc == 2, (rc, err)
        assert b'\x1b[?1049h' not in screen, screen[:200]
        assert 'interactive terminal' in err, err


_CSI = re.compile(r'\x1b\[([0-9;?<>=!]*)([A-Za-z@`])')


def _screen(data, rows, cols):
    """Place the bytes ratatui wrote on a rows x cols grid and return it as
    text. ESC [ r ; c H moves the cursor, printable text advances it, ESC [ 2 J
    clears, every other control sequence is dropped. ratatui redraws only the
    cells that changed since the previous frame, so a phrase is rarely
    contiguous in the raw stream; only the composed grid can be searched."""
    grid = [[' '] * cols for _ in range(rows)]
    row = col = 0
    text = data.decode('utf-8', errors='replace')
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '\x1b':
            m = _CSI.match(text, i)
            if m is None:
                i += 1
                continue
            params, final = m.groups()
            if final == 'H':
                parts = (params.split(';') + [''])[:2]
                row = int(parts[0] or 1) - 1
                col = int(parts[1] or 1) - 1
            elif final == 'J' and params in ('2', '3'):
                grid = [[' '] * cols for _ in range(rows)]
            i = m.end()
            continue
        if ch == '\r':
            col = 0
        elif ch == '\n':
            row += 1
        elif ch >= ' ':
            if 0 <= row < rows and 0 <= col < cols:
                grid[row][col] = ch
            col += 1
        i += 1
    return '\n'.join(''.join(line).rstrip() for line in grid)


def _tui_drive(args, script, env, cwd, rows=50, cols=200, timeout=120,
               controlling=False):
    """Run `lkpr-rs tui --python <this python> *args` on a rows x cols
    pseudo-terminal and play `script`: for each (phrase, keys), wait until the
    drawn screen contains phrase, record that screen, then type keys (bytes, or
    a function of the Popen object returning bytes; None closes the terminal
    instead, as a terminal emulator does when its window goes). With
    `controlling` the process is a session leader with the pseudo-terminal as
    its controlling terminal, so closing it hangs the process up (SIGHUP) the
    way a real terminal does. Returns (returncode, the screens recorded per
    step plus the final one, stderr)."""
    import fcntl
    import pty
    import select
    import struct
    import termios
    master, slave = pty.openpty()
    closed = False

    def close_terminal():
        nonlocal closed
        if not closed:
            closed = True
            os.close(master)
            os.close(slave)

    def own_the_terminal():
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    try:
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
        proc = subprocess.Popen([_binary(), 'tui', '--python', sys.executable, *args],
                                stdin=slave, stdout=slave, stderr=subprocess.PIPE,
                                text=True, env=dict(env, TERM='xterm-256color'), cwd=cwd,
                                preexec_fn=own_the_terminal if controlling else None)
        data, screens, step = b'', [], 0
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if closed:
                if proc.poll() is not None:
                    break
                time.sleep(0.1)
                continue
            exited = proc.poll() is not None
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                with contextlib.suppress(OSError):
                    data += os.read(master, 65536)
            elif exited:
                break
            if step < len(script):
                phrase, keys = script[step]
                shown = _screen(data, rows, cols)
                if phrase in shown:
                    screens.append(shown)
                    typed = keys(proc) if callable(keys) else keys
                    if typed is None:
                        close_terminal()
                    else:
                        os.write(master, typed)
                    step += 1
        if proc.poll() is None:
            # A hung session must not leave a backend behind for the next test.
            for pid in _descendants(proc.pid):
                with contextlib.suppress(OSError):
                    os.kill(pid, signal.SIGKILL)
            proc.kill()
        _, err = proc.communicate(timeout=30)
        screens.append(_screen(data, rows, cols))
        return proc.returncode, screens, err
    finally:
        close_terminal()


def test_tui_runs_the_backend_and_saves_the_snapshot():
    """A whole session on a pseudo-terminal against the real backend: Enter
    checks the capabilities, Enter starts the run, the Result screen shows the
    report `thermo-summary` prints for the same log, `s` + Enter writes the raw
    snapshot under the default name in the working directory, `q` exits 0. The
    saved snapshot is bound to the request_id shown on Confirm and Result and
    carries the backend response `thermo-summary --json` reports."""
    _util.require_numpy()
    log = EVALS / 'native-unit-summary' / 'files' / 'log.lammps'
    with _home() as (tmp, env):
        work = tmp / 'work'
        work.mkdir()
        rc, screens, err = _tui_drive(['--log', str(log)], [
            ('Enter check', b'\r'),
            ('Enter starts the run', b'\r'),
            ('s saves the raw snapshot', b's'),
            ('save snapshot as', b'\r'),
            ('saved log.lammps.snapshot.json', b'q'),
        ], env, work)
        assert rc == 0 and err == '', (rc, err, screens[-1])
        assert len(screens) == 6, screens[-1]
        setup, confirm, result = screens[0], screens[1], screens[2]
        assert str(log) in setup and '1/5 setup' in setup, setup
        assert '"operation": "thermo.summary"' in confirm and '3/5 confirm' in confirm, confirm
        assert '5/5 result' in result, result
        human = _rs(['thermo-summary', '--python', sys.executable, '--log', str(log)], env, work)
        assert human.returncode == 0, human.stderr
        for line in human.stdout.splitlines():
            assert line.rstrip() in result, (line, result)
        saved = work / 'log.lammps.snapshot.json'
        raw = saved.read_bytes()
        snapshot = json.loads(raw)
        assert raw.endswith(b'\n') and snapshot['state'] == 'succeeded', snapshot
        assert snapshot['request_id'] in confirm and snapshot['request_id'] in result
        assert snapshot['job_id'] in result, result
        rs = _rs(['thermo-summary', '--python', sys.executable, '--log', str(log), '--json'],
                 env, work)
        cli = json.loads(rs.stdout)
        assert _comparable(snapshot['backend_response']) == _comparable(cli['backend_response'])
        assert set(snapshot) == set(cli), (sorted(snapshot), sorted(cli))
        # Lifecycle events were classified as events, not kept as stderr text.
        aside = work / 'log.lammps.snapshot.json.stderr.txt'
        assert not aside.exists() or '"sequence"' not in aside.read_text(), aside


def test_tui_cancels_through_the_backend_and_cleans_up():
    """`c` on the Running screen: SIGINT reaches the blocked backend, the Result
    screen shows the backend's own cancelled snapshot with the cancel note, no
    backend process survives, and `q` leaves with 0."""
    _util.require_numpy()
    with _home() as (tmp, env):
        fifo = tmp / 'blocked log'
        os.mkfifo(fifo)
        tree = []

        def cancel(proc):
            # Press c only once the scientific child (exec --request) exists.
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                tree[:] = _descendants(proc.pid)
                cmdlines = []
                for pid in tree:
                    with contextlib.suppress(OSError):
                        cmdlines.append(Path(f'/proc/{pid}/cmdline').read_bytes())
                if any(b'exec\x00--request' in c for c in cmdlines):
                    return b'c'
                time.sleep(0.05)
            raise AssertionError('backend did not reach execution')

        rc, screens, err = _tui_drive(['--log', str(fifo), '--timeout', '60'], [
            ('Enter check', b'\r'),
            ('Enter starts the run', b'\r'),
            ('c or Ctrl-C cancel', cancel),
            ('A cancel was requested', b'q'),
        ], env, tmp)
        assert rc == 0 and err == '', (rc, err, screens[-1])
        assert len(screens) == 5, screens[-1]
        result = screens[3]
        assert 'thermo.summary  cancelled' in result, result
        assert 'Cancellation requested by owner' in result, result
        assert all(_stopped(pid) for pid in tree), tree


def test_tui_stops_the_backend_when_the_terminal_closes():
    """The terminal window goes away during a run (hang-up on the controlling
    terminal): the process leaves with 1, says on stderr that it waits for the
    backend, and the backend, which sits in its own process group and never
    saw the hang-up, is cancelled and gone."""
    _util.require_numpy()
    with _home() as (tmp, env):
        fifo = tmp / 'blocked log'
        os.mkfifo(fifo)
        tree = []

        def close_once_running(proc):
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                tree[:] = _descendants(proc.pid)
                cmdlines = []
                for pid in tree:
                    with contextlib.suppress(OSError):
                        cmdlines.append(Path(f'/proc/{pid}/cmdline').read_bytes())
                if any(b'exec\x00--request' in c for c in cmdlines):
                    return None
                time.sleep(0.05)
            raise AssertionError('backend did not reach execution')

        rc, screens, err = _tui_drive(['--log', str(fifo), '--timeout', '60'], [
            ('Enter check', b'\r'),
            ('Enter starts the run', b'\r'),
            ('c or Ctrl-C cancel', close_once_running),
        ], env, tmp, controlling=True)
        assert rc == 1, (rc, err, screens[-1])
        # Either the hang-up is seen before crossterm reads the dead tty, or a
        # draw fails with EIO first; both are terminal errors, never a spin.
        assert 'terminal_error' in err, err
        assert 'waiting for the backend to stop' in err, err
        assert tree and all(_stopped(pid) for pid in tree), tree


def test_tui_too_small_terminal_shows_the_notice_and_leaves_on_ctrl_c():
    """Below 80x24 nothing but the notice is drawn, and Ctrl-C still leaves
    (130) so nobody is stuck in a window they cannot enlarge."""
    with _home() as (tmp, env):
        rc, screens, err = _tui_drive([], [
            ('at least 80x24', b'\x03'),
        ], env, tmp, rows=12, cols=60)
        assert rc == 130 and err == '', (rc, err, screens[-1])
        notice = screens[0]
        assert '60x12' in notice and 'Ctrl-C' in notice, notice
        assert 'Setup' not in notice, notice
