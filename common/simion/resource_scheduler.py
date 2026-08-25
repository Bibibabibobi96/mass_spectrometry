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


DEFAULT_RESOURCE_CALIBRATION_SECONDS = 20
RESOURCE_IDENTITY_KEYS = (
    "solver",
    "field_kind",
    "frontend_grid_profile_id",
    "oatof_numerical_profile_id",
    "trajectory_quality_profile_id",
    "time_integration_profile_id",
    # Profile IDs describe a registered default, but exploration may resolve
    # different numerics inline.  Use the resulting values for a memory
    # profile match so an old, coarser observation cannot authorize parallel
    # work for a finer override merely because its source profile ID matches.
    "frontend_cell_mm_xyz",
    "accelerator_overlay_cell_mm_xyz",
    "reflectron_cell_mm",
    "trajectory_quality",
    "rf_steps_per_period",
    "accelerator_field_profile_id",
    "frontend_pa0_sha256",
    "accelerator_overlay_pa0_sha256",
    "reflectron_pa0_sha256",
    # Case campaigns may run distinct, complete SIMION inputs rather than
    # partitions of one particle table.  This key lets them reuse an observed
    # process peak only for the same complete input; it does not itself impose
    # a concurrency limit.
    "case_input_sha256",
)
DEFAULT_MEMORY_SAFETY_NUMERATOR = 105
DEFAULT_MEMORY_SAFETY_DENOMINATOR = 100


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
        # A measured peak can be reused only when it does not contradict a
        # resource-relevant property declared by this run.  Ranking a profile
        # with a different RF step count, grid, or trajectory-quality profile
        # as merely "nearest" could understate its working-set reservation.
        if any(
            resource_identity.get(key) is not None
            and identity.get(key) != resource_identity[key]
            for key in RESOURCE_IDENTITY_KEYS
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
    safety_numerator = _positive_int(
        request.get("memory_safety_numerator", DEFAULT_MEMORY_SAFETY_NUMERATOR),
        "memory_safety_numerator",
    )
    safety_denominator = _positive_int(
        request.get("memory_safety_denominator", DEFAULT_MEMORY_SAFETY_DENOMINATOR),
        "memory_safety_denominator",
    )
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
        if available is not None:
            available = _nonnegative_int(available, "available_memory_bytes")
        if fallback is not None:
            fallback = _positive_int(fallback, "unknown_per_batch_reservation_bytes")
        if available is not None and (
            available - reserve < (fallback if fallback is not None else 1)
        ):
            reason = (
                "available memory cannot support one unknown SIMION bootstrap batch after reserve"
                if fallback is not None
                else "available memory does not satisfy the SIMION bootstrap reserve"
            )
            raise ValueError(reason)
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
                "memory_selection_reason": (
                    "explicit_bootstrap_reservation"
                    if fallback is not None
                    else "no_unverified_memory_estimate"
                ),
                "requires_observed_peak_before_followup": True,
                "resource_calibration": {
                    "kind": "time_limited_process_peak_v1",
                    "duration_seconds": DEFAULT_RESOURCE_CALIBRATION_SECONDS,
                    "terminal_action": "terminate_process_tree_then_replan",
                    "output_scope": "RESOURCE_CALIBRATION_ONLY",
                },
            },
            "host": {"available_memory_bytes": available, "logical_processors": processor_count},
            "limits": {
                "maximum_parallel_batches": maximum_batches,
                "memory_reserve_bytes": reserve,
                "cpu_capacity": cpu_capacity,
                "cpu_cores_per_batch": cpu_per_batch,
                "reserve_cpu_cores": cpu_reserve,
                "memory_safety_numerator": safety_numerator,
                "memory_safety_denominator": safety_denominator,
            },
            "waves": [{
                "index": 1, "kind": "bootstrap", "batch_count": 1,
                "particle_count": particles,
                "batches": plan_single_wave_batches(particles, 1)["batches"],
            }],
        }
    peak = _positive_int(profile["per_batch_peak_working_set_bytes"], "profile peak")
    reserved_peak = (peak * safety_numerator + safety_denominator - 1) // safety_denominator
    if available is None:
        # Without an observed current memory capacity, one batch is the only
        # non-speculative choice.  This is deliberately not a project policy
        # knob: hosts with observable memory are always planned from it.
        memory_capacity = 1
        memory_reason = "host_memory_unavailable_single_batch"
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
            "memory_safety_numerator": safety_numerator,
            "memory_safety_denominator": safety_denominator,
        },
        "waves": [{
            "index": 1, "kind": "scheduled", "batch_count": parallelism,
            "particle_count": particles,
            "batches": plan_single_wave_batches(particles, parallelism)["batches"],
        }],
    }


