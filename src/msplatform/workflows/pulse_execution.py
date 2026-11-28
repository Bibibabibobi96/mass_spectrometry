"""Resolve discovery and full-instrument flights from frozen native contracts."""
from __future__ import annotations

from typing import Any


def resolve_phase_flight(author_flight: dict, *, phase: str, decision: dict | None = None,
                         requires_rf: bool = True) -> dict[str, Any]:
    """Derive one native control from the frozen author's explicit plan."""
    from msplatform.backends.simion.tracking_program import validate_native_flight

    author = validate_native_flight(author_flight, requires_rf=requires_rf, allow_discovery=True)
    if phase not in {"discovery", "full_instrument"}:
        raise ValueError("native flight phase must be discovery or full_instrument")
    if author["pulse"]["mode"] != "discover":
        if phase != "full_instrument" or decision is not None:
            raise ValueError("only an author discovery plan can derive flight phases or a decision")
        return validate_native_flight(author, requires_rf=requires_rf)
    actual = {key: value for key, value in author.items() if key != "pulse"}
    if phase == "discovery":
        if decision is not None:
            raise ValueError("discovery cannot consume a pulse decision")
        actual.update(pulse={"mode": "held_off"}, observation_times_us=list(author["pulse"]["candidate_times_us"]))
    else:
        if (not isinstance(decision, dict) or decision.get("schema_version") != 2
                or decision.get("role") != "single_reflection_actual_occupancy_pulse_decision"
                or decision.get("status") != "success"
                or decision.get("selection_uses_future_terminal_outcome") is not False
                or decision.get("candidate_times_us") != author["pulse"]["candidate_times_us"]
                or decision.get("pulse_width_us") != author["pulse"]["width_us"]):
            raise ValueError("timed discovery successor requires a successful matching actual-occupancy decision")
        time = decision.get("actual_pulse_time_us")
        selection = decision.get("selection", {})
        if (isinstance(time, bool) or not isinstance(time, (int, float))
                or time not in author["pulse"]["candidate_times_us"]
                or selection.get("status") != "selected" or selection.get("selected_time_us") != time):
            raise ValueError("pulse decision must select one declared actual candidate")
        actual["pulse"] = {"mode": "timed", "time_us": time, "width_us": author["pulse"]["width_us"]}
    return validate_native_flight(actual, requires_rf=requires_rf)
