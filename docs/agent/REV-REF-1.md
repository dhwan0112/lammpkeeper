# REV-REF-1 — reject unsupported CIF occupancy/disorder

Status: complete; [PR #23](https://github.com/dhwan0112/lammpkeeper/pull/23).
Baseline: merged main `6c073471856748929cdd5a4a2980876db04f4856` (PR #22).
Branch: `fix/rev-ref-1-cif-occupancy`.

## Failure and bounded decision

The review measured a CIF P1 site with explicit occupancy zero being returned
as one full atom. The parent staged
`test_rev_ref_1_zero_occupancy_cannot_become_a_full_atom` in
`tests/pending_review_findings.py` and observed its failure before changing code:
`AssertionError: explicit zero-occupancy site was accepted as a full atom`.
The same reproduction passes after the guard implementation. It was moved into
`tests/test_cif_occupancy.py`, registered in `tests/run.py`, and the staging file
restored byte-for-byte. No fixture/golden change is included.

The existing reference schema is unweighted `{name, cell, atoms}`. This repair
**does not add partial-site weighting, choose disorder alternatives or introduce
a new physical model**. It rejects unsupported or ambiguous declared site data
before element/coordinate filtering or symmetry expansion, rather than silently
filtering sites or publishing an unsupported full-atom reference.

### Supported subset

- Missing occupancy retains the existing unit-site compatibility convention.
- Explicit occupancy must be a finite **exact nominal decimal one**. Decimal
  comparison prevents values such as `.9999999999999999999999` from rounding to
  one via float64. Zero, partial, out-of-subset values, `?`, `.`, nonfinite and
  malformed tokens reject visibly.
- Ordinary decimal/scientific notation and a digit uncertainty suffix are
  accepted when the nominal value is exactly one, with or without simple field
  quotes. Uncertainty is not propagated and is not used to fit a partial value
  to one. Values outside this nominal-unit subset can be valid CIF measurements;
  rejection does not pronounce them physically invalid.
- `_atom_site_disorder_assembly` and `_atom_site_disorder_group` accept only the
  **unquoted `.`** not-applicable marker (or absent columns). Other codes,
  including `0`, and unknown/quoted markers are unsupported. No unverified
  meaning is assigned to group `0` and no alternatives are selected.
- Atom-site header matching/mapping is case-insensitive so mixed/uppercase
  occupancy cannot become an ignored extra column. Duplicate guarded headers
  and incomplete/misaligned guarded rows reject.
- Guarded rows support simple single-line quoted fields and inline comments;
  malformed quotes and semicolon/multiline fields reject instead of whitespace
  shifting metadata. The legacy unguarded whitespace subset is retained.
- Explicit site constraints outside the first imported fractional atom loop
  (scalar, orphan or another loop) reject because association is ambiguous.
  Dotted occupancy/disorder tag spellings are also detected so unsupported
  placement cannot silently override an imported underscore-style loop.

Errors are `ValueError` with source, one-based line and relevant tag, plus site
label/value where available. Unsupported site data does not return a partially
filtered crystal. Source files are not rewritten; no new result key or flag is
added. Existing missing-source/fetch and symmetry behavior remains separate.

COMCIFS dictionary definitions consulted on 2026-10-28:
https://raw.githubusercontent.com/COMCIFS/cif_core/master/cif_core.dic
(`atom_site.occupancy`, `atom_site.disorder_group`, `atom_site.disorder_assembly`,
with underscore aliases). Several IUCr HTML requests returned HTTP 403; no claim
is made that all such pages were accessible. The definitions describe occupancy
as a site fraction and disorder fields as codes for alternatives/clusters; they
do not supply the weighting/selection model this reader lacks.

## Independent review and safety probes

A read-only reviewer identified a concrete bypass during implementation: a row
labelled `loopSite1` escaped a broad `startswith('loop')` skip, while `loop_1`
escaped a prefix-based regex boundary. The parent independently reproduced both:
one valid site followed by an occupancy-zero site returned a one-atom crystal.
The implementation now distinguishes actual `loop_` control tokens and validates
all guarded data labels, rather than applying the legacy prefix skip. Regressions
cover these cases separately from the original zero-occupancy reproduction.

The parent also reproduced a packed-scalar escape: after valid unit-site rows,
`_chemical_name_mineral 'Probe' _atom_site_occupancy 0` on one physical line was
missed by line-anchored declaration discovery. A lexical association scanner now
finds unquoted constraint tags anywhere in the token stream, while ignoring
comments, quoted values and column-one semicolon text. It preserves source
offsets for binding tags to the imported header and rejects ambiguous placement.
This is a site-safety scan, not a replacement general CIF parser.

The review also checked discovery/placement, duplicate tags, row validation before
coordinate filtering, exact nominal-one parsing and the conservative disorder
policy. A mistaken unsupported claim about a special group-0 dictionary meaning
was explicitly withdrawn; the policy is a supported-format restriction, not a
scientific assertion about that code.

## Compatibility and verification

Parent independently extracted baseline `parse_cif` from
`git show 6c07347:lammps_post/references.py` and compared complete crystal output
(name, atom list and cell) for nine absent/unit-occupancy forms: absent, `1`,
`1.0`, `+1.000`, `1e0`, `10e-1`, `1.0(2)`, `1(0)e0`, `1e0(2)` — identical.
`compute_reference_rdf`, `_expand_symmetry` and `_cell_from_params` are
AST-identical to baseline, including their existing limitations.

Parent isolated-HOME initial targeted run of the old reference/real-Agg/golden
modules measured **13 passed, 0 failed, 0 skipped**, plus the passing staged
reproduction. After integration, the **20 new collected CIF regressions** plus
old reference/real-Agg/golden and thermo-integrity modules measured **45 passed,
0 failed, 0 skipped**:

```bash
HOME="$(mktemp -d /tmp/opencode/rev-ref-1-target-home.XXXXXX)" \
  TMPDIR=/tmp/opencode LKPR_SLOW=1 PYTHONDONTWRITEBYTECODE=1 \
  /home/kim/opt/miniforge3/envs/chem/bin/python - <<'PY'
import sys
sys.path.insert(0, 'tests')
import run
run.MODULES = ['test_cif_occupancy', 'test_audit_references_plots',
               'test_regression_numeric', 'test_log_integrity']
raise SystemExit(run.main())
PY
```

The new regressions include all rejection forms/precision boundaries, positive
literal fractional/Cartesian geometry, P1/centering, late-site abort, bad-coordinate
filter bypasses, case/reordering, quotes/comments, disorder codes, scalar/orphan/
packed/duplicate/misaligned metadata, loop-like labels, benign literal tag mentions,
mocked COD responses and actual shell failure before reference compute/render or
recipe/cache publication. Mock sentinels are not actual CIF image-rendering or
network evidence; the old Agg tests exercise real artists.

Parent static/preservation checks measured **75 Python modules / 1019 documented
definitions**, all accepted by Python 3.9 grammar. Every pre-existing test/fixture/
golden file except additive runner registration is byte-identical to baseline;
all 36 test modules are registered exactly once. The thesis tag remains at
`cdf5c38e975871debf64eb6d810e78a08165c381`. No mapping, generated protocol, lockfile
or binary change is included. `git diff --check` passes. Test-owner commands and
scoped evidence remain in `/tmp/opencode/rev-ref-1-tests.md`.

### Full verifier matrix (parent measured)

All runs used isolated HOME and unchanged slow goldens. HEAD was `6c07347` with
final source/test/runner changes in the working tree; commit `41b164a` preserves
those tested bytes.

| Environment/path | Passed | Failed | Skipped | Smoke |
| --- | ---: | ---: | ---: | --- |
| Expanded Python 3.12.14 / NumPy 2.5.3 / native | 425 | 0 | 0 | post analyses + real plots; prep artifacts/script syntax passed |
| Same interpreter, `LKPR_NO_NATIVE=1` | 419 | 0 | 6 | same post/prep smoke passed |
| Default Python 3.14.4 / NumPy 2.3.5 / native | 408 | 0 | 17 | post passed; prep skipped without ASE |

```bash
PYTHON=/home/kim/opt/miniforge3/envs/chem/bin/python TMPDIR=/tmp/opencode \
  LKPR_VERIFY_DIR=/tmp/opencode/rev-ref-1-rich PYTHONDONTWRITEBYTECODE=1 \
  bash .cursor/skills/verify-lkpr/scripts/verify.sh full
PYTHON=/home/kim/opt/miniforge3/envs/chem/bin/python LKPR_NO_NATIVE=1 \
  TMPDIR=/tmp/opencode LKPR_VERIFY_DIR=/tmp/opencode/rev-ref-1-numpy \
  PYTHONDONTWRITEBYTECODE=1 bash .cursor/skills/verify-lkpr/scripts/verify.sh full
TMPDIR=/tmp/opencode LKPR_VERIFY_DIR=/tmp/opencode/rev-ref-1-default \
  PYTHONDONTWRITEBYTECODE=1 bash .cursor/skills/verify-lkpr/scripts/verify.sh full
```

Local evidence:

- `/tmp/opencode/rev-ref-1-rich/20261028T131746-6c07347-full`
- `/tmp/opencode/rev-ref-1-numpy/20261028T131746-6c07347-full`
- `/tmp/opencode/rev-ref-1-default/20261028T131746-6c07347-full`

Forced NumPy skips exactly these native-only tests (all pass in native):

- `test_dump_reader.test_native_parser_matches_loadtxt`
- `test_periodicity.test_native_boundary_metadata_matches_numpy_without_fallback`
- `test_slab_reference.test_slab_native_and_numpy_match_every_reader_access_path`
- `test_species_metadata.test_dump_native_metadata_parity_without_numpy_fallback`
- `test_species_metadata.test_dump_native_raw_type_ids_without_fallback`
- `test_triclinic_io.test_box_aware_real_native_success_matches_numpy_without_fallback`

Default Python skips the same four ASE/twelve Matplotlib tests individually named
in [`REVIEW-20261028.md#named-skips-and-unavailable-integrations`](REVIEW-20261028.md#named-skips-and-unavailable-integrations),
plus `test_cif_occupancy.test_cif_shell_interactive_import_fails_before_compute_plot_or_publication`
(`matplotlib not installed (interactive CIF shell check)`). The other 19 new CIF
tests execute there; the expanded run passes every test. MDAnalysis and pytest
execution remain unverified; no native rebuild or fresh wheel build is claimed.

Final parent checks again measured complete baseline crystal equality for all
nine absent/unit forms and rejection of all three independently reproduced
label/packed-scalar escapes. AST comparison proves **every module node outside
`parse_cif`, the four new private guards/constants, the Decimal import and module
documentation is unchanged**, including all built-ins and reference RDF math.
This is preservation evidence, not proof that existing reference geometry/shell
limitations are correct. Other 22 review follow-ups remain open.

This is not comprehensive CIF cell/coordinate/symmetry validation, a fix for
reference RDF shell completeness, or an implementation of generic disorder.
Other review items remain independent. No real LAMMPS/HPC, real COD fetch,
external-potential evaluation or physical-reference certification is claimed.
