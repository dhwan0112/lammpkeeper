"""GEN-3 cell metadata tests independent of domain labels and geometry kernels.

Literal corner extrema check dump-bound inversion independently of its min/max
formula. Determinant checks concern cell volume, not minimum-image correctness.
"""

from dataclasses import FrozenInstanceError
import itertools

import _util
import numpy as np

from lammpkeeper.io import Box


def _error(call, *details):
    """Require visible invalid-metadata rejection with contextual diagnostics."""
    try:
        call()
    except ValueError as exc:
        assert all(detail.lower() in str(exc).lower() for detail in details), str(exc)
    else:
        raise AssertionError('invalid cell metadata was accepted')


def test_box_model_orthogonal_metadata_and_unresolved_pbc():
    """A physical box does not silently assume periodicity when none is supplied."""
    cell = Box((-2, 3, 5), (8, 15, 25))
    assert cell.lo == (-2., 3., 5.) and cell.hi == (8., 15., 25.)
    assert cell.tilt == (0., 0., 0.) and cell.is_orthogonal and cell.pbc is None
    np.testing.assert_array_equal(cell.lengths, [10, 12, 20])
    np.testing.assert_array_equal(cell.matrix, np.diag([10, 12, 20]))
    assert cell.volume == 2400.


def test_box_model_restricted_matrix_volume_and_nonzero_origin():
    """Rows carry basis vectors; diagonal lengths are not Euclidean edge norms."""
    cell = Box((-2, 3, 5), (8, 15, 25), (-3, 4, -2), (True, False, True))
    np.testing.assert_array_equal(cell.matrix, [[10, 0, 0], [-3, 12, 0], [4, -2, 20]])
    np.testing.assert_array_equal(cell.bounds, [[-2, 8], [3, 15], [5, 25]])
    assert cell.pbc == (True, False, True) and not cell.is_orthogonal
    np.testing.assert_allclose(cell.volume, np.linalg.det(cell.matrix), rtol=1e-14)
    assert cell.volume == 2400.


def test_box_model_dump_bounds_are_corrected_not_used_as_physical_lengths():
    """Enclosing limits carry extra tilt extent and cannot normalize a cell volume."""
    cell = Box.from_dump_bounds([[-5, 12], [1, 15], [5, 25]],
                                (-3, 4, -2), (True, True, False))
    assert cell.lo == (-2., 3., 5.) and cell.hi == (8., 15., 25.)
    assert cell.volume == 2400. and cell.volume != 17 * 14 * 20


def test_box_model_dump_corrections_match_independent_cartesian_vertices():
    """All tilt signs and the xy+xz corner agree with eight literal cell corners."""
    origin = np.array([-2., 3., 5.])
    upper = np.array([8., 15., 25.])
    corners = np.array(list(itertools.product((0., 1.), repeat=3)))
    for xy, xz, yz in itertools.product((-2., 0., 2.), repeat=3):
        literal_basis = np.array([[10., 0., 0.], [xy, 12., 0.], [xz, yz, 20.]])
        xyz = origin + corners @ literal_basis
        outer = np.column_stack((xyz.min(axis=0), xyz.max(axis=0)))
        cell = Box.from_dump_bounds(outer, (xy, xz, yz), (True, True, True))
        np.testing.assert_array_equal(cell.bounds, np.column_stack((origin, upper)))
        np.testing.assert_array_equal(cell.matrix, literal_basis)


def test_box_model_constructor_does_not_apply_dump_corrections_twice():
    """The data-file constructor accepts physical lo/hi exactly as supplied."""
    cell = Box((-2, 3, 5), (8, 15, 25), (-3, 4, -2))
    np.testing.assert_array_equal(cell.lengths, [10, 12, 20])
    wrong = Box.from_dump_bounds(cell.bounds, cell.tilt)
    assert not np.array_equal(wrong.bounds, cell.bounds)


