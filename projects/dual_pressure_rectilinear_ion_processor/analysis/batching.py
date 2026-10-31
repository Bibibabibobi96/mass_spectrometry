"""Project projections around repository SIMION dispatch and ID rebasing.

No resource decision is made here. Canonical particles are sliced unchanged;
the common scheduler owns intervals, and the common CSV merger owns ID offsets.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

from common.contracts.file_identity import file_sha256
from common.contracts.recorded_file_removal import remove_recorded_files
from common.contracts.write_run_manifest import publish_run_manifest, resolve_path, write_json_atomic
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.particle_physics import kinetic_energy_ev
from common.simion.native_completion import require_one_fly_completion
from common.simion.particle_batching import merge_rebased_particle_csvs
# Import public dependencies before prepare freezes the loaded source closure.
from common.simion import batch_continuation as batch_continuation
from common.simion import resource_profile as resource_profile
from common.simion import resource_scheduler
from common.simion.particle_source import project_direct_velocity, render_standard_beams, render_source_states
from projects.dual_pressure_rectilinear_ion_processor.analysis.coordinates import to_project_position, to_project_vector
from projects.dual_pressure_rectilinear_ion_processor.analysis.upstream_admission import frozen_release_states


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def frozen_runtime_profile(run: Path, *, allow_legacy: bool = False) -> dict:
    """Select one private budget; legacy names are read only for historical replay."""
    path = run / "inputs/runtime_profiles.json"
    legacy = run / "inputs/execution_profiles.json"
    if path.is_file() and legacy.is_file():
        raise ValueError("ambiguous frozen runtime profile contracts")
    role = "ion_processor_runtime_profiles"
    if not path.is_file() and allow_legacy:
        path, role = legacy, "ion_processor_execution_profiles"
    registry = _read(path)
    if (registry.get("schema_version") != 1 or registry.get("role") != role
            or registry.get("project_id") != "dual_pressure_rectilinear_ion_processor"):
        raise ValueError("frozen runtime profile identity differs")
    matches = [item for item in registry["profiles"] if item["profile_id"] == "native_functional"]
    if len(matches) != 1:
        raise ValueError("exactly one frozen native_functional runtime profile is required")
    return matches[0]


def publish_manifest(run: Path, status: str) -> dict:
    """Pass arbitrarily many worker outputs directly to the public Python API.

    Repeated absolute --output arguments can exceed Windows' command-line limit.
    Frozen inputs retain their input identity; only generated files are outputs.
    """
    if status not in {"success", "failed"}:
        raise ValueError("native run requires a terminal status")
    config = _read(run/"run_config.json")
    project_root = Path(config["project_root"]).resolve() if config.get("project_root") else None
    input_paths = {resolve_path(value, run.resolve(), project_root)
                   for value in config.get("inputs", {}).values() if isinstance(value, str)}
    outputs = sorted(path for path in run.rglob("*") if path.is_file()
                     and path.resolve() not in input_paths
                     and path.name not in {"run_manifest.json", "run_config.json"}
                     and not path.name.startswith("."))
    return publish_run_manifest(run/"run_config.json", status,
                                software=["SIMION 2020", "Python 3.11"], output_paths=outputs)


def dispatch_request_for_field(run: Path, c: dict, pa_sha: str, retain: bool, *, processor_program: Path) -> dict:
    """Project frozen science and native field identity without creating assets."""
    identity = {key:c[key] for key in ("baseline", "numerics", "source", "native_operating_point", "native_projection")}
    if "coordinate_transform" in c:
        identity["coordinate_transform"] = c["coordinate_transform"]
    identity["native_timing"] = c["native_timing"]
    if "injected_source" in c:
        identity["injected_source"] = _read(run/"inputs/injected_source.json")["source_states"]
    identity["programs"] = {name:file_sha256(processor_program if name == "processor.lua" else run/"simion"/name) for name in ("processor.lua", "collision_hs1.lua", "native_drive.lua", "simion_rf_drive.lua", "voltage_waveforms.lua", "extraction_force_audit.lua")}
    identity["retain_batch_trajectories"] = retain
    request = dict(solver="SIMION", field_kind="rf", particle_count=c["source"]["particle_count"], independent_particles=True,
                   rf_steps_per_period=c["numerics"]["rf_steps_per_period"], trajectory_quality=c["numerics"]["trajectory_quality"],
                   frontend_grid_profile_id="ion_processor_native_uniform_grid", frontend_cell_mm_xyz=[c["numerics"]["native_grid_mm"]]*3,
                   trajectory_quality_profile_id=("ion_processor_retained_native_trajectories" if retain else "ion_processor_csv_native_trajectories"), time_integration_profile_id="ion_processor_rf_hs1_stage_boundaries",
                   frontend_pa0_sha256=pa_sha, case_input_sha256=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest().upper(),
                   workload_topology_id="ion_processor_one_native_instance_15_adjustable_electrodes",
                   field_loading_policy_id=("native_all_15_basis_force_audit_retained_trajectories" if retain else "native_all_15_basis_force_audit_csv_diagnostics"))
    return request


def continuation_ancestry(predecessor: Path) -> list[Path]:
    """Validate and return the explicit predecessor and its bound data ancestors."""
    from common.contracts.write_run_manifest import require_completed_terminal_publication

    chain = []
    origins = []
    current = predecessor.resolve(strict=True)
    while True:
        if current in chain:
            raise ValueError("continuation ancestry contains a cycle")
        chain.append(current)
        manifest_path = current / "run_manifest.json"
        require_completed_terminal_publication(manifest_path)
        manifest = _read(manifest_path)
        if (manifest.get("project") != "dual_pressure_rectilinear_ion_processor"
                or manifest.get("mode") != "native_electrode_functional"
                or manifest.get("run_id") != current.name
                or manifest.get("status") not in {"success", "failed"}):
            raise ValueError("continuation ancestry identity differs")
        plan_record = manifest.get("inputs", {}).get("continuation_plan")
        if not plan_record:
            if any(origin != current for origin in origins):
                raise ValueError("continuation ancestry has inconsistent data origins")
            return chain
        verify_record("continuation ancestry plan", plan_record, base_dir=current)
        plan = _read(record_path(plan_record, base_dir=current))
        if (plan.get("role") != "simion_whole_unit_replay_plan" or plan.get("status") != "ready"
                or plan.get("reusable_unit_count") != 1 or plan.get("replay_unit_count") != 0
                or len(plan.get("units", [])) != 1 or plan["units"][0].get("key") != "complete_population"
                or plan["units"][0].get("action") != "reuse"):
            raise ValueError("continuation ancestry requires a complete population plan")
        origin = Path(plan["predecessor"]["run_dir"]).resolve(strict=True)
        records = manifest.get("inputs", {})
        bound = records.get("continuation_origin_manifest") or records.get("continuation_predecessor_manifest")
        if (not bound or record_path(bound, base_dir=current) != origin / "run_manifest.json"
                or str(bound.get("sha256", "")).upper() != str(plan["predecessor"]["manifest_sha256"]).upper()):
            raise ValueError("continuation ancestry manifest is not bound to plan")
        verify_record("continuation ancestry manifest", bound, base_dir=current)
        origins.append(origin)
        direct = records.get("continuation_predecessor_manifest")
        if not direct:
            raise ValueError("continuation direct predecessor is not bound")
        verify_record("continuation direct predecessor", direct, base_dir=current)
        direct_path = record_path(direct, base_dir=current)
        if direct_path.name != "run_manifest.json":
            raise ValueError("continuation direct predecessor manifest differs")
        current = direct_path.parent


def continuation_protection_paths(predecessor: Path) -> list[Path]:
    """Protect direct and partial-replay provenance, including data ancestors."""
    result: list[Path] = []
    pending = [predecessor.resolve(strict=True)]
    while pending:
        current = pending.pop()
        for source in continuation_ancestry(current):
            if source in result:
                continue
            result.append(source)
            manifest = _read(source/"run_manifest.json")
            record = manifest.get("inputs", {}).get("partial_predecessor_manifest")
            if record:
                verify_record("partial provenance predecessor", record, base_dir=source)
                path = record_path(record, base_dir=source)
                if path.name != "run_manifest.json":
                    raise ValueError("partial provenance predecessor manifest differs")
                if path.parent in result:
                    raise ValueError("partial provenance ancestry contains a cycle")
                pending.append(path.parent)
    return result


def _validate_continuation_science(run: Path, predecessor: Path) -> tuple[dict, dict]:
    """Verify frozen science before reusing either the population or a batch."""
    from common.contracts.write_run_manifest import require_completed_terminal_publication
    manifest_path = predecessor / "run_manifest.json"
    require_completed_terminal_publication(manifest_path)
    manifest = _read(manifest_path)
    if (manifest.get("project") != "dual_pressure_rectilinear_ion_processor"
            or manifest.get("mode") != "native_electrode_functional"
            or manifest.get("status") not in {"success", "failed"}
            or manifest.get("run_id") != predecessor.name):
        raise ValueError("IP predecessor must be an explicit terminal functional run")
    verify_record("predecessor run config", manifest["run_config"], base_dir=predecessor)
    records = list(manifest.get("inputs", {}).values()) + list(manifest.get("outputs", []))
    def bound(relative: str) -> Path:
        path = (predecessor / relative).resolve()
        matches = [record for record in records if record_path(record, base_dir=predecessor) == path]
        if len(matches) != 1:
            raise ValueError("IP predecessor must uniquely bind " + relative)
        verify_record("IP predecessor " + relative, matches[0], base_dir=predecessor)
        return path
    prior = _read(bound("inputs/resolved_model.json"))
    current = _read(run / "inputs/resolved_model.json")
    for key in ("baseline", "numerics", "source", "native_operating_point", "native_projection", "native_timing", "coordinate_transform"):
        if prior.get(key) != current.get(key):
            raise ValueError("IP predecessor scientific identity differs: " + key)
    if "injected_source" in prior:
        bound("inputs/injected_states.csv")
    if frozen_release_states(predecessor, prior) != frozen_release_states(run, current):
        raise ValueError("IP predecessor frozen particle states differ")
    for name in ("processor.gem", "runtime.lua", "collision_hs1.lua", "native_drive.lua", "simion_rf_drive.lua", "voltage_waveforms.lua", "extraction_force_audit.lua", "processor.fly2", "source_states.lua"):
        previous = bound("simion/" + name)
        if file_sha256(previous) != file_sha256(run / "simion" / name):
            raise ValueError("IP predecessor native input differs: " + name)
    old_profile = frozen_runtime_profile(predecessor, allow_legacy=True)
    new_profile = frozen_runtime_profile(run)
    if old_profile["retain_batch_trajectories"] != new_profile["retain_batch_trajectories"]:
        raise ValueError("IP predecessor trajectory output policy differs")
    return manifest, current


def prepare_completed_reanalysis(run: Path, predecessor: Path) -> dict:
    """Bind an already merged, completely recorded native run without a new Fly."""
    from common.simion.batch_continuation import WholeUnitReplayUnit, build_whole_unit_replay_plan

    run = run.resolve()
    ancestry = continuation_ancestry(predecessor)
    explicit_predecessor, predecessor = ancestry[0], ancestry[-1]
    if run in ancestry:
        raise ValueError("continuation requires a distinct new run")
    manifest, current = _validate_continuation_science(run, predecessor)
    prior = _read(predecessor / "inputs/resolved_model.json")
    manifest_path = predecessor / "run_manifest.json"
    required = [Path(value) for value in (
        "results/batch_merge_receipt.json", "results/batch_input_validation_receipt.json", "results/simion_execution_batch_plan.json", "results/simion_batch_resource_usage.json",
        "simion/events.csv", "simion/samples.csv", "simion/collision_rng_seeds.csv",
        "simion/hs1_bound_parameters.csv", "simion/extraction_steps.csv", "simion/extraction_impulses.csv",
        "logs/flight.log")]
    required.append(native_field_sample_path(predecessor).resolve())
    plan = build_whole_unit_replay_plan(predecessor_run_dir=predecessor, output_dir=run / "inputs",
        units=[WholeUnitReplayUnit("complete_population", tuple(required), True)])
    if plan["reusable_unit_count"] != 1:
        raise ValueError("IP predecessor lacks complete native population outputs")
    merge = _read(predecessor / "results/batch_merge_receipt.json")
    validation = _read(predecessor / "results/batch_input_validation_receipt.json")
    batches = _read(predecessor / "results/simion_execution_batch_plan.json")
    if (merge.get("role") != "ion_processor_batch_merge" or merge.get("all_ids_closed") is not True
            or merge.get("particle_count") != current["source"]["particle_count"]
            or validation.get("role") != "ion_processor_batch_input_validation"
            or validation.get("status") != "validated_before_sample_merge"
            or validation.get("particle_count") != merge["particle_count"]
            or merge.get("batch_count") != len(batches.get("batches", []))
            or batches.get("particle_count") != merge["particle_count"]):
        raise ValueError("IP predecessor lacks a closed native population")
    combined = (predecessor / "logs/flight.log").read_text(encoding="utf-8-sig")
    sections = re.split(r"(?m)^BATCH_LOG index=(\d+) offset=(-?\d+)\r?\n", combined)
    if len(sections) != 1 + 3 * len(batches["batches"]):
        raise ValueError("IP predecessor batch completion inventory differs")
    for batch, (index, offset, text) in zip(batches["batches"],
            zip(sections[1::3], sections[2::3], sections[3::3], strict=True), strict=True):
        expected_offset = 0 if "injected_source" in prior else batch["simion_particle_id_offset"]
        if (int(index) != batch["index"] or int(offset) != expected_offset or "ION_PROCESSOR_END" not in text
                or require_one_fly_completion(text.splitlines()).splats != batch["count"]):
            raise ValueError("IP predecessor batch native completion differs")
    # Preserve the actual original field authority in analysis metadata; no
    # field or workbench is opened or generated during complete reuse.
    current["native_field"] = prior["native_field"]
    _write(run / "inputs/resolved_model.json", current)
    config = _read(run / "run_config.json")
    config["inputs"]["continuation_predecessor_manifest"] = str(explicit_predecessor / "run_manifest.json")
    if explicit_predecessor != predecessor:
        config["inputs"]["continuation_origin_manifest"] = str(manifest_path)
    config["inputs"]["continuation_plan"] = str(run / "inputs/simion_whole_unit_replay_plan.json")
    config["parameters"]["continuation_predecessor"] = str(explicit_predecessor)
    _write(run / "run_config.json", config)
    return plan


def native_data_directory(run: Path) -> Path:
    """Read the frozen continuation plan, or use this run's native results."""
    plan_path = run / "inputs/simion_whole_unit_replay_plan.json"
    if not plan_path.is_file():
        return run / "simion"
    plan = _read(plan_path)
    if (plan.get("role") != "simion_whole_unit_replay_plan" or plan.get("status") != "ready"
            or plan.get("reusable_unit_count") != 1 or plan.get("replay_unit_count") != 0):
        raise ValueError("IP continuation plan does not bind a complete population")
    outputs = plan["units"][0]["terminal_outputs"]
    matches = [Path(row["path"]) for row in outputs if Path(row["path"]).name == "events.csv"]
    if len(matches) != 1 or matches[0].parent.name != "simion":
        raise ValueError("IP continuation events reference differs")
    return matches[0].parent


