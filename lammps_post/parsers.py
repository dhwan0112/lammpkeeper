"""
═══════════════════════════════════════════════════════════════
Section 2: File Parsers
═══════════════════════════════════════════════════════════════
Three parsers for the main LAMMPS output file types:
  1. parse_dump()      — Trajectory files (.dump, .lammpstrj)
  2. parse_log()       — Log files (thermodynamic data)
  3. parse_data_file() — Data files (final structure snapshots)

All parsers are format-agnostic: they auto-detect column layouts
and handle any combination of atom properties (id, type, x, y, z,
q, vx, vy, vz, element, etc.) without hardcoded column positions.

Also includes detect_forcefield() for auto-detecting the force field
type (ReaxFF / ACE / HDNNP) from dump column layouts and atom data.
═══════════════════════════════════════════════════════════════
"""

import ast
import hashlib
import json
import mmap
import operator
import os
import queue
import re
import shlex
import threading
import warnings
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from lammpkeeper.common.mapping import FORCE_FIELDS, type_to_label

# Dump/data geometry here is orthogonal only; arbitrary property columns do not
# imply support for tilted cells, scaled-coordinate conversion or every atom style.
# Units and species provenance come from input/log metadata when available;
# detect_forcefield retains a visibly warned, domain-specific legacy guess.
# Optional Rust atom-block parser (native/build.sh); LKPR_NO_NATIVE=1 disables it.
_native = None
if not os.environ.get('LKPR_NO_NATIVE'):
    try:
        from . import _dumpparse as _native
    except ImportError:
        pass

def parse_dump(filepath, max_frames=None, stride=1, columns=None, dtype=np.float64):
    """
    Universal LAMMPS dump / lammpstrj trajectory file parser.

    Reads the standard LAMMPS dump format, which consists of repeated
    blocks of the form:
        ITEM: TIMESTEP
        <timestep number>
        ITEM: NUMBER OF ATOMS
        <N>
        ITEM: BOX BOUNDS ...
        <xlo xhi>
        <ylo yhi>
        <zlo zhi>
        ITEM: ATOMS <col1> <col2> ...
        <atom data lines x N>

    This parser supports ALL dump column layouts. It auto-detects the
    column names from the 'ITEM: ATOMS' header line on the first frame,
    then maps each numeric column to a sequential index. The 'element'
    column (string type, used by ACE potential) is stored separately.

    Both .dump and .lammpstrj files use this identical format — file
    extension does not matter.

    Args:
        filepath:   str — Path to the dump or lammpstrj file.
        max_frames: int or None — Stop reading after this many frames.
                    Useful for quick previews of large trajectories.
        stride:     int — Read every Nth frame (default: 1 = all frames).
                    stride=10 reads frames 1, 11, 21, ... to reduce
                    memory usage for long trajectories.
        columns:    iterable[str] or None — Keep only these columns
                    (e.g. ANALYSIS_COLUMNS). None keeps every column.
        dtype:      numpy dtype of the 'atoms' arrays (float32 halves memory).

    All frames are held in memory; iterate a DumpReader instead to process
    one frame at a time.

    Returns:
        frames:  list[dict] — One dict per frame with keys:
                   'timestep' (int)     — MD step number
                   'natoms'   (int)     — Number of atoms in this frame
                   'box'      (ndarray) — Shape (3, 2): [[xlo,xhi], [ylo,yhi], [zlo,zhi]]
                   'atoms'    (ndarray) — Shape (N, n_cols): all numeric atom data
                   'elements' (ndarray[str] or None) — Element symbols if 'element' column exists
        columns: list[str]  — Names of numeric columns in order (e.g., ['id','type','x','y','z','q'])
        col_idx: dict[str, int] — Mapping from column name to index in the atoms array.
                   Example: col_idx['z'] = 4 means atoms[:, 4] gives z-coordinates.
    """
    reader = DumpReader(filepath, columns=columns, dtype=dtype,
                        stride=stride, max_frames=max_frames)
    frames = list(reader)
    col_idx = dict(reader.col_idx) if reader.raw_columns else None
    return frames, list(reader.columns), col_idx


# Non-numeric dump columns, kept out of the numeric 'atoms' array.
STRING_COLUMNS = ('element',)


def _validate_frame_limits(stride, max_frames):
    """Require integer frame limits rather than silently rounding/slicing floats."""
    try:
        stride = operator.index(stride)
    except TypeError:
        raise ValueError(f"stride must be an integer >= 1, got {stride!r}") from None
    if stride < 1:
        raise ValueError(f"stride must be >= 1, got {stride}")
    if max_frames is not None:
        try:
            max_frames = operator.index(max_frames)
        except TypeError:
            raise ValueError(f"max_frames must be an integer >= 0 or None, got {max_frames!r}") from None
        if max_frames < 0:
            raise ValueError(f"max_frames must be >= 0, got {max_frames}")
    return stride, max_frames

# Every column the analysis and plotting code reads, for DumpReader(columns=...).
ANALYSIS_COLUMNS = ('id', 'type', 'element', 'x', 'y', 'z', 'q')

# DumpReader.index() returns scanned mmap pages to the OS every this many bytes.
_INDEX_RELEASE_BYTES = 32 * 1024 ** 2


# One boundary token per axis in 'ITEM: BOX BOUNDS' ('pp', 'ff', 'fs', 'mm', ...).
_BOUNDARY_TOKEN = re.compile(r'^[pfsm]{1,2}$')


def parse_boundary_flags(line):
    """
    Per-axis boundary flags from an 'ITEM: BOX BOUNDS ...' header line.

    LAMMPS writes one token per axis after the keyword, preceded by
    'xy xz yz' for triclinic boxes, e.g. 'ITEM: BOX BOUNDS pp pp ff'.

    Returns:
        tuple[str, str, str] — e.g. ('pp', 'pp', 'ff'), or None when the line
        carries no flags (dumps written by very old LAMMPS versions).
    """
    tokens = line.split()[3:]
    if len(tokens) < 3:
        return None
    flags = tuple(tokens[-3:])
    if not all(_BOUNDARY_TOKEN.match(t) for t in flags):
        return None
    return flags


def pbc_from_boundary(boundary):
    """
    (x, y, z) periodicity from dump boundary flags (parse_boundary_flags).

    An axis is periodic only when both of its faces are 'p'. Returns None
    when boundary is None, so callers can fall back to another source.
    """
    if boundary is None:
        return None
    return tuple(flag == 'pp' for flag in boundary)


