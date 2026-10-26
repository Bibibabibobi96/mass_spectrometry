"""Plan provider-native downstream fields and publish completed native evidence.

The managed caller executes each argv through its public resource-budget
wrapper. This module never spawns SIMION, owns no cache and does not Fly.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import stat

from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record
from integrations.runtime.single_flight_source import lua_value as _lua_value
from integrations.runtime.single_flight_frontend import instance_design_record, native_frontend_instances
from integrations.workflows.single_reflection_flight.field_plan import working_point_member_id
from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import derive_simion_geometry, resolve_physical_geometry

_PROVIDER = "projects/single_reflection_oa_tof_mass_analyzer/simion"
_RESOURCES = {
    "tube_builder": f"{_PROVIDER}/workbench/build_flight_tube_variant.lua",
    "tube_gem": f"{_PROVIDER}/workbench/oatof_flight_tube_ground.gem",
    "detector_builder": f"{_PROVIDER}/workbench/build_detector_variant.lua",
    "detector_gem": f"{_PROVIDER}/workbench/oatof_detector_ground.gem",
    "reflectron_builder": f"{_PROVIDER}/reflectron/build_reflectron_variant.lua",
    "reflectron_gem": f"{_PROVIDER}/reflectron/oatof_reflectron_ideal_10_5.gem",
    "exporter": "common/simion/export_standalone_pa.lua",
    "audit": "integrations/workflows/single_reflection_flight/audit_downstream_fields.lua",
}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def _live_run(run: Path) -> Path:
    run = run.absolute()
    if not run.is_dir():
        raise ValueError("downstream producer run directory is missing")
    if _read(run / "run_config.json").get("project") != "instrument_assembly":
        raise ValueError("downstream producer requires an instrument_assembly run")
    manifest = run / "run_manifest.json"
    if manifest.exists() and _read(manifest).get("status") != "checkpoint":
        raise ValueError("downstream producer cannot modify a terminal run")
    return run


def _validate_provider_inputs(g: dict, b: dict, m: dict, rings: dict, v: dict) -> None:
    """Apply the three provider builders' numeric preconditions before staging."""
    # Sources: simion/workbench/build_{flight_tube,detector}_variant.lua and
    # simion/reflectron/build_reflectron_variant.lua under the oaTOF provider.
    positive = [
        ("geometry_mm", g, ("flight_tube_r", "flight_tube_wall", "shield_endcap_thickness",
                            "L_reflectron", "ring_thickness", "shield_axial_gap", "L_stage1",
                            "L_stage2", "bore_r", "ring_outer_r")),
        ("flight_tube", b["flight_tube"], ("cell_axial_mm", "cell_radial_mm", "max_gib")),
        ("reflectron", b["reflectron"], ("cell_axial_mm", "cell_radial_mm", "max_gib")),
        ("detector", b["detector"], ("margin_xy_mm", "max_mib")),
        ("simion_detector_marker", m, ("cell_xy_mm", "cell_z_mm", "active_radius_mm",
                                      "absorber_thickness_mm", "front_margin_z_mm", "back_margin_z_mm")),
    ]
    for label, values, keys in positive:
        for key in keys:
            value = values[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"downstream {label}.{key} must be finite and positive")
    for label, values, keys in (("geometry_mm", g, ("shield_outer_z_min", "L_flight")),
                                ("electrodes_V", v, ("midgrid", "backplate"))):
        for key in keys:
            value = values[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"downstream {label}.{key} must be finite")
    if g["L_flight"] - g["shield_outer_z_min"] <= g["shield_endcap_thickness"]:
        raise ValueError("downstream flight_tube interface must lie beyond the near cap")
    if not g["bore_r"] < g["ring_outer_r"] < g["flight_tube_r"]:
        raise ValueError("downstream reflectron radii must be ordered")
    if abs(g["L_reflectron"] - g["L_stage1"] - g["L_stage2"]) >= 1e-9:
        raise ValueError("downstream reflectron length must equal stage1 + stage2")
    for key in ("stage1_count", "stage2_count"):
        value = rings[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 1 or value != math.floor(value):
            raise ValueError(f"downstream rings.{key} must be a positive integer")
    middle = g["L_stage1"] / b["reflectron"]["cell_axial_mm"]
    if abs(middle - math.floor(middle + 0.5)) > 1e-8:
        raise ValueError("downstream reflectron midgrid zero-width sheet must lie on a raw PA row")
    for key, minimum in (("absorber_thickness_mm", 5 * m["cell_z_mm"]),
                          ("front_margin_z_mm", 10 * m["cell_z_mm"]),
                          ("back_margin_z_mm", 5 * m["cell_z_mm"])):
        if m[key] < minimum:
            raise ValueError(f"downstream detector {key} is below its provider cell-span minimum")
    if b["detector"]["margin_xy_mm"] < m["cell_xy_mm"]:
        raise ValueError("downstream detector margin_xy_mm must span at least one xy cell")


def preflight_frontend_resources(design: dict, limits: dict, *, reused_member_ids: tuple[str, ...] | list[str] = ()) -> dict:
    """Reject impossible direct-field budgets without predicting process peaks.

    SIMION 2020 uses 8 bytes/node on disk and about 10 in RAM. Each numerical
    domain publishes its declared common working fields. Parent Refine/export opens two
    parent arrays; a patch boundary transfer opens parent plus patch, then
    Refine/export opens two patch arrays. Published fields and construction scratch
    determine the cold disk floor. Headers and process overhead are excluded.
    """
    kinds = [point['kind'] for point in (design.get('working_points') or [])]
    expected_kinds = ['carrier_off', *[kind for kind in kinds if kind == 'rf_reference'],
                      *(['pulse_delta'] if 'pulse_delta' in kinds else [])]
    if (design.get("schema_version") != 3
            or design.get("role") != "frontend_native_field_design"
            or design.get("surface") != "none"
            or kinds != expected_kinds):
        raise ValueError("frontend resource preflight requires ordered OFF, RF and optional pulse fields")
    field_count = len(design["working_points"])
    members = [working_point_member_id(point) for point in design["working_points"]]
    if len(members) != len(set(members)) or len(reused_member_ids) != len(set(reused_member_ids)) or not set(reused_member_ids) <= set(members):
        raise ValueError("frontend reused members must be unique actual working members")
    missing_count = len(set(members) - set(reused_member_ids))
    domains = design.get("domains", [])
    if ([row.get("domain_id") for row in domains] not in
            (["parent"], ["parent", "entrance_refinement"])
            or domains[0].get("boundary_policy") != "native_zero_neumann"
            or (len(domains) == 2 and (domains[1].get("boundary_policy") != "parent_dirichlet"
                or domains[1].get("parent_domain_id") != "parent"))):
        raise ValueError("frontend resources require ordered parent and optional entrance refinement domains")
    arrays = []
    for domain in domains:
        dimensions = [domain["dimensions"][axis] for axis in ("nx", "ny", "nz")]
        if any(type(value) is not int or value < 2 for value in dimensions):
            raise ValueError(f"{domain['domain_id']}: resource dimensions must be positive PA grid sizes")
        nodes = math.prod(dimensions)
        arrays.append(dict(domain_id=domain["domain_id"], nodes=nodes,
                           disk_payload_bytes=nodes * 8, ram_bytes=nodes * 10))
    parent_nodes = arrays[0]["nodes"]
    patch_nodes = arrays[1]["nodes"] if len(arrays) == 2 else 0
    total_nodes = parent_nodes + patch_nodes
    disk_floor = 8 * missing_count * total_nodes
    ram_floor = max(20 * parent_nodes, 10 * total_nodes, 20 * patch_nodes)
    # Domains complete in order: earlier ordinary payloads remain resident,
    # while only the current domain owns raw geometry and working-PA scratch.
    cache_peak = 0
    preceding_nodes = 0
    if missing_count:
        for array in arrays:
            cache_peak = max(cache_peak, 8 * (
                missing_count * preceding_nodes + (missing_count + 2) * array["nodes"]))
            preceding_nodes += array["nodes"]
        cache_peak = max(cache_peak, disk_floor)
    # A declared producer source only contributes immutable PA inputs here.
    # Field-design planning neither Refines nor Flies it; execute performs the
    # actual-workbench/Fly memory checks at the point those arrays are opened.
    required = () if not missing_count else (
        ("transient_run_directory_bytes", disk_floor),
        ("process_tree_working_set_bytes", ram_floor),
    )
    for name, floor in required:
        limit = limits[name]
        if type(limit) is not int or limit <= floor:
            raise ValueError(f"frontend mandatory PA lower bound {name}={floor} requires positive "
                             f"headroom; budget={limit}. Headers, other payloads and process overhead "
                             "are excluded; this is not a peak guarantee.")
    return dict(domain_arrays=arrays, working_point_count=field_count, missing_working_member_count=missing_count, runtime_array_count=field_count * len(arrays),
        mandatory_new_disk_payload_bytes_lower_bound=disk_floor,
        construction_process_array_bytes_lower_bound=ram_floor,
        flight_process_array_bytes_lower_bound=10 * field_count * total_nodes,
        # Sealing deletes each member working scratch; publication moves its
        # payload. Domain raw geometry is removed before the next domain.
        cache_miss_new_disk_payload_bytes_lower_bound=cache_peak,
        scope="mandatory_array_lower_bounds_only__headers_other_payloads_and_process_overhead_excluded",
        cache_policy="each_domain_publishes_only_common_standalone_fields__not_a_rebuild_decision")


def plan_downstream_fields(preparation: dict, run: Path, *, snapshot_root: Path, field_limits: dict | None = None) -> dict:
    """Return ordered native commands, using only the frozen final provider."""
    run = _live_run(run)
    frontend_floor = None
    if field_limits is not None:
        field_design = _read(run / "inputs/frontend_field_design.json")
        reused_members = []
        if "frontend_fields" in preparation.get("input_records", {}):
            request = _read(record_path(preparation["input_records"]["request"]))
            reused_members = request["providers"].get("frontend_field_reuse_members",
                [working_point_member_id(point) for point in field_design["working_points"]])
        frontend_floor = preflight_frontend_resources(field_design, field_limits, reused_member_ids=reused_members)
    if preparation.get("role") != "single_reflection_geometry_preparation":
        raise ValueError("current geometry preparation receipt required")
    geometry = _read(record_path(preparation['outputs']['frontend_geometry']))
    oatof_id = native_frontend_instances(geometry['composition_plan'])[1]
    provider_record = instance_design_record(preparation, oatof_id)
    verify_record("frozen final oaTOF", provider_record)
    provider_path = record_path(provider_record)
    # Identity records canonicalize their paths.  Compare canonical locations
    # for containment, but retain the execution-junction spelling in `run` and
    # all native argv values below.
    if not provider_path.is_relative_to((run / "inputs").resolve(strict=True)):
        raise ValueError("oaTOF provider must be frozen in this producer run")
    resolved = _read(provider_path)
    if resolved.get("role") != "oa_tof_resolved_contract_do_not_edit":
        raise ValueError("a complete final oaTOF resolved contract is required")
    g, b, m = (resolved[k] for k in ("geometry_mm", "simion_geometry_build", "simion_detector_marker"))
    rings, v = resolved["rings"], resolved["electrodes_V"]
    _validate_provider_inputs(g, b, m, rings, v)
    snapshot_root = snapshot_root.absolute()
    resources = {key: snapshot_root / name for key, name in _RESOURCES.items()}
    if any(not path.is_file() for path in resources.values()):
        raise ValueError("frozen downstream provider resources are incomplete")
    # A declared source is a frozen scientific input, never an opportunistic
    # search for a prior producer.  It carries the already published static
    # fields; this consumer only reserves its own frontend arrays.
    source_records = preparation["input_records"]
    if "downstream_fields" in source_records:
        required = ("downstream_fields", "downstream_fields_manifest", "downstream_fields_command_plan")
        if any(key not in source_records for key in required):
            raise ValueError("declared downstream field source is incomplete")
        receipt_record, manifest_record, command_record = (source_records[key] for key in required)
        for label, record in zip(required, (receipt_record, manifest_record, command_record), strict=True):
            verify_record("frozen " + label, record)
        receipt, manifest, command_plan = (_read(record_path(record)) for record in
                                           (receipt_record, manifest_record, command_record))
        if (receipt.get("schema_version") != 1
                or receipt.get("role") != "single_reflection_downstream_field_preparation"
                or receipt.get("status") != "success"
                or receipt.get("native_family_origin") != "generated_in_producer_run"):
            raise ValueError("declared downstream field receipt is not a successful native publication")
        if manifest.get("role") != "simulation_run_manifest":
            raise ValueError("declared downstream source manifest is not terminal")
        if any(str(receipt["oatof_resolved_record"][key]).upper() != str(provider_record[key]).upper()
               for key in ("bytes", "sha256")):
            raise ValueError("declared downstream fields differ from the frozen final oaTOF provider")
        # Reject unavailable source assets before any frontend construction.
        # Reuse the runtime's metadata projection; PA bytes are guarded only
        # when the workbench actually consumes them.
        from integrations.workflows.single_reflection_flight.runtime import _downstream_fields
        _downstream_fields(receipt_record, provider_record, manifest_record)
        published_plan = receipt.get("command_plan_record", {})
        if any(str(published_plan.get(key, "")).upper() != str(command_record.get(key, "")).upper()
               for key in ("bytes", "sha256")):
            raise ValueError("declared downstream command plan differs from its publication")
        current_resources = {key: file_record(path) for key, path in resources.items()}
        planned_resources = command_plan.get("resource_records", {})
        if set(planned_resources) != set(_RESOURCES) or any(
                any(str(planned_resources[name].get(key, "")).upper() != str(current_resources[name][key]).upper()
                    for key in ("bytes", "sha256")) for name in _RESOURCES):
            raise ValueError("declared downstream native resources differ from the frozen snapshot")
        reserved_payload = 0
        if field_limits is not None and field_limits["transient_run_directory_bytes"] <= reserved_payload:
            raise ValueError("instrument run array payload reservation requires positive headroom")
        plan = dict(schema_version=1, role="single_reflection_downstream_native_plan", run_directory=str(run),
                    oatof_resolved_record=provider_record, resource_records=current_resources, assets=[], steps=[],
                    frontend_resource_lower_bounds=frontend_floor,
                    reserved_run_array_payload_bytes=reserved_payload, array_estimates=[],
                    estimate_scope="reused_published_downstream_fields__frontend_array_storage_only",
                    publication=dict(receipt_record=receipt_record))
        plan_path = run / "inputs" / "downstream_field_source_plan.json"
        _write(plan_path, plan)
        return dict(plan_record=file_record(plan_path), steps=[], array_estimates=[],
                    frontend_resource_lower_bounds=frontend_floor, reserved_run_array_payload_bytes=reserved_payload,
                    publication=plan["publication"])
    directory = run / "simion/downstream_fields"
    if directory.exists():
        raise ValueError("refusing to overwrite downstream build staging")
    tube, mirror, detector = (directory / name for name in ("flight_tube.pa#", "reflectron.pa#", "detector.pa#"))
    operating = directory / "reflectron.pa"
    steps = []

    def command(name: str, stage: str, resource: str, args: list, marker: str) -> None:
        steps.append(dict(index=len(steps), name=name, resource_stage=stage,
            argv=["--nogui", "--noprompt", "lua", str(resources[resource]), *map(str, args)],
            success_marker=marker))

    projection_path = directory / "oatof_resolved.lua"
    physical = resolve_physical_geometry(resolved)
    command("flight_tube", "pa_refine", "tube_builder",
        [resources["tube_gem"], tube, projection_path], "BUILD: PASS")
    command("detector", "pa_refine", "detector_builder",
        [resources["detector_gem"], detector, projection_path], "BUILD: PASS")
    command("reflectron", "pa_refine", "reflectron_builder",
        [resources["reflectron_gem"], mirror, projection_path, "refine-all"], "BUILD: PASS")
    command("reflectron_export", "prepare", "exporter", [mirror.with_suffix(".pa0"), operating], "STANDALONE_PA_EXPORT=PASS")
    domains = derive_simion_geometry(geometry=g, coordinate=resolved["coordinate_convention"], build=b,
                                     marker=m, source=resolved["particle_source"])["simion_instances"]
    assets, estimates = [], []
    for domain in domains:
        role = "flight_tube" if domain["role"] == "flight_tube_shield" else domain["role"]
        if role == "accelerator":
            continue
        native = role != "reflectron"
        stem = directory / role
        numerics = b["flight_tube" if role == "flight_tube" else role]
        pitches = ([m["cell_xy_mm"], m["cell_xy_mm"], m["cell_z_mm"]] if role == "detector" else
                   [numerics["cell_axial_mm"], numerics["cell_radial_mm"], numerics["cell_radial_mm"]])
        grid = {key: domain[key] for key in ("nx", "ny", "nz")}
        grid.update(dict(zip(("dx_mm", "dy_mm", "dz_mm"), pitches, strict=True)))
        asset = dict(role=role, representation="run_private_native_static_family" if native else "standalone_voltageized_static_pa",
            carrier_path=str(stem.with_suffix(".pa0" if native else ".pa")),
            family_paths=[str(stem.with_suffix(suffix)) for suffix in (".pa#", ".pa0", ".pa1", ".pa-surf")] if native else [],
            grid=grid, symmetry="3dplanar" if role == "detector" else "2dcylindrical")
        if role == "reflectron":
            asset["endpoint_samples"] = [dict(x=0, voltage=0),
                dict(x=round(g["L_stage1"] / pitches[0]), voltage=v["midgrid"]),
                dict(x=math.ceil(g["L_reflectron"] / pitches[0]), voltage=v["backplate"])]
        assets.append(asset)
        nodes = domain["nx"] * domain["ny"] * domain["nz"]
        # Exact storage factors from the provider Lua builders cited above:
        # PA#, PA0, basis members and surface metadata; not process peak RAM.
        factor = rings["stage1_count"] + rings["stage2_count"] + 6.25 if role == "reflectron" else 3.25
        array_bytes = nodes * 8 * factor
        limit_key, unit = ("max_mib", 1024**2) if role == "detector" else ("max_gib", 1024**3)
        if array_bytes / unit > numerics[limit_key]:
            raise ValueError(f"downstream {role} provider array estimate {array_bytes / unit:.12g} exceeds {limit_key}={numerics[limit_key]}")
        estimates.append(dict(role=role, nodes=nodes, single_array_bytes=nodes * 8, provider_array_set_bytes=array_bytes))
    # Only downstream construction is run-private. Frontend fields publish
    # directly to their common owner, with no duplicate run payload.
    # The standalone reflectron export coexists with its producer PA family.
    reserved_payload = math.ceil(sum(row['provider_array_set_bytes'] for row in estimates)
        + next(row['single_array_bytes'] for row in estimates if row['role'] == 'reflectron'))
    if field_limits is not None and field_limits['transient_run_directory_bytes'] <= reserved_payload:
        raise ValueError(f"instrument run array payload reservation {reserved_payload} requires positive headroom; "
                         f"budget={field_limits['transient_run_directory_bytes']}. "
                         "Headers, logs and process overhead are excluded.")
    directory.mkdir(parents=True)
    projection_path.write_text("return " + _lua_value(dict(resolved, physical_geometry=physical)) + "\n",
                               encoding="utf-8", newline="\n")
    audit_output = directory / "native_audit.json"
    audit_spec = directory / "native_audit.lua"
    audit_spec.write_text("return " + _lua_value(dict(assets=assets, output=str(audit_output))) + "\n", encoding="utf-8", newline="\n")
    command("native_audit", "prepare", "audit", [audit_spec], "DOWNSTREAM_NATIVE_AUDIT=PASS")
    plan = dict(schema_version=1, role="single_reflection_downstream_native_plan", run_directory=str(run),
        oatof_resolved_record=provider_record, resource_records={key: file_record(path) for key, path in resources.items()},
        provider_projection_record=file_record(projection_path),
        audit_spec_record=file_record(audit_spec), audit_output=str(audit_output), assets=assets, steps=steps,
        frontend_resource_lower_bounds=frontend_floor,
        reserved_run_array_payload_bytes=reserved_payload,
        array_estimates=estimates, estimate_scope="array_storage_only__not_process_peak_or_execution_budget")
    plan_path = directory / "command_plan.json"
    _write(plan_path, plan)
    return dict(plan_record=file_record(plan_path), steps=steps, array_estimates=estimates,
                frontend_resource_lower_bounds=frontend_floor, reserved_run_array_payload_bytes=reserved_payload)


def publish_downstream_fields(plan_path: Path, execution_records: list[dict]) -> dict:
    """Publish only after every native step and its native audit succeeded."""
    plan = _read(plan_path)
    run = _live_run(Path(plan["run_directory"]))
    # Keep the short execution junction in command arguments, but compare
    # canonical paths when establishing filesystem containment.
    if (plan.get("role") != "single_reflection_downstream_native_plan"
            or not plan_path.resolve().is_relative_to(run.resolve())):
        raise ValueError("run-local downstream native plan required")
    output = plan_path.parent / "downstream_field_preparation.json"
    if output.exists():
        raise ValueError("downstream publication already exists")
    if len(execution_records) != len(plan["steps"]):
        raise ValueError("all native execution records are required")
    for step, execution in zip(plan["steps"], execution_records, strict=True):
        if (execution["index"] != step["index"] or execution["argv"] != step["argv"] or execution["exit_code"] != 0):
            raise ValueError("native command execution failed or differs from the frozen plan")
        for key in ("stdout_record", "stderr_record", "usage_record"):
            record = execution[key]
            if not record_path(record).is_relative_to(run.resolve()):
                raise ValueError("native execution evidence must belong to the producer run")
            verify_record(key, record)
        usage = _read(record_path(execution["usage_record"]))
        if (usage.get("role") != "multipole_resource_usage" or usage.get("status") not in {"running", "completed"}
                or usage.get("failure_class") is not None or usage.get("limit_name") is not None):
            raise ValueError("native execution resource evidence reports failure")
        if step["success_marker"] not in record_path(execution["stdout_record"]).read_text(encoding="utf-8-sig"):
            raise ValueError("native command did not report its completion marker")
    audit_path = Path(plan["audit_output"])
    audit = _read(audit_path)
    if (audit.get("role") != "single_reflection_downstream_native_audit" or audit.get("status") != "success"
            or audit.get("checked_assets") != [{"role": a["role"], "grid": a["grid"]} for a in plan["assets"]]):
        raise ValueError("native field audit did not verify every planned downstream domain")
    # Each actual payload crosses this publication identity boundary once.
    assets = []
    for asset in plan["assets"]:
        paths = [Path(name) for name in asset["family_paths"]] or [Path(asset["carrier_path"])]
        if any(not path.is_file() or path.stat().st_size <= 0 for path in paths):
            raise ValueError("native downstream asset has missing or empty members")
        records = {}
        for path in paths:
            path.chmod(path.stat().st_mode & ~stat.S_IWRITE)
            records[str(path)] = {**file_record(path), "read_only": True}
        assets.append(dict(role=asset["role"], representation=asset["representation"],
            carrier_record=records[asset["carrier_path"]],
            family_records=list(records.values()) if asset["family_paths"] else []))
    receipt = dict(schema_version=1, role="single_reflection_downstream_field_preparation", status="success",
        native_family_origin="generated_in_producer_run", run_directory=str(run),
        oatof_resolved_record=plan["oatof_resolved_record"], assets=assets,
        command_plan_record=file_record(plan_path), native_execution_records=execution_records,
        native_audit_record=file_record(audit_path),
        validation_scope="native_dimensions_symmetry_ground_potential_and_reflectron_endpoints__not_convergence_or_flight")
    _write(output, receipt)
    return dict(receipt_record=file_record(output), receipt=receipt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--preparation", type=Path)
    parser.add_argument("--snapshot-root", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--execution-records", type=Path)
    parser.add_argument("--engineering-budget", type=Path)
    args = parser.parse_args()
    if args.plan is not None and args.execution_records is not None:
        result = publish_downstream_fields(args.plan, json.loads(args.execution_records.read_text(encoding="utf-8-sig")))
    elif args.run is not None and args.preparation is not None and args.snapshot_root is not None:
        limits = (_read(args.engineering_budget)["stage_limits"]["instrument_field_design"]
                  if args.engineering_budget is not None else None)
        result = plan_downstream_fields(_read(args.preparation), args.run, snapshot_root=args.snapshot_root, field_limits=limits)
    else:
        parser.error("provide preparation/run/snapshot-root, or plan/execution-records")
    print(json.dumps(result, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
