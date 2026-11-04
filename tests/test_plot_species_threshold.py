"""REV-PLOT-2: exact plot species, full-range structure bins, recorded thresholds.

A fake backend records labels, guide lines and histogram inputs; nothing is
rendered or saved, so these checks cover label/selection logic, not pixels.
"""
import collections
import contextlib
import io
import os
from pathlib import Path
import shlex
import tempfile
from unittest.mock import patch

import _util


class _Axes:
    """Record the semantic plotting calls the REV-PLOT-2 checks inspect."""
    def __init__(self):
        """Start with empty property and call records; transAxes is an opaque token."""
        self.properties = {}
        self.calls = collections.defaultdict(list)
        self.transAxes = object()

    def set(self, **kwargs):
        """Capture bulk axis properties such as labels and titles."""
        self.properties.update(kwargs)

    def set_title(self, title):
        """Capture a directly set title."""
        self.properties['title'] = title

    def barh(self, centers, counts, **kwargs):
        """Record one type's bin centers and counts with its legend label."""
        self.calls['barh'].append((kwargs.get('label'), [float(c) for c in centers],
                                   [int(c) for c in counts]))

    def hist(self, values, **kwargs):
        """Record the values a histogram received."""
        self.calls['hist'].append([float(v) for v in values])

    def axhline(self, y, **kwargs):
        """Record a horizontal guide and its legend label."""
        self.calls['axhline'].append((round(float(y), 6), kwargs.get('label')))

    def text(self, x, y, text, **kwargs):
        """Record panel annotations."""
        self.calls['text'].append(text)

    def scatter(self, x, y, **kwargs):
        """Record a point group's label and size."""
        self.calls['scatter'].append((kwargs.get('label'), len(x)))

    def legend(self, *args, **kwargs):
        """Record legend requests so empty-legend calls are visible."""
        self.calls['legend'].append(True)

    def plot(self, *args, label=None, **kwargs):
        """Record line labels only."""
        self.calls['plot'].append(label)

    def __getattr__(self, name):
        """Ignore rendering-only methods outside this label-logic boundary."""
        return lambda *args, **kwargs: None


class _Figure:
    """Accept a figure title without rendering."""
    def suptitle(self, title):
        """Record the figure title."""
        self.title = title


class _Backend:
    """Hand out recording axes for any subplot grid the plot functions request."""
    def __init__(self):
        """Keep every axes object created, in creation order."""
        self.axes = []

    def subplots(self, nrows=1, ncols=1, **kwargs):
        """Return a single axes or a flat list, matching how the callers unpack."""
        made = [_Axes() for _ in range(nrows * ncols)]
        self.axes.extend(made)
        return _Figure(), (made[0] if len(made) == 1 else made)

    def tight_layout(self):
        """Accept layout requests."""
        pass


@contextlib.contextmanager
def _fake_backend():
    """Patch the backend and saving; yield the plotting module, backend, paths, stdout."""
    from lammps_post import plotting
    backend = _Backend()
    paths = []
    with patch.object(plotting, 'HAS_MPL', True), \
            patch.object(plotting, 'plt', backend, create=True), \
            patch.object(plotting, '_save_fig', lambda fig, path, dpi: paths.append(path)), \
            contextlib.redirect_stdout(io.StringIO()) as out:
        yield plotting, backend, paths, out


def test_resolve_plot_species_uses_exact_labels_only():
    """Co/NO never count as oxygen and no largest-type guess stands in for a species."""
    from lammps_post.plotting import resolve_plot_species
    assert resolve_plot_species({1: 'Fe', 2: 'Co', 3: 'O'})[:2] == ((3,), (1,))
    assert resolve_plot_species({1: 'Fe', 2: 'NO'})[:2] == ((), (1,))
    assert resolve_plot_species({1: 'A', 2: 'B'})[:2] == ((), ())
    # Canonical ACE labels resolve without a session map; 'Mn' alone does not.
    assert resolve_plot_species({1: 'Fe_up', 2: 'Fe_down', 3: 'O'})[:2] == ((3,), (1, 2))
    assert resolve_plot_species({1: 'Mn', 2: 'O'})[:2] == ((2,), ())
    # Legacy string-keyed element maps keep the sorted-element synthesized IDs.
    o, fe, labels = resolve_plot_species({'Fe': 'Fe_up', 'Mn': 'Fe_down', 'O': 'O'})
    assert (o, fe) == ((3,), (1, 2))
    assert labels == {1: 'Fe_up', 2: 'Fe_down', 3: 'O'}


