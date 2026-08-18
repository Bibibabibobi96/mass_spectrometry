"""Publish a detector-blind ballistic connector-gap screen."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np

from common.contracts.artifact_naming import validate_run_id
from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.run_publication import (
    freeze_repository_inputs,
    portable_path,
    publish_manifest,
    write_pending_json,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_layout import (
    project_handoff_through_connector,
)


INTEGRATION_ID = "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
MODE = "detector_blind_connector_gap_screen"


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ContractError(f"{path.name} must contain one JSON object")
    return value


def _bound_path(record: Any, base: Path, label: str) -> Path:
    if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
        raise ContractError(f"{label} file record differs")
    path = Path(str(record["path"]))
    path = path.resolve() if path.is_absolute() else (base / path).resolve()
    if not path.is_file() or file_sha256(path) != record["sha256"]:
        raise ContractError(f"{label} file identity differs")
    return path


def _id_digest(ids: list[int]) -> str:
    payload = json.dumps(ids, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest().upper()


def _residual_summary(z: np.ndarray, vz: np.ndarray) -> dict[str, float | int]:
    if len(z) < 2 or len(z) != len(vz):
        raise ContractError("z0-vz residual requires at least two particles")
    design = np.column_stack((np.ones(len(z)), z))
    intercept, slope = np.linalg.lstsq(design, vz, rcond=None)[0]
    residual = vz - (intercept + slope * z)
    return {
        "particle_count": len(z),
        "fit_intercept_m_s": float(intercept),
        "fit_slope_m_s_per_mm": float(slope),
        "residual_rms_m_s": float(np.sqrt(np.mean(residual**2))),
        "residual_sample_sigma_m_s": float(np.std(residual, ddof=1)),
    }


def analyze_request(contract_path: Path) -> tuple[dict[str, Any], dict[str, Path]]:
    contract_path = contract_path.resolve()
    contract = _load_json(contract_path)
    if (
        contract.get("role") != "rf_oatof_detector_blind_connector_gap_screen_request"
        or contract.get("detector_results_used") is not False
        or contract.get("selection_uses_detector_outcome") is not False
    ):
        raise ContractError("connector-gap request is not detector-blind")
    base = contract_path.parent
    state_path = _bound_path(contract.get("source_state"), base, "source state")
    geometry_path = _bound_path(contract.get("geometry"), base, "geometry")
    candidates = contract.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ContractError("connector-gap matrix is empty")
    gaps = [float(candidate["gap_mm"]) for candidate in candidates]
    if gaps != sorted(set(gaps)) or any(not np.isfinite(gap) or gap < 0 for gap in gaps):
        raise ContractError("connector-gap matrix must be finite, unique, and ordered")
    with state_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    source_rows = [row for row in rows if row["event"] == "source"]
    handoff_rows = [
        row for row in rows if row["event"] == "handoff" and row["status"] == "transmitted"
    ]
    if not source_rows or not handoff_rows:
        raise ContractError("connector-gap source lacks S0 or transmitted handoff rows")
    source_by_id = {int(row["particle_id"]): row for row in source_rows}
    handoff_by_id = {int(row["particle_id"]): row for row in handoff_rows}
    if len(source_by_id) != len(source_rows):
        raise ContractError("S0 particle identities are not unique")
    geometry = _load_json(geometry_path)
    inputs = {"request": contract_path, "source_state": state_path, "geometry": geometry_path}
    result_rows = []
    for candidate in candidates:
        gap = float(candidate["gap_mm"])
        connection_path = _bound_path(
            candidate.get("resolved_connection"), base, f"gap {gap} resolved connection"
        )
        inputs[f"resolved_connection_gap_{format(gap, '.12g')}"] = connection_path
        projected = project_handoff_through_connector(
            handoff_rows, _load_json(connection_path), geometry
        )
        if not math.isclose(
            float(projected["actual_gap_mm"]), gap, rel_tol=0.0, abs_tol=1e-12
        ):
            raise ContractError("candidate gap differs from resolved actual gap")
        candidates_at_plane = sorted(
            projected["handoff_candidates"], key=lambda row: int(row["particle_id"])
        )
        survivors = sorted(
            projected["finite_wall_survivors"], key=lambda row: int(row["particle_id"])
        )
        ids = [int(row["particle_id"]) for row in survivors]
        survivor_handoff = [handoff_by_id[particle_id] for particle_id in ids]
        half_y = float(projected["aperture_half_width_y_mm"])
        half_z = float(projected["aperture_half_height_z_mm"])
        center = projected["aperture_center_mm"]
        angles = [
            np.hypot(float(row["vy_m_s"]), float(row["vz_m_s"]))
            / float(row["vx_m_s"])
            for row in survivors
        ]
        margins = [
            min(
                1.0 - abs(float(row["outer_y_mm"]) - center[1]) / half_y,
                1.0 - abs(float(row["outer_z_mm"]) - center[2]) / half_z,
                1.0 - abs(float(row["inner_y_mm"]) - center[1]) / half_y,
                1.0 - abs(float(row["inner_z_mm"]) - center[2]) / half_z,
            )
            for row in survivors
        ]
        geometric_y = [float(row["outer_y_mm"]) - center[1] for row in candidates_at_plane]
        geometric_z = [float(row["outer_z_mm"]) - center[2] for row in candidates_at_plane]
        aperture_z = np.asarray([float(row["outer_z_mm"]) for row in survivors])
        aperture_vz = np.asarray([float(row["vz_m_s"]) for row in survivors])
        stage_ids = {
            "S0": sorted(source_by_id),
            "transmitted_handoff": sorted(handoff_by_id),
            "aperture_plane_forward": [int(row["particle_id"]) for row in candidates_at_plane],
            "finite_wall_survivors": ids,
        }
        result_rows.append({
            "gap_mm": gap,
            "counts": {
                "S0": len(source_rows), "transmitted_handoff": len(handoff_rows),
                "aperture_plane_forward": len(candidates_at_plane),
                "finite_wall_survivors": len(survivors),
            },
            "stage_particle_identity": {
                stage: {"ordered_particle_ids": values, "ordered_particle_ids_sha256": _id_digest(values)}
                for stage, values in stage_ids.items()
            },
            "initial_z0_vz_residual": {
                "population": "finite_wall_survivor_ids_at_common_handoff",
                **_residual_summary(
                    np.asarray([
                        float(row["transverse_y_mm"]) for row in survivor_handoff
                    ]),
                    np.asarray([
                        float(row["velocity_y_m_s"]) for row in survivor_handoff
                    ]),
                ),
            },
            "aperture_plane_geometric_residual": {
                "definition": "vz_regressed_on_intercept_and_outer_aperture_plane_z_L",
                "vz_on_z_L_regression": _residual_summary(aperture_z, aperture_vz),
                "coordinate_offset_from_aperture_center": {
                "y_rms_mm": float(np.sqrt(np.mean(np.square(geometric_y)))),
                "z_rms_mm": float(np.sqrt(np.mean(np.square(geometric_z)))),
                "y_max_abs_mm": float(np.max(np.abs(geometric_y))),
                "z_max_abs_mm": float(np.max(np.abs(geometric_z))),
                },
            },
            "q90_transverse_angle_rad": float(np.quantile(angles, 0.90)),
            "q05_normalized_finite_wall_margin": float(np.quantile(margins, 0.05)),
        })
    return {
        "schema_version": 1,
        "role": "rf_oatof_detector_blind_connector_gap_screen",
        "status": "PASS",
        "detector_results_used": False,
        "selection_uses_detector_outcome": False,
        "matrix_gap_mm": gaps,
        "common_handoff_all_particle_z0_vz_residual": _residual_summary(
            np.asarray([float(row["transverse_y_mm"]) for row in handoff_rows]),
            np.asarray([float(row["velocity_y_m_s"]) for row in handoff_rows]),
        ),
        "candidates": result_rows,
    }, inputs


def publish(repo_root: Path, contract_path: Path, run_id: str) -> Path:
    validate_run_id(run_id)
    repo_root, workspace = repo_root.resolve(), repo_root.resolve().parent
    run_dir = workspace / "artifacts" / "projects" / INTEGRATION_ID / "runs" / run_id
    if run_dir.exists():
        raise ContractError(f"analysis run already exists: {run_dir}")
    result, inputs = analyze_request(contract_path)
    inputs["implementation"] = Path(__file__).resolve()
    run_dir.mkdir(parents=True)
    frozen = freeze_repository_inputs(inputs, repo_root=repo_root, run_dir=run_dir)
    config_path = run_dir / "run_config.json"
    result_path = run_dir / "results" / "connector_gap_screen.json"
    summary_path = run_dir / "summary.json"
    manifest_path = run_dir / "run_manifest.json"
    write_pending_json(config_path, {
        "schema_version": 2, "run_id": run_id, "project": INTEGRATION_ID,
        "mode": MODE, "project_root": str(workspace),
        "inputs": {key: portable_path(path, workspace) for key, path in frozen.items()},
        "parameters": {"detector_results_used": False, "matrix_gap_mm": result["matrix_gap_mm"]},
        "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
        "formal_gate_passed": False,
    })
    write_pending_json(result_path, result)
    write_pending_json(summary_path, {
        "schema_version": 1, "role": "rf_oatof_connector_gap_screen_summary",
        "status": "success", "analysis_status": "DETECTOR_BLIND_FUNCTIONAL_ONLY",
        "result": portable_path(result_path, run_dir), "formal_gate_passed": False,
    })
    pending = manifest_path.with_name(".run_manifest.json.pending")
    publish_manifest(
        repo_root=repo_root, run_config=config_path, manifest_path=pending,
        status="success", outputs=(result_path, summary_path), project=INTEGRATION_ID,
        mode=MODE, label="connector-gap-screen",
    )
    os.replace(pending, manifest_path)
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(f"CONNECTOR_GAP_SCREEN=PASS MANIFEST={publish(args.repo_root, args.request, args.run_id)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
