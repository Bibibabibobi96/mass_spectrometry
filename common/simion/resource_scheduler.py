"""Repository-level planning for independent SIMION particle batches.

This module does not discover or launch campaigns.  A project submits an already
authorized request and keeps ownership of its physics, inputs and outputs.  The
shared planner makes the resource decision reproducible for RF and electrostatic
SIMION work alike, using a matching completed profile when available and a
one-batch bootstrap when it is not.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from common.simion.particle_batching import plan_single_wave_batches


RESOURCE_IDENTITY_KEYS = (
    "solver",
    "field_kind",
    "frontend_grid_profile_id",
    "oatof_numerical_profile_id",
    "trajectory_quality_profile_id",
    "time_integration_profile_id",
    "rf_steps_per_period",
    "accelerator_field_profile_id",
    "frontend_pa0_sha256",
    "accelerator_overlay_pa0_sha256",
    "reflectron_pa0_sha256",
)


def available_physical_memory_bytes() -> int | None:
    """Return currently available physical memory on Windows, if observable."""
    if os.name != "nt":
        return None
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong),
            ("total_physical", ctypes.c_ulonglong),
            ("available_physical", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong),
            ("available_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("available_virtual", ctypes.c_ulonglong),
            ("available_extended_virtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.available_physical)


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _nonnegative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def select_memory_profile(
    resource_identity: dict[str, Any], profiles: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return the closest completed profile, preferring the safer peak on ties."""
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for profile in profiles:
        identity = profile.get("resource_identity")
        peak = profile.get("per_batch_peak_working_set_bytes")
        if not isinstance(identity, dict) or isinstance(peak, bool) or not isinstance(peak, int) or peak < 1:
            continue
        if (
            identity.get("solver") != resource_identity.get("solver")
            or identity.get("field_kind") != resource_identity.get("field_kind")
        ):
            continue
        score = sum(
            resource_identity.get(key) is not None
            and resource_identity.get(key) == identity.get(key)
            for key in RESOURCE_IDENTITY_KEYS
        )
        ranked.append((score, peak, profile))
    if not ranked:
        return None
    score, _peak, profile = max(ranked, key=lambda item: (item[0], item[1]))
    result = dict(profile)
    result["match_score"] = score
    result["match_kind"] = (
        "exact_resource_profile" if score == len(RESOURCE_IDENTITY_KEYS) else "nearest_resource_profile"
    )
    return result


