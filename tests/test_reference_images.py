"""REV-REF-2: reference RDFs enumerate every periodic image inside the cutoff.

The oracle here is a direct Cartesian image enumeration whose finite range is
justified from the reciprocal lattice, independently of the production code:
the perpendicular width of the cell along lattice direction i is
``w_i = 1 / |b_i|`` for reciprocal row ``b_i`` (``inv(cell).T``). An image at
integer offset ``n_i`` of a site whose unwrapped fractional difference lies in
(-1, 1) is at least ``(|n_i| - 1) * w_i`` away, so offsets with
``|n_i| > r_max / w_i + 1`` cannot fall inside the cutoff. Enumerating up to
``ceil(r_max / w_i) + 1`` on every axis is therefore complete; interiority of
the result is not the argument.
"""
import itertools
import math

import _util


def _brute_force_counts(crystal, pair, r_max, n_bins):
    """Oracle pair-count histogram from an explicit, generously sized supercell."""
    import numpy as np
    cell = np.asarray(crystal['cell'], dtype=float)
    elements = [e for e, _ in crystal['atoms']]
    frac = np.array([f for _, f in crystal['atoms']], dtype=float)
    cart = frac @ cell
    pos_a = cart[[e == pair[0] for e in elements]]
    pos_b = cart[[e == pair[1] for e in elements]]
    widths = 1.0 / np.linalg.norm(np.linalg.inv(cell).T, axis=1)
    reach = [math.ceil(r_max / w) + 1 for w in widths]
    shifts = np.array(list(itertools.product(*[range(-k, k + 1) for k in reach]))) @ cell
    counts = np.zeros(n_bins, dtype=int)
    dr = r_max / n_bins
    for a in pos_a:
        d = (pos_b[:, None, :] + shifts[None, :, :]) - a
        r = np.linalg.norm(d, axis=2).ravel()
        r = r[(r > 0.01) & (r < r_max)]
        counts += np.bincount((r / dr).astype(int), minlength=n_bins)[:n_bins]
    return counts, len(pos_a), len(pos_b), abs(float(np.linalg.det(cell)))


def _counts_from_rdf(ref, n_a, n_b, vol, r_max, n_bins):
    """Recover integer pair counts per bin from g(r) and the normalization."""
    import numpy as np
    edges = np.linspace(0, r_max, n_bins + 1)
    shell_vol = (4 / 3) * np.pi * (edges[1:] ** 3 - edges[:-1] ** 3)
    counts = ref['g'] * n_a * shell_vol * (n_b / vol)
    rounded = np.rint(counts)
    np.testing.assert_allclose(counts, rounded, atol=1e-6)
    return rounded.astype(int)


def test_alpha_fe_outer_shells_are_complete_at_the_default_cutoff():
    """bcc Fe-Fe shells up to 6 Å, including the sixfold 2a shell at 5.733 Å."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.references import CRYSTAL_DB, compute_reference_rdf

    crystal = CRYSTAL_DB['alpha-Fe']
    a = float(np.linalg.norm(crystal['cell'][0]))
    r_max, n_bins = 6.0, 200
    ref = compute_reference_rdf('alpha-Fe', pair=('Fe', 'Fe'), r_max=r_max, n_bins=n_bins)
    # Pair counts summed over both sites of the cell; per-site coordination
    # is half of that.
    counts = _counts_from_rdf(ref, 2, 2, a ** 3, r_max, n_bins) // 2
    # Independent bcc shell table: radius in units of a, neighbours per site.
    shells = [(math.sqrt(3) / 2, 8), (1.0, 6), (math.sqrt(2), 12),
              (math.sqrt(11) / 2, 24), (math.sqrt(3), 8), (2.0, 6)]
    assert a * 2.0 < r_max < a * math.sqrt(19) / 2
    dr = r_max / n_bins
    for scale, expected in shells:
        radius = a * scale
        window = (ref['r'] > radius - 2 * dr) & (ref['r'] < radius + 2 * dr)
        assert counts[window].sum() == expected, (radius, counts[window])
    assert counts.sum() == sum(n for _, n in shells)
    # The former fourfold-supercell scheme gave 3 at 2a; a larger cutoff still
    # recovers the next shell (24 at a*sqrt(19)/2) without any replication knob.
    wide = compute_reference_rdf('alpha-Fe', pair=('Fe', 'Fe'), r_max=7.0, n_bins=700)
    wide_counts = _counts_from_rdf(wide, 2, 2, a ** 3, 7.0, 700) // 2
    radius = a * math.sqrt(19) / 2
    window = (wide['r'] > radius - 0.02) & (wide['r'] < radius + 0.02)
    assert wide_counts[window].sum() == 24


def test_builtin_histograms_match_independent_image_enumeration():
    """Every built-in phase and pair reproduces the brute-force count per bin."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.references import CRYSTAL_DB, compute_reference_rdf

    r_max, n_bins = 6.0, 200
    checked = 0
    for key, crystal in CRYSTAL_DB.items():
        present = sorted({e for e, _ in crystal['atoms']})
        for pair in itertools.product(present, repeat=2):
            expected, n_a, n_b, vol = _brute_force_counts(crystal, pair, r_max, n_bins)
            ref = compute_reference_rdf(key, pair=pair, r_max=r_max, n_bins=n_bins)
            got = _counts_from_rdf(ref, n_a, n_b, vol, r_max, n_bins)
            assert np.array_equal(got, expected), (key, pair)
            assert expected.sum() > 0
            checked += 1
    assert checked == 1 + 4 + 4 + 4


