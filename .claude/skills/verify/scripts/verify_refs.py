#!/usr/bin/env python3
"""verify: run lkpr's real analysis code on small reference inputs and compare
the numbers with stored reference values inside stated tolerances.

Usage (from the repo root, always with an isolated HOME):
    HOME="$(mktemp -d)" python3 .claude/skills/verify/scripts/verify_refs.py           # all checks
    HOME="$(mktemp -d)" python3 .claude/skills/verify/scripts/verify_refs.py --doctor  # doctor only
    HOME="$(mktemp -d)" python3 .claude/skills/verify/scripts/verify_refs.py --only analytic-msd
    HOME="$(mktemp -d)" python3 .claude/skills/verify/scripts/verify_refs.py --list

Reference values live in ../references/<check-id>.json. A check runs only when
its JSON file exists; the compute functions below for ids without a JSON file
are inactive until the maintainer adds confirmed reference values.

Every reference key carries a `kind` that says what a PASS means:
    analytic  the value follows from a closed-form identity (independent standard)
    external  literature, crystallography or a database value (independent standard)
    fixture   a committed data file aggregated without this repository's code
    snapshot  this repository's own output at `baseline_commit`; PASS means
              "unchanged since that commit" (a regression check), not that the
              number is physically right.

Evidence is written to $LKPR_VERIFY_DIR (default ~/.cache/lkpr-verify) under
<timestamp>-<sha>-refs/: doctor.txt, results.json, summary.txt. Exit status is
1 if any check FAILs or ERRORs, 2 on usage or missing-fixture problems.
"""
import argparse
import contextlib
import datetime as _dt
import io
import json
import os
import platform
import subprocess
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
REF_DIR = os.path.join(SKILL_DIR, 'references')
REPO_ROOT = os.path.abspath(os.path.join(SKILL_DIR, '..', '..', '..'))
FIXTURE = os.path.join(REPO_ROOT, 'tests', 'fixtures', 'ace_examples', 'regular_MD', 'traj.dump')

os.environ.setdefault('LKPR_NO_HISTORY', '1')
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


# ── small helpers ──────────────────────────────────────────────────────────

def _git(*args):
    try:
        return subprocess.run(['git', *args], cwd=REPO_ROOT, capture_output=True,
                              text=True, timeout=20).stdout.strip()
    except Exception as exc:  # git missing or not a repo
        return f'<git unavailable: {exc}>'


def _have(module):
    try:
        __import__(module)
        return True
    except Exception:
        return False


@contextlib.contextmanager
def _quiet():
    """Make lkpr's shell treat stdin as empty and swallow its progress output."""
    saved = sys.stdin
    sys.stdin = io.StringIO('')
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            yield
    finally:
        sys.stdin = saved


def _load_fixture_state():
    """Load the ACE fixture through the same shell path real users take."""
    from lammps_post.shell import LammpsPostShell
    sh = LammpsPostShell()
    with _quiet():
        sh.do_load(f'dump {FIXTURE}')
    return sh.state


def _frame(rows, step=0, box=((0, 10), (0, 10), (0, 30))):
    import numpy as np
    return {'atoms': np.asarray(rows, dtype=float).reshape((-1, 5)),
            'box': np.asarray(box, dtype=float), 'timestep': step}


COL = {'id': 0, 'type': 1, 'x': 2, 'y': 3, 'z': 4}


# ── compute functions: one per check id, return {key: measured value} ─────

def compute_fixture_ace_bulk():
    import numpy as np
    from lammps_post import analysis as A
    from lammps_post.parsers import pbc_from_boundary
    s = _load_fixture_state()
    f, ci = s.dump_frames, s.dump_col_idx
    f0 = f[0]
    types = f0['atoms'][:, ci['type']]
    counts = {str(int(k)): int(v) for k, v in zip(*np.unique(types, return_counts=True))}
    box = np.asarray(f0['box'], float)
    spin = A.analyze_spin_evolution(f, ci, dt_fs=s.dt_fs)
    return {
        'n_frames': len(f),
        'n_atoms': int(f0['natoms']),
        'type_counts': counts,
        'box_lengths': (box[:, 1] - box[:, 0]).tolist(),
        'pbc': list(pbc_from_boundary(f.reader.boundary)),
        'first_timestep': int(f0['timestep']),
        'last_timestep': int(f[-1]['timestep']),
        'spin_n_up_min_max': [int(np.min(spin['n_up'])), int(np.max(spin['n_up']))],
        'spin_n_down_min_max': [int(np.min(spin['n_down'])), int(np.max(spin['n_down']))],
        'spin_n_o_min_max': [int(np.min(spin['n_o'])), int(np.max(spin['n_o']))],
        'spin_up_fraction': float(np.mean(spin['up_fraction'])),
        # Composition convention: types 1+2 are both Fe (type 2 is the ACE
        # 'Mn' proxy slot for Fe_down), so metal:O is 3:4 and type1:type2 is 1:2.
        'metal_to_o_ratio': (counts['1'] + counts['2']) / counts['3'],
        'type1_to_type2_ratio': counts['1'] / counts['2'],
    }


