"""GEN-3 independent Cartesian probes of explicit lattice-vector geometry."""

import ast
from fractions import Fraction
import itertools
from pathlib import Path
from unittest.mock import patch

import _util


def _api():
    """Load the core dependency without turning its absence into a pass."""
    _util.require_numpy()
    import numpy as np
    from lammpkeeper.io import Box
    from lammpkeeper.core import geometry
    return np, Box, geometry


def _reject(call, fragment):
    """Require a visible validation failure rather than an approximate answer."""
    try:
        call()
    except ValueError as exc:
        assert fragment.lower() in str(exc).lower(), str(exc)
    else:
        raise AssertionError('unsupported geometry was silently accepted')


def _cartesian_oracle(displacements, rows, flags, reach):
    """Enumerate a caller-chosen Cartesian image cube, independent of production.

    Probe coordinates and the deliberately generous integer range are explicit
    in each test; no transform, QR, singular-value bound or production helper is
    used here. The test verifies the optimum is not on an artificial cube edge.
    """
    import numpy as np
    images = list(itertools.product(*(range(-reach, reach + 1) if flag else (0,)
                                      for flag in flags)))
    translations = np.array([sum((image[axis] * np.asarray(rows[axis])
                                  for axis in range(3)), np.zeros(3))
                             for image in images])
    result = []
    for vector in np.asarray(displacements).reshape(-1, 3):
        candidates = vector - translations
        norms = np.sum(candidates * candidates, axis=1)
        index = int(np.argmin(norms))
        assert all(not flags[axis] or abs(images[index][axis]) < reach
                   for axis in range(3)), 'independent oracle range is too small'
        result.append(candidates[index])
    return np.asarray(result).reshape(np.asarray(displacements).shape)


def test_geometry_fractional_rounding_counterexample_is_not_the_answer():
    """A modest skew already invalidates independently rounded fractions."""
    np, Box, geo = _api()
    cell = Box((0, 0, 0), (1, 1, 1), tilt=(0.4, 0, 0), pbc=(True,) * 3)
    vector = np.array([0.686, 0.49, 0.0])
    expected = np.array([-0.314, 0.49, 0.0])
    got = geo.minimum_image(vector, cell)
    np.testing.assert_allclose(got, expected, rtol=0, atol=1e-15)
    assert np.linalg.norm(got) < np.linalg.norm(vector)
    np.testing.assert_allclose(np.linalg.norm(got), 0.5819759445200463, rtol=2e-15)


def test_geometry_all_eight_pbc_subsets_match_cartesian_image_oracle():
    """Periodic flags select lattice rows, including Cartesian-coupled rows."""
    np, Box, geo = _api()
    rows = ((1.7, 0, 0), (0.8, 1.3, 0), (-0.6, 0.5, 1.1))
    rng = np.random.default_rng(734)
    vectors = rng.uniform(-2.0, 2.0, (2, 7, 3))
    vectors[0, 0] = (0.9, 0.85, 0.0)
    for flags in itertools.product((False, True), repeat=3):
        cell = Box((3, -4, 2), (4.7, -2.7, 3.1),
                   tilt=(0.8, -0.6, 0.5), pbc=flags)
        expected = _cartesian_oracle(vectors, rows, flags, reach=7)
        np.testing.assert_allclose(geo.minimum_image(vectors, cell), expected,
                                   rtol=0, atol=2e-14)
    # With only b periodic, subtracting b changes x as well as y.
    cell = Box((0, 0, 0), (1.7, 1.3, 1.1), tilt=(0.8, -0.6, 0.5),
               pbc=(False, True, False))
    np.testing.assert_allclose(geo.minimum_image([0.9, 0.85, 0], cell),
                               [0.1, -0.45, 0], rtol=0, atol=2e-16)


