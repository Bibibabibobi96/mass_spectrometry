"""Validate an RF handoff bundle before oa-TOF candidate consumption."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
DEFAULT_MODE = PROJECT_ROOT / "config" / "modes" / "rf_handoff_projection.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def repo_path(value: str) -> Path:
    return (REPO_ROOT / value).resolve()


def workspace_path(value: str) -> Path:
    return (WORKSPACE_ROOT / value).resolve()


def validate_mode(
    mode_path: Path = DEFAULT_MODE,
    require_runtime_assets: bool = False,
) -> dict[str, Any]:
    mode = load_json(mode_path)
    if mode.get("role") != "oa_tof_external_handoff_projection_candidate":
        raise ValueError("unsupported external-handoff mode role")
    if mode.get("status") == "formal":
        raise ValueError("RF handoff projection must remain a candidate")
    claims = mode["claims"]
    forbidden = (
        "physical_link_claim_allowed",
        "resolution_claim_allowed",
        "formal_asset_modification_allowed",
        "promotion_authorized",
    )
    if any(claims.get(key) is not False for key in forbidden):
        raise ValueError("candidate mode contains an unauthorized claim")
    if claims.get("functional_projection_claim_allowed") is not True:
        raise ValueError("candidate must explicitly scope its functional projection claim")
    if len(mode.get("source_cases", [])) != 2:
        raise ValueError("the projection requires the paired RF COMSOL and SIMION ensembles")
    case_ids = [case["case_id"] for case in mode["source_cases"]]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("source case IDs must be unique")
    if {case["upstream_solver"] for case in mode["source_cases"]} != {"COMSOL", "SIMION"}:
        raise ValueError("source cases must cover RF COMSOL and SIMION")

    contract_path = repo_path(mode["handoff_contract"])
    contract = load_json(contract_path)
    if contract.get("role") != "component_chain_handoff_contract":
        raise ValueError("upstream handoff contract role mismatch")
    if contract.get("package_generation_allowed") is not False:
        raise ValueError("upstream draft unexpectedly permits package generation")
    if contract.get("electrical_interface", {}).get("status") != "unresolved":
        raise ValueError("candidate mode is only valid while the electrical interface is explicit")
    acceptance = contract["acceptance_criteria"]["downstream_functional"]
    if acceptance.get("n100_resolution_claim_allowed") is not False:
        raise ValueError("N=100 must not authorize a resolution claim")

    if require_runtime_assets:
        for consumer in mode["target_consumers"].values():
            asset = workspace_path(consumer["formal_asset"])
            if not asset.is_file():
                raise ValueError(f"formal read-only consumer asset is missing: {asset}")
    return {"mode": mode, "contract": contract, "contract_path": contract_path, "acceptance": acceptance}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _same_number(left: str, right: str, tolerance: float = 1e-10) -> bool:
    return math.isclose(float(left), float(right), rel_tol=tolerance, abs_tol=tolerance)


def validate_bundle(
    canonical_path: Path,
    ion_path: Path,
    row_map_path: Path,
    metadata_path: Path,
    mode_path: Path = DEFAULT_MODE,
) -> dict[str, Any]:
    validated = validate_mode(mode_path)
    metadata = load_json(metadata_path)
    if metadata.get("status") != "PASS" or metadata.get("package_generation_allowed") is not False:
        raise ValueError("handoff metadata is not a passing projection-only bundle")
    if metadata.get("contract", {}).get("sha256", "").upper() != sha256(validated["contract_path"]):
        raise ValueError("handoff bundle contract hash is stale")
    declared = metadata.get("outputs", {})
    checks = {
        "canonical_handoff_csv": canonical_path,
        "oatof_ion": ion_path,
        "row_map_csv": row_map_path,
    }
    for key, path in checks.items():
        if declared.get(key, {}).get("sha256", "").upper() != sha256(path):
            raise ValueError(f"handoff bundle output hash mismatch: {key}")

    canonical = _read_csv(canonical_path)
    row_map = _read_csv(row_map_path)
    ion_lines = [line for line in ion_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not canonical or len(canonical) != len(row_map) or len(canonical) != len(ion_lines):
        raise ValueError("canonical, row-map and ION particle counts differ")
    seen_ids: set[int] = set()
    local_birth = float(validated["mode"]["clock_policy"]["solver_local_birth_time_us"])
    for index, (state, mapping, line) in enumerate(zip(canonical, row_map, ion_lines), start=1):
        particle_id = int(state["particle_id"])
        if particle_id in seen_ids:
            raise ValueError("canonical particle IDs must be unique")
        seen_ids.add(particle_id)
        if int(mapping["solver_row_index"]) != index or int(mapping["particle_id"]) != particle_id:
            raise ValueError("row map does not preserve canonical particle identity")
        for field in ("instrument_time_us", "lineage_age_us", "particle_age_us"):
            if not _same_number(state[field], mapping[field]):
                raise ValueError(f"row map clock mismatch: {field}")
        ion = line.split(",")
        if len(ion) != 11:
            raise ValueError("derived oa-TOF ION row must contain 11 columns")
        if not math.isclose(float(ion[0]), local_birth, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("derived ION solver birth time violates the candidate clock policy")
        comparisons = (
            (ion[1], state["mass_amu"]),
            (ion[2], state["charge_state"]),
            (ion[3], state["position_x_mm"]),
            (ion[4], state["position_y_mm"]),
            (ion[5], state["position_z_mm"]),
            (ion[8], state["kinetic_energy_eV"]),
        )
        if any(not _same_number(left, right) for left, right in comparisons):
            raise ValueError("derived ION content differs from the canonical state")
    return {
        "particles": len(canonical),
        "canonical_sha256": sha256(canonical_path),
        "ion_sha256": sha256(ion_path),
        "row_map_sha256": sha256(row_map_path),
        "metadata_sha256": sha256(metadata_path),
        "handoff_contract_sha256": sha256(validated["contract_path"]),
        "functional_projection_runtime_authorized": True,
        "physical_link_claim_allowed": False,
        "resolution_claim_allowed": False,
        "formal_asset_modification_allowed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", type=Path, default=DEFAULT_MODE)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check-mode", action="store_true")
    action.add_argument("--validate-bundle", action="store_true")
    parser.add_argument("--canonical", type=Path)
    parser.add_argument("--ion", type=Path)
    parser.add_argument("--row-map", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.check_mode:
        validate_mode(args.mode)
        print("RF_HANDOFF_CONSUMER_MODE=PASS STATUS=CANDIDATE PHYSICAL_LINK=false")
        return
    required = (args.canonical, args.ion, args.row_map, args.metadata, args.output)
    if any(value is None for value in required):
        parser.error("--validate-bundle requires all bundle paths and --output")
    result = validate_bundle(args.canonical, args.ion, args.row_map, args.metadata, args.mode)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"RF_HANDOFF_BUNDLE=PASS PARTICLES={result['particles']}")


if __name__ == "__main__":
    main()
