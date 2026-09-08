"""Solver-neutral first-prism L0 contract for the MR-TOF Candidate.

This module deliberately models only the reference static first-prism
diagnostic.  It
turns the explicitly declared 4005-eV post-acceleration total energy,
4000-eV fast component, and 5-eV drift component into
an analyser-entry direction, verifies that the CAD triangle is actually on
the declared ray, and records the ideal hard-boundary voltage seed.  It does
not approximate the finite three-dimensional field or invent the second
pre-Stripe prism setting.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    derive_two_zone_placement,
)


class PrismL0Error(ValueError):
    """Raised when the first-prism physical contract is incomplete or invalid."""


@dataclass(frozen=True)
class FirstPrismL0:
    """Resolved first-prism reference state in the documented project frame."""

    total_kinetic_energy_ev: float
    drift_kinetic_energy_ev: float
    fast_kinetic_energy_ev: float
    drift_angle_degrees: float
    entry_position_project_mm: tuple[float, float, float]
    entry_unit_direction_project: tuple[float, float, float]
    target_unit_direction_project: tuple[float, float, float]
    triangle_entry_project_mm: tuple[float, float, float]
    triangle_exit_project_mm: tuple[float, float, float]
    target_plane_z_mm: float
    target_plane_x_mm: float
    target_plane_y_acceptance_mm: tuple[float, float]
    hard_boundary_alpha_degrees: float
    hard_boundary_beta_degrees: float
    hard_boundary_seed_voltage_v: float
    second_prism_status: str

    def receipt(self) -> dict[str, Any]:
        return {"schema_version": 1, "status": "reference_static_prism_candidate__first_prism_l0_only",
                **asdict(self)}


def _number(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise PrismL0Error(f"{label} must be a finite number")
    return float(value)


def _unit(vector: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(vector, list) or len(vector) != 3:
        raise PrismL0Error(f"{label} must be a three-component vector")
    values = tuple(_number(value, label) for value in vector)
    magnitude = math.sqrt(sum(value * value for value in values))
    if magnitude <= 0.0:
        raise PrismL0Error(f"{label} must be nonzero")
    return tuple(value / magnitude for value in values)


def _cross(left: tuple[float, float], right: tuple[float, float]) -> float:
    return left[0] * right[1] - left[1] * right[0]


def _ray_segment_intersection_yz(
    origin: tuple[float, float], direction: tuple[float, float],
    start: tuple[float, float], end: tuple[float, float],
) -> tuple[float, float] | None:
    """Return ray parameter and segment parameter for a nonparallel crossing."""
    edge = (end[0] - start[0], end[1] - start[1])
    denominator = _cross(direction, edge)
    if abs(denominator) <= 1e-12:
        return None
    delta = (start[0] - origin[0], start[1] - origin[1])
    ray_t = _cross(delta, edge) / denominator
    segment_u = _cross(delta, direction) / denominator
    if ray_t <= 0.0 or segment_u < -1e-10 or segment_u > 1.0 + 1e-10:
        return None
    return ray_t, min(1.0, max(0.0, segment_u))


def _triangle_crossings(
    origin_yz: tuple[float, float], direction_yz: tuple[float, float], triangle: list[list[float]],
) -> tuple[tuple[float, float], tuple[float, float]]:
    if not isinstance(triangle, list) or len(triangle) != 3:
        raise PrismL0Error("first-prism triangle must have exactly three y-z vertices")
    vertices = [(_number(vertex[0], "triangle y"), _number(vertex[1], "triangle z"))
                for vertex in triangle if isinstance(vertex, list) and len(vertex) == 2]
    if len(vertices) != 3:
        raise PrismL0Error("first-prism triangle vertices must be y-z pairs")
    hits: list[tuple[float, tuple[float, float]]] = []
    for start, end in zip(vertices, vertices[1:] + vertices[:1]):
        result = _ray_segment_intersection_yz(origin_yz, direction_yz, start, end)
        if result is not None:
            ray_t, fraction = result
            point = (start[0] + fraction * (end[0] - start[0]), start[1] + fraction * (end[1] - start[1]))
            if not hits or abs(ray_t - hits[-1][0]) > 1e-9:
                hits.append((ray_t, point))
    hits.sort(key=lambda item: item[0])
    if len(hits) != 2:
        raise PrismL0Error("declared first-prism entry ray must cross the CAD triangle exactly twice")
    return hits[0][1], hits[1][1]


def derive_first_prism_l0(contract: dict[str, Any]) -> FirstPrismL0:
    """Resolve and validate the Candidate's first-prism L0 reference contract."""
    block = contract.get("prism_transport")
    if not isinstance(block, dict) or block.get("status") != "reference_static_prism_candidate__first_prism_l0_only":
        raise PrismL0Error("prism_transport must declare the first-prism reference Candidate status")
    energy = block.get("energy_partition")
    first = block.get("first_prism")
    second = block.get("second_prism")
    if not isinstance(energy, dict) or not isinstance(first, dict) or not isinstance(second, dict):
        raise PrismL0Error("prism_transport requires energy_partition, first_prism, and second_prism")
    reference_ground = _number(block.get("reference_ground_voltage_v"), "prism reference ground voltage")
    if energy.get("semantics") != "post_acceleration_total_and_orthogonal_components_per_charge_ev":
        raise PrismL0Error("first-prism energy semantics must declare total and orthogonal components")
    total = _number(energy.get("total_kinetic_energy_ev"), "prism total kinetic energy")
    drift = _number(energy.get("drift_kinetic_energy_ev"), "prism drift kinetic energy")
    fast = _number(
        energy.get("fast_reflection_kinetic_energy_ev"), "prism fast-reflection kinetic energy"
    )
    if not 0.0 < drift < total:
        raise PrismL0Error("first-prism drift energy must be positive and smaller than total energy")
    expected_nominal = _number(contract.get("nominal", {}).get("energy_per_charge_v"), "nominal energy")
    if expected_nominal != fast or total != drift + fast:
        raise PrismL0Error("first-prism energy must close as total=drift+nominal axial energy")
    if first.get("electrode_id") != 16 or first.get("station") != "accelerator_exit":
        raise PrismL0Error("first-prism L0 contract must bind CAD electrode id 16 at accelerator_exit")
    if first.get("local_angle_convention") != "positive_beta_is_positive_project_y_about_negative_project_z":
        raise PrismL0Error("first-prism local angle convention is missing or incompatible")
    entry = first.get("entry_reference")
    target = first.get("target_interface")
    if not isinstance(entry, dict) or not isinstance(target, dict):
        raise PrismL0Error("first-prism requires entry_reference and target_interface")
    entry_position = entry.get("position_project_mm")
    if not isinstance(entry_position, list) or len(entry_position) != 3:
        raise PrismL0Error("first-prism entry position must be a project-frame point")
    entry_x, entry_y, entry_z = (_number(value, "first-prism entry position") for value in entry_position)
    entry_direction = _unit(entry.get("direction_project"), "first-prism entry direction")
    placement = derive_two_zone_placement(contract)
    focus_x = _number(contract.get("accelerator", {}).get("focus_project_position_mm", [None])[0], "accelerator focus x")
    if (
        abs(entry_x - focus_x) > 1e-9
        or abs(entry_y - placement.focus_y_mm) > 1e-9
        or abs(entry_z - placement.focus_z_mm) > 1e-9
    ):
        raise PrismL0Error("first-prism entry must agree with the derived two-zone focus")
    if any(abs(component - expected) > 1e-12 for component, expected in zip(entry_direction, (0.0, 0.0, -1.0))):
        raise PrismL0Error("reference first-prism entry must be purely along negative project z")
    prisms = contract.get("prisms", {}).get("electrodes", [])
    matches = [item for item in prisms if isinstance(item, dict) and item.get("id") == 16]
    if len(matches) != 1:
        raise PrismL0Error("CAD geometry must provide exactly one electrode-16 prism")
    polygons = matches[0].get("polygons_yz_mm")
    if not isinstance(polygons, list) or not polygons:
        raise PrismL0Error("first-prism CAD triangle is missing")
    raw = polygons[0]
    triangle = [[raw[index], raw[index + 1]] for index in range(0, len(raw), 2)] if isinstance(raw, list) else []
    crossing_in, crossing_out = _triangle_crossings((entry_y, entry_z), (entry_direction[1], entry_direction[2]), triangle)
    if target.get("axis") != "z":
        raise PrismL0Error("first-prism target interface must be a project-z plane")
    target_z = _number(target.get("coordinate_mm"), "first-prism target plane")
    target_x = _number(target.get("x_mm"), "first-prism target x")
    if target_x != entry_x or target.get("ground_shield_id") != 18:
        raise PrismL0Error("first-prism target must retain the entry x coordinate in grounded shield 18")
    shields = contract.get("prisms", {}).get("ground_shields", [])
    shield = next((item for item in shields if isinstance(item, dict) and item.get("id") == 18), None)
    if not isinstance(shield, dict):
        raise PrismL0Error("grounded shield 18 is required for the first-prism target")
    slots = shield.get("rectangular_slots_mm")
    if not isinstance(slots, list) or len(slots) != 1 or not isinstance(slots[0], dict):
        raise PrismL0Error("grounded shield 18 must provide one finite CAD beam slot")
    box = slots[0].get("box")
    if not isinstance(box, list) or len(box) != 6:
        raise PrismL0Error("grounded shield 18 beam slot must be a six-coordinate box")
    x0, y0, slot_z0, x1, y1, _ = (_number(value, "grounded-1 slot") for value in box)
    if not x0 <= target_x <= x1:
        raise PrismL0Error("first-prism target x must remain inside the grounded-1 slot")
    mirror_face_z = _number(shield.get("cad_negative_inner_mirror_face_z_mm"), "negative mirror inner face")
    if not mirror_face_z < target_z < slot_z0:
        raise PrismL0Error("first-prism target z plane must remain in the CAD gap after the grounded-1 slot")
    target_acceptance = target.get("y_acceptance_from_slot")
    if target_acceptance != "grounded_shield_18_slot_y_bounds":
        raise PrismL0Error("target y acceptance must be derived from the grounded-1 CAD slot")
    theta = math.atan(math.sqrt(drift / fast))
    output = (0.0, math.sin(theta), -math.cos(theta))
    seed = total * math.cos(theta) * math.sin(theta)
    if second.get("electrode_id") != 17 or second.get("status") != "pre_stripe_injection_pending":
        raise PrismL0Error("second prism must remain id-17 and explicitly pending the pre-Stripe injection contract")
    if _number(second.get("voltage_v"), "second-prism pending voltage") != reference_ground:
        raise PrismL0Error("unsolved pre-Stripe second-prism voltage must equal the contractual reference ground")
    return FirstPrismL0(
        total, drift, fast, math.degrees(theta), (entry_x, entry_y, entry_z), entry_direction, output,
        (entry_x, crossing_in[0], crossing_in[1]), (entry_x, crossing_out[0], crossing_out[1]),
        target_z, target_x, (y0, y1), 0.0, math.degrees(theta), seed, str(second["status"]),
    )