def compute_reference_crystal_fe3o4():
    import itertools
    import numpy as np
    from lammps_post.references import CRYSTAL_DB, compute_reference_rdf
    crystal = CRYSTAL_DB['Fe3O4']
    cell = np.asarray(crystal['cell'], float)
    fe = np.array([p for e, p in crystal['atoms'] if e == 'Fe']) @ cell
    ox = np.array([p for e, p in crystal['atoms'] if e == 'O']) @ cell
    # Direct image enumeration, independent of production MIC code.
    images = np.concatenate([ox + np.array(s) @ cell
                             for s in itertools.product((-1, 0, 1), repeat=3)])
    d = np.linalg.norm(fe[:, None, :] - images[None, :, :], axis=2)
    nearest = np.sort(d.min(axis=1))
    coord = np.sum(d < 2.3, axis=1)
    ref = compute_reference_rdf('Fe3O4', pair=('Fe', 'O'), r_max=6.0)
    r = np.asarray(ref['r']); g = np.asarray(ref['g'])
    nz = np.nonzero(g > 0)[0]
    return {
        'lattice_a': float(cell[0, 0]),
        'n_fe': int(len(fe)), 'n_o': int(len(ox)),
        'nearest_fe_o_sorted': nearest.tolist(),
        'coordination_histogram': {str(int(k)): int(v) for k, v in zip(*np.unique(coord, return_counts=True))},
        'rdf_first_two_nonzero_r': r[nz[:2]].tolist(),
        'rdf_bin_width': float(r[1] - r[0]),
    }


def compute_analytic_msd():
    from lammps_post.analysis import analyze_msd
    out = {}
    # Every atom shifts by (1, 2, 2): MSD is exactly 9 on the second frame.
    shift = [_frame([[1, 1, 1, 1, 1], [2, 1, 5, 1, 1]]),
             _frame([[1, 1, 2, 3, 3], [2, 1, 6, 3, 3]], 100)]
    m = analyze_msd(shift, COL, species_type=1, dt_fs=2.0, pbc=(True, True, False))
    out['uniform_shift_msd'] = [float(x) for x in m['msd']]
    out['uniform_shift_time_ps'] = [float(x) for x in m['time']]
    # Static atoms whose type labels swap must show zero displacement.
    swap = [_frame([[1, 1, 1, 1, 1], [2, 2, 5, 1, 1]]),
            _frame([[1, 2, 1, 1, 1], [2, 1, 5, 1, 1]], 100)]
    out['type_swap_static_msd'] = [float(x) for x in analyze_msd(swap, COL, species_type=1)['msd']]
    # One atom crosses the periodic x boundary: 9.5 -> 0.5 in a 10 box is a 1.0 step.
    cross = [_frame([[1, 1, 9.5, 1, 1]]), _frame([[1, 1, 0.5, 1, 1]], 100)]
    out['periodic_crossing_msd'] = [float(x) for x in analyze_msd(cross, COL, species_type=1, pbc=(True, True, False))['msd']]
    # Variable box: the x length changes 10 -> 12 -> 8 between frames. With the
    # documented current-frame-length MIC the steps are +3 and -2 (MSD [0, 9, 1]);
    # a first-frame-length implementation would give [0, 1, 9]. This pins the
    # convention only; it is not evidence of physical diffusion accuracy.
    varbox = [_frame([[1, 1, 9.5, 1, 1]], 0, box=((0, 10), (0, 10), (0, 30))),
              _frame([[1, 1, 0.5, 1, 1]], 100, box=((0, 12), (0, 10), (0, 30))),
              _frame([[1, 1, 6.5, 1, 1]], 200, box=((0, 8), (0, 10), (0, 30)))]
    out['variable_box_msd'] = [float(x) for x in analyze_msd(varbox, COL, species_type=1, pbc=(True, True, False))['msd']]
    return out


