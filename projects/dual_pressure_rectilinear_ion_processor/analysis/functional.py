"""Freeze and analyze the abstract SIMION Ion Processor functional workflow.

Positions are mm, velocities m/s at the public boundary, and time is us.
New runs publish the declared project XYZ frame; legacy frozen runs retain
their original x-directed canonical mapping. No particle is resampled between the guide and extraction.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import statistics
import sys
import subprocess
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.contracts.canonical_clock_authority import validate_clock_authority
from common.contracts.verify_run_manifest import record_path
from common.contracts.particle_count_policy import POLICY_PATH, validate_positive_particle_count, validate_standard_particle_count
from common.contracts.particle_physics import kinetic_energy_ev
from common.contracts.particle_state import PARTICLE_STATE_COLUMNS, ENUMS, validate_particle_state
from common.ion_release.release import generate_release_states, materialize_release_from_file, validate_release_spec
from common.simion.particle_source import render_standard_beams, render_source_states
from projects.dual_pressure_rectilinear_ion_processor.analysis.native_geometry import native_projection, render_gem

from projects.dual_pressure_rectilinear_ion_processor.analysis.coordinates import (
    transform_from_config, to_project_position, to_project_vector,
    to_local_position, to_local_vector,
)

PROJECT = "dual_pressure_rectilinear_ion_processor"
EVENTS = ["source", "hp_enter", "capture", "transfer", "pre_extraction", "extraction_exit", "terminal"]


def derive_native_timing(baseline: dict[str, Any]) -> dict[str, Any]:
    """Compile author-selected LP switch alignment on the instrument clock.

    Eight ULPs of the computed half-cycle index cover phase arithmetic roundoff
    at an already-zero request; this is not a physical switching tolerance.
    Other consumers read the frozen result and never recompute alignment.
    """
    electric, clock, schedule = (baseline[key] for key in ("electric", "clock", "schedule"))
    frequency = electric["rf_frequency_hz"] * 1e-6
    phase_cycles = clock["rf_phase_rad"] / (2 * math.pi)
    requested = schedule["extraction_start_us"]
    delay = electric["rf_quench_delay_cycles"]
    alignment = electric["rf_quench_alignment"]
    if not isinstance(alignment, str) or alignment not in {"requested_time", "next_cosine_zero"}:
        raise ValueError("unsupported electric.rf_quench_alignment")
    if not all(math.isfinite(value) for value in (frequency, phase_cycles, requested, delay, clock["epoch_us"])) or frequency <= 0 or delay <= 0:
        raise ValueError("invalid native RF timing inputs")
    if alignment == "requested_time":
        primary = requested
        roundoff_us = 0
        policy = "requested_instrument_time_v1"
    else:
        if 2 * delay != round(2 * delay):
            raise ValueError("side RF zero switching requires a positive integer number of half-cycles")
        index = 2 * (frequency * (clock["epoch_us"] + requested) + phase_cycles) - .5
        if not math.isfinite(index):
            raise ValueError("native RF timing phase overflows its finite clock")
        roundoff = 8 * math.ulp(index)
        nearest = round(index)
        if abs(index - nearest) <= roundoff:
            primary = requested
        else:
            primary = (.25 + .5 * math.ceil(index) - phase_cycles) / frequency - clock["epoch_us"]
            if primary < requested:
                raise ValueError("derived primary RF quench precedes its requested time")
        roundoff_us = roundoff/(2*frequency)
        policy = "cosine_zero_at_or_after_requested_v1"
    pulse = primary + delay / frequency
    if not schedule["lift_end_us"] <= primary < pulse < schedule["terminal_us"]:
        raise ValueError("derived RF quench/pulse must follow lift and precede terminal time")
    return dict(schema_version=1, role="native_electrode_timing",
                policy=policy, requested_quench_us=requested,
                primary_quench_us=primary, side_quench_us=pulse, pulse_start_us=pulse,
                alignment_roundoff_us=roundoff_us)


def read_json(path: Path) -> dict[str, Any]:
    """Read one versioned UTF-8 JSON object."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    """Write reproducible, finite JSON using LF."""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


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


def adapt_hs1_for_repeat_fly(original: str) -> str:
    """Add reset and read-only lexical parameter audit; preserve collision code.

    SIMION 2020 rejects simion.workbench_program during callback-time imports.
    The installed official source is never edited. This run-local adapter resets
    private state and exposes the module-bound adjustables without mutating them.
    Unknown source declarations are rejected before creating the adapted copy.
    """
    for declaration in ("local max_timestep", "local is_initialized", "local ke_averages", "local last_collision_times", "local trace_count"):
        if declaration not in original:
            raise ValueError(f"official HS1 reset contract missing: {declaration}")
    bound_names = ("_gas_mass_amu", "_temperature_k", "_pressure_pa", "_sigma_m2",
                   "_mean_free_path_mm", "_steps_per_MFP", "_random_seed",
                   "_mark_collisions", "_trace_level")
    for name in bound_names:
        if not re.search(rf"(?m)^adjustable\s+{re.escape(name)}\s*=", original):
            raise ValueError(f"official HS1 bound parameter declaration missing: {name}")
    if "function HS1.bound_parameters" in original or "function HS1.reset_run_state" in original:
        raise ValueError("official HS1 source already contains project adapter hooks")
    if original.count("return HS1")!=1:
        raise ValueError("unsupported official HS1 return structure")
    hook="""-- Project lifecycle adapter: no change to collision equations or sampling.
