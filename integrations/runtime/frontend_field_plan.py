"""Pure frontend response construction plan, shared by native field consumers."""
from __future__ import annotations
import json,math
from pathlib import Path
from common.contracts.file_identity import file_sha256
from common.simion.pa_family_cache import canonical_pa_family_cache_key
from integrations.runtime.single_flight_electrode_contract import require_pa_plus_solution_model,render_pa_plus_solution_model


def sample_node(point: list, rotation: list, translation: list, origin: dict, pitch: dict,
                dimensions: dict) -> tuple[list[int], list[float]]:
    """Snap a sample only, then invert its single physical pose for body checks."""
    world = [sum(rotation[a][k]*point[k] for k in range(3))+translation[a] for a in range(3)]
    if not all(math.isfinite(value) for value in world):
        raise ValueError("nonfinite physical sample position")
    gu = [int(math.floor((world[a]-origin[axis])/pitch[axis]+.5)) for a,axis in enumerate('xyz')]
    if any(not 0 <= gu[a] < dimensions['n'+axis] for a,axis in enumerate('xyz')):
        raise ValueError("physical sample is outside declared PA bounds")
    snapped = [origin[axis]+gu[a]*pitch[axis] for a,axis in enumerate('xyz')]
    body = [sum(rotation[a][k]*(snapped[a]-translation[a]) for a in range(3)) for k in range(3)]
    return gu, body


def cylinder_sample(rod: dict, rotation: list, translation: list, origin: dict,
                    pitch: dict, dimensions: dict) -> list[int]:
    """Require the snapped point strictly inside this actual rod segment."""
    point = [rod['center_x_mm'], rod['center_y_mm'], (rod['z_min_mm']+rod['z_max_mm'])/2]
    gu, body = sample_node(point, rotation, translation, origin, pitch, dimensions)
    if (not rod['z_min_mm'] < body[2] < rod['z_max_mm'] or
            (body[0]-point[0])**2+(body[1]-point[1])**2 >= rod['radius_mm']**2):
        raise ValueError("rod sample not strictly inside its actual segment metal")
    return gu


def box_sample(box: dict, hole: dict | None, rotation: list, translation: list,
               origin: dict, pitch: dict, dimensions: dict, *,
               local_z_bounds_mm: tuple[float, float] | None = None) -> list[int] | None:
    """Sample original metal, optionally intersected with an explicit local Z interval.

    The entrance-domain caller guarantees the complete X extent and center Y.
    Only a geometrically disjoint Z interval returns None; an intersecting body
    without a legal grid node still fails the original metal/sheet checks.
    """
    point = [(box[f'{axis}_min_mm']+box[f'{axis}_max_mm'])/2 for axis in 'xyz']
    if local_z_bounds_mm is not None:
        lo, hi = max(box['z_min_mm'], local_z_bounds_mm[0]), min(box['z_max_mm'], local_z_bounds_mm[1])
        if lo > hi:
            return None
        point[2] = (lo+hi)/2
    if hole:
        point[0] = (hole['x_max_mm']+box['x_max_mm'])/2
    gu, body = sample_node(point, rotation, translation, origin, pitch, dimensions)
    for k, axis in enumerate('xyz'):
        lo, hi = box[f'{axis}_min_mm'], box[f'{axis}_max_mm']
        if lo == hi:
            if not math.isclose(body[k], lo, rel_tol=0, abs_tol=32*math.ulp(max(1., abs(lo)))):
                raise ValueError("ideal-sheet anchor not represented at declared PA node plane")
        elif not lo < body[k] < hi:
            raise ValueError("endpoint/ring anchor not strictly inside actual metal extent")
    if hole and all(hole[f'{axis}_min_mm'] <= body[k] <= hole[f'{axis}_max_mm'] for k,axis in enumerate('xyz')):
        raise ValueError("metal sample landed in aperture")
    return gu


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
    identity['builder_identity']={name:file_sha256(path) for name,path in {
     'initializer':runtime/'initialize_fast_adjust_pa_basis.lua',
     'exporter':runtime.parents[1]/'common/simion/export_standalone_pa.lua',
     'pa_plus':p/'frontend.pa+',
     'field_support':runtime/'local_frontend_field_support.ps1',
     'field_plan':runtime/'frontend_field_plan.py',
     'response_set_contract':runtime.parents[1]/'common/simion/standalone_pa_response_set.py',
     'verifier':runtime/'verify_local_frontend_fields.lua'}.items()}
    assert identity['basis_namespace']==m and identity['mesh']==f['cell_mm_xyz'] and identity['grid_phase']==f['instance_origin_mm']
    ids=m['mode_ids'];names=[f'frontend.response_{i}.pa' for i in ids]+['standalone_response_set.json','standalone_mode_normalization.tsv']
    recipe={'schema_version':2,'source_location':'build_scratch','receipt_name':'standalone_response_set.json','exporter_path':str(runtime.parents[1]/'common/simion/export_standalone_pa.lua'),
     'exports':[{'response_id':i,'source_name':f'frontend.pa{i}','standalone_name':f'frontend.response_{i}.pa'} for i in ids]}
    pitch=f['cell_mm_xyz']
    samples,physical = _bare_samples(f,m)
    return {'identity':identity,'cache_key':canonical_pa_family_cache_key(identity),'mode_ids':ids,'model_id':m['model_id'],'mode_count':m['mode_count'],'filenames':names,'recipe':recipe,
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