def test_cutoff_beyond_the_cell_and_skew_cells_stay_complete():
    """Images are complete when r_max exceeds the cell and for oblique cells."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.references import compute_reference_rdf

    r_max, n_bins = 7.0, 350
    # Simple cubic, one site, cutoff 3.5 cells: shell table in units of a.
    cubic = {'name': 'sc', 'cell': np.eye(3) * 2.0,
             'atoms': [('X', [0.0, 0.0, 0.0])]}
    ref = compute_reference_rdf(cubic, pair=('X', 'X'), r_max=r_max, n_bins=n_bins)
    counts = _counts_from_rdf(ref, 1, 1, 8.0, r_max, n_bins)
    squares = {}
    for n in itertools.product(range(-4, 5), repeat=3):
        q = sum(v * v for v in n)
        if 0 < q * 4.0 < r_max ** 2:
            squares[q] = squares.get(q, 0) + 1
    assert counts.sum() == sum(squares.values())
    dr = r_max / n_bins
    for q, expected in squares.items():
        radius = 2.0 * math.sqrt(q)
        window = (ref['r'] > radius - 2 * dr) & (ref['r'] < radius + 2 * dr)
        assert counts[window].sum() == expected, (radius, expected)

    # Strongly oblique two-site cell: the componentwise minimum image of the
    # former scheme is wrong here; the brute-force oracle is the reference.
    skew = {'name': 'skew',
            'cell': np.array([[3.0, 0.0, 0.0], [2.6, 1.1, 0.0], [1.9, 2.2, 1.4]]),
            'atoms': [('A', [0.0, 0.0, 0.0]), ('B', [0.37, 0.81, 0.52])]}
    for pair in (('A', 'B'), ('B', 'A'), ('A', 'A')):
        expected, n_a, n_b, vol = _brute_force_counts(skew, pair, r_max, n_bins)
        ref = compute_reference_rdf(skew, pair=pair, r_max=r_max, n_bins=n_bins)
        got = _counts_from_rdf(ref, n_a, n_b, vol, r_max, n_bins)
        assert np.array_equal(got, expected), pair
        assert expected.sum() > 50


def test_offset_box_is_the_width_bound_and_singular_cells_are_rejected():
    """_lattice_image_offsets spans ceil(r_max/width + 1/2) per axis (more for
    sheared cells), and singular, zero-r_max or non-finite inputs raise."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.references import _lattice_image_offsets, compute_reference_rdf

    offsets = _lattice_image_offsets(np.diag([2.0, 4.0, 13.0]), 6.0)
    # ceil(6/2 + .5) = 4, ceil(6/4 + .5) = 2, ceil(6/13 + .5) = 1
    assert offsets.min(axis=0).tolist() == [-4, -2, -1]
    assert offsets.max(axis=0).tolist() == [4, 2, 1]
    assert len(offsets) == 9 * 5 * 3
    # A sheared cell with the same volume keeps the same widths only along
    # the unsheared axis; the sheared axes need more images, never fewer.
    sheared = _lattice_image_offsets(np.array([[2.0, 0, 0], [3.0, 4.0, 0], [0, 0, 13.0]]), 6.0)
    assert sheared.max(axis=0)[2] == 1
    assert sheared.max(axis=0)[0] >= 4 and sheared.max(axis=0)[1] >= 2

    singular = {'name': 'flat', 'cell': [[1, 0, 0], [0, 1, 0], [1, 1, 0]],
                'atoms': [('X', [0, 0, 0])]}
    for bad_call in (
            lambda: compute_reference_rdf(singular, pair=('X', 'X')),
            lambda: _lattice_image_offsets(np.zeros((3, 3)), 6.0),
            lambda: _lattice_image_offsets(np.eye(3), 0.0),
            lambda: _lattice_image_offsets(np.eye(3) * float('nan'), 6.0),
    ):
        try:
            bad_call()
        except ValueError as exc:
            assert 'singular' in str(exc) or 'r_max' in str(exc) or 'finite' in str(exc), exc
        else:
            raise AssertionError('expected ValueError')

    assert compute_reference_rdf('alpha-Fe', pair=('Fe', 'O')) is None
    assert compute_reference_rdf('no-such-phase') is None
    assert compute_reference_rdf(42) is None
