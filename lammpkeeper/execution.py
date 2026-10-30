"""Bounded synchronous EXEC-1 JSON adapter; scientific logic lives in application."""
import contextlib
import json
import platform
import sys

import numpy as np

from lammpkeeper import VERSION
from lammpkeeper.application import (
    InputChangedError, PARSER_SELECTION_POLICY, STEP_PRECISION_POLICY,
    SUMMARY_KEYS, summarize_thermo_file,
)


MAX_REQUEST_BYTES = 1024 * 1024
MAX_REQUEST_ID = 128
MAX_PATH = 4096
MAX_DIAGNOSTIC = 1024
MAX_WARNINGS = 64
_FIELDS = {'protocol_version', 'request_id', 'operation', 'operation_version',
           'input', 'parameters'}


class RequestError(ValueError):
    """Carry a stable protocol error category for invalid request controls."""

    def __init__(self, code, message):
        """Retain the machine category separately from the readable diagnostic."""
        self.code = code
        super().__init__(message)


def _text(value, limit):
    """Accept only bounded nonblank strings for identifiers and input paths."""
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _base(request=None):
    """Build a failure-safe envelope, echoing only bounded scalar identity fields."""
    request = request if isinstance(request, dict) else {}
    request_id = request.get('request_id')
    operation = request.get('operation')
    version = request.get('operation_version')
    return {'protocol_version': 1,
            'request_id': request_id if _text(request_id, MAX_REQUEST_ID) else None,
            'operation': operation if _text(operation, MAX_REQUEST_ID) else None,
            'operation_version': version if type(version) is int and abs(version) < 2**53 else None,
            'status': 'failed', 'result': None, 'error': None, 'warnings': [],
            'artifacts': [],
            'provenance': {'package_version': VERSION, 'numpy_version': np.__version__,
                           'python_version': platform.python_version(),
                           'python_executable': sys.executable,
                           'input_fingerprint': None,
                           'parser_selection_policy': PARSER_SELECTION_POLICY,
                           'step_precision_policy': STEP_PRECISION_POLICY,
                           'unit_source': 'unresolved'}}


def _fail(response, code, message):
    """Attach a categorized, bounded diagnostic without publishing a result."""
    response['error'] = {'code': code, 'message': str(message)[:MAX_DIAGNOSTIC]}
    return response


def _validate(request):
    """Enforce the exact v1 schema before opening any scientific input."""
    if not isinstance(request, dict) or set(request) != _FIELDS:
        raise RequestError('invalid_request', 'Request must contain exactly: ' + ', '.join(sorted(_FIELDS)))
    if not _text(request['request_id'], MAX_REQUEST_ID):
        raise RequestError('invalid_request', f'request_id must be nonblank string of at most {MAX_REQUEST_ID} characters')
    for field in ('protocol_version', 'operation_version'):
        if type(request[field]) is not int:
            raise RequestError('invalid_request', f'{field} must be an integer (not bool or float)')
        if request[field] != 1:
            raise RequestError('unsupported_version', f'Unsupported {field}; supported: 1')
    if request['operation'] != 'thermo.summary':
        raise RequestError('invalid_request', 'Supported operation: thermo.summary')
    inp = request['input']
    if not isinstance(inp, dict) or set(inp) != {'log'} or not _text(inp['log'], MAX_PATH):
        raise RequestError('invalid_request', f'input must contain only log: nonblank path string, at most {MAX_PATH} characters')
    if '\x00' in inp['log']:
        raise RequestError('invalid_request', 'input.log may not contain NUL')
    if not isinstance(request['parameters'], dict) or request['parameters']:
        raise RequestError('invalid_request', 'parameters must be an empty object')


def execute_request(request):
    """Execute a decoded request and return one JSON-safe success/failure envelope."""
    response = _base(request)
    diagnostics = []
    try:
        _validate(request)
        # Guard the protocol stream even if a parser later gains human logging.
        with contextlib.redirect_stdout(sys.stderr):
            result, _, _ = summarize_thermo_file(request['input']['log'], diagnostics,
                                                 response['provenance'])
        response.update(status='succeeded', result=result)
    except RequestError as exc:
        _fail(response, exc.code, exc)
    except InputChangedError as exc:
        _fail(response, 'input_changed', exc)
    except OSError as exc:
        _fail(response, 'io_error', exc)
    except (ValueError, UnicodeError) as exc:
        _fail(response, 'invalid_input', exc)
    except Exception as exc:
        _fail(response, 'internal_error', f'{type(exc).__name__}: {exc}')
    response['warnings'] = [str(item)[:MAX_DIAGNOSTIC] for item in diagnostics[:MAX_WARNINGS]]
    if len(diagnostics) > MAX_WARNINGS:
        response['warnings'][-1] = 'Additional warnings omitted (warning count bound reached)'
    return response


