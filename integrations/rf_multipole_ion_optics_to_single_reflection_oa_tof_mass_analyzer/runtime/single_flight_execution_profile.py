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
) -> dict[str, Any]:
    """Return one fully resolved profile or fail closed on invalid numerics."""

    try:
        if (
            configuration.get("role")
            != "rf_oatof_simion_single_flight_configuration"
            or configuration.get("clock_basis") != "canonical_instrument_time_us"
        ):
            raise ValueError(ERROR)
        batching_policy = configuration["batching_policy"]
        qualification_policy = configuration["resolution_qualification_policy"]
        if not isinstance(batching_policy, dict) or not isinstance(qualification_policy, dict):
            raise ValueError(ERROR)
        parallel_batch_memory_reservation_bytes = _positive_integer(
            batching_policy["parallel_batch_memory_reservation_bytes"]
        )
        required_bootstrap_resample_count = _positive_integer(
            qualification_policy["required_bootstrap_resample_count"]
        )

        selected_grid_id = frontend_grid_profile_id or configuration[
            "default_frontend_grid_profile_id"
        ]
        grid = unique_named_profile(configuration, "frontend_grid_profiles", selected_grid_id)
        cell = grid.get("cell_mm_xyz")
        if not isinstance(cell, dict) or set(cell) != {"x", "y", "z"}:
            raise ValueError(ERROR)
        frontend_cell_mm_xyz = {axis: _positive_number(cell[axis]) for axis in ("x", "y", "z")}

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
            overlay_cell = overlay.get("cell_mm_xyz")
            if not isinstance(overlay_cell, dict) or set(overlay_cell) != {"x", "y", "z"}:
                raise ValueError(ERROR)
            overlay_cell_mm_xyz = {
                axis: _positive_number(overlay_cell[axis]) for axis in ("x", "y", "z")
            }
            if (
                overlay_cell_mm_xyz["x"] != frontend_cell_mm_xyz["x"]
                or overlay_cell_mm_xyz["y"] != frontend_cell_mm_xyz["y"]
                or overlay_cell_mm_xyz["z"] > frontend_cell_mm_xyz["z"]
            ):
                raise ValueError(ERROR)

        selected_oatof_id = oatof_numerical_profile_id or configuration[
            "default_oatof_numerical_profile_id"
        ]
        oatof = unique_named_profile(configuration, "oatof_numerical_profiles", selected_oatof_id)
        reflectron = oatof.get("reflectron_cell_mm")
        if not isinstance(reflectron, dict):
            raise ValueError(ERROR)
        reflectron_cell_mm = {
            "axial": _positive_number(reflectron.get("axial")),
            "radial": _positive_number(reflectron.get("radial")),
        }

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
        "parallel_batch_memory_reservation_bytes": parallel_batch_memory_reservation_bytes,
        "required_qualification_bootstrap_resamples": required_bootstrap_resample_count,
        "clock_basis": configuration["clock_basis"],
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
            ),
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
