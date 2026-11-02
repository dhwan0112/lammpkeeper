"""AUDIT-20261027: verifier must not certify missing generated artifacts."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import _util  # noqa: F401


def _run_verifier(case, mode='full', stubs=None, extra_env=None, details=None,
                  precreate=(), runs=1):
    """Run the real verifier against controlled subprocess outputs in a fake checkout.

    The embedded interpreter is a fault-injection fixture, not a solver or
    renderer: each case changes artifact presence or reported success while
    the verifier's own evidence checks remain real.
    Nonempty placeholder images and input files test artifact gates, not file
    validity or physics. The returned summary survives temporary cleanup; the
    fake checkout and its generated evidence files do not.

    ``stubs`` maps command names to shell bodies placed first on PATH to
    inject host faults (failing mktemp or cp); ``extra_env`` feeds them.
    Every fake-interpreter call is appended to a log through a wrapper so
    tests can prove which verifier steps ran. When ``details`` (a dict) is
    given it receives ``calls`` (interpreter argv lines), ``evidence`` (names
    of surviving evidence files) and ``stderr``.
    """
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='lkpr-verifier-') as tmp:
        checkout = Path(tmp) / 'checkout'
        script = checkout / '.cursor/skills/verify-lkpr/scripts/verify.sh'
        script.parent.mkdir(parents=True)
        shutil.copyfile(root / '.cursor/skills/verify-lkpr/scripts/verify.sh', script)
        fixture = checkout / 'tests/fixtures/ace_examples/regular_MD/traj.dump'
        fixture.parent.mkdir(parents=True)
        fixture.write_text('synthetic fixture; fake interpreter never reads it\n')
        fake = Path(tmp) / 'python'
        # Keep this embedded executable unchanged: the failure matrix depends
        # on its exact simulated commands, filenames and zero-exit omissions.
        fake.write_text('''#!/usr/bin/env python3
import os
from pathlib import Path
import sys
args = sys.argv[1:]
case = os.environ['VERIFIER_CASE']
if args == ['--version']:
    print('Python fake verifier fixture')
elif args and args[0] == '-c':
    pass
elif args == ['tests/run.py']:
    print('0 passed, 0 failed, 0 skipped' if case == 'zero_tests' else '1 passed, 0 failed, 0 skipped')
elif args[:3] == ['-m', 'lammpkeeper', 'post']:
    out = Path(args[args.index('--output') + 1])
    out.mkdir(parents=True, exist_ok=True)
    plots = ['density_profile.png', 'msd_Fe.png', 'o2_dissociation.png', 'oar.png',
             'penetration.png', 'penetration_trend.png', 'rdf_Fe_O.png', 'snapshots.png',
             'spin_evolution.png', 'structure.png']
    if case == 'partial_post':
        plots = ['msd_Fe.png']
    if case != 'empty_post':
        for name in plots:
            (out / name).write_bytes(b'fake image fixture')
    if '--batch' in args and case != 'empty_quick':
        sections = ['density_all', 'msd_Fe', 'rdf_Fe-O', 'spin', 'dissociation',
                    'penetration', 'penetration_trend', 'oar']
        (out / 'summary.txt').write_text('\\n'.join('--- ' + key + ' ---' for key in sections))
elif args[:3] == ['-m', 'lammpkeeper', 'prep']:
    out = Path(args[args.index('--write') + 1])
    out.mkdir(parents=True, exist_ok=True)
    if case != 'empty_prep':
        for name in ['ace_oxidation.in', 'lammps_ace.data', 'regions_ace.inc', 'structure.xyz', 'run.sh']:
            (out / name).write_text('#!/bin/bash\\ntrue\\n')
    if case == 'logged_error':
        print('Error: synthetic write failure')
else:
    raise SystemExit('unexpected fake interpreter arguments: ' + repr(args))
''')
        fake.chmod(0o755)
        # Route all verifier Python work to the fixture; isolate HOME and the
        # evidence directory so no real preparation or plot generation runs.
        calls = Path(tmp) / 'calls.log'
        wrapper = Path(tmp) / 'python-wrapper'
        wrapper.write_text('#!/bin/sh\necho "$*" >> "%s"\nexec "%s" "$@"\n' % (calls, fake))
        wrapper.chmod(0o755)
        env = dict(os.environ, PYTHON=str(wrapper), VERIFIER_CASE=case,
                   HOME=tmp, LKPR_VERIFY_DIR=str(Path(tmp) / 'evidence'))
        if stubs:
            stub_dir = Path(tmp) / 'stubbin'
            stub_dir.mkdir()
            for name, body in stubs.items():
                (stub_dir / name).write_text('#!/bin/sh\n' + body)
                (stub_dir / name).chmod(0o755)
            env['PATH'] = str(stub_dir) + os.pathsep + env['PATH']
            env['STUB_STATE'] = str(Path(tmp) / 'stub-state')
        env.update(extra_env or {})
        for rel in precreate:
            sentinel = Path(tmp) / 'evidence' / rel
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.write_text('sentinel\n')
        procs = [subprocess.Popen(['bash', str(script), mode], cwd=checkout, env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for _ in range(runs)]
        outs = [p.communicate(timeout=60) for p in procs]
        proc = subprocess.CompletedProcess(procs[0].args, procs[0].returncode, *outs[0])
        if details is not None:
            details['returncodes'] = [p.returncode for p in procs]
            details['calls'] = calls.read_text().splitlines() if calls.exists() else []
            details['stderr'] = proc.stderr
            dirs = Path(tmp) / 'stub-state.dirs'
            details['leftover_dirs'] = [d for d in (dirs.read_text().split() if dirs.exists() else [])
                                        if os.path.isdir(d)]
            details['evidence'] = sorted(p.name for p in (Path(tmp) / 'evidence').glob('*/*'))
        summaries = list((Path(tmp) / 'evidence').glob('*/summary.txt'))
        assert len(summaries) == runs, (proc.stdout, proc.stderr)
        if details is not None:
            details['summaries'] = sorted(str(x.parent.name) for x in summaries)
            details['stdout'] = proc.stdout
            details['sentinels'] = {rel: (Path(tmp) / 'evidence' / rel).read_text()
                                    if (Path(tmp) / 'evidence' / rel).exists() else None
                                    for rel in precreate}
        summary = summaries[0].read_text()
        if proc.returncode:
            summary += proc.stderr
            for filename in ('post.log', 'post-batch.log', 'post-summary.txt'):
                log = summaries[0].parent / filename
                if log.exists():
                    summary += '\n' + filename + ':\n' + log.read_text()
        return proc.returncode, summary


def test_verifier_rejects_empty_prep_output():
    """A zero-exit preparation command with no artifacts is not verification success."""
    code, summary = _run_verifier('empty_prep')
    assert code != 0 and 'FAIL prep' in summary, summary


def test_verifier_rejects_logged_prep_failure_even_with_zero_exit():
    """Logged write errors must fail verification even when files and exit zero exist."""
    code, summary = _run_verifier('logged_error')
    assert code != 0 and 'FAIL prep' in summary, summary


def test_verifier_rejects_zero_collected_tests():
    """An empty passing test run supplies no regression evidence and must fail."""
    code, summary = _run_verifier('zero_tests')
    assert code != 0 and 'FAIL tests' in summary, summary


def test_verifier_rejects_missing_requested_plots():
    """A nominally successful plot command must produce its requested artifacts."""
    code, summary = _run_verifier('empty_post')
    assert code != 0 and 'FAIL post' in summary, summary


def test_verifier_rejects_partial_requested_plots():
    """One nonempty plot cannot stand in for the complete requested plot set."""
    code, summary = _run_verifier('partial_post')
    assert code != 0 and 'FAIL post' in summary, summary


def test_verifier_requires_analysis_evidence_in_quick_mode():
    """Quick mode may omit images but cannot omit the requested analysis summary."""
    code, summary = _run_verifier('empty_quick', mode='quick')
    assert code != 0 and 'FAIL post' in summary, summary


def test_verifier_accepts_complete_nonempty_smoke_outputs():
    """The complete synthetic artifact set is a positive control for verifier checks."""
    code, summary = _run_verifier('complete')
    assert code == 0 and 'PASS prep' in summary and 'PASS post' in summary, summary


def test_verifier_accepts_quick_analysis_evidence_without_requested_plots():
    """A complete quick summary passes without requiring unrequested plot artifacts."""
    code, summary = _run_verifier('complete', mode='quick')
    assert code == 0 and 'PASS post' in summary and 'FAIL' not in summary, summary


# Fails the Nth mktemp call (STUB_FAIL_ON=all fails every call). Created
# directories are listed in $STUB_STATE.dirs so tests can check cleanup.
_MKTEMP_STUB = """n=$(cat "$STUB_STATE" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$STUB_STATE"
if [ "$STUB_FAIL_ON" = all ] || [ "$STUB_FAIL_ON" = "$n" ]; then echo 'mktemp: stub failure' >&2; exit 1; fi
d=$(/usr/bin/mktemp "$@") || exit 1
echo "$d" >> "$STUB_STATE.dirs"; echo "$d"
"""


def _assert_setup_refused(fail_on):
    """Run with a failing mktemp and assert the verifier stops before any work."""
    details = {}
    code, summary = _run_verifier('complete', mode='quick', stubs={'mktemp': _MKTEMP_STUB},
                                  extra_env={'STUB_FAIL_ON': fail_on}, details=details)
    assert code != 0, summary
    assert 'mktemp' in details['stderr'] and 'temporary' in details['stderr'], details['stderr']
    assert details['calls'] == [], details['calls']
    assert 'FAIL setup' in summary, summary
    return details


def test_verifier_refuses_to_run_when_mktemp_fails():
    """REV-VERIFY-1: no mktemp means no HOME/WORK, so no tests or post may run."""
    _assert_setup_refused('all')


def test_verifier_refuses_when_second_mktemp_fails_and_cleans_first():
    """REV-VERIFY-1: a failed WORK mktemp must remove the already-created TMPHOME."""
    details = _assert_setup_refused('2')
    assert details['leftover_dirs'] == [], details['leftover_dirs']


# Fails only when the destination (last argument) is post-summary.txt; every
# other copy is delegated to the real cp so the rest of the run is unchanged.
_CP_STUB = """for a; do last="$a"; done
case "$last" in */post-summary.txt) echo 'cp: stub denied' >&2; exit 1 ;; esac
exec /bin/cp "$@"
"""


def test_verifier_fails_when_post_summary_evidence_cannot_be_retained():
    """REV-VERIFY-3: a denied evidence copy must fail the run, not exit zero."""
    details = {}
    code, summary = _run_verifier('complete', mode='quick', stubs={'cp': _CP_STUB}, details=details)
    assert code != 0, summary
    assert 'FAIL evidence' in summary and 'post-summary.txt' in summary, summary
    assert 'post-summary.txt' not in details['evidence'], details['evidence']


# Freezes the verifier timestamp so every run in a test computes the same
# evidence stamp, which forces the same-second collision.
_DATE_STUB = "echo 20260101T000000\n"


def test_verifier_does_not_reuse_existing_evidence_directory():
    """REV-VERIFY-2: a pre-existing same stamp/SHA/mode directory must survive untouched."""
    details = {}
    first = '20260101T000000-nogit-quick/tests.log'
    code, summary = _run_verifier('complete', mode='quick', stubs={'date': _DATE_STUB},
                                  details=details, precreate=[first, '20260101T000000-2-nogit-quick/x.log'])
    assert code == 0, summary
    assert details['sentinels'][first] == 'sentinel\n', details['sentinels']
    assert details['summaries'] == ['20260101T000000-3-nogit-quick'], details['summaries']
    assert 'evidence: ' in details['stdout'] and '20260101T000000-3-nogit-quick' in details['stdout']


def test_verifier_concurrent_same_second_runs_keep_independent_evidence():
    """REV-VERIFY-2: simultaneous identical runs each retain their own summary."""
    details = {}
    code, summary = _run_verifier('complete', mode='quick', stubs={'date': _DATE_STUB},
                                  details=details, runs=3)
    assert details['returncodes'] == [0, 0, 0], details['returncodes']
    assert len(set(details['summaries'])) == 3, details['summaries']
    assert all(n.endswith('-nogit-quick') for n in details['summaries']), details['summaries']