class DumpReader:
    """
    Lazy LAMMPS dump reader: iterating yields one frame dict at a time, so a
    trajectory can be analyzed in memory proportional to one frame.

    Frame dicts have the same keys as parse_dump's (timestep, natoms, box,
    atoms, elements). The column layout is read from the first frame on
    construction and exposed as `raw_columns` (file order, all columns),
    `columns` (kept numeric columns) and `col_idx` (name -> atoms column).
    The first frame's boundary flags are exposed as `boundary` (see
    parse_boundary_flags; None if the header has none). Header metadata is read
    by the shared Python scanner, independently of the native/NumPy atom-block
    backend. LazyFrames exposes the same metadata through its `reader`.
    The read-only `type_ids` property snapshots raw numeric types observed while
    consuming frames, including unlabelled types. `type_labels` additionally
    snapshots explicit type/element pairs. Both ignore column projection and
    legacy synthesized types; indexing headers alone does not populate either.

    Args:
        filepath:   str — Path to the dump or lammpstrj file.
        columns:    iterable[str] or None — Keep only these columns (names not
                    in the file are ignored). None keeps every column. Skipped
                    property columns are never converted, which speeds parsing;
                    raw numeric types are always validated for explicit metadata.
        dtype:      numpy dtype for the 'atoms' array. float32 halves memory;
                    ids/types stay exact below 2**24 (16.7M).
        stride:     int — Yield every Nth frame, starting with the first.
        max_frames: int or None — Stop after yielding this many frames
                    (None or 0 = no limit).

    Raises ValueError on a malformed or truncated atom block, or when a later
    frame changes the column layout.
    """

    # Snapshot source identity and fix the retained column layout for this reader.
    # Selection follows file order, not the caller's requested order; unknown
    # requested names are ignored. Only float32/float64 use the native backend.
    def __init__(self, filepath, columns=None, dtype=np.float64, stride=1, max_frames=None):
        """Bind an unchanged source to fixed columns, dtype and validated limits."""
        stride, max_frames = _validate_frame_limits(stride, max_frames)
        self.filepath = filepath
        self._source_signature = self._signature()
        self.dtype = np.dtype(dtype)
        self.stride = stride
        self.max_frames = max_frames
        self.raw_columns = self._read_layout()
        self._type_ids = set()
        self._type_labels = {}
        self._type_labels_lock = threading.Lock()
        self._has_type_ids = 'type' in self.raw_columns
        self._has_type_labels = self._has_type_ids and 'element' in self.raw_columns

        keep = None if columns is None else set(columns)
        self._usecols = [i for i, c in enumerate(self.raw_columns) if keep is None or c in keep]
        kept = [self.raw_columns[i] for i in self._usecols]
        self.columns = [c for c in kept if c not in STRING_COLUMNS]
        self.col_idx = {c: i for i, c in enumerate(self.columns)}
        self.has_elements = 'element' in kept

        # Positions within `kept`, used to split the structured record array.
        self._numeric_pos = [k for k, c in enumerate(kept) if c not in STRING_COLUMNS]
        self._element_pos = kept.index('element') if self.has_elements else None
        self._element_col = self._usecols[self._element_pos] if self.has_elements else None
        self._native = _native if self.dtype in (np.float64, np.float32) else None

    @property
    def type_ids(self):
        """Return immutable raw numeric type IDs observed in successfully consumed frames."""
        with self._type_labels_lock:
            return frozenset(self._type_ids)

    @property
    def type_labels(self):
        """Return a defensive snapshot of explicit type labels in consumed frames."""
        with self._type_labels_lock:
            return dict(self._type_labels)

    def _observe_type_labels(self, fields, timestep):
        """Atomically validate raw numeric IDs and optional explicit labels after parsing."""
        if not self._has_type_ids:
            return
        type_col = self.raw_columns.index('type')
        element_col = self.raw_columns.index('element') if self._has_type_labels else None
        pending_ids = set()
        pending = {}
        with self._type_labels_lock:
            for row in fields:
                try:
                    tid = int(row[type_col])
                except ValueError:
                    raise ValueError(f"{self.filepath}: invalid explicit type at step {timestep}: "
                                     f"{row[type_col]!r}") from None
                if tid <= 0:
                    raise ValueError(f"{self.filepath}: explicit type must be positive at step {timestep}: {tid}")
                pending_ids.add(tid)
                if not self._has_type_labels:
                    continue
                label = row[element_col]
                previous = pending.get(tid, self._type_labels.get(tid))
                if previous is not None and previous != label:
                    message = (f"{self.filepath}: inconsistent explicit label for type {tid} at step "
                               f"{timestep}: {previous!r} != {label!r}")
                    warnings.warn(message, RuntimeWarning, stacklevel=3)
                    raise ValueError(message)
                pending[tid] = label
            self._type_ids.update(pending_ids)
            self._type_labels.update(pending)

    # Preflight the first frame without materializing atom rows; empty files have
    # no layout. Later headers must match this layout and the boundary metadata.
    def _read_layout(self):
        """Preflight the first header and boundary flags; return [] for an empty file."""
        # The first frame's 'ITEM: BOX BOUNDS' line also gives the boundary
        # flags; LAMMPS does not change them during a run.
        self.boundary = None
        with open(self.filepath, 'r') as f:
            for line in f:
                if line.strip() == 'ITEM: TIMESTEP':
                    _, _, _, header = self._read_header(f, first=True)
                    return header
                if line.strip():
                    raise ValueError(f"{self.filepath}: invalid dump header: {line.strip()}")
        return []

    # Stat identity includes replacement, size and nanosecond modification/change
    # metadata. This is a mutation guard, not a content hash or a file lock.
    def _signature(self):
        """Return stat-based source identity for detecting stale indexes and caches."""
        st = os.stat(self.filepath)
        return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)

    # Refuse stale offsets/cache entries instead of mixing trajectory revisions.
    def _check_source(self):
        """Raise if source metadata no longer matches this reader's snapshot."""
        if self._signature() != self._source_signature:
            raise ValueError(f"{self.filepath}: dump source changed; create a new DumpReader/index/cache")

    def _read_header(self, stream, first=False):
        """Shared structural/geometry preflight for streaming and indexed paths."""
        # Adapt both text streams and binary mmap streams to stripped header text.
        def line():
            """Read one stripped header line from either text or binary streams."""
            value = stream.readline()
            return value.decode().strip() if isinstance(value, bytes) else value.strip()

        timestep = int(line())
        if line() != 'ITEM: NUMBER OF ATOMS':
            raise ValueError(f"{self.filepath}: invalid atom-count header at step {timestep}")
        natoms = int(line())
        if natoms < 0:
            raise ValueError(f"{self.filepath}: negative atom count at step {timestep}")
        bounds_header = line()
        if bounds_header.split()[:3] != ['ITEM:', 'BOX', 'BOUNDS']:
            raise ValueError(f"{self.filepath}: invalid box header at step {timestep}")
        # Reject restricted/general triclinic markers and extra bound values;
        # dropping tilt would otherwise produce plausible but incorrect geometry.
        tokens = bounds_header.split()[3:]
        if any(t in tokens for t in ('xy', 'xz', 'yz', 'abc', 'origin')):
            raise ValueError(f"{self.filepath}: triclinic dump boxes are not supported (step {timestep})")
        boundary = parse_boundary_flags(bounds_header)
        if tokens and (len(tokens) != 3 or boundary is None):
            raise ValueError(f"{self.filepath}: malformed boundary flags at step {timestep}")
        if first:
            self.boundary = boundary
        elif boundary != self.boundary:
            raise ValueError(f"{self.filepath}: boundary flags change at step {timestep}: "
                             f"{boundary} != {self.boundary}")
        box = []
        for _ in range(3):
            parts = line().split()
            if len(parts) > 2:
                raise ValueError(f"{self.filepath}: triclinic/extra box values at step {timestep}")
            if len(parts) != 2:
                raise ValueError(f"{self.filepath}: malformed box bounds at step {timestep}")
            lo, hi = map(float, parts)
            if not np.isfinite([lo, hi]).all() or hi <= lo:
                raise ValueError(f"{self.filepath}: invalid box bounds at step {timestep}")
            box.append([lo, hi])
        header = line().split()
        if header[:2] != ['ITEM:', 'ATOMS'] or len(header) < 3:
            raise ValueError(f"{self.filepath}: invalid ATOMS header at step {timestep}")
        header = header[2:]
        if len(set(header)) != len(header):
            raise ValueError(f"{self.filepath}: duplicate atom column header at step {timestep}")
        if not first and header != self.raw_columns:
            raise ValueError(f"{self.filepath}: column layout changes at step {timestep}: "
                             f"{header} != {self.raw_columns}")
        return timestep, natoms, np.array(box), header

    def index(self):
        """
        Scan the file once for frame headers without parsing atom data.

        The search for each next 'ITEM: TIMESTEP' runs inside mmap.find (C
        speed), so indexing costs about one sequential read of the file.
        Returns a DumpIndex with per-frame timestep, natoms, box and the byte
        span of the atom block, which read_frame() uses for random access.
        """
        # Index every source frame; stride/max_frames belong to the later view.
        # This validates headers, not atom payloads: malformed rows fail on load.
        # Only offsets/metadata survive the mmap context; no borrowed mmap views do.
        idx = DumpIndex()
        self._check_source()
        if os.path.getsize(self.filepath) == 0:
            return idx.finalize()
        marker = b'ITEM: TIMESTEP'
        can_release = hasattr(mmap, 'MADV_DONTNEED')
        with open(self.filepath, 'rb') as f, \
                mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            size = mm.size()
            released = 0
            pos = mm.find(marker)
            while pos != -1:
                # Scanned pages count toward RSS until dropped; release them in
                # page-aligned steps so indexing a multi-GB dump stays small.
                if can_release and pos - released >= _INDEX_RELEASE_BYTES:
                    upto = pos - pos % mmap.PAGESIZE
                    mm.madvise(mmap.MADV_DONTNEED, released, upto - released)
                    released = upto
                mm.seek(pos)
                mm.readline()                   # ITEM: TIMESTEP
                timestep, natoms, box, _ = self._read_header(mm)
                start = mm.tell()
                pos = mm.find(marker, start)
                idx.add(timestep, natoms, box, start, size if pos == -1 else pos)
        return idx.finalize()

    def read_frame(self, index, k):
        """Parse frame k of `index` (from self.index()) with one seek + read."""
        # The index must belong to this reader/source. Copy bounds so mutating a
        # returned frame cannot change the index's geometry for future reads.
        self._check_source()
        start, end = int(index.block_start[k]), int(index.block_end[k])
        natoms, timestep = int(index.natoms[k]), int(index.timesteps[k])
        with open(self.filepath, 'rb') as f:
            f.seek(start)
            block = f.read(end - start)
        atoms, elements = self._parse_block(block, natoms, timestep)
        return {
            'timestep': timestep,
            'natoms': natoms,
            'box': index.boxes[k].copy(),
            'atoms': atoms,
            'elements': elements,
        }

    def frame_nbytes(self, natoms):
        """Estimated memory of one parsed frame (atoms + 2-letter elements)."""
        # Excludes dict/box overhead and underestimates longer element strings;
        # cache insertion below also measures the actual parsed array sizes.
        per_atom = len(self.columns) * self.dtype.itemsize + (8 if self.has_elements else 0)
        return natoms * per_atom

    # Reopen for each pass, apply stride to source-frame positions, and stop after
    # the requested number of yielded frames. None/0 means unlimited, not empty.
    # Skipped atom rows are advanced without numeric conversion or payload checks.
    def __iter__(self):
        """Stream selected frames from the unchanged source, reopening for each pass."""
        self._check_source()
        n_seen = 0
        n_yielded = 0
        with open(self.filepath, 'r') as f:
            while True:
                line = f.readline()
                if not line:
                    return
                if not line.strip():
                    continue
                if line.strip() != 'ITEM: TIMESTEP':
                    raise ValueError(f"{self.filepath}: unexpected atom lines or frame header: {line.strip()}")
                timestep, natoms, box, _ = self._read_header(f)

                n_seen += 1
                if (n_seen - 1) % self.stride:
                    for _ in range(natoms):
                        f.readline()
                    continue

                block = ''.join([f.readline() for _ in range(natoms)]).encode()
                atoms, elements = self._parse_block(block, natoms, timestep)
                yield {
                    'timestep': timestep,
                    'natoms': natoms,
                    'box': box,
                    'atoms': atoms,
                    'elements': elements,
                }

                n_yielded += 1
                if self.max_frames and n_yielded >= self.max_frames:
                    return

    def _parse_block(self, block, natoms, timestep):
        """Parse the first natoms lines of the atom block `block` (bytes)."""
        # Validate the complete supplied block before either backend: blank,
        # missing or surplus rows are errors, not silently skipped observations.
        n_numeric = len(self._numeric_pos)
        lines = block.decode().splitlines()
        if len(lines) != natoms or any(not row.strip() for row in lines):
            raise ValueError(f"{self.filepath}: frame at step {timestep} has invalid atom lines, "
                             f"expected {natoms} (truncated or surplus dump?)")
        fields = None
        if self._has_type_ids or self.has_elements or 'id' in self.col_idx:
            fields = [row.split() for row in lines]
            if any(len(row) != len(self.raw_columns) for row in fields):
                raise ValueError(f"{self.filepath}: malformed atom block at step {timestep}: wrong column count")
            # Integer identity must survive the homogeneous numeric array exactly.
            for name in ('id', 'type'):
                if name not in self.col_idx:
                    continue
                col = self.raw_columns.index(name)
                for row in fields:
                    try:
                        value = int(row[col])
                        converted = self.dtype.type(value)
                        exact = np.isfinite(converted) and int(converted) == value
                    except (ValueError, OverflowError):
                        exact = False
                    if not exact:
                        raise ValueError(f"{self.filepath}: {name} precision/integer error "
                                         f"at step {timestep}: {row[col]} cannot be stored as {self.dtype}")
        if natoms == 0:
            empty_elements = np.empty(0, dtype='U1') if self.has_elements else None
            return np.empty((0, n_numeric), dtype=self.dtype), empty_elements

        # Selected identity columns must round-trip exactly through the requested
        # homogeneous dtype; float32 therefore cannot represent every large ID.
        # Unselected property columns need not be numeric and are not converted;
        # raw types remain exact integer metadata regardless of numeric projection.
        if self._native is not None:
            try:
                values, elements, rows = self._native.parse_block(
                    block, natoms, self._usecols, self._element_col,
                    self.dtype == np.float32)
            except ValueError:
                rows = -1
            if rows == natoms:
                # NumPy retains the returned bytearray as backing storage; it does
                # not borrow the temporary input block or copy numeric values here.
                atoms = np.frombuffer(values, dtype=self.dtype).reshape(natoms, n_numeric)
                if elements is not None:
                    elements = np.array(elements)
                self._observe_type_labels(fields, timestep)
                return atoms, elements

        # Reference path; the native parser defers here for every error case.
        try:
            if not self._usecols:
                atoms = np.empty((natoms, 0), dtype=self.dtype)
                elements = None
            elif not self.has_elements:
                atoms = np.loadtxt(lines, dtype=self.dtype, usecols=self._usecols, ndmin=2)
                elements = None
            else:
                width = max(1, max(len(row[self._element_col]) for row in fields))
                row_dtype = [(f'c{k}', f'U{width}' if self.raw_columns[i] in STRING_COLUMNS else self.dtype)
                             for k, i in enumerate(self._usecols)]
                rec = np.loadtxt(lines, dtype=row_dtype, usecols=self._usecols, ndmin=1)
                names = rec.dtype.names
                elements = rec[names[self._element_pos]]
                # Fixed-width str array: ~8 bytes/atom for 2-letter symbols,
                # and elements still compare/hash like Python str.
                width = max(1, int(np.char.str_len(elements).max()))
                elements = elements.astype(f'U{width}')
                atoms = np.empty((len(rec), n_numeric), dtype=self.dtype)
                for j, k in enumerate(self._numeric_pos):
                    atoms[:, j] = rec[names[k]]
        except ValueError as e:
            raise ValueError(
                f"{self.filepath}: malformed atom block at step {timestep}: {e}") from None

        if len(atoms) != natoms:
            raise ValueError(
                f"{self.filepath}: frame at step {timestep} has {len(atoms)} atom lines, "
                f"expected {natoms} (truncated dump?)")
        self._observe_type_labels(fields, timestep)
        return atoms, elements


