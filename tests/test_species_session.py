"""GEN-1 session integration using serialized generic species and explicit unions.

Synthetic metadata/load-order checks do not identify a real material or validate
force-field classification. Kernel comparisons check dispatch parity; analytic
displacements separately check the selected ID cohort's MSD.
"""

import contextlib
import hashlib
import io
import itertools
import json
from pathlib import Path
import shlex
import tempfile
import warnings

import _util


def _quiet(call):
    """Discard stdout presentation while allowing exceptions and warnings to escape."""
    with contextlib.redirect_stdout(io.StringIO()):
        return call()


def _shell():
    """Construct a shell without persistent history or interactive prompting."""
    from lammps_post.shell import LammpsPostShell
    from lammps_post.state import SessionState
    shell = LammpsPostShell.__new__(LammpsPostShell)
    shell.state = SessionState()
    shell.noninteractive = True
    return shell


def _load(shell, kind, path, extra=''):
    """Exercise the actual command parser, including safely quoted source paths."""
    return _quiet(lambda: shell.do_load(f'{kind} {shlex.quote(str(path))}{extra}'))


def _error(call, *needles):
    """Require explicit rejection with enough context to diagnose the metadata."""
    try:
        _quiet(call)
    except ValueError as exc:
        for needle in needles:
            assert str(needle).lower() in str(exc).lower(), str(exc)
        return
    raise AssertionError('Expected a visible metadata error')


def _input(path, labels):
    """Serialize sparse typed slots without requiring a recognized force field."""
    slots = [labels.get(t, 'NULL') for t in range(1, max(labels) + 1)]
    path.write_text('units metal\nboundary p p p\natom_style atomic\n'
                    'pair_style pace\npair_coeff * * generic.yace '
                    + ' '.join(slots) + '\ntimestep 0.001\n')


def _data(path, labels):
    """Write labelled Masses and one static atom per sparse numeric type."""
    path.write_text('Generic system\n\n%d atoms\n%d atom types\n\n'
                    '0 20 xlo xhi\n0 20 ylo yhi\n0 20 zlo zhi\n\nMasses\n\n%s\n'
                    '\nAtoms # atomic\n\n%s\n' %
                    (len(labels), max(labels),
                     '\n'.join(f'{t} 1.0' + (f' # species={labels[t]}' if t in labels else '')
                               for t in range(1, max(labels) + 1)),
                     '\n'.join(f'{i} {t} {i} 1 1' for i, t in enumerate(labels, 1))))


def _dump(path, labels=None, per_frame=None):
    """Write ID-stable trajectories with squared displacements one, nine, zero."""
    labels = labels or {2: 'A', 7: 'A', 9: 'B'}
    maps = per_frame or [labels, labels]
    text = ''
    for index, frame_labels in enumerate(maps):
        rows = []
        for atom_id, (tid, label) in enumerate(frame_labels.items(), 1):
            x = atom_id * 3 + ([1, 3, 0][atom_id - 1] if index else 0)
            rows.append(f'{atom_id} {tid} {label} {x} 1 1')
        text += ('ITEM: TIMESTEP\n%d\nITEM: NUMBER OF ATOMS\n%d\n'
                 'ITEM: BOX BOUNDS pp pp pp\n0 20\n0 20\n0 20\n'
                 'ITEM: ATOMS id type element x y z\n%s\n' %
                 (index * 100, len(rows), '\n'.join(rows)))
    path.write_text(text)


def _manifest(path, groups=None, **fields):
    """Write an explicitly requested schema-one sidecar, never auto-discovered."""
    path.write_text(json.dumps(dict(schema_version=1,
                                   species_groups=groups or {'X': [2, 7]}, **fields)))


