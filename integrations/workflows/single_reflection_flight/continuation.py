"""Adapt the single-reflection workbench to common whole-batch continuation.

The workbench remains the only scientific input projection. This adapter freezes
only the predecessor dispatch and workbench receipt, then delegates complete
batch reuse/replay selection to the shared SIMION planner.
"""
from __future__ import annotations

import csv
from copy import deepcopy
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
from common.simion.native_completion import frontend_batch_completion_path, validate_frontend_batch_completion


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


def recover_provisional_dispatch(preparation: Mapping[str, Any], phase: str) -> dict[str, Any] | None:
    """Reconstruct the original first interval only from bound natural-exit measurements."""
    if phase == "default_replay" and not preparation["default_replay_requested"]:
        return None
    from common.simion.resource_scheduler import plan_recovered_formal_followup

    parent, _, records, _ = _parent(preparation)
    _, workbench_path, workbench_phase = _phase_paths(parent, phase)
    if phase == 'default_replay' or workbench_path.resolve() not in records:
        return None
    _bound_parent_file(workbench_path, records, 'provisional workbench')
    workbench = _read(workbench_path, 'provisional workbench')
    if workbench.get('coverage') != 'initial_formal_batch_only':
        return None
    cases=workbench.get('batches')
    if not isinstance(cases,list) or len(cases)!=1:
        raise ValueError('provisional workbench requires exactly one formal case')
    case=_published_case(cases[0], records)
    provisional=parent/'results'/f'{workbench_phase}.provisional_dispatch_plan.json'
    _bound_parent_file(provisional,records,'provisional dispatch')
    receipt=frontend_batch_completion_path(parent,workbench_phase,str(case['case_id']))
    _bound_parent_file(receipt,records,'provisional formal completion')
    validate_frontend_batch_completion(receipt,phase=workbench_phase,case_id=str(case['case_id']),
        stdout=Path(case['stdout']),count=int(case['count']),row_range=case['source_row_range'])
    return plan_recovered_formal_followup(_read(provisional,'provisional dispatch'),_read(receipt,'formal completion'))


def freeze_phase_inputs(preparation: Mapping[str, Any], run: Path, phase: str) -> dict[str, Any] | None:
    """Freeze the two small, manifest-bound predecessor receipts for ``phase``."""
    if phase == "default_replay" and not preparation["default_replay_requested"]:
        return None
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