def test_geometry_strong_tilt_needs_images_outside_fixed_neighbor_cube():
    """The nearest image can be five cells away despite small fractions."""
    np, Box, geo = _api()
    rows = ((1, 0, 0), (9.0, 1, 0), (0, 0, 1))
    cell = Box((0, 0, 0), (1, 1, 1), tilt=(9, 0, 0), pbc=(True,) * 3)
    vectors = np.array([[4.9, 0.49, 0.1], [-4.9, -0.49, -0.1]])
    expected = _cartesian_oracle(vectors, rows, cell.pbc, reach=12)
    np.testing.assert_allclose(geo.minimum_image(vectors, cell), expected,
                               rtol=0, atol=2e-15)
    np.testing.assert_allclose(expected[0], [-0.1, 0.49, 0.1], rtol=0, atol=1e-15)


def test_geometry_large_unreduced_tilt_has_a_small_nearest_plane_sphere():
    """Nearest-plane initialization avoids scanning the naive huge tilt cube."""
    np, Box, geo = _api()
    cell = Box((0, 0, 0), (1, 1, 1), tilt=(1000, 0, 0), pbc=(True,) * 3)
    np.testing.assert_allclose(geo.minimum_image([490.49, 0.49, 0], cell),
                               [0.49, 0.49, 0], rtol=0, atol=3e-14)


def test_geometry_transforms_nonzero_origin_unknown_pbc_roundtrip():
    """Transforms neither need flags nor confine points to the central cell."""
    np, Box, geo = _api()
    cell = Box((3, -2, 5), (5, 1, 9), tilt=(0.7, -0.3, 1.2))
    rows = np.array([[2, 0, 0], [0.7, 3, 0], [-0.3, 1.2, 4]])
    fractions = np.array([[[-2.1, 0.3, 4.7], [0, 0, 0]],
                          [[1, 1, 1], [0.25, -1.25, 2.5]]])
    cartesian = np.array([3, -2, 5]) + fractions @ rows
    for dtype in (np.float32, np.float64):
        supplied = fractions.astype(dtype)
        expected = np.array([3, -2, 5]) + supplied.astype(float) @ rows
        converted = geo.to_cartesian(supplied, cell)
        assert converted.dtype == np.float64
        np.testing.assert_allclose(converted, expected, rtol=0, atol=2e-15)
        np.testing.assert_allclose(geo.to_fractional(converted, cell), supplied,
                                   rtol=0, atol=2e-15)
    np.testing.assert_allclose(geo.to_fractional(cartesian, cell), fractions,
                               rtol=0, atol=2e-15)


def test_geometry_wraps_only_periodic_fractional_components_all_masks():
    """Off-cell A/B points wrap across skew faces without Cartesian masking."""
    np, Box, geo = _api()
    rows = np.array([[2, 0, 0], [0.7, 3, 0], [-0.3, 1.2, 4]])
    origin = np.array([3, -2, 5])
    fractions = np.array([[-2.1, 0.3, 4.7], [0.25, -1.25, 2.5]])
    points = {'A': origin + fractions[0] @ rows,
              'B': origin + fractions[1] @ rows}
    cartesian = np.array([points['A'], points['B']])
    for flags in itertools.product((False, True), repeat=3):
        cell = Box(origin, origin + [2, 3, 4], tilt=(0.7, -0.3, 1.2), pbc=flags)
        expected = fractions.copy()
        expected[:, flags] -= np.floor(expected[:, flags])
        wrapped = geo.wrap_positions(cartesian, cell)
        np.testing.assert_allclose(wrapped, origin + expected @ rows,
                                   rtol=0, atol=4e-15)
        assert not np.shares_memory(wrapped, cartesian)


def test_geometry_exact_ties_are_deterministic_and_near_ties_stay_shortest():
    """Skew equal minima use lexicographic images, not a broad norm tolerance."""
    np, Box, geo = _api()
    skew = Box((0, 0, 0), (1, 1, 1), tilt=(0.4, 0, 0),
               pbc=(True, False, False))
    vectors = np.array([[0.5, 0, 0], [1.5, 0, 0], [-0.5, 0, 0],
                        [0.5 + 1e-13, 0, 0], [0.5 - 1e-13, 0, 0]])
    expected = vectors.copy()
    expected[:, 0] = [0.5, 0.5, 0.5, -0.5 + 1e-13, 0.5 - 1e-13]
    got = geo.minimum_image(vectors, skew)
    np.testing.assert_allclose(got, expected, rtol=0, atol=1e-16)
    for _ in range(3):
        np.testing.assert_array_equal(geo.minimum_image(vectors, skew), got)


