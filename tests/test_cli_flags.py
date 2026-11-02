"""REV-UI-4: CLI style flags, --find and --batch fail visibly and exit nonzero.

Before this fix, bad `--dpi` values printed a traceback, `--dpi 0` was ignored,
an empty `--find` exited 0, presentation settings accepted NaN/inf/negatives,
and `--batch` with `--analyze`/`--plot` dropped the script silently.
"""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import _util

REPO = Path(__file__).resolve().parents[1]


def _cli(args, cwd, home):
    """Run `python -m lammpkeeper post ARGS` isolated; return CompletedProcess."""
    env = dict(os.environ, HOME=str(home), LKPR_NO_HISTORY='1', MPLBACKEND='Agg',
               PYTHONDONTWRITEBYTECODE='1',
               PYTHONPATH=str(REPO) + os.pathsep + os.environ.get('PYTHONPATH', ''))
    return subprocess.run([sys.executable, '-W', 'ignore', '-m', 'lammpkeeper', 'post'] + args,
                          cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=120)


def _shell():
    """A fresh noninteractive shell."""
    from lammps_post.shell import LammpsPostShell
    shell = LammpsPostShell()
    shell.noninteractive = True
    return shell


def _run(shell, command):
    """Run one command silently; return (ok, output)."""
    with contextlib.redirect_stdout(io.StringIO()) as out:
        shell.onecmd(command)
    return shell.last_command_ok, out.getvalue()


def test_bad_dpi_flag_exits_one_without_traceback():
    """--dpi 0 and --dpi -5 exit 1 with a clear message, not a traceback or silent 0."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        for value in ('0', '-5'):
            r = _cli(['--dpi', value, '--find', tmp], tmp, tmp)
            assert r.returncode == 1, (value, r.returncode, r.stdout, r.stderr)
            assert 'Traceback' not in r.stderr + r.stdout
            assert 'dpi' in r.stdout


def test_find_without_match_exits_one():
    """An explicit --find with no result fails for automation."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / 'empty'
        empty.mkdir()
        r = _cli(['--find', str(empty)], tmp, tmp)
        assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
        assert 'no LAMMPS files found' in r.stdout


def test_interactive_find_without_match_still_succeeds():
    """The shell command `find` keeps printing and does not count a failure."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        shell = _shell()
        ok, out = _run(shell, 'find %s' % tmp)
        assert ok and shell.command_failures == 0, out
        assert 'No LAMMPS files found' in out


def test_valid_style_flag_still_works():
    """A valid --dpi with --find on an empty directory reaches find (exit 1 only from find)."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        r = _cli(['--dpi', '120', '--find', tmp], tmp, tmp)
        assert 'must be' not in r.stdout and 'Traceback' not in r.stderr
        assert 'no LAMMPS files found' in r.stdout


def test_batch_with_one_shot_is_usage_error():
    """--batch plus --analyze/--plot exits 2 and runs nothing."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / 's.txt'
        script.write_text('help\n')
        for extra in (['--analyze'], ['--plot', 'thermo']):
            r = _cli(['--batch', str(script)] + extra, tmp, tmp)
            assert r.returncode == 2, (extra, r.returncode, r.stdout, r.stderr)
            assert '--batch cannot be combined' in r.stderr


def test_bad_presentation_values_rejected_without_state_change():
    """NaN, inf, negatives, zero, fractions, lo>=hi and extra tokens fail and keep old state."""
    _util.require_numpy()
    shell = _shell()
    s = shell.state
    before = (s.dpi, s.font_size, s.linewidth, s.marker_size, s.grid_alpha,
              s.z_focus, s.figsize_override, s.fig_width, s.fig_height)
    bad = ['dpi 0', 'dpi -1', 'dpi nan', 'dpi inf', 'dpi 1.5',
           'fontsize 0', 'fontsize -2', 'fontsize nan',
           'linewidth 0', 'linewidth -1', 'linewidth nan', 'linewidth inf',
           'markersize 0', 'markersize -3', 'markersize nan',
           'grid_alpha -0.1', 'grid_alpha 1.5', 'grid_alpha nan', 'grid_alpha inf',
           'figsize 0 5', 'figsize 5 -1', 'figsize nan 5', 'figsize 5 inf', 'figsize 4 5 6',
           'z_focus nan 5', 'z_focus 1 inf', 'z_focus 5 1', 'z_focus 3 3', 'z_focus 1 2 3']
    for command in bad:
        ok, out = _run(shell, 'set ' + command)
        assert ok is False, command
    after = (s.dpi, s.font_size, s.linewidth, s.marker_size, s.grid_alpha,
             s.z_focus, s.figsize_override, s.fig_width, s.fig_height)
    assert before == after, (before, after)
    assert shell.command_failures == len(bad)


def test_valid_presentation_values_accepted():
    """Ordinary values, including grid_alpha 0 and 1, still set."""
    _util.require_numpy()
    shell = _shell()
    for command in ('dpi 200', 'fontsize 12', 'linewidth 2.5', 'markersize 4',
                    'grid_alpha 0', 'grid_alpha 1', 'figsize 6 4', 'z_focus 1 9'):
        ok, out = _run(shell, 'set ' + command)
        assert ok, (command, out)
    s = shell.state
    assert (s.dpi, s.font_size, s.linewidth, s.marker_size) == (200, 12, 2.5, 4.0)
    assert s.grid_alpha == 1.0 and s.figsize_override == (6.0, 4.0) and s.z_focus == (1.0, 9.0)
