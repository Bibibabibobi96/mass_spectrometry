"""Rebuild the S1 canonical handoff on the physical oa-TOF entry surface."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import build_oatof_handoff as handoff


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _compare_legacy_rows(legacy: list[dict[str, str]], rows: list[dict[str, str]]) -> dict[str, object]:
    if len(legacy) != len(rows):
        raise ValueError("legacy and rebuilt S1 entry tables have different row counts")
    invariant_columns = [name for name in rows[0] if name != "position_x_mm"]
    invariant_mismatches = 0
    x_shifts: list[float] = []
    for old, new in zip(legacy, rows, strict=True):
        if any(old[name] != new[name] for name in invariant_columns):
            invariant_mismatches += 1
        x_shifts.append(float(new["position_x_mm"]) - float(old["position_x_mm"]))
    if invariant_mismatches:
        raise ValueError("entry repair changed fields other than position_x_mm")
    if not all(math.isclose(value, x_shifts[0], rel_tol=0, abs_tol=1e-12) for value in x_shifts):
        raise ValueError("entry repair did not apply one rigid x-coordinate correction")
    return {
        "rows": len(rows),
        "only_position_x_changed": True,
        "rigid_position_x_shift_mm": x_shifts[0],
        "invariant_column_mismatches": 0,
    }


def rebuild(
    source_csv: Path,
    source_manifest: Path,
    project_root: Path,
    handoff_contract: Path,
    joint_contract: Path,
    canonical_output: Path,
    ion_output: Path,
    row_map_output: Path,
    metadata_output: Path,
    summary_output: Path,
    legacy_canonical: Path | None = None,
) -> dict[str, object]:
    handoff.PROJECT_ROOT = project_root.resolve()
    joint = json.loads(joint_contract.read_text(encoding="utf-8"))
    registration = joint["nominal_registration"]
    target_origin = [float(value) for value in registration["target_entry_center_instrument_mm"]]
    expected_frame = registration["instrument_frame"]
    metadata = handoff.build_handoff(
        source_csv, source_manifest, handoff_contract, canonical_output, ion_output,
        row_map_output, metadata_output, solver_clock="instrument_time",
        target_origin_override_mm=target_origin,
    )
    rows = _read_rows(canonical_output)
    if not rows:
        raise ValueError("rebuilt S1 entry table is empty")
    if any(row["frame_id"] != expected_frame for row in rows):
        raise ValueError("rebuilt S1 entry table does not use the joint-contract frame")
    maximum_entry_surface_residual = max(
        abs(float(row["position_x_mm"]) - target_origin[0]) for row in rows
    )
    if maximum_entry_surface_residual > 1e-12:
        raise ValueError("rebuilt S1 entries are not on the physical entry surface")

    comparison: dict[str, object] | None = None
    if legacy_canonical is not None:
        legacy = _read_rows(legacy_canonical)
        comparison = {
            "legacy_table": str(legacy_canonical.resolve()),
            **_compare_legacy_rows(legacy, rows),
        }

    summary = {
        "schema_version": 1,
        "role": "rf_to_oatof_s1_physical_entry_boundary_repair",
        "status": "PASS",
        "particles": len(rows),
        "frame_id": expected_frame,
        "physical_entry_surface_x_mm": target_origin[0],
        "maximum_entry_surface_residual_mm": maximum_entry_surface_residual,
        "numerical_release_offset_inside_surface_mm": float(
            joint["port_sweep"]["particle_release_offset_inside_outer_face_mm"]
        ),
        "solver_rerun": False,
        "comparison_to_legacy_projection": comparison,
        "handoff_metadata_status": metadata["status"],
        "claim": (
            "The canonical state is now recorded on the physical entry surface. "
            "The numerical inward release offset remains a separate solver setting."
        ),
    }
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-csv", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--handoff-contract", type=Path, required=True)
    parser.add_argument("--joint-contract", type=Path, required=True)
    parser.add_argument("--canonical-output", type=Path, required=True)
    parser.add_argument("--ion-output", type=Path, required=True)
    parser.add_argument("--row-map-output", type=Path, required=True)
    parser.add_argument("--metadata-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    parser.add_argument("--legacy-canonical", type=Path)
    args = parser.parse_args()
    result = rebuild(**vars(args))
    print(
        f"S1_ENTRY_BOUNDARY_REPAIR=PASS PARTICLES={result['particles']} "
        f"ENTRY_X_MM={result['physical_entry_surface_x_mm']:.12g}"
    )


if __name__ == "__main__":
    main()
