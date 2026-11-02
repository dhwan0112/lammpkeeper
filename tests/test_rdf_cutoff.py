"""REV-ANALYSIS-7: RDF cutoff beyond the nearest-image limit is flagged.

compute_rdf counts the nearest periodic image of each pair (ADR-0003). That
count is complete only for r < half the shortest nonzero periodic lattice
vector (``r_complete``); beyond it, a second image within the cutoff is missed
and g(r) is undercounted. The maintainer chose (2026-11-01) to keep the
nearest-image estimator, warn, and report ``r_complete`` in the result, plot
and exports. Oracles below enumerate lattice vectors and images explicitly from
literal bases; production MIC and the new helper never generate expectations.
"""
import itertools
from unittest.mock import patch
import warnings

import _util

COL = dict(id=0, type=1, x=2, y=3, z=4)


def _frames(positions, types, lengths=(10, 10, 10), tilt=(0, 0, 0), pbc=None, step=0):
    """One frame; a typed Box when `pbc` is given, else legacy bounds only."""
    import numpy as np
    pos = np.asarray(positions, float)
    rows = np.column_stack((np.arange(1, len(pos) + 1), types, pos))
    frame = dict(atoms=rows, box=np.column_stack(((0, 0, 0), lengths)).astype(float), timestep=step)
    if pbc is not None:
        from lammpkeeper.io import Box
        frame['cell'] = Box((0, 0, 0), lengths, tilt=tilt, pbc=pbc)
        frame['box'] = frame['cell'].bounds
        if any(tilt):
            frame['tilt'] = tilt
    return [frame]


def _brute_radius(basis):
    """Half the shortest nonzero integer combination of literal rows, |n_i| <= 6."""
    import numpy as np
    best = np.inf
    for n in itertools.product(range(-6, 7), repeat=len(basis)):
        if any(n):
            v = np.asarray(n, float) @ basis
            best = min(best, float(np.sqrt(v @ v)))
    return best / 2


def _rdf(*args, **kwargs):
    """compute_rdf with warnings recorded; returns (result, list of messages)."""
    from lammps_post.analysis import compute_rdf
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        result = compute_rdf(*args, **kwargs)
    return result, [str(w.message) for w in caught if 'r_complete' in str(w.message)]


def _random(n, lengths, seed):
    """Reproducible random positions inside an orthogonal box."""
    import numpy as np
    return np.random.default_rng(seed).uniform(0, 1, (n, 3)) * np.asarray(lengths, float)


def test_unique_image_radius_is_half_the_shortest_periodic_vector():
    """Exact for orthogonal and tilted cells and every PBC subset; inf without PBC."""
    _util.require_numpy()
    import numpy as np
    from lammpkeeper.core.geometry import unique_image_radius
    from lammpkeeper.io import Box
    cells = [((10, 12, 30), (0, 0, 0)), ((10, 10, 30), (5, 0, 0)),
             ((10, 3, 8), (4, 0, 0)), ((3, 4, 5), (1.1, -.8, .7)), ((4, 5, 6), (-1.2, .6, -1.3))]
    for lengths, tilt in cells:
        h = np.array([[lengths[0], 0, 0], [tilt[0], lengths[1], 0],
                      [tilt[1], tilt[2], lengths[2]]], float)
        for pbc in itertools.product((True, False), repeat=3):
            got = unique_image_radius(Box((0, 0, 0), lengths, tilt=tilt, pbc=pbc))
            if not any(pbc):
                assert got == float('inf')
                continue
            want = _brute_radius(h[list(pbc)])
            assert np.isclose(got, want, rtol=1e-12, atol=0), (lengths, tilt, pbc, got, want)
    # Plane spacing (8.94/2 = 4.47) would wrongly cap this cell below 5.
    assert unique_image_radius(Box((0, 0, 0), (10, 10, 30), tilt=(5, 0, 0),
                                   pbc=(True, True, False))) == 5.0


def test_cutoff_beyond_limit_warns_and_reports_r_complete():
    """r_max above min periodic L/2 warns; r_complete is reported either way."""
    _util.require_numpy()
    pos = _random(40, (10, 10, 10), 1)
    types = [1] * 20 + [2] * 20
    result, messages = _rdf(_frames(pos, types), COL, 1, 2, r_max=6.0, pbc=(True, True, True))
    assert result['r_complete'] == 5.0
    assert len(messages) == 1 and '5' in messages[0] and 'undercount' in messages[0], messages
    result, messages = _rdf(_frames(pos, types), COL, 1, 2, r_max=5.0, pbc=(True, True, True))
    assert result['r_complete'] == 5.0 and messages == []
    # Slab: only periodic axes count. Lz = 4 does not limit a p p f cutoff.
    slab = _random(40, (10, 12, 4), 2)
    result, messages = _rdf(_frames(slab, types, lengths=(10, 12, 4)), COL, 1, 2,
                            r_max=4.5, pbc=(True, True, False))
    assert result['r_complete'] == 5.0 and messages == []
    # Legacy z_pbc switch: z periodic now limits the cutoff.
    result, messages = _rdf(_frames(slab, types, lengths=(10, 12, 4)), COL, 1, 2,
                            r_max=4.5, z_pbc=True)
    assert result['r_complete'] == 2.0 and len(messages) == 1
    # No periodic axis: no nearest-image limit.
    result, messages = _rdf(_frames(pos, types), COL, 1, 2, r_max=6.0, pbc=(False, False, False))
    assert result['r_complete'] == float('inf') and messages == []