def test_species_session_all_source_orders_preserve_sparse_generic_labels():
    """Input, Masses and typed dump labels merge identically in all load orders."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        labels = {2: 'A', 7: 'A', 9: 'B'}
        files = {kind: root / kind for kind in ('input', 'data', 'dump')}
        _input(files['input'], labels)
        _data(files['data'], labels)
        _dump(files['dump'], labels)
        for order in itertools.permutations(files):
            shell = _shell()
            for kind in order:
                _load(shell, kind, files[kind])
            assert shell.state.atom_types == labels
            assert shell.state.species_map.resolve('A') == frozenset({2, 7})
            assert shell.state.species_map.resolve('B') == frozenset({9})
            assert shell.state.surface_z is None
            assert shell.state.species_sources['dump'] == labels


def test_species_session_partial_sources_fill_not_replace():
    """Compatible partial input and data maps fill missing slots in either order."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _input(root / 'run.in', {2: 'A'})
        _data(root / 'run.data', {7: 'A', 9: 'B'})
        for order in (('input', 'data'), ('data', 'input')):
            shell = _shell()
            for kind in order:
                _load(shell, kind, root / ('run.in' if kind == 'input' else 'run.data'))
            assert shell.state.atom_types == {2: 'A', 7: 'A', 9: 'B'}
            assert shell.state.species_map.resolve('A') == frozenset({2, 7})


def test_species_session_conflict_rolls_back_source_cache_and_manual_surface():
    """Contradictory explicit identities warn and cannot partially publish a load."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _input(root / 'run.in', {2: 'A'})
        _data(root / 'bad.data', {2: 'B'})
        shell = _shell()
        _load(shell, 'input', root / 'run.in')
        shell.state.cache['sentinel'] = sentinel = object()
        shell.state.surface_z = 42
        shell.state.surface_z_manual = True
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            _error(lambda: _load(shell, 'data', root / 'bad.data'), '2', 'input', 'data', 'A', 'B')
        assert any(issubclass(w.category, RuntimeWarning) and 'Conflicting' in str(w.message)
                   for w in caught)
        assert shell.state.data_path is None
        assert shell.state.atom_types == {2: 'A'}
        assert shell.state.cache == {'sentinel': sentinel}
        assert shell.state.surface_z == 42 and shell.state.surface_z_manual


def test_species_session_manifest_pending_resolves_and_unloads_to_pending():
    """Manifest-first groups stay pending until typed sources arrive, then resolve."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _manifest(root / 'run.json')
        _data(root / 'run.data', {2: 'A', 7: 'A', 9: 'B'})
        shell = _shell()
        _load(shell, 'manifest', root / 'run.json')
        _error(lambda: shell.state.species_map, 'pending', 'X', '2', '7', 'run.json')
        _load(shell, 'data', root / 'run.data')
        assert shell.state.species_map.resolve('X') == frozenset({2, 7})
        shell.state.cache['old'] = object()
        _quiet(lambda: shell.do_unload('data'))
        assert not shell.state.cache
        _error(lambda: shell.state.species_map, 'pending', 'X')
        _load(shell, 'data', root / 'run.data')
        assert shell.state.species_map.resolve('X') == frozenset({2, 7})
        _quiet(lambda: shell.do_unload('manifest'))
        _error(lambda: shell.state.species_map.resolve('X'), 'unknown', 'A', 'B')


