# Declared dual-cone CAD profile

Use the installed component provider `dual_cone_tandem_quadrupole` with an explicit
source baseline; the sole geometry profile is `declared_cone_following_v1`.
`components.resolve_component` validates source and resolved design together.
The existing `assembly.assemble` accepts that complete provider object in an
explicit recipe, including a single instance with no invented downstream part.
The recipe supplies its proper device-to-assembly `RigidTransform`.

`exporters.export_cad(assembly, format="step", options=..., context=...)` is the
existing managed STEP operation; `exporters.inspect_cad(reference, checks=...)`
cold-reads the published result. Select the declared optional `cad-step` dependency
and explicit `physical_solids`, `write_pcurves`, `precision_mode` and optional
English export name. The engineering context/workspace and shared host ledger
follow the normal deployment API; no SolidWorks, SIMION or GUI is invoked.

The provider emits two truncated conical shells, four elliptical first-stage rods,
four circular second-stage rods and one apertured plate: eleven physical solids
in the same seven scientific groups as the existing driven model. Real mechanical
ports are the first-cone aperture face and the downstream plate aperture face.
The conical entry has no uniform straight aperture-wall thickness, so its port
records null rather than inventing one. No enclosure, flange, pump or fillet is
added. Cone radial truncation comes from the resolved computational closure, not
a confirmed manufacturing outer diameter.

The first-stage CAD rods follow the resolved axial-offset cone surface. Existing
SIMION C0 rods retain their explicitly documented flat upstream surrogate; sharing
the author design does not make those two projections equal. Cone shell profiles
are owned by the component `geometry_members` module and consumed by GEM and CAD;
CAD itself depends on no PA grid, workbench offset, source or drive setting.
The assembly pose applies once to local bodies; the PA embedding is never added.

Member identities and STEP labels retain cone, individual rod and plate identity;
source references resolve into the complete frozen design. The existing export
report records source members, seven groups, pose and serialization profile.
An eleven-solid STEP and selected aperture/metal probes do not certify all holes,
manufacturing tolerances, field equivalence or scientific qualification.
Current evidence and remaining limits are maintained only in [PROJECT](PROJECT.md).