def plan_simion_case_dispatch(
    cases: list[dict[str, Any]],
    request: dict[str, Any],
    profiles: list[dict[str, Any]],
    *,
    available_memory_bytes: int | None = None,
    logical_processors: int | None = None,
) -> dict[str, Any]:
    """Plan one resource-safe wave of independent complete SIMION cases.

    A case is not a particle batch: its complete input can have a different
    field array and working set.  Each item therefore supplies a stable
    ``case_id`` and a resource identity.  Unknown identities are deliberately
    returned one at a time as bootstrap work.  Once callers add their observed
    peaks to ``profiles``, the planner packs only known cases into a wave using
    the same CPU, reserve and safety policy as particle dispatch.
    """
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a non-empty array")
    case_ids: set[str] = set()
    normalized: list[tuple[str, dict[str, Any]]] = []
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str):
            raise ValueError("each case requires a string case_id")
        case_id = case["case_id"]
        if not case_id or case_id in case_ids:
            raise ValueError("case IDs must be non-empty and unique")
        identity = case.get("resource_identity")
        if not isinstance(identity, dict):
            raise ValueError("each case requires a resource_identity object")
        case_ids.add(case_id)
        normalized.append((case_id, identity))

    # Delegate all policy validation and individual resource estimates to the
    # particle planner.  Giving it one synthetic independent particle is only
    # an internal unit of capacity; no particle IDs or physics are produced by
    # this case-level API.
    individual_plans: list[tuple[str, dict[str, Any]]] = []
    for case_id, identity in normalized:
        individual_request = {
            **request,
            **identity,
            "particle_count": 1,
            "independent_particles": True,
            "maximum_parallel_batches": 1,
        }
        individual_plans.append((case_id, plan_simion_dispatch(
            individual_request, profiles,
            available_memory_bytes=available_memory_bytes,
            logical_processors=logical_processors,
        )))

    first_plan = individual_plans[0][1]
    case_limits = dict(first_plan["limits"])
    # The one-batch value above was solely used to ask the particle planner
    # whether an individual case fits.  A case wave intentionally has no
    # historical fixed cap; its actual cap is current CPU and memory capacity.
    case_limits.pop("maximum_parallel_batches")
    case_limits["maximum_parallel_cases"] = len(normalized)
    unknown = [
        (case_id, plan) for case_id, plan in individual_plans
        if plan["estimation"]["kind"] == "unknown_resource_profile_bootstrap"
    ]
    if unknown:
        case_id, bootstrap = unknown[0]
        return {
            "schema_version": 1,
            "role": "simion_repository_case_dispatch_plan",
            "solver": "SIMION",
            "field_kind": request.get("field_kind"),
            "case_count": len(normalized),
            "estimation": {
                "kind": "unknown_resource_profile_bootstrap",
                "requires_observed_peak_before_followup": True,
                "unknown_case_id": case_id,
            },
            "host": bootstrap["host"],
            "limits": case_limits,
            "waves": [{
                "index": 1,
                "kind": "bootstrap",
                "case_count": 1,
                "cases": [{"case_id": case_id}],
            }],
        }

    limits = first_plan["limits"]
    host = first_plan["host"]
    available = host["available_memory_bytes"]
    selected: list[dict[str, str]] = []
    reserved_memory = limits["memory_reserve_bytes"]
    used_cpu = limits["reserve_cpu_cores"]
    for case_id, plan in individual_plans:
        peak = plan["estimation"]["reserved_peak_bytes"]
        next_cpu = used_cpu + limits["cpu_cores_per_batch"]
        next_memory = reserved_memory + sum(
            item["reserved_peak_bytes"] for item in selected
        ) + peak
        if next_cpu > host["logical_processors"]:
            continue
        if available is None:
            if selected:
                continue
        elif next_memory > available:
            continue
        selected.append({"case_id": case_id, "reserved_peak_bytes": peak})
        used_cpu = next_cpu
    if not selected:
        # Every individual plan already established that one known case fits;
        # reaching this branch would indicate an internal accounting error.
        raise ValueError("resource policy cannot schedule one known SIMION case")
    return {
        "schema_version": 1,
        "role": "simion_repository_case_dispatch_plan",
        "solver": "SIMION",
        "field_kind": request.get("field_kind"),
        "case_count": len(normalized),
        "estimation": {
            "kind": "observed_case_profiles",
            "memory_selection_reason": (
                "host_memory_unavailable_single_case"
                if available is None else "largest_case_wave_within_current_available_memory"
            ),
        },
        "host": host,
        "limits": case_limits,
        "waves": [{
            "index": 1,
            "kind": "scheduled",
            "case_count": len(selected),
            "cases": selected,
        }],
    }


