"""Select explicit research inputs for the installed ideal-field L1 workflow.

The named project inputs retain their existing science. Execution requires an
explicit saved deployment/profile and a managed research workspace; the installed
workflow owns freezing, observed processes and terminal publication.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from msplatform.workflows.rf_mass_filter import finite_length

PROJECT_ROOT = Path(__file__).resolve().parents[2]
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=DEFAULT_BASELINE)
    parser.add_argument('--resolved-design', type=Path, default=DEFAULT_RESOLVED)
    parser.add_argument('--mode', type=Path, default=DEFAULT_MODE)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--run-id')
    parser.add_argument('--check-contract', action='store_true')
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--execution-environment', type=Path)
    parser.add_argument('--engineering-profile')
    parser.add_argument('--artifact-project-root', type=Path)
    args = parser.parse_args()
    if args.check_contract:
        finite_length.validate_l1_contract(load_json(args.baseline), load_json(args.mode), load_json(args.source))
        print('QUADRUPOLE_MASS_FILTER_L1_CONTRACT=PASS')
        return
    if not args.run_id or args.workspace is None or args.execution_environment is None or not args.engineering_profile:
        parser.error('execution requires --run-id, --workspace, --execution-environment and --engineering-profile')
    from msplatform.execution.context import load_environment
    context = load_environment(args.execution_environment, workspace=args.workspace, profile=args.engineering_profile)
    destination = run(args.baseline, args.resolved_design, args.mode, args.source,
                      args.run_id, args.artifact_project_root, context=context)
    print(f'QUADRUPOLE_MASS_FILTER_L1=PASS RUN={destination.name}')


if __name__ == '__main__':
    main()