def compute_analytic_rdf_pair():
    import numpy as np
    from lammps_post.analysis import compute_rdf
    out = {}
    box = ((0, 20), (0, 20), (0, 20))
    pair = [_frame([[1, 1, 5.0, 5.0, 5.0], [2, 2, 7.0, 5.0, 5.0]], box=box)]
    rdf = compute_rdf(pair, COL, type_a=1, type_b=2, r_max=6.0, n_bins=200, pbc=(True, True, True))
    r = np.asarray(rdf['r']); g = np.asarray(rdf['g'])
    out['isolated_pair_peak_r'] = float(r[int(np.argmax(g))])
    out['isolated_pair_nonzero_bins'] = int(np.count_nonzero(g))
    out['bin_width'] = float(r[1] - r[0])
    # The same pair split across the periodic x face: 0.5 and 19.5 are 1.0 apart.
    wrapped = [_frame([[1, 1, 0.5, 5.0, 5.0], [2, 2, 19.5, 5.0, 5.0]], box=box)]
    rdf2 = compute_rdf(wrapped, COL, type_a=1, type_b=2, r_max=6.0, n_bins=200, pbc=(True, True, True))
    g2 = np.asarray(rdf2['g'])
    out['wrapped_pair_peak_r'] = float(np.asarray(rdf2['r'])[int(np.argmax(g2))])
    out['wrapped_pair_nonzero_bins'] = int(np.count_nonzero(g2))
    return out


def compute_box_geometry():
    from lammpkeeper.io import Box
    # from_dump_bounds takes LAMMPS *enclosing* dump bounds: for a tilt xy = 2
    # the physical x length is (xhi_bound - xlo_bound) - xy. Bounds (0, 12) with
    # xy = 2 therefore describe a 10 x 10 x 30 cell; bounds (0, 10) describe 8 x 10 x 30.
    ortho = Box.from_dump_bounds(((0, 10), (0, 10), (0, 30)))
    tilted = Box.from_dump_bounds(((0, 12), (0, 10), (0, 30)), tilt=(2.0, 0.0, 0.0))
    shrunk = Box.from_dump_bounds(((0, 10), (0, 10), (0, 30)), tilt=(2.0, 0.0, 0.0))
    return {
        'orthogonal_volume': float(ortho.volume),
        'orthogonal_is_orthogonal': bool(ortho.is_orthogonal),
        'tilted_volume': float(tilted.volume),
        'tilted_is_orthogonal': bool(tilted.is_orthogonal),
        'tilted_lengths': [float(x) for x in tilted.lengths],
        'enclosing_bounds_shrink_lengths': [float(x) for x in shrunk.lengths],
        'enclosing_bounds_shrink_volume': float(shrunk.volume),
    }


def compute_fixture_ace_rdf_msd():
    """Snapshot values of the ACE fixture: regression against baseline_commit."""
    import numpy as np
    from lammps_post import analysis as A
    from lammps_post.parsers import pbc_from_boundary
    s = _load_fixture_state()
    f, ci = s.dump_frames, s.dump_col_idx
    pbc = pbc_from_boundary(f.reader.boundary)
    rdf = A.compute_rdf(f, ci, type_a=1, type_b=3, z_pbc=True)
    r = np.asarray(rdf['r']); g = np.asarray(rdf['g']); i = int(np.argmax(g))
    n_used = int(rdf.get('n_frames', 0))
    return {
        # compute_rdf averages the LAST max_frames (default 20) frames.
        'rdf_frames_timestep_range': [int(f[-n_used]['timestep']), int(f[-1]['timestep'])],
        'rdf_feup_o_peak_r': float(r[i]),
        'rdf_feup_o_peak_g': float(g[i]),
        'msd_o_endpoint': float(A.analyze_msd(f, ci, species_type=3, dt_fs=s.dt_fs, pbc=pbc)['msd'][-1]),
        'msd_feup_endpoint': float(A.analyze_msd(f, ci, species_type=1, dt_fs=s.dt_fs, pbc=pbc)['msd'][-1]),
    }


COMPUTE = {
    'fixture-ace-bulk': compute_fixture_ace_bulk,
    'reference-crystal-fe3o4': compute_reference_crystal_fe3o4,
    'analytic-msd': compute_analytic_msd,
    'analytic-rdf-pair': compute_analytic_rdf_pair,
    'box-geometry': compute_box_geometry,
    'fixture-ace-rdf-msd': compute_fixture_ace_rdf_msd,
}

KINDS = ('analytic', 'external', 'fixture', 'snapshot')