def test_box_model_defensive_immutability_and_fresh_array_properties():
    """Neither original containers nor even writable copies can mutate a cell."""
    lo, hi, tilt, flags = [0, 0, 0], [10, 12, 20], [1, 2, 3], [True, False, True]
    cell = Box(lo, hi, tilt, flags)
    lo[0], hi[0], tilt[0], flags[0] = 99, 99, 99, False
    assert cell.lo == (0., 0., 0.) and cell.hi == (10., 12., 20.)
    assert cell.tilt == (1., 2., 3.) and cell.pbc == (True, False, True)
    for name in ('matrix', 'bounds', 'lengths'):
        original = getattr(cell, name)
        assert original.dtype == np.float64 and not original.flags.writeable
        copy = original.copy()
        original.setflags(write=True)
        original.flat[0] = 999
        np.testing.assert_array_equal(getattr(cell, name), copy)
    try:
        cell.lo = (99, 0, 0)
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError('cell attributes can be replaced')


def test_box_model_with_pbc_does_not_change_cached_source_metadata():
    """Explicit resolution returns a new value and preserves source unknown flags."""
    source = Box((0, 0, 0), (10, 12, 20), (1, 2, 3))
    resolved = source.with_pbc((True, False, np.bool_(True)))
    assert source.pbc is None and resolved.pbc == (True, False, True)
    assert resolved is not source and resolved.bounds.tolist() == source.bounds.tolist()
    assert resolved.with_pbc(None) == source
    assert hash(source) == hash(Box(source.lo, source.hi, source.tilt))


def test_box_model_nonzero_tilts_are_never_silently_flattened():
    """Exact zero is orthogonal, but arbitrarily small finite shear is not."""
    assert Box((0, 0, 0), (1, 1, 1), (-0., 0., 0.)).is_orthogonal
    for axis in range(3):
        tilt = [0., 0., 0.]
        tilt[axis] = 1e-100
        assert not Box((0, 0, 0), (1, 1, 1), tilt).is_orthogonal


def test_box_model_rejects_bad_vectors_and_nonpositive_or_overflowing_geometry():
    """Wrong shape, non-real values and unusable lengths/volumes fail visibly."""
    for vector in (None, 2, '123', [0, 0], [[0, 0, 0]], [0, True, 0],
                   [0, '1', 0], [0, complex(1, 1), 0], [0, float('nan'), 0],
                   [0, float('inf'), 0]):
        _error(lambda: Box(vector, (10, 12, 20)), 'lo')
        _error(lambda: Box((0, 0, 0), vector), 'hi')
        _error(lambda: Box((0, 0, 0), (10, 12, 20), vector), 'tilt')
    for upper in ((0, 1, 1), (-1, 1, 1), (1e308, 1e308, 1e308),
                  (1e-308, 1e-308, 1e-308)):
        _error(lambda: Box((0, 0, 0), upper), 'finite', 'positive')


def test_box_model_volume_survives_representable_extreme_aspect_ratios():
    """Intermediate product overflow is not proof that the final volume is invalid."""
    for lengths, expected in (((1e200, 1e200, 1e-200), 1e200),
                               ((1e-200, 1e-200, 1e200), 1e-200),
                               ((1e-200, 1e-120, 1e200), 1e-120)):
        cell = Box((0., 0., 0.), lengths)
        np.testing.assert_allclose(cell.volume, expected, rtol=1e-14, atol=0.)


def test_box_model_rejects_nonboolean_pbc_and_malformed_dump_bounds():
    """PBC cannot be inferred by numeric coercion; incomplete outer bounds fail."""
    for flags in (True, 1, (), (True, False), (1, 0, 1), 'ppp',
                  (True, False, 'p'), (True, False, True, False)):
        _error(lambda: Box((0, 0, 0), (10, 12, 20), pbc=flags), 'pbc')
    for bounds in (None, [0, 10], [[0, 10, 1]] * 3,
                   [[0, float('nan')], [0, 12], [0, 20]],
                   [[False, True]] * 3, [[False, 10], [0, 12], [0, 20]],
                   [[0, 10], [0, 12], [0, np.bool_(True)]]):
        _error(lambda: Box.from_dump_bounds(bounds), 'bounds')
    _error(lambda: Box.from_dump_bounds([[0, 1], [0, 1], [0, 1]], (2, 0, 0)),
            'finite', 'positive')
