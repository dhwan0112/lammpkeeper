# REV-REF-4: invalid reference cells are rejected, never clipped or defaulted

Status: fixed and verified (PR #95).
Branch: `rev-ref-4/cell-validation` from main after PR #94.
Source: BACKLOG REV-REF-4 (P2; skew-reference MIC / invalid-cell limits).

## Problem

The backlog row has two halves.

1. *Skew-reference MIC limits.* `compute_reference_rdf` used a componentwise
   minimum-image convention in a 4x4x4 supercell, which undercounts
   neighbours in oblique cells (perpendicular widths smaller than edge
   lengths) and near half the supercell width. REV-REF-2 (PR #94) replaced
   that scheme with an exact enumeration of every lattice image inside the
   cutoff, with a bound derived from the perpendicular widths, so there is no
   minimum-image convention left to limit. `tests/test_reference_images.py`
   checks a skew cell against an independent oracle. Nothing remains to do
   for this half; this PR does not touch the RDF code.
2. *Invalid-cell limits.* `_cell_from_params` accepted any numbers and
   clipped the volume residual `1 - cos²α - cos²β - cos²γ + 2 cosα cosβ cosγ`
   to zero via `max(..., 0.0)` before the square root, so an angle triple
   that describes no cell (for example 170/170/170, or 10/10/30) silently
   produced a flat cell with `c_z = 0` and zero volume, and `r_max`-sized
   reference RDFs were then computed from it (the old code would divide by
   zero volume; the REV-REF-2 code raises "singular cell" one layer deeper,
   with no mention of the angles). Zero or negative lengths, angles of 0 or
   180 degrees, non-finite values and non-numeric input were not checked
   either. `parse_cif` added two more silent paths: an angle tag whose value
   is `0` fell through `or 90.0` and became 90 degrees, and an angle or
   length tag whose value is not a number (`?`, `.`, text) was read as `None`
   and reported as "missing cell parameters" or turned into 90 degrees.

## Change

`lammps_post/references.py`:

- `_cell_from_params` validates every parameter and raises `ValueError`
  naming the offending one: non-numeric (`bool`, numpy bool, `str` and
  `bytes` included, so numeric strings are not accepted) -> "must be a
  number", non-finite -> "must be finite", length `<= 0` -> "must be
  positive", angle outside the open interval (0, 180) -> "must lie strictly
  between 0 and 180 degrees", residual `<= 1e-12` -> the three angles "do not
  describe a cell with positive volume; each angle must be smaller than the
  sum of the other two and the three must sum to less than 360 degrees". The
  tolerance matters: the residual is dimensionless with rounding error of
  order 1e-15, and exact boundary triples evaluate to either sign (120/120/120
  gives +1e-15, 45/45/90 gives -1.6e-16), so a strict `> 0` test would have
  accepted 120/120/120 and built a cell with `c_z` of order 1e-8. The
  `max(..., 0.0)` clip is gone; `c_z = c * sqrt(residual) / sin γ` is computed
  only after the residual is known to be positive. Valid cells are built
  exactly as before (the cubic and hexagonal constructions are reproduced to
  1e-12).
- `parse_cif` reads cell tags through `_cell_param(tag, default)`: an absent
  length still yields the "Missing cell parameters" message and a `None`
  result, an absent angle still defaults to 90 degrees, but a tag that is
  present and not a number raises `ValueError("CIF <tag> value <raw> is not a
  number")`, and an invalid cell raises `ValueError("CIF cell parameters are
  invalid: <reason>")`. The shell's `plot rdf` CIF import already treats a
  `ValueError` from `parse_cif` as a failed command that publishes nothing
  (`tests/test_rdf_reference_pair.py::test_failed_cif_import_on_legacy_key_publishes_nothing`),
  so the new errors surface as a failed command with the message, not as a
  wrong curve.

No built-in phase is affected: the four CRYSTAL_DB cells are constructed
from valid parameters and their digests are unchanged.

## Tests

`tests/test_cell_validation.py` (4 tests):

- `test_valid_cells_round_trip_and_match_the_builtin_constructions`: cubic
  and hexagonal parameters reproduce `_cubic_cell`/`_hexagonal_cell`; a
  triclinic cell (4.1, 5.3, 6.7, 71, 83.5, 112) returns its lengths and angles
  to 1e-9 and its determinant equals `abc·sqrt(residual)`; the matrix is lower
  triangular with positive `c_z`; integers are accepted; the thin but valid
  triple 10/10/19 is built rather than clipped.
- `test_invalid_parameters_are_rejected_not_clipped`: 26 rejections with the
  expected message fragment (zero and negative lengths, NaN/inf, text and
  numeric strings, bytes, `None`, `bool`, numpy bool, angles 0/180/-30/200/NaN,
  four impossible angle triples including 170/170/170 and 10/10/30, and seven
  exact boundary triples such as 120/120/120, 60/60/120 and 45/45/90 whose
  residual rounds to +1e-15 or -1e-16).
- `test_cif_cell_parameters_are_validated_not_defaulted`: absent angle tags
  give 90 degrees and explicit 90 (with or without an uncertainty suffix)
  builds the same cell; `_cell_angle_alpha/beta/gamma 0` each raise (they used
  to become 90); 120/120/120 raises "positive volume";
  `?`, `.` and text values raise "is not a number" for angles and lengths;
  170/170/170 raises "positive volume"; a negative length with an
  uncertainty suffix raises; an absent length still returns `None`; a valid
  triclinic CIF with uncertainty suffixes builds the expected cell.
- `test_triclinic_cif_reference_matches_the_image_oracle`: a valid P1
  triclinic CIF (3.1/4.4/5.2 Å, 71/83.5/112 degrees, two Fe sites and one O
  site) is parsed and its Fe-O, O-Fe and Fe-Fe reference histograms at 7 Å
  equal the brute-force image enumeration of
  `tests/test_reference_images.py` in every bin (137 bins, so no lattice
  translation length sits on a bin edge).

Registered in `tests/run.py`.

## Verification

| Check | Result |
|---|---|
| `test_cell_validation` | 4 passed |
| `test_cif_occupancy`, `test_symop_grammar`, `test_reference_images`, `test_rdf_reference_pair`, `test_audit_references_plots` | 19/0/1, 6/0/0, 4/0/0, 8/0/0, 4/0/7 passed/failed/skipped, unchanged |
| Full suite, native | 769 passed, 0 failed, 26 skipped (765/0/26 before) |
| Full suite, `LKPR_NO_NATIVE=1` | 756 passed, 0 failed, 39 skipped (752/0/39 before) |
| Built-in phase digests (`compute_reference_rdf` for all 13 phase/pair combinations) | identical to main `dae2720`: cells+sites digest `63b0772d233ffa57`, g(r) digest `a7b6c7764ddb115b` (6 Å, 200 bins) |

## Review round

Independent read-only review of the staged diff (`ref4.diff`, 452 lines)
before the final test runs. Findings and outcome:

1. *Defect (confirmed, fixed).* The residual test was `<= 0.0`. The reviewer
   argued that exact boundary triples round to a small positive residual;
   measured values confirmed it: 120/120/120 -> +9.99e-16, 100/100/160 ->
   +2.57e-16 (would have been accepted and built a cell with `c_z` ~ 1e-8),
   while 60/60/120, 10/10/20, 1/1/2 -> exactly 0 and 45/45/90, 30/60/90 ->
   -1.6e-16. The test now rejects `residual <= 1e-12` (dimensionless, far
   below any physical cell: the thin valid 10/10/19 cell has residual
   3.2e-4) and seven boundary triples were added to the rejection cases plus
   a 120/120/120 CIF case.
2. *Minor (fixed).* `np.bool_` is not a `bool` and numeric strings pass
   `float()`, so the "non-numeric" wording overstated the check. The type
   guard now rejects `bool`, `np.bool_`, `str` and `bytes`; `np.True_`,
   `'4.0'` and `b'90'` are tested.
3. *Minor (noted).* The triclinic oracle test checks the RDF against the
   cell that `_cell_from_params` produced; the cell itself is checked by the
   round-trip test (lengths, angles, determinant), so the two together cover
   the path.
4. *Minor (fixed).* Coverage gaps: explicit `90` through `parse_cif`, and
   `_cell_angle_alpha/beta 0` (only gamma was tested) are now covered.

The reviewer verified the `c_z` formula against the previous construction,
that `'-4.0(2)'` reaches "must be positive" through `_strip_uncertainty`,
that `?`/`.`/text reach the new "is not a number" error, that the only
non-test caller is the shell CIF import whose generic handler turns a
`ValueError` into a failed command, and that no existing test CIF uses
`_cell_angle_*` or `?` values. Docs were found consistent with the code
apart from the wording fixed under item 2.
