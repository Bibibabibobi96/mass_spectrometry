"""Shared immutable whole-unit continuation planning for SIMION runners.

Consumers supply native completion facts and remain responsible for scientific
input projection and result materialization.  The common planner independently
reuses complete, manifest-bound units, including units finished out of order.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Sequence

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError, validate_schema


WHOLE_UNIT_ROLE = "simion_whole_unit_replay_plan"
SCHEMA_PATH = Path(__file__).parents[1] / "contracts" / "schemas" / "simion_batch_continuation.schema.json"


@dataclass(frozen=True)
class WholeUnitReplayUnit:
    """One independently restartable work unit and its terminal artifacts.

    A unit is reusable only when *every* declared terminal artifact is present,
    manifest-bound, byte-identical, and the consumer's native completion
    check passed.  ``is_complete`` is an explicit fact supplied by the
    consumer; common intentionally does not interpret project TRACE or other
    solver output.  A known-incomplete unit is replayed without opening its
    potentially large terminal artifacts.  ``is_complete`` is required so a
    caller cannot accidentally infer completion from file presence.  Consumers
    use this for independent units that can finish out of order.
    """

    key: str
    terminal_outputs: tuple[Path, ...]
    is_complete: bool


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def _checkpoint_has_intact_immutable_inputs(
    *, manifest: dict[str, Any], config: dict[str, Any]
) -> bool:
    """Recognize a checkpoint whose mutable run config gained only metadata.

    A SIMION batch can complete after the checkpoint manifest is written and
    before the runner appends completion bookkeeping to ``run_config.json``.
    Its raw TRACE remains reusable only when the immutable input records in
    that checkpoint still verify byte-for-byte.  This is deliberately narrower
    than accepting general manifest drift.
    """

    if (
        manifest.get("status") != "checkpoint"
        or config.get("run_id") != manifest.get("run_id")
        or config.get("mode") != manifest.get("mode")
    ):
        return False
    records = manifest.get("inputs")
    if not isinstance(records, dict) or not records:
        return False
    for record in records.values():
        if not isinstance(record, dict):
            return False
        path_value, digest = record.get("path"), record.get("sha256")
        if (
            not record.get("exists")
            or not isinstance(path_value, str)
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            return False
        path = Path(path_value)
        if not path.is_file() or file_sha256(path).upper() != digest.upper():
            return False
    return True


def _manifest_hashes(run_dir: Path) -> tuple[dict[Path, str], dict[str, Any]]:
    manifest_path = run_dir / "run_manifest.json"
    manifest = _load_object(manifest_path, "continuation predecessor manifest")
    # Completed batches remain reusable after successful publication too, so
    # analysis or publication can be repeated without another native flight.
    # Live runs are never predecessors; all accepted inputs stay manifest-bound.
    if manifest.get("role") != "simulation_run_manifest" or manifest.get("status") not in {"failed", "interrupted", "checkpoint", "success"}:
        raise ContractError("continuation predecessor manifest status differs")
    config_path = run_dir / "run_config.json"
    config = _load_object(config_path, "continuation predecessor run configuration")
    config_record = manifest.get("run_config")
    config_is_bound = (
        isinstance(config_record, dict)
        and config_record.get("sha256") == file_sha256(config_path)
    )
    if not config_is_bound and not _checkpoint_has_intact_immutable_inputs(
        manifest=manifest, config=config
    ):
        raise ContractError("continuation predecessor run config is unbound")
    result: dict[Path, str] = {}
    for record in manifest.get("outputs", []):
        if not isinstance(record, dict):
            continue
        path, digest = record.get("path"), record.get("sha256")
        if isinstance(path, str) and isinstance(digest, str) and len(digest) == 64:
            result[Path(path).resolve()] = digest.upper()
    return result, manifest


def _whole_unit_artifact_hashes(run_dir: Path) -> tuple[dict[Path, str], dict[str, Any]]:
    """Index exactly the current predecessor's bound inputs and outputs."""

    outputs, manifest = _manifest_hashes(run_dir)
    result = dict(outputs)

    def add(record: object) -> None:
        if not isinstance(record, dict):
            return
        path_value, digest = record.get("path"), record.get("sha256")
        if not isinstance(path_value, str) or not isinstance(digest, str) or len(digest) != 64:
            return
        path = Path(path_value).resolve()
        digest = digest.upper()
        existing = result.get(path)
        if existing is not None and existing != digest:
            raise ContractError("whole-unit replay manifest artifact binding conflicts")
        result[path] = digest

    inputs = manifest.get("inputs")
    if isinstance(inputs, dict):
        for record in inputs.values():
            add(record)
    for record in manifest.get("outputs", []):
        add(record)
    return result, manifest


