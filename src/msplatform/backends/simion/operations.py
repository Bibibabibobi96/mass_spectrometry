"""Public SIMION operations over complete domain objects."""
from __future__ import annotations

import copy
import os
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from msplatform.assembly.model import Assembly
from msplatform.contracts.machine_contracts import ContractError
from msplatform.results import artifacts as artifact_reader
from .compiler import CompiledSimionGeometry, compile_geometry as compile_simion_geometry
from .rf_compiler import compile_independent_multipoles
from .oa_compiler import compile_independent_accelerators

if TYPE_CHECKING:
    from msplatform.assembly.handoff import HandoffResult
    from msplatform.results.artifacts import OpenedArtifact
    from msplatform.execution.context import ExecutionContext
    from msplatform.ion_release.authoring import ReleaseRealization


def _reject_legacy_composite_execution(geometry: Mapping[str, Any]) -> None:
    """Retain historical model readers while retiring this public execution type."""
    plan = geometry.get('composition_plan')
    if plan is None:
        plan = geometry.get('source_snapshot', {}).get('composition_plan', {})
    selected = plan.get('scope', {}).get('instance_ids', [])
    interfaces = plan.get('components', {})
    if any(interfaces.get(name, {}).get('project_id') == 'single_reflection_oa_tof_mass_analyzer'
           for name in selected):
        raise ContractError('legacy composite OA–TOF is historical read-only; use independent OA + single_reflection_tof')


def build_geometry(compiled: CompiledSimionGeometry, *, context: ExecutionContext) -> OpenedArtifact:
    """Materialize actual unsolved geometry through the one public execution owner.

    Engineering limits and retention are explicit in context.stage_policy_path.
    Native reopen/relocation qualifications remain separate recorded facts.
    """
    from dataclasses import asdict
    from datetime import datetime
    from functools import partial
    from uuid import uuid4
    from msplatform.backends.simion.geometry_execution import execute_geometry
    from msplatform.backends.simion.native_plans import plan_geometry_build
    from msplatform.backends.simion.resources import structural_seed_path
    from msplatform.backends.simion import native_completion
    from msplatform.io.manifest_records import file_record
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.stage_policy import read_stage_policy

    if not isinstance(compiled, CompiledSimionGeometry):
        raise ContractError("build_geometry requires compiled SIMION geometry")
    _reject_legacy_composite_execution(compiled.frontend_geometry)
    if context is None or "simion" not in context.tools or not context.tools["simion"].is_file():
        raise ContractError("build_geometry requires an explicit available SIMION executable")
    stage, authority = read_stage_policy(context, "build_geometry", required_roles=("solver_native_binary",))
    runtime = stage.get("runtime", {})
    if (set(runtime) - {"simion_allow_asynchronous_io"}
            or ("simion_allow_asynchronous_io" in runtime
                and type(runtime["simion_allow_asynchronous_io"]) is not bool)):
        raise ContractError("SIMION geometry runtime only accepts explicit boolean simion_allow_asynchronous_io")
    snapshot = CompiledSimionGeometry(**asdict(compiled))
    provider_sources = {}
    if snapshot.frontend_geometry.get('role') == 'simion_neutral_multi_domain_collision_geometry':
        from .generic_geometry import multi_domain_source_paths, seal_multi_domain_geometry_for_publication
        from msplatform.io.manifest_records import verify_record
        provider_sources = {name:file_record(path,'required_evidence') for name,path in multi_domain_source_paths(snapshot).items()}
        snapshot = seal_multi_domain_geometry_for_publication(snapshot)
        for record in provider_sources.values(): verify_record('multi-domain source after admission',record)
    if snapshot.frontend_geometry.get("role") == "simion_neutral_world_collision_geometry":
        from .generic_geometry import seal_neutral_geometry_for_publication
        snapshot = seal_neutral_geometry_for_publication(snapshot)
    count = (len(snapshot.frontend_gems) if snapshot.frontend_geometry.get("role") in {"simion_independent_rf_geometry", "simion_independent_oa_geometry", "simion_rf_ip_geometry", "simion_oa_mr_complete_geometry", "simion_ip_mr_complete_geometry", "simion_rf_oa_geometry", "simion_neutral_world_collision_geometry", "simion_neutral_multi_domain_collision_geometry"}
             else 4 + int("entrance_refinement" in snapshot.frontend_geometry["numerical_domains"]))
    seed = file_record(structural_seed_path(count), "required_evidence")
    # Only derive path-independent action names/relative file lengths here.
    # The owner alone creates the actual run and its existing ASCII projection.
    planning_root = context.execution_root / "geometry-plan"
    plan = plan_geometry_build(snapshot, run_directory=planning_root, seed_record=seed,
        native_path_resource=planning_root / "inputs/native_sources/native_run_path.lua")
    ids = tuple(row["operation_id"] for row in plan.operations)
    source = file_record(Path(execute_geometry.__code__.co_filename).resolve(), "required_evidence")
    surface_validator = None
    if snapshot.frontend_geometry.get("role") in {"simion_ip_mr_complete_geometry", "simion_neutral_world_collision_geometry", "simion_neutral_multi_domain_collision_geometry"}:
        from . import native_surface_state
        surface_validator = file_record(Path(native_surface_state.__file__).resolve(), "required_evidence")
    result = run_managed_stage(context, descriptor=dict(project="instrument_assembly", mode="geometry_only", software=["SIMION"]),
        run_id=datetime.now().strftime("%Y%m%d_%H%M%S") + "__build__simion__geometry-" + uuid4().hex[:12],
        payload=dict(action="build_geometry", compiled_geometry=asdict(snapshot), stage_policy=stage),
        committed_new_bytes=stage["limits"]["transient_run_directory_bytes"],
        commitment_inputs=[authority, *([surface_validator] if surface_validator else []), *provider_sources.values()], retention=stage["artifact_retention"],
        expected_operation_ids=ids,
        operation_dependencies={name: [ids[index-1]] for index, name in enumerate(ids) if index},
        action=partial(execute_geometry, compiled=snapshot, seed_record=seed, limits=stage["limits"],
            allow_asynchronous_io=runtime.get("simion_allow_asynchronous_io"), surface_validator_record=surface_validator, provider_source_records=provider_sources),
        action_record=source,
        expected_relative_paths=[str(Path(path).relative_to(planning_root)) for path in (*plan.declared_outputs, *(row["optional_surface"] for row in plan.operations if "optional_surface" in row))],
        use_short_execution_path=True, completion_api=lambda: native_completion)
    return artifact_reader.open_artifact({"manifest": result["manifest"], "product_id": "geometry"}, expected_kind="geometry_artifact")


