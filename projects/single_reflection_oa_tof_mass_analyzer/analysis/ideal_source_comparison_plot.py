"""Headless evidence figures from already-computed ideal-source case records.

Only display summaries (seed median and range) are prepared here. TOF, FWHM,
resolution, acceptance and uncertainty are never recomputed from particles.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import matplotlib as mpl
import numpy as np
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import ScalarFormatter
from PIL import Image


STYLE = {
    "font.family": "DejaVu Sans", "font.size": 8,
    "axes.labelsize": 9, "axes.titlesize": 10, "legend.fontsize": 8,
    "lines.linewidth": 1.1, "lines.markersize": 4,
    "axes.spines.top": False, "axes.spines.right": False,
    "svg.fonttype": "none", "savefig.facecolor": "white",
}
ARM_STYLE = {
    "two_zone_matched": ("#0072B2", "--", "s", "Two-zone, matched"),
    "three_zone_matched": ("#D55E00", "-", "o", "Three-zone, matched"),
}


def prepare_comparison_series(
    records: list[dict[str, Any]], config: dict[str, Any], *,
    stage: str, arm: str | None = None, residual_sigma_m_per_s: float | None = None,
) -> list[dict[str, Any]]:
    """Prepare ordered plot points, with missing/ineligible seeds left as gaps."""

    if stage not in {"residual_scan", "width_scan"} or (stage == "width_scan" and arm not in ARM_STYLE):
        raise ValueError("unknown plot stage or width-scan arm")
    x_key = "residual_sigma_m_per_s" if stage == "residual_scan" else "full_width_mm"
    x_values = config[stage]["residual_sigma_m_per_s" if stage == "residual_scan" else "full_widths_mm"]
    prepared = []
    for x in x_values:
        subset = [record for record in records if record["case"]["stage"] == stage
                  and record["case"][x_key] == x
                  and (stage == "residual_scan" or record["case"]["residual_sigma_m_per_s"] == residual_sigma_m_per_s)]
        seeds = [record["case"]["seed"] for record in subset]
        if len(set(seeds)) != len(seeds):
            raise ValueError("duplicate seeds within a plotted scan point")
        samples, excluded = [], []
        for record in subset:
            selected = record["arms"].get(arm, {}) if arm else {}
            value = record["resolution_gain_percent"] if stage == "residual_scan" else selected["resolution"]
            eligible = record["comparison_eligible"] if stage == "residual_scan" else selected["full_cohort_reachable"]
            if value is not None and (not np.isfinite(value) or (stage == "width_scan" and value <= 0)):
                raise ValueError("plot data contain non-finite gain or nonpositive resolution")
            if eligible and value is not None:
                samples.append({"seed": record["case"]["seed"], "value": float(value)})
            else:
                excluded.append({"seed": record["case"]["seed"], "value": value,
                                 "reason": selected.get("reason") or record.get("reason") or "undefined peak or incomplete axial mother cohort"})
        values = [sample["value"] for sample in samples]
        complete = len(samples) == config["sampling"]["replicate_count"] and not excluded
        prepared.append({"x": float(x), "samples": samples, "excluded": excluded,
                         "expected_seeds": config["sampling"]["replicate_count"],
                         "median": float(np.median(values)) if complete else None,
                         "minimum": min(values) if complete else None,
                         "maximum": max(values) if complete else None})
    return prepared


def _plot_series(axis: Axes, series: list[dict[str, Any]], *, color: str,
                 linestyle: str, marker: str, label: str) -> None:
    x = np.asarray([point["x"] for point in series])
    middle = np.asarray([point["median"] if point["median"] is not None else np.nan for point in series])
    lower = np.asarray([point["minimum"] if point["minimum"] is not None else np.nan for point in series])
    upper = np.asarray([point["maximum"] if point["maximum"] is not None else np.nan for point in series])
    axis.plot(x, middle, color=color, linestyle=linestyle, marker=marker, label=label)
    valid = np.isfinite(middle)
    axis.errorbar(x[valid], middle[valid], yerr=np.array([middle[valid]-lower[valid], upper[valid]-middle[valid]]),
                  fmt="none", color=color, capsize=3, elinewidth=.8)
    raw_x = [point["x"] for point in series for _ in point["samples"]]
    raw_y = [sample["value"] for point in series for sample in point["samples"]]
    axis.scatter(raw_x, raw_y, color=color, marker=marker, s=12, alpha=.45, zorder=3)
    if np.any(~valid):
        axis.plot(x[~valid], np.full(np.count_nonzero(~valid), .025), linestyle="none", marker="x",
                  color=color, transform=axis.get_xaxis_transform(), clip_on=False)


def build_residual_gain_figure(series: list[dict[str, Any]]) -> tuple[Figure, Axes]:
    """Render measured seed gains; symlog x includes zero without shifting data."""

    figure = Figure(figsize=(183/25.4, 100/25.4), layout="constrained")
    FigureCanvasAgg(figure)
    axis = figure.subplots()
    _plot_series(axis, series, color="#0072B2", linestyle="-", marker="o", label="Three-zone: source-aware mirror / uncorrelated setting")
    axis.axhline(0, color="#555555", linewidth=.7, linestyle=":")
    axis.set_xscale("symlog", linthresh=1.0)
    axis.set_yscale("symlog", linthresh=1.0)
    if series[-1]["x"] > series[0]["x"]:
        axis.set_xlim(series[0]["x"], series[-1]["x"])
    axis.set_xticks([point["x"] for point in series])
    axis.xaxis.set_major_formatter(ScalarFormatter())
    axis.set_xlabel("Prescribed axial velocity residual sigma (m/s)")
    axis.set_ylabel("Resolution change after mirror retuning (%, symlog)")
    axis.set_title("Residual magnitude and source-aware retuning")
    axis.grid(axis="y", color="#DDDDDD", linewidth=.5)
    axis.legend(loc="best", frameon=False)
    figure.supxlabel("Dots: individual seeds; line: median; bars: min–max (not CI). Axis-edge x: missing/ineligible.", fontsize=8)
    return figure, axis


def build_width_resolution_figure(
    panels: list[dict[str, Any]], *, minimum_resolution: float,
) -> tuple[Figure, list[Axes]]:
    """Render matched structure curves with common logarithmic resolution scale."""

    if not panels or minimum_resolution <= 0 or not np.isfinite(minimum_resolution):
        raise ValueError("width figure requires panels and a positive finite threshold")
    figure = Figure(figsize=(183/25.4, 105/25.4), layout="constrained")
    FigureCanvasAgg(figure)
    axes = list(np.asarray(figure.subplots(1, len(panels), sharey=True, squeeze=False)).ravel())
    all_values = [sample["value"] for panel in panels for series in panel["series"].values()
                  for point in series for sample in point["samples"]]
    for axis, panel in zip(axes, panels):
        for arm, series in panel["series"].items():
            color, line, marker, label = ARM_STYLE[arm]
            _plot_series(axis, series, color=color, linestyle=line, marker=marker, label=label)
        axis.axhline(minimum_resolution, color="#333333", linestyle=":", linewidth=1.0, label=f"R threshold = {minimum_resolution:g}")
        axis.set_title(f"Residual sigma = {panel['residual_sigma_m_per_s']:g} m/s")
        axis.set_xlabel("Full axial source width (mm)")
        axis.set_yscale("log")
        axis.grid(axis="y", which="major", color="#DDDDDD", linewidth=.5)
    limits = all_values + [minimum_resolution]
    axes[0].set_ylim(min(limits)/1.5, max(limits)*1.5)
    axes[0].set_ylabel("Mass resolution R (dimensionless)")
    axes[0].legend(loc="best", frameon=False)
    figure.supxlabel("Dots: seeds; lines: medians; bars: min–max (not CI). Gaps: incomplete/undefined full-cohort result.", fontsize=8)
    return figure, axes


def _save_figure(figure: Figure, result_dir: Path, stem: str) -> list[Path]:
    outputs = []
    for format_name in ("png", "svg"):
        target = result_dir / f"{stem}.{format_name}"
        if target.exists():
            raise FileExistsError(f"will not overwrite evidence figure: {target}")
        temporary = target.with_suffix(target.suffix + ".tmp")
        figure.savefig(temporary, format=format_name, dpi=300, facecolor="white")
        if format_name == "png":
            with Image.open(temporary) as preview:
                preview.verify()
        else:
            ElementTree.parse(temporary)
        temporary.replace(target)
        outputs.append(target)
    # Shared logarithmic axes otherwise warn when clear() resets their limits to
    # zero. The exported files are already frozen; this only releases artists.
    for axis in figure.axes:
        axis.set_yscale("linear")
    figure.clear()
    return outputs


def export_comparison_figures(
    records: list[dict[str, Any]], config: dict[str, Any], result_dir: Path,
) -> list[Path]:
    """Export two PNG/SVG figures and captions/provenance metadata into a new run.

