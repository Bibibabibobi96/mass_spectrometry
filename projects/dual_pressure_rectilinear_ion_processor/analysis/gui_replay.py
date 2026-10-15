"""Prepare isolated native-field replays and compare actual event/state evidence."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import shutil
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record

PROJECT = "dual_pressure_rectilinear_ion_processor"
ABS_TOL = 1e-9
REL_TOL = 1e-12


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def prepare_replay(run: Path, baseline_run: Path, repeat_fly_count: int = 1) -> dict:
    """Copy frozen controls and isolate the complete verified native PA family.

    Does not run SIMION, change source file attributes, or publish a terminal
    manifest. The caller owns capacity/host leases and checkpoint publication.
    """
    if isinstance(repeat_fly_count, bool) or not isinstance(repeat_fly_count, int) or repeat_fly_count not in (1, 2):
        raise ValueError("repeat_fly_count must be 1 or 2")
    run, baseline_run = run.resolve(), baseline_run.resolve()
    if run == baseline_run or baseline_run in run.parents or run in baseline_run.parents:
        raise ValueError("GUI replay must use a separate, nonoverlapping run")
    manifest_path = baseline_run / "run_manifest.json"
    manifest = _read(manifest_path)
    if manifest.get("project") != PROJECT or manifest.get("status") not in {"success", "failed"}:
        raise ValueError("baseline must be a terminal Ion Processor run")
    records = list(manifest.get("inputs", {}).values()) + list(manifest.get("outputs", []))
    if "run_config" in manifest:
        records.append(manifest["run_config"])
    if not records:
        raise ValueError("baseline manifest has no bound records")
    verified = {}
    for index, record in enumerate(records):
        verify_record(f"GUI baseline record {index}", record, base_dir=baseline_run)
        verified[record_path(record, base_dir=baseline_run)] = record
    summary = _read(baseline_run / "summary.json")
    if summary.get("role") != "ion_processor_functional_summary" or summary.get("status") not in {"functional_pass", "functional_incomplete", "exploration_pass", "exploration_incomplete"}:
        raise ValueError("baseline lacks measured physical summary")
    log = baseline_run / "logs/flight.log"
    if "ION_PROCESSOR_END" not in log.read_text(encoding="utf-8-sig"):
        raise ValueError("baseline Fly completion sentinel is missing")
    required = [baseline_run / "summary.json", log, baseline_run / "simion/events.csv", baseline_run / "simion/samples.csv", baseline_run / "results/particle_state.csv"]
    config = _read(baseline_run / "inputs/resolved_model.json")
    profile = config.get("source_profile")
    if profile not in {"functional", "exploration"} or summary.get("source_profile") != profile:
        raise ValueError("baseline source_profile must be frozen and match measured summary")
    if not summary["status"].startswith(profile + "_"):
        raise ValueError("baseline status would upgrade or mislabel its frozen source profile")
    field_directory = Path(config.get("native_field", {}).get("directory", str(baseline_run / "simion")))
    if not field_directory.is_absolute():
        field_directory = baseline_run / field_directory
    field_directory = field_directory.resolve()
    family = [field_directory / ("processor.pa" + suffix) for suffix in ["#", *map(str, range(16)), "-surf"]]
    controls = ["frozen_config.lua", "collision_hs1.lua", "source_states.lua", "native_drive.lua", "simion_rf_drive.lua", "processor.fly2"]
    required += family + [baseline_run / "simion" / name for name in [*controls, "processor.lua"]]
    required += [baseline_run / "inputs/resolved_model.json"]
    field_diagnostic_files = []
    if (baseline_run / "inputs/field_diagnostics.json").is_file():
        output_paths = {record_path(record, base_dir=baseline_run) for record in manifest.get("outputs", [])}
        for name in ("native_field_samples.csv", "native_potential_audit.csv"):
            path = baseline_run / "simion" / name
            if path.resolve() not in output_paths:
                raise ValueError(f"baseline field diagnostic is not a manifest-bound output: {name}")
            field_diagnostic_files.append(path)
        required.extend(field_diagnostic_files)
    for path in required:
        if path.resolve() not in verified:
            raise ValueError(f"baseline required input is not manifest-bound: {path}")
    inputs, solver = run / "inputs", run / "simion"
    inputs.mkdir(exist_ok=True)
    solver.mkdir(exist_ok=True)
    for source in family:
        target = solver / source.name
        shutil.copyfile(source, target)
        if file_sha256(target) != file_sha256(source):
            raise ValueError(f"native PA clone identity mismatch: {source.name}")
    # Recheck the source after cloning: a GUI workbench must never share PA handles.
    for index, source in enumerate(family):
        verify_record(f"post-clone baseline PA {index}", verified[source.resolve()], base_dir=baseline_run)
    for name in controls:
        shutil.copyfile(baseline_run / "simion" / name, solver / name)
    for path in field_diagnostic_files:
        shutil.copyfile(path, solver / path.name)
    for source in (baseline_run / "inputs").glob("*.json"):
        if source.resolve() not in verified:
            raise ValueError(f"unbound baseline input: {source}")
        shutil.copyfile(source, inputs / source.name)
    for source, target in ((manifest_path, "baseline_manifest.json"), (baseline_run / "summary.json", "baseline_summary.json"), (baseline_run / "simion/events.csv", "baseline_events.csv"), (baseline_run / "simion/samples.csv", "baseline_samples.csv"), (baseline_run / "results/particle_state.csv", "baseline_particle_state.csv")):
        shutil.copyfile(source, inputs / target)
    project = Path(__file__).resolve().parents[1]
    runtime = baseline_run / "simion/processor.lua"
    shutil.copyfile(runtime, solver / "processor.lua")
    if repeat_fly_count == 2:
        repeat_directory = json.dumps(str(solver.resolve()).replace("\\", "/").rstrip("/") + "/")
        orchestrator = "\n".join([
            "", "-- BEGIN_REPEAT_FLY_ORCHESTRATION: control flow only, no physics changes.",
            "local repeat_directory=" + repeat_directory,
            "local function snapshot_repeat(source_name,target_name)",
            " local input=assert(io.open(repeat_directory..source_name,'rb'))",
            " local output=assert(io.open(repeat_directory..target_name,'wb'))",
            " while true do local block=input:read(65536);if not block then break end;assert(output:write(block)) end",
            " assert(input:close());assert(output:close())", "end",
            "function segment.flym()",
            " for repeat_index=1,2 do",
            "  run() -- Official Fly'm sequencing; initialize_run resets each complete Fly.",
            "  snapshot_repeat('events.csv','repeat_'..repeat_index..'_events.csv')",
            "  snapshot_repeat('samples.csv','repeat_'..repeat_index..'_samples.csv')",
            "  print('ION_PROCESSOR_REPEAT_COMPLETE '..repeat_index)",
            " end", "end", "",
        ])
        with (solver / "processor.lua").open("a", encoding="utf-8") as stream:
            stream.write(orchestrator)
    seed = project.parents[1] / "common/simion/assets/iob_instance_seeds/1_instance_seed.iob"
    shutil.copyfile(seed, solver / "1_instance_seed.iob")
    config = _read(inputs / "resolved_model.json")
    from projects.dual_pressure_rectilinear_ion_processor.analysis.functional import lua_literal

    config.setdefault("native_field", {})["directory"] = str(solver.resolve())
    config["workbench_seed_path"] = str(seed.resolve())
    _write(inputs / "resolved_model.json", config)
    (solver / "frozen_config.lua").write_text("return " + lua_literal(config) + "\n", encoding="utf-8")
    builder_source = project / "simion/build_workbench.lua"
    shutil.copyfile(builder_source, solver / "build_gui_workbench.lua")
    baseline_runtime_record = verified[(baseline_run / "simion/processor.lua").resolve()]
    replay_runtime_record = file_record(solver / "processor.lua")
    runtime_wrapper_changed = baseline_runtime_record["sha256"].upper() != replay_runtime_record["sha256"].upper()
    wrapper_difference = (
        "baseline_exact_copy: runtime bytes identical to frozen baseline; no workspace runtime consumed"
        if not runtime_wrapper_changed else
        "baseline_exact_copy plus explicit repeat-Fly orchestration only; frozen runtime and drive/RF/source/HS1 preserved, no workspace runtime upgrade; repeated trajectory equivalence requires measured comparison"
    )
    plan = dict(schema_version=1, role="ion_processor_gui_replay_plan", repeat_fly_count=repeat_fly_count, repeat_orchestration="official_segment_flym_two_run_calls_with_complete_event_sample_snapshots" if repeat_fly_count == 2 else "single_Fly_default_unchanged", runtime_source_policy="baseline_exact_copy", field_diagnostics_policy="exact_copy_of_verified_baseline_outputs_no_new_field_solve" if field_diagnostic_files else "not_declared_by_baseline", field_diagnostics_source_records=[verified[path.resolve()] for path in field_diagnostic_files], baseline_run=str(baseline_run), source_profile=profile, baseline_evidence_scope=profile + "_baseline", baseline_manifest_sha256=file_sha256(manifest_path), baseline_events_record=file_record(inputs / "baseline_events.csv"), baseline_samples_record=file_record(inputs / "baseline_samples.csv"), baseline_particle_state_record=file_record(inputs / "baseline_particle_state.csv"), workbench_seed_record=file_record(seed), workbench_seed_placeholder_record=file_record(seed.parent / "iob_seed_placeholder_01.pa0"), initial_display_voltage_policy="clone baseline PA0 without builder Fast Adjust; runtime owns time-dependent voltages", native_pa_records=[verified[p.resolve()] for p in family], pa_policy="independent_full_family_clone_source_immutable_GUI_PA0_mutable_basis_immutable", local_native_pa_records=[file_record(solver / path.name) for path in family if path.name != "processor.pa0"], initial_local_pa0_record=file_record(solver / "processor.pa0"), builder_source_record=file_record(builder_source), workbench_save_policy="IOB save may persist associated GUI PA0; isolated clone protects source family; pa1..15 must remain byte-identical", baseline_runtime_record=baseline_runtime_record, replay_runtime_record=replay_runtime_record, runtime_wrapper_changed=runtime_wrapper_changed, wrapper_difference=wrapper_difference, gui_iob=str(solver / "processor.iob"), grouped=0, random_seed=config["numerics"]["seed"], trajectory_quality=config["numerics"]["trajectory_quality"], retain_trajectories=1, gui_manual_fly_completed=False)
    _write(inputs / "gui_replay_plan.json", plan)
    run_config = _read(run / "run_config.json")
    run_config.setdefault("inputs", {}).update({"baseline_manifest": str(manifest_path), "public_workbench_seed": str(seed), "public_seed_placeholder": str(seed.parent / "iob_seed_placeholder_01.pa0"), **{f"baseline_native_pa_{index}": str(path) for index, path in enumerate(family)}})
    for folder in (inputs, solver):
        run_config["inputs"].update({str(path.relative_to(run)).replace("/", "_"): str(path) for path in folder.iterdir() if path.is_file() and path != solver / "processor.pa0"})
    run_config["parameters"] = dict(workflow="native_gui_replay", baseline_run=str(baseline_run), source_profile=profile, baseline_evidence_scope=profile + "_baseline", baseline_manifest_sha256=plan["baseline_manifest_sha256"], runtime_wrapper_changed=runtime_wrapper_changed, repeat_fly_count=repeat_fly_count, manual_gui_confirmed=False)
    _write(run / "run_config.json", run_config)
    return plan


def _compare_tables(actual_path: Path, expected_path: Path) -> dict[str, Any]:
    with actual_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields, actual = reader.fieldnames, list(reader)
    with expected_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        expected_fields, expected = reader.fieldnames, list(reader)
    if fields != expected_fields or not fields or len(actual) != len(expected) or not actual:
        raise ValueError("replay table columns/row count differ or contain no evidence")
    identity = {"particle_id", "event", "status", "terminal_reason", "reason"}
    maximum = {field: 0.0 for field in fields if field not in identity}
    passed = True
    for left, right in zip(actual, expected):
        for field in fields:
            if field in identity:
                if left[field] != right[field]:
                    raise ValueError(f"replay identity/event order mismatch: {field}")
            else:
                a, b = float(left[field]), float(right[field])
                if not math.isfinite(a) or not math.isfinite(b):
                    raise ValueError("replay contains nonfinite numerical state")
                maximum[field] = max(maximum[field], abs(a-b))
                passed = passed and abs(a-b) <= ABS_TOL + REL_TOL * abs(b)
    return dict(passed=passed, rows=len(actual), max_absolute_difference=maximum, column_tolerances={field: dict(absolute=ABS_TOL, relative=REL_TOL, source="15-significant-digit serialization comparison; absolute plus relative times baseline magnitude") for field in maximum})


def finalize_replay(run: Path, manual_gui_confirmed: bool = False) -> dict:
    """Analyze Fly and compare every recorded event/sample and canonical row.

    Headless replay never proves manual visual review. Caller must explicitly
    confirm an actual manual GUI Fly; terminal manifest publication is external.
    """
    from projects.dual_pressure_rectilinear_ion_processor.analysis.functional import analyze

    run = run.resolve()
    plan = _read(run / "inputs/gui_replay_plan.json")
    baseline = Path(plan["baseline_run"])
    if file_sha256(baseline / "run_manifest.json") != plan["baseline_manifest_sha256"]:
        raise ValueError("baseline manifest identity changed")
    for index, record in enumerate(plan["native_pa_records"]):
        verify_record(f"replay native PA {index}", record, base_dir=baseline)
    for index, record in enumerate(plan["local_native_pa_records"]):
        verify_record(f"GUI immutable native basis/family {index}", record)
    current_pa0 = file_record(run / "simion/processor.pa0")
    pa0_changed = current_pa0["sha256"] != plan["initial_local_pa0_record"]["sha256"]
    verify_record("frozen baseline events", plan["baseline_events_record"])
    verify_record("frozen baseline samples", plan["baseline_samples_record"])
    verify_record("frozen baseline canonical states", plan["baseline_particle_state_record"])
    measured = analyze(run)
    profile = _read(run / "inputs/resolved_model.json").get("source_profile")
    if profile != plan.get("source_profile") or measured.get("source_profile") != profile:
        raise ValueError("replay source profile differs from frozen baseline")
    if not measured["status"].startswith(profile + "_"):
        raise ValueError("replay status would upgrade its frozen source profile")
    raw = _compare_tables(run / "simion/events.csv", run / "inputs/baseline_events.csv")
    samples = _compare_tables(run / "simion/samples.csv", run / "inputs/baseline_samples.csv")
    canonical = _compare_tables(run / "results/particle_state.csv", run / "inputs/baseline_particle_state.csv")
    repeats = []
    if plan["repeat_fly_count"] == 2:
        for index in (1, 2):
            repeats.append(dict(repeat_index=index,
                raw_events=_compare_tables(run / f"simion/repeat_{index}_events.csv", run / "inputs/baseline_events.csv"),
                sampled_trajectory=_compare_tables(run / f"simion/repeat_{index}_samples.csv", run / "inputs/baseline_samples.csv")))
    repeat_equivalence = all(row["raw_events"]["passed"] and row["sampled_trajectory"]["passed"] for row in repeats)
    result = dict(schema_version=1, role="ion_processor_gui_replay_comparison", comparison_scope="manual_gui_replay_vs_baseline" if manual_gui_confirmed else "headless_replay_vs_baseline", numerical_equivalence=raw["passed"] and canonical["passed"] and samples["passed"] and repeat_equivalence, repeat_fly_count=plan["repeat_fly_count"], repeated_fly_comparisons=repeats, gui_pa0_record=current_pa0, gui_pa0_changed=pa0_changed, source_native_family_verified=True, local_immutable_basis_verified=True, workbench_save_policy=plan["workbench_save_policy"], comparison_coverage="all_recorded_events_and_samples_not_every_integration_step", sampled_trajectory=samples, gui_visual_review=bool(manual_gui_confirmed), manual_gui_confirmed=bool(manual_gui_confirmed), source_profile=profile, qualification="unqualified_" + profile + "_replay_no_Candidate_or_Formal", measured_functional_status=measured["status"], raw_events=raw, canonical_particle_state=canonical, baseline_manifest_sha256=plan["baseline_manifest_sha256"])
    _write(run / "results/gui_comparison.json", result)
    return result
