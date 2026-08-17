"""Compile a frozen T5 theory result into a three-zone SIMION Candidate input.

The compiler is intentionally one-way: it verifies a hash-bound T5 receipt and
report, consumes their already-frozen primary row and branch root, and derives
the resolved ideal fields through :mod:`three_zone_ideal_theory`.  It never
searches for a root or ranks candidates.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import load_json, validate_schema
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    AffineSource,
    InnerSolution,
    OuterGeometry,
    ReflectronGeometry,
    compute_time_derivatives,
    derive_three_zone_state,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_theory_experiment import (
    load_campaign,
)


RECEIPT_SCHEMA = "oatof_three_zone_stage_receipt.schema.json"
REPORT_SCHEMA = "oatof_three_zone_stage_report.schema.json"
OUTPUT_SCHEMA = "oatof_three_zone_simion_candidate_resolved.schema.json"
SUPPORTED_T5_CONCLUSIONS = frozenset(
    {
        "PRIMARY_CONFIRMATION_PASSED_OVER_BEST_TWO_ZONE",
        "PRIMARY_THEORY_ONLY_SUPPORTED",
    }
)


def _file_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"bound file is missing: {resolved}")
    return {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": file_sha256(resolved),
    }


def _verify_bound_file(record: Mapping[str, Any], *, label: str) -> Path:
    path = Path(str(record["path"])).resolve()
    if not path.is_file():
        raise ValueError(f"{label} is missing: {path}")
    if path.stat().st_size != int(record["bytes"]):
        raise ValueError(f"{label} byte count differs from its receipt binding")
    if file_sha256(path) != str(record["sha256"]).upper():
        raise ValueError(f"{label} SHA-256 differs from its receipt binding")
    return path


def _finite_float(value: Any, *, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def _outer_values(record: Mapping[str, Any], *, label: str) -> dict[str, float]:
    names = ("d1_mm", "l23_mm", "lambda", "delta_v1_v")
    if set(record) != set(names):
        raise ValueError(f"{label} must contain exactly {names}")
    return {
        name: _finite_float(record[name], label=f"{label}.{name}") for name in names
    }


def _inner_values(record: Mapping[str, Any], *, label: str) -> dict[str, float]:
    names = ("eta", "u_r1_v", "f_r2_v_per_mm")
    if set(record) != set(names):
        raise ValueError(f"{label} must contain exactly {names}")
    return {
        name: _finite_float(record[name], label=f"{label}.{name}") for name in names
    }


def _frozen_primary(
    report: Mapping[str, Any], campaign: Mapping[str, Any], receipt: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, float], dict[str, float]]:
    rows = report.get("results", {}).get("rows")
    if not isinstance(rows, list):
        raise ValueError("T5 report results.rows must be an array")
    matching = [row for row in rows if row.get("row_id") == "frozen_primary"]
    if len(matching) != 1:
        raise ValueError("T5 report must contain exactly one frozen_primary row")
    row = matching[0]
    if not isinstance(row, dict) or row.get("row_status") != "accepted_unique_root":
        raise ValueError("frozen_primary must have accepted_unique_root status")

    row_outer = _outer_values(row.get("outer", {}), label="frozen_primary.outer")
    receipt_outer = _outer_values(
        receipt.get("frozen_primary") or {}, label="receipt.frozen_primary"
    )
    if row_outer != receipt_outer:
        raise ValueError("receipt frozen_primary does not exactly match the T5 row")

    row_inner = _inner_values(row.get("inner", {}), label="frozen_primary.inner")
    audit = row.get("branch_selection_audit")
    if not isinstance(audit, dict):
        raise ValueError("frozen_primary branch_selection_audit is missing")
    if audit.get("policy") != "scaled_parameter_distance_unique_nearest":
        raise ValueError("frozen_primary branch policy is not the frozen three-zone policy")
    if audit.get("performance_used") is not False:
        raise ValueError("frozen_primary branch selection must never use performance")
    if audit.get("machine_safe_tie") is not False:
        raise ValueError("frozen_primary branch selection is tied or not proven unique")
    expected_reference = campaign["root_policy"][
        "three_zone_branch_reference_fixture_id"
    ]
    if audit.get("reference_fixture_id") != expected_reference:
        raise ValueError("frozen_primary branch reference differs from the campaign")

    chosen_index = audit.get("chosen_accepted_index")
    if isinstance(chosen_index, bool) or not isinstance(chosen_index, int):
        raise ValueError("frozen_primary has no integer frozen branch index")
    summaries = audit.get("accepted_root_summaries")
    if not isinstance(summaries, list) or not 0 <= chosen_index < len(summaries):
        raise ValueError("frozen_primary frozen branch index is out of range")
    if row.get("workflow_accepted_root_count") != len(summaries):
        raise ValueError("frozen_primary accepted-root census differs from its audit")
    selected = summaries[chosen_index]
    if not isinstance(selected, dict) or selected.get("accepted_index") != chosen_index:
        raise ValueError("frozen_primary selected branch index is internally inconsistent")
    selected_inner = _inner_values(
        selected.get("inner", {}), label="frozen_primary.selected_branch.inner"
    )
    if selected_inner != row_inner:
        raise ValueError("frozen_primary row does not exactly match its frozen branch root")
    post_root = selected.get("post_root_audit")
    if not isinstance(post_root, dict) or post_root.get("workflow_post_root_passed") is not True:
        raise ValueError("frozen_primary selected branch did not pass its post-root audit")
    row_post_root = row.get("post_root_audit")
    if not isinstance(row_post_root, dict) or row_post_root.get(
        "workflow_post_root_passed"
    ) is not True:
        raise ValueError("frozen_primary row did not preserve a passing post-root audit")

    coordinates = selected.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) != 3:
        raise ValueError("frozen branch root must contain three scaled coordinates")
    for index, value in enumerate(coordinates):
        _finite_float(value, label=f"frozen branch coordinate {index}")
    distance = selected.get("distance_to_branch_reference")
    if distance is None or _finite_float(distance, label="branch distance") < 0.0:
        raise ValueError("frozen branch root must bind a non-negative branch distance")
    cluster_index = selected.get("cluster_index")
    if isinstance(cluster_index, bool) or not isinstance(cluster_index, int) or cluster_index < 0:
        raise ValueError("frozen branch root must bind a non-negative cluster index")
    return row, selected, row_outer, row_inner


def compile_t5_simion_candidate(
    campaign_path: Path, receipt_path: Path
) -> dict[str, Any]:
    """Return a schema-valid Candidate resolved mapping from frozen T5 evidence."""

    campaign_path = campaign_path.resolve()
    receipt_path = receipt_path.resolve()
    campaign = load_campaign(campaign_path)
    receipt = load_json(receipt_path)
    validate_schema(receipt, RECEIPT_SCHEMA)

    campaign_record = _file_record(campaign_path)
    receipt_record = _file_record(receipt_path)
    if receipt["campaign_id"] != campaign["campaign_id"]:
        raise ValueError("T5 receipt campaign_id differs from the supplied campaign")
    if receipt["campaign_sha256"] != campaign_record["sha256"]:
        raise ValueError("T5 receipt campaign SHA-256 differs from the supplied campaign")
    if receipt["stage_id"] != "T5" or receipt["status"] != "success":
        raise ValueError("only a successful T5 receipt can compile a Candidate")
    if receipt["conclusion"] not in SUPPORTED_T5_CONCLUSIONS:
        raise ValueError("T5 conclusion does not support a Candidate handoff")

    report_path = _verify_bound_file(receipt["report"], label="T5 stage report")
    if report_path.parent != receipt_path.parent:
        raise ValueError("T5 receipt and its bound report must share one run directory")
    report = load_json(report_path)
    validate_schema(report, REPORT_SCHEMA)
    if report["campaign_id"] != receipt["campaign_id"]:
        raise ValueError("T5 report campaign_id differs from its receipt")
    if report["stage_id"] != receipt["stage_id"]:
        raise ValueError("T5 report stage_id differs from its receipt")
    if report["plan_sha256"] != receipt["plan_sha256"]:
        raise ValueError("T5 report plan SHA-256 differs from its receipt")
    if report["status"] != receipt["status"]:
        raise ValueError("T5 report status differs from its receipt")
    if report["scientific_assessment"] != receipt["conclusion"]:
        raise ValueError("T5 report assessment differs from its receipt conclusion")
    if report["claim_limit"] != receipt["claim_limit"]:
        raise ValueError("T5 report claim limit differs from its receipt")

    primary_row, branch, outer_values, inner_values = _frozen_primary(
        report, campaign, receipt
    )
    source_record = campaign["frozen_source"]
    source = AffineSource.from_velocity(
        mass_to_charge_th=float(source_record["mass_to_charge_th"]),
        center_x_mm=float(source_record["center_x_mm"]),
        center_velocity_m_per_s=float(source_record["center_velocity_m_per_s"]),
        velocity_slope_m_per_s_per_mm=float(
            source_record["velocity_slope_m_per_s_per_mm"]
        ),
    )
    outer = OuterGeometry(
        zone1_length_mm=outer_values["d1_mm"],
        downstream_length_mm=outer_values["l23_mm"],
        split_fraction=outer_values["lambda"],
        zone1_voltage_drop_v=outer_values["delta_v1_v"],
        nominal_energy_per_charge_v=float(
            source_record["nominal_energy_per_charge_v"]
        ),
    )
    inner = InnerSolution(
        stage1_voltage_drop_v=inner_values["u_r1_v"],
        stage2_field_v_per_mm=inner_values["f_r2_v_per_mm"],
        eta=inner_values["eta"],
    )
    reflectron_record = campaign["reflectron_geometry"]
    reflectron = ReflectronGeometry(
        stage1_length_mm=float(reflectron_record["stage1_length_mm"]),
        stage2_length_mm=float(reflectron_record["stage2_length_mm"]),
        upstream_drift_mm=float(reflectron_record["upstream_drift_mm"]),
        downstream_drift_mm=float(reflectron_record["downstream_drift_mm"]),
    )
    state = derive_three_zone_state(source, outer, inner.eta)
    derivatives = compute_time_derivatives(source, state, reflectron, inner)

    recorded_contrast = _finite_float(
        primary_row.get("accelerator_field_contrast"),
        label="frozen_primary.accelerator_field_contrast",
    )
    derived_contrast = max(
        state.field_ratio_2_over_3, 1.0 / state.field_ratio_2_over_3
    )
    if recorded_contrast != derived_contrast:
        raise ValueError("frozen_primary field contrast differs from exact theory")

    focus_drift = derivatives.focus_drift_after_exit_mm
    exit_z = -focus_drift
    intermediate2_z = exit_z - state.zone3_length_mm
    intermediate1_z = intermediate2_z - state.zone2_length_mm
    repeller_z = intermediate1_z - state.zone1_length_mm
    branch_root = {
        "policy": "scaled_parameter_distance_unique_nearest",
        "reference_fixture_id": campaign["root_policy"][
            "three_zone_branch_reference_fixture_id"
        ],
        "accepted_index": int(branch["accepted_index"]),
        "cluster_index": int(branch["cluster_index"]),
        "coordinates": [float(value) for value in branch["coordinates"]],
        "distance_to_branch_reference": float(
            branch["distance_to_branch_reference"]
        ),
        "inner": inner_values,
    }
    report_record = _file_record(report_path)
    result = {
        "schema_version": 1,
        "role": "oatof_three_zone_simion_candidate_resolved",
        "project_id": "single_reflection_oa_tof_mass_analyzer",
        "qualification": "CANDIDATE_ONLY",
        "compiler_mode": "T5_FROZEN_PRIMARY_AND_BRANCH_ONLY",
        "campaign": {
            "campaign_id": campaign["campaign_id"],
            "file": campaign_record,
        },
        "t5_evidence": {
            "stage_id": "T5",
            "status": "success",
            "conclusion": receipt["conclusion"],
            "plan_sha256": receipt["plan_sha256"],
            "receipt": receipt_record,
            "report": report_record,
            "frozen_primary_row_id": "frozen_primary",
            "frozen_branch_root": branch_root,
        },
        "source_identity": {
            "authority": "campaign.frozen_source",
            "campaign_id": campaign["campaign_id"],
            "campaign_sha256": campaign_record["sha256"],
            "frozen_source": dict(source_record),
        },
        "identities": {
            "topology_id": "three_zone_accelerator_ideal_v1",
            "geometry_id": "three_zone_focus_origin_planes_v1",
            "field_id": "three_zone_piecewise_uniform_ideal_field_v1",
        },
        "accelerator_topology": {
            "topology_id": "three_zone_accelerator_ideal_v1",
            "planes_global_z_mm": {
                "repeller": repeller_z,
                "intermediate1": intermediate1_z,
                "intermediate2": intermediate2_z,
                "exit": exit_z,
            },
            "potentials_v": {
                "repeller": state.repeller_v,
                "intermediate1": state.grid1_v,
                "intermediate2": state.grid2_v,
                "exit": state.exit_v,
            },
        },
        "accelerator_physics": {
            "lengths_mm": {
                "d1": state.zone1_length_mm,
                "d2": state.zone2_length_mm,
                "d3": state.zone3_length_mm,
            },
            "fields_v_per_mm": {
                "e1": state.field1_v_per_mm,
                "e2": state.field2_v_per_mm,
                "e3": state.field3_v_per_mm,
            },
            "focus_drift_after_exit_mm": focus_drift,
        },
        "reflectron": {
            "u_r1_v": inner.stage1_voltage_drop_v,
            "f_r2_v_per_mm": inner.stage2_field_v_per_mm,
        },
        "claim_limit": (
            "Candidate-only ideal three-zone resolved input; no SIMION execution, "
            "real-field qualification, manufacturing qualification, or Formal promotion."
        ),
    }
    validate_schema(result, OUTPUT_SCHEMA)
    return result


def write_t5_simion_candidate(
    campaign_path: Path, receipt_path: Path, output_path: Path
) -> dict[str, Any]:
    """Compile and exclusively write one Candidate resolved JSON document."""

    result = compile_t5_simion_candidate(campaign_path, receipt_path)
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    """Run the narrow T5-to-Candidate compiler command line."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--t5-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)
    write_t5_simion_candidate(
        arguments.campaign, arguments.t5_receipt, arguments.output
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
