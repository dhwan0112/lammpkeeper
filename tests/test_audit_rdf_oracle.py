"""Independent explicit-pair oracle supporting the approved RDF rebaseline.

The final fixture frames include minimization. This checks the RDF calculation,
not equilibrium sampling, a phase assignment or the physical time axis.
"""
import os
import numpy as np

import _util  # noqa: F401
from _util import FIXTURE, noninteractive, require


def test_fixture_rdf_matches_explicit_per_frame_pair_normalization():
    """Compare the last 20 fixture RDFs to full pair matrices with frame-local density."""
    # The explicit Cartesian pair matrix is intentionally a slow independent
    # oracle; missing opt-in or fixture data must be reported as a visible skip.
    require(os.environ.get('LKPR_SLOW') == '1', 'LKPR_SLOW=1 not set (RDF oracle)')
    require(os.path.exists(FIXTURE), 'ACE fixture not found')
    from lammps_post import analysis as a
    from lammps_post.shell import LammpsPostShell
    sh = LammpsPostShell()
    with noninteractive():
        sh.do_load(f'dump {FIXTURE}')
    frames, ci = sh.state.dump_frames, sh.state.dump_col_idx
    observed = a.compute_rdf(frames, ci, type_a=1, type_b=3, z_pbc=True)
    edges = np.linspace(0, 6, 201)
    shell_volumes = (4 * np.pi / 3) * np.diff(edges ** 3)
    curves = []
    for frame in frames[-20:]:
        rows = frame['atoms']
        lengths = np.diff(frame['box'], axis=1).ravel()
        pos_cols = [ci[c] for c in ('x', 'y', 'z')]
        pa = rows[rows[:, ci['type']] == 1][:, pos_cols]
        pb = rows[rows[:, ci['type']] == 3][:, pos_cols]
        # Full ordered A-B displacement matrix, without production pair search.
        delta = pb[None, :, :] - pa[:, None, :]
        # This reference call requests bulk periodicity on all three axes.
        delta -= lengths * np.rint(delta / lengths)
        distances = np.sqrt(np.sum(delta ** 2, axis=-1)).ravel()
        distances = distances[(distances > 0) & (distances < 6)]
        counts = np.bincount((distances / .03).astype(int), minlength=200)
        # N_a*rho_b times shell volume is the expected ideal-gas pair count.
        # Normalize each frame first: changing volume/population must not turn
        # the arithmetic ensemble mean into a pooled-histogram estimator.
        exposure = len(pa) * len(pb) / np.prod(lengths)
        curves.append(counts / (exposure * shell_volumes))
    np.testing.assert_allclose(observed['g'], np.mean(curves, axis=0),
                               rtol=1e-12, atol=1e-12)
    assert observed['n_frames'] == len(curves) == 20
