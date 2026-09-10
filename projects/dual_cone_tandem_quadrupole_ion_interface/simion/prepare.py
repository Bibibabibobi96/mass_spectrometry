"""Prepare immutable SIMION inputs and fail closed on missing gas-field evidence."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.simion.particle_source import render_standard_beams, render_source_states
from projects.dual_cone_tandem_quadrupole_ion_interface.simion.geometry import (
    DEFAULT_NUMERICS,
    DEFAULT_RESOLVED,
    render_gem,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
SCIENCE = PROJECT_ROOT / "config" / "ion_transport_science.json"
GAS_INTERFACE = PROJECT_ROOT / "config" / "gas_field_interface.json"
RF_KERNEL = REPO_ROOT / "common" / "multipole" / "simion_rf_drive.lua"
PROGRAM = PROJECT_ROOT / "simion" / "programs" / "gas_assisted_transport.lua"
SDS_FILES = ("collision_sds.lua", "mbmr.dat", "textfilelib.lua", "arraylib.lua", "m_defs.dat")
SHA256 = re.compile(r"^[0-9A-Fa-f]{64}$")


def _load(path: Path, role: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("role") != role:
        raise ValueError(f"unexpected contract role: {path}")
    return value


def validate_gas_field_manifest(path: Path, interface: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    manifest = _load(path, interface["runtime_artifact_contract"]["manifest_role"])
    required = set(interface["runtime_artifact_contract"]["required_manifest_keys"])
    if set(manifest) != required:
        raise ValueError("gas-field manifest keys differ from the governed interface")
    if manifest["schema_version"] != 1 or manifest["project_id"] != interface["project_id"]:
        raise ValueError("gas-field manifest identity differs")
    if manifest["coordinate_frame"] != interface["runtime_artifact_contract"]["coordinate_frame"]:
        raise ValueError("gas-field coordinate frame differs")
    if manifest["domain"] != interface["runtime_artifact_contract"]["domain"]:
        raise ValueError("gas-field domain does not cover the governed transport domain exactly")
    record = manifest["runtime_lua"]
    if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
        raise ValueError("gas-field runtime_lua record differs")
    runtime = Path(record["path"]).resolve()
    expected = str(record["sha256"])
    if not runtime.is_file() or not SHA256.fullmatch(expected):
        raise ValueError("gas-field runtime Lua is missing or has an invalid SHA-256")
    if file_sha256(runtime).upper() != expected.upper():
        raise ValueError("gas-field runtime Lua SHA-256 differs")
    source = runtime.read_text(encoding="utf-8")
    for name in interface["runtime_artifact_contract"]["runtime_lua_required_functions"]:
        if not re.search(rf"\b{name}\s*=\s*function\b|\bfunction\s+[^\n]*\b{name}\b", source):
            raise ValueError(f"gas-field runtime Lua omits required function {name}")
    return manifest, runtime


def freeze_file(source: Path, destination: Path) -> dict[str, Any]:
    source = source.resolve(strict=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if file_sha256(source) != file_sha256(destination):
        raise ValueError(f"frozen input hash differs: {source}")
    return {
        "source_path": str(source),
        "frozen_path": str(destination.resolve()),
        "sha256": file_sha256(destination),
        "bytes": destination.stat().st_size,
    }


def _lua_string(value: str | Path) -> str:
    return "[[" + str(value).replace("]]", "] ]") + "]]"


def _render_run_config(
    *, mode: str, science: dict[str, Any], numerics: dict[str, Any], solver: Path
) -> str:
    def stage_record(name: str) -> str:
        stage = science["electric_field"][name]
        ids = stage["electrode_group_ids"]
        return (
            "{waveform=" + _lua_string(stage["waveform"])
            + f",frequency_hz={stage['frequency_hz']:.15g},phase_rad={stage['phase_rad']:.15g}"
            + f",rf_amplitude_v={stage['rf_amplitude_v_zero_to_peak_per_group']:.15g}"
            + f",dc_amplitude_v={stage['dc_amplitude_v_per_group']:.15g}"
            + f",common_mode_v={stage['common_mode_offset_v']:.15g}"
            + f",electrode_1={int(ids['1'])},electrode_2={int(ids['2'])}}}"
        )

    trajectory = numerics["trajectory"]
    gas = science["gas"]
    collision_lua = solver / "collision_sds" / "collision_sds.lua"
    gas_lua = solver / "gas_field_runtime.lua"
    results = solver.parents[1] / "results"
    return "\n".join([
        "return {",
        f"  mode={_lua_string(mode)},",
        f"  rf_drive_kernel={_lua_string(solver / 'simion_rf_drive.lua')},",
        f"  collision_sds_lua={_lua_string(collision_lua)},",
        f"  gas_field_lua={_lua_string(gas_lua)},",
        f"  trajectory_csv={_lua_string(results / 'trajectory_samples.csv')},",
        f"  final_state_csv={_lua_string(results / 'particle_final_state.csv')},",
        "  trajectory_sample_interval_us=1,",
        f"  stage_1={stage_record('stage_1')},",
        f"  stage_2={stage_record('stage_2')},",
        f"  first_cone_v={science['electric_field']['static_electrodes_v']['first_cone']:.15g},",
        f"  second_cone_v={science['electric_field']['static_electrodes_v']['second_cone']:.15g},",
        f"  rf_steps_per_period={int(trajectory['rf_steps_per_period'])},",
        f"  maximum_time_us={trajectory['maximum_time_us']:.15g},",
        # Stop one half PA cell before the 108 mm physical end so SDS does not
        # evaluate the gas field beyond its declared domain on the terminal step.
        f"  downstream_workbench_z_mm={109.75:.15g},",
        f"  device_x_offset_mm={25.5:.15g},device_y_offset_mm={25.5:.15g},device_z_offset_mm={2.0:.15g},",
        f"  random_seed={int(trajectory['random_seed'])},",
        f"  collision_gas_mass_amu={gas['collision_gas_mass_amu']:.15g},",
        f"  collision_gas_diameter_nm={gas['collision_gas_diameter_nm']:.15g},",
        f"  diffusion_enabled={1 if gas['diffusion_enabled'] else 0},",
        "}",
        "",
    ])


def prepare(
    output_dir: Path,
    *,
    mode: str,
    collision_sds_dir: Path | None = None,
    gas_field_manifest: Path | None = None,
    simion_exe: Path | None = None,
) -> dict[str, Any]:
    if mode not in {"c0_gem_smoke", "gas_assisted_transport"}:
        raise ValueError("unsupported SIMION preparation mode")
    resolved = _load(DEFAULT_RESOLVED, "dual_cone_tandem_quadrupole_resolved_geometry")
    numerics = _load(DEFAULT_NUMERICS, "dual_cone_simion_solver_numerics")
    science = _load(SCIENCE, "dual_cone_simion_ion_transport_science")
    interface = _load(GAS_INTERFACE, "dual_cone_simion_gas_field_interface")
    if science.get("trajectory_authority") != "simion":
        raise ValueError("SIMION must remain the trajectory authority")

    validated_gas: tuple[dict[str, Any], Path] | None = None
    validated_sds_root: Path | None = None
    if mode == "gas_assisted_transport":
        if gas_field_manifest is None:
            raise ValueError("gas-assisted preparation requires --gas-field-manifest")
        if collision_sds_dir is None:
            raise ValueError("gas-assisted preparation requires --collision-sds-dir")
        validated_gas = validate_gas_field_manifest(gas_field_manifest, interface)
        validated_sds_root = collision_sds_dir.resolve(strict=True)
        missing_sds = [name for name in SDS_FILES if not (validated_sds_root / name).is_file()]
        if missing_sds:
            raise ValueError("SIMION official collision_sds closure is incomplete: " + ", ".join(missing_sds))

    output_dir = output_dir.resolve()
    frozen = output_dir / "input"
    solver = output_dir / "solver" / "simion"
    frozen.mkdir(parents=True, exist_ok=True)
    solver.mkdir(parents=True, exist_ok=True)
    (output_dir / "results").mkdir(parents=True, exist_ok=True)
    gem = solver / "dual_cone_tandem.gem"
    gem.write_text(render_gem(resolved, numerics), encoding="utf-8")
    inputs: dict[str, Any] = {
        "resolved_geometry": freeze_file(DEFAULT_RESOLVED, frozen / "resolved_geometry.json"),
        "simion_solver_numerics": freeze_file(DEFAULT_NUMERICS, frozen / "simion_solver_numerics.json"),
        "ion_transport_science": freeze_file(SCIENCE, frozen / "ion_transport_science.json"),
        "gas_field_interface": freeze_file(GAS_INTERFACE, frozen / "gas_field_interface.json"),
        "rf_drive_kernel": freeze_file(RF_KERNEL, solver / "simion_rf_drive.lua"),
        "simion_program": freeze_file(PROGRAM, solver / "gas_assisted_transport.lua"),
        "gem": {"path": str(gem), "sha256": file_sha256(gem)},
    }

    source = science["ion"]
    center, z_source = 25.5, 1.0
    fly2 = solver / "c0_smoke.fly2"
    fly2.write_text(
        render_standard_beams([{
            "tob": 0.0, "mass": source["mass_amu"], "charge": source["charge_state"],
            "x": center, "y": center, "z": z_source,
            "ke": source["source_kinetic_energy_ev"], "az": 0.0, "el": 0.0,
            "cwf": 1.0, "color": 1,
        }]),
        encoding="utf-8",
    )
    states = solver / "source_states.lua"
    states.write_text(render_source_states([{
        "particle_id": 1, "t": 0.0, "x": center, "y": center, "z": z_source,
        "vx": 0.0, "vy": 0.0, "vz": 0.0, "ke": source["source_kinetic_energy_ev"],
    }]), encoding="utf-8")
    inputs["particle_fly2"] = {"path": str(fly2), "sha256": file_sha256(fly2)}
    inputs["source_states"] = {"path": str(states), "sha256": file_sha256(states)}

    if mode == "gas_assisted_transport":
        assert validated_gas is not None and validated_sds_root is not None
        assert gas_field_manifest is not None
        manifest, runtime = validated_gas
        inputs["gas_field_manifest"] = freeze_file(gas_field_manifest, frozen / "gas_field_manifest.json")
        inputs["gas_field_runtime"] = freeze_file(runtime, solver / "gas_field_runtime.lua")
        inputs["simion_official_collision_sds"] = {
            name: freeze_file(validated_sds_root / name, solver / "collision_sds" / name)
            for name in SDS_FILES
        }
        inputs["gas_field_manifest_identity"] = manifest

    run_config = solver / "run_config.lua"
    run_config.write_text(
        _render_run_config(mode=mode, science=science, numerics=numerics, solver=solver),
        encoding="utf-8",
    )
    inputs["simion_run_config"] = {"path": str(run_config), "sha256": file_sha256(run_config)}
    if simion_exe is not None:
        executable = simion_exe.resolve(strict=True)
        identity = {
            "geometry": {"resolved_geometry_sha256": inputs["resolved_geometry"]["sha256"]},
            "gem": {"sha256": inputs["gem"]["sha256"]},
            "basis_namespace": "dual_cone_tandem",
            "mesh": numerics["pa"]["cell_mm_xyz"],
            "grid_phase": {"workbench_origin_mm": [25.5, 25.5, 2.0]},
            "surface": numerics["pa"]["surface_enhancement"],
            "simion_identity": {"executable_sha256": file_sha256(executable)},
            "refine_policy": numerics["pa"]["refine_policy"],
            "builder_identity": {"geometry_compiler_sha256": file_sha256(Path(__file__).with_name("geometry.py"))},
        }
        identity_path = frozen / "pa_cache_identity.json"
        identity_path.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
        inputs["pa_cache_identity"] = {"path": str(identity_path), "sha256": file_sha256(identity_path)}

    receipt = {
        "schema_version": 1,
        "role": "dual_cone_simion_preparation_receipt",
        "project_id": science["project_id"],
        "mode": mode,
        "trajectory_authority": "simion",
        "collision_model": "none" if mode == "c0_gem_smoke" else "simion_official_collision_sds",
        "qualified_evidence": False,
        "inputs": inputs,
    }
    receipt_path = output_dir / "preparation_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("c0_gem_smoke", "gas_assisted_transport"))
    parser.add_argument("--collision-sds-dir", type=Path)
    parser.add_argument("--gas-field-manifest", type=Path)
    parser.add_argument("--simion-exe", type=Path)
    args = parser.parse_args()
    receipt = prepare(
        args.output_dir,
        mode=args.mode,
        collision_sds_dir=args.collision_sds_dir,
        gas_field_manifest=args.gas_field_manifest,
        simion_exe=args.simion_exe,
    )
    print(f"DUAL_CONE_SIMION_PREPARE=PASS MODE={receipt['mode']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
