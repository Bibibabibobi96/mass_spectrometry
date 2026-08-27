"""Compile a detector-blind, fair real-field candidate pool for Paper 1 J2.

The pool is deliberately finite and pre-registered.  It does not optimize,
simulate, or read any detector outcome: it only applies bounded physical
controls to one resolved three-zone Candidate and rederives every dependent
accelerator quantity.  The later J2 selector may therefore compare weighted
and unweighted scores over precisely the same physical alternatives.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import copy
import json
import math
from typing import Any, Mapping, Sequence

from common.contracts.machine_contracts import validate_schema


ELECTRODES = ("repeller", "intermediate1", "intermediate2", "exit")
MOVABLE_PLANES = ("intermediate2", "exit")
REFLECTRON_CONTROLS = ("u_r1_v", "f_r2_v_per_mm")
OUTPUT_SCHEMA = "oatof_three_zone_simion_candidate_resolved.schema.json"


def _canonical_sha256(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest().upper()


def _finite(value: object, *, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def _values(values: Mapping[str, object], *, names: tuple[str, ...], label: str) -> dict[str, float]:
    if set(values) != set(names):
        raise ValueError(f"{label} must name exactly {names}")
    return {name: _finite(values[name], label=f"{label}.{name}") for name in names}


@dataclass(frozen=True)
class J2CandidateProposal:
    """One bounded physical alternative in a frozen J2 candidate pool."""

    candidate_id: str
    voltage_offset_v: Mapping[str, float]
    plane_offset_mm: Mapping[str, float]
    reflectron_offset: Mapping[str, float]


@dataclass(frozen=True)
class J2CandidatePoolRequest:
    """Pre-registered common candidate set for weighted/unweighted J2 selection."""

    request_id: str
    candidate_pool_id: str
    adjustable_electrodes: tuple[str, ...]
    voltage_abs_bounds_v: Mapping[str, float]
    plane_abs_bounds_mm: Mapping[str, float]
    reflectron_abs_bounds: Mapping[str, float]
    proposals: Sequence[J2CandidateProposal]


def _validate_request(request: J2CandidatePoolRequest) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    if not request.request_id or not request.request_id.replace("_", "").isalnum():
        raise ValueError("request_id must be a non-empty identifier")
    if not request.candidate_pool_id or not request.candidate_pool_id.replace("_", "").isalnum():
        raise ValueError("candidate_pool_id must be a non-empty identifier")
    if not request.adjustable_electrodes or len(set(request.adjustable_electrodes)) != len(request.adjustable_electrodes):
        raise ValueError("adjustable_electrodes must be a nonempty unique list")
    if any(name not in ELECTRODES for name in request.adjustable_electrodes):
        raise ValueError("adjustable_electrodes contains an unknown electrode")
    voltage_bounds = _values(request.voltage_abs_bounds_v, names=ELECTRODES, label="voltage_abs_bounds_v")
    plane_bounds = _values(request.plane_abs_bounds_mm, names=MOVABLE_PLANES, label="plane_abs_bounds_mm")
    reflectron_bounds = _values(request.reflectron_abs_bounds, names=REFLECTRON_CONTROLS, label="reflectron_abs_bounds")
    if any(value < 0.0 for value in (*voltage_bounds.values(), *plane_bounds.values(), *reflectron_bounds.values())):
        raise ValueError("candidate-pool bounds must be non-negative")
    if len(request.proposals) < 2:
        raise ValueError("a J2 fair candidate pool requires at least two proposals")
    ids = [proposal.candidate_id for proposal in request.proposals]
    if any(not candidate_id or not candidate_id.replace("_", "").isalnum() for candidate_id in ids) or len(set(ids)) != len(ids):
        raise ValueError("proposal candidate IDs must be unique non-empty identifiers")
    return voltage_bounds, plane_bounds, reflectron_bounds


def _base_values(candidate: Mapping[str, Any]) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    validate_schema(dict(candidate), OUTPUT_SCHEMA)
    if candidate.get("compiler_mode") not in {"T5_FROZEN_PRIMARY_AND_BRANCH_ONLY", "C3_J3_EXACT_LOCAL_DIRECTION_V1"}:
        raise ValueError("J2 pool base Candidate must be a frozen T5-compatible Candidate")
    topology = candidate["accelerator_topology"]
    planes = _values(topology["planes_global_z_mm"], names=ELECTRODES, label="base planes")
    potentials = _values(topology["potentials_v"], names=ELECTRODES, label="base potentials")
    reflectron = _values(candidate["reflectron"], names=REFLECTRON_CONTROLS, label="base reflectron")
    return planes, potentials, reflectron


def _proposal_values(proposal: J2CandidateProposal) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    return (
        _values(proposal.voltage_offset_v, names=ELECTRODES, label=f"{proposal.candidate_id}.voltage_offset_v"),
        _values(proposal.plane_offset_mm, names=MOVABLE_PLANES, label=f"{proposal.candidate_id}.plane_offset_mm"),
        _values(proposal.reflectron_offset, names=REFLECTRON_CONTROLS, label=f"{proposal.candidate_id}.reflectron_offset"),
    )


def _compile_one(
    base: Mapping[str, Any], request: J2CandidatePoolRequest, proposal: J2CandidateProposal,
    *, voltage_bounds: Mapping[str, float], plane_bounds: Mapping[str, float], reflectron_bounds: Mapping[str, float],
    base_planes: Mapping[str, float], base_potentials: Mapping[str, float], base_reflectron: Mapping[str, float], request_sha256: str,
) -> dict[str, Any]:
    voltage, plane, reflectron = _proposal_values(proposal)
    if any(voltage[name] != 0.0 for name in ELECTRODES if name not in request.adjustable_electrodes):
        raise ValueError("a fixed electrode has a nonzero J2 voltage offset")
    if any(abs(voltage[name]) > voltage_bounds[name] + 1e-12 for name in ELECTRODES):
        raise ValueError("J2 voltage offset exceeds its pre-registered bound")
    if any(abs(plane[name]) > plane_bounds[name] + 1e-12 for name in MOVABLE_PLANES):
        raise ValueError("J2 plane offset exceeds its pre-registered bound")
    if any(abs(reflectron[name]) > reflectron_bounds[name] + 1e-12 for name in REFLECTRON_CONTROLS):
        raise ValueError("J2 reflectron offset exceeds its pre-registered bound")
    planes = {**base_planes, **{name: base_planes[name] + plane[name] for name in MOVABLE_PLANES}}
    potentials = {name: base_potentials[name] + voltage[name] for name in ELECTRODES}
    reflectron_values = {name: base_reflectron[name] + reflectron[name] for name in REFLECTRON_CONTROLS}
    if not all(planes[left] < planes[right] for left, right in zip(ELECTRODES, ELECTRODES[1:])):
        raise ValueError("J2 plane offset changes event topology")
    if not all(potentials[left] > potentials[right] for left, right in zip(ELECTRODES, ELECTRODES[1:])):
        raise ValueError("J2 voltage offset inverts an accelerator field")
    if any(value <= 0.0 for value in reflectron_values.values()):
        raise ValueError("J2 reflectron offset is not physical")
    lengths = {"d1": planes["intermediate1"] - planes["repeller"], "d2": planes["intermediate2"] - planes["intermediate1"], "d3": planes["exit"] - planes["intermediate2"]}
    fields = {"e1": (potentials["repeller"] - potentials["intermediate1"]) / lengths["d1"], "e2": (potentials["intermediate1"] - potentials["intermediate2"]) / lengths["d2"], "e3": (potentials["intermediate2"] - potentials["exit"]) / lengths["d3"]}
    result = copy.deepcopy(base)
    result["compiler_mode"] = "J2_REAL_FIELD_CANDIDATE_POOL_V1"
    result["j2_evidence"] = {"candidate_pool_id": request.candidate_pool_id, "candidate_id": proposal.candidate_id, "pool_request_sha256": request_sha256}
    result["accelerator_topology"] = {"topology_id": "three_zone_accelerator_ideal_v1", "planes_global_z_mm": planes, "potentials_v": potentials}
    result["accelerator_physics"] = {"lengths_mm": lengths, "fields_v_per_mm": fields, "focus_drift_after_exit_mm": -planes["exit"]}
    result["reflectron"] = reflectron_values
    result["claim_limit"] = "Candidate-only J2 common real-field pool input; no detector outcome, solver result, J2 ranking, performance, or Formal qualification."
    validate_schema(result, OUTPUT_SCHEMA)
    return result


def compile_j2_candidate_pool(base_candidate: Mapping[str, Any], request: J2CandidatePoolRequest) -> dict[str, Any]:
    """Compile schema-valid Candidates sharing one physical pool and bounds."""

    voltage_bounds, plane_bounds, reflectron_bounds = _validate_request(request)
    base_planes, base_potentials, base_reflectron = _base_values(base_candidate)
    request_semantic = {
        "request_id": request.request_id, "candidate_pool_id": request.candidate_pool_id,
        "adjustable_electrodes": list(request.adjustable_electrodes),
        "voltage_abs_bounds_v": voltage_bounds, "plane_abs_bounds_mm": plane_bounds,
        "reflectron_abs_bounds": reflectron_bounds,
        "proposals": [
            {"candidate_id": proposal.candidate_id, "voltage_offset_v": _proposal_values(proposal)[0], "plane_offset_mm": _proposal_values(proposal)[1], "reflectron_offset": _proposal_values(proposal)[2]}
            for proposal in request.proposals
        ],
    }
    request_sha256 = _canonical_sha256(request_semantic)
    candidates = [
        _compile_one(base_candidate, request, proposal, voltage_bounds=voltage_bounds, plane_bounds=plane_bounds,
            reflectron_bounds=reflectron_bounds, base_planes=base_planes, base_potentials=base_potentials,
            base_reflectron=base_reflectron, request_sha256=request_sha256)
        for proposal in request.proposals
    ]
    semantic = {"role": "oatof_paper1_j2_real_field_candidate_pool", "base_candidate_sha256": _canonical_sha256(base_candidate), "request": request_semantic, "request_sha256": request_sha256, "candidate_ids": [item["j2_evidence"]["candidate_id"] for item in candidates]}
    return {**semantic, "candidates": candidates, "semantic_sha256": _canonical_sha256(semantic)}
