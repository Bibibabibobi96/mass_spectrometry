"""Frozen public recipes orchestrate existing native owners and SI result readers.

The legacy execution owner retains ownership of PA/MPH payloads. ArtifactStore
owns only small verified references, canonical scientific data and run evidence.
"""
from __future__ import annotations

import base64
import copy
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from typing import Any

from msplatform import assembly, components
from msplatform.io.file_identity import canonical_json_sha256, file_sha256
from msplatform.io.manifest_records import file_record
from msplatform.recipes import SimulationRecipe, validate_recipe
from msplatform.results.particle_data import read_particle_data, summarize_particle_data, write_particle_data
from msplatform.results.model import TraceResult
from msplatform.storage import ArtifactStore


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")


def _executable_records(paths):
    # Installed executables are implementation evidence, not owned PA/MPH
    # payloads. Declare that role even above the shared large-file I/O tier.
    return {name: {key: value for key, value in file_record(Path(path), "required_evidence").items()
                   if key in {"bytes", "sha256"}} for name, path in paths.items()}


def _assembly(recipe: dict):
    study = recipe["study"]["document"]
    resolved = {name: components.resolve_component(request) for name, request in study["component_requests"].items()}
    return assembly.assemble(study["recipe"], resolved, local_scope=study.get("local_scope"))


def _realizations(release, *, resource_root=None):
    from msplatform.particle_release import load_recorded_release, sample_release
    if release["role"] == "canonical_mass_scan_request":
        from .mass_scan import prepare_mass_scan
        return prepare_mass_scan(release)
    if release["role"] == "canonical_recorded_birth_request":
        if resource_root is None:
            raise ValueError("recorded birth requires the frozen resource directory")
        from msplatform.contracts.clock import ClockIdentity
        source = Path(resource_root) / "recorded_birth.csv"
        record = file_record(source)
        expected = release["source_record"]
        if record["bytes"] != expected["bytes"] or record["sha256"].upper() != expected["sha256"].upper():
            raise ValueError("recorded birth snapshot differs from its frozen source")
        species = release["species"]
        packet = load_recorded_release(record, clock=ClockIdentity(**release["clock"]),
            frame_id=release["frame_id"], source_component_id=release["source_component_id"],
            species_id=release["species_id"], species_kind=species["species_kind"],
            relative_weights=release["relative_weights"], instrument_origin_us=release["instrument_origin_us"],
            expected_particle_ids=release["particle_ids"])
        if any(row["mass_amu"] != species["mass_amu"] or row["charge_state"] != species["charge_state"]
               for row in packet["rows"]):
            raise ValueError("recorded birth rows differ from the explicit species")
        return [packet]
    return [sample_release(release)]


def _archive_comsol_detector_contract(trajectory, directory):
    """Freeze the actual guarded native plan; the full field asset may later be collected."""
    import hashlib
    record = trajectory.data_records.get("plan")
    if not isinstance(record, dict):
        raise ValueError("COMSOL trajectory lacks its manifest-bound detector plan")
    payload = trajectory.data_path("plan").read_bytes()
    if len(payload) != record["bytes"] or hashlib.sha256(payload).hexdigest().upper() != str(record["sha256"]).upper():
        raise ValueError("COMSOL trajectory plan differs from its protected record")
    facts_record = trajectory.data_records.get("native_facts")
    if not isinstance(facts_record, dict):
        raise ValueError("COMSOL trajectory lacks its manifest-bound native facts")
    facts = trajectory.data_path("native_facts").read_bytes()
    if len(facts) != facts_record["bytes"] or hashlib.sha256(facts).hexdigest().upper() != str(facts_record["sha256"]).upper():
        raise ValueError("COMSOL trajectory facts differ from their protected record")
    plan = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(plan, dict) or "detector_active_face" not in plan:
        raise ValueError("COMSOL plan lacks an explicit detector face declaration")
    face = plan["detector_active_face"]
    if face is not None and not isinstance(face, dict):
        raise ValueError("COMSOL detector face must be an explicit object or null")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "detector_plan.json").write_bytes(payload)
    (directory / "detector_native_facts.json").write_bytes(facts)
    _write(directory / "detector_contract.json", {"schema_version": 1, "role": "public_native_detector_contract",
        "backend": "comsol", "source_reference": copy.deepcopy(trajectory.reference),
        "source_plan_sha256": str(record["sha256"]).upper(),
        "source_facts_sha256": str(facts_record["sha256"]).upper(), "detector_active_face": copy.deepcopy(face)})


def _particle_document(particles):
    return particles.to_dict() if hasattr(particles, "to_dict") else particles


def compile_sds_inputs(recipe, instrument):
    """Compile the frozen Study without admitting its CFD payload or starting an owner."""
    from msplatform.backends.simion.dual_cone_stages import plan_geometry_stage, plan_model_stage
    from msplatform.backends.simion.dual_cone_transport import source_placement
    from msplatform.recipes.dual_cone import project_sds_numerics, validate_sds_physics, validate_sds_release

    study = recipe["study"]["document"]
    if recipe["gas_environment"]["status"] != "sds":
        raise ValueError("SDS planning requires an explicitly selected SDS environment")
    scope = instrument.composition_plan["scope"]["instance_ids"]
    if scope != ["dual_cone"] or instrument.components["dual_cone"].provider_id != "dual_cone_tandem_quadrupole":
        raise ValueError("SDS planning requires the actual single dual-cone Assembly")
    resolved = instrument.components["dual_cone"].resolved_design
    numerics = project_sds_numerics(study, recipe["recording"])
    source = validate_sds_release(study["release"])
    interface, collision = validate_sds_physics(study)
    placement = study["recipe"]["instances"][0]["transform"]
    geometry = plan_geometry_stage(resolved=resolved, numerics=numerics, placement=placement)
    physics = {name: study["physics"][name] for name in ("field_model", "boundary_policy")}
    clock = {**study["release"]["clock"], **study["drive"]["clock"]}
    model = plan_model_stage(geometry["projection"], electric_field=study["drive"]["dual_cone_electric_field"],
                             clock=clock, physics=physics, placement=placement)
    source_to_device = study["model_input_sources"].get("source_to_device")
    source_world, _ = source_placement(resolved, numerics, source, placement=placement,
                                       source_to_device=source_to_device)
    return {"resolved": resolved, "numerics": numerics, "source": source, "interface": interface,
            "collision_science": collision, "placement": placement, "source_to_device": source_to_device,
            "geometry_plan": geometry,
            "model_plan": model, "source_frame_id": source_world.to_frame_id}


def _materialize_sds_inputs(recipe, directory):
    """Write only authenticated frozen small SDS inputs for the existing stage owner."""
    from msplatform.recipes.dual_cone import (project_sds_numerics, sds_environment_bytes,
                                               sds_resource_identities, validate_sds_physics,
                                               validate_sds_release, validate_sds_resources)

    snapshots = recipe["resource_snapshots"]["sds"]
    digest = recipe["gas_environment"]["sha256"]
    validate_sds_resources(snapshots, digest)
    study = recipe["study"]["document"]
    interface, collision = validate_sds_physics(study)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    sds_dir = directory / "sds"
    sds_dir.mkdir()
    identities = sds_resource_identities(snapshots, digest)
    for name in identities:
        (sds_dir / name).write_bytes(base64.b64decode(snapshots[name]["bytes_base64"], validate=True))
    source_path, numerics_path, interface_path = (directory / name for name in
                                                    ("source.json", "numerics.json", "interface.json"))
    _write(source_path, validate_sds_release(study["release"]))
    _write(numerics_path, project_sds_numerics(study, recipe["recording"]))
    _write(interface_path, interface)
    return {"source_path": source_path, "numerics_path": numerics_path, "interface_path": interface_path,
            "sds_dir": sds_dir, "identities": identities, "collision_science": collision,
            "environment_bytes": sds_environment_bytes(snapshots, digest),
            "gas_field_reference": copy.deepcopy(snapshots["sds_gas_field"]["reference"])}


def _preflight_sds(recipe, instrument, *, context, artifact_store):
    """Compile SDS authoring and admit the actual CFD source when a context is supplied."""
    from msplatform.backends.simion.dual_cone_transport import admit_sds_gas_field
    from msplatform.recipes.dual_cone import sds_environment_bytes
    from msplatform.execution.native_source_guard import guard_native_source

    plan = compile_sds_inputs(recipe, instrument)
    closure = recipe["resource_snapshots"]["sds"]
    available = None
    source_status = "not_checked_without_context"
    if context is not None:
        reference = closure["sds_gas_field"]["reference"]
        with guard_native_source(reference, expected_kind="gas_field",
                expected_artifact_root=context.workspace / "artifacts", artifact_store=artifact_store) as gas:
            admit_sds_gas_field(gas.reference,
                environment_bytes=sds_environment_bytes(closure, recipe["gas_environment"]["sha256"]),
                resolved=plan["resolved"], interface=plan["interface"])
        source_status = "guarded_and_admitted"
        available = (context.python_executable.is_file() and context.powershell_executable.is_file()
                     and "simion" in context.tools and context.tools["simion"].is_file())
    return {"field_source": "simion_native", "particle_tracer": "simion",
            "field_assembly_strategy": "native_domain_composition", "implemented": True,
            "host_available": available, "native_verified": False, "verification_scope": "scientific_compilation_only",
            "assembly_id": recipe["assembly"]["assembly_id"], "gas_source_admission": source_status,
            "limitations": ["SDS observations are actual callback samples, not a uniform or exact time grid",
                            "actual native field and particle execution require separate qualification"]}


