"""Repository-owned resource planning for independent SIMION particle batches.

Particle count controls run time, not the assumed instantaneous footprint of a
SIMION process. Resource-safe concurrency therefore controls only the number
of *simultaneously active* processes. For one numerical identity, independent
particle work is divided evenly across those concurrent lanes; no arbitrary
per-process particle ceiling is imposed. With no exact resource profile, the
first batch is formal work: it keeps running during a 30-second observation
and its result is retained.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

FORMAL_OBSERVATION_SECONDS = 30
INITIAL_CPU_LANES = 10
MINIMUM_PROCESS_CPU_PERCENT = 10.0
CPU_ADMISSION_PERCENT = 95.0
# These are repository-wide Windows safety reserves, deliberately expressed in
# binary bytes rather than as fractions of installed RAM.  A percentage made the same
# safe free-memory level vary with host capacity and caused an unnecessarily
# large reservation on the 48 GiB research workstation.
MEMORY_ADMISSION_RESERVE_BYTES = 2 * 1024**3
MEMORY_CRITICAL_RESERVE_BYTES = 1 * 1024**3
MEMORY_CRITICAL_SECONDS = 15
LAUNCH_STAGGER_SECONDS = 5
KNOWN_MEMORY_SAFETY_FACTOR = 1.10
# A formal batch observes the actual solver identity for 30 seconds and keeps
# running afterwards.  Its peak therefore receives the same 10% headroom as
# an exact historical profile; admission continues to be guarded by the 2 GiB
# system reserve and live peak checks in the executor.
OBSERVED_MEMORY_SAFETY_FACTOR = 1.10
RESOURCE_IDENTITY_KEYS = (
    "solver", "field_kind", "frontend_grid_profile_id",
    "oatof_numerical_profile_id", "trajectory_quality_profile_id",
    "time_integration_profile_id", "frontend_cell_mm_xyz",
    "accelerator_overlay_cell_mm_xyz", "reflectron_cell_mm",
    "trajectory_quality", "rf_steps_per_period", "accelerator_field_profile_id",
    "frontend_pa0_sha256", "accelerator_overlay_pa0_sha256",
    "reflectron_pa0_sha256", "case_input_sha256",
)

RETIRED_PROJECT_RESOURCE_KEYS = frozenset({
    "maximum_parallel_batches", "unknown_per_batch_reservation_bytes",
    "reserve_available_memory_bytes", "cpu_cores_per_batch",
    "reserve_cpu_cores", "memory_safety_numerator", "memory_safety_denominator",
    "maximum_process_tree_working_set_bytes",
})


def physical_memory_bytes() -> tuple[int, int] | None:
    """Return ``(available, total)`` physical memory on Windows."""
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
    return int(status.available_physical), int(status.total_physical)


def available_physical_memory_bytes() -> int | None:
    observed = physical_memory_bytes()
    return None if observed is None else observed[0]


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _nonnegative_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{name} must be a non-negative number")
    return float(value)


def _validate_request(request: dict[str, Any]) -> tuple[int, str]:
    retired = sorted(RETIRED_PROJECT_RESOURCE_KEYS.intersection(request))
    if retired:
        raise ValueError(
            "project request contains retired repository resource controls: "
            + ", ".join(retired)
        )
    particles = _positive_int(request.get("particle_count"), "particle_count")
    if request.get("solver") != "SIMION":
        raise ValueError("scheduler accepts only SIMION requests")
    field_kind = request.get("field_kind")
    if field_kind not in {"rf", "electrostatic"}:
        raise ValueError("field_kind must be rf or electrostatic")
    rf_steps = request.get("rf_steps_per_period")
    if field_kind == "rf" and (
        isinstance(rf_steps, bool) or not isinstance(rf_steps, int) or rf_steps < 1
    ):
        raise ValueError("RF scheduling requires a positive rf_steps_per_period")
    if field_kind == "electrostatic" and rf_steps is not None:
        raise ValueError("electrostatic scheduling must not carry rf_steps_per_period")
    if particles > 1 and request.get("independent_particles") is not True:
        raise ValueError("parallel-capable particle work requires independent_particles=true")
    return particles, field_kind


def select_memory_profile(
    resource_identity: dict[str, Any], profiles: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return the safest profile with the exact complete numerical identity."""
    expected = {key: resource_identity.get(key) for key in RESOURCE_IDENTITY_KEYS}
    matches = []
    for profile in profiles:
        identity = profile.get("resource_identity")
        peak = profile.get("per_batch_peak_working_set_bytes")
        if not isinstance(identity, dict) or isinstance(peak, bool) or not isinstance(peak, int) or peak < 1:
            continue
        actual = {key: identity.get(key) for key in RESOURCE_IDENTITY_KEYS}
        if actual == expected:
            matches.append(profile)
    if not matches:
        return None
    result = dict(max(matches, key=lambda item: item["per_batch_peak_working_set_bytes"]))
    result["match_kind"] = "exact_resource_profile"
    return result


