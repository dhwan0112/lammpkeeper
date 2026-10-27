"""HPC-1: execute rendered PBS scripts locally with injected I/O failures.

No scheduler, MPI, LAMMPS, NumPy, ASE or pytest is required. Only the rendered
test copy's scratch root and module initialization are substituted; production
site defaults remain untouched. Filesystem effects stay inside temporary directories.
"""
import contextlib
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace

import _util  # noqa: F401 (path bootstrap)
from lammps_pre.state import PreState
from lammps_pre.templates import render_run_script
from lammps_pre.writers import get_filenames


def _executable(path, text):
    """Install a local Bash stub, never a real scheduler or simulation executable."""
    path.write_text('#!/bin/bash\n' + text)
    path.chmod(0o755)


@contextlib.contextmanager
def _run_job(failure='', lammps_status=0):
    """Execute rendered Bash in an isolated tree with controlled command failures.

    Local PATH stubs exercise real shell branching without an HPC allocation;
    payload files and event logs independently reveal copy and cleanup order.
    """
    with tempfile.TemporaryDirectory(prefix='lkpr_hpc1_') as tmp:
        root = Path(tmp)
        # Spaces exercise quoting of scratch and copyback destinations.
        work = root / 'work directory'
        home = root / 'home'
        bin_dir = root / 'bin'
        for directory in (work, home, bin_dir):
            directory.mkdir()
        scratch_root = root / 'scratch root'
        scratch = scratch_root / 'test-user' / 'hpc1-job'
        archive = work / 'failed_hpc1-job'
        events = root / 'events.log'
        marker = root / 'mpirun.called'
        existing_target = scratch
        if failure in ('existing_scratch', 'symlink_scratch'):
            if failure == 'symlink_scratch':
                existing_target = root / 'unrelated existing directory'
                existing_target.mkdir()
                scratch.parent.mkdir(parents=True)
                scratch.symlink_to(existing_target, target_is_directory=True)
            else:
                scratch.mkdir(parents=True)
            (existing_target / 'previous-result').write_text('do not overwrite\n')

        state = PreState()
        state.lammps_bin = str(bin_dir / 'lmp')
        names = get_filenames(state)
        for name in (names['input'], names['data'], names['regions'],
                     state.ff['potential_file']):
            (work / name).write_text('staged input: ' + name + '\n')

        _executable(bin_dir / 'lmp', 'exit 0\n')
        # MPI is a payload-producing stub; no scheduler, real MPI or LAMMPS is invoked.
        _executable(bin_dir / 'module', 'exit 0\n')
        _executable(bin_dir / 'mpirun', '''
printf 'mpirun\\n' >> "$TEST_EVENTS"
printf '%s\\n' "$PWD" > "$TEST_MARKER"
printf 'trajectory payload\\n' > trajectory.out
printf 'hidden restart payload\\n' > .restart.hidden
mkdir -p nested .hidden-output
printf 'nested payload\\n' > nested/frame.out
printf 'hidden directory payload\\n' > .hidden-output/frame.out
exit "$TEST_LAMMPS_STATUS"
''')
        _executable(bin_dir / 'cp', '''
dest="${!#}"
dest="${dest%/}"
printf 'cp -> %s\\n' "$dest" >> "$TEST_EVENTS"
if [[ "$dest" == "$TEST_SCRATCH" ]]; then
    if [[ "$TEST_FAILURE" == stage_input_cp && "$1" == "$TEST_INPUT" ]] ||
       [[ "$TEST_FAILURE" == stage_required_cp && "$1" == "$TEST_REQUIRED" ]]; then
        echo "injected staging copy failure" >&2
        exit 71
    fi
elif [[ "$TEST_FAILURE" == partial_copyback ]]; then
    /bin/cp "$TEST_SCRATCH/trajectory.out" "$dest"/ || exit 77
    echo "injected partial result copy failure" >&2
    exit 72
elif [[ "$TEST_FAILURE" == copyback_cp || "$TEST_FAILURE" == archive_cp ]]; then
    echo "injected result copy failure" >&2
    exit 72
fi
exec /bin/cp "$@"
''')
        _executable(bin_dir / 'mkdir', '''
dest="${!#}"
dest="${dest%/}"
printf 'mkdir -> %s\\n' "$dest" >> "$TEST_EVENTS"
if [[ "$TEST_FAILURE" == stage_mkdir && "$dest" == "$TEST_SCRATCH" ]] ||
   [[ "$TEST_FAILURE" == stage_parent_mkdir && "$dest" == "${TEST_SCRATCH%/*}" ]] ||
   [[ "$TEST_FAILURE" == archive_mkdir && "$dest" == "$TEST_ARCHIVE" ]]; then
    echo "injected mkdir failure" >&2
    exit 73
fi
exec /bin/mkdir "$@"
''')
        _executable(bin_dir / 'rm', '''
printf 'rm\\n' >> "$TEST_EVENTS"
if [[ "$TEST_FAILURE" == cleanup_rm ]]; then
    echo "injected cleanup rm failure" >&2
    exit 75
fi
exec /bin/rm "$@"
''')
        # cd is a shell builtin, so inject its failure through Bash's startup file.
        bash_env = root / 'bash_env'
        bash_env.write_text('''
cd() {
    if [[ "$TEST_FAILURE" == stage_cd && "$1" == "$TEST_SCRATCH" ]]; then
        echo "injected cd failure" >&2
        return 74
    fi
    if [[ "$TEST_FAILURE" == cleanup_cd && "$PWD" == "$TEST_SCRATCH" &&
          "$1" != "$TEST_SCRATCH" ]]; then
        echo "injected cleanup cd failure" >&2
        return 76
    fi
    builtin cd "$@"
}
''')
        env = {
            'HOME': str(home), 'USER': 'test-user',
            'PATH': str(bin_dir) + ':/usr/bin:/bin',
            'PBS_O_WORKDIR': str(work), 'PBS_JOBID': 'hpc1-job',
            'LKPR_SCRATCH': str(scratch),
            'BASH_ENV': str(bash_env), 'TEST_FAILURE': failure,
            'TEST_LAMMPS_STATUS': str(lammps_status),
            'TEST_SCRATCH': str(scratch), 'TEST_ARCHIVE': str(archive),
            'TEST_INPUT': str(work / names['input']),
            'TEST_REQUIRED': str(work / names['regions']),
            'TEST_EVENTS': str(events), 'TEST_MARKER': str(marker),
        }
        if failure == 'relative_scratch':
            env['LKPR_SCRATCH'] = 'relative scratch'
        rendered = render_run_script(None, state)
        syntax = subprocess.run(['/bin/bash', '-n'], input=rendered, text=True,
                                capture_output=True, env=env, timeout=10)
        assert syntax.returncode == 0, syntax.stderr
        assert '/hpctmp/' in rendered, 'update test isolation for new scratch root'
        rendered = rendered.replace('/hpctmp/', str(scratch_root) + '/')
        # Only the test copy is redirected; production rendering and templates stay intact.
        rendered = rendered.replace(
            'source /etc/profile.d/modules.sh 2>/dev/null || true',
            ': # test-only: do not initialize site environment')
        script = root / 'run.sh'
        script.write_text(rendered)
        result = subprocess.run(['/bin/bash', str(script)], cwd=work, env=env,
                                text=True, capture_output=True, timeout=15)
        log = (work / 'run.log').read_text()
        yield SimpleNamespace(result=result, work=work, scratch=scratch,
                              archive=archive, marker=marker, log=log,
                              existing_target=existing_target,
                              events=events.read_text() if events.exists() else '')


