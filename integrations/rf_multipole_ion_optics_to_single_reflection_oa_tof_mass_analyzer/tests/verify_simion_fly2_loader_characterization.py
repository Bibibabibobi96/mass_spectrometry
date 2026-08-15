"""Compare two official SIMION-2020 FLY2 particle representations.

This fixed, long-term selection characterization covers the frozen staged-grid2
N=34 source.  It compares documented direct ``velocity=vector`` against the
documented ``ke`` plus ``direction=vector`` fields, using SIMION's own
``speed_to_ke`` conversion in the latter FLY2 expression.  Both arms observe
the first ``segment.initialize`` checkpoint and splat immediately; neither arm
writes particle velocity or advances a trajectory.  A PASS does not authorize
a production representation or tolerance.
"""

from __future__ import annotations

import csv
import hashlib
import inspect
import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from common.contracts.particle_physics import kinetic_energy_ev
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_source import (
    render_restart_fly2 as production_render_restart_fly2,
)
REPO = Path(__file__).resolve().parents[3]
WORKSPACE = REPO.parent
SIMION = Path(r"C:\Program Files\SIMION-2020\simion.exe")
OFFICIAL_EXAMPLE = Path(r"C:\Program Files\SIMION-2020\examples\einzel")
CANONICAL_SOURCE = (
    WORKSPACE
    / "artifacts/projects/rf_octupole_ion_optics/runs"
    / "20260804_094500__sim__cross__oct-simion-grid2-common-oatof__n34"
    / "inputs/canonical_simion_local_accelerator_exit.csv"
)
RECEIPT = (
    REPO
    / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
    / "config/diagnostics/staged_grid2_n34_simion_fly2_loader_ab_characterization.json"
)
AUTHORIZATION_RECEIPT = RECEIPT.with_name(
    "staged_grid2_n34_simion_fly2_loader_authorization_budget.json"
)
OFFICIAL_DIRECTION_EXAMPLE = (
    Path(r"C:\Program Files\SIMION-2020\examples\child_particles\child.fly2")
)
OFFICIAL_ZERO_EXAMPLE = (
    Path(r"C:\Program Files\SIMION-2020\examples\surface_enhancement\quad.fly2")
)
OFFICIAL_SPEED_TO_KE_EXAMPLE = (
    Path(r"C:\Program Files\SIMION-2020\courses\short\session10\random.lua")
)
EXPECTED_SOURCE_SHA256 = (
    "66F88F513F8FA20AB55C35A15A41CC9DA7E8FC62FAB19781BA7E1CEAD6350019"
)
PRODUCTION_RENDERER = (
    REPO
    / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
    / "runtime/single_flight_source.py"
)
MASS_AMU = 100.0
CHARGE_STATE = 1
NEAR_AXIS_EPSILON = 1e-6

PROGRAM = """simion.workbench_program()
simion.early_access(8.2)
sim_segment_global = 1

function segment.initialize()
  print(string.format(
    'LOADER_CHECKPOINT case=%d mass_amu=%.17g charge_state=%.17g x_mm=%.17g y_mm=%.17g z_mm=%.17g vx_mm_per_us=%.17g vy_mm_per_us=%.17g vz_mm_per_us=%.17g native_ion_ke_eV=%.17g',
    ion_number, ion_mass, ion_charge, ion_px_mm, ion_py_mm, ion_pz_mm,
    ion_vx_mm, ion_vy_mm, ion_vz_mm, ion_ke))
  ion_splat = 1
end
"""

