"""Write a hash-bound manifest for the two-instance MR-TOF SIMION assembly."""
from __future__ import annotations

import argparse
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_candidate_geometry import resolve_split_iob_origins
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_manifest_common import (
    record_artifact,
    record_pa_family,
    validate_no_flight_structure_report,
    write_manifest,
)


def build_manifest(contract_path: Path, run_directory: Path, iob_path: Path,
                   structure_report_path: Path | None = None) -> dict[str, object]:
    """Build the historical two-instance geometry-review receipt unchanged."""
    origins = resolve_split_iob_origins(contract_path)
    if structure_report_path is not None:
        validate_no_flight_structure_report(structure_report_path)
    analyzer = record_pa_family(run_directory, "mrtof_analyzer", range(1, 21))
    accelerator = record_pa_family(run_directory, "mrtof_accelerator", (22, 23, 24, 26, 27, 28, 29, 30))
    result: dict[str, object] = {
        "schema_version": 1,
        "project_id": "parallel_mirror_dual_stripe_mr_tof",
        "status": "prototype_geometry_review_only",
        "workbench": {"instance_count": 2, "iob": record_artifact(iob_path)},
        "instances": [
            {"role": "analyzer", "origin_mm": origins["analyzer"], **analyzer},
            {"role": "shielded_two_zone_accelerator", "origin_mm": origins["accelerator"], **accelerator},
        ],
        "limitations": [
            "Analyzer PA is 2 x 2 x 2 mm/gu geometry-review mesh, not a convergence result.",
            "Accelerator PA is independently refined inside its grounded enclosure.",
            "No trajectory, timing, transmission, or resolution claim follows from this IOB.",
        ],
    }
    if structure_report_path is not None:
        result["workbench"]["structure_report"] = record_artifact(structure_report_path)  # type: ignore[index]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--iob", type=Path, required=True)
    parser.add_argument("--structure-report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_manifest(args.contract, args.run, args.iob, args.structure_report)
    write_manifest(args.output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
