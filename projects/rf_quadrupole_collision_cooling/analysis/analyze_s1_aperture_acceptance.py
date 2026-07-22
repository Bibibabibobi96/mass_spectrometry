"""Analyze the solver-free S1 axial aperture/acceptance tradeoff."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import build_interface_handoff as interface


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]
WORKSPACE_ROOT = REPOSITORY_ROOT.parent
DEFAULT_MODE = PROJECT_ROOT / "config" / "modes" / "rf_to_oatof_s1_aperture_precheck.json"
MANIFEST_PROCESS_TIMEOUT_S = 60


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def configured_path(value: str) -> Path:
    path = Path(value)
    root = WORKSPACE_ROOT if path.parts and path.parts[0] == "artifacts" else REPOSITORY_ROOT
    return (root / path).resolve()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def verify_manifest_output(manifest: dict[str, Any], path: Path) -> None:
    target = path.resolve()
    for record in manifest.get("outputs", []):
        if Path(record["path"]).resolve() == target:
            if record.get("sha256") != sha256(target):
                raise ValueError(f"S0 output hash changed: {target}")
            return
    raise ValueError(f"S0 manifest does not record source table: {target}")


def read_axial_offsets(path: Path, center_z_mm: float) -> list[float]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"empty virtual-entry table: {path}")
    return [float(row["position_z_mm"]) - center_z_mm for row in rows]


def run(mode_path: Path, run_id: str, artifact_project_root: Path) -> Path:
    mode = load_json(mode_path)
    stages_path = configured_path(mode["stage_plan"])
    stages = load_json(stages_path)
    if mode.get("stage") != "S1" or stages.get("current_stage") != "S1":
        raise ValueError("S1 precheck is not authorized by the sequential plan")
    claims = mode["claims"]
    prohibited = (
        "final_aperture_design_claim_allowed",
        "three_dimensional_transmission_claim_allowed",
        "joint_field_claim_allowed",
        "physical_link_claim_allowed",
        "formal_asset_modification_allowed",
    )
    if any(claims.get(key) is not False for key in prohibited):
        raise ValueError("S1 aperture precheck exceeds its allowed claim scope")

    contract_path = configured_path(mode["interface_contract"])
    validated = interface.validate_contract(contract_path)
    contract = validated["contract"]
    center_z = float(contract["boundaries"]["target_entry_surface"]["center_mm"][2])
    theory_ceiling = float(validated["entry_aperture_theory_full_width_ceiling_mm"])
    source_manifest_path = configured_path(mode["source_run_manifest"])
    verifier = REPOSITORY_ROOT / "common" / "contracts" / "verify_run_manifest.py"
    subprocess.run(
        [sys.executable, str(verifier), str(source_manifest_path)],
        check=True,
        cwd=REPOSITORY_ROOT,
        timeout=MANIFEST_PROCESS_TIMEOUT_S,
    )
    source_manifest = load_json(source_manifest_path)

    destination = artifact_project_root.resolve() / "runs" / run_id
    if destination.exists():
        raise FileExistsError(destination)
    results_dir = destination / "results"
    results_dir.mkdir(parents=True)
    try:
        frozen = destination / "inputs"
        frozen.mkdir()
        frozen_files = {
            "mode": (mode_path.resolve(), frozen / "mode.json"),
            "stage_plan": (stages_path, frozen / "stage_plan.json"),
            "interface_contract": (contract_path, frozen / "interface_contract.json"),
            "runner": (Path(__file__).resolve(), frozen / "analyze_s1_aperture_acceptance.py.txt"),
            "interface_builder": (
                Path(interface.__file__).resolve(),
                frozen / "build_interface_handoff.py.txt",
            ),
            "entry_aperture_reference": (
                Path(interface.entry_aperture_l0.__file__).resolve(),
                frozen / "entry_aperture_l0.py.txt",
            ),
        }
        inputs: dict[str, str] = {}
        for name, (source, target) in frozen_files.items():
            shutil.copy2(source, target)
            inputs[name] = str(target)
        inputs["source_s0_run_manifest"] = str(source_manifest_path)

        cases: dict[str, Any] = {}
        requested = [float(value) for value in mode["requested_acceptance_fractions"]]
        for case in mode["source_cases"]:
            path = configured_path(case["virtual_entry_events_csv"])
            verify_manifest_output(source_manifest, path)
            inputs[f"{case['case_id']}_virtual_entry_events"] = str(path)
            offsets = read_axial_offsets(path, center_z)
            cases[case["case_id"]] = interface.entry_aperture_l0.axial_acceptance_tradeoff(
                offsets,
                theory_ceiling,
                requested,
            )

        metrics_path = results_dir / "s1_axial_aperture_acceptance_precheck.json"
        metrics = {
            "schema_version": 1,
            "role": "rf_to_oatof_s1_axial_aperture_acceptance_precheck",
            "analysis_status": "PASS",
            "interface_stage_status": "BLOCKED",
            "theoretical_axial_full_height_ceiling_mm": theory_ceiling,
            "final_design_selected": False,
            "minimum_geometric_transmission_frozen": False,
            "physical_link": False,
            "cases": cases,
            "claim_limit": "Best-case axial geometric cut only; a finite 3D port and joint field can only reduce transmission.",
            "remaining_blockers": [
                "minimum geometric transmission per frozen source case",
                "design safety factor and remaining aperture bounds",
                "parameterized three-dimensional shield opening",
                "common potential reference and static joint-field ownership",
            ],
        }
        metrics_path.write_text(
            json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        summary_path = destination / "summary.json"
        summary_path.write_text(json.dumps({
            "schema_version": 1,
            "role": "rf_to_oatof_s1_aperture_precheck_run_summary",
            "status": "success",
            "analysis_status": "PASS",
            "interface_stage_status": "BLOCKED",
            "physical_link": False,
            "result": "results/s1_axial_aperture_acceptance_precheck.json",
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        run_config = destination / "run_config.json"
        run_config.write_text(json.dumps({
            "schema_version": 1,
            "run_id": run_id,
            "project": "rf_quadrupole_collision_cooling",
            "mode": "rf_to_oatof_s1_axial_aperture_acceptance_precheck",
            "project_root": str(REPOSITORY_ROOT),
            "inputs": inputs,
            "parameters": {
                "stage": "S1",
                "solver_rerun": False,
                "theoretical_axial_full_height_ceiling_mm": theory_ceiling,
            },
            "formal_gate_passed": False,
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        writer = REPOSITORY_ROOT / "common" / "contracts" / "write_run_manifest.py"
        subprocess.run([
            sys.executable,
            str(writer),
            "--run-config", str(run_config),
            "--manifest", str(destination / "run_manifest.json"),
            "--status", "success",
            "--software", "Python 3.11 solver-free S1 aperture precheck",
            "--output", str(metrics_path),
            "--output", str(summary_path),
        ], check=True, cwd=REPOSITORY_ROOT, timeout=MANIFEST_PROCESS_TIMEOUT_S)
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
    print(f"RF_TO_OATOF_S1_APERTURE_PRECHECK=PASS RUN={destination.name} STAGE=BLOCKED")


if __name__ == "__main__":
    main()
