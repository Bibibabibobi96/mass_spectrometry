"""Prepare isolated native-field replays and compare actual event/state evidence."""
from __future__ import annotations

import csv
import json
import math
import os
import stat
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


def validate_baseline_for_private_gui(baseline_run: Path) -> dict:
    """Verify a named light projection; never inspect native PA payload bytes."""
    baseline_run = baseline_run.resolve()
    manifest_path = baseline_run / "run_manifest.json"
    manifest = _read(manifest_path)
    if manifest.get("project") != PROJECT or manifest.get("status") not in {"success", "failed"}:
        raise ValueError("baseline must be a terminal Ion Processor run")
    receipt_path = baseline_run / "solver_review_retirement_receipt.json"
    retired = receipt_path.is_file()
    if retired:
        from common.contracts.solver_review_retirement import verify_retirement
        if verify_retirement(baseline_run).get("status") != "PASS":
            raise ValueError("baseline retirement verification failed")
    records = list(manifest.get("inputs", {}).values()) + list(manifest.get("outputs", []))
    if "run_config" not in manifest:
        raise ValueError("baseline manifest must bind its local run config")
    records.append(manifest["run_config"])
    config = _read(baseline_run / "inputs/resolved_model.json")
    summary = _read(baseline_run / "summary.json")
    functional_status = summary.get("functional_status", summary.get("status"))
    if summary.get("role") != "ion_processor_functional_summary" or functional_status not in {"functional_pass", "functional_incomplete", "exploration_pass", "exploration_incomplete"}:
        raise ValueError("baseline lacks measured physical summary")
    if "functional_status" in summary and summary.get("status") != manifest["status"]:
        raise ValueError("baseline canonical summary status differs from manifest")
    profile = config.get("source_profile")
    if profile not in {"functional", "exploration"} or summary.get("source_profile") != profile:
        raise ValueError("baseline source_profile must be frozen and match measured summary")
    if not functional_status.startswith(profile + "_"):
        raise ValueError("baseline status would upgrade or mislabel its frozen source profile")
    controls = ["frozen_config.lua", "collision_hs1.lua", "source_states.lua", "native_drive.lua", "simion_rf_drive.lua", "processor.fly2", "processor.gem", "build_workbench.lua"]
    field_diagnostics = (baseline_run / "inputs/field_diagnostics.json").is_file()
    if field_diagnostics:
        controls.append("probe_native_field.lua")
    required = [baseline_run / name for name in ("run_config.json", "summary.json", "logs/flight.log", "simion/events.csv", "simion/samples.csv", "results/particle_state.csv", "inputs/resolved_model.json")]
    required += [baseline_run / "simion" / name for name in [*controls, "processor.lua"]]
    required += [path for path in (baseline_run / "inputs").glob("*.json")
                 if path.name != "resource_budget.json"]
    verified = {}
    for path in dict.fromkeys(p.resolve() for p in required):
        matches = [r for r in records if record_path(r, base_dir=baseline_run) == path]
        if not matches:
            raise ValueError(f"baseline required input is not manifest-bound: {path}")
        for record in matches:
            verify_record("GUI light consumer projection", record, base_dir=baseline_run)
        verified[path] = matches[0]
    if record_path(manifest["run_config"], base_dir=baseline_run) != baseline_run / "run_config.json":
        raise ValueError("baseline must bind the local run config")
    if "ION_PROCESSOR_END" not in (baseline_run / "logs/flight.log").read_text(encoding="utf-8-sig"):
        raise ValueError("baseline Fly completion sentinel is missing")
    ids = config["native_projection"]["electrode_ids"]
    if not ids or any(isinstance(i, bool) or not isinstance(i, int) or i < 1 for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("frozen native electrode namespace is invalid")
    names = ["processor.pa#", "processor.pa0", *["processor.pa" + str(i) for i in ids], "processor.pa-surf"]
    historical = [r for r in records if Path(r["path"]).name in names]
    return dict(manifest=manifest, verified=verified, config=config, summary=summary, profile=profile,
                controls=controls, expected_native_members=names, historical_native_records=historical,
                field_diagnostics_enabled=field_diagnostics, retired=retired, retirement_record=file_record(receipt_path) if retired else None)


def prepare_replay(run: Path, baseline_run: Path, repeat_fly_count: int = 1) -> dict:
    """Prepare a private Refine from a verified light source, including retired runs."""
    if isinstance(repeat_fly_count, bool) or not isinstance(repeat_fly_count, int) or repeat_fly_count not in (1, 2):
        raise ValueError("repeat_fly_count must be 1 or 2")
    run, baseline_run = run.resolve(), baseline_run.resolve()
    if run == baseline_run or baseline_run in run.parents or run in baseline_run.parents:
        raise ValueError("GUI replay must use a separate, nonoverlapping run")
    projection = validate_baseline_for_private_gui(baseline_run)
    manifest_path = baseline_run / "run_manifest.json"
    verified, profile, controls = (projection[key] for key in ("verified", "profile", "controls"))
    # No field table is cloned. After a fresh private query, the recording step
    # compares manifest-bound baseline CSVs without opening baseline PA payloads.
    field_diagnostic_files = []
    inputs, solver = run / "inputs", run / "simion"
    inputs.mkdir(exist_ok=True)
    solver.mkdir(exist_ok=True)
    # The raw baseline family is never passed to a vendor process or copied.
    # Only a new GEM->Refine build may create this GUI run's private family.
    for name in controls:
        shutil.copyfile(baseline_run / "simion" / name, solver / name)
    for source in (baseline_run / "inputs").glob("*.json"):
        if source.name == "resource_budget.json":
            continue
        if source.resolve() not in verified:
            raise ValueError(f"unbound baseline input: {source}")
        shutil.copyfile(source, inputs / source.name)
    for source, target in ((manifest_path, "baseline_manifest.json"), (baseline_run / "summary.json", "baseline_summary.json"), (baseline_run / "simion/events.csv", "baseline_events.csv"), (baseline_run / "results/particle_state.csv", "baseline_particle_state.csv")):
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
    if "native_timing" in config and _read(inputs / "native_timing.json") != config["native_timing"]:
        raise ValueError("GUI frozen native timing JSON differs from baseline resolved timing")
    from projects.dual_pressure_rectilinear_ion_processor.analysis.functional import lua_literal

    config["native_field"] = {"directory": str(solver.resolve()), "source_manifest": None, "construction_policy": "new_private_refine_from_frozen_GEM"}
    config["workbench_seed_path"] = str(seed.resolve())
    _write(inputs / "resolved_model.json", config)
    (solver / "frozen_config.lua").write_text("return " + lua_literal(config) + "\n", encoding="utf-8")
    builder_source = baseline_run / "simion/build_workbench.lua"
    shutil.copyfile(builder_source, solver / "build_gui_workbench.lua")
    baseline_runtime_record = verified[(baseline_run / "simion/processor.lua").resolve()]
    baseline_samples = (baseline_run / "simion/samples.csv").resolve()
    baseline_samples_record = {**verified[baseline_samples], "path": str(baseline_samples)}
    replay_runtime_record = file_record(solver / "processor.lua")
    runtime_wrapper_changed = baseline_runtime_record["sha256"].upper() != replay_runtime_record["sha256"].upper()
    wrapper_difference = (
        "baseline_exact_copy: runtime bytes identical to frozen baseline; no workspace runtime consumed"
        if not runtime_wrapper_changed else
        "baseline_exact_copy plus explicit repeat-Fly orchestration only; frozen runtime and drive/RF/source/HS1 preserved, no workspace runtime upgrade; repeated trajectory equivalence requires measured comparison"
    )
    plan = dict(schema_version=1, role="ion_processor_gui_replay_plan", repeat_fly_count=repeat_fly_count, repeat_orchestration="official_segment_flym_two_run_calls_with_complete_event_sample_snapshots" if repeat_fly_count == 2 else "single_Fly_default_unchanged", runtime_source_policy="baseline_exact_copy", field_diagnostics_policy="query_new_private_field_using_frozen_probe" if projection["field_diagnostics_enabled"] else "not_declared_by_baseline", field_diagnostics_source_records=[verified[path.resolve()] for path in field_diagnostic_files], baseline_run=str(baseline_run), source_profile=profile, baseline_evidence_scope=profile + "_baseline", baseline_manifest_sha256=file_sha256(manifest_path), baseline_events_record=file_record(inputs / "baseline_events.csv"), baseline_samples_record=baseline_samples_record, baseline_trajectory_storage="verified_immutable_source_reference", baseline_particle_state_record=file_record(inputs / "baseline_particle_state.csv"), workbench_seed_record=file_record(seed), workbench_seed_placeholder_record=file_record(seed.parent / "iob_seed_placeholder_01.pa0"), initial_display_voltage_policy="new private Refine; no builder Fast Adjust; runtime owns time-dependent voltages", native_pa_records=projection["historical_native_records"], baseline_consumer_projection_id="ion_processor_gui_private_refine_light_v1", baseline_retirement_verified=projection["retired"], baseline_retirement_record=projection["retirement_record"], source_PA_bytes_consumed=False, baseline_consumed_records=list(verified.values()), field_diagnostics_enabled=projection["field_diagnostics_enabled"], pa_policy="new_private_refine_from_frozen_GEM_no_baseline_PA_clone", construction_status="inputs_prepared_no_field_or_IOB_yet", geometry_record=file_record(solver / "processor.gem"), frozen_control_records=[file_record(solver / name) for name in sorted(set(controls + ["processor.lua", "build_gui_workbench.lua"]))], expected_native_members=projection["expected_native_members"], local_native_pa_records=[], initial_local_pa0_record=None, builder_source_record=file_record(builder_source), workbench_save_policy="IOB save may persist associated private GUI PA0; no baseline native PA is vendor-opened; private numbered responses remain byte-identical", baseline_runtime_record=baseline_runtime_record, replay_runtime_record=replay_runtime_record, runtime_wrapper_changed=runtime_wrapper_changed, wrapper_difference=wrapper_difference, gui_iob=str(solver / "processor.iob"), grouped=0, random_seed=config["numerics"]["seed"], trajectory_quality=config["numerics"]["trajectory_quality"], retain_trajectories=1, gui_manual_fly_completed=False)
    _write(inputs / "gui_replay_plan.json", plan)
    run_config = _read(run / "run_config.json")
    run_config.setdefault("inputs", {}).update({"baseline_manifest": str(manifest_path), "public_workbench_seed": str(seed), "public_seed_placeholder": str(seed.parent / "iob_seed_placeholder_01.pa0"), **{f"baseline_light_{index}": str(path) for index, path in enumerate(verified)}})
    run_config["inputs"]["baseline_samples"] = str(baseline_samples)
    if projection["retired"]:
        shutil.copyfile(baseline_run / "solver_review_retirement_receipt.json", inputs / "baseline_retirement_receipt.json")
        run_config["inputs"]["baseline_retirement_receipt"] = str(baseline_run / "solver_review_retirement_receipt.json")
    for folder in (inputs, solver):
        run_config["inputs"].update({str(path.relative_to(run)).replace("/", "_"): str(path) for path in folder.iterdir() if path.is_file() and path != solver / "processor.pa0"})
    run_config["parameters"] = dict(workflow="native_gui_replay", baseline_run=str(baseline_run), source_profile=profile, baseline_evidence_scope=profile + "_baseline", baseline_manifest_sha256=plan["baseline_manifest_sha256"], runtime_wrapper_changed=runtime_wrapper_changed, repeat_fly_count=repeat_fly_count, manual_gui_confirmed=False)
    _write(run / "run_config.json", run_config)
    return plan



def record_prepared_native_family(run: Path) -> dict:
    """Seal evidence after real private Refine/query/IOB build, never Fly."""
    run = run.resolve()
    inputs, solver = run / "inputs", run / "simion"
    plan = _read(inputs / "gui_replay_plan.json")
    if plan.get("pa_policy") != "new_private_refine_from_frozen_GEM_no_baseline_PA_clone":
        raise ValueError("GUI preparation requires new private Refine policy")
    verify_record("frozen GUI GEM", plan["geometry_record"])
    for index, record in enumerate(plan["frozen_control_records"]):
        verify_record(f"frozen GUI control {index}", record)
    if "Fast adjust Refining completed" not in (run / "logs/refine.log").read_text(encoding="utf-8-sig"):
        raise ValueError("private GUI field lacks completed Refine evidence")
    if "ION_PROCESSOR_WORKBENCH=PASS" not in (run / "logs/workbench.log").read_text(encoding="utf-8-sig"):
        raise ValueError("private GUI IOB lacks native pose/build evidence")
    if not (solver / "processor.iob").is_file():
        raise ValueError("private GUI IOB is missing")
    names = plan["expected_native_members"]
    if (not names or len(set(names)) != len(names)
            or any(Path(name).name != name for name in names)):
        raise ValueError("private GUI family members must be unique direct filenames")
    family = [solver / name for name in names]
    if any(not path.is_file() for path in family):
        raise ValueError("private GUI native family is incomplete, including fractional surface")
    # Only fresh files owned by this build may be flushed. Refuse junctions,
    # symlinks and hard-linked aliases before opening ANY member for writing.
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if solver.resolve() != solver or solver.is_symlink() or getattr(solver.lstat(), "st_file_attributes", 0) & reparse:
        raise ValueError("private GUI solver directory must not be an alias")
    for path in family:
        info = path.lstat()
        if (path.resolve().parent != solver or path.is_symlink()
                or getattr(info, "st_file_attributes", 0) & reparse
                or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise ValueError("private GUI family member must not alias an external source")
    # Vendor processes have exited. Commit this new writable producer family
    # before file_record's unbuffered large-file reads; never flush baseline PA.
    for path in family:
        with path.open("r+b", buffering=0) as handle:
            handle.flush()
            os.fsync(handle.fileno())
    if plan.get("field_diagnostics_enabled", bool(plan["field_diagnostics_source_records"])):
        for name in ("native_field_samples.csv", "native_potential_audit.csv"):
            if not (solver / name).is_file():
                raise ValueError("new private field diagnostic is missing")
    comparison = _record_native_field_preparation_comparison(run, plan)
    plan["native_field_preparation_comparison_record"] = file_record(run / "results/native_field_preparation_comparison.json")
    plan["local_native_pa_records"] = [file_record(path) for path in family if path.name != "processor.pa0"]
    plan["initial_local_pa0_record"] = file_record(solver / "processor.pa0")
    plan["private_iob_record"] = file_record(solver / "processor.iob")
    plan["construction_status"] = "private_refine_and_native_IOB_prepared_not_flown"
    plan["trajectory_equivalence_verified"] = False
    _write(inputs / "gui_replay_plan.json", plan)
    config = _read(run / "run_config.json")
    for path in family:
        if path.name != "processor.pa0":
            config.setdefault("inputs", {})["private_native_" + path.name] = str(path)
    if plan.get("field_diagnostics_enabled", bool(plan["field_diagnostics_source_records"])):
        for name in ("native_field_samples.csv", "native_potential_audit.csv"):
            path = solver / name
            if not path.is_file():
                raise ValueError("new private field diagnostic is missing")
            config["inputs"]["private_" + name] = str(path)
        for name, table in comparison["tables"].items():
            config["inputs"]["baseline_" + name] = table["baseline"]["path"]
    config["parameters"]["native_field_construction"] = plan["construction_status"]
    _write(run / "run_config.json", config)
    return plan


def _compare_tables(actual_path: Path, expected_path: Path, *, identity_fields: set[str] | None = None) -> dict[str, Any]:
    with actual_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields, actual = reader.fieldnames, list(reader)
    with expected_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        expected_fields, expected = reader.fieldnames, list(reader)
    if fields != expected_fields or not fields or len(actual) != len(expected) or not actual:
        raise ValueError("replay table columns/row count differ or contain no evidence")
    identity = {"particle_id", "event", "status", "terminal_reason", "reason"} | (identity_fields or set())
    maximum = {field: 0.0 for field in fields if field not in identity}
    passed = True
    for left, right in zip(actual, expected):
        for field in fields:
            if field in identity:
                if field in {"t_us", "x_mm", "y_mm", "z_mm", "electrode"}:
                    if not all(math.isfinite(float(value)) for value in (left[field], right[field])):
                        raise ValueError("replay contains nonfinite numerical sample identity")
                if left[field] != right[field]:
                    raise ValueError(f"replay identity/event order mismatch: {field}")
            else:
                a, b = float(left[field]), float(right[field])
                if not math.isfinite(a) or not math.isfinite(b):
                    raise ValueError("replay contains nonfinite numerical state")
                maximum[field] = max(maximum[field], abs(a-b))
                passed = passed and abs(a-b) <= ABS_TOL + REL_TOL * abs(b)
    return dict(passed=passed, rows=len(actual), max_absolute_difference=maximum, column_tolerances={field: dict(absolute=ABS_TOL, relative=REL_TOL, source="15-significant-digit serialization comparison; absolute plus relative times baseline magnitude") for field in maximum})


def _record_native_field_preparation_comparison(run: Path, plan: dict) -> dict:
    """Report only corresponding sampled native fields, never a Fly/GUI claim."""
    result = dict(schema_version=1, role="ion_processor_native_field_preparation_comparison",
                  comparison_scope="new_private_refine_samples_vs_manifest_bound_baseline_samples",
                  numerical_differences_are_diagnostic_only=True, solver_fly_executed=False,
                  gui_operated=False, gui_visual_review=False, trajectory_equivalence_verified=False,
                  qualification="sampled_field_preparation_only_no_Candidate_or_Formal", tables={})
    if not plan.get("field_diagnostics_enabled", bool(plan["field_diagnostics_source_records"])):
        result["status"] = "not_declared_by_baseline"
    else:
        baseline = Path(plan["baseline_run"])
        manifest_path = baseline / "run_manifest.json"
        if file_sha256(manifest_path) != plan["baseline_manifest_sha256"]:
            raise ValueError("baseline manifest identity changed during private field preparation")
        manifest = _read(manifest_path)
        if manifest.get("project") != PROJECT or manifest.get("status") not in {"success", "failed"}:
            raise ValueError("native field comparison requires a terminal IP baseline manifest")
        records = [*manifest.get("inputs", {}).values(), *manifest.get("outputs", [])]
        headers = {
            "native_field_samples.csv": ["stage_id", "section_id", "sample_kind", "t_us", "x_mm", "y_mm", "z_mm", "potential_v", "ex_v_per_mm", "ey_v_per_mm", "ez_v_per_mm", "electrode"],
            "native_potential_audit.csv": ["t_us", "x_mm", "y_mm", "z_mm", "potential_v"],
        }
        for name, columns in headers.items():
            expected = baseline / "simion" / name
            actual = run / "simion" / name
            matches = [record for record in records if record_path(record, base_dir=baseline) == expected.resolve()]
            if not matches:
                raise ValueError(f"baseline field diagnostic is not manifest-bound: {name}")
            for record in matches:
                verify_record("baseline native field comparison", record, base_dir=baseline)
            for path in (expected, actual):
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    if csv.DictReader(stream).fieldnames != columns:
                        raise ValueError(f"native field diagnostic columns differ: {path}")
            comparison = _compare_tables(actual, expected, identity_fields={
                "stage_id", "section_id", "sample_kind", "t_us", "x_mm", "y_mm", "z_mm"})
            result["tables"][name] = dict(baseline=file_record(expected), prepared=file_record(actual), **comparison)
        result.update(status="compared", baseline_manifest_record=file_record(manifest_path),
                      all_sampled_values_within_existing_comparison_tolerances=all(
                          row["passed"] for row in result["tables"].values()))
    (run / "results").mkdir(exist_ok=True)
    _write(run / "results/native_field_preparation_comparison.json", result)
    return result


def _verify_active_gui_receipts(run: Path, config: dict) -> dict:
    """Validate actual full-cohort and HS1 receipts for the new declared policy."""
    n = config["numerics"]
    if n.get("collision_rng_policy") != "per_global_particle_seed_v1":
        return dict(verified=False, scope="legacy_policy_no_new_HS1_binding_claim")
    def rows(name):
        with (run / "simion" / name).open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))
    expected_ids = list(range(1, config["source"]["particle_count"] + 1))
    events = rows("events.csv")
    for event in ("source", "terminal"):
        if sorted(int(r["particle_id"]) for r in events if r["event"] == event) != expected_ids:
            raise ValueError("GUI full source/terminal cohort does not close")
    seeds = rows("collision_rng_seeds.csv")
    if [int(r["particle_id"]) for r in seeds] != expected_ids or any(
        int(r["global_particle_id"]) != int(r["particle_id"])
        or int(r["seed"]) != n["seed"] + int(r["particle_id"]) - 1 for r in seeds
    ):
        raise ValueError("GUI RNG receipt does not cover the full master cohort")
    gas = config["baseline"]["gas"]
    expected = dict(gas_mass_amu=gas["mass_amu"], temperature_k=gas["temperature_k"], pressure_pa=0,
                    sigma_m2=gas["cross_section_m2"], mean_free_path_mm=gas["mean_free_path_mm"],
                    steps_per_mfp=n["hs1_steps_per_mfp"], random_seed=n["seed"]+1, mark_collisions=0, trace_level=0)
    audit = rows("hs1_bound_parameters.csv")
    if len(audit) != 2 or {r["phase"] for r in audit} != {"before_init", "after_init"} or any(
        float(r[key]) != value for r in audit for key, value in expected.items()
    ):
        raise ValueError("GUI HS1 binding audit differs from frozen authority")
    return dict(verified=True, source_count=len(expected_ids), terminal_count=len(expected_ids),
                seed_receipt_verified=True, hs1_binding_verified=True,
                pressure_semantics="zero fallback; frozen runtime pressure callback supplies HP/LP gas")


