"""GEN-3 opt-in restricted-triclinic dump/data IO compatibility checks."""

from pathlib import Path
import tempfile
from unittest import mock
import warnings

import _util  # noqa: F401
from _util import require_numpy, skip


def _error(call, needle):
    """Require malformed or unsupported input to fail with an explicit reason."""
    try:
        call()
    except ValueError as exc:
        assert needle.lower() in str(exc).lower(), str(exc)
    else:
        raise AssertionError('expected ValueError mentioning ' + needle)


def _dump(step=0, tilt=(2, -3, -4), lo=(4, -6, 2), lengths=(10, 12, 14),
          flags='pp ff pp', columns='id type element x y z', rows=None):
    """Serialize bounds using independent LAMMPS enclosing-bound arithmetic."""
    xy, xz, yz = tilt
    outer = ((lo[0] + min(0, xy, xz, xy + xz),
              lo[0] + lengths[0] + max(0, xy, xz, xy + xz), xy),
             (lo[1] + min(0, yz), lo[1] + lengths[1] + max(0, yz), xz),
             (lo[2], lo[2] + lengths[2], yz))
    rows = ['1 2 A 5 -5 3', '2 7 B 6 -4 4'] if rows is None else rows
    return '\n'.join(['ITEM: TIMESTEP', str(step), 'ITEM: NUMBER OF ATOMS',
                      str(len(rows)), 'ITEM: BOX BOUNDS xy xz yz' + (' ' + flags if flags else ''),
                      *(' '.join(map(str, row)) for row in outer),
                      'ITEM: ATOMS ' + columns, *rows]) + '\n'


def _data(tilt='2 -3 -4 xy xz yz', atom='1 2 5 -5 3 2 -1 4'):
    """Serialize physical data bounds and optional image flags without unwrapping."""
    return ('Synthetic restricted cell\n\n1 atoms\n\n4 14 xlo xhi\n-6 6 ylo yhi\n'
            '2 16 zlo zhi\n' + tilt + '\n\nMasses\n\n2 11 # A\n'
            '7 12 # species=B\n9 13 # ambiguous prose\n\nAtoms # atomic\n\n' + atom + '\n')


def _padded_dump(**kwargs):
    """Keep every source line at equal byte width so foreign offsets look valid."""
    return ''.join(line.ljust(80) + '\n' for line in _dump(**kwargs).splitlines())


def _assert_cell(frame, tilt, lo=(4, -6, 2), lengths=(10, 12, 14), pbc=(True, False, True)):
    """Compare physical parameters and determinant to independent fixed numbers."""
    import numpy as np
    from lammpkeeper.io import Box
    cell = frame['cell']
    assert isinstance(cell, Box)
    assert tuple(cell.lo) == lo and tuple(cell.tilt) == tuple(tilt)
    assert cell.pbc == pbc
    assert np.array_equal(cell.lengths, lengths)
    assert np.array_equal(frame['box'], np.column_stack((lo, np.array(lo) + lengths)))
    assert np.array_equal(frame['box'], cell.bounds)
    assert tuple(frame['tilt']) == tuple(tilt)
    assert np.isclose(cell.volume, 1680)


def test_box_model_keyword_and_legacy_rejection():
    """The new API is explicit and leaves legacy schemas and rejection unchanged."""
    require_numpy()
    from lammps_post.parsers import DumpReader, parse_dump, parse_data_file, parse_data_species
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'cell.dump'
        path.write_text(_dump())
        for call in (lambda: DumpReader(path), lambda: parse_dump(path)):
            _error(call, 'triclinic')
        reader = DumpReader(path, box_model=True)
        assert reader.box_model is True
        _assert_cell(next(iter(reader)), (2, -3, -4))
        path.write_text(_dump(tilt=(0, 0, 0)).replace(' xy xz yz', '')
                        .replace('4 14 0', '4 14').replace('-6 6 0', '-6 6').replace('2 16 0', '2 16'))
        plain = next(iter(DumpReader(path)))
        assert 'cell' not in plain and 'tilt' not in plain
        assert DumpReader(path).box_model is False
        _assert_cell(next(iter(DumpReader(path, box_model=True))), (0, 0, 0))
        path = Path(tmp) / 'cell.data'
        path.write_text(_data())
        _error(lambda: parse_data_file(path), 'triclinic')
        _error(lambda: parse_data_species(path), 'triclinic')


