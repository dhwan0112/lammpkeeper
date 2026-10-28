"""Guard: DumpReader / parse_dump on synthetic dumps.

Covers the layouts the ACE fixture does not: a type+charge (ReaxFF-style) dump
with no element column, 1- and 0-atom frames, column selection, float32, and
the failure modes (truncated block, layout change) that must raise instead of
silently returning wrong data. Skips cleanly without numpy.
"""
import os
import tempfile

import _util  # noqa: F401  (path bootstrap)
from _util import have_numpy, skip


def _frame(step, rows, cols='id type q x y z', box=((0, 10), (0, 10), (0, 20))):
    """Serialize explicit rows without relying on the production dump writer."""
    head = [
       'ITEM: TIMESTEP', str(step),
       'ITEM: NUMBER OF ATOMS', str(len(rows)),
       'ITEM: BOX BOUNDS pp pp ff',
    ] + [f'{lo} {hi}' for lo, hi in box] + [f'ITEM: ATOMS {cols}']
    return '\n'.join(head + [' '.join(str(v) for v in r) for r in rows]) + '\n'


def _write(text):
    """Persist a synthetic dump; the calling test owns its temporary path."""
    fd, path = tempfile.mkstemp(suffix='.dump')
    with os.fdopen(fd, 'w') as f:
        f.write(text)
    return path


REAX_ROWS = [
   (1, 1, 0.12, 1.0, 2.0, 3.0),
   (2, 2, -0.55, 4.0, 5.0, 6.0),
   (3, 1, 0.40, 7.0, 8.0, 9.5),
]


def _expect_value_error(fn, needle):
    """Require malformed input to fail visibly with the relevant diagnostic."""
    try:
        fn()
    except ValueError as e:
        assert needle in str(e), str(e)
        return
    raise AssertionError(f'expected ValueError mentioning {needle!r}')


def test_type_charge_layout_without_elements():
    """Charge-bearing numeric dumps retain column indices, precision and box."""
    if not have_numpy():
        skip('numpy not installed')
    import numpy as np
    from lammps_post.parsers import parse_dump
    path = _write(_frame(0, REAX_ROWS) + _frame(100, REAX_ROWS))
    try:
        frames, columns, col_idx = parse_dump(path)
    finally:
        os.remove(path)
    assert columns == ['id', 'type', 'q', 'x', 'y', 'z']
    assert col_idx == {'id': 0, 'type': 1, 'q': 2, 'x': 3, 'y': 4, 'z': 5}
    assert [f['timestep'] for f in frames] == [0, 100]
    assert frames[0]['elements'] is None
    assert frames[0]['atoms'].dtype == np.float64
    assert np.array_equal(frames[1]['atoms'], np.array(REAX_ROWS, dtype=float))
    assert np.array_equal(frames[0]['box'], [[0, 10], [0, 10], [0, 20]])


def test_single_and_zero_atom_frames_keep_2d_shape():
    """Small populations must not collapse the atom matrix into a vector."""
    if not have_numpy():
        skip('numpy not installed')
    from lammps_post.parsers import parse_dump
    path = _write(_frame(0, REAX_ROWS[:1]) + _frame(1, []))
    try:
        frames, _, _ = parse_dump(path)
    finally:
        os.remove(path)
    assert frames[0]['atoms'].shape == (1, 6)
    assert frames[1]['atoms'].shape == (0, 6)


def test_column_selection_and_float32():
    """Numeric projection preserves requested precision and separate elements."""
    if not have_numpy():
        skip('numpy not installed')
    import numpy as np
    from lammps_post.parsers import DumpReader
    rows = [(7, 'Fe', 1.5, 2.5, 3.5, 0.1), (9, 'O', 4.5, 5.5, 6.5, 0.2)]
    path = _write(_frame(0, rows, cols='id element x y z vx'))
    try:
        r = DumpReader(path, columns=('element', 'x', 'z', 'no_such_col'), dtype=np.float32)
        frames = list(r)
    finally:
        os.remove(path)
    assert r.raw_columns == ['id', 'element', 'x', 'y', 'z', 'vx']
    assert r.columns == ['x', 'z'] and r.col_idx == {'x': 0, 'z': 1}
    atoms = frames[0]['atoms']
    assert atoms.dtype == np.float32
    assert np.array_equal(atoms, np.array([[1.5, 3.5], [4.5, 6.5]], dtype=np.float32))
    assert list(frames[0]['elements']) == ['Fe', 'O']
    assert frames[0]['elements'].dtype == np.dtype('U2')


def test_stride_and_max_frames():
    """Frame limits apply after stride selection; zero retains legacy no-limit behavior."""
    if not have_numpy():
        skip('numpy not installed')
    from lammps_post.parsers import DumpReader
    path = _write(''.join(_frame(s, REAX_ROWS) for s in range(10)))
    try:
        assert [f['timestep'] for f in DumpReader(path, stride=3)] == [0, 3, 6, 9]
        assert [f['timestep'] for f in DumpReader(path, stride=3, max_frames=2)] == [0, 3]
        assert len(list(DumpReader(path, max_frames=0))) == 10
    finally:
        os.remove(path)


