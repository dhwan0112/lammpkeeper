"""REV-PREP-1: bounded, local execution of rendered copyback control flow.

These filesystem regressions do not validate MPI, LAMMPS, or HPC site setup.
Only test-copy site initialization and the default scratch path are replaced.
Every executed script uses a disposable home, trusted local launchers, and a
scratch-removal guard. Concurrent mutation, hard links, and mount aliases are
outside this regression contract.
"""
import contextlib
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import _util  # noqa: F401 (path bootstrap)
from lammps_pre.state import PreState
from lammps_pre.templates import render_run_script
from lammps_pre.writers import get_filenames


PAYLOADS = {
    'trajectory.out': b'trajectory payload\n',
    '.restart.hidden': b'hidden restart payload\n',
    'nested/frame.out': b'nested payload\n',
    '.hidden-output/frame.out': b'hidden directory payload\n',
}


def _executable(path, body):
    """Create a disposable Bash stub, never a real solver or MPI executable."""
    path.write_text('#!/bin/bash\nset -eu\n' + body)
    path.chmod(0o755)


def _isolated_render(state, root):
    """Redirect only the rendered test copy's site setup and default scratch."""
    text = render_run_script(None, state)
    site = 'source /etc/profile.d/modules.sh 2>/dev/null || true'
    default = '/hpctmp/$USER/$JOBID'
    assert text.count(site) == text.count(default) == 1
    text = text.replace(site, ': # test only: no site initialization')
    text = text.replace(default, str(root / 'unused default scratch'))
    assert '/hpctmp/' not in text and 'source /etc/profile.d/' not in text
    return text


@contextlib.contextmanager
def _job(seed=None, extra='', status=0, copy_failure=False, work_mode=0o700,
         work_link=False, work_suffix=''):
    """Run the complete rendered script with a strict temp-only command harness."""
    with tempfile.TemporaryDirectory(prefix='lkpr_copyback_') as tmp:
        root = Path(tmp)
        work, home, bins = (root / name for name in ('work with spaces', 'home', 'bin'))
        for path in (work, home, bins):
            path.mkdir()
        work.chmod(work_mode)
        submission = root / 'submission link' if work_link else work
        if work_link:
            submission.symlink_to(work, target_is_directory=True)
        scratch = root / 'scratch with spaces'
        events = root / 'events'
        archive = work / 'failed_copyback-job'
        state = PreState()
        state.set_ff('ace')
        state.lammps_bin = str(bins / 'lmp')
        names = get_filenames(state)
        staged = (names['input'], names['data'], names['regions'],
                  state.ff['potential_file'])
        inputs = {name: ('staged input: ' + name + '\n').encode() for name in staged}
        for name, content in inputs.items():
            (work / name).write_bytes(content)
        job = SimpleNamespace(root=root, work=work, submission=submission,
                              scratch=scratch, archive=archive, inputs=inputs)
        if seed:
            seed(job)
        payload_commands = []
        for name, content in PAYLOADS.items():
            parent = str(Path(name).parent)
            payload_commands.extend((
                'mkdir -p -- ' + shlex.quote(parent),
                'printf %s ' + shlex.quote(content.decode()) + ' > ' + shlex.quote(name)))
        _executable(bins / 'module', 'exit 0\n')
        _executable(bins / 'lmp',
                    'printf "FORBIDDEN SOLVER EXECUTION\\n" >> "$TEST_EVENTS"\nexit 99\n')
        _executable(bins / 'mpirun', '\n'.join(payload_commands) + '\n' + extra +
                    '\nprintf "solver-stub\\n" >> "$TEST_EVENTS"\nexit "$TEST_STATUS"\n')
        _executable(bins / 'cp', '''
dest="${!#}"
if [[ "${dest%/}" != "$LKPR_SCRATCH" ]]; then
    printf 'result-copy\n' >> "$TEST_EVENTS"
    if [[ "$TEST_COPY_FAILURE" == 1 ]]; then
        printf 'injected result copy failure\n' >&2
        exit 72
    fi
fi
exec /bin/cp "$@"
''')
        _executable(bins / 'rm', '''
[[ "$#" == 3 && "$1" == -rf && "$2" == -- && "$3" == "$LKPR_SCRATCH" ]] || exit 98
[[ "$LKPR_SCRATCH" == "$TEST_ROOT/scratch with spaces" && ! -L "$LKPR_SCRATCH" ]] || exit 98
printf 'scratch-cleanup\n' >> "$TEST_EVENTS"
exec /bin/rm "$@"
''')
        env = {
            'HOME': str(home), 'USER': 'copyback-only', 'PATH': str(bins) + ':/bin',
            'BASH_ENV': '/dev/null', 'PBS_O_WORKDIR': str(submission) + work_suffix,
            'PBS_JOBID': 'copyback-job', 'LKPR_SCRATCH': str(scratch),
            'TEST_ROOT': str(root), 'TEST_EVENTS': str(events), 'TEST_STATUS': str(status),
            'TEST_COPY_FAILURE': str(int(copy_failure)), 'LKPR_NO_HISTORY': '1',
        }
        text = _isolated_render(state, root)
        script = root / 'run.sh'
        script.write_text(text)
        syntax = subprocess.run(['/bin/bash', '-n', str(script)], env=env,
                                capture_output=True, text=True, timeout=10)
        assert syntax.returncode == 0, syntax.stderr
        job.result = subprocess.run(['/bin/bash', str(script)], cwd=work, env=env,
                                    capture_output=True, text=True, timeout=15)
        job.log = job.result.stdout + job.result.stderr
        job.events = events.read_text() if events.exists() else ''
        assert 'FORBIDDEN SOLVER EXECUTION' not in job.events, job.log
        assert 'solver-stub\n' in job.events, job.log
        yield job