def _assert_outputs(destination):
    """Verify exact payloads including dotfiles and nested hidden directories."""
    for name, payload in (
        ('trajectory.out', 'trajectory payload\n'),
        ('.restart.hidden', 'hidden restart payload\n'),
        ('nested/frame.out', 'nested payload\n'),
        ('.hidden-output/frame.out', 'hidden directory payload\n'),
    ):
        path = destination / name
        assert path.is_file(), f'missing copied output: {path}'
        assert path.read_text() == payload, f'corrupt output: {path}'


def _assert_preserved(job):
    """Failed recovery must retain complete scratch and report a recoverable error."""
    assert job.scratch.is_dir(), f'scratch deleted after failed copy: {job.log}'
    _assert_outputs(job.scratch)
    assert job.result.returncode != 0, f'failure reported as exit 0: {job.log}'
    assert 'Success:' not in job.log, job.log
    assert str(job.scratch) in job.log, 'recovery log must identify scratch path'
    assert 'preserv' in job.log.lower() or 'retain' in job.log.lower() or \
        'kept' in job.log.lower(), 'recovery log must say scratch was kept'


def test_success_copies_hidden_outputs_before_cleanup():
    """Only a complete successful copy permits deleting the simulation scratch."""
    with _run_job() as job:
        assert job.result.returncode == 0, job.log
        assert job.marker.read_text().strip() == str(job.scratch)
        _assert_outputs(job.work)
        assert not job.scratch.exists(), 'verified copy should allow scratch cleanup'
        assert 'Success:' in job.log, job.log


def test_successful_lammps_failed_copyback_preserves_scratch():
    """Simulation success cannot mask a failed result transfer or erase scratch."""
    with _run_job('copyback_cp') as job:
        assert job.marker.exists(), 'LAMMPS stub was not called'
        assert 'injected result copy failure' in job.log, job.log
        _assert_preserved(job)
        assert not (job.work / 'trajectory.out').exists()


def test_failed_lammps_archives_hidden_outputs_and_keeps_exit_status():
    """Successful failure-archiving retains all output and the simulator's status 37."""
    with _run_job(lammps_status=37) as job:
        assert job.result.returncode == 37, job.log
        _assert_outputs(job.archive)
        assert not job.scratch.exists(), 'successful archive should allow cleanup'
        assert 'Success:' not in job.log, job.log
        assert str(job.archive) in job.log, job.log
        assert not (job.work / 'trajectory.out').exists()


