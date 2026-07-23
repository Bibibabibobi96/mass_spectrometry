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
INTERFACE = PROJECT_ROOT / "config" / "rf_to_oatof_interface_candidate.json"
S1 = PROJECT_ROOT / "config" / "rf_to_oatof_s1_joint_field.json"
S2 = PROJECT_ROOT / "config" / "rf_to_oatof_s2_passive_connector.json"
STAGES = {
    "s1": (
        S1,
        PROJECT_ROOT / "config" / "resolved_rf_to_oatof_s1_spatial_registration.json",
    ),
    "s2": (
        S2,
        PROJECT_ROOT / "config" / "resolved_rf_to_oatof_s2_spatial_registration.json",
    ),
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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
    interface_path: Path = INTERFACE,
    source_root: Path = REPOSITORY_ROOT,
    rf_resolved_path: Path | None = None,
    oatof_baseline_path: Path | None = None,
) -> dict[str, Any]:
    """Resolve S1 or S2 registration from existing authoritative project inputs."""
    stage = _load(stage_path)
    interface = _load(interface_path)
    rf_resolved_path = rf_resolved_path or (
        PROJECT_ROOT / stage["inputs"]["rf_resolved_geometry"]
    ).resolve()
    oatof_baseline_path = oatof_baseline_path or (
        PROJECT_ROOT / stage["inputs"]["oatof_baseline"]
    ).resolve()
    rf_resolved = _load(rf_resolved_path)
    oatof_baseline = _load(oatof_baseline_path)
    registration = stage["nominal_registration"]
    instrument_frame = registration["instrument_frame"]
    source_frame = interface["boundaries"]["source_exit_surface"]["frame_id"]
    target_frame = interface["boundaries"]["target_entry_surface"]["frame_id"]
    target_pose = registration["target_component_pose"]
    target_transform = RigidTransform(
        target_frame,
        instrument_frame,
        target_pose["rotation_component_to_instrument"],
        target_pose["translation_mm"],
    )
    target_reference = derive_oatof_entry_reference(oatof_baseline)
    target_surface = PlaneSurface(
        target_frame,
        target_reference["center_mm"],
        target_reference["normal"],
    )
    target_instrument = target_transform.transform_plane(target_surface)
    gap_field = (
        "connector_gap_mm"
        if stage.get("stage") == "S2"
        else "direct_mating_gap_mm"
    )
    gap = float(registration[gap_field])
    desired_source_instrument = tuple(
        center + gap * normal
        for center, normal in zip(
            target_instrument.center_mm,
            target_instrument.normal,
        )
    )
    source_exit_z = float(
        rf_resolved["interfaces_mm"]["exit"]["connector_z_max_mm"]
    )
    source_local_center = (0.0, 0.0, source_exit_z)
    source_rotation = registration["source_component_pose"][
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
    source_normal = _positive_axis_vector(
        rf_resolved["coordinate"]["axial_axis"]
    )
    surfaces = {
        "source_exit": PlaneSurface(
            source_frame,
            source_local_center,
            source_normal,
        ),
        "target_entry": target_surface,
    }
    common_reference = interface["electrical_interface"][
        "common_potential_reference"
    ]
    scalar_bindings = {
        "rf_axis_common_mode": {
            "value": rf_resolved["drive"]["common_mode_offset_V"],
            "unit": "V",
            "source_file": rf_resolved_path,
            "json_pointer": "/drive/common_mode_offset_V",
            "electrode_bindings": ["rf_axis_reference"],
        },
        "rf_exit_enclosure_dc": {
            "value": common_reference["potential_V"],
            "unit": "V",
            "source_file": interface_path,
            "json_pointer": (
                "/electrical_interface/common_potential_reference/potential_V"
            ),
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
            "value": common_reference["potential_V"],
            "unit": "V",
            "source_file": interface_path,
            "json_pointer": (
                "/electrical_interface/common_potential_reference/potential_V"
            ),
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
            interface_path,
            oatof_baseline_path,
            rf_resolved_path,
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
    parser.add_argument("--interface", type=Path, default=INTERFACE)
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
        args.interface,
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
