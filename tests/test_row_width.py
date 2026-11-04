"""REV-IO-3: every dump atom row must have exactly the header's column count.

A column projection used to read only the selected fields, so a short row such
as `1 2` under `ITEM: ATOMS x y z` was accepted when only `x` was requested.
The width is now checked on the raw row before projection, on the native and
NumPy paths and on every access path (iteration, index + read_frame,
LazyFrames, parse_dump). Short and long rows raise ValueError naming the file,
timestep and row. Valid dumps are unchanged.
"""

from pathlib import Path
import tempfile
from unittest import mock

import _util  # noqa: F401
from _util import require, require_numpy

LAYOUTS = {
    'x y z': ['1 2 3', '4 5 6'],
    'id type x y z': ['1 1 1 2 3', '2 1 4 5 6'],
    'id type element x y z': ['1 1 A 1 2 3', '2 1 A 4 5 6'],
    'x y z vx': ['1 2 3 7', '4 5 6 8'],
}


def _dump(columns, rows, step=5):
    """Serialize one 'pp pp ff' frame with the given atom rows."""
    return '\n'.join(['ITEM: TIMESTEP', str(step), 'ITEM: NUMBER OF ATOMS', str(len(rows)),
                      'ITEM: BOX BOUNDS pp pp ff', '0 10', '0 10', '0 10',
                      'ITEM: ATOMS ' + columns, *rows]) + '\n'


def _backends():
    """Yield (name, force_numpy); native only when the module is loaded."""
    from lammps_post import parsers
    yield 'numpy', True
    if parsers._native is not None:
        yield 'native', False


def _reader(path, columns, force_numpy):
    """Build a reader; force_numpy detaches the native parser from it."""
    from lammps_post import parsers
    reader = parsers.DumpReader(path, columns=columns)
    if force_numpy:
        reader._native = None
    return reader


def _access_paths(path, columns, force_numpy):
    """Yield (name, thunk) loading frame 0 through each public access path."""
    from lammps_post import parsers

    def iterate():
        """Frame 0 through plain iteration of the reader."""
        return next(iter(_reader(path, columns, force_numpy)))

    def indexed():
        """Frame 0 through the index + read_frame path."""
        reader = _reader(path, columns, force_numpy)
        return reader.read_frame(reader.index(), 0)

    def lazy():
        """Frame 0 through LazyFrames indexing."""
        return parsers.LazyFrames(_reader(path, columns, force_numpy))[0]

    yield 'iter', iterate
    yield 'read_frame', indexed
    yield 'lazy', lazy
    if not force_numpy:
        # parse_dump builds its own reader, so it follows the module backend.
        yield 'parse_dump', lambda: parsers.parse_dump(path, columns=columns)[0][0]
    else:
        def parse_dump():
            """Frame 0 through parse_dump() with the native parser disabled."""
            with mock.patch.object(parsers, '_native', None):
                return parsers.parse_dump(path, columns=columns)[0][0]
        yield 'parse_dump', parse_dump


def _projections(layout):
    """Return the projections to test: full, and the first column only."""
    return [None, (layout.split()[0],)]


def _with_file(text, fn):
    """Write text to a temp dump and call fn(path)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'w.dump'
        path.write_text(text)
        return fn(path)


def test_bad_row_width_rejected_on_every_path():
    """Short and long rows raise ValueError naming file, step and row, everywhere."""
    require_numpy()
    for layout, rows in LAYOUTS.items():
        width = len(layout.split())
        short = rows[1].rsplit(' ', 1)[0]
        for label, bad in (('short', short), ('long', rows[1] + ' 9')):
            text = _dump(layout, [rows[0], bad])
            for columns in _projections(layout):
                for backend, force in _backends():
                    def run(path):
                        """Expect the located width ValueError from every access path."""
                        for name, thunk in _access_paths(path, columns, force):
                            try:
                                thunk()
                            except ValueError as e:
                                msg = str(e)
                                assert 'w.dump' in msg and 'step 5' in msg, msg
                                assert 'row 2' in msg, msg
                                assert f'expected {width}' in msg, msg
                                continue
                            raise AssertionError(
                                f'{backend}/{name}: {label} row accepted, layout={layout!r}, '
                                f'columns={columns}')
                    _with_file(text, run)
    require(any(n == 'native' for n, _ in _backends()),
            'native parser not built: only NumPy path checked')


def test_valid_rows_unchanged_without_numpy_fallback():
    """Valid dumps parse on every path; native success never calls np.loadtxt."""
    require_numpy()
    import numpy as np
    from lammps_post import parsers
    for layout, rows in LAYOUTS.items():
        text = _dump(layout, rows)
        for columns in _projections(layout):
            results = {}
            for backend, force in _backends():
                def run(path):
                    """Collect frame 0 from every access path; native must not fall back."""
                    for name, thunk in _access_paths(path, columns, force):
                        if backend == 'native':
                            with mock.patch.object(np, 'loadtxt',
                                                   side_effect=AssertionError('fallback used')):
                                frame = thunk()
                        else:
                            frame = thunk()
                        results[(backend, name)] = frame['atoms'].copy()
                _with_file(text, run)
            ref = results[('numpy', 'iter')]
            for key, atoms in results.items():
                assert atoms.shape == ref.shape and (atoms == ref).all(), (key, layout, columns)
    require(parsers._native is not None, 'native parser not built (run native/build.sh)')