def test_empty_file_matches_legacy_return():
    """Empty input keeps the public empty-result tuple rather than inventing metadata."""
    if not have_numpy():
        skip('numpy not installed')
    from lammps_post.parsers import parse_dump
    path = _write('')
    try:
        assert parse_dump(path) == ([], [], None)
    finally:
        os.remove(path)


def test_truncated_final_frame_raises():
    """A missing final atom must identify its timestep, not silently drop a frame."""
    if not have_numpy():
        skip('numpy not installed')
    from lammps_post.parsers import parse_dump
    text = _frame(0, REAX_ROWS) + _frame(100, REAX_ROWS)
    path = _write(text.rsplit('\n', 2)[0] + '\n')   # drop the last atom line
    try:
        _expect_value_error(lambda: parse_dump(path), 'step 100')
    finally:
        os.remove(path)


def test_partial_last_line_raises():
    """A cut numeric row is corruption even when it occurs at end of file."""
    if not have_numpy():
        skip('numpy not installed')
    from lammps_post.parsers import parse_dump
    path = _write((_frame(0, REAX_ROWS)).rstrip('\n')[:-4])  # cut mid-line
    try:
        _expect_value_error(lambda: parse_dump(path), 'step 0')
    finally:
        os.remove(path)


def _frames_equal(a, b):
    """Compare frame metadata, numeric dtype and values across reader paths."""
    import numpy as np
    assert a['timestep'] == b['timestep'] and a['natoms'] == b['natoms']
    assert np.array_equal(a['box'], b['box'])
    assert a['atoms'].dtype == b['atoms'].dtype and np.array_equal(a['atoms'], b['atoms'])
    if a['elements'] is None:
        assert b['elements'] is None
    else:
        assert list(a['elements']) == list(b['elements'])


def test_lazy_frames_match_parse_dump_at_any_cache_size():
    """Cached and budget-disabled lazy access retain eager-reader semantics."""
    if not have_numpy():
        skip('numpy not installed')
    import numpy as np
    from lammps_post.parsers import parse_dump, DumpReader, LazyFrames
    path = _write(''.join(_frame(s, REAX_ROWS[: 1 + s % 3]) for s in range(9)))
    try:
        for kw in ({}, {'stride': 2}, {'max_frames': 4}, {'stride': 3, 'max_frames': 2}):
            ref, _, _ = parse_dump(path, **kw)
            # The small budget disables caching by estimate; no LRU eviction is tested.
            for cache_bytes in (0, 200, 10 ** 9):   # stream / budget-disabled / cached
                lf = LazyFrames(DumpReader(path), cache_bytes=cache_bytes, **kw)
                assert len(lf) == len(ref) and bool(lf)
                for a, b in zip(ref, lf):
                    _frames_equal(a, b)
                _frames_equal(ref[-1], lf[-1])
                for a, b in zip(ref[1:], lf[1:]):
                    _frames_equal(a, b)
                assert np.array_equal(lf.boxes, [f['box'] for f in ref])
                assert list(lf.timesteps) == [f['timestep'] for f in ref]
    finally:
        os.remove(path)


def test_lazy_frames_transform_survives_eviction():
    """Re-read uncached frames must receive the transform just like iteration.

    Cache size zero forces reloads; this does not exercise an eviction algorithm.
    """
    if not have_numpy():
        skip('numpy not installed')
    from lammps_post.parsers import DumpReader, LazyFrames
    path = _write(''.join(_frame(s, REAX_ROWS) for s in range(4)))
    try:
        lf = LazyFrames(DumpReader(path), cache_bytes=0)
        lf.set_transform(lambda fr: dict(fr, atoms=fr['atoms'] * 2))
        assert all(fr['atoms'][0, 0] == 2.0 for fr in lf)
        assert lf[0]['atoms'][0, 0] == 2.0
    finally:
        os.remove(path)


def test_lazy_frames_raise_on_truncated_frame_access():
    """Indexing may discover a frame header, but accessing corrupt atoms must fail."""
    if not have_numpy():
        skip('numpy not installed')
    from lammps_post.parsers import DumpReader, LazyFrames
    text = _frame(0, REAX_ROWS) + _frame(100, REAX_ROWS)
    path = _write(text.rsplit('\n', 2)[0] + '\n')
    try:
        lf = LazyFrames(DumpReader(path))
        assert len(lf) == 2 and lf[0]['natoms'] == 3
        _expect_value_error(lambda: lf[-1], 'step 100')
    finally:
        os.remove(path)


