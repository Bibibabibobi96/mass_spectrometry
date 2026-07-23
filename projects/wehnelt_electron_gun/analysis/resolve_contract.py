"""Resolve and validate the Wehnelt electron-gun machine contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

PROJECT_ID = "wehnelt_electron_gun"
MODEL_ID = "wehnelt.transverse_helical_filament.thermal_transport.v1"


class ContractError(ValueError):
    """Raised when a Wehnelt source contract is ambiguous or invalid."""


def _require_exact_keys(
    value: dict[str, Any], expected: set[str], context: str
) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        raise ContractError(
            f"{context} keys mismatch; missing={missing}, unknown={unknown}"
        )


def _require_dict(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{context} must be an object")
    return value


def _require_bool(value: Any, context: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{context} must be boolean")
    return value


def _require_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{context} must be a non-empty string")
    return value


def _require_number(
    value: Any,
    context: str,
    *,
    minimum: float | None = None,
    strict_minimum: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{context} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ContractError(f"{context} must be finite")
    if minimum is not None:
        if strict_minimum and numeric <= minimum:
            raise ContractError(f"{context} must be > {minimum}")
        if not strict_minimum and numeric < minimum:
            raise ContractError(f"{context} must be >= {minimum}")
    return numeric


def _require_positive_integer(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{context} must be a positive integer")
    return value


def load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object while rejecting non-standard numeric constants."""

    try:
        with path.open("r", encoding="utf-8") as stream:
            value = json.load(
                stream,
                parse_constant=lambda token: (_ for _ in ()).throw(
                    ContractError(f"{path}: non-finite JSON number {token}")
                ),
            )
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
    return _require_dict(value, str(path))


