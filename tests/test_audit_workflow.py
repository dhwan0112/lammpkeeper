"""AUDIT-20261027 shell/state regressions; synthetic inputs, NumPy only.

Plot backends are mocked: these test dispatch, provenance, and numerical
selection, not rendering or real LAMMPS/HPC execution.
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

import _util  # noqa: F401 (repository path bootstrap)
import numpy as np

from lammps_post.shell import LammpsPostShell
import lammps_post.shell as shell_module


def _quiet(call):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        result = call()
    return result, out.getvalue()


def _dump(path, zs=(10, 30, 50)):
    rows = [[i + 1, i + 1, i + 1, 1, z] for i, z in enumerate(zs)]
    text = ''
    for step in (0, 100):
        moved = [r[:] for r in rows]
        if step:
            moved[0][2] += 1
            if len(moved) > 1:
                moved[1][2] += 3
        text += ('ITEM: TIMESTEP\n%d\nITEM: NUMBER OF ATOMS\n%d\n'
                 'ITEM: BOX BOUNDS pp pp ff\n0 100\n0 100\n0 100\n'
                 'ITEM: ATOMS id type x y z\n%s\n' %
                 (step, len(moved), '\n'.join(' '.join(map(str, r)) for r in moved)))
    path.write_text(text)


def _input(path, elements='Fe Mn O'):
    path.write_text('units metal\nboundary p p f\natom_style atomic\n'
                    'pair_style pace\npair_coeff * * test.yace %s\n'
                    'timestep 0.002\n' % elements)


def _shell(directory):
    shell = LammpsPostShell()
    shell.state.output_dir = str(directory / 'plots')
    return shell


def _load(shell, kind, path, extra=''):
    return _quiet(lambda: shell.do_load(f'{kind} {shlex.quote(str(path))}{extra}'))


def _cli(args):
    return subprocess.run([sys.executable, *args], input='', text=True,
                          capture_output=True, timeout=30,
                          env=dict(os.environ, LKPR_NO_HISTORY='1',
                                   PYTHONDONTWRITEBYTECODE='1'))


def test_audit_input_preserves_canonical_spin_union_and_invalidates_time():
    with tempfile.TemporaryDirectory(prefix='lk-workflow-') as temp:
        root = Path(temp)
        _dump(root / 'traj.dump')
        _input(root / 'run.in')
        shell = _shell(root)
        _load(shell, 'dump', root / 'traj.dump')
        _quiet(lambda: shell._analyze_msd(['--species', 'Fe'], _batch=True))
        _load(shell, 'input', root / 'run.in')
        assert 'msd_Fe' not in shell.state.cache
        assert shell.state.atom_types == {1: 'Fe_up', 2: 'Fe_down', 3: 'O'}
        _quiet(lambda: shell._analyze_msd(['--species', 'Fe'], _batch=True))
        np.testing.assert_allclose(shell.state.cache['msd_Fe']['msd'], [0, 5])
        np.testing.assert_allclose(shell.state.cache['msd_Fe']['time'], [0, 0.2])
        _quiet(lambda: shell.do_set('forcefield reaxff'))
        assert not shell.state.cache


def test_audit_surface_mapping_applies_in_both_load_orders():
    with tempfile.TemporaryDirectory(prefix='lk-workflow-') as temp:
        root = Path(temp)
        _dump(root / 'traj.dump')
        _input(root / 'run.in', 'O O Fe')
        for order in (('input', 'dump'), ('dump', 'input')):
            shell = _shell(root)
            for kind in order:
                _load(shell, kind, root / ('run.in' if kind == 'input' else 'traj.dump'))
            assert np.isclose(shell.state.surface_z, 48.6)
            _quiet(lambda: shell.do_set('types 1=Fe 2=O 3=O'))
            assert np.isclose(shell.state.surface_z, 8.6)


def test_audit_structure_cache_replacement_and_unload():
    with tempfile.TemporaryDirectory(prefix='lk-workflow-') as temp:
        root = Path(temp)
        _dump(root / 'a.dump')
        _dump(root / 'b.dump', (80, 90))
        shell = _shell(root)
        _load(shell, 'dump', root / 'a.dump')
        _quiet(lambda: shell._analyze_structure([]))
        _load(shell, 'dump', root / 'b.dump')
        with patch.object(shell_module, 'plot_structure') as plot:
            _quiet(lambda: shell._iplot_structure([], _batch=True))
            np.testing.assert_allclose(plot.call_args.args[0][:, 4], [80, 90])
        _quiet(lambda: shell.do_unload('all'))
        with patch.object(shell_module, 'plot_structure') as plot:
            _quiet(lambda: shell._iplot_structure([], _batch=True))
            assert not plot.called


def test_audit_density_union_and_malformed_flags():
    with tempfile.TemporaryDirectory(prefix='lk-workflow-') as temp:
        root = Path(temp)
        _dump(root / 'traj.dump')
        shell = _shell(root)
        _load(shell, 'dump', root / 'traj.dump')
        _quiet(lambda: shell.do_set('types 1=A 2=A 3=B'))
        _quiet(lambda: shell._analyze_density(['--species', 'A'], _batch=True))
        density = shell.state.cache['density_A']
        count = np.sum(density['density']) * np.diff(density['z'])[0] * 100 * 100
        assert np.isclose(count, 2), count
        for opts in (['--species'], ['--speceis', 'A'],
                     ['--species', 'A', '--typo'], ['--species', 'missing']):
            shell.state.clear_cache()
            try:
                _quiet(lambda: shell._analyze_density(opts, _batch=True))
            except ValueError:
                pass
            else:
                raise AssertionError(f'accepted malformed selection {opts}')
            assert not shell.state.cache


def test_audit_oxygen_union_reaches_all_dependent_calls():
    with tempfile.TemporaryDirectory(prefix='lk-workflow-') as temp:
        root = Path(temp)
        _dump(root / 'traj.dump')
        shell = _shell(root)
        _load(shell, 'dump', root / 'traj.dump')
        _quiet(lambda: shell.do_set('types 1=Fe 2=O 3=O'))
        _quiet(lambda: shell.do_set('surface_z 90'))
        _quiet(lambda: shell._analyze_oar([]))
        np.testing.assert_allclose(shell.state.cache['oar']['n_absorbed'], [2, 2])
        calls = [('_analyze_penetration', 'analyze_penetration'),
                 ('_analyze_penetration_trend', 'analyze_penetration_trend'),
                 ('_analyze_dissociation', 'detect_o2_dissociation'),
                 ('_iplot_penetration_profile', 'analyze_penetration_profile')]
        for method, function in calls:
            with patch.object(shell_module, function, side_effect=ValueError('sentinel')) as calc:
                try:
                    _quiet(lambda: getattr(shell, method)([]))
                except ValueError as exc:
                    assert str(exc) == 'sentinel'
                assert set(calc.call_args.kwargs['o_type']) == {2, 3}


def test_audit_surface_species_union_reaches_charge_and_profile_calls():
    with tempfile.TemporaryDirectory(prefix='lk-workflow-') as temp:
        root = Path(temp)
        _dump(root / 'traj.dump')
        shell = _shell(root)
        _load(shell, 'dump', root / 'traj.dump')
        shell.state.ff_info['has_charge'] = True
        for method, function, args in (
                ('_analyze_charge', 'analyze_charge_evolution', []),
                ('_analyze_charge_z', 'analyze_charge_z', ['0']),
                ('_analyze_or', 'compute_or', []),
                ('_iplot_penetration_profile', 'analyze_penetration_profile', [])):
            with patch.object(shell_module, function, side_effect=ValueError('sentinel')) as calc:
                try:
                    _quiet(lambda: getattr(shell, method)(args))
                except ValueError as exc:
                    assert str(exc) == 'sentinel'
                assert set(calc.call_args.kwargs['fe_type']) == {1, 2}


def test_audit_cli_errors_spaces_and_batch_quit():
    with tempfile.TemporaryDirectory(prefix='lk workflow ') as temp:
        root = Path(temp)
        _dump(root / 'with space.dump')
        for args in (['-m', 'lammps_post', '--dump', str(root / 'absent.dump'), '--analyze', 'all'],
                     ['-m', 'lammpkeeper', 'post', '--analyze', 'nonsense'],
                     ['-m', 'lammps_post', '--plot', 'nonsense']):
            proc = _cli(args)
            assert proc.returncode != 0, proc.stdout
        proc = _cli(['-m', 'lammps_post', '--dump', str(root / 'with space.dump'),
                     '--analyze', 'structure', '--output', str(root / 'output')])
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert 'File not found' not in proc.stdout
        batch = root / 'commands.txt'
        batch.write_text('nonsense\nquit\nset dt 7\ninfo\n')
        proc = _cli(['-m', 'lammpkeeper', 'post', '--batch', str(batch)])
        assert proc.returncode != 0
        assert 'Timestep: 7.0 fs' not in proc.stdout
        batch.write_text('quit\nnonsense\n')
        assert _cli(['-m', 'lammps_post', '--batch', str(batch)]).returncode == 0


def test_audit_shared_failures_do_not_claim_complete():
    with tempfile.TemporaryDirectory(prefix='lk-workflow-') as temp:
        root = Path(temp)
        _dump(root / 'traj.dump')
        shell = _shell(root)
        _load(shell, 'dump', root / 'traj.dump', ' --cache-mb 0')
        out = io.StringIO()
        with patch.object(shell, '_analyze_rdf', side_effect=RuntimeError('synthetic failure')), \
                patch.object(shell, '_dump_jobs_after_rdf', return_value=[]), \
                contextlib.redirect_stdout(out):
            try:
                shell._analyze_all()
            except RuntimeError:
                pass
            else:
                raise AssertionError('shared job failure did not propagate')
        assert 'All analyses complete' not in out.getvalue()


def test_audit_noninteractive_plot_uses_defaults_without_input():
    with tempfile.TemporaryDirectory(prefix='lk-workflow-') as temp:
        root = Path(temp)
        _dump(root / 'traj.dump')
        shell = _shell(root)
        shell.noninteractive = True
        _load(shell, 'dump', root / 'traj.dump')
        _quiet(lambda: shell._analyze_msd(['--species', 'Fe'], _batch=True))
        with patch.object(shell_module, 'plot_msd') as plot, \
                patch('builtins.input', side_effect=AssertionError('prompted')):
            _quiet(lambda: shell.do_plot('msd'))
            assert plot.called


def test_audit_one_shot_plot_runs_without_prompts_even_on_a_tty():
    from lammps_post.cli import main
    with tempfile.TemporaryDirectory(prefix='lk-workflow-') as temp:
        root = Path(temp)
        _dump(root / 'with space.dump')
        with patch('sys.stdin.isatty', return_value=True), \
                patch('builtins.input', side_effect=AssertionError('prompted')), \
                patch.object(shell_module, 'plot_msd') as plot:
            _quiet(lambda: main(['--dump', str(root / 'with space.dump'),
                                 '--plot', 'msd', '--output', str(root / 'output')]))
            assert plot.called


def test_audit_pressure_dispatch_uses_units_and_box_height():
    with tempfile.TemporaryDirectory(prefix='lk-workflow-') as temp:
        root = Path(temp)
        _dump(root / 'traj.dump')
        shell = _shell(root)
        _load(shell, 'dump', root / 'traj.dump')
        shell.state.log_data = {'step': np.array([0]), 'press': np.array([1.])}
        shell.state.ff_info['unit_system'] = 'real'
        shell.state.plot_recipes['pressure'] = {'slab_z_range': (0, 50)}
        for name, backend in (('thermo', 'plot_thermo'),
                              ('thermostat', 'plot_thermostat_summary'),
                              ('pressure', 'plot_pressure')):
            with patch.object(shell_module, backend) as plot:
                _quiet(lambda: getattr(shell, f'_iplot_{name}')([], _batch=True))
                assert plot.call_args.kwargs['unit_system'] == 'real'
                if name == 'pressure':
                    np.testing.assert_allclose(plot.call_args.args[0]['lz'], [100])
                    assert plot.call_args.kwargs['slab_z_range'] == (0, 50)


def test_audit_unload_input_discards_cache_and_restores_dump_metadata():
    with tempfile.TemporaryDirectory(prefix='lk-workflow-') as temp:
        root = Path(temp)
        _dump(root / 'traj.dump')
        _input(root / 'run.in', 'O O Fe')
        shell = _shell(root)
        _load(shell, 'dump', root / 'traj.dump')
        original = dict(shell.state.atom_types)
        original_surface = shell.state.surface_z
        _load(shell, 'input', root / 'run.in')
        shell.state.cache['sentinel'] = object()
        _quiet(lambda: shell.do_unload('input'))
        assert not shell.state.cache
        assert shell.state.atom_types == original
        assert shell.state.surface_z == original_surface
        _quiet(lambda: shell.do_set('surface_z 77'))
        _quiet(lambda: shell.do_set('types 1=Fe 2=O 3=O'))
        assert shell.state.surface_z == 77  # Explicit manual geometry wins.


def test_audit_log_data_provenance_invalidates_performance_mass_and_box():
    with tempfile.TemporaryDirectory(prefix='lk-workflow-') as temp:
        root = Path(temp)
        shell = _shell(root)
        for name, seconds in (('a', 10), ('b', 90)):
            path = root / f'{name}.log'
            path.write_text('LAMMPS (test)\nStep Temp PotEng\n0 300 -1\n100 300 -2\n'
                            f'Loop time of {seconds} on 1 procs for 100 steps with 2 atoms\n')
            _load(shell, 'log', path)
            assert 'performance' not in shell.state.cache
            _quiet(lambda: shell._analyze_performance([]))
            assert sum(shell.state.cache['performance'].values()) == seconds
        _quiet(lambda: shell.do_unload('log'))
        assert 'performance' not in shell.state.cache
        for name, masses, z in (('a', 'Masses\n\n1 10\n2 20\n\n', 10),
                                ('b', '', 80)):
            path = root / f'{name}.data'
            path.write_text('LAMMPS data\n\n2 atoms\n2 atom types\n\n'
                            '0 100 xlo xhi\n0 100 ylo yhi\n0 100 zlo zhi\n\n' + masses +
                            f'Atoms # atomic\n\n1 1 1 1 {z}\n2 2 2 2 {z+1}\n')
            _load(shell, 'data', path)
            assert shell.state.total_mass_amu == (30 if masses else None)
            _quiet(lambda: shell._analyze_structure([]))
            np.testing.assert_allclose(shell.state._structure_atoms[:, 4], [z, z + 1])
        _quiet(lambda: shell.do_unload('data'))
        assert shell.state.data_box is None
        assert shell.state.data_masses is None
        assert shell.state.total_mass_amu is None
