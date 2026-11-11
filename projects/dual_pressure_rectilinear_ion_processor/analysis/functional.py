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
import statistics
import sys
import subprocess
from pathlib import Path
from typing import Any

from msplatform.execution.retention import classify_file
from msplatform.execution.inputs import enumerate_python_sources, freeze_file
from common.simion.workbench_seed import freeze_workbench_seed
from msplatform.contracts.particle_physics import kinetic_energy_ev
from projects.rf_multipole_ion_optics.analysis.rf_event_table_validation import PARTICLE_STATE_COLUMNS, ENUMS, validate_rf_event_table
from msplatform.workflows.ion_processor import preparation
from msplatform.workflows.ion_processor import field_reference
from msplatform.components.dual_pressure_rectilinear_ion_processor.timing import derive_native_timing
from msplatform.backends.simion.ip_handoff import (
    load_injected_source, frozen_release_states,
)

from msplatform.components.dual_pressure_rectilinear_ion_processor.coordinates import (
    transform_from_config, to_project_position, to_project_vector,
    to_local_position, to_local_vector,
)

# Installed scientific dependencies required by this package and its shared consumers.
# Freeze their canonical source bytes; the legacy constant name does not denote aliases.
FROZEN_SCIENTIFIC_BRIDGE_MODULES = (
    "src/msplatform/contracts/particle_physics.py",
    "src/msplatform/ion_release/release.py",
)
# Actual runtime dependencies, independent of incidental imports in the author process.
FROZEN_RUNTIME_MODULES = (
    "src/msplatform/execution/simion_dispatch.py",
    "common/simion/resource_profile.py",
    "src/msplatform/backends/simion/particle_batching.py",
)
PROJECT = "dual_pressure_rectilinear_ion_processor"
EVENTS = ["source", "hp_enter", "capture", "transfer", "pre_extraction", "extraction_exit", "terminal"]