def plan_simion_dispatch(
    request: dict[str, Any],
    profiles: list[dict[str, Any]],
    *,
    available_memory_bytes: int | None = None,
    logical_processors: int | None = None,
) -> dict[str, Any]:
    """Plan safe parallel waves for an authorized, independent SIMION request.

    An RF request must state a positive ``rf_steps_per_period``; an electrostatic
    request must not.  Unknown resource identities deliberately get one pilot
    batch, after which :func:`plan_adaptive_followup` consumes its observed peak.
    """
    particles = _positive_int(request.get("particle_count"), "particle_count")
    # An omitted cap means "let measured host capacity decide", not the
    # historical accidental policy of one lane.  The separate default remains
    # one for hosts whose available memory cannot be observed.
    maximum_batches = _positive_int(
        request.get("maximum_parallel_batches", particles), "maximum_parallel_batches"
    )
    maximum_batches = min(maximum_batches, particles)
    default_batches = _positive_int(
        request.get("default_parallel_batches", 1),
        "default_parallel_batches",
    )
    if default_batches > maximum_batches:
        raise ValueError("default_parallel_batches cannot exceed maximum_parallel_batches")
    if request.get("solver") != "SIMION":
        raise ValueError("scheduler accepts only SIMION requests")
    field_kind = request.get("field_kind")
    if field_kind not in {"rf", "electrostatic"}:
        raise ValueError("field_kind must be rf or electrostatic")
    rf_steps = request.get("rf_steps_per_period")
    if field_kind == "rf" and (isinstance(rf_steps, bool) or not isinstance(rf_steps, int) or rf_steps < 1):
        raise ValueError("RF scheduling requires a positive rf_steps_per_period")
    if field_kind == "electrostatic" and rf_steps is not None:
        raise ValueError("electrostatic scheduling must not carry rf_steps_per_period")
    if maximum_batches > 1 and request.get("independent_particles") is not True:
        raise ValueError("parallel batches require independent_particles=true")
    reserve = _nonnegative_int(request.get("reserve_available_memory_bytes", 0), "reserve_available_memory_bytes")
    cpu_per_batch = _positive_int(request.get("cpu_cores_per_batch", 1), "cpu_cores_per_batch")
    cpu_reserve = _nonnegative_int(request.get("reserve_cpu_cores", 0), "reserve_cpu_cores")
    processor_count = logical_processors if logical_processors is not None else os.cpu_count()
    if processor_count is None:
        processor_count = 1
    processor_count = _positive_int(processor_count, "logical_processors")
    cpu_capacity = (processor_count - cpu_reserve) // cpu_per_batch
    if cpu_capacity < 1:
        raise ValueError("available CPU cores cannot support one SIMION batch after reserve")
    identity = {key: request.get(key) for key in RESOURCE_IDENTITY_KEYS}
    profile = select_memory_profile(identity, profiles)
    available = available_physical_memory_bytes() if available_memory_bytes is None else available_memory_bytes
    fallback = request.get("unknown_per_batch_reservation_bytes")
    if profile is None:
        fallback = _positive_int(fallback, "unknown_per_batch_reservation_bytes")
        if available is not None:
            available = _nonnegative_int(available, "available_memory_bytes")
            if available - reserve < fallback:
                raise ValueError("available memory cannot support one unknown SIMION bootstrap batch after reserve")
        return {
            "schema_version": 1,
            "role": "simion_repository_dispatch_plan",
            "solver": "SIMION",
            "field_kind": field_kind,
            "particle_count": particles,
            "resource_identity": identity,
            "estimation": {
                "kind": "unknown_resource_profile_bootstrap",
                "bootstrap_reservation_bytes": fallback,
                "requires_observed_peak_before_followup": True,
            },
            "host": {"available_memory_bytes": available, "logical_processors": processor_count},
            "limits": {
                "maximum_parallel_batches": maximum_batches,
                "memory_reserve_bytes": reserve,
                "cpu_capacity": cpu_capacity,
                "cpu_cores_per_batch": cpu_per_batch,
                "reserve_cpu_cores": cpu_reserve,
            },
            "waves": [{
                "index": 1, "kind": "bootstrap", "batch_count": 1,
                "particle_count": particles,
                "batches": plan_single_wave_batches(particles, 1)["batches"],
            }],
        }
    peak = _positive_int(profile["per_batch_peak_working_set_bytes"], "profile peak")
    safety_numerator = _positive_int(request.get("memory_safety_numerator", 115), "memory_safety_numerator")
    safety_denominator = _positive_int(request.get("memory_safety_denominator", 100), "memory_safety_denominator")
    reserved_peak = (peak * safety_numerator + safety_denominator - 1) // safety_denominator
    if available is None:
        memory_capacity = default_batches
        memory_reason = "host_memory_unavailable_use_authorized_cap"
    else:
        available = _nonnegative_int(available, "available_memory_bytes")
        memory_capacity = (available - reserve) // reserved_peak
        if memory_capacity < 1:
            raise ValueError("available memory cannot support one SIMION batch after reserve")
        memory_reason = "largest_count_within_current_available_memory"
    parallelism = min(maximum_batches, cpu_capacity, int(memory_capacity), particles)
    return {
        "schema_version": 1,
        "role": "simion_repository_dispatch_plan",
        "solver": "SIMION",
        "field_kind": field_kind,
        "particle_count": particles,
        "resource_identity": identity,
        "estimation": {
            "kind": profile["match_kind"], "match_score": profile["match_score"],
            "observed_peak_bytes": peak, "reserved_peak_bytes": reserved_peak,
            "memory_selection_reason": memory_reason,
        },
        "host": {"available_memory_bytes": available, "logical_processors": processor_count},
        "limits": {
            "maximum_parallel_batches": maximum_batches,
            "memory_reserve_bytes": reserve,
            "cpu_capacity": cpu_capacity,
            "cpu_cores_per_batch": cpu_per_batch,
            "reserve_cpu_cores": cpu_reserve,
        },
        "waves": [{
            "index": 1, "kind": "scheduled", "batch_count": parallelism,
            "particle_count": particles,
            "batches": plan_single_wave_batches(particles, parallelism)["batches"],
        }],
    }


def plan_adaptive_followup(plan: dict[str, Any], observed_peak_bytes: int) -> dict[str, Any]:
    """Turn an unknown-profile bootstrap result into a measured follow-up plan."""
    if plan.get("estimation", {}).get("kind") != "unknown_resource_profile_bootstrap":
        raise ValueError("adaptive followup requires an unknown-profile bootstrap plan")
    request = {
        "solver": "SIMION", "field_kind": plan["field_kind"],
        "particle_count": plan["particle_count"], "independent_particles": True,
        "maximum_parallel_batches": plan["limits"]["maximum_parallel_batches"],
        "reserve_available_memory_bytes": plan["limits"]["memory_reserve_bytes"],
        "cpu_cores_per_batch": plan["limits"]["cpu_cores_per_batch"],
        "reserve_cpu_cores": plan["limits"]["reserve_cpu_cores"],
        **plan["resource_identity"],
    }
    profile = {"resource_identity": plan["resource_identity"], "per_batch_peak_working_set_bytes": _positive_int(observed_peak_bytes, "observed_peak_bytes")}
    result = plan_simion_dispatch(request, [profile], available_memory_bytes=plan["host"]["available_memory_bytes"], logical_processors=plan["host"]["logical_processors"])
    result["estimation"]["kind"] = "observed_bootstrap_peak"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--available-memory-bytes", type=int)
    parser.add_argument("--logical-processors", type=int)
    parser.add_argument("--observed-bootstrap-peak-bytes", type=int)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8-sig"))
    profiles = json.loads(args.profiles.read_text(encoding="utf-8-sig"))
    if not isinstance(request, dict) or not isinstance(profiles, list):
        parser.error("request must be an object and profiles must be an array")
    plan = plan_simion_dispatch(
        request, profiles, available_memory_bytes=args.available_memory_bytes,
        logical_processors=args.logical_processors,
    )
    if args.observed_bootstrap_peak_bytes is not None:
        plan = plan_adaptive_followup(plan, args.observed_bootstrap_peak_bytes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(
        "SIMION_REPOSITORY_DISPATCH_PLAN=PASS "
        f"FIELD_KIND={plan['field_kind']} WAVES={len(plan['waves'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