def finalize_replay(run: Path, manual_gui_confirmed: bool = False) -> dict:
    """Analyze Fly and compare every recorded event/sample and canonical row.

    Headless replay never proves manual visual review. Caller must explicitly
    confirm an actual manual GUI Fly; terminal manifest publication is external.
    """
    from projects.dual_pressure_rectilinear_ion_processor.analysis.functional import analyze

    run = run.resolve()
    plan = _read(run / "inputs/gui_replay_plan.json")
    if plan.get("pa_policy") == "new_private_refine_from_frozen_GEM_no_baseline_PA_clone" and plan.get("construction_status") != "private_refine_and_native_IOB_prepared_not_flown":
        raise ValueError("private GUI Refine/IOB preparation is not sealed")
    baseline = Path(plan["baseline_run"])
    if file_sha256(baseline / "run_manifest.json") != plan["baseline_manifest_sha256"]:
        raise ValueError("baseline manifest identity changed")
    validate_baseline_for_private_gui(baseline)
    if plan.get("baseline_retirement_record"):
        verify_record("baseline completed retirement receipt", plan["baseline_retirement_record"])
    for index, record in enumerate(plan["local_native_pa_records"]):
        verify_record(f"GUI immutable native basis/family {index}", record)
    current_pa0 = file_record(run / "simion/processor.pa0")
    pa0_changed = current_pa0["sha256"] != plan["initial_local_pa0_record"]["sha256"]
    verify_record("frozen baseline events", plan["baseline_events_record"], base_dir=run)
    verify_record("frozen baseline samples", plan["baseline_samples_record"], base_dir=run)
    verify_record("frozen baseline canonical states", plan["baseline_particle_state_record"], base_dir=run)
    expected_events = record_path(plan["baseline_events_record"], base_dir=run)
    expected_samples = record_path(plan["baseline_samples_record"], base_dir=run)
    expected_states = record_path(plan["baseline_particle_state_record"], base_dir=run)
    native_receipts = _verify_active_gui_receipts(run, _read(run / "inputs/resolved_model.json"))
    measured = analyze(run)
    profile = _read(run / "inputs/resolved_model.json").get("source_profile")
    if profile != plan.get("source_profile") or measured.get("source_profile") != profile:
        raise ValueError("replay source profile differs from frozen baseline")
    measured_status = measured.get("functional_status", measured["status"])
    if not measured_status.startswith(profile + "_"):
        raise ValueError("replay status would upgrade its frozen source profile")
    def compare_recorded(actual, expected):
        try:
            return _compare_tables(actual, expected)
        except ValueError as exc:
            return dict(passed=False, difference=str(exc))
    raw = compare_recorded(run / "simion/events.csv", expected_events)
    samples = compare_recorded(run / "simion/samples.csv", expected_samples)
    canonical = compare_recorded(run / "results/particle_state.csv", expected_states)
    repeats = []
    if plan["repeat_fly_count"] == 2:
        for index in (1, 2):
            repeats.append(dict(repeat_index=index,
                raw_events=compare_recorded(run / f"simion/repeat_{index}_events.csv", expected_events),
                sampled_trajectory=compare_recorded(run / f"simion/repeat_{index}_samples.csv", expected_samples)))
    repeat_equivalence = all(row["raw_events"]["passed"] and row["sampled_trajectory"]["passed"] for row in repeats)
    result = dict(schema_version=1, role="ion_processor_gui_replay_comparison", comparison_scope="manual_gui_replay_vs_baseline" if manual_gui_confirmed else "headless_replay_vs_baseline", numerical_equivalence=raw["passed"] and canonical["passed"] and samples["passed"] and repeat_equivalence, repeat_fly_count=plan["repeat_fly_count"], repeated_fly_comparisons=repeats, gui_pa0_record=current_pa0, gui_pa0_changed=pa0_changed, source_native_family_verified=False, source_PA_bytes_consumed=False, baseline_light_projection_verified=True, native_receipts=native_receipts, exact_trajectory_match_required=False, local_immutable_basis_verified=True, workbench_save_policy=plan["workbench_save_policy"], comparison_coverage="all_recorded_events_and_samples_not_every_integration_step", sampled_trajectory=samples, gui_visual_review=bool(manual_gui_confirmed), manual_gui_confirmed=bool(manual_gui_confirmed), source_profile=profile, qualification="unqualified_" + profile + "_replay_no_Candidate_or_Formal", measured_functional_status=measured_status, raw_events=raw, canonical_particle_state=canonical, baseline_manifest_sha256=plan["baseline_manifest_sha256"])
    _write(run / "results/gui_comparison.json", result)
    return result
