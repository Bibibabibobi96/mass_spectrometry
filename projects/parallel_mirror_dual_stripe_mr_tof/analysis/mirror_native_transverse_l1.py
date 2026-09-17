"""Prepare and reduce a native-SIMION transverse bare-mirror L1 probe.

This module is deliberately solver-log facing but solver-process free.  It
derives ten deterministic particles from one already frozen bare-mirror period
probe: five transverse perturbations for each of the ``+z`` and ``-z`` launch
directions at the same nominal energy and ``y=280 mm`` slice.  The owning
SIMION program must emit exactly two ``MRTOF_NATIVE_L1`` events per particle:
``first_return`` after one mirror reflection and ``full_return`` after the
second.  Keeping those two events distinct is essential: the L1 map uses the
first return while the time-aberration coefficients use the full period.

No voltage, geometry, PA, or candidate qualification is created here.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

from common.contracts.file_identity import file_sha256


class NativeTransverseL1Error(ValueError):
    """Raised when a native transverse L1 input or SIMION log is invalid."""


PROBE_KINDS = (
    "center",
    "x_positive",
    "x_negative",
    "alpha_positive",
    "alpha_negative",
)
PHASES = ("first_return", "full_return")
_RETURN_Y_TOLERANCE_MM = 1.0e-3
_EVENT = re.compile(r"^MRTOF_NATIVE_L1\s+(?P<fields>.+)$", re.MULTILINE)
_COMPLETED = re.compile(
    r"(?:^|,)(?:Fly'm complete\. Splats:|Fly completed\.)\s*(?P<splats>\d+)(?:\s+splats)?",
    re.MULTILINE,
)


def _finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise NativeTransverseL1Error(f"{label} is not numeric") from error
    if not math.isfinite(result):
        raise NativeTransverseL1Error(f"{label} is non-finite")
    return result


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise NativeTransverseL1Error(f"{label} is not an integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise NativeTransverseL1Error(f"{label} is not an integer") from error
    if str(result) != str(value).strip():
        raise NativeTransverseL1Error(f"{label} is not an integer")
    return result


def _object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NativeTransverseL1Error(f"{label} is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise NativeTransverseL1Error(f"{label} must be an object")
    return value


def _validate_period_probe(period_probe: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the frozen bare-mirror source needed by the L1 probe."""

    if (
        period_probe.get("schema_version") != 2
        or period_probe.get("role") != "mrtof_bare_mirror_real_field_period_probe"
        or period_probe.get("status") != "prepared"
    ):
        raise NativeTransverseL1Error("period probe is not the current prepared real-field contract")
    nominal_energy = _finite(period_probe.get("nominal_energy_ev"), "period probe nominal energy")
    mass = _finite(period_probe.get("particle_mass_th"), "period probe mass")
    charge = _finite(period_probe.get("particle_charge_e"), "period probe charge")
    y_mm = _finite(period_probe.get("probe_y_mm"), "period probe y")
    if nominal_energy <= 0.0 or mass <= 0.0 or charge <= 0.0:
        raise NativeTransverseL1Error("period probe nominal particle state is invalid")
    if not math.isclose(y_mm, 280.0, rel_tol=0.0, abs_tol=1.0e-9):
        raise NativeTransverseL1Error("native transverse L1 is defined only at project y=280 mm")
    voltages = period_probe.get("mirror_voltages_v")
    if (
        not isinstance(voltages, list)
        or len(voltages) != 5
        or any(not math.isfinite(float(value)) for value in voltages)
        or float(voltages[0]) != 0.0
    ):
        raise NativeTransverseL1Error("period probe mirror voltages are invalid")
    for label in ("stripe_biases_v", "prism_voltages_v"):
        values = period_probe.get(label)
        if (
            not isinstance(values, list)
            or len(values) != 2
            or any(not math.isfinite(float(value)) or float(value) != 0.0 for value in values)
        ):
            raise NativeTransverseL1Error(f"period probe {label} must keep the bare-mirror auxiliaries grounded")
    particles = period_probe.get("particles")
    if not isinstance(particles, list) or not particles:
        raise NativeTransverseL1Error("period probe particle list is missing")
    nominal_sources = []
    for particle in particles:
        if not isinstance(particle, dict):
            raise NativeTransverseL1Error("period probe particle is invalid")
        energy = _finite(particle.get("target_energy_ev"), "period probe particle energy")
        position = particle.get("position_project_mm")
        direction = particle.get("direction_project")
        if (
            not isinstance(position, list)
            or len(position) != 3
            or not isinstance(direction, list)
            or len(direction) != 3
            or any(not math.isfinite(float(value)) for value in position + direction)
        ):
            raise NativeTransverseL1Error("period probe particle geometry is invalid")
        if math.isclose(energy, nominal_energy, rel_tol=0.0, abs_tol=1.0e-9):
            nominal_sources.append(particle)
    if len(nominal_sources) != 1:
        raise NativeTransverseL1Error("period probe must contain exactly one nominal-energy particle")
    source = nominal_sources[0]
    if (
        [float(value) for value in source["position_project_mm"]] != [0.0, y_mm, 0.0]
        or [float(value) for value in source["direction_project"]] != [0.0, 0.0, 1.0]
    ):
        raise NativeTransverseL1Error("period probe nominal source is not the project central +z reference")
    return {
        "nominal_energy_ev": nominal_energy,
        "particle_mass_th": mass,
        "particle_charge_e": charge,
        "probe_y_mm": y_mm,
        "mirror_voltages_v": [float(value) for value in voltages],
        "qualification": str(period_probe.get("qualification", "")),
    }


