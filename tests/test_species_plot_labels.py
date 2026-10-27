"""Plot label/filename plumbing with a fake backend, not visual verification."""
import contextlib
import os
from unittest.mock import patch

import _util


class _Axes:
    def __init__(self):
        self.properties = {}

    def set(self, **kwargs):
        self.properties.update(kwargs)

    def set_title(self, title):
        self.properties['title'] = title

    def __getattr__(self, name):
        # No rendering is needed to inspect titles and the _save_fig path.
        return lambda *args, **kwargs: None


class _Backend:
    def __init__(self, axes):
        self.axes = axes

    def subplots(self, **kwargs):
        return object(), self.axes

    def tight_layout(self):
        pass


@contextlib.contextmanager
def _fake_backend():
    from lammps_post import plotting
    axes = _Axes()
    paths = []
    with patch.object(plotting, 'HAS_MPL', True), \
            patch.object(plotting, 'plt', _Backend(axes), create=True), \
            patch.object(plotting, '_save_fig', lambda fig, path, dpi: paths.append(path)):
        yield plotting, axes, paths


def test_msd_display_label_does_not_rename_output_file():
    _util.require_numpy()
    for raw, display in [('Fe', 'Fe (all spins)'), ('Fe_up', 'Fe↑'), ('Fe_down', 'Fe↓')]:
        data = {'time': [0, 1], 'msd': [0, 1], 'label': raw, 'display_label': display}
        with _fake_backend() as (plotting, axes, paths):
            plotting.plot_msd(data, raw, 'out')
        assert axes.properties['title'] == f'Mean Square Displacement — {display}'
        assert paths == [os.path.join('out', f'msd_{raw}.png')]


def test_rdf_display_label_does_not_rename_output_file():
    _util.require_numpy()
    import numpy as np
    for raw, display in [('Fe-O', 'Fe (all spins)-O'), ('Fe_up-O', 'Fe↑-O')]:
        data = {'r': np.array([1., 2.]), 'g': np.array([0., 1.]), 'n_frames': 1,
                'label': raw, 'display_label': display}
        with _fake_backend() as (plotting, axes, paths):
            plotting.plot_rdf(data, 'out')
        assert axes.properties['title'] == f'{display} RDF'
        assert paths == [os.path.join('out', f'rdf_{raw.replace("-", "_")}.png')]


def test_plot_labels_without_metadata_keep_legacy_behavior():
    _util.require_numpy()
    import numpy as np
    with _fake_backend() as (plotting, axes, paths):
        plotting.plot_msd({'time': [0, 1], 'msd': [0, 1]}, 'A', 'out')
    assert axes.properties['title'] == 'Mean Square Displacement — A'
    assert paths == [os.path.join('out', 'msd_A.png')]
    with _fake_backend() as (plotting, axes, paths):
        plotting.plot_rdf({'r': np.array([1., 2.]), 'g': np.array([0., 1.]),
                           'label': 'A-B', 'n_frames': 1}, 'out')
    assert axes.properties['title'] == 'A-B RDF'
    assert paths == [os.path.join('out', 'rdf_A_B.png')]
