"""Prepare and publish one same-mesh COMSOL P/S candidate; no optimizer or PA copies."""
from __future__ import annotations

import argparse
import json
import math
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from msplatform.execution.artifact_retention import validate_retention
from msplatform.execution.capacity_ledger import record_capacity_object
from msplatform.execution.recorded_file_removal import write_json_atomic
from msplatform.execution.run_capacity_lifecycle import register_writing, register_writing_range
from msplatform.execution.terminal_publication import publish_terminal_state
from msplatform.execution.inputs import freeze_file

from .resources import native_resource_path, native_resource_text
from msplatform.execution.retention import apply_retention, build_run_manifest
from msplatform.backends.comsol.candidate_authority import (
    derive_candidate_authority,
    named_record as _named_record,
)
from msplatform.backends.comsol.static_field_binding import _record, load_binding

def _sealed_export_plan(manifest: Path, grid: dict[str, Any], model: Path,
                        dataset: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    """Bind one sealed export's exact grid and stored model/solution, without PA I/O."""
    records = [r for r in read(manifest)["inputs"].values()
               if Path(r["path"]).name in {"plan.json", "diagnostic_plan.json"}]
    if len(records) != 1:
        raise ValueError("scalar export must bind exactly one sealed export plan")
    path = Path(_named_record(records, Path(records[0]["path"]).name,
                              "scalar export plan")["path"])
    _record(manifest, path)
    plan = read(path)
    if Path(plan["source_mph"]).resolve() != model.resolve():
        raise ValueError("source field and source scalar binding do not share the same MPH")
    if any(plan[k] != grid[k] for k in ("origin_mm", "pitch_mm", "dimensions")):
        raise ValueError("source scalar binding and sealed export plan grids differ")
    if any(plan[k] != dataset[k] for k in ("dataset_tag", "solution_tag")):
        raise ValueError("source scalar export and stored solution dataset differ")
    return path, plan


def read(path: Path) -> dict[str, Any]:
    """Read one UTF-8 JSON authority."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def compile_request(request: dict[str, Any]) -> dict[str, Any]:
    """Read sealed small receipts and inherit large model identities by record/size."""
    if request.get("schema_version") != 1 or request.get("role") != "mrtof_same_mesh_field_provider_request":
        raise ValueError("unsupported field provider request")
    # Optional official launcher override; absence retains the common entry's default.
    if "comsol_allocator" in request and request["comsol_allocator"] not in ("auto", "scalable", "native"):
        raise ValueError("comsol_allocator must be auto, scalable or native")
    binding = load_binding(Path(request["source_binding_path"]))
    manifest = Path(request["source_field_manifest"])
    summary = read(manifest.with_name("summary.json"))
    source_result = summary["result"]
    if summary["status"] != "success" or not source_result["field_solved"]:
        raise ValueError("source must be a successfully solved field")
    model = Path(summary["model_path"])
    model_record = _record(manifest, model)
    dataset_path = manifest.parent / "results" / "dataset_readback.json"
    dataset = read(dataset_path)
    _record(manifest, dataset_path)
    if dataset["dataset_type"] != "Solution":
        raise ValueError("source dataset must consume a stored solution")
    export_root = Path(binding["export_manifest"]).parent
    export_manifest = Path(binding["export_manifest"])
    export_plan_path, export_plan = _sealed_export_plan(export_manifest, binding["grid"], model, dataset)
    study_mesh_path = None
    if "active_mesh_tag" in source_result:
        active_mesh_tag = source_result["active_mesh_tag"]
    else:
        # Legacy sealed single-mesh fields already recorded the actual Study binding.
        study_mesh_path = Path(_named_record(read(manifest)["outputs"], "solver_configured.json",
                                            "source Study mesh readback")["path"])
        _record(manifest, study_mesh_path)
        properties = read(study_mesh_path)["study_step"]["properties"]
        meshes = [r for r in properties if r["name"] == "mesh"]
        if (len(meshes) != 1 or meshes[0]["read_error"] or len(meshes[0]["value"]) != 2
                or meshes[0]["value"][0] != "geom1"):
            raise ValueError("source Study must bind one recorded geom1 mesh")
        active_mesh_tag = meshes[0]["value"][1]
    if not isinstance(active_mesh_tag, str) or not active_mesh_tag:
        raise ValueError("source active mesh tag must be explicit")
    if "active_mesh_tag" in export_plan and export_plan["active_mesh_tag"] != active_mesh_tag:
        raise ValueError("source scalar export and solved active mesh differ")
    source_authority = read(manifest.parent / "inputs" / "frozen_input.json")
    source_geometry = read(manifest.parent / "inputs" / "resolved_geometry.json")
    if source_authority != binding["authority"] or source_geometry != binding["geometry"]:
        raise ValueError("source field geometry/voltage authority differs from scalar binding")
    candidate, mirror_paths = derive_candidate_authority(request, source_authority)
    validate_retention(request["artifact_retention"])
    if request["resource_threshold_action"] != "warn":
        raise ValueError("this provider uses warning-only resource thresholds")
    for key in ("solve_memory_bytes", "solve_seconds", "artifact_budget_bytes"):
        if not math.isfinite(float(request[key])) or request[key] <= 0:
            raise ValueError(f"positive resource observation budget required: {key}")
    grid = {k: export_plan[k] for k in ("origin_mm", "maximum_mm", "pitch_mm", "dimensions", "point_count", "block_points")}
    grid.update(dataset_tag=dataset["dataset_tag"], solution_tag=dataset["solution_tag"])
    windows = []
    for index, window in enumerate(binding.get("refinement_windows", []), start=1):
        local_manifest = Path(window["export_manifest"])
        path, local_plan = _sealed_export_plan(local_manifest, window["grid"], model, dataset)
        if local_plan.get("active_mesh_tag", active_mesh_tag) != active_mesh_tag:
            raise ValueError("source refinement window and solved active mesh differ")
        local_grid = {k: local_plan[k] for k in grid}
        windows.append(dict(name=window["name"], active_box_mm=window["active_box_mm"],
                            export_manifest=str(local_manifest), source_export_plan=str(path),
                            export_grid=local_grid, receipt_directory=f"windows/window-{index:03d}"))
    writer = export_root / "inputs" / "simion_pa_save.m"
    _record(Path(binding["export_manifest"]), writer)
    return dict(request, source_mph=str(model), source_mph_record=model_record,
                source_model_not_copied_or_rehashed=True, export_grid=grid, refinement_windows=windows,
                active_mesh_tag=active_mesh_tag, source_export_plan=str(export_plan_path),
                source_study_mesh_readback=str(study_mesh_path) if study_mesh_path else None,
                expected_tetrahedra=int(source_result["tetrahedra"]),
                expected_vacuum_domain_count=int(source_result["vacuum_domain_count"]),
                candidate_authority=candidate, source_authority=source_authority,
                mirror_reference_paths=mirror_paths,
                geometry=source_geometry, source_dataset=dataset, writer=str(writer),
                assembly_manifest=binding["assembly_manifest"], collision_manifest=binding["collision_manifest"])


def resolve_completed_provider(request: dict[str, Any], manifest: Path) -> str | None:
    """Validate one explicitly selected sealed provider; reuse only its full target authority."""
    expected = compile_request(request)
    sealed = read(manifest)
    if sealed.get("mode") != "same_mesh_ps_field_provider" or sealed.get("status") != "success":
        raise ValueError("completed provider must be a successful same_mesh_ps_field_provider")
    summary_path = manifest.with_name("summary.json")
    plan_path = manifest.parent / "inputs" / "plan.json"
    for path in (summary_path, plan_path):
        _record(manifest, path)
    summary, completed = read(summary_path), read(plan_path)
    if summary.get("status") != "success" or not summary.get("field_binding"):
        raise ValueError("completed provider must publish a successful field binding")
    binding_path = Path(summary["field_binding"])
    _record(manifest, binding_path)
    binding = load_binding(binding_path)
    if Path(binding["export_manifest"]).resolve() != manifest.resolve():
        raise ValueError("completed binding must consume the explicitly selected provider")
    for key in ("source_field_manifest", "source_mph", "assembly_manifest", "collision_manifest"):
        if Path(completed[key]).resolve() != Path(expected[key]).resolve():
            raise ValueError(f"completed provider source differs: {key}")
    for key in ("active_mesh_tag", "source_dataset", "export_grid", "expected_tetrahedra",
                "expected_vacuum_domain_count"):
        if completed[key] != expected[key]:
            raise ValueError(f"completed provider source/grid differs: {key}")
    # compile_request already validates the sealed MPH record and actual file size;
    # inherit that record instead of opening or hashing the large model again.
    if any(completed["source_mph_record"][k] != expected["source_mph_record"][k]
           for k in ("bytes", "sha256")):
        raise ValueError("completed provider stored source MPH identity differs")
    source_authority_path = manifest.parent / "inputs" / "source_authority.json"
    _record(manifest, source_authority_path)
    if read(source_authority_path) != expected["source_authority"] or binding["geometry"] != expected["geometry"]:
        raise ValueError("completed provider source authority/geometry differs")
    for key in ("assembly_manifest", "collision_manifest"):
        if Path(binding[key]).resolve() != Path(expected[key]).resolve():
            raise ValueError(f"completed binding differs: {key}")
    grid_keys = ("origin_mm", "pitch_mm", "dimensions", "dataset_tag", "solution_tag")
    if (any(binding["grid"][k] != expected["export_grid"][k] for k in grid_keys)
            or binding["grid"].get("active_mesh_tag") != expected["active_mesh_tag"]):
        raise ValueError("completed binding base grid/mesh differs")
    windows, planned = binding.get("refinement_windows", []), completed.get("refinement_windows", [])
    if len(windows) != len(expected["refinement_windows"]) or len(planned) != len(windows):
        raise ValueError("completed provider ordered refinement windows differ")
    for window, frozen, wanted in zip(windows, planned, expected["refinement_windows"], strict=True):
        if any(window[k] != wanted[k] or frozen[k] != wanted[k] for k in ("name", "active_box_mm")):
            raise ValueError("completed provider refinement window name/order/box differs")
        local_manifest = Path(window["export_manifest"])
        _record(manifest, local_manifest)
        _, local_plan = _sealed_export_plan(local_manifest, window["grid"],
                                            Path(expected["source_mph"]), expected["source_dataset"])
        if (frozen["export_grid"] != wanted["export_grid"]
                or any(local_plan[k] != v for k, v in wanted["export_grid"].items())
                or local_plan["active_mesh_tag"] != expected["active_mesh_tag"]
                or window["grid"].get("active_mesh_tag") != expected["active_mesh_tag"]):
            raise ValueError("completed provider refinement window grid/mesh differs")
    fixed = {k:v for k,v in binding["authority"].items() if k != "analyzer_electrode_voltages_v"}
    if fixed != {k:v for k,v in expected["candidate_authority"].items() if k != "analyzer_electrode_voltages_v"}:
        raise ValueError("completed provider fixed voltage/assembly authority differs")
    voltages = binding["authority"]["analyzer_electrode_voltages_v"]
    if len(voltages) != 20 or any(not math.isfinite(float(v)) for v in voltages):
        raise ValueError("completed provider requires twenty finite analyzer voltages")
    return str(binding_path.resolve()) if binding["authority"] == expected["candidate_authority"] else None


TASK_SOURCE = native_resource_text("candidate_field.m")


def prepare(
    request_path: Path,
    run: Path,
    *,
    repository_root: Path,
    runner_path: Path,
) -> dict[str, Any]:
    """Freeze one explicit request, project runner and installed native closure."""
    plan = compile_request(read(request_path))
    if run.exists() or run.parent.name != "runs" or run.parent.parent.name != "parallel_mirror_dual_stripe_mr_tof":
        raise ValueError("prepare requires a new MR project run identity")
    root = run.parents[3]
    repository_root = repository_root.resolve(strict=True)
    plan.update(
        run_id=run.name,
        run_directory=str(run.resolve()),
        repo_root=str(repository_root),
    )
    sources = {"corridor_field.py": Path(__file__), "request.json": request_path,
               "source_model_manifest.json": Path(plan["source_field_manifest"]),
               "source_dataset_readback.json": Path(plan["source_field_manifest"]).parent / "results" / "dataset_readback.json",
               "simion_pa_save.m": Path(plan["writer"])}
    sources["source_export_plan.json"] = Path(plan["source_export_plan"])
    if plan["source_study_mesh_readback"]:
        sources["source_study_mesh_readback.json"] = Path(plan["source_study_mesh_readback"])
    sources.update({name: Path(path) for name, path in plan["mirror_reference_paths"].items()})
    sources["run_corridor_field_provider.ps1"] = runner_path.resolve(strict=True)
    for name in (
        "candidate_field.m",
        "update_corridor_workpoint_voltages.m",
        "export_corridor_scalar_field.m", "sample_scalar_grid_blocks.m",
        "classify_corridor_conductor_voltage.m",
    ):
        sources[name] = native_resource_path(name)
    run.mkdir()
    register_writing_range(root, run)
    inputs = run / "inputs"
    inputs.mkdir()
    code_root = inputs / "code"
    plan.update(matlab_resource_directory=str(inputs.resolve()),
                python_code_root=str(code_root.resolve()))
    for name, path in sources.items():
        shutil.copyfile(path, inputs / name)
    package_root = Path(__file__).resolve().parents[3]
    for source in sorted(package_root.joinpath("msplatform").rglob("*")):
        if not source.is_file() or source.suffix not in {".py", ".json", ".m"}:
            continue
        relative = source.relative_to(package_root)
        destination = code_root / "src" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        freeze_file(source, destination)
    for name, value in (("source_authority.json", plan.pop("source_authority")),
                        ("frozen_input.json", plan.pop("candidate_authority")),
                        ("resolved_geometry.json", plan.pop("geometry"))):
        write_json_atomic(inputs / name, value)
    write_json_atomic(inputs / "plan.json", plan)
    for window in plan["refinement_windows"]:
        receipt = run / window["receipt_directory"]
        local = receipt / "inputs"
        local.mkdir(parents=True)
        window["output_directory"] = str(local.resolve())
        for name in ("frozen_input.json", "resolved_geometry.json"):
            shutil.copyfile(inputs / name, local / name)
        local_plan = dict(window["export_grid"], source_mph=plan["source_mph"],
                          active_mesh_tag=plan["active_mesh_tag"],
                          source_field_manifest=plan["source_field_manifest"],
                          source_export_manifest=window["export_manifest"],
                          name=window["name"], active_box_mm=window["active_box_mm"])
        write_json_atomic(local / "plan.json", local_plan)
        write_json_atomic(inputs / f"{receipt.name}_source_export_plan.json",
                          read(Path(window["source_export_plan"])))
        write_json_atomic(inputs / f"{receipt.name}_source_export_manifest.json",
                          read(Path(window["export_manifest"])))
        # Nested export receipts share the parent run identity and lifecycle owner.
        write_json_atomic(receipt / "run_config.json", dict(schema_version=2,
            run_id=run.name, project=run.parent.parent.name, mode="same_mesh_ps_field_provider",
            formal_gate_passed=False, artifact_retention=plan["artifact_retention"],
            parameters=local_plan, inputs={p.name:str(p) for p in local.iterdir() if p.is_file()}))
    write_json_atomic(inputs / "plan.json", plan)
    config = dict(schema_version=2,run_id=run.name,project=run.parent.parent.name,
                  mode="same_mesh_ps_field_provider",formal_gate_passed=False,
                  artifact_retention=plan["artifact_retention"],parameters=plan,
                  capacity_ledger_lifecycle=dict(schema_version=1,enabled=True,artifact_root=str(root),
                                               light_evidence_budget_bytes=plan["artifact_budget_bytes"]),
                  inputs={p.relative_to(inputs).as_posix():str(p)
                          for p in inputs.rglob("*") if p.is_file()})
    write_json_atomic(run / "run_config.json", config)
    register_writing(root, run / "run_config.json")
    return {"run_directory": str(run), "status": "prepared_not_executed"}


def _window_completed(local: Path, window: dict[str, Any], plan: dict[str, Any],
                      authority: dict[str, Any], geometry: dict[str, Any]) -> bool:
    """Require the candidate window's frozen identity and complete scalar export."""
    required = ("result.json", "field_v.pa", "field_valid.pa", "frozen_input.json",
                "resolved_geometry.json", "plan.json")
    if not all((local / name).is_file() for name in required):
        return False
    result, frozen = read(local / "result.json"), read(local / "plan.json")
    grid = window["export_grid"]
    return (result.get("status") == "success" and result.get("field_units") == "V"
            and result.get("active_mesh_tag") == plan["active_mesh_tag"]
            and all(result.get(k) == grid[k] for k in
                    ("origin_mm", "pitch_mm", "dimensions", "dataset_tag", "solution_tag"))
            and all(frozen.get(k) == v for k, v in grid.items())
            and frozen.get("source_mph") == plan["source_mph"]
            and frozen.get("active_mesh_tag") == plan["active_mesh_tag"]
            and frozen.get("active_box_mm") == window["active_box_mm"]
            and read(local / "frozen_input.json") == authority
            and read(local / "resolved_geometry.json") == geometry)


def finalize(run: Path) -> dict[str, Any]:
    """Seal native outputs using the caller's existing retention/manifest policies."""
    inputs = run / "inputs"
    plan = read(inputs / "plan.json")
    usage = read(inputs / "provider_usage.json")
    result = read(inputs / "result.json") if (inputs / "result.json").is_file() else None
    success = (usage["outcome"] == "success" and result is not None and result.get("status") == "success"
               and all((inputs / name).is_file() for name in ("field_v.pa", "field_valid.pa")))
    windows = plan.get("refinement_windows", [])
    authority, geometry = read(inputs / "frozen_input.json"), read(inputs / "resolved_geometry.json")
    success = success and all(_window_completed(run / w["receipt_directory"] / "inputs", w,
                                               plan, authority, geometry) for w in windows)
    status = "success" if success else "interrupted" if usage["outcome"] == "interrupted" else "failed"
    if (run / "run_manifest.json").exists():
        raise ValueError("terminal provider identity cannot be overwritten")
    if success:
        for name in ("field_v.pa", "field_valid.pa"):
            (inputs / name).chmod(0o444)
        binding = dict(schema_version=1,
            role="mrtof_static_comsol_field_binding",export_manifest=str(run / "run_manifest.json"),
            assembly_manifest=plan["assembly_manifest"],collision_manifest=plan["collision_manifest"])
        if windows:
            binding["refinement_windows"] = [dict(name=w["name"], active_box_mm=w["active_box_mm"],
                export_manifest=str(run / w["receipt_directory"] / "run_manifest.json")) for w in windows]
        write_json_atomic(inputs / "field_binding.json", binding)
    summary = dict(status=status,result=result,usage=usage,formal_gate_passed=False,
                   field_binding=str(inputs / "field_binding.json") if success else None,
                   source_mph=plan["source_mph"],source_mph_not_copied_or_rehashed=True,
                   limitations=["Same-grid voltage synchronization, not field convergence or trajectory qualification."])
    config = run / "run_config.json"
    write_json_atomic(run / "summary.json", summary)
    retention = apply_retention(config)
    receipt_outputs = []
    for window in windows:
        receipt = run / window["receipt_directory"]
        local = receipt / "inputs"
        if success:
            for name in ("field_v.pa", "field_valid.pa"):
                (local / name).chmod(0o444)
        local_summary = dict(status=status, result=read(local / "result.json")
                             if (local / "result.json").is_file() else None,
                             parent_run=str(run), formal_gate_passed=False)
        local_manifest = build_run_manifest(receipt / "run_config.json", status,
            software=["COMSOL=6.4", "MATLAB=R2025b"],
            output_paths=[receipt / "summary.json", *[p for p in local.iterdir() if p.is_file()]],
            virtual_documents={receipt / "summary.json":local_summary})
        publish_terminal_state(receipt, local_summary, local_manifest)
        # Parent retention scans every nested payload. The child seals each PA once;
        # the parent freezes its receipt, not a second full read/hash of the same PA.
        receipt_outputs.extend([receipt / "run_config.json", receipt / "summary.json",
                                receipt / "run_manifest.json"])
    outputs = [run / "summary.json", retention, *[p for p in inputs.iterdir() if p.is_file()]]
    outputs.extend(receipt_outputs)
    manifest = build_run_manifest(config,status,software=["COMSOL=6.4","MATLAB=R2025b"],
                                  output_paths=outputs,virtual_documents={run / "summary.json":summary})
    publish_terminal_state(run,summary,manifest)
    record_capacity_object(run.parents[3],path=run,object_class="rebuildable_payload" if success else "light_evidence",
        bytes_count=sum(p.stat().st_size for p in run.rglob("*") if p.is_file()),status="ready",pin=success,
        pin_reason="Candidate scalar field consumers" if success else None,owner="mrtof-same-mesh-field-provider",
        retention_reason="solver_review while referenced",review_deadline=(datetime.now()+timedelta(days=7)).date().isoformat(),
        retirement_route="Governed retirement after consumers release")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request",type=Path)
    parser.add_argument("--run-directory",type=Path)
    parser.add_argument("--repository-root",type=Path)
    parser.add_argument("--runner-path",type=Path)
    parser.add_argument("--finalize",action="store_true")
    parser.add_argument("--resolve-completed-request",type=Path)
    parser.add_argument("--completed-provider-manifest",type=Path)
    args = parser.parse_args()
    if args.resolve_completed_request is not None or args.completed_provider_manifest is not None:
        if (args.resolve_completed_request is None or args.completed_provider_manifest is None
                or args.request is not None or args.run_directory is not None or args.finalize
                or args.repository_root is not None or args.runner_path is not None):
            parser.error("completed resolution requires only --resolve-completed-request and --completed-provider-manifest")
        print(json.dumps({"binding": resolve_completed_provider(read(args.resolve_completed_request),
                                                               args.completed_provider_manifest)}))
        return
    if args.run_directory is None:
        parser.error("prepare/finalize requires --run-directory")
    if not args.finalize and (args.request is None or args.repository_root is None or args.runner_path is None):
        parser.error("prepare requires --request, --repository-root and --runner-path")
    print(json.dumps(
        finalize(args.run_directory) if args.finalize else prepare(
            args.request,
            args.run_directory,
            repository_root=args.repository_root,
            runner_path=args.runner_path,
        )
    ))


if __name__ == "__main__":
    main()
