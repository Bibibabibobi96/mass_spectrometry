"""Scientific compilation and explicit input materialization for the HS1 Ion Processor.

These inputs are unsolved; creating them never builds an IOB, refines fields or flies ions.
Repository orchestration, seed provision and native execution are separate consumers.
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

from msplatform.contracts.particle_count import validate_positive_particle_count
from msplatform.contracts.particle_count_policy import validate_standard_particle_count
from msplatform.contracts.particle_physics import kinetic_energy_ev
from msplatform.contracts.gas import BoxDomain
from msplatform.gas.field import prepare_gas_field
from msplatform.components.dual_pressure_rectilinear_ion_processor.gas_regions import build_gas_field_spec
from msplatform.backends.simion.gas_runtime import compile_gas_runtime
from msplatform.ion_release.release import generate_release_states, materialize_release_from_file, validate_release_spec
from msplatform.components.dual_pressure_rectilinear_ion_processor.native_geometry import native_projection
from msplatform.components.dual_pressure_rectilinear_ion_processor.timing import derive_native_timing
from msplatform.components.dual_pressure_rectilinear_ion_processor.coordinates import transform_from_config, to_project_position, to_project_vector
from msplatform.backends.simion.source import project_direct_velocity, render_standard_beams, render_source_states
from msplatform.backends.simion.ip_geometry import render_gem
from msplatform.backends.simion.ip_handoff import release_states, freeze_injected_source
from msplatform.backends.simion.collision_hs1 import adapt_hs1_for_repeat_fly
from msplatform.backends.simion.resources import native_resource_path
from msplatform.execution.resources import resource_path
from msplatform.execution.inputs import freeze_file
from msplatform.execution.clock_authority import validate_clock_authority
from msplatform.io.file_identity import file_sha256
from msplatform.io.manifest_records import file_record

def lua_literal(value: Any) -> str:
    """Serialize frozen JSON values into a data-only Lua companion."""
    if isinstance(value, dict):
        return "{" + ",".join("[" + json.dumps(k) + "]=" + lua_literal(v) for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "{" + ",".join(map(lua_literal, value)) + "}"
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "nil"
    return json.dumps(value, allow_nan=False)

def validate_source_profile(config: dict[str, Any]) -> str:
    """Validate explicit study scope and count without upgrading exploration."""
    profile = config["source_profile"]
    if profile == "upstream":
        if "injected_source" not in config or config["source"]["particle_count"] < 0:
            raise ValueError("upstream source requires its frozen admission contract")
        return profile
    count = validate_positive_particle_count(config["source"]["particle_count"])
    if profile == "functional":
        validate_standard_particle_count(count)
    elif profile != "exploration":
        raise ValueError("source_profile must be functional or exploration")
    return profile

def validate_configs(config: dict[str, Any]) -> None:
    """Reject malformed scientific inputs before solver startup."""
    baseline, numerics, source, acceptance = (config[k] for k in ("baseline", "numerics", "source", "acceptance"))
    expected = {
        "geometry": "guide_length_mm hp_length_mm lp_length_mm r0_mm guide_r0_mm guide_order hp_center_mm lp_center_mm extraction_slit_length_mm extraction_slit_width_mm extraction_end_y_mm boundary_radius_mm",
        "electric": "rf_frequency_hz rf_peak_to_peak_v guide_rf_peak_to_peak_v rf_quench_delay_cycles rf_quench_alignment lift_v",
        "gas": "temperature_k mass_amu hp_pressure_pa lp_pressure_pa cross_section_m2 mean_free_path_mm",
        "schedule": "capture_end_us transfer_end_us lift_end_us extraction_start_us terminal_us",
        "clock": "epoch_us frame_id rf_phase_rad",
    }
    if set(baseline) - {"electrode_contours"} != {"schema_version", "native_geometry", *expected} or baseline["schema_version"] != 1:
        raise ValueError("unsupported baseline schema/fields")
    for section, fields in expected.items():
        if set(baseline[section]) != set(fields.split()):
            raise ValueError(f"unknown or missing {section} fields")
        for key, value in baseline[section].items():
            if section == "electric" and key == "rf_quench_alignment":
                if not isinstance(value, str) or value not in {"requested_time", "next_cosine_zero"}:
                    raise ValueError("unsupported electric.rf_quench_alignment")
            elif key == "frame_id":
                if not isinstance(value, str) or not value:
                    raise ValueError("frame_id must be nonempty")
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"invalid finite number {section}.{key}")
            elif section == "gas" and key in {"hp_pressure_pa", "lp_pressure_pa"} and value < 0:
                raise ValueError(f"negative pressure {section}.{key}")
            elif key not in {"epoch_us", "rf_phase_rad", "mean_free_path_mm", "hp_pressure_pa", "lp_pressure_pa"} and value <= 0:
                raise ValueError(f"nonpositive physical input {section}.{key}")
    nkeys = "schema_version dt_us trajectory_quality sample_interval_us extraction_sample_interval_us seed rf_steps_per_period solver_timeout_s hs1_steps_per_mfp native_grid_mm refine_convergence_v native_aux_segments collision_rng_policy".split()
    if set(numerics) != set(nkeys) or numerics["schema_version"] != 1:
        raise ValueError("unsupported numerics schema/fields")
    if numerics["collision_rng_policy"] != "per_global_particle_seed_v1":
        raise ValueError("unsupported collision RNG policy")
    for key, value in numerics.items():
        if key == "collision_rng_policy":
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"invalid numerics.{key}")
    for key in ("dt_us", "sample_interval_us", "extraction_sample_interval_us", "rf_steps_per_period", "solver_timeout_s", "hs1_steps_per_mfp"):
        if numerics[key] <= 0:
            raise ValueError(f"nonpositive numerics.{key}")
    for key in ("seed", "rf_steps_per_period", "trajectory_quality"):
        if numerics[key] != int(numerics[key]):
            raise ValueError(f"numerics.{key} must be integer")
    g, s, e = (baseline[k] for k in ("geometry", "schedule", "electric"))
    if not (0 < s["capture_end_us"] < s["transfer_end_us"] < s["lift_end_us"] == s["extraction_start_us"] < s["terminal_us"]):
        raise ValueError("stage times must be ordered, with lift ending at extraction")
    if not (g["guide_length_mm"] < g["hp_center_mm"] < g["guide_length_mm"] + g["hp_length_mm"] < g["lp_center_mm"] < sum(g[k] for k in ("guide_length_mm", "hp_length_mm", "lp_length_mm"))):
        raise ValueError("trap centers must lie inside their segments")
    if g["guide_order"] != 4 or baseline["gas"]["mean_free_path_mm"] != -1:
        raise ValueError("this version supports ideal octupole and HS1 automatic MFP")
    if numerics["dt_us"] > 1e6 / e["rf_frequency_hz"] / numerics["rf_steps_per_period"]:
        raise ValueError("time step exceeds declared RF resolution")
    if baseline["clock"]["epoch_us"] != 0:
        raise ValueError("single-cohort workflow begins at instrument epoch zero")
    timing = derive_native_timing(baseline)
    if "native_timing" in config and config["native_timing"] != timing:
        raise ValueError("native timing differs from its scientific compiler")
    transform_from_config(config)
    if "injected_source" not in config:
        validate_release_spec(source)
    validate_source_profile(config)
    if not 1 <= numerics["seed"] <= 2**31-2 or numerics["seed"]+source["particle_count"]-1 > 2**31-2:
        raise ValueError("per-particle seed exceeds project conservative integer envelope")
    if source["frame_id"] != baseline["clock"]["frame_id"] or ("injected_source" not in config and source["common_time_of_birth_s"] != 0):
        raise ValueError("source frame/clock mismatch")
    if source["particle_count"] and source["species"]["charge_state"] <= 0:
        raise ValueError("positive ions are required for this polarity schedule")
    akeys = "schema_version minimum_capture_fraction minimum_extraction_fraction max_hp_mean_kinetic_energy_ev max_pre_extraction_axial_sigma_mm minimum_extraction_mean_energy_ev maximum_extraction_mean_energy_ev".split()
    if set(acceptance) != set(akeys) or acceptance["schema_version"] != 1:
        raise ValueError("unsupported acceptance schema/fields")
    for key in akeys[1:]:
        value = acceptance[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"invalid acceptance.{key}")
    if any(acceptance[k] > 1 for k in ("minimum_capture_fraction", "minimum_extraction_fraction")):
        raise ValueError("fraction threshold outside (0,1]")
    if acceptance["minimum_extraction_mean_energy_ev"] > acceptance["maximum_extraction_mean_energy_ev"]:
        raise ValueError("extraction energy bounds must be ordered")
    if "shield_extraction_slit_width_mm" not in baseline["native_geometry"]:
        raise ValueError("current author inputs require an explicit shield extraction aperture")
    native_projection(baseline, numerics)
    point=config["native_operating_point"]
    point_keys="schema_version capture_hp_offset_v capture_lp_offset_v guide_offset_v hp_aux_capture_relative_v hp_aux_transfer_relative_v hp_transfer_offset_v lp_outer_relative_v lp_inner_relative_v entrance_lens_v end_lens_relative_v extraction_push_relative_v extraction_pull_relative_v extraction_shield_relative_v lift_v".split()
    if set(point)!=set(point_keys) or point["schema_version"]!=1:
        raise ValueError("unsupported native operating point")
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in point.values()):
        raise ValueError("native voltages must be finite")

def derive_numerical_boundaries(projection: dict[str, Any]) -> dict[str, Any]:
    """Place numerical observations inside both native axial domain ends.

    This midpoint is an observation/termination surface, not metal. It leaves
    the native geometry and GEM unchanged and uses only the frozen projection.
    """
    ends = [solid["max_mm"][0] for electrode in projection["electrodes"]
            if electrode["name"] == "exit_lens" for solid in electrode["solids"]
            if solid["shape"] == "box"]
    if not ends:
        raise ValueError("exit lens solid is required for numerical boundary")
    last_lens = max(ends)
    domain_end = projection["maximum_mm"][0]
    boundary = (last_lens + domain_end) / 2
    if not all(math.isfinite(value) for value in (last_lens, domain_end, boundary)) or not last_lens < boundary < domain_end:
        raise ValueError("numerical downstream exit must lie after lens and inside PA domain")
    origin, grid = projection["origin_mm"][0], projection["grid_mm"]
    upstream = origin + grid
    if not all(math.isfinite(value) for value in (origin, grid, upstream)) or grid <= 0 or not origin < upstream < boundary:
        raise ValueError("numerical upstream exit must lie one positive PA cell inside domain")
    return {"schema_version": 2, "role": "native_numerical_observation_boundaries",
            "upstream_exit_x_mm": upstream, "downstream_exit_x_mm": boundary,
            "classification": "numerical_observation_not_metal"}

def validate_numerical_boundaries(boundaries: dict, projection: dict, *, recorded: bool = False) -> None:
    """Validate active observations or an explicit read-only historical record."""
    expected = derive_numerical_boundaries(projection)
    if recorded and set(boundaries) == {"downstream_exit_x_mm", "classification"}:
        expected = {key: expected[key] for key in boundaries}
    if boundaries != expected:
        raise ValueError("numerical observation boundaries differ from their derived authority")

def validate_diagnostics_config(config: dict) -> None:
    """Validate the complete diagnostic author contract before solver startup."""
    contract = config
    expected = {"schema_version", "role", "max_ordinary_bracket_us", "max_extraction_bracket_us", "evolution_interval_us", "png_dpi", "snapshots", "stage_labels"}
    if set(contract) != expected or contract["schema_version"] != 1 or contract["role"] != "ion_processor_diagnostics":
        raise ValueError("unsupported diagnostics contract")
    for key in ("max_ordinary_bracket_us", "max_extraction_bracket_us", "evolution_interval_us", "png_dpi"):
        if isinstance(contract[key], bool) or not isinstance(contract[key], (int, float)) or not math.isfinite(contract[key]) or contract[key] <= 0:
            raise ValueError(f"invalid diagnostics {key}")
    if contract["png_dpi"] < 180:
        raise ValueError("diagnostic PNG requires at least 180 DPI")
    labels = []
    allowed_anchors = {"epoch_us", "capture_end_us", "transfer_end_us", "lift_end_us", "extraction_start_us", "terminal_us", "primary_quench_us", "pulse_start_us"}
    if not isinstance(contract["snapshots"], list) or not contract["snapshots"]:
        raise ValueError("diagnostic snapshots must be nonempty")
    for item in contract["snapshots"]:
        if not isinstance(item, dict) or set(item) != {"label", "anchor", "offset_us"}:
            raise ValueError("snapshot must declare label/anchor/offset")
        if not isinstance(item["label"], str) or not item["label"] or item["anchor"] not in allowed_anchors:
            raise ValueError("invalid snapshot label or schedule anchor")
        if isinstance(item["offset_us"], bool) or not isinstance(item["offset_us"], (int,float)) or not math.isfinite(item["offset_us"]):
            raise ValueError("snapshot offset must be finite numeric")
        labels.append(item["label"])
    if len(set(labels)) != len(labels) or not isinstance(contract["stage_labels"], list) or not contract["stage_labels"] or not set(contract["stage_labels"]) <= set(labels):
        raise ValueError("duplicate or missing diagnostic stage label")


def validate_field_diagnostics_config(config: dict[str, Any]) -> None:
    """Reject unknown sampling controls, nonfinite inputs and unsupported stages."""
    keys = {"schema_version", "epsilon_us", "stages", "sections", "section_radius_scale", "fit_radius_scale",
            "section_grid_multiple", "axial_grid_multiple", "orthogonal_grid_multiple", "quiver_stride",
            "maximum_samples", "figure_width_mm", "figure_height_mm", "dpi"}
    if set(config) != keys or config["schema_version"] != 1:
        raise ValueError("unsupported field diagnostics schema/fields")
    for key in keys - {"schema_version", "stages", "sections"}:
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"field diagnostics {key} must be positive and finite")
    for key in ("section_grid_multiple", "axial_grid_multiple", "orthogonal_grid_multiple", "quiver_stride", "maximum_samples", "dpi"):
        if int(config[key]) != config[key]:
            raise ValueError(f"field diagnostics {key} must be integer")
    if config["fit_radius_scale"] >= config["section_radius_scale"]:
        raise ValueError("fit radius must lie inside sampled cross sections")
    seen = set()
    for stage in config["stages"]:
        if set(stage) != {"stage_id", "time_ref", "component"} or not stage["stage_id"] or stage["stage_id"] in seen:
            raise ValueError("invalid/duplicate field stage")
        seen.add(stage["stage_id"])
        if stage["time_ref"] not in {"capture_mid", "transfer_mid", "pre_extraction", "quench_mid", "pulse_after"}:
            raise ValueError("unsupported field time reference")
        if stage["component"] not in {"dc", "rf_only_peak", "total"}:
            raise ValueError("unsupported native field component")
    if not seen:
        raise ValueError("field stages cannot be empty")
    seen = set()
    for section in config["sections"]:
        expected = {"section_id", "position_ref"}
        if section.get("position_ref") == "hp_fraction":
            expected.add("fraction")
            fraction = section["fraction"]
            if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not 0 < fraction < 1:
                raise ValueError("HP section fraction must be in (0,1)")
        elif section.get("position_ref") != "lp_center":
            raise ValueError("unsupported native field section")
        if set(section) != expected or not section["section_id"] or section["section_id"] in seen:
            raise ValueError("invalid/duplicate field section")
        seen.add(section["section_id"])
    if not seen:
        raise ValueError("field sections cannot be empty")


def compile_source(config: dict[str, Any], *, admission: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compile the existing source/clock projection without vendor, seed or file writes.

    Admission is the explicit validated result of ip_handoff.load_injected_source;
    standalone sources use the existing release specification and deterministic sampler.
    """
    config = copy.deepcopy(config)
    states = []
    if admission is not None:
        states = release_states(admission)
        species = {(row["mass_amu"], row["charge_state"]) for row in states}
        if len(species) > 1:
            raise ValueError("current IP diagnostics support one actual upstream species per run")
        config["source"] = dict(frame_id=admission["contract"]["frame_id"], particle_count=len(states),
            mother_particle_count=admission["census"]["mother_count"],
            species=dict(zip(("mass_amu", "charge_state"), next(iter(species)))) if species else None)
        config["source_profile"] = "upstream"
        config["source_authority_file"] = "injected_source.json"
        config["injected_source"] = dict(clock_epoch_id=admission["clock"]["clock_epoch_id"],
            particle_ids=[row["particle_id"] for row in states],
            mother_particle_count=admission["census"]["mother_count"])
        if states and config["numerics"]["seed"] + max(config["injected_source"]["particle_ids"]) - 1 > 2**31 - 2:
            raise ValueError("original upstream particle ID exceeds IP per-particle seed envelope")
    validate_configs(config)
    if admission is None:
        states = generate_release_states(config["source"])
    config["native_timing"] = derive_native_timing(config["baseline"])
    beams, companions = [], []
    for ordinal, row in enumerate(states, 1):
        vx, vy, vz = (row[k] for k in ("vx_m_s", "vy_m_s", "vz_m_s"))
        energy = kinetic_energy_ev(row["mass_amu"], vx, vy, vz)
        arrival = row["arrival_time_us"] if admission is not None else 0
        x, y, z = to_project_position(config, [row["x_mm"], row["y_mm"], row["z_mm"]])
        direction = to_project_vector(config, [vx, vy, vz])
        state, beam = project_direct_velocity(particle_id=ordinal, time_us=arrival,
            position_mm=[row["x_mm"], row["y_mm"], row["z_mm"]], velocity_m_s=[vx, vy, vz], energy_ev=energy,
            mass_amu=row["mass_amu"], charge_state=row["charge_state"], beam_position_mm=[x, y, z],
            beam_direction=list(direction), weight=1, color=1)
        companions.append(state)
        beams.append(beam)
    config["extraction_force_audit"] = dict(schema_version=1, role="native_extraction_force_audit", start_reference="native_timing.primary_quench_us", field_basis_count=15, step_state_scope="actual_pre_and_post_HS1", integration="Hermite_composite_Simpson_5_vs_3")
    config["native_projection"] = native_projection(config["baseline"],config["numerics"])
    config["numerical_boundaries"] = derive_numerical_boundaries(config["native_projection"])
    if any(row["x_mm"] <= config["numerical_boundaries"]["upstream_exit_x_mm"] for row in states):
        raise ValueError("source births must lie strictly inside the upstream numerical observation")
    if admission is not None and any(row["arrival_time_us"] >= config["baseline"]["schedule"]["capture_end_us"] for row in states):
        raise ValueError("IP injection must arrive before the declared capture checkpoint")
    return dict(config=config, states=states, fly2=render_standard_beams(beams),
                source_states=render_source_states(companions),
                clock_epoch_id="ion_processor_epoch_zero_v1" if admission is None else admission["clock"]["clock_epoch_id"])