def contract_sha256(value: dict[str, Any]) -> str:
    """Return the SHA-256 of one canonical JSON contract."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def validate_baseline(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate the physical baseline without inserting defaults."""

    _require_exact_keys(
        raw,
        {
            "schema_version",
            "role",
            "project_id",
            "model_id",
            "capability",
            "coordinate_convention",
            "filament",
            "geometry_mm",
            "electrodes_V",
            "collection_metric",
        },
        "baseline",
    )
    if raw["schema_version"] != 1:
        raise ContractError("baseline.schema_version must equal 1")
    if raw["role"] != "wehnelt_electron_gun_physical_baseline":
        raise ContractError("baseline.role identity mismatch")
    if raw["project_id"] != PROJECT_ID or raw["model_id"] != MODEL_ID:
        raise ContractError("baseline project/model identity mismatch")

    capability = _require_dict(raw["capability"], "baseline.capability")
    _require_exact_keys(
        capability,
        {
            "id",
            "imaging_quality_claim_allowed",
            "formal_performance_claim_allowed",
        },
        "baseline.capability",
    )
    if capability["id"] != "wehnelt_thermal_electron_transport":
        raise ContractError("baseline.capability.id identity mismatch")
    if _require_bool(
        capability["imaging_quality_claim_allowed"],
        "baseline.capability.imaging_quality_claim_allowed",
    ):
        raise ContractError("the transverse prototype cannot claim imaging quality")
    if _require_bool(
        capability["formal_performance_claim_allowed"],
        "baseline.capability.formal_performance_claim_allowed",
    ):
        raise ContractError("the current prototype cannot claim formal performance")

    coordinate = _require_dict(
        raw["coordinate_convention"], "baseline.coordinate_convention"
    )
    _require_exact_keys(
        coordinate,
        {
            "frame_id",
            "units",
            "origin",
            "beam_axis",
            "filament_helix_axis",
            "handedness",
        },
        "baseline.coordinate_convention",
    )
    if (
        coordinate["frame_id"] != "wehnelt_electron_gun_component"
        or coordinate["units"] != "mm"
        or coordinate["beam_axis"] != "+z"
        or coordinate["filament_helix_axis"] != "+x"
        or coordinate["handedness"] != "right_handed"
    ):
        raise ContractError("unsupported Wehnelt coordinate convention")
    _require_string(coordinate["origin"], "baseline.coordinate_convention.origin")

    filament = _require_dict(raw["filament"], "baseline.filament")
    _require_exact_keys(
        filament,
        {
            "material",
            "coil_major_radius_mm",
            "wire_radius_mm",
            "turn_count",
            "axial_pitch_mm",
            "axis_center_z_mm",
            "temperature_K",
            "emission_velocity_distribution",
        },
        "baseline.filament",
    )
    if filament["material"] != "tungsten":
        raise ContractError("the current filament material must remain tungsten")
    for key in (
        "coil_major_radius_mm",
        "wire_radius_mm",
        "axial_pitch_mm",
        "temperature_K",
    ):
        _require_number(
            filament[key],
            f"baseline.filament.{key}",
            minimum=0.0,
            strict_minimum=True,
        )
    _require_number(
        filament["axis_center_z_mm"], "baseline.filament.axis_center_z_mm"
    )
    _require_positive_integer(
        filament["turn_count"], "baseline.filament.turn_count"
    )
    if filament["emission_velocity_distribution"] != "Thermal":
        raise ContractError("only the current thermal emission model is supported")

    geometry = _require_dict(raw["geometry_mm"], "baseline.geometry_mm")
    geometry_keys = {
        "wehnelt_skirt_below_reference",
        "wehnelt_cavity_reference_height",
        "wehnelt_cavity_ceiling_gap",
        "wehnelt_front_wall_thickness",
        "wehnelt_cavity_radius",
        "wehnelt_outer_radius",
        "wehnelt_aperture_radius",
        "wehnelt_to_anode_gap",
        "anode_outer_radius",
        "anode_aperture_radius",
        "anode_thickness",
        "post_anode_drift",
        "vacuum_domain_radius",
        "vacuum_margin_below_wehnelt",
        "electrode_chamfer_distance",
        "boolean_tool_overshoot_each_side",
    }
    _require_exact_keys(geometry, geometry_keys, "baseline.geometry_mm")
    for key in geometry_keys:
        _require_number(
            geometry[key],
            f"baseline.geometry_mm.{key}",
            minimum=0.0,
            strict_minimum=True,
        )
    if not (
        geometry["wehnelt_aperture_radius"]
        < geometry["wehnelt_cavity_radius"]
        < geometry["wehnelt_outer_radius"]
        < geometry["vacuum_domain_radius"]
    ):
        raise ContractError("Wehnelt radial geometry is not nested")
    if not (
        geometry["anode_aperture_radius"]
        < geometry["anode_outer_radius"]
        < geometry["vacuum_domain_radius"]
    ):
        raise ContractError("anode radial geometry is not nested")
    if geometry["electrode_chamfer_distance"] >= min(
        geometry["wehnelt_aperture_radius"],
        geometry["anode_aperture_radius"],
    ):
        raise ContractError("chamfer distance must remain below both apertures")

    electrodes = _require_dict(raw["electrodes_V"], "baseline.electrodes_V")
    _require_exact_keys(
        electrodes, {"cathode", "wehnelt", "anode"}, "baseline.electrodes_V"
    )
    cathode = _require_number(
        electrodes["cathode"], "baseline.electrodes_V.cathode"
    )
    wehnelt = _require_number(
        electrodes["wehnelt"], "baseline.electrodes_V.wehnelt"
    )
    anode = _require_number(electrodes["anode"], "baseline.electrodes_V.anode")
    if not wehnelt < cathode < anode:
        raise ContractError("electrode ordering must remain Wehnelt < cathode < anode")

    metric = _require_dict(raw["collection_metric"], "baseline.collection_metric")
    _require_exact_keys(
        metric,
        {
            "valid_state_rule",
            "usable_energy_min_eV",
            "usable_energy_max_eV",
            "historical_value_is_current_evidence",
        },
        "baseline.collection_metric",
    )
    if metric["valid_state_rule"] != "finite_final_particle_position":
        raise ContractError("unsupported collection valid-state rule")
    minimum_energy = _require_number(
        metric["usable_energy_min_eV"],
        "baseline.collection_metric.usable_energy_min_eV",
        minimum=0.0,
    )
    maximum_energy = _require_number(
        metric["usable_energy_max_eV"],
        "baseline.collection_metric.usable_energy_max_eV",
        minimum=0.0,
        strict_minimum=True,
    )
    if minimum_energy >= maximum_energy:
        raise ContractError("usable energy interval must be increasing")
    if _require_bool(
        metric["historical_value_is_current_evidence"],
        "baseline.collection_metric.historical_value_is_current_evidence",
    ):
        raise ContractError("historical collection efficiency is not current evidence")
    return raw


