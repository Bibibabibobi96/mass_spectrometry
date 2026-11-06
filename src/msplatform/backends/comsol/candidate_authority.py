"""Derive complete MR analyzer voltage authorities without solver execution."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_contract import CandidateContractError, load_contract, mirror_power_supply_limits
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.operating_authority import apply_terminal_mirror_variation, fixed_mirror_stripe_source_state
from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_voltage import candidate_authority
from .static_field_binding import _record as record

def read(path: Path) -> dict[str, Any]:
    """Read one UTF-8 JSON authority."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def derive_candidate_authority(
    request: dict[str, Any],
    source_authority: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Derive full voltage/mirror authority independently of unused solve metadata."""
    if request.get("schema_version") != 1 or request.get("role") not in (
        "mrtof_same_mesh_field_provider_request", "mrtof_native_static_field_provider_request"
    ):
        raise ValueError("unsupported field provider request")
    mirror_paths = {}
    mirror_target = None
    if request.get("mirror_voltage_variation_path"):
        reference = Path(request["mirror_reference_trial_manifest"])
        reference_manifest = read(reference)
        for name in (
            "fixed_mirror_stripe_downstream_authority.json", "mirror_exact_k_summary.json",
            "dual_stripe_exact_k_summary.json", "trajectory_contract.json",
            "two_prism_trial_materialization.json",
        ):
            item = named_record(reference_manifest["inputs"], name, name)
            path = Path(item["path"])
            record(reference, path)
            mirror_paths[name] = str(path)
        trajectory = load_contract(Path(mirror_paths["trajectory_contract.json"]))
        contract = load_contract(
            Path(request["mirror_contract_path"]),
            inherited_detector_return_path=trajectory["accelerator"]["detector_return_path"],
            inherited_mirror_power_supply_limits_v=mirror_power_supply_limits(trajectory),
        )
        _, _, energy, base_mirror, _ = fixed_mirror_stripe_source_state(
            read(Path(mirror_paths["fixed_mirror_stripe_downstream_authority.json"])),
            read(Path(mirror_paths["mirror_exact_k_summary.json"])),
            read(Path(mirror_paths["dual_stripe_exact_k_summary.json"])),
            contract,
        )
        scale = float(contract["simion"]["nonaccelerator_scale"])
        if not math.isfinite(scale) or scale <= 0 or scale != float(trajectory["simion"]["nonaccelerator_scale"]):
            raise ValueError("mirror reference and active voltage scales differ or are invalid")
        reference_trial = read(Path(mirror_paths["two_prism_trial_materialization.json"]))
        if reference_trial["selected_axial_energy_per_charge_v"] != energy or any(
            not math.isclose(float(a), float(b), rel_tol=0, abs_tol=1e-9)
            for a, b in zip(
                source_authority["analyzer_electrode_voltages_v"][:10],
                reference_trial["analyzer_electrode_voltages_v"][:10], strict=True,
            )
        ):
            raise ValueError("source MPH mirror voltages differ from the reference actual authority")
        mirror_target, _ = apply_terminal_mirror_variation(
            variation=read(Path(request["mirror_voltage_variation_path"])),
            base_voltages=base_mirror, contract=contract, axial_energy_v=energy,
        )
        mirror_target = [v * scale for v in mirror_target]
        mirror_paths["terminal_time_mirror_voltage_variation.json"] = request["mirror_voltage_variation_path"]
        mirror_paths["mirror_update_contract.json"] = request["mirror_contract_path"]
    candidate = candidate_authority(
        source_authority, request["candidate_voltages_v"], mirror_voltages_v=mirror_target
    )
    return candidate, mirror_paths


def named_record(records: object, filename: str, label: str) -> dict[str, Any]:
    """Return exactly one named manifest record or fail closed."""
    from collections.abc import Mapping

    values = records.values() if isinstance(records, Mapping) else records
    candidates = values if isinstance(values, list) or hasattr(values, "__iter__") else []
    matches = [
        item for item in candidates
        if isinstance(item, Mapping) and Path(str(item.get("path", ""))).name == filename
    ]
    if len(matches) != 1:
        raise CandidateContractError(f"Stripe run must bind exactly one {label}")
    return matches[0]
