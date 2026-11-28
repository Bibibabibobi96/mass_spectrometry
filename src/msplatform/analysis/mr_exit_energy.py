"""Compare measured IP and reference MR energy evidence without solver calls."""
from __future__ import annotations

import csv
import statistics
from pathlib import Path
from typing import Any

from msplatform.analysis.particle_census import partition_cohort
from msplatform.contracts.particle_physics import kinetic_energy_ev
from msplatform.contracts.particle_state import load_component_particle_state_csv
from msplatform.results.component_exit_history import validate_component_exit_binding
from msplatform.results.mr_reference import (
    _bound_file, _finite, _identity, _read,
)


def _distribution(values: list[float]) -> dict[str, Any]:
    return {"count": len(values), "mean": statistics.fmean(values),
            "population_sigma": statistics.pstdev(values),
            "minimum": min(values), "maximum": max(values)}


def _exit_distributions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    energy, velocity = {}, {}
    for axis in "xyz":
        velocity[axis] = _distribution([row[f"velocity_{axis}_m_s"] for row in rows])
        values = [kinetic_energy_ev(row["mass_amu"], *(
            row[f"velocity_{other}_m_s"] if other == axis else 0.0 for other in "xyz"
        )) / abs(row["charge_state"]) for row in rows]
        energy[axis] = _distribution(values)
    total = [kinetic_energy_ev(row["mass_amu"], *(
        row[f"velocity_{axis}_m_s"] for axis in "xyz"
    )) / abs(row["charge_state"]) for row in rows]
    return {"statistic_basis": "unweighted_recorded_exit_particles_no_recentring_or_filtering",
            "energy_unit": "eV_per_abs_charge_state", "velocity_unit": "m_s",
            "directional_energy": energy, "total_energy": _distribution(total), "velocity": velocity}


