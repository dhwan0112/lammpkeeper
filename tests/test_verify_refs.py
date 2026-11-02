"""Schema and coverage tests for the verify skill's reference checker (VERIFY-REF-2).

The checker (.claude/skills/verify/scripts/verify_refs.py) is a verifier: a
silent PASS on a broken or missing reference file is worse than a crash. These
tests load the script by path and point it at temporary reference directories,
so the committed references are never touched.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import tempfile

import _util

SCRIPT = os.path.join(_util.REPO_ROOT, '.claude', 'skills', 'verify', 'scripts', 'verify_refs.py')
REAL_REFS = os.path.join(_util.REPO_ROOT, '.claude', 'skills', 'verify', 'references')


def _load():
    """Import the checker script as a fresh module object."""
    spec = importlib.util.spec_from_file_location('verify_refs_under_test', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _good_spec(**over):
    """A minimal well-formed reference spec for the fake check id."""
    spec = {'id': 'fake-check', 'reference': {'a': 1.0}, 'kind': {'a': 'analytic'},
            'tolerance': {'a': {'abs': 1e-9}}}
    spec.update(over)
    return spec


@contextlib.contextmanager
def _refdir(mod, files, compute=None):
    """Temporary REF_DIR holding `files` ({name: json-able or raw str}); optional COMPUTE override."""
    tmp = tempfile.mkdtemp(prefix='lkpr-vr2-')
    saved = (mod.REF_DIR, dict(mod.COMPUTE))
    try:
        for name, body in files.items():
            with open(os.path.join(tmp, name), 'w') as fh:
                fh.write(body if isinstance(body, str) else json.dumps(body))
        mod.REF_DIR = tmp
        if compute is not None:
            mod.COMPUTE.clear()
            mod.COMPUTE.update(compute)
        yield tmp
    finally:
        mod.REF_DIR = saved[0]
        mod.COMPUTE.clear()
        mod.COMPUTE.update(saved[1])
        shutil.rmtree(tmp, ignore_errors=True)


def _main(mod, argv):
    """Run main() with stdout/stderr captured; return (exit code, stdout, evidence json or None)."""
    ev = tempfile.mkdtemp(prefix='lkpr-vr2-ev-')
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = mod.main(list(argv) + ['--evidence-dir', ev])
        results = None
        for root, _dirs, names in os.walk(ev):
            if 'results.json' in names:
                with open(os.path.join(root, 'results.json')) as fh:
                    results = json.load(fh)
        return code, out.getvalue() + err.getvalue(), results
    finally:
        shutil.rmtree(ev, ignore_errors=True)


def test_missing_reference_for_known_compute_id_is_error():
    """A COMPUTE id without a reference JSON must be a named ERROR with exit 1, not an inactive skip."""
    _util.require_numpy()
    mod = _load()
    only = 'analytic-msd'
    files = {n: json.load(open(os.path.join(REAL_REFS, n)))
             for n in os.listdir(REAL_REFS) if n.endswith('.json') and n != only + '.json'}
    with _refdir(mod, files):
        code, text, results = _main(mod, ['--only', only])
    assert code == 1, (code, text)
    rec = [r for r in results['results'] if r['id'] == only]
    assert rec and rec[0]['status'] == 'ERROR' and 'missing reference' in rec[0]['detail'], rec


def test_missing_reference_is_error_in_default_run_and_doctor_exit():
    """Without --only the missing id is still reported, and --doctor exits 2 instead of 0."""
    _util.require_numpy()
    mod = _load()
    files = {'analytic-msd.json': json.load(open(os.path.join(REAL_REFS, 'analytic-msd.json')))}
    with _refdir(mod, files):
        code, text, results = _main(mod, ['--only', 'analytic-msd', '--only', 'box-geometry'])
        assert code == 1, (code, text)
        status = {r['id']: r['status'] for r in results['results']}
        assert status == {'analytic-msd': 'PASS', 'box-geometry': 'ERROR'}, status
        dcode, dtext, _ = _main(mod, ['--doctor', '--only', 'analytic-msd'])
        assert dcode == 2, (dcode, dtext)
        assert 'MISSING reference (ERROR)' in dtext, dtext


def test_allowlisted_missing_reference_is_not_an_error():
    """An id listed in MISSING_REFERENCE_ALLOWED may lack a file; the allowlist ships empty."""
    _util.require_numpy()
    mod = _load()
    assert getattr(mod, 'MISSING_REFERENCE_ALLOWED', None) == {}, 'allowlist must ship empty'
    files = {'analytic-msd.json': json.load(open(os.path.join(REAL_REFS, 'analytic-msd.json')))}
    with _refdir(mod, files):
        mod.MISSING_REFERENCE_ALLOWED = {n: 'test' for n in mod.COMPUTE if n != 'analytic-msd'}
        code, text, results = _main(mod, [])
    assert code == 0, (code, text)
    assert [r['id'] for r in results['results']] == ['analytic-msd']


def test_json_without_compute_function_still_errors():
    """Guard: a reference file for an id with no compute function stays an ERROR."""
    mod = _load()
    with _refdir(mod, {'orphan.json': _good_spec(id='orphan')}, compute={}):
        specs = mod.load_specs()
        rec = mod.run_check(specs[0])
    assert rec['status'] == 'ERROR' and 'no compute function' in rec['detail'], rec


def test_empty_reference_is_schema_error():
    """`reference: {}` must not PASS with 'all 0 reference keys'."""
    mod = _load()
    errs = mod.spec_errors(_good_spec(reference={}, kind={}, tolerance={}))
    assert any('empty' in e for e in errs), errs
    with _refdir(mod, {}, compute={'fake-check': lambda: {}}):
        rec = mod.run_check(_good_spec(reference={}, kind={}, tolerance={}))
    assert rec['status'] == 'ERROR', rec


def test_missing_reference_key_is_schema_error_not_crash():
    """A spec with no `reference` key must give a schema error instead of a KeyError."""
    mod = _load()
    spec = {'id': 'fake-check', 'kind': {}}
    errs = mod.spec_errors(spec)
    assert any("'reference'" in e for e in errs), errs
    with _refdir(mod, {}, compute={'fake-check': lambda: {}}):
        rec = mod.run_check(spec)
    assert rec['status'] == 'ERROR', rec


def test_tolerance_for_unknown_key_is_schema_error():
    """A tolerance key that matches no reference key (typo) must be flagged."""
    mod = _load()
    errs = mod.spec_errors(_good_spec(tolerance={'a': {'abs': 1e-9}, 'b': {'abs': 1.0}}))
    assert any('tolerance given for unknown key' in e for e in errs), errs


def test_non_dict_sections_are_schema_errors():
    """Non-dict reference/kind/tolerance (and a non-dict file or tolerance entry) are rejected without raising."""
    mod = _load()
    for over in ({'reference': [1, 2]}, {'reference': 'x'}, {'kind': ['analytic']},
                 {'kind': 'analytic'}, {'tolerance': [1]}, {'tolerance': 0.1},
                 {'tolerance': {'a': 1e-9}}):
        errs = mod.spec_errors(_good_spec(**over))
        assert errs, over
    assert mod.spec_errors([1, 2]) and mod.spec_errors('x') and mod.spec_errors(None)


def test_bad_tolerance_fields_are_schema_errors():
    """Unknown tolerance field names and negative or non-numeric values are rejected."""
    mod = _load()
    for tol in ({'tol': 1e-3}, {'abs': -1.0}, {'abs': 'small'}, {'rel': True}):
        assert mod.spec_errors(_good_spec(tolerance={'a': tol})), tol


def test_well_formed_spec_has_no_errors():
    """Guard: the minimal good spec and every committed reference file validate cleanly."""
    mod = _load()
    assert mod.spec_errors(_good_spec()) == []
    for name in sorted(os.listdir(REAL_REFS)):
        if name.endswith('.json'):
            with open(os.path.join(REAL_REFS, name)) as fh:
                assert mod.spec_errors(json.load(fh)) == [], name


def test_unlisted_measured_key_is_error():
    """A key the compute function returns but the reference omits must turn the check into ERROR."""
    _util.require_numpy()
    mod = _load()
    compute = {'fake-check': lambda: {'a': 1.0, 'extra': 5}}
    with _refdir(mod, {}, compute=compute):
        rec = mod.run_check(_good_spec())
    assert rec['status'] == 'ERROR' and 'extra' in rec['detail'], rec
    assert rec['unlisted_measured_keys'] == ['extra'], rec


def test_matching_measured_keys_still_pass_and_compare_unchanged():
    """Guard: exact key coverage passes; one tolerance still applies to nested values."""
    _util.require_numpy()
    mod = _load()
    spec = _good_spec(reference={'a': {'x': [1.0, 2.0]}}, tolerance={'a': {'abs': 0.1}})
    with _refdir(mod, {}, compute={'fake-check': lambda: {'a': {'x': [1.05, 1.95]}}}):
        assert mod.run_check(spec)['status'] == 'PASS'
    with _refdir(mod, {}, compute={'fake-check': lambda: {'a': {'x': [1.05, 2.5]}}}):
        assert mod.run_check(spec)['status'] == 'FAIL'


def test_malformed_files_on_disk_become_errors_in_main():
    """Unparseable JSON, a non-object file and an empty reference all give ERROR results and exit 1."""
    _util.require_numpy()
    mod = _load()
    files = {'fake-a.json': '{not json', 'fake-b.json': '[1, 2]',
             'fake-c.json': {'id': 'fake-c', 'reference': {}, 'kind': {}}}
    compute = {k: (lambda: {}) for k in ('fake-a', 'fake-b', 'fake-c')}
    with _refdir(mod, files, compute=compute):
        code, text, results = _main(mod, [])
    assert code == 1, (code, text)
    assert {r['id']: r['status'] for r in results['results']} == {
        'fake-a': 'ERROR', 'fake-b': 'ERROR', 'fake-c': 'ERROR'}


def test_real_references_cover_every_compute_id():
    """Guard: the committed reference directory has one file per COMPUTE id and no allowlist entries."""
    mod = _load()
    have = {n[:-5] for n in os.listdir(REAL_REFS) if n.endswith('.json')}
    assert have == set(mod.COMPUTE), (sorted(have), sorted(mod.COMPUTE))
    assert not mod.MISSING_REFERENCE_ALLOWED
