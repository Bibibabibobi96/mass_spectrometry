"""Map the frozen ideal-axial J3 direction to physical three-zone controls.

The mapping is deliberately derived at every finite-difference point.  It does
not linearly interpolate electrode positions or potentials: ``eta`` is a
nonlinear three-zone geometry control, so each ``k*h`` point is recomputed from
the same exact theory used in C2 before it can be handed to a real-PA compiler.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from common.contracts.machine_contracts import validate_schema
from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_candidate_control import (
    FINITE_DIFFERENCE_SCALES,
)
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


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest().upper()


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    return value


def _finite_controls(value: object, *, label: str) -> np.ndarray:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} must be the three physical C2 controls")
    controls = np.asarray(value, dtype=float)
    if not np.all(np.isfinite(controls)):
        raise ValueError(f"{label} must be finite")
    return controls


def _row(result: Mapping[str, Any], source_id: str) -> Mapping[str, Any]:
    if (
        result.get("stage_id") != "C2_J3"
        or result.get("conclusion") != "PASS_CONTINUE"
        or result.get("metrics", {}).get("claim_target") != "j3_local_direction"
    ):
        raise ValueError("C3 physical mapping requires a passing C2_J3 result")
    rows = result.get("metrics", {}).get("rows")
    matches = [
        row for row in rows if isinstance(row, Mapping)
        and row.get("architecture") == "three_zone" and row.get("source_id") == source_id
    ] if isinstance(rows, list) else []
    if len(matches) != 1:
        raise ValueError("C3 physical mapping requires one three-zone C2 row for the source")
    return matches[0]


def _topology(
    source: AffineSource, outer: OuterGeometry, reflectron: ReflectronGeometry,
    controls: np.ndarray,
) -> dict[str, Any]:
    inner = InnerSolution(float(controls[0]), float(controls[1]), float(controls[2]))
    state = derive_three_zone_state(source, outer, inner.eta)
    derivatives = compute_time_derivatives(source, state, reflectron, inner)
    exit_z = -float(derivatives.focus_drift_after_exit_mm)
    intermediate2_z = exit_z - state.zone3_length_mm
    intermediate1_z = intermediate2_z - state.zone2_length_mm
    repeller_z = intermediate1_z - state.zone1_length_mm
    planes = {
        "repeller": repeller_z,
        "intermediate1": intermediate1_z,
        "intermediate2": intermediate2_z,
        "exit": exit_z,
    }
    potentials = {
        "repeller": state.repeller_v,
        "intermediate1": state.grid1_v,
        "intermediate2": state.grid2_v,
        "exit": state.exit_v,
    }
    if not all(planes[left] < planes[right] for left, right in zip(planes, tuple(planes)[1:])):
        raise ValueError("C2 J3 mapping produces unordered accelerator planes")
    if not all(potentials[left] > potentials[right] for left, right in zip(potentials, tuple(potentials)[1:])):
        raise ValueError("C2 J3 mapping produces an inverted accelerator field")
    return {
        "accelerator_topology": {
            "topology_id": "three_zone_accelerator_ideal_v1",
            "planes_global_z_mm": planes,
            "potentials_v": potentials,
        },
        "reflectron": {"u_r1_v": inner.stage1_voltage_drop_v, "f_r2_v_per_mm": inner.stage2_field_v_per_mm},
        "accelerator_physics": {
            "lengths_mm": {"d1": state.zone1_length_mm, "d2": state.zone2_length_mm, "d3": state.zone3_length_mm},
            "fields_v_per_mm": {"e1": state.field1_v_per_mm, "e2": state.field2_v_per_mm, "e3": state.field3_v_per_mm},
            "focus_drift_after_exit_mm": derivatives.focus_drift_after_exit_mm,
        },
    }


def _validate_zero_candidate(variant: Mapping[str, Any], candidate_path: Path) -> None:
    candidate = _load_object(candidate_path)
    if candidate.get("role") != "oatof_three_zone_simion_candidate_resolved":
        raise ValueError("C3 physical mapping Candidate identity differs")
    try:
        expected = candidate["accelerator_topology"]
        observed = variant["accelerator_topology"]
        for section, names in (("planes_global_z_mm", ("repeller", "intermediate1", "intermediate2", "exit")), ("potentials_v", ("repeller", "intermediate1", "intermediate2", "exit"))):
            if any(not math.isclose(float(observed[section][name]), float(expected[section][name]), rel_tol=1e-10, abs_tol=1e-10) for name in names):
                raise ValueError("C2 J3 zero point differs from the frozen Candidate")
        if any(not math.isclose(float(variant["reflectron"][name]), float(candidate["reflectron"][name]), rel_tol=1e-10, abs_tol=1e-10) for name in ("u_r1_v", "f_r2_v_per_mm")):
            raise ValueError("C2 J3 zero point differs from the frozen Candidate")
    except (KeyError, TypeError, ValueError) as exc:
        if "frozen Candidate" in str(exc):
            raise
        raise ValueError("C3 physical mapping Candidate topology is incomplete") from exc
def compile_c2_j3_physical_control_family(
    *, campaign_path: Path, c2_result_path: Path, source_id: str,
    candidate_path: Path | None = None,
) -> dict[str, Any]:
    """Compile the exact physical C3 family from the locked C2 J3 direction."""

    campaign_path, c2_result_path = campaign_path.resolve(), c2_result_path.resolve()
    campaign, result = load_campaign(campaign_path), _load_object(c2_result_path)
    row = _row(result, source_id)
    directions = row.get("directions")
    if not isinstance(directions, Mapping):
        raise ValueError("C2 J3 directions are absent")
    zero = _finite_controls(directions.get("zero", {}).get("controls"), label="C2 zero controls")
    improve = _finite_controls(directions.get("improve", {}).get("controls"), label="C2 improve controls")
    worsen = _finite_controls(directions.get("worsen", {}).get("controls"), label="C2 worsen controls")
    forward, reverse = improve - zero, zero - worsen
    if not np.allclose(forward, reverse, rtol=1e-7, atol=1e-10):
        raise ValueError("C2 improve/zero/worsen controls do not define a symmetric local direction")
    if not np.any(np.abs(forward) > 0.0):
        raise ValueError("C2 J3 physical direction is zero")

    frozen = campaign["frozen_source"]
    source = AffineSource.from_velocity(
        mass_to_charge_th=float(frozen["mass_to_charge_th"]),
        center_x_mm=float(frozen["center_x_mm"]),
        center_velocity_m_per_s=float(frozen["center_velocity_m_per_s"]),
        velocity_slope_m_per_s_per_mm=float(frozen["velocity_slope_m_per_s_per_mm"]),
    )
    anchor = campaign["fixtures"]["low_contrast_anchor"]["outer"]
    outer = OuterGeometry(
        float(anchor["d1_mm"]), float(anchor["l23_mm"]), float(anchor["lambda"]),
        float(anchor["delta_v1_v"]), float(frozen["nominal_energy_per_charge_v"]),
    )
    reflectron = ReflectronGeometry(**campaign["reflectron_geometry"])
    variants = []
    for scale in FINITE_DIFFERENCE_SCALES:
        controls = zero + float(scale) * forward
        variants.append({
            "scale_h": scale,
            "inner_controls": {
                "u_r1_v": float(controls[0]),
                "f_r2_v_per_mm": float(controls[1]),
                "eta": float(controls[2]),
            },
            **_topology(source, outer, reflectron, controls),
            "requires_pa_rebuild": True,
        })
    candidate_record: dict[str, str] | None = None
    if candidate_path is not None:
        candidate_path = candidate_path.resolve()
        _validate_zero_candidate(variants[2], candidate_path)
        candidate_record = {"path": str(candidate_path), "sha256": _sha256(candidate_path)}
    return {
        "role": "oatof_paper1_c3_j3_physical_control_family",
        "qualification": "CANDIDATE_ONLY",
        "source_id": source_id,
        "campaign": {"path": str(campaign_path), "sha256": _sha256(campaign_path)},
        "c2_j3_result": {"path": str(c2_result_path), "sha256": _sha256(c2_result_path)},
        "base_candidate": candidate_record,
        "raw_control_h": {"u_r1_v": float(forward[0]), "f_r2_v_per_mm": float(forward[1]), "eta": float(forward[2])},
        "variants": variants,
        "claim_limit": "Exact C2-to-physical mapping only; no PA, SIMION, derivative, transmission, or peak-width result.",
    }


def compile_c3_j3_variant_candidate(
    *, base_candidate_path: Path, physical_family_path: Path, scale_h: float,
) -> dict[str, Any]:
    """Materialize one C3 variant in the established Candidate input shape."""

    base_candidate_path, physical_family_path = base_candidate_path.resolve(), physical_family_path.resolve()
    base, family = _load_object(base_candidate_path), _load_object(physical_family_path)
    validate_schema(base, "oatof_three_zone_simion_candidate_resolved.schema.json")
    if family.get("role") != "oatof_paper1_c3_j3_physical_control_family":
        raise ValueError("C3 physical family identity differs")
    binding = family.get("base_candidate")
    if not isinstance(binding, Mapping) or binding.get("sha256") != _sha256(base_candidate_path):
        raise ValueError("C3 physical family is not bound to this Candidate")
    variants = family.get("variants")
    matches = [item for item in variants if isinstance(item, Mapping) and float(item.get("scale_h", math.nan)) == scale_h] if isinstance(variants, list) else []
    if len(matches) != 1:
        raise ValueError("C3 physical family does not contain the requested scale")
    variant = matches[0]
    result = json.loads(json.dumps(base))
    result["compiler_mode"] = "C3_J3_EXACT_LOCAL_DIRECTION_V1"
    result["accelerator_topology"] = variant["accelerator_topology"]
    result["accelerator_physics"] = variant["accelerator_physics"]
    result["reflectron"] = variant["reflectron"]
    result["c3_j3_evidence"] = {
        "physical_family": {
            "path": str(physical_family_path),
            "bytes": physical_family_path.stat().st_size,
            "sha256": _sha256(physical_family_path),
        },
        "scale_h": scale_h,
    }
    result["claim_limit"] = "C3 J3 local Candidate only; requires PA rebuild and does not establish a real-field result."
    validate_schema(result, "oatof_three_zone_simion_candidate_resolved.schema.json")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--c2-j3-result", required=True, type=Path)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--variant-candidate-output", type=Path)
    parser.add_argument("--scale-h", type=float)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = compile_c2_j3_physical_control_family(
        campaign_path=args.campaign,
        c2_result_path=args.c2_j3_result,
        source_id=args.source_id,
        candidate_path=args.candidate,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.variant_candidate_output is not None:
        if args.candidate is None or args.scale_h is None:
            parser.error("--variant-candidate-output requires --candidate and --scale-h")
        candidate = compile_c3_j3_variant_candidate(
            base_candidate_path=args.candidate, physical_family_path=args.output,
            scale_h=args.scale_h,
        )
        args.variant_candidate_output.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
