"""AUDIT-20261027: independent crystal geometry and real Agg artist checks.

No pytest/ASE dependency; plotting checks skip visibly without matplotlib.
"""
from collections import Counter
from contextlib import contextmanager
import itertools
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import warnings

import _util


def test_magnetite_stoichiometry_and_periodic_coordination():
    _util.require_numpy()
    import numpy as np
    from lammps_post.references import CRYSTAL_DB

    crystal = CRYSTAL_DB['Fe3O4']
    assert Counter(e for e, _ in crystal['atoms']) == {'Fe': 24, 'O': 32}
    cell = crystal['cell']
    fe = np.array([p for e, p in crystal['atoms'] if e == 'Fe']) @ cell
    oxygen = np.array([p for e, p in crystal['atoms'] if e == 'O']) @ cell
    # Independent direct image enumeration, not production symmetry or MIC.
    images = np.concatenate([oxygen + np.array(s) @ cell
                             for s in itertools.product((-1, 0, 1), repeat=3)])
    distances = np.linalg.norm(fe[:, None, :] - images[None, :, :], axis=2)
    assert Counter(np.sum(distances < 2.3, axis=1)) == {4: 8, 6: 16}
    # Fd-3m origin 2, u=.2549: independent analytic tetrahedral and
    # octahedral Fe-O bond lengths; these distinguish a count-only repair.
    tetra = 8.396 * np.sqrt(3) * (.2549 - .125)
    octa = 8.396 * np.sqrt((.5 - .2549)**2 + 2 * (.2549 - .25)**2)
    np.testing.assert_allclose(np.sort(distances.min(axis=1)),
                               sorted([tetra] * 8 + [octa] * 16), atol=1e-12)
    # No coincident atoms even across periodic cell boundaries.
    frac = np.array([p for _, p in crystal['atoms']])
    delta = frac[:, None] - frac[None, :]
    delta -= np.round(delta)
    pair_dist = np.linalg.norm(delta @ cell, axis=2)
    np.fill_diagonal(pair_dist, np.inf)
    assert pair_dist.min() > 1.8


_CIF = '''data_test
_cell_length_a 2.8665
_cell_length_b 2.8665
_cell_length_c 2.8665
{symmetry}
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Fe1 Fe 0 0 0
'''


def test_cif_missing_symmetry_requires_established_p1():
    _util.require_numpy()
    from lammps_post.references import parse_cif
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'structure.cif'
        for declaration in ("_space_group_IT_number 229\n_space_group_name_H-M_alt 'I m -3 m'",
                            "_symmetry_space_group_name_H-M 'I m -3 m'", '',
                            "_space_group_IT_number 229\n_space_group_name_H-M_alt 'P 1'"):
            path.write_text(_CIF.format(symmetry=declaration))
            try:
                parse_cif(str(path))
            except ValueError as exc:
                assert 'symmetry' in str(exc).lower()
            else:
                raise AssertionError('CIF without explicit symmetry or established P1 accepted')
        for declaration in ('_space_group_IT_number 1',
                            "_symmetry_space_group_name_H-M 'P 1'",
                            "_space_group_name_H-M_alt 'P1'"):
            path.write_text(_CIF.format(symmetry=declaration))
            assert len(parse_cif(str(path))['atoms']) == 1


