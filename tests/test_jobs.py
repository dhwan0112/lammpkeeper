"""EXEC-2 regressions for bounded, process-owned local execution."""
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

import _util


def _request(path='unused.log'):
    """Build a complete EXEC-1 request without scientific defaults."""
    return {'protocol_version': 1, 'request_id': 'local-A',
            'operation': 'thermo.summary', 'operation_version': 1,
            'input': {'log': str(path)}, 'parameters': {}}


def _fake(root, handshake='', execution='', name='python with spaces', before_read=''):
    """Create a fast stdlib-only interpreter stand-in with real subprocess pipes."""
    from lammpkeeper.execution import capabilities, _base
    cap = capabilities()
    response = _base(_request())
    response.update(status='succeeded', result={
        'sample_count': 1, 'statistics': {'step': {'min': 0, 'max': 0, 'mean': 0, 'std': 0}},
        'unit_system': 'metal', 'units': {'step': 'step'}})
    response['provenance']['input_fingerprint'] = {
        'method': 'stat', 'resolved_path': str(root / 'unused.log'),
        'size': 1, 'mtime_ns': '1', 'inode': '1', 'device': '1'}
    path = root / name
    path.write_text('#!' + sys.executable + '\n' +
                    'import json, os, pathlib, signal, subprocess, sys, time\n' +
                    'root = pathlib.Path(' + repr(str(root)) + ')\n' +
                    'cap = ' + repr(cap) + '\n' +
                    'response = ' + repr(response) + '\n' +
                    "assert os.environ['LKPR_NO_HISTORY'] == '1'\n" +
                    "phase = 'handshake' if sys.argv[-1] == '--capabilities' else 'execution'\n" +
                    "(root / (phase + '.started')).write_text(str(os.getpid()))\n" +
                    "if phase == 'handshake':\n" +
                    "    assert sys.stdin.buffer.read() == b''\n" +
                    "    cap['provenance']['python_executable'] = os.path.abspath(sys.argv[0])\n" +
                    ''.join('    ' + line + '\n' for line in handshake.splitlines()) +
                    "    print(json.dumps(cap, allow_nan=False), flush=True)\n" +
                    "else:\n" +
                    ''.join('    ' + line + '\n' for line in before_read.splitlines()) +
                    "    request = json.loads(sys.stdin.buffer.read())\n" +
                    "    (root / 'received.json').write_text(json.dumps(request))\n" +
                    "    for key in ('request_id', 'operation', 'operation_version'):\n" +
                    "        response[key] = request[key]\n" +
                    "    response['provenance']['python_executable'] = os.path.abspath(sys.argv[0])\n" +
                    ''.join('    ' + line + '\n' for line in execution.splitlines()) +
                    "    print(json.dumps(response, allow_nan=False), flush=True)\n" +
                    "    sys.exit(0 if response['status'] == 'succeeded' else 1)\n")
    path.chmod(0o755)
    return str(path)


