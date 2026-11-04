"""REV-REF-4: cell parameters are validated, never clipped, and CIF cells that
are not a number or not a cell raise instead of defaulting.

The reference RDF no longer uses a minimum-image convention at all (REV-REF-2
enumerates every image inside the cutoff), so the only remaining way to get a
wrong reference geometry from a CIF was an invalid cell that
``_cell_from_params`` silently clipped (negative volume residual -> flat cell)
or that ``parse_cif`` silently defaulted (angle ``0`` or ``?`` -> 90 degrees).
"""
import math
import os
import tempfile

import _util


def _raises(call, *fragments):
    """Assert that call() raises ValueError whose text contains every fragment;
    return that text."""
    try:
        call()
    except ValueError as exc:
        text = str(exc)
        for fragment in fragments:
            assert fragment in text, (fragment, text)
        return text
    raise AssertionError('expected ValueError')


def _lengths_and_angles(cell):
    """Recover (a, b, c, alpha, beta, gamma) in Å/degrees from a 3x3 row cell."""
    import numpy as np
    a, b, c = (np.linalg.norm(v) for v in cell)
    angle = lambda u, v: math.degrees(math.acos(float(np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v)))))
    return (a, b, c, angle(cell[1], cell[2]), angle(cell[0], cell[2]), angle(cell[0], cell[1]))


def test_valid_cells_round_trip_and_match_the_builtin_constructions():
    """_cell_from_params reproduces the cubic/hexagonal builders, round-trips a
    triclinic cell with the analytic volume, and builds thin but valid cells."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.references import _cell_from_params, _cubic_cell, _hexagonal_cell

    np.testing.assert_allclose(_cell_from_params(2.8665, 2.8665, 2.8665, 90, 90, 90),
                               _cubic_cell(2.8665), atol=1e-12)
    np.testing.assert_allclose(_cell_from_params(5.038, 5.038, 13.772, 90, 90, 120),
                               _hexagonal_cell(5.038, 13.772), atol=1e-12)
    # Triclinic: recovered lengths/angles and the analytic volume are the
    # oracle; the matrix must be lower triangular with positive c_z.
    params = (4.1, 5.3, 6.7, 71.0, 83.5, 112.0)
    cell = _cell_from_params(*params)
    np.testing.assert_allclose(_lengths_and_angles(cell), params, atol=1e-9)
    ca, cb, cg = (math.cos(math.radians(x)) for x in params[3:])
    volume = params[0] * params[1] * params[2] * math.sqrt(1 - ca**2 - cb**2 - cg**2 + 2 * ca * cb * cg)
    np.testing.assert_allclose(np.linalg.det(cell), volume, rtol=1e-12)
    assert cell[0, 1] == cell[0, 2] == cell[1, 2] == 0 and cell[2, 2] > 0
    # Integer and string-free numeric inputs are accepted as numbers.
    np.testing.assert_allclose(_cell_from_params(2, 2, 2, 90, 90, 90), _cubic_cell(2.0), atol=1e-12)
    # A thin but valid cell (alpha + beta > gamma) is built, not clipped.
    thin = _cell_from_params(1, 1, 1, 10, 10, 19)
    assert np.linalg.det(thin) > 0.01


def test_invalid_parameters_are_rejected_not_clipped():
    """Non-positive lengths, non-finite or non-numeric values, out-of-range
    angles and zero-volume triples raise ValueError naming the parameter."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.references import _cell_from_params

    cases = [
        ((0, 1, 1, 90, 90, 90), 'cell length a must be positive'),
        ((1, -2.5, 1, 90, 90, 90), 'cell length b must be positive'),
        ((1, 1, float('nan'), 90, 90, 90), 'cell parameter c must be finite'),
        ((1, 1, float('inf'), 90, 90, 90), 'cell parameter c must be finite'),
        ((1, 1, 'x', 90, 90, 90), "cell parameter c must be a number, got 'x'"),
        ((1, 1, None, 90, 90, 90), 'cell parameter c must be a number, got None'),
        ((1, 1, True, 90, 90, 90), 'cell parameter c must be a number'),
        ((1, 1, np.True_, 90, 90, 90), 'cell parameter c must be a number'),
        ((1, 1, '4.0', 90, 90, 90), "cell parameter c must be a number, got '4.0'"),
        ((1, 1, 1, 90, 90, b'90'), 'cell parameter gamma must be a number'),
        ((1, 1, 1, 0, 90, 90), 'cell angle alpha must lie strictly between 0 and 180'),
        ((1, 1, 1, 90, 180, 90), 'cell angle beta must lie strictly between 0 and 180'),
        ((1, 1, 1, 90, 90, -30), 'cell angle gamma must lie strictly between 0 and 180'),
        ((1, 1, 1, 90, 90, 200), 'cell angle gamma must lie strictly between 0 and 180'),
        ((1, 1, 1, 90, 90, float('nan')), 'cell parameter gamma must be finite'),
        # Angle triples with no positive-volume cell: previously clipped to a
        # flat cell (zero c_z) without any signal.
        ((1, 1, 1, 170, 170, 170), 'do not describe a cell with positive volume'),
        ((1, 1, 1, 10, 10, 30), 'do not describe a cell with positive volume'),
        ((1, 1, 1, 10, 10, 20), 'do not describe a cell with positive volume'),
        ((2, 3, 4, 150, 150, 70), 'do not describe a cell with positive volume'),
        # Exact boundary triples (angles summing to 360, or one angle equal to
        # the sum of the other two) whose residual rounds to +1e-15 or -1e-16
        # rather than 0; all must be rejected regardless of rounding sign.
        ((1, 1, 1, 120, 120, 120), 'do not describe a cell with positive volume'),
        ((1, 1, 1, 100, 100, 160), 'do not describe a cell with positive volume'),
        ((1, 1, 1, 60, 60, 120), 'do not describe a cell with positive volume'),
        ((1, 1, 1, 45, 45, 90), 'do not describe a cell with positive volume'),
        ((1, 1, 1, 30, 60, 90), 'do not describe a cell with positive volume'),
        ((1, 1, 1, 1, 1, 2), 'do not describe a cell with positive volume'),
        ((1, 1, 1, 179, 179, 2), 'do not describe a cell with positive volume'),
    ]
    for args, fragment in cases:
        _raises(lambda: _cell_from_params(*args), fragment)