def test_species_session_manifest_hash_failure_is_transactional():
    """A replaced sidecar with incorrect provenance cannot erase valid groups/results."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _data(root / 'run.data', {2: 'A', 7: 'A', 9: 'B'})
        digest = hashlib.sha256((root / 'run.data').read_bytes()).hexdigest()
        _manifest(root / 'good.json', provenance={'file_hashes': {'run.data': digest}})
        _manifest(root / 'bad.json', {'Y': [9]},
                  provenance={'file_hashes': {'run.data': '0' * 64}})
        shell = _shell()
        _load(shell, 'data', root / 'run.data')
        _load(shell, 'manifest', root / 'good.json')
        shell.state.cache['old'] = sentinel = object()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            _error(lambda: _load(shell, 'manifest', root / 'bad.json'), 'hash', 'mismatch')
        assert any('hash mismatch' in str(w.message) for w in caught)
        assert shell.state.manifest_path == str((root / 'good.json').resolve())
        assert shell.state.species_map.resolve('X') == frozenset({2, 7})
        assert shell.state.cache == {'old': sentinel}


def test_species_session_groups_reach_actual_rdf_msd_and_density():
    """Manifest unions reach kernels while requested labels remain raw cache keys."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import compute_rdf, compute_density_profile
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _dump(root / 'run.dump')
        _manifest(root / 'run.json')
        shell = _shell()
        _load(shell, 'dump', root / 'run.dump')
        _load(shell, 'manifest', root / 'run.json')
        _quiet(lambda: shell._analyze_msd(['--species', 'X'], _batch=True))
        np.testing.assert_allclose(shell.state.cache['msd_X']['msd'], [0, 5])
        assert shell.state.cache['msd_X']['label'] == 'X'
        _quiet(lambda: shell._analyze_rdf(['X-B'], _batch=True))
        # Reusing the same kernel isolates selection/dispatch parity; this is
        # not an independent oracle for RDF pair counts or normalization.
        expected = compute_rdf(shell.state.dump_frames, shell.state.dump_col_idx,
                               type_a={2, 7}, type_b={9}, pbc=(True, True, True), z_pbc=True)
        np.testing.assert_array_equal(shell.state.cache['rdf_X-B']['g'], expected['g'])
        assert shell.state.cache['rdf_X-B']['label'] == 'X-B'
        _quiet(lambda: shell._analyze_density(['--species', 'X'], _batch=True))
        expected = compute_density_profile(shell.state.dump_frames, shell.state.dump_col_idx,
                                           species_type={2, 7}, species_name='X')
        for key, value in expected.items():
            if isinstance(value, np.ndarray):
                np.testing.assert_array_equal(shell.state.cache['density_X'][key], value)
        assert shell._density_species()['X'] == frozenset({2, 7})


def test_species_session_source_unload_and_replacement_preserve_ownership():
    """Removing a higher source restores surviving evidence, not overwritten ff_info."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _input(root / 'run.in', {2: 'A'})
        _data(root / 'run.data', {7: 'A', 9: 'B'})
        _data(root / 'new.data', {9: 'B'})
        shell = _shell()
        _load(shell, 'input', root / 'run.in')
        _load(shell, 'data', root / 'run.data')
        _load(shell, 'data', root / 'new.data')
        assert shell.state.atom_types == {2: 'A', 9: 'B'}
        _quiet(lambda: shell.do_unload('input'))
        assert shell.state.atom_types == {9: 'B'}
        _quiet(lambda: shell.do_unload('all'))
        assert shell.state.species_map.type_sets() == {}


def test_species_session_managed_update_invalidates_but_legacy_maps_are_fresh():
    """Managed edits clear results; direct legacy edits refresh selections only."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _data(root / 'run.data', {2: 'A', 7: 'A', 9: 'B'})
        shell = _shell()
        shell.state.ff_info['atom_types'] = {2: 'A'}
        first = shell.state.species_map
        shell.state.ff_info['atom_types'][7] = 'A'
        assert first.resolve('A') == frozenset({2})
        assert shell.state.species_map.resolve('A') == frozenset({2, 7})
        shell.state.cache['old'] = object()
        shell.state.surface_z = 55
        shell.state.surface_z_manual = True
        _load(shell, 'data', root / 'run.data')
        assert not shell.state.cache and shell.state.surface_z == 55


