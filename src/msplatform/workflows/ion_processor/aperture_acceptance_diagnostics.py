"""Hypothetical thin circular apertures applied to recorded z=0 exit states.

Pure, field-free postprocessing: no solver, electrode, collision or trajectory
modification. A hole selects position at its plane, not angle directly.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from matplotlib.figure import Figure


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _contract(contract: dict) -> dict:
    required = {"drift_lengths_mm", "aperture_radii_mm", "center_x_mm", "center_y_mm"}
    if set(contract) != required:
        raise ValueError("aperture contract requires exactly the four documented fields")
    result = {key: _number(contract[key], key) for key in ("center_x_mm", "center_y_mm")}
    for key in ("drift_lengths_mm", "aperture_radii_mm"):
        raw = contract[key]
        if not isinstance(raw, (list, tuple)) or not raw:
            raise ValueError(f"{key} must be a nonempty sequence")
        values = [_number(value, key) for value in raw]
        if len(set(values)) != len(values) or any(value < 0 for value in values):
            raise ValueError(f"{key} must contain unique nonnegative values")
        result[key] = values
    return result


def _exits(case: dict) -> tuple[list[int], dict[int, dict]]:
    mother, declared = set(case["sources"]), set(case["exits"])
    if not declared <= mother:
        raise ValueError("exit IDs must belong to the mother population")
    measured = {}
    fields = ("x_mm", "y_mm", "z_mm", "t_us", "vx_mm_us", "vy_mm_us", "vz_mm_us", "total_energy_eV")
    for raw in case["states"]:
        if raw.get("plane_z_mm") != 0 or raw.get("status") not in {"alive", "extracted"}:
            continue
        pid = raw["particle_id"]
        if pid not in declared or pid in measured:
            raise ValueError("unknown or duplicate valid z=0 exit state")
        row = {key: _number(raw[key], key) for key in fields}
        if row["z_mm"] != 0 or row["vz_mm_us"] >= 0 or row["total_energy_eV"] < 0:
            raise ValueError("exit states require z=0, negative vz and nonnegative kinetic energy")
        measured[pid] = row
    if set(measured) != declared:
        raise ValueError("every declared exit requires one valid recorded z=0 state")
    return sorted(mother), measured


def _widths(rows: list[dict]) -> dict:
    result = dict(sigma_theta_x_deg=None, sigma_theta_y_deg=None, sigma_t_ns=None,
                  central90_time_ns=None, sigma_total_energy_eV=None)
    if len(rows) < 2:
        return result
    for axis in "xy":
        angles = [math.degrees(math.atan2(row[f"v{axis}_mm_us"], abs(row["vz_mm_us"]))) for row in rows]
        result[f"sigma_theta_{axis}_deg"] = float(np.std(angles, ddof=0))
    times = np.array([row["t_us"] for row in rows])
    result.update(sigma_t_ns=float(times.std(ddof=0)*1000),
                  central90_time_ns=float(np.diff(np.quantile(times, [.05, .95], method="linear"))[0]*1000),
                  sigma_total_energy_eV=float(np.std([row["total_energy_eV"] for row in rows], ddof=0)))
    return result


def prepare_aperture_diagnostics(exit_cases: list[dict], contract: dict) -> dict:
    """Return all-ID aperture decisions, transmission denominators and widths.

    Cases are existing spatial-crossing cases with ``label``, ``sources``,
    ``exits`` and ``states``. Every declared exit must have exactly one valid
    z=0 crossing with finite mm, us, mm/us and total_energy_eV fields. Source IDs
    absent from exits remain explicitly ``upstream_not_extracted``. Each L has
    an unfiltered reference (radius None), including its predicted arrival times.
    Radius zero is an explicit point aperture; the geometric boundary is closed.
    """
    specification = _contract(contract)
    labels = [case["label"] for case in exit_cases]
    if not labels or len(set(labels)) != len(labels):
        raise ValueError("cases must have nonempty unique labels")
    statistics, decisions = [], []
    for case in exit_cases:
        mother, exits = _exits(case)
        for length in specification["drift_lengths_mm"]:
            predicted = {}
            for pid, source in exits.items():
                dt = length/abs(source["vz_mm_us"])
                row = dict(source, x_mm=source["x_mm"]+dt*source["vx_mm_us"],
                           y_mm=source["y_mm"]+dt*source["vy_mm_us"],
                           z_mm=-length, t_us=source["t_us"]+dt)
                if not all(math.isfinite(value) for value in row.values()):
                    raise ValueError("nonfinite field-free prediction")
                predicted[pid] = row
            for radius in (None, *specification["aperture_radii_mm"]):
                accepted = []
                for pid in mother:
                    row = predicted.get(pid)
                    radial = math.hypot(row["x_mm"]-specification["center_x_mm"],
                                        row["y_mm"]-specification["center_y_mm"]) if row else None
                    keep = row is not None and (radius is None or radial <= radius)
                    if keep:
                        accepted.append(pid)
                    particle = dict(case=case["label"], drift_length_mm=length,
                        aperture_radius_mm=radius, particle_id=pid,
                        status="upstream_not_extracted" if row is None else "accepted" if keep else "aperture_rejected",
                        radial_distance_mm=radial)
                    for key in ("x_mm", "y_mm", "z_mm", "t_us", "vx_mm_us", "vy_mm_us", "vz_mm_us", "total_energy_eV"):
                        particle[f"original_{key}"] = exits[pid][key] if row else None
                        particle[f"predicted_{key}"] = row[key] if row else None
                    decisions.append(particle)
                rejected = sorted(set(exits)-set(accepted))
                statistics.append(dict(case=case["label"], drift_length_mm=length,
                    aperture_radius_mm=radius, unfiltered_reference=radius is None,
                    mother_count=len(mother), exit_count=len(exits), accepted_count=len(accepted),
                    rejected_exit_count=len(rejected), upstream_not_extracted_count=len(mother)-len(exits),
                    transmission_mother=len(accepted)/len(mother) if mother else None,
                    transmission_exit=len(accepted)/len(exits) if exits else None,
                    accepted_ids=accepted, rejected_exit_ids=rejected,
                    upstream_not_extracted_ids=sorted(set(mother)-set(exits)),
                    **_widths([predicted[pid] for pid in accepted])))
    return dict(schema_version=1, role="hypothetical_aperture_acceptance", contract=specification, case_order=labels,
        summary_rows=[row for row in statistics if not row["unfiltered_reference"]],
        reference_rows=[row for row in statistics if row["unfiltered_reference"]], particle_rows=decisions,
        metadata=dict(scope="Hypothetical thin circular aperture in a field-free straight drift from recorded z=0 states; no physical aperture simulation or MRTOF qualification.",
            selection="Position at the aperture plane; not a direct angle cut. Independent single-aperture alternatives, not serial apertures. Boundary included without added tolerance.",
            time="Absolute recorded t_us plus L/abs(vz); no recentering or source-time decorrelation.",
            moments="Population SD (ddof=0), all retained IDs and tails. Widths null for N<2. Central90 uses linear 95th minus 5th percentiles, not FWHM.",
            reference="Unfiltered exit population at every drift length, with upstream non-exits retained in mother denominator.",
            energy="Recorded total_energy_eV retained unchanged in field-free drift; aperture does not cool individual ions."))


def build_aperture_figure(prepared: dict) -> Figure:
    """Return an English full-range transmission/width figure; no save or show."""
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    labels = prepared["case_order"]
    fig, axes = plt.subplots(len(labels), 4, figsize=(17, 3.1*len(labels)+2),
                             squeeze=False, sharex=True, sharey="col")
    metrics = (("sigma_theta_x_deg", "SD theta x (deg)"), ("sigma_theta_y_deg", "SD theta y (deg)"),
               ("sigma_t_ns", "Arrival-time SD (ns)"), ("central90_time_ns", "Central 90% arrival-time width (ns)"))
    colors = plt.get_cmap("tab10")
    lengths = prepared["contract"]["drift_lengths_mm"]
    markers = ("o", "s", "^", "D", "v", "P", "X")
    styles = ("-", "--", "-.", ":", (0, (5, 1, 1, 1)), (0, (1, 1, 3, 1)))
    for index, label in enumerate(labels):
        for ax, (metric, ylabel) in zip(axes[index], metrics):
            for j, length in enumerate(lengths):
                rows = [row for row in prepared["summary_rows"]+prepared["reference_rows"] if row["case"] == label and row["drift_length_mm"] == length]
                selected = sorted((row for row in rows if not row["unfiltered_reference"]), key=lambda row: row["aperture_radius_mm"])
                valid = [row for row in selected if row[metric] is not None and row["transmission_mother"] is not None]
                # Radius order is retained: repeated transmission can have distinct widths.
                ax.plot([100*row["transmission_mother"] for row in valid], [row[metric] for row in valid],
                        color=colors(index % 10), marker=markers[j % len(markers)],
                        linestyle=styles[j % len(styles)], linewidth=.9, markersize=4)
                reference = next(row for row in rows if row["unfiltered_reference"])
                if reference[metric] is not None and reference["transmission_mother"] is not None:
                    ax.scatter([100*reference["transmission_mother"]], [reference[metric]], marker=markers[j % len(markers)],
                               edgecolors=[colors(index % 10)], facecolors="none", s=85, linewidths=1.3)
            ax.set(xlabel="Transmission / mother (%)", ylabel=ylabel, xlim=(0, 100), title=label)
            ax.grid(alpha=.2)
    legend = [Line2D([], [], color="black", marker=markers[j % len(markers)], linestyle=styles[j % len(styles)], label=f"L = {length:g} mm") for j, length in enumerate(lengths)]
    legend += [Line2D([], [], color="black", marker="o", markerfacecolor="none", linestyle="none", label="Unfiltered exit reference")]
    fig.legend(handles=legend, loc="lower center", ncol=4, fontsize=9, frameon=False)
    radii = ", ".join(f"{value:g}" for value in prepared["contract"]["aperture_radii_mm"])
    center = prepared["contract"]
    fig.suptitle("Hypothetical single circular aperture | Field-free prediction, no field modification\n"
                 f"Radii: {radii} mm; center ({center['center_x_mm']:g}, {center['center_y_mm']:g}) mm | "
                 "All tails; N < 2 widths undefined\nPoints joined in increasing radius; exact per-radius results in summary table; hollow markers = unfiltered reference", fontsize=11)
    fig.tight_layout(rect=(0, .08, 1, .90))
    return fig
