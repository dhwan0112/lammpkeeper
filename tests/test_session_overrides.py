"""REV-SESSION-1: physical shell overrides must be finite and valid before publication."""
import contextlib
import io
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

import _util


def _dump(path):
    """Write two frames of a 4-atom slab with an explicit Fe/Fe/O type layout."""
    text = ''
    for step in (0, 100):
        rows = ['1 1 1 1 10', '2 1 2 1 10', f'3 2 {3 + (step > 0)} 1 10', '4 3 4 1 12']
        text += (f'ITEM: TIMESTEP\n{step}\nITEM: NUMBER OF ATOMS\n4\n'
                 'ITEM: BOX BOUNDS pp pp ff\n0 100\n0 100\n0 100\n'
                 'ITEM: ATOMS id type x y z\n' + '\n'.join(rows) + '\n')
    path.write_text(text)


def _loaded_shell(tmp):
    """Return a noninteractive shell with the synthetic dump loaded."""
    from lammps_post.shell import LammpsPostShell
    path = Path(tmp) / 'traj.dump'
    _dump(path)
    shell = LammpsPostShell()
    shell.noninteractive = True
    shell.state.output_dir = str(Path(tmp) / 'out')
    with contextlib.redirect_stdout(io.StringIO()):
        shell.do_load(f'dump {shlex.quote(str(path))}')
    return shell


def _run(shell, command):
    """Run one shell command with stdout captured; return the captured text."""
    with contextlib.redirect_stdout(io.StringIO()) as out:
        shell.onecmd(command)
    return out.getvalue()


def test_invalid_surface_and_dt_are_rejected_without_state_change():
    """Bad values fail the command and leave value, manual flag and caches intact."""
    _util.require_numpy()
    cases = [('surface_z nan', 'surface_z'), ('surface_z inf', 'surface_z'),
             ('surface_z -inf', 'surface_z'), ('dt nan', 'dt'), ('dt inf', 'dt'),
             ('dt -1', 'dt'), ('dt 0', 'dt'), ('dt -0.0', 'dt')]
    for setting, key in cases:
        with tempfile.TemporaryDirectory() as tmp:
            shell = _loaded_shell(tmp)
            state = shell.state
            # Establish a previous valid manual value so "unchanged" is observable.
            _run(shell, 'set surface_z 7.5')
            _run(shell, 'set dt 2.0')
            cached = object()
            state.cache['sentinel'] = cached
            before = (state.surface_z, state.surface_z_manual, state.dt_fs)
            failures = shell.command_failures
            _run(shell, 'set ' + setting)
            assert shell.last_command_ok is False, setting
            assert shell.command_failures == failures + 1, setting
            assert (state.surface_z, state.surface_z_manual, state.dt_fs) == before, setting
            assert state.cache.get('sentinel') is cached, setting
            assert before[0] == 7.5 and before[2] == 2.0


def test_invalid_override_does_not_produce_analysis_results():
    """After a rejected override, analyses use the earlier valid surface and timestep."""
    _util.require_numpy()
    import numpy as np
    with tempfile.TemporaryDirectory() as tmp:
        shell = _loaded_shell(tmp)
        _run(shell, 'set surface_z 11.0')
        _run(shell, 'set dt 0.5')
        _run(shell, 'set surface_z nan')
        _run(shell, 'set dt -1')
        _run(shell, 'analyze msd --species Fe')
        time = np.asarray(shell.state.cache['msd_Fe']['time'], dtype=float)
        # Frames are 100 steps apart: 100 * 0.5 fs = 50 fs = 0.05 ps.
        assert np.allclose(time, [0.0, 0.05]), time


def test_valid_overrides_still_work():
    """Finite surface planes (any sign) and positive timesteps behave as before."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        shell = _loaded_shell(tmp)
        for value in ('0', '-3.5', '11.25'):
            _run(shell, 'set surface_z ' + value)
            assert shell.last_command_ok is True
            assert shell.state.surface_z == float(value)
            assert shell.state.surface_z_manual is True
        _run(shell, 'set dt 0.25')
        assert shell.last_command_ok is True and shell.state.dt_fs == 0.25


def test_invalid_mass_is_rejected():
    """Total mass must be finite and positive; a rejected value keeps the old one."""
    _util.require_numpy()
    for bad in ('nan', 'inf', '0', '-5'):
        with tempfile.TemporaryDirectory() as tmp:
            shell = _loaded_shell(tmp)
            _run(shell, 'set mass 100.0')
            _run(shell, 'set mass ' + bad)
            assert shell.last_command_ok is False, bad
            assert shell.state.total_mass_amu == 100.0, bad


def test_interactive_surface_prompt_rejects_nonfinite():
    """The surface prompt path applies the same finite check as `set surface_z`."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        shell = _loaded_shell(tmp)
        shell.state.surface_z = None
        shell._ask = lambda *a, **k: 'nan'
        with contextlib.redirect_stdout(io.StringIO()):
            ok = shell._require_surface_z()
        assert ok is False
        assert shell.state.surface_z is None
        assert not shell.state.surface_z_manual


def test_batch_cli_exits_nonzero_for_invalid_override():
    """A real batch subprocess reports a rejected physical override as failure."""
    _util.require_numpy()
    for line in ('set surface_z nan', 'set dt -1'):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'traj.dump'
            _dump(path)
            commands = root / 'commands.txt'
            commands.write_text(line + '\n')
            home = root / 'home'
            home.mkdir()
            result = subprocess.run(
                [sys.executable, '-m', 'lammpkeeper', 'post', '--dump', str(path),
                 '--batch', str(commands), '--output', str(root / 'out')],
                cwd=_util.REPO_ROOT,
                env=dict(os.environ, HOME=str(home), LKPR_NO_HISTORY='1',
                         PYTHONPATH=_util.REPO_ROOT),
                input='', text=True, capture_output=True, timeout=60)
            assert result.returncode != 0, (line, result.stdout + result.stderr)
