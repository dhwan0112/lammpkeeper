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

import mmap
import os
import queue
import re
import threading
from collections.abc import Sequence
from contextlib import contextmanager

import numpy as np

from lammpkeeper.common.mapping import type_to_label

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

# Every column the analysis and plotting code reads, for DumpReader(columns=...).
ANALYSIS_COLUMNS = ('id', 'type', 'element', 'x', 'y', 'z', 'q')

# Parse width for element labels; shrunk to the longest label afterwards.
_ELEMENT_PARSE_DTYPE = 'U16'

# DumpReader.index() returns scanned mmap pages to the OS every this many bytes.
_INDEX_RELEASE_BYTES = 32 * 1024 ** 2


class DumpReader:
    """
    Lazy LAMMPS dump reader: iterating yields one frame dict at a time, so a
    trajectory can be analyzed in memory proportional to one frame.

    Frame dicts have the same keys as parse_dump's (timestep, natoms, box,
    atoms, elements). The column layout is read from the first frame on
    construction and exposed as `raw_columns` (file order, all columns),
    `columns` (kept numeric columns) and `col_idx` (name -> atoms column).

    Args:
        filepath:   str — Path to the dump or lammpstrj file.
        columns:    iterable[str] or None — Keep only these columns (names not
                    in the file are ignored). None keeps every column. Skipped
                    columns are never converted, which also speeds parsing.
        dtype:      numpy dtype for the 'atoms' array. float32 halves memory;
                    ids/types stay exact below 2**24 (16.7M).
        stride:     int — Yield every Nth frame, starting with the first.
        max_frames: int or None — Stop after yielding this many frames
                    (None or 0 = no limit).

    Raises ValueError on a malformed or truncated atom block, or when a later
    frame changes the column layout.
    """

    def __init__(self, filepath, columns=None, dtype=np.float64, stride=1, max_frames=None):
        if stride < 1:
            raise ValueError(f"stride must be >= 1, got {stride}")
        self.filepath = filepath
        self.dtype = np.dtype(dtype)
        self.stride = stride
        self.max_frames = max_frames
        self.raw_columns = self._read_layout()

        keep = None if columns is None else set(columns)
        self._usecols = [i for i, c in enumerate(self.raw_columns) if keep is None or c in keep]
        kept = [self.raw_columns[i] for i in self._usecols]
        self.columns = [c for c in kept if c not in STRING_COLUMNS]
        self.col_idx = {c: i for i, c in enumerate(self.columns)}
        self.has_elements = 'element' in kept

        # Positions within `kept`, used to split the structured record array.
        self._numeric_pos = [k for k, c in enumerate(kept) if c not in STRING_COLUMNS]
        self._element_pos = kept.index('element') if self.has_elements else None
        self._row_dtype = [(f'c{k}', _ELEMENT_PARSE_DTYPE if c in STRING_COLUMNS else self.dtype)
                           for k, c in enumerate(kept)]

    def _read_layout(self):
        with open(self.filepath, 'r') as f:
            for line in f:
                if line.startswith('ITEM: ATOMS'):
                    return line.split()[2:]
        return []

    def index(self):
        """
        Scan the file once for frame headers without parsing atom data.

        The search for each next 'ITEM: TIMESTEP' runs inside mmap.find (C
        speed), so indexing costs about one sequential read of the file.
        Returns a DumpIndex with per-frame timestep, natoms, box and the byte
        span of the atom block, which read_frame() uses for random access.
        """
        idx = DumpIndex()
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
                timestep = int(mm.readline())
                mm.readline()                   # ITEM: NUMBER OF ATOMS
                natoms = int(mm.readline())
                mm.readline()                   # ITEM: BOX BOUNDS ...
                box = [[float(v) for v in mm.readline().split()[:2]] for _ in range(3)]
                header = mm.readline().decode().split()[2:]
                if header != self.raw_columns:
                    raise ValueError(
                        f"{self.filepath}: column layout changes at step {timestep}: "
                        f"{header} != {self.raw_columns}")
                start = mm.tell()
                pos = mm.find(marker, start)
                idx.add(timestep, natoms, box, start, size if pos == -1 else pos)
        return idx.finalize()

    def read_frame(self, index, k):
        """Parse frame k of `index` (from self.index()) with one seek + read."""
        start, end = int(index.block_start[k]), int(index.block_end[k])
        natoms, timestep = int(index.natoms[k]), int(index.timesteps[k])
        with open(self.filepath, 'rb') as f:
            f.seek(start)
            text = f.read(end - start).decode()
        # Only the first natoms lines belong to the frame, as with readline().
        lines = text.split('\n', natoms)[:natoms] if natoms else []
        atoms, elements = self._parse_block(lines, natoms, timestep)
        return {
            'timestep': timestep,
            'natoms': natoms,
            'box': index.boxes[k].copy(),
            'atoms': atoms,
            'elements': elements,
        }

    def frame_nbytes(self, natoms):
        """Estimated memory of one parsed frame (atoms + 2-letter elements)."""
        per_atom = len(self.columns) * self.dtype.itemsize + (8 if self.has_elements else 0)
        return natoms * per_atom

    def __iter__(self):
        n_seen = 0
        n_yielded = 0
        with open(self.filepath, 'r') as f:
            while True:
                line = f.readline()
                if not line:
                    return
                if 'ITEM: TIMESTEP' not in line:
                    continue

                timestep = int(f.readline())
                f.readline()                    # ITEM: NUMBER OF ATOMS
                natoms = int(f.readline())
                f.readline()                    # ITEM: BOX BOUNDS ...
                # lo/hi per axis; a triclinic tilt factor (3rd value) is ignored.
                box = np.array([[float(v) for v in f.readline().split()[:2]]
                                for _ in range(3)])
                header = f.readline().split()[2:]
                if header != self.raw_columns:
                    raise ValueError(
                        f"{self.filepath}: column layout changes at step {timestep}: "
                        f"{header} != {self.raw_columns}")

                n_seen += 1
                if (n_seen - 1) % self.stride:
                    for _ in range(natoms):
                        f.readline()
                    continue

                lines = [f.readline() for _ in range(natoms)]
                atoms, elements = self._parse_block(lines, natoms, timestep)
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

    def _parse_block(self, lines, natoms, timestep):
        n_numeric = len(self._numeric_pos)
        if natoms == 0:
            empty_elements = np.empty(0, dtype='U1') if self.has_elements else None
            return np.empty((0, n_numeric), dtype=self.dtype), empty_elements

        try:
            if not self.has_elements:
                atoms = np.loadtxt(lines, dtype=self.dtype, usecols=self._usecols, ndmin=2)
                elements = None
            else:
                rec = np.loadtxt(lines, dtype=self._row_dtype, usecols=self._usecols, ndmin=1)
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
        return atoms, elements


