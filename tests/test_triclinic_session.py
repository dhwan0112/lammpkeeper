"""GEN-3 serialized session, PBC ownership and unsupported-consumer regressions."""

import contextlib
import io
import itertools
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch
import warnings

import _util


def _quiet(call):
    """Capture presentation while preserving actual exceptions and numerical work."""
    with contextlib.redirect_stdout(io.StringIO()):
        return call()


def _shell():
    """Construct a prompt-free session without touching persistent history."""
    from lammps_post.shell import LammpsPostShell
    from lammps_post.state import SessionState
    shell = LammpsPostShell.__new__(LammpsPostShell)
    shell.state = SessionState()
    shell.noninteractive = True
    shell.command_failures = 0
    return shell


def _load(shell, kind, path, options=''):
    """Use the public load command with paths quoted exactly as CLI callers do."""
    return _quiet(lambda: shell.do_load(f'{kind} {shlex.quote(str(path))} {options}'))


def _error(call, *needles):
    """Require a visible error rather than a skipped or silently downgraded result."""
    try:
        _quiet(call)
    except ValueError as exc:
        for needle in needles:
            assert needle.lower() in str(exc).lower(), str(exc)
        return
    raise AssertionError('Expected explicit rejection')


def _dump(path, flags='pp pp pp', synthetic=False, labels=('A', 'B'), tilt=4):
    """Write a fixed physical 10-cube with wrapped steps of 0.4 Angstrom."""
    text = ''
    for step in range(3):
        x = (9.8 + .4 * step) % 10
        rows = []
        for atom_id, (label, px) in enumerate(zip(labels, (x, x - 9 if step == 0 else x + 1)), 1):
            identity = f'{atom_id} {label}' if synthetic else f'{atom_id} {atom_id} {label}'
            rows.append(f'{identity} {px:.12g} 1 1')
        if step == 1:
            rows.reverse()
        columns = 'id element x y z' if synthetic else 'id type element x y z'
        markers = 'xy xz yz ' if tilt else ''
        bounds = f'0 {10 + tilt} {tilt}\n0 10 0\n0 10 0' if tilt else '0 10\n0 10\n0 10'
        text += (f'ITEM: TIMESTEP\n{step}\nITEM: NUMBER OF ATOMS\n2\n'
                 f'ITEM: BOX BOUNDS {markers}{flags}\n{bounds}\n'
                 f'ITEM: ATOMS {columns}\n' + '\n'.join(rows) + '\n')
    path.write_text(text)


def _input(path, boundary='p p p', labels=('A', 'B')):
    """Serialize explicit boundary metadata and arbitrary species slots."""
    command = f'boundary {boundary}\n' if boundary else ''
    path.write_text('units metal\n' + command + 'atom_style atomic\n'
                    'pair_style pace\npair_coeff * * generic.yace '
                    + ' '.join(labels) + '\ntimestep 0.001\n')


def _data(path, labels=('A', 'B')):
    """Data lo/hi are physical parameters, not the dump's enclosing bounds."""
    path.write_text('Generic cell\n\n2 atoms\n2 atom types\n\n'
                    '0 10 xlo xhi\n0 10 ylo yhi\n0 10 zlo zhi\n'
                    '4 0 0 xy xz yz\n\nMasses\n\n'
                    f'1 2 # species={labels[0]}\n2 3 # species={labels[1]}\n'
                    '\nAtoms # atomic\n\n1 1 1 1 1\n2 2 2 1 1\n')


def _cli(root, commands):
    """Run the actual module entry point in an isolated temporary HOME."""
    batch = root / 'commands.txt'
    batch.write_text('\n'.join(commands) + '\n')
    home = root / 'home'
    home.mkdir(exist_ok=True)
    env = dict(os.environ, HOME=str(home), MPLBACKEND='Agg')
    return subprocess.run([sys.executable, '-m', 'lammps_post', '--batch', str(batch),
                           '--output', str(root / 'plots')], cwd=_util.REPO_ROOT,
                          env=env, text=True, capture_output=True, timeout=60)


