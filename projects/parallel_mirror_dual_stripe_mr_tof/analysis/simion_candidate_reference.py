"""Pure reference and SIMION-GEM source generator for the MR-TOF prototype.

The only coordinate frame accepted here is the project frame: z is reflection,
y is drift, x is transverse focusing, and z=0 is the injection midplane.  This
module deliberately does not import the oa-TOF implementation: its accelerator
is a separate candidate, even though it uses the same two-uniform-field theory.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from projects.orthogonal_accelerator.analysis.accelerator_time_focus import (
    PhysicsContractError,
    compact_exit_focus_bound,
)
from projects.orthogonal_accelerator.analysis.two_zone_geometry import TwoZoneGeometryError, UniformRingPlaneLayout, derive_uniform_ring_planes
from projects.orthogonal_accelerator.analysis.two_zone_theory import TwoZoneTheoryError, TwoZoneTimeFocus, derive_two_zone_time_focus
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_geometry_parameters import derive_mirror_boundaries


class CandidateContractError(ValueError):
    """Raised when the prototype contract cannot describe a physical candidate."""


@dataclass(frozen=True)
class TwoZoneFocus(TwoZoneTimeFocus):
    """MR alias retaining the candidate-reference result type."""


@dataclass(frozen=True)
class TwoZonePlacement:
    """Project-frame locations of the three two-zone accelerator electrodes."""

    repeller_z_mm: float
    grid_1_z_mm: float
    exit_grid_z_mm: float
    focus_y_mm: float
    focus_z_mm: float


@dataclass(frozen=True)
class OperatingEnergyEnvelope:
    """Derived per-charge energy quantities for the coupled accelerator/analyser."""

    pre_acceleration_kinetic_energy_v: float
    net_gain_reference_center_v: float
    selected_net_gain_center_v: float
    net_gain_center_minimum_v: float
    net_gain_center_maximum_v: float
    particle_net_gain_half_range_v: float
    mirror_energy_nodes_v: tuple[float, float, float]
    mirror_b_through_d_maximum_v: float
    post_acceleration_total_energy_reference_v: float


def _number(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise CandidateContractError(f"{name} must be finite")
    return result


def resolve_trajectory_profile(
    contract: dict[str, Any], profile_id: str | None = None,
) -> dict[str, float | str]:
    """Resolve one named SIMION integration profile from the numerical contract."""
    simion = contract.get("simion")
    if not isinstance(simion, dict):
        raise CandidateContractError("simion contract is required")
    profiles = simion.get("trajectory_profiles")
    selected_id = profile_id or simion.get("default_trajectory_profile_id")
    if not isinstance(profiles, dict) or not isinstance(selected_id, str) or not selected_id:
        raise CandidateContractError(
            "simion trajectory_profiles and default_trajectory_profile_id are required"
        )
    profile = profiles.get(selected_id)
    if not isinstance(profile, dict):
        raise CandidateContractError(f"unknown SIMION trajectory profile: {selected_id}")
    if set(profile) != {"trajectory_quality", "maximum_step_us", "purpose"}:
        raise CandidateContractError(
            f"SIMION trajectory profile {selected_id} has an invalid field set"
        )
    trajectory_quality = _number(
        profile.get("trajectory_quality"),
        f"simion.trajectory_profiles.{selected_id}.trajectory_quality",
    )
    maximum_step_us = _number(
        profile.get("maximum_step_us"),
        f"simion.trajectory_profiles.{selected_id}.maximum_step_us",
    )
    purpose = profile.get("purpose")
    if trajectory_quality <= 0.0 or maximum_step_us <= 0.0 or not isinstance(purpose, str) or not purpose:
        raise CandidateContractError(f"SIMION trajectory profile {selected_id} is invalid")
    return {
        "profile_id": selected_id,
        "trajectory_quality": trajectory_quality,
        "maximum_step_us": maximum_step_us,
        "purpose": purpose,
    }


def derive_operating_energy_envelope(
    contract: dict[str, Any], *, selected_center_v: float | None = None,
) -> OperatingEnergyEnvelope:
    """Derive accelerator search and mirror-window energies from native inputs.

    The current mirror and Stripe theory deliberately use the selected net-gain
    reference centre as ``w0``.  The incoming 5 eV/q remains separately visible
    in total-energy bookkeeping and is not silently added to that theory axis.
    """
    energy = contract.get("accelerator_energy_contract")
    if not isinstance(energy, dict):
        raise CandidateContractError("accelerator_energy_contract is required")
    pre_energy = _number(
        energy.get("pre_acceleration_kinetic_energy_per_charge_v"),
        "pre_acceleration_kinetic_energy_per_charge_v",
    )
    reference = _number(
        energy.get("net_gain_reference_center_per_charge_v"),
        "net_gain_reference_center_per_charge_v",
    )
    center_half_range = _number(
        energy.get("net_gain_center_search_half_range_per_charge_v"),
        "net_gain_center_search_half_range_per_charge_v",
    )
    particle_half_range = _number(
        energy.get("maximum_particle_net_gain_deviation_per_charge_v"),
        "maximum_particle_net_gain_deviation_per_charge_v",
    )
    if pre_energy < 0.0 or reference <= 0.0:
        raise CandidateContractError("accelerator energies require pre-energy >= 0 and gain > 0")
    if not 0.0 < center_half_range < reference:
        raise CandidateContractError("net-gain centre search half-range must be in (0, reference)")
    if not 0.0 < particle_half_range < reference - center_half_range:
        raise CandidateContractError(
            "particle net-gain deviation must be positive and below the lowest centre"
        )
    if energy.get("mirror_and_stripe_energy_basis") != "net_acceleration_gain_reference_center":
        raise CandidateContractError(
            "mirror and Stripe energy basis must be the net-gain reference centre"
        )
    nominal = _number(contract.get("nominal", {}).get("energy_per_charge_v"), "nominal energy")
    if nominal != reference:
        raise CandidateContractError(
            "nominal mirror/Stripe energy must equal the net-gain reference centre"
        )
    selected = reference if selected_center_v is None else _number(
        selected_center_v, "selected net-gain center"
    )
    center_minimum = reference - center_half_range
    center_maximum = reference + center_half_range
    if not center_minimum <= selected <= center_maximum:
        raise CandidateContractError("selected net-gain center lies outside the declared search range")
    nodes = (selected - particle_half_range, selected, selected + particle_half_range)
    return OperatingEnergyEnvelope(
        pre_acceleration_kinetic_energy_v=pre_energy,
        net_gain_reference_center_v=reference,
        selected_net_gain_center_v=selected,
        net_gain_center_minimum_v=center_minimum,
        net_gain_center_maximum_v=center_maximum,
        particle_net_gain_half_range_v=particle_half_range,
        mirror_energy_nodes_v=nodes,
        mirror_b_through_d_maximum_v=nodes[0],
        post_acceleration_total_energy_reference_v=pre_energy + selected,
    )


def derive_mirror_voltage_bounds(
    contract: dict[str, Any], *, selected_center_v: float | None = None,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Resolve B--E bounds as hardware-supply/physics intersections."""
    energy = derive_operating_energy_envelope(contract, selected_center_v=selected_center_v)
    envelope = contract["mirror"]["theory_requirements"]["voltage_envelope_v"]
    keys = ("B", "C", "D", "E")
    expected_cap = "minimum_particle_net_acceleration_gain_per_charge_v"
    if any(envelope[key].get("maximum_inclusive_v") != expected_cap for key in keys[:3]):
        raise CandidateContractError("mirror B--D maxima must reference the minimum particle net gain")
    if envelope["E"].get("minimum_exclusive_v") != "maximum_mirror_energy_per_charge_v":
        raise CandidateContractError("mirror E minimum must reference the maximum mirror energy")
    supply_bounds = []
    for key in keys:
        limits = envelope[key].get("power_supply_limits_v")
        if not isinstance(limits, dict):
            raise CandidateContractError(f"mirror {key} power-supply limits are required")
        supply_low = _number(limits.get("minimum_inclusive_v"), f"mirror {key} supply minimum")
        supply_high = _number(limits.get("maximum_inclusive_v"), f"mirror {key} supply maximum")
        if supply_low >= supply_high:
            raise CandidateContractError(f"mirror {key} power-supply limits are empty")
        supply_bounds.append((supply_low, supply_high))
    lower = tuple(
        max(math.nextafter(max(energy.mirror_energy_nodes_v), math.inf), supply_low)
        if key == "E" else supply_low
        for key, (supply_low, _supply_high) in zip(keys, supply_bounds, strict=True)
    )
    upper = tuple(
        supply_high if key == "E" else min(energy.mirror_b_through_d_maximum_v, supply_high)
        for key, (_supply_low, supply_high) in zip(keys, supply_bounds, strict=True)
    )
    if any(low >= high for low, high in zip(lower, upper, strict=True)):
        raise CandidateContractError("resolved mirror voltage envelope is empty")
    return lower, upper