def read_json(path: Path) -> dict[str, Any]:
    """Read one versioned UTF-8 JSON object."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    """Write reproducible, finite JSON using LF."""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")









def prepare(run: Path, project: Path, simion_dir: Path, native_field_run: Path | None = None,
            source_profile: str = "functional", configuration_directory: Path | None = None,
            injected_source: Path | None = None, protected_injected_paths: list[Path] | None = None) -> None:
    """Freeze contracts, official HS1, RF kernel and shared release for one run."""
    repo = project.parent.parent
    configuration = configuration_directory.resolve() if configuration_directory is not None else project / "config"
    inputs, solver = run / "inputs", run / "simion"
    if source_profile not in {"functional", "exploration"}:
        raise ValueError("source_profile must be functional or exploration")
    config_files = {name: f"{name}.json" for name in
                    ("baseline", "numerics", "source", "acceptance", "native_operating_point", "diagnostics", "field_diagnostics")}
    config_files["source"] = "source_exploration.json" if source_profile == "exploration" else "source.json"
    # Dynamic language inputs belong to the same runnable frozen package as Python.
    runtime_resources = [repo / "src/msplatform/backends/simion/resources" / ("ip_" + name) for name in
        ("runtime.lua", "build_workbench.lua", "probe_native_field.lua", "extraction_force_audit.lua")]
    runtime_resources.extend(repo / relative for relative in (
        "src/msplatform/execution/resources/artifact_retention.json",
        "src/msplatform/contracts/particle_count_policy.json", "src/msplatform/execution/resources/host_resource_policy.json",
        "src/msplatform/backends/simion/resources/rf_drive.lua", "src/msplatform/backends/simion/resources/voltage_waveforms.lua",
        "src/msplatform/backends/simion/resources/native_drive.lua",
        "src/msplatform/backends/simion/resources/scientific_event_csv.lua",
        "src/msplatform/backends/simion/resources/collision_hs1_gas.lua",
        "src/msplatform/backends/simion/resources/1_instance_seed.iob",
        "common/simion/assets/iob_instance_seeds/iob_seed_placeholder_01.pa0"))
    runtime_resources.append(repo / "src/msplatform/execution/resources/native_run_path.lua")
    core_sources = [repo / relative for relative in enumerate_python_sources(
        repo, package_roots=("src/msplatform",), provider_root="src/msplatform",
        resource_suffixes=(".schema.json",))]
    runtime_resources.extend(path for path in core_sources if path.suffix != ".py")
    required_resources = [*runtime_resources, *(configuration / name for name in config_files.values()),
        simion_dir / "examples/collision_hs1/collision_hs1.lua"]
    missing = [str(path) for path in required_resources if not path.is_file()]
    if missing:
        raise ValueError("IP prepare required resource is missing: " + "; ".join(missing))
    config = {name: read_json(configuration / filename) for name, filename in config_files.items()}
    if (configuration / "coordinate_transform.json").is_file():
        config_files["coordinate_transform"] = "coordinate_transform.json"
        config["coordinate_transform"] = read_json(configuration / "coordinate_transform.json")
    elif configuration_directory is not None:
        raise ValueError("external configuration directory requires its explicit coordinate transform")
    selected_config_files = dict(config_files)
    config["source_profile"] = source_profile
    config["source_authority_file"] = config_files["source"]
    if injected_source is not None and protected_injected_paths is not None:
        from msplatform.backends.simion.ip_handoff import injected_source_protection_paths
        if set(injected_source_protection_paths(injected_source)) != {Path(path).resolve() for path in protected_injected_paths}:
            raise ValueError("injected source protection authorities changed after admission")
    admission = load_injected_source(injected_source) if injected_source is not None else None
    if injected_source is not None and protected_injected_paths is not None:
        if set(injected_source_protection_paths(injected_source)) != {Path(path).resolve() for path in protected_injected_paths}:
            raise ValueError("injected source protection authorities changed while freezing")
    authorities = {name: configuration / filename for name, filename in config_files.items()}
    authorities.update({name: configuration / (name + ".json") for name in
                       ("geometry_sources", "source_parameter_sources", "component_matching_derivation")
                       if (configuration / (name + ".json")).is_file()})
    compiled = preparation.materialize_inputs(run, config, configuration_files=authorities,
        hs1_source=simion_dir / "examples/collision_hs1/collision_hs1.lua", admission=admission)
    config, states = compiled["config"], compiled["states"]
    git_context = {}
    for key, arguments in (("git_sha", ["rev-parse", "HEAD"]), ("worktree_porcelain", ["status", "--porcelain"])):
        result = subprocess.run(["git", "-C", str(repo), *arguments], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", check=False,
                                cwd=repo, timeout=10)
        git_context[key] = result.stdout.strip() if result.returncode == 0 else "unavailable"
    git_context["worktree_dirty"] = bool(git_context["worktree_porcelain"])
    write_json(inputs / "source_context.json", git_context)
    seed = freeze_workbench_seed(run, repo)
    config["workbench_seed_path"] = seed["seed"]["frozen"]["path"]
    config["workbench_seed_records"] = seed
    config["native_field"]={"directory":str(solver),"source_manifest":None}
    external_inputs={}
    if native_field_run is not None:
        external_inputs = field_reference.bind_native_field(run, config, native_field_run)
    (solver / "frozen_config.lua").write_text("return " + preparation.lua_literal(config) + "\n", encoding="utf-8")
    write_json(inputs / "resolved_model.json", config)
    # These genuine downstream producers must join the root workflow snapshot;
    # scientific input compilation itself does not import plotting modules.
    from projects.dual_pressure_rectilinear_ion_processor.analysis import diagnostics, field_diagnostics
    assert callable(diagnostics.export_diagnostics)
    assert callable(field_diagnostics.export_field_diagnostics)
    from projects.dual_pressure_rectilinear_ion_processor.analysis import batching
    from projects.dual_pressure_rectilinear_ion_processor.analysis import extraction_force_budget
    from msplatform.analysis.population_moments import population_pair_moments
    from msplatform.analysis.beam_focus_diagnostics import prepare_focus_diagnostics
    from msplatform.io.figure_export import export_figures
    from msplatform.analysis.plane_crossings import iter_bounded_plane_crossings
    from msplatform.analysis.particle_census import partition_cohort
    assert batching.resource_profile.PROFILE_ROLE == "simion_resource_profile"
    assert callable(extraction_force_budget.export_force_budget)
    assert callable(population_pair_moments)
    assert callable(prepare_focus_diagnostics)
    assert callable(export_figures)
    assert callable(iter_bounded_plane_crossings)
    assert callable(partition_cohort)
    # Freeze the loaded repository source closure after shared source generation.
    # Solver inputs remain independent of an editable working tree.
    source_paths = {path for path in core_sources if path.suffix == ".py"}
    source_paths.update(repo / relative for relative in enumerate_python_sources(
        repo, module_paths=(*FROZEN_SCIENTIFIC_BRIDGE_MODULES, *FROZEN_RUNTIME_MODULES)))
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
        if (path.name.startswith("test_") or path.name.endswith("_test.py")
                or {"test_support", "testing_support"}.intersection(relative.parts)):
            continue
        source_paths.add(path)
    # A module can have several import names; freeze each physical source once.
    for path in sorted(source_paths):
        relative = path.relative_to(repo)
        target=inputs/"code"/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        freeze_file(path,target)
    for source in runtime_resources:
        target = inputs / "code" / source.relative_to(repo)
        target.parent.mkdir(parents=True, exist_ok=True)
        freeze_file(source, target, retention_classifier=classify_file)
    # Preserve the selected author inputs at the package's normal project location.
    # An external candidate remains the authority; current repository defaults never fill it.
    configuration_resources = [configuration / name for name in selected_config_files.values()]
    configuration_resources.extend(configuration / (name + ".json") for name in
        ("geometry_sources", "source_parameter_sources", "component_matching_derivation")
        if (configuration / (name + ".json")).is_file())
    for source in configuration_resources:
        target = inputs / "code" / project.relative_to(repo) / "config" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        freeze_file(source, target)
    run_config = read_json(run / "run_config.json")
    run_config["inputs"] = {str(p.relative_to(run)).replace("/", "_"): str(p) for folder in (inputs, solver) for p in folder.rglob("*") if p.is_file()}
    run_config["inputs"].update(external_inputs)
    run_config["inputs"]["public_workbench_seed"]=config["workbench_seed_path"]
    run_config["parameters"] = dict(workflow="native_electrode_functional", actual_particle_count=len(states), qualification="unqualified_simplified_electrodes", canonical_state_frame="axial_z=x; transverse_x=z; transverse_y=y", clock_epoch_id="ion_processor_epoch_zero_v1", collision_model="official_SIMION_2020_HS1", rf_amplitude_convention="per_electrode_peak_to_peak_divided_by_two", source_handoff="same_cohort_no_reset", space_charge_enabled=False)
    if "coordinate_transform" in config:
        run_config["parameters"]["canonical_state_frame"] = transform_from_config(config).to_frame_id
        run_config["parameters"]["native_geometry_frame"] = transform_from_config(config).from_frame_id
    run_config["parameters"].update(source_profile=config["source_profile"], source_authority_file=config["source_authority_file"],
                                    configuration_directory=str(configuration.resolve()))
    if admission is not None:
        run_config["parameters"].update(clock_epoch_id=admission["clock"]["clock_epoch_id"],
            mother_particle_count=admission["census"]["mother_count"],
            source_handoff="real_mechanical_exit__original_birth_and_absolute_arrival_preserved")
    write_json(run / "run_config.json", run_config)


def analyze(run: Path) -> dict[str, Any]:
    """Validate all identities and publish measured functional acceptance."""
    c = read_json(run / "inputs/resolved_model.json")
    profile = preparation.validate_source_profile(c)
    transform = transform_from_config(c)
    transformed = "coordinate_transform" in c
    b, acceptance = c["baseline"], c["acceptance"]
    sources = frozen_release_states(run, c)
    source_by_id = {row["particle_id"]: row for row in sources}
    if not sources and "injected_source" in c:
        with (run/"results/particle_state.csv").open("w", encoding="utf-8", newline="") as stream:
            csv.DictWriter(stream, fieldnames=PARTICLE_STATE_COLUMNS).writeheader()
        census = read_json(run/"inputs/upstream_mother_census.json")
        summary = dict(schema_version=1, role="ion_processor_functional_summary", status="success",
            source_profile="upstream", actual_particle_count=0, mother_particle_count=census["mother_count"],
            qualification="empty_upstream_admission__no_IP_flight", solver_executed=False,
            functional_baseline_eligible=False, functional_status="upstream_empty",
            upstream_census=census, identity_validation=dict(status="PASS", particles=0))
        write_json(run/"summary.json", summary)
        return summary
    from msplatform.results.ip_continuation import native_data_directory
    with (native_data_directory(run) / "events.csv").open(encoding="utf-8", newline="") as f:
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
        if event["reason"] in {"downstream_domain_exit", "backward_escape"}:
            downstream = event["reason"] == "downstream_domain_exit"
            direction = "downstream" if downstream else "upstream"
            if event["event"] != "terminal":
                raise ValueError(f"{direction} domain exit must be a terminal event")
            boundaries = c.get("numerical_boundaries")
            try:
                preparation.validate_numerical_boundaries(boundaries or {}, c["native_projection"])
            except ValueError:
                raise ValueError(f"{direction} domain exit lacks its derived numerical boundary")
            position = to_local_position(c, [float(event[k]) for k in ("x_mm", "y_mm", "z_mm")])
            velocity = to_local_vector(c, [float(event[k]) for k in ("vx_mm_us", "vy_mm_us", "vz_mm_us")])
            plane = boundaries["downstream_exit_x_mm" if downstream else "upstream_exit_x_mm"]
            if abs(position[0] - plane) > 1e-9 or (velocity[0] <= 0 if downstream else velocity[0] >= 0):
                raise ValueError(f"{direction} domain exit is outside its plane/direction")
        if event["event"]=="extraction_exit":
            local_position = to_local_position(c, [float(event[k]) for k in ("x_mm", "y_mm", "z_mm")])
            local_velocity = to_local_vector(c, [float(event[k]) for k in ("vx_mm_us", "vy_mm_us", "vz_mm_us")])
            if t<timing["primary_quench_us"] or abs(local_position[1]-b["geometry"]["extraction_end_y_mm"])>1e-9 or local_velocity[1]<=0:
                raise ValueError("extraction event is outside its acceptance plane/clock/direction")
    # Canonical lifecycle is separate from the recorded stop reason and from
    # this owner's acceptance/counting rules. A time budget is not physical loss.
    status_by_reason = {
        "none": "alive", "acceptance_surface": "transmitted", "timeout": "timeout",
        "acceptance_radius": "lost", "acceptance_aperture": "lost", "electrode": "lost",
        "radial_escape": "lost", "backward_escape": "lost", "downstream_domain_exit": "lost",
    }
    rows = []
    local_guide_positions = {}
    for r in raw:
        if int(r["particle_id"]) not in source_by_id:
            raise AssertionError("particle IDs do not match the input table")
        source = source_by_id[int(r["particle_id"])]
        mass = source["mass_amu"]
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
        rows.append(dict(zip(PARTICLE_STATE_COLUMNS, [int(r["particle_id"]),event,status_by_reason.get(reason, "unknown"),reason,t,t-source["birth_time_s"]*1e6,(2*math.pi*b["electric"]["rf_frequency_hz"]*t*1e-6+b["clock"]["rf_phase_rad"])%(2*math.pi),*position,*(v*1000 for v in velocity),kinetic_energy_ev(mass,vx*1000,vy*1000,vz*1000),radius,divergence,b["geometry"]["boundary_radius_mm"]])))
    output = run / "results/particle_state.csv"
    with output.open("w", encoding="utf-8", newline="") as f:
        writer=csv.DictWriter(f,fieldnames=PARTICLE_STATE_COLUMNS); writer.writeheader(); writer.writerows(rows)
    expected = {}
    for source in sources:
        arrival = source["arrival_time_us"] if "injected_source" in c else 0
        x, y, z = to_project_position(c, [source[k] for k in ("x_mm", "y_mm", "z_mm")])
        vx, vy, vz = to_project_vector(c, [source[k] for k in ("vx_m_s", "vy_m_s", "vz_m_s")])
        position = (z, x, y) if transformed else (x, z, y)
        velocity = (vz, vx, vy) if transformed else (vx, vz, vy)
        expected[source["particle_id"]] = dict(zip(
            ("time_us", "elapsed_time_us", "axial_z_mm", "transverse_x_mm", "transverse_y_mm",
             "velocity_axial_m_s", "velocity_x_m_s", "velocity_y_m_s", "kinetic_energy_eV"),
            (arrival, arrival-source["birth_time_s"]*1e6, *position, *velocity, kinetic_energy_ev(source["mass_amu"], vx, vy, vz))))
    validation = validate_rf_event_table(output,expected,b["electric"]["rf_frequency_hz"],b["clock"]["rf_phase_rad"],enums={**ENUMS,"event":EVENTS,"terminal_reason":[*ENUMS["terminal_reason"],"downstream_domain_exit"]})
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
    if "injected_source" in c:
        summary.update(mother_particle_count=c["injected_source"]["mother_particle_count"],
            upstream_census=read_json(run/"inputs/upstream_mother_census.json"),
            claim="measured IP continuation of real upstream mechanical exits; state_handoff, not joint field solve")
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
    # New native runs always provide passive per-step force/collision evidence.
    # Historical sealed runs keep their own frozen analysis implementation.
    if "extraction_force_audit" in c:
        from projects.dual_pressure_rectilinear_ion_processor.analysis.extraction_force_budget import export_force_budget
        export_force_budget(run)
    return summary


def main() -> None:
    """Single workflow boundary for preparation and solver-output analysis."""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("prepare","adopt-native-field","analyze","prepare-replay","finalize-replay","prepare-dispatch","prepare-continuation","prepare-partial-continuation","restore-partial-batches","materialize-batches","merge-batches","publish-manifest","compare-extraction-study","compare-geometry-study"))
    parser.add_argument("--run",required=True,type=Path)
    parser.add_argument("--simion-dir",type=Path)
    parser.add_argument("--baseline-run",type=Path)
    parser.add_argument("--manual-gui-confirmed",action="store_true")
    parser.add_argument("--repeat-fly-count",type=int,choices=(1,2),default=1)
    parser.add_argument("--native-field-run",type=Path)
    parser.add_argument("--batch-plan",type=Path)
    parser.add_argument("--native-pa0-record",type=json.loads,help=argparse.SUPPRESS)
    parser.add_argument("--status",choices=("success","failed"))
    parser.add_argument("--source-profile",choices=("functional","exploration"),default="functional")
    parser.add_argument("--configuration-directory",type=Path)
    parser.add_argument("--injected-source",type=Path)
    parser.add_argument("--protected-injected-path",type=Path,action="append")
    args=parser.parse_args()
    if args.action=="compare-geometry-study":
        from projects.dual_pressure_rectilinear_ion_processor.analysis.geometry_comparison import analyze_geometry_study
        print(json.dumps(analyze_geometry_study(args.run)))
    elif args.action=="compare-extraction-study":
        from projects.dual_pressure_rectilinear_ion_processor.analysis.extraction_phase_space_comparison import analyze_registered_study
        result=analyze_registered_study(args.run)
        print(json.dumps({key:result[key] for key in ("status","source_counts","extracted_counts")}))
    elif args.action=="prepare":
        if args.simion_dir is None: parser.error("prepare requires --simion-dir")
        prepare(args.run,Path(__file__).resolve().parent.parent,args.simion_dir,args.native_field_run,args.source_profile,
                args.configuration_directory,args.injected_source,args.protected_injected_path)
    elif args.action=="adopt-native-field":
        if args.native_field_run is None: parser.error("adopt-native-field requires --native-field-run")
        field_reference.adopt_native_field(args.run, args.native_field_run)
    elif args.action in {"prepare-dispatch", "prepare-continuation", "prepare-partial-continuation", "restore-partial-batches", "materialize-batches", "merge-batches", "publish-manifest"}:
        from projects.dual_pressure_rectilinear_ion_processor.analysis import batching
        if args.action == "publish-manifest":
            if args.status is None: parser.error("publish-manifest requires --status")
            batching.publish_manifest(args.run,args.status)
            print("RUN_MANIFEST=PASS")
        elif args.action == "prepare-continuation":
            if args.baseline_run is None: parser.error("prepare-continuation requires --baseline-run")
            print(json.dumps(batching.prepare_completed_reanalysis(args.run, args.baseline_run)))
        elif args.action == "prepare-partial-continuation":
            if args.baseline_run is None: parser.error("prepare-partial-continuation requires --baseline-run")
            print(json.dumps(batching.prepare_partial_batch_replay(args.run, args.baseline_run)))
        elif args.action == "restore-partial-batches":
            print(json.dumps(batching.restore_reusable_batches(args.run)))
        elif args.action == "prepare-dispatch":
            print(json.dumps(batching.prepare_request(args.run,args.native_pa0_record)))
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
