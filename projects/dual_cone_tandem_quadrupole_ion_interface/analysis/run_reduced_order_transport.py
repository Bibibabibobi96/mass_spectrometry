"""Run and publish one compact pressure-drag trajectory screening experiment."""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path

import numpy as np

from common.contracts.artifact_naming import validate_run_id
from common.contracts.particle_count_policy import validate_positive_particle_count
from projects.dual_cone_tandem_quadrupole_ion_interface.analysis.reduced_order_transport import (
    PROJECT_ID,
    load_json,
    plot_screening_result,
    simulate,
    summarize,
    write_result_tables,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]
DEFAULT_RESOLVED = PROJECT_ROOT / "config" / "resolved_geometry.json"
DEFAULT_SCIENCE = PROJECT_ROOT / "config" / "science.json"
DEFAULT_NUMERICS = PROJECT_ROOT / "config" / "solver_numerics.json"
DEFAULT_BASELINE = PROJECT_ROOT / "config" / "baseline.json"
PARTICLE_POLICY = REPOSITORY_ROOT / "common" / "contracts" / "particle_count_policy.json"


def _write_json(path: Path, document: dict[str, object]) -> None:
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _manifest_command(
    run_config_path: Path, status: str, outputs: list[Path]
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "common.contracts.write_run_manifest",
        "--run-config",
        str(run_config_path),
        "--status",
        status,
        "--software",
        f"Python {platform.python_version()}; NumPy {np.__version__}",
    ]
    for output in outputs:
        command.extend(("--output", str(output)))
    return command


def _publish_manifest(run_config_path: Path, status: str, outputs: list[Path]) -> None:
    completed = subprocess.run(
        _manifest_command(run_config_path, status, outputs),
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if completed.returncode != 0:
        raise RuntimeError("run manifest publication failed: " + (completed.stdout + completed.stderr).strip())
    manifest = run_config_path.with_name("run_manifest.json")
    verify = subprocess.run(
        [
            sys.executable,
            "-m",
            "common.contracts.verify_run_manifest",
            str(manifest),
            "--require-status",
            status,
            "--require-local-run-config",
            "--require-run-id",
            run_config_path.parent.name,
            "--require-project",
            PROJECT_ID,
            "--require-mode",
            "pressure_drag_screening",
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if verify.returncode != 0:
        raise RuntimeError("run manifest verification failed: " + (verify.stdout + verify.stderr).strip())


def execute(
    output_dir: Path,
    particle_count: int,
    seed: int,
    baseline_path: Path = DEFAULT_BASELINE,
    resolved_path: Path = DEFAULT_RESOLVED,
    science_path: Path = DEFAULT_SCIENCE,
    numerics_path: Path = DEFAULT_NUMERICS,
) -> dict[str, object]:
    """Execute a fresh run directory and publish its terminal manifest."""
    validate_positive_particle_count(particle_count)
    if isinstance(seed, bool) or seed < 0 or seed > 2**63 - 1:
        raise ValueError("seed must be an integer in [0, 2^63-1]")
    output_dir = output_dir.resolve()
    validate_run_id(output_dir.name)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"output run directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    relative_inputs = {
        "baseline": str(baseline_path.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "resolved_geometry": str(resolved_path.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "science": str(science_path.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "solver_numerics": str(numerics_path.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "particle_count_policy": "../../common/contracts/particle_count_policy.json",
        "geometry_resolver": "analysis/resolve_geometry.py",
        "transport_implementation": "analysis/reduced_order_transport.py",
        "run_orchestrator": "analysis/run_reduced_order_transport.py",
        "shared_multipole_geometry": "../../common/multipole/round_rod_geometry.py",
        "shared_multipole_field": "../../common/multipole/ideal_transport.py",
        "shared_multipole_rf_contract": "../../common/multipole/family_contract.py",
        "canonical_particle_state_writer": "../../common/contracts/component_particle_state.py",
    }
    run_config_path = output_dir / "run_config.json"
    run_config = {
        "schema_version": 2,
        "run_id": output_dir.name,
        "project": PROJECT_ID,
        "mode": "pressure_drag_screening",
        "project_root": str(PROJECT_ROOT),
        "inputs": relative_inputs,
        "execution": {
            "particle_count": particle_count,
            "seed": seed,
            "source_prefix_rule": "particle_id_keyed_source_sample",
        },
        "claim_scope": "prototype_geometry_and_transport_trend_screening_only",
        "formal_gate_passed": False,
        "artifact_retention": {"policy_version": 1, "class": "compact", "reason": None},
    }
    _write_json(run_config_path, run_config)
    summary_path = output_dir / "summary.json"
    try:
        resolved = json.loads(resolved_path.read_text(encoding="utf-8-sig"))
        science = load_json(science_path, "pressure_drag_transport_science_contract")
        numerics = load_json(numerics_path, "pressure_drag_transport_solver_numerics")
        result = simulate(particle_count, seed, resolved, science, numerics)
        validation = write_result_tables(output_dir, result, science)
        figure_path = output_dir / "transport__trajectory-projection.png"
        plot_screening_result(figure_path, result, resolved, science)
        metrics = summarize(result, science)
        summary: dict[str, object] = {
            "schema_version": 1,
            "role": "pressure_drag_screening_summary",
            "status": "success",
            "run_id": output_dir.name,
            "project_id": PROJECT_ID,
            "mode": "pressure_drag_screening",
            "claim_scope": "prototype_geometry_and_transport_trend_screening_only",
            "metrics": metrics,
            "component_state_validation": validation,
            "interpretation": (
                "Geometry and RF/drag trend screening only; prescribed pressure/flow and provisional operating point "
                "do not support quantitative instrument transmission claims."
            ),
            "formal_gate_passed": False,
        }
        _write_json(summary_path, summary)
        outputs = [
            summary_path,
            output_dir / "source_particle_state.csv",
            output_dir / "particle_events.csv",
            figure_path,
        ]
        exit_state = output_dir / "exit_particle_state.csv"
        if exit_state.is_file():
            outputs.append(exit_state)
        _publish_manifest(run_config_path, "success", outputs)
        return summary
    except Exception as error:
        failure = {
            "schema_version": 1,
            "role": "pressure_drag_screening_summary",
            "status": "failed",
            "run_id": output_dir.name,
            "project_id": PROJECT_ID,
            "mode": "pressure_drag_screening",
            "failure_stage": "reduced_order_execution_or_publication",
            "error_type": type(error).__name__,
            "error": str(error),
            "formal_gate_passed": False,
        }
        _write_json(summary_path, failure)
        if not (output_dir / "run_manifest.json").is_file():
            _publish_manifest(run_config_path, "failed", [summary_path])
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--particle-count", required=True, type=int)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--resolved", type=Path, default=DEFAULT_RESOLVED)
    parser.add_argument("--science", type=Path, default=DEFAULT_SCIENCE)
    parser.add_argument("--numerics", type=Path, default=DEFAULT_NUMERICS)
    arguments = parser.parse_args()
    summary = execute(
        arguments.output_dir,
        arguments.particle_count,
        arguments.seed,
        arguments.baseline,
        arguments.resolved,
        arguments.science,
        arguments.numerics,
    )
    print(
        "PRESSURE_DRAG_SCREENING=PASS "
        f"N={summary['metrics']['particle_count']} "
        f"TRANSMITTED={summary['metrics']['transmitted_count']} "
        f"RUN={summary['run_id']}"
    )


if __name__ == "__main__":
    main()