def source_capacity_projection(*, artifact_root: Path, request_path: Path | None = None,
                               preparation: Mapping[str, Any] | None = None,
                               borrowed_paths: list[str] | None = None) -> dict[str, Any]:
    """Project explicit source lineage to existing capacity owners, without PA reads.

    This only establishes read protection. Preparation and the continuation
    planner retain their scientific applicability and actual completion checks.
    """
    from common.contracts.run_capacity_lifecycle import resolve_consumed_run_capacity_owner

    target = artifact_root.resolve(strict=True)
    queue: list[tuple[dict, dict | None]] = []
    payload_records: list[dict] = []
    field_sources: list[tuple[str, dict, dict]] = []
    borrowed = {Path(path).resolve() for path in (borrowed_paths or [])}

    def protected_records(value: Any) -> None:
        if isinstance(value, Mapping):
            if isinstance(value.get("path"), str) and "bytes" in value and "sha256" in value:
                payload_records.append(dict(value))
            for child in value.values():
                protected_records(child)
        elif isinstance(value, list):
            for child in value:
                protected_records(child)

    if request_path is not None:
        request_path = request_path.resolve(strict=True)
        request = _read(request_path, "source-protection request")
        continuation = request.get("continuation")
        if continuation:
            manifest_record = dict(continuation["predecessor_run_manifest"])
            manifest_record["path"] = str(record_path(manifest_record, base_dir=request_path.parent))
            stopped_record = continuation.get("stopped_receipt")
            if stopped_record is not None:
                stopped_record = dict(stopped_record, path=str(record_path(stopped_record, base_dir=request_path.parent)))
            queue.append((manifest_record, stopped_record))
        for key in ("frontend_fields", "downstream_fields"):
            source = request.get("providers", {}).get(key)
            if source is None:
                continue
            source = dict(source, path=str(record_path(source, base_dir=request_path.parent)))
            verify_record("explicit "+key, source)
            path = Path(source["path"])
            # These are the existing prepare owner layouts, never PA-path inference.
            if key == "frontend_fields" and path.parent.name == "inputs":
                producer = path.parent.parent
            elif (key == "downstream_fields" and path.name == "downstream_field_preparation.json"
                  and path.parent.name == "downstream_fields" and path.parent.parent.name == "simion"):
                producer = path.parents[2]
            else:
                raise ValueError("source protection requires the canonical explicit "+key+" receipt")
            manifest_record = file_record(producer/"run_manifest.json")
            queue.append((manifest_record, None))
            field_sources.append((key, source, manifest_record))
    if preparation is not None:
        records = preparation["input_records"]
        for name in ("frontend_fields_manifest", "downstream_fields_manifest", "continuation_parent_manifest"):
            if name in records:
                stopped = records.get("continuation_stopped_receipt") if name == "continuation_parent_manifest" else None
                queue.append((dict(records[name]), stopped))
        for name in ("frontend_fields", "downstream_fields"):
            if name in records:
                verify_record("frozen "+name, dict(records[name]))
                field_sources.append((name, dict(records[name]), dict(records[name+"_manifest"])))

    references: dict[Path, dict] = {}
    owners: dict[Path, dict] = {}
    bound_paths: set[Path] = set()
    while queue:
        record, stopped_record = queue.pop()
        frozen_path = record_path(record)
        verify_record("source lineage manifest", record)
        manifest = _read(frozen_path, "source lineage manifest")
        config_record = manifest.get("run_config", {})
        if stopped_record is not None and manifest.get("status") == "checkpoint":
            verify_record("source lineage stopped receipt", dict(stopped_record))
            config_record = _read(record_path(dict(stopped_record)), "source stopped receipt").get("run_config", {})
        config_path = record_path(config_record, base_dir=frozen_path.parent)
        if config_path.name != "run_config.json":
            raise ValueError("source lineage manifest lacks its exact owner config")
        canonical = config_path.parent/"run_manifest.json"
        canonical_record = {**record, "path": str(canonical)}
        canonical_record.pop("source_path", None)
        if canonical in references:
            if _identity(references[canonical]["manifest_record"], "source manifest") != _identity(canonical_record, "source manifest"):
                raise ValueError("source lineage has conflicting manifest identities")
            continue
        owner = resolve_consumed_run_capacity_owner(canonical_record, consumer_artifact_root=target,
                                                   stopped_receipt_record=stopped_record)
        reference = dict(manifest_record=canonical_record, protected_paths=[], protected_cache_keys=[])
        if stopped_record is not None:
            reference["stopped_receipt_record"] = dict(stopped_record)
        references[canonical] = reference
        owners[canonical] = owner
        records = _manifest_records(manifest)
        bound_paths.update(records)
        for name, child in manifest["inputs"].items():
            if name in ("frontend_fields_manifest", "downstream_fields_manifest", "continuation_parent_manifest"):
                stopped = manifest["inputs"].get("continuation_stopped_receipt") if name == "continuation_parent_manifest" else None
                queue.append((dict(child), stopped))
            if name.startswith("continuation_artifact_"):
                borrowed.add(record_path(child))
        for item in manifest["outputs"]:
            if Path(item["path"]).name not in ("workbench_preparation.json", "discovery_workbench_preparation.json"):
                continue
            verify_record("source workbench receipt", item)
            workbench = _read(record_path(item), "source workbench receipt")
            for raw in workbench.get("batches", []):
                case = _published_case(raw, records)
                protected_records(case.get("continuation_pa_guard_records", []))
    for kind, record, manifest_record in field_sources:
        value = _read(record_path(record), kind+" source receipt")
        if kind == "frontend_fields":
            for domain in value["domains"]:
                for row in domain["working_points"]:
                    info = domain if value["schema_version"] == 2 else row
                    # Match the existing field-plan projection: generation is
                    # explicit provenance, never a root inferred from a PA path.
                    payload_records.append(dict(row, path=str(Path(info["generation_directory"]).resolve()/Path(row["path"]).name), cache_key=info["cache_key"]))
        else:
            from integrations.workflows.single_reflection_flight.downstream_fields import load_downstream_fields
            canonical = Path(manifest_record.get("source_path", manifest_record["path"]))
            normalized = dict(manifest_record, path=str(canonical), source_path=str(canonical))
            _, _, guards = load_downstream_fields(record, value["oatof_resolved_record"], normalized)
            payload_records.extend(guards)
    if borrowed - bound_paths:
        raise ValueError("continuation protection artifact is not bound by explicit source lineage")
    paths = borrowed | {record_path(record) for record in payload_records}
    for path in sorted(paths):
        candidates = [canonical for canonical, owner in owners.items()
                      if path.is_relative_to(Path(owner["artifact_root"]))]
        roots = {owners[canonical]["artifact_root"] for canonical in candidates}
        if len(roots) != 1:
            raise ValueError("source protection path has no unambiguous explicit capacity owner: "+str(path))
        # Multiple runs on the same physical root share one existing source lease.
        reference = references[candidates[0]]
        reference["protected_paths"].append(str(path))
        for record in payload_records:
            if record_path(record) == path and "cache_key" in record:
                if record["cache_key"] not in reference["protected_cache_keys"]:
                    reference["protected_cache_keys"].append(record["cache_key"])
    return dict(source_references=list(references.values()))



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


