"""REV-ANALYSIS-5: selected nonfinite z must be rejected, never dropped or diluted.

All numeric examples are in-memory (plus one literal-``nan`` dump file) and use
arbitrary type IDs. Expected values come from explicit population arithmetic.
A NaN coordinate has an unknown location, so it is neither "absorbed" nor
"outside the range": the analysis must raise instead of inventing a value.
"""

import _util


COL = dict(type=0, q=1, z=2, unused=3)
Z_COL = dict(type=0, z=1)


def _frame(rows, step=40):
    """Orthogonal 10 A cube frame with columns type, z (rows are [type, z])."""
    import numpy as np
    return dict(atoms=np.asarray(rows, dtype=float).reshape(-1, 2), timestep=step,
                box=np.asarray([(0, 10)] * 3, dtype=float))


def _qframe(rows, step=40):
    """Frame with columns type, q, z, unused (rows are [type, q, z, 0])."""
    import numpy as np
    return dict(atoms=np.asarray(rows, dtype=float).reshape(-1, 4), timestep=step,
                box=np.asarray([(0, 10)] * 3, dtype=float))


def _reject(call, analysis, step, count=1):
    """Require an analysis-, timestep- and count-specific nonfinite-z ValueError."""
    try:
        call()
    except ValueError as exc:
        message = str(exc).lower()
        for text in (analysis.lower(), 'z', 'finite', f'timestep {step}',
                     f'{count} '):
            assert text in message, str(exc)
    else:
        raise AssertionError('selected nonfinite z must raise ValueError')


def _bad_values():
    """NaN and both infinities are all unusable coordinates."""
    import numpy as np
    return (np.nan, np.inf, -np.inf)


def test_oar_rejects_selected_nonfinite_z():
    """The [1, NaN] repro must not yield n_total=2, oar=.5 without comment."""
    _util.require_numpy()
    from lammps_post.analysis import compute_oar
    for bad in _bad_values():
        for index in (0, 1):
            frame = _frame([[6, 1.0], [6, 8.0]])
            frame['atoms'][index, 1] = bad
            _reject(lambda: compute_oar([frame], Z_COL, 5.0, o_type=6),
                    'OAR', 40)


def test_oar_counts_every_bad_atom_and_union_member():
    """The reported count covers all selected types, not just the first bad atom."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import compute_oar
    frame = _frame([[6, np.nan], [8, np.inf], [6, 1.0], [3, np.nan]])
    _reject(lambda: compute_oar([frame], Z_COL, 5.0, o_type={6, 8}),
            'OAR', 40, count=2)


def test_penetration_rejects_selected_nonfinite_z():
    """Summary penetration must not turn [1, NaN] into frac_adsorbed=.5."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_penetration
    for bad in _bad_values():
        frame = _frame([[6, 1.0], [6, bad]])
        _reject(lambda: analyze_penetration([frame], Z_COL, 5.0, o_type=6),
                'Penetration', 40)


def test_penetration_trend_rejects_selected_nonfinite_z():
    """Trend statistics (mean/std/ratio) must not hide a bad selected z."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_penetration_trend
    for bad in _bad_values():
        frame = _frame([[6, 1.0], [6, bad]])
        _reject(lambda: analyze_penetration_trend([frame], Z_COL, 5.0, o_type=6),
                'Penetration trend', 40)


def test_density_rejects_selected_nonfinite_z_even_outside_range():
    """np.histogram drops NaN, losing 1 of 2 atoms; Inf is out of range silently."""
    _util.require_numpy()
    from lammps_post.analysis import compute_density_profile
    for bad in _bad_values():
        frame = _frame([[6, 1.0], [6, bad]])
        _reject(lambda: compute_density_profile([frame], Z_COL, z_range=(0, 10),
                                                n_bins=10, species_type=6),
                'Density profile', 40)


def test_density_all_species_validates_every_atom():
    """With no species filter every atom is selected, whatever its type."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import compute_density_profile
    frame = _frame([[6, 1.0], [9, np.nan]])
    _reject(lambda: compute_density_profile([frame], Z_COL, z_range=(0, 10),
                                            n_bins=10), 'Density profile', 40)


def test_density_automatic_range_still_rejects():
    """The automatic-range path reads the same coordinates and must also raise."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import compute_density_profile
    frame = _frame([[6, 1.0], [6, np.nan]])
    _reject(lambda: compute_density_profile([frame], Z_COL, n_bins=10,
                                            species_type=6),
            'Density profile', 40)


def test_charge_region_rejects_selected_metal_with_nonfinite_z():
    """A metal whose slab membership is unknown cannot be dropped from a slab."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_charge_evolution, compute_or
    for bad in _bad_values():
        frame = _qframe([[4, .9, 3, 0], [7, .9, bad, 0]])
        for function, name in ((analyze_charge_evolution, 'Charge evolution'),
                               (compute_or, 'Oxidation rate')):
            _reject(lambda: function([frame], COL, fe_type={4, 7}, z_range=(2, 4)),
                    name, 40)


