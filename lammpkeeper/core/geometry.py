"""NumPy geometry for explicit row-basis :class:`lammpkeeper.io.Box` cells.

Skew minimum images solve the closest-vector problem on *periodic basis rows*,
not Cartesian axes. Reduced QR gives ``B.T = Q @ R``. The perpendicular part
of a displacement is constant, so every improving image is in the finite sphere
``||Q.T @ d - R @ n|| <= incumbent_parallel_norm``. Back substitution enumerates
every integer in that sphere, with outward floating-point padding. Fractional
rounding and nearest-plane rounding only supply initial incumbents.

Safety limits are deliberate errors, never approximate fallbacks: condition
numbers above 1e10, singular values outside [1e-150, 1e150], image coefficients
above 2**45, and searches visiting more than 50,000 integer nodes *per displacement*
raise ValueError. The scale limits keep squared sphere radii representable. An
extreme cell can be valid metadata but unsupported for numerical geometry. Sphere
bounds include 128 float64 machine epsilons times the arithmetic scale and basis
condition number. This outward budget covers projection/QR sensitivity, including
large nonperiodic components. It only admits extra candidates, and never relaxes
the exact final comparison. A radius is changed only for an exactly verified
incumbent, never because a rejected candidate has a smaller rounded projection.

Image objectives are compared directly from the original displacement, basis,
and integer coefficients, before any residual subtraction. An extended-precision
sign filter has an absolute forward-error bound; uncertain signs use exact
stdlib Fraction arithmetic on the represented float64 inputs. Exact equal
objectives choose the lexicographically smallest periodic image coefficient
tuple (basis-row order).
Orthogonal cells retain NumPy round-to-even ties and the legacy axis arithmetic.
"""

from fractions import Fraction

import numpy as np

from lammpkeeper.io import Box


_MAX_CONDITION = 1.0e10
_MIN_SCALE = 1.0e-150
_MAX_SCALE = 1.0e150
_MAX_IMAGE = 2 ** 45
_MAX_SEARCH_NODES = 50_000
_ROUNDING_PAD = 128.0 * np.finfo(np.float64).eps
_MAX_RADIUS = np.sqrt(np.finfo(np.float64).max) / 4.0


def _array(values, name):
    """Copy finite real coordinates with a final dimension of three."""
    try:
        raw = np.asarray(values)
        if np.iscomplexobj(raw):
            raise ValueError('complex coordinates are not supported')
        result = np.array(raw, dtype=np.float64, copy=True)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{name} must be finite real coordinates ending in 3') from exc
    if result.ndim < 1 or result.shape[-1] != 3:
        raise ValueError(f'{name} must have a final dimension of 3')
    if not np.all(np.isfinite(result)):
        raise ValueError(f'{name} must contain only finite coordinates')
    return result


def _cell(cell, periodic=False):
    """Require typed metadata, and resolved lattice flags when needed."""
    if not isinstance(cell, Box):
        raise ValueError('cell must be an explicit lammpkeeper.io.Box')
    if periodic and (cell.pbc is None or len(cell.pbc) != 3
                     or not all(isinstance(flag, (bool, np.bool_)) for flag in cell.pbc)):
        raise ValueError('periodic geometry requires three resolved boolean PBC flags')


def _condition(matrix):
    """Reject numerically unsupported bases before any inverse/search."""
    try:
        singular = np.linalg.svd(matrix, compute_uv=False)
    except np.linalg.LinAlgError as exc:
        raise ValueError('cell conditioning could not be determined') from exc
    if (not np.all(np.isfinite(singular)) or singular[-1] <= 0
            or singular[-1] < singular[0] / _MAX_CONDITION):
        raise ValueError('cell conditioning exceeds the geometry limit of 1e10')
    if singular[-1] < _MIN_SCALE or singular[0] > _MAX_SCALE:
        raise ValueError('cell scale outside the safe geometry range [1e-150, 1e150]')
    return float(singular[0] / singular[-1])


