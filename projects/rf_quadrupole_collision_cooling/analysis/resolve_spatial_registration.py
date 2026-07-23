"""Resolve the authoritative RF-to-oaTOF component registration publication."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.rigid_transform import (
    FramedPosition,
    FramedVector,
    PlaneSurface,
    RigidTransform,
)
from common.contracts.spatial_registration import (
    resolve_spatial_registration,
    write_or_check_release,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parents[1]
SHARED_JOINT = (
    PROJECT_ROOT
    / "config"
    / "rf_to_oatof_shared_physical_port_joint_geometry.json"
)
S2 = PROJECT_ROOT / "config" / "rf_to_oatof_s2_passive_connector.json"
STAGES = {
    "s2": (
        S2,
        PROJECT_ROOT / "config" / "resolved_rf_to_oatof_s2_spatial_registration.json",
    ),
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_pointer(document: Any, pointer: str) -> Any:
    """Resolve one absolute JSON pointer without accepting missing keys."""
    if not pointer.startswith("/"):
        raise ValueError(f"invalid JSON pointer: {pointer}")
    value = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def _validate_shared_authority(
    shared: dict[str, Any],
    rf_resolved: dict[str, Any],
    oatof_baseline: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], float]:
    """Validate every active boundary/electrical binding in the shared joint."""
    if shared.get("role") != "rf_to_oatof_shared_physical_port_joint_geometry":
        raise ValueError("shared physical-port role differs")
    sources = {
        "rf_resolved_geometry": rf_resolved,
        "oatof_baseline": oatof_baseline,
    }
    boundaries = shared["physical_boundaries"]
    source = boundaries["source_exit_surface"]
    target = boundaries["target_entry_surface"]
    source_bindings = source["bindings"]
    z_binding = source_bindings["local_center_z_mm"]
    if float(source["local_center_mm"][2]) != float(
        _json_pointer(sources[z_binding["source_input"]], z_binding["json_pointer"])
    ):
        raise ValueError("shared source-exit center binding differs")
    normal_binding = source_bindings["outward_normal"]
    axis = _json_pointer(
        sources[normal_binding["source_input"]], normal_binding["json_pointer"]
    )
    if axis != normal_binding["expected_source_value"]:
        raise ValueError("shared source-exit normal binding differs")
    if tuple(source["outward_normal"]) != _positive_axis_vector(str(axis)):
        raise ValueError("shared source-exit outward normal differs")
    aperture = source["physical_aperture"]
    aperture_binding = aperture["source_binding"]
    if float(aperture["radius_mm"]) != float(
        _json_pointer(
            sources[aperture_binding["source_input"]],
            aperture_binding["json_pointer"],
        )
    ):
        raise ValueError("shared source-exit aperture binding differs")

    target_binding = target["reference_binding"]
    if target_binding["source_input"] != "oatof_baseline":
        raise ValueError("shared target-entry authority differs")
    for pointer in target_binding["json_pointers"]:
        _json_pointer(oatof_baseline, pointer)
    target_reference = derive_oatof_entry_reference(oatof_baseline)
    if (
        target["frame_id"]
        != oatof_baseline["coordinate_convention"]["frame_id"]
        or tuple(target["center_mm"]) != tuple(target_reference["center_mm"])
        or tuple(target["outward_normal"]) != tuple(target_reference["normal"])
    ):
        raise ValueError("shared target-entry surface binding differs")

    common = shared["electrical_interface"]["common_potential_reference"]
    if common["unit"] != "V":
        raise ValueError("shared common-potential unit differs")
    common_value = float(common["potential_V"])
    for binding in common["required_equal_source_bindings"]:
        source_document = sources[binding["source_input"]]
        if float(_json_pointer(source_document, binding["json_pointer"])) != common_value:
            raise ValueError("shared common-potential source binding differs")
    return source, target, common_value


def derive_oatof_entry_reference(target_baseline: dict[str, Any]) -> dict[str, Any]:
    """Derive the oaTOF negative-x shield outer face from target geometry."""
    geometry = target_baseline["geometry_mm"]
    source = target_baseline["particle_source"]
    axis_x = float(target_baseline["coordinate_convention"]["accelerator_axis_x"])
    inner_half = sum(
        float(geometry[key])
        for key in (
            "accelerator_bore_half",
            "accelerator_ring_width",
            "accelerator_insulation_gap",
        )
    )
    wall = float(geometry["accelerator_shield_wall"])
    return {
        "center_mm": (
            axis_x - inner_half - wall,
            float(source["center_y_mm"]),
            float(source["center_z_mm"]),
        ),
        "normal": (-1.0, 0.0, 0.0),
    }


def _positive_axis_vector(axis: str) -> tuple[float, float, float]:
    axes = {
        "x": (1.0, 0.0, 0.0),
        "y": (0.0, 1.0, 0.0),
        "z": (0.0, 0.0, 1.0),
    }
    try:
        return axes[axis.removeprefix("+")]
    except KeyError as error:
        raise ValueError(f"unsupported RF resolved axis: {axis}") from error


def resolve_stage(
    stage_path: Path,
    shared_path: Path | None = None,
    source_root: Path = REPOSITORY_ROOT,
    rf_resolved_path: Path | None = None,
    oatof_baseline_path: Path | None = None,
) -> dict[str, Any]:
    """Resolve S2 registration from existing authoritative project inputs."""
    stage = _load(stage_path)
    shared_path = shared_path or (
        PROJECT_ROOT / stage["inputs"]["shared_physical_port_joint_geometry"]
    ).resolve()
    shared = _load(shared_path)
    if shared.get("authoritative_inputs") != {
        "rf_resolved_geometry": stage["inputs"]["rf_resolved_geometry"],
        "oatof_baseline": stage["inputs"]["oatof_baseline"],
    }:
        raise ValueError("S2 and shared physical-port authoritative inputs differ")
    rf_resolved_path = rf_resolved_path or (
        PROJECT_ROOT / stage["inputs"]["rf_resolved_geometry"]
    ).resolve()
    oatof_baseline_path = oatof_baseline_path or (
        PROJECT_ROOT / stage["inputs"]["oatof_baseline"]
    ).resolve()
    rf_resolved = _load(rf_resolved_path)
    oatof_baseline = _load(oatof_baseline_path)
    source_boundary, target_boundary, common_reference_V = (
        _validate_shared_authority(shared, rf_resolved, oatof_baseline)
    )
    registration = stage["nominal_registration"]
    shared_registration = shared["nominal_registration"]
    instrument_frame = shared_registration["instrument_frame"]
    source_frame = source_boundary["frame_id"]
    target_frame = target_boundary["frame_id"]
    target_pose = shared_registration["target_component_pose"]
    target_transform = RigidTransform(
        target_frame,
        instrument_frame,
        target_pose["rotation_component_to_instrument"],
        target_pose["translation_mm"],
    )
    target_surface = PlaneSurface(
        target_frame,
        target_boundary["center_mm"],
        target_boundary["outward_normal"],
    )
    target_instrument = target_transform.transform_plane(target_surface)
    if stage.get("stage") != "S2":
        raise ValueError("only the active S2 connector registration is supported")
    gap = float(registration["connector_gap_mm"])
    desired_source_instrument = tuple(
        center + gap * normal
        for center, normal in zip(
            target_instrument.center_mm,
            target_instrument.normal,
        )
    )
    source_local_center = tuple(source_boundary["local_center_mm"])
    source_rotation = shared_registration["source_component_pose"][
        "rotation_component_to_instrument"
    ]
    rotation_only = RigidTransform(
        source_frame,
        instrument_frame,
        source_rotation,
        (0.0, 0.0, 0.0),
    )
    rotated_local_center = rotation_only.transform_vector(
        FramedVector(source_frame, source_local_center)
    ).components
    source_translation = tuple(
        desired - rotated
        for desired, rotated in zip(
            desired_source_instrument,
            rotated_local_center,
        )
    )
    poses = {
        source_frame: RigidTransform(
            source_frame,
            instrument_frame,
            source_rotation,
            source_translation,
        ),
        target_frame: target_transform,
    }
    if (
        registration["instrument_frame"] != instrument_frame
        or registration["target_component_pose"] != target_pose
        or registration["source_component_pose"][
            "rotation_component_to_instrument"
        ] != source_rotation
        or tuple(registration["source_exit_center_local_mm"])
        != source_local_center
        or tuple(registration["source_exit_center_instrument_mm"])
        != desired_source_instrument
        or tuple(registration["target_entry_center_instrument_mm"])
        != tuple(target_instrument.center_mm)
    ):
        raise ValueError("S2 nominal registration differs from shared derivation")
    if tuple(registration["source_component_pose"]["translation_mm"]) != source_translation:
        raise ValueError("S2 source pose translation differs from shared derivation")
    source_normal = tuple(source_boundary["outward_normal"])
    surfaces = {
        "source_exit": PlaneSurface(
            source_frame,
            source_local_center,
            source_normal,
        ),
        "target_entry": target_surface,
    }
    scalar_bindings = {
        "rf_axis_common_mode": {
            "value": rf_resolved["drive"]["common_mode_offset_V"],
            "unit": "V",
            "source_file": rf_resolved_path,
            "json_pointer": "/drive/common_mode_offset_V",
            "electrode_bindings": ["rf_axis_reference"],
        },
        "rf_exit_enclosure_dc": {
            "value": common_reference_V,
            "unit": "V",
            "source_file": shared_path,
            "json_pointer": "/electrical_interface/common_potential_reference/potential_V",
            "electrode_bindings": ["rf_exit_enclosure"],
        },
        "rf_peak_amplitude": {
            "value": rf_resolved["drive"][
                "rf_amplitude_V_zero_to_peak_per_group"
            ],
            "unit": "V_peak",
            "source_file": rf_resolved_path,
            "json_pointer": "/drive/rf_amplitude_V_zero_to_peak_per_group",
            "electrode_bindings": ["rf_electrode_group_1", "rf_electrode_group_2"],
        },
        "rf_frequency": {
            "value": rf_resolved["drive"]["frequency_Hz"],
            "unit": "Hz",
            "source_file": rf_resolved_path,
            "json_pointer": "/drive/frequency_Hz",
            "electrode_bindings": ["rf_electrode_group_1", "rf_electrode_group_2"],
        },
        "oatof_shield_dc": {
            "value": oatof_baseline["electrodes_V"]["shield"],
            "unit": "V",
            "source_file": oatof_baseline_path,
            "json_pointer": "/electrodes_V/shield",
            "electrode_bindings": ["oatof_accelerator_shield"],
        },
        "interface_common_reference": {
            "value": common_reference_V,
            "unit": "V",
            "source_file": shared_path,
            "json_pointer": "/electrical_interface/common_potential_reference/potential_V",
            "electrode_bindings": [
                "rf_exit_enclosure",
                "rf_axis_reference",
                "oatof_accelerator_shield",
            ],
        },
    }
    release = resolve_spatial_registration(
        registration_id="rf_quadrupole_collision_cooling_to_oa_tof",
        instrument_frame_id=instrument_frame,
        component_poses=poses,
        source_component_id=source_frame,
        target_component_id=target_frame,
        surfaces=surfaces,
        source_files=[
            oatof_baseline_path,
            rf_resolved_path,
            shared_path,
            stage_path,
        ],
        repository_root=source_root,
        scalar_bindings=scalar_bindings,
    )
    source_instrument = poses[source_frame].transform_position(
        FramedPosition(source_frame, source_local_center)
    ).coordinates_mm
    resolved_target_instrument = tuple(
        release["resolved_surfaces"]["target_entry"]["in_instrument_frame"][
            "center_mm"
        ]
    )
    displacement = tuple(
        target - source
        for source, target in zip(source_instrument, resolved_target_instrument)
    )
    separation_along_outward = -sum(
        value * normal
        for value, normal in zip(displacement, target_instrument.normal)
    )
    if not math.isclose(
        separation_along_outward,
        gap,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("resolved connector gap is inconsistent")
    release["project_semantics"] = {
        "stage": stage["stage"],
        "connector_gap_mm": gap,
        "source_exit_center_instrument_mm": list(source_instrument),
        "target_entry_center_instrument_mm": list(resolved_target_instrument),
        "source_surface_derivation": {
            "source": "rf_resolved_design.interfaces_mm.exit.connector_z_max_mm",
            "local_center_mm": list(source_local_center),
        },
        "electrical_policy": (
            "scalars are unchanged by coordinates; source, unit and electrode "
            "bindings remain authoritative"
        ),
        "commercial_solver_policy": (
            "read and validate this release; fixed-pose compatibility must fail closed"
        ),
    }
    return release


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=STAGES, default="s2")
    parser.add_argument("--stage-contract", type=Path)
    parser.add_argument("--shared-joint", type=Path)
    parser.add_argument("--source-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--rf-resolved", type=Path)
    parser.add_argument("--oatof-baseline", type=Path)
    parser.add_argument("--output", type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--write", action="store_true")
    args = parser.parse_args()
    default_stage_path, default_output = STAGES[args.stage]
    stage_path = args.stage_contract or default_stage_path
    output = args.output or default_output
    release = resolve_stage(
        stage_path,
        args.shared_joint,
        args.source_root,
        args.rf_resolved,
        args.oatof_baseline,
    )
    try:
        write_or_check_release(output, release, check=args.check)
    except ValueError as error:
        raise SystemExit(f"SPATIAL_REGISTRATION=FAIL {error}") from error
    print(f"SPATIAL_REGISTRATION=PASS STAGE={args.stage.upper()}")


if __name__ == "__main__":
    main()