def prepare_model(geometry: OpenedArtifact | Mapping[str, Any], *, drive: Mapping[str, Any],
                  physics: Mapping[str, Any], context: ExecutionContext) -> OpenedArtifact:
    """Publish a driven, unsolved model from explicit geometry and clock authority.

    Scientific group defaults are expanded from the same providers. The clock
    authority is an explicit versioned example resource or contract record plus
    data_root; it is never discovered from context or a prior run.
    """
    from datetime import datetime
    from functools import partial
    import json
    from uuid import uuid4
    from msplatform.backends.simion.compiler import CompiledSimionGeometry
    from msplatform.backends.simion.model import project_resolved_drive, compile_prepared_model
    from msplatform.backends.simion.model_execution import execute_model
    from msplatform.backends.simion.resources import structural_seed_path
    from msplatform.backends.simion import native_completion
    from msplatform.results.artifacts import OpenedArtifact
    from msplatform.execution.clock_authority import validate_clock_authority
    from msplatform.io.manifest_records import file_record, verify_record
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.payload_inputs import materialize_payloads
    from msplatform.execution.stage_policy import read_stage_policy

    if not isinstance(drive, Mapping):
        raise ContractError("model drive must be an explicit mapping")
    if "simion" not in context.tools or not context.tools["simion"].is_file():
        raise ContractError("prepare_model requires an explicit available SIMION executable")
    source = artifact_reader.open_artifact(geometry.reference if isinstance(geometry, OpenedArtifact) else geometry,
                           expected_kind="geometry_artifact")
    stage, policy_record = read_stage_policy(context, "prepare_model", required_roles=("solver_native_binary",))
    runtime = stage.get("runtime", {})
    if (set(runtime) - {"simion_allow_asynchronous_io"}
            or ("simion_allow_asynchronous_io" in runtime and type(runtime["simion_allow_asynchronous_io"]) is not bool)):
        raise ContractError("SIMION model runtime only accepts explicit boolean simion_allow_asynchronous_io")
    values = json.loads(source.data_path("compiled_geometry").read_text(encoding="utf-8-sig"))
    values["downstream_specs"] = tuple(values["downstream_specs"])
    compiled = CompiledSimionGeometry(**values)
    _reject_legacy_composite_execution(compiled.frontend_geometry)
    if compiled.frontend_geometry.get("role") == "simion_rf_oa_geometry":
        raise ContractError("joint geometry has no supported prepared model yet")
    joint_oa_mr = compiled.frontend_geometry.get("role") == "simion_oa_mr_complete_geometry"
    joint_ip = compiled.frontend_geometry.get("role") == "simion_rf_ip_geometry"
    joint_ip_mr = compiled.frontend_geometry.get("role") == "simion_ip_mr_complete_geometry"
    ip_mr_has_rf = joint_ip_mr and any(row["project_id"] == "rf_multipole_ion_optics"
        for name, row in compiled.frontend_geometry["composition_plan"]["components"].items()
        if name in compiled.frontend_geometry["composition_plan"]["scope"]["instance_ids"])
    static_world = compiled.frontend_geometry.get("role") in {"simion_neutral_world_collision_geometry", "simion_neutral_multi_domain_collision_geometry"}
    independent_rf = compiled.frontend_geometry.get("role") == "simion_independent_rf_geometry"
    independent_oa = compiled.frontend_geometry.get("role") == "simion_independent_oa_geometry"
    split_oa_tof = compiled.frontend_geometry.get("role") == "simion_split_oa_tof_geometry"
    independent_component = independent_rf or independent_oa or joint_ip or joint_oa_mr or joint_ip_mr or static_world
    required = {"clock", "clock_authority"} | ({"oa_groups", "mr_authority", "pulse"} if joint_oa_mr else set()) | ({"groups"} if independent_oa or split_oa_tof or joint_ip or ip_mr_has_rf or static_world else set()) | ({"ip_schedule"} if joint_ip or joint_ip_mr else set()) | ({"mr_authority"} if joint_ip_mr else set()) | (set() if independent_component else {"pulse"})
    if (not required <= drive.keys() or set(drive) - required - (set() if joint_oa_mr or joint_ip_mr else {"groups"}) - ({"pulse", "ip_schedule", "ip_schedules"} if static_world else {"pulse"} if independent_oa else set())
            or not isinstance(drive["clock"], Mapping)
            or set(drive["clock"]) != {"phase_reference_instrument_time_us"}):
        raise ContractError("model drive requires its actual clock/groups and declared pulse contract")
    authority = drive["clock_authority"]
    if isinstance(authority, Mapping) and set(authority) == {"example_resource"}:
        from importlib.resources import files
        if authority["example_resource"] != "instrument_clock_authority_v1.json":
            raise ContractError("unknown versioned example clock authority")
        data_root = Path(str(files("msplatform.examples")))
        contract_record = file_record(data_root / authority["example_resource"], "required_evidence")
    elif isinstance(authority, Mapping) and set(authority) == {"contract", "data_root"}:
        data_root = Path(authority["data_root"])
        contract_record = dict(authority["contract"])
        if not data_root.is_absolute():
            raise ContractError("clock authority data_root must be explicit and absolute")
    else:
        raise ContractError("clock authority requires example_resource or explicit contract record and data_root")
    verify_record("model clock authority", contract_record)
    contract_path = Path(contract_record["path"])
    validation = validate_clock_authority(contract_path, data_root)
    contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    epoch_record = file_record((data_root / contract["authority"]["path"]).resolve(), "required_evidence")
    clock_reference = dict(contract=contract_record, authority=epoch_record, data_root=str(data_root))
    if joint_ip or joint_ip_mr or (static_world and ("ip_schedule" in drive or "ip_schedules" in drive)):
        epoch = json.loads((data_root / contract["authority"]["path"]).read_text(encoding="utf-8-sig"))
        if type(epoch.get("instrument_time_us")) not in (int, float) or epoch["instrument_time_us"] != 0:
            raise ContractError("IP schedule requires the existing zero instrument epoch")
    geometry_plan = (compiled.frontend_geometry['source_snapshot']['composition_plan'] if static_world else compiled.frontend_geometry['composition_plan'])
    selected = geometry_plan['scope']['instance_ids']
    components = {name: compiled.components_resolved[name] for name in selected}
    clock = dict(clock_epoch_id=validation["clock_epoch_id"], authority_sha256=validation["authority_sha256"],
                 **dict(drive["clock"]))
    if joint_oa_mr:
        expanded = dict(oa_groups=copy.deepcopy(drive["oa_groups"]),
            mr_authority=copy.deepcopy(drive["mr_authority"]), pulse=copy.deepcopy(drive["pulse"]), clock=clock)
    elif joint_ip_mr:
        expanded = dict(clock=clock, ip_schedule=copy.deepcopy(drive["ip_schedule"]),
            mr_authority=copy.deepcopy(drive["mr_authority"]),
            **({"groups": copy.deepcopy(drive["groups"])} if ip_mr_has_rf else {}))
    elif joint_ip:
        expanded = dict(groups=copy.deepcopy(drive["groups"]), clock=clock,
            ip_schedule=copy.deepcopy(drive["ip_schedule"]))
    elif split_oa_tof:
        expanded = dict(groups=copy.deepcopy(drive["groups"]), pulse=copy.deepcopy(drive["pulse"]), clock=clock)
    elif independent_oa or static_world:
        expanded = dict(groups=copy.deepcopy(drive["groups"]), clock=clock,
            **({"pulse": copy.deepcopy(drive["pulse"])} if "pulse" in drive else {}),
            **({"ip_schedule": copy.deepcopy(drive["ip_schedule"])} if static_world and "ip_schedule" in drive else {}),
            **({"ip_schedules": copy.deepcopy(drive["ip_schedules"])} if static_world and "ip_schedules" in drive else {}))
    else:
        expanded = project_resolved_drive(compiled, components, clock=clock,
            **({} if independent_rf else dict(pulse=drive["pulse"])))
    if "groups" in drive:
        expanded["groups"] = copy.deepcopy(drive["groups"])
    if static_world and 'producer_validated_members' in compiled.frontend_geometry:
        if (source.producer.get('status') != 'success' or source.producer.get('mode') != 'geometry_only'
                or source.producer.get('project') != 'instrument_assembly'
                or source.metadata.get('backend') != 'simion'
                or source.metadata.get('geometry_materialized') is not True
                or source.metadata.get('field_status') != 'not_solved'
                or source.metadata.get('source_status') != 'not_requested'):
            raise ContractError('neutral producer projection requires a successful published geometry owner')
        from .model import _compile_static_world_published_model
        model = _compile_static_world_published_model(compiled, components, drive=expanded, physics=physics)
    else:
        model = compile_prepared_model(compiled, components, drive=expanded, physics=physics)
    model_provider_sources={}
    if compiled.frontend_geometry.get('role') == 'simion_neutral_multi_domain_collision_geometry':
        from .generic_geometry import multi_domain_source_paths
        model_provider_sources={name:file_record(path,'required_evidence') for name,path in multi_domain_source_paths(compiled).items()}
    seed = file_record(structural_seed_path(len(compiled.frontend_gems) if independent_component else 4 + int(
        "entrance_refinement" in compiled.frontend_geometry["numerical_domains"])), "required_evidence")
    ids = ("materialize_geometry", "build_model", "verify_model")
    result = run_managed_stage(context,
        descriptor=dict(project="instrument_assembly", mode="prepared_model", software=["SIMION"]),
        run_id=datetime.now().strftime("%Y%m%d_%H%M%S") + "__build__simion__model-" + uuid4().hex[:12],
        payload=dict(action="prepare_model", geometry=source.reference, model=model.document,
                     clock_authority=clock_reference, stage_policy=stage),
        committed_new_bytes=stage["limits"]["transient_run_directory_bytes"],
        commitment_inputs=[policy_record, contract_record, epoch_record, *model_provider_sources.values()], retention=stage["artifact_retention"],
        expected_operation_ids=ids,
        operation_dependencies={name: [ids[index-1]] for index, name in enumerate(ids) if index},
        action=partial(execute_model, model=model, geometry_reference=source.reference, seed_record=seed,
            limits=stage["limits"], clock_authority_reference=clock_reference,
            materialize_geometry=partial(materialize_payloads, limits=stage["limits"]),
            materializer_record=file_record(Path(materialize_payloads.__code__.co_filename).resolve(), "required_evidence"),
            allow_asynchronous_io=runtime.get("simion_allow_asynchronous_io"), provider_source_records=model_provider_sources),
        action_record=file_record(Path(execute_model.__code__.co_filename).resolve(), "required_evidence"),
        source_references=[{"manifest_record": source.reference["manifest"]}],
        use_short_execution_path=True, completion_api=lambda: native_completion)
    return artifact_reader.open_artifact({"manifest": result["manifest"], "product_id": "model"}, expected_kind="prepared_model")