function HS1.reset_run_state()
    is_initialized = false
    max_timestep = nil
    ke_averages = {}
    last_collision_times = {}
    trace_count = 0
end

-- Read the actual adjustable bindings in the imported HS1 module's scope.
-- This allocates an audit table only; no parameter, PRNG or collision state changes.
function HS1.bound_parameters()
    return {
        gas_mass_amu = _gas_mass_amu,
        temperature_k = _temperature_k,
        pressure_pa = _pressure_pa,
        sigma_m2 = _sigma_m2,
        mean_free_path_mm = _mean_free_path_mm,
        steps_per_mfp = _steps_per_MFP,
        random_seed = _random_seed,
        mark_collisions = _mark_collisions,
        trace_level = _trace_level,
    }
end

"""
    return original.replace("return HS1",hook+"return HS1")


def validate_source_profile(config: dict[str, Any]) -> str:
    """Validate explicit study scope and count without upgrading exploration."""
    profile = config["source_profile"]
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
        "geometry": "guide_length_mm hp_length_mm lp_length_mm r0_mm guide_r0_mm guide_order hp_center_mm lp_center_mm interface_halfwidth_mm guide_blend_halfwidth_mm extraction_slit_length_mm extraction_slit_width_mm extraction_end_y_mm boundary_radius_mm",
        "electric": "rf_frequency_hz rf_peak_to_peak_v guide_rf_peak_to_peak_v rf_quench_delay_cycles rf_quench_alignment hp_axial_curvature_v_per_mm2 lp_axial_curvature_v_per_mm2 lp_capture_offset_v hp_transfer_offset_v lift_v extraction_gradient_v_per_mm hp_transfer_gradient_v_per_mm lp_transfer_axial_curvature_v_per_mm2",
        "gas": "temperature_k mass_amu hp_pressure_pa lp_pressure_pa cross_section_m2 mean_free_path_mm",
        "schedule": "capture_end_us transfer_end_us lift_end_us extraction_start_us terminal_us",
        "clock": "epoch_us frame_id rf_phase_rad",
    }
    if set(baseline) != {"schema_version", "native_geometry", *expected} or baseline["schema_version"] != 1:
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
            elif key not in {"epoch_us", "rf_phase_rad", "mean_free_path_mm"} and value <= 0:
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
    validate_release_spec(source)
    validate_source_profile(config)
    if not 1 <= numerics["seed"] <= 2**31-2 or numerics["seed"]+source["particle_count"]-1 > 2**31-2:
        raise ValueError("per-particle seed exceeds project conservative integer envelope")
    if source["frame_id"] != baseline["clock"]["frame_id"] or source["common_time_of_birth_s"] != 0:
        raise ValueError("source frame/clock mismatch")
    if source["species"]["charge_state"] <= 0:
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
    native_projection(baseline, numerics)
    point=config["native_operating_point"]
    point_keys="schema_version capture_hp_offset_v capture_lp_offset_v guide_offset_v hp_aux_capture_relative_v hp_aux_transfer_relative_v hp_transfer_offset_v lp_outer_relative_v lp_inner_relative_v entrance_lens_v end_lens_relative_v extraction_push_relative_v extraction_pull_relative_v extraction_shield_relative_v lift_v".split()
    if set(point)!=set(point_keys) or point["schema_version"]!=1:
        raise ValueError("unsupported native operating point")
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in point.values()):
        raise ValueError("native voltages must be finite")


def derive_numerical_boundaries(projection: dict[str, Any]) -> dict[str, Any]:
    """Place a diagnostic exit inside the native domain after the last lens.

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
    return {"downstream_exit_x_mm": boundary, "classification": "numerical_observation_not_metal"}