def test_dump_physical_bounds_tilt_signs_and_volume():
    """Both tilt signs and nonzero origins distinguish true bounds from an AABB."""
    require_numpy()
    import numpy as np
    from lammps_post.parsers import parse_dump
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'cell.dump'
        for tilt in ((2, -3, -4), (-2, 3, 4), (2, 3, -4), (-2, -3, 4)):
            path.write_text(_dump(tilt=tilt))
            frames, columns, col_idx = parse_dump(path, box_model=True)
            _assert_cell(frames[0], tilt)
            assert columns == ['id', 'type', 'x', 'y', 'z'] and col_idx['x'] == 2
            assert np.array_equal(frames[0]['atoms'][:, 2:], [[5, -5, 3], [6, -4, 4]])
            assert frames[0]['cell'].volume < (10 + abs(tilt[0]) + abs(tilt[1])) * (12 + abs(tilt[2])) * 14


def test_dump_all_access_paths_keep_per_frame_cells_and_projection():
    """Index, slices, caches, transforms and shared delivery retain full cells."""
    require_numpy()
    import numpy as np
    from lammps_post.parsers import DumpReader, LazyFrames, parse_dump
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'dynamic.dump'
        path.write_text(_dump() + _dump(1, tilt=(-2, 3, 4), lo=(5, -6, 2)) +
                        _dump(2, tilt=(1, 2, 3), lengths=(11, 12, 14)))
        expected, columns, _ = parse_dump(path, columns=['element', 'type'], box_model=True)
        assert columns == ['type']
        for cache_bytes in (0, 10**6):
            reader = DumpReader(path, columns=['element', 'type'], box_model=True)
            index = reader.index()
            assert not reader.type_ids and not reader.type_labels
            lazy = LazyFrames(reader, index=index, cache_bytes=cache_bytes)
            lazy.set_transform(lambda fr: dict(fr, transformed=True))
            assert lazy.boxes.shape == (3, 3, 2)
            assert np.array_equal(lazy.boxes, [fr['box'] for fr in expected])
            for k in range(3):
                for actual in (reader.read_frame(index, k), lazy[k], list(reader)[k], lazy[::-1][2 - k]):
                    assert np.array_equal(actual['box'], expected[k]['box'])
                    assert actual['cell'].lo == expected[k]['cell'].lo
                    assert actual['cell'].tilt == expected[k]['cell'].tilt
                    assert tuple(actual['tilt']) == tuple(expected[k]['tilt'])
                    assert np.array_equal(actual['atoms'], expected[k]['atoms'])
                    assert list(actual['elements']) == ['A', 'B']
            assert lazy[0]['transformed']
            with lazy.shared_pass():
                assert [fr['cell'].tilt for fr in lazy] == [fr['cell'].tilt for fr in expected]
            assert reader.type_ids == frozenset((2, 7)) and reader.type_labels == {2: 'A', 7: 'B'}


def test_indexed_cell_bounds_consistency_precedes_atom_evidence():
    """Reject contradictory compatibility bounds without reconstructing a cell."""
    require_numpy()
    import numpy as np
    from lammps_post.parsers import DumpReader
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'cell.dump'
        path.write_text(_dump())
        reader = DumpReader(path, box_model=True)
        index = reader.index()
        frame = reader.read_frame(index, 0)
        frame['box'][0, 0] = -999
        assert np.array_equal(reader.read_frame(index, 0)['box'], index.cells[0].bounds)
        other = DumpReader(path, box_model=True)
        index.boxes[0, 0, 0] = -999
        _error(lambda: other.read_frame(index, 0), 'box/cell')
        assert not other.type_ids and not other.type_labels


