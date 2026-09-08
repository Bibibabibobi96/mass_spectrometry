"""Read a managed mirror L0/L1 Candidate as a frozen downstream input."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common.contracts.file_identity import canonical_json_sha256, file_sha256
from common.contracts.verify_run_manifest import record_path, verify_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_geometry_parameters import (
    derive_mirror_boundaries,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import (
    MirrorL0Design,
    effective_axial_width_mm,
    reduced_period,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    derive_mirror_voltage_bounds,
    derive_operating_energy_envelope,
    load_contract,
)


PROJECT_ID = "parallel_mirror_dual_stripe_mr_tof"
MIRROR_MODE = "analytic_mirror_l0_l1_candidate"
MIRROR_QUALIFICATION = "analytic_2d_candidate__peak_field_and_3d_validation_pending"


@dataclass(frozen=True)
class ManagedMirrorRoot:
    """One independently qualified gamma-target mirror root."""

    design: MirrorL0Design
    nominal_reduced_period_mm_per_sqrt_v: float
    nominal_axial_width_w_mm: float
    source_l0_restart_index: int | None
    gamma_degrees: float


@dataclass(frozen=True)
class ManagedMirrorCandidate:
    """Verified mirror design and derived period consumed by later stages."""

    design: MirrorL0Design
    energy_points_v: tuple[float, float, float]
    nominal_energy_per_charge_v: float
    nominal_reduced_period_mm_per_sqrt_v: float
    nominal_axial_width_w_mm: float
    contract: dict[str, Any]
    run_id: str
    manifest_sha256: str
    contract_sha256: str
    downstream_contract_sha256: str
    l0_receipt_sha256: str
    l1_receipt_sha256: str
    root_family: tuple[ManagedMirrorRoot, ...]


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateContractError(f"{label} is not readable JSON: {path}") from error
    if not isinstance(value, dict):
        raise CandidateContractError(f"{label} must be a JSON object")
    return value


def _record_named(records: object, filename: str, label: str) -> dict[str, Any]:
    if isinstance(records, dict):
        matches = [record for record in records.values() if isinstance(record, dict) and Path(str(record.get("path", ""))).name == filename]
    elif isinstance(records, list):
        matches = [record for record in records if isinstance(record, dict) and Path(str(record.get("path", ""))).name == filename]
    else:
        matches = []
    if len(matches) != 1:
        raise CandidateContractError(f"managed mirror manifest must contain exactly one {label} record")
    return matches[0]


def _finite(value: object, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise CandidateContractError(f"{label} must be numeric") from error
    if not math.isfinite(result):
        raise CandidateContractError(f"{label} must be finite")
    return result


def mirror_stage_contract_projection(contract: dict[str, Any]) -> dict[str, Any]:
    """Return exactly the contract fields owned or read by the mirror stage."""
    try:
        stripe = contract["dual_stripe"]
        return {
            "project_id": contract["project_id"],
            "geometry_authority_model": contract["geometry_authority"]["model"],
            "coordinate_frame_id": contract["coordinate_system"]["frame_id"],
            "nominal_energy_per_charge_v": contract["nominal"]["energy_per_charge_v"],
            "accelerator_energy_contract": contract["accelerator_energy_contract"],
            "mirror": contract["mirror"],
            "load_contract_stripe_validation": {
                "physical_electrode_count": stripe["physical_electrode_count"],
                "theoretical_response_count": stripe["theoretical_response_count"],
                "beam_slot_width_mm": stripe["beam_slot_width_mm"],
                "minimum_width_mm": stripe["minimum_width_mm"],
                "maximum_width_mm": stripe["maximum_width_mm"],
            },
        }
    except (KeyError, TypeError) as error:
        raise CandidateContractError("mirror-stage contract projection is incomplete") from error


def load_managed_mirror_candidate(
    manifest_path: Path,
    downstream_contract_path: Path | None = None,
) -> ManagedMirrorCandidate:
    """Verify a terminal managed run and derive its immutable mirror design.

    Downstream Stripe/prism work supplies only this manifest path.  The
    function verifies every manifest-recorded byte, follows the frozen
    contract and receipt hash chain, and derives ``R`` and ``W`` from the
    selected mirror solution.  It never consults a historical voltage table
    or accepts an independently entered axial width.
    """
    path = manifest_path.resolve()
    manifest_dir = path.parent
    manifest = _load_json(path, "managed mirror run manifest")
    if manifest.get("schema_version") != 2:
        raise CandidateContractError("managed mirror input requires a schema-v2 run manifest")
    if manifest.get("status") != "success" or manifest.get("project") != PROJECT_ID or manifest.get("mode") != MIRROR_MODE:
        raise CandidateContractError("managed mirror manifest has the wrong terminal status, project, or mode")
    try:
        verify_record("run_config", manifest["run_config"], base_dir=manifest_dir)
        for name, record in manifest.get("inputs", {}).items():
            verify_record(f"input {name}", record, base_dir=manifest_dir)
        for index, record in enumerate(manifest.get("outputs", []), start=1):
            verify_record(f"output {index}", record, base_dir=manifest_dir)
    except (AssertionError, KeyError, TypeError, ValueError) as error:
        raise CandidateContractError(f"managed mirror manifest integrity failed: {error}") from error

    run_config_path = record_path(manifest["run_config"], base_dir=manifest_dir)
    run_config = _load_json(run_config_path, "managed mirror run config")
    for field in ("run_id", "project", "mode"):
        if run_config.get(field) != manifest.get(field):
            raise CandidateContractError(f"managed mirror run_config {field} differs from its manifest")

    contract_record = _record_named(manifest.get("inputs"), "simion_candidate_two_zone.json", "frozen contract")
    summary_record = _record_named(manifest.get("outputs"), "summary.json", "summary")
    l0_record = _record_named(manifest.get("outputs"), "mirror_l0_family_receipt.json", "L0 receipt")
    l1_record = _record_named(manifest.get("outputs"), "mirror_l0_l1_candidate_receipt.json", "L1 receipt")
    contract_path = record_path(contract_record, base_dir=manifest_dir)
    summary_path = record_path(summary_record, base_dir=manifest_dir)
    l1_path = record_path(l1_record, base_dir=manifest_dir)
    summary = _load_json(summary_path, "managed mirror summary")
    l1_receipt = _load_json(l1_path, "managed mirror L1 receipt")
    if (
        summary.get("role") != "mrtof_mirror_l0_l1_candidate_summary"
        or summary.get("status") != "success"
        or summary.get("qualification") != MIRROR_QUALIFICATION
    ):
        raise CandidateContractError("managed mirror summary is not the accepted analytic Candidate qualification")
    identity = summary.get("input_identity")
    if not isinstance(identity, dict):
        raise CandidateContractError("managed mirror summary omits its input identity")
    expected_identity = {
        "contract_sha256": str(contract_record.get("sha256", "")).upper(),
        "l0_receipt_sha256": str(l0_record.get("sha256", "")).upper(),
        "l1_receipt_sha256": str(l1_record.get("sha256", "")).upper(),
    }
    if {key: str(identity.get(key, "")).upper() for key in expected_identity} != expected_identity:
        raise CandidateContractError("managed mirror summary hash chain differs from its terminal manifest")

    parent_contract = load_contract(contract_path)
    downstream_contract = (
        load_contract(downstream_contract_path.resolve())
        if downstream_contract_path is not None
        else parent_contract
    )
    if canonical_json_sha256(mirror_stage_contract_projection(parent_contract)) != canonical_json_sha256(
        mirror_stage_contract_projection(downstream_contract)
    ):
        raise CandidateContractError("downstream contract changed one or more mirror-stage inputs")
    mirror = parent_contract["mirror"]
    boundaries = derive_mirror_boundaries(mirror)
    voltage_record = summary.get("selected_mirror_voltages_v")
    if not isinstance(voltage_record, dict) or tuple(voltage_record) != ("A", "B", "C", "D", "E"):
        raise CandidateContractError("managed mirror summary must provide ordered A--E voltages")
    voltages = tuple(_finite(voltage_record[name], f"mirror voltage {name}") for name in ("A", "B", "C", "D", "E"))
    if voltages[0] != 0.0:
        raise CandidateContractError("managed mirror Candidate must keep electrode A grounded")
    energies = derive_operating_energy_envelope(parent_contract).mirror_energy_nodes_v
    if len(energies) != 3 or tuple(sorted(energies)) != energies or voltages[-1] <= max(energies):
        raise CandidateContractError("managed mirror Candidate has invalid energy nodes or terminal retention")
    lower_bounds, upper_bounds = derive_mirror_voltage_bounds(parent_contract)
    if any(not low <= value <= high for value, low, high in zip(voltages[1:], lower_bounds, upper_bounds, strict=True)):
        raise CandidateContractError("managed mirror Candidate violates the derived voltage envelope")
    transverse_half_gap = _finite(
        mirror["theory_requirements"]["berdnikov_transverse_half_gap_mm"],
        "Berdnikov transverse half gap",
    )
    transitions = tuple(
        _finite(value, "mirror transition") for value in boundaries["analytic_transition_z_mm"]
    )
    terminal_plane = _finite(boundaries["terminal_electrode_plane_z_mm"], "mirror terminal plane")

    def design_from_voltages(values: tuple[float, ...]) -> MirrorL0Design:
        return MirrorL0Design(
            transverse_half_gap_mm=transverse_half_gap,
            transition_z_mm=transitions,
            electrode_voltages_v=values,
            terminal_electrode_plane_z_mm=terminal_plane,
            terminal_electrode_voltage_v=values[-1],
        )

    design = design_from_voltages(voltages)
    nominal_energy = _finite(parent_contract["nominal"]["energy_per_charge_v"], "nominal energy")
    period = reduced_period(nominal_energy, design)
    family_record = l1_receipt.get("gamma_target_root_family")
    family_items = family_record.get("roots") if isinstance(family_record, dict) else None
    roots: list[ManagedMirrorRoot] = []
    if isinstance(family_items, list):
        for index, item in enumerate(family_items):
            convergence = item.get("probe_convergence") if isinstance(item, dict) else None
            if not isinstance(convergence, dict) or convergence.get("status") != "pass":
                raise CandidateContractError(f"managed mirror root family member {index} lacks probe convergence")
            root_l0 = item.get("l0_receipt")
            root_l1 = item.get("l1_screen")
            root_values = root_l0.get("electrode_voltages_v") if isinstance(root_l0, dict) else None
            mapping = root_l1.get("nominal_mapping") if isinstance(root_l1, dict) else None
            if not isinstance(root_values, list) or len(root_values) != 5 or not isinstance(mapping, dict):
                raise CandidateContractError(f"managed mirror root family member {index} is incomplete")
            root_voltages = tuple(_finite(value, "mirror root voltage") for value in root_values)
            if root_voltages[0] != 0.0 or root_voltages[-1] <= max(energies):
                raise CandidateContractError(f"managed mirror root family member {index} violates mirror retention")
            root_design = design_from_voltages(root_voltages)
            root_period = reduced_period(nominal_energy, root_design)
            source_index = item.get("source_l0_restart_index")
            if source_index is not None and (not isinstance(source_index, int) or isinstance(source_index, bool) or source_index < 0):
                raise CandidateContractError(f"managed mirror root family member {index} has an invalid source index")
            roots.append(ManagedMirrorRoot(
                design=root_design,
                nominal_reduced_period_mm_per_sqrt_v=root_period,
                nominal_axial_width_w_mm=effective_axial_width_mm(nominal_energy, root_period),
                source_l0_restart_index=source_index,
                gamma_degrees=_finite(mapping.get("gamma_degrees"), "mirror root gamma"),
            ))
    if not roots:
        roots.append(ManagedMirrorRoot(
            design=design,
            nominal_reduced_period_mm_per_sqrt_v=period,
            nominal_axial_width_w_mm=effective_axial_width_mm(nominal_energy, period),
            source_l0_restart_index=None,
            gamma_degrees=_finite(summary.get("gamma_degrees", 90.0), "selected mirror gamma"),
        ))
    return ManagedMirrorCandidate(
        design=design,
        energy_points_v=energies,
        nominal_energy_per_charge_v=nominal_energy,
        nominal_reduced_period_mm_per_sqrt_v=period,
        nominal_axial_width_w_mm=effective_axial_width_mm(nominal_energy, period),
        contract=downstream_contract,
        run_id=str(manifest["run_id"]),
        manifest_sha256=file_sha256(path),
        contract_sha256=expected_identity["contract_sha256"],
        downstream_contract_sha256=(
            file_sha256(downstream_contract_path.resolve())
            if downstream_contract_path is not None
            else expected_identity["contract_sha256"]
        ),
        l0_receipt_sha256=expected_identity["l0_receipt_sha256"],
        l1_receipt_sha256=expected_identity["l1_receipt_sha256"],
        root_family=tuple(roots),
    )
