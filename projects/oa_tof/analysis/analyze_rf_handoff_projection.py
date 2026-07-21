"""Normalize RF->oa-TOF detector results and evaluate the functional candidate."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from statistics import fmean
from typing import Any

from prepare_rf_handoff_projection import DEFAULT_MODE, load_json, validate_mode


DETECTOR_COLUMNS = [
    "upstream_case_id",
    "upstream_solver",
    "downstream_solver",
    "solver_row_index",
    "particle_id",
    "clock_epoch_id",
    "handoff_instrument_time_us",
    "handoff_lineage_age_us",
    "handoff_particle_age_us",
    "local_oatof_tof_us",
    "detector_instrument_time_us",
    "detector_lineage_age_us",
    "detector_particle_age_us",
    "hit",
    "detector_x_mm",
    "detector_y_mm",
    "detector_radius_mm",
]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes"}


def symmetric_relative_difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    denominator = abs(left) + abs(right)
    return 0.0 if denominator == 0 else 2.0 * abs(left - right) / denominator


def _normalize_case(
    case: dict[str, Any],
    detector_x_mm: float,
    detector_y_mm: float,
    detector_radius_mm: float,
) -> list[dict[str, Any]]:
    canonical = {int(row["particle_id"]): row for row in _read_csv(Path(case["canonical"]))}
    row_map = {int(row["solver_row_index"]): row for row in _read_csv(Path(case["row_map"]))}
    normalized: list[dict[str, Any]] = []
    for downstream_solver, result_path in case["downstream_results"].items():
        results = _read_csv(Path(result_path))
        if len(results) != len(row_map):
            raise ValueError(f"{case['case_id']} {downstream_solver} result count differs from row map")
        seen_rows: set[int] = set()
        for result in results:
            row_index = int(result["Ion"])
            if row_index in seen_rows or row_index not in row_map:
                raise ValueError("downstream solver rows must map one-to-one onto the handoff bundle")
            seen_rows.add(row_index)
            mapping = row_map[row_index]
            particle_id = int(mapping["particle_id"])
            state = canonical[particle_id]
            solver_hit = _as_bool(result["Hit"])
            local_tof_value = float(result["TofUs"])
            x_value = float(result["XMm"])
            y_value = float(result["YMm"])
            if solver_hit and (not math.isfinite(local_tof_value) or local_tof_value <= 0):
                raise ValueError("hit detector time must be finite and positive")
            local_tof = local_tof_value if math.isfinite(local_tof_value) else None
            x_mm = x_value if math.isfinite(x_value) else None
            y_mm = y_value if math.isfinite(y_value) else None
            radius = (
                math.hypot(x_mm - detector_x_mm, y_mm - detector_y_mm)
                if x_mm is not None and y_mm is not None else None
            )
            hit = solver_hit and radius is not None and radius <= detector_radius_mm
            instrument_time = float(mapping["instrument_time_us"])
            lineage_age = float(mapping["lineage_age_us"])
            particle_age = float(mapping["particle_age_us"])
            normalized.append({
                "upstream_case_id": case["case_id"],
                "upstream_solver": case["upstream_solver"],
                "downstream_solver": downstream_solver,
                "solver_row_index": row_index,
                "particle_id": particle_id,
                "clock_epoch_id": state["clock_epoch_id"],
                "handoff_instrument_time_us": instrument_time,
                "handoff_lineage_age_us": lineage_age,
                "handoff_particle_age_us": particle_age,
                "local_oatof_tof_us": local_tof,
                "detector_instrument_time_us": instrument_time + local_tof if local_tof is not None else None,
                "detector_lineage_age_us": lineage_age + local_tof if local_tof is not None else None,
                "detector_particle_age_us": particle_age + local_tof if local_tof is not None else None,
                "hit": hit,
                "detector_x_mm": x_mm,
                "detector_y_mm": y_mm,
                "detector_radius_mm": radius,
            })
    return normalized


def _metrics(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    hits = [row for row in rows if row["hit"]]
    if not hits:
        return {
            "emitted": len(rows), "hits": 0, "transmission": 0.0,
            "mean_local_tof_us": None, "rms_detector_radius_mm": None,
            "detector_r99_mm": None,
        }
    radii = sorted(row["detector_radius_mm"] for row in hits)
    r99_index = max(0, math.ceil(0.99 * len(radii)) - 1)
    return {
        "emitted": len(rows),
        "hits": len(hits),
        "transmission": len(hits) / len(rows),
        "mean_local_tof_us": fmean(row["local_oatof_tof_us"] for row in hits),
        "rms_detector_radius_mm": math.sqrt(fmean(row["detector_radius_mm"] ** 2 for row in hits)),
        "detector_r99_mm": radii[r99_index],
        "mean_detector_instrument_time_us": fmean(row["detector_instrument_time_us"] for row in hits),
    }


def analyze(input_manifest_path: Path, output_dir: Path, mode_path: Path = DEFAULT_MODE) -> dict[str, Any]:
    validated = validate_mode(mode_path)
    manifest = load_json(input_manifest_path)
    cases = manifest.get("cases", [])
    if len(cases) != 2:
        raise ValueError("functional projection analysis requires two upstream ensembles")
    resolved = load_json(Path(manifest["resolved_geometry"]))
    detector_x = float(resolved["coordinate_convention"]["detector_x"])
    detector_y = float(resolved["coordinate_convention"].get("detector_y", 0.0))
    detector_radius = float(resolved["geometry_mm"]["detector_radius"])
    rows = [
        row for case in cases
        for row in _normalize_case(case, detector_x, detector_y, detector_radius)
    ]
    downstream_solvers = sorted({row["downstream_solver"] for row in rows})
    if not downstream_solvers:
        raise ValueError("no downstream solver results were supplied")

    metrics: dict[str, dict[str, Any]] = {}
    for solver in downstream_solvers:
        metrics[solver] = {}
        for case in cases:
            selected = [
                row for row in rows
                if row["downstream_solver"] == solver and row["upstream_case_id"] == case["case_id"]
            ]
            if not selected:
                raise ValueError(f"missing {solver} results for {case['case_id']}")
            metrics[solver][case["case_id"]] = _metrics(selected)

    acceptance = validated["acceptance"]
    comparisons: dict[str, Any] = {}
    case_ids = [case["case_id"] for case in cases]
    for solver in downstream_solvers:
        left = metrics[solver][case_ids[0]]
        right = metrics[solver][case_ids[1]]
        tof_difference = symmetric_relative_difference(left["mean_local_tof_us"], right["mean_local_tof_us"])
        radius_difference = symmetric_relative_difference(
            left["rms_detector_radius_mm"], right["rms_detector_radius_mm"]
        )
        values = {
            "transmission_absolute_difference": abs(left["transmission"] - right["transmission"]),
            "mean_tof_symmetric_relative_difference": tof_difference,
            "rms_detector_radius_symmetric_relative_difference": radius_difference,
        }
        solver_rows = [row for row in rows if row["downstream_solver"] == solver]
        hits_by_case = {
            case_id: {row["particle_id"] for row in solver_rows if row["upstream_case_id"] == case_id and row["hit"]}
            for case_id in case_ids
        }
        changed_ids = sorted(hits_by_case[case_ids[0]] ^ hits_by_case[case_ids[1]])
        changed_hit_radii = [
            row["detector_radius_mm"] for row in solver_rows
            if row["particle_id"] in changed_ids and row["hit"] and row["detector_radius_mm"] is not None
        ]
        values.update({
            "detector_classification_change_count": len(changed_ids),
            "detector_classification_changed_particle_ids": changed_ids,
            "minimum_detected_radius_among_changed_particles_mm": min(changed_hit_radii) if changed_hit_radii else None,
            "minimum_detected_radius_fraction_of_active_radius_among_changed_particles": (
                min(changed_hit_radii) / detector_radius if changed_hit_radii else None
            ),
        })
        checks = {
            "minimum_particles": all(
                item["emitted"] >= int(acceptance["minimum_particles_for_transport_and_centroid"])
                for item in (left, right)
            ),
            "minimum_detector_transmission": all(
                item["transmission"] >= float(acceptance["minimum_detector_transmission"])
                for item in (left, right)
            ),
            "cross_ensemble_transmission": values["transmission_absolute_difference"]
            <= float(acceptance["maximum_cross_ensemble_transmission_absolute_difference"]),
            "cross_ensemble_mean_tof": tof_difference is not None and tof_difference
            <= float(acceptance["maximum_cross_ensemble_mean_tof_relative_difference"]),
            "cross_ensemble_rms_detector_radius": radius_difference is not None and radius_difference
            <= float(acceptance["maximum_cross_ensemble_rms_detector_radius_relative_difference"]),
        }
        comparisons[solver] = {**values, "checks": checks, "status": "PASS" if all(checks.values()) else "FAIL"}

    cross_solver_comparisons: dict[str, Any] = {}
    if set(downstream_solvers) == {"COMSOL", "SIMION"}:
        for case_id in case_ids:
            comsol = metrics["COMSOL"][case_id]
            simion = metrics["SIMION"][case_id]
            cross_solver_comparisons[case_id] = {
                "transmission_absolute_difference": abs(
                    comsol["transmission"] - simion["transmission"]
                ),
                "mean_tof_symmetric_relative_difference": symmetric_relative_difference(
                    comsol["mean_local_tof_us"], simion["mean_local_tof_us"]
                ),
                "rms_detector_radius_symmetric_relative_difference": symmetric_relative_difference(
                    comsol["rms_detector_radius_mm"], simion["rms_detector_radius_mm"]
                ),
            }

    comparisons_pass = all(comparison["status"] == "PASS" for comparison in comparisons.values())
    comparison_kind = validated["mode"].get("comparison_kind", "cross_solver_upstream")
    functional_status = (
        "PASS" if comparisons_pass and comparison_kind == "rf_mesh_pair"
        else "CONDITIONAL_PASS" if comparisons_pass
        else "FAIL"
    )
    mesh_decision = None
    if comparison_kind == "rf_mesh_pair":
        performance_path = Path(validated["mode"]["field_performance_contract"])
        if not performance_path.is_absolute():
            performance_path = Path(__file__).resolve().parents[3] / performance_path
        budgets = load_json(performance_path)["provisional_performance_budgets"]
        r99_limit = float(budgets["maximum_detector_r99_fraction_of_active_radius"]) * detector_radius
        loss_budget = float(budgets["maximum_additional_field_induced_loss_fraction_after_geometric_cut"])
        per_solver = {}
        retain = True
        for solver in downstream_solvers:
            r99_pass = {
                case_id: metrics[solver][case_id]["detector_r99_mm"] is not None
                and metrics[solver][case_id]["detector_r99_mm"] <= r99_limit
                for case_id in case_ids
            }
            same_r99_classification = len(set(r99_pass.values())) == 1
            loss_within_budget = comparisons[solver]["transmission_absolute_difference"] <= loss_budget + 1e-12
            solver_retain = comparisons[solver]["status"] == "PASS" and loss_within_budget and same_r99_classification
            retain = retain and solver_retain
            per_solver[solver] = {
                "detector_r99_limit_mm": r99_limit,
                "detector_r99_pass_by_case": r99_pass,
                "same_detector_r99_classification": same_r99_classification,
                "transmission_difference_within_one_percentage_point_budget": loss_within_budget,
                "retain_low_cost_mesh_for_next_stage": solver_retain,
            }
        mesh_decision = {
            "status": "RETAIN_LOW_COST_FOR_NEXT_STAGE" if retain else "MESH_DECISION_UNRESOLVED",
            "low_cost_case_id": next(case["case_id"] for case in cases if case.get("mesh_role") == "low_cost_candidate"),
            "reference_case_id": next(case["case_id"] for case in cases if case.get("mesh_role") == "reference"),
            "per_solver": per_solver,
            "claim_limit": "Qualifies the selected projected RF-COMSOL to oaTOF-SIMION functional chain and its low-cost RF mesh. Physical connector transport, pulse capture and formal resolution remain deferred.",
        }
    output_dir.mkdir(parents=True, exist_ok=True)
    detector_csv = output_dir / "detector_particles.csv"
    with detector_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DETECTOR_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: (
            row["downstream_solver"], row["upstream_case_id"], row["solver_row_index"]
        )))
    result = {
        "schema_version": 1,
        "role": "oa_tof_rf_handoff_functional_projection",
        "status": functional_status,
        "downstream_solver_coverage": downstream_solvers,
        "metrics": metrics,
        "cross_ensemble_comparisons": comparisons,
        "cross_downstream_solver_comparisons": cross_solver_comparisons,
        "rf_mesh_decision": mesh_decision,
        "clock_reconstruction": "PASS",
        "functional_link_status": "PASS" if functional_status == "PASS" else functional_status,
        "strict_rf_interface_status": "FAIL",
        "physical_link_status": "BLOCKED",
        "resolution_validation_status": "DEFERRED_TO_N1000_REGRESSION",
        "resolution_claim_allowed": False,
        "formal_assets_modified": False,
        "promotion_authorized": False,
        "open_blockers": validated["mode"]["open_blockers"],
        "detector_particles": str(detector_csv.resolve()),
    }
    metrics_path = output_dir / "rf_handoff_projection_metrics.json"
    metrics_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", type=Path, default=DEFAULT_MODE)
    args = parser.parse_args()
    result = analyze(args.input_manifest, args.output_dir, args.mode)
    print(f"RF_HANDOFF_FUNCTIONAL_PROJECTION={result['status']}")
    if result["status"] == "FAIL":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
