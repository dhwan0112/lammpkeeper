"""REV-IO-10: dump atom columns are separated by spaces or tabs only.

The native parser split atom rows on ASCII whitespace while the shared width
check and the NumPy reference split on Unicode whitespace (`str.split`,
`np.loadtxt`). A row containing a no-break space (U+00A0), a vertical tab or a
Unicode space therefore passed the width check and parsed differently on the
two backends: NumPy returned the written columns, native returned shifted
columns, both silently. Such a separator now raises ValueError naming the
file, timestep, row and code point before either backend runs, on every access
path and under any locale. LAMMPS writes only spaces, so valid dumps are
unchanged; tab-separated rows stay accepted.

NumPy and native are separate tests: a host without the native module records
PASS for the NumPy path and a named SKIP for native, and the native tests
forbid the `np.loadtxt` fallback so they cannot pass through NumPy.
"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest import mock

from _util import REPO_ROOT, dump_frame, require, require_numpy

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
STEP = 5
NATIVE_MISSING = 'native parser not built (run native/build.sh)'


def _dump(rows):
    """Serialize one 'pp pp ff' frame at STEP with the given atom rows."""
    return dump_frame(rows, COLUMNS, step=STEP)


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


def _require_native():
    from lammps_post import parsers
    require(parsers._native is not None, NATIVE_MISSING)


def _forbid_loadtxt():
    """Patch so a native test cannot pass by falling back to the NumPy reader."""
    import numpy as np
    return mock.patch.object(np, 'loadtxt', side_effect=AssertionError('forbidden native fallback'))


def _check_foreign_rejected(force_numpy):
    """Every FOREIGN separator raises ValueError (file, step, row, code point) on every path."""
    for label, sep in FOREIGN.items():
        # Second row, between type and x: the row keeps six str.split() tokens.
        bad = ROWS[1].replace(' ', sep, 2).replace(sep, ' ', 1)
        assert len(bad.split()) == 6, (label, bad)
        text = _dump([ROWS[0], bad])
        for columns in (None, ('x', 'y', 'z')):
            def run(path):
                for name, thunk in _access_paths(path, columns, force_numpy):
                    try:
                        thunk()
                    except ValueError as e:
                        msg = str(e)
                        assert 'w.dump' in msg and f'step {STEP}' in msg, msg
                        assert 'row 2' in msg, msg
                        assert f'U+{ord(sep):04X}' in msg, msg
                        continue
                    raise AssertionError(f'{name}: {label} separator accepted, columns={columns}')
            _with_file(text, run)


def _tab_results(force_numpy):
    """Return {(columns, access path): atoms} for a tab-separated dump."""
    text = _dump([row.replace(' ', '\t') for row in ROWS])
    results = {}
    for columns in (None, ('x', 'y', 'z')):
        def run(path):
            for name, thunk in _access_paths(path, columns, force_numpy):
                results[(columns, name)] = thunk()['atoms'].copy()
        _with_file(text, run)
    return results


def _expected(columns):
    import numpy as np
    expected = np.array([r.split() for r in ROWS], dtype=float)
    return expected if columns is None else expected[:, 2:5]


def test_foreign_separator_rejected_numpy():
    """Any non-ASCII or odd ASCII separator raises ValueError on the NumPy path."""
    require_numpy()
    _check_foreign_rejected(True)


def test_foreign_separator_rejected_native():
    """The same rejection on the native path, with the NumPy fallback forbidden."""
    require_numpy()
    _require_native()
    with _forbid_loadtxt():
        _check_foreign_rejected(False)


def test_foreign_separator_rejected_under_c_locale():
    """A C locale reports the row and code point, not UnicodeDecodeError.

    The streaming reader opens the dump as UTF-8 like read_frame decodes it;
    before, a locale-encoded open raised UnicodeDecodeError (a ValueError
    subclass) from the layout preflight on every access path.
    """
    require_numpy()
    code = ('import locale, sys\n'
            f'sys.path.insert(0, {os.path.join(REPO_ROOT, "tests")!r})\n'
            'print(locale.getpreferredencoding(False))\n'
            'import test_dump_whitespace as t\n'
            't._check_foreign_rejected(True)\n'
            'print("rejected on every path")\n')
    env = {**os.environ, 'LC_ALL': 'C', 'LANG': 'C', 'LC_CTYPE': 'C',
           'PYTHONUTF8': '0', 'PYTHONCOERCECLOCALE': '0'}
    proc = subprocess.run([sys.executable, '-c', code], cwd=REPO_ROOT, env=env,
                          capture_output=True, encoding='utf-8', errors='replace')
    encoding = proc.stdout.split('\n', 1)[0]
    require('utf' not in encoding.lower(), f'host keeps a UTF-8 locale under LC_ALL=C ({encoding})')
    assert proc.returncode == 0 and 'rejected on every path' in proc.stdout, \
        (encoding, proc.stderr[-800:])


def test_tab_separated_rows_numpy():
    """Tabs are an accepted separator; every access path returns the written values."""
    require_numpy()
    for (columns, name), atoms in _tab_results(True).items():
        expected = _expected(columns)
        assert atoms.shape == expected.shape and (atoms == expected).all(), (columns, name, atoms)


def test_tab_separated_rows_native_match_numpy():
    """The native parser returns the NumPy values for tabs, without the loadtxt fallback."""
    require_numpy()
    _require_native()
    with _forbid_loadtxt():
        native = _tab_results(False)
    reference = _tab_results(True)
    assert native.keys() == reference.keys()
    for key, atoms in native.items():
        assert atoms.shape == reference[key].shape and (atoms == reference[key]).all(), key


def test_row_number_follows_splitlines():
    """`_foreign_separator` numbers rows as the width check does: LF, CRLF and CR alike."""
    require_numpy()
    from lammps_post.parsers import _foreign_separator
    nbsp = ' '
    for ending in ('\n', '\r\n', '\r'):
        text = ending.join(['1 1 0.1', '2 1' + nbsp + '0.4', '3 1 0.7']) + ending
        assert _foreign_separator(text) == (2, nbsp), (repr(ending), _foreign_separator(text))
    assert _foreign_separator('1 1 0.1\n2 1 0.4\n' + nbsp) == (3, nbsp)
    assert _foreign_separator('1\x0b1') == (1, '\x0b')
    assert _foreign_separator('1 1\t0.1\r\n2 1 0.4\n') is None
