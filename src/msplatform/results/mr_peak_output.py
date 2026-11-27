"""Write recorded detector-peak tables and figures without recomputing metrics."""
import csv
import json
from pathlib import Path
from typing import Any


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def write_detector_peak(output: Path, peak: dict[str, Any], spectra: dict[str, Any] | None,
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