def _validate_mode(mode_id: str, mode: dict[str, Any]) -> None:
    _require_exact_keys(
        mode,
        {
            "execution_mode",
            "evidence_kind",
            "candidate_evidence_allowed",
            "minimum_evidence_particle_count",
            "mesh",
            "particle_time_ns",
            "reporting",
        },
        f"mode.{mode_id}",
    )
    expected_execution = "build_only" if mode_id == "build_only_smoke" else "full"
    if mode["execution_mode"] != expected_execution:
        raise ContractError(f"mode.{mode_id}.execution_mode mismatch")
    allowed = _require_bool(
        mode["candidate_evidence_allowed"],
        f"mode.{mode_id}.candidate_evidence_allowed",
    )
    minimum_count = mode["minimum_evidence_particle_count"]
    if mode_id == "build_only_smoke":
        if allowed or minimum_count is not None:
            raise ContractError("build-only smoke must remain evidence-ineligible")
    elif not allowed or _require_positive_integer(
        minimum_count, f"mode.{mode_id}.minimum_evidence_particle_count"
    ) < 100:
        raise ContractError("functional evidence minimum must be at least N=100")
    _require_string(mode["evidence_kind"], f"mode.{mode_id}.evidence_kind")

    mesh = _require_dict(mode["mesh"], f"mode.{mode_id}.mesh")
    _require_exact_keys(
        mesh,
        {
            "automatic_level",
            "filament_surface_hmax_mm",
            "filament_surface_hmin_mm",
            "maximum_element_growth_rate",
            "element_type",
        },
        f"mode.{mode_id}.mesh",
    )
    level = _require_positive_integer(
        mesh["automatic_level"], f"mode.{mode_id}.mesh.automatic_level"
    )
    if level > 9:
        raise ContractError("mesh automatic level must be in [1, 9]")
    hmax = _require_number(
        mesh["filament_surface_hmax_mm"],
        f"mode.{mode_id}.mesh.filament_surface_hmax_mm",
        minimum=0.0,
        strict_minimum=True,
    )
    hmin = _require_number(
        mesh["filament_surface_hmin_mm"],
        f"mode.{mode_id}.mesh.filament_surface_hmin_mm",
        minimum=0.0,
        strict_minimum=True,
    )
    if hmin > hmax:
        raise ContractError("filament mesh hmin must not exceed hmax")
    _require_number(
        mesh["maximum_element_growth_rate"],
        f"mode.{mode_id}.mesh.maximum_element_growth_rate",
        minimum=1.0,
    )
    if mesh["element_type"] != "FreeTet":
        raise ContractError("the current mesh element type must remain FreeTet")

    time = _require_dict(mode["particle_time_ns"], f"mode.{mode_id}.particle_time_ns")
    _require_exact_keys(
        time, {"start", "step", "end"}, f"mode.{mode_id}.particle_time_ns"
    )
    start = _require_number(time["start"], f"mode.{mode_id}.particle_time_ns.start")
    step = _require_number(
        time["step"],
        f"mode.{mode_id}.particle_time_ns.step",
        minimum=0.0,
        strict_minimum=True,
    )
    end = _require_number(
        time["end"],
        f"mode.{mode_id}.particle_time_ns.end",
        minimum=0.0,
        strict_minimum=True,
    )
    if start != 0.0 or step > end:
        raise ContractError("particle time range must start at zero with step <= end")

    reporting = _require_dict(mode["reporting"], f"mode.{mode_id}.reporting")
    _require_exact_keys(
        reporting,
        {
            "field_image_width_px",
            "field_image_height_px",
            "trajectory_image_width_px",
            "trajectory_image_height_px",
            "electrostatic_axis_samples_z_mm",
        },
        f"mode.{mode_id}.reporting",
    )
    for key in (
        "field_image_width_px",
        "field_image_height_px",
        "trajectory_image_width_px",
        "trajectory_image_height_px",
    ):
        _require_positive_integer(reporting[key], f"mode.{mode_id}.reporting.{key}")
    samples = reporting["electrostatic_axis_samples_z_mm"]
    if not isinstance(samples, list) or not samples:
        raise ContractError("electrostatic axis samples must be a non-empty array")
    parsed = [
        _require_number(value, f"mode.{mode_id}.reporting.axis_sample[{index}]")
        for index, value in enumerate(samples)
    ]
    if parsed != sorted(set(parsed)):
        raise ContractError("electrostatic axis samples must be unique and increasing")


