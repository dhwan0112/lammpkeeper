"""REV-IO-7: LAMMPS math in `parse_input` equal-style variables.

prep's own inputs compute step counts with LAMMPS math functions (`round`,
and since REV-PREP-7 `ternary` with comparisons). `parse_input` used to accept
arithmetic only, so `load input` of a prep-written ACE input failed with
"cannot resolve numeric expression 'round(500/0.00025)'". Expected values below
follow LAMMPS `src/variable.cpp` (checked 2026-11-01): `round` is MYROUND
(half up), `%` is C `fmod`, unary minus binds tighter than `^`, operators of
equal precedence associate left to right, and `min()`/`max()` are special
functions of one vector argument, not scalar math.
"""
import contextlib
import io
import os
import tempfile
import warnings

import _util  # noqa: F401  (path bootstrap)

from lammps_post.parsers import parse_input


def _parse(text):
    """Parse an input script written to a temporary file; return (config, path)."""
    fd, path = tempfile.mkstemp(suffix='.in')
    with os.fdopen(fd, 'w') as f:
        f.write(text)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            return parse_input(path), path
    finally:
        os.remove(path)


def _value(formula):
    """Resolve one equal-style formula the way parse_input stores it."""
    config, _ = _parse(f'units metal\nvariable x equal {formula}\n')
    return config['z_variables']['x']


def _rejects(formula, *needles):
    """An unsupported or ambiguous formula raises when substituted, naming the cause."""
    try:
        _parse(f'units metal\nvariable x equal {formula}\ntimestep ${{x}}\n')
    except ValueError as exc:
        for needle in needles:
            assert needle in str(exc), f'{needle!r} missing from {exc}'
        return
    raise AssertionError(f'{formula!r} was accepted')


def test_lammps_math_functions_use_lammps_semantics():
    """round is half-up (LAMMPS MYROUND), not Python's half-even; others exact."""
    expected = {
        'round(500/0.00025)': 2000000.0,
        'round(0.5)': 1.0, 'round(2.5)': 3.0, 'round(-2.5)': -2.0, 'round(-2.6)': -3.0,
        'floor(-1.5)': -2.0, 'ceil(-1.5)': -1.0, 'abs(-3)': 3.0,
        'ternary(1,2,3)': 2.0, 'ternary(0,2,3)': 3.0,
        'ternary(5-6>0,5-6,0)': 0.0,
        # Only the selected branch is evaluated, as in LAMMPS.
        'ternary(0,1/0,7)': 7.0,
    }
    for formula, value in expected.items():
        assert _value(formula) == value, (formula, _value(formula), value)


def test_comparisons_modulo_and_power_follow_lammps_rules():
    """Comparisons give 1/0, % is fmod, unary minus binds tighter than ^."""
    expected = {
        '2<3': 1.0, '3<=2': 0.0, '2>1': 1.0, '2>=3': 0.0, '2==2': 1.0, '2!=2': 0.0,
        '1+1>1': 1.0,
        '-7%3': -1.0, '7%-3': 1.0,
        '(-2)^2': 4.0, '-(2^2)': -4.0, '(2^3)^2': 64.0, '2^(3^2)': 512.0, '2*3^2': 18.0,
    }
    for formula, value in expected.items():
        assert _value(formula) == value, (formula, _value(formula), value)


def test_ambiguous_or_unsupported_formulas_raise_instead_of_guessing():
    """Forms where Python and LAMMPS disagree, and non-math functions, are rejected."""
    # Python reads -2^2 as -(2^2) and 2^3^2 as 2^(3^2); LAMMPS reads (-2)^2 and (2^3)^2.
    _rejects('-2^2', 'parenthes')
    _rejects('2^3^2', 'parenthes')
    # Python chains comparisons; LAMMPS evaluates them pairwise with == below <.
    _rejects('1<2<3', 'chained')
    # LAMMPS min()/max() take one vector argument; scalar min(a,b) aborts LAMMPS.
    _rejects('min(1,2)', 'min()', 'special function')
    _rejects('max(0,round(5))', 'max()', 'special function')
    _rejects('sqrt(4)', 'unsupported function', 'sqrt')
    _rejects('round(1,2)', 'round()', 'argument')
    _rejects('ternary(1,2)', 'ternary()', 'argument')
    _rejects('round(x=1)', 'argument')
    _rejects('1/0')
    _rejects('5%0')


def test_prep_written_inputs_load_with_explicit_timestep():
    """Real prep ACE/ReaxFF output loads in post with explicit dt and its step counts."""
    _util.require_numpy()
    from lammps_pre.writers import get_filenames, write_all
    from test_audit_prep import _build, _state
    expected_dt = {'ace': 0.25, 'reaxff2010': 0.25, 'reaxff2015': 0.25}
    for ff, dt_fs in expected_dt.items():
        s = _state()
        s.set_ff(ff)
        build = _build(s)
        with tempfile.TemporaryDirectory(prefix='lk io7 ') as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                write_all(build, s, tmp)
            path = os.path.join(tmp, get_filenames(s)['input'])
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                config = parse_input(path)
        md = config['metadata']
        assert config['dt_fs'] == dt_fs and md.dt_fs.status == 'explicit', (ff, md.dt_fs)
        assert md.ff_family.value == ('ace' if ff == 'ace' else 'reaxff'), ff
        steps = config['z_variables']
        ox = round(s.get_ox_ps() * (1 if ff == 'ace' else 1000) / s.ff['dt'])
        assert steps['ox_steps'] == ox, (ff, steps)
        if ff == 'ace':
            dense = min(ox, round(s.dump_dense_ps / s.ff['dt']))
            assert (steps['ox_dense'], steps['ox_remain']) == (dense, ox - dense), steps