def solve_fields(model: OpenedArtifact | Mapping[str, Any], *, numerics: Mapping[str, Any],
                 context: ExecutionContext,
                 reuse_fields: OpenedArtifact | Mapping[str, Any] | None = None,
                 scalar_field_basis: Mapping[str, Any] | None = None,
                 reuse_collision_geometry: OpenedArtifact | Mapping[str, Any] | None = None) -> OpenedArtifact:
    """Explicitly solve an unsolved model, without source sampling or flight.

    Optional reuse names one published field product, never a latest lookup.
    With an explicit sampled scalar basis, reuse_collision_geometry borrows only
    verified collision assets from their original producer. The new scalar basis
    is independently admitted and both producers remain protected; this is not
    reuse of the previous electric field or a native solve.
    The backend validates the actual spatial operator before reusing downstream
    data; the new field product retains the current model's drive and clock.
    """
    from datetime import datetime
    from functools import partial
    from uuid import uuid4
    from msplatform.backends.simion.field_closure import load_field_model
    from msplatform.backends.simion.field_execution import execute_fields, plan_fields_execution
    from msplatform.backends.simion import native_completion
    from msplatform.results.artifacts import OpenedArtifact
    from msplatform.io.manifest_records import file_record
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.payload_inputs import materialize_payloads
    from msplatform.execution.stage_policy import read_stage_policy

    if not isinstance(numerics, Mapping):
        raise ContractError("solve_fields requires explicit field numerics")
    if reuse_collision_geometry is not None and scalar_field_basis is None:
        raise ContractError('collision geometry reuse requires an explicit sampled scalar basis')
    if "simion" not in context.tools or not context.tools["simion"].is_file():
        raise ContractError("solve_fields requires an explicit available SIMION executable")
    stage, policy_record = read_stage_policy(context, "solve_fields", required_roles=("solver_native_binary",))
    runtime = stage.get("runtime", {})
    if (set(runtime) - {"simion_allow_asynchronous_io"}
            or ("simion_allow_asynchronous_io" in runtime and type(runtime["simion_allow_asynchronous_io"]) is not bool)):
        raise ContractError("SIMION field runtime only accepts explicit boolean simion_allow_asynchronous_io")
    if scalar_field_basis is not None:
        # Representation is selected from the actual published model, never a provider name.
        from msplatform.backends.simion.artifacts import CompiledPreparedModel
        from msplatform.backends.simion.model import require_prepared_model
        candidate = model if isinstance(model, OpenedArtifact) else artifact_reader.open_artifact(model, expected_kind='prepared_model')
        candidate_model = CompiledPreparedModel(candidate.data_path('compiled_model').read_text(encoding='utf8'))
        _reject_legacy_composite_execution(require_prepared_model(candidate_model)['geometry']['frontend_geometry'])
        if require_prepared_model(candidate_model)['geometry']['frontend_geometry'].get('role') in {'simion_neutral_world_collision_geometry','simion_neutral_multi_domain_collision_geometry'}:
            from msplatform.backends.simion.neutral_sampled_field import prepare_neutral_sampled_inputs, execute_neutral_sampled_fields
            if reuse_fields is not None or reuse_collision_geometry is not None or numerics: raise ContractError('neutral sampled fields require explicit samples and empty field numerics')
            if not isinstance(scalar_field_basis, Mapping) or set(scalar_field_basis)-{'geometry_artifact','operator','samples','refinement_windows'} or not {'geometry_artifact','operator','samples'} <= set(scalar_field_basis):
                raise ContractError('neutral sampled fields require geometry, operator and explicit weighted samples')
            def ref(value):
                if not isinstance(value,OpenedArtifact):return copy.deepcopy(value)
                result=value.reference;result['manifest']=dict(result['manifest'],path=str(value.manifest_location));return result
            selection=copy.deepcopy(dict(scalar_field_basis));selection['geometry_artifact']=ref(scalar_field_basis['geometry_artifact'])
            for name,row in selection['samples'].items():row['reference']=ref(scalar_field_basis['samples'][name]['reference'])
            for window in selection.get('refinement_windows',[]):
                for name,value in window['samples'].items():window['samples'][name]=ref(value)
            selected_model=ref(model);planning_root=context.execution_root/'neutral-sampled-fields-plan'
            planned=prepare_neutral_sampled_inputs(selected_model,selection=selection,output_directory=planning_root/'simion/collision')
            from msplatform.backends.simion.standalone_pa_composition import PaHeader
            geometry=planned['model'].document['geometry']['frontend_geometry'];tasks=planned['geometry_plan']['tasks']
            if geometry.get('role') == 'simion_neutral_multi_domain_collision_geometry':
                from msplatform.backends.simion.neutral_sampled_field import neutral_multi_background_grid
                background=neutral_multi_background_grid(planned['model'],planned['binding']); dims=background['dimensions']; pitch=background['pitch_mm']
                lower=PaHeader(-2,1,1.0,*dims,0,*pitch).file_bytes
                for task in tasks:
                    domain=geometry['domains'][task['role']];p=domain['pitch_mm']
                    lower+=PaHeader(-2,1,1.0,*domain['dimensions'],0,p,p,p).file_bytes
                    if 'fractional_surface' in task['source_records']:lower+=task['source_records']['fractional_surface']['bytes']
            else:
                dims=geometry['dimensions'];pitch=geometry['pitch_mm']
                lower=2*PaHeader(-2,1,1.0,*dims,0,pitch,pitch,pitch).file_bytes
                if 'fractional_surface' in tasks[0]['source_records']:lower+=tasks[0]['source_records']['fractional_surface']['bytes']
            limits=stage['limits']
            if limits['reserved_run_payload_bytes'] < lower or limits['transient_run_directory_bytes'] < lower:
                raise ContractError(f'neutral collision output lower bound {lower} bytes exceeds declared reservation or transient limit')
            ids=planned['expected_operation_ids'];relative=[str(path.relative_to(planning_root)) for task in tasks for path in (Path(task['output_path']),Path(task['output_path']).with_suffix('.pa-surf'))]+['simion/collision/background.pa','simion/collision/collision.iob','simion/collision/collision.fly2']
            result=run_managed_stage(context,descriptor=dict(project='instrument_assembly',mode='fields_only',software=['SIMION']),
                run_id=datetime.now().strftime('%Y%m%d_%H%M%S')+'__sim__simion__fields-'+uuid4().hex[:12],
                payload=dict(action='solve_fields',model=planned['prepared_source'],numerics={},reuse_fields=None,scalar_field_basis=selection,stage_policy=stage),
                committed_new_bytes=limits['transient_run_directory_bytes'],commitment_inputs=[policy_record],retention=stage['artifact_retention'],
                expected_operation_ids=ids,operation_dependencies={name:[ids[index-1]] for index,name in enumerate(ids) if index},
                action=partial(execute_neutral_sampled_fields,model_reference=planned['prepared_source'],selection=selection,limits=limits,allow_asynchronous_io=runtime.get('simion_allow_asynchronous_io')),
                action_record=file_record(Path(execute_neutral_sampled_fields.__code__.co_filename).resolve(),'required_evidence'),source_references=planned['source_references'],expected_relative_paths=relative,use_short_execution_path=True,completion_api=lambda:native_completion)
            return artifact_reader.open_artifact({'manifest':result['manifest'],'product_id':'fields'},expected_kind='field_bundle')
        from msplatform.backends.simion.ip_mr_field_execution import prepare_ip_mr_field_inputs, execute_ip_mr_sampled_fields
        if reuse_fields is not None:
            raise ContractError('sampled scalar fields cannot be combined with field reuse')
        if numerics:
            raise ContractError('saved scalar basis requires empty numerics; its grids and operator are explicit in the source products')
        required={'geometry_artifact','operator','samples','collision_priority_evidence'}
        if (not isinstance(scalar_field_basis, Mapping) or not required <= scalar_field_basis.keys()
                or set(scalar_field_basis)-required-{'refinement_windows'}):
            raise ContractError('sampled scalar selection requires geometry, operator, samples and collision priority evidence')
        evidence=copy.deepcopy(scalar_field_basis['collision_priority_evidence'])
        if not isinstance(evidence, Mapping) or set(evidence)!={'boxes_record','clearance_record','source_record'}:
            raise ContractError('collision priority evidence requires boxes, clearance and source records')
        if not isinstance(scalar_field_basis['samples'], Mapping):
            raise ContractError('sampled scalar basis requires an explicit sample mapping')
        windows=scalar_field_basis.get('refinement_windows')
        if windows is not None and (not isinstance(windows,list) or any(
                not isinstance(window,Mapping) or set(window)!={'name','active_box_mm','samples'}
                or not isinstance(window['samples'],Mapping) for window in windows)):
            raise ContractError('sampled scalar refinement windows require explicit sample mappings')
        def reference(value):
            if not isinstance(value, OpenedArtifact):
                return copy.deepcopy(value)
            result=value.reference
            result['manifest']=dict(result['manifest'],path=str(value.manifest_location))
            return result
        selection=dict(geometry_artifact=reference(scalar_field_basis['geometry_artifact']),
            operator=copy.deepcopy(scalar_field_basis['operator']),
            samples={key:reference(value) for key,value in scalar_field_basis['samples'].items()})
        if windows is not None:
            selection['refinement_windows']=[dict(name=window['name'],active_box_mm=copy.deepcopy(window['active_box_mm']),
                samples={key:reference(value) for key,value in window['samples'].items()})
                for window in windows]
        selected_model=reference(model)
        if reuse_collision_geometry is not None:
            from msplatform.backends.simion.ip_mr_field_execution import prepare_reused_ip_mr_collisions, execute_reused_ip_mr_collisions
            reuse_reference=reference(reuse_collision_geometry)
            prepared=prepare_reused_ip_mr_collisions(selected_model,scalar_field_basis=selection,
                priority_evidence=evidence,reuse_reference=reuse_reference,
                output_directory=context.execution_root/'sampled-fields-plan/simion/collision')
            unique={}
            for item in prepared['source_references']:
                record=item['manifest_record'];key=os.path.normcase(str(Path(record['path']).resolve()))
                if key in unique and unique[key]['manifest_record']!=record:raise ContractError('conflicting source manifest identity')
                unique[key]=item
            result=run_managed_stage(context,
                descriptor=dict(project='instrument_assembly',mode='fields_only',software=['SIMION']),
                run_id=datetime.now().strftime('%Y%m%d_%H%M%S')+'__sim__simion__fields-'+uuid4().hex[:12],
                payload=dict(action='solve_fields',model=prepared['prepared_source'],numerics={},reuse_fields=None,
                    reuse_collision_geometry=reuse_reference,scalar_field_basis=dict(selection,collision_priority_evidence=evidence),stage_policy=stage),
                committed_new_bytes=stage['limits']['transient_run_directory_bytes'],commitment_inputs=[policy_record],
                retention=stage['artifact_retention'],expected_operation_ids=(),operation_dependencies={},
                action=partial(execute_reused_ip_mr_collisions,model_reference=selected_model,scalar_field_basis=selection,
                    priority_evidence=evidence,reuse_reference=reuse_reference),
                action_record=file_record(Path(execute_reused_ip_mr_collisions.__code__.co_filename).resolve(),'required_evidence'),
                source_references=list(unique.values()),use_short_execution_path=True,completion_api=lambda:native_completion)
            return artifact_reader.open_artifact({'manifest':result['manifest'],'product_id':'fields'},expected_kind='field_bundle')
        planning_root=context.execution_root/'sampled-fields-plan'
        prepared=prepare_ip_mr_field_inputs(selected_model,scalar_field_basis=selection,
            priority_evidence=evidence,output_directory=planning_root/'simion/collision')
        # Each converted collision array and the numerical background has one
        # ordinary PA payload. Surface copies are additional known output bytes.
        # This is a lower bound, not an estimate of peak or retained usage.
        from msplatform.backends.simion.standalone_pa_composition import PaHeader
        lower_bound=0
        for row in prepared['priority_projection']['instances']:
            grid=row['grid']
            lower_bound+=PaHeader(-2,1,1.0,grid['nx'],grid['ny'],grid['nz'],0,
                                  grid['dx_mm'],grid['dy_mm'],grid['dz_mm']).file_bytes
        lower_bound+=sum(task['source_records']['fractional_surface']['bytes']
                         for task in prepared['geometry_plan']['tasks']
                         if 'fractional_surface' in task['source_records'])
        limits=stage['limits']
        if (limits['reserved_run_payload_bytes'] < lower_bound or
                limits['transient_run_directory_bytes'] < lower_bound):
            raise ContractError(f'sampled collision output lower bound {lower_bound} bytes exceeds declared reservation or transient limit')
        ids=prepared['expected_operation_ids']
        output_paths=[str(Path(task['output_path']).relative_to(planning_root)) for task in prepared['geometry_plan']['tasks']]
        output_paths += [str(Path(path).with_suffix('.pa-surf')) for path in output_paths]
        output_paths += ['simion/collision/background.pa','simion/collision/collision.iob',
                         'simion/collision/collision.fly2']
        result=run_managed_stage(context,
            descriptor=dict(project='instrument_assembly',mode='fields_only',software=['SIMION']),
            run_id=datetime.now().strftime('%Y%m%d_%H%M%S')+'__sim__simion__fields-'+uuid4().hex[:12],
            payload=dict(action='solve_fields',model=prepared['prepared_source'],numerics={},reuse_fields=None,
                         scalar_field_basis=dict(selection,collision_priority_evidence=evidence),stage_policy=stage),
            committed_new_bytes=stage['limits']['transient_run_directory_bytes'],
            commitment_inputs=[policy_record,*evidence.values()],retention=stage['artifact_retention'],
            expected_operation_ids=ids,
            operation_dependencies={name:[ids[index-1]] for index,name in enumerate(ids) if index},
            action=partial(execute_ip_mr_sampled_fields,model_reference=prepared['prepared_source'],
                scalar_field_basis=selection,priority_evidence=evidence,limits=stage['limits'],
                allow_asynchronous_io=runtime.get('simion_allow_asynchronous_io')),
            action_record=file_record(Path(execute_ip_mr_sampled_fields.__code__.co_filename).resolve(),'required_evidence'),
            source_references=prepared['source_references'],expected_relative_paths=output_paths,
            use_short_execution_path=True,completion_api=lambda: native_completion)
        return artifact_reader.open_artifact({'manifest':result['manifest'],'product_id':'fields'},expected_kind='field_bundle')
    source = load_field_model(model.reference if isinstance(model, OpenedArtifact) else model)
    _reject_legacy_composite_execution(source.model.document['geometry']['frontend_geometry'])
    if source.model.document['geometry']['frontend_geometry'].get('role') == 'simion_neutral_multi_domain_collision_geometry':
        raise ContractError('multi-domain fields require their explicit sampled scalar basis')
    selected_numerics = copy.deepcopy(dict(numerics))
    reuse_reference = None
    references = [{"manifest_record": source.artifact.reference["manifest"]}]
    if reuse_fields is not None:
        reused = artifact_reader.open_artifact(reuse_fields.reference if isinstance(reuse_fields, OpenedArtifact) else reuse_fields,
                               expected_kind="field_bundle")
        reuse_reference = reused.reference
        references.append({"manifest_record": reuse_reference["manifest"]})
        if reused.metadata.get("field_representation") in {"producer_owned_rf_fractional_family", "producer_owned_oa_fractional_family", "producer_owned_static_world_fractional_family"}:
            original = reused.metadata.get("family_producer_reference", reused.reference)
            references.append({"manifest_record": original["manifest"]})
        if reused.metadata.get("field_representation") == "producer_owned_static_world_standalone_operating_pa":
            original = reused.metadata.get("operating_producer_reference", reused.reference)
            references.append({"manifest_record": original["manifest"]})
    graph = plan_fields_execution(source.model, numerics=selected_numerics, reuse_fields_reference=reuse_reference)
    surface_validator = None
    if source.model.document['geometry']['frontend_geometry'].get('role') == 'simion_neutral_world_collision_geometry':
        from . import native_surface_state
        surface_validator = file_record(Path(native_surface_state.__file__).resolve(), 'required_evidence')
    result = run_managed_stage(context,
        descriptor=dict(project="instrument_assembly", mode="fields_only", software=["SIMION"]),
        run_id=datetime.now().strftime("%Y%m%d_%H%M%S") + "__sim__simion__fields-" + uuid4().hex[:12],
        payload=dict(action="solve_fields", model=source.artifact.reference, numerics=selected_numerics,
                     reuse_fields=reuse_reference, stage_policy=stage),
        committed_new_bytes=stage["limits"]["transient_run_directory_bytes"],
        commitment_inputs=[policy_record, *([surface_validator] if surface_validator else [])], retention=stage["artifact_retention"],
        expected_operation_ids=tuple(graph["expected_operation_ids"]),
        operation_dependencies=graph["operation_dependencies"],
        action=partial(execute_fields, model_reference=source.artifact.reference, numerics=selected_numerics,
            limits=stage["limits"], materialize_geometry=partial(materialize_payloads, limits=stage["limits"]),
            materializer_record=file_record(Path(materialize_payloads.__code__.co_filename).resolve(), "required_evidence"),
            allow_asynchronous_io=runtime.get("simion_allow_asynchronous_io"), reuse_fields_reference=reuse_reference,
            surface_validator_record=surface_validator),
        action_record=file_record(Path(execute_fields.__code__.co_filename).resolve(), "required_evidence"),
        source_references=references, use_short_execution_path=True, completion_api=lambda: native_completion)
    return artifact_reader.open_artifact({"manifest": result["manifest"], "product_id": "fields"}, expected_kind="field_bundle")


