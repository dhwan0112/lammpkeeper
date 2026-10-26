"""Guard: periodicity from the dump's BOX BOUNDS flags.

- parse_boundary_flags / pbc_from_boundary read orthogonal and triclinic
  headers, and return None for a header without flags.
- DumpReader exposes the first frame's flags as `boundary`, independent of
  streaming/indexed/cached access and native/NumPy atom parsing (PARSE-1).
- analyze_msd unwraps only the axes `pbc` marks periodic, and rejects
  duplicate atom IDs instead of silently skipping malformed frames.
- The shell's _periodicity prefers the dump flags over the input file and the
  surface_z heuristic, and 'analyze msd' / 'analyze rdf' follow it.

Skips cleanly without numpy.
"""
import os
import tempfile

import _util  # noqa: F401  (path bootstrap)
from _util import have_numpy, noninteractive, skip


def _frame(step, rows, bounds='pp pp ff', box=((0, 10), (0, 10), (0, 20)),
           cols='id type x y z'):
    head = [
        'ITEM: TIMESTEP', str(step),
        'ITEM: NUMBER OF ATOMS', str(len(rows)),
        f'ITEM: BOX BOUNDS {bounds}'.rstrip(),
    ] + [f'{lo} {hi}' for lo, hi in box] + [f'ITEM: ATOMS {cols}']
    return '\n'.join(head + [' '.join(str(v) for v in r) for r in rows]) + '\n'


def _write(text):
    fd, path = tempfile.mkstemp(suffix='.dump')
    with os.fdopen(fd, 'w') as f:
        f.write(text)
    return path


def test_boundary_flags_from_header():
    from lammps_post.parsers import parse_boundary_flags, pbc_from_boundary
    assert parse_boundary_flags('ITEM: BOX BOUNDS pp pp ff\n') == ('pp', 'pp', 'ff')
    assert parse_boundary_flags('ITEM: BOX BOUNDS xy xz yz pp pp pp') == ('pp', 'pp', 'pp')
    assert parse_boundary_flags('ITEM: BOX BOUNDS pp pp fs') == ('pp', 'pp', 'fs')
    assert parse_boundary_flags('ITEM: BOX BOUNDS') is None
    assert parse_boundary_flags('ITEM: BOX BOUNDS xy xz yz') is None
    assert pbc_from_boundary(('pp', 'pp', 'ff')) == (True, True, False)
    assert pbc_from_boundary(('pp', 'pp', 'pp')) == (True, True, True)
    assert pbc_from_boundary(('pp', 'fm', 'pp')) == (True, False, True)
    assert pbc_from_boundary(None) is None


_BOUNDARY_CASES = (
    ('pp pp ff', ('pp', 'pp', 'ff'), (True, True, False)),
    ('pp pp pp', ('pp', 'pp', 'pp'), (True, True, True)),
    ('ff fs mm', ('ff', 'fs', 'mm'), (False, False, False)),
    ('', None, None),
)


def _read_paths(reader):
    """Exercise the atom-block entry points without changing reader metadata."""
    from lammps_post.parsers import LazyFrames
    from test_dump_reader import _frames_equal
    streamed = list(reader)
    index = reader.index()
    paths = {'stream': streamed,
             'indexed': [reader.read_frame(index, k) for k in range(len(index))]}
    for cache_bytes in (0, 10 ** 6):
        lazy = LazyFrames(reader, index=index, cache_bytes=cache_bytes)
        assert lazy.reader is reader
        assert lazy.fits_in_cache == bool(cache_bytes)
        frames = list(lazy)
        again = lazy[-1]
        _frames_equal(frames[-1], again)
        assert (again is frames[-1]) == bool(cache_bytes)
        paths[f'lazy-{cache_bytes}'] = frames
    return paths


def test_dump_reader_exposes_boundary():
    """NumPy parsing preserves flags, including unknown rather than guessed PBC."""
    if not have_numpy():
        skip('numpy not installed')
    import numpy as np
    from lammps_post.parsers import DumpReader, pbc_from_boundary
    from test_dump_reader import _frames_equal
    rows = [(1, 1, 1.0, 2.0, 3.0), (2, 2, 4.0, 5.0, 6.0)]
    for bounds, expected, pbc in _BOUNDARY_CASES:
        path = _write(_frame(0, rows, bounds) + _frame(100, rows[:1], bounds))
        try:
            reader = DumpReader(path)
            reader._native = None
            assert reader.boundary == expected, bounds
            assert pbc_from_boundary(reader.boundary) == pbc, bounds
            paths = _read_paths(reader)
            for frames in paths.values():
                assert len(frames) == 2
                for k, frame in enumerate(frames):
                    assert set(frame) == {'timestep', 'natoms', 'box', 'atoms', 'elements'}
                    assert frame['timestep'] == (0, 100)[k]
                    assert frame['natoms'] == (2, 1)[k]
                    assert np.array_equal(frame['atoms'], np.array(rows[:2 - k]))
                    assert frame['elements'] is None
                    _frames_equal(paths['stream'][k], frame)
            assert reader.boundary == expected, bounds
            assert pbc_from_boundary(reader.boundary) == pbc, bounds
        finally:
            os.remove(path)


