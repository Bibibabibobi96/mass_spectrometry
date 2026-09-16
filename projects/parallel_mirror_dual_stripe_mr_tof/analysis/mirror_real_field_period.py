"""Prepare and reduce a bare-mirror SIMION period comparison.

The comparison keeps the manufactured three-dimensional electrodes and the
accepted mirror voltages, but grounds both Stripe sets and both prisms.  It is
therefore a finite-geometry mirror diagnostic, not a complete-analyser result.
"""
from __future__ import annotations

import json
import math
import re
import argparse
from pathlib import Path
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import (
    MirrorL0Design,
    normalized_period_slope_per_v,
    reduced_period,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


PERIOD_EVENT = re.compile(
    r"MRTOF_MIRROR_PERIOD ion=(?P<ion>\d+) target_energy_ev=(?P<energy>[-+0-9.eE]+) "
    r"period_us=(?P<period>[-+0-9.eE]+) turns=(?P<turns>\d+) "
    r"x_mm=(?P<x>[-+0-9.eE]+) y_mm=(?P<y>[-+0-9.eE]+) z_mm=(?P<z>[-+0-9.eE]+) "
    r"vx_mm_us=(?P<vx>[-+0-9.eE]+) vy_mm_us=(?P<vy>[-+0-9.eE]+) "
    r"vz_mm_us=(?P<vz>[-+0-9.eE]+)"
)
FLY_COMPLETED = re.compile(
    r"(?:^|,)(?:Fly'm complete\. Splats:|Fly completed\.)\s*(?P<splats>\d+)(?:\s+splats)?",
    re.MULTILINE,
)


def _object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateContractError(f"{label} is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise CandidateContractError(f"{label} must be an object")
    return value


def load_exact_k_point(run_dir: Path) -> dict[str, Any]:
    """Load the manifest-bound exact-K summary used by the active field."""
    root = run_dir.resolve()
    manifest = _object(root / "run_manifest.json", "exact-K run manifest")
    if (
        manifest.get("project") != "parallel_mirror_dual_stripe_mr_tof"
        or manifest.get("status") != "success"
    ):
        raise CandidateContractError("exact-K run is not a successful MR-TOF run")
    summary_path = root / "summary.json"
    matches = [
        item for item in manifest.get("outputs", [])
        if isinstance(item, dict)
        and Path(str(item.get("path", ""))).resolve() == summary_path
    ]
    if len(matches) != 1:
        raise CandidateContractError("exact-K summary is not a unique manifest output")
    summary = _object(summary_path, "exact-K summary")
    point = summary.get("selected_operating_point")
    roots = summary.get("roots")
    if not isinstance(point, dict) or not isinstance(roots, list) or len(roots) != 1:
        raise CandidateContractError("exact-K summary lacks one selected mirror root")
    receipt = roots[0].get("refined_mirror_receipt")
    l0 = receipt.get("l0_receipt") if isinstance(receipt, dict) else None
    if not isinstance(l0, dict):
        raise CandidateContractError("exact-K summary lacks its L0 mirror receipt")
    if point.get("mirror_voltages_v") != l0.get("electrode_voltages_v"):
        raise CandidateContractError("selected mirror voltages differ from the L0 receipt")
    return {"root": root, "manifest": manifest, "summary": summary, "point": point, "l0": l0}


def build_probe_contract(run_dir: Path, *, y_mm: float = 280.0) -> dict[str, Any]:
    loaded = load_exact_k_point(run_dir)
    point, l0 = loaded["point"], loaded["l0"]
    three = l0.get("three_point")
    if not isinstance(three, dict):
        raise CandidateContractError("L0 receipt lacks three-point energies")
    centers = [float(value) for value in three.get("energies_v", [])]
    step = float(l0.get("period_slope_derivative_step_v"))
    if len(centers) != 3 or centers != sorted(centers) or step <= 0.0:
        raise CandidateContractError("L0 energy nodes or derivative step are invalid")
    energies = sorted({center + offset * step for center in centers for offset in (-1, 0, 1)})
    nominal = float(point["energy_per_charge_v"])
    nominal_period = float(point["mirror_full_two_mirror_period_T0_us_for_declared_mass"])
    design = MirrorL0Design(
        transverse_half_gap_mm=float(l0["transverse_half_gap_mm"]),
        transition_z_mm=tuple(float(value) for value in l0["transition_z_mm"]),
        electrode_voltages_v=tuple(float(value) for value in l0["electrode_voltages_v"]),
        terminal_electrode_plane_z_mm=float(l0["terminal_electrode_plane_z_mm"]),
        terminal_electrode_voltage_v=float(l0["electrode_voltages_v"][-1]),
    )
    scale = nominal_period / reduced_period(nominal, design)
    records = []
    for index, energy in enumerate(energies, start=1):
        records.append({
            "particle_id": index,
            "target_energy_ev": energy,
            "theory_period_us": scale * reduced_period(energy, design),
            "position_project_mm": [0.0, float(y_mm), 0.0],
            "direction_project": [0.0, 0.0, 1.0],
        })
    return {
        "schema_version": 1,
        "role": "mrtof_bare_mirror_real_field_period_probe",
        "status": "prepared",
        "qualification": "finite_3d_candidate_diagnostic__not_complete_analyser",
        "source_exact_k_run_id": loaded["manifest"]["run_id"],
        "mirror_voltages_v": list(design.electrode_voltages_v),
        "stripe_biases_v": [0.0, 0.0],
        "prism_voltages_v": [0.0, 0.0],
        "energy_centers_ev": centers,
        "derivative_step_ev": step,
        "nominal_energy_ev": nominal,
        "nominal_theory_period_us": nominal_period,
        "particle_mass_th": 524.0,
        "particle_charge_e": 1.0,
        "probe_y_mm": float(y_mm),
        "particles": records,
        "theory_normalized_period_slopes_per_v": [
            normalized_period_slope_per_v(design, center, step) for center in centers
        ],
    }


def write_fly2(contract: dict[str, Any], path: Path) -> None:
    beams = []
    for record in contract["particles"]:
        x, y, z = record["position_project_mm"]
        dx, dy, dz = record["direction_project"]
        beams.append(
            "  standard_beam {\n"
            "    n = 1, tob = 0, mass = 524, charge = 1,\n"
            f"    ke = {record['target_energy_ev']:.17g}, cwf = 1, color = 0,\n"
            f"    direction = vector({dx:.17g}, {dy:.17g}, {dz:.17g}),\n"
            "    position = circle_distribution {\n"
            f"      center = vector({x:.17g}, {y:.17g}, {z:.17g}),\n"
            f"      normal = vector({dx:.17g}, {dy:.17g}, {dz:.17g}), radius = 0, fill = true\n"
            "    }\n"
            "  }"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("particles {\n  coordinates = 0,\n" + ",\n".join(beams) + "\n}\n", encoding="utf-8")


def analyze_log(contract: dict[str, Any], log_path: Path) -> dict[str, Any]:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    completion = list(FLY_COMPLETED.finditer(text))
    if len(completion) != 1 or int(completion[0].group("splats")) != len(contract["particles"]):
        raise CandidateContractError("mirror period flight did not terminate the complete probe cohort")
    events: dict[int, dict[str, float | int]] = {}
    for match in PERIOD_EVENT.finditer(text):
        ion = int(match.group("ion"))
        if ion in events:
            raise CandidateContractError(f"duplicate mirror period event for ion {ion}")
        events[ion] = {
            "particle_id": ion,
            "target_energy_ev": float(match.group("energy")),
            "period_us": float(match.group("period")),
            "turns": int(match.group("turns")),
            "return_x_mm": float(match.group("x")),
            "return_y_mm": float(match.group("y")),
            "return_z_mm": float(match.group("z")),
            "return_vx_mm_us": float(match.group("vx")),
            "return_vy_mm_us": float(match.group("vy")),
            "return_vz_mm_us": float(match.group("vz")),
        }
    expected = {int(item["particle_id"]): item for item in contract["particles"]}
    if set(events) != set(expected):
        raise CandidateContractError("mirror period events do not cover the frozen probe cohort")
    by_energy: dict[float, dict[str, Any]] = {}
    for ion, event in events.items():
        source = expected[ion]
        if not math.isclose(float(event["target_energy_ev"]), float(source["target_energy_ev"]), rel_tol=0, abs_tol=1e-9):
            raise CandidateContractError(f"ion {ion} energy label differs from its source")
        if event["turns"] != 2 or float(event["return_vz_mm_us"]) <= 0.0:
            raise CandidateContractError(f"ion {ion} did not complete one two-mirror period")
        theory = float(source["theory_period_us"])
        event["theory_period_us"] = theory
        event["period_residual_us"] = float(event["period_us"]) - theory
        event["period_residual_ppm"] = 1e6 * (float(event["period_us"]) - theory) / theory
        by_energy[float(source["target_energy_ev"])] = event
    step = float(contract["derivative_step_ev"])
    real_slopes = []
    center_records = []
    for center in contract["energy_centers_ev"]:
        center = float(center)
        low, mid, high = by_energy[center - step], by_energy[center], by_energy[center + step]
        slope = (float(high["period_us"]) - float(low["period_us"])) / (2.0 * step * float(mid["period_us"]))
        real_slopes.append(slope)
        center_records.append(mid)
    theory_slopes = [float(value) for value in contract["theory_normalized_period_slopes_per_v"]]
    return {
        "schema_version": 1,
        "role": "mrtof_bare_mirror_real_field_period_comparison",
        "status": "candidate_diagnostic",
        "qualification": "one_y_slice_finite_3d_period_test__not_grid_converged",
        "probe_y_mm": contract["probe_y_mm"],
        "energy_centers_ev": contract["energy_centers_ev"],
        "derivative_step_ev": step,
        "theory_normalized_period_slopes_per_v": theory_slopes,
        "simion_normalized_period_slopes_per_v": real_slopes,
        "slope_difference_per_v": [real - theory for real, theory in zip(real_slopes, theory_slopes, strict=True)],
        "center_period_residual_ppm": [float(item["period_residual_ppm"]) for item in center_records],
        "particles": [by_energy[energy] for energy in sorted(by_energy)],
        "interpretation": {
            "stripes_and_prisms_grounded": True,
            "manufactured_slots_covers_and_finite_y_geometry_retained": True,
            "absolute_energy_axis_central_potential_correction_applied": False,
            "acceptance_threshold_assigned": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--exact-k-run", required=True, type=Path)
    prepare.add_argument("--probe-y-mm", type=float, default=280.0)
    prepare.add_argument("--contract-output", required=True, type=Path)
    prepare.add_argument("--fly2-output", required=True, type=Path)
    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--contract", required=True, type=Path)
    analyze.add_argument("--log", required=True, type=Path)
    analyze.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        contract = build_probe_contract(args.exact_k_run, y_mm=args.probe_y_mm)
        args.contract_output.parent.mkdir(parents=True, exist_ok=True)
        args.contract_output.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
        write_fly2(contract, args.fly2_output)
        print(f"MRTOF_MIRROR_PERIOD_PREPARE=PASS PARTICLES={len(contract['particles'])}")
    else:
        contract = _object(args.contract, "mirror period probe contract")
        result = analyze_log(contract, args.log)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print("MRTOF_MIRROR_PERIOD_ANALYZE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
