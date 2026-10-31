# lkpr verification map

This directory is the maintained source for verifying LammpKeeper's numbers. Read
this index before running anything, then use the matching feature file as the
recipe. The harness is `scripts/verify_refs.py` in the parent directory.

## Baseline preconditions

- Work from the repo root of this checkout; the runner imports `lammpkeeper`,
  `lammps_post` and `lammpkeeper.io` from there, not from an installed copy.
- Export `LKPR_HOME="$(mktemp -d)"` and run every command with `HOME="$LKPR_HOME"`.
- Set `LKPR_VERIFY_DIR` to a directory you keep so evidence survives cleanup.
- `verify_refs.py --doctor` reports `ok numpy`, `ok lammpkeeper 1.2.0` from this
  repo, `fixture: present` and six reference files.
- `tests/fixtures/**` is read-only. Never regenerate or edit the fixture.

## Driving conventions

- Every check is `verify_refs.py --only <check-id>`; the full run is the same
  script with no arguments.
- Treat every command as literal. Do not add `--max-frames` or change `r_max`,
  `n_bins` or `dt_fs`: the references were measured with the defaults named in
  each feature file.
- Compare numbers only against `references/<check-id>.json`. Do not compare
  against values quoted in code comments, docs or earlier reports.
- Never edit a reference file to make a run pass. A disagreement is a finding.

## Reference kinds and what PASS means

Every key in `references/<id>.json` has a `kind`, and the meaning of a PASS
follows it:

| kind | the reference is | PASS means |
|---|---|---|
| `analytic` | a closed-form identity with stated constants | agreement with an independent standard |
| `external` | a literature, crystallographic or database value named in `source`/`sources` | agreement with an independent standard |
| `fixture` | a committed data file aggregated without this repository's code | agreement with an independent standard |
| `snapshot` | this repository's own output at `baseline_commit` | unchanged since that commit (regression check); **not** evidence of physical correctness |

Report snapshot PASSes with that wording. A snapshot re-baseline is a separate,
justified change that records a new `baseline_commit`.

## Proof and skip reporting

- Proof is the `summary.txt` line for the check plus, for any key outside
  tolerance, the measured value, reference and tolerance from `results.json`.
- Record the check id, the git SHA from `doctor.txt` and the evidence directory.
- Report an unrunnable check with the doctor line that blocks it (missing module,
  missing fixture). Do not report it as passed through another path.
- A skipped or inactive check is not a pass. The doctor lists inactive compute
  functions explicitly.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing the
user-visible behaviour. It then uses exactly four H2 sections in this order:
`Sub-features`, `How to get to it (user POV)`, `Driving it with verify_refs.py`,
`Gotchas`.

## Features

- [ACE bulk fixture facts](./fixture-ace-bulk.md): loading the committed Fe3O4
  trajectory reproduces its documented frame count, populations, box, PBC and
  constant spin populations.
- [Reference crystal Fe3O4](./reference-crystal-fe3o4.md): the built-in magnetite
  cell gives the analytic tetrahedral and octahedral Fe-O distances, directly and
  through the reference-RDF generator.
- [Analytic MSD](./analytic-msd.md): `analyze_msd` on hand-built frames returns the
  exact squared displacements, including a periodic crossing and a type swap.
- [Analytic RDF pair](./analytic-rdf-pair.md): `compute_rdf` on an isolated pair
  puts the single peak in the bin of the true distance, in-box and across a
  periodic face.
- [Box geometry](./box-geometry.md): `lammpkeeper.io.Box` volume and edge lengths
  are invariant under xy tilt.
- [ACE fixture RDF/MSD snapshot](./fixture-ace-rdf-msd.md): the Fe_up-O g(r)
  peak over the last 20 frames and the Fe_up/O MSD endpoints are unchanged since
  `baseline_commit` (snapshot kind; regression only).

## Pending references (not run, not mapped)

These behaviours are obvious candidates but have no reference value yet. They
are not run. (The ACE fixture RDF peak and MSD endpoints were registered on
2026-10-31 as `snapshot` keys in `fixture-ace-rdf-msd`; note that `compute_rdf`
averages the **last** 20 frames by default, which in this fixture is the tail of
the final minimization, not the 1200 K MD.)

| Candidate check id | Quantity | Where a reference could come from |
|---|---|---|
| (none yet) | Thermo values parsed from `tests/fixtures/ace_examples/regular_MD/log.lammps` (`parse_log`) | hand-read rows of the log file (`fixture` kind) |
| (none yet) | Density profile, O2 dissociation, penetration, OAR | need a slab `p p f` fixture (TEST-3 is analytic only) |
| (none yet) | `lkpr prep` generated coordinates vs. a stored structure | needs ASE and a maintainer-approved reference `structure.xyz` |
| (none yet) | Non-Fe species system (GEN-8) | no fixture |
| (none yet) | Triclinic RDF/MSD against an analytic tilted cell | analytic construction possible; needs agreed cell and tolerance |
| (none yet) | Literature citations for the Fe3O4 constants a = 8.396 A and u = 0.2549 | maintainer fills `sources` in `reference-crystal-fe3o4.json` (currently "repo constant, literature citation pending") |