def _finite_result(result):
    """Do not publish overflowed geometry as coordinates."""
    if not np.all(np.isfinite(result)):
        raise ValueError('geometry arithmetic produced nonfinite coordinates')
    return result


def to_fractional(positions, cell):
    """Return ``s`` for ``positions = cell.lo + s @ cell.matrix``; PBC optional."""
    _cell(cell)
    points = _array(positions, 'positions')
    matrix = cell.matrix
    _condition(matrix)
    with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
        if cell.is_orthogonal:
            result = (points - np.asarray(cell.lo)) / cell.lengths
        else:
            shifted = points - np.asarray(cell.lo)
            result = np.linalg.solve(matrix.T, shifted.reshape(-1, 3).T).T
            result = result.reshape(points.shape)
    return _finite_result(result)


def to_cartesian(fractional, cell):
    """Return ``cell.lo + fractional @ cell.matrix`` without wrapping."""
    _cell(cell)
    points = _array(fractional, 'fractional')
    matrix = cell.matrix
    _condition(matrix)
    with np.errstate(over='ignore', invalid='ignore'):
        result = np.asarray(cell.lo) + points @ matrix
    return _finite_result(result)


def wrap_positions(positions, cell):
    """Wrap periodic fractional components into [0, 1); leave other components."""
    _cell(cell, periodic=True)
    points = _array(positions, 'positions')
    if not any(cell.pbc):
        return points
    fractional = to_fractional(points, cell)
    mask = np.asarray(cell.pbc, dtype=bool)
    if np.any(np.abs(fractional[..., mask]) > _MAX_IMAGE):
        raise ValueError('periodic image coefficients exceed the 2**45 geometry limit')
    fractional[..., mask] -= np.floor(fractional[..., mask])
    return to_cartesian(fractional, cell)


def _integers_nearest_first(low, high, center):
    """Yield a finite interval by distance from center, with lower integer ties."""
    left = min(high, int(np.floor(center)))
    right = max(low, left + 1)
    while left >= low or right <= high:
        if left >= low and (right > high or center - left <= right - center):
            yield left
            left -= 1
        else:
            yield right
            right += 1


def _image_comparator(displacement, basis):
    """Make a filtered/exact comparison of image objectives from original inputs.

    For candidate n and incumbent m the squared-norm difference is exactly
    ``((m-n) @ B) dot (2*d - (n+m) @ B)``. Computing rounded residuals first
    would destroy this identity near a large perpendicular displacement.

    The filter uses 128*eps*sum(T*(2*abs(d)+S)) plus 128*tiny, where
    T=abs(m-n)@abs(B), S=abs(n+m)@abs(B). For at most three basis rows this
    bounds all product/sum/subtraction errors, including evaluation of the
    positive error scale itself; 128*tiny covers gradual-underflow errors.
    Integer sums/differences (<=2**46) and float64 inputs convert exactly to
    longdouble, even when it is only float64. Overflow or an uncertain sign
    invokes exact arithmetic, never an approximate tie. Fractions are lazy
    and reused for all uncertain comparisons of this displacement.
    """
    extended_d = displacement.astype(np.longdouble)
    extended_b = basis.astype(np.longdouble)
    absolute_b = np.abs(extended_b)
    precision = np.finfo(np.longdouble)
    exact_d = exact_b = None

    def compare(candidate, incumbent):
        """Return -1, 0, or 1 for the exact objective difference."""
        nonlocal exact_d, exact_b
        if candidate == incumbent:
            return 0
        delta = tuple(m - n for n, m in zip(candidate, incumbent))
        total = tuple(n + m for n, m in zip(candidate, incumbent))
        extended_delta = np.asarray(delta, dtype=np.longdouble)
        extended_total = np.asarray(total, dtype=np.longdouble)
        with np.errstate(over='ignore', under='ignore', invalid='ignore'):
            difference = np.sum((extended_delta @ extended_b)
                                * (2 * extended_d - extended_total @ extended_b))
            scale = np.sum((np.abs(extended_delta) @ absolute_b)
                           * (2 * np.abs(extended_d) + np.abs(extended_total) @ absolute_b))
            error = 128 * precision.eps * scale + 128 * precision.tiny
        if np.isfinite(difference) and np.isfinite(error):
            if difference > error:
                return 1
            if difference < -error:
                return -1
        if exact_d is None:
            exact_d = tuple(Fraction.from_float(float(value)) for value in displacement)
            exact_b = tuple(tuple(Fraction.from_float(float(value)) for value in row)
                            for row in basis)
        difference = sum(
            sum(delta[row] * exact_b[row][axis] for row in range(len(basis)))
            * (2 * exact_d[axis]
               - sum(total[row] * exact_b[row][axis] for row in range(len(basis))))
            for axis in range(3))
        return (difference > 0) - (difference < 0)

    return compare