class DumpIndex:
    """Per-frame metadata from DumpReader.index(): arrays of length n_frames."""

    # Accumulate scan results before converting them to compact typed arrays.
    def __init__(self):
        """Create an unfinished metadata builder with no frame payloads."""
        self._rows = []

    # Append one frame's metadata and half-open atom-payload byte interval.
    def add(self, timestep, natoms, box, block_start, block_end):
        """Append source metadata and the half-open byte span of one atom block."""
        self._rows.append((timestep, natoms, box, block_start, block_end))

    # Seal the builder once, releasing row tuples; consumers treat the public
    # arrays as read-only even though NumPy write protection is not enforced.
    def finalize(self):
        """Convert accumulated rows to typed arrays once and return this index."""
        rows = self._rows
        self.timesteps = np.array([r[0] for r in rows], dtype=np.int64)
        self.natoms = np.array([r[1] for r in rows], dtype=np.int64)
        self.boxes = np.array([r[2] for r in rows], dtype=np.float64).reshape(-1, 3, 2)
        self.block_start = np.array([r[3] for r in rows], dtype=np.int64)
        self.block_end = np.array([r[4] for r in rows], dtype=np.int64)
        del self._rows
        return self

    # Frame count is available after finalization, including for an empty file.
    def __len__(self):
        """Return the frame count of a finalized index."""
        return len(self.timesteps)


# Default memory budget for LazyFrames' parsed-frame cache.
DEFAULT_CACHE_BYTES = 128 * 1024 ** 2

# Distinguish omitted view limits from explicit overrides (including None/0).
_INHERIT_READER_LIMIT = object()


class _FrameStore:
    """
    Parsed-frame cache shared by a LazyFrames and all of its slices.

    All or nothing: LazyFrames turns caching off (`keep`) when its frames do
    not all fit. A partial cache would hold a full budget of memory to save
    re-parsing only some frames, and analyze-all already shares one pass.
    """

    # Own the reader/index/cache once; slices reuse this same store and transform.
    def __init__(self, reader, index, cache_bytes, transform):
        """Create the cache, budget and optional load transform shared by all views."""
        self.reader = reader
        self.index = index
        self.cache_bytes = cache_bytes
        self.keep = True
        self.transform = transform
        self.cache = {}
        self.cached_bytes = 0
        self._lock = threading.Lock()

    # Check source freshness even on cache hits, then load/transform on misses.
    # Returned frame dicts/arrays are shared references, not defensive copies.
    # The lock protects insertion/accounting; concurrent misses may both parse.
    def get(self, k):
        """Return a source-checked frame, transforming misses and caching if allowed."""
        self.reader._check_source()
        fr = self.cache.get(k)
        if fr is not None:
            return fr
        fr = self.reader.read_frame(self.index, k)
        if self.transform is not None:
            fr = self.transform(fr)
        nbytes = fr['atoms'].nbytes + (fr['elements'].nbytes if fr['elements'] is not None else 0)
        with self._lock:
            if self.keep and k not in self.cache and self.cached_bytes + nbytes <= self.cache_bytes:
                self.cache[k] = fr
                self.cached_bytes += nbytes
        return fr

    # Invalidate transformed frames across all views; budget/policy are unchanged.
    # Transform changes and clearing are intended outside an active shared pass.
    def clear(self):
        """Release cached frames for every view without changing the cache policy."""
        self.cache.clear()
        self.cached_bytes = 0


class LazyFrames(Sequence):
    """
    Read-only list of dump frames that parses each frame from disk on access.

    Drop-in for parse_dump's frame list: supports len(), integer (incl.
    negative) indexing, slicing (returns another LazyFrames), iteration and
    truthiness. A trajectory whose parsed frames fit in `cache_bytes` is
    parsed once and then served from memory; a larger one streams from disk
    one frame at a time and keeps no frames.

    Frame dicts are shared with the cache and must be treated as read-only;
    use set_transform() to derive per-frame data (e.g. a synthesized type
    column) so it survives cache eviction.

    Args:
        reader:      DumpReader — decides columns, dtype and default frame limits.
        index:       DumpIndex or None — from reader.index() (scanned if None).
        cache_bytes: int — Parsed-frame cache budget (0 = always stream).
        stride:      int — Keep every Nth frame, starting with the first;
                     omitted inherits reader.stride.
        max_frames:  int or None — Keep at most this many frames; omitted
                     inherits reader.max_frames. Explicit None/0 means all.
    """

    # Root views choose source positions and all-or-nothing cache policy. Slices
    # inherit the store rather than allocating a second budget or reindexing.
    def __init__(self, reader, index=None, cache_bytes=DEFAULT_CACHE_BYTES,
                 stride=_INHERIT_READER_LIMIT, max_frames=_INHERIT_READER_LIMIT,
                 transform=None, _store=None, _positions=None):
        """Build a limited root view or reuse an existing store for a lazy slice."""
        new_store = _store is None
        if new_store:
            if stride is _INHERIT_READER_LIMIT:
                stride = reader.stride
            if max_frames is _INHERIT_READER_LIMIT:
                max_frames = reader.max_frames
            stride, max_frames = _validate_frame_limits(stride, max_frames)
            index = reader.index() if index is None else index
            _store = _FrameStore(reader, index, cache_bytes, transform)
            _positions = range(0, len(index), stride)
            if max_frames:
                _positions = _positions[:max_frames]
        self._store = _store
        self._positions = _positions
        self._shared = None
        if new_store:
            _store.keep = self.fits_in_cache

    # Length reflects the selected view, not the complete source index.
    def __len__(self):
        """Return the number of source positions selected by this view."""
        return len(self._positions)

    # Range indexing supplies negative-index/bounds behavior; slicing stays lazy
    # and shares cached frame objects with its parent view.
    def __getitem__(self, i):
        """Load an indexed frame or return a lazy slice sharing the same cache."""
        if isinstance(i, slice):
            return LazyFrames(None, _store=self._store, _positions=self._positions[i])
        return self._store.get(self._positions[i])

    # Only this view's active context redirects iteration to shared delivery;
    # random access and independently constructed slices continue loading normally.
    def __iter__(self):
        """Iterate in view order, subscribing to its shared producer when active."""
        shared = self._shared
        if shared is not None:
            return shared.subscribe()
        return self._iter_range(0, len(self._positions))

    # Yield a half-open interval in view coordinates through the shared store.
    def _iter_range(self, begin, end):
        """Load a half-open interval in view coordinates without shared delivery."""
        get = self._store.get
        for k in self._positions[begin:end]:
            yield get(k)

    @contextmanager
    def shared_pass(self, depth=4):
        """
        While active, every iteration over this view (from any thread) is fed
        by one producer that parses each frame once and hands it to all
        iterators, so N concurrent analyses cost one read of the trajectory.

        An iterator opened after the producer has moved on reads the frames it
        missed on its own, then joins; each iterator still sees every frame in
        order. `depth` frames may queue per iterator, so memory stays bounded.
        Random access and slices are unaffected.
        """
        # Context exit disables new subscriptions and requests producer shutdown.
        # Consumers should finish/close their iterators while the context is live;
        # this context does not turn cancellation into a synthetic successful EOF.
        if depth < 1:
            raise ValueError('shared_pass depth must be >= 1')
        shared = _SharedPass(self, depth)
        self._shared = shared
        try:
            yield shared
        finally:
            self._shared = None
            shared.shutdown()

    def set_transform(self, transform):
        """Apply transform(frame) -> frame to every frame on load; clears the cache."""
        # Transform replacement affects slices too because they share the store.
        self._store.transform = transform
        self._store.clear()

    @property
    # Expose the source reader/layout without triggering atom parsing.
    def reader(self):
        """Expose the shared source reader without loading atom payloads."""
        return self._store.reader

    @property
    # Return selected source step labels, not elapsed time or inferred MD duration.
    def timesteps(self):
        """Return selected source step labels, not inferred elapsed MD time."""
        return self._store.index.timesteps[list(self._positions)]

    @property
    def boxes(self):
        """(n_frames, 3, 2) box bounds, from the index (no atom parsing)."""
        return self._store.index.boxes[list(self._positions)]

    @property
    def estimated_bytes(self):
        """Memory needed to hold every frame in this view in the cache."""
        natoms = self._store.index.natoms[list(self._positions)]
        return int(self._store.reader.frame_nbytes(int(natoms.sum())))

    @property
    # Report the shared store's configured array-memory budget in bytes.
    def cache_bytes(self):
        """Return the array-memory budget shared by this view and its slices."""
        return self._store.cache_bytes

    @property
    # Estimate whether this view fits; root construction fixes the store policy.
    # A smaller slice does not retroactively enable its parent's disabled cache.
    def fits_in_cache(self):
        """Report whether this view's estimated array storage fits the shared budget."""
        return self.estimated_bytes <= self._store.cache_bytes


_END = object()


# Queue envelope preserves a producer exception for re-raising by each consumer.
class _Failure:
    """Carry a producer exception through subscriber queues for re-raising."""
    # Keep the original exception rather than replacing it with a success marker.
    def __init__(self, exc):
        """Retain the original exception rather than a successful end marker."""
        self.exc = exc