def _partial_unit_source(unit: dict) -> Path:
    inputs = [Path(item["path"]).resolve() for item in unit["terminal_outputs"]
              if Path(item["path"]).name == "batch_input.json"]
    if len(inputs) != 1 or not re.fullmatch(r"simion_batch_\d+", inputs[0].parent.name):
        raise ValueError("IP reusable batch lacks its unique source directory")
    return inputs[0].parent.parent


def prepare_partial_batch_replay(run: Path, predecessor: Path) -> dict:
    """Plan complete native workers from an explicit failed predecessor."""
    from common.simion.batch_continuation import WholeUnitReplayUnit, build_whole_unit_replay_plan

    run, predecessor = run.resolve(), predecessor.resolve(strict=True)
    if run == predecessor:
        raise ValueError("continuation requires a distinct run")
    ancestry = continuation_ancestry(predecessor)
    if len(ancestry) != 1:
        raise ValueError("partial batches must belong to the immediate predecessor")
    manifest, current = _validate_continuation_science(run, predecessor)
    records = {record_path(record, base_dir=predecessor): record
               for record in [manifest["run_config"], *manifest["inputs"].values(), *manifest["outputs"]]}
    def small(relative: str) -> Path | None:
        path = (predecessor / relative).resolve()
        record = records.get(path)
        if record is None or not path.is_file():
            return None
        verify_record("IP partial " + relative, record, base_dir=predecessor)
        return path

    batch_path = small("results/simion_execution_batch_plan.json")
    if batch_path is None:
        raise ValueError("IP predecessor lacks its bound batch plan")
    batches = _read(batch_path)
    if batches.get("particle_count") != current["source"]["particle_count"]:
        raise ValueError("IP predecessor batch population differs")
    field_sample = native_field_sample_path(predecessor).resolve()
    field_record = records.get(field_sample)
    if field_record is not None:
        verify_record("IP predecessor field samples", field_record, base_dir=predecessor)
    if field_record is None:
        raise ValueError("IP predecessor lacks bound native field samples for analysis")
    prior_plan_path = small("inputs/partial_batch_replay/simion_whole_unit_replay_plan.json")
    prior_batch_path = small("inputs/partial_batch_replay/batch_plan.json")
    inherited = {}
    if prior_plan_path is not None:
        if prior_batch_path is None or _read(prior_batch_path) != batches:
            raise ValueError("IP inherited batch partition differs")
        prior_plan = _read(prior_plan_path)
        previous = manifest.get("inputs", {}).get("partial_predecessor_manifest")
        if (not previous or record_path(previous, base_dir=predecessor) != Path(prior_plan["predecessor"]["run_dir"]).resolve()/"run_manifest.json"
                or str(previous.get("sha256", "")).upper() != str(prior_plan["predecessor"]["manifest_sha256"]).upper()):
            raise ValueError("IP inherited replay plan lacks predecessor binding")
        verify_record("IP inherited replay predecessor", previous, base_dir=predecessor)
        inherited = {item["key"]: item for item in prior_plan["units"] if item["action"] == "reuse"}
    expected_first = 1
    units = []
    for batch in batches.get("batches", []):
        index, first, last, count = (batch[k] for k in ("index", "particle_id_min", "particle_id_max", "count"))
        if (type(index) is not int or index != len(units) + 1 or first != expected_first
                or count != last-first+1 or batch["simion_particle_id_offset"] != first-1):
            raise ValueError("IP predecessor batch partition differs")
        expected_first = last+1
        prefix = f"simion_batch_{index:04d}"
        receipt = small(f"results/native_batch_completion_{index:04d}.json")
        input_receipt = small(f"{prefix}/batch_input.json")
        log = small(f"logs/flight_batch_{index:04d}.log")
        complete = False
        if receipt and input_receipt and log:
            fact, worker = _read(receipt), _read(input_receipt)
            text = log.read_text(encoding="utf-8-sig")
            if (fact.get("role") == "ion_processor_native_batch_completion" and fact.get("completed") is True
                    and fact.get("exit_code") == 0 and fact.get("batch") == batch and worker.get("batch") == batch
                    and "ION_PROCESSOR_END" in text):
                try:
                    complete = require_one_fly_completion(text.splitlines()).splats == count
                except ValueError:
                    complete = False
        paths = [Path(f"results/native_batch_completion_{index:04d}.json"), Path(f"{prefix}/batch_input.json"),
                 Path(f"logs/flight_batch_{index:04d}.log"), Path(f"{prefix}/collision_rng_seeds.csv"),
                 Path(f"{prefix}/hs1_bound_parameters.csv")]
        archive_prefix = f"results/merged_worker_csv_batch_{index:04d}"
        archive_plan = small(archive_prefix + "_archive_plan.json")
        archive_receipt = small(archive_prefix + "_archive_receipt.json")
        if archive_plan and archive_receipt:
            archived, removal = _read(archive_plan), _read(archive_receipt)
            archive = predecessor / (archive_prefix + ".zip")
            expected = [f"{prefix}/{name}" for name in ("events.csv", "samples.csv", "extraction_steps.csv", "extraction_impulses.csv")]
            if (archived.get("role") != "ion_processor_worker_csv_archive_plan" or archived.get("status") != "verified"
                    or [item.get("path") for item in archived.get("source_files", [])] != expected
                    or removal.get("role") != "ion_processor_worker_csv_archive_receipt" or removal.get("status") != "complete"
                    or removal.get("plan_sha256") != file_sha256(archive_plan)
                    or removal.get("removed_files") != expected
                    or archived.get("archive", {}).get("path") != archive.relative_to(predecessor).as_posix()):
                raise ValueError("IP worker archive evidence differs")
            paths.extend([Path(archive_prefix + ".zip"), Path(archive_prefix + "_archive_plan.json"), Path(archive_prefix + "_archive_receipt.json")])
        else:
            paths.extend(Path(f"{prefix}/{name}") for name in ("events.csv", "samples.csv", "extraction_steps.csv", "extraction_impulses.csv"))
        complete = complete and all((predecessor/path).resolve() in records and (predecessor/path).is_file() for path in paths)
        units.append(WholeUnitReplayUnit(f"batch_{index:04d}", tuple(paths), complete))
    if not units or expected_first != batches["particle_count"]+1:
        raise ValueError("IP predecessor batch partition does not close")
    plan = build_whole_unit_replay_plan(predecessor_run_dir=predecessor, output_dir=run/"inputs/partial_batch_replay", units=units)
    protected = set(continuation_protection_paths(predecessor)) if inherited else set()
    with tempfile.TemporaryDirectory(prefix="ip_continuation_plan_") as temporary:
        for item in plan["units"]:
            previous = inherited.get(item["key"])
            if item["action"] != "replay" or previous is None:
                continue
            source = _partial_unit_source(previous)
            if source not in protected:
                raise ValueError("IP inherited batch source is outside protected ancestry")
            checked = build_whole_unit_replay_plan(predecessor_run_dir=source, output_dir=Path(temporary),
                units=[WholeUnitReplayUnit(item["key"], tuple(Path(row["path"]) for row in previous["terminal_outputs"]), True)])
            if checked["reusable_unit_count"] != 1 or checked["units"][0]["terminal_outputs"] != previous["terminal_outputs"]:
                raise ValueError("IP inherited batch identity differs")
            item.update(checked["units"][0])
    plan["reusable_unit_count"] = sum(item["action"] == "reuse" for item in plan["units"])
    plan["replay_unit_count"] = sum(item["action"] == "replay" for item in plan["units"])
    _write(run/"inputs/partial_batch_replay/simion_whole_unit_replay_plan.json", plan)
    _write(run/"inputs/partial_batch_replay/batch_plan.json", batches)
    field_record = dict(field_record); field_record["path"] = str(field_sample)
    _write(run/"inputs/partial_batch_replay/field_source.json", field_record)
    current["native_field"] = _read(predecessor/"inputs/resolved_model.json")["native_field"]
    _write(run/"inputs/resolved_model.json", current)
    config = _read(run/"run_config.json")
    config.setdefault("inputs", {}).update(partial_predecessor_manifest=str(predecessor/"run_manifest.json"),
        partial_batch_replay_plan=str(run/"inputs/partial_batch_replay/simion_whole_unit_replay_plan.json"),
        partial_batch_plan=str(run/"inputs/partial_batch_replay/batch_plan.json"),
        partial_field_source=str(run/"inputs/partial_batch_replay/field_source.json"),
        partial_field_samples=str(field_sample))
    config.setdefault("parameters", {})["continuation_predecessor"] = str(predecessor)
    _write(run/"run_config.json", config)
    return plan


