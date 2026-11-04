"""C-1: interactive z-range prompts parse signed ranges and fail loudly on typos.

Before REV-UI-6 the slab and z-focus prompts split on the first '-' under
``except ValueError: pass``: a negative lower bound, ``0:80`` or ``0 80`` was
dropped without a message and the pressure recipe saved ``slab_z_range None``.
"""
import shlex
import tempfile
from pathlib import Path
from unittest.mock import PropertyMock, patch

import _util  # noqa: F401 (repository path bootstrap)
import numpy as np

import lammps_post.shell as shell_module
from lammps_post.shell import LammpsPostShell, _fmt_z_range, _parse_z_range
from test_audit_workflow import _dump, _quiet, _shell


def test_parse_z_range_accepts_signed_and_alternate_separators():
    """Every advertised separator works and negative bounds keep their sign."""
    cases = {'0-80': (0, 80), '-5-80': (-5, 80), '-5.0-80.0': (-5, 80),
             '0:80': (0, 80), '-10:30': (-10, 30), '0,80': (0, 80),
             '0 80': (0, 80), ' 0 - 30 ': (0, 30), '-5.0--1.0': (-5, -1),
             '1e1:2e1': (10, 20)}
    for text, want in cases.items():
        assert _parse_z_range(text, 'z') == want, text


def test_parse_z_range_rejects_garbage_reversed_and_nonfinite():
    """Unparsable, single-value, reversed or nonfinite answers raise ValueError."""
    for text in ('abc', '5', '0:80:9', 'nan:1', '1:inf', '80-0', '0 -5', '3:3'):
        try:
            _parse_z_range(text, 'Slab z-range')
        except ValueError as exc:
            assert 'Slab z-range' in str(exc), exc
        else:
            raise AssertionError(f'{text!r} parsed')


def test_fmt_z_range_round_trips_narrow_and_signed_ranges():
    """Prompt defaults never round a valid range into one the parser rejects."""
    for lo, hi in ((0, 0.3), (-5, 80), (12.04, 12.06), (-3.25, -1.5)):
        assert _parse_z_range(_fmt_z_range(lo, hi), 'z') == (lo, hi)


def test_pressure_default_from_small_or_negative_surface():
    """A small surface gives a parseable default; one at or below 0 offers bulk."""
    with tempfile.TemporaryDirectory(prefix='lk-zrange-') as temp:
        shell = _pressure_shell(Path(temp))
        for surface, want_default, want_slab in ((0.3, '0:0.3', (0, 0.3)),
                                                 (-3.0, 'none', None)):
            shell.state.plot_recipes.pop('pressure', None)
            shell.state.surface_z = surface
            seen = []
            plot = _run_pressure(shell, lambda prompt, default: seen.append(default) or default)
            assert seen == [want_default], (surface, seen)
            assert plot.call_args.kwargs['slab_z_range'] == want_slab, surface


def _pressure_shell(root):
    _dump(root / 'traj.dump')
    shell = _shell(root)
    _quiet(lambda: shell.do_load(f"dump {shlex.quote(str(root / 'traj.dump'))}"))
    shell.state.log_data = {'step': np.array([0]), 'press': np.array([1.])}
    shell.state.ff_info['unit_system'] = 'real'
    return shell


def _interactive(answer):
    """Patch the shell into prompting mode; ``answer`` maps (prompt, default) to input."""
    return (patch.object(LammpsPostShell, '_no_prompt', new_callable=PropertyMock,
                         return_value=False),
            patch.object(LammpsPostShell, '_ask',
                         lambda self, prompt, default=None: answer(prompt, default)))


def _run_pressure(shell, answer):
    p1, p2 = _interactive(answer)
    with p1, p2, patch.object(shell_module, 'plot_pressure') as plot:
        _quiet(lambda: shell._iplot_pressure([]))
    return plot


def test_pressure_slab_prompt_parses_negative_and_colon_ranges():
    """'-5-80' and '0:80' reach the backend and the saved recipe."""
    with tempfile.TemporaryDirectory(prefix='lk-zrange-') as temp:
        shell = _pressure_shell(Path(temp))
        for text, want in (('-5-80', (-5, 80)), ('0:80', (0, 80)), ('0 80', (0, 80))):
            plot = _run_pressure(shell, lambda prompt, default, t=text: t)
            assert plot.call_args.kwargs['slab_z_range'] == want, text
            assert shell.state.plot_recipes['pressure']['slab_z_range'] == want


def test_pressure_slab_negative_default_round_trips():
    """A saved negative lower bound is offered as a default that parses back."""
    with tempfile.TemporaryDirectory(prefix='lk-zrange-') as temp:
        shell = _pressure_shell(Path(temp))
        shell.state.plot_recipes['pressure'] = {'slab_z_range': (-5.0, 80.0)}
        seen = []
        plot = _run_pressure(shell, lambda prompt, default: seen.append(default) or default)
        assert seen == ['-5:80'], seen
        assert plot.call_args.kwargs['slab_z_range'] == (-5.0, 80.0)


def test_pressure_slab_typo_raises_without_plot_or_recipe():
    """A malformed range fails before plotting and keeps the previous recipe."""
    with tempfile.TemporaryDirectory(prefix='lk-zrange-') as temp:
        shell = _pressure_shell(Path(temp))
        shell.state.plot_recipes['pressure'] = {'slab_z_range': (0.0, 50.0)}
        try:
            _run_pressure(shell, lambda prompt, default: '0..80')
        except ValueError as exc:
            assert 'Slab z-range' in str(exc), exc
        else:
            raise AssertionError('typo accepted')
        assert shell.state.plot_recipes['pressure'] == {'slab_z_range': (0.0, 50.0)}


def test_pressure_slab_none_keeps_bulk():
    """'none' still selects the bulk (uncorrected) pressure."""
    with tempfile.TemporaryDirectory(prefix='lk-zrange-') as temp:
        shell = _pressure_shell(Path(temp))
        plot = _run_pressure(shell, lambda prompt, default: 'none')
        assert plot.call_args.kwargs['slab_z_range'] is None


def test_snapshot_and_structure_z_focus_accept_negative_lower_bound():
    """Snapshot/structure z-focus prompts parse '-10:30' and reject typos."""
    with tempfile.TemporaryDirectory(prefix='lk-zrange-') as temp:
        shell = _pressure_shell(Path(temp))
        for method, backend in (('_iplot_snapshot', 'plot_snapshot'),
                                ('_iplot_structure', 'plot_structure')):
            def answer(prompt, default):
                return '-10:30' if 'focus' in prompt else default
            p1, p2 = _interactive(answer)
            with p1, p2, patch.object(shell_module, backend) as plot:
                _quiet(lambda: getattr(shell, method)([]))
            assert plot.call_args.kwargs['z_focus'] == (-10, 30), method

            def bad(prompt, default):
                return '0..30' if 'focus' in prompt else default
            p1, p2 = _interactive(bad)
            with p1, p2, patch.object(shell_module, backend) as plot:
                try:
                    _quiet(lambda: getattr(shell, method)([]))
                except ValueError as exc:
                    assert 'z-axis focus range' in str(exc), exc
                else:
                    raise AssertionError(f'{method} accepted a typo')
            assert not plot.called, method
