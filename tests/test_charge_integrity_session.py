"""REV-ANALYSIS-1: reject bad charges without publishing stale shell results."""
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


def _dump(path, charge):
    """Write two charged species with explicit labels and a finite slab box."""
    path.write_text(
        'ITEM: TIMESTEP\n10\nITEM: NUMBER OF ATOMS\n2\n'
        'ITEM: BOX BOUNDS pp pp ff\n0 10\n0 10\n0 10\n'
        'ITEM: ATOMS id type element x y z q\n'
        f'1 1 Fe 1 1 1 {charge}\n2 2 O 2 2 2 -0.9\n')


def test_failed_charge_retry_invalidates_only_affected_cache():
    """A failed retry cannot leave the previous charge result available to plot."""
    _util.require_numpy()
    from lammps_post.shell import LammpsPostShell
    for key, command in (('charge', 'charge'), ('charge_z', 'charge_z 0'), ('or', 'or')):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'charged.dump'
            _dump(path, 'nan')
            shell = LammpsPostShell()
            shell.state.output_dir = tmp
            with contextlib.redirect_stdout(io.StringIO()):
                shell.do_load(f'dump {shlex.quote(str(path))}')
            stale = object()
            unrelated = object()
            shell.state.cache[key] = stale
            shell.state.cache['unrelated'] = unrelated
            with contextlib.redirect_stdout(io.StringIO()) as output:
                shell.onecmd(f'analyze {command}')
            assert key not in shell.state.cache, (key, output.getvalue())
            assert shell.state.cache['unrelated'] is unrelated
            assert shell.last_command_ok is False
            assert shell.command_failures == 1
            assert 'nonfinite' in output.getvalue().lower(), output.getvalue()


def test_cancelled_charge_profile_keeps_previous_cache():
    """Cancelling frame selection is not a failed recomputation of old results."""
    _util.require_numpy()
    from lammps_post.shell import LammpsPostShell
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'charged.dump'
        _dump(path, '0.9')
        shell = LammpsPostShell()
        shell.state.output_dir = tmp
        with contextlib.redirect_stdout(io.StringIO()):
            shell.do_load(f'dump {shlex.quote(str(path))}')
        previous = object()
        shell.state.cache['charge_z'] = previous
        with patch.object(shell, '_ask', return_value=None) as ask:
            shell._analyze_charge_z([])
        ask.assert_called_once()
        assert shell.state.cache['charge_z'] is previous
        assert shell.command_failures == 0


def test_charge_cli_rejects_nonfinite_and_accepts_finite():
    """Real one-shot commands report selected bad charges as failure, not success."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        home = root / 'home'
        home.mkdir()
        path = root / 'charged.dump'
        for charge, success in (('0.9', True), ('nan', False), ('inf', False), ('-inf', False)):
            _dump(path, charge)
            for analysis in ('charge', 'charge_z', 'or'):
                env = dict(os.environ, HOME=str(home), LKPR_NO_HISTORY='1',
                           PYTHONPATH=_util.REPO_ROOT)
                result = subprocess.run(
                    [sys.executable, '-m', 'lammpkeeper', 'post', '--dump', str(path),
                     '--analyze', analysis, '--output', str(root / 'out')],
                    cwd=_util.REPO_ROOT, env=env, input='', text=True,
                    capture_output=True, timeout=30)
                output = result.stdout + result.stderr
                assert (result.returncode == 0) == success, (analysis, charge, output)
                if not success:
                    assert 'nonfinite' in output.lower(), output


def test_batch_success_after_bad_charge_does_not_hide_failure():
    """A later successful command cannot turn rejected charge input into exit zero."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        home = root / 'home'
        home.mkdir()
        path = root / 'charged.dump'
        _dump(path, 'nan')
        commands = root / 'commands.txt'
        commands.write_text('analyze or\ninfo\n')
        result = subprocess.run(
            [sys.executable, '-m', 'lammpkeeper', 'post', '--dump', str(path),
             '--batch', str(commands), '--output', str(root / 'out')],
            cwd=_util.REPO_ROOT,
            env=dict(os.environ, HOME=str(home), LKPR_NO_HISTORY='1',
                     PYTHONPATH=_util.REPO_ROOT),
            input='', text=True, capture_output=True, timeout=30)
        assert result.returncode != 0, result.stdout + result.stderr
        assert 'nonfinite' in (result.stdout + result.stderr).lower()
