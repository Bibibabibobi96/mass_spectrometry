"""Validate the static A/B/C/D axial-acceleration experiment orchestration."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from common.multipole.compile_design_request import (
    compile_governed_design_request_file,
)
from common.multipole.design_profile import resolve_design_profile
from projects.rf_quadrupole_collision_cooling.analysis.generate_interface_particle_table import (
    validate_bundle,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PROJECT_ID = "rf_quadrupole_collision_cooling"
CONTRACT_ROLE = "rf_quadrupole_axial_acceleration_four_arm_experiment"
EXPECTED_ARMS = {
    "A": ("official_transport", "control_2eV_n100", "finite_3d_rf_on"),
    "B": ("official_transport", "candidate_5eV_n100", "finite_3d_rf_on"),
    "C": (
        "explicit_axial_reference",
        "control_2eV_n100",
        "axial_acceleration_rf_on",
    ),
    "D": (
        "endplate_acceleration_reference",
        "control_2eV_n100",
        "endplate_acceleration_rf_on",
    ),
}
EXPECTED_ORDER = [
    "COMSOL_A",
    "COMSOL_B",
    "COMSOL_C",
    "COMSOL_D",
    "COMSOL_delta_report",
    "SIMION_independent_review_if_approved",
]
ACCELERATED_FIELDS = [
    "source_reference_V",
    "output_reference_V",
    "predicted_energy_gain_eV",
    "predicted_output_energy_eV",
]
EXPECTED_AUTHORITIES = {
    "design_profile_registry": "projects/rf_quadrupole_collision_cooling/config/design_profiles.json",
    "source_family": "projects/rf_quadrupole_collision_cooling/config/interface_readiness_particle_source.json",
    "distribution": "projects/rf_quadrupole_collision_cooling/config/official_particle_source.json",
    "bundle_preflight_resolved": "projects/rf_quadrupole_collision_cooling/config/resolved_design_official.json",
    "interface_contract": "projects/rf_quadrupole_collision_cooling/config/interface_contract.json",
}
EXPECTED_SELECTORS = {
    "control_2eV_n100": {
        "operating_point_id": "official_100amu_2eV",
        "particle_count": 100,
        "representation": "canonical10",
    },
    "candidate_5eV_n100": {
        "operating_point_id": "rf_to_oatof_100amu_5eV",
        "particle_count": 100,
        "representation": "canonical10",
    },
}
REQUIRED_BUNDLE_KEYS = [
    "algorithm_version",
    "seed",
    "policy",
    "inputs",
    "operating_point_ids",
    "latent_sha256",
    "sample_family_sha256",
    "coordinate_mapping_version",
    "artifacts",
]
REQUIRED_ARTIFACT_KEYS = [
    "relative_path",
    "operating_point_id",
    "particle_count",
    "representation",
    "sha256",
    "n1000_parent",
]


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _repository_path(relative: str) -> Path:
    path = (REPOSITORY_ROOT / relative).resolve()
    if not path.is_relative_to(REPOSITORY_ROOT) or not path.is_file():
        raise ValueError(f"contract reference is missing or escapes repository: {relative}")
    return path


def _compile_profile(profile_id: str) -> dict[str, Any]:
    profile = resolve_design_profile(REPOSITORY_ROOT, PROJECT_ID, profile_id)
    return compile_governed_design_request_file(
        profile["paths"]["design_request"],
        profile["paths"]["design_variables"],
        profile["paths"]["optimization_envelope"],
        expected_identity=profile["profile"]["identity"],
        provenance_root=REPOSITORY_ROOT,
    )


def _validate_static_contract(
    contract: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    if (
        contract.get("schema_version") != 1
        or contract.get("role") != CONTRACT_ROLE
        or contract.get("project_id") != PROJECT_ID
    ):
        raise ValueError("four-arm experiment identity is invalid")
    authorities = contract["authorities"]
    if authorities != EXPECTED_AUTHORITIES:
        raise ValueError("four-arm authority routing differs")
    for reference in authorities.values():
        _repository_path(reference)
    selectors = contract["source_selectors"]
    if selectors != EXPECTED_SELECTORS:
        raise ValueError("four-arm source selectors differ")
    arms = contract["arms"]
    if [arm.get("arm_id") for arm in arms] != list(EXPECTED_ARMS):
        raise ValueError("four-arm experiment arm order or identity differs")
    resolved: dict[str, dict[str, Any]] = {}
    for arm in arms:
        arm_id = arm["arm_id"]
        expected_profile, expected_selector, expected_case = EXPECTED_ARMS[arm_id]
        if (
            arm.get("design_profile_id") != expected_profile
            or arm.get("source_selector") != expected_selector
            or arm.get("primary_case_id") != expected_case
        ):
            raise ValueError(f"four-arm binding differs for arm {arm_id}")
        resolved[arm_id] = _compile_profile(expected_profile)
        evidence_reference = arm.get("evidence_contract")
        if arm_id in {"C", "D"}:
            evidence = _load(_repository_path(evidence_reference))
            if (
                evidence.get("role") != "multipole_transport_evidence_contract"
                or evidence.get("project_id") != PROJECT_ID
                or evidence.get("design_profile_id") != expected_profile
            ):
                raise ValueError(f"evidence contract differs for arm {arm_id}")
        elif evidence_reference is not None:
            raise ValueError(f"unaccelerated arm {arm_id} must not invent evidence thresholds")
    required_fields = contract["comparison_contract"]["accelerated_arm_invariants"][
        "resolved_fields_required_equal"
    ]
    accelerated_arm_ids = contract["comparison_contract"][
        "accelerated_arm_invariants"
    ].get("arm_ids")
    if accelerated_arm_ids != ["C", "D"] or required_fields != ACCELERATED_FIELDS:
        raise ValueError("accelerated-arm resolved field list differs")
    for field in required_fields:
        if resolved["C"]["axial_drive"][field] != resolved["D"]["axial_drive"][field]:
            raise ValueError(f"C/D resolved axial-drive field differs: {field}")
    if resolved["C"]["axial_drive"]["topology"] != "segmented_rod_axial_acceleration":
        raise ValueError("arm C does not resolve segmented-rod acceleration")
    if resolved["D"]["axial_drive"]["topology"] != "endplate_potential_step":
        raise ValueError("arm D does not resolve endplate acceleration")
    interface = _load(_repository_path(authorities["interface_contract"]))
    surface = contract["comparison_contract"]["acceptance_surface"]
    if (
        surface.get("contract") != authorities["interface_contract"]
        or surface.get("json_pointer") != "/planes/acceptance_detector"
        or float(interface["planes"]["acceptance_detector"]["z_mm"]) != 95.2
    ):
        raise ValueError("four-arm acceptance detector is not the governed z=95.2 mm plane")
    paired = contract["comparison_contract"]["paired_population"]
    if paired != {
        "all_source_particle_ids_required": True,
        "loss_filtering_allowed": False,
        "common_survivor_filtering_allowed": False,
    }:
        raise ValueError("four-arm no-loss paired population policy differs")
    invariants = contract["comparison_contract"]["source_invariants"]
    if invariants != {
        "A_C_D_exact_same_n100_path_and_sha": True,
        "B_same_latent_and_sample_family_as_A": True,
        "B_only_energy_and_velocity_scale_may_change": True,
        "n100_must_be_n1000_prefix": True,
    }:
        raise ValueError("four-arm source invariants differ")
    if contract["comparison_contract"]["execution_order"] != EXPECTED_ORDER:
        raise ValueError("four-arm COMSOL-first/SIMION-review order differs")
    comparison = contract["comparison_contract"]["C_vs_D"]
    if comparison != {
        "reporting_mode": "delta_only",
        "equivalence_tolerance": None,
        "equivalence_claim_allowed": False,
    }:
        raise ValueError("C/D comparison must remain delta-only without a tolerance")
    post_run = contract["comparison_contract"].get("post_run_acceptance")
    if post_run != {
        "run_mode": "resolved_design_transport",
        "state_output": "results/particle_state__primary.csv",
        "metrics_output": "results/finite_3d_transport_metrics.json",
        "terminal_event": "terminal",
        "terminal_status": "transmitted",
        "terminal_reason": "acceptance_detector",
        "claim_limit": (
            "N=100 functional, per-ID descriptive deltas only; no statistical, "
            "Formal, equivalence, superiority, optimization, or cooling claim."
        ),
        "comparison_fields": [
            "kinetic_energy_eV",
            "divergence_angle_deg",
            "radial_position_mm",
            "elapsed_time_us",
        ],
        "descriptive_aggregations": [
            {
                "output_name": "mean_kinetic_energy_eV",
                "field": "kinetic_energy_eV",
                "operation": "mean",
            },
            {
                "output_name": "rms_divergence_angle_deg",
                "field": "divergence_angle_deg",
                "operation": "rms",
            },
            {
                "output_name": "rms_radial_position_mm",
                "field": "radial_position_mm",
                "operation": "rms",
            },
            {
                "output_name": "mean_elapsed_time_us",
                "field": "elapsed_time_us",
                "operation": "mean",
            },
        ],
        "comparisons": [
            {
                "comparison_id": "source_energy_B_minus_A",
                "minuend_arm_id": "B",
                "subtrahend_arm_id": "A",
                "reporting_mode": "functional_delta",
            },
            {
                "comparison_id": "axial_topology_C_minus_D",
                "minuend_arm_id": "C",
                "subtrahend_arm_id": "D",
                "reporting_mode": "delta_only",
            },
        ],
    }:
        raise ValueError("four-arm post-run acceptance contract differs")
    bundle_binding = contract["bundle_binding"]
    if (
        bundle_binding.get("metadata_path") is not None
        or bundle_binding.get("required_role")
        != "rf_quadrupole_paired_particle_source_bundle"
        or bundle_binding.get("required_identity_keys") != REQUIRED_BUNDLE_KEYS
        or bundle_binding.get("artifact_identity_keys") != REQUIRED_ARTIFACT_KEYS
    ):
        raise ValueError("four-arm future bundle binding differs or freezes an unfounded path")
    return resolved, interface


def _artifact(
    metadata: dict[str, Any], selector: dict[str, Any]
) -> dict[str, Any]:
    matches = [
        item
        for item in metadata["artifacts"]
        if item["operating_point_id"] == selector["operating_point_id"]
        and item["particle_count"] == selector["particle_count"]
        and item["representation"] == selector["representation"]
    ]
    if len(matches) != 1:
        raise ValueError("bundle does not uniquely satisfy a four-arm source selector")
    return matches[0]


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _validate_only_energy_velocity_scale(control: Path, candidate: Path) -> None:
    left = _rows(control)
    right = _rows(candidate)
    if len(left) != len(right) or not left:
        raise ValueError("A/B source populations differ")
    invariant_fields = [
        "particle_id",
        "birth_time_s",
        "x_mm",
        "y_mm",
        "z_mm",
        "mass_amu",
        "charge_state",
    ]
    speed_changed = False
    for control_row, candidate_row in zip(left, right, strict=True):
        if any(control_row[field] != candidate_row[field] for field in invariant_fields):
            raise ValueError("B differs from A outside energy/velocity scale")
        control_velocity = [float(control_row[field]) for field in ("vx_m_s", "vy_m_s", "vz_m_s")]
        candidate_velocity = [
            float(candidate_row[field]) for field in ("vx_m_s", "vy_m_s", "vz_m_s")
        ]
        control_speed = math.sqrt(sum(value * value for value in control_velocity))
        candidate_speed = math.sqrt(sum(value * value for value in candidate_velocity))
        if control_speed <= 0 or candidate_speed <= 0:
            raise ValueError("A/B source contains a nonpositive speed")
        for control_value, candidate_value in zip(
            control_velocity, candidate_velocity, strict=True
        ):
            if not math.isclose(
                control_value / control_speed,
                candidate_value / candidate_speed,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise ValueError("B velocity direction differs from A")
        speed_changed = speed_changed or not math.isclose(
            control_speed, candidate_speed, rel_tol=1e-12, abs_tol=0.0
        )
    if not speed_changed:
        raise ValueError("B does not change the source energy/velocity scale")


def validate_experiment(
    contract_path: Path,
    *,
    bundle_metadata_path: Path | None = None,
) -> dict[str, Any]:
    """Validate static authorities and, when supplied, the frozen bundle identity."""
    contract = _load(contract_path)
    resolved, interface = _validate_static_contract(contract)
    result: dict[str, Any] = {
        "schema_version": 1,
        "role": "rf_quadrupole_axial_acceleration_four_arm_validation",
        "static_contract": "PASS",
        "acceptance_detector_z_mm": interface["planes"]["acceptance_detector"]["z_mm"],
        "C_D_resolved_axial_drive_identity": "PASS",
        "execution_order": "COMSOL_FIRST_SIMION_REVIEW",
        "C_D_claim_mode": "DELTA_ONLY",
        "run_ready": False,
    }
    if bundle_metadata_path is None:
        result["status"] = "BLOCKED_MISSING_PAIRED_BUNDLE_METADATA"
        return result
    authorities = contract["authorities"]
    metadata = validate_bundle(
        bundle_metadata_path,
        _repository_path(authorities["source_family"]),
        _repository_path(authorities["distribution"]),
        _repository_path(authorities["bundle_preflight_resolved"]),
    )
    binding = contract["bundle_binding"]
    if metadata.get("role") != binding["required_role"]:
        raise ValueError("bundle role differs from four-arm requirement")
    if not set(binding["required_identity_keys"]).issubset(metadata):
        raise ValueError("bundle metadata lacks required four-arm identity keys")
    for item in metadata["artifacts"]:
        if not set(binding["artifact_identity_keys"]).issubset(item):
            raise ValueError("bundle artifact lacks required four-arm identity keys")
    selectors = contract["source_selectors"]
    control = _artifact(metadata, selectors["control_2eV_n100"])
    candidate = _artifact(metadata, selectors["candidate_5eV_n100"])
    arm_sources = {
        arm["arm_id"]: _artifact(metadata, selectors[arm["source_selector"]])
        for arm in contract["arms"]
    }
    if not (
        arm_sources["A"]["relative_path"]
        == arm_sources["C"]["relative_path"]
        == arm_sources["D"]["relative_path"]
        and arm_sources["A"]["sha256"]
        == arm_sources["C"]["sha256"]
        == arm_sources["D"]["sha256"]
    ):
        raise ValueError("A/C/D do not bind the exact same N=100 source")
    bundle_root = bundle_metadata_path.parent.resolve()
    control_path = (bundle_root / control["relative_path"]).resolve()
    candidate_path = (bundle_root / candidate["relative_path"]).resolve()
    if not control_path.is_relative_to(bundle_root) or not candidate_path.is_relative_to(bundle_root):
        raise ValueError("four-arm bundle artifact escapes its metadata root")
    _validate_only_energy_velocity_scale(control_path, candidate_path)
    result.update(
        {
            "status": "READY_FOR_COMSOL_FIRST_EXECUTION",
            "run_ready": True,
            "bundle_sample_family_sha256": metadata["sample_family_sha256"],
            "A_C_D_source_sha256": arm_sources["A"]["sha256"],
            "B_source_sha256": arm_sources["B"]["sha256"],
        }
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=REPOSITORY_ROOT
        / "projects"
        / PROJECT_ID
        / "config"
        / "axial_acceleration_four_arm_experiment.json",
    )
    parser.add_argument("--bundle-metadata", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate_experiment(
        args.contract, bundle_metadata_path=args.bundle_metadata
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
