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

Value-preserving: the derived tables are exactly equal to the literals they
replaced. This does NOT change post's atom-count heuristic (detect_forcefield
Rule 3), which is the separate, flagged reverse-map fragility.
"""

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
