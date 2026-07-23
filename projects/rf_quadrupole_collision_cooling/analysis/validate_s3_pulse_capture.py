"""Validate the minimal S3 shared-clock pulse-capture contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = PROJECT_ROOT / "config" / "rf_to_oatof_s3_pulse_capture.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: str) -> Path:
    return (PROJECT_ROOT / path).resolve()


def validate_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    """Return a validated S3 contract or raise for inconsistent authority."""
    contract = _load(path)
    if contract.get("schema_version") != 1 or contract.get("stage") != "S3":
        raise ValueError("S3 pulse-capture contract identity differs")
    if contract.get("status") != "nominal_cumulative_function_passed_stage_unqualified":
        raise ValueError("S3 cumulative function evidence is not recorded")
    inputs = contract["inputs"]
    stage_plan = _load(_relative(inputs["stage_plan"]))
    s2 = _load(_relative(inputs["s2_connector"]))
    shared_joint = _load(_relative(inputs["shared_physical_port_joint_geometry"]))
    pulse = _load(_relative(inputs["pulse_timing_policy"]))
    baseline = _load(_relative(inputs["oatof_baseline"]))
    stages = stage_plan.get("stages", [])
    if [item.get("id") for item in stages] != ["S2", "S3"]:
        raise ValueError("active stage plan must contain only the internal S2 step and S3 entry")
    internal_step, stage = stages
    if stage_plan.get("current_stage") != "S3":
        raise ValueError("S3 is not the current cumulative integration stage")
    governance = stage_plan.get("governance", {})
    if (
        stage_plan.get("status") != "active_cumulative_pipeline"
        or governance.get("stage_relationship") != "internal_step_then_cumulative_entry"
        or governance.get("public_entry_count") != 1
        or governance.get("internal_steps_are_not_entrypoints") is not True
        or governance.get("active_entrypoint")
        != "tests/cross_solver/run_s3_cumulative_chain.ps1"
    ):
        raise ValueError("interface stage governance does not expose one cumulative entry")
    if (
        internal_step.get("role") != "internal_passive_connector_step"
        or internal_step.get("public_entrypoint") is not False
        or internal_step.get("entrypoint")
        != "tests/comsol/run_s2_passive_connector_field.ps1"
    ):
        raise ValueError("S2 must remain an internal passive-connector step")
    if (
        stage.get("role") != "current_cumulative_entry"
        or stage.get("public_entrypoint") is not True
        or stage.get("entrypoint") != governance["active_entrypoint"]
    ):
        raise ValueError("S3 must be the sole current cumulative entry")
    if stage.get("status") != contract["status"]:
        raise ValueError("S3 stage plan and runtime contract differ")
    if s2["nominal_particle_evidence"]["status"] != "PASS":
        raise ValueError("S3 functional prototype requires the S2 nominal particle evidence")
    if shared_joint.get("role") != "rf_to_oatof_shared_physical_port_joint_geometry":
        raise ValueError("S3 shared physical-port authority differs")
    if s2["permissions"]["s2_stage_pass_allowed"]:
        raise ValueError("S3 prototype must not silently promote S2")
    source = contract["source"]
    if source["source_particles"] != s2["functional_candidate"]["source_particles"]:
        raise ValueError("S3 and S2 source particle counts differ")
    if source["timing_state_run_id"] != s2["nominal_particle_evidence"]["run_id"]:
        raise ValueError("S3 timing state is not the accepted S2 nominal run")
    if source["clock_epoch_id"] != s2["functional_candidate"]["clock_epoch_id"]:
        raise ValueError("S3 and S2 clock epochs differ")
    if pulse["method"] != "selected_species_ballistic_port_survivor_x_centroid":
        raise ValueError("S3 pulse timing method differs")
    waveform = contract["waveform"]
    if [waveform[key] for key in (
        "pre_pulse_oatof_field_scale", "pulse_oatof_field_scale",
        "post_pulse_oatof_field_scale",
    )] != [0.0, 1.0, 0.0]:
        raise ValueError("S3 finite pulse scales differ")
    if waveform["rise_fall_model"] != "ideal_finite_step":
        raise ValueError("S3 first functional waveform must be an explicit finite step")
    if float(waveform["post_pulse_tracking_time_us"]) <= 0:
        raise ValueError("S3 post-pulse tracking duration must be positive")
    geometry = contract["timing_geometry"]
    if float(baseline["geometry_mm"]["accelerator_shield_wall"]) <= 0:
        raise ValueError("oaTOF accelerator shield thickness is invalid")
    if set(geometry) != {
        "entry_surface_source", "port_source", "wall_thickness_source",
        "target_centroid_source", "release_offset_source",
    }:
        raise ValueError("S3 timing geometry sources differ")
    runtime = contract["runtime"]
    if runtime["detector_tracking_included"]:
        raise ValueError("S3 local functional runtime must not claim detector tracking")
    if runtime["minimum_active_at_pulse"] < 1 or runtime["minimum_local_accelerator_exit"] < 1:
        raise ValueError("S3 functional minima are invalid")
    claims = contract["claims"]
    if claims["compact_storage_claimed"] or claims["minimum_transmission_qualified"]:
        raise ValueError("S3 functional prototype overclaims beam performance")
    if claims["s2_stage_passed"] or claims["s3_stage_passed"] or claims["formal_gate_passed"]:
        raise ValueError("S3 functional prototype overclaims qualification")
    permissions = contract["permissions"]
    if not permissions["schedule_derivation_allowed"] or not permissions["nominal_particle_runtime_allowed"]:
        raise ValueError("S3 functional runtime is not authorized")
    if permissions["s3_stage_pass_allowed"] or permissions["formal_promotion_allowed"]:
        raise ValueError("S3 qualification must remain blocked")
    return contract


def main() -> None:
    contract = validate_contract()
    print(
        "S3_PULSE_CAPTURE=PASS "
        f"SOURCE_PARTICLES={contract['source']['source_particles']} "
        "RUNTIME_ALLOWED=true STAGE_PASS_ALLOWED=false"
    )


if __name__ == "__main__":
    main()