class DumpIndex:
    """Per-frame metadata from DumpReader.index(): arrays of length n_frames."""

    def __init__(self):
        self._rows = []

    def add(self, timestep, natoms, box, block_start, block_end):
        self._rows.append((timestep, natoms, box, block_start, block_end))

    def finalize(self):
        rows = self._rows
        self.timesteps = np.array([r[0] for r in rows], dtype=np.int64)
        self.natoms = np.array([r[1] for r in rows], dtype=np.int64)
        self.boxes = np.array([r[2] for r in rows], dtype=np.float64).reshape(-1, 3, 2)
        self.block_start = np.array([r[3] for r in rows], dtype=np.int64)
        self.block_end = np.array([r[4] for r in rows], dtype=np.int64)
        del self._rows
        return self

    def __len__(self):
        return len(self.timesteps)


# Default memory budget for LazyFrames' parsed-frame cache.
DEFAULT_CACHE_BYTES = 1024 * 1024 ** 2


class _FrameStore:
    """
    Parsed-frame cache shared by a LazyFrames and all of its slices.

    Fill-then-keep rather than LRU: analyses scan the whole trajectory in
    order, and LRU over a scan longer than the budget never hits while still
    holding a full budget of frames. Keeping the first frames that fit gives
    every later scan that many hits, at the same memory ceiling.
    """

    def __init__(self, reader, index, cache_bytes, transform):
        self.reader = reader
        self.index = index
        self.cache_bytes = cache_bytes
        self.transform = transform
        self.cache = {}
        self.cached_bytes = 0
        self._lock = threading.Lock()

    def get(self, k):
        fr = self.cache.get(k)
        if fr is not None:
            return fr
        fr = self.reader.read_frame(self.index, k)
        if self.transform is not None:
            fr = self.transform(fr)
        nbytes = fr['atoms'].nbytes + (fr['elements'].nbytes if fr['elements'] is not None else 0)
        with self._lock:
            if k not in self.cache and self.cached_bytes + nbytes <= self.cache_bytes:
                self.cache[k] = fr
                self.cached_bytes += nbytes
        return fr

    def clear(self):
        self.cache.clear()
        self.cached_bytes = 0


