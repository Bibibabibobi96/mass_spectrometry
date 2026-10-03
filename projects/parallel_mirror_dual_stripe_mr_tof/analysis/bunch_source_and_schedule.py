"""Deterministic MR-TOF bunch states and detector-blind accelerator timing.

This module contains no solver calls and chooses no physical widths.  Callers
must supply the complete source envelope and the trajectory step used by the
pilot flight.  The generated particle order is prefix-stable, so the standard
N=100 cohort is the exact leading prefix of the N=1000 mother cohort.
"""
from __future__ import annotations

import argparse
import hashlib
import csv
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from common.contracts.file_identity import file_sha256
from common.contracts.particle_count_policy import validate_standard_particle_count
from common.ion_release.cylinder import (
    apply_controlled_position_pair,
    apply_controlled_slow_energy_pair,
    generate_center_axis_pair_halton_cylinder_phase_space,
    generate_halton_cylinder_phase_space,
)
from common.simion.particle_source import render_standard_beams
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    derive_two_zone_placement,
    load_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import (
    parse_events,
)


_CLOCK_BASIS = "ion_time_of_flight_us_from_common_tob_zero_release"
_SAMPLING_METHOD = "center_z_pair_then_halton_position_energy_angle_v1"
_SLOW_ENERGY_SAMPLING_METHOD = "center_slow_energy_pair_then_halton_position_energy_angle_v1"
_ABERRATION_SENTINEL_SAMPLING_METHOD = (
    "center_z_slow_energy_x_pairs_then_halton_position_energy_angle_v1"
)
_EXTENDED_ABERRATION_SENTINEL_SAMPLING_METHOD = (
    "center_local_and_envelope_position_slow_energy_pairs_then_halton_v1"
)
_LEGACY_SAMPLING_METHOD = "center_first_halton_position_energy_angle_v1"
_FORMAL_VOLUME_SAMPLING_METHOD = "halton_volume_position_energy_angle_v1"
_GAUSSIAN_VOLUME_SAMPLING_METHOD = "halton_volume_position_gaussian_release_ey_v1"
_CONTROLLED_DIAGNOSTIC_COHORT_ROLE = "controlled_diagnostic"
_FORMAL_VOLUME_COHORT_ROLE = "formal_volume"
_SOURCE_DEFINITION_ROLE = "mrtof_ideal_bunch_source_definition"
_CURRENT_SOURCE_DEFINITION_SCHEMA = 4
_COORDINATE_SEMANTICS = {
    "x": "transverse_mirror_focusing",
    "y": "slow_drift_positive_stripe_function_argument",
    "z": "fast_reflection_and_acceleration_axis",
    "workbench_from_project": "identity",
}