def _assert_payloads(destination, inputs=None):
    """Verify all generated bytes, including hidden output and staged inputs."""
    for name, content in dict(PAYLOADS, **(inputs or {})).items():
        assert (destination / name).read_bytes() == content, name


def _assert_retained(job, unsafe=None, status=1, no_copy=True):
    """Require complete scratch, visible recovery paths, and no success/cleanup."""
    assert job.result.returncode == status, job.log
    assert job.scratch.is_dir(), job.log
    _assert_payloads(job.scratch, job.inputs)
    assert 'Success:' not in job.log and 'COPY_OK=1' not in job.log, job.log
    assert str(job.scratch) in job.log and 'kept' in job.log.lower(), job.log
    assert 'scratch-cleanup\n' not in job.events, job.events
    if no_copy:
        assert 'result-copy\n' not in job.events, job.events
    if unsafe is not None:
        assert str(unsafe) in job.log, 'diagnostic omitted unsafe path: ' + job.log


def _collision(name, kind='absolute', directory=False, extra=''):
    """Seed a link collision and verify link identity and separate target bytes."""
    def seed(job):
        """Create only disposable collision paths and record the original link identity."""
        target = job.root / 'unrelated target'
        if directory:
            target.mkdir()
            (target / 'sentinel').write_bytes(b'unrelated directory bytes\x00\n')
        elif kind != 'dangling':
            target.write_bytes(b'unrelated file bytes\x00\n')
        unsafe = job.work / name
        unsafe.parent.mkdir(parents=True, exist_ok=True)
        link = os.path.relpath(target, unsafe.parent) if kind == 'relative' else str(target)
        unsafe.symlink_to(link, target_is_directory=directory)
        job.unsafe, job.target, job.link = unsafe, target, link
        job.identity = unsafe.lstat().st_ino
    with _job(seed=seed, extra=extra) as job:
        _assert_retained(job, job.unsafe)
        assert job.unsafe.is_symlink()
        assert os.readlink(job.unsafe) == job.link
        assert job.unsafe.lstat().st_ino == job.identity
        if directory:
            assert sorted(p.name for p in job.target.iterdir()) == ['sentinel']
            assert (job.target / 'sentinel').read_bytes() == b'unrelated directory bytes\x00\n'
        elif kind == 'dangling':
            assert not job.target.exists(), 'copyback created a dangling link target'
        else:
            assert job.target.read_bytes() == b'unrelated file bytes\x00\n'


