"""Derive all local-family cache probes from one prepared-source receipt."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from common.simion.pa_family_cache import canonical_pa_family_cache_key
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_pa_family import (
    derive_local_pa_family_contract,
    local_pa_family_filenames,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_patch_geometry import (
    REGIONS,
    build_local_patch_gem,
)


def derive_batch_plan(
    *, contract: Path, receipt: Path, regions: list[str], scale_factor: float,
    cache_root: Path, simion_executable: Path, simion_release: str,
) -> dict[str, Any]:
    """Probe all regions without opening source PA payloads or creating copies."""
    if not regions or len(set(regions)) != len(regions) or any(region not in REGIONS for region in regions):
        raise ValueError("batch regions must be a nonempty unique subset of declared local regions")
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="mrtof_local_batch_plan_") as directory:
        temporary = Path(directory)
        for region in regions:
            gem = temporary / f"{region}.gem"
            gem.write_text(build_local_patch_gem(contract, region, scale_factor), encoding="utf-8", newline="\n")
            family = derive_local_pa_family_contract(
                contract, region, scale_factor, gem, temporary, simion_executable,
                simion_release, receipt,
            )
            filenames = local_pa_family_filenames(region, len(family["response_recipes"]))
            cache_key = canonical_pa_family_cache_key(family["identity"])
            # This batch pre-plan deliberately performs only a metadata presence
            # check.  The child runner validates and hashes each generation once
            # immediately before use; doing the same full multi-GB probe here
            # would double all cache-hit I/O without strengthening the boundary.
            pointer = cache_root / cache_key / "current_generation.json"
            disposition = "unverified_hit_candidate" if pointer.is_file() else "miss"
            rows.append({"region": region, "identity": family["identity"], "filenames": list(filenames),
                         "cache_disposition": disposition, "cache_key": cache_key})
    return {"schema_version": 1, "role": "mrtof_analyzer_local_family_batch_plan", "status": "success",
            "source_mode": "prepared_receipt_metadata_only", "scale_factor": scale_factor,
            "regions": rows, "miss_count": sum(row["cache_disposition"] == "miss" for row in rows)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--prepared-source-receipt", required=True, type=Path)
    parser.add_argument("--regions", required=True, nargs="+", choices=REGIONS)
    parser.add_argument("--scale-factor", required=True, type=float)
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--simion-executable", required=True, type=Path)
    parser.add_argument("--simion-release", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    document = derive_batch_plan(contract=args.contract, receipt=args.prepared_source_receipt, regions=args.regions,
        scale_factor=args.scale_factor, cache_root=args.cache_root, simion_executable=args.simion_executable,
        simion_release=args.simion_release)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
