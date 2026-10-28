"""GEN-1 explicit metadata adapters and lazy dump identity regressions."""

import hashlib
import json
from pathlib import Path
import tempfile
from unittest import mock
import warnings

import _util  # noqa: F401
from _util import require, require_numpy


def _error(call, needle, cls=ValueError):
    """Require an explicit failure containing a useful source diagnostic."""
    try:
        call()
    except cls as exc:
        assert needle.lower() in str(exc).lower(), str(exc)
    else:
        raise AssertionError('expected ' + cls.__name__)


def _warn_error(call, needle):
    """Require both a visible runtime warning and rejection of bad metadata."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        _error(call, needle)
    assert any(issubclass(w.category, RuntimeWarning) and needle.lower() in str(w.message).lower()
               for w in caught), caught


def _data(rows):
    """Serialize sparse Masses without declaring a contradictory type count."""
    return ('Synthetic metadata\n\n0 atoms\n\n0 10 xlo xhi\n0 10 ylo yhi\n'
            '0 10 zlo zhi\n\nMasses\n\n' + '\n'.join(rows) + '\n\nAtoms # atomic\n')


def _frame(step, rows, columns='id type element x y z'):
    """Serialize arbitrary generic labels with orthogonal periodic geometry."""
    return '\n'.join(['ITEM: TIMESTEP', str(step), 'ITEM: NUMBER OF ATOMS',
                      str(len(rows)), 'ITEM: BOX BOUNDS pp pp pp', '0 10',
                      '0 10', '0 10', 'ITEM: ATOMS ' + columns, *rows]) + '\n'


def test_data_species_comments_and_sparse_ids():
    """Only exact single-label or species= comments assign explicit species."""
    require_numpy()
    from lammps_post.parsers import parse_data_file, parse_data_species
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'sparse system.data'
        path.write_text(_data(['2 11 # A', '7 12 # species=A', '9 13 # B',
                                    '13 14', '17 15 #', '21 16 # general prose',
                                    '22 17 # species=', '23 18 # species=X extra']))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            labels = parse_data_species(path)
        assert labels == {2: 'A', 7: 'A', 9: 'B'}
        assert len(caught) == 3
        assert all(issubclass(w.category, RuntimeWarning) and 'ambiguous' in str(w.message).lower()
                   for w in caught)
        atoms, box, masses = parse_data_file(path)
        assert atoms.shape == (0, 5) and box.shape == (3, 2)
        assert masses == {2: 11, 7: 12, 9: 13, 13: 14, 17: 15, 21: 16, 22: 17, 23: 18}


def test_data_species_validates_structural_ids_and_sections():
    """Metadata extraction inherits structural corruption checks and section boundaries."""
    require_numpy()
    from lammps_post.parsers import parse_data_species
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'system.data'
        for rows in (['0 12 # A'], ['-1 12 # A'], ['2.5 12 # A'],
                     ['2 12 # A', '2 12 # B'], ['2 -12 # A']):
            path.write_text(_data(rows))
            _error(lambda: parse_data_species(path), 'Masses')
        path.write_text(_data(['2 12 # A']).replace('Atoms # atomic', 'Pair Coeffs\n2 1 # B\n\nAtoms # atomic'))
        assert parse_data_species(path) == {2: 'A'}
        path.write_text(_data(['2 12 # A']).replace('0 atoms', '1 atoms'))
        _error(lambda: parse_data_species(path), 'count')
        path.write_text(_data([]).replace('Masses', 'Velocities'))
        assert parse_data_species(path) == {}


def test_manifest_optional_records_and_groups():
    """Manifests retain records and sparse overlapping explicit groups without physics guesses."""
    require_numpy()
    from lammps_post.parsers import parse_run_manifest
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'run metadata.json'
        path.write_text('{"schema_version": 1}')
        assert parse_run_manifest(path) == {'schema_version': 1, 'species_groups': {},
                                            'path': str(path.resolve())}
        payload = {'schema_version': 1, 'species_groups': {'A': [2, 7], 'X': [7, 9]},
                   'domain': 'example', 'system': {'name': 'generic system'},
                   'provenance': {'note': 'explicit metadata'}}
        path.write_text(json.dumps(payload))
        assert parse_run_manifest(path) == dict(payload, path=str(path.resolve()))


def test_manifest_rejects_bad_schema_groups_and_unknown_fields():
    """Schema validation rejects booleans, empty groups and duplicated LAMMPS metadata."""
    require_numpy()
    from lammps_post.parsers import parse_run_manifest
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'run.json'
        bad = [[], {}, {'schema_version': True}, {'schema_version': 1.0},
               {'schema_version': 2}, {'schema_version': 1, 'species_groups': []},
               {'schema_version': 1, 'domain': {}}, {'schema_version': 1, 'system': []},
               {'schema_version': 1, 'provenance': None}]
        bad += [{'schema_version': 1, key: {}} for key in
                ('atom_types', 'element_map', 'units', 'boundary', 'pair_style', 'dt_fs', 'path', 'unknown')]
        bad += [{'schema_version': 1, 'species_groups': group} for group in
                ({'': [2]}, {' ': [2]}, {'A': []}, {'A': [True]}, {'A': [0]},
                 {'A': [-1]}, {'A': [2.0]}, {'A': ['2']}, {'A': None}, {'A': {'2': 1}})]
        for payload in bad:
            path.write_text(json.dumps(payload))
            _error(lambda: parse_run_manifest(path), 'manifest')
        for text in ('{"schema_version":1,"schema_version":1}',
                     '{"schema_version":1,"species_groups":{"A":[2],"A":[7]}}',
                     '{"schema_version":1,"provenance":{"note":1,"note":2}}'):
            path.write_text(text)
            _error(lambda: parse_run_manifest(path), 'duplicate')
        path.write_text('{"schema_version":1,"provenance":{"value":NaN}}')
        _error(lambda: parse_run_manifest(path), 'manifest')


def test_manifest_hash_checks_bytes_and_relative_spaced_paths():
    """Hashes use manifest-relative bytes, including spaces and explicit parent references."""
    require_numpy()
    from lammps_post.parsers import parse_run_manifest
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'metadata').mkdir()
        source = root / 'source data.bin'
        source.write_bytes(b'generic\x00A\r\nB\xff')
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        path = root / 'metadata' / 'run.json'
        payload = {'schema_version': 1, 'provenance': {'file_hashes': {'../source data.bin': digest.upper()}}}
        path.write_text(json.dumps(payload))
        assert parse_run_manifest(path)['provenance'] == payload['provenance']
        source.write_bytes(b'changed')
        _warn_error(lambda: parse_run_manifest(path), 'hash mismatch')
        source.unlink()
        _error(lambda: parse_run_manifest(path), 'source data.bin', OSError)


def test_manifest_rejects_malformed_hash_records_and_missing_manifest():
    """Malformed hash declarations fail before metadata can be applied."""
    require_numpy()
    from lammps_post.parsers import parse_run_manifest
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'run.json'
        _error(lambda: parse_run_manifest(path), 'run.json', OSError)
        for hashes in ([], None, {'': '0' * 64}, {'/absolute': '0' * 64},
                       {'source': 'g' * 64}, {'source': 'a' * 63}, {'source': 12}):
            path.write_text(json.dumps({'schema_version': 1, 'provenance': {'file_hashes': hashes}}))
            _error(lambda: parse_run_manifest(path), 'manifest')


def _reader_access(reader, mode):
    """Return an iterator covering streaming, indexed, cached and uncached paths."""
    from lammps_post.parsers import LazyFrames
    if mode == 'stream':
        return iter(reader)
    if mode == 'index':
        index = reader.index()
        return (reader.read_frame(index, k) for k in range(len(index)))
    return iter(LazyFrames(reader, cache_bytes=10**6 if mode == 'cached' else 0))


def test_dump_unlabelled_raw_type_ids_are_lazy_and_projection_independent():
    """Raw sparse numeric IDs establish known types without force-field label guesses."""
    require_numpy()
    from lammps_post.parsers import DumpReader, LazyFrames
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'trajectory.dump'
        path.write_text(_frame(0, ['1 2 1 2 3'], 'id type x y z')
                        + _frame(1, ['1 7 2 3 4'], 'id type x y z'))
        for columns in (None, (), ('x',)):
            for mode in ('stream', 'index', 'cached', 'uncached'):
                reader = DumpReader(path, columns=columns)
                reader._native = None
                assert reader.type_ids == frozenset()
                frames = _reader_access(reader, mode)
                assert reader.type_ids == frozenset()
                next(frames)
                snapshot = reader.type_ids
                assert isinstance(snapshot, frozenset) and snapshot == frozenset({2})
                next(frames)
                assert snapshot == frozenset({2})
                assert reader.type_ids == frozenset({2, 7})
                assert reader.type_labels == {}
                _error(lambda: setattr(reader, 'type_ids', frozenset()), 'type_ids', AttributeError)
        reader = DumpReader(path)
        frames = LazyFrames(reader)
        assert len(frames) == 2 and reader.type_ids == frozenset()
        frames[1]
        assert reader.type_ids == frozenset({7})
        assert frames[1] is frames[1]
        frames[0]
        assert reader.type_ids == frozenset({2, 7})
        for limits in ({'stride': 2}, {'max_frames': 1}):
            reader = DumpReader(path, **limits)
            list(reader)
            assert reader.type_ids == frozenset({2})


def test_dump_unlabelled_invalid_or_failed_frames_do_not_commit_type_ids():
    """Projected numeric types are still validated and failed frames commit no partial IDs."""
    require_numpy()
    from lammps_post.parsers import DumpReader
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'trajectory.dump'
        for tid in ('0', '-2', '2.5', 'invalid'):
            path.write_text(_frame(0, ['1 2 1 2 3', f'2 {tid} 1 2 3'], 'id type x y z'))
            for columns in (None, (), ('x',)):
                for mode in ('stream', 'index', 'cached', 'uncached'):
                    reader = DumpReader(path, columns=columns)
                    reader._native = None
                    _error(lambda: list(_reader_access(reader, mode)), 'type')
                    assert reader.type_ids == frozenset()
                    assert reader.type_labels == {}
        path.write_text(_frame(0, ['1 2 1 2 3'], 'id type x y z')
                        + _frame(1, ['1 7 1 2 3', '2 9 broken 2 3'], 'id type x y z'))
        for mode in ('stream', 'index', 'cached', 'uncached'):
            reader = DumpReader(path)
            reader._native = None
            frames = _reader_access(reader, mode)
            next(frames)
            _error(lambda: next(frames), 'malformed')
            assert reader.type_ids == frozenset({2})


def test_dump_native_raw_type_ids_without_fallback():
    """Native parsing establishes unlabelled raw IDs even when no columns are retained."""
    require_numpy()
    import numpy as np
    from lammps_post import parsers
    require(parsers._native is not None, 'native parser not built (run native/build.sh)')

    def native_success(*args):
        """Require actual successful native parsing, including zero-column projections."""
        result = parsers._native.parse_block(*args)
        assert result[2] == args[1], 'native parser requested fallback'
        return result

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'trajectory.dump'
        path.write_text(_frame(0, ['1 2 1 2 3'], 'id type x y z')
                        + _frame(1, ['1 7 2 3 4'], 'id type x y z'))
        for dtype in (np.float32, np.float64):
            for columns in (None, (), ('x',)):
                for mode in ('stream', 'index', 'cached', 'uncached'):
                    reader = parsers.DumpReader(path, dtype=dtype, columns=columns)
                    assert reader._native is parsers._native
                    backend = mock.Mock()
                    backend.parse_block.side_effect = native_success
                    reader._native = backend
                    with mock.patch.object(np, 'loadtxt', side_effect=AssertionError('forbidden native fallback')):
                        list(_reader_access(reader, mode))
                    assert backend.parse_block.call_count == 2
                    assert reader.type_ids == frozenset({2, 7})
                    assert reader.type_labels == {}
        for tid in ('0', '-2', '2.5', 'invalid'):
            path.write_text(_frame(0, ['1 2 1 2 3'], 'id type x y z')
                            + _frame(1, ['1 7 1 2 3', f'2 {tid} 1 2 3'], 'id type x y z'))
            for columns in ((), ('x',)):
                for mode in ('stream', 'index', 'cached', 'uncached'):
                    reader = parsers.DumpReader(path, columns=columns)
                    backend = mock.Mock()
                    backend.parse_block.side_effect = native_success
                    reader._native = backend
                    with mock.patch.object(np, 'loadtxt', side_effect=AssertionError('forbidden native fallback')):
                        _error(lambda: list(_reader_access(reader, mode)), 'type')
                    assert backend.parse_block.call_count == 2
                    assert reader.type_ids == frozenset({2})
                    assert reader.type_labels == {}


def test_dump_type_labels_are_lazy_defensive_and_allow_atom_type_changes():
    """Only consumed raw type/element pairs contribute, regardless of numeric projection."""
    require_numpy()
    from lammps_post.parsers import DumpReader, LazyFrames
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'trajectory.dump'
        path.write_text(_frame(0, ['1 2 A 1 2 3']) + _frame(1, ['1 7 B 2 3 4']))
        for columns in (None, ('x',), ('element',), ()):
            for mode in ('stream', 'index', 'cached', 'uncached'):
                reader = DumpReader(path, columns=columns)
                reader._native = None
                assert reader.type_labels == {}
                frames = _reader_access(reader, mode)
                assert reader.type_labels == {}
                next(frames)
                assert reader.type_labels == {2: 'A'}
                assert reader.type_ids == frozenset({2})
                snapshot = reader.type_labels
                snapshot[2] = 'X'
                assert reader.type_labels == {2: 'A'}
                next(frames)
                assert reader.type_labels == {2: 'A', 7: 'B'}
                assert reader.type_ids == frozenset({2, 7})
                _error(lambda: setattr(reader, 'type_labels', {}), 'type_labels', AttributeError)
        reader = DumpReader(path)
        frames = LazyFrames(reader)
        assert reader.type_labels == {} and len(frames) == 2
        assert frames[1]['timestep'] == 1 and reader.type_labels == {7: 'B'}
        cached = frames[1]
        assert frames[1] is cached
        frames[0]
        assert reader.type_labels == {2: 'A', 7: 'B'}


def test_dump_type_label_conflicts_reject_every_access_and_projection():
    """Contradictory labels warn and reject atomically within or across consumed frames."""
    require_numpy()
    from lammps_post.parsers import DumpReader
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'trajectory.dump'
        for text in (_frame(0, ['1 2 A 1 2 3', '2 2 B 2 3 4']),
                     _frame(0, ['1 2 A 1 2 3']) + _frame(1, ['1 2 B 2 3 4'])):
            path.write_text(text)
            for columns in (None, ('x',), ()):
                for mode in ('stream', 'index', 'cached', 'uncached'):
                    reader = DumpReader(path, columns=columns)
                    reader._native = None
                    _warn_error(lambda: list(_reader_access(reader, mode)), 'type 2')
                    assert reader.type_labels == ({} if text.count('ITEM: TIMESTEP') == 1 else {2: 'A'})
                    assert reader.type_ids == (frozenset() if text.count('ITEM: TIMESTEP') == 1 else frozenset({2}))


def test_dump_bad_projected_type_and_failed_frame_do_not_assign_labels():
    """Raw explicit types remain integral/positive and failed frames do not partially commit."""
    require_numpy()
    from lammps_post.parsers import DumpReader
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'trajectory.dump'
        for tid in ('0', '-2', '2.5', 'invalid'):
            path.write_text(_frame(0, [f'1 {tid} A 1 2 3']))
            reader = DumpReader(path, columns=('x',))
            _error(lambda: list(reader), 'type')
            assert reader.type_labels == {}
        path.write_text(_frame(0, ['1 2 A 1 2 3', '2 7 B broken 2 3']))
        reader = DumpReader(path)
        _error(lambda: list(reader), 'malformed')
        assert reader.type_labels == {}
        path.write_text(_frame(0, ['1 2 A 1 2 3', '2 7 B 1 2 3', '3 7 X 1 2 3']))
        reader = DumpReader(path)
        _warn_error(lambda: list(reader), 'type 7')
        assert reader.type_labels == {}
        assert reader.type_ids == frozenset()


def test_dump_skipped_frames_and_element_only_have_no_authoritative_types():
    """Stride/max limits do not scan atom metadata or promote synthesized legacy types."""
    require_numpy()
    from lammps_post.parsers import DumpReader, LazyFrames
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'trajectory.dump'
        path.write_text(_frame(0, ['1 2 A 1 2 3']) + _frame(1, ['1 2 B 2 3 4'])
                        + _frame(2, ['1 2 A 3 4 5']))
        for reader in (DumpReader(path, stride=2), DumpReader(path, max_frames=1)):
            list(reader)
            assert reader.type_labels == {2: 'A'}
        reader = DumpReader(path)
        frames = LazyFrames(reader)
        frames[0]
        _warn_error(lambda: frames[1], 'type 2')
        assert frames[0]['timestep'] == 0
        path.write_text(_frame(0, ['1 A 1 2 3'], 'id element x y z'))
        reader = DumpReader(path)

        def synthesize_type(frame):
            """Append an actual legacy numeric type column, not authoritative metadata."""
            import numpy as np
            frame = dict(frame)
            frame['atoms'] = np.column_stack((frame['atoms'],
                                               np.full(len(frame['atoms']), 2)))
            return frame

        frames = list(LazyFrames(reader, transform=synthesize_type))
        assert frames[0]['atoms'].shape == (1, 5)
        assert frames[0]['atoms'][0, -1] == 2
        assert reader.type_labels == {}
        assert reader.type_ids == frozenset()


def test_dump_native_metadata_parity_without_numpy_fallback():
    """Prove native successes and conflict guards without calling the portable parser."""
    require_numpy()
    import numpy as np
    from lammps_post import parsers
    require(parsers._native is not None, 'native parser not built (run native/build.sh)')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'trajectory.dump'
        path.write_text(_frame(0, ['1 2 A 1 2 3']) + _frame(1, ['1 7 B 2 3 4']))
        for dtype in (np.float32, np.float64):
            for columns in (None, ('x',)):
                for mode in ('stream', 'index', 'cached', 'uncached'):
                    reader = parsers.DumpReader(path, dtype=dtype, columns=columns)
                    assert reader._native is parsers._native
                    with mock.patch.object(np, 'loadtxt', side_effect=AssertionError('forbidden native fallback')):
                        list(_reader_access(reader, mode))
                    assert reader.type_labels == {2: 'A', 7: 'B'}
        path.write_text(_frame(0, ['1 2 A 1 2 3']) + _frame(1, ['1 2 B 2 3 4']))
        for mode in ('stream', 'index', 'cached', 'uncached'):
            reader = parsers.DumpReader(path)
            with mock.patch.object(np, 'loadtxt', side_effect=AssertionError('forbidden native fallback')):
                _warn_error(lambda: list(_reader_access(reader, mode)), 'type 2')
