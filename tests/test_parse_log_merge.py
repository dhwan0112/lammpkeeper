"""Guard: parse_log reassembles the full multi-stage run.

Regression for the bug where parse_log kept only the LARGEST thermo block and
silently dropped every other stage (e.g. an ACE run's spin-equilibration and
thermalization prefix — the first ~170 ps — vanished from every thermo/pressure
plot). The ACE example `regular_MD/log.lammps` fixture has four thermo blocks in
two column layouts, so it exercises both the same-layout merge and the
mismatched-layout exclusion. Skips cleanly without numpy or the fixture.
"""
import os

import _util  # noqa: F401  (path bootstrap)
from _util import REPO_ROOT, have_numpy

LOG = os.path.join(REPO_ROOT, 'tests', 'fixtures', 'ace_examples',
                   'regular_MD', 'log.lammps')


def _available():
    return have_numpy() and os.path.exists(LOG)


def test_parse_log_merges_same_layout_blocks():
    if not _available():
        return  # skip: no numpy or fixture
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
    largest = max(len(b[1]) for b in blocks)
    same_layout = sum(len(b[1]) for b in blocks if list(b[0]) == list(L['headers']))

    # Merged series spans more than the single largest block (blocks were joined)
    # but no more than every row sharing the production layout (others excluded).
    assert largest < len(step) <= same_layout

    # Steps strictly increasing: sorted with duplicate boundary steps removed.
    assert np.all(np.diff(step) > 0)

    # 'stages' stays one label per data row.
    assert len(L['stages']) == len(step)