class LazyFrames(Sequence):
    """
    Read-only list of dump frames that parses each frame from disk on access.

    Drop-in for parse_dump's frame list: supports len(), integer (incl.
    negative) indexing, slicing (returns another LazyFrames), iteration and
    truthiness. Parsed frames are cached up to `cache_bytes`: a trajectory
    that fits is parsed once and then served from memory; for a larger one
    the frames that fit stay cached and the rest stream from disk, one
    frame at a time.

    Frame dicts are shared with the cache and must be treated as read-only;
    use set_transform() to derive per-frame data (e.g. a synthesized type
    column) so it survives cache eviction.

    Args:
        reader:      DumpReader — decides columns and dtype.
        index:       DumpIndex or None — from reader.index() (scanned if None).
        cache_bytes: int — Parsed-frame cache budget (0 = always stream).
        stride:      int — Keep every Nth frame, starting with the first.
        max_frames:  int or None — Keep at most this many frames (None/0 = all).
    """

    def __init__(self, reader, index=None, cache_bytes=DEFAULT_CACHE_BYTES,
                 stride=1, max_frames=None, transform=None, _store=None, _positions=None):
        if _store is None:
            if stride < 1:
                raise ValueError(f"stride must be >= 1, got {stride}")
            index = reader.index() if index is None else index
            _store = _FrameStore(reader, index, cache_bytes, transform)
            _positions = range(0, len(index), stride)
            if max_frames:
                _positions = _positions[:max_frames]
        self._store = _store
        self._positions = _positions
        self._shared = None

    def __len__(self):
        return len(self._positions)

    def __getitem__(self, i):
        if isinstance(i, slice):
            return LazyFrames(None, _store=self._store, _positions=self._positions[i])
        return self._store.get(self._positions[i])

    def __iter__(self):
        shared = self._shared
        if shared is not None:
            return shared.subscribe()
        return self._iter_range(0, len(self._positions))

    def _iter_range(self, begin, end):
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
        shared = _SharedPass(self, depth)
        self._shared = shared
        try:
            yield shared
        finally:
            self._shared = None
            shared.shutdown()

    def set_transform(self, transform):
        """Apply transform(frame) -> frame to every frame on load; clears the cache."""
        self._store.transform = transform
        self._store.clear()

    @property
    def reader(self):
        return self._store.reader

    @property
    def timesteps(self):
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
    def cache_bytes(self):
        return self._store.cache_bytes

    @property
    def fits_in_cache(self):
        return self.estimated_bytes <= self._store.cache_bytes


_END = object()


class _Failure:
    def __init__(self, exc):
        self.exc = exc


class _Subscriber:
    def __init__(self, depth):
        self.queue = queue.Queue(maxsize=depth)
        self.closed = False

    def put(self, item, stop):
        # Poll so a subscriber that stopped iterating cannot block the producer.
        while not self.closed and not stop.is_set():
            try:
                self.queue.put(item, timeout=0.05)
                return
            except queue.Full:
                continue

    def close(self):
        self.closed = True
        try:
            while True:
                self.queue.get_nowait()
        except queue.Empty:
            pass