def validate_modes(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate the finite numerical-mode set."""

    _require_exact_keys(
        raw, {"schema_version", "role", "project_id", "modes"}, "numerical modes"
    )
    if raw["schema_version"] != 1:
        raise ContractError("numerical_modes.schema_version must equal 1")
    if raw["role"] != "wehnelt_electron_gun_numerical_modes":
        raise ContractError("numerical_modes.role identity mismatch")
    if raw["project_id"] != PROJECT_ID:
        raise ContractError("numerical_modes.project_id identity mismatch")
    modes = _require_dict(raw["modes"], "numerical_modes.modes")
    if set(modes) != {"build_only_smoke", "functional_reference"}:
        raise ContractError("numerical mode identities are fixed and exhaustive")
    for mode_id, mode in modes.items():
        _validate_mode(mode_id, _require_dict(mode, f"mode.{mode_id}"))
    return raw


def derive_geometry(baseline: dict[str, Any]) -> dict[str, float]:
    """Derive all shared axial coordinates once from the physical baseline."""

    filament = baseline["filament"]
    geometry = baseline["geometry_mm"]
    coil_length = float(filament["turn_count"]) * float(
        filament["axial_pitch_mm"]
    )
    wehnelt_bottom = -float(geometry["wehnelt_skirt_below_reference"])
    wehnelt_ceiling = float(geometry["wehnelt_cavity_reference_height"]) + float(
        geometry["wehnelt_cavity_ceiling_gap"]
    )
    wehnelt_top = wehnelt_ceiling + float(
        geometry["wehnelt_front_wall_thickness"]
    )
    anode_bottom = wehnelt_top + float(geometry["wehnelt_to_anode_gap"])
    anode_top = anode_bottom + float(geometry["anode_thickness"])
    domain_bottom = wehnelt_bottom - float(
        geometry["vacuum_margin_below_wehnelt"]
    )
    domain_top = anode_top + float(geometry["post_anode_drift"])
    radial_extent = float(filament["coil_major_radius_mm"]) + float(
        filament["wire_radius_mm"]
    )
    if (
        float(filament["axis_center_z_mm"]) - radial_extent <= wehnelt_bottom
        or float(filament["axis_center_z_mm"]) + radial_extent >= wehnelt_ceiling
    ):
        raise ContractError("filament does not fit inside the Wehnelt cavity")
    return {
        "coil_length_mm": coil_length,
        "coil_x_min_mm": -coil_length / 2.0,
        "coil_x_max_mm": coil_length / 2.0,
        "wehnelt_bottom_z_mm": wehnelt_bottom,
        "wehnelt_cavity_ceiling_z_mm": wehnelt_ceiling,
        "wehnelt_top_z_mm": wehnelt_top,
        "anode_bottom_z_mm": anode_bottom,
        "anode_top_z_mm": anode_top,
        "vacuum_domain_bottom_z_mm": domain_bottom,
        "vacuum_domain_top_z_mm": domain_top,
    }


def resolve_contract(
    baseline: dict[str, Any],
    modes: dict[str, Any],
    mode_id: str,
    evidence_particle_count: int | None,
) -> dict[str, Any]:
    """Combine physical input and one named numerical mode."""

    validate_baseline(baseline)
    validate_modes(modes)
    if mode_id not in modes["modes"]:
        raise ContractError(f"unknown numerical mode: {mode_id}")
    selected = modes["modes"][mode_id]
    if evidence_particle_count is not None:
        evidence_particle_count = _require_positive_integer(
            evidence_particle_count, "evidence_particle_count"
        )
    minimum_count = selected["minimum_evidence_particle_count"]
    if selected["candidate_evidence_allowed"]:
        if evidence_particle_count is None:
            raise ContractError("functional mode requires an evidence particle count")
        if evidence_particle_count < minimum_count:
            raise ContractError(
                f"N={evidence_particle_count} is below the functional minimum "
                f"N={minimum_count}"
            )
    elif evidence_particle_count is None:
        raise ContractError("build-only mode requires an explicit fixture particle count")

    return {
        "schema_version": 1,
        "role": "wehnelt_electron_gun_resolved_contract",
        "project_id": PROJECT_ID,
        "model_id": MODEL_ID,
        "selected_mode_id": mode_id,
        "source_identity": {
            "hash_algorithm": "SHA-256",
            "serialization": "canonical_json_sorted_keys_compact_utf8",
            "baseline_path": "config/baseline.json",
            "baseline_sha256": contract_sha256(baseline),
            "numerical_modes_path": "config/numerical_modes.json",
            "numerical_modes_sha256": contract_sha256(modes),
        },
        "physical": baseline,
        "derived_geometry_mm": derive_geometry(baseline),
        "numerical": selected,
        "evidence": {
            "requested_particle_count": evidence_particle_count,
            "candidate_evidence_allowed": selected["candidate_evidence_allowed"],
            "minimum_particle_count": minimum_count,
            "scope": selected["evidence_kind"],
        },
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    """Write deterministic UTF-8 JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the resolver command-line interface."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--modes", type=Path, required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--evidence-particle-count", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--check",
        type=Path,
        help="Require an existing resolved file to match canonical resolution.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Resolve, write, or freshness-check the contract."""

    args = build_parser().parse_args(argv)
    try:
        resolved = resolve_contract(
            load_json(args.baseline),
            load_json(args.modes),
            args.mode,
            args.evidence_particle_count,
        )
        if args.check is not None and load_json(args.check) != resolved:
            raise ContractError(f"stale resolved contract: {args.check}")
        if args.output is not None:
            write_json(args.output, resolved)
        if args.check is None and args.output is None:
            print(json.dumps(resolved, indent=2, ensure_ascii=False))
    except ContractError as exc:
        print(f"ERROR: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
