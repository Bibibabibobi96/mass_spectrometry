"""Explicit inert dual-cone recipe author fixture; never native qualification."""
import copy
import hashlib
import json
from pathlib import Path

from msplatform.backends.simion.dual_cone_transport import SDS_FILES


ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "src/msplatform/components/dual_cone_tandem_quadrupole/config"


def write_dual_cone_recipe_fixture(root: Path) -> Path:
    """Write one small source-bound author input, with an inert gas manifest."""
    root.mkdir(parents=True, exist_ok=True)
    def read(name):
        return json.loads((CONFIG / name).read_text(encoding="utf-8"))
    def write(name, payload):
        (root / name).write_bytes(payload)
        return {"path": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest().upper()}
    native = read("simion_solver_numerics.json")
    geometry = copy.deepcopy(native)
    trajectory = geometry.pop("trajectory")
    fields = {"refine_policy": geometry["pa"].pop("refine_policy")}
    environment = write("environment.json", (CONFIG / "gas_environment.json").read_bytes())
    sources = {name: write(name, ("inert fixture " + name).encode()) for name in SDS_FILES}
    names = ("science", "science_author", "numerics", "geometry", "environment", "species_data",
             "constants_data", "transport_data", "field_csv", "field_metadata")
    records = {name: {"path": "inert_" + name} for name in names}
    manifest = dict(schema_version=2, role="simulation_run_manifest", status="success", inputs=records, outputs=[],
        products={"gas_field": dict(schema_version=1, kind="gas_field", status="complete",
            metadata={"backend": "comsol", "claim_scope": "inert_fixture_not_native"}, data=records)})
    manifest_record = write("gas_manifest.json", json.dumps(manifest).encode())
    request = dict(environment_instance_id="dual_cone", environment_record=environment,
        gas_field_reference=dict(path="gas_manifest.json", sha256=manifest_record["sha256"], product_id="gas_field"),
        sds_records=sources)
    request_record = write("sds_request.json", json.dumps(request).encode())
    frame = read("baseline.json")["coordinate_frame"]["frame_id"]
    source = read("cylindrical_particle_source.json")
    source["particle_count"] = source["mother_particle_count"] = 3
    clock = dict(clock_epoch_id="instrument_clock_epoch_v1",
                 authority_sha256="6A035131B2BDBA6F7F20CBF6B6FD20EDAA5DCB3D7EC8EB7349F74F7AC35238A0")
    science = read("ion_transport_science.json")
    study = dict(schema_version=1, name="dual_cone_inert_recipe_fixture",
        component_requests={"dual_cone": dict(provider_id="dual_cone_tandem_quadrupole", design=read("baseline.json"))},
        recipe=dict(schema_version=2, role="assembly_recipe", integration_id="instrument_assembly",
            recipe_id="dual_cone_inert_recipe_fixture", assembly_frame_id=frame,
            position_tolerance_mm=1e-8, angular_tolerance_rad=1e-10,
            instances=[dict(instance_id="dual_cone", project_id="dual_cone_tandem_quadrupole",
                transform=dict(schema_version=1, role="rigid_transform", from_frame_id=frame, to_frame_id=frame,
                    rotation=[[1,0,0],[0,1,0],[0,0,1]], translation_mm=[0,0,0]))], connections=[], containments=[]),
        drive=dict(clock=dict(phase_reference_instrument_time_us=0.),
            clock_authority=dict(example_resource="instrument_clock_authority_v1.json"),
            dual_cone_electric_field=science["electric_field"]),
        physics=dict(field_model="external_electrostatic_linear", boundary_policy="native_zero_neumann",
            gas_field_interface=read("gas_field_interface.json"), sds_collision_science=science["gas"]),
        release=dict(schema_version=1, role="canonical_birth_source_request", release_spec=source, clock=clock,
            instrument_origin_us=0., species_id="inert_ion", source_component_id="dual_cone", relative_weights=None),
        numerics=dict(geometry=geometry, fields=fields,
            tracing=dict(end_policy=dict(maximum_particle_age_us=trajectory["maximum_time_us"]),
                simion={key: trajectory[key] for key in ("maximum_step_us", "trajectory_quality", "rf_steps_per_period", "random_seed")})),
        cad_export=dict(representation="solid", write_pcurves=True, precision_mode="default"),
        claim_limit="inert software fixture; no native qualification", model_input_sources={
            "fixture": "original author configs; historical source coordinates used directly as device-local coordinates",
            "source_to_device": dict(schema_version=1, role="rigid_transform",
                from_frame_id=source["frame_id"], to_frame_id=frame,
                rotation=[[1,0,0],[0,1,0],[0,0,1]], translation_mm=[0,0,0])})
    study_record = write("study.json", json.dumps(study).encode())
    text = f'''schema_version = 2
constants_version = "repository_particle_physics_v1"
label = "inert dual cone fixture"
particle_tracer = "simion"
field_assembly_strategy = "native_domain_composition"
particle_field_coupling = "external_given_field"
[study]
path = "study.json"
sha256 = "{study_record['sha256']}"
[field_source]
kind = "simion_native"
[recording]
mode = "actual_callback_samples"
sample_interval_us = {trajectory['sample_interval_us']}
end_time_us = {trajectory['maximum_time_us']}
[gas_environment]
status = "sds"
path = "sds_request.json"
sha256 = "{request_record['sha256']}"
'''
    author = root / "author.toml"
    author.write_text(text, encoding="utf-8", newline="\n")
    return author
