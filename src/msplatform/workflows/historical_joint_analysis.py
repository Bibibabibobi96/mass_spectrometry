"""Authenticated recorded-flight analysis and Store publication."""
from __future__ import annotations
import csv
import json
from pathlib import Path
import shutil
from typing import Any

from msplatform.analysis.particle_census import partition_cohort, subset_efficiency
from msplatform.analysis.mr_population import close_event_rows, time_statistics, population_rows, prepare_detector_peak
from msplatform.results.historical_joint_source import read_measured_source
from msplatform.results.mr_peak_output import write_detector_peak
from msplatform.io.file_identity import file_sha256
from msplatform.analysis.mr_observations import read_scientific_events


def _identity(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": file_sha256(path)}


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")








def analyze_measured_component(log_path: Path, source_receipt_path: Path, output_directory: Path, *,
                               peak_analysis_contract: dict[str, Any] | None = None,
                               contract_base_directory: Path | None = None,
                               scientific_event_output: dict[str, Any] | None = None) -> dict[str, Any]:
    """Publish complete per-ID census and observed timing from absolute-time logs.

    Source receipt is the authority for original IDs, initial 6D, clock and full
    mother census. Invalid/duplicate/unknown/missing lifecycles fail before any
    output. No solver, GUI, propagation or undeclared peak fitting is performed.
    """
    if output_directory.exists():
        raise FileExistsError(f"Refusing to overwrite measured analysis: {output_directory}")
    receipt, states, census, census_path = read_measured_source(source_receipt_path)
    actual, completions, log_identity = read_scientific_events(log_path, scientific_event_output=scientific_event_output)
    events, terminals, detectors = close_event_rows(actual, completions, states)
    rows = population_rows(census, states, terminals, detectors)
    mother = [int(row["particle_id"]) for row in census]
    partition = partition_cohort(mother, [(row["particle_id"], row["downstream_status"]) for row in rows],
        categories=("not_transferred", "detected", "timeout", "loss", "topology_rejected", "unknown"), relative_weights=None)
    # Missing historical mother weights are unknown, never inferred as unit weights.
    complete_weights = all(row.get("particle_weight") for row in census)
    weights = {int(row["particle_id"]): float(row["particle_weight"]) for row in census} if complete_weights else None
    mother_efficiency = subset_efficiency(mother, detectors, mother, relative_weights=weights) if complete_weights else None
    handoff_weights = {pid: row["particle_weight"] for pid, row in states.items()}
    handoff_efficiency = subset_efficiency(list(states), detectors, list(states), relative_weights=handoff_weights)
    counts = {"mother_source": len(census), "upstream_not_transferred": receipt["counts"]["not_transferred"],
              "downstream_released": len(states), "detected": len(detectors),
              "downstream_timeout": sum(row["downstream_status"] == "timeout" for row in rows),
              "downstream_loss": sum(row["downstream_status"] == "loss" for row in rows),
              "downstream_topology_rejected": sum(row["downstream_status"] == "topology_rejected" for row in rows),
              "downstream_unknown": sum(row["downstream_status"] == "unknown" for row in rows)}
    arrivals = [float(event["t_us"]) for event in detectors.values()]
    elapsed = [float(event["t_us"])-states[particle]["instrument_time_us"] for particle, event in detectors.items()]
    pulse = (validate_measured_peak_source_reference(peak_analysis_contract, contract_base_directory or source_receipt_path.parent, receipt, states)
             if peak_analysis_contract is not None else None)
    peak, spectra = prepare_detector_peak(peak_analysis_contract, pulse, receipt, states, detectors)
    output_directory.mkdir(parents=True)
    shutil.copyfile(census_path, output_directory / "upstream_source_census.csv")
    with (output_directory / "particle_census.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    _write(output_directory / "parsed_events.json", events)
    if peak_analysis_contract is not None:
        write_detector_peak(output_directory, peak, spectra, states, detectors,
                            dict(counts=counts, clock_epoch_id=receipt["clock_epoch_id"],
                                 inputs={"log": dict(path=str(log_path.resolve()), bytes=log_path.stat().st_size, sha256=log_identity.upper()), "source_receipt": _identity(source_receipt_path)},
                                 producer=_identity(Path(__file__))))
    report = {"schema_version": 1, "role": "mrtof_measured_component_analysis", "status": "population_closed",
              "qualification": "recorded_lifecycle_and_timing_only", "physical_performance_pass": None,
              "counts": counts, "clock_epoch_id": receipt["clock_epoch_id"], "frame_id": receipt["frame_id"],
              "detected_fraction_of_mother": len(detectors)/len(census),
              "detected_fraction_of_handoff": len(detectors)/len(states),
              "population_partition_counts": partition["counts"],
              "weighted_efficiency": {"mother": mother_efficiency,
                  "mother_unavailable_reason": None if complete_weights else "incomplete_mother_weights",
                  "handoff": handoff_efficiency},
              "absolute_arrival": time_statistics(arrivals, "canonical_absolute_instrument_time_us"),
              "elapsed_since_handoff": time_statistics(elapsed, "per_particle_elapsed_since_measured_handoff_diagnostic_only"),
              "detector_peak": peak,
              "peak_time_policy": "Use common absolute arrival axis for packet width; never subtract individual handoff times for peak analysis.",
              "plot_consumer": "particle_census.csv and parsed_events.json retain original IDs/absolute times for existing MR diagnostic plotting; no OA ideal-source receipt is fabricated.",
              "inputs": {"log": dict(path=str(log_path.resolve()), bytes=log_path.stat().st_size, sha256=log_identity.upper()), "source_receipt": _identity(source_receipt_path)},
              "outputs": {path.stem: _identity(path) for path in sorted(output_directory.iterdir())}}
    _write(output_directory / "analysis_receipt.json", report)
    return report


import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt

from msplatform.results.mr_joint_output import record_birth_clock_projection, save_figure
from msplatform.analysis import mr_trajectory_diagnostics
from msplatform.analysis.mr_trajectory_diagnostics import (
    COORDINATES, prism_rows, prism_statistics, snapshot_times, trajectory_lifetimes, snapshot_rows, build_prism_figure, build_snapshot_figure, build_loss_figure, summarize_loss_acceptance,
)
from msplatform.io.manifest_records import record_path, verify_record as _verify_record
from functools import partial
from msplatform.execution.retention import classify_file
verify_record = partial(_verify_record, retention_classifier=classify_file)
from msplatform.io.manifest_records import file_record as _file_record
file_record = partial(_file_record, retention_classifier=classify_file)
from msplatform.analysis.mr_trajectory_diagnostics import build_loss_acceptance_figure, prepare_mirror_domain_rows, prepare_loss_rows
from msplatform.results.historical_joint_source import (
    iter_trajectory_rows, project_recorded_events, read_prepared_joint_inputs, write_loss_evidence, read_design_reference, validate_birth_clock_projection, validate_completed_source_batches,
    validate_measured_peak_source_reference,
)
from msplatform.analysis.mr_observations import _prism_phase_space_diagnostic, collision_diagnostics, _collision_geometry_projection
from msplatform.backends.comsol.static_field_binding import load_binding
from msplatform.analysis.mr_observations import extract_trajectory_samples




def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_rows(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _bound(record: dict, base: Path) -> Path:
    verify_record("prepared diagnostic input", record, base_dir=base)
    return record_path(record, base_dir=base)


def analyze_recorded_joint_flight(preparation_receipt: Path, merged_log: Path, output_directory: Path,
                                  *, merge_receipt: Path | None = None,
                                  analysis_contract: Path | None = None) -> dict[str, Any]:
    """Automatically publish full-census Prism, time-cloud and loss diagnostics.

    Inputs must be frozen measured-source trial/clock identities and a complete
    merged original-ID log. No solver, GUI, interpolation outside support,
    particle filtering or whole-beam acceptance/performance gate is performed.
    """
    if output_directory.exists():
        raise FileExistsError(output_directory)
    prepared, source_path, source, states, mother, contract = read_prepared_joint_inputs(preparation_receipt, verify=verify_record)
    contract_base = _bound(prepared["trajectory_contract"], preparation_receipt.parent).parent
    analysis_provenance = None
    if analysis_contract is not None:
        replacement = _read(analysis_contract)
        from msplatform.analysis.joint_analysis_contract import validate_posthoc_analysis_contract
        execution = validate_posthoc_analysis_contract(contract, replacement, contract_base=analysis_contract.parent)
        analysis_provenance = dict(contract=file_record(analysis_contract),
            original_trajectory_contract=prepared["trajectory_contract"],
            change=execution["analysis_change"], qualification="explicit_post_hoc_analysis_only__native_flight_unchanged")
        contract, contract_base = replacement, analysis_contract.parent
    if contract.get("peak_analysis") is not None:
        validate_measured_peak_source_reference(contract["peak_analysis"], contract_base, source, states)
    elif analysis_contract is not None:
        raise ValueError("Post-hoc analysis contract requires an explicit measured peak declaration")
    binding_path = _bound(prepared["field_binding"], preparation_receipt.parent)
    binding = load_binding(binding_path)
    if binding["geometry"]["frame_id"] != source["frame_id"]:
        raise ValueError("Loss diagnostic native geometry and measured source frame differ")
    scientific_event_output = None
    if merge_receipt is not None:
        merged = _read(merge_receipt)
        if (merged.get("schema_version") != 1 or merged.get("role") != "mrtof_measured_batch_log_merge"
                or merged.get("status") != "success" or merged.get("id_rebasing_applied") is not False
                or merged.get("all_batch_losses_retained") is not True
                or merged.get("particle_count") != len(states)
                or merged.get("original_particle_ids") != prepared["expected_particle_ids"]
                or merged.get("mother_particle_count") != prepared["mother_particle_count"]
                or merged.get("solver_epoch_instrument_time_us") != prepared["solver_epoch_instrument_time_us"]):
            raise ValueError("Measured merge receipt differs from prepared population/clock")
        if (_bound(merged["preparation"], merge_receipt.parent).resolve() != preparation_receipt.resolve()
                or _bound(merged["merged_log"], merge_receipt.parent).resolve() != merged_log.resolve()):
            raise ValueError("Measured merge receipt differs from preparation/log identity")
        scientific_event_output = merged.get("scientific_event_output")
        batches = merged["batches"]
        if not batches:
            raise ValueError("Measured merge receipt lacks completed source batches")
        # Normalize only file records in memory. Recovery adds provenance fields
        # to its copied records; those do not change the actual file identities.
        existing = prepared.get("completed_source_batches")
        if existing is not None:
            def identities(rows: list[dict], base: Path) -> list[dict]:
                return [{key: file_record(_bound(row[key], base)) for key in ("log", "batch_receipt", "fly2")}
                        for row in rows]
            if identities(existing, preparation_receipt.parent) != identities(batches, merge_receipt.parent):
                raise ValueError("Embedded and merged completed source batches conflict")
        prepared = dict(prepared, completed_source_batches=batches)
        # Resolve records relative to their receipt before the existing source
        # TOB validator consumes them relative to the preparation directory.
        prepared["completed_source_batches"] = [
            {key: file_record(_bound(row[key], merge_receipt.parent)) for key in ("log", "batch_receipt", "fly2")}
            for row in batches]
    output_directory.mkdir(parents=True)
    event_log = merged_log
    if scientific_event_output is None:
        event_log = output_directory / "events.log"
        project_recorded_events(merged_log, event_log)
    population = analyze_measured_component(event_log, source_path, output_directory / "population",
        peak_analysis_contract=contract.get("peak_analysis"),
        contract_base_directory=contract_base, scientific_event_output=scientific_event_output)
    events = _read(output_directory / "population/parsed_events.json")
    census = _rows(output_directory / "population/particle_census.csv")
    trajectory = extract_trajectory_samples(log_path=merged_log, output_path=output_directory / "trajectory_samples.csv",
                                           receipt_path=output_directory / "trajectory_receipt.json", recording_config=prepared["trajectory_recording"], scientific_event_output=scientific_event_output)
    actual_trajectory = Path(trajectory["trajectory_csv"])
    birth_authority = validate_birth_clock_projection(source, states, source_path.parent)
    birth_authority["actual_launch_evidence"] = validate_completed_source_batches(prepared, states, preparation_receipt.parent)
    lifetimes = trajectory_lifetimes(iter_trajectory_rows(actual_trajectory), states,
                                     {int(event["ion"]): event for event in events if event["kind"] == "terminal"},
                                     initialization_epoch_us=birth_authority["epoch_us"])
    if any(value["birth_clock_projected"] for value in lifetimes.values()) and birth_authority["actual_launch_evidence"]["status"] != "verified_actual_launched_sources":
        raise ValueError("Initialize birth-clock projection requires verified actual launched batch FLY2 evidence")
    birth_projection = record_birth_clock_projection(output_directory, lifetimes, birth_authority, record_file=file_record)
    times = snapshot_times(lifetimes, events)
    snapshots, gap = snapshot_rows(iter_trajectory_rows(actual_trajectory), lifetimes, mother,
                                  {int(r["particle_id"]): r["downstream_status"] for r in census}, times)
    _write_rows(output_directory / "timed_spatial_clouds.csv", snapshots, list(snapshots[0]))
    prism = prism_rows(events, states)
    design = read_design_reference(prepared, preparation_receipt.parent, verify=verify_record)
    for row in prism:
        row["raw_signed_angle_difference_to_reference_deg"] = (
            row["signed_yz_angle_deg"]-design["p2_target_signed_angle_deg"]
            if row["stage"] == "p2_fixed_plane" and row["signed_yz_angle_deg"] != "" and "p2_target_signed_angle_deg" in design else "")
        row["positive_turn_y_difference_to_reference_mm"] = (
            row["y_mm"]-design["positive_turn_target_y_mm"]
            if row["stage"] == "first_positive_turn" and "positive_turn_target_y_mm" in design else "")
    prism_columns = ["stage", "particle_id", "event_index", "first_recorded_crossing", "instrument_time_us", *COORDINATES,
                     "signed_yz_angle_deg", "transverse_tilt_deg", "inside_aperture", "direction_ok", "Ex_per_charge_eV", "Ey_per_charge_eV", "Ez_per_charge_eV", "K_per_charge_eV", "raw_signed_angle_difference_to_reference_deg", "positive_turn_y_difference_to_reference_mm"]
    _write_rows(output_directory / "prism_phase_space.csv", prism, prism_columns)
    species = {(float(r["mass_amu"]), int(r["charge_state"])) for r in states.values()}
    standard = _prism_phase_space_diagnostic(events, tuple(sorted(states)), *next(iter(species))) if len(species) == 1 else None
    loss = write_loss_evidence(merged_log, output_directory / "loss_evidence", census, source, scientific_event_output=scientific_event_output, verify=verify_record, record_file=file_record)
    acceptance_rows, collisions = prepare_loss_rows(events, states, census, collision_diagnostics(
        events, _collision_geometry_projection(binding["geometry"])))
    _write_rows(output_directory / "loss_acceptance.csv", acceptance_rows, list(acceptance_rows[0]))
    domain_rows, crossing_rows, domain = prepare_mirror_domain_rows(
        iter_trajectory_rows(actual_trajectory), binding, set(states),
        {int(e["ion"]): e for e in events if e["kind"] == "terminal"})
    domain_columns = ["particle_id", "window", "scope", "sample_count", "inside_x_sample_count", "outside_x_sample_count",
                      "inside_active_box_sample_count", "maximum_abs_x_mm", "x_min_mm", "x_max_mm", "z_min_mm", "z_max_mm"]
    _write_rows(output_directory / "mirror_domain_samples.csv", domain_rows, domain_columns)
    crossing_columns = ["particle_id", "window", "boundary_x_mm", "first_negative_mirror_pass",
                        *[prefix+key for prefix in ("before_", "after_") for key in ("t_us", *COORDINATES)]]
    _write_rows(output_directory / "mirror_x_boundary_crossings.csv", crossing_rows, crossing_columns)
    acceptance = summarize_loss_acceptance(acceptance_rows, collisions, domain)
    acceptance["inputs"] = dict(field_binding=file_record(binding_path))
    acceptance["producer"] = file_record(Path(mr_trajectory_diagnostics.__file__))
    acceptance["outputs"] = [file_record(output_directory / name) for name in (
        "loss_acceptance.csv", "mirror_domain_samples.csv", "mirror_x_boundary_crossings.csv")]
    _write(output_directory / "loss_acceptance_receipt.json", acceptance)
    metadata = dict(schema_version=1, role="mrtof_prepared_joint_diagnostic_figure", counts=population["counts"],
                    frame_id=source["frame_id"], clock_epoch_id=source["clock_epoch_id"],
                    units=dict(position="mm", velocity="mm/us", time="absolute instrument us", energy="eV/abs(q)", angle="deg"),
                    inputs=dict(preparation=file_record(preparation_receipt), merged_log=file_record(merged_log),
                                source_receipt=file_record(source_path), field_binding=file_record(binding_path)),
                    producer=file_record(Path(__file__)), style="English, color plus marker/line, 180 DPI PNG and vector SVG", design_reference=design,
                    filtering="no mother exclusion; first crossing plots preserve every raw branch in CSV; no detector-conditioned selection",
                    interpolation="linear only between adjacent recorded states; no extrapolation; terminal points separately marked",
                    maximum_interpolation_gap_us=gap, automatic_snapshot_selection=times,
                    recording_policy=prepared["trajectory_recording"], uncertainty="descriptive finite cohort; no inferred acceptance or confidence interval",
                    birth_clock_projection=birth_projection,
                    loss_acceptance=acceptance,
                    potential_correction="not evaluated; terminal ion_volts is not used as scalar-field potential; raw K differences are not conservation residuals",
                    qualification="diagnostic_only_no_physics_GUI_or_Formal_pass")
    if analysis_provenance is not None:
        metadata["inputs"]["analysis_contract"] = analysis_provenance["contract"]
        metadata["analysis_contract_provenance"] = analysis_provenance
    if merge_receipt is not None:
        metadata["inputs"]["batch_log_merge_receipt"] = file_record(merge_receipt)
    with plt.rc_context({"font.size": 9, "axes.titlesize": 9}):
        for role, builder, args in (("prism_phase_space", build_prism_figure, (prism, len(mother), design)),
                                    ("timed_spatial_clouds", build_snapshot_figure, (snapshots, times, len(mother), source["solver_epoch_instrument_time_us"])),
                                    ("population_and_losses", build_loss_figure, (census,)),
                                    ("loss_acceptance", build_loss_acceptance_figure, (acceptance_rows, binding["geometry"]))):
            figure, _ = builder(*args)
            save_figure(figure, output_directory / role, metadata, record_file=file_record)
    result = dict(schema_version=1, role="mrtof_prepared_joint_diagnostics", status="complete_recorded_diagnostics",
                  inputs=metadata["inputs"], analysis_contract_provenance=analysis_provenance,
                  counts=population["counts"], figure_roles=["prism_phase_space", "timed_spatial_clouds", "population_and_losses", "loss_acceptance"],
                  detector_peak=population["detector_peak"],
                  snapshot_count=len(times), maximum_interpolation_gap_us=gap, trajectory=trajectory,
                  birth_clock_projection=birth_projection,
                  prism_phase_space_reference=standard, signed_angle_definition="atan2(vy,vz), full quadrant; zero yz speed undefined",
                  prism_statistics=prism_statistics(prism, {int(row["particle_id"]) for row in mother}),
                  frozen_design_reference=design,
                  legacy_reference_angle_definition="existing reference diagnostic uses atan2(vy,abs(vz)); use explicit CSV signed_yz_angle_deg for full quadrant",
                  loss_evidence=loss, loss_acceptance=acceptance,
                  qualification="descriptive_diagnostics_only_no_whole_beam_acceptance_or_performance_pass",
                  outputs=[file_record(path) for path in sorted(output_directory.rglob("*")) if path.is_file()])
    _write(output_directory / "diagnostics_receipt.json", result)
    return result




from contextlib import ExitStack, contextmanager
from msplatform.execution.native_source_guard import guard_historical_measured_flight, guard_historical_joint_component
from msplatform.io.manifest_records import validate_file_record


@contextmanager
def _guard_joint_sources(source_manifest: Path, ancestor_manifests: tuple[Path, ...], analysis_contract: Path | None):
    """Hold an explicitly declared, complete historical file graph before analysis.

    The supported graph contains only individually stopped joint and IP native
    component owners. Unknown owner versions and unresolved references fail closed.
    """
    paths = [Path(source_manifest).resolve(strict=True), *(Path(p).resolve(strict=True) for p in ancestor_manifests)]
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate historical owner manifest")
    with ExitStack() as stack:
        sources = []
        manifest_records = []
        for index, path in enumerate(paths):
            manifest = _read(path)
            identity = (manifest.get("project"), manifest.get("mode"))
            if index == 0 and identity != ("instrument_assembly", "prepared_joint"):
                raise ValueError("source must be a historical joint flight")
            if identity == ("instrument_assembly", "prepared_joint"):
                guard = guard_historical_measured_flight
            elif identity == ("dual_pressure_rectilinear_ion_processor", "native_electrode_functional"):
                guard = guard_historical_joint_component
            else:
                raise ValueError("unsupported historical ancestor identity")
            manifest_record = file_record(path, "required_evidence")
            sources.append(stack.enter_context(guard(manifest_record)))
            manifest_records.append(manifest_record)
        root = sources[0]
        index_by_path = {}
        for source, manifest_record in zip(sources, manifest_records, strict=True):
            for name, record in source.manifest.get("inputs", {}).items():
                if isinstance(record, dict) and record.get("exists") is True:
                    index_by_path.setdefault(record_path(record, base_dir=source.root), []).append((source, "input", name, record))
            for record in source.manifest.get("outputs", []):
                if isinstance(record, dict) and record.get("exists") is True:
                    path = record_path(record, base_dir=source.root)
                    index_by_path.setdefault(path, []).append((source, "output", str(path.relative_to(source.root)), record))
            index_by_path.setdefault(source.root / "run_manifest.json", []).append((source, "manifest", None, manifest_record))
        held, visiting = set(), set()
        def hold(path, expected=None):
            path = Path(path).resolve(strict=True)
            choices = index_by_path.get(path, [])
            if not choices:
                raise ValueError("historical source file is not bound by an explicitly guarded manifest")
            identities = {(row[3]["bytes"], str(row[3]["sha256"]).upper()) for row in choices if row[3] is not None}
            if len(identities) > 1:
                raise ValueError("conflicting historical source file identities")
            if expected is not None:
                validate_file_record(expected, "historical analysis dependency")
                if not identities or (expected["bytes"], str(expected["sha256"]).upper()) not in identities:
                    raise ValueError("historical dependency differs from its owner manifest")
            if path in visiting:
                raise ValueError("historical dependency cycle")
            if path in held:
                return path
            row = choices[0]
            if row[1] == "input": row[0].input(row[2])
            elif row[1] == "output": row[0].output(row[2])
            held.add(path)
            if path.suffix.lower() == ".json" and row[1] != "manifest":
                if path.stat().st_size > 4 * 1024 * 1024:
                    raise ValueError("unsupported large historical JSON dependency")
                visiting.add(path)
                document = _read(path)
                def visit(value):
                    if isinstance(value, dict):
                        if all(key in value for key in ("path", "exists", "bytes", "sha256")) and value.get("exists") is True:
                            child = record_path(value, base_dir=path.parent)
                            if child.suffix.lower() in {".pa", ".pa0", ".mph"}:
                                raise ValueError("unsupported native payload in analysis dependency graph")
                            hold(child, value)
                            return
                        for key, item in value.items():
                            if key in {"events_path", "trajectory_path"} and item:
                                candidate = Path(item)
                                hold(candidate if candidate.is_absolute() else path.parent / candidate)
                            elif key == "source_run" and item:
                                component = Path(item).resolve(strict=True)
                                matches = [owner for owner in sources if owner.root == component and
                                    owner.manifest.get("project") == "dual_pressure_rectilinear_ion_processor" and
                                    owner.manifest.get("mode") == "native_electrode_functional"]
                                if len(matches) != 1:
                                    raise ValueError("historical component owner was not explicitly guarded")
                                hold(component / "run_manifest.json")
                                hold(component / "simion/events.csv")
                                hold(component / "simion/samples.csv")
                            elif key == "authority" and isinstance(item, dict) and {"path", "field", "sha256"} <= item.keys():
                                authority = hold(path.parent / item["path"])
                                choices = index_by_path[authority]
                                if not any(row[3] is not None and str(row[3]["sha256"]).upper() == str(item["sha256"]).upper() for row in choices):
                                    raise ValueError("clock authority identity differs from its guarded manifest")
                            elif isinstance(item, str) and (Path(item).is_absolute() or key in {
                                    "export_manifest", "baseline_binding", "manifest", "pa_path",
                                    "scalar_pa", "surface", "source_descriptor_path"}):
                                candidate = Path(item)
                                candidate = candidate if candidate.is_absolute() else path.parent / candidate
                                if candidate.suffix.lower() in {".pa", ".pa0", ".mph"}:
                                    raise ValueError("unsupported native payload in analysis dependency graph")
                                if candidate.is_dir():
                                    if not any(candidate.resolve().is_relative_to(owner.root) for owner in sources):
                                        raise ValueError("unbound historical directory reference")
                                else:
                                    hold(candidate)
                            else:
                                visit(item)
                    elif isinstance(value, list):
                        for item in value: visit(item)
                visit(document)
                visiting.remove(path)
            return path
        preparation = hold(root.root / "results/prepared_joint_trial.json")
        merge_path = hold(root.root / "results/batch_log_merge_receipt.json")
        summary_path = hold(root.root / "summary.json")
        merged = _read(merge_path)
        merged_log = hold(record_path(merged["merged_log"], base_dir=merge_path.parent), merged["merged_log"])
        contract = hold(analysis_contract) if analysis_contract is not None else None
        from msplatform.results.historical_joint_source import validate_joint_recorded_evidence
        validate_joint_recorded_evidence(root.manifest, root.config, _read(summary_path), _read(preparation), merged, run_id=root.root.name)
        yield dict(preparation=preparation, merged_log=merged_log, merge=merge_path, contract=contract,
                   source_status=root.manifest["status"], manifests=paths, held=held)


def _joint_analysis_action(session, *, inputs):
    output = session.result_dir / "recorded_diagnostics"
    try:
        report = analyze_recorded_joint_flight(inputs["preparation"], inputs["merged_log"], output,
            merge_receipt=inputs["merge"], analysis_contract=inputs["contract"])
        provenance = session.declare_file(session.result_dir / "historical_source.json", "required_evidence")
        _write(provenance, dict(schema_version=1, role="historical_joint_analysis_source",
            source_execution_status=inputs["source_status"], source_manifests=[str(path) for path in inputs["manifests"]],
            source_qualification="recorded_analysis_only"))
        paths = [path for path in output.rglob("*") if path.is_file()] + [provenance]
        for path in paths: session.declare_file(path, "required_evidence")
        return dict(status="success", summary=dict(source_execution_status=inputs["source_status"],
                    scientific_status=report["status"], qualification="recorded_analysis_only"),
                    output_paths=list(map(str, paths)), required_output_paths=list(map(str, paths)),
                    retention_preserve_paths=[], manifest_extra_fields={})
    except BaseException as error:
        paths = [path for path in output.rglob("*") if path.is_file()] if output.exists() else []
        for path in paths: session.declare_file(path, "required_evidence")
        error.failure_output_paths = paths
        raise


def publish_joint_analysis(context, *, source_manifest: Path, ancestor_manifests: tuple[Path, ...],
                           analysis_contract: Path | None, artifact_store, committed_new_bytes: int,
                           run_id: str, retention: dict) -> dict[str, Any]:
    """Publish a stopped historical measured-flight analysis under one Store owner.

    All explicitly named source owners and their dependency records remain held
    until publication completes. Unsupported or incomplete source evidence fails
    before an analysis run begins; no original scientific status is changed.
    """
    from msplatform.execution.completion import no_particle_batch_completion_api
    from msplatform.execution.owner import run_managed_stage, standalone_native_store
    if type(committed_new_bytes) is not int or committed_new_bytes <= 0:
        raise ValueError("committed_new_bytes must be a positive integer")
    with _guard_joint_sources(source_manifest, ancestor_manifests, analysis_contract) as inputs:
        with standalone_native_store(artifact_store, task_key="historical-joint:" + run_id,
                                     budget=committed_new_bytes) as scope:
            result = run_managed_stage(context, artifact_store=artifact_store,
                descriptor=dict(project="instrument_assembly", mode="historical_joint_analysis", software=["Python"]),
                run_id=run_id, payload=dict(analysis_only=True, source_execution_status=inputs["source_status"]),
                committed_new_bytes=committed_new_bytes,
                commitment_inputs=[file_record(path, "required_evidence") for path in inputs["manifests"]],
                retention=retention, expected_operation_ids=[], operation_dependencies={},
                action=partial(_joint_analysis_action, inputs=inputs),
                action_record=file_record(Path(__file__), "required_evidence"),
                completion_api=no_particle_batch_completion_api)
            if result.get("status") != "success":
                raise RuntimeError("historical joint analysis failed: " + str(result.get("status")))
        artifact_store.inspect_run(scope["parent_run_id"])
        from msplatform.execution.native_source_guard import guard_historical_run
        with guard_historical_run(result["manifest"], expected_project="instrument_assembly",
                                  expected_mode="historical_joint_analysis") as published:
            receipt_path = Path(published.output("results/recorded_diagnostics/diagnostics_receipt.json")["path"])
            receipt = _read(receipt_path)
            for item in receipt["outputs"]:
                path = record_path(item)
                relative = str(path.relative_to(published.root))
                record = published.output(relative)
                if (record["bytes"], record["sha256"].upper()) != (item["bytes"], item["sha256"].upper()):
                    raise ValueError("published diagnostic record differs from its manifest")
            source_provenance = _read(Path(published.output("results/historical_source.json")["path"]))
            if source_provenance["source_execution_status"] != inputs["source_status"]:
                raise ValueError("published historical source status differs")
        return dict(result, store_run_id=scope["parent_run_id"], store_run_path=str(scope["published_path"]),
                    diagnostics=receipt)


def main() -> int:
    """Run recorded-joint diagnostics without starting a solver or new flight."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze-joint")
    analyze.add_argument("--preparation", required=True, type=Path)
    analyze.add_argument("--log", required=True, type=Path)
    analyze.add_argument("--output", required=True, type=Path)
    analyze.add_argument("--analysis-contract", type=Path)
    args = parser.parse_args()
    analyze_recorded_joint_flight(args.preparation, args.log, args.output,
        merge_receipt=args.preparation.parent / "batch_log_merge_receipt.json", analysis_contract=args.analysis_contract)
    print("RECORDED_JOINT_ANALYSIS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