def test_species_session_manifest_conflicting_group_rejects_load():
    """An exact label cannot be redefined by a manifest subset."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _data(root / 'run.data', {2: 'A', 7: 'A', 9: 'B'})
        _manifest(root / 'bad.json', {'A': [2]})
        shell = _shell()
        _load(shell, 'data', root / 'run.data')
        _error(lambda: _load(shell, 'manifest', root / 'bad.json'), 'conflicting', 'A')
        assert shell.state.run_manifest is None


def test_species_session_streaming_labels_validate_before_kernel_consumption():
    """New middle-frame identities update lazily and force retry, never a wrong union."""
    _util.require_numpy()
    import numpy as np
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _dump(root / 'run.dump', per_frame=[{2: 'A', 9: 'B'},
                                           {2: 'A', 7: 'A', 9: 'B'},
                                           {2: 'A', 9: 'B'}])
        shell = _shell()
        _load(shell, 'dump', root / 'run.dump', ' --cache-mb 0')
        assert shell.state.species_map.resolve('A') == frozenset({2})
        _error(lambda: shell._analyze_msd(['--species', 'A'], _batch=True), 'expanded', 'retry')
        assert 'msd_A' not in shell.state.cache
        assert shell.state.species_map.resolve('A') == frozenset({2, 7})
        _quiet(lambda: shell._analyze_msd(['--species', 'A'], _batch=True))
        assert np.all(np.isfinite(shell.state.cache['msd_A']['msd']))


def test_species_session_explicit_dump_conflict_is_rejected_lazily():
    """A middle frame cannot contradict loaded input or preserve old numeric results."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _input(root / 'run.in', {2: 'A', 7: 'A', 9: 'B'})
        _dump(root / 'run.dump', per_frame=[{2: 'A', 9: 'B'},
                                           {2: 'A', 7: 'X', 9: 'B'},
                                           {2: 'A', 9: 'B'}])
        shell = _shell()
        _load(shell, 'input', root / 'run.in')
        _load(shell, 'dump', root / 'run.dump', ' --cache-mb 0')
        shell.state.cache['old'] = object()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            _error(lambda: shell._analyze_msd(['--species', 'A'], _batch=True), '7', 'input', 'dump')
        assert any('Conflicting' in str(w.message) for w in caught)
        assert not shell.state.cache


def test_species_session_dump_replacement_conflict_preserves_old_source():
    """A rejected dump cannot replace an existing reader, labels or cached result."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _input(root / 'run.in', {2: 'A', 7: 'A', 9: 'B'})
        _dump(root / 'good.dump')
        _dump(root / 'bad.dump', {2: 'X', 7: 'A', 9: 'B'})
        shell = _shell()
        _load(shell, 'input', root / 'run.in')
        _load(shell, 'dump', root / 'good.dump')
        old_frames = shell.state.dump_frames
        shell.state.cache['old'] = sentinel = object()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            _error(lambda: _load(shell, 'dump', root / 'bad.dump'), '2', 'input', 'dump')
        assert any('Conflicting' in str(w.message) for w in caught)
        assert shell.state.dump_frames is old_frames
        assert shell.state.dump_path == str(root / 'good.dump')
        assert shell.state.species_map.resolve('A') == frozenset({2, 7})
        assert shell.state.cache == {'old': sentinel}


def test_species_session_manifest_syntax_and_pending_redefinition_rejected():
    """Malformed/proven conflicts reject; unknown additional memberships stay pending."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _data(root / 'run.data', {2: 'A'})
        (root / 'syntax.json').write_text('{')
        _manifest(root / 'pending.json', {'A': [2, 99]})
        _manifest(root / 'conflict.json', {'A': [99]})
        shell = _shell()
        _load(shell, 'data', root / 'run.data')
        _error(lambda: _load(shell, 'manifest', root / 'syntax.json'), 'malformed')
        # Identity justification: unknown type 99 could also have label A, so
        # including it does not contradict known A={2}. Dropping known type 2
        # from that exact-label group is already a provable contradiction.
        _load(shell, 'manifest', root / 'pending.json')
        _error(lambda: shell.state.species_map, 'pending', '99')
        _error(lambda: _load(shell, 'manifest', root / 'conflict.json'), 'conflicting', 'A')
        assert shell.state.manifest_path == str((root / 'pending.json').resolve())
        assert 'manifest ' in shell.complete_load('', 'load ', 5, 5)
        assert 'manifest' in shell.complete_unload('mani', 'unload mani', 7, 11)


