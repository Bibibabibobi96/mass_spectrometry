"""Author the measured-centroid prism research target."""
from __future__ import annotations

import copy
import math
from msplatform.contracts.particle_physics import kinetic_energy_ev
from msplatform.io.strict_json import require_number


def author_measured_centroid_prism_target(*, event_field_audit: dict, audit_request: dict,
        controller_projection: dict, source_receipt: dict, trajectory_contract: dict, design_target: dict,
        stripe_1_voltage_v: float, input_records: dict) -> dict:
    """Freeze one source-specific engineering reference using the existing L0 Psi.

    The caller verifies and freezes the parsed JSON documents and input records
    through the existing manifest APIs before calling. This pure function checks
    their internal identities; it performs no I/O. The target is immutable per anchor;
    this authoring inverse is not a P/S controller or an energy acceptance gate.
    """
    from scipy.optimize import brentq
    from msplatform.contracts.particle_state import DERIVED_ABSOLUTE_TOLERANCE, DERIVED_RELATIVE_TOLERANCE
    from msplatform.components.parallel_mirror_dual_stripe_mr_tof.dual_stripe_l0 import (
        converging_design_potential_delta_v, resolve_converging_prism_target,
    )

    documents = dict(event_field_audit=event_field_audit, audit_request=audit_request,
                     controller_projection=controller_projection, source_receipt=source_receipt,
                     trajectory_contract=trajectory_contract, design_target=design_target)
    if set(input_records) != set(documents):
        raise ValueError("Target authoring requires all six frozen input records")
    for record in input_records.values():
        if (not isinstance(record, dict) or not isinstance(record.get("path"), str)
                or type(record.get("bytes")) is not int or record["bytes"] <= 0
                or not isinstance(record.get("sha256"), str) or len(record["sha256"]) != 64
                or any(c not in "0123456789abcdefABCDEF" for c in record["sha256"])):
            raise ValueError("Frozen input file identity is incomplete")

    def equal_record(a: dict, b: dict) -> bool:
        return a.get("bytes") == b.get("bytes") and str(a.get("sha256", "")).lower() == str(b.get("sha256", "")).lower()

    def close(a: float, b: float) -> bool:
        # Canonical derived-value consistency, not a trajectory energy tolerance.
        return math.isclose(a, b, rel_tol=DERIVED_RELATIVE_TOLERANCE, abs_tol=DERIVED_ABSOLUTE_TOLERANCE)

    if (event_field_audit.get("schema_version") != 1
            or event_field_audit.get("role") != "mrtof_actual_probe_event_energy_field_audit"
            or event_field_audit.get("status") != "reported"
            or event_field_audit.get("potential_authority") != "actual_materialized_scalar_native_PA__scalar_adapter_raw_sample"
            or audit_request.get("role") != "mrtof_actual_probe_event_field_audit_request" or audit_request.get("schema_version") != 1
            or not equal_record(event_field_audit["inputs"]["request"], input_records["audit_request"])
            or source_receipt.get("role") != "mrtof_measured_exit_centroid_probe_source"
            or source_receipt.get("counts") != dict(source=1, transferred=1, not_transferred=0)
            or design_target.get("role") != "mrtof_measured_centroid_closure_target_authority"):
        raise ValueError("Actual same-binding constructed-probe evidence is required")
    request_inputs = audit_request["inputs"]
    if (not equal_record(request_inputs["source_receipt"], input_records["source_receipt"])
            or not equal_record(request_inputs["canonical_source"], source_receipt["outputs"]["component_particle_state"])):
        raise ValueError("Actual audit names a different canonical probe source")
    if (controller_projection.get("role") != "mrtof_measured_exit_centroid_controller_projection"
            or not equal_record(request_inputs["projection"], input_records["controller_projection"])
            or not equal_record(controller_projection["inputs"]["source_receipt"], input_records["source_receipt"])):
        raise ValueError("Audit names a different controller projection")
    field = controller_projection["field_authority_projection"]
    if (field.get("role") != "mrtof_measured_centroid_live_field_projection"
            or not equal_record(field["binding_record"], request_inputs["candidate_binding"])):
        raise ValueError("Birth and clean evidence must use one frozen actual binding")
    voltages = field["analyzer_electrode_voltages_v"]
    stripe = require_number(stripe_1_voltage_v, "S1 anchor")
    if len(voltages) != 20 or voltages[10] != stripe or voltages[11] != stripe or voltages[12:14] != [0, 0]:
        raise ValueError("Target anchor must retain actual S1 and grounded S2")
    mass, charge = require_number(source_receipt["mass_amu"], "mass"), require_number(source_receipt["charge_state"], "charge")
    if mass <= 0 or charge <= 0 or mass != audit_request["mass_amu"] or charge != audit_request["charge_state"]:
        raise ValueError("Target authoring requires the same positive-ion species")
    rows, points = event_field_audit["samples"], audit_request["points"]
    if (not rows or len({r["sample_id"] for r in rows}) != len(rows)
            or {r["sample_id"] for r in rows} != {p["sample_id"] for p in points} or len(points) != len(rows)):
        raise ValueError("Actual event-field population does not close")
    requested = {p["sample_id"]: p for p in points}
    energies = {}
    for row in rows:
        point = requested[row["sample_id"]]
        for key in ("event", "instrument_time_us", "position_mm", "velocity_m_s", "kinetic_energy_per_charge_ev"):
            if row[key] != point[key]:
                raise ValueError("Audit event differs from its frozen actual query")
        position, velocity = row["position_mm"], row["velocity_m_s"]
        if len(position) != 3 or len(velocity) != 3:
            raise ValueError("Complete Cartesian state required")
        for value in [*position, *velocity, row["instrument_time_us"]]:
            require_number(value, "actual event state")
        axes = [kinetic_energy_ev(mass, *(velocity[i] if i == a else 0 for i in range(3)))/charge for a in range(3)]
        kinetic = require_number(row["kinetic_energy_per_charge_ev"], "event K/q")
        phi = require_number(row.get("phi_v"), "actual electrostatic phi")
        if not close(sum(axes), kinetic) or not close(kinetic+phi, require_number(row["k_over_q_plus_phi_v"], "event H/q")):
            raise ValueError("Actual K/velocity/phi energy ledger is inconsistent")
        energies[row["sample_id"]] = axes
    births = [r for r in rows if r["sample_id"] == "source_centroid" and r["event"] == "source_centroid"]
    if len(births) != 1:
        raise ValueError("Unique canonical centroid birth required")
    birth = births[0]
    birth_k = require_number(source_receipt["centroid_kinetic_energy_eV"], "canonical centroid K")/charge
    h = birth_k+birth["phi_v"]
    if (not close(birth_k, birth["kinetic_energy_per_charge_ev"])
            or birth["instrument_time_us"] != source_receipt["solver_epoch_instrument_time_us"]
            or not close(h, require_number(event_field_audit["source_centroid_h_over_q_v"], "source H/q"))):
        raise ValueError("Actual birth ledger differs from canonical centroid")
    reference = design_target["prism_handoff_target"]
    contract = copy.deepcopy(trajectory_contract)
    all_authored = ("mode", "axial_energy_per_charge_v", "mirror_axial_width_w_mm",
        "slow_energy_reference_per_charge_v", "total_energy_reference_per_charge_v", "clean_reference_slow_energy_per_charge_v")
    contract["prism_transport"]["handoff_target"] = {key:reference[key] for key in all_authored}
    bridges = contract["dual_stripe"]["beam_slot_y_bridges_mm"]
    geometry = dict(mirror_convergence_transform=contract["mirror"]["convergence_transform"], metadata=dict(
        ion_foil_slot_bridge_from_min_y_mm=bridges["from_min_y_mm"], ion_foil_slot_bridge_from_max_y_mm=bridges["from_max_y_mm"]))
    if resolve_converging_prism_target(contract, geometry) != reference:
        raise ValueError("MR design model geometry or tolerance differs from its frozen contract")
    lo, hi = reference["clean_y_interval_mm"]
    clean_rows = [r for r in rows if r["event"] == "central_plane_directional"
        and r["instrument_time_us"] > birth["instrument_time_us"] and r["position_mm"][2] == 0
        and lo < r["position_mm"][1] < hi and r["velocity_m_s"][1] > 0 and r["velocity_m_s"][2] < 0]
    if not clean_rows:
        raise ValueError("First forward clean negative-z reference was not observed")
    clean = min(clean_rows, key=lambda r: r["instrument_time_us"])
    ex = energies[clean["sample_id"]][0]
    available = require_number(h-clean["phi_v"]-ex, "available YZ energy")
    ws = require_number(reference["slow_energy_reference_per_charge_v"], "MR design Ws")
    if available <= 0 or ws <= 0:
        raise ValueError("Positive available YZ energy and MR design action required")

    def residual(energy: float) -> float:
        target = dict(reference, axial_energy_per_charge_v=energy)
        return available-energy+converging_design_potential_delta_v(target, stripe, clean["position_mm"][1])-ws

    # Physical open interval; no arbitrary search range or energy acceptance.
    lower = math.nextafter(max(0.0, stripe), math.inf)
    upper = math.nextafter(available, 0.0)
    if lower >= upper or not math.isfinite(residual(lower)) or not math.isfinite(residual(upper)) or residual(lower)*residual(upper) > 0:
        raise ValueError("No bracketed physical fast/slow partition in the existing L0 model")
    fast = float(brentq(residual, lower, upper))
    slow = available-fast
    if not 0 < fast < available or not slow > 0 or not close(slow+converging_design_potential_delta_v(
            dict(reference, axial_energy_per_charge_v=fast), stripe, clean["position_mm"][1]), ws):
        raise ValueError("No physical self-consistent target partition")
    authored_keys = ("mode", "axial_energy_per_charge_v", "mirror_axial_width_w_mm", "slow_energy_reference_per_charge_v")
    contract["prism_transport"]["handoff_target"] = {k: reference[k] for k in authored_keys}
    contract["prism_transport"]["handoff_target"].update(axial_energy_per_charge_v=fast,
        total_energy_reference_per_charge_v=available, clean_reference_slow_energy_per_charge_v=slow)
    resolved = resolve_converging_prism_target(contract, geometry)
    target = copy.deepcopy(design_target)
    target["prism_handoff_target"] = resolved
    target["inputs"].update(interface_energy_field_audit=copy.deepcopy(input_records["event_field_audit"]),
                             trajectory_contract=copy.deepcopy(input_records["trajectory_contract"]))
    target["source_energy_ledger"] = dict(mean_particle_kinetic_energy_ev_per_q=require_number(source_receipt["mean_particle_kinetic_energy_eV"],"mother mean K")/charge,
        kinetic_energy_of_mean_velocity_ev_per_q=birth_k, centroid_joint_phi_v=birth["phi_v"], centroid_joint_hamiltonian_ev_per_q=h)
    target["qualification"] = "immutable_anchor_source_specific_L0_engineering_target__not_3D_action_or_N100_energy_acceptance"
    return dict(schema_version=1, role="mrtof_measured_centroid_prism_target_authoring", inputs=copy.deepcopy(input_records),
        target_authority=target, authoring_ledger=dict(binding=copy.deepcopy(request_inputs["candidate_binding"]),
            birth_sample_id=birth["sample_id"], clean_sample_id=clean["sample_id"], clean_position_mm=copy.deepcopy(clean["position_mm"]),
            stripe_1_anchor_voltage_v=stripe, source_h_over_q_v=h, actual_clean_phi_v=clean["phi_v"], actual_clean_ex_ev_per_q=ex,
            available_clean_yz_energy_ev_per_q=available, observed_clean_ky_ev_per_q=energies[clean["sample_id"]][1],
            observed_clean_delta_h_v=clean["k_over_q_plus_phi_v"]-h, fast_reference_ev_per_q=fast, slow_reference_ev_per_q=slow,
            self_consistency_residual_ev_per_q=residual(fast), clean_target_angle_degrees=math.degrees(math.atan2(math.sqrt(slow),math.sqrt(fast))),
            model_total_energy_semantics="YZ available energy after subtracting physical phi and Ex; not full 3D Hamiltonian",
            p2_angle_semantics="retained historical engineering diagnostic; clean angle is not a P2-plane target",
            source_velocity_rescaled=False, target_updates="new explicit version and cleared columns; never move within one anchor"),
        physical_matching_qualified=False, energy_acceptance="not_declared")

# Official SIMION 8.0/8.1 FLY2 and initialize APIs; also present in SIMION 2020
# docs/simion.chm (fly2_file.html, time.html, particle_initial_conditions.html).
# Reviewed 2026-10-16: https://simion.com/info/time.html and /fly2_file.html.
# TOF is solver time from zero, not time since each particle's TOB.