def track(fields: OpenedArtifact | Mapping[str, Any],
          particles: ReleaseRealization | HandoffResult | Mapping[str, Any], *,
          propagation: Mapping[str, Any], observations: Mapping[str, Any],
          numerics: Mapping[str, Any], context: ExecutionContext,
          source_reference: OpenedArtifact | Mapping[str, Any] | None = None,
          unit_size: int | None = None, recovery_reference: Mapping[str, Any] | None = None,
          dispatch_profiles: Sequence[Mapping[str, Any]] = (),
          birth_source_authority: Mapping[str, Any] | None = None, hs1_request: Mapping[str, Any] | None = None,
          scalar_field_basis: Mapping[str, Any] | None = None) -> OpenedArtifact:
    """Publish an explicit fixed-field flight, preserving its original cohort/clock.

    A release realization starts at birth; a HandoffResult requires its published
    trajectory producer. The backend verifies the actual observed source before
    relaunch. Zero handoff publishes full mother facts without launching tools.
    unit_size fixes ordinal replay boundaries without changing original IDs or
    the full mother. recovery_reference is one explicit predecessor manifest
    file record: complete units are verified and reused, incomplete units fully
    replayed by the existing dispatcher. Opening a field never solves it.

    Complete RF-IP tracking requires an explicit hs1_request: typed IP-local
    bath_domain and outer GasFieldSpec, original vendor_record, and numerics
    containing seed and hs1_steps_per_mfp. The selected IP pose maps gas queries
    and velocities; the outer field must cover the complete parent. This route
    requires sequential grouped=0 and never restarts particles at gas boundaries.
    """
    from dataclasses import asdict
    from datetime import datetime
    from functools import partial
    from uuid import uuid4
    from msplatform.assembly.handoff import HandoffResult
    from msplatform.backends.simion.artifacts import CompiledPreparedModel
    from msplatform.backends.simion.model import require_prepared_model
    from msplatform.backends.simion.tracking_execution import execute_tracking, plan_tracking_execution, validate_birth_authority
    from msplatform.backends.simion.tracking_units import inspect_tracking_recovery, tracking_applicability
    from msplatform.backends.simion import native_completion
    from msplatform.results.artifacts import OpenedArtifact
    from msplatform.io.manifest_records import file_record
    from msplatform.execution.owner import run_managed_stage
    from msplatform.execution.stage_policy import read_stage_policy
    from msplatform.ion_release.authoring import ReleaseRealization

    source = fields if isinstance(fields, OpenedArtifact) else artifact_reader.open_artifact(fields, expected_kind="field_bundle")
    meta = source.metadata
    if (source.kind != "field_bundle" or meta.get("backend") != "simion"
            or meta.get("field_status") != "available" or meta.get("source_status") != "not_requested"):
        raise ContractError("track requires a published source-independent SIMION FieldBundle")
    model = CompiledPreparedModel(source.data_path("compiled_model").read_text(encoding="utf-8-sig"))
    document = require_prepared_model(model)
    _reject_legacy_composite_execution(document['geometry']['frontend_geometry'])
    if meta.get("model_identity_sha256") != document["model_identity_sha256"] or meta.get("clock") != document["drive"]["clock"]:
        raise ContractError("tracking field model/clock identity differs")
    tracking_geometry = document["geometry"]["frontend_geometry"]
    tracking_plan = tracking_geometry.get("composition_plan", {})
    selected = tracking_plan.get("scope", {}).get("instance_ids", [])
    interfaces = tracking_plan.get("components", {})
    legacy_oa_tof = any(interfaces.get(name, {}).get("project_id") == "single_reflection_oa_tof_mass_analyzer"
                        for name in selected)
    if (tracking_geometry.get("role") == "simion_split_oa_tof_geometry" or legacy_oa_tof) and (
            isinstance(particles, HandoffResult) or
            (isinstance(propagation, Mapping) and propagation.get("scope") in {"segmented_upstream", "state_relaunch"})):
        raise ContractError("OA–TOF requires original births and continuous_assembly; cross-component relaunch is retired")
    sampled_neutral = meta.get('field_representation') in {'neutral_sampled_basis_with_collision_geometry','neutral_multi_sampled_basis_with_collision_geometry'}
    neutral_admission = None
    if sampled_neutral:
        if scalar_field_basis is not None:
            raise ContractError('neutral sampled tracking uses the basis published in its FieldBundle')
        from msplatform.backends.simion.rf_tracking_execution import admit_neutral_sampled_tracking_fields
        neutral_admission = admit_neutral_sampled_tracking_fields(source.reference)
    if (document['geometry']['frontend_geometry'].get('role') in {'simion_neutral_world_collision_geometry','simion_neutral_multi_domain_collision_geometry'}
            and meta.get('field_representation') not in {'producer_owned_static_world_standalone_operating_pa', 'neutral_sampled_basis_with_collision_geometry','neutral_multi_sampled_basis_with_collision_geometry'}):
        raise ContractError('static world tracking requires its published standalone operating field; fractional families must be finalized before publication')
    sampled_ip_mr = meta.get('field_representation') == 'assembly_sampled_basis_with_collision_geometry'
    ip_mr_admission = None
    if sampled_ip_mr:
        if scalar_field_basis is not None:
            raise ContractError('sampled IP-MR tracking uses the basis already published in its FieldBundle')
        from msplatform.backends.simion.ip_mr_tracking_admission import admit_ip_mr_tracking_fields
        ip_mr_admission = admit_ip_mr_tracking_fields(source.reference)
    packet = particles.to_dict() if isinstance(particles, ReleaseRealization) else copy.deepcopy(particles)
    birth_authority = None if birth_source_authority is None else validate_birth_authority(birth_source_authority, packet)
    clocks = {name: dict(source.data_records[name], path=str(source.data_path(name)))
              for name in ("clock_authority", "instrument_epoch")}
    if (not isinstance(dispatch_profiles, Sequence) or isinstance(dispatch_profiles, (str, bytes))
            or any(not isinstance(profile, Mapping) for profile in dispatch_profiles)):
        raise ContractError("tracking dispatch_profiles must be an explicit sequence of resource profiles")
    profiles = tuple(copy.deepcopy(dict(profile)) for profile in dispatch_profiles)
    recovery = None
    if recovery_reference is not None:
        if (not isinstance(recovery_reference, Mapping)
                or not isinstance(recovery_reference.get("path"), str)
                or not Path(recovery_reference["path"]).is_absolute()):
            raise ContractError("tracking recovery requires an explicit absolute predecessor manifest file record")
        recovery = copy.deepcopy(dict(recovery_reference))
    planning = dict(particles=packet, clock_records=clocks, propagation=propagation,
                    observations=observations, numerics=numerics, unit_size=unit_size,
                    field_manifest_record=source.reference["manifest"],
                    **({'birth_source_authority': birth_authority} if birth_authority is not None else {}), hs1_request=hs1_request,
                    **({'ip_mr_field_reference': source.reference} if sampled_ip_mr else {}),
                    **({'neutral_sampled_field_reference': source.reference} if sampled_neutral else {}))
    graph = plan_tracking_execution(model, **planning)
    if scalar_field_basis is not None:
        if isinstance(packet, HandoffResult) or hs1_request is not None:
            raise ContractError('scalar basis requires an original-birth SFI flight')
        from msplatform.backends.simion.tracking_execution import _resolve_scalar_basis
        graph['scalar_field_basis'] = _resolve_scalar_basis(source, model, graph, scalar_field_basis)
    planned_applicability = tracking_applicability(graph) if hs1_request is not None or scalar_field_basis is not None or sampled_neutral else None
    if recovery is not None:
        inspected = inspect_tracking_recovery(graph, recovery)
        graph = plan_tracking_execution(model, **planning, reused_unit_keys=inspected["reused_unit_keys"])
        if scalar_field_basis is not None:
            graph['scalar_field_basis'] = _resolve_scalar_basis(source, model, graph, scalar_field_basis)
    predecessor = None
    references = [{"manifest_record": source.reference["manifest"]}]
    if ip_mr_admission is not None or neutral_admission is not None:
        selected_manifests = {}
        selected_admission = ip_mr_admission if ip_mr_admission is not None else neutral_admission
        for record in (source.reference['manifest'], *selected_admission['source_manifests']):
            key = os.path.normcase(str(Path(record['path']).resolve()))
            identity = (record['bytes'], str(record['sha256']).lower())
            if key in selected_manifests:
                if selected_manifests[key] != identity:
                    raise ContractError('conflicting IP-MR source manifest identity: ' + key)
                continue
            selected_manifests[key] = identity
            if key != os.path.normcase(str(Path(source.reference['manifest']['path']).resolve())):
                references.append({'manifest_record': record})
    if birth_authority is not None:
        references.append({"manifest_record": birth_authority['manifest']})
    if scalar_field_basis is not None:
        admitted = graph['scalar_field_basis']
        references.append({'manifest_record': admitted['geometry_reference']['manifest']})
        scalar_manifests = {}
        for entry in admitted['bases'].values():
            for level in [entry, *entry.get('refinement_windows', [])]:
                manifests = [level['reference']['manifest'], level['field_solution_reference']['manifest']]
                if level.get('original_samples_reference') is not None:
                    manifests.append(level['original_samples_reference']['manifest'])
                for manifest in manifests:
                    key = os.path.normcase(str(Path(manifest['path']).resolve()))
                    identity = (manifest['bytes'], manifest['sha256'], manifest.get('retention_role'))
                    if key in scalar_manifests:
                        if scalar_manifests[key] != identity: raise ValueError('conflicting scalar producer record: ' + key)
                        continue
                    scalar_manifests[key] = identity
                    references.append({'manifest_record': manifest})
    if meta.get('field_representation') in {'producer_owned_rf_fractional_family','producer_owned_oa_fractional_family','producer_owned_rf_ip_fractional_family','producer_owned_static_world_fractional_family'}:
        original=meta.get('family_producer_reference',source.reference)
        references.append({'manifest_record':original['manifest']})
    if meta.get('field_representation') == 'producer_owned_static_world_standalone_operating_pa':
        original = meta.get('operating_producer_reference', source.reference)
        references.append({'manifest_record': original['manifest']})
    if meta.get('field_representation') == 'split_scalar_world_with_collision_geometry':
        collision = artifact_reader.open_artifact(meta['collision_source_reference'], expected_kind='field_bundle')
        if (collision.metadata.get('backend') != 'simion'
                or collision.metadata.get('field_representation') == 'split_scalar_world_with_collision_geometry'
                or collision.metadata.get('model_identity_sha256') != meta.get('model_identity_sha256')):
            raise ContractError('world scalar collision source differs from its original native model')
        references.append({'manifest_record': collision.reference['manifest']})
    if recovery is not None:
        references.append({"manifest_record": recovery})
    if isinstance(packet, HandoffResult):
        if source_reference is None:
            raise ContractError("state relaunch requires its published trajectory source reference")
        predecessor = (source_reference if isinstance(source_reference, OpenedArtifact)
                       else artifact_reader.open_artifact(source_reference, expected_kind="trajectory_result"))
        if predecessor.kind != "trajectory_result":
            raise ContractError("handoff producer must be a published trajectory result")
        references.append({"manifest_record": predecessor.reference["manifest"]})
    elif source_reference is not None:
        raise ContractError("birth realization cannot claim a handoff producer")
    if graph["native_requested"] and ("simion" not in context.tools or not context.tools["simion"].is_file()):
        raise ContractError("nonempty tracking requires an explicit available SIMION executable")
    stage, policy_record = read_stage_policy(context, "track", required_roles=("solver_native_binary",))
    runtime = stage.get("runtime", {})
    if (set(runtime) - {"simion_allow_asynchronous_io"}
            or ("simion_allow_asynchronous_io" in runtime and type(runtime["simion_allow_asynchronous_io"]) is not bool)):
        raise ContractError("SIMION tracking runtime only accepts explicit boolean simion_allow_asynchronous_io")
    result = run_managed_stage(context,
        descriptor=dict(project="instrument_assembly", mode="tracking", software=["SIMION"]),
        run_id=datetime.now().strftime("%Y%m%d_%H%M%S") + "__sim__simion__track-" + uuid4().hex[:12],
        payload=dict(action="track", fields=source.reference,
            particles=asdict(packet) if isinstance(packet, HandoffResult) else packet,
            propagation=copy.deepcopy(dict(propagation)), observations=copy.deepcopy(dict(observations)),
            numerics=copy.deepcopy(dict(numerics)), source_reference=predecessor.reference if predecessor else None,
            unit_size=unit_size, recovery_reference=recovery, dispatch_profiles=copy.deepcopy(profiles),
            **({'scalar_field_basis': graph['scalar_field_basis']} if scalar_field_basis is not None else {}),
            **({'birth_source_authority': birth_authority} if birth_authority is not None else {}),
            **({'hs1_identity': graph['hs1_identity'], 'hs1_vendor_record': dict(hs1_request['vendor_record'])} if hs1_request is not None else {}),
            stage_policy=stage),
        committed_new_bytes=stage["limits"]["transient_run_directory_bytes"],
        commitment_inputs=[policy_record], retention=stage["artifact_retention"],
        expected_operation_ids=tuple(graph["expected_operation_ids"]),
        operation_dependencies=graph["operation_dependencies"],
        action=partial(execute_tracking, fields_reference=source, particles=packet,
            propagation=graph["propagation"], observations=graph["observations"], numerics=graph["numerics"],
            limits=stage["limits"], source_reference=predecessor.reference if predecessor else None,
            unit_size=unit_size, recovery_reference=recovery, dispatch_profiles=profiles,
            **({'birth_source_authority': birth_authority} if birth_authority is not None else {}),
            hs1_request=hs1_request, expected_tracking_applicability=planned_applicability,
            **({'scalar_field_basis': scalar_field_basis, 'expected_scalar_basis': graph['scalar_field_basis']} if scalar_field_basis is not None else {}),
            allow_asynchronous_io=runtime.get("simion_allow_asynchronous_io")),
        action_record=file_record(Path(execute_tracking.__code__.co_filename).resolve(), "required_evidence"),
        source_references=references, use_short_execution_path=True, completion_api=lambda: native_completion)
    return artifact_reader.open_artifact({"manifest": result["manifest"], "product_id": "trajectory"}, expected_kind="trajectory_result")


