"""Small inert fixtures for frozen paired metadata tests; no production owner."""
import json
from pathlib import Path
import shutil

from msplatform.backends.comsol.paired_static_field import prepare
from msplatform.backends.simion.native_completion import retention_api
from msplatform.execution.manifest_publication import build_run_manifest
from tests.components.single_reflection_oa_tof_mass_analyzer.analysis import test_paired_accelerator_static_field_prepare as preparation_tests

ROOT=Path(__file__).resolve().parents[4]

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf8')
    return value

def prepared(root):
    author=root/'author';author.mkdir()
    fixture=preparation_tests.PairedAcceleratorStaticFieldPrepareTests()
    request=fixture._request(author);source=fixture._write_request(author,request)
    run=root/'run';(run/'inputs/sources').mkdir(parents=True)
    for name,record in request['source_records'].items():
        shutil.copyfile(record['path'],run/f'inputs/sources/{name}.json')
    shutil.copyfile(source,run/'inputs/request.json')
    write(run/'run_config.json',{'parameters':{'request_source_path':str(source)}})
    for name in ('results','logs','comsol'):(run/name).mkdir()
    return run,author

def prepare_run(run):
    source=Path(read(run/'run_config.json')['parameters']['request_source_path'])
    return prepare(run/'inputs/request.json',run/'inputs/bvp',source_snapshot_root=run/'inputs/sources',source_base_dir=source.parent)

def completed_comsol_source(root):
    import copy
    import pandas as pd
    from msplatform.io.manifest_records import file_record
    root=root.resolve();run,_=prepared(root);plan=prepare_run(run)
    producer=root/'producer';(producer/'comsol').mkdir(parents=True)
    points=producer/'inputs/bvp/paired_accelerator_field_points.csv';points.parent.mkdir(parents=True)
    frame=pd.read_csv(plan['sample_points']['path']).iloc[[0]*115].copy()
    frame['point_id']=range(1,116);frame.to_csv(points,index=False)
    previous=copy.deepcopy(plan);previous['sample_points']=dict(file_record(points),count=115)
    plan_path=producer/'inputs/bvp/paired_accelerator_static_field_plan.json'
    write(plan_path,previous);write(run/'inputs/bvp/paired_accelerator_static_field_plan.json',previous)
    backend=Path('src/msplatform/backends/comsol/matlab/build_and_export_paired_accelerator_field.m')
    frozen=producer/'inputs/runtime_snapshot'/backend;frozen.parent.mkdir(parents=True)
    shutil.copyfile(ROOT/backend,frozen)
    model=producer/'comsol/paired_accelerator_static.mph';model.write_bytes(b'inert model identity only')
    solution=producer/'comsol/comsol_field_solution.json'
    write(solution,dict(schema_version=1,role='oatof_paired_accelerator_static_field_solution',status='solved_saved',
        solution_present=True,solution_tag='sol1',plan_path=str(plan_path),model_path=str(model)))
    samples=producer/'comsol/comsol_field_samples.csv'
    for axis in 'xyz':frame[f'E{axis}_V_per_m']=0.
    frame.to_csv(samples,index=False)
    facts=producer/'comsol/comsol_field_native_facts.json'
    write(facts,dict(backend='COMSOL',coordinate_unit='mm',field_unit=['V/m']*3,point_count=115,
        plan_path=str(plan_path),model_path=str(model),sample_path=str(samples)))
    config=producer/'run_config.json'
    write(config,dict(schema_version=1,run_id='20261026_010000__test__python__inert-static-exports',
        project='instrument_assembly',mode='paired_accelerator_static_field',
        inputs={'plan':str(plan_path),'points':str(points),'backend':str(frozen)}))
    def publish(outputs=None):
        manifest=build_run_manifest(config,'success',output_paths=outputs or [solution,model,samples,facts],retention_api=retention_api)
        write(producer/'run_manifest.json',manifest);write(run/'inputs/comsol_source_manifest.json',manifest)
    publish()
    return run,producer,model,samples,facts,publish