def test_geometry_large_perpendicular_residual_does_not_hide_shorter_image():
    """A constant nonperiodic norm must not turn unequal images into a tie."""
    np, Box, geo = _api()
    cell = Box((0, 0, 0), (1, 1, 1), tilt=(0.4, 0, 0),
               pbc=(True, False, False))
    vector = np.array([0.5 + 1e-13, 0, 1e8])
    got = geo.minimum_image(vector, cell)
    np.testing.assert_array_equal(got, vector - [1, 0, 0])


def _exact_rank_one_image(vector, row):
    """Independent exact nearest integer of (d dot b)/(b dot b), lower ties."""
    d = tuple(Fraction.from_float(float(value)) for value in vector)
    b = tuple(Fraction.from_float(float(value)) for value in row)
    center = sum(x * y for x, y in zip(d, b)) / sum(value * value for value in b)
    lower = center.numerator // center.denominator
    return lower if center - lower <= Fraction(1, 2) else lower + 1


def test_geometry_oblique_large_perpendicular_rank_one_exact_image_regression():
    """Promoting an already rounded residual cannot recover the correct image."""
    np, Box, geo = _api()
    cell = Box((0, 0, 0), (1, 1, 1), tilt=(0.4, 0, 0),
               pbc=(False, True, False))
    row = np.array([0.4, 1.0, 0.0])
    for offset in (0.5799999, 0.5800001, 0.58):
        original = np.array([1e8, -4e7 + offset, 0.0])
        for sign in (1, -1):
            for translation in (0, 1, -7, 31):
                vector = sign * original + translation * row
                image = _exact_rank_one_image(vector, row)
                expected = vector - image * row
                actual = geo.minimum_image(vector, cell)
                np.testing.assert_array_equal(actual, expected,
                                               err_msg=f'{offset=}, {sign=}, {translation=}, {image=}')
        if offset != 0.58:
            assert _exact_rank_one_image(original, row) == (offset > 0.58)


def test_geometry_oblique_three_component_rank_one_exact_ties_and_neighbors():
    """A dyadic skew row has exact ties despite a large perpendicular offset."""
    np, Box, geo = _api()
    cell = Box((0, 0, 0), (1, 1, 1), tilt=(0, 0.5, 0.25),
               pbc=(False, False, True))
    row = np.array([0.5, 0.25, 1.0])
    perpendicular = np.array([1e8, -2e8, 0.0])
    for sign in (1, -1):
        for translation in (-9, 0, 7):
            tie = sign * perpendicular + (translation + 0.5) * row
            for z in (tie[2], np.nextafter(tie[2], -np.inf),
                      np.nextafter(tie[2], np.inf)):
                vector = tie.copy()
                vector[2] = z
                image = _exact_rank_one_image(vector, row)
                np.testing.assert_array_equal(geo.minimum_image(vector, cell),
                                               vector - image * row)


def test_geometry_uncertain_signs_are_exact_when_longdouble_is_only_float64():
    """Emulate platforms without an extended mantissa; exact fallback is required."""
    np, _, _ = _api()
    with patch.object(np, 'longdouble', np.float64):
        test_geometry_oblique_large_perpendicular_rank_one_exact_image_regression()
        test_geometry_oblique_three_component_rank_one_exact_ties_and_neighbors()


