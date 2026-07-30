"""Solver-neutral multipole exit-state diagnostic and comparison figures."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


NUMERIC_COLUMNS = (
    "transverse_x_mm",
    "transverse_y_mm",
    "radial_position_mm",
    "divergence_angle_deg",
    "kinetic_energy_eV",
    "elapsed_time_us",
)
EVENT_PREFERENCE = (
    ("handoff", ("transmitted",)),
    ("rod_exit", ("alive", "transmitted")),
    ("terminal", ("transmitted",)),
)
HISTOGRAMS = (
    ("radial_position_mm", "Radial position (mm)"),
    ("divergence_angle_deg", "Divergence angle (deg)"),
    ("kinetic_energy_eV", "Kinetic energy (eV)"),
    ("elapsed_time_us", "Elapsed time (us)"),
)
COLORS = ("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00")
MARKERS = ("o", "s", "^", "D", "v")


@dataclass(frozen=True)
class ExitState:
    label: str
    source_path: Path
    source_sha256: str
    event: str
    statuses: tuple[str, ...]
    source_particle_count: int
    values: dict[str, np.ndarray]

    @property
    def selected_count(self) -> int:
        return len(self.values["transverse_x_mm"])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_exit_state(path: Path, label: str) -> ExitState:
    path = path.resolve()
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError(f"Canonical particle-state table is empty: {path}")
    required = {"particle_id", "event", "status", *NUMERIC_COLUMNS}
    missing = sorted(required.difference(rows[0]))
    if missing:
        raise ValueError(f"Canonical particle-state table is missing columns: {missing}")
    source_particle_ids = [
        row["particle_id"] for row in rows if row["event"] == "source"
    ]
    source_ids = set(source_particle_ids)
    if not source_ids:
        raise ValueError("Canonical particle-state table has no source rows.")
    if "" in source_ids or len(source_ids) != len(source_particle_ids):
        raise ValueError("Canonical particle-state source particle IDs are invalid.")
    selected: list[dict[str, str]] = []
    selected_event = ""
    selected_statuses: tuple[str, ...] = ()
    for event, statuses in EVENT_PREFERENCE:
        selected = [
            row for row in rows if row["event"] == event and row["status"] in statuses
        ]
        if selected:
            selected_event = event
            selected_statuses = statuses
            break
    if not selected:
        raise ValueError("No supported transmitted exit-state rows were found.")
    selected_particle_ids = [row["particle_id"] for row in selected]
    if (
        "" in selected_particle_ids
        or len(set(selected_particle_ids)) != len(selected_particle_ids)
    ):
        raise ValueError("Selected exit-state particle IDs are invalid or duplicated.")
    unknown_particle_ids = sorted(set(selected_particle_ids) - source_ids)
    if unknown_particle_ids:
        raise ValueError(
            "Selected exit-state particle IDs do not belong to the source: "
            + ", ".join(unknown_particle_ids[:5])
        )
    values = {
        column: np.asarray([float(row[column]) for row in selected], dtype=float)
        for column in NUMERIC_COLUMNS
    }
    for column, value in values.items():
        if not np.isfinite(value).all():
            raise ValueError(f"Selected exit-state column contains NaN/Inf: {column}")
    return ExitState(
        label=label,
        source_path=path,
        source_sha256=sha256_file(path),
        event=selected_event,
        statuses=selected_statuses,
        source_particle_count=len(source_ids),
        values=values,
    )


def _expanded_range(values: Iterable[np.ndarray], *, symmetric: bool = False) -> tuple[float, float]:
    pooled = np.concatenate(tuple(values))
    low, high = float(np.min(pooled)), float(np.max(pooled))
    if symmetric:
        bound = max(abs(low), abs(high))
        bound = bound if bound > 0 else 1.0
        return (-1.05 * bound, 1.05 * bound)
    width = high - low
    padding = 0.05 * width if width > 0 else max(abs(low) * 0.05, 0.5)
    return (low - padding, high + padding)


def prepare_scales(states: Sequence[ExitState], bin_count: int = 24) -> dict:
    if not states:
        raise ValueError("At least one exit-state series is required.")
    if bin_count < 2:
        raise ValueError("bin_count must be at least 2.")
    transverse = _expanded_range(
        [
            state.values[column]
            for state in states
            for column in ("transverse_x_mm", "transverse_y_mm")
        ],
        symmetric=True,
    )
    histograms = {}
    for column, _ in HISTOGRAMS:
        low, high = _expanded_range([state.values[column] for state in states])
        histograms[column] = np.linspace(low, high, bin_count + 1)
    return {
        "transverse_mm": transverse,
        "histogram_edges": histograms,
        "radial_vs_divergence": {
            "x": _expanded_range([s.values["radial_position_mm"] for s in states]),
            "y": _expanded_range([s.values["divergence_angle_deg"] for s in states]),
        },
    }


def render_exit_state_figure(
    states: Sequence[ExitState], scales: dict, title: str
) -> tuple[plt.Figure, np.ndarray]:
    figure, axes = plt.subplots(2, 3, figsize=(12.0, 7.2), constrained_layout=True)
    xy = axes[0, 0]
    for index, state in enumerate(states):
        xy.scatter(
            state.values["transverse_x_mm"],
            state.values["transverse_y_mm"],
            s=18,
            alpha=0.72,
            color=COLORS[index % len(COLORS)],
            marker=MARKERS[index % len(MARKERS)],
            label=f"{state.label} (N={state.selected_count})",
        )
    xy.set(xlabel="Transverse x (mm)", ylabel="Transverse y (mm)")
    xy.set_xlim(scales["transverse_mm"])
    xy.set_ylim(scales["transverse_mm"])
    xy.set_aspect("equal", adjustable="box")
    xy.legend(fontsize=8)

    histogram_axes = (axes[0, 1], axes[0, 2], axes[1, 0], axes[1, 1])
    for axis, (column, xlabel) in zip(histogram_axes, HISTOGRAMS, strict=True):
        edges = scales["histogram_edges"][column]
        for index, state in enumerate(states):
            weights = np.full(state.selected_count, 1.0 / state.selected_count)
            axis.hist(
                state.values[column],
                bins=edges,
                weights=weights,
                histtype="step",
                linewidth=1.6,
                color=COLORS[index % len(COLORS)],
                label=state.label,
            )
        axis.set(xlabel=xlabel, ylabel="Probability per fixed bin")
        axis.set_xlim(float(edges[0]), float(edges[-1]))

    correlation = axes[1, 2]
    for index, state in enumerate(states):
        correlation.scatter(
            state.values["radial_position_mm"],
            state.values["divergence_angle_deg"],
            s=18,
            alpha=0.72,
            color=COLORS[index % len(COLORS)],
            marker=MARKERS[index % len(MARKERS)],
            label=state.label,
        )
    correlation.set(xlabel="Radial position (mm)", ylabel="Divergence angle (deg)")
    correlation.set_xlim(scales["radial_vs_divergence"]["x"])
    correlation.set_ylim(scales["radial_vs_divergence"]["y"])
    for axis in axes.flat:
        axis.grid(True, alpha=0.22)
    figure.suptitle(title)
    return figure, axes


def _git_identity(repo_root: Path | None) -> dict:
    if repo_root is None:
        return {"commit": None, "working_tree": "unknown"}
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        return {"commit": commit, "working_tree": "dirty" if dirty else "clean"}
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return {"commit": None, "working_tree": "unknown"}


def _jsonable_scales(scales: dict) -> dict:
    return {
        "transverse_mm": list(scales["transverse_mm"]),
        "histogram_edges": {
            key: value.tolist() for key, value in scales["histogram_edges"].items()
        },
        "radial_vs_divergence": {
            key: list(value) for key, value in scales["radial_vs_divergence"].items()
        },
    }


def export_figure(
    states: Sequence[ExitState],
    output: Path,
    manifest: Path,
    title: str,
    purpose: str,
    *,
    bin_count: int = 24,
    dpi: int = 200,
    repo_root: Path | None = None,
    run_ids: Sequence[str | None] | None = None,
) -> dict:
    if dpi < 180:
        raise ValueError("Diagnostic PNG DPI must be at least 180.")
    scales = prepare_scales(states, bin_count=bin_count)
    figure, _ = render_exit_state_figure(states, scales, title)
    output = output.resolve()
    manifest = manifest.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_name(f".{output.stem}.tmp{output.suffix}")
    try:
        figure.savefig(
            temporary_output,
            format=output.suffix.lstrip("."),
            dpi=dpi,
            facecolor="white",
        )
        plt.imread(temporary_output)
        os.replace(temporary_output, output)
    finally:
        plt.close(figure)
        temporary_output.unlink(missing_ok=True)
    run_ids = run_ids or [None] * len(states)
    series = []
    for state, run_id in zip(states, run_ids, strict=True):
        series.append(
            {
                "label": state.label,
                "run_id": run_id,
                "canonical_state": {
                    "path": str(state.source_path),
                    "sha256": state.source_sha256,
                },
                "selection": {
                    "event": state.event,
                    "statuses": list(state.statuses),
                    "source_particle_count": state.source_particle_count,
                    "selected_particle_count": state.selected_count,
                    "excluded_particle_count": state.source_particle_count
                    - state.selected_count,
                    "invalid_selected_count": 0,
                },
            }
        )
    document = {
        "schema_version": 1,
        "role": "multipole_exit_state_figure_manifest",
        "purpose": purpose,
        "figure": {
            "path": str(output),
            "sha256": sha256_file(output),
            "format": output.suffix.lstrip(".").upper(),
            "size_inches": [12.0, 7.2],
            "dpi": dpi,
        },
        "git": _git_identity(repo_root),
        "coordinate_frame": "multipole local frame; axial z, transverse x/y",
        "time_origin": "elapsed_time_us is measured from each particle source event",
        "units": {
            "position": "mm",
            "divergence_angle": "deg",
            "kinetic_energy": "eV",
            "elapsed_time": "us",
        },
        "filtering": "No outlier clipping or display subsampling; solver-neutral exit-event preference is frozen.",
        "normalization": "Each one-dimensional histogram is probability per fixed bin and sums to one per series.",
        "bin_count": bin_count,
        "shared_scales": _jsonable_scales(scales),
        "series": series,
        "random_selection": None,
        "fitting": None,
        "uncertainty": None,
    }
    temporary_manifest = manifest.with_name(f".{manifest.name}.tmp")
    temporary_manifest.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(temporary_manifest, manifest)
    return document


def _series_argument(value: str) -> tuple[str, Path, str | None]:
    parts = value.split("=", 2)
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise argparse.ArgumentTypeError("series must be LABEL=PATH or LABEL=PATH=RUN_ID")
    return parts[0], Path(parts[1]), parts[2] if len(parts) == 3 else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--series", action="append", type=_series_argument, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--purpose", required=True)
    parser.add_argument("--bin-count", type=int, default=24)
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--repo-root", type=Path)
    arguments = parser.parse_args()
    states = [load_exit_state(path, label) for label, path, _ in arguments.series]
    export_figure(
        states,
        arguments.output,
        arguments.manifest,
        arguments.title,
        arguments.purpose,
        bin_count=arguments.bin_count,
        dpi=arguments.dpi,
        repo_root=arguments.repo_root,
        run_ids=[run_id for _, _, run_id in arguments.series],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
