"""Recorded measured-population lifecycle and time statistics."""
import math
import statistics
from typing import Any
from msplatform.analysis.peak_metrics import AnalysisSettings, compute_time_peak_metrics, unavailable_peak_metadata


def log_roundoff_us(time_us: float) -> float:
    # mrtof_candidate.lua emits event t_us with %.12g: half its last decimal.
    return 0.5 * 10 ** (math.floor(math.log10(abs(time_us))) - 11) if time_us else 0.0


def close_event_rows(events, completed, states):
    if not completed or sum(completion.splats for completion in completed) != len(states):
        raise ValueError("Fly completion count differs from transferred source")
    terminals, detectors, splats = {}, {}, {}
    for event in events:
        particle = int(event["ion"])
        if particle not in states:
            raise ValueError(f"Unknown downstream particle ID: {particle}")
        time = float(event["t_us"])
        birth = states[particle]["instrument_time_us"]
        if time + log_roundoff_us(time) < birth:
            raise ValueError(f"Absolute event clock precedes measured handoff: {particle}")
        if particle in terminals:
            raise ValueError(f"Event follows terminal or duplicate terminal: {particle}")
        # Different interpolated plane events may print out of chronological
        # order within one solver step; retain their recorded times unchanged.
        kind = event["kind"]
        target = {"terminal": terminals, "detector": detectors, "splat": splats}.get(kind)
        if target is not None:
            if particle in target:
                raise ValueError(f"Duplicate {kind} for particle: {particle}")
            target[particle] = event
    if set(terminals) != set(states):
        raise ValueError(f"Missing downstream terminal IDs: {sorted(set(states)-set(terminals))}")
    for particle, terminal in terminals.items():
        code = int(terminal["splat"])
        if particle in splats and int(splats[particle]["code"]) != code:
            raise ValueError(f"Splat and terminal codes conflict: {particle}")
        if (particle in detectors) != (code == 1):
            if not (code == 1 and particle not in detectors
                    and terminal.get("termination_kind") == "programmatic_stop_with_unconfirmed_crossing"):
                raise ValueError(f"Detector and terminal codes conflict: {particle}")
    return events, terminals, detectors


def time_statistics(values: list[float], basis: str) -> dict[str, Any]:
    return {"time_basis": basis, "unit": "us", "count": len(values),
            "mean": statistics.fmean(values) if values else None,
            "population_sigma": statistics.pstdev(values) if len(values) >= 2 else None,
            "minimum": min(values) if values else None, "maximum": max(values) if values else None,
            "range": max(values)-min(values) if len(values) >= 2 else None,
            "width_status": "observed_population_sigma_and_range" if len(values) >= 2 else "unavailable_fewer_than_two_hits",
            "fwhm": None, "resolution": None, "peak_status": "unavailable_no_declared_peak_analysis_contract"}


