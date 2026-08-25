"""Compile local, physically bounded three-zone control perturbations for Paper 1.

This is deliberately not an optimizer and does not consume arrival-time data.  It
turns a pre-registered electrode direction into the five finite-difference points
needed by C3 (``-2h, -h, 0, +h, +2h``), while refusing a topology inversion or an
unbounded geometry change.  The integration owns the later PA/IOB rebuild and
SIMION execution; this module owns only the solver-neutral request identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from typing import Any, Mapping


ELECTRODES = ("repeller", "intermediate1", "intermediate2", "exit")
MOVABLE_PLANES = ("intermediate2", "exit")
FINITE_DIFFERENCE_SCALES = (-2.0, -1.0, 0.0, 1.0, 2.0)


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest().upper()


def _finite(value: object, *, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def _mapping(values: Mapping[str, object], *, keys: tuple[str, ...], label: str) -> dict[str, float]:
    if set(values) != set(keys):
        raise ValueError(f"{label} must name exactly {keys}")
    return {name: _finite(values[name], label=f"{label}.{name}") for name in keys}


@dataclass(frozen=True)
class CandidateControlRequest:
    """One pre-registered physical direction around a three-zone Candidate.

    ``voltage_direction_v`` and ``plane_direction_mm`` are *one h* physical
    perturbations, not fitted values.  The latter is restricted to grid2 and the
    exit because moving upstream planes would silently change the injection
    reference.  A zero geometry direction is the normal voltage-only C3 case.
    """

    request_id: str
    adjustable_electrodes: tuple[str, ...]
    voltage_direction_v: Mapping[str, float]
    plane_direction_mm: Mapping[str, float]
    voltage_abs_bounds_v: Mapping[str, float]
    plane_abs_bounds_mm: Mapping[str, float]

    def validated(self) -> "CandidateControlRequest":
        if not self.request_id or not self.request_id.replace("_", "").isalnum():
            raise ValueError("request_id must be a non-empty identifier")
        if not self.adjustable_electrodes or len(set(self.adjustable_electrodes)) != len(self.adjustable_electrodes):
            raise ValueError("adjustable_electrodes must be a nonempty unique list")
        if any(name not in ELECTRODES for name in self.adjustable_electrodes):
            raise ValueError("adjustable_electrodes contains an unknown electrode")
        if "intermediate2" not in self.adjustable_electrodes:
            raise ValueError("a J3 local request must expose the grid2 electrode")
        voltage = _mapping(self.voltage_direction_v, keys=ELECTRODES, label="voltage_direction_v")
        planes = _mapping(self.plane_direction_mm, keys=MOVABLE_PLANES, label="plane_direction_mm")
        voltage_bounds = _mapping(self.voltage_abs_bounds_v, keys=ELECTRODES, label="voltage_abs_bounds_v")
        plane_bounds = _mapping(self.plane_abs_bounds_mm, keys=MOVABLE_PLANES, label="plane_abs_bounds_mm")
        if any(value < 0.0 for value in (*voltage_bounds.values(), *plane_bounds.values())):
            raise ValueError("control bounds must be non-negative")
        if any(voltage[name] != 0.0 for name in ELECTRODES if name not in self.adjustable_electrodes):
            raise ValueError("a fixed electrode has a nonzero voltage direction")
        if not any(value != 0.0 for value in voltage.values()) and not any(value != 0.0 for value in planes.values()):
            raise ValueError("local control direction is identically zero")
        return self


def _candidate_topology(candidate: Mapping[str, Any]) -> tuple[dict[str, float], dict[str, float]]:
    if (
        candidate.get("role") != "oatof_three_zone_simion_candidate_resolved"
        or candidate.get("qualification") != "CANDIDATE_ONLY"
    ):
        raise ValueError("C3 local control requires a three-zone Candidate-only input")
    topology = candidate.get("accelerator_topology")
    if not isinstance(topology, Mapping) or topology.get("topology_id") != "three_zone_accelerator_ideal_v1":
        raise ValueError("C3 local control Candidate topology differs")
    planes_raw, potentials_raw = topology.get("planes_global_z_mm"), topology.get("potentials_v")
    if not isinstance(planes_raw, Mapping) or not isinstance(potentials_raw, Mapping):
        raise ValueError("C3 local control Candidate topology is incomplete")
    planes = _mapping(planes_raw, keys=ELECTRODES, label="candidate planes")
    potentials = _mapping(potentials_raw, keys=ELECTRODES, label="candidate potentials")
    if not all(planes[left] < planes[right] for left, right in zip(ELECTRODES, ELECTRODES[1:])):
        raise ValueError("C3 local control Candidate planes are not ordered")
    if not all(potentials[left] > potentials[right] for left, right in zip(ELECTRODES, ELECTRODES[1:])):
        raise ValueError("C3 local control Candidate potentials are not ordered")
    return planes, potentials


def compile_local_control_candidates(
    candidate: Mapping[str, Any], request: CandidateControlRequest,
) -> dict[str, Any]:
    """Compile the complete symmetric C3 finite-difference family.

    The returned records are immutable inputs for a later layout/PA compiler;
    their identity includes the entire base candidate and request, so a numerical
    result cannot be detached from its control direction or bounds.
    """

    request = request.validated()
    reference_planes, reference_potentials = _candidate_topology(candidate)
    voltage = _mapping(request.voltage_direction_v, keys=ELECTRODES, label="voltage_direction_v")
    plane = _mapping(request.plane_direction_mm, keys=MOVABLE_PLANES, label="plane_direction_mm")
    voltage_bounds = _mapping(request.voltage_abs_bounds_v, keys=ELECTRODES, label="voltage_abs_bounds_v")
    plane_bounds = _mapping(request.plane_abs_bounds_mm, keys=MOVABLE_PLANES, label="plane_abs_bounds_mm")
    variants: list[dict[str, Any]] = []
    for scale in FINITE_DIFFERENCE_SCALES:
        potentials = {name: reference_potentials[name] + scale * voltage[name] for name in ELECTRODES}
        planes = {**reference_planes, **{name: reference_planes[name] + scale * plane[name] for name in MOVABLE_PLANES}}
        if any(abs(potentials[name] - reference_potentials[name]) > voltage_bounds[name] + 1e-12 for name in ELECTRODES):
            raise ValueError("C3 voltage perturbation exceeds its pre-registered bound")
        if any(abs(planes[name] - reference_planes[name]) > plane_bounds[name] + 1e-12 for name in MOVABLE_PLANES):
            raise ValueError("C3 plane perturbation exceeds its pre-registered bound")
        if not all(planes[left] < planes[right] for left, right in zip(ELECTRODES, ELECTRODES[1:])):
            raise ValueError("C3 plane perturbation changes event topology")
        if not all(potentials[left] > potentials[right] for left, right in zip(ELECTRODES, ELECTRODES[1:])):
            raise ValueError("C3 voltage perturbation inverts an accelerator field")
        variants.append({
            "scale": scale,
            "variant_id": f"{request.request_id}_{scale:+.0f}h".replace("+", "plus").replace("-", "minus"),
            "accelerator_topology": {"topology_id": "three_zone_accelerator_ideal_v1", "planes_global_z_mm": planes, "potentials_v": potentials},
            "requires_pa_rebuild": True,
        })
    semantic = {
        "role": "oatof_paper1_c3_local_control_family",
        "base_candidate_sha256": _canonical_sha256(candidate),
        "request": {
            "request_id": request.request_id,
            "adjustable_electrodes": list(request.adjustable_electrodes),
            "voltage_direction_v": voltage,
            "plane_direction_mm": plane,
            "voltage_abs_bounds_v": voltage_bounds,
            "plane_abs_bounds_mm": plane_bounds,
        },
        "scales_h": list(FINITE_DIFFERENCE_SCALES),
        "variants": variants,
        "claim_limit": "Compiler-only C3 input; no real-field derivative, transmission, FWHM, or J2 conclusion.",
    }
    return {**semantic, "semantic_sha256": _canonical_sha256(semantic)}
