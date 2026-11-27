"""Descriptive MR trajectory statistics and population figures."""
import json
import math
import statistics
from collections import Counter, defaultdict
from typing import Any

from matplotlib import pyplot as plt
from matplotlib.patches import Ellipse, Patch, Polygon, Rectangle
from msplatform.contracts.particle_physics import kinetic_energy_ev
from msplatform.analysis.mr_population import log_roundoff_us

COORDINATES = ("x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us")

STAGES = ("p1_exit", "p2_fixed_plane")
COLORS = {"alive": "#0072B2", "detected": "#009E73", "loss": "#D55E00", "timeout": "#CC79A7"}
MARKERS = {"alive": "o", "detected": "s", "loss": "x", "timeout": "^"}


def prism_statistics(rows: list[dict], mother_ids: set[int]) -> dict:
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



def recorded_stages(events: list[dict]) -> list[tuple[str, bool]]:
    """Recorded stage presence; no interpolation or centre-point tolerance."""
    return [
        ("p1_exit", any(e["kind"] == "prism_pass" and int(e.get("n", 0)) == 1 for e in events)),
        ("negative_pre_injection_turn", any(e["kind"] == "pre_injection_mirror_turn" for e in events)),
        ("p2_entry", any(e["kind"] == "prism_entry" and int(e.get("n", 0)) == 2 for e in events)),
        ("p2_fixed_plane", any(e["kind"] == "p2_low_field_crossing" for e in events)),
        ("positive_origin_turn", any(e["kind"] == "pre_origin_positive_mirror_turn" for e in events)),
        ("first_forward_negative_central_crossing", any(e["kind"] == "central_plane_directional"
            and int(e.get("n", 0)) == 1 and float(e.get("direction_z", 0)) < 0
            and float(e.get("vy_mm_us", 0)) > 0 for e in events)),
        ("target_k", any(e["kind"] == "target_k" for e in events)),
        ("return_p2_entry", any(e["kind"] == "return_p2_entry" for e in events)),
        ("return_p2_pass", any(e["kind"] == "return_p2_pass" for e in events)),
        ("detector", any(e["kind"] == "detector" for e in events)),
    ]



def contact_z_limits(rows: list[dict]) -> list[float] | None:
    positions = [float(r["terminal_z_mm"]) for r in rows if r["termination_kind"] == "native_contact"]
    if not positions:
        return None
    margin = max((max(positions)-min(positions))*.08, 1)
    return [min(positions)-margin, max(positions)+margin]



def summarize_loss_acceptance(rows: list[dict], collision: dict, domain: dict) -> dict[str, Any]:
    return dict(schema_version=1, role="mrtof_recorded_loss_acceptance_diagnostics",
                mother_particle_count=len(rows), group_counts=dict(Counter(r["group"] for r in rows)),
                first_missing_recorded_stage_counts=dict(Counter(r["first_missing_recorded_stage"] for r in rows)),
                collision_diagnostics=collision, mirror_domain=domain,
                source_policy="unaltered handoff six-dimensional states; upstream non-transferred have no handoff state",
                energy_policy="component and total K/abs(q) calculated from velocity and canonical mass/charge; never ion_volts",
                geometry_projection="native resolved solids; original collision classifier tolerance retained",
                geometry_rendering="independent solid/aperture outline projections, not CSG cross sections; no occluding hole fills",
                geometry_context=dict(contact_z_limits_mm=contact_z_limits(rows),
                    selection="both contact panels share all native-contact z min/max plus 8% of span, minimum 1 mm per side; no contact points excluded",
                    clipping="geometry context clipped to observed contact z extent with margin; full geometry context when no native contacts",
                    data_retention="complete CSV remains unclipped"),
                recorded_stage_policy="first_forward_negative_central_crossing is recorded n=1, direction_z<0, vy>0 only; no clean-domain y/x acceptance gate",
                qualification="descriptive finite-cohort evidence; no new whole-beam gate or causal assertion")


def prism_rows(events: list[dict], states: dict) -> list[dict]:
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



