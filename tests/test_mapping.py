"""Type<->element resolution: canonical tables, prep emission, post detection.

The convention is fixed by the ACE potential itself
(`pair_coeff * * ACE_Fe-O.yace Fe Mn O` -> 1=Fe_up, 2=Fe_down, 3=O, with 'Mn'
standing in for spin-down Fe; Bienvenu et al., npj Comput. Mater. 2025, 11:81).
Everything below asserts that both sides of the pipeline agree on it.
"""
import _util  # noqa: F401  (path bootstrap)

from lammpkeeper.common.mapping import (
   type_to_label, element_to_label, label_to_type, element_to_type,
   element_order, FORCE_FIELDS)


def test_canonical_tables():
    assert type_to_label('ace') == {1: 'Fe_up', 2: 'Fe_down', 3: 'O'}
    assert type_to_label('reaxff') == {1: 'Fe', 2: 'O'}
    assert type_to_label('hdnnp') == {1: 'Fe', 2: 'O'}
    assert element_to_label('ace') == {'Fe': 'Fe_up', 'Mn': 'Fe_down', 'O': 'O'}
    assert label_to_type('ace') == {'Fe_up': 1, 'Fe_down': 2, 'O': 3}
    assert element_to_type('ace') == {'Fe': 1, 'Mn': 2, 'O': 3}
    # Order matters: this is what goes into pair_coeff and dump_modify element.
    assert element_order('ace') == ['Fe', 'Mn', 'O']
    assert element_order('reaxff') == ['Fe', 'O']
    # ACE 'Mn' is the spin-down Fe proxy, not real manganese.
    assert FORCE_FIELDS['ace'][2] == ('Mn', 'Fe_down')


def test_prep_presets_preserved():
    from lammps_pre.state import FF_PRESETS
    assert FF_PRESETS['ace']['atom_types'] == {1: 'Fe_up', 2: 'Fe_down', 3: 'O'}
    assert FF_PRESETS['reaxff2010']['atom_types'] == {1: 'Fe', 2: 'O'}
    assert FF_PRESETS['reaxff2015']['atom_types'] == {1: 'Fe', 2: 'O'}


def test_prep_ace_emits_element_labels():
    """prep must write the convention into the trajectory, not leave it implicit."""
    from lammps_pre.state import FF_PRESETS
    ace = FF_PRESETS['ace']
    assert 'element' in ace['dump_fields'].split()
    # pair_coeff and dump_modify must carry the same element order.
    assert ace['pair_coeff'].split()[-3:] == element_order('ace')


def test_post_detect_ace_element_path_is_type_keyed():
    """Rule 2: element column with 'Mn'. atom_types is keyed by type NUMBER.

    Element-keyed entries used to slip past the `isinstance(t, int)` guards in
    state._guess_surface_z / _guess_o_type, which then fell back to "Fe is type 1"
    and dropped Fe_down entirely.
    """
    _util.require_numpy()
    import numpy as np
    from lammps_post.parsers import detect_forcefield
    frames = [{'elements': ['Fe', 'Mn', 'O'], 'atoms': np.zeros((3, 3), dtype=float)}]
    info = detect_forcefield(['id', 'x', 'y', 'z'], {'x': 0, 'y': 1, 'z': 2}, frames)
    assert info['forcefield'] == 'ace'
    assert info['unit_system'] == 'metal'
    assert info['has_element'] is True
    assert info['atom_types'] == type_to_label('ace')
    assert all(isinstance(k, int) for k in info['atom_types'])


def test_post_detect_ace_labelless_uses_the_convention_not_atom_counts():
    """Rule 3: legacy dumps with no element column.

    This used to guess O as "the rarest type, if it has <20% of the most common".
    That premise is false for the bulk magnetite these runs target (Fe3O4 is
    Fe:O = 3:4, so O is the MOST abundant species), and it inverts under strong
    spin polarization — the minority Fe became "O" and every O-based analysis
    silently went wrong. The last two cases below are the ones that used to fail.
    """
    _util.require_numpy()
    import numpy as np
    from lammps_post.parsers import detect_forcefield

    def detect(n_up, n_down, n_o):
        types = np.array([1] * n_up + [2] * n_down + [3] * n_o, dtype=float)
        atoms = np.zeros((len(types), 2), dtype=float)
        atoms[:, 1] = types
        frames = [{'atoms': atoms, 'elements': None}]
        return detect_forcefield(['id', 'type'], {'id': 0, 'type': 1}, frames)['atom_types']

    for n_up, n_down, n_o in [
          (41, 87, 8),        # slab + O2 gas (O is rarest)
          (64, 128, 256),     # bulk Fe3O4    (O is the MAJORITY)
          (400, 3600, 400),   # 10% spin-up   (used to yield {2:Fe_up, 3:Fe_down, 1:O})
          (80, 3920, 400),    # 2%  spin-up   (same failure)
    ]:
        assert detect(n_up, n_down, n_o) == type_to_label('ace'), (n_up, n_down, n_o)


def _write_element_dump(path, counts):
    """Minimal element-only dump: `id element x y z`, like the ACE examples."""
    n = sum(counts.values())
    lines = ['ITEM: TIMESTEP', '0', 'ITEM: NUMBER OF ATOMS', str(n),
             'ITEM: BOX BOUNDS pp pp pp', '0 10', '0 10', '0 10',
             'ITEM: ATOMS id element x y z']
    i = 0
    for el, c in counts.items():
        for _ in range(c):
            i += 1
            lines.append(f'{i} {el} 1.0 1.0 1.0')
    with open(path, 'w') as fh:
        fh.write('\n'.join(lines) + '\n')


def test_type_synthesis_from_elements_is_canonical_not_alphabetical():
    """An element-only dump gets a synthesized numeric 'type' column.

    Numbering the elements alphabetically only works when all of them appear in
    frame 0. A spin-equilibration run that starts fully polarized has no 'Fe'
    yet, so Mn and O would be numbered 1 and 2 — and O, really type 3, would be
    read as Fe_down by every type-based analysis.
    """
    _util.require_numpy()
    import os
    import tempfile
    import numpy as np
    from _util import noninteractive
    from lammps_post.shell import LammpsPostShell

    def synthesized_types(counts):
        d = tempfile.mkdtemp()
        p = os.path.join(d, 'traj.dump')
        _write_element_dump(p, counts)
        sh = LammpsPostShell()
        with noninteractive():
            sh.do_load(f'dump {p}')
        s = sh.state
        t = s.dump_frames[0]['atoms'][:, s.dump_col_idx['type']].astype(int)
        return {int(k): int(v) for k, v in zip(*np.unique(t, return_counts=True))}

    assert synthesized_types({'Fe': 10, 'Mn': 20, 'O': 40}) == {1: 10, 2: 20, 3: 40}
    # No Fe_up present: Mn stays type 2 and O stays type 3 (alphabetical gave 1, 2).
    assert synthesized_types({'Mn': 30, 'O': 40}) == {2: 30, 3: 40}