CHECKPOINT = re.compile(
    r"LOADER_CHECKPOINT case=(?P<case>\d+) mass_amu=(?P<mass>[-+0-9.eE]+) "
    r"charge_state=(?P<charge>[-+0-9.eE]+) x_mm=(?P<x>[-+0-9.eE]+) "
    r"y_mm=(?P<y>[-+0-9.eE]+) z_mm=(?P<z>[-+0-9.eE]+) "
    r"vx_mm_per_us=(?P<vx>[-+0-9.eE]+) "
    r"vy_mm_per_us=(?P<vy>[-+0-9.eE]+) "
    r"vz_mm_per_us=(?P<vz>[-+0-9.eE]+) "
    r"native_ion_ke_eV=(?P<native_ke>[-+0-9.eE]+)"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest().upper()


def _unit(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    norm = math.sqrt(sum(value * value for value in vector))
    return tuple(value / norm for value in vector)


def _directions() -> list[tuple[float, float, float]]:
    directions = {
        _unit((float(x), float(y), float(z)))
        for x in (-1, 0, 1)
        for y in (-1, 0, 1)
        for z in (-1, 0, 1)
        if (x, y, z) != (0, 0, 0)
    }
    directions.update(
        _unit(vector)
        for vector in (
            (NEAR_AXIS_EPSILON, 0.0, 1.0),
            (-NEAR_AXIS_EPSILON, 0.0, 1.0),
            (0.0, NEAR_AXIS_EPSILON, 1.0),
            (0.0, -NEAR_AXIS_EPSILON, 1.0),
            (NEAR_AXIS_EPSILON, NEAR_AXIS_EPSILON, 1.0),
            (-NEAR_AXIS_EPSILON, -NEAR_AXIS_EPSILON, 1.0),
        )
    )
    return sorted(directions)


def _load_source() -> list[dict[str, str]]:
    if _sha256(CANONICAL_SOURCE) != EXPECTED_SOURCE_SHA256:
        raise ValueError("frozen N34 canonical source SHA256 differs")
    with CANONICAL_SOURCE.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 34:
        raise ValueError("frozen canonical source is not N34")
    if {float(row["mass_amu"]) for row in rows} != {MASS_AMU}:
        raise ValueError("frozen canonical source mass differs")
    if {int(row["charge_state"]) for row in rows} != {CHARGE_STATE}:
        raise ValueError("frozen canonical source charge differs")
    return rows


def _state(case_id: str, velocity: tuple[float, float, float]) -> dict[str, object]:
    return {
        "case_id": case_id,
        "mass_amu": MASS_AMU,
        "charge_state": CHARGE_STATE,
        "position_mm": [3.0, 0.0, 0.0],
        "velocity_m_per_s": list(velocity),
    }


def _case_tables(
    source_rows: list[dict[str, str]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    speeds = [
        math.sqrt(sum(float(row[f"velocity_{axis}_m_s"]) ** 2 for axis in "xyz"))
        for row in source_rows
    ]
    minimum, maximum = min(speeds), max(speeds)
    speed_nodes = [minimum + (maximum - minimum) * index / 8 for index in range(9)]
    threshold = [_state("threshold_zero", (0.0, 0.0, 0.0))]
    for speed_index, speed in enumerate(speed_nodes):
        for direction_index, direction in enumerate(_directions()):
            threshold.append(
                _state(
                    f"threshold_s{speed_index:02d}_d{direction_index:02d}",
                    tuple(speed * value for value in direction),
                )
            )
    witness = [
        _state(
            f"witness_particle_{int(row['particle_id'])}",
            tuple(float(row[f"velocity_{axis}_m_s"]) for axis in "xyz"),
        )
        for row in source_rows
    ]
    if len(threshold) != 289 or len(witness) != 34:
        raise AssertionError("characterization case count differs")
    return threshold, witness


def _direct_velocity_fly2(cases: list[dict[str, object]]) -> str:
    lines = ["particles {", "  coordinates = 0,"]
    for case in cases:
        velocity = case["velocity_m_per_s"]
        position = ", ".join(format(value, ".17g") for value in case["position_mm"])
        velocity_text = ", ".join(
            format(value / 1000.0, ".17g") for value in velocity
        )
        lines.append(
            "  standard_beam { tob = 0, mass = 100, charge = 1, cwf = 1, "
            "color = 0, position = vector(" + position + "), velocity = vector("
            + velocity_text + ") },"
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def _official_ke_direction_fly2(cases: list[dict[str, object]]) -> str:
    lines = ["particles {", "  coordinates = 0,"]
    for case in cases:
        velocity = case["velocity_m_per_s"]
        speed = math.sqrt(sum(value * value for value in velocity))
        direction = [0.0, 1.0, 0.0] if speed == 0 else [
            value / speed for value in velocity
        ]
        position = ", ".join(format(value, ".17g") for value in case["position_mm"])
        direction_text = ", ".join(format(value, ".17g") for value in direction)
        lines.append(
            "  standard_beam { tob = 0, mass = 100, charge = 1, cwf = 1, "
            "color = 0, position = vector(" + position + "), ke = "
            + "speed_to_ke(" + format(speed / 1000.0, ".17g") + ", 100)"
            + ", direction = vector("
            + direction_text + ") },"
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def _production_direct_velocity_fly2(cases: list[dict[str, object]]) -> str:
    rows = []
    for index, case in enumerate(cases, start=1):
        velocity = case["velocity_m_per_s"]
        rows.append(
            {
                "particle_id": str(index),
                "instrument_time_us": "0",
                "mass_amu": format(MASS_AMU, ".17g"),
                "charge_state": str(CHARGE_STATE),
                **{
                    f"position_{axis}_mm": format(value, ".17g")
                    for axis, value in zip("xyz", case["position_mm"])
                },
                **{
                    f"velocity_{axis}_m_s": format(value, ".17g")
                    for axis, value in zip("xyz", velocity)
                },
                "kinetic_energy_eV": format(
                    kinetic_energy_ev(MASS_AMU, *velocity), ".17g"
                ),
            }
        )
    return production_render_restart_fly2(rows)


def _run_once(
    directory: Path, cases: list[dict[str, object]], representation: str,
) -> list[dict[str, float]]:
    particle_path = directory / f"loader_cases__{representation}.fly2"
    render = {
        "direct_velocity_vector_diagnostic": _direct_velocity_fly2,
        "official_ke_direction_vector": _official_ke_direction_fly2,
        "production_direct_velocity_vector": _production_direct_velocity_fly2,
    }[representation]
    particle_path.write_text(render(cases), encoding="utf-8", newline="\n")
    result = subprocess.run(
        [
            str(SIMION),
            "--default-num-particles", str(max(100, len(cases))),
            "--nogui", "--noprompt", "fly",
            "--retain-trajectories", "0",
            "--particles", str(particle_path),
            "--programs", "1",
            str(directory / "einzel.iob"),
        ],
        cwd=directory,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr + result.stdout)
    matches = list(CHECKPOINT.finditer(result.stdout))
    if [int(match["case"]) for match in matches] != list(range(1, len(cases) + 1)):
        raise ValueError("SIMION loader checkpoint coverage/order differs")
    return [
        {
            "mass_amu": float(match["mass"]),
            "charge_state": float(match["charge"]),
            "position_x_mm": float(match["x"]),
            "position_y_mm": float(match["y"]),
            "position_z_mm": float(match["z"]),
            "velocity_x_m_per_s": 1000.0 * float(match["vx"]),
            "velocity_y_m_per_s": 1000.0 * float(match["vy"]),
            "velocity_z_m_per_s": 1000.0 * float(match["vz"]),
            "native_ion_ke_eV": float(match["native_ke"]),
        }
        for match in matches
    ]


def _observations(
    cases: list[dict[str, object]], actual: list[dict[str, float]],
) -> list[dict[str, object]]:
    result = []
    for case, observed in zip(cases, actual):
        expected_v = case["velocity_m_per_s"]
        actual_v = [observed[f"velocity_{axis}_m_per_s"] for axis in "xyz"]
        speed = math.sqrt(sum(value * value for value in expected_v))
        component_errors = [abs(a - b) for a, b in zip(actual_v, expected_v)]
        expected_energy = kinetic_energy_ev(MASS_AMU, *expected_v)
        actual_energy = kinetic_energy_ev(MASS_AMU, *actual_v)
        actual_speed = math.sqrt(sum(value * value for value in actual_v))
        direction_angle = None
        if speed > 0 and actual_speed > 0:
            cross = (
                actual_v[1] * expected_v[2] - actual_v[2] * expected_v[1],
                actual_v[2] * expected_v[0] - actual_v[0] * expected_v[2],
                actual_v[0] * expected_v[1] - actual_v[1] * expected_v[0],
            )
            cross_norm = math.sqrt(sum(value * value for value in cross))
            dot = sum(a * b for a, b in zip(actual_v, expected_v))
            direction_angle = math.atan2(cross_norm, dot)
        result.append(
            {
                "case_id": case["case_id"],
                "expected_velocity_m_per_s": expected_v,
                "actual_velocity_m_per_s": actual_v,
                "expected_speed_m_per_s": speed,
                "actual_speed_m_per_s": actual_speed,
                "speed_abs_error_m_per_s": abs(actual_speed - speed),
                "nonzero_direction_angle_error_rad": direction_angle,
                "maximum_component_abs_error_m_per_s": max(component_errors),
                "maximum_component_relative_to_speed": (
                    max(component_errors) / speed if speed else 0.0
                ),
                "expected_derived_energy_eV": expected_energy,
                "actual_derived_energy_eV": actual_energy,
                "derived_energy_abs_error_eV": abs(actual_energy - expected_energy),
                "derived_energy_relative_error": (
                    abs(actual_energy - expected_energy) / expected_energy
                    if expected_energy else 0.0
                ),
                "native_ion_ke_eV_diagnostic_only": observed["native_ion_ke_eV"],
            }
        )
    return result


def _raw_envelope(observations: list[dict[str, object]]) -> dict[str, float]:
    angles = [
        float(row["nonzero_direction_angle_error_rad"])
        for row in observations
        if row["nonzero_direction_angle_error_rad"] is not None
    ]
    return {
        "maximum_component_abs_error_m_per_s": max(
            float(row["maximum_component_abs_error_m_per_s"]) for row in observations
        ),
        "maximum_component_relative_to_speed": max(
            float(row["maximum_component_relative_to_speed"]) for row in observations
        ),
        "maximum_speed_abs_error_m_per_s": max(
            float(row["speed_abs_error_m_per_s"]) for row in observations
        ),
        "maximum_nonzero_direction_angle_error_rad": max(angles),
        "maximum_derived_energy_abs_error_eV": max(
            float(row["derived_energy_abs_error_eV"]) for row in observations
        ),
        "maximum_derived_energy_relative_error": max(
            float(row["derived_energy_relative_error"]) for row in observations
        ),
    }


def _selection_not_worse(
    candidate: dict[str, float], comparator: dict[str, float],
) -> bool:
    return all(
        candidate[key] <= comparator[key]
        for key in (
            "maximum_component_abs_error_m_per_s",
            "maximum_component_relative_to_speed",
            "maximum_derived_energy_abs_error_eV",
            "maximum_derived_energy_relative_error",
        )
    )


def _ceil_one_significant_digit(value: float) -> float:
    if value == 0:
        return 0.0
    exponent = math.floor(math.log10(abs(value)))
    scale = 10.0**exponent
    rounded = math.ceil(value / scale) * scale
    return float(format(rounded, ".0e"))


def main() -> int:
    for required in (
        SIMION, OFFICIAL_EXAMPLE / "einzel.iob", OFFICIAL_DIRECTION_EXAMPLE,
        OFFICIAL_ZERO_EXAMPLE, OFFICIAL_SPEED_TO_KE_EXAMPLE,
        CANONICAL_SOURCE,
    ):
        if not required.is_file():
            raise FileNotFoundError(required)
    source_rows = _load_source()
    threshold_cases, witness_cases = _case_tables(source_rows)
    cases = threshold_cases + witness_cases
    direct_fly2 = _direct_velocity_fly2(cases)
    official_fly2 = _official_ke_direction_fly2(cases)
    production_fly2 = _production_direct_velocity_fly2(cases)
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary) / "einzel"
        shutil.copytree(OFFICIAL_EXAMPLE, directory)
        (directory / "einzel.lua").write_text(PROGRAM, encoding="utf-8", newline="\n")
        syntax_probe = _run_once(
            directory, [threshold_cases[0], threshold_cases[1]],
            "official_ke_direction_vector",
        )
        if any(
            syntax_probe[0][f"velocity_{axis}_m_per_s"] != 0.0 for axis in "xyz"
        ):
            raise ValueError("official zero-KE direction probe did not load zero velocity")
        direct_first = _run_once(
            directory, cases, "direct_velocity_vector_diagnostic"
        )
        direct_second = _run_once(
            directory, cases, "direct_velocity_vector_diagnostic"
        )
        official_first = _run_once(
            directory, cases, "official_ke_direction_vector"
        )
        official_second = _run_once(
            directory, cases, "official_ke_direction_vector"
        )
        production_first = _run_once(
            directory, cases, "production_direct_velocity_vector"
        )
        production_second = _run_once(
            directory, cases, "production_direct_velocity_vector"
        )
    if (
        direct_first != direct_second
        or official_first != official_second
        or production_first != production_second
    ):
        raise ValueError("SIMION loader checkpoint values are not repeatable")
    direct = _observations(cases, direct_first)
    official = _observations(cases, official_first)
    direct_threshold = direct[: len(threshold_cases)]
    official_threshold = official[: len(threshold_cases)]
    direct_witnesses = direct[len(threshold_cases) :]
    official_witnesses = official[len(threshold_cases) :]
    production = _observations(cases, production_first)
    production_threshold = production[: len(threshold_cases)]
    production_witnesses = production[len(threshold_cases) :]
    direct_envelope = _raw_envelope(direct_threshold)
    official_envelope = _raw_envelope(official_threshold)
    direct_witness_envelope = _raw_envelope(direct_witnesses)
    official_witness_envelope = _raw_envelope(official_witnesses)
    official_not_worse = (
        _selection_not_worse(official_envelope, direct_envelope)
        and _selection_not_worse(
            official_witness_envelope, direct_witness_envelope
        )
    )
    receipt = {
        "schema_version": 1,
        "role": "rf_oatof_simion_fly2_loader_representation_ab_characterization",
        "status": "PASS",
        "claim_scope": {
            "canonical_source_sha256": EXPECTED_SOURCE_SHA256,
            "mass_amu": MASS_AMU,
            "charge_state": CHARGE_STATE,
            "future_sources_or_renderers_authorized": False,
            "continuous_velocity_domain_authorized": False,
        },
        "official_method": {
            "vendor": "Scientific Instrument Services",
            "product": "SIMION-2020",
            "fly2_individual_particles_url": "https://simion.com/info/fly2_file.html#individual-particles",
            "workbench_ion_ke_url": "https://simion.com/info/workbench_program_extensions.html",
            "installed_direction_example_relative_path": "examples/child_particles/child.fly2",
            "installed_zero_ke_example_relative_path": "examples/surface_enhancement/quad.fly2",
            "installed_speed_to_ke_example_relative_path": "courses/short/session10/random.lua",
            "ke_conversion_expression": "speed_to_ke(speed_mm_per_us, mass_amu)",
            "ke_conversion_fly2_availability": "verified_by_same-run_syntax_probe",
            "installed_example_relative_path": "examples/einzel/einzel.iob",
            "checkpoint": "first segment.initialize",
            "field_propagation_steps": 0,
            "velocity_write_performed": False,
            "native_ion_ke_role": "diagnostic_only",
        },
        "identities": {
            "simion_executable_sha256": _sha256(SIMION),
            "direct_comparator_renderer": "harness_local_frozen_function",
            "direct_comparator_renderer_sha256": hashlib.sha256(
                inspect.getsource(_direct_velocity_fly2).encode()
            ).hexdigest().upper(),
            "direct_comparator_generated_fly2_sha256": hashlib.sha256(
                direct_fly2.encode()
            ).hexdigest().upper(),
            "candidate_renderer_sha256": hashlib.sha256(
                inspect.getsource(_official_ke_direction_fly2).encode()
            ).hexdigest().upper(),
            "candidate_generated_fly2_sha256": hashlib.sha256(
                official_fly2.encode()
            ).hexdigest().upper(),
            "program_sha256": hashlib.sha256(PROGRAM.encode()).hexdigest().upper(),
            "harness_path": Path(__file__).resolve().relative_to(REPO).as_posix(),
            "harness_sha256": _sha256(Path(__file__).resolve()),
            "official_example_iob_sha256": _sha256(OFFICIAL_EXAMPLE / "einzel.iob"),
            "official_direction_example_sha256": _sha256(OFFICIAL_DIRECTION_EXAMPLE),
            "official_zero_ke_example_sha256": _sha256(OFFICIAL_ZERO_EXAMPLE),
            "official_speed_to_ke_example_sha256": _sha256(
                OFFICIAL_SPEED_TO_KE_EXAMPLE
            ),
            "canonical_source_path": CANONICAL_SOURCE.relative_to(WORKSPACE).as_posix(),
            "canonical_source_sha256": EXPECTED_SOURCE_SHA256,
        },
        "case_tables": {
            "threshold_case_count": len(threshold_cases),
            "threshold_cases_sha256": _canonical_json_sha256(threshold_cases),
            "threshold_selection": "zero plus 9 inclusive source-speed-bound nodes by 32 predeclared directions",
            "exact_vector_witness_count": len(witness_cases),
            "exact_vector_witnesses_sha256": _canonical_json_sha256(witness_cases),
            "exact_vectors_participate_in_threshold_selection": False,
        },
        "ab_result": {
            "official_direct_velocity_vector": {
                "role": "current_production_comparator",
                "synthetic_raw_error_envelope": direct_envelope,
                "n34_witness_raw_error_envelope": direct_witness_envelope,
                "zero_speed_observation": direct_threshold[0],
            },
            "official_ke_direction_vector": {
                "role": "candidate_selected_only_if_gate_passes",
                "synthetic_raw_error_envelope": official_envelope,
                "n34_witness_raw_error_envelope": official_witness_envelope,
                "zero_speed_direction": [0.0, 1.0, 0.0],
                "zero_speed_observation": official_threshold[0],
                "error_envelopes_not_worse_than_direct_velocity": official_not_worse,
                "candidate_can_be_authorized": official_not_worse,
                "production_authorized": False,
            },
            "position_clock_and_identity_contract": "unchanged_existing_strict_contract",
            "production_tolerance_or_authorization_published": False,
        },
        "repeatability": {
            "official_syntax_and_zero_probe_passed": True,
            "independent_cli_runs_per_representation": 2,
            "direct_checkpoint_values_exact": True,
            "official_checkpoint_values_exact": True,
        },
        "diagnostic_direct_velocity_threshold_observations": direct_threshold,
        "official_ke_direction_threshold_observations": official_threshold,
        "diagnostic_direct_velocity_exact_vector_witnesses": direct_witnesses,
        "official_ke_direction_exact_vector_pass_witnesses": official_witnesses,
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    production_envelope = _raw_envelope(production_threshold)
    velocity_raw_relative = production_envelope[
        "maximum_component_relative_to_speed"
    ]
    energy_raw_relative = production_envelope[
        "maximum_derived_energy_relative_error"
    ]
    velocity_authorized_relative = _ceil_one_significant_digit(
        4.0 * velocity_raw_relative
    )
    energy_authorized_relative = _ceil_one_significant_digit(
        4.0 * energy_raw_relative
    )
    zero = production_threshold[0]
    zero_exact = (
        zero["maximum_component_abs_error_m_per_s"] == 0
        and zero["derived_energy_abs_error_eV"] == 0
    )
    witness_velocity_pass = all(
        row["maximum_component_abs_error_m_per_s"]
        <= velocity_authorized_relative * row["expected_speed_m_per_s"]
        for row in production_witnesses
    )
    witness_energy_pass = all(
        row["derived_energy_abs_error_eV"]
        <= energy_authorized_relative * row["expected_derived_energy_eV"]
        for row in production_witnesses
    )
    if (
        velocity_authorized_relative != 2e-8
        or energy_authorized_relative != 3e-8
        or not zero_exact
        or not witness_velocity_pass
        or not witness_energy_pass
    ):
        raise ValueError(
            "production loader authorization budget gate differs: "
            + json.dumps(
                {
                    "velocity_authorized_relative": velocity_authorized_relative,
                    "energy_authorized_relative": energy_authorized_relative,
                    "zero_exact": zero_exact,
                    "witness_velocity_pass": witness_velocity_pass,
                    "witness_energy_pass": witness_energy_pass,
                },
                sort_keys=True,
            )
        )
    authorization_receipt = {
        "schema_version": 1,
        "role": "rf_oatof_simion_fly2_loader_authorization_budget",
        "status": "PASS",
        "contract_integration_status": "NOT_INTEGRATED_PENDING_REVIEW",
        "claim_scope": {
            "representation": "standard_beam_direct_velocity_vector",
            "canonical_source_sha256": EXPECTED_SOURCE_SHA256,
            "mass_amu": MASS_AMU,
            "charge_state": CHARGE_STATE,
            "future_sources_or_renderers_authorized": False,
            "continuous_velocity_domain_authorized": False,
        },
        "identities": {
            "selection_receipt_path": RECEIPT.relative_to(REPO).as_posix(),
            "selection_receipt_sha256": _sha256(RECEIPT),
            "simion_executable_sha256": _sha256(SIMION),
            "program_sha256": hashlib.sha256(PROGRAM.encode()).hexdigest().upper(),
            "harness_path": Path(__file__).resolve().relative_to(REPO).as_posix(),
            "harness_sha256": _sha256(Path(__file__).resolve()),
            "production_renderer_path": PRODUCTION_RENDERER.relative_to(REPO).as_posix(),
            "production_renderer_sha256": _sha256(PRODUCTION_RENDERER),
            "production_generated_fly2_sha256": hashlib.sha256(
                production_fly2.encode()
            ).hexdigest().upper(),
            "canonical_source_path": CANONICAL_SOURCE.relative_to(WORKSPACE).as_posix(),
            "canonical_source_sha256": EXPECTED_SOURCE_SHA256,
        },
        "derivation_population": {
            "synthetic_case_count": len(threshold_cases),
            "synthetic_cases_sha256": _canonical_json_sha256(threshold_cases),
            "independent_cli_runs": 2,
            "checkpoint_values_exact_between_runs": True,
            "n34_exact_vector_witness_count": len(witness_cases),
            "n34_witnesses_participate_in_budget_derivation": False,
        },
        "authorized_budget": {
            "velocity": {
                "formula": "component_abs_error <= relative_bound * expected_speed",
                "raw_relative_envelope": velocity_raw_relative,
                "absolute_floor_m_per_s": 0.0,
                "zero_speed_must_be_exact": True,
                "safety_factor": 4.0,
                "pre_round_relative_bound": 4.0 * velocity_raw_relative,
                "rounding_rule": "ceil_outward_to_one_significant_digit",
                "authorized_relative_bound": velocity_authorized_relative,
            },
            "derived_energy": {
                "authority": "actual_velocity_plus_canonical_mass_common_function",
                "formula": "energy_abs_error <= relative_bound * expected_energy",
                "raw_relative_envelope": energy_raw_relative,
                "absolute_floor_eV": 0.0,
                "zero_energy_must_be_exact": True,
                "safety_factor": 4.0,
                "pre_round_relative_bound": 4.0 * energy_raw_relative,
                "rounding_rule": "ceil_outward_to_one_significant_digit",
                "authorized_relative_bound": energy_authorized_relative,
            },
            "native_ion_ke": "diagnostic_only",
            "position_clock_id_row_map": "unchanged_existing_strict_contract",
        },
        "n34_exact_vector_witness_gate": {
            "velocity_all_pass": witness_velocity_pass,
            "energy_all_pass": witness_energy_pass,
            "raw_error_envelope": _raw_envelope(production_witnesses),
        },
        "production_threshold_observations": production_threshold,
        "production_n34_exact_vector_witnesses": production_witnesses,
    }
    AUTHORIZATION_RECEIPT.write_text(
        json.dumps(authorization_receipt, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "SIMION_FLY2_LOADER_CHARACTERIZATION=PASS "
        f"THRESHOLD={len(threshold_cases)} WITNESS={len(witness_cases)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