def native_field_sample_path(run: Path) -> Path:
    """Use locally measured field samples, otherwise the verified predecessor record."""
    local = run/"simion/native_field_samples.csv"
    if local.is_file():
        return local
    record_pathname = run/"inputs/partial_batch_replay/field_source.json"
    if record_pathname.is_file():
        return Path(_read(record_pathname)["path"])
    plan_path = run/"inputs/simion_whole_unit_replay_plan.json"
    if plan_path.is_file():
        outputs = _read(plan_path)["units"][0]["terminal_outputs"]
        matches = [Path(item["path"]) for item in outputs if Path(item["path"]).name == "native_field_samples.csv"]
        if len(matches) != 1:
            raise ValueError("continuation field sample reference differs")
        return matches[0]
    return native_data_directory(run)/"native_field_samples.csv"


def restore_reusable_batches(run: Path) -> dict:
    """Reference raw workers; extract only archived CSVs required by the merger."""
    run = run.resolve()
    plan = _read(run/"inputs/partial_batch_replay/simion_whole_unit_replay_plan.json")
    batches = _read(run/"inputs/partial_batch_replay/batch_plan.json")
    if len(plan["units"]) != len(batches["batches"]):
        raise ValueError("partial replay inventory differs")
    mother = frozen_release_states(run, _read(run/"inputs/resolved_model.json"))
    restored = []
    for batch, unit in zip(batches["batches"], plan["units"], strict=True):
        index = batch["index"]
        if unit["key"] != f"batch_{index:04d}":
            raise ValueError("partial replay batch order differs")
        if unit["action"] != "reuse":
            continue
        parent = _partial_unit_source(unit)
        paths = {Path(item["path"]).resolve(): item["sha256"] for item in unit["terminal_outputs"]}
        folder = f"simion_batch_{index:04d}"
        old_input = _read(parent/folder/"batch_input.json")
        expected_ids = [row["particle_id"] for row in mother[batch["particle_id_min"]-1:batch["particle_id_max"]]]
        if old_input.get("batch") != batch or old_input.get("source_global_ids") != expected_ids:
            raise ValueError("partial replay worker inputs differ")
        def require_bound(relative: str) -> None:
            source = (parent/relative).resolve()
            if source not in paths:
                raise ValueError("partial replay source is not bound by the plan")
        for relative in (f"logs/flight_batch_{index:04d}.log", f"results/native_batch_completion_{index:04d}.json",
                         f"{folder}/collision_rng_seeds.csv", f"{folder}/hs1_bound_parameters.csv"):
            require_bound(relative)
        prefix = f"results/merged_worker_csv_batch_{index:04d}"
        archive = (parent/(prefix+".zip")).resolve()
        names = [f"{folder}/{name}" for name in ("events.csv", "samples.csv", "extraction_steps.csv", "extraction_impulses.csv")]
        if archive in paths:
            archive_plan = (parent/(prefix+"_archive_plan.json")).resolve()
            if archive_plan not in paths:
                raise ValueError("partial archive plan is not bound")
            metadata = _read(archive_plan)
            (run/folder).mkdir(exist_ok=True)
            with zipfile.ZipFile(archive) as bundle:
                if bundle.namelist() != names:
                    raise ValueError("partial archive member inventory differs")
                for item in metadata["source_files"]:
                    destination = run/item["path"]
                    digest, count = hashlib.sha256(), 0
                    with bundle.open(item["path"]) as src, destination.open("xb") as dst:
                        while block := src.read(1024*1024):
                            dst.write(block); digest.update(block); count += len(block)
                    if count != item["bytes"] or digest.hexdigest().upper() != item["sha256"]:
                        raise ValueError("partial archive member identity differs")
        else:
            for name in names:
                require_bound(name)
        restored.append(index)
    return {"restored_batch_indices": restored}


