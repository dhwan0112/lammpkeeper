"""AUDIT-20261027: verifier must not certify missing generated artifacts."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import _util  # noqa: F401


def _run_verifier(case, mode='full'):
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
                    'penetration', 'penetration_trend', 'oar', 'structure']
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
        env = dict(os.environ, PYTHON=str(fake), VERIFIER_CASE=case,
                   HOME=tmp, LKPR_VERIFY_DIR=str(Path(tmp) / 'evidence'))
        proc = subprocess.run(['bash', str(script), mode], cwd=checkout,
                              env=env, capture_output=True, text=True, timeout=30)
        summaries = list((Path(tmp) / 'evidence').glob('*/summary.txt'))
        assert len(summaries) == 1, proc.stdout + proc.stderr
        summary = summaries[0].read_text()
        if proc.returncode:
            summary += proc.stderr
            for filename in ('post.log', 'post-batch.log', 'post-summary.txt'):
                log = summaries[0].parent / filename
                if log.exists():
                    summary += '\n' + filename + ':\n' + log.read_text()
        return proc.returncode, summary


def test_verifier_rejects_empty_prep_output():
    code, summary = _run_verifier('empty_prep')
    assert code != 0 and 'FAIL prep' in summary, summary


def test_verifier_rejects_logged_prep_failure_even_with_zero_exit():
    code, summary = _run_verifier('logged_error')
    assert code != 0 and 'FAIL prep' in summary, summary


def test_verifier_rejects_zero_collected_tests():
    code, summary = _run_verifier('zero_tests')
    assert code != 0 and 'FAIL tests' in summary, summary


def test_verifier_rejects_missing_requested_plots():
    code, summary = _run_verifier('empty_post')
    assert code != 0 and 'FAIL post' in summary, summary


def test_verifier_rejects_partial_requested_plots():
    code, summary = _run_verifier('partial_post')
    assert code != 0 and 'FAIL post' in summary, summary


def test_verifier_requires_analysis_evidence_in_quick_mode():
    code, summary = _run_verifier('empty_quick', mode='quick')
    assert code != 0 and 'FAIL post' in summary, summary


def test_verifier_accepts_complete_nonempty_smoke_outputs():
    code, summary = _run_verifier('complete')
    assert code == 0 and 'PASS prep' in summary and 'PASS post' in summary, summary


def test_verifier_accepts_quick_analysis_evidence_without_requested_plots():
    code, summary = _run_verifier('complete', mode='quick')
    assert code == 0 and 'PASS post' in summary and 'FAIL' not in summary, summary
