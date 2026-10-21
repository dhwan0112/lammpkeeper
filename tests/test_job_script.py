"""HPC-1: the generated PBS run script must never lose results.

Runs the generated script locally with stub mpirun/cp/lmp on PATH:
- copy succeeds   -> exit 0, results (incl. dotfiles) copied back, scratch removed
- copy-back fails -> exit nonzero, scratch kept, its path printed
- scratch cannot be created/entered -> exit nonzero

The scratch root is redirected with LKPR_SCRATCH so the test never touches
the real /hpctmp. LAMMPS input generation is not exercised here.
"""
import os
import stat
import subprocess
import tempfile

import _util  # noqa: F401  (path bootstrap)
from _util import skip


def _render():
    from lammps_pre.state import PreState
    from lammps_pre.templates import render_run_script
    from lammps_pre.writers import get_filenames
    s = PreState()
    return render_run_script(None, s), get_filenames(s), s


def _stub(path, body):
    with open(path, 'w') as f:
        f.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)


def _run_case(fail_copy_back=False, scratch_blocked=False):
    script, names, _ = _render()
    root = tempfile.mkdtemp(prefix='lkpr_hpc_')
    work = os.path.join(root, 'work')
    stubbin = os.path.join(root, 'bin')
    os.makedirs(work)
    os.makedirs(stubbin)
    import re
    required = re.search(r'required_files="([^"]*)"', script).group(1).split()
    for name in [names['input']] + required:
        with open(os.path.join(work, name), 'w') as f:
            f.write('dummy\n')
    _stub(os.path.join(stubbin, 'mpirun'),
          '#!/bin/bash\n'
          'echo result > result.txt\n'
          'echo hidden > .hidden_result\n'
          'exit ${STUB_MPI_EXIT:-0}\n')
    _stub(os.path.join(stubbin, 'lmp'), '#!/bin/bash\nexit 0\n')
    _stub(os.path.join(stubbin, 'cp'),
          '#!/bin/bash\n'
          'for last; do :; done\n'
          'if [ -n "${FAIL_CP_DEST:-}" ] && [ "$last" = "$FAIL_CP_DEST" ]; then exit 1; fi\n'
          'exec /bin/cp "$@"\n')
    script_path = os.path.join(root, 'run.sh')
    with open(script_path, 'w') as f:
        f.write(script)
    scratch = os.path.join(root, 'scratch')
    env = dict(os.environ)
    env.update({
        'PATH': stubbin + ':/usr/bin:/bin',
        'PBS_O_WORKDIR': work,
        'PBS_JOBID': 'testjob',
        'LKPR_SCRATCH': scratch,
        'HOME': root,
    })
    if fail_copy_back:
        env['FAIL_CP_DEST'] = work + '/'
    if scratch_blocked:
        blocker = os.path.join(root, 'blocker')
        with open(blocker, 'w') as f:
            f.write('not a directory')
        env['LKPR_SCRATCH'] = os.path.join(blocker, 'sub')
        scratch = env['LKPR_SCRATCH']
    proc = subprocess.run(['bash', script_path], env=env, cwd=work,
                          capture_output=True, text=True, timeout=120)
    return proc, work, scratch


def test_generated_script_passes_bash_syntax_check():
    script, _, _ = _render()
    with tempfile.NamedTemporaryFile('w', suffix='.sh', delete=False) as f:
        f.write(script)
        path = f.name
    proc = subprocess.run(['bash', '-n', path], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_copy_success_removes_scratch_and_keeps_dotfiles():
    proc, work, scratch = _run_case()
    assert proc.returncode == 0, proc.stdout
    assert os.path.exists(os.path.join(work, 'result.txt'))
    assert os.path.exists(os.path.join(work, '.hidden_result')), 'dotfiles were not copied back'
    assert not os.path.exists(scratch), 'scratch kept after successful copy'


def test_copy_failure_keeps_scratch_and_exits_nonzero():
    proc, work, scratch = _run_case(fail_copy_back=True)
    assert proc.returncode != 0, proc.stdout
    assert os.path.exists(os.path.join(scratch, 'result.txt')), 'scratch was deleted after failed copy'
    assert scratch in proc.stdout, 'scratch path not printed'


def test_scratch_failure_exits_nonzero():
    proc, work, scratch = _run_case(scratch_blocked=True)
    assert proc.returncode != 0, proc.stdout
