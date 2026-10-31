"""Process-owned EXEC-2 jobs over the unchanged synchronous EXEC-1 protocol.

Only POSIX process groups with non-reaping waitid are supported. A non-daemon
supervisor thread owns two fresh children (discovery, then execution), not a
service or persistent backend.
Children must remain in their inherited process group: deliberate setsid escape,
parent SIGKILL, external side effects and restart recovery are not covered.
Package versions and interpreter identity are checked, not immutable build hashes.
Embedding applications must not reap this supervisor's children independently.

Transport bounds: one 1 MiB request and at most 1 MiB each of stdout/stderr per
child; either stream overflowing fails the job. Retained stderr diagnostics are
the first 1024 characters per phase. The four possible state-transition events
are never dropped. Cleanup adds up to 0.15 seconds TERM grace, one second leader
reaping and 0.15 seconds final pipe draining, with 0.02-second polling granularity.
Cleanup health is separate from the lifecycle outcome: cleanup.status is
not_required, pending, complete, failed, or (in a bounded CLI observation)
incomplete. cleanup.reaped is null if no child existed, true only after confirmed
cleanup, and false when cleanup/reaping is unconfirmed. cleanup.error is a bounded
code/message diagnostic that cancellation and timeout cannot overwrite.
"""
import argparse
import copy
import json
import logging
import math
import os
import selectors
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

from lammpkeeper import VERSION
from lammpkeeper import execution


LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
MAX_STREAM_BYTES = 1024 * 1024
TERMINATE_GRACE = 0.15
KILL_WAIT = 1.0
POLL_INTERVAL = 0.02
TERMINAL_STATES = frozenset(('succeeded', 'failed', 'cancelled', 'timed_out'))
_ENVELOPE_KEYS = frozenset(('protocol_version', 'request_id', 'operation',
                          'operation_version', 'status', 'result', 'error',
                          'warnings', 'artifacts', 'provenance'))


class _JobError(Exception):
    """Keep local transport failures distinct from validated backend failures."""

    def __init__(self, code, message, state='failed'):
        """Store the terminal category and a bounded human-readable diagnostic."""
        self.code = code
        self.message = str(message)[:execution.MAX_DIAGNOSTIC]
        self.state = state
        super().__init__(self.message)


def _duration(value, allow_zero=False):
    """Accept finite numeric seconds, excluding booleans and numeric strings."""
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or
            not math.isfinite(value) or value < 0 or (value == 0 and not allow_zero)):
        raise ValueError('timeout must be finite positive seconds (not bool)'
                         if not allow_zero else 'wait timeout must be finite nonnegative seconds')
    return float(value)


def _python_choice(python, env):
    """Select one configuration source, accepting string-valued path-like objects."""
    source = ('explicit' if python is not None else
              ('LKPR_PYTHON' if 'LKPR_PYTHON' in env else 'sys.executable'))
    requested = python if python is not None else env.get('LKPR_PYTHON', sys.executable)
    if isinstance(requested, os.PathLike):
        requested = os.fspath(requested)
    return source, requested


def _select_python(python, cwd, env):
    """Resolve exactly one interpreter while preserving virtualenv symlinks."""
    source, requested = _python_choice(python, env)
    selection = {'source': source, 'requested': requested, 'executable': None}
    if (not isinstance(requested, str) or not requested.strip() or
            len(requested) > execution.MAX_PATH or '\x00' in requested):
        raise _JobError('invalid_interpreter', f'{source} must select a nonempty executable path or name')
    if os.path.dirname(requested):
        selected = os.path.abspath(os.path.join(cwd, requested))
    else:
        # Resolve relative PATH entries against the captured caller directory,
        # never a later process-wide chdir. Do not dereference venv/bin/python.
        path = os.pathsep.join(os.path.abspath(os.path.join(cwd, item))
                               for item in env.get('PATH', os.defpath).split(os.pathsep))
        selected = shutil.which(requested, path=path)
    if not selected or not os.path.isfile(selected) or not os.access(selected, os.X_OK):
        raise _JobError('invalid_interpreter',
                        f'{source} executable is missing or not executable: {requested}')
    selection['executable'] = os.path.abspath(selected)
    return selection


