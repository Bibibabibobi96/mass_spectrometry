"""Publish oaTOF accelerator ON voltages from its final resolved design.

The provider owns plane potentials and linear ring-divider voltages. Solver
electrode numbering and the experiment's OFF/pulse policy belong to consumers.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from projects.rf_multipole_ion_optics.core.grounded_shield import require_grounded_potential
from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_geometry import resolve_accelerator_geometry


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite numeric data")
    return float(value)


def linear_ring_electrode_voltages(
    planes_z_mm: Sequence[float], ring_z_mm: Sequence[float],
    endpoint_voltages_v: Sequence[float],
) -> list[float]:
    """Interpolate ordered rings between grid1, optional intermediate2 and grid2.

    Two or three strictly increasing plane positions are required. Each segment
    is linear between its explicit voltage endpoints; rings never extrapolate.
    The repeller is not a ring-divider endpoint. Arithmetic follows the existing
    analyzer Python plan, including selecting the left interval at a shared plane.
    """
    planes = [_finite(value, "plane position") for value in planes_z_mm]
    potentials = [_finite(value, "endpoint voltage") for value in endpoint_voltages_v]
    rings = [_finite(value, "ring position") for value in ring_z_mm]
    if len(planes) not in (2, 3) or len(potentials) != len(planes):
        raise ValueError("linear ring divider requires two or three matching planes and voltages")
    if any(left >= right for left, right in zip(planes, planes[1:])):
        raise ValueError("ring-divider planes must be strictly increasing")
    if any(left >= right for left, right in zip(rings, rings[1:])):
        raise ValueError("ring positions must be strictly increasing")
    if any(z < planes[0] or z > planes[-1] for z in rings):
        raise ValueError("ring position lies outside divider planes; extrapolation is forbidden")
    endpoints = list(zip(planes, potentials, strict=True))
    result = []
    for z in rings:
        (z0, v0), (z1, v1) = next((a, b) for a, b in zip(endpoints, endpoints[1:]) if z <= b[0])
        result.append(v0 + (v1 - v0) * (z - z0) / (z1 - z0))
    return result


def resolve_accelerator_electrical_design(
    oatof_resolved: Mapping[str, Any], *, variant_id: str, geometry_projection: Any = None,
) -> dict[str, Any]:
    """Publish semantic ON voltages and actual provider plane/ring positions.

    No source-dependent voltage inference, OFF policy, solver IDs or waveform is
    introduced. Three-zone topology potentials and the resolved electrode table
    must agree; conflicting representations cannot silently choose a winner.
    """
    projection = (resolve_accelerator_geometry(oatof_resolved, variant_id=variant_id)
                  if geometry_projection is None else geometry_projection)
    if projection.variant_id != variant_id:
        raise ValueError("accelerator geometry and electrical variant differ")
    geometry = projection.local_region
    three_zone = "intermediate2_z_mm" in geometry
    planes = dict(repeller=geometry["repeller_front_z_mm"], grid1=geometry["grid1_z_mm"])
    if three_zone:
        planes["intermediate2"] = geometry["intermediate2_z_mm"]
    planes["grid2"] = geometry["grid2_z_mm"]
    try:
        electrode = oatof_resolved["electrodes_V"]
        voltages = {role: _finite(electrode[role], f"electrodes_V.{role}") for role in planes}
        shield = require_grounded_potential(electrode["shield"], "oaTOF accelerator shield")
        rings = list(geometry["ring_z_mm"])
    except (KeyError, TypeError) as error:
        raise ValueError(f"oaTOF accelerator electrical design is incomplete: {error}") from error
    plane_values = [_finite(value, "accelerator plane position") for value in planes.values()]
    if any(left >= right for left, right in zip(plane_values, plane_values[1:])):
        raise ValueError("accelerator planes must be strictly increasing")
    if three_zone:
        topology = oatof_resolved["accelerator_topology"]["potentials_v"]
        for semantic, native in (("repeller", "repeller"), ("grid1", "intermediate1"),
                                 ("intermediate2", "intermediate2"), ("grid2", "exit")):
            if voltages[semantic] != _finite(topology[native], "topology potential"):
                raise ValueError(f"resolved electrode voltage conflicts with topology: {semantic}")
    divider = [role for role in planes if role != "repeller"]
    voltages["rings"] = linear_ring_electrode_voltages(
        [planes[role] for role in divider], rings, [voltages[role] for role in divider])
    voltages["shield"] = shield
    return dict(schema_version=1, role="oatof_accelerator_electrical_design", variant_id=variant_id,
                frame_id="oatof_global", planes_z_mm=planes, ring_z_mm=rings,
                operating_voltages_v=voltages)
