"""Guard: the single-read analysis engine and the cKDTree RDF path.

- LazyFrames.shared_pass: completed concurrent iterators see every frame in
  order; an intentionally stopped iterator sees its prefix. The producer count
  excludes independent prefix replays by late joiners, not all disk reads.
- 'analyze all' over a shared read gives the same results as sequential.
- compute_rdf's cKDTree path bins exactly like the brute-force fallback.
  Both paths share production binning/normalization: parity is not an independent
  proof of physical RDF normalization or restricted-triclinic support.

Skips cleanly without numpy, scipy (RDF) or the fixture.
"""
import os
import tempfile
import threading

import _util  # noqa: F401  (path bootstrap)
from _util import FIXTURE, have_numpy, noninteractive, section_hash, skip


def _have_scipy():
    """Probe the optional spatial backend so absence is an explicit test skip."""
    try:
        import scipy.spatial  # noqa: F401
        return True
    except ImportError:
        return False


def _lazy_fixture(**kw):
    """Wrap the reference dump with caller-selected cache and frame limits."""
    from lammps_post.parsers import DumpReader, LazyFrames
    return LazyFrames(DumpReader(FIXTURE), **kw)


def test_shared_pass_feeds_every_iterator_every_frame_once():
    """Late joiners replay the full stream while early exits cannot deadlock peers."""
    if not have_numpy():
        skip('numpy not installed')
    if not os.path.exists(FIXTURE):
        skip(f'fixture not found: {FIXTURE}')
    frames = _lazy_fixture(cache_bytes=0, max_frames=60)
    expected = [f['timestep'] for f in frames]
    # A separate sequential pass defines order before concurrent consumption begins.
    seen = {}
    gate = threading.Event()

    def consume(name, wait=False, stop_after=None):
        """Record one consumer's sequence with controlled late joining or early exit."""
        if wait:
            gate.wait()
        steps = []
        for fr in frames:
            steps.append(fr['timestep'])
            if name == 'early' and len(steps) == 20:
                gate.set()          # let the late iterator join mid-stream
            if stop_after is not None and len(steps) == stop_after:
                break
        seen[name] = steps

    with frames.shared_pass(depth=2) as shared:
        threads = [threading.Thread(target=consume, args=('early',)),
                   threading.Thread(target=consume, args=('also_early',)),
                   threading.Thread(target=consume, args=('late',), kwargs={'wait': True}),
                   threading.Thread(target=consume, args=('quits',), kwargs={'stop_after': 5})]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)
        assert not any(t.is_alive() for t in threads), 'shared pass deadlocked'
    assert seen['early'] == expected
    assert seen['also_early'] == expected
    assert seen['late'] == expected
    assert seen['quits'] == expected[:5]
    assert shared.frames_parsed <= len(expected)


def test_shared_pass_propagates_parse_errors():
    """Producer failure must reach consumers instead of looking like end of input."""
    if not have_numpy():
        skip('numpy not installed')
    if not os.path.exists(FIXTURE):
        skip(f'fixture not found: {FIXTURE}')
    frames = _lazy_fixture(cache_bytes=0, max_frames=10)

    def boom(fr):
        """Inject a deterministic transform failure at the fourth indexed timestep."""
        if fr['timestep'] == frames.timesteps[3]:
            raise ValueError('bad frame')
        return fr

    frames.set_transform(boom)
    with frames.shared_pass():
        try:
            list(frames)
        except ValueError as e:
            assert 'bad frame' in str(e)
        else:
            raise AssertionError('expected the producer error to reach the iterator')


def _analyze_all(load_opts):
    """Run the same shell workload with only the loading/cache policy varied."""
    from lammps_post.shell import LammpsPostShell
    sh = LammpsPostShell()
    sh.state.output_dir = tempfile.mkdtemp(prefix='lkpr_test_')
    with noninteractive():
        sh.do_load(f'dump {FIXTURE} {load_opts}')
        sh.do_analyze('all')
    return sh.state


def test_shared_analyze_all_matches_sequential():
    """Shared streaming must preserve every sequential analysis cache fingerprint."""
    if not have_numpy():
        skip('numpy not installed')
    if not os.path.exists(FIXTURE):
        skip(f'fixture not found: {FIXTURE}')
    seq = _analyze_all('')
    assert seq.dump_frames.fits_in_cache
    shared = _analyze_all('--cache-mb 0.01')
    assert not shared.dump_frames.fits_in_cache
    assert sorted(seq.cache) == sorted(shared.cache)
    for key in seq.cache:
        assert section_hash(seq.cache[key]) == section_hash(shared.cache[key]), key


def test_rdf_tree_path_bins_like_brute_force():
    """Candidate acceleration must preserve exact RDF bins for bulk and slab PBC."""
    if not have_numpy():
        skip('numpy not installed')
    if not _have_scipy():
        skip('scipy not installed')
    if not os.path.exists(FIXTURE):
        skip(f'fixture not found: {FIXTURE}')
    import numpy as np
    from lammps_post import analysis as A
    frames = _lazy_fixture()
    col_idx = dict(frames.reader.col_idx)
    ace = {'Fe': 1, 'Mn': 2, 'O': 3}
    frames.set_transform(lambda fr: dict(fr, atoms=np.hstack(
       [fr['atoms'], np.array([ace[e] for e in fr['elements']], float)[:, None]])))
    col_idx['type'] = len(col_idx)

    real = A._rdf_candidate_pairs
    # Disable only candidate generation: binning and normalization remain production code.
    try:
        for ta, tb in ((1, 3), (3, 3)):
            for z_pbc in (False, True):
                A._rdf_candidate_pairs = real
                tree = A.compute_rdf(frames, col_idx, ta, tb, max_frames=5, z_pbc=z_pbc)
                A._rdf_candidate_pairs = lambda *a, **k: None
                brute = A.compute_rdf(frames, col_idx, ta, tb, max_frames=5, z_pbc=z_pbc)
                assert np.array_equal(tree['g'], brute['g']), (ta, tb, z_pbc)
    finally:
        A._rdf_candidate_pairs = real