def test_rev_prep_1_copyback_must_not_follow_destination_symlink():
    """Rendered copyback must preserve a separate target and retain recoverable output."""
    import test_job_script_safety as safety

    original = safety._executable
    original_run = subprocess.run

    def install(path, text):
        """Seed the staged failing repro and add a strict local cleanup guard."""
        if path.name == 'mpirun':
            text = ('printf "unrelated original\\n" > "$PBS_O_WORKDIR/../unrelated-target"\n'
                    'ln -s -- "$PBS_O_WORKDIR/../unrelated-target" '
                    '"$PBS_O_WORKDIR/trajectory.out"\n' + text)
        elif path.name == 'rm':
            text = ('[[ "$#" == 3 && "$1" == -rf && "$2" == -- && '
                    '"$3" == "$TEST_SCRATCH" && ! -L "$3" ]] || exit 98\n' + text)
        elif path.name == 'lmp':
            text = 'echo "FORBIDDEN SOLVER EXECUTION" >&2; exit 99\n'
        original(path, text)

    def isolated_run(*args, **kwargs):
        """Keep the reused helper on trusted PATH and disable inherited Bash setup."""
        env = dict(kwargs['env'])
        env['PATH'] = env['PATH'].split(':')[0] + ':/bin'
        env['BASH_ENV'] = '/dev/null'
        kwargs['env'] = env
        return original_run(*args, **kwargs)

    with patch.object(safety, '_executable', side_effect=install), \
            patch.object(safety.subprocess, 'run', side_effect=isolated_run):
        with safety._run_job() as job:
            target = job.work.parent / 'unrelated-target'
            assert target.read_text() == 'unrelated original\n', 'copyback overwrote symlink target'
            assert (job.work / 'trajectory.out').is_symlink()
            assert job.result.returncode != 0 and job.scratch.is_dir(), job.log
            assert 'Success:' not in job.log, job.log
            safety._assert_preserved(job)


def test_absolute_leaf_symlink_is_rejected_before_copy():
    """An absolute destination leaf link must not redirect a result overwrite."""
    _collision('trajectory.out')


def test_relative_leaf_symlink_is_rejected_before_copy():
    """A relative destination leaf link retains its exact stored target and bytes."""
    _collision('trajectory.out', kind='relative')


def test_dangling_leaf_symlink_is_rejected_before_copy():
    """A dangling leaf link is unsafe even though the destination does not exist."""
    _collision('trajectory.out', kind='dangling')


def test_top_level_directory_symlink_is_rejected_before_copy():
    """A source directory cannot be merged through a destination directory link."""
    _collision('nested', directory=True)


def test_nested_leaf_symlink_under_real_parent_is_rejected():
    """Preflight must recurse through matching real directories before any copy."""
    _collision('nested/frame.out', kind='relative')


def test_nested_directory_symlink_is_rejected():
    """A deeper directory collision cannot redirect recursively generated output."""
    _collision('nested/deeper', directory=True,
               extra='mkdir -p nested/deeper\nprintf "deep payload\\n" > nested/deeper/value\n')


def test_hidden_leaf_and_directory_symlinks_are_rejected():
    """Dotfile and hidden-directory collisions receive the same complete preflight."""
    for name, directory in (('.restart.hidden', False), ('.hidden-output', True),
                            ('.hidden-output/frame.out', False)):
        _collision(name, directory=directory)


def test_destination_root_symlink_is_rejected():
    """A symlink used as the destination root is refused without replacing it."""
    for suffix in ('', '/', '///', '/.', '/./', '/././//'):
        with _job(work_link=True, work_suffix=suffix) as job:
            _assert_retained(job, job.submission)
            assert job.submission.is_symlink()
            assert os.readlink(job.submission) == str(job.work)
            assert not (job.work / 'trajectory.out').exists()
            for name, content in job.inputs.items():
                assert (job.work / name).read_bytes() == content