# One bounded delivery queue per active iterator provides producer backpressure.
class _Subscriber:
    """Bound one iterator's queued frames and expose cooperative cancellation."""
    # Closed is a cancellation signal checked during timed producer queue writes.
    def __init__(self, depth):
        """Create an open subscription with at most depth queued deliveries."""
        self.queue = queue.Queue(maxsize=depth)
        self.closed = False

    # Retry full queues until delivery, explicit iterator closure or global stop.
    # A still-open slow consumer intentionally throttles the shared producer.
    def put(self, item, stop):
        """Deliver with backpressure until accepted, closed or globally cancelled."""
        # Poll so explicit subscription closure or global shutdown can interrupt
        # backpressure; a paused but still-open consumer can still throttle us.
        while not self.closed and not stop.is_set():
            try:
                self.queue.put(item, timeout=0.05)
                return
            except queue.Full:
                continue

    # Cancel this subscription and release queued frame references; other
    # subscribers remain active and their queues are not drained here.
    def close(self):
        """Cancel this subscription and release its queued frame references."""
        self.closed = True
        try:
            while True:
                self.queue.get_nowait()
        except queue.Empty:
            pass


class _SharedPass:
    """Producer/subscriber state behind LazyFrames.shared_pass()."""

    # Own producer progress, subscription membership and a cooperative stop event.
    # The membership/progress lock is not held while parsing or blocking on queues.
    def __init__(self, view, depth):
        """Initialize cooperative producer state for one view and bounded consumers."""
        self._view = view
        self._depth = depth
        self._lock = threading.Lock()
        self._subs = []
        self._next = 0              # position the producer parses next
        self._producer = None
        self._stop = threading.Event()
        self.frames_parsed = 0

    # Defer actual registration until the iterator is advanced, not merely made.
    def subscribe(self):
        """Yield every frame, deferring subscription registration until first advance."""
        # Register only on first next(). Closing an unstarted generator otherwise
        # never enters _consume's finally and leaves a permanently full queue.
        yield from self._subscribe_started()

    # Atomically join at the next producer position; late arrivals replay earlier
    # frames independently, or the whole view if production has already finished.
    def _subscribe_started(self):
        """Register at current producer progress or return an independent replay."""
        n = len(self._view)
        with self._lock:
            start = self._next
            if start >= n or self._stop.is_set():
                sub = None
            else:
                sub = _Subscriber(self._depth)
                self._subs.append(sub)
                if self._producer is None:
                    self._producer = threading.Thread(target=self._produce, daemon=True)
                    self._producer.start()
        if sub is None:
            return self._view._iter_range(0, n)
        return self._consume(sub, start)

    # Replay the missed prefix, consume shared frames in order, and always cancel
    # on exhaustion/error/explicit generator close. Failure envelopes re-raise.
    def _consume(self, sub, start):
        """Replay missed frames, consume deliveries and always close the subscription."""
        try:
            # Frames parsed before this iterator joined are read independently.
            yield from self._view._iter_range(0, start)
            while True:
                item = sub.queue.get()
                if item is _END:
                    return
                if isinstance(item, _Failure):
                    raise item.exc
                yield item
        finally:
            sub.close()

    # Parse once per shared position and fan out the same read-only-by-contract
    # frame object. Completion and failures are distinct queue messages; if all
    # subscribers close, a future subscriber may restart at the saved position.
    def _produce(self):
        """Fan out parsed frames, completion or failures to currently open consumers."""
        get = self._view._store.get
        positions = self._view._positions
        n = len(positions)
        try:
            while True:
                with self._lock:
                    self._subs = [s for s in self._subs if not s.closed]
                    i = self._next
                    if self._stop.is_set() or not self._subs:
                        self._producer = None   # a later subscriber restarts from _next
                        return
                    if i >= n:
                        finished, self._subs, self._producer = self._subs, [], None
                        break
                fr = get(positions[i])
                self.frames_parsed += 1
                with self._lock:
                    # Advancing _next and snapshotting under one lock: a subscriber
                    # either joined in time to receive frame i here, or starts at i+1.
                    self._next = i + 1
                    targets = [s for s in self._subs if not s.closed]
                for s in targets:
                    s.put(fr, self._stop)
            for s in finished:
                s.put(_END, self._stop)
        except BaseException as e:
            with self._lock:
                failed, self._subs, self._producer = self._subs, [], None
            for s in failed:
                s.put(_Failure(e), self._stop)

    # Request cancellation and wait at most five seconds; this is cooperative,
    # not forced thread termination, and cannot interrupt an in-progress file read.
    def shutdown(self):
        """Request cooperative stop and wait up to five seconds for the producer."""
        self._stop.set()
        producer = self._producer
        if producer is not None:
            producer.join(timeout=5)


def parse_log(filepath):
    """
    Universal LAMMPS log file parser with automatic stage detection
    and wall-clock time extraction.

    LAMMPS log files contain thermodynamic output in tabular blocks
    that look like:
        Step  Temp  PotEng  KinEng  ...
        0     300   -1234   45.6    ...
        100   305   -1230   46.2    ...
        ...
        Loop time of 123.45 on 4 procs ...

    This parser:
    1. Scans for thermo header lines beginning with 'Step'
    2. Reads numeric data rows until a terminator is found
    3. Tracks simulation stages (spin_eq, minimize, equilibrate, oxidation)
    4. Extracts 'Loop time' values for performance analysis
    5. Normalizes column names (e.g., 'PotEng' -> 'pe', 'TotEng' -> 'etotal')
    6. Reassembles compatible MD blocks in source order, never optimizer steps

    Args:
        filepath: str — Path to the LAMMPS log file.

    Returns:
        dict with keys:
            'headers'     : list[str]         — Original column names from log
            'step'        : np.array          — Step numbers (normalized key)
            'temp'        : np.array          — Temperature values (if present)
            'pe'          : np.array          — Potential energy (if present)
            'ke'          : np.array          — Kinetic energy (if present)
            'etotal'      : np.array          — Total energy (if present)
            'press'       : np.array          — Pressure (if present)
            'vol'         : np.array          — Volume (if present)
            'stages'      : list[str]         — Stage label for each data row
            'stage_times' : dict[str, float]  — Stage name -> wall time (seconds)
            'raw_blocks'  : list              — All detected thermo blocks
            'block_kinds' : list[str]         — 'md'/'minimize' for each raw block
            'block_ids'   : np.array          — Source block index for each output row
            'timeline_valid': bool           — False for ambiguous/reset or optimizer-only steps
            'unit_system': str/None          — Explicit echoed metal/real units, never a dump guess
            'dt_fs': float/None              — Explicit numeric echoed timestep in femtoseconds
            'elapsed_md_steps': np.array/None — Within-block MD increments only,
                                               excluding optimizer iterations;
                                               not time without a confirmed timestep
        Returns None if no thermo data is found.
    """
    # Column name normalization map: LAMMPS uses different names depending
    # on thermo_style settings and unit system. This maps all variants to
    # consistent short keys used throughout the analysis functions.
    NORM = {
        'step': 'step', 'temp': 'temp', 'temperature': 'temp',
        'c_temp_mobile': 'temp',       # Custom compute for mobile atoms (NVT)
        'poteng': 'pe', 'pe': 'pe',
        'kineng': 'ke', 'ke': 'ke',
        'toteng': 'etotal', 'etotal': 'etotal',
        'press': 'press', 'pressure': 'press',
        'pxx': 'pxx', 'pyy': 'pyy', 'pzz': 'pzz',  # Stress tensor components
        'volume': 'vol', 'vol': 'vol',
        'density': 'density',
    }

    block_kinds = []

    # Freeze a completed table and append its captured MD/minimization identity
    # in the same order as raw_blocks, independently of printable stage labels.
    def _as_block(headers, rows, stages):
        """Materialize one table and record its captured MD/minimization identity."""
        # Nested float lists cost ~32 bytes/value; keep finished blocks as ndarrays.
        block_kinds.append(block_kind)
        return (headers, np.array(rows, dtype=np.float64), stages)

    blocks = []              # Accumulated thermo blocks: [(headers, ndarray, stages), ...]
    current_headers = None   # Column names for the current thermo block
    current_data = []        # Rows of numeric data for the current block
    current_stages = []      # Stage label for each row in the current block
    reading = False          # True when inside a thermo data block
    stage = "init"           # Current simulation stage label
    stage_times = {}         # Accumulated wall time per stage (seconds)
    kind = 'md'
    block_kind = 'md'
    unit_system = None
    timestep = None
    unresolved_timestep = False

    # Only explicit echoed units/timestep commands establish time provenance.
    # A later unresolved timestep invalidates dt_fs until a numeric echo resolves
    # it; mixed units or changing numeric dt cannot share this single timeline.
    with open(filepath, 'r') as fh:
        for raw in fh:
            line = raw.strip()
            low = line.lower()
            if low.startswith('units '):
                unit = line.split()[1]
                if unit not in ('metal', 'real'):
                    raise ValueError(f"{filepath}: unsupported units style {unit!r}; supported: metal, real")
                if unit_system is not None and unit_system != unit:
                    raise ValueError(f"{filepath}: mixed units styles require separate thermo histories")
                unit_system = unit
            if low.startswith('timestep '):
                try:
                    value = float(line.split()[1])
                except ValueError:
                    # LAMMPS may echo the substituted numeric command next.
                    unresolved_timestep = True
                else:
                    if not np.isfinite(value) or value <= 0:
                        raise ValueError(f"{filepath}: timestep must be finite and positive")
                    if timestep is not None and timestep != value:
                        raise ValueError(f"{filepath}: changing timestep requires separate thermo timelines")
                    timestep = value
                    unresolved_timestep = False

            # Warnings may be interleaved with a running thermo table. They are
            # diagnostics, not a table terminator or a simulation-stage marker.
            if line.startswith('WARNING'):
                continue

            # --- Stage detection ---
            # LAMMPS input scripts often print stage markers via 'print' commands.
            # We look for keywords to classify the current simulation phase.
            if low.startswith('minimize ') or low.startswith('setting up ') and 'minimization' in low:
                kind, stage = 'minimize', 'minimize'
            elif low.startswith('run ') or low.startswith('setting up ') and 'run' in low:
                kind = 'md'
                if stage == 'minimize':
                    stage = 'md'
            if 'stage 0' in low or ('spin' in low and ('equil' in low or 'stage' in low)):
                stage = 'spin_eq'         # MC spin equilibration phase
            elif 'stage 1' in low or 'minimiz' in low:
                stage = 'minimize'        # Energy minimization (CG, FIRE, etc.)
            elif 'stage 2' in low or 'equilibrat' in low:
                stage = 'equilibrate'     # NVT/NPT equilibration
            elif 'stage 3' in low or 'oxidat' in low:
                stage = 'oxidation'       # Production oxidation run

            # --- Loop time extraction ---
            # After each 'run' command, LAMMPS prints: "Loop time of X.XX on N procs..."
            # This gives the wall-clock time for that run segment.
            if line.startswith('Loop time of'):
                parts = line.split()
                try:
                    loop_time = float(parts[3])  # Wall time in seconds
                    stage_times[stage] = stage_times.get(stage, 0) + loop_time
                except (ValueError, IndexError):
                    pass

            # --- Thermo header detection ---
            # A thermo header line begins with 'Step' (pressure-only is valid).
            # When found, we start reading numeric data rows.
            if line.split() and line.split()[0] == 'Step' and len(line.split()) > 1:
                if reading and current_data:
                    # Save the previous thermo block before starting a new one
                    blocks.append(_as_block(current_headers, current_data, current_stages))
                # Start a new thermo block with the detected column headers
                current_headers = line.split()
                current_data = []
                current_stages = []
                block_kind = kind
                reading = True
                continue

            # --- End of thermo block ---
            # Thermo blocks end when LAMMPS prints a summary line, error,
            # or starts a new command (minimize, etc.).
            if reading and ('Loop time' in line or line.startswith('ERROR') or
                            'cg style' in low or
                            'minimize' in low):
                if current_data:
                    blocks.append(_as_block(current_headers, current_data, current_stages))
                reading = False
                current_headers = None
                continue

            # --- Data line parsing ---
            # Inside a thermo block, each line should have exactly as many
            # numeric values as there are column headers.
            if reading and current_headers:
                parts = line.split()
                if len(parts) == len(current_headers):
                    try:
                        vals = [float(p) for p in parts]
                        current_data.append(vals)
                        current_stages.append(stage)
                    except ValueError:
                        # Non-numeric line encountered — end this thermo block
                        if current_data:
                            blocks.append(_as_block(current_headers, current_data, current_stages))
                        reading = False
                        current_headers = None

    # Capture the last thermo block if the file ends during data reading
    if reading and current_data:
        blocks.append(_as_block(current_headers, current_data, current_stages))

    if not blocks:
        return None  # No thermo data found in the entire log file

    # Keep raw blocks exactly as written. Optimizer iterations are not physical
    # MD time even when their thermo_style happens to match the MD layout.
    # Source block IDs remain stable after filtering; compatible headers are
    # chosen from the longest MD table (or optimizer tables only if no MD exists).
    # elapsed_md_steps sums within-MD-block deltas, not unknown inter-block gaps.
    md_blocks = [(i, b) for i, b in enumerate(blocks) if block_kinds[i] == 'md']
    candidates = md_blocks or list(enumerate(blocks))
    headers = max(candidates, key=lambda item: len(item[1][1]))[1][0]
    selected = [(i, b) for i, b in candidates if b[0] == headers]
    merged_data, stages, block_ids, elapsed = [], [], [], []
    timeline_valid = bool(md_blocks)
    if any(kind == 'minimize' for kind in block_kinds[:selected[-1][0]]):
        # Even after optimizer rows are excluded, the absolute Step counter can
        # contain optimizer iterations. Only elapsed_md_steps removes that gap.
        timeline_valid = False
    elapsed_step = 0.0
    elapsed_offsets = {}
    previous_md_end = None
    for bi, (hdr, data, _) in md_blocks:
        step_column = hdr.index('Step')
        steps = data[:, step_column]
        if np.any(np.diff(steps) < 0) or (previous_md_end is not None and steps[0] < previous_md_end):
            timeline_valid = False
        elapsed_offsets[bi] = elapsed_step
        elapsed_step += float(steps[-1] - steps[0])
        previous_md_end = steps[-1]
    si = headers.index('Step')
    previous = None
    for bi, (hdr, data, stg) in selected:
        if np.any(np.diff(data[:, si]) < 0):
            timeline_valid = False
        local = data[:, si] - data[0, si]
        # Only identical adjacent boundary records can be safely coalesced.
        start = 0
        if previous is not None:
            if data[0, si] < previous[si]:
                timeline_valid = False
            elif data[0, si] == previous[si]:
                if np.array_equal(previous, data[0]) and block_kinds[bi] == 'md':
                    start = 1
                else:
                    timeline_valid = False
        merged_data.append(data[start:])
        stages.extend(stg[start:])
        block_ids.extend([bi] * len(data[start:]))
        elapsed.extend((elapsed_offsets.get(bi, 0.0) + local[start:]).tolist())
        previous = data[-1]
    arr = np.concatenate(merged_data)
    if not timeline_valid:
        warnings.warn(f"{filepath}: ambiguous/reset or non-MD thermo step timeline; "
                      "source rows retained, do not interpret step as elapsed MD time", RuntimeWarning)
    omitted = len(blocks) - len(selected)
    if omitted:
        warnings.warn(f"{filepath}: excluded {omitted} minimization/incompatible thermo block(s) "
                      "from MD arrays; all source data remain in raw_blocks", RuntimeWarning)

    # Build the result dict with normalized column keys
    result = {'headers': headers, 'stages': stages, 'stage_times': stage_times,
              'raw_blocks': blocks, 'block_kinds': block_kinds,
              'block_ids': np.array(block_ids, dtype=np.int64),
              'timeline_valid': timeline_valid,
              'elapsed_md_steps': np.array(elapsed) if md_blocks else None,
              'unit_system': unit_system,
              'dt_fs': (timestep * (1000.0 if unit_system == 'metal' else 1.0)
                        if timestep is not None and unit_system is not None
                        and not unresolved_timestep else None)}
    if unresolved_timestep:
        warnings.warn(f"{filepath}: unresolved timestep command in log; supply confirmed input metadata",
                      RuntimeWarning)

    for i, h in enumerate(headers):
        # Normalize: 'PotEng' -> 'pe', 'TotEng' -> 'etotal', etc.
        key = NORM.get(h.lower(), h.lower())
        result[key] = arr[:, i]

    return result


