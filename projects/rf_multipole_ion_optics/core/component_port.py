"""Compile a provided multipole exit port from one frozen resolved design."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from common.contracts.machine_contracts import ContractError, validate_schema
from common.contracts.file_identity import file_sha256
from common.contracts.canonical_clock_authority import validate_clock_authority
from common.contracts.particle_state import PARTICLE_STATE_COLUMNS
from projects.rf_multipole_ion_optics.core.compile_design_request import resolved_design_sha256
from projects.rf_multipole_ion_optics.core.interface_geometry import transport_numerical_domain, transport_observations
from projects.rf_multipole_ion_optics.simion.simion_geometry import physical_electrode_view



def load_transport_producer_result(manifest: Mapping[str, Any], base: Path) -> dict[str, Any]:
    """Read the sealed transport result, separating complete states from qualification.

    A normal successful transport publication already proves execution completion.
    A scientific failure additionally requires the explicit normal-path completion
    declaration and the manifest-bound current evidence evaluation. Generic failed
    or interrupted publications do not qualify as measured-state producers.
    """
    from common.contracts.verify_run_manifest import record_path, verify_record

    status = manifest.get("status")
    if status not in {"success", "failed"}:
        raise ContractError("transport producer must have a complete scientific result")
    run = record_path(manifest["run_config"], base_dir=base).parent
    summary_path = run / "summary.json"
    evaluation_path = run / "results/evidence_evaluation.json"
    selected = {}
    for record in manifest.get("outputs", []):
        path = record_path(record, base_dir=base)
        if path in {summary_path, evaluation_path}:
            if path in selected:
                raise ContractError("transport result must have one manifest record per consumed file")
            selected[path] = record

    consumed = {}

    def read_result(path: Path, name: str) -> dict:
        if path not in selected:
            raise ContractError("transport manifest lacks its " + name)
        record = selected[path]
        verify_record(name, record, base_dir=base)
        consumed[name] = {**record, "path": str(path)}
        return json.loads(path.read_text(encoding="utf-8-sig"))

    summary = read_result(summary_path, "summary")
    if (summary.get("schema_version") != 1
            or summary.get("role") != "multipole_simion_finite_3d_transport_summary"
            or summary.get("status") != status or summary.get("project_id") != manifest["project"]
            or not isinstance(summary.get("design_profile_id"), str)
            or not summary["design_profile_id"]
            or ("native_execution_complete" in summary and summary["native_execution_complete"] is not True)):
        raise ContractError("transport summary identity or completion differs")
    qualification = summary.get("qualification_status")
    if "checks" in summary and (not isinstance(summary["checks"], dict)
                                or any(type(value) is not bool for value in summary["checks"].values())):
        raise ContractError("transport summary checks must be declared boolean results")
    checks = {}
    if status == "failed" and (summary.get("native_execution_complete") is not True
                               or qualification != "FAIL" or "checks" not in summary):
        raise ContractError("failed transport lacks a complete native scientific-result declaration")
    if qualification in {"PASS", "FAIL"}:
        evaluation = read_result(evaluation_path, "evidence_evaluation")
        validate_schema(evaluation, "multipole_evidence_evaluation.schema.json")
        checks = evaluation["checks"]
        expected = "PASS" if all(checks.values()) else "FAIL"
        if (evaluation["project_id"] != summary["project_id"]
                or evaluation["design_profile_id"] != summary["design_profile_id"]
                or evaluation["status"] != expected or qualification != expected
                or status != ("success" if expected == "PASS" else "failed")
                or ("checks" in summary and summary["checks"] != checks)):
            raise ContractError("transport scientific checks or qualification differ")
    elif qualification != "UNQUALIFIED" or status != "success" or summary.get("checks", {}):
        raise ContractError("transport qualification is not its declared scientific result")
    return dict(source_scientific_status=status, checks=checks,
                qualification_status=qualification, input_records=consumed)


def build_assembly_interface(resolved_design: Mapping[str, Any], *, geometry_profile_id: str) -> dict[str, Any]:
    """Publish the frozen real rod/shell faces independently of observations."""
    validate_schema(dict(resolved_design), "multipole_resolved_design.schema.json")
    if resolved_design_sha256(resolved_design) != resolved_design["resolved_sha256"]:
        raise ContractError("multipole mechanical interface resolved design hash is stale")
    geometry = resolved_design["geometry_mm"]
    if geometry["enclosure"]["model"] == "rectangular_reference_enclosure_v1":
        raise ContractError("the independent rectangular reference has no bare/shell assembly interface")
    result = dict(schema_version=1, role="component_geometry_interface",
        project_id=resolved_design["identity"]["project_id"],
        variant_id="bare_rods" if geometry["enclosure"]["model"] == "bare" else "cylindrical_grounded_shell",
        geometry_profile_id=geometry_profile_id, local_frame_id=resolved_design["coordinate"]["coordinate_id"],
        length_unit="mm", ports=geometry["enclosure_layout"]["ports"],
        component_electrodes=[dict(component_electrode_id=row['native_electrode_id'], role=row['scientific_id'])
                              for row in physical_electrode_view(dict(resolved_design))])
    validate_schema(result, "component_geometry_interface.schema.json")
    return result

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
        source = {int(r["particle_id"]): r for r in csv.DictReader(handle)}
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
    return dict(schema_version=1, role="multipole_mechanical_exit_census", status="PASS",
                mother_count=len(source), exit_count=len(exits), non_exit_count=len(source)-len(exits),
                mother_particle_ids=sorted(source), exit_particle_ids=sorted(exits),
                non_exit_particle_ids=sorted(set(source)-set(exits)),
                terminal_reasons={str(particle): row["terminal_reason"] for particle, row in sorted(terminals.items())},
                scope="actual native mechanical exit observations; old handoff/census statistics remain separate")