def materialize_inputs(run: Path, config: dict[str, Any], *, configuration_files: dict[str, Path],
                       hs1_source: Path, admission: dict[str, Any] | None = None) -> dict[str, Any]:
    """Freeze explicit research/vendor authorities and unsolved native input files.

    No project defaults, repository lookup, seed, field adoption or run owner is used.
    Required resources and the official-source adapter are checked before output writes.
    """
    for key, validate in (("diagnostics", validate_diagnostics_config),
                          ("field_diagnostics", validate_field_diagnostics_config)):
        if key in config:
            validate(config[key])
    supplied_config = config
    compiled = compile_source(config, admission=admission)
    config = compiled["config"]
    projection = config["native_projection"]
    gas_spec = build_gas_field_spec(config["baseline"], domain=BoxDomain(
        projection["origin_mm"], projection["maximum_mm"], (True,)*3, (True,)*3))
    gas_lua = compile_gas_runtime(prepare_gas_field(gas_spec), placement=transform_from_config(config))
    native = {name: native_resource_path("ip_" + name) for name in
              ("runtime.lua", "build_workbench.lua", "probe_native_field.lua", "extraction_force_audit.lua")}
    native.update({name: native_resource_path(source) for name, source in
                   (("native_drive.lua", "native_drive.lua"),
                    ("scientific_event_csv.lua", "scientific_event_csv.lua"),
                    ("simion_rf_drive.lua", "rf_drive.lua"),
                    ("collision_hs1_gas.lua", "collision_hs1_gas.lua"),
                    ("voltage_waveforms.lua", "voltage_waveforms.lua"))})
    native["native_run_path.lua"] = resource_path("native_run_path.lua")
    authorities = {name: Path(path) for name, path in configuration_files.items()}
    required_authorities = {"baseline", "numerics", "acceptance", "native_operating_point"}
    if admission is None:
        required_authorities.add("source")
    required_authorities.update(key for key in ("coordinate_transform", "diagnostics", "field_diagnostics") if key in config)
    if not required_authorities.issubset(authorities):
        raise ValueError("IP materialization missing explicit research authorities: " + ", ".join(sorted(required_authorities - authorities.keys())))
    missing = [str(path) for path in [*authorities.values(), Path(hs1_source), *native.values()] if not path.is_file()]
    if missing:
        raise ValueError("IP materialization required resource is missing: " + "; ".join(missing))
    for name, path in authorities.items():
        if name in supplied_config and json.loads(path.read_text(encoding="utf-8-sig")) != supplied_config[name]:
            raise ValueError(f"IP research authority differs from supplied configuration: {name}")
    original = Path(hs1_source).read_text(encoding="utf-8")
    adapted = adapt_hs1_for_repeat_fly(original)
    inputs, solver = run / "inputs", run / "simion"
    inputs.mkdir(exist_ok=True)
    solver.mkdir(exist_ok=True)
    for name, source in authorities.items():
        if name == "source" and admission is not None:
            continue
        freeze_file(source, inputs / (name + ".json"))
    if admission is not None:
        freeze_injected_source(admission, run)
    else:
        materialize_release_from_file(inputs / "source.json", inputs / "release.csv", inputs / "release_receipt.json")
    for name, source in native.items():
        freeze_file(source, solver / name)
    collision_original = freeze_file(Path(hs1_source), inputs / "collision_hs1_original.lua")
    (solver / "collision_hs1.lua").write_text(adapted, encoding="utf-8")
    def write_json(path: Path, value: dict[str, Any]) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    write_json(inputs / "collision_adapter.json", dict(schema_version=1, role="hs1_repeat_fly_lifecycle_adapter", original_sha256=collision_original["sha256"], adapted_sha256=file_sha256(solver / "collision_hs1.lua"), algorithm_changed=False, adapter_hooks=["reset_run_state", "bound_parameters"], bound_parameters_read_only=True, reason="Run-local lifecycle reset plus read-only audit of module-bound adjustables; SIMION 2020 forbids callback-time workbench imports"))
    write_json(inputs / "native_timing.json", config["native_timing"])
    (solver / "processor.fly2").write_text(compiled["fly2"], encoding="utf-8")
    (solver / "source_states.lua").write_text(compiled["source_states"], encoding="utf-8")
    (solver / "processor.gem").write_text(render_gem(config["native_projection"]), encoding="utf-8")
    (solver / "gas_field.lua").write_text(gas_lua, encoding="utf-8", newline="\n")
    config["gas_runtime"] = dict(schema_version=1, field_id=gas_spec.field_id,
        query_frame_id=transform_from_config(config).to_frame_id,
        sampling_policy="legacy_callback_sampling_v1", source_kind=gas_spec.source.kind,
        assumptions=list(gas_spec.source.assumptions), runtime=file_record(solver / "gas_field.lua"))
    (solver / "frozen_config.lua").write_text("return " + lua_literal(config) + "\n", encoding="utf-8")
    write_json(inputs / "resolved_model.json", config)
    epoch_path = inputs / "instrument_epoch.json"
    if admission is None:
        write_json(epoch_path, {"instrument_time_us": config["baseline"]["clock"]["epoch_us"]})
        write_json(inputs / "clock_authority.json", dict(schema_version=1, role="canonical_clock_authority", clock_epoch_id="ion_processor_epoch_zero_v1", instrument_time_unit="us", canonical_time_basis="instrument_epoch_absolute_time", authority=dict(path="inputs/instrument_epoch.json", sha256=file_sha256(epoch_path), field="instrument_time_us"), solver_local_time_basis="elapsed_time_from_zero_us", adapter_materialization="instrument_time_us_equals_authority_epoch_plus_solver_elapsed_once", handoff_policy="preserve_instrument_time_us_and_clock_epoch_id", legacy_new_campaign_allowed=False))
    write_json(inputs / "clock_validation.json", validate_clock_authority(inputs / "clock_authority.json", run))
    return compiled