def parse_data_file(filepath):
    """
    Parse a LAMMPS data file to extract atom positions, types, and masses.

    LAMMPS data files describe a static configuration and contain sections
    like 'Masses', 'Atoms', 'Velocities', 'Bonds', etc. This parser
    extracts the 'Masses' and 'Atoms' sections plus the simulation box
    dimensions from the header.

    Supports the 'atomic' atom style where each atom line is:
        atom_id  atom_type  x  y  z
    Also supports charge, full, molecular, bond and angle styles when labelled
    in the Atoms section comment, plus optional integer image flags. Only id,
    type and xyz are returned. Unlabelled 5/8-field rows are atomic; ambiguous
    6/9-field rows retain the legacy charge interpretation with a warning.
    Triclinic cells, malformed rows and declared-count mismatches raise.

    Args:
        filepath: str — Path to the LAMMPS data file.

    Returns:
        atoms:  np.array shape (N, 5) — [id, type, x, y, z] for each atom.
                Returns empty array (0, 5) if no atoms found.
        box:    np.array shape (3, 2) — [[xlo, xhi], [ylo, yhi], [zlo, zhi]].
                Returns empty array if no box bounds found.
        masses: dict[int, float] — Atom type ID -> mass in atomic mass units.
    """
    # This is a structural subset reader: topology/velocities are not returned,
    # charge/molecule/image fields are validated but not used to unwrap positions.
    # Box bounds carry no PBC flags or unit style; callers must obtain those from
    # run metadata rather than infer them from lengths or numeric mass values.
    atoms, bounds, masses = [], {}, {}
    section, atom_style, declared_atoms, declared_types = None, None, None, None
    seen_ids = set()
    saw_masses = False
    # style -> (required fields, type column, xyz start)
    styles = {'atomic': (5, 1, 2), 'charge': (6, 1, 3),
              'full': (7, 2, 4), 'molecular': (6, 2, 3),
              'bond': (6, 2, 3), 'angle': (6, 2, 3)}
    with open(filepath, 'r') as f:
        next(f, None)  # LAMMPS always reserves the first line for a title.
        for lineno, line in enumerate(f, 2):
            body, _, comment = line.partition('#')
            stripped = body.strip()
            if not stripped:
                continue
            parts = stripped.split()
            if (parts[-3:] == ['xy', 'xz', 'yz'] or
                    any(token in parts for token in ('avec', 'bvec', 'cvec')) or
                    parts[-1:] == ['abc']):
                raise ValueError(f"{filepath}:{lineno}: triclinic data boxes are not supported")
            if len(parts) == 2 and parts[1] == 'atoms':
                declared_atoms = int(parts[0])
                if declared_atoms < 0:
                    raise ValueError(f"{filepath}:{lineno}: negative atom count")
                continue
            if len(parts) == 3 and parts[1:] == ['atom', 'types']:
                declared_types = int(parts[0])
                if declared_types < 0:
                    raise ValueError(f"{filepath}:{lineno}: negative atom type count")
                continue
            if len(parts) == 4 and parts[-2:] in (['xlo', 'xhi'], ['ylo', 'yhi'], ['zlo', 'zhi']):
                axis = parts[-2][0]
                values = list(map(float, parts[:2]))
                if axis in bounds or not np.isfinite(values).all() or values[1] <= values[0]:
                    raise ValueError(f"{filepath}:{lineno}: invalid/duplicate box bounds")
                bounds[axis] = values
                continue
            if stripped[0].isalpha():
                # Every section header ends the previous section, including
                # coefficient/topology sections that this API does not return.
                if re.fullmatch(r'[A-Za-z][A-Za-z0-9]*(?: [A-Za-z][A-Za-z0-9]*)*', stripped):
                    section = stripped
                    if section == 'Masses':
                        saw_masses = True
                    if section == 'Atoms':
                        atom_style = comment.strip().split()[0] if comment.strip() else None
                        if atom_style is not None and atom_style not in styles:
                            raise ValueError(f"{filepath}:{lineno}: unsupported atom style {atom_style!r}")
                    continue
            try:
                if section == 'Masses':
                    if len(parts) != 2:
                        raise ValueError('mass row must contain type and mass')
                    tid, mass = int(parts[0]), float(parts[1])
                    if tid <= 0 or tid in masses or not np.isfinite(mass) or mass <= 0:
                        raise ValueError('invalid/duplicate mass')
                    if declared_types is not None and tid > declared_types:
                        raise ValueError('mass type exceeds declared atom types')
                    masses[tid] = mass
                elif section == 'Atoms':
                    if atom_style is None:
                        if len(parts) in (5, 8):
                            atom_style = 'atomic'
                        elif len(parts) in (6, 9):
                            atom_style = 'charge'
                            warnings.warn(f"{filepath}:{lineno}: unlabelled six-field Atoms layout "
                                          "guessed as charge; specify Atoms # charge to disambiguate molecular style",
                                          RuntimeWarning)
                        else:
                            raise ValueError('ambiguous Atoms layout; specify an atom style')
                    required, type_col, xyz_col = styles[atom_style]
                    if len(parts) not in (required, required + 3):
                        raise ValueError(f'wrong field count for atom style {atom_style}')
                    aid, tid = int(parts[0]), int(parts[type_col])
                    xyz = list(map(float, parts[xyz_col:xyz_col + 3]))
                    if aid <= 0 or aid in seen_ids or tid <= 0 or not np.isfinite(xyz).all():
                        raise ValueError('invalid/duplicate atom ID, type or coordinates')
                    if int(float(aid)) != aid or int(float(tid)) != tid:
                        raise ValueError('atom ID/type precision loss in float64 output')
                    if declared_types is not None and tid > declared_types:
                        raise ValueError('atom type exceeds declared atom types')
                    if len(parts) == required + 3:
                        [int(value) for value in parts[-3:]]
                    # Validate fields intentionally not returned (charge/molecule).
                    if atom_style == 'charge':
                        if not np.isfinite(float(parts[2])):
                            raise ValueError('invalid atom charge')
                    elif type_col == 2:
                        int(parts[1])
                        if atom_style == 'full' and not np.isfinite(float(parts[3])):
                            raise ValueError('invalid atom charge')
                    seen_ids.add(aid)
                    atoms.append([aid, tid, *xyz])
            except (ValueError, OverflowError) as exc:
                raise ValueError(f"{filepath}:{lineno}: malformed {section} row: {exc}") from None
    if declared_atoms is not None and len(atoms) != declared_atoms:
        raise ValueError(f"{filepath}: atom count mismatch: read {len(atoms)}, declared {declared_atoms}")
    if saw_masses and declared_types is not None and len(masses) != declared_types:
        raise ValueError(f"{filepath}: Masses count mismatch: read {len(masses)}, declared {declared_types}")
    if bounds and len(bounds) != 3:
        raise ValueError(f"{filepath}: incomplete box bounds")
    box = [bounds[axis] for axis in 'xyz'] if bounds else []
    return (np.array(atoms, dtype=float).reshape(-1, 5),
            np.array(box, dtype=float).reshape(-1, 2), masses)


