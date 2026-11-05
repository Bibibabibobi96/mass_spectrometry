"""Owned STEP export action and installed worker; no process or lifecycle owner."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from msplatform.execution.manifest_records import file_record, verify_record

WORKER_CODE = "from msplatform.exporters.execution import export_worker;import sys;export_worker(sys.argv[1])"
_REQUEST_FIELDS = {"schema_version", "role", "snapshot_record", "options_record", "representation",
                   "run_directory", "step_path", "report_path"}


def _write_new(path: Path, value: Mapping) -> None:
    encoded = json.dumps(dict(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(encoded)


def _inside(path, root: Path) -> Path:
    value = Path(path)
    if not value.is_absolute() or not value.resolve().is_relative_to(root):
        raise ValueError("CAD path escapes its owned run")
    return value.resolve()


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def export_worker(path: str | Path) -> None:
    """Consume the frozen request using installed imports; no solver/GUI/source."""
    from msplatform.exporters.step import export_assembly_step

    path = Path(path).resolve()
    request = _read(path)
    if (not isinstance(request, dict) or set(request) != _REQUEST_FIELDS
            or type(request["schema_version"]) is not int or request["schema_version"] != 1
            or request["role"] != "assembly_step_export_request"):
        raise ValueError("unsupported CAD worker request")
    root = Path(request["run_directory"])
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("CAD request requires its existing owned run")
    root = root.resolve()
    _inside(path, root)
    if path != root / "inputs/cad_export_request.json":
        raise ValueError("CAD request does not belong to its original run inputs")
    step, report = (_inside(request[name], root) for name in ("step_path", "report_path"))
    if step != root / "results/assembly.step" or report != root / "results/cad_export_report.json":
        raise ValueError("CAD output differs from its owned destination")
    inputs = []
    for name in ("snapshot_record", "options_record"):
        record = request[name]
        if not isinstance(record, dict):
            raise ValueError("CAD request input record is missing")
        input_path = _inside(record["path"], root)
        verify_record(name, record)
        inputs.append(input_path)
    if len({path, step, report, *inputs}) != 5 or step.exists() or report.exists():
        raise FileExistsError("CAD export refuses existing or overlapping destinations")
    snapshot, options = map(_read, inputs)
    projection = export_assembly_step(snapshot, destination=step,
        representation=request["representation"], options=options)
    if not step.is_file() or step.stat().st_size == 0:
        raise FileNotFoundError("CAD exporter produced no STEP")
    _write_new(report, dict(schema_version=1, role="owned_assembly_step_export",
        snapshot_record=request["snapshot_record"], options_record=request["options_record"],
        step_record=file_record(step, "solver_native_binary"), projection=projection))
    print("ASSEMBLY_STEP_EXPORT=PASS", flush=True)


def execute_cad_export(session, *, snapshot: Mapping, representation: str,
                       options: Mapping, limits: Mapping) -> dict:
    """Freeze one complete snapshot and delegate transport to the real RunSession."""
    if session.expected_operation_ids != ("export_step",):
        raise ValueError("CAD action requires exactly its admitted export_step operation")
    root = session.artifact_run_dir.resolve()

    def owned(path: Path, role: str) -> Path:
        target = session.canonical_path(path)
        _inside(target, root)
        session.declare_file(target, role)
        return target

    assembly = owned(session.input_dir / "cad_assembly.json", "required_evidence")
    option_path = owned(session.input_dir / "cad_options.json", "required_evidence")
    request_path = owned(session.input_dir / "cad_export_request.json", "required_evidence")
    step = owned(session.result_dir / "assembly.step", "solver_native_binary")
    report = owned(session.result_dir / "cad_export_report.json", "required_evidence")
    if any(path.exists() for path in (assembly, option_path, request_path, step, report)):
        raise FileExistsError("CAD action refuses existing inputs or outputs")
    _write_new(assembly, snapshot)
    _write_new(option_path, options)
    records = {"assembly_snapshot": file_record(assembly, "required_evidence"),
               "export_options": file_record(option_path, "required_evidence")}
    _write_new(request_path, dict(schema_version=1, role="assembly_step_export_request",
        snapshot_record=records["assembly_snapshot"], options_record=records["export_options"],
        representation=representation, run_directory=str(root), step_path=str(step), report_path=str(report)))
    records["export_request"] = file_record(request_path, "required_evidence")
    for name, record in records.items():
        session.add_input("cad_" + name, record)
    session.run_process("export_step", executable=session.context.python_executable,
        arguments=["-c", WORKER_CODE, str(request_path)], role="GATE", stage="cad_export", limits=limits)
    for name, record in records.items():
        verify_record(name, record)
    stdout = session.log_dir / "operation_0001.stdout.log"
    if b"ASSEMBLY_STEP_EXPORT=PASS" not in stdout.read_bytes().splitlines():
        raise ValueError("CAD export completion marker is missing")
    if not step.is_file() or step.stat().st_size == 0 or not report.is_file():
        raise FileNotFoundError("CAD action is missing its actual STEP or report")
    value = _read(report)
    if (not isinstance(value, dict) or set(value) != {"schema_version", "role", "snapshot_record",
            "options_record", "step_record", "projection"}
            or type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["role"] != "owned_assembly_step_export"
            or value["snapshot_record"] != records["assembly_snapshot"]
            or value["options_record"] != records["export_options"]):
        raise ValueError("CAD export report differs from the frozen request")
    if value["step_record"].get("path") != str(step):
        raise ValueError("CAD report STEP path differs from its owned destination")
    verify_record("CAD STEP", value["step_record"])
    projection = value["projection"]
    if (type(projection.get("schema_version")) is not int or projection["schema_version"] != 1
            or projection.get("role") != "assembly_step_projection"
            or projection.get("representation") != representation or projection.get("options") != dict(options)
            or projection.get("length_unit") != "mm" or Path(projection.get("step_path", "")).resolve() != step):
        raise ValueError("CAD projection report differs from its requested export")
    records.update(step=file_record(step, "solver_native_binary"), report=file_record(report, "required_evidence"))
    metadata = dict(representation=representation, length_unit="mm", source_status="not_requested",
        field_status="not_solved", refine_calls=0, fly_calls=0, gui_calls=0,
        scientific_qualification="not_granted")
    return dict(status="success", summary=metadata, output_paths=[str(step), str(report)],
        required_output_paths=[str(step), str(report)], retention_preserve_paths=[],
        manifest_extra_fields={"products": {"cad_geometry": dict(schema_version=1,
            kind="cad_geometry", status="complete", metadata=metadata, data=records)}})


class _NoParticleBatchCompletion:
    @staticmethod
    def recoverable_batch_log_kind(path):
        return None

    @staticmethod
    def has_recoverable_batch_completion(path):
        return False

    @staticmethod
    def recoverable_batch_logs(run_dir):
        logs = Path(run_dir) / "logs"
        if logs.is_dir() and any(path.is_file() and
                (path.match("simion__batch*.trace.log") or path.match("simion__batch*.stdout.log"))
                for path in logs.iterdir()):
            raise ValueError("CAD-only action contains unexpected particle batch evidence")
        return set()


def no_particle_batch_completion_api():
    """Explicit CAD retention policy: partial STEP never grants TRACE recovery."""
    return _NoParticleBatchCompletion
