"""Select explicit research inputs for the installed ideal-field L1 workflow.

The named project inputs retain their existing science. Execution requires an
explicit saved deployment/profile and a managed research workspace; the installed
workflow owns freezing, observed processes and terminal publication.
"""
from __future__ import annotations

import json
from pathlib import Path

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
        run_id: str, *, context, artifact_store) -> Path:
    """Delegate to the sole managed workflow with the caller's actual context."""
    result = finite_length.run(context, baseline_path=baseline_path, resolved_path=resolved_path,
        mode_path=mode_path, source_path=source_path, run_id=run_id, artifact_store=artifact_store)
    return Path(result['run_directory'])


def analyze(parent_manifest_path: Path, run_id: str, *, context, artifact_store) -> Path:
    """Create a managed analysis-only child from an explicit sealed parent."""
    result = finite_length.analyze(context, parent_manifest_path=parent_manifest_path,
        run_id=run_id, artifact_store=artifact_store)
    return Path(result['run_directory'])


def resume(run_id: str, asset_id: str, *, context, artifact_store) -> dict:
    """Replay only a stopped Store stage; the original parent run is unchanged."""
    from msplatform.execution.artifact_naming import validate_run_id
    from msplatform.execution.owner import recover_managed_native_store_stage
    validate_run_id(run_id)
    run_directory = artifact_store.asset_status(asset_id)['path'] / 'runs' / run_id
    if not run_directory.is_dir():
        raise ValueError('Store stage run identity differs')
    replayed = recover_managed_native_store_stage(artifact_store, asset_id, context=context)
    state = artifact_store.asset_status(asset_id)['state']
    if state == 'ready':
        with artifact_store.claim_verified(asset_id):
            if not (run_directory / 'run_manifest.json').is_file():
                raise ValueError('ready Store stage lacks its manifest')
    return {'status': state, 'run_directory': str(run_directory), 'replayed': replayed}
