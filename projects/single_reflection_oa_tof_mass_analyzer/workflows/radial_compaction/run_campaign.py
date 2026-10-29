"""Run the governed SIMION-only oaTOF radial-compaction campaign."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any



PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "radial_compaction_campaign.json"
BASELINE_PATH = PROJECT_ROOT / "config" / "baseline.json"
NUMERICS_PATH = PROJECT_ROOT / "config" / "formal_solver_numerics.json"
MODE_PATH = PROJECT_ROOT / "config" / "modes" / "formal.json"
CANDIDATE_RUNTIME_PATH = PROJECT_ROOT / "config" / "candidate_runtime.json"
ARTIFACT_ROOT = (
    WORKSPACE_ROOT
    / "artifacts"
    / "projects"
    / "single_reflection_oa_tof_mass_analyzer"
)
PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"

from common.contracts.artifact_naming import validate_run_id
from common.contracts.file_identity import canonical_json_sha256
from common.contracts.frozen_inputs import freeze_file
from common.contracts.machine_contracts import load_json, sha256
from common.contracts.particle_count_policy import validate_standard_particle_count
from common.contracts.recorded_file_removal import write_json_atomic
from common.contracts.verify_run_manifest import verify_record
from common.contracts.write_run_manifest import (
    TERMINAL_JOURNAL_NAME, file_record,
    require_completed_terminal_publication,
)
from common.host_resource_python import run_heavy_function, run_managed_python_process
from common.simion.batch_continuation import WholeUnitReplayUnit, build_whole_unit_replay_plan
from common.simion.native_completion import require_one_fly_completion
from common.simion.process_observation import run_observed_process
from common.simion.resource_profile import discover_case_resource_profiles
from common.simion.resource_scheduler import plan_simion_case_dispatch
from projects.single_reflection_oa_tof_mass_analyzer.analysis.compile_candidate_design import (
    compile_design_overrides,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.candidate_source_closure import (
    RELATIVE_PATHS, freeze_candidate_source_closure, frozen_source_path, verify_candidate_source_closure,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import (
    resolve_contract_documents,
    serialized,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.simion_component_pa_plan import (
    compile_component_pa_plan, sum_component_commitments,
)
from projects.single_reflection_oa_tof_mass_analyzer.workflows.radial_compaction import analysis
from projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.prepare_candidate_consumers import (
    prepare,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.prepare_candidate_run import (
    _registered_candidate_template, freeze_pa_producer_handoffs, plan_pa_producer_handoffs,
)


MODE_FLAGS = {
    "actual": (0, 0, 0),
    "ideal_stage1": (0, 1, 0),
    "ideal_stage2": (0, 0, 1),
    "ideal_reflectron": (0, 1, 1),
    "ideal_all": (1, 1, 1),
}
PROJECT_ID = "single_reflection_oa_tof_mass_analyzer"
RUN_ROLE = "oatof_radial_compaction_run_config"
PA_HANDOFF_RETENTION_REASON = "Explicit PA producer handoff output requested by radial campaign CLI"
FROZEN_INPUTS = (
    "campaign", "baseline", "solver_numerics", "mode", "reference_summary",
    "reference_particles",
    "candidate_runtime", "template_registration_config", "template_registration_summary",
    "template_registration_manifest", "template_registration_report", "template_iob", "template_con",
)
EXTRA_SOURCE_IDS = (
    "projects/single_reflection_oa_tof_mass_analyzer/workflows/radial_compaction/run_campaign.py",
    "projects/single_reflection_oa_tof_mass_analyzer/workflows/radial_compaction/analysis.py",
    "projects/single_reflection_oa_tof_mass_analyzer/analysis/compile_candidate_design.py",
    "common/contracts/frozen_inputs.py",
    "common/contracts/schemas/simion_batch_continuation.schema.json",
    "common/simion/batch_continuation.py",
    "common/simion/native_completion.py",
    "common/simion/resource_profile.py",
    "common/simion/resource_scheduler.py",
)
# These sources are consumed only after native Fly in this workflow. All other
# closure members, the driver, frozen inputs and solver/runtime remain bound.
ANALYSIS_ONLY_SOURCES = frozenset({
    "common/analysis/peak_metrics.py",
    "projects/single_reflection_oa_tof_mass_analyzer/analysis/solver_diagnostics.py",
    "projects/single_reflection_oa_tof_mass_analyzer/workflows/radial_compaction/analysis.py",
})


def _write_json(path: Path, document: Any) -> None:
    write_json_atomic(path, document)


def _same_flight_dependencies(current: dict[str, Any], parent: dict[str, Any]) -> bool:
    """Compare frozen inputs and all native dependencies, excluding pure analyzers."""
    if {k: v for k, v in current.items() if k != "sources"} != {
        k: v for k, v in parent.items() if k != "sources"
    }:
        return False
    current_sources, parent_sources = current["sources"], parent["sources"]
    if current_sources.keys() != parent_sources.keys():
        return False
    return all(current_sources[name] == parent_sources[name]
               for name in current_sources if name not in ANALYSIS_ONLY_SOURCES)


def _read_parent(parent: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Accept only a published predecessor, never a live or historical bare directory."""
    parent = parent.resolve(strict=True)
    require_completed_terminal_publication(parent / "run_manifest.json")
    manifest = load_json(parent / "run_manifest.json")
    config = load_json(parent / "run_config.json")
    summary = load_json(parent / "summary.json")
    if (
        config.get("role") != RUN_ROLE or config.get("recovery_protocol_version") != 1
        or config.get("project") != PROJECT_ID or config.get("run_id") != parent.name
        or manifest.get("role") != "simulation_run_manifest"
        or manifest.get("run_id") != parent.name or manifest.get("project") != PROJECT_ID
        or manifest.get("status") not in {"success", "failed", "interrupted"}
        or summary.get("role") != "oatof_radial_compaction_campaign_summary"
        or summary.get("run_id") != parent.name
        or summary.get("status") != manifest.get("status")
        or summary.get("writers_stopped") is not True
    ):
        raise ValueError("predecessor is not a published radial campaign with stopped writers")
    validate_run_id(parent.name)
    if Path(manifest["run_config"]["path"]).resolve() != parent / "run_config.json":
        raise ValueError("predecessor run_config path differs")
    verify_record("predecessor run_config", manifest["run_config"])
    bound = {Path(item["path"]).resolve(): item for item in manifest["outputs"]}
    summary_record = bound.get(parent / "summary.json")
    if summary_record is None:
        raise ValueError("predecessor summary is not manifest-bound")
    verify_record("predecessor summary", summary_record)
    for name in (*FROZEN_INPUTS, "recovery_context", "execution_source_closure"):
        record = manifest.get("inputs", {}).get(name)
        if not isinstance(record, dict) or Path(record["path"]).resolve() != Path(config["inputs"][name]).resolve():
            raise ValueError(f"predecessor frozen input is not bound: {name}")
        verify_record(f"predecessor {name}", record)
    verify_candidate_source_closure(load_json(Path(config["inputs"]["execution_source_closure"])))
    return config, summary, manifest


def _source_inputs(parent: Path | None, campaign_path: Path | None = None) -> tuple[Any, dict[str, Path]]:
    """Resolve scientific inputs without creating run artifacts."""
    if parent is not None and campaign_path is not None:
        raise ValueError("--resume-from cannot be combined with an explicit --campaign")
    parent_data = _read_parent(parent) if parent is not None else None
    if parent_data:
        source_paths = {name: Path(parent_data[0]["inputs"][name]) for name in FROZEN_INPUTS}
    else:
        campaign_path = Path(campaign_path or CONFIG_PATH).resolve(strict=True)
        campaign = load_json(campaign_path)
        reference_summary, reference_particles = _verify_authorities(campaign)
        source_paths = dict(zip(FROZEN_INPUTS[:6], (
            campaign_path, BASELINE_PATH, NUMERICS_PATH, MODE_PATH,
            reference_summary, reference_particles,
        )))
    campaign = load_json(source_paths["campaign"])
    if (campaign.get("schema_version") != 1
            or campaign.get("role") != "oatof_simion_radial_compaction_campaign"
            or campaign.get("status") != "authorized"):
        raise ValueError("radial-compaction campaign is not an active authorized execution contract")
    if parent_data is None:
        runtime = load_json(CANDIDATE_RUNTIME_PATH)
        if runtime.get("role") != "oa_tof_candidate_runtime":
            raise ValueError("candidate runtime config has an unsupported role")
        template_id = str(runtime.get("simion_template_run_id", ""))
        validate_run_id(template_id)
        registration = _registered_candidate_template(ARTIFACT_ROOT / "runs" / template_id, ARTIFACT_ROOT)
        template = registration["registration_run"]
        source_paths.update({
            "candidate_runtime": CANDIDATE_RUNTIME_PATH,
            "template_registration_config": template / "run_config.json",
            "template_registration_summary": template / "summary.json",
            "template_registration_manifest": registration["registration_manifest"],
            "template_registration_report": template / "simion_layout_runtime_report.txt",
            "template_iob": registration["source_iob"], "template_con": registration["source_con"],
        })
    cases = campaign["radius_screen"] + campaign["ring_count_compensation"]["cases"]
    case_ids = [case["case_id"] for case in cases]
    if (not campaign["radius_screen"] or len(case_ids) != len(set(case_ids))
            or any(not isinstance(key, str) or re.fullmatch(r"[a-z][a-z0-9_]*", key) is None for key in case_ids)):
        raise ValueError("radial campaign requires unique safe case identifiers and a nonempty radius screen")
    validate_standard_particle_count(campaign["fixed_contract"]["particle_count"])
    if any(mode not in MODE_FLAGS for mode in campaign["ideal_field_attribution"]["modes"]):
        raise ValueError("radial campaign requested an unknown existing field diagnostic mode")
    return parent_data, source_paths