def test_resolve_plot_species_prefers_explicit_selection():
    """An explicit Fe/O selection wins; names absent from it fall back to exact labels."""
    from lammps_post.plotting import resolve_plot_species
    types = {1: 'Fe_up', 2: 'Fe_down', 3: 'O', 4: 'Co'}
    species = {'Fe': frozenset({2}), 'O': frozenset({3, 4})}
    assert resolve_plot_species(types, species)[:2] == ((3, 4), (2,))
    assert resolve_plot_species(types, {'Fe': frozenset({1, 2})})[:2] == ((3,), (1, 2))
    assert resolve_plot_species({1: 'Fe', 2: 'Co'}, {})[:2] == ((), (1,))


def test_structure_histogram_covers_negative_z():
    """Atoms below z=0 enter lattice-aligned bins; non-negative data keep the legacy edges."""
    _util.require_numpy()
    import numpy as np
    atoms = np.array([[1, 1, 0, 0, -4.0], [2, 1, 0, 0, -1.0], [3, 2, 0, 0, 0.5], [4, 1, 0, 0, 10.0]])
    with _fake_backend() as (plotting, backend, paths, out):
        plotting.plot_structure(atoms, {1: 'Fe', 2: 'O'}, 'out')
    a1 = backend.axes[0]
    counted = sum(sum(counts) for _label, _centers, counts in a1.calls['barh'])
    assert counted == len(atoms)
    centers = a1.calls['barh'][0][1]
    assert centers[0] < 0
    assert abs(round((centers[0] - 2.87 / 2) / 2.87) - (centers[0] - 2.87 / 2) / 2.87) < 1e-9
    assert paths == [os.path.join('out', 'structure.png')]
    with _fake_backend() as (plotting, backend, paths, out):
        plotting.plot_structure(atoms[2:], {1: 'Fe', 2: 'O'}, 'out')
    assert abs(backend.axes[0].calls['barh'][0][1][0] - 2.87 / 2) < 1e-12


def test_structure_oxygen_and_surface_use_exact_species():
    """The O panel plots only O, and the surface guide is the highest Fe, not Co."""
    _util.require_numpy()
    import numpy as np
    atoms = np.array([[1, 1, 0, 0, 0.0], [2, 1, 0, 0, 2.87], [3, 1, 0, 0, 5.74],
                      [4, 2, 0, 0, 20.0], [5, 3, 0, 0, 8.0], [6, 3, 0, 0, 9.0]])
    with _fake_backend() as (plotting, backend, paths, out):
        plotting.plot_structure(atoms, {1: 'Fe', 2: 'Co', 3: 'O'}, 'out')
    a2 = backend.axes[1]
    assert a2.calls['hist'] == [[8.0, 9.0]]
    assert a2.calls['axhline'] == [(5.74, 'Fe surface (5.7 Å)')]
    assert a2.calls['legend'] == [True]
    assert a2.properties['title'] == 'O Atom z-Distribution'
    # 'NO' is not oxygen: the panel states the absence instead of drawing type 2.
    atoms = np.array([[1, 1, 0, 0, 0.0], [2, 1, 0, 0, 2.87], [3, 2, 0, 0, 5.0]])
    with _fake_backend() as (plotting, backend, paths, out):
        plotting.plot_structure(atoms, {1: 'Fe', 2: 'NO'}, 'out')
    a2 = backend.axes[1]
    assert a2.calls['hist'] == []
    assert a2.calls['text'] == ['no O species in the atom type map']
    assert 'No O species in the atom type map' in out.getvalue()
    assert a2.calls['axhline'] == [(2.87, 'Fe surface (2.9 Å)')]


