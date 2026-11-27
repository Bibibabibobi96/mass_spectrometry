"""MR response authority, fine-domain extension and frozen TE1 references."""
from __future__ import annotations

import copy
import math
from typing import Any
from pathlib import Path
import json

from .candidate_voltage import PS_GROUPS, candidate_authority
from .candidate_contract import CandidateContractError
from .operating_authority import vector as _finite_vector

RESPONSE_NORMALIZATION_V = 10000.0
TE1_AXIS = "te1"


def _finite(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("finite numeric assembly input required")
    return float(value)


def _te1_excitation(basis: dict[str, Any]) -> list[float]:
    """Return the five physical mirror voltages of one normalized TE1 direction."""
    direction = basis.get("direction_v_per_coordinate")
    if (
        basis.get("axis") != TE1_AXIS
        or basis.get("normalization_v") != RESPONSE_NORMALIZATION_V
        or not isinstance(direction, list)
        or len(direction) != 4
        or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in direction)
        or max(abs(v) for v in direction) == 0
    ):
        raise ValueError("TE1 response requires a finite nonzero direction and 10000 V normalization")
    magnitude = max(abs(v) for v in direction)
    return [0.0, *[RESPONSE_NORMALIZATION_V * (v / magnitude) for v in direction]]


def _pure_axis_authority(source: dict[str, Any], axis: str) -> dict[str, Any]:
    """Keep frozen bodies/assembly while prescribing one normalized excitation."""
    result = copy.deepcopy(source)
    result["analyzer_electrode_voltages_v"] = [0.0] * 20
    for component in result["component_voltages_v"]:
        component["voltage_v"] = 0.0
    for physical_id in PS_GROUPS[axis]:
        result["analyzer_electrode_voltages_v"][physical_id - 1] = RESPONSE_NORMALIZATION_V
    return result


def _response_authority(source: dict[str, Any], basis: dict[str, Any]) -> dict[str, Any]:
    """Prescribe only the declared pure P/S axis or paired TE1 mirror direction."""
    if basis.get("axis") != TE1_AXIS:
        return _pure_axis_authority(source, basis["axis"])
    excitation = _te1_excitation(basis)
    if basis.get("physical_electrode_ids") != [i + 1 for i, v in enumerate(excitation * 2) if v != 0]:
        raise ValueError("TE1 response physical electrode grouping differs")
    result = copy.deepcopy(source)
    result["analyzer_electrode_voltages_v"] = excitation * 2 + [0.0] * 10
    for component in result["component_voltages_v"]:
        component["voltage_v"] = 0.0
    return result


def _te1_basis_metadata(reference_path: Path) -> dict[str, Any]:
    """Freeze the existing TE1 reference direction; this is not a working voltage."""

    _, coordinate, _, delta = _te1_reference(reference_path)
    basis = {
        "axis": TE1_AXIS,
        "normalization_v": RESPONSE_NORMALIZATION_V,
        "direction_v_per_coordinate": [v / coordinate for v in delta],
    }
    excitation = _te1_excitation(basis)
    basis.update(
        physical_electrode_ids=[i + 1 for i, v in enumerate(excitation * 2) if v != 0],
        excitation_semantics="pure normalized TE1 direction; all other analyzer/component potentials zero",
        combination_semantics="base PA plus physical mirror increment / normalized direction times this PA",
    )
    return basis


