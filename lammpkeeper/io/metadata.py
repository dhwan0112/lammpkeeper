"""Immutable run metadata with per-field provenance (ADR-0005, GEN-2a).

This module only *stores and combines* facts about a LAMMPS run: pair style,
force-field family, atom style, units, timestep and the derived femtosecond
step. Every field records whether it is explicit (declared by a LAMMPS input),
guessed (a legacy heuristic) or unresolved (no evidence). Unknown is an
explicit ``None`` with status ``'unresolved'``; nothing here fabricates a value.

It deliberately holds no element names, force-field presets or domain
constants (AGENTS.md section 3). The family vocabulary and the pair-style
classifier live in ``lammps_post.parsers``; this model only stores their
string results. Importing it reads no files.
"""

import math
from dataclasses import dataclass

EXPLICIT = 'explicit'
GUESSED = 'guessed'
UNRESOLVED = 'unresolved'
STATUSES = (EXPLICIT, GUESSED, UNRESOLVED)

# Femtoseconds per native timestep unit for the physical LAMMPS unit styles
# supported by the analysis code: metal time is ps, real time is fs. Any other
# style (lj, si, ...) has no entry on purpose: no scale is invented for it.
_FS_PER_TIME_UNIT = {'metal': 1000.0, 'real': 1.0}


@dataclass(frozen=True)
class MetadataField:
    """One metadata value with its original text, evidence status and source.

    ``value`` is the normalized value, ``raw`` the text as declared (or None),
    ``status`` one of explicit/guessed/unresolved, ``source`` where the evidence
    came from (an input path or a heuristic name) and ``note`` a short reason,
    mainly why a field is unresolved. An unresolved field must carry
    ``value is None`` so a placeholder can never look like evidence.
    """

    value: object = None
    raw: object = None
    status: str = UNRESOLVED
    source: object = None
    note: object = None

    def __post_init__(self):
        """Reject unknown statuses and unresolved fields that carry a value."""
        if self.status not in STATUSES:
            raise ValueError(f"metadata status must be one of {STATUSES}, got {self.status!r}")
        if self.status == UNRESOLVED and self.value is not None:
            raise ValueError("an unresolved metadata field must have value None")
        if self.status != UNRESOLVED and self.value is None:
            raise ValueError(f"a {self.status} metadata field needs a value")


def _unresolved(note):
    """Build an unresolved field whose only content is the reason."""
    return MetadataField(None, None, UNRESOLVED, None, note)


def _check_timestep(timestep):
    """Return timestep as float after requiring a finite, strictly positive number."""
    if isinstance(timestep, bool) or not isinstance(timestep, (int, float)):
        raise ValueError(f"timestep must be a number, got {timestep!r}")
    value = float(timestep)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"timestep must be finite and positive, got {timestep!r}")
    return value


def derive_dt_fs(units, timestep):
    """Convert a native timestep to femtoseconds from explicit units.

    Args:
        units:    str or None - the declared LAMMPS units style.
        timestep: float or None - the declared native timestep.

    Returns:
        (dt_fs, reason): ``dt_fs`` is a float for metal/real with a valid
        timestep, otherwise None with a human-readable ``reason``.
    """
    if units is None and timestep is None:
        return None, "neither units nor timestep is declared"
    if units is None:
        return None, "timestep is declared but units is not; its time unit is unknown"
    if timestep is None:
        return None, "units is declared but timestep is not"
    if units not in _FS_PER_TIME_UNIT:
        return None, (f"units {units!r} has no supported femtosecond conversion; "
                      "no scale is invented")
    return _check_timestep(timestep) * _FS_PER_TIME_UNIT[units], None


@dataclass(frozen=True)
class RunMetadata:
    """Immutable record of the run facts a consumer may rely on.

    Each attribute is a ``MetadataField``. ``timestep`` is in the native unit
    of ``units`` and ``dt_fs`` is derived only when both are explicit.
    """

    pair_style: MetadataField
    ff_family: MetadataField
    atom_style: MetadataField
    units: MetadataField
    timestep: MetadataField
    dt_fs: MetadataField

    FIELDS = ('pair_style', 'ff_family', 'atom_style', 'units', 'timestep', 'dt_fs')

    @classmethod
    def from_explicit(cls, source, *, pair_style=None, ff_family=None, atom_style=None,
                      units=None, timestep=None, timestep_raw=None):
        """Build metadata from commands a LAMMPS input explicitly declared.

        Every argument left as None becomes an unresolved field. ``ff_family``
        is the classifier's string result for ``pair_style`` (the caller owns
        the vocabulary). ``dt_fs`` is explicit only when ``units`` and
        ``timestep`` are both explicit and the unit style is convertible;
        otherwise it is unresolved with the reason. Raises ValueError for a
        non-finite or non-positive timestep.
        """
        def field(value, raw=None):
            """Explicit field for a declared value, unresolved when not declared."""
            if value is None:
                return _unresolved('not declared in the input')
            return MetadataField(value, value if raw is None else raw, EXPLICIT, source)

        step = None if timestep is None else _check_timestep(timestep)
        dt_value, reason = derive_dt_fs(units, step)
        if dt_value is None:
            dt_field = _unresolved(reason)
        else:
            dt_field = MetadataField(dt_value, None, EXPLICIT, source,
                                     f"{step!r} x {_FS_PER_TIME_UNIT[units]:g} fs ({units} units)")
        if ff_family is not None and pair_style is None:
            raise ValueError("ff_family needs the explicit pair_style it was classified from")
        return cls(
            pair_style=field(pair_style),
            ff_family=(MetadataField(ff_family, pair_style, EXPLICIT, source,
                                     "classified from the first pair_style token")
                       if ff_family is not None else _unresolved('no explicit pair_style')),
            atom_style=field(atom_style),
            units=field(units),
            timestep=field(step, timestep_raw),
            dt_fs=dt_field,
        )

    @classmethod
    def from_guess(cls, info, source='detect_forcefield'):
        """Wrap a legacy ``detect_forcefield`` result with every field 'guessed'.

        Only values the heuristic actually produced are stored: force-field
        family, unit system and femtosecond step. Pair style, atom style and the
        native timestep stay unresolved because the heuristic never saw them.
        Nothing here is explicit, so guessed units never confirm a timestep.
        """
        def field(key, note):
            """Guessed field for a heuristic value, unresolved when it gave none."""
            value = info.get(key)
            if value is None:
                return _unresolved('the legacy heuristic does not provide it')
            return MetadataField(value, value, GUESSED, source, note)

        note = 'legacy shape heuristic, not run metadata'
        return cls(
            pair_style=_unresolved('the legacy heuristic does not provide it'),
            ff_family=field('forcefield', note),
            atom_style=_unresolved('the legacy heuristic does not provide it'),
            units=field('unit_system', note),
            timestep=_unresolved('the legacy heuristic does not provide it'),
            dt_fs=field('dt_fs', note),
        )

    def describe(self):
        """Return one line per field: name, value, status and source/reason.

        Intended for status output so a consumer can show what is explicit,
        guessed or unresolved before relying on a number.
        """
        lines = []
        for name in self.FIELDS:
            f = getattr(self, name)
            detail = f.source if f.status != UNRESOLVED else f.note
            tail = f" ({detail})" if detail else ''
            shown = '-' if f.value is None else repr(f.value)
            lines.append(f"{name}: {shown} [{f.status}]{tail}")
        return '\n'.join(lines)
