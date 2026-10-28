"""Immutable orthogonal/restricted-triclinic cell metadata (ADR-0003).

The bounds are physical restricted-cell parameters, not an enclosing Cartesian
box. Basis vectors are rows: ``r = lo + fractional @ matrix``. Periodic flags
refer to those lattice vectors; None means unresolved, never all-periodic.
Geometry algorithms and file parsing live outside this model.
"""

from dataclasses import dataclass
import math
from numbers import Real
from typing import Optional, Tuple

import numpy as np


def _triple(values, name):
    """Snapshot exactly three finite real numbers, excluding boolean coercions."""
    if isinstance(values, (str, bytes, dict)):
        raise ValueError(f'Box {name} must contain three finite real numbers')
    try:
        items = tuple(values)
        if len(items) != 3 or any(isinstance(v, (bool, np.bool_)) or not isinstance(v, Real)
                                 for v in items):
            raise ValueError
        result = tuple(float(v) for v in items)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f'Box {name} must contain three finite real numbers') from None
    if not np.all(np.isfinite(result)):
        raise ValueError(f'Box {name} must contain three finite real numbers')
    return result


def _periodic(flags):
    """Retain unresolved PBC or normalize exactly three explicit booleans."""
    if flags is None:
        return None
    try:
        items = tuple(flags)
    except TypeError:
        raise ValueError('Box pbc must be three booleans or None') from None
    if len(items) != 3 or not all(isinstance(v, (bool, np.bool_)) for v in items):
        raise ValueError('Box pbc must be three booleans or None')
    return tuple(bool(v) for v in items)


def _readonly(values):
    """Return a fresh float64 array whose initial view is read-only."""
    array = np.array(values, dtype=np.float64, copy=True)
    array.setflags(write=False)
    return array


def _volume(lengths):
    """Preserve ordinary product arithmetic, with a safe extreme-range fallback."""
    with np.errstate(over='ignore', under='ignore', invalid='ignore'):
        volume = float(np.prod(lengths))
        intermediates = np.cumprod(lengths)
    if (np.isfinite(volume) and volume > 0 and np.all(np.isfinite(intermediates))
            and np.all(intermediates >= np.finfo(np.float64).tiny)):
        return volume
    # Three normalized mantissas cannot overflow/underflow; accumulate powers
    # separately so a representable final product survives extreme aspect ratios.
    mantissa, exponent = 1.0, 0
    for length in lengths:
        fraction, power = math.frexp(float(length))
        mantissa *= fraction
        exponent += power
    try:
        return math.ldexp(mantissa, exponent)
    except OverflowError:
        return float('inf')


@dataclass(frozen=True)
class Box:
    """Own finite physical bounds, restricted tilts and optional per-vector PBC.

    Positive diagonal lengths make the row basis right-handed. This class does
    not rotate arbitrary general cells, infer units/PBC, wrap positions or apply
    an affine-motion convention. Inputs are copied to immutable tuples; property
    arrays are fresh snapshots so even resetting their write flag cannot mutate
    the cell. ``tilt`` has the exact order ``(xy, xz, yz)``.
    """

    lo: Tuple[float, float, float]
    hi: Tuple[float, float, float]
    tilt: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    pbc: Optional[Tuple[bool, bool, bool]] = None

    def __post_init__(self):
        """Validate physical geometry before publishing a usable metadata object."""
        lo, hi, tilt = (_triple(values, name) for values, name in
                        ((self.lo, 'lo'), (self.hi, 'hi'), (self.tilt, 'tilt')))
        with np.errstate(over='ignore', under='ignore', invalid='ignore'):
            lengths = np.asarray(hi) - np.asarray(lo)
        if not np.all(np.isfinite(lengths)) or np.any(lengths <= 0):
            raise ValueError('Box lengths and volume must be finite and positive')
        volume = _volume(lengths)
        if not np.isfinite(volume) or volume <= 0:
            raise ValueError('Box lengths and volume must be finite and positive')
        object.__setattr__(self, 'lo', lo)
        object.__setattr__(self, 'hi', hi)
        object.__setattr__(self, 'tilt', tilt)
        object.__setattr__(self, 'pbc', _periodic(self.pbc))

    @property
    def lengths(self):
        """Return the three positive diagonal lengths, not tilted-edge norms."""
        return _readonly(np.asarray(self.hi) - np.asarray(self.lo))

    @property
    def bounds(self):
        """Return physical lo/hi as a fresh (3,2) compatibility snapshot."""
        return _readonly(np.column_stack((self.lo, self.hi)))

    @property
    def matrix(self):
        """Return lattice vectors as rows for ``cartesian = lo + s @ H``."""
        lx, ly, lz = self.lengths
        xy, xz, yz = self.tilt
        return _readonly(((lx, 0.0, 0.0), (xy, ly, 0.0), (xz, yz, lz)))

    @property
    def volume(self):
        """Return the determinant of this positive triangular restricted basis."""
        return _volume(self.lengths)

    @property
    def is_orthogonal(self):
        """Report exact zero tilt; never discard a small but nonzero shear."""
        return all(value == 0.0 for value in self.tilt)

    def with_pbc(self, flags):
        """Return an independently validated cell with resolved/unresolved flags."""
        return type(self)(self.lo, self.hi, self.tilt, flags)

    @classmethod
    def from_dump_bounds(cls, bounds, tilt=(0.0, 0.0, 0.0), pbc=None):
        """Invert LAMMPS enclosing bounds; never use this for data-file bounds.

        Rows carry outer x/y/z limits; tilt is supplied separately in xy/xz/yz
        order. Correcting only by individual tilts misses the xy+xz corner.
        Corrected lengths are validated by the ordinary constructor.
        """
        try:
            rows = tuple(tuple(row) for row in bounds)
            if (len(rows) != 3 or any(len(row) != 2 for row in rows)
                    or any(isinstance(v, (bool, np.bool_)) or not isinstance(v, Real)
                           for row in rows for v in row)):
                raise ValueError
            raw = np.asarray(rows, dtype=np.float64)
        except (TypeError, ValueError, OverflowError):
            raise ValueError('Dump bounds must be a finite numeric (3,2) array') from None
        if not np.all(np.isfinite(raw)):
            raise ValueError('Dump bounds must be a finite numeric (3,2) array')
        xy, xz, yz = tilt = _triple(tilt, 'tilt')
        lo, hi = raw[:, 0].copy(), raw[:, 1].copy()
        with np.errstate(over='ignore', invalid='ignore'):
            lo[0] -= min(0.0, xy, xz, xy + xz)
            hi[0] -= max(0.0, xy, xz, xy + xz)
            lo[1] -= min(0.0, yz)
            hi[1] -= max(0.0, yz)
        return cls(lo, hi, tilt, pbc)
