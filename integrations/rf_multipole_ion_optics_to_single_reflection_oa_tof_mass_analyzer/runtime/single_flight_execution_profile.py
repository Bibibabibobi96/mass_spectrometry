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
        qualification_policy = configuration["resolution_qualification_policy"]
        if not isinstance(qualification_policy, dict):
            raise ValueError(ERROR)
        required_bootstrap_resample_count = _positive_integer(
            qualification_policy["required_bootstrap_resample_count"]
        )

        selected_grid_id = frontend_grid_profile_id or configuration[
            "default_frontend_grid_profile_id"
        ]
        grid = unique_named_profile(configuration, "frontend_grid_profiles", selected_grid_id)
        frontend_cell_mm_xyz = _numeric_cell(grid.get("cell_mm_xyz"))

        overlay = grid.get("accelerator_overlay")
        overlay_enabled = isinstance(overlay, dict) and overlay.get("enabled") is True
        overlay_cell_mm_xyz: dict[str, float] | None = None
        if overlay_enabled:
            if (
                set(overlay) - {"enabled", "cell_mm_xyz", "boundary_mode", "transient_disk_estimate"}
                or overlay.get("boundary_mode") != "coarse_electrode_basis_dirichlet_v1"
                or len(set(frontend_cell_mm_xyz.values())) != 1
            ):
                raise ValueError(ERROR)
            overlay_cell_mm_xyz = _numeric_cell(overlay.get("cell_mm_xyz"))

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
                if not overlay_enabled:
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
        if overlay_enabled and (
            overlay_cell_mm_xyz is None
            or overlay_cell_mm_xyz["x"] != frontend_cell_mm_xyz["x"]
            or overlay_cell_mm_xyz["y"] != frontend_cell_mm_xyz["y"]
            or overlay_cell_mm_xyz["z"] > frontend_cell_mm_xyz["z"]
        ):
            raise ValueError(ERROR)

        maximum_tof = _positive_number(
            configuration["maximum_time_of_flight_us"]
            if maximum_time_of_flight_us is None or maximum_time_of_flight_us <= 0
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
        "field_overlay_id": grid.get("field_overlay_id"),
        "accelerator_overlay_enabled": overlay_enabled,
        "accelerator_overlay_cell_mm_xyz": overlay_cell_mm_xyz,
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
        "required_qualification_bootstrap_resamples": required_bootstrap_resample_count,
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
