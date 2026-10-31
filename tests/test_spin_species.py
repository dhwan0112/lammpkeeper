"""REV-SESSION-2: spin analysis must agree with the active species selections."""
import contextlib
import io
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

import _util

_INPUT = ('units metal\nboundary p p f\natom_style atomic\npair_style pace\n'
          'pair_coeff * * fake.yace Fe Mn O\ntimestep 0.001\n')


def _dump(path):
    """Write two frames with independent counts: type 1 x2, type 2 x1, type 3 x1."""
    text = ''
    for step in (0, 100):
        rows = ['1 1 1 1 10', '2 1 2 1 10', '3 2 3 1 10', '4 3 4 1 12']
        text += ('ITEM: TIMESTEP\n%d\nITEM: NUMBER OF ATOMS\n4\n'
                 'ITEM: BOX BOUNDS pp pp ff\n0 100\n0 100\n0 100\n'
                 'ITEM: ATOMS id type x y z\n' % step) + '\n'.join(rows) + '\n'
    path.write_text(text)


def _shell(tmp, command=None):
    """Load the synthetic dump under explicit canonical ACE input metadata."""
    from lammps_post.shell import LammpsPostShell
    root = Path(tmp)
    _dump(root / 't.dump')
    (root / 'a.in').write_text(_INPUT)
    shell = LammpsPostShell()
    shell.noninteractive = True
    shell.state.output_dir = str(root / 'out')
    with contextlib.redirect_stdout(io.StringIO()):
        shell.onecmd('load dump %s' % shlex.quote(str(root / 't.dump')))
        shell.onecmd('load input %s' % shlex.quote(str(root / 'a.in')))
        if command:
            shell.onecmd(command)
    return shell


def test_swapped_override_is_rejected_without_cache_entry():
    """A manual Fe_up/Fe_down swap must fail loudly, naming selections and slots."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        shell = _shell(tmp, 'set types 1=Fe_down 2=Fe_up 3=O')
        assert shell.state.species_map.resolve('Fe_up') == frozenset({2})
        with contextlib.redirect_stdout(io.StringIO()) as out:
            shell.onecmd('analyze spin')
        text = out.getvalue()
        assert 'spin' not in shell.state.cache, text
        assert shell.last_command_ok is False
        assert shell.command_failures == 1
        for needle in ('Fe_up', 'Fe_down', 'canonical'):
            assert needle in text, text


def test_rejection_drops_stale_spin_result_and_plot_does_not_reuse_it():
    """A failed retry must not leave an older spin curve for plotting."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        shell = _shell(tmp, 'analyze spin')
        assert 'spin' in shell.state.cache
        with contextlib.redirect_stdout(io.StringIO()):
            shell.onecmd('set types 1=Fe_down 2=Fe_up 3=O')
        # The species change itself already clears the numerical cache.
        assert 'spin' not in shell.state.cache
        shell.state.cache['spin'] = object()
        with contextlib.redirect_stdout(io.StringIO()):
            shell.onecmd('analyze spin')
        assert 'spin' not in shell.state.cache
        assert not (Path(tmp) / 'out').exists() or not list((Path(tmp) / 'out').glob('spin*'))


def test_canonical_session_counts_are_independent_and_unchanged():
    """Canonical ACE labels give hand-counted populations: up 2, down 1, O 1."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        shell = _shell(tmp, 'analyze spin')
        result = shell.state.cache['spin']
        assert result['n_up'].tolist() == [2, 2]
        assert result['n_down'].tolist() == [1, 1]
        assert result['n_o'].tolist() == [1, 1]
        assert abs(float(result['up_fraction'][-1]) - 2 / 3) < 1e-12
        assert shell.last_command_ok is True


def test_idempotent_canonical_override_is_accepted():
    """Declaring the canonical labels explicitly is not a deviation."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        shell = _shell(tmp, 'set types 1=Fe_up 2=Fe_down 3=O')
        with contextlib.redirect_stdout(io.StringIO()):
            shell.onecmd('analyze spin')
        assert shell.state.cache['spin']['n_up'].tolist() == [2, 2]


