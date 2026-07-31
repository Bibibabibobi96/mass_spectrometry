"""Evaluate L3 multipole convergence and converged cross-solver agreement."""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from common.contracts.particle_physics import kinetic_energy_ev
COMSOL_PRIMARY_STATE_FILE = "particle_state__primary.csv"
SUPPORTED_SOLVERS = ("COMSOL", "SIMION")
CELL_AXES = ("x", "y", "z")
PHYSICS_IDENTITY_FIELDS = (
    "model_level",
    "design_profile_id",
    "operating_mode_id",
    "operating_point_id",
)
PARTICLE_ENVELOPE_FIELDS = (
    "transverse_x_mm",
    "transverse_y_mm",
    "velocity_x_m_s",
    "velocity_y_m_s",
    "elapsed_time_us",
    "kinetic_energy_eV",
)
CANDIDATE_OBSERVABLE_FIELDS = (
    "rms_radius",
    "rms_divergence",
    "mean_energy",
    "mean_tof",
)


def normalize_simion_solver_numerics(
    numerics: dict[str, Any],
) -> dict[str, Any]:
    """Normalize SIMION spacing while keeping this frozen analysis module portable."""

    has_legacy = "cell_mm" in numerics
    has_canonical = "cell_mm_xyz" in numerics
    if has_legacy == has_canonical:
        raise ValueError(
            "SIMION numerics must define exactly one of cell_mm or cell_mm_xyz"
        )
    result = dict(numerics)
    spacing = result.pop("cell_mm") if has_legacy else result["cell_mm_xyz"]
    if has_legacy:
        spacing = {axis: spacing for axis in CELL_AXES}
    if not isinstance(spacing, dict) or set(spacing) != set(CELL_AXES):
        raise ValueError("cell_mm_xyz must contain exactly x, y, and z")
    normalized: dict[str, float] = {}
    for axis in CELL_AXES:
        value = spacing[axis]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("SIMION cell spacing must be positive finite numbers")
        normalized[axis] = float(value)
        if not math.isfinite(normalized[axis]) or normalized[axis] <= 0:
            raise ValueError("SIMION cell spacing must be positive finite numbers")
    result["cell_mm_xyz"] = normalized
    return result
