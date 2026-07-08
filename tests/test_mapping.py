"""Stage 2 mapping single-source-of-truth: canonical tables + value preservation."""
import _util  # noqa: F401  (path bootstrap)

from lammpkeeper.common.mapping import (
   type_to_label, element_to_label, label_to_type, FORCE_FIELDS)


def test_canonical_tables():
   assert type_to_label('ace') == {1: 'Fe_up', 2: 'Fe_down', 3: 'O'}
   assert type_to_label('reaxff') == {1: 'Fe', 2: 'O'}
   assert type_to_label('hdnnp') == {1: 'Fe', 2: 'O'}
   assert element_to_label('ace') == {'Fe': 'Fe_up', 'Mn': 'Fe_down', 'O': 'O'}
   assert label_to_type('ace') == {'Fe_up': 1, 'Fe_down': 2, 'O': 3}
   # ACE 'Mn' is the spin-down Fe proxy, not real manganese.
   assert FORCE_FIELDS['ace'][2] == ('Mn', 'Fe_down')


def test_prep_presets_preserved():
   from lammps_pre.state import FF_PRESETS
   assert FF_PRESETS['ace']['atom_types'] == {1: 'Fe_up', 2: 'Fe_down', 3: 'O'}
   assert FF_PRESETS['reaxff2010']['atom_types'] == {1: 'Fe', 2: 'O'}
   assert FF_PRESETS['reaxff2015']['atom_types'] == {1: 'Fe', 2: 'O'}


def test_post_detect_reverse_map_ace_element_path():
   if not _util.have_numpy():
      return  # skip without numpy
   import numpy as np
   from lammps_post.parsers import detect_forcefield
   frames = [{'elements': ['Fe', 'Mn', 'O'],
              'atoms': np.zeros((3, 3), dtype=float)}]
   info = detect_forcefield(['id', 'x', 'y', 'z'], {'x': 0, 'y': 1, 'z': 2}, frames)
   assert info['forcefield'] == 'ace'
   assert info['unit_system'] == 'metal'
   assert info['atom_types'] == {'Fe': 'Fe_up', 'Mn': 'Fe_down', 'O': 'O'}