def parse_data_species(filepath):
    """Extract exact Masses comment labels after validating the data structure.

    Only ``# A`` and ``# species=A`` assign labels. Missing comments are
    unresolved; ambiguous comments warn rather than guessing from chemical mass.
    Sparse numeric IDs and the existing ``parse_data_file`` return stay intact.
    """
    parse_data_file(filepath)
    labels = {}
    section = None
    with open(filepath, 'r') as stream:
        next(stream, None)
        for lineno, line in enumerate(stream, 2):
            body, _, comment = line.partition('#')
            body = body.strip()
            if not body:
                continue
            if re.fullmatch(r'[A-Za-z][A-Za-z0-9]*(?: [A-Za-z][A-Za-z0-9]*)*', body):
                section = body
                continue
            if section != 'Masses' or not comment.strip():
                continue
            tokens = comment.split()
            label = None
            if len(tokens) == 1:
                token = tokens[0]
                if token.startswith('species='):
                    label = token[len('species='):] or None
                else:
                    label = token
            if label is None:
                warnings.warn(f"{filepath}:{lineno}: ambiguous Masses species comment "
                              f"{comment.strip()!r}; ignoring label", RuntimeWarning, stacklevel=2)
                continue
            labels[int(body.split()[0])] = label
    return labels


def parse_run_manifest(filepath):
    """Read schema-1 groups/provenance and verify explicitly referenced SHA-256s.

    No manifest is discovered or written automatically. LAMMPS identity/physics
    fields are not allowed top-level metadata. Relative hash paths resolve from
    the manifest directory, including explicit parent-directory references.
    """
    path = Path(filepath).resolve()

    def unique_object(pairs):
        """Reject duplicate JSON keys at any nesting depth instead of overwriting."""
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{path}: manifest duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_constant(value):
        """Reject non-JSON NaN/infinity constants accepted by Python's decoder."""
        raise ValueError(f"{path}: manifest invalid JSON constant {value!r}")

    with path.open('r', encoding='utf-8') as stream:
        try:
            payload = json.load(stream, object_pairs_hook=unique_object,
                                parse_constant=reject_constant)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: malformed manifest JSON: {exc}") from None
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: manifest must be a JSON object")
    allowed = {'schema_version', 'species_groups', 'domain', 'system', 'provenance'}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"{path}: manifest unknown/duplicated LAMMPS fields: {sorted(unknown)}")
    version = payload.get('schema_version')
    if type(version) is not int or version != 1:
        raise ValueError(f"{path}: manifest schema_version must be integer 1")
    groups = payload.setdefault('species_groups', {})
    if not isinstance(groups, dict):
        raise ValueError(f"{path}: manifest species_groups must be an object")
    for name, members in groups.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{path}: manifest group names must be nonblank strings")
        if (not isinstance(members, list) or not members or
                any(type(tid) is not int or tid <= 0 for tid in members)):
            raise ValueError(f"{path}: manifest group {name!r} requires a nonempty list of positive integer IDs")
    if 'domain' in payload and not isinstance(payload['domain'], str):
        raise ValueError(f"{path}: manifest domain must be a string")
    for field in ('system', 'provenance'):
        if field in payload and not isinstance(payload[field], dict):
            raise ValueError(f"{path}: manifest {field} must be an object")
    provenance = payload.get('provenance', {})
    if 'file_hashes' in provenance:
        hashes = provenance['file_hashes']
        if not isinstance(hashes, dict):
            raise ValueError(f"{path}: manifest provenance.file_hashes must be an object")
        for reference, expected in hashes.items():
            if (not isinstance(reference, str) or not reference.strip() or
                    Path(reference).is_absolute()):
                raise ValueError(f"{path}: manifest hash paths must be nonempty relative paths")
            if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', expected):
                raise ValueError(f"{path}: manifest SHA-256 digest for {reference!r} must be 64 hex characters")
            source = (path.parent / reference).resolve()
            digest = hashlib.sha256()
            with source.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            if digest.hexdigest() != expected.lower():
                message = f"{path}: manifest hash mismatch for {reference!r} ({source})"
                warnings.warn(message, RuntimeWarning, stacklevel=2)
                raise ValueError(message)
    payload['path'] = str(path)
    return payload