def test_species_session_raw_proxy_evidence_survives_analysis_adaptation():
    """Canonical preset display aliases never overwrite the raw source identities."""
    _util.require_numpy()
    from lammpkeeper.common.mapping import element_to_type, type_to_label
    raw = {tid: label for label, tid in element_to_type('ace').items()}
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _input(root / 'run.in', raw)
        _dump(root / 'run.dump', raw)
        shell = _shell()
        _load(shell, 'input', root / 'run.in')
        _load(shell, 'dump', root / 'run.dump')
        assert shell.state.atom_types == type_to_label('ace')
        assert shell.state.species_sources['input'] == raw
        assert shell.state.species_sources['dump'] == raw
        _quiet(lambda: shell.do_unload('input'))
        assert shell.state.atom_types == type_to_label('ace')
        assert shell.state.species_map.resolve('Fe') == frozenset({1, 2})


def test_species_session_resolved_exact_group_can_become_pending_on_unload():
    """A previously valid exact-label union becomes pending, not an unload error."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _input(root / 'run.in', {2: 'A'})
        _data(root / 'run.data', {7: 'A'})
        _manifest(root / 'run.json', {'A': [2, 7]})
        shell = _shell()
        _load(shell, 'input', root / 'run.in')
        _load(shell, 'data', root / 'run.data')
        _load(shell, 'manifest', root / 'run.json')
        _quiet(lambda: shell.do_unload('data'))
        _error(lambda: shell.state.species_map, 'pending', 'A', '7')
        _load(shell, 'data', root / 'run.data')
        assert shell.state.species_map.resolve('A') == frozenset({2, 7})


def test_species_session_partial_identity_can_load_before_unlabelled_dump():
    """Partial sources may load in any order, but unresolved frames block analyses."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _input(root / 'run.in', {2: 'A'})
        _data(root / 'run.data', {7: 'A', 9: 'B'})
        _dump(root / 'run.dump')
        text = (root / 'run.dump').read_text().replace('type element x', 'type x')
        for label in ('A', 'B'):
            text = text.replace(f' {label} ', ' ')
        (root / 'run.dump').write_text(text)
        files = {'input': root / 'run.in', 'data': root / 'run.data', 'dump': root / 'run.dump'}
        for order in itertools.permutations(files):
            shell = _shell()
            for kind in order:
                _load(shell, kind, files[kind])
                if shell.state.dump_frames and shell.state.atom_types == {2: 'A'}:
                    _error(lambda: shell._analyze_msd(['--species', 'A'], _batch=True),
                           'explicit', '7', '9')
            assert shell.state.species_map.resolve('A') == frozenset({2, 7})
            _quiet(lambda: shell._analyze_msd(['--species', 'A'], _batch=True))


def test_species_session_forcefield_alias_conflict_rejects_setting_atomically():
    """Changing a preset cannot silently invalidate an existing manifest union."""
    _util.require_numpy()
    from lammpkeeper.common.mapping import type_to_label
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _manifest(root / 'run.json', {'Fe': [1]})
        shell = _shell()
        shell.state.ff_info.update(forcefield='reaxff', atom_types=type_to_label('ace'))
        _load(shell, 'manifest', root / 'run.json')
        shell.state.cache['old'] = sentinel = object()
        _error(lambda: shell.do_set('forcefield ace'), 'conflicting', 'Fe')
        assert shell.state.ff == 'reaxff'
        assert shell.state.cache == {'old': sentinel}