def _nearest_image(displacement, basis, q, r, condition):
    """Search the complete QR sphere for one displacement, or fail visibly."""
    k = len(basis)
    coefficients = np.linalg.solve(r, q.T @ displacement)
    if not np.all(np.isfinite(coefficients)) or np.any(np.abs(coefficients) > _MAX_IMAGE):
        raise ValueError('periodic image coefficients exceed the 2**45 geometry limit')
    base = np.round(coefficients)
    shifted = displacement - base @ basis
    projected = q.T @ shifted
    if not np.all(np.isfinite(shifted)) or not np.all(np.isfinite(projected)):
        raise ValueError('minimum-image arithmetic produced nonfinite coordinates')

    # Nearest-plane initialization avoids a huge sphere from unreduced tilts.
    babai = np.zeros(k, dtype=np.float64)
    for level in range(k - 1, -1, -1):
        babai[level] = np.round((projected[level] - r[level, level + 1:] @
                                 babai[level + 1:]) / r[level, level])
    if not np.all(np.isfinite(babai)):
        raise ValueError('minimum-image nearest-plane arithmetic is nonfinite')
    compare = _image_comparator(displacement, basis)
    best_image = None
    best_parallel = np.inf
    for seed in (np.zeros(k), babai):
        image = tuple(int(value) for value in base + seed)
        if any(abs(value) > _MAX_IMAGE for value in image):
            raise ValueError('periodic image coefficients exceed the 2**45 geometry limit')
        parallel = projected - r @ seed
        difference = -1 if best_image is None else compare(image, best_image)
        if difference < 0 or (difference == 0 and image < best_image):
            best_image = image
            best_parallel = float(parallel @ parallel)
    scale = max(float(np.linalg.norm(displacement)),
                float(np.linalg.norm(base @ basis)),
                float(np.linalg.norm(basis)) * (1.0 + float(np.linalg.norm(base))
                                                + float(np.linalg.norm(babai))),
                float(np.sqrt(best_parallel)))
    # QR is backward stable, but a periodic subspace may be sensitive by cond(B).
    # The unprojected displacement scale is essential when a large perpendicular
    # component nearly cancels in Q.T @ d. Inside the incumbent sphere,
    # ||m|| <= ||R^-1|| * (||projected|| + radius); hence the condition factor
    # also bounds R@m rounding for candidate coefficients, not only the seeds.
    # The budget is outward-only and is never a final comparison tolerance.
    padding = _ROUNDING_PAD * condition * scale
    if not np.isfinite(best_parallel) or not np.isfinite(padding):
        raise ValueError('minimum-image norm arithmetic is nonfinite')
    if np.sqrt(best_parallel) + padding > _MAX_RADIUS:
        raise ValueError('minimum-image sphere arithmetic exceeds the safe scale')

    trial = np.zeros(k, dtype=np.float64)
    nodes = 0

    def visit(level, partial):
        """Enumerate lower triangular sphere slices from the last QR row up."""
        nonlocal nodes, best_image, best_parallel
        radius = np.sqrt(best_parallel) + padding
        available = radius * radius - partial
        if available < 0:
            return
        offset = float(r[level, level + 1:] @ trial[level + 1:])
        center = (projected[level] - offset) / r[level, level]
        extent = np.sqrt(available) / abs(r[level, level])
        endpoint_pad = _ROUNDING_PAD * max(1.0, abs(center), extent)
        low = int(np.ceil(center - extent - endpoint_pad))
        high = int(np.floor(center + extent + endpoint_pad))
        if low + base[level] < -_MAX_IMAGE or high + base[level] > _MAX_IMAGE:
            raise ValueError('periodic image coefficients exceed the 2**45 geometry limit')
        for integer in _integers_nearest_first(low, high, center):
            nodes += 1
            if nodes > _MAX_SEARCH_NODES:
                raise ValueError('minimum-image search work limit exceeded (50000 nodes)')
            trial[level] = integer
            error = projected[level] - offset - r[level, level] * integer
            next_partial = partial + error * error
            if next_partial > (np.sqrt(best_parallel) + padding) ** 2:
                continue
            if level:
                visit(level - 1, next_partial)
            else:
                image = tuple(int(value) for value in base + trial)
                difference = compare(image, best_image)
                if difference < 0 or (difference == 0 and image < best_image):
                    best_image = image
                    best_parallel = next_partial

    visit(k - 1, 0.0)
    return displacement - np.asarray(best_image, dtype=np.float64) @ basis


