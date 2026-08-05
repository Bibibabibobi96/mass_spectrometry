"""Prepare one campaign-declared multipole-to-oaTOF execution."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from common.contracts.file_identity import file_sha256, repository_text_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from common.contracts.particle_count_policy import validate_standard_particle_count
from common.integration.adapter_contract import (
    load_execution_adapter_registry,
    resolve_execution_mapping,
)
from common.integration.resolve_connection import (
    derive_direct_mating_translation,
    load_connection_profile_registry,
    verify_composition_plan,
    write_resolved_and_plan,
)
from common.multipole.component_port import build_exit_component_port
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_layout import (
    compile_geometry_and_port,
    derive_pulse_schedule,
    select_profile,
)


INTEGRATION_ID = (
    "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)
UPSTREAM_PROJECTS = {
    "rf_quadrupole_ion_optics",
    "rf_hexapole_ion_optics",
    "rf_octupole_ion_optics",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ContractError(f"JSON object required: {path}")
    return value


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def _repo_record(root: Path, record: dict[str, str], label: str) -> Path:
    path = (root / record["path"]).resolve()
    if (
        not path.is_relative_to(root)
        or not path.is_file()
        or repository_text_sha256(path) != record["sha256"]
    ):
        raise ContractError(f"{label} is missing, stale or escapes the repository")
    return path


def _workspace_path(workspace: Path, raw: str, label: str) -> Path:
    value = Path(raw)
    path = value.resolve() if value.is_absolute() else (workspace / value).resolve()
    artifacts = (workspace / "artifacts").resolve()
    if not path.is_relative_to(artifacts) or not path.is_file():
        raise ContractError(f"{label} is missing or escapes workspace artifacts")
    return path


def _workspace_record(
    workspace: Path, record: dict[str, str], label: str
) -> Path:
    path = _workspace_path(workspace, record["path"], label)
    if file_sha256(path) != record["sha256"]:
        raise ContractError(f"{label} SHA-256 is stale")
    return path


def _workspace_relative(path: Path, workspace: Path) -> str:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError as exc:
        raise ContractError(f"path escapes the workspace: {path}") from exc


def _unique_profile(document: dict[str, Any], profile_id: str) -> dict[str, Any]:
    matches = [
        item
        for item in document["profiles"]
        if item["connection_profile_id"] == profile_id
    ]
    if len(matches) != 1:
        raise ContractError(f"connection profile is not unique: {profile_id}")
    return matches[0]


def _source_solver(manifest: dict[str, Any]) -> str:
    software = " ".join(str(item).lower() for item in manifest.get("software", []))
    matches = [name for name in ("comsol", "simion") if name in software]
    if len(matches) != 1:
        raise ContractError("source manifest solver identity is not unique")
    return matches[0]


def _verify_manifest_record(
    workspace: Path,
    record: dict[str, Any],
    expected_path: Path,
    expected_sha256: str,
    label: str,
) -> None:
    if not record.get("exists"):
        raise ContractError(f"source manifest {label} record is absent")
    path = _workspace_path(workspace, str(record["path"]), label)
    if path != expected_path.resolve() or record["sha256"] != expected_sha256:
        raise ContractError(f"source manifest {label} identity differs")


def _load_source_evidence(
    *,
    workspace: Path,
    experiment: dict[str, Any],
    expected_project_id: str,
) -> dict[str, Any]:
    source = experiment["source"]
    launched_count = validate_standard_particle_count(
        int(source["launched_particle_count"])
    )
    selected_count = int(source["particle_count"])
    if selected_count > launched_count:
        raise ContractError("selected source particle count exceeds launched count")
    manifest_path = _workspace_record(workspace, source["manifest"], "source manifest")
    state_path = _workspace_record(workspace, source["state"], "source state")
    particle_source_path = _workspace_record(
        workspace, source["particle_source"], "source particle table"
    )
    metadata_path = _workspace_record(workspace, source["metadata"], "source metadata")
    manifest = _load(manifest_path)
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("status") != "success"
        or manifest.get("run_id") != source["run_id"]
        or manifest.get("project") != expected_project_id
        or expected_project_id not in UPSTREAM_PROJECTS
    ):
        raise ContractError("source manifest run/project/status identity differs")
    source_role = source["particle_source_manifest_input_role"]
    _verify_manifest_record(
        workspace,
        manifest.get("inputs", {}).get(source_role, {}),
        particle_source_path,
        source["particle_source"]["sha256"],
        "particle source",
    )
    _verify_manifest_record(
        workspace,
        manifest.get("inputs", {}).get("particle_source_metadata", {}),
        metadata_path,
        source["metadata"]["sha256"],
        "particle source metadata",
    )
    matching_states = [
        record
        for record in manifest.get("outputs", [])
        if record.get("sha256") == source["state"]["sha256"]
    ]
    if len(matching_states) != 1:
        raise ContractError("source state is not uniquely frozen by its manifest")
    _verify_manifest_record(
        workspace,
        matching_states[0],
        state_path,
        source["state"]["sha256"],
        "source state",
    )
    design_record = manifest.get("inputs", {}).get("multipole_resolved_design", {})
    design_path = _workspace_path(
        workspace, str(design_record.get("path", "")), "source resolved design"
    )
    if (
        not design_record.get("exists")
        or file_sha256(design_path) != design_record.get("sha256")
    ):
        raise ContractError("source resolved design is absent or stale")
    resolved_design = _load(design_path)
    validate_schema(resolved_design, "multipole_resolved_design.schema.json")
    run_config_record = manifest.get("run_config", {})
    run_config_path = _workspace_path(
        workspace, str(run_config_record.get("path", "")), "source run config"
    )
    if (
        not run_config_record.get("exists")
        or file_sha256(run_config_path) != run_config_record.get("sha256")
    ):
        raise ContractError("source run config is absent or stale")
    run_config = _load(run_config_path)
    design_profile_id = run_config.get("parameters", {}).get("design_profile_id")
    if (
        not isinstance(design_profile_id, str)
        or not design_profile_id
        or resolved_design["identity"]["project_id"] != expected_project_id
    ):
        raise ContractError("source design profile/project identity differs")
    terminal = resolved_design.get("downstream_terminal")
    if (
        not isinstance(terminal, dict)
        or terminal.get("terminal_profile_id") != "oatof_shield_terminal"
        or terminal.get("surface_role") != "aperture_outer_tangent_plane"
        or float(terminal.get("rod_end_clearance_mm", -1.0)) != 1.0
        or terminal.get("upstream_terminal_electrode_present") is not False
    ):
        raise ContractError("source design does not freeze the governed oaTOF terminal")
    return {
        "source": source,
        "manifest": manifest,
        "state_path": state_path,
        "solver_id": _source_solver(manifest),
        "resolved_design": resolved_design,
        "resolved_design_path": design_path,
        "resolved_design_sha256": design_record["sha256"],
        "design_profile_id": design_profile_id,
        "launched_particle_count": launched_count,
        "particle_count": selected_count,
    }


def prepare_family_source_closure(
    *,
    repo_root: Path,
    profile_registry_path: Path,
    adapter_registry_path: Path,
    campaign_path: Path,
    experiment_id: str,
    resolved_output: Path,
    plan_output: Path,
) -> tuple[Path, Path]:
    root = repo_root.resolve()
    workspace = root.parent
    campaign_path = campaign_path.resolve()
    if not campaign_path.is_relative_to(root):
        raise ContractError("integration campaign must be repository-managed")
    campaign = _load(campaign_path)
    validate_schema(campaign, "rf_multipole_oatof_experiment_campaign.schema.json")
    if campaign["integration_id"] != INTEGRATION_ID:
        raise ContractError("campaign integration identity differs")
    identities = [item["experiment_id"] for item in campaign["experiments"]]
    sequences = [item["sequence"] for item in campaign["experiments"]]
    if len(identities) != len(set(identities)) or len(sequences) != len(set(sequences)):
        raise ContractError("campaign experiment IDs and sequences must be unique")
    matches = [item for item in campaign["experiments"] if item["experiment_id"] == experiment_id]
    if len(matches) != 1:
        raise ContractError("campaign experiment must resolve exactly once")
    experiment = matches[0]
    execution_strategy = experiment.get(
        "execution_strategy", "staged_three_stage"
    )
    profile_registry = load_connection_profile_registry(profile_registry_path)
    profile = _unique_profile(profile_registry, experiment["connection_profile_id"])
    expected_project_id = profile["upstream"]["project_id"]

    adapter_registry = load_execution_adapter_registry(adapter_registry_path)
    mapping = resolve_execution_mapping(
        adapter_registry, experiment["connection_profile_id"], repo_root=root
    )
    runtime_binding_record = {
        "path": mapping["runtime_binding_path"],
        "sha256": mapping["runtime_binding_sha256"],
    }
    runtime_binding_path = _repo_record(
        root, runtime_binding_record, "family runtime binding"
    )
    runtime_binding = _load(runtime_binding_path)
    validate_schema(runtime_binding, "rf_multipole_oatof_runtime_binding.schema.json")
    if (
        runtime_binding["schema_version"] != 3
        or runtime_binding["connection_profile_id"]
        != experiment["connection_profile_id"]
        or runtime_binding["upstream_project_id"] != expected_project_id
    ):
        raise ContractError("active family runtime binding identity differs")
    source_adapter_record = runtime_binding["contracts"]["source_adapter_contract"]
    source_adapter_path = _repo_record(
        root, source_adapter_record, "family source adapter"
    )
    source_adapter = _load(source_adapter_path)
    validate_schema(source_adapter, "rf_multipole_oatof_source_adapter.schema.json")
    policy_record = runtime_binding["contracts"]["execution_policy_contract"]
    if policy_record != campaign["execution_policy"]:
        raise ContractError("campaign and runtime execution policies differ")
    policy_path = _repo_record(root, policy_record, "integration execution policy")
    policy = _load(policy_path)
    validate_schema(policy, "rf_multipole_oatof_execution_policy.schema.json")

    evidence = _load_source_evidence(
        workspace=workspace,
        experiment=experiment,
        expected_project_id=expected_project_id,
    )
    source = evidence["source"]
    solver_id = evidence["solver_id"]
    if execution_strategy == "simion_single_flight" and solver_id != "simion":
        raise ContractError("SIMION single-flight execution requires a SIMION source run")
    handoff_publication_record = source.get(
        "handoff_publication_contract",
        runtime_binding["contracts"]["handoff_publication_contract"],
    )
    handoff_publication_path = _repo_record(
        root, handoff_publication_record, "handoff publication contract"
    )
    handoff_publication = _load(handoff_publication_path)
    if (
        handoff_publication.get("schema_version") != 1
        or handoff_publication.get("role")
        != "multipole_handoff_publication_contract"
        or handoff_publication.get("population", {}).get(
            "expected_source_particle_count"
        )
        != source["launched_particle_count"]
        or handoff_publication.get("canonical_state", {}).get(
            "source_component_id"
        )
        != expected_project_id
    ):
        raise ContractError(
            "handoff publication contract differs from the selected source population"
        )
    adapter = copy.deepcopy(source_adapter["adapter"])
    adapter["dependencies"] = {
        "handoff_publication_contract": handoff_publication_record
    }
    resolved_source = copy.deepcopy(source)
    resolved_source.pop("handoff_publication_contract", None)
    resolved_source_contract = {
        "schema_version": 2,
        "role": "rf_multipole_oatof_source_contract",
        "upstream_project_id": expected_project_id,
        "selector": copy.deepcopy(source_adapter["selector"]),
        "adapter": adapter,
        "canonical_state": copy.deepcopy(source_adapter["canonical_state"]),
        "source_branches": {
            solver_id: {
                "solver_id": solver_id,
                "recorded_project_id": expected_project_id,
                "source": resolved_source,
            }
        },
    }
    validate_schema(
        resolved_source_contract, "rf_multipole_oatof_source_contract.schema.json"
    )
    plan_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_source_contract_path = plan_output.with_name(
        "resolved_source_contract.json"
    )
    resolved_source_contract_path.write_text(
        json.dumps(resolved_source_contract, indent=2) + "\n", encoding="utf-8"
    )

    upstream_resolved_design_path = plan_output.with_name(
        "upstream_resolved_design.json"
    )
    shutil.copyfile(evidence["resolved_design_path"], upstream_resolved_design_path)
    if file_sha256(upstream_resolved_design_path) != evidence["resolved_design_sha256"]:
        raise ContractError("frozen upstream resolved design identity differs")

    upstream_port = build_exit_component_port(
        evidence["resolved_design"],
        design_profile_id=evidence["design_profile_id"],
        authority_path=_workspace_relative(upstream_resolved_design_path, workspace),
        authority_sha256=evidence["resolved_design_sha256"],
    )
    upstream_port_path = plan_output.with_name("resolved_upstream_port.json")
    upstream_port_path.write_text(
        json.dumps(upstream_port, indent=2) + "\n", encoding="utf-8"
    )
    resolved_registry = {
        "schema_version": profile_registry["schema_version"],
        "role": profile_registry["role"],
        "integration_id": profile_registry["integration_id"],
        "profiles": [copy.deepcopy(profile)],
    }
    resolved_upstream = resolved_registry["profiles"][0]["upstream"]
    if resolved_upstream.pop("port_binding", None) != "source_run_resolved_design":
        raise ContractError("upstream port is not runtime-bound to source design")
    resolved_upstream["port_contract"] = _workspace_relative(
        upstream_port_path, workspace
    )
    layout_files: dict[str, Path] | None = None
    if campaign["schema_version"] == 2:
        if execution_strategy != "simion_single_flight":
            raise ContractError("single-flight layout profiles require SIMION single flight")
        layout_registry_path = (
            root / "integrations" / INTEGRATION_ID / "config" /
            "single_flight_layout_profiles.json"
        )
        layout_profile = select_profile(
            _load(layout_registry_path), experiment["single_flight_layout_profile_id"]
        )
        base_geometry_path = (
            root / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json"
        )
        base_downstream_port_path = (root / profile["downstream"]["port_contract"]).resolve()
        geometry, downstream_port, _ = compile_geometry_and_port(
            _load(base_geometry_path), _load(base_downstream_port_path), layout_profile
        )
        geometry_path = plan_output.with_name("resolved_oatof_geometry.json")
        geometry_path.write_text(json.dumps(geometry, indent=2) + "\n", encoding="utf-8")
        downstream_port["authority"]["source_contract"] = _workspace_relative(
            geometry_path, workspace
        )
        downstream_port["authority"]["source_sha256"] = file_sha256(geometry_path)
        downstream_port_path = plan_output.with_name("resolved_downstream_port.json")
        downstream_port_path.write_text(
            json.dumps(downstream_port, indent=2) + "\n", encoding="utf-8"
        )
        validate_schema(downstream_port, "component_port.schema.json")
        resolved_registry["profiles"][0]["downstream"]["port_contract"] = (
            _workspace_relative(downstream_port_path, workspace)
        )
        registration = resolved_registry["profiles"][0]["spatial_registration"]
        registration["translation_mm"] = derive_direct_mating_translation(
            registration["rotation_upstream_to_downstream"],
            upstream_port["mating_surface"]["center_mm"],
            downstream_port["mating_surface"]["center_mm"],
        )
        layout_files = {
            "registry": layout_registry_path,
            "geometry": geometry_path,
            "downstream_port": downstream_port_path,
        }
    resolved_registry_path = plan_output.with_name(
        "resolved_connection_profile_registry.json"
    )
    resolved_registry_path.write_text(
        json.dumps(resolved_registry, indent=2) + "\n", encoding="utf-8"
    )

    source_identity = {
        "source_branch_id": solver_id,
        "solver_id": solver_id,
        "run_id": source["run_id"],
        "project_id": expected_project_id,
        "manifest_sha256": source["manifest"]["sha256"],
        "event_sha256": source["state"]["sha256"],
        "particle_source_sha256": source["particle_source"]["sha256"],
        "metadata_sha256": source["metadata"]["sha256"],
    }
    row_sha256 = _canonical_sha256(experiment)
    execution_particle_count = (
        evidence["launched_particle_count"]
        if execution_strategy == "simion_single_flight"
        else evidence["particle_count"]
    )
    resolved_budget = {
        "schema_version": 1,
        "role": "integration_resolved_engineering_budget",
        "integration_id": INTEGRATION_ID,
        "connection_profile_id": experiment["connection_profile_id"],
        "campaign_id": campaign["campaign_id"],
        "experiment_id": experiment_id,
        "experiment_row_sha256": row_sha256,
        "execution_strategy": execution_strategy,
        "policy_id": policy["policy_id"],
        "source_identity": source_identity,
        "launched_particle_count": evidence["launched_particle_count"],
        "particle_count": execution_particle_count,
        "retention_class": policy["retention_class"],
        "stage_limits": policy["stage_limits"],
        "budget_exhaustion_result": policy["budget_exhaustion_result"],
    }
    resolved_budget_path = plan_output.with_name("resolved_engineering_budget.json")
    resolved_budget_path.write_text(
        json.dumps(resolved_budget, indent=2) + "\n", encoding="utf-8"
    )

    resolved_path, plan_path = write_resolved_and_plan(
        resolved_registry_path,
        experiment["connection_profile_id"],
        resolved_output,
        plan_output,
        repo_root=root,
    )
    if layout_files is not None:
        schedule = derive_pulse_schedule(
            evidence["state_path"], _load(resolved_path), _load(layout_files["geometry"]),
            layout_profile,
        )
        schedule_path = plan_output.with_name("resolved_single_flight_pulse_schedule.json")
        schedule_path.write_text(json.dumps(schedule, indent=2) + "\n", encoding="utf-8")
        layout_files["schedule"] = schedule_path
    plan = _load(plan_path)
    plan["execution_steps"] = [
        {
            "step_id": "rf_to_oatof_transfer",
            "adapter": "powershell",
            "entrypoint": mapping["adapter_entrypoint"],
            "arguments": [
                f"adapter_registry_sha256={repository_text_sha256(adapter_registry_path)}",
                f"campaign_path={campaign_path.relative_to(root).as_posix()}",
                f"campaign_sha256={repository_text_sha256(campaign_path)}",
                f"campaign_id={campaign['campaign_id']}",
                f"experiment_id={experiment_id}",
                f"experiment_row_sha256={row_sha256}",
                f"execution_strategy={execution_strategy}",
                f"runtime_binding_path={runtime_binding_record['path']}",
                f"runtime_binding_sha256={runtime_binding_record['sha256']}",
                f"source_branch_id={solver_id}",
                "resolved_budget_filename=resolved_engineering_budget.json",
                f"resolved_budget_sha256={file_sha256(resolved_budget_path)}",
                "resolved_source_contract_filename=resolved_source_contract.json",
                f"resolved_source_contract_sha256={file_sha256(resolved_source_contract_path)}",
                "upstream_resolved_design_filename=upstream_resolved_design.json",
                "upstream_resolved_design_sha256="
                + evidence["resolved_design_sha256"],
            ] + ([] if layout_files is None else [
                f"layout_profile_id={experiment['single_flight_layout_profile_id']}",
                "resolved_oatof_geometry_filename=resolved_oatof_geometry.json",
                f"resolved_oatof_geometry_sha256={file_sha256(layout_files['geometry'])}",
                "resolved_single_flight_pulse_schedule_filename=resolved_single_flight_pulse_schedule.json",
                f"resolved_single_flight_pulse_schedule_sha256={file_sha256(layout_files['schedule'])}",
                f"single_flight_layout_registry_sha256={repository_text_sha256(layout_files['registry'])}",
            ]),
        }
    ]
    validate_schema(plan, "composition_plan.schema.json")
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    verify_composition_plan(plan_path, resolved_path, repo_root=root)
    return resolved_path, plan_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--profile-registry", required=True, type=Path)
    parser.add_argument("--adapter-registry", required=True, type=Path)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--resolved-output", required=True, type=Path)
    parser.add_argument("--plan-output", required=True, type=Path)
    args = parser.parse_args()
    resolved, plan = prepare_family_source_closure(
        repo_root=args.repo_root,
        profile_registry_path=args.profile_registry,
        adapter_registry_path=args.adapter_registry,
        campaign_path=args.campaign,
        experiment_id=args.experiment_id,
        resolved_output=args.resolved_output,
        plan_output=args.plan_output,
    )
    print(f"FAMILY_SOURCE_CLOSURE_PREPARE=PASS RESOLVED={resolved} PLAN={plan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