def _prepare_execution_request(
    run_id: str, simion_exe: Path, parent: Path | None, dry_run: bool,
    campaign_path: Path | None = None,
    *, pa_producer_handoffs: list[tuple[Path, Path]] | None = None,
    pa_handoff_output: Path | None = None,
) -> dict[str, Any]:
    """Compile every potential case's public PA commitment before creating a run."""
    validate_run_id(run_id)
    if (ARTIFACT_ROOT / "runs" / run_id).exists():
        raise ValueError(f"run output already exists: {ARTIFACT_ROOT / 'runs' / run_id}")
    if dry_run and (pa_producer_handoffs or pa_handoff_output is not None):
        raise ValueError("PA handoff options cannot be combined with --dry-run")
    if pa_handoff_output is not None:
        pa_handoff_output = pa_handoff_output.resolve()
        if pa_handoff_output.is_relative_to((ARTIFACT_ROOT / "runs").resolve()) or pa_handoff_output.exists():
            raise ValueError("PA handoff output must be a new file outside project runs")
        if not pa_handoff_output.parent.is_dir():
            raise ValueError("PA handoff output requires an existing parent directory")
    parent_data, sources = _source_inputs(parent, campaign_path)
    science_bytes = {name: sources[name].read_bytes() for name in (
        "campaign", "baseline", "solver_numerics", "mode",
    )}
    campaign, baseline, numerics, mode = [json.loads(science_bytes[name].decode("utf-8-sig"))
                                        for name in science_bytes]
    target = next(row for row in campaign["radius_screen"]
                  if row["case_id"] == campaign["ring_count_compensation"]["target_case_id"])
    cases = campaign["radius_screen"] + [
        {**target, **row} for row in campaign["ring_count_compensation"]["cases"]
    ]
    input_identity = {name: (hashlib.sha256(science_bytes[name]).hexdigest().upper()
                            if name in science_bytes else sha256(path))
                      for name, path in sources.items()}
    source_identity = {name: sha256(REPO_ROOT / name) for name in dict.fromkeys((*RELATIVE_PATHS, *EXTRA_SOURCE_IDS))}
    plans = {}
    for case in cases:
        _, _, resolved = _compile_case_contract(
            case, baseline, numerics, mode, input_identity["mode"],
            campaign["fixed_contract"]["default_reflectron_mesh_mm"],
        )
        plans[case["case_id"]] = compile_component_pa_plan(
            resolved, repository_root=REPO_ROOT, simion_exe=simion_exe,
        )
    if any(sha256(sources[name]) != digest for name, digest in input_identity.items()):
        raise ValueError("scientific inputs changed during capacity planning")
    cache_keys = {component["cache_key"] for plan in plans.values()
                  for component in plan["components"] if component["cacheable"]}
    handoff_plan = (plan_pa_producer_handoffs(pa_producer_handoffs, expected_cache_keys=cache_keys,
                                            artifact_root=ARTIFACT_ROOT.parents[1])
                    if pa_producer_handoffs else None)
    dependencies = {parent.resolve()} if parent else set()
    if handoff_plan:
        dependencies.update(Path(path) for path in handoff_plan["protected_paths"])
    # Protect both registered template owners while freezing and any ancestors
    # providing completed units. Never infer an owner from a latest-run search.
    run_base = (ARTIFACT_ROOT / "runs").resolve()
    dependency_inputs = [*sources.values(), *(parent_data[0]["inputs"].values() if parent_data else [])]
    for value in dependency_inputs:
        try:
            relative = Path(value).resolve().relative_to(run_base)
        except ValueError:
            continue
        dependencies.add(run_base / relative.parts[0])
    return {
        "schema_version": 1, "role": "oatof_radial_compaction_execution_request",
        "run_id": run_id, "project": PROJECT_ID,
        "repository_root": str(REPO_ROOT), "artifact_project_root": str(ARTIFACT_ROOT),
        "python_executable": str(Path(sys.executable).resolve()), "simion_exe": str(simion_exe),
        "parent_run_dir": str(parent) if parent else None,
        "campaign_path": None if parent else str(sources["campaign"]), "dry_run": dry_run,
        "scientific_input_sha256": input_identity, "source_sha256": source_identity,
        "input_paths": {name: str(path) for name, path in sources.items()},
        "component_plans": plans, "committed_new_bytes": sum_component_commitments(plans.values()),
        "protected_cache_keys": sorted(cache_keys),
        "dependency_run_dirs": [str(path) for path in sorted(dependencies)],
        "pa_producer_handoffs": handoff_plan,
        "pa_handoff_output": str(pa_handoff_output) if pa_handoff_output is not None else None,
    }


