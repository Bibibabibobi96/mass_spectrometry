"""Recorded prepared-joint equivalence and centroid analysis."""
from __future__ import annotations

import json
import re

from pathlib import Path
from itertools import zip_longest
from typing import Any

from msplatform.execution.inputs import freeze_file
from msplatform.contracts.particle_state import load_component_particle_state_csv
from msplatform.io.manifest_records import record_path
from msplatform.execution.retention import verify_record
from msplatform.execution.retention import file_record
from msplatform.backends.comsol.static_field_binding import load_binding, native_response_operator
from msplatform.analysis.native_completion import parse_fly_completed_line
from msplatform.io.scientific_csv import iter_csv_rows
from msplatform.analysis.mr_observations import read_scientific_events


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8", newline="\n")


def freeze_equivalence_reference(reference_run: Path, preparation: dict[str, Any],
                                  inputs: Path) -> dict[str, Any]:
    """Bind a completed batch from a fully verified interrupted flight, without PA reads."""
    from msplatform.backends.simion.native_completion import retention_api
    from msplatform.execution.manifest_verification import verify_run_manifest

    verify_run_manifest(reference_run / "run_manifest.json", require_status="interrupted",
                        retention_api=retention_api)
    manifest = _read(reference_run / "run_manifest.json")
    # Historical MR runs remain read-only comparison evidence. New executions
    # have exactly the assembly owner/mode; no old public execution branch exists.
    if (manifest.get("project"), manifest.get("mode")) not in {
        ("instrument_assembly", "prepared_joint"),
        ("multi_reflection_tof", "two_prism_joint_measured_trial"),
    }:
        raise ValueError("Equivalence reference owner/mode differs from a prepared joint flight")
    outputs = {record_path(record, base_dir=reference_run): record for record in manifest["outputs"]}

    def published_output(relative: str) -> Path:
        path = (reference_run / relative).resolve()
        if path not in outputs:
            raise ValueError("Equivalence manifest does not bind " + relative)
        return path  # The complete public verifier above already verified bytes.

    prior_path = published_output("results/prepared_joint_trial.json")
    prior = _read(prior_path)
    for name in ("expected_particle_ids", "mother_particle_count", "launched_particle_count",
                 "solver_epoch_instrument_time_us", "numerics"):
        if prior[name] != preparation[name]:
            raise ValueError("Equivalence reference differs in "+name)
    for name in ("parent_preparation", "field_binding", "trajectory_contract"):
        if prior[name]["sha256"] != preparation[name]["sha256"]:
            raise ValueError("Equivalence reference differs in frozen "+name)
    for name in ("component_particle_state.csv", "source_census.csv", "source_states.lua",
                 "source_projection.lua", "source.fly2", "clock_authority.json"):
        prior_source = Path(prior["measured_source_directory"]) / name
        published_output(prior_source.relative_to(reference_run).as_posix())
        if file_record(prior_source)["sha256"] != file_record(Path(preparation["measured_source_directory"]) / name)["sha256"]:
            raise ValueError("Equivalence reference differs in measured source "+name)
    log = published_output("logs/joint_flight_batch_001.log")
    completions, terminal_ids, clean_exit = [], [], False
    with log.open(encoding="utf-8-sig") as handle:
        for line in handle:
            completion = parse_fly_completed_line(line)
            if completion:
                completions.append(completion.splats)
            if line.startswith("MRTOF_EVENT terminal "):
                terminal_ids.append(int(re.search(r"\bion=(\d+)", line)[1]))
            if line.startswith("IOB_FLIGHT: PASS "):
                clean_exit = True
            if line.lower().startswith("error,"):
                raise ValueError("Equivalence reference batch reported a solver error")
    reference_science=None
    batch_receipt=(reference_run/"results/batches/batch_001/batch_receipt.json").resolve()
    if batch_receipt in outputs:
        batch=_read(batch_receipt)
        if "scientific_event_output" in batch:
            reference_science=dict(batch["scientific_event_output"])
            for key,record_key in (("events_path","events_record"),("trajectory_path","trajectory_record")):
                if not reference_science.get(key): continue
                path=Path(reference_science[key]).resolve()
                if path not in outputs: raise ValueError("Equivalence scientific output is not manifest-bound")
                reference_science[record_key]=dict(outputs[path],path=str(path))
            actual,_,_=read_scientific_events(log,scientific_event_output=reference_science)
            terminal_ids=[int(row["ion"]) for row in actual if row["kind"]=="terminal"]
    if (len(completions) != 1 or not clean_exit or completions[0] != len(terminal_ids)
            or terminal_ids != preparation["expected_particle_ids"][:completions[0]]):
        raise ValueError("Equivalence reference lacks one naturally completed exact source prefix")
    frozen_log = inputs / "trajectory_equivalence_reference.log"
    frozen_manifest = inputs / "trajectory_equivalence_reference_manifest.json"
    freeze_file(log, frozen_log)
    freeze_file(reference_run / "run_manifest.json", frozen_manifest)
    return dict(reference_log=file_record(frozen_log), reference_manifest=file_record(frozen_manifest),
                source_run=str(reference_run.resolve()),scientific_event_output=reference_science,
                original_particle_ids=terminal_ids, completed_particle_count=len(terminal_ids),
                source_and_field_identity_verified=True, reference_status="interrupted")


