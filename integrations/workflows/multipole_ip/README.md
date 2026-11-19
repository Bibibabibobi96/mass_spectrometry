# Continuous RF–IP consumer

`msplatform.workflows.multipole_ip.continuous.run_continuous` calls the existing
public geometry, model, field and tracking stages for a complete RF–IP Assembly.
`track_existing_fields` instead consumes one explicit published RF–IP field bundle;
a missing, tampered or wrong-scope field is refused without rebuilding it.

Supply the following existing inputs explicitly; the consumer does not choose a
physical design, source, drive, gas, mesh or engineering budget.

| Inputs | Existing contract |
|---|---|
| `assembly`, `geometry_numerics` | Complete canonical RF/IP instances, poses, connection and numerical domain |
| `drive`, `physics`, `field_numerics` | Actual model clock authority, phase, scientific-group drive, IP schedule and field settings |
| `particles` | An original `ReleaseRealization` or explicitly bound recorded birth packet, preserving its entire mother cohort |
| `propagation`, `observations`, `tracking_numerics` | `continuous_assembly`, `stop=None`, explicit end policy, observations and supported sequential HS1 numerics |
| `hs1_request` | Typed IP bath, complete outer gas/vacuum field, original vendor record and seed/step controls |
| `context` | Existing execution context with tools and the policies required by the requested stages |

The field-only function takes `fields` in place of the design/model/field inputs.
Both functions forward `birth_source_authority`, `unit_size`,
`recovery_reference` and `dispatch_profiles` to public tracking when supplied.
Recovery uses this explicit field path; the design path deliberately builds and
solves. Full birth admission runs before expensive stages without resampling;
geometry, model-clock and field applicability remain checked by their public
stages. The result is the normal trajectory artifact, with its original mother,
clock, observations, losses and provenance. Interfaces do not reinitialize it.

For an existing field, `continuous.ps1` invokes the same installed module with
`-ReleaseRequest -FieldsReference -Propagation -Observations -Numerics
-Hs1Request -Environment -Workspace -Profile`. The HS1 JSON schema is packaged
beside `continuous.py`; it explicitly describes the bath box, uniform outer
field and vendor path, which may be absolute or relative to that document.
Optional recovery, dispatch and unit-size inputs follow the public tracker.
The PowerShell layer only forwards these inputs and the selected Python.

Software tests cover the real compiler, field reader, managed tracking/recovery,
typed HS1/CLI admission and failure guards using an inert native leaf. Real
construction, Refine, coupled-field and HS1 qualification remain open. The
existing segmented preparation entry stays until that corresponding native
replacement is validated; adding the continuous consumer does not retire it.
