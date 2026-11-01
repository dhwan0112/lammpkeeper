# GEN-2a — run metadata model, pair-style classifier, additive parser output

Status: implemented and fully verified by the parent;
[PR #48](https://github.com/dhwan0112/lammpkeeper/pull/48).
Branch: `gen/gen-2a-run-metadata` (base main `7192e64`). ADR-0005 steps 1–2 only.

> **Superseded in part by GEN-2b** (PR #49, `docs/agent/GEN-2b.md`; noted in
> the 2026-11-01 audit). This file records the GEN-2a stage. Since GEN-2b the
> legacy `forcefield` key uses the exact classifier (no substring match), and
> contradictory repeated `atom_style` / `pair_style` declarations raise. The
> "Unchanged on purpose" and "Decisions to review" sections below describe
> GEN-2a only.

## What changed

- `lammpkeeper/io/metadata.py` (new): frozen `MetadataField(value, raw, status,
  source, note)` and `RunMetadata(pair_style, ff_family, atom_style, units,
  timestep, dt_fs)`. Status is `explicit`, `guessed` or `unresolved`; an
  unresolved field must hold `None`. `RunMetadata.from_explicit` builds from
  declared input commands; `from_guess` wraps a `detect_forcefield` dict;
  `describe()` lists each field with status and source/reason;
  `derive_dt_fs(units, timestep)` converts only `metal` (ps, x1000) and `real`
  (fs). No element names, force-field presets or domain constants live here.
- `lammps_post/parsers.py`: module-level `classify_pair_style(text)` (exact
  first-token alias table, case-sensitive; `None` for empty input; everything
  else, including hybrid styles, is `'generic'`), and `parse_input` now adds
  `config['metadata']`.
- `lammpkeeper/io/__init__.py`: exports only.
- `tests/test_run_metadata.py` (new, 23 tests). **Not yet registered in
  `tests/run.py`** (parent-owned).

## Behavior change (documented exception allowed by ADR-0005)

`parse_input` now raises `ValueError` (with the file path and both values) when
one input declares `timestep` twice with different resolved values. Equal
repeats (also via variables/arithmetic) are accepted. Previously the last
declaration silently won.

## Unchanged on purpose

All existing `parse_input` keys keep their values, including the legacy
substring-based `forcefield` and the `dt_fs` key. Nine synthetic inputs (ACE,
ReaxFF, HDNNP, EAM, hybrid, filename trap, units only, timestep only, atom_style
only) were captured on unmodified main and are pinned in the test. The shell
still consumes the legacy keys; nothing routes through `metadata` yet.
`parse_input` still rejects units other than metal/real (existing behavior), so
`units lj` is only reachable through `RunMetadata.from_explicit` for now.

## Verified against the LAMMPS manual (docs.lammps.org, 2026-11-01)

Verified (present in pair_pace / pair_reaxff / pair_hdnnp / Commands_pair):
`pace`, `pace/extrapolation`, `pace/kk`, `pace/extrapolation/kk`, the APIP
variants `pace/apip`, `pace/fast/apip`, `pace/precise/apip`; `reaxff`,
`reaxff/kk`, `reaxff/omp`; `hdnnp`.

Assumed, not in the current manual: `reax/c`, `reax/c/kk`, `reax/c/omp`
(historical ReaxFF names kept because the legacy parser accepted `reax/c`).

Deliberately not recognized: `ace` and `n2p2` as pair-style names (ADR-0005's
text lists them as aliases, but neither is a LAMMPS pair style; `n2p2` is the
library behind `hdnnp`), bare `reax`, and any substring or filename. They
classify as `generic`. The legacy `forcefield` key still matches `ace`/`n2p2`
substrings until GEN-2b. If the maintainer wants those two tokens accepted
anyway, add them to `_PAIR_STYLE_FAMILIES` and flip two test rows.

## Decisions to review

- `from_guess` marks only values the heuristic produced (family, units, dt_fs)
  as `guessed`; pair_style, atom_style and native timestep stay `unresolved`
  rather than being invented.
- Repeated `atom_style` and multiple `pair_style` commands are not conflict-
  checked in this stage (last wins, as before). ADR-0005 asks to reject
  contradictory declarations; only timestep was authorized for now.

## What GEN-2b must do

1. Route the shell/session through `config['metadata']`, replacing the legacy
   `config['forcefield']`/`dt_fs` consumers; then remove the substring logic.
2. Candidate-resolution transactions for load/replace/unload with rollback and
   cache invalidation; log-versus-input disagreement checks in either order.
3. `--input PATH` preload flag, CLI help and CHANGELOG entry.
4. Manual `set dt` / `set forcefield` overrides stored separately, with the
   ADR lifetime rules, and `generic` added to the forcefield choices.
5. Status output using `RunMetadata.describe()`; generic family gets no Fe/O
   labels, spin analysis or FF dt default.
6. Decide conflict rules for repeated `atom_style`/`pair_style`, and prove Fe-O
   goldens unchanged without rebaselining.

## Parent integration (2026-11-01, measured)

- Reviewed the diff: the io model holds no element/FF literals; the alias table
  and classifier live in `parsers.py`; legacy `config['forcefield']`/`dt_fs` are
  untouched. Added docstrings to two nested helpers in `metadata.py`.
- ADR-0005 gained an "Implementation clarification" recording the verified
  alias list and why `ace`/`n2p2` are not aliases (older n2p2 `nnp` inputs are
  classified `generic`, the safe direction).
- Fail-before reproduced by the parent: against main's `parsers.py` the new
  module cannot even import (`classify_pair_style` missing); with the change
  **23 passed**. (Worker's per-test count with only `metadata.py` present:
  6 passed, 17 failed.)
- Registered `test_run_metadata` in `tests/run.py`; BACKLOG and CHANGELOG updated.
- Full verifier on `dfd3227`: native **612 passed, 0 failed, 0 skipped**; forced
  NumPy **603 passed, 0 failed, 9 skipped** (six known native-only checks plus
  three REV-IO-4 native-comparison tests). Post analyses/real plots and prep
  passed. Evidence: `/tmp/opencode/g2a-native/20261101T121256-dfd3227-full`,
  `/tmp/opencode/g2a-numpy/20261101T121258-dfd3227-full`. Native extension not
  rebuilt; pytest, MDAnalysis, Python 3.9 runtime and HPC not run.