def test_native_boundary_metadata_matches_numpy_without_fallback():
    """Require successful extension calls, not a native-enabled silent fallback."""
    if not have_numpy():
        skip('numpy not installed')
    import importlib.machinery
    from types import SimpleNamespace
    from unittest.mock import patch
    import numpy as np
    from lammps_post import parsers
    from test_dump_reader import _frames_equal
    native = parsers._native
    if native is None:
        skip('native parser unavailable or disabled (run native/build.sh; unset LKPR_NO_NATIVE)')
    assert any(native.__file__.endswith(suffix)
               for suffix in importlib.machinery.EXTENSION_SUFFIXES), native.__file__

    successful_calls = []

    def parse_block(*args):
        result = native.parse_block(*args)
        assert result[2] == args[1], 'native parser deferred to NumPy'
        successful_calls.append(result[2])
        return result

    rows = [(7, 'A', 1, 1.125, -2.5, 3.75),
            (9, 'B', 2, 4.5, 5.25, 6.125)]
    for bounds, expected, pbc in _BOUNDARY_CASES:
        path = _write(_frame(0, rows, bounds, cols='id element type x y z')
                      + _frame(100, rows[:1], bounds, cols='id element type x y z'))
        try:
            for dtype in (np.float64, np.float32):
                for columns in (None, ('id', 'x', 'z')):
                    reference = parsers.DumpReader(path, dtype=dtype, columns=columns)
                    reference._native = None
                    numpy_paths = _read_paths(reference)
                    reader = parsers.DumpReader(path, dtype=dtype, columns=columns)
                    assert reader._native is native
                    reader._native = SimpleNamespace(parse_block=parse_block)
                    assert reader.boundary == reference.boundary == expected, bounds
                    assert parsers.pbc_from_boundary(reader.boundary) == pbc, bounds
                    before = len(successful_calls)
                    with patch.object(np, 'loadtxt', side_effect=AssertionError(
                            'native parity test must not fall back to NumPy')):
                        native_paths = _read_paths(reader)
                    # 2 streamed + 2 indexed + 3 uncached + 2 cached block parses.
                    assert len(successful_calls) - before == 9
                    assert reader.boundary == reference.boundary == expected, bounds
                    assert parsers.pbc_from_boundary(reader.boundary) == pbc, bounds
                    assert reader.raw_columns == reference.raw_columns
                    assert reader.columns == reference.columns
                    assert reader.col_idx == reference.col_idx
                    for access, frames in native_paths.items():
                        assert len(frames) == len(numpy_paths[access]) == 2
                        for k, frame in enumerate(frames):
                            assert set(frame) == {'timestep', 'natoms', 'box',
                                                  'atoms', 'elements'}
                            _frames_equal(numpy_paths[access][k], frame)
                            assert frame['atoms'].dtype == dtype
                            if columns is None:
                                assert list(frame['elements']) == ['A', 'B'][:2 - k]
                                ref_elements = numpy_paths[access][k]['elements']
                                assert frame['elements'].dtype == ref_elements.dtype
                            else:
                                assert frame['elements'] is None
        finally:
            os.remove(path)


def test_bulk_fixture_boundary_metadata():
    if not have_numpy():
        skip('numpy not installed')
    from _util import FIXTURE
    from lammps_post.parsers import DumpReader, LazyFrames, pbc_from_boundary
    from test_dump_reader import _frames_equal
    if not os.path.exists(FIXTURE):
        skip(f'fixture not found: {FIXTURE}')
    reader = DumpReader(FIXTURE)
    assert reader.boundary == ('pp', 'pp', 'pp')
    assert pbc_from_boundary(reader.boundary) == (True, True, True)
    first = next(iter(reader))
    index = reader.index()
    _frames_equal(first, reader.read_frame(index, 0))
    for cache_bytes in (0, 10 ** 6):
        lazy = LazyFrames(reader, index=index, cache_bytes=cache_bytes, max_frames=1)
        _frames_equal(first, lazy[0])
        _frames_equal(first, next(iter(lazy)))
        assert lazy.reader.boundary == ('pp', 'pp', 'pp')
        assert pbc_from_boundary(lazy.reader.boundary) == (True, True, True)


def _z_crossing_frames():
    """One atom moving +1 A in z per frame across the z boundary of a 10 A cube."""
    import numpy as np
    col_idx = {'id': 0, 'type': 1, 'x': 2, 'y': 3, 'z': 4}
    box = np.array([[0.0, 10.0]] * 3)
    frames = []
    for k, z in enumerate((8.5, 9.5, 0.5, 1.5)):
        atoms = np.array([[1.0, 1.0, 5.0, 5.0, z]])
        frames.append({'timestep': k, 'box': box, 'atoms': atoms})
    return frames, col_idx


