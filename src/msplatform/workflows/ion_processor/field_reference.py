"""Bind an existing IP producer family by its explicit consumed-record projection.

Metadata preparation is not native-use authorization: the existing launcher must
hold immutable source guards before any PA consumer. No PA family is copied here.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from msplatform.io.file_identity import file_sha256
from msplatform.io.manifest_records import record_path
from msplatform.workflows.ion_processor import preparation

PROJECT = "dual_pressure_rectilinear_ion_processor"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def bind_native_field(run: Path, config: dict, parent: Path) -> dict:
    """Bind the owner's field records; the launcher verifies and guards payloads.

    This preparation projection checks small source evidence and exact member
    metadata. It does not authorize native use: run_functional must acquire the
    public immutable-source guards before starting any source-field consumer.
    """
    run = run.resolve()
    inputs, solver = run/"inputs", run/"simion"
    parent = parent.resolve()
    manifest_path = parent/"run_manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("project") != PROJECT or manifest.get("status") not in {"success", "failed"}:
        raise ValueError("native field source must be an explicit terminal project run")
    parent_config = read_json(parent/"inputs/resolved_model.json")
    if parent_config["native_projection"] != config["native_projection"] or parent_config["numerics"]["refine_convergence_v"] != config["numerics"]["refine_convergence_v"]:
        raise ValueError("native field geometry/grid/refine identity differs")
    if file_sha256(parent/"simion/processor.gem") != file_sha256(solver/"processor.gem"):
        raise ValueError("native GEM identity differs")
    if "Fast adjust Refining completed" not in (parent/"logs/refine.log").read_text(encoding="utf-8-sig"):
        raise ValueError("native field source lacks completed Refine evidence")
    family = [parent/"simion"/("processor.pa"+suffix) for suffix in ["#", *map(str, range(16)), "-surf"]]
    arguments = [sys.executable, "-c", "from msplatform.execution.manifest_verification import main; from msplatform.backends.simion.native_completion import retention_api; main(retention_api=retention_api)", str(manifest_path), "--require-project", PROJECT, "--require-status", manifest["status"], "--consumer-projection-id", "ion_processor_native_field_v1"]
    required_inputs = {(parent/relative).resolve() for relative in
                       ("simion/processor.gem", "inputs/numerics.json", "inputs/resolved_model.json")}
    selected_inputs = set()
    for key, record in manifest["inputs"].items():
        if record_path(record, base_dir=parent) in required_inputs:
            selected_inputs.add(record_path(record, base_dir=parent))
            arguments.extend(["--consumed-input", key, str(record_path(record, base_dir=parent))])
    if selected_inputs != required_inputs:
        raise ValueError("native field source does not bind its frozen geometry/numerics")
    records = []
    for path in family:
        matches = [record for record in manifest["outputs"] if record_path(record, base_dir=parent) == path.resolve()]
        if len(matches) != 1:
            raise ValueError("native field manifest does not uniquely bind its family")
        record = matches[0]
        digest = record.get("sha256")
        if (record.get("exists") is not True or not isinstance(record.get("bytes"), int)
                or isinstance(record["bytes"], bool) or record["bytes"] < 0
                or not isinstance(digest, str) or re.fullmatch(r"[A-Fa-f0-9]{64}", digest) is None
                or not path.is_file() or path.stat().st_size != record["bytes"]):
            raise ValueError("native field member metadata differs from its owner")
        records.append(dict(path=str(path.resolve()), bytes=record["bytes"], sha256=digest.upper()))
    for path in [parent/"logs/refine.log"]:
        arguments.extend(["--consumed-output", str(path)])
    verification = subprocess.run(arguments, cwd=run, timeout=120, capture_output=True, text=True, encoding="utf-8", check=True)
    config["native_field"] = {"directory": str(parent/"simion"), "source_manifest": str(manifest_path), "source_manifest_sha256": file_sha256(manifest_path), "consumer_projection_id": "ion_processor_native_field_v1"}
    write_json(inputs/"native_field_consumption.json", {**config["native_field"], "verification": verification.stdout,
        "payload_validation": "launcher_immutable_source_guard_required_before_native_use", "family_records": records})
    # The source owner retains its PA byte authority. The child binds that
    # small manifest and this consumption projection, rather than publishing
    # the same external PA payloads again as if they were child-owned inputs.
    return {"native_field_manifest": str(manifest_path),
            "native_field_consumption": str(inputs/"native_field_consumption.json")}


def adopt_native_field(run: Path, parent: Path) -> None:
    """Bind the previous field after partial classification and before any Fly."""
    config = read_json(run/"inputs/resolved_model.json")
    external = bind_native_field(run, config, parent)
    write_json(run/"inputs/resolved_model.json", config)
    (run/"simion/frozen_config.lua").write_text("return " + preparation.lua_literal(config) + "\n", encoding="utf-8")
    run_config = read_json(run/"run_config.json")
    run_config["inputs"].update(external)
    run_config["inputs"]["native_field_consumption"] = str(run/"inputs/native_field_consumption.json")
    write_json(run/"run_config.json", run_config)