SPATIAL_COMPARISON_AXES = (
    "spatial",
    "spatial_radial",
    "spatial_axial",
    "spatial_isotropic",
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _load_hashed_json(path: Path) -> tuple[dict[str, Any], str]:
    payload = path.read_bytes()
    document = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return document, hashlib.sha256(payload).hexdigest().upper()


def physical_resolved_design_sha256(resolved: dict[str, Any]) -> str:
    """Hash compiled physics while excluding compiler and authority provenance."""
    payload = copy.deepcopy(resolved)
    for field in ("compiler", "governance", "sources", "resolved_sha256"):
        payload.pop(field, None)
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def solver_name(manifest: dict[str, Any]) -> str:
    software = " ".join(str(item) for item in manifest.get("software", []))
    matches = [name for name in SUPPORTED_SOLVERS if name in software.upper()]
    if len(matches) != 1:
        raise ValueError("manifest must identify exactly one supported solver")
    return matches[0]


def manifest_record(manifest: dict[str, Any], filename: str) -> Path:
    matches = [
        Path(record["path"])
        for record in manifest.get("outputs", [])
        if Path(record["path"]).name == filename
    ]
    if len(matches) != 1 or not matches[0].is_file():
        raise ValueError(f"manifest must contain exactly one existing {filename}")
    return matches[0]


def primary_case_id(manifest: dict[str, Any]) -> str:
    """Resolve the named primary case from retained machine-readable outputs."""
    case_ids: set[str] = set()
    for record in manifest.get("outputs", []):
        path = Path(record["path"])
        if path.suffix.lower() != ".json" or not path.is_file():
            continue
        try:
            value = load_json(path).get("primary_case_id")
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if value:
            case_ids.add(str(value))
    if len(case_ids) != 1:
        raise ValueError("manifest outputs must identify exactly one primary_case_id")
    return case_ids.pop()


def primary_state_filename(manifest: dict[str, Any], solver: str) -> str:
    if solver == "COMSOL":
        return COMSOL_PRIMARY_STATE_FILE
    return f"particle_states__{primary_case_id(manifest)}.csv"


def mean_source_energy_from_particle_input(path: Path) -> float:
    """Calculate the normalization energy from the frozen solver-neutral source."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("particle source input is empty")
    particle_ids = [int(row["particle_id"]) for row in rows]
    if particle_ids != list(range(1, len(rows) + 1)):
        raise ValueError("particle source IDs must be contiguous, ordered, and one-based")
    energies = [
        kinetic_energy_ev(
            float(row["mass_amu"]),
            float(row["vx_m_s"]),
            float(row["vy_m_s"]),
            float(row["vz_m_s"]),
        )
        for row in rows
    ]
    return sum(energies) / len(energies)


def _finite_row_value(row: dict[str, Any], field: str) -> float:
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"handoff state has invalid {field}") from exc
    if not math.isfinite(value):
        raise ValueError(f"handoff state has non-finite {field}")
    return value


def handoff_observables(values: list[dict[str, Any]]) -> dict[str, float]:
    """Derive beam observables from canonical particle-state primitives."""
    if not values:
        raise ValueError("run has no transmitted handoff states")
    positions: list[tuple[float, float]] = []
    directions: list[tuple[float, float, float]] = []
    elapsed_times: list[float] = []
    energies: list[float] = []
    divergence_angles: list[float] = []
    for row in values:
        x = _finite_row_value(row, "transverse_x_mm")
        y = _finite_row_value(row, "transverse_y_mm")
        vx = _finite_row_value(row, "velocity_x_m_s")
        vy = _finite_row_value(row, "velocity_y_m_s")
        vz = _finite_row_value(row, "velocity_axial_m_s")
        speed = math.sqrt(vx * vx + vy * vy + vz * vz)
        if speed <= 0:
            raise ValueError("handoff state has zero velocity magnitude")
        positions.append((x, y))
        directions.append((vx / speed, vy / speed, vz / speed))
        divergence_angles.append(
            math.degrees(math.atan2(math.hypot(vx, vy), vz))
        )
        elapsed_times.append(_finite_row_value(row, "elapsed_time_us"))
        energies.append(_finite_row_value(row, "kinetic_energy_eV"))

    count = len(values)
    centroid_x = math.fsum(point[0] for point in positions) / count
    centroid_y = math.fsum(point[1] for point in positions) / count
    centered_spatial_spread = math.sqrt(
        math.fsum(
            (x - centroid_x) ** 2 + (y - centroid_y) ** 2
            for x, y in positions
        )
        / count
    )
    mean_direction = tuple(
        math.fsum(direction[index] for direction in directions) / count
        for index in range(3)
    )
    mean_direction_norm = math.sqrt(
        math.fsum(component * component for component in mean_direction)
    )
    if mean_direction_norm <= 0:
        raise ValueError("handoff states have undefined mean beam direction")
    mean_direction_unit = tuple(
        component / mean_direction_norm for component in mean_direction
    )
    angular_offsets = [
        math.degrees(
            math.acos(
                max(
                    -1.0,
                    min(
                        1.0,
                        math.fsum(
                            direction[index] * mean_direction_unit[index]
                            for index in range(3)
                        ),
                    ),
                )
            )
        )
        for direction in directions
    ]
    mean_energy = math.fsum(energies) / count
    return {
        "transverse_centroid_x_mm": centroid_x,
        "transverse_centroid_y_mm": centroid_y,
        "centered_spatial_rms_spread_mm": centered_spatial_spread,
        "mean_beam_direction_unit_x": mean_direction_unit[0],
        "mean_beam_direction_unit_y": mean_direction_unit[1],
        "mean_beam_direction_unit_z": mean_direction_unit[2],
        "centered_angular_rms_spread_deg": math.sqrt(
            math.fsum(offset * offset for offset in angular_offsets) / count
        ),
        "mean_energy": mean_energy,
        "centered_rms_energy_spread_eV": math.sqrt(
            math.fsum((energy - mean_energy) ** 2 for energy in energies) / count
        ),
        "mean_tof": math.fsum(elapsed_times) / count,
        # Historical, uncentered observables retained for existing contracts.
        "rms_radius": math.sqrt(
            math.fsum(x * x + y * y for x, y in positions) / count
        ),
        "rms_divergence": math.sqrt(
            math.fsum(angle * angle for angle in divergence_angles) / count
        ),
    }


def run_data(manifest_path: Path) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    if manifest.get("status") != "success":
        raise ValueError(f"source run is not successful: {manifest_path}")
    solver = solver_name(manifest)
    config = load_json(Path(manifest["run_config"]["path"]))
    numerics = load_json(Path(manifest["inputs"]["solver_numerics"]["path"]))
    if solver == "SIMION":
        numerics = normalize_simion_solver_numerics(numerics)
    resolved = load_json(Path(manifest["inputs"]["multipole_resolved_design"]["path"]))
    state_path = manifest_record(manifest, primary_state_filename(manifest, solver))
    with state_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    handoff_rows = [
        row
        for row in rows
        if row["event"] == "handoff" and row["status"] == "transmitted"
    ]
    handoff_ids = [int(row["particle_id"]) for row in handoff_rows]
    if len(handoff_ids) != len(set(handoff_ids)):
        raise ValueError("transmitted handoff particle IDs must be unique")
    handoff = dict(zip(handoff_ids, handoff_rows, strict=True))
    if not handoff:
        raise ValueError("run has no transmitted handoff states")
    source_rows = [row for row in rows if row["event"] == "source"]
    source_ids = [int(row["particle_id"]) for row in source_rows]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("source particle IDs must be unique")
    source = dict(zip(source_ids, source_rows, strict=True))
    if set(source) != set(range(1, len(source) + 1)):
        raise ValueError("source particle IDs must be contiguous and one-based")
    values = list(handoff.values())
    derived_observables = handoff_observables(values)
    exit_interface = resolved["interfaces_mm"]["exit"]
    aperture_radius = float(exit_interface["aperture_radius_mm"])
    projection_distance = float(exit_interface["census_plane_z_mm"]) - float(
        exit_interface["handoff_plane_z_mm"]
    )
    if aperture_radius <= 0 or projection_distance < 0:
        raise ValueError("exit aperture or handoff-to-census distance is invalid")
    rf_period_us = 1e6 / float(resolved["drive"]["frequency_Hz"])
    particle_source_path = Path(manifest["inputs"]["particle_source"]["path"])
    if not particle_source_path.is_file():
        raise ValueError("manifest particle_source input does not exist")
    mean_source_energy = mean_source_energy_from_particle_input(particle_source_path)
    rms_radius = derived_observables["rms_radius"]
    rms_divergence = derived_observables["rms_divergence"]
    mean_tof = derived_observables["mean_tof"]
    mean_energy = derived_observables["mean_energy"]
    maximum_rod_radius = max(
        _finite_row_value(row, "max_rod_radius_mm") for row in rows
    )
    working_radius = float(resolved["geometry_mm"]["enclosure"]["working_region_radius_mm"])
    margin_fraction = (working_radius - maximum_rod_radius) / working_radius
    return {
        "manifest": manifest,
        "config": config,
        "numerics": numerics,
        "solver": solver,
        "run_id": manifest["run_id"],
        "project": manifest["project"],
        "resolved_design_sha256": config["provenance"]["parent_resolved_design_sha256"],
        "physical_resolved_design_sha256": physical_resolved_design_sha256(
            resolved
        ),
        "particle_source_sha256": config["provenance"]["particle_source_sha256"],
        "scales": {
            "exit_aperture_radius_mm": aperture_radius,
            "handoff_to_census_distance_mm": projection_distance,
            "rf_period_us": rf_period_us,
            "mean_source_energy_eV": mean_source_energy,
        },
        "handoff_particle_ids": sorted(handoff),
        "source_particle_ids": sorted(source),
        "lost_particle_ids": sorted(set(source) - set(handoff)),
        "_handoff": handoff,
        "observables": {
            **derived_observables,
            "transmission": len(handoff) / len(source),
            "transmitted_particle_count": len(handoff),
            "maximum_rod_radius": maximum_rod_radius,
            "minimum_working_radius_margin_fraction": margin_fraction,
            "rms_radius_exit_aperture_fraction": rms_radius / aperture_radius,
            "projected_divergence_exit_aperture_fraction": (
                projection_distance
                * math.tan(math.radians(rms_divergence))
                / aperture_radius
            ),
            "mean_tof_rf_periods": mean_tof / rf_period_us,
            "mean_energy_source_fraction": mean_energy / mean_source_energy,
        },
    }


def symmetric_relative(a: float, b: float) -> float:
    scale = (abs(a) + abs(b)) / 2
    return abs(a - b) / scale if scale else 0.0


def optional_absolute_difference(
    a: float | int | None, b: float | int | None
) -> float | None:
    """Return a finite absolute difference, or None for an unavailable metric."""
    if a is None or b is None:
        return None
    left = float(a)
    right = float(b)
    if not math.isfinite(left) or not math.isfinite(right):
        return None
    return abs(left - right)


def optional_direction_separation(
    a: dict[str, Any], b: dict[str, Any]
) -> float | None:
    """Return the angle between finite unit mean-direction vectors."""
    fields = (
        "mean_beam_direction_unit_x",
        "mean_beam_direction_unit_y",
        "mean_beam_direction_unit_z",
    )
    try:
        left = tuple(float(a[field]) for field in fields)
        right = tuple(float(b[field]) for field in fields)
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (*left, *right)):
        return None
    left_norm = math.sqrt(math.fsum(value * value for value in left))
    right_norm = math.sqrt(math.fsum(value * value for value in right))
    if left_norm <= 0 or right_norm <= 0:
        return None
    cosine = math.fsum(
        left[index] * right[index] for index in range(3)
    ) / (left_norm * right_norm)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def optional_centroid_separation(
    a: dict[str, Any], b: dict[str, Any]
) -> float | None:
    """Return transverse centroid-vector separation for finite components."""
    fields = ("transverse_centroid_x_mm", "transverse_centroid_y_mm")
    try:
        left = tuple(float(a[field]) for field in fields)
        right = tuple(float(b[field]) for field in fields)
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (*left, *right)):
        return None
    return math.hypot(left[0] - right[0], left[1] - right[1])


def observable_differences(
    a: dict[str, Any], b: dict[str, Any]
) -> dict[str, float | None]:
    ao = a["observables"]
    bo = b["observables"]
    differences = {
        "transmitted_particle_count_difference": abs(
            ao["transmitted_particle_count"] - bo["transmitted_particle_count"]
        ),
        "rms_radius_exit_aperture_fraction_difference": abs(
            ao["rms_radius_exit_aperture_fraction"]
            - bo["rms_radius_exit_aperture_fraction"]
        ),
        "projected_divergence_exit_aperture_fraction_difference": abs(
            ao["projected_divergence_exit_aperture_fraction"]
            - bo["projected_divergence_exit_aperture_fraction"]
        ),
        "mean_tof_rf_period_difference": abs(
            ao["mean_tof_rf_periods"] - bo["mean_tof_rf_periods"]
        ),
        "mean_energy_source_fraction_difference": abs(
            ao["mean_energy_source_fraction"]
            - bo["mean_energy_source_fraction"]
        ),
        "transmission_absolute_difference": abs(
            ao["transmission"] - bo["transmission"]
        ),
        "mean_tof_relative_difference": symmetric_relative(ao["mean_tof"], bo["mean_tof"]),
        "rms_radius_relative_difference": symmetric_relative(ao["rms_radius"], bo["rms_radius"]),
        "rms_divergence_relative_difference": symmetric_relative(
            ao["rms_divergence"], bo["rms_divergence"]
        ),
        "mean_energy_relative_difference": symmetric_relative(
            ao["mean_energy"], bo["mean_energy"]
        ),
        "rms_radius_absolute_difference_mm": optional_absolute_difference(
            ao["rms_radius"], bo["rms_radius"]
        ),
        "rms_divergence_absolute_difference_deg": optional_absolute_difference(
            ao["rms_divergence"], bo["rms_divergence"]
        ),
        "mean_energy_absolute_difference_eV": optional_absolute_difference(
            ao["mean_energy"], bo["mean_energy"]
        ),
        "rms_energy_spread_absolute_difference_eV": optional_absolute_difference(
            ao.get("rms_energy_spread"), bo.get("rms_energy_spread")
        ),
        "sample_std_energy_spread_absolute_difference_eV": (
            optional_absolute_difference(
                ao.get("sample_std_energy_spread"),
                bo.get("sample_std_energy_spread"),
            )
        ),
        "transverse_centroid_vector_difference_mm": optional_centroid_separation(
            ao, bo
        ),
        "centered_spatial_rms_spread_absolute_difference_mm": (
            optional_absolute_difference(
                ao.get("centered_spatial_rms_spread_mm"),
                bo.get("centered_spatial_rms_spread_mm"),
            )
        ),
        "mean_beam_direction_separation_deg": optional_direction_separation(
            ao, bo
        ),
        "centered_angular_rms_spread_absolute_difference_deg": (
            optional_absolute_difference(
                ao.get("centered_angular_rms_spread_deg"),
                bo.get("centered_angular_rms_spread_deg"),
            )
        ),
        "centered_rms_energy_spread_absolute_difference_eV": (
            optional_absolute_difference(
                ao.get("centered_rms_energy_spread_eV"),
                bo.get("centered_rms_energy_spread_eV"),
            )
        ),
    }
    common_ids = sorted(set(a["_handoff"]) & set(b["_handoff"]))
    if common_ids:
        def paired_rms(fields: tuple[str, ...]) -> float:
            return math.sqrt(
                sum(
                    sum(
                        (
                            float(a["_handoff"][particle_id][field])
                            - float(b["_handoff"][particle_id][field])
                        )
                        ** 2
                        for field in fields
                    )
                    for particle_id in common_ids
                )
                / len(common_ids)
            )

        differences.update(
            paired_transverse_position_rms_difference_mm=paired_rms(
                ("transverse_x_mm", "transverse_y_mm")
            ),
            paired_transverse_velocity_rms_difference_m_s=paired_rms(
                ("velocity_x_m_s", "velocity_y_m_s")
            ),
            paired_elapsed_time_rms_difference_us=paired_rms(("elapsed_time_us",)),
            paired_energy_rms_difference_eV=paired_rms(("kinetic_energy_eV",)),
        )
    return differences


def compose_engineering_progression_contract(
    policy: dict[str, Any],
    functional_contract: dict[str, Any],
    *,
    functional_contract_sha256: str,
) -> dict[str, Any]:
    """Bind functional acceptance to the decomposed engineering capability."""
    supported_statuses = {
        "DRAFT_PENDING_ENERGY_THRESHOLDS",
        "ACTIVE_ENGINEERING_PROGRESSION_POLICY",
    }
    policy_status = policy.get("status")
    if (
        policy.get("role")
        != "multipole_engineering_progression_acceptance_contract"
        or policy_status not in supported_statuses
    ):
        raise ValueError("engineering progression policy identity differs")
    functional_binding = policy.get("functional_acceptance")
    if not isinstance(functional_binding, dict):
        raise ValueError("engineering progression functional binding is missing")
    if (
        functional_binding.get("required_result") != "PASS"
        or str(functional_binding.get("sha256", "")).upper()
        != functional_contract_sha256.upper()
    ):
        raise ValueError("engineering progression functional binding is stale")
    if functional_contract.get("claim_profile") != "functional_transport":
        raise ValueError("functional acceptance claim profile differs")

    comparison_kinds = policy.get("scope", {}).get("comparison_kinds")
    if comparison_kinds != ["same_solver_discretization", "cross_solver"]:
        raise ValueError("engineering progression comparison kinds differ")
    continuous = policy.get("continuous_engineering_acceptance")
    if not isinstance(continuous, dict):
        raise ValueError("continuous engineering acceptance is missing")
    if (
        continuous.get("comparison_operator")
        != "absolute_difference_less_than_or_equal"
        or continuous.get("all_approved_thresholds_required") is not True
        or continuous.get("energy_thresholds_required_before_activation")
        is not True
    ):
        raise ValueError("engineering progression observable contract differs")
    missing_result = continuous.get("missing_metric_result")
    if missing_result != "NOT_EVALUATED_DO_NOT_PROGRESS":
        raise ValueError("engineering progression missing-metric policy differs")

    policy_metrics = {
        ("spatial_observables", "centroid_position_difference_mm"): (
            "transverse_centroid_vector_difference_mm",
            False,
        ),
        ("spatial_observables", "centered_spatial_spread_difference_mm"): (
            "centered_spatial_rms_spread_absolute_difference_mm",
            False,
        ),
        ("angular_observables", "mean_direction_difference_deg"): (
            "mean_beam_direction_separation_deg",
            False,
        ),
        ("angular_observables", "centered_angular_spread_difference_deg"): (
            "centered_angular_rms_spread_absolute_difference_deg",
            False,
        ),
        ("energy_observables", "mean_energy_difference_eV"): (
            "mean_energy_absolute_difference_eV",
            True,
        ),
        ("energy_observables", "centered_energy_spread_difference_eV"): (
            "centered_rms_energy_spread_absolute_difference_eV",
            True,
        ),
    }
    maximum_limits = {}
    pending_metrics = []
    for (section_name, policy_name), (
        metric,
        may_be_pending,
    ) in policy_metrics.items():
        section = continuous.get(section_name)
        entry = section.get(policy_name) if isinstance(section, dict) else None
        if not isinstance(entry, dict):
            raise ValueError(
                f"engineering progression policy lacks {section_name}.{policy_name}"
            )
        value = entry.get("maximum")
        if value is None:
            if not may_be_pending:
                raise ValueError(
                    "approved spatial and angular limits must be present"
                )
            pending_metrics.append(metric)
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            raise ValueError(
                "engineering progression limits must be finite and nonnegative"
            )
        maximum_limits[metric] = float(value)
    if policy_status == "ACTIVE_ENGINEERING_PROGRESSION_POLICY" and pending_metrics:
        raise ValueError("active engineering policy lacks required energy thresholds")

    result = copy.deepcopy(functional_contract)
    for acceptance_name in (
        "same_solver_acceptance",
        "cross_solver_acceptance",
    ):
        acceptance = result.get(acceptance_name)
        if not isinstance(acceptance, dict):
            raise ValueError(
                f"functional contract lacks {acceptance_name}"
            )
        maximum = acceptance.get("maximum")
        if not isinstance(maximum, dict):
            raise ValueError(f"{acceptance_name}.maximum must be an object")
        maximum.update(maximum_limits)
    result["claim_profile"] = "engineering_progression"
    result["claim_limit"] = policy["claim_limit"]
    result["missing_metric_result"] = missing_result
    result["engineering_required_difference_metrics"] = [
        *maximum_limits,
        *pending_metrics,
    ]
    result["pending_required_threshold_metrics"] = pending_metrics
    result["engineering_progression_policy"] = {
        "contract_id": policy["contract_id"],
        "functional_contract_sha256": functional_contract_sha256.upper(),
        "status": policy_status,
    }
    return result


def load_engineering_progression_contract(
    policy_path: Path,
    functional_contract_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load, hash, bind, and compose the shared engineering contract."""
    policy_path = policy_path.resolve()
    functional_contract_path = functional_contract_path.resolve()
    policy, policy_sha256 = _load_hashed_json(policy_path)
    functional_contract, functional_sha256 = _load_hashed_json(
        functional_contract_path
    )
    binding = policy.get("functional_acceptance")
    if not isinstance(binding, dict) or not isinstance(binding.get("path"), str):
        raise ValueError("engineering progression functional path is missing")
    declared_path = binding["path"].replace("\\", "/").strip("/")
    actual_path = functional_contract_path.as_posix()
    if not declared_path or not (
        actual_path == declared_path
        or actual_path.endswith("/" + declared_path)
    ):
        raise ValueError("engineering progression functional path differs")
    contract = compose_engineering_progression_contract(
        policy,
        functional_contract,
        functional_contract_sha256=functional_sha256,
    )
    provenance = {
        "policy": {
            "path": str(policy_path),
            "sha256": policy_sha256,
            "contract_id": policy["contract_id"],
            "status": policy["status"],
        },
        "functional_contract": {
            "path": str(functional_contract_path),
            "sha256": functional_sha256,
            "contract_id": functional_contract["contract_id"],
        },
    }
    return contract, provenance


def _closed_interval(center: float, half_width: float) -> list[float]:
    if not math.isfinite(center) or not math.isfinite(half_width) or half_width < 0:
        raise ValueError("interval center and half-width must be finite and nonnegative")
    return [center - half_width, center + half_width]


def _same_particle_ids(runs: list[dict[str, Any]]) -> bool:
    return all(
        run["handoff_particle_ids"] == runs[0]["handoff_particle_ids"]
        for run in runs[1:]
    )


def standalone_candidate_envelope(
    solver_runs: dict[str, dict[str, dict[str, Any]]],
    minimum_transmission: float = 0.8,
) -> dict[str, Any]:
    """Build a conservative union of converged COMSOL and SIMION intervals.

    Each solver contributes a nominal run and its adjacent spatial and temporal
    refinements.  The numerical half-width is the larger absolute change from
    nominal along those two axes.  Solver intervals are then unioned; their
    center-to-center difference is therefore never treated as a separately
    invented percentage tolerance.
    """

    if set(solver_runs) != set(SUPPORTED_SOLVERS):
        raise ValueError("candidate envelope requires COMSOL and SIMION")
    required_levels = {"nominal", "spatial_refined", "temporal_refined"}
    all_runs: list[dict[str, Any]] = []
    per_solver: dict[str, Any] = {}
    identity_errors: list[str] = []
    for solver in SUPPORTED_SOLVERS:
        levels = solver_runs[solver]
        if set(levels) != required_levels:
            raise ValueError(
                f"{solver} candidate runs must be nominal, spatial_refined, "
                "and temporal_refined"
            )
        nominal = levels["nominal"]
        spatial = levels["spatial_refined"]
        temporal = levels["temporal_refined"]
        runs = [nominal, spatial, temporal]
        all_runs.extend(runs)
        if any(run["solver"] != solver for run in runs):
            identity_errors.append(f"{solver} run labels differ from solver")
        identity_errors.extend(
            f"{solver} spatial: {error}"
            for error in validate_identity(nominal, spatial, "spatial")
        )
        identity_errors.extend(
            f"{solver} temporal: {error}"
            for error in validate_identity(nominal, temporal, "temporal")
        )
        if not _same_particle_ids(runs):
            identity_errors.append(f"{solver} adjacent numerical particle IDs differ")

        particle_intervals: dict[str, Any] = {}
        if _same_particle_ids(runs):
            for particle_id in nominal["handoff_particle_ids"]:
                fields = {}
                for field in PARTICLE_ENVELOPE_FIELDS:
                    center = float(nominal["_handoff"][particle_id][field])
                    spatial_change = abs(
                        center - float(spatial["_handoff"][particle_id][field])
                    )
                    temporal_change = abs(
                        center - float(temporal["_handoff"][particle_id][field])
                    )
                    half_width = max(spatial_change, temporal_change)
                    fields[field] = {
                        "nominal": center,
                        "numerical_half_width": half_width,
                        "interval": _closed_interval(center, half_width),
                    }
                particle_intervals[str(particle_id)] = fields

        observable_intervals = {}
        for field in CANDIDATE_OBSERVABLE_FIELDS:
            center = float(nominal["observables"][field])
            half_width = max(
                abs(center - float(spatial["observables"][field])),
                abs(center - float(temporal["observables"][field])),
            )
            observable_intervals[field] = {
                "nominal": center,
                "numerical_half_width": half_width,
                "interval": _closed_interval(center, half_width),
            }
        per_solver[solver] = {
            "run_ids": {level: levels[level]["run_id"] for level in sorted(levels)},
            "handoff_particle_ids": nominal["handoff_particle_ids"],
            "lost_particle_ids": nominal.get("lost_particle_ids", []),
            "particle_intervals": particle_intervals,
            "observable_intervals": observable_intervals,
        }

    nominal_runs = [solver_runs[solver]["nominal"] for solver in SUPPORTED_SOLVERS]
    if not _same_particle_ids(nominal_runs):
        identity_errors.append("cross-solver nominal particle IDs differ")
    for solver in SUPPORTED_SOLVERS[1:]:
        identity_errors.extend(
            f"cross-solver: {error}"
            for error in validate_identity(
                solver_runs[SUPPORTED_SOLVERS[0]]["nominal"],
                solver_runs[solver]["nominal"],
                "cross_solver",
            )
        )

    union_observables = {}
    for field in CANDIDATE_OBSERVABLE_FIELDS:
        intervals = [
            per_solver[solver]["observable_intervals"][field]["interval"]
            for solver in SUPPORTED_SOLVERS
        ]
        union_observables[field] = [
            min(interval[0] for interval in intervals),
            max(interval[1] for interval in intervals),
        ]

    union_particles: dict[str, Any] = {}
    common_ids = set(per_solver[SUPPORTED_SOLVERS[0]]["particle_intervals"])
    common_ids &= set(per_solver[SUPPORTED_SOLVERS[1]]["particle_intervals"])
    for particle_id in sorted(common_ids, key=int):
        fields = {}
        for field in PARTICLE_ENVELOPE_FIELDS:
            intervals = [
                per_solver[solver]["particle_intervals"][particle_id][field][
                    "interval"
                ]
                for solver in SUPPORTED_SOLVERS
            ]
            fields[field] = [
                min(interval[0] for interval in intervals),
                max(interval[1] for interval in intervals),
            ]
        x_interval = fields["transverse_x_mm"]
        y_interval = fields["transverse_y_mm"]
        radial_upper = math.hypot(
            max(abs(value) for value in x_interval),
            max(abs(value) for value in y_interval),
        )
        union_particles[particle_id] = {
            "fields": fields,
            "worst_transverse_radius_mm": radial_upper,
        }

    aperture_radius = min(
        float(run["scales"]["exit_aperture_radius_mm"]) for run in all_runs
    )
    worst_radius = max(
        (
            particle["worst_transverse_radius_mm"]
            for particle in union_particles.values()
        ),
        default=math.inf,
    )
    checks = {
        "identity": not identity_errors,
        "minimum_transmission": all(
            float(run["observables"]["transmission"]) >= minimum_transmission
            for run in all_runs
        ),
        "exact_handoff_particle_ids": _same_particle_ids(all_runs),
        "positive_rod_margin": all(
            float(run["observables"]["minimum_working_radius_margin_fraction"]) > 0
            for run in all_runs
        ),
        "positive_aperture_margin": worst_radius < aperture_radius,
    }
    return {
        "schema_version": 1,
        "role": "multipole_standalone_candidate_envelope",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "method": (
            "per-solver max(spatial adjacent change, temporal adjacent change), "
            "followed by closed-interval union across solvers"
        ),
        "minimum_transmission": minimum_transmission,
        "identity_errors": identity_errors,
        "checks": checks,
        "per_solver": per_solver,
        "union": {
            "observable_intervals": union_observables,
            "particle_intervals": union_particles,
            "exit_aperture_radius_mm": aperture_radius,
            "worst_transverse_radius_mm": worst_radius,
            "minimum_aperture_margin_mm": aperture_radius - worst_radius,
        },
        "claim_limit": (
            "Numerical Candidate envelope only; no mode superiority or Formal "
            "mechanical claim."
        ),
    }


def without_path(value: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    parent: Any = result
    for key in path[:-1]:
        parent = parent[key]
    del parent[path[-1]]
    return result


def physics_identity(config: dict[str, Any]) -> dict[str, Any]:
    """Return the run-config fields that bind one multipole physics case."""
    parameters = config.get("parameters")
    if not isinstance(parameters, dict):
        raise ValueError("run config parameters must be an object")
    missing = [name for name in PHYSICS_IDENTITY_FIELDS if name not in parameters]
    if "mode" not in config:
        missing.append("mode")
    if missing:
        raise ValueError(
            "run config is missing physics identity fields: " + ", ".join(missing)
        )
    return {
        "mode": config["mode"],
        **{name: parameters[name] for name in PHYSICS_IDENTITY_FIELDS},
    }


def validate_identity(
    baseline: dict[str, Any], refined: dict[str, Any], axis: str
) -> list[str]:
    errors = []
    identity_fields = ["project", "particle_source_sha256"]
    identity_fields.append(
        "physical_resolved_design_sha256"
        if axis == "mesh_strategy"
        else "resolved_design_sha256"
    )
    for field in identity_fields:
        if baseline[field] != refined[field]:
            errors.append(f"{field} differs")
    if baseline["scales"] != refined["scales"]:
        errors.append("normalization scales differ")
    if axis == "cross_solver":
        if baseline["solver"] == refined["solver"]:
            errors.append("cross-solver comparison requires different solvers")
        return errors
    if baseline["solver"] != refined["solver"]:
        errors.append("same-solver comparison requires one solver")
        return errors
    solver = baseline["solver"]
    if axis == "mesh_strategy":
        try:
            if physics_identity(baseline["config"]) != physics_identity(
                refined["config"]
            ):
                errors.append("physics identity differs")
        except (KeyError, ValueError) as exc:
            errors.append(str(exc))
        coarse = baseline["numerics"]
        fine = refined["numerics"]
        coarse_mesh = coarse.get("mesh")
        fine_mesh = fine.get("mesh")
        if not isinstance(coarse_mesh, dict) or not isinstance(fine_mesh, dict):
            errors.append("mesh-strategy comparison requires mesh objects")
        else:
            if without_path(coarse, ("mesh",)) != without_path(fine, ("mesh",)):
                errors.append("non-mesh solver numerics differ")
            if coarse_mesh == fine_mesh:
                errors.append("mesh objects do not differ")
            if coarse_mesh.get("strategy") == fine_mesh.get("strategy"):
                errors.append("mesh strategies do not differ")
    elif axis in SPATIAL_COMPARISON_AXES:
        coarse = baseline["numerics"]
        fine = refined["numerics"]
        if solver == "COMSOL":
            if axis != "spatial":
                errors.append(
                    "COMSOL supports only the generic spatial comparison axis"
                )
                return errors
            candidate_paths = (
                ("mesh", "working_region_maximum_element_size_mm"),
                (
                    "mesh",
                    "hybrid",
                    "sensitive_region",
                    "maximum_element_size_mm",
                ),
                (
                    "mesh",
                    "hybrid",
                    "sensitive_region",
                    "exit_interface_refinement",
                    "maximum_element_size_mm",
                ),
            )
            changed_paths = []
            for candidate_path in candidate_paths:
                coarse_value: Any = coarse
                fine_value: Any = fine
                try:
                    for key in candidate_path:
                        coarse_value = coarse_value[key]
                        fine_value = fine_value[key]
                except (KeyError, TypeError):
                    continue
                if coarse_value != fine_value:
                    changed_paths.append(candidate_path)
            if len(changed_paths) != 1:
                errors.append(
                    "COMSOL spatial comparison must change exactly one supported "
                    "mesh-size axis"
                )
                return errors
            path = changed_paths[0]
            if without_path(coarse, path) != without_path(fine, path):
                errors.append("non-spatial solver numerics differ")
            coarse_value = coarse
            fine_value = fine
            for key in path:
                coarse_value = coarse_value[key]
                fine_value = fine_value[key]
            if not float(fine_value) < float(coarse_value):
                errors.append("refined spatial discretization is not smaller")
        else:
            try:
                coarse = normalize_simion_solver_numerics(coarse)
                fine = normalize_simion_solver_numerics(fine)
            except ValueError as exc:
                errors.append(str(exc))
                return errors
            coarse_cell = coarse["cell_mm_xyz"]
            fine_cell = fine["cell_mm_xyz"]
            coarse_without_cell = dict(coarse)
            fine_without_cell = dict(fine)
            del coarse_without_cell["cell_mm_xyz"]
            del fine_without_cell["cell_mm_xyz"]
            if coarse_without_cell != fine_without_cell:
                errors.append("non-spatial solver numerics differ")
            refined_axes = {
                "spatial": set(CELL_AXES),
                "spatial_radial": {"x", "y"},
                "spatial_axial": {"z"},
                "spatial_isotropic": set(CELL_AXES),
            }[axis]
            for cell_axis in CELL_AXES:
                coarse_value = float(coarse_cell[cell_axis])
                fine_value = float(fine_cell[cell_axis])
                if cell_axis in refined_axes:
                    if not fine_value < coarse_value:
                        errors.append(
                            f"refined SIMION {cell_axis}-cell spacing is not smaller"
                        )
                elif fine_value != coarse_value:
                    errors.append(
                        f"non-target SIMION {cell_axis}-cell spacing differs"
                    )
    elif axis == "temporal":
        path = ("trajectory", "rf_steps_per_period")
        coarse = baseline["numerics"]
        fine = refined["numerics"]
        if without_path(coarse, path) != without_path(fine, path):
            errors.append("non-temporal solver numerics differ")
        if not int(fine["trajectory"]["rf_steps_per_period"]) > int(
            coarse["trajectory"]["rf_steps_per_period"]
        ):
            errors.append("refined RF steps per period is not larger")
    else:
        errors.append(f"unsupported comparison axis: {axis}")
    return errors


def evaluate(
    baseline: dict[str, Any],
    refined: dict[str, Any],
    axis: str,
    contract: dict[str, Any],
) -> dict[str, Any]:
    required_acceptance = (
        ("same_solver_acceptance",)
        if axis == "mesh_strategy"
        else ("same_solver_acceptance", "cross_solver_acceptance")
    )
    for name in required_acceptance:
        if name not in contract:
            raise ValueError(
                "method-only contract cannot qualify results; supply a preregistered "
                f"applicable contract containing {name}"
            )
    errors = validate_identity(baseline, refined, axis)
    differences = observable_differences(baseline, refined)
    acceptance_name = (
        "cross_solver_acceptance" if axis == "cross_solver"
        else "same_solver_acceptance"
    )
    acceptance = contract[acceptance_name]
    maximum = acceptance.get("maximum")
    if axis == "mesh_strategy" and maximum is not None and not isinstance(
        maximum, dict
    ):
        raise ValueError(
            "mesh-strategy same_solver_acceptance.maximum must be an object"
        )
    if axis == "mesh_strategy" and set(maximum or {}) - {
        "transmitted_particle_count_difference"
    }:
        raise ValueError(
            "mesh-strategy functional screening cannot apply continuous "
            "difference limits"
        )
    if axis != "mesh_strategy" and (
        not isinstance(maximum, dict) or not maximum
    ):
        raise ValueError(f"{acceptance_name}.maximum must define accepted differences")
    checks: dict[str, bool] = {}
    missing_metric_checks: set[str] = set()
    for name, limit in (maximum or {}).items():
        if name not in differences:
            raise ValueError(f"{acceptance_name}.maximum has unknown metric {name}")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, (int, float))
            or not math.isfinite(float(limit))
            or float(limit) < 0
        ):
            raise ValueError(f"{acceptance_name}.maximum.{name} must be finite")
        value = differences[name]
        if value is None or not math.isfinite(float(value)):
            checks[name] = False
            missing_metric_checks.add(name)
        else:
            checks[name] = float(value) <= float(limit)
    for name, minimum in acceptance.get("minimum_each_run", {}).items():
        if (
            isinstance(minimum, bool)
            or not isinstance(minimum, (int, float))
            or not math.isfinite(float(minimum))
        ):
            raise ValueError(f"{acceptance_name}.minimum_each_run.{name} is invalid")
        baseline_value = baseline["observables"].get(name)
        refined_value = refined["observables"].get(name)
        checks[f"baseline_{name}_minimum"] = (
            isinstance(baseline_value, (int, float))
            and not isinstance(baseline_value, bool)
            and math.isfinite(float(baseline_value))
            and float(baseline_value) >= float(minimum)
        )
        checks[f"refined_or_peer_{name}_minimum"] = (
            isinstance(refined_value, (int, float))
            and not isinstance(refined_value, bool)
            and math.isfinite(float(refined_value))
            and float(refined_value) >= float(minimum)
        )
    for name in acceptance.get("positive_each_run", []):
        baseline_value = baseline["observables"].get(name)
        refined_value = refined["observables"].get(name)
        checks[f"baseline_{name}_positive"] = (
            isinstance(baseline_value, (int, float))
            and not isinstance(baseline_value, bool)
            and math.isfinite(float(baseline_value))
            and float(baseline_value) > 0
        )
        checks[f"refined_or_peer_{name}_positive"] = (
            isinstance(refined_value, (int, float))
            and not isinstance(refined_value, bool)
            and math.isfinite(float(refined_value))
            and float(refined_value) > 0
        )
    baseline_ids = baseline.get("handoff_particle_ids")
    refined_ids = refined.get("handoff_particle_ids")
    baseline_handoff = baseline.get("_handoff")
    refined_handoff = refined.get("_handoff")
    exact_handoff_ids = (
        isinstance(baseline_ids, list)
        and isinstance(refined_ids, list)
        and len(baseline_ids) == len(set(baseline_ids))
        and len(refined_ids) == len(set(refined_ids))
        and isinstance(baseline_handoff, dict)
        and isinstance(refined_handoff, dict)
        and baseline_ids == sorted(baseline_handoff)
        and refined_ids == sorted(refined_handoff)
        and baseline_ids == refined_ids
    )
    checks["handoff_particle_id_sets"] = exact_handoff_ids
    nonmissing_failure = any(
        not passed and name not in missing_metric_checks
        for name, passed in checks.items()
    )
    engineering = contract.get("claim_profile") == "engineering_progression"
    policy_status = contract.get("engineering_progression_policy", {}).get(
        "status"
    )
    pending_thresholds = contract.get("pending_required_threshold_metrics", [])
    if errors or nonmissing_failure:
        status = "FAIL"
    elif missing_metric_checks or (
        engineering
        and (
            policy_status != "ACTIVE_ENGINEERING_PROGRESSION_POLICY"
            or pending_thresholds
        )
    ):
        status = contract.get(
            "missing_metric_result", "NOT_EVALUATED_DO_NOT_PROGRESS"
        )
    else:
        status = "PASS"
    result = {
        "schema_version": 1,
        "role": "multipole_l3_numerical_qualification_result",
        "status": status,
        "comparison_axis": axis,
        "claim_profile": contract.get("claim_profile"),
        "baseline": {
            key: baseline[key]
            for key in ("run_id", "project", "solver", "scales", "observables")
        },
        "refined_or_peer": {
            key: refined[key]
            for key in ("run_id", "project", "solver", "scales", "observables")
        },
        "identity_errors": errors,
        "differences": differences,
        "acceptance": acceptance,
        "checks": checks,
        "claim_limit": contract["claim_limit"],
    }
    if engineering:
        result["engineering_progression_status"] = status
        result["numerical_convergence_status"] = "DEFERRED_NOT_WAIVED"
        result["missing_required_metrics"] = sorted(missing_metric_checks)
        result["pending_required_threshold_metrics"] = list(pending_thresholds)
    if axis == "mesh_strategy":
        result["functional_status"] = status
        result["continuous_status"] = "INCONCLUSIVE_NO_SOURCED_ERROR_BUDGET"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-manifest", required=True, type=Path)
    parser.add_argument("--refined-manifest", required=True, type=Path)
    parser.add_argument(
        "--axis",
        required=True,
        choices=(
            "spatial",
            "spatial_radial",
            "spatial_axial",
            "spatial_isotropic",
            "temporal",
            "cross_solver",
            "mesh_strategy",
        ),
    )
    parser.add_argument(
        "--contract",
        required=True,
        type=Path,
        help="Preregistered project or explicitly applicable shared acceptance contract.",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate(
        run_data(args.baseline_manifest),
        run_data(args.refined_manifest),
        args.axis,
        load_json(args.contract),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    status_line = (
        f"MULTIPOLE_NUMERICAL_QUALIFICATION={result['status']} "
        f"AXIS={args.axis} OUTPUT={args.output.resolve()}"
    )
    if args.axis == "mesh_strategy":
        status_line += (
            f" FUNCTIONAL={result['functional_status']} "
            f"CONTINUOUS={result['continuous_status']}"
        )
    print(status_line)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
