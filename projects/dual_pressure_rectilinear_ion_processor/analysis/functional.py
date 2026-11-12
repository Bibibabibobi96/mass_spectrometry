"""Freeze and analyze the abstract SIMION Ion Processor functional workflow.

Positions are mm, velocities m/s at the public boundary, and time is us.
New runs publish the declared project XYZ frame; legacy frozen runs retain
their original x-directed canonical mapping. No particle is resampled between the guide and extraction.
"""
from __future__ import annotations

import argparse
import json
import sys
import subprocess
from pathlib import Path
from typing import Any

from msplatform.execution.retention import classify_file
from msplatform.execution.inputs import enumerate_python_sources, freeze_file
from msplatform.backends.simion.workbench_seed import freeze_workbench_seed
from msplatform.workflows.ion_processor import preparation
from msplatform.workflows.ion_processor import field_reference
from msplatform.backends.simion.ip_handoff import (
    load_injected_source,
)

from msplatform.components.dual_pressure_rectilinear_ion_processor.coordinates import (
    transform_from_config,
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
    seed = freeze_workbench_seed(run, seed_path=repo / "src/msplatform/backends/simion/resources/1_instance_seed.iob",
        placeholder_path=repo / "common/simion/assets/iob_instance_seeds/iob_seed_placeholder_01.pa0")
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
    from msplatform.workflows.ion_processor import diagnostics, field_diagnostics
    assert callable(diagnostics.export_diagnostics)
    assert callable(field_diagnostics.export_field_diagnostics)
    from projects.dual_pressure_rectilinear_ion_processor.analysis import batching
    from msplatform.workflows.ion_processor import extraction_force_budget
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
        from msplatform.workflows.ion_processor.analysis import analyze
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