def _published_case(case: Mapping[str, Any], records: Mapping[Path, tuple[int, str]] | None = None) -> dict[str, Any]:
    """Resolve saved execution aliases through canonical published control records."""
    result = deepcopy(case)
    outputs = result['outputs']
    if records is not None:
        for name, record in outputs.items():
            original = record_path(record)
            if original.is_file() or records.get(original) == _identity(record, 'parent '+name):
                continue
            # Saved batch controls have a fixed simion/phase/case/file layout.
            # The terminal manifest, not a guessed replacement prefix, binds
            # both that suffix and the immutable content identity.
            suffix = original.parts[-4:]
            matches = [path for path, identity in records.items()
                       if path.parts[-4:] == suffix and identity == _identity(record, 'parent '+name)]
            if len(matches) != 1:
                raise ValueError('single-reflection continuation '+name+' is not uniquely manifest-bound')
            outputs[name] = dict(record, path=str(matches[0]))
    result['outputs'] = outputs
    spec = record_path(outputs["build_spec"])
    # Batch layout is fixed by this adapter. Its canonical control record can
    # belong to an earlier owner explicitly rebound by the direct parent.
    artifact_owner = spec.parents[3]
    relative_spec = spec.relative_to(artifact_owner)
    old_root = Path(case["iob_path"])
    for _ in relative_spec.parts:
        old_root = old_root.parent
    old_root = Path(case.get("parent_execution_root", old_root))
    result["parent_execution_root"] = str(old_root)
    def durable_path(value: str, identity: tuple[int, str] | None = None,
                     *, allow_unpublished: bool = False) -> str:
        path = Path(value)
        if records is not None and path in records:
            if identity is not None and records[path] != identity:
                raise ValueError('single-reflection continuation case path identity differs: '+value)
            return value
        if path.is_relative_to(old_root):
            target = artifact_owner / path.relative_to(old_root)
            if records is not None and target in records:
                if identity is not None and records[target] != identity:
                    raise ValueError('single-reflection continuation case path identity differs: '+value)
                return str(target)
        if path.exists():
            return value
        # A case may inherit its IOB from one owner and publish replay evidence
        # under another. Only this adapter's fixed layouts may be rebound;
        # each file still needs a unique terminal-manifest identity.
        parts = path.parts
        case_id = str(case.get('case_id', ''))
        suffix = None
        if len(parts) >= 4:
            tail = parts[-4:]
            if (tail[0] == 'results' and tail[1] == 'single_reflection'
                    and tail[2] == 'default_replay'
                    and tail[3] in {case_id+'.stdout.log', case_id+'.stderr.log', 'resource_usage.json'}):
                suffix = tail
            elif (identity is not None and tail[0:2] == ('inputs', 'continuation')
                  and tail[2] in {'baseline', 'default_replay', 'discovery'}
                  and tail[3] in {'workbench_preparation.json', 'discovery_workbench_preparation.json',
                                  'full_instrument.dispatch_plan.json', 'discovery.dispatch_plan.json'}):
                suffix = tail
        if records is not None and suffix is not None:
            matches = [candidate for candidate, bound in records.items()
                       if candidate.parts[-len(suffix):] == suffix and (identity is None or bound == identity)]
            if len(matches) > 1:
                raise ValueError('single-reflection continuation case path is not uniquely manifest-bound: '+value)
            if len(matches) == 1:
                return str(matches[0])
            if identity is not None or not allow_unpublished:
                raise ValueError('single-reflection continuation case path is not uniquely manifest-bound: '+value)
        if path.is_relative_to(old_root):
            # An unstarted output or a missing published whole unit remains
            # unavailable; the planner must replay it rather than claim reuse.
            return str(artifact_owner / path.relative_to(old_root))
        if allow_unpublished:
            return value
        raise ValueError('single-reflection continuation case path is not uniquely manifest-bound: '+value)

    def transport_records(value: Any) -> None:
        # Only identity-bearing file records are transported recursively inside
        # this existing case receipt. Historical command strings remain history.
        if isinstance(value, dict):
            if isinstance(value.get('path'), str) and 'bytes' in value and 'sha256' in value:
                value['path'] = durable_path(value['path'], _identity(value, 'parent case record'))
            for child in value.values():
                transport_records(child)
        elif isinstance(value, list):
            for child in value:
                transport_records(child)

    transport_records(result)
    for name in ('stdout', 'stderr', 'replay_stdout', 'replay_stderr', 'receipt_path'):
        if isinstance(case.get(name), str):
            # An unstarted replay has no log yet. Its output destination must
            # retain the same owner-relative layout, not claim published data.
            result[name] = durable_path(case[name], allow_unpublished=name.startswith('replay_') or name == 'stderr')
    for item in result.get('iob_pa_copies', []):
        item['destination'] = durable_path(item['destination'], _identity(item['source_record'], 'IOB PA transport'))
    if "iob" in outputs:
        iob = record_path(outputs["iob"])
        result.update(iob_path=str(iob), working_directory=str(iob.parent))
    for name in ('iob_builder_arguments', 'iob_verify_arguments'):
        if name in case:
            arguments = list(case[name])
            for index in (3, 4):
                if len(arguments) > index and isinstance(arguments[index], str):
                    source_path = Path(arguments[index])
                    if (index == 3 and records is not None and source_path.resolve() not in records
                            and source_path.name == "build_iob.lua" and source_path.is_file()):
                        # A recovered case may retain an ancestor's existing compiler
                        # address while its direct parent freezes the same source.
                        # Rebind only this fixed compiler role and exact bytes.
                        identity = _identity(file_record(source_path), "inherited IOB builder")
                        matches = [path for path, bound in records.items()
                                   if path.parts[-4:] == source_path.parts[-4:] and bound == identity]
                        if len(matches) != 1:
                            raise ValueError("inherited IOB builder is not uniquely manifest-bound")
                        arguments[index] = str(matches[0])
                    else:
                        arguments[index] = durable_path(arguments[index])
            result[name] = arguments

    return result


