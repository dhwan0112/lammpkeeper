"""Immutable explicit species selections with no force-field or element guesses.

A species label is a selection, not necessarily a chemical element: several
labels may overlap, and repeated type labels form a union. File parsing, source
precedence, domain aliases and display translations belong to adapters outside
this module. Numeric type IDs are never compacted or inferred from a label.
Selections contain type IDs, not atom IDs: tracking a fixed cohort through type
changes remains the responsibility of a time-series consumer.
"""

from dataclasses import dataclass
from numbers import Integral
from types import MappingProxyType
from typing import Mapping


def _valid_name(name):
    """Require a nonblank string; preserve case and any surrounding whitespace."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f'Invalid species name {name!r}; expected a nonblank string')
    return name


def _type_id(value):
    """Normalize integral scalars while rejecting booleans and lossy conversions."""
    if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
        raise ValueError(f'Invalid atom type ID {value!r}; expected a positive integer')
    return int(value)


def _members(name, values):
    """Consume a nonempty iterable once and deduplicate positive type IDs."""
    try:
        items = list(values)
    except TypeError:
        raise ValueError(f'Group {name!r} must contain atom type IDs') from None
    if not items:
        raise ValueError(f'Group {name!r} must contain positive integer atom type IDs')
    return frozenset(_type_id(value) for value in items)


@dataclass(frozen=True, init=False)
class SpeciesMap:
    """Own immutable label-to-type selections, independent of a force-field name.

    Direct construction declares the known types through the union of all
    supplied selections. Use ``from_atom_types`` when named groups must be
    checked against a separately supplied universe of existing type IDs.
    Snapshots do not observe later mutations of caller-owned dictionaries/lists.
    """

    _label_types: Mapping[str, frozenset]

    def __init__(self, label_types):
        """Copy explicit label-to-type iterables; permit an empty unloaded map."""
        if not isinstance(label_types, Mapping):
            raise ValueError('Species selections must be a label-to-types mapping')
        resolved = {_valid_name(name): _members(name, values)
                    for name, values in label_types.items()}
        object.__setattr__(self, '_label_types', MappingProxyType(resolved))

    @classmethod
    def from_atom_types(cls, atom_types, *, groups=None):
        """Union repeated type labels, then validate groups against existing IDs.

        Exact labels cannot be redefined with different membership. Overlapping
        distinct groups are valid; aliases inferred from spelling are not added.
        Group references must already exist in atom_types; pending metadata is
        an adapter/session concern, not a partially resolved SpeciesMap state.
        """
        if not isinstance(atom_types, Mapping):
            raise ValueError('Atom types must be a type-ID-to-label mapping')
        if groups is not None and not isinstance(groups, Mapping):
            raise ValueError('Species groups must be a name-to-types mapping')
        normalized = {}
        resolved = {}
        for raw_id, label in atom_types.items():
            type_id = _type_id(raw_id)
            _valid_name(label)
            normalized[type_id] = label
            resolved.setdefault(label, set()).add(type_id)
        for name, selection in (groups or {}).items():
            _valid_name(name)
            members = _members(name, selection)
            missing = members - normalized.keys()
            if missing:
                raise ValueError(f'Group {name!r} refers to unknown atom type IDs {sorted(missing)}')
            if name in resolved and resolved[name] != members:
                raise ValueError(f'Conflicting definition for species {name!r}')
            # Equal membership is an idempotent declaration, not a label override.
            resolved[name] = members
        return cls(resolved)

    def resolve(self, name):
        """Return a selection; unknown names never mean all atoms or a default."""
        if not isinstance(name, str) or name not in self._label_types:
            choices = ', '.join(sorted(self._label_types)) or '(none; supply explicit type labels)'
            raise ValueError(f'Unknown species {name!r}. Valid species: {choices}')
        return self._label_types[name]

    def type_sets(self):
        """Return a fresh dictionary of immutable memberships for compatibility."""
        return dict(self._label_types)