def prepare(run: Path, project: Path, simion_dir: Path, native_field_run: Path | None = None,
            source_profile: str = "functional", configuration_directory: Path | None = None) -> None:
    """Freeze contracts, official HS1, RF kernel and shared release for one run."""
    repo = project.parent.parent
    configuration = configuration_directory.resolve() if configuration_directory is not None else project / "config"
    inputs, solver = run / "inputs", run / "simion"
    solver.mkdir(exist_ok=True)
    if source_profile not in {"functional", "exploration"}:
        raise ValueError("source_profile must be functional or exploration")
    config_files = {name: f"{name}.json" for name in
                    ("baseline", "numerics", "source", "acceptance", "native_operating_point", "diagnostics", "field_diagnostics")}
    config_files["source"] = "source_exploration.json" if source_profile == "exploration" else "source.json"
    config = {name: read_json(configuration / filename) for name, filename in config_files.items()}
    if (configuration / "coordinate_transform.json").is_file():
        config_files["coordinate_transform"] = "coordinate_transform.json"
        config["coordinate_transform"] = read_json(configuration / "coordinate_transform.json")
    elif configuration_directory is not None:
        raise ValueError("external configuration directory requires its explicit coordinate transform")
    config["source_profile"] = source_profile
    config["source_authority_file"] = config_files["source"]
    validate_configs(config)
    config["native_timing"] = derive_native_timing(config["baseline"])
    write_json(inputs / "native_timing.json", config["native_timing"])
    from projects.dual_pressure_rectilinear_ion_processor.analysis.diagnostics import validate_diagnostics_config
    from projects.dual_pressure_rectilinear_ion_processor.analysis.field_diagnostics import validate_field_diagnostics_config
    validate_diagnostics_config(config["diagnostics"])
    validate_field_diagnostics_config(config["field_diagnostics"])
    for name, filename in config_files.items():
        shutil.copyfile(configuration / filename, inputs / f"{name}.json")
    for evidence_name in ("geometry_sources", "source_parameter_sources", "component_matching_derivation"):
        evidence_path = configuration / f"{evidence_name}.json"
        if evidence_path.is_file():
            shutil.copyfile(evidence_path, inputs / evidence_path.name)
    git_context = {}
    for key, arguments in (("git_sha", ["rev-parse", "HEAD"]), ("worktree_porcelain", ["status", "--porcelain"])):
        result = subprocess.run(["git", "-C", str(repo), *arguments], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", check=False,
                                cwd=repo, timeout=10)
        git_context[key] = result.stdout.strip() if result.returncode == 0 else "unavailable"
    git_context["worktree_dirty"] = bool(git_context["worktree_porcelain"])
    write_json(inputs / "source_context.json", git_context)
    for name in ("runtime.lua", "native_drive.lua", "build_workbench.lua", "probe_native_field.lua"):
        shutil.copyfile(project / "simion" / name, solver / name)
    shutil.copyfile(repo / "common/multipole/simion_rf_drive.lua", solver / "simion_rf_drive.lua")
    shutil.copyfile(simion_dir / "examples/collision_hs1/collision_hs1.lua", inputs / "collision_hs1_original.lua")
    original=(inputs/"collision_hs1_original.lua").read_text(encoding="utf-8")
    (solver/"collision_hs1.lua").write_text(adapt_hs1_for_repeat_fly(original),encoding="utf-8")
    write_json(inputs/"collision_adapter.json",dict(schema_version=1,role="hs1_repeat_fly_lifecycle_adapter",original_sha256=file_sha256(inputs/"collision_hs1_original.lua"),adapted_sha256=file_sha256(solver/"collision_hs1.lua"),algorithm_changed=False,adapter_hooks=["reset_run_state","bound_parameters"],bound_parameters_read_only=True,reason="Run-local lifecycle reset plus read-only audit of module-bound adjustables; SIMION 2020 forbids callback-time workbench imports"))
    shutil.copyfile(repo / "common/simion/assets/iob_instance_seeds/1_instance_seed.iob", solver / "1_instance_seed.iob")
    materialize_release_from_file(inputs / "source.json", inputs / "release.csv", inputs / "release_receipt.json")
    states = generate_release_states(config["source"])
    beams, companions = [], []
    for row in states:
        vx, vy, vz = (row[k] for k in ("vx_m_s", "vy_m_s", "vz_m_s"))
        energy = kinetic_energy_ev(row["mass_amu"], vx, vy, vz)
        companions.append(dict(particle_id=row["particle_id"], t=0, x=row["x_mm"], y=row["y_mm"], z=row["z_mm"], vx=vx/1000, vy=vy/1000, vz=vz/1000, ke=energy))
        x, y, z = to_project_position(config, [row["x_mm"], row["y_mm"], row["z_mm"]])
        direction = to_project_vector(config, [vx, vy, vz])
        beams.append(dict(tob=0, mass=row["mass_amu"], charge=row["charge_state"], x=x, y=y, z=z, direction=direction, ke=energy, cwf=1, color=1))
    (solver / "processor.fly2").write_text(render_standard_beams(beams), encoding="utf-8")
    (solver / "source_states.lua").write_text(render_source_states(companions), encoding="utf-8")
    config["native_projection"] = native_projection(config["baseline"],config["numerics"])
    config["numerical_boundaries"] = derive_numerical_boundaries(config["native_projection"])
    (solver / "processor.gem").write_text(render_gem(config["baseline"],config["numerics"]),encoding="utf-8")
    config["workbench_seed_path"]=str(repo/"common/simion/assets/iob_instance_seeds/1_instance_seed.iob")
    config["native_field"]={"directory":str(solver),"source_manifest":None}
    external_inputs={}
    if native_field_run is not None:
        parent=native_field_run.resolve()
        manifest_path=parent/"run_manifest.json"
        manifest=read_json(manifest_path)
        if manifest.get("project")!=PROJECT or manifest.get("status") not in {"success","failed"}:
            raise ValueError("native field source must be an explicit terminal project run")
        parent_config=read_json(parent/"inputs/resolved_model.json")
        if parent_config["native_projection"]!=config["native_projection"] or parent_config["numerics"]["refine_convergence_v"]!=config["numerics"]["refine_convergence_v"]:
            raise ValueError("native field geometry/grid/refine identity differs")
        if file_sha256(parent/"simion/processor.gem")!=file_sha256(solver/"processor.gem"):
            raise ValueError("native GEM identity differs")
        if "Fast adjust Refining completed" not in (parent/"logs/refine.log").read_text(encoding="utf-8-sig"):
            raise ValueError("native field source lacks completed Refine evidence")
        family=[parent/"simion"/("processor.pa"+suffix) for suffix in ["#",*map(str,range(16)),"-surf"]]
        arguments=[sys.executable,"-m","common.contracts.verify_run_manifest",str(manifest_path),"--require-project",PROJECT,"--require-status",manifest["status"],"--consumer-projection-id","ion_processor_native_field_v1"]
        for key,record in manifest["inputs"].items():
            if record_path(record,base_dir=parent) in {(parent/"simion/processor.gem").resolve(),(parent/"inputs/numerics.json").resolve()}:
                arguments.extend(["--consumed-input",key,str(record_path(record,base_dir=parent))])
        for path in [*family,parent/"logs/refine.log"]:
            arguments.extend(["--consumed-output",str(path)])
        verification=subprocess.run(arguments,cwd=repo,timeout=120,capture_output=True,text=True,encoding="utf-8",check=True)
        config["native_field"]={"directory":str(parent/"simion"),"source_manifest":str(manifest_path),"source_manifest_sha256":file_sha256(manifest_path),"consumer_projection_id":"ion_processor_native_field_v1"}
        write_json(inputs/"native_field_consumption.json",{**config["native_field"],"verification":verification.stdout})
        external_inputs={f"native_field_{index}":str(path) for index,path in enumerate(family)}
        external_inputs["native_field_manifest"]=str(manifest_path)
    (solver / "frozen_config.lua").write_text("return " + lua_literal(config) + "\n", encoding="utf-8")
    write_json(inputs / "resolved_model.json", config)
    epoch_path = inputs / "instrument_epoch.json"
    write_json(epoch_path, {"instrument_time_us": config["baseline"]["clock"]["epoch_us"]})
    write_json(inputs / "clock_authority.json", dict(schema_version=1, role="canonical_clock_authority", clock_epoch_id="ion_processor_epoch_zero_v1", instrument_time_unit="us", canonical_time_basis="instrument_epoch_absolute_time", authority=dict(path="inputs/instrument_epoch.json", sha256=file_sha256(epoch_path), field="instrument_time_us"), solver_local_time_basis="elapsed_time_from_zero_us", adapter_materialization="instrument_time_us_equals_authority_epoch_plus_solver_elapsed_once", handoff_policy="preserve_instrument_time_us_and_clock_epoch_id", legacy_new_campaign_allowed=False))
    write_json(inputs / "clock_validation.json",validate_clock_authority(inputs/"clock_authority.json",run))
    from projects.dual_pressure_rectilinear_ion_processor.analysis import batching
    assert batching.resource_profile.PROFILE_ROLE == "simion_resource_profile"
    # Freeze the loaded repository source closure after shared source generation.
    # Solver inputs remain independent of an editable working tree.
    for module in tuple(sys.modules.values()):
        file=getattr(module,"__file__",None)
        if not file:
            continue
        path=Path(file).resolve()
        if path.suffix!=".py" or repo not in path.parents:
            continue
        relative=path.relative_to(repo)
        if relative.parts[0] not in {"common","projects"}:
            continue
        target=inputs/"code"/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,target)
    # The imported policy module reads its adjacent JSON at runtime. Freeze the
    # resource as well as Python sources so an isolated closure is executable.
    policy_relative = POLICY_PATH.relative_to(Path(__file__).resolve().parents[3])
    policy_target = inputs / "code" / policy_relative
    policy_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(repo / policy_relative, policy_target)
    host_policy = inputs / "code/common/host_resource_policy.json"
    host_policy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(repo / "common/host_resource_policy.json", host_policy)
    run_config = read_json(run / "run_config.json")
    run_config["inputs"] = {str(p.relative_to(run)).replace("/", "_"): str(p) for folder in (inputs, solver) for p in folder.rglob("*") if p.is_file()}
    run_config["inputs"].update(external_inputs)
    run_config["inputs"]["public_workbench_seed"]=config["workbench_seed_path"]
    run_config["parameters"] = dict(workflow="native_electrode_functional", actual_particle_count=len(states), qualification="unqualified_simplified_electrodes", canonical_state_frame="axial_z=x; transverse_x=z; transverse_y=y", clock_epoch_id="ion_processor_epoch_zero_v1", collision_model="official_SIMION_2020_HS1", rf_amplitude_convention="per_electrode_peak_to_peak_divided_by_two", source_handoff="same_cohort_no_reset", space_charge_enabled=False)
    if "coordinate_transform" in config:
        run_config["parameters"]["canonical_state_frame"] = transform_from_config(config).to_frame_id
        run_config["parameters"]["native_geometry_frame"] = transform_from_config(config).from_frame_id
    run_config["parameters"].update(source_profile=source_profile, source_authority_file=config_files["source"],
                                    configuration_directory=str(configuration.resolve()))
    write_json(run / "run_config.json", run_config)