def test_missing_spin_labels_are_rejected():
    """An override without Fe_up/Fe_down labels cannot be analyzed as spin."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        shell = _shell(tmp, 'set types 1=Fe 2=Fe 3=O')
        with contextlib.redirect_stdout(io.StringIO()) as out:
            shell.onecmd('analyze spin')
        assert 'spin' not in shell.state.cache
        assert shell.last_command_ok is False
        assert 'canonical' in out.getvalue()


def test_fixture_session_result_matches_kernel_directly():
    """The committed ACE fixture gives the same arrays through shell and kernel."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_spin_evolution
    from lammps_post.shell import LammpsPostShell
    fixture = os.path.join(_util.REPO_ROOT, 'tests', 'fixtures', 'ace_examples',
                           'regular_MD', 'traj.dump')
    shell = LammpsPostShell()
    shell.noninteractive = True
    with tempfile.TemporaryDirectory() as tmp:
        shell.state.output_dir = tmp
        with contextlib.redirect_stdout(io.StringIO()):
            shell.onecmd('load dump %s' % shlex.quote(fixture))
            shell.onecmd('set forcefield ace')
            shell.onecmd('analyze spin')
        assert shell.last_command_ok is True
        got = shell.state.cache['spin']
        want = analyze_spin_evolution(shell.state.dump_frames, shell.state.dump_col_idx,
                                      dt_fs=shell.state.dt_fs)
        for key in want:
            assert np.array_equal(got[key], want[key]), key
        assert got['n_up'][0] == 64 and got['n_down'][0] == 128


def test_analyze_all_skips_noncanonical_spin_visibly_and_keeps_canonical():
    """'analyze all' skips spin with a notice on a noncanonical map; canonical runs it.

    Found by the parent's full verifier: the TEST-3 slab reference (dump-only,
    labels Fe/O, guessed ACE) previously ran spin on fixed type channels, counting
    O as Fe_down. An explicit 'analyze spin' fails; the batch-wide command skips.
    """
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        # Plain Fe/O labels (as in the slab reference) keep the other analyses
        # meaningful while leaving no Fe_up/Fe_down selections for spin.
        shell = _shell(tmp, 'set types 1=Fe 2=Fe 3=O')
        with contextlib.redirect_stdout(io.StringIO()) as out:
            shell.onecmd('set surface_z 11')
            shell.onecmd('analyze all')
        text = out.getvalue()
        assert shell.last_command_ok is True, text
        assert 'spin' not in shell.state.cache, text
        assert 'Skipping spin' in text and 'canonical' in text, text
    with tempfile.TemporaryDirectory() as tmp:
        shell = _shell(tmp)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            shell.onecmd('set surface_z 11')
            shell.onecmd('analyze all')
        assert shell.last_command_ok is True, out.getvalue()
        assert shell.state.cache['spin']['n_up'].tolist() == [2, 2]


def _cli(tmp, extra):
    """Run the real one-shot/batch CLI with an isolated HOME."""
    root = Path(tmp)
    _dump(root / 't.dump')
    (root / 'a.in').write_text(_INPUT)
    home = root / 'home'
    home.mkdir(exist_ok=True)
    return subprocess.run(
        [sys.executable, '-m', 'lammpkeeper', 'post', '--dump', str(root / 't.dump'),
         '--output', str(root / 'out')] + extra,
        cwd=_util.REPO_ROOT, input='', text=True, capture_output=True, timeout=60,
        env=dict(os.environ, HOME=str(home), LKPR_NO_HISTORY='1',
                 PYTHONPATH=_util.REPO_ROOT, MPLBACKEND='Agg'))


def test_batch_cli_exit_codes_for_rejected_and_canonical():
    """Batch override swap exits nonzero; the same batch without it exits zero."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'bad.txt').write_text(
            'load input %s\nset types 1=Fe_down 2=Fe_up 3=O\nanalyze spin\nquit\n'
            % shlex.quote(str(root / 'a.in')))
        (root / 'good.txt').write_text(
            'load input %s\nanalyze spin\nquit\n' % shlex.quote(str(root / 'a.in')))
        _dump(root / 't.dump')
        (root / 'a.in').write_text(_INPUT)
        bad = _cli(tmp, ['--batch', str(root / 'bad.txt')])
        assert bad.returncode != 0, bad.stdout + bad.stderr
        assert 'canonical' in (bad.stdout + bad.stderr)
        good = _cli(tmp, ['--batch', str(root / 'good.txt')])
        assert good.returncode == 0, good.stdout + good.stderr