def test_msd_unwraps_z_only_when_periodic():
    if not have_numpy():
        skip('numpy not installed')
    import numpy as np
    from lammps_post.analysis import analyze_msd
    frames, col_idx = _z_crossing_frames()
    bulk = analyze_msd(frames, col_idx, pbc=(True, True, True))
    assert np.allclose(bulk['msd'], [0.0, 1.0, 4.0, 9.0])
    # Slab default leaves z alone, so the boundary crossing shows as a jump.
    slab = analyze_msd(frames, col_idx)
    assert np.allclose(slab['msd'], [0.0, 1.0, 64.0, 49.0])


def test_msd_rejects_duplicate_ids_instead_of_skipping_frames():
    if not have_numpy():
        skip('numpy not installed')
    import numpy as np
    from lammps_post.analysis import analyze_msd
    frames, col_idx = _z_crossing_frames()
    frames[2] = dict(frames[2], atoms=np.vstack([frames[2]['atoms']] * 2))
    # PHYS-2 physical justification: repeating the same ID is not a second atom.
    # Silently dropping its frame (the old expectation) also creates an unknown
    # sampling gap across which minimum-image unwrapping can miss crossings.
    # Reject the malformed trajectory, rather than bless a partial MSD series.
    try:
        analyze_msd(frames, col_idx, pbc=(True, True, True))
    except ValueError as exc:
        assert 'duplicate' in str(exc).lower() and '2' in str(exc)
    else:
        raise AssertionError('duplicate IDs must be rejected, not skipped')
    assert 'n_skipped' not in analyze_msd(_z_crossing_frames()[0], col_idx)


def test_shell_periodicity_prefers_dump_flags():
    if not have_numpy():
        skip('numpy not installed')
    from lammps_post.shell import LammpsPostShell
    rows = [(1, 1, 1.0, 2.0, 3.0), (2, 2, 4.0, 5.0, 6.0)]
    path = _write(_frame(0, rows, 'pp pp pp') + _frame(1, rows, 'pp pp pp'))
    try:
        sh = LammpsPostShell()
        sh.state.output_dir = tempfile.mkdtemp(prefix='lkpr_test_')
        with noninteractive():
            sh.do_load(f'dump {path}')
        s = sh.state
        # The dump says p p p; an input file saying p p f does not override it.
        s.input_config = {'boundary': ['p', 'p', 'f']}
        assert sh._periodicity() == ((True, True, True), 'dump')
        # Without dump flags: input file, then surface_z.
        s.dump_frames.reader.boundary = None
        assert sh._periodicity() == ((True, True, False), 'input')
        s.input_config = None
        s.surface_z = 5.0
        assert sh._periodicity() == ((True, True, False), 'surface_z')
        s.surface_z = None
        assert sh._periodicity() == ((True, True, True), 'surface_z')
    finally:
        os.remove(path)


def _crossing_dump(bounds):
    """Fe (type 1) fixed at z = 1 A; O (type 2) crossing z of a 10 A cube."""
    box = ((0, 10), (0, 10), (0, 10))
    text = ''
    for k, z in enumerate((8.5, 9.5, 0.5, 1.5)):
        rows = [(1, 1, 5.0, 5.0, 1.0), (2, 2, 5.0, 5.0, z)]
        text += _frame(k, rows, bounds, box)
    return _write(text)


def test_shell_msd_and_rdf_follow_dump_flags():
    if not have_numpy():
        skip('numpy not installed')
    import numpy as np
    from lammps_post.shell import LammpsPostShell
    for bounds, msd_o, z_pbc in (('pp pp pp', [0.0, 1.0, 4.0, 9.0], True),
                                 ('pp pp ff', [0.0, 1.0, 64.0, 49.0], False)):
        path = _crossing_dump(bounds)
        try:
            sh = LammpsPostShell()
            sh.state.output_dir = tempfile.mkdtemp(prefix='lkpr_test_')
            with noninteractive():
                sh.do_load(f'dump {path}')
                sh.do_set('types 1=Fe 2=O')
                sh._analyze_msd(['--species', 'O'], _batch=True)
                sh._analyze_rdf(['Fe-O', '--frames', '4'], _batch=True)
            s = sh.state
            assert np.allclose(s.cache['msd_O']['msd'], msd_o), (bounds, s.cache['msd_O'])
            # Fe-O z separations are 7.5, 8.5, 0.5, 0.5 A; across a periodic
            # z they are 2.5 and 1.5 A for the first two frames, so the two
            # z_pbc settings give different g(r).
            from lammps_post.analysis import compute_rdf

            def ref(flag):
                return compute_rdf(s.dump_frames, s.dump_col_idx, 1, 2, max_frames=4,
                                   label_a='Fe', label_b='O', z_pbc=flag)['g']
            got = s.cache['rdf_Fe-O']['g']
            assert np.array_equal(got, ref(z_pbc)), bounds
            assert not np.array_equal(got, ref(not z_pbc)), bounds
        finally:
            os.remove(path)
