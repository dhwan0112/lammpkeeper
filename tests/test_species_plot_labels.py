"""Plot label/filename plumbing with a fake backend, not visual verification."""
import contextlib
import os
from unittest.mock import patch

import _util


class _Axes:
    """Record semantic labels without requiring Matplotlib or visual comparison."""
    def __init__(self):
        """Start each plot with an independent title/property record."""
        self.properties = {}

    def set(self, **kwargs):
        """Capture axis properties that the plotting API sets in bulk."""
        self.properties.update(kwargs)

    def set_title(self, title):
        """Capture the human-facing title independently of the output filename."""
        self.properties['title'] = title

    def __getattr__(self, name):
        """Ignore rendering-only methods outside this label-plumbing test boundary."""
        # No rendering is needed to inspect titles and the _save_fig path.
        return lambda *args, **kwargs: None


class _Backend:
    """Supply only the backend operations needed to reach label and save logic."""
    def __init__(self, axes):
        """Reuse the provided recorder so assertions can inspect plotting calls."""
        self.axes = axes

    def subplots(self, **kwargs):
        """Return an opaque figure and recording axes without creating a GUI."""
        return object(), self.axes

    def tight_layout(self):
        """Accept layout requests without claiming to validate rendered geometry."""
        pass


@contextlib.contextmanager
def _fake_backend():
    """Patch rendering and saving while retaining production label/path decisions."""
    from lammps_post import plotting
    axes = _Axes()
    paths = []
    # Intercept saves so label checks neither write images nor require a GUI backend.
    with patch.object(plotting, 'HAS_MPL', True), \
            patch.object(plotting, 'plt', _Backend(axes), create=True), \
            patch.object(plotting, '_save_fig', lambda fig, path, dpi: paths.append(path)):
        yield plotting, axes, paths


def test_msd_display_label_does_not_rename_output_file():
    """Friendly spin titles must not break stable raw-label MSD filenames."""
    _util.require_numpy()
    for raw, display in [('Fe', 'Fe (all spins)'), ('Fe_up', 'Fe↑'), ('Fe_down', 'Fe↓')]:
        data = {'time': [0, 1], 'msd': [0, 1], 'label': raw, 'display_label': display}
        with _fake_backend() as (plotting, axes, paths):
            plotting.plot_msd(data, raw, 'out')
        assert axes.properties['title'] == f'Mean Square Displacement — {display}'
        assert paths == [os.path.join('out', f'msd_{raw}.png')]


def test_rdf_display_label_does_not_rename_output_file():
    """Friendly pair titles must not change the raw pair's normalized filename."""
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
    """Older result dictionaries retain their original titles and file paths."""
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
