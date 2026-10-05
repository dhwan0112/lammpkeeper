"""Numeric regression: golden fingerprints on the ACE example trajectory.

Guards that refactors do not change analysis output. Golden hashes were
captured on the committed baseline (see MIGRATION.md, Stage 2 step B).
Fast checks run by default; RDF/MSD are slower and opt-in via LKPR_SLOW=1.
Skips cleanly when numpy or the fixture is unavailable.
"""
import os

import _util  # noqa: F401  (path bootstrap)
from _util import FIXTURE, have_numpy, noninteractive, section_hash

# sha256[:16] of the canonical fingerprints (baseline commit bb6c634).
#
# post_ff_info was re-baselined when atom_types became type-keyed everywhere
# (detect_forcefield Rule 2 used to return element keys: {'Fe':'Fe_up', ...}).
# Representation only — the physics fingerprints below are byte-identical
# across that change, and _guess_o_type still returns 3.
GOLDEN_FAST = {
   'post_ff_info': 'a89e3dee6928721b',
   'post_guess_o_type': '4e07408562bedb8b',
   'spin': 'bf7fa759103f2883',
}
GOLDEN_SLOW = {
   'rdf_FeUp_O': '46e63f7e15ac805b',
   'msd_O': 'ce2e617b3ad32239',
   'msd_FeUp': 'eb7f778ead75a17d',
}


def _available():
    return have_numpy() and os.path.exists(FIXTURE)


def _load_state():
    from lammps_post.shell import LammpsPostShell
    sh = LammpsPostShell()
    with noninteractive():
        sh.do_load(f'dump {FIXTURE}')
    return sh.state


def test_numeric_regression_fast():
    if not _available():
        return  # skip: no numpy or fixture
    from lammps_post import analysis as A
    s = _load_state()
    assert section_hash(dict(s.ff_info)) == GOLDEN_FAST['post_ff_info']
    assert section_hash(s._guess_o_type()) == GOLDEN_FAST['post_guess_o_type']
    spin = A.analyze_spin_evolution(s.dump_frames, s.dump_col_idx, dt_fs=s.dt_fs)
    assert section_hash(spin) == GOLDEN_FAST['spin']


def test_numeric_regression_rdf_msd_slow():
    if os.environ.get('LKPR_SLOW') != '1':
        return  # opt-in (RDF/MSD are slower)
    if not _available():
        return
    from lammps_post import analysis as A
    s = _load_state()
    f, ci = s.dump_frames, s.dump_col_idx
    assert section_hash(A.compute_rdf(f, ci, type_a=1, type_b=3, z_pbc=True)) == GOLDEN_SLOW['rdf_FeUp_O']
    assert section_hash(A.analyze_msd(f, ci, species_type=3, dt_fs=s.dt_fs)) == GOLDEN_SLOW['msd_O']
    assert section_hash(A.analyze_msd(f, ci, species_type=1, dt_fs=s.dt_fs)) == GOLDEN_SLOW['msd_FeUp']