def test_triclinic_session_rdf_msd_analytic_cached_and_streamed():
    """Real dispatch uses physical volume and exact wrapped fixed-cell motion."""
    _util.require_numpy()
    import numpy as np
    with tempfile.TemporaryDirectory(prefix='lk-tri-session-') as tmp:
        root = Path(tmp)
        _dump(root / 'run.dump')
        for cache in (0, 1):
            shell = _shell()
            _load(shell, 'dump', root / 'run.dump', f'--cache-mb {cache}')
            frames = shell.state.dump_frames
            assert frames.reader.box_model
            assert frames[0]['cell'].tilt == (4., 0., 0.)
            np.testing.assert_array_equal(frames.boxes[0], [[0, 10]] * 3)
            _quiet(lambda: shell.do_analyze('msd --species A'))
            np.testing.assert_allclose(shell.state.cache['msd_A']['msd'], [0, .16, .64], atol=1e-13)
            _quiet(lambda: shell.do_analyze('rdf A-B --frames 3'))
            result = shell.state.cache['rdf_A-B']
            nonzero = np.flatnonzero(result['g'])
            assert len(nonzero) == 1
            k = nonzero[0]
            dr = result['r'][1] - result['r'][0]
            lo, hi = result['r'][k] - dr / 2, result['r'][k] + dr / 2
            expected = 1000 / (4 * np.pi / 3 * (hi ** 3 - lo ** 3))
            np.testing.assert_allclose(result['g'][k], expected, rtol=1e-13)
            assert shell.state.surface_z is None


def test_triclinic_session_unknown_pbc_resolves_and_unloads_for_all_views():
    """Input-owned flags refresh cached slices without freezing the raw index cell."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-tri-session-') as tmp:
        root = Path(tmp)
        _dump(root / 'run.dump', flags='')
        _input(root / 'run.in', 'p p f')
        _input(root / 'next.in', 'f p p')
        for cache, order in itertools.product((0, 1), (('dump', 'input'), ('input', 'dump'))):
            shell = _shell()
            paths = {'dump': root / 'run.dump', 'input': root / 'run.in'}
            for kind in order:
                _load(shell, kind, paths[kind], f'--cache-mb {cache}' if kind == 'dump' else '')
            frames = shell.state.dump_frames
            view = frames[::2]
            assert view[0]['cell'].pbc == (True, True, False)
            assert shell._periodicity() == ((True, True, False), 'input')
            assert frames.reader.read_frame(frames._store.index, 0)['cell'].pbc is None
            _load(shell, 'input', root / 'next.in')
            assert view[0]['cell'].pbc == (False, True, True)
            assert shell.state.pbc == (False, True, True)
            _quiet(lambda: shell.do_unload('input'))
            assert view[-1]['cell'].pbc is None
            shell.state.surface_z = 8
            shell.state.surface_z_manual = True
            _error(lambda: shell.state.pbc, 'triclinic', 'unresolved', 'boundary')
            shell.state.cache['rdf_A-B'] = object()
            _error(lambda: shell.do_analyze('rdf A-B'), 'unresolved')
            assert 'rdf_A-B' not in shell.state.cache
            shell.state.cache['msd_A'] = object()
            _error(lambda: shell.do_analyze('msd --species A'), 'unresolved')
            assert 'msd_A' not in shell.state.cache


def test_triclinic_session_dump_flags_win_in_both_load_orders():
    """The dump's lattice-vector mask outranks contradictory input boundaries."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-tri-session-') as tmp:
        root = Path(tmp)
        _dump(root / 'run.dump', 'pp ff pp')
        _input(root / 'run.in', 'f p f')
        for order in (('input', 'dump'), ('dump', 'input')):
            shell = _shell()
            for kind in order:
                _load(shell, kind, root / ('run.in' if kind == 'input' else 'run.dump'))
            assert shell.state.pbc == (True, False, True)
            assert shell._periodicity() == ((True, False, True), 'dump')
            assert shell.state.dump_frames[0]['cell'].pbc == (True, False, True)
            _quiet(lambda: shell.do_unload('input'))
            assert shell.state.dump_frames[-1]['cell'].pbc == (True, False, True)


