"""Compile the frozen 300 mm, 4 mm ideal result into an exploration Candidate.

The input is a selected result already published by the ideal-field acceptance
run.  This module performs no search and deliberately produces only a
``CANDIDATE_ONLY`` artifact: the eventual three-dimensional field is a new
test, not evidence inherited from the one-dimensional calculation.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.optimize import root

from common.contracts.artifact_naming import validate_run_id
from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import load_json, validate_schema
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_acceptance_theory import (
    axial_time_coefficients,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.ideal_source_comparison import (
    IdealWorkingPoint,
    NumericalSourceSpec,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.three_zone_ideal_theory import (
    InnerSolution,
    OuterGeometry,
    ReflectronGeometry,
    derive_three_zone_state,
)


OUTPUT_SCHEMA = "oatof_three_zone_simion_candidate_resolved.schema.json"
PROJECT_ID = "single_reflection_oa_tof_mass_analyzer"
PUBLISH_MODE = "ideal_acceptance_300mm_simion_candidate_compile"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKSPACE_ROOT = REPOSITORY_ROOT.parent
CANDIDATE_NAME = "ideal_acceptance_300mm_simion_candidate_resolved.json"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _record(path: Path, *, label: str) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"{label} is missing: {resolved}")
    return {
        "path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": file_sha256(resolved),
    }


def _workspace_relative(path: Path, workspace_root: Path, *, label: str) -> str:
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError as error:
        raise ValueError(f"{label} must be inside the workspace") from error


def _write_exclusive_json(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2)
        stream.write("\n")


def _manifest_contains(manifest: dict[str, Any], path: Path) -> bool:
    """Return whether a manifest output records this exact immutable file."""

    for record in manifest.get("outputs", []):
        if not isinstance(record, dict) or "path" not in record:
            continue
        try:
            recorded_path = Path(str(record["path"])).resolve()
        except OSError:
            continue
        if recorded_path == path.resolve() and record.get("sha256") == file_sha256(path):
            return True
    return False


def _number(value: Any, *, label: str, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0.0):
        raise ValueError(f"{label} must be {'positive ' if positive else ''}finite")
    return result


def compile_ideal_acceptance_300mm_candidate(
    configuration_path: Path, run_manifest_path: Path, selected_result_path: Path,
    *, total_length_mm: float = 300.0,
) -> dict[str, Any]:
    """Return a hash-bound 250 mm or 300 mm / 4 mm ideal-field Candidate.

    The result is accepted only when the frozen selection independently passed
    both its population and particle checks.  It is still not a real-field
    validation or an assertion that either square or cylindrical hardware has
    the same axial field.
    """

    configuration = _load(configuration_path)
    manifest = _load(run_manifest_path)
    selected = _load(selected_result_path)
    if (
        configuration.get("role") != "ideal_acceptance_theory"
        or _number(configuration.get("design", {}).get("total_acceleration_length_mm"), label="total acceleration length") != total_length_mm
        or manifest.get("status") != "success"
        or manifest.get("project") != "single_reflection_oa_tof_mass_analyzer"
        or selected.get("full_width_mm") != 4
        or selected.get("theoretical_population_pass") is not True
        or selected.get("independent_particle_pass") is not True
        or not _manifest_contains(manifest, selected_result_path)
    ):
        raise ValueError(f"{total_length_mm:g} mm ideal-acceptance evidence is not a frozen 4 mm pass")
    point = selected.get("point")
    if not isinstance(point, dict):
        raise ValueError("selected ideal-acceptance point is missing")
    state = point.get("state")
    inner = point.get("inner")
    source_point = point.get("design_source")
    if not all(isinstance(value, dict) for value in (state, inner, source_point)):
        raise ValueError("selected ideal-acceptance state is incomplete")
    project_root = Path(__file__).resolve().parents[1]
    reference_path = (project_root / str(configuration.get("reference_config"))).resolve()
    reference = _load(reference_path)
    reference_source = reference.get("source")
    reference_outer = reference.get("outer")
    if not isinstance(reference_source, dict) or not isinstance(reference_outer, dict):
        raise ValueError("ideal-acceptance reference source is incomplete")
    d1 = _number(state.get("zone1_length_mm"), label="zone1 length", positive=True)
    d2 = _number(state.get("zone2_length_mm"), label="zone2 length", positive=True)
    d3 = _number(state.get("zone3_length_mm"), label="zone3 length", positive=True)
    if not math.isclose(d1 + d2 + d3, total_length_mm, rel_tol=0.0, abs_tol=1e-6):
        raise ValueError(f"selected ideal-acceptance lengths do not sum to {total_length_mm:g} mm")
    focus = _number(point.get("focus_drift_mm"), label="focus drift", positive=True)
    exit_z = -focus
    intermediate2_z = exit_z - d3
    intermediate1_z = intermediate2_z - d2
    repeller_z = intermediate1_z - d1
    source = {
        "mass_to_charge_th": _number(reference_source.get("mass_to_charge_th"), label="source mass", positive=True),
        "charge_sign": 1,
        "center_x_mm": _number(source_point.get("center_x_mm"), label="source center", positive=True),
        "center_velocity_m_per_s": _number(reference_source.get("center_velocity_m_per_s"), label="source velocity"),
        "velocity_slope_m_per_s_per_mm": _number(reference_source.get("velocity_slope_m_per_s_per_mm"), label="source slope"),
        "nominal_energy_per_charge_v": _number(reference_outer.get("nominal_energy_per_charge_v"), label="source energy", positive=True),
    }
    if source["center_x_mm"] >= d1:
        raise ValueError("selected source center is outside the first accelerator zone")
    result = {
        "schema_version": 1,
        "role": "oatof_three_zone_simion_candidate_resolved",
        "project_id": "single_reflection_oa_tof_mass_analyzer",
        "qualification": "CANDIDATE_ONLY",
        "compiler_mode": f"IDEAL_ACCEPTANCE_{int(total_length_mm)}MM_SELECTED_POINT_V1",
        "campaign": {"campaign_id": f"ideal_acceptance_{int(total_length_mm)}mm", "file": _record(configuration_path, label="configuration")},
        "ideal_acceptance_evidence": {
            "configuration": _record(configuration_path, label="configuration"),
            "run_manifest": _record(run_manifest_path, label="run manifest"),
            "selected_result": _record(selected_result_path, label="selected result"),
            "selected_design_id": str(selected.get("design_id")),
            "full_width_mm": 4.0,
            "total_acceleration_length_mm": total_length_mm,
        },
        "source_identity": {
            "authority": "ideal_acceptance.selected_point",
            "campaign_id": f"ideal_acceptance_{int(total_length_mm)}mm",
            "campaign_sha256": file_sha256(configuration_path),
            "frozen_source": source,
        },
        "identities": {
            "topology_id": "three_zone_accelerator_ideal_v1",
            "geometry_id": "three_zone_focus_origin_planes_v1",
            "field_id": "three_zone_piecewise_uniform_ideal_field_v1",
        },
        "accelerator_topology": {
            "topology_id": "three_zone_accelerator_ideal_v1",
            "planes_global_z_mm": {"repeller": repeller_z, "intermediate1": intermediate1_z, "intermediate2": intermediate2_z, "exit": exit_z},
            "potentials_v": {
                "repeller": _number(state.get("repeller_v"), label="repeller potential"),
                "intermediate1": _number(state.get("grid1_v"), label="grid1 potential"),
                "intermediate2": _number(state.get("grid2_v"), label="grid2 potential"),
                "exit": _number(state.get("exit_v"), label="exit potential"),
            },
        },
        "accelerator_physics": {
            "lengths_mm": {"d1": d1, "d2": d2, "d3": d3},
            "fields_v_per_mm": {
                "e1": _number(state.get("field1_v_per_mm"), label="field1", positive=True),
                "e2": _number(state.get("field2_v_per_mm"), label="field2", positive=True),
                "e3": _number(state.get("field3_v_per_mm"), label="field3", positive=True),
            },
            "focus_drift_after_exit_mm": focus,
        },
        "reflectron": {
            "u_r1_v": _number(inner.get("stage1_voltage_drop_v"), label="reflectron stage1", positive=True),
            "f_r2_v_per_mm": _number(inner.get("stage2_field_v_per_mm"), label="reflectron stage2", positive=True),
        },
        "claim_limit": f"Exploration-only {total_length_mm:g} mm ideal-field selected point. Square and cylindrical real fields, collection, numerical convergence, and Formal qualification remain unverified.",
    }
    validate_schema(result, OUTPUT_SCHEMA)
    return result


def _nearest_grid(value: float, grid: float) -> float:
    """Return a deterministic nearest positive grid multiple."""

    if grid <= 0.0 or not math.isfinite(grid):
        raise ValueError("axial numerical grid must be positive and finite")
    return round(value / grid) * grid


def compile_grid_realized_ideal_acceptance_300mm_candidate(
    configuration_path: Path, run_manifest_path: Path, selected_result_path: Path,
    *, axial_grid_z_mm: float, total_length_mm: float = 300.0,
) -> dict[str, Any]:
    """Re-close the ideal equations after making the three planes grid-realizable.

    The selected 300 mm result has a continuous zone boundary.  A local PA
    cannot place that boundary between its fine-grid rows.  This routine holds
    the selected first-zone/source contract and 300 mm total length fixed,
    snaps the two downstream zone lengths to the declared fine axial grid, and
    solves the same a1=a2=a3 equations again.  It does *not* represent a 3-D
    field validation or a new global design search.
    """

    base = compile_ideal_acceptance_300mm_candidate(
        configuration_path, run_manifest_path, selected_result_path, total_length_mm=total_length_mm
    )
    configuration = _load(configuration_path)
    reference_path = (
        Path(__file__).resolve().parents[1]
        / str(configuration["reference_config"])
    ).resolve()
    reference = _load(reference_path)
    source_values = base["source_identity"]["frozen_source"]
    source = NumericalSourceSpec(
        mass_to_charge_th=float(source_values["mass_to_charge_th"]),
        center_x_mm=float(source_values["center_x_mm"]),
        center_velocity_m_per_s=float(source_values["center_velocity_m_per_s"]),
        velocity_slope_m_per_s_per_mm=float(
            source_values["velocity_slope_m_per_s_per_mm"]
        ),
    )
    affine = source.affine()
    original_lengths = base["accelerator_physics"]["lengths_mm"]
    d1 = _nearest_grid(float(original_lengths["d1"]), axial_grid_z_mm)
    downstream = _nearest_grid(
        float(original_lengths["d2"]) + float(original_lengths["d3"]),
        axial_grid_z_mm,
    )
    d2 = _nearest_grid(float(original_lengths["d2"]), axial_grid_z_mm)
    d3 = downstream - d2
    if min(d1, d2, d3) <= 0.0 or not math.isclose(
        d1 + downstream, total_length_mm, rel_tol=0.0, abs_tol=axial_grid_z_mm / 10.0
    ):
        raise ValueError(f"grid realization does not preserve the {total_length_mm:g} mm positive-length topology")
    if not math.isclose(source.center_x_mm / axial_grid_z_mm, round(source.center_x_mm / axial_grid_z_mm), abs_tol=1e-9):
        raise ValueError("selected source center is not aligned to the requested axial grid")
    e1 = float(base["accelerator_physics"]["fields_v_per_mm"]["e1"])
    nominal_energy = float(source_values["nominal_energy_per_charge_v"])
    outer = OuterGeometry(
        zone1_length_mm=d1,
        downstream_length_mm=downstream,
        split_fraction=d2 / downstream,
        zone1_voltage_drop_v=e1 * d1,
        nominal_energy_per_charge_v=nominal_energy,
    )
    reflectron_values = reference.get("reflectron")
    if not isinstance(reflectron_values, dict):
        raise ValueError("ideal-acceptance reference reflectron is missing")
    reflectron = ReflectronGeometry(**reflectron_values)
    focus = float(base["accelerator_physics"]["focus_drift_after_exit_mm"])
    old_fields = base["accelerator_physics"]["fields_v_per_mm"]
    initial_eta = math.log(float(old_fields["e2"]) / float(old_fields["e3"]))
    initial = np.asarray(
        [initial_eta, float(base["reflectron"]["u_r1_v"]), float(base["reflectron"]["f_r2_v_per_mm"])],
        dtype=float,
    )
    half_width = 2.0

    def residual(values: np.ndarray) -> np.ndarray:
        eta, u_r1, f_r2 = (float(item) for item in values)
        if not (-20.0 < eta < 20.0 and 0.0 < u_r1 < nominal_energy and f_r2 > 0.0):
            return np.full(3, 1.0e9)
        point = IdealWorkingPoint(
            affine,
            derive_three_zone_state(affine, outer, eta),
            reflectron,
            InnerSolution(u_r1, f_r2, eta),
            focus,
            None,
        )
        return axial_time_coefficients(point, order=4)[1:4] * (
            half_width ** np.arange(1, 4)
        )

    solved = root(residual, initial, method="hybr", options={"xtol": 1.0e-10})
    solved_residual = residual(np.asarray(solved.x, dtype=float))
    tolerance = float(configuration["numerics"]["coefficient_tolerance_ns"])
    if not solved.success or not np.all(np.isfinite(solved_residual)) or np.max(np.abs(solved_residual)) > tolerance:
        raise ValueError(
            "grid-realized third-order focus closure failed: "
            f"success={solved.success}; max_scaled_residual_ns={np.max(np.abs(solved_residual)):.6g}"
        )
    eta, u_r1, f_r2 = (float(item) for item in solved.x)
    state = derive_three_zone_state(affine, outer, eta)
    exit_z = -focus
    intermediate2_z = exit_z - d3
    intermediate1_z = intermediate2_z - d2
    repeller_z = intermediate1_z - d1
    result = copy.deepcopy(base)
    result["compiler_mode"] = f"IDEAL_ACCEPTANCE_{int(total_length_mm)}MM_GRID_REALIZED_V1"
    result["accelerator_topology"] = {
        "topology_id": "three_zone_accelerator_ideal_v1",
        "planes_global_z_mm": {
            "repeller": repeller_z,
            "intermediate1": intermediate1_z,
            "intermediate2": intermediate2_z,
            "exit": exit_z,
        },
        "potentials_v": {
            "repeller": state.repeller_v,
            "intermediate1": state.grid1_v,
            "intermediate2": state.grid2_v,
            "exit": state.exit_v,
        },
    }
    result["accelerator_physics"] = {
        "lengths_mm": {"d1": d1, "d2": d2, "d3": d3},
        "fields_v_per_mm": {
            "e1": state.field1_v_per_mm,
            "e2": state.field2_v_per_mm,
            "e3": state.field3_v_per_mm,
        },
        "focus_drift_after_exit_mm": focus,
    }
    result["reflectron"] = {"u_r1_v": u_r1, "f_r2_v_per_mm": f_r2}
    result["numerical_grid_realization"] = {
        "axial_grid_z_mm": float(axial_grid_z_mm),
        "zone_lengths_mm": {"d1": d1, "d2": d2, "d3": d3},
        "scaled_focus_equation_residual_ns": [float(item) for item in solved_residual],
        "method": "three_zone_a1_a2_a3_root_on_grid_realized_lengths_v1",
    }
    result["claim_limit"] = (
        f"Exploration-only {total_length_mm:g} mm/4 mm ideal-field Candidate whose plane locations and "
        "third-order focus equations were re-closed on a declared "
        f"{axial_grid_z_mm:g} mm axial grid. Square and cylindrical real fields, collection, "
        "numerical convergence, and Formal qualification remain unverified."
    )
    validate_schema(result, OUTPUT_SCHEMA)
    return result


def _portable_candidate(
    candidate: Mapping[str, Any], *, workspace_root: Path
) -> dict[str, Any]:
    """Make provenance paths portable without changing their file identities."""

    portable = copy.deepcopy(candidate)
    records = (
        ("ideal acceptance configuration", portable["campaign"]["file"]),
        (
            "ideal acceptance configuration",
            portable["ideal_acceptance_evidence"]["configuration"],
        ),
        (
            "ideal acceptance manifest",
            portable["ideal_acceptance_evidence"]["run_manifest"],
        ),
        (
            "ideal acceptance selected result",
            portable["ideal_acceptance_evidence"]["selected_result"],
        ),
    )
    for label, record in records:
        record["path"] = _workspace_relative(
            Path(str(record["path"])), workspace_root, label=label
        )
    validate_schema(portable, OUTPUT_SCHEMA)
    return portable


def _publish_manifest(
    *, run_dir: Path, run_config: Path, outputs: Sequence[Path]
) -> Path:
    """Write and verify a standard non-Formal manifest before publication."""

    pending = run_dir / ".run_manifest.json.pending"
    command = [
        sys.executable,
        "-m",
        "common.contracts.write_run_manifest",
        "--run-config",
        str(run_config),
        "--manifest",
        str(pending),
        "--status",
        "success",
        "--software",
        f"Python {sys.version_info.major}.{sys.version_info.minor}",
    ]
    for output in outputs:
        command.extend(("--output", str(output)))
    completed = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "ideal-acceptance Candidate manifest publication failed: "
            + (completed.stdout + completed.stderr).strip()
        )
    manifest = load_json(pending)
    if (
        manifest.get("role") != "simulation_run_manifest"
        or manifest.get("status") != "success"
        or manifest.get("project") != PROJECT_ID
        or manifest.get("mode") != PUBLISH_MODE
        or manifest.get("formal_eligible") is not False
    ):
        raise RuntimeError("ideal-acceptance Candidate manifest identity differs")
    records = [manifest["run_config"], *manifest["inputs"].values(), *manifest["outputs"]]
    for record in records:
        record["path"] = os.path.relpath(
            Path(str(record["path"])).resolve(), run_dir
        ).replace("\\", "/")
    pending.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    verified = subprocess.run(
        [
            sys.executable,
            "-m",
            "common.contracts.verify_run_manifest",
            str(pending),
            "--require-status",
            "success",
            "--require-local-run-config",
            "--require-run-id",
            str(manifest["run_id"]),
            "--require-project",
            PROJECT_ID,
            "--require-mode",
            PUBLISH_MODE,
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if verified.returncode != 0:
        raise RuntimeError(
            "ideal-acceptance Candidate manifest verification failed: "
            + (verified.stdout + verified.stderr).strip()
        )
    destination = run_dir / "run_manifest.json"
    os.replace(pending, destination)
    return destination


def publish_ideal_acceptance_300mm_candidate(
    configuration_path: Path,
    run_manifest_path: Path,
    selected_result_path: Path,
    run_dir: Path,
    *,
    workspace_root: Path = DEFAULT_WORKSPACE_ROOT,
    axial_grid_z_mm: float | None = None, total_length_mm: float = 300.0,
) -> dict[str, Any]:
    """Atomically publish the selected ideal point as a Candidate-only run.

    Publication records the exact ideal-field evidence used to select the
    point.  It deliberately does not treat that evidence as proof that a real
    square or cylindrical field reproduces the ideal axial field.
    """

    workspace_root = workspace_root.resolve()
    configuration_path = configuration_path.resolve()
    run_manifest_path = run_manifest_path.resolve()
    selected_result_path = selected_result_path.resolve()
    run_dir = run_dir.resolve()
    validate_run_id(run_dir.name)
    canonical_runs = (
        workspace_root / "artifacts" / "projects" / PROJECT_ID / "runs"
    ).resolve()
    if run_dir.parent != canonical_runs:
        raise ValueError("Candidate run_dir must use the canonical workspace artifact root")
    if run_dir.exists():
        raise FileExistsError(f"Candidate run directory already exists: {run_dir}")
    if axial_grid_z_mm is None:
        compiler = lambda config, manifest, selected: compile_ideal_acceptance_300mm_candidate(
            config, manifest, selected, total_length_mm=total_length_mm
        )
    else:
        compiler = lambda config, manifest, selected: compile_grid_realized_ideal_acceptance_300mm_candidate(
            config, manifest, selected, axial_grid_z_mm=axial_grid_z_mm,
            total_length_mm=total_length_mm,
        )
    candidate = _portable_candidate(
        compiler(configuration_path, run_manifest_path, selected_result_path),
        workspace_root=workspace_root,
    )
    configuration = _load(configuration_path)
    reference_path = (
        Path(__file__).resolve().parents[1]
        / str(configuration["reference_config"])
    ).resolve()
    code_inputs = {
        "candidate_compiler_source": Path(__file__).resolve(),
        "candidate_output_schema": REPOSITORY_ROOT
        / "common/contracts/schemas/oatof_three_zone_simion_candidate_resolved.schema.json",
        "ideal_acceptance_configuration": configuration_path,
        "ideal_acceptance_run_manifest": run_manifest_path,
        "ideal_acceptance_selected_result": selected_result_path,
        "ideal_acceptance_reference_source": reference_path,
    }
    for label, path in code_inputs.items():
        if not path.is_file():
            raise ValueError(f"{label} is missing: {path}")
        _workspace_relative(path, workspace_root, label=label)

    canonical_runs.mkdir(parents=True, exist_ok=True)
    lock_path = canonical_runs / f".{run_dir.name}.publish.lock"
    try:
        lock_path.open("x", encoding="utf-8").close()
    except FileExistsError as error:
        raise FileExistsError(f"Candidate publication is already active: {run_dir}") from error
    staging: Path | None = None
    try:
        staging = Path(tempfile.mkdtemp(prefix=f".{run_dir.name}.pending-", dir=canonical_runs))
        candidate_path = staging / "results" / CANDIDATE_NAME
        summary_path = staging / "summary.json"
        config_path = staging / "run_config.json"
        _write_exclusive_json(candidate_path, candidate)
        relative_input = lambda path: os.path.relpath(path, staging).replace("\\", "/")
        _write_exclusive_json(
            config_path,
            {
                "schema_version": 1,
                "role": "ideal_acceptance_300mm_simion_candidate_run_config",
                "run_id": run_dir.name,
                "project": PROJECT_ID,
                "mode": PUBLISH_MODE,
                "inputs": {
                    name: relative_input(path) for name, path in code_inputs.items()
                },
                "parameters": {
                    "campaign_id": candidate["campaign"]["campaign_id"],
                    "compiler_mode": candidate["compiler_mode"],
                    "qualification": candidate["qualification"],
                    "selected_design_id": candidate["ideal_acceptance_evidence"]["selected_design_id"],
                    "total_length_mm": total_length_mm, **({"axial_grid_z_mm": axial_grid_z_mm} if axial_grid_z_mm is not None else {}),
                },
                "formal_gate_passed": False,
            },
        )
        _write_exclusive_json(
            summary_path,
            {
                "schema_version": 1,
                "role": "ideal_acceptance_300mm_simion_candidate_summary",
                "status": "success",
                "run_id": run_dir.name,
                "qualification": "CANDIDATE_ONLY",
                "candidate": {
                    "path": f"results/{CANDIDATE_NAME}",
                    "bytes": candidate_path.stat().st_size,
                    "sha256": file_sha256(candidate_path),
                },
                "claim_limit": candidate["claim_limit"],
                "formal_gate_passed": False,
            },
        )
        _publish_manifest(
            run_dir=staging,
            run_config=config_path,
            outputs=(candidate_path, summary_path),
        )
        if run_dir.exists():
            raise FileExistsError(f"Candidate run directory already exists: {run_dir}")
        staging.rename(run_dir)
    except BaseException:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)
        raise
    finally:
        lock_path.unlink(missing_ok=True)
    return _load(run_dir / "summary.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", required=True, type=Path)
    parser.add_argument("--run-manifest", required=True, type=Path)
    parser.add_argument("--selected-result", required=True, type=Path)
    destinations = parser.add_mutually_exclusive_group(required=True)
    destinations.add_argument("--output", type=Path)
    destinations.add_argument("--run-dir", type=Path)
    parser.add_argument("--workspace-root", type=Path, default=DEFAULT_WORKSPACE_ROOT)
    parser.add_argument(
        "--axial-grid-z-mm", type=float,
        help="re-close the 300 mm Candidate on this fine axial grid before publication",
    )
    parser.add_argument("--total-length-mm", type=float, choices=(250.0, 300.0), default=300.0)
    arguments = parser.parse_args()
    if arguments.output is not None:
        if arguments.workspace_root != DEFAULT_WORKSPACE_ROOT:
            parser.error("--workspace-root is only valid with --run-dir")
        result = (
            compile_ideal_acceptance_300mm_candidate(
                arguments.configuration, arguments.run_manifest, arguments.selected_result, total_length_mm=arguments.total_length_mm
            )
            if arguments.axial_grid_z_mm is None
            else compile_grid_realized_ideal_acceptance_300mm_candidate(
                arguments.configuration, arguments.run_manifest, arguments.selected_result,
                axial_grid_z_mm=arguments.axial_grid_z_mm, total_length_mm=arguments.total_length_mm,
            )
        )
        _write_exclusive_json(arguments.output, result)
    else:
        publish_ideal_acceptance_300mm_candidate(
            arguments.configuration,
            arguments.run_manifest,
            arguments.selected_result,
            arguments.run_dir,
            workspace_root=arguments.workspace_root,
            axial_grid_z_mm=arguments.axial_grid_z_mm, total_length_mm=arguments.total_length_mm,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
