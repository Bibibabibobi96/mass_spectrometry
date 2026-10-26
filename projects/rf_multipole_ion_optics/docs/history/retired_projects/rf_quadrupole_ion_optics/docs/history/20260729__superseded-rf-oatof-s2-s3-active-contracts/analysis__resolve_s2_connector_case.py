"""Resolve one approved connector topology case into the S2 machine contract."""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.rigid_transform import FramedVector, RigidTransform


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = PROJECT_ROOT / "config" / "rf_to_oatof_s2_passive_connector.json"
DEFAULT_CASES = PROJECT_ROOT / "config" / "rf_to_oatof_connector_cases.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_case(base_path: Path, cases_path: Path, case_id: str) -> dict[str, Any]:
    """Return a derived S2 contract for one approved non-negative gap case."""
    base = _load(base_path)
    cases = _load(cases_path)
    if cases.get("role") != "rf_to_oatof_passive_connector_topology_cases":
        raise ValueError("connector topology-case role differs")
    matches = [item for item in cases.get("cases", []) if item.get("case_id") == case_id]
    if len(matches) != 1:
        raise ValueError(f"connector case must resolve uniquely: {case_id}")
    selected = matches[0]
    gap_mm = float(selected["connector_gap_mm"])
    if not math.isfinite(gap_mm) or gap_mm < 0:
        raise ValueError("connector case gap must be finite and non-negative")

    result = copy.deepcopy(base)
    registration = result["nominal_registration"]
    base_gap_mm = float(registration["connector_gap_mm"])
    target = [float(value) for value in registration["target_entry_center_instrument_mm"]]
    source = [target[0] - gap_mm, target[1], target[2]]
    local = [float(value) for value in registration["source_exit_center_local_mm"]]
    rotation = registration["source_component_pose"]["rotation_component_to_instrument"]
    rotation_only = RigidTransform(
        "rf_quadrupole_component",
        registration["instrument_frame"],
        rotation,
        (0.0, 0.0, 0.0),
    )
    rotated = rotation_only.transform_vector(
        FramedVector("rf_quadrupole_component", local)
    ).components
    translation = [source[index] - rotated[index] for index in range(3)]
    registration["source_exit_center_instrument_mm"] = source
    registration["source_component_pose"]["translation_mm"] = translation
    registration["connector_gap_mm"] = gap_mm
    if not math.isclose(gap_mm, base_gap_mm, rel_tol=0.0, abs_tol=1e-12):
        registration["derivation"] = (
            f"Derive RF source pose from target entry minus approved connector case gap {gap_mm:g} mm."
        )

    geometry = result["passive_connector_geometry"]
    geometry["axial_extent_x_mm"] = [source[0], target[0]]
    geometry["length_mm"] = gap_mm
    result["runtime_case"] = {
        "case_id": case_id,
        "topology": selected["topology"],
        "connector_gap_mm": gap_mm,
        "connector_domain_present": gap_mm > 0,
        "qualification_claim_allowed": False,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = resolve_case(args.base, args.cases, args.case_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        "S2_CONNECTOR_CASE=PASS "
        f"CASE={args.case_id} GAP_MM={result['runtime_case']['connector_gap_mm']:g}"
    )


if __name__ == "__main__":
    main()
