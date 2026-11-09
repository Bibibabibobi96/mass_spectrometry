"""Read a sealed RF transport result without executing a solver."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from msplatform.contracts.machine_contracts import ContractError, validate_schema
from msplatform.io.manifest_records import record_path, verify_record


def load_transport_producer_result(manifest: Mapping[str, Any], base: Path) -> dict[str, Any]:
    """Read the sealed transport result, separating complete states from qualification.

    A normal successful transport publication already proves execution completion.
    A scientific failure additionally requires the explicit normal-path completion
    declaration and the manifest-bound current evidence evaluation. Generic failed
    or interrupted publications do not qualify as measured-state producers.
    """
    status = manifest.get("status")
    if status not in {"success", "failed"}:
        raise ContractError("transport producer must have a complete scientific result")
    run = record_path(manifest["run_config"], base_dir=base).parent
    summary_path = run / "summary.json"
    evaluation_path = run / "results/evidence_evaluation.json"
    selected = {}
    for record in manifest.get("outputs", []):
        path = record_path(record, base_dir=base)
        if path in {summary_path, evaluation_path}:
            if path in selected:
                raise ContractError("transport result must have one manifest record per consumed file")
            selected[path] = record

    consumed = {}

    def read_result(path: Path, name: str) -> dict:
        if path not in selected:
            raise ContractError("transport manifest lacks its " + name)
        record = selected[path]
        verify_record(name, record, base_dir=base)
        consumed[name] = {**record, "path": str(path)}
        return json.loads(path.read_text(encoding="utf-8-sig"))

    summary = read_result(summary_path, "summary")
    if (summary.get("schema_version") != 1
            or summary.get("role") != "multipole_simion_finite_3d_transport_summary"
            or summary.get("status") != status or summary.get("project_id") != manifest["project"]
            or not isinstance(summary.get("design_profile_id"), str)
            or not summary["design_profile_id"]
            or ("native_execution_complete" in summary and summary["native_execution_complete"] is not True)):
        raise ContractError("transport summary identity or completion differs")
    qualification = summary.get("qualification_status")
    if "checks" in summary and (not isinstance(summary["checks"], dict)
                                or any(type(value) is not bool for value in summary["checks"].values())):
        raise ContractError("transport summary checks must be declared boolean results")
    checks = {}
    if status == "failed" and (summary.get("native_execution_complete") is not True
                               or qualification != "FAIL" or "checks" not in summary):
        raise ContractError("failed transport lacks a complete native scientific-result declaration")
    if qualification in {"PASS", "FAIL"}:
        evaluation = read_result(evaluation_path, "evidence_evaluation")
        validate_schema(evaluation, "multipole_evidence_evaluation.schema.json")
        checks = evaluation["checks"]
        expected = "PASS" if all(checks.values()) else "FAIL"
        if (evaluation["project_id"] != summary["project_id"]
                or evaluation["design_profile_id"] != summary["design_profile_id"]
                or evaluation["status"] != expected or qualification != expected
                or status != ("success" if expected == "PASS" else "failed")
                or ("checks" in summary and summary["checks"] != checks)):
            raise ContractError("transport scientific checks or qualification differ")
    elif qualification != "UNQUALIFIED" or status != "success" or summary.get("checks", {}):
        raise ContractError("transport qualification is not its declared scientific result")
    return dict(source_scientific_status=status, checks=checks,
                qualification_status=qualification, input_records=consumed)