def _capacity(
    *, particle_count: int, available_memory_bytes: int | None,
    total_physical_memory_bytes: int | None, per_process_memory_bytes: int,
    process_cpu_percent: float, background_cpu_percent: float,
) -> tuple[int, int, int]:
    cpu_cost = max(MINIMUM_PROCESS_CPU_PERCENT, process_cpu_percent)
    cpu_capacity = max(1, math.floor(
        max(0.0, CPU_ADMISSION_PERCENT - background_cpu_percent) / cpu_cost
    ))
    if available_memory_bytes is None or total_physical_memory_bytes is None:
        memory_capacity = 1
    else:
        memory_capacity = max(
            1,
            (available_memory_bytes - MEMORY_ADMISSION_RESERVE_BYTES)
            // per_process_memory_bytes,
        )
    return min(particle_count, cpu_capacity, memory_capacity), cpu_capacity, memory_capacity


def _public_limits(maximum_concurrency: int, cpu_capacity: int, memory_capacity: int) -> dict[str, Any]:
    return {
        "maximum_concurrency": maximum_concurrency,
        "cpu_capacity": cpu_capacity,
        "memory_capacity": memory_capacity,
        "formal_observation_seconds": FORMAL_OBSERVATION_SECONDS,
        "minimum_process_cpu_percent": MINIMUM_PROCESS_CPU_PERCENT,
        "cpu_admission_percent": CPU_ADMISSION_PERCENT,
        "memory_admission_reserve_bytes": MEMORY_ADMISSION_RESERVE_BYTES,
        "memory_critical_reserve_bytes": MEMORY_CRITICAL_RESERVE_BYTES,
        "memory_critical_seconds": MEMORY_CRITICAL_SECONDS,
        "launch_stagger_seconds": LAUNCH_STAGGER_SECONDS,
    }


def _initial_formal_batch(particles: int) -> dict[str, int]:
    count = math.ceil(particles / min(particles, INITIAL_CPU_LANES))
    return {
        "index": 1, "count": count, "particle_id_min": 1,
        "particle_id_max": count, "simion_particle_id_offset": 0,
    }


def _balanced_lane_loads(total: int, lane_count: int) -> list[int]:
    """Split positive independent-particle work as evenly as possible."""
    if total < 0 or lane_count < 1:
        raise ValueError("balanced lane inputs are invalid")
    quotient, remainder = divmod(total, lane_count)
    return [quotient + (1 if index < remainder else 0) for index in range(lane_count)]


def _batches_from_counts(counts: list[int], first_count: int = 0) -> list[dict[str, int]]:
    """Publish contiguous canonical particle-ID ranges for scheduled counts."""
    batches: list[dict[str, int]] = []
    next_particle_id = first_count + 1
    for index, count in enumerate(counts, start=1):
        batches.append({
            "index": index,
            "count": count,
            "particle_id_min": next_particle_id,
            "particle_id_max": next_particle_id + count - 1,
            "simion_particle_id_offset": next_particle_id - 1,
        })
        next_particle_id += count
    return batches


def _batches_after_formal_first(
    particles: int, first: dict[str, int], concurrency: int, first_completed: bool
) -> list[dict[str, int]]:
    """Balance remaining work while retaining the first formal result."""
    first_count = first["count"]
    remaining = particles - first_count
    if remaining <= 0:
        return [dict(first)]
    if first_completed:
        tail_counts = _balanced_lane_loads(remaining, concurrency)
    elif concurrency == 1:
        tail_counts = [remaining]
    else:
        target_lane_load = max(first_count, math.ceil(particles / concurrency))
        first_lane_remainder = target_lane_load - first_count
        other_lane_counts = _balanced_lane_loads(
            remaining - first_lane_remainder, concurrency - 1
        )
        # Start each previously idle lane first.  The retained observation
        # batch receives its one balancing remainder only after it finishes.
        tail_counts = other_lane_counts + ([first_lane_remainder] if first_lane_remainder else [])
    batches = [dict(first)]
    for batch in _batches_from_counts(tail_counts, first_count):
        batch["index"] += 1
        batches.append(batch)
    return batches


