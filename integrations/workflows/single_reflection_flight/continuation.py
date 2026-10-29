"""Adapt the single-reflection workbench to common whole-batch continuation.

The workbench remains the only scientific input projection. This adapter freezes
only the predecessor dispatch and workbench receipt, then delegates complete
batch reuse/replay selection to the shared SIMION planner.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import shutil
from typing import Any, Mapping

from common.contracts.verify_run_manifest import record_path, verify_record
from common.contracts.write_run_manifest import file_record
from common.simion.batch_continuation import WholeUnitReplayUnit, build_whole_unit_replay_plan
from common.simion.particle_batching import batch_plan_from_dispatch
from integrations.runtime.single_flight_source import GLOBAL_COLUMNS
from integrations.workflows.single_reflection_flight.census import read_native_evidence


def _read(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is unreadable") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _identity(record: Mapping[str, Any], label: str) -> tuple[int, str]:
    size, digest = record.get("bytes"), record.get("sha256")
    if type(size) is not int or size < 0 or not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f"{label} identity is invalid")
    return size, digest.upper()


def _same_identity(current: Mapping[str, Any], parent: Mapping[str, Any], label: str) -> None:
    if _identity(current, f"current {label}") != _identity(parent, f"parent {label}"):
        raise ValueError(f"single-reflection continuation {label} differs")


def _manifest_records(manifest: Mapping[str, Any]) -> dict[Path, tuple[int, str]]:
    inputs, outputs = manifest.get("inputs"), manifest.get("outputs")
    if not isinstance(inputs, dict) or not isinstance(outputs, list):
        raise ValueError("single-reflection continuation parent manifest records are invalid")
    records: dict[Path, tuple[int, str]] = {}
    for record in [*inputs.values(), *outputs]:
        if not isinstance(record, Mapping):
            raise ValueError("single-reflection continuation parent manifest record is invalid")
        path = record_path(dict(record)).resolve()
        identity = _identity(record, "parent manifest")
        previous = records.setdefault(path, identity)
        if previous != identity:
            raise ValueError("single-reflection continuation parent manifest has conflicting records")
    return records


def _bound_parent_file(path: Path, records: Mapping[Path, tuple[int, str]], label: str) -> None:
    record = records.get(path.resolve())
    if record is None:
        raise ValueError(f"single-reflection continuation {label} is not uniquely manifest-bound")
    try:
        verify_record(label, {"path": str(path), "exists": True, "bytes": record[0], "sha256": record[1]})
    except AssertionError as error:
        raise ValueError(f"single-reflection continuation {label} differs") from error


def _parent(preparation: Mapping[str, Any]) -> tuple[Path, dict[str, Any], dict[Path, tuple[int, str]], dict[str, Any]]:
    record = preparation.get("input_records", {}).get("continuation_parent_manifest")
    if not isinstance(record, dict) or not isinstance(record.get("source_path"), str):
        raise ValueError("single-reflection continuation requires a frozen parent manifest")
    try:
        verify_record("frozen continuation parent manifest", record)
    except AssertionError as error:
        raise ValueError("single-reflection continuation frozen parent manifest differs") from error
    parent_manifest = Path(record["source_path"]).resolve()
    if parent_manifest.name != "run_manifest.json" or not parent_manifest.is_file():
        raise ValueError("single-reflection continuation parent manifest source path is invalid")
    if _identity(file_record(parent_manifest), "parent manifest") != _identity(record, "frozen parent manifest"):
        raise ValueError("single-reflection continuation parent manifest differs from its frozen input")
    manifest = _read(record_path(record), "frozen continuation parent manifest")
    return parent_manifest.parent, manifest, _manifest_records(manifest), record


def _phase_paths(parent: Path, phase: str) -> tuple[Path, Path, str]:
    if phase == "discovery":
        return (parent / "results" / "discovery.dispatch_plan.json",
                parent / "results" / "single_reflection" / "discovery_workbench_preparation.json", "discovery")
    if phase in {"baseline", "default_replay"}:
        return (parent / "results" / "full_instrument.dispatch_plan.json",
                parent / "results" / "single_reflection" / "workbench_preparation.json", "full_instrument")
    raise ValueError("single-reflection continuation phase is invalid")


def freeze_phase_inputs(preparation: Mapping[str, Any], run: Path, phase: str) -> dict[str, Any] | None:
    """Freeze the two small, manifest-bound predecessor receipts for ``phase``."""
    parent, manifest, records, parent_manifest_record = _parent(preparation)
    dispatch, workbench, _ = _phase_paths(parent, phase)
    if dispatch.resolve() not in records and workbench.resolve() not in records:
        if dispatch.exists() or workbench.exists():
            raise ValueError("single-reflection continuation phase has unpublished predecessor receipts")
        return None
    _bound_parent_file(dispatch, records, "final dispatch")
    _bound_parent_file(workbench, records, "workbench receipt")
    destination = run / "inputs" / "continuation" / phase
    if destination.exists():
        raise ValueError("single-reflection continuation phase inputs already exist")
    destination.mkdir(parents=True)
    frozen_dispatch, frozen_workbench = destination / dispatch.name, destination / workbench.name
    shutil.copyfile(dispatch, frozen_dispatch)
    shutil.copyfile(workbench, frozen_workbench)
    return {"parent_run_dir": str(parent), "parent_manifest_record": parent_manifest_record,
            "dispatch_record": {**file_record(frozen_dispatch), "source_path": str(dispatch)},
            "workbench_record": {**file_record(frozen_workbench), "source_path": str(workbench)},
            "parent_manifest_run_id": manifest.get("run_id")}


def _source_ids(record: Mapping[str, Any]) -> list[int]:
    try:
        verify_record("current projected source", dict(record))
        with record_path(dict(record)).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != tuple(GLOBAL_COLUMNS):
                raise ValueError("projected source columns differ")
            ids = [int(row["particle_id"]) for row in reader]
    except (AssertionError, OSError, UnicodeError, KeyError, ValueError) as error:
        raise ValueError("single-reflection continuation projected source is invalid") from error
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("single-reflection continuation projected source IDs differ")
    return ids


def _fixed_batches(dispatch: Mapping[str, Any], source_ids: list[int]) -> list[dict[str, Any]]:
    plan = batch_plan_from_dispatch(dict(dispatch)) if dispatch.get("role") == "simion_repository_dispatch_plan" else dict(dispatch)
    if plan.get("role") != "simion_single_wave_particle_batch_plan" or plan.get("coverage") != "complete_population":
        raise ValueError("single-reflection continuation requires a published final complete dispatch")
    batches = plan.get("batches")
    if plan.get("particle_count") != len(source_ids) or not isinstance(batches, list) or not batches:
        raise ValueError("single-reflection continuation final dispatch population differs")
    seen: list[int] = []
    result: list[dict[str, Any]] = []
    for index, batch in enumerate(batches, 1):
        if not isinstance(batch, dict):
            raise ValueError("single-reflection continuation final dispatch batch is invalid")
        low, high, count = (batch.get(name) for name in ("particle_id_min", "particle_id_max", "count"))
        if (any(type(value) is not int for value in (low, high, count)) or batch.get("index") != index
                or low < 1 or high < low or count != high - low + 1):
            raise ValueError("single-reflection continuation final dispatch interval differs")
        seen.extend(range(low, high + 1))
        result.append({"index": index, "low": low, "high": high,
                       "key": f"batch_{index:04d}__rows_{low:06d}_{high:06d}"})
    if seen != list(range(1, len(source_ids) + 1)):
        raise ValueError("single-reflection continuation final dispatch does not preserve original source rows")
    return result


def _cases(workbench: Mapping[str, Any], batches: list[dict[str, Any]], source_ids: list[int]) -> dict[tuple[int, int], dict[str, Any]]:
    values = workbench.get("batches")
    if not isinstance(values, list):
        raise ValueError("single-reflection continuation workbench batches differ")
    cases = {tuple(case.get("source_row_range", ())): case for case in values if isinstance(case, dict)}
    if len(cases) != len(batches):
        raise ValueError("single-reflection continuation workbench batches differ")
    for batch in batches:
        low, high = batch["low"], batch["high"]
        case = cases.get((low, high))
        if case is None or case.get("expected_particle_ids") != source_ids[low - 1:high]:
            raise ValueError("single-reflection continuation source-row binding differs")
    return cases


def _records_match(left: list[Mapping[str, Any]], right: list[Mapping[str, Any]], label: str) -> None:
    if [_identity(item, label) for item in left] != [_identity(item, label) for item in right]:
        raise ValueError(f"single-reflection continuation {label} differs")


def _verified_text(record: Mapping[str, Any], label: str) -> str:
    try:
        verify_record(label, dict(record))
        return record_path(dict(record)).read_text(encoding="utf-8-sig")
    except (AssertionError, OSError, UnicodeError) as error:
        raise ValueError(f"single-reflection continuation {label} differs") from error


def _normalized_build_text(text: str, run_root: Path, lexical_root: Path,
                           guards: list[Mapping[str, Any]], copies: list[Mapping[str, Any]] = ()) -> str:
    """Compare field content identities independently of owner/short-path spellings."""
    root = run_root.resolve()
    for index, guard in enumerate(guards):
        path = record_path(dict(guard))
        candidates = [path]
        for copy in copies:
            if record_path(dict(copy["source_record"])) == path:
                _same_identity(copy["source_record"], guard, "IOB PA transport source")
                destination = Path(copy["destination"])
                candidates.extend([destination, destination.resolve()])
        if path.is_relative_to(root):
            candidates.append(lexical_root / path.relative_to(root))
        for candidate in candidates:
            text = text.replace(candidate.as_posix(), f"<PA_{index}>").replace(str(candidate), f"<PA_{index}>")
    for candidate in (root, lexical_root):
        text = text.replace(candidate.as_posix(), "<RUN_ROOT>").replace(str(candidate), "<RUN_ROOT>")
    return text


def _normalized_program_text(text: str, guards: list[Mapping[str, Any]]) -> str:
    """Normalize only exact PA path literals bound to frozen field records."""
    for index, guard in enumerate(guards):
        path = record_path(dict(guard))
        for spelling in {str(path), path.as_posix()}:
            text = text.replace(json.dumps(spelling, ensure_ascii=True),
                                json.dumps(f"<PA_{index}>"))
    return text


def _builder_identity(case: Mapping[str, Any], label: str) -> tuple[int, str]:
    arguments = case.get("iob_builder_arguments")
    if not isinstance(arguments, list) or len(arguments) < 4 or not isinstance(arguments[3], str):
        raise ValueError(f"single-reflection continuation {label} builder is missing")
    return _identity(file_record(Path(arguments[3])), f"{label} builder")


def _published_case(case: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve saved execution aliases through canonical published control records."""
    result = dict(case)
    spec = record_path(case["outputs"]["build_spec"])
    # Batch layout is fixed by this adapter. Its canonical control record can
    # belong to an earlier owner explicitly rebound by the direct parent.
    artifact_owner = spec.parents[3]
    relative_spec = spec.relative_to(artifact_owner)
    old_root = Path(case["iob_path"])
    for _ in relative_spec.parts:
        old_root = old_root.parent
    old_root = Path(case.get("parent_execution_root", old_root))
    result["parent_execution_root"] = str(old_root)
    for name in ("stdout", "stderr", "replay_stdout", "replay_stderr"):
        if isinstance(case.get(name), str):
            path = Path(case[name])
            if path.is_relative_to(old_root):
                result[name] = str(artifact_owner / path.relative_to(old_root))
    if "iob" in case["outputs"]:
        iob = record_path(case["outputs"]["iob"])
        result.update(iob_path=str(iob), working_directory=str(iob.parent))
    arguments = list(case["iob_builder_arguments"])
    builder = Path(arguments[3])
    if not builder.is_file() and builder.is_relative_to(old_root):
        arguments[3] = str(artifact_owner / builder.relative_to(old_root))
    result["iob_builder_arguments"] = arguments
    return result