def analyze(run: Path) -> dict[str, Any]:
    """Validate all identities and publish measured functional acceptance."""
    c = read_json(run / "inputs/resolved_model.json")
    profile = validate_source_profile(c)
    transform = transform_from_config(c)
    transformed = "coordinate_transform" in c
    b, acceptance = c["baseline"], c["acceptance"]
    sources = generate_release_states(c["source"])
    with (run / "simion/events.csv").open(encoding="utf-8", newline="") as f:
        raw = list(csv.DictReader(f))
    schedule=b["schedule"]
    timing = c["native_timing"]
    if timing != derive_native_timing(b):
        raise ValueError("frozen native timing differs from scientific inputs")
    stage_times={"capture":schedule["capture_end_us"],"transfer":schedule["transfer_end_us"],"pre_extraction":timing["primary_quench_us"]}
    previous_time: dict[int,float]={}
    for event in raw:
        particle=int(event["particle_id"]);t=float(event["t_us"])
        if not math.isfinite(t) or t<previous_time.get(particle,0):
            raise ValueError("nonfinite or nonmonotonic scientific event clock")
        previous_time[particle]=t
        if event["event"] in stage_times and abs(t-stage_times[event["event"]])>1e-6:
            raise ValueError("scientific event does not match its frozen stage clock")
        if event["reason"] == "downstream_domain_exit":
            if event["event"] != "terminal":
                raise ValueError("downstream domain exit must be a terminal event")
            boundaries = c.get("numerical_boundaries")
            if boundaries is None or boundaries != derive_numerical_boundaries(c["native_projection"]):
                raise ValueError("downstream domain exit lacks its derived numerical boundary")
            position = to_local_position(c, [float(event[k]) for k in ("x_mm", "y_mm", "z_mm")])
            velocity = to_local_vector(c, [float(event[k]) for k in ("vx_mm_us", "vy_mm_us", "vz_mm_us")])
            if abs(position[0] - boundaries["downstream_exit_x_mm"]) > 1e-9 or velocity[0] <= 0:
                raise ValueError("downstream domain exit is outside its plane/direction")
        if event["event"]=="extraction_exit":
            local_position = to_local_position(c, [float(event[k]) for k in ("x_mm", "y_mm", "z_mm")])
            local_velocity = to_local_vector(c, [float(event[k]) for k in ("vx_mm_us", "vy_mm_us", "vz_mm_us")])
            if t<timing["primary_quench_us"] or abs(local_position[1]-b["geometry"]["extraction_end_y_mm"])>1e-9 or local_velocity[1]<=0:
                raise ValueError("extraction event is outside its acceptance plane/clock/direction")
    rows = []
    local_guide_positions = {}
    mass = c["source"]["species"]["mass_amu"]
    for r in raw:
        t,x,y,z,vx,vy,vz = (float(r[k]) for k in ("t_us","x_mm","y_mm","z_mm","vx_mm_us","vy_mm_us","vz_mm_us"))
        lx, ly, lz = to_local_position(c, [x, y, z])
        lvx, lvy, lvz = to_local_vector(c, [vx, vy, vz])
        position = (z, x, y) if transformed else (x, z, y)
        velocity = (vz, vx, vy) if transformed else (vx, vz, vy)
        radius = math.hypot(x, y) if transformed else math.hypot(ly, lz)
        divergence = math.degrees(math.atan2(math.hypot(vx, vy), abs(vz))) if transformed else math.degrees(math.atan2(math.hypot(lvy, lvz), abs(lvx)))
        reason = r["reason"]
        event = r["event"]
        local_guide_positions[(int(r["particle_id"]), event)] = lx
        rows.append(dict(zip(PARTICLE_STATE_COLUMNS, [int(r["particle_id"]),event,"transmitted" if reason == "acceptance_surface" else "lost" if reason != "none" else "alive",reason,t,t,(2*math.pi*b["electric"]["rf_frequency_hz"]*t*1e-6+b["clock"]["rf_phase_rad"])%(2*math.pi),*position,*(v*1000 for v in velocity),kinetic_energy_ev(mass,vx*1000,vy*1000,vz*1000),radius,divergence,b["geometry"]["boundary_radius_mm"]])))
    output = run / "results/particle_state.csv"
    with output.open("w", encoding="utf-8", newline="") as f:
        writer=csv.DictWriter(f,fieldnames=PARTICLE_STATE_COLUMNS); writer.writeheader(); writer.writerows(rows)
    expected = {}
    for source in sources:
        x, y, z = to_project_position(c, [source[k] for k in ("x_mm", "y_mm", "z_mm")])
        vx, vy, vz = to_project_vector(c, [source[k] for k in ("vx_m_s", "vy_m_s", "vz_m_s")])
        position = (z, x, y) if transformed else (x, z, y)
        velocity = (vz, vx, vy) if transformed else (vx, vz, vy)
        expected[source["particle_id"]] = dict(zip(
            ("time_us", "elapsed_time_us", "axial_z_mm", "transverse_x_mm", "transverse_y_mm",
             "velocity_axial_m_s", "velocity_x_m_s", "velocity_y_m_s", "kinetic_energy_eV"),
            (0, 0, *position, *velocity, kinetic_energy_ev(mass, vx, vy, vz))))
    validation = validate_particle_state(output,expected,b["electric"]["rf_frequency_hz"],b["clock"]["rf_phase_rad"],enums={**ENUMS,"event":EVENTS,"terminal_reason":[*ENUMS["terminal_reason"],"downstream_domain_exit"]})
    grouped={event:[r for r in rows if r["event"]==event] for event in EVENTS}
    metrics = {}
    for event, group in grouped.items():
        metrics[event] = dict(count=len(group),mean_kinetic_energy_ev=statistics.fmean(r["kinetic_energy_eV"] for r in group) if group else None,axial_sigma_mm=statistics.pstdev(local_guide_positions[(r["particle_id"], event)] for r in group) if group else None)
    if transformed:
        for metric in metrics.values():
            metric["slow_sigma_y_mm"] = metric["axial_sigma_mm"]
            metric["axial_sigma_axis"] = "native guide axis = project y"
    hp=[r for r in grouped["capture"] if b["geometry"]["guide_length_mm"] <= local_guide_positions[(r["particle_id"], "capture")] <= b["geometry"]["guide_length_mm"]+b["geometry"]["hp_length_mm"]]
    hp_end=b["geometry"]["guide_length_mm"]+b["geometry"]["hp_length_mm"]
    lp_end=hp_end+b["geometry"]["lp_length_mm"]
    lp=[r for r in grouped["pre_extraction"] if hp_end<local_guide_positions[(r["particle_id"], "pre_extraction")]<lp_end]
    n=len(sources); m=metrics
    checks = dict(capture_fraction=len(hp)/n >= acceptance["minimum_capture_fraction"], extraction_fraction=len(grouped["extraction_exit"])/n >= acceptance["minimum_extraction_fraction"], hp_cooling=bool(hp) and statistics.fmean(r["kinetic_energy_eV"] for r in hp) <= acceptance["max_hp_mean_kinetic_energy_ev"], lp_compression=bool(grouped["pre_extraction"]) and m["pre_extraction"]["axial_sigma_mm"] <= acceptance["max_pre_extraction_axial_sigma_mm"], extraction_energy=bool(grouped["extraction_exit"]) and acceptance["minimum_extraction_mean_energy_ev"] <= m["extraction_exit"]["mean_kinetic_energy_ev"] <= acceptance["maximum_extraction_mean_energy_ev"])
    checks["lp_occupation"]=bool(lp) and len(lp)==len(grouped["pre_extraction"])
    summary=dict(schema_version=1,role="ion_processor_functional_summary",status="success" if all(checks.values()) else "failed",qualification="unqualified_simplified_native_electrodes",actual_particle_count=n,capture_fraction=len(hp)/n,extraction_fraction=len(grouped["extraction_exit"])/n,checks=checks,metrics=metrics,identity_validation=validation,terminal_reasons={reason:sum(r["terminal_reason"]==reason for r in grouped["terminal"]) for reason in sorted({r["terminal_reason"] for r in grouped["terminal"]})})
    if transformed:
        summary["frame_id"] = transform.to_frame_id
        summary["compression_axis"] = "native guide axis = project y"
        summary["canonical_column_semantics"] = {
            "radial_position_mm": "distance from project world z axis: hypot(world x, world y)",
            "divergence_angle_deg": "angle to project world z axis using absolute vz",
            "max_rod_radius_mm": "native local radial acceptance parameter; not a world-origin cylinder gate",
        }
        summary["native_acceptance_domain"] = {
            "frame_id": transform.from_frame_id,
            "guide_axis": "local x = project world y",
            "radial_rule_before_extraction": "abs(local y), abs(local z) <= boundary_radius_mm",
            "boundary_radius_mm": b["geometry"]["boundary_radius_mm"],
            "extraction_plane_local_y_mm": b["geometry"]["extraction_end_y_mm"],
        }
    summary["source_profile"] = profile
    summary["status"] = "success" if all(checks.values()) else "failed"
    summary["functional_status"] = profile + ("_pass" if all(checks.values()) else "_incomplete")
    summary["functional_baseline_eligible"] = profile == "functional"
    write_json(run / "summary.json",summary)
    # Legacy terminal runs remain immutable and have no new diagnostic contract.
    # For newly prepared runs these are required outputs; errors preserve the
    # measured physical summary and make execution incomplete at the runner.
    if (run / "inputs/diagnostics.json").is_file():
        from projects.dual_pressure_rectilinear_ion_processor.analysis.diagnostics import export_diagnostics
        export_diagnostics(run)
    if (run / "inputs/field_diagnostics.json").is_file():
        from projects.dual_pressure_rectilinear_ion_processor.analysis.field_diagnostics import export_field_diagnostics
        export_field_diagnostics(run)
    return summary


