"""REV-IO-9: pair_coeff species maps use exact pair-style names (ADR-0005).

parse_input used substring tests (`'ace' in substyle`, `'n2p2' in substyle`)
to decide which hybrid sub-styles carry a species map and which styles take no
potential file, while ADR-0005's classifier accepts exact LAMMPS names only.
The maintainer approved (2026-11-02) using the same exact-name table for both
decisions. Real LAMMPS names (pace, pace/kk, reaxff, reax/c, hdnnp, ...) map
as before; names that are not LAMMPS pair styles (`ace`, `n2p2`, `mypace`) no
longer count as ACE/HDNNP styles. Labels are made up (A, B) so no Fe/O
literal can make a test pass.
"""
import os
import tempfile
import warnings

import _util  # noqa: F401  (path bootstrap)


def _config(text):
    """parse_input of an input script text, warnings silenced."""
    from lammps_post.parsers import parse_input
    fd, path = tempfile.mkstemp(suffix='.in')
    with os.fdopen(fd, 'w') as f:
        f.write('units metal\n' + text)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            return parse_input(path)
    finally:
        os.remove(path)


def test_hybrid_lammps_sub_styles_still_map_species():
    """pace, pace/kk, reaxff, reax/c, a numbered pace and hdnnp map exactly as before."""
    cases = {
        'pace': 'pair_coeff * * pace pot.yace A B\n',
        'pace/kk': 'pair_coeff * * pace/kk pot.yace A B\n',
        'reaxff NULL': 'pair_coeff * * reaxff ffield.reax A B\n',
        'reax/c NULL': 'pair_coeff * * reax/c ffield.reax A B\n',
        'pace pace': 'pair_coeff * * pace 1 pot.yace A B\n',
        'hdnnp 6.0 dir nnp': 'pair_coeff * * hdnnp A B\n',
    }
    for sub, coeff in cases.items():
        config = _config(f'pair_style hybrid/overlay {sub} zbl 1.0 2.0\n{coeff}pair_coeff 1 1 zbl 26 26\n')
        assert config['element_map'] == {1: 'A', 2: 'B'}, (sub, config['element_map'])
    hd = _config('pair_style hybrid hdnnp 6.0 dir nnp zbl 1.0 2.0\npair_coeff * * hdnnp A B\n')
    assert hd['pair_coeff'] == {'potential_file': None, 'elements': ['A', 'B']}


def test_hybrid_non_lammps_names_no_longer_map_species():
    """`ace`, `n2p2` and a made-up `mypace` contain a substring but are not LAMMPS styles."""
    for sub in ('ace', 'n2p2', 'mypace'):
        config = _config(f'pair_style hybrid {sub} lj/cut 2.5\npair_coeff * * {sub} pot.file A B\n')
        assert config['element_map'] == {}, (sub, config['element_map'])
        assert config['pair_coeff'] is None, (sub, config['pair_coeff'])


def test_non_hybrid_styles_follow_exact_names():
    """hdnnp takes no potential file; every other style uses `file elements` as LAMMPS does."""
    hd = _config('pair_style hdnnp 6.0 dir nnp\npair_coeff * * A B\n')
    assert hd['pair_coeff'] == {'potential_file': None, 'elements': ['A', 'B']}
    assert hd['element_map'] == {1: 'A', 2: 'B'}
    eam = _config('pair_style eam/alloy\npair_coeff * * pot.eam.alloy A B\n')
    assert eam['pair_coeff'] == {'potential_file': 'pot.eam.alloy', 'elements': ['A', 'B']}
    # `n2p2` is the library behind hdnnp, not a LAMMPS pair style (LAMMPS
    # rejects it); its pair_coeff is read with the general `file elements` rule.
    n2p2 = _config('pair_style n2p2\npair_coeff * * weights.data A B\n')
    assert n2p2['pair_coeff'] == {'potential_file': 'weights.data', 'elements': ['A', 'B']}