def _decode(raw):
    """Read exactly one UTF-8 JSON value, rejecting duplicates and nonfinite data."""
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=execution._pairs,
                           parse_constant=execution._constant, parse_float=execution._float)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise _JobError('invalid_response', f'Invalid backend JSON: {exc}') from exc
    if not isinstance(value, dict):
        raise _JobError('invalid_response', 'Backend response must be a JSON object')
    return value


def _required_text(value, limit=execution.MAX_DIAGNOSTIC):
    """Recognize bounded, nonblank protocol diagnostics and identity strings."""
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _stat_decimal(value, signed=False):
    """Recognize ASCII decimal stat strings with at most one permitted minus sign."""
    if not isinstance(value, str) or not value.isascii():
        return False
    digits = value[1:] if signed and value.startswith('-') else value
    return digits.isdigit()


def _validate_envelope(response, returncode, request, selected):
    """Validate transport identity and status before retaining any backend result."""
    def invalid(message):
        """Raise one stable malformed-response category at the validation boundary."""
        raise _JobError('invalid_response', message)

    if set(response) != _ENVELOPE_KEYS:
        invalid('Backend envelope has missing or unknown fields')
    for field in ('protocol_version', 'operation_version'):
        if type(response[field]) is not int or response[field] != 1:
            invalid(f'Unsupported backend {field}; expected integer 1')
    if response['request_id'] != request['request_id'] or response['operation'] != request['operation']:
        invalid('Backend request_id or operation does not match submitted identity')
    status, result, error = response['status'], response['result'], response['error']
    if status == 'succeeded':
        if returncode != 0 or error is not None or not isinstance(result, dict):
            invalid('Success requires exit 0, an object result and null error')
    elif status == 'failed':
        if (returncode != 1 or result is not None or not isinstance(error, dict) or
                set(error) != {'code', 'message'} or
                not all(_required_text(error[key]) for key in ('code', 'message'))):
            invalid('Failure requires exit 1, null result and a bounded code/message error')
    else:
        invalid('Backend status must be succeeded or failed')
    if (not isinstance(response['warnings'], list) or len(response['warnings']) > execution.MAX_WARNINGS or
            any(not isinstance(item, str) or len(item) > execution.MAX_DIAGNOSTIC
                for item in response['warnings']) or
            response['artifacts'] != []):
        invalid('Backend warnings or EXEC-1 artifact declaration is invalid')
    provenance = response['provenance']
    if (not isinstance(provenance, dict) or set(provenance) != {
            'package_version', 'python_version', 'python_executable', 'numpy_version',
            'input_fingerprint', 'parser_selection_policy', 'step_precision_policy', 'unit_source'}):
        invalid('Backend provenance has missing or unknown fields')
    for key in ('package_version', 'python_version', 'python_executable', 'numpy_version'):
        limit = execution.MAX_PATH if key == 'python_executable' else execution.MAX_DIAGNOSTIC
        if not _required_text(provenance.get(key), limit):
            invalid(f'Backend provenance requires {key}')
    for key in ('parser_selection_policy', 'step_precision_policy', 'unit_source'):
        if not _required_text(provenance[key]):
            invalid(f'Backend provenance requires {key}')
    fingerprint = provenance['input_fingerprint']
    if fingerprint is not None:
        if (not isinstance(fingerprint, dict) or set(fingerprint) != {
                'method', 'resolved_path', 'size', 'mtime_ns', 'inode', 'device'} or
                fingerprint['method'] != 'stat' or not isinstance(fingerprint['resolved_path'], str) or
                not os.path.isabs(fingerprint['resolved_path']) or
                type(fingerprint['size']) is not int or fingerprint['size'] < 0 or
                any(not _stat_decimal(fingerprint[key], signed=(key == 'mtime_ns'))
                    for key in ('mtime_ns', 'inode', 'device'))):
            invalid('Backend stat input fingerprint is malformed')
    # abspath preserves symlinks: venv and base interpreters can share a target
    # inode but are not interchangeable execution environments.
    if (not os.path.isabs(provenance['python_executable']) or
            os.path.normpath(provenance['python_executable']) != selected):
        invalid('Backend python_executable does not match the selected launch path')
    if provenance['package_version'] != VERSION:
        raise _JobError('incompatible_backend',
                        f'Backend package version {provenance["package_version"]} does not match {VERSION}')
    return response