def test_species_session_generated_proxy_labels_agree_in_every_source_order():
    """Prep's actual Masses labels and raw potential slots encode the same identity."""
    _util.require_numpy()
    import numpy as np
    from types import SimpleNamespace
    from lammps_pre.state import FF_PRESETS
    from lammps_pre.writers import write_data_file
    from lammpkeeper.common.mapping import element_to_type, type_to_label
    raw = {tid: label for label, tid in element_to_type('ace').items()}
    labels = type_to_label('ace')
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        build = SimpleNamespace(fe_positions=np.array([[1, 1, 1], [2, 1, 1]]),
                                o2_positions=np.array([[3, 1, 1]]),
                                box=(0, 20, 0, 20, 0, 20),
                                regions={'n_fixed_layers': 1, 'n_thermostat_layers': 1,
                                         'n_nve_layers': 1})
        prep = SimpleNamespace(ff=FF_PRESETS['ace'], surface='100', nx=1, ny=1, nz=3)
        _quiet(lambda: write_data_file(build, prep, str(root / 'generated.data')))
        _input(root / 'run.in', raw)
        _dump(root / 'run.dump', raw)
        files = {'input': root / 'run.in', 'data': root / 'generated.data',
                 'dump': root / 'run.dump'}
        for order in itertools.permutations(files):
            shell = _shell()
            for kind in order:
                _load(shell, kind, files[kind])
            assert shell.state.atom_types == labels
            assert shell.state.species_sources['data'] == labels
            assert shell.state.species_sources['input'] == raw
            assert shell.state.species_sources['dump'] == raw
            assert shell.state.species_map.resolve('Fe') == frozenset({1, 2})
        _data(root / 'wrong.data', {1: labels[2], 2: labels[1], 3: labels[3]})
        shell = _shell()
        _load(shell, 'input', root / 'run.in')
        with warnings.catch_warnings(record=True):
            warnings.simplefilter('always')
            _error(lambda: _load(shell, 'data', root / 'wrong.data'), 'conflicting', '1')


def test_species_session_manual_override_has_explicit_source_owned_lifetime():
    """Manual analysis names survive sidecars but clear on successful typed-source edits."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _data(root / 'run.data', {2: 'A', 7: 'A', 9: 'B'})
        _data(root / 'bad.data', {2: 'B'})
        _input(root / 'run.in', {2: 'A', 7: 'A', 9: 'B'})
        _manifest(root / 'run.json')
        shell = _shell()
        _load(shell, 'input', root / 'run.in')
        _load(shell, 'data', root / 'run.data')
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            _quiet(lambda: shell.do_set('types 2=Y 7=Y 9=Z'))
        assert any('manual' in str(w.message).lower() for w in caught)
        _load(shell, 'manifest', root / 'run.json')
        assert shell.state.species_map.resolve('Y') == frozenset({2, 7})
        (root / 'log.lammps').write_text('LAMMPS\nStep Temp\n0 300\n10 310\n'
                                       'Loop time of 1 on 1 procs for 10 steps with 3 atoms\n')
        _load(shell, 'log', root / 'log.lammps')
        assert shell.state.species_map.resolve('Y') == frozenset({2, 7})
        _quiet(lambda: shell.do_unload('log'))
        assert shell.state.species_map.resolve('Y') == frozenset({2, 7})
        _quiet(lambda: shell.do_unload('manifest'))
        assert shell.state.species_map.resolve('Y') == frozenset({2, 7})
        shell.state.cache['override_result'] = sentinel = object()
        with warnings.catch_warnings(record=True):
            warnings.simplefilter('always')
            _error(lambda: _load(shell, 'data', root / 'bad.data'), 'conflicting')
        assert shell.state.species_map.resolve('Y') == frozenset({2, 7})
        assert shell.state.cache == {'override_result': sentinel}
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            _quiet(lambda: shell.do_unload('input'))
        assert any('override' in str(w.message).lower() and 'clear' in str(w.message).lower()
                   for w in caught)
        assert shell.state.atom_types == {2: 'A', 7: 'A', 9: 'B'}
        _quiet(lambda: shell.do_set('types 2=Y 7=Y 9=Z'))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            _load(shell, 'input', root / 'run.in')
        assert any('override' in str(w.message).lower() and 'clear' in str(w.message).lower()
                   for w in caught)
        assert shell.state.atom_types == {2: 'A', 7: 'A', 9: 'B'}
        _quiet(lambda: shell.do_set('types 2=Y 7=Y 9=Z'))
        _quiet(lambda: shell.do_unload('all'))
        assert shell.state.species_map.type_sets() == {}


def test_species_session_pending_exact_group_is_load_order_independent():
    """Unknown extra IDs do not prove an exact-label conflict; known exclusions do."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _input(root / 'partial.in', {2: 'A'})
        _input(root / 'full.in', {2: 'A', 99: 'A'})
        _input(root / 'excluded.in', {2: 'A', 7: 'A'})
        _input(root / 'other.in', {2: 'A', 99: 'B'})
        _manifest(root / 'run.json', {'A': [2, 99]})
        for manifest_first in (False, True):
            shell = _shell()
            for kind, path in ([('manifest', root / 'run.json'), ('input', root / 'partial.in')]
                               if manifest_first else
                               [('input', root / 'partial.in'), ('manifest', root / 'run.json')]):
                _load(shell, kind, path)
            _error(lambda: shell.state.species_map, 'pending', '99')
            _load(shell, 'input', root / 'full.in')
            assert shell.state.species_map.resolve('A') == frozenset({2, 99})
            for filename in ('excluded.in', 'other.in'):
                rejected = _shell()
                if manifest_first:
                    _load(rejected, 'manifest', root / 'run.json')
                    _error(lambda: _load(rejected, 'input', root / filename), 'conflicting', 'A')
                else:
                    _load(rejected, 'input', root / filename)
                    _error(lambda: _load(rejected, 'manifest', root / 'run.json'), 'conflicting', 'A')


