# 2026-08-28 compact artifact hygiene audit

DOC_STATUS: ARCHIVED_READ_ONLY

## Scope and current capacity

This audit covers `artifacts/projects/` only.  At the audit point, C: had
22.79 GiB free of 1,862.91 GiB and artifacts occupied 989.11 GiB.  The source
repository itself occupied less than 0.5 GiB.  No Formal asset, document- or
manifest-referenced scientific result, current cache generation, or running
process was deleted.

The integration project occupied 939.17 GiB: 524.47 GiB in PA cache, 403.31
GiB in runs and 11.38 GiB in scratch.  The capacity issue is therefore
artifact lifecycle, not tracked source code.

## Confirmed compact violations

Twenty `interrupted` runs under
`rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/`
declare `artifact_retention.class=compact`, have no `retention_actions.json`,
and still contain 394.000 GiB of rebuildable SIMION PA arrays.  The largest
five are listed below; the complete affected population is exactly the
20 compact interrupted runs containing `*.pa#`, `*.pa0` or `*.paN`.

| run | PA files | PA GiB | evidence preserved if PA arrays are removed |
|---|---:|---:|---|
| `20260828_180200__sim__simion__rf-oatof-single-flight-gap0__n5000__r05` | 108 | 71.788 | frozen inputs, logs, summary and interrupted receipt |
| `20260828_180200__sim__simion__rf-oatof-single-flight-gap0__n5000` | 108 | 71.788 | same |
| `20260828_093100__sim__simion__rf-oatof-single-flight-gap0__n5000` | 108 | 37.935 | same |
| `20260827_201300__sim__simion__rf-oatof-single-flight-gap0__n1` | 108 | 37.935 | same |
| `20260828_180200__sim__simion__rf-oatof-single-flight-gap0__n5000__r03` | 11 | 33.966 | same |

The root cause is not an entitlement to retain PA arrays: the public runtime
does call compact retention on normal success and caught failure.  These runs
were externally interrupted before the terminal cleanup path completed, so no
`retention_actions.json` was published.  A future reconciler must use the
existing run's compact class to remove only PA/trajectory payload while
preserving its frozen input, logs and failure receipt; it must never delete the
whole run merely because it was interrupted.

## Confirmed manual-disposition targets

All targets below were checked to have zero run-manifest references.  The three
scratch names occur only in the prior hygiene audit, which is an audit record,
not an evidence dependency.  The cache targets are incomplete `b-*` staging
directories: they have neither `current_generation.json` nor a cache manifest,
so they are not reusable cache generations.

| exact path relative to `artifacts/projects` | GiB | reason and rebuildability |
|---|---:|---|
| `rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/fixed_geometry_actual77_voltage_diagnostic_20260820` | 10.562 | invalid scratch task; one-off diagnostic, rebuildable only as a new declared task |
| `rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/c3_total_axis_smoke_20260826` | 0.589 | invalid scratch task; superseded smoke payload |
| `rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/copycheck-10a15d43cbdc4017973614fd1c34362e` | 0.208 | invalid scratch copy check |
| `rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/cache/simion_single_flight_frontend/b-155983f22ac0` | 15.468 | unpublished cache-build staging; no manifest/pointer |
| `rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/cache/simion_single_flight_frontend/b-2a115954296f` | 3.088 | unpublished cache-build staging; no manifest/pointer |

These five targets total **29.915 GiB**.  They are the only full directories
this audit classifies as immediately removable without modifying an existing
run manifest.  The requested deletion was rejected before PowerShell started
by the execution environment, so this record is a precise pending disposition,
not a claim that bytes were freed.

## Cache boundary

The two active cache roots contain 422.650 GiB (frontend) and 101.749 GiB
(accelerator overlay).  Most content is under key-specific
`current_generation.json` pointers and generation manifests.  It may be
expensive and include old generation payloads, but this audit does not delete
it: a current pointer is an active reproducibility dependency.  Legacy root
cache payload and current generation payload can differ even for the same
cache key, so size/name similarity is insufficient proof of duplication.

## Prevention applied

The ideal-field acceptance workflow previously wrote a full density CSV for
every rejected screening candidate.  It now retains only deterministic screen
metrics and writes population curves only for the reference and selected
confirmation designs.  This preserves selection evidence while preventing a
compact run from retaining rebuildable screening curves.  The focused workflow
test verifies the absence of screen density files and their paths.

## Verification

- `python common/contracts/verify_artifact_layout.py ../artifacts/projects`:
  completed successfully after the audit inventory.
- `python -m unittest projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.test_ideal_acceptance_workflow`:
  5 tests passed.
