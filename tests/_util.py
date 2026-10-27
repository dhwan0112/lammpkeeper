"""Shared helpers for the LammpKeeper regression suite.

Works both under pytest (`pytest tests/`) and with the dependency-free runner
(`python tests/run.py`). Importing this module puts the repo root on sys.path
so `lammpkeeper`, `lammps_pre`, `lammps_post` import cleanly.
"""
import io
import os
import sys
import json
import hashlib
import contextlib

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

    # Git-tracked ACE example trajectory (element column: Fe/Mn/O, bulk pp pp pp).
    # Shipped under tests/fixtures/ from the ACE Fe-O potential's own examples.
FIXTURE = os.path.join(
   REPO_ROOT, 'tests', 'fixtures', 'ace_examples', 'regular_MD', 'traj.dump')


def have_numpy():
    """Probe the core numeric dependency without turning absence into a test pass."""
    try:
        import numpy  # noqa: F401
        return True
    except ImportError:
        return False


class Skip(Exception):
    """A test cannot run in this environment (missing dependency/fixture).

    Raised by skip()/require(); tests/run.py reports it as SKIP, pytest
    reports it as skipped. Never use a bare `return` to skip: the runner
    used to count that as PASS (BACKLOG TEST-1).
    """


def skip(reason):
    """Skip the calling test with `reason` (pytest-aware).

    PYTEST_CURRENT_TEST is set by pytest only while a test runs, so it is
    the reliable "under pytest" signal ('pytest' in sys.modules can be
    true in a plain runner session that merely imported pytest).
    """
    if os.environ.get('PYTEST_CURRENT_TEST'):
        import pytest
        pytest.skip(reason)
    raise Skip(reason)


def require(condition, reason):
    """Skip the calling test unless `condition` holds."""
    if not condition:
        skip(reason)


def require_numpy():
    """Report a named dependency skip before a test imports NumPy-specific code."""
    require(have_numpy(), 'numpy not installed')


@contextlib.contextmanager
def noninteractive():
    """Silence stdout and make stdin look empty.

    Shell dispatch treats this non-TTY stream as noninteractive, avoiding load
    prompts and using explicit defaults. pytest may supply an input-capture
    object that raises OSError on reads; providing our own stream makes both
    runners exercise the same predictable no-input contract.
    """
    saved = sys.stdin
    sys.stdin = io.StringIO('')
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            yield
    finally:
        sys.stdin = saved


def canon(o):
    """Normalize nested numeric results for stable regression fingerprints.

    Array shape is retained and values are rounded to eight decimals to avoid
    testing insignificant floating-point serialization differences. This tests
    reproducibility, not physical correctness; rebaselines need an independent
    oracle and explicit approval. Non-doc string literals here are part of the
    existing fingerprint format and must not change during annotation.
    """
    import numpy as np
    if isinstance(o, dict):
        return {str(k): canon(v) for k, v in sorted(o.items(), key=lambda x: str(x[0]))}
    if isinstance(o, (list, tuple)):
        return [canon(x) for x in o]
    if isinstance(o, np.ndarray):
        return ['ndarray', list(o.shape),
                [round(float(v), 8) for v in np.asarray(o, float).ravel()]]
    if isinstance(o, (np.floating, float)):
        return round(float(o), 8)
    if isinstance(o, (np.integer, int)):
        return int(o)
    if isinstance(o, (bool, str)) or o is None:
        return o
    return repr(o)


def section_hash(obj):
    """Short sha256 of the canonical JSON of obj (matches the /tmp harness)."""
    return hashlib.sha256(json.dumps(canon(obj), sort_keys=True).encode()).hexdigest()[:16]
