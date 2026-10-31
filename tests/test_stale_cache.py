"""REV-SESSION-3: cached results must not be published after the dump changed."""
import contextlib
import io
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

import _util


def _write_dump(path, last_x):
    """Write a 2-frame dump: one Fe atom, x 1 -> last_x (type 1, id 1).

    Analytic MSD of that atom: [0, (last_x - 1)**2]; last_x=2 gives 1,
    last_x=12 gives 121 (the changed file). Two atoms would only dilute it.
    """
    text = ''
    for step, x in ((0, 1.0), (100, last_x)):
        text += ('ITEM: TIMESTEP\n%d\nITEM: NUMBER OF ATOMS\n1\n'
                 'ITEM: BOX BOUNDS pp pp pp\n0 100\n0 100\n0 100\n'
                 'ITEM: ATOMS id type x y z\n1 1 %s 1 1\n' % (step, x))
    path.write_text(text)


def _shell(tmp):
    """Load the original dump (MSD 1) and analyze Fe MSD; return (shell, dump path)."""
    from lammps_post.shell import LammpsPostShell
    root = Path(tmp)
    dump = root / 't.dump'
    _write_dump(dump, 2.0)
    shell = LammpsPostShell()
    shell.noninteractive = True
    shell.state.output_dir = str(root / 'out')
    with contextlib.redirect_stdout(io.StringIO()):
        shell.onecmd('load dump %s' % shlex.quote(str(dump)))
        shell.onecmd('set types 1=Fe')
        shell.onecmd('analyze msd --species Fe')
    assert shell.last_command_ok is True
    assert 'msd_Fe' in shell.state.cache
    return shell, dump


def _outputs(tmp):
    """List files written under the session output directory."""
    out = Path(tmp) / 'out'
    return sorted(p.name for p in out.glob('*')) if out.exists() else []


def _run(shell, command):
    """Run one command, returning captured stdout."""
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        shell.onecmd(command)
    return buf.getvalue()


def test_unchanged_source_plot_and_export_still_work():
    """Without a source change the cached MSD is plotted and exported as before."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        shell, _ = _shell(tmp)
        text = _run(shell, 'export csv msd_Fe')
        assert shell.last_command_ok is True, text
        names = _outputs(tmp)
        assert any(n.endswith('.csv') for n in names), (names, text)
        assert 'msd_Fe' in shell.state.cache
        assert abs(float(shell.state.cache['msd_Fe']['msd'][-1]) - 1.0) < 1e-9
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            _util.skip('matplotlib missing: Agg plot save not exercised')
            return
        text = _run(shell, 'plot msd Fe')
        assert shell.last_command_ok is True, text
        assert any(n.endswith('.png') for n in _outputs(tmp)), text


def test_changed_source_plot_is_rejected_and_writes_nothing():
    """A rewritten dump (true MSD 121) must not yield the cached MSD 1 as a PNG."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        shell, dump = _shell(tmp)
        before = _outputs(tmp)
        _write_dump(dump, 12.0)
        text = _run(shell, 'plot msd Fe')
        assert shell.last_command_ok is False, text
        assert 'reload' in text, text
        assert _outputs(tmp) == before, _outputs(tmp)
        assert not shell.state.cache, list(shell.state.cache)
        # A retry cannot resurrect the old curve either.
        _run(shell, 'plot msd Fe')
        assert _outputs(tmp) == before


def test_changed_source_export_is_rejected_and_writes_nothing():
    """Export csv/latex/summary refuse stale caches and create no file."""
    _util.require_numpy()
    for command in ('export csv msd_Fe', 'export latex msd_Fe', 'export summary summary'):
        with tempfile.TemporaryDirectory() as tmp:
            shell, dump = _shell(tmp)
            before = _outputs(tmp)
            _write_dump(dump, 12.0)
            text = _run(shell, command)
            assert shell.last_command_ok is False, (command, text)
            assert _outputs(tmp) == before, (command, _outputs(tmp))
            assert not shell.state.cache


def test_deleted_source_is_rejected():
    """A removed dump behaves like a changed one: loud failure, no artifact."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        shell, dump = _shell(tmp)
        before = _outputs(tmp)
        dump.unlink()
        text = _run(shell, 'plot msd Fe')
        assert shell.last_command_ok is False, text
        assert 'reload' in text, text
        assert _outputs(tmp) == before
        assert not shell.state.cache


def test_reload_after_change_gives_fresh_result():
    """After the documented remedy (reload) MSD is the new analytic 121."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        shell, dump = _shell(tmp)
        _write_dump(dump, 12.0)
        _run(shell, 'plot msd Fe')
        _run(shell, 'load dump %s' % shlex.quote(str(dump)))
        _run(shell, 'set types 1=Fe')
        _run(shell, 'analyze msd --species Fe')
        assert shell.last_command_ok is True
        assert abs(float(shell.state.cache['msd_Fe']['msd'][-1]) - 121.0) < 1e-9


def test_ensure_cache_checks_source_before_reuse():
    """The shared cache gate rejects stale data before key-presence reuse."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        shell, dump = _shell(tmp)
        _write_dump(dump, 12.0)
        try:
            shell._ensure_cache('msd', '_analyze_msd')
        except ValueError as exc:
            assert 'reload' in str(exc)
        else:
            raise AssertionError('stale cache was reused')
        assert not shell.state.cache


def test_batch_cli_exit_code_for_changed_source():
    """The real batch CLI exits nonzero when the dump changes between analysis and plot.

    The batch script is a FIFO so the test can rewrite the dump after the
    analysis finished (observed on stdout) and before the plot line is sent.
    """
    _util.require_numpy()
    _util.require(hasattr(os, 'mkfifo'), 'os.mkfifo unavailable')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dump = root / 't.dump'
        _write_dump(dump, 2.0)
        fifo = root / 'script.fifo'
        os.mkfifo(str(fifo))
        home = root / 'home'
        home.mkdir()
        proc = subprocess.Popen(
            [sys.executable, '-m', 'lammpkeeper', 'post', '--dump', str(dump),
             '--output', str(root / 'out'), '--batch', str(fifo)],
            cwd=_util.REPO_ROOT, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=dict(os.environ, HOME=str(home), LKPR_NO_HISTORY='1',
                     PYTHONPATH=_util.REPO_ROOT, MPLBACKEND='Agg',
                     PYTHONUNBUFFERED='1'))
        try:
            with open(str(fifo), 'w') as script:
                script.write('set types 1=Fe\nanalyze msd --species Fe\n')
                script.flush()
                seen = ''
                # Wait until the analysis has really finished before mutating.
                while 'Final MSD' not in seen:
                    line = proc.stdout.readline()
                    assert line, 'CLI ended before analysis finished: ' + seen
                    seen += line
                _write_dump(dump, 12.0)
                script.write('plot msd Fe\nquit\n')
                script.flush()
            rest = proc.communicate(timeout=60)[0]
        finally:
            if proc.poll() is None:
                proc.kill()
        assert proc.returncode == 1, seen + rest
        assert 'reload' in rest, rest
        assert not list((root / 'out').glob('*.png'))