def _run_sds_stages(recipe, instrument, inputs, gas, *, store, stack, context, claims, calls, account, invoke,
                    implementation, clock_authority_reference):
    """Run existing dual-cone stage owners with an already guarded CFD source."""
    from msplatform.backends.simion import dual_cone_stages
    from msplatform.backends.simion.dual_cone_transport import admit_sds_gas_field

    plan = compile_sds_inputs(recipe, instrument)
    _, _, _, admitted = admit_sds_gas_field(gas.reference, environment_bytes=inputs["environment_bytes"],
                                             resolved=plan["resolved"], interface=plan["interface"])
    study = recipe["study"]["document"]
    raw_root = context.workspace / "artifacts"
    receipts = {}
    def stage(name, identity, produce, kind, *, detector_required=True):
        stage_implementation = implementation if name == "track" else {
            key: value for key, value in implementation.items() if key != "workflow"}
        key = canonical_json_sha256({"stage": "dual_cone_" + name, "identity": identity,
                                     "implementation": stage_implementation})
        artifact, receipt = _native_reference(store, stack, key, lambda: invoke(produce), kind=kind,
            raw_root=raw_root, claims=claims, calls=calls, account=account, detector_required=detector_required)
        receipts[name] = receipt
        return artifact, key

    geometry, geometry_key = stage("geometry", plan["geometry_plan"],
        lambda: dual_cone_stages.build_geometry(resolved=plan["resolved"], numerics=plan["numerics"],
                                                placement=plan["placement"], context=context), "geometry_artifact")
    model, model_key = stage("model", {"geometry": geometry_key, "plan": plan["model_plan"],
                                      "clock": recipe["resource_snapshots"]["instrument_epoch_v1.json"]["sha256"]},
        lambda: dual_cone_stages.prepare_model(geometry, electric_field=study["drive"]["dual_cone_electric_field"],
            clock=plan["model_plan"]["projection"]["clock"], physics=plan["model_plan"]["projection"]["physics"],
            clock_authority_reference=clock_authority_reference, placement=plan["placement"], context=context), "prepared_model")
    field, field_key = stage("fields", {"model": model_key, "numerics": study["numerics"]["fields"]},
        lambda: dual_cone_stages.solve_fields(model, numerics=plan["numerics"], context=context), "field_bundle")
    gas_identity = {"manifest_sha256": gas.reference["manifest"]["sha256"],
                    "product_id": gas.reference["product_id"]}
    identity = {"field": field_key, "gas": gas_identity, "source": plan["source"],
                "placement": plan["placement"], "source_to_device": plan["source_to_device"],
                "numerics": plan["numerics"], "collision": plan["collision_science"],
                "sds_sources": inputs["identities"], "recording": recipe["recording"],
                "species": recipe["species"], "clock": study["release"]["clock"]}
    clock = {"basis": "experiment_relative", "unit": "s", **study["release"]["clock"]}
    trajectory, _ = stage("track", identity,
        lambda: dual_cone_stages.track_fields(field, gas_field_reference=gas.reference,
            source_spec_path=inputs["source_path"], numerics_path=inputs["numerics_path"],
            collision_science=plan["collision_science"], interface_path=inputs["interface_path"],
            collision_sds_dir=inputs["sds_dir"], context=context, placement=plan["placement"],
            source_to_device=plan["source_to_device"], canonical_result={"species": recipe["species"][0],
                "frame_id": plan["source_frame_id"], "clock": clock},
            expected_gas_environment=admitted.to_dict(), expected_sds_records=inputs["identities"],
            frozen_environment_bytes=inputs["environment_bytes"]), "trajectory_result", detector_required=False)
    return trajectory, receipts


def _guarded_focus_authority(recipe, model, *, resource_root, stack):
    """Recompute focus authority from the frozen author under both file guards."""
    from importlib.resources import files
    from msplatform.io.file_identity import guarded_file_identity
    from .oa_focus_model_projection import project_focus_model

    snapshots = recipe["resource_snapshots"]
    campaign_path = Path(resource_root) / "oa_focus_campaign.json"
    contract_path = Path(str(files("msplatform.components.orthogonal_accelerator").joinpath("component_contract.json")))
    for name, path in (("oa_focus_campaign.json", campaign_path), ("oa_focus_component_contract.json", contract_path)):
        payload = base64.b64decode(snapshots[name]["bytes_base64"], validate=True)
        identity = snapshots[name]["sha256"]
        stack.enter_context(guarded_file_identity(path, expected_bytes=len(payload), expected_sha256=identity))
    study = recipe["study"]["document"]
    profile = study["component_requests"]["oa"]["design"]["geometry_profile"]
    cell = study["numerics"]["geometry"]["component_domains"]["oa"]["cell_mm_xyz"]
    projected = project_focus_model(campaign_path, geometry_profile=profile,
                                    mesh_mm_per_gu=[cell[axis] for axis in "xyz"],
                                    clock=model.document["drive"]["clock"])
    if projected["model"].document != model.document:
        raise ValueError("OA focus campaign projection differs from the selected Study model")
    return projected["observations"]


def _hs1_request(recipe, resource_root):
    if recipe["gas_environment"]["status"] == "vacuum":
        return None
    from msplatform.contracts.gas import BoxDomain
    document = json.loads((Path(resource_root) / "hs1_request.json").read_text(encoding="utf-8-sig"))
    def box(value):
        if set(value) != {"minimum_mm", "maximum_mm", "lower_closed", "upper_closed"}:
            raise ValueError("HS1 box requires explicit bounds and closure")
        return BoxDomain(tuple(value["minimum_mm"]), tuple(value["maximum_mm"]),
                         tuple(value["lower_closed"]), tuple(value["upper_closed"]))
    return dict(bath_domain=box(document["bath_domain"]),
        outer_domain=box(document["outer_domain"]),
        numerics=dict(document["numerics"]), environment_instance_id=document["environment_instance_id"],
        environment_record=file_record(Path(resource_root)/"hs1_environment.json"),
        vendor_record=file_record(Path(resource_root)/"hs1_vendor.lua"))


def _flight_request(recipe, instrument, particles, *, focus_authority=None):
    study = recipe["study"]["document"]
    selected = recipe["recording"].get("plane_observations")
    if focus_authority is not None:
        if selected not in (None, []):
            raise ValueError("OA focus planes come only from the authenticated campaign")
        selected = []
    if selected is None:
        tof = [name for name, component in instrument.components.items() if component.provider_id == "single_reflection_tof"]
        if len(tof) != 1:
            raise ValueError("a study without one TOF detector requires explicit plane observations")
        selected = [{"schema_version": 2, "observation_id": "detector", "source_instance_id": tof[0],
                     "surface_id": "detector_active_face", "max_records": len(_particle_document(particles)["rows"])}]
    observations = {"plane_observations": copy.deepcopy(selected),
                    "observation_times_us": recipe["recording"]["observation_times_us"]}
    if focus_authority is not None:
        observations["oa_focus_authority"] = copy.deepcopy(focus_authority)
    if "oa_focus_field_mode" in recipe["recording"]:
        if focus_authority is None:
            raise ValueError("OA focus field mode requires authenticated focus authority")
        observations["oa_focus_field_mode"] = recipe["recording"]["oa_focus_field_mode"]
    if "field_intervention" in recipe["recording"]:
        observations["field_intervention"] = copy.deepcopy(recipe["recording"]["field_intervention"])
    propagation = {"schema_version": 1, "scope": "continuous_assembly", "stop": None,
                   "consumed_plane_events": [], "end_policy": study["numerics"]["tracing"]["end_policy"]}
    if focus_authority is not None:
        propagation["publication_contract"] = "oa_focus_original_birth_si_v1"
        propagation["dynamics"] = {"kinematics": "nonrelativistic", "collisions": "none", "space_charge": "none"}
    if recipe["gas_environment"]["status"] == "hs1":
        propagation["dynamics"] = {"kinematics": "nonrelativistic", "collisions": "hs1", "space_charge": "none"}
    providers = [instrument.components[name].provider_id for name in instrument.composition_plan["scope"]["instance_ids"]]
    if len(providers) == 2 and set(providers) == {"rf_multipole", "ion_processor"}:
        if selected != []:
            raise ValueError("public RF-IP SI tracing requires explicitly empty plane observations")
        propagation["publication_contract"] = "original_birth_si_v1"
    return propagation, observations


