"""Materialize published bytes through the one admitted file-copy process."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from msplatform.execution.inputs import freeze_file
from msplatform.execution.manifest_records import file_record
from msplatform.execution.recorded_file_removal import write_json_atomic
from msplatform.execution.resources import resource_path
from msplatform.execution.run_session import RunSession


def _copies(copies: Sequence[Mapping[str, Any]], session: RunSession) -> list[dict[str, Any]]:
    result, destinations = [], set()
    for item in copies:
        if set(item) != {"source_record", "destination"}:
            raise ValueError("payload copy requires source_record and destination")
        record = copy.deepcopy(dict(item["source_record"]))
        source, target = Path(record["path"]), Path(item["destination"])
        if (record.get("exists") is not True or type(record.get("bytes")) is not int or record["bytes"] < 0
                or not isinstance(record.get("sha256"), str)
                or not re.fullmatch(r"[a-fA-F0-9]{64}", record["sha256"])
                or not source.is_absolute() or not source.is_file() or source.is_symlink()
                or not target.is_absolute() or target.exists() or target.is_symlink()):
            raise ValueError("payload copy requires a complete source record and an independent new destination")
        destination = session.canonical_path(target)
        if (not destination.is_relative_to(session.artifact_run_dir.resolve())
                or destination in destinations or destination == source.resolve()):
            raise ValueError("payload destinations must be unique and inside the admitted run")
        session.declare_file(destination, record["retention_role"])
        destinations.add(destination)
        result.append(dict(source_record=record, destination=str(destination)))
    if not result:
        raise ValueError("payload materialization requires at least one explicit copy")
    return result


def _outputs(receipt: Mapping[str, Any], copies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if (type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 1
            or receipt.get("role") != "payload_materialization"
            or receipt.get("status") != "success" or receipt.get("primary") is not None
            or receipt.get("secondary_errors") != []):
        raise ValueError("payload materialization receipt is incomplete or failed")
    outputs = receipt.get("outputs")
    if not isinstance(outputs, list) or len(outputs) != len(copies):
        raise ValueError("payload materialization output closure differs")
    for actual, requested in zip(outputs, copies, strict=True):
        source = requested["source_record"]
        if (actual.get("path") != requested["destination"] or actual.get("exists") is not True
                or type(actual.get("bytes")) is not int or actual["bytes"] != source["bytes"]
                or str(actual.get("sha256", "")).upper() != source["sha256"].upper()
                or actual.get("retention_role") != source["retention_role"]
                or not Path(actual["path"]).is_file() or Path(actual["path"]).stat().st_size != source["bytes"]):
            raise ValueError("materialized payload differs from its requested source identity")
    releases = receipt.get("source_and_destination_releases")
    identities = {str(Path(item["source_record"]["path"]).resolve()): item["source_record"] for item in copies}
    identities.update({row["path"]: row for row in outputs})
    if (not isinstance(releases, list) or len(releases) != len(identities)
            or {row.get("path") for row in releases} != set(identities)
            or any(row.get("write_delete_guarded") is not False
                or row.get("bytes") != identities[row["path"]]["bytes"]
                or str(row.get("sha256", "")).upper() != identities[row["path"]]["sha256"].upper()
                for row in releases)):
        raise ValueError("payload source/destination guard release is incomplete")
    return copy.deepcopy(outputs)


def materialize_payloads(copies: Sequence[Mapping[str, Any]], *, session: RunSession,
                         operation_id: str = "materialize_geometry",
                         limits: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Copy exact original records under GATE; never read large bytes in Python.

    The caller owns producer publication/capacity protection. The private worker
    holds immutable OS source guards through destination byte verification.
    All copy, robocopy and explicit identity-reader children share the existing
    RunSession observed process tree; no completion fact is fabricated here.
    The role is preserved from each caller-declared record, never a suffix guess.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", operation_id):
        raise ValueError("payload operation ID must be an explicit simple identifier")
    selected = _copies(copies, session)
    directory = session.input_dir / ("payload_" + operation_id)
    if directory.exists():
        raise FileExistsError("payload materialization refuses an existing request directory")
    directory.mkdir(parents=True)
    scripts = {}
    for name in ("payload_file_support.ps1", "payload_materialize_owner.ps1"):
        target = session.declare_file(directory / name, "required_evidence")
        freeze_file(resource_path(name), target)
        record = file_record(session.canonical_path(target), "required_evidence")
        session.add_input("payload_" + operation_id + "_" + name, record)
        scripts[name] = target
    request_path = session.declare_file(directory / "request.json", "required_evidence")
    receipt_path = session.declare_file(session.result_dir / (operation_id + "_payload_receipt.json"), "required_evidence")
    if receipt_path.exists():
        raise FileExistsError("payload materialization refuses an existing receipt")
    write_json_atomic(request_path, dict(schema_version=1, python_executable=str(session.context.python_executable),
        copies=selected, receipt_path=str(session.canonical_path(receipt_path))))
    session.add_input("payload_" + operation_id + "_request",
        file_record(session.canonical_path(request_path), "required_evidence"))
    session.run_process(operation_id, executable=session.context.powershell_executable,
        arguments=["-NoProfile", "-File", str(scripts["payload_materialize_owner.ps1"]), "-RequestPath", str(request_path)],
        role="GATE", stage="native_input_materialization", limits=limits)
    observed = [row for row in session.operations if row["operation_id"] == operation_id]
    if (len(observed) != 1 or observed[0]["observation"].get("exit_confirmed") is not True
            or observed[0]["observation"].get("returncode") != 0):
        raise ValueError("payload copy process exit is not confirmed successful")
    return _outputs(json.loads(receipt_path.read_text(encoding="utf-8-sig")), selected)
