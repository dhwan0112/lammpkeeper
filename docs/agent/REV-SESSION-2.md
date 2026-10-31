# REV-SESSION-2 — spin analysis vs. the active species map

Status: implemented, parent verification pending.

## Problem
With explicit canonical ACE input and `set types 1=Fe_down 2=Fe_up 3=O`, the
active `SpeciesMap` resolves `Fe_up = {2}`, but `analyze spin` still counted fixed
type 1 as up (`n_up=[2,2]`, `up_fraction=0.667` on the probe) and plots labelled
those counts Fe_up/Fe_down.

## Decision
`analyze_spin_evolution` (analysis.py) stays unchanged: it reads the canonical ACE
type channels from `label_to_type('ace')` (`Fe_up=1`, `Fe_down=2`, `O=3`;
mapping.py, confirmed). `_analyze_spin` in `lammps_post/shell.py` now compares the
active map's `Fe_up` and `Fe_down` selections with exactly those slots before
computing. Any difference (manual override, input/data labels, groups, missing
labels) raises `ValueError` naming the active selections and canonical slots; the
command fails (batch/one-shot exit nonzero) and no `spin` cache entry exists.
The old `spin` entry is dropped at entry, so a failed retry cannot be plotted.
Canonical sessions produce bit-identical results (tested against the kernel and
the committed fixture: 64 up / 128 down at frame 0).

## Rejected alternative
Honoring overrides (feeding the active Fe_up/Fe_down selections to the kernel)
would redefine spin semantics and the canonical convention (a species-mapping
human gate) and would need a kernel API change plus golden review. Not done.

## Cache invalidation (checked)
`set types` calls `_invalidate_metadata` -> `state.clear_cache()`, so a `spin`
result computed before a species change is already discarded; the plot path
(`_ensure_cache('spin', '_analyze_spin')`) then recomputes and hits the new check.
Tested; no new provenance system (REV-SESSION-3).

## Evidence
Tests: `tests/test_spin_species.py` (7). On unmodified code 4 failed, 3 passed
(swap, missing labels, stale-cache retry, batch exit code failed). With the fix
all pass.
