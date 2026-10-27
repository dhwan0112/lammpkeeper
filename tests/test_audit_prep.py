"""AUDIT-20261027 prep regressions; no scheduler or real LAMMPS is run.

Only NumPy is needed for geometry checks; the two non-(100) slab checks
explicitly skip without ASE. Job scripts run with guarded local stubs.
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


def _state():
    from lammps_pre.state import PreState
    s = PreState()
    s.nx, s.ny, s.nz = 4, 4, 8
    s.n_fixed_layers, s.n_thermostat_layers = 1, 2
    s.n_o2 = 4
    return s


def _build(s):
    _util.require_numpy()
    from lammps_pre.builders import build_all
    with contextlib.redirect_stdout(io.StringIO()):
        return build_all(s)


def _rejects(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError('invalid configuration was accepted')


def test_odd_width_skew_slabs_are_rejected():
    _util.require_numpy()
    from lammps_pre import builders
    _util.require(builders.HAS_ASE, 'ase not installed')
    for surface in ('110', '111'):
        s = _state()
        s.surface, s.ny = surface, 3
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            result = builders.build_all(s)
        assert result is None, f'{surface}: unsupported tilt was discarded'
        assert s.build_result is None
        assert 'even' in log.getvalue().lower(), log.getvalue()


def test_even_width_surfaces_preserve_written_periodic_nearest_distance():
    _util.require_numpy()
    import numpy as np
    from lammps_pre import builders
    from lammps_pre.writers import write_data_file
    _util.require(builders.HAS_ASE, 'ase not installed')
    for surface in ('100', '110', '111'):
        s = _state()
        s.surface = surface
        b = _build(s)
        assert b is not None
        for ff in ('ace', 'reaxff2010', 'reaxff2015'):
            s.set_ff(ff)
            other = _build(s)
            assert np.array_equal(other.fe_positions, b.fe_positions)
            assert np.array_equal(other.o2_positions, b.o2_positions)
            assert other.box == b.box
        s.set_ff('reaxff2010')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'slab.data'
            with contextlib.redirect_stdout(io.StringIO()):
                write_data_file(b, s, path)
            rows = path.read_text().split('Atoms # charge\n\n')[1]
            xyz = np.loadtxt(io.StringIO(rows))[:len(b.fe_positions), 3:6]
        # Independent explicit lateral-image enumeration, not the builder MIC.
        delta = xyz[:, None, :] - xyz[None, :, :]
        minimum = np.full(delta.shape[:2], np.inf)
        for ix in range(-1, 2):
            for iy in range(-1, 2):
                shift = np.array([ix * b.box[1], iy * b.box[3], 0.0])
                minimum = np.minimum(minimum, np.sum((delta + shift) ** 2, axis=2))
        np.fill_diagonal(minimum, np.inf)
        assert abs(np.sqrt(minimum.min()) - np.sqrt(3) * s.a_fe / 2) < 2e-8


def test_geometry_mutation_invalidates_build_but_simulation_edits_do_not():
    for key, value in (('nx', 5), ('ny', 6), ('nz', 9), ('surface', '110'),
                       ('a_fe', 2.9), ('n_o2', 5), ('vacuum', 40.0),
                       ('seed', 7), ('o2_bond', 1.3), ('o2_separation', 3.5),
                       ('n_fixed_layers', 2), ('n_thermostat_layers', 3)):
        s = _state()
        b = _build(s)
        assert b is not None
        s.temperature = 800
        s.set_ff('ace')
        assert s.build_result is b, 'simulation/format changes must preserve geometry'
        setattr(s, key, value)
        assert s.build_result is None, f'{key}: stale geometry remains writable'


def test_old_build_cannot_be_written_under_changed_metadata():
    from lammps_pre.writers import write_data_file
    s = _state()
    b = _build(s)
    s.nx = 8
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'must-not-exist.data'
        _rejects(lambda: write_data_file(b, s, path))
        assert not path.exists()


def test_failed_rebuild_clears_previous_result():
    s = _state()
    assert _build(s) is not None
    s.vacuum = 3.0
    assert _build(s) is None
    assert s.build_result is None


def test_o2_incomplete_placement_is_failure_not_partial_success():
    s = _state()
    s.n_o2, s.o2_separation = 2, 1e6
    assert _build(s) is None
    assert s.build_result is None


def test_nonpositive_layers_are_rejected_before_geometry_generation():
    for fixed, nvt in ((0, 2), (1, 0), (1, -1), (-1, 2), (0, 0)):
        s = _state()
        s.n_fixed_layers, s.n_thermostat_layers = fixed, nvt
        assert _build(s) is None, f'unsupported layer counts accepted: {fixed}/{nvt}'
        assert s.build_result is None


def test_seeded_gas_axes_are_isotropic_and_repeatable():
    _util.require_numpy()
    import numpy as np
    from lammps_pre import builders
    s = _state()
    s.n_o2 = 1
    slab = {'cell': np.diag([20.0, 20.0, 20.0])}
    regions = {'z_wall_lower': 10.0}
    rng = np.random.default_rng(42)
    axes = []
    with patch.object(builders.np.random, 'default_rng', return_value=rng):
        for _ in range(6000):
            p = builders.place_o2(slab, regions, s)
            axes.append((p[0] - p[1]) / s.o2_bond)
    axes = np.asarray(axes)
    assert np.all(np.abs(np.mean(axes ** 2, axis=0) - 1 / 3) < .025)
    assert np.all(np.abs(np.mean(axes, axis=0)) < .03)
    first = builders.place_o2(slab, regions, s)
    assert np.array_equal(first, builders.place_o2(slab, regions, s))
    assert abs(np.linalg.norm(first[0] - first[1]) - s.o2_bond) < 1e-12


def test_ace_cpu_overrides_use_compatible_or_automatic_grid():
    from lammps_pre.templates import render_input_script, render_run_script
    s = _state()
    s.set_ff('ace')
    s.ncpus, s.nproc_x, s.nproc_y = 24, 4, 6
    text = render_input_script(None, s)
    assert 'NPROC_X  index 4' in text and 'NPROC_Y  index 6' in text
    assert 'ncpus=24:mpiprocs=24' in render_run_script(None, s)
    s.nproc_x = s.nproc_y = None
    text = render_input_script(None, s)
    assert 'NPROC_X  index *' in text and 'NPROC_Y  index *' in text
    s.nproc_x, s.nproc_y = 6, 8
    _rejects(lambda: render_input_script(None, s))
    _rejects(lambda: render_run_script(None, s))
    s.nproc_x, s.nproc_y = 4, None
    _rejects(lambda: render_input_script(None, s))
    s.ncpus = 0
    _rejects(lambda: render_run_script(None, s))


def test_ace_dense_stage_is_configured_clamped_and_exact_in_steps():
    from lammps_pre.templates import render_input_script
    s = _state()
    s.set_ff('ace')
    for ox, dense in ((12, 5), (12, 50), (0, 5), (12, 0), (.00075, .0005)):
        s.ox_ps, s.dump_dense_ps = ox, dense
        text = render_input_script(None, s)
        variables = {}
        for line in text.splitlines():
            parts = line.split()
            if parts and parts[0] == 'variable':
                variables[parts[1]] = parts[3]
        assert float(variables['DENSE_PS']) == dense
        # Evaluate only the numeric duration variables, including short OX_PS
        # supplied at runtime, independently of the generation-time duration.
        for runtime_ox in (ox, .00075, 0):
            env = {'OX_PS': runtime_ox, 'DENSE_PS': dense, 'dt': s.ff['dt']}
            for key in ('ox_steps', 'ox_dense', 'ox_remain'):
                expression = variables[key]
                for name, value in env.items():
                    expression = expression.replace('${' + name + '}', str(value))
                env[key] = eval(expression, {'__builtins__': {}},
                                {'round': round, 'max': max, 'min': min})
            assert env['ox_dense'] >= 0 and env['ox_remain'] >= 0
            assert env['ox_dense'] + env['ox_remain'] == round(runtime_ox / s.ff['dt'])
            assert env['ox_dense'] <= round(dense / s.ff['dt'])
    for value in (-1, float('nan'), float('inf')):
        s.dump_dense_ps = value
        _rejects(lambda: render_input_script(None, s))


@contextlib.contextmanager
def _edge_job(status=37, archive_kind='directory', work_mode=0o700):
    """Guard every cleanup command and substitute *all* cluster defaults."""
    from lammps_pre.templates import render_run_script
    from lammps_pre.writers import get_filenames
    with tempfile.TemporaryDirectory(prefix='lkpr_audit_prep_') as tmp:
        root = Path(tmp)
        work, home, bins = (root / p for p in ('work with spaces', 'home', 'bin'))
        for path in (work, home, bins):
            path.mkdir()
        work.chmod(work_mode)
        scratch = root / 'scratch with spaces'
        target = root / 'unrelated'
        target.mkdir()
        (target / 'trajectory.out').write_text('unrelated original\n')
        archive = work / 'failed_audit-job'
        if archive_kind == 'directory':
            archive.mkdir()
            (archive / 'trajectory.out').write_text('previous run\n')
        elif archive_kind == 'symlink':
            archive.symlink_to(target, target_is_directory=True)
        elif archive_kind == 'dangling':
            archive.symlink_to(root / 'missing', target_is_directory=True)
        s = _state()
        s.lammps_bin = str(bins / 'lmp')
        names = get_filenames(s)
        for filename in (names['input'], names['data'], names['regions'],
                         s.ff['potential_file']):
            (work / filename).write_text('synthetic input\n')
        scripts = {
            'module': 'exit 0\n',
            'lmp': 'echo "REAL EXECUTABLE MUST NOT RUN" >&2; exit 99\n',
            'mpirun': 'printf "new run\\n" > trajectory.out\n'
                      'printf "hidden\\n" > .hidden\nexit "$TEST_STATUS"\n',
            'rm': '[[ "${!#}" == "$LKPR_SCRATCH" ]] || exit 98\n'
                  'exec /bin/rm "$@"\n',
        }
        for name, body in scripts.items():
            path = bins / name
            path.write_text('#!/bin/bash\n' + body)
            path.chmod(0o755)
        rendered = render_run_script(None, s).replace(
            'source /etc/profile.d/modules.sh 2>/dev/null || true', ': # no site setup')
        rendered = rendered.replace('/hpctmp/$USER/$JOBID', str(root / 'unused-scratch'))
        path = root / 'run.sh'
        path.write_text(rendered)
        env = {'HOME': str(home), 'USER': 'audit-only',
               'PATH': f'{bins}:/usr/bin:/bin', 'PBS_O_WORKDIR': str(work),
               'PBS_JOBID': 'audit-job', 'LKPR_SCRATCH': str(scratch),
               'TEST_STATUS': str(status), 'LKPR_NO_HISTORY': '1',
               'PYTHONDONTWRITEBYTECODE': '1'}
        syntax = subprocess.run(['/bin/bash', '-n', str(path)], env=env,
                                capture_output=True, text=True, timeout=10)
        assert syntax.returncode == 0, syntax.stderr
        run = subprocess.run(['/bin/bash', '-c', 'umask 022; exec /bin/bash "$1"',
                              'test', str(path)], cwd=work, env=env,
                             capture_output=True, text=True, timeout=15)
        yield run, work, scratch, archive, target


def test_failure_archives_never_reuse_directories_or_follow_symlinks():
    for kind in ('directory', 'symlink', 'dangling'):
        with _edge_job(archive_kind=kind) as (run, work, scratch, archive, target):
            assert run.returncode == 37, run.stdout + run.stderr
            assert (scratch / 'trajectory.out').read_text() == 'new run\n'
            assert (target / 'trajectory.out').read_text() == 'unrelated original\n'
            assert 'kept' in run.stdout.lower(), run.stdout
            if kind == 'directory':
                assert (archive / 'trajectory.out').read_text() == 'previous run\n'
            else:
                assert archive.is_symlink()


def test_copyback_preserves_destination_directory_mode():
    for mode in (0o700, 0o750, 0o2770):
        with _edge_job(status=0, archive_kind=None, work_mode=mode) as job:
            run, work, scratch, _, _ = job
            assert run.returncode == 0, run.stdout + run.stderr
            assert work.stat().st_mode & 0o7777 == mode
            assert (work / 'trajectory.out').read_text() == 'new run\n'
            assert (work / '.hidden').read_text() == 'hidden\n'
            assert not scratch.exists()


def _cli(*args):
    env = dict(os.environ, LKPR_NO_HISTORY='1', PYTHONDONTWRITEBYTECODE='1')
    with tempfile.TemporaryDirectory(prefix='lkpr_prep_home_') as home:
        env['HOME'] = home
        return subprocess.run([sys.executable, '-m', 'lammps_pre', *args],
                              cwd=_util.REPO_ROOT, env=env, input='',
                              capture_output=True, text=True, timeout=30)


def test_prep_cli_errors_are_nonzero_and_do_not_write_files():
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for command in ('set fixed_layers 0', 'set nvt_layers -1', 'set o2 -1',
                        'set slab 0 4 8', 'set seed not-a-number', 'nonsense',
                        'write unknown', 'set output "unterminated'):
            batch = root / 'commands.txt'
            output = root / 'must not be written'
            batch.write_text(command + '\nwrite all ' + shlex.quote(str(output)) + '\n')
            result = _cli('--batch', str(batch))
            assert result.returncode != 0, (command, result.stdout, result.stderr)
            assert not output.exists(), (command, result.stdout)
        result = _cli('--o2', '-1', '--build')
        assert result.returncode != 0, result.stdout
        batch.write_text('set slab 4 4 8\nset o2 4\nset vacuum 3\nbuild\n')
        assert _cli('--batch', str(batch)).returncode != 0
        result = _cli('--batch', str(root / 'absent.txt'))
        assert result.returncode != 0


def test_prep_cli_batch_quit_stops_execution_and_space_paths_work():
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        batch = root / 'commands with spaces.txt'
        batch.write_text('quit\nthis-command-must-not-run\n')
        result = _cli('--batch', str(batch))
        assert result.returncode == 0, result.stderr
        assert 'this-command-must-not-run' not in result.stdout
        out = root / 'output with spaces'
        result = _cli('--slab', '4x4x8', '--o2', '4', '--seed', '0', '--write', str(out))
        assert result.returncode == 0, result.stdout + result.stderr
        assert (out / 'lammps.data').is_file(), result.stdout
        assert not (root / 'output').exists()
        assert 'Structure seed: 0' in result.stdout


def test_prep_cli_stale_build_refuses_batch_write_without_prompting():
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        output = root / 'not written'
        batch = root / 'commands.txt'
        batch.write_text('set slab 4 4 8\nset o2 4\nbuild\nset o2 5\n'
                         'write all ' + shlex.quote(str(output)) + '\n')
        result = _cli('--batch', str(batch))
        assert result.returncode != 0, result.stdout + result.stderr
        assert 'Build now?' not in result.stdout
        assert not output.exists()


def test_prep_cli_matrix_paths_and_build_errors_propagate():
    _util.require_numpy()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        output = root / 'matrix with spaces'
        result = _cli('--slab', '4x4x8', '--matrix', 'temps=300 o2=4',
                      '--write', str(output))
        assert result.returncode == 0, result.stdout + result.stderr
        assert (output / 'o2_4' / '300K' / 'lammps.data').is_file()
        batch = root / 'commands.txt'
        batch.write_text('set slab 4 4 8\nset vacuum 3\n'
                         'matrix temps=300 o2=4 output=' +
                         shlex.quote(str(root / 'failed matrix')) + '\n')
        result = _cli('--batch', str(batch))
        assert result.returncode != 0, result.stdout + result.stderr
        assert 'Matrix complete' not in result.stdout
        # An existing regular file is not an output directory.
        occupied = root / 'occupied'
        occupied.write_text('keep this\n')
        result = _cli('--slab', '4x4x8', '--o2', '4', '--write', str(occupied))
        assert result.returncode != 0
        assert occupied.read_text() == 'keep this\n'


if __name__ == '__main__':
    failed = skipped = passed = 0
    for name, test in sorted(list(globals().items())):
        if name.startswith('test_') and callable(test):
            try:
                test()
            except _util.Skip as exc:
                skipped += 1
                print(f'SKIP {name}: {exc}')
            except Exception as exc:
                failed += 1
                print(f'FAIL {name}: {type(exc).__name__}: {exc}')
            else:
                passed += 1
                print(f'PASS {name}')
    print(f'{passed} passed, {failed} failed, {skipped} skipped')
    raise SystemExit(bool(failed))
