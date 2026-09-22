"""Identity and publication adapter for one closed two-zone PA controller."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from common.contracts.file_identity import file_sha256
from common.simion.pa_family_cache import (
    PAFamilyCacheError, advance_pa_family_cache_transaction, probe_pa_family_cache,
)

FILES = ("orthogonal_accelerator_focus.pa#", *(f"orthogonal_accelerator_focus.pa{index}" for index in range(10)))


def identity(plan: Mapping[str, Any], builder: Path, simion_executable: Path) -> dict[str, Any]:
    if plan.get("role") != "orthogonal_accelerator_component_focus_pa_plan":
        raise ValueError("component focus PA plan identity is invalid")
    domain = plan.get("numerical_domain")
    if not isinstance(domain, Mapping):
        raise ValueError("component focus PA numerical domain is invalid")
    return {
        "geometry": {"role": "orthogonal_accelerator_closed_two_zone_focus_controller", "layout": plan["layout"]},
        "gem": {"sha256": __import__("hashlib").sha256(str(plan["gem"]).encode("utf-8")).hexdigest()},
        "basis_namespace": {"native_solution_ids": list(range(10)), "electrode_ids": list(range(1, 10)), "runtime": "pa0_fast_adjust_only"},
        "mesh": {"mm_per_gu": domain["mesh_mm_per_gu"]},
        "grid_phase": {"pa_span_mm": domain["span_mm"], "iob_origin_mm": domain["iob_origin_mm"]},
        "surface": "none",
        "simion_identity": {"release": "SIMION 2020", "executable_sha256": file_sha256(simion_executable)},
        "refine_policy": {"operation": "one_native_fast_adjust_family_solutions_0_through_9", "response_bank": "absent"},
        "builder_identity": {"path": "projects/orthogonal_accelerator/simion/build_component_focus_pa.lua", "sha256": file_sha256(builder)},
    }


def _progress(result: Any, value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "cache_key": result.cache_key,
        "status": result.status,
        "action_required": result.action_required,
        "transaction_directory": str(result.transaction_directory),
        "build_directory": str(result.build_directory),
        "scratch_directory": str(result.scratch_directory),
        "inventory_sha256": result.inventory_sha256,
        "generation_sha256": result.generation_sha256,
        "generation_directory": str(result.generation_directory) if result.generation_directory else None,
        "missing_files": list(result.missing_files),
        "identity": dict(value),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("probe", "advance-transaction"), required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--builder", type=Path, required=True)
    parser.add_argument("--simion-executable", type=Path, required=True)
    parser.add_argument("--verification-evidence", type=Path)
    parser.add_argument("--owner")
    args = parser.parse_args()
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        value = identity(plan, args.builder, args.simion_executable)
        if args.action == "probe":
            if args.verification_evidence is not None or args.owner is not None:
                raise ValueError("probe does not accept verification evidence or transaction owner")
            result = probe_pa_family_cache(args.cache_root, value, expected_filenames=FILES)
            if result.generation_directory is not None:
                manifest = json.loads((result.generation_directory / "cache_manifest.json").read_text(encoding="utf-8"))
                if tuple(record["name"] for record in manifest["files"]) != FILES:
                    raise ValueError("published controller cache inventory differs from the exact native Fast Adjust family")
            output = {"disposition": result.disposition.value, "cache_key": result.cache_key,
                      "generation_directory": str(result.generation_directory) if result.generation_directory else None,
                      "generation_sha256": result.generation_directory.name if result.generation_directory else None,
                      "identity": value}
        else:
            if not isinstance(args.owner, str) or not args.owner.strip():
                raise ValueError("advance-transaction requires a nonempty owner")
            evidence = (
                json.loads(args.verification_evidence.read_text(encoding="utf-8-sig"))
                if args.verification_evidence is not None else None
            )
            result = advance_pa_family_cache_transaction(
                args.cache_root, value, FILES, verification_evidence=evidence,
                recovery_policy="none", owner=args.owner,
            )
            if result.generation_directory is not None and tuple(
                record["name"] for record in json.loads(
                    (result.generation_directory / "cache_manifest.json").read_text(encoding="utf-8")
                )["files"]
            ) != FILES:
                raise ValueError("published controller cache inventory differs from the exact native Fast Adjust family")
            output = _progress(result, value)
    except (OSError, ValueError, json.JSONDecodeError, PAFamilyCacheError) as error:
        print(f"ACCELERATOR_COMPONENT_FOCUS_PA_CACHE=FAIL ERROR={error}")
        return 1
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
