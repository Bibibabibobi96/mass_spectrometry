"""One mixed-species SIMION Fly over an explicitly staged Formal IOB."""
from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any, Mapping, Sequence, TYPE_CHECKING

from msplatform.backends.simion.detector_census import analyze_simion_log
from msplatform.backends.simion.formal_runtime import stage_verified_simion_runtime
from msplatform.io.manifest_records import file_record

if TYPE_CHECKING:
    from msplatform.execution.run_session import RunSession


def run_mixed_species_fly(
    session: RunSession,
    *,
    operation_id: str,
    simion_executable: Path,
    artifact_project_root: Path,
    project_id: str,
    combined_ion: Path,
    total_particles: int,
    max_tof_us: float,
    output_csv: Path,
    summary_path: Path,
    runtime_receipt: Path,
    limits: Mapping[str, Any],
    immutable_input_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Stage, fly, census, and remove only this run's verified private copy."""
    runtime = session.run_dir / "formal_simion_runtime"
    receipt, staged = stage_verified_simion_runtime(
        artifact_project_root=artifact_project_root, destination=runtime,
        receipt=runtime_receipt, project_id=project_id,
    )
    session.add_input("formal_simion_runtime_receipt", file_record(runtime_receipt, "required_evidence"))
    for path in staged:
        session.declare_file(path, "solver_native_binary")
    iob = runtime / "oatof_ideal_grounded.iob"
    stdout = session.declare_file(session.log_dir / "simion_stdout.log", "required_evidence")
    # RunSession owns the native stdout/stderr transport. This compatibility
    # name is a deterministic copy only after the writer has stopped.
    try:
        arguments = [
            "--default-num-particles", str(total_particles), "--nogui", "fly",
            "--trajectory-quality", "8", "--retain-trajectories", "0",
            "--particles", str(combined_ion), "--programs", "1",
            "--adjustable", "trajectory_quality=8",
            "--adjustable", "trajectory_log_enable=1",
            "--adjustable", f"diagnostic_max_tof_us={max_tof_us:g}", str(iob),
        ]
        observed = session.run_process(
            operation_id, executable=simion_executable, arguments=arguments,
            role="SIMION", stage="flight", limits=limits,
            immutable_input_records=immutable_input_records,
        )
        if observed["observation"]["exit_code"] != 0:
            raise RuntimeError("SIMION mixed-species fly failed")
        process_record = session.log_dir / (
            f"operation_{session.expected_operation_ids.index(operation_id) + 1:04d}.stdout.log"
        )
        shutil.copyfile(process_record, stdout)
        frame, summary = analyze_simion_log(
            stdout, combined_ion, mode="mass_spectrum_candidate",
            distribution="five_species_shared_source", detector_radius_mm=40.0,
            allow_incomplete_census=False,
        )
        if int(summary["Hit"]) != total_particles:
            raise ValueError(
                f"SIMION detected {summary['Hit']}/{total_particles} mixed-species ions"
            )
        frame.to_csv(output_csv, index=False)
        import json
        summary_path.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n",
                                encoding="utf-8")
        return {"receipt": receipt, "summary": summary}
    finally:
        if session.writers_stopped and runtime.exists():
            shutil.rmtree(runtime)