def test_partial_copyback_preserves_complete_scratch():
    """One transferred file is not proof that the remaining scratch is disposable."""
    with _run_job('partial_copyback') as job:
        assert 'injected partial result copy failure' in job.log, job.log
        _assert_preserved(job)
        assert (job.work / 'trajectory.out').read_text() == 'trajectory payload\n'
        assert not (job.work / '.restart.hidden').exists()


def test_relative_scratch_is_rejected_before_staging():
    """Relative scratch paths must fail before any staging or simulation launch."""
    with _run_job('relative_scratch') as job:
        assert job.result.returncode != 0, job.log
        assert 'scratch path must be absolute' in job.log, job.log
        assert not job.marker.exists()
        assert not (job.work / 'relative scratch').exists()
        assert not job.scratch.exists()


def test_failed_lammps_failed_archive_copy_preserves_scratch():
    """An archive copy error must preserve the only complete failed-run output."""
    with _run_job('archive_cp', lammps_status=37) as job:
        assert 'injected result copy failure' in job.log, job.log
        _assert_preserved(job)
        assert not (job.archive / 'trajectory.out').exists()


def test_failed_lammps_failed_archive_mkdir_preserves_scratch():
    """A missing archive destination prevents copy attempts and retains scratch."""
    with _run_job('archive_mkdir', lammps_status=37) as job:
        assert 'injected mkdir failure' in job.log, job.log
        _assert_preserved(job)
        assert not job.archive.exists()
        assert f'cp -> {job.archive}' not in job.events, job.events


def _assert_staging_failure(failure, message):
    """Require injected preparation errors to stop launch and leave a useful log."""
    with _run_job(failure) as job:
        assert message in job.log, job.log
        assert not job.marker.exists(), f'LAMMPS ran after {failure}: {job.log}'
        assert job.result.returncode != 0, job.log
        assert 'Success:' not in job.log, job.log
        assert (job.work / 'run.log').is_file()


def test_stage_mkdir_failure_prevents_lammps():
    """Failure to create the job scratch directory must stop simulation launch."""
    _assert_staging_failure('stage_mkdir', 'injected mkdir failure')


def test_stage_parent_mkdir_failure_prevents_lammps():
    """Failure to create the scratch parent is fatal before staging proceeds."""
    _assert_staging_failure('stage_parent_mkdir', 'injected mkdir failure')


def test_stage_input_copy_failure_prevents_lammps():
    """A missing staged input script must never be followed by an MPI launch."""
    _assert_staging_failure('stage_input_cp', 'injected staging copy failure')


def test_stage_required_copy_failure_prevents_lammps():
    """Failure copying required region data must stop the otherwise runnable job."""
    _assert_staging_failure('stage_required_cp', 'injected staging copy failure')


def test_stage_cd_failure_prevents_lammps():
    """A failed directory change must not run LAMMPS in the submission directory."""
    _assert_staging_failure('stage_cd', 'injected cd failure')


def _assert_existing_scratch_rejected(failure):
    """Reject occupied scratch while preserving prior bytes and symlink identity."""
    with _run_job(failure) as job:
        assert not job.marker.exists(), f'LAMMPS reused existing scratch: {job.log}'
        assert job.result.returncode != 0, job.log
        assert (job.existing_target / 'previous-result').read_text() == \
            'do not overwrite\n'
        assert sorted(path.name for path in job.existing_target.iterdir()) == \
            ['previous-result'], 'existing scratch contents were changed'
        assert 'Success:' not in job.log, job.log
        assert str(job.scratch) in job.log, 'rejection must identify scratch path'
        if failure == 'symlink_scratch':
            assert job.scratch.is_symlink(), 'pre-existing symlink was removed'


def test_existing_scratch_is_not_reused_or_deleted():
    """An existing directory belongs to prior work and must remain untouched."""
    _assert_existing_scratch_rejected('existing_scratch')


def test_symlink_scratch_is_not_followed_or_deleted():
    """A pre-existing symlink must neither redirect staging nor be removed."""
    _assert_existing_scratch_rejected('symlink_scratch')


def test_cleanup_rm_failure_returns_nonzero_and_keeps_copied_results():
    """Deletion failure remains visible even after results were safely copied."""
    with _run_job('cleanup_rm') as job:
        assert 'injected cleanup rm failure' in job.log, job.log
        assert job.result.returncode != 0, f'cleanup failure returned 0: {job.log}'
        _assert_outputs(job.work)
        _assert_outputs(job.scratch)
        assert str(job.scratch) in job.log, 'cleanup error must identify scratch'


def test_cleanup_cd_failure_keeps_scratch_without_attempting_rm():
    """Cleanup must not attempt deletion after failing to leave scratch."""
    with _run_job('cleanup_cd') as job:
        assert 'injected cleanup cd failure' in job.log, job.log
        assert job.result.returncode != 0, job.log
        _assert_outputs(job.work)
        _assert_outputs(job.scratch)
        assert 'rm\n' not in job.events, 'cleanup continued after failed cd'
        assert str(job.scratch) in job.log, 'cleanup error must identify scratch'
