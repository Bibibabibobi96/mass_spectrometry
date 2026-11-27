"""Validate recorded joint-flight provenance without opening its original owner."""
from collections.abc import Mapping
import csv
import json
import math
import re
from pathlib import Path
from typing import Any

from msplatform.analysis.particle_census import partition_cohort
from msplatform.contracts.particle_state import load_component_particle_state_csv
from msplatform.io.clock_authority import validate_clock_authority
from msplatform.io.scientific_csv import iter_csv_rows
from msplatform.io.manifest_records import file_record, record_path, verify_record


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def validate_joint_run_identity(manifest: Mapping, config: Mapping, *, run_id: str) -> None:
    """Validate the recorded owner and its unchanged execution status."""
    if (manifest.get('project'), manifest.get('mode')) != ('instrument_assembly', 'prepared_joint'):
        raise ValueError('Analysis source requires instrument_assembly/prepared_joint')
    if manifest.get('status') not in {'success', 'failed'}:
        raise ValueError('Analysis source requires a terminal native flight')
    if (config.get('project'), config.get('mode'), config.get('run_id')) != (
            'instrument_assembly', 'prepared_joint', run_id) or manifest.get('run_id') != run_id:
        raise ValueError('Analysis source run identity differs from its manifest')


def validate_joint_recorded_evidence(manifest: Mapping, config: Mapping, summary: Mapping,
                                     prepared: Mapping, merge: Mapping, *, run_id: str) -> None:
    """Check one historical measured cohort and its complete original-ID merge."""
    validate_joint_run_identity(manifest, config, run_id=run_id)
    if summary.get('status') != manifest['status'] or (
            manifest['status'] == 'failed' and summary.get('failure_stage') != 'automatic_joint_diagnostics'):
        raise ValueError('Analysis source failed before automatic joint diagnostics')
    if prepared.get('role') != 'mrtof_prepared_joint_trial' or prepared.get('source_mode') != 'measured_population':
        raise ValueError('Analysis requires the original measured-population preparation')
    expected = prepared['expected_particle_ids']
    if (merge.get('schema_version') != 1 or merge.get('role') != 'mrtof_measured_batch_log_merge'
            or merge.get('status') != 'success' or merge.get('all_batch_losses_retained') is not True
            or merge.get('id_rebasing_applied') is not False or merge.get('original_particle_ids') != expected
            or merge.get('particle_count') != prepared['launched_particle_count']
            or merge.get('mother_particle_count') != prepared['mother_particle_count']
            or merge.get('solver_epoch_instrument_time_us') != prepared['solver_epoch_instrument_time_us']
            or not merge.get('batches')):
        raise ValueError('Analysis source lacks a complete original-ID native merge')


def read_measured_source(path: Path) -> tuple[dict[str, Any], dict[int, dict[str, Any]], list[dict[str, str]], Path]:
    receipt = _read(path)
    if (receipt.get("schema_version") != 1 or receipt.get("role") != "mrtof_measured_component_source"
            or receipt.get("status") != "prepared_only" or receipt.get("source_materialization_ready") is not True):
        raise ValueError("Unsupported prepared measured-source receipt")
    for name, record in {**receipt["inputs"], **receipt["outputs"]}.items():
        verify_record(name, dict(record, retention_role=record.get('retention_role') or 'required_evidence'), base_dir=path.parent)
    state_path = record_path(receipt["outputs"]["component_particle_state"], base_dir=path.parent)
    census_path = record_path(receipt["outputs"]["source_census"], base_dir=path.parent)
    table = load_component_particle_state_csv(state_path)
    validation = table.report
    clock_path = record_path(receipt["outputs"]["clock_authority"], base_dir=path.parent)
    clock = validate_clock_authority(clock_path, path.parent)
    epoch_path = record_path(receipt["outputs"]["instrument_epoch"], base_dir=path.parent)
    if (validation["frame_ids"] != [receipt["frame_id"]]
            or validation["clock_epoch_ids"] != [receipt["clock_epoch_id"]]
            or clock["clock_epoch_id"] != receipt["clock_epoch_id"]
            or _read(epoch_path)["instrument_time_us"] != receipt["solver_epoch_instrument_time_us"]):
        raise ValueError("Prepared source clock/frame authority differs")
    states = {row["particle_id"]: row for row in table.rows}
    census = _rows(census_path)
    try:
        partition = partition_cohort([int(row["particle_id"]) for row in census],
            [(int(row["particle_id"]), row["transfer_status"]) for row in census],
            categories=("transferred", "not_transferred"), relative_weights=None)
    except ValueError as exc:
        raise ValueError("Prepared source complete mother census does not close") from exc
    transferred = set(partition["particle_ids_by_category"]["transferred"])
    counts = {"source": partition["mother_count"], "transferred": len(states),
              "not_transferred": partition["counts"]["not_transferred"]}
    if transferred != set(states) or counts != receipt["counts"]:
        raise ValueError("Prepared source complete mother census does not close")
    for row in census:
        pid = int(row["particle_id"])
        if row.get("particle_weight"):
            weight = float(row["particle_weight"])
            if not math.isfinite(weight) or weight <= 0:
                raise ValueError("Prepared source census has an invalid weight")
            if pid in states and weight != states[pid]["particle_weight"]:
                raise ValueError("Prepared source census and transferred state weights differ")
    return receipt, states, census, census_path