def _finite(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise CandidateContractError(f"{label} must be finite")
    return float(value)


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateContractError(f"{label} is unreadable") from error
    if not isinstance(value, dict):
        raise CandidateContractError(f"{label} must be an object")
    return value


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    payload = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _vector3(values: Sequence[float], label: str) -> tuple[float, float, float]:
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        raise CandidateContractError(f"{label} must contain three values")
    return tuple(_finite(value, label) for value in values)  # type: ignore[return-value]




def _normalize(values: Sequence[float]) -> tuple[float, float, float]:
    """Normalize one MR adapter direction before FLY2 serialization."""
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(norm) or norm <= 0.0:
        raise CandidateContractError("source direction must be nonzero")
    return tuple(value / norm for value in values)  # type: ignore[return-value]

def deterministic_ideal_bunch_states(
    *,
    particle_count: int,
    mother_particle_count: int,
    center_workbench_mm: Sequence[float],
    aperture_plane_axes: tuple[int, int],
    acceleration_axis: int,
    position_radius_mm: float,
    acceleration_axis_full_width_mm: float,
    controlled_focus_half_span_mm: float | None = None,
    controlled_slow_energy_half_span_ev_per_charge: float | None = None,
    controlled_envelope_half_span_fraction: float | None = None,
    kinetic_energy_center_ev: float,
    kinetic_energy_full_width_ev: float,
    nominal_direction_workbench: Sequence[float],
    angular_full_width_deg: float,
    mass_th: float,
    charge_e: int,
    common_time_of_birth_us: float = 0.0,
    cohort_role: str = _CONTROLLED_DIAGNOSTIC_COHORT_ROLE,
    kinetic_energy_distribution: str = "uniform",
    kinetic_energy_sigma_ev: float | None = None,
) -> list[dict[str, Any]]:
    """Return an explicit, byte-stable ideal cohort with a centre-first prefix.

    Widths are full widths except an explicit Gaussian energy sigma in eV.
    Formal volume samples have no forced centre. Diagnostic cohorts retain
    their centre and controlled pairs; no solver RNG participates.
    """
    try:
        validate_standard_particle_count(particle_count)
        validate_standard_particle_count(mother_particle_count)
    except ValueError as error:
        raise CandidateContractError(str(error)) from error
    if mother_particle_count < particle_count:
        raise CandidateContractError("particle count must be a mother-cohort prefix")
    if any(axis not in (0, 1, 2) for axis in aperture_plane_axes) or len(set(aperture_plane_axes)) != 2:
        raise CandidateContractError("aperture plane axes must be two unique axes")
    if acceleration_axis not in (0, 1, 2) or acceleration_axis in aperture_plane_axes:
        raise CandidateContractError("acceleration axis must complement the aperture plane")
    if cohort_role not in {_CONTROLLED_DIAGNOSTIC_COHORT_ROLE, _FORMAL_VOLUME_COHORT_ROLE}:
        raise CandidateContractError("source cohort role is invalid")
    if kinetic_energy_distribution not in {"uniform", "gaussian"}:
        raise CandidateContractError("unsupported kinetic-energy distribution")
    if kinetic_energy_distribution == "gaussian" and (
        cohort_role != _FORMAL_VOLUME_COHORT_ROLE
        or list(nominal_direction_workbench) != [0.0, 1.0, 0.0]
        or angular_full_width_deg != 0.0
    ):
        raise CandidateContractError("Gaussian release Ey requires formal volume and zero-angle +y direction")
    if kinetic_energy_distribution == "uniform" and kinetic_energy_sigma_ev is not None:
        raise CandidateContractError("uniform energy does not accept sigma")
    if cohort_role == _FORMAL_VOLUME_COHORT_ROLE and any(value is not None for value in (
        controlled_focus_half_span_mm,
        controlled_slow_energy_half_span_ev_per_charge,
        controlled_envelope_half_span_fraction,
    )):
        raise CandidateContractError("formal volume cohort cannot contain controlled sentinels")
    sampler = (
        generate_halton_cylinder_phase_space
        if cohort_role == _FORMAL_VOLUME_COHORT_ROLE
        else generate_center_axis_pair_halton_cylinder_phase_space
    )
    sampler_arguments = {
        "particle_count": particle_count,
        "center_mm": _vector3(center_workbench_mm, "source centre"),
        "transverse_axes": aperture_plane_axes,
        "axis": acceleration_axis,
        "radius_mm": _finite(position_radius_mm, "position radius"),
        "height_mm": _finite(acceleration_axis_full_width_mm, "axial full width"),
        "kinetic_energy_center_ev": _finite(kinetic_energy_center_ev, "kinetic-energy centre"),
        "kinetic_energy_full_width_ev": _finite(kinetic_energy_full_width_ev, "kinetic-energy full width"),
        "nominal_direction": _vector3(nominal_direction_workbench, "nominal direction"),
        "angular_full_width_deg": _finite(angular_full_width_deg, "angular full width"),
    }
    if cohort_role == _CONTROLLED_DIAGNOSTIC_COHORT_ROLE:
        sampler_arguments.update({
            "controlled_axis": 2,
            "controlled_axis_half_span_mm": controlled_focus_half_span_mm,
        })
    else:
        sampler_arguments.update({
            "kinetic_energy_distribution": kinetic_energy_distribution,
            "kinetic_energy_sigma_ev": kinetic_energy_sigma_ev,
        })
    try:
        samples = sampler(**sampler_arguments)
    except ValueError as error:
        raise CandidateContractError(str(error)) from error
    mass = _finite(mass_th, "particle mass")
    tob = _finite(common_time_of_birth_us, "common time of birth")
    if mass <= 0 or type(charge_e) is not int or charge_e == 0:
        raise CandidateContractError("source species and energy envelope must be physical")
    states = [{
        "particle_id": sample["particle_id"],
        "tob_us": tob,
        "mass_th": mass,
        "charge_e": charge_e,
        "kinetic_energy_ev": sample["kinetic_energy_ev"],
        "position_workbench_mm": sample["position_mm"],
        "direction_workbench": sample["direction"],
    } for sample in samples]
    if controlled_slow_energy_half_span_ev_per_charge is not None:
        try:
            combined = controlled_focus_half_span_mm is not None
            states = apply_controlled_slow_energy_pair(
                states,
                charge_state=charge_e,
                half_span_ev_per_charge=controlled_slow_energy_half_span_ev_per_charge,
                negative_particle_id=4 if combined else 2,
                positive_particle_id=5 if combined else 3,
            )
            if combined:
                states = apply_controlled_position_pair(
                    states,
                    controlled_axis=0,
                    half_span_mm=controlled_focus_half_span_mm,
                    negative_particle_id=6,
                    positive_particle_id=7,
                    position_key="position_workbench_mm",
                )
                if controlled_envelope_half_span_fraction is not None:
                    fraction = _finite(
                        controlled_envelope_half_span_fraction,
                        "controlled envelope half-span fraction",
                    )
                    if not 0.0 < fraction <= 1.0:
                        raise CandidateContractError(
                            "controlled envelope half-span fraction must be in (0, 1]"
                        )
                    if len(states) < 13:
                        raise CandidateContractError(
                            "extended aberration sentinels require at least thirteen particles"
                        )
                    envelope_pairs = (
                        (acceleration_axis, acceleration_axis_full_width_mm / 2.0, 8, 9),
                        (aperture_plane_axes[0], position_radius_mm, 10, 11),
                        (aperture_plane_axes[1], position_radius_mm, 12, 13),
                    )
                    for axis, half_span, negative_id, positive_id in envelope_pairs:
                        states = apply_controlled_position_pair(
                            states,
                            controlled_axis=axis,
                            half_span_mm=half_span * fraction,
                            negative_particle_id=negative_id,
                            positive_particle_id=positive_id,
                            position_key="position_workbench_mm",
                        )
        except ValueError as error:
            raise CandidateContractError(str(error)) from error
    return states


def materialize_bunch_source_from_definition(
    *,
    definition_path: Path,
    state_table_path: Path,
    fly2_path: Path,
    receipt_path: Path,
    geometry_contract_path: Path | None = None,
    accelerator_provider_receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Materialize a cohort only from one complete frozen source definition."""
    definition = _load_object(definition_path, "bunch source definition")
    schema_version = definition.get("schema_version")
    if (
        schema_version not in (1, 2, 3, _CURRENT_SOURCE_DEFINITION_SCHEMA)
        or definition.get("role") != _SOURCE_DEFINITION_ROLE
        or definition.get("status") != "frozen"
    ):
        raise CandidateContractError("bunch source definition identity is invalid")
    required = (
        "source_profile_id", "frame_id", "particle_count", "mother_particle_count",
        "aperture_plane_axes", "acceleration_axis",
        "position_radius_mm", "acceleration_axis_full_width_mm",
        "kinetic_energy_center_ev", "kinetic_energy_full_width_ev",
        "nominal_direction_workbench", "angular_full_width_deg",
        "mass_th", "charge_e", "common_time_of_birth_us",
    )
    if schema_version in (1, 2):
        required = (*required, "center_workbench_mm")
    elif schema_version == 3:
        required = (
            *required,
            "center_rule",
            "center_offset_workbench_mm",
            "field_cache_dependency",
        )
    else:
        required = (
            *required,
            "center_rule",
            "source_y_offset_mm",
            "field_cache_dependency",
            "cohort_role",
        )
    missing = [name for name in required if name not in definition]
    if missing:
        raise CandidateContractError(
            "bunch source definition is incomplete: " + ", ".join(missing)
        )
    geometry_binding: dict[str, Any] | None = None
    resolved_center = _vector3(
        definition["center_workbench_mm"], "source centre"
    ) if schema_version in (1, 2) else None
    if schema_version in (2, 3, _CURRENT_SOURCE_DEFINITION_SCHEMA):
        if geometry_contract_path is None:
            raise CandidateContractError(
                "schema-2 bunch source definition requires its geometry contract"
            )
        geometry_contract = load_contract(geometry_contract_path)
        frame = geometry_contract["coordinate_system"]
        transform = frame.get("simion_workbench_from_project")
        if (
            definition.get("frame_id") != frame.get("frame_id")
            or definition.get("coordinate_semantics") != _COORDINATE_SEMANTICS
            or not isinstance(transform, dict)
            or transform.get("rotation") != [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
            or transform.get("translation_mm") != [0, 0, 0]
        ):
            raise CandidateContractError(
                "bunch source coordinates must use the identity project/workbench x-y-z frame"
            )
        placement = derive_two_zone_placement(geometry_contract)
        release = _finite(
            geometry_contract["accelerator"].get("release_position_in_gap_1_mm"),
            "accelerator release position",
        )
        expected_center = (
            0.0,
            placement.focus_y_mm,
            placement.repeller_z_mm - release,
        )
        geometry_sha = file_sha256(geometry_contract_path).lower()
        if schema_version == 2:
            actual_center = resolved_center
            if any(
                not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12)
                for actual, expected in zip(actual_center, expected_center, strict=True)
            ):
                raise CandidateContractError(
                    "bunch source centre differs from the resolved accelerator release position"
                )
            authority = definition.get("center_authority")
            if (
                not isinstance(authority, dict)
                or authority.get("method")
                != "derived_two_zone_placement_repeller_minus_gap1_release"
                or str(authority.get("geometry_contract_sha256", "")).lower() != geometry_sha
            ):
                raise CandidateContractError("bunch source centre authority is invalid")
        elif schema_version == 3:
            if (
                definition.get("center_rule")
                != "resolved_accelerator_release_position"
                or definition.get("field_cache_dependency") != "none"
            ):
                raise CandidateContractError(
                    "schema-3 source placement must be resolved at run time and field-cache independent"
                )
            offset = _vector3(
                definition["center_offset_workbench_mm"], "source centre offset"
            )
            resolved_center = tuple(
                expected + delta
                for expected, delta in zip(expected_center, offset, strict=True)
            )
        else:
            if (
                definition.get("center_rule")
                != "resolved_provider_accelerator_release_position"
                or definition.get("field_cache_dependency") != "none"
            ):
                raise CandidateContractError(
                    "schema-4 source placement must use the provider release position and remain field-cache independent"
                )
            if accelerator_provider_receipt_path is None:
                raise CandidateContractError(
                    "schema-4 bunch source definition requires its accelerator provider receipt"
                )
            provider = _load_object(
                accelerator_provider_receipt_path, "accelerator provider receipt"
            )
            projection = provider.get("mrtof_projection")
            provider_geometry = (
                projection.get("geometry") if isinstance(projection, dict) else None
            )
            if (
                provider.get("role") != "orthogonal_accelerator_mrtof_runtime_receipt"
                or provider.get("status") != "published_standalone_response_bank"
                or not isinstance(provider_geometry, dict)
                or provider_geometry.get("acceleration_direction") != "-z"
            ):
                raise CandidateContractError(
                    "accelerator provider receipt lacks a published MR geometry projection"
                )
            source_y_offset = _finite(
                definition["source_y_offset_mm"], "source y offset"
            )
            release = _finite(
                provider_geometry.get("release_position_in_gap_1_mm"),
                "provider accelerator release position",
            )
            repeller_to_exit = _finite(
                provider_geometry.get("repeller_to_exit_mm"),
                "provider accelerator repeller-to-exit distance",
            )
            resolved_center = (
                0.0,
                placement.focus_y_mm + source_y_offset,
                repeller_to_exit - release,
            )
            provider_binding = {
                "path": str(accelerator_provider_receipt_path.resolve()),
                "bytes": accelerator_provider_receipt_path.stat().st_size,
                "sha256": file_sha256(accelerator_provider_receipt_path).lower(),
                "derived_release_z_mm": resolved_center[2],
            }
        geometry_binding = {
            "path": str(geometry_contract_path.resolve()),
            "bytes": geometry_contract_path.stat().st_size,
            "sha256": geometry_sha,
            "derived_center_workbench_mm": list(resolved_center),
        }
    assert resolved_center is not None
    cohort_role = (
        definition["cohort_role"]
        if schema_version == _CURRENT_SOURCE_DEFINITION_SCHEMA
        else _CONTROLLED_DIAGNOSTIC_COHORT_ROLE
    )
    if cohort_role not in {_CONTROLLED_DIAGNOSTIC_COHORT_ROLE, _FORMAL_VOLUME_COHORT_ROLE}:
        raise CandidateContractError("source cohort role is invalid")
    controlled_focus_half_span_mm = definition.get("controlled_focus_half_span_mm")
    controlled_focus_fraction = definition.get(
        "controlled_focus_half_span_fraction_of_radius"
    )
    if controlled_focus_fraction is not None:
        if controlled_focus_half_span_mm is not None:
            raise CandidateContractError(
                "controlled focus span must use one absolute or relative definition"
            )
        controlled_focus_fraction = _finite(
            controlled_focus_fraction, "controlled focus half-span fraction"
        )
        if not 0.0 < controlled_focus_fraction <= 1.0:
            raise CandidateContractError(
                "controlled focus half-span fraction must be in (0, 1]"
            )
        controlled_focus_half_span_mm = (
            _finite(definition["position_radius_mm"], "position radius")
            * controlled_focus_fraction
        )
    controlled_slow_energy_half_span = definition.get(
        "controlled_slow_energy_half_span_ev_per_charge"
    )
    if controlled_slow_energy_half_span is not None:
        controlled_slow_energy_half_span = _finite(
            controlled_slow_energy_half_span,
            "controlled slow-energy half span per charge",
        )
        if controlled_slow_energy_half_span <= 0.0:
            raise CandidateContractError(
                "controlled slow-energy half span per charge must be positive"
            )
        if controlled_focus_half_span_mm is not None and definition["particle_count"] < 7:
            raise CandidateContractError("combined aberration sentinels require at least seven particles")
    combined_sentinels = (
        controlled_focus_half_span_mm is not None
        and controlled_slow_energy_half_span is not None
    )
    controlled_envelope_fraction = None
    if combined_sentinels:
        controlled_envelope_fraction = _finite(
            definition.get("controlled_envelope_half_span_fraction", 1.0),
            "controlled envelope half-span fraction",
        )
        if not 0.0 < controlled_envelope_fraction <= 1.0:
            raise CandidateContractError(
                "controlled envelope half-span fraction must be in (0, 1]"
            )
        if definition["particle_count"] < 13:
            raise CandidateContractError(
                "extended aberration sentinels require at least thirteen particles"
            )
    states = deterministic_ideal_bunch_states(
        particle_count=definition["particle_count"],
        mother_particle_count=definition["mother_particle_count"],
        center_workbench_mm=resolved_center,
        aperture_plane_axes=tuple(definition["aperture_plane_axes"]),
        acceleration_axis=definition["acceleration_axis"],
        position_radius_mm=definition["position_radius_mm"],
        acceleration_axis_full_width_mm=definition["acceleration_axis_full_width_mm"],
        controlled_focus_half_span_mm=controlled_focus_half_span_mm,
        controlled_slow_energy_half_span_ev_per_charge=controlled_slow_energy_half_span,
        controlled_envelope_half_span_fraction=controlled_envelope_fraction,
        kinetic_energy_center_ev=definition["kinetic_energy_center_ev"],
        kinetic_energy_full_width_ev=definition["kinetic_energy_full_width_ev"],
        nominal_direction_workbench=definition["nominal_direction_workbench"],
        angular_full_width_deg=definition["angular_full_width_deg"],
        mass_th=definition["mass_th"],
        charge_e=definition["charge_e"],
        common_time_of_birth_us=definition["common_time_of_birth_us"],
        cohort_role=cohort_role,
        kinetic_energy_distribution=definition.get("kinetic_energy_distribution", "uniform"),
        kinetic_energy_sigma_ev=definition.get("kinetic_energy_sigma_ev"),
    )
    nominal_center_state = {
        "tob_us": _finite(definition["common_time_of_birth_us"], "common time of birth"),
        "mass_th": _finite(definition["mass_th"], "particle mass"),
        "charge_e": definition["charge_e"],
        "kinetic_energy_ev": _finite(definition["kinetic_energy_center_ev"], "kinetic-energy centre"),
        "position_workbench_mm": list(resolved_center),
        "direction_workbench": list(_normalize(_vector3(
            definition["nominal_direction_workbench"], "nominal direction",
        ))),
    }
    receipt = materialize_bunch_source(
        states=states,
        mother_particle_count=definition["mother_particle_count"],
        source_profile_id=definition["source_profile_id"],
        frame_id=definition["frame_id"],
        state_table_path=state_table_path,
        fly2_path=fly2_path,
        receipt_path=receipt_path,
        controlled_focus_pair=(
            None
            if cohort_role == _FORMAL_VOLUME_COHORT_ROLE
            or (controlled_slow_energy_half_span is not None
            and controlled_focus_half_span_mm is None)
            else {
            "coordinate": "z_mm",
            "negative_particle_id": 2,
            "positive_particle_id": 3,
            "coordinate_span_mm": 2.0 * (
                _finite(controlled_focus_half_span_mm, "controlled focus half span")
                if controlled_focus_half_span_mm is not None
                else (
                    _finite(definition["acceleration_axis_full_width_mm"], "axial full width") / 2.0
                    if int(definition["acceleration_axis"]) == 2
                    else _finite(definition["position_radius_mm"], "position radius")
                )
            ),
            "fixed_variables": "position_x_y__kinetic_energy__direction__mass__charge__birth_time",
            }
        ),
        controlled_slow_energy_pair=(
            {
                "coordinate": "release_slow_y_kinetic_energy_ev",
                "negative_particle_id": 4 if combined_sentinels else 2,
                "positive_particle_id": 5 if combined_sentinels else 3,
                "half_span_ev_per_charge": controlled_slow_energy_half_span,
                "coordinate_span_ev": (
                    2.0 * controlled_slow_energy_half_span * abs(int(definition["charge_e"]))
                ),
                "fixed_variables": "position__direction__mass__charge__birth_time",
            }
            if controlled_slow_energy_half_span is not None else None
        ),
        controlled_transverse_x_pair=(
            {
                "coordinate": "x_mm",
                "negative_particle_id": 6,
                "positive_particle_id": 7,
                "coordinate_span_mm": 2.0 * controlled_focus_half_span_mm,
                "fixed_variables": "position_y_z__kinetic_energy__direction__mass__charge__birth_time",
            }
            if combined_sentinels else None
        ),
        controlled_position_pairs=(
            [
                {
                    "name": "local_z",
                    "coordinate": "z_mm",
                    "negative_particle_id": 2,
                    "positive_particle_id": 3,
                    "coordinate_span_mm": 2.0 * controlled_focus_half_span_mm,
                    "fixed_variables": "all_except_z_mm",
                    "scope": "local",
                },
                {
                    "name": "local_x",
                    "coordinate": "x_mm",
                    "negative_particle_id": 6,
                    "positive_particle_id": 7,
                    "coordinate_span_mm": 2.0 * controlled_focus_half_span_mm,
                    "fixed_variables": "all_except_x_mm",
                    "scope": "local",
                },
                {
                    "name": "envelope_y",
                    "coordinate": "y_mm",
                    "negative_particle_id": 8,
                    "positive_particle_id": 9,
                    "coordinate_span_mm": (
                        _finite(definition["acceleration_axis_full_width_mm"], "axial full width")
                        * controlled_envelope_fraction
                    ),
                    "fixed_variables": "all_except_y_mm",
                    "scope": "envelope",
                },
                {
                    "name": "envelope_x",
                    "coordinate": "x_mm",
                    "negative_particle_id": 10,
                    "positive_particle_id": 11,
                    "coordinate_span_mm": (
                        2.0 * _finite(definition["position_radius_mm"], "position radius")
                        * controlled_envelope_fraction
                    ),
                    "fixed_variables": "all_except_x_mm",
                    "scope": "envelope",
                },
                {
                    "name": "envelope_z",
                    "coordinate": "z_mm",
                    "negative_particle_id": 12,
                    "positive_particle_id": 13,
                    "coordinate_span_mm": (
                        2.0 * _finite(definition["position_radius_mm"], "position radius")
                        * controlled_envelope_fraction
                    ),
                    "fixed_variables": "all_except_z_mm",
                    "scope": "envelope",
                },
            ]
            if combined_sentinels else None
        ),
        controlled_head_particle_count=13 if combined_sentinels else None,
        cohort_role=cohort_role,
        nominal_center_state=nominal_center_state,
    )
    receipt["definition"] = {
        "path": str(definition_path.resolve()),
        "bytes": definition_path.stat().st_size,
        "sha256": file_sha256(definition_path).lower(),
    }
    if definition.get("kinetic_energy_distribution") == "gaussian":
        receipt["sampling_method"] = _GAUSSIAN_VOLUME_SAMPLING_METHOD
        receipt["release_energy_distribution"] = {
            "kind": "gaussian", "component": "Ey", "unit": "eV",
            "center_ev": nominal_center_state["kinetic_energy_ev"],
            "sigma_ev": definition["kinetic_energy_sigma_ev"],
            "nonpositive_policy": "fail_without_clipping_or_resampling",
            "latent_sequence": "halton_base7_inverse_standard_normal_v1",
            "latent_index_start": 1,
            "mother_particle_count": definition["mother_particle_count"],
        }
        receipt["latent_mother_sequence"] = {
            "method": "halton_position_base2_3_5_energy_base7_v1",
            "index_start": 1, "mother_particle_count": definition["mother_particle_count"],
            "position_energy_correlation": "no_intentional_correlation__distinct_halton_dimensions",
            "nominal_center_state": nominal_center_state,
            "aperture_plane_axes": definition["aperture_plane_axes"],
            "cylinder_axis": definition["acceleration_axis"],
            "radius_mm": definition["position_radius_mm"],
            "height_mm": definition["acceleration_axis_full_width_mm"],
        }
    if geometry_binding is not None:
        receipt["geometry_contract"] = geometry_binding
        if schema_version == 2:
            receipt["center_authority"] = dict(definition["center_authority"])
        elif schema_version == 3:
            receipt["center_rule"] = definition["center_rule"]
            receipt["center_offset_workbench_mm"] = list(
                _vector3(definition["center_offset_workbench_mm"], "source centre offset")
            )
            receipt["field_cache_dependency"] = "none"
        else:
            receipt["center_rule"] = definition["center_rule"]
            receipt["source_y_offset_mm"] = _finite(
                definition["source_y_offset_mm"], "source y offset"
            )
            receipt["field_cache_dependency"] = "none"
            receipt["accelerator_provider_receipt"] = provider_binding
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    return receipt


def bunch_identity(states: Sequence[Mapping[str, Any]], mother_particle_count: int) -> dict[str, Any]:
    """Return the exact ordered state and particle-ID identities."""
    try:
        validate_standard_particle_count(mother_particle_count)
    except ValueError as error:
        raise CandidateContractError(str(error)) from error
    if mother_particle_count < len(states):
        raise CandidateContractError("mother cohort cannot be smaller than its materialized prefix")
    particle_ids = [int(state["particle_id"]) for state in states]
    if particle_ids != list(range(1, len(states) + 1)):
        raise CandidateContractError("bunch particle IDs must be contiguous and one-based")
    canonical = json.dumps(list(states), sort_keys=True, separators=(",", ":"), allow_nan=False)
    ids = json.dumps(particle_ids, separators=(",", ":"))
    return {
        "sampling_method": _SAMPLING_METHOD,
        "particle_count": len(states),
        "mother_particle_count": mother_particle_count,
        "prefix_rule": "ordered_first_n_states_of_one_mother_cohort",
        "clock_basis": _CLOCK_BASIS,
        "expected_particle_ids": particle_ids,
        "expected_particle_ids_sha256": hashlib.sha256(ids.encode("utf-8")).hexdigest(),
        "particle_states_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def render_bunch_fly2(states: Sequence[Mapping[str, Any]]) -> str:
    """Serialize every frozen state as its own SIMION ``n=1`` beam."""
    beams = []
    for state in states:
        position = _vector3(state["position_workbench_mm"], "state position")
        direction = _normalize(_vector3(state["direction_workbench"], "state direction"))
        charge = state.get("charge_e")
        if type(charge) is not int or charge == 0:
            raise CandidateContractError("state charge must be a nonzero integer")
        beams.append({
            "tob": f"{_finite(state['tob_us'], 'state tob'):.17g}",
            "mass": f"{_finite(state['mass_th'], 'state mass'):.17g}",
            "charge": str(charge),
            "x": f"{position[0]:.17g}", "y": f"{position[1]:.17g}", "z": f"{position[2]:.17g}",
            "direction": [f"{value:.17g}" for value in direction],
            "ke": f"{_finite(state['kinetic_energy_ev'], 'state energy'):.17g}",
            "cwf": "1", "color": "0",
        })
    return render_standard_beams(beams)


def materialize_bunch_source(
    *,
    states: Sequence[Mapping[str, Any]],
    mother_particle_count: int,
    source_profile_id: str,
    frame_id: str,
    state_table_path: Path,
    fly2_path: Path,
    receipt_path: Path,
    controlled_focus_pair: Mapping[str, Any] | None = None,
    controlled_slow_energy_pair: Mapping[str, Any] | None = None,
    controlled_transverse_x_pair: Mapping[str, Any] | None = None,
    controlled_position_pairs: Sequence[Mapping[str, Any]] | None = None,
    controlled_head_particle_count: int | None = None,
    cohort_role: str = _CONTROLLED_DIAGNOSTIC_COHORT_ROLE,
    nominal_center_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write one explicit cohort as a prefix-comparable CSV and Fly2 pair."""
    if not source_profile_id or not frame_id:
        raise CandidateContractError("source profile and frame identities are required")
    if not states:
        raise CandidateContractError("bunch source must contain at least one state")
    masses = {_finite(state["mass_th"], "state mass") for state in states}
    charges = {state.get("charge_e") for state in states}
    birth_times = {_finite(state["tob_us"], "state tob") for state in states}
    if len(masses) != 1 or len(charges) != 1 or len(birth_times) != 1:
        raise CandidateContractError("bunch source must use one species and one common birth time")
    charge = next(iter(charges))
    if type(charge) is not int or charge == 0:
        raise CandidateContractError("bunch source charge must be a nonzero integer")
    identity = bunch_identity(states, mother_particle_count)
    if cohort_role not in {_CONTROLLED_DIAGNOSTIC_COHORT_ROLE, _FORMAL_VOLUME_COHORT_ROLE}:
        raise CandidateContractError("source cohort role is invalid")
    if cohort_role == _FORMAL_VOLUME_COHORT_ROLE:
        if any(value is not None for value in (
            controlled_focus_pair, controlled_slow_energy_pair,
            controlled_transverse_x_pair, controlled_position_pairs,
        )):
            raise CandidateContractError("formal volume cohort cannot contain controlled sentinels")
        identity["sampling_method"] = _FORMAL_VOLUME_SAMPLING_METHOD
    elif controlled_position_pairs is not None:
        if controlled_transverse_x_pair is None:
            raise CandidateContractError("extended sentinels require the local x sentinel")
        identity["sampling_method"] = _EXTENDED_ABERRATION_SENTINEL_SAMPLING_METHOD
    elif controlled_transverse_x_pair is not None:
        if controlled_focus_pair is None or controlled_slow_energy_pair is None:
            raise CandidateContractError("transverse sentinel requires the z and slow-energy sentinels")
        identity["sampling_method"] = _ABERRATION_SENTINEL_SAMPLING_METHOD
    elif controlled_slow_energy_pair is not None:
        identity["sampling_method"] = _SLOW_ENERGY_SAMPLING_METHOD
    elif controlled_focus_pair is None:
        identity["sampling_method"] = _LEGACY_SAMPLING_METHOD
    columns = (
        "particle_id", "tob_us", "mass_th", "charge_e", "kinetic_energy_ev",
        "x_mm", "y_mm", "z_mm", "direction_x", "direction_y", "direction_z",
    )
    state_table_path.parent.mkdir(parents=True, exist_ok=True)
    with state_table_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(columns)
        for state in states:
            position = _vector3(state["position_workbench_mm"], "state position")
            direction = _normalize(_vector3(state["direction_workbench"], "state direction"))
            writer.writerow((
                int(state["particle_id"]),
                f"{_finite(state['tob_us'], 'state tob'):.17g}",
                f"{_finite(state['mass_th'], 'state mass'):.17g}",
                int(state["charge_e"]),
                f"{_finite(state['kinetic_energy_ev'], 'state energy'):.17g}",
                *(f"{value:.17g}" for value in position),
                *(f"{value:.17g}" for value in direction),
            ))
    fly2_path.parent.mkdir(parents=True, exist_ok=True)
    fly2_path.write_text(render_bunch_fly2(states), encoding="utf-8", newline="\n")
    receipt = {
        "schema_version": 1,
        "role": "mrtof_deterministic_ideal_bunch_source",
        "status": "materialized",
        "source_profile_id": source_profile_id,
        "frame_id": frame_id,
        "species": {"mass_th": next(iter(masses)), "charge_e": charge},
        "common_time_of_birth_us": next(iter(birth_times)),
        "cohort_role": cohort_role,
        "nominal_center_state": dict(nominal_center_state or states[0]),
        **identity,
        "state_table": {
            "path": str(state_table_path.resolve()),
            "bytes": state_table_path.stat().st_size,
            "sha256": file_sha256(state_table_path).lower(),
        },
        "fly2": {
            "path": str(fly2_path.resolve()),
            "bytes": fly2_path.stat().st_size,
            "sha256": file_sha256(fly2_path).lower(),
        },
    }
    if cohort_role == _CONTROLLED_DIAGNOSTIC_COHORT_ROLE:
        receipt["center_particle_state"] = dict(states[0])
    if controlled_focus_pair is not None:
        receipt["controlled_focus_pair"] = dict(controlled_focus_pair)
    if controlled_slow_energy_pair is not None:
        receipt["controlled_slow_energy_pair"] = dict(controlled_slow_energy_pair)
    if controlled_transverse_x_pair is not None:
        receipt["controlled_transverse_x_pair"] = dict(controlled_transverse_x_pair)
    if controlled_position_pairs is not None:
        receipt["controlled_position_pairs"] = [
            dict(pair) for pair in controlled_position_pairs
        ]
        if controlled_head_particle_count is None or controlled_head_particle_count < 1:
            raise CandidateContractError("controlled head particle count is invalid")
        receipt["controlled_head_particle_count"] = controlled_head_particle_count
        receipt["volume_particle_id_min"] = controlled_head_particle_count + 1
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n",
    )
    return receipt


def load_verified_bunch_source_receipt(receipt_path: Path) -> dict[str, Any]:
    """Load a materialized bunch only when both payloads retain their identity."""
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateContractError("bunch source receipt is unreadable") from error
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_version") != 1
        or receipt.get("role") != "mrtof_deterministic_ideal_bunch_source"
        or receipt.get("status") != "materialized"
        or receipt.get("sampling_method") not in {
            _SAMPLING_METHOD, _SLOW_ENERGY_SAMPLING_METHOD,
            _ABERRATION_SENTINEL_SAMPLING_METHOD,
            _EXTENDED_ABERRATION_SENTINEL_SAMPLING_METHOD,
            _LEGACY_SAMPLING_METHOD, _FORMAL_VOLUME_SAMPLING_METHOD, _GAUSSIAN_VOLUME_SAMPLING_METHOD,
        }
        or receipt.get("clock_basis") != _CLOCK_BASIS
    ):
        raise CandidateContractError("bunch source receipt identity is invalid")
    cohort_role = receipt.get("cohort_role", _CONTROLLED_DIAGNOSTIC_COHORT_ROLE)
    if cohort_role not in {_CONTROLLED_DIAGNOSTIC_COHORT_ROLE, _FORMAL_VOLUME_COHORT_ROLE}:
        raise CandidateContractError("bunch source cohort role is invalid")
    if (
        cohort_role == _FORMAL_VOLUME_COHORT_ROLE
        and receipt.get("sampling_method") not in {_FORMAL_VOLUME_SAMPLING_METHOD, _GAUSSIAN_VOLUME_SAMPLING_METHOD}
    ):
        raise CandidateContractError("formal volume source has the wrong sampling method")
    species = receipt.get("species")
    if (
        not isinstance(species, dict)
        or _finite(species.get("mass_th"), "bunch source mass") <= 0
        or type(species.get("charge_e")) is not int
        or species["charge_e"] == 0
    ):
        raise CandidateContractError("bunch source receipt species is invalid")
    _finite(receipt.get("common_time_of_birth_us"), "bunch source common birth time")
    if type(receipt.get("particle_count")) is not int or type(receipt.get("mother_particle_count")) is not int:
        raise CandidateContractError("bunch source receipt has a nonstandard particle count")
    try:
        validate_standard_particle_count(receipt["particle_count"])
        validate_standard_particle_count(receipt["mother_particle_count"])
    except (TypeError, ValueError) as error:
        raise CandidateContractError("bunch source receipt has a nonstandard particle count") from error
    expected = receipt.get("expected_particle_ids")
    count = int(receipt["particle_count"])
    if int(receipt["mother_particle_count"]) < count:
        raise CandidateContractError("bunch source mother cohort is smaller than its prefix")
    if expected != list(range(1, count + 1)):
        raise CandidateContractError("bunch source receipt has the wrong ordered particle IDs")
    ids = json.dumps(expected, separators=(",", ":")).encode("utf-8")
    if receipt.get("expected_particle_ids_sha256") != hashlib.sha256(ids).hexdigest():
        raise CandidateContractError("bunch source ordered-ID identity changed")
    for key in ("state_table", "fly2"):
        record = receipt.get(key)
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise CandidateContractError(f"bunch source {key} binding is incomplete")
        path = Path(record["path"])
        if (
            not path.is_file()
            or path.stat().st_size != record.get("bytes")
            or file_sha256(path).lower() != str(record.get("sha256", "")).lower()
        ):
            raise CandidateContractError(f"bunch source {key} identity changed")
    for key in ("definition", "geometry_contract", "accelerator_provider_receipt"):
        record = receipt.get(key)
        if record is None:
            continue
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise CandidateContractError(f"bunch source {key} binding is incomplete")
        path = Path(record["path"])
        if (
            not path.is_file()
            or path.stat().st_size != record.get("bytes")
            or file_sha256(path).lower() != str(record.get("sha256", "")).lower()
        ):
            raise CandidateContractError(f"bunch source {key} identity changed")
    state_table_path = Path(receipt["state_table"]["path"])
    with state_table_path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != count or [int(row["particle_id"]) for row in rows] != expected:
        raise CandidateContractError("bunch state table differs from its particle contract")
    nominal_center = receipt.get("nominal_center_state")
    if not isinstance(nominal_center, dict):
        nominal_center = receipt.get("center_particle_state")
    if (
        not isinstance(nominal_center, dict)
        or _finite(nominal_center.get("mass_th"), "nominal center mass") <= 0.0
        or type(nominal_center.get("charge_e")) is not int
        or nominal_center["charge_e"] == 0
        or _finite(nominal_center.get("kinetic_energy_ev"), "nominal center energy") <= 0.0
    ):
        raise CandidateContractError("bunch nominal center state is invalid")
    _vector3(nominal_center.get("position_workbench_mm"), "nominal center position")
    _normalize(_vector3(nominal_center.get("direction_workbench"), "nominal center direction"))
    center = receipt.get("center_particle_state")
    if cohort_role == _FORMAL_VOLUME_COHORT_ROLE and center is not None:
        raise CandidateContractError("formal volume source cannot publish a center particle")
    if center is not None and (
        not isinstance(center, dict)
        or center.get("particle_id") != 1
        or int(rows[0]["particle_id"]) != 1
        or float(rows[0]["tob_us"]) != _finite(center.get("tob_us"), "center tob")
        or float(rows[0]["mass_th"]) != _finite(center.get("mass_th"), "center mass")
        or int(rows[0]["charge_e"]) != center.get("charge_e")
        or float(rows[0]["kinetic_energy_ev"]) != _finite(center.get("kinetic_energy_ev"), "center energy")
        or [float(rows[0][key]) for key in ("x_mm", "y_mm", "z_mm")]
        != list(_vector3(center.get("position_workbench_mm"), "center position"))
        or [float(rows[0][key]) for key in ("direction_x", "direction_y", "direction_z")]
        != list(_normalize(_vector3(center.get("direction_workbench"), "center direction")))
    ):
        raise CandidateContractError("bunch center particle differs from its state table")
    pair = receipt.get("controlled_focus_pair")
    if receipt.get("sampling_method") in {
        _SAMPLING_METHOD, _ABERRATION_SENTINEL_SAMPLING_METHOD,
        _EXTENDED_ABERRATION_SENTINEL_SAMPLING_METHOD,
    }:
        if (
            not isinstance(pair, dict)
            or pair.get("coordinate") != "z_mm"
            or pair.get("negative_particle_id") != 2
            or pair.get("positive_particle_id") != 3
            or pair.get("fixed_variables")
            != "position_x_y__kinetic_energy__direction__mass__charge__birth_time"
        ):
            raise CandidateContractError("bunch controlled focus pair is missing")
        try:
            span = _finite(pair.get("coordinate_span_mm"), "controlled focus span")
            center_row, negative_row, positive_row = rows[0], rows[1], rows[2]
        except IndexError as error:
            raise CandidateContractError("bunch controlled focus pair is incomplete") from error
        fixed_columns = (
            "tob_us", "mass_th", "charge_e", "kinetic_energy_ev", "x_mm", "y_mm",
            "direction_x", "direction_y", "direction_z",
        )
        if (
            span <= 0.0
            or any(negative_row[name] != center_row[name] or positive_row[name] != center_row[name]
                   for name in fixed_columns)
            or not math.isclose(float(positive_row["z_mm"]) - float(negative_row["z_mm"]), span,
                                rel_tol=0.0, abs_tol=1e-12)
            or not math.isclose(
                (float(positive_row["z_mm"]) + float(negative_row["z_mm"])) / 2.0,
                float(center_row["z_mm"]), rel_tol=0.0, abs_tol=1e-12,
            )
        ):
            raise CandidateContractError("bunch controlled focus pair differs from its state table")
    slow_pair = receipt.get("controlled_slow_energy_pair")
    if receipt.get("sampling_method") in {
        _SLOW_ENERGY_SAMPLING_METHOD, _ABERRATION_SENTINEL_SAMPLING_METHOD,
        _EXTENDED_ABERRATION_SENTINEL_SAMPLING_METHOD,
    }:
        expected_negative = (
            4 if receipt.get("sampling_method") in {
                _ABERRATION_SENTINEL_SAMPLING_METHOD,
                _EXTENDED_ABERRATION_SENTINEL_SAMPLING_METHOD,
            } else 2
        )
        expected_positive = expected_negative + 1
        if (
            not isinstance(slow_pair, dict)
            or slow_pair.get("coordinate") != "release_slow_y_kinetic_energy_ev"
            or slow_pair.get("negative_particle_id") != expected_negative
            or slow_pair.get("positive_particle_id") != expected_positive
            or slow_pair.get("fixed_variables")
            != "position__direction__mass__charge__birth_time"
        ):
            raise CandidateContractError("bunch controlled slow-energy pair is missing")
        try:
            span = _finite(slow_pair.get("coordinate_span_ev"), "controlled slow-energy span")
            center_row = rows[0]
            negative_row = rows[expected_negative - 1]
            positive_row = rows[expected_positive - 1]
        except IndexError as error:
            raise CandidateContractError("bunch controlled slow-energy pair is incomplete") from error
        fixed_columns = (
            "tob_us", "mass_th", "charge_e", "x_mm", "y_mm", "z_mm",
            "direction_x", "direction_y", "direction_z",
        )
        if (
            span <= 0.0
            or any(negative_row[name] != center_row[name] or positive_row[name] != center_row[name]
                   for name in fixed_columns)
            or not math.isclose(
                float(positive_row["kinetic_energy_ev"])
                - float(negative_row["kinetic_energy_ev"]),
                span, rel_tol=0.0, abs_tol=1e-12,
            )
            or not math.isclose(
                (float(positive_row["kinetic_energy_ev"])
                 + float(negative_row["kinetic_energy_ev"])) / 2.0,
                float(center_row["kinetic_energy_ev"]), rel_tol=0.0, abs_tol=1e-12,
            )
        ):
            raise CandidateContractError(
                "bunch controlled slow-energy pair differs from its state table"
            )
    x_pair = receipt.get("controlled_transverse_x_pair")
    if receipt.get("sampling_method") in {
        _ABERRATION_SENTINEL_SAMPLING_METHOD,
        _EXTENDED_ABERRATION_SENTINEL_SAMPLING_METHOD,
    }:
        if (
            not isinstance(x_pair, dict)
            or x_pair.get("coordinate") != "x_mm"
            or x_pair.get("negative_particle_id") != 6
            or x_pair.get("positive_particle_id") != 7
            or x_pair.get("fixed_variables")
            != "position_y_z__kinetic_energy__direction__mass__charge__birth_time"
        ):
            raise CandidateContractError("bunch controlled transverse-x pair is missing")
        span = _finite(x_pair.get("coordinate_span_mm"), "controlled transverse-x span")
        center_row, negative_row, positive_row = rows[0], rows[5], rows[6]
        fixed_columns = (
            "tob_us", "mass_th", "charge_e", "kinetic_energy_ev", "y_mm", "z_mm",
            "direction_x", "direction_y", "direction_z",
        )
        if (
            span <= 0.0
            or any(negative_row[name] != center_row[name] or positive_row[name] != center_row[name]
                   for name in fixed_columns)
            or not math.isclose(
                float(positive_row["x_mm"]) - float(negative_row["x_mm"]),
                span, rel_tol=0.0, abs_tol=1e-12,
            )
            or not math.isclose(
                (float(positive_row["x_mm"]) + float(negative_row["x_mm"])) / 2.0,
                float(center_row["x_mm"]), rel_tol=0.0, abs_tol=1e-12,
            )
        ):
            raise CandidateContractError(
                "bunch controlled transverse-x pair differs from its state table"
            )
    position_pairs = receipt.get("controlled_position_pairs")
    if receipt.get("sampling_method") == _EXTENDED_ABERRATION_SENTINEL_SAMPLING_METHOD:
        if (
            not isinstance(position_pairs, list)
            or [pair.get("name") for pair in position_pairs if isinstance(pair, dict)]
            != ["local_z", "local_x", "envelope_y", "envelope_x", "envelope_z"]
            or receipt.get("controlled_head_particle_count") != 13
            or receipt.get("volume_particle_id_min") != 14
        ):
            raise CandidateContractError("bunch controlled position-pair metadata is invalid")
        center_row = rows[0]
        coordinate_columns = {"x_mm", "y_mm", "z_mm"}
        for controlled_position_pair in position_pairs:
            coordinate = controlled_position_pair.get("coordinate")
            try:
                negative_id = int(controlled_position_pair["negative_particle_id"])
                positive_id = int(controlled_position_pair["positive_particle_id"])
                span = _finite(
                    controlled_position_pair.get("coordinate_span_mm"),
                    "controlled position span",
                )
                negative_row = rows[negative_id - 1]
                positive_row = rows[positive_id - 1]
            except (IndexError, KeyError, TypeError, ValueError) as error:
                raise CandidateContractError(
                    "bunch controlled position pair is incomplete"
                ) from error
            fixed_columns = set(center_row) - {"particle_id", coordinate}
            if (
                coordinate not in coordinate_columns
                or span <= 0.0
                or any(
                    negative_row[name] != center_row[name]
                    or positive_row[name] != center_row[name]
                    for name in fixed_columns
                )
                or not math.isclose(
                    float(positive_row[coordinate]) - float(negative_row[coordinate]),
                    span, rel_tol=0.0, abs_tol=1e-12,
                )
                or not math.isclose(
                    (float(positive_row[coordinate]) + float(negative_row[coordinate])) / 2.0,
                    float(center_row[coordinate]), rel_tol=0.0, abs_tol=1e-12,
                )
            ):
                raise CandidateContractError(
                    "bunch controlled position pair differs from its state table"
                )
    fly2_text = Path(receipt["fly2"]["path"]).read_text(encoding="utf-8")
    if fly2_text.count("standard_beam {") != count or "circle_distribution" in fly2_text:
        raise CandidateContractError("bunch Fly2 is not an explicit per-particle source")
    return receipt


