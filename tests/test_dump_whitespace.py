"""REV-IO-10: dump atom rows may be separated only by ASCII space, tab, CR, LF, FF.

The native parser split atom rows on ASCII whitespace while the shared width
check and the NumPy reference split on Unicode whitespace (`str.split`,
`np.loadtxt`). A row containing a no-break space (U+00A0), a vertical tab or a
Unicode space therefore passed the width check and parsed differently on the
two backends: NumPy returned the written columns, native returned shifted
columns, both silently. Such a separator now raises ValueError naming the
file, timestep, row and code point before either backend runs. LAMMPS writes
only spaces, so valid dumps are unchanged; tab-separated rows stay accepted.
"""

from pathlib import Path
import tempfile
from unittest import mock

import _util  # noqa: F401
from _util import require, require_numpy

# Separators that str.split()/np.loadtxt accept but the native parser does not.
FOREIGN = {
    'nbsp': ' ',
    'em space': ' ',
    'ideographic space': '　',
    'vertical tab': '\x0b',
    'unit separator': '\x1f',
}

COLUMNS = 'id type x y z vx'
ROWS = ['1 1 0.1 0.2 0.3 7', '2 1 0.4 0.5 0.6 8']


def _dump(rows, step=5):
    """Serialize one 'pp pp ff' frame with the given atom rows."""
    return '\n'.join(['ITEM: TIMESTEP', str(step), 'ITEM: NUMBER OF ATOMS', str(len(rows)),
                      'ITEM: BOX BOUNDS pp pp ff', '0 10', '0 10', '0 10',
                      'ITEM: ATOMS ' + COLUMNS, *rows]) + '\n'


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
        return next(iter(_reader(path, columns, force_numpy)))

    def indexed():
        reader = _reader(path, columns, force_numpy)
        return reader.read_frame(reader.index(), 0)

    def lazy():
        return parsers.LazyFrames(_reader(path, columns, force_numpy))[0]

    def parse_dump():
        if force_numpy:
            with mock.patch.object(parsers, '_native', None):
                return parsers.parse_dump(path, columns=columns)[0][0]
        return parsers.parse_dump(path, columns=columns)[0][0]

    yield 'iter', iterate
    yield 'read_frame', indexed
    yield 'lazy', lazy
    yield 'parse_dump', parse_dump


def _with_file(text, fn):
    """Write text to a temp dump (UTF-8) and call fn(path)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'w.dump'
        path.write_text(text, encoding='utf-8')
        return fn(path)


def test_foreign_separator_rejected_on_every_path():
    """Any non-ASCII or odd ASCII separator raises ValueError on both backends."""
    require_numpy()
    for label, sep in FOREIGN.items():
        # Second row, between type and x: the row keeps six str.split() tokens.
        bad = ROWS[1].replace(' ', sep, 2).replace(sep, ' ', 1)
        assert len(bad.split()) == 6, (label, bad)
        text = _dump([ROWS[0], bad])
        for columns in (None, ('x', 'y', 'z')):
            for backend, force in _backends():
                def run(path):
                    for name, thunk in _access_paths(path, columns, force):
                        try:
                            thunk()
                        except ValueError as e:
                            msg = str(e)
                            assert 'w.dump' in msg and 'step 5' in msg, msg
                            assert 'row 2' in msg, msg
                            assert f'U+{ord(sep):04X}' in msg, msg
                            continue
                        raise AssertionError(
                            f'{backend}/{name}: {label} separator accepted, columns={columns}')
                _with_file(text, run)
    require(any(n == 'native' for n, _ in _backends()),
            'native parser not built: only NumPy path checked')


def test_tab_separated_rows_identical_on_both_backends():
    """Tabs are an accepted separator; native and NumPy return the same values."""
    require_numpy()
    import numpy as np
    text = _dump([row.replace(' ', '\t') for row in ROWS])
    for columns in (None, ('x', 'y', 'z')):
        results = {}
        for backend, force in _backends():
            def run(path):
                for name, thunk in _access_paths(path, columns, force):
                    results[(backend, name)] = thunk()['atoms'].copy()
            _with_file(text, run)
        ref = results[('numpy', 'iter')]
        expected = np.array([r.split() for r in ROWS], dtype=float)
        if columns is not None:
            expected = expected[:, 2:5]
        assert ref.shape == expected.shape and (ref == expected).all(), (columns, ref)
        for key, atoms in results.items():
            assert atoms.shape == ref.shape and (atoms == ref).all(), (key, columns)
    require(any(n == 'native' for n, _ in _backends()),
            'native parser not built: only NumPy path checked')