def compile_response_coefficients(
    base_authority: dict[str, Any],
    target_voltages_v: dict[str, float],
    available_axes: list[str],
    *,
    mirror_voltages_v: list[float] | None = None,
    te1_basis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Plan pure-basis increments; no field I/O, solve, or trajectory prediction."""
    if (
        set(target_voltages_v) != set(PS_GROUPS)
        or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in target_voltages_v.values()
        )
        or len(available_axes) != len(set(available_axes))
        or not set(available_axes) <= set(PS_GROUPS) | {TE1_AXIS}
        or (TE1_AXIS in available_axes) != (te1_basis is not None)
    ):
        raise ValueError("response coefficients require finite complete P/S targets and unique available axes")
    values = base_authority["analyzer_electrode_voltages_v"]
    coefficients = {}
    for axis, ids in PS_GROUPS.items():
        anchor = values[ids[0] - 1]
        if any(values[i - 1] != anchor for i in ids):
            raise ValueError("baseline P/S group does not have one voltage")
        delta = target_voltages_v[axis] - anchor
        if axis not in available_axes and delta != 0:
            raise ValueError("target changes an axis without a pure response")
        if axis in available_axes:
            coefficient = delta / RESPONSE_NORMALIZATION_V
            if not math.isfinite(coefficient):
                raise ValueError("response coefficient is nonfinite")
            coefficients[axis] = coefficient
    target = candidate_authority(base_authority, target_voltages_v, mirror_voltages_v=mirror_voltages_v)
    if te1_basis is not None:
        excitation = _te1_excitation(te1_basis)
        if values[:10] != values[:5] * 2:
            raise ValueError("TE1 baseline requires equal paired mirror voltages")
        delta = [b - a for a, b in zip(values[:5], target["analyzer_electrode_voltages_v"][:5], strict=True)]
        index = max(range(5), key=lambda i: abs(excitation[i]))
        coefficient = delta[index] / excitation[index]
        # Same absolute voltage reconstruction tolerance as mirror authority;
        # compare actual vectors, never apply an absolute coordinate to an offset.
        if not math.isfinite(coefficient) or any(
            not math.isclose(change, coefficient * voltage, rel_tol=0.0, abs_tol=1e-9)
            for change, voltage in zip(delta, excitation, strict=True)
        ):
            raise ValueError("target mirror increment is incompatible with the frozen TE1 direction")
        coefficients[TE1_AXIS] = coefficient
    return {"target_authority": target, "coefficients": coefficients, "normalization_v": RESPONSE_NORMALIZATION_V}


def extend_fine_z_domain(grid: dict, active: list, update: dict, parent_grid: dict) -> tuple[dict, list]:
    """Derive one lower-z extension without changing any other numerical coordinate."""
    if not isinstance(update, dict) or set(update) != {"solve_z_min_mm", "active_z_min_mm"}:
        raise ValueError("IP fine extension requires only solve_z_min_mm and active_z_min_mm")
    lower, route = (_finite(update[key]) for key in ("solve_z_min_mm", "active_z_min_mm"))
    old_lower = grid["origin_mm"][2]
    if not lower < old_lower or not route < active[2][0] or not lower < route:
        raise ValueError("IP fine extension must extend both lower-z bounds downward with a halo")
    result = copy.deepcopy(grid)
    steps = (old_lower - lower) / grid["pitch_mm"][2]
    if not math.isclose(steps, round(steps), abs_tol=1e-8, rel_tol=0):
        raise ValueError("IP fine extension must align with its unchanged z pitch")
    result["origin_mm"][2] = lower
    result["dimensions"][2] += round(steps)
    coverage = copy.deepcopy(active)
    coverage[2][0] = route
    if (lower < parent_grid["origin_mm"][2]
            or route - lower < grid["pitch_mm"][2]):
        raise ValueError("IP fine extension exceeds its unchanged parent or lacks a gradient halo")
    return result, coverage


def _te1_reference(path: Path) -> tuple[dict[str, Any], float, list[float], list[float]]:
    """Read and validate one schema-1 TE1 mirror variation."""
    reference = json.loads(path.read_text(encoding="utf-8-sig"))
    if (
        reference.get("schema_version") != 1
        or reference.get("role") != "mrtof_terminal_time_mirror_voltage_variation"
        or reference.get("status") != "screening_candidate_materialized"
        or reference.get("qualification") != "diagnostic_only__complete_3d_detector_response_pending"
        or reference.get("mode") != "TE1"
    ):
        raise CandidateContractError("reference must be one schema-1 TE1 variation")
    try:
        coordinate = float(reference["coordinate"])
    except (KeyError, TypeError, ValueError) as error:
        raise CandidateContractError("reference TE1 coordinate is invalid") from error
    if not math.isfinite(coordinate) or coordinate == 0.0:
        raise CandidateContractError("reference TE1 coordinate must be finite and nonzero")
    base = _finite_vector(reference.get("base_mirror_voltages_v"), 5, "base voltages")
    target = _finite_vector(reference.get("target_mirror_voltages_v"), 5, "target voltages")
    delta = _finite_vector(reference.get("voltage_delta_v"), 4, "voltage delta")
    if base[0] != 0.0 or target[0] != 0.0:
        raise CandidateContractError("mirror ground voltage must remain zero")
    if any(
        not math.isclose(target[index + 1] - base[index + 1], delta[index], rel_tol=0.0, abs_tol=1e-9)
        for index in range(4)
    ):
        raise CandidateContractError("reference TE1 variation delta is inconsistent")
    return reference, coordinate, base, delta
