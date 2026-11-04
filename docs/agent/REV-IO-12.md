# REV-IO-12: non-increasing dump timesteps warn

Status: fixed and verified (PR #98).
Branch: `fix/dump-timestep-order` from main `0a5b4fc`.
Source: AUDIT-20261104 finding B-R1 (P2, silent wrong time axes).

## Problem

Every time-dependent analysis (MSD, penetration, charge and coordination time
series) builds its time axis from frame step numbers (`timestep * dt_fs`).
Neither the reader nor any analysis checked that the steps increase. A
concatenated or restarted dump with steps 0, 100, 50, 50 loaded without a
message, and its time axes repeated or ran backwards.

## Change

`lammps_post/parsers.py`: `DumpReader._check_step_order` runs for every frame
header on the streaming path (`__iter__`, including stride-skipped frames, so
`parse_dump` too) and on the index path (`index()`, so `read_frame`,
`LazyFrames` and the shell). The first step that is not larger than the one
before it issues one `RuntimeWarning` per pass:

```
<path>: dump timesteps are not strictly increasing: step 50 follows step 100 (frame 2); time axes built from step numbers will repeat or run backwards. Remove duplicated or overlapping frames (e.g. from restarts) before time-dependent analyses
```

Frames are still returned in file order. Nothing is dropped or sorted, because
which copy of a repeated step is right depends on how the run was restarted.

Why a warning and not an error: the audit asked for "a visible rejection or
warning". A dump with one repeated restart frame is common and its structural
analyses (RDF, density, last-frame structure) remain valid, so raising would
reject usable files. Raising in time-dependent analyses is a separate behaviour
decision and is listed under Follow-up.

| Steps | Before | After |
| --- | --- | --- |
| strictly increasing | loads | unchanged, no warning |
| repeated (restart overlap) | loads silently | loads, one warning |
| decreasing (concatenated runs) | loads silently | loads, one warning |

## Tests

`tests/test_dump_step_order.py` (registered in `tests/run.py`), 4 tests. The
three warning tests **failed before the fix** (no warning was issued).

- Steps 0, 100, 50, 50, 200: stream, strided stream, `parse_dump` and
  `LazyFrames` keep file order and warn exactly once, naming step 50 after 100
  at frame 2.
- A duplicated restart frame warns on the stream and index paths.
- Increasing steps (including a single frame) never warn.
- `load dump` in the shell reports the warning and keeps the frames.

Verification: full runner native 786 passed / 0 failed / 26 skipped, NumPy
(`LKPR_NO_NATIVE=1`) 773 / 0 / 39. Two existing tests whose fixture dumps
repeat a step (`test_audit_workflow`, a triclinic session test) now emit the
warning; it is correct for their data and neither asserts warning silence.

## Follow-up

- Time-dependent analyses could raise on a non-increasing time axis instead of
  relying on the load warning. That changes accepted inputs and needs a
  maintainer decision.
