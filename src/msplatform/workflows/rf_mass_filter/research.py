"""Select explicit research inputs for the installed ideal-field L1 workflow.

The named project inputs retain their existing science. Execution requires an
explicit saved deployment/profile and a managed research workspace; the installed
workflow owns freezing, observed processes and terminal publication.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from msplatform.execution.resources.workspace_paths import resolve_run_artifact_root
from msplatform.workflows.rf_mass_filter import finite_length

PROJECT_ROOT = Path(__file__).resolve().parents[2] / "components" / "rf_multipole"
DEFAULT_BASELINE = PROJECT_ROOT / 'variants/quadrupole/config/baseline.json'
DEFAULT_RESOLVED = PROJECT_ROOT / 'variants/quadrupole/config/resolved_design_mass_filter.json'
DEFAULT_MODE = PROJECT_ROOT / 'config/modes/quadrupole_mass_filter_reference.json'
DEFAULT_SOURCE = PROJECT_ROOT / 'variants/quadrupole/config/official_particle_source.json'


def load_json(path: Path) -> dict:
    """Load one explicitly selected research input without execution."""
    return json.loads(path.read_text(encoding='utf-8-sig'))


def run(baseline_path: Path, resolved_path: Path, mode_path: Path, source_path: Path,
        run_id: str, artifact_project_root: Path | None = None, *, context) -> Path:
    """Delegate to the sole managed workflow with the caller's actual context."""
    result = finite_length.run(context, baseline_path=baseline_path, resolved_path=resolved_path,
        mode_path=mode_path, source_path=source_path, run_id=run_id, artifact_project_root=artifact_project_root)
    return Path(result['run_directory'])


def analyze(parent_manifest_path: Path, run_id: str, artifact_project_root: Path | None = None, *, context) -> Path:
    """Create a managed analysis-only child from an explicit sealed parent."""
    result = finite_length.analyze(context, parent_manifest_path=parent_manifest_path,
        run_id=run_id, artifact_project_root=artifact_project_root)
    return Path(result['run_directory'])


def resume(run_id: str, result_path: Path | None, artifact_project_root: Path | None, *, context) -> dict:
    """Resume only the original owner's stopped finalization from its small Result."""
    from msplatform.execution.completion import no_particle_batch_completion_api
    from msplatform.execution.owner import resume_finalization

    expected_root = resolve_run_artifact_root(context.workspace / 'artifacts', owner_kind='component', owner_id='rf_multipole_ion_optics')
    if artifact_project_root is not None and artifact_project_root.resolve() != expected_root.resolve():
        raise ValueError(f'Explicit artifact root must use the selected managed research workspace: {expected_root}')
    selected = result_path or expected_root / 'scratch/workflow_results' / run_id / 'result.json'
    document = load_json(selected)
    if Path(document.get('run_directory', '')).name != run_id:
        raise ValueError('Finalization Result run identity differs from --run-id')
    return resume_finalization(context, selected, completion_api=no_particle_batch_completion_api)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--resolved-design', type=Path)
    parser.add_argument('--mode', type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--run-id')
    parser.add_argument('--check-contract', action='store_true')
    parser.add_argument('--resume-finalization', action='store_true')
    parser.add_argument('--analyze-only', action='store_true')
    parser.add_argument('--parent-manifest', type=Path)
    parser.add_argument('--result-path', type=Path)
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--execution-environment', type=Path)
    parser.add_argument('--engineering-profile')
    parser.add_argument('--artifact-project-root', type=Path)
    args = parser.parse_args()
    if args.resume_finalization and args.analyze_only:
        parser.error('--resume-finalization cannot be combined with --analyze-only')
    if args.resume_finalization:
        if args.check_contract or args.parent_manifest is not None or any(value is not None for value in (
                args.baseline, args.resolved_design, args.mode, args.source)):
            parser.error('--resume-finalization does not accept scientific inputs or --check-contract')
    elif args.analyze_only:
        if (args.check_contract or args.result_path is not None or args.parent_manifest is None
                or any(value is not None for value in (args.baseline, args.resolved_design, args.mode, args.source))):
            parser.error('--analyze-only requires --parent-manifest and no scientific, contract or Result options')
    else:
        if args.result_path is not None or args.parent_manifest is not None:
            parser.error('--result-path and --parent-manifest require their explicit recovery/analysis modes')
        args.baseline = args.baseline or DEFAULT_BASELINE
        args.resolved_design = args.resolved_design or DEFAULT_RESOLVED
        args.mode = args.mode or DEFAULT_MODE
        args.source = args.source or DEFAULT_SOURCE
    if args.check_contract:
        finite_length.validate_l1_contract(load_json(args.baseline), load_json(args.mode), load_json(args.source))
        print('QUADRUPOLE_MASS_FILTER_L1_CONTRACT=PASS')
        return
    if not args.run_id or args.workspace is None or args.execution_environment is None or not args.engineering_profile:
        parser.error('execution requires --run-id, --workspace, --execution-environment and --engineering-profile')
    from msplatform.execution.context import load_environment
    context = load_environment(args.execution_environment, workspace=args.workspace, profile=args.engineering_profile)
    if args.resume_finalization:
        result = resume(args.run_id, args.result_path, args.artifact_project_root, context=context)
        print(f"QUADRUPOLE_MASS_FILTER_L1_FINALIZATION={result['status'].upper()} RUN={Path(result['run_directory']).name}")
        return
    if args.analyze_only:
        destination = analyze(args.parent_manifest, args.run_id, args.artifact_project_root, context=context)
        print(f'QUADRUPOLE_MASS_FILTER_L1_ANALYSIS=PASS RUN={destination.name}')
        return
    destination = run(args.baseline, args.resolved_design, args.mode, args.source,
                      args.run_id, args.artifact_project_root, context=context)
    print(f'QUADRUPOLE_MASS_FILTER_L1=PASS RUN={destination.name}')


if __name__ == '__main__':
    main()
