"""Resolve and validate one frozen SIMION single-flight execution profile.

This is intentionally solver-independent: it owns configuration selection and
numerical invariants, while PowerShell owns run packaging and process lifecycle.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


ERROR = "Single-flight numerical configuration is invalid."


def unique_named_profile(
    configuration: dict[str, Any], collection: str, profile_id: str, failure: str = ERROR
) -> dict[str, Any]:
    profiles = configuration.get(collection)
    matches = [
        profile for profile in profiles
        if isinstance(profile, dict) and profile.get("profile_id") == profile_id
    ] if isinstance(profiles, list) else []
    if len(matches) != 1:
        raise ValueError(failure)
    return matches[0]


def _positive_number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(ERROR) from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(ERROR)
    return number


def _positive_integer(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(ERROR)
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(ERROR) from exc
    if number < 1 or number != value:
        raise ValueError(ERROR)
    return number


def _numeric_cell(value: Any) -> dict[str, float]:
    """Validate a three-dimensional positive grid cell."""

    if not isinstance(value, dict) or set(value) != {"x", "y", "z"}:
        raise ValueError(ERROR)
    return {axis: _positive_number(value[axis]) for axis in ("x", "y", "z")}


def _numeric_reflectron_cell(value: Any) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != {"axial", "radial"}:
        raise ValueError(ERROR)
    return {axis: _positive_number(value[axis]) for axis in ("axial", "radial")}


def _resolve_accelerator_overlays(
    overlay: Any, frontend_cell_mm_xyz: dict[str, float]
) -> tuple[bool, str | None, dict[str, float] | None, list[dict[str, Any]]]:
    """Resolve legacy whole or explicit two-local accelerator PA overlays."""

    if not isinstance(overlay, dict) or overlay.get("enabled") is not True:
        return False, None, None, []
    layout = overlay.get("layout", "whole_accelerator_v1")
    common = {"enabled", "layout", "boundary_mode", "transient_disk_estimate"}
    if (
        overlay.get("boundary_mode") != "coarse_electrode_basis_dirichlet_v1"
        or frontend_cell_mm_xyz["x"] != frontend_cell_mm_xyz["y"]
    ):
        raise ValueError(ERROR)
    if layout == "whole_accelerator_v1":
        if set(overlay) - (common | {"cell_mm_xyz"}):
            raise ValueError(ERROR)
        cell = _numeric_cell(overlay.get("cell_mm_xyz"))
        specs = [{"region_id": "whole_accelerator", "cell_mm_xyz": cell}]
    elif layout == "two_local_v1":
        if set(overlay) - (common | {"entrance", "intermediate2"}):
            raise ValueError(ERROR)
        entrance = overlay.get("entrance")
        intermediate = overlay.get("intermediate2")
        if (
            not isinstance(entrance, dict)
            or set(entrance) != {"cell_mm_xyz"}
            or not isinstance(intermediate, dict)
            or set(intermediate) != {"cell_mm_xyz", "half_span_mm"}
        ):
            raise ValueError(ERROR)
        entrance_cell = _numeric_cell(entrance["cell_mm_xyz"])
        intermediate_cell = _numeric_cell(intermediate["cell_mm_xyz"])
        specs = [
            {"region_id": "entrance", "cell_mm_xyz": entrance_cell},
            {
                "region_id": "intermediate2",
                "cell_mm_xyz": intermediate_cell,
                "intermediate_half_span_mm": _positive_number(
                    intermediate["half_span_mm"]
                ),
            },
        ]
        cell = entrance_cell
    else:
        raise ValueError(ERROR)
    for spec in specs:
        cell_mm_xyz = spec["cell_mm_xyz"]
        if (
            cell_mm_xyz["x"] != frontend_cell_mm_xyz["x"]
            or cell_mm_xyz["y"] != frontend_cell_mm_xyz["y"]
            or cell_mm_xyz["z"] > frontend_cell_mm_xyz["z"]
        ):
            raise ValueError(ERROR)
    return True, layout, cell, specs


def _resolve_accelerator_main_domain(value: Any) -> dict[str, Any]:
    """Resolve the numerical extent of the fine accelerator PA.

    A full fine PA remains available for convergence reference.  The active
    full-axial core and the legacy directed corridor are numerical-domain
    declarations, not changes to the physical accelerator: omitted distant
    transverse electrode surfaces are represented by the common coarse
    electrode-basis Dirichlet family.
    """

    if value is None:
        return {"policy_id": "full_accelerator_v1"}
    if not isinstance(value, dict) or not isinstance(value.get("policy_id"), str):
        raise ValueError(ERROR)
    policy_id = value["policy_id"]
    if policy_id == "full_accelerator_v1":
        if set(value) != {"policy_id"}:
            raise ValueError(ERROR)
        return {"policy_id": policy_id}
    if policy_id in {
        "directed_kinematic_corridor_v1",
        "coarse_boundary_supported_full_axial_core_v1",
    }:
        if set(value) != {
            "policy_id", "exit_axis_positive_extent_mm", "transverse_half_span_mm"
        }:
            raise ValueError(ERROR)
        return {
            "policy_id": policy_id,
            "exit_axis_positive_extent_mm": _positive_number(
                value["exit_axis_positive_extent_mm"]
            ),
            "transverse_half_span_mm": _positive_number(
                value["transverse_half_span_mm"]
            ),
        }
    raise ValueError(ERROR)


def _resolve_accelerator_entrance_local(
    value: Any, main_cell_mm_xyz: dict[str, float]
) -> dict[str, Any] | None:
    """Resolve the small PA that owns the scanned accelerator-side aperture."""

    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "enabled",
        "cell_mm_xyz",
        "boundary_mode",
        "iob_mode",
        "domain_policy",
    } or value.get("enabled") is not True:
        raise ValueError(ERROR)
    cell = _numeric_cell(value["cell_mm_xyz"])
    if any(
        not math.isclose(cell[axis], main_cell_mm_xyz[axis], abs_tol=1e-12)
        for axis in ("x", "y", "z")
    ):
        raise ValueError(ERROR)
    if (
        value.get("boundary_mode")
        != "accelerator_main_electrode_basis_dirichlet_v1"
        or value.get("iob_mode") != "highest_priority_entrance_local_v1"
    ):
        raise ValueError(ERROR)
    policy = value.get("domain_policy")
    if not isinstance(policy, dict) or set(policy) != {
        "policy_id",
        "accelerator_side_extent_mm",
        "transverse_half_span_mm",
        "grid1_downstream_guard_mm",
    } or policy.get("policy_id") != "aperture_perturbation_local_v1":
        raise ValueError(ERROR)
    return {
        "enabled": True,
        "cell_mm_xyz": cell,
        "boundary_mode": value["boundary_mode"],
        "iob_mode": value["iob_mode"],
        "domain_policy": {
            "policy_id": policy["policy_id"],
            "accelerator_side_extent_mm": _positive_number(
                policy["accelerator_side_extent_mm"]
            ),
            "transverse_half_span_mm": _positive_number(
                policy["transverse_half_span_mm"]
            ),
            "grid1_downstream_guard_mm": _positive_number(
                policy["grid1_downstream_guard_mm"]
            ),
        },
    }


def resolve_execution_profile(
    configuration: dict[str, Any],
    *,
    frontend_grid_profile_id: str | None = None,
    oatof_numerical_profile_id: str | None = None,
    trajectory_quality_profile_id: str | None = None,
    time_integration_profile_id: str | None = None,
    maximum_time_of_flight_us: float | None = None,
    spatial_window_profile_id: str | None = None,
    include_source_region_diagnostic: bool = False,
    numerical_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one fully resolved profile or fail closed on invalid numerics."""

    try:
        if (
            configuration.get("role")
            != "rf_oatof_simion_single_flight_configuration"
            or configuration.get("clock_basis") != "canonical_instrument_time_us"
        ):
            raise ValueError(ERROR)
        selected_grid_id = frontend_grid_profile_id or configuration[
            "default_frontend_grid_profile_id"
        ]
        grid = unique_named_profile(configuration, "frontend_grid_profiles", selected_grid_id)
        frontend_cell_mm_xyz = _numeric_cell(grid.get("cell_mm_xyz"))
        raw_coarse_bridge_cell = grid.get("coarse_bridge_cell_mm_xyz")
        coarse_bridge_cell_mm_xyz = (
            frontend_cell_mm_xyz
            if raw_coarse_bridge_cell is None
            else _numeric_cell(raw_coarse_bridge_cell)
        )
        if any(
            coarse_bridge_cell_mm_xyz[axis] < frontend_cell_mm_xyz[axis]
            for axis in ("x", "y", "z")
        ):
            raise ValueError(ERROR)

        overlay_enabled, overlay_layout, overlay_cell_mm_xyz, overlay_specs = (
            _resolve_accelerator_overlays(
                grid.get("accelerator_overlay"), frontend_cell_mm_xyz
            )
        )
        accelerator_main_domain = _resolve_accelerator_main_domain(
            grid.get("accelerator_main_domain")
        )
        reference_aperture = grid.get("accelerator_main_reference_aperture_mm")
        if reference_aperture is not None:
            if not isinstance(reference_aperture, dict) or set(reference_aperture) != {
                "width", "height"
            }:
                raise ValueError(ERROR)
            reference_aperture = {
                "width": _positive_number(reference_aperture["width"]),
                "height": _positive_number(reference_aperture["height"]),
            }
        entrance_local = _resolve_accelerator_entrance_local(
            grid.get("accelerator_entrance_local"), frontend_cell_mm_xyz
        )
        if entrance_local is not None and (
            reference_aperture is None or overlay_enabled
        ):
            # The ordinary six-slot topology gives slot 6 to the entrance
            # replacement.  A simultaneous intermediate2 convergence overlay
            # requires the separately governed seven-slot profile.
            raise ValueError(ERROR)

        selected_oatof_id = oatof_numerical_profile_id or configuration[
            "default_oatof_numerical_profile_id"
        ]
        oatof = unique_named_profile(configuration, "oatof_numerical_profiles", selected_oatof_id)
        reflectron_cell_mm = _numeric_reflectron_cell(oatof.get("reflectron_cell_mm"))

        selected_trajectory_id = trajectory_quality_profile_id or configuration[
            "default_trajectory_quality_profile_id"
        ]
        trajectory = unique_named_profile(
            configuration, "trajectory_quality_profiles", selected_trajectory_id
        )
        trajectory_quality = _positive_integer(trajectory.get("trajectory_quality"))

        selected_time_id = time_integration_profile_id or configuration[
            "default_time_integration_profile_id"
        ]
        time = unique_named_profile(configuration, "time_integration_profiles", selected_time_id)
        rf_steps_per_period = _positive_integer(time.get("rf_steps_per_period"))

        if numerical_overrides is not None:
            allowed_overrides = {
                "frontend_cell_mm_xyz",
                "accelerator_overlay_cell_mm_xyz",
                "reflectron_cell_mm",
                "trajectory_quality",
                "rf_steps_per_period",
            }
            if (
                not isinstance(numerical_overrides, dict)
                or not numerical_overrides
                or set(numerical_overrides) - allowed_overrides
            ):
                raise ValueError(ERROR)
            if "frontend_cell_mm_xyz" in numerical_overrides:
                frontend_cell_mm_xyz = _numeric_cell(
                    numerical_overrides["frontend_cell_mm_xyz"]
                )
            if "accelerator_overlay_cell_mm_xyz" in numerical_overrides:
                if not overlay_enabled or overlay_layout != "whole_accelerator_v1":
                    raise ValueError(ERROR)
                overlay_cell_mm_xyz = _numeric_cell(
                    numerical_overrides["accelerator_overlay_cell_mm_xyz"]
                )
            if "reflectron_cell_mm" in numerical_overrides:
                reflectron_cell_mm = _numeric_reflectron_cell(
                    numerical_overrides["reflectron_cell_mm"]
                )
            if "trajectory_quality" in numerical_overrides:
                trajectory_quality = _positive_integer(numerical_overrides["trajectory_quality"])
            if "rf_steps_per_period" in numerical_overrides:
                rf_steps_per_period = _positive_integer(
                    numerical_overrides["rf_steps_per_period"]
                )
        if overlay_layout == "whole_accelerator_v1":
            assert overlay_cell_mm_xyz is not None
            overlay_specs = [
                {"region_id": "whole_accelerator", "cell_mm_xyz": overlay_cell_mm_xyz}
            ]
        for spec in overlay_specs:
            cell_mm_xyz = spec["cell_mm_xyz"]
            if (
                cell_mm_xyz["x"] != frontend_cell_mm_xyz["x"]
                or cell_mm_xyz["y"] != frontend_cell_mm_xyz["y"]
                or cell_mm_xyz["z"] > frontend_cell_mm_xyz["z"]
            ):
                raise ValueError(ERROR)

        maximum_tof = _positive_number(
            configuration["maximum_time_of_flight_us"]
            if maximum_time_of_flight_us is None
            else maximum_time_of_flight_us
        )
        spatial_window = (
            None
            if not spatial_window_profile_id
            else unique_named_profile(
                configuration, "spatial_window_profiles", spatial_window_profile_id
            )
        )
        source_region_diagnostic = (
            unique_named_profile(
                configuration,
                "source_region_diagnostic_profiles",
                configuration["default_source_region_diagnostic_profile_id"],
            )
            if include_source_region_diagnostic
            else None
        )
    except (KeyError, TypeError, ValueError) as exc:
        if str(exc) == ERROR:
            raise
        raise ValueError(ERROR) from exc

    return {
        "frontend_grid_profile_id": selected_grid_id,
        "frontend_cell_mm_xyz": frontend_cell_mm_xyz,
        "coarse_bridge_cell_mm_xyz": coarse_bridge_cell_mm_xyz,
        "field_overlay_id": grid.get("field_overlay_id"),
        "accelerator_overlay_enabled": overlay_enabled,
        "accelerator_overlay_layout": overlay_layout,
        "accelerator_overlay_cell_mm_xyz": overlay_cell_mm_xyz,
        "accelerator_overlay_specs": overlay_specs,
        "accelerator_main_domain": accelerator_main_domain,
        "accelerator_main_reference_aperture_mm": reference_aperture,
        "accelerator_entrance_local": entrance_local,
        "accelerator_overlay_boundary_mode": (
            "coarse_electrode_basis_dirichlet_v1" if overlay_enabled else None
        ),
        "oatof_numerical_profile_id": selected_oatof_id,
        "reflectron_cell_mm": reflectron_cell_mm,
        "trajectory_quality_profile_id": selected_trajectory_id,
        "trajectory_quality": trajectory_quality,
        "time_integration_profile_id": selected_time_id,
        "rf_steps_per_period": rf_steps_per_period,
        "maximum_time_of_flight_us": maximum_tof,
        "spatial_window_profile_id": (
            spatial_window["profile_id"] if spatial_window is not None else None
        ),
        "source_region_diagnostic_profile_id": (
            source_region_diagnostic["profile_id"]
            if source_region_diagnostic is not None
            else None
        ),
        "clock_basis": configuration["clock_basis"],
        "numerical_authority": (
            "exploration_inline_override_v1"
            if numerical_overrides is not None
            else "registered_profile_v1"
        ),
    }


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--frontend-grid-profile-id")
    parser.add_argument("--oatof-numerical-profile-id")
    parser.add_argument("--trajectory-quality-profile-id")
    parser.add_argument("--time-integration-profile-id")
    parser.add_argument("--maximum-time-of-flight-us", type=float)
    parser.add_argument("--spatial-window-profile-id")
    parser.add_argument("--include-source-region-diagnostic", action="store_true")
    parser.add_argument("--numerical-overrides", type=Path)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(
            resolve_execution_profile(
                _load(args.configuration),
                frontend_grid_profile_id=args.frontend_grid_profile_id,
                oatof_numerical_profile_id=args.oatof_numerical_profile_id,
                trajectory_quality_profile_id=args.trajectory_quality_profile_id,
                time_integration_profile_id=args.time_integration_profile_id,
                maximum_time_of_flight_us=args.maximum_time_of_flight_us,
                spatial_window_profile_id=args.spatial_window_profile_id,
                include_source_region_diagnostic=args.include_source_region_diagnostic,
                numerical_overrides=(
                    _load(args.numerical_overrides)
                    if args.numerical_overrides is not None
                    else None
                ),
            ),
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
