"""Generate self-contained SIMION text inputs from ``baseline.json``.

MATLAB and PowerShell can read JSON directly. SIMION Workbench files must
remain portable, so their GUI-visible numeric declarations are generated from
the same contract and committed. ``--check`` is the stale-file gate and
``--write`` is called by the formal delivery builder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import RESOLVED_PATH, resolve_contract, serialized


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = PROJECT_ROOT / "config" / "baseline.json"
RESOLVED_LUA_PATH = PROJECT_ROOT / "simion" / "workbench" / "formal" / "oatof_resolved.lua"
PROGRAM_PATH = PROJECT_ROOT / "simion" / "workbench" / "formal" / "oatof_ideal_grounded.lua"
FLY2_PATH = PROJECT_ROOT / "simion" / "workbench" / "formal" / "oatof_ideal_grounded.fly2"
NUMERICS_PATH = PROJECT_ROOT / "config" / "formal_solver_numerics.json"
OPTIMIZATION_ENVELOPE_PATH = PROJECT_ROOT / "config" / "optimization_envelope.json"
AUTHORITY_DOCUMENTS = (
    PROJECT_ROOT / "config" / "experiment_campaign.json",
    PROJECT_ROOT / "config" / "radial_compaction_campaign.json",
)
BEGIN = "-- BEGIN GENERATED BASELINE ADJUSTABLES"
END = "-- END GENERATED BASELINE ADJUSTABLES"


def number(value: float | int | bool) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return repr(float(value))


def validate_resolved_contract(contract: dict) -> dict:
    if contract.get("schema_version") != 1 or contract.get("role") != "oa_tof_resolved_contract_do_not_edit":
        raise ValueError("unsupported oa-TOF resolved contract")
    geometry = contract["geometry_mm"]
    coordinate = contract.get("coordinate_convention", {})
    if coordinate.get("frame_id") != "oatof_global":
        raise ValueError("oa-TOF resolved coordinate frame must be oatof_global")
    accelerator = contract["geometry_derivation"]["accelerator"]
    checks = {
        "accelerator grid1": (
            geometry["accelerator_grid1_z"],
            geometry["accelerator_repeller_z"] + accelerator["d1_mm"],
        ),
        "accelerator grid2": (
            geometry["accelerator_grid2_z"],
            geometry["accelerator_grid1_z"] + accelerator["d2_mm"],
        ),
        "focus plane": (
            geometry["accelerator_focus_z"],
            geometry["accelerator_grid2_z"]
            + accelerator["focus_drift_after_grid2_mm"],
        ),
        "reflectron length": (
            geometry["L_reflectron"],
            geometry["L_stage1"] + geometry["L_stage2"],
        ),
    }
    source = contract["particle_source"]
    if source["center_z_rule"] == "accelerator_repeller_z + accelerator_stage1_length_mm/2":
        expected_source_z = geometry["accelerator_repeller_z"] + accelerator["d1_mm"] / 2
        theory = accelerator.get("finite_interval_theory")
        if theory is not None and not math.isclose(
            source["center_z_mm"], expected_source_z, rel_tol=0.0, abs_tol=1e-10
        ):
            finite_interval_source_z = (
                theory["canonical_repeller_z_mm"] + theory["source_center_mm"]
            )
            if math.isclose(
                source["center_z_mm"], finite_interval_source_z,
                rel_tol=0.0, abs_tol=1e-10,
            ):
                expected_source_z = finite_interval_source_z
    elif source["center_z_rule"] == (
        "geometry_derivation.accelerator.finite_interval_theory."
        "canonical_repeller_z_mm + source_center_mm"
    ):
        theory = accelerator["finite_interval_theory"]
        expected_source_z = theory["canonical_repeller_z_mm"] + theory["source_center_mm"]
    else:
        raise ValueError(f"unsupported source center rule: {source['center_z_rule']}")
    checks["source center z"] = (source["center_z_mm"], expected_source_z)
    for label, (actual, expected) in checks.items():
        if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-10):
            raise ValueError(f"inconsistent {label}: {actual} != {expected}")
    return contract


def load_contract(contract_path: Path | None = None) -> dict:
    if contract_path is None:
        return validate_resolved_contract(resolve_contract())
    return validate_resolved_contract(json.loads(contract_path.read_text(encoding="utf-8")))


def lua_value(value: object, indent: int = 0) -> str:
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    spacing = " " * indent
    child = " " * (indent + 2)
    if isinstance(value, list):
        return "{\n" + ",\n".join(child + lua_value(item, indent + 2) for item in value) + "\n" + spacing + "}"
    if isinstance(value, dict):
        items = []
        for key, item in value.items():
            lua_key = key if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) else f"[{json.dumps(key)}]"
            items.append(f"{child}{lua_key}={lua_value(item, indent + 2)}")
        return "{\n" + ",\n".join(items) + "\n" + spacing + "}"
    raise TypeError(type(value))


def render_resolved_lua(contract: dict) -> str:
    return "-- Generated from config/resolved_geometry.json; do not edit.\nreturn " + lua_value(contract) + "\n"


def generated_adjustables(contract: dict) -> str:
    geometry = contract["geometry_mm"]
    accelerator = contract["geometry_derivation"]["accelerator"]
    coordinate = contract["coordinate_convention"]
    voltage = contract["electrodes_V"]
    runtime = contract["simion_runtime"]
    marker = contract["simion_detector_marker"]
    rings = contract["rings"]
    instance_z = (
        geometry["accelerator_repeller_z"]
        - geometry["accelerator_repeller_thickness"]
        - geometry["accelerator_rear_clearance"]
        - geometry["accelerator_shield_wall"]
    )
    values = [
        ("V_repeller", voltage["repeller"]),
        ("V_grid1", voltage["grid1"]),
        ("V_mid", voltage["midgrid"]),
        ("V_backplate", voltage["backplate"]),
        ("accelerator_fast_adjust_enable", 1),
        ("ideal_accel_enable", 0),
        ("ideal_refl_stage1_enable", 0),
        ("ideal_refl_stage2_enable", 0),
        ("ideal_accel_ez_enable", 0),
        ("ideal_drift_ez_enable", 0),
        ("ideal_refl_stage1_ez_enable", 0),
        ("ideal_refl_stage2_ez_enable", 0),
        ("accelerator_assembly_translation_z_mm", geometry["accelerator_repeller_z"]),
        ("accelerator_stage1_length_mm", accelerator["d1_mm"]),
        ("accelerator_stage2_length_mm", accelerator["d2_mm"]),
        ("accelerator_ring_count", rings["accelerator_count"]),
        ("accelerator_repeller_front_z_mm", geometry["accelerator_repeller_z"]),
        ("accelerator_grid1_z_mm", geometry["accelerator_grid1_z"]),
        ("accelerator_grid2_z_mm", geometry["accelerator_grid2_z"]),
        ("accelerator_focus_drift_mm", accelerator["focus_drift_after_grid2_mm"]),
        ("reflectron_entgrid_z_mm", geometry["L_flight"]),
        ("field_free_one_way_length_mm", geometry["L_flight"] - geometry["detector_z"]),
        ("reflectron_stage1_length_mm", geometry["L_stage1"]),
        ("reflectron_stage2_length_mm", geometry["L_stage2"]),
        ("reflectron_stage1_ring_count", rings["stage1_count"]),
        ("reflectron_stage2_ring_count", rings["stage2_count"]),
        ("reflectron_midgrid_z_mm", geometry["L_flight"] + geometry["L_stage1"]),
        ("reflectron_backplate_z_mm", geometry["L_flight"] + geometry["L_reflectron"]),
        ("reflectron_axis_x_mm", coordinate["reflectron_axis"][0]),
        ("reflectron_axis_y_mm", coordinate["reflectron_axis"][1]),
        ("reflectron_grid_radius_mm", geometry["ring_outer_r"]),
        ("accelerator_axis_x_mm", coordinate["accelerator_axis_x"]),
        ("accelerator_axis_y_mm", 0),
        ("accelerator_bore_half_mm", geometry["accelerator_bore_half"]),
        ("accelerator_ring_width_mm", geometry["accelerator_ring_width"]),
        ("accelerator_insulation_gap_mm", geometry["accelerator_insulation_gap"]),
        ("accelerator_shield_wall_mm", geometry["accelerator_shield_wall"]),
        ("accelerator_rear_insulation_gap_mm", geometry["accelerator_rear_clearance"]),
        ("accelerator_repeller_thickness_mm", geometry["accelerator_repeller_thickness"]),
        ("flight_tube_inner_radius_mm", geometry["flight_tube_r"]),
        ("flight_tube_shield_wall_mm", geometry["flight_tube_wall"]),
        ("flight_tube_near_endcap_gap_mm", geometry["shield_near_endcap_gap"]),
        ("flight_tube_far_endcap_gap_mm", geometry["shield_axial_gap"]),
        ("flight_tube_endcap_thickness_mm", geometry["shield_endcap_thickness"]),
        ("reflectron_backplate_thickness_mm", geometry["ring_thickness"]),
        ("detector_mirror_offset_x_mm", 0),
        ("detector_mirror_offset_y_mm", 0),
        ("detector_active_plane_z_mm", marker["active_plane_z_mm"]),
        ("detector_radius_mm", marker["active_radius_mm"]),
        ("detector_marker_absorber_thickness_mm", marker["absorber_thickness_mm"]),
        ("detector_marker_front_margin_z_mm", marker["front_margin_z_mm"]),
        ("detector_marker_back_margin_z_mm", marker["back_margin_z_mm"]),
        ("detector_tstep_enable", int(marker["crossing_step_control_enabled"])),
        ("detector_capture_arm_distance_mm", marker["capture_arm_distance_mm"]),
        ("detector_capture_depth_mm", marker["capture_depth_mm"]),
        ("diagnostic_return_plane_z_mm", geometry["detector_z"] + 20.5),
        ("diagnostic_max_tof_us", 90),
        ("trajectory_quality", runtime["trajectory_quality"]),
        ("trajectory_log_enable", int(runtime["trajectory_log_default_enabled"])),
        ("trajectory_log_stride", 1000),
        ("accelerator_instance_z_mm", instance_z),
    ]
    lines = [BEGIN, "-- Generated by analysis/sync_geometry_contract.py; do not edit this block."]
    lines.extend(f"adjustable {name}={number(value)}" for name, value in values)
    lines.append(END)
    return "\n".join(lines)


def render_program(contract: dict) -> str:
    source = PROGRAM_PATH.read_text(encoding="utf-8")
    block = generated_adjustables(contract)
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(source):
        raise ValueError(f"generated markers are missing from {PROGRAM_PATH}")
    return pattern.sub(block, source, count=1)


def _replace_unique_sha(
    source: str,
    key: str,
    old_sha: str,
    new_sha: str,
    label: str,
    path: Path,
) -> str:
    marker = f'"{key}": "{old_sha}"'
    if source.count(marker) != 1:
        raise ValueError(f"{label} SHA marker is not unique in {path}")
    return source.replace(marker, f'"{key}": "{new_sha}"', 1)


def render_optimization_envelope() -> str:
    source = OPTIMIZATION_ENVELOPE_PATH.read_text(encoding="utf-8")
    document = json.loads(source)
    reference = document["reference"]
    if reference.get("baseline") != "config/baseline.json":
        raise ValueError("unexpected baseline reference in optimization envelope")
    baseline_sha = hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest().upper()
    return _replace_unique_sha(
        source,
        "baseline_sha256",
        reference["baseline_sha256"],
        baseline_sha,
        "baseline reference",
        OPTIMIZATION_ENVELOPE_PATH,
    )


def render_authority_document(path: Path, optimization_envelope: str) -> str:
    source = path.read_text(encoding="utf-8")
    document = json.loads(source)
    bindings = {
        "baseline": ("config/baseline.json", CONTRACT_PATH.read_bytes()),
        "solver_numerics": (
            "config/formal_solver_numerics.json",
            NUMERICS_PATH.read_bytes(),
        ),
        "optimization_envelope": (
            "config/optimization_envelope.json",
            optimization_envelope.encode("utf-8"),
        ),
    }
    for label, (expected_path, content) in bindings.items():
        authority = document["authorities"].get(label)
        if authority is None:
            continue
        if authority.get("path") != expected_path:
            raise ValueError(f"unexpected {label} authority path in {path}")
        source = _replace_unique_sha(
            source,
            "sha256",
            authority["sha256"],
            hashlib.sha256(content).hexdigest().upper(),
            f"{label} authority",
            path,
        )
    return source


def frozen_fly2_seed(path: Path = FLY2_PATH) -> int:
    """Read the one run-instance seed already frozen in a generated Fly2 source."""

    matches = re.findall(r"(?m)^seed\((-?\d+)\)\s*$", path.read_text(encoding="utf-8"))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one frozen integer seed in {path}")
    return int(matches[0])


def render_fly2(contract: dict, *, particle_source_seed: int) -> str:
    if type(particle_source_seed) is not int:
        raise ValueError("Fly2 rendering requires an explicit integer particle source seed")
    source = contract["particle_source"]
    target = contract["validation_target"]
    runtime = contract["simion_runtime"]
    center_z = source["center_z_mm"]
    bounds = {
        axis: (source[f"center_{axis}_mm"] - source[f"size_{axis}_mm"] / 2,
               source[f"center_{axis}_mm"] + source[f"size_{axis}_mm"] / 2)
        for axis in "xy"
    }
    bounds["z"] = (center_z - source["size_z_mm"] / 2, center_z + source["size_z_mm"] / 2)
    return f"""-- Generated by analysis/sync_geometry_contract.py from config/baseline.json.