def test_triclinic_session_all_source_orders_keep_groups_and_raw_metadata():
    """Manifest-first unions survive all source orders and override-owned lifetimes."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-tri-session-') as tmp:
        root = Path(tmp)
        _dump(root / 'run.dump', '')
        _data(root / 'run.data')
        _input(root / 'run.in', 'p p f')
        (root / 'run.json').write_text(json.dumps({'schema_version': 1,
                                                 'species_groups': {'X': [1, 2]}}))
        files = {'input': root / 'run.in', 'data': root / 'run.data',
                 'dump': root / 'run.dump'}
        for order in itertools.permutations(files):
            shell = _shell()
            _load(shell, 'manifest', root / 'run.json')
            for kind in order:
                _load(shell, kind, files[kind])
            assert shell.state.species_map.resolve('X') == frozenset({1, 2})
            assert shell.state.species_sources == {kind: {1: 'A', 2: 'B'} for kind in files}
            assert shell.state.dump_frames.reader.type_ids == frozenset({1, 2})
            assert shell.state.dump_frames[0]['cell'].pbc == (True, True, False)
            assert shell.state.data_cell.pbc == (True, True, False)
            with warnings.catch_warnings(record=True):
                warnings.simplefilter('always')
                _quiet(lambda: shell.do_set('types 1=Y 2=Z'))
                assert shell.state._species_override == {1: 'Y', 2: 'Z'}
                _load(shell, 'input', root / 'run.in')
            assert shell.state._species_override is None
            assert shell.state.atom_types == {1: 'A', 2: 'B'}
            assert shell.state.dump_frames[0]['cell'].pbc == (True, True, False)


def test_triclinic_session_no_implicit_boundary_from_input_defaults():
    """An input without boundary cannot turn unknown flags into periodic metadata."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-tri-session-') as tmp:
        root = Path(tmp)
        _dump(root / 'run.dump', '')
        _input(root / 'run.in', '')
        shell = _shell()
        _load(shell, 'input', root / 'run.in')
        _load(shell, 'dump', root / 'run.dump')
        assert shell.state.dump_frames[0]['cell'].pbc is None
        _error(lambda: shell._periodicity(), 'unresolved')


def test_triclinic_session_synthetic_types_compose_with_pbc_and_slice_eviction():
    """Element-only identity transforms survive PBC changes and uncached slicing."""
    _util.require_numpy()
    import numpy as np
    with tempfile.TemporaryDirectory(prefix='lk-tri-session-') as tmp:
        root = Path(tmp)
        _dump(root / 'run.dump', '', synthetic=True)
        _input(root / 'run.in')
        for cache in (0, 1):
            shell = _shell()
            _load(shell, 'dump', root / 'run.dump', f'--cache-mb {cache}')
            frames = shell.state.dump_frames
            view = frames[1:]
            _load(shell, 'input', root / 'run.in')
            for frame in view:
                assert frame['cell'].pbc == (True, True, True)
                assert frame['atoms'].shape == (2, 5)
                np.testing.assert_array_equal(sorted(frame['atoms'][:, -1]), [1, 2])
            _quiet(lambda: shell.do_analyze('msd --species A'))
            np.testing.assert_allclose(shell.state.cache['msd_A']['msd'], [0, .16, .64])
            assert not frames.reader.type_ids