def test_species_session_synthetic_types_never_certify_manifest_references():
    """Element-only synthesized slots are not authoritative numeric identity evidence."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _dump(root / 'typed.dump', {1: 'Fe', 2: 'Mn', 3: 'O'})
        lines = (root / 'typed.dump').read_text().splitlines()
        element_only = []
        atom_rows = False
        for line in lines:
            if line.startswith('ITEM:'):
                atom_rows = line.startswith('ITEM: ATOMS')
                element_only.append(line.replace('id type element', 'id element'))
            elif atom_rows:
                parts = line.split()
                element_only.append(' '.join(parts[:1] + parts[2:]))
            else:
                element_only.append(line)
        (root / 'elements.dump').write_text('\n'.join(element_only) + '\n')
        _manifest(root / 'run.json', {'X': [1, 2]})
        for order in (('dump', 'manifest'), ('manifest', 'dump')):
            shell = _shell()
            for kind in order:
                _load(shell, kind, root / ('elements.dump' if kind == 'dump' else 'run.json'))
            _error(lambda: shell.state.species_map, 'pending', '1', '2')


def test_species_session_unlabelled_raw_types_support_numeric_manifest_unions():
    """Raw numeric IDs validate unions without making heuristic species authoritative."""
    _util.require_numpy()
    import numpy as np
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _dump(root / 'run.dump')
        text = (root / 'run.dump').read_text().replace('type element x', 'type x')
        for label in ('A', 'B'):
            text = text.replace(f' {label} ', ' ')
        (root / 'run.dump').write_text(text)
        _manifest(root / 'run.json', {'X': [2, 7], 'Fe_up': [7]})
        _manifest(root / 'unknown.json', {'Y': [1]})
        for order in (('dump', 'manifest'), ('manifest', 'dump')):
            shell = _shell()
            for kind in order:
                _load(shell, kind, root / ('run.dump' if kind == 'dump' else 'run.json'))
            assert shell.state.dump_frames.reader.type_ids == frozenset({2, 7, 9})
            assert shell.state.species_map.resolve('X') == frozenset({2, 7})
            assert shell.state.species_map.resolve('Fe_up') == frozenset({7})
            _quiet(lambda: shell._analyze_msd(['--species', 'X'], _batch=True))
            np.testing.assert_allclose(shell.state.cache['msd_X']['msd'], [0, 5])
            _quiet(lambda: shell._analyze_rdf(['X-X'], _batch=True))
            _quiet(lambda: shell._analyze_msd(['--species', 'Fe_up'], _batch=True))
            assert shell.state.cache['msd_Fe_up']['display_label'] == 'Fe_up'
            _load(shell, 'manifest', root / 'unknown.json')
            _error(lambda: shell.state.species_map, 'pending', '1')


def test_species_session_lazy_expansion_clears_only_automatic_geometry():
    """Stream/shared discovery clears focus and stale planes, retaining manual planes."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _dump(root / 'run.dump', per_frame=[{2: 'A', 9: 'B'},
                                           {2: 'A', 7: 'A', 9: 'B'},
                                           {2: 'A', 9: 'B'}])
        for cache_mb, shared, manual in itertools.product((0, 128), (False, True), (False, True)):
            shell = _shell()
            _load(shell, 'dump', root / 'run.dump', f' --cache-mb {cache_mb}')
            shell.state.surface_z = 55
            shell.state.surface_z_manual = manual
            shell.state.z_focus = (0, 10)
            shell.state.cache['old'] = object()
            context = shell.state.dump_frames.shared_pass() if shared else contextlib.nullcontext()
            with context:
                _error(lambda: shell._analyze_msd(['--species', 'A'], _batch=True),
                       'expanded', 'retry')
            assert shell.state.z_focus is None
            assert shell.state.surface_z == (55 if manual else None)
            assert not shell.state.cache
            _quiet(lambda: shell._analyze_msd(['--species', 'A'], _batch=True))