def snapshot_times(lifetimes: dict, events: list[dict]) -> list[dict]:
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



def trajectory_lifetimes(rows, states: dict, terminals: dict[int, dict], *, initialization_epoch_us: float | None = None) -> dict[int, dict]:
    lifetimes = {}
    for row in rows:
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
                if abs(actual-event) > log_roundoff_us(actual)+math.ulp(actual):
                    raise ValueError("Trajectory terminal differs from the recorded terminal event")
    if set(lifetimes) != set(states) or any("terminal" not in row for row in lifetimes.values()):
        raise ValueError("Trajectory source/terminal IDs do not close")
    return lifetimes




def snapshot_rows(source_rows, lifetimes: dict, census: list[dict], terminal_status: dict, times: list[dict]) -> tuple[list[dict], float]:
    interpolated, previous, maximum_gap = {}, {}, 0.0
    for raw in source_rows:
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



GROUPS = {
    "detected": ("Detected", "#009E73", "o"),
    "early_contact": ("Contact before P2 entry", "#D55E00", "x"),
    "later_contact": ("Contact after P2 entry", "#E69F00", "^"),
    "topology": ("Topology termination", "#CC79A7", "s"),
    "other_termination": ("Other termination", "#0072B2", "+"),
    "not_transferred": ("Upstream, no handoff", "#666666", "D"),
}


def _add_geometry_projections(axes, geometry: dict) -> None:
    """Draw independent native solid/aperture outlines, never a CSG section."""
    def add(body: dict, aperture: bool = False) -> None:
        polygon = body.get("polygon_yz_mm")
        box = body.get("box")
        if box is None:
            box = [body["x"][0], min(p[0] for p in polygon), min(p[1] for p in polygon),
                   body["x"][1], max(p[0] for p in polygon), max(p[1] for p in polygon)]
        style = dict(fill=False, edgecolor="#0072B2" if aperture else "#777777",
                     linewidth=.65 if aperture else .4, alpha=.75 if aperture else .5,
                     zorder=1 if aperture else 0, gid="aperture_projection" if aperture else "solid_projection")
        axes[0].add_patch(Rectangle((box[2], box[0]), box[5]-box[2], box[3]-box[0], **style))
        if polygon:
            axes[1].add_patch(Polygon([(p[1], p[0]) for p in polygon], **style))
        else:
            axes[1].add_patch(Rectangle((box[2], box[1]), box[5]-box[2], box[4]-box[1], **style))

    bodies = [*geometry["mirror_ground_shields"], *geometry["mirror_electrodes"], *geometry["mirror_e_closures"],
              *geometry["central_ground_electrodes"], *geometry["stripe_electrodes"],
              *[part for prism in geometry["prism_electrodes"] for part in prism["parts"]],
              *[part for shield in geometry["prism_ground_shields"] for part in shield["body_sections"]]]
    if "detector" in geometry:
        bodies.append(geometry["detector"])
    for body in bodies:
        add(body)
        if "terminal_polygon_yz_mm" in body:
            add(dict(x=body["x"], polygon_yz_mm=body["terminal_polygon_yz_mm"]))
        for hole in body.get("holes", []):
            add(hole, True)
    for shield in geometry["prism_ground_shields"]:
        add(dict(x=shield["x"], polygon_yz_mm=shield["prism_clearance_polygon_yz_mm"]), True)
        for box in shield.get("rectangular_slots_mm", []):
            add(dict(box=box), True)
    for box in (geometry["mirror_slot"], geometry["mirror_inner_shield_slot"],
                geometry["stripe_slot"], *geometry["central_ground_slots"]):
        if box:
            add(dict(box=box), True)
    for electrode in geometry.get("ion_processor_electrodes", []):
        for shapes, aperture in ((electrode["solids"], False), (electrode["cutouts"], True)):
            for shape in shapes:
                if shape["shape"] == "box":
                    add(dict(box=[*shape["min_mm"], *shape["max_mm"]]), aperture)
                elif shape["shape"] == "cylinder3d":
                    a, b = shape["endpoints_mm"]
                    if a[0] != b[0] or a[2] != b[2]:
                        raise ValueError("IP projection requires the native y-axis cylinder geometry")
                    radius = shape["radius_mm"]
                    style = dict(fill=False, edgecolor="#0072B2" if aperture else "#777777",
                                 linewidth=.65 if aperture else .4, alpha=.75 if aperture else .5,
                                 gid="aperture_projection" if aperture else "solid_projection")
                    axes[0].add_patch(Ellipse((a[2], a[0]), 2*radius, 2*radius, **style))
                    axes[1].add_patch(Rectangle((a[2]-radius, min(a[1], b[1])), 2*radius, abs(b[1]-a[1]), **style))
                else:
                    raise ValueError("Unsupported native IP shape in geometry projection")



