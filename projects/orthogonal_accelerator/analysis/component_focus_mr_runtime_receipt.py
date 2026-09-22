"""Project a published component-focus PA family for MR-TOF read-only use.

This adapter deliberately reads only the small provider receipts, plan and cache
manifest.  It neither opens every PA member nor invokes SIMION.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class MrRuntimeReceiptError(ValueError):
    """Raised when a provider result cannot be handed to MR-TOF."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise MrRuntimeReceiptError(f"required provider file is missing: {resolved}")
    return {"path": str(resolved), "bytes": resolved.stat().st_size, "sha256": _sha256(resolved)}


def project(*, workflow_receipt_path: Path, pa_result_path: Path,
            pa_manifest_path: Path, campaign_path: Path, plan_path: Path) -> dict[str, Any]:
    """Return the compact, read-only MR projection of one published family."""
    try:
        workflow = json.loads(workflow_receipt_path.read_text(encoding="utf-8"))
        result = json.loads(pa_result_path.read_text(encoding="utf-8"))
        campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MrRuntimeReceiptError("provider result is unreadable") from error
    if workflow.get("role") != "orthogonal_accelerator_component_focus_workflow_receipt":
        raise MrRuntimeReceiptError("workflow receipt has the wrong role")
    if workflow.get("status") != "candidate_complete":
        raise MrRuntimeReceiptError("provider workflow has not passed complete N=100 time focus")
    if result.get("disposition") not in {"published", "hit"}:
        raise MrRuntimeReceiptError("provider PA family is not published")
    generation = Path(str(result.get("generation_directory", ""))).resolve()
    cache_manifest = generation / "cache_manifest.json"
    controller = generation / "orthogonal_accelerator_focus.pa0"
    try:
        cache = json.loads(cache_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MrRuntimeReceiptError("published provider cache manifest is unreadable") from error
    if cache.get("cache_key") != result.get("cache_key") or cache.get("generation_sha256") != result.get("generation_sha256"):
        raise MrRuntimeReceiptError("published provider cache identity differs from PA result")
    names = [record.get("name") for record in cache.get("files", [])]
    expected = ["orthogonal_accelerator_focus.pa#"] + [f"orthogonal_accelerator_focus.pa{index}" for index in range(10)]
    if names != expected:
        raise MrRuntimeReceiptError("published provider cache has the wrong native family")
    voltages = campaign.get("operating_point", {}).get("electrode_voltages_v")
    layout = plan.get("layout", {})
    if not isinstance(voltages, list) or len(voltages) != 9:
        raise MrRuntimeReceiptError("provider campaign lacks nine electrode voltages")
    try:
        endpoint = [float(value) for value in voltages[1:4]]
        rings = [float(value) for value in voltages[4:]]
        gap_1, gap_2 = float(layout["gap_1_mm"]), float(layout["gap_2_mm"])
        release = float(plan["theory_seed"]["release_position_from_repeller_mm"])
        aperture_y = float(layout["aperture_height_y_mm"])
        # The campaign contract intentionally carries only Fast-Adjust
        # voltages.  The PA plan owns the derived nominal axial energy, which
        # stays invariant while the controller varies the first-gap drop.
        theory_seed = plan["theory_seed"]
        target = float(theory_seed["nominal_energy_per_charge_v"] if "nominal_energy_per_charge_v" in theory_seed
                       else campaign["operating_point"]["final_energy_per_charge_v"])
    except (KeyError, TypeError, ValueError) as error:
        raise MrRuntimeReceiptError("provider plan lacks the MR runtime projection") from error
    return {
        "schema_version": 1,
        "role": "orthogonal_accelerator_mrtof_runtime_receipt",
        "status": "published_read_only",
        "qualification": "provider_component_candidate_only__mr_system_flight_pending",
        "provider_workflow_receipt": _record(workflow_receipt_path),
        "pa_child_manifest": _record(pa_manifest_path),
        "published_cache_manifest": _record(cache_manifest),
        "read_only_controller_pa0": _record(controller),
        "resolved_campaign": _record(campaign_path),
        "provider_plan": _record(plan_path),
        "pa_family": {"cache_key": result["cache_key"], "generation_sha256": result["generation_sha256"],
                      "generation_directory": str(generation), "policy": "published_read_only__runtime_fast_adjust"},
        "mrtof_projection": {
            "energy_per_charge_v": target,
            "target_axial_energy_per_charge_v": target,
            "finite_3d_gain_correction_v": 0.0,
            "endpoint_voltages_v": endpoint,
            "ring_voltages_v": rings,
            "geometry": {"acceleration_direction": "-z", "gap_1_mm": gap_1, "gap_2_mm": gap_2,
                         "repeller_to_exit_mm": gap_1 + gap_2,
                         "release_position_in_gap_1_mm": release,
                         "aperture_height_y_mm": aperture_y,
                         "geometry_profile_id": plan.get("geometry_profile_id")},
        },
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-receipt", type=Path, required=True)
    parser.add_argument("--pa-result", type=Path, required=True)
    parser.add_argument("--pa-manifest", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        value = project(workflow_receipt_path=args.workflow_receipt, pa_result_path=args.pa_result,
                        pa_manifest_path=args.pa_manifest, campaign_path=args.campaign, plan_path=args.plan)
    except (OSError, ValueError) as error:
        print(f"ORTHOGONAL_ACCELERATOR_MRTOF_RUNTIME_RECEIPT=FAIL ERROR={error}")
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print("ORTHOGONAL_ACCELERATOR_MRTOF_RUNTIME_RECEIPT=PASS CACHE_READ_ONLY=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