def _await_file(path, timeout=5):
    """Synchronize on a child-written sentinel, not guessed startup sleeps."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text():
            return path.read_text()
        time.sleep(0.005)
    raise AssertionError('Child did not publish sentinel: ' + str(path))


def _assert_stopped(pid):
    """Accept reaped processes or init-owned zombies, but never live descendants."""
    stat = Path('/proc') / str(pid) / 'stat'
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            state = stat.read_text().split(') ', 1)[1].split()[0]
        except FileNotFoundError:
            return
        if state == 'Z':
            return  # Grandchildren are reaped by their new parent, not this API.
        time.sleep(0.005)
    raise AssertionError(f'Process {pid} remains live')


def _cli(root, args, raw=None, timeout=10):
    """Run the public module router outside the checkout with isolated history."""
    env = dict(os.environ, HOME=str(root / 'home'), TMPDIR='/tmp/opencode',
               PYTHONPATH=_util.REPO_ROOT)
    return subprocess.run([sys.executable, '-m', 'lammpkeeper', 'run'] + args,
                          input=raw, capture_output=True, text=True, cwd=root,
                          env=env, timeout=timeout)


def test_local_job_real_backend_parity_and_snapshot_isolation():
    """Match synchronous arithmetic and keep detached terminal snapshots stable."""
    _util.require_numpy()
    from lammpkeeper.execution import execute_request
    from lammpkeeper.jobs import start_job
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        path = Path(tmp) / 'input.log'
        path.write_text('units metal\nrun 2\nStep Temp\n0 2\n1 4\n2 6\n')
        request = _request(path)
        expected = execute_request(request)
        job = start_job(request, python=sys.executable)
        snapshot = job.wait(15)
        assert snapshot['state'] == 'succeeded', snapshot
        assert snapshot['backend_response']['result'] == expected['result']
        assert [event['state'] for event in snapshot['events']] == [
            'created', 'handshaking', 'running', 'succeeded']
        snapshot['events'].clear()
        snapshot['backend_response']['result'].clear()
        assert job.cancel() == job.snapshot()
        assert job.wait(0)['backend_response']['result'] == expected['result']
        assert len(job.snapshot()['events']) == 4
        json.dumps(job.snapshot(), allow_nan=False)


def test_default_interpreter_committed_fixture_parity_and_foreign_child_versions():
    """Preserve Fe-O results by default and allow reported child ecosystem versions."""
    _util.require_numpy()
    from lammpkeeper.execution import execute_request
    from lammpkeeper.jobs import start_job
    request = _request(Path(_util.FIXTURE).with_name('log.lammps'))
    expected = execute_request(request)
    with patch.dict(os.environ):
        os.environ.pop('LKPR_PYTHON', None)
        snapshot = start_job(request).wait(15)
    assert snapshot['state'] == 'succeeded', snapshot
    assert snapshot['backend_response'] == expected
    assert snapshot['interpreter']['source'] == 'sys.executable'
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        handshake = ("cap['provenance']['python_version'] = 'different-child-python'\n"
                     "cap['provenance']['numpy_version'] = 'different-child-numpy'")
        execution = ("response['provenance']['python_version'] = 'different-child-python'\n"
                     "response['provenance']['numpy_version'] = 'different-child-numpy'")
        snapshot = start_job(_request(), python=_fake(root, handshake, execution)).wait(5)
        assert snapshot['state'] == 'succeeded', snapshot
        assert snapshot['handshake']['numpy_version'] == 'different-child-numpy'
        assert snapshot['backend_response']['provenance']['python_version'] == 'different-child-python'


def test_interpreter_precedence_missing_empty_and_no_fallback():
    """Honor explicit/env/default selection and retain failures instead of retrying."""
    from lammpkeeper.jobs import start_job
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        fake = _fake(root)
        with patch.dict(os.environ, {'LKPR_PYTHON': fake}):
            snapshot = start_job(_request()).wait(5)
            assert snapshot['state'] == 'succeeded', snapshot
            assert snapshot['interpreter'] == {'source': 'LKPR_PYTHON', 'requested': fake, 'executable': fake}
            for explicit in ('', '/missing/explicit-python', 'does-not-exist-exec2'):
                snapshot = start_job(_request(), python=explicit).wait(0)
                assert snapshot['state'] == 'failed'
                assert snapshot['error']['code'] == 'invalid_interpreter'
                assert snapshot['interpreter']['source'] == 'explicit'
        for value in ('', '/missing/env-python'):
            with patch.dict(os.environ, {'LKPR_PYTHON': value}):
                snapshot = start_job(_request()).wait(0)
                assert snapshot['error']['code'] == 'invalid_interpreter'
                assert snapshot['interpreter']['source'] == 'LKPR_PYTHON'
        with patch.dict(os.environ, {'LKPR_PYTHON': '/missing/env-python'}):
            assert start_job(_request(), python=fake).wait(5)['state'] == 'succeeded'


def test_interpreter_symlink_launch_path_is_not_dereferenced():
    """Preserve a real Python symlink path, including virtualenv-style bin paths."""
    from lammpkeeper.jobs import start_job
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        binary = root / 'venv with spaces' / 'bin' / 'python'
        binary.parent.mkdir(parents=True)
        binary.symlink_to(sys.executable)
        log = root / 'input.log'
        log.write_text('units metal\nStep Temp\n0 2\n')
        snapshot = start_job(_request(log), python=str(binary)).wait(15)
        assert snapshot['state'] == 'succeeded', snapshot
        assert snapshot['interpreter']['executable'] == str(binary)
        assert snapshot['handshake']['python_executable'] == str(binary)
        assert snapshot['backend_response']['provenance']['python_executable'] == str(binary)


def test_submission_freezes_request_cwd_environment_and_path_lookup():
    """Use one frozen context for both children despite later caller mutation."""
    from lammpkeeper.jobs import start_job
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        work = root / 'work'
        work.mkdir()
        release = root / 'release'
        fake = _fake(root, handshake="while not (root / 'release').exists():\n    time.sleep(0.005)",
                     execution="assert os.environ['EXEC2_SENTINEL'] == 'original'\nassert os.getcwd() == str(root / 'work')")
        request = _request('original.log')
        caller = os.getcwd()
        try:
            os.chdir(root)
            with patch.dict(os.environ, {'PATH': str(root), 'EXEC2_SENTINEL': 'original'}):
                job = start_job(request, python=Path(fake).name, cwd='work')
                _await_file(root / 'handshake.started')
                request['request_id'] = 'mutated'
                request['input']['log'] = 'mutated.log'
                os.environ['EXEC2_SENTINEL'] = 'mutated'
                os.environ['PATH'] = '/nonexistent'
                os.chdir(work)
                release.touch()
                snapshot = job.wait(5)
            assert snapshot['state'] == 'succeeded', snapshot
            assert snapshot['cwd'] == str(work)
            assert json.loads((root / 'received.json').read_text()) == _request('original.log')
        finally:
            release.touch()
            os.chdir(caller)


def test_relative_interpreter_is_relative_to_caller_not_job_cwd():
    """Resolve an explicit relative executable before switching the child directory."""
    from lammpkeeper.jobs import start_job
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        (root / 'work').mkdir()
        _fake(root, name='python-local')
        caller = os.getcwd()
        try:
            os.chdir(root)
            snapshot = start_job(_request(), python='./python-local', cwd='work').wait(5)
        finally:
            os.chdir(caller)
        assert snapshot['state'] == 'succeeded', snapshot
        assert snapshot['interpreter']['executable'] == str(root / 'python-local')


def test_handshake_rejects_incompatible_or_incomplete_backend_before_execution():
    """Never launch the operation after incompatible discovery or foreign identity."""
    from lammpkeeper.jobs import start_job
    changes = ["cap['result']['protocol_versions'] = [2]",
               "cap['result']['protocol_versions'] = [True]",
               "cap['result']['operations'] = {}",
               "cap['result']['operations']['thermo.summary']['versions'] = [2]",
               "cap['result']['operations']['thermo.summary']['versions'] = [True]",
               "cap['provenance']['package_version'] = 'incompatible'",
               "del cap['provenance']['numpy_version']",
               "cap['provenance']['python_executable'] = '/foreign/python'",
               "cap['operation'] = 'foreign'", "cap['operation_version'] = True",
               "cap['request_id'] = 'foreign'",
               "cap['status'] = 'failed'; cap['result'] = None; cap['error'] = {'code': 'missing', 'message': 'missing backend'}",
               "os.write(1, b'not a backend'); sys.exit(1)"]
    for change in changes:
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
            root = Path(tmp)
            fake = _fake(root, handshake=change)
            snapshot = start_job(_request(), python=fake).wait(5)
            assert snapshot['state'] == 'failed', (change, snapshot)
            assert snapshot['backend_response'] is None
            assert not (root / 'execution.started').exists(), change


def test_result_rejects_foreign_versions_identity_status_exit_and_provenance():
    """Do not retain malformed results, even if they claim scientific success."""
    from lammpkeeper.jobs import start_job
    changes = ["response['request_id'] = 'foreign'", "response['operation'] = 'foreign'",
               "response['protocol_version'] = 2", "response['protocol_version'] = True",
               "response['operation_version'] = 1.0", "response['operation_version'] = False",
               "response['status'] = 'cancelled'", "response['extra'] = 1",
               "response['error'] = {'code': 'x', 'message': 'x'}",
               "response['result']['sample_count'] = True",
               "response['result']['statistics']['step']['mean'] = False",
               "response['provenance']['numpy_version'] = 'changed'",
               "response['provenance']['python_version'] = 'changed'",
               "response['provenance']['python_executable'] = '/foreign/python'",
               "response['provenance']['package_version'] = 'changed'",
               "print(json.dumps(response), flush=True); sys.exit(1)",
               "response.update(status='failed', result=None, error={'code': 'x', 'message': 'x'}); print(json.dumps(response), flush=True); sys.exit(0)",
               "response.update(status='failed', result=None, error={'code': 'x', 'message': 'x'}); print(json.dumps(response), flush=True); sys.exit(2)"]
    for change in changes:
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
            root = Path(tmp)
            snapshot = start_job(_request(), python=_fake(root, execution=change)).wait(5)
            assert snapshot['state'] == 'failed', (change, snapshot)
            assert snapshot['backend_response'] is None, (change, snapshot)
            assert snapshot['error']['code'] in ('invalid_response', 'incompatible_backend')


def test_strict_output_json_rejects_duplicates_nonfinite_utf8_and_extra_values():
    """Enforce one strict UTF-8 result for both discovery and execution streams."""
    from lammpkeeper.jobs import start_job
    outputs = [b'{"x": 1, "x": 2}', b'{"x": NaN}', b'{"x": Infinity}',
               b'{"x": 1e9999}', b'{}\n{}', b'\xff', b'[]', b'null', b'']
    for phase in ('handshake', 'execution'):
        for raw in outputs:
            with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
                root = Path(tmp)
                code = 'os.write(1, ' + repr(raw) + '); sys.exit(0)'
                snapshot = start_job(_request(), python=_fake(root, **{phase: code})).wait(5)
                assert snapshot['state'] == 'failed', (phase, raw, snapshot)
                assert snapshot['error']['code'] == 'invalid_response'
                assert snapshot['backend_response'] is None


def test_genuine_failed_backend_envelope_and_error_are_preserved():
    """Retain a validated exit-1 failure without converting it to transport success."""
    from lammpkeeper.jobs import start_job
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        code = "response.update(status='failed', result=None, error={'code': 'invalid_input', 'message': 'synthetic input rejected'})"
        snapshot = start_job(_request(), python=_fake(root, execution=code)).wait(5)
        assert snapshot['state'] == 'failed', snapshot
        assert snapshot['cleanup'] == {'status': 'complete', 'reaped': True, 'error': None}
        assert snapshot['error'] == snapshot['backend_response']['error']
        assert snapshot['error']['code'] == 'invalid_input'


def test_child_crash_and_non_executable_import_failure_are_visible():
    """Map sudden process death and interpreter import failure to local failure."""
    from lammpkeeper.jobs import start_job
    for phase in ('handshake', 'execution'):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
            root = Path(tmp)
            code = 'os.kill(os.getpid(), signal.SIGKILL)'
            snapshot = start_job(_request(), python=_fake(root, **{phase: code})).wait(5)
            assert snapshot['state'] == 'failed', snapshot
            assert snapshot['error']['code'] == 'child_crash', snapshot
            assert snapshot['backend_response'] is None
            _assert_stopped(int((root / (phase + '.started')).read_text()))
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        wrapper = root / 'missing backend python'
        wrapper.write_text('#!' + sys.executable + '\n' +
                           'import json, os, pathlib, sys\n' +
                           'pathlib.Path(' + repr(str(root / 'invocation.json')) +
                           ').write_text(json.dumps(sys.argv[1:]))\n' +
                           'os.execv(sys.executable, [sys.executable, "-S"] + sys.argv[1:])\n')
        wrapper.chmod(0o755)
        snapshot = start_job(_request(), python=str(wrapper), cwd=str(root)).wait(5)
        assert snapshot['state'] == 'failed', snapshot
        assert snapshot['backend_response'] is None
        assert 'No module named' in snapshot['diagnostics']['handshake'], snapshot
        assert json.loads((root / 'invocation.json').read_text()) == [
            '-m', 'lammpkeeper', 'exec', '--capabilities']


def test_stdout_and_stderr_limits_fail_bounded_without_pipe_deadlock():
    """Independently reject excessive streams while draining both concurrently."""
    from lammpkeeper.jobs import MAX_STREAM_BYTES, start_job
    codes = ["os.write(1, b'x' * (1024 * 1024 + 65536))",
             "os.write(2, b'x' * (1024 * 1024 + 65536))",
             "for _ in range(40):\n    os.write(1, b'x' * 32768)\n    os.write(2, b'y' * 32768)"]
    for phase in ('handshake', 'execution'):
        for code in codes:
            with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
                root = Path(tmp)
                start = time.monotonic()
                snapshot = start_job(_request(), python=_fake(root, **{phase: code})).wait(5)
                assert snapshot['state'] == 'failed', snapshot
                assert snapshot['error']['code'] == 'output_limit', snapshot
                assert snapshot['backend_response'] is None
                assert len(snapshot['diagnostics'][phase]) <= 1024 < MAX_STREAM_BYTES
                assert time.monotonic() - start < 5


def test_large_stderr_before_stdin_read_and_bounded_request_do_not_deadlock():
    """Pump output before the backend consumes a request larger than a pipe buffer."""
    from lammpkeeper.jobs import start_job
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        fake = _fake(root, handshake="os.write(2, b'h' * 262144)",
                     before_read="os.write(2, b'e' * 262144)")
        request = _request('\U0001f680' * 4096)
        snapshot = start_job(request, python=fake).wait(5)
        assert snapshot['state'] == 'succeeded', snapshot
        assert len(snapshot['diagnostics']['handshake']) == 1024
        assert len(snapshot['diagnostics']['execution']) == 1024
        assert json.loads((root / 'received.json').read_text()) == request


def test_request_byte_bound_and_unsupported_platform_fail_without_spawning():
    """Enforce the shared byte limit and refuse missing process-group guarantees."""
    from lammpkeeper.jobs import start_job
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        fake = _fake(root)
        with patch('lammpkeeper.jobs.execution.MAX_REQUEST_BYTES', 32):
            snapshot = start_job(_request(), python=fake).wait(0)
        assert snapshot['state'] == 'failed'
        assert '32 bytes' in snapshot['error']['message']
        with patch('lammpkeeper.jobs.os.name', 'unsupported'):
            snapshot = start_job(_request(), python=fake).wait(0)
        assert snapshot['error']['code'] == 'unsupported_platform'
        assert not (root / 'handshake.started').exists()


def test_timeout_validation_and_wait_limit_does_not_cancel():
    """Reject invalid deadlines while keeping caller wait limits non-destructive."""
    from lammpkeeper.jobs import start_job
    for timeout in (True, False, 0, -1, float('inf'), float('nan'), '1', None):
        snapshot = start_job(_request(), timeout=timeout).wait(0)
        assert snapshot['state'] == 'failed', (timeout, snapshot)
        assert snapshot['backend_response'] is None
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        fake = _fake(root, handshake='signal.pause()')
        job = start_job(_request(), python=fake, timeout=10)
        _await_file(root / 'handshake.started')
        try:
            job.wait(0)
        except TimeoutError:
            pass
        else:
            raise AssertionError('Active job wait did not expire')
        assert job.snapshot()['state'] == 'handshaking'
        assert job.snapshot()['cleanup'] == {'status': 'pending', 'reaped': False, 'error': None}
        job.cancel()
        assert job.wait(5)['state'] == 'cancelled'


def test_overall_timeout_includes_handshake_and_execution_and_reaps():
    """Use one monotonic job deadline across both subprocess phases.

    REV-TEST-2: reaching the execution child needs two interpreter startups
    (measured 0.25-0.30 s unloaded), so the former fixed 0.3 s budget sometimes
    expired during handshake and the execution case never started. Budgets now
    leave over a second for startup. The execution case spends most of its
    budget in a slow handshake: one shared deadline stops near ``timeout``,
    while a fresh per-phase timer could not stop before handshake delay plus
    ``timeout``, which exceeds the elapsed bound.
    """
    from lammpkeeper.jobs import start_job
    cases = (('handshake', 1.5, {'handshake': 'signal.pause()'}, 3.5),
             ('execution', 3.0, {'handshake': 'time.sleep(1.5)',
                                 'execution': 'signal.pause()'}, 4.4))
    for phase, timeout, code, bound in cases:
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
            root = Path(tmp)
            fake = _fake(root, **code)
            started = time.monotonic()
            snapshot = start_job(_request(), python=fake, timeout=timeout).wait(10)
            elapsed = time.monotonic() - started
            assert snapshot['state'] == 'timed_out', snapshot
            assert snapshot['error']['code'] == 'timed_out'
            assert snapshot['backend_response'] is None
            sentinel = root / (phase + '.started')
            # A missing sentinel means the budget ended before this phase began:
            # report the startup budget, not a misleading FileNotFoundError.
            assert sentinel.exists(), f'{phase} never started within {timeout} s'
            assert timeout <= elapsed < bound, (phase, timeout, elapsed)
            _assert_stopped(int(sentinel.read_text()))


def test_cancel_both_phases_idempotence_and_terminal_snapshot_immutability():
    """Accept owner cancellation once and publish no stale success after cleanup."""
    from lammpkeeper.jobs import start_job
    for phase in ('handshake', 'execution'):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
            root = Path(tmp)
            job = start_job(_request(), python=_fake(root, **{phase: 'signal.pause()'}))
            _await_file(root / (phase + '.started'))
            job.cancel()
            job.cancel()
            snapshot = job.wait(5)
            assert snapshot['state'] == 'cancelled', snapshot
            assert snapshot['backend_response'] is None
            assert job.cancel() == snapshot == job.wait(0) == job.snapshot()
            assert [event['sequence'] for event in snapshot['events']] == list(range(1, len(snapshot['events']) + 1))
            assert len(snapshot['events']) <= 4
            assert [event['elapsed_seconds'] for event in snapshot['events']] == sorted(event['elapsed_seconds'] for event in snapshot['events'])
            _assert_stopped(int((root / (phase + '.started')).read_text()))


def test_cancel_kills_ignoring_descendants_that_hold_pipes_after_leader_exit():
    """Escalate against the original process group even when its leader has exited."""
    from lammpkeeper.jobs import start_job
    descendant = ("import os, pathlib, signal; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                  "pathlib.Path(%r).write_text(str(os.getpid())); signal.pause()")
    for phase in ('handshake', 'execution'):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
            root = Path(tmp)
            child_code = descendant % str(root / 'descendant.pid')
            code = ("signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                    "subprocess.Popen([" + repr(sys.executable) + ", '-c', " + repr(child_code) + "])\n"
                    "while not (root / 'descendant.pid').exists():\n    time.sleep(0.005)\n"
                    "signal.pause()")
            job = start_job(_request(), python=_fake(root, **{phase: code}))
            descendant_pid = int(_await_file(root / 'descendant.pid'))
            job.cancel()
            snapshot = job.wait(5)
            assert snapshot['state'] == 'cancelled', snapshot
            _assert_stopped(descendant_pid)
            _assert_stopped(int((root / (phase + '.started')).read_text()))
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        child_code = descendant % str(root / 'descendant.pid')
        code = ("subprocess.Popen([" + repr(sys.executable) + ", '-c', " + repr(child_code) + "])\n"
                "while not (root / 'descendant.pid').exists():\n    time.sleep(0.005)")
        snapshot = start_job(_request(), python=_fake(root, execution=code)).wait(5)
        assert snapshot['state'] == 'succeeded', snapshot
        _assert_stopped(int((root / 'descendant.pid').read_text()))


def test_leader_pid_is_reserved_until_last_group_signal_then_fully_reaped():
    """Prevent PID/group-ID reuse by inspecting exit without prematurely reaping."""
    from lammpkeeper import jobs
    observed = []
    original = jobs._signal_group
    def observe_signal(process, sig):
        """Require the leader to remain waitable throughout normal group cleanup."""
        info = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        if info is not None:
            observed.append(process.pid)
        return original(process, sig)
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        with patch('lammpkeeper.jobs._signal_group', side_effect=observe_signal):
            snapshot = jobs.start_job(_request(), python=_fake(root)).wait(5)
        assert snapshot['state'] == 'succeeded', snapshot
        assert len(set(observed)) == 2  # Capability and operation leaders.
        for pid in set(observed):
            try:
                os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            except ChildProcessError:
                pass
            else:
                raise AssertionError('Terminal publication preceded leader reaping')


def test_cancellation_deadline_race_and_late_success_cannot_change_terminal_state():
    """Linearize cancellation before deadline and reject cancellation after expiry."""
    from lammpkeeper.jobs import start_job
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        fake = _fake(root, handshake='signal.pause()')
        job = start_job(_request(), python=fake, timeout=10)
        _await_file(root / 'handshake.started')
        with job._lock:
            job._deadline = time.monotonic() - 1
            job.cancel()
        assert job.wait(5)['state'] == 'timed_out'
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        job = start_job(_request(), python=_fake(root, handshake='signal.pause()'))
        _await_file(root / 'handshake.started')
        with job._lock:
            job.cancel()
            job._deadline = time.monotonic() - 1
        snapshot = job.wait(5)
        assert snapshot['state'] == 'cancelled', snapshot
        assert snapshot['backend_response'] is None


def test_cancel_or_timeout_before_result_commit_discards_validated_success():
    """Place a deterministic barrier immediately before successful publication."""
    from lammpkeeper import jobs
    original = jobs._validate_result
    for action in ('cancel', 'timeout'):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
            root = Path(tmp)
            reached = threading.Event()
            release = threading.Event()
            def hold_result(*args):
                """Validate the real envelope, then let the owner win the commit race."""
                response = original(*args)
                reached.set()
                assert release.wait(5), 'Owner did not release result-validation barrier'
                return response
            with patch('lammpkeeper.jobs._validate_result', side_effect=hold_result):
                job = jobs.start_job(_request(), python=_fake(root))
                try:
                    assert reached.wait(5), job.snapshot()
                    if action == 'cancel':
                        job.cancel()
                    else:
                        with job._lock:
                            job._deadline = time.monotonic() - 1
                finally:
                    release.set()
                snapshot = job.wait(5)
            assert snapshot['state'] == ('cancelled' if action == 'cancel' else 'timed_out'), snapshot
            assert snapshot['backend_response'] is None
            assert job.cancel() == snapshot


def test_overall_deadline_is_not_reset_between_child_phases():
    """Check the same captured deadline survives discovery and operation startup."""
    from lammpkeeper.jobs import start_job
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        fake = _fake(root, handshake="while not (root / 'release').exists():\n    time.sleep(0.005)",
                     execution='signal.pause()')
        job = start_job(_request(), python=fake, timeout=10)
        try:
            _await_file(root / 'handshake.started')
            deadline = job._deadline
            (root / 'release').touch()
            _await_file(root / 'execution.started')
            assert job._deadline == deadline
        finally:
            job.cancel()
            job.wait(5)


def test_invalid_request_is_reused_validation_and_never_spawns():
    """Reuse EXEC-1 request validation before any backend capability probe."""
    from lammpkeeper.jobs import start_job
    invalid = [None, {}, dict(_request(), protocol_version=True),
               dict(_request(), operation_version=2), dict(_request(), parameters={'x': 1})]
    for request in invalid:
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
            root = Path(tmp)
            snapshot = start_job(request, python=_fake(root)).wait(0)
            assert snapshot['state'] == 'failed', snapshot
            assert not (root / 'handshake.started').exists()
    with patch('lammpkeeper.jobs.execution._validate', side_effect=ValueError('shared schema sentinel')):
        snapshot = start_job(_request()).wait(0)
    assert snapshot['error']['message'] == 'shared schema sentinel'


def test_concurrent_jobs_have_unique_ids_even_for_same_request_identity():
    """Keep lifecycle ownership independent from reusable scientific request IDs."""
    from lammpkeeper.jobs import start_job
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        fake = _fake(root)
        jobs = [start_job(_request(), python=fake) for _ in range(3)]
        snapshots = [job.wait(5) for job in jobs]
        assert all(snapshot['state'] == 'succeeded' for snapshot in snapshots), snapshots
        assert len({snapshot['job_id'] for snapshot in snapshots}) == 3
        assert {snapshot['request_id'] for snapshot in snapshots} == {'local-A'}


def test_cli_one_json_snapshot_events_stderr_and_structured_argument_errors():
    """Keep final stdout machine-readable on success, failure and invalid options."""
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        fake = _fake(root)
        proc = _cli(root, ['--request', '-', '--python', fake, '--events'], json.dumps(_request()))
        assert proc.returncode == 0, proc.stderr + proc.stdout
        snapshot = json.loads(proc.stdout)
        assert snapshot['state'] == 'succeeded'
        assert snapshot['cleanup'] == {'status': 'complete', 'reaped': True, 'error': None}
        assert len(proc.stdout.splitlines()) == 1
        assert [json.loads(line) for line in proc.stderr.splitlines()] == snapshot['events']
        assert not (root / 'home').exists()
        for args, raw in [([], None), (['--unknown'], None),
                          (['--request', '-', '--timeout', 'nan'], json.dumps(_request())),
                          (['--request', '-', '--timeout', 'no'], json.dumps(_request())),
                          (['--request', '-', '--python', ''], json.dumps(_request())),
                          (['--request', '-'], '{"x": 1, "x": 2}'),
                          (['--request', '/does/not/exist'], None)]:
            proc = _cli(root, args, raw)
            assert proc.returncode == 1, (args, proc.stdout, proc.stderr)
            snapshot = json.loads(proc.stdout)
            assert snapshot['state'] == 'failed', snapshot
            assert snapshot['cleanup'] == {'status': 'not_required', 'reaped': None, 'error': None}
            assert snapshot['backend_response'] is None
        help_result = _cli(root, ['--help'])
        assert help_result.returncode == 0 and 'usage:' in help_result.stdout


def test_cli_ctrl_c_cancels_owned_job_and_emits_final_snapshot():
    """Handle SIGINT with bounded process-group cleanup and final JSON exit 130."""
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        fake = _fake(root, execution='signal.pause()')
        request_path = root / 'request.json'
        request_path.write_text(json.dumps(_request()))
        env = dict(os.environ, HOME=str(root / 'home'), TMPDIR='/tmp/opencode',
                   PYTHONPATH=_util.REPO_ROOT)
        proc = subprocess.Popen([sys.executable, '-m', 'lammpkeeper', 'run',
                                 '--request', str(request_path), '--python', fake, '--events'],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=env, cwd=root)
        try:
            pid = int(_await_file(root / 'execution.started'))
            proc.send_signal(signal.SIGINT)
            stdout, stderr = proc.communicate(timeout=5)
            assert proc.returncode == 130, stdout + stderr
            snapshot = json.loads(stdout)
            assert snapshot['state'] == 'cancelled', snapshot
            assert snapshot['backend_response'] is None
            assert [json.loads(line) for line in stderr.splitlines()] == snapshot['events']
            _assert_stopped(pid)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)


def test_cli_ctrl_c_during_submission_does_not_lose_the_started_handle():
    """Defer interruption across thread creation and assignment to avoid orphan work."""
    from lammpkeeper import jobs
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        fake = _fake(root, handshake='signal.pause()')
        path = root / 'request.json'
        path.write_text(json.dumps(_request()))
        owned = []
        original = jobs.start_job
        def interrupt_submission(*args, **kwargs):
            """Deliver SIGINT after a live handle exists but before its caller owns it."""
            job = original(*args, **kwargs)
            owned.append(job)
            os.kill(os.getpid(), signal.SIGINT)
            return job
        output = io.StringIO()
        try:
            with patch('lammpkeeper.jobs.start_job', side_effect=interrupt_submission):
                with contextlib.redirect_stdout(output):
                    status = jobs.main(['--request', str(path), '--python', fake])
            snapshot = json.loads(output.getvalue())
            assert status == 130
            assert snapshot['job_id'] == owned[0].snapshot()['job_id']
            assert snapshot['state'] == 'cancelled', snapshot
            assert owned[0].wait(0) == snapshot
        finally:
            for job in owned:
                job.cancel()
                job.wait(5)


def test_cancel_and_timeout_retain_cleanup_failure_without_stale_success():
    """Keep failed reap confirmation visible independently of the terminal race."""
    from lammpkeeper import jobs
    original = jobs._cleanup
    for phase in ('handshake', 'execution'):
        for action in ('cancel', 'timeout'):
            with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
                root = Path(tmp)
                fake = _fake(root, **{phase: 'signal.pause()'})
                def fail_confirmation(process):
                    """Reap the real child first, then safely simulate a cleanup failure."""
                    original(process)
                    is_handshake = '--capabilities' in process.args
                    if is_handshake == (phase == 'handshake'):
                        raise jobs._JobError('cleanup_failed', 'synthetic reap failure ' + 'x' * 2048)
                with patch('lammpkeeper.jobs._cleanup', side_effect=fail_confirmation):
                    job = jobs.start_job(_request(), python=fake)
                    pid = int(_await_file(root / (phase + '.started')))
                    if action == 'cancel':
                        job.cancel()
                    else:
                        with job._lock:
                            job._deadline = time.monotonic() - 1
                    snapshot = job.wait(5)
                expected = 'cancelled' if action == 'cancel' else 'timed_out'
                assert snapshot['state'] == expected, snapshot
                assert snapshot['error']['code'] == expected, snapshot
                assert snapshot['cleanup']['status'] == 'failed', snapshot
                assert snapshot['cleanup']['reaped'] is False, snapshot
                assert snapshot['cleanup']['error']['code'] == 'cleanup_failed'
                assert snapshot['cleanup']['error']['message'].startswith('synthetic reap failure')
                assert len(snapshot['cleanup']['error']['message']) <= 1024
                assert snapshot['backend_response'] is None
                assert sum(event['state'] in jobs.TERMINAL_STATES for event in snapshot['events']) == 1
                assert snapshot == job.snapshot() == job.cancel() == job.wait(0)
                _assert_stopped(pid)


def test_cleanup_group_signal_errors_are_bounded_and_reaping_is_still_attempted():
    """Report signal and reap failures using a safe harness with no actual process."""
    from lammpkeeper import jobs
    class UnreapableProcess:
        """Model an unconfirmable child without creating or signalling any OS PID."""

        def __init__(self):
            """Track the bounded reap attempt independently of group signalling."""
            self.waits = []

        def wait(self, timeout):
            """Simulate the OS failing to confirm reaping within its finite budget."""
            self.waits.append(timeout)
            raise subprocess.TimeoutExpired('safe synthetic process', timeout)

    process = UnreapableProcess()
    with patch('lammpkeeper.jobs._signal_group', side_effect=PermissionError('synthetic signal denied')) as signals:
        try:
            jobs._cleanup(process)
        except jobs._JobError as exc:
            assert exc.code == 'cleanup_failed'
            assert 'synthetic signal denied' in exc.message
            assert 'reap' in exc.message.lower()
            assert len(exc.message) <= 1024
        else:
            raise AssertionError('Failed group signalling/reaping was not reported')
    assert [call.args[1] for call in signals.call_args_list] == [signal.SIGTERM, signal.SIGKILL]
    assert process.waits == [jobs.KILL_WAIT]


def test_cleanup_oserror_is_retained_in_snapshot_after_cancellation():
    """Preserve OS cleanup diagnostics even when cancellation sets the primary error."""
    from lammpkeeper import jobs
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        original = jobs._cleanup
        def fail_os_confirmation(process):
            """Avoid leaking children while injecting an OS-level cleanup failure."""
            original(process)
            raise PermissionError('synthetic process-group access failure')
        with patch('lammpkeeper.jobs._cleanup', side_effect=fail_os_confirmation):
            job = jobs.start_job(_request(), python=_fake(root, handshake='signal.pause()'))
            pid = int(_await_file(root / 'handshake.started'))
            job.cancel()
            snapshot = job.wait(5)
        assert snapshot['state'] == 'cancelled'
        assert snapshot['cleanup']['status'] == 'failed', snapshot
        assert snapshot['cleanup']['error']['code'] == 'cleanup_failed'
        assert 'synthetic process-group access failure' in snapshot['cleanup']['error']['message']
        assert snapshot['backend_response'] is None
        _assert_stopped(pid)


def test_fingerprint_rejects_non_ascii_or_invalid_signed_decimal_strings():
    """Accept only ASCII stat identifiers with one optional minus for mtime_ns."""
    from lammpkeeper import jobs
    malformed = [('mtime_ns', '--1'), ('mtime_ns', '\u0661'),
                 ('mtime_ns', '+1'), ('mtime_ns', '-\u0661'),
                 ('inode', '-1'), ('device', '-1'),
                 ('inode', '\u0661'), ('device', '\uff11'),
                 ('inode', ''), ('device', '--1')]
    for field, value in malformed:
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
            root = Path(tmp)
            code = "response['provenance']['input_fingerprint'][%r] = %r" % (field, value)
            snapshot = jobs.start_job(_request(), python=_fake(root, execution=code)).wait(5)
            assert snapshot['state'] == 'failed', (field, value, snapshot)
            assert snapshot['error']['code'] == 'invalid_response', snapshot
            assert snapshot['backend_response'] is None
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        code = "response['provenance']['input_fingerprint']['mtime_ns'] = '-1'"
        snapshot = jobs.start_job(_request(), python=_fake(root, execution=code)).wait(5)
        assert snapshot['state'] == 'succeeded', snapshot


def test_cli_ctrl_c_cleanup_wait_timeout_emits_honest_nonterminal_json():
    """Emit exit-130 JSON without falsely completing a supervisor still in cleanup."""
    from lammpkeeper import jobs
    with tempfile.TemporaryDirectory(dir='/tmp/opencode') as tmp:
        root = Path(tmp)
        fake = _fake(root, handshake='signal.pause()')
        request_path = root / 'request.json'
        request_path.write_text(json.dumps(_request()))
        owned = []
        reached = threading.Event()
        release = threading.Event()
        original_start = jobs.start_job
        original_cleanup = jobs._cleanup
        original_wait = jobs.LocalJob.wait
        def hold_cleanup(process):
            """Clean real children, then model an outstanding OS confirmation call."""
            original_cleanup(process)
            reached.set()
            assert release.wait(5), 'Owner did not release safe cleanup barrier'

        def interrupt_submission(*args, **kwargs):
            """Interrupt only after a real child exists and the CLI will own its handle."""
            job = original_start(*args, **kwargs)
            owned.append(job)
            _await_file(root / 'handshake.started')
            os.kill(os.getpid(), signal.SIGINT)
            return job

        def expire_cleanup_wait(self, timeout=None):
            """Force the CLI's bounded cleanup wait to expire while cleanup is pending."""
            if timeout is not None and timeout > 1:
                assert reached.wait(5), 'Supervisor did not enter safe cleanup barrier'
                raise TimeoutError('synthetic CLI cleanup wait expired')
            return original_wait(self, timeout)

        output, errors = io.StringIO(), io.StringIO()
        try:
            with patch('lammpkeeper.jobs.start_job', side_effect=interrupt_submission):
                with patch('lammpkeeper.jobs._cleanup', side_effect=hold_cleanup):
                    with patch.object(jobs.LocalJob, 'wait', expire_cleanup_wait):
                        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                            status = jobs.main(['--request', str(request_path), '--python', fake, '--events'])
            snapshot = json.loads(output.getvalue())
            assert status == 130
            assert len(output.getvalue().splitlines()) == 1
            assert snapshot['job_id'] == owned[0].snapshot()['job_id']
            assert snapshot['state'] not in jobs.TERMINAL_STATES, snapshot
            assert snapshot['cleanup']['status'] == 'incomplete', snapshot
            assert snapshot['cleanup']['reaped'] is False
            assert snapshot['cleanup']['error']['code'] == 'cleanup_wait_timeout'
            assert snapshot['error']['code'] == 'cleanup_wait_timeout'
            assert snapshot['backend_response'] is None
            assert not owned[0]._done.is_set()
            assert [json.loads(line) for line in errors.getvalue().splitlines()] == snapshot['events']
        finally:
            release.set()
            for job in owned:
                job.cancel()
                original_wait(job, 5)