def minimum_image(displacements, cell):
    """Return exact shortest periodic images, preserving leading array dimensions.

    Orthogonal images use ``d[..., i] -= L[i] * np.round(d[..., i] / L[i])``.
    Skew images use the complete finite sphere described in this module's docs;
    resource or conditioning limits raise instead of returning an approximation.
    Input arrays are never modified. Unknown PBC is an error even for empty input.
    """
    _cell(cell, periodic=True)
    result = _array(displacements, 'displacements')
    mask = np.asarray(cell.pbc, dtype=bool)
    if not np.any(mask):
        return result
    if cell.is_orthogonal:
        lengths = cell.lengths
        _condition(np.diag(lengths[mask]))
        with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
            for axis in np.flatnonzero(mask):
                ratios = result[..., axis] / lengths[axis]
                if not np.all(np.isfinite(ratios)) or np.any(np.abs(ratios) > _MAX_IMAGE):
                    raise ValueError('periodic image coefficients exceed the 2**45 geometry limit')
                result[..., axis] -= lengths[axis] * np.round(ratios)
        return _finite_result(result)
    basis = cell.matrix[mask]
    condition = _condition(basis)
    q, r = np.linalg.qr(basis.T, mode='reduced')
    flat = result.reshape(-1, 3)
    for index in range(len(flat)):
        flat[index] = _nearest_image(flat[index], basis, q, r, condition)
    return _finite_result(result)


def unwrap_step(previous_wrapped, current_wrapped, previous_unwrapped, cell):
    """Advance a constant-cell image walk using the exact minimum-image step.

    All three arrays must have identical shapes. Correct reconstruction requires
    that each physical step lie strictly inside the periodic Voronoi cell; wrapped
    samples alone cannot diagnose aliasing. Atom-ID alignment is the caller's job.
    """
    _cell(cell, periodic=True)
    previous = _array(previous_wrapped, 'previous_wrapped')
    current = _array(current_wrapped, 'current_wrapped')
    unwrapped = _array(previous_unwrapped, 'previous_unwrapped')
    if previous.shape != current.shape or previous.shape != unwrapped.shape:
        raise ValueError('unwrap_step requires identical coordinate array shapes')
    with np.errstate(over='ignore', invalid='ignore'):
        delta = current - previous
        result = unwrapped + minimum_image(delta, cell)
    return _finite_result(result)