def _validate_capabilities(response, returncode, selected):
    """Require compatible discovery before any operation child can be launched."""
    _validate_envelope(response, returncode,
                       {'request_id': None, 'operation': 'capabilities'}, selected)
    if response['status'] != 'succeeded':
        raise _JobError('incompatible_backend', 'Backend capability discovery failed')
    result = response['result']
    protocols = result.get('protocol_versions')
    operations = result.get('operations')
    if (not isinstance(protocols, list) or not protocols or
            any(type(version) is not int for version in protocols) or 1 not in protocols or
            not isinstance(operations, dict) or not isinstance(operations.get('thermo.summary'), dict)):
        raise _JobError('incompatible_backend', 'Backend must advertise protocol 1 and thermo.summary')
    versions = operations['thermo.summary'].get('versions')
    if (not isinstance(versions, list) or not versions or
            any(type(version) is not int for version in versions) or 1 not in versions):
        raise _JobError('incompatible_backend', 'Backend must advertise thermo.summary version 1')
    return {key: response['provenance'][key] for key in
            ('package_version', 'python_version', 'python_executable', 'numpy_version')}


def _validate_result(response, returncode, request, selected, handshake):
    """Reject foreign provenance and malformed summary shapes, not recompute science."""
    _validate_envelope(response, returncode, request, selected)
    if any(response['provenance'][key] != value for key, value in handshake.items()):
        raise _JobError('invalid_response', 'Execution provenance differs from capability handshake')
    if response['status'] == 'succeeded':
        result = response['result']
        if (set(result) != {'sample_count', 'statistics', 'unit_system', 'units'} or
                type(result['sample_count']) is not int or result['sample_count'] < 1 or
                result['unit_system'] not in ('metal', 'real', None) or
                not isinstance(result['statistics'], dict) or not result['statistics'] or
                not isinstance(result['units'], dict) or set(result['units']) != set(result['statistics']) or
                'step' not in result['statistics'] or response['provenance']['input_fingerprint'] is None):
            raise _JobError('invalid_response', 'Malformed thermo.summary result fields')
        for column, statistics in result['statistics'].items():
            if (column not in execution.SUMMARY_KEYS or not isinstance(statistics, dict) or
                    set(statistics) != {'min', 'max', 'mean', 'std'} or
                    any(type(number) not in (int, float) for number in statistics.values()) or
                    not (result['units'][column] is None or _required_text(result['units'][column]))):
                raise _JobError('invalid_response', 'Malformed thermo.summary statistics or units')
    return response


def _signal_group(process, sig):
    """Signal only the session created for this child, tolerating a finished group."""
    try:
        os.killpg(process.pid, sig)
        return True
    except ProcessLookupError:
        return False


