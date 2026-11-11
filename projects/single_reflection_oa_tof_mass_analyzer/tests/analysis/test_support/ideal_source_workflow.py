"""Small real-owner context/input fixtures for solver-free TOF workflow tests.

No test methods, scientific algorithms, source defaults or synthetic process
completion facts live here. Callers select their original research documents.
"""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from unittest.mock import patch

from msplatform.execution.capacity_protection import load_capacity_protection_leases
from msplatform.execution.context import ExecutionContext
from msplatform.execution.resources import resource_path


def copy_input_root(source_project: Path, destination: Path) -> Path:
    """Copy only the five declared original JSON inputs to an explicit test root."""
    for relative in (
        'config/analysis_contract.json',
        'config/experiments/ideal_source_comparison.json',
        'config/experiments/ideal_source_affine_slope_scan.json',
        'config/experiments/ideal_acceptance_theory.json',
        'config/experiments/ideal_acceptance_fixed_length.json',
    ):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_project / relative, target)
    return destination


def make_context(workspace: Path) -> ExecutionContext:
    """Select explicit TEST policies; retain actual public admission and ledger."""
    workspace.mkdir(parents=True, exist_ok=True)
    stage = workspace / 'test-owned-stage-policy.json'
    limits = dict(wall_clock_seconds=120,
                  transient_run_directory_bytes=268435456,
                  process_tree_working_set_bytes=2147483648,
                  minimum_system_available_memory_bytes=1073741824,
                  compact_final_retained_bytes=67108864,
                  automatic_retry_count=0)
    stages = {name: dict(limits=limits,
                        artifact_retention=dict(policy_version=1,
                                                **{'class': 'compact'}, reason=None))
              for name in ('ideal_source_comparison', 'ideal_source_slope_scan',
                           'ideal_acceptance_theory')}
    stage.write_text(json.dumps(dict(schema_version=1, role='execution_stage_policy',
                                    stages=stages)), encoding='utf-8')
    capacity = workspace / 'test-owned-capacity-policy.json'
    capacity_policy = json.loads(resource_path('artifact_capacity_policy.json').read_text(encoding='utf-8'))
    capacity_policy.update(target_gib=1, minimum_free_gib=64 / 1024)
    capacity.write_text(json.dumps(capacity_policy), encoding='utf-8')
    host = json.loads(os.environ['MASS_SPECTROMETRY_HOST_CONTEXT_JSON'])
    return ExecutionContext(
        workspace=workspace, python_executable=Path(sys.executable),
        powershell_executable=Path(shutil.which('pwsh')), tools={},
        host_state_path=Path(os.environ['MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH']),
        policy_path=Path(host['policy_path']), capacity_policy_path=capacity,
        stage_policy_path=stage)


@contextmanager
def owned_workflow_environment() -> Iterator[None]:
    """Let real workflow operations acquire their own leases on the shared host."""
    with patch.dict(os.environ, {
        'MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN': '',
        'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID': '',
        'MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE': '',
    }):
        yield


@contextmanager
def retained_workspace() -> Iterator[Path]:
    """Retain unexpected failures and real finalization/writer/capacity holds."""
    root = Path(tempfile.mkdtemp(prefix='tof-ideal-workflow-'))
    primary = None
    retain = False
    results = []
    active = []
    try:
        yield root
    except BaseException as error:
        primary = error
        retain = True
        raise
    finally:
        audit_error = None
        try:
            owners = {}
            artifact_roots = set()
            for path in root.rglob('result.json'):
                if path.parent.parent.name != 'workflow_results':
                    continue
                value = json.loads(path.read_text(encoding='utf-8-sig'))
                if value.get('role') != 'run_artifact_workflow_result':
                    continue
                results.append(str(path))
                run = Path(value['run_directory']).resolve()
                if not run.is_relative_to(root.resolve()) or run in owners:
                    raise AssertionError('Test owner Result has an external or duplicate run identity')
                owners[run] = value
                if (value.get('resume_action') is not None or value.get('writers_confirmed') is not True
                        or value.get('capacity_session', {}).get('status') != 'released'):
                    retain = True
            for path in root.rglob('capacity_session.json'):
                if not (path.parent.name == 'logs' and path.parent.parent.parent.name == 'runs'):
                    continue
                snapshot = json.loads(path.read_text(encoding='utf-8-sig'))
                run = path.parent.parent.resolve()
                artifact_root = Path(snapshot['artifact_root']).resolve()
                if not artifact_root.is_relative_to(root.resolve()):
                    raise AssertionError('Test capacity authority escaped its owned workspace')
                artifact_roots.add(artifact_root)
                public = owners.get(run)
                final = {} if public is None else public.get('capacity_session', {})
                # The immutable preparation snapshot can remain status=active.
                # Closure comes from the original owner's Result plus live lease
                # audit, never from absence or rewriting that historical snapshot.
                if (public is None or public.get('resume_action') is not None
                        or public.get('writers_confirmed') is not True or final.get('status') != 'released'
                        or any(final.get(key) != snapshot[key] for key in ('artifact_root', 'lease_id', 'owner'))):
                    active.append(str(path))
                    retain = True
            for artifact_root in artifact_roots:
                audit = load_capacity_protection_leases(artifact_root)
                if audit['audit']:
                    active.extend(str(row['lease_id']) for row in audit['audit'])
                    retain = True
        except Exception as error:
            retain = True
            if primary is not None:
                primary.add_note(f'Workspace hold audit failed: {error!r}')
            else:
                audit_error = error
        if retain:
            print('TOF_IDEAL_RETAINED_WORKSPACE=' + json.dumps(
                dict(path=str(root), results=results, active_capacity_sessions=active)))
        else:
            if root.resolve().parent != Path(tempfile.gettempdir()).resolve() or not root.name.startswith('tof-ideal-workflow-'):
                raise AssertionError('Test cleanup target escaped its owned temporary root')
            shutil.rmtree(root)
        if audit_error is not None:
            raise audit_error
