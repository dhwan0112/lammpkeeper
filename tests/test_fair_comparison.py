"""The fair-comparison invariant: every force field starts from the SAME structure.

The whole point of the study is to compare force fields on one system, so the
only thing that may differ between their inputs is the file format — atom style,
type count, charge column. Coordinates, box, and regions must be identical.

This used to fail. `compute_regions` anchored the reflective O2 wall to the
force field's own interaction cutoff (`state.rc`: ACE 7.0 A, ReaxFF 5.0 A), and
the wall in turn anchors both the O2 placement band and the box height. The Fe
slab matched across force fields; the O2 layer sat 2.0 A higher and the box was
2.0 A taller for ACE. Fixed by placing the wall at the LARGEST cutoff for every
force field (state.WALL_CUTOFF), which satisfies all of them and depends on none.

Needs ASE (prep's slab builder); skips cleanly without it.
"""
import _util  # noqa: F401  (path bootstrap)

FIELDS = ('ace', 'reaxff2010', 'reaxff2015')


def _have_ase():
    """Probe the optional structure builder rather than passing an unbuilt system."""
    try:
        import ase  # noqa: F401
        return True
    except ImportError:
        return False


def _build(ff):
    """Build the identical system under force field `ff`."""
    from lammps_pre.state import PreState
    from lammps_pre.builders import build_all
    import io
    import contextlib

    s = PreState()
    assert s.set_ff(ff)          # set_ff, not `s.forcefield = ...`: it loads the preset
    s.temperature = 800
    s.nx, s.ny, s.nz = 4, 4, 8
    s.n_o2 = 4
    s.boundary = 'p p f'
    s.seed = 12345
    with contextlib.redirect_stdout(io.StringIO()):
        return build_all(s)


def test_all_force_fields_build_identical_coordinates():
    """A fixed seed and geometry must yield bit-identical atoms across presets."""
    _util.require(_have_ase(), 'ase not installed')
    _util.require_numpy()
    import numpy as np

    builds = {ff: _build(ff) for ff in FIELDS}
    # Compare coordinates directly, not derived energies that legitimately differ by FF.
    assert all(b is not None for b in builds.values())

    ref_ff = FIELDS[0]
    ref = builds[ref_ff]
    for ff in FIELDS[1:]:
        b = builds[ff]
        assert np.array_equal(b.fe_positions, ref.fe_positions), f'{ff}: Fe moved'
        # The O2 gas is the part that used to drift with the cutoff.
        assert np.array_equal(b.o2_positions, ref.o2_positions), f'{ff}: O2 moved'
        assert np.array_equal(b.cell, ref.cell), f'{ff}: cell differs'
        assert b.box == ref.box, f'{ff}: box differs ({b.box} vs {ref.box})'
        assert b.n_atoms == ref.n_atoms


def test_wall_does_not_depend_on_the_force_field():
    """The regression guard proper: the wall must not track state.rc again."""
    _util.require(_have_ase(), 'ase not installed')
    _util.require_numpy()
    from lammps_pre.state import PreState, WALL_CUTOFF, FF_PRESETS

    # The shared cutoff must clear every force field's own cutoff, or the O2 gas
    # could feel the slab before the oxidation stage lifts the wall.
    assert WALL_CUTOFF == max(p['rc'] for p in FF_PRESETS.values())
    for ff in FIELDS:
        s = PreState()
        assert s.set_ff(ff)
        assert s.wall_cutoff == WALL_CUTOFF
        assert s.wall_cutoff >= s.rc, f'{ff}: wall inside its own cutoff'

    walls = {ff: _build(ff).regions['z_wall_lower'] for ff in FIELDS}
    assert len(set(walls.values())) == 1, f'wall is force-field dependent: {walls}'
