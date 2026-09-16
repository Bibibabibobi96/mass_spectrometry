"""Prepare and reduce grounded-auxiliary mirror-axis field profiles."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import (
    MirrorL0Design,
    axial_potential_gradient_v_per_mm,
    axial_potential_v,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_period import (
    load_exact_k_point,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)

REGIONS = (
    ("negative_mirror", "mirror_turn_negative", -319, -132),
    ("negative_bridge", "stripe_mirror_bridge_negative", -131, -73),
    ("central", "central_transport", -72, 71),
    ("positive_bridge", "stripe_mirror_bridge_positive", 72, 130),
    ("positive_mirror", "mirror_turn_positive", 131, 319),
)


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CandidateContractError(f"JSON object required: {path}")
    return value


def prepare(
    coarse_workbench: Path, fine_workbench: Path, output: Path, y_mm: float,
    *, fine_mirror_mesh_mm: float | None = None,
) -> dict[str, Any]:
    plans = []
    meshes = []
    for root in (coarse_workbench.resolve(), fine_workbench.resolve()):
        manifest = _object(root / "run_manifest.json")
        if manifest.get("status") != "success" or manifest.get("mode") != "analyzer_local_replacement_workbench":
            raise CandidateContractError("field profile requires successful local replacement workbenches")
        plan = _object(root / "results" / "current_analyzer_local_refinement_plan.json")
        config = _object(root / "run_config.json")
        plans.append(plan)
        meshes.append([float(v) for v in config["parameters"]["local_mesh_mm_per_gu"]])
    if plans[0]["handoff_planes_project_mm"] != plans[1]["handoff_planes_project_mm"]:
        raise CandidateContractError("coarse and fine workbenches use different handoff planes")
    output.mkdir(parents=True, exist_ok=True)
    regions = []
    for label, key, lower, upper in REGIONS:
        sample_path = output / f"samples_{label}.csv"
        with sample_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(("name", "x_mm", "y_mm", "z_mm"))
            for z_mm in range(lower, upper + 1):
                writer.writerow((f"z_{z_mm}", 0, f"{y_mm:.17g}", z_mm))
        regions.append({
            "label": label,
            "plan_key": key,
            "sample_csv": str(sample_path),
            "coarse_origin_mm": plans[0]["patches"][key][:3],
            "fine_origin_mm": plans[1]["patches"][key][:3],
        })
    contract = {
        "schema_version": 1,
        "role": "mrtof_grounded_auxiliary_mirror_axis_field_profile",
        "status": "prepared",
        "probe_x_mm": 0.0,
        "probe_y_mm": float(y_mm),
        "coarse_mesh_mm_per_gu": meshes[0],
        "fine_mesh_mm_per_gu": meshes[1],
        "stripes_and_prisms_grounded": True,
        "regions": regions,
    }
    contract["mesh_by_region_mm_per_gu"] = {
        "coarse": {label: meshes[0] for label, *_ in REGIONS},
        "fine": {
            label: ([fine_mirror_mesh_mm] * 3 if fine_mirror_mesh_mm is not None and "mirror" in label else meshes[1])
            for label, *_ in REGIONS
        },
    }
    (output / "profile_contract.json").write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
    return contract


def _rms(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values) / len(values))


def analyze(contract_path: Path, exact_k_run: Path, samples_directory: Path, output: Path) -> dict[str, Any]:
    contract = _object(contract_path)
    loaded = load_exact_k_point(exact_k_run)
    l0 = loaded["l0"]
    design = MirrorL0Design(
        transverse_half_gap_mm=float(l0["transverse_half_gap_mm"]),
        transition_z_mm=tuple(float(v) for v in l0["transition_z_mm"]),
        electrode_voltages_v=tuple(float(v) for v in l0["electrode_voltages_v"]),
        terminal_electrode_plane_z_mm=float(l0["terminal_electrode_plane_z_mm"]),
        terminal_electrode_voltage_v=float(l0["electrode_voltages_v"][-1]),
    )
    rows: list[dict[str, Any]] = []
    for region in contract["regions"]:
        path = samples_directory / f"comparison_{region['label']}.csv"
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                z_mm = float(row["z_mm"])
                if abs(z_mm) >= 320.0:
                    continue
                rows.append({
                    "region": region["label"], "z_mm": z_mm,
                    "coarse_potential_v": float(row["potential_a_V"]),
                    "fine_potential_v": float(row["potential_b_V"]),
                    "coarse_ex_v_per_mm": float(row["ex_a_V_per_mm"]),
                    "coarse_ey_v_per_mm": float(row["ey_a_V_per_mm"]),
                    "coarse_ez_v_per_mm": float(row["ez_a_V_per_mm"]),
                    "fine_ex_v_per_mm": float(row["ex_b_V_per_mm"]),
                    "fine_ey_v_per_mm": float(row["ey_b_V_per_mm"]),
                    "fine_ez_v_per_mm": float(row["ez_b_V_per_mm"]),
                })
    rows.sort(key=lambda row: row["z_mm"])
    zero = next((row for row in rows if row["z_mm"] == 0.0), None)
    if zero is None or len(rows) != 639:
        raise CandidateContractError("profile must contain exactly the vacuum axis z=-319..319 including z=0")
    theory_zero = axial_potential_v(0.0, design)
    for row in rows:
        z_mm = row["z_mm"]
        theory_potential = axial_potential_v(z_mm, design) - theory_zero
        theory_ez = -axial_potential_gradient_v_per_mm(z_mm, design)
        row["theory_potential_v"] = theory_potential
        row["theory_ez_v_per_mm"] = theory_ez
        for prefix in ("coarse", "fine"):
            row[f"{prefix}_potential_aligned_v"] = row[f"{prefix}_potential_v"] - zero[f"{prefix}_potential_v"]
            row[f"{prefix}_potential_residual_v"] = row[f"{prefix}_potential_aligned_v"] - theory_potential
            row[f"{prefix}_ez_residual_v_per_mm"] = row[f"{prefix}_ez_v_per_mm"] - theory_ez
        row["fine_minus_coarse_potential_v"] = row["fine_potential_aligned_v"] - row["coarse_potential_aligned_v"]
        row["fine_minus_coarse_ez_v_per_mm"] = row["fine_ez_v_per_mm"] - row["coarse_ez_v_per_mm"]

    def metrics(selected: list[dict[str, Any]]) -> dict[str, float]:
        result: dict[str, float] = {}
        for name in ("coarse_potential_residual_v", "fine_potential_residual_v",
                     "coarse_ez_residual_v_per_mm", "fine_ez_residual_v_per_mm",
                     "fine_minus_coarse_potential_v", "fine_minus_coarse_ez_v_per_mm"):
            values = [float(row[name]) for row in selected]
            result[f"{name}_rms"] = _rms(values)
            result[f"{name}_max_abs"] = max(abs(value) for value in values)
        for prefix in ("coarse", "fine"):
            transverse = [math.hypot(row[f"{prefix}_ex_v_per_mm"], row[f"{prefix}_ey_v_per_mm"]) for row in selected]
            result[f"{prefix}_transverse_field_max_v_per_mm"] = max(transverse)
            result[f"{prefix}_ex_max_abs_v_per_mm"] = max(abs(row[f"{prefix}_ex_v_per_mm"]) for row in selected)
            result[f"{prefix}_ey_max_abs_v_per_mm"] = max(abs(row[f"{prefix}_ey_v_per_mm"]) for row in selected)
        return result

    report = {
        "schema_version": 1,
        "role": "mrtof_grounded_auxiliary_mirror_axis_field_comparison",
        "status": "candidate_diagnostic",
        "qualification": "axis_profile_two_mesh_levels__not_spatially_or_grid_converged",
        "probe_y_mm": contract["probe_y_mm"],
        "coarse_mesh_mm_per_gu": contract["coarse_mesh_mm_per_gu"],
        "fine_mesh_mm_per_gu": contract["fine_mesh_mm_per_gu"],
        "mesh_by_region_mm_per_gu": contract.get("mesh_by_region_mm_per_gu"),
        "mirror_voltages_v": list(design.electrode_voltages_v),
        "global_metrics": metrics(rows),
        "region_metrics": {region: metrics([row for row in rows if row["region"] == region]) for region, *_ in REGIONS},
        "samples": rows,
        "interpretation": {
            "potential_offset_removed_at_z0": True,
            "theory_is_infinite_2d_berdnikov_axis_field": True,
            "real_field_retains_grounded_slots_covers_stripes_and_prism_shields": True,
            "two_mesh_levels_cannot_establish_asymptotic_convergence": True,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--coarse-workbench", type=Path, required=True)
    prepare_parser.add_argument("--fine-workbench", type=Path, required=True)
    prepare_parser.add_argument("--output-directory", type=Path, required=True)
    prepare_parser.add_argument("--probe-y-mm", type=float, default=280.0)
    prepare_parser.add_argument("--fine-mirror-mesh-mm", type=float)
    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument("--contract", type=Path, required=True)
    analyze_parser.add_argument("--exact-k-run", type=Path, required=True)
    analyze_parser.add_argument("--samples-directory", type=Path, required=True)
    analyze_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(
            args.coarse_workbench, args.fine_workbench, args.output_directory, args.probe_y_mm,
            fine_mirror_mesh_mm=args.fine_mirror_mesh_mm,
        )
        print("MRTOF_MIRROR_FIELD_PROFILE_PREPARE=PASS")
    else:
        analyze(args.contract, args.exact_k_run, args.samples_directory, args.output)
        print("MRTOF_MIRROR_FIELD_PROFILE_ANALYZE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
