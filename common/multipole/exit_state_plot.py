"""Solver-neutral multipole exit-state diagnostic and comparison figures."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


NUMERIC_COLUMNS = (
    "axial_z_mm",
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
COMPARISON_COLORS = ("#0072B2", "#E69F00", "#009E73", "#D55E00", "#56B4E9", "#CC79A7", "#000000")
LINESTYLES = ("-", "--", "-.", ":")


@dataclass(frozen=True)
class ExitState:
    label: str
    source_path: Path
    source_sha256: str
    event: str
    statuses: tuple[str, ...]
    source_particle_count: int
    source_particle_ids: tuple[str, ...]
    selected_particle_ids: tuple[str, ...]
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
            selected_statuses = tuple(sorted({row["status"] for row in selected}))
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
        source_particle_ids=tuple(sorted(source_ids)),
        selected_particle_ids=tuple(sorted(selected_particle_ids)),
        values=values,
    )


def _expanded_range(
    values: Iterable[np.ndarray], *, symmetric: bool = False, nonnegative: bool = False
) -> tuple[float, float]:
    pooled = np.concatenate(tuple(values))
    low, high = float(np.min(pooled)), float(np.max(pooled))
    if nonnegative:
        if low < 0:
            raise ValueError("Nonnegative exit-state quantity contains a negative value.")
        return (0.0, 1.05 * high if high > 0 else 1.0)
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
        low, high = _expanded_range(
            [state.values[column] for state in states],
            nonnegative=column in {"radial_position_mm", "divergence_angle_deg"},
        )
        histograms[column] = np.linspace(low, high, bin_count + 1)
    return {
        "transverse_mm": transverse,
        "histogram_edges": histograms,
        "radial_vs_divergence": {
            "x": _expanded_range([s.values["radial_position_mm"] for s in states], nonnegative=True),
            "y": _expanded_range([s.values["divergence_angle_deg"] for s in states], nonnegative=True),
        },
    }


def validate_comparison_states(
    states: Sequence[ExitState], *, require_paired_ids: bool = False
) -> dict:
    if not states:
        raise ValueError("At least one exit-state series is required.")
    labels = [state.label for state in states]
    if any(not label for label in labels) or len(set(labels)) != len(labels):
        raise ValueError("Comparison series labels must be non-empty and unique.")
    reference = states[0]
    planes = []
    for state in states:
        unique_planes = np.unique(state.values["axial_z_mm"])
        if len(unique_planes) != 1:
            raise ValueError(f"Comparison series {state.label} spans multiple axial planes.")
        planes.append(float(unique_planes[0]))
    if any(plane != planes[0] for plane in planes[1:]):
        raise ValueError("Comparison series select different axial planes.")
    requirements = (
        ("event", "events"),
        ("statuses", "statuses"),
        ("source_particle_ids", "source particle-ID cohorts"),
    )
    for state in states[1:]:
        for attribute, label in requirements:
            if getattr(state, attribute) != getattr(reference, attribute):
                raise ValueError(f"Comparison series use different {label}.")
        if require_paired_ids and state.selected_particle_ids != reference.selected_particle_ids:
            raise ValueError("Paired comparison series use different selected particle IDs.")
    return {
        "event": reference.event,
        "statuses": list(reference.statuses),
        "source_particle_ids": list(reference.source_particle_ids),
        "selected_axial_z_mm": planes[0],
        "paired_particle_ids_required": require_paired_ids,
        "selected_particle_ids": list(reference.selected_particle_ids) if require_paired_ids else None,
    }


def prepare_shared_scale_contract(
    states: Sequence[ExitState],
    *,
    bin_count: int = 24,
    require_paired_ids: bool = False,
) -> dict:
    labels = sorted(state.label for state in states)
    styles = {
        label: {
            "color": COMPARISON_COLORS[index % len(COMPARISON_COLORS)],
            "linestyle": LINESTYLES[
                (index // len(COMPARISON_COLORS)) % len(LINESTYLES)
            ],
        }
        for index, label in enumerate(labels)
    }
    scales = prepare_scales(states, bin_count=bin_count)
    return {
        "comparison": validate_comparison_states(states, require_paired_ids=require_paired_ids),
        "bin_count": bin_count,
        "shared_scales": {
            "histogram_edges": {
                key: value.tolist() for key, value in scales["histogram_edges"].items()
            }
        },
        "style_map": styles,
    }


def validate_shared_scale_contract(
    contract: dict,
    states: Sequence[ExitState],
) -> None:
    styles = contract.get("style_map")
    bin_count = contract.get("bin_count")
    scales = contract.get("shared_scales")
    edges_by_column = scales.get("histogram_edges") if isinstance(scales, dict) else None
    comparison = contract.get("comparison")
    if (
        not isinstance(styles, dict)
        or not isinstance(bin_count, int)
        or bin_count < 2
        or not isinstance(edges_by_column, dict)
        or not isinstance(comparison, dict)
    ):
        raise ValueError("Shared scale contract is invalid.")
    unknown = sorted({state.label for state in states}.difference(styles))
    if unknown:
        raise ValueError(
            "Comparison series are absent from the shared scale contract: "
            + ", ".join(unknown)
        )
    active_styles = []
    for state in states:
        style = styles[state.label]
        if (
            not isinstance(style, dict)
            or set(style) != {"color", "linestyle"}
            or not matplotlib.colors.is_color_like(style["color"])
            or style["linestyle"] not in LINESTYLES
        ):
            raise ValueError(f"Shared scale contract style is invalid for {state.label}.")
        active_styles.append((style["color"], style["linestyle"]))
    if len(set(active_styles)) != len(active_styles):
        raise ValueError("Active comparison series must use unique styles.")
    observed = validate_comparison_states(
        states,
        require_paired_ids=bool(comparison.get("paired_particle_ids_required")),
    )
    for key in (
        "event",
        "statuses",
        "source_particle_ids",
        "selected_axial_z_mm",
        "paired_particle_ids_required",
        "selected_particle_ids",
    ):
        if observed[key] != comparison.get(key):
            raise ValueError(f"Comparison series differ from scale-contract {key}.")
    for column, _ in HISTOGRAMS:
        edges = np.asarray(edges_by_column.get(column, ()), dtype=float)
        nonnegative = column in {"radial_position_mm", "divergence_angle_deg"}
        if (
            len(edges) != bin_count + 1
            or not np.isfinite(edges).all()
            or not np.all(np.diff(edges) > 0)
            or (nonnegative and edges[0] != 0.0)
        ):
            raise ValueError(f"Shared scale contract edges are invalid for {column}.")
        for state in states:
            values = state.values[column]
            if float(np.min(values)) < edges[0] or float(np.max(values)) > edges[-1]:
                raise ValueError(
                    f"Comparison series {state.label} exceeds shared edges for {column}."
                )


def _plot_histograms(
    axes: Iterable[plt.Axes],
    states: Sequence[ExitState],
    edges_by_column: dict,
    styles: dict | None = None,
) -> None:
    for axis, (column, xlabel) in zip(axes, HISTOGRAMS, strict=True):
        edges = np.asarray(edges_by_column[column], dtype=float)
        for index, state in enumerate(states):
            style = styles[state.label] if styles else {
                "color": COLORS[index % len(COLORS)],
                "linestyle": "-",
            }
            label = state.label
            if styles:
                label += f" (N={state.selected_count}/{state.source_particle_count})"
            axis.hist(
                state.values[column],
                bins=edges,
                weights=np.full(state.selected_count, 1.0 / state.selected_count),
                histtype="step",
                linewidth=1.6,
                label=label,
                **style,
            )
        axis.set(xlabel=xlabel, ylabel="Selected-cohort probability per fixed bin")
        axis.set_xlim(float(edges[0]), float(edges[-1]))


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

    _plot_histograms(
        (axes[0, 1], axes[0, 2], axes[1, 0], axes[1, 1]),
        states,
        scales["histogram_edges"],
    )

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


def render_four_domain_comparison(
    states: Sequence[ExitState],
    scale_contract: dict,
    title: str,
) -> tuple[plt.Figure, np.ndarray]:
    validate_shared_scale_contract(scale_contract, states)
    scales = scale_contract["shared_scales"]
    styles = scale_contract["style_map"]
    figure, axes = plt.subplots(2, 2, figsize=(8.0, 6.4))
    _plot_histograms(axes.flat, states, scales["histogram_edges"], styles)
    for axis in axes.flat:
        axis.grid(True, alpha=0.22)
    for axis in axes[:, 1]:
        axis.set_ylabel("")
    figure.tight_layout(rect=(0.0, 0.0, 1.0, 0.86))
    handles, labels = axes[0, 0].get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.93),
        ncol=min(3, len(labels)),
        fontsize=8,
    )
    figure.suptitle(title, y=0.99)
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


def _series_manifest(
    states: Sequence[ExitState],
    run_ids: Sequence[str | None] | None,
) -> list[dict]:
    resolved_run_ids = run_ids or [None] * len(states)
    return [
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
                "excluded_particle_count": (
                    state.source_particle_count - state.selected_count
                ),
                "invalid_selected_count": 0,
            },
        }
        for state, run_id in zip(states, resolved_run_ids, strict=True)
    ]


def _replace_path(source: Path, destination: Path) -> None:
    """Narrow atomic-replace seam used by transactional publication tests."""

    os.replace(source, destination)


def _publish_figure(
    figure: plt.Figure, output: Path, manifest: Path, dpi: int, document: dict
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    temporary_output = output.with_name(f".{output.stem}.{token}.tmp{output.suffix}")
    temporary_manifest = manifest.with_name(f".{manifest.name}.{token}.tmp")
    backups: dict[Path, Path] = {}
    installed: list[Path] = []
    committed = False
    try:
        figure.savefig(temporary_output, format=output.suffix.lstrip("."), dpi=dpi, facecolor="white")
        plt.imread(temporary_output)
        document["figure"]["sha256"] = sha256_file(temporary_output)
        temporary_manifest.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        for target in (output, manifest):
            if target.exists():
                backup = target.with_name(f".{target.name}.{token}.backup")
                _replace_path(target, backup)
                backups[target] = backup
        for temporary, target in ((temporary_output, output), (temporary_manifest, manifest)):
            _replace_path(temporary, target)
            installed.append(target)
        committed = True
    except Exception:
        for target in reversed(installed):
            target.unlink(missing_ok=True)
        for target, backup in backups.items():
            if backup.exists():
                _replace_path(backup, target)
        raise
    finally:
        plt.close(figure)
        temporary_output.unlink(missing_ok=True)
        temporary_manifest.unlink(missing_ok=True)
        if committed:
            for backup in backups.values():
                backup.unlink(missing_ok=True)


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
    scale_contract: dict | None = None,
) -> dict:
    if dpi < 180:
        raise ValueError("Diagnostic PNG DPI must be at least 180.")
    output = output.resolve()
    manifest = manifest.resolve()
    if output == manifest:
        raise ValueError("Figure output and manifest paths must differ.")
    series = _series_manifest(states, run_ids)
    if scale_contract is None:
        scales = prepare_scales(states, bin_count=bin_count)
        figure, _ = render_exit_state_figure(states, scales, title)
        shared_scales = _jsonable_scales(scales)
        figure_size = [12.0, 7.2]
    else:
        validate_shared_scale_contract(scale_contract, states)
        figure, _ = render_four_domain_comparison(states, scale_contract, title)
        shared_scales = scale_contract["shared_scales"]
        bin_count = scale_contract["bin_count"]
        figure_size = [8.0, 6.4]
    document = {
        "schema_version": 1,
        "role": "multipole_exit_state_figure_manifest",
        "purpose": purpose,
        "figure": {
            "path": str(output),
            "sha256": None,
            "format": output.suffix.lstrip(".").upper(),
            "size_inches": figure_size,
            "dpi": dpi,
        },
        "git": _git_identity(repo_root),
        "units": {"position": "mm", "divergence_angle": "deg", "kinetic_energy": "eV", "elapsed_time": "us"},
        "filtering": "No outlier clipping or display subsampling; solver-neutral exit-event preference is frozen.",
        "normalization": "Each histogram is conditional on its selected cohort and sums to one per series.",
        "claim_limit": (
            "This figure validates CSV-level event, status, particle-ID cohort, and axial-plane consistency only; "
            "source, design, coordinate-frame, time-origin, and physical equivalence remain batch-contract duties."
        ),
        "bin_count": bin_count,
        "shared_scales": shared_scales,
        "series": series,
        "random_selection": None,
        "fitting": None,
        "uncertainty": None,
    }
    if scale_contract is not None:
        document["layout"] = "four_domain_fixed_bin_comparison"
        document["comparison"] = scale_contract["comparison"]
        document["style_map"] = scale_contract["style_map"]
    _publish_figure(figure, output, manifest, dpi, document)
    return document


def export_four_domain_figure(
    states: Sequence[ExitState],
    output: Path,
    manifest: Path,
    title: str,
    purpose: str,
    *,
    scale_contract: dict,
    dpi: int = 200,
    repo_root: Path | None = None,
    run_ids: Sequence[str | None] | None = None,
) -> dict:
    return export_figure(
        states, output, manifest, title, purpose,
        dpi=dpi,
        repo_root=repo_root,
        run_ids=run_ids,
        scale_contract=scale_contract,
    )


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