def build_loss_acceptance_figure(rows: list[dict], geometry: dict):
    """Plot source phase space and real contacts with native outline projections."""
    figure, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    for group, (label, color, marker) in GROUPS.items():
        selected = [r for r in rows if r["group"] == group]
        if not selected:
            continue
        source = [r for r in selected if r["source_position_x_mm"] != ""]
        for axis, dimension in zip(axes[0], "xy"):
            axis.scatter([float(r[f"source_position_{dimension}_mm"]) for r in source],
                         [float(r[f"source_velocity_{dimension}_m_s"]) for r in source],
                         color=color, marker=marker, s=23, label=f"{label} (N={len(selected)}, source={len(source)})")
        contacts = [r for r in selected if r["termination_kind"] == "native_contact"]
        for axis, dimension in zip(axes[1], "xy"):
            axis.scatter([float(r["terminal_z_mm"]) for r in contacts],
                         [float(r[f"terminal_{dimension}_mm"]) for r in contacts],
                         color=color, marker=marker, s=26, zorder=3)
    _add_geometry_projections(axes[1], geometry)
    for axis, dimension in zip(axes[0], "xy"):
        axis.set(xlabel=f"Handoff {dimension} (mm)", ylabel=f"Handoff v{dimension} (m/s)")
    axes[0, 0].set_title("Source x phase space")
    axes[0, 1].set_title("Source y phase space")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    handles.extend([Patch(fill=False, edgecolor="#777777"), Patch(fill=False, edgecolor="#0072B2")])
    labels.extend(["Solid projection", "Aperture projection"])
    figure.legend(handles, labels, fontsize=7, loc="outside lower center", ncol=3)
    figure.suptitle(f"Handoff phase space and contact locations (mother N={len(rows)})", fontsize=11)
    contact_limits = contact_z_limits(rows)
    for axis, dimension in zip(axes[1], "xy"):
        axis.set(xlabel="Terminal z (mm)", ylabel=f"Terminal {dimension} (mm)",
                 title=f"Contact projections: z-{dimension} (unequal scales)")
        axis.autoscale_view()
        if contact_limits is not None:
            axis.set_xlim(*contact_limits)
        contacts = [float(r[f"terminal_{dimension}_mm"]) for r in rows if r["termination_kind"] == "native_contact"]
        if contacts:
            margin = max((max(contacts)-min(contacts))*.08, 1)
            axis.set_ylim(min(contacts)-margin, max(contacts)+margin)
        else:
            axis.text(.5, .5, "No native contacts", transform=axis.transAxes, ha="center", va="center")
        axis.grid(alpha=.15)
    return figure, axes




STATE = ("x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us")

def _mirror_windows(binding: dict) -> list[dict]:
    """Select the narrowest declared x window covering each mirror's z domain."""
    mirrors = binding["geometry"]["mirror_electrodes"]
    selected = []
    for sign in (-1, 1):
        bodies = [r["box"] for r in mirrors if sign*(r["box"][2]+r["box"][5]) > 0]
        candidates = [w for w in binding.get("refinement_windows", [])
                      if sign*w["active_box_mm"][2][0] > 0 and sign*w["active_box_mm"][2][1] > 0
                      and any(w["active_box_mm"][2][0] <= (b[2]+b[5])/2 <= w["active_box_mm"][2][1] for b in bodies)]
        if candidates:
            selected.append(min(candidates, key=lambda w: w["active_box_mm"][0][1]-w["active_box_mm"][0][0]))
    return selected


