"""TEST-1: skips are explicit and reported, never counted as PASS."""
import contextlib
import os

import _util  # noqa: F401  (path bootstrap)
from _util import Skip, require, skip


@contextlib.contextmanager
def _not_under_pytest():
    """Clear pytest's per-test marker so skip() takes the runner path."""
    saved = os.environ.pop('PYTEST_CURRENT_TEST', None)
    try:
        yield
    finally:
        if saved is not None:
            os.environ['PYTEST_CURRENT_TEST'] = saved


def test_skip_raises_skip_outside_pytest():
    with _not_under_pytest():
        try:
            skip('example reason')
        except Skip as e:
            assert 'example reason' in str(e)
        else:
            raise AssertionError('skip() did not raise')


def test_require_skips_only_when_condition_fails():
    with _not_under_pytest():
        require(True, 'must not raise')
        try:
            require(False, 'missing thing')
        except Skip as e:
            assert 'missing thing' in str(e)
        else:
            raise AssertionError('require(False, ...) did not skip')
