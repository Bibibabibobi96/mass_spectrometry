"""Read a versioned historical cross-solver record with explicit evidence roots."""

from __future__ import annotations

import json
from pathlib import Path

from msplatform.analysis.cross_solver_validation import validate_cross_solver_metrics
from msplatform.io.file_identity import file_sha256

PROJECT_ID = "single_reflection_oa_tof_mass_analyzer"


def require_hash(path: Path, expected: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    actual = file_sha256(path)
    if actual != expected:
        raise ValueError(f"SHA-256 mismatch for {path}: {actual} != {expected}")


def require_artifact_references(node: object, artifact_root: Path) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key.endswith("artifact_relative_path"):
                hash_candidates = (
                    key[: -len("_relative_path")] + "_sha256",
                    key[: -len("_artifact_relative_path")] + "_sha256",
                )
                hash_key = next(
                    (candidate for candidate in hash_candidates if candidate in node),
                    None,
                )
                if hash_key is None:
                    raise ValueError(
                        f"Missing one of {hash_candidates} beside {key}"
                    )
                require_hash(artifact_root / str(value), str(node[hash_key]))
            else:
                require_artifact_references(value, artifact_root)
    elif isinstance(node, list):
        for value in node:
            require_artifact_references(value, artifact_root)


def read_cross_solver_record(config_path: Path, artifact_root: Path) -> dict:
    """Decode and validate an explicit historical record; never execute its producer."""

    config_path = config_path.resolve(strict=True)
    project_dir = config_path.parent.parent
    record = json.loads(config_path.read_text(encoding="utf-8"))
    if type(record.get("schema_version")) is not int or record["schema_version"] not in {1, 2, 3, 4, 5}:
        raise ValueError("Unsupported historical cross-solver record version")
    if record["status"] != "formal_cross_solver_validation":
        raise ValueError("Formal validation record is not active")

    require_hash(
        project_dir / "config" / record["physical_contract"],
        record["physical_contract_sha256"],
    )
    require_hash(
        project_dir / "config" / record["analysis_contract"],
        record["analysis_contract_sha256"],
    )
    require_artifact_references(record, artifact_root)
    if record.get("schema_version", 0) < 4:
        diagnostics = record.get("diagnostics", {})
        if diagnostics.get("status") != "peak_shoulder_source_localized":
            raise ValueError("Formal peak-shoulder diagnostic is not localized")
    else:
        validation_scope = record.get("validation_scope")
        allowed_scopes = {
            "direct_rerun_of_current_formal_comsol_and_simion_assets",
            "validated_candidate_assets_promoted_atomically_to_current_formal",
        }
        if validation_scope not in allowed_scopes:
            raise ValueError(f"Unsupported formal validation scope: {validation_scope}")
        if validation_scope == "validated_candidate_assets_promoted_atomically_to_current_formal":
            promotion = record.get("promotion_evidence")
            if not isinstance(promotion, dict):
                raise ValueError("Promoted formal validation lacks promotion evidence")
            required_paths = (
                (
                    "validation_run_manifest_artifact_relative_path",
                    "evidence_run_manifest_artifact_relative_path",
                    "comsol_gui_artifact_relative_path",
                    "simion_gui_artifact_relative_path",
                    "cad_artifact_relative_path",
                )
                if record.get("schema_version", 0) >= 5
                else (
                    "validation_run_manifest_artifact_relative_path",
                    "comsol_promotion_report_artifact_relative_path",
                    "cad_sync_report_artifact_relative_path",
                )
            )
            for key in required_paths:
                if key not in promotion:
                    raise ValueError(f"Promoted formal validation lacks {key}")
            manifest_keys = ["validation_run_manifest_artifact_relative_path"]
            if record.get("schema_version", 0) >= 5:
                manifest_keys.append("evidence_run_manifest_artifact_relative_path")
            for key in manifest_keys:
                source_manifest = json.loads(
                    (artifact_root / promotion[key]).read_text(encoding="utf-8-sig")
                )
                if source_manifest.get("status") != "success":
                    raise ValueError(f"Promotion source run is not successful: {promotion[key]}")
            if record.get("schema_version", 0) >= 5:
                expected_roles = {
                    "comsol_gui_artifact_relative_path": "oa_tof_comsol_gui_gate",
                    "simion_gui_artifact_relative_path": "oa_tof_simion_gui_gate",
                    "cad_artifact_relative_path": "oa_tof_cad_gate",
                }
                for key, expected_role in expected_roles.items():
                    evidence = json.loads(
                        (artifact_root / promotion[key]).read_text(
                            encoding="utf-8-sig"
                        )
                    )
                    if (
                        evidence.get("schema_version") != 1
                        or evidence.get("role") != expected_role
                        or evidence.get("project") != PROJECT_ID
                        or evidence.get("status") != "PASS"
                    ):
                        raise ValueError(f"GUI/CAD evidence is not PASS: {promotion[key]}")
            else:
                for key in (
                    "comsol_promotion_report_artifact_relative_path",
                    "cad_sync_report_artifact_relative_path",
                ):
                    report = (
                        artifact_root / promotion[key]
                    ).read_text(encoding="utf-8-sig")
                    if "STATUS=PASS" not in report.splitlines():
                        raise ValueError(f"Promotion report is not PASS: {promotion[key]}")
    comparison_path = artifact_root / record["comparison_artifact_relative_path"]
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    validate_cross_solver_metrics(record, comparison)
    return {"schema_version": 1, "role": "historical_cross_solver_comparison",
            "historical_schema_version": record["schema_version"], "comparison": comparison}