def compare_trajectory_representation(preparation_path: Path, log_path: Path,
                                       output_path: Path, *, scientific_event_receipt: Path | None = None) -> dict[str, Any]:
    """Require exact event/sample text for the frozen prefix, retaining the whole new wave."""
    preparation = _read(preparation_path)
    reference = preparation["trajectory_equivalence_reference"]
    if not reference:
        raise ValueError("An explicit trajectory equivalence reference is required")
    verify_record("trajectory equivalence baseline", reference["reference_log"])
    verify_record("trajectory equivalence baseline manifest", reference["reference_manifest"])
    identifiers = set(reference["original_particle_ids"])
    def selected_lines(path: Path):
        with path.open(encoding="utf-8-sig") as handle:
            for line in handle:
                if line.startswith(("MRTOF_EVENT ", "MRTOF_TRAJECTORY ")):
                    match = re.search(r"\bion=(\d+)", line)
                    if match and int(match[1]) in identifiers:
                        yield line.rstrip("\r\n")
    current_science=_read(scientific_event_receipt)["scientific_event_output"] if scientific_event_receipt is not None else None
    reference_science=reference.get("scientific_event_output")
    def selected_records(path,science):
        events,_,_=read_scientific_events(path,scientific_event_output=science)
        for event in events:
            if int(event["ion"]) in identifiers: yield ("event",event)
        if science is not None:
            columns=("ion","phase","t_us","x_mm","y_mm","z_mm","vx_mm_us","vy_mm_us","vz_mm_us")
            if not science.get("trajectory_path"): raise ValueError("equivalence requires explicit complete trajectory output")
            samples=iter_csv_rows(Path(science["trajectory_path"]),columns,exact_header=columns,expected_record=science.get("trajectory_record"))
        else:
            def legacy_samples():
                with path.open(encoding="utf-8-sig") as source:
                    for line in source:
                        if line.startswith("MRTOF_TRAJECTORY "): yield dict(token.split("=",1) for token in line.split()[1:])
            samples=legacy_samples()
        for sample in samples:
            if int(sample["ion"]) in identifiers:
                yield ("trajectory",{key:value if key=="phase" else float(value) for key,value in sample.items()})
    structured = current_science is not None or reference_science is not None
    baseline_rows=selected_records(Path(reference["reference_log"]["path"]),reference_science) if structured else selected_lines(Path(reference["reference_log"]["path"]))
    current_rows=selected_records(log_path,current_science) if structured else selected_lines(log_path)
    mismatches, lines = [], 0
    for index, (baseline, current) in enumerate(zip_longest(baseline_rows,current_rows), 1):
        lines = index
        if baseline != current and len(mismatches) < 10:
            mismatches.append(dict(selected_line=index, reference=baseline, current=current))
    result = dict(schema_version=1, role="mrtof_field_consumer_trajectory_equivalence",
                  status="pass" if not mismatches and lines else "fail", compared_line_count=lines,
                  original_particle_ids=reference["original_particle_ids"],
                  scope="complete_event_and_trajectory_fields_of_manifest_bound_completed_prefix" if structured else "complete_event_and_trajectory_text_of_manifest_bound_completed_prefix",
                  physical_matching_qualified=False, numerical_representation_only=True,
                  reference=reference, new_log=file_record(log_path), first_mismatches=mismatches)
    _write(output_path, result)
    if result["status"] != "pass":
        raise ValueError("Memory consumer trajectory representation differs from its full-field reference")
    return result