def build_native_l1_probe_contract(
    period_probe_path: Path,
    *,
    position_probe_mm: float,
    angle_probe_rad: float,
) -> dict[str, Any]:
    """Build ten native L1 particles from a frozen period-probe contract.

    ``position_probe_mm`` and ``angle_probe_rad`` are numerical perturbations
    supplied by the owning frozen L1 profile; this function has no defaults.
    """

    position = _finite(position_probe_mm, "position probe")
    angle = _finite(angle_probe_rad, "angle probe")
    if position <= 0.0 or angle <= 0.0:
        raise NativeTransverseL1Error("native L1 perturbations must be positive")
    source_path = period_probe_path.resolve()
    source = _validate_period_probe(_object(source_path, "period probe contract"))
    states = (
        ("center", 0.0, 0.0),
        ("x_positive", position, 0.0),
        ("x_negative", -position, 0.0),
        ("alpha_positive", 0.0, angle),
        ("alpha_negative", 0.0, -angle),
    )
    particles = []
    particle_id = 1
    for direction_z in (-1, 1):
        for probe_kind, initial_x, initial_alpha in states:
            particles.append({
                "particle_id": particle_id,
                "direction_z": direction_z,
                "probe_kind": probe_kind,
                "initial_x_mm": initial_x,
                "initial_alpha_rad": initial_alpha,
                "position_project_mm": [initial_x, source["probe_y_mm"], 0.0],
                "direction_project": [
                    math.sin(initial_alpha), 0.0, direction_z * math.cos(initial_alpha),
                ],
                "energy_ev": source["nominal_energy_ev"],
            })
            particle_id += 1
    contract = {
        "schema_version": 1,
        "role": "mrtof_native_simion_transverse_l1_probe",
        "status": "prepared",
        "qualification": "native_simion_bare_mirror_transverse_l1_diagnostic__not_candidate",
        "source_period_probe_contract_sha256": file_sha256(source_path),
        "source_period_probe_qualification": source["qualification"],
        "mirror_voltages_v": source["mirror_voltages_v"],
        "stripe_biases_v": [0.0, 0.0],
        "prism_voltages_v": [0.0, 0.0],
        "nominal_energy_ev": source["nominal_energy_ev"],
        "particle_mass_th": source["particle_mass_th"],
        "particle_charge_e": source["particle_charge_e"],
        "probe_y_mm": source["probe_y_mm"],
        "position_probe_mm": position,
        "angle_probe_rad": angle,
        "particles": particles,
    }
    validate_native_l1_probe_contract(contract)
    return contract