def plan_simion_dispatch(
    request: dict[str, Any], profiles: list[dict[str, Any]], *,
    available_memory_bytes: int | None = None,
    total_physical_memory_bytes: int | None = None,
    logical_processors: int | None = None,
    background_cpu_percent: float = 0.0,
) -> dict[str, Any]:
    """Create an initial repository dispatch plan."""
    particles, field_kind = _validate_request(request)
    if available_memory_bytes is None or total_physical_memory_bytes is None:
        observed = physical_memory_bytes()
        if observed is not None:
            available_memory_bytes = observed[0] if available_memory_bytes is None else available_memory_bytes
            total_physical_memory_bytes = observed[1] if total_physical_memory_bytes is None else total_physical_memory_bytes
    identity = {key: request.get(key) for key in RESOURCE_IDENTITY_KEYS}
    profile = select_memory_profile(identity, profiles)
    host = {
        "available_memory_bytes": available_memory_bytes,
        "total_physical_memory_bytes": total_physical_memory_bytes,
        "logical_processors": logical_processors or os.cpu_count() or 1,
    }
    if profile is None:
        first = _initial_formal_batch(particles)
        return {
            "schema_version": 2, "role": "simion_repository_dispatch_plan",
            "solver": "SIMION", "field_kind": field_kind,
            "particle_count": particles, "resource_identity": identity,
            "estimation": {
                "kind": "formal_first_batch_observation",
                "requires_observation_before_remaining_launches": particles > first["count"],
                "observation_seconds": FORMAL_OBSERVATION_SECONDS,
                "first_batch_result_retained": True,
                "terminal_action": "continue_process_and_replan_remaining_particles",
            },
            "host": host, "limits": _public_limits(1, 1, 1),
            "waves": [{
                "index": 1, "kind": "formal_observation", "batch_count": 1,
                "particle_count": particles, "coverage": "initial_formal_batch_only",
                "batches": [first],
            }],
        }
    peak = _positive_int(profile["per_batch_peak_working_set_bytes"], "profile peak")
    memory_budget = math.ceil(peak * KNOWN_MEMORY_SAFETY_FACTOR)
    process_cpu = _nonnegative_number(profile.get("per_batch_cpu_percent", 0.0), "profile CPU")
    concurrency, cpu_capacity, memory_capacity = _capacity(
        particle_count=particles, available_memory_bytes=available_memory_bytes,
        total_physical_memory_bytes=total_physical_memory_bytes,
        per_process_memory_bytes=memory_budget, process_cpu_percent=process_cpu,
        background_cpu_percent=_nonnegative_number(background_cpu_percent, "background CPU"),
    )
    batches = _batches_from_counts(_balanced_lane_loads(particles, concurrency))
    return {
        "schema_version": 2, "role": "simion_repository_dispatch_plan",
        "solver": "SIMION", "field_kind": field_kind, "particle_count": particles,
        "resource_identity": identity,
        "estimation": {
            "kind": "exact_resource_profile", "observed_peak_bytes": peak,
            "per_process_memory_budget_bytes": memory_budget,
            "per_process_cpu_percent": max(MINIMUM_PROCESS_CPU_PERCENT, process_cpu),
            "memory_safety_factor": KNOWN_MEMORY_SAFETY_FACTOR,
            "observation_wait_skipped": True,
        },
        "host": host, "limits": _public_limits(concurrency, cpu_capacity, memory_capacity),
        "waves": [{
            "index": 1, "kind": "scheduled", "batch_count": len(batches),
            "particle_count": particles, "coverage": "complete_population",
            "batches": batches,
        }],
    }


