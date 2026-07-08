# LammpKeeper (`lkpr`) — Migration Notes

Consolidation of the two independent CLIs (`lammps-pre`, `lammps-post`) under a
single entry point `lkpr` with `prep` / `post` subcommands.

**Primary goal:** unify the entry point *without changing any numeric or physical
behavior.* Shared-module extraction and refactoring come later, with regression
checks.

---

## Stage 1 — dispatcher-only (current)

Minimal, non-destructive. No files were moved; no analysis/physics code changed.

### What was added
| File | Purpose |
|------|---------|
| `lammpkeeper/__init__.py` | package + single `VERSION` |
| `lammpkeeper/cli.py` | top-level `lkpr` router (`main`) |
| `lammpkeeper/__main__.py` | `python -m lammpkeeper` support |
| `pyproject.toml` | packaging; `lkpr = "lammpkeeper.cli:main"`; extras `[prep]`/`[post]`/`[all]` |

### What was changed (minimal, backward-compatible)
- `lammps_pre/cli.py` — `def main():` → `def main(argv=None):`, and
  `parser.parse_args()` → `parser.parse_args(argv)`.
- `lammps_post/cli.py` — same two-line change.

Because `argv` defaults to `None` and `parser.parse_args(None)` reads `sys.argv`,
every existing invocation behaves **exactly** as before.

### How dispatch works
`lkpr <command> <args...>` forwards `<args...>` **verbatim** to the existing
sub-CLI:

```
lkpr prep --ff ace --temp 500 --o2 100 --write ./out/
      └── lammps_pre.cli.main(['--ff','ace','--temp','500','--o2','100','--write','./out/'])

lkpr post --log log.lammps --plot thermo --theme publication
      └── lammps_post.cli.main(['--log','log.lammps','--plot','thermo','--theme','publication'])
```

The top-level parser owns only `lkpr -h` and `lkpr --version`; it does **not**
re-declare subcommand flags, so each subcommand keeps its own argparse
definitions, help text, `--version` string, and exit behavior unchanged.

### Backwards compatibility (unchanged, still works)
- `python -m lammps_pre ...` / `python lammps-pre.py ...`
- `python -m lammps_post ...` / `python lammps-post.py ...`

### Decisions made to preserve behavior
- **No file moves / no import rewrites.** The physical reorg into
  `lammpkeeper/{prep,post,common}/` is Stage 2, so Stage-1 risk stays near zero.
- **Flags are namespaced under subcommands**, so the pre-existing flag
  differences are not conflicts (e.g. prep `--write` vs post `--output`,
  prep `--ff` vs post `--format`). They are left as-is; harmonizing them is a
  Stage-2 decision and would be flagged before any change.
- **Indentation:** new `lammpkeeper/` files use 3-space indentation (project
  guardrail). The pre-existing `lammps_pre` / `lammps_post` packages remain
  4-space; edits within them preserve their existing 4-space style. (Style split
  noted here intentionally.)

---

## Stage 2 — refactoring (incremental, each step regression-verified)

Guarded by before/after baselines. Each step is a pure/value-preserving refactor
verified against the committed prior state, then committed.

### Completed

**Step A — `common/display.py`.** `display.py` was byte-identical in both
packages. Moved to the single source of truth; both package modules are now
re-export shims. Verified: rendered display API and CLI snapshots
(`post --find`, no-data error, `--help`) byte-identical before/after; object
identity `lammps_pre.display.C is lammps_post.display.C is
lammpkeeper.common.display.C`.

**Step B — `common/mapping.py`.** Single source of truth for the per-force-field
`type↔element↔label` convention, replacing three independent copies:
`lammps_pre.state.FF_PRESETS` (forward), `lammps_post.parsers.detect_forcefield`
(reverse: ACE element dict, ReaxFF/HDNNP fallbacks), and
`lammps_post.analysis.analyze_spin_evolution` (hardcoded ACE types 1/2/3).
Value-preserving; does **not** alter post's atom-count heuristic (the separate,
still-open reverse-map fragility — documented below).

