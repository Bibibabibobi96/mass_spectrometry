"""Default measured-source joint diagnostics from recorded states, without flight.

Population closure and event parsing reuse measured_component_analysis. Sparse
trajectory extraction reuses the existing trial adapter. Rendering never changes
states or qualifies old centre-point criteria as whole-cohort acceptance.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
from typing import Any

import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.patches import Rectangle

from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.measured_component_analysis import (
    _load_source, _log_roundoff_us, analyze_measured_component,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import _prism_phase_space_diagnostic
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import extract_trajectory_samples

COORDINATES = ("x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us")
COLORS = {"alive": "#0072B2", "detected": "#009E73", "loss": "#D55E00", "timeout": "#CC79A7"}
MARKERS = {"alive": "o", "detected": "s", "loss": "x", "timeout": "^"}
STAGES = ("p1_exit", "p2_fixed_plane")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_rows(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _bound(record: dict, base: Path) -> Path:
    verify_record("prepared diagnostic input", record, base_dir=base)
    return record_path(record, base_dir=base)


def _inputs(preparation: Path) -> tuple[dict, Path, dict, dict, list[dict], dict]:
    prepared = _read(preparation)
    if prepared.get("schema_version") != 1 or prepared.get("role") != "mrtof_prepared_joint_trial":
        raise ValueError("Unsupported prepared joint-trial receipt")
    source_path = _bound(prepared["source_receipt"], preparation.parent)
    source, states, census, _ = _load_source(source_path)
    if (set(prepared["expected_particle_ids"]) != set(states)
            or len(prepared["expected_particle_ids"]) != len(states)
            or prepared["mother_particle_count"] != len(census)
            or prepared["solver_epoch_instrument_time_us"] != source["solver_epoch_instrument_time_us"]):
        raise ValueError("Prepared source ID/clock/mother census differs")
    contract_path = _bound(prepared["trajectory_contract"], preparation.parent)
    _bound(prepared["operating_point"], preparation.parent)
    contract = _read(contract_path)
    if contract["coordinate_system"]["frame_id"] != source["frame_id"]:
        raise ValueError("Diagnostic geometry and measured source frame differ")
    return prepared, source_path, source, states, census, contract


def _project_events(merged_log: Path, destination: Path) -> None:
    # Full trajectories can be GB-scale; the established event analyzer should
    # receive only its own compact event/completion protocol, not dense states.
    with merged_log.open(encoding="utf-8-sig") as source, destination.open("w", encoding="utf-8", newline="\n") as target:
        for line in source:
            if line.startswith("MRTOF_EVENT ") or line.startswith("status,Fly completed."):
                target.write(line)


def _prism_rows(events: list[dict], states: dict) -> list[dict]:
    rows, seen = [], set()
    for event_index, event in enumerate(events):
        if event["kind"] == "prism_pass" and event.get("n") == 1:
            stage = "p1_exit"
        elif event["kind"] == "p2_low_field_crossing":
            stage = "p2_fixed_plane"
        elif event["kind"] == "pre_origin_positive_mirror_turn":
            stage = "first_positive_turn"
        else:
            continue
        particle = int(event["ion"])
        source = states[particle]
        vx, vy, vz = (float(event[name]) for name in COORDINATES[3:])
        energy = {axis: kinetic_energy_ev(float(source["mass_amu"]), *(
            velocity * 1000 if other == axis else 0 for other, velocity in zip("xyz", (vx, vy, vz))
        )) / abs(int(source["charge_state"])) for axis in "xyz"}
        speed_yz = math.hypot(vy, vz)
        row = {"stage": stage, "particle_id": particle, "event_index": event_index,
               "first_recorded_crossing": int((stage, particle) not in seen), "instrument_time_us": event["t_us"],
               **{name: event[name] for name in COORDINATES},
               "signed_yz_angle_deg": math.degrees(math.atan2(vy, vz)) if speed_yz else "",
               "transverse_tilt_deg": math.degrees(math.atan2(vx, speed_yz)) if vx or speed_yz else "",
               "inside_aperture": event.get("inside_aperture", ""), "direction_ok": event.get("direction_ok", ""),
               "Ex_per_charge_eV": energy["x"], "Ey_per_charge_eV": energy["y"], "Ez_per_charge_eV": energy["z"],
               "K_per_charge_eV": sum(energy.values())}
        seen.add((stage, particle))
        rows.append(row)
    return rows


def _design_reference(prepared: dict, base: Path) -> dict:
    record = prepared.get("reference_materialization")
    if record is None:
        return dict(status="unavailable_no_bound_compatible_Mirror_Stripe_reference")
    value = _read(_bound(record, base))
    pointers = {"p2_target_tangent_ratio": "target_low_field_tangent_ratio_vy_over_vz",
                "p2_target_signed_angle_deg": "target_nominal_injection_angle_degrees",
                "positive_turn_target_y_mm": "target_positive_mirror_turn_y_mm"}
    result = {key: float(value[source]) for key, source in pointers.items()}
    if not all(math.isfinite(number) for number in result.values()):
        raise ValueError("Nonfinite frozen Prism design target")
    section = value["p2_low_field_reference_section"]
    result["p2_aperture"] = section["transit_aperture_project_mm"]
    result["p2_plane_z_mm"] = section["reference_plane_project_z_mm"]
    return dict(result, status="frozen_reference_differences_only", source=record,
                acceptance="not_applied_to_N100__old_centre_thresholds_not_reused")


def _prism_statistics(rows: list[dict], mother_ids: set[int]) -> dict:
    result = {}
    for stage in (*STAGES, "first_positive_turn"):
        selected = [row for row in rows if row["stage"] == stage and row["first_recorded_crossing"]]
        ids = {row["particle_id"] for row in selected}
        metrics = {}
        for key in ("x_mm", "y_mm", "z_mm", "Ex_per_charge_eV", "Ey_per_charge_eV", "Ez_per_charge_eV", "K_per_charge_eV",
                    "raw_signed_angle_difference_to_reference_deg", "positive_turn_y_difference_to_reference_mm"):
            values = [float(row[key]) for row in selected if row[key] != ""]
            metrics[key] = dict(count=len(values), mean=statistics.fmean(values) if values else None,
                                population_sigma=statistics.pstdev(values) if values else None,
                                minimum=min(values) if values else None, maximum=max(values) if values else None)
        angles = [math.radians(float(row["signed_yz_angle_deg"])) for row in selected if row["signed_yz_angle_deg"] != ""]
        circular_mean = math.degrees(math.atan2(statistics.fmean(math.sin(a) for a in angles),
                                               statistics.fmean(math.cos(a) for a in angles))) if angles else None
        result[stage] = dict(reached_count=len(ids), mother_count=len(mother_ids),
                            reached_particle_ids=sorted(ids), missing_mother_particle_ids=sorted(mother_ids-ids),
                            outside_aperture_ids=sorted(row["particle_id"] for row in selected if row["inside_aperture"] == 0),
                            direction_flagged_ids=sorted(row["particle_id"] for row in selected if row["direction_ok"] == 0),
                            nonpositive_vz_ids=sorted(row["particle_id"] for row in selected if row["vz_mm_us"] <= 0),
                            nonpositive_vy_ids=sorted(row["particle_id"] for row in selected if row["vy_mm_us"] <= 0),
                            signed_yz_circular_mean_deg=circular_mean,
                            angle_semantics="atan2(vy,vz); circular mean preserves the +/-180 degree branch", metrics=metrics)
    return result


def _validate_birth_clock_projection(source: dict, states: dict, base: Path) -> dict:
    """Verify explicit FLY2 TOBs and ordinal map against canonical handoff time."""
    map_path = _bound(source["outputs"]["ordinal_source_map"], base)
    fly_path = _bound(source["outputs"]["source"], base)
    mapping = _rows(map_path)
    tobs = [float(value) for value in re.findall(r"\btob\s*=\s*([^,]+),", fly_path.read_text(encoding="utf-8-sig"))]
    if len(mapping) != len(states) or len(tobs) != len(states):
        raise ValueError("FLY2 TOBs/ordinal map do not cover the measured source")
    epoch = source["solver_epoch_instrument_time_us"]
    identifiers = []
    for ordinal, (row, tob) in enumerate(zip(mapping, tobs), 1):
        particle = int(row["particle_id"])
        if particle not in states:
            raise ValueError("FLY2 map contains an unknown measured particle")
        absolute = float(states[particle]["instrument_time_us"])
        offset = absolute-epoch
        if (int(row["simion_ordinal"]) != ordinal or float(row["instrument_time_us"]) != absolute
                or float(row["solver_birth_time_us"]) != offset or tob != offset or offset < 0):
            raise ValueError("FLY2/ordinal birth offset differs from canonical instrument clock")
        identifiers.append(particle)
    if set(identifiers) != set(states):
        raise ValueError("FLY2 ordinal IDs do not close")
    return dict(epoch_us=epoch, fly2=file_record(fly_path), ordinal_map=file_record(map_path),
                verified_particle_count=len(states), policy="canonical_time_equals_epoch_plus_verified_per_particle_FLY2_TOB")


def _validate_completed_source_batches(prepared: dict, states: dict, base: Path) -> dict:
    """Bind actual launched FLY2 bytes, per-batch original IDs and their TOBs."""
    batches = prepared.get("completed_source_batches", [])
    if not batches:
        return dict(status="not_supplied", verified_particle_count=0)
    identifiers, evidence = [], []
    epoch = prepared["solver_epoch_instrument_time_us"]
    for batch in batches:
        receipt_path = _bound(batch["batch_receipt"], base)
        fly_path = _bound(batch["fly2"], base)
        _bound(batch["log"], base)
        receipt = _read(receipt_path)
        ids = receipt["original_particle_ids"]
        expected_fly = receipt["outputs"]["source"]
        if (receipt.get("schema_version") != 1 or receipt.get("role") != "mrtof_measured_source_batch"
                or receipt["count"] != len(ids) or receipt["solver_epoch_instrument_time_us"] != epoch
                or batch["fly2"]["sha256"].lower() != expected_fly["sha256"].lower()
                or batch["fly2"]["bytes"] != expected_fly["bytes"]):
            raise ValueError("Completed source batch or actual FLY2 identity differs")
        tobs = [float(value) for value in re.findall(r"\btob\s*=\s*([^,]+),", fly_path.read_text(encoding="utf-8-sig"))]
        if len(tobs) != len(ids) or any(particle not in states for particle in ids):
            raise ValueError("Actual launched FLY2 particle IDs do not close")
        for particle, tob in zip(ids, tobs):
            if tob != float(states[particle]["instrument_time_us"])-epoch:
                raise ValueError("Actual launched FLY2 TOB differs from canonical per-particle birth")
        identifiers.extend(ids)
        evidence.append(dict(batch_receipt=batch["batch_receipt"], fly2=batch["fly2"], log=batch["log"],
                             verified_particle_ids=ids, verified_birth_offsets_us=tobs))
    if len(identifiers) != len(states) or set(identifiers) != set(states):
        raise ValueError("Completed launched source batches duplicate or omit original IDs")
    return dict(status="verified_actual_launched_sources", verified_particle_count=len(states), batches=evidence)


def _trajectory_lifetimes(path: Path, states: dict, terminals: dict[int, dict], *, initialization_epoch_us: float | None = None) -> dict[int, dict]:
    lifetimes = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            particle = int(row["ion"])
            if particle not in states:
                raise ValueError("Unknown trajectory particle ID")
            if row["phase"] == "birth":
                expected = states[particle]
                actual = [float(row[key]) for key in ("t_us", *COORDINATES)]
                canonical = [float(expected["instrument_time_us"]),
                             *[float(expected[f"position_{axis}_mm"]) for axis in "xyz"],
                             *[float(expected[f"velocity_{axis}_m_s"])/1000 for axis in "xyz"]]
                if actual[1:] != canonical[1:]:
                    raise ValueError("Recorded trajectory birth differs from measured canonical 6D/absolute clock")
                projected = actual[0] != canonical[0]
                if projected and (initialization_epoch_us is None or actual[0] != initialization_epoch_us
                                  or canonical[0] < initialization_epoch_us):
                    raise ValueError("Recorded birth clock is neither canonical TOB nor verified initialize-phase solver zero")
                lifetimes[particle] = dict(birth=canonical[0], raw_birth_time_us=actual[0],
                    birth_clock_projected=projected, six_dimensional_state_exact=True,
                    birth_clock_semantics="initialize_engine_zero_before_TOB_application" if projected else "canonical_handoff_time",
                    subsequent_sample_count=0, first_subsequent_time_us=None)
            else:
                if float(row["t_us"]) < lifetimes[particle]["birth"]:
                    raise ValueError("Integrated trajectory sample precedes canonical per-particle TOB")
                lifetimes[particle]["subsequent_sample_count"] += 1
                if lifetimes[particle]["first_subsequent_time_us"] is None:
                    lifetimes[particle]["first_subsequent_time_us"] = float(row["t_us"])
            if row["phase"] == "terminal":
                lifetimes[particle].update(terminal=float(row["t_us"]), terminal_state={key: float(row[key]) for key in COORDINATES})
                for key in ("t_us", *COORDINATES):
                    actual, event = float(row[key]), float(terminals[particle][key])
                    # Event fields use %.12g, trajectory fields %.17g. This is
                    # their decimal serialization bound, not a physical gate.
                    if abs(actual-event) > _log_roundoff_us(actual)+math.ulp(actual):
                        raise ValueError("Trajectory terminal differs from the recorded terminal event")
    if set(lifetimes) != set(states) or any("terminal" not in row for row in lifetimes.values()):
        raise ValueError("Trajectory source/terminal IDs do not close")
    return lifetimes


def _snapshot_times(lifetimes: dict, events: list[dict]) -> list[dict]:
    start = min(row["birth"] for row in lifetimes.values())
    end = max(row["terminal"] for row in lifetimes.values())
    choices = [("First measured birth", start), ("Observed lifetime midpoint", (start+end)/2), ("Last terminal", end)]
    selectors = {
        "P1 exit median": lambda event: event["kind"] == "prism_pass" and event.get("n") == 1,
        "Negative pre-reflection median": lambda event: event["kind"] == "pre_injection_mirror_turn",
        "P2 raw plane median": lambda event: event["kind"] == "p2_low_field_crossing",
        "First positive-turn median": lambda event: event["kind"] == "pre_origin_positive_mirror_turn",
    }
    for label, select in selectors.items():
        times = [float(event["t_us"]) for event in events if select(event)]
        if times:
            time = statistics.median(times)
            if start <= time <= end:
                choices.append((label, time))
    return [{"label": label, "instrument_time_us": time} for label, time in sorted(set(choices), key=lambda item: item[1])]


def _snapshot_rows(path: Path, lifetimes: dict, census: list[dict], terminal_status: dict, times: list[dict]) -> tuple[list[dict], float]:
    interpolated, previous, maximum_gap = {}, {}, 0.0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            particle, time = int(raw["ion"]), float(raw["t_us"])
            if raw["phase"] == "birth":
                time = lifetimes[particle]["birth"]  # Derived view only; raw CSV remains unchanged.
            if time > lifetimes[particle]["terminal"]:
                continue  # Native contact backstep: terminal is the authority.
            current = {key: float(raw[key]) for key in COORDINATES}
            if particle in previous:
                before_t, before = previous[particle]
                for index, selected in enumerate(times):
                    selected_t = selected["instrument_time_us"]
                    if before_t <= selected_t <= time and selected_t < lifetimes[particle]["terminal"]:
                        fraction = (selected_t-before_t)/(time-before_t) if time > before_t else 0
                        interpolated[particle, index] = {
                            key: before[key]+fraction*(current[key]-before[key]) for key in COORDINATES}
                        maximum_gap = max(maximum_gap, time-before_t)
            previous[particle] = time, current
    rows = []
    for index, selected in enumerate(times):
        time = selected["instrument_time_us"]
        for mother in census:
            particle = int(mother["particle_id"])
            row = dict(snapshot_index=index, snapshot_label=selected["label"], instrument_time_us=time,
                       particle_id=particle, state="upstream_not_transferred", **{key: "" for key in COORDINATES})
            if particle in lifetimes:
                lifetime = lifetimes[particle]
                if time < lifetime["birth"]:
                    row["state"] = "not_yet_handed_off"
                elif time >= lifetime["terminal"]:
                    row.update(state=terminal_status[particle], **lifetime["terminal_state"])
                else:
                    if (particle, index) not in interpolated:
                        raise ValueError("Alive snapshot lacks an observed interpolation bracket")
                    row.update(state="alive", **interpolated[particle, index])
            rows.append(row)
    return rows, maximum_gap


def _record_birth_clock_projection(output: Path, lifetimes: dict, authority: dict) -> dict:
    rows = [dict(particle_id=particle, raw_birth_time_us=value["raw_birth_time_us"],
                 canonical_birth_time_us=value["birth"], raw_minus_canonical_us=value["raw_birth_time_us"]-value["birth"],
                 birth_clock_projected=value["birth_clock_projected"], semantics=value["birth_clock_semantics"],
                 six_dimensional_state_exact=value["six_dimensional_state_exact"],
                 first_subsequent_time_us=value["first_subsequent_time_us"],
                 subsequent_sample_count=value["subsequent_sample_count"], all_subsequent_times_at_or_after_canonical_birth=True)
            for particle, value in sorted(lifetimes.items())]
    _write_rows(output / "birth_clock_projection.csv", rows, list(rows[0]))
    result = dict(schema_version=1, role="mrtof_initialize_birth_clock_projection", authority=authority,
                  particle_count=len(rows), projected_particle_ids=[r["particle_id"] for r in rows if r["birth_clock_projected"]],
                  maximum_absolute_raw_clock_difference_us=max(abs(r["raw_minus_canonical_us"]) for r in rows),
                  raw_trajectory_csv_modified=False, six_dimensional_state_changed=False,
                  interpretation="Initialize callback may report engine elapsed zero before SIMION applies per-ion TOB. Canonical handoff birth is used only in derived lifetime/snapshot views; all subsequent recorded times and raw rows remain unchanged.",
                  numerical_tolerance_added=False, rows_record=file_record(output / "birth_clock_projection.csv"))
    _write(output / "birth_clock_projection.json", result)
    return result


def _save_figure(figure, path: Path, metadata: dict) -> None:
    outputs = {}
    for extension in ("png", "svg"):
        target = path.with_suffix("."+extension)
        figure.savefig(target, dpi=180, facecolor="white")
        outputs[extension] = file_record(target)
    _write(path.with_suffix(".metadata.json"), dict(metadata, figure_role=path.name,
           figure_size_inches=list(figure.get_size_inches()), dpi=180, outputs=outputs))
    plt.close(figure)


def build_prism_figure(rows: list[dict], mother_count: int, design: dict):
    """Render every first raw crossing, including aperture/direction anomalies."""
    figure, axes = plt.subplots(4, 2, figsize=(11, 12), constrained_layout=True)
    for column, stage in enumerate(STAGES):
        selected = [row for row in rows if row["stage"] == stage and row["first_recorded_crossing"]]
        axes[0, column].set_title(f"{stage.replace('_', ' ').title()}: {len(selected)}/{mother_count} mother ions")
        axes[0, column].scatter([r["x_mm"] for r in selected], [r["y_mm"] for r in selected], s=14, marker="o", color="#0072B2", label="All first raw crossings")
        flagged = [r for r in selected if r["inside_aperture"] == 0 or r["direction_ok"] == 0]
        axes[0, column].scatter([r["x_mm"] for r in flagged], [r["y_mm"] for r in flagged], s=32, marker="x", color="#D55E00", label="Aperture/direction flag")
        axes[0, column].set(xlabel="Project x (mm)", ylabel="Project y (mm)")
        if stage == "p2_fixed_plane" and "p2_aperture" in design:
            aperture = design["p2_aperture"]
            xmin, xmax = aperture["x_mm"]
            ymin, ymax = aperture["y_mm"]
            axes[0, column].add_patch(Rectangle((xmin, ymin), xmax-xmin, ymax-ymin, facecolor="#dddddd", edgecolor="black", alpha=.5, zorder=0))
            axes[0, column].plot([xmin, xmax], [ymin, ymax], alpha=0)  # Include the full aperture in autoscaling.
            axes[0, column].text(xmin, ymin, f" P2 aperture at z={design['p2_plane_z_mm']:g} mm", fontsize=8, va="bottom")
        angular = [row for row in selected if row["signed_yz_angle_deg"] != ""]
        axes[1, column].scatter([r["y_mm"] for r in angular], [r["signed_yz_angle_deg"] for r in angular], s=14, marker="o", color="#0072B2")
        axes[1, column].set(xlabel="Project y (mm)", ylabel="atan2(vy, vz) (deg)")
        if stage == "p2_fixed_plane" and "p2_target_signed_angle_deg" in design:
            axes[1, column].axhline(design["p2_target_signed_angle_deg"], color="#000000", linestyle="--", label=f"Frozen angle {design['p2_target_signed_angle_deg']:.6f} deg; no gate")
            axes[1, column].legend(fontsize=7)
        for component, color, line in (("Ex", "#0072B2", "-"), ("Ey", "#D55E00", "--"), ("Ez", "#009E73", "-."), ("K", "#000000", ":")):
            panel = 2 if component in {"Ex", "Ey"} else 3
            values = sorted(float(r[component+"_per_charge_eV"]) for r in selected)
            if values:
                axes[panel, column].step([values[0], *values], [0, *[(i+1)/len(values) for i in range(len(values))]], where="post", color=color, linestyle=line, label=component)
        for panel in (2, 3):
            axes[panel, column].set(xlabel="Component kinetic energy / |q| (eV)", ylabel="Empirical cumulative fraction")
            axes[panel, column].set_ylim(0, 1)
            axes[panel, column].ticklabel_format(axis="x", style="plain", useOffset=False)
            if selected:
                axes[panel, column].legend()
        axes[0, column].legend(fontsize=8)
        if not selected:
            for axis in axes[:, column]:
                axis.text(.5, .5, "No recorded arrivals", transform=axis.transAxes, ha="center")
    # Paired energy panels use common scales; different component groups keep
    # separate axes so transverse energy is not compressed against ~4 keV.
    for panel, components in ((2, ("Ex", "Ey")), (3, ("Ez", "K"))):
        values = [float(row[key+"_per_charge_eV"]) for row in rows
                  if row["stage"] in STAGES and row["first_recorded_crossing"] for key in components]
        if values:
            low, high = min(values), max(values)
            padding = (high-low)*.05 if high > low else max(abs(low)*.05, 1.)
            for axis in axes[panel]:
                axis.set_xlim(low-padding, high+padding)
    figure.suptitle("Prism position, signed direction and kinetic-energy partition\nAll raw first crossings; no energy or whole-beam acceptance threshold")
    return figure, axes


def build_snapshot_figure(rows: list[dict], times: list[dict], mother_count: int, epoch_us: float):
    """Render paired y-z/x-z views at automatically selected absolute times."""
    figure, axes = plt.subplots(len(times), 2, figsize=(11, max(4, 2.6*len(times))), constrained_layout=True, squeeze=False)
    all_positioned = [row for row in rows if row["x_mm"] != ""]
    for index, selected in enumerate(times):
        group = [row for row in rows if row["snapshot_index"] == index]
        alive = sum(row["state"] == "alive" for row in group)
        for column, horizontal in enumerate(("y_mm", "x_mm")):
            axis = axes[index, column]
            for state, color in COLORS.items():
                points = [row for row in group if row["state"] == state]
                axis.scatter([r[horizontal] for r in points], [r["z_mm"] for r in points], color=color, marker=MARKERS[state], s=13,
                             label=state if state == "alive" else state+" last position")
            axis.set(xlabel=f"Project {horizontal[0]} (mm)", ylabel="Project z (mm)",
                     title=f"{selected['label']}: t-epoch={selected['instrument_time_us']-epoch_us:.6f} us; alive {alive}/{mother_count}")
            if all_positioned:
                for name, setter in ((horizontal, axis.set_xlim), ("z_mm", axis.set_ylim)):
                    lo, hi = min(float(r[name]) for r in all_positioned), max(float(r[name]) for r in all_positioned)
                    padding = (hi-lo)*.05 if hi > lo else 1.0
                    setter(lo-padding, hi+padding)
            axis.legend(fontsize=7, loc="best")
    figure.suptitle("Automatic common-time spatial distributions\nInterpolation within observed brackets only; terminal markers are not alive clouds; axis scales differ")
    return figure, axes


def build_loss_figure(census: list[dict]):
    """Show the complete mother population and every downstream terminal site."""
    figure, axes = plt.subplots(1, 2, figsize=(11, 4.5), constrained_layout=True)
    categories = ("not_transferred", "detected", "loss", "timeout")
    axes[0].bar(range(4), [sum(r["downstream_status"] == state for r in census) for state in categories],
                color=("#777777", "#009E73", "#D55E00", "#CC79A7"), hatch="//", edgecolor="black")
    axes[0].set(xticks=range(4), xticklabels=[s.replace("_", "\n") for s in categories], ylabel="Mother particle count", title=f"Complete population: N={len(census)}")
    for state in ("detected", "loss", "timeout"):
        selected = [r for r in census if r["downstream_status"] == state]
        axes[1].scatter([float(r["terminal_position_y_mm"]) for r in selected], [float(r["terminal_position_z_mm"]) for r in selected],
                        s=18, color=COLORS[state], marker=MARKERS[state], label=state)
        if state != "detected" and len(selected) <= 12:
            for row in selected:
                axes[1].annotate(str(row["particle_id"]), (float(row["terminal_position_y_mm"]), float(row["terminal_position_z_mm"])), fontsize=7)
    axes[1].set(xlabel="Terminal project y (mm)", ylabel="Terminal project z (mm)", title="Downstream terminal states; upstream evidence linked separately")
    axes[1].legend()
    return figure, axes


def _loss_evidence(merged_log: Path, destination: Path, census: list[dict], source_receipt: dict) -> dict:
    destination.mkdir()
    downstream = {int(row["particle_id"]) for row in census if row["downstream_status"] in {"loss", "timeout"}}
    upstream = {int(row["particle_id"]) for row in census if row["downstream_status"] == "not_transferred"}
    counts = {particle: 0 for particle in downstream | upstream}
    handles = {particle: (destination/f"particle_{particle:05d}.jsonl").open("w", encoding="utf-8") for particle in counts}
    sources = []
    try:
        with merged_log.open(encoding="utf-8-sig") as source:
            for line_number, line in enumerate(source, 1):
                match = re.search(r"\bion=(\d+)\b", line)
                if match and int(match[1]) in downstream:
                    particle = int(match[1])
                    handles[particle].write(json.dumps(dict(source=str(merged_log), line_number=line_number, raw_line=line))+"\n")
                    counts[particle] += 1
        handoff_path = _bound(source_receipt["inputs"]["handoff_receipt"], merged_log.parent)
        handoff = _read(handoff_path)
        component_path = _bound(handoff["inputs"]["component_receipt"], handoff_path.parent)
        component = _read(component_path)
        upstream_run = Path(component["source_run"])
        manifest_path = _bound(component["inputs"]["run_manifest.json"], component_path.parent)
        manifest = _read(manifest_path)
        records = [*manifest.get("inputs", {}).values(), *manifest.get("outputs", [])]
        for name in ("events.csv", "samples.csv"):
            path = upstream_run / "simion" / name
            matches = [r for r in records if record_path(r, base_dir=upstream_run) == path.resolve()]
            if not matches:
                raise ValueError("Upstream loss evidence is not manifest-bound: "+name)
            for record in matches:
                verify_record("upstream complete loss evidence", record, base_dir=upstream_run)
            sources.append({**matches[0], "path": str(path.resolve())})
            with path.open(encoding="utf-8-sig", newline="") as stream:
                header = next(csv.reader([stream.readline()]))
                particle_column = header.index("particle_id")
                for line_number, line in enumerate(stream, 2):
                    values = next(csv.reader([line]))
                    particle = int(values[particle_column])
                    if particle in upstream:
                        handles[particle].write(json.dumps(dict(source=str(path), line_number=line_number, raw_line=line, fields=dict(zip(header, values))))+"\n")
                        counts[particle] += 1
    finally:
        for handle in handles.values():
            handle.close()
    if any(counts[particle] == 0 for particle in counts):
        raise ValueError("A lost particle lacks complete raw evidence")
    result = dict(schema_version=1, role="mrtof_full_loss_evidence", downstream_lost_ids=sorted(downstream),
                  upstream_not_transferred_ids=sorted(upstream), raw_record_counts=counts,
                  upstream_sources=sources, merged_log=str(merged_log),
                  selection="all raw per-ion lines; no row sampling or terminal-only substitution",
                  files=[file_record(path) for path in sorted(destination.glob("*.jsonl"))])
    _write(destination / "loss_evidence.json", result)
    return result


def analyze_prepared_joint_flight(preparation_receipt: Path, merged_log: Path, output_directory: Path,
                                  *, merge_receipt: Path | None = None) -> dict[str, Any]:
    """Automatically publish full-census Prism, time-cloud and loss diagnostics.

    Inputs must be frozen measured-source trial/clock identities and a complete
    merged original-ID log. No solver, GUI, interpolation outside support,
    particle filtering or whole-beam acceptance/performance gate is performed.
    """
    if output_directory.exists():
        raise FileExistsError(output_directory)
    prepared, source_path, source, states, mother, contract = _inputs(preparation_receipt)
    if merge_receipt is not None:
        merged = _read(merge_receipt)
        if (merged.get("schema_version") != 1 or merged.get("role") != "mrtof_measured_batch_log_merge"
                or merged.get("status") != "success" or merged.get("id_rebasing_applied") is not False
                or merged.get("all_batch_losses_retained") is not True
                or merged.get("particle_count") != len(states)
                or merged.get("original_particle_ids") != prepared["expected_particle_ids"]
                or merged.get("mother_particle_count") != prepared["mother_particle_count"]
                or merged.get("solver_epoch_instrument_time_us") != prepared["solver_epoch_instrument_time_us"]):
            raise ValueError("Measured merge receipt differs from prepared population/clock")
        if (_bound(merged["preparation"], merge_receipt.parent).resolve() != preparation_receipt.resolve()
                or _bound(merged["merged_log"], merge_receipt.parent).resolve() != merged_log.resolve()):
            raise ValueError("Measured merge receipt differs from preparation/log identity")
        batches = merged["batches"]
        if not batches:
            raise ValueError("Measured merge receipt lacks completed source batches")
        # Normalize only file records in memory. Recovery adds provenance fields
        # to its copied records; those do not change the actual file identities.
        existing = prepared.get("completed_source_batches")
        if existing is not None:
            def identities(rows: list[dict], base: Path) -> list[dict]:
                return [{key: file_record(_bound(row[key], base)) for key in ("log", "batch_receipt", "fly2")}
                        for row in rows]
            if identities(existing, preparation_receipt.parent) != identities(batches, merge_receipt.parent):
                raise ValueError("Embedded and merged completed source batches conflict")
        prepared = dict(prepared, completed_source_batches=batches)
        # Resolve records relative to their receipt before the existing source
        # TOB validator consumes them relative to the preparation directory.
        prepared["completed_source_batches"] = [
            {key: file_record(_bound(row[key], merge_receipt.parent)) for key in ("log", "batch_receipt", "fly2")}
            for row in batches]
    output_directory.mkdir(parents=True)
    event_log = output_directory / "events.log"
    _project_events(merged_log, event_log)
    population = analyze_measured_component(event_log, source_path, output_directory / "population")
    events = _read(output_directory / "population/parsed_events.json")
    census = _rows(output_directory / "population/particle_census.csv")
    trajectory = extract_trajectory_samples(log_path=merged_log, output_path=output_directory / "trajectory_samples.csv",
                                           receipt_path=output_directory / "trajectory_receipt.json", recording_config=prepared["trajectory_recording"])
    birth_authority = _validate_birth_clock_projection(source, states, source_path.parent)
    birth_authority["actual_launch_evidence"] = _validate_completed_source_batches(prepared, states, preparation_receipt.parent)
    lifetimes = _trajectory_lifetimes(output_directory / "trajectory_samples.csv", states,
                                     {int(event["ion"]): event for event in events if event["kind"] == "terminal"},
                                     initialization_epoch_us=birth_authority["epoch_us"])
    if any(value["birth_clock_projected"] for value in lifetimes.values()) and birth_authority["actual_launch_evidence"]["status"] != "verified_actual_launched_sources":
        raise ValueError("Initialize birth-clock projection requires verified actual launched batch FLY2 evidence")
    birth_projection = _record_birth_clock_projection(output_directory, lifetimes, birth_authority)
    times = _snapshot_times(lifetimes, events)
    snapshots, gap = _snapshot_rows(output_directory / "trajectory_samples.csv", lifetimes, mother,
                                  {int(r["particle_id"]): r["downstream_status"] for r in census}, times)
    _write_rows(output_directory / "timed_spatial_clouds.csv", snapshots, list(snapshots[0]))
    prism = _prism_rows(events, states)
    design = _design_reference(prepared, preparation_receipt.parent)
    for row in prism:
        row["raw_signed_angle_difference_to_reference_deg"] = (
            row["signed_yz_angle_deg"]-design["p2_target_signed_angle_deg"]
            if row["stage"] == "p2_fixed_plane" and row["signed_yz_angle_deg"] != "" and "p2_target_signed_angle_deg" in design else "")
        row["positive_turn_y_difference_to_reference_mm"] = (
            row["y_mm"]-design["positive_turn_target_y_mm"]
            if row["stage"] == "first_positive_turn" and "positive_turn_target_y_mm" in design else "")
    prism_columns = ["stage", "particle_id", "event_index", "first_recorded_crossing", "instrument_time_us", *COORDINATES,
                     "signed_yz_angle_deg", "transverse_tilt_deg", "inside_aperture", "direction_ok", "Ex_per_charge_eV", "Ey_per_charge_eV", "Ez_per_charge_eV", "K_per_charge_eV", "raw_signed_angle_difference_to_reference_deg", "positive_turn_y_difference_to_reference_mm"]
    _write_rows(output_directory / "prism_phase_space.csv", prism, prism_columns)
    species = {(float(r["mass_amu"]), int(r["charge_state"])) for r in states.values()}
    standard = _prism_phase_space_diagnostic(events, tuple(sorted(states)), *next(iter(species))) if len(species) == 1 else None
    loss = _loss_evidence(merged_log, output_directory / "loss_evidence", census, source)
    repo = Path(__file__).resolve().parents[3]
    git = {}
    for key, arguments in (("sha", ["rev-parse", "HEAD"]), ("worktree", ["status", "--porcelain"])):
        process = subprocess.run(["git", "-C", str(repo), *arguments], cwd=repo, capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=10, check=False)
        git[key] = process.stdout.strip() if process.returncode == 0 else "unavailable"
    metadata = dict(schema_version=1, role="mrtof_prepared_joint_diagnostic_figure", counts=population["counts"], git=git,
                    frame_id=source["frame_id"], clock_epoch_id=source["clock_epoch_id"],
                    units=dict(position="mm", velocity="mm/us", time="absolute instrument us", energy="eV/abs(q)", angle="deg"),
                    inputs=dict(preparation=file_record(preparation_receipt), merged_log=file_record(merged_log), source_receipt=file_record(source_path)),
                    producer=file_record(Path(__file__)), style="English, color plus marker/line, 180 DPI PNG and vector SVG", design_reference=design,
                    filtering="no mother exclusion; first crossing plots preserve every raw branch in CSV; no detector-conditioned selection",
                    interpolation="linear only between adjacent recorded states; no extrapolation; terminal points separately marked",
                    maximum_interpolation_gap_us=gap, automatic_snapshot_selection=times,
                    recording_policy=prepared["trajectory_recording"], uncertainty="descriptive finite cohort; no inferred acceptance or confidence interval",
                    birth_clock_projection=birth_projection,
                    potential_correction="not evaluated; terminal ion_volts is not used as scalar-field potential; raw K differences are not conservation residuals",
                    qualification="diagnostic_only_no_physics_GUI_or_Formal_pass")
    if merge_receipt is not None:
        metadata["inputs"]["batch_log_merge_receipt"] = file_record(merge_receipt)
    with plt.rc_context({"font.size": 9, "axes.titlesize": 9}):
        for role, builder, args in (("prism_phase_space", build_prism_figure, (prism, len(mother), design)),
                                    ("timed_spatial_clouds", build_snapshot_figure, (snapshots, times, len(mother), source["solver_epoch_instrument_time_us"])),
                                    ("population_and_losses", build_loss_figure, (census,))):
            figure, _ = builder(*args)
            _save_figure(figure, output_directory / role, metadata)
    result = dict(schema_version=1, role="mrtof_prepared_joint_diagnostics", status="complete_recorded_diagnostics",
                  inputs=metadata["inputs"],
                  counts=population["counts"], figure_roles=["prism_phase_space", "timed_spatial_clouds", "population_and_losses"],
                  snapshot_count=len(times), maximum_interpolation_gap_us=gap, trajectory=trajectory,
                  birth_clock_projection=birth_projection,
                  prism_phase_space_reference=standard, signed_angle_definition="atan2(vy,vz), full quadrant; zero yz speed undefined",
                  prism_statistics=_prism_statistics(prism, {int(row["particle_id"]) for row in mother}),
                  frozen_design_reference=design,
                  legacy_reference_angle_definition="existing reference diagnostic uses atan2(vy,abs(vz)); use explicit CSV signed_yz_angle_deg for full quadrant",
                  loss_evidence=loss, qualification="descriptive_diagnostics_only_no_whole_beam_acceptance_or_performance_pass",
                  outputs=[file_record(path) for path in sorted(output_directory.rglob("*")) if path.is_file()])
    _write(output_directory / "diagnostics_receipt.json", result)
    return result