def prepare_mirror_domain_rows(trajectory_rows, binding: dict, particle_ids: set[int],
                               terminals: dict[int, dict]) -> tuple[list[dict], list[dict], dict]:
    """Stream every recorded sample; retain before/after x-boundary brackets.

    z domains and x bounds are the actual narrowest mirror refinement windows.
    Counts are sampling-dependent and include terminal/backstep rows only up to
    the physical terminal time. No sub-step crossing location is invented.
    """
    windows = _mirror_windows(binding)
    stats = {}
    previous = {}
    crossings = []
    first_negative = {}
    for particle in sorted(particle_ids):
        for window in windows:
            for scope in ("all_mirror_samples", "first_negative_mirror_pass"):
                if scope.startswith("first") and window["active_box_mm"][2][0] >= 0:
                    continue
                stats[particle, window["name"], scope] = dict(
                    particle_id=particle, window=window["name"], scope=scope, sample_count=0,
                    inside_x_sample_count=0, outside_x_sample_count=0, inside_active_box_sample_count=0,
                    maximum_abs_x_mm="", x_min_mm=window["active_box_mm"][0][0],
                    x_max_mm=window["active_box_mm"][0][1], z_min_mm=window["active_box_mm"][2][0],
                    z_max_mm=window["active_box_mm"][2][1])
    for raw in trajectory_rows:
        particle = int(raw["ion"])
        if particle not in particle_ids:
            raise ValueError("Mirror-domain diagnostic found unknown trajectory ID")
        state = {key: float(raw[key]) for key in ("t_us", *STATE)}
        if state["t_us"] > float(terminals[particle]["t_us"]):
            continue
        before = previous.get(particle)
        for window in windows:
            box = window["active_box_mm"]
            in_z = box[2][0] <= state["z_mm"] <= box[2][1]
            negative = box[2][1] < 0
            progress = first_negative.get(particle, "not_entered")
            if negative:
                if in_z and progress == "not_entered":
                    first_negative[particle] = progress = "inside"
                elif not in_z and progress == "inside":
                    first_negative[particle] = progress = "finished"
            if not in_z:
                continue
            inside_x = box[0][0] <= state["x_mm"] <= box[0][1]
            scopes = ["all_mirror_samples"]
            if negative and progress == "inside":
                scopes.append("first_negative_mirror_pass")
            for scope in scopes:
                row = stats[particle, window["name"], scope]
                row["sample_count"] += 1
                row["inside_x_sample_count" if inside_x else "outside_x_sample_count"] += 1
                row["inside_active_box_sample_count"] += int(all(
                    box[a][0] <= state[f"{axis}_mm"] <= box[a][1] for a, axis in enumerate("xyz")))
                row["maximum_abs_x_mm"] = max(float(row["maximum_abs_x_mm"] or 0), abs(state["x_mm"]))
            if before and box[2][0] <= before["z_mm"] <= box[2][1]:
                for face, boundary in enumerate(box[0]):
                    # Each signed face separately: a bracket can cross both.
                    before_inside = before["x_mm"] >= boundary if face == 0 else before["x_mm"] <= boundary
                    after_inside = state["x_mm"] >= boundary if face == 0 else state["x_mm"] <= boundary
                    if before_inside != after_inside:
                        crossings.append(dict(particle_id=particle, window=window["name"],
                            boundary_x_mm=boundary, first_negative_mirror_pass=negative and progress == "inside",
                            **{"before_"+key: value for key, value in before.items()},
                            **{"after_"+key: value for key, value in state.items()}))
        previous[particle] = state
    return list(stats.values()), crossings, dict(
        windows=[dict(name=w["name"], active_box_mm=w["active_box_mm"]) for w in windows],
        scope="all recorded samples within declared mirror refinement z domains, including x/y outside active boxes",
        first_pass="first contiguous negative-window z-domain visit in recorded order",
        crossing="adjacent states both in window z domain, each signed x face separately; no interpolation",
        interpretation="sampling/field-domain evidence only; crossings do not establish a field discontinuity or causal loss")




