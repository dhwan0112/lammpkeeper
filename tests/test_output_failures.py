"""REV-UI-3: an explicit output request either writes its artifact or fails.

Before this fix, several export paths and a direct `plot pressure` request
printed a message and returned, so `--batch` and one-shot runs exited 0 with
no artifact. Those paths now raise, the shell records a failure, and nothing
(not even the output directory) is created first. `plot all` may still skip an
inapplicable pressure plot deliberately, with a notice.
"""
import contextlib
import io
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from unittest.mock import patch

import _util


def _write_dump(path):
    """Two frames of one Fe atom moving 1 -> 2 Å in x (MSD [0, 1])."""
    text = ''
    for step, x in ((0, 1.0), (100, 2.0)):
        text += ('ITEM: TIMESTEP\n%d\nITEM: NUMBER OF ATOMS\n1\n'
                 'ITEM: BOX BOUNDS pp pp pp\n0 100\n0 100\n0 100\n'
                 'ITEM: ATOMS id type x y z\n1 1 %s 1 1\n' % (step, x))
    path.write_text(text)


def _write_log(path, pressure):
    """A two-row thermo log, with or without a Press column."""
    header = 'Step Temp Press' if pressure else 'Step Temp'
    rows = ['0 300 1.0', '10 301 2.0'] if pressure else ['0 300', '10 301']
    # `units metal` as LAMMPS echoes it, so units are explicit and only the
    # pressure columns differ between the two variants.
    path.write_text('\n'.join(['units metal', header] + rows + ['Loop time of 1 on 1 procs for 10 steps with 1 atoms', '']))


def _shell(root, dump=True, log=None):
    """A noninteractive session writing to root/out; MSD of Fe is cached when a dump is loaded."""
    from lammps_post.shell import LammpsPostShell
    shell = LammpsPostShell()
    shell.noninteractive = True
    shell.state.output_dir = str(root / 'out')
    with contextlib.redirect_stdout(io.StringIO()):
        if dump:
            path = root / 't.dump'
            _write_dump(path)
            shell.onecmd('load dump %s' % shlex.quote(str(path)))
            shell.onecmd('set types 1=Fe')
            shell.onecmd('set dt 1')
            shell.onecmd('analyze msd --species Fe')
            assert shell.last_command_ok and 'msd_Fe' in shell.state.cache
        if log is not None:
            path = root / 'log.lammps'
            _write_log(path, pressure=log)
            shell.onecmd('load log %s' % shlex.quote(str(path)))
            assert shell.last_command_ok
    return shell


def _fails(shell, command):
    """Run one command; assert the shell recorded a failure."""
    with contextlib.redirect_stdout(io.StringIO()) as out:
        shell.onecmd(command)
    assert shell.last_command_ok is False, (command, out.getvalue())
    return out.getvalue()


def _ok(shell, command):
    """Run one command; assert it succeeded."""
    with contextlib.redirect_stdout(io.StringIO()) as out:
        shell.onecmd(command)
    assert shell.last_command_ok is True, (command, out.getvalue())
    return out.getvalue()


def test_failed_export_requests_fail_and_create_nothing():
    """Missing data, unknown format, bad usage and no arrays fail before any write."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shell = _shell(root)
        shell.state.cache['meta_only'] = {'label': 'x', 'n_frames': 3}
        for command in ('export csv missing', 'export latex missing', 'export bogus msd_Fe',
                        'export', 'export csv', 'export csv meta_only', 'export latex meta_only'):
            _fails(shell, command)
        assert not (root / 'out').exists(), sorted(p.name for p in (root / 'out').glob('*'))


def test_missing_pandas_fails_for_tabular_exports():
    """CSV/LaTeX need pandas; without it the request fails instead of printing only."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shell = _shell(root)
        with patch('lammps_post.shell.HAS_PANDAS', False):
            _fails(shell, 'export csv msd_Fe')
            _fails(shell, 'export latex msd_Fe')
        assert not (root / 'out').exists()


def test_csv_header_failure_leaves_no_partial_file():
    """The file is opened only after everything written into it has been built."""
    _util.require_numpy()
    _util.require(_util_has('pandas'), 'pandas not installed')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shell = _shell(root)
        with patch.object(type(shell), '_export_header_lines',
                          side_effect=RuntimeError('header failed')):
            _fails(shell, 'export csv msd_Fe')
            _fails(shell, 'export latex msd_Fe')
        assert not (root / 'out' / 'msd_Fe.csv').exists()
        assert not (root / 'out' / 'msd_Fe.tex').exists()


def test_successful_exports_and_summary_names_follow_the_help_text():
    """Valid exports still write; `export summary [filename]` uses the name as given."""
    _util.require_numpy()
    _util.require(_util_has('pandas'), 'pandas not installed')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shell = _shell(root)
        _ok(shell, 'export csv msd_Fe')
        assert (root / 'out' / 'msd_Fe.csv').read_text().splitlines()[0] == 'time,msd'
        _ok(shell, 'export latex msd_Fe')
        assert (root / 'out' / 'msd_Fe.tex').exists()
        _ok(shell, 'export summary')
        assert (root / 'out' / 'summary.txt').exists()
        named = root / 'notes.md'
        _ok(shell, 'export summary %s' % shlex.quote(str(named)))
        assert named.exists() and 'LAMMPS-POST Analysis Summary' in named.read_text()
        verbatim = root / 'my_summary.txt'
        _ok(shell, 'export summary %s' % shlex.quote(str(verbatim)))
        assert verbatim.exists()


def test_requested_pressure_plot_without_pressure_data_fails_but_plot_all_skips():
    """A direct `plot pressure` needs Press or Pxx/Pyy/Pzz; plot all skips it visibly."""
    _util.require_numpy()
    _util.require(_util_has('matplotlib'), 'matplotlib not installed')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shell = _shell(root, dump=False, log=False)
        message = _fails(shell, 'plot pressure')
        assert 'pressure' in message.lower()
        assert not (root / 'out' / 'pressure.png').exists()
        out = _ok(shell, 'plot all')
        assert 'skip' in out.lower() and 'pressure' in out.lower(), out
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shell = _shell(root, dump=False, log=True)
        _ok(shell, 'plot pressure')
        assert any(p.name.startswith('pressure') for p in (root / 'out').glob('*.png'))


def test_batch_cli_exit_code_for_failed_export():
    """The real batch CLI exits nonzero when an export request has no data."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dump = root / 't.dump'
        _write_dump(dump)
        script = root / 'cmds'
        script.write_text('export csv missing\n')
        home = root / 'home'
        home.mkdir()
        proc = subprocess.run(
            [sys.executable, '-m', 'lammpkeeper', 'post', '--dump', str(dump),
             '--output', str(root / 'out'), '--batch', str(script)],
            cwd=_util.REPO_ROOT, text=True, capture_output=True, stdin=subprocess.DEVNULL,
            env=dict(os.environ, HOME=str(home), LKPR_NO_HISTORY='1',
                     PYTHONPATH=_util.REPO_ROOT, MPLBACKEND='Agg'), timeout=120)
        assert proc.returncode == 1, proc.stdout + proc.stderr
        assert not (root / 'out' / 'missing.csv').exists()


def _util_has(module):
    """True if `module` imports (optional dependency probe)."""
    try:
        __import__(module)
        return True
    except ImportError:
        return False