def parse_input(filepath):
    """
    Parse a LAMMPS input (.in) file to extract simulation configuration.

    Extracts units, boundary conditions, pair_style/pair_coeff (force field
    type and element-to-type mapping), timestep, group definitions, stages,
    dump/output files, thermo settings, temperature, and z-region variables.

    Handles line continuations (&) and include directives (resolved
    relative to the input file directory).

    Args:
        filepath: str — Path to the LAMMPS input script.

    Returns:
        dict with keys:
            'units'        : str or None  — 'real', 'metal', etc.
            'atom_style'   : str or None  — 'charge', 'atomic', etc.
            'boundary'     : list[str]    — ['p', 'p', 'f'] or similar
            'pair_style'   : str or None  — Full pair_style string
            'pair_coeff'   : dict or None — {'potential_file': str, 'elements': list[str]}
            'element_map'  : dict         — {1: 'Fe', 2: 'O', ...} from pair_coeff
            'forcefield'   : str          — 'reaxff', 'ace', or 'unknown'
            'timestep'     : float or None
            'dt_fs'        : float or None — Timestep in femtoseconds
            'read_data'    : str or None  — Data file path
            'groups'       : dict         — {name: definition_string}
            'type_groups'  : dict         — {name: [type_ints]} for groups defined by type
            'variables'    : dict         — {name: value_string}
            'fixes'        : list[str]    — Fix definition strings
            'dumps'        : list[dict]   — [{'name', 'group', 'every', 'file', 'columns'}]
            'log_file'     : str or None
            'write_data'   : str or None
            'write_restart': str or None
            'thermo_style' : list[str]    — Thermo column names
            'thermo_every' : int or None
            'temperature'  : float or None — From velocity create command
            'stages'       : list[str]    — Stage marker strings from print commands
            'runs'         : list[dict]   — [{'steps': int, 'stage': str}]
            'reaction_type': str          — Inferred reaction description
            'z_variables'  : dict         — {name: float} for z-coordinate variables
    """
    # Static extraction is deliberately not a LAMMPS interpreter: no loops,
    # jumps, functions or simulation-dependent equal-variable evaluation run.
    # Some descriptive fields retain unresolved tokens; values required for
    # includes, species mapping and timestep use the strict resolvers below.
    config = {
        'units': None, 'atom_style': None, 'boundary': [],
        'pair_style': None, 'pair_coeff': None, 'element_map': {},
        'forcefield': 'unknown', 'timestep': None, 'dt_fs': None,
        'read_data': None, 'groups': {}, 'type_groups': {},
        'variables': {}, 'fixes': [], 'dumps': [],
        'log_file': None, 'write_data': None, 'write_restart': None,
        'thermo_style': [], 'thermo_every': None,
        'temperature': None, 'stages': [], 'runs': [],
        'reaction_type': 'unknown', 'z_variables': {},
    }

    # Includes are expanded lazily so definitions before an include can resolve
    # its filename. Missing files, include cycles and lexical errors propagate.
    # Yield tokenized logical commands, preserving quoted comment/continuation
    # characters; canonical include paths guard cycles with a 64-level ceiling.
    def _read_lines(fpath, parents=()):
        """Yield lexed commands with relative includes expanded and cycles rejected."""
        fpath = os.path.realpath(fpath)
        if fpath in parents or len(parents) >= 64:
            raise ValueError(f"{fpath}: cyclic or excessive include nesting")
        pending = ''
        with open(fpath, 'r') as f:
            for lineno, raw in enumerate(f, 1):
                # Strip comments without losing the distinction between quoted
                # filenames/strings and LAMMPS continuation characters.
                quote, escaped, clean = None, False, []
                for ch in raw.rstrip('\n'):
                    if escaped:
                        clean.append(ch)
                        escaped = False
                        continue
                    if ch == '\\':
                        escaped = True
                    elif quote:
                        if ch == quote:
                            quote = None
                    elif ch in ('"', "'"):
                        quote = ch
                    elif ch == '#':
                        break
                    clean.append(ch)
                text = ''.join(clean).rstrip()
                if quote is None and text.endswith('&'):
                    pending += text[:-1] + ' '
                    continue
                text = pending + text
                pending = ''
                try:
                    parts = shlex.split(text, comments=True, posix=True)
                except ValueError as exc:
                    raise ValueError(f"{fpath}:{lineno}: quote/lexing error: {exc}") from None
                if not parts:
                    continue
                if parts[0].lower() == 'include':
                    if len(parts) != 2:
                        raise ValueError(f"{fpath}:{lineno}: include requires one filename")
                    inc_path = os.path.join(os.path.dirname(fpath), _resolve_string(parts[1]))
                    yield from _read_lines(inc_path, parents + (fpath,))
                else:
                    yield parts
        if pending:
            raise ValueError(f"{fpath}: unterminated line continuation")

    current_stage = 'init'
    mappings = {}
    reference = re.compile(r'\$\{(\w+)\}|\$(\w)')
    arithmetic = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                  ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod}

    # Resolve supported static equal/string/single-value index variables only;
    # reject unknown names, dependency cycles and excessive recursive references.
    def _variable(name, stack):
        """Resolve supported static variable styles, rejecting cycles and unknowns."""
        if name in stack or len(stack) > 32 or name not in config['variables']:
            raise ValueError(f"{filepath}: cannot resolve variable {name!r} (unknown/cyclic)")
        style, _, value = config['variables'][name].partition(' ')
        if style == 'equal':
            return format(_resolve_numeric(value, stack + (name,)), '.15g')
        if style in ('string', 'index') and value and (style != 'index' or len(value.split()) == 1):
            return _resolve_string(value, stack + (name,))
        raise ValueError(f"{filepath}: cannot resolve variable {name!r} with style {style}")

    # Substitute ${name}/single-character $X via the callback's current dependency
    # stack. Leftover dollar syntax (including runtime substitutions) is rejected.
    def _resolve_string(value, stack=()):
        """Expand named static substitutions and reject remaining dollar syntax."""
        value = reference.sub(lambda m: _variable(m.group(1) or m.group(2), stack), value)
        if '$' in value:
            raise ValueError(f"{filepath}: cannot resolve LAMMPS substitution {value!r}")
        return value

    def _resolve_numeric(value, stack=()):
        """Bounded arithmetic only: no eval, functions, attributes or runtime data."""
        # Length/node/exponent/result limits bound static arithmetic; these are
        # supported-expression limits, not an attempt to emulate all LAMMPS math.
        value = _resolve_string(value, stack)
        try:
            if len(value) > 4096:
                raise ValueError('expression too long')
            tree = ast.parse(value.replace('^', '**'), mode='eval')
            if len(list(ast.walk(tree))) > 64:
                raise ValueError('expression too complex')

            # Recursively evaluate only numeric constants, v_name references and
            # whitelisted operators; every intermediate must stay finite/bounded.
            def calculate(node):
                """Evaluate a whitelisted AST node with finite intermediate results."""
                if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                    result = float(node.value)
                elif isinstance(node, ast.Name) and node.id.startswith('v_'):
                    result = float(_variable(node.id[2:], stack))
                elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                    result = calculate(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
                elif isinstance(node, ast.BinOp) and type(node.op) in arithmetic:
                    left, right = calculate(node.left), calculate(node.right)
                    if isinstance(node.op, ast.Pow) and abs(right) > 100:
                        raise ValueError('exponent too large')
                    result = arithmetic[type(node.op)](left, right)
                else:
                    raise ValueError('unsupported expression')
                if isinstance(result, complex) or not np.isfinite(result) or abs(result) > 1e100:
                    raise ValueError('nonfinite/excessive expression')
                return result

            return calculate(tree.body)
        except (ValueError, TypeError, SyntaxError, ArithmeticError) as exc:
            raise ValueError(f"{filepath}: cannot resolve numeric expression {value!r}: {exc}") from None

    for parts in _read_lines(filepath):
        cmd = parts[0].lower()

        if cmd == 'units' and len(parts) >= 2:
            if config['units'] is not None and config['units'] != parts[1]:
                raise ValueError(f"{filepath}: changing units requires separate configurations")
            config['units'] = parts[1]
            if config['units'] not in ('metal', 'real'):
                raise ValueError(f"{filepath}: unsupported units style {config['units']!r}; supported: metal, real")
        elif cmd == 'atom_style' and len(parts) >= 2:
            config['atom_style'] = parts[1]
        elif cmd == 'boundary' and len(parts) >= 4:
            if config['boundary'] and config['boundary'] != parts[1:4]:
                raise ValueError(f"{filepath}: changing boundary requires separate trajectories/configuration")
            config['boundary'] = parts[1:4]
        elif cmd == 'pair_style':
            config['pair_style'] = ' '.join(parts[1:])
            mappings.clear()
            config['element_map'] = {}
            config['pair_coeff'] = None
        elif cmd == 'pair_coeff':
            # pair_coeff * * <potential_file> <elem1> <elem2> ...
            if len(parts) >= 4 and parts[1] == '*' and parts[2] == '*':
                args = [_resolve_string(part) for part in parts[3:]]
                style = (config['pair_style'] or '').split()
                substyle = style[0] if style else ''
                if substyle.startswith('hybrid'):
                    substyle = args.pop(0)
                    if args and args[0].isdigit():
                        substyle += ':' + args.pop(0)
                    if not any(name in substyle for name in ('pace', 'ace', 'reax', 'hdnnp', 'n2p2')):
                        # Numeric pair coefficients do not encode species maps.
                        continue
                if not args:
                    raise ValueError(f"{filepath}: incomplete pair_coeff mapping")
                try:
                    float(args[0])
                except ValueError:
                    pass
                else:
                    # Ordinary numeric pair coefficients carry no species map.
                    continue
                if any(name in substyle for name in ('hdnnp', 'n2p2')):
                    potential_file, elements = None, args
                else:
                    potential_file, elements = args[0], args[1:]
                if any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_+.-]*', e) for e in elements):
                    raise ValueError(f"{filepath}: unsupported/unresolved pair_coeff species mapping {elements}")
                config['pair_coeff'] = {
                    'potential_file': potential_file,
                    'elements': elements,
                }
                mappings[substyle] = {i + 1: elem for i, elem in enumerate(elements) if elem.upper() != 'NULL'}
                config['element_map'] = {}
                for mapping in mappings.values():
                    for tid, elem in mapping.items():
                        if tid in config['element_map'] and config['element_map'][tid] != elem:
                            raise ValueError(f"{filepath}: conflicting hybrid species for type {tid}")
                        config['element_map'][tid] = elem
        elif cmd == 'timestep' and len(parts) >= 2:
            config['timestep'] = _resolve_numeric(parts[1])
            if config['timestep'] <= 0:
                raise ValueError(f"{filepath}: timestep must be positive")
        elif cmd == 'read_data' and len(parts) >= 2:
            config['read_data'] = _resolve_string(parts[1])
        elif cmd == 'group' and len(parts) >= 3:
            name = parts[1]
            defn = ' '.join(parts[2:])
            config['groups'][name] = defn
            # Extract type numbers from "type N" or "type N1 N2 N3"
            if 'type' in parts[2:]:
                try:
                    tidx = parts.index('type', 2)
                    type_nums = []
                    for tp in parts[tidx + 1:]:
                        try:
                            type_nums.append(int(tp))
                        except ValueError:
                            break
                    if type_nums:
                        config['type_groups'][name] = type_nums
                except (ValueError, IndexError):
                    pass
        elif cmd == 'variable' and len(parts) >= 3:
            vname = parts[1]
            if parts[2] == 'delete':
                config['variables'].pop(vname, None)
                config['z_variables'].pop(vname, None)
                continue
            if len(parts) < 4:
                raise ValueError(f"{filepath}: incomplete variable definition for {vname!r}")
            # ${name}/$X are immediate substitutions, unlike dynamic v_name
            # references in equal expressions. Resolve before replacing the old
            # definition so `variable dt equal ${dt}*2` reads the previous value.
            definition = _resolve_string(' '.join(parts[3:]))
            config['variables'][vname] = parts[2] + ' ' + definition
            config['z_variables'].pop(vname, None)
            if parts[2] == 'equal':
                try:
                    config['z_variables'][vname] = _resolve_numeric(definition, (vname,))
                except ValueError:
                    pass
        elif cmd == 'fix':
            config['fixes'].append(' '.join(parts[1:]))
        elif cmd == 'dump' and len(parts) >= 6:
            dump_info = {
                'name': parts[1],
                'group': parts[2],
                'style': parts[3],
                'every': None,
                'file': parts[5] if len(parts) > 5 else None,
                'columns': parts[6:] if len(parts) > 6 else [],
            }
            try:
                dump_info['every'] = int(parts[4])
            except ValueError:
                pass
            config['dumps'].append(dump_info)
        elif cmd == 'write_data' and len(parts) >= 2:
            config['write_data'] = parts[1]
        elif cmd == 'write_restart' and len(parts) >= 2:
            config['write_restart'] = parts[1]
        elif cmd == 'log' and len(parts) >= 2:
            config['log_file'] = parts[1]
        elif cmd == 'thermo_style' and len(parts) >= 2:
            if parts[1] == 'custom' and len(parts) >= 3:
                config['thermo_style'] = parts[2:]
            else:
                config['thermo_style'] = parts[1:]
        elif cmd == 'thermo' and len(parts) >= 2:
            try:
                config['thermo_every'] = int(parts[1])
            except ValueError:
                pass
        elif cmd == 'velocity' and 'create' in parts:
            try:
                cidx = parts.index('create')
                temp_str = parts[cidx + 1]
                try:
                    config['temperature'] = float(temp_str)
                except ValueError:
                    resolved = _resolve_numeric(temp_str)
                    if resolved is not None:
                        config['temperature'] = resolved
            except (ValueError, IndexError):
                pass
        elif cmd == 'run' and len(parts) >= 2:
            try:
                config['runs'].append({'steps': int(parts[1]), 'stage': current_stage})
            except ValueError:
                pass
        elif cmd == 'print' and len(parts) >= 2:
            msg = ' '.join(parts[1:]).strip('"').strip("'")
            msg_low = msg.lower()
            config['stages'].append(msg)
            # Update current stage label
            if 'spin' in msg_low and ('eq' in msg_low or 'stage 0' in msg_low):
                current_stage = 'spin_eq'
            elif 'minim' in msg_low or 'stage 1' in msg_low:
                current_stage = 'minimize'
            elif 'equilibr' in msg_low or 'stage 2' in msg_low:
                current_stage = 'equilibrate'
            elif 'oxid' in msg_low or 'stage 3' in msg_low:
                current_stage = 'oxidation'

    # Refresh dynamic equal expressions after all redefinitions. Never expose
    # a stale cached value when a dependency changed or became unresolvable.
    config['z_variables'].clear()
    for name, definition in config['variables'].items():
        if definition.startswith('equal '):
            try:
                config['z_variables'][name] = _resolve_numeric(definition[6:], (name,))
            except ValueError:
                pass

    # Derive forcefield from pair_style
    ps = (config['pair_style'] or '').lower()
    if 'reaxff' in ps or 'reax/c' in ps:
        config['forcefield'] = 'reaxff'
    elif 'pace' in ps or 'ace' in ps:
        config['forcefield'] = 'ace'
    elif 'hdnnp' in ps or 'n2p2' in ps:
        config['forcefield'] = 'hdnnp'

    # Compute dt_fs from units + timestep
    if config['timestep'] is not None:
        if config['units'] == 'metal':
            # metal: timestep is in ps, convert to fs
            config['dt_fs'] = config['timestep'] * 1000.0
        elif config['units'] == 'real':
            # real: timestep is already in fs
            config['dt_fs'] = config['timestep']
        else:
            warnings.warn(f"{filepath}: timestep present without explicit units; dt_fs remains unknown", RuntimeWarning)

    # Infer reaction type
    stages_text = ' '.join(config['stages']).lower()
    has_o = any(v.upper() == 'O' or 'O' in v for v in config['element_map'].values())
    has_fe = any('fe' in v.lower() for v in config['element_map'].values())
    if 'oxid' in stages_text and has_fe and has_o:
        config['reaction_type'] = 'Fe oxidation (slab + O₂ gas)'
    elif has_fe and has_o:
        config['reaction_type'] = 'Fe-O interaction'

    return config