def analysis_source_record(run: Path, path: Path) -> dict:
    """Reuse the already verified continuation identity for diagnostic provenance."""
    path = path.resolve()
    field_record = run/"inputs/partial_batch_replay/field_source.json"
    if field_record.is_file():
        record = _read(field_record)
        if Path(record["path"]).resolve() == path:
            return record
    plan_path = run / "inputs/simion_whole_unit_replay_plan.json"
    if plan_path.is_file():
        outputs = _read(plan_path)["units"][0]["terminal_outputs"]
        matches = [row for row in outputs if Path(row["path"]).resolve() == path]
        if len(matches) != 1 or not path.is_file():
            raise ValueError("IP continuation diagnostic source is not bound")
        return dict(path=str(path), bytes=path.stat().st_size, sha256=matches[0]["sha256"])
    return dict(path=str(path), bytes=path.stat().st_size, sha256=file_sha256(path))


def prepare_request(run: Path, native_pa0_record: dict | None = None) -> dict:
    """Describe the real one-instance native loading identity without CPU limits."""
    c = _read(run/"inputs/resolved_model.json")
    _archive_policy(run)
    profile = frozen_runtime_profile(run)
    retain = profile["retain_batch_trajectories"]
    if not isinstance(retain, bool):
        raise ValueError("retain_batch_trajectories must be boolean")
    field = Path(c["native_field"]["directory"])/"processor.pa0"
    source_manifest = c["native_field"].get("source_manifest")
    if source_manifest:
        if native_pa0_record is not None:
            raise ValueError("external published field cannot override manifest identity")
        parent = Path(source_manifest).parent
        manifest = _read(Path(source_manifest))
        outputs = manifest["outputs"]
        records = list(manifest["inputs"].values()) + (list(outputs.values()) if isinstance(outputs, dict) else outputs)
        pa_sha = next(r["sha256"] for r in records if record_path(r, base_dir=parent)==field.resolve())
    elif native_pa0_record is not None:
        # Internal PS projection: its live public guard owns this new run's PA.
        # This is not an authorization to reuse external or unprotected assets.
        if (not field.resolve().is_relative_to(run.resolve())
                or record_path(native_pa0_record) != field.resolve()
                or native_pa0_record.get("bytes") != field.stat().st_size
                or not re.fullmatch(r"[0-9A-Fa-f]{64}", str(native_pa0_record.get("sha256", "")))):
            raise ValueError("guarded native controller record differs from this run")
        pa_sha = native_pa0_record["sha256"]
    else:
        pa_sha = file_sha256(field)
    request = dispatch_request_for_field(run, c, pa_sha, retain, processor_program=run/"simion/processor.lua")
    templates = not bool(source_manifest)
    preparation = dict(requires_vendor_templates=templates, native_pa0_record=dict(path=str(field.resolve()),bytes=field.stat().st_size,sha256=pa_sha),
                       template_count=request["particle_count"],script=str(run/"simion/build_batch_iobs.lua"))
    if templates:
        destinations=[]
        for index in range(1,request["particle_count"]+1):
            folder=run/f"simion_batch_{index:04d}"
            folder.mkdir(exist_ok=True)
            destinations.append(str((folder/"processor.iob").resolve()).replace("\\","/"))
        canonical=json.dumps(str((run/"simion/processor.iob").resolve()).replace("\\","/"))
        expected=json.dumps(str(field.resolve()).replace("\\","/").lower())
        script="local directory=assert(debug.getinfo(1,'S').source:sub(2):match('^(.*[/\\\\])'))\n"
        script+="local native_path=assert(loadfile(directory..'native_run_path.lua'))()\nlocal wb=simion.wb\nwb:load(native_path("+canonical+"))\n"
        script+="assert(wb.instances[1].pa.path:gsub(string.char(92),'/'):lower()==native_path("+expected+"):gsub(string.char(92),'/'):lower()"+",'batch template PA identity mismatch')\n"
        for target in destinations:script+="wb:save(native_path("+json.dumps(target)+"))\n"
        script+="print('ION_PROCESSOR_BATCH_IOB_TEMPLATES=PASS')\n"
        (run/"simion/build_batch_iobs.lua").write_text(script,encoding="utf-8")
    _write(run/"inputs/batch_iob_preparation.json",preparation)
    # Validate using the public planner; the runner performs live planning again.
    resource_scheduler.plan_simion_dispatch(request, [])
    _write(run/"inputs/simion_dispatch_request.json", request)
    return request


