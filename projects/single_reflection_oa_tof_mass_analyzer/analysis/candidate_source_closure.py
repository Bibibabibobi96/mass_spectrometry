"""Freeze and verify the executable source closure of an oa-TOF candidate run."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import marshal
import struct
import types
import sys
from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import sha256
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record
from projects.orthogonal_accelerator.analysis.component_contract import load_accelerator_dependency


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
ROLE = "oa_tof_candidate_execution_source_closure"

# This is intentionally an auditable allowlist, not dependency discovery.
# Keep paths repository-relative and use forward slashes in the machine record.
RELATIVE_PATHS = (
    "common/host_resource_python.py",
    "common/host_resource_python.ps1",
    "common/contracts/run_artifact_support.ps1",
    "common/paths/workspace_paths.py",
    "common/paths/workspace_paths.ps1",
    "common/contracts/artifact_identity_archive.py",
    "common/contracts/artifact_cache_contract.py",
    "common/contracts/gui_source_protection.py",
    "common/contracts/artifact_retention.py",
    "common/contracts/artifact_retention.json",
    "common/contracts/artifact_capacity_policy.json",
    "common/contracts/capacity_ledger.py",
    "common/contracts/capacity_protection.py",
    "common/contracts/execution_aliases.py",
    "common/contracts/expected_values.py",
    "common/contracts/frozen_inputs.py",
    "common/contracts/historical_source_scratch_retirement.py",
    "common/contracts/legacy_owner_disposition.py",
    "common/contracts/particle_physics.py",
    "common/contracts/reconcile_artifact_capacity.py",
    "common/contracts/recorded_file_removal.py",
    "common/contracts/run_capacity_lifecycle.py",
    "common/contracts/solver_review_retirement.py",
    "common/contracts/stage_reuse.py",
    "common/contracts/validate_design_request.py",
    "common/contracts/verify_artifact_layout.py",
    "common/contracts/verify_run_manifest.py",
    "common/contracts/write_run_manifest.py",
    "common/contracts/schemas/design_variable_catalog.schema.json",
    "common/simion/__init__.py",
    "common/simion/cache_generation.py",
    "common/simion/immutable_pa_parity.py",
    "common/simion/native_completion.py",
    "common/simion/pa_family_cache.py",
    "common/simion/standalone_pa_response_set.py",
    "common/simion/short_pa_path_support.ps1",
    "common/simion/native_fast_adjust_runtime_support.ps1",
    "common/simion/assemble_native_fast_adjust_family.lua",
    "common/simion/export_standalone_pa.lua",
    "common/simion/voltageize_pa0.lua",
    "common/contracts/run_artifact_workflow.ps1",
    "projects/single_reflection_oa_tof_mass_analyzer/analysis/candidate_source_closure.py",
    "projects/single_reflection_oa_tof_mass_analyzer/analysis/native_stage_completion.py",
    "projects/single_reflection_oa_tof_mass_analyzer/analysis/compile_candidate_design.py",
    "projects/single_reflection_oa_tof_mass_analyzer/analysis/oatof_oaaccelerator_coupling.py",
    "projects/single_reflection_oa_tof_mass_analyzer/analysis/reflectron_dual_stage_solver.py",
    "projects/single_reflection_oa_tof_mass_analyzer/analysis/simion_component_pa_plan.py",
    "projects/single_reflection_oa_tof_mass_analyzer/simion/reflectron/refine_single_pa.lua",
    "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/verify_component_pa.lua",
    "common/simion/process_observation.py",
    "projects/rf_multipole_ion_optics/core/grounded_shield.py",
    "common/simion/aperture.py",
    "common/contracts/machine_contracts.py",
    "common/contracts/schemas/simion_rectangular_aperture_discretization.schema.json",
    "projects/single_reflection_oa_tof_mass_analyzer/analysis/geometry_contract.py",
    "projects/single_reflection_oa_tof_mass_analyzer/analysis/accelerator_geometry.py",
    "projects/single_reflection_oa_tof_mass_analyzer/analysis/accelerator_electrical.py",
    "projects/single_reflection_oa_tof_mass_analyzer/analysis/sync_geometry_contract.py",
    "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/prepare_candidate_consumers.py",
    "projects/single_reflection_oa_tof_mass_analyzer/config/candidate_consumers.json",
    "projects/single_reflection_oa_tof_mass_analyzer/config/design_variables.json",
    "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/formal/oatof_ideal_grounded.lua",
    "common/host_execution_lease.ps1",
    "common/host_resource_scheduler.py",
    "common/host_resource_policy.json",
    "common/resource_budget_support.ps1",
    "common/comsol/add_comsol_size_feature.m",
    "common/comsol/livelink_environment.ps1",
    "common/comsol/livelink_failure_classification.ps1",
    "common/comsol/livelink_r2025b/comsolstartup.m",
    "common/comsol/resolve_comsol_64.ps1",
    "common/comsol/run_comsol_r2025b.ps1",
    "common/paths/workspace_paths.m",
    "common/paths/resolve_path_identity.m",
    "common/analysis/peak_metrics.py",
    "common/contracts/artifact_naming.py",
    "common/contracts/file_identity.py",
    "common/contracts/particle_count_policy.json",
    "common/contracts/particle_count_policy.py",
    "common/require_powershell7.ps1",
    "common/solidworks/import_step_to_solidworks.m",
    "common/solidworks/import_step_to_solidworks.py",
    "common/solidworks/installation.py",
    "projects/orthogonal_accelerator/analysis/accelerator_time_focus.py",
    "projects/orthogonal_accelerator/analysis/component_contract.py",
    "projects/orthogonal_accelerator/analysis/three_zone_ideal_theory.py",
    "projects/orthogonal_accelerator/analysis/two_zone_geometry.py",
    "projects/orthogonal_accelerator/comsol/build_sectioned_geometry.m",
    "projects/orthogonal_accelerator/config/component_contract.json",
    "projects/orthogonal_accelerator/comsol/build_accelerator_grids.m",
    "projects/orthogonal_accelerator/simion/build_two_zone_pa.lua",
    "projects/orthogonal_accelerator/simion/two_zone_accelerator.gem",
    "common/ion_release/dotnet_gaussian_box_ion11.py",
    "projects/single_reflection_oa_tof_mass_analyzer/config/accelerator_dependency.json",
    "projects/single_reflection_oa_tof_mass_analyzer/analysis/candidate_run_lifecycle.py",
    "projects/single_reflection_oa_tof_mass_analyzer/analysis/analyze_comsol_detector_events.py",
    "projects/single_reflection_oa_tof_mass_analyzer/analysis/prepare_candidate_run.py",
    "projects/single_reflection_oa_tof_mass_analyzer/analysis/reference_analysis.py",
    "projects/single_reflection_oa_tof_mass_analyzer/analysis/reference_analysis_core.py",
    "projects/single_reflection_oa_tof_mass_analyzer/cad/export_oatof_cad_step.m",
    "projects/single_reflection_oa_tof_mass_analyzer/cad/ms_export_oatof_to_solidworks.m",
    "projects/single_reflection_oa_tof_mass_analyzer/cad/oatof_cad_export_manifest.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/configure_oatof_segmented_output.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_build_accelerator_geometry.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_build_detector_geometry.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_build_drift_geometry.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_build_grid_geometry.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_build_mesh.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_build_model_core.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_report_model_timing.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_validate_candidate_solution.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_build_saved_particle_solution.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_save_run_model.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_write_saved_particle_context.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_postprocess_saved_solution.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/reextract_oatof_saved_solution.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_particle_plot_view.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_build_reflectron_geometry.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_configure_particle_model.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_cpt_solver_policy.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_create_result_nodes.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_extract_detector_arrivals.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_detector_arrival_reducer.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_export_detector_events.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_parse_field_idealization.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_read_cartesian_release.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/run_oatof_model.m",
    "projects/single_reflection_oa_tof_mass_analyzer/comsol/verify_oatof_comsol_sync.m",
    "projects/single_reflection_oa_tof_mass_analyzer/docs/SIMION_DELIVERY_CHECKLIST.md",
    "projects/single_reflection_oa_tof_mass_analyzer/load_oatof_contract.m",
    "projects/single_reflection_oa_tof_mass_analyzer/oatof_lifecycle_preflight.ps1",
    "projects/single_reflection_oa_tof_mass_analyzer/oatof_assert_formal_write_authorized.m",
    "projects/single_reflection_oa_tof_mass_analyzer/oatof_paths.m",
    "projects/single_reflection_oa_tof_mass_analyzer/simion/reflectron/build_reflectron_variant.lua",
    "projects/single_reflection_oa_tof_mass_analyzer/simion/reflectron/oatof_reflectron_ideal_10_5.gem",
    "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/build_detector_variant.lua",
    "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/build_flight_tube_variant.lua",
    "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/generate_comsol_consistent_ions.ps1",
    "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/analyze_ideal_field_log.ps1",
    "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/build_formal_delivery.ps1",
    "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/build_formal_iob.lua",
    "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/run_n100_transport.ps1",
    "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/run_candidate_flight.ps1",
    "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/oatof_detector_ground.gem",
    "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/oatof_flight_tube_ground.gem",
    "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/verify_iob_runtime_contract.lua",
    "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/verify_iob_runtime_contract.ps1",
    "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_cad_sync.m",
    "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_contract_build.m",
    "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate.py",
    "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/run_candidate_workflow.py",
    "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/candidate_stage_execution.py",
    "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/candidate_comsol_stage.py",
    "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/candidate_simion_stage.py",
    "projects/single_reflection_oa_tof_mass_analyzer/workflows/design_candidate/candidate_cad_stage.py",
    "projects/single_reflection_oa_tof_mass_analyzer/analysis/solver_diagnostics.py",
)

PYTHON_BOUND_SOURCES = frozenset({
    "common/host_execution_lease.ps1",
    "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/generate_comsol_consistent_ions.ps1",
    "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/analyze_ideal_field_log.ps1",
    "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/build_formal_delivery.ps1",
})
PYTHON_ASSIGNMENT = "$python = Join-Path $repoRoot '.venv\\Scripts\\python.exe'"
HOST_PYTHON_ASSIGNMENT = "$python = if ($env:SIMULATION_PYTHON_EXE) { $env:SIMULATION_PYTHON_EXE } else {\n    Join-Path $repo '.venv/Scripts/python.exe'\n  }"
ANALYSIS_PYTHON_ASSIGNMENT = "$python = if ($env:SIMULATION_PYTHON_EXE) { $env:SIMULATION_PYTHON_EXE } else {\n  Join-Path $repoRoot '.venv\\Scripts\\python.exe'\n}"

GENERATOR_PYTHON_ASSIGNMENT = "$python = if ($PythonExe) {\n  [IO.Path]::GetFullPath($PythonExe)\n} elseif ($env:SIMULATION_PYTHON_EXE) {\n  [IO.Path]::GetFullPath($env:SIMULATION_PYTHON_EXE)\n} else {\n  Join-Path $repoRoot '.venv\\Scripts\\python.exe'\n}"


def _source_path(source_id: str) -> Path:
    relative = Path(source_id)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"invalid candidate source path: {source_id}")
    source = (REPO_ROOT / relative).resolve()
    if not source.is_file() or REPO_ROOT not in source.parents:
        raise ValueError(f"candidate source is absent or escapes repository: {source_id}")
    return source


def _bind_python_runtime(payload: bytes, python_executable: Path, assignment: str = PYTHON_ASSIGNMENT) -> bytes:
    text = payload.decode("utf-8")
    if text.count(assignment) != 1:
        raise ValueError("candidate PowerShell source has an unexpected Python binding")
    escaped = str(python_executable).replace("'", "''")
    replacement = f"$python = '{escaped}' # frozen candidate runtime binding"
    return text.replace(assignment, replacement).encode("utf-8")


def freeze_candidate_source_closure(
    code_root: Path,
    artifact_root: Path,
    python_executable: Path | None = None,
    *,
    extra_source_ids: tuple[str, ...] = (),
    resolved_contract: Path | None = None,
    analysis_contract: Path | None = None,
) -> dict[str, Any]:
    """Copy the declared closure and return its immutable execution record."""
    code_root = code_root.resolve()
    python_path = Path(python_executable or sys.executable).resolve()
    if not python_path.is_file():
        raise ValueError(f"candidate Python runtime is unavailable: {python_path}")
    artifact_path = artifact_root.resolve()
    load_accelerator_dependency(
        REPO_ROOT, PROJECT_ROOT / "config/accelerator_dependency.json",
        consumer_project_id=PROJECT_ROOT.name, required_variant="two_zone",
    )

    if not isinstance(extra_source_ids, tuple) or any(
        not isinstance(source_id, str) or not source_id for source_id in extra_source_ids
    ):
        raise ValueError("extra candidate source ids must be a tuple of relative paths")
    declarations = list(RELATIVE_PATHS)
    for source_id in extra_source_ids:
        normalized = source_id.replace("\\", "/")
        _source_path(normalized)
        if normalized not in declarations:
            declarations.append(normalized)

    analysis_resources = {}
    if (resolved_contract is None) != (analysis_contract is None):
        raise ValueError("Candidate detector analysis requires both explicit physical and analysis contracts")
    if resolved_contract is not None:
        analysis_resources = {
            "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json": resolved_contract.resolve(strict=True),
            "projects/single_reflection_oa_tof_mass_analyzer/config/analysis_contract.json": analysis_contract.resolve(strict=True),
        }
        declarations.extend(analysis_resources)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for declared in declarations:
        source_id = declared.replace("\\", "/")
        if source_id in seen:
            raise ValueError(f"duplicate candidate source id: {source_id}")
        seen.add(source_id)
        source = analysis_resources.get(source_id) or _source_path(source_id)
        source_digest = sha256(source)
        payload = source.read_bytes()
        if sha256(source) != source_digest:
            raise ValueError(f"candidate source changed while frozen: {source_id}")

        transformations: list[str] = []
        if source_id in PYTHON_BOUND_SOURCES:
            if source_id == "common/host_execution_lease.ps1":
                assignment = HOST_PYTHON_ASSIGNMENT
            elif source_id == "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/analyze_ideal_field_log.ps1":
                assignment = ANALYSIS_PYTHON_ASSIGNMENT
            elif source_id == "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/generate_comsol_consistent_ions.ps1":
                assignment = GENERATOR_PYTHON_ASSIGNMENT
            else:
                assignment = PYTHON_ASSIGNMENT
            payload = _bind_python_runtime(payload, python_path, assignment)
            transformations.append("python_runtime_binding")
        target = code_root / source_id
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        records.append(
            {
                "source_id": source_id,
                "source_sha256": source_digest,
                "sha256": sha256(target),
                "bytes": target.stat().st_size,
                "transformations": transformations,
            }
        )

    closure = {
        "schema_version": 2,
        "role": ROLE,
        "code_root": str(code_root),
        "runtime": {
            "python_executable": str(python_path),
            "python_sha256": sha256(python_path),
            "candidate_artifact_root": str(artifact_path),
        },
        "sources": records,
    }
    verify_candidate_source_closure(closure)
    return closure


def verify_candidate_source_closure(closure: dict[str, Any]) -> None:
    """Reject malformed, missing, extra, or modified frozen source files."""
    if closure.get("schema_version") != 2 or closure.get("role") != ROLE:
        raise ValueError("invalid candidate source closure")
    records = closure.get("sources")
    if not isinstance(records, list) or not records:
        raise ValueError("invalid candidate source closure")
    runtime = closure.get("runtime", {})
    python_path = Path(runtime.get("python_executable", "")).resolve()
    if not python_path.is_file() or sha256(python_path).lower() != str(runtime.get("python_sha256", "")).lower():
        raise ValueError("candidate Python runtime changed or is unavailable")

    root = Path(closure.get("code_root", "")).resolve()
    expected: set[Path] = set()
    source_ids: set[str] = set()
    for item in records:
        source_id = str(item.get("source_id", "")).replace("\\", "/")
        if source_id in source_ids:
            raise ValueError(f"duplicate frozen candidate source id: {source_id}")
        source_ids.add(source_id)
        relative = Path(source_id)
        path = (root / relative).resolve()
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or root not in path.parents
            or not path.is_file()
            or path.stat().st_size != item.get("bytes")
            or sha256(path).lower() != str(item.get("sha256", "")).lower()
        ):
            raise ValueError(f"frozen candidate source changed: {source_id}")
        expected.add(path)

    actual = {path.resolve() for path in root.rglob("*") if path.is_file()}
    if actual != expected:
        raise ValueError("candidate source closure has missing or extra files")


def frozen_source_path(closure: dict[str, Any], source_id: str) -> str:
    """Resolve a declared path; execution and publication verify the full closure."""
    if closure.get("schema_version") != 2 or closure.get("role") != ROLE:
        raise ValueError("invalid candidate source closure")
    normalized = source_id.replace("\\", "/")
    declared = [item["source_id"] for item in closure["sources"]]
    if len(declared) != len(set(declared)):
        raise ValueError("duplicate frozen candidate source id")
    if normalized not in declared:
        raise ValueError(f"undeclared candidate source id: {normalized}")
    root = Path(closure["code_root"]).resolve()
    relative = Path(normalized)
    path = (root / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or root not in path.parents:
        raise ValueError(f"invalid candidate source path: {normalized}")
    return str(path)


def _same_frozen_code(left: Any, right: Any) -> bool:
    """Compare compiled fields, including metadata ignored by code equality."""
    if type(left) is not type(right):
        return False
    if isinstance(left, types.CodeType):
        fields = (
            "co_argcount", "co_posonlyargcount", "co_kwonlyargcount", "co_nlocals",
            "co_stacksize", "co_flags", "co_code", "co_names", "co_varnames",
            "co_filename", "co_name", "co_qualname", "co_firstlineno",
            "co_linetable", "co_exceptiontable", "co_freevars", "co_cellvars", "co_consts",
        )
        return all(_same_frozen_code(getattr(left, key), getattr(right, key)) for key in fields)
    if isinstance(left, tuple):
        return len(left) == len(right) and all(_same_frozen_code(a, b) for a, b in zip(left, right))
    if isinstance(left, frozenset):
        return left == right
    # Scalars have no marshal object-reference layout; retain float bit patterns.
    return marshal.dumps(left) == marshal.dumps(right)


def derive_candidate_source_closure(
    parent_manifest_path: Path, parent_closure_path: Path, code_root: Path, *,
    embedded_candidate_plan: bool = False,
) -> dict[str, Any]:
    """Derive read-only parent evidence with authenticated CPython 3.11 caches.

    The normal verifier remains strict. No parent code or bytecode is executed;
    only declared sources enter the new evidence root. The caller owns terminal
    consumption guards and publishes the returned closure/derivation in its new run.
    embedded_candidate_plan selects only the known manifest-bound Candidate
    runtime-plan field; it does not synthesize a standalone historical closure.
    PEP 552 defines the timestamp header; Python's marshal warning requires the
    existing manifest identity check before decoding any cached code object.
    """
    parent_manifest_path = parent_manifest_path.resolve()
    parent_closure_path = parent_closure_path.resolve()
    code_root = code_root.resolve()
    parent = parent_manifest_path.parent
    manifest = json.loads(parent_manifest_path.read_bytes())
    if manifest.get("role") != "simulation_run_manifest" or manifest.get("status") not in {"success", "failed", "interrupted"}:
        raise ValueError("source derivation requires an explicit terminal parent manifest")
    bindings = [*manifest.get("inputs", {}).values(), *manifest.get("outputs", [])]

    def bound(path: Path) -> dict[str, Any]:
        records = [item for item in bindings if isinstance(item, dict) and record_path(item, base_dir=parent) == path]
        if not records or len({(item.get("bytes"), item.get("sha256")) for item in records}) != 1:
            raise ValueError(f"parent manifest lacks a unique source identity: {path}")
        record = {**records[0], "path": str(path)}
        try:
            verify_record("parent source derivation", record)
        except AssertionError as error:
            raise ValueError(str(error)) from error
        return record

    closure_record = bound(parent_closure_path)
    closure = json.loads(parent_closure_path.read_bytes())
    if type(embedded_candidate_plan) is not bool:
        raise ValueError("embedded Candidate plan selection must be boolean")
    if embedded_candidate_plan:
        if (closure.get("schema_version") != 1 or closure.get("role") != "oa_tof_candidate_run_plan"
                or closure.get("run_id") != parent.name or manifest.get("project") != PROJECT_ROOT.name
                or Path(str(closure.get("run_root", ""))).resolve() != parent
                or not isinstance(closure.get("execution_source_closure"), dict)):
            raise ValueError("parent source container is not the bound Candidate runtime plan")
        closure = closure["execution_source_closure"]
    source_root = Path(closure.get("code_root", "")).resolve()
    if parent not in source_root.parents or parent not in parent_closure_path.parents:
        raise ValueError("parent source closure escapes its run")
    if code_root.exists() or parent == code_root or parent in code_root.parents:
        raise ValueError("source derivation requires a fresh destination outside the parent")
    runtime = closure.get("runtime", {})
    runtime_path = Path(runtime.get("python_executable", "")).resolve()
    if sys.version_info[:2] != (3, 11) or sys.implementation.name != "cpython" or runtime_path != Path(sys.executable).resolve():
        raise ValueError("source derivation requires the bound CPython 3.11 runtime")
    if sha256(runtime_path).lower() != str(runtime.get("python_sha256", "")).lower():
        raise ValueError("parent Python runtime identity differs")
    # Validate every declared source using the unchanged verifier in a clean
    # destination; first collect bytes without allowing any unbound extra file.
    if closure.get("schema_version") != 2 or closure.get("role") != ROLE or not closure.get("sources"):
        raise ValueError("invalid parent candidate source closure")
    sources: dict[Path, bytes] = {}
    for item in closure["sources"]:
        relative = Path(item["source_id"])
        path = (source_root / relative).resolve()
        if relative.is_absolute() or ".." in relative.parts or source_root not in path.parents or path in sources:
            raise ValueError("invalid or duplicate parent frozen source")
        payload = path.read_bytes()
        if len(payload) != item["bytes"] or hashlib.sha256(payload).hexdigest().lower() != str(item["sha256"]).lower():
            raise ValueError(f"parent frozen source changed: {item['source_id']}")
        sources[path] = payload
    caches = []
    extras = {path.resolve() for path in source_root.rglob("*") if path.is_file()} - sources.keys()
    for path in sorted(extras):
        identity = bound(path)  # Authenticate before marshal; never trust arbitrary caches.
        try:
            source = Path(importlib.util.source_from_cache(str(path))).resolve()
        except ValueError as error:
            raise ValueError(f"unknown parent source extra: {path}") from error
        if source not in sources:
            raise ValueError(f"cached code lacks a declared source: {path}")
        expected_cache = Path(importlib.util.cache_from_source(str(source), optimization="")).resolve()
        if path != expected_cache:
            raise ValueError(f"unsupported parent bytecode cache name: {path}")
        payload = path.read_bytes()
        if len(payload) != identity["bytes"] or hashlib.sha256(payload).hexdigest().lower() != str(identity["sha256"]).lower():
            raise ValueError(f"parent bytecode changed while read: {path}")
        if len(payload) < 16 or payload[:4] != importlib.util.MAGIC_NUMBER or struct.unpack("<I", payload[4:8])[0] != 0:
            raise ValueError(f"unsupported parent bytecode header: {path}")
        if struct.unpack("<II", payload[8:16]) != (int(source.stat().st_mtime) & 0xFFFFFFFF, len(sources[source]) & 0xFFFFFFFF):
            raise ValueError(f"parent bytecode source metadata differs: {path}")
        stream = io.BytesIO(payload[16:])
        try:
            cached = marshal.load(stream)
        except (EOFError, ValueError, TypeError) as error:
            raise ValueError(f"invalid authenticated parent bytecode: {path}") from error
        rebuilt = compile(sources[source], str(source), "exec", dont_inherit=True, optimize=0)
        if stream.read() or not isinstance(cached, types.CodeType) or not _same_frozen_code(cached, rebuilt):
            raise ValueError(f"parent bytecode differs from frozen source: {path}")
        caches.append({"record": identity, "source_id": source.relative_to(source_root).as_posix(),
                       "validation": "bound_cpython311_timestamp_code_fields_equal"})
    code_root.mkdir(parents=True)
    for source, payload in sources.items():
        target = code_root / source.relative_to(source_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    derived = {**closure, "code_root": str(code_root)}
    verify_candidate_source_closure(derived)
    return {"closure": derived, "derivation": {
        "schema_version": 1, "role": "oa_tof_parent_source_closure_derivation",
        "parent_manifest": file_record(parent_manifest_path), "parent_closure": closure_record,
        **({"parent_closure_field": "execution_source_closure"} if embedded_candidate_plan else {}),
        "validated_bytecode": caches, "copied_sources": len(sources),
        "parent_modified": False, "bytecode_executed": False,
    }}
