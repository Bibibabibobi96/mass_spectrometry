"""Analyze a frozen ion-processor run and publish its declared diagnostics."""
from __future__ import annotations

import csv
import math
import statistics
from pathlib import Path
from typing import Any

from msplatform.backends.simion.ip_handoff import frozen_release_states
from msplatform.components.dual_pressure_rectilinear_ion_processor.coordinates import (
    transform_from_config, to_project_position, to_project_vector, to_local_position, to_local_vector,
)
from msplatform.components.dual_pressure_rectilinear_ion_processor.timing import derive_native_timing
from msplatform.components.rf_multipole.event_table import PARTICLE_STATE_COLUMNS, ENUMS, validate_rf_event_table
from msplatform.contracts.particle_physics import kinetic_energy_ev
from msplatform.workflows.ion_processor import preparation
from msplatform.workflows.ion_processor.field_reference import read_json, write_json

EVENTS = ["source", "hp_enter", "capture", "transfer", "pre_extraction", "extraction_exit", "terminal"]

def analyze(run: Path) -> dict[str, Any]:
    """Validate all identities and publish measured functional acceptance."""
    c = read_json(run / "inputs/resolved_model.json")
    profile = preparation.validate_source_profile(c)
    transform = transform_from_config(c)
    transformed = "coordinate_transform" in c
    b, acceptance = c["baseline"], c["acceptance"]
    sources = frozen_release_states(run, c)
    source_by_id = {row["particle_id"]: row for row in sources}
    if not sources and "injected_source" in c:
        with (run/"results/particle_state.csv").open("w", encoding="utf-8", newline="") as stream:
            csv.DictWriter(stream, fieldnames=PARTICLE_STATE_COLUMNS).writeheader()
        census = read_json(run/"inputs/upstream_mother_census.json")
        summary = dict(schema_version=1, role="ion_processor_functional_summary", status="success",
            source_profile="upstream", actual_particle_count=0, mother_particle_count=census["mother_count"],
            qualification="empty_upstream_admission__no_IP_flight", solver_executed=False,
            functional_baseline_eligible=False, functional_status="upstream_empty",
            upstream_census=census, identity_validation=dict(status="PASS", particles=0))
        write_json(run/"summary.json", summary)
        return summary
    from msplatform.results.ip_continuation import native_data_directory
    with (native_data_directory(run) / "events.csv").open(encoding="utf-8", newline="") as f:
        raw = list(csv.DictReader(f))
    schedule=b["schedule"]
    timing = c["native_timing"]
    if timing != derive_native_timing(b):
        raise ValueError("frozen native timing differs from scientific inputs")
    stage_times={"capture":schedule["capture_end_us"],"transfer":schedule["transfer_end_us"],"pre_extraction":timing["primary_quench_us"]}
    previous_time: dict[int,float]={}
    for event in raw:
        particle=int(event["particle_id"]);t=float(event["t_us"])
        if not math.isfinite(t) or t<previous_time.get(particle,0):
            raise ValueError("nonfinite or nonmonotonic scientific event clock")
        previous_time[particle]=t
        if event["event"] in stage_times and abs(t-stage_times[event["event"]])>1e-6:
            raise ValueError("scientific event does not match its frozen stage clock")
        if event["reason"] in {"downstream_domain_exit", "backward_escape"}:
            downstream = event["reason"] == "downstream_domain_exit"
            direction = "downstream" if downstream else "upstream"
            if event["event"] != "terminal":
                raise ValueError(f"{direction} domain exit must be a terminal event")
            boundaries = c.get("numerical_boundaries")
            try:
                preparation.validate_numerical_boundaries(boundaries or {}, c["native_projection"])
            except ValueError:
                raise ValueError(f"{direction} domain exit lacks its derived numerical boundary")
            position = to_local_position(c, [float(event[k]) for k in ("x_mm", "y_mm", "z_mm")])
            velocity = to_local_vector(c, [float(event[k]) for k in ("vx_mm_us", "vy_mm_us", "vz_mm_us")])
            plane = boundaries["downstream_exit_x_mm" if downstream else "upstream_exit_x_mm"]
            if abs(position[0] - plane) > 1e-9 or (velocity[0] <= 0 if downstream else velocity[0] >= 0):
                raise ValueError(f"{direction} domain exit is outside its plane/direction")
        if event["event"]=="extraction_exit":
            local_position = to_local_position(c, [float(event[k]) for k in ("x_mm", "y_mm", "z_mm")])
            local_velocity = to_local_vector(c, [float(event[k]) for k in ("vx_mm_us", "vy_mm_us", "vz_mm_us")])
            if t<timing["primary_quench_us"] or abs(local_position[1]-b["geometry"]["extraction_end_y_mm"])>1e-9 or local_velocity[1]<=0:
                raise ValueError("extraction event is outside its acceptance plane/clock/direction")
    # Canonical lifecycle is separate from the recorded stop reason and from
    # this owner's acceptance/counting rules. A time budget is not physical loss.
    status_by_reason = {
        "none": "alive", "acceptance_surface": "transmitted", "timeout": "timeout",
        "acceptance_radius": "lost", "acceptance_aperture": "lost", "electrode": "lost",
        "radial_escape": "lost", "backward_escape": "lost", "downstream_domain_exit": "lost",
    }
    rows = []
    local_guide_positions = {}
    for r in raw:
        if int(r["particle_id"]) not in source_by_id:
            raise AssertionError("particle IDs do not match the input table")
        source = source_by_id[int(r["particle_id"])]
        mass = source["mass_amu"]
        t,x,y,z,vx,vy,vz = (float(r[k]) for k in ("t_us","x_mm","y_mm","z_mm","vx_mm_us","vy_mm_us","vz_mm_us"))
        lx, ly, lz = to_local_position(c, [x, y, z])
        lvx, lvy, lvz = to_local_vector(c, [vx, vy, vz])
        position = (z, x, y) if transformed else (x, z, y)
        velocity = (vz, vx, vy) if transformed else (vx, vz, vy)
        radius = math.hypot(x, y) if transformed else math.hypot(ly, lz)
        divergence = math.degrees(math.atan2(math.hypot(vx, vy), abs(vz))) if transformed else math.degrees(math.atan2(math.hypot(lvy, lvz), abs(lvx)))
        reason = r["reason"]
        event = r["event"]
        local_guide_positions[(int(r["particle_id"]), event)] = lx
        rows.append(dict(zip(PARTICLE_STATE_COLUMNS, [int(r["particle_id"]),event,status_by_reason.get(reason, "unknown"),reason,t,t-source["birth_time_s"]*1e6,(2*math.pi*b["electric"]["rf_frequency_hz"]*t*1e-6+b["clock"]["rf_phase_rad"])%(2*math.pi),*position,*(v*1000 for v in velocity),kinetic_energy_ev(mass,vx*1000,vy*1000,vz*1000),radius,divergence,b["geometry"]["boundary_radius_mm"]])))
    output = run / "results/particle_state.csv"
    with output.open("w", encoding="utf-8", newline="") as f:
        writer=csv.DictWriter(f,fieldnames=PARTICLE_STATE_COLUMNS); writer.writeheader(); writer.writerows(rows)
    expected = {}
    for source in sources:
        arrival = source["arrival_time_us"] if "injected_source" in c else 0
        x, y, z = to_project_position(c, [source[k] for k in ("x_mm", "y_mm", "z_mm")])
        vx, vy, vz = to_project_vector(c, [source[k] for k in ("vx_m_s", "vy_m_s", "vz_m_s")])
        position = (z, x, y) if transformed else (x, z, y)
        velocity = (vz, vx, vy) if transformed else (vx, vz, vy)
        expected[source["particle_id"]] = dict(zip(
            ("time_us", "elapsed_time_us", "axial_z_mm", "transverse_x_mm", "transverse_y_mm",
             "velocity_axial_m_s", "velocity_x_m_s", "velocity_y_m_s", "kinetic_energy_eV"),
            (arrival, arrival-source["birth_time_s"]*1e6, *position, *velocity, kinetic_energy_ev(source["mass_amu"], vx, vy, vz))))
    validation = validate_rf_event_table(output,expected,b["electric"]["rf_frequency_hz"],b["clock"]["rf_phase_rad"],enums={**ENUMS,"event":EVENTS,"terminal_reason":[*ENUMS["terminal_reason"],"downstream_domain_exit"]})
    grouped={event:[r for r in rows if r["event"]==event] for event in EVENTS}
    metrics = {}
    for event, group in grouped.items():
        metrics[event] = dict(count=len(group),mean_kinetic_energy_ev=statistics.fmean(r["kinetic_energy_eV"] for r in group) if group else None,axial_sigma_mm=statistics.pstdev(local_guide_positions[(r["particle_id"], event)] for r in group) if group else None)
    if transformed:
        for metric in metrics.values():
            metric["slow_sigma_y_mm"] = metric["axial_sigma_mm"]
            metric["axial_sigma_axis"] = "native guide axis = project y"
    hp=[r for r in grouped["capture"] if b["geometry"]["guide_length_mm"] <= local_guide_positions[(r["particle_id"], "capture")] <= b["geometry"]["guide_length_mm"]+b["geometry"]["hp_length_mm"]]
    hp_end=b["geometry"]["guide_length_mm"]+b["geometry"]["hp_length_mm"]
    lp_end=hp_end+b["geometry"]["lp_length_mm"]
    lp=[r for r in grouped["pre_extraction"] if hp_end<local_guide_positions[(r["particle_id"], "pre_extraction")]<lp_end]
    n=len(sources); m=metrics
    checks = dict(capture_fraction=len(hp)/n >= acceptance["minimum_capture_fraction"], extraction_fraction=len(grouped["extraction_exit"])/n >= acceptance["minimum_extraction_fraction"], hp_cooling=bool(hp) and statistics.fmean(r["kinetic_energy_eV"] for r in hp) <= acceptance["max_hp_mean_kinetic_energy_ev"], lp_compression=bool(grouped["pre_extraction"]) and m["pre_extraction"]["axial_sigma_mm"] <= acceptance["max_pre_extraction_axial_sigma_mm"], extraction_energy=bool(grouped["extraction_exit"]) and acceptance["minimum_extraction_mean_energy_ev"] <= m["extraction_exit"]["mean_kinetic_energy_ev"] <= acceptance["maximum_extraction_mean_energy_ev"])
    checks["lp_occupation"]=bool(lp) and len(lp)==len(grouped["pre_extraction"])
    summary=dict(schema_version=1,role="ion_processor_functional_summary",status="success" if all(checks.values()) else "failed",qualification="unqualified_simplified_native_electrodes",actual_particle_count=n,capture_fraction=len(hp)/n,extraction_fraction=len(grouped["extraction_exit"])/n,checks=checks,metrics=metrics,identity_validation=validation,terminal_reasons={reason:sum(r["terminal_reason"]==reason for r in grouped["terminal"]) for reason in sorted({r["terminal_reason"] for r in grouped["terminal"]})})
    if transformed:
        summary["frame_id"] = transform.to_frame_id
        summary["compression_axis"] = "native guide axis = project y"
        summary["canonical_column_semantics"] = {
            "radial_position_mm": "distance from project world z axis: hypot(world x, world y)",
            "divergence_angle_deg": "angle to project world z axis using absolute vz",
            "max_rod_radius_mm": "native local radial acceptance parameter; not a world-origin cylinder gate",
        }
        summary["native_acceptance_domain"] = {
            "frame_id": transform.from_frame_id,
            "guide_axis": "local x = project world y",
            "radial_rule_before_extraction": "abs(local y), abs(local z) <= boundary_radius_mm",
            "boundary_radius_mm": b["geometry"]["boundary_radius_mm"],
            "extraction_plane_local_y_mm": b["geometry"]["extraction_end_y_mm"],
        }
    summary["source_profile"] = profile
    summary["status"] = "success" if all(checks.values()) else "failed"
    summary["functional_status"] = profile + ("_pass" if all(checks.values()) else "_incomplete")
    summary["functional_baseline_eligible"] = profile == "functional"
    if "injected_source" in c:
        summary.update(mother_particle_count=c["injected_source"]["mother_particle_count"],
            upstream_census=read_json(run/"inputs/upstream_mother_census.json"),
            claim="measured IP continuation of real upstream mechanical exits; state_handoff, not joint field solve")
    write_json(run / "summary.json",summary)
    # Legacy terminal runs remain immutable and have no new diagnostic contract.
    # For newly prepared runs these are required outputs; errors preserve the
    # measured physical summary and make execution incomplete at the runner.
    if (run / "inputs/diagnostics.json").is_file():
        from msplatform.workflows.ion_processor.diagnostics import export_diagnostics
        export_diagnostics(run)
    if (run / "inputs/field_diagnostics.json").is_file():
        from msplatform.workflows.ion_processor.field_diagnostics import export_field_diagnostics
        export_field_diagnostics(run)
    # New native runs always provide passive per-step force/collision evidence.
    # Historical sealed runs keep their own frozen analysis implementation.
    if "extraction_force_audit" in c:
        from msplatform.workflows.ion_processor.extraction_force_budget import export_force_budget
        export_force_budget(run)
    return summary
