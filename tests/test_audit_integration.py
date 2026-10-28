"""Cross-module audit contracts: parser timeline and CLI plotting failures.

Synthetic log/dump text isolates metadata routing, not a real LAMMPS run.
Captured Agg artists check values; mocked pressure dispatch checks arguments
only, and simulated renderer absence checks failure routing, not installation.
"""
from pathlib import Path
import tempfile
from unittest.mock import patch
import warnings

import _util


def test_parsed_md_timeline_not_absolute_optimizer_or_reset_steps_is_plotted():
    """Rendered x data use accumulated MD steps across resets and minimization."""
    import numpy as np
    from lammps_post.parsers import parse_log
    from test_audit_references_plots import _capture_plots
    block = ('Step Temp PotEng Press Pxx Pyy Pzz\n'
             '0 300 -10 1 1 1 1\n10 301 -11 1 1 1 1\nLoop time of 1 on 1 procs\n')
    cases = [
        'run 10\n' + block + 'reset_timestep 0\nrun 10\n' + block,
        'run 10\n' + block +
        'minimize 0 1e-8 100 1000\nStep Temp PotEng Press Pxx Pyy Pzz\n'
        '10 301 -11 1 1 1 1\n12 301 -18 1 1 1 1\nLoop time of 1 on 1 procs\n'
        'run 10\nStep Temp PotEng Press Pxx Pyy Pzz\n'
        '12 302 -18 1 1 1 1\n22 303 -17 1 1 1 1\nLoop time of 1 on 1 procs\n',
    ]
    with tempfile.TemporaryDirectory() as tmp, _capture_plots() as (p, figures):
        path = Path(tmp) / 'log.lammps'
        for text in cases:
            path.write_text(text)
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', RuntimeWarning)
                log = parse_log(path)
            for function, filename in ((p.plot_thermo, 'thermo.png'),
                                       (p.plot_thermostat_summary, 'thermostat_summary.png'),
                                       (p.plot_pressure, 'pressure_analysis.png')):
                function(log, tmp, dt_fs=2.)
                fig = figures[filename]
                # Two ten-step MD segments at 2 fs span 0.04 ps; reset or
                # optimizer counters consume no extra physical MD duration.
                np.testing.assert_allclose(fig.axes[0].lines[0].get_xdata(), [0, .02, .02, .04])
                p.plt.close(fig)


def test_optimizer_only_thermo_cannot_be_labeled_elapsed_md_time():
    """Optimizer iterations cannot be converted into a physical MD time axis."""
    from lammps_post import plotting as p
    _util.require(p.HAS_MPL, 'matplotlib not installed (real Agg artist checks)')
    from lammps_post.parsers import parse_log
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'log.lammps'
        path.write_text('minimize 0 1e-8 100 1000\nStep Temp PotEng Press\n'
                        '0 300 -10 1\n10 0 -20 1\nLoop time of 1 on 1 procs\n')
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            log = parse_log(path)
        for function in (p.plot_thermo, p.plot_thermostat_summary, p.plot_pressure):
            try:
                function(log, tmp, dt_fs=1.)
            except ValueError as exc:
                assert 'MD' in str(exc)
            else:
                raise AssertionError('optimizer iterations displayed as elapsed MD time')


def test_duplicate_step_counters_do_not_infer_ambiguous_slab_heights():
    """Repeated step labels cannot safely join log samples to run-specific boxes.

    The renderer is mocked: this asserts that ambiguous Lz is not synthesized,
    not what a subsequent pressure figure or warning actually looks like.
    """
    import numpy as np
    from lammps_post import shell as sm
    from test_audit_workflow import _dump, _shell, _load, _quiet
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        path = root / 'traj.dump'
        _dump(path)
        path.write_text(path.read_text() * 2)  # Concatenated runs reset their step counter.
        shell = _shell(root)
        _load(shell, 'dump', path)
        shell.state.log_data = dict(step=np.array([0, 100, 0, 100]), press=np.ones(4))
        shell.state.plot_recipes['pressure'] = {'slab_z_range': (0, 50)}
        with patch.object(sm, 'plot_pressure') as plot:
            _quiet(lambda: shell._iplot_pressure([], _batch=True))
            assert 'lz' not in plot.call_args.args[0], 'duplicate steps cannot identify run-specific heights'


