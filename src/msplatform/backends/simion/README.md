# SIMION geometry compiler

`compile_geometry(assembly, *, numerics)` compiles the supported RF/oaTOF
assembly into `CompiledSimionGeometry`. It reads installed GEM resources but
does not create a run, sample particles, start SIMION, Refine, Fly or open a GUI.

The assembly mapping contains `composition_plan` and `components_resolved`.
The plan retains its complete parent and explicit scope; resolved designs cover
exactly the selected instances. The compiler checks the plan against the
existing assembly compiler, including mechanical connections and scope.

Geometry numerics contains `frontend_domains`, `geometry_build` and
`detector_marker`. The optional `electrode_group_native_ids` supplies an expert
native-label mapping. Without it, the backend allocates labels automatically.
Scientific group IDs remain provider-owned. The supported default native range
is SIMION 8.1's 1–1000, not a physical limit on RF segmentation.

The result contains:

- `frontend_gems`: complete GEM text for the parent and optional entrance patch.
- `frontend_geometry`: validated poses, scope, native maps and grid metadata.
- `downstream_specs`: flight-tube, reflectron and detector GEM templates with
  complete `template_variables` and native-instance metadata. SIMION's GEM Lua
  preprocessor consumes these variables as `_G.var`; these are build-only
  specifications, not refined fields or built PA assets.
- `provider_content_identities`: hashes of actual supplied component content
  and interfaces. These are content identities, not filesystem receipts.

`resources.gem_template_path/text(role)` reads the single installed template
for each downstream role. Missing resources fail explicitly. Legacy outer
workflows keep their real file-record, run and process responsibilities and
delegate pure compilation here. Their explicit old-version adapters remain
compatibility boundaries; they do not define new scientific identities.

Validation includes direct request4/axial3/array2, retained request3 and legacy
plan readers, zero-gap collision/common-ground cases, original template bytes,
historical GEM region/grid vectors and source-independent compilation.
Software verification does not grant native, GUI or scientific qualification.

## Static gas runtime compilation

`gas_runtime.compile_gas_runtime(field, *, placement=None)` emits a local Lua 5.1
sampler from an explicitly prepared static gas field. It performs no I/O, native
operation, vendor callback installation or random draw. Positions use mm; gas
velocity uses m/s and rotates once into the query frame. Joint lookup preserves
explicit domain/status semantics and the legacy positive-weight valid-corner
grid policy, including .9g field values, .17g grid geometry and 8192-value chunks.
It has no particle/time cache. The older uniform-control envelope tolerance is
not silently applied to canonical fields.

Actual emitted-Lua tests cover serialization, masks, endpoints, pose, source
metadata, thin-region point sequences and Python/Lua finite-value failures.
These T2 checks do not prove native step crossing or collision physics. Existing
IP/SDS Program adoption and retirement of the old component generators
remain separate migration work; their callback/RNG ordering must be preserved.

The composed gas tests and Changed routing passed; the initial architecture check
exposed the missing backend-to-gas rule, then all ten boundary methods passed after
adding only that intended direction. The original ordinary-install parent passed
in 252.068 seconds with source access denied: direct wheel and sdist-rebuilt wheel
both exercise installed gas compilation and the canonical RF sine/cosine probe.
All package payloads match source and sdist. This does not close Program/native
gas acceptance or the final Repository/performance requirements.
