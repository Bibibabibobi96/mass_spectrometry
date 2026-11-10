"""Dual-cone stage projections and published scientific closure checks.

These are plans/data validators, not completed native stages. The canonical IOB
roles are implemented but native validation remains pending; no function here
fabricates a process or qualification.
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping
from pathlib import Path

from msplatform.io.file_identity import canonical_json_sha256
from msplatform.results.artifacts import OpenedArtifact, open_artifact
from .dual_cone_geometry import device_to_workbench_offsets, geometry_grid, render_gem
from .model import RF_PHYSICS, _validate_timing


ELECTRODE_IDS = (1, 2, 3, 11, 12, 21, 22)


def device_placement(resolved, numerics, placement=None):
    """Resolve one proper device-to-world pose; omission reads legacy translation.

    The numerical offset embeds the local device in its PA grid. It remains
    independent of an explicitly requested world placement.
    """
    from msplatform.contracts.rigid_transform import RigidTransform

    local = resolved["coordinate_frame"]["frame_id"]
    if placement is None:
        return RigidTransform(local, "dual_cone_workbench",
                              ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
                              device_to_workbench_offsets(numerics))
    value = placement if isinstance(placement, RigidTransform) else RigidTransform.from_contract(placement)
    if value.from_frame_id != local:
        raise ValueError("dual-cone placement source frame differs from the resolved device")
    return value


def native_instance_pose(resolved, numerics, placement=None):
    """Compose the already embedded array frame into the requested world frame."""
    from msplatform.contracts.rigid_transform import RigidTransform
    from .native_plans import rigid_iob_placement

    world = device_placement(resolved, numerics, placement)
    embedded = RigidTransform(world.from_frame_id, world.from_frame_id + ".simion_array",
                              ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
                              device_to_workbench_offsets(numerics))
    array_to_world = embedded.inverse().then(world)
    native = rigid_iob_placement(array_to_world.to_contract())
    return array_to_world.to_contract(), {key: value for key, value in native.items() if key not in {"ox", "oy", "oz"}}


def transport_refinement(numerics: Mapping) -> dict:
    """Resolve the selected explicit numerical policy before creating outputs."""
    pa = numerics["pa"]
    policy = pa["refine_policy"]
    if policy == "simion_refine_without_convergence_argument":
        if "convergence_v" in pa:
            raise ValueError("vendor-default refinement cannot carry a convergence override")
        return {"refine_policy": policy}
    if policy == "explicit_convergence":
        value = pa["convergence_v"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("explicit convergence_v must be positive and finite")
        return {"refine_policy": policy, "convergence_v": value}
    raise ValueError("unsupported explicit dual-cone refine_policy")


def _snapshot(value):
    return json.loads(json.dumps(value, allow_nan=False))


def _identity(document):
    value = _snapshot(document)
    return dict(value, identity_sha256=canonical_json_sha256(value))


def _graph(ids):
    return dict(
        expected_operation_ids=ids,
        operation_dependencies={name: [ids[i - 1]] for i, name in enumerate(ids) if i},
        native_status="not_executed",
        canonical_iob_role="implemented_pending_native_validation",
    )


def plan_geometry_stage(*, resolved: Mapping, numerics: Mapping, placement=None) -> dict:
    """Geometry has no gas/SDS/source/trajectory dependency or sampled particle."""
    grid = geometry_grid(dict(resolved), dict(numerics))
    # Retain only the actual geometry authority; unrelated trajectory or Refine
    # choices are not part of the geometry identity or a required input section.
    selected = dict(
        pa={name: copy.deepcopy(numerics["pa"][name]) for name in ("cell_mm_xyz", "grid_points_xyz", "surface_enhancement", "symmetry")},
        workbench=copy.deepcopy(numerics["workbench"]),
        role=numerics["role"],
        schema_version=numerics["schema_version"],
    )
    if selected["pa"]["symmetry"] != "planar_no_mirror" or selected["workbench"]["pa_instance_count"] != 1:
        raise ValueError("this actual dual-cone geometry has one nonmirrored planar PA instance")
    if selected["pa"]["surface_enhancement"] != "fractional":
        raise ValueError("dual-cone geometry requires its actual fractional surface")
    projection = _identity(
        dict(
            schema_version=1,
            role="dual_cone_simion_geometry_projection",
            resolved=_snapshot(resolved),
            numerics=selected,
            grid=grid,
            gem=render_gem(dict(resolved), dict(numerics)),
            electrode_ids=list(ELECTRODE_IDS),
        )
    )
    return dict(
        **({"placement": device_placement(resolved, numerics, placement).to_contract()} if placement is not None else {}),
        projection=projection,
        **_graph(["build_geometry", "build_geometry_model", "verify_geometry_model"]),
        sampled_particles=0,
        refine_calls=0,
        fly_calls=0,
    )


def require_geometry_projection(value: Mapping) -> dict:
    if not isinstance(value, Mapping) or value.get("role") != "dual_cone_simion_geometry_projection":
        raise ValueError("dual-cone geometry projection role differs")
    expected = plan_geometry_stage(resolved=value["resolved"], numerics=value["numerics"])["projection"]
    if dict(value) != expected:
        raise ValueError("dual-cone geometry projection identity differs")
    return expected


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(name + " must be finite")
    return value


def plan_model_stage(geometry: Mapping, *, electric_field: Mapping, clock: Mapping, physics: Mapping, placement=None) -> dict:
    """Project a driven, source-free model, never a gas/particle run config."""
    geometry = require_geometry_projection(geometry)
    if dict(physics) != RF_PHYSICS:
        raise ValueError("dual-cone model requires explicit external linear electrostatic/native boundary physics")
    _validate_timing(dict(clock=clock), requires_pulse=False)
    rows = []
    static = electric_field["static_electrodes_v"]
    if set(static) != {"first_cone", "second_cone", "downstream_aperture_plate"}:
        raise ValueError("dual-cone static electrode bindings differ")
    for eid, name in zip(ELECTRODE_IDS[:3], ("first_cone", "second_cone", "downstream_aperture_plate"), strict=True):
        rows.append(
            dict(
                kind="static",
                instance_id="dual_cone",
                electrode_group_id=name,
                native_targets=[dict(domain="dual_cone", electrode_id=eid)],
                voltage_v=_finite(static[name], name),
            )
        )
    for name, expected in (("stage_1", {"1": 11, "2": 12}), ("stage_2", {"1": 21, "2": 22})):
        stage = electric_field[name]
        if dict(stage["electrode_group_ids"]) != expected:
            raise ValueError("dual-cone physical drive native IDs differ")
        if stage["waveform"] not in {"sine", "cosine"}:
            raise ValueError("unsupported actual RF waveform")
        for key in (
            "frequency_hz",
            "phase_rad",
            "rf_amplitude_v_zero_to_peak_per_group",
            "dc_amplitude_v_per_group",
            "common_mode_offset_v",
        ):
            _finite(stage[key], name + "." + key)
        if stage["frequency_hz"] <= 0 or stage["rf_amplitude_v_zero_to_peak_per_group"] < 0:
            raise ValueError("RF frequency/amplitude outside its physical domain")
        # Map the existing opposed physical groups to the SAME canonical
        # model_drive/rf_drive consumer schema; no waveform algorithm is copied.
        for group, eid in expected.items():
            sign = 1 if group == "1" else -1
            rows.append(
                dict(
                    kind="rf",
                    instance_id="dual_cone",
                    electrode_group_id=name + "_group_" + group,
                    native_targets=[dict(domain="dual_cone", electrode_id=eid)],
                    waveform=stage["waveform"],
                    frequency_hz=stage["frequency_hz"],
                    phase_rad=stage["phase_rad"],
                    rf_amplitude_v=stage["rf_amplitude_v_zero_to_peak_per_group"],
                    dc_v=sign * stage["dc_amplitude_v_per_group"],
                    common_mode_v=stage["common_mode_offset_v"],
                    polarity=sign,
                )
            )
    selected = dict(static_electrodes_v=_snapshot(static))
    for name in ("stage_1", "stage_2"):
        selected[name] = {
            key: copy.deepcopy(electric_field[name][key])
            for key in (
                "waveform",
                "frequency_hz",
                "phase_rad",
                "rf_amplitude_v_zero_to_peak_per_group",
                "dc_amplitude_v_per_group",
                "common_mode_offset_v",
                "electrode_group_ids",
            )
        }
    projection = _identity(
        dict(
            schema_version=1,
            role="dual_cone_prepared_model_projection",
            **({"placement": device_placement(geometry["resolved"], geometry["numerics"], placement).to_contract()} if placement is not None else {}),
            geometry=geometry,
            electric_field=selected,
            native_drive_rows=rows,
            clock=_snapshot(clock),
            physics=_snapshot(physics),
            field_status="not_solved",
            source_status="not_requested",
        )
    )
    return dict(
        projection=projection,
        **_graph(["materialize_geometry", "build_model", "verify_model"]),
        sampled_particles=0,
        refine_calls=0,
        fly_calls=0,
    )


def require_model_projection(value: Mapping) -> dict:
    if (
        not isinstance(value, Mapping)
        or value.get("role") != "dual_cone_prepared_model_projection"
        or value.get("field_status") != "not_solved"
        or value.get("source_status") != "not_requested"
    ):
        raise ValueError("dual-cone prepared model is not a source-free unsolved model")
    expected = plan_model_stage(
        value["geometry"], electric_field=value["electric_field"], clock=value["clock"], physics=value["physics"],
        placement=value.get("placement")
    )["projection"]
    if dict(value) != expected:
        raise ValueError("dual-cone prepared model identity differs")
    return expected


def render_model_stage_configuration(model: Mapping) -> str:
    """Project to the EXISTING source-free model_drive Lua consumer input."""
    from .source import lua_value

    document = require_model_projection(model)
    value = dict(
        schema_version=1,
        role="simion_model_drive",
        model_identity_sha256=document["identity_sha256"],
        clock=document["clock"],
        groups=document["native_drive_rows"],
    )
    return "return " + lua_value(value) + "\n"


def _record_identity(record):
    from msplatform.io.manifest_records import validate_file_record

    value = validate_file_record(record, "dual-cone basis authority")
    if value["exists"] is not True or value["bytes"] <= 0:
        raise ValueError("basis authority must be an existing nonempty record")
    return dict(bytes=value["bytes"], sha256=value["sha256"].upper())


def require_field_numerics(model: Mapping, numerics: Mapping) -> dict:
    """Refine controls cannot silently redefine an already published raw domain."""
    geometry = model["geometry"]["numerics"]
    for name in ("cell_mm_xyz", "grid_points_xyz", "surface_enhancement", "symmetry"):
        if name in numerics["pa"] and numerics["pa"][name] != geometry["pa"][name]:
            raise ValueError("field numerics cannot redefine selected geometry " + name)
    if "workbench" in numerics and numerics["workbench"] != geometry["workbench"]:
        raise ValueError("field numerics cannot redefine selected geometry workbench")
    return transport_refinement(numerics)


def plan_fields_stage(
    model: Mapping, *, numerics: Mapping, raw_records: Mapping, implementation_records: Mapping, reuse_reference=None
) -> dict:
    """Bind only the source-independent spatial operator, not RF/gas/flight."""
    model = require_model_projection(model)
    if set(raw_records) != {"raw_geometry", "fractional_surface", "surface_witnesses"}:
        raise ValueError("field solve requires exact raw/surface/witness records")
    if set(implementation_records) != {"simion", "refiner", "auditor"}:
        raise ValueError("field solve requires actual tool/refiner/auditor identities")
    identity = _identity(
        dict(
            schema_version=1,
            role="dual_cone_fractional_spatial_identity",
            geometry_identity_sha256=model["geometry"]["identity_sha256"],
            electrode_ids=list(ELECTRODE_IDS),
            grid=model["geometry"]["grid"],
            physics=model["physics"],
            raw_geometry={name: _record_identity(row) for name, row in raw_records.items()},
            refinement=require_field_numerics(model, numerics),
            implementation={name: _record_identity(row) for name, row in implementation_records.items()},
        )
    )
    if reuse_reference is not None:
        require_fields_product(reuse_reference, expected_spatial_identity=identity)
    ids = ["audit_fields"] if reuse_reference is not None else ["materialize_geometry", "refine_fields", "audit_fields"]
    return dict(
        spatial_identity=identity,
        **_graph(ids),
        reuse_requested=reuse_reference is not None,
        source_status="not_requested",
        sampled_particles=0,
        fly_calls=0,
    )


def _product(reference, kind, projection_name):
    selected = open_artifact(
        reference.reference if isinstance(reference, OpenedArtifact) else reference, expected_kind=kind
    )
    if selected.metadata.get("backend") != "simion" or selected.metadata.get("domain_id") != "dual_cone":
        raise ValueError("product does not declare actual dual-cone SIMION ownership")
    projection = json.loads(selected.data_path(projection_name).read_text(encoding="utf-8-sig"))
    return selected, projection


def _raw_closure(product):
    locations = product.data_locations
    for name in (
        "raw_geometry",
        "fractional_surface",
        "surface_witnesses",
        "workbench",
        "zero_particle_format_control",
    ):
        if name not in locations:
            raise ValueError("source-free native closure is missing: " + name)
    raw = locations["raw_geometry"]
    if not str(raw).endswith(".pa#") or locations["fractional_surface"] != raw.with_suffix(".pa-surf"):
        raise ValueError("raw geometry has no actual same-stem fractional surface")
    # open_artifact already verified these exact native records. Shape checks
    # use its verified snapshot rather than hashing a large PA repeatedly.
    return {
        name: dict(product.data_records[name], path=str(locations[name]))
        for name in ("raw_geometry", "fractional_surface", "surface_witnesses")
    }


def _closed_receipts(product, key, expected):
    rows = json.loads(product.data_path(key).read_text(encoding="utf-8-sig"))
    if (
        not isinstance(rows, list)
        or len(rows) != len(expected)
        or any(not isinstance(row, dict) for row in rows)
        or {row.get("operation_id") for row in rows} != set(expected)
    ):
        raise ValueError("published native closure lacks its actual stage operations")
    for row in rows:
        observation = row.get("observation", {})
        if (
            observation.get("exit_confirmed") is not True
            or observation.get("returncode") != 0
            or any(
                type(observation.get(name)) is not int or observation[name] <= 0
                for name in ("process_id", "process_started_at_utc_ticks")
            )
        ):
            raise ValueError("published native closure lacks known successful stopped writers")
    return rows


def require_geometry_product(reference):
    product, projection = _product(reference, "geometry_artifact", "compiled_geometry")
    require_geometry_projection(projection)
    if "placement" in product.metadata:
        pose = device_placement(projection["resolved"], projection["numerics"], product.metadata["placement"]).to_contract()
        if json.loads(product.data_path("placement").read_text(encoding="utf-8-sig")) != pose:
            raise ValueError("geometry placement differs from its frozen authority")
    _raw_closure(product)
    _closed_receipts(
        product, "native_stage_receipts", ("build_geometry", "build_geometry_model", "verify_geometry_model")
    )
    if product.metadata.get("sampled_particles") != 0 or product.metadata.get("field_status") != "not_solved":
        raise ValueError("geometry product claims particles or solved fields")
    return product


def _product_clock(product, projection):
    # Reuse the canonical read-only clock-data validator; no owner or machine
    # configuration is loaded. Preserve the contract's original relative path.
    from msplatform.execution.clock_authority import validate_clock_authority
    from msplatform.contracts.clock import ClockIdentity, require_same_clock

    contract_path = product.data_locations["clock_authority"]
    clock_receipt = validate_clock_authority(contract_path, contract_path.parent)
    require_same_clock(
        ClockIdentity(projection["clock"]["clock_epoch_id"], projection["clock"]["authority_sha256"]),
        ClockIdentity(clock_receipt["clock_epoch_id"], clock_receipt["authority_sha256"]),
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    if (contract_path.parent / contract["authority"]["path"]).resolve() != product.data_locations[
        "instrument_epoch"
    ].resolve():
        raise ValueError("prepared model epoch differs from its actual frozen authority")


def require_model_product(reference):
    product, projection = _product(reference, "prepared_model", "compiled_model")
    require_model_projection(projection)
    _raw_closure(product)
    _closed_receipts(product, "native_stage_receipts", ("materialize_geometry", "build_model", "verify_model"))
    for name in ("model_configuration", "model_readback", "clock_authority", "instrument_epoch"):
        product.data_path(name)
    _product_clock(product, projection)
    if (
        product.metadata.get("field_status") != "not_solved"
        or product.metadata.get("source_status") != "not_requested"
        or product.metadata.get("sampled_particles") != 0
    ):
        raise ValueError("prepared model product is not unsolved and source free")
    return product


def require_fields_product(reference, *, expected_spatial_identity=None):
    product, projection = _product(reference, "field_bundle", "compiled_model")
    require_model_projection(projection)
    _product_clock(product, projection)
    metadata = product.metadata
    if (
        metadata.get("field_status") != "available"
        or metadata.get("source_status") != "not_requested"
        or metadata.get("field_representation") != "producer_owned_dual_cone_fractional_family"
    ):
        raise ValueError("field product has no available actual dual-cone fractional basis")
    spatial = metadata.get("spatial_identity")
    if (
        not isinstance(spatial, dict)
        or spatial.get("role") != "dual_cone_fractional_spatial_identity"
        or spatial.get("electrode_ids") != list(ELECTRODE_IDS)
        or spatial.get("grid") != projection["geometry"]["grid"]
        or spatial.get("geometry_identity_sha256") != projection["geometry"]["identity_sha256"]
        or spatial.get("physics") != projection["physics"]
        or _identity({key: value for key, value in spatial.items() if key != "identity_sha256"}) != spatial
    ):
        raise ValueError("saved basis spatial identity is incomplete or inconsistent")
    if expected_spatial_identity is not None and metadata.get("spatial_identity") != expected_spatial_identity:
        raise ValueError("saved basis differs from the selected actual spatial operator")
    producer_reference = metadata.get("family_producer_reference")
    producer = (
        product if producer_reference is None else open_artifact(producer_reference, expected_kind="field_bundle")
    )
    if "family_producer_reference" in producer.metadata:
        raise ValueError("saved basis must reference its original producer, not a reference chain")
    if producer.metadata.get("field_representation") != metadata["field_representation"] or producer.metadata.get(
        "spatial_identity"
    ) != metadata.get("spatial_identity"):
        raise ValueError("saved basis and original producer operator differ")

    def members(selected):
        names = ["family_raw", "family_surface", "family_carrier", "surface_witnesses"]
        names.extend("response_" + str(eid) for eid in ELECTRODE_IDS)
        locations = selected.data_locations
        if any(name not in locations for name in names):
            raise ValueError("saved basis member is missing")
        records = {name: dict(selected.data_records[name], path=str(locations[name])) for name in names}
        carrier = Path(records["family_carrier"]["path"])
        paths = [Path(row["path"]) for name, row in records.items() if name != "surface_witnesses"]
        expected = {
            carrier.with_suffix(suffix)
            for suffix in (".pa#", ".pa-surf", ".pa0", *(".pa" + str(eid) for eid in ELECTRODE_IDS))
        }
        if set(paths) != expected or len(paths) != len(expected):
            raise ValueError("saved basis lacks its exact seven-electrode same-producer family")
        return records

    records = members(product)
    if records != members(producer):
        raise ValueError("saved basis members differ from their original producer")
    for record in records.values():
        if not Path(record["path"]).resolve().is_relative_to(producer.manifest_location.parent):
            raise ValueError("saved field member is not retained at its original producer")
    _closed_receipts(producer, "field_native_receipts", ("refine_fields",))
    _closed_receipts(product, "field_audit_receipts", ("audit_fields",))
    audit = json.loads(product.data_path("field_audit").read_text(encoding="utf-8-sig"))
    if audit.get("status") != "success" or audit.get("checked_domains") != ["dual_cone"]:
        raise ValueError("published field product lacks actual dual-cone readback")

    return product, producer


def plan_saved_fly_inputs(
    model: Mapping,
    *,
    gas_field_reference,
    source_spec: Mapping,
    numerics: Mapping,
    collision_science: Mapping,
    collision_sds_records: Mapping,
    placement=None,
    source_to_device=None,
) -> dict:
    """Validate the same explicit Fly inputs before a future field publication."""
    from msplatform.ion_release.release import validate_release_spec
    from msplatform.results.gas_field import read_gas_field
    from .dual_cone_transport import SDS_FILES

    model = require_model_projection(model)
    from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.gas_field_validation import validate_gas_field_data
    opened_gas = read_gas_field(gas_field_reference)
    validate_gas_field_data(opened_gas.data)
    gas = opened_gas.artifact
    gas_geometry = json.loads(gas.data_path("geometry").read_text(encoding="utf-8-sig"))
    if gas_geometry != model["geometry"]["resolved"]:
        raise ValueError("gas producer geometry differs from selected saved fields")
    if collision_science["collision_model"] != "simion_official_collision_sds":
        raise ValueError("tracking requires explicit official SDS collision science")
    collision = {}
    for name in ("collision_gas_mass_amu", "collision_gas_diameter_nm"):
        value = _finite(collision_science[name], name)
        if value <= 0:
            raise ValueError("collision parameters must be positive")
        collision[name] = value
    if type(collision_science["diffusion_enabled"]) is not bool:
        raise ValueError("collision diffusion_enabled must be boolean")
    collision["diffusion_enabled"] = collision_science["diffusion_enabled"]
    validate_release_spec(source_spec)
    placement = model.get("placement") if placement is None else placement
    if placement is not None or source_to_device is not None:
        from .dual_cone_transport import source_placement
        pose = device_placement(model["geometry"]["resolved"], model["geometry"]["numerics"], placement)
        _, registration = source_placement(model["geometry"]["resolved"], model["geometry"]["numerics"],
            source_spec, placement=pose.to_contract(), source_to_device=source_to_device)
        placement = pose.to_contract()
    if set(collision_sds_records) != set(SDS_FILES):
        raise ValueError("tracking requires the exact official five-file SDS closure")
    for record in collision_sds_records.values():
        _record_identity(record)
    for name in ("maximum_time_us", "maximum_step_us", "sample_interval_us"):
        if _finite(numerics["trajectory"][name], name) <= 0:
            raise ValueError("tracking trajectory limits must be positive")
    return dict(
        **_graph(["build_tracking_model", "verify_tracking_model", "fly"]),
        **({"placement": placement} if placement is not None else {}),
        **({"source_to_device": registration.to_contract()} if source_to_device is not None else {}),
        gas_field_reference=gas.reference,
        source_count=source_spec["particle_count"],
        collision=collision,
        refine_calls=0,
        geometry_build_calls=0,
        field_recomputed=False,
        source_status="explicit_preparation_required",
        protection_status="owner_acquisition_required",
    )


def plan_saved_field_fly(
    *,
    fields_reference,
    gas_field_reference,
    source_spec: Mapping,
    numerics: Mapping,
    collision_science: Mapping,
    collision_sds_records: Mapping,
    placement=None,
    source_to_device=None,
) -> dict:
    """Saved-field tracking graph has no materialize/build-geometry/Refine path."""
    fields, producer = require_fields_product(fields_reference)
    model = json.loads(fields.data_path("compiled_model").read_text(encoding="utf-8-sig"))
    return dict(
        **plan_saved_fly_inputs(model, gas_field_reference=gas_field_reference,
            source_spec=source_spec, numerics=numerics, collision_science=collision_science,
            collision_sds_records=collision_sds_records, placement=placement,
            source_to_device=source_to_device),
        fields_reference=fields.reference, family_producer_reference=producer.reference,
    )


def require_trajectory_product(reference: Mapping | OpenedArtifact) -> OpenedArtifact:
    """Read only the actual published dual-cone terminal data, not old fields/code."""
    product = open_artifact(reference.reference if isinstance(reference, OpenedArtifact) else reference,
                            expected_kind="trajectory_result")
    if (product.metadata.get("backend") != "simion"
            or product.metadata.get("model") != "dual_cone_sds_gas_assisted_transport"):
        raise ValueError("trajectory product does not belong to dual-cone SIMION transport")
    for name in ("final_state", "metrics", "preparation_receipt", "source_csv"):
        product.data_path(name)
    return product