def prepare_phase_continuation(preparation: Mapping[str, Any], current_workbench: Mapping[str, Any], run: Path, phase: str) -> dict[str, Any] | None:
    """Plan whole-batch reuse/replay directly from current and parent workbenches."""
    if phase == "default_replay" and not preparation["default_replay_requested"]:
        return None
    if preparation.get("role") != "single_reflection_geometry_preparation":
        raise ValueError("current single-reflection preparation receipt is required")
    frozen = freeze_phase_inputs(preparation, run, phase)
    if frozen is None:
        return None
    parent = Path(frozen["parent_run_dir"])
    _, _, expected_workbench_phase = _phase_paths(parent, phase)
    parent_dispatch = _read(record_path(frozen["dispatch_record"]), "frozen final dispatch")
    parent_workbench = _read(record_path(frozen["workbench_record"]), "frozen workbench receipt")
    recovered_dispatch=recover_provisional_dispatch(preparation,phase)
    if recovered_dispatch is not None:
        parent_dispatch=recovered_dispatch
        recovered_path=run/'inputs'/'continuation'/phase/'recovered_dispatch_plan.json'
        recovered_path.write_text(json.dumps(recovered_dispatch,indent=2)+'\n',encoding='utf-8',newline='\n')
        frozen['dispatch_record']=file_record(recovered_path)
    _, parent_manifest, parent_records, _ = _parent(preparation)
    parent_workbench["batches"] = [_published_case(case, parent_records) for case in parent_workbench["batches"]]
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
    legacy_execution = parent / 'results' / 'single_reflection' / 'flight_execution_records.json'
    legacy_rows = []
    if parent_manifest.get('status') == 'success' and legacy_execution.resolve() in parent_records:
        _bound_parent_file(legacy_execution, parent_records, 'legacy flight execution records')
        legacy_rows = json.loads(legacy_execution.read_text(encoding='utf-8-sig'))
        if not isinstance(legacy_rows, list):
            raise ValueError('legacy flight execution records are invalid')
    batches = _fixed_batches(parent_dispatch, source_ids)
    current_cases = _cases(current_workbench, batches, source_ids)
    parent_cases = _cases(parent_workbench, batches[:1] if recovered_dispatch is not None else batches, source_ids)
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
        current_case = current_cases[(low, high)]
        parent_case = parent_cases.get((low, high))
        if parent_case is None and recovered_dispatch is not None:
            units.append(WholeUnitReplayUnit(key,(Path('results/missing.log'),),False))
            completion.append({'key':key,'source_row_range':[low,high],'is_complete':False})
            continue
        if parent_case is None:
            raise ValueError('single-reflection continuation parent case is missing')
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
        if complete:
            receipt_phase = 'default_replay' if phase == 'default_replay' else expected_workbench_phase
            receipt = frontend_batch_completion_path(parent, receipt_phase, str(parent_case['case_id']))
            if receipt.resolve() not in parent_records:
                candidates = [path for path in parent_records if path.name == receipt.name
                              and path.parent.name == receipt_phase and path.parent.parent.name == 'frontend_batch_completion']
                if len(candidates) > 1:
                    raise ValueError('frontend batch completion has ambiguous manifest bindings')
                if candidates:
                    receipt = candidates[0]
            if receipt.resolve() in parent_records:
                _bound_parent_file(receipt, parent_records, 'frontend batch completion')
                validate_frontend_batch_completion(receipt, phase=receipt_phase, case_id=str(parent_case['case_id']),
                    stdout=stdout, count=int(parent_case['count']), row_range=[low, high])
                paths.append(receipt)
            else:
                if 'continuation_source' in parent_case:
                    raise ValueError('inherited frontend completion is not manifest-bound')
                expected_phase = 'discovery' if phase == 'discovery' else phase
                matches = [row for row in legacy_rows if isinstance(row, dict) and row.get('phase') == expected_phase
                           and row.get('exit_code') == 0 and row.get('controls_unchanged') is True
                           and isinstance(row.get('stdout_path'), str)
                           and Path(row['stdout_path']).resolve() == stdout.resolve()]
                if len(matches) == 1:
                    paths.append(legacy_execution)
                else:
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