def test_dump_index_rejects_foreign_equal_offset_geometry_before_evidence():
    """Same offsets and physical bounds cannot make another source index valid."""
    require_numpy()
    import numpy as np
    from lammps_post.parsers import DumpReader, LazyFrames
    with tempfile.TemporaryDirectory() as tmp:
        path_a, path_b = Path(tmp) / 'a.dump', Path(tmp) / 'b.dump'
        path_a.write_text(_padded_dump(tilt=(2, -3, -4)))
        for tilt, flags in (((-2, 3, 4), 'pp ff pp'), ((2, -3, -4), 'ff pp ff')):
            path_b.write_text(_padded_dump(tilt=tilt, flags=flags,
                                           rows=['3 9 X 7 -3 5', '4 11 Y 8 -2 6']))
            reader_a = DumpReader(path_a, box_model=True)
            reader_b = DumpReader(path_b, box_model=True)
            index_a, index_b = reader_a.index(), reader_b.index()
            assert np.array_equal(index_a.block_start, index_b.block_start)
            assert np.array_equal(index_a.block_end, index_b.block_end)
            assert np.array_equal(index_a.boxes, index_b.boxes)
            assert path_a.stat().st_size == path_b.stat().st_size
            for reader, foreign in ((reader_a, index_b), (reader_b, index_a)):
                with mock.patch.object(reader, '_parse_block', side_effect=AssertionError('atom parsing forbidden')):
                    _error(lambda: reader.read_frame(foreign, 0), 'index source')
                    _error(lambda: LazyFrames(reader, index=foreign)[0], 'index source')
                assert not reader.type_ids and not reader.type_labels


def test_dump_index_same_source_sharing_ignores_projection_dtype_and_limits():
    """Compatible readers share geometry without tying indexes to atom backends."""
    require_numpy()
    import numpy as np
    from lammps_post.parsers import DumpReader, LazyFrames
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'shared.dump'
        path.write_text(_padded_dump() + _padded_dump(step=1, tilt=(-2, 3, 4)))
        producer = DumpReader(path, box_model=True, stride=2, max_frames=1)
        index = producer.index()
        assert len(index) == 2 and not producer.type_ids and not producer.type_labels
        for dtype in (np.float32, np.float64):
            for columns in (None, ['type', 'element'], ['x'], []):
                for use_numpy in (False, True):
                    reader = DumpReader(path, box_model=True, columns=columns, dtype=dtype,
                                        stride=3, max_frames=1)
                    if use_numpy:
                        reader._native = None
                    frame = reader.read_frame(index, 1)
                    assert frame['timestep'] == 1 and tuple(frame['tilt']) == (-2, 3, 4)
                    assert frame['atoms'].dtype == dtype
                    assert frame['atoms'].shape == (2, len(reader.columns))
                    assert reader.type_ids == frozenset((2, 7)) and reader.type_labels == {2: 'A', 7: 'B'}
                    lazy = LazyFrames(reader, index=index, stride=1, max_frames=None)
                    assert len(lazy) == 2
                    assert [fr['timestep'] for fr in lazy] == [0, 1]
        assert not producer.type_ids and not producer.type_labels


def test_dump_index_stale_source_rejected_by_fresh_reader_before_evidence():
    """A fresh reader cannot validate an old index merely by validating itself."""
    require_numpy()
    from lammps_post.parsers import DumpReader
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'changed.dump'
        path.write_text(_padded_dump())
        original = DumpReader(path, box_model=True)
        old_index = original.index()
        path.write_text(_padded_dump(tilt=(-2, 3, 4), rows=['3 9 X 7 -3 5', '4 11 Y 8 -2 6']))
        fresh = DumpReader(path, box_model=True)
        fresh._check_source()
        with mock.patch.object(fresh, '_parse_block', side_effect=AssertionError('atom parsing forbidden')):
            _error(lambda: fresh.read_frame(old_index, 0), 'index source')
        assert not fresh.type_ids and not fresh.type_labels
        _error(lambda: original.read_frame(old_index, 0), 'source changed')


def test_dump_index_rejects_unbound_and_incompatible_header_contracts():
    """Mode, raw layout and boundary metadata are part of index compatibility."""
    require_numpy()
    from lammps_post.parsers import DumpReader, DumpIndex
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'orthogonal.dump'
        text = _dump(tilt=(0, 0, 0)).replace(' xy xz yz', '')
        text = text.replace('4 14 0', '4 14').replace('-6 6 0', '-6 6').replace('2 16 0', '2 16')
        path.write_text(text)
        legacy, aware = DumpReader(path), DumpReader(path, box_model=True)
        legacy_index, aware_index = legacy.index(), aware.index()
        unbound = DumpIndex()
        unbound.add(aware_index.timesteps[0], aware_index.natoms[0], aware_index.boxes[0],
                    aware_index.block_start[0], aware_index.block_end[0], cell=aware_index.cells[0])
        unbound.finalize()
        for reader, index, reason in ((legacy, aware_index, 'index contract'),
                                       (aware, legacy_index, 'index contract'),
                                       (aware, unbound, 'unbound index')):
            with mock.patch.object(reader, '_parse_block', side_effect=AssertionError('atom parsing forbidden')):
                _error(lambda: reader.read_frame(index, 0), reason)
            assert not reader.type_ids and not reader.type_labels
        for changed in ('layout', 'boundary'):
            reader = DumpReader(path, box_model=True)
            if changed == 'layout':
                reader.raw_columns[1] = 'q'
            else:
                reader.boundary = ('ff', 'pp', 'ff')
            with mock.patch.object(reader, '_parse_block', side_effect=AssertionError('atom parsing forbidden')):
                _error(lambda: reader.read_frame(aware_index, 0), 'index contract')
            assert not reader.type_ids and not reader.type_labels


