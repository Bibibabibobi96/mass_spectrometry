"""Project a component-focus response bank and private runtime for MR-TOF.

This adapter reads only provider receipts, sealed cache metadata, and the small
private-runtime checkpoint.  It never opens a PA payload.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from common.simion.pa_family_cache import PAFamilyCacheError, validate_pa_family_cache_generation
from common.simion.standalone_pa_response_set import (
    StandalonePaResponseSetError,
    validate_standalone_pa_response_set,
)


class MrRuntimeReceiptError(ValueError):
    """Raised when a provider result cannot be handed to MR-TOF."""


_RAW_NAME = "orthogonal_accelerator_focus.pa#"
_RECEIPT_NAME = "orthogonal_accelerator_focus.standalone_responses.json"
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


def _record_matches(path: Path, record: dict[str, Any]) -> bool:
    """Compare one manifest record without imposing hash-letter case."""
    actual = _record(path)
    return (
        actual["path"] == str(path.resolve())
        and actual["bytes"] == record.get("bytes")
        and actual["sha256"] == str(record.get("sha256", "")).lower()
    )


def _verify_pa_child_source(pa_manifest_path: Path, pa_result_path: Path) -> None:
    """Bind the small PA result to its verified, terminal child manifest."""
    manifest_path = pa_manifest_path.resolve()
    manifest = _load_json(manifest_path, "provider PA child manifest")
    if (manifest.get("role") != "simulation_run_manifest" or manifest.get("status") not in {"success", "checkpoint"}
            or manifest.get("project") != "orthogonal_accelerator"
            or manifest.get("mode") != "component_focus_pa_build"):
        raise MrRuntimeReceiptError("provider PA child manifest is not a reusable component PA build")
    config = manifest.get("run_config")
    if not isinstance(config, dict):
        raise MrRuntimeReceiptError("provider PA child manifest lacks its run config record")
    config_path = _record_path(config, manifest_path.parent)
    if config_path.parent != manifest_path.parent or not _record_matches(config_path, config):
        raise MrRuntimeReceiptError("provider PA child run config identity differs from its manifest")
    result_path = pa_result_path.resolve()
    matches = [record for record in manifest.get("outputs", []) if isinstance(record, dict)
               and _record_path(record, manifest_path.parent) == result_path]
    if len(matches) != 1 or not _record_matches(result_path, matches[0]):
        raise MrRuntimeReceiptError("provider PA result is not the verified child-manifest output")


def _verify_flight_child_source(
    flight_child: dict[str, Any], analysis_path: Path, analysis_record: dict[str, Any],
) -> None:
    manifest_path = analysis_path.parent.parent / "run_manifest.json"
    manifest = _load_json(manifest_path, "selected provider flight manifest")
    manifest_record = _record(manifest_path)
    if (manifest.get("role") != "simulation_run_manifest" or manifest.get("status") != "success"
            or manifest.get("project") != "orthogonal_accelerator"
            or manifest.get("mode") != "component_focus_flight"
            or manifest_record["sha256"] != str(flight_child.get("manifest_sha256", "")).lower()):
        raise MrRuntimeReceiptError("selected provider flight manifest is invalid")
    matches = [
        record for record in manifest.get("outputs", []) if isinstance(record, dict)
        and _record_path(record, manifest_path.parent) == analysis_path
    ]
    if (len(matches) != 1
            or matches[0].get("bytes") != analysis_record.get("bytes")
            or str(matches[0].get("sha256", "")).lower() != str(analysis_record.get("sha256", "")).lower()):
        raise MrRuntimeReceiptError("selected provider flight analysis is not its manifest output")


def _response_bank_record(
    generation: Path, cache_key: str, electrode_count: int,
) -> tuple[dict[str, Any], Path]:
    """Return only manifest-bound runtime-safe response metadata."""
    expected = (
        _RAW_NAME,
        *(f"orthogonal_accelerator_focus.pa{index}" for index in range(electrode_count + 1)),
        *(f"orthogonal_accelerator_focus.response{index}.pa" for index in range(1, electrode_count + 1)),
        _RECEIPT_NAME,
    )
    try:
        cache = validate_pa_family_cache_generation(
            generation,
            expected_cache_key=cache_key,
            expected_filenames=expected,
            verify_payload=False,
        )
        responses = validate_standalone_pa_response_set(
            generation, cache, _RECEIPT_NAME,
            expected_response_ids=range(1, electrode_count + 1),
            inventory_is_verified=True,
        )
    except (PAFamilyCacheError, StandalonePaResponseSetError) as error:
        raise MrRuntimeReceiptError(f"published provider response bank is invalid: {error}") from error
    indexed = {item["name"]: item for item in cache["files"]}
    return {
        "generation_directory": str(generation),
        "raw": indexed[_RAW_NAME],
        "receipt_name": _RECEIPT_NAME,
        "receipt": indexed[_RECEIPT_NAME],
        "response_ids": list(range(1, electrode_count + 1)),
        "responses": [
            {"response_id": item.response_id, "name": item.name,
             "bytes": item.bytes, "sha256": item.sha256}
            for item in responses
        ],
        "published_native_members_opened": False,
    }, generation / "cache_manifest.json"


def _private_runtime_record(
    result: dict[str, Any], cache_key: str, generation_sha256: str, electrode_count: int,
) -> dict[str, Any]:
    checkpoint_path = Path(str(result.get("runtime_checkpoint_path", ""))).resolve()
    checkpoint = _load_json(checkpoint_path, "provider private runtime checkpoint")
    directory = Path(str(checkpoint.get("directory", ""))).resolve()
    expected_names = [f"orthogonal_accelerator_focus.pa{index}" for index in range(electrode_count + 1)]
    members = checkpoint.get("members")
    if (
        checkpoint.get("role") != "orthogonal_accelerator_shared_runtime_checkpoint"
        or checkpoint.get("status") != "prepared"
        or checkpoint.get("cache_key") != cache_key
        or checkpoint.get("generation_sha256") != generation_sha256
        or checkpoint.get("controller_refine") != "solutions={0}"
        or checkpoint.get("response_refine_performed") is not False
        or checkpoint.get("published_native_members_opened") is not False
        or not directory.is_dir()
        or not isinstance(members, list)
        or [item.get("name") for item in members if isinstance(item, dict)] != expected_names
    ):
        raise MrRuntimeReceiptError("provider private runtime checkpoint identity differs")
    for item in members:
        path = directory / str(item["name"])
        if not path.is_file() or path.stat().st_size != item.get("bytes"):
            raise MrRuntimeReceiptError("provider private runtime member size differs")
    controller = (directory / expected_names[0]).resolve()
    if controller != Path(str(result.get("runtime_controller_path", ""))).resolve():
        raise MrRuntimeReceiptError("provider PA result points at another private runtime controller")
    return {
        "checkpoint": _record(checkpoint_path),
        "directory": str(directory),
        "controller_path": str(controller),
        "member_count": len(expected_names),
    }


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
    hard_gate = workflow.get("hard_gate")
    if (not isinstance(hard_gate, dict)
            or hard_gate.get("complete_transport_passed") is not True
            or hard_gate.get("exit_slow_energy_passed") is not True
            or hard_gate.get("exit_axial_energy_passed") is not True
            or hard_gate.get("exit_transverse_energy_passed") is not True
            or hard_gate.get("exit_transverse_velocity_bias_passed") is not True):
        raise MrRuntimeReceiptError("provider workflow has not passed transport, exit Ex/Ey/Ez, and signed x-velocity gates")
    flight_child = workflow.get("flight_child")
    analysis_record = flight_child.get("analysis") if isinstance(flight_child, dict) else None
    if not isinstance(analysis_record, dict):
        raise MrRuntimeReceiptError("provider workflow lacks its selected flight analysis")
    analysis_path = _record_path(analysis_record, workflow_receipt_path.parent)
    actual_analysis = _record(analysis_path)
    if (actual_analysis["path"] != str(analysis_path)
            or actual_analysis["bytes"] != analysis_record.get("bytes")
            or actual_analysis["sha256"] != str(analysis_record.get("sha256", "")).lower()):
        raise MrRuntimeReceiptError("selected provider flight analysis differs from the workflow receipt")
    _verify_flight_child_source(flight_child, analysis_path, analysis_record)
    analysis = _load_json(analysis_path, "selected provider flight analysis")
    assessment = workflow.get("exit_energy_assessment")
    if (analysis.get("status") != "candidate_complete"
            or analysis.get("hard_gate") != hard_gate
            or analysis.get("exit_energy_assessment") != assessment
            or not isinstance(assessment, dict) or assessment.get("passed") is not True):
        raise MrRuntimeReceiptError("selected provider flight does not substantiate the exit-energy acceptance")
    try:
        target_energy = float(assessment["target_axial_energy_per_charge_v"])
        tolerances = assessment["tolerances"]
        center_energy = assessment["center_particle"]
        cohort_energy = assessment["cohort"]
        required_numbers = (
            target_energy,
            float(tolerances["maximum_exit_slow_energy_error_per_charge_v"]),
            float(tolerances["maximum_exit_axial_energy_error_per_charge_v"]),
            float(tolerances["maximum_exit_transverse_energy_error_per_charge_v"]),
            float(tolerances["maximum_exit_transverse_velocity_bias_mm_per_us"]),
            float(center_energy["measured_exit_slow_energy_per_charge_v"]),
            float(center_energy["slow_energy_residual_per_charge_v"]),
            float(center_energy["measured_exit_axial_energy_per_charge_v"]),
            float(center_energy["axial_energy_residual_per_charge_v"]),
            float(center_energy["measured_exit_transverse_energy_per_charge_v"]),
            float(center_energy["transverse_energy_residual_per_charge_v"]),
            float(center_energy["delta_x_mm"]),
            float(center_energy["delta_vx_mm_per_us"]),
            float(cohort_energy["maximum_absolute_slow_energy_residual_per_charge_v"]),
            float(cohort_energy["maximum_absolute_axial_energy_residual_per_charge_v"]),
            float(cohort_energy["maximum_absolute_transverse_energy_residual_per_charge_v"]),
            float(cohort_energy["mean_delta_x_mm"]),
            float(cohort_energy["mean_delta_vx_mm_per_us"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise MrRuntimeReceiptError("provider exit-energy assessment is incomplete") from error
    if not all(math.isfinite(value) for value in required_numbers):
        raise MrRuntimeReceiptError("provider exit-energy assessment contains a non-finite value")
    if (center_energy.get("slow_energy_passed") is not True
            or center_energy.get("axial_energy_passed") is not True
            or center_energy.get("transverse_energy_passed") is not True
            or center_energy.get("transverse_velocity_bias_passed") is not True
            or cohort_energy.get("slow_energy_passed") is not True
            or cohort_energy.get("axial_energy_passed") is not True
            or cohort_energy.get("transverse_energy_passed") is not True
            or cohort_energy.get("transverse_velocity_bias_passed") is not True):
        raise MrRuntimeReceiptError("provider exit-energy assessment does not pass its center and cohort gates")
    published = (
        result.get("disposition") in {"published", "hit"}
        or (
            result.get("status") == "published"
            and result.get("action_required") == "complete"
        )
    )
    if not published:
        raise MrRuntimeReceiptError("provider PA family is not published")
    generation = Path(str(result.get("generation_directory", ""))).resolve()
    if not generation.is_dir():
        raise MrRuntimeReceiptError("published provider cache generation is missing")
    cache_key, generation_sha256 = result.get("cache_key"), result.get("generation_sha256")
    if not isinstance(cache_key, str) or not isinstance(generation_sha256, str):
        raise MrRuntimeReceiptError("provider PA result lacks cache identity")
    point = campaign.get("operating_point", {})
    voltages = point.get("electrode_voltages_v")
    layout = plan.get("layout", {})
    try:
        electrode_count = 4 + int(layout["ring_count"])
    except (KeyError, TypeError, ValueError) as error:
        raise MrRuntimeReceiptError("provider plan lacks its ring count") from error
    if plan.get("electrode_count") != electrode_count:
        raise MrRuntimeReceiptError("provider plan electrode count differs from its profile layout")
    if not isinstance(voltages, list) or len(voltages) != electrode_count:
        raise MrRuntimeReceiptError("provider campaign voltage count differs from its profile layout")
    response_bank, cache_manifest = _response_bank_record(generation, cache_key, electrode_count)
    private_runtime = _private_runtime_record(result, cache_key, generation_sha256, electrode_count)
    if generation.name != generation_sha256:
        raise MrRuntimeReceiptError("published provider cache generation differs from PA result")
    try:
        endpoint = [float(value) for value in voltages[1:4]]
        rings = [float(value) for value in voltages[4:]]
        gap_1, gap_2 = float(layout["gap_1_mm"]), float(layout["gap_2_mm"])
        release = float(plan["theory_seed"]["release_position_from_repeller_mm"])
        aperture_y = float(layout["aperture_height_y_mm"])
        theory_seed = plan["theory_seed"]
        target = float(theory_seed["nominal_energy_per_charge_v"] if "nominal_energy_per_charge_v" in theory_seed
                       else campaign["operating_point"]["final_energy_per_charge_v"])
        correction = float(point["finite_3d_gain_correction_v"])
        instance_center_y = float(point["instance_center_y_mm"])
        release_spec = campaign["release_spec"]
        release_center_y = float(release_spec["geometry"]["center_mm"][1])
        species = release_spec["species"]
        sampling = release_spec["sampling"]
        charge = float(species["charge_state"])
        slow_center = float(sampling["kinetic_energy"]["center_ev"]) / abs(charge)
        slow_width = float(sampling["kinetic_energy"]["full_width_ev"]) / abs(charge)
        mass = float(species["mass_amu"])
        direction = [float(value) for value in sampling["nominal_direction"]]
        geometry = release_spec["geometry"]
        release_geometry = {
            "shape": geometry["shape"], "center_mm": [float(value) for value in geometry["center_mm"]],
            "axis": geometry["axis"], "radius_mm": float(geometry["radius_mm"]),
            "height_mm": float(geometry["height_mm"]),
        }
        angular_width = float(sampling["angular_full_width_deg"])
    except (KeyError, TypeError, ValueError) as error:
        raise MrRuntimeReceiptError("provider plan lacks the MR runtime projection") from error
    if (charge == 0.0 or mass <= 0.0 or slow_width < 0.0 or len(direction) != 3
            or not all(math.isfinite(value) for value in (
                correction, instance_center_y, release_center_y, slow_center, slow_width, mass, charge,
                angular_width, release_geometry["radius_mm"], release_geometry["height_mm"],
                *direction, *release_geometry["center_mm"],
            ))):
        raise MrRuntimeReceiptError("accepted provider release is invalid")
    if not math.isclose(target, target_energy, rel_tol=0.0, abs_tol=1.0e-12):
        raise MrRuntimeReceiptError("provider exit-energy target differs from the runtime projection")
    return {
        "schema_version": 1,
        "role": "orthogonal_accelerator_mrtof_runtime_receipt",
        "status": "published_standalone_response_bank",
        "qualification": "provider_component_candidate_only__mr_system_flight_pending",
        "provider_workflow_receipt": _record(workflow_receipt_path),
        "pa_child_manifest": _record(pa_manifest_path),
        "published_cache_manifest": _record(cache_manifest),
        "standalone_response_bank": response_bank,
        "private_runtime_checkpoint": private_runtime,
        "resolved_campaign": _record(campaign_path),
        "provider_plan": _record(plan_path),
        "pa_family": {"cache_key": cache_key, "generation_sha256": generation_sha256,
                      "generation_directory": str(generation),
                      "policy": "published_native_provenance__runtime_standalone_responses_only"},
        "mrtof_projection": {
            "energy_per_charge_v": target + correction,
            "target_axial_energy_per_charge_v": target,
            "finite_3d_gain_correction_v": correction,
            "required_source_y_offset_from_accelerator_axis_mm": release_center_y - instance_center_y,
            "accepted_release": {
                "slow_energy_center_per_charge_v": slow_center,
                "slow_energy_full_width_per_charge_v": slow_width,
                "mass_th": mass,
                "charge_e": charge,
                "nominal_direction": direction,
                "angular_full_width_deg": angular_width,
                "geometry": release_geometry,
            },
            "provider_exit_energy_acceptance": assessment,
            "endpoint_voltages_v": endpoint,
            "ring_voltages_v": rings,
            "geometry": {"acceleration_direction": "-z", "gap_1_mm": gap_1, "gap_2_mm": gap_2,
                         "ring_count": electrode_count - 4,
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
            or not _record_matches(config_path, record)):
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
