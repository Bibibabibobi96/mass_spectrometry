"""Prepare solver/CAD candidate inputs without launching commercial software."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from projects.single_reflection_oa_tof_mass_analyzer.analysis.sync_geometry_contract import (
    load_contract,
    render_fly2,
    render_program,
    render_resolved_lua,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONSUMER_CONTRACT_PATH = PROJECT_ROOT / "config" / "candidate_consumers.json"
VARIABLE_CATALOG_PATH = PROJECT_ROOT / "config" / "design_variables.json"


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


def prepare(
    contract_path: Path,
    output_dir: Path,
    particle_source_seed: int | None = None,
) -> dict[str, Path]:
    if not isinstance(particle_source_seed, int):
        raise ValueError("candidate consumer preparation requires an explicit particle source seed")
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
        "fly2": render_fly2(contract, particle_source_seed=particle_source_seed),
    }
    for key, path in generated.items():
        path.write_text(contents[key], encoding="utf-8", newline="\n")

    return generated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--particle-source-seed", required=True, type=int)
    args = parser.parse_args()
    prepare(
        args.contract,
        args.output_dir.resolve(),
        particle_source_seed=args.particle_source_seed,
    )
    print(f"CANDIDATE_CONSUMER_PREPARE=STATIC_INPUTS_READY SOURCE={Path(__file__).resolve()}")


if __name__ == "__main__":
    main()