def _validated_simion_field_reference(recipe):
    """Apply the one recipe and frozen-manifest authority before source access."""
    from msplatform.recipes.native_assets import validate_collision_reference

    recipe = validate_recipe(recipe)
    if recipe['schema_version'] != 2:
        raise ValueError('explicit native field reference requires a frozen native recipe')
    source = recipe.get('field_source')
    if not isinstance(source, dict) or set(source) != {'kind', 'reference'} or source['kind'] != 'simion_native':
        raise ValueError('an explicit SIMION native field reference is required')
    return recipe, validate_collision_reference(source['reference'])


def _admit_simion_field_reference(recipe, *, expected_model, field_numerics, artifact=None):
    """Validate author-derived inputs before the scientific field admission."""
    from .simion_field_reference import admit_simion_field_reference

    recipe, frozen = _validated_simion_field_reference(recipe)
    authority = json.loads(base64.b64decode(recipe['resource_snapshots']['instrument_clock_authority_v1.json']['bytes_base64']))
    return admit_simion_field_reference(recipe['study']['document'], reference=frozen['reference'],
        clock_authority=authority, expected_model=expected_model, field_numerics=field_numerics, artifact=artifact)


def compile_simion_model(recipe: dict):
    """Recompile a validated frozen Study and clock as its one SIMION model."""
    from msplatform.backends import simion
    from msplatform.backends.simion.model import compile_prepared_model
    recipe = validate_recipe(recipe)
    if recipe["schema_version"] != 2 or recipe["particle_tracer"] != "simion":
        raise ValueError("SIMION model requires a resolved native SIMION recipe")
    instrument = _assembly(recipe)
    study = recipe["study"]["document"]
    compiled = simion.compile_geometry(instrument, numerics=study["numerics"]["geometry"])
    from msplatform.contracts.pulse import field_reference_drive
    drive = field_reference_drive(study["drive"])
    authority = json.loads(base64.b64decode(recipe["resource_snapshots"]["instrument_clock_authority_v1.json"]["bytes_base64"]))
    drive.pop("clock_authority")
    drive["clock"].update(clock_epoch_id=authority["clock_epoch_id"], authority_sha256=authority["authority"]["sha256"])
    return compile_prepared_model(compiled, instrument.components_resolved, drive=drive, physics=study["physics"])


def _guard_compensation_sources(recipe, *, stack, context, artifact_store, compensated_model):
    """Hold and revalidate the complete declared fit lineage through consumption."""
    snapshot = recipe["resource_snapshots"].get("compensation_provenance.json")
    if snapshot is None:
        return None
    if context is None or artifact_store is None:
        raise ValueError("compensation provenance requires an execution workspace and ArtifactStore for source validation")
    from msplatform.backends.simion.artifacts import CompiledPreparedModel
    from msplatform.backends.simion.reflectron_response_binding import fit_sampled_axis, plan_compensated_reflectron
    from msplatform.execution.native_source_guard import guard_native_source
    provenance = json.loads(base64.b64decode(snapshot["bytes_base64"]))
    original = validate_recipe(provenance["original_resolved_recipe"])
    if original["recipe_id"] != provenance["original_recipe_id"]:
        raise ValueError("compensation original recipe identity differs")
    original_model = compile_simion_model(original)
    if original_model.document["model_identity_sha256"] != provenance["original_model_identity_sha256"]:
        raise ValueError("compensation original model identity differs")
    source_asset_ids = set()
    axis = stack.enter_context(guard_native_source(provenance["axis_samples_reference"], expected_kind="axis_response_samples",
        expected_artifact_root=context.workspace / "artifacts", artifact_store=artifact_store, asset_ids=source_asset_ids))
    field = stack.enter_context(guard_native_source(provenance["original_field_reference"], expected_kind="field_bundle",
        expected_artifact_root=context.workspace / "artifacts", artifact_store=artifact_store, asset_ids=source_asset_ids))
    stored_model = CompiledPreparedModel(field.data_path("compiled_model").read_text(encoding="utf-8-sig"))
    if stored_model.document != original_model.document:
        raise ValueError("compensation source field differs from the original recipe model")
    binding = axis.metadata["binding"]
    def identity(reference):
        return {"product_id": reference["product_id"],
                "bytes": reference["manifest"]["bytes"], "sha256": reference["manifest"]["sha256"].upper()}
    if (binding["model_identity_sha256"] != provenance["original_model_identity_sha256"]
            or identity(binding["field_reference"]) != identity(field.reference)):
        raise ValueError("compensation axis and original field identity differ")
    fit = fit_sampled_axis(axis)
    if canonical_json_sha256(fit) != canonical_json_sha256(provenance["fit"]):
        raise ValueError("compensation fit differs from the authenticated axis samples")
    if original_model.document["geometry"]["frontend_geometry"]["tof_instance_id"] != provenance["instance_id"]:
        raise ValueError("compensation target differs from the original model")
    plan_compensated_reflectron(field, original_model=original_model, compensated_model=compensated_model,
        expected_downstream_identity=binding["downstream_identity"], expected_grid=binding["grid"],
        expected_frame_id=binding["frame_id"], fit=fit, regularization=fit["fit"]["regularization"])
    return {"declared": provenance, "source_asset_ids": sorted(source_asset_ids),
            "axis_owner": _native_owner_evidence(artifact_store, axis),
            "field_owner": _native_owner_evidence(artifact_store, field)}


def _require_oa_focus_contrast_ready():
    raise ValueError("OA focus field contrast is not yet validated for public execution")