def _cleanup(process):
    """Attempt all bounded cleanup stages and retain signal/reaping failures."""
    problems = []
    signalled = False
    try:
        signalled = _signal_group(process, signal.SIGTERM)
    except OSError as exc:
        problems.append(f'Group SIGTERM failed: {exc}')
    if signalled:
        # A reaped leader does not imply its descendants released inherited
        # pipes. Escalation targets the group regardless of leader returncode.
        end = time.monotonic() + TERMINATE_GRACE
        while time.monotonic() < end:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                break
            except OSError as exc:
                problems.append(f'Group existence check failed: {exc}')
                break
            time.sleep(POLL_INTERVAL)
    # Even failed TERM/existence checks must not bypass KILL and the bounded
    # reap attempt. An OS error is retained rather than silently claiming that
    # cancellation or timeout guaranteed cleanup of a possibly living group.
    try:
        _signal_group(process, signal.SIGKILL)
    except OSError as exc:
        problems.append(f'Group SIGKILL failed: {exc}')
    try:
        process.wait(timeout=KILL_WAIT)
    except subprocess.TimeoutExpired:
        problems.append('Child could not be reaped after process-group SIGKILL')
    except OSError as exc:
        problems.append(f'Child reaping failed: {exc}')
    if problems:
        raise _JobError('cleanup_failed', '; '.join(problems))


def _child_exited(process):
    """Inspect leader exit without releasing the PID that reserves its group ID."""
    # Popen.poll() would reap a dead leader before group cleanup. Keeping that
    # zombie waitable prevents PID/group-ID reuse from targeting an unrelated
    # new session between exit detection and the last killpg call. Applications
    # embedding this API must not install a competing child reaper.
    info = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    return info is not None and info.si_pid == process.pid