def test_geometry_rank_two_large_perpendicular_matches_exact_cartesian_oracle():
    """Two oblique periodic rows retain the correct image near a Voronoi face."""
    np, Box, geo = _api()
    cell = Box((0, 0, 0), (1, 1, 1), tilt=(0.4, 0.2, 0.3),
               pbc=(False, True, True))
    rows = np.array([[0.4, 1, 0], [0.2, 0.3, 1]])
    exact_rows = [[Fraction.from_float(float(x)) for x in row] for row in rows]
    images = tuple(itertools.product(range(-4, 5), repeat=2))
    for sign in (-1, 1):
        for translation in ((0, 0), (-2, 1), (1, -2)):
            for offset in (0.5 - 1e-7, 0.5, 0.5 + 1e-7):
                vector = (sign * np.array([1e8, -4e7, -8e6])
                          + offset * rows[0] + np.asarray(translation) @ rows)
                exact_d = [Fraction.from_float(float(x)) for x in vector]
                objectives = [sum((exact_d[axis]
                                   - sum(image[row] * exact_rows[row][axis]
                                         for row in range(2))) ** 2
                                  for axis in range(3)) for image in images]
                image = images[min(range(len(images)), key=lambda i: (objectives[i], images[i]))]
                assert all(abs(value) < 4 for value in image)
                np.testing.assert_array_equal(geo.minimum_image(vector, cell),
                                               vector - np.asarray(image) @ rows)


def test_geometry_orthogonal_arithmetic_and_round_even_ties_unchanged():
    """Orthogonal images are bit-for-bit the preexisting per-axis expression."""
    np, Box, geo = _api()
    rng = np.random.default_rng(31)
    for dtype in (np.float32, np.float64):
        vectors = rng.uniform(-12, 12, (2, 5, 3)).astype(dtype)
        vectors[0, :4, 0] = [-3.0, -1.0, 1.0, 3.0]
        for flags in itertools.product((False, True), repeat=3):
            cell = Box((-2, 1, 4), (0, 4, 9), pbc=flags)
            expected = vectors.astype(float)
            for axis, length in enumerate((2, 3, 5)):
                if flags[axis]:
                    expected[..., axis] -= length * np.round(expected[..., axis] / length)
            np.testing.assert_array_equal(geo.minimum_image(vectors, cell), expected)


def test_geometry_vectors_batches_and_empty_shapes_return_fresh_arrays():
    """Every API preserves leading dimensions, including zero-size axes."""
    np, Box, geo = _api()
    for tilt in ((0, 0, 0), (0.4, -0.2, 0.3)):
        cell = Box((2, -1, 3), (4, 2, 7), tilt=tilt, pbc=(True,) * 3)
        for shape in ((3,), (0, 3), (2, 0, 3), (2, 3, 4, 3)):
            values = np.zeros(shape)
            original = values.copy()
            for function in (geo.to_fractional, geo.to_cartesian,
                             geo.wrap_positions, geo.minimum_image):
                output = function(values, cell)
                assert output.shape == shape
                assert output.dtype == np.float64
                assert not np.shares_memory(output, values)
                np.testing.assert_array_equal(values, original)
            output = geo.unwrap_step(values, values, values, cell)
            assert output.shape == shape
            assert not np.shares_memory(output, values)
            np.testing.assert_array_equal(output, values)


def test_geometry_constant_cell_unwrap_matches_prescribed_analytic_crossings():
    """Small true steps recover repeated crossings of tilted lattice faces."""
    np, Box, geo = _api()
    rows = np.array([[2, 0, 0], [0.8, 1.5, 0], [-0.4, 0.3, 2.5]])
    origin = np.array([3, -2, 5])
    start = np.array([[0.9, 0.85, 0.2], [0.1, -0.2, 0.95]])
    steps = np.array([[0.17, 0.13, 0.04], [-0.11, -0.07, 0.12]])
    for flags in ((True, True, True), (False, True, True), (True, False, True)):
        cell = Box(origin, origin + [2, 1.5, 2.5], tilt=(0.8, -0.4, 0.3), pbc=flags)
        previous = None
        unwrapped = None
        for time in range(19):
            fractional = start + time * steps
            expected = origin + fractional @ rows
            wrapped_fractional = fractional.copy()
            wrapped_fractional[:, flags] -= np.floor(wrapped_fractional[:, flags])
            current = origin + wrapped_fractional @ rows
            if previous is None:
                unwrapped = expected.copy()
            else:
                unwrapped = geo.unwrap_step(previous, current, unwrapped, cell)
            np.testing.assert_allclose(unwrapped, expected, rtol=0, atol=2e-14)
            previous = current