def test_cif_explicit_centering_is_expanded():
    _util.require_numpy()
    import numpy as np
    from lammps_post.references import parse_cif
    symmetry = """_space_group_IT_number 229
loop_
_space_group_symop_operation_xyz
'x,y,z'
'x+1/2,y+1/2,z+1/2'
"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'structure.cif'
        path.write_text(_CIF.format(symmetry=symmetry))
        crystal = parse_cif(str(path))
    assert len(crystal['atoms']) == 2
    np.testing.assert_allclose(crystal['atoms'][1][1], [.5] * 3)


@contextmanager
def _capture_plots():
    _util.require_numpy()
    from lammps_post import plotting as p
    _util.require(p.HAS_MPL, 'matplotlib not installed (real Agg artist checks)')
    captured = {}

    def save(fig, path, dpi):
        fig.canvas.draw()  # Actual Agg renderer, not mocked axes.
        captured[os.path.basename(path)] = fig

    with patch.object(p, '_save_fig', save):
        try:
            yield p, captured
        finally:
            for fig in captured.values():
                p.plt.close(fig)


def _thermo_data(length_z=100., native_pressure=1.):
    import numpy as np
    n = 12
    return dict(step=np.arange(n), time_ps=np.arange(n, dtype=float),
                temp=np.full(n, 300.), pe=np.full(n, -1.), etotal=np.full(n, -.5),
                press=np.full(n, native_pressure), pxx=np.full(n, native_pressure),
                pyy=np.full(n, native_pressure), pzz=np.full(n, native_pressure),
                vol=np.full(n, 100. * length_z), lx=np.full(n, 10.),
                ly=np.full(n, 10.), lz=np.full(n, length_z))


def test_real_and_metal_pressure_artists_have_correct_units():
    _util.require_numpy()
    import numpy as np
    with _capture_plots() as (p, captured):
        for name, function, index, filename in (
                ('thermo', p.plot_thermo, 3, 'thermo.png'),
                ('thermostat', p.plot_thermostat_summary, 1, 'thermostat_summary.png'),
                ('pressure', p.plot_pressure, 1, 'pressure_analysis.png')):
            for native, bar_scale in (('metal', 1.), ('real', 1.01325)):
                for display, scale in (('bar', 1.), ('gpa', 1e-4)):
                    function(_thermo_data(), 'unused', pressure_unit=display,
                             unit_system=native)
                    fig = captured[filename]
                    ax = fig.axes[index]
                    np.testing.assert_allclose(ax.lines[0].get_ydata(),
                                               bar_scale * scale, rtol=1e-14,
                                               err_msg=f'{name}/{native}/{display}')
                    assert ('bar' if display == 'bar' else 'GPa') in ax.get_ylabel()
                    p.plt.close(fig)


def test_slab_pressure_uses_per_frame_lz_over_thickness():
    _util.require_numpy()
    import numpy as np
    with _capture_plots() as (p, captured):
        for length in (100., 200.):
            p.plot_pressure(_thermo_data(length, 10.), 'unused', slab_z_range=(0., 10.))
            fig = captured['pressure_analysis.png']
            ax = fig.axes[2]
            np.testing.assert_allclose(ax.lines[0].get_ydata(), length)
            assert 'rescaled' in ax.get_title().lower()
            assert any('assum' in text.get_text().lower() for text in ax.texts)
            p.plt.close(fig)
        data = _thermo_data(native_pressure=10.)
        data['lz'] = np.linspace(100., 200., 12)
        data['vol'] = data['lz'] * 100.
        p.plot_pressure(data, 'unused', slab_z_range=(0., 10.))
        np.testing.assert_allclose(captured['pressure_analysis.png'].axes[2].lines[0].get_ydata(),
                                   data['lz'])


def test_slab_pressure_missing_or_invalid_geometry_is_visibly_uncorrected():
    _util.require_numpy()
    import numpy as np
    with _capture_plots() as (p, captured):
        for bad_lz in (None, np.ones(11), np.full(12, np.nan), np.full(12, 5.)):
            data = _thermo_data(native_pressure=10.)
            if bad_lz is None:
                del data['lz']
            else:
                data['lz'] = bad_lz
            with warnings.catch_warnings(record=True) as seen:
                warnings.simplefilter('always')
                p.plot_pressure(data, 'unused', slab_z_range=(0., 10.))
            assert any('uncorrected' in str(w.message).lower() for w in seen)
            fig = captured['pressure_analysis.png']
            assert 'uncorrected' in fig.axes[2].get_title().lower()
            np.testing.assert_allclose(fig.axes[2].lines[0].get_ydata(), 10.)
            p.plt.close(fig)
        data = _thermo_data(native_pressure=10.)
        for key in ('pxx', 'pyy', 'pzz'):
            del data[key]
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter('always')
            p.plot_pressure(data, 'unused', slab_z_range=(0., 10.))
        assert any('uncorrected' in str(w.message).lower() for w in seen)
        fig = captured['pressure_analysis.png']
        assert 'uncorrected' in fig.axes[1].get_title().lower()
        np.testing.assert_allclose(fig.axes[1].lines[0].get_ydata(), 10.)


def _profile_data(n_o, crossing_times, o_z=None):
    import numpy as np
    if o_z is None:
        o_z = np.full((3, n_o), 12.)
    return dict(time=np.arange(len(o_z), dtype=float), o_z_traj=o_z,
                surface_z=np.full(len(o_z), 10.), min_o_z=np.full(len(o_z), 8.),
                cross_times=np.asarray(crossing_times, dtype=float), n_o=n_o)


def test_t50_requires_half_initial_population_and_correct_event_index():
    _util.require_numpy()
    import numpy as np
    with _capture_plots() as (p, captured):
        for population, times, expected in ((100, [1., 2.], None),
                                             (100, np.arange(1, 101), 50.),
                                             (5, np.arange(1, 6), 3.),
                                             (1, [1.], 1.)):
            p.plot_penetration_profile(_profile_data(population, times), 'unused',
                                       n_snapshots=2)
            ax = captured['o_adsorption_timeline.png'].axes[0]
            annotations = [text for text in ax.texts if 't₅₀' in text.get_text()]
            if expected is None:
                assert not annotations, '2/100 uptake cannot establish population t50'
            else:
                assert len(annotations) == 1
                assert annotations[0].get_position()[0] == expected
                np.testing.assert_allclose(ax.lines[1].get_ydata(), np.ceil(population / 2))
            for fig in captured.values():
                p.plt.close(fig)


def test_profile_union_nan_trajectories_and_present_population_metrics():
    _util.require_numpy()
    import numpy as np
    # Initial n_o=2, but the ID union has three columns. Empty frames must
    # remain gaps, never become fictitious zero-height/zero-uptake samples.
    o_z = np.array([[12., 8., np.nan], [np.nan, 8., 12.],
                    [np.nan, np.nan, np.nan], [np.nan, 8., np.nan]])
    with _capture_plots() as (p, captured):
        with warnings.catch_warnings(record=True) as seen:
            warnings.simplefilter('always')
            p.plot_penetration_profile(_profile_data(2, [0.], o_z), 'unused', n_snapshots=2)
        assert not any('empty slice' in str(w.message).lower() for w in seen)
        spaghetti = captured['o_trajectories.png'].axes[0]
        assert len(spaghetti.lines) == 5  # Three IDs + surface + minimum.
        np.testing.assert_allclose(spaghetti.lines[2].get_ydata(), o_z[:, 2], equal_nan=True)
        metrics = captured['o_penetration_metrics.png'].axes
        np.testing.assert_allclose(metrics[0].lines[0].get_ydata(), [10., 10., np.nan, 8.],
                                   equal_nan=True)
        np.testing.assert_allclose(metrics[1].lines[0].get_ydata(), [50., 50., np.nan, 100.],
                                   equal_nan=True)


def test_profile_later_arrivals_cannot_establish_initial_cohort_t50():
    _util.require_numpy()
    import numpy as np
    o_z = np.array([[12., 12., 12., 12., np.nan, np.nan, np.nan],
                    [8., 12., 12., 12., 8., 8., 8.],
                    [8., 12., 12., 12., 8., 8., 8.]])
    data = _profile_data(7, [1.] * 4, o_z)
    data['n_initial_o'] = 4
    with _capture_plots() as (p, captured):
        p.plot_penetration_profile(data, 'unused', n_snapshots=2)
        ax = captured['o_adsorption_timeline.png'].axes[0]
        assert '1/4 initial O' in ax.get_title()
        assert not any('t₅₀' in text.get_text() for text in ax.texts)
        np.testing.assert_allclose(ax.lines[0].get_ydata(), [1.])


def test_normalized_spin_legend_states_different_denominators():
    _util.require_numpy()
    import numpy as np
    data = dict(time=np.arange(3), up_fraction=np.full(3, .25),
                down_fraction=np.full(3, .75), o_fraction=np.full(3, .5))
    with _capture_plots() as (p, captured):
        p.plot_spin(data, 'unused', normalize=True)
        ax = captured['spin_evolution.png'].axes[0]
        assert 'total' not in ax.get_ylabel().lower()
        assert [line.get_label() for line in ax.lines] == [
            'Fe up / all Fe', 'Fe down / all Fe', 'O / all atoms']


def test_pressure_unit_validation_and_slab_metadata_consistency():
    _util.require_numpy()
    import numpy as np
    from lammps_post import plotting as p
    for native, display in (('lj', 'bar'), ('real', 'atm')):
        try:
            p._pressure_scale(native, display)
        except ValueError:
            pass
        else:
            raise AssertionError('Unsupported pressure units accepted')
    data = _thermo_data()
    data['vol'] *= 2
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter('always')
        assert p._slab_volume_scale(data, (0., 10.), 12) is None
    assert any('uncorrected' in str(w.message) for w in seen)
    # Height suffices for the stated z-aligned same-cross-section convention.
    np.testing.assert_allclose(p._slab_volume_scale({'lz': np.full(12, 100.)},
                                                   (0., 10.), 12), 10.)