def test_zero_tilt_and_unknown_boundary_metadata():
    """Zero-tilt restricted headers are orthogonal and missing flags stay unknown."""
    require_numpy()
    from lammps_post.parsers import DumpReader
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'cell.dump'
        path.write_text(_dump(tilt=(0, 0, 0), flags='', columns='id type xs ys zs', rows=['1 2 .1 .2 .3']))
        reader = DumpReader(path, box_model=True)
        frame = next(iter(reader))
        assert frame['cell'].is_orthogonal and frame['cell'].pbc is None
        assert reader.boundary is None
        path.write_text(_dump(flags=''))
        _assert_cell(next(iter(DumpReader(path, box_model=True))), (2, -3, -4), pbc=None)


def test_dump_rejects_malformed_restricted_and_general_geometry():
    """Partial markers, malformed bounds and general cells never lose geometry."""
    require_numpy()
    from lammps_post.parsers import DumpReader
    baseline = _dump()
    bad = [(baseline.replace('xy xz yz', 'xy xz'), 'triclinic'),
           (baseline.replace('xy xz yz', 'abc origin'), 'triclinic'),
           (baseline.replace('xy xz yz', 'avec bvec cvec'), 'triclinic'),
           (baseline.replace('xy xz yz', 'xz xy yz'), 'triclinic'),
           (baseline.replace('xy xz yz ', ''), 'box'),
           (baseline.replace('1 16 2\n', '1 16\n'), 'box'),
           (baseline.replace('1 16 2\n', '1 16 2 8\n'), 'box'),
           (baseline.replace('1 16 2\n', 'nan 16 2\n'), 'box'),
           (baseline.replace('1 16 2\n', '1 16 inf\n'), 'box'),
           (baseline.replace('1 16 2\n', '1 2 2\n'), 'box'),
           (baseline.replace('pp ff pp', 'pp pp'), 'boundary')]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'bad.dump'
        for text, reason in bad:
            path.write_text(text)
            _error(lambda: DumpReader(path, box_model=True), reason)


def test_nonorthogonal_dump_requires_literal_cartesian_family_before_evidence():
    """Unsupported coordinate families cannot masquerade as interpreted xyz."""
    require_numpy()
    from lammps_post.parsers import DumpReader
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'coords.dump'
        for coordinates in ('xs ys zs', 'xu yu zu', 'xsu ysu zsu', 'x y zs', 'ix iy iz', 'q vx vy'):
            path.write_text(_dump(columns='id type element ' + coordinates))
            _error(lambda: DumpReader(path, box_model=True, columns=['type']), 'x, y, z')
        path.write_text(_dump(columns='id type element x y z xs xu ix',
                              rows=['1 2 A 5 -5 3 .1 25 2']))
        frame = next(iter(DumpReader(path, box_model=True, columns=['xs', 'xu', 'ix'])))
        assert list(frame['atoms'][0]) == [.1, 25, 2]


def test_later_geometry_and_boundary_errors_do_not_publish_atom_evidence():
    """All read paths validate each cell before consuming its new raw types."""
    require_numpy()
    from lammps_post.parsers import DumpReader
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'later.dump'
        later = _dump(1, rows=['3 9 X 5 -5 3'])
        for bad in (later.replace('1 16 2\n', '1 2 2\n'), later.replace('pp ff pp', 'pp pp pp')):
            path.write_text(_dump() + bad)
            reader = DumpReader(path, box_model=True, columns=[])
            frames = iter(reader)
            next(frames)
            _error(lambda: next(frames), 'box' if '1 2 2\n' in bad else 'boundary')
            assert reader.type_ids == frozenset((2, 7))
            assert reader.type_labels == {2: 'A', 7: 'B'}
            other = DumpReader(path, box_model=True)
            _error(other.index, 'box' if '1 2 2\n' in bad else 'boundary')
            assert not other.type_ids and not other.type_labels