def materialize_batches(run: Path, batch_plan: Path) -> dict:
    """Create isolated sibling workbenches; keep IOB relative PA references valid."""
    from projects.dual_pressure_rectilinear_ion_processor.analysis.functional import lua_literal
    run = run.resolve()
    c = _read(run/"inputs/resolved_model.json")
    retain = frozen_runtime_profile(run)["retain_batch_trajectories"]
    if not isinstance(retain, bool):
        raise ValueError("retain_batch_trajectories must be boolean")
    plan = _read(batch_plan)
    partial_path = run/"inputs/partial_batch_replay/simion_whole_unit_replay_plan.json"
    reused = {item["key"] for item in _read(partial_path)["units"] if item["action"] == "reuse"} if partial_path.exists() else set()
    mother = frozen_release_states(run, c)
    if plan["particle_count"] != len(mother):
        raise ValueError("batch plan population differs from frozen mother cohort")
    controls = ("processor.lua", "scientific_event_csv.lua", "collision_hs1.lua", "native_drive.lua", "simion_rf_drive.lua", "voltage_waveforms.lua", "extraction_force_audit.lua", "processor.iob")
    workers = []
    for batch in plan["batches"]:
        if f"batch_{batch['index']:04d}" in reused:
            continue
        first, last, offset = (batch[k] for k in ("particle_id_min", "particle_id_max", "simion_particle_id_offset"))
        if not 1<=first<=last<=len(mother) or last-first+1!=batch["count"] or offset!=first-1:
            raise ValueError("invalid canonical batch interval")
        folder = run/f"simion_batch_{batch['index']:04d}"
        receipt = folder/"batch_input.json"
        if receipt.exists():
            if _read(receipt)["batch"] != batch:
                raise ValueError("replan changed an already materialized batch")
        else:
            template=folder/"processor.iob"
            is_template=not c["native_field"].get("source_manifest")
            if folder.exists():
                allowed = {"processor.iob", "processor.lua", "processor.fly2"}
                if not is_template or not {path.name for path in folder.iterdir()} <= allowed:
                    raise ValueError("batch directory exists without an immutable input receipt")
                # Official wb:save copies associated programs and particles along
                # with the relocated IOB. Only exact master controls may be
                # replaced by the immutable worker copy / canonical source slice.
                for name in ("processor.lua", "processor.fly2"):
                    associated = folder / name
                    if (associated.exists() or associated.is_symlink()) and (
                        not associated.is_file() or associated.is_symlink()
                        or associated.stat().st_nlink != 1
                        or associated.resolve().parent != folder.resolve()
                        or file_sha256(associated) != file_sha256(run/"simion"/name)
                    ):
                        raise ValueError("vendor batch template companion differs from canonical master: " + name)
            folder.mkdir(exist_ok=True)
            if is_template and not template.is_file():raise ValueError("native batch IOB template was not built before flight")
            # Same parent and depth as canonical simion: every relative IOB PA
            # reference resolves identically. No binary rewrite or vendor save.
            if folder.parent != (run/"simion").parent:
                raise ValueError("batch IOB must be a sibling of canonical IOB")
            for name in controls:
                if name == "processor.iob" and is_template:continue
                shutil.copyfile(run/"simion"/name, folder/name)
            worker_config = copy.deepcopy(c)
            worker_config["execution_batch"] = dict(particle_id_offset=offset, particle_id_min=first, particle_id_max=last, retain_trajectories=retain)
            if "injected_source" in c:
                worker_config["execution_batch"]["global_particle_ids"] = [r["particle_id"] for r in mother[first-1:last]]
            beams, companions = [], []
            for local_id, row in enumerate(mother[first-1:last], 1):
                v = [row[k] for k in ("vx_m_s", "vy_m_s", "vz_m_s")]
                energy = kinetic_energy_ev(row["mass_amu"], *v)
                xyz = [row[k] for k in ("x_mm", "y_mm", "z_mm")]
                world = to_project_position(c, xyz)
                arrival = row["arrival_time_us"] if "injected_source" in c else 0
                state, beam = project_direct_velocity(particle_id=local_id, time_us=arrival,
                    position_mm=xyz, velocity_m_s=v, energy_ev=energy, mass_amu=row["mass_amu"],
                    charge_state=row["charge_state"], beam_position_mm=list(world),
                    beam_direction=list(to_project_vector(c, v)), weight=1, color=1)
                companions.append(state)
                beams.append(beam)
            (folder/"processor.fly2").write_text(render_standard_beams(beams),encoding="utf-8")
            (folder/"source_states.lua").write_text(render_source_states(companions),encoding="utf-8")
            (folder/"frozen_config.lua").write_text("return "+lua_literal(worker_config)+"\n",encoding="utf-8")
            _write(receipt,dict(batch=batch,source_global_ids=[r["particle_id"] for r in mother[first-1:last]],iob_policy=("vendor_saved_absolute_PA_reference_template" if is_template else "byte_exact_sibling_copy_same_relative_PA_resolution"),native_field_directory=c["native_field"]["directory"]))
        workers.append(dict(batch=batch,directory=str(folder)))
    config = _read(run/"run_config.json")
    for worker in workers:
        for path in Path(worker["directory"]).iterdir():
            if path.name in (*controls,"processor.fly2","source_states.lua","frozen_config.lua","batch_input.json"):
                config.setdefault("inputs",{})[str(path.relative_to(run))]=str(path)
    config.setdefault("inputs",{}).update(simion_dispatch_request=str(run/"inputs/simion_dispatch_request.json"),simion_batch_plan=str(batch_plan))
    _write(run/"run_config.json",config)
    _write(run/"results/batch_materialization.json",dict(workers=workers))
    return dict(workers=workers)