class LocalJob:
    """Thread-safe handle owned solely by its submitting Python process.

    States are created -> handshaking -> running -> a single immutable terminal
    state (succeeded/failed/cancelled/timed_out); early failure can skip phases.
    Snapshots/events are deep copies. The at-most-four transition events are
    always retained and logged, with increasing sequence and monotonic elapsed
    seconds, not fabricated scientific progress. No cross-process lookup exists.
    A terminal outcome with cleanup.status='failed' does not assert successful
    reaping; its separate cleanup.error survives cancellation/timeout precedence.
    """

    def __init__(self, request, python=None, timeout=60.0, cwd=None):
        """Freeze submission context and start supervision, or retain a local failure."""
        self._lock = threading.RLock()
        self._done = threading.Event()
        self._cancel = threading.Event()
        self._started = time.monotonic()
        self._deadline = float('inf')
        self._data = {'job_schema_version': 1, 'job_id': str(uuid.uuid4()),
                      'request_id': None, 'operation': None, 'operation_version': None,
                      'state': 'created', 'cwd': None, 'timeout_seconds': None,
                      'elapsed_seconds': 0.0, 'interpreter': None, 'handshake': None,
                      'error': None, 'backend_response': None,
                      'cleanup': {'status': 'not_required', 'reaped': None, 'error': None},
                      'diagnostics': {'handshake': '', 'execution': ''}, 'events': []}
        self._transition('created')
        try:
            if (os.name != 'posix' or any(not hasattr(os, name) for name in
                    ('killpg', 'waitid', 'P_PID', 'WEXITED', 'WNOHANG', 'WNOWAIT'))):
                raise _JobError('unsupported_platform',
                                'Local supervision requires POSIX process groups and non-reaping waitid')
            self._data['timeout_seconds'] = _duration(timeout)
            self._deadline = self._started + self._data['timeout_seconds']
            caller_cwd = os.getcwd()
            self._data['cwd'] = (os.path.abspath(os.path.join(caller_cwd, os.fspath(cwd)))
                                 if cwd is not None else caller_cwd)
            self._env = dict(os.environ)
            self._env['LKPR_NO_HISTORY'] = '1'
            execution._validate(request)
            self._raw = json.dumps(request, allow_nan=False, ensure_ascii=True,
                                   separators=(',', ':')).encode('utf-8')
            if len(self._raw) > execution.MAX_REQUEST_BYTES:
                raise ValueError(f'Request exceeds {execution.MAX_REQUEST_BYTES} bytes')
            # The wire representation freezes caller-owned nested dictionaries
            # before returning the handle or starting either backend subprocess.
            self._request = json.loads(self._raw)
            for key in ('request_id', 'operation', 'operation_version'):
                self._data[key] = self._request[key]
            source, requested = _python_choice(python, self._env)
            self._data['interpreter'] = {'source': source,
                                         'requested': (requested[:execution.MAX_PATH]
                                                       if isinstance(requested, str) else None),
                                         'executable': None}
            self._data['interpreter'] = _select_python(python, caller_cwd, self._env)
        except _JobError as exc:
            self._finish(exc.state, {'code': exc.code, 'message': exc.message})
            return
        except (ValueError, TypeError, OSError, RecursionError, OverflowError) as exc:
            self._finish('failed', {'code': getattr(exc, 'code', 'invalid_request'),
                                    'message': str(exc)[:execution.MAX_DIAGNOSTIC]})
            return
        try:
            self._thread = threading.Thread(target=self._supervise,
                                            name='lkpr-job-' + self._data['job_id'], daemon=False)
            self._thread.start()
        except RuntimeError as exc:
            self._finish('failed', {'code': 'transport_error',
                                    'message': str(exc)[:execution.MAX_DIAGNOSTIC]})

    def _transition(self, state):
        """Append one bounded lifecycle event while the caller holds the state lock."""
        self._data['state'] = state
        elapsed = time.monotonic() - self._started
        self._data['elapsed_seconds'] = elapsed
        event = {'sequence': len(self._data['events']) + 1,
                 'state': state, 'elapsed_seconds': elapsed}
        self._data['events'].append(event)
        LOGGER.info('Local job %s: %s', self._data['job_id'], state)

    def _interrupt(self):
        """Give accepted cancellation precedence, then enforce the overall deadline."""
        if self._cancel.is_set():
            raise _JobError('cancelled', 'Cancellation requested by owner', 'cancelled')
        if time.monotonic() >= self._deadline:
            raise _JobError('timed_out', 'Overall job timeout expired', 'timed_out')

    def _finish(self, state, error=None, response=None):
        """Commit terminal data once, with cancellation/deadline checked atomically."""
        with self._lock:
            if self._done.is_set():
                return
            if error is not None and error.get('code') == 'cleanup_failed':
                self._data['cleanup'] = {'status': 'failed', 'reaped': False,
                                         'error': {'code': 'cleanup_failed',
                                                   'message': str(error['message'])[:execution.MAX_DIAGNOSTIC]}}
            if self._data['cleanup']['error'] is not None:
                # Cleanup health is independent of the outcome race below.
                # Never attach even a valid backend response to uncertain cleanup.
                response = None
                if state == 'succeeded':
                    state, error = 'failed', self._data['cleanup']['error']
            try:
                self._interrupt()
            except _JobError as exc:
                state, error, response = exc.state, {'code': exc.code, 'message': exc.message}, None
            self._data['error'] = error
            self._data['backend_response'] = response
            self._transition(state)
            if error:
                LOGGER.warning('Local job %s: %s: %s', self._data['job_id'], error['code'], error['message'])
            self._done.set()

    def snapshot(self):
        """Return a detached JSON-safe snapshot; terminal snapshots never change."""
        with self._lock:
            result = copy.deepcopy(self._data)
            if not self._done.is_set():
                result['elapsed_seconds'] = time.monotonic() - self._started
            return result

    def wait(self, timeout=None):
        """Return terminal snapshot; a caller wait limit raises without cancelling.

        timeout=None waits for the job's own finite deadline and cleanup. A
        nonnegative finite timeout limits only this wait, not execution lifetime.
        """
        if timeout is not None:
            timeout = _duration(timeout, allow_zero=True)
        if timeout is None:
            self._done.wait()
        else:
            deadline = time.monotonic() + timeout
            while not self._done.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Local job is still active; wait limit does not cancel it')
                # A valid finite duration can exceed the platform lock timeout;
                # chunk the caller wait instead of overflowing the native lock.
                self._done.wait(min(remaining, threading.TIMEOUT_MAX))
        return self.snapshot()

    def cancel(self):
        """Request cancellation idempotently and return current, possibly active state.

        Setting the request and terminal publication share one lock. If this call
        wins before the overall deadline, success/failure cannot be published
        afterward, even if cleanup crosses that deadline. A request at/after the
        deadline cannot replace timed_out. wait() observes the
        cancelled terminal state after a cleanup attempt; inspect cleanup.status
        to distinguish confirmed reaping from cleanup failure. A terminal job is
        unchanged. Cancellation does not roll back arbitrary external effects.
        """
        with self._lock:
            if not self._done.is_set() and time.monotonic() < self._deadline:
                self._cancel.set()
            return self.snapshot()

    def _cleanup_child(self, process):
        """Keep bounded cleanup diagnostics independent of cancellation/timeout."""
        try:
            _cleanup(process)
        except Exception as exc:
            message = exc.message if isinstance(exc, _JobError) else f'{type(exc).__name__}: {exc}'
            failure = _JobError('cleanup_failed', message)
            with self._lock:
                self._data['cleanup'] = {
                    'status': 'failed', 'reaped': False,
                    'error': {'code': failure.code, 'message': failure.message}}
            LOGGER.warning('Local job %s cleanup failed: %s',
                           self._data['job_id'], failure.message)
            raise failure from exc
        with self._lock:
            self._data['cleanup'] = {'status': 'complete', 'reaped': True, 'error': None}

    def _child(self, phase, args, raw=None):
        """Concurrently pump three nonblocking pipes with per-stream byte bounds."""
        self._interrupt()
        selector = selectors.DefaultSelector()
        outputs = {'stdout': bytearray(), 'stderr': bytearray()}
        process = None
        offset = 0
        cleaned = False
        cleanup_attempted = False
        drain_deadline = None
        with self._lock:
            previous_cleanup = self._data['cleanup']
            self._data['cleanup'] = {'status': 'pending', 'reaped': False, 'error': None}
        try:
            process = subprocess.Popen([self._data['interpreter']['executable'],
                                        '-m', 'lammpkeeper', 'exec'] + args,
                                       stdin=subprocess.DEVNULL if raw is None else subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       cwd=self._data['cwd'], env=self._env,
                                       shell=False, start_new_session=True)
            for stream, name in ((process.stdout, 'stdout'), (process.stderr, 'stderr'),
                                 (process.stdin, 'stdin')):
                if stream is not None:
                    os.set_blocking(stream.fileno(), False)
                    event = selectors.EVENT_WRITE if name == 'stdin' else selectors.EVENT_READ
                    selector.register(stream, event, name)
            while True:
                self._interrupt()
                for key, _ in selector.select(POLL_INTERVAL):
                    name, stream = key.data, key.fileobj
                    if name == 'stdin':
                        try:
                            offset += os.write(stream.fileno(), raw[offset:offset + 16384])
                        except BrokenPipeError:
                            offset = len(raw)
                        except BlockingIOError:
                            continue
                        if offset == len(raw):
                            selector.unregister(stream)
                            stream.close()
                    else:
                        try:
                            chunk = os.read(stream.fileno(), 65536)
                        except BlockingIOError:
                            continue
                        if not chunk:
                            selector.unregister(stream)
                            continue
                        if len(outputs[name]) + len(chunk) > MAX_STREAM_BYTES:
                            raise _JobError('output_limit',
                                            f'{phase} {name} exceeds {MAX_STREAM_BYTES} bytes')
                        outputs[name].extend(chunk)
                if not cleaned and _child_exited(process):
                    cleanup_attempted = True
                    self._cleanup_child(process)
                    cleaned = True
                    drain_deadline = time.monotonic() + TERMINATE_GRACE
                if cleaned and (not selector.get_map() or time.monotonic() >= drain_deadline):
                    break
        finally:
            try:
                if process is not None and not cleanup_attempted:
                    # Mark the attempt before calling: a failed attempt must not
                    # be retried implicitly or have its first diagnostic erased.
                    cleanup_attempted = True
                    self._cleanup_child(process)
            finally:
                selector.close()
                if process is not None:
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream is not None:
                            stream.close()
                with self._lock:
                    if process is None:
                        self._data['cleanup'] = previous_cleanup
                    self._data['diagnostics'][phase] = outputs['stderr'].decode(
                        'utf-8', errors='replace')[:execution.MAX_DIAGNOSTIC]
        self._interrupt()
        if process.returncode < 0:
            raise _JobError('child_crash', f'{phase} child terminated by signal {-process.returncode}')
        return bytes(outputs['stdout']), process.returncode

    def _supervise(self):
        """Publish validated results only with confirmed cleanup, or visible failure."""
        try:
            with self._lock:
                self._transition('handshaking')
            raw, status = self._child('handshake', ['--capabilities'])
            selected = self._data['interpreter']['executable']
            handshake = _validate_capabilities(_decode(raw), status, selected)
            with self._lock:
                self._interrupt()
                self._data['handshake'] = handshake
                self._transition('running')
            raw, status = self._child('execution', ['--request', '-'], self._raw)
            response = _validate_result(_decode(raw), status, self._request, selected, handshake)
            self._finish(response['status'], response['error'], response)
        except _JobError as exc:
            self._finish(exc.state, {'code': exc.code, 'message': exc.message})
        except Exception as exc:
            self._finish('failed', {'code': 'transport_error',
                                    'message': f'{type(exc).__name__}: {exc}'[:execution.MAX_DIAGNOSTIC]})