def spec_errors(spec):
    """Return schema problems in a reference file; empty list means well-formed."""
    errs = []
    kinds = spec.get('kind', {})
    for key in spec.get('reference', {}):
        k = kinds.get(key)
        if k not in KINDS:
            errs.append(f'key {key!r}: kind {k!r} must be one of {KINDS}')
        if k == 'snapshot' and not spec.get('baseline_commit'):
            errs.append(f'key {key!r}: snapshot kind requires a top-level baseline_commit')
    for key in kinds:
        if key not in spec.get('reference', {}):
            errs.append(f'kind given for unknown key {key!r}')
    return errs


# ── comparison ─────────────────────────────────────────────────────────────

def _compare(measured, reference, tol):
    """Return (ok, detail). Numbers use abs/rel tolerance; others must be equal."""
    import numpy as np
    atol = float(tol.get('abs', 0.0)); rtol = float(tol.get('rel', 0.0))
    if isinstance(reference, bool) or reference is None or isinstance(reference, str):
        return measured == reference, f'measured={measured!r} reference={reference!r}'
    if isinstance(reference, dict):
        if not isinstance(measured, dict) or set(measured) != set(reference):
            return False, f'keys differ: measured={sorted(map(str, measured or {}))} reference={sorted(reference)}'
        bad = [k for k in reference if not _compare(measured[k], reference[k], tol)[0]]
        return not bad, ('ok' if not bad else f'differs at {bad}: measured={measured} reference={reference}')
    try:
        m = np.asarray(measured, dtype=float); ref = np.asarray(reference, dtype=float)
    except (TypeError, ValueError):
        return measured == reference, f'measured={measured!r} reference={reference!r}'
    if m.shape != ref.shape:
        return False, f'shape {m.shape} != {ref.shape}'
    diff = np.abs(m - ref); allowed = atol + rtol * np.abs(ref)
    ok = bool(np.all(diff <= allowed))
    worst = float(np.max(diff)) if diff.size else 0.0
    return ok, f'max|diff|={worst:.3e} allowed={float(np.max(allowed)) if allowed.size else 0.0:.3e}'


def run_check(spec):
    cid = spec['id']
    fn = COMPUTE.get(cid)
    if fn is None:
        return {'id': cid, 'status': 'ERROR', 'detail': 'no compute function for this id', 'keys': {}}
    errs = spec_errors(spec)
    if errs:
        return {'id': cid, 'status': 'ERROR', 'detail': 'malformed reference file: ' + '; '.join(errs), 'keys': {}}
    try:
        measured = fn()
    except Exception:
        return {'id': cid, 'status': 'ERROR', 'detail': traceback.format_exc(limit=6), 'keys': {}}
    keys = {}
    failed = []
    for key, ref in spec['reference'].items():
        tol = spec.get('tolerance', {}).get(key, {})
        if key not in measured:
            keys[key] = {'ok': False, 'detail': 'not measured'}; failed.append(key); continue
        ok, detail = _compare(measured[key], ref, tol)
        kind = spec['kind'][key]
        keys[key] = {'ok': ok, 'kind': kind, 'measured': measured[key], 'reference': ref,
                     'tolerance': tol, 'detail': f'[{kind}] {detail}'}
        if not ok:
            failed.append(key)
    status = 'PASS' if not failed else 'FAIL'
    counts = {k: sum(1 for v in keys.values() if v.get('kind') == k) for k in KINDS}
    meaning = ', '.join(f'{n} {k}' for k, n in counts.items() if n)
    if counts['snapshot']:
        meaning += f"; snapshot keys are a regression check against baseline_commit {spec['baseline_commit'][:7]}, not a correctness proof"
    detail = (f'all {len(keys)} reference keys within tolerance ({meaning})' if not failed
              else 'failed keys: %s' % ', '.join(failed))
    return {'id': cid, 'status': status, 'detail': detail, 'keys': keys, 'source': spec.get('source'),
            'baseline_commit': spec.get('baseline_commit')}


# ── doctor ─────────────────────────────────────────────────────────────────

