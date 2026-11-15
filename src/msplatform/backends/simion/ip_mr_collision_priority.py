"""Explicit IP–MR numerical priority policy; no native operation or field solve."""
from __future__ import annotations
import copy
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from msplatform.components.geometry_members import assembly_geometry_members
from msplatform.io.manifest_records import verify_record
from .compiler import CompiledSimionGeometry, _content_sha256
from .native_plans import rigid_iob_placement


def _record_json(name: str, record: Mapping[str, Any]) -> dict:
    verify_record(name, dict(record))
    return json.loads(Path(record['path']).read_text(encoding='utf8'))


def compile_ip_mr_priority(geometry: CompiledSimionGeometry, *, instances: Sequence[Mapping[str, Any]],
        roles: Mapping[str, str], background_bounds_mm: Sequence[Sequence[float]], boxes_record: Mapping[str, Any],
        clearance_record: Mapping[str, Any], source_record: Mapping[str, Any]) -> dict[str, Any]:
    """Bind explicit instance slots and the source/box-specific clearance records.

    Lengths are millimetres. This does not validate PA payloads, scalar halo,
    native priority semantics, collision occupancy or scientific qualification.
    """
    if not isinstance(geometry,CompiledSimionGeometry) or geometry.frontend_geometry.get('role')!='simion_ip_mr_complete_geometry':
        raise ValueError('complete selected IP–MR geometry required')
    required={'background','rf','ip','analyzer','detector'}
    if not isinstance(roles,Mapping) or set(roles)!=required or len(set(roles.values()))!=5 or any(not isinstance(v,str) or not v for v in roles.values()):
        raise ValueError('five distinct explicit numerical instance roles required')
    boxes=_record_json('priority boxes',boxes_record);evidence=_record_json('priority clearance',clearance_record)
    source=_record_json('priority canonical source',source_record)
    if evidence.get('role')!='diagnostic_cad_numeric_box_foreign_metal' or evidence.get('qualification') is not False:
        raise ValueError('box clearance evidence required')
    if str(evidence.get('boxes_sha256','')).upper()!=str(boxes_record['sha256']).upper() or str(evidence.get('source_sha256','')).upper()!=str(source_record['sha256']).upper():
        raise ValueError('clearance source or numerical box identity differs')
    snapshot=source['assembly'];geo=geometry.frontend_geometry
    if snapshot['composition_plan']!=geo['composition_plan'] or snapshot['components_resolved']!=geometry.components_resolved:
        raise ValueError('clearance physical composition differs from compiled geometry')
    for name in geo['composition_plan']['scope']['instance_ids']:
        if _content_sha256(snapshot['components_source'][name])!=geometry.provider_content_identities[name]['source_content_sha256']:
            raise ValueError('clearance component source identity differs')
    assets=geo['asset_components']; ip,rf=roles['ip'],roles['rf'];analyzer,detector=roles['analyzer'],roles['detector']
    if set(assets)!={ip,rf,analyzer,detector} or assets[ip]!=ip or assets[rf]!=rf or assets[analyzer]!=assets[detector]:
        raise ValueError('explicit instances differ from complete selected component assets')
    mr=assets[analyzer]
    if set(snapshot['composition_plan']['scope']['instance_ids'])!={ip,rf,mr}:
        raise ValueError('selected component scope differs')
    members=assembly_geometry_members(snapshot)
    mr_members=[m for m in members if m['instance_id']==mr]; rf_members=[m for m in members if m['instance_id']==rf]
    detector_members=[m for m in mr_members if m['electrode_group_id']=='detector']
    if len(detector_members)!=1: raise ValueError('one canonical detector physical member required')
    d_id=detector_members[0]['member_id']
    expected={('ip_box_vs_mr',m['instance_id'],m['member_id']) for m in mr_members}
    expected|={('detector_box_vs_analyzer',m['instance_id'],m['member_id']) for m in mr_members if m['member_id']!=d_id}
    expected|={('ip_box_vs_rf',m['instance_id'],m['member_id']) for m in rf_members}
    rows=evidence['rows'];actual=[(r['comparison'],r['instance_id'],r['member_id']) for r in rows]
    if len(actual)!=len(expected) or len(set(actual))!=len(actual) or set(actual)!=expected:
        raise ValueError('complete clearance member coverage required')
    profile=evidence['cad_profile'];tol=profile.get('length_error_bound_mm')
    if type(tol) not in (int,float) or not math.isfinite(tol) or tol<=0:
        raise ValueError('explicit positive CAD bound required')
    by_id={(m['instance_id'],m['member_id']):m for m in members}
    from msplatform.backends.comsol.assembly_geometry import _world_bounds
    def box_world(box):
        bounds=box['bounds'];pose=box['pose'];center=[(b[0]+b[1])/2 for b in bounds];size=[b[1]-b[0] for b in bounds]
        if any(not math.isfinite(x) or x<=0 for x in size):raise ValueError('invalid numerical box')
        # Reuse canonical transformed conservative-bound owner for the numerical box.
        return _world_bounds(dict(shape=dict(kind='box',center_mm=center,size_mm=size),transform=pose))
    world_boxes={name:box_world(boxes['assets'][name]) for name in (ip,detector)}
    for row in rows:
        member=by_id[(row['instance_id'],row['member_id'])]
        if row['source_refs']!=member['source_refs'] or row['electrode_group_id']!=member['electrode_group_id'] or row['classification']!='broadphase_clear':
            raise ValueError('clearance member evidence differs or is unresolved')
        lo,hi=_world_bounds(member);a,b=world_boxes[detector if row['comparison']=='detector_box_vs_analyzer' else ip]
        lower=math.sqrt(sum(max(0.,lo[i]-b[i],a[i]-hi[i])**2 for i in range(3)))
        if not math.isfinite(lower) or lower<=2*tol:raise ValueError('foreign member numerical-box clearance is not established')
    ordered=[roles[k] for k in ('background','rf','ip','analyzer','detector')]
    if len(instances)!=5 or {x.get('role') for x in instances}!=set(ordered):
        raise ValueError('five explicit background/RF/IP/analyzer/detector instances required')
    by_role={x['role']:x for x in instances};indices=[by_role[k].get('instance_index') for k in ordered];priorities=[by_role[k].get('priority_number') for k in ordered]
    if indices!=list(range(1,6)) or priorities!=indices or any(type(x) is not int for x in indices+priorities):
        raise ValueError('actual workbench indices and priorities must follow background/RF/IP/analyzer/detector order')
    for role in ordered[1:]:
        domain=geo['numerical_domains'][role];proposed=boxes['assets'][role];bounds=domain['bounds_mm']
        if proposed['bounds']!=[[bounds[a+'_min'],bounds[a+'_max']] for a in 'xyz'] or proposed['pitch']!=[domain['cell_mm_xyz'][a] for a in 'xyz'] or proposed['pose']!=geo['asset_poses'][role]:
            raise ValueError('certified numerical box, pitch or pose differs')
        row=by_role[role];grid=domain['dimensions'];expected_grid={**grid,**{'d'+a+'_mm':domain['cell_mm_xyz'][a] for a in 'xyz'}}
        expected_place=rigid_iob_placement(proposed['pose'],origin_mm=[domain['instance_origin_mm'][a] for a in 'xyz'])
        if row.get('grid')!=expected_grid or row.get('rotation')!=proposed['pose']['rotation'] or row.get('placement')!=expected_place:
            raise ValueError('actual physical PA instance grid or pose differs')
    if (len(background_bounds_mm)!=3 or any(len(x)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) for v in x) or x[0]>=x[1] for x in background_bounds_mm)):
        raise ValueError('explicit finite world background bounds required')
    background=by_role[roles['background']];grid=background.get('grid',{});placement=background.get('placement',{})
    if (background.get('rotation')!=[[1,0,0],[0,1,0],[0,0,1]] or any(placement.get(k)!=v for k,v in {'az_deg':0,'el_deg':0,'rt_deg':0,'scale':1}.items())):
        raise ValueError('background requires actual axis-aligned unit-scale placement')
    for axis,b in zip('xyz',background_bounds_mm,strict=True):
        n=grid.get('n'+axis);pitch=grid.get('d'+axis+'_mm');start=placement.get(axis+'_mm')
        if (type(n) is not int or n<2 or type(pitch) not in (int,float) or not math.isfinite(pitch) or pitch<=0 or type(start) not in (int,float) or not math.isfinite(start) or [start,start+(n-1)*pitch]!=list(b)):
            raise ValueError('background actual grid and bounds differ')
    for member in members:
        lo,hi=_world_bounds(member)
        if any(lo[i]<background_bounds_mm[i][0] or hi[i]>background_bounds_mm[i][1] for i in range(3)):
            raise ValueError('world background does not cover complete physical members')
    return dict(role='ip_mr_collision_priority',roles=copy.deepcopy(dict(roles)),instances=copy.deepcopy(sorted(instances,key=lambda row:row['instance_index'])),analyzer_slot=by_role[analyzer]['instance_index'],
        ip_box=copy.deepcopy(boxes['assets'][ip]),background_bounds_mm=copy.deepcopy(list(background_bounds_mm)),
        evidence_records=[dict(boxes_record),dict(clearance_record),dict(source_record)],
        limitations=['no occupancy or aperture validation','no scalar support or collision qualification'])


