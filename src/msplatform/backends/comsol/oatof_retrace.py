"""COMSOL native adapter for one explicit oa-TOF species retrace."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, TYPE_CHECKING

from msplatform.io.manifest_records import file_record, verify_record

if TYPE_CHECKING:
    from msplatform.execution.run_session import RunSession


def load_launcher_completion(path: Path, *, run_id: str) -> dict[str, Any]:
    """Validate the public launcher's actual writer and release facts."""
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or value.get("role") != "comsol_launcher_completion"
            or value.get("run_id") != run_id
            or not isinstance(value.get("operations"), list)
            or not value["operations"] or not isinstance(value.get("host_release"), dict)):
        raise ValueError("COMSOL completion receipt identity differs")
    release = value["host_release"]
    if (release.get("error") is not None
            or (release.get("inherited") is False and (
                not isinstance(release.get("result"), dict)
                or release["result"].get("status") != "released"
                or release["result"].get("token") != release.get("token")))):
        raise ValueError("COMSOL writer or host release remains unknown")
    for operation in value["operations"]:
        observation = operation.get("observation")
        if (not isinstance(observation, dict) or observation.get("exit_confirmed") is not True
                or any(type(observation.get(name)) is not int for name in (
                    "process_id", "process_started_at_utc_ticks"))
                or observation["process_id"] <= 0
                or observation["process_started_at_utc_ticks"] <= 0):
            raise ValueError("COMSOL writer completion is unknown")
    return value


def completion_successful(completion: Mapping[str, Any]) -> bool:
    return all(int(row["observation"]["returncode"]) == 0
               for row in completion["operations"])


def run_species_retrace(
    session: RunSession,
    *,
    operation_id: str,
    run_id: str,
    launcher: Path,
    task_script: Path,
    source_model: Path,
    ion_table: Path,
    output_csv: Path,
    report_path: Path,
    completion_path: Path,
    runtime_dir: Path,
    results_dir: Path,
    scientific_environment: Mapping[str, str],
    limits: Mapping[str, Any],
    immutable_input_records: tuple[Mapping[str, Any], ...],
) -> dict[str, Any]:
    """Run the documented R2025b launcher once for one single-species table."""
    host_context = session.environment["MASS_SPECTROMETRY_HOST_CONTEXT_JSON"]
    arguments = [
        "-NoProfile", "-NonInteractive", "-File", str(launcher),
        "-HostContextJson", host_context,
        "-WorkingDirectory", str(session.run_dir),
        "-TaskScript", str(task_script),
        "-ReportPath", str(report_path),
        "-RunId", run_id,
        "-RunDir", str(session.run_dir),
        "-CompletionPath", str(completion_path),
    ]
    environment = {
        "OATOF_SOURCE_MODEL_PATH": str(source_model),
        "OATOF_ION_TABLE": str(ion_table),
        "OATOF_COMSOL_OUTPUT_CSV": str(output_csv),
        "OATOF_RUNTIME_DIR": str(runtime_dir),
        "OATOF_RESULTS_DIR": str(results_dir),
        **scientific_environment,
    }
    try:
        session.run_process(
            operation_id, executable=session.context.powershell_executable,
            arguments=arguments, role="COMSOL", stage="solver", limits=limits,
            environment=environment, immutable_input_records=immutable_input_records,
        )
    except Exception as primary:
        if completion_path.is_file():
            try:
                load_launcher_completion(completion_path, run_id=run_id)
            except Exception as receipt_error:
                primary.add_note(f"COMSOL completion receipt error: {receipt_error}")
        raise
    completion = load_launcher_completion(completion_path, run_id=run_id)
    return {
        "completion": file_record(completion_path, "required_evidence"),
        "receipt": completion,
    }


def verify_completed_species(
    *, run_id: str, particle_count: int, csv_path: Path,
    report_path: Path, completion_path: Path,
) -> dict[str, Any]:
    """Authenticate the complete native and scientific species unit."""
    completion = load_launcher_completion(completion_path, run_id=run_id)
    records = {
        "completion": file_record(completion_path, "required_evidence"),
        "csv": file_record(csv_path, "required_evidence"),
        "report": file_record(report_path, "required_evidence"),
    }
    for name, record in records.items():
        verify_record(f"COMSOL {name}", record)
    expected = f"DETECTED={particle_count}/{particle_count}"
    if (not completion_successful(completion)
            or expected not in report_path.read_text(encoding="utf-8-sig").splitlines()):
        raise ValueError(f"COMSOL species lacks {expected}")
    return {"receipt": completion, **records}
