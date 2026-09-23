"""Project a published component-focus PA family for MR-TOF read-only use.

This adapter reads only provider receipts and sealed cache metadata.  It never
opens a PA payload: the controller identity comes from the published cache
manifest, whose lightweight validation checks the sealed inventory and sizes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from common.simion.pa_family_cache import PAFamilyCacheError, validate_pa_family_cache_generation


class MrRuntimeReceiptError(ValueError):
    """Raised when a provider result cannot be handed to MR-TOF."""


_CONTROLLER_NAME = "orthogonal_accelerator_focus.pa0"
_EXPECTED_FILES = (
    "orthogonal_accelerator_focus.pa#",
    *(f"orthogonal_accelerator_focus.pa{index}" for index in range(10)),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(path: Path) -> dict[str, Any]:
    """Record a lightweight JSON/provider input after reading it."""
    resolved = path.resolve()
    if not resolved.is_file():
        raise MrRuntimeReceiptError(f"required provider file is missing: {resolved}")
    return {"path": str(resolved), "bytes": resolved.stat().st_size, "sha256": _sha256(resolved)}


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MrRuntimeReceiptError(f"{label} is unreadable") from error
    if not isinstance(value, dict):
        raise MrRuntimeReceiptError(f"{label} must be a JSON object")
    return value


def _record_path(record: dict[str, Any], base: Path) -> Path:
    path = Path(str(record.get("path", "")))
    return (path if path.is_absolute() else base / path).resolve()


def _verify_pa_child_source(pa_manifest_path: Path, pa_result_path: Path) -> None:
    """Bind the small PA result to its verified, terminal child manifest."""
    manifest_path = pa_manifest_path.resolve()
    manifest = _load_json(manifest_path, "provider PA child manifest")
    if (manifest.get("role") != "simulation_run_manifest" or manifest.get("status") != "success"
            or manifest.get("project") != "orthogonal_accelerator"
            or manifest.get("mode") != "component_focus_pa_build"):
        raise MrRuntimeReceiptError("provider PA child manifest is not a successful component PA build")
    config = manifest.get("run_config")
    if not isinstance(config, dict):
        raise MrRuntimeReceiptError("provider PA child manifest lacks its run config record")
    config_path = _record_path(config, manifest_path.parent)
    if config_path.parent != manifest_path.parent or _record(config_path) != {
        "path": str(config_path), "bytes": config.get("bytes"), "sha256": config.get("sha256"),
    }:
        raise MrRuntimeReceiptError("provider PA child run config identity differs from its manifest")
    result_path = pa_result_path.resolve()
    matches = [record for record in manifest.get("outputs", []) if isinstance(record, dict)
               and _record_path(record, manifest_path.parent) == result_path]
    if len(matches) != 1 or _record(result_path) != {
        "path": str(result_path), "bytes": matches[0].get("bytes"), "sha256": matches[0].get("sha256"),
    }:
        raise MrRuntimeReceiptError("provider PA result is not the verified child-manifest output")


def _controller_record(generation: Path, cache_key: str) -> tuple[dict[str, Any], Path]:
    """Return PA0's sealed-manifest identity without reading or hashing PA0."""
    try:
        cache = validate_pa_family_cache_generation(
            generation, expected_cache_key=cache_key, expected_filenames=_EXPECTED_FILES,
            verify_payload=False,
        )
    except PAFamilyCacheError as error:
        raise MrRuntimeReceiptError(f"published provider cache is not a sealed native family: {error}") from error
    controller = generation / _CONTROLLER_NAME
    record = next((item for item in cache["files"] if item["name"] == _CONTROLLER_NAME), None)
    if not isinstance(record, dict) or controller.stat().st_size != record["bytes"]:
        raise MrRuntimeReceiptError("published controller PA0 differs from sealed cache metadata")
    return {"path": str(controller.resolve()), "bytes": record["bytes"], "sha256": record["sha256"]}, generation / "cache_manifest.json"