def render_ip_mr_instance_adjust(policy: Mapping[str, Any]) -> str:
    """Render a helper for the caller-owned SIMION instance_adjust hook."""
    if policy.get('role')!='ip_mr_collision_priority' or type(policy.get('analyzer_slot')) is not int or policy['analyzer_slot']<1:
        raise ValueError('verified IP–MR priority policy required')
    box=policy['ip_box'];pose=box['pose'];rot=pose['rotation'];origin=pose['translation_mm'];bounds=box['bounds']
    def num(x: float) -> str:
        if type(x) not in (int,float) or not math.isfinite(x):raise ValueError('finite transform required')
        return format(x,'.17g')
    terms=[' + '.join(f'({num(rot[i][j])})*(ion_p{"xyz"[i]}_mm-({num(origin[i])}))' for i in range(3)) for j in range(3)]
    lines=['local function ip_mr_priority_adjust()',f'  if ion_instance ~= {policy["analyzer_slot"]} then return end']
    lines.extend(f'  local q{i+1} = {term}' for i,term in enumerate(terms))
    lines.append('  if '+ ' and '.join(f'q{i+1} >= ({num(b[0])}) and q{i+1} <= ({num(b[1])})' for i,b in enumerate(bounds))+' then ion_instance = 0 end')
    return '\n'.join([*lines,'end',''])




