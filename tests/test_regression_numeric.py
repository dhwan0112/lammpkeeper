"""Numeric regression: golden fingerprints on the ACE example trajectory.

Guards that refactors do not change analysis output. Golden hashes were
captured on the committed baseline (see MIGRATION.md, Stage 2 step B).
Fast checks run by default; RDF/MSD are slower and opt-in via LKPR_SLOW=1.
Skips cleanly when numpy or the fixture is unavailable.
"""
import os

import _util  # noqa: F401  (path bootstrap)
from _util import FIXTURE, have_numpy, noninteractive, section_hash, skip

# sha256[:16] of the canonical fingerprints (baseline commit bb6c634).
#
# post_ff_info was re-baselined when atom_types became type-keyed everywhere
# (detect_forcefield Rule 2 used to return element keys: {'Fe':'Fe_up', ...}).
# Representation only — the physics fingerprints below are byte-identical
# across that change, and _guess_o_type still returns 3.
GOLDEN_FAST = {
   # Hashes certify reproducibility only; analytic tests supply independent checks.
   'post_ff_info': 'a89e3dee6928721b',
   'post_guess_o_type': '4e07408562bedb8b',
   'spin': 'bf7fa759103f2883',
}
GOLDEN_SLOW = {
    # AUDIT-20261027, explicitly approved by maintainer during this session:
    # mean of per-frame RDFs, each normalized by its own N_a*N_b/V, replaces
    # normalization of the pooled histogram by the FINAL frame's density.
    # Old hash 46e63f7e15ac805b; peak 55.81320591646232 -> 55.81309067093663.
    # Independent full A-B displacement matrices agree (test_audit_rdf_oracle).
    # Last 20 frames include minimization: an arithmetic regression, not an
    # equilibrium phase/kinetics validation. Fixtures and MSD goldens unchanged.
    'rdf_FeUp_O': '129e29ad92fc7d6f',
    'msd_O': 'ce2e617b3ad32239',
    # PHYS-1/2, maintainer-approved 2026-10-27: the bulk dump says pp pp pp.
    # The old slab-default hash eb7f778ead75a17d ended at 17.4725703688831 A^2;
    # xyz unwrapping gives 0.074623992827988 A^2 (hash below). Four z-wrapping
    # atoms caused the false box-sized jumps. Independent ID dictionaries and
    # brute-force periodic-image enumeration agree within 4.17e-16 A^2;
    # test_msd also checks analytic vibrations and explicit bulk/slab crossings.
    # This endpoint includes minimization: a regression target, not a certified
    # equilibrium thermal MSD. The historical time-axis heuristic is unchanged.
    'msd_FeUp': '8a151e1c5051cb59',
}


def _available():
    """Require NumPy and the reference trajectory before checking fingerprints."""
    return have_numpy() and os.path.exists(FIXTURE)


def _load_state():
    """Load the committed ACE example through the same shell path used by users."""
    from lammps_post.shell import LammpsPostShell
    sh = LammpsPostShell()
    with noninteractive():
        sh.do_load(f'dump {FIXTURE}')
    return sh.state


def test_numeric_regression_fast():
    """Metadata and spin hashes detect baseline drift, not independent physical truth."""
    if not _available():
        skip('numpy not installed or fixture not found')
    from lammps_post import analysis as A
    s = _load_state()
    assert section_hash(dict(s.ff_info)) == GOLDEN_FAST['post_ff_info']
    assert section_hash(s._guess_o_type()) == GOLDEN_FAST['post_guess_o_type']
    spin = A.analyze_spin_evolution(s.dump_frames, s.dump_col_idx, dt_fs=s.dt_fs)
    assert section_hash(spin) == GOLDEN_FAST['spin']


def test_numeric_regression_rdf_msd_slow():
    """Opt-in bulk RDF/MSD fingerprints preserve the documented reference arithmetic."""
    if os.environ.get('LKPR_SLOW') != '1':
        skip('LKPR_SLOW=1 not set (opt-in RDF/MSD golden)')
    if not _available():
        skip('numpy not installed or fixture not found')
    from lammps_post import analysis as A
    s = _load_state()
    f, ci = s.dump_frames, s.dump_col_idx
    from lammps_post.parsers import pbc_from_boundary
    pbc = pbc_from_boundary(f.reader.boundary)
    assert pbc == (True, True, True), 'the ACE reference trajectory is bulk, not a slab'
    assert section_hash(A.compute_rdf(f, ci, type_a=1, type_b=3, z_pbc=True)) == GOLDEN_SLOW['rdf_FeUp_O']
    assert section_hash(A.analyze_msd(f, ci, species_type=3, dt_fs=s.dt_fs, pbc=pbc)) == GOLDEN_SLOW['msd_O']
    assert section_hash(A.analyze_msd(f, ci, species_type=1, dt_fs=s.dt_fs, pbc=pbc)) == GOLDEN_SLOW['msd_FeUp']
