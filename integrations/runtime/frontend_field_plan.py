"""Pure frontend response construction plan, shared by native field consumers."""
from __future__ import annotations
import json,math
from pathlib import Path
from common.contracts.file_identity import file_sha256
from msplatform.backends.simion.pa_family_cache import canonical_pa_family_cache_key
from integrations.runtime.single_flight_electrode_contract import require_pa_plus_solution_model,render_pa_plus_solution_model








def build_field_plan(p: Path, exe: Path, runtime: Path) -> dict:
    """Resolve declared native samples and immutable cache inputs before Refine."""
    load=lambda name:json.loads((p/name).read_text(encoding='utf-8-sig'))
    f=load('frontend_contract.json');v=load('cache_physical_inputs.json');n=load('numerics.json')
    m=require_pa_plus_solution_model(f['pa_plus_solution_model'])
    supported_models={'two_zone_linear_ring_bare_octupole_pa_plus_v1':5,'three_zone_linear_ring_bare_octupole_pa_plus_v1':6}
    assert m['model_id'] in supported_models and m['mode_count']==supported_models[m['model_id']]
    assert v['refine_policy']==n['refine_policy']=='official_defaults' and v['surface']=='none'
    identity={k:v[k] for k in ('geometry','basis_namespace','mesh','grid_phase','surface','refine_policy')}
    identity['gem']=file_sha256(p/'frontend.gem')
    assert v['gem']==identity['gem'],'prepared GEM identity differs'
    assert (p/'frontend.pa+').read_bytes()==render_pa_plus_solution_model(m).encode(),'PA+ differs from declared mode model'
    identity['simion_identity']={'release':'SIMION 2020','executable_bytes':exe.stat().st_size,'executable_sha256':file_sha256(exe)}
    path=lambda role: {'path_role':role}
    operations = [
      dict(kind='gem2pa',name='local_field_gem2pa',arguments=['--nogui','--noprompt','gem2pa',path('gem'),path('template')]),
      dict(kind='verify_raw',name='local_field_raw_physical_ids',arguments=['--nogui','--noprompt','lua',path('verifier'),path('verification_spec'),path('raw_report'),'raw',path('template')]),
      dict(kind='refine_defaults',name='local_field_refine_declared_modes',arguments=['--nogui','--noprompt','lua',path('initializer'),path('template')])]
    operations += [dict(kind='export',name=f'local_field_export_{mode}',mode_id=mode,
        arguments=['--nogui','--noprompt','lua',path('exporter'),path(f'basis_{mode}'),path(f'response_{mode}')]) for mode in m['mode_ids']]
    sources={name:file_sha256(path) for name,path in {
     'initializer':runtime/'initialize_fast_adjust_pa_basis.lua',
     'exporter':runtime.parents[1]/'src/msplatform/backends/simion/resources/export_standalone_pa.lua',
     'pa_plus':p/'frontend.pa+',
     'field_support':runtime/'local_frontend_field_support.ps1',
     'field_plan':runtime/'frontend_field_plan.py',
     'response_set_contract':runtime.parents[1]/'src/msplatform/backends/simion/standalone_pa_response_set.py',
     'verifier':runtime/'verify_local_frontend_fields.lua'}.items()}
    identity['builder_identity']={name:sources[name] for name in ('initializer','exporter','pa_plus','verifier','response_set_contract')}
    identity['builder_identity']['basis_operations']=[op for op in operations if op['kind']!='verify_raw']
    assert identity['basis_namespace']==m and identity['mesh']==f['cell_mm_xyz'] and identity['grid_phase']==f['instance_origin_mm']
    ids=m['mode_ids'];names=[f'frontend.response_{i}.pa' for i in ids]+['standalone_response_set.json','standalone_mode_normalization.tsv']
    recipe={'schema_version':2,'source_location':'build_scratch','receipt_name':'standalone_response_set.json','exporter_path':str(runtime.parents[1]/'src/msplatform/backends/simion/resources/export_standalone_pa.lua'),
     'exports':[{'response_id':i,'source_name':f'frontend.pa{i}','standalone_name':f'frontend.response_{i}.pa'} for i in ids]}
    pitch=f['cell_mm_xyz']
    samples,physical = _bare_samples(f,m)
    return {'identity':identity,'source_provenance':sources,'basis_operations':operations,'cache_key':canonical_pa_family_cache_key(identity),'mode_ids':ids,'model_id':m['model_id'],'mode_count':m['mode_count'],'filenames':names,'recipe':recipe,
     'grid':[f['dimensions'][k] for k in ('nx','ny','nz')]+[pitch[a] for a in 'xyz'],'samples':samples,'physical_samples':physical}


