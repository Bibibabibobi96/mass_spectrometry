"""Project file boundary; neutral design lives in installed components."""
from __future__ import annotations
import json
import math
from pathlib import Path
from typing import Any
from msplatform.io.file_identity import file_sha256 as _sha256
from msplatform.components.single_reflection_oa_tof.geometry_contract import (
    _close as _close, _validate_science as _validate_science,
    _require_exact_keys as _require_exact_keys,
    resolve_electrode_geometry as resolve_electrode_geometry,
    resolve_contract_documents as _resolve_documents, serialized as serialized,
)
from msplatform.backends.simion.tof_geometry import derive_simion_geometry as derive_simion_geometry, resolve_physical_geometry as resolve_physical_geometry
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = PROJECT_ROOT / "config/baseline.json"
MODE_PATH = PROJECT_ROOT / "config/modes/formal.json"
NUMERICS_PATH = PROJECT_ROOT / "config/formal_solver_numerics.json"
RESOLVED_PATH = PROJECT_ROOT / "config/resolved_geometry.json"


def _validate_layers(baseline, science, numerics):
    _validate_science(baseline, science)
    _require_exact_keys(numerics, {"schema_version", "role", "comsol", "simion"}, "solver numerics contract")
    if type(numerics["schema_version"]) is not int or numerics["schema_version"] != 1:
        raise ValueError("unsupported solver numerics schema_version; requires integer 1")
    if numerics.get("role") != "oa_tof_formal_solver_numerics":
        raise ValueError("unsupported formal solver numerics contract")
    if not isinstance(science.get("particle"), dict) or not isinstance(numerics.get("comsol"), dict) or not isinstance(numerics.get("simion"), dict):
        raise ValueError("formal contracts are missing required science or solver sections")
    runtime = numerics["comsol"]
    for key in ("routine_reflectron_hmax_mm", "routine_accelerator_hmax_mm", "convergence_accelerator_hmax_mm",
                "fine_output_step_ns", "field_free_output_step_ns"):
        value = runtime.get(key)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"comsol.{key} must be a finite positive number")
    if runtime.get("solver_steps") not in ("free", "intermediate", "strict"):
        raise ValueError("comsol.solver_steps must be free, intermediate or strict")
    if runtime.get("times_to_store") != "tlist":
        raise ValueError("comsol.times_to_store must be tlist for OA-TOF detector sampling")

def resolve_contract_documents(baseline, mode, numerics, *, input_identity):
    _validate_layers(baseline, mode, numerics)
    build = numerics["simion"]["geometry_build"]
    marker = numerics["simion"]["detector_marker"]
    if not 0 < marker["capture_depth_mm"] < marker["absorber_thickness_mm"]:
        raise ValueError("detector capture depth must lie inside the numerical absorber")
    if marker["capture_arm_distance_mm"] <= marker["front_margin_z_mm"]:
        raise ValueError("detector capture arm distance must exceed the PA front margin")
    resolved = _resolve_documents(baseline, mode, input_identity=input_identity)
    resolved.update(simion_runtime={**numerics["simion"], "routine_particles": mode["particle"]["statistical_count"]},
        simion_geometry_build=build, comsol_runtime=numerics["comsol"], simion_detector_marker=marker)
    physical = resolve_physical_geometry(resolved)
    face = physical["detector_active_face"]
    if marker["active_plane_z_mm"] != face["center_mm"][2] or marker["active_radius_mm"] != face["radius_mm"]:
        raise ValueError("numerical detector marker differs from the physical detector active face")
    detector_body = physical["simion"]["detector_body"]
    resolved["derived"] = derive_simion_geometry(geometry=resolved["geometry_mm"], coordinate=resolved["coordinate_convention"], build=build, marker=marker, source=resolved["particle_source"], physical_detector=detector_body)
    return resolved


def _input_label(path: Path, run_role: str) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return f"run_input:{run_role}"

def resolve_contract(
    baseline_path: Path = BASELINE_PATH,
    mode_path: Path = MODE_PATH,
    numerics_path: Path = NUMERICS_PATH,
) -> dict[str, Any]:
    baseline_path = Path(baseline_path)
    mode_path = Path(mode_path)
    numerics_path = Path(numerics_path)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    mode = json.loads(mode_path.read_text(encoding="utf-8"))
    numerics = json.loads(numerics_path.read_text(encoding="utf-8"))
    return resolve_contract_documents(baseline, mode, numerics, input_identity={
        "baseline": _input_label(baseline_path, "candidate_baseline.json"),
        "baseline_sha256": _sha256(baseline_path),
        "mode": _input_label(mode_path, "candidate_science_mode.json"),
        "mode_sha256": _sha256(mode_path),
        "solver_numerics": _input_label(numerics_path, "candidate_solver_numerics.json"),
        "solver_numerics_sha256": _sha256(numerics_path),
    })