def prepare_phase_continuation(preparation: Mapping[str, Any], current_workbench: Mapping[str, Any], run: Path, phase: str) -> dict[str, Any] | None:
    """Plan whole-batch reuse/replay directly from current and parent workbenches."""
    if preparation.get("role") != "single_reflection_geometry_preparation":
        raise ValueError("current single-reflection preparation receipt is required")
    frozen = freeze_phase_inputs(preparation, run, phase)
    if frozen is None:
        return None
    parent = Path(frozen["parent_run_dir"])
    _, _, expected_workbench_phase = _phase_paths(parent, phase)
    parent_dispatch = _read(record_path(frozen["dispatch_record"]), "frozen final dispatch")
    parent_workbench = _read(record_path(frozen["workbench_record"]), "frozen workbench receipt")
    parent_workbench["batches"] = [_published_case(case) for case in parent_workbench["batches"]]
    if current_workbench.get("role") != "single_reflection_workbench_preparation":
        raise ValueError("current single-reflection workbench receipt is required")
    if current_workbench.get("phase") != expected_workbench_phase or parent_workbench.get("phase") != expected_workbench_phase:
        raise ValueError("single-reflection continuation workbench phase differs")
    source_record = preparation.get("outputs", {}).get("projected_source")
    if not isinstance(source_record, Mapping) or current_workbench.get("source_transform_applied") is not False:
        raise ValueError("single-reflection continuation current source differs")
    _same_identity(current_workbench.get("source_record", {}), source_record, "source")
    _same_identity(parent_workbench.get("source_record", {}), source_record, "source")
    source_ids = _source_ids(source_record)
    batches = _fixed_batches(parent_dispatch, source_ids)
    current_cases, parent_cases = _cases(current_workbench, batches, source_ids), _cases(parent_workbench, batches, source_ids)
    if current_workbench.get("flight") != parent_workbench.get("flight"):
        raise ValueError("single-reflection continuation flight differs")
    if current_workbench.get("clock_epoch_id") != parent_workbench.get("clock_epoch_id"):
        raise ValueError("single-reflection continuation clock differs")
    for workbench, label in ((current_workbench, "current"), (parent_workbench, "parent")):
        guards = workbench.get("pa_guard_records")
        if not isinstance(guards, list) or not all(isinstance(item, Mapping) for item in guards):
            raise ValueError(f"single-reflection continuation {label} PA guards are missing")
    _records_match(current_workbench["pa_guard_records"], parent_workbench["pa_guard_records"], "PA fields")
    units: list[WholeUnitReplayUnit] = []
    completion: list[dict[str, Any]] = []
    reusable_cases: list[dict[str, Any]] = []
    for batch in batches:
        key, low, high = batch["key"], batch["low"], batch["high"]
        current_case, parent_case = current_cases[(low, high)], parent_cases[(low, high)]
        current_outputs, parent_outputs = current_case.get("outputs"), parent_case.get("outputs")
        preview = current_case.get("preview")
        if not isinstance(parent_outputs, Mapping):
            raise ValueError("single-reflection continuation workbench controls are missing")
        if isinstance(preview, Mapping):
            current_outputs = None
        elif not isinstance(current_outputs, Mapping):
            raise ValueError("single-reflection continuation workbench controls are missing")
        for name in ("program", "particles", "build_spec"):
            if not isinstance(parent_outputs.get(name), Mapping) or (current_outputs is not None and not isinstance(current_outputs.get(name), Mapping)):
                raise ValueError("single-reflection continuation workbench controls are missing")
        if preview is not None:
            if (_normalized_program_text(_verified_text(parent_outputs["program"], "parent Program"),
                    parent_case.get("continuation_pa_guard_records", parent_case.get("iob_pa_guard_records", parent_workbench["pa_guard_records"])))
                    != _normalized_program_text(str(preview.get("program", "")), current_workbench["pa_guard_records"])):
                raise ValueError("single-reflection continuation Program differs")
            if _verified_text(parent_outputs["particles"], "parent particles") != preview.get("particles"):
                raise ValueError("single-reflection continuation particles differs")
            current_build = _normalized_build_text(str(preview.get("build_spec", "")), run, run.absolute(), current_workbench["pa_guard_records"], current_workbench.get("iob_pa_copies", []))
        else:
            _same_identity(current_outputs["program"], parent_outputs["program"], "Program")
            _same_identity(current_outputs["particles"], parent_outputs["particles"], "particles")
            current_build = _normalized_build_text(_verified_text(current_outputs["build_spec"], "current build specification"), run, run.absolute(), current_workbench["pa_guard_records"], current_workbench.get("iob_pa_copies", []))
        parent_build = _normalized_build_text(_verified_text(parent_outputs["build_spec"], "parent build specification"),
            record_path(parent_outputs["build_spec"]).parents[3], Path(parent_case["parent_execution_root"]), parent_workbench["pa_guard_records"], parent_case.get("iob_pa_copies", []))
        if current_build != parent_build:
            raise ValueError("single-reflection continuation build specification differs")
        if preview is not None:
            current_builder = _identity(file_record(Path(str(preview.get("builder_path", "")))), "current builder")
        else:
            current_builder = _builder_identity(current_case, "current")
        if current_builder != _builder_identity(parent_case, "parent"):
            raise ValueError("single-reflection continuation IOB builder differs")
        current_seeds = (preview.get("seed_records") if preview is not None else current_case.get("seed_records"))
        parent_seeds = parent_case.get("seed_records")
        if (not isinstance(current_seeds, list) or not isinstance(parent_seeds, list)
                or not all(isinstance(item, Mapping) for item in [*current_seeds, *parent_seeds])):
            raise ValueError("single-reflection continuation IOB seeds are missing")
        _records_match(current_seeds, parent_seeds, "IOB seeds")
        output_name = "replay_stdout" if phase == "default_replay" else "stdout"
        complete = isinstance(parent_outputs.get("iob"), Mapping)
        paths: list[Path] = []
        try:
            stdout = Path(parent_case.get(output_name, parent / "results" / "single_reflection" /
                                          "default_replay" / f"{parent_case.get('case_id', key)}.stdout.log"))
            if not stdout.is_file():
                raise OSError("parent native stdout is absent")
            read_native_evidence(stdout, {pid: {"particle_id": pid} for pid in source_ids[low - 1:high]}, dict(current_workbench["flight"]))
            if complete:
                paths = [stdout, *(record_path(parent_outputs[name]) for name in ("program", "particles", "build_spec", "iob"))]
        except (KeyError, OSError, UnicodeError, ValueError):
            complete, paths = False, []
        units.append(WholeUnitReplayUnit(key, tuple(path.resolve() for path in paths) if complete else (Path("results/missing.log"),), complete))
        completion.append({"key": key, "source_row_range": [low, high], "is_complete": complete})
        if complete:
            reusable_cases.append({"key": key, "source_row_range": [low, high], "parent_case_id": parent_case.get("case_id"), "parent_iob_record": parent_outputs["iob"]})
    plan = build_whole_unit_replay_plan(predecessor_run_dir=parent, output_dir=run / "inputs" / "continuation" / phase, units=units)
    plan_path = run / "inputs" / "continuation" / phase / "simion_whole_unit_replay_plan.json"
    return {"phase": phase, "frozen_inputs": frozen, "source_record": source_record, "parent_source_record": parent_workbench["source_record"], "completion": completion, "reusable_parent_cases": reusable_cases, "plan": plan, "plan_record": file_record(plan_path)}