Input records remain unchanged. A missing seed breaks the summary curve; valid
remaining seed dots stay visible. Incomplete-cohort and undefined results are
listed in metadata, not silently promoted into full-cohort acceptance evidence.
"""

    if not records or not result_dir.is_dir():
        raise ValueError("figures require case records and an existing results directory")
    residual = prepare_comparison_series(records, config, stage="residual_scan")
    panels = [{"residual_sigma_m_per_s": sigma, "series": {
        arm: prepare_comparison_series(records, config, stage="width_scan", arm=arm, residual_sigma_m_per_s=sigma)
        for arm in ARM_STYLE}} for sigma in config["width_scan"]["residual_sigma_m_per_s"]]
    caption_scope = (
        "Synthetic uniform axial sources with prescribed velocity correlation and independent Gaussian residuals. "
        f"N={config['sampling']['particle_count']} mother particles per seed; {config['sampling']['replicate_count']} seeds per point. "
        "Exact one-dimensional pulse-relative TOF and canonical direct mass FWHM determine R. "
        "Geometry, source IDs and accelerator fields stay fixed in retuning; only the two mirror fields change. "
        "Two-/three-zone width curves use matched mirrors, common outer geometry and the declared field contrast. "
        "Dots are source-seed results, lines connect medians only at complete points, and bars show min–max ranges, not confidence intervals. "
        "No smoothing, interpolation, fitted curve, selected best seed, new metric calculation, or common-hit intersection. "
        "Missing/ineligible points break lines and are marked at the axis edge. No 3D collection, physical source-production, global-optimum or Formal claim."
    )
    with mpl.rc_context(STYLE):
        gain_figure, _ = build_residual_gain_figure(residual)
        width_figure, _ = build_width_resolution_figure(panels, minimum_resolution=config["width_scan"]["minimum_resolution"])
        outputs = _save_figure(gain_figure, result_dir, "residual-retuning__gain")
        outputs += _save_figure(width_figure, result_dir, "source-width__resolution")
    metadata = {
        "schema_version": 1, "role": "ideal_source_comparison_figure_metadata",
        "parent_run_id": result_dir.parent.name, "style_profile": "publication_double_183_mm_300_dpi",
        "figure_level": "run_evidence_pending_actual_size_review",
        "caption": caption_scope,
        "axes": {"residual_gain": "x symlog with linear threshold 1 m/s includes sigma=0; y symlog with linear threshold 1 percent keeps small positive/negative gains visible across orders of magnitude",
                 "width_resolution": "x linear mm; y log R, common range including declared threshold"},
        "units": {"residual_sigma": "m/s", "source_full_width": "mm", "resolution": "dimensionless", "resolution_gain": "%"},
        "resolution_threshold": config["width_scan"]["minimum_resolution"],
        "source": config["source"], "sampling": config["sampling"],
        "source_records": [{"case": record["case"], "numerical_identity": record.get("identity"),
                            "record_sha256": record.get("record_sha256"), "particles": record.get("particles"),
                            "counts": {arm: {key: values.get(key) for key in ("mother_particle_count", "detector_arrival_count", "classification_counts", "full_cohort_reachable")}
                                       for arm, values in record["arms"].items()}} for record in records],
        "plot_data": {"residual_gain": residual, "width_resolution": panels},
        "files": [{"path": path.name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in outputs],
        "provenance_authority": "Parent run_config and run_manifest freeze source contracts, code, git identity, inputs and these outputs.",
    }
    path = result_dir / "ideal-source-comparison__figures.json"
    if path.exists():
        raise FileExistsError(f"will not overwrite figure metadata: {path}")
    path.write_text(json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return outputs + [path]
