"""Validate the minimal S3 shared-clock pulse-capture contract."""

from __future__ import annotations

import json
import math
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
    if contract.get("schema_version") != 2 or contract.get("stage") != "S3":
        raise ValueError("S3 pulse-capture contract identity differs")
    if contract.get("status") != "nominal_cumulative_function_passed_stage_unqualified":
        raise ValueError("S3 cumulative function evidence is not recorded")
    inputs = contract["inputs"]
    stage_plan = _load(_relative(inputs["stage_plan"]))
    s2 = _load(_relative(inputs["s2_connector"]))
    spatial = _load(_relative(inputs["spatial_registration"]))
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
    if (
        spatial.get("role") != "resolved_spatial_registration_do_not_edit"
        or spatial.get("instrument_frame_id") != "oatof_global"
        or spatial.get("project_semantics", {}).get("stage") != "S2"
    ):
        raise ValueError("S3 resolved spatial-registration authority differs")
    if s2["permissions"]["s2_stage_pass_allowed"]:
        raise ValueError("S3 prototype must not silently promote S2")
    source = contract["source"]
    if source["source_particles"] != s2["functional_candidate"]["source_particles"]:
        raise ValueError("S3 and S2 source particle counts differ")
    if source["timing_state_run_id"] != s2["nominal_particle_evidence"]["run_id"]:
        raise ValueError("S3 timing state is not the accepted S2 nominal run")
    if source["clock_epoch_id"] != s2["functional_candidate"]["clock_epoch_id"]:
        raise ValueError("S3 and S2 clock epochs differ")
    identity = contract["identity_contract"]
    if (
        identity.get("canonical_state_schema")
        != "common/contracts/schemas/component_particle_state.schema.json"
        or identity.get("frame_id") != "oatof_global"
        or identity.get("clock_epoch_id_source") != "source.clock_epoch_id"
        or identity.get("species_identity_key")
        != ["species_id", "mass_amu", "charge_state"]
    ):
        raise ValueError("S3 canonical identity contract differs")
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
    expected_geometry_sources = {
        "entry_surface_source": (
            "s2_connector.nominal_registration.target_entry_center_instrument_mm"
        ),
        "port_source": (
            "s2_connector.passive_connector_geometry.downstream_entry_aperture"
        ),
        "wall_thickness_source": "oatof_baseline.geometry_mm.accelerator_shield_wall",
        "target_centroid_source": "oatof_baseline.particle_source.center_x_mm",
        "release_offset_source": (
            "s2_connector.no_pulse_field_candidate.boundary_probe_inset_mm"
        ),
    }
    if float(baseline["geometry_mm"]["accelerator_shield_wall"]) <= 0:
        raise ValueError("oaTOF accelerator shield thickness is invalid")
    if geometry != expected_geometry_sources:
        raise ValueError("S3 timing geometry sources differ")
    target_center = s2["nominal_registration"][
        "target_entry_center_instrument_mm"
    ]
    shared_target = shared_joint["physical_boundaries"]["target_entry_surface"]
    port = s2["passive_connector_geometry"]["downstream_entry_aperture"]
    if (
        target_center != shared_target["center_mm"]
        or port["center_mm"] != target_center
        or shared_target["outward_normal"] != [-1.0, 0.0, 0.0]
        or s2["nominal_registration"]["incoming_axis"] != "+x"
    ):
        raise ValueError("S3 entry surface, aperture or direction differs")
    if (
        spatial["resolved_surfaces"]["target_entry"]["in_instrument_frame"][
            "center_mm"
        ]
        != target_center
        or spatial["project_semantics"]["connector_gap_mm"]
        != s2["nominal_registration"]["connector_gap_mm"]
    ):
        raise ValueError("S3 geometry differs from resolved S2 registration")
    if (
        float(port["full_width_y_mm"])
        != float(
            shared_joint["port_sweep"][
                "selected_n100_candidate_full_width_y_mm"
            ]
        )
        or float(port["full_height_z_mm"])
        != float(shared_joint["port_sweep"]["full_height_z_mm"])
        or float(s2["no_pulse_field_candidate"]["boundary_probe_inset_mm"])
        != float(
            shared_joint["port_sweep"][
                "particle_release_offset_inside_outer_face_mm"
            ]
        )
    ):
        raise ValueError("S3 aperture or numerical release offset differs")
    common_reference = shared_joint["electrical_interface"][
        "common_potential_reference"
    ]
    if (
        float(s2["field_ownership"]["common_ground_V"])
        != float(common_reference["potential_V"])
        or float(baseline["electrodes_V"]["shield"])
        != float(common_reference["potential_V"])
        or common_reference["unit"] != "V"
    ):
        raise ValueError("S3 common-potential continuity differs")
    source_mass = float(source["target_mass_amu"])
    source_charge = source["target_charge_state"]
    if (
        not math.isfinite(source_mass)
        or source_mass <= 0
        or not isinstance(source_charge, int)
        or isinstance(source_charge, bool)
        or source_charge == 0
    ):
        raise ValueError("S3 target species selector is invalid")
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