def test_triclinic_session_data_cell_physical_mass_pbc_unload_and_rollback():
    """Structured data parsing publishes geometry/species atomically with mass totals."""
    _util.require_numpy()
    import numpy as np
    with tempfile.TemporaryDirectory(prefix='lk-tri-session-') as tmp:
        root = Path(tmp)
        _data(root / 'run.data')
        _data(root / 'bad.data', ('X', 'B'))
        _input(root / 'run.in', 'p f p')
        for order in (('input', 'data'), ('data', 'input')):
            shell = _shell()
            assert shell.state.data_cell is None
            for kind in order:
                _load(shell, kind, root / ('run.in' if kind == 'input' else 'run.data'))
                if kind == 'data' and shell.state.input_config is None:
                    assert shell.state.data_cell.pbc is None
            cell = shell.state.data_cell
            assert cell.pbc == (True, False, True)
            np.testing.assert_array_equal(shell.state.data_box, [[0, 10]] * 3)
            assert cell.volume == 1000 and shell.state.total_mass_amu == 5
            shell.state.cache['sentinel'] = sentinel = object()
            before = set(shell.state.__dict__)
            with warnings.catch_warnings(record=True):
                warnings.simplefilter('always')
                _error(lambda: _load(shell, 'data', root / 'bad.data'), 'conflicting', '1')
            assert set(shell.state.__dict__) == before
            assert shell.state.data_cell is cell
            assert shell.state.data_path == str(root / 'run.data')
            assert shell.state.cache == {'sentinel': sentinel}
            _quiet(lambda: shell.do_unload('input'))
            assert shell.state.data_cell.pbc is None
            _error(lambda: shell.do_analyze('structure'), 'orthogonal', 'triclinic')
            _quiet(lambda: shell.do_unload('data'))
            assert shell.state.data_cell is None and shell.state.data_box is None
            assert shell.state.total_mass_amu is None


def test_triclinic_session_surface_and_unsupported_analysis_guards():
    """Automatic planes are disabled and manual planes cannot authorize slab kernels."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-tri-session-') as tmp:
        root = Path(tmp)
        _dump(root / 'run.dump', labels=('Fe', 'O'))
        shell = _shell()
        _load(shell, 'dump', root / 'run.dump')
        assert shell.state.surface_z is None
        _quiet(lambda: shell.state._guess_surface_z())
        assert shell.state.surface_z is None
        _quiet(lambda: shell.do_set('surface_z 8'))
        assert shell.state.surface_z == 8 and shell.state.surface_z_manual
        _error(lambda: shell.state.compute_z_focus(), 'orthogonal')
        # Unrestricted OR counts charges only, unlike OAR and slab/z profiles.
        for name in ('density', 'charge_z', 'oar', 'penetration',
                     'penetration_trend', 'dissociation', 'structure'):
            shell.state.cache[name] = object()
            _error(lambda n=name: shell.do_analyze(n), 'orthogonal', 'triclinic')
            assert name not in shell.state.cache
        assert shell.state.surface_z == 8 and shell.state.surface_z_manual
        shell.state.cache['sentinel'] = object()
        _error(lambda: shell.do_analyze('all'), 'orthogonal', 'triclinic')
        assert not shell.state.cache


def test_triclinic_session_later_tilt_cannot_infer_surface_from_first_orthogonal_frame():
    """Whole-trajectory guards use retained cells, not merely the first frame kind."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-tri-session-') as tmp:
        root = Path(tmp)
        _dump(root / 'ortho.dump', labels=('Fe', 'O'), tilt=0)
        _dump(root / 'tri.dump', labels=('Fe', 'O'))
        text = (root / 'ortho.dump').read_text()
        first = text[:text.index('ITEM: TIMESTEP', 1)]
        (root / 'mixed.dump').write_text(first + (root / 'tri.dump').read_text())
        shell = _shell()
        _load(shell, 'dump', root / 'mixed.dump')
        assert shell.state.dump_frames[0]['cell'].is_orthogonal
        assert shell.state.has_triclinic_dump()
        assert shell.state.surface_z is None
        _error(lambda: shell.do_analyze('density'), 'orthogonal', 'triclinic')


