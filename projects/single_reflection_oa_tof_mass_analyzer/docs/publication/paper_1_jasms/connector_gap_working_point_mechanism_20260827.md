# Connector-gap residual and working-point mechanism experiment

## Scope and frozen controls

This is a collisionless, independent-particle, RF terminal-octupole-to-OA-TOF
simulation at 100 Th.  It uses one ordered 5000-particle mother cohort.  For
each connector length, the already frozen pulse epoch and pre-pulse state are
reused; no time-window search occurs.  Within a connector length, geometry,
RF, pulse, numerical settings, and particle IDs are fixed.  The only changed
quantity is the accelerator/reflectron working point derived from the existing
source `z-vz` relation.  The inherited setting is the frozen T5 working point for
an earlier ideal affine source, not a same-budget reoptimization of a classical
correlation-focusing method.  The adjusted setting reuses
`source_zvz_three_zone_theory_working_point_v1`; this is a test of source-specific
retuning, not a comparison demonstrating a new optimization algorithm.

The corrected derivative analysis is
[`20260827_123019__analysis__python__connector-gap-pulse-clock-correction`](../../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20260827_123019__analysis__python__connector-gap-pulse-clock-correction/).
Its `run_config.json` freezes all six source runs, analysis settings, and
superseded reports; `run_manifest.json` hashes the inputs and new outputs.
Each arm's FWHM and shape metrics use all of that arm's detector hits, not a
cross-arm common-hit filter.  Particle ID pairing is used only for bootstrap
uncertainty.  The two arms within every gap happened to have identical detector
ID sets, so a resolution gain cannot be attributed to changed transmission.

### Clock and uncertainty correction

The earlier reports in
`paper1_stage_evidence/connector_gap_working_point/20260827_112500/` used
absolute `instrument_time_us` in the resolution calculation.  That included
pre-pulse transport and overstated absolute R.  Those R values and their
absolute-difference bootstrap intervals are superseded, not publication
evidence.  No raw CSV, frozen source manifest, or historical report was changed;
no SIMION trajectory was rerun.

All new resolution calculations use the existing authoritative
`pulse_effective_elapsed_us = instrument_time_us - pulse_effective_time_us`,
verified against the source clock declaration.  Missing or inconsistent clocks
fail rather than falling back to instrument time.  FWHM and hit counts are
unchanged.  The paired bootstrap now reports the signed percentage gain
`100 * (R_adjusted / R_inherited - 1)`, using the unchanged canonical direct KDE
FWHM kernel.  Its 95% intervals describe particle resampling of these observed
paired detector populations, not systematic simulation error, source-to-source
uncertainty, or a population-independent guarantee.

## Results

| Connector gap | Detector hits / 5000 mother particles | Inherited FWHM (ns), R | Relation-derived FWHM (ns), R | Signed relative R change | Signed gain 95% interval |
|---:|---:|---:|---:|---:|---:|
| 0 mm | 3679 (73.58%) | 2.155, 7,269 | 2.086, 7,510 | +3.31% | +0.37% to +5.28% |
| 51.2 mm | 157 (3.14%) | 4.011, 3,906 | 1.479, 10,592 | +171.19% | +121.63% to +214.01% |
| 102.4 mm | 59 (1.18%) | 3.559, 4,402 | 1.060, 14,774 | +235.62% | +132.45% to +351.98% |

All three intervals used 1000 valid paired resamples (seed 20260827), with no
invalid replicates.  The 0 mm interval supports a small positive change within
this observed population; it does not support literally no focusing benefit.

The detector-blind source analysis uses two different paired ID populations;
it is not one common three-gap residual curve:

| Connector comparison | Common locked pre-pulse IDs | Conditional axial residual RMS (m/s) |
|---|---:|---:|
| 0 to 51.2 mm | 137 | 49.61 to 17.48 |
| 51.2 to 102.4 mm | 34 | 21.04 to 11.47 |

The corresponding source receipts are in
`paper1_stage_evidence/C1/20260827_120000__s1_connector_gap_triplet_v2/`.
The complete pre-pulse populations are respectively 4558, 393, and 117 out of
5000 mother particles.  Conditional-model residuals are not proof of absolutely
uncorrectable randomness.

At 0 mm the relation-derived setting produces only a small practical change.
At 51.2 mm it lowers FWHM by 63.1% with unchanged detector IDs and hit count;
this is the principal numerical mechanism evidence.  The 102.4 mm arm shows
the same direction but is a low-transmission boundary observation, not a
precision main result.  Its inherited spectrum has two significant KDE modes;
the relation-derived setting has one.  Both longer-gap adjusted spectra have a
small nonzero tail fraction, which must be reported rather than hidden by a
single-resolution metric.

## Conclusion and limits

`PASS_CONTINUE / MODEL_SPECIFIC`: the within-gap controlled comparisons show
that retuning the working point for the current source can substantially improve
focusing without changing detector transmission.  The two source-only paired
comparisons associate longer gaps with smaller conditional residuals and lower
transmission.  Together these results support a model-specific relation between
source conditioning and retuning benefit, not a universal residual threshold or
a causal isolation of residual magnitude from every other gap-dependent source
property.  The small positive change at 0 mm is not evidence of exactly zero
benefit; its significance must use the signed interval, not the old absolute
difference interval.

It does **not** establish a universal source model, measured-instrument
performance, multi-mass behavior, collision/space-charge behavior, a general
analyzer optimum, superiority over a fairly reoptimized existing method, or a
first/novel claim.  The next publication decision should
retain 51.2 mm as the central model-specific result and explicitly present the
102.4 mm transmission tradeoff.