def test_species_session_numeric_data_ids_resolve_groups_without_species_guesses():
    """Numeric Masses/Atoms declarations can validate a union without chemical labels."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _data(root / 'run.data', {2: 'A', 7: 'A', 9: 'B'})
        (root / 'run.data').write_text('\n'.join(
            line.split('#', 1)[0] if 'species=' in line else line
            for line in (root / 'run.data').read_text().splitlines()) + '\n')
        _manifest(root / 'run.json', {'X': [2, 7]})
        for order in (('data', 'manifest'), ('manifest', 'data')):
            shell = _shell()
            for kind in order:
                _load(shell, kind, root / ('run.data' if kind == 'data' else 'run.json'))
            assert shell.state.atom_types == {}
            assert shell.state.species_map.type_sets() == {'X': frozenset({2, 7})}
            assert shell.state.species_sources['data'] == {}


def test_species_session_known_unlabelled_extra_cannot_redefine_exact_species():
    """Known numeric IDs stop being pending but cannot silently widen exact A."""
    _util.require_numpy()
    with tempfile.TemporaryDirectory(prefix='lk-species-') as tmp:
        root = Path(tmp)
        _input(root / 'run.in', {2: 'A'})
        _dump(root / 'run.dump', {2: 'A', 99: 'B'})
        text = (root / 'run.dump').read_text().replace('type element x', 'type x')
        text = text.replace(' A ', ' ').replace(' B ', ' ')
        (root / 'run.dump').write_text(text)
        _manifest(root / 'run.json', {'A': [2, 99]})
        paths = {'input': root / 'run.in', 'dump': root / 'run.dump',
                 'manifest': root / 'run.json'}
        for order in itertools.permutations(paths):
            shell = _shell()
            for kind in order[:-1]:
                _load(shell, kind, paths[kind])
            _error(lambda: _load(shell, order[-1], paths[order[-1]]), 'Conflicting', 'A')


if __name__ == '__main__':
    passed = failed = skipped = 0
    for name, test in sorted(list(globals().items())):
        if name.startswith('test_') and callable(test):
            try:
                with warnings.catch_warnings(record=True):
                    warnings.simplefilter('always')
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
    print(f'RESULT: {passed} passed, {failed} failed, {skipped} skipped')
    raise SystemExit(bool(failed))
