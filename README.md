# LammpKeeper (`lkpr`)

A unified command-line tool for **pre- and post-processing LAMMPS simulations**
of iron oxidation/reduction with machine-learned and reactive force fields
(ACE, ReaxFF, 4G-HDNNP).

One entry point, two subcommands:

```
lkpr prep …    # build slabs + O2, generate LAMMPS input scripts
lkpr post …    # analyze & plot trajectories (RDF, MSD, charge, O2 dissociation, spin…)
```

The design goal is **multi-force-field format consistency**: every force field
starts from *identical coordinates* and differs only in file format, so a
comparison across force fields is fair by construction. The type↔element
convention (including the ACE spin encoding — type 1 = Fe↑, type 2 = Fe↓ via the
`Mn` slot, type 3 = O; Bienvenu et al., *npj Comput. Mater.* **11**, 81, 2025)
lives in a single shared module so prep and post can never disagree.

## Install

```bash
pip install -e .            # core (numpy)
pip install -e .[prep]      # + ASE (structure generation)
pip install -e .[post]      # + matplotlib, scipy, pandas, MDAnalysis (analysis)
pip install -e .[all]       # everything, incl. rich
pip install -e .[dev]       # + pytest
```

Requires Python ≥ 3.9. After install the `lkpr` command is on your PATH; you can
also run it without installing via `python -m lammpkeeper`.

## Usage

```bash
# Pre-processing: build a slab + O2 and write LAMMPS inputs
lkpr prep --ff ace --temp 800 --o2 4 --slab 4x4x8 --write ./run/

# Interactive mode (tab completion, live preview)
lkpr prep

# Post-processing: analyze a trajectory and make publication plots
lkpr post --dump traj.lammpstrj --log log.lammps --analyze all --plot all --theme publication
```

Run `lkpr prep -h` / `lkpr post -h` for the full option list. The legacy entry
points (`python -m lammps_pre`, `python -m lammps_post`, and the `lammps-pre.py`
/ `lammps-post.py` wrapper scripts) still work unchanged.

## Explicit species and groups

Species selections are system-owned; they need not have a force-field name:

```python
from lammpkeeper.core import SpeciesMap

species = SpeciesMap.from_atom_types({2: 'A', 7: 'A', 9: 'B'},
                                     groups={'X': [2, 9]})
assert species.resolve('A') == frozenset({2, 7})
assert species.resolve('X') == frozenset({2, 9})
```

Post uses explicit input/data/dump labels and can load optional JSON groups with
`load manifest "lkpr-run.json"` in its shell or batch commands. Contradictory
explicit labels fail visibly; unresolved group references cannot drive analysis.
Manifests do not override LAMMPS units or force-field settings and are not written
or discovered automatically. Existing ACE spin presets and legacy mapping APIs
remain compatible. The existing `set types` command remains a warned manual
analysis-label override; input/data/dump load/unload expires it visibly, whereas
manifest/log changes retain it. Dump-only FF classification still has warned
heuristics (GEN-2), so generic selection is not complete FF generality.
See [`docs/agent/GEN-1.md`](docs/agent/GEN-1.md) for schema, commands and limits.

## Restricted-triclinic geometry

The post shell supports restricted LAMMPS `xy/xz/yz` cells with Cartesian
`x,y,z` coordinates for **RDF** and **constant-cell MSD**. PBC must come from dump
flags or explicit input boundaries; tilted cells do not infer it from a surface.
Unsupported tilted slab/O₂ analyses and plots fail visibly, so use individual
`analyze rdf` / `analyze msd` commands rather than `analyze all` for these cells.

Python callers can opt into `parse_dump(..., box_model=True)` or use
`read_data_file(...)` from `lammps_post.parsers`. Frames carry an immutable
`lammpkeeper.io.Box` in `frame['cell']`; compatibility bounds alone are not the
cell geometry. Legacy reader defaults remain orthogonal-only. General rotated
cells, scaled/unwrapped conversion, image reconstruction and deforming-cell
triclinic MSD are not supported. See [`docs/agent/GEN-3.md`](docs/agent/GEN-3.md)
for numerical limits, sampling assumptions and the approved API.

## Tests

```bash
HOME="$(mktemp -d)" pytest                       # if pytest is installed
HOME="$(mktemp -d)" python tests/run.py          # no pytest required; NumPy core
HOME="$(mktemp -d)" LKPR_SLOW=1 python tests/run.py # RDF/MSD goldens and oracle
```

The numeric regression uses the ACE example trajectory shipped in
`tests/fixtures/ace_examples/`. The latest whole-source review, English annotation
inventory, known open findings and verification limits are recorded in
[`docs/agent/REVIEW-20261028.md`](docs/agent/REVIEW-20261028.md); passing regressions
are not a claim that every scientific input or optional path is validated.

## Layout

```
lammpkeeper/     unified CLI + core/ (species, geometry) + io/ (Box) + common/
lammps_pre/      structure building & LAMMPS input generation
lammps_post/     trajectory analysis & plotting
tests/           regression suite + fixtures
MIGRATION.md     how the two originally-separate CLIs were unified (design record)
```

See [`MIGRATION.md`](MIGRATION.md) for the integration history and the
behavior-preservation decisions behind it.
