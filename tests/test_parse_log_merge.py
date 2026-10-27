"""Guard: preserve compatible MD blocks without treating minimization as time.

AUDIT-20261027 physical correction: the fixture's second block matching the
production layout is MINIMIZATION, not another MD segment. The historical
assertion requiring more than 201 selected rows locked in optimizer iterations
as physical time. Retain all four raw blocks, but exclude optimizer rows from
MD arrays. A separate analytic test still requires genuine MD blocks to merge.
"""
import os

import _util  # noqa: F401  (path bootstrap)
from _util import REPO_ROOT, have_numpy, skip

LOG = os.path.join(REPO_ROOT, 'tests', 'fixtures', 'ace_examples',
                   'regular_MD', 'log.lammps')


def _available():
    """Gate fixture-backed parsing on both NumPy and the reference log's presence."""
    return have_numpy() and os.path.exists(LOG)


def test_parse_log_fixture_keeps_optimizer_iterations_out_of_md_arrays():
    """The selected MD block, not minimizer rows, defines every merged MD sample."""
    if not _available():
        skip('numpy not installed or log fixture not found')
    import numpy as np
    from lammps_post.parsers import parse_log

    L = parse_log(LOG)
    assert L is not None
    blocks = L['raw_blocks']

    # The fixture must actually be multi-block across more than one layout,
    # otherwise this test proves nothing.
    assert len(blocks) > 1
    assert len({tuple(b[0]) for b in blocks}) > 1

    step = L['step']
    assert [len(b[1]) for b in blocks] == [1, 11, 201, 150]
    assert L['block_kinds'] == ['md', 'md', 'md', 'minimize']
    # Independent source-block identity, not just an adjusted row-count bound.
    selected = blocks[2][1]
    si = blocks[2][0].index('Step')
    np.testing.assert_array_equal(step, selected[:, si])
    np.testing.assert_array_equal(L['block_ids'], np.full(len(selected), 2))
    assert step[0] == 100 and step[-1] == 2100
    assert not any(stage == 'minimize' for stage in L['stages'])
    assert np.all(np.diff(step) > 0)
    assert len(L['stages']) == len(step)


def test_parse_log_merges_compatible_md_blocks_in_source_order():
    """Adjacent compatible runs deduplicate their common endpoint without reordering."""
    if not have_numpy():
        skip('numpy not installed')
    import numpy as np
    from pathlib import Path
    import tempfile
    from lammps_post.parsers import parse_log
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'log.lammps'
        path.write_text('run 10\nStep Temp PotEng\n0 300 -10\n10 301 -11\n'
                        'Loop time of 1 on 1 procs\n'
                        'run 10\nStep Temp PotEng\n10 301 -11\n20 302 -12\n'
                        'Loop time of 1 on 1 procs\n')
        log = parse_log(path)
    # Expected samples are read directly from the tiny source log, not another parser path.
    np.testing.assert_array_equal(log['step'], [0, 10, 20])
    np.testing.assert_array_equal(log['pe'], [-10, -11, -12])
    np.testing.assert_array_equal(log['elapsed_md_steps'], [0, 10, 20])
    assert log['timeline_valid'] and log['block_kinds'] == ['md', 'md']
