"""Thin installed command line over the same recipe, workflow and results APIs."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Sequence


def _add_rf_stationary_parser(root_commands):
    parser = root_commands.add_parser("rf-stationary", help="prepare and compare RF stationary fields")
    commands = parser.add_subparsers(dest="stationary_command", required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("--resolved-design", type=Path, required=True)
    generate.add_argument("--sampling-plan", type=Path, required=True)
    generate.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--input", type=Path, required=True)
    validate.add_argument("--output", type=Path, required=True)
    validate.add_argument("--authority", type=Path)
    authorize = commands.add_parser("authorize")
    authorize.add_argument("--resolved-design", type=Path, required=True)
    authorize.add_argument("--sampling-plan", type=Path, required=True)
    authorize.add_argument("--points", type=Path, required=True)
    authorize.add_argument("--source-id", required=True)
    authorize.add_argument("--output", type=Path, required=True)
    comparison = commands.add_parser("comparison-authority")
    comparison.add_argument("--reference-authority", type=Path, required=True)
    comparison.add_argument("--candidate-authority", type=Path, required=True)
    comparison.add_argument("--coordinate-tolerance-mm", type=float, required=True)
    comparison.add_argument("--output", type=Path, required=True)
    compare = commands.add_parser("compare")
    compare.add_argument("--reference", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)
    compare.add_argument("--comparison-authority", type=Path)
    for name in ("solve-comsol", "saved-comsol", "simion-sample"):
        command = commands.add_parser(name)
        command.add_argument("--budget", type=Path, required=True)
        command.add_argument("--run-id", required=True)
        command.add_argument("--source-id", required=True)
        command.add_argument("--workspace", type=Path, required=True)
        command.add_argument("--python", type=Path, required=True)
        command.add_argument("--powershell", type=Path, required=True)
        command.add_argument("--host-state", type=Path, required=True)
        command.add_argument("--policy", type=Path, required=True)
        if name in {"solve-comsol", "saved-comsol"}:
            command.add_argument("--artifact-root", type=Path, required=True)
            if name == "solve-comsol":
                command.add_argument("--resolved-runtime", type=Path, required=True)
                command.add_argument("--preregistration", type=Path, required=True)
                command.add_argument("--science-task", type=Path, required=True)
            else:
                command.add_argument("--parent-manifest", type=Path, required=True)
            command.add_argument("--sampling-plan", type=Path, required=True)
            command.add_argument("--comsol-launcher", type=Path, required=True)
            command.add_argument("--matlab-root", type=Path, required=True)
        else:
            command.add_argument("--artifact-root", type=Path, required=True)
            command.add_argument("--request", type=Path, required=True)
            command.add_argument("--simion", type=Path, required=True)
    return parser


def _report_native_stage_result(output):
    """Report the actual stage status without turning a failed producer green."""
    print(json.dumps(output, ensure_ascii=False, allow_nan=False, indent=2))
    status = output.get("status")
    if status not in {"success", "failed", "cancelled", "interrupted"}:
        raise ValueError("native stage returned an unsupported execution status")
    return 0 if status == "success" else 1


def _run_rf_stationary(arguments):
    from msplatform.workflows import rf_stationary as stationary
    if arguments.stationary_command == 'generate':
        rows = stationary.sampling.generate_stationary_field_sample_rows(stationary._json(arguments.resolved_design), stationary._json(arguments.sampling_plan))
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        stationary.sampling.write_stationary_field_sample_csv(rows, arguments.output)
        return 0
    if arguments.stationary_command == 'validate':
        if arguments.authority is not None:
            stationary.sampling.validate_stationary_output_authority(stationary._json(arguments.authority), arguments.input)
        stationary._validation_document(arguments.authority, arguments.input, arguments.output) if arguments.authority else None
        if arguments.authority is None:
            records = stationary.sampling.load_stationary_field_output_csv(arguments.input)
            stationary.write_json_atomic(arguments.output, dict(schema_version=1, role='multipole_stationary_field_sample_validation', status='PASS', field_cases=list(stationary.sampling.FIELD_CASES), point_count=len({row.sample_id for row in records}), row_count=len(records)))
        return 0
    if arguments.stationary_command == 'authorize':
        with arguments.points.open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != stationary.sampling.SAMPLE_COLUMNS:
                raise stationary.sampling.StationaryFieldContractError('stationary point columns differ')
            points = list(reader)
        authority = stationary.sampling.build_stationary_sampling_authority(stationary._json(arguments.resolved_design), stationary._json(arguments.sampling_plan), points, points_path=arguments.points, source_id=arguments.source_id)
        stationary.write_json_atomic(arguments.output, authority)
        return 0
    if arguments.stationary_command == 'comparison-authority':
        authority = stationary.sampling.build_multipole_comparison_authority(stationary._json(arguments.reference_authority), stationary._json(arguments.candidate_authority), coordinate_tolerance_mm=arguments.coordinate_tolerance_mm)
        stationary.write_json_atomic(arguments.output, authority)
        return 0
    if arguments.stationary_command == 'compare':
        if arguments.comparison_authority is not None:
            stationary._compare_generic(arguments)
        else:
            comparison = stationary.sampling.compare_stationary_field_outputs(stationary.sampling.load_stationary_field_output_csv(arguments.reference), stationary.sampling.load_stationary_field_output_csv(arguments.candidate))
            stationary.write_json_atomic(arguments.output, comparison)
        return 0
    if arguments.stationary_command == 'solve-comsol':
        from msplatform.storage.store import ArtifactStore
        context = stationary._context(arguments, tools=dict(comsol_launcher=arguments.comsol_launcher.absolute(), matlab_root=arguments.matlab_root.absolute()))
        return _report_native_stage_result(stationary.solve_comsol(resolved_runtime=arguments.resolved_runtime, preregistration=arguments.preregistration, science_task=arguments.science_task, sampling_plan=arguments.sampling_plan, budget=arguments.budget, run_id=arguments.run_id, source_id=arguments.source_id, context=context, artifact_store=ArtifactStore(arguments.artifact_root)))
    if arguments.stationary_command == 'saved-comsol':
        from msplatform.storage.store import ArtifactStore
        context = stationary._context(arguments, tools=dict(comsol_launcher=arguments.comsol_launcher.absolute(), matlab_root=arguments.matlab_root.absolute()))
        return _report_native_stage_result(stationary.saved_comsol(parent_manifest=arguments.parent_manifest, sampling_plan=arguments.sampling_plan, budget=arguments.budget, run_id=arguments.run_id, source_id=arguments.source_id, context=context, artifact_store=ArtifactStore(arguments.artifact_root)))
    if arguments.stationary_command == 'simion-sample':
        from msplatform.storage.store import ArtifactStore
        context = stationary._context(arguments, tools=dict(simion=arguments.simion.absolute()))
        return _report_native_stage_result(stationary.simion_samples(request_path=arguments.request, budget=arguments.budget, run_id=arguments.run_id, source_id=arguments.source_id, context=context, artifact_store=ArtifactStore(arguments.artifact_root)))
    raise AssertionError(arguments.stationary_command)


def _add_rf_filter_research_parser(commands):
    parser = commands.add_parser("rf-filter-research", help="run or reanalyze the RF mass-filter study")
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--resolved-design', type=Path)
    parser.add_argument('--mode', type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--run-id')
    parser.add_argument('--check-contract', action='store_true')
    parser.add_argument('--resume-finalization', action='store_true')
    parser.add_argument('--analyze-only', action='store_true')
    parser.add_argument('--parent-manifest', type=Path)
    parser.add_argument('--asset-id')
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--execution-environment', type=Path)
    parser.add_argument('--engineering-profile')
    parser.add_argument('--artifact-root', type=Path)
    return parser


def _run_rf_filter_research(args, parser):
    from msplatform.workflows.rf_mass_filter import research
    if args.resume_finalization and args.analyze_only:
        parser.error('--resume-finalization cannot be combined with --analyze-only')
    if args.resume_finalization:
        if not args.asset_id:
            parser.error('--resume-finalization requires --asset-id')
        if args.check_contract or args.parent_manifest is not None or any((value is not None for value in (args.baseline, args.resolved_design, args.mode, args.source))):
            parser.error('--resume-finalization does not accept scientific inputs or --check-contract')
    elif args.analyze_only:
        if args.check_contract or args.asset_id is not None or args.parent_manifest is None or any((value is not None for value in (args.baseline, args.resolved_design, args.mode, args.source))):
            parser.error('--analyze-only requires --parent-manifest and no scientific, contract or Result options')
    else:
        if args.asset_id is not None or args.parent_manifest is not None:
            parser.error('--asset-id and --parent-manifest require their explicit recovery/analysis modes')
        args.baseline = args.baseline or research.DEFAULT_BASELINE
        args.resolved_design = args.resolved_design or research.DEFAULT_RESOLVED
        args.mode = args.mode or research.DEFAULT_MODE
        args.source = args.source or research.DEFAULT_SOURCE
    if args.check_contract:
        research.finite_length.validate_l1_contract(research.load_json(args.baseline), research.load_json(args.mode), research.load_json(args.source))
        print('QUADRUPOLE_MASS_FILTER_L1_CONTRACT=PASS')
        return 0
    if not args.run_id or args.workspace is None or args.execution_environment is None or (not args.engineering_profile) or (args.artifact_root is None):
        parser.error('execution requires --run-id, --workspace, --artifact-root, --execution-environment and --engineering-profile')
    from msplatform.execution.context import load_environment
    context = load_environment(args.execution_environment, workspace=args.workspace, profile=args.engineering_profile)
    from msplatform.storage.store import ArtifactStore
    store = ArtifactStore(args.artifact_root)
    if args.resume_finalization:
        result = research.resume(args.run_id, args.asset_id, context=context, artifact_store=store)
        print(f"QUADRUPOLE_MASS_FILTER_L1_FINALIZATION={result['status'].upper()} RUN={Path(result['run_directory']).name}")
        if result['status'] not in {'ready', 'failed'}:
            raise ValueError('research recovery returned a nonterminal Store state')
        return 0 if result['status'] == 'ready' else 1
    if args.analyze_only:
        destination = research.analyze(args.parent_manifest, args.run_id, context=context, artifact_store=store)
        print(f'QUADRUPOLE_MASS_FILTER_L1_ANALYSIS=PASS RUN={destination.name}')
        return 0
    destination = research.run(args.baseline, args.resolved_design, args.mode, args.source, args.run_id, context=context, artifact_store=store)
    print(f'QUADRUPOLE_MASS_FILTER_L1=PASS RUN={destination.name}')
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the single installed CLI and its actual capability subcommands."""
    parser = argparse.ArgumentParser(prog="msplatform")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="resolve SI inputs and check supported capabilities")
    validate.add_argument("recipe")
    validate.add_argument("--artifact-root", help="Store holding explicitly referenced native evidence")
    run = commands.add_parser("run", help="trace a recipe and publish complete evidence")
    run.add_argument("recipe")
    run.add_argument("--artifact-root", required=True)
    run.add_argument("--source-revision", help="explicit repository SHA for provenance; never a cache invalidation key")
    for name in ("high-water-bytes", "low-water-bytes"):
        run.add_argument("--" + name, type=int)
    run.add_argument("--safety-bytes", type=int, default=0)
    run.add_argument("--reserve-bytes", type=int, default=0)
    run.add_argument("--tracking-execution", type=Path,
                     help="explicit JSON engineering controls for supported native tracking")
    for command in (validate, run):
        command.add_argument("--execution-environment", help="explicit native machine deployment JSON")
        command.add_argument("--profile", help="named native engineering profile")
        command.add_argument("--workspace", help="existing native execution owner's workspace")
    results = commands.add_parser("results").add_subparsers(dest="results_command", required=True)
    inspect = results.add_parser("inspect", help="verify and recompute statistics from published data")
    inspect.add_argument("run_id")
    inspect.add_argument("--artifact-root", required=True)
    gc = commands.add_parser("gc", help="collect only policy-eligible unprotected caches")
    gc.add_argument("--artifact-root", required=True)
    gc.add_argument("--target-bytes", type=int, default=0)
    _add_rf_stationary_parser(commands)
    _add_rf_filter_research_parser(commands)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one explicit public capability through the single CLI."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "rf-stationary":
            return _run_rf_stationary(args)
        if args.command == "rf-filter-research":
            return _run_rf_filter_research(args, parser)
        context = None
        if args.command in {"validate", "run"}:
            selected = (args.execution_environment, args.profile, args.workspace)
            if any(selected):
                if not all(selected):
                    raise ValueError("native deployment requires execution-environment, profile and workspace together")
                from msplatform.execution.context import load_environment
                context = load_environment(args.execution_environment, workspace=args.workspace, profile=args.profile)
        if args.command == "validate":
            from msplatform.recipes import load_recipe
            from msplatform.tracing import preflight
            output = load_recipe(args.recipe).to_dict()
            if output["schema_version"] == 2:
                from msplatform.workflows.native_tracing import preflight_native
                from msplatform.storage import ArtifactStore
                store = ArtifactStore(args.artifact_root) if args.artifact_root else None
                output = {"resolved": output, "capabilities": preflight_native(
                    output, context=context, artifact_store=store)}
            else:
                if context is not None:
                    raise ValueError("reference validation does not consume a native deployment")
                preflight(output)
        elif args.command == "run":
            from msplatform.workflows.tracing import run_recipe
            controls = {}
            if args.tracking_execution is not None:
                from msplatform.io.strict_json import load_json_object
                controls["tracking_execution"] = load_json_object(args.tracking_execution)
            output = run_recipe(args.recipe, artifact_root=args.artifact_root,
                                high_water_bytes=args.high_water_bytes, low_water_bytes=args.low_water_bytes,
                                safety_bytes=args.safety_bytes, reserve_bytes=args.reserve_bytes,
                                source_revision=args.source_revision, context=context, **controls)
        elif args.command == "results":
            from msplatform.workflows.tracing import inspect_results
            output = inspect_results(args.run_id, artifact_root=args.artifact_root)
        else:
            from msplatform.storage import ArtifactStore
            output = ArtifactStore(args.artifact_root).collect(target_bytes=args.target_bytes)
        print(json.dumps(output, ensure_ascii=False, allow_nan=False, indent=2))
        status = (output.get("summary") or {}).get("execution_status") if isinstance(output, dict) else None
        return 1 if status in {"failed", "cancelled", "interrupted"} else 0
    except (ValueError, OSError, RuntimeError, KeyError) as error:
        parser.exit(2, f"msplatform: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
