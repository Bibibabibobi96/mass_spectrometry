# Connector-gap residual threshold mechanism experiment

## Scope and frozen controls

This is a collisionless, independent-particle, RF terminal-octupole-to-OA-TOF
simulation at 100 Th.  It uses one ordered 5000-particle mother cohort.  For
each connector length, the already frozen pulse epoch and pre-pulse state are
reused; no time-window search occurs.  Within a connector length, geometry,
RF, pulse, numerical settings, and particle IDs are fixed.  The only changed
quantity is the accelerator/reflectron working point derived from the existing
source `z-vz` relation.

The reproducible arm reports are in
`artifacts/projects/single_reflection_oa_tof_mass_analyzer/paper1_stage_evidence/connector_gap_working_point/20260827_112500/`.
Each arm's FWHM and shape metrics use all of that arm's detector hits, not a
cross-arm common-hit filter.  Particle ID pairing is used only for bootstrap
uncertainty.  The two arms within every gap happened to have identical detector
ID sets, so a resolution gain cannot be attributed to changed transmission.

## Results

| Connector gap | Pre-pulse residual RMS (m/s) | Detector hits / 5000 mother particles | Inherited FWHM (ns), R | Relation-derived FWHM (ns), R | Relative R change | 1000× paired-bootstrap absolute R difference, 95% interval |
|---:|---:|---:|---:|---:|---:|---:|
| 0 mm | 49.61 | 3679 (73.58%) | 2.155, 17,842 | 2.086, 18,433 | +3.31% | 0.42–5.02% |
| 51.2 mm | 17.48 | 157 (3.14%) | 4.011, 11,057 | 1.479, 29,989 | +171.22% | 54.88–68.16% |
| 102.4 mm | 11.47 | 59 (1.18%) | 3.559, 14,122 | 1.060, 47,405 | +235.67% | 56.99–77.88% |

At 0 mm the relation-derived setting produces only a small practical change.
At 51.2 mm it lowers FWHM by 63.1% with unchanged detector IDs and hit count;
this is the principal numerical mechanism evidence.  The 102.4 mm arm shows
the same direction but is a low-transmission boundary observation, not a
precision main result.  Its inherited spectrum has two significant KDE modes;
the relation-derived setting has one.  Both longer-gap adjusted spectra have a
small nonzero tail fraction, which must be reported rather than hidden by a
single-resolution metric.

## Conclusion and limits

`PASS_CONTINUE`: within this frozen source model, increasing the connector gap
reduces the conditional axial residual while sharply reducing transmission, and
a large working-point focusing benefit appears only after the residual is
lower.  This supports the paper's limited residual-threshold mechanism claim.

It does **not** establish a universal source model, measured-instrument
performance, multi-mass behavior, collision/space-charge behavior, a general
analyzer optimum, or a first/novel claim.  The next publication decision should
retain 51.2 mm as the central model-specific result and explicitly present the
102.4 mm transmission tradeoff.
