"""TEST-1: skips are explicit and reported, never counted as PASS."""
import sys

import _util
from _util import Skip, require, skip


def test_skip_raises_skip_outside_pytest():
    saved = sys.modules.pop('pytest', None)
    try:
        try:
            skip('example reason')
        except Skip as e:
            assert 'example reason' in str(e)
        else:
            raise AssertionError('skip() did not raise')
    finally:
        if saved is not None:
            sys.modules['pytest'] = saved


def test_require_skips_only_when_condition_fails():
    saved = sys.modules.pop('pytest', None)
    try:
        require(True, 'must not raise')
        try:
            require(False, 'missing thing')
        except Skip as e:
            assert 'missing thing' in str(e)
        else:
            raise AssertionError('require(False, ...) did not skip')
    finally:
        if saved is not None:
            sys.modules['pytest'] = saved