def test_real_destination_root_accepts_trailing_slashes_and_dot():
    """Normal directory spellings still merge outputs without copying root modes."""
    for suffix in ('/', '///', '/.', '/./', '/././//'):
        with _job(work_suffix=suffix) as job:
            assert job.result.returncode == 0, job.log
            _assert_payloads(job.work, job.inputs)
            assert job.work.stat().st_mode & 0o7777 == 0o700
            assert not job.scratch.exists()
            assert 'Success:' in job.log


def test_late_collision_preflights_all_children_before_first_copy():
    """A late nested collision leaves earlier ordinary destination bytes untouched."""
    def seed(job):
        """Place an early ordinary output before a late, nested unsafe destination."""
        (job.work / '000-earlier-output').write_bytes(b'old ordinary bytes\x00\n')
        (job.work / 'zzz-late').mkdir()
        target = job.root / 'late target'
        target.write_bytes(b'late target original\n')
        (job.work / 'zzz-late' / 'last').symlink_to(target)
    extra = ('printf "new ordinary bytes\\n" > 000-earlier-output\n'
             'mkdir zzz-late\nprintf "new late bytes\\n" > zzz-late/last\n')
    with _job(seed=seed, extra=extra) as job:
        _assert_retained(job, job.work / 'zzz-late' / 'last')
        assert (job.work / '000-earlier-output').read_bytes() == b'old ordinary bytes\x00\n'
        assert (job.root / 'late target').read_bytes() == b'late target original\n'
        assert (job.scratch / '000-earlier-output').read_bytes() == b'new ordinary bytes\n'
        assert (job.scratch / 'zzz-late' / 'last').read_bytes() == b'new late bytes\n'


def test_source_symlinks_are_copied_without_traversal():
    """Source links, including a cyclic directory target, remain ordinary artifacts."""
    def seed(job):
        """Keep a cyclic source-link target outside scratch with independent bytes."""
        target = job.root / 'source link target'
        target.mkdir()
        (target / 'sentinel').write_bytes(b'external original\n')
        (target / 'cycle').symlink_to(target, target_is_directory=True)
    extra = ('ln -s -- "$TEST_ROOT/source link target" artifact-link\n'
             'ln -s -- "$TEST_ROOT/missing source target" dangling-artifact\n')
    with _job(seed=seed, extra=extra) as job:
        assert job.result.returncode == 0, job.log
        assert (job.work / 'artifact-link').is_symlink()
        assert os.readlink(job.work / 'artifact-link') == str(job.root / 'source link target')
        assert (job.work / 'dangling-artifact').is_symlink()
        assert not (job.root / 'missing source target').exists()
        assert (job.root / 'source link target' / 'sentinel').read_bytes() == b'external original\n'
        assert not job.scratch.exists()


def test_unrelated_destination_links_do_not_block_success():
    """Noncolliding destination links at top level and in merged directories survive."""
    def seed(job):
        """Prepare noncolliding links whose names are absent from the source tree."""
        target = job.root / 'unrelated'
        target.write_bytes(b'unrelated original\n')
        (job.work / 'unrelated-link').symlink_to(target)
        (job.work / 'nested').mkdir()
        (job.work / 'nested' / 'unrelated-link').symlink_to('../missing-relative')
    with _job(seed=seed) as job:
        assert job.result.returncode == 0, job.log
        _assert_payloads(job.work, job.inputs)
        assert os.readlink(job.work / 'unrelated-link') == str(job.root / 'unrelated')
        assert os.readlink(job.work / 'nested' / 'unrelated-link') == '../missing-relative'
        assert (job.root / 'unrelated').read_bytes() == b'unrelated original\n'
        assert not job.scratch.exists()


def test_normal_overwrite_directory_merge_and_root_modes_are_preserved():
    """Normal archive-copy semantics retain unrelated entries and destination-root mode."""
    def seed(job):
        """Prepare overwrite targets and unrelated files in a real destination tree."""
        (job.work / 'trajectory.out').write_bytes(b'old trajectory\n')
        (job.work / 'nested').mkdir()
        (job.work / 'nested' / 'frame.out').write_bytes(b'old nested\n')
        (job.work / 'nested' / 'keep-existing').write_bytes(b'keep nested\n')
        (job.work / 'keep-existing').write_bytes(b'keep top\n')
    for mode in (0o700, 0o750, 0o2770):
        with _job(seed=seed, work_mode=mode) as job:
            assert job.result.returncode == 0, job.log
            _assert_payloads(job.work, job.inputs)
            assert job.work.stat().st_mode & 0o7777 == mode
            assert (job.work / 'nested' / 'keep-existing').read_bytes() == b'keep nested\n'
            assert (job.work / 'keep-existing').read_bytes() == b'keep top\n'
            assert not job.scratch.exists()
            assert 'Success:' in job.log