def doctor():
    lines = [f'repo: {REPO_ROOT}',
             f'git: {_git("rev-parse", "--abbrev-ref", "HEAD")} @ {_git("rev-parse", "--short", "HEAD")}',
             f'dirty files: {len([l for l in _git("status", "--porcelain").splitlines() if l])}',
             f'python: {platform.python_version()} ({sys.executable})',
             f'HOME: {os.environ.get("HOME")}  LKPR_NO_HISTORY={os.environ.get("LKPR_NO_HISTORY")}']
    for m in ('numpy', 'scipy', 'ase', 'matplotlib', 'pandas', 'MDAnalysis'):
        lines.append(f'  {"ok     " if _have(m) else "MISSING"} {m}')
    try:
        import lammpkeeper
        lines.append(f'  ok      lammpkeeper {lammpkeeper.VERSION} from {os.path.dirname(lammpkeeper.__file__)}')
    except Exception as exc:
        lines.append(f'  MISSING lammpkeeper ({exc})')
    lines.append(f'  fixture: {"present" if os.path.exists(FIXTURE) else "MISSING"} {FIXTURE}')
    refs = sorted(f[:-5] for f in os.listdir(REF_DIR) if f.endswith('.json')) if os.path.isdir(REF_DIR) else []
    lines.append(f'  reference files: {len(refs)} {refs}')
    inactive = sorted(set(COMPUTE) - set(refs))
    lines.append(f'  compute functions without references (inactive): {inactive}')
    ok = _have('numpy') and os.path.exists(FIXTURE) and bool(refs)
    return ok, '\n'.join(lines)


# ── main ───────────────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--only', action='append', default=[], help='run only this check id (repeatable)')
    ap.add_argument('--doctor', action='store_true', help='print the doctor report and exit')
    ap.add_argument('--list', action='store_true', help='list checks and their reference sources')
    ap.add_argument('--evidence-dir', default=None, help='override $LKPR_VERIFY_DIR')
    args = ap.parse_args(argv)

    ok, report = doctor()
    print(report)
    if args.doctor:
        return 0 if ok else 2

    specs = []
    for name in sorted(os.listdir(REF_DIR)):
        if name.endswith('.json'):
            with open(os.path.join(REF_DIR, name)) as fh:
                spec = json.load(fh)
            spec.setdefault('id', name[:-5])
            specs.append(spec)
    if args.list:
        for s in specs:
            kinds = s.get('kind', {})
            by_kind = {k: sorted(key for key, kk in kinds.items() if kk == k) for k in KINDS}
            print(f"{s['id']}: {s.get('description','')}\n    source: {s.get('source','')}\n    status: {s.get('status','')}")
            for k, ks in by_kind.items():
                if ks:
                    print(f'    {k}: {", ".join(ks)}')
            if s.get('baseline_commit'):
                print(f"    baseline_commit: {s['baseline_commit']}")
            for e in spec_errors(s):
                print(f'    SCHEMA ERROR: {e}')
        return 0
    if args.only:
        specs = [s for s in specs if s['id'] in args.only]
        missing = set(args.only) - {s['id'] for s in specs}
        if missing:
            print(f'unknown check id(s): {sorted(missing)}', file=sys.stderr); return 2
    if not ok:
        print('doctor failed: numpy, the fixture or reference files are missing', file=sys.stderr); return 2

    root = args.evidence_dir or os.environ.get('LKPR_VERIFY_DIR') or os.path.join(os.path.expanduser('~'), '.cache', 'lkpr-verify')
    stamp = _dt.datetime.now().strftime('%Y%m%dT%H%M%S')
    evid = os.path.join(root, f'{stamp}-{_git("rev-parse", "--short", "HEAD")}-refs')
    os.makedirs(evid, exist_ok=True)
    with open(os.path.join(evid, 'doctor.txt'), 'w') as fh:
        fh.write(report + '\n')

    results = [run_check(s) for s in specs]
    summary = [f"{r['status']} {r['id']} — {r['detail'].splitlines()[0] if r['detail'] else ''}" for r in results]
    for r in results:
        print(f"\n{r['status']} {r['id']}: {r['detail'].splitlines()[0]}")
        for k, v in r['keys'].items():
            mark = 'ok  ' if v.get('ok') else 'FAIL'
            print(f"    {mark} {k}: {v.get('detail')}")
        if r['status'] == 'ERROR':
            print(r['detail'])
    with open(os.path.join(evid, 'results.json'), 'w') as fh:
        json.dump({'evidence_dir': evid, 'results': results}, fh, indent=2, default=str)
    with open(os.path.join(evid, 'summary.txt'), 'w') as fh:
        fh.write('\n'.join(summary) + '\n')
    print('\n' + '\n'.join(summary))
    print(f'evidence: {evid}')
    return 1 if any(r['status'] in ('FAIL', 'ERROR') for r in results) else 0


if __name__ == '__main__':
    sys.exit(main())