def test_triclinic_session_unsupported_plots_reject_before_rendering():
    """Cached slab curves, O2 and snapshot/structure views cannot bypass safety gates."""
    _util.require_numpy()
    from lammps_post.plotting import plot_snapshot, plot_pressure
    with tempfile.TemporaryDirectory(prefix='lk-tri-session-') as tmp:
        root = Path(tmp)
        _dump(root / 'run.dump')
        shell = _shell()
        _load(shell, 'dump', root / 'run.dump')
        shell.state.output_dir = str(root / 'plots')
        for name in ('snapshot', 'structure', 'density', 'dissociation', 'penetration_profile', 'all'):
            shell.state.cache[name] = object()
            _error(lambda n=name: shell.do_plot(n), 'orthogonal', 'triclinic')
        assert not (root / 'plots').exists()
        _error(lambda: plot_snapshot(shell.state.dump_frames, shell.state.dump_col_idx,
                                     shell.state.atom_types, str(root)), 'orthogonal', 'triclinic')
        shell.state.log_data = {'step': [0], 'press': [1]}
        shell.state.plot_recipes['pressure'] = {'slab_z_range': (0, 8)}
        _error(lambda: shell._iplot_pressure([], _batch=True), 'slab pressure', 'triclinic')
        _error(lambda: plot_pressure({'xy': [4], 'step': [0]}, str(root),
                                    slab_z_range=(0, 8)), 'slab pressure', 'triclinic')


def test_triclinic_session_info_reports_physical_kind_tilt_and_unknown_flags():
    """Inspection identifies physical restricted-cell bounds rather than an AABB."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-tri-session-') as tmp:
        root = Path(tmp)
        _dump(root / 'run.dump', '')
        shell = _shell()
        _load(shell, 'dump', root / 'run.dump')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            shell.do_info('')
            shell.do_show('box')
        text = out.getvalue().lower()
        for word in ('restricted triclinic', 'physical', 'tilt', 'unresolved', '1000'):
            assert word in text, text


def test_triclinic_session_actual_cli_batch_success_and_visible_failures():
    """Real serialized A/B CLI RDF/MSD succeed; unsupported batch work exits nonzero."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-tri-session-') as tmp:
        root = Path(tmp)
        _dump(root / 'run.dump')
        load = f'load dump {shlex.quote(str(root / "run.dump"))} --cache-mb 0'
        result = _cli(root, [load, 'analyze rdf A-B', 'analyze msd --species A'])
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'Final MSD: 0.64' in result.stdout
        for command in ('analyze all', 'plot snapshot', 'plot dissociation'):
            result = _cli(root, [load, command])
            assert result.returncode != 0, result.stdout + result.stderr
            assert 'triclinic' in result.stdout.lower()
            assert 'all analyses complete' not in result.stdout.lower()


def test_triclinic_session_rdf_msd_shared_pass_generic_groups():
    """Two supported kernels can share the streaming source with manifest-first groups."""
    _util.require_numpy()
    import numpy as np
    with tempfile.TemporaryDirectory(prefix='lk-tri-session-') as tmp:
        root = Path(tmp)
        _dump(root / 'run.dump')
        (root / 'run.json').write_text(json.dumps({'schema_version': 1,
                                                 'species_groups': {'X': [1, 2]}}))
        shell = _shell()
        _load(shell, 'manifest', root / 'run.json')
        _load(shell, 'dump', root / 'run.dump', '--cache-mb 0')
        _quiet(lambda: shell._run_jobs_shared([
            lambda: shell._analyze_rdf(['X-B'], _batch=True),
            lambda: shell._analyze_msd(['--species', 'X'], _batch=True)]))
        np.testing.assert_allclose(shell.state.cache['msd_X']['msd'], [0, .16, .64])
        assert shell.state.cache['rdf_X-B']['label'] == 'X-B'


