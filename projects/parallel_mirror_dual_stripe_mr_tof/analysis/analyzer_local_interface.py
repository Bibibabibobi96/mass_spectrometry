"""Aggregate matched physical-lattice measurements at local PA interfaces."""
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


FACES = ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max")
METRICS = (
    "max_abs_potential_V",
    "rms_potential_V",
    "max_abs_normal_field_V_per_mm",
    "rms_normal_field_V_per_mm",
    "max_abs_reference_potential_V",
    "max_abs_reference_normal_field_V_per_mm",
)


def _positive_number(value: object, label: str, *, allow_zero: bool = True) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CandidateContractError(f"{label} must be numeric") from exc
    if not math.isfinite(number) or number < 0 or (not allow_zero and number == 0):
        raise CandidateContractError(f"{label} must be finite and nonnegative")
    return number


def _read_face_metrics(path: Path) -> dict[str, dict[str, float | int]]:
    if not path.is_file():
        raise CandidateContractError(f"interface CSV is missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if tuple(row.get("face") for row in rows) != FACES:
        raise CandidateContractError(f"interface CSV faces differ: {path}")
    result: dict[str, dict[str, float | int]] = {}
    for row in rows:
        face = str(row["face"])
        try:
            total_nodes = int(str(row["total_nodes"]))
            potential_samples = int(str(row["vacuum_potential_samples"]))
            field_samples = int(str(row["field_samples"]))
            physical_nodes = int(str(row["face_physical_nodes"]))
            near_physical_nodes = int(str(row["near_physical_vacuum_nodes"]))
        except (TypeError, ValueError) as exc:
            raise CandidateContractError(f"interface counts differ: {path}") from exc
        if (
            total_nodes <= 0
            or potential_samples + physical_nodes != total_nodes
            or field_samples <= 0
            or physical_nodes < 0
            or near_physical_nodes < 0
            or field_samples + near_physical_nodes != potential_samples
        ):
            raise CandidateContractError(f"interface counts differ: {path}")
        values: dict[str, float | int] = {
            "total_nodes": total_nodes,
            "potential_samples": potential_samples,
            "field_samples": field_samples,
            "face_physical_nodes": physical_nodes,
            "near_physical_vacuum_nodes": near_physical_nodes,
        }
        for metric in METRICS:
            values[metric] = _positive_number(row.get(metric), f"{path}:{face}:{metric}")
        result[face] = values
    return result


def analyze_interface_convergence(input_path: Path) -> dict[str, Any]:
    """Validate a complete coarse/fine matrix and report measured convergence."""
    document = json.loads(input_path.read_text(encoding="utf-8-sig"))
    if document.get("role") != "mrtof_analyzer_local_interface_measurement_input":
        raise CandidateContractError("interface measurement input role differs")
    scales = tuple(float(value) for value in document.get("scale_factors", ()))
    if len(scales) != 2 or not scales[0] > scales[1] > 0:
        raise CandidateContractError("interface comparison requires coarse and fine scales")
    regions = tuple(str(value) for value in document.get("regions", ()))
    groups = tuple(str(value) for value in document.get("response_groups", ()))
    if len(regions) != 2 or len(set(regions)) != 2 or len(groups) != 8 or len(set(groups)) != 8:
        raise CandidateContractError("interface comparison matrix dimensions differ")
    expected = {(scale, region, group) for scale in scales for region in regions for group in groups}
    observed: dict[tuple[float, str, str], dict[str, dict[str, float | int]]] = {}
    records = document.get("comparisons")
    if not isinstance(records, list):
        raise CandidateContractError("interface comparisons must be a list")
    for record in records:
        if not isinstance(record, dict):
            raise CandidateContractError("interface comparison record must be an object")
        key = (float(record.get("scale_factor")), str(record.get("region")), str(record.get("group")))
        if key not in expected or key in observed:
            raise CandidateContractError("interface comparison matrix has an unknown or duplicate cell")
        observed[key] = _read_face_metrics(Path(str(record.get("csv_path"))))
    if set(observed) != expected:
        raise CandidateContractError("interface comparison matrix is incomplete")

    native_records = document.get("native_face_scans")
    if not isinstance(native_records, list):
        raise CandidateContractError("native interface face scans must be a list")
    native: dict[tuple[float, str, str], dict[str, dict[str, float | int]]] = {}
    for record in native_records:
        if not isinstance(record, dict):
            raise CandidateContractError("native interface record must be an object")
        key = (float(record.get("scale_factor")), str(record.get("region")), str(record.get("group")))
        if key not in expected or key in native:
            raise CandidateContractError("native interface matrix has an unknown or duplicate cell")
        native[key] = _read_face_metrics(Path(str(record.get("csv_path"))))
    if set(native) != expected:
        raise CandidateContractError("native interface matrix is incomplete")

    comparisons: list[dict[str, Any]] = []
    all_potential: list[float] = []
    all_coarse_field: list[float] = []
    all_fine_field: list[float] = []
    for region in regions:
        for group in groups:
            for face in FACES:
                coarse = observed[(scales[0], region, group)][face]
                fine = observed[(scales[1], region, group)][face]
                if coarse["potential_samples"] != fine["potential_samples"]:
                    raise CandidateContractError(
                        f"physical sample lattice differs for {region}/{group}/{face}"
                    )
                coarse_field = float(coarse["max_abs_normal_field_V_per_mm"])
                fine_field = float(fine["max_abs_normal_field_V_per_mm"])
                coarse_rms = float(coarse["rms_normal_field_V_per_mm"])
                fine_rms = float(fine["rms_normal_field_V_per_mm"])
                all_potential.extend((float(coarse["max_abs_potential_V"]), float(fine["max_abs_potential_V"])))
                all_coarse_field.append(coarse_field)
                all_fine_field.append(fine_field)
                comparisons.append({
                    "region": region,
                    "group": group,
                    "face": face,
                    "samples": coarse["potential_samples"],
                    "coarse": coarse,
                    "fine": fine,
                    "fine_over_coarse_max_normal_field": (
                        fine_field / coarse_field if coarse_field else None
                    ),
                    "fine_over_coarse_rms_normal_field": (
                        fine_rms / coarse_rms if coarse_rms else None
                    ),
                })
    return {
        "schema_version": 1,
        "role": "mrtof_analyzer_local_interface_convergence",
        "status": "success",
        "qualification": "measured_interface_convergence__acceptance_threshold_not_defined",
        "scale_factors": list(scales),
        "physical_sample_spacing_mm": _positive_number(
            document.get("physical_sample_spacing_mm"),
            "physical sample spacing",
            allow_zero=False,
        ),
        "regions": list(regions),
        "response_groups": list(groups),
        "native_patch_face_nodes_evaluated": {
            str(scale): sum(
                int(native[(scale, region, group)][face]["potential_samples"])
                for region in regions for group in groups for face in FACES
            )
            for scale in scales
        },
        "comparison_count": len(comparisons),
        "maximum_abs_dirichlet_potential_mismatch_V": max(all_potential),
        "maximum_abs_normal_field_mismatch_V_per_mm": {
            "coarse": max(all_coarse_field),
            "fine": max(all_fine_field),
            "fine_over_coarse": max(all_fine_field) / max(all_coarse_field),
        },
        "comparisons": comparisons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    result = analyze_interface_convergence(arguments.input)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
