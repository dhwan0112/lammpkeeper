"""REV-GEOM-1: wrap_positions returns strict [0, 1) periodic fractions and is idempotent.

Float64 rounding could place a wrapped point exactly on the upper cell face:
the measured case x = -1e-17 in a unit cell wrapped to 1.0, and wrapping that
result again gave 0.0. The maintainer chose (2026-11-02) a strict half-open,
idempotent convention: the fractions the wrap produces are in [0, 1), wrapping
again returns the same points bit for bit, and in orthogonal cells converting the
result back gives [0, 1) exactly. Tilted cells allow a documented rounding
tolerance (64 eps times the basis condition number) on that conversion. Equivalent periodic positions, so no
physical image selection changes.
"""
import itertools

import _util


def _api():
    """NumPy, Box and the geometry module (skips visibly without NumPy)."""
    _util.require_numpy()
    import numpy as np
    from lammpkeeper.io import Box
    from lammpkeeper.core import geometry as geo
    return np, Box, geo


def test_measured_face_case_wraps_to_zero_and_is_idempotent():
    """The reproduced -1e-17 case lands on 0, not 1, and a second wrap changes nothing."""
    np, Box, geo = _api()
    cell = Box((0, 0, 0), (1, 1, 1), pbc=(True, False, False))
    once = geo.wrap_positions([[-1e-17, .25, .5]], cell)
    assert once.tolist() == [[0.0, .25, .5]], once.tolist()
    assert np.array_equal(geo.wrap_positions(once, cell), once)


def test_near_face_points_are_half_open_and_idempotent_in_tilted_cells():
    """Points within a few ulps of every face, in orthogonal and tilted cells, every PBC subset."""
    np, Box, geo = _api()
    rng = np.random.default_rng(7)
    cells = [((0, 0, 0), (1, 1, 1), (0, 0, 0)), ((2, -3, 4), (5, 1, 9), (0, 0, 0)),
             ((2, -3, 4), (5, 1, 9), (0.7, -0.3, 1.2)), ((0, 0, 0), (3, 4, 5), (1.1, -.8, .7))]
    eps = np.finfo(np.float64).eps
    for lo, hi, tilt in cells:
        for flags in itertools.product((False, True), repeat=3):
            if not any(flags):
                continue
            cell = Box(lo, hi, tilt=tilt, pbc=flags)
            base = rng.uniform(0, 1, (200, 3))
            faces = rng.choice([0.0, 1.0, -1.0, 2.0], size=(200, 3))
            nudge = rng.integers(-4, 5, size=(200, 3)) * eps
            frac = np.where(rng.uniform(size=(200, 3)) < .5, faces + nudge, base)
            points = geo.to_cartesian(frac, cell)
            once = geo.wrap_positions(points, cell)
            back = geo.to_fractional(once, cell)[:, list(flags)]
            if any(tilt):
                # Tilted rebuilds may round by the documented tolerance.
                tol = geo._wrap_tolerance(cell, np.asarray(flags))
                assert 0 < tol < 1e-10
                assert np.all(back >= -tol) and np.all(back < 1 + tol), (lo, tilt, flags, back.min(), back.max())
            else:
                assert np.all(back >= 0) and np.all(back < 1), (lo, tilt, flags, back.min(), back.max())
            assert np.array_equal(geo.wrap_positions(once, cell), once), (lo, tilt, flags)
            # Same periodic positions: every displacement is a lattice vector.
            image = geo.to_fractional(once, cell) - geo.to_fractional(points, cell)
            assert np.allclose(image, np.round(image), atol=1e-9)
            assert np.allclose(image[:, [not f for f in flags]], 0, atol=1e-12)


def test_already_wrapped_points_are_returned_unchanged():
    """In-range points are not rebuilt, so they keep their exact bits."""
    np, Box, geo = _api()
    cell = Box((2, -3, 4), (5, 1, 9), tilt=(0.7, -0.3, 1.2), pbc=(True, True, True))
    points = geo.to_cartesian(np.random.default_rng(3).uniform(.01, .99, (50, 3)), cell)
    assert np.array_equal(geo.wrap_positions(points, cell), points)
