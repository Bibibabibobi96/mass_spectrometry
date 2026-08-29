"""Repository-owned resource planning for independent SIMION work.

Particle count controls run time, not the assumed instantaneous footprint of a
SIMION process. Resource-safe concurrency therefore controls only the number
of *simultaneously active* processes. For one numerical identity, independent
particle work is divided evenly across those concurrent lanes; no arbitrary
per-process particle ceiling is imposed.  The same public mechanism also
schedules a fixed set of independent SIMION jobs (for example, PA basis
refinements) without inventing project-local CPU or memory controls. With no
exact resource profile, the first work item is formal work: it has a minimum
45-second observation, completes its whole lifecycle, and its result is
retained before sibling work is admitted.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

FORMAL_OBSERVATION_SECONDS = 45
INITIAL_CPU_LANES = 10
MINIMUM_PROCESS_CPU_PERCENT = 10.0
CPU_ADMISSION_PERCENT = 95.0
# These are repository-wide Windows safety reserves, deliberately expressed in
# binary bytes rather than as fractions of installed RAM.  A percentage made the same
# safe free-memory level vary with host capacity and caused an unnecessarily
# large reservation on the 48 GiB research workstation.
MEMORY_ADMISSION_RESERVE_BYTES = 1 * 1024**3
MEMORY_CRITICAL_RESERVE_BYTES = 512 * 1024**2
MEMORY_CRITICAL_SECONDS = 15
LAUNCH_STAGGER_SECONDS = 5
# After a memory-danger recovery, the scheduler must observe a full mature
# window before restoring one lane.  This prevents a delayed SIMION working-set
# expansion from turning a brief initial underestimate into repeated churn.
MEMORY_RECOVERY_STABLE_SECONDS = 45
MAXIMUM_MEMORY_RECOVERY_ATTEMPTS = 2
# A danger response is deliberately gradual: remove the newest worker, observe
# again, and permit at most one further newest-worker removal.  If memory still
# remains critically low after those two measured attempts, the executor must
# fail closed rather than repeatedly churn workers until Windows becomes
# unresponsive.
MAXIMUM_MEMORY_DANGER_TERMINATION_ATTEMPTS = 2
KNOWN_MEMORY_SAFETY_FACTOR = 1.10
# A formal batch has a minimum 45-second observation and then runs to natural
# completion before siblings can be admitted.  Its full-lifecycle peak receives
# the same 10% headroom as an exact historical profile; admission continues to
# be guarded by the 1 GiB system reserve and live peak checks in the executor.
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


def _validate_request(request: dict[str, Any]) -> tuple[int, str, str]:
    retired = sorted(RETIRED_PROJECT_RESOURCE_KEYS.intersection(request))
    if retired:
        raise ValueError(
            "project request contains retired repository resource controls: "
            + ", ".join(retired)
        )
    has_particles = "particle_count" in request
    has_work_items = "work_item_count" in request
    if has_particles == has_work_items:
        raise ValueError(
            "scheduler request requires exactly one of particle_count or work_item_count"
        )
    unit = "particles" if has_particles else "independent_work_items"
    count_name = "particle_count" if has_particles else "work_item_count"
    count = _positive_int(request.get(count_name), count_name)
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
    independence_key = (
        "independent_particles" if unit == "particles" else "independent_work_items"
    )
    if count > 1 and request.get(independence_key) is not True:
        raise ValueError(
            f"parallel-capable {unit} require {independence_key}=true"
        )
    return count, field_kind, unit


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
        "memory_recovery_stable_seconds": MEMORY_RECOVERY_STABLE_SECONDS,
        "maximum_memory_recovery_attempts": MAXIMUM_MEMORY_RECOVERY_ATTEMPTS,
        "maximum_memory_danger_termination_attempts": (
            MAXIMUM_MEMORY_DANGER_TERMINATION_ATTEMPTS
        ),
        "launch_stagger_seconds": LAUNCH_STAGGER_SECONDS,
    }


def _format_gib(byte_count: Any) -> str:
    """Format an optional byte count for a concise scheduler event."""
    if not isinstance(byte_count, int):
        return "UNKNOWN"
    return f"{byte_count / 1024**3:.2f}GiB"


def format_dispatch_decision_event(plan: dict[str, Any]) -> str:
    """Return one human-readable event describing a frozen dispatch decision.

    This reports planned capacity, never a live process count.  The executor
    owns live process lifecycle events because it is the only layer that can
    observe them truthfully.
    """
    estimation = plan.get("estimation", {})
    limits = plan.get("limits", {})
    host = plan.get("host", {})
    wave = plan.get("waves", [{}])[0]
    kind = str(estimation.get("kind", "unknown"))
    measurement = {
        "formal_first_batch_observation": "FIRST_FORMAL_BATCH",
        "observed_formal_batch": "OBSERVED_FORMAL_BATCH",
        "exact_resource_profile": "EXACT_HISTORICAL_PROFILE",
    }.get(kind, kind.upper())
    unit = plan.get("dispatch_unit", "particles")
    count_key = "particle_count" if unit == "particles" else "work_item_count"
    count_label = "PARTICLES" if unit == "particles" else "WORK_ITEMS"
    fields = [
        "SIMION_RESOURCE_EVENT=DISPATCH_DECISION",
        f"MEASUREMENT={measurement}",
        f"{count_label}={plan.get(count_key, 'UNKNOWN')}",
        f"BATCHES={wave.get('batch_count', 'UNKNOWN')}",
        f"MAX_CONCURRENCY={limits.get('maximum_concurrency', 'UNKNOWN')}",
        f"CPU_CAPACITY={limits.get('cpu_capacity', 'UNKNOWN')}",
        f"MEMORY_CAPACITY={limits.get('memory_capacity', 'UNKNOWN')}",
        f"AVAILABLE_MEMORY={_format_gib(host.get('available_memory_bytes'))}",
        f"MEMORY_RESERVE={_format_gib(limits.get('memory_admission_reserve_bytes'))}",
    ]
    if kind == "formal_first_batch_observation":
        fields.append(f"OBSERVATION_SECONDS={estimation.get('observation_seconds', 'UNKNOWN')}")
    else:
        fields.extend((
            f"PEAK_MEMORY={_format_gib(estimation.get('observed_peak_bytes'))}",
            f"PROCESS_MEMORY_BUDGET={_format_gib(estimation.get('per_process_memory_budget_bytes'))}",
            f"PROCESS_CPU_PERCENT={estimation.get('per_process_cpu_percent', 'UNKNOWN')}",
        ))
    return " ".join(fields)


def _initial_formal_batch(work_count: int, unit: str) -> dict[str, int]:
    # A particle observation is an even one-tenth prefix.  A fixed job cannot
    # be split without changing the job's numerical identity, so observe one.
    count = 1 if unit == "independent_work_items" else math.ceil(
        work_count / min(work_count, INITIAL_CPU_LANES)
    )
    range_prefix = "particle" if unit == "particles" else "work_item"
    return {
        "index": 1, "count": count, f"{range_prefix}_id_min": 1,
        f"{range_prefix}_id_max": count,
        **({"simion_particle_id_offset": 0} if unit == "particles" else {}),
    }


def _balanced_lane_loads(total: int, lane_count: int) -> list[int]:
    """Split positive independent-particle work as evenly as possible."""
    if total < 0 or lane_count < 1:
        raise ValueError("balanced lane inputs are invalid")
    quotient, remainder = divmod(total, lane_count)
    return [quotient + (1 if index < remainder else 0) for index in range(lane_count)]


def _batches_from_counts(
    counts: list[int], first_count: int = 0, unit: str = "particles"
) -> list[dict[str, int]]:
    """Publish contiguous canonical particle or work-item ranges."""
    batches: list[dict[str, int]] = []
    next_particle_id = first_count + 1
    range_prefix = "particle" if unit == "particles" else "work_item"
    for index, count in enumerate(counts, start=1):
        batches.append({
            "index": index,
            "count": count,
            f"{range_prefix}_id_min": next_particle_id,
            f"{range_prefix}_id_max": next_particle_id + count - 1,
            **({"simion_particle_id_offset": next_particle_id - 1}
               if unit == "particles" else {}),
        })
        next_particle_id += count
    return batches


def _batches_after_formal_first(
    work_count: int, first: dict[str, int], concurrency: int,
    first_completed: bool, unit: str = "particles"
) -> list[dict[str, int]]:
    """Balance lanes, with one later remainder for the retained first batch.

    The first formal batch may already have completed when this is called.  It
    is still a partial lane, rather than a reason to make every following
    lane smaller.  Keep the original lane target and emit its remainder as a
    final batch.  That gives the same total work per logical lane whether the
    full-lifecycle observation finished quickly or slowly.
    """
    first_count = first["count"]
    remaining = work_count - first_count
    if remaining <= 0:
        return [dict(first)]
    if concurrency == 1:
        tail_counts = [remaining]
    else:
        target_lane_load = max(first_count, math.ceil(work_count / concurrency))
        first_lane_remainder = target_lane_load - first_count
        other_lane_counts = _balanced_lane_loads(
            remaining - first_lane_remainder, concurrency - 1
        )
        # Start each previously idle lane first.  The retained observation
        # batch receives its one balancing remainder only after it finishes.
        tail_counts = other_lane_counts + ([first_lane_remainder] if first_lane_remainder else [])
    batches = [dict(first)]
    for batch in _batches_from_counts(tail_counts, first_count, unit):
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
    work_count, field_kind, unit = _validate_request(request)
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
        first = _initial_formal_batch(work_count, unit)
        count_field = "particle_count" if unit == "particles" else "work_item_count"
        return {
            "schema_version": 2, "role": "simion_repository_dispatch_plan",
            "solver": "SIMION", "field_kind": field_kind,
            "dispatch_unit": unit, count_field: work_count,
            "resource_identity": identity,
            "estimation": {
                "kind": "formal_first_batch_observation",
                "requires_observation_before_remaining_launches": work_count > first["count"],
                "observation_seconds": FORMAL_OBSERVATION_SECONDS,
                "first_batch_result_retained": True,
                "terminal_action": "complete_first_formal_batch_then_replan_remaining_particles",
            },
            "host": host, "limits": _public_limits(1, 1, 1),
            "waves": [{
                "index": 1, "kind": "formal_observation", "batch_count": 1,
                count_field: work_count, "coverage": "initial_formal_batch_only",
                "batches": [first],
            }],
        }
    peak = _positive_int(profile["per_batch_peak_working_set_bytes"], "profile peak")
    memory_budget = math.ceil(peak * KNOWN_MEMORY_SAFETY_FACTOR)
    process_cpu = _nonnegative_number(profile.get("per_batch_cpu_percent", 0.0), "profile CPU")
    concurrency, cpu_capacity, memory_capacity = _capacity(
        particle_count=work_count, available_memory_bytes=available_memory_bytes,
        total_physical_memory_bytes=total_physical_memory_bytes,
        per_process_memory_bytes=memory_budget, process_cpu_percent=process_cpu,
        background_cpu_percent=0.0,
    )
    batches = _batches_from_counts(
        _balanced_lane_loads(work_count, concurrency), unit=unit
    )
    count_field = "particle_count" if unit == "particles" else "work_item_count"
    return {
        "schema_version": 2, "role": "simion_repository_dispatch_plan",
        "solver": "SIMION", "field_kind": field_kind, "dispatch_unit": unit,
        count_field: work_count,
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
            count_field: work_count, "coverage": "complete_population",
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
    unit = plan.get("dispatch_unit", "particles")
    count_field = "particle_count" if unit == "particles" else "work_item_count"
    work_count = _positive_int(plan.get(count_field), count_field)
    concurrency, cpu_capacity, memory_capacity = _capacity(
        particle_count=work_count, available_memory_bytes=available_memory_bytes,
        total_physical_memory_bytes=total_physical_memory_bytes,
        per_process_memory_bytes=memory_budget, process_cpu_percent=cpu,
        # Background CPU is transient host state, not a durable per-run
        # capacity. The executor gates every staggered launch against the
        # live CPU value plus this observed per-process cost.
        background_cpu_percent=0.0,
    )
    if not first_batch_completed:
        # Available RAM is sampled while the retained formal batch is already
        # running.  It can therefore admit zero additional workers.  _capacity
        # deliberately floors every standalone plan at one lane; reusing that
        # floor as an *additional* lane would turn a one-process host into a
        # false two-lane plan and leave the executor waiting forever.  Count
        # the already-running formal lane once, then add only whole extra
        # process budgets that genuinely fit after the fixed Windows reserve.
        if available_memory_bytes is None:
            additional_memory_capacity = 0
        else:
            additional_memory_capacity = max(
                0,
                (available_memory_bytes - MEMORY_ADMISSION_RESERVE_BYTES)
                // memory_budget,
            )
        memory_capacity = 1 + additional_memory_capacity
        # CPU capacity is an independent process count.  The active formal
        # worker is one of those processes, so preserve its existing lane.
        cpu_capacity += 1
        concurrency = min(work_count, cpu_capacity, memory_capacity)
    first = dict(plan["waves"][0]["batches"][0])
    batches = _batches_after_formal_first(
        work_count, first, concurrency, first_batch_completed, unit
    )
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
        count_field: work_count, "coverage": "complete_population",
        "batches": batches,
    }]
    return result


def _request_from_dispatch_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if plan.get("role") != "simion_repository_dispatch_plan":
        raise ValueError("prepared dispatch plan has an unsupported role")
    unit = plan.get("dispatch_unit", "particles")
    if unit == "particles":
        count = {"particle_count": plan.get("particle_count"), "independent_particles": True}
    elif unit == "independent_work_items":
        count = {
            "work_item_count": plan.get("work_item_count"),
            "independent_work_items": True,
        }
    else:
        raise ValueError("prepared dispatch plan has an unsupported dispatch_unit")
    return {
        "solver": "SIMION", "field_kind": plan.get("field_kind"),
        **count, **dict(plan.get("resource_identity", {})),
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
    print(format_dispatch_decision_event(plan))
    print(f"SIMION_REPOSITORY_DISPATCH_PLAN=PASS FIELD_KIND={plan['field_kind']} WAVES={len(plan['waves'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