def preflight_native(recipe: dict, *, context=None, artifact_store=None) -> dict:
    """Check scientific compilation independently of host availability/native evidence."""
    recipe = validate_recipe(recipe)
    if recipe["schema_version"] != 2:
        raise ValueError("native preflight requires a native resolved recipe")
    selected = (recipe["field_source"]["kind"], recipe["particle_tracer"], recipe["field_assembly_strategy"])
    if ("compensation_provenance.json" in recipe["resource_snapshots"]
            and selected != ("simion_native", "simion", "native_domain_composition")):
        raise ValueError("compensation provenance requires the SIMION native field strategy")
    if selected not in {("simion_native", "simion", "native_domain_composition"),
                        ("simion_native", "simion", "sampled_joint_field"),
                        ("comsol_native", "comsol", "joint_solve"),
                        ("comsol_native", "simion", "sampled_joint_field")}:
        raise ValueError("native public execution is not yet implemented for this field/tracer/assembly combination")
    instrument = _assembly(recipe)
    providers = [instrument.components[name].provider_id for name in instrument.composition_plan["scope"]["instance_ids"]]
    split = (providers.count("orthogonal_accelerator") == 1 and providers.count("single_reflection_tof") == 1
             and all(name in {"orthogonal_accelerator", "single_reflection_tof", "rf_multipole"} for name in providers)
             and providers.count("rf_multipole") <= 1)
    ip_mr = (providers.count("ion_processor") == 1
             and providers.count("multi_reflection_tof") == 1
             and all(name in {"ion_processor", "multi_reflection_tof", "rf_multipole"} for name in providers)
             and providers.count("rf_multipole") <= 1)
    local_mr = providers == ["multi_reflection_tof"]
    focus = providers == ["orthogonal_accelerator"] and "oa_focus_campaign.json" in recipe["resource_snapshots"]
    rf_ip = len(providers) == 2 and set(providers) == {"rf_multipole", "ion_processor"}
    if recipe["gas_environment"]["status"] == "sds":
        return _preflight_sds(recipe, instrument, context=context, artifact_store=artifact_store)
    if ("field_intervention" in recipe["recording"] or "field_interventions" in recipe["recording"]) and not split:
        raise ValueError("field intervention requires the actual split OA and TOF assembly")
    discovery = recipe["study"]["document"].get("drive", {}).get("pulse", {}).get("mode") == "discover"
    if discovery and (not split or selected != ("simion_native", "simion", "native_domain_composition")
                      or recipe["study"]["document"]["release"].get("role") == "canonical_mass_scan_request"):
        raise ValueError("discovery requires one original-birth split SIMION native-field cohort")
    if not split and not ip_mr and not local_mr and not rf_ip and not focus:
        raise ValueError("native execution requires a supported split TOF, RF-IP, IP-MR, local MR or focus assembly")
    if "oa_focus_field_modes" in recipe["recording"]:
        if not focus:
            raise ValueError("OA focus field modes require the independent authenticated OA scope")
        _require_oa_focus_contrast_ready()
    if focus:
        if (selected != ("simion_native", "simion", "native_domain_composition")
                or recipe["gas_environment"]["status"] != "vacuum" or "reference" in recipe["field_source"]
                or recipe["recording"].get("plane_observations") not in (None, [])):
            raise ValueError("OA focus requires its native field, vacuum and campaign-derived planes")
    if rf_ip and (selected != ("simion_native", "simion", "native_domain_composition")
                  or recipe["gas_environment"]["status"] != "hs1"
                  or recipe["recording"].get("plane_observations") != []):
        raise ValueError("RF-IP requires its native field producer, HS1 and explicit empty plane observations")
    if local_mr and (selected != ("simion_native", "simion", "sampled_joint_field")
                     or recipe["study"]["document"]["schema_version"] != 2
                     or "reference" not in recipe["field_source"] or recipe["gas_environment"]["status"] != "vacuum"
                     or "plane_observations" not in recipe["recording"]):
        raise ValueError("local MR requires explicit scope, sampled SIMION field, vacuum and plane observations")
    if ip_mr and (selected != ("simion_native", "simion", "sampled_joint_field")
                  or "reference" not in recipe["field_source"] or recipe["gas_environment"]["status"] != "hs1"):
        raise ValueError("IP-MR requires an explicit sampled SIMION field reference and HS1 environment")
    if split and selected == ("simion_native", "simion", "sampled_joint_field"):
        raise ValueError("split TOF requires its declared native-domain field strategy")
    if split and recipe["gas_environment"]["status"] != "vacuum":
        raise ValueError("split TOF native tracing currently requires explicit vacuum")
    if selected[0] == "comsol_native":
        scalar = selected[1] == "simion"
        if scalar:
            from .scalar_tracing import compile_scalar_inputs
            admission = compile_scalar_inputs(recipe)
            if context is not None:
                root = (context.workspace / "artifacts").resolve()
                if any(root not in admission[name].manifest_location.resolve().parents
                       for name in ("background", "on", "prepared", "geometry", "collision")):
                    raise ValueError("scalar source owners must belong to the explicit execution workspace artifact root")
        else:
            from .comsol_tracing import compile_comsol_inputs
            for particles in _realizations(recipe["study"]["document"]["release"]):
                compile_comsol_inputs(recipe, instrument, particles)
        available = None if context is None else (
            context.python_executable.is_file() and context.powershell_executable.is_file()
            and all(name in context.tools and context.tools[name].is_file() for name in ("comsol", "comsol_launcher"))
            and "matlab_root" in context.tools and (context.tools["matlab_root"] / "bin/matlab.exe").is_file())
        if scalar and available is not None:
            available = available and "simion" in context.tools and context.tools["simion"].is_file()
        return {"field_source": selected[0], "particle_tracer": selected[1], "field_assembly_strategy": selected[2],
                "implemented": True, "host_available": available, "native_verified": False,
                "verification_scope": "scientific_compilation_only", "assembly_id": recipe["assembly"]["assembly_id"],
                "limitations": (["explicit frozen OFF/ON source and collision carrier; no Compute or Refine fallback",
                                  "sample support and numerical accuracy require actual native qualification"] if scalar else
                                ["one common birth time and species per native batch; no RF",
                                "finite exterior potential differs from the SIMION Neumann boundary",
                                "actual native fields and particle tracing remain separately qualified"])}
    from msplatform.backends.simion.field_execution import plan_fields_execution
    study = recipe["study"]["document"]
    model = compile_simion_model(recipe)
    from msplatform.backends.simion.tracking_execution import plan_tracking_execution
    # Admission protects the selected field throughout planning; no native process is started.
    with ExitStack() as stack:
        _guard_compensation_sources(recipe, stack=stack, context=context, artifact_store=artifact_store,
                                    compensated_model=model)
        selected_field = None
        if ip_mr or local_mr:
            if study["numerics"]["fields"] != {"mode": "frozen_sampled_field"}:
                raise ValueError("IP-MR requires explicitly frozen sampled-field numerics")
        else:
            plan_fields_execution(model, numerics=study["numerics"]["fields"])
        if 'reference' in recipe['field_source']:
            if context is None:
                raise ValueError('explicit SIMION field reference requires an execution workspace for owner validation')
            from msplatform.execution.native_source_guard import guard_native_source
            recipe, frozen = _validated_simion_field_reference(recipe)
            selected_field = stack.enter_context(guard_native_source(frozen['reference'], expected_kind='field_bundle',
                                             expected_artifact_root=context.workspace/'artifacts', artifact_store=artifact_store))
            _admit_simion_field_reference(recipe, expected_model=model, field_numerics=study['numerics']['fields'], artifact=selected_field)
        directory = stack.enter_context(tempfile.TemporaryDirectory(prefix="msplatform-preflight-"))
        root = Path(directory)
        for name, snapshot in recipe["resource_snapshots"].items():
            (root / name).write_bytes(base64.b64decode(snapshot["bytes_base64"]))
        clocks = {"clock_authority": file_record(root / "instrument_clock_authority_v1.json"),
                  "instrument_epoch": file_record(root / "instrument_epoch_v1.json")}
        focus_authority = None
        focus_testplane_record = None
        if focus:
            if context is None or "simion" not in context.tools or not Path(context.tools["simion"]).is_file():
                raise ValueError("OA focus preflight requires an explicit SIMION executable and TestPlane")
            from msplatform.io.file_identity import guarded_file_identity
            focus_authority = _guarded_focus_authority(recipe, model, resource_root=root, stack=stack)
            testplane = Path(context.tools["simion"]).resolve().parent / "examples/test_plane/testplanelib.lua"
            if not testplane.is_file():
                raise ValueError("OA focus preflight requires the installed SIMION TestPlane library")
            focus_testplane_record = file_record(testplane, "required_evidence")
            stack.enter_context(guarded_file_identity(testplane, expected_bytes=focus_testplane_record["bytes"],
                                                       expected_sha256=focus_testplane_record["sha256"]))
        hs1 = _hs1_request(recipe, root)
        for particles in _realizations(study["release"], resource_root=root):
            propagation, observations = _flight_request(recipe, instrument, particles, focus_authority=focus_authority)
            if discovery:
                author = copy.deepcopy(study["drive"]["pulse"])
                observations["observation_times_us"] = author["candidate_times_us"]
                observations["pulse_discovery"] = {"phase": "discovery", "author": author}
            plan_tracking_execution(model, particles=_particle_document(particles), clock_records=clocks,
                propagation=propagation, observations=observations, numerics=study["numerics"]["tracing"]["simion"],
                **({'hs1_request': hs1, 'ip_mr_field_reference': selected_field.reference} if ip_mr else
                   {'hs1_request': hs1} if rf_ip else {}),
                **({'neutral_sampled_field_reference': selected_field.reference} if local_mr else {}),
                **({'focus_testplane_record': focus_testplane_record} if focus_testplane_record is not None else {}))
    available = None if context is None else all(
        Path(path).is_file() for path in (context.python_executable, context.powershell_executable,
                                         context.tools.get("simion", Path("missing-simion"))))
    return {"field_source": selected[0], "particle_tracer": selected[1], "field_assembly_strategy": selected[2],
            "implemented": True, "host_available": available, "native_verified": False,
            "verification_scope": "scientific_compilation_only", "assembly_id": recipe["assembly"]["assembly_id"],
            "limitations": (["RF-IP uses one original birth cohort and the explicitly declared HS1 model",
                             "native qualification requires a recorded actual run"] if rf_ip else
                            ["IP-MR uses the explicitly published sampled field and declared HS1 model",
                             "native qualification requires a recorded actual run"] if ip_mr else
                            ["local MR uses an explicitly published sampled field and an independent original-birth source",
                             "the authored local scope retains its parent boundary; no upstream continuation is inferred",
                             "native qualification requires a recorded actual run"] if local_mr else
                            ["prescribed electric field; no collisions or self consistency",
                             "native PA domain composition is not a monolithic joint electrostatic solve",
                             "native qualification requires a recorded actual run"])}


def _trace_cache_key(*, field_key, particles, propagation, observations, numerics, recipe, implementation, tracking_execution=None):
    """Bind trajectory reuse to actual cohort, observation and gas authorities."""
    scientific_observations = copy.deepcopy(observations)
    focus = scientific_observations.get("oa_focus_authority")
    if isinstance(focus, dict):
        for name in ("campaign", "component_contract"):
            if isinstance(focus.get(name), dict):
                focus[name].pop("path", None)
    identity = {"stage": "trace", "field": field_key, "particles": particles,
        "propagation": propagation, "observations": scientific_observations,
        "gas_environment": recipe["gas_environment"], "gas_data": recipe["gas_data"],
        "gas_resources": {name: value["sha256"] for name, value in recipe["resource_snapshots"].items()
                          if name.startswith("hs1_")},
        "numerics": numerics, "implementation": implementation}
    if tracking_execution is not None:
        execution_key = {}
        if tracking_execution.get("unit_size") is not None:
            execution_key["unit_size"] = tracking_execution["unit_size"]
        predecessor = tracking_execution.get("recovery_reference")
        if predecessor is not None:
            execution_key["recovery_reference"] = {"bytes": predecessor["bytes"], "sha256": predecessor["sha256"].upper()}
        if execution_key:
            identity["tracking_execution"] = execution_key
    return canonical_json_sha256(identity)


