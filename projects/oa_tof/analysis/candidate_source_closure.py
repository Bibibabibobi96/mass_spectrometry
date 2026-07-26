"""Freeze and verify the executable source closure of an oa-TOF candidate run."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import sha256


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
ROLE = "oa_tof_candidate_execution_source_closure"

# This is intentionally an auditable allowlist, not dependency discovery.
# Keep paths repository-relative and use forward slashes in the machine record.
RELATIVE_PATHS = (
    "common/comsol/livelink_environment.ps1",
    "common/comsol/livelink_failure_classification.ps1",
    "common/comsol/livelink_r2025b/comsolstartup.m",
    "common/comsol/resolve_comsol_64.ps1",
    "common/comsol/run_comsol_r2025b.ps1",
    "common/contracts/artifact_naming.py",
    "common/contracts/particle_count_policy.json",
    "common/contracts/particle_count_policy.py",
    "common/require_powershell7.ps1",
    "common/solidworks/import_step_to_solidworks.m",
    "common/solidworks/import_step_to_solidworks.py",
    "common/solidworks/installation.py",
    "projects/oa_tof/analysis/generate_ion_source.py",
    "projects/oa_tof/cad/export_oatof_cad_step.m",
    "projects/oa_tof/cad/ms_export_oatof_to_solidworks.m",
    "projects/oa_tof/cad/oatof_cad_export_manifest.m",
    "projects/oa_tof/comsol/configure_oatof_segmented_output.m",
    "projects/oa_tof/comsol/ms_oaTOF_two_stage_ringstack_reflectron.m",
    "projects/oa_tof/comsol/oatof_build_accelerator_geometry.m",
    "projects/oa_tof/comsol/oatof_build_detector_geometry.m",
    "projects/oa_tof/comsol/oatof_build_drift_geometry.m",
    "projects/oa_tof/comsol/oatof_build_grid_geometry.m",
    "projects/oa_tof/comsol/oatof_build_mesh.m",
    "projects/oa_tof/comsol/oatof_build_model_core.m",
    "projects/oa_tof/comsol/oatof_build_reflectron_geometry.m",
    "projects/oa_tof/comsol/oatof_configure_particle_model.m",
    "projects/oa_tof/comsol/oatof_create_result_nodes.m",
    "projects/oa_tof/comsol/oatof_extract_detector_arrivals.m",
    "projects/oa_tof/comsol/oatof_parse_field_idealization.m",
    "projects/oa_tof/comsol/run_oatof_model.m",
    "projects/oa_tof/docs/SIMION_REPRODUCTION_PARAMETERS.md",
    "projects/oa_tof/load_oatof_contract.m",
    "projects/oa_tof/oatof_lifecycle_preflight.ps1",
    "projects/oa_tof/oatof_assert_formal_write_authorized.m",
    "projects/oa_tof/oatof_paths.m",
    "projects/oa_tof/simion/accelerator/build_accelerator_variant.lua",
    "projects/oa_tof/simion/accelerator/oatof_accelerator_3d.gem",
    "projects/oa_tof/simion/reflectron/build_reflectron_variant.lua",
    "projects/oa_tof/simion/reflectron/oatof_reflectron_ideal_10_5.gem",
    "projects/oa_tof/simion/workbench/build_detector_variant.lua",
    "projects/oa_tof/simion/workbench/build_flight_tube_variant.lua",
    "projects/oa_tof/simion/workbench/generate_comsol_consistent_ions.ps1",
    "projects/oa_tof/simion/workbench/analyze_ideal_field_log.ps1",
    "projects/oa_tof/simion/workbench/build_formal_delivery.ps1",
    "projects/oa_tof/simion/workbench/build_formal_iob.lua",
    "projects/oa_tof/simion/workbench/run_n100_transport.ps1",
    "projects/oa_tof/simion/workbench/oatof_detector_ground.gem",
    "projects/oa_tof/simion/workbench/oatof_flight_tube_ground.gem",
    "projects/oa_tof/workflows/design_candidate/run_candidate_cad_sync.m",
    "projects/oa_tof/workflows/design_candidate/run_candidate_contract_build.m",
    "projects/oa_tof/tests/comsol/verify_oatof_comsol_sync.m",
    "projects/oa_tof/tests/simion/verify_iob_runtime_contract.lua",
    "projects/oa_tof/tests/simion/verify_iob_runtime_contract.ps1",
    "projects/oa_tof/analysis/solver_diagnostics.py",
)

PYTHON_BOUND_SOURCES = frozenset({
    "projects/oa_tof/simion/workbench/generate_comsol_consistent_ions.ps1",
    "projects/oa_tof/simion/workbench/analyze_ideal_field_log.ps1",
    "projects/oa_tof/simion/workbench/build_formal_delivery.ps1",
})
PYTHON_ASSIGNMENT = "$python = Join-Path $repoRoot '.venv\\Scripts\\python.exe'"
WORKSPACE_ASSIGNMENT = "    workspaceRoot = fileparts(repoRoot);"


def _source_path(source_id: str) -> Path:
    relative = Path(source_id)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"invalid candidate source path: {source_id}")
    source = (REPO_ROOT / relative).resolve()
    if not source.is_file() or REPO_ROOT not in source.parents:
        raise ValueError(f"candidate source is absent or escapes repository: {source_id}")
    return source


def _bind_python_runtime(payload: bytes, python_executable: Path) -> bytes:
    text = payload.decode("utf-8")
    if text.count(PYTHON_ASSIGNMENT) != 1:
        raise ValueError("candidate PowerShell source has an unexpected Python binding")
    escaped = str(python_executable).replace("'", "''")
    replacement = f"$python = '{escaped}' # frozen candidate runtime binding"
    return text.replace(PYTHON_ASSIGNMENT, replacement).encode("utf-8")


def freeze_candidate_source_closure(
    code_root: Path,
    artifact_root: Path,
    python_executable: Path | None = None,
) -> dict[str, Any]:
    """Copy the declared closure and return its immutable execution record."""
    code_root = code_root.resolve()
    python_path = Path(python_executable or sys.executable).resolve()
    if not python_path.is_file():
        raise ValueError(f"candidate Python runtime is unavailable: {python_path}")
    artifact_path = artifact_root.resolve()

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for declared in RELATIVE_PATHS:
        source_id = declared.replace("\\", "/")
        if source_id in seen:
            raise ValueError(f"duplicate candidate source id: {source_id}")
        seen.add(source_id)
        source = _source_path(source_id)
        source_digest = sha256(source)
        payload = source.read_bytes()
        if sha256(source) != source_digest:
            raise ValueError(f"candidate source changed while frozen: {source_id}")

        transformations: list[str] = []
        if source_id in PYTHON_BOUND_SOURCES:
            payload = _bind_python_runtime(payload, python_path)
            transformations.append("python_runtime_binding")
        if source_id == "projects/oa_tof/oatof_paths.m":
            text = payload.decode("utf-8")
            if text.count(WORKSPACE_ASSIGNMENT) != 1:
                raise ValueError("candidate MATLAB paths source has an unexpected workspace binding")
            workspace_path = artifact_path.parents[2]
            matlab_path = str(workspace_path).replace("'", "''")
            payload = text.replace(
                WORKSPACE_ASSIGNMENT,
                f"    workspaceRoot = '{matlab_path}'; % frozen candidate workspace binding",
            ).encode("utf-8")
            transformations.append("candidate_workspace_root_binding")

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
    """Resolve one declared frozen source after verifying the whole closure."""
    verify_candidate_source_closure(closure)
    normalized = source_id.replace("\\", "/")
    declared = {item["source_id"] for item in closure["sources"]}
    if normalized not in declared:
        raise ValueError(f"undeclared candidate source id: {normalized}")
    return str(Path(closure["code_root"]) / normalized)
