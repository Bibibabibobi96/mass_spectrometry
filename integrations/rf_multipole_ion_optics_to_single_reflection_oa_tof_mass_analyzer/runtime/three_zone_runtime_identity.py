"""Validate the frozen three-zone single-flight physical identity in Python."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


SUPPORTED_CANDIDATE_MODES = {
    "T5_FROZEN_PRIMARY_AND_BRANCH_ONLY",
    "C3_J3_EXACT_LOCAL_DIRECTION_V1",
    "J2_REAL_FIELD_CANDIDATE_POOL_V1",
    "IDEAL_ACCEPTANCE_250MM_SELECTED_POINT_V1",
    "IDEAL_ACCEPTANCE_250MM_GRID_REALIZED_V1",
    "IDEAL_ACCEPTANCE_300MM_SELECTED_POINT_V1",
    "IDEAL_ACCEPTANCE_300MM_GRID_REALIZED_V1",
}


def _value(document: dict[str, Any], *keys: str) -> Any:
    value: Any = document
    for key in keys:
        if not isinstance(value, dict):
            raise ValueError("Frozen three-zone Candidate/runtime identity differs.")
        value = value[key]
    return value


def _text(document: dict[str, Any], *keys: str) -> str:
    value = _value(document, *keys)
    return "" if value is None else str(value)


def _positive_finite(document: dict[str, Any], key: str) -> bool:
    """Whether a candidate-owned physical extent is a usable scalar."""

    try:
        value = float(document[key])
    except (KeyError, TypeError, ValueError):
        return False
    return math.isfinite(value) and value > 0.0


def _field_profile(
    configuration: dict[str, Any], profile_id: str
) -> dict[str, Any]:
    profiles = configuration.get("accelerator_field_profiles")
    matches = [
        profile
        for profile in profiles if isinstance(profile, dict)
        and profile.get("profile_id") == profile_id
    ] if isinstance(profiles, list) else []
    if len(matches) != 1:
        raise ValueError("Frozen three-zone Candidate/runtime identity differs.")
    return matches[0]


def validate_runtime_identity(
    *,
    candidate: dict[str, Any],
    candidate_sha256: str,
    geometry: dict[str, Any],
    geometry_sha256: str,
    frontend_contract: dict[str, Any],
    frontend_electrode_topology: dict[str, Any],
    region_field: dict[str, Any],
    configuration: dict[str, Any],
    layout_profile_id: str,
    architecture_generation_id: str,
    theory_working_point: dict[str, Any] | None = None,
) -> dict[str, str | int]:
    """Return the identity projection when all compiled three-zone inputs agree."""

    try:
        topology_id = _text(candidate, "identities", "topology_id")
        geometry_id = _text(candidate, "identities", "geometry_id")
        frontend_topology_id = _text(frontend_electrode_topology, "topology_id")
        field_profile_id = _text(region_field, "semantic", "canonical_profile_id")
        field_profile = _field_profile(configuration, field_profile_id)
        field_id_value = field_profile.get("field_id")
        field_id = "" if field_id_value is None else str(field_id_value)
        identity_matches = (
            int(candidate.get("schema_version", 0)) == 1
            and candidate.get("role") == "oatof_three_zone_simion_candidate_resolved"
            and candidate.get("qualification") == "CANDIDATE_ONLY"
            and candidate.get("compiler_mode") in SUPPORTED_CANDIDATE_MODES
            and bool(topology_id.strip())
            and bool(geometry_id.strip())
            and _text(candidate, "accelerator_topology", "topology_id") == topology_id
            and _text(geometry, "single_flight_layout_derivation", "layout_profile_id")
            == layout_profile_id
            and _text(geometry, "single_flight_layout_derivation", "architecture_generation_id")
            == architecture_generation_id
            and _text(
                geometry,
                "single_flight_layout_derivation",
                "design_compilation",
                "candidate",
                "sha256",
            )
            == candidate_sha256
            and _text(geometry, "accelerator_topology", "topology_id") == topology_id
            and _text(frontend_contract, "accelerator_topology_id") == topology_id
            and bool(frontend_topology_id.strip())
            and _text(region_field, "layout_geometry", "sha256") == geometry_sha256
            and _text(
                region_field, "semantic", "accelerator_topology", "topology_id"
            )
            == topology_id
            and field_profile.get("profile_id") == field_profile_id
            and field_profile.get("topology_id") == topology_id
            and field_profile.get("geometry_id") == geometry_id
            and field_profile.get("frontend_electrode_topology_id")
            == frontend_topology_id
            and bool(field_id.strip())
        )
    except (KeyError, TypeError, ValueError):
        identity_matches = False
    if not identity_matches:
        raise ValueError("Frozen three-zone Candidate/runtime identity differs.")
    if candidate.get("compiler_mode") == "C3_J3_EXACT_LOCAL_DIRECTION_V1":
        evidence = candidate.get("c3_j3_evidence")
        if (
            not isinstance(evidence, dict)
            or set(evidence) != {"physical_family", "scale_h"}
            or theory_working_point is not None
        ):
            raise ValueError("C3 J3 Candidate/runtime identity differs.")
    if candidate.get("compiler_mode") == "J2_REAL_FIELD_CANDIDATE_POOL_V1":
        evidence = candidate.get("j2_evidence")
        if (
            not isinstance(evidence, dict)
            or set(evidence) != {"candidate_pool_id", "candidate_id", "pool_request_sha256"}
            or theory_working_point is not None
        ):
            raise ValueError("J2 Candidate/runtime identity differs.")
    if candidate.get("compiler_mode") in {
        "IDEAL_ACCEPTANCE_250MM_SELECTED_POINT_V1",
        "IDEAL_ACCEPTANCE_250MM_GRID_REALIZED_V1",
        "IDEAL_ACCEPTANCE_300MM_SELECTED_POINT_V1",
        "IDEAL_ACCEPTANCE_300MM_GRID_REALIZED_V1",
    }:
        evidence = candidate.get("ideal_acceptance_evidence")
        if (
            not isinstance(evidence, dict)
            # These are candidate-owned physical values.  Requiring the old
            # 4 mm and 250/300 mm study points here would turn an identity
            # check into an unnecessary limit on future realizations.
            or not _positive_finite(evidence, "full_width_mm")
            or not _positive_finite(evidence, "total_acceleration_length_mm")
            or theory_working_point is not None
        ):
            raise ValueError("ideal-acceptance Candidate/runtime identity differs.")
    if candidate.get("compiler_mode") in {
        "IDEAL_ACCEPTANCE_250MM_GRID_REALIZED_V1",
        "IDEAL_ACCEPTANCE_300MM_GRID_REALIZED_V1",
    }:
        realization = candidate.get("numerical_grid_realization")
        if not isinstance(realization, dict):
            raise ValueError("grid-realized Candidate lacks numerical realization evidence.")
        try:
            grid_z = float(realization["axial_grid_z_mm"])
            lengths = realization["zone_lengths_mm"]
            residual = realization["scaled_focus_equation_residual_ns"]
            aligned = all(
                abs(float(lengths[role]) / grid_z - round(float(lengths[role]) / grid_z))
                <= 1.0e-8
                for role in ("d1", "d2", "d3")
            )
            closed = len(residual) == 3 and all(abs(float(value)) <= 1.0e-6 for value in residual)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            aligned = False
            closed = False
        if not aligned or not closed:
            raise ValueError("grid-realized Candidate numerical closure differs.")

    try:
        compilation = _value(
            geometry, "single_flight_layout_derivation", "design_compilation"
        )
        translation = float(compilation.get("candidate_axial_translation_z_mm", 0.0))
        if candidate.get("compiler_mode") in {
            "IDEAL_ACCEPTANCE_250MM_SELECTED_POINT_V1",
            "IDEAL_ACCEPTANCE_250MM_GRID_REALIZED_V1",
            "IDEAL_ACCEPTANCE_300MM_SELECTED_POINT_V1",
            "IDEAL_ACCEPTANCE_300MM_GRID_REALIZED_V1",
        }:
            if not translation:
                raise ValueError("ideal-acceptance Candidate axial placement is missing.")
        elif translation != 0.0:
            raise ValueError("unexpected Candidate axial placement.")
        for mapping_name in ("planes_global_z_mm", "potentials_v"):
            for role in ("repeller", "intermediate1", "intermediate2", "exit"):
                candidate_value = float(
                    _value(candidate, "accelerator_topology", mapping_name, role)
                )
                expected_value = (
                    float(
                        _value(
                            theory_working_point,
                            "accelerator_topology",
                            "potentials_v",
                            role,
                        )
                    )
                    if theory_working_point is not None
                    and mapping_name == "potentials_v"
                    else candidate_value
                )
                if (
                    mapping_name == "planes_global_z_mm"
                    and theory_working_point is None
                ):
                    expected_value += translation
                if (
                    float(_value(geometry, "accelerator_topology", mapping_name, role))
                    != expected_value
                    or float(
                        _value(
                            region_field,
                            "semantic",
                            "accelerator_topology",
                            mapping_name,
                            role,
                        )
                    )
                    != expected_value
                ):
                    raise ValueError(
                        "Frozen three-zone Candidate plane or potential mapping differs."
                    )
    except (KeyError, TypeError, ValueError) as exc:
        if "plane or potential mapping differs" in str(exc):
            raise
        raise ValueError(
            "Frozen three-zone Candidate plane or potential mapping differs."
        ) from exc

    if theory_working_point is not None:
        try:
            theory_matches = (
                theory_working_point.get("role") == "rf_oatof_theory_working_point"
                and theory_working_point.get("policy_id")
                == "source_zvz_three_zone_theory_working_point_v1"
                and float(_value(geometry, "electrodes_V", "midgrid"))
                == float(_value(theory_working_point, "reflectron", "stage1_voltage_v"))
                and float(_value(geometry, "electrodes_V", "backplate"))
                == float(_value(theory_working_point, "reflectron", "backplate_voltage_v"))
            )
        except (KeyError, TypeError, ValueError):
            theory_matches = False
        if not theory_matches:
            raise ValueError("Theory working point and resolved electrode potentials differ.")
    return {
        "schema_version": 1,
        "role": "rf_oatof_three_zone_runtime_identity",
        "topology_id": topology_id,
        "geometry_id": geometry_id,
        "frontend_electrode_topology_id": frontend_topology_id,
        "field_profile_id": field_profile_id,
        "field_id": field_id,
    }


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--candidate-sha256", required=True)
    parser.add_argument("--geometry", required=True, type=Path)
    parser.add_argument("--geometry-sha256", required=True)
    parser.add_argument("--frontend-contract", required=True, type=Path)
    parser.add_argument("--frontend-electrode-topology", required=True, type=Path)
    parser.add_argument("--region-field", required=True, type=Path)
    parser.add_argument("--configuration", required=True, type=Path)
    parser.add_argument("--layout-profile-id", required=True)
    parser.add_argument("--architecture-generation-id", required=True)
    parser.add_argument("--theory-working-point", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    projection = validate_runtime_identity(
        candidate=_load(args.candidate),
        candidate_sha256=args.candidate_sha256,
        geometry=_load(args.geometry),
        geometry_sha256=args.geometry_sha256,
        frontend_contract=_load(args.frontend_contract),
        frontend_electrode_topology=_load(args.frontend_electrode_topology),
        region_field=_load(args.region_field),
        configuration=_load(args.configuration),
        layout_profile_id=args.layout_profile_id,
        architecture_generation_id=args.architecture_generation_id,
        theory_working_point=(
            _load(args.theory_working_point)
            if args.theory_working_point is not None
            else None
        ),
    )
    if args.output is not None:
        args.output.write_text(
            json.dumps(projection, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