def prepare_loss_rows(events: list[dict], states: dict[int, dict], census: list[dict],
                      collision: dict) -> tuple[list[dict], dict]:
    """Join all mother IDs to source, recorded milestones and native contacts."""
    contacts = {int(r["ion"]): r for r in collision["collision_particles"]}
    by_ion = defaultdict(list)
    for event in events:
        by_ion[int(event["ion"])].append(event)
    rows = []
    for mother in census:
        particle = int(mother["particle_id"])
        chain = by_ion[particle]
        terminal = next((e for e in chain if e["kind"] == "terminal"), {})
        splat = next((e for e in chain if e["kind"] == "splat"), {})
        phases = [e for e in chain if e["kind"] == "target_k_phase_sample"]
        stage_presence = recorded_stages(chain)
        transferred = particle in states
        code = int(terminal["splat"]) if terminal else None
        contact = contacts.get(particle, {})
        topology = (code not in (None, -1, 1) and splat.get("termination_kind") == "programmatic_topology_rejection"
                    and float(splat.get("physical_collision", 1)) == 0)
        group = ("not_transferred" if not transferred else "detected" if mother["downstream_status"] == "detected"
                 else "early_contact" if contact and not dict(stage_presence)["p2_entry"]
                 else "later_contact" if contact else "topology" if topology else "other_termination")
        row = dict(particle_id=particle, downstream_status=mother["downstream_status"], group=group,
                   termination_kind="native_contact" if contact else "topology" if topology else group,
                   upstream_terminal_reason=mother.get("upstream_terminal_reason", ""),
                   first_missing_recorded_stage=next((name for name, present in stage_presence if not present), "none")
                       if transferred else "not_transferred",
                   last_recorded_stage=next((name for name, present in reversed(stage_presence) if present), "none"),
                   component=contact.get("component", ""), electrode_id=contact.get("electrode_id") or "",
                   candidate_components=json.dumps(contact.get("candidate_components", []), sort_keys=True),
                   terminal_splat=code if code is not None else "", terminal_reason=splat.get("reason", ""),
                   terminal_instrument_time_us=terminal.get("t_us", ""),
                   target_phase_event_count=len(phases), target_phase_y_mm=phases[0]["y_mm"] if phases else "",
                   target_phase_instrument_time_us=phases[0]["t_us"] if phases else "")
        for key in STATE:
            row["terminal_"+key] = terminal.get(key, "")
            row["target_phase_"+key] = phases[0].get(key, "") if phases else ""
        source = states.get(particle, {})
        for axis in "xyz":
            row[f"source_position_{axis}_mm"] = source.get(f"position_{axis}_mm", "")
            row[f"source_velocity_{axis}_m_s"] = source.get(f"velocity_{axis}_m_s", "")
        for key in ("mass_amu", "charge_state", "instrument_time_us", "kinetic_energy_eV"):
            row["source_"+key] = source.get(key, "")
        for axis in "xyz":
            velocity = [float(source[f"velocity_{a}_m_s"]) if a == axis else 0 for a in "xyz"] if source else []
            row[f"source_E{axis}_per_charge_eV"] = (
                kinetic_energy_ev(float(source["mass_amu"]), *velocity)/abs(float(source["charge_state"])) if source else "")
            terminal_velocity = [float(terminal[f"v{a}_mm_us"])*1000 if a == axis else 0 for a in "xyz"] if source and terminal else []
            row[f"terminal_E{axis}_per_charge_eV"] = (
                kinetic_energy_ev(float(source["mass_amu"]), *terminal_velocity)/abs(float(source["charge_state"]))
                if source and terminal else "")
        row["source_K_per_charge_eV"] = sum(row[f"source_E{a}_per_charge_eV"] for a in "xyz") if source else ""
        row["terminal_K_per_charge_eV"] = sum(row[f"terminal_E{a}_per_charge_eV"] for a in "xyz") if source and terminal else ""
        rows.append(row)
    return rows, collision