def test_charge_without_region_does_not_read_z():
    """Unrestricted charge statistics ignore a bad z, as before (no slab used)."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_charge_evolution, compute_or
    frame = _qframe([[4, .9, 3, 0], [4, .1, np.nan, 0]])
    ev = analyze_charge_evolution([frame], COL, fe_type=4)
    assert ev['n_total_fe'].tolist() == [2] and ev['n_oxidized'].tolist() == [1]
    assert compute_or([frame], COL, fe_type=4)['or'].tolist() == [.5]


def test_charge_z_rejects_selected_nonfinite_z():
    """Metal and count-only oxygen atoms with unknown z are both rejected."""
    _util.require_numpy()
    from lammps_post.analysis import analyze_charge_z
    for bad in _bad_values():
        for atom_type, label in ((4, 'metal'), (9, 'oxygen')):
            frame = _qframe([[4, .9, 2, 0], [atom_type, .5, bad, 0]])
            _reject(lambda: analyze_charge_z(frame, COL, z_bins=2, fe_type={4, 7},
                                             o_type=9), 'Charge z profile', 40)


def test_unrelated_species_with_nonfinite_z_is_harmless():
    """Only contributing atoms are validated; finite results stay unchanged."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import (analyze_charge_z, analyze_penetration,
                                      analyze_penetration_trend,
                                      compute_density_profile, compute_oar)
    frame = _frame([[6, 1.0], [6, 8.0], [3, np.nan], [5, np.inf]])
    oar = compute_oar([frame], Z_COL, 5.0, o_type=6)
    assert oar['n_total'].tolist() == [2] and oar['oar'].tolist() == [.5]
    pen = analyze_penetration([frame], Z_COL, 5.0, o_type=6)
    assert pen['n_total_o'].tolist() == [2] and pen['frac_adsorbed'].tolist() == [0.5]
    trend = analyze_penetration_trend([frame], Z_COL, 5.0, o_type=6)
    assert trend['adsorption_ratio_raw'].tolist() == [.5]
    dens = compute_density_profile([frame], Z_COL, z_range=(0, 10), n_bins=10,
                                   species_type=6)
    # Two atoms in a 10 x 10 cross-section: integral of rho dz equals 2/100.
    assert abs(dens['density'].sum() * 1.0 - 2 / 100) < 1e-12
    qframe = _qframe([[4, .9, 2, 0], [3, .1, np.nan, 0]])
    prof = analyze_charge_z(qframe, COL, z_bins=2, fe_type=4, o_type=9)
    assert prof['fe_count'].tolist() == [1, 0]


def test_empty_selection_and_finite_frames_unchanged():
    """No selected atoms stays valid (zero/NaN as documented); finite data exact."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import (analyze_penetration, compute_density_profile,
                                      compute_oar)
    frame = _frame([[3, np.nan]])
    assert compute_oar([frame], Z_COL, 5.0, o_type=6)['oar'].tolist() == [0]
    pen = analyze_penetration([frame], Z_COL, 5.0, o_type=6)
    assert pen['n_total_o'].tolist() == [0] and np.isnan(pen['o_min_z'][0])
    dens = compute_density_profile([frame], Z_COL, z_range=(0, 10), n_bins=10,
                                   species_type=6)
    assert dens['density'].tolist() == [0.0] * 10
    finite = _frame([[6, 1.0], [6, 8.0]])
    assert compute_oar([finite], Z_COL, 5.0, o_type=6)['n_absorbed'].tolist() == [1]


def test_later_frame_is_revalidated_with_its_own_timestep():
    """A bad atom appearing (or changing type) in frame 2 reports timestep 80."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import compute_oar
    first = _frame([[6, 1.0], [9, np.nan]])
    later = _frame([[6, 1.0], [6, np.nan]], step=80)
    _reject(lambda: compute_oar([first, later], Z_COL, 5.0, o_type=6), 'OAR', 80)


def test_literal_nan_dump_is_rejected_native_and_numpy_paths():
    """A real dump with a literal nan z reaches the analyses on both parsers."""
    _util.require_numpy()
    import os
    import tempfile
    from lammps_post import parsers
    from lammps_post.analysis import compute_density_profile, compute_oar
    text = ('ITEM: TIMESTEP\n40\nITEM: NUMBER OF ATOMS\n2\n'
            'ITEM: BOX BOUNDS pp pp pp\n0 10\n0 10\n0 10\n'
            'ITEM: ATOMS id type x y z\n'
            '1 6 1 1 1.0\n2 6 2 2 nan\n')
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'nan.dump')
        with open(path, 'w') as handle:
            handle.write(text)
        for use_native in (True, False):
            reader = parsers.DumpReader(path)
            if not use_native:
                reader._native = None
            frames = list(reader)
            _reject(lambda: compute_oar(frames, reader.col_idx, 5.0, o_type=6),
                    'OAR', 40)
            _reject(lambda: compute_density_profile(
                frames, reader.col_idx, z_range=(0, 10), n_bins=10,
                species_type=6), 'Density profile', 40)