def plan_adaptive_followup(
    plan: dict[str, Any], observed_peak_bytes: int, *,
    observed_cpu_percent: float = 0.0, background_cpu_percent: float = 0.0,
    available_memory_bytes: int | None = None,
    total_physical_memory_bytes: int | None = None,
    first_batch_completed: bool = False,
) -> dict[str, Any]:
    """Finalize batching while retaining the already-started formal batch."""
    if plan.get("estimation", {}).get("kind") != "formal_first_batch_observation":
        raise ValueError("adaptive followup requires a formal-first-batch plan")
    peak = _positive_int(observed_peak_bytes, "observed_peak_bytes")
    cpu = _nonnegative_number(observed_cpu_percent, "observed_cpu_percent")
    background = _nonnegative_number(background_cpu_percent, "background_cpu_percent")
    available_memory_bytes = (
        plan.get("host", {}).get("available_memory_bytes")
        if available_memory_bytes is None else available_memory_bytes
    )
    total_physical_memory_bytes = (
        plan.get("host", {}).get("total_physical_memory_bytes")
        if total_physical_memory_bytes is None else total_physical_memory_bytes
    )
    memory_budget = math.ceil(peak * OBSERVED_MEMORY_SAFETY_FACTOR)
    particles = _positive_int(plan.get("particle_count"), "particle_count")
    concurrency, cpu_capacity, memory_capacity = _capacity(
        particle_count=particles, available_memory_bytes=available_memory_bytes,
        total_physical_memory_bytes=total_physical_memory_bytes,
        per_process_memory_bytes=memory_budget, process_cpu_percent=cpu,
        background_cpu_percent=background,
    )
    if not first_batch_completed:
        # ``available_memory_bytes`` and background CPU are sampled while the
        # retained first formal batch is already running.  _capacity therefore
        # describes *additional* safe launches, not total concurrency.  Count
        # that existing formal process exactly once instead of wasting a lane.
        concurrency = min(particles, concurrency + 1)
        cpu_capacity += 1
        memory_capacity += 1
    first = dict(plan["waves"][0]["batches"][0])
    batches = _batches_after_formal_first(particles, first, concurrency, first_batch_completed)
    result = json.loads(json.dumps(plan))
    result["estimation"] = {
        "kind": "observed_formal_batch", "observed_peak_bytes": peak,
        "per_process_memory_budget_bytes": memory_budget,
        "per_process_cpu_percent": max(MINIMUM_PROCESS_CPU_PERCENT, cpu),
        "background_cpu_percent": background,
        "memory_safety_factor": OBSERVED_MEMORY_SAFETY_FACTOR,
        "first_batch_completed_during_observation": bool(first_batch_completed),
        "retained_first_batch_counts_toward_concurrency": not first_batch_completed,
        "first_batch_result_retained": True,
    }
    result["host"]["available_memory_bytes"] = available_memory_bytes
    result["host"]["total_physical_memory_bytes"] = total_physical_memory_bytes
    result["limits"] = _public_limits(concurrency, cpu_capacity, memory_capacity)
    result["waves"] = [{
        "index": 1, "kind": "scheduled", "batch_count": len(batches),
        "particle_count": particles, "coverage": "complete_population",
        "batches": batches,
    }]
    return result


def _request_from_dispatch_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if plan.get("role") != "simion_repository_dispatch_plan":
        raise ValueError("prepared dispatch plan has an unsupported role")
    return {
        "solver": "SIMION", "field_kind": plan.get("field_kind"),
        "particle_count": plan.get("particle_count"), "independent_particles": True,
        **dict(plan.get("resource_identity", {})),
    }


def plan_runtime_dispatch(
    prepared_plan: dict[str, Any], *, available_memory_bytes: int | None = None,
    total_physical_memory_bytes: int | None = None,
    logical_processors: int | None = None,
) -> dict[str, Any]:
    estimation = prepared_plan.get("estimation", {})
    profiles: list[dict[str, Any]] = []
    if estimation.get("kind") == "exact_resource_profile":
        profiles.append({
            "resource_identity": prepared_plan["resource_identity"],
            "per_batch_peak_working_set_bytes": estimation["observed_peak_bytes"],
            "per_batch_cpu_percent": estimation.get("per_process_cpu_percent", 0.0),
        })
    return plan_simion_dispatch(
        _request_from_dispatch_plan(prepared_plan), profiles,
        available_memory_bytes=available_memory_bytes,
        total_physical_memory_bytes=total_physical_memory_bytes,
        logical_processors=logical_processors,
    )


