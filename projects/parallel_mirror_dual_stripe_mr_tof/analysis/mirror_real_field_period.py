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
from typing import Any, Mapping

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import (
    MirrorL0Design,
    normalized_period_slope_per_v,
    reduced_period,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_l1_screen import (
    SPEED_MM_US_PER_SQRT_EV_PER_TH,
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


def fixed_grid_point_qualification(selection: Mapping[str, Any]) -> str:
    """Preserve the point workflow's bounded qualification in downstream evidence."""

    qualification = str(selection.get("qualification", ""))
    if qualification not in {
        "diagnostic_secant_point_only__not_a_candidate_operating_point",
        "secant_model_proposal_fixed_grid_validation_only__not_accepted",
    }:
        raise CandidateContractError("fixed-grid voltage point qualification is unsupported")
    return qualification


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
    root_index = summary.get("selected_root_index")
    if (
        not isinstance(point, dict)
        or not isinstance(roots, list)
        or not roots
        or not isinstance(root_index, int)
        or isinstance(root_index, bool)
        or not 0 <= root_index < len(roots)
    ):
        raise CandidateContractError("exact-K summary lacks an explicit selected mirror root")
    selected_root = roots[root_index]
    root_point = selected_root.get("point") if isinstance(selected_root, dict) else None
    if (
        not isinstance(root_point, dict)
        or any(point.get(key) != value for key, value in root_point.items())
    ):
        raise CandidateContractError("exact-K selected root and operating point differ")
    receipt = selected_root.get("refined_mirror_receipt")
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


def build_real_field_probe_contract(
    refinement_run_dir: Path,
    axis_response_run_dir: Path,
    selection_receipt_path: Path,
    *,
    y_mm: float = 280.0,
) -> dict[str, Any]:
    """Build a bare-mirror probe from one selected real-field L1 root."""

    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_voltage_family import (
        load_axis_response_basis_csv,
        normalized_slopes,
        reduced_period_from_basis,
    )

    refinement_root = refinement_run_dir.resolve()
    refinement_manifest = _object(
        refinement_root / "run_manifest.json", "real-field L1 run manifest",
    )
    if (
        refinement_manifest.get("project") != "parallel_mirror_dual_stripe_mr_tof"
        or refinement_manifest.get("mode") != "real_3d_mirror_l1_continuous_refinement"
        or refinement_manifest.get("status") != "success"
    ):
        raise CandidateContractError("real-field L1 run identity is invalid")
    refinement_path = (
        refinement_root / "results" / "real_3d_mirror_l1_continuous_refinement.json"
    ).resolve()
    refinement_matches = [
        item for item in refinement_manifest.get("outputs", [])
        if isinstance(item, dict)
        and Path(str(item.get("path", ""))).resolve() == refinement_path
    ]
    if (
        len(refinement_matches) != 1
        or not refinement_path.is_file()
        or str(refinement_matches[0].get("sha256", "")).upper()
        != file_sha256(refinement_path)
    ):
        raise CandidateContractError("real-field L1 result is not uniquely manifest-bound")
    refinement = _object(refinement_path, "real-field L1 result")
    selection = _object(selection_receipt_path, "fixed-grid selection receipt")
    roots = refinement.get("roots")
    if not isinstance(roots, list):
        raise CandidateContractError("real-field L1 refinement lacks roots")
    selection_role = selection.get("role")
    if selection_role == "mrtof_real_3d_mirror_fixed_grid_validation_selection":
        if (
            selection.get("status") != "selected_for_fixed_0p25mm_native_validation"
            or selection.get("source_refinement_sha256") != file_sha256(refinement_path)
            or not isinstance(selection.get("selected_roots"), list)
            or len(selection["selected_roots"]) != 1
        ):
            raise CandidateContractError("fixed-grid selection does not identify one L1 root")
        selected = selection["selected_roots"][0]
        root_index = int(selected["root_index"])
        if (
            not 0 <= root_index < len(roots)
            or selected.get("mirror_voltages_v") != roots[root_index].get("mirror_voltages_v")
        ):
            raise CandidateContractError("fixed-grid selection root differs from L1 refinement")
        qualification = "selected_real_field_root_fixed_grid_validation_only"
        deferred_gates = list(selected["deferred_hard_gate_failures"])
    elif selection_role == "mrtof_fixed_grid_mirror_voltage_point":
        if (
            selection.get("status") != "prepared_for_independent_fixed_grid_diagnostic"
            or selection.get("source_refinement_sha256") != file_sha256(refinement_path)
        ):
            raise CandidateContractError("fixed-grid voltage point identity is invalid")
        root_index = int(selection.get("source_root_index", -1))
        if not 0 <= root_index < len(roots):
            raise CandidateContractError("fixed-grid voltage point has no source root")
        selected = selection
        qualification = fixed_grid_point_qualification(selection)
        deferred_gates = []
    else:
        raise CandidateContractError("fixed-grid selection receipt role is unsupported")

    family_path = (
        refinement_root / "inputs" / "real_3d_mirror_l0_voltage_family.json"
    ).resolve()
    family = _object(family_path, "frozen real-field L0 family")
    if refinement.get("inputs", {}).get("family_sha256") != file_sha256(family_path):
        raise CandidateContractError("frozen L0 family hash differs from L1 input identity")
    centers = [float(value) for value in family.get("energy_centers_ev", [])]
    step = float(family.get("period_slope_derivative_step_ev"))
    if len(centers) != 3 or centers != sorted(centers) or step <= 0.0:
        raise CandidateContractError("real-field L0 energy nodes or derivative step are invalid")

    axis_root = axis_response_run_dir.resolve()
    axis_manifest = _object(axis_root / "run_manifest.json", "axis response run manifest")
    if (
        axis_manifest.get("project") != "parallel_mirror_dual_stripe_mr_tof"
        or axis_manifest.get("mode") != "real_3d_mirror_l0_voltage_family"
        or axis_manifest.get("status") != "success"
    ):
        raise CandidateContractError("axis response run identity is invalid")

    def axis_output(name: str) -> Path:
        path = (axis_root / "results" / name).resolve()
        matches = [
            item for item in axis_manifest.get("outputs", [])
            if isinstance(item, dict) and Path(str(item.get("path", ""))).resolve() == path
        ]
        if (
            len(matches) != 1
            or not path.is_file()
            or str(matches[0].get("sha256", "")).upper() != file_sha256(path)
        ):
            raise CandidateContractError(f"axis response output is not manifest-bound: {name}")
        return path

    axis_receipt = _object(
        axis_output("mirror_response_sampling_receipt.json"), "axis response receipt",
    )
    if (
        int(axis_receipt.get("axis_basis_schema_version", 0)) != 2
        or axis_receipt.get("axis_period_authority")
        != "integrated_piecewise_linear_sampled_Ez"
    ):
        raise CandidateContractError("axis response basis is not field-consistent schema 2")
    _potential_basis, field_basis = load_axis_response_basis_csv(
        axis_output("real_3d_mirror_axis_response_basis.csv"),
        normalization_v=float(axis_receipt["basis_normalization_v"]),
    )
    voltages = [float(value) for value in selected["mirror_voltages_v"]]
    if len(voltages) != 5 or voltages[0] != 0.0:
        raise CandidateContractError("selected real-field mirror voltage vector is invalid")
    energies = sorted({center + offset * step for center in centers for offset in (-1, 0, 1)})
    mass_th = 524.0
    time_scale = 2.0 * math.sqrt(mass_th) / SPEED_MM_US_PER_SQRT_EV_PER_TH
    records = []
    for index, energy in enumerate(energies, start=1):
        reduced, _turns = reduced_period_from_basis(field_basis, energy, voltages[1:])
        records.append({
            "particle_id": index,
            "target_energy_ev": energy,
            "theory_period_us": time_scale * reduced,
            "position_project_mm": [0.0, float(y_mm), 0.0],
            "direction_project": [0.0, 0.0, 1.0],
        })
    nominal = centers[1]
    nominal_reduced, _turns = reduced_period_from_basis(
        field_basis, nominal, voltages[1:],
    )
    return {
        "schema_version": 2,
        "role": "mrtof_bare_mirror_real_field_period_probe",
        "status": "prepared",
        "qualification": qualification,
        "source_real_field_l1_run_id": refinement_manifest["run_id"],
        "source_real_field_l1_sha256": file_sha256(refinement_path),
        "source_axis_response_run_id": axis_manifest["run_id"],
        "source_selection_receipt_sha256": file_sha256(selection_receipt_path),
        "selected_root_index": root_index,
        "axis_period_authority": "integrated_piecewise_linear_sampled_Ez",
        "mirror_voltages_v": voltages,
        "stripe_biases_v": [0.0, 0.0],
        "prism_voltages_v": [0.0, 0.0],
        "energy_centers_ev": centers,
        "derivative_step_ev": step,
        "nominal_energy_ev": nominal,
        "nominal_theory_period_us": time_scale * nominal_reduced,
        "particle_mass_th": mass_th,
        "particle_charge_e": 1.0,
        "probe_y_mm": float(y_mm),
        "particles": records,
        "theory_normalized_period_slopes_per_v": list(normalized_slopes(
            field_basis, voltages[1:], centers, step,
        )),
        "deferred_l1_probe_convergence_gates": list(
            deferred_gates
        ),
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
    prepare_real = subparsers.add_parser("prepare-real-field")
    prepare_real.add_argument("--refinement-run", required=True, type=Path)
    prepare_real.add_argument("--axis-response-run", required=True, type=Path)
    prepare_real.add_argument("--selection-receipt", required=True, type=Path)
    prepare_real.add_argument("--probe-y-mm", type=float, default=280.0)
    prepare_real.add_argument("--contract-output", required=True, type=Path)
    prepare_real.add_argument("--fly2-output", required=True, type=Path)
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
    elif args.action == "prepare-real-field":
        contract = build_real_field_probe_contract(
            args.refinement_run,
            args.axis_response_run,
            args.selection_receipt,
            y_mm=args.probe_y_mm,
        )
        args.contract_output.parent.mkdir(parents=True, exist_ok=True)
        args.contract_output.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
        write_fly2(contract, args.fly2_output)
        print(f"MRTOF_REAL_FIELD_MIRROR_PERIOD_PREPARE=PASS PARTICLES={len(contract['particles'])}")
    else:
        contract = _object(args.contract, "mirror period probe contract")
        result = analyze_log(contract, args.log)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print("MRTOF_MIRROR_PERIOD_ANALYZE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