def detect_forcefield(columns, col_idx, frames):
    """
    Auto-detect the force field type from dump file column layout and atom data.

    This is a legacy heuristic, not authoritative metadata. Every inference
    warns with the assumed force field, units, timestep and species labels.
    Explicit dump labels override species guesses outside the established ACE
    proxy-label convention. Use input/run metadata to confirm the assumptions.

    Detection logic (applied in order of priority):

    1. If the dump has a 'q' (charge) column → ReaxFF
       ReaxFF uses QEq charge equilibration, so dump files written with
       'dump_modify ... element ...' include per-atom charges. This is the
       most reliable indicator. ReaxFF uses 'real' units (kcal/mol, Angstrom, fs)
       with a typical timestep of 0.25 fs.

    2. If the dump has an 'element' column containing 'Mn' → ACE
       ACE potentials for magnetic iron oxides use 'Mn' as a proxy for
       spin-down Fe atoms. The element column presence with 'Mn' uniquely
       identifies ACE simulations with spin tracking.

    3. If there are ≥ 3 atom types (no charge column) → ACE
       Even without element labels, having 3+ types (Fe_up, Fe_down, O)
       indicates an ACE simulation with spin-resolved atom types.

    4. Otherwise → HDNNP (default)
       Two-type systems without charge data default to 4G-HDNNP, which
       handles charges internally via the n2p2 interface.

    Args:
        columns: list[str]       — Dump file column names (from parse_dump)
        col_idx: dict[str, int]  — Column name to array index mapping
        frames:  list[dict]      — Parsed trajectory frames (needs at least 1)

    Returns:
        dict with keys:
            'forcefield'   : str  — 'reaxff', 'ace', or 'hdnnp'
            'unit_system'  : str  — 'real' (ReaxFF) or 'metal' (ACE/HDNNP)
            'dt_fs'        : float — Default timestep in femtoseconds
            'has_charge'   : bool — Whether charge data is available
            'has_velocity' : bool — Whether velocity columns (vx,vy,vz) exist
            'has_element'  : bool — Whether element column exists
            'atom_types'   : dict — Type ID -> human-readable name mapping
    """
    cols_set = set(columns)
    has_element = bool(frames and frames[0].get('elements') is not None)
    explicit_map = {}
    labels = set(frames[0]['elements']) if has_element else set()
    if has_element and 'type' in col_idx:
        for value, label in zip(frames[0]['atoms'][:, col_idx['type']], frames[0]['elements']):
            tid = int(value)
            if tid in explicit_map and explicit_map[tid] != str(label):
                raise ValueError(f"type {tid} has inconsistent explicit dump element labels")
            explicit_map[tid] = str(label)

    # Finalize each heuristic branch: preserve authoritative explicit labels
    # unless canonical proxy slots match, and warn about all inferred metadata.
    def _metadata(info):
        """Preserve explicit species labels where applicable and warn about guesses."""
        # Registry aliases apply only when explicit type -> element assignments
        # agree with their canonical slots. The same element set in another
        # order (or under different type IDs) is authoritative, not a proxy map.
        canonical = FORCE_FIELDS.get(info['forcefield'], {})
        alias_elements = {element for element, label in canonical.values() if element != label}
        canonical_elements = {element for element, _label in canonical.values()}
        matching_slots = all(tid in canonical and canonical[tid][0] == element
                             for tid, element in explicit_map.items())
        legacy_proxy = (bool(alias_elements & labels) and labels <= canonical_elements
                        and matching_slots)
        if has_element and not legacy_proxy:
            info['atom_types'] = explicit_map
        info['has_element'] = has_element
        warnings.warn("Dump forcefield/units/timestep are heuristic guesses: "
                      f"{info['forcefield']}, {info['unit_system']}, dt_fs={info['dt_fs']}; "
                      f"atom labels={info['atom_types']}. Supply input metadata to confirm.", RuntimeWarning,
                      stacklevel=3)
        return info

    # --- Detection Rule 1: Charge column → ReaxFF ---
    if 'q' in cols_set:
        # Build atom type mapping from the first frame's unique type values
        if frames and 'type' in col_idx:
            types = frames[0]['atoms'][:, col_idx['type']].astype(int)
            unique_types = sorted(int(t) for t in set(types))
            if len(unique_types) == 2:
                # Standard Fe-O system: type 1 = Fe, type 2 = O
                type_map = {unique_types[0]: 'Fe', unique_types[1]: 'O'}
            elif len(unique_types) == 3:
                # Fe-Cr-O system (e.g., stainless steel oxidation)
                type_map = {unique_types[0]: 'Fe', unique_types[1]: 'Cr', unique_types[2]: 'O'}
            else:
                type_map = {int(t): f'Type{t}' for t in unique_types}
        else:
            type_map = type_to_label('reaxff')  # Fallback default: {1:'Fe', 2:'O'}

        return _metadata({
            'forcefield': 'reaxff',
            'unit_system': 'real',       # kcal/mol, Angstrom, fs
            'dt_fs': 0.25,               # Typical ReaxFF timestep: 0.25 fs
            'has_charge': True,
            'has_velocity': 'vx' in cols_set,
            'has_element': False,
            'atom_types': type_map,
        })

    # --- Detection Rule 2: registry proxy elements imply an alias convention ---
    if has_element:
        for ff, canonical in FORCE_FIELDS.items():
            alias_elements = {element for element, label in canonical.values() if element != label}
            canonical_elements = {element for element, _label in canonical.values()}
            if not (alias_elements & labels and labels <= canonical_elements):
                continue
            # Element-only dumps may infer the historical slot convention;
            # explicit numeric slots must agree before aliases can be applied.
            # atom_types is keyed by type NUMBER, like every other rule: callers
            # (state._guess_o_type, state._guess_surface_z, shell's type labels)
            # index it with the numeric type column. Element-keyed entries used to
            # slip past their `isinstance(t, int)` guards and silently degrade to
            # a "Fe is type 1 only" fallback, which drops Fe_down.
            return _metadata({
                'forcefield': ff,
                'unit_system': 'metal',   # eV, Angstrom, ps
                'dt_fs': 0.25,            # ACE Fe-O potential uses 0.00025 ps = 0.25 fs
                'has_charge': False,
                'has_velocity': 'vx' in cols_set,
                'has_element': True,
                'atom_types': type_to_label(ff),
            })

    # --- Detection Rule 3: ≥ 3 atom types → ACE (spin-resolved) ---
    if frames and 'type' in col_idx:
        types = frames[0]['atoms'][:, col_idx['type']].astype(int)
        max_type = int(types.max()) if len(types) else 0

        if max_type >= 3:
            unique_types = sorted(set(int(t) for t in types))

            if len(unique_types) == 3:
                # The ACE type order is fixed by the potential:
                #   pair_coeff * * ACE_Fe-O.yace Fe Mn O  ->  1=Fe_up, 2=Fe_down, 3=O
                # so read it from the shared convention rather than guessing.
                #
                # Assumes the three types ARE 1/2/3 — true for every ACE dump,
                # since the pair_coeff line fixes the order. A second 3-type
                # chargeless force field with a different order would land here
                # and be mislabelled; give it its own branch when one appears.
                #
                # This used to guess O as "the rarest type, if it has < 20% of the
                # most common". That premise ("O is far fewer than Fe") holds for a
                # slab + O2 gas, but is false for the bulk magnetite these ACE runs
                # actually target — Fe3O4 is Fe:O = 3:4, so O is the MOST abundant
                # species. Combined with ferromagnetic spin ordering (the MC swap is
                # semi-grand with mu=0, so the minority spin population can get
                # small), the rarest type becomes the minority Fe rather than O, and
                # the guess silently relabelled Fe_up as O — corrupting every
                # O-based analysis. Newly generated trajectories carry an element
                # column and never reach this branch at all.
                type_map = type_to_label('ace')
            else:
                # 4+ spin-resolved types: no fixed convention to fall back on, so
                # keep the original count heuristic.
                type_counts = {int(t): int(np.sum(types == t)) for t in unique_types}
                # The key callback ranks populations, not type IDs; ties retain
                # sorted type order. This remains a guess, not species evidence.
                sorted_by_count = sorted(type_counts.items(), key=lambda x: x[1])
                rarest_type, rarest_count = sorted_by_count[0]
                most_count = sorted_by_count[-1][1]

                if rarest_count < most_count * 0.2:
                    o_type = rarest_type
                else:
                    o_type = max(unique_types)

                fe_types = [t for t in unique_types if t != o_type]
                type_map = {}
                if len(fe_types) >= 1:
                    type_map[fe_types[0]] = 'Fe_up'
                if len(fe_types) >= 2:
                    type_map[fe_types[1]] = 'Fe_down'
                if len(fe_types) >= 3:
                    type_map[fe_types[2]] = 'Fe_NM'
                for ft in fe_types[3:]:
                    type_map[ft] = f'Fe_type{ft}'
                type_map[o_type] = 'O'

            return _metadata({
                'forcefield': 'ace',
                'unit_system': 'metal',
                'dt_fs': 0.25,            # ACE Fe-O potential uses 0.00025 ps = 0.25 fs
                'has_charge': False,
                'has_velocity': 'vx' in cols_set,
                'has_element': has_element,
                'atom_types': type_map,
            })

    # --- Detection Rule 4: Default → HDNNP ---
    # Two types without charge = 4G-HDNNP (or any simple 2-type potential)
    return _metadata({
        'forcefield': 'hdnnp',
        'unit_system': 'metal',
        'dt_fs': 1.0,
        'has_charge': False,
        'has_velocity': 'vx' in cols_set,
        'has_element': has_element,
        'atom_types': type_to_label('hdnnp'),
    })
