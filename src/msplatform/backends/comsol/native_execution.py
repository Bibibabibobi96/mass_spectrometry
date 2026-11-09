"""Shared source materialization and receipt checks for COMSOL operations."""
from __future__ import annotations
import json
from pathlib import Path
from msplatform.execution.inputs import freeze_file
from msplatform.execution.resources import RESOURCE_NAMES, resource_path
from msplatform.io.manifest_records import file_record
from .resources import LAUNCHER_RESOURCES, native_resource_path

def matlab_text(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def freeze_native_sources(session, matlab_resources) -> tuple[Path, list[dict]]:
    root = session.input_dir / "native_sources"
    sources = [(Path(__file__).resolve(), Path("backends/comsol/native_execution.py"))]
    sources.extend((native_resource_path(name), Path("backends/comsol/matlab") / name) for name in matlab_resources)
    sources.extend((native_resource_path(name), Path("backends/comsol/launcher") / name)
                   for name in sorted(LAUNCHER_RESOURCES))
    sources.extend((resource_path(name), Path("execution/resources") / name)
                   for name in sorted(RESOURCE_NAMES) if name.endswith(".ps1"))
    records = []
    for source, relative in sources:
        target = session.declare_file(root / "msplatform" / relative, "required_evidence")
        target.parent.mkdir(parents=True, exist_ok=True)
        freeze_file(source, target)
        record = file_record(target, "required_evidence")
        session.add_input("native_" + relative.as_posix().replace("/", "_").replace(".", "_"), record)
        records.append(record)
    return root / "msplatform/backends/comsol/launcher/run_comsol_r2025b.ps1", records


def require_launcher_completion(path: Path, run_id: str) -> None:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    operations = value.get("operations")
    if (value.get("role") != "comsol_launcher_completion" or value.get("schema_version") != 1
            or value.get("run_id") != run_id or not isinstance(operations, list) or len(operations) != 1):
        raise ValueError("COMSOL launcher completion differs from the one declared attempt")
    observation = operations[0].get("observation", {})
    if (observation.get("exit_confirmed") is not True or observation.get("returncode") != 0
            or type(observation.get("process_id")) is not int or observation["process_id"] <= 0
            or type(observation.get("process_started_at_utc_ticks")) is not int
            or observation["process_started_at_utc_ticks"] <= 0):
        raise ValueError("COMSOL launcher has no successful native exit evidence")
    release = value.get("host_release", {})
    if release.get("error") is not None or (release.get("inherited") is not True
            and release.get("result", {}).get("status") != "released"):
        raise ValueError("COMSOL launcher host release is unconfirmed")


def declare_runtime_files(session, directory: Path, *, bootstrap: Path) -> None:
    # Only the canonical launcher's two explicit storage trees and documented
    # diagnostic filenames are admitted. Other unexpected files fail owner audit.
    for name in ("comsol_tmp", "comsol_recovery"):
        root = directory / name
        if root.is_dir():
            for path in root.rglob("*"):
                if path.is_file():
                    session.declare_file(path, "solver_native_binary")
    diagnostics = [Path(str(bootstrap) + ".launcher.attempt1." + stream + ".log")
                   for stream in ("stdout", "stderr")]
    diagnostics.extend(bootstrap.parent.glob("hs_err_pid*.log"))
    for path in diagnostics:
        if path.is_file():
            session.declare_file(path, "required_evidence")