class _SharedPass:
    """Producer/subscriber state behind LazyFrames.shared_pass()."""

    def __init__(self, view, depth):
        self._view = view
        self._depth = depth
        self._lock = threading.Lock()
        self._subs = []
        self._next = 0              # position the producer parses next
        self._producer = None
        self._stop = threading.Event()
        self.frames_parsed = 0

    def subscribe(self):
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

    def _consume(self, sub, start):
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

    def _produce(self):
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

    def shutdown(self):
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
    1. Scans for thermo header lines (containing 'Step' + energy keywords)
    2. Reads numeric data rows until a terminator is found
    3. Tracks simulation stages (spin_eq, minimize, equilibrate, oxidation)
    4. Extracts 'Loop time' values for performance analysis
    5. Normalizes column names (e.g., 'PotEng' -> 'pe', 'TotEng' -> 'etotal')
    6. Returns data from the LARGEST thermo block (= production run)

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

    def _as_block(headers, rows, stages):
        # Nested float lists cost ~32 bytes/value; keep finished blocks as ndarrays.
        return (headers, np.array(rows, dtype=np.float64), stages)

    blocks = []              # Accumulated thermo blocks: [(headers, ndarray, stages), ...]
    current_headers = None   # Column names for the current thermo block
    current_data = []        # Rows of numeric data for the current block
    current_stages = []      # Stage label for each row in the current block
    reading = False          # True when inside a thermo data block
    stage = "init"           # Current simulation stage label
    stage_times = {}         # Accumulated wall time per stage (seconds)

    with open(filepath, 'r') as fh:
        for raw in fh:
            line = raw.strip()
            low = line.lower()

            # --- Stage detection ---
            # LAMMPS input scripts often print stage markers via 'print' commands.
            # We look for keywords to classify the current simulation phase.
            if 'stage 0' in low or 'spin' in low:
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
            # A thermo header line contains 'Step' and at least one energy keyword.
            # When found, we start reading numeric data rows.
            if ('Step' in line and
                any(k in line for k in ('Temp', 'PotEng', 'TotEng', 'KinEng', 'pe', 'ke'))):
                if reading and current_data:
                    # Save the previous thermo block before starting a new one
                    blocks.append(_as_block(current_headers, current_data, current_stages))
                # Start a new thermo block with the detected column headers
                current_headers = line.split()
                current_data = []
                current_stages = []
                reading = True
                continue

            # --- End of thermo block ---
            # Thermo blocks end when LAMMPS prints a summary line, error,
            # warning, or starts a new command (minimize, etc.).
            if reading and ('Loop time' in line or line.startswith('ERROR') or
                            line.startswith('WARNING') or 'cg style' in low or
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

    # Reassemble the FULL run rather than only the largest thermo block.
    #
    # A multi-stage simulation writes one thermo block per run/minimize
    # (spin-eq, minimize, equilibrate, oxidation, ...). Keeping only the
    # largest block silently dropped every other stage — the ACE runs, for
    # instance, lost the first ~170 ps (spin equilibration + thermalization)
    # from every thermo/pressure plot. Concatenate all blocks that share the
    # production block's column layout, ordered by step with duplicated
    # boundary steps removed. Blocks printed with a different thermo_style
    # (mismatched headers, e.g. a minimization block) are left out because
    # their columns do not align.
    headers = max(blocks, key=lambda x: len(x[1]))[0]
    merged_data, stages = [], []
    for hdr, data, stg in blocks:
        if hdr == headers:
            merged_data.append(data)
            stages.extend(stg if len(stg) == len(data) else [''] * len(data))
    arr = np.concatenate(merged_data)

    # Order by step and drop rows whose step repeats (block boundaries print
    # the same step twice). These templates use one monotonic step counter, so
    # this never collapses distinct data; a restart that reset the counter would.
    step_cols = [i for i, h in enumerate(headers) if h.lower() == 'step']
    if step_cols and len(arr):
        si = step_cols[0]
        order = np.argsort(arr[:, si], kind='stable')
        arr = arr[order]
        stages = [stages[k] for k in order]
        _, first = np.unique(arr[:, si], return_index=True)
        keep = np.sort(first)
        arr = arr[keep]
        stages = [stages[k] for k in keep]

    # Build the result dict with normalized column keys
    result = {'headers': headers, 'stages': stages, 'stage_times': stage_times,
              'raw_blocks': blocks}

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
    Also works with 'charge' atom style (id type q x y z) by reading
    the first 5 numeric columns. For charge style, the charge column
    is skipped — use dump files for charge analysis.

    Args:
        filepath: str — Path to the LAMMPS data file.

    Returns:
        atoms:  np.array shape (N, 5) — [id, type, x, y, z] for each atom.
                Returns empty array (0, 5) if no atoms found.
        box:    np.array shape (3, 2) — [[xlo, xhi], [ylo, yhi], [zlo, zhi]].
                Returns empty array if no box bounds found.
        masses: dict[int, float] — Atom type ID -> mass in atomic mass units.
    """
    atoms = []
    box = []
    masses = {}
    in_atoms = False    # True when reading the 'Atoms' section
    in_masses = False   # True when reading the 'Masses' section
    atom_style = None   # 'charge' or 'atomic', detected from header

    with open(filepath, 'r') as f:
        for line in f:
            stripped = line.strip()

            # --- Box bounds (in the header, before any sections) ---
            # Format: "xlo xhi xlo xhi" or similar
            if 'xlo' in stripped and 'xhi' in stripped:
                parts = stripped.split()
                box.append([float(parts[0]), float(parts[1])])
            elif 'ylo' in stripped and 'yhi' in stripped:
                parts = stripped.split()
                box.append([float(parts[0]), float(parts[1])])
            elif 'zlo' in stripped and 'zhi' in stripped:
                parts = stripped.split()
                box.append([float(parts[0]), float(parts[1])])

            # --- Section header detection ---
            # Sections are delimited by keyword lines ('Masses', 'Atoms', etc.)
            if stripped.startswith('Masses'):
                in_masses = True
                in_atoms = False
                continue
            if 'Atoms' in stripped:
                in_atoms = True
                in_masses = False
                # Detect atom style from header: "Atoms # charge" or "Atoms # atomic"
                if '# charge' in stripped:
                    atom_style = 'charge'
                elif '# atomic' in stripped:
                    atom_style = 'atomic'
                continue
            if stripped.startswith('Velocities') or stripped.startswith('Bonds'):
                in_atoms = False  # End of Atoms section
                continue

            # --- Masses section: "type_id  mass" ---
            if in_masses and stripped and not stripped.startswith('#'):
                parts = stripped.split()
                if len(parts) >= 2:
                    try:
                        masses[int(parts[0])] = float(parts[1])
                    except ValueError:
                        pass

            # --- Atoms section ---
            # atomic style: "id type x y z"           (5 columns)
            # charge style: "id type q x y z"         (6+ columns)
            if in_atoms and stripped and not stripped.startswith('#'):
                parts = stripped.split()
                if len(parts) >= 5:
                    try:
                        # Determine xyz column offset based on atom style
                        if atom_style == 'charge' or (atom_style is None and len(parts) >= 6):
                            # charge style: id(0) type(1) q(2) x(3) y(4) z(5)
                            xyz_off = 3
                        else:
                            # atomic style: id(0) type(1) x(2) y(3) z(4)
                            xyz_off = 2
                        atoms.append([int(parts[0]), int(parts[1]),
                                      float(parts[xyz_off]), float(parts[xyz_off+1]),
                                      float(parts[xyz_off+2])])
                    except (ValueError, IndexError):
                        pass

    return (np.array(atoms) if atoms else np.empty((0, 5)),
            np.array(box) if box else np.empty((0, 2)),
            masses)


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
    base_dir = os.path.dirname(os.path.abspath(filepath))

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

    # Pre-process: read file, handle continuations and includes
    def _read_lines(fpath):
        lines = []
        try:
            with open(fpath, 'r') as f:
                raw_lines = f.readlines()
        except (OSError, IOError):
            return lines
        i = 0
        while i < len(raw_lines):
            line = raw_lines[i].rstrip('\n')
            # Handle line continuation with &
            while line.rstrip().endswith('&'):
                line = line.rstrip()[:-1].rstrip()
                i += 1
                if i < len(raw_lines):
                    line += ' ' + raw_lines[i].strip()
                else:
                    break
            # Handle include
            stripped = line.strip()
            if stripped.lower().startswith('include'):
                parts = stripped.split(None, 1)
                if len(parts) == 2:
                    inc_path = os.path.join(base_dir, parts[1].strip())
                    lines.extend(_read_lines(inc_path))
            else:
                lines.append(line)
            i += 1
        return lines

    logical_lines = _read_lines(filepath)
    current_stage = 'init'

    def _resolve_numeric(val_str):
        """Resolve a LAMMPS ${var} or $X reference to a float value.

        Looks up the variable name in config['z_variables'] (numeric values
        already parsed from 'variable ... equal ...' lines), then falls back
        to extracting the first numeric token from config['variables'].
        Returns float or None if unresolvable.
        """
        m = re.match(r'^\$\{(\w+)\}$|^\$(\w)$', val_str)
        if not m:
            return None
        varname = m.group(1) or m.group(2)
        # z_variables has floats from 'variable X equal <number>'
        if varname in config['z_variables']:
            return config['z_variables'][varname]
        # Fall back: parse from raw variable definition
        if varname in config['variables']:
            defn_parts = config['variables'][varname].split()
            # 'index 600' or 'equal 0.00025' → try the second token
            if len(defn_parts) >= 2:
                try:
                    return float(defn_parts[1])
                except ValueError:
                    pass
        return None

    for line in logical_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        # Remove inline comments (but not inside quotes)
        if '#' in stripped:
            in_quote = False
            for ci, ch in enumerate(stripped):
                if ch == '"':
                    in_quote = not in_quote
                elif ch == '#' and not in_quote:
                    stripped = stripped[:ci].rstrip()
                    break

        parts = stripped.split()
        if not parts:
            continue
        cmd = parts[0].lower()

        if cmd == 'units' and len(parts) >= 2:
            config['units'] = parts[1]
        elif cmd == 'atom_style' and len(parts) >= 2:
            config['atom_style'] = parts[1]
        elif cmd == 'boundary' and len(parts) >= 4:
            config['boundary'] = parts[1:4]
        elif cmd == 'pair_style':
            config['pair_style'] = ' '.join(parts[1:])
        elif cmd == 'pair_coeff':
            # pair_coeff * * <potential_file> <elem1> <elem2> ...
            if len(parts) >= 4 and parts[1] == '*' and parts[2] == '*':
                potential_file = parts[3]
                elements = [e for e in parts[4:] if not e.startswith('-')]
                config['pair_coeff'] = {
                    'potential_file': potential_file,
                    'elements': elements,
                }
                for i, elem in enumerate(elements):
                    if elem.upper() != 'NULL':
                        config['element_map'][i + 1] = elem
        elif cmd == 'timestep' and len(parts) >= 2:
            try:
                config['timestep'] = float(parts[1])
            except ValueError:
                # Resolve LAMMPS variable references like ${dt}
                resolved = _resolve_numeric(parts[1])
                if resolved is not None:
                    config['timestep'] = resolved
        elif cmd == 'read_data' and len(parts) >= 2:
            config['read_data'] = parts[1]
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
        elif cmd == 'variable' and len(parts) >= 4:
            vname = parts[1]
            config['variables'][vname] = ' '.join(parts[2:])
            if parts[2] == 'equal':
                try:
                    config['z_variables'][vname] = float(parts[3])
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
            config['dt_fs'] = config['timestep']

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

        return {
            'forcefield': 'reaxff',
            'unit_system': 'real',       # kcal/mol, Angstrom, fs
            'dt_fs': 0.25,               # Typical ReaxFF timestep: 0.25 fs
            'has_charge': True,
            'has_velocity': 'vx' in cols_set,
            'has_element': False,
            'atom_types': type_map,
        }

    # --- Detection Rule 2: Element column with 'Mn' → ACE with spin tracking ---
    has_element = frames and frames[0].get('elements') is not None

    if has_element:
        elements = set(frames[0]['elements'])
        if 'Mn' in elements:
            # 'Mn' is used as a proxy for spin-down Fe in ACE magnetite simulations.
            # Real Mn is NOT present — it's a labeling convention from the potential.
            # atom_types is keyed by type NUMBER, like every other rule: callers
            # (state._guess_o_type, state._guess_surface_z, shell's type labels)
            # index it with the numeric type column. Element-keyed entries used to
            # slip past their `isinstance(t, int)` guards and silently degrade to
            # a "Fe is type 1 only" fallback, which drops Fe_down.
            return {
                'forcefield': 'ace',
                'unit_system': 'metal',   # eV, Angstrom, ps
                'dt_fs': 0.25,            # ACE Fe-O potential uses 0.00025 ps = 0.25 fs
                'has_charge': False,
                'has_velocity': 'vx' in cols_set,
                'has_element': True,
                'atom_types': type_to_label('ace'),
            }

    # --- Detection Rule 3: ≥ 3 atom types → ACE (spin-resolved) ---
    if frames and 'type' in col_idx:
        types = frames[0]['atoms'][:, col_idx['type']].astype(int)
        max_type = int(types.max())

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

            return {
                'forcefield': 'ace',
                'unit_system': 'metal',
                'dt_fs': 0.25,            # ACE Fe-O potential uses 0.00025 ps = 0.25 fs
                'has_charge': False,
                'has_velocity': 'vx' in cols_set,
                'has_element': has_element,
                'atom_types': type_map,
            }

    # --- Detection Rule 4: Default → HDNNP ---
    # Two types without charge = 4G-HDNNP (or any simple 2-type potential)
    return {
        'forcefield': 'hdnnp',
        'unit_system': 'metal',
        'dt_fs': 1.0,
        'has_charge': False,
        'has_velocity': 'vx' in cols_set,
        'has_element': has_element,
        'atom_types': type_to_label('hdnnp'),
    }