def _complete_trajectory(artifact, *, detector_required=True) -> bool:
    if artifact.kind != "trajectory_result":
        return True
    data = read_particle_data(artifact.data_path("particle_data_execution_json").parent)
    return (data["execution_status"] == "succeeded" and data["data_integrity"].get("status") == "complete"
            and bool(data["metadata"].get("species"))
            and data["data_integrity"].get("detector_observation", {}).get("status") in
                ({"complete"} if detector_required else {"complete", "not_requested"}))


def _native_owner_evidence(store, artifact):
    """Report only the owner identity already authenticated by the source guard."""
    manifest = copy.deepcopy(artifact.reference['manifest'])
    path = Path(manifest['path']).resolve()
    native_assets = (store.root / 'assets' / 'native_stage').resolve()
    if path.is_relative_to(native_assets):
        parts = path.relative_to(store.root).parts
        if len(parts) < 6 or parts[:2] != ('assets', 'native_stage'):
            raise ValueError('native Store manifest path differs from its asset identity')
        return {'kind': 'artifact_store_native_stage', 'asset_id': parts[3], 'manifest': manifest}
    return {'kind': 'protected_external_native_source', 'manifest': manifest}


def _native_reference(store, stack, key, produce, *, kind, raw_root, claims, calls, account, detector_required=True):
    """Verify a tiny cached reference against its real owner before reuse."""
    cached = stack.enter_context(store.claim_key(key))
    from msplatform.execution.native_source_guard import guard_native_source
    if cached is not None:
        asset_id, path = cached
        try:
            reference = json.loads((path / "reference.json").read_text(encoding="utf-8"))
            artifact = stack.enter_context(guard_native_source(reference, expected_kind=kind,
                                                               expected_artifact_root=raw_root, artifact_store=store))
            if not _complete_trajectory(artifact, detector_required=detector_required):
                artifact = None
        except (ValueError, OSError, KeyError):
            artifact = None
        if artifact is not None:
            token, _ = stack.enter_context(store.claim_token(asset_id))
            claims.append(token)
            return artifact, {"asset_id": asset_id, "task_key": key, "reused": True,
                              "producer_owner": _native_owner_evidence(store, artifact)}
    calls.append(key)
    from msplatform.execution.owner import managed_native_store
    with managed_native_store(store, task_key=key, lifetime=stack, account=account):
        artifact = produce()
    artifact = stack.enter_context(guard_native_source(artifact.reference, expected_kind=kind,
                                                       expected_artifact_root=raw_root, artifact_store=store))
    if not _complete_trajectory(artifact, detector_required=detector_required):
        return artifact, {"asset_id": None, "task_key": key, "reused": False,
                          "producer_owner": _native_owner_evidence(store, artifact),
                          "cache_status": "ineligible_incomplete_or_failed"}
    work = store.new_work()
    _write(work / "reference.json", artifact.reference)
    account(work)
    asset_id, _ = stack.enter_context(store.put_asset_claimed("native_reference", key, work, retention="cache"))
    token, _ = stack.enter_context(store.claim_token(asset_id))
    claims.append(token)
    return artifact, {"asset_id": asset_id, "task_key": key, "reused": False,
                      "producer_owner": _native_owner_evidence(store, artifact)}


def run_loaded_recipe(loaded: SimulationRecipe, *, context, artifact_root,
                      high_water_bytes=None, low_water_bytes=None, safety_bytes=0,
                      reserve_bytes=0, source_revision=None, cancelled=None, tracking_execution=None) -> dict:
    """Run one already-read author input through native owners without rereading it."""
    if context is None:
        raise ValueError("native execution requires an explicit ExecutionContext")
    if cancelled is not None:
        raise ValueError("native callback cancellation is not implemented; managed owner cancellation applies")
    recipe = loaded.to_dict()
    if tracking_execution is not None:
        if (not isinstance(tracking_execution, dict)
                or set(tracking_execution) - {"unit_size", "recovery_reference", "dispatch_profiles"}):
            raise ValueError("tracking_execution permits only unit_size, recovery_reference and dispatch_profiles")
        tracking_execution = copy.deepcopy(tracking_execution)
        unit_size = tracking_execution.get("unit_size")
        if unit_size is not None and (type(unit_size) is not int or unit_size <= 0):
            raise ValueError("tracking execution unit_size must be a positive integer")
        profiles = tracking_execution.get("dispatch_profiles", [])
        if not isinstance(profiles, list) or any(not isinstance(row, dict) for row in profiles):
            raise ValueError("tracking execution dispatch_profiles must be an explicit list of objects")
        recovery = tracking_execution.get("recovery_reference")
        if recovery is not None:
            if (not isinstance(recovery, dict) or not isinstance(recovery.get("path"), str)
                    or not Path(recovery["path"]).is_absolute() or type(recovery.get("bytes")) is not int
                    or recovery["bytes"] < 0 or not isinstance(recovery.get("sha256"), str)
                    or len(recovery["sha256"]) != 64
                    or any(c not in "0123456789abcdefABCDEF" for c in recovery["sha256"])):
                raise ValueError("tracking execution recovery requires an absolute manifest file record")
        if (recipe["particle_tracer"] != "simion" or recipe["field_source"]["kind"] != "simion_native"
                or recipe["gas_environment"]["status"] == "sds"
                or recipe["study"]["document"]["release"].get("role") == "canonical_mass_scan_request"
                or recipe["study"]["document"]["drive"].get("pulse", {}).get("mode") == "discover"
                or "oa_focus_campaign" in recipe["study"]["document"]["model_input_sources"]
                or "field_intervention" in recipe["recording"] or "field_interventions" in recipe["recording"]):
            raise ValueError("tracking execution controls require one non-discovery SIMION native cohort")
    if source_revision is not None:
        import re
        if not re.fullmatch(r"[0-9a-fA-F]{40}", source_revision):
            raise ValueError("source_revision must be an explicit full repository SHA")
    if type(reserve_bytes) is not int or reserve_bytes <= 0:
        raise ValueError("native scientific outputs require an explicit positive reserve_bytes budget")
    store = ArtifactStore(artifact_root, high_water_bytes=high_water_bytes,
                          low_water_bytes=low_water_bytes, safety_bytes=safety_bytes)
    # The raw native owner and this Store must never govern the same payload.
    raw_root = (context.workspace / "artifacts").resolve()
    if store.root == raw_root or raw_root in store.root.parents or store.root in raw_root.parents:
        raise ValueError("native ArtifactStore and existing native owner roots must be disjoint")
    report = preflight_native(recipe, context=context, artifact_store=store)
    if not report["host_available"]:
        raise ValueError("selected native execution tools are unavailable")
    run_id, work = store.begin_run()
    (work / "author.toml").write_bytes(loaded.source_bytes)
    if tracking_execution is not None:
        _write(work / "tracking_execution.json", tracking_execution)
    _write(work / "resolved.json", recipe)
    _write(work / "preflight.json", report)
    with store.run_writer(run_id):
        try:
            with store.reserve(reserve_bytes) as reservation:
                store.mark_running(run_id)
                _execute(store, recipe, context, run_id, work, reservation, source_revision, reserve_bytes,
                         **({"tracking_execution": tracking_execution} if tracking_execution is not None else {}))
        except BaseException as error:
            status = store.run_status(run_id)["execution_status"]
            if status == "queued":
                store.set_queued_reason(run_id, str(error))
            elif status == "running":
                store.finish_run(run_id, "cancelled" if isinstance(error, KeyboardInterrupt) else "failed", reason=str(error))
            raise
    from .tracing import inspect_results
    return {"run_id": run_id, "artifact_root": str(store.root), **inspect_results(run_id, artifact_root=store.root)}


from msplatform.execution.owner import store_growth_accountant as _growth_accountant


