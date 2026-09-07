# Legacy isolated accelerator shield diagnostic

<!-- DOC_STATUS: ARCHIVED_READ_ONLY -->

> Archived evidence only. This document does not define current project status,
> requirements, or qualification; see the current authority in
> [`docs/PROJECT.md`](../PROJECT.md).

This is read-only historical source, archived on 2026-09-03 during the
orthogonal-accelerator ownership migration. It is not an active test, a
registered workflow, or evidence for the independent project's qualification.

## Source identity

- Original repository path: `projects/single_reflection_oa_tof_mass_analyzer/tests/comsol/test_square_shield_accel.m`.
- Original source revision baseline: `055dbaf57661f080f25378c13abe698c303db9e2`; the preserved bytes are the audited worktree source.
- Preserved payload: [test_square_shield_accel.m](20260903__legacy-accelerator-diagnostic/test_square_shield_accel.m).
- Raw-byte SHA-256: `4e87f18e13910afc6ba82149a30dcbcf34a889230fe11080b63c9d51a2e95316`.
- Relocation verified identical raw-byte SHA-256; no source edits and no solver execution were made during archival.

## Scope and retired status

The source builds an isolated COMSOL second-region square shield, five square
rings and two endpoint ideal grids, then samples its electrostatic field. It
does not build an oa-TOF reflector or complete instrument. Its fixed historical
dimensions and voltage, unused oa-TOF path helper, `OATOF_RUNTIME_DIR` output,
printed diagnostics without a registered pass criterion, and missing run
lifecycle records make it unsuitable as an active independent-project test.

Do not execute this payload or treat its printed `SUCCESS` text as a current
acceptance result. A future field-linearity validation must consume the active
component contract, current builders and registered run/retention lifecycle;
this file remains only provenance for the earlier implementation.
