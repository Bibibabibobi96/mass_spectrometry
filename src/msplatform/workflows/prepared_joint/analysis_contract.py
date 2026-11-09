"""Shared scientific contract changes; offline analysis never invokes a controller."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any


def _native_refine_change(reference: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any] | None:
    """Validate both native identities and isolate only the declared Boolean strategy."""
    from msplatform.backends.comsol.static_field_binding import resolve_native_refine_numerics

    profiles = [value["simion"].get("numerical_profiles", {}) for value in (reference, contract)]
    if not any("native_static_field" in profile for profile in profiles):
        return None
    previous, current = [resolve_native_refine_numerics(value) for value in (reference, contract)]
    for value in (reference, contract):
        value["simion"]["numerical_profiles"]["native_static_field"]["refine"].pop("skipped_point", None)
    if previous == current:
        return None
    # Other numerical changes remain in the full contract comparison below.
    return dict(change_kind="native_refine_skipped_point_policy_only", previous=previous, current=current)



def reference_changes(expected: dict[str, Any], scientific: dict[str, Any], *, contract_base: Path) -> dict:
    from msplatform.components.parallel_mirror_dual_stripe_mr_tof.candidate_contract import resolve_trajectory_profile
    native_refine_change = _native_refine_change(expected, scientific)
    analysis_change = None
    peak = scientific.get("peak_analysis")
    previous_peak = expected.get("peak_analysis")
    if peak and peak.get("time_basis") == "instrument_arrival_minus_common_extraction_pulse_us":
        from msplatform.workflows.prepared_joint.measured_population import validate_measured_peak_analysis_contract
        validate_measured_peak_analysis_contract(peak, contract_base)
        if peak != previous_peak:
            names = ("resolution_definition", "settings")
            old_method = previous_peak.get("method_id") if previous_peak else None
            method_ok = old_method == peak["method_id"] or (
                old_method == "common_gaussian_kde_time_v1" and peak["method_id"] == "common_gaussian_kde_time_v2"
                and previous_peak.get("time_basis") in (
                    "instrument_arrival_us_from_common_zero_birth",
                    "instrument_arrival_minus_common_extraction_pulse_us",
                )
            )
            if previous_peak is None or not method_ok or any(peak[name] != previous_peak.get(name) for name in names):
                raise ValueError("Measured peak reference change must retain the declared method, time basis and settings")
            analysis_change = dict(change_kind=("measured_detector_peak_method_upgrade" if old_method != peak["method_id"]
                                                else "measured_detector_common_pulse_reference"),
                                   previous=previous_peak, current=peak)
            scientific["peak_analysis"] = expected["peak_analysis"]
    previous = resolve_trajectory_profile(expected)
    current = resolve_trajectory_profile(scientific)
    profile_id = previous["profile_id"]
    if current["profile_id"] != profile_id:
        raise ValueError("Prepared joint trial must retain its selected trajectory profile")
    if current["trajectory_quality"] != previous["trajectory_quality"]:
        raise ValueError("Prepared joint timestep comparison must retain trajectory quality")
    selected = scientific["simion"]["trajectory_profiles"][profile_id]["maximum_step_us"]
    if isinstance(selected, bool) or not isinstance(selected, (int, float)):
        raise ValueError("Selected maximum_step_us must be a numeric integration bound")
    change = None
    if current["maximum_step_us"] != previous["maximum_step_us"]:
        change = dict(change_kind="selected_trajectory_maximum_step_only", profile_id=profile_id,
                      maximum_step_us=dict(previous=previous["maximum_step_us"], current=current["maximum_step_us"]))
    scientific["simion"]["trajectory_profiles"][profile_id]["maximum_step_us"] = (
        expected["simion"]["trajectory_profiles"][profile_id]["maximum_step_us"])
    return dict(reference_profile=previous, selected_profile=current, numerical_change=change,
                analysis_change=analysis_change, native_refine_change=native_refine_change)


def validate_posthoc_analysis_contract(reference: dict[str, Any], contract: dict[str, Any], *, contract_base: Path) -> dict:
    """Allow only the original declared peak-analysis change over frozen native inputs."""
    if ({key: value for key, value in contract.items() if key != "peak_analysis"}
            != {key: value for key, value in reference.items() if key != "peak_analysis"}):
        raise ValueError("Post-hoc analysis contract may change only peak_analysis")
    expected = json.loads(json.dumps(reference))
    scientific = json.loads(json.dumps(contract))
    expected["simion"].pop("trajectory_recording", None)
    scientific["simion"].pop("trajectory_recording", None)
    changes = reference_changes(expected, scientific, contract_base=contract_base)
    if scientific != expected:
        raise ValueError("Finalization contract changes more than the selected trajectory step")
    return dict(reference_profile=changes["reference_profile"], selected_profile=changes["selected_profile"],
        numerical_change=changes["numerical_change"], execution_budget_change=None,
        analysis_change=changes["analysis_change"], native_refine_change=changes["native_refine_change"])