def _rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(encoding="utf-8-sig",newline="") as stream:
        reader=csv.DictReader(stream)
        return reader.fieldnames or [],list(reader)


def _csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)


def _archive_policy(run: Path) -> bool:
    enabled = frozen_runtime_profile(run)["archive_merged_worker_csv"]
    if not isinstance(enabled, bool):
        raise ValueError("archive_merged_worker_csv must be boolean")
    return enabled


def _verify_worker_archive(archive: Path, records: list[dict]) -> None:
    """Read every archived byte and verify CRC plus original SHA/size identities."""
    with zipfile.ZipFile(archive) as bundle:
        if bundle.namelist() != [record["path"] for record in records] or bundle.testzip() is not None:
            raise ValueError("worker CSV archive member inventory or CRC differs")
        for record in records:
            digest, size = hashlib.sha256(), 0
            with bundle.open(record["path"]) as stream:
                while block := stream.read(1024*1024):
                    digest.update(block)
                    size += len(block)
            if size != record["bytes"] or digest.hexdigest().upper() != record["sha256"]:
                raise ValueError("worker CSV archive identity differs: " + record["path"])


def _archive_merged_worker_csv(run: Path, batch: dict) -> dict:
    """Retain one consumed worker before the public merger opens the next."""
    run = run.resolve()
    prefix = f"merged_worker_csv_batch_{batch['index']:04d}"
    archive = run/"results"/(prefix+".zip")
    plan_path = run/"results"/(prefix+"_archive_plan.json")
    receipt_path = run/"results"/(prefix+"_archive_receipt.json")
    if any(path.exists() for path in (archive, plan_path, receipt_path)):
        raise ValueError("worker CSV archive outputs already exist; use a new run")
    records = []
    for name in ("events.csv", "samples.csv", "extraction_steps.csv", "extraction_impulses.csv"):
        path = run/f"simion_batch_{batch['index']:04d}"/name
        if path.resolve() != path or not path.is_file() or path.is_symlink():
            raise ValueError("worker CSV archive source is not an exact same-run regular file")
        records.append(dict(path=path.relative_to(run).as_posix(),
                            bytes=path.stat().st_size, sha256=file_sha256(path)))
    if not records or len({record["path"] for record in records}) != len(records):
        raise ValueError("worker CSV archive source inventory is empty or duplicated")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for record in records:
            with (run/record["path"]).open("rb") as source, bundle.open(record["path"], "w", force_zip64=True) as target:
                shutil.copyfileobj(source, target, length=1024*1024)
    with archive.open("rb+") as stream:
        stream.flush()
        os.fsync(stream.fileno())
    _verify_worker_archive(archive, records)
    plan = dict(schema_version=1, role="ion_processor_worker_csv_archive_plan", status="verified",
                source_files=records, archive=dict(path=archive.relative_to(run).as_posix(),
                    bytes=archive.stat().st_size, sha256=file_sha256(archive)),
                validation_receipt_sha256=file_sha256(run/"results/batch_input_validation_receipt.json"),
                semantics="Byte-exact worker CSV preservation after all ID/HS1/seed checks and consumption by the public CSV merger; archives reconstruct evidence even if a later batch merge fails")
    write_json_atomic(plan_path, plan)
    receipt = dict(schema_version=1, role="ion_processor_worker_csv_archive_receipt", status="removal_pending",
                   plan_path=plan_path.relative_to(run).as_posix(), plan_sha256=file_sha256(plan_path), removed_files=[])
    write_json_atomic(receipt_path, receipt)
    try:
        for record in remove_recorded_files(run, records):
            receipt["removed_files"].append(record["path"])
            write_json_atomic(receipt_path, receipt)
    except Exception as exc:
        receipt.update(status="removal_failed", error=str(exc))
        write_json_atomic(receipt_path, receipt)
        raise
    receipt["status"] = "complete"
    write_json_atomic(receipt_path, receipt)
    return receipt


