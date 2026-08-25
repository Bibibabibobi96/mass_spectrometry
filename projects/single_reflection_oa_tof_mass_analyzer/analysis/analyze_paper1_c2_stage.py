"""Run the C2 axial J2/J3 eliminator from frozen C1 source assessments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import spearmanr

from projects.single_reflection_oa_tof_mass_analyzer.analysis.paper1_c2_axial_oracle import (
    AxialC2Design,
    load_c2_axial_source,
    run_axial_c2_screen,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    AffineSource,
    InnerSolution,
    OuterGeometry,
    ReflectronGeometry,
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    return value


def _designs(campaign: dict[str, Any], phase: dict[str, Any]) -> tuple[AxialC2Design, AxialC2Design]:
    frozen = campaign["frozen_source"]
    anchor = campaign["fixtures"]["low_contrast_anchor"]
    phase_source = phase["frozen_phase_space_input"]
    source = AffineSource.from_velocity(
        mass_to_charge_th=float(phase_source["mass_to_charge_Th"]),
        center_x_mm=float(phase_source["release_position_mm"]),
        center_velocity_m_per_s=float(frozen["center_velocity_m_per_s"]),
        velocity_slope_m_per_s_per_mm=float(frozen["velocity_slope_m_per_s_per_mm"]),
    )
    outer_values = anchor["outer"]
    outer = OuterGeometry(
        float(outer_values["d1_mm"]), float(outer_values["l23_mm"]),
        float(outer_values["lambda"]), float(outer_values["delta_v1_v"]),
        float(frozen["nominal_energy_per_charge_v"]),
    )
    reflectron = ReflectronGeometry(**campaign["reflectron_geometry"])
    inner_values = anchor["inner"]
    inner = InnerSolution(
        float(inner_values["u_r1_v"]), float(inner_values["f_r2_v_per_mm"]),
        float(inner_values["eta"]),
    )
    return (
        AxialC2Design(source, outer, reflectron, inner, False, np.asarray([50.0, 1.0])),
        AxialC2Design(source, outer, reflectron, inner, True, np.asarray([50.0, 1.0, 0.2])),
    )


def _direction_summary(rows: list[dict[str, Any]], *, bootstrap_seed: int, replicates: int) -> dict[str, Any]:
    predicted: list[float] = []
    observed: list[float] = []
    total_time_samples: list[np.ndarray] = []
    for row in rows:
        if row["architecture"] != "three_zone":
            continue
        for direction in ("improve", "zero", "worsen"):
            record = row["directions"][direction]
            residual = np.asarray(record.pop("locked_exact_conditional_residual_us"), dtype=float)
            total_time = np.asarray(record.pop("locked_exact_total_time_us"), dtype=float)
            predicted.append(float(record["predicted_total_objective_us2"]))
            observed.append(float(np.var(total_time, ddof=0)))
            total_time_samples.append(total_time)
            record["locked_exact_conditional_residual_variance_us2"] = float(np.var(residual, ddof=0))
            record["locked_exact_total_variance_us2"] = observed[-1]
    correlation = float(spearmanr(predicted, observed).statistic)
    generator = np.random.default_rng(bootstrap_seed)
    samples: list[float] = []
    for _ in range(replicates):
        bootstrap_variance = [
            float(np.var(values[generator.integers(0, values.size, values.size)], ddof=0))
            for values in total_time_samples
        ]
        samples.append(float(spearmanr(predicted, bootstrap_variance).statistic))
    return {
        "three_zone_direction_count": len(predicted),
        "spearman_point_estimate": correlation,
        "spearman_bootstrap_lower_95": float(np.quantile(samples, 0.025)),
        "bootstrap_replicates": replicates,
    }


def analyze_c2_stage(
    *, first_assessment: Path, second_assessment: Path, theory_campaign: Path,
    phase_match: Path, bootstrap_seed: int = 20260825, bootstrap_replicates: int = 200,
) -> dict[str, Any]:
    """Evaluate C2 gates without consuming detector outcomes for model selection."""

    campaign, phase = _load(theory_campaign), _load(phase_match)
    two_zone, three_zone = _designs(campaign, phase)
    phase_source = phase["frozen_phase_space_input"]
    sources = [
        load_c2_axial_source(
            assessment_path=path,
            mass_to_charge_th=float(phase_source["mass_to_charge_Th"]),
            release_position_mm=float(phase_source["release_position_mm"]),
        )
        for path in (first_assessment, second_assessment)
    ]
    if len({source.source_id for source in sources}) != 2:
        raise ValueError("C2 requires two distinct C1 source conditions")
    rows = [run_axial_c2_screen(source, design) for source in sources for design in (two_zone, three_zone)]
    derivative_error = max(
        max(item["gradient_relative_error"] for item in row["derivative_audits"])
        for row in rows
    )
    response_platform_error = max(
        max(item["design_response_step_platform_relative_error"] for item in row["derivative_audits"])
        for row in rows
    )
    direction = _direction_summary(rows, bootstrap_seed=bootstrap_seed, replicates=bootstrap_replicates)
    weighted_beats_unweighted = all(
        row["directions"]["improve"]["locked_exact_total_variance_us2"]
        < row["unweighted"]["locked_exact_total_variance_us2"]
        for row in rows if row["architecture"] == "three_zone"
    )
    gates = {
        "independent_g_derivative_le_1_percent": bool(derivative_error <= 0.01),
        "G_step_platform_le_1_percent": bool(response_platform_error <= 0.01),
        "direction_spearman_ge_0p7": bool(direction["spearman_point_estimate"] >= 0.7),
        "direction_bootstrap_lower_gt_zero": bool(direction["spearman_bootstrap_lower_95"] > 0.0),
        "two_zone_is_zero_control_reference": bool(all(
            row["weighted"]["prediction"]["effective_rank"] == 0
            for row in rows if row["architecture"] == "two_zone"
        )),
        "J2_locked_exact_better_than_unweighted": bool(weighted_beats_unweighted),
    }
    conclusion = "PASS_CONTINUE" if all(gates.values()) else "INCONCLUSIVE_REVISE"
    return {
        "stage_id": "C2",
        "conclusion": conclusion,
        "claim_limit": "Exact ideal-field axial z-vz oracle only; not a full 6D source, real field, transmission, peak-width, or Formal conclusion.",
        "inputs": {"c1_assessments": [str(path.resolve()) for path in (first_assessment, second_assessment)], "theory_campaign": str(theory_campaign.resolve()), "phase_match": str(phase_match.resolve())},
        "metrics": {"maximum_g_derivative_relative_error": derivative_error, "maximum_G_step_platform_relative_error": response_platform_error, "direction_prediction": direction, "gates": gates, "rows": rows},
        "failures": [name for name, passed in gates.items() if not passed],
        "claims_supported": ["Within the frozen ideal axial oracle, the constrained two-zone control space has zero remaining D1/D2-preserving direction while the three-zone arm has one source-weighted direction."],
        "claims_prohibited": ["Any 6D, 3D, detector, FWHM, transmission, cross-mass, or Formal claim."],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-c1", required=True, type=Path)
    parser.add_argument("--second-c1", required=True, type=Path)
    parser.add_argument("--theory-campaign", required=True, type=Path)
    parser.add_argument("--phase-match", required=True, type=Path)
    parser.add_argument("--bootstrap-replicates", type=int, default=200)
    parser.add_argument("--bootstrap-seed", type=int, default=20260825)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = analyze_c2_stage(first_assessment=args.first_c1, second_assessment=args.second_c1, theory_campaign=args.theory_campaign, phase_match=args.phase_match, bootstrap_replicates=args.bootstrap_replicates, bootstrap_seed=args.bootstrap_seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
