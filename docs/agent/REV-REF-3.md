# REV-REF-3: CIF symmetry operators are parsed by a complete grammar

Status: fixed and verified (PR #93).
Branch: `rev-ref-3/symop-grammar` from `63d9bc0` (main after PR #92).
Source: BACKLOG REV-REF-3 (P2; F-REF-3 in `docs/agent/REVIEW-20261028.md`).

## Problem

`lammps_post/references.py::_apply_symop` tokenized an xyz operator with a
permissive `re.findall` and summed whatever it recognized. Anything else was
ignored: `_apply_symop('garbage,y,z', [.2,.3,.4])` returned `[0, .3, .4]`,
`x/2` meant `x`, `x+w` meant `x`, a two-component operator produced a third
component of 0, and a singular operator such as `x, x, z` was applied as if it
were a symmetry operation. The CIF symmetry loop skipped any row without a
comma, so a garbled row vanished and the remaining rows were expanded as a
complete cell. A reference g(r) computed from such a cell is wrong without any
signal.

## Change

`lammps_post/references.py`:

- `_parse_symop(text)` returns `(rotation, translation)` for one operator or
  raises `ValueError`. Grammar: exactly three comma-separated components; each
  a non-empty sum of terms; a term is a signed coordinate (`x`, `-y`, `+z`,
  optionally with an integer coefficient, `2*x`) or a signed translation
  (`1/2`, `0.5`, `.25`, `1`); every term after the first carries its own
  sign; case and whitespace are ignored; nothing else may appear. The rotation
  part must have determinant +1 or -1 (every space-group operation does in
  lattice coordinates), so `x, x, z` and `2x, y, z` reject. Messages name the
  operator, the component and the offending text (or the determinant).
- `_apply_symop` parses with `_parse_symop` and applies the matrix; the
  previous docstring caveat that input "needs external validation" is gone.
- `_expand_symmetry` parses every operator before generating any site, so a
  bad operator fails the whole expansion instead of a partial cell. The
  rounding/wrapping/duplicate rules are unchanged.
- `parse_cif`: every non-empty, non-comment row of the symmetry loop must be a
  valid operator; a row that is not raises
  `CIF symmetry loop (<tag>) row '<row>' is not a valid operator: ...`. The
  operator text is read by `_symop_loop_row` (leading integer id removed, a
  quoted operator taken from its quotes even when further columns follow, an
  unquoted row taken whole). The P1 fallback and the missing-symmetry
  rejection are untouched.

`tests/test_symop_grammar.py` (new): eleven valid operator forms checked
against hand-written matrices; seventeen malformed or singular operators
rejected with the expected fragment through both `_parse_symop` and
`_apply_symop`; `_expand_symmetry` rejection before any site and preserved
expansion/wrapping; the hematite built-in unchanged (12 Fe + 18 O and the
digest of the sorted rounded expansion recorded on main before the change);
CIF loops with a bad row (`garbage`, no commas, two components, singular)
reject naming the tag and row for both `_space_group_symop_operation_xyz`
and `_symmetry_equiv_pos_as_xyz`; quoted operators with a trailing column,
unquoted, numbered and uppercase rows expand; declared P1 and the
missing-symmetry rejection are unchanged. `tests/run.py` registers the module.

## Decisions

- Reject, do not repair. The old code's fallback (ignore what it could not
  read) is exactly what turned a typo into a wrong reference cell. The grammar
  covers every form used by the built-ins and by conventional CIF files; a
  form outside it is reported with the text that failed so the file can be
  fixed.
- Unimodular check. A rotation part with determinant other than ±1 cannot map
  the lattice onto itself, so it is not a symmetry operation regardless of
  syntax; checking the determinant catches duplicated or dropped coordinates
  (`x, x, z`) that are syntactically valid. Non-crystallographic but
  unimodular integer matrices (`2*x-y, x, z`) are still accepted: the
  parser validates the grammar and invertibility, not space-group membership.
- Operators are parsed once per expansion rather than once per atom and
  operator; the result is the same and the import-time hematite expansion is
  faster.
- The hematite digest is a golden of the pre-change expansion of valid
  operators; it pins preservation, not correctness of the database, which
  AUDIT-20261027 verified separately.

## Verification

| Check | Result |
|---|---|
| `tests/test_symop_grammar.py` (6 tests) | pass |
| `test_cif_occupancy`, `test_audit_references_plots`, `test_slab_reference`, `test_verify_refs`, `test_rdf_reference_pair` | pass (matplotlib skips only) |
| `HOME=$(mktemp -d) /usr/bin/python3 tests/run.py` | 761 passed, 0 failed, 26 skipped (755/0/26 before) |
| same with `LKPR_NO_NATIVE=1` | 748 passed, 0 failed, 39 skipped (742/0/39 before) |

## Review round

An independent read-only review of the full diff found no correctness defects. It traced
`-x+y+2/3, -x+1/3, z+1/2+1/3` and `x+0.5, y-.25, z+1.` through the term regex, checked every
`_hematite_symops` entry against the grammar, confirmed that `1x` parses as `x` while `+-x`, `--x`,
`x+-1/2`, `x+1/2.5`, `1/2/3`, `1/2x`, `0.5x`, `1e-3` and `2*1/2` are all rejected, checked each
`_VALID` matrix and `_MALFORMED` message fragment against the parser's actual output, and confirmed
that the only other caller of `parse_cif` (the shell's CIF import at `shell.py:3258`) already reports
`ValueError` through the command handler.

One observation was followed up: the hematite digest test compares the new code against a constant,
so the constant itself had to come from the pre-change code. The digest was recomputed on `main`
(63d9bc0, before this change) with the same sorted/rounded rows and gave `dc6fbe479ee2a0c1`, the
value the test asserts, with the same 12 Fe + 18 O count. No code changes were needed after review.