-- The seed is a preserved run-instance binding; do not move it into the physical contract.
seed({particle_source_seed})

local function positive_gaussian_energy()
  local energy
  repeat
    local u1 = math.max(rand(), 1e-15)
    local u2 = rand()
    local normal = math.sqrt(-2*math.log(u1))*math.cos(2*math.pi*u2)
    energy = {number(target['initial_energy_mean_ev'])} + {number(target['initial_energy_sigma_ev'])}*normal
  until energy > 0
  return energy
end

particles {{
  coordinates = 0,
  standard_beam {{
    n = {int(runtime['routine_particles'])},
    tob = 0,
    mass = {number(target['mass_amu'])},
    charge = 1,
    x = uniform_distribution {{ min = {number(bounds['x'][0])}, max = {number(bounds['x'][1])} }},
    y = uniform_distribution {{ min = {number(bounds['y'][0])}, max = {number(bounds['y'][1])} }},
    z = uniform_distribution {{ min = {number(bounds['z'][0])}, max = {number(bounds['z'][1])} }},
    ke = distribution(positive_gaussian_energy),
    cwf = 1,
    color = 1,
    direction = vector({number(source['direction_x'])}, {number(source['direction_y'])}, {number(source['direction_z'])})
  }}
}}
"""


def update(path: Path, expected: str, write: bool) -> bool:
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if current == expected:
        return False
    if write:
        path.write_text(expected, encoding="utf-8", newline="\n")
        return True
    raise SystemExit(f"STALE={path.relative_to(PROJECT_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()
    contract = load_contract()
    source_seed = frozen_fly2_seed()
    optimization_envelope = render_optimization_envelope()
    changed = [
        path
        for path, content in (
            (RESOLVED_PATH, serialized(contract)),
            (RESOLVED_LUA_PATH, render_resolved_lua(contract)),
            (PROGRAM_PATH, render_program(contract)),
            (FLY2_PATH, render_fly2(contract, particle_source_seed=source_seed)),
            (OPTIMIZATION_ENVELOPE_PATH, optimization_envelope),
            *(
                (path, render_authority_document(path, optimization_envelope))
                for path in AUTHORITY_DOCUMENTS
            ),
        )
        if update(path, content, args.write)
    ]
    print("GEOMETRY_TEXT_SYNC=PASS")
    for path in changed:
        print(f"UPDATED={path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
