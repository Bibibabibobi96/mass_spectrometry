"""Guard explicit successful paired static model sources without copying MPH."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import json
from pathlib import Path

from msplatform.backends.comsol.paired_static_model import load_paired_static_model_source
from msplatform.execution.native_source_guard import guard_historical_run
from msplatform.execution.run_paths import project_run_path
from msplatform.io.file_identity import guarded_file_identity
from msplatform.io.manifest_records import file_record, record_path, require_completed_terminal_publication


@contextmanager
def guard_paired_saved_model(store, manifest_path: Path, *, _seen=None):
    """Hold one direct, successful model and its precise manifest-bound records.

    No failed source, borrowed historical chain or model copy is implied.
    The caller retains the returned Store claim through any native child.
    """
    path = Path(manifest_path).resolve(strict=True)
    seen=set() if _seen is None else set(_seen)
    if path in seen:
        raise ValueError('cyclic paired historical model source')
    seen.add(path)
    if path.name != 'run_manifest.json':
        raise ValueError('paired source requires its run_manifest.json')
    manifest_record = file_record(path, 'required_evidence')
    with ExitStack() as stack:
        asset_id = None
        token = None
        execution_alias = None
        if path.is_relative_to(store.root/'assets'):
            parts = path.relative_to(store.root).parts
            if len(parts) < 6 or parts[:2] != ('assets','native_stage'):
                raise ValueError('paired Store model source identity differs')
            asset_id = parts[3]
            token, asset = stack.enter_context(store.claim_token(asset_id))
            if not path.is_relative_to(asset):
                raise ValueError('paired Store claim differs')
            stack.enter_context(guarded_file_identity(path,expected_bytes=manifest_record['bytes'],expected_sha256=manifest_record['sha256']))
            require_completed_terminal_publication(path)
            manifest=json.loads(path.read_text(encoding='utf8'))
            root=path.parent
            if (manifest.get('role')!='simulation_run_manifest' or manifest.get('status')!='success'
                    or manifest.get('project')!='instrument_assembly' or manifest.get('mode')!='paired_accelerator_static_field'
                    or manifest.get('run_id')!=root.name):
                raise ValueError('paired Store source is not a successful paired stage')
            rows=[*manifest.get('inputs',{}).values(),*manifest.get('outputs',[])]
            def held(relative):
                wanted=(root/relative).resolve()
                matches=[item for item in rows if record_path(item,base_dir=root)==wanted]
                if not matches or any((r['bytes'],r['sha256'].upper()) != (matches[0]['bytes'],matches[0]['sha256'].upper()) for r in matches):
                    raise ValueError('paired Store model record missing or conflicting: '+relative)
                record=dict(matches[0],path=str(wanted))
                stack.enter_context(guarded_file_identity(wanted,expected_bytes=record['bytes'],expected_sha256=record['sha256']))
                return record
            plan=held('inputs/bvp/paired_accelerator_static_field_plan.json')
            solution=held('comsol/comsol_field_solution.json')
            model=held('comsol/paired_accelerator_static.mph')
            completion=held('results/execution_completion.json')
            metadata=json.loads(Path(completion['path']).read_text(encoding='utf8'))
            execution_alias=metadata.get('package',{}).get('execution_alias')
            if metadata.get('run_id') != root.name:
                raise ValueError('paired Store completion run identity differs')
        else:
            historical=stack.enter_context(guard_historical_run(manifest_record,
                expected_project='instrument_assembly',expected_mode='paired_accelerator_static_field'))
            root=historical.root
            def input_at(relative):
                wanted=(root/relative).resolve()
                names=[name for name,value in historical.manifest['inputs'].items()
                       if record_path(value,base_dir=root)==wanted]
                if len(names)!=1:
                    raise ValueError('paired historical model input missing or ambiguous: '+relative)
                return historical.input(names[0])
            output_paths={record_path(row,base_dir=root) for row in historical.manifest.get('outputs',[])}
            if (root/'comsol/comsol_field_solution.json').resolve() not in output_paths:
                consumer_plan=input_at('inputs/bvp/paired_accelerator_static_field_plan.json')
                receipt=input_at('inputs/comsol_source.json')
                snapshot=input_at('inputs/comsol_source_manifest.json')
                reference=json.loads(Path(receipt['path']).read_text(encoding='utf8'))
                origin=reference.get('manifest',{})
                if (not isinstance(origin,dict) or not isinstance(origin.get('source_path'),str)
                        or any(origin.get(key)!=snapshot.get(key) for key in ('bytes','sha256'))):
                    raise ValueError('paired borrowed source requires one exact flat original manifest')
                original=stack.enter_context(guard_paired_saved_model(store,Path(origin['source_path']),_seen=seen))
                legacy=load_paired_static_model_source(path,path,
                    expected_plan=json.loads(Path(consumer_plan['path']).read_text(encoding='utf8')))
                if (Path(legacy['manifest']['source_path']).resolve()!=Path(original['manifest']['path'])
                        or any(record_path(legacy[name])!=Path(original[name]['path']) for name in ('plan','solution','model'))):
                    raise ValueError('paired borrowed source differs from protected original')
                yield dict(original,source_chain=[manifest_record,consumer_plan,receipt,snapshot,
                                                   *original.get('source_chain',[])])
                return
            plan=input_at('inputs/bvp/paired_accelerator_static_field_plan.json')
            solution=historical.output('comsol/comsol_field_solution.json')
            model=historical.output('comsol/paired_accelerator_static.mph')
            # The legacy decoder validates the exact original vendor code binding.
            legacy=load_paired_static_model_source(path,path)
            if Path(legacy['manifest']['source_path']).resolve()!=path:
                raise ValueError('borrowed historical paired model is not a direct source')
            backend=legacy['backend']
            backend_path=record_path(backend,base_dir=root)
            stack.enter_context(guarded_file_identity(backend_path,expected_bytes=backend['bytes'],expected_sha256=backend['sha256']))
            # Re-read after all files are held; no unchecked metadata can race the consumer.
            legacy=load_paired_static_model_source(path,path)
            if any(record_path(legacy[name],base_dir=root)!=Path(record['path']) for name,record in (
                    ('plan',plan),('solution',solution),('model',model))):
                raise ValueError('paired historical decoded source differs')
        facts=json.loads(Path(solution['path']).read_text(encoding='utf8'))
        def persistent(value):
            if not isinstance(value,str) or not value:
                raise ValueError('paired saved model fact path is missing')
            return Path(project_run_path(value,execution_alias,root) if execution_alias else value).resolve()
        if (facts.get('schema_version')!=1 or facts.get('role')!='oatof_paired_accelerator_static_field_solution'
                or facts.get('status')!='solved_saved' or facts.get('solution_present') is not True
                or facts.get('solution_tag')!='sol1' or persistent(facts.get('plan_path'))!=Path(plan['path'])
                or persistent(facts.get('model_path'))!=Path(model['path'])):
            raise ValueError('paired solved model native facts differ')
        yield dict(manifest=manifest_record,plan=plan,solution=solution,model=model,
                   source_stage='solved_saved',asset_id=asset_id,claim_token=token)

@contextmanager
def guard_paired_saved_samples(store, manifest_path: Path):
    """Hold a terminal successful paired COMSOL export, without opening its MPH."""
    path=Path(manifest_path).resolve(strict=True)
    if path.name!='run_manifest.json':
        raise ValueError('paired samples require their run_manifest.json')
    record=file_record(path,'required_evidence')
    with ExitStack() as stack:
        asset_id=None
        if path.is_relative_to(store.root/'assets'):
            parts=path.relative_to(store.root).parts
            if len(parts)<6 or parts[:2]!=('assets','native_stage'):
                raise ValueError('paired Store samples source identity differs')
            asset_id=parts[3]
            _,asset=stack.enter_context(store.claim_token(asset_id))
            if not path.is_relative_to(asset):
                raise ValueError('paired Store samples claim differs')
            stack.enter_context(guarded_file_identity(path,expected_bytes=record['bytes'],expected_sha256=record['sha256']))
            require_completed_terminal_publication(path)
            manifest=json.loads(path.read_text(encoding='utf8'));root=path.parent
            if (manifest.get('role')!='simulation_run_manifest' or manifest.get('status')!='success'
                    or manifest.get('project')!='instrument_assembly' or manifest.get('mode')!='paired_accelerator_static_field'
                    or manifest.get('run_id')!=root.name):
                raise ValueError('paired Store samples require a successful paired stage')
            rows=[*manifest.get('inputs',{}).values(),*manifest.get('outputs',[])]
            def held(relative):
                wanted=(root/relative).resolve()
                matches=[item for item in rows if record_path(item,base_dir=root)==wanted]
                if not matches or any((r['bytes'],r['sha256'].upper())!=(matches[0]['bytes'],matches[0]['sha256'].upper()) for r in matches):
                    raise ValueError('paired Store sample record missing or conflicting: '+relative)
                value=dict(matches[0],path=str(wanted))
                stack.enter_context(guarded_file_identity(wanted,expected_bytes=value['bytes'],expected_sha256=value['sha256']))
                return value
            plan=held('inputs/bvp/paired_accelerator_static_field_plan.json')
            samples=held('comsol/comsol_field_samples.csv')
            facts=held('comsol/comsol_field_native_facts.json')
            completion=held('results/execution_completion.json')
            metadata=json.loads(Path(completion['path']).read_text(encoding='utf8'))
            if metadata.get('run_id')!=root.name:
                raise ValueError('paired sample completion identity differs')
            alias=metadata.get('package',{}).get('execution_alias')
        else:
            source=stack.enter_context(guard_historical_run(record,expected_project='instrument_assembly',
                                                           expected_mode='paired_accelerator_static_field'))
            root=source.root
            wanted=(root/'inputs/bvp/paired_accelerator_static_field_plan.json').resolve()
            names=[name for name,value in source.manifest['inputs'].items() if record_path(value,base_dir=root)==wanted]
            if len(names)!=1:
                raise ValueError('paired historical sample plan missing or ambiguous')
            plan=source.input(names[0]);samples=source.output('comsol/comsol_field_samples.csv')
            facts=source.output('comsol/comsol_field_native_facts.json');alias=None
            rows=[*source.manifest['inputs'].values(),*source.manifest['outputs']]
        data=json.loads(Path(facts['path']).read_text(encoding='utf8'))
        plan_data=json.loads(Path(plan['path']).read_text(encoding='utf8'))
        def persistent(value):
            if not isinstance(value,str) or not value:
                raise ValueError('paired sample fact path is missing')
            return Path(project_run_path(value,alias,root) if alias else value).resolve()
        if (data.get('backend')!='COMSOL' or data.get('coordinate_unit')!='mm' or data.get('field_unit')!=['V/m']*3
                or data.get('point_count')!=plan_data.get('sample_points',{}).get('count')
                or persistent(data.get('plan_path'))!=Path(plan['path'])
                or persistent(data.get('sample_path'))!=Path(samples['path'])
                or not any(record_path(item,base_dir=root)==persistent(data.get('model_path')) for item in rows)):
            raise ValueError('paired completed sample facts differ')
        yield dict(manifest=record,plan=plan,samples=samples,facts=facts,asset_id=asset_id)

@contextmanager
def guard_paired_failed_prepared_model(store, manifest_path: Path):
    """Open sealed failed/interrupted prepared evidence with proven stopped workers."""
    from msplatform.execution.native_source_guard import guard_failed_store_evidence, guard_stopped_store_evidence
    path=Path(manifest_path).resolve(strict=True)
    manifest_record=file_record(path,'required_evidence')
    manifest=json.loads(path.read_text(encoding='utf8'))
    root=path.parent
    if (path.name!='run_manifest.json' or manifest.get('project')!='instrument_assembly'
            or manifest.get('mode')!='paired_accelerator_static_field' or manifest.get('run_id')!=root.name):
        raise ValueError('failed prepared source is not a paired run')
    def selected(relative):
        expected=(root/relative).resolve()
        found=[row for row in manifest.get('outputs',[]) if record_path(row,base_dir=root)==expected]
        if len(found)!=1:
            raise ValueError('failed paired source lacks exact '+relative)
        return found[0]
    solution=selected('comsol/comsol_field_solution.json')
    model=selected('comsol/paired_accelerator_static.mph')
    with ExitStack() as stack:
        if manifest.get('status')=='failed':
            stack.enter_context(guard_failed_store_evidence(store,manifest_record,solution))
            proven=stack.enter_context(guard_failed_store_evidence(store,manifest_record,model))
        elif manifest.get('status')=='interrupted':
            proven,hold=stack.enter_context(guard_stopped_store_evidence(store,manifest_record))
            hold([solution,model])
        else:
            raise ValueError('prepared paired source must be failed or interrupted')
        if proven!=manifest:
            raise ValueError('failed paired manifest changed during proof')
        wanted=(root/'inputs/bvp/paired_accelerator_static_field_plan.json').resolve()
        matches=[row for row in manifest.get('inputs',{}).values() if record_path(row,base_dir=root)==wanted]
        if len(matches)!=1:
            raise ValueError('failed paired source lacks exact plan')
        plan=dict(matches[0],path=str(wanted))
        stack.enter_context(guarded_file_identity(wanted,expected_bytes=plan['bytes'],expected_sha256=plan['sha256']))
        completion=json.loads((root/'results/execution_completion.json').read_text(encoding='utf8'))
        alias=completion.get('package',{}).get('execution_alias')
        facts=json.loads(Path(solution['path']).read_text(encoding='utf8'))
        def persistent(value):
            if not isinstance(value,str) or not value:
                raise ValueError('prepared model fact path is missing')
            return Path(project_run_path(value,alias,root) if alias else value).resolve()
        count=facts.get('tetrahedra')
        if (facts.get('schema_version')!=1 or facts.get('role')!='oatof_paired_accelerator_static_field_solution'
                or facts.get('status')!='prepared_saved' or facts.get('solution_present') is not False
                or facts.get('solution_tag')!='sol1' or facts.get('study_tag')!='std1'
                or facts.get('mesh_complete') is not True or type(count) not in (int,float)
                or count<=0 or int(count)!=count or persistent(facts.get('plan_path'))!=wanted
                or persistent(facts.get('model_path'))!=record_path(model,base_dir=root)):
            raise ValueError('failed paired prepared model native facts differ')
        yield dict(manifest=manifest_record,plan=plan,solution=dict(solution,path=str(record_path(solution,base_dir=root))),
                   model=dict(model,path=str(record_path(model,base_dir=root))),source_stage='prepared_saved',
                   asset_id=None,claim_token=None)