def merge_batches(run: Path, batch_plan: Path) -> dict:
    """Validate full native batch closure, then use public offset rebasing once."""
    archive_workers = _archive_policy(run)
    c, plan = _read(run/"inputs/resolved_model.json"), _read(batch_plan)
    original_ids = c["injected_source"]["particle_ids"] if "injected_source" in c else None
    partial_path = run/"inputs/partial_batch_replay/simion_whole_unit_replay_plan.json"
    partial = _read(partial_path) if partial_path.exists() else None
    reused = {item["key"]: item for item in partial["units"] if item["action"] == "reuse"} if partial else {}
    events, samples, seeds, audits, log_parts = [], [], [], [], []
    from projects.dual_pressure_rectilinear_ion_processor.analysis.extraction_force_budget import STEP_COLUMNS, IMPULSE_COLUMNS
    force_headers = {"extraction_steps.csv":STEP_COLUMNS, "extraction_impulses.csv":IMPULSE_COLUMNS}
    force_sources = {name:[] for name in force_headers}
    original_fields = None
    for batch in plan["batches"]:
        folder=run/f"simion_batch_{batch['index']:04d}"
        unit = reused.get(f"batch_{batch['index']:04d}")
        parent = _partial_unit_source(unit) if unit else None
        source_folder = (parent/folder.name) if unit else folder
        archived = bool(unit and any(Path(item["path"]).suffix == ".zip" for item in unit["terminal_outputs"]))
        csv_folder = folder if archived else source_folder
        offset=0 if original_ids is not None else batch["simion_particle_id_offset"]
        log=(parent if unit else run)/f"logs/flight_batch_{batch['index']:04d}.log"
        log_text = log.read_text(encoding="utf-8-sig")
        if "ION_PROCESSOR_END" not in log_text:
            raise ValueError("batch lacks native completion sentinel")
        completion = require_one_fly_completion(log_text.splitlines())
        if completion.splats != batch["count"]:
            raise ValueError("batch native Fly splats differ from the declared particle count")
        fields, rows=_rows(csv_folder/"events.csv")
        if original_fields is None:original_fields=fields
        if fields!=original_fields:raise ValueError("batch event columns differ")
        expected=(original_ids[batch["particle_id_min"]-1:batch["particle_id_max"]]
                  if original_ids is not None else list(range(1,batch["count"]+1)))
        for event in ("source","terminal"):
            if sorted(int(row["particle_id"]) for row in rows if row["event"]==event)!=expected:
                raise ValueError("batch source/terminal IDs do not close")
        if any(int(row["particle_id"]) not in expected for row in rows):raise ValueError("foreign batch ID")
        _, sample_rows = _rows(csv_folder/"samples.csv")
        if any(int(row["particle_id"]) not in expected for row in sample_rows):
            raise ValueError("foreign batch sample ID")
        events.append((csv_folder/"events.csv",offset));samples.append((csv_folder/"samples.csv",offset))
        for name in force_sources:
            force_fields, force_rows = _rows(csv_folder/name)
            if tuple(force_fields) != force_headers[name]:
                raise ValueError("batch force-audit header differs from declared protocol")
            if any(int(row["particle_id"]) not in expected for row in force_rows):
                raise ValueError("foreign batch force-audit ID")
            force_sources[name].append((csv_folder/name,offset))
        seeds.append((source_folder/"collision_rng_seeds.csv",offset))
        audit_fields,audit=_rows(source_folder/"hs1_bound_parameters.csv")
        if len(audit)!=2 or {row["phase"] for row in audit}!={"before_init","after_init"}:raise ValueError("batch lacks HS1 audit phases")
        audits.append((audit_fields,audit))
        log_parts.append(f"BATCH_LOG index={batch['index']} offset={offset}\n"+log_text)
    merge_rebased_particle_csvs(events,run/"simion/events.csv")
    merge_rebased_particle_csvs(seeds,run/"simion/collision_rng_seeds.csv")
    _,seed_rows=_rows(run/"simion/collision_rng_seeds.csv")
    ids=[]
    for row in seed_rows:
        particle=int(row["particle_id"]);ids.append(particle)
        if int(row["global_particle_id"])!=particle or int(row["seed"])!=c["numerics"]["seed"]+particle-1:
            raise ValueError("collision RNG does not match canonical per-particle policy")
    if ids!=(original_ids if original_ids is not None else list(range(1,c["source"]["particle_count"]+1))):raise ValueError("seed receipt does not cover full admitted cohort")
    expected_audit = dict(gas_mass_amu=c["baseline"]["gas"]["mass_amu"],temperature_k=c["baseline"]["gas"]["temperature_k"],pressure_pa=0,
                          sigma_m2=c["baseline"]["gas"]["cross_section_m2"],mean_free_path_mm=c["baseline"]["gas"]["mean_free_path_mm"],
                          steps_per_mfp=c["numerics"]["hs1_steps_per_mfp"],random_seed=c["numerics"]["seed"]+1,mark_collisions=0,trace_level=0)
    for fields,audit in audits:
        for row in audit:
            if any(float(row[key])!=value for key,value in expected_audit.items()):raise ValueError("worker HS1 bindings differ from frozen authority")
    canonical=[next(row for row in audits[0][1] if row["phase"]==phase) for phase in ("before_init","after_init")]
    _csv(run/"simion/hs1_bound_parameters.csv",audits[0][0],canonical)
    (run/"logs/flight.log").write_text("\n".join(log_parts),encoding="utf-8")
    for name, sources in force_sources.items():
        merge_rebased_particle_csvs(sources,run/"simion"/name)
    result=dict(schema_version=1,role="ion_processor_batch_merge",particle_count=len(ids),batch_count=len(plan["batches"]),all_ids_closed=True,
                hs1_audit="all per-worker rows validated; canonical CSV is the identical before/after pair",rng_policy=c["numerics"]["collision_rng_policy"])
    write_json_atomic(run/"results/batch_input_validation_receipt.json",
           {**result, "role": "ion_processor_batch_input_validation", "status": "validated_before_sample_merge"})
    archive_receipts = []
    def consumed_samples():
        for batch, source in zip(plan["batches"], samples, strict=True):
            yield source
            # The public merger closes each source before requesting the next.
            # Retain its byte-exact ZIP before removing any raw source file.
            if archive_workers and f"batch_{batch['index']:04d}" not in reused:
                archive_receipts.append(_archive_merged_worker_csv(run, batch))
            unit = reused.get(f"batch_{batch['index']:04d}")
            if unit and any(Path(item["path"]).suffix == ".zip" for item in unit["terminal_outputs"]):
                origin = _partial_unit_source(unit)
                archive_plan = origin/f"results/merged_worker_csv_batch_{batch['index']:04d}_archive_plan.json"
                list(remove_recorded_files(run, _read(archive_plan)["source_files"]))
    merge_rebased_particle_csvs(consumed_samples(),run/"simion/samples.csv")
    _write(run/"results/batch_merge_receipt.json",result)
    if archive_workers:
        write_json_atomic(run/"results/merged_worker_csv_archive_receipt.json",
            dict(schema_version=1, role="ion_processor_worker_csv_archive_aggregate", status="complete",
                 merge_receipt_sha256=file_sha256(run/"results/batch_merge_receipt.json"), batches=archive_receipts,
                 reused_batch_indices=[batch["index"] for batch in plan["batches"] if f"batch_{batch['index']:04d}" in reused]))
    return result
