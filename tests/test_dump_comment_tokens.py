"""REV-IO-4: '#' is ordinary text in dump atom rows, never comment syntax.

LAMMPS dump atom rows are whitespace-separated fields. The NumPy fallback
must not strip '#' tails, so a corrupted numeric token is rejected on the
native and NumPy paths alike, and a text label containing '#' parses the same
on both. Other formats (data file, log, input) keep their '#' comments and are
not touched here.
"""

from pathlib import Path
import tempfile
from unittest import mock

import _util  # noqa: F401
from _util import require, require_numpy


def _dump(rows, columns='id type element x y z'):
    """Serialize one ordinary 'pp pp ff' frame with the given atom rows."""
    return '\n'.join(['ITEM: TIMESTEP', '0', 'ITEM: NUMBER OF ATOMS', str(len(rows)),
                      'ITEM: BOX BOUNDS pp pp ff', '0 10', '0 10', '0 10',
                      'ITEM: ATOMS ' + columns, *rows]) + '\n'


def _read(text, force_numpy):
    """Read the frame; force_numpy detaches the native parser from the reader."""
    from lammps_post import parsers
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'c.dump'
        path.write_text(text)
        reader = parsers.DumpReader(path)
        if force_numpy:
            reader._native = None
        frames = list(reader)
        return frames[0], dict(reader.type_labels)


def _backends():
    """Yield (name, force_numpy); native is included only when it is loaded."""
    from lammps_post import parsers
    yield 'numpy', True
    if parsers._native is not None:
        yield 'native', False


def test_corrupted_numeric_token_is_rejected_on_every_path():
    """`3#CORRUPTED` must raise, not be silently truncated to 3."""
    require_numpy()
    for name, force in _backends():
        for row in ('1 1 A 1 2 3#CORRUPTED', '1 1 A 1 2#x 3', '1 1 A 1 2 #3'):
            try:
                _read(_dump([row]), force)
            except ValueError:
                continue
            raise AssertionError(f'{name}: row {row!r} was accepted')
    # Without the optional native module only the NumPy half ran; say so.
    require(any(n == 'native' for n, _ in _backends()),
            'native parser unavailable: only NumPy path checked')


def test_numeric_only_block_rejects_hash_token():
    """The no-element projection shares the fallback and must reject '#' too."""
    require_numpy()
    for name, force in _backends():
        try:
            _read(_dump(['1 1 1 2 3#bad'], 'id type x y z'), force)
        except ValueError:
            continue
        raise AssertionError(f'{name}: numeric-only corrupted row accepted')


def test_hash_in_element_label_parses_identically():
    """A label like `A#site` is plain text on the NumPy path, as on native."""
    require_numpy()
    from lammps_post import parsers
    text = _dump(['1 1 A#site 1 2 3', '2 1 A#site 4 5 6'])
    frame_np, labels_np = _read(text, True)
    assert list(frame_np['elements']) == ['A#site', 'A#site']
    assert frame_np['atoms'].tolist() == [[1, 1, 1, 2, 3], [2, 1, 4, 5, 6]]
    assert labels_np == {1: 'A#site'}
    require(parsers._native is not None, 'native parser not built (run native/build.sh)')
    import numpy as np

    with mock.patch.object(np, 'loadtxt', side_effect=AssertionError('forbidden native fallback')):
        frame_nat, labels_nat = _read(text, False)
    assert list(frame_nat['elements']) == list(frame_np['elements'])
    assert (frame_nat['atoms'] == frame_np['atoms']).all()
    assert labels_nat == labels_np


def test_valid_fixture_identical_on_both_paths():
    """The committed ACE fixture parses to equal arrays on native and NumPy."""
    require_numpy()
    from lammps_post import parsers
    require(parsers._native is not None, 'native parser not built (run native/build.sh)')
    import numpy as np
    a = parsers.DumpReader(_util.FIXTURE, max_frames=2)
    b = parsers.DumpReader(_util.FIXTURE, max_frames=2)
    b._native = None
    fa, fb = list(a), list(b)
    assert len(fa) == len(fb) == 2
    for x, y in zip(fa, fb):
        assert np.array_equal(x['atoms'], y['atoms'])
        assert list(x['elements']) == list(y['elements'])
