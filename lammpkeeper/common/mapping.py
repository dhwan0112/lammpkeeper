"""
Canonical per-force-field atom TYPE <-> ELEMENT <-> LABEL convention.

Single source of truth shared by the prep (structure generation) and post
(analysis) sides. Extracted in Stage 2 to remove three independent copies of
the ACE "type 1 = Fe_up, type 2 = Fe_down, type 3 = O" convention that
previously lived in:
  - lammps_pre.state.FF_PRESETS            (forward: type -> label)
  - lammps_post.parsers.detect_forcefield  (reverse: element/type -> label)
  - lammps_post.analysis.analyze_spin_evolution (hardcoded types 1/2/3)

Each force field maps an atom TYPE NUMBER to (element_symbol, label):
  - element_symbol: the LAMMPS pair_coeff element slot. ACE uses 'Mn' as the
    spin-down Fe proxy (Bienvenu et al., npj Comput. Mater. 2025, 11:81).
  - label: the human-readable species name used in analysis and plots.

The canonical tables preserve the historical slot convention; analysis aliases
below are additive views, not new LAMMPS types or a guess from label prefixes.
Input/dump metadata can override a preset only through explicit matching rules
in the caller. Legacy force-field/count inference remains separate in the post
parser and is now visibly warned; these helpers do not certify that inference.
"""

from numbers import Integral


# type_number -> (element_symbol, label)
FORCE_FIELDS = {
   'ace': {1: ('Fe', 'Fe_up'), 2: ('Mn', 'Fe_down'), 3: ('O', 'O')},
   'reaxff': {1: ('Fe', 'Fe'), 2: ('O', 'O')},
   'hdnnp': {1: ('Fe', 'Fe'), 2: ('O', 'O')},
}


def type_to_label(ff):
    """{type_number: label}  e.g. 'ace' -> {1: 'Fe_up', 2: 'Fe_down', 3: 'O'}."""
    return {t: label for t, (_el, label) in FORCE_FIELDS[ff].items()}


def element_to_label(ff):
    """{element_symbol: label}  e.g. 'ace' -> {'Fe':'Fe_up','Mn':'Fe_down','O':'O'}."""
    return {el: label for _t, (el, label) in FORCE_FIELDS[ff].items()}


def label_to_type(ff):
    """{label: type_number}  e.g. 'ace' -> {'Fe_up':1,'Fe_down':2,'O':3}."""
    return {label: t for t, (_el, label) in FORCE_FIELDS[ff].items()}


def element_to_type(ff):
    """{element_symbol: type_number}  e.g. 'ace' -> {'Fe':1,'Mn':2,'O':3}."""
    return {el: t for t, (el, _label) in FORCE_FIELDS[ff].items()}


def element_order(ff):
    """Element symbols in atom-type order: 'ace' -> ['Fe', 'Mn', 'O'].

    This is the order LAMMPS expects in `pair_coeff * * <potential> <elements>`
    and in `dump_modify <id> element <elements>`. Sourcing both from here keeps
    what prep writes and what post reads from ever drifting apart.
    """
    return [el for _t, (el, _label) in sorted(FORCE_FIELDS[ff].items())]


# Analysis aliases only: these do not change LAMMPS element slots or legacy
# one-type conversion APIs. Apply a preset only while its member labels match
# the explicitly supplied system map; user relabeling takes precedence.
_SPECIES_GROUPS = {'ace': {'Fe': frozenset({1, 2})}}
_SPECIES_DISPLAY = {'ace': {'Fe': 'Fe (all spins)',
                            'Fe_up': 'Fe↑', 'Fe_down': 'Fe↓'}}


def species_type_sets(atom_types, ff=None, groups=None):
    """Resolve explicit type labels and optional groups to immutable type sets.

    Repeated labels are an explicit union, not a last-type-wins inverse map.
    Arbitrary underscore prefixes are never guessed. ``groups`` may add named
    unions of existing type IDs but cannot silently redefine an exact label or
    an applicable preset alias: conflicting definitions raise explicitly.
    Canonical FF tables and legacy conversion helpers remain unchanged.
    """
    resolved = {}
    for type_id, label in atom_types.items():
        if (isinstance(type_id, bool) or not isinstance(type_id, Integral)
                or type_id <= 0):
            raise ValueError(f'Invalid atom type ID {type_id!r}; expected a positive integer')
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f'Invalid label for atom type {type_id}: {label!r}')
        resolved.setdefault(label, set()).add(int(type_id))

    canonical = FORCE_FIELDS.get(ff, {})
    # A named alias is valid only for the same encoded member labels. Merely
    # selecting a force-field name must not relabel an explicitly mapped system.
    for name, members in _SPECIES_GROUPS.get(ff, {}).items():
        if all(t in atom_types and atom_types[t] == canonical[t][1] for t in members):
            # A system may explicitly use the same label for a different type.
            # Do not replace it with a preset alias merely because ff matches.
            if name not in resolved:
                resolved[name] = set(members)

    # Exact labels and established aliases cannot silently acquire different
    # membership through a later group definition; callers must resolve the
    # conflict explicitly before any numerical selection is made.
    for name, selection in (groups or {}).items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f'Invalid species group name {name!r}')
        try:
            members = list(selection)
        except TypeError:
            raise ValueError(f'Group {name!r} must contain atom type IDs') from None
        if not members or any(isinstance(t, bool) or not isinstance(t, Integral)
                              or t <= 0 for t in members):
            raise ValueError(f'Group {name!r} must contain positive integer atom type IDs')
        members = set(map(int, members))
        missing = members - atom_types.keys()
        if missing:
            raise ValueError(f'Group {name!r} refers to unknown atom type IDs {sorted(missing)}')
        if name in resolved and resolved[name] != members:
            raise ValueError(f'Conflicting definition for species {name!r}')
        resolved[name] = members
    return {name: frozenset(members) for name, members in resolved.items()}


def resolve_species(name, atom_types, ff=None, groups=None):
    """Return the explicit type set for a label; unknown names never mean all."""
    available = species_type_sets(atom_types, ff=ff, groups=groups)
    if name not in available:
        choices = ', '.join(sorted(available)) or '(none; supply explicit type labels)'
        raise ValueError(f'Unknown species {name!r}. Valid species: {choices}')
    return available[name]


def species_display_name(name, atom_types, ff=None, groups=None):
    """Human-readable selection name, separate from cache/file identifiers."""
    members = resolve_species(name, atom_types, ff=ff, groups=groups)
    canonical = FORCE_FIELDS.get(ff, {})
    canonical_members = _SPECIES_GROUPS.get(ff, {}).get(name)
    if canonical_members is None:
        canonical_members = frozenset(t for t, (_element, label) in canonical.items()
                                      if label == name)
    if (members == canonical_members
            and all(t in canonical and atom_types[t] == canonical[t][1] for t in members)):
        display = _SPECIES_DISPLAY.get(ff, {}).get(name)
        if display is not None:
            return display
    if len(members) > 1:
        return f'{name} (types {", ".join(map(str, sorted(members)))})'
    return name