def plan_adaptive_followup(plan: dict[str, Any], observed_peak_bytes: int) -> dict[str, Any]:
    """Turn an unknown-profile bootstrap result into a measured follow-up plan."""
    if plan.get("estimation", {}).get("kind") != "unknown_resource_profile_bootstrap":
        raise ValueError("adaptive followup requires an unknown-profile bootstrap plan")
    request = _request_from_dispatch_plan(plan)
    profile = {"resource_identity": plan["resource_identity"], "per_batch_peak_working_set_bytes": _positive_int(observed_peak_bytes, "observed_peak_bytes")}
    result = plan_simion_dispatch(request, [profile], available_memory_bytes=plan["host"]["available_memory_bytes"], logical_processors=plan["host"]["logical_processors"])
    result["estimation"]["kind"] = "observed_bootstrap_peak"
    return result


def _request_from_dispatch_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Project a prepared dispatch plan into the scheduler's policy request."""
    if plan.get("role") != "simion_repository_dispatch_plan":
        raise ValueError("prepared dispatch plan has an unsupported role")
    identity = plan.get("resource_identity")
    limits = plan.get("limits")
    if not isinstance(identity, dict) or not isinstance(limits, dict):
        raise ValueError("prepared dispatch plan lacks resource identity or limits")
    return {
        "solver": "SIMION", "field_kind": plan.get("field_kind"),
        "particle_count": plan.get("particle_count"), "independent_particles": True,
        "maximum_parallel_batches": limits.get("maximum_parallel_batches"),
        "reserve_available_memory_bytes": limits.get("memory_reserve_bytes"),
        "cpu_cores_per_batch": limits.get("cpu_cores_per_batch"),
        "reserve_cpu_cores": limits.get("reserve_cpu_cores"),
        "memory_safety_numerator": limits.get("memory_safety_numerator"),
        "memory_safety_denominator": limits.get("memory_safety_denominator"),
        **identity,
    }


def plan_runtime_dispatch(
    prepared_plan: dict[str, Any], *, available_memory_bytes: int | None = None,
    logical_processors: int | None = None,
) -> dict[str, Any]:
    """Re-plan a prepared independent-particle workload on the current host.

    The prepared plan remains the authority for physics-adjacent resource identity,
    caps and safety policy. Only observed host capacity is renewed at execution.
    """
    request = _request_from_dispatch_plan(prepared_plan)
    estimation = prepared_plan.get("estimation")
    if not isinstance(estimation, dict):
        raise ValueError("prepared dispatch plan lacks estimation")
    profiles: list[dict[str, Any]] = []
    observed_peak = estimation.get("observed_peak_bytes")
    if observed_peak is not None:
        profiles.append({
            "resource_identity": prepared_plan["resource_identity"],
            "per_batch_peak_working_set_bytes": _positive_int(
                observed_peak, "prepared observed_peak_bytes"
            ),
        })
    return plan_simion_dispatch(
        request, profiles, available_memory_bytes=available_memory_bytes,
        logical_processors=logical_processors,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--request", type=Path)
    source.add_argument("--prepared-plan", type=Path)
    parser.add_argument("--profiles", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--available-memory-bytes", type=int)
    parser.add_argument("--logical-processors", type=int)
    parser.add_argument("--observed-bootstrap-peak-bytes", type=int)
    args = parser.parse_args()
    if args.prepared_plan is not None:
        if args.profiles is not None:
            parser.error("prepared-plan cannot be combined with profiles")
        prepared_plan = json.loads(args.prepared_plan.read_text(encoding="utf-8-sig"))
        if not isinstance(prepared_plan, dict):
            parser.error("prepared-plan must be an object")
        plan = plan_runtime_dispatch(
            prepared_plan, available_memory_bytes=args.available_memory_bytes,
            logical_processors=args.logical_processors,
        )
    else:
        request = json.loads(args.request.read_text(encoding="utf-8-sig"))
        profiles = [] if args.profiles is None else json.loads(args.profiles.read_text(encoding="utf-8-sig"))
        if not isinstance(request, dict) or not isinstance(profiles, list):
            parser.error("request must be an object and profiles must be an array when supplied")
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
