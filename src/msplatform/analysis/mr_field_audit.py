"""Reduce recorded MR interface and event field samples without solver calls."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from msplatform.contracts.rigid_transform import FramedVector, RigidTransform
from msplatform.execution.retention import file_record, verify_record


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def summarize_interface_field_audit(directory: Path) -> dict:
    """Report gauge-separated potential/field residuals and centroid energy bookkeeping."""
    request = _read(directory / "request.json")
    transform = RigidTransform.from_contract(request["local_to_mr"])
    with (directory / "raw_field_samples.csv").open(encoding="utf-8-sig", newline="") as handle:
        raw = list(csv.DictReader(handle))
    if [row["sample_id"] for row in raw] != [p["sample_id"] for p in request["points"]]:
        raise ValueError("interface field sample IDs/order do not close")
    rows = []
    for point, sample in zip(request["points"], raw):
        values = {key: float(value) for key, value in sample.items() if key != "sample_id"}
        if not all(math.isfinite(value) for value in values.values()):
            raise ValueError("nonfinite interface audit values")
        source_field = transform.transform_vector(FramedVector(transform.from_frame_id,
            [values[f"source_e{axis}_local_v_mm"] for axis in "xyz"])).components
        delta = [values[f"joint_e{axis}_v_mm"]-source_field[a] for a, axis in enumerate("xyz")]
        phi, joint_phi = values["source_phi_v"], values["joint_phi_v"]
        k = point["kinetic_energy_per_charge_ev"]
        rows.append(dict(point, source_phi_v=phi, joint_phi_v=joint_phi, delta_phi_v=joint_phi-phi,
                         source_field_mr_v_mm=list(source_field), delta_field_v_mm=delta,
                         source_elapsed_us=values["source_elapsed_us"], source_rf_differential_v=values["source_rf_differential_v"],
                         source_electrode_voltages_v15=[values[f"source_electrode_{index}_v"] for index in range(1,16)],
                         source_k_over_q_plus_phi_v=k+phi, joint_k_over_q_plus_phi_v=k+joint_phi))
    particles, centroid = rows[:-1], rows[-1]
    offset = sum(row["delta_phi_v"] for row in particles)/len(particles)
    for row in rows:
        row["delta_phi_without_constant_v"] = row["delta_phi_v"]-offset
    result = dict(schema_version=1, role="mrtof_interface_energy_field_audit", status="reported",
                  energy_acceptance="not_declared", tolerance=None, physical_matching_qualified=False,
                  scope="same_registered_points_and_absolute_times__not_energy_conservation_or_joint_flight_qualification",
                  units=dict(position="mm",time="absolute_instrument_us",potential="V",field="V/mm",energy_per_charge="eV/q"),
                  particle_count=len(particles), inputs=dict(request=file_record(directory / "request.json"),
                    raw_samples=file_record(directory / "raw_field_samples.csv")), coverage=request["coverage"],
                  mean_delta_phi_constant_v=offset,
                  max_abs_delta_phi_without_constant_v=max(abs(row["delta_phi_without_constant_v"]) for row in particles),
                  max_delta_field_norm_v_mm=max(math.sqrt(sum(v*v for v in row["delta_field_v_mm"])) for row in particles),
                  centroid=dict(definition=request["centroid_definition"],
                    kinetic_energy_of_mean_velocity_ev_per_q=centroid["kinetic_energy_per_charge_ev"],
                    mean_particle_kinetic_energy_ev_per_q=sum(row["kinetic_energy_per_charge_ev"] for row in particles)/len(particles),
                    velocity_spread_energy_ev_per_q=sum(row["kinetic_energy_per_charge_ev"] for row in particles)/len(particles)-centroid["kinetic_energy_per_charge_ev"],
                    mean_source_k_over_q_plus_phi_v=sum(row["source_k_over_q_plus_phi_v"] for row in particles)/len(particles),
                    mean_joint_k_over_q_plus_phi_v=sum(row["joint_k_over_q_plus_phi_v"] for row in particles)/len(particles),
                    field_sample=centroid), samples=particles)
    _write(directory / "interface_energy_field_audit.json", result)
    return result


def summarize_event_field_audit(directory: Path) -> dict:
    """Join actual native V/E queries to original 6D states; never assume phi=0."""
    request = _read(directory / "event_audit_request.json")
    for key, record in request["inputs"].items():
        verify_record("event audit frozen " + key,record)
    samples = {}
    raw_records = []
    for job in request["jobs"]:
        verify_record("event audit query",job["request"])
        path = Path(job["raw_output"])
        with path.open(encoding="utf-8-sig",newline="") as handle:
            rows = list(csv.DictReader(handle))
        if [row["sample_id"] for row in rows] != job["point_ids"]:
            raise ValueError("actual field query IDs or routes do not close")
        for row in rows:
            if row["sample_id"] in samples:
                raise ValueError("duplicate actual field sample")
            values = {key:float(value) for key,value in row.items() if key != "sample_id"}
            if not all(math.isfinite(v) for v in values.values()):
                raise ValueError("nonfinite actual event phi/E")
            samples[row["sample_id"]] = values
        raw_records.append(file_record(path))
    from msplatform.analysis.event_energy import sampled_event_energy
    ledger, baseline = sampled_event_energy(request['points'], samples)
    result = dict(schema_version=1,role="mrtof_actual_probe_event_energy_field_audit",status="reported",
        energy_acceptance="not_declared",tolerance=None,physical_matching_qualified=False,
        potential_authority="actual_materialized_scalar_native_PA__scalar_adapter_raw_sample",
        energy_definition="H_over_q=K_over_q+actual_electrostatic_phi__not_effective_Psi",
        inputs=dict(request=file_record(directory / "event_audit_request.json"),raw_samples=raw_records),
        samples=ledger,source_centroid_h_over_q_v=baseline)
    _write(directory / "event_energy_field_audit.json",result)
    return result
