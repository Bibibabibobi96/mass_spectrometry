"""Run the solver-free S0 RF-to-oaTOF direct-boundary reference."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import build_interface_handoff as interface


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]
WORKSPACE_ROOT = REPOSITORY_ROOT.parent
DEFAULT_MODE = PROJECT_ROOT / "config" / "modes" / "rf_to_oatof_s0_reference.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def configured_path(value: str) -> Path:
    path = Path(value)
    root = WORKSPACE_ROOT if path.parts and path.parts[0] == "artifacts" else REPOSITORY_ROOT
    return (root / path).resolve()


def case_metrics(
    source_rows: list[dict[str, Any]],
    target_rows: list[dict[str, Any]],
    target_origin_mm: list[float],
) -> dict[str, Any]:
    if len(source_rows) != len(target_rows):
        raise ValueError("S0 mapping is not lossless")
    ids = [int(row["particle_id"]) for row in target_rows]
    if len(ids) != len(set(ids)) or ids != sorted(ids):
        raise ValueError("S0 particle identities are not unique and sorted")
    clock_fields = (
        "instrument_time_us", "lineage_birth_time_us", "particle_birth_time_us"
    )
    maximum_clock_residual = max(
        abs(float(after[field]) - float(before[field]))
        for before, after in zip(source_rows, target_rows)
        for field in clock_fields
    )
    maximum_plane_residual = max(
        abs(float(row["position_x_mm"]) - float(target_origin_mm[0]))
        for row in target_rows
    )
    minimum_normal_velocity = min(float(row["velocity_x_m_s"]) for row in target_rows)
    radial_squared = [
        (float(row["position_y_mm"]) - float(target_origin_mm[1])) ** 2
        + (float(row["position_z_mm"]) - float(target_origin_mm[2])) ** 2
        for row in target_rows
    ]
    return {
        "source_particles": len(source_rows),
        "virtual_entry_particles": len(target_rows),
        "losses": len(source_rows) - len(target_rows),
        "maximum_target_plane_residual_mm": maximum_plane_residual,
        "maximum_clock_value_residual_us": maximum_clock_residual,
        "minimum_target_normal_velocity_m_s": minimum_normal_velocity,
        "mean_instrument_time_us": sum(
            float(row["instrument_time_us"]) for row in target_rows
        ) / len(target_rows),
        "rms_virtual_entry_offset_mm": math.sqrt(sum(radial_squared) / len(radial_squared)),
    }


def run(mode_path: Path, run_id: str, artifact_project_root: Path) -> Path:
    mode = load_json(mode_path)
    stages = load_json(configured_path(mode["stage_plan"]))
    s0 = stages["stages"][0]
    if (
        mode.get("stage") != "S0"
        or s0.get("id") != "S0"
        or s0.get("status") not in {"ready_for_lightweight_test", "passed"}
        or stages.get("current_stage") not in {"S0", "S1"}
    ):
        raise ValueError("S0 runner is not authorized by the sequential interface plan")
    if mode["claims"].get("physical_link_claim_allowed") is not False:
        raise ValueError("S0 must prohibit a physical-link claim")
    contract_path = configured_path(mode["interface_contract"])
    validated = interface.validate_contract(contract_path)
    contract = validated["contract"]
    source_origin = [
        0.0, 0.0, float(contract["boundaries"]["source_exit_surface"]["z_mm"])
    ]
    target_origin = contract["boundaries"]["target_entry_surface"]["center_mm"]
    destination = artifact_project_root.resolve() / "runs" / run_id
    if destination.exists():
        raise FileExistsError(destination)
    results = destination / "results"
    results.mkdir(parents=True)
    try:
        frozen_inputs = destination / "inputs"
        frozen_inputs.mkdir()
        frozen_mode = frozen_inputs / "mode.json"
        frozen_stages = frozen_inputs / "stage_plan.json"
        frozen_contract = frozen_inputs / "interface_contract.json"
        frozen_runner = frozen_inputs / "run_interface_s0_reference.py.txt"
        frozen_builder = frozen_inputs / "build_interface_handoff.py.txt"
        frozen_legacy_builder = frozen_inputs / "build_oatof_handoff.py.txt"
        frozen_aperture = frozen_inputs / "entry_aperture_l0.py.txt"
        shutil.copy2(mode_path.resolve(), frozen_mode)
        shutil.copy2(configured_path(mode["stage_plan"]), frozen_stages)
        shutil.copy2(contract_path, frozen_contract)
        shutil.copy2(Path(__file__).resolve(), frozen_runner)
        shutil.copy2(Path(interface.__file__).resolve(), frozen_builder)
        shutil.copy2(Path(interface.legacy.__file__).resolve(), frozen_legacy_builder)
        shutil.copy2(Path(interface.entry_aperture_l0.__file__).resolve(), frozen_aperture)
        inputs: dict[str, str] = {
            "mode": str(frozen_mode),
            "stage_plan": str(frozen_stages),
            "interface_contract": str(frozen_contract),
            "runner": str(frozen_runner),
            "interface_builder": str(frozen_builder),
            "legacy_handoff_builder": str(frozen_legacy_builder),
            "entry_aperture_reference": str(frozen_aperture),
        }
        outputs: list[Path] = []
        all_metrics: dict[str, Any] = {}
        for case in mode["source_cases"]:
            source_csv = configured_path(case["particle_state_csv"])
            source_manifest = configured_path(case["run_manifest"])
            inputs[f"{case['case_id']}_particle_state"] = str(source_csv)
            inputs[f"{case['case_id']}_run_manifest"] = str(source_manifest)
            source_validation = interface.validate_source_without_writing(
                source_csv, source_manifest, contract_path
            )
            source_rows = interface.legacy.read_handoff_rows(source_csv, contract)
            source_events, _ = interface.convert_source_rows(source_rows, contract)
            virtual_rows = interface.build_virtual_entry_rows(
                source_events,
                contract,
                source_origin,
                mode["rotation_source_to_target"],
            )
            output = results / f"{case['case_id']}__virtual_entry_events.csv"
            interface._write_csv(output, virtual_rows)
            outputs.append(output)
            metrics = case_metrics(source_events, virtual_rows, target_origin)
            metrics["upstream_solver"] = case["upstream_solver"]
            metrics["source_validation"] = source_validation
            all_metrics[case["case_id"]] = metrics

        acceptance = mode["acceptance"]
        failures: list[str] = []
        for case_id, metrics in all_metrics.items():
            if metrics["virtual_entry_particles"] != int(acceptance["required_particles_per_case"]):
                failures.append(f"{case_id}: particle count")
            if metrics["losses"] != 0:
                failures.append(f"{case_id}: mapping loss")
            if metrics["maximum_target_plane_residual_mm"] > float(
                acceptance["maximum_target_plane_residual_mm"]
            ):
                failures.append(f"{case_id}: plane residual")
            if metrics["minimum_target_normal_velocity_m_s"] <= 0:
                failures.append(f"{case_id}: non-forward velocity")
            if metrics["maximum_clock_value_residual_us"] != 0:
                failures.append(f"{case_id}: clock mutation")
        status = "PASS" if not failures else "FAIL"
        metrics_path = results / "s0_direct_boundary_metrics.json"
        metrics_path.write_text(json.dumps({
            "schema_version": 1,
            "role": "rf_to_oatof_s0_direct_boundary_metrics",
            "stage": "S0",
            "status": status,
            "physical_link": False,
            "field_transport": False,
            "aperture_clipping_applied": False,
            "target_surface_status": contract["boundaries"]["target_entry_surface"]["status"],
            "cases": all_metrics,
            "failures": failures,
            "claim_limit": "Solver-free coordinate/time data-path reference only; the oaTOF shield remains closed.",
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        outputs.append(metrics_path)
        run_config = destination / "run_config.json"
        run_config.write_text(json.dumps({
            "schema_version": 1,
            "run_id": run_id,
            "project": "rf_quadrupole_collision_cooling",
            "mode": "rf_to_oatof_s0_direct_boundary_reference",
            "project_root": str(REPOSITORY_ROOT),
            "inputs": inputs,
            "parameters": {"stage": "S0", "solver_rerun": False},
            "formal_gate_passed": False,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        summary = destination / "summary.json"
        summary.write_text(json.dumps({
            "schema_version": 1,
            "role": "rf_to_oatof_s0_run_summary",
            "status": "success" if status == "PASS" else "failed",
            "stage_gate": status,
            "physical_link": False,
            "particles_per_case": int(acceptance["required_particles_per_case"]),
            "result": "results/s0_direct_boundary_metrics.json",
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        outputs.append(summary)
        writer = REPOSITORY_ROOT / "common" / "contracts" / "write_run_manifest.py"
        command = [
            sys.executable, str(writer), "--run-config", str(run_config),
            "--manifest", str(destination / "run_manifest.json"),
            "--status", "success" if status == "PASS" else "failed",
            "--software", "Python 3.11 solver-free S0 reference",
        ]
        for output in outputs:
            command.extend(("--output", str(output)))
        subprocess.run(command, check=True)
        if failures:
            raise RuntimeError("S0 gate failed: " + ", ".join(failures))
        return destination
    except Exception:
        if not (destination / "run_manifest.json").exists():
            shutil.rmtree(destination, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", type=Path, default=DEFAULT_MODE)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--artifact-project-root",
        type=Path,
        default=WORKSPACE_ROOT / "artifacts" / "projects" / "rf_quadrupole_collision_cooling",
    )
    args = parser.parse_args()
    destination = run(args.mode, args.run_id, args.artifact_project_root)
    print(f"RF_TO_OATOF_S0=PASS RUN={destination.name} PHYSICAL_LINK=false")


if __name__ == "__main__":
    main()