def _bare_samples(f: dict,m: dict) -> tuple[list,list]:
    R=f['guide_registration']['rotation_upstream_to_downstream'];t=f['guide_registration']['translation_mm'];origin=f['instance_origin_mm'];pitch=f['cell_mm_xyz']
    samples=[];physical=[]
    for rod in f['guide_contract']['rod_array']['rods']:
     gu=cylinder_sample(rod,R,t,origin,pitch,f['dimensions'])
     physical.append(dict(label=f'rod_{rod["physical_electrode_id"]}',kind='rod',electrode_id=rod['physical_electrode_id'],gu=gu))
     for mode in m['modes']:
      samples.append([mode['mode_id'],f'rod_{rod["physical_electrode_id"]}',*gu,'1',mode['physical_electrode_coefficients'].get(str(rod['physical_electrode_id']),0),'unity_anchor' if rod['physical_electrode_id']==1 and mode['name'] in ('rod_common','rod_differential') else 'declared_sample'])
    axis=[0,0,(f['guide_contract']['rod_array']['rods'][0]['z_min_mm']+f['guide_contract']['rod_array']['rods'][0]['z_max_mm'])/2]
    world=[sum(R[a][k]*axis[k] for k in range(3))+t[a] for a in range(3)]
    gu=[int(math.floor((world[a]-origin[axis])/pitch[axis]+.5)) for a,axis in enumerate('xyz')]
    for mode in m['modes']:
     samples.append([mode['mode_id'],'guide_axis_finite',*gu,'0','any','declared_sample'])
    # Reference points use the actual provider geometry and PA frame: two-zone
    # solid/frame interiors, or three-zone declared zero-thickness ideal sheets.
    # Sheet-node voltage validation is not a claim about a real wire-grid collision surface.
    local=f['accelerator_local_region'];component=local['accelerator_component']
    A=component['transform']['rotation'];b=component['transform']['translation_mm'];data=local['canonical_electrodes']
    anchors=[(data['repeller']['component_electrode_id'],data['repeller']['solid_box_mm'],None)]
    if m['model_id']=='two_zone_linear_ring_bare_octupole_pa_plus_v1':
     anchors += [(g['component_electrode_id'],g['frame_outer_box_mm'],g['aperture_box_mm']) for g in data['grid_supports']]
    else:
     anchors += [(g['component_electrode_id'],g['sheet_box_mm'],None) for g in data['ideal_sheets']]
    assert len(anchors)==m['mode_count']-2,'physical endpoint geometry differs from supported mode count'
    for provider_id,box,hole in anchors:
     physical_id=component['local_electrode_ids'][str(provider_id)]
     endpoint_modes=[mode for mode in m['modes'] if mode['name'] not in ('rod_common','rod_differential') and mode['physical_electrode_coefficients'].get(str(physical_id))==1]
     assert len(endpoint_modes)==1,'physical endpoint lacks a unique unity mode'
     name=endpoint_modes[0]['name']
     gu=box_sample(box,hole,A,b,origin,pitch,f['dimensions'])
     physical.append(dict(label=name+'_metal',kind='endpoint',electrode_id=physical_id,gu=gu))
     for mode in m['modes']:
      coefficient=mode['physical_electrode_coefficients'].get(str(physical_id),0)
      samples.append([mode['mode_id'],name+'_metal',*gu,'1',coefficient,'unity_anchor' if mode['name']==name else 'declared_sample'])
    return samples,physical

from msplatform.backends.simion.physical_samples import (
    sample_node as sample_node,
    cylinder_sample as cylinder_sample,
    box_sample as box_sample,
)