_CIF = '''data_test
_cell_length_a 4.0
_cell_length_b 4.0
_cell_length_c 4.0
{angles}
_symmetry_space_group_name_H-M 'P 1'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
X1 X 0.0 0.0 0.0
'''


def _write(tmp, name, text):
    """Write text to tmp/name and return the path."""
    path = os.path.join(tmp, name)
    with open(path, 'w') as handle:
        handle.write(text)
    return path


def test_cif_cell_parameters_are_validated_not_defaulted():
    """parse_cif defaults only absent angles to 90; zero angles, invalid
    triples and non-numeric values (including '?' and '.') raise ValueError."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.references import parse_cif

    with tempfile.TemporaryDirectory() as tmp:
        # Absent angle tags still take 90 degrees.
        crystal = parse_cif(_write(tmp, 'absent.cif', _CIF.format(angles='')))
        np.testing.assert_allclose(crystal['cell'], np.eye(3) * 4.0, atol=1e-12)
        # An explicit 90 is the same as the default.
        crystal = parse_cif(_write(tmp, 'ninety.cif', _CIF.format(
            angles='_cell_angle_alpha 90\n_cell_angle_beta 90.0(0)\n_cell_angle_gamma 90')))
        np.testing.assert_allclose(crystal['cell'], np.eye(3) * 4.0, atol=1e-12)
        # Angle 0 used to pass through `or 90.0` as 90 degrees, for each angle.
        for name in ('alpha', 'beta', 'gamma'):
            _raises(lambda: parse_cif(_write(tmp, 'zero.cif', _CIF.format(angles=f'_cell_angle_{name} 0'))),
                    'CIF cell parameters are invalid', f'cell angle {name}')
        # Boundary triple that rounds to a positive residual.
        _raises(lambda: parse_cif(_write(tmp, 'rhombo.cif', _CIF.format(
            angles='_cell_angle_alpha 120\n_cell_angle_beta 120\n_cell_angle_gamma 120'))),
                'CIF cell parameters are invalid', 'positive volume')
        # The CIF unknown markers and non-numeric text are not numbers.
        for marker in ('?', '.', 'ninety'):
            _raises(lambda: parse_cif(_write(tmp, 'unknown.cif',
                                             _CIF.format(angles=f'_cell_angle_alpha {marker}'))),
                    '_cell_angle_alpha', 'is not a number')
        _raises(lambda: parse_cif(_write(tmp, 'badlen.cif',
                                         _CIF.format(angles='').replace('_cell_length_b 4.0', '_cell_length_b ?'))),
                '_cell_length_b', 'is not a number')
        # Geometrically impossible angle triple.
        _raises(lambda: parse_cif(_write(tmp, 'flat.cif', _CIF.format(
            angles='_cell_angle_alpha 170\n_cell_angle_beta 170\n_cell_angle_gamma 170'))),
                'CIF cell parameters are invalid', 'positive volume')
        # Negative length with an uncertainty suffix.
        _raises(lambda: parse_cif(_write(tmp, 'neg.cif',
                                         _CIF.format(angles='').replace('_cell_length_c 4.0', '_cell_length_c -4.0(2)'))),
                'cell length c must be positive')
        # An absent length is still reported as missing (None), as before.
        assert parse_cif(_write(tmp, 'missing.cif',
                                _CIF.format(angles='').replace('_cell_length_a 4.0\n', ''))) is None
        # A valid triclinic CIF builds the same cell as the direct constructor.
        text = _CIF.format(angles='_cell_angle_alpha 71.0(3)\n_cell_angle_beta 83.5\n_cell_angle_gamma 112')
        text = text.replace('_cell_length_b 4.0', '_cell_length_b 5.3').replace('_cell_length_c 4.0', '_cell_length_c 6.7')
        crystal = parse_cif(_write(tmp, 'tri.cif', text))
        np.testing.assert_allclose(_lengths_and_angles(crystal['cell']), (4.0, 5.3, 6.7, 71.0, 83.5, 112.0), atol=1e-9)


def test_triclinic_cif_reference_matches_the_image_oracle():
    """A valid low-symmetry CIF cell flows through parse_cif into
    compute_reference_rdf and reproduces the independent brute-force image
    enumeration of tests/test_reference_images.py in every bin."""
    _util.require_numpy()
    import sys
    import numpy as np
    from lammps_post.references import compute_reference_rdf, parse_cif
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from test_reference_images import _brute_force_counts, _counts_from_rdf

    text = '''data_tri
_cell_length_a 3.1(2)
_cell_length_b 4.4
_cell_length_c 5.2
_cell_angle_alpha 71.0
_cell_angle_beta 83.5
_cell_angle_gamma 112.0
_symmetry_space_group_name_H-M 'P 1'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Fe1 Fe 0.0 0.0 0.0
Fe2 Fe 0.5 0.5 0.5
O1 O 0.37 0.81 0.52
'''
    with tempfile.TemporaryDirectory() as tmp:
        crystal = parse_cif(_write(tmp, 'tri.cif', text))
    assert crystal is not None and len(crystal['atoms']) == 3
    # 137 bins: the bin width 7/137 does not divide any lattice length, so no
    # lattice-translation distance (3.1, 4.4, 5.2 Å) sits on a bin edge where
    # the two enumeration orders could round to different sides.
    for pair in (('Fe', 'O'), ('O', 'Fe'), ('Fe', 'Fe')):
        ref = compute_reference_rdf(crystal, pair=pair, r_max=7.0, n_bins=137)
        expected, n_a, n_b, vol = _brute_force_counts(crystal, pair, 7.0, 137)
        got = _counts_from_rdf(ref, n_a, n_b, vol, 7.0, 137)
        assert expected.sum() > 20, pair
        np.testing.assert_array_equal(got, expected, err_msg=str(pair))
