"""Shared immutable batch-prefix continuation planning for SIMION runners.

This module owns cross-run recovery identity rather than a project's physics:
it validates an interrupted parent, frozen batch ranges, and byte-identical
raw logs, then writes the reusable per-batch terminal prefixes into a *new*
run.  A consumer supplies its native TRACE grammar and remains responsible for
project-specific input projection and result materialization.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError, validate_schema


ROLE = "simion_batch_continuation_plan"
WHOLE_UNIT_ROLE = "simion_whole_unit_replay_plan"
SCHEMA_PATH = Path(__file__).parents[1] / "contracts" / "schemas" / "simion_batch_continuation.schema.json"


@dataclass(frozen=True)
class TraceContinuationPolicy:
    """Native log grammar required to retain a particle terminal prefix.

    ``terminal_pattern`` and ``state_pattern`` require a named
    ``particle_id`` group; the latter additionally requires ``sample_index``.
    The common layer deliberately does not assign event names or terminal
    reasons, because those retain their project/Program meaning.
    """

    terminal_prefix: str
    terminal_pattern: re.Pattern[str]
    state_prefix: str
    state_pattern: re.Pattern[str]
    completion_prefix: str
    prohibited_patterns: tuple[re.Pattern[str], ...] = ()
    release_prefix: str | None = None
    release_pattern: re.Pattern[str] | None = None


@dataclass(frozen=True)
class WholeUnitReplayUnit:
    """One independently restartable work unit and its terminal artifacts.

    A unit is reusable only when *every* declared terminal artifact is present,
    manifest-bound, and byte-identical.  Consumers use this for case-level
    work that has no safely composable particle prefix.
    """

    key: str
    terminal_outputs: tuple[Path, ...]


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def _manifest_hashes(run_dir: Path) -> tuple[dict[Path, str], dict[str, Any]]:
    manifest_path = run_dir / "run_manifest.json"
    manifest = _load_object(manifest_path, "continuation predecessor manifest")
    if manifest.get("role") != "simulation_run_manifest" or manifest.get("status") not in {"failed", "interrupted"}:
        raise ContractError("continuation predecessor manifest status differs")
    config_path = run_dir / "run_config.json"
    config_record = manifest.get("run_config")
    if not isinstance(config_record, dict) or config_record.get("sha256") != file_sha256(config_path):
        raise ContractError("continuation predecessor run config is unbound")
    result: dict[Path, str] = {}
    for record in manifest.get("outputs", []):
        if not isinstance(record, dict):
            continue
        path, digest = record.get("path"), record.get("sha256")
        if isinstance(path, str) and isinstance(digest, str) and len(digest) == 64:
            result[Path(path).resolve()] = digest.upper()
    return result, manifest


def _bound_input(manifest: dict[str, Any], config: dict[str, Any], role: str) -> tuple[Path, str]:
    """Return one parent input only if config, manifest, and bytes agree."""

    config_inputs = config.get("inputs")
    records = manifest.get("inputs")
    if not isinstance(config_inputs, dict) or not isinstance(records, dict):
        raise ContractError("continuation predecessor input registry is invalid")
    configured = config_inputs.get(role)
    record = records.get(role)
    if not isinstance(configured, str) or not isinstance(record, dict):
        raise ContractError(f"continuation predecessor input is missing: {role}")
    path_value, digest = record.get("path"), record.get("sha256")
    if not isinstance(path_value, str) or not isinstance(digest, str) or len(digest) != 64:
        raise ContractError(f"continuation predecessor input binding differs: {role}")
    path = Path(configured).resolve()
    if path != Path(path_value).resolve() or not record.get("exists") or not path.is_file():
        raise ContractError(f"continuation predecessor input binding differs: {role}")
    if file_sha256(path).upper() != digest.upper():
        raise ContractError(f"continuation predecessor input hash differs: {role}")
    return path, digest.upper()


def _validate_plan(plan: dict[str, Any], particle_ids: Sequence[int]) -> list[dict[str, int]]:
    if plan.get("role") != "simion_single_wave_particle_batch_plan":
        raise ContractError("continuation batch plan role differs")
    entries = plan.get("batches")
    if not isinstance(entries, list) or not entries:
        raise ContractError("continuation batch plan is empty")
    normalized: list[dict[str, int]] = []
    observed: list[int] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ContractError("continuation batch plan entry is invalid")
        try:
            first, last, count = (int(entry[key]) for key in ("particle_id_min", "particle_id_max", "count"))
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("continuation batch range is invalid") from exc
        if int(entry.get("index", -1)) != index or count < 1 or last - first + 1 != count:
            raise ContractError("continuation batch range differs")
        normalized.append({"index": index, "first": first, "last": last, "count": count})
        observed.extend(range(first, last + 1))
    if observed != list(particle_ids):
        raise ContractError("continuation batch plan does not cover frozen cohort")
    return normalized


def _source_logs(
    run_dir: Path, index: int, imported_dir_name: str, continuation_dir_name: str, log_glob: str,
) -> list[Path]:
    imported_candidates = (
        run_dir / "inputs" / continuation_dir_name / imported_dir_name / f"batch{index:02d}.stdout.log",
        run_dir / "inputs" / imported_dir_name / f"batch{index:02d}.stdout.log",
    )
    result = [path for path in imported_candidates if path.is_file()]
    # A scheduled-but-never-started worker may leave an empty redirected file.
    # It contains no evidence and must not conflict with an imported checkpoint.
    result.extend(
        path for path in sorted(run_dir.glob(log_glob.format(index=index)))
        if path.read_bytes().strip()
    )
    if len({path.resolve() for path in result}) != len(result):
        raise ContractError("continuation batch log is duplicated")
    return result


def _prior_imported_hashes(
    run_dir: Path, manifest: dict[str, Any], config: dict[str, Any], continuation_dir_name: str,
    batch_plan_sha256: str, frozen_inputs: Mapping[str, str],
) -> dict[Path, str]:
    """Bind prefixes imported by an earlier recovery in the ancestor chain."""

    if "simion_batch_continuation_plan" not in (config.get("inputs") or {}):
        return {}
    path, digest = _bound_input(manifest, config, "simion_batch_continuation_plan")
    plan = _load_object(path, "prior SIMION batch continuation plan")
    predecessor = plan.get("predecessor")
    if (plan.get("role") != ROLE or not isinstance(plan.get("batches"), list) or
            not isinstance(predecessor, dict) or
            not isinstance(predecessor.get("run_dir"), str) or
            not isinstance(predecessor.get("manifest_sha256"), str) or
            plan.get("batch_plan", {}).get("sha256", "").upper() != batch_plan_sha256.upper() or
            plan.get("frozen_inputs") != dict(frozen_inputs)):
        raise ContractError("prior SIMION batch continuation plan differs")
    previous_manifest = Path(predecessor["run_dir"]) / "run_manifest.json"
    if (not previous_manifest.is_file() or
            file_sha256(previous_manifest).upper() != predecessor["manifest_sha256"].upper()):
        raise ContractError("prior SIMION batch continuation predecessor differs")
    if file_sha256(path).upper() != digest:
        raise ContractError("prior SIMION batch continuation plan hash differs")
    result: dict[Path, str] = {}
    for entry in plan["batches"]:
        trace = entry.get("imported_completed_trace") if isinstance(entry, dict) else None
        if not isinstance(trace, dict):
            continue
        path_value, digest = trace.get("path"), trace.get("sha256")
        if not isinstance(path_value, str) or not isinstance(digest, str) or len(digest) != 64:
            raise ContractError("prior imported trace binding differs")
        result[Path(path_value).resolve()] = digest.upper()
    return result


def _completed_prefix(
    paths: Iterable[Path], *, first: int, count: int, hashes: dict[Path, str], policy: TraceContinuationPolicy,
) -> tuple[int, list[str], list[dict[str, str]]]:
    """Return one *complete* checkpoint batch, or no reusable rows.

    A SIMION worker may be interrupted after emitting a valid-looking terminal
    prefix.  That prefix is useful diagnostic evidence, but it is not a
    checkpoint: other workers can have finished out of order and a later
    recovery must never splice an arbitrary particle prefix into a newly
    planned wave.  Reusing only a terminally completed whole batch makes the
    batch plan an immutable checkpoint boundary.
    """
    paths = list(paths)
    if len(paths) > 1:
        # A canonical recovery stores one imported log for a completed batch;
        # a newly launched worker stores one raw log.  Two candidates for the
        # same global batch indicate an ambiguous/old partial-replay lineage.
        raise ContractError("continuation batch has multiple source logs")
    expected = first
    terminal_ids: set[int] = set()
    release_ids: set[int] = set()
    expected_release = first
    state_keys: set[tuple[int, int]] = set()
    retained: list[tuple[int, str]] = []
    sources: list[dict[str, str]] = []
    completion_line_index: int | None = None
    nonempty_line_index = -1
    for path in paths:
        digest = hashes.get(path.resolve())
        if digest is None or file_sha256(path).upper() != digest:
            raise ContractError("continuation source log hash differs")
        try:
            lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
        except (OSError, UnicodeError) as exc:
            raise ContractError("continuation source log is unreadable") from exc
        sources.append({"path": str(path), "sha256": digest})
        for line_index, line in enumerate(lines):
            if line:
                nonempty_line_index = line_index
            if any(pattern.match(line) for pattern in policy.prohibited_patterns):
                raise ContractError("continuation source emitted prohibited TRACE")
            if policy.release_prefix is not None and line.startswith(policy.release_prefix):
                if policy.release_pattern is None:
                    raise ContractError("continuation release policy is incomplete")
                match = policy.release_pattern.fullmatch(line)
                if match is None:
                    raise ContractError("continuation source-release TRACE is malformed")
                particle_id = int(match["particle_id"])
                ion = match.groupdict().get("ion")
                if (particle_id != expected_release or particle_id in release_ids or
                        (ion is not None and int(ion) != particle_id - first + 1)):
                    raise ContractError("continuation source-release identity differs")
                release_ids.add(particle_id)
                expected_release += 1
                retained.append((particle_id, line))
            elif line.startswith(policy.terminal_prefix):
                match = policy.terminal_pattern.fullmatch(line)
                if match is None:
                    raise ContractError("continuation terminal TRACE is malformed")
                particle_id = int(match["particle_id"])
                if particle_id != expected or particle_id in terminal_ids:
                    raise ContractError("continuation terminal IDs are not a contiguous prefix within their batch")
                ion = match.groupdict().get("ion")
                if ion is not None and int(ion) != particle_id - first + 1:
                    raise ContractError("continuation terminal local ion identity differs")
                terminal_ids.add(particle_id)
                retained.append((particle_id, line))
                expected += 1
            elif line.startswith(policy.state_prefix):
                match = policy.state_pattern.fullmatch(line)
                if match is None:
                    raise ContractError("continuation state TRACE is malformed")
                particle_id, sample_index = int(match["particle_id"]), int(match["sample_index"])
                if particle_id < first or particle_id >= first + count or (particle_id, sample_index) in state_keys:
                    raise ContractError("continuation state identity differs")
                ion = match.groupdict().get("ion")
                if ion is not None and int(ion) != particle_id - first + 1:
                    raise ContractError("continuation state local ion identity differs")
                state_keys.add((particle_id, sample_index))
                retained.append((particle_id, line))
            elif line.startswith(policy.completion_prefix):
                if completion_line_index is not None:
                    raise ContractError("continuation completion sentinel is duplicated")
                completion_line_index = line_index
                retained.append((first, line))
            elif line.startswith("TRACE:"):
                raise ContractError("continuation source emitted unrecognized TRACE")
    completed = len(terminal_ids)
    if completed > count:
        raise ContractError("continuation completion sentinel differs")
    # The sentinel is accepted only as the last nonempty line in its log.  A
    # normal SIMION completion is therefore not confused with a stale prefix
    # followed by a crash or another execution appended to the same file.
    if completion_line_index is None:
        return 0, [], sources
    if completion_line_index != nonempty_line_index or completed != count:
        raise ContractError("continuation completion sentinel differs")
    if policy.release_prefix is not None and len(release_ids) != count:
        raise ContractError("continuation source-release census differs")
    return count, [line for _, line in retained], sources


def build_batch_continuation_plan(
    *, predecessor_run_dir: Path, particle_ids: Sequence[int], expected_execution_mode: str,
    contract_input_role: str, expected_contract_sha256: str, cohort_input_paths: Mapping[str, Path],
    policy: TraceContinuationPolicy, output_dir: Path, batch_plan_input_role: str = "simion_execution_batch_plan",
    imported_dir_name: str = "imported_completed_batches", continuation_dir_name: str = "simion_batch_continuation",
    log_glob: str = "logs/simion__batch{index:02d}*.stdout.log",
) -> dict[str, Any]:
    """Build a manifest-bound, per-batch replay plan for a new immutable run."""

    predecessor_run_dir = predecessor_run_dir.resolve()
    output_dir = output_dir.resolve()
    if output_dir == predecessor_run_dir or predecessor_run_dir in output_dir.parents:
        raise ContractError("continuation output directory is within predecessor run")
    continuation_plan_path = output_dir / "simion_batch_continuation_plan.json"
    canonical_plan_path = output_dir / "simion_execution_batch_plan.json"
    imported_root = output_dir / imported_dir_name
    if continuation_plan_path.exists() or canonical_plan_path.exists() or imported_root.exists():
        raise ContractError("continuation output target already exists")
    expected_hashes, manifest = _manifest_hashes(predecessor_run_dir)
    config_path = predecessor_run_dir / "run_config.json"
    config = _load_object(config_path, "continuation predecessor run configuration")
    parameters = config.get("parameters")
    if not isinstance(parameters, dict) or parameters.get("execution_mode") != expected_execution_mode:
        raise ContractError("continuation predecessor execution mode differs")
    if parameters.get("particle_count") != len(particle_ids) or parameters.get("launched_particle_count") != len(particle_ids):
        raise ContractError("continuation predecessor population differs")
    contract_path, contract_sha256 = _bound_input(manifest, config, contract_input_role)
    if contract_sha256 != expected_contract_sha256.upper():
        raise ContractError("continuation contract identity differs")
    plan_path, plan_sha256 = _bound_input(manifest, config, batch_plan_input_role)
    plan = _load_object(plan_path, "continuation predecessor batch plan")
    batches = _validate_plan(plan, particle_ids)
    frozen_inputs: dict[str, str] = {}
    for role, child_path in cohort_input_paths.items():
        _, parent_sha256 = _bound_input(manifest, config, role)
        child_path = child_path.resolve()
        if not child_path.is_file() or file_sha256(child_path).upper() != parent_sha256:
            raise ContractError(f"continuation frozen cohort identity differs: {role}")
        frozen_inputs[role] = parent_sha256
    expected_hashes.update(_prior_imported_hashes(
        predecessor_run_dir, manifest, config, continuation_dir_name, plan_sha256, frozen_inputs,
    ))
    output: list[dict[str, Any]] = []
    prefix_open = True
    for batch in batches:
        candidate_paths = _source_logs(
            predecessor_run_dir, batch["index"], imported_dir_name, continuation_dir_name, log_glob,
        ) if prefix_open else []
        # A host/process interruption can leave the currently active worker's
        # redirected stdout on disk after the last published checkpoint.  It
        # is intentionally not trusted: only a byte hash recorded in the
        # predecessor manifest may contribute to a resumed population.
        paths = [
            path for path in candidate_paths
            if path.resolve() in expected_hashes
        ]
        completed, retained, sources = _completed_prefix(
            paths, first=batch["first"], count=batch["count"], hashes=expected_hashes, policy=policy,
        ) if paths else (0, [], [])
        if completed != batch["count"]:
            # Checkpoints are a global ordered prefix, not a set of whichever
            # workers happened to terminate before a host interruption.
            prefix_open = False
        imported = None
        if completed:
            imported_root.mkdir(parents=True, exist_ok=True)
            path = imported_root / f"batch{batch['index']:02d}.stdout.log"
            path.write_text("\n".join(retained) + "\n", encoding="utf-8", newline="\n")
            imported = {"path": str(path), "sha256": file_sha256(path)}
        output.append({"index": batch["index"], "particle_id_min": batch["first"], "particle_id_max": batch["last"], "count": batch["count"], "completed_particle_count": completed, "replay_particle_id_min": batch["first"] + completed, "replay_particle_count": batch["count"] - completed, "imported_completed_trace": imported, "source_logs": sources})
    result = {"schema_version": 1, "role": ROLE, "status": "ready", "predecessor": {"run_dir": str(predecessor_run_dir), "run_id": manifest.get("run_id"), "manifest_sha256": file_sha256(predecessor_run_dir / "run_manifest.json"), "run_config_sha256": file_sha256(config_path)}, "batch_plan": {"path": str(canonical_plan_path), "sha256": plan_sha256, "particle_count": len(particle_ids), "batch_count": len(output), "predecessor_path": str(plan_path)}, "contract": {"path": str(contract_path), "sha256": expected_contract_sha256.upper(), "input_role": contract_input_role}, "frozen_inputs": frozen_inputs, "batches": output, "completed_particle_count": sum(item["completed_particle_count"] for item in output), "replay_particle_count": sum(item["replay_particle_count"] for item in output)}
    if result["completed_particle_count"] + result["replay_particle_count"] != len(particle_ids):
        raise AssertionError("continuation plan does not cover frozen cohort")
    validate_schema(result, SCHEMA_PATH)
    output_dir.mkdir(parents=True, exist_ok=True)
    canonical_plan_path.write_bytes(plan_path.read_bytes())
    if file_sha256(canonical_plan_path).upper() != plan_sha256:
        raise AssertionError("materialized canonical batch plan hash differs")
    continuation_plan_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    return result


def build_whole_unit_replay_plan(
    *, predecessor_run_dir: Path, output_dir: Path, units: Sequence[WholeUnitReplayUnit],
) -> dict[str, Any]:
    """Plan immutable reuse/replay for independent, non-prefix work units.

    This is intentionally separate from particle-prefix continuation: it
    never treats an incomplete unit as partly reusable.  Artifact paths are
    run-relative so no project-specific result layout leaks into this module.
    """

    predecessor_run_dir = predecessor_run_dir.resolve()
    manifest_hashes, manifest = _manifest_hashes(predecessor_run_dir)
    if not units:
        raise ContractError("whole-unit replay plan is empty")
    observed_keys: set[str] = set()
    records: list[dict[str, Any]] = []
    for unit in units:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", unit.key) or unit.key in observed_keys:
            raise ContractError("whole-unit replay key differs")
        observed_keys.add(unit.key)
        if not unit.terminal_outputs:
            raise ContractError("whole-unit replay terminal outputs are empty")
        artifacts: list[dict[str, str]] = []
        reusable = True
        seen_paths: set[Path] = set()
        for relative in unit.terminal_outputs:
            if relative.is_absolute() or ".." in relative.parts:
                raise ContractError("whole-unit replay output path escapes predecessor run")
            absolute = (predecessor_run_dir / relative).resolve()
            if absolute in seen_paths:
                raise ContractError("whole-unit replay output is duplicated")
            seen_paths.add(absolute)
            digest = manifest_hashes.get(absolute)
            if absolute.exists() and digest is None:
                raise ContractError("whole-unit replay output is not manifest-bound")
            if digest is None:
                reusable = False
                continue
            if not absolute.is_file() or file_sha256(absolute).upper() != digest:
                raise ContractError("whole-unit replay output hash differs")
            artifacts.append({"path": str(relative), "sha256": digest})
        records.append({
            "key": unit.key,
            "action": "reuse" if reusable else "replay",
            "terminal_outputs": artifacts if reusable else [],
        })
    result = {
        "schema_version": 1,
        "role": WHOLE_UNIT_ROLE,
        "status": "ready",
        "predecessor": {
            "run_dir": str(predecessor_run_dir),
            "run_id": manifest.get("run_id"),
            "manifest_sha256": file_sha256(predecessor_run_dir / "run_manifest.json"),
            "run_config_sha256": file_sha256(predecessor_run_dir / "run_config.json"),
        },
        "units": records,
        "reusable_unit_count": sum(record["action"] == "reuse" for record in records),
        "replay_unit_count": sum(record["action"] == "replay" for record in records),
    }
    validate_schema(result, SCHEMA_PATH)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "simion_whole_unit_replay_plan.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return result