Regression record (fixture `regular_MD/traj.dump`, 448 atoms, 350 frames, ACE
element-path; numpy-only). Canonical fingerprint of prep `FF_PRESETS` atom_types,
post `ff_info`/`_guess_o_type`, RDF(Fe↑–O), MSD(O), MSD(Fe↑), and spin —
**identical before/after** (44 KB canonical blob byte-for-byte; TOTAL sha256
`6a3b93bc…`). Note: this fixture exercises the deterministic element path, not
the count heuristic (Rule 3) or slab z-PBC / 2D-MSD paths — those remain
unverified and are out of scope for this value-preserving step.

### Regression suite (`tests/`)

The ad-hoc before/after checks are now a committed suite that locks in Stage 1+2
behavior. Runs with **or without** pytest:

```
python tests/run.py          # dependency-free runner (numpy-only)
LKPR_SLOW=1 python tests/run.py   # include RDF/MSD golden checks
pytest tests/                # if pytest installed (pip install -e .[dev])
```

- `test_mapping.py`   — canonical tables + prep/post value preservation.
- `test_display.py`   — single-source object identity + rendering.
- `test_lkpr_cli.py`  — dispatcher routing + verbatim delegation (sub-versions).
- `test_regression_numeric.py` — golden fingerprints (ff_info, spin, RDF, MSD)
  on the ACE example trajectory; skips cleanly if numpy/fixture absent.

### Planned (still behavior-sensitive — flag before doing)

- `forcefields.py` — reconcile FF naming (`prep`: ace/reaxff2010/reaxff2015 vs
  `post`: reaxff/ace/hdnnp) and shared units/dt/atom_style metadata.
- `lammps_data.py` — the data-file format contract shared by prep (write) and
  post (read).
- `units.py` — ps↔fs↔steps conversion (note: prep `ps_to_steps` and post `dt_fs`
  derivation are *different* operations; shared surface is only the metal-vs-real
  convention, so payoff is small).
- Reverse-map fragility fix (behavior/format change): make prep emit
  `dump_modify element Fe Mn O` so post reverse-maps ACE deterministically
  instead of via the atom-count heuristic. Requires re-confirming the
  "same coordinates, format-only difference" fair-comparison invariant.
- Promoting `--batch`/`--version` to a parent parser cuts against the current
  forward-verbatim dispatcher — needs a design decision first.
- Optionally move packages into `lammpkeeper/prep/` and `lammpkeeper/post/` and
  update imports (with a compatibility shim for external references).

### Known invariants to re-verify in Stage 2 (do NOT change in Stage 1)
- **ACE type↔element mapping (top priority).** prep writes ACE trajectories with
  **no element labels** (`id type x y z ...`), and all Fe as type 1 at build time
  (Fe_down/type 2 is created at runtime by `set type/fraction`). So
  `lammps_post`'s deterministic detector (element `Mn` → Fe_down) never fires on
  prep output; it falls back to an atom-count heuristic to guess which type is O.
  It is correct for the canonical `{1:Fe_up, 2:Fe_down, 3:O}` layout but fragile
  under strong spin imbalance, and post additionally uses a *second* mechanism
  (spin analysis hard-codes types 1/2/3). Neither reads prep's convention →
  motivation for `common/mapping.py`.
- **Physics (located, not yet numerically verified):** RDF O₂ intramolecular
  exclusion; slab (`p p f`) z-PBC handling (confirmed off for slab); MSD 2D/3D
  dimensionality factor in the diffusion-coefficient extraction; charge
  Fe⁰/Fe²⁺/Fe³⁺ classification; O₂ dissociation cutoff (~1.8 Å). These are the
  documented "previously bug-prone" spots and are the subject of Stage-2
  regression, not Stage-1 edits.