def _execute_sds(store, recipe, context, run_id, work, reservation, source_revision, budget):
    """Publish one original-birth SDS run through the existing managed stage owners."""
    from msplatform.backends import simion
    from msplatform.execution.native_artifact_controls import protect_native_controls
    from msplatform.execution.native_source_guard import guard_native_source
    from .native_evidence import summarize_native_workers

    account = _growth_accountant(store, reservation, budget, work)
    inputs = _materialize_sds_inputs(recipe, work / "sds_inputs")
    resources = work / "frozen_resources"
    resources.mkdir()
    for name in ("instrument_clock_authority_v1.json", "instrument_epoch_v1.json"):
        (resources / name).write_bytes(base64.b64decode(recipe["resource_snapshots"][name]["bytes_base64"], validate=True))
    clock_reference = {"contract": file_record(resources / "instrument_clock_authority_v1.json", "required_evidence"),
                       "authority": file_record(resources / "instrument_epoch_v1.json", "required_evidence"),
                       "data_root": str(resources)}
    instrument = _assembly(recipe)
    account(work)
    package = Path(__file__).parents[1]
    backend = Path(simion.__file__).parent
    implementation = {"workflow": file_sha256(__file__),
        "shared_sources": canonical_json_sha256({path.relative_to(package).as_posix(): file_sha256(path)
            for directory in ("assembly", "components", "contracts", "physics", "results", "particle_release", "fields", "io")
            for path in sorted((package / directory).rglob("*.py")) if path.is_file()}),
        "backend_sources": canonical_json_sha256({path.relative_to(backend).as_posix(): file_sha256(path)
            for path in sorted(backend.rglob("*")) if path.is_file() and path.suffix in
                {".py", ".m", ".lua", ".gem", ".json", ".ps1", ".iob", ".pa0", ".fly2"}}),
        "native_executable": _executable_records({"simion": context.tools["simion"]})}
    claims, calls = [], []
    with ExitStack() as stack:
        source_assets = set()
        gas = stack.enter_context(guard_native_source(inputs["gas_field_reference"], expected_kind="gas_field",
            expected_artifact_root=context.workspace / "artifacts", artifact_store=store, asset_ids=source_assets))
        frozen = store.new_work()
        _write(frozen / "input.json", recipe)
        account(frozen)
        input_id, _ = stack.enter_context(store.put_asset_claimed("native_input", recipe["recipe_id"], frozen, retention="cache"))
        token, _ = stack.enter_context(store.claim_token(input_id))
        claims.append(token)
        def invoke(action):
            with protect_native_controls(store, run_id=run_id, claim_ids=tuple(claims),
                                         reservation_ids=(reservation,), work_directory=work):
                return action()
        trajectory, receipts = _run_sds_stages(recipe, instrument, inputs, gas, store=store, stack=stack,
            context=context, claims=claims, calls=calls, account=account, invoke=invoke,
            implementation=implementation, clock_authority_reference=clock_reference)
        data = read_particle_data(trajectory.data_path("particle_data_execution_json").parent)
        plan = compile_sds_inputs(recipe, instrument)
        expected_clock = {"basis": "experiment_relative", "unit": "s", **recipe["study"]["document"]["release"]["clock"]}
        if (data["metadata"]["frame_id"] != plan["source_frame_id"] or data["metadata"]["clock"] != expected_clock
                or data["metadata"].get("species") != recipe["species"]
                or len(data["initial_states"]) != plan["source"]["particle_count"]):
            raise ValueError("SDS trajectory differs from the frozen source, species, frame or clock")
        result = TraceResult(**{key: data[key] for key in ("initial_states", "terminal_states", "events", "trajectories",
                                                            "execution_status", "data_integrity")})
        write_particle_data(work, result, metadata={"schema_version": 2, **data["metadata"]})
        reread = read_particle_data(work)
        _write(work / "summary.json", summarize_particle_data(reread))
        _write(work / "native_stages.json", receipts)
        evidence = summarize_native_workers(work)
        for control in evidence["controls"]:
            for record in control["records"].values():
                record["path"] = Path(record["path"]).relative_to(work).as_posix()
        _write(work / "native_worker_evidence.json", evidence)
        _write(work / "provenance.json", {"schema_version": 1, "execution_owner": "native_tracing",
            "author_sha256": file_sha256(work / "author.toml"), "recipe_id": recipe["recipe_id"],
            "repository_source": {"sha": source_revision, "status": "declared" if source_revision else "unavailable"},
            "stages": receipts, "stage_productions": calls, "raw_asset_owner": "see_stage_producer_owner",
            "gas_source": _native_owner_evidence(store, gas), "implementation": implementation})
        account(work)
        store.publish_run(work, run_id=run_id, execution_status=reread["execution_status"],
                          required_assets=tuple(sorted(source_assets)),
                          provenance_assets=[input_id, *(row["asset_id"] for row in receipts.values() if row["asset_id"])])