def plan_simion_case_dispatch(
    cases: list[dict[str, Any]], request: dict[str, Any], profiles: list[dict[str, Any]],
    *, available_memory_bytes: int | None = None,
    total_physical_memory_bytes: int | None = None,
    logical_processors: int | None = None,
) -> dict[str, Any]:
    """Conservatively schedule complete cases; particle batching is preferred."""
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a non-empty array")
    seen: set[str] = set()
    plans: list[tuple[str, dict[str, Any]]] = []
    for case in cases:
        case_id, identity = case.get("case_id"), case.get("resource_identity")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError("case IDs must be non-empty and unique")
        if not isinstance(identity, dict):
            raise ValueError("each case requires a resource_identity object")
        seen.add(case_id)
        plans.append((case_id, plan_simion_dispatch(
            {**request, **identity, "particle_count": 1, "independent_particles": True},
            profiles, available_memory_bytes=available_memory_bytes,
            total_physical_memory_bytes=total_physical_memory_bytes,
            logical_processors=logical_processors,
        )))
    unknown = [
        (case_id, plan) for case_id, plan in plans
        if plan["estimation"]["kind"] == "formal_first_batch_observation"
    ]
    if unknown:
        selected = [{"case_id": unknown[0][0]}]
        limits = plans[0][1]["limits"]
        estimation = "formal_first_case_observation"
        kind = "formal_observation"
    else:
        host = plans[0][1]["host"]
        available = host["available_memory_bytes"]
        memory_left = None if available is None else (
            available - MEMORY_ADMISSION_RESERVE_BYTES
        )
        cpu_left = CPU_ADMISSION_PERCENT
        selected = []
        for case_id, plan in plans:
            memory = int(plan["estimation"]["per_process_memory_budget_bytes"])
            cpu = float(plan["estimation"]["per_process_cpu_percent"])
            if memory_left is not None and memory > memory_left:
                continue
            if cpu > cpu_left:
                continue
            selected.append({
                "case_id": case_id,
                "per_process_memory_budget_bytes": memory,
                "per_process_cpu_percent": cpu,
            })
            if memory_left is not None:
                memory_left -= memory
            cpu_left -= cpu
        if not selected:
            selected = [{
                "case_id": plans[0][0],
                "per_process_memory_budget_bytes": plans[0][1]["estimation"][
                    "per_process_memory_budget_bytes"
                ],
                "per_process_cpu_percent": plans[0][1]["estimation"][
                    "per_process_cpu_percent"
                ],
            }]
        limits = _public_limits(len(selected), len(selected), len(selected))
        estimation = "exact_resource_profiles"
        kind = "scheduled"
    return {
        "schema_version": 2, "role": "simion_repository_case_dispatch_plan",
        "solver": "SIMION", "field_kind": request.get("field_kind"),
        "case_count": len(cases),
        "estimation": {"kind": estimation},
        "host": plans[0][1]["host"], "limits": limits,
        "waves": [{
            "index": 1, "kind": kind,
            "case_count": len(selected), "cases": selected,
        }],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--request", type=Path)
    source.add_argument("--prepared-plan", type=Path)
    parser.add_argument("--profiles", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--available-memory-bytes", type=int)
    parser.add_argument("--total-physical-memory-bytes", type=int)
    parser.add_argument("--logical-processors", type=int)
    parser.add_argument("--observed-formal-peak-bytes", type=int)
    parser.add_argument("--observed-formal-cpu-percent", type=float, default=0.0)
    parser.add_argument("--observed-background-cpu-percent", type=float, default=0.0)
    parser.add_argument("--first-batch-completed", action="store_true")
    args = parser.parse_args()
    if args.prepared_plan:
        prepared = json.loads(args.prepared_plan.read_text(encoding="utf-8-sig"))
        plan = plan_runtime_dispatch(
            prepared, available_memory_bytes=args.available_memory_bytes,
            total_physical_memory_bytes=args.total_physical_memory_bytes,
            logical_processors=args.logical_processors,
        )
    else:
        request = json.loads(args.request.read_text(encoding="utf-8-sig"))
        profiles = [] if args.profiles is None else json.loads(args.profiles.read_text(encoding="utf-8-sig"))
        plan = plan_simion_dispatch(
            request, profiles, available_memory_bytes=args.available_memory_bytes,
            total_physical_memory_bytes=args.total_physical_memory_bytes,
            logical_processors=args.logical_processors,
        )
    if args.observed_formal_peak_bytes is not None:
        plan = plan_adaptive_followup(
            plan, args.observed_formal_peak_bytes,
            observed_cpu_percent=args.observed_formal_cpu_percent,
            background_cpu_percent=args.observed_background_cpu_percent,
            available_memory_bytes=args.available_memory_bytes,
            total_physical_memory_bytes=args.total_physical_memory_bytes,
            first_batch_completed=args.first_batch_completed,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(f"SIMION_REPOSITORY_DISPATCH_PLAN=PASS FIELD_KIND={plan['field_kind']} WAVES={len(plan['waves'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
