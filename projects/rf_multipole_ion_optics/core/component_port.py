"""Compile a provided multipole exit port from one frozen resolved design."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from msplatform.analysis.particle_census import partition_cohort
from common.contracts.machine_contracts import ContractError
from common.contracts.file_identity import file_sha256
from common.contracts.canonical_clock_authority import validate_clock_authority
from projects.rf_multipole_ion_optics.analysis.rf_event_table_validation import PARTICLE_STATE_COLUMNS
from msplatform.components.rf_multipole.assembly_interface import build_assembly_interface as build_assembly_interface
from projects.rf_multipole_ion_optics.core.interface_geometry import transport_numerical_domain, transport_observations



def prepare_exit_observation_inputs(run: Path, resolved: Mapping[str, Any], *, design_profile_id: str, cell_z_mm: float) -> dict[str, Any]:
    """Freeze a standalone absolute clock and, for an open model, its real exit guard.

    Standalone multipole source birth_time_s and RF phases already use the
    zero-based instrument axis directly. Epoch zero is that protocol origin,
    not the first ion's birth and not a per-particle clock reset.
    """
    inputs = run/"inputs"
    def write(name: str, value: Any) -> Path:
        path = inputs/name
        if path.exists():
            raise ContractError(f"refuse to overwrite frozen multipole input: {name}")
        path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")
        return path
    epoch = write("instrument_epoch.json", dict(instrument_time_us=0.))
    authority = dict(schema_version=1, role="canonical_clock_authority", clock_epoch_id="instrument_clock_epoch_v1",
        instrument_time_unit="us", canonical_time_basis="instrument_epoch_absolute_time",
        authority=dict(path="inputs/instrument_epoch.json", sha256=file_sha256(epoch), field="instrument_time_us"),
        solver_local_time_basis="elapsed_time_from_zero_us", adapter_materialization="instrument_time_us_equals_authority_epoch_plus_solver_elapsed_once",
        handoff_policy="preserve_instrument_time_us_and_clock_epoch_id", legacy_new_campaign_allowed=False)
    clock = write("clock_authority.json", authority)
    validate_clock_authority(clock, run)
    if resolved["geometry_mm"]["enclosure"]["model"] == "rectangular_reference_enclosure_v1":
        return dict(mechanical_exit_enabled=False)
    interface = build_assembly_interface(resolved, geometry_profile_id=design_profile_id)
    port = interface["ports"]["mechanical_exit"]
    surface = float(port["center_mm"][2])
    section = port["cross_section"]
    aperture = float(section["radius_mm"]) if section["shape"] == "circle" else None
    if not math.isfinite(cell_z_mm) or cell_z_mm <= 0:
        raise ContractError("positive finite exit observation axial cell required")
    observations = transport_observations(resolved)
    last_observation = max(surface, float(observations["handoff_plane_z_mm"]), float(observations["census_plane_z_mm"]))
    domain_end = float(transport_numerical_domain(resolved)["z_max_mm"])
    if domain_end < last_observation + 2*cell_z_mm - 1e-12:
        raise ContractError("real exit observation requires two axial cells beyond the last declared observation")
    plan = dict(schema_version=1, role="multipole_mechanical_exit_observation", frame_id=interface["local_frame_id"],
        mechanical_exit_z_mm=surface, aperture_radius_mm=aperture,
        numerical_guard_z_mm=last_observation+cell_z_mm, numerical_domain_end_z_mm=domain_end,
        guard_offset_axial_cells=1, minimum_domain_extension_axial_cells=2, cell_z_mm=cell_z_mm,
        guard_implementation="native_callback_stop_inside_PA__no_absorbing_electrode",
        state_columns=PARTICLE_STATE_COLUMNS, crossing_event="mechanical_exit", terminal_event="terminal",
        native_bracket_events=["mechanical_exit_step_before", "mechanical_exit_step_after"],
        interpolation="actual_native_step_bracket_linear_state__no_handoff_extrapolation",
        terminal_state_scope="native_terminate_or_last_other_actions__not_exact_surface_contact",
        qualification="functional interface observation; numerical boundary convergence not established")
    write("mechanical_exit_interface.json", interface)
    write("mechanical_exit_observation.json", plan)
    return dict(mechanical_exit_enabled=True, **plan)


def validate_exit_observations(state_path: Path, source_path: Path, plan: Mapping[str, Any]) -> dict[str, Any]:
    """Validate native real-exit records and terminal coverage of every original ID."""
    with source_path.open(encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    source_ids = [int(row["particle_id"]) for row in source_rows]
    try:
        partition_cohort(source_ids, ((pid, "source") for pid in source_ids),
                         categories=("source",), relative_weights=None)
    except ValueError as exc:
        raise ContractError("mechanical exit source requires unique original mother IDs") from exc
    source = dict(zip(source_ids, source_rows, strict=True))
    with state_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != PARTICLE_STATE_COLUMNS:
            raise ContractError("mechanical exit state columns differ from the frozen canonical projection")
        rows = list(reader)
    exits, terminals, brackets = {}, {}, {}
    for row in rows:
        particle = int(row["particle_id"])
        if particle not in source:
            raise ContractError("mechanical exit record contains an ID outside the original cohort")
        values = {k: float(row[k]) for k in PARTICLE_STATE_COLUMNS if k not in {"particle_id", "event", "status", "terminal_reason"}}
        if not all(math.isfinite(v) for v in values.values()):
            raise ContractError("mechanical exit record contains nonfinite state")
        birth = float(source[particle]["birth_time_s"])*1e6
        if not math.isclose(values["time_us"]-values["elapsed_time_us"], birth, rel_tol=1e-10, abs_tol=1e-9):
            raise ContractError("mechanical exit clock does not preserve the original birth")
        if row["event"] in {"mechanical_exit_step_before", "mechanical_exit_step_after"}:
            pair = brackets.setdefault(particle, {})
            if row["event"] in pair:
                raise ContractError("duplicate mechanical exit native bracket")
            pair[row["event"]] = values
        elif row["event"] == "mechanical_exit":
            if particle in exits or row["status"] != "transmitted" or row["terminal_reason"] != "none":
                raise ContractError("mechanical exit crossing identity/status is invalid")
            if abs(values["axial_z_mm"]-plan["mechanical_exit_z_mm"]) > 1e-9 or values["velocity_axial_m_s"] <= 0:
                raise ContractError("mechanical exit crossing is outside its real plane/direction")
            if plan["aperture_radius_mm"] is not None and math.hypot(values["transverse_x_mm"], values["transverse_y_mm"]) > plan["aperture_radius_mm"]+1e-9:
                raise ContractError("mechanical exit crossing is outside the physical bore")
            exits[particle] = row
        elif row["event"] == "terminal":
            if particle in terminals:
                raise ContractError("duplicate mechanical exit terminal")
            terminals[particle] = row
        else:
            raise ContractError("unknown mechanical exit observation event")
    if set(terminals) != set(source):
        raise ContractError("mechanical exit observations do not close the complete mother cohort")
    for particle, row in exits.items():
        pair = brackets.get(particle, {})
        if set(pair) != {"mechanical_exit_step_before", "mechanical_exit_step_after"}:
            raise ContractError("mechanical exit lacks its actual native step bracket")
        before, after = pair["mechanical_exit_step_before"], pair["mechanical_exit_step_after"]
        plane = plan["mechanical_exit_z_mm"]
        if not before["axial_z_mm"] < plane <= after["axial_z_mm"] or before["time_us"] >= after["time_us"]:
            raise ContractError("mechanical exit native states do not bracket the forward crossing")
        fraction = (plane-before["axial_z_mm"])/(after["axial_z_mm"]-before["axial_z_mm"])
        for key in ("time_us", "transverse_x_mm", "transverse_y_mm", "velocity_axial_m_s", "velocity_x_m_s", "velocity_y_m_s", "kinetic_energy_eV"):
            expected = before[key]+fraction*(after[key]-before[key])
            # Each native endpoint and crossing is serialized with %.12g.
            if not math.isclose(float(row[key]), expected, rel_tol=2e-11, abs_tol=1e-9):
                raise ContractError(f"mechanical exit {key} differs from its native bracket interpolation")
        if float(terminals[particle]["time_us"]) < float(row["time_us"]):
            raise ContractError("real terminal precedes its mechanical exit crossing")
    if set(brackets) != set(exits):
        raise ContractError("mechanical exit native brackets do not match crossing IDs")
    census = partition_cohort(sorted(source),
        ((pid, "exit" if pid in exits else "non_exit_terminal") for pid in terminals),
        categories=("exit", "non_exit_terminal"), relative_weights=None)
    # Preserve the published census contract; non-exit is not a physical loss classification.
    return dict(schema_version=1, role="multipole_mechanical_exit_census", status="PASS",
                mother_count=census["mother_count"], exit_count=census["counts"]["exit"],
                non_exit_count=census["counts"]["non_exit_terminal"],
                mother_particle_ids=census["mother_particle_ids"],
                exit_particle_ids=census["particle_ids_by_category"]["exit"],
                non_exit_particle_ids=census["particle_ids_by_category"]["non_exit_terminal"],
                terminal_reasons={str(particle): row["terminal_reason"] for particle, row in sorted(terminals.items())},
                scope="actual native mechanical exit observations; old handoff/census statistics remain separate")
