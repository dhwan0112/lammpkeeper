"""
Preset/compatibility adapter for atom TYPE <-> ELEMENT <-> LABEL conventions.

SpeciesMap owns generic selection storage/resolution; this module remains the
single source of preset conventions shared by prep and post. Stage 2 extracted
the ACE "type 1 = Fe_up, type 2 = Fe_down, type 3 = O" convention from three copies that
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
in the caller. Stage B preserved historical values; Step C later replaced the
three-type ACE population guess with this deterministic slot convention.
Legacy force-field inference and a count-based fallback remain in the post
parser, visibly warned and still subject to GEN-2; these helpers do not certify
those guesses.
"""

from lammpkeeper.core import SpeciesMap


# type_number -> (element_symbol, label)
FORCE_FIELDS = {
   'ace': {1: ('Fe', 'Fe_up'), 2: ('Mn', 'Fe_down'), 3: ('O', 'O')},
   'reaxff': {1: ('Fe', 'Fe'), 2: ('O', 'O')},
   'hdnnp': {1: ('Fe', 'Fe'), 2: ('O', 'O')},
}


def type_to_label(ff):
    """Copy the preset type-to-label table; an unknown preset raises KeyError."""
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


def make_species_map(atom_types, ff=None, groups=None):
    """Adapt explicit labels/groups and compatible preset aliases to a system map.

    Generic validation, immutable storage and name resolution belong to
    ``SpeciesMap``. This adapter alone knows domain aliases: choosing a force
    field never overwrites user-supplied labels or injects prefix-based guesses.
    Existing scalar tables/conversion helpers remain unchanged.
    Unknown/omitted presets are harmless here: only the explicit labels/groups
    apply, unlike the strict legacy scalar table lookups above.
    """
    exact = SpeciesMap.from_atom_types(atom_types).type_sets()
    resolved = SpeciesMap.from_atom_types(atom_types, groups=groups).type_sets()
    canonical = FORCE_FIELDS.get(ff, {})
    for name, members in _SPECIES_GROUPS.get(ff, {}).items():
        # An exact user label suppresses this alias. Otherwise every alias member
        # must retain its canonical slot label; an explicit unequal group errors.
        if (name not in exact
                and all(t in atom_types and atom_types[t] == canonical[t][1] for t in members)):
            if name in resolved and resolved[name] != members:
                raise ValueError(f'Conflicting definition for species {name!r}')
            resolved[name] = members
    return SpeciesMap(resolved)


def species_type_sets(atom_types, ff=None, groups=None):
    """Legacy dictionary view of the generic map, including applicable presets."""
    return make_species_map(atom_types, ff=ff, groups=groups).type_sets()


def resolve_species(name, atom_types, ff=None, groups=None):
    """Legacy resolver routed through SpeciesMap; unknown names never mean all."""
    return make_species_map(atom_types, ff=ff, groups=groups).resolve(name)


def species_display_name(name, atom_types, ff=None, groups=None):
    """Format a resolved selection without changing its cache/file identifier.

    Preset display semantics require matching membership and matching slot
    labels; reusing a familiar group name alone is insufficient evidence.
    """
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
