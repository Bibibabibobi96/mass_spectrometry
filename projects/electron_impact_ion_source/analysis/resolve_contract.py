"""Resolve and validate the electron-impact ion-source machine contract."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

PROJECT_ID = "electron_impact_ion_source"
MODEL_ID = "ei_source.long_thin_apertured_tube.yield_feasibility.v1"


class ContractError(ValueError):
    """Raised when a contract violates identity, units, shape, or range rules."""


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
    maximum: float | None = None,
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
    if maximum is not None and numeric > maximum:
        raise ContractError(f"{context} must be <= {maximum}")
    return numeric


def _require_positive_integer(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{context} must be a positive integer")
    return value


def load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object and reject non-standard numeric constants."""

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


def validate_baseline(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate the physical-input source without inventing defaults."""

    _require_exact_keys(
        raw,
        {
            "schema_version",
            "role",
            "project_id",
            "model_id",
            "capability",
            "geometry_mm",
            "electrodes_V",
            "gas",
            "ionization",
            "electron_source",
        },
        "baseline",
    )
    if raw["schema_version"] != 1:
        raise ContractError("baseline.schema_version must equal 1")
    if raw["role"] != "electron_impact_ion_source_physical_baseline":
        raise ContractError("baseline.role identity mismatch")
    if raw["project_id"] != PROJECT_ID or raw["model_id"] != MODEL_ID:
        raise ContractError("baseline project/model identity mismatch")

    capability = _require_dict(raw["capability"], "baseline.capability")
    _require_exact_keys(
        capability, {"id", "heavy_ion_source_claim_allowed"}, "baseline.capability"
    )
    if capability["id"] != "electron_impact_ionization_yield_feasibility":
        raise ContractError("baseline.capability.id identity mismatch")
    if _require_bool(
        capability["heavy_ion_source_claim_allowed"],
        "baseline.capability.heavy_ion_source_claim_allowed",
    ):
        raise ContractError("prototype contract must not claim a heavy-ion source")

    geometry = _require_dict(raw["geometry_mm"], "baseline.geometry_mm")
    geometry_keys = {
        "tube_bore_radius",
        "cathode_anode_path_length",
        "electrode_disk_thickness",
        "electrode_aperture_radius",
        "boolean_hole_overshoot_each_side",
        "release_volume_radius",
        "release_volume_length",
        "release_volume_start_z",
        "collector_capture_backoff",
    }
    _require_exact_keys(geometry, geometry_keys, "baseline.geometry_mm")
    for key in geometry_keys:
        _require_number(
            geometry[key],
            f"baseline.geometry_mm.{key}",
            minimum=0.0,
            strict_minimum=True,
        )
    if geometry["electrode_aperture_radius"] >= geometry["tube_bore_radius"]:
        raise ContractError("electrode aperture must be inside the tube bore")
    if geometry["release_volume_radius"] > geometry["electrode_aperture_radius"]:
        raise ContractError("release volume radius must fit through the aperture")
    release_end = (
        geometry["release_volume_start_z"] + geometry["release_volume_length"]
    )
    if release_end >= geometry["cathode_anode_path_length"]:
        raise ContractError("release volume must remain inside the path length")
    if geometry["collector_capture_backoff"] >= geometry["cathode_anode_path_length"]:
        raise ContractError("collector backoff must be smaller than the path length")

    electrodes = _require_dict(raw["electrodes_V"], "baseline.electrodes_V")
    _require_exact_keys(electrodes, {"cathode", "anode"}, "baseline.electrodes_V")
    cathode = _require_number(electrodes["cathode"], "baseline.electrodes_V.cathode")
    anode = _require_number(electrodes["anode"], "baseline.electrodes_V.anode")
    if anode <= cathode:
        raise ContractError("anode voltage must exceed cathode voltage")

    gas = _require_dict(raw["gas"], "baseline.gas")
    _require_exact_keys(
        gas, {"neutral_number_density_per_m3", "relative_permittivity"}, "baseline.gas"
    )
    _require_number(
        gas["neutral_number_density_per_m3"],
        "baseline.gas.neutral_number_density_per_m3",
        minimum=0.0,
        strict_minimum=True,
    )
    _require_number(
        gas["relative_permittivity"],
        "baseline.gas.relative_permittivity",
        minimum=1.0,
    )

    ionization = _require_dict(raw["ionization"], "baseline.ionization")
    ionization_keys = {
        "cross_section_m2",
        "primary_energy_loss_eV",
        "release_secondary_electron",
        "release_ionized_particle",
        "release_primary_electron",
        "count_all_collisions",
        "count_ionization_collisions",
        "collision_detection",
    }
    _require_exact_keys(ionization, ionization_keys, "baseline.ionization")
    _require_number(
        ionization["cross_section_m2"],
        "baseline.ionization.cross_section_m2",
        minimum=0.0,
        strict_minimum=True,
    )
    _require_number(
        ionization["primary_energy_loss_eV"],
        "baseline.ionization.primary_energy_loss_eV",
        minimum=0.0,
        strict_minimum=True,
    )
    for key in (
        "release_secondary_electron",
        "release_ionized_particle",
        "release_primary_electron",
        "count_all_collisions",
        "count_ionization_collisions",
    ):
        _require_bool(ionization[key], f"baseline.ionization.{key}")
    if ionization["release_ionized_particle"]:
        raise ContractError("this prototype must not enable heavy-ion release")
    if not ionization["release_primary_electron"]:
        raise ContractError("primary-electron release must remain enabled")
    if (
        _require_string(
            ionization["collision_detection"],
            "baseline.ionization.collision_detection",
        )
        != "NullCollisionMethodColdGasApproximation"
    ):
        raise ContractError("unsupported collision detection method")

    source = _require_dict(raw["electron_source"], "baseline.electron_source")
    _require_exact_keys(
        source, {"release_velocity_m_per_s", "velocity_distribution"}, "source"
    )
    velocity = source["release_velocity_m_per_s"]
    if not isinstance(velocity, list) or len(velocity) != 3:
        raise ContractError("release_velocity_m_per_s must contain x/y/z")
    components = [
        _require_number(item, f"release_velocity_m_per_s[{index}]")
        for index, item in enumerate(velocity)
    ]
    if math.sqrt(sum(item * item for item in components)) <= 0.0:
        raise ContractError("release velocity magnitude must be positive")
    if source["velocity_distribution"] != "fixed":
        raise ContractError("unsupported velocity distribution")
    return raw


def validate_modes(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate the finite set of supported numerical modes."""

    _require_exact_keys(
        raw, {"schema_version", "role", "project_id", "modes"}, "numerical modes"
    )
    if raw["schema_version"] != 1:
        raise ContractError("numerical_modes.schema_version must equal 1")
    if raw["role"] != "electron_impact_ion_source_numerical_modes":
        raise ContractError("numerical_modes.role identity mismatch")
    if raw["project_id"] != PROJECT_ID:
        raise ContractError("numerical_modes.project_id identity mismatch")
    modes = _require_dict(raw["modes"], "numerical_modes.modes")
    if set(modes) != {"build_only_smoke", "functional_reference"}:
        raise ContractError("numerical mode identities are fixed and exhaustive")
    for mode_id, value in modes.items():
        mode = _require_dict(value, f"mode.{mode_id}")
        _require_exact_keys(
            mode,
            {
                "execution_mode",
                "evidence_kind",
                "candidate_evidence_allowed",
                "minimum_evidence_particle_count",
                "mesh",
                "time_ns",
                "solver",
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
        _require_exact_keys(mesh, {"automatic_level"}, f"mode.{mode_id}.mesh")
        level = _require_positive_integer(
            mesh["automatic_level"], f"mode.{mode_id}.mesh.automatic_level"
        )
        if level > 9:
            raise ContractError("mesh automatic level must be in [1, 9]")

        time_ns = _require_dict(mode["time_ns"], f"mode.{mode_id}.time_ns")
        _require_exact_keys(time_ns, {"end", "step"}, f"mode.{mode_id}.time_ns")
        end_ns = _require_number(
            time_ns["end"],
            f"mode.{mode_id}.time_ns.end",
            minimum=0.0,
            strict_minimum=True,
        )
        step_ns = _require_number(
            time_ns["step"],
            f"mode.{mode_id}.time_ns.step",
            minimum=0.0,
            strict_minimum=True,
        )
        if step_ns > end_ns:
            raise ContractError("time step must not exceed the end time")

        solver = _require_dict(mode["solver"], f"mode.{mode_id}.solver")
        _require_exact_keys(
            solver, {"time_integrator", "strict_time_steps"}, f"mode.{mode_id}.solver"
        )
        if solver["time_integrator"] != "BDF":
            raise ContractError("only the validated BDF integrator is supported")
        _require_bool(
            solver["strict_time_steps"], f"mode.{mode_id}.solver.strict_time_steps"
        )

        reporting = _require_dict(mode["reporting"], f"mode.{mode_id}.reporting")
        _require_exact_keys(
            reporting,
            {"maximum_trajectory_curves", "figure_dpi"},
            f"mode.{mode_id}.reporting",
        )
        _require_positive_integer(
            reporting["maximum_trajectory_curves"],
            f"mode.{mode_id}.reporting.maximum_trajectory_curves",
        )
        _require_positive_integer(
            reporting["figure_dpi"], f"mode.{mode_id}.reporting.figure_dpi"
        )
    return raw


def resolve_contract(
    baseline: dict[str, Any],
    modes: dict[str, Any],
    mode_id: str,
    evidence_particle_count: int | None,
) -> dict[str, Any]:
    """Combine physical baseline and one named numerical mode."""

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
    evidence = {
        "requested_particle_count": evidence_particle_count,
        "candidate_evidence_allowed": selected["candidate_evidence_allowed"],
        "minimum_particle_count": minimum_count,
        "scope": selected["evidence_kind"],
    }
    return {
        "schema_version": 1,
        "role": "electron_impact_ion_source_resolved_contract",
        "project_id": PROJECT_ID,
        "model_id": MODEL_ID,
        "selected_mode_id": mode_id,
        "physical": baseline,
        "numerical": selected,
        "evidence": evidence,
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    """Write deterministic UTF-8 JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""

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
        if args.check is not None:
            existing = load_json(args.check)
            if existing != resolved:
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