def test_triclinic_session_rejected_io_preserves_loaded_sources_and_cache():
    """General abc and scaled-only tilted dumps fail atomically with useful context."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-tri-session-') as tmp:
        root = Path(tmp)
        _dump(root / 'good.dump')
        text = (root / 'good.dump').read_text()
        for filename, bad, needle in (
                ('scaled.dump', text.replace(' x y z', ' xs ys zs'), 'cartesian'),
                ('general.dump', text.replace('xy xz yz', 'abc origin'), 'general')):
            (root / filename).write_text(bad)
            shell = _shell()
            _load(shell, 'dump', root / 'good.dump')
            frames = shell.state.dump_frames
            shell.state.cache['sentinel'] = sentinel = object()
            _error(lambda: _load(shell, 'dump', root / filename), needle)
            assert shell.state.dump_frames is frames
            assert shell.state.cache == {'sentinel': sentinel}


def test_triclinic_session_failed_input_replacement_keeps_resolved_cells():
    """A species-conflicting input replacement restores its old PBC and source cache."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-tri-session-') as tmp:
        root = Path(tmp)
        _dump(root / 'run.dump', '')
        _input(root / 'run.in', 'p p f')
        _input(root / 'bad.in', 'f f p', labels=('X', 'B'))
        shell = _shell()
        _load(shell, 'dump', root / 'run.dump')
        _load(shell, 'input', root / 'run.in')
        frames = shell.state.dump_frames
        view = frames[:]
        assert view[0]['cell'].pbc == (True, True, False)
        shell.state.cache['sentinel'] = sentinel = object()
        with warnings.catch_warnings(record=True):
            warnings.simplefilter('always')
            _error(lambda: _load(shell, 'input', root / 'bad.in'), 'conflicting')
        assert shell.state.cache == {'sentinel': sentinel}
        assert view[0]['cell'].pbc == shell.state.pbc == (True, True, False)


def test_triclinic_session_supported_curves_render_with_real_matplotlib():
    """Render only RDF/MSD curves; this is not a tilted-cell structure renderer."""
    _util.require_numpy()
    from lammps_post import plotting
    _util.require(plotting.HAS_MPL, 'matplotlib not installed (triclinic RDF/MSD curves)')
    with tempfile.TemporaryDirectory(prefix='lk-tri-session-') as tmp:
        root = Path(tmp)
        _dump(root / 'run.dump')
        shell = _shell()
        _load(shell, 'dump', root / 'run.dump')
        shell.state.output_dir = str(root / 'plots')
        _quiet(lambda: shell.do_analyze('rdf A-B'))
        _quiet(lambda: shell.do_analyze('msd --species A'))
        _quiet(lambda: shell.do_plot('rdf A-B'))
        _quiet(lambda: shell.do_plot('msd A'))
        images = list((root / 'plots').glob('*.png'))
        assert len(images) == 2
        assert all(image.stat().st_size > 0 for image in images)


def test_triclinic_session_legacy_state_guards_validate_actual_frames():
    """Legacy duck-typed states need compatibility without bypassing geometry checks."""
    _util.require_numpy()
    import numpy as np
    from lammpkeeper.io import Box
    from test_o2_periodicity import _shell as legacy_shell
    shell = legacy_shell(None, ['p', 'f', 'p'], 8)
    assert shell._periodicity() == ((True, False, True), 'input')
    assert shell._require_surface_z()
    for geometry in ('typed', 'raw_tilt', 'bad_bounds'):
        shell = legacy_shell(None, None, 8)
        shell.state.cache = {'dissociation': 'stale', 'msd_X': 'keep'}
        frame = shell.state.dump_frames[0]
        if geometry == 'typed':
            frame['cell'] = Box((0, 0, 0), (60, 60, 60), tilt=(4, 0, 0), pbc=None)
        elif geometry == 'raw_tilt':
            frame['tilt'] = (4, 0, 0)
        else:
            frame['box'] = np.zeros((3, 3))
        _error(lambda: shell._analyze_dissociation([]), 'orthogonal')
        assert shell.state.cache == {'msd_X': 'keep'}
        _error(lambda: shell._require_surface_z(), 'orthogonal')
        assert not hasattr(shell.state, '_structure_atoms')
        if geometry == 'typed':
            _error(lambda: shell._periodicity(), 'triclinic', 'unresolved')
    shell = legacy_shell(None, ['p', 'invalid', 'f'], None)
    _error(lambda: shell._periodicity(), 'boundary')
    shell = legacy_shell(None, None, None)
    shell.state.dump_frames = []
    shell.state.data_box = np.zeros((3, 3))
    _error(lambda: shell._guard_geometry('Slab pressure normalization', include_data=True),
           'orthogonal')


