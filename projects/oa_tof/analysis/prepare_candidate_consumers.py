"""Prepare solver/CAD candidate inputs without launching commercial software."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from sync_geometry_contract import load_contract, render_fly2, render_program, render_resolved_lua


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONSUMER_CONTRACT_PATH = PROJECT_ROOT / "config" / "candidate_consumers.json"
VARIABLE_CATALOG_PATH = PROJECT_ROOT / "config" / "design_variables.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_routing_coverage(consumer_contract: dict, variable_catalog: dict) -> None:
    consumers = set(consumer_contract.get("consumers", {}))
    routed_effects = {"comsol", "simion", "cad"}
    missing = []
    for variable in variable_catalog.get("variables", []):
        for effect in set(variable.get("rebuild_effects", [])) & routed_effects:
            if effect not in consumers:
                missing.append(f"{variable['variable_id']}:{effect}")
    if missing:
        raise ValueError("candidate consumer routing is incomplete: " + ", ".join(sorted(missing)))


def prepare(contract_path: Path, output_dir: Path) -> dict:
    contract_path = contract_path.resolve()
    contract = load_contract(contract_path)
    consumer_contract = json.loads(CONSUMER_CONTRACT_PATH.read_text(encoding="utf-8"))
    if consumer_contract.get("role") != "oa_tof_candidate_consumer_contract":
        raise ValueError("unsupported candidate consumer contract")
    variable_catalog = json.loads(VARIABLE_CATALOG_PATH.read_text(encoding="utf-8"))
    verify_routing_coverage(consumer_contract, variable_catalog)

    simion_dir = output_dir / "simion"
    simion_dir.mkdir(parents=True, exist_ok=True)
    generated = {
        "resolved_lua": simion_dir / "oatof_resolved.lua",
        "program": simion_dir / "oatof_ideal_grounded.lua",
        "fly2": simion_dir / "oatof_ideal_grounded.fly2",
    }
    contents = {
        "resolved_lua": render_resolved_lua(contract),
        "program": render_program(contract),
        "fly2": render_fly2(contract),
    }
    for key, path in generated.items():
        path.write_text(contents[key], encoding="utf-8", newline="\n")

    candidate_mph = (output_dir / "comsol" / "oa_tof__candidate.mph").resolve()
    cad_dir = (output_dir / "cad").resolve()
    plan = {
        "schema_version": 1,
        "role": "oa_tof_candidate_consumption_plan",
        "status": "STATIC_INPUTS_READY",
        "candidate_contract": {"path": str(contract_path), "sha256": sha256(contract_path)},
        "consumers": {
            "comsol": {
                "entrypoint": "comsol/run_oatof_model.m",
                "arguments": {"ContractPath": str(contract_path), "OutputModelPath": str(candidate_mph)},
                "runtime_status": "not_run",
            },
            "simion": {
                "entrypoint": "analysis/prepare_candidate_consumers.py",
                "generated": {
                    key: {"path": str(path.resolve()), "sha256": sha256(path)}
                    for key, path in generated.items()
                },
                "runtime_status": "text_generated_pa_iob_not_built",
            },
            "cad": {
                "entrypoint": "cad/ms_export_oatof_to_solidworks.m",
                "arguments": {"modelPath": str(candidate_mph), "outputDir": str(cad_dir)},
                "runtime_status": "blocked_until_candidate_mph_exists",
            },
        },
        "coverage_semantics": consumer_contract["coverage_semantics"],
        "limitations": consumer_contract["limitations"],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = output_dir / "candidate_consumption_plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return plan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    plan = prepare(args.contract, args.output_dir.resolve())
    print(f"CANDIDATE_CONSUMER_PREPARE={plan['status']}")


if __name__ == "__main__":
    main()