def test_unusual_names_copy_normally_and_collisions_remain_visible():
    """Spaces, leading dashes, and newlines must survive arrays and recursive paths."""
    for name in ('output with spaces', '-leading-output', 'line\nbreak-output'):
        extra = 'printf "unusual bytes\\n" > ' + shlex.quote(name) + '\n'
        with _job(extra=extra) as job:
            assert job.result.returncode == 0, job.log
            assert (job.work / name).read_bytes() == b'unusual bytes\n'
        _collision(name, extra=extra)


def test_solver_failure_uses_fresh_archive_and_preserves_status_37():
    """Successful failure recovery archives complete output and returns the solver status."""
    with _job(status=37) as job:
        assert job.result.returncode == 37, job.log
        _assert_payloads(job.archive, job.inputs)
        assert not job.scratch.exists()
        assert not (job.work / 'trajectory.out').exists()
        assert 'Success:' not in job.log and str(job.archive) in job.log


def test_existing_archives_are_never_reused_or_followed():
    """Existing real, linked, and dangling archives preserve prior state and solver status."""
    for kind in ('directory', 'symlink', 'dangling'):
        def seed(job):
            """Prepare one occupied archive without creating a missing link target."""
            target = job.root / 'archive target'
            if kind != 'dangling':
                target.mkdir()
                (target / 'prior').write_bytes(b'prior archive target\n')
            if kind == 'directory':
                job.archive.mkdir()
                (job.archive / 'prior').write_bytes(b'prior archive\n')
            else:
                job.archive.symlink_to(target, target_is_directory=True)
        with _job(seed=seed, status=37) as job:
            _assert_retained(job, job.archive, status=37)
            if kind == 'directory':
                assert sorted(p.name for p in job.archive.iterdir()) == ['prior']
                assert (job.archive / 'prior').read_bytes() == b'prior archive\n'
            else:
                assert job.archive.is_symlink()
                assert os.readlink(job.archive) == str(job.root / 'archive target')
            if kind != 'dangling':
                assert (job.root / 'archive target' / 'prior').read_bytes() == b'prior archive target\n'
            else:
                assert not (job.root / 'archive target').exists()


def test_copy_failure_after_safe_preflight_retains_complete_scratch():
    """An actual copy error cannot authorize cleanup or hide a nonzero solver status."""
    for status in (0, 37):
        with _job(status=status, copy_failure=True) as job:
            _assert_retained(job, status=status or 1, no_copy=False)
            assert 'result-copy\n' in job.events
            assert 'injected result copy failure' in job.log
            destination = job.archive if status else job.work
            assert not (destination / 'trajectory.out').exists()


def test_all_forcefields_render_valid_identical_copyback_control_flow():
    """All three force-field scripts parse as Bash and share the tested copyback tail."""
    with tempfile.TemporaryDirectory(prefix='lkpr_copyback_syntax_') as tmp:
        root = Path(tmp)
        home = root / 'home'
        home.mkdir()
        env = {'HOME': str(home), 'PATH': '/bin', 'BASH_ENV': '/dev/null'}
        tails = []
        for forcefield in ('ace', 'reaxff2010', 'reaxff2015'):
            state = PreState()
            state.set_ff(forcefield)
            rendered = _isolated_render(state, root)
            result = subprocess.run(['/bin/bash', '-n'], input=rendered, env=env,
                                    capture_output=True, text=True, timeout=10)
            assert result.returncode == 0, (forcefield, result.stderr)
            tails.append(rendered.split('EXIT_CODE=$?\n', 1)[1])
        assert tails[0] == tails[1] == tails[2]