def main() -> None:
    """Single workflow boundary for preparation and solver-output analysis."""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("prepare","analyze","prepare-replay","finalize-replay","prepare-dispatch","materialize-batches","merge-batches","publish-manifest"))
    parser.add_argument("--run",required=True,type=Path)
    parser.add_argument("--simion-dir",type=Path)
    parser.add_argument("--baseline-run",type=Path)
    parser.add_argument("--manual-gui-confirmed",action="store_true")
    parser.add_argument("--repeat-fly-count",type=int,choices=(1,2),default=1)
    parser.add_argument("--native-field-run",type=Path)
    parser.add_argument("--batch-plan",type=Path)
    parser.add_argument("--status",choices=("success","failed"))
    parser.add_argument("--source-profile",choices=("functional","exploration"),default="functional")
    parser.add_argument("--configuration-directory",type=Path)
    args=parser.parse_args()
    if args.action=="prepare":
        if args.simion_dir is None: parser.error("prepare requires --simion-dir")
        prepare(args.run,Path(__file__).resolve().parent.parent,args.simion_dir,args.native_field_run,args.source_profile,
                args.configuration_directory)
    elif args.action in {"prepare-dispatch", "materialize-batches", "merge-batches", "publish-manifest"}:
        from projects.dual_pressure_rectilinear_ion_processor.analysis import batching
        if args.action == "publish-manifest":
            if args.status is None: parser.error("publish-manifest requires --status")
            batching.publish_manifest(args.run,args.status)
            print("RUN_MANIFEST=PASS")
        elif args.action == "prepare-dispatch":
            print(json.dumps(batching.prepare_request(args.run)))
        else:
            if args.batch_plan is None: parser.error("batch action requires --batch-plan")
            action = batching.materialize_batches if args.action == "materialize-batches" else batching.merge_batches
            print(json.dumps(action(args.run,args.batch_plan)))
    elif args.action=="analyze":
        result=analyze(args.run); print(json.dumps(result));
        if result["status"] != "success": raise SystemExit(2)
    elif args.action=="prepare-replay":
        from projects.dual_pressure_rectilinear_ion_processor.analysis.gui_replay import prepare_replay
        if args.baseline_run is None: parser.error("prepare-replay requires --baseline-run")
        print(json.dumps(prepare_replay(args.run,args.baseline_run,args.repeat_fly_count)))
    else:
        from projects.dual_pressure_rectilinear_ion_processor.analysis.gui_replay import finalize_replay
        result=finalize_replay(args.run,args.manual_gui_confirmed)
        config=read_json(args.run/"run_config.json")
        config["parameters"]["manual_gui_confirmed"]=args.manual_gui_confirmed
        write_json(args.run/"run_config.json",config)
        print(json.dumps(result))
        if result["measured_functional_status"] not in {"functional_pass","exploration_pass"}:
            raise SystemExit(2)


if __name__=="__main__":
    main()