def build_whole_unit_replay_plan(
    *, predecessor_run_dir: Path, output_dir: Path, units: Sequence[WholeUnitReplayUnit],
) -> dict[str, Any]:
    """Plan immutable reuse/replay for independent work units.

    Units may finish out of order, but an incomplete unit always replays in full.  Relative artifacts resolve under the predecessor; an
    absolute artifact must already be bound by that same predecessor manifest.
    This preserves prior immutable evidence without searching ancestors.
    """

    predecessor_run_dir = predecessor_run_dir.resolve()
    manifest_hashes, manifest = _whole_unit_artifact_hashes(predecessor_run_dir)
    if not units:
        raise ContractError("whole-unit replay plan is empty")
    observed_keys: set[str] = set()
    records: list[dict[str, Any]] = []
    for unit in units:
        if not isinstance(unit, WholeUnitReplayUnit):
            raise ContractError("whole-unit replay unit is invalid")
        if not isinstance(unit.key, str) or not isinstance(unit.terminal_outputs, tuple):
            raise ContractError("whole-unit replay unit is invalid")
        if type(unit.is_complete) is not bool:
            raise ContractError("whole-unit replay completion fact is invalid")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", unit.key) or unit.key in observed_keys:
            raise ContractError("whole-unit replay key differs")
        observed_keys.add(unit.key)
        if not unit.terminal_outputs:
            raise ContractError("whole-unit replay terminal outputs are empty")
        if any(not isinstance(path, Path) for path in unit.terminal_outputs):
            raise ContractError("whole-unit replay output path is invalid")
        if not unit.is_complete:
            # A caller already established this work unit did not reach its
            # native terminal state.  It must replay as one unit; reading or
            # hashing a large partial log cannot make it reusable.
            records.append({"key": unit.key, "action": "replay", "terminal_outputs": []})
            continue
        artifacts: list[dict[str, str]] = []
        reusable = True
        seen_paths: set[Path] = set()
        for requested in unit.terminal_outputs:
            if not requested.is_absolute() and ".." in requested.parts:
                raise ContractError("whole-unit replay output path escapes predecessor run")
            absolute = requested.resolve() if requested.is_absolute() else (predecessor_run_dir / requested).resolve()
            if absolute in seen_paths:
                raise ContractError("whole-unit replay output is duplicated")
            seen_paths.add(absolute)
            digest = manifest_hashes.get(absolute)
            if requested.is_absolute() and digest is None:
                raise ContractError("whole-unit replay absolute output is not manifest-bound")
            if absolute.exists() and digest is None:
                raise ContractError("whole-unit replay output is not manifest-bound")
            if digest is None:
                reusable = False
                continue
            if not absolute.is_file() or file_sha256(absolute).upper() != digest:
                raise ContractError("whole-unit replay output hash differs")
            artifacts.append({"path": str(absolute), "sha256": digest})
        records.append({
            "key": unit.key,
            "action": "reuse" if reusable else "replay",
            "terminal_outputs": artifacts if reusable else [],
        })
    result = {
        "schema_version": 2,
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