def iter_trajectory_rows(path: Path):
    """Stream the original recorded trajectory rows without loading the log."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def _bound(record: dict, base: Path) -> Path:
    verify_record("prepared diagnostic input", dict(record, retention_role=record.get("retention_role") or "required_evidence"), base_dir=base)
    return record_path(record, base_dir=base)


def validate_birth_clock_projection(source: dict, states: dict, base: Path) -> dict:
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


def validate_completed_source_batches(prepared: dict, states: dict, base: Path) -> dict:
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




def validate_measured_peak_analysis_contract(contract: dict[str, Any], base: Path) -> float:
    """Verify explicit common-pulse peak settings and frozen timing bytes; return pulse time in us."""
    from msplatform.analysis.peak_metrics import AnalysisSettings
    if (set(contract) != {"method_id", "resolution_definition", "time_basis", "settings", "common_time_reference"}
            or contract["method_id"] != "common_gaussian_kde_time_v2"
            or contract["resolution_definition"] != "mean_tof_us/(2*direct_fwhm_tof_us)"
            or contract["time_basis"] != "instrument_arrival_minus_common_extraction_pulse_us"
            or set(contract["settings"]) != set(AnalysisSettings.__dataclass_fields__)):
        raise ValueError("Unsupported measured detector peak analysis contract")
    reference = contract["common_time_reference"]
    if (set(reference) != {"clock_epoch_id", "timing", "field"}
            or not isinstance(reference["clock_epoch_id"], str) or not reference["clock_epoch_id"]
            or reference["field"] != "pulse_start_us"):
        raise ValueError("Detector peak extraction clock authority differs")
    verify_record("detector peak timing", dict(reference["timing"], retention_role=reference["timing"].get("retention_role") or "required_evidence"), base_dir=base)
    timing_path = record_path(reference["timing"], base_dir=base)
    timing = _read(timing_path)
    pulse = timing[reference["field"]]
    if (timing.get("schema_version") != 1 or timing.get("role") != "native_electrode_timing"
            or isinstance(pulse, bool) or not isinstance(pulse, (int, float)) or not math.isfinite(pulse)):
        raise ValueError("Invalid common extraction pulse time")
    settings = AnalysisSettings(**contract["settings"])
    if (type(settings.grid_points) is not int or type(settings.standardized_grid_points) is not int
            or settings.grid_points < 3 or settings.standardized_grid_points < 3
            or not math.isfinite(settings.bandwidth_multiplier) or settings.bandwidth_multiplier <= 0
            or not 0 < settings.mode_threshold_fraction <= 1
            or not math.isfinite(settings.standardized_grid_min) or not math.isfinite(settings.standardized_grid_max)
            or settings.standardized_grid_min >= settings.standardized_grid_max):
        raise ValueError("Invalid detector peak numerical settings")
    return float(pulse)


def validate_measured_peak_source_reference(contract: dict[str, Any], base: Path, source: dict[str, Any],
                                            states: dict[int, dict[str, Any]]) -> float:
    """Check a common pulse against actual handoff clock/states before flight or analysis."""
    pulse = validate_measured_peak_analysis_contract(contract, base)
    if contract["common_time_reference"]["clock_epoch_id"] != source["clock_epoch_id"]:
        raise ValueError("Detector peak extraction clock authority differs")
    if not states or any(pulse > row["instrument_time_us"] for row in states.values()):
        raise ValueError("Invalid common extraction pulse time after measured handoff")
    return pulse



def project_recorded_events(merged_log: Path, destination: Path) -> None:
    # Full trajectories can be GB-scale; the established event analyzer should
    # receive only its own compact event/completion protocol, not dense states.
    with merged_log.open(encoding="utf-8-sig") as source, destination.open("w", encoding="utf-8", newline="\n") as target:
        for line in source:
            if line.startswith("MRTOF_EVENT ") or line.startswith("status,Fly completed."):
                target.write(line)





def read_prepared_joint_inputs(preparation: Path, *, verify) -> tuple[dict, Path, dict, dict, list[dict], dict]:
    def bound(record):
        verify("prepared diagnostic input", record, base_dir=preparation.parent)
        return record_path(record, base_dir=preparation.parent)

    prepared = _read(preparation)
    if prepared.get("schema_version") != 1 or prepared.get("role") != "mrtof_prepared_joint_trial":
        raise ValueError("Unsupported prepared joint-trial receipt")
    source_path = bound(prepared["source_receipt"])
    source, states, census, _ = read_measured_source(source_path)
    if (set(prepared["expected_particle_ids"]) != set(states)
            or len(prepared["expected_particle_ids"]) != len(states)
            or prepared["mother_particle_count"] != len(census)
            or prepared["solver_epoch_instrument_time_us"] != source["solver_epoch_instrument_time_us"]):
        raise ValueError("Prepared source ID/clock/mother census differs")
    contract_path = bound(prepared["trajectory_contract"])
    bound(prepared["operating_point"])
    contract = _read(contract_path)
    if contract["coordinate_system"]["frame_id"] != source["frame_id"]:
        raise ValueError("Diagnostic geometry and measured source frame differ")
    return prepared, source_path, source, states, census, contract




def write_loss_evidence(merged_log: Path, destination: Path, census: list[dict], source_receipt: dict, *, scientific_event_output=None, verify, record_file) -> dict:
    def bound(record, base):
        verify("prepared diagnostic input", record, base_dir=base)
        return record_path(record, base_dir=base)

    def write(path, value):
        path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")

    destination.mkdir()
    downstream = {int(row["particle_id"]) for row in census if row["downstream_status"] in {"loss", "timeout"}}
    upstream = {int(row["particle_id"]) for row in census if row["downstream_status"] == "not_transferred"}
    counts = {particle: 0 for particle in downstream | upstream}
    handles = {particle: (destination/f"particle_{particle:05d}.jsonl").open("w", encoding="utf-8") for particle in counts}
    sources = []
    try:
        if scientific_event_output is not None:
            for key in ("events_path","trajectory_path"):
                if not scientific_event_output.get(key): continue
                path=Path(scientific_event_output[key])
                for row_number,row in enumerate(iter_csv_rows(path,("ion",)),2):
                    particle=int(float(row["ion"]))
                    if particle in downstream:
                        handles[particle].write(json.dumps(dict(source=str(path),row_number=row_number,fields=row))+"\n")
                        counts[particle]+=1
        else:
            with merged_log.open(encoding="utf-8-sig") as source:
                for line_number, line in enumerate(source, 1):
                    match = re.search(r"\bion=(\d+)\b", line)
                    if match and int(match[1]) in downstream:
                        particle = int(match[1])
                        handles[particle].write(json.dumps(dict(source=str(merged_log), line_number=line_number, raw_line=line))+"\n")
                        counts[particle] += 1
        handoff_path = bound(source_receipt["inputs"]["handoff_receipt"], merged_log.parent)
        handoff = _read(handoff_path)
        component_path = bound(handoff["inputs"]["component_receipt"], handoff_path.parent)
        component = _read(component_path)
        upstream_run = Path(component["source_run"])
        manifest_path = bound(component["inputs"]["run_manifest.json"], component_path.parent)
        manifest = _read(manifest_path)
        records = [*manifest.get("inputs", {}).values(), *manifest.get("outputs", [])]
        for name in ("events.csv", "samples.csv"):
            path = upstream_run / "simion" / name
            matches = [r for r in records if record_path(r, base_dir=upstream_run) == path.resolve()]
            if not matches:
                raise ValueError("Upstream loss evidence is not manifest-bound: "+name)
            for record in matches:
                verify("upstream complete loss evidence", record, base_dir=upstream_run)
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
                  files=[record_file(path) for path in sorted(destination.glob("*.jsonl"))])
    write(destination / "loss_evidence.json", result)
    return result




def read_design_reference(prepared: dict, base: Path, *, verify) -> dict:
    record = prepared.get("reference_materialization")
    if record is None:
        return dict(status="unavailable_no_bound_compatible_Mirror_Stripe_reference")
    verify("prepared diagnostic input", record, base_dir=base)
    value = _read(record_path(record, base_dir=base))
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
