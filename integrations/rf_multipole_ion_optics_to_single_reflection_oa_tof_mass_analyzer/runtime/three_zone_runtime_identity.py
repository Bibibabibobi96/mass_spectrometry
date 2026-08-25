"""Validate the frozen three-zone single-flight physical identity in Python."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


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
            and candidate.get("compiler_mode") == "T5_FROZEN_PRIMARY_AND_BRANCH_ONLY"
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

    try:
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