def start_job(request, python=None, timeout=60.0, cwd=None):
    """Submit one validated EXEC-1 request and return its process-owned LocalJob.

    Interpreter precedence is explicit python, LKPR_PYTHON (including invalid
    empty values), then sys.executable. There is never fallback or installation.
    Caller cwd/environment are captured once; LKPR_NO_HISTORY=1 is the only child
    environment override. Invalid submissions return an already failed handle.
    Relative interpreter paths use the submission caller directory, not the
    optional child cwd. Executable symlinks are preserved, never dereferenced.
    The finite positive overall timeout includes validation, discovery, execution
    and result validation; bounded termination/reaping can add cleanup time.
    """
    return LocalJob(request, python=python, timeout=timeout, cwd=cwd)


class _ArgumentParser(argparse.ArgumentParser):
    """Keep run-command argument errors inside the structured job boundary."""

    def error(self, message):
        """Raise a readable parse failure instead of printing usage to stdout."""
        raise ValueError(message)


def main(argv=None):
    """Wait for this invocation's job and print one JSON snapshot (Ctrl-C: 130).

    --events emits retained lifecycle events as JSON lines to stderr only. This
    command provides no cross-command status/cancel or persistence. Ctrl-C asks
    the owned job to cancel and waits a bounded interval for group reaping.
    If that wait expires, emit a nonterminal snapshot with explicit incomplete
    cleanup, not a fabricated terminal event. The non-daemon worker may still
    keep the interpreter alive if an OS operation cannot be interrupted.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = _ArgumentParser(prog='lkpr run', description=
                             'Run one process-owned local job; wait for its final JSON snapshot.')
    parser.add_argument('--request', required=True, metavar='PATH',
                        help='EXEC-1 JSON request path, or - for stdin')
    parser.add_argument('--python', metavar='PATH', help='explicit Python executable (no fallback)')
    parser.add_argument('--timeout', type=float, default=60.0, metavar='SECONDS',
                        help='overall finite positive job timeout (default: 60)')
    parser.add_argument('--events', action='store_true', help='stream lifecycle event JSON lines to stderr')
    if argv in (['--help'], ['-h']):
        parser.print_help()
        return 0
    job = None
    emitted = 0
    interrupted = False
    try:
        # Help with other flags is not a successful job submission.
        if '-h' in argv or '--help' in argv:
            raise ValueError('Use --help alone for ordinary help')
        options = parser.parse_args(argv)
        request = execution._read_request(options.request)
        submission_interrupted = False
        def defer_submission_interrupt(signum, frame):
            """Delay SIGINT until the newly created handle is assigned to its owner."""
            nonlocal submission_interrupted
            submission_interrupted = True

        # Without deferral SIGINT can unwind start_job after its worker starts
        # but before assignment, leaving this CLI unable to cancel its own job.
        previous = signal.signal(signal.SIGINT, defer_submission_interrupt)
        try:
            job = start_job(request, python=options.python, timeout=options.timeout)
        finally:
            signal.signal(signal.SIGINT, previous)
        if submission_interrupted:
            raise KeyboardInterrupt
        while True:
            snapshot = job.snapshot()
            if options.events:
                for event in snapshot['events'][emitted:]:
                    print(json.dumps(event, allow_nan=False, separators=(',', ':')), file=sys.stderr, flush=True)
                emitted = len(snapshot['events'])
            try:
                snapshot = job.wait(POLL_INTERVAL)
                break
            except TimeoutError:
                continue
    except KeyboardInterrupt:
        interrupted = True
        if job is None:
            snapshot = _submission_failure('cancelled', 'Interrupted before job submission',
                                           state='cancelled')
        else:
            # A second interrupt must not abandon live children during cleanup.
            previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
            try:
                job.cancel()
                try:
                    snapshot = job.wait(2 * (TERMINATE_GRACE + KILL_WAIT) + 1)
                except TimeoutError:
                    snapshot = job.snapshot()
                    if snapshot['state'] not in TERMINAL_STATES:
                        failure = {'code': 'cleanup_wait_timeout', 'message':
                                   'CLI cleanup wait expired; supervisor may still be active and children unconfirmed'}
                        # This is a detached observation, not terminal publication:
                        # do not alter the job, invent an event, or claim completion.
                        if snapshot['cleanup']['error'] is None:
                            snapshot['cleanup'] = {'status': 'incomplete',
                                                   'reaped': False, 'error': failure}
                        snapshot['error'] = failure
                        snapshot['backend_response'] = None
                        LOGGER.warning('Local job %s: %s', snapshot['job_id'], failure['message'])
            finally:
                signal.signal(signal.SIGINT, previous)
    except (ValueError, OSError, UnicodeError, RecursionError) as exc:
        snapshot = _submission_failure('invalid_request', exc)
    if job is not None and 'options' in locals() and options.events:
        for event in snapshot['events'][emitted:]:
            print(json.dumps(event, allow_nan=False, separators=(',', ':')),
                  file=sys.stderr, flush=True)
    print(json.dumps(snapshot, allow_nan=False, separators=(',', ':'), ensure_ascii=True))
    return 130 if interrupted else (0 if snapshot['state'] == 'succeeded' else 1)


def _submission_failure(code, message, state='failed'):
    """Build the same snapshot schema for failures before a request can be read."""
    job = LocalJob.__new__(LocalJob)
    job._lock = threading.RLock()
    job._done = threading.Event()
    job._cancel = threading.Event()
    job._started = time.monotonic()
    job._deadline = float('inf')
    job._data = {'job_schema_version': 1, 'job_id': str(uuid.uuid4()),
                 'request_id': None, 'operation': None, 'operation_version': None,
                 'state': 'created', 'cwd': None, 'timeout_seconds': None,
                 'elapsed_seconds': 0.0, 'interpreter': None, 'handshake': None,
                 'error': None, 'backend_response': None,
                 'cleanup': {'status': 'not_required', 'reaped': None, 'error': None},
                 'diagnostics': {'handshake': '', 'execution': ''}, 'events': []}
    job._transition('created')
    job._finish(state, {'code': code, 'message': str(message)[:execution.MAX_DIAGNOSTIC]})
    return job.snapshot()