def _freeze_run(
    run_root: Path, simion_exe: Path, parent: Path | None, *,
    initialized_config: dict[str, Any] | None = None,
    capacity_session_path: Path | None = None,
    campaign_path: Path | None = None,
    execution_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze inputs into the owner's initialized package, or a new isolated fixture."""
    if initialized_config is None and run_root.exists():
        raise ValueError(f"run output already exists: {run_root}")
    parent_data, source_paths = _source_inputs(parent, campaign_path)
    context = {
        "schema_version": 1, "role": "oatof_radial_compaction_recovery_context",
        "inputs": {name: sha256(path) for name, path in source_paths.items()},
        "campaign_driver_sha256": sha256(Path(__file__)), "simion_sha256": sha256(simion_exe),
        "python_sha256": sha256(Path(sys.executable)),
    }
    if execution_request is not None and context["inputs"] != execution_request["scientific_input_sha256"]:
        raise ValueError("scientific inputs changed after capacity planning")
    inputs = run_root / "inputs"
    inputs.mkdir(parents=True, exist_ok=initialized_config is not None)
    declared = dict((initialized_config or {}).get("inputs", {}))
    for name, source in source_paths.items():
        target = inputs / "template" / source.name if name in {"template_iob", "template_con"} else inputs / f"{name}{source.suffix}"
        target.parent.mkdir(parents=True, exist_ok=True)
        frozen = freeze_file(source, target)
        if frozen["sha256"] != context["inputs"][name]:
            raise ValueError(f"scientific input changed while freezing: {name}")
        declared[name] = str(target)
    closure = freeze_candidate_source_closure(
        inputs / "code", ARTIFACT_ROOT, Path(sys.executable), extra_source_ids=EXTRA_SOURCE_IDS,
    )
    context["sources"] = {row["source_id"]: row["source_sha256"] for row in closure["sources"]}
    if execution_request is not None and context["sources"] != execution_request["source_sha256"]:
        raise ValueError("execution sources changed after capacity planning")
    if parent_data and not _same_flight_dependencies(context, load_json(Path(parent_data[0]["inputs"]["recovery_context"]))):
        raise ValueError("predecessor frozen execution identity differs; continuation is refused")
    for index, source in enumerate(closure["sources"]):
        declared[f"source_{index:03d}"] = frozen_source_path(closure, source["source_id"])
    closure_path = inputs / "execution_source_closure.json"
    _write_json(closure_path, closure)
    declared["execution_source_closure"] = str(closure_path)
    context_path = inputs / "recovery_context.json"
    _write_json(context_path, context)
    declared["recovery_context"] = str(context_path)
    if execution_request is not None:
        for case_id, plan in execution_request["component_plans"].items():
            plan_path = inputs / f"component_plan_{case_id}.json"
            _write_json(plan_path, plan)
            declared[f"component_plan_{case_id}"] = str(plan_path)
    handoff = None
    if execution_request is not None and execution_request.get("pa_producer_handoffs"):
        handoff = freeze_pa_producer_handoffs(
            run_root, execution_request["pa_producer_handoffs"],
            expected_cache_keys=set(execution_request["protected_cache_keys"]),
            capacity_session=load_json(capacity_session_path),
        )
        declared["pa_producer_handoffs"] = handoff["path"]
        for index, record in enumerate(handoff["frozen_input_records"]):
            if record["path"] != handoff["path"]:
                declared[f"pa_producer_handoff_{index:03d}"] = record["path"]
    config = {
        **(initialized_config or {}),
        "schema_version": 2, "role": RUN_ROLE, "recovery_protocol_version": 1,
        "run_id": run_root.name, "project": PROJECT_ID,
        "mode": "simion_radial_compaction", "inputs": declared,
        "context_sha256": canonical_json_sha256(context),
        "parent_run_id": parent.name if parent is not None else None,
        "artifact_retention": copy.deepcopy((initialized_config or {}).get(
            "artifact_retention", {"policy_version": 1, "class": "compact", "reason": None})),
    }
    if handoff is not None:
        config["pa_producer_handoffs"] = {key: handoff[key] for key in ("path", "exists", "bytes", "sha256")}
    if capacity_session_path is not None:
        config["capacity_session_path"] = str(capacity_session_path)
        config["parameters"] = {"lifecycle_stage": "inputs_frozen"}
    _write_json(run_root / "run_config.json", config)
    _write_json(run_root / "summary.json", {
        "status": "running", "run_id": run_root.name, "writers_stopped": False,
    })
    return config


def _validate_prepared_run(
    run_config_path: Path, capacity_session_path: Path, execution_request_path: Path | None = None,
) -> dict[str, Any]:
    """Check the public package checkpoint and the owner's actual session identity."""
    run_config_path = run_config_path.resolve(strict=True)
    run_root = run_config_path.parent
    initial = load_json(run_config_path)
    expected_inputs = ({"execution_request": str(execution_request_path.resolve(strict=True))}
                       if execution_request_path is not None else {})
    if execution_request_path is not None and execution_request_path.resolve() != run_root / "inputs" / "execution_request.json":
        raise ValueError("prepared execution request must be the owner's frozen run input")
    retain_handoff = (execution_request_path is not None
                      and bool(load_json(execution_request_path).get("payload", {}).get("pa_handoff_output")))
    validate_run_id(run_root.name)
    if (
        run_config_path.name != "run_config.json"
        or run_root != (ARTIFACT_ROOT / "runs" / run_root.name).resolve()
        or initial.get("schema_version") != 2
        or initial.get("project") != PROJECT_ID or initial.get("run_id") != run_root.name
        or initial.get("inputs") != expected_inputs
        or initial.get("parameters", {}).get("lifecycle_stage") != "run_package_initialized"
        or initial.get("artifact_retention", {}).get("class") != ("solver_review" if retain_handoff else "compact")
        or (retain_handoff and initial["artifact_retention"].get("reason") != PA_HANDOFF_RETENTION_REASON)
        or initial.get("capacity_ledger_lifecycle", {}).get("enabled") is not True
    ):
        raise ValueError("radial execution requires a fresh public run package with capacity lifecycle")
    require_completed_terminal_publication(run_root / "run_manifest.json")
    manifest = load_json(run_root / "run_manifest.json")
    summary = load_json(run_root / "summary.json")
    if (
        manifest.get("status") != "checkpoint" or manifest.get("run_id") != run_root.name
        or manifest.get("project") != PROJECT_ID or manifest.get("role") != "simulation_run_manifest"
        or summary.get("role") != "run_package_initialization_summary"
        or summary.get("status") != "checkpoint"
        or Path(manifest["run_config"]["path"]).resolve() != run_config_path
    ):
        raise ValueError("radial package initialization checkpoint differs")
    verify_record("initialized run_config", manifest["run_config"])
    if execution_request_path is not None:
        request_record = manifest.get("inputs", {}).get("execution_request")
        if not isinstance(request_record, dict) or Path(request_record["path"]).resolve() != execution_request_path.resolve():
            raise ValueError("admitted execution request is not manifest-bound")
        verify_record("admitted execution request", request_record)
    bound_summary = [record for record in manifest["outputs"]
                     if Path(record["path"]).resolve() == run_root / "summary.json"]
    if len(bound_summary) != 1:
        raise ValueError("initialized summary is not uniquely manifest-bound")
    verify_record("initialized summary", bound_summary[0])
    session = load_json(capacity_session_path.resolve(strict=True))
    if (
        session.get("schema_version") != 1 or session.get("role") != "artifact_workflow_capacity_session"
        or session.get("status") != "active" or not session.get("lease_id")
        or run_root not in {Path(path).resolve() for path in session.get("protected_paths", [])}
        or Path(session["artifact_root"]).resolve()
        != Path(initial["capacity_ledger_lifecycle"]["artifact_root"]).resolve()
    ):
        raise ValueError("radial run is not protected by the supplied active capacity session")
    return initial


def _plan_replay(run_root: Path, parent: Path, config: dict[str, Any]) -> None:
    """Let the common planner select only published complete native Fly units."""
    parent_config, summary, _ = _read_parent(parent)
    campaign = load_json(Path(config["inputs"]["campaign"]))
    case_ids = {row["case_id"] for row in (
        campaign["radius_screen"] + campaign["ring_count_compensation"]["cases"]
    )}
    records = summary.get("native_units", {})
    units = []
    for case_id in sorted(case_ids):
        for mode in MODE_FLAGS:
            key = f"{case_id}.{mode}"
            record = records.get(key)
            complete = (isinstance(record, dict)
                        and type(record.get("native_returncode")) is int
                        and record["native_returncode"] == 0
                        and record.get("native_splats") == campaign["fixed_contract"]["particle_count"])
            if complete and (
                record.get("case_id") != case_id or record.get("mode") != mode
                or record.get("context_sha256") != parent_config["context_sha256"]
                or record.get("role") != "oatof_radial_compaction_native_unit"
            ):
                raise ValueError(f"predecessor native unit identity differs: {key}")
            paths = tuple(Path(record[name]) for name in ("receipt", "stdout", "stderr", "ion")) if complete else (Path("uncompleted-native-unit"),)
            units.append(WholeUnitReplayUnit(key, paths, complete))
    plan = build_whole_unit_replay_plan(
        predecessor_run_dir=parent, output_dir=run_root / "inputs", units=units,
    )
    config["inputs"]["continuation_plan"] = str(run_root / "inputs" / "simion_whole_unit_replay_plan.json")
    config["continuation_parent_context_sha256"] = parent_config["context_sha256"]
    config["continuation_units"] = {}
    for unit in plan["units"]:
        if unit["action"] != "reuse":
            continue
        record = records[unit["key"]]
        native = load_json(Path(record["receipt"]))
        if any(native.get(name) != record.get(name) for name in (
            "case_id", "mode", "context_sha256", "native_returncode", "stdout", "stderr", "ion",
            "native_splats",
        )):
            raise ValueError(f"predecessor native receipt differs: {unit['key']}")
        config["continuation_units"][unit["key"]] = record["receipt"]
        for artifact in unit["terminal_outputs"]:
            config["inputs"][f"reused_{len(config['inputs']):04d}"] = artifact["path"]
    _write_json(run_root / "run_config.json", config)


def _campaign_outputs(
    run_root: Path, summary: dict[str, Any],
) -> tuple[list[str], list[str]]:
    """Describe scientific outputs for the sole public lifecycle publisher."""
    config_path = run_root / "run_config.json"
    native_units = {}
    for receipt in sorted(run_root.glob("cases/*/results/*_native.json")):
        native = load_json(receipt)
        if (native.get("role") == "oatof_radial_compaction_native_unit"
                and type(native.get("native_returncode")) is int
                and native["native_returncode"] == 0):
            native_units[f"{native['case_id']}.{native['mode']}"] = {
                **native, "receipt": str(receipt),
            }
    summary.update(run_id=run_root.name, native_units=native_units)
    native_paths = {Path(unit[name]).resolve() for unit in native_units.values()
                    for name in ("receipt", "stdout", "stderr", "ion")}
    for path in native_paths:
        if not path.is_file():
            raise ValueError(f"completed native unit output is missing: {path}")
    inputs = {Path(value).resolve() for value in load_json(config_path)["inputs"].values()}
    outputs = [path for path in run_root.rglob("*") if path.is_file()
               and path.resolve() not in inputs
               and path.name not in {"run_manifest.json", "run_config.json", TERMINAL_JOURNAL_NAME}]
    return [str(path) for path in outputs], [str(path) for path in sorted(native_paths)]


def _record_phase(run_root: Path, stage: str) -> None:
    _write_json(run_root / "summary.json", {
        "status": "running", "run_id": run_root.name, "active_stage": stage,
        "writers_stopped": False,
    })


def _verify_authorities(config: dict[str, Any]) -> tuple[Path, Path]:
    for key, path in (("baseline", BASELINE_PATH), ("solver_numerics", NUMERICS_PATH)):
        if sha256(path) != config["authorities"][key]["sha256"]:
            raise ValueError(f"radial campaign authority is stale: {key}")
    reference = config["authorities"]["reference_result"]
    reference_root = ARTIFACT_ROOT / "runs" / reference["run_id"]
    summary = reference_root / reference["relative_path"]
    particles = reference_root / reference["particle_relative_path"]
    if sha256(summary) != reference["sha256"]:
        raise ValueError("radial campaign reference summary changed")
    if sha256(particles) != reference["particle_sha256"]:
        raise ValueError("radial campaign reference particle table changed")
    return summary, particles


def _assert_only_allowed_changes(
    baseline: dict[str, Any], candidate: dict[str, Any], *, allow_ring_counts: bool,
    allowed_geometry_keys: set[str] | None = None,
) -> None:
    left, right = copy.deepcopy(baseline), copy.deepcopy(candidate)
    allowed_geometry_keys = allowed_geometry_keys or set()
    for document in (left, right):
        geometry = document["geometry_mm"]
        for key in {"bore_r", "ring_outer_r", "flight_tube_r"} | allowed_geometry_keys:
            geometry.pop(key)
        if allow_ring_counts:
            document["rings"].pop("stage1_count")
            document["rings"].pop("stage2_count")
        # This is a generated accelerator-envelope coordinate.  Older baseline
        # contracts predate the field; candidate compilation now materializes
        # it without changing any radial-compaction design freedom.
        document.get("geometry_derivation", {}).get("accelerator", {}).pop(
            "outer_envelope_min_z_mm", None
        )
    if left != right:
        raise ValueError("candidate changed a non-authorized geometry, source, voltage or solver value")


def _overrides(case: dict[str, Any]) -> list[dict[str, Any]]:
    values = [
        ("reflectron_bore_radius", case["bore_radius_mm"], "mm"),
        ("reflectron_ring_outer_radius", case["ring_outer_radius_mm"], "mm"),
        (
            "reflectron_shield_inner_radius",
            case["shared_shield_inner_radius_mm"],
            "mm",
        ),
    ]
    if "stage1_count" in case:
        values.extend(
            [
                ("reflectron_stage1_electrode_count", case["stage1_count"], "count"),
                ("reflectron_stage2_electrode_count", case["stage2_count"], "count"),
            ]
        )
    if "ring_thickness_mm" in case:
        values.append(
            ("reflectron_ring_thickness", case["ring_thickness_mm"], "mm")
        )
    return [
        {"variable": variable, "value": value, "unit": unit}
        for variable, value, unit in values
    ]


def _compile_case_contract(
    case: dict[str, Any], baseline: dict[str, Any], numerics: dict[str, Any],
    mode: dict[str, Any], mode_sha256: str, default_mesh: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Share the same governed case compilation before admission and execution."""
    candidate, _ = compile_design_overrides(baseline, _overrides(case))
    _assert_only_allowed_changes(
        baseline, candidate, allow_ring_counts="stage1_count" in case,
        allowed_geometry_keys={
            "ring_thickness", "shield_bore_z_max", "shield_outer_z_max"
        }
        if "ring_thickness_mm" in case else set(),
    )
    numerics = copy.deepcopy(numerics)
    numerics["simion"]["geometry_build"]["reflectron"]["cell_axial_mm"] = float(
        default_mesh["axial"]
    )
    numerics["simion"]["geometry_build"]["reflectron"]["cell_radial_mm"] = float(
        default_mesh["radial"]
    )
    if "reflectron_cell_axial_mm" in case:
        numerics["simion"]["geometry_build"]["reflectron"]["cell_axial_mm"] = float(
            case["reflectron_cell_axial_mm"]
        )
    resolved = resolve_contract_documents(candidate, mode, numerics, input_identity={
        "baseline": "run_input:candidate_baseline.json",
        "baseline_sha256": hashlib.sha256(serialized(candidate).encode("utf-8")).hexdigest().upper(),
        "mode": "run_input:candidate_science_mode.json", "mode_sha256": mode_sha256,
        "solver_numerics": "run_input:candidate_solver_numerics.json",
        "solver_numerics_sha256": hashlib.sha256(serialized(numerics).encode("utf-8")).hexdigest().upper(),
    })
    return candidate, numerics, resolved


def _prepare_case(
    case: dict[str, Any], run_root: Path, baseline: dict[str, Any], seed: int,
    default_mesh: dict[str, Any],
) -> dict[str, Any]:
    case_root = run_root / "cases" / case["case_id"]
    contracts = case_root / "contracts"
    baseline_path = contracts / "candidate_baseline.json"
    resolved_path = contracts / "candidate_resolved_geometry.json"
    numerics_path = contracts / "candidate_solver_numerics.json"
    if case_root.exists():
        raise ValueError(f"case output already exists; use a new run identity: {case_root}")
    run_config_path = run_root / "run_config.json"
    run_config = load_json(run_config_path) if run_config_path.is_file() else {}
    frozen = run_config.get("inputs", {})
    mode_path = Path(frozen.get("mode", MODE_PATH))
    candidate, numerics, resolved = _compile_case_contract(
        case, baseline, load_json(Path(frozen.get("solver_numerics", NUMERICS_PATH))),
        load_json(mode_path), sha256(mode_path), default_mesh,
    )
    contracts.mkdir(parents=True)
    _write_json(baseline_path, candidate)
    _write_json(numerics_path, numerics)
    resolved_path.write_text(serialized(resolved), encoding="utf-8")
    prepared = case_root / "prepared"
    prepare(resolved_path, prepared, particle_source_seed=seed)
    return {
        **case,
        "case_root": case_root,
        "baseline_path": baseline_path,
        "resolved_path": resolved_path,
        "text_dir": prepared / "simion",
        "simion_dir": case_root / "simion",
        "run_id": run_root.name,
        "context_sha256": run_config.get("context_sha256"),
        "continuation_parent_context_sha256": run_config.get("continuation_parent_context_sha256"),
        "capacity_session_path": run_config.get("capacity_session_path"),
        "component_plan_path": frozen.get(f"component_plan_{case['case_id']}"),
        "replay_units": {
            mode: Path(receipt) for key, receipt in run_config.get("continuation_units", {}).items()
            for case_id, mode in [key.rsplit(".", 1)] if case_id == case["case_id"]
        },
        "pa_build_seconds": None,
    }


def _observe_operation(
    command: list[str], *, cwd: Path, stdout: Path, stderr: Path,
    receipt_path: Path, operation_id: str, resource_release_id: str | None,
    warning_seconds: float | None = None,
) -> tuple[Any, int | None]:
    """Record actual process observations for the public owner's final proof check."""
    receipt = {"schema_version": 1, "role": "oatof_execution_observation",
               "operation": {"operation_id": operation_id,
                             "observation": {"exit_confirmed": False, "returncode": None},
                             "resource_release_id": resource_release_id}}
    _write_json(receipt_path, receipt)
    try:
        result, peak = run_observed_process(command, cwd=cwd, stdout=stdout, stderr=stderr,
                                            warning_seconds=warning_seconds)
    except BaseException as failure:
        receipt["operation"]["observation"] = {
            "exit_confirmed": getattr(failure, "observed_process_exit_confirmed", False) is True,
            "returncode": getattr(failure, "observed_process_returncode", None),
        }
        try:
            _write_json(receipt_path, receipt)
        except BaseException as recording_error:
            failure.add_note(f"Process observation recording failed: {recording_error}")
        raise
    receipt["operation"]["observation"] = {"exit_confirmed": True, "returncode": result.returncode}
    _write_json(receipt_path, receipt)
    return result, peak


def _managed_process_observation(receipt: Any) -> dict[str, Any]:
    """Project a recorded actual-worker proof without replacing native facts."""
    record = receipt if isinstance(receipt, dict) else {}
    code = record.get("exit_code")
    confirmed = (
        type(record.get("schema_version")) is int and record["schema_version"] == 1
        and record.get("role") == "repository_managed_python_completion"
        and all(record.get(key) is True for key in (
            "ownership_confirmed", "worker_exit_confirmed", "launcher_exit_confirmed",
            "stdout_drained", "stderr_drained",
        ))
        and all(type(record.get(key)) is int and record[key] > 0 for key in (
            "launcher_process_id", "worker_process_id", "worker_started_at_utc_ticks",
        ))
        and type(code) is int
    )
    return {"exit_confirmed": confirmed, "returncode": code if type(code) is int else None}


def _builder_writer_operations(build: dict[str, Any], case_id: str) -> list[dict[str, Any]]:
    """Keep operation and actual helper facts separate under the same owner."""
    operations = []
    for item in build["operations"]:
        prefix = f"{case_id}.{item['operation_id']}"
        process = item["observation"]
        for suffix, observation in (
            ("process", {key: process.get(key) for key in ("exit_confirmed", "returncode")}),
            ("worker", _managed_process_observation(item.get("managed_process_completion"))),
        ):
            operations.append({"operation_id": f"{prefix}.{suffix}", "observation": observation,
                               "resource_release_id": f"build:{case_id}"})
    return operations


def _build_case(
    case: dict[str, Any], *, simion_exe: Path, template_iob: Path,
    seed: int, run_id: str, particle_count: int,
) -> None:
    if case.get("build_complete") is True:
        return
    run_config = load_json(case["case_root"].parents[1] / "run_config.json")
    builder = Path(frozen_source_path(
        load_json(Path(run_config["inputs"]["execution_source_closure"])),
        "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/build_formal_delivery.ps1",
    ))
    logs = case["case_root"] / "logs"
    command = [
        "pwsh.exe", "-NoProfile", "-File", str(builder),
        "-SimionExe", str(simion_exe),
        "-OutputDir", str(case["simion_dir"]),
        "-ArtifactProjectRoot", str(ARTIFACT_ROOT),
        "-TemplateIob", str(template_iob),
        "-RunId", run_id,
        "-ContractPath", str(case["resolved_path"]),
        "-CandidateBaselinePath", str(case["baseline_path"]),
        "-CandidateTextDir", str(case["text_dir"]),
        "-CapacitySessionPath", str(case["capacity_session_path"]),
        "-ContextSha256", case["context_sha256"],
        "-ComponentPlanPath", str(case["component_plan_path"]),
        "-ParticleCount", str(particle_count),
        "-CompletionPath", str(logs / "build_completion.json"),
        "-ParticleSeed", str(seed),
        "-DeferRunFinalization",
    ]
    if handoff_path := run_config["inputs"].get("pa_producer_handoffs"):
        command.extend(["-ProducerHandoffPath", handoff_path])
    started = time.perf_counter()
    completed, _ = _observe_operation(
        command, cwd=REPO_ROOT, stdout=logs / "pa_build.log", stderr=logs / "pa_build.stderr.log",
        receipt_path=case["case_root"] / "results/build_operation.json",
        operation_id=f"{case['case_id']}.build", resource_release_id=f"build:{case['case_id']}",
        warning_seconds=1800,
    )
    case["pa_build_seconds"] = time.perf_counter() - started
    if completed.returncode:
        raise RuntimeError(f"PA build failed ({completed.returncode}); see {logs / 'pa_build.stderr.log'}")
    build = load_json(logs / "build_completion.json")
    if (build.get("schema_version") != 1 or build.get("role") != "oatof_component_build_completion"
            or build.get("run_id") != run_id or build.get("context_sha256") != case["context_sha256"]):
        raise ValueError("PA build completion identity differs")
    operations = _builder_writer_operations(build, case["case_id"])
    stopped = bool(operations) and all(item["observation"]["exit_confirmed"] is True for item in operations)
    if not stopped or any(item["observation"]["returncode"] != 0 for item in operations):
        error = RuntimeError(f"PA build native/helper completion failed; see {logs / 'build_completion.json'}")
        error.observed_process_exit_confirmed = stopped
        raise error
    case["build_complete"] = True


def _run_guarded_flight(
    case: dict[str, Any], mode: str, command: list[str], stdout: Path, stderr: Path,
) -> tuple[int, int | None, float]:
    """Consume the PA guard's separate native and actual Python worker facts."""
    run_root = case["case_root"].parents[1]
    config = load_json(run_root / "run_config.json")
    closure = load_json(Path(config["inputs"]["execution_source_closure"]))
    wrapper = frozen_source_path(closure,
        "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/run_candidate_flight.ps1")
    request_path = case["case_root"] / "results" / f"{mode}_flight_request.json"
    process_receipt = case["case_root"] / "results" / f"{mode}_process_result.json"
    observation_path = case["case_root"] / "results" / f"{mode}_native_operation.json"
    _write_json(request_path, {
        "schema_version": 1, "role": "oatof_candidate_flight_request",
        "executable": command[0], "argv": command[1:], "cwd": str(case["simion_dir"]),
        "stdout": str(stdout), "stderr": str(stderr), "result_receipt": str(process_receipt),
        "warning_seconds": 1800, "context_sha256": case["context_sha256"],
        "run_id": case["run_id"], "case_id": case["case_id"], "mode": mode,
    })
    completed, _ = _observe_operation(
        ["pwsh.exe", "-NoProfile", "-File", wrapper, "-ExecutionRequestPath", str(request_path),
         "-RuntimeReceiptPath", str(case["simion_dir"] / "simion_runtime_receipt.json"),
         "-CapacitySessionPath", str(case["capacity_session_path"]),
         "-PythonExe", str(PYTHON), "-RepositoryRoot", str(REPO_ROOT)],
        cwd=REPO_ROOT, stdout=stdout.with_name(f"{mode}_owner.log"),
        stderr=stderr.with_name(f"{mode}_owner.stderr.log"), receipt_path=observation_path,
        operation_id=f"{case['case_id']}.{mode}.native", resource_release_id=case.get("_resource_release_id"),
        warning_seconds=1800,
    )
    observation = load_json(observation_path)
    observation["operation"]["observation"] = {"exit_confirmed": False, "returncode": None}
    _write_json(observation_path, observation)
    try:
        receipt = load_json(process_receipt)
        managed = receipt.get("managed_process_completion", {})
        managed_observation = _managed_process_observation(managed)
        if (
            receipt.get("schema_version") != 1 or receipt.get("role") != "oatof_candidate_flight_process_result"
            or any(receipt.get(key) != value for key, value in {
                "run_id": case["run_id"], "case_id": case["case_id"], "mode": mode,
                "context_sha256": case["context_sha256"],
            }.items())
            or receipt.get("native_exit_confirmed") is not True
            or type(receipt.get("native_returncode")) is not int
            or managed_observation["exit_confirmed"] is not True
        ):
            raise ValueError("guarded Fly has no matching complete native/worker observation")
    except BaseException as failure:
        failure.observed_process_exit_confirmed = False
        raise
    observation["operation"]["observation"] = {
        "exit_confirmed": True, "returncode": receipt["native_returncode"],
    }
    _write_json(observation_path, observation)
    if completed.returncode or managed["exit_code"]:
        failure = RuntimeError(f"guarded Fly owner failed (owner={completed.returncode}, worker={managed['exit_code']}); see {stderr.with_name(f'{mode}_owner.stderr.log')}")
        failure.observed_process_exit_confirmed = True
        failure.observed_process_returncode = receipt["native_returncode"]
        raise failure
    return (receipt["native_returncode"], receipt["native_peak_working_set_bytes"],
            receipt["native_elapsed_seconds"])


def _fly(case: dict[str, Any], mode: str, simion_exe: Path, particle_count: int,
          trajectory_quality: int) -> dict[str, Any]:
    accel, stage1, stage2 = MODE_FLAGS[mode]
    logs = case["case_root"] / "logs"
    results = case["case_root"] / "results"
    log = logs / f"{mode}.log"
    error = logs / f"{mode}.stderr.log"
    summary_path = results / f"{mode}_summary.json"
    native_path = results / f"{mode}_native.json"
    if summary_path.exists() or native_path.exists():
        raise ValueError("native unit output already exists; continuation requires a new run")
    reused = case.get("replay_units", {}).get(mode)
    native = load_json(reused) if reused else None
    ion = Path(native["ion"]) if native else case["simion_dir"] / f"oatof_comsol_524amu_gaussian_N{particle_count}.ion"
    command = [
        str(simion_exe), "--default-num-particles", str(particle_count),
        "--nogui", "fly", "--trajectory-quality", str(trajectory_quality),
        "--retain-trajectories", "0", "--particles", str(ion),
        "--adjustable", f"trajectory_quality={trajectory_quality}",
        "--adjustable", f"ideal_accel_enable={accel}",
        "--adjustable", f"ideal_refl_stage1_enable={stage1}",
        "--adjustable", f"ideal_refl_stage2_enable={stage2}",
        "--adjustable", "trajectory_log_enable=1",
        str(case["simion_dir"] / "oatof_ideal_grounded.iob"),
    ]
    if native:
        if (
            native.get("case_id") != case["case_id"] or native.get("mode") != mode
            or native.get("context_sha256") != case.get("continuation_parent_context_sha256", case["context_sha256"])
            or type(native.get("native_returncode")) is not int or native["native_returncode"] != 0
            or native.get("role") != "oatof_radial_compaction_native_unit"
            or native.get("particle_count") != particle_count
            or native.get("native_splats") != particle_count
            or native.get("trajectory_quality") != trajectory_quality
        ):
            raise ValueError("native unit does not match the frozen flight request")
        log, error = Path(native["stdout"]), Path(native["stderr"])
        elapsed = None
        reused_flight = True
        resource_profile = native["resource_profile"]
    else:
        if log.exists() or error.exists():
            raise ValueError("partial native logs require a new run and whole-unit replay")
        resource_identity = _case_resource_identity(case, ion, particle_count, trajectory_quality)
        native_returncode, peak_working_set_bytes, elapsed = _run_guarded_flight(case, mode, command, log, error)
        try:
            if native_returncode != 0:
                raise RuntimeError(f"command failed ({native_returncode}); see {error}")
            with log.open("r", encoding="utf-8-sig") as stream:
                completion = require_one_fly_completion(stream)
            if completion.splats != particle_count:
                raise ValueError("native Fly completion does not cover the frozen particle population")
        except BaseException as failure:
            failure.observed_process_exit_confirmed = True
            failure.observed_process_returncode = native_returncode
            raise
        reused_flight = False
        resource_profile = {
            "resource_identity": resource_identity,
            "per_batch_peak_working_set_bytes": peak_working_set_bytes,
        }
        native = {
            "schema_version": 1, "role": "oatof_radial_compaction_native_unit",
            "native_returncode": native_returncode,
            "native_splats": completion.splats,
            "case_id": case["case_id"], "mode": mode,
            "context_sha256": case["context_sha256"],
            "particle_count": particle_count, "trajectory_quality": trajectory_quality,
            "stdout": str(log), "stderr": str(error), "ion": str(ion),
            "flight_seconds": elapsed, "resource_profile": resource_profile,
        }
    # Publish the native completion before analysis. A later analysis failure
    # can replay this whole unit only after the run manifest binds its bytes.
    try:
        _write_json(native_path, {
            **native, "run_id": case["run_id"],
            "context_sha256": case["context_sha256"],
            "reused_from_receipt": str(reused) if reused else None,
        })
    except BaseException as failure:
        failure.observed_process_exit_confirmed = True
        failure.observed_process_returncode = 0
        raise
    try:
        return analysis.analyze_flight(case, mode, log, ion, particle_count, elapsed, reused_flight, resource_profile)
    except BaseException as failure:
        # Analysis is in-process; the native unit above is already complete.
        failure.observed_process_exit_confirmed = True
        failure.observed_process_returncode = native["native_returncode"]
        raise


def _case_resource_identity(
    case: dict[str, Any], ion: Path, particle_count: int, trajectory_quality: int,
) -> dict[str, Any]:
    """Identify the complete SIMION input that determines one case's memory use."""
    input_identity = {
        "iob_sha256": sha256(case["simion_dir"] / "oatof_ideal_grounded.iob"),
        "ion_sha256": sha256(ion),
        "particle_count": particle_count,
        "trajectory_quality": trajectory_quality,
    }
    encoded = json.dumps(input_identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "solver": "SIMION",
        "field_kind": "electrostatic",
        "oatof_numerical_profile_id": "radial_compaction",
        "trajectory_quality_profile_id": f"explicit-{trajectory_quality}",
        "case_input_sha256": hashlib.sha256(encoded).hexdigest().upper(),
    }


def _case_profile(result: dict[str, Any]) -> dict[str, Any] | None:
    profile = result.get("resource_profile")
    if not isinstance(profile, dict):
        return None
    identity = profile.get("resource_identity")
    peak = profile.get("per_batch_peak_working_set_bytes")
    if not isinstance(identity, dict) or isinstance(peak, bool) or not isinstance(peak, int) or peak < 1:
        return None
    return {"resource_identity": identity, "per_batch_peak_working_set_bytes": peak}


def _bind_frozen_execution_context(
    run_config_path: Path, execution_request_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind every freshly imported worker to the same frozen execution authority."""
    global ARTIFACT_ROOT, PYTHON
    request = load_json(execution_request_path)
    config = load_json(run_config_path)
    payload = request["payload"]
    artifact_root = Path(payload["artifact_project_root"]).resolve()
    selected_python = Path(request["python_executable"]).resolve(strict=True)
    run_root = run_config_path.resolve(strict=True).parent
    closure = load_json(Path(config["inputs"]["execution_source_closure"]))
    verify_candidate_source_closure(closure)
    if (request.get("role") != "run_artifact_workflow_request" or request.get("schema_version") != 1
            or payload.get("project") != PROJECT_ID or payload.get("run_id") != run_root.name
            or config.get("role") != RUN_ROLE or config.get("project") != PROJECT_ID
            or config.get("run_id") != run_root.name
            or run_root != artifact_root / "runs" / run_root.name
            or execution_request_path.resolve() != run_root / "inputs/execution_request.json"
            or Path(config["inputs"]["execution_request"]).resolve() != execution_request_path.resolve()
            or selected_python != Path(sys.executable).resolve()
            or Path(closure["runtime"]["python_executable"]).resolve() != selected_python
            or Path(closure["runtime"]["candidate_artifact_root"]).resolve() != artifact_root
            or Path(__file__).resolve() != Path(frozen_source_path(closure, EXTRA_SOURCE_IDS[0])).resolve()):
        raise ValueError("radial worker does not match the frozen execution authority")
    resource_state = os.environ.get("MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH", "")
    if not resource_state or not Path(resource_state).is_absolute():
        raise ValueError("frozen worker requires the public owner's absolute shared scheduler path")
    ARTIFACT_ROOT, PYTHON = artifact_root, selected_python
    return config, request


def _bind_pool_execution_context(cases: list[dict[str, Any]]) -> None:
    run_roots = {case["case_root"].resolve().parents[1] for case in cases}
    if len(run_roots) != 1:
        raise ValueError("one flight pool requires one frozen run authority")
    run_root = run_roots.pop()
    config, _ = _bind_frozen_execution_context(run_root / "run_config.json", run_root / "inputs/execution_request.json")
    if any(case.get("run_id") != config["run_id"] or case.get("context_sha256") != config["context_sha256"]
           or case["case_root"].resolve() != run_root / "cases" / case["case_id"] for case in cases):
        raise ValueError("flight pool case differs from its frozen run identity")


def _run_parallel_flights(
    cases: list[dict[str, Any]], mode: str, simion_exe: Path,
    particle_count: int, trajectory_quality: int,
    known_profiles: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Execute only the case wave chosen by the shared resource scheduler."""
    if cases:
        _bind_pool_execution_context(cases)
    outputs: dict[str, dict[str, Any]] = {}
    pending = list(cases)
    profiles: list[dict[str, Any]] = list(known_profiles or [])
    for case in list(pending):
        if mode in case.get("replay_units", {}):
            outputs[case["case_id"]] = _fly(case, mode, simion_exe, particle_count, trajectory_quality)
            existing = _case_profile(outputs[case["case_id"]])
            if existing is not None:
                profiles.append(existing)
            pending.remove(case)
    while pending:
        descriptors = []
        for case in pending:
            ion = case["simion_dir"] / f"oatof_comsol_524amu_gaussian_N{particle_count}.ion"
            descriptors.append({
                "case_id": case["case_id"],
                "resource_identity": _case_resource_identity(
                    case, ion, particle_count, trajectory_quality
                ),
            })
        dispatch = plan_simion_case_dispatch(
            descriptors,
            {"solver": "SIMION", "field_kind": "electrostatic"},
            profiles,
        )
        selected_ids = [item["case_id"] for item in dispatch["waves"][0]["cases"]]
        selected = [case for case in pending if case["case_id"] in selected_ids]
        # This executor makes no resource decision: it receives exactly the
        # wave already chosen by common.simion.resource_scheduler.
        failure: BaseException | None = None
        exit_unconfirmed = False
        with ThreadPoolExecutor(max_workers=len(selected)) as pool:
            futures = {
                pool.submit(
                    _fly, case, mode, simion_exe, particle_count, trajectory_quality
                ): case["case_id"]
                for case in selected
            }
            for future in as_completed(futures):
                case_id = futures[future]
                try:
                    outputs[case_id] = future.result()
                except BaseException as error:
                    if failure is None:
                        failure = error
                    else:
                        failure.add_note(f"Concurrent case {case_id} failed: {type(error).__name__}: {error}")
                    exit_unconfirmed |= getattr(error, "observed_process_exit_confirmed", False) is not True
                    continue
                observed = _case_profile(outputs[case_id])
                if observed is not None:
                    profiles.append(observed)
                print(f"FLIGHT=PASS CASE={case_id} MODE={mode}", flush=True)
        if failure is not None:
            failure.observed_process_exit_confirmed = not exit_unconfirmed
            raise failure
        pending = [case for case in pending if case["case_id"] not in selected_ids]
    return outputs


def _profiles_from_results(results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only observed, usable resource profiles from completed case results."""
    return [profile for result in results.values() if (profile := _case_profile(result)) is not None]


def _maximum_profiles(*groups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse repeated observations to the safest peak for each exact input."""
    selected: dict[str, dict[str, Any]] = {}
    for group in groups:
        for profile in _profiles_from_results(group):
            key = json.dumps(profile["resource_identity"], sort_keys=True)
            existing = selected.get(key)
            if (
                existing is None
                or profile["per_batch_peak_working_set_bytes"]
                > existing["per_batch_peak_working_set_bytes"]
            ):
                selected[key] = profile
    return [selected[key] for key in sorted(selected)]


def _run_flight_stage(
    cases: list[dict[str, Any]], mode: str, simion_exe: Path, count: int, quality: int,
    profiles: list[dict[str, Any]], resource_releases: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Retain the real whole-pool owner's completion receipt even on failure."""
    if all(mode in case.get("replay_units", {}) for case in cases):
        return _run_parallel_flights(cases, mode, simion_exe, count, quality, profiles)
    receipt: dict[str, Any] = {}
    release_id = f"flight:{len(resource_releases)}:{mode}"
    resource_releases.append({"release_id": release_id, "completion_receipt": receipt})
    for case in cases:
        case["_resource_release_id"] = release_id
    return run_heavy_function(
        "projects.single_reflection_oa_tof_mass_analyzer.workflows.radial_compaction.run_campaign",
        "_run_parallel_flights", cases, mode, simion_exe, count, quality, profiles,
        completion_receipt=receipt,
    )


def _execute_campaign(
    run_root: Path, run_config: dict[str, Any], simion_exe: Path, *, dry_run: bool,
) -> dict[str, Any]:
    config = load_json(Path(run_config["inputs"]["campaign"]))
    baseline = load_json(Path(run_config["inputs"]["baseline"]))
    reference_metrics = analysis.canonical_metrics(Path(run_config["inputs"]["reference_particles"]))
    seed = int(config["fixed_contract"]["particle_source_seed"])
    count = int(config["fixed_contract"]["particle_count"])
    quality = int(config["fixed_contract"]["trajectory_quality"])
    default_mesh = config["fixed_contract"]["default_reflectron_mesh_mm"]
    resource_releases: list[dict[str, Any]] = []
    run_config["_resource_releases"] = resource_releases
    _record_phase(run_root, "prepare_cases")
    primary = [
        _prepare_case(case, run_root, baseline, seed, default_mesh)
        for case in config["radius_screen"]
    ]
    if dry_run:
        print(f"RADIAL_COMPACTION=DRY_RUN CASES={len(primary)} ROOT={run_root}")
        return {"schema_version": 1, "role": "oatof_radial_compaction_plan_summary",
                "status": "success", "dry_run": True, "cases": len(primary)}

    def build(case: dict[str, Any]) -> None:
        if case.get("build_complete") is True:
            return
        _build_case(case, simion_exe=simion_exe, template_iob=Path(run_config["inputs"]["template_iob"]),
                    seed=seed, run_id=run_root.name, particle_count=count)

    for case in primary:
        if "actual" in case["replay_units"]:
            continue
        _record_phase(run_root, f"pa_build:{case['case_id']}")
        build(case)
        ion = case["simion_dir"] / f"oatof_comsol_524amu_gaussian_N{count}.ion"
        if sha256(ion) != config["fixed_contract"]["particle_table_sha256"]:
            raise ValueError(f"candidate source differs from reference: {case['case_id']}")
        print(f"PA_BUILD=PASS CASE={case['case_id']}", flush=True)

    persisted_profiles = discover_case_resource_profiles(ARTIFACT_ROOT / "runs")
    _record_phase(run_root, "actual_flights_and_analysis")
    actual = _run_flight_stage(
        primary, "actual", simion_exe, count, quality, persisted_profiles, resource_releases,
    )
    resolution_reference = float(reference_metrics["mass_resolution"])
    acceptance = config["acceptance"]

    def passes(result: dict[str, Any]) -> bool:
        diagnostics = result["diagnostics"]
        metrics = result["canonical_peak_metrics"]
        return (
            diagnostics["Hit"] / diagnostics["Emitted"]
            >= acceptance["minimum_hit_fraction"]
            and metrics["mass_resolution"] / resolution_reference
            >= acceptance["minimum_resolution_ratio_to_reference"]
            and metrics["significant_kde_modes"]
            <= acceptance["maximum_significant_kde_modes"]
        )

    failed = [case for case in primary if not passes(actual[case["case_id"]])]
    ideal: dict[str, dict[str, dict[str, Any]]] = {}
    if config["ideal_field_attribution"]["execute_for_failed_radius_cases"]:
        for mode in config["ideal_field_attribution"]["modes"]:
            _record_phase(run_root, f"{mode}_flights_and_analysis")
            for case in failed:
                if mode not in case["replay_units"]:
                    build(case)
            ideal[mode] = _run_flight_stage(
                failed, mode, simion_exe, count, quality,
                persisted_profiles + _profiles_from_results(actual), resource_releases,
            ) if failed else {}

    target_id = config["ring_count_compensation"]["target_case_id"]
    target = next(case for case in primary if case["case_id"] == target_id)
    compensation: list[dict[str, Any]] = []
    compensation_results: dict[str, dict[str, Any]] = {}
    compensation_ideal: dict[str, dict[str, dict[str, Any]]] = {}
    if (
        config["ring_count_compensation"]["execute_when_target_fails"]
        and not passes(actual[target_id])
        and actual[target_id]["diagnostics"]["Hit"]
        / actual[target_id]["diagnostics"]["Emitted"]
        >= acceptance["minimum_hit_fraction"]
        and ideal.get("ideal_reflectron", {})
        .get(target_id, {})
        .get("canonical_peak_metrics", {})
        .get("mass_resolution", 0.0)
        >= 0.95 * resolution_reference
    ):
        _record_phase(run_root, "compensation_builds")
        for ring_case in config["ring_count_compensation"]["cases"]:
            merged = {
                **{key: target[key] for key in (
                    "bore_radius_mm", "ring_outer_radius_mm",
                    "shared_shield_inner_radius_mm"
                )},
                **ring_case,
            }
            candidate = _prepare_case(merged, run_root, baseline, seed, default_mesh)
            if "actual" not in candidate["replay_units"]:
                build(candidate)
            compensation.append(candidate)
            print(f"PA_BUILD=PASS CASE={candidate['case_id']}", flush=True)
        _record_phase(run_root, "compensation_actual_flights_and_analysis")
        compensation_results = _run_flight_stage(
            compensation, "actual", simion_exe, count, quality, persisted_profiles, resource_releases,
        )
        diagnostic_ids = set(
            config["ring_count_compensation"].get(
                "ideal_field_diagnostic_case_ids", []
            )
        )
        diagnostic_cases = [
            case for case in compensation if case["case_id"] in diagnostic_ids
        ]
        missing_diagnostic_ids = diagnostic_ids - {
            case["case_id"] for case in diagnostic_cases
        }
        if missing_diagnostic_ids:
            raise ValueError(
                "unknown compensation ideal-field case: "
                + ", ".join(sorted(missing_diagnostic_ids))
            )
        for mode in config["ideal_field_attribution"]["modes"]:
            _record_phase(run_root, f"compensation_{mode}_flights_and_analysis")
            for case in diagnostic_cases:
                if mode not in case["replay_units"]:
                    build(case)
            compensation_ideal[mode] = _run_flight_stage(
                diagnostic_cases, mode, simion_exe, count, quality,
                persisted_profiles + _profiles_from_results(compensation_results), resource_releases,
            )

    _record_phase(run_root, "campaign_analysis")
    rows = []
    for case in primary + compensation:
        result = (actual if case in primary else compensation_results)[case["case_id"]]
        metrics = result["canonical_peak_metrics"]
        rows.append(
            {
                "case_id": case["case_id"],
                "shared_shield_inner_radius_mm": case["shared_shield_inner_radius_mm"],
                "instrument_outer_radius_mm": case["shared_shield_inner_radius_mm"]
                + config["fixed_contract"]["fixed_shield_wall_mm"],
                "bore_radius_mm": case["bore_radius_mm"],
                "ring_outer_radius_mm": case["ring_outer_radius_mm"],
                "stage1_count": case.get("stage1_count", baseline["rings"]["stage1_count"]),
                "stage2_count": case.get("stage2_count", baseline["rings"]["stage2_count"]),
                "ring_thickness_mm": case.get(
                    "ring_thickness_mm", baseline["geometry_mm"]["ring_thickness"]
                ),
                "reflectron_cell_axial_mm": case.get(
                    "reflectron_cell_axial_mm",
                    config["fixed_contract"]["default_reflectron_mesh_mm"]["axial"],
                ),
                "hit": result["diagnostics"]["Hit"],
                "mass_resolution": metrics["mass_resolution"],
                "resolution_ratio_to_reference": metrics["mass_resolution"] / resolution_reference,
                "significant_kde_modes": metrics["significant_kde_modes"],
                "accepted": passes(result),
                "pa_build_seconds": case["pa_build_seconds"],
                "flight_seconds": result["flight_seconds"],
            }
        )
    accepted = [row for row in rows if row["accepted"]]
    best = min(accepted, key=lambda row: row["instrument_outer_radius_mm"]) if accepted else None
    summary = {
        "schema_version": 1,
        "role": "oatof_radial_compaction_campaign_summary",
        "status": "success",
        "reference": {
            "mass_resolution": resolution_reference,
            "significant_kde_modes": reference_metrics["significant_kde_modes"],
            "instrument_outer_radius_mm": baseline["geometry_mm"]["flight_tube_r"]
            + baseline["geometry_mm"]["flight_tube_wall"],
        },
        "best_accepted_case": best,
        "cases": rows,
        "ideal_field_results": ideal,
        "compensation_ideal_field_results": compensation_ideal,
        "simion_case_resource_profiles": _maximum_profiles(
            actual,
            compensation_results,
            *ideal.values(),
            *compensation_ideal.values(),
        ),
        "fixed_contract_verified": True,
        "shared_shield_radius_and_wall_verified": True,
    }
    return summary


def _execute_frozen_campaign(
    run_config_path: Path, capacity_session_path: Path,
    execution_request_path: Path, completion_path: Path,
) -> None:
    """Private worker loaded from the recorded code root, consuming frozen inputs."""
    run_config, request = _bind_frozen_execution_context(run_config_path, execution_request_path)
    payload = request["payload"]
    run_root = run_config_path.parent
    parent = Path(payload["parent_run_dir"]) if payload["parent_run_dir"] else None
    simion_exe, dry_run = Path(payload["simion_exe"]), payload["dry_run"]
    failure = None
    try:
        if parent is not None:
            _plan_replay(run_root, parent, run_config)
        count = int(load_json(Path(run_config["inputs"]["campaign"]))["fixed_contract"]["particle_count"])
        validate_standard_particle_count(count)
        summary = _execute_campaign(run_root, run_config, simion_exe, dry_run=dry_run)
    except BaseException as error:
        failure = error
        summary = {
            "schema_version": 1, "role": "oatof_radial_compaction_campaign_summary",
            "status": "interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "failed",
            "failure_stage": load_json(run_root / "summary.json").get("active_stage", "continuation_plan"),
            "error": f"{type(error).__name__}: {error}",
        }
    try:
        output_paths, required_paths = _campaign_outputs(run_root, summary)
        operations = [load_json(path)["operation"]
                      for path in sorted(run_root.glob("cases/*/results/*_operation.json"))]
        if failure is not None and getattr(failure, "observed_process_exit_confirmed", None) is False:
            operations.append({"operation_id": "unconfirmed-worker", "observation": {
                "exit_confirmed": False, "returncode": getattr(failure, "observed_process_returncode", None)},
                "resource_release_id": None})
        releases = list(run_config.get("_resource_releases", []))
        for path in sorted(run_root.glob("cases/*/logs/build_completion.json")):
            build = load_json(path)
            case_id = path.parents[1].name
            if (build.get("role") != "oatof_component_build_completion" or build.get("schema_version") != 1
                    or build.get("run_id") != run_root.name or build.get("context_sha256") != run_config["context_sha256"]):
                raise ValueError("PA build completion identity differs")
            release_id = f"build:{case_id}"
            observation = load_json(path.parents[1] / "results/build_operation.json")["operation"]["observation"]
            releases.append({"release_id": release_id, "completion_receipt": {
                "bridge_process_exit_confirmed": observation["exit_confirmed"],
                "bridge_process_returncode": observation["returncode"], "host_release": build["host_release"],
            }})
            operations.extend(_builder_writer_operations(build, case_id))
        completion = {
            "schema_version": 1, "role": "run_artifact_workflow_completion",
            "run_id": run_root.name, "project": PROJECT_ID,
            "execution_request": file_record(execution_request_path),
            "run_config": file_record(run_config_path),
            "status": summary["status"], "summary": summary,
            "output_paths": output_paths, "required_output_paths": required_paths,
            "retention_preserve_paths": [],
            "manifest_extra_fields": {},
            "writer_completion": {"operations": operations,
                                  "resource_releases": releases},
            "exception": ({"type": type(failure).__name__, "module": type(failure).__module__,
                           "message": str(failure), "notes": list(getattr(failure, "__notes__", []))}
                          if failure is not None else None),
        }
        _write_json(completion_path, completion)
    except BaseException as recording_error:
        if failure is not None:
            failure.add_note(f"Radial completion recording failed: {type(recording_error).__name__}: {recording_error}")
            raise failure
        raise
    if failure is not None:
        raise failure


def execute_prepared_run(
    run_config_path: Path, capacity_session_path: Path,
    execution_request_path: Path, completion_path: Path,
) -> None:
    """Internal call made while the PowerShell package/capacity owner stays alive."""
    run_config_path, capacity_session_path = Path(run_config_path), Path(capacity_session_path)
    execution_request_path, completion_path = Path(execution_request_path), Path(completion_path)
    initial = _validate_prepared_run(run_config_path, capacity_session_path, execution_request_path)
    request = load_json(execution_request_path)
    payload = request["payload"]
    if (
        request.get("schema_version") != 1 or request.get("role") != "run_artifact_workflow_request"
        or payload.get("role") != "oatof_radial_compaction_execution_request"
        or payload.get("schema_version") != 1 or payload.get("run_id") != initial["run_id"]
        or payload.get("project") != PROJECT_ID
        or Path(payload["artifact_project_root"]).resolve() != ARTIFACT_ROOT.resolve()
        or Path(request["python_executable"]).resolve() != Path(sys.executable).resolve()
    ):
        raise ValueError("prepared radial execution differs from the admitted request")
    run_root = run_config_path.resolve().parent
    config = _freeze_run(
        run_root, Path(payload["simion_exe"]).resolve(strict=True),
        Path(payload["parent_run_dir"]).resolve(strict=True) if payload["parent_run_dir"] else None,
        initialized_config=initial, capacity_session_path=capacity_session_path.resolve(),
        campaign_path=Path(payload["campaign_path"]) if payload["campaign_path"] else None,
        execution_request=payload,
    )
    closure = load_json(Path(config["inputs"]["execution_source_closure"]))
    code_root = Path(closure["code_root"])
    provisional = completion_path.with_name("frozen_execution_completion.json")
    if completion_path.exists() or provisional.exists():
        raise ValueError("prepared completion must be new for this run")
    worker = (
        "from common.host_resource_python import await_managed_process_start; await_managed_process_start(); "
        "from pathlib import Path; import sys; "
        "from projects.single_reflection_oa_tof_mass_analyzer.workflows.radial_compaction.run_campaign "
        "import _execute_frozen_campaign; _execute_frozen_campaign(*(Path(p) for p in sys.argv[1:]))"
    )
    wait_path = run_root / "logs/frozen_execution_wait.json"
    try:
        receipt = run_managed_python_process(
            ["-B", "-c", worker, str(run_config_path), str(capacity_session_path),
             str(execution_request_path), str(provisional)],
            cwd=code_root, stdout=run_root / "logs/frozen_execution.log",
            stderr=run_root / "logs/frozen_execution.stderr.log",
            environment={**os.environ, "PYTHONPATH": str(code_root), "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except BaseException as error:
        try:
            _write_json(wait_path, {"managed_process": getattr(error, "managed_python_completion", None),
                                   "error": f"{type(error).__name__}: {error}"})
        except BaseException as recording_error:
            error.add_note(f"Frozen worker wait recording failed: {recording_error}")
        raise
    _write_json(wait_path, {"managed_process": receipt, "error": None})
    if not provisional.is_file():
        raise RuntimeError(f"Frozen radial execution returned no completion ({receipt['exit_code']}); see {run_root / 'logs/frozen_execution.stderr.log'}")
    completion = load_json(provisional)
    if receipt["exit_code"] and completion.get("status") not in {"failed", "interrupted"}:
        raise ValueError("Frozen radial success contradicts its actual worker exit")
    completion["output_paths"] = list(dict.fromkeys([*completion["output_paths"], str(wait_path)]))
    _write_json(provisional, completion)
    # Windows rename is atomic and rejects an existing destination. A worker's
    # provisional record cannot authorize publication before its owner returns.
    provisional.rename(completion_path)
    if receipt["exit_code"]:
        error = RuntimeError(f"Frozen radial execution failed ({receipt['exit_code']}); see {run_root / 'logs/frozen_execution.stderr.log'}")
        error.managed_python_completion = receipt
        raise error


def _invoke_workflow_owner(request: dict[str, Any]) -> None:
    """Use the one public package/capacity/publication owner without a new CLI."""
    with tempfile.TemporaryDirectory(prefix="oatof-radial-request-") as directory:
        temporary = Path(directory)
        request_path = temporary / "request.json"
        handoff_output = request["payload"].get("pa_handoff_output")
        result_path = (Path(handoff_output) if handoff_output else
                       ARTIFACT_ROOT / "scratch" / "workflow_results" / request["package"]["run_id"] / "result.json")
        result_path.parent.mkdir(parents=True, exist_ok=True)
        if result_path.exists():
            raise ValueError(f"Workflow Result already exists: {result_path}")
        _write_json(request_path, request)
        result, _ = run_observed_process(
            ["pwsh.exe", "-NoProfile", "-File", str(REPO_ROOT / "common/contracts/run_artifact_workflow.ps1"),
             "-RequestPath", str(request_path), "-ResultPath", str(result_path)],
            cwd=REPO_ROOT, stdout=temporary / "owner.log", stderr=temporary / "owner.stderr.log",
            warning_seconds=1800,
        )
        if result.returncode:
            details = (temporary / "owner.stderr.log").read_text(encoding="utf-8-sig")
            raise RuntimeError(f"Radial workflow owner failed ({result.returncode}): {details}; result: {result_path}")
        if not result_path.is_file():
            raise RuntimeError("Radial workflow owner returned no result receipt")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--resume-finalization", action="store_true",
                        help="Resume publication for this run from its frozen request and retained owner result")
    parser.add_argument("--owner-result", type=Path,
                        help="Existing owner Result when an explicit PA handoff output was used")
    parser.add_argument("--simion-exe", type=Path,
                        default=Path(r"C:\Program Files\SIMION-2020\simion.exe"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume-from", type=Path,
                        help="Explicit published predecessor; --run-id must identify a new run")
    parser.add_argument("--campaign", type=Path, default=None,
                        help="Explicit authorized campaign contract; continuation uses only its parent's frozen contract")
    parser.add_argument("--pa-handoff-output", type=Path,
                        help="Keep the public owner's original Result outside runs; explicitly selects solver_review retention")
    parser.add_argument("--pa-producer-handoff", type=Path, nargs=2, action="append", metavar=("TRANSACTION", "OWNER_RESULT"),
                        help="Explicit unpublished PA producer pair; repeat for multiple components, independently of --resume-from")
    args = parser.parse_args()
    if args.resume_finalization:
        validate_run_id(args.run_id)
        run_root = ARTIFACT_ROOT / "runs" / args.run_id
        request_path = run_root / "inputs" / "execution_request.json"
        request = load_json(request_path)
        result_path = (args.owner_result or Path(request["payload"].get("pa_handoff_output") or
                       ARTIFACT_ROOT / "scratch" / "workflow_results" / args.run_id / "result.json"))
        result_path = result_path.resolve(strict=True)
        if request["package"]["project"] != PROJECT_ID or request["package"]["mode"] != "simion_radial_compaction":
            raise ValueError("finalization request is not a radial compaction run")
        with tempfile.TemporaryDirectory(prefix="oatof-radial-finalize-") as directory:
            temporary = Path(directory)
            result, _ = run_observed_process(
                ["pwsh.exe", "-NoProfile", "-File", str(REPO_ROOT / "common/contracts/run_artifact_workflow.ps1"),
                 "-RequestPath", str(request_path), "-ResultPath", str(result_path), "-ResumeFinalization"],
                cwd=REPO_ROOT, stdout=temporary / "owner.log", stderr=temporary / "owner.stderr.log",
                warning_seconds=1800,
            )
            if result.returncode:
                raise RuntimeError(f"Radial finalization failed; result: {result_path}; "
                                   f"{(temporary / 'owner.stderr.log').read_text(encoding='utf-8-sig')}")
        print(f"RADIAL_COMPACTION=FINALIZED ROOT={run_root} RESULT={result_path}", flush=True)
        return
    if args.owner_result is not None:
        parser.error("--owner-result requires --resume-finalization")
    if args.resume_from is not None and args.campaign is not None:
        parser.error("--resume-from cannot be combined with an explicit --campaign")
    if args.dry_run and (args.pa_handoff_output is not None or args.pa_producer_handoff):
        parser.error("PA handoff options cannot be combined with --dry-run")
    validate_run_id(args.run_id)
    payload = _prepare_execution_request(
        args.run_id, args.simion_exe.resolve(strict=True),
        args.resume_from.resolve(strict=True) if args.resume_from else None, args.dry_run,
        campaign_path=args.campaign,
        pa_producer_handoffs=args.pa_producer_handoff, pa_handoff_output=args.pa_handoff_output,
    )
    policy_path = REPO_ROOT / "common/contracts/artifact_capacity_policy.json"
    commitment = (load_json(policy_path)["light_evidence_budget_bytes"]
                  if args.dry_run else payload["committed_new_bytes"])
    request = {
        "schema_version": 1, "role": "run_artifact_workflow_request",
        "repository_root": str(REPO_ROOT), "python_executable": str(Path(sys.executable).resolve()),
        "package": {"project": PROJECT_ID, "run_id": args.run_id, "mode": "simion_radial_compaction",
                    "artifact_project_root": str(ARTIFACT_ROOT), "software": ["SIMION 2020"],
                    "retention_class": "solver_review" if args.pa_handoff_output is not None else "compact",
                    "retention_reason": PA_HANDOFF_RETENTION_REASON if args.pa_handoff_output is not None else ""},
        "capacity": {"committed_new_bytes": commitment,
                     "commitment_inputs": [file_record(Path(path)) for path in payload["input_paths"].values()]
                     + ([file_record(policy_path)] if args.dry_run else [])
                     + (payload["pa_producer_handoffs"]["source_records"] if payload["pa_producer_handoffs"] else []),
                     "protected_paths": payload["dependency_run_dirs"],
                     "protected_cache_keys": [] if args.dry_run else payload["protected_cache_keys"]},
        "prepared": {"module": "projects.single_reflection_oa_tof_mass_analyzer.workflows.radial_compaction.run_campaign",
                     "function": "execute_prepared_run", "import_root": str(REPO_ROOT),
                     "entrypoint": file_record(Path(__file__).resolve())},
        "payload": payload,
    }
    _invoke_workflow_owner(request)
    summary = load_json(ARTIFACT_ROOT / "runs" / args.run_id / "summary.json")
    if summary.get("status") != "success" or summary.get("writers_stopped") is not True:
        raise RuntimeError("Radial workflow did not publish a successful stopped-writer terminal state")
    result_path = args.pa_handoff_output or ARTIFACT_ROOT / "scratch" / "workflow_results" / args.run_id / "result.json"
    print(f"RADIAL_COMPACTION={'DRY_RUN' if args.dry_run else 'PASS'} ROOT={ARTIFACT_ROOT / 'runs' / args.run_id} RESULT={result_path}", flush=True)


if __name__ == "__main__":
    main()