def test_below_limit_matches_all_image_oracle_and_above_limit_undercounts():
    """Independent all-image counts equal g up to r_complete and exceed it beyond."""
    _util.require_numpy()
    import numpy as np
    lengths = np.array([10.0, 10.0, 10.0])
    pos = _random(60, lengths, 3)
    types = np.array([1] * 30 + [2] * 30)
    a, b = pos[types == 1], pos[types == 2]

    def oracle(r_max, n_bins):
        """Count every periodic image (|n| <= 2) of each A-B pair below r_max."""
        edges = np.linspace(0, r_max, n_bins + 1)
        hist = np.zeros(n_bins)
        for shift in itertools.product(range(-2, 3), repeat=3):
            d = b[None, :, :] + np.asarray(shift) * lengths - a[:, None, :]
            r = np.linalg.norm(d, axis=2).ravel()
            r = r[(r > 0) & (r < r_max)]
            hist += np.histogram(r, bins=edges)[0]
        shell = (4 / 3) * np.pi * np.diff(edges ** 3)
        return hist / (len(a) * shell * len(b) / lengths.prod())

    got, _ = _rdf(_frames(pos, types), COL, 1, 2, r_max=5.0, n_bins=50, pbc=(True, True, True))
    np.testing.assert_allclose(got['g'], oracle(5.0, 50), rtol=1e-12, atol=1e-12)
    got, _ = _rdf(_frames(pos, types), COL, 1, 2, r_max=8.0, n_bins=80, pbc=(True, True, True))
    want = oracle(8.0, 80)
    inside = got['r'] < 5.0
    np.testing.assert_allclose(got['g'][inside], want[inside], rtol=1e-12, atol=1e-12)
    # Beyond r_complete the nearest-image estimator misses pairs: this is what the warning flags.
    assert np.sum(want[~inside]) > 1.2 * np.sum(got['g'][~inside])


def test_fast_and_fallback_paths_report_the_same_limit():
    """The cKDTree path and the row-wise fallback give the same r_complete and warning."""
    _util.require_numpy()
    import numpy as np
    pos = _random(40, (10, 11, 12), 4)
    types = [1] * 20 + [2] * 20
    fast, fast_msg = _rdf(_frames(pos, types, lengths=(10, 11, 12)), COL, 1, 2, r_max=6.0,
                          pbc=(True, True, True))
    with patch('lammps_post.analysis._rdf_candidate_pairs', return_value=None):
        slow, slow_msg = _rdf(_frames(pos, types, lengths=(10, 11, 12)), COL, 1, 2, r_max=6.0,
                              pbc=(True, True, True))
    assert fast['r_complete'] == slow['r_complete'] == 5.0
    assert fast_msg == slow_msg and len(fast_msg) == 1
    np.testing.assert_array_equal(fast['g'], slow['g'])


def test_triclinic_cell_uses_the_exact_lattice_limit():
    """A tilted typed cell is limited by its shortest lattice vector, not plane spacing."""
    _util.require_numpy()
    pos = [[1, 1, 5], [4, 6, 5], [8, 2, 6], [3, 8, 4]]
    frames = _frames(pos, [1, 2, 1, 2], lengths=(10, 10, 30), tilt=(5, 0, 0),
                     pbc=(True, True, False))
    result, messages = _rdf(frames, COL, 1, 2, r_max=4.8, n_bins=12)
    assert result['r_complete'] == 5.0 and messages == []
    result, messages = _rdf(frames, COL, 1, 2, r_max=5.2, n_bins=12)
    assert result['r_complete'] == 5.0 and len(messages) == 1


def test_exports_and_plot_mark_an_incomplete_range():
    """CSV/LaTeX header and the RDF plot show r_complete only when it is below r_max."""
    _util.require_numpy()
    from lammps_post.shell import LammpsPostShell
    pos = _random(40, (10, 10, 10), 5)
    types = [1] * 20 + [2] * 20
    incomplete, _ = _rdf(_frames(pos, types), COL, 1, 2, r_max=6.0, pbc=(True, True, True))
    complete, _ = _rdf(_frames(pos, types), COL, 1, 2, r_max=5.0, pbc=(True, True, True))
    lines = LammpsPostShell._export_header_lines(incomplete)
    assert any(line.startswith('r_complete: 5 ') and 'nearest' in line for line in lines), lines
    assert not any('r_complete' in line for line in LammpsPostShell._export_header_lines(complete))
    try:
        import matplotlib
    except ImportError:
        _util.skip('matplotlib not installed: plot marker not checked')
    matplotlib.use('Agg')
    from lammps_post import plotting
    for data, marked in ((incomplete, True), (complete, False)):
        figures = []
        with patch.object(plotting, '_save_fig', side_effect=lambda fig, *a, **k: figures.append(fig)):
            plotting.plot_rdf(data, '/nonexistent-not-written')
        xs = [tuple(line.get_xdata()) for line in figures[0].axes[0].get_lines()]
        assert ((5.0, 5.0) in xs) == marked, xs
