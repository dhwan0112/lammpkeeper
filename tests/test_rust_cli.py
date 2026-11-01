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
    build = subprocess.run([cargo, 'build', '--quiet', '--manifest-path', str(CRATE / 'Cargo.toml')],
                           capture_output=True, text=True, timeout=600, env=env)
    assert build.returncode == 0, build.stderr
    path = str(CRATE / 'target' / 'debug' / 'lkpr-rs')
    _BIN.append(path)
    return path


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
