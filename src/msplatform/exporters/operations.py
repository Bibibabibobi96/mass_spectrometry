"""Public CAD export and independent inspection operations."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from msplatform.assembly.model import Assembly
from msplatform.contracts.machine_contracts import ContractError
from msplatform.results import artifacts as artifact_reader

if TYPE_CHECKING:
    from msplatform.results.artifacts import OpenedArtifact
    from msplatform.execution.context import ExecutionContext


def inspect_cad(result: OpenedArtifact | Mapping[str, Any], *, checks: Mapping[str, Any]) -> dict[str, Any]:
    """Independently cold-read published STEP data; no export, owner or viewer."""
    import json
    from msplatform.results.artifacts import OpenedArtifact
    from msplatform.exporters.step import inspect_assembly_step
    source = result if isinstance(result, OpenedArtifact) else artifact_reader.open_artifact(result, expected_kind="cad_geometry")
    if source.kind != "cad_geometry" or not isinstance(checks, Mapping) or set(checks) != {"schema_version", "kind", "probes"}:
        raise ContractError("STEP inspection requires explicit current checks and cad_geometry")
    if type(checks['schema_version']) is not int or checks['schema_version'] != 1 or checks['kind'] != 'physical_solids_step_v1' or not isinstance(checks['probes'],(list,tuple)):
        raise ContractError("unsupported STEP inspection checks")
    report = json.loads(source.data_path('report').read_text(encoding='utf-8-sig'))
    for key, report_key in (('step','step_record'),('assembly_snapshot','snapshot_record'),('export_options','options_record')):
        source.data_path(key)
        actual, declared = source.data_records[key], report[report_key]
        if actual['bytes'] != declared['bytes'] or actual['sha256'].upper() != declared['sha256'].upper():
            raise ContractError("STEP report content identity differs from the published data")
    snapshot = json.loads(source.data_path('assembly_snapshot').read_text(encoding='utf-8-sig'))
    options = json.loads(source.data_path('export_options').read_text(encoding='utf-8-sig'))
    if report['projection']['options'] != options:
        raise ContractError("STEP report options differ from its frozen input")
    inspection = inspect_assembly_step(source.data_path('step'), assembly=snapshot, export_report=report,
                                       probes=copy.deepcopy(checks['probes']))
    inspection.update(cad_reference=source.reference, producer=source.producer, checks=copy.deepcopy(dict(checks)))
    return inspection


def _validate_step_export_options(assembly: Assembly, format: str, options: Mapping[str, Any]) -> str:
    """One pure option boundary shared by STEP planning and actual export."""
    from msplatform.exporters.step import step_export_filename
    if not isinstance(assembly, Assembly) or format != "step":
        raise ContractError("export_cad requires a complete Assembly and the supported step format")
    if not isinstance(options, Mapping) or options.get('representation') != 'physical_solids':
        raise ContractError("STEP options require physical_solids and explicit write_pcurves/precision_mode")
    try:
        return step_export_filename({key: value for key, value in options.items() if key != 'representation'})
    except ValueError as error:
        raise ContractError(str(error)) from error


def export_cad(assembly: Assembly, *, format: str, options: Mapping[str, Any],
               context: ExecutionContext) -> OpenedArtifact:
    """Publish an independent STEP without solver, source, field or GUI actions.

    The selected context Python must have this distribution and cad-step extra
    installed. Optional options["name"] is the file stem and STEP root display
    name; omitted it preserves assembly.step. Engineering/retention policy is
    explicit, as for native geometry.
    """
    from datetime import datetime
    from functools import partial
    from uuid import uuid4
    from msplatform.exporters.step import assembly_geometry_members
    from msplatform.exporters.execution import execute_cad_export
    from msplatform.execution.completion import no_particle_batch_completion_api
    from msplatform.io.manifest_records import file_record
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.stage_policy import read_stage_policy

    filename = _validate_step_export_options(assembly, format, options)
    snapshot = dict(composition_plan=assembly.composition_plan, components_resolved=assembly.components_resolved,
                    components_source=assembly.components_source)
    assembly_geometry_members(snapshot)
    stage, authority = read_stage_policy(context, "export_cad", required_roles=("solver_native_binary",))
    if stage.get("runtime"):
        raise ContractError("The STEP exporter has no additional runtime mode")
    source = file_record(Path(execute_cad_export.__code__.co_filename).resolve(), "required_evidence")
    result = run_managed_stage(context,
        descriptor=dict(project="instrument_assembly", mode="cad_only", software=["CadQuery", "OCCT"]),
        run_id=datetime.now().strftime("%Y%m%d_%H%M%S") + "__build__cad__assembly-" + uuid4().hex[:12],
        payload=dict(action="export_cad", assembly=snapshot, options=copy.deepcopy(dict(options)), stage_policy=stage),
        committed_new_bytes=stage["limits"]["transient_run_directory_bytes"], commitment_inputs=[authority],
        retention=stage["artifact_retention"], expected_operation_ids=("export_step",),
        operation_dependencies={"export_step": ()},
        action=partial(execute_cad_export, snapshot=snapshot, representation=options["representation"],
            options={name: options[name] for name in ("write_pcurves", "precision_mode", "name") if name in options}, limits=stage["limits"]),
        action_record=source, completion_api=no_particle_batch_completion_api,
        expected_relative_paths=("results/" + filename, "results/cad_export_report.json"))
    return artifact_reader.open_artifact({"manifest": result["manifest"], "product_id": "cad_geometry"}, expected_kind="cad_geometry")
