"""Freeze original births and an explicitly designed cooled-to-OA assembly."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.artifact_naming import validate_run_id
from common.contracts.machine_contracts import validate_schema
from common.integration.resolve_assembly import derive_assembly_scope
from projects.orthogonal_accelerator.analysis.assembly_interface import resolve_assembly_interface
from common.contracts.rigid_transform import RigidTransform
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record, require_completed_terminal_publication
from integrations.runtime.single_flight_source import GLOBAL_COLUMNS, transform_source_rows
from integrations.workflows.local_frontend.prepare import (
    SOURCE_CLOCK, SOURCE_NAMES, _csv_text, _keys, _load, _number, _registration, _source_inputs, _producer_clock,
)
from integrations.workflows.cooled_frontend.geometry import (
    CONDITIONER_ELECTRODE_IDS, compile_cooled_frontend, compile_field_plan,
)
from projects.dual_pressure_rectilinear_ion_processor.analysis.cooled_buncher import build_cooled_buncher_contract, prepare_buncher_probe_points, export_cooled_buncher_assembly_interface
from projects.dual_pressure_rectilinear_ion_processor.analysis.guide_interface import export_guide_contract
from common.simion.collision_hs1 import adapt_hs1_for_repeat_fly


ROLE = "instrument_assembly_cooled_frontend_request"
_NUMERICS = {"cell_mm_xyz", "refine_convergence_v", "maximum_step_us", "rf_steps_per_period",
             "maximum_flight_us", "trajectory_sample_interval_us", "extraction_sample_interval_us",
             "trajectory_quality", "collision_seed", "hs1_steps_per_mfp"}


def _decision_producer(path: Path, workspace: Path, identity: dict) -> dict:
    """Project the explicitly referenced decision onto its typed artifact owner."""
    artifact_root=workspace/"artifacts"
    relative=path.relative_to(artifact_root)
    integration_id="instrument_assembly"
    parts=relative.parts
    if len(parts)<5 or parts[0] != "projects" or parts[1]!=integration_id or parts[2]!="runs":
        raise ValueError("common pulse decision must belong to an explicit integration artifact run")
    owner=artifact_root.joinpath(*parts[:4])
    manifest_path=owner/"run_manifest.json"
    require_completed_terminal_publication(manifest_path)
    manifest=_load(manifest_path)
    if manifest.get("status")!="success" or manifest.get("role")!="simulation_run_manifest":
        raise ValueError("production common pulse decision requires a successful sealed producer")
    matches=[r for r in [*manifest.get("inputs",{}).values(),*manifest.get("outputs",[])] if record_path(r,base_dir=owner)==path]
    if not matches:
        raise ValueError("production common pulse decision is not bound by its producer manifest")
    for record in matches:
        if record.get("bytes") != identity["bytes"] or record.get("sha256", "").upper() != identity["sha256"].upper():
            raise ValueError("common pulse decision producer binding differs")
    return dict(schema_version=1,role="cooled_frontend_common_pulse_producer",producer_manifest=file_record(manifest_path),original_decision=dict(identity, path=str(path)))


def validate_request(request: dict) -> None:
    """Validate authored physics/numerics before source I/O or output writes."""
    required = {"schema_version", "role", "source", "accelerator_component", "composition_plan", "numerics", "conditioner", "drive", "pressure_scale", "pulse", "diagnostics",
                "field_source", "common_pulse_decision", "design_targets"}
    if not required <= set(request) or set(request) - required - {"local_scope", "verify_saved_workbench_replay"}:
        raise ValueError("cooled request fields differ from the current contract")
    if type(request["schema_version"]) is not int or request["schema_version"] != 3 or request["role"] != ROLE:
        raise ValueError("unsupported cooled frontend request")
    if type(request.get("verify_saved_workbench_replay", False)) is not bool:
        raise ValueError("verify_saved_workbench_replay must be a boolean")
    record = request["composition_plan"]
    if (not isinstance(record, dict) or not {"path", "bytes", "sha256"} <= set(record)
            or not set(record) <= {"path", "bytes", "sha256", "exists", "retention_role"}
            or not isinstance(record["path"], str) or type(record["bytes"]) is not int or record["bytes"] <= 0
            or not isinstance(record["sha256"], str) or len(record["sha256"]) != 64):
        raise ValueError("composition_plan requires an explicit frozen file record")
    _keys(request["numerics"], _NUMERICS, "cooled numerics")
    numerical = request["numerics"]
    _keys(numerical["cell_mm_xyz"], set("xyz"), "cell pitch")
    for key, value in {**numerical["cell_mm_xyz"], **{k: v for k, v in numerical.items() if k != "cell_mm_xyz"}}.items():
        _number(value, key, positive=True)
    for key in ("rf_steps_per_period", "trajectory_quality", "collision_seed"):
        if type(numerical[key]) is not int:
            raise ValueError(f"{key} must be an integer")
    if not 1 <= numerical["trajectory_quality"] <= 500:
        raise ValueError("SIMION trajectory quality must be within 1..500")
    if type(request["pressure_scale"]) not in (int, float) or request["pressure_scale"] not in (0, 1):
        raise ValueError("controlled pressure scale must be exactly zero or one")
    _keys(request["drive"], {"capture_voltages_v", "closed_voltages_v", "release_voltages_v", "entrance_close_us", "release_start_us"}, "cooled drive")
    for key in ("entrance_close_us","release_start_us"):
        _number(request["drive"][key],key,positive=True)
    if not 0 < request["drive"]["entrance_close_us"] < request["drive"]["release_start_us"] < numerical["maximum_flight_us"]:
        raise ValueError("capture/close/release must be ordered within the complete flight horizon")
    if request["pulse"] != {"policy_id": "actual_field_reference_exit_centering_v1", "target": "oa_exit_geometric_center",
                             "reference_temperature_policy": "provider_gas_temperature"}:
        raise ValueError("cooled OA pulse requires the common actual-field reference policy")
    if request["diagnostics"] != {"policy_id": "automatic_full_population_v1"}:
        raise ValueError("automatic complete-mother diagnostics required")
    _keys(request["design_targets"],{"thermal_sigma_y_mm","static_release_energy_gain_ev"},"cooled design targets")
    for name,value in request["design_targets"].items():
        _number(value,name,positive=True)
    for key in ("field_source", "common_pulse_decision"):
        record = request[key]
        if record is not None:
            if not isinstance(record,dict) or not {"path","bytes","sha256"}.issubset(record) or not set(record).issubset({"path","bytes","sha256","exists","retention_role"}) or record.get("exists",True) is not True:
                raise ValueError(f"{key} requires an existing explicit file record")
            if not isinstance(record["path"], str) or type(record["bytes"]) is not int or record["bytes"] < 0 or not isinstance(record["sha256"], str) or len(record["sha256"]) != 64:
                raise ValueError(f"{key} must be an explicit file identity or null")


def _cooled_instances(plan: dict) -> tuple[str, str, dict]:
    """Select the one supported cooler-to-OA edge from an already scoped plan."""
    selected = plan["scope"]["instance_ids"]
    components = plan["components"]
    coolers = [instance_id for instance_id in selected
               if components[instance_id]["project_id"] == "dual_pressure_rectilinear_ion_processor"]
    accelerators = [instance_id for instance_id in selected
                    if components[instance_id]["project_id"] == "orthogonal_accelerator"]
    if len(selected) != 2 or len(coolers) != 1 or len(accelerators) != 1:
        raise ValueError("cooled frontend supports an explicitly selected cooler and orthogonal accelerator only")
    cooler, accelerator = coolers[0], accelerators[0]
    internal = set(plan["scope"]["connection_ids"])
    edges = [edge for edge in plan["recipe"]["connections"] if edge["connection_id"] in internal]
    if len(edges) != 1:
        raise ValueError("cooled frontend requires one internal cooler-to-OA connection")
    edge = edges[0]
    if (edge["upstream"] != {"instance_id": cooler, "port_id": "exit_gate_outer_face"}
            or edge["downstream"] != {"instance_id": accelerator, "port_id": "side_entry"}
            or edge["coupling_mode"] != "monolithic_joint_solve"):
        raise ValueError("cooled frontend requires exit_gate_outer_face to OA side_entry joint solve")
    return cooler, accelerator, edge


def compile_probe_plan(conditioner: dict, frontend: dict, field_plan: dict) -> tuple[dict, list[dict]]:
    """Emit a reproducible actual-field stencil and axial barrier line.

    The stencil spacing follows the explicit PA pitch. It is a diagnostic
    resolution, not a replacement for a mesh-convergence comparison.
    """
    pitch = max(frontend["cell_mm_xyz"].values())
    local = prepare_buncher_probe_points(conditioner, [-2*pitch, -pitch, 0., pitch, 2*pitch])
    points = [dict(name=f"well_{p['point_id']}", **{f"{a}_mm": p[f"{a}_mm"] for a in "xyz"}) for p in local]
    start = conditioner["geometry"]["entrance_center_mr_mm"]
    stop = conditioner["geometry"]["exit_face_center_mr_mm"]
    count = int(math.ceil((stop[1]-start[1])/pitch))
    points += [dict(name=f"axis_{i}", x_mm=start[0], y_mm=start[1]+(stop[1]-start[1])*i/count, z_mm=start[2]) for i in range(count+1)]
    port=frontend["accelerator_local_region"]["port"]
    entry_y=port["flange_max_mm"]
    from integrations.workflows.local_frontend.analyze import _capture_bounds
    center_y=_capture_bounds(frontend)["y"]["center_mm"]
    extended_count=max(1,int(math.ceil((center_y-stop[1])/pitch)))
    points += [dict(name=f"release_axis_{i}",x_mm=stop[0],y_mm=stop[1]+(center_y-stop[1])*i/extended_count,z_mm=stop[2]) for i in range(1,extended_count+1)]
    points += [dict(name="oa_side_entry",x_mm=stop[0],y_mm=entry_y+pitch,z_mm=stop[2]),
               dict(name="oa_center",x_mm=stop[0],y_mm=center_y,z_mm=stop[2])]
    return dict(schema_version=1, role="rf_oatof_cooled_frontend_probe_plan", frame_id="mrtof_global_cartesian",
        point_columns=["name", "x_mm", "y_mm", "z_mm"], local_stencil_count=len(local), axial_line_count=count+1,
        release_axis_count=extended_count, oa_side_entry_vacuum_offset_mm=pitch,
        local_offsets_mm=[-2*pitch, -pitch, 0., pitch, 2*pitch],
        sampler_repository_path="integrations/workflows/cooled_frontend/sample_field.lua",
        sampler_arguments=["PA_PATH", ",".join(str(frontend["instance_origin_mm"][a]) for a in "xyz"), "INPUT_CSV", "OUTPUT_CSV"],
        output_columns=["name", "x_mm", "y_mm", "z_mm", "potential_v", "ex_v_per_mm", "ey_v_per_mm", "ez_v_per_mm"],
        working_point_kinds=[p["kind"] for p in field_plan["working_points"]],
        interpretation="compose measured DC stage potentials and unit RF fields before effective-well fits; axial line is not a 3D saddle search"), points


def prepare_cooled_frontend(request_path: Path, output_directory: Path | None,
                           repo_root: Path, workspace_root: Path, *, simion_directory: Path | None = None, run_id: str | None = None) -> dict[str, Any]:
    """Validate/compile or freeze a caller-owned run; never solve or generate ions."""
    repo=Path(repo_root).resolve(strict=True)
    workspace = Path(workspace_root).resolve(strict=True)
    request_path = Path(request_path).resolve(strict=True)
    request = _load(request_path)
    validate_request(request)
    request = {**request, "verify_saved_workbench_replay": request.get("verify_saved_workbench_replay", False)}
    parent_record = request["composition_plan"]
    parent_path = record_path(parent_record, base_dir=request_path.parent)
    frozen_parent = None
    if output_directory is not None:
        managed_inputs = Path(output_directory).resolve() / "inputs"
        managed_inputs.mkdir(parents=True, exist_ok=True)
        frozen_parent = managed_inputs / "parent_composition_plan.json"
        if frozen_parent.exists():
            raise ValueError("refuse to overwrite frozen cooled parent composition plan")
        shutil.copyfile(parent_path, frozen_parent)
        verify_record("frozen cooled parent composition plan", {**parent_record, "path": str(frozen_parent)})
        parent = _load(frozen_parent)
    else:
        verify_record("cooled parent composition plan", {**parent_record, "path": str(parent_path)})
        parent = _load(parent_path)
    plan = derive_assembly_scope(parent, local_scope=request.get("local_scope"))
    if plan["assembly_frame_id"] != "mrtof_global_cartesian":
        raise ValueError("cooled frontend must use native MR coordinates")
    upstream_id, downstream_id, edge = _cooled_instances(plan)
    references={};decision_provenance=None
    for name in ("field_source","common_pulse_decision"):
        record=request[name]
        if record is None:
            references[name]=None
        else:
            path=Path(record["path"])
            path=(path if path.is_absolute() else workspace/path).resolve(strict=True)
            authored_envelope=repo/"integrations/config/experiments/cooled_frontend"
            allowed=path.is_relative_to(workspace/"artifacts") or (name=="field_source" and path.is_relative_to(authored_envelope))
            if not allowed or path.stat().st_size != record["bytes"] or file_sha256(path) != record["sha256"]:
                raise ValueError(f"{name} frozen workspace artifact identity differs")
            references[name]=dict(record, path=str(path))
            if name=="common_pulse_decision":
                decision_provenance=_decision_producer(path,workspace,references[name])
    paths, model, _spec, raw_rows, manifest = _source_inputs(request["source"], workspace)
    clock = _producer_clock(manifest["inputs"], paths["producer_manifest"].parent, model)
    guide = export_guide_contract(model, {k: request["source"][k] for k in SOURCE_NAMES[1:]})
    recipe = plan["recipe"]
    poses = {row["instance_id"]: row["transform"] for row in recipe["instances"]}
    if plan["integration_id"] != "instrument_assembly":
        raise ValueError("cooled assembly must be owned by instrument_assembly")
    pose = RigidTransform.from_contract(poses[upstream_id])
    conditioner = build_cooled_buncher_contract(model, guide_contract=guide,
        native_to_assembly=poses[upstream_id], request=request["conditioner"], electrode_ids=CONDITIONER_ELECTRODE_IDS)
    numerical, component = request["numerics"], copy.deepcopy(request["accelerator_component"])
    if "transform" in component:
        raise ValueError("accelerator placement belongs only to the frozen parent composition plan")
    actual_cooler = export_cooled_buncher_assembly_interface(conditioner, guide)
    actual_accelerator = resolve_assembly_interface(
        component["requirements"], geometry_profile_id=component["geometry_profile_id"]
    )
    if plan["components"][upstream_id] != actual_cooler:
        raise ValueError("selected cooler provider interface differs from frozen parent composition plan")
    if plan["components"][downstream_id] != actual_accelerator:
        raise ValueError("selected accelerator provider interface differs from frozen parent composition plan")
    check = next(item for item in plan["connection_checks"] if item["connection_id"] == edge["connection_id"])
    gap = _number(check["gap_mm"], "exit gap", positive=True)
    component["transform"] = {key: poses[downstream_id][key] for key in ("rotation", "translation_mm")}
    # Guide geometry has a fixed provider coordinate representation; convert it
    # to the cooler native frame before applying the sole assembly placement.
    guide_pose = RigidTransform.from_contract(guide["coordinate_transform"]).inverse().then(pose)
    connection = dict(spatial_registration=dict(rotation_upstream_to_downstream=[list(r) for r in guide_pose.rotation],
                                                translation_mm=list(guide_pose.translation_mm)))
    gem, frontend = compile_cooled_frontend(guide, connection, component, conditioner, cell_mm_xyz=numerical["cell_mm_xyz"], exit_gap_mm=gap)
    registration, _ = _registration(dict(source_to_common=guide["coordinate_transform"], guide_to_solver=guide_pose.to_contract()), guide, component, frontend)
    rows = transform_source_rows(raw_rows, pose)
    field_plan = compile_field_plan(frontend, guide, request["drive"],
        hp_rf_peak_amplitude_v=conditioner["drive"]["rf_amplitude_v"],
        refine_convergence_v=numerical["refine_convergence_v"])
    probe_plan, probe_points = compile_probe_plan(conditioner, frontend, field_plan)
    if numerical["collision_seed"] + len(rows)-1 > 2147483646:
        raise ValueError("per-original-ID collision seeds exceed the existing integer contract")
    result = dict(schema_version=1, role="instrument_assembly_cooled_frontend_preparation", status="validated", particle_count=len(rows),
                  default_replay_requested=request["verify_saved_workbench_replay"],
                  pressure_scale=request["pressure_scale"], frontend=frontend, conditioner=conditioner,
                  field_plan=field_plan, probe_plan=probe_plan, input_records={k: dict(path=str(v), exists=True, bytes=request["source"][k]["bytes"], sha256=request["source"][k]["sha256"].upper()) for k, v in paths.items()} | clock["records"],
                  assembly_plan=plan, geometry_gem=gem,
                  source_states_preserved=True, scope="local cooled source and OA only; no MR analyzer")
    if output_directory is None:
        return result
    if run_id is None:
        raise ValueError("writing a prepared run requires the managed run_id")
    validate_run_id(run_id)
    output = Path(output_directory).resolve()
    hs1_source = None if simion_directory is None else Path(simion_directory).resolve(strict=True)/"examples/collision_hs1/collision_hs1.lua"
    if request["common_pulse_decision"] is not None and hs1_source is None:
        raise ValueError("population preparation requires explicit SIMION directory to freeze official HS1")
    hs1_text = None if hs1_source is None else adapt_hs1_for_repeat_fly(hs1_source.read_text(encoding="utf-8-sig"))
    inputs = output/"inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    if (inputs/"cooled_field_plan.json").exists():
        raise ValueError("refuse to overwrite frozen cooled preparation")
    for name,basename in (("field_source","cooled_field_source.json"),("common_pulse_decision","cooled_common_pulse_decision.json")):
        if references[name] is not None:
            source=Path(references[name]["path"])
            target=inputs/basename
            shutil.copyfile(source,target)
            if file_sha256(target)!=references[name]["sha256"]:
                raise ValueError(f"frozen {name} bytes changed")
            references[name]=dict(references[name], path=str(target))
            if name == "field_source":
                envelope = _load(target)
                manifest_path = Path(envelope["source_owner_manifest_record"]["path"])
                if not manifest_path.is_absolute():
                    manifest_path = workspace / manifest_path
                require_completed_terminal_publication(manifest_path)
                owner = _load(manifest_path)
                for role, source_record in (("manifest", envelope["source_owner_manifest_record"]),
                                            ("run_config", owner["run_config"])):
                    original = Path(source_record["path"])
                    if not original.is_absolute():
                        original = workspace / original
                    verify_record("cooled field producer " + role, {**source_record, "path": str(original)})
                    shutil.copyfile(original, inputs / ("cooled_field_source_" + role + ".json"))
    documents = {"request.json": request, "guide_contract.json": guide, "frontend_contract.json": frontend, "conditioner_contract.json": conditioner,
                 "registration.json": registration, "numerics.json": numerical, "composition_plan.json": plan,
                 "cooled_field_plan.json": field_plan, "cooled_drive.json": request["drive"],
                 "cooled_probe_plan.json": probe_plan,
                 "cooled_design_targets.json": request["design_targets"],
                 "cooled_experiment.json": dict(schema_version=1, role="rf_oatof_cooled_pressure_control", pressure_scale=request["pressure_scale"],
                                                pulse=request["pulse"], gas=conditioner["gas"], field_source=references["field_source"],
                                                common_pulse_decision=references["common_pulse_decision"],
                                                sole_pressure_variable="shared geometry, voltage endpoints and common frozen gate/OA clocks"),
                 "source_identity.json": dict(provider_project_id=guide["provider_project_id"], particle_count=len(rows),
                                              sampling="complete_frozen_population__no_resampling", source_inputs=result["input_records"], clock_epoch_id=clock["clock_epoch_id"],
                                              native_clock_projection=SOURCE_CLOCK)}
    if decision_provenance is not None:
        documents["cooled_common_pulse_provenance.json"]=decision_provenance
    plan_bytes = (json.dumps(plan, indent=2, allow_nan=False)+"\n").encode("utf-8")
    identity = dict(schema_version=2, integration_id="instrument_assembly", workflow_id="cooled_frontend", run_id=run_id,
                    composition_plan=dict(path="composition_plan.json", sha256=hashlib.sha256(plan_bytes).hexdigest().upper()))
    validate_schema(identity, "integration_artifact_identity.schema.json")
    documents["integration_identity.json"] = identity
    for name, value in documents.items():
        (inputs/name).write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")
    paths.update(clock["paths"])
    for name, role in {
        "clock_authority.json": "clock_authority", "instrument_epoch.json": "instrument_epoch",
        "resolved_model.json": "resolved_model", "source_spec.json": "source_spec",
        "release_raw.csv": "release_csv", "producer_manifest.json": "producer_manifest",
    }.items():
        source, target = paths[role], inputs/name
        if target.resolve() != source.resolve():
            shutil.copyfile(source, target)
        if file_sha256(target) != result["input_records"][role]["sha256"]:
            raise ValueError(f"frozen cooled input changed: {name}")
    for name, text in {"frontend.gem": gem, "cooled_probe_points.csv": _csv_text(["name", "x_mm", "y_mm", "z_mm"], probe_points),
                       "release_global.csv": _csv_text(GLOBAL_COLUMNS, rows)}.items():
        (inputs/name).write_text(text, encoding="utf-8", newline="\n")
    if hs1_text is not None:
        frozen_hs1=inputs/"cooled_collision_hs1.lua"
        frozen_hs1.write_text(hs1_text,encoding="utf-8",newline="\n")
        (inputs/"cooled_hs1_identity.json").write_text(json.dumps(dict(source=file_record(hs1_source), adapted=file_record(frozen_hs1),
            adapter="common.simion.collision_hs1.adapt_hs1_for_repeat_fly"),indent=2)+"\n",encoding="utf-8",newline="\n")
    result.update(status="prepared", output_directory=str(output))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--simion-directory", type=Path)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    if args.validate_only == bool(args.output_directory):
        parser.error("choose validate-only or an owned output-directory")
    result = prepare_cooled_frontend(args.request, args.output_directory, args.repo_root, args.workspace_root,simion_directory=args.simion_directory, run_id=args.run_id)
    print(json.dumps({k: result[k] for k in ("role", "status", "particle_count", "pressure_scale")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