def mirror_power_supply_limits(contract: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Return the current per-electrode supply policy for legacy artifact rebinding."""
    envelope = contract["mirror"]["theory_requirements"]["voltage_envelope_v"]
    result: dict[str, dict[str, float]] = {}
    for key in ("B", "C", "D", "E"):
        limits = envelope[key].get("power_supply_limits_v")
        if not isinstance(limits, dict):
            raise CandidateContractError(f"mirror {key} power-supply limits are required")
        result[key] = {
            "minimum_inclusive_v": _number(
                limits.get("minimum_inclusive_v"), f"mirror {key} supply minimum",
            ),
            "maximum_inclusive_v": _number(
                limits.get("maximum_inclusive_v"), f"mirror {key} supply maximum",
            ),
        }
    return result


def load_contract(
    path: Path, *, inherited_detector_return_path: dict[str, Any] | None = None,
    inherited_mirror_power_supply_limits_v: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Load and minimally validate one MR-TOF candidate contract.

    The two ``inherited_*`` arguments are only for rebinding an older, immutable
    physical artifact whose contract predates a non-geometric policy.  Supplied
    policy must itself be current and valid; an existing upstream policy is
    never overwritten or allowed to disagree.  Default loading remains
    fail-closed.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("project_id") != "parallel_mirror_dual_stripe_mr_tof":
        raise CandidateContractError("project_id must identify the MR-TOF project")
    authority = data.get("geometry_authority", {})
    if authority.get("model") not in {
        "theory_derived_3d",
        "manufactured_CAD_geometry__theory_optimized_operating_point",
    }:
        raise CandidateContractError(
            "geometry authority must be either a theory-derived design or a fixed manufactured "
            "mirror geometry with a theory-optimized operating point"
        )
    frame = data.get("coordinate_system", {})
    if frame.get("frame_id") != "astral.xyz.reflection_z.drift_y.transverse_x.v2":
        raise CandidateContractError("candidate must use the documented Astral coordinate frame")
    mirror = data.get("mirror", {})
    if _number(mirror.get("beam_slot_width_mm"), "beam_slot_width_mm") != 30.0:
        raise CandidateContractError("CAD mirror beam slot is a fixed 30 mm mechanical constraint")
    stripe = data.get("dual_stripe", {})
    if stripe.get("physical_electrode_count") != 4 or stripe.get("theoretical_response_count") != 2:
        raise CandidateContractError("dual stripe requires four physical electrodes and two responses")
    if _number(stripe.get("beam_slot_width_mm"), "ion_foil_beam_slot_width_mm") != 4.0:
        raise CandidateContractError("CAD Ion-Foil beam slot is a fixed 4 mm mechanical constraint")
    if _number(stripe["minimum_width_mm"], "minimum_width_mm") <= 0.0:
        raise CandidateContractError("stripe widths must remain positive")
    if _number(stripe["maximum_width_mm"], "maximum_width_mm") < _number(stripe["minimum_width_mm"], "minimum_width_mm"):
        raise CandidateContractError("maximum stripe width must be >= minimum width")
    if inherited_mirror_power_supply_limits_v is not None:
        holder = {
            "mirror": {
                "theory_requirements": {
                    "voltage_envelope_v": {
                        key: {"power_supply_limits_v": dict(value)}
                        for key, value in inherited_mirror_power_supply_limits_v.items()
                    },
                },
            },
        }
        inherited_limits = mirror_power_supply_limits(holder)
        envelope = mirror.get("theory_requirements", {}).get("voltage_envelope_v", {})
        for key, limits in inherited_limits.items():
            electrode = envelope.get(key)
            if not isinstance(electrode, dict):
                raise CandidateContractError(f"mirror {key} voltage envelope is required")
            existing = electrode.get("power_supply_limits_v")
            if existing is None:
                electrode["power_supply_limits_v"] = dict(limits)
            elif existing != limits:
                raise CandidateContractError(
                    f"mirror {key} inherited power-supply limits disagree with the artifact"
                )
    accelerator = data.get("accelerator")
    if (
        inherited_detector_return_path is not None
        and isinstance(accelerator, dict)
        and accelerator.get("detector_return_path") is None
    ):
        policy_holder = {"accelerator": {"detector_return_path": inherited_detector_return_path}}
        validate_detector_return_path(policy_holder)
        accelerator["detector_return_path"] = dict(inherited_detector_return_path)
    validate_detector_return_path(data)
    # Historical frozen geometry contracts may predate this non-geometric
    # design input. Current contracts that declare it are validated here; the
    # active project baseline is required by its tests to contain it.
    if (
        isinstance(accelerator, dict)
        and accelerator.get("design_source_acceptance") is not None
    ):
        derive_accelerator_design_source_interval(data)
        acceptance = accelerator["design_source_acceptance"]
        if (
            acceptance.get("geometry_rule")
            == "compact_exit_focus_bound_at_maximum_declared_center__native_uniform_ring_planes"
            and data.get("candidate_derivation") is None
        ):
            design = derive_compact_accelerator_acceptance_design(data)
            declared = {
                "gap_1_mm": accelerator.get("gap_1_mm"),
                "gap_2_mm": accelerator.get("gap_2_mm"),
                "repeller_v": accelerator.get("repeller_v"),
                "intermediate_grid_v": accelerator.get("intermediate_grid_v"),
                "exit_grid_v": accelerator.get("exit_grid_v"),
            }
            expected = {
                "gap_1_mm": design["gap1_mm"],
                "gap_2_mm": design["gap2_mm"],
                "repeller_v": design["reference_repeller_v"],
                "intermediate_grid_v": design["reference_intermediate_grid_v"],
                "exit_grid_v": design["reference_exit_grid_v"],
            }
            for name, expected_value in expected.items():
                actual = _number(declared[name], f"accelerator {name}")
                if not math.isclose(
                    actual, float(expected_value), rel_tol=0.0, abs_tol=1e-9
                ):
                    raise CandidateContractError(
                        f"accelerator {name} differs from its compact declared-source acceptance design"
                    )
    derive_operating_energy_envelope(data)
    derive_mirror_voltage_bounds(data)
    return data


def validate_detector_return_path(contract: dict[str, Any]) -> dict[str, Any]:
    """Validate the separate positive-z detector-return branch."""
    accelerator = contract.get("accelerator")
    if not isinstance(accelerator, dict):
        raise CandidateContractError("accelerator contract is required")
    return_path = accelerator.get("detector_return_path")
    required = {
        "status": "required_separate_from_accelerator",
        "detector_half_space": "positive_project_z",
        "detector_surface_normal": "+z",
        "required_hit_direction": "z_negative",
        "accelerator_reentry_after_safe_exit": "forbidden",
    }
    if not isinstance(return_path, dict) or any(return_path.get(key) != value for key, value in required.items()):
        raise CandidateContractError(
            "detector return must remain at z>0, hit toward -z, and forbid accelerator re-entry"
        )
    return return_path


def derive_accelerator_design_source_interval(
    contract: dict[str, Any],
) -> dict[str, float | str]:
    """Resolve the accelerator-owned finite axial source design interval.

    This is a design/acceptance input, not a sampled particle distribution and
    not part of any PA-family cache identity. Individual flights remain free
    to use narrower or otherwise different source profiles.
    """
    accelerator = contract.get("accelerator")
    if not isinstance(accelerator, dict):
        raise CandidateContractError("accelerator contract is required")
    acceptance = accelerator.get("design_source_acceptance")
    if not isinstance(acceptance, dict):
        raise CandidateContractError("accelerator design source acceptance is required")
    if acceptance.get("axis") != "z":
        raise CandidateContractError("accelerator design source acceptance must use project z")
    if (
        acceptance.get("spread_definition")
        != "symmetric_full_width_about_release_position"
    ):
        raise CandidateContractError("accelerator design source width semantics differ")
    if acceptance.get("field_cache_dependency") != "none":
        raise CandidateContractError(
            "source acceptance must not enter PA-family cache identity"
        )
    width = _number(
        acceptance.get("axial_full_width_mm"),
        "accelerator design axial full width",
    )
    gap = _number(accelerator.get("gap_1_mm"), "gap_1_mm")
    release = _number(
        accelerator.get("release_position_in_gap_1_mm"),
        "release_position_in_gap_1_mm",
    )
    if width <= 0.0:
        raise CandidateContractError(
            "accelerator design axial full width must be positive"
        )
    lower = release - width / 2.0
    upper = release + width / 2.0
    if not 0.0 < lower < upper < gap:
        raise CandidateContractError(
            "accelerator design source interval must remain strictly inside gap 1"
        )
    return {
        "axis": "z",
        "axial_full_width_mm": width,
        "release_minimum_in_gap_1_mm": lower,
        "release_maximum_in_gap_1_mm": upper,
        "spread_definition": "symmetric_full_width_about_release_position",
        "field_cache_dependency": "none",
    }


def derive_compact_accelerator_acceptance_design(
    contract: dict[str, Any],
) -> dict[str, float | str | bool]:
    """Derive a compact two-zone geometry for the full declared envelope.

    The highest permitted operating centre is the worst case under homogeneous
    voltage scaling.  Designing that point for the declared per-particle energy
    half-range guarantees every lower operating centre stays inside the same
    downstream mirror/Stripe energy envelope.
    """
    accelerator = contract.get("accelerator")
    if not isinstance(accelerator, dict):
        raise CandidateContractError("accelerator contract is required")
    interval = derive_accelerator_design_source_interval(contract)
    energy = derive_operating_energy_envelope(contract)
    gap1_minimum = _number(accelerator.get("gap_1_mm"), "gap_1_mm")
    release = _number(
        accelerator.get("release_position_in_gap_1_mm"),
        "release_position_in_gap_1_mm",
    )
    try:
        bound = compact_exit_focus_bound(
            energy.net_gain_center_maximum_v,
            energy.particle_net_gain_half_range_v,
            float(interval["axial_full_width_mm"]),
            gap1_minimum,
        )
    except PhysicsContractError as error:
        raise CandidateContractError(
            "declared accelerator source/energy envelope has no compact two-zone design"
        ) from error
    if not math.isclose(release, float(bound["gap1_mm"]) / 2.0, abs_tol=1e-12):
        raise CandidateContractError(
            "compact two-zone acceptance design requires a centered release position"
        )
    simion = contract.get("simion")
    component_mesh = simion.get("component_mesh_mm_per_gu") if isinstance(simion, dict) else None
    accelerator_mesh = component_mesh.get("accelerator") if isinstance(component_mesh, dict) else None
    if not isinstance(accelerator_mesh, list) or len(accelerator_mesh) != 3:
        raise CandidateContractError("accelerator component mesh is required")
    axial_mesh = _number(accelerator_mesh[2], "accelerator axial mesh")
    if axial_mesh <= 0.0:
        raise CandidateContractError("accelerator axial mesh must be positive")
    ideal_gap2 = float(bound["gap2_mm"])
    stage_2_rings = accelerator.get("stage_2_rings")
    if not isinstance(stage_2_rings, dict):
        raise CandidateContractError("accelerator stage-2 ring contract is required")
    ring_count_raw = _number(
        stage_2_rings.get("count"), "accelerator stage-2 ring count"
    )
    ring_count = int(ring_count_raw)
    if ring_count_raw != ring_count:
        raise CandidateContractError("accelerator stage-2 ring count must be an integer")
    if ring_count < 0:
        raise CandidateContractError("accelerator stage-2 ring count must be nonnegative")
    # Every ideal grid and every uniformly spaced physical ring must land on a
    # native axial node.  With N interior rings the complete gap therefore has
    # to be an integer multiple of (N+1)*dz, not merely dz.  Choose the
    # downstream-focus side; workbench placement transports the resulting
    # small positive ideal drift to project z=0.
    gap_quantum = (ring_count + 1) * axial_mesh
    resolved_gap2 = round(
        math.floor((ideal_gap2 + 1e-12) / gap_quantum) * gap_quantum,
        12,
    )
    if resolved_gap2 <= 0.0 or ideal_gap2 - resolved_gap2 >= gap_quantum + 1e-12:
        raise CandidateContractError("accelerator compact gap cannot be resolved on its axial mesh")
    scale = (
        energy.net_gain_reference_center_v
        / energy.net_gain_center_maximum_v
    )
    exit_v = _number(accelerator.get("exit_grid_v"), "exit_grid_v")
    reference_repeller = exit_v + float(bound["repeller_relative_V"]) * scale
    reference_intermediate = (
        exit_v + float(bound["intermediate_relative_V"]) * scale
    )
    try:
        resolved_focus = derive_two_zone_time_focus(
            repeller_v=reference_repeller,
            intermediate_v=reference_intermediate,
            exit_v=exit_v,
            gap_1_mm=float(bound["gap1_mm"]),
            gap_2_mm=resolved_gap2,
            release_position_in_gap_1_mm=release,
            require_downstream_focus=True,
        )
    except TwoZoneTheoryError as error:
        raise CandidateContractError(
            "solver-aligned compact accelerator has no downstream focus"
        ) from error
    return {
        **bound,
        "ideal_gap2_mm": ideal_gap2,
        "gap2_mm": resolved_gap2,
        "gap2_solver_quantization_mm": resolved_gap2 - ideal_gap2,
        "gap2_solver_quantum_mm": gap_quantum,
        "axial_mesh_mm_per_gu": axial_mesh,
        "resolved_compact_accelerator_length_mm": float(bound["gap1_mm"]) + resolved_gap2,
        "design_operating_center_rule": "maximum_declared_net_gain_center",
        "reference_voltage_scaling_rule": "homogeneous_about_exit_grid",
        "net_gain_center_maximum_v": energy.net_gain_center_maximum_v,
        "net_gain_reference_center_v": energy.net_gain_reference_center_v,
        "reference_repeller_v": reference_repeller,
        "reference_intermediate_grid_v": reference_intermediate,
        "reference_exit_grid_v": exit_v,
        "resolved_focus_drift_after_exit_mm": resolved_focus.focus_after_exit_mm,
        "reference_spatial_energy_half_range_v": (
            energy.particle_net_gain_half_range_v * scale
        ),
    }


def derive_two_zone_focus(
    contract: dict[str, Any], *, require_downstream_focus: bool = True,
) -> TwoZoneFocus:
    """Derive the signed ideal focus, downstream-only by default."""
    frame = contract.get("coordinate_system", {})
    if frame.get("frame_id") != "astral.xyz.reflection_z.drift_y.transverse_x.v2":
        raise CandidateContractError("candidate must use the documented Astral coordinate frame")
    accelerator = contract["accelerator"]
    try:
        focus = derive_two_zone_time_focus(
            repeller_v=_number(accelerator["repeller_v"], "repeller_v"),
            intermediate_v=_number(accelerator["intermediate_grid_v"], "intermediate_grid_v"),
            exit_v=_number(accelerator["exit_grid_v"], "exit_grid_v"),
            gap_1_mm=_number(accelerator["gap_1_mm"], "gap_1_mm"),
            gap_2_mm=_number(accelerator["gap_2_mm"], "gap_2_mm"),
            release_position_in_gap_1_mm=_number(
                accelerator["release_position_in_gap_1_mm"], "release_position_in_gap_1_mm"
            ),
            require_downstream_focus=require_downstream_focus,
        )
    except TwoZoneTheoryError as error:
        raise CandidateContractError(str(error)) from error
    result = TwoZoneFocus(
        focus.field_1_v_per_mm, focus.field_2_v_per_mm,
        focus.energy_per_charge_v, focus.focus_after_exit_mm,
    )
    expected_gain = derive_operating_energy_envelope(contract).net_gain_reference_center_v
    if not math.isclose(result.energy_per_charge_v, expected_gain, rel_tol=0.0, abs_tol=1e-9):
        raise CandidateContractError(
            "two-zone reference voltages must produce the declared net-gain reference centre"
        )
    return result


def derive_two_zone_placement(contract: dict[str, Any]) -> TwoZonePlacement:
    """Place the -z accelerator so its first time focus lies on the z=0 plane.

    The focus plane constrains only z.  Its y coordinate is the independently
    declared injection-line coordinate and must not be silently collapsed to
    the project origin.
    """
    accelerator = contract["accelerator"]
    if accelerator.get("axis") != "z_negative":
        raise CandidateContractError("the two-zone Candidate accelerator must accelerate along -z")
    focus_position = accelerator.get("focus_project_position_mm")
    if not isinstance(focus_position, list) or len(focus_position) != 3:
        raise CandidateContractError("focus_project_position_mm must be a three-coordinate project point")
    focus_x = _number(focus_position[0], "focus_project_position_mm[0]")
    focus_z = _number(focus_position[2], "focus_project_position_mm[2]")
    anchor = accelerator.get("focus_y_anchor")
    if not isinstance(anchor, dict) or anchor.get("method") != "audited_triangle_y_bounds_midpoint":
        raise CandidateContractError("accelerator focus y must be derived from an audited prism station")
    station = anchor.get("prism_station")
    prisms = contract.get("prisms", {}).get("electrodes", [])
    matching = [item for item in prisms if isinstance(item, dict) and item.get("station") == station]
    if len(matching) != 1:
        raise CandidateContractError("accelerator focus y anchor must select exactly one prism station")
    coordinates = matching[0].get("polygons_yz_mm", [])
    y_values = [
        _number(polygon[index], "accelerator focus prism y coordinate")
        for polygon in coordinates if isinstance(polygon, list)
        for index in range(0, len(polygon), 2)
    ]
    if not y_values:
        raise CandidateContractError("accelerator focus prism has no y-coordinate evidence")
    focus_y = (min(y_values) + max(y_values)) / 2.0
    if abs(focus_x) > 1e-12 or abs(focus_z) > 1e-12 or accelerator.get("focus_plane_constraint") != "z=0":
        raise CandidateContractError(
            "first time focus must lie on the x=0, z=0 central injection plane"
        )
    focus = derive_two_zone_focus(contract)
    gap_1 = _number(accelerator["gap_1_mm"], "gap_1_mm")
    gap_2 = _number(accelerator["gap_2_mm"], "gap_2_mm")
    # Ions leave the exit grid toward -z.  The upstream repeller/grid planes
    # therefore lie on +z, and the positive post-exit focal distance ends at z=0.
    exit_grid = focus_z + focus.focus_after_exit_mm
    grid_1 = exit_grid + gap_2
    repeller = grid_1 + gap_1
    return TwoZonePlacement(repeller, grid_1, exit_grid, focus_y, focus_z)


def derive_stage_2_ring_layout(
    contract: dict[str, Any], *, placement_contract: dict[str, Any] | None = None,
) -> UniformRingPlaneLayout:
    """Return the physical second-zone ring planes in project ``z`` order.

    The long second field region extends from grid1 toward the lower-``z``
    exit grid.  Ring count and thickness are project inputs; their equal pitch
    is solver-neutral shared geometry derived from the two endpoint planes.
    """
    layout_contract = contract if placement_contract is None else placement_contract
    accelerator = layout_contract.get("accelerator")
    if not isinstance(accelerator, dict):
        raise CandidateContractError("stage-2 rings require an accelerator contract")
    rings = accelerator.get("stage_2_rings")
    if not isinstance(rings, dict):
        raise CandidateContractError("accelerator.stage_2_rings is required")
    count = rings.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise CandidateContractError("accelerator.stage_2_rings.count must be a positive integer")
    if rings.get("outer_frame") != "inherits_declared_repeller_and_grid_frame" or rings.get("beam_aperture") != "inherits_declared_accelerator_aperture":
        raise CandidateContractError("stage-2 rings must inherit the declared accelerator frame and aperture")
    if rings.get("voltage_rule") != "linear_interpolation_from_grid1_to_exit":
        raise CandidateContractError("stage-2 ring voltage rule must interpolate the two field endpoints")
    placement = derive_two_zone_placement(layout_contract)
    try:
        return derive_uniform_ring_planes(
            placement.grid_1_z_mm,
            placement.exit_grid_z_mm,
            count,
            ring_thickness_mm=_number(rings.get("thickness_z_mm"), "accelerator.stage_2_rings.thickness_z_mm"),
        )
    except TwoZoneGeometryError as error:
        raise CandidateContractError(str(error)) from error


def derive_stage_2_ring_voltages(
    contract: dict[str, Any], *, placement_contract: dict[str, Any] | None = None,
) -> tuple[float, ...]:
    """Linearly interpolate stage-2 ring voltages from grid1 to the exit grid."""
    accelerator = contract["accelerator"]
    layout = derive_stage_2_ring_layout(
        contract, placement_contract=placement_contract,
    )
    grid_1 = _number(accelerator["intermediate_grid_v"], "intermediate_grid_v")
    exit_grid = _number(accelerator["exit_grid_v"], "exit_grid_v")
    return tuple(
        grid_1 + (exit_grid - grid_1) * index / (len(layout.centers_mm) + 1)
        for index in range(1, len(layout.centers_mm) + 1)
    )


def build_simion_gem(contract: dict[str, Any]) -> str:
    """Emit a reviewable legacy-GEM electrode map with stable electrode IDs.

    This is a topology source, not an approval to run SIMION: CAD dimensions and
    full PA bounds remain subject to the project CAD audit and numerical contract.
    """
    if contract.get("geometry_authority", {}).get("model") not in {
        "theory_derived_3d",
        "manufactured_CAD_geometry__theory_optimized_operating_point",
    }:
        raise CandidateContractError("SIMION topology needs a qualified Candidate authority")
    mirror = contract["mirror"]
    if _number(mirror.get("beam_slot_width_mm"), "beam_slot_width_mm") != 30.0:
        raise CandidateContractError("CAD mirror beam slot is a fixed 30 mm mechanical constraint")
    stripe = contract["dual_stripe"]
    if _number(stripe.get("beam_slot_width_mm"), "ion_foil_beam_slot_width_mm") != 4.0:
        raise CandidateContractError("CAD Ion-Foil beam slot is a fixed 4 mm mechanical constraint")
    edges = [_number(value, "electrode_z_edges_mm") for value in derive_mirror_boundaries(mirror)["active_start_z_mm"]]
    if len(edges) != 5 or edges != sorted(edges) or edges[0] <= 0.0:
        raise CandidateContractError("five positive ordered mirror electrode edges are required")
    width = _number(stripe["maximum_width_mm"], "maximum_width_mm")
    corridor = _number(stripe["central_grounded_corridor_mm"], "central_grounded_corridor_mm")
    lines = [
        "; MR-TOF Candidate-only topology source for SIMION 2020 legacy GEM.",
        "; Frame: x transverse focus, y drift, z reflection; central plane is z=0.",
        "; IDs 1..5 right mirror, 6..10 left mirror, 11..14 physical dual stripes.",
        "; Stripe pairs (11,12) and (13,14) share independently adjustable voltages.",
        "pa_define(801,801,1601, planar,none,electrostatic,,,0.25,0.25,0.25, surface=none)",
        "locate(400,400,800) {",
    ]
    for index, edge in enumerate(edges, start=1):
        lines.append(f"  e({index}) {{ box3D(-{width},-{width},{edge - 2}, {width},{width},{edge + 2}) }}")
        lines.append(f"  e({index + 5}) {{ box3D(-{width},-{width},{-edge - 2}, {width},{width},{-edge + 2}) }}")
    half = corridor / 2.0
    lines.extend([
        f"  e(11) {{ box3D(-{width},-{width},-{half}, {width},-{width / 2}, {half}) }}",
        f"  e(12) {{ box3D(-{width},{width / 2},-{half}, {width},{width}, {half}) }}",
        f"  e(13) {{ box3D(-{width / 2},-{width},-{half}, {width / 2},-{width / 2}, {half}) }}",
        f"  e(14) {{ box3D(-{width / 2},{width / 2},-{half}, {width / 2},{width}, {half}) }}",
        "  ; The accelerator, prism, grounded guard, detector and raw-node ideal grids are generated only after CAD audit.",
        "}",
        "",
    ])
    return "\n".join(lines)


def write_gem(contract_path: Path, output_path: Path) -> TwoZoneFocus:
    """Validate a contract, emit its GEM source, and return the focus placement."""
    contract = load_contract(contract_path)
    focus = derive_two_zone_focus(contract)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_simion_gem(contract), encoding="utf-8", newline="\n")
    return focus
