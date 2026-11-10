"""Prepare immutable SIMION inputs and fail closed on missing gas-field evidence."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path
from typing import Any

from msplatform.io.file_identity import file_sha256
from msplatform.execution.inputs import freeze_file
from msplatform.contracts.particle_physics import kinetic_energy_ev
from msplatform.ion_release.release import materialize_release_from_file
from msplatform.backends.simion.source import render_standard_beams, render_source_states, lua_value, transform_source_rows
from msplatform.backends.simion import dual_cone_geometry
from msplatform.backends.simion.dual_cone_geometry import (
    device_to_workbench_offsets,
    render_gem,
)


SDS_FILES = ("collision_sds.lua", "mbmr.dat", "textfilelib.lua", "arraylib.lua", "m_defs.dat")
SHA256 = re.compile(r"^[0-9A-Fa-f]{64}$")


def _load(path: Path, role: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("role") != role:
        raise ValueError(f"unexpected contract role: {path}")
    return value


def validate_runtime_manifest(path: Path, interface: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    manifest = _load(path, interface["runtime_artifact_contract"]["manifest_role"])
    required = set(interface["runtime_artifact_contract"]["required_manifest_keys"])
    if set(manifest) != required:
        raise ValueError("gas-field manifest keys differ from the governed interface")
    if manifest["schema_version"] != 1 or manifest["project_id"] != interface["project_id"]:
        raise ValueError("gas-field manifest identity differs")
    source_record = manifest["source"]
    if not isinstance(source_record, dict):
        raise ValueError("gas-field source record must be an object")
    source_kind = source_record.get("kind")
    if source_kind not in interface["runtime_artifact_contract"]["allowed_source_kinds"]:
        raise ValueError("gas-field source kind is not governed")
    if source_kind == "validated_comsol_axisymmetric_rz":
        expected_source_keys = {"kind", "field_csv", "metadata", "source_contract_sha256"}
        if set(source_record) != expected_source_keys:
            raise ValueError("COMSOL gas-field source record differs")
        for role in ("field_csv", "metadata"):
            source_file = source_record[role]
            if not isinstance(source_file, dict) or set(source_file) != {"path", "sha256"}:
                raise ValueError(f"COMSOL gas-field {role} identity differs")
            source_path = Path(source_file["path"]).resolve()
            if not source_path.is_file() or not SHA256.fullmatch(str(source_file["sha256"])):
                raise ValueError(f"COMSOL gas-field {role} is missing or has invalid identity")
            if file_sha256(source_path).upper() != str(source_file["sha256"]).upper():
                raise ValueError(f"COMSOL gas-field {role} SHA-256 differs")
        hashes = source_record["source_contract_sha256"]
        if (
            not isinstance(hashes, dict)
            or set(hashes)
            != {
                "gas_flow_science",
                "comsol_solver_numerics",
                "resolved_geometry",
            }
            or any(not SHA256.fullmatch(str(value)) for value in hashes.values())
        ):
            raise ValueError("COMSOL gas-field source-contract identities differ")
    else:
        if set(source_record) != {"kind", "spec_sha256", "interface_sha256"} or any(
            not SHA256.fullmatch(str(source_record[key])) for key in ("spec_sha256", "interface_sha256")
        ):
            raise ValueError("uniform gas-field source identities differ")
    if manifest["coordinate_frame"] != interface["runtime_artifact_contract"]["coordinate_frame"]:
        raise ValueError("gas-field coordinate frame differs")
    if manifest["domain"] != interface["runtime_artifact_contract"]["domain"]:
        raise ValueError("gas-field domain does not cover the governed transport domain exactly")
    if manifest["interpolation_policy"] != interface["runtime_artifact_contract"]["interpolation_policy"]:
        raise ValueError("gas-field interpolation policy differs from the governed interface")
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


def _lua_string(value: str | Path) -> str:
    return "[[" + str(value).replace("]]", "] ]") + "]]"


def _render_run_config(
    *,
    mode: str,
    science: dict[str, Any],
    numerics: dict[str, Any],
    resolved: dict[str, Any],
    solver: Path,
    model_projection=None,
    placement=None,
) -> str:
    def stage_record(name: str) -> str:
        stage = science["electric_field"][name]
        ids = stage["electrode_group_ids"]
        return (
            "{waveform="
            + _lua_string(stage["waveform"])
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
    plate = resolved["geometry_mm"]["downstream_aperture_plate"]
    pa_cell_z = float(numerics["pa"]["cell_mm_xyz"]["z"])
    terminal_device_z = float(plate["downstream_observation_end_z_mm"]) - 0.5 * pa_cell_z
    from .dual_cone_geometry import geometry_grid
    grid = geometry_grid(resolved, numerics)
    offset_x, offset_y, offset_z = device_to_workbench_offsets(numerics)
    if not 0 <= terminal_device_z + offset_z <= (grid["nz"] - 1) * grid["dz_mm"]:
        raise ValueError("observation plane lies outside the explicit PA grid")
    terminal_workbench_z = terminal_device_z + offset_z
    return "\n".join(
        [
            "return {",
            *(
                []
                if model_projection is None
                else [
                    f"  model_configuration={_lua_string(solver / 'model_drive_configuration.lua')},",
                    f"  model_consumer={_lua_string(solver / 'model_drive.lua')},",
                    f"  pulse_hook={_lua_string(solver / 'single_flight_pulse_hook.lua')},",
                    f"  waveforms={_lua_string(solver / 'voltage_waveforms.lua')},",
                ]
            ),
            *([] if placement is None else [
                "  device_placement=" + lua_value(placement) + ",",
                "  native_instance_index=1,",
                f"  pa_dx_mm={numerics['pa']['cell_mm_xyz']['x']:.17g},pa_dy_mm={numerics['pa']['cell_mm_xyz']['y']:.17g},pa_dz_mm={numerics['pa']['cell_mm_xyz']['z']:.17g},",
                f"  downstream_device_z_mm={terminal_device_z:.17g},",
            ]),
            f"  mode={_lua_string(mode)},",
            f"  rf_drive_kernel={_lua_string(solver / 'simion_rf_drive.lua')},",
            f"  collision_sds_lua={_lua_string(collision_lua)},",
            f"  gas_field_lua={_lua_string(gas_lua)},",
            f"  trajectory_csv={_lua_string(results / 'trajectory_samples.csv')},",
            f"  final_state_csv={_lua_string(results / 'particle_final_state.csv')},",
            f"  trajectory_sample_interval_us={trajectory['sample_interval_us']:.15g},",
            f"  stage_1={stage_record('stage_1')},",
            f"  stage_2={stage_record('stage_2')},",
            f"  first_cone_v={science['electric_field']['static_electrodes_v']['first_cone']:.15g},",
            f"  second_cone_v={science['electric_field']['static_electrodes_v']['second_cone']:.15g},",
            f"  downstream_aperture_plate_v={science['electric_field']['static_electrodes_v']['downstream_aperture_plate']:.15g},",
            f"  rf_steps_per_period={int(trajectory['rf_steps_per_period'])},",
            f"  maximum_time_us={trajectory['maximum_time_us']:.15g},"
            f"  maximum_step_us={trajectory['maximum_step_us']:.15g},",
            # Stop one half PA cell before the physical end so SDS does not
            # evaluate the gas field beyond its declared domain on the terminal step.
            f"  downstream_workbench_z_mm={terminal_workbench_z:.15g},",
            f"  device_x_offset_mm={offset_x:.15g},device_y_offset_mm={offset_y:.15g},device_z_offset_mm={offset_z:.15g},",
            f"  random_seed={int(trajectory['random_seed'])},",
            f"  collision_gas_mass_amu={gas['collision_gas_mass_amu']:.15g},",
            f"  collision_gas_diameter_nm={gas['collision_gas_diameter_nm']:.15g},",
            f"  diffusion_enabled={1 if gas['diffusion_enabled'] else 0},",
            "}",
            "",
        ]
    )


def source_placement(resolved, numerics, source_spec, *, placement=None, source_to_device=None):
    """Bind source and device frames with the existing canonical composition.

    Omission of both transforms explicitly retains the historical translation-
    only interpretation. New posed sources either already name the device
    frame or provide their actual source-to-device registration.
    """
    from msplatform.contracts.rigid_transform import RigidTransform
    from .dual_cone_stages import device_placement

    world = device_placement(resolved, numerics, placement)
    if placement is None and source_to_device is None:
        return world, None
    if source_to_device is None:
        if source_spec["frame_id"] != world.from_frame_id:
            raise ValueError("source frame requires an explicit source-to-device rigid transform")
        registration = RigidTransform.identity(world.from_frame_id)
    else:
        registration = (source_to_device if isinstance(source_to_device, RigidTransform)
                        else RigidTransform.from_contract(source_to_device))
        if (registration.from_frame_id != source_spec["frame_id"]
                or registration.to_frame_id != world.from_frame_id):
            raise ValueError("source-to-device rigid transform frame binding differs")
    return registration.then(world), registration


def _materialize_gas_source(
    *,
    frozen: Path,
    solver: Path,
    resolved: dict[str, Any],
    gas_science: dict[str, Any],
    numerics: dict[str, Any],
    source_spec_path: Path,
    placement=None,
    source_to_device=None,
) -> tuple[Path, Path, dict[str, Any]]:
    spec = _load(source_spec_path, "repository_ion_release")
    geometry = spec["geometry"]
    radius = float(geometry["radius_mm"])
    z_max = float(geometry["center_mm"][2]) + 0.5 * float(geometry["height_mm"])
    first_cone = resolved["geometry_mm"]["first_cone"]
    plenum_radius = float(gas_science["geometry_proxy"]["upstream_plenum_radius_mm"])
    world, registration = source_placement(resolved, numerics, spec,
        placement=placement, source_to_device=source_to_device)
    # Keep the historical author-cylinder constraints in their original frame.
    if registration is None or (registration.rotation == ((1.,0.,0.),(0.,1.,0.),(0.,0.,1.))
                                and registration.translation_mm == (0.,0.,0.)):
        if radius > plenum_radius:
            raise ValueError("cylindrical source radius exceeds the upstream plenum")
        if z_max >= float(first_cone["aperture_reference_z_mm"]):
            raise ValueError("cylindrical source must remain upstream of the first cone inside the PA")

    source_csv = frozen / "cylindrical_ion_source.csv"
    source_receipt = frozen / "cylindrical_ion_source_receipt.json"
    receipt = materialize_release_from_file(source_spec_path, source_csv, source_receipt)
    offset_x, offset_y, offset_z = device_to_workbench_offsets(numerics)
    beams: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    with source_csv.open(encoding="utf-8", newline="") as stream:
        source_rows = list(csv.DictReader(stream))
    projected = transform_source_rows(source_rows, world) if registration is not None else None
    local_rows = transform_source_rows(source_rows, registration) if registration is not None else None
    from .dual_cone_geometry import geometry_grid
    grid = geometry_grid(resolved, numerics)
    for index, row in enumerate(source_rows):
        local = [float(local_rows[index]["position_"+axis+"_mm"]) if local_rows is not None else float(row[axis+"_mm"]) for axis in "xyz"]
        if (math.hypot(local[0], local[1]) > plenum_radius
                or local[2] >= float(first_cone["aperture_reference_z_mm"])):
            raise ValueError("projected source is outside the device-local upstream plenum")
        for axis, value, offset in zip("xyz", local, (offset_x, offset_y, offset_z), strict=True):
            if not 0. <= value + offset <= (grid["n"+axis]-1)*grid["d"+axis+"_mm"]:
                raise ValueError("projected source lies outside the PA-local grid")
        vx, vy, vz = (float(row[name]) for name in ("vx_m_s", "vy_m_s", "vz_m_s"))
        mass = float(row["mass_amu"])
        energy = kinetic_energy_ev(mass, vx, vy, vz)
        x = offset_x + float(row["x_mm"])
        y = offset_y + float(row["y_mm"])
        z = offset_z + float(row["z_mm"])
        tob = float(row["birth_time_s"]) * 1e6
        if projected is not None:
            target = projected[index]
            x, y, z = (float(target["position_"+axis+"_mm"]) for axis in "xyz")
            vx, vy, vz = (float(target["velocity_"+axis+"_m_s"]) for axis in "xyz")
            tob = float(target["instrument_time_us"])
            energy = float(target["kinetic_energy_eV"])
        beams.append(
            {
                "tob": format(tob, ".15g"),
                "mass": format(mass, ".15g"),
                "charge": int(row["charge_state"]),
                "x": format(x, ".15g"),
                "y": format(y, ".15g"),
                "z": format(z, ".15g"),
                "direction": tuple(format(value, ".15g") for value in (vx, vy, vz)),
                "ke": format(energy, ".15g"),
                "cwf": 1,
                "color": 3,
            }
        )
        states.append(
            {
                "particle_id": int(row["particle_id"]),
                "t": tob,
                "x": x,
                "y": y,
                "z": z,
                "vx": vx / 1000.0,
                "vy": vy / 1000.0,
                "vz": vz / 1000.0,
                "ke": energy,
            }
        )
    fly2 = solver / "gas_source.fly2"
    states_path = solver / "gas_source_states.lua"
    fly2.write_text(render_standard_beams(beams), encoding="utf-8")
    states_path.write_text(render_source_states(states), encoding="utf-8")
    return fly2, states_path, receipt


def prepare_transport(
    output_dir: Path,
    *,
    mode: str,
    resolved_path: Path,
    numerics_path: Path,
    science_path: Path,
    interface_path: Path,
    gas_science_path: Path,
    source_spec_path: Path,
    gas_field_reference: dict | None = None,
    collision_sds_dir: Path | None = None,
    gas_field_manifest: Path | None = None,
    simion_exe: Path | None = None,
    materialize_geometry: bool = True,
    model_projection=None,
    placement=None,
    source_to_device=None,
) -> dict[str, Any]:
    if type(materialize_geometry) is not bool:
        raise TypeError("materialize_geometry must be boolean")
    if not materialize_geometry and (
        mode != "gas_assisted_transport" or model_projection is None or simion_exe is not None
    ):
        raise ValueError("source-only preparation requires its explicit saved model and no cache builder")
    if model_projection is not None:
        from .dual_cone_stages import require_model_projection

        require_model_projection(model_projection)
    if mode not in {"c0_gem_smoke", "gas_assisted_transport"}:
        raise ValueError("unsupported SIMION preparation mode")
    if mode == "c0_gem_smoke" and source_to_device is not None:
        raise ValueError("source_to_device does not apply to the fixed device-local C0 smoke source")
    resolved = _load(resolved_path, "dual_cone_tandem_quadrupole_resolved_geometry")
    numerics = _load(numerics_path, "dual_cone_simion_solver_numerics")
    science = _load(science_path, "dual_cone_simion_ion_transport_science")
    interface = _load(interface_path, "dual_cone_simion_gas_field_interface")
    gas_science = _load(gas_science_path, "dual_cone_axisymmetric_gas_flow_science_contract")
    if science.get("trajectory_authority") != "simion":
        raise ValueError("SIMION must remain the trajectory authority")
    for name in ("sample_interval_us", "maximum_step_us"):
        value = numerics["trajectory"].get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("SIMION trajectory " + name + " must be explicit, positive and finite")

    from .dual_cone_stages import device_placement
    placement = (model_projection or {}).get("placement") if placement is None else placement
    if placement is not None or source_to_device is not None:
        placement = device_placement(resolved, numerics, placement).to_contract()
        if mode == "gas_assisted_transport":
            source_placement(resolved, numerics, _load(source_spec_path, "repository_ion_release"),
                             placement=placement, source_to_device=source_to_device)
    if mode == "c0_gem_smoke":
        from .dual_cone_geometry import geometry_grid
        grid = geometry_grid(resolved, numerics)
        offsets = device_to_workbench_offsets(numerics)
        for axis, local, offset in zip("xyz", (0., 0., -1.), offsets, strict=True):
            if not 0 <= local + offset <= (grid["n"+axis] - 1) * grid["d"+axis+"_mm"]:
                raise ValueError("C0 source lies outside the explicit PA grid")
    from msplatform.backends.simion.resources import native_resource_path

    program = native_resource_path("dual_cone_gas_assisted_transport.lua")
    rf_kernel = native_resource_path("rf_drive.lua")
    producer = None
    if gas_field_reference is not None:
        if gas_field_manifest is not None:
            raise ValueError("Select one explicit gas field product or runtime manifest")
        from msplatform.results.gas_field import read_gas_field

        from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.gas_field_validation import validate_gas_field_data
        opened_gas = read_gas_field(gas_field_reference)
        validate_gas_field_data(opened_gas.data)
        producer = opened_gas.artifact
        selected = {"geometry": resolved_path, "science": gas_science_path}
        for name, path in selected.items():
            if file_sha256(path).upper() != producer.data_records[name]["sha256"].upper():
                raise ValueError("Gas producer " + name + " differs from selected transport inputs")
    validated_gas: tuple[dict[str, Any], Path] | None = None
    validated_sds_root: Path | None = None
    if mode == "gas_assisted_transport":
        if gas_field_manifest is None and producer is None:
            raise ValueError("gas-assisted preparation requires --gas-field-manifest")
        if collision_sds_dir is None:
            raise ValueError("gas-assisted preparation requires --collision-sds-dir")
        if gas_field_manifest is not None:
            validated_gas = validate_runtime_manifest(gas_field_manifest, interface)
            source = validated_gas[0]["source"]
            if source["kind"] == "validated_comsol_axisymmetric_rz":
                hashes = source["source_contract_sha256"]
                if hashes["resolved_geometry"].upper() != file_sha256(resolved_path).upper():
                    raise ValueError("Gas producer geometry differs from selected transport geometry")
                if hashes["gas_flow_science"].upper() != file_sha256(gas_science_path).upper():
                    raise ValueError("Gas producer science differs from selected transport gas science")
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
    if materialize_geometry:
        gem.write_text(render_gem(resolved, numerics), encoding="utf-8")
    inputs: dict[str, Any] = {
        "resolved_geometry": freeze_file(resolved_path, frozen / "resolved_geometry.json"),
        "simion_solver_numerics": freeze_file(numerics_path, frozen / "simion_solver_numerics.json"),
        "ion_transport_science": freeze_file(science_path, frozen / "ion_transport_science.json"),
        "gas_field_interface": freeze_file(interface_path, frozen / "gas_field_interface.json"),
        "rf_drive_kernel": freeze_file(rf_kernel, solver / "simion_rf_drive.lua"),
        "simion_program": freeze_file(program, solver / "gas_assisted_transport.lua"),
    }

    for name, value in (("placement", placement), ("source_to_device", source_to_device)):
        if value is not None:
            value = value.to_contract() if hasattr(value, "to_contract") else value
            path = frozen / (name + ".json")
            path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            inputs[name] = {"path": str(path), "sha256": file_sha256(path)}
    if materialize_geometry:
        inputs["gem"] = {"path": str(gem), "sha256": file_sha256(gem)}
    if model_projection is not None:
        from .dual_cone_stages import render_model_stage_configuration

        configuration = solver / "model_drive_configuration.lua"
        configuration.write_text(render_model_stage_configuration(model_projection), encoding="utf-8")
        inputs["model_drive_configuration"] = {"path": str(configuration), "sha256": file_sha256(configuration)}
        for name in ("model_drive.lua", "single_flight_pulse_hook.lua", "voltage_waveforms.lua"):
            inputs["model_resource_" + name] = freeze_file(native_resource_path(name), solver / name)
    if mode == "c0_gem_smoke":
        source = science["ion"]
        offset_x, offset_y, offset_z = device_to_workbench_offsets(numerics)
        center_x, center_y, z_source = offset_x, offset_y, offset_z - 1.0
        smoke_direction = None
        if placement is not None:
            from msplatform.contracts.rigid_transform import FramedPosition, FramedVector
            transform = device_placement(resolved, numerics, placement)
            center_x, center_y, z_source = transform.transform_position(FramedPosition(transform.from_frame_id, (0,0,-1))).coordinates_mm
            smoke_direction = transform.transform_vector(FramedVector(transform.from_frame_id, (1,0,0))).components
        fly2 = solver / "c0_smoke.fly2"
        fly2.write_text(
            render_standard_beams(
                [
                    {
                        "tob": 0.0,
                        "mass": source["mass_amu"],
                        "charge": source["charge_state"],
                        "x": center_x,
                        "y": center_y,
                        "z": z_source,
                        "ke": source["source_kinetic_energy_ev"],
                        **({"az": 0.0, "el": 0.0} if smoke_direction is None else {"direction": smoke_direction}),
                        "cwf": 1.0,
                        "color": 1,
                    }
                ]
            ),
            encoding="utf-8",
        )
        states = solver / "source_states.lua"
        states.write_text(
            render_source_states(
                [
                    {
                        "particle_id": 1,
                        "t": 0.0,
                        "x": center_x,
                        "y": center_y,
                        "z": z_source,
                        "vx": 0.0,
                        "vy": 0.0,
                        "vz": 0.0,
                        "ke": source["source_kinetic_energy_ev"],
                    }
                ]
            ),
            encoding="utf-8",
        )
        inputs["particle_fly2"] = {"path": str(fly2), "sha256": file_sha256(fly2)}
        inputs["source_states"] = {"path": str(states), "sha256": file_sha256(states)}

    if mode == "gas_assisted_transport":
        if producer is not None:
            from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.gas_runtime import export_runtime

            paths = producer.data_locations
            gas_field_manifest = frozen / "compiled_gas_field_manifest.json"
            export_runtime(
                paths["field_csv"],
                paths["field_metadata"],
                solver / "compiled_gas_field.lua",
                gas_field_manifest,
                paths["science"],
                paths["numerics"],
                paths["geometry"],
                interface_path,
            )
            validated_gas = validate_runtime_manifest(gas_field_manifest, interface)
            inputs["gas_producer_manifest"] = freeze_file(
                Path(producer.reference["manifest"]["path"]), frozen / "gas_producer_manifest.json"
            )
            for name in ("science", "numerics", "geometry"):
                inputs["gas_producer_" + name] = freeze_file(paths[name], frozen / ("gas_producer_" + name + ".json"))
        assert validated_gas is not None and validated_sds_root is not None
        assert gas_field_manifest is not None
        manifest, runtime = validated_gas
        inputs["gas_field_manifest"] = freeze_file(gas_field_manifest, frozen / "gas_field_manifest.json")
        inputs["gas_field_runtime"] = freeze_file(
            runtime,
            solver / "gas_field_runtime.lua",
            # Embedded gas lookup data is required evidence, not a native solver payload.
            retention_classifier=lambda _path, **_metadata: "required_evidence",
        )
        (solver / "collision_sds").mkdir()
        inputs["simion_official_collision_sds"] = {
            name: freeze_file(validated_sds_root / name, solver / "collision_sds" / name) for name in SDS_FILES
        }
        inputs["gas_field_manifest_identity"] = manifest
        source_fly2, source_states, source_receipt = _materialize_gas_source(
            frozen=frozen,
            solver=solver,
            resolved=resolved,
            gas_science=gas_science,
            numerics=numerics,
            source_spec_path=source_spec_path,
            placement=placement, source_to_device=source_to_device,
        )
        inputs["gas_flow_science"] = freeze_file(gas_science_path, frozen / "gas_flow_science.json")
        inputs["cylindrical_ion_source_spec"] = freeze_file(source_spec_path, frozen / "cylindrical_ion_source.json")
        inputs["cylindrical_ion_source_csv"] = {
            "path": str((frozen / "cylindrical_ion_source.csv").resolve()),
            "sha256": file_sha256(frozen / "cylindrical_ion_source.csv"),
        }
        inputs["cylindrical_ion_source_receipt"] = {
            "path": str((frozen / "cylindrical_ion_source_receipt.json").resolve()),
            "sha256": file_sha256(frozen / "cylindrical_ion_source_receipt.json"),
            "identity": source_receipt,
        }
        inputs["particle_fly2"] = {"path": str(source_fly2), "sha256": file_sha256(source_fly2)}
        inputs["source_states"] = {"path": str(source_states), "sha256": file_sha256(source_states)}

    run_config = solver / "run_config.lua"
    run_config.write_text(
        _render_run_config(
            mode=mode,
            science=science,
            numerics=numerics,
            resolved=resolved,
            solver=solver,
            model_projection=model_projection,
            placement=placement,
        ),
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
            "grid_phase": {"workbench_origin_mm": list(device_to_workbench_offsets(numerics))},
            "surface": numerics["pa"]["surface_enhancement"],
            "simion_identity": {"executable_sha256": file_sha256(executable)},
            "refine_policy": numerics["pa"]["refine_policy"],
            "builder_identity": {"geometry_compiler_sha256": file_sha256(Path(dual_cone_geometry.__file__).resolve())},
        }
        identity_path = frozen / "pa_cache_identity.json"
        identity_path.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
        inputs["pa_cache_identity"] = {"path": str(identity_path), "sha256": file_sha256(identity_path)}

    # The project receipt retains its existing four-field frozen-input shape.
    # Map the shared API record here rather than maintaining a second copier.
    frozen_records = [record for record in inputs.values() if "source_path" in record]
    frozen_records.extend(inputs.get("simion_official_collision_sds", {}).values())
    for record in frozen_records:
        record["frozen_path"] = record.pop("path")
        del record["exists"]

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
    parser.add_argument("--placement", type=Path)
    parser.add_argument("--source-to-device", type=Path)
    for name in ("resolved", "numerics", "science", "interface", "gas-science", "source-spec"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--collision-sds-dir", type=Path)
    parser.add_argument("--gas-field-manifest", type=Path)
    parser.add_argument("--gas-field-reference", type=Path)
    parser.add_argument("--simion-exe", type=Path)
    args = parser.parse_args()
    reference = (
        None
        if args.gas_field_reference is None
        else json.loads(args.gas_field_reference.read_text(encoding="utf-8-sig"))
    )
    receipt = prepare_transport(
        args.output_dir,
        mode=args.mode,
        resolved_path=args.resolved,
        numerics_path=args.numerics,
        science_path=args.science,
        interface_path=args.interface,
        gas_science_path=args.gas_science,
        source_spec_path=args.source_spec,
        placement=None if args.placement is None else json.loads(args.placement.read_text(encoding="utf-8-sig")),
        source_to_device=None if args.source_to_device is None else json.loads(args.source_to_device.read_text(encoding="utf-8-sig")),
        gas_field_reference=reference,
        collision_sds_dir=args.collision_sds_dir,
        gas_field_manifest=args.gas_field_manifest,
        simion_exe=args.simion_exe,
    )
    print(f"DUAL_CONE_SIMION_PREPARE=PASS MODE={receipt['mode']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
