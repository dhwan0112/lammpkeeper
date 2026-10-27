"""Known-failing repros for open BACKLOG items (review of 2026-10-20).

NOT collected by pytest or tests/run.py (file name does not start with test_).
Each test FAILS on the current code and must PASS once its item is fixed.
When fixing an item: move its test into a collected tests/test_*.py module,
register that module in tests/run.py MODULES, and delete it from here.

MSD repros (PHYS-2/PHYS-1) are now collected in tests/test_msd.py.

PHYS-3 periodicity repro is now collected in tests/test_o2_periodicity.py.

  test_o2_count_independent_of_total_o_count       -> PHYS-5
"""
import numpy as np

import _util  # noqa: F401  (path bootstrap)
from lammps_post.analysis import detect_o2_dissociation

COL = {'id': 0, 'type': 1, 'x': 2, 'y': 3, 'z': 4}


def _fr(rows, box, ts=0):
    return {'atoms': np.array(rows, float), 'box': np.array(box, float), 'timestep': ts}


def test_o2_count_independent_of_total_o_count():
    # 4-O chain (gaps 1.0/0.5/1.0 A). Adding 17 far-away O atoms must not
    # change how the chain is paired (slow path n<=20 vs tree path n>20).
    box = [[0, 40], [0, 40], [0, 40]]
    chain = [[1, 2, 5, 5, 5], [2, 2, 6.0, 5, 5], [3, 2, 6.5, 5, 5], [4, 2, 7.5, 5, 5]]
    far = [[10 + k, 2, 20 + (k % 4) * 4, 20 + (k // 4) * 4, 30] for k in range(17)]
    a = detect_o2_dissociation([_fr(chain, box)], COL, bond_cutoff=1.5, o_type=2)['n_o2'][0]
    b = detect_o2_dissociation([_fr(chain + far, box)], COL, bond_cutoff=1.5, o_type=2)['n_o2'][0]
    assert a == b, f'pairing depends on code path: {a} (n=4) vs {b} (n=21)'
