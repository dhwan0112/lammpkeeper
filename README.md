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

## Tests

```bash
pytest                       # if pytest is installed
python tests/run.py          # dependency-free runner (numpy only)
LKPR_SLOW=1 python tests/run.py   # include the slower RDF/MSD golden checks
```

The numeric regression uses the ACE example trajectory shipped in
`tests/fixtures/ace_examples/`.

## Layout

```
lammpkeeper/     unified CLI (lkpr) + common/ (shared mapping, display)
lammps_pre/      structure building & LAMMPS input generation
lammps_post/     trajectory analysis & plotting
tests/           regression suite + fixtures
MIGRATION.md     how the two originally-separate CLIs were unified (design record)
```

See [`MIGRATION.md`](MIGRATION.md) for the integration history and the
behavior-preservation decisions behind it.
