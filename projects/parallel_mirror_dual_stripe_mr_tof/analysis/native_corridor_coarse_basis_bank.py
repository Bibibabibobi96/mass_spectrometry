"""Identity for the reusable coarse physical-electrode donor bank."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.simion.pa_family_cache import canonical_pa_family_cache_key


def derive_identity(
    recipe_path: Path, coarse_manifest_path: Path, builder_path: Path,
    simion_executable: Path, simion_release: str,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    recipe = json.loads(recipe_path.read_text(encoding="utf-8-sig"))
    manifest = json.loads(coarse_manifest_path.read_text(encoding="utf-8-sig"))
    physical_ids = tuple(sorted({
        int(value)
        for response in recipe["response_recipes"]
        for value in response["physical_ids"]
    }))
    names = tuple(f"mrtof_analyzer.pa{value}" for value in physical_ids)
    raw_name = str(recipe["coarse_raw_member"]["name"])
    raw_records = [record for record in manifest["files"] if record["name"] == raw_name]
    if len(raw_records) != 1 or names != tuple(
        sorted(
            {str(name) for response in recipe["response_recipes"] for name in response["scratch_basis_names"]},
            key=lambda value: int(value.rsplit(".pa", 1)[1]),
        )
    ):
        raise ValueError("coarse donor recipe inventory differs")
    generation = recipe["coarse_raw_generation_identity"]
    identity = {
        "geometry": {
            "role": "mrtof_coarse_physical_electrode_donor_bank",
            "coarse_raw": {
                "cache_key": str(generation["cache_key"]).upper(),
                "generation_sha256": str(generation["generation_sha256"]).upper(),
                "member": raw_records[0],
            },
        },
        "gem": {"source": "published_coarse_raw_geometry"},
        "basis_namespace": {
            "physical_ids": list(physical_ids),
            "filenames": list(names),
            "basis_voltage_v": 10000.0,
        },
        "mesh": manifest["identity"]["mesh"],
        "grid_phase": manifest["identity"]["grid_phase"],
        "surface": manifest["identity"]["surface"],
        "simion_identity": {
            "release": simion_release,
            "executable_sha256": file_sha256(simion_executable).upper(),
        },
        "refine_policy": {"mode": "native_refine_one_physical_solution_per_member"},
        "builder_identity": {
            "path": "projects/parallel_mirror_dual_stripe_mr_tof/simion/build_component_basis.lua",
            "sha256": file_sha256(builder_path).upper(),
        },
    }
    canonical_pa_family_cache_key(identity)
    return identity, names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--coarse-manifest", type=Path, required=True)
    parser.add_argument("--builder", type=Path, required=True)
    parser.add_argument("--simion-executable", type=Path, required=True)
    parser.add_argument("--simion-release", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    identity, names = derive_identity(
        args.recipe, args.coarse_manifest, args.builder,
        args.simion_executable, args.simion_release,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"identity": str(args.output.resolve()), "filenames": list(names)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