def _execute(store, recipe, context, run_id, work, reservation, source_revision, budget, *, tracking_execution=None):
    if recipe["gas_environment"]["status"] == "sds":
        return _execute_sds(store, recipe, context, run_id, work, reservation, source_revision, budget)
    account = _growth_accountant(store, reservation, budget, work)
    from msplatform.backends import simion
    from msplatform.execution.native_artifact_controls import protect_native_controls
    study = recipe["study"]["document"]
    instrument = _assembly(recipe)
    resources = work / "frozen_resources"
    resources.mkdir()
    for name, snapshot in recipe["resource_snapshots"].items():
        if name == "sds":
            continue  # The nested SDS closure is materialized by its authenticated adapter.
        (resources / name).write_bytes(base64.b64decode(snapshot["bytes_base64"]))
    account(work)
    from msplatform.contracts.pulse import field_reference_drive
    drive = field_reference_drive(study["drive"])
    drive["clock_authority"] = {"contract": file_record(resources / "instrument_clock_authority_v1.json"),
                                 "data_root": str(resources)}
    comsol = recipe["field_source"]["kind"] == "comsol_native"
    scalar = comsol and recipe["particle_tracer"] == "simion"
    if comsol:
        from msplatform.backends import comsol as backend_module
        compiled = None
        tool_paths = {"comsol": context.tools["comsol"], "matlab": context.tools["matlab_root"] / "bin/matlab.exe",
                      "launcher": context.tools["comsol_launcher"]}
    else:
        backend_module = simion
        compiled = simion.compile_geometry(instrument, numerics=study["numerics"]["geometry"])
        tool_paths = {"simion": context.tools["simion"]}
    package = Path(__file__).parents[1]
    shared_sources = canonical_json_sha256({path.relative_to(package).as_posix(): file_sha256(path)
        for directory in ("assembly", "components", "contracts", "physics", "results", "particle_release", "fields", "io")
        for path in sorted((package / directory).rglob("*.py")) if path.is_file()})
    def identity(module, paths):
        backend = Path(module.__file__).parent
        return {
        "shared_sources": shared_sources,
        "backend_sources": canonical_json_sha256({path.relative_to(backend).as_posix(): file_sha256(path)
            for path in sorted(backend.rglob("*")) if path.is_file() and path.suffix in {
                ".py", ".m", ".lua", ".gem", ".json", ".ps1", ".iob", ".pa0", ".fly2"}}),
        "native_executable": _executable_records(paths)}
    backend_identity = identity(backend_module, tool_paths)
    implementation = {"workflow": file_sha256(__file__), **backend_identity}
    if scalar:
        # COMSOL export/support also consume SIMION scalar-payload code; both
        # owners must change identity when that shared implementation changes.
        simion_identity = identity(simion, {"simion": context.tools["simion"]})
        backend_identity["scalar_payload_sources"] = simion_identity["backend_sources"]
        bridge_source = file_sha256(Path(__file__).with_name("scalar_tracing.py"))
        backend_identity["bridge_source"] = bridge_source
        simion_identity["bridge_source"] = bridge_source
        implementation = {"workflow": file_sha256(__file__),
                          "comsol": backend_identity,
                          "simion": simion_identity}
    calls, receipts, control_ids = [], {}, []
    with ExitStack() as stack:
        compensation = None
        required_assets = []
        recovery = None if tracking_execution is None else tracking_execution.get("recovery_reference")
        if recovery is not None:
            recovery_assets = set()
            from msplatform.execution.native_source_guard import guard_tracking_recovery
            stack.enter_context(guard_tracking_recovery(store, recovery,
                raw_root=context.workspace / "artifacts", asset_ids=recovery_assets))
            required_assets.extend(sorted(recovery_assets))
        if "compensation_provenance.json" in recipe["resource_snapshots"]:
            compensation = _guard_compensation_sources(recipe, stack=stack, context=context, artifact_store=store,
                                                        compensated_model=compile_simion_model(recipe))
            required_assets.extend(compensation["source_asset_ids"])
        snapshot = store.new_work()
        _write(snapshot / "input.json", recipe)
        account(snapshot)
        input_id, _ = stack.enter_context(store.put_asset_claimed("native_input", recipe["recipe_id"], snapshot, retention="cache"))
        token, _ = stack.enter_context(store.claim_token(input_id))
        control_ids.append(token)
        focus_authority = None
        if "oa_focus_campaign.json" in recipe["resource_snapshots"]:
            focus_key = canonical_json_sha256({name: recipe["resource_snapshots"][name]["sha256"]
                                             for name in ("oa_focus_campaign.json", "oa_focus_component_contract.json")})
            cached_focus = stack.enter_context(store.claim_key(focus_key))
            if cached_focus is not None:
                try:
                    if any(file_sha256(cached_focus[1] / name).upper() != recipe["resource_snapshots"][name]["sha256"].upper()
                           for name in ("oa_focus_campaign.json", "oa_focus_component_contract.json")):
                        cached_focus = None
                except OSError:
                    cached_focus = None
            if cached_focus is None:
                focus_work = store.new_work()
                for name in ("oa_focus_campaign.json", "oa_focus_component_contract.json"):
                    (focus_work / name).write_bytes(base64.b64decode(recipe["resource_snapshots"][name]["bytes_base64"], validate=True))
                account(focus_work)
                focus_id, focus_path = stack.enter_context(store.put_asset_claimed("native_input", focus_key, focus_work, retention="cache"))
            else:
                focus_id, focus_path = cached_focus
            focus_token, _ = stack.enter_context(store.claim_token(focus_id))
            control_ids.append(focus_token)
            required_assets.append(focus_id)
            focus_compiled_model = compile_simion_model(recipe)
            focus_authority = _guarded_focus_authority(recipe, focus_compiled_model,
                                                        resource_root=focus_path, stack=stack)
            _write(work / "oa_focus_authority.json", focus_authority)
            _write(work / "oa_focus_model.json", focus_compiled_model.document)
            for name in ("oa_focus_campaign.json", "oa_focus_component_contract.json"):
                (work / name).write_bytes(base64.b64decode(recipe["resource_snapshots"][name]["bytes_base64"], validate=True))
            account(work)

        def invoke(action):
            with protect_native_controls(store, run_id=run_id, claim_ids=tuple(control_ids),
                                         reservation_ids=(reservation,), work_directory=work):
                return action()

        field_implementation = {key: value for key, value in implementation.items() if key != "workflow"}
        if not comsol and 'reference' in recipe['field_source']:
            from msplatform.execution.native_source_guard import guard_native_source
            recipe, frozen = _validated_simion_field_reference(recipe)
            field = stack.enter_context(guard_native_source(frozen['reference'], expected_kind='field_bundle',
                                                           expected_artifact_root=context.workspace/'artifacts', artifact_store=store))
            requested_model = compile_simion_model(recipe)
            field = _admit_simion_field_reference(recipe, expected_model=requested_model,
                                                 field_numerics=study['numerics']['fields'], artifact=field)
            field_key = canonical_json_sha256(dict(stage='explicit_simion_field_reference',
                manifest_sha256=frozen['snapshot']['sha256'], product_id=frozen['reference']['product_id'],
                model_identity_sha256=requested_model.document['model_identity_sha256'], field_numerics=study['numerics']['fields']))
            receipts['field'] = dict(asset_id=None, task_key=field_key, reused=True, reuse_scope='explicit_field_reference',
                                     reference=field.reference, producer=field.producer, producer_owner=_native_owner_evidence(store, field))
            _write(work / 'native_stages.json', receipts)
            account(work)
        elif not comsol:
            geometry_key = canonical_json_sha256({"stage": "geometry", "compiled": compiled.__dict__, "implementation": field_implementation})
            geometry, receipts["geometry"] = _native_reference(store, stack, geometry_key,
                lambda: invoke(lambda: simion.build_geometry(compiled, context=context)), kind="geometry_artifact", raw_root=context.workspace / "artifacts", claims=control_ids, calls=calls, account=account)
            _write(work / "native_stages.json", receipts)
            account(work)
            model_key = canonical_json_sha256({"stage": "model", "geometry": geometry_key, "drive": study["drive"],
                "clock_resources": {name: recipe["resource_snapshots"][name]["sha256"] for name in ("instrument_clock_authority_v1.json", "instrument_epoch_v1.json")},
                "physics": study["physics"], "implementation": field_implementation})
            model, receipts["model"] = _native_reference(store, stack, model_key,
                lambda: invoke(lambda: simion.prepare_model(geometry, drive=drive, physics=study["physics"], context=context)), kind="prepared_model", raw_root=context.workspace / "artifacts", claims=control_ids, calls=calls, account=account)
            _write(work / "native_stages.json", receipts)
            account(work)
            field_identity = {"stage": "field", "model": model_key, "numerics": study["numerics"]["fields"], "implementation": field_implementation}
            if compensation is not None:
                field_identity["compensation_provenance_sha256"] = recipe["resource_snapshots"]["compensation_provenance.json"]["sha256"]
            field_key = canonical_json_sha256(field_identity)
            basis = (None if compensation is None else dict(reference=compensation["declared"]["original_field_reference"],
                     fit=compensation["declared"]["fit"], regularization=compensation["declared"]["fit"]["fit"]["regularization"]))
            field, receipts["field"] = _native_reference(store, stack, field_key,
                lambda: invoke(lambda: simion.solve_fields(model, numerics=study["numerics"]["fields"], context=context,
                    **({"compensated_basis": basis} if basis is not None else {}))), kind="field_bundle", raw_root=context.workspace / "artifacts", claims=control_ids, calls=calls, account=account)
            _write(work / "native_stages.json", receipts)
            account(work)
        if (not comsol and compiled.frontend_geometry.get('role') not in {'simion_ip_mr_complete_geometry', 'simion_neutral_world_collision_geometry', 'simion_rf_ip_geometry', 'simion_independent_oa_geometry'}
                and field.metadata.get('ground_representation') != 'analytic_zero_on_native_geometry'):
            from msplatform.backends.simion import grounded_runtime, native_plans
            from msplatform.backends.simion.resources import native_resource_path
            source_field = field
            runtime_key = canonical_json_sha256({
                'stage': 'standalone_ground_carriers', 'field': field_key,
                'owner': file_sha256(grounded_runtime.__file__), 'plan': file_sha256(native_plans.__file__),
                'converter': file_sha256(native_resource_path('raw_collision_pa.lua')),
                'native_executable': backend_identity['native_executable']})
            field, receipts['runtime_field'] = _native_reference(store, stack, runtime_key,
                lambda: invoke(lambda: grounded_runtime.prepare_grounded_runtime_fields(source_field, context=context)),
                kind='field_bundle', raw_root=context.workspace/'artifacts', claims=control_ids, calls=calls, account=account)
            field_key = runtime_key
            _write(work / 'native_stages.json', receipts)
            account(work)
        cohort = _realizations(study["release"], resource_root=resources)
        if focus_authority is not None:
            if len(cohort) != 1:
                raise ValueError("OA focus requires one original-birth realization")
            from msplatform.backends.simion.tracking_execution import _birth_states
            focus_model = focus_compiled_model.document
            focus_geometry = dict(focus_model["geometry"]["frontend_geometry"],
                                  native_frame_id=focus_model["native_frame_id"])
            packet = _particle_document(cohort[0])
            projected, _, _ = _birth_states(packet, focus_geometry)
            _write(work / "oa_focus_source_packet.json", packet)
            _write(work / "oa_focus_projected_birth_rows.json", projected)
            account(work)
        focus_modes = recipe["recording"].get("oa_focus_field_modes")
        collection_cases = recipe["recording"].get("field_interventions")
        if focus_modes is not None:
            collection_cases = [{"id": mode, "selector": mode} for mode in focus_modes]
        cases = collection_cases if collection_cases is not None else [None]
        stage_memo = {}
        collection = []
        case_statuses = []
        for case_index, case in enumerate(cases):
            case_recipe = copy.deepcopy(recipe)
            case_recipe["recording"].pop("field_interventions", None)
            case_recipe["recording"].pop("oa_focus_field_modes", None)
            if case is not None:
                if focus_modes is not None:
                    case_recipe["recording"]["oa_focus_field_mode"] = case["selector"]
                else:
                    case_recipe["recording"]["field_intervention"] = case
            case_prefix = "" if case is None else "case_" + case["id"] + "_"
            case_path = work if collection_cases is None else work / "cases" / f"{case_index:04d}"
            case_path.mkdir(parents=True, exist_ok=True)
            from .mass_scan import merge_mass_scan, analyze_mass_scan
            batches, common = [], None
            for ordinal, particles in enumerate(cohort):
                if comsol:
                    if scalar:
                        from .scalar_tracing import run_scalar_stages as run_stages
                    else:
                        from .comsol_tracing import run_comsol_stages as run_stages
                    def stage_cache(name, key, kind, produce):
                        cache_id = (key, kind)
                        if cache_id in stage_memo:
                            artifact, receipt = stage_memo[cache_id]
                            receipt = {**receipt, "reused": True, "reuse_scope": "current_run"}
                            receipts[f"{case_prefix}batch_{ordinal}_{name}"] = receipt
                            _write(work / "native_stages.json", receipts)
                            account(work)
                            return artifact, receipt
                        result = _native_reference(store, stack, key, produce, kind=kind,
                            raw_root=context.workspace / "artifacts", claims=control_ids, calls=calls, account=account)
                        stage_memo[cache_id] = result
                        receipts[f"{case_prefix}batch_{ordinal}_{name}"] = result[1]
                        _write(work / "native_stages.json", receipts)
                        account(work)
                        return result
                    trajectory, batch_receipts = run_stages(case_recipe, instrument, particles, context=context,
                        invoke=invoke, stage_cache=stage_cache, implementation=field_implementation,
                        epoch_record=file_record(resources / "instrument_epoch_v1.json"),
                        **({"resource_root": resources} if scalar else {}))
                    receipts.update({f"{case_prefix}batch_{ordinal}_{name}": receipt for name, receipt in batch_receipts.items()})
                else:
                    propagation, observations = _flight_request(case_recipe, instrument, particles, focus_authority=focus_authority)
                    hs1 = _hs1_request(recipe, resources)
                    author_pulse = study["drive"].get("pulse", {})
                    if author_pulse.get("mode") == "discover":
                        pilot_observations = copy.deepcopy(observations)
                        pilot_observations["observation_times_us"] = copy.deepcopy(author_pulse["candidate_times_us"])
                        pilot_observations["pulse_discovery"] = {"phase": "discovery", "author": copy.deepcopy(author_pulse)}
                        pilot_key = _trace_cache_key(field_key=field_key,
                            particles=(study["release"] if isinstance(particles, dict) else particles.to_dict()),
                            propagation=propagation, observations=pilot_observations, numerics=study["numerics"]["tracing"]["simion"],
                            recipe=case_recipe, implementation=implementation)
                        pilot, receipts[case_prefix + "discovery_" + str(ordinal)] = _native_reference(store, stack, pilot_key,
                            lambda: invoke(lambda: simion.track(field, particles, propagation=propagation,
                                observations=pilot_observations, numerics=study["numerics"]["tracing"]["simion"], context=context)),
                            kind="trajectory_result", raw_root=context.workspace / "artifacts", claims=control_ids, calls=calls, account=account)
                        pilot_receipt = receipts[case_prefix + "discovery_" + str(ordinal)]
                        owner = pilot_receipt.get("producer_owner", {})
                        if owner.get("kind") == "artifact_store_native_stage":
                            required_assets.append(owner["asset_id"])
                        discovery_dir = work / "discovery" / f"{case_index:04d}" / f"{ordinal:04d}"
                        discovery_dir.mkdir(parents=True, exist_ok=True)
                        for key in ("collection", "observations", "source_provenance", "compiled_model"):
                            (discovery_dir / (key + ".json")).write_bytes(pilot.data_path(key).read_bytes())
                        (discovery_dir / "pilot_manifest.json").write_bytes(Path(pilot.reference["manifest"]["path"]).read_bytes())
                        _write(discovery_dir / "pilot_reference.json", pilot.reference)
                        account(work)
                        observations["pulse_discovery"] = {"phase": "selected", "author": copy.deepcopy(author_pulse),
                                                           "pilot": copy.deepcopy(pilot.reference)}
                    trace_key = _trace_cache_key(field_key=field_key,
                        particles=(study["release"] if isinstance(particles, dict) else particles.to_dict()),
                        propagation=propagation, observations=observations, numerics=study["numerics"]["tracing"]["simion"],
                        recipe=case_recipe, implementation=implementation, tracking_execution=tracking_execution)
                    trajectory, receipts[case_prefix + "trace_" + str(ordinal)] = _native_reference(store, stack, trace_key,
                        lambda: invoke(lambda: simion.track(field, particles, propagation=propagation, observations=observations,
                            numerics=study["numerics"]["tracing"]["simion"], context=context,
                            **({"hs1_request": hs1} if hs1 is not None else {}),
                            **(tracking_execution or {}))), kind="trajectory_result",
                        raw_root=context.workspace / "artifacts", claims=control_ids, calls=calls, account=account,
                        **({"detector_required": False} if not observations["plane_observations"] else {}))
                if not comsol and study["drive"].get("pulse", {}).get("mode") == "discover":
                    selected_collection = json.loads(trajectory.data_path("collection").read_text(encoding="utf-8-sig"))
                    resolution = selected_collection.get("discovery_resolution")
                    if not isinstance(resolution, dict) or resolution.get("decision", {}).get("status") != "success":
                        raise ValueError("selected flight lacks its authenticated discovery decision")
                    _write(discovery_dir / "selection.json", resolution)
                    account(work)
                if comsol and not scalar:
                    detector_directory = (case_path if len(cohort) == 1 else
                                          case_path / "detector_contracts" / f"{ordinal:04d}")
                    _archive_comsol_detector_contract(trajectory, detector_directory)
                    account(work)
                data = read_particle_data(trajectory.data_path("particle_data_execution_json").parent)
                if scalar:
                    from msplatform.backends.simion.model import require_prepared_model
                    from msplatform.backends.simion.artifacts import CompiledPreparedModel
                    from .scalar_tracing import compile_scalar_inputs
                    collision = compile_scalar_inputs(recipe)["collision"]
                    collision_model = CompiledPreparedModel(collision.data_path("compiled_model").read_text(encoding="utf-8-sig"))
                    expected_frame = require_prepared_model(collision_model)["geometry"]["frontend_geometry"]["native_frame_id"]
                else:
                    geometry = None if comsol else compiled.frontend_geometry
                    expected_frame = (study["recipe"]["assembly_frame_id"] if comsol else
                        geometry["domain"]["frame_id"] if geometry.get("role") == "simion_neutral_world_collision_geometry"
                        else json.loads(field.data_path("compiled_model").read_text(encoding="utf-8-sig"))["native_frame_id"]
                        if geometry.get("role") in {"simion_rf_ip_geometry", "simion_independent_oa_geometry"} else geometry["native_frame_id"])
                if data["metadata"]["frame_id"] != expected_frame:
                    raise ValueError("native batch result has a different frame")
                expected_clock = {"basis": "experiment_relative", "unit": "s", **_particle_document(particles)["clock"]}
                if data["metadata"]["clock"] != expected_clock:
                    raise ValueError("native batch result has a different experiment clock")
                expected_species_ids = {row["species_id"] for row in data["initial_states"]}
                expected_species = [row for row in recipe["species"] if row["species_id"] in expected_species_ids]
                if data["metadata"].get("species") != expected_species:
                    raise ValueError("native batch species differ from the frozen source registry")
                batch_basis = {key: data["metadata"][key] for key in ("frame_id", "clock", "initial_state_basis")}
                if common is not None and common != batch_basis:
                    raise ValueError("native species batches disagree on frame, clock or lineage basis")
                common = batch_basis
                batches.append(data)
                _write(work / "native_stages.json", receipts)
                account(work)
            results = [TraceResult(**{key: batch[key] for key in ("initial_states", "terminal_states", "events", "trajectories", "execution_status", "data_integrity")})
                       for batch in batches]
            if all(result.execution_status == "succeeded" and result.data_integrity.get("status") == "complete" for result in results):
                merged = merge_mass_scan(results)
            else:
                from msplatform.results.model import merge_trace_batches
                merged = merge_trace_batches(batches)
            write_particle_data(case_path, merged, metadata={"schema_version": 2, **common, "species": recipe["species"]})
            data = read_particle_data(case_path)
            if data["execution_status"] == "succeeded" and data["data_integrity"].get("status") == "complete":
                _write(case_path / "analysis.json", analyze_mass_scan(data))
            else:
                _write(case_path / "analysis.json", {"status": "not_applicable", "reason": "incomplete_or_failed_tracking"})
            summary = summarize_particle_data(data)
            _write(case_path / "summary.json", summary)
            case_statuses.append(data["execution_status"])
            if case is not None:
                collection.append({"id": case["id"], "selector": case["selector"],
                                   "path": f"cases/{case_index:04d}", "summary": summary})
        if collection_cases is not None:
            _write(work / "collection.json", {"schema_version": 1, "role": ("oa_focus_field_contrast_collection" if focus_modes is not None
                             else "field_intervention_collection"),
                    "cases": collection})
        execution_status = ("succeeded" if all(value == "succeeded" for value in case_statuses)
                            else "cancelled" if "cancelled" in case_statuses else "failed")
        from .native_evidence import summarize_native_workers
        worker_evidence = summarize_native_workers(work)
        # Publication moves this work tree. Keep its sealed evidence locations
        # relative to the published run, rather than pointing at vanished work.
        for control in worker_evidence["controls"]:
            for record in control["records"].values():
                record["path"] = Path(record["path"]).relative_to(work).as_posix()
        _write(work / "native_worker_evidence.json", worker_evidence)
        _write(work / "provenance.json", {"schema_version": 1, "execution_owner": "native_tracing",
            "author_sha256": file_sha256(work / "author.toml"), "recipe_id": recipe["recipe_id"],
            "repository_source": {"sha": source_revision, "status": "declared" if source_revision else "unavailable"},
            "stages": receipts, "stage_productions": calls,
            "raw_asset_owner": "see_stage_producer_owner", "implementation": implementation,
            **({"compensation_sources": {key: compensation[key] for key in ("axis_owner", "field_owner")}}
               if compensation is not None else {})})
        account(work)
        store.publish_run(work, run_id=run_id, execution_status=execution_status,
                          required_assets=tuple(required_assets), provenance_assets=[input_id, *(receipt["asset_id"] for receipt in receipts.values() if receipt["asset_id"])])
