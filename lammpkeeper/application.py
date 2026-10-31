"""Callable EXEC-1 thermo summary; no shell, session, plotting or history state.

Direct calls summarize the supplied loaded snapshot and never reread its source.
The file wrapper loads a fresh snapshot with the existing parser. Its stat check
detects ordinary concurrent edits/replacements, not adversarial same-stat edits.
"""
from pathlib import Path
import warnings

import numpy as np


SUMMARY_KEYS = ('step', 'temp', 'pe', 'ke', 'etotal', 'press', 'vol')
PARSER_SELECTION_POLICY = (
    'parse_log: prefer MD blocks if present, otherwise optimizer-only blocks; '
    'choose headers of longest candidate (first on ties); concatenate exact-header '
    'matches in source order; exclude incompatible/minimization blocks when MD '
    'exists; coalesce identical adjacent MD boundary records. Statistics describe '
    'selected rows, not necessarily elapsed MD time or an equilibrium ensemble.')
STEP_PRECISION_POLICY = (
    'parsed_float64: every retained raw Step column and selected step must be '
    'finite, integral and abs(value) < 2**53; this is not exact original-token '
    'validation (float64 parsing may already have rounded source values).')
_ALIASES = {'step': 'step', 'temp': 'temp', 'temperature': 'temp',
            'c_temp_mobile': 'temp', 'poteng': 'pe', 'pe': 'pe',
            'kineng': 'ke', 'ke': 'ke', 'toteng': 'etotal', 'etotal': 'etotal',
            'press': 'press', 'pressure': 'press', 'volume': 'vol', 'vol': 'vol'}


class InputChangedError(ValueError):
    """The log identity changed while a fresh snapshot was being parsed."""


def _header_columns(headers, context):
    """Map supported aliases to columns, rejecting ambiguous summary inputs."""
    if (not isinstance(headers, (list, tuple)) or not headers or
            not all(isinstance(header, str) for header in headers)):
        raise ValueError(f'{context}: expected a nonempty list of column headers')
    seen = {}
    for i, header in enumerate(headers):
        key = _ALIASES.get(str(header).lower())
        if key is None:
            continue
        if key in seen:
            raise ValueError(f'{context}: duplicate/alias collision for {key!r} '
                             f'in headers {headers!r}')
        seen[key] = i
    return seen


def _numeric(values, context, ndim):
    """Copy finite real values into a shape-checked float64 snapshot."""
    try:
        raw = np.asarray(values)
        if raw.dtype.kind not in 'iuf':
            raise ValueError('expected real numeric values')
        arr = np.array(raw, dtype=np.float64, copy=True)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{context}: expected real numeric array: {exc}') from exc
    if arr.ndim != ndim or not arr.size:
        raise ValueError(f'{context}: expected nonempty {ndim}-dimensional array')
    if not np.all(np.isfinite(arr)):
        raise ValueError(f'{context}: values must be finite')
    return arr


def _steps(values, context):
    """Guard parsed Step precision without claiming original-token validation."""
    if (not np.all(np.isfinite(values)) or
            np.any(np.abs(values) >= 2**53) or
            np.any(values != np.trunc(values))):
        raise ValueError(f'{context}: parsed float64 Step must be finite, integral '
                         'and abs(value) < 2**53; exact source tokens are not validated')