def test_box_aware_payload_failure_and_source_change_preserve_metadata():
    """Malformed atom rows and source mutation retain existing atomicity guards."""
    require_numpy()
    from lammps_post.parsers import DumpReader, LazyFrames
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'atoms.dump'
        for mode in ('stream', 'index', 'cached', 'uncached'):
            path.write_text(_dump() + _dump(1, rows=['3 9 X 5 -5 3', '4 11 Y bad -4 4']))
            reader = DumpReader(path, box_model=True)
            if mode == 'stream':
                frames = iter(reader)
            elif mode == 'index':
                index = reader.index()
                frames = (reader.read_frame(index, k) for k in range(len(index)))
            else:
                frames = iter(LazyFrames(reader, cache_bytes=10**6 if mode == 'cached' else 0))
            next(frames)
            _error(lambda: next(frames), 'atom block')
            assert reader.type_ids == frozenset((2, 7)) and reader.type_labels == {2: 'A', 7: 'B'}
        path.write_text(_dump())
        reader = DumpReader(path, box_model=True)
        lazy = LazyFrames(reader)
        lazy[0]
        path.write_text(_dump(1))
        _error(lambda: lazy[0], 'source changed')
        _error(lambda: next(iter(reader)), 'source changed')
        assert reader.type_ids == frozenset((2, 7))


def test_box_aware_projected_types_and_integer_precision_remain_exact():
    """Projection validates raw types while preserving IDs beyond float32 precision."""
    require_numpy()
    import numpy as np
    from lammps_post.parsers import DumpReader
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'identity.dump'
        path.write_text(_dump(rows=['1 9007199254740993 A 5 -5 3']))
        reader = DumpReader(path, box_model=True, columns=['x'], dtype=np.float32)
        next(iter(reader))
        assert reader.type_ids == frozenset((9007199254740993,))
        path.write_text(_dump(rows=['16777217 2 A 5 -5 3']))
        _error(lambda: next(iter(DumpReader(path, box_model=True, dtype=np.float32))), 'precision')
        path.write_text(_dump(rows=['1 2.5 A 5 -5 3']))
        reader = DumpReader(path, box_model=True, columns=[])
        _error(lambda: next(iter(reader)), 'type')
        assert not reader.type_ids and not reader.type_labels


def test_box_aware_real_native_success_matches_numpy_without_fallback():
    """Use the real native atom parser and forbid fallback on successful fixtures."""
    require_numpy()
    import numpy as np
    from lammps_post import parsers
    if parsers._native is None:
        skip('native dump parser unavailable or LKPR_NO_NATIVE=1')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'native.dump'
        path.write_text(_dump() + _dump(1, tilt=(-2, 3, 4)))
        for dtype in (np.float32, np.float64):
            for columns in (None, ['type', 'element'], ['x'], []):
                reader = parsers.DumpReader(path, box_model=True, dtype=dtype, columns=columns)
                native = reader._native
                assert native is not None
                with mock.patch.object(reader, '_native', wraps=native) as tracked:
                    with mock.patch.object(np, 'loadtxt', side_effect=AssertionError('native fallback forbidden')):
                        actual = list(parsers.LazyFrames(reader))
                    assert tracked.parse_block.call_count == 2
                reference_reader = parsers.DumpReader(path, box_model=True, dtype=dtype, columns=columns)
                reference_reader._native = None
                expected = list(reference_reader)
                for a, b in zip(actual, expected):
                    assert np.array_equal(a['atoms'], b['atoms']) and a['atoms'].dtype == b['atoms'].dtype
                    assert np.array_equal(a['box'], b['box'])
                    assert a['cell'].tilt == b['cell'].tilt and a['cell'].pbc == b['cell'].pbc
                    assert (None if a['elements'] is None else list(a['elements'])) == (
                        None if b['elements'] is None else list(b['elements']))
                assert reader.type_ids == reference_reader.type_ids
                assert reader.type_labels == reference_reader.type_labels