def test_shell_streaming_load_matches_golden():
    """--cache-mb 0 re-parses every frame from disk; physics must not change."""
    if not have_numpy():
        skip('numpy not installed')
    from _util import FIXTURE, noninteractive, section_hash
    if not os.path.exists(FIXTURE):
        skip(f'fixture not found: {FIXTURE}')
    from test_regression_numeric import GOLDEN_FAST
    # Fingerprints catch cache-policy drift; they are not independent physics oracles.
    from lammps_post import analysis as A
    from lammps_post.shell import LammpsPostShell
    sh = LammpsPostShell()
    with noninteractive():
        sh.do_load(f'dump {FIXTURE} --cache-mb 0')
    s = sh.state
    assert s.dump_frames.cache_bytes == 0
    assert section_hash(dict(s.ff_info)) == GOLDEN_FAST['post_ff_info']
    assert section_hash(s._guess_o_type()) == GOLDEN_FAST['post_guess_o_type']
    spin = A.analyze_spin_evolution(s.dump_frames, s.dump_col_idx, dt_fs=s.dt_fs)
    assert section_hash(spin) == GOLDEN_FAST['spin']


def test_native_parser_matches_loadtxt():
    """The native-permitted reader must match NumPy for these selected examples.

    This test checks availability but permits fallback. Strict native-success
    coverage is supplied by species-metadata and Box-aware tests instead.
    """
    if not have_numpy():
        skip('numpy not installed')
    import numpy as np
    from lammps_post import parsers
    if parsers._native is None:
        # Without the extension, NumPy-only equality would falsely imply native coverage.
        skip('native parser not built (run native/build.sh)')
    from _util import FIXTURE
    rows = [(7, 'Fe', 1.5e-3, -2.5, 3.0000000000000004, '0.1'),
            (9, 'O', 4.5, 'inf', 6.5, '-1e-300'),
            (11, 'Fe', 0.1, 0.2, 0.30000000000000004, '7')]
    text = (_frame(0, rows, cols='id element x y z q')
            + _frame(1, rows[:1], cols='id element x y z q')
            + _frame(2, [], cols='id element x y z q'))
    path = _write(text)
    paths = [path] + ([FIXTURE] if os.path.exists(FIXTURE) else [])
    try:
        for p in paths:
            for columns in (None, ('element', 'x', 'z'), ('x', 'q')):
                for dtype in (np.float64, np.float32):
                    r = parsers.DumpReader(p, columns=columns, dtype=dtype, max_frames=5)
                    native = list(r)
                    r._native = None
                    ref = list(r)
                    assert len(native) == len(ref)
                    for a, b in zip(ref, native):
                        _frames_equal(a, b)
                        if a['elements'] is not None:
                            assert a['elements'].dtype == b['elements'].dtype
    finally:
        os.remove(path)

        # Malformed blocks fall back to loadtxt, which reports the error.
    bad = _frame(0, REAX_ROWS[:2] + [(3, 1, 'x0.4', 7.0, 8.0, 9.5)])
    blank = _frame(0, REAX_ROWS).replace('\n2 2', '\n\n2 2')
    for text, needle in ((bad, 'malformed'), (blank, 'atom lines')):
        path = _write(text)
        try:
            _expect_value_error(lambda: parsers.parse_dump(path), needle)
        finally:
            os.remove(path)


def test_shell_load_skips_unused_columns_unless_asked():
    """Projection saves memory without losing velocity metadata or z coordinates."""
    if not have_numpy():
        skip('numpy not installed')
    import numpy as np
    from _util import noninteractive
    from lammps_post.shell import LammpsPostShell
    rows = [r + (0.5, -0.5, 0.25) for r in REAX_ROWS]
    path = _write(_frame(0, rows, cols='id type q x y z vx vy vz'))
    try:
        for opts, cols in (('', ['id', 'type', 'q', 'x', 'y', 'z']),
                           ('--all-columns', ['id', 'type', 'q', 'x', 'y', 'z', 'vx', 'vy', 'vz'])):
            sh = LammpsPostShell()
            sh.state.output_dir = tempfile.mkdtemp(prefix='lkpr_test_')
            with noninteractive():
                sh.do_load(f'dump {path} {opts}')
            s = sh.state
            assert s.dump_columns == cols, s.dump_columns
            assert s.ff_info['has_velocity'] is True
            fr = s.dump_frames[0]
            assert fr['atoms'].dtype == np.float64
            assert np.array_equal(fr['atoms'][:, s.dump_col_idx['z']], [r[5] for r in rows])
    finally:
        os.remove(path)


def test_layout_change_raises():
    """A changing column schema cannot be interpreted using the first-frame map."""
    if not have_numpy():
        skip('numpy not installed')
    from lammps_post.parsers import parse_dump
    rows_xyz = [r[:2] + r[3:] for r in REAX_ROWS]
    path = _write(_frame(0, REAX_ROWS) + _frame(100, rows_xyz, cols='id type x y z'))
    try:
        _expect_value_error(lambda: parse_dump(path), 'column layout changes')
    finally:
        os.remove(path)