def summarize_thermo(log_data):
    """Return detached native-unit min/max/mean/population-std of selected rows.

    Only the seven legacy ordered columns are summarized. Selected columns must
    be finite nonempty 1-D arrays of equal length. Step precision is checked in
    *all* raw tables, including omitted ones. No inference or unit conversion is
    performed. Unknown units warn and have null dependent unit labels.
    Invalid snapshots raise ValueError rather than publishing partial statistics.
    """
    if not isinstance(log_data, dict):
        raise ValueError('thermo data must be a loaded log dictionary')
    if 'step' not in log_data:
        raise ValueError('thermo data require a step column')
    unit_system = log_data.get('unit_system')
    if unit_system is not None and unit_system not in ('metal', 'real'):
        raise ValueError(f'unsupported log unit_system {unit_system!r}; supported: metal, real')
    if 'headers' in log_data:
        _header_columns(log_data['headers'], 'selected thermo')
    for i, block in enumerate(log_data.get('raw_blocks', [])):
        try:
            headers, values, _ = block
            columns = _header_columns(headers, f'raw thermo block {i}')
            raw = np.asarray(values)
            if raw.ndim != 2 or raw.shape[1] != len(headers) or 'step' not in columns:
                raise ValueError('expected a Step-headed 2-D table matching headers')
            steps = _numeric(raw[:, columns['step']], f'raw thermo block {i} step', 1)
            _steps(steps, f'raw thermo block {i} step')
        except (TypeError, ValueError, IndexError) as exc:
            raise ValueError(f'raw thermo block {i}: {exc}') from exc
    arrays = {}
    count = None
    for key in SUMMARY_KEYS:
        if key not in log_data:
            continue
        values = _numeric(log_data[key], f'thermo {key}', 1)
        if count is not None and len(values) != count:
            raise ValueError(f'thermo {key}: length {len(values)} differs from step length {count}')
        count = len(values)
        if key == 'step':
            _steps(values, 'thermo step')
        arrays[key] = values
    statistics = {}
    for key, values in arrays.items():
        with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
            stats = {'min': float(values.min()), 'max': float(values.max()),
                     'mean': float(values.mean()), 'std': float(values.std(ddof=0))}
        if not all(np.isfinite(v) for v in stats.values()):
            raise ValueError(f'thermo {key}: computed statistics are not finite (numeric overflow)')
        statistics[key] = stats
    if unit_system is None:
        warnings.warn('Log unit_system is unresolved; statistics remain in native '
                      'units, dependent unit labels are null; no conversion or session '
                      'heuristic is applied.', RuntimeWarning, stacklevel=2)
    energy = {'metal': 'eV', 'real': 'kcal/mol'}.get(unit_system)
    native = {'step': 'step', 'temp': 'K' if unit_system else None,
              'pe': energy, 'ke': energy, 'etotal': energy,
              'press': {'metal': 'bar', 'real': 'atm'}.get(unit_system),
              'vol': 'angstrom^3' if unit_system else None}
    return {'sample_count': count, 'statistics': statistics,
            'unit_system': unit_system,
            'units': {key: native[key] for key in statistics}}


def _fingerprint(source):
    """Record resolved path and stat identity, explicitly not a content hash."""
    resolved = source.resolve(strict=True)
    stat = source.stat()
    return {'method': 'stat', 'resolved_path': str(resolved),
            'size': stat.st_size, 'mtime_ns': str(stat.st_mtime_ns),
            'inode': str(stat.st_ino), 'device': str(stat.st_dev)}


def summarize_thermo_file(path, diagnostics=None, provenance=None):
    """Fresh parse and summary with captured warnings and before/after stat.

    Return ``(result, warnings, fingerprint)``. Optional mutable collectors retain
    diagnostics/provenance on failure for execution adapters. No file is written.
    """
    from lammps_post.parsers import parse_log

    diagnostics = [] if diagnostics is None else diagnostics
    provenance = {} if provenance is None else provenance
    source = Path(path).absolute()
    before = _fingerprint(source)
    provenance['input_fingerprint'] = before
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        try:
            try:
                data = parse_log(source)
                if isinstance(data, dict) and data.get('unit_system') in ('metal', 'real'):
                    provenance['unit_source'] = 'log.unit_system'
                result = summarize_thermo(data)
                provenance['unit_source'] = ('log.unit_system'
                                             if result['unit_system'] else 'unresolved')
            finally:
                try:
                    after = _fingerprint(source)
                except OSError as exc:
                    raise InputChangedError('Log became unavailable while parsing; '
                                            'no result published') from exc
                if after != before:
                    raise InputChangedError('Log stat identity changed while parsing; '
                                            'no result published')
        finally:
            diagnostics.extend(str(item.message) for item in caught)
    return result, diagnostics, before
