"""Identity for the symmetric full-domain 1 mm analyzer raw PA."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.simion.pa_family_cache import canonical_pa_family_cache_key
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_system_geometry import (
    build_analyzer_gem,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import load_contract


def derive(contract_path: Path, simion_executable: Path, simion_release: str) -> tuple[dict[str, Any], str]:
    contract = load_contract(contract_path)
    simion = contract["simion"]
    mesh = [float(value) for value in simion["component_mesh_mm_per_gu"]["analyzer"]]
    span = [float(value) for value in simion["analyzer_pa_span_mm"]]
    origin = [float(value) for value in simion["analyzer_pa_origin_mm"]]
    shape = [int(round(span[index] / mesh[index])) + 1 for index in range(3)]
    if mesh != [1.0, 1.0, 1.0] or origin != [-span[0] / 2.0, -162.0, -span[2] / 2.0]:
        raise ValueError("coarse analyzer must retain the full bilateral 1 mm domain")
    gem = build_analyzer_gem(contract_path)
    identity = {
        "geometry": {"role": "mrtof_symmetric_full_domain_coarse_raw", "grid_shape": shape},
        "gem": {"sha256": __import__("hashlib").sha256(gem.encode("utf-8")).hexdigest().upper()},
        "basis_namespace": {"artifact_role": "physical_raw_geometry_only"},
        "mesh": {"mm_per_gu": mesh},
        "grid_phase": {"analyzer_origin_mm": origin, "pa_span_mm": span},
        "surface": "none",
        "simion_identity": {"release": simion_release, "executable_sha256": file_sha256(simion_executable).upper()},
        "refine_policy": {"operation": "gem2pa_raw_geometry_only", "refine_performed": False},
        "builder_identity": {
            "geometry_generator_sha256": file_sha256(Path(__file__).with_name("native_system_geometry.py")).upper(),
            "gem2pa_runner_sha256": file_sha256(Path(__file__).resolve().parents[3] / "common/simion/run_gem2pa.ps1").upper(),
        },
    }
    if math.prod(shape) <= 0:
        raise ValueError("coarse analyzer grid is empty")
    canonical_pa_family_cache_key(identity)
    return identity, gem


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--simion-executable", type=Path, required=True)
    parser.add_argument("--simion-release", required=True)
    parser.add_argument("--identity-output", type=Path, required=True)
    parser.add_argument("--gem-output", type=Path, required=True)
    args = parser.parse_args()
    identity, gem = derive(args.contract, args.simion_executable, args.simion_release)
    args.identity_output.parent.mkdir(parents=True, exist_ok=True)
    args.gem_output.parent.mkdir(parents=True, exist_ok=True)
    args.identity_output.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.gem_output.write_text(gem, encoding="utf-8", newline="\n")
    print("MRTOF_COARSE_RAW_IDENTITY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
