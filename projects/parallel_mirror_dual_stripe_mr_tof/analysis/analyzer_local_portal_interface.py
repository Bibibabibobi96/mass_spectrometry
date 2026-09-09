"""Prepare trajectory portals and aggregate local-to-local PA seam metrics."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import (
    parse_events,
)


SEAMS = {
    "negative_central_to_bridge": {
        "event_name": "handoff_negative_central_to_bridge__z_plane",
        "coordinate_mm": -72.0,
        "region_a": "central_transport",
        "region_b": "stripe_mirror_bridge_negative",
        "transform_a": "identity",
        "transform_b": "identity",
    },
    "positive_central_to_bridge": {
        "event_name": "handoff_positive_central_to_bridge__z_plane",
        "coordinate_mm": 72.0,
        "region_a": "central_transport",
        "region_b": "stripe_mirror_bridge_positive",
        "transform_a": "identity",
        "transform_b": "identity",
    },
    "negative_bridge_to_mirror": {
        "event_name": "handoff_negative_bridge_to_mirror__z_plane",
        "coordinate_mm": -131.0,
        "region_a": "stripe_mirror_bridge_negative",
        "region_b": "mirror_turn_negative",
        "transform_a": "identity",
        "transform_b": "identity",
    },
    "positive_bridge_to_mirror": {
        "event_name": "handoff_positive_bridge_to_mirror__z_plane",
        "coordinate_mm": 131.0,
        "region_a": "stripe_mirror_bridge_positive",
        "region_b": "mirror_turn_positive",
        "transform_a": "identity",
        "transform_b": "identity",
    },
}
DELTA_FIELDS = (
    "delta_potential_V",
    "delta_ex_V_per_mm",
    "delta_ey_V_per_mm",
    "delta_ez_V_per_mm",
)


def prepare_portal_samples(log_path: Path, output_directory: Path) -> dict[str, Any]:
    """Freeze exact centre-trajectory samples on the two effective PA seams."""
    events = parse_events(log_path.read_text(encoding="utf-8-sig", errors="replace"))
    output_directory.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for seam, specification in SEAMS.items():
        rows = [
            event for event in events
            if event["kind"] == "patch_interface"
            and event["name"] == specification["event_name"]
        ]
        if not rows:
            raise CandidateContractError(f"centre trace has no samples for seam {seam}")
        coordinate = float(specification["coordinate_mm"])
        if any(abs(float(row["z_mm"]) - coordinate) > 1e-9 for row in rows):
            raise CandidateContractError(f"centre trace coordinate differs for seam {seam}")
        csv_path = output_directory / f"samples__{seam}.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(("name", "x_mm", "y_mm", "z_mm"))
            for index, row in enumerate(rows, 1):
                writer.writerow((
                    f"{seam}__{index}",
                    format(float(row["x_mm"]), ".17g"),
                    format(float(row["y_mm"]), ".17g"),
                    format(float(row["z_mm"]), ".17g"),
                ))
        records.append({
            "seam": seam,
            "event_name": specification["event_name"],
            "coordinate_mm": coordinate,
            "region_a": specification["region_a"],
            "region_b": specification["region_b"],
            "transform_a": specification["transform_a"],
            "transform_b": specification["transform_b"],
            "sample_count": len(rows),
            "sample_csv": str(csv_path.resolve()),
            "x_envelope_mm": [
                min(float(row["x_mm"]) for row in rows),
                max(float(row["x_mm"]) for row in rows),
            ],
            "y_envelope_mm": [
                min(float(row["y_mm"]) for row in rows),
                max(float(row["y_mm"]) for row in rows),
            ],
        })
    return {
        "schema_version": 1,
        "role": "mrtof_analyzer_local_portal_samples",
        "status": "success",
        "qualification": "single_center_portal_seed_only",
        "source_log": str(log_path.resolve()),
        "seams": records,
    }


def _comparison_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise CandidateContractError(f"portal comparison CSV is missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or any(field not in rows[0] for field in DELTA_FIELDS):
        raise CandidateContractError(f"portal comparison CSV schema differs: {path}")
    return rows


def _metrics_from_rows(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    result: dict[str, Any] = {"sample_count": len(rows)}
    for field in DELTA_FIELDS:
        values: list[float] = []
        for row in rows:
            try:
                value = float(row[field])
            except (TypeError, ValueError) as exc:
                raise CandidateContractError(f"non-numeric portal metric {field}: {label}") from exc
            if not math.isfinite(value):
                raise CandidateContractError(f"non-finite portal metric {field}: {label}")
            values.append(value)
        stem = field.removeprefix("delta_")
        result[f"max_abs_{stem}"] = max(abs(value) for value in values)
        result[f"rms_{stem}"] = math.sqrt(sum(value * value for value in values) / len(values))
    return result


def analyze_portal_comparisons(input_path: Path) -> dict[str, Any]:
    """Validate a complete two-scale, four-seam, eight-basis comparison matrix."""
    document = json.loads(input_path.read_text(encoding="utf-8-sig"))
    if document.get("role") != "mrtof_analyzer_local_portal_comparison_input":
        raise CandidateContractError("portal comparison input role differs")
    scales = tuple(float(value) for value in document.get("scale_factors", ()))
    seams = tuple(str(value) for value in document.get("seams", ()))
    groups = tuple(str(value) for value in document.get("response_groups", ()))
    if len(scales) != 2 or not scales[0] > scales[1] > 0:
        raise CandidateContractError("portal comparison requires ordered coarse/fine scales")
    if set(seams) != set(SEAMS) or len(groups) != 8 or len(set(groups)) != 8:
        raise CandidateContractError("portal comparison matrix axes differ")
    expected = {(scale, seam, group) for scale in scales for seam in seams for group in groups}
    records = document.get("comparisons")
    if not isinstance(records, list):
        raise CandidateContractError("portal comparisons must be a list")
    observed: dict[tuple[float, str, str], dict[str, Any]] = {}
    observed_rows: dict[tuple[float, str, str], list[dict[str, str]]] = {}
    comparisons: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            raise CandidateContractError("portal comparison record must be an object")
        key = (float(record.get("scale_factor")), str(record.get("seam")), str(record.get("group")))
        if key not in expected or key in observed:
            raise CandidateContractError("portal comparison matrix has unknown or duplicate cells")
        csv_path = Path(str(record.get("csv_path")))
        rows = _comparison_rows(csv_path)
        measured = _metrics_from_rows(rows, str(csv_path))
        observed[key] = measured
        observed_rows[key] = rows
        comparisons.append({"scale_factor": key[0], "seam": key[1], "group": key[2], **measured})
    if set(observed) != expected:
        raise CandidateContractError("portal comparison matrix is incomplete")
    convergence: list[dict[str, Any]] = []
    for seam in seams:
        for group in groups:
            coarse = observed[(scales[0], seam, group)]
            fine = observed[(scales[1], seam, group)]
            if coarse["sample_count"] != fine["sample_count"]:
                raise CandidateContractError(f"portal sample counts differ for {seam}/{group}")
            convergence.append({
                "seam": seam,
                "group": group,
                "sample_count": coarse["sample_count"],
                "coarse": coarse,
                "fine": fine,
                "fine_over_coarse_max_abs_delta_ez": (
                    fine["max_abs_ez_V_per_mm"] / coarse["max_abs_ez_V_per_mm"]
                    if coarse["max_abs_ez_V_per_mm"] else None
                ),
            })
    group_voltages = document.get("operating_group_voltages_V")
    basis_by_scale = document.get("basis_voltage_V_by_scale")
    if (not isinstance(group_voltages, list) or len(group_voltages) != len(groups)
            or not isinstance(basis_by_scale, dict)):
        raise CandidateContractError("operating voltages or basis normalization differ")
    voltages = [float(value) for value in group_voltages]
    try:
        parsed_basis = {float(key): float(value) for key, value in basis_by_scale.items()}
    except (TypeError, ValueError) as exc:
        raise CandidateContractError("basis normalization keys or values are invalid") from exc
    if set(parsed_basis) != set(scales):
        raise CandidateContractError("basis normalization scales differ")
    basis = {scale: parsed_basis[scale] for scale in scales}
    if any(not math.isfinite(value) for value in voltages) or any(
        not math.isfinite(value) or value == 0 for value in basis.values()
    ):
        raise CandidateContractError("operating voltages or basis normalization are invalid")
    operating: dict[tuple[float, str], dict[str, Any]] = {}
    for scale in scales:
        for seam in seams:
            rows_by_group = [observed_rows[(scale, seam, group)] for group in groups]
            names = [tuple(row["name"] for row in rows) for rows in rows_by_group]
            if any(item != names[0] for item in names[1:]):
                raise CandidateContractError(f"portal sample order differs for {scale}/{seam}")
            combined: list[dict[str, Any]] = []
            for index, name in enumerate(names[0]):
                row: dict[str, Any] = {"name": name}
                for field in DELTA_FIELDS:
                    row[field] = sum(
                        float(rows_by_group[group_index][index][field])
                        * voltages[group_index] / basis[scale]
                        for group_index in range(len(groups))
                    )
                combined.append(row)
            operating[(scale, seam)] = _metrics_from_rows(
                combined, f"{scale}/{seam}/operating"
            )
    return {
        "schema_version": 1,
        "role": "mrtof_analyzer_local_portal_interface_convergence",
        "status": "success",
        "qualification": "single_center_portal_measured__acceptance_threshold_not_defined",
        "scale_factors": list(scales),
        "seams": list(seams),
        "response_groups": list(groups),
        "comparison_count": len(comparisons),
        "maximum_abs_delta_potential_V": {
            str(scale): max(
                observed[(scale, seam, group)]["max_abs_potential_V"]
                for seam in seams for group in groups
            ) for scale in scales
        },
        "maximum_abs_delta_ez_V_per_mm": {
            str(scale): max(
                observed[(scale, seam, group)]["max_abs_ez_V_per_mm"]
                for seam in seams for group in groups
            ) for scale in scales
        },
        "operating_point": {
            "group_voltages_V": voltages,
            "basis_voltage_V_by_scale": {str(scale): basis[scale] for scale in scales},
            "maximum_abs_delta_potential_V": {
                str(scale): max(
                    operating[(scale, seam)]["max_abs_potential_V"] for seam in seams
                ) for scale in scales
            },
            "maximum_abs_delta_ez_V_per_mm": {
                str(scale): max(
                    operating[(scale, seam)]["max_abs_ez_V_per_mm"] for seam in seams
                ) for scale in scales
            },
            "comparisons": [
                {"scale_factor": scale, "seam": seam, **operating[(scale, seam)]}
                for scale in scales for seam in seams
            ],
        },
        "convergence": convergence,
        "comparisons": comparisons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare-samples")
    prepare.add_argument("--log", required=True, type=Path)
    prepare.add_argument("--output-directory", required=True, type=Path)
    prepare.add_argument("--receipt", required=True, type=Path)
    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--input", required=True, type=Path)
    analyze.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.command == "prepare-samples":
        result = prepare_portal_samples(arguments.log, arguments.output_directory)
        output = arguments.receipt
    else:
        result = analyze_portal_comparisons(arguments.input)
        output = arguments.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