def population_rows(census: list[dict[str, str]], states: dict[int, dict[str, Any]],
                     terminals: dict[int, dict[str, Any]], detectors: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for original in census:
        particle = int(original["particle_id"])
        row = {"particle_id": particle, "upstream_transfer_status": original["transfer_status"],
               "upstream_terminal_reason": original["terminal_reason"],
               "upstream_terminal_instrument_time_us": original["instrument_time_us"],
               "handoff_instrument_time_us": "", "downstream_status": "not_transferred",
               "downstream_terminal_splat": "", "downstream_terminal_instrument_time_us": "",
               "detector_arrival_instrument_time_us": "", "detector_time_since_handoff_us": ""}
        for axis in "xyz":
            row[f"terminal_position_{axis}_mm"] = ""
            row[f"terminal_velocity_{axis}_m_s"] = ""
        if particle in states:
            handoff = states[particle]["instrument_time_us"]
            terminal = terminals[particle]
            code = int(terminal["splat"])
            status = {1: "detected", 2: "timeout", -1: "loss", 4: "topology_rejected"}.get(code, "unknown")
            if terminal.get("termination_kind") == "programmatic_stop_with_unconfirmed_crossing":
                status = "unknown"
            row.update(handoff_instrument_time_us=handoff,
                       downstream_status=status,
                       downstream_terminal_splat=code, downstream_terminal_instrument_time_us=terminal["t_us"])
            for axis in "xyz":
                row[f"terminal_position_{axis}_mm"] = terminal[f"{axis}_mm"]
                row[f"terminal_velocity_{axis}_m_s"] = terminal[f"v{axis}_mm_us"] * 1000
            if particle in detectors:
                arrival = float(detectors[particle]["t_us"])
                row.update(detector_arrival_instrument_time_us=arrival,
                           detector_time_since_handoff_us=arrival-handoff)
        result.append(row)
    return result



def prepare_detector_peak(contract: dict[str, Any] | None, pulse: float | None, receipt: dict[str, Any],
                           states: dict[int, dict[str, Any]], detectors: dict[int, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Use one frozen extraction reference for every detected arrival; never recenter individual ions."""
    result: dict[str, Any] = {"status": "unavailable_missing_analysis_contract", "fwhm_us": None,
                              "time_equivalent_resolution": None,
                              "qualification": "detector_survivor_conditioned_time_equivalent_only",
                              "detected_particle_ids": sorted(detectors), "analysis_contract": contract}
    weights = [states[particle]["particle_weight"] for particle in sorted(detectors)]
    result["analysis_metadata"] = unavailable_peak_metadata(
        len(detectors), result["status"], weights=weights,
    )
    if contract is None:
        return result, None

    if pulse is None:
        raise ValueError("validated common pulse is required")
    reference = contract["common_time_reference"]
    species = {(row["mass_amu"], row["charge_state"]) for row in states.values()}
    if len(species) != 1:
        raise ValueError("Detector peak analysis requires one frozen species")
    mass, charge = next(iter(species))
    settings = AnalysisSettings(**contract["settings"])
    times = [float(detectors[particle]["t_us"])-pulse for particle in sorted(detectors)]
    if any(not math.isfinite(time) or time <= 0 for time in times):
        raise ValueError("Detector TOF must follow the common extraction pulse")
    result.update(common_time_reference={**reference, "resolved_pulse_start_us": pulse},
                  settings=settings.to_dict(), count=len(times),
                  mean_tof_us=statistics.fmean(times) if times else None,
                  nominal_mass_amu=mass, charge_state=charge,
                  timing_policy="One common pulse subtraction; all detector hits retained; no per-ion handoff subtraction.")
    time_reference = {
        "kind": "common_extraction_pulse", "clock_epoch_id": reference["clock_epoch_id"],
        "reference_time_us": pulse, "timing": reference["timing"], "field": reference["field"],
        "clock_qualification": "validated_epoch_and_frozen_timing",
    }
    result["analysis_metadata"] = unavailable_peak_metadata(
        len(times), result["status"], method_id=contract["method_id"], weights=weights,
        settings=settings.to_dict(), time_reference=time_reference,
    )
    if len(times) < 3:
        result["status"] = "unavailable_fewer_than_three_hits"
        result["analysis_metadata"]["status"] = result["status"]
        return result, None
    if min(times) == max(times):
        result["status"] = "unavailable_zero_variance"
        result["analysis_metadata"]["status"] = result["status"]
        return result, None
    metrics, spectra = compute_time_peak_metrics(times, settings, weights=weights)
    metrics["analysis_metadata"]["time_reference"] = time_reference
    result["analysis_metadata"] = metrics["analysis_metadata"]
    result["species"] = {key: states[next(iter(states))][key]
                         for key in ("mass_amu", "charge_state", "mass_to_charge_Th")}
    result.update(status="evaluated", fwhm_us=metrics["direct_fwhm_tof_ns"]/1000,
                  time_equivalent_resolution=metrics["time_equivalent_resolution"], metrics=metrics)
    return result, spectra