def project(*, workflow_receipt_path: Path, pa_result_path: Path,
            pa_manifest_path: Path, campaign_path: Path, plan_path: Path) -> dict[str, Any]:
    """Return the compact, read-only MR projection of one published family."""
    workflow = _load_json(workflow_receipt_path, "provider workflow receipt")
    result = _load_json(pa_result_path, "provider PA result")
    campaign = _load_json(campaign_path, "provider campaign")
    plan = _load_json(plan_path, "provider plan")
    _verify_pa_child_source(pa_manifest_path, pa_result_path)
    if workflow.get("role") != "orthogonal_accelerator_component_focus_workflow_receipt":
        raise MrRuntimeReceiptError("workflow receipt has the wrong role")
    if workflow.get("status") != "candidate_complete":
        raise MrRuntimeReceiptError("provider workflow has not passed complete N=100 time focus")
    if result.get("disposition") not in {"published", "hit"}:
        raise MrRuntimeReceiptError("provider PA family is not published")
    generation = Path(str(result.get("generation_directory", ""))).resolve()
    if not generation.is_dir():
        raise MrRuntimeReceiptError("published provider cache generation is missing")
    cache_key, generation_sha256 = result.get("cache_key"), result.get("generation_sha256")
    if not isinstance(cache_key, str) or not isinstance(generation_sha256, str):
        raise MrRuntimeReceiptError("provider PA result lacks cache identity")
    controller_record, cache_manifest = _controller_record(generation, cache_key)
    if generation.name != generation_sha256:
        raise MrRuntimeReceiptError("published provider cache generation differs from PA result")
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
        "read_only_controller_pa0": controller_record,
        "resolved_campaign": _record(campaign_path),
        "provider_plan": _record(plan_path),
        "pa_family": {"cache_key": cache_key, "generation_sha256": generation_sha256,
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


def _owner_run_directory(output_path: Path) -> Path:
    """Require the receipt to stay in its active provider workflow run."""
    output = output_path.resolve()
    if output.name != "mrtof_runtime_receipt.json" or output.parent.name != "results":
        raise MrRuntimeReceiptError("MR runtime receipt must use its owner run results/mrtof_runtime_receipt.json path")
    run_dir = output.parent.parent
    config_path, manifest_path = run_dir / "run_config.json", run_dir / "run_manifest.json"
    config = _load_json(config_path, "owner run config")
    manifest = _load_json(manifest_path, "owner run manifest")
    if (config.get("schema_version") != 2 or config.get("project") != "orthogonal_accelerator"
            or config.get("mode") != "component_focus_workflow"
            or not isinstance(config.get("run_id"), str)
            or not config.get("capacity_ledger_lifecycle", {}).get("enabled")
            or not isinstance(config.get("artifact_retention"), dict)):
        raise MrRuntimeReceiptError("MR runtime receipt owner lacks the required lifecycle envelope")
    record = manifest.get("run_config")
    if (manifest.get("role") != "simulation_run_manifest" or manifest.get("status") != "checkpoint"
            or manifest.get("project") != config["project"] or manifest.get("mode") != config["mode"]
            or not isinstance(record, dict) or _record_path(record, run_dir) != config_path.resolve()
            or _record(config_path) != {"path": str(config_path.resolve()), "bytes": record.get("bytes"),
                                        "sha256": record.get("sha256")}):
        raise MrRuntimeReceiptError("MR runtime receipt owner manifest is not an active matching lifecycle checkpoint")
    if output.exists():
        raise MrRuntimeReceiptError("MR runtime receipt already exists; immutable owner output cannot be replaced")
    return run_dir


def write_receipt(value: dict[str, Any], output_path: Path) -> None:
    """Write only the designated receipt in a live, lifecycle-owned run."""
    _owner_run_directory(output_path)
    output_path.resolve().write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


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
        write_receipt(value, args.output)
    except (OSError, ValueError) as error:
        print(f"ORTHOGONAL_ACCELERATOR_MRTOF_RUNTIME_RECEIPT=FAIL ERROR={error}")
        return 1
    print("ORTHOGONAL_ACCELERATOR_MRTOF_RUNTIME_RECEIPT=PASS CACHE_READ_ONLY=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
