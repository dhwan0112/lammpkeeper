"""REV-IO-2: a dump that changes during an active iteration must not be published.

An active DumpReader iterator used to accept a frame or type appended after
construction and published the new type, although a fresh source check rejects
the changed file. These tests mutate a real file between frames (append,
truncate, replace by rename, touch, delete) and require a ValueError before any
changed content is yielded or any new type is observed.
"""
import os
from pathlib import Path
import tempfile

import _util

NATOMS = 400            # ~7 KB per frame: bigger than one text-buffer read
NFRAMES = 6


def _frame(step, type_id=1, natoms=NATOMS):
    """Return one dump frame text; atom i has x = step + i / 1000 and the given type."""
    rows = ''.join('%d %d %.3f 1.0 1.0\n' % (i + 1, type_id, step + i / 1000.0) for i in range(natoms))
    return ('ITEM: TIMESTEP\n%d\nITEM: NUMBER OF ATOMS\n%d\n'
            'ITEM: BOX BOUNDS pp pp pp\n0 100\n0 100\n0 100\n'
            'ITEM: ATOMS id type x y z\n%s' % (step, natoms, rows))


def _write(path, steps=range(NFRAMES), type_id=1):
    """Write a multi-frame single-type dump at `path`."""
    Path(path).write_text(''.join(_frame(s, type_id) for s in steps))


def _reader(path, **kw):
    """Return a DumpReader for `path` (lazy import keeps skip behaviour in _util)."""
    from lammps_post.parsers import DumpReader
    return DumpReader(str(path), **kw)


def _raises_changed(fn):
    """Assert fn() raises ValueError that says the source changed during reading."""
    try:
        fn()
    except ValueError as exc:
        assert 'changed during reading' in str(exc), str(exc)
        return str(exc)
    raise AssertionError('expected ValueError for a changed source')


def _drain_expect_change(reader, it, path):
    """Consume `it`; require the change error, no new type, and the file name in it."""
    msg = _raises_changed(lambda: list(it))
    assert Path(path).name in msg, msg
    assert reader.type_ids == frozenset({1}), reader.type_ids


def test_unchanged_stream_is_exact():
    """Without mutation the stream yields every frame exactly as the file holds it."""
    _util.require(_util.have_numpy(), 'numpy missing')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 't.dump'
        _write(path)
        frames = list(_reader(path))
        assert [f['timestep'] for f in frames] == list(range(NFRAMES))
        for f in frames:
            assert f['atoms'].shape == (NATOMS, 5)
            assert abs(f['atoms'][3, 2] - (f['timestep'] + 0.003)) < 1e-9
        assert [f['timestep'] for f in _reader(path, stride=2)] == [0, 2, 4]
        assert [f['timestep'] for f in _reader(path, max_frames=2)] == [0, 1]
        assert list(_reader(Path(tmp) / 't.dump', columns=['x']))[0]['atoms'].shape == (NATOMS, 1)


def test_unchanged_fixture_streams():
    """The committed ACE fixture streams all 350 frames unchanged (no type column)."""
    _util.require(os.path.exists(_util.FIXTURE) and _util.have_numpy(), 'fixture/numpy missing')
    reader = _reader(_util.FIXTURE)
    n = sum(1 for _ in reader)
    assert n == 350 and reader.type_ids == frozenset()


def test_append_new_type_during_iteration():
    """A frame with a new type appended mid-stream is rejected before it is observed."""
    _util.require(_util.have_numpy(), 'numpy missing')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 't.dump'
        _write(path)
        reader = _reader(path)
        it = iter(reader)
        first = next(it)
        before = first['atoms'].copy()
        with open(path, 'a') as f:
            f.write(_frame(NFRAMES, type_id=2))
        _drain_expect_change(reader, it, path)
        assert (first['atoms'] == before).all()      # earlier frame untouched


def test_truncate_during_iteration():
    """Truncation at a frame boundary cannot end the pass as a silent short trajectory."""
    _util.require(_util.have_numpy(), 'numpy missing')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 't.dump'
        _write(path)
        it = iter(_reader(path))
        next(it)
        _write(path, steps=range(2))
        _raises_changed(lambda: list(it))


def test_replace_by_rename_during_iteration():
    """Replacing the file (new inode, new type in a later frame) is rejected."""
    _util.require(_util.have_numpy(), 'numpy missing')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 't.dump'
        _write(path)
        reader = _reader(path)
        it = iter(reader)
        next(it)
        other = Path(tmp) / 'other.dump'
        other.write_text(''.join(_frame(s, 2 if s >= 3 else 1) for s in range(NFRAMES)))
        os.replace(other, path)
        _drain_expect_change(reader, it, path)


def test_touch_same_size_during_iteration():
    """A same-size rewrite with a new mtime is detected; identical metadata is a stat limit."""
    _util.require(_util.have_numpy(), 'numpy missing')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 't.dump'
        _write(path)
        it = iter(_reader(path))
        next(it)
        st = os.stat(path)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
        _raises_changed(lambda: list(it))


def test_delete_during_iteration():
    """A vanished file is reported as changed, not as a clean end of stream."""
    _util.require(_util.have_numpy(), 'numpy missing')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 't.dump'
        _write(path)
        it = iter(_reader(path))
        next(it)
        os.remove(path)
        _raises_changed(lambda: list(it))


def test_change_with_strided_pass():
    """Skipped frames are checked too: a change while skipping still raises."""
    _util.require(_util.have_numpy(), 'numpy missing')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 't.dump'
        _write(path)
        reader = _reader(path, stride=2)
        it = iter(reader)
        next(it)
        with open(path, 'a') as f:
            f.write(_frame(NFRAMES, type_id=2))
        _drain_expect_change(reader, it, path)


def test_index_read_frame_and_lazyframes_see_change():
    """Indexed reads and LazyFrames (cache off) reject a changed file and publish no type."""
    _util.require(_util.have_numpy(), 'numpy missing')
    from lammps_post.parsers import LazyFrames
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 't.dump'
        _write(path)
        reader = _reader(path)
        index = reader.index()
        assert reader.read_frame(index, 0)['timestep'] == 0
        frames = LazyFrames(_reader(path), cache_bytes=0)
        assert frames[1]['timestep'] == 1
        with open(path, 'a') as f:
            f.write(_frame(NFRAMES, type_id=2))
        for call in (lambda: reader.read_frame(index, NFRAMES - 1),
                     lambda: reader.index(),
                     lambda: frames[2],
                     lambda: list(frames)):
            try:
                call()
            except ValueError as exc:
                assert 'changed' in str(exc), str(exc)
            else:
                raise AssertionError('changed source was accepted')
        assert 2 not in reader.type_ids and 2 not in frames.reader.type_ids


if __name__ == '__main__':
    import traceback
    failed = 0
    for name, fn in sorted(list(globals().items())):
        if name.startswith('test_'):
            try:
                fn()
                print('PASS', name)
            except Exception:
                failed += 1
                print('FAIL', name)
                traceback.print_exc()
    raise SystemExit(bool(failed))