def analyze_centroid_probe(preparation_path: Path, log_path: Path, output_directory: Path, *, scientific_event_receipt: Path | None = None) -> dict[str, Any]:
    """Project genuine N1 events for the existing controller's measured-source branch.

    This does not impersonate an OA trial or evaluate any field potential,
    clean-action target, acceptance tolerance or population qualification.
    """
    import csv
    import math
    from msplatform.contracts.particle_physics import kinetic_energy_ev
    from msplatform.analysis.mr_observations import read_scientific_events
    from msplatform.components.multi_reflection_tof.prism_handoff import (
        ProjectPhaseSpaceState, observation_from_simion_events, prism_handoff_residuals,
    )
    from msplatform.workflows.prepared_joint.prism_trial import _prism_handoff_event_prefix, _static_field_receipt
    preparation = _read(preparation_path)
    if preparation.get("source_mode") != "centroid_probe" or preparation["expected_particle_ids"] != [1]:
        raise ValueError("Independent constructed centroid probe required")
    for key in ("source_receipt", "reference_materialization", "field_binding", "trajectory_contract", "operating_point"):
        verify_record(key, preparation[key])
    source_receipt_path = Path(preparation["source_receipt"]["path"])
    source_receipt = _read(source_receipt_path)
    if source_receipt.get("role") != "mrtof_measured_exit_centroid_probe_source":
        raise ValueError("Probe source identity differs")
    source_directory = Path(preparation["measured_source_directory"])
    for record in source_receipt["outputs"].values():
        verify_record("probe source output", record)
    row, = load_component_particle_state_csv(source_directory / "component_particle_state.csv").rows
    source = ProjectPhaseSpaceState(tuple(float(row[f"position_{a}_mm"]) for a in "xyz"),
                                   tuple(float(row[f"velocity_{a}_m_s"])/1000 for a in "xyz"))
    science = _read(scientific_event_receipt)["scientific_event_output"] if scientific_event_receipt is not None else None
    events, finished, _ = read_scientific_events(log_path,scientific_event_output=science)
    terminals = [event for event in events if event["kind"] == "terminal"]
    completions = [completion.splats for completion in finished]
    if len(terminals) != 1 or completions != [1] or any(int(e["ion"]) != 1 for e in events):
        raise ValueError("Probe event population or natural completion does not close")
    reference = _read(Path(preparation["reference_materialization"]["path"]))
    target_keys = ("target_positive_mirror_turn_y_mm", "target_low_field_tangent_ratio_vy_over_vz",
                   "target_nominal_injection_angle_degrees", "p2_low_field_reference_section",
                   "target_drift_period_ratio", "target_slow_turn_y_mm")
    targets = {key: reference[key] for key in target_keys if key in reference}
    stage = dict(status="incomplete", particle_id=1)
    try:
        measured = observation_from_simion_events(_prism_handoff_event_prefix(events), source, ion_number=1)
        residuals = dict(prism_handoff_residuals(measured,
            target_positive_mirror_turn_y_mm=targets["target_positive_mirror_turn_y_mm"],
            target_tangent_ratio_vy_over_vz=targets["target_low_field_tangent_ratio_vy_over_vz"]))
        stage.update(status="observed", residuals=residuals,
            p2_low_field_reference_state=dict(position_mm=measured.p2_shield_low_field_reference.position_mm,
                                            velocity_mm_per_us=measured.p2_shield_low_field_reference.velocity_mm_per_us),
            positive_mirror_turn_state=dict(position_mm=measured.positive_mirror_turn.position_mm,
                                           velocity_mm_per_us=measured.positive_mirror_turn.velocity_mm_per_us))
    except ValueError as error:
        stage["reason"] = str(error)
    binding = load_binding(Path(preparation["field_binding"]["path"]))
    field_receipt=_static_field_receipt(binding,Path(preparation["field_binding"]["path"]))
    values=binding["authority"]["analyzer_electrode_voltages_v"]
    ip_values=sorted([item for item in binding["authority"]["component_voltages_v"]
                      if item["component_namespace"]=="ion_processor"],key=lambda item:item["component_electrode_id"])
    if len(values)!=20 or [item["component_electrode_id"] for item in ip_values] != list(range(1,16)):
        raise ValueError("Live measured field projection requires actual twenty analyzer and fifteen IP voltages")
    field_projection=dict(schema_version=1,role="mrtof_measured_centroid_live_field_projection",
        binding_record=preparation["field_binding"],normalized_binding=binding,
        native_operator=native_response_operator(binding,binding["authority"]),
        analyzer_electrode_voltages_v=values,ion_processor_component_voltages_v15=ip_values,
        scope="manifest_bound_historical_metadata_only__not_authorization_to_Fly_retired_fields")
    materialization = dict(role="mrtof_measured_centroid_probe_materialization", schema_version=1,
        source_projection="measured_exit_centroid", source_cohort=source_receipt["cohort"],
        stripe_biases_v=preparation["stripe_biases_v"], prism_voltages_v=preparation["prism_voltages_v"],
        source_center_state=dict(position_mm=source.position_mm, velocity_mm_per_us=source.velocity_mm_per_us,
                                 instrument_time_us=float(row["instrument_time_us"]),
                                 mass_amu=float(row["mass_amu"]), charge_state=int(row["charge_state"]),
                                 kinetic_energy_eV=float(row["kinetic_energy_eV"])),
        field_binding=field_receipt, source_receipt=preparation["source_receipt"], **targets)
    observation = dict(role="mrtof_measured_centroid_probe_observation", schema_version=1,
        status="probe_observed", prism_voltages_v=preparation["prism_voltages_v"],
        center_particle_prism_handoff_validation=stage, residuals=stage.get("residuals", {}),
        events=events, terminal=terminals[0], physical_potential_evaluated=False,
        full_population_qualified=False)
    output_directory.mkdir(parents=True, exist_ok=False)
    with (output_directory / "probe_event_states.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = ["event", "instrument_time_us", *[f"{a}_mm" for a in "xyz"],
                  *[f"v{a}_mm_us" for a in "xyz"], "Ex_eV", "Ey_eV", "Ez_eV", "K_eV", "signed_angle_yz_degrees"]
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        mass = float(row["mass_amu"])
        for event in events:
            if not all(k in event for k in fields[2:8]):
                continue
            velocity = [float(event[f"v{a}_mm_us"])*1000 for a in "xyz"]
            axes = {f"E{a}_eV": kinetic_energy_ev(mass, *(velocity[i] if i == j else 0 for i in range(3)))
                    for j,a in enumerate("xyz")}
            writer.writerow(dict(event=event["kind"], instrument_time_us=event["t_us"],
                **{key: event[key] for key in fields[2:8]}, **axes, K_eV=kinetic_energy_ev(mass, *velocity),
                signed_angle_yz_degrees=math.degrees(math.atan2(velocity[1],velocity[2]))))
    _write(output_directory / "two_prism_trial_observation.json", observation)
    _write(output_directory / "measured_probe_materialization.json", materialization)
    result = dict(schema_version=1, role="mrtof_measured_exit_centroid_controller_projection",
        observation=observation, materialization=materialization,
        field_authority_projection=field_projection,
        frozen_problem=dict(source_center_projection=dict(role="measured_exit_centroid", cohort=source_receipt["cohort"],
            state=materialization["source_center_state"], mother_source_receipt=source_receipt["inputs"]["mother_source_receipt"]),
            targets=targets, static_field_problem=native_response_operator(binding,binding["authority"])),
        inputs=dict(preparation=file_record(preparation_path), log=file_record(log_path),
                    source_receipt=file_record(source_receipt_path)),
        qualification="constructed_probe_observation_only", physical_potential_evaluated=False,
        outputs={p.stem: file_record(p) for p in sorted(output_directory.iterdir())})
    _write(output_directory / "controller_projection.json", result)
    return result


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    analyze = sub.add_parser("analyze-probe")
    analyze.add_argument("--preparation", type=Path, required=True)
    analyze.add_argument("--log", type=Path, required=True)
    analyze.add_argument("--output", type=Path, required=True)
    analyze.add_argument("--scientific-event-receipt", type=Path)
    args = parser.parse_args()
    if args.command == "analyze-probe":
        analyze_centroid_probe(args.preparation,args.log,args.output,scientific_event_receipt=args.scientific_event_receipt)


if __name__ == "__main__":
    main()