def parent_case_records(preparation: Mapping[str, Any], workbench: Mapping[str, Any],
                        case: Mapping[str, Any], *, replay: bool = False) -> dict[Path, dict[str, Any]]:
    """Authorize only exact reused artifacts from the published common phase plan."""
    binding = case.get("replay_continuation_source" if replay else "continuation_source")
    if binding is None:
        return {}
    planned = workbench.get("replay_continuation" if replay else "continuation")
    if not isinstance(planned, Mapping):
        raise ValueError("parent case lacks its explicit continuation plan")
    parent, _, records, _ = _parent(preparation)
    plan_record = planned["plan_record"]
    verify_record("whole-unit continuation plan", plan_record)
    plan = _read(record_path(plan_record), "whole-unit continuation plan")
    units = [unit for unit in plan["units"] if unit["key"] == case["case_id"]]
    if len(units) != 1 or units[0] != binding or binding.get("action") != "reuse":
        raise ValueError("parent case differs from explicit common reuse plan")
    if Path(plan["predecessor"]["run_dir"]).resolve() != parent:
        raise ValueError("parent case continuation owner differs")
    allowed = {}
    for artifact in binding["terminal_outputs"]:
        path = Path(artifact["path"]).resolve()
        if not Path(artifact["path"]).is_absolute() or plan.get("schema_version") != 2:
            raise ValueError("parent case requires the current absolute whole-unit plan")
        identity = records.get(path)
        if identity is None or identity[1] != artifact["sha256"].upper():
            raise ValueError("parent case artifact is not manifest-bound")
        record = dict(path=str(path), exists=True, bytes=identity[0], sha256=identity[1])
        verify_record("reused artifact", record)
        allowed[path] = record
    return allowed