def test_structure_without_fe_species_uses_supplied_surface_guide():
    """No Fe species means no 'Fe surface' claim: the given z_surface is a plain guide."""
    _util.require_numpy()
    import numpy as np
    atoms = np.array([[1, 1, 0, 0, 1.0], [2, 2, 0, 0, 2.0]])
    with _fake_backend() as (plotting, backend, paths, out):
        plotting.plot_structure(atoms, {1: 'A', 2: 'B'}, 'out', z_surface=12.0)
    a1, a2 = backend.axes[:2]
    assert a1.calls['axhline'] == [(12.0, None)]
    assert a2.calls['axhline'] == [(12.0, 'Surface guide (12.0 Å)')]
    assert [label for label, _c, _n in a1.calls['barh']] == ['A', 'B']
    with _fake_backend() as (plotting, backend, paths, out):
        plotting.plot_structure(atoms, {1: 'A', 2: 'B'}, 'out')
    a2 = backend.axes[1]
    assert a2.calls['axhline'] == [] and a2.calls['legend'] == []


def test_charge_plots_label_the_recorded_threshold():
    """Count axis, fraction title and OR title show q_thr; legacy caches keep 0.3."""
    _util.require_numpy()
    import numpy as np
    data = {'time': np.array([0., 1.]), 'avg': np.array([0.1, 0.2]), 'max': np.array([0.3, 0.4]),
            'n_oxidized': np.array([0, 1]), 'n_total_fe': np.array([2, 2]),
            'frac_oxidized': np.array([0., 0.5]), 'q_thr': 0.25}
    with _fake_backend() as (plotting, backend, paths, out):
        plotting.plot_charge_evolution(data, 'out')
    assert backend.axes[1].properties['ylabel'] == 'N(Fe, q > 0.25)'
    with _fake_backend() as (plotting, backend, paths, out):
        plotting.plot_charge_evolution(data, 'out', normalize=True)
    assert backend.axes[1].properties['title'] == 'Oxidized Fe Fraction (q > 0.25 e)'
    legacy = {k: v for k, v in data.items() if k != 'q_thr'}
    with _fake_backend() as (plotting, backend, paths, out):
        plotting.plot_charge_evolution(legacy, 'out')
    assert backend.axes[1].properties['ylabel'] == 'N(Fe, q > 0.3)'
    with _fake_backend() as (plotting, backend, paths, out):
        plotting.plot_or({'time': data['time'], 'or': data['frac_oxidized'], 'q_thr': 0.25}, 'out')
    assert backend.axes[0].properties['title'] == 'Fe Oxidation Rate (q > 0.25)'
    with _fake_backend() as (plotting, backend, paths, out):
        plotting.plot_or({'time': data['time'], 'or': data['frac_oxidized']}, 'out')
    assert backend.axes[0].properties['title'] == 'Fe Oxidation Rate (q > 0.3)'
    assert paths == [os.path.join('out', 'oxidation_rate.png')]


def test_charge_analyses_record_their_threshold():
    """Charge evolution and OR results carry the q_thr they were computed with."""
    _util.require_numpy()
    import numpy as np
    from lammps_post.analysis import analyze_charge_evolution, compute_or
    frame = {'timestep': 0, 'atoms': np.array([[1, 1, 0.1], [2, 1, 0.5], [3, 2, -0.6]])}
    col_idx = {'id': 0, 'type': 1, 'q': 2}
    result = analyze_charge_evolution([frame], col_idx, dt_fs=0.25, q_thr=0.25, fe_type=1)
    assert result['q_thr'] == 0.25 and list(result['n_oxidized']) == [1]
    result = compute_or([frame], col_idx, dt_fs=0.25, q_thr=0.45, fe_type=1)
    assert result['q_thr'] == 0.45 and list(result['or']) == [0.5]
    assert analyze_charge_evolution([frame], {'id': 0, 'type': 1}, dt_fs=0.25) is None