def source_cohort_identity(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Project the immutable source fields used by pilot and fixed-time flights."""
    keys = (
        "source_profile_id", "frame_id", "cohort_role", "sampling_method", "particle_count",
        "mother_particle_count", "prefix_rule", "clock_basis",
        "expected_particle_ids_sha256", "particle_states_sha256",
    )
    if any(key not in receipt for key in keys):
        raise CandidateContractError("bunch source receipt lacks cohort identity")
    return {
        **{key: receipt[key] for key in keys},
        **{key: receipt[key] for key in ("release_energy_distribution", "latent_mother_sequence") if key in receipt},
    }


def resolve_bunch_source_interval(
    *, receipt_path: Path, particle_id_min: int, particle_id_max: int,
) -> dict[str, Any]:
    """Resolve one immutable contiguous interval from a verified mother cohort."""
    receipt = load_verified_bunch_source_receipt(receipt_path)
    count = int(receipt["particle_count"])
    if not 1 <= particle_id_min <= particle_id_max <= count:
        raise ValueError("source particle interval is outside the frozen cohort")
    with Path(receipt["state_table"]["path"]).open(
        "r", encoding="utf-8", newline="",
    ) as stream:
        rows = list(csv.DictReader(stream))
    selected = rows[particle_id_min - 1:particle_id_max]
    particle_ids = list(range(particle_id_min, particle_id_max + 1))
    if [int(row["particle_id"]) for row in selected] != particle_ids:
        raise ValueError("source selection is not one contiguous global-ID interval")
    states = [{
        "tob_us": float(row["tob_us"]),
        "mass_th": float(row["mass_th"]),
        "charge_e": int(row["charge_e"]),
        "kinetic_energy_ev": float(row["kinetic_energy_ev"]),
        "position_workbench_mm": [float(row[key]) for key in ("x_mm", "y_mm", "z_mm")],
        "direction_workbench": [
            float(row[key]) for key in ("direction_x", "direction_y", "direction_z")
        ],
    } for row in selected]
    fly2 = render_bunch_fly2(states)
    ids_payload = json.dumps(particle_ids, separators=(",", ":")).encode("utf-8")
    state_payload = json.dumps(states, sort_keys=True, separators=(",", ":")).encode("utf-8")
    parent_identity = source_cohort_identity(receipt)
    cohort_identity = {
        **parent_identity,
        "particle_count": len(states),
        "expected_particle_ids_sha256": hashlib.sha256(ids_payload).hexdigest(),
        "particle_states_sha256": hashlib.sha256(state_payload).hexdigest(),
        "selection": {
            "role": "contiguous_frozen_source_diagnostic_selection",
            "particle_id_min": particle_id_min,
            "particle_id_max": particle_id_max,
            "parent_particle_count": count,
            "parent_particle_states_sha256": parent_identity["particle_states_sha256"],
            "source_receipt_sha256": file_sha256(receipt_path).lower(),
        },
    }
    selected_fly2_sha256 = hashlib.sha256(fly2.encode("utf-8")).hexdigest()
    cohort_identity["selection"].update({
        "expected_particle_ids_sha256": cohort_identity["expected_particle_ids_sha256"],
        "particle_states_sha256": cohort_identity["particle_states_sha256"],
        "fly2_sha256": selected_fly2_sha256,
    })
    return {
        "particle_ids": particle_ids,
        "states": states,
        "fly2": fly2,
        "fly2_sha256": selected_fly2_sha256,
        "source_cohort": cohort_identity,
    }


def solver_problem_identity_from_trial_receipt(
    trial_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind the field, geometry, voltages and numerics shared by pilot/final runs."""
    required = (
        "selected_axial_energy_per_charge_v", "mirror_voltages_v",
        "stripe_biases_v", "prism_voltages_v", "accelerator_endpoint_voltages_v",
        "accelerator_ring_voltages_v", "trajectory_profile", "inputs",
        "target_drift_period_ratio", "target_half_oscillation_count",
    )
    missing = [name for name in required if name not in trial_receipt]
    if missing:
        raise CandidateContractError(
            "pilot trial receipt lacks solver identity: " + ", ".join(missing)
        )
    inputs = trial_receipt.get("inputs")
    if not isinstance(inputs, dict):
        raise CandidateContractError("pilot trial receipt inputs are invalid")
    stable_inputs = {
        key: value for key, value in inputs.items()
        if key != "accelerator_pulse_schedule_sha256"
    }
    flight_scope = trial_receipt.get("flight_scope")
    if flight_scope is None:
        raise CandidateContractError(
            "pilot trial receipt does not identify the complete 3-D flight scope"
        )
    if flight_scope != "complete_three_dimensional_static_return":
        raise CandidateContractError("pilot trial receipt has a forbidden flight scope")
    projection = {
        "schema_version": 1,
        "role": "mrtof_bunch_solver_problem_identity",
        **{name: trial_receipt[name] for name in required if name != "inputs"},
        "inputs": stable_inputs,
        "flight_scope": flight_scope,
    }
    return {**projection, "canonical_sha256": _canonical_sha256(projection)}


def freeze_bunch_pulse_schedule_from_files(
    *,
    source_receipt_path: Path,
    pilot_log_path: Path,
    pilot_trial_receipt_path: Path,
    guard_us: float,
    output_path: Path,
    pulse_off_time_us: float | None = None,
) -> dict[str, Any]:
    """Freeze a detector-blind schedule from one complete frozen pilot cohort."""
    source = load_verified_bunch_source_receipt(source_receipt_path)
    trial = _load_object(pilot_trial_receipt_path, "pilot trial receipt")
    selection = trial.get("source_selection")
    if isinstance(selection, dict):
        # The runner records every explicit interval, including the complete
        # 1..N interval.  Reconstruct that exact view instead of inferring the
        # parent cohort merely because its particle count happens to match.
        # This preserves strict source identity while allowing a complete
        # interval to use its independently rendered Fly2 representation.
        try:
            interval = resolve_bunch_source_interval(
                receipt_path=source_receipt_path,
                particle_id_min=int(selection["particle_id_min"]),
                particle_id_max=int(selection["particle_id_max"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise CandidateContractError("pilot source interval identity is invalid") from error
        expected_cohort = interval["source_cohort"]
        expected_fly2_sha256 = interval["fly2_sha256"]
        expected_particle_ids = interval["particle_ids"]
    else:
        if trial.get("source_particle_count") != source["particle_count"]:
            raise CandidateContractError("pilot trial particle count differs from source cohort")
        expected_cohort = source_cohort_identity(source)
        expected_fly2_sha256 = source["fly2"]["sha256"]
        expected_particle_ids = list(source["expected_particle_ids"])
    if trial.get("source_cohort") != expected_cohort:
        raise CandidateContractError("pilot trial consumed a different source cohort")
    if str(trial.get("fly2_sha256", "")).lower() != str(expected_fly2_sha256).lower():
        raise CandidateContractError("pilot trial Fly2 differs from source cohort")
    pulse = trial.get("accelerator_pulse")
    if (
        not isinstance(pulse, dict)
        or pulse.get("mode") != "static"
        or pulse.get("qualification") != "static_accelerator"
        or pulse.get("fixed_global_time_applied") is not False
    ):
        raise CandidateContractError(
            "bunch safe-exit pilot must use the static accelerator state"
        )
    trajectory = trial.get("trajectory_profile")
    if not isinstance(trajectory, dict):
        raise CandidateContractError("pilot trial has no trajectory profile")
    maximum_step_us = _finite(
        trajectory.get("maximum_step_us"), "pilot maximum trajectory step"
    )
    events = parse_events(pilot_log_path.read_text(encoding="utf-8"))
    schedule = derive_bunch_pulse_schedule(
        events=events,
        expected_particle_ids=expected_particle_ids,
        guard_us=guard_us,
        pilot_maximum_step_us=maximum_step_us,
        source_cohort_identity=expected_cohort,
        solver_problem_identity=solver_problem_identity_from_trial_receipt(trial),
        pulse_off_time_us=pulse_off_time_us,
        accelerator_instance=int(trial.get("accelerator_instance", 3)),
    )
    schedule["inputs"] = {
        "source_receipt_sha256": file_sha256(source_receipt_path).lower(),
        "pilot_log_sha256": file_sha256(pilot_log_path).lower(),
        "pilot_trial_receipt_sha256": file_sha256(pilot_trial_receipt_path).lower(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(schedule, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    return schedule


def derive_bunch_pulse_schedule(
    *,
    events: Iterable[Mapping[str, Any]],
    expected_particle_ids: Sequence[int],
    guard_us: float,
    pilot_maximum_step_us: float,
    source_cohort_identity: Mapping[str, Any],
    solver_problem_identity: Mapping[str, Any],
    pulse_off_time_us: float | None = None,
    accelerator_instance: int = 3,
) -> dict[str, Any]:
    """Derive one global off time from every particle's unique safe exit."""
    expected = list(expected_particle_ids)
    if expected != list(range(1, len(expected) + 1)):
        raise CandidateContractError("expected bunch IDs must be contiguous and one-based")
    guard = _finite(guard_us, "accelerator pulse guard")
    maximum_step = _finite(pilot_maximum_step_us, "pilot maximum step")
    if type(accelerator_instance) is not int or accelerator_instance != 3:
        raise CandidateContractError("accelerator instance must be 3")
    if maximum_step <= 0 or guard < maximum_step:
        raise CandidateContractError("accelerator pulse guard must cover at least one pilot maximum step")
    if not source_cohort_identity or not solver_problem_identity:
        raise CandidateContractError("source and solver identities are required")

    materialized = [dict(event) for event in events]
    exits = [event for event in materialized if event.get("kind") == "accelerator_safe_exit"]
    unknown = sorted({int(event.get("ion", -1)) for event in exits} - set(expected))
    if unknown:
        raise CandidateContractError(f"safe-exit events contain unknown particles: {unknown}")
    selected: list[dict[str, Any]] = []
    for particle_id in expected:
        matches = [event for event in exits if int(event.get("ion", -1)) == particle_id]
        if len(matches) != 1:
            raise CandidateContractError(
                f"particle {particle_id} must have exactly one accelerator safe exit"
            )
        event = matches[0]
        time_us = _finite(event.get("t_us"), "safe-exit time")
        if (
            int(event.get("from_instance", -1)) != accelerator_instance
            or int(event.get("to_instance", accelerator_instance)) == accelerator_instance
            or _finite(event.get("vz_mm_us"), "safe-exit axial velocity") >= 0
        ):
            raise CandidateContractError(f"particle {particle_id} has a non-injection safe exit")
        exit_index = next(
            index for index, item in enumerate(materialized) if item is event
        )
        if any(
            item.get("kind") in {"terminal", "splat"}
            and int(item.get("ion", -1)) == particle_id
            for item in materialized[:exit_index]
        ):
            raise CandidateContractError(f"particle {particle_id} terminated before its safe exit")
        selected.append({
            "particle_id": particle_id,
            "time_us": time_us,
            "from_instance": accelerator_instance,
            "to_instance": int(event["to_instance"]),
        })
    last = max(selected, key=lambda item: (item["time_us"], item["particle_id"]))
    minimum_pulse_off_time_us = last["time_us"] + guard
    if pulse_off_time_us is None:
        selected_pulse_off_time_us = minimum_pulse_off_time_us
        pulse_off_authority = "cohort_last_safe_exit_plus_guard"
    else:
        selected_pulse_off_time_us = _finite(
            pulse_off_time_us, "common accelerator pulse-off time"
        )
        if selected_pulse_off_time_us < minimum_pulse_off_time_us:
            raise CandidateContractError(
                "common accelerator pulse-off time precedes the cohort safe-exit envelope"
            )
        pulse_off_authority = "caller_common_envelope_verified_against_this_cohort"
    return {
        "schema_version": 2,
        "role": "mrtof_accelerator_global_pulse_schedule",
        "status": "frozen",
        "qualification": "complete_bunch_safe_exit_schedule__numerical_convergence_pending",
        "mode": "fixed_global_time",
        "time_basis": _CLOCK_BASIS,
        "source_cohort": dict(source_cohort_identity),
        "solver_problem_identity": dict(solver_problem_identity),
        "safe_exit_definition": {
            "from_instance": accelerator_instance,
            "to_instance_rule": f"not_{accelerator_instance}",
            "required_project_z_direction": "negative",
            "event_count": len(selected),
            "first_safe_exit_time_us": min(item["time_us"] for item in selected),
            "last_safe_exit_time_us": last["time_us"],
            "last_safe_exit_particle_id": last["particle_id"],
        },
        "guard": {
            "value_us": guard,
            "minimum_basis": "at_least_one_frozen_pilot_maximum_step",
            "pilot_maximum_step_us": maximum_step,
        },
        "pulse_off_time_us": selected_pulse_off_time_us,
        "pulse_off_authority": pulse_off_authority,
        "minimum_pulse_off_time_us": minimum_pulse_off_time_us,
        "additional_common_envelope_margin_us": (
            selected_pulse_off_time_us - minimum_pulse_off_time_us
        ),
        "after_state": {
            "accelerator_electrode_ids": list(range(1, 10)),
            "voltage_v": 0.0,
        },
    }


def validate_fixed_global_pulse_events(
    *,
    events: Iterable[Mapping[str, Any]],
    expected_particle_ids: Sequence[int],
    pulse_off_time_us: float,
    time_tolerance_us: float,
    accelerator_instance: int = 3,
) -> dict[str, Any]:
    """Require a common pulse outside the trial-declared accelerator instance."""
    if type(accelerator_instance) is not int or accelerator_instance != 3:
        raise CandidateContractError("accelerator instance must be 3")
    expected = list(expected_particle_ids)
    if expected != list(range(1, len(expected) + 1)):
        raise CandidateContractError("expected bunch IDs must be contiguous and one-based")
    scheduled = _finite(pulse_off_time_us, "scheduled accelerator pulse time")
    tolerance = _finite(time_tolerance_us, "accelerator pulse time tolerance")
    if scheduled <= 0 or tolerance < 0:
        raise CandidateContractError("pulse time must be positive and tolerance nonnegative")
    selected = [
        dict(event) for event in events
        if event.get("kind") == "accelerator_global_pulse_applied"
    ]
    unknown = sorted({int(event.get("ion", -1)) for event in selected} - set(expected))
    if unknown:
        raise CandidateContractError(f"global pulse events contain unknown particles: {unknown}")
    actual_times: list[float] = []
    for particle_id in expected:
        matches = [event for event in selected if int(event.get("ion", -1)) == particle_id]
        if len(matches) != 1:
            raise CandidateContractError(
                f"particle {particle_id} must have exactly one fixed global pulse event"
            )
        event = matches[0]
        actual = _finite(event.get("t_us"), "actual accelerator pulse time")
        declared = _finite(event.get("scheduled_t_us"), "event scheduled pulse time")
        if event.get("trigger") != "fixed_global_time":
            raise CandidateContractError(f"particle {particle_id} has the wrong pulse trigger")
        if abs(declared - scheduled) > tolerance or abs(actual - scheduled) > tolerance:
            raise CandidateContractError(f"particle {particle_id} missed the common pulse boundary")
        instance = event.get("instance")
        if (type(instance) not in (int, float) or not math.isfinite(instance)
                or instance < 1 or int(instance) != instance):
            raise CandidateContractError(f"particle {particle_id} lacks a valid pulse-off instance")
        if instance == accelerator_instance:
            raise CandidateContractError(f"particle {particle_id} remained in the accelerator at pulse-off")
        actual_times.append(actual)
    return {
        "status": "pass",
        "particle_count": len(expected),
        "event_count": len(selected),
        "scheduled_pulse_off_time_us": scheduled,
        "maximum_absolute_time_error_us": max(
            (abs(value - scheduled) for value in actual_times), default=0.0,
        ),
        "all_particles_outside_accelerator": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    materialize = subparsers.add_parser("materialize-source")
    materialize.add_argument("--definition", required=True, type=Path)
    materialize.add_argument("--state-table", required=True, type=Path)
    materialize.add_argument("--fly2", required=True, type=Path)
    materialize.add_argument("--receipt", required=True, type=Path)
    materialize.add_argument("--geometry-contract", type=Path)
    materialize.add_argument("--accelerator-provider-receipt", type=Path)
    freeze = subparsers.add_parser("freeze-schedule")
    freeze.add_argument("--source-receipt", required=True, type=Path)
    freeze.add_argument("--pilot-log", required=True, type=Path)
    freeze.add_argument("--pilot-trial-receipt", required=True, type=Path)
    freeze.add_argument("--guard-us", required=True, type=float)
    freeze.add_argument("--pulse-off-time-us", type=float)
    freeze.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.command == "materialize-source":
        result = materialize_bunch_source_from_definition(
            definition_path=arguments.definition,
            state_table_path=arguments.state_table,
            fly2_path=arguments.fly2,
            receipt_path=arguments.receipt,
            geometry_contract_path=arguments.geometry_contract,
            accelerator_provider_receipt_path=arguments.accelerator_provider_receipt,
        )
        print(
            "MRTOF_BUNCH_SOURCE_MATERIALIZE=PASS "
            f"N={result['particle_count']} SHA256={result['particle_states_sha256']}"
        )
    else:
        result = freeze_bunch_pulse_schedule_from_files(
            source_receipt_path=arguments.source_receipt,
            pilot_log_path=arguments.pilot_log,
            pilot_trial_receipt_path=arguments.pilot_trial_receipt,
            guard_us=arguments.guard_us,
            output_path=arguments.output,
            pulse_off_time_us=arguments.pulse_off_time_us,
        )
        print(
            "MRTOF_BUNCH_PULSE_SCHEDULE=PASS "
            f"N={result['safe_exit_definition']['event_count']} "
            f"TIME_US={result['pulse_off_time_us']:.12g}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
