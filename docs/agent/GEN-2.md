# GEN-2 — explicit force-field and run metadata

Status: architecture proposal complete; awaiting approval of
ADR-0005. Branch: `gen/gen-2-explicit-metadata`.
Baseline: merged main `b9bd50333ad0b69a7274c89af850a56216d048c5`.

## Progress and decisions

1. The maintainer requested continuation after REV-PREP-1. Resume the accepted
   GEN-1 → GEN-3 → GEN-2 roadmap, one bounded item at a time.
2. Baseline verification was measured on merged main: **444 passed, 0 failed,
   0 skipped**, post analyses/plots and prep artifact/script-syntax smoke passed.
   Evidence: `/tmp/opencode/rev-prep-1-merged-main/20261028T163309-b9bd503-full`;
   published in PR #24. This is baseline evidence, not GEN-2 implementation proof.
3. Read MIGRATION.md and accepted ADR-0001 before proposing architecture changes.
   Found a specification conflict: the old GEN-2 backlog suggests reading physics
   metadata from a manifest, while accepted ADR-0001 explicitly forbids duplicating
   units, pair_style, atom_style and timestep there. Follow the accepted ADR:
   LAMMPS files own those facts; optional JSON retains groups/domain/provenance.
4. An independent read-only reviewer examines source-resolution, generic-field
   classification, conflicts, load order and compatibility boundaries. Parent owns
   proposal integration and roadmap updates. No runtime implementation is approved
   by the generic instruction to continue.
5. Independent review identified five source-inferred risks: unknown explicit
   styles retain a guessed FF; substring matching misclassifies unrelated styles;
   FF/species/capabilities are coupled; partial time metadata can mix explicit
   units with a guessed timestep; load/unload/manual overrides and independent
   logs need distinct provenance. Parent inspected the cited parser/shell paths.
6. Proposed ADR-0005 now defines exact-token classification, explicit unknown →
   generic, unknown-time handling, log-owned metadata, transactional resolution
   and manual override lifetimes. Keep classification in existing parsers; add
   only `io/metadata.py`, deferring the full registry/package migration.
7. Architecture gate: stop before runtime changes. Requested acceptance concerns
   the proposed contract; no ADR has been marked accepted by the agent.
8. Final independent document review requested a stricter partial-time rule.
   Incorporated: even recognized explicit FFs cannot supply an undeclared dt;
   guessed units cannot convert an explicit native timestep into confirmed fs.
   Legacy inferred time is confined to the path with no explicit pair-style,
   units or timestep declarations. Partial explicit metadata remains unresolved.

## Proposal checks

Parent ran `git diff --check` and checked that tracked changes are documentation
only, ADR-0005 remains proposed, and the thesis tag is unchanged: passed. No
runtime tests were rerun for this documentation-only proposal; **444/0/0** above
is explicitly prior merged-main baseline evidence. No GEN-2 implementation or
architectural acceptance is claimed.

## Scope and gates

The next approval is the explicit metadata contract, not new physical defaults,
new mappings, LJ-to-femtosecond conversion, generated simulation inputs or HPC.
Preserve existing public entry points, Fe-O fixtures/goldens, the thesis tag and
user-owned `Claude outputs/`. Unknown pair styles must not silently acquire
ACE/ReaxFF/HDNNP domain assumptions. Reduced LJ units need visible unsupported
handling wherever existing analysis requires physical units.

The `/architect` and `/poteto-mode` commands are not exposed in this harness;
perform the repository's required architecture review through source inspection,
independent read-only review and a proposed ADR. Do not represent those unavailable
commands as executed. Implementation and full verification follow only after the
maintainer accepts the proposed contract.

## Refresh for approval review (2026-11-01)

After the integrity batch (#37–#44) and UI-1 (#46), the roadmap order puts the
ADR-0005 approval review next. The unpublished proposal (`e273ce0`) was carried
onto main `f752337` as a fresh branch `gen/gen-2-adr-0005` (content of the ADR's
decision sections unchanged). A "Changes on main since drafting" subsection
records how REV-SESSION-1/2, REV-IO-6 and EXEC/UI-1 relate to it. Status remains
**proposed**; implementation waits for explicit maintainer acceptance.

## Renumbering note (2026-10-31)

Accepted ADR-0004 on main now records the Rust/Python/agent interface decision
(PR #28). This unpublished proposal was renamed from ADR-0004 to **ADR-0005**
without changing its content or status. It is still proposed, not accepted.
Before publication, rebase on current main and reconcile its `--input` CLI and
metadata-resolution plans with the EXEC-1/EXEC-2 application contract.