def test_log_only_and_mixed_source_plots_use_explicit_log_units_and_timestep():
    """An unrelated dump must not override real-unit log pressure or time scaling."""
    import numpy as np
    from test_audit_references_plots import _capture_plots
    from test_audit_workflow import _dump, _shell, _load, _quiet
    with tempfile.TemporaryDirectory() as tmp, _capture_plots() as (p, figures):
        root = Path(tmp)
        path = root / 'real.log'
        path.write_text('units real\ntimestep 2\nrun 11\n'
                        'Step Temp PotEng Press Pxx Pyy Pzz\n' +
                        ''.join(f'{i} 300 -1 1 1 1 1\n' for i in range(12)) +
                        'Loop time of 1 on 1 procs\n')
        shell = _shell(root)
        _load(shell, 'log', path)
        for load_dump in (False, True):
            if load_dump:
                dump = root / 'unrelated_metal.dump'
                _dump(dump)
                _load(shell, 'dump', dump)
            for name, filename, pressure_index in (
                    ('thermo', 'thermo.png', 3),
                    ('thermostat', 'thermostat_summary.png', 1),
                    ('pressure', 'pressure_analysis.png', 0)):
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', RuntimeWarning)
                    _quiet(lambda: getattr(shell, '_iplot_' + name)([], _batch=True))
                fig = figures[filename]
                pressure = fig.axes[pressure_index].lines[0]
                # In real units pressure is atm: 1 atm = 1.01325 bar.
                # The log's 2 fs timestep gives 0.002 ps per step.
                np.testing.assert_allclose(pressure.get_ydata(), 1.01325)
                np.testing.assert_allclose(pressure.get_xdata(), np.arange(12) * .002)
                p.plt.close(fig)


def test_unknown_or_conflicting_log_metadata_is_not_silently_interpreted():
    """Reject unconfirmed/conflicting metadata before assigning a thermo timeline.

    Helper/parser rejection is tested directly; this case does not render an
    artist or establish behavior for variable-timestep integration histories.
    """
    import numpy as np
    from lammps_post.shell import LammpsPostShell
    from lammps_post.parsers import parse_log
    shell = LammpsPostShell()
    shell.state.log_data = {'step': np.array([0, 1]), 'press': np.ones(2)}
    for config, log_metadata in ((None, {}),
                                  ({'units': 'metal'}, {'unit_system': 'real', 'dt_fs': 2.}),
                                  ({'units': 'real', 'dt_fs': 3.}, {'unit_system': 'real', 'dt_fs': 2.})):
        shell.state.input_config = config
        shell.state.log_data.update(log_metadata)
        try:
            shell._thermo_plot_metadata()
        except ValueError:
            pass
        else:
            raise AssertionError('unconfirmed/conflicting log metadata accepted')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'log.lammps'
        table = 'Step Temp Press\n0 300 1\n1 300 1\nLoop time of 1 on 1 procs\n'
        path.write_text('units metal\ntimestep 0.002\n' + table)
        log = parse_log(path)
        assert log['unit_system'] == 'metal' and log['dt_fs'] == 2.
        for prefix in ('units real\nunits metal\n',
                       'units real\ntimestep 1\ntimestep 2\n'):
            path.write_text(prefix + table)
            try:
                parse_log(path)
            except ValueError:
                pass
            else:
                raise AssertionError('mixed-unit/timestep histories accepted as one timeline')


def test_requested_cli_plot_without_matplotlib_fails_instead_of_success_without_output():
    """A requested image without a renderer must produce a nonzero CLI failure."""
    from lammps_post import plotting as p
    from lammps_post.cli import main
    from test_audit_workflow import _dump, _quiet
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'traj.dump'
        _dump(path)
        # Simulate dependency absence deliberately; this checks failure routing,
        # whereas the artist tests exercise real Agg figures when available.
        with patch.object(p, 'HAS_MPL', False):
            try:
                _quiet(lambda: main(['--dump', str(path), '--plot', 'msd', '--output', tmp]))
            except SystemExit as exc:
                assert exc.code != 0
            else:
                raise AssertionError('requested plot silently succeeded without matplotlib')
