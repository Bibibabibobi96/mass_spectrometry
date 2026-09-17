"""Load the verified fixed-mirror, variable-slow-energy Stripe operating point."""
from __future__ import annotations

from dataclasses import dataclass
import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping

from common.contracts.file_identity import file_sha256
from common.contracts.verify_run_manifest import record_path, verify_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.fixed_grid_mirror_stripe_handoff import (
    load_fixed_grid_mirror_point,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import MirrorL0Design
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


@dataclass(frozen=True)
class FixedMirrorStripeOperatingPoint:
    """One manifest-bound mirror/Stripe centre for downstream components."""

    stripe_run_id: str
    fixed_grid_run_id: str
    axial_energy_per_charge_v: float
    slow_energy_per_charge_v: float
    mirror_voltages_v: tuple[float, float, float, float, float]
    stripe_biases_v: tuple[float, float]
    target_period_ratio: float
    predicted_period_ratio: float
    mirror_reduced_period_mm_per_sqrt_v: float
    mirror_axial_width_w_mm: float
    mirror_design: MirrorL0Design
    contract: dict[str, Any]


def _object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateContractError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise CandidateContractError(f"{label} must be an object")
    return value


def _named_record(records: object, filename: str, label: str) -> Mapping[str, Any]:
    values = records.values() if isinstance(records, Mapping) else records
    candidates = values if isinstance(values, list) or hasattr(values, "__iter__") else []
    matches = [
        item for item in candidates
        if isinstance(item, Mapping) and Path(str(item.get("path", ""))).name == filename
    ]
    if len(matches) != 1:
        raise CandidateContractError(f"Stripe run must bind exactly one {label}")
    return matches[0]


def _finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CandidateContractError(f"{label} must be finite") from exc
    if not math.isfinite(result):
        raise CandidateContractError(f"{label} must be finite")
    return result


def load_fixed_mirror_stripe_operating_point(
    stripe_manifest_path: Path,
    downstream_contract_path: Path | None = None,
) -> FixedMirrorStripeOperatingPoint:
    """Verify and join the r130-style mirror evidence with its r3-style Stripe seed."""
    path = stripe_manifest_path.resolve()
    root = path.parent
    manifest = _object(path, "fixed-mirror Stripe manifest")
    if (
        manifest.get("schema_version") != 2
        or manifest.get("project") != "parallel_mirror_dual_stripe_mr_tof"
        or manifest.get("mode") != "dual_stripe_fixed_grid_native_downstream_seed"
        or manifest.get("status") != "success"
    ):
        raise CandidateContractError("fixed-mirror Stripe manifest identity is invalid")
    try:
        verify_record("run_config", manifest["run_config"], base_dir=root)
        for name, record in manifest.get("inputs", {}).items():
            verify_record(f"input {name}", record, base_dir=root)
        for index, record in enumerate(manifest.get("outputs", []), start=1):
            verify_record(f"output {index}", record, base_dir=root)
    except (AssertionError, KeyError, TypeError, ValueError) as exc:
        raise CandidateContractError("fixed-mirror Stripe manifest integrity failed") from exc

    parent_record = _named_record(
        manifest.get("inputs"), "parent_fixed_grid_run_manifest.json", "fixed-grid parent",
    )
    contract_record = _named_record(
        manifest.get("inputs"), "simion_candidate_two_zone.json", "downstream contract",
    )
    summary_record = _named_record(manifest.get("outputs"), "summary.json", "summary")
    parent_path = record_path(parent_record, base_dir=root)
    contract_path = record_path(contract_record, base_dir=root)
    summary_path = record_path(summary_record, base_dir=root)
    parent_manifest = _object(parent_path, "fixed-grid parent manifest")
    summary = _object(summary_path, "fixed-mirror Stripe summary")
    mirror = load_fixed_grid_mirror_point(
        parent_path,
        downstream_contract_path.resolve()
        if downstream_contract_path is not None
        else contract_path,
    )
    if (
        summary.get("schema_version") != 3
        or summary.get("role")
        != "mrtof_dual_stripe_paper_theory_instance_specific_operating_seed_family"
        or summary.get("status")
        != "fixed_grid_native_mirror_exact_K_slow_energy_and_spatial_return_inverse_complete"
        or str(summary.get("fixed_grid_manifest_sha256", "")).upper()
        != file_sha256(parent_path)
    ):
        raise CandidateContractError("fixed-mirror Stripe summary identity is invalid")
    seed = summary.get("selected_seed")
    materialized = (
        seed.get("native_spatial_return_materialization")
        if isinstance(seed, Mapping) else None
    )
    if not isinstance(seed, Mapping) or not isinstance(materialized, Mapping):
        raise CandidateContractError("fixed-mirror Stripe summary lacks its selected materialization")
    axial = _finite(seed.get("selected_axial_energy_per_charge_v"), "selected axial energy")
    slow = _finite(seed.get("selected_exact_K_slow_energy_per_charge_v"), "selected slow energy")
    target = _finite(seed.get("target_drift_period_ratio"), "target K")
    predicted = _finite(seed.get("predicted_continuous_oscillation_count"), "predicted K")
    biases = tuple(_finite(value, "Stripe bias") for value in seed.get("stripe_biases_v", []))
    materialized_biases = tuple(
        _finite(value, "materialized Stripe bias")
        for value in materialized.get("stripe_biases_v", [])
    )
    if (
        axial != mirror.nominal_energy_per_charge_v
        or slow <= 0.0
        or len(biases) != 2
        or biases != materialized_biases
        or _finite(materialized.get("source_slow_energy_per_charge_v"), "materialized slow energy") != slow
        or _finite(materialized.get("axial_energy_per_charge_v"), "materialized axial energy") != axial
        or _finite(materialized.get("continuous_oscillation_count"), "materialized K") != predicted
        or not math.isclose(predicted, target, rel_tol=0.0, abs_tol=1e-12)
    ):
        raise CandidateContractError("fixed-mirror Stripe selected point is internally inconsistent")
    return FixedMirrorStripeOperatingPoint(
        stripe_run_id=str(manifest["run_id"]),
        fixed_grid_run_id=str(parent_manifest["run_id"]),
        axial_energy_per_charge_v=axial,
        slow_energy_per_charge_v=slow,
        mirror_voltages_v=tuple(mirror.design.electrode_voltages_v),
        stripe_biases_v=(biases[0], biases[1]),
        target_period_ratio=target,
        predicted_period_ratio=predicted,
        mirror_reduced_period_mm_per_sqrt_v=mirror.nominal_reduced_period_mm_per_sqrt_v,
        mirror_axial_width_w_mm=mirror.nominal_axial_width_w_mm,
        mirror_design=mirror.design,
        contract=mirror.contract,
    )


def build_downstream_authority_receipt(stripe_manifest_path: Path) -> dict[str, Any]:
    """Serialize the compact subset consumed by accelerator and prism workflows."""
    point = load_fixed_mirror_stripe_operating_point(stripe_manifest_path)
    return {
        "schema_version": 1,
        "role": "mrtof_fixed_mirror_stripe_downstream_operating_authority",
        "status": "success",
        "qualification": "analytic_exact_K_center__finite_3d_stripe_and_full_flight_pending",
        "source_stripe_run_id": point.stripe_run_id,
        "source_fixed_grid_run_id": point.fixed_grid_run_id,
        "source_stripe_manifest_sha256": file_sha256(stripe_manifest_path.resolve()),
        "axial_energy_per_charge_v": point.axial_energy_per_charge_v,
        "slow_energy_per_charge_v": point.slow_energy_per_charge_v,
        "mirror_voltages_v": list(point.mirror_voltages_v),
        "stripe_biases_v": list(point.stripe_biases_v),
        "target_period_ratio": point.target_period_ratio,
        "predicted_period_ratio": point.predicted_period_ratio,
        "mirror_reduced_period_mm_per_sqrt_v": point.mirror_reduced_period_mm_per_sqrt_v,
        "mirror_axial_width_w_mm": point.mirror_axial_width_w_mm,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    receipt = build_downstream_authority_receipt(arguments.manifest)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(receipt, indent=2, allow_nan=False) + "\n", encoding="utf-8",
    )
    print("MRTOF_FIXED_MIRROR_STRIPE_AUTHORITY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
