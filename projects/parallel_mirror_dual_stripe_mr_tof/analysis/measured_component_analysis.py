"""Close a measured-source MR flight against its entire upstream mother cohort.

This solver-independent consumer reports recorded detector arrivals and elapsed
handoff times separately. It does not invoke the OA ideal-source analyzer, fit
an undeclared peak model, or grant physical/field/performance qualification.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import shutil
import statistics
from typing import Any

from common.analysis.particle_census import partition_cohort, subset_efficiency
from common.contracts.canonical_clock_authority import validate_clock_authority
from common.contracts.component_particle_state import load_component_particle_state_csv
from common.contracts.file_identity import file_sha256
from common.contracts.verify_run_manifest import record_path, verify_record
from common.simion.native_completion import parse_fly_completed_line
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import parse_events, unavailable_peak_metadata


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _identity(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": file_sha256(path)}


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def _load_source(path: Path) -> tuple[dict[str, Any], dict[int, dict[str, Any]], list[dict[str, str]], Path]:
    receipt = _read(path)
    if (receipt.get("schema_version") != 1 or receipt.get("role") != "mrtof_measured_component_source"
            or receipt.get("status") != "prepared_only" or receipt.get("source_materialization_ready") is not True):
        raise ValueError("Unsupported prepared measured-source receipt")
    for name, record in {**receipt["inputs"], **receipt["outputs"]}.items():
        verify_record(name, record, base_dir=path.parent)
    state_path = record_path(receipt["outputs"]["component_particle_state"], base_dir=path.parent)
    census_path = record_path(receipt["outputs"]["source_census"], base_dir=path.parent)
    table = load_component_particle_state_csv(state_path)
    validation = table.report
    clock_path = record_path(receipt["outputs"]["clock_authority"], base_dir=path.parent)
    clock = validate_clock_authority(clock_path, path.parent)
    epoch_path = record_path(receipt["outputs"]["instrument_epoch"], base_dir=path.parent)
    if (validation["frame_ids"] != [receipt["frame_id"]]
            or validation["clock_epoch_ids"] != [receipt["clock_epoch_id"]]
            or clock["clock_epoch_id"] != receipt["clock_epoch_id"]
            or _read(epoch_path)["instrument_time_us"] != receipt["solver_epoch_instrument_time_us"]):
        raise ValueError("Prepared source clock/frame authority differs")
    states = {row["particle_id"]: row for row in table.rows}
    census = _rows(census_path)
    try:
        partition = partition_cohort([int(row["particle_id"]) for row in census],
            [(int(row["particle_id"]), row["transfer_status"]) for row in census],
            categories=("transferred", "not_transferred"), relative_weights=None)
    except ValueError as exc:
        raise ValueError("Prepared source complete mother census does not close") from exc
    transferred = set(partition["particle_ids_by_category"]["transferred"])
    counts = {"source": partition["mother_count"], "transferred": len(states),
              "not_transferred": partition["counts"]["not_transferred"]}
    if transferred != set(states) or counts != receipt["counts"]:
        raise ValueError("Prepared source complete mother census does not close")
    for row in census:
        pid = int(row["particle_id"])
        if row.get("particle_weight"):
            weight = float(row["particle_weight"])
            if not math.isfinite(weight) or weight <= 0:
                raise ValueError("Prepared source census has an invalid weight")
            if pid in states and weight != states[pid]["particle_weight"]:
                raise ValueError("Prepared source census and transferred state weights differ")
    return receipt, states, census, census_path


def _log_roundoff_us(time_us: float) -> float:
    # mrtof_candidate.lua emits event t_us with %.12g: half its last decimal.
    return 0.5 * 10 ** (math.floor(math.log10(abs(time_us))) - 11) if time_us else 0.0


def _close_events(text: str, states: dict[int, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    events = parse_events(text)
    completed = [completion for line in text.splitlines()
                 if (completion := parse_fly_completed_line(line)) is not None]
    if not completed or sum(completion.splats for completion in completed) != len(states):
        raise ValueError("Fly completion count differs from transferred source")
    terminals, detectors, splats = {}, {}, {}
    for event in events:
        particle = int(event["ion"])
        if particle not in states:
            raise ValueError(f"Unknown downstream particle ID: {particle}")
        time = float(event["t_us"])
        birth = states[particle]["instrument_time_us"]
        if time + _log_roundoff_us(time) < birth:
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
            raise ValueError(f"Detector and terminal codes conflict: {particle}")
    return events, terminals, detectors


def _statistics(values: list[float], basis: str) -> dict[str, Any]:
    return {"time_basis": basis, "unit": "us", "count": len(values),
            "mean": statistics.fmean(values) if values else None,
            "population_sigma": statistics.pstdev(values) if len(values) >= 2 else None,
            "minimum": min(values) if values else None, "maximum": max(values) if values else None,
            "range": max(values)-min(values) if len(values) >= 2 else None,
            "width_status": "observed_population_sigma_and_range" if len(values) >= 2 else "unavailable_fewer_than_two_hits",
            "fwhm": None, "resolution": None, "peak_status": "unavailable_no_declared_peak_analysis_contract"}


def _population_rows(census: list[dict[str, str]], states: dict[int, dict[str, Any]],
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


def validate_measured_peak_analysis_contract(contract: dict[str, Any], base: Path) -> float:
    """Verify explicit common-pulse peak settings and frozen timing bytes; return pulse time in us."""
    from common.analysis.peak_metrics import AnalysisSettings
    if (set(contract) != {"method_id", "resolution_definition", "time_basis", "settings", "common_time_reference"}
            or contract["method_id"] != "common_gaussian_kde_time_v2"
            or contract["resolution_definition"] != "mean_tof_us/(2*direct_fwhm_tof_us)"
            or contract["time_basis"] != "instrument_arrival_minus_common_extraction_pulse_us"
            or set(contract["settings"]) != set(AnalysisSettings.__dataclass_fields__)):
        raise ValueError("Unsupported measured detector peak analysis contract")
    reference = contract["common_time_reference"]
    if (set(reference) != {"clock_epoch_id", "timing", "field"}
            or not isinstance(reference["clock_epoch_id"], str) or not reference["clock_epoch_id"]
            or reference["field"] != "pulse_start_us"):
        raise ValueError("Detector peak extraction clock authority differs")
    verify_record("detector peak timing", reference["timing"], base_dir=base)
    timing_path = record_path(reference["timing"], base_dir=base)
    timing = _read(timing_path)
    pulse = timing[reference["field"]]
    if (timing.get("schema_version") != 1 or timing.get("role") != "native_electrode_timing"
            or isinstance(pulse, bool) or not isinstance(pulse, (int, float)) or not math.isfinite(pulse)):
        raise ValueError("Invalid common extraction pulse time")
    settings = AnalysisSettings(**contract["settings"])
    if (type(settings.grid_points) is not int or type(settings.standardized_grid_points) is not int
            or settings.grid_points < 3 or settings.standardized_grid_points < 3
            or not math.isfinite(settings.bandwidth_multiplier) or settings.bandwidth_multiplier <= 0
            or not 0 < settings.mode_threshold_fraction <= 1
            or not math.isfinite(settings.standardized_grid_min) or not math.isfinite(settings.standardized_grid_max)
            or settings.standardized_grid_min >= settings.standardized_grid_max):
        raise ValueError("Invalid detector peak numerical settings")
    return float(pulse)


def validate_measured_peak_source_reference(contract: dict[str, Any], base: Path, source: dict[str, Any],
                                            states: dict[int, dict[str, Any]]) -> float:
    """Check a common pulse against actual handoff clock/states before flight or analysis."""
    pulse = validate_measured_peak_analysis_contract(contract, base)
    if contract["common_time_reference"]["clock_epoch_id"] != source["clock_epoch_id"]:
        raise ValueError("Detector peak extraction clock authority differs")
    if not states or any(pulse > row["instrument_time_us"] for row in states.values()):
        raise ValueError("Invalid common extraction pulse time after measured handoff")
    return pulse


def _prepare_detector_peak(contract: dict[str, Any] | None, base: Path, receipt: dict[str, Any],
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
    from common.analysis.peak_metrics import AnalysisSettings, compute_time_peak_metrics

    pulse = validate_measured_peak_source_reference(contract, base, receipt, states)
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


def _save_detector_peak(output: Path, peak: dict[str, Any], spectra: dict[str, Any] | None,
                        states: dict[int, dict[str, Any]], detectors: dict[int, dict[str, Any]], metadata: dict[str, Any]) -> None:
    """Export raw hits, KDE samples and a headless figure without recomputing metrics."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    pulse = peak["common_time_reference"]["resolved_pulse_start_us"]
    with (output / "detector_peak_samples.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(("particle_id", "detector_instrument_time_us", "common_pulse_time_us", "tof_from_common_pulse_us", "handoff_instrument_time_us"))
        for particle in sorted(detectors):
            arrival = float(detectors[particle]["t_us"])
            writer.writerow((particle, arrival, pulse, arrival-pulse, states[particle]["instrument_time_us"]))
    figure = Figure(figsize=(8, 4.4), layout="constrained")
    FigureCanvasAgg(figure)
    axis = figure.subplots()
    if spectra is not None:
        with (output / "detector_peak_spectrum.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(("tof_from_common_pulse_us", "probability_density_per_us", "peak_normalized_density"))
            writer.writerows(zip(spectra["time_grid_us"], spectra["time_density"], spectra["time_density_normalized"]))
        axis.plot(spectra["time_grid_us"], spectra["time_density_normalized"], color="#0072B2", label="Common Gaussian KDE")
        axis.plot(spectra["tof_us"], [0]*len(spectra["tof_us"]), "|", color="black", markersize=8, label="All detected ions")
        left, right = float(spectra["time_half_left_us"]), float(spectra["time_half_right_us"])
        axis.plot([left, right], [.5, .5], "s--", color="#D55E00", label="Direct FWHM")
        axis.set_title(f"FWHM = {peak['fwhm_us']*1000:.4g} ns; time-equivalent R = {peak['time_equivalent_resolution']:.5g}")
        axis.legend(fontsize=8)
    else:
        axis.text(.5, .5, peak["status"].replace("_", " "), ha="center", transform=axis.transAxes)
        arrivals = [float(event["t_us"])-pulse for event in detectors.values()]
        axis.plot(arrivals, [0]*len(arrivals), "|", color="black", markersize=8)
    axis.set(xlabel="Detector TOF from common extraction pulse (us)", ylabel="Peak-normalized probability density")
    counts = metadata["counts"]
    figure.suptitle(f"Detected {counts['detected']}/{counts['mother_source']} mother ions ({counts['downstream_released']} handed off)")
    metadata = dict(metadata, role="mrtof_measured_detector_peak_figure", peak_analysis=peak,
                    size_inches=[8, 4.4], dpi=180, formats=["png", "svg"],
                    filtering="All detector survivors; no tail removal or per-ion time recentering", uncertainty="Finite cohort descriptive KDE; no confidence interval")
    for extension in ("png", "svg"):
        figure.savefig(output / f"detector_peak.{extension}", format=extension, dpi=180, facecolor="white")
    _write(output / "detector_peak.metadata.json", metadata)
    figure.clear()


def analyze_measured_component(log_path: Path, source_receipt_path: Path, output_directory: Path, *,
                               peak_analysis_contract: dict[str, Any] | None = None,
                               contract_base_directory: Path | None = None) -> dict[str, Any]:
    """Publish complete per-ID census and observed timing from absolute-time logs.

    Source receipt is the authority for original IDs, initial 6D, clock and full
    mother census. Invalid/duplicate/unknown/missing lifecycles fail before any
    output. No solver, GUI, propagation or undeclared peak fitting is performed.
    """
    if output_directory.exists():
        raise FileExistsError(f"Refusing to overwrite measured analysis: {output_directory}")
    receipt, states, census, census_path = _load_source(source_receipt_path)
    events, terminals, detectors = _close_events(log_path.read_text(encoding="utf-8-sig"), states)
    rows = _population_rows(census, states, terminals, detectors)
    mother = [int(row["particle_id"]) for row in census]
    partition = partition_cohort(mother, [(row["particle_id"], row["downstream_status"]) for row in rows],
        categories=("not_transferred", "detected", "timeout", "loss", "topology_rejected", "unknown"), relative_weights=None)
    # Missing historical mother weights are unknown, never inferred as unit weights.
    complete_weights = all(row.get("particle_weight") for row in census)
    weights = {int(row["particle_id"]): float(row["particle_weight"]) for row in census} if complete_weights else None
    mother_efficiency = subset_efficiency(mother, detectors, mother, relative_weights=weights) if complete_weights else None
    handoff_weights = {pid: row["particle_weight"] for pid, row in states.items()}
    handoff_efficiency = subset_efficiency(list(states), detectors, list(states), relative_weights=handoff_weights)
    counts = {"mother_source": len(census), "upstream_not_transferred": receipt["counts"]["not_transferred"],
              "downstream_released": len(states), "detected": len(detectors),
              "downstream_timeout": sum(row["downstream_status"] == "timeout" for row in rows),
              "downstream_loss": sum(row["downstream_status"] == "loss" for row in rows),
              "downstream_topology_rejected": sum(row["downstream_status"] == "topology_rejected" for row in rows),
              "downstream_unknown": sum(row["downstream_status"] == "unknown" for row in rows)}
    arrivals = [float(event["t_us"]) for event in detectors.values()]
    elapsed = [float(event["t_us"])-states[particle]["instrument_time_us"] for particle, event in detectors.items()]
    peak, spectra = _prepare_detector_peak(peak_analysis_contract, contract_base_directory or source_receipt_path.parent,
                                          receipt, states, detectors)
    output_directory.mkdir(parents=True)
    shutil.copyfile(census_path, output_directory / "upstream_source_census.csv")
    with (output_directory / "particle_census.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    _write(output_directory / "parsed_events.json", events)
    if peak_analysis_contract is not None:
        _save_detector_peak(output_directory, peak, spectra, states, detectors,
                            dict(counts=counts, clock_epoch_id=receipt["clock_epoch_id"],
                                 inputs={"log": _identity(log_path), "source_receipt": _identity(source_receipt_path)},
                                 producer=_identity(Path(__file__))))
    report = {"schema_version": 1, "role": "mrtof_measured_component_analysis", "status": "population_closed",
              "qualification": "recorded_lifecycle_and_timing_only", "physical_performance_pass": None,
              "counts": counts, "clock_epoch_id": receipt["clock_epoch_id"], "frame_id": receipt["frame_id"],
              "detected_fraction_of_mother": len(detectors)/len(census),
              "detected_fraction_of_handoff": len(detectors)/len(states),
              "population_partition_counts": partition["counts"],
              "weighted_efficiency": {"mother": mother_efficiency,
                  "mother_unavailable_reason": None if complete_weights else "incomplete_mother_weights",
                  "handoff": handoff_efficiency},
              "absolute_arrival": _statistics(arrivals, "canonical_absolute_instrument_time_us"),
              "elapsed_since_handoff": _statistics(elapsed, "per_particle_elapsed_since_measured_handoff_diagnostic_only"),
              "detector_peak": peak,
              "peak_time_policy": "Use common absolute arrival axis for packet width; never subtract individual handoff times for peak analysis.",
              "plot_consumer": "particle_census.csv and parsed_events.json retain original IDs/absolute times for existing MR diagnostic plotting; no OA ideal-source receipt is fabricated.",
              "inputs": {"log": _identity(log_path), "source_receipt": _identity(source_receipt_path)},
              "outputs": {path.stem: _identity(path) for path in sorted(output_directory.iterdir())}}
    _write(output_directory / "analysis_receipt.json", report)
    return report