def validate_native_l1_probe_contract(contract: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    """Fail closed on the stable native L1 source table and particle identity."""

    if (
        contract.get("schema_version") != 1
        or contract.get("role") != "mrtof_native_simion_transverse_l1_probe"
        or contract.get("status") != "prepared"
    ):
        raise NativeTransverseL1Error("native L1 probe contract identity is invalid")
    source_sha = contract.get("source_period_probe_contract_sha256")
    if not isinstance(source_sha, str) or re.fullmatch(r"[A-F0-9]{64}", source_sha) is None:
        raise NativeTransverseL1Error("native L1 contract has no frozen period-probe identity")
    energy = _finite(contract.get("nominal_energy_ev"), "native L1 nominal energy")
    mass = _finite(contract.get("particle_mass_th"), "native L1 mass")
    charge = _finite(contract.get("particle_charge_e"), "native L1 charge")
    y_mm = _finite(contract.get("probe_y_mm"), "native L1 y")
    position = _finite(contract.get("position_probe_mm"), "native L1 position probe")
    angle = _finite(contract.get("angle_probe_rad"), "native L1 angle probe")
    if energy <= 0.0 or mass <= 0.0 or charge <= 0.0 or position <= 0.0 or angle <= 0.0:
        raise NativeTransverseL1Error("native L1 particle or perturbation state is invalid")
    if not math.isclose(y_mm, 280.0, rel_tol=0.0, abs_tol=1.0e-9):
        raise NativeTransverseL1Error("native L1 contract does not use y=280 mm")
    mirror_voltages = contract.get("mirror_voltages_v")
    if (
        not isinstance(mirror_voltages, list)
        or len(mirror_voltages) != 5
        or float(mirror_voltages[0]) != 0.0
        or any(not math.isfinite(float(value)) for value in mirror_voltages)
    ):
        raise NativeTransverseL1Error("native L1 mirror voltage vector is invalid")
    for label in ("stripe_biases_v", "prism_voltages_v"):
        values = contract.get(label)
        if (
            not isinstance(values, list)
            or len(values) != 2
            or any(not math.isfinite(float(value)) or float(value) != 0.0 for value in values)
        ):
            raise NativeTransverseL1Error(f"native L1 {label} must remain grounded")
    particles = contract.get("particles")
    if not isinstance(particles, list) or len(particles) != 10:
        raise NativeTransverseL1Error("native L1 contract requires ten particles")
    expected = {(direction, kind) for direction in (-1, 1) for kind in PROBE_KINDS}
    by_id: dict[int, dict[str, Any]] = {}
    actual: set[tuple[int, str]] = set()
    expected_states = {
        "center": (0.0, 0.0),
        "x_positive": (position, 0.0),
        "x_negative": (-position, 0.0),
        "alpha_positive": (0.0, angle),
        "alpha_negative": (0.0, -angle),
    }
    for particle in particles:
        if not isinstance(particle, dict):
            raise NativeTransverseL1Error("native L1 particle record is invalid")
        particle_id = _integer(particle.get("particle_id"), "native L1 particle id")
        direction = _integer(particle.get("direction_z"), "native L1 direction")
        kind = particle.get("probe_kind")
        if particle_id <= 0 or particle_id in by_id or direction not in {-1, 1} or kind not in PROBE_KINDS:
            raise NativeTransverseL1Error("native L1 particle identity is invalid or duplicate")
        initial_x = _finite(particle.get("initial_x_mm"), "native L1 initial x")
        initial_alpha = _finite(particle.get("initial_alpha_rad"), "native L1 initial alpha")
        expected_x, expected_alpha = expected_states[kind]
        if not (
            math.isclose(initial_x, expected_x, rel_tol=0.0, abs_tol=1.0e-15)
            and math.isclose(initial_alpha, expected_alpha, rel_tol=0.0, abs_tol=1.0e-15)
            and math.isclose(_finite(particle.get("energy_ev"), "native L1 particle energy"), energy, rel_tol=0.0, abs_tol=1.0e-9)
        ):
            raise NativeTransverseL1Error("native L1 particle perturbation differs from its contract state")
        source_position = particle.get("position_project_mm")
        source_direction = particle.get("direction_project")
        if not isinstance(source_position, list) or not isinstance(source_direction, list) or len(source_position) != 3 or len(source_direction) != 3:
            raise NativeTransverseL1Error("native L1 particle source vector is invalid")
        expected_direction = [math.sin(initial_alpha), 0.0, direction * math.cos(initial_alpha)]
        if any(
            not math.isclose(_finite(actual_value, "native L1 source value"), expected_value, rel_tol=0.0, abs_tol=1.0e-15)
            for actual_value, expected_value in zip(source_direction, expected_direction, strict=True)
        ) or [float(value) for value in source_position] != [initial_x, y_mm, 0.0]:
            raise NativeTransverseL1Error("native L1 particle source does not match its perturbation")
        by_id[particle_id] = dict(particle)
        actual.add((direction, str(kind)))
    if actual != expected or set(by_id) != set(range(1, 11)):
        raise NativeTransverseL1Error("native L1 particle set is incomplete or not deterministic")
    return by_id


def write_fly2(contract: Mapping[str, Any], path: Path) -> None:
    """Render the deterministic ten-particle SIMION Fly2 source."""

    particles = validate_native_l1_probe_contract(contract)
    mass = _finite(contract["particle_mass_th"], "native L1 mass")
    charge = _finite(contract["particle_charge_e"], "native L1 charge")
    beams = []
    for particle_id in sorted(particles):
        particle = particles[particle_id]
        x, y, z = (float(value) for value in particle["position_project_mm"])
        dx, dy, dz = (float(value) for value in particle["direction_project"])
        beams.append(
            "  standard_beam {\n"
            f"    n = 1, tob = 0, mass = {mass:.17g}, charge = {charge:.17g},\n"
            f"    ke = {float(particle['energy_ev']):.17g}, cwf = 1, color = {particle_id},\n"
            f"    direction = vector({dx:.17g}, {dy:.17g}, {dz:.17g}),\n"
            "    position = circle_distribution {\n"
            f"      center = vector({x:.17g}, {y:.17g}, {z:.17g}),\n"
            f"      normal = vector({dx:.17g}, {dy:.17g}, {dz:.17g}), radius = 0, fill = true\n"
            "    }\n"
            "  }"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("particles {\n  coordinates = 0,\n" + ",\n".join(beams) + "\n}\n", encoding="utf-8", newline="\n")


def write_lua_source_contract(contract: Mapping[str, Any], path: Path) -> None:
    """Render the immutable Lua lookup table consumed by the native L1 program."""

    particles = validate_native_l1_probe_contract(contract)
    lines = ["return {"]
    for particle_id in sorted(particles):
        particle = particles[particle_id]
        lines.append(
            "  [%d]={direction_z=%d,probe_kind=%s,energy_ev=%.17g},"
            % (
                particle_id,
                particle["direction_z"],
                json.dumps(str(particle["probe_kind"])),
                particle["energy_ev"],
            )
        )
    lines.append("}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _parse_event_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for token in text.split():
        if "=" not in token:
            raise NativeTransverseL1Error("native L1 event has a non-key-value token")
        key, value = token.split("=", 1)
        if not key or not value or key in fields:
            raise NativeTransverseL1Error("native L1 event has an empty or duplicate field")
        fields[key] = value
    return fields


def analyze_native_l1_log(contract: Mapping[str, Any], log_path: Path) -> dict[str, Any]:
    """Parse a completed native L1 cohort and calculate the frozen L1 metrics."""

    particles = validate_native_l1_probe_contract(contract)
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise NativeTransverseL1Error(f"native L1 log is unreadable: {log_path}") from error
    completion = list(_COMPLETED.finditer(text))
    if len(completion) != 1 or int(completion[0].group("splats")) != len(particles):
        raise NativeTransverseL1Error("native L1 SIMION flight did not complete the ten-particle cohort")
    if "MRTOF_NATIVE_L1_TIMEOUT" in text or "MRTOF_NATIVE_L1_TERMINAL" in text:
        raise NativeTransverseL1Error("native L1 log reports a timeout or non-complete terminal particle")
    required = {
        "ion", "phase", "direction_z", "probe_kind", "energy_ev", "time_us", "turns",
        "x_mm", "y_mm", "vx_mm_us", "vy_mm_us", "vz_mm_us",
    }
    events: dict[tuple[int, str], dict[str, Any]] = {}
    for match in _EVENT.finditer(text):
        raw = _parse_event_fields(match.group("fields"))
        if set(raw) != required:
            raise NativeTransverseL1Error("native L1 event fields differ from the canonical schema")
        particle_id = _integer(raw["ion"], "native L1 event ion")
        phase = raw["phase"]
        if particle_id not in particles or phase not in PHASES or (particle_id, phase) in events:
            raise NativeTransverseL1Error("native L1 event identity is unknown or duplicate")
        source = particles[particle_id]
        direction = _integer(raw["direction_z"], "native L1 event direction")
        turns = _integer(raw["turns"], "native L1 event turns")
        if direction != source["direction_z"] or raw["probe_kind"] != source["probe_kind"]:
            raise NativeTransverseL1Error("native L1 event disagrees with frozen particle identity")
        if not math.isclose(_finite(raw["energy_ev"], "native L1 event energy"), float(source["energy_ev"]), rel_tol=0.0, abs_tol=1.0e-9):
            raise NativeTransverseL1Error("native L1 event energy differs from its source")
        values = {
            "time_us": _finite(raw["time_us"], "native L1 event time"),
            "x_mm": _finite(raw["x_mm"], "native L1 event x"),
            "y_mm": _finite(raw["y_mm"], "native L1 event y"),
            "vx_mm_us": _finite(raw["vx_mm_us"], "native L1 event vx"),
            "vy_mm_us": _finite(raw["vy_mm_us"], "native L1 event vy"),
            "vz_mm_us": _finite(raw["vz_mm_us"], "native L1 event vz"),
        }
        if values["time_us"] <= 0.0 or turns != (1 if phase == "first_return" else 2):
            raise NativeTransverseL1Error("native L1 event phase has an invalid time or turn count")
        # The Lua crossing is interpolated across a 0.00002-us SIMION step.
        # At the approximately 40-mm/us longitudinal speed of this frozen
        # probe, 1e-3 mm is the bounded numerical section tolerance; it is
        # deliberately far below the 0.25-mm fixed mirror mesh.
        if not math.isclose(
            values["y_mm"],
            float(contract["probe_y_mm"]),
            rel_tol=0.0,
            abs_tol=_RETURN_Y_TOLERANCE_MM,
        ):
            raise NativeTransverseL1Error("native L1 event left its frozen y slice")
        denominator = -direction * values["vz_mm_us"] if phase == "first_return" else direction * values["vz_mm_us"]
        if denominator <= 0.0:
            raise NativeTransverseL1Error("native L1 event has the wrong longitudinal return direction")
        events[(particle_id, phase)] = {"particle_id": particle_id, "phase": phase, "turns": turns, **values}
    expected_keys = {(particle_id, phase) for particle_id in particles for phase in PHASES}
    if set(events) != expected_keys:
        raise NativeTransverseL1Error("native L1 events do not cover exactly both returns of every particle")

    position_probe = float(contract["position_probe_mm"])
    angle_probe = float(contract["angle_probe_rad"])
    directions: dict[str, Any] = {}
    for direction in (-1, 1):
        states = {
            particles[particle_id]["probe_kind"]: {
                phase: events[(particle_id, phase)] for phase in PHASES
            }
            for particle_id in particles if particles[particle_id]["direction_z"] == direction
        }
        center = states["center"]
        xp, xm = states["x_positive"], states["x_negative"]
        ap, am = states["alpha_positive"], states["alpha_negative"]

        def first_alpha(state: Mapping[str, Mapping[str, Any]]) -> float:
            event = state["first_return"]
            return float(event["vx_mm_us"]) / (-direction * float(event["vz_mm_us"]))

        matrix = [
            [
                (float(xp["first_return"]["x_mm"]) - float(xm["first_return"]["x_mm"])) / (2.0 * position_probe),
                (float(ap["first_return"]["x_mm"]) - float(am["first_return"]["x_mm"])) / (2.0 * angle_probe),
            ],
            [
                (first_alpha(xp) - first_alpha(xm)) / (2.0 * position_probe),
                (first_alpha(ap) - first_alpha(am)) / (2.0 * angle_probe),
            ],
        ]
        determinant = matrix[0][0] * matrix[1][1] - matrix[0][1] * matrix[1][0]
        trace_half = 0.5 * (matrix[0][0] + matrix[1][1])
        stable = abs(trace_half) < 1.0
        gamma = math.degrees(math.acos(max(-1.0, min(1.0, trace_half)))) if stable else None
        center_period = float(center["full_return"]["time_us"])
        t_xx = (
            float(xp["full_return"]["time_us"]) + float(xm["full_return"]["time_us"]) - 2.0 * center_period
        ) / (2.0 * position_probe * position_probe)
        t_aa = (
            float(ap["full_return"]["time_us"]) + float(am["full_return"]["time_us"]) - 2.0 * center_period
        ) / (2.0 * angle_probe * angle_probe)
        f_mm = None
        tbar = None
        if gamma is not None:
            sine = math.sin(math.radians(gamma))
            candidate_f = matrix[0][1] / sine if abs(sine) > 1.0e-14 else math.nan
            if math.isfinite(candidate_f) and abs(candidate_f) > 1.0e-14:
                f_mm = candidate_f
                tbar = 0.5 * (t_xx + t_aa / (candidate_f * candidate_f))
        directions[str(direction)] = {
            "matrix": matrix,
            "determinant": determinant,
            "reversibility_difference": matrix[0][0] - matrix[1][1],
            "trace_half": trace_half,
            "stable": stable,
            "stability_margin": 1.0 - abs(trace_half),
            "gamma_degrees": gamma,
            "full_two_mirror_period_us": center_period,
            "T_xx_us_per_mm2": t_xx,
            "T_alphaalpha_us_per_rad2": t_aa,
            "f_mm": f_mm,
            "Tbar_xx_us_per_mm2": tbar,
            "particles": states,
        }
    return {
        "schema_version": 1,
        "role": "mrtof_native_simion_transverse_l1_analysis",
        "status": "native_l1_diagnostic_complete",
        "qualification": "native_simion_bare_mirror_transverse_l1_diagnostic__not_candidate",
        "nominal_energy_ev": float(contract["nominal_energy_ev"]),
        "probe_y_mm": float(contract["probe_y_mm"]),
        "position_probe_mm": position_probe,
        "angle_probe_rad": angle_probe,
        "directions": directions,
    }


def main() -> int:
    """Provide the small file boundary used by the managed SIMION runner."""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--period-probe-contract", required=True, type=Path)
    prepare.add_argument("--position-probe-mm", required=True, type=float)
    prepare.add_argument("--angle-probe-rad", required=True, type=float)
    prepare.add_argument("--contract-output", required=True, type=Path)
    prepare.add_argument("--fly2-output", required=True, type=Path)
    prepare.add_argument("--lua-source-output", required=True, type=Path)
    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--contract", required=True, type=Path)
    analyze.add_argument("--log", required=True, type=Path)
    analyze.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        contract = build_native_l1_probe_contract(
            args.period_probe_contract,
            position_probe_mm=args.position_probe_mm,
            angle_probe_rad=args.angle_probe_rad,
        )
        args.contract_output.parent.mkdir(parents=True, exist_ok=True)
        args.contract_output.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
        write_fly2(contract, args.fly2_output)
        write_lua_source_contract(contract, args.lua_source_output)
        print("MRTOF_NATIVE_L1_PREPARE=PASS PARTICLES=10")
    else:
        contract = _object(args.contract, "native L1 probe contract")
        result = analyze_native_l1_log(contract, args.log)
        result["source_native_l1_probe_contract_sha256"] = file_sha256(args.contract)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print("MRTOF_NATIVE_L1_ANALYZE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