def compile_geometry(assembly: Assembly, *, numerics: Mapping[str, Any]) -> CompiledSimionGeometry:
    """Compile native geometry specifications only; no source, writes, solve or Fly."""
    if not isinstance(assembly, Assembly):
        raise ContractError("SIMION geometry compilation requires an explicitly assembled design")
    _reject_legacy_composite_execution({'composition_plan': assembly.composition_plan})
    if isinstance(numerics, Mapping) and numerics.get("representation") == "neutral_multi_domain_collision":
        from .generic_geometry import compile_generic_multi_domain_geometry
        return compile_generic_multi_domain_geometry(assembly, numerics=numerics)
    if isinstance(numerics, Mapping) and numerics.get("representation") == "neutral_world_collision":
        from .generic_geometry import compile_generic_collision_geometry
        return compile_generic_collision_geometry(assembly, numerics=numerics)
    plan = assembly.composition_plan
    selected = plan["scope"]["instance_ids"]
    projects = [plan["components"][name]["project_id"] for name in selected]
    if len(projects) == 2 and set(projects) == {"rf_multipole_ion_optics", "dual_pressure_rectilinear_ion_processor"}:
        from .ip_compiler import compile_ip_assembly_geometry
        return compile_ip_assembly_geometry(assembly, numerics=copy.deepcopy(dict(numerics)))
    if len(projects) == 2 and set(projects) == {"rf_multipole_ion_optics", "orthogonal_accelerator"}:
        from .rf_oa_compiler import compile_rf_oa_geometry
        return compile_rf_oa_geometry(assembly, numerics=copy.deepcopy(dict(numerics)))
    if len(projects) == 2 and set(projects) == {"orthogonal_accelerator", "parallel_mirror_dual_stripe_mr_tof"}:
        from .mr_compiler import compile_complete_mr_geometry
        return compile_complete_mr_geometry(assembly, numerics=copy.deepcopy(dict(numerics)))
    if (len(projects) in (2, 3) and set(projects) in (
            {"dual_pressure_rectilinear_ion_processor", "parallel_mirror_dual_stripe_mr_tof"},
            {"rf_multipole_ion_optics", "dual_pressure_rectilinear_ion_processor", "parallel_mirror_dual_stripe_mr_tof"})):
        from .mr_compiler import compile_complete_mr_geometry
        return compile_complete_mr_geometry(assembly, numerics=copy.deepcopy(dict(numerics)))
    if selected and all(plan["components"][name]["project_id"] == "rf_multipole_ion_optics" for name in selected):
        return compile_independent_multipoles(
            dict(composition_plan=plan, components_resolved=assembly.components_resolved),
            numerics=copy.deepcopy(dict(numerics)),
        )
    if selected and all(plan["components"][name]["project_id"] == "orthogonal_accelerator" for name in selected):
        return compile_independent_accelerators(
            dict(composition_plan=plan, components_resolved={name:assembly.components_resolved[name] for name in selected}),
            numerics=copy.deepcopy(dict(numerics)))
    compiled = compile_simion_geometry(
        {"composition_plan": copy.deepcopy(dict(assembly.composition_plan)),
         "components_resolved": {name: copy.deepcopy(assembly.components_resolved[name]) for name in selected}},
        numerics=copy.deepcopy(dict(numerics)),
    )
    return replace(compiled, components_resolved=assembly.components_resolved)