def project_ip_mr_collision_iob(geometry: CompiledSimionGeometry, *, instances: Sequence[Mapping[str, Any]],
        roles: Mapping[str, str], background_bounds_mm: Sequence[Sequence[float]], boxes_record: Mapping[str, Any],
        clearance_record: Mapping[str, Any], source_record: Mapping[str, Any],
        asset_records: Mapping[str, Mapping[str, Mapping[str, Any]]], seed_record: Mapping[str, Any],
        empty_control_record: Mapping[str, Any], output_iob: Path) -> dict[str, Any]:
    """Produce a source-free five-slot native spec from the verified policy and exact records.

    The caller freezes and protects every returned record for both native operations.
    Node witnesses and background readback are checked by the native writer; this
    projection does not prove full collision occupancy or native priority behavior.
    """
    policy=compile_ip_mr_priority(geometry,instances=instances,roles=roles,
        background_bounds_mm=background_bounds_mm,boxes_record=boxes_record,
        clearance_record=clearance_record,source_record=source_record)
    if set(asset_records)!=set(policy['roles'].values()):
        raise ValueError('collision records must cover exactly the five validated roles')
    records=[dict(seed_record),dict(empty_control_record),*copy.deepcopy(policy['evidence_records'])]
    from .resources import STRUCTURAL_SEEDS
    verify_record('collision seed',dict(seed_record));verify_record('zero particle control',dict(empty_control_record))
    if (seed_record['bytes'],str(seed_record['sha256']).lower())!=STRUCTURAL_SEEDS[5]:
        raise ValueError('authenticated five-slot structural seed required')
    rows=[];paths=set()
    for row in policy['instances']:
        name=row['role']; supplied=asset_records[name]
        keys={'pa'} if name==policy['roles']['background'] else {'pa','fractional_surface','surface_witnesses'}
        if name!=policy['roles']['background'] and 'surface_state' in supplied:
            keys={'pa','surface_witnesses','surface_state'} | ({'fractional_surface'} if 'fractional_surface' in supplied else set())
        if set(supplied)!=keys:raise ValueError('collision PA and witness record closure differs')
        row=copy.deepcopy(row)
        for key in sorted(keys):
            record=dict(supplied[key]);verify_record(name+' '+key,record)
            path=Path(record['path']).resolve(strict=True)
            if path in paths:raise ValueError('collision input records must have distinct paths')
            paths.add(path);records.append(record)
            row['path' if key=='pa' else key]=str(path)
        if Path(row['path']).suffix.lower()!='.pa':raise ValueError('collision input requires an ordinary .pa')
        if name!=policy['roles']['background']:
            if 'fractional_surface' not in row and 'surface_state' in row:
                row['fractional_surface']=str(Path(row['path']).with_suffix('.pa-surf'))
            if Path(row['fractional_surface'])!=Path(row['path']).with_suffix('.pa-surf'):
                raise ValueError('collision fractional companion must match the PA stem')
            row['physical_samples']=copy.deepcopy(geometry.frontend_geometry['raw_physical_samples'][name])
            if not row['physical_samples']:raise ValueError('canonical physical witnesses required')
        rows.append(row)
    output=Path(output_iob).absolute()
    if output.suffix.lower()!='.iob' or output.exists() or output.resolve() in paths:
        raise ValueError('fresh IOB output path required')
    seed=Path(seed_record['path']).resolve(strict=True)
    spec=dict(schema_version=1,role='ip_mr_collision_iob_build',collision_roles=copy.deepcopy(policy['roles']),
        instances=rows,seed_iob=str(seed),output_iob=str(output),empty_particle_control=str(Path(empty_control_record['path']).resolve(strict=True)),
        bootstrap_paths=[str(seed.parent/f'iob_seed_placeholder_{i:02d}.pa0') for i in range(1,6)])
    return dict(policy=policy,spec=spec,immutable_records=records)
