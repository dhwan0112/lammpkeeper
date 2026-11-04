"""REV-REF-3: CIF xyz symmetry operators are parsed by a complete grammar.

Malformed operators, wrong component counts and singular operators reject
visibly (``_parse_symop``, ``_apply_symop``, ``_expand_symmetry`` and the CIF
symmetry loop); valid built-in and P1 geometry is unchanged. Expected numbers
are written out by hand from the explicit matrices, not computed by the code
under test.
"""
import collections
import hashlib
from pathlib import Path
import tempfile

import _util

_CIF = '''data_test
_cell_length_a 4.0
_cell_length_b 4.0
_cell_length_c 4.0
{symmetry}
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
X1 X 0.1 0.2 0.3
'''

# (operator, rotation rows, translation): hand-written reference matrices.
_VALID = [
    ('x, y, z', [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [0, 0, 0]),
    ('-x, y+1/2, -z+1/2', [[-1, 0, 0], [0, 1, 0], [0, 0, -1]], [0, .5, .5]),
    ('1/2+x, 1/2-y, z', [[1, 0, 0], [0, -1, 0], [0, 0, 1]], [.5, .5, 0]),
    ('-y, x-y, z+1/3', [[0, -1, 0], [1, -1, 0], [0, 0, 1]], [0, 0, 1 / 3]),
    ('-x+y+2/3, -x+1/3, z+1/2+1/3', [[-1, 1, 0], [-1, 0, 0], [0, 0, 1]], [2 / 3, 1 / 3, 5 / 6]),
    ('X,Y,Z', [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [0, 0, 0]),
    (' x , y , z ', [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [0, 0, 0]),
    ('x+0.5, y-.25, z+1.', [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [.5, -.25, 1]),
    ('+x, -y, +z', [[1, 0, 0], [0, -1, 0], [0, 0, 1]], [0, 0, 0]),
    ('2*x-y, x, z', [[2, -1, 0], [1, 0, 0], [0, 0, 1]], [0, 0, 0]),
    ('-z, -x, -y', [[0, 0, -1], [-1, 0, 0], [0, -1, 0]], [0, 0, 0]),
]

# (operator, fragment the error must mention)
_MALFORMED = [
    ('garbage,y,z', "'garbage'"),
    ('x,y', 'exactly three'),
    ('x,y,z,1/2', 'exactly three'),
    ('x,,z', 'component 2 is empty'),
    (' , y, z', 'component 1 is empty'),
    ('x 1/2, y, z', 'without an explicit sign'),
    ('x y, y, z', 'without an explicit sign'),
    ('x/2, y, z', "unrecognized text '/2'"),
    ('x+, y, z', "unrecognized text '+'"),
    ('x+w, y, z', "unrecognized text '+w'"),
    ('x+1/0, y, z', 'zero denominator'),
    ('x;y;z', 'exactly three'),
    ('x+1/2), y, z', "unrecognized text ')'"),
    ('x, x, z', 'determinant 0'),
    ('2x, y, z', 'determinant 2'),
    ('x+y, x-y, z', 'determinant -2'),
    ('0x, y, z', 'determinant 0'),
]


def _raises(call, *fragments):
    """Assert ValueError whose message contains every fragment."""
    try:
        call()
    except ValueError as exc:
        for fragment in fragments:
            assert fragment in str(exc), (fragment, str(exc))
        return str(exc)
    raise AssertionError('ValueError expected')


def test_parse_symop_matches_hand_written_matrices():
    """Each supported operator form yields exactly its rotation and translation."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.references import _apply_symop, _parse_symop
    frac = np.array([.2, .3, .4])
    for text, rows, shift in _VALID:
        rotation, translation = _parse_symop(text)
        np.testing.assert_array_equal(rotation, rows)
        np.testing.assert_allclose(translation, shift, atol=1e-12)
        expected = np.array(rows, dtype=float) @ frac + np.array(shift, dtype=float)
        np.testing.assert_allclose(_apply_symop(text, frac), expected, atol=1e-12)
    # The F-REF-3 probe: 'garbage' used to contribute zero and pass through.
    np.testing.assert_allclose(_apply_symop('-y, x-y, z+1/3', frac), [-.3, -.1, .4 + 1 / 3])


def test_malformed_operators_reject_with_component_and_text():
    """Nothing outside the grammar, and no singular operator, is applied."""
    _util.require_numpy()
    from lammps_post.references import _apply_symop, _parse_symop
    for text, fragment in _MALFORMED:
        message = _raises(lambda: _parse_symop(text), repr(text), fragment)
        assert 'symmetry operation' in message
        _raises(lambda: _apply_symop(text, [.2, .3, .4]), fragment)
    _raises(lambda: _parse_symop(None), 'must be a string')
    _raises(lambda: _parse_symop(['x', 'y', 'z']), 'must be a string')


def test_expand_symmetry_rejects_before_generating_any_site():
    """One bad operator fails the whole expansion; valid lists expand as before."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.references import _expand_symmetry
    asym = [('Fe', [0, 0, 0]), ('O', [.25, .25, .25])]
    good = ['x, y, z', 'x+1/2, y+1/2, z+1/2']
    atoms = _expand_symmetry(asym, good)
    assert [e for e, _ in atoms] == ['Fe', 'Fe', 'O', 'O']
    np.testing.assert_allclose([p for _, p in atoms],
                               [[0, 0, 0], [.5, .5, .5], [.25, .25, .25], [.75, .75, .75]])
    for bad in (['x, y, z', 'garbage, y, z'], ['x, x, z'], ['x, y, z', 'x,y']):
        _raises(lambda: _expand_symmetry(asym, bad), 'symmetry operation')
    # Wrapping still happens after a valid translation beyond the cell.
    wrapped = _expand_symmetry([('X', [.9, .9, .9])], ['x+1/2, y-1, z+2'])
    np.testing.assert_allclose(wrapped[0][1], [.4, .9, .9])


def test_builtin_crystals_are_unchanged():
    """The hematite expansion (the only built-in generated from operators) is preserved."""
    _util.require_numpy()
    from lammps_post.references import CRYSTAL_DB, _hematite_asym, _hematite_symops, _expand_symmetry
    atoms = CRYSTAL_DB['Fe2O3']['atoms']
    assert collections.Counter(e for e, _ in atoms) == {'Fe': 12, 'O': 18}
    rows = sorted((e, round(f[0], 4), round(f[1], 4), round(f[2], 4)) for e, f in atoms)
    # Digest of the sorted, rounded expansion recorded on main before REV-REF-3.
    assert hashlib.sha256(repr(rows).encode()).hexdigest()[:16] == 'dc6fbe479ee2a0c1'
    assert _expand_symmetry(_hematite_asym, _hematite_symops) == atoms
    assert len(_hematite_symops) == 36


def _parse(symmetry):
    """Parse the template CIF with the given symmetry block."""
    from lammps_post.references import parse_cif
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'structure.cif'
        path.write_text(_CIF.format(symmetry=symmetry))
        return parse_cif(str(path))


def test_cif_symmetry_loop_rows_must_all_be_valid_operators():
    """A malformed loop row names itself and aborts; it is never skipped."""
    _util.require_numpy()
    loop = 'loop_\n_space_group_symop_id\n_space_group_symop_operation_xyz\n'
    for rows, fragment in (("1 'x,y,z'\n2 'garbage, y, z'\n", "'garbage'"),
                           ("1 x,y,z\n2 x y z\n", 'exactly three'),
                           ("1 'x,y,z'\n2 '-x,-y'\n", 'exactly three'),
                           ("1 'x,y,z'\n2 'x,x,z'\n", 'determinant 0'),
                           ("1 'x,y,z'\n2 'x+1/2,y+1/2,z+1/2' 1/2\n", None)):
        if fragment is None:
            # A quoted operator followed by another column is read from the quotes.
            crystal = _parse(loop + rows)
            assert len(crystal['atoms']) == 2
            continue
        message = _raises(lambda: _parse(loop + rows), 'CIF symmetry loop', fragment)
        assert '_space_group_symop_operation_xyz' in message
        assert 'row' in message
    # The legacy tag is validated the same way.
    legacy = 'loop_\n_symmetry_equiv_pos_as_xyz\n'
    _raises(lambda: _parse(legacy + "'x,y,z'\n'x, 2y, z'\n"), 'CIF symmetry loop',
            '_symmetry_equiv_pos_as_xyz', 'determinant 2')


def test_cif_valid_loops_and_declared_p1_still_expand():
    """Unquoted, quoted, numbered and uppercase valid rows expand; P1 keeps identity."""
    _util.require_numpy()
    import numpy as np
    loop = 'loop_\n_space_group_symop_operation_xyz\n'
    for rows in ("x,y,z\n-x,-y,-z\n", "'x, y, z'\n'-x, -y, -z'\n",
                 "1 'x,y,z'\n2 '-x,-y,-z'\n", '"X,Y,Z"\n"-X,-Y,-Z"\n',
                 "1 x, y, z\n2 -x, -y, -z\n"):
        crystal = _parse(loop + rows)
        assert [e for e, _ in crystal['atoms']] == ['X', 'X']
        np.testing.assert_allclose([p for _, p in crystal['atoms']],
                                   [[.1, .2, .3], [.9, .8, .7]])
    crystal = _parse('_space_group_IT_number 1')
    np.testing.assert_allclose([p for _, p in crystal['atoms']], [[.1, .2, .3]])
    _raises(lambda: _parse('_space_group_IT_number 2'), 'CIF symmetry is missing')