def test_data_box_species_and_stored_cartesian_coordinates():
    """Data bounds are already physical, and images must not unwrap coordinates."""
    require_numpy()
    import numpy as np
    from lammps_post.parsers import read_data_file
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'cell.data'
        for tilt in ('2 -3 -4 xy xz yz', '-2 3 4 xy xz yz', '0 0 0 xy xz yz', ''):
            path.write_text(_data(tilt=tilt))
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                result = read_data_file(path, pbc=(True, False, True))
            assert set(result) == {'atoms', 'cell', 'masses', 'species'}
            assert np.array_equal(result['atoms'], [[1, 2, 5, -5, 3]])
            cell = result['cell']
            assert np.array_equal(cell.bounds, [[4, 14], [-6, 6], [2, 16]])
            assert cell.pbc == (True, False, True) and np.isclose(cell.volume, 1680)
            assert result['masses'] == {2: 11, 7: 12, 9: 13}
            assert result['species'] == {2: 'A', 7: 'B'}
            assert len(caught) == 1 and 'ambiguous' in str(caught[0].message)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            assert read_data_file(path)['cell'].pbc is None


def test_data_box_path_reuses_style_count_identity_and_mass_checks():
    """The opt-in path must not weaken any structural checks from legacy data IO."""
    require_numpy()
    from lammps_post.parsers import read_data_file
    baseline = _data().replace('9 13 # ambiguous prose\n', '')
    bad = [(baseline.replace('1 atoms', '2 atoms'), 'count'),
           (baseline.replace('2 11 # A', '2 -11 # A'), 'Masses'),
           (baseline.replace('7 12 # species=B', '2 12 # species=B'), 'Masses'),
           (baseline.replace('Atoms # atomic', 'Atoms # sphere'), 'style'),
           (baseline.replace('3 2 -1 4\n', '3 2.5 -1 4\n'), 'Atoms'),
           (baseline.replace('1 2 5 -5 3', '0 2 5 -5 3'), 'Atoms'),
           (baseline.replace('1 2 5 -5 3', '1 2 nan -5 3'), 'Atoms'),
           (baseline.replace('4 14 xlo xhi', '4 14 xlo xhi\n4 14 xlo xhi'), 'bounds'),
           (baseline.replace('4 14 xlo xhi', '4 14 xlo xhi\n4 14 2 xlo xhi'), 'bounds'),
           (baseline.replace('2 16 zlo zhi\n', ''), 'bounds'),
           (baseline.replace('2 -3 -4 xy xz yz', '2 -3 -4 avec'), 'triclinic'),
           (baseline.replace('2 -3 -4 xy xz yz', '2 -3 -4 abc origin'), 'triclinic'),
           (baseline.replace('2 -3 -4 xy xz yz', '2 -3 xy xz'), 'triclinic'),
           (baseline.replace('2 -3 -4 xy xz yz', '2 -3 nan xy xz yz'), 'tilt'),
           (baseline.replace('2 -3 -4 xy xz yz', '2 -3 -4 xy xz yz\n2 -3 -4 xy xz yz'), 'tilt')]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'bad.data'
        for text, reason in bad:
            path.write_text(text)
            _error(lambda: read_data_file(path), reason)


def test_data_supported_styles_and_species_grammar_match_legacy_validation():
    """Shared extraction keeps all supported atom styles and exact label grammar."""
    require_numpy()
    import numpy as np
    from lammps_post.parsers import read_data_file, parse_data_file, parse_data_species
    rows = {'atomic': '1 2 5 -5 3', 'charge': '1 2 -.5 5 -5 3',
            'full': '1 8 2 -.5 5 -5 3', 'molecular': '1 8 2 5 -5 3',
            'bond': '1 8 2 5 -5 3', 'angle': '1 8 2 5 -5 3'}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'styles.data'
        for style, row in rows.items():
            for images in ('', ' 2 -1 4'):
                text = _data(tilt='', atom=row + images).replace('Atoms # atomic', 'Atoms # ' + style)
                text = text.replace('9 13 # ambiguous prose', '9 13 # species=')
                path.write_text(text)
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter('always')
                    result = read_data_file(path)
                assert len(caught) == 1 and 'ambiguous' in str(caught[0].message)
                atoms, bounds, masses = parse_data_file(path)
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter('always')
                    species = parse_data_species(path)
                assert len(caught) == 1
                assert np.array_equal(result['atoms'], [[1, 2, 5, -5, 3]])
                assert np.array_equal(result['atoms'], atoms)
                assert np.array_equal(result['cell'].bounds, bounds)
                assert result['masses'] == masses and result['species'] == species == {2: 'A', 7: 'B'}
