"""Write a hash-bound manifest for analyser, accelerator, and detector PAs."""
from __future__ import annotations

import argparse
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import geometry_receipt
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import load_contract
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_candidate_geometry import (
    ACCELERATOR_LOCAL_ELECTRODE_IDS,
    resolve_split_iob_origins,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_manifest_common import (
    record_artifact,
    record_pa_family,
    validate_no_flight_structure_report,
    write_manifest,
)


def build_manifest(contract_path: Path, run_directory: Path, iob_path: Path,
                   structure_report_path: Path) -> dict[str, object]:
    """Build the active three-component no-flight geometry-review receipt."""
    origins = resolve_split_iob_origins(contract_path)
    geometry = geometry_receipt(load_contract(contract_path))
    analyzer_ids = sorted({
        electrode_id for role, values in geometry["electrode_ids"].items()
        if role not in {"accelerator", "detector"} for electrode_id in values
    })
    validate_no_flight_structure_report(structure_report_path)
    analyzer = record_pa_family(run_directory, "mrtof_analyzer", range(1, max(analyzer_ids) + 1))
    accelerator = record_pa_family(
        run_directory, "mrtof_accelerator", sorted(ACCELERATOR_LOCAL_ELECTRODE_IDS.values()),
    )
    return {
        "schema_version": 1,
        "project_id": "parallel_mirror_dual_stripe_mr_tof",
        "status": "prototype_geometry_review_only",
        "geometry": geometry,
        "workbench": {
            "instance_count": 3,
            "iob": record_artifact(iob_path),
            "program": record_artifact(iob_path.with_suffix(".lua")),
            "operating_point": record_artifact(iob_path.with_suffix(".operating_point.lua")),
            "voltage_map": record_artifact(iob_path.with_suffix(".voltage_map.lua")),
            "structure_report": record_artifact(structure_report_path),
        },
        "instances": [
            {
                "role": "analyzer",
                "origin_mm": origins["analyzer"],
                "physical_electrode_ids": analyzer_ids,
                "basis_namespace": "dense_1_to_max_id_including_zero_response_unused_ids",
                **analyzer,
            },
            {
                "role": "shielded_two_zone_accelerator",
                "origin_mm": origins["accelerator"],
                "stable_project_to_local_electrode_id": ACCELERATOR_LOCAL_ELECTRODE_IDS,
                **accelerator,
            },
            {
                "role": "detector",
                "origin_mm": origins["detector"],
                "raw_pa": record_artifact(run_directory / "mrtof_detector.pa#"),
                "basis_arrays": [],
                "electrostatic_solution": "none__raw_zero_voltage_geometry_only_terminal_plane",
            },
        ],
        "limitations": [
            "Detector is a separate zero-voltage, unrefined geometry-only PA, not an analyser-PA marker.",
            "No trajectory, timing, transmission, or resolution claim follows from this IOB.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--iob", type=Path, required=True)
    parser.add_argument("--structure-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_manifest(args.contract, args.run, args.iob, args.structure_report)
    write_manifest(args.output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
