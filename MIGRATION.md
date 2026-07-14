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

### End-to-end verification with a real LAMMPS run

The regression suite above only replays a committed trajectory. This section
records an actual `lkpr prep` → **LAMMPS** → `lkpr post` cycle, run to check
that the unified entry point produces inputs LAMMPS accepts and output `post`
reads back correctly.

**Setup.** LAMMPS 22 Jul 2025 (`REAXFF`, `ML-PACE`, `ML-HDNNP` built in);
`lkpr` installed as a real console script (`pip install -e .`) into a venv over
the conda `mlff` env (ase, scipy, pandas, matplotlib, MDAnalysis, rich present).
Fe(100) 4×4×8 slab, 4 O₂, 800 K, `p p f`, seed 12345 — same defaults as
production, only smaller and shorter.

| Check | Result |
|-------|--------|
| `lkpr prep` → LAMMPS-valid inputs (ReaxFF-2010) | ✅ ran to completion, 12 ps oxidation, 502 frames |
| `lkpr prep` → LAMMPS-valid inputs (ACE) | ✅ data/regions/script accepted; stages 0–2 ran (see MC note below) |
| `lkpr post --analyze all --plot all` (ReaxFF) | ✅ 14 analyses, 16 figures |
| `lkpr post --analyze all --plot all` (ACE) | ✅ 12 analyses, 14 figures |
| units / atom_style per FF, read back from the generated script | ✅ reaxff = real+charge, ace = metal+atomic |
| prep forward map == post reverse map (real dumps) | ✅ reaxff `{1:Fe,2:O}`, ace `{1:Fe_up,2:Fe_down,3:O}` |
| dt / time axis agreement (prep preset vs post detection) | ✅ 0.25 fs both, units agree |
| Legacy entry points still work | ✅ `python -m lammps_pre/-post`, `lammps-pre.py`, `lammps-post.py` |
| Regression suite under the **full** dependency set | ✅ 13 passed (same golden hashes as numpy-only) |

**LAMMPS confirms the ACE spin convention.** The `pace` pair style echoed
`type #1(Fe) → ACE species #1`, `#2(Mn) → #2`, `#3(O) → #3`, and the runtime
`set … type/fraction` produced real type-2 atoms (counts `{1:41, 2:87, 3:8}`).
`post` read that label-less dump back as `{1:Fe_up, 2:Fe_down, 3:O}` and
reported an Fe_up fraction of 0.320 = 41/128 exactly.

**Physics checks on the real ReaxFF oxidation** (not just "no exception"):
O₂ dissociation 4 → 1 (6 O atoms dissociated) — matched atom-by-atom against
raw O–O distances; QEq total charge conserved to 0.000000 e; Fe positive
(max +0.455 e) / O negative (mean −0.738 e); Fe⁰=124 / Fe²⁺=4 / Fe³⁺=0,
consistent with the reported "oxidized Fe (q>0.3) = 4". `compute_rdf` was
validated against Fe–O distances computed directly from the coordinates
(RDF peak 1.57 Å vs true bonded mean 1.53 Å) — **the RDF code is faithful.**

*Observation (pre-existing, not caused by this work):* those Fe–O bonds are
short versus the literature (~1.9–2.1 Å). The repo's own production result
(`lammps/Runs/reaxff2010/o2_100/800K/final_reaxff2010_800K.data`, 2000 Fe +
200 O) shows the same thing — Fe–O mean 1.600 Å, Fe–Fe 2.379 Å — against
1.571 Å / 2.371 Å here. So this run **reproduces the existing production
physics**; the short bond is a property of the ReaxFF-2010 setup, worth a
separate look but unrelated to the CLI integration.

### Issues found by the end-to-end run (open — need a decision)

1. **Coordinates are not bit-identical across force fields (your call).** The
   brief states all force fields should use *identical coordinates, differing
   only in format*. The Fe slab does satisfy this exactly (bit-identical between
   the ReaxFF and ACE builds). The O₂ layer does not: it sits exactly 2.0 Å
   higher in the ACE build, and the box is 2.0 Å taller. Cause: `builders.py`
   `z_wall_lower = z_nve_top + rc + 0.9`, and *both* the O₂ placement band
   (`z_lo = z_wall_lower + 1.0`) and the box top (`zhi = z_wall_lower + vacuum`)
   are anchored to it — so the FF-specific cutoff (ACE 7.0 Å vs ReaxFF 5.0 Å)
   leaks into the initial geometry.

   How much this matters is a separate question, and the honest answer is
   "probably very little": the O₂ are a thermal gas placed at random heights
   within a band, they diffuse for several ps before reaching the surface (the
   ReaxFF run above took ~2.2 ps), the shift is a rigid translation of the whole
   band, and *relative to the reflective wall* — which is what the O₂ actually
   sees, and which is removed before oxidation starts — the placement is
   identical. So this is a literal violation of the stated invariant with a
   plausibly negligible physical effect. Flagged rather than fixed, because
   changing it changes every generated structure.

2. **ACE reverse-map heuristic: concrete failure boundary (high).** prep emits
   ACE dumps with no element column (`id type x y z vx vy vz`), so post's
   deterministic Rule 2 can never fire and Rule 3 (atom-count heuristic) is
   always used. It is correct for this run ({1:41, 2:87, 3:8} → right answer),
   but it breaks once the minority spin population drops to about the O count:
   e.g. 400 Fe_up / 3600 Fe_down / 400 O yields `{2:Fe_up, 3:Fe_down, 1:O}` —
   Fe_up is misread as O and every O-based analysis silently becomes garbage.
   Strong spin polarization is a physically reachable state (the MC swap is
   semi-grand with µ=0), so this is not hypothetical. The already-planned fix
   (`dump_modify element Fe Mn O`) removes the heuristic entirely.

3. **The local LAMMPS cannot run prep's ACE script (medium).**
   `/home/kdh/chemistry/lammps/install/bin/lmp` is built without the **MC**
   package, so `fix atom/swap` (the spin-swap MC in the ACE template) aborts the
   run. Everything before it is fine. Rebuild with `-D PKG_MC=on` to run ACE
   locally; the HPC binary evidently has it. (Verification here used a copy with
   only that one `fix` line commented out.)

4. **ACE template cannot produce a short oxidation run (low).**
   `ox_dense = round(50.0/dt)` is hardcoded and `ox_remain = round((OX_PS-50)/dt)`,
   so any `OX_PS < 50` emits a negative `run` count and LAMMPS errors out. The
   oxidation stage is therefore always ≥ 200 000 steps — fine for production,
   impossible for a smoke test.

5. **prep has no HDNNP/CHGNet preset (question).** post can detect `hdnnp`
   (Rule 4), but prep only generates `ace` / `reaxff2010` / `reaxff2015`. If the
   4-force-field comparison is the goal, prep is missing two.

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
