"""Project file boundary; neutral design lives in installed components."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from msplatform.io.file_identity import file_sha256 as _sha256
from msplatform.components.single_reflection_oa_tof.geometry_contract import (
    _close as _close, _validate_science as _validate_science,
    _require_exact_keys as _require_exact_keys,
    resolve_electrode_geometry as resolve_electrode_geometry,
    serialized as serialized,
)
from msplatform.backends.simion.tof_geometry import (
    derive_simion_geometry as derive_simion_geometry,
    resolve_physical_geometry as resolve_physical_geometry,
    resolve_oatof_contract_documents,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2] / "components/single_reflection_oa_tof"
BASELINE_PATH = PROJECT_ROOT / "config/baseline.json"
MODE_PATH = PROJECT_ROOT / "config/modes/formal.json"
NUMERICS_PATH = PROJECT_ROOT / "config/formal_solver_numerics.json"
RESOLVED_PATH = PROJECT_ROOT / "config/resolved_geometry.json"


def resolve_contract_documents(baseline, mode, numerics, *, input_identity):
    return resolve_oatof_contract_documents(
        baseline, mode, numerics, input_identity=input_identity)


def _input_label(path: Path, run_role: str, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return f"run_input:{run_role}"


def resolve_contract(
    baseline_path: Path = BASELINE_PATH,
    mode_path: Path = MODE_PATH,
    numerics_path: Path = NUMERICS_PATH,
    *,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    baseline_path = Path(baseline_path)
    mode_path = Path(mode_path)
    numerics_path = Path(numerics_path)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    mode = json.loads(mode_path.read_text(encoding="utf-8"))
    numerics = json.loads(numerics_path.read_text(encoding="utf-8"))
    return resolve_contract_documents(baseline, mode, numerics, input_identity={
        "baseline": _input_label(baseline_path, "candidate_baseline.json", project_root),
        "baseline_sha256": _sha256(baseline_path),
        "mode": _input_label(mode_path, "candidate_science_mode.json", project_root),
        "mode_sha256": _sha256(mode_path),
        "solver_numerics": _input_label(numerics_path, "candidate_solver_numerics.json", project_root),
        "solver_numerics_sha256": _sha256(numerics_path),
    })