def _reference_exit(reference_mr_run: Path) -> tuple[float, dict[str, Any], dict[str, Any]]:
    # Reuse the existing exact manifest projection; no PA payload is consumed.
    from msplatform.results.mr_reference import verified_reference
    from msplatform.analysis.mr_observations import parse_events
    provider_path = verified_reference(reference_mr_run, "simion/accelerator_provider_runtime_receipt.json")
    source_path = verified_reference(reference_mr_run, "simion/bunch_source_receipt.json")
    log_path = verified_reference(reference_mr_run, "logs/native_two_prism_flight.log")
    provider, source = _read(provider_path), _read(source_path)
    state_path = _bound_file(source["state_table"], source_path.parent)
    with state_path.open(encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    by_id = {int(row["particle_id"]): row for row in source_rows}
    expected = set(source["expected_particle_ids"])
    if len(by_id) != len(source_rows) or set(by_id) != expected or len(expected) != source["particle_count"]:
        raise ValueError("Reference OA complete source IDs do not close")
    exits = [event for event in parse_events(log_path.read_text(encoding="utf-8-sig"))
             if event["kind"] == "accelerator_geometric_exit"]
    if len(exits) != len(expected) or {int(event["ion"]) for event in exits} != expected:
        raise ValueError("Reference OA geometric-exit IDs do not close")
    rows = []
    for event in exits:
        particle = by_id[int(event["ion"])]
        if event["z_mm"] != 0 or event["vz_mm_us"] >= 0:
            raise ValueError("Reference OA exit must be at geometric z=0 toward negative z")
        row = {"mass_amu": float(particle["mass_th"]), "charge_state": particle["charge_e"]}
        # Canonical physical charge may be serialized as a floating number.
        charge = float(row["charge_state"])
        if not charge.is_integer() or charge == 0 or row["mass_amu"] <= 0:
            raise ValueError("Reference OA species is invalid")
        row["charge_state"] = int(charge)
        row.update({f"velocity_{axis}_m_s": event[f"v{axis}_mm_us"] * 1000 for axis in "xyz"})
        rows.append(row)
    target = _finite(provider["mrtof_projection"]["target_axial_energy_per_charge_v"], "MR axial target")
    if target <= 0:
        raise ValueError("MR axial target must be positive")
    source_energy = _distribution([float(row["kinetic_energy_ev"]) / abs(float(row["charge_e"])) for row in source_rows])
    reference = {"counts": {"source": len(expected), "geometric_exit": len(rows)},
                 "surface": "accelerator_geometric_exit_z0_not_PA_safe_exit",
                 "source_release_total_energy_per_charge": source_energy,
                 "source_release_distribution": source.get("release_energy_distribution"),
                 "exit": _exit_distributions(rows)}
    identities = {name: _identity(path) for name, path in (
        ("reference_provider", provider_path), ("reference_source", source_path),
        ("reference_source_states", state_path), ("reference_log", log_path),
        ("reference_manifest", reference_mr_run / "run_manifest.json"))}
    return target, reference, identities


def compare_measured_exit_energy(component_receipt_path: Path, reference_mr_run: Path) -> dict[str, Any]:
    """Compare a new measured IP exit to frozen MR target and actual OA cohort.

    No source vector is changed. Reference and IP distributions use eV/|q|;
    all mother IDs and losses are retained. A centroid residual and empirical
    spread are evidence, not an invented acceptance tolerance or performance
    PASS. This function reads only manifest/receipt-bound light evidence.
    """
    component = _read(component_receipt_path)
    validate_component_exit_binding(component)
    for record in component["inputs"].values():
        _bound_file(record, component_receipt_path.parent)
    state_path = _bound_file(component["outputs"]["component_states"], component_receipt_path.parent)
    census_path = _bound_file(component["outputs"]["mother_census"], component_receipt_path.parent)
    table = load_component_particle_state_csv(state_path)
    rows, validation = table.rows, table.report
    with census_path.open(encoding="utf-8-sig", newline="") as handle:
        census = list(csv.DictReader(handle))
    ids = {row["particle_id"] for row in rows}
    partition = partition_cohort([int(row["particle_id"]) for row in census],
        [(int(row["particle_id"]), row["transfer_status"]) for row in census],
        categories=("transferred", "not_transferred"), relative_weights=None)
    transferred = set(partition["particle_ids_by_category"]["transferred"])
    lost = set(partition["particle_ids_by_category"]["not_transferred"])
    if (ids != transferred or ids != set(component["transferred_particle_ids"])
            or lost != set(component.get("not_transferred_particle_ids", component.get("lost_particle_ids", [])))
            or component["counts"] != {"source": len(census), "transferred": len(rows), "not_transferred": len(lost)}):
        raise ValueError("IP complete mother census and energy cohort do not close")
    if (validation["frame_ids"] != [component["frame_id"]]
            or validation["clock_epoch_ids"] != [component["clock_epoch_id"]]
            or any(row["velocity_z_m_s"] >= 0
                   or row["source_component_id"] != component["source_instance_id"]
                   or row["target_component_id"] != component["target_instance_id"]
                   or row["state_event"] != "extraction_exit" for row in rows)):
        raise ValueError("IP measured exit frame, clock or negative-z direction differs")
    target, reference, identities = _reference_exit(reference_mr_run)
    measured = _exit_distributions(rows)
    axial = measured["directional_energy"]["z"]
    ref_axial = reference["exit"]["directional_energy"]["z"]
    residual = axial["mean"] - target
    sigma = ref_axial["population_sigma"]
    return {"schema_version": 1, "role": "mrtof_measured_exit_energy_comparison",
            "status": "characterized_without_acceptance_tolerance", "qualification": "energy_distribution_comparison_only",
            "energy_unit": "eV_per_abs_charge_state", "target_axial_energy_per_charge_v": target,
            "target_basis": "historical_OA_provider_axial_design_seed_not_unique_IP_or_total_energy_target",
            "ip_counts": component["counts"], "ip_transferred_particle_ids": sorted(ids), "ip_not_transferred_particle_ids": sorted(lost),
            "ip_exit": measured, "reference_oa": reference,
            "centroid_residual_to_target": residual,
            "centroid_residual_to_reference_oa_mean": axial["mean"]-ref_axial["mean"],
            "total_energy_centroid_difference_to_reference_oa": measured["total_energy"]["mean"]-reference["exit"]["total_energy"]["mean"],
            "directional_energy_centroid_difference_to_reference_oa": {
                axis: measured["directional_energy"][axis]["mean"]-reference["exit"]["directional_energy"][axis]["mean"]
                for axis in "xyz"},
            "nominal_total_energy_target": {
                "status": "undefined_no_explicit_same_surface_total_energy_target", "value": None,
                "reason": "Do not add historical axial seed to OA release Ey: release and exit are distinct potential/reference surfaces."},
            "electrostatic_energy_reference": {
                "invariant": "K_per_abs_charge_plus_charge_sign_times_potential",
                "positive_ion_form": "K/q + phi = constant_in_static_electrostatic_transport",
                "potential_difference_compensated": False,
                "comparison_basis": "raw_measured_kinetic_energies_at_OA_geometric_z0_and_IP_recorded_exit_z0",
                "required_for_downstream_comparison": "Determine potentials and signed directions at the same Prism design/reference surface before interpreting kinetic-energy differences."},
            "centroid_residual_in_reference_population_sigma": residual/sigma if sigma > 0 else None,
            "centroid_match_accepted": None,
            "matching_criterion": "Report axial and total-energy differences only. Evaluate subsequent Prism design using K/q+phi and signed direction at its specified surface; no tolerance or acceptance is assigned.",
            "caveats": [
                "Reference population sigma is empirical beam dispersion, not a centroid acceptance tolerance or numerical error bound.",
                "Deterministic finite cohorts do not justify an IID sigma/sqrt(N) confidence test or tolerance.",
                "Old provider 0.05 eV residual tolerances validate its own controlled extraction, not a replacement IP centroid or full beam.",
                "Small IP slow-axis energy is intentional; its difference from OA Ey is descriptive and is not a mismatch or failure criterion.",
                "Prism voltages and geometry may redistribute y/z momentum and direction, subject to electrostatic energy conservation and physical acceptance; arbitrary independent components are not implied.",
                "Matching mean Ez does not qualify emittance, time focus, prism transport or detector performance.",
                "All transferred ions enter the distributions; upstream non-transfers remain in the full mother census.",
            ],
            "inputs": {**identities, "component_receipt": _identity(component_receipt_path),
                       "component_states": _identity(state_path), "mother_census": _identity(census_path)}}
