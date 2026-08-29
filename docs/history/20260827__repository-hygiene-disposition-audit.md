# 2026-08-27 repository hygiene disposition audit

DOC_STATUS: ARCHIVED_READ_ONLY

## Scope and result

This is a post-audit disposition record for the user's repository-wide cleanup
authorization. It does not alter scientific evidence, Formal assets, run
manifests, archive payloads, or a cache generation selected by
`current_generation.json`.

The audit found 28 invalid scratch task directories and four invalid cache
staging directories. Each target is untracked, has no `run_manifest.json`, and
is either an invalid `task_id` or a cache directory with neither
`cache_manifest.json` nor `current_generation.json`. They are therefore not
reusable cache entries or publishable run evidence. A text-reference search
found no reference for the four cache staging names except that
`b-e83da53eb407` appears as a stale staging-path mention in two run summaries;
those summaries are retained and the missing cache is correctly a cache MISS.

The requested process deletion was attempted with an explicit literal target
list and pre-deletion checks. The execution environment rejected the command
before PowerShell started, so **no target listed below was deleted by this
audit**. The entries remain safe, explicitly audited manual-deletion targets.

| class | targets | logical bytes | GiB |
|---|---:|---:|---:|
| invalid scratch tasks | 28 | 12,415,090,045 | 11.562 |
| unmanifested cache staging | 4 | 23,506,127,502 | 21.892 |
| total | 32 | 35,921,217,547 | 33.454 |

## Exact manual deletion targets

### Invalid scratch tasks

```text
artifacts/projects/rf_hexapole_ion_optics/scratch/paper1_s2_n1000_launcher                         4,605
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/20260818_143200__prepare__pre-pulse-time-series-gap3p2__n100 100,690
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/20260820_221500__prepare-v3 83,464
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/c1_gap0_single_snapshot_prepare 819,433
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/c3_axis_export_prepare_20260826 119,457
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/c3_total_axis_smoke_20260826 643,557,130
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/connector-gap-n100-prepare 434,889
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/copycheck-10a15d43cbdc4017973614fd1c34362e 223,118,168
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/debug1024 108,533
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/dt40_preflight_r04 83,068
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/fixed_geometry_actual77_voltage_diagnostic_20260820 11,433,609,737
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/formal_asset_repair_20260819_0950 112,550,528
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/fullideal-zvz-launch-20260820-030000 1,260
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/fullideal-zvz-launch-20260820-030000-retry1 2,655
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/overlay_basis_diagnostic_20260827 16,569
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/paper1_gap0_validate 133,178
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/paper1_gap0_zvz_validate 136,722
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/r05-launch 6,586
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/recompiled-connection-inspect 60,083
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/recompiled-ideal-launch-20260820-115000 2,587
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/recompiled-ideal-launch-20260820-120000 1,372
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/source-population-prepare-validation 88,835
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/scratch/zvz-launch-20260820-022000 2,783
artifacts/projects/single_reflection_oa_tof_mass_analyzer/scratch/commercial_parallel_probe_20260825 47,541
artifacts/projects/single_reflection_oa_tof_mass_analyzer/scratch/j2_gap51p2_development_probe 0
artifacts/projects/single_reflection_oa_tof_mass_analyzer/scratch/misplaced_empty_scratch_20260825 0
artifacts/projects/single_reflection_oa_tof_mass_analyzer/scratch/threezone-actual77-t4a 88
artifacts/projects/single_reflection_oa_tof_mass_analyzer/scratch/threezone-actual77-t4b 84
```

### Cache-MISS staging directories

```text
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/cache/simion_single_flight_frontend/b-e83da53eb407 9,965,247,600
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/cache/simion_single_flight_frontend/b-be9eb341578b 6,972,001,396
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/cache/simion_single_flight_frontend/b-f3a4eed2c993 2,518,797,664
artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/cache/simion_accelerator_overlay/b-492d8eec9423 4,050,080,842
```

## Verification boundary

`common/verify_repository_hygiene.ps1` passed. Full
`common/contracts/verify_artifact_layout.py ../artifacts/projects` remains
blocked at the first invalid scratch task ID, as expected until the listed
targets are removed. The audit deliberately retains all validly named scratch
directories, unexpected project-top-level result folders, manifests, and both
legacy and current-generation cache entries because their scientific or user
ownership cannot be disproved by a hygiene audit alone.