def _write_case(root):
    """Write a two-frame orthogonal dump with types 1-3 and an ACE 'Fe Mn O' input."""
    rows = ['1 1 1 1 10', '2 2 2 1 30', '3 3 3 1 50']
    text = ''
    for step in (0, 100):
        text += ('ITEM: TIMESTEP\n%d\nITEM: NUMBER OF ATOMS\n3\n'
                 'ITEM: BOX BOUNDS pp pp ff\n0 100\n0 100\n0 100\n'
                 'ITEM: ATOMS id type x y z\n%s\n' % (step, '\n'.join(rows)))
    (root / 'traj.dump').write_text(text)
    (root / 'run.in').write_text('units metal\nboundary p p f\natom_style atomic\n'
                                 'pair_style pace\npair_coeff * * test.yace Fe Mn O\n'
                                 'timestep 0.002\n')


def _quiet(call):
    """Run a shell call with captured stdout."""
    with contextlib.redirect_stdout(io.StringIO()) as out:
        result = call()
    return result, out.getvalue()


def test_shell_passes_session_species_to_structure_and_snapshot_plots():
    """The shell hands its species snapshot (ACE Fe spin union) to both plots."""
    _util.require_numpy()
    from lammps_post.shell import LammpsPostShell
    import lammps_post.shell as shell_module
    with tempfile.TemporaryDirectory(prefix='lk-plot2-') as temp:
        root = Path(temp)
        _write_case(root)
        shell = LammpsPostShell()
        shell.state.output_dir = str(root / 'plots')
        for kind, name in (('input', 'run.in'), ('dump', 'traj.dump')):
            _quiet(lambda: shell.do_load(f'{kind} {shlex.quote(str(root / name))}'))
        species = shell._plot_species()
        assert species['Fe'] == frozenset({1, 2}) and species['O'] == frozenset({3})
        with patch.object(shell_module, 'plot_structure') as plot:
            _quiet(lambda: shell._iplot_structure([], _batch=True))
        assert plot.call_args.kwargs['species']['Fe'] == frozenset({1, 2})
        with patch.object(shell_module, 'plot_snapshot') as plot:
            _quiet(lambda: shell._iplot_snapshot([], _batch=True))
        assert plot.call_args.kwargs['species']['Fe'] == frozenset({1, 2})


def test_snapshot_groups_exact_species_and_keeps_other_types():
    """Snapshots draw resolved Fe/O plus a grey 'other' group; no type-1/2 guess."""
    _util.require_numpy()
    import numpy as np
    box = np.array([[0., 100.], [0., 100.], [0., 100.]])
    atoms = np.array([[1, 1, 1, 1, 10.], [2, 2, 2, 1, 30.], [3, 3, 3, 1, 50.]])
    frames = [{'timestep': step, 'atoms': atoms, 'box': box} for step in (0, 100)]
    col_idx = {'id': 0, 'type': 1, 'x': 2, 'y': 3, 'z': 4}
    with _fake_backend() as (plotting, backend, paths, out):
        plotting.plot_snapshot(frames, col_idx, {1: 'Fe', 2: 'Co', 3: 'O'}, 'out', indices=[0])
    assert backend.axes[0].calls['scatter'] == [('Fe', 1), ('O', 1), ('other: Co', 1)]
    with _fake_backend() as (plotting, backend, paths, out):
        plotting.plot_snapshot(frames, col_idx, {1: 'A', 2: 'B', 3: 'C'}, 'out', indices=[0, 1])
    assert [ax.calls['scatter'] for ax in backend.axes] == [[('other: A, B, C', 3)]] * 2
    assert 'No Fe or O species in the atom type map' in out.getvalue()
    assert paths == [os.path.join('out', 'snapshots.png')]