def capabilities():
    """Return bounded discovery in the same envelope (no request ID required)."""
    response = _base()
    response.update(status='succeeded', operation='capabilities', operation_version=1,
                    result={
                        'protocol_versions': [1],
                        'operations': {'thermo.summary': {
                            'versions': [1], 'columns': list(SUMMARY_KEYS),
                            'statistics': ['min', 'max', 'mean', 'std'],
                            'result_fields': ['sample_count', 'statistics', 'unit_system', 'units'],
                            'std_ddof': 0, 'selected_rows': PARSER_SELECTION_POLICY,
                            'step_precision': STEP_PRECISION_POLICY}},
                        'request_schema': {
                            'type': 'object', 'required': sorted(_FIELDS),
                            'additionalProperties': False,
                            'properties': {
                                'protocol_version': {'type': 'integer', 'const': 1},
                                'request_id': {'type': 'string', 'minLength': 1,
                                               'maxLength': MAX_REQUEST_ID, 'pattern': r'\S'},
                                'operation': {'const': 'thermo.summary'},
                                'operation_version': {'type': 'integer', 'const': 1},
                                'input': {'type': 'object', 'required': ['log'],
                                          'additionalProperties': False,
                                          'properties': {'log': {'type': 'string',
                                                                 'minLength': 1, 'maxLength': MAX_PATH,
                                                                 'pattern': r'\S'}}},
                                'parameters': {'type': 'object', 'maxProperties': 0}}},
                        'schema_caveats': [
                            'Versions require integer JSON tokens, not float tokens (including 1.0) or bool values; JSON Schema integer alone does not express this lexical restriction.',
                            'input.log must not contain NUL, in addition to the declared string length and nonblank restrictions.'],
                        'units': {'supported': ['metal', 'real'], 'conversion': False,
                                  'unresolved': 'native values; null dependent units and warning',
                                  'source': 'log.unit_system only; no session heuristics'},
                        'bounds': {'request_bytes': MAX_REQUEST_BYTES,
                                   'request_id_characters': MAX_REQUEST_ID,
                                   'path_characters': MAX_PATH,
                                   'diagnostic_characters': MAX_DIAGNOSTIC,
                                   'warnings': MAX_WARNINGS, 'summary_columns': len(SUMMARY_KEYS)},
                        'execution': {'mode': 'synchronous', 'cancellation': False,
                                      'artifacts': False},
                        'input_identity': 'before/after stat, not content hash',
                        'paths': 'input.log relative to caller working directory, not request file',
                        'strict_json': 'duplicate keys and nonfinite numbers rejected; versions require integer tokens, not bool or float',
                        'error_codes': ['invalid_request', 'unsupported_version', 'invalid_input',
                                        'input_changed', 'io_error', 'internal_error']})
    return response


def _pairs(pairs):
    """Reject duplicate JSON keys instead of silently keeping the last value."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def _constant(value):
    """Reject nonstandard nonfinite JSON tokens with a readable diagnostic."""
    raise ValueError(f'Nonfinite JSON number is not permitted: {value}')


def _float(value):
    """Reject numeric JSON literals whose float conversion overflows to infinity."""
    number = float(value)
    if not np.isfinite(number):
        _constant(value)
    return number


def _read_request(path):
    """Read at most one bounded UTF-8 request and apply strict JSON decoding."""
    if path == '-':
        stream = getattr(sys.stdin, 'buffer', sys.stdin)
        raw = stream.read(MAX_REQUEST_BYTES + 1)
    else:
        with open(path, 'rb') as stream:
            raw = stream.read(MAX_REQUEST_BYTES + 1)
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    if len(raw) > MAX_REQUEST_BYTES:
        raise ValueError(f'Request exceeds {MAX_REQUEST_BYTES} bytes')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                      parse_constant=_constant, parse_float=_float)


def main(argv=None):
    """One invocation, one strict JSON line; help alone is ordinary human text."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv in (['-h'], ['--help']):
        print('usage: lkpr exec --request PATH | --capabilities\n'
              'PATH - reads one JSON request from stdin (maximum 1 MiB).')
        return 0
    response = _base()
    try:
        if argv == ['--capabilities']:
            response = capabilities()
        elif (len(argv) == 2 and argv[0] == '--request' and
              (argv[1] == '-' or not argv[1].startswith('-'))):
            response = execute_request(_read_request(argv[1]))
        else:
            raise ValueError('Expected exactly --request PATH or --capabilities; no output option is supported')
    except OSError as exc:
        _fail(response, 'io_error', exc)
    except (ValueError, UnicodeError, RecursionError) as exc:
        _fail(response, 'invalid_request', exc)
    except Exception as exc:
        _fail(response, 'internal_error', f'{type(exc).__name__}: {exc}')
    print(json.dumps(response, allow_nan=False, separators=(',', ':'), ensure_ascii=True))
    return 0 if response['status'] == 'succeeded' else 1
