"""Recorded population loss and field-domain evidence, without acceptance gates.

The original collision classifier owns solid membership. Field-domain crossings
are adjacent recorded-state brackets, not inferred field discontinuities or
electrode contacts. Upstream particles without a handoff retain blank source6D.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
from typing import Any

from matplotlib import pyplot as plt
from matplotlib.patches import Ellipse, Patch, Polygon, Rectangle

from common.contracts.particle_physics import kinetic_energy_ev
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import collision_diagnostics
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import _collision_geometry_projection

STATE = ("x_mm", "y_mm", "z_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us")
GROUPS = {
    "detected": ("Detected", "#009E73", "o"),
    "early_contact": ("Contact before P2 entry", "#D55E00", "x"),
    "later_contact": ("Contact after P2 entry", "#E69F00", "^"),
    "topology": ("Topology termination", "#CC79A7", "s"),
    "other_termination": ("Other termination", "#0072B2", "+"),
    "not_transferred": ("Upstream, no handoff", "#666666", "D"),
}


def _stages(events: list[dict]) -> list[tuple[str, bool]]:
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


def prepare_loss_rows(events: list[dict], states: dict[int, dict], census: list[dict],
                      geometry: dict) -> tuple[list[dict], dict]:
    """Join all mother IDs to source, recorded milestones and native contacts."""
    collision = collision_diagnostics(events, _collision_geometry_projection(geometry))
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
        stage_presence = _stages(chain)
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


def prepare_mirror_domain_rows(trajectory: Path, binding: dict, particle_ids: set[int],
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
    with trajectory.open(encoding="utf-8-sig", newline="") as stream:
        for raw in csv.DictReader(stream):
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


def _contact_z_limits(rows: list[dict]) -> list[float] | None:
    positions = [float(r["terminal_z_mm"]) for r in rows if r["termination_kind"] == "native_contact"]
    if not positions:
        return None
    margin = max((max(positions)-min(positions))*.08, 1)
    return [min(positions)-margin, max(positions)+margin]


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
    contact_z_limits = _contact_z_limits(rows)
    for axis, dimension in zip(axes[1], "xy"):
        axis.set(xlabel="Terminal z (mm)", ylabel=f"Terminal {dimension} (mm)",
                 title=f"Contact projections: z-{dimension} (unequal scales)")
        axis.autoscale_view()
        if contact_z_limits is not None:
            axis.set_xlim(*contact_z_limits)
        contacts = [float(r[f"terminal_{dimension}_mm"]) for r in rows if r["termination_kind"] == "native_contact"]
        if contacts:
            margin = max((max(contacts)-min(contacts))*.08, 1)
            axis.set_ylim(min(contacts)-margin, max(contacts)+margin)
        else:
            axis.text(.5, .5, "No native contacts", transform=axis.transAxes, ha="center", va="center")
        axis.grid(alpha=.15)
    return figure, axes


def summarize_loss_acceptance(rows: list[dict], collision: dict, domain: dict) -> dict[str, Any]:
    return dict(schema_version=1, role="mrtof_recorded_loss_acceptance_diagnostics",
                mother_particle_count=len(rows), group_counts=dict(Counter(r["group"] for r in rows)),
                first_missing_recorded_stage_counts=dict(Counter(r["first_missing_recorded_stage"] for r in rows)),
                collision_diagnostics=collision, mirror_domain=domain,
                source_policy="unaltered handoff six-dimensional states; upstream non-transferred have no handoff state",
                energy_policy="component and total K/abs(q) calculated from velocity and canonical mass/charge; never ion_volts",
                geometry_projection="native resolved solids; original collision classifier tolerance retained",
                geometry_rendering="independent solid/aperture outline projections, not CSG cross sections; no occluding hole fills",
                geometry_context=dict(contact_z_limits_mm=_contact_z_limits(rows),
                    selection="both contact panels share all native-contact z min/max plus 8% of span, minimum 1 mm per side; no contact points excluded",
                    clipping="geometry context clipped to observed contact z extent with margin; full geometry context when no native contacts",
                    data_retention="complete CSV remains unclipped"),
                recorded_stage_policy="first_forward_negative_central_crossing is recorded n=1, direction_z<0, vy>0 only; no clean-domain y/x acceptance gate",
                qualification="descriptive finite-cohort evidence; no new whole-beam gate or causal assertion")