def test_triclinic_session_interactive_pure_curves_never_request_spatial_focus():
    """Mock renderers: pure charge/spin/OR/thermo dispatch must never inspect z."""
    _util.require_numpy()
    from lammps_post import shell as module
    with tempfile.TemporaryDirectory(prefix='lk-tri-session-') as tmp:
        root = Path(tmp)
        _dump(root / 'run.dump')
        for saved in (False, True):
            shell = _shell()
            _load(shell, 'dump', root / 'run.dump')
            shell.noninteractive = False
            shell.state.output_dir = str(root / 'plots')
            shell.state.cache.update({key: {'pure': True} for key in ('charge', 'spin', 'or')})
            shell.state.log_data = {'step': [0], 'press': [1],
                                    'unit_system': 'metal', 'dt_fs': 1}
            shell.state.compute_z_focus = focus = Mock(side_effect=AssertionError('spatial focus called'))
            if saved:
                shell.state.plot_recipes = {
                    key: {'z_focus': (0, 8), 'normalize': False, 'lw': 2}
                    for key in ('charge_evolution', 'spin_evolution')}
            prompts = []

            def answer(prompt, default=None):
                """Supply interactive defaults while recording offered scientific options."""
                prompts.append(prompt)
                return default

            with patch.object(module, 'plt', SimpleNamespace(rcParams={}), create=True), \
                    patch.object(module, 'plot_charge_evolution') as charge, \
                    patch.object(module, 'plot_spin') as spin, \
                    patch.object(module, 'plot_or') as oxidation, \
                    patch.object(module, 'plot_thermo') as thermo, \
                    patch.object(module, 'plot_thermostat_summary') as thermostat, \
                    patch.object(shell, '_ask', side_effect=answer), \
                    patch.object(sys, 'stdin', SimpleNamespace(isatty=lambda: True)):
                _quiet(lambda: shell.do_plot('charge'))
                _quiet(lambda: shell.do_plot('spin'))
                _quiet(lambda: shell.do_plot('or'))
                _quiet(lambda: shell.do_plot('thermo'))
                _quiet(lambda: shell.do_plot('thermostat'))
            focus.assert_not_called()
            assert not any('z-axis' in prompt for prompt in prompts)
            assert (charge.call_count == spin.call_count == oxidation.call_count
                    == thermo.call_count == thermostat.call_count == 1)
            for key in ('charge_evolution', 'spin_evolution'):
                assert shell.state.plot_recipes[key]['z_focus'] is None


def test_triclinic_session_unrestricted_or_is_pure_charge_dispatch():
    """OR without z selection is a charge count, independent of cell geometry."""
    _util.require_numpy()
    import numpy as np
    from lammps_post import shell as module
    from lammps_post.analysis import compute_or
    with tempfile.TemporaryDirectory(prefix='lk-tri-session-') as tmp:
        root = Path(tmp)
        _dump(root / 'run.dump', flags='', labels=('Fe', 'O'))
        lines = (root / 'run.dump').read_text().replace(' x y z', ' x y z q').splitlines()
        lines = [line + (' 0.5' if line.split()[0] == '1' else ' 0.1')
                 if len(line.split()) == 6 and line.split()[0].isdigit() else line for line in lines]
        (root / 'run.dump').write_text('\n'.join(lines) + '\n')
        shell = _shell()
        _load(shell, 'dump', root / 'run.dump')
        _quiet(lambda: shell.do_analyze('or'))
        expected = compute_or(shell.state.dump_frames, shell.state.dump_col_idx,
                              dt_fs=shell.state.dt_fs, q_thr=shell.state.q_threshold, fe_type={1})
        np.testing.assert_array_equal(shell.state.cache['or']['or'], [1, 1, 1])
        np.testing.assert_array_equal(shell.state.cache['or']['time'], expected['time'])
        _error(lambda: compute_or(shell.state.dump_frames, shell.state.dump_col_idx,
                                  fe_type={1}, z_range=(0, 8)), 'orthogonal')
        shell.state.compute_z_focus = focus = Mock(side_effect=AssertionError('spatial focus called'))
        with patch.object(module, 'plot_or') as renderer:
            _quiet(lambda: shell.do_plot('or'))
        assert renderer.call_count == 1
        focus.assert_not_called()