def test_geometry_rejects_invalid_finite_shapes_and_unresolved_pbc():
    """Unknown flags, bare bounds, nonfinite coordinates and shape guesses fail."""
    np, Box, geo = _api()
    cell = Box((0, 0, 0), (1, 1, 1), tilt=(0.4, 0, 0), pbc=(True,) * 3)
    for function in (geo.to_fractional, geo.to_cartesian,
                     geo.wrap_positions, geo.minimum_image):
        for invalid in (0, [], [1, 2], [[1, 2], [3, 4]], np.zeros((3, 1))):
            _reject(lambda: function(invalid, cell), '3')
        for invalid in ([np.nan, 0, 0], [0, np.inf, 0], [0, 0, -np.inf],
                        [1j, 0, 0]):
            _reject(lambda: function(invalid, cell), 'finite')
        _reject(lambda: function([0, 0, 0], np.array([[0, 1]] * 3)), 'Box')
    unknown = Box((0, 0, 0), (1, 1, 1), tilt=(0.4, 0, 0))
    for values in ([0, 0, 0], np.empty((0, 3))):
        _reject(lambda: geo.minimum_image(values, unknown), 'PBC')
        _reject(lambda: geo.wrap_positions(values, unknown), 'PBC')
        _reject(lambda: geo.unwrap_step(values, values, values, unknown), 'PBC')
    _reject(lambda: geo.unwrap_step([0, 0, 0], [[0, 0, 0]], [0, 0, 0], cell),
            'identical')
    _reject(lambda: geo.unwrap_step([0, 0, 0], [np.inf, 0, 0], [0, 0, 0], cell),
            'finite')


def test_geometry_conditioning_search_work_and_coefficient_guards_are_visible():
    """Actual unsupported cells/displacements exercise every resource guard."""
    np, Box, geo = _api()
    ill_conditioned = Box((0, 0, 0), (1e-12, 1, 1), tilt=(0.4, 0, 0),
                          pbc=(True,) * 3)
    for function in (geo.to_fractional, geo.to_cartesian, geo.minimum_image,
                     geo.wrap_positions):
        _reject(lambda: function([0.1, 0.2, 0.3], ill_conditioned), 'conditioning')
    costly = Box((0, 0, 0), (1e6, 1, 1), tilt=(0.1, 0, 0),
                 pbc=(True, True, False))
    _reject(lambda: geo.minimum_image([5e5, 0, 0], costly), 'search work limit')
    for tilt in ((0, 0, 0), (0.4, 0, 0)):
        cell = Box((0, 0, 0), (1, 1, 1), tilt=tilt, pbc=(True,) * 3)
        _reject(lambda: geo.minimum_image([1e20, 0, 0], cell), 'coefficients')
        _reject(lambda: geo.wrap_positions([1e20, 0, 0], cell), 'coefficients')
    for scale in (1e-200, 1e200):
        # Reciprocal nonperiodic lengths keep volume finite and positive, while
        # the selected one-row periodic basis has an unsupported absolute scale.
        tiny_or_huge = Box((0, 0, 0), (scale, 1 / scale, 1),
                           tilt=(0.4 * scale, 0, 0), pbc=(True, False, False))
        _reject(lambda: geo.minimum_image([0.686 * scale, 0.49 * scale, 0],
                                          tiny_or_huge), 'scale')
    # No periodic rows means identity, even for geometrically ill-conditioned metadata.
    nonperiodic = ill_conditioned.with_pbc((False,) * 3)
    np.testing.assert_array_equal(geo.minimum_image([1e20, 2, 3], nonperiodic),
                                  [1e20, 2, 3])


def test_geometry_python39_syntax_public_docstrings_and_numpy_only_imports():
    """The new module remains Python 3.9-compatible and backend-independent."""
    source = Path(_util.REPO_ROOT, 'lammpkeeper/core/geometry.py').read_text()
    tree = ast.parse(source, feature_version=(3, 9))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for name in ('to_fractional', 'to_cartesian', 'wrap_positions',
                 'minimum_image', 'unwrap_step'):
        assert ast.get_docstring(functions[name]), name
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name == 'numpy' for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module in ('lammpkeeper.io', 'fractions'), node.module
