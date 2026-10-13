"""Export frozen physical MR conductors using the shared SolidWorks 2022 bridge.

Original Stripe native solids preserve exact B-splines; owned simulation
variants suppress circular mounting cuts without changing beam slots.
Other resolved parts use local axes (project y,z,x); assembly restores mm.
Reference sheets are zero-thickness; no manufacturing wall is invented.
"""
from __future__ import annotations

import argparse
import copy
import csv
import json
import hashlib
import math
import re
import struct
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


def rectangle(box: list[float]) -> dict:
    """Represent a project box as an x-directed extrusion."""
    return dict(x=[box[0],box[3]],polygon_yz_mm=[
        [box[1],box[2]],[box[4],box[2]],[box[4],box[5]],[box[1],box[5]]])


def original_stripe_instances(parts: list[dict],geometry: dict,curve_contract: dict,
    native_audit: dict,parent_audit: dict,child_pose: dict,frame: dict) -> list[dict]:
    """Compose recorded real poses and match exact native controls, never fit."""
    from .compose_top_level_cad_pose import compose
    if native_audit.get('status')!='success' or parent_audit.get('status')!='success':
        raise ValueError('Original native/parent read evidence is incomplete')
    if frame['target_frame']!=geometry['frame_id']:raise ValueError('Original native target frame differs')
    f=frame['target_from_source'];rotation=f['rotation']
    frame_array=[rotation[column][row] for row in range(3) for column in range(3)]+[
        float(v)/1000 for v in f['translation_mm']]+[1.,0.,0.,0.]
    originals={int(d['name'].split('ion foil ')[1].split('.')[0]):d for d in native_audit['documents']}
    children=child_pose['components'];theory=curve_contract['dual_stripe'];result=copy.deepcopy(parts)
    instances={'s1_electrode_11':(11,1,'ion foil 1-3'),'s1_electrode_12':(12,1,'ion foil 1-4'),
        's2_electrode_13':(13,3,'ion foil 3-3'),'s2_electrode_14':(14,3,'ion foil 3-4'),
        'central_ion_foil_ground':(15,2,'ion foil 2-2')}
    for spec in result:
        if spec['name'] not in instances:continue
        eid,number,suffix=instances[spec['name']]
        # A ground voltage/id is shared by unrelated physical pieces. Original
        # geometry and pose belong only to these audited physical instances.
        if spec['electrode_namespace']!='analyzer' or spec['electrode_id']!=eid:
            raise ValueError('Original physical instance electrical identity differs')
        doc=originals[number]
        source=Path(doc['path'])
        if hashlib.sha256(source.read_bytes()).hexdigest()!=geometry['cad_body_topology_identity']['source_native_sha256'][f'ion_foil_{number}']:
            raise ValueError('Original native identity differs from frozen geometry')
        matches=[c for c in children if c['instance_name'].endswith(suffix)]
        if len(matches)!=1:raise ValueError('Original physical instance mapping is not unique')
        top=compose(matches[0]['solidworks_transform_array'],parent_audit['parent']['transform'])
        top_array=sum(top['rotation'],[])+top['translation_m']+[1.,0.,0.,0.]
        world=compose(top_array,frame_array)
        transform=sum(world['rotation'],[])+world['translation_m']+[1.,0.,0.,0.]
        definitions=[]
        if number in (1,3):
            edges=theory['theory_profile'][f'set_{1 if number==1 else 2}']
            sign=1 if spec['electrode_id'] in (11,13) else -1
            definitions=[(k,v,sign) for k,v in edges.items() if isinstance(v,dict) and v.get('basis')=='cubic_bspline']
        else:
            central=theory['central_ground_profile']
            definitions=[(side+'.'+k,v,1) for side in ('positive_x','negative_x','terminal_profile')
                for k,v in central[side].items() if isinstance(v,dict) and v.get('basis')=='cubic_bspline']
        evidence=[]
        for label,definition,sign in definitions:
            candidates=[];target=definition['control_points_yz_mm']
            for edge in doc['body_bspline_edges']:
                if edge['order']!=definition['order'] or len(edge['knots'])!=len(definition['knots']) or len(edge['control_points_local_m'])!=len(target):continue
                controls=[[sum(float(p[i])*transform[i*3+j] for i in range(3))*1000+transform[9+j]*1000
                    for j in range(3)] for p in edge['control_points_local_m']]
                for reverse in (False,True):
                    points=controls[::-1] if reverse else controls
                    knots=[edge['knots'][0]+edge['knots'][-1]-k for k in edge['knots'][::-1]] if reverse else edge['knots']
                    dk=max(abs(a-b) for a,b in zip(knots,definition['knots'],strict=True))
                    dp=max(abs(point[j+1]-expected[j]*(sign if j==1 else 1))
                        for point,expected in zip(points,target,strict=True) for j in range(2))
                    candidates.append((dp,dk,edge['edge_index'],reverse))
            if not candidates:raise ValueError('Original B-spline definition missing: '+label)
            dp,dk,index,reverse=min(candidates)
            if dp>1e-5 or dk>1e-12:raise ValueError('Original B-spline controls/knots differ: '+label)
            evidence.append(dict(definition=label,max_control_delta_mm=dp,max_knot_delta=dk,edge_index=index,reverse=reverse))
        spec.update(geometry_kind='original_native_solid',original_native=str(source),project_transform=transform,
            original_exact_local_box_mm=doc['exact_local_box_mm'],original_volume_mm3=doc['volume_mm3'],
            original_body_bspline_edges=doc['body_bspline_edges'],
            original_curve_matches=evidence,curve_representation='original_native_bspline_and_features__not_sample_fit',
            simulation_representation='frozen_sampled_polygon__non_beam_fastener_details_omitted')
    return result


def compile_parts(geometry: dict, authority: dict) -> list[dict]:
    """Group separate physical/electrical bodies from frozen resolved geometry."""
    parts=[]; voltages=authority['analyzer_electrode_voltages_v']
    if len(voltages)!=20 or not all(math.isfinite(v) for v in voltages):
        raise ValueError('Complete finite twenty-slot voltage authority required')

    def add(name,group,eid,solids,cuts=(),*,namespace='analyzer',voltage=None,reference=False):
        parts.append(dict(name=name,group=group,electrode_namespace=namespace,electrode_id=eid,
            voltage_v=voltages[eid-1] if voltage is None else voltage,
            solids=copy.deepcopy(solids),cuts=copy.deepcopy(cuts),
            geometry_kind='reference_sheet' if reference else 'physical_conductor'))

    for e in geometry['mirror_electrodes']:
        side='positive' if e['box'][2]>0 else 'negative'
        add(f"mirror_{side}_e{e['id']:02}",'mirror',e['id'],[rectangle(e['box'])],[rectangle(e['beam_slot'])])
    for i,e in enumerate(geometry['mirror_ground_shields'],1):
        cuts=[rectangle(geometry['mirror_inner_shield_slot'])] if e['role']=='inner_stripe_facing_4mm_slot' else []
        add(f'mirror_ground_shield_{i}','ground_shield',15,[rectangle(e['box'])],cuts)
    for i,e in enumerate(geometry['mirror_e_closures'],1):
        add(f'mirror_outer_closure_{i}','mirror',e['id'],[rectangle(e['box'])])
    for e in geometry['stripe_electrodes']:
        add(f"s{1 if e['id'] in (11,12) else 2}_electrode_{e['id']}",'stripe',e['id'],
            [dict(x=e['x'],polygon_yz_mm=e[k]) for k in ('polygon_yz_mm','terminal_polygon_yz_mm')],
            [rectangle(geometry['stripe_slot'])])
    add('central_ion_foil_ground','ground_shield',15,
        [dict(x=e['x'],polygon_yz_mm=e['polygon_yz_mm']) for e in geometry['central_ground_electrodes']],
        [rectangle(e) for e in geometry['central_ground_slots']])
    for e in geometry['prism_electrodes']:
        for i,body in enumerate(e['parts']):
            add(f"p{e['id']-15}_{'negative_x' if i==0 else 'positive_x'}",'prism',e['id'],[body])
    for e in geometry['prism_ground_shields']:
        add(f"p{1 if e['id']==18 else 2}_ground_shield",'ground_shield',e['id'],e['body_sections'],
            [dict(x=e['x'],polygon_yz_mm=e['prism_clearance_polygon_yz_mm'])]
            +[rectangle(b) for b in e.get('rectangular_slots_mm',[])])
    assembly=authority['assembly']; oa=assembly['accelerator_resolved_electrodes']
    offset=[a+b for a,b in zip(oa['local_to_pa_translation_mm'],assembly['accelerator_iob_origin_mm'],strict=True)]
    component_v={(e['component_namespace'],e['component_electrode_id']):e['voltage_v'] for e in authority['component_voltages_v']}

    def box(b):
        return [b[f'{axis}_{side}_mm']+offset[i] for side in ('min','max') for i,axis in enumerate('xyz')]

    def oa_part(name,e,outer,holes=()):
        body=box(e[outer]); cuts=[];redundant=[]
        for h in holes:
            cut=box(e[h])
            if h=='exit_opening_box_mm' and 'cavity_box_mm' in e:
                cavity=box(e['cavity_box_mm'])
                if all(cavity[i]<=cut[i] and cut[i+3]<=cavity[i+3] for i in range(3)):
                    # Exact frozen set difference: the cavity already removes
                    # this opening. SolidWorks correctly rejects a no-body cut.
                    redundant.append(dict(source=h,box_mm=cut,reason='fully_contained_in_declared_cavity'))
                    continue
            if h=='aperture_box_mm':
                pad=body[5]-body[2];cut[2]-=pad;cut[5]+=pad
            elif h=='exit_opening_box_mm':
                pad=cut[5]-cut[2];cut[2]-=pad;cut[5]+=pad
            cuts.append(rectangle(cut))
        eid=e['component_electrode_id']
        add(name,'oa',eid,[rectangle(body)],cuts,namespace='accelerator',voltage=component_v[('accelerator',eid)])
        if redundant:parts[-1]['declared_redundant_cuts']=redundant

    oa_part('oa_enclosure',oa['grounded_enclosure'],'outer_box_mm',('cavity_box_mm','exit_opening_box_mm'))
    oa_part('oa_repeller',oa['repeller'],'solid_box_mm')
    for i,e in enumerate(oa['grid_supports'],1):
        oa_part(f'oa_grid_frame_{i}',e,'frame_outer_box_mm',('aperture_box_mm',))
        b=e['ideal_sheet_mm'];z=b['z_mm']+offset[2]
        sheet=[b['x_min_mm']+offset[0],b['y_min_mm']+offset[1],z,b['x_max_mm']+offset[0],b['y_max_mm']+offset[1],z]
        add(f'oa_ideal_grid_sheet_{i}','reference',e['component_electrode_id'],[dict(box_mm=sheet)],
            namespace='accelerator',voltage=component_v[('accelerator',e['component_electrode_id'])],reference=True)
    for i,e in enumerate(oa['rings'],1):
        oa_part(f'oa_ring_{i:02}',e,'outer_box_mm',('aperture_box_mm',))
    d=geometry['detector']
    if d!=assembly['detector']:
        raise ValueError('Detector resolved assembly mismatch')
    add('detector','detector',d['id'],[rectangle(d['box'])],namespace='detector',voltage=component_v[('detector',d['id'])])
    b=authority['boundary_contract']['box_mm'];full=[-b[3],b[1],b[2],b[3],b[4],b[5]]
    for axis in range(3):
        for side in (0,1):
            face=list(full);face[axis]=face[axis+3]=full[axis+3*side]
            add(f"c0_reference_{'xyz'[axis]}_{side}",'reference',0,[dict(box_mm=face)],namespace='boundary',voltage=0,reference=True)
    return parts


def member(value):
    """Read a parameterless late-bound COM member."""
    # COM dispatch objects are Python-callable via their default member, but
    # Feature/Body interfaces have no default member. Do not invoke objects.
    return value() if callable(value) and not hasattr(value,'_oleobj_') else value


def build_operation(document, operation: dict, cut: bool) -> None:
    """Create native extrude/cut from the unmodified resolved YZ polygon."""
    feature=member(document.FirstFeature)
    while feature is not None and member(feature.GetTypeName2)!='RefPlane':
        feature=member(feature.GetNextFeature)
    if feature is None or not feature.Select2(False,0):
        raise RuntimeError('Clean template front plane is unavailable')
    manager=document.SketchManager;manager.InsertSketch(True);manager.AddToDB=True
    points=operation['polygon_yz_mm']
    try:
        for p,q in zip(points,points[1:]+points[:1],strict=True):
            if p!=q and manager.CreateLine(p[0]/1000,p[1]/1000,0,q[0]/1000,q[1]/1000,0) is None:
                raise RuntimeError('Sketch line creation failed')
    finally:manager.AddToDB=False
    manager.InsertSketch(True)
    lo,hi=operation['x']
    # Official cut default points against the sketch normal; reverse it so
    # both operations run from the declared lower x to the upper x.
    common=[True,False,cut,0,0,(hi-lo)/1000,0,False,False,False,False,0,0,False,False,False,False]
    if cut:
        result=document.FeatureManager.FeatureCut3(*common,False,False,True,False,False,False,3,abs(lo)/1000,lo<0)
    else:
        result=document.FeatureManager.FeatureExtrusion2(*common,True,False,True,3,abs(lo)/1000,lo<0)
    if result is None:raise RuntimeError(f'Native feature failed cut={cut} x={lo,hi}')


def build_sheet(document, box: list) -> None:
    """Use official planar surface API, without adding sheet thickness."""
    fixed=next(i for i in range(3) if box[i]==box[i+3]);axes=[i for i in range(3) if i!=fixed]
    points=[]
    for a,b in [(0,0),(1,0),(1,1),(0,1)]:
        xyz=list(box[:3]);xyz[axes[0]]=box[axes[0]+3*a];xyz[axes[1]]=box[axes[1]+3*b]
        points.append([xyz[1]/1000,xyz[2]/1000,xyz[0]/1000])
    manager=document.SketchManager;manager.Insert3DSketch(True)
    segments=[manager.CreateLine(*a,*b) for a,b in zip(points,points[1:]+points[:1],strict=True)]
    manager.Insert3DSketch(True);document.ClearSelection2(True)
    selection=member(document.SelectionManager.CreateSelectData);selection.Mark=1
    for segment in segments:
        if segment is None or not segment.Select4(True,selection):raise RuntimeError('Sheet boundary selection failed')
    if not member(document.InsertPlanarRefSurface):raise RuntimeError('Reference sheet creation failed')


def exact_body_bounds_mm(body,transform: list[float]) -> list[float]:
    """Six official exact extrema of one rigidly placed body, in mm."""
    box=[]
    for sign in (-1,1):
        for axis in range(3):
            direction=[sign*transform[i*3+axis] for i in range(3)]
            found,*xyz=body.GetExtremePoint(*direction,0.0,0.0,0.0)
            if not found:raise RuntimeError('Exact body extreme point unavailable')
            value=sum(float(xyz[i])*transform[i*3+axis] for i in range(3))*transform[12]+transform[9+axis]
            if not math.isfinite(value):raise RuntimeError('Nonfinite body extreme point')
            box.append(value*1000)
    return box


def body_bounds_mm(document,transform: list[float]) -> list[float]:
    """Exact extrema after the official component rigid transform, in mm."""
    bodies=list(document.GetBodies2(0,False) or [])+list(document.GetBodies2(1,False) or [])
    if not bodies:raise RuntimeError('CAD document has no body')
    boxes=[exact_body_bounds_mm(b,transform) for b in bodies]
    local=[min(b[i] for b in boxes) for i in range(3)]+[max(b[i+3] for b in boxes) for i in range(3)]
    return local


PROJECT_TRANSFORM=[0,1,0,0,0,1,1,0,0,0,0,0,1,0,0,0]


def bounds_mm(document) -> list[float]:
    """Exact part bounds, mapped once to project axes."""
    return body_bounds_mm(document,PROJECT_TRANSFORM)


def volume_mm3(document) -> float:
    """Read official solid-body mass properties at unit density, ignoring sheets."""
    return sum(float(b.GetMassProperties(1.0)[3])*1e9 for b in (document.GetBodies2(0,False) or []))


def mass_property_volume_levels(document) -> dict:
    """Installed IMassProperty2: compare low/medium/high integration, no edit."""
    document.ClearSelection2(True)
    mass=member(document.Extension.CreateMassProperty2)
    if mass is None:
        if document.GetBodies2(0,False):raise RuntimeError('Solid mass-property object unavailable')
        return {'0':0.0,'1':0.0,'2':0.0}  # zero-thickness ideal grids/C0 have no solid volume
    mass.UseSystemUnits=True
    levels={}
    for level in (0,1,2):
        mass.AccuracyLevel=level
        if mass.AccuracyLevel!=level:raise RuntimeError('Mass-property accuracy rejected')
        if not member(mass.Recalculate):raise RuntimeError('Mass-property recalculation failed')
        levels[str(level)]=float(mass.Volume)*1e9
    return levels


def expected_bounds_mm(spec: dict) -> list[float]:
    """Bounds of the frozen solids; declared internal cuts retain outer extrema."""
    boxes=[]
    for op in spec['solids']:
        if 'box_mm' in op:boxes.append(op['box_mm']);continue
        p=op['polygon_yz_mm']
        boxes.append([op['x'][0],min(v[0] for v in p),min(v[1] for v in p),
                      op['x'][1],max(v[0] for v in p),max(v[1] for v in p)])
    return [min(b[i] for b in boxes) for i in range(3)]+[max(b[i+3] for b in boxes) for i in range(3)]


def inspect_assembly(document,*,high_accuracy: bool=False,sample_root: Path|None=None,sample_count: int=2001) -> dict:
    """Read resolved native/STEP leaf count and physical volume without saving."""
    leaves=[]
    for comp in (document.GetComponents(True) or []):
        model=member(comp.GetModelDoc2)
        if model is None:raise RuntimeError('Saved assembly has an unresolved/missing component')
        if member(model.GetType)==1:
            transform=[float(v) for v in comp.Transform2.ArrayData]
            levels=mass_property_volume_levels(model) if high_accuracy else None
            samples=save_trimmed_curve_samples(model,transform,sample_root/str(len(leaves)),sample_count=sample_count) if sample_root else []
            leaves.append(dict(name=str(member(comp.Name2)),volume_mm3=levels['2'] if levels else volume_mm3(model),
                               native_reference=str(member(model.GetPathName)),
                               solid_count=len(model.GetBodies2(0,False) or []),sheet_count=len(model.GetBodies2(1,False) or []),
                               transform=transform,world_box_mm=body_bounds_mm(model,transform),
                               mass_property_volume_levels_mm3=levels,
                               bspline_edges=inspect_bspline_edges(model) if high_accuracy else None,
                               trimmed_curve_sample_files=samples))
    return dict(leaf_count=len(leaves),volume_mm3=sum(x['volume_mm3'] for x in leaves),leaves=leaves)


def inspect_exchange_geometry(document,*,sample_root: Path|None=None) -> dict:
    """Read assembly leaves or flattened Parasolid world bodies without saving."""
    if member(document.GetType)==2:
        result=inspect_assembly(document,high_accuracy=sample_root is not None,sample_root=sample_root);result['representation']='assembly_leaves';return result
    if member(document.GetType)!=1:raise RuntimeError('Neutral CAD must contain a part or assembly')
    identity=[1,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0];leaves=[]
    samples=save_trimmed_curve_samples(document,identity,sample_root,sample_count=2001) if sample_root else []
    for kind in (0,1):
        for index,body in enumerate(document.GetBodies2(kind,False) or []):
            leaves.append(dict(name=f'body_{kind}_{index}',native_reference='',
                solid_count=int(kind==0),sheet_count=int(kind==1),
                volume_mm3=float(body.GetMassProperties(1.0)[3])*1e9 if kind==0 else 0,
                world_box_mm=exact_body_bounds_mm(body,identity),trimmed_curve_sample_files=[samples[len(leaves)]] if samples else []))
    return dict(leaf_count=len(leaves),volume_mm3=sum(x['volume_mm3'] for x in leaves),leaves=leaves,
                representation='flattened_world_bodies__hierarchy_in_native_assembly_and_bom')


def verify_assembly_leaves(inspected: dict,rows: list[dict],*,native: bool,engineering_step: bool=False) -> None:
    """Match every reopened leaf's world extrema/volume, not just a total."""
    if inspected['leaf_count']!=len(rows):raise RuntimeError('Reopened assembly leaf count differs')
    remaining=list(rows)
    for leaf in inspected['leaves']:
        if native:
            references=[r for r in remaining if Path(leaf['native_reference']).resolve()==Path(r['native']).resolve()]
            if len(references)!=1:raise RuntimeError('Saved native leaf world geometry reference differs')
            if max(abs(a-b) for a,b in zip(leaf['transform'],references[0].get('project_transform',PROJECT_TRANSFORM),strict=True))>1e-12:
                raise RuntimeError('Saved native leaf world pose differs')
        matches=[r for r in remaining if
            max(abs(a-b) for a,b in zip(leaf['world_box_mm'],r['project_box_mm'],strict=True))<=(0.005 if engineering_step and not native else 1e-5)
            and (engineering_step and not native or abs(leaf['volume_mm3']-r['volume_mm3'])<=max(1e-5,r['volume_mm3']*1e-9))
            and all(leaf.get(k)==r[k] for k in ('solid_count','sheet_count') if k in r)
            and (not native or Path(leaf['native_reference']).resolve()==Path(r['native']).resolve())]
        if not matches:
            nearest=min(remaining,key=lambda r:max(abs(a-b) for a,b in zip(leaf['world_box_mm'],r['project_box_mm'],strict=True)))
            detail=dict(actual_name=leaf['name'],actual_reference=leaf['native_reference'],
                actual_box_mm=leaf['world_box_mm'],actual_volume_mm3=leaf['volume_mm3'],
                nearest_name=Path(nearest['native']).stem,
                box_delta_mm=[a-b for a,b in zip(leaf['world_box_mm'],nearest['project_box_mm'],strict=True)],
                volume_delta_mm3=leaf['volume_mm3']-nearest['volume_mm3'])
            raise RuntimeError('Reopened leaf world geometry/volume does not match frozen part: '+json.dumps(detail))
        remaining.remove(matches[0])
        if engineering_step and not native:
            reference=matches[0]
            leaf['physical_component']=reference['name']
            leaf['volume_delta_mm3']=leaf['volume_mm3']-reference['volume_mm3']
            leaf['volume_delta_relative']=leaf['volume_delta_mm3']/reference['volume_mm3'] if reference['volume_mm3'] else None
            leaf['max_extrema_delta_mm']=max(abs(a-b) for a,b in zip(leaf['world_box_mm'],reference['project_box_mm'],strict=True))
            leaf['trimmed_edge_validation']=compare_trimmed_curve_samples(reference.get('trimmed_curve_sample_files',[]),leaf.get('trimmed_curve_sample_files',[]))


def close_owned_parts(sw,titles: list[str],rows: list[dict]) -> None:
    """Close only this assembly's preloaded part windows before cold reopen."""
    for title in dict.fromkeys(titles):sw.CloseDoc(title)
    for row in rows:
        if sw.GetOpenDocumentByName(row['native']) is not None:
            raise RuntimeError('Owned native part remains open before cold assembly reopen: '+row['native'])


def open_reference_document(sw,path: str,kind: int,error,warning):
    """Official OpenDoc6 TIPS: avoid a separate part SceneGraph per preload."""
    sw.DocumentVisible(False,1)
    try:return sw.OpenDoc6(path,kind,3,'',error,warning)
    finally:sw.DocumentVisible(True,1)


def save_step_document(sw,document,path: Path):
    """Official AP214 save avoids the observed AP203 assembly knit loss."""
    from common.solidworks.import_step_to_solidworks import save_native_document
    original=sw.GetUserPreferenceIntegerValue(75)  # installed swStepAP
    try:
        if not sw.SetUserPreferenceIntegerValue(75,214):raise RuntimeError('STEP AP214 setting rejected')
        return save_native_document(document,path)
    finally:sw.SetUserPreferenceIntegerValue(75,original)


def save_exchange_document(sw,document,path: Path):
    """Official extension-selected SaveAs; scope and restore Parasolid options."""
    from common.solidworks.import_step_to_solidworks import save_native_document
    document.ClearSelection2(True)
    if path.suffix=='.step':return save_step_document(sw,document,path)
    if path.suffix!='.x_t':raise ValueError('Unsupported engineering exchange extension')
    # Installed swconst.chm and 2022 PIA: swParasolidOutputVersion=89,
    # latest=0; swXTAssemSaveFormat toggle=12. Flatten only the exchange file;
    # editable SLDASM references/poses and BOM remain independently validated.
    version=sw.GetUserPreferenceIntegerValue(89)
    is_assembly=member(document.GetType)==2
    flatten=bool(sw.GetUserPreferenceToggle(12)) if is_assembly else None
    try:
        sw.SetUserPreferenceIntegerValue(89,0)
        if sw.GetUserPreferenceIntegerValue(89)!=0:raise RuntimeError('Parasolid latest version rejected')
        if is_assembly:
            sw.SetUserPreferenceToggle(12,True)
            if not sw.GetUserPreferenceToggle(12):raise RuntimeError('Parasolid flat assembly option rejected')
        return save_native_document(document,path)
    finally:
        sw.SetUserPreferenceIntegerValue(89,version)
        if is_assembly:sw.SetUserPreferenceToggle(12,flatten)
        if sw.GetUserPreferenceIntegerValue(89)!=version or (is_assembly and bool(sw.GetUserPreferenceToggle(12))!=flatten):
            raise RuntimeError('Parasolid export preferences not restored')


def gui_resource_counts(sw) -> dict:
    """Small diagnostic only; unavailable Windows counts never change gates."""
    try:
        import ctypes
        from ctypes import wintypes
        pid=int(member(sw.GetProcessID))
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        user=ctypes.WinDLL('user32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        user.GetGuiResources.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        user.GetGuiResources.restype=wintypes.DWORD
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:raise OSError(ctypes.get_last_error(),'OpenProcess limited query failed')
        try:
            result=dict(pid=pid)
            for key,flag in [('gdi',0),('user',1),('gdi_peak',2),('user_peak',4)]:
                ctypes.set_last_error(0);value=int(user.GetGuiResources(handle,flag))
                if value==0 and ctypes.get_last_error():raise OSError(ctypes.get_last_error(),'GetGuiResources failed')
                result[key]=value
            return result
        finally:kernel.CloseHandle(handle)
    except Exception as exc:return dict(unavailable=str(exc))


def save_assembly(sw,rows: list[dict],output: Path,stem: str,api_state: dict,state_path: Path,exchange_format: str='step',*,electrical_step: bool=False,reuse_native_samples: bool=False) -> dict:
    """One official flat assembly save/reopen path, reused for named groups."""
    import pythoncom
    import win32com.client
    from common.solidworks.import_step_to_solidworks import (
        ASSEMBLY_TEMPLATE,create_transform,document_title,save_native_document)
    assembly=sw.NewDocument(str(ASSEMBLY_TEMPLATE),2,0,0)
    if assembly is None:raise RuntimeError('Assembly template failed')
    opened_titles=[]
    try:
        for ordinal,row in enumerate(rows,1):
            error=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
            warning=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
            # AddComponent5 requires a preloaded reference, not a writeable
            # part. Only the new assembly receives poses/save operations.
            part=open_reference_document(sw,row['native'],1,error,warning)
            if ordinal in (1,20,40,45,46,len(rows)) or part is None or error.value:
                api_state.setdefault('assembly_load_resources',[]).append(dict(assembly=stem,ordinal=ordinal,
                    part=Path(row['native']).name,error=int(error.value),warning=int(warning.value),
                    gui=gui_resource_counts(sw)))
                state_path.write_text(json.dumps(api_state,indent=2)+'\n',encoding='utf-8')
            if part is None or error.value:
                raise RuntimeError(f"Native part reopen failed: {row['native']} error={error.value} warning={warning.value} model_none={part is None}")
            opened_titles.append(document_title(part))
            if electrical_step:
                row['sealed_body_volume_mm3']=row['volume_mm3']
                row['mass_property_volume_levels_mm3']=mass_property_volume_levels(part)
                row['volume_mm3']=row['mass_property_volume_levels_mm3']['2']
                row['bspline_edges']=inspect_bspline_edges(part)
                if not reuse_native_samples:
                    row['trimmed_curve_sample_files']=save_trimmed_curve_samples(part,row.get('project_transform',PROJECT_TRANSFORM),
                        output.parent/'results'/'curves'/stem/'native'/row['name'],sample_count=2001)
            comp=assembly.AddComponent5(row['native'],0,'',False,'',0,0,0)
            if comp is None:raise RuntimeError('Component insertion failed')
            if member(comp.IsFixed):
                assembly.ClearSelection2(True)
                null=win32com.client.VARIANT(pythoncom.VT_DISPATCH,None)
                comp.Select4(False,null,False);assembly.UnfixComponent()
            comp.Transform2=create_transform(sw.GetMathUtility,row.get('project_transform',PROJECT_TRANSFORM))
        _=member(assembly.EditRebuild3);assembly.ClearSelection2(True)
        error=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
        sw.ActivateDoc3(document_title(assembly),False,0,error)
        if error.value:raise RuntimeError('Assembly activation for STEP failed')
        native_path=output/(stem+'.SLDASM');step_path=output/(stem+('.x_t' if exchange_format=='parasolid' else '.step'))
        ns=save_native_document(assembly,native_path);ss=save_exchange_document(sw,assembly,step_path)
        if ns[0] or ss[0]:raise RuntimeError('Assembly save failed')
        manager=member(assembly.InterferenceDetectionManager)
        manager.TreatCoincidenceAsInterference=False
        manager.IncludeMultibodyPartInterferences=True;manager.IgnoreHiddenBodies=False
        interferences=[]
        for item in (member(manager.GetInterferences) or []):
            interferences.append(dict(volume_mm3=float(member(item.Volume))*1e9,
                components=[str(member(c.Name2)) for c in member(item.Components)]))
        _=member(manager.Done)
        if any(x['volume_mm3']>1e-5 for x in interferences):
            raise RuntimeError('Assembly contains overlapping physical conductors: '+str(interferences))
    finally:
        sw.CloseDoc(document_title(assembly))
        close_owned_parts(sw,opened_titles,rows[:len(opened_titles)])
    error=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
    warning=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
    reopened=open_reference_document(sw,str(native_path),2,error,warning)
    if reopened is None or error.value:raise RuntimeError('Saved native assembly reopen failed')
    try:
        native_reopen=inspect_assembly(reopened,high_accuracy=electrical_step);verify_assembly_leaves(native_reopen,rows,native=True)
    finally:sw.CloseDoc(document_title(reopened))
    for row in rows:sw.CloseDoc(Path(row['native']).name)
    null=win32com.client.VARIANT(pythoncom.VT_DISPATCH,None)
    import_original={key:bool(sw.GetUserPreferenceToggle(key)) for key in (690,769)} if electrical_step else {}
    sw.DocumentVisible(False,1)
    try:
        # Installed 2022 FileOpenOptionsSTEPIGESACIS: no automatic healing
        # or analytic-face conversion in a geometry-preservation comparison.
        for key in import_original:sw.SetUserPreferenceToggle(key,False)
        reloaded=sw.LoadFile4(str(step_path),'r',null,error)
    finally:
        sw.DocumentVisible(True,1)
        for key,value in import_original.items():sw.SetUserPreferenceToggle(key,value)
        if import_original:
            restored={key:bool(sw.GetUserPreferenceToggle(key)) for key in import_original}
            api_state.setdefault('step_import_preferences',{})[stem]=dict(original=import_original,restored=restored,
                automatic_healing=False,analytic_conversion=False)
            state_path.write_text(json.dumps(api_state,indent=2)+'\n',encoding='utf-8')
            if restored!=import_original:raise RuntimeError('STEP import preferences not restored')
    if reloaded is None or error.value:raise RuntimeError('Assembly STEP reload failed')
    try:
        if exchange_format=='step' and not electrical_step and member(reloaded.GetType)!=2:raise RuntimeError('STEP must retain independent assembly leaves')
        step_reopen=inspect_exchange_geometry(reloaded,sample_root=output.parent/'results'/'curves'/stem/'step') if electrical_step else inspect_exchange_geometry(reloaded)
        step_reopen['document_type']=int(member(reloaded.GetType))
        if electrical_step:
            api_state.setdefault('electrical_step_reopen',{})[stem]=dict(expected=rows,actual=step_reopen)
            state_path.write_text(json.dumps(api_state,indent=2)+'\n',encoding='utf-8')
        verify_assembly_leaves(step_reopen,rows,native=False,engineering_step=electrical_step)
    finally:sw.CloseDoc(document_title(reloaded))
    return dict(name=stem,component_count=len(rows),assembly_native=str(native_path),assembly_exchange=str(step_path),
                native_part_open_options='Silent|ReadOnly',native_cold_reopen=True,exchange_format=exchange_format,
                exchange_export_protocol='Parasolid latest__flattened_world_bodies' if exchange_format=='parasolid' else 'AP214',
                native_reopen=native_reopen,exchange_reopen=step_reopen,interferences=interferences)


def reopen_owned_part(sw,native: Path,*,allow_detector_property_repair: bool=False,writable: bool=False):
    """Official read-only reopen, with one explicit owned-copy repair case."""
    import pythoncom
    import win32com.client
    error=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
    warning=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
    doc=sw.OpenDoc6(str(native),1,1 if writable else 3,'',error,warning)
    repair=None
    if doc is None and error.value==2097152 and allow_detector_property_repair and native.stem=='detector':
        settings=sw.GetOpenDocSpec(str(native));settings.Silent=True
        settings.ReadOnly=False;settings.AutoRepair=True;settings.CriticalDataRepair=False
        doc=sw.OpenDoc7(settings)
        repair=dict(method='IDocumentSpecification.AutoRepair',original_error=2097152,
                    error=int(settings.Error),warning=int(settings.Warning))
        if doc is None or settings.Error:raise RuntimeError('Owned detector custom-property repair failed')
        repair['opened_document_path']=str(member(doc.GetPathName))
    elif doc is None or error.value:
        raise RuntimeError(f"Reuse native reopen failed {native} error={error.value} warning={warning.value}")
    return doc,repair


def verify_preserved_bspline_edges(observed: list[dict],expected: list[dict]) -> dict:
    """Match audited exact local controls/knots; edge indices may change."""
    remaining=list(observed);deltas=[]
    if len(remaining)!=len(expected):raise RuntimeError('Exact B-spline edge count changed')
    for reference in expected:
        candidates=[]
        for index,edge in enumerate(remaining):
            if edge['order']!=reference['order'] or len(edge['knots'])!=len(reference['knots']):continue
            if len(edge['control_points_local_m'])!=len(reference['control_points_local_m']):continue
            for reverse in (False,True):
                controls=edge['control_points_local_m'][::-1] if reverse else edge['control_points_local_m']
                knots=[edge['knots'][0]+edge['knots'][-1]-v for v in edge['knots'][::-1]] if reverse else edge['knots']
                dp=max(abs(a-b)*1000 for p,q in zip(controls,reference['control_points_local_m'],strict=True) for a,b in zip(p,q,strict=True))
                dk=max(abs(a-b) for a,b in zip(knots,reference['knots'],strict=True))
                candidates.append((dp,dk,index))
        if not candidates:raise RuntimeError('Audited exact B-spline edge missing')
        dp,dk,index=min(candidates)
        if dp>1e-5 or dk>1e-12:raise RuntimeError('Exact B-spline controls or knots changed')
        remaining.pop(index);deltas.append(dp)
    return dict(edge_count=len(expected),max_control_delta_mm=max(deltas),knots_preserved=True)


def inspect_bspline_edges(document) -> list[dict]:
    """Read modified/cold-reloaded edges using installed GetBCurveParams3."""
    edges=[]
    for body in document.GetBodies2(0,False) or []:
        for edge in member(body.GetEdges) or []:
            curve=member(edge.GetCurve)
            if not member(curve.IsBcurve):continue
            values=list(curve.GetBCurveParams3(True,False,True))
            dimension,order=struct.unpack('ii',struct.pack('d',float(values[0])))
            count,_=struct.unpack('ii',struct.pack('d',float(values[1])))
            end=2+count+order
            if dimension!=3:raise RuntimeError('Unexpected exact B-spline control dimension')
            edges.append(dict(order=order,knots=list(map(float,values[2:end])),
                control_points_local_m=[list(map(float,values[end+i*dimension:end+(i+1)*dimension])) for i in range(count)]))
    return edges


def save_trimmed_curve_samples(document,transform: list[float],output: Path,*,sample_count: int) -> list[str]:
    """Persist actual Evaluate2 positions per body before any comparison."""
    if sample_count<3:raise ValueError('At least three curve samples required')
    output.mkdir(parents=True,exist_ok=True);paths=[]
    bodies=list(document.GetBodies2(0,False) or [])+list(document.GetBodies2(1,False) or [])
    for index,body in enumerate(bodies):
        edges=[]
        for ordinal,edge in enumerate(member(body.GetEdges) or []):
            curve=member(edge.GetCurve);params=list(member(edge.GetCurveParams2))
            sense=struct.unpack('ii',struct.pack('d',float(params[10])))[1]
            endpoints=[list(map(float,params[:3])),list(map(float,params[3:6]))]
            # CurveParamData/edge parameters can have another native
            # parameterization. Use official closest-point ParamU on this
            # actual live Curve, then independently verify both endpoints.
            projected=[list(map(float,curve.GetClosestPointOn(*point))) for point in endpoints]
            lo,hi=[point[3] for point in projected]
            curved=bool(member(curve.IsBcurve));count=sample_count if curved else 2
            parameters=[lo+(hi-lo)*i/(count-1) for i in range(count)]
            points=[list(map(float,curve.Evaluate2(u,0)[:3])) for u in parameters]
            norm=lambda a,b:math.sqrt(sum((x-y)**2 for x,y in zip(a,b,strict=True)))
            endpoint_delta=min(max(norm(points[0],endpoints[0]),norm(points[-1],endpoints[1])),
                max(norm(points[0],endpoints[1]),norm(points[-1],endpoints[0])))
            world=[[1000*(sum(point[i]*transform[i*3+j] for i in range(3))+transform[9+j]) for j in range(3)] for point in points]
            if endpoint_delta>1e-8:raise RuntimeError('Actual trimmed curve endpoint projection differs')
            edges.append(dict(edge_ordinal=ordinal,curve_identity=int(member(curve.Identity)),is_bspline=curved,
                edge_curve_params2=params,sense_flag=sense,parameter_range=[lo,hi],parameters=parameters,
                parameter_source='ICurve.GetClosestPointOn__actual_edge_endpoints',projected_endpoints=projected,
                endpoint_delta_m=endpoint_delta,local_points_m=points,world_points_mm=world))
        path=output/f'body_{index}.json';temporary=path.with_suffix('.json.part')
        value=dict(schema_version=1,body_ordinal=index,local_length_unit='m',world_length_unit='mm',
            coordinate_frame='frozen_project_xyz',project_transform=transform,edges=edges,
            qualification='raw_actual_trimmed_curve_samples__no_comparison_or_global_error_bound')
        temporary.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8');temporary.replace(path)
        paths.append(str(path))
    return paths


def compare_trimmed_curve_samples(reference_files: list[str],observed_files: list[str],*,straight_only: bool=False) -> dict:
    """Finite world-space edge comparison, not control encoding or a global bound."""
    import numpy as np
    from scipy.interpolate import CubicSpline
    if len(reference_files)!=len(observed_files):raise RuntimeError('STEP body count differs')
    references=[edge for path in reference_files for edge in json.loads(Path(path).read_text())['edges']]
    remaining=[edge for path in observed_files for edge in json.loads(Path(path).read_text())['edges']]
    if straight_only:
        references=[edge for edge in references if not edge['is_bspline']]
        remaining=[edge for edge in remaining if not edge['is_bspline']]
    if len(references)!=len(remaining):raise RuntimeError('STEP trim edge topology changed')
    results=[]
    for reference in references:
        p=np.asarray(reference['world_points_mm'],dtype=float)
        axis=int(np.argmax(np.ptp(p,axis=0)))
        ordered=np.argsort(p[:,axis]);p=p[ordered]
        if np.any(np.diff(p[:,axis])<=0):raise RuntimeError('Actual edge has no supported monotone coordinate')
        candidates=[]
        for i,edge in enumerate(remaining):
            if edge['is_bspline']!=reference['is_bspline']:continue
            q=np.asarray(edge['world_points_mm'],dtype=float)
            score=max(np.max(np.abs(p.min(axis=0)-q.min(axis=0))),np.max(np.abs(p.max(axis=0)-q.max(axis=0))))
            candidates.append((float(score),i))
        if not candidates:raise RuntimeError('STEP actual curve type changed')
        _,index=min(candidates);edge=remaining.pop(index)
        q=np.asarray(edge['world_points_mm'],dtype=float);q=q[np.argsort(q[:,axis])]
        if np.any(np.diff(q[:,axis])<=0):raise RuntimeError('STEP edge has no supported monotone coordinate')
        endpoint=max(float(np.linalg.norm(p[0]-q[0])),float(np.linalg.norm(p[-1]-q[-1])))
        spans=[];mask=np.ones(len(p),dtype=bool)
        if not reference['is_bspline']:
            spans=[endpoint]
        for stride in ((2,1) if reference['is_bspline'] else (1,)):
            if not reference['is_bspline']:break
            sampled=q[::stride]
            if not np.array_equal(sampled[-1],q[-1]):sampled=np.vstack((sampled,q[-1]))
            mask=(p[:,axis]>=sampled[0,axis])&(p[:,axis]<=sampled[-1,axis])
            if not np.any(mask):raise RuntimeError('STEP curve has no common spatial extent')
            predicted=CubicSpline(sampled[:,axis],sampled,axis=0)(p[mask,axis])
            spans.append(float(np.max(np.linalg.norm(predicted-p[mask],axis=1))))
        delta=max(endpoint,*spans)
        if delta>0.005:raise RuntimeError(f'STEP actual trim deviation {delta} mm exceeds approved 0.005 mm')
        results.append(dict(reference_edge=reference['edge_ordinal'],observed_edge=edge['edge_ordinal'],
            is_bspline=reference['is_bspline'],endpoint_delta_mm=endpoint,max_sampled_delta_mm=delta,
            support_levels_max_mm=spans,support_refinement_change_mm=abs(spans[-1]-spans[0]),
            common_reference_points=int(np.count_nonzero(mask))))
    return dict(status='PASS',edge_count=len(results),max_sampled_delta_mm=max((row['max_sampled_delta_mm'] for row in results),default=0),
        tolerance_mm=0.005,qualification='user_approved_finite_engineering_STEP_exchange__not_strict_global_bound',edges=results)


def omit_mounting_holes(document,spec: dict,reference_inventory: dict|None=None) -> dict:
    """Suppress only original circular-cut features in this owned working copy."""
    import pythoncom
    import win32com.client
    transform=spec['project_transform'];observed=machining_feature_inventory(document,transform)
    reused=not observed['cylindrical_faces']
    if reused and reference_inventory is None:raise RuntimeError('No-hole reuse requires frozen original-hole inventory')
    before=reference_inventory if reference_inventory is not None else observed
    if reference_inventory is not None:
        if abs(before['volume_mm3']-spec['original_volume_mm3'])>max(1e-5,before['volume_mm3']*1e-9):
            raise RuntimeError('Original-hole reference volume differs from original native audit')
        if max(abs(a-b) for a,b in zip(before['project_transform'],transform,strict=True))>1e-12:
            raise RuntimeError('Original-hole reference pose differs')
    owners={f['feature_name'] for f in before['cylindrical_faces']}
    if len(before['cylindrical_faces'])!=(8 if spec['name']=='central_ion_foil_ground' else 6):
        raise RuntimeError('Original circular machining-hole inventory differs')
    features={f['name']:f for f in before['features']}
    hole_profiles={p for name in owners for p in features[name]['parents']
        if features.get(p,{}).get('type')=='ProfileFeature' and
        all(f['name'] in owners for f in before['features'] if p in f['parents'])}
    for name in owners:
        f=features[name]
        if f['type'] not in ('HoleWzd','MirrorPattern') and f['underlying_type']!='Cut':
            raise RuntimeError('Cylinder belongs to a non-hole feature: '+name)
        if f['type']=='MirrorPattern' and not any(features.get(p,{}).get('type')=='HoleWzd' for p in f['parents']):
            raise RuntimeError('Mirror feature is not the audited hole-seed pattern')
    expected_fill=0.
    for face in before['cylindrical_faces']:
        circles=face['circular_trim_edges']
        if len(circles)!=2:raise RuntimeError('Machining cylinder must have two circular end trims')
        depth=math.dist(circles[0]['native_center_mm'],circles[1]['native_center_mm'])
        expected_fill+=math.pi*face['radius_mm']**2*depth
    for cone in before['conical_faces']:
        if cone['feature_name'] not in owners:raise RuntimeError('Non-hole cone must not be removed')
        radius=cone['native_parameters'][6]*1000;angle=cone['native_parameters'][7]
        expected_fill+=math.pi*radius**3/(3*math.tan(angle))
    null=win32com.client.VARIANT(pythoncom.VT_EMPTY,None)
    suppressed=[]
    # Mirror instances are removed first, then their cut seed. No slot/extrusion
    # feature is selected by name resemblance or by cylindrical face sense.
    for name in sorted(owners,key=lambda n:features[n]['type']!='MirrorPattern'):
        feature=document.FeatureByName(name)
        if reused and not member(feature.IsSuppressed):raise RuntimeError('Reused no-hole seed or pattern is not suppressed')
        if not member(feature.IsSuppressed):
            if not feature.SetSuppression2(0,1,null):raise RuntimeError('Official hole-feature suppression failed: '+name)
        if not member(feature.IsSuppressed):raise RuntimeError('Hole feature remains active: '+name)
        suppressed.append(name)
    if not reused and not member(document.EditRebuild3):raise RuntimeError('No-hole native rebuild failed')
    after=observed if reused else machining_feature_inventory(document,transform)
    if after['cylindrical_faces'] or after['conical_faces']:raise RuntimeError('Circular machining geometry remains')
    for f in after['features']:
        if f['name'] not in owners|hole_profiles and f['suppressed']!=features[f['name']]['suppressed']:
            raise RuntimeError('Non-hole feature suppression changed: '+f['name'])
    curves=verify_preserved_bspline_edges(inspect_bspline_edges(document),spec['original_body_bspline_edges'])
    delta=after['volume_mm3']-before['volume_mm3']
    if abs(delta-expected_fill)>max(1e-5,after['volume_mm3']*1e-9):
        raise RuntimeError('No-hole volume change differs from circular cylinders and drill-tip cones')
    slot_walls=[f for f in after['planar_faces'] if abs(f['world_normal'][0])>.999999 and abs(abs(f['world_root_mm'][0])-2)<1e-5]
    if len(slot_walls)!=2:raise RuntimeError('Original four-millimetre beam-slot walls changed')
    return dict(variant='simulation_cad__all_circular_mounting_holes_omitted',
        suppressed_features=suppressed,original_hole_face_count=len(before['cylindrical_faces']),remaining_circular_faces=0,
        reused_saved_no_hole_geometry=reused,
        dependent_hole_profiles_suppressed=[f['name'] for f in after['features'] if f['name'] in hole_profiles and f['suppressed']],
        original_volume_mm3=before['volume_mm3'],reference_volume_mm3=after['volume_mm3'],filled_volume_mm3=delta,
        analytical_cylinder_and_drill_tip_fill_mm3=expected_fill,analytical_fill_delta_mm3=delta-expected_fill,
        retained_beam_slot_wall_x_mm=[f['world_root_mm'][0] for f in slot_walls],
        original_m6_drill_tip_to_beam_slot_wall_mm=min(2-c['native_parameters'][6]*1000/math.tan(c['native_parameters'][7]) for c in before['conical_faces']),
        exact_curves=curves,non_hole_feature_suppression_unchanged=True,
        beam_slot_features_retained=True,original_sources_modified=False)


def machining_feature_inventory(document,transform: list[float]) -> dict:
    """Read feature ownership and exact cylinder/circle loci; never edit CAD."""
    features=[];feature=member(document.FirstFeature)
    while feature is not None:
        features.append(dict(name=str(member(feature.Name)),type=str(member(feature.GetTypeName2)),
                             underlying_type=str(member(feature.GetTypeName)),
                             parents=[str(member(p.Name)) for p in (member(feature.GetParents) or [])],
                             suppressed=bool(member(feature.IsSuppressed))))
        feature=member(feature.GetNextFeature)
    def world(point):
        return [(sum(float(point[i])*transform[i*3+j] for i in range(3))*transform[12]+transform[9+j])*1000 for j in range(3)]
    cylinders=[];planes=[];cones=[]
    for body_index,body in enumerate(document.GetBodies2(0,False) or []):
        for face_index,face in enumerate(member(body.GetFaces) or []):
            surface=member(face.GetSurface)
            if surface is None:continue
            owner=member(face.GetFeature)
            if member(surface.IsPlane):
                parameters=list(map(float,member(surface.PlaneParams)))
                planes.append(dict(feature_name=str(member(owner.Name)),world_root_mm=world(parameters[3:6]),
                    world_normal=[sum(parameters[i]*transform[i*3+j] for i in range(3)) for j in range(3)]))
            if member(surface.IsCone):
                cones.append(dict(feature_name=str(member(owner.Name)),native_parameters=list(map(float,member(surface.ConeParams)))))
            if not member(surface.IsCylinder):continue
            parameters=list(map(float,member(surface.CylinderParams)))
            owner=member(face.GetFeature);circles=[]
            for edge_index,edge in enumerate(member(face.GetEdges) or []):
                curve=member(edge.GetCurve)
                if curve is not None and member(curve.IsCircle):
                    values=list(map(float,member(curve.CircleParams)))
                    circles.append(dict(edge_index=edge_index,native_center_mm=[v*1000 for v in values[:3]],
                        world_center_mm=world(values[:3]),radius_mm=values[6]*1000))
            cylinders.append(dict(body_index=body_index,face_index=face_index,
                feature_name=str(member(owner.Name)) if owner is not None else None,
                feature_type=str(member(owner.GetTypeName2)) if owner is not None else None,
                native_axis_origin_mm=[v*1000 for v in parameters[:3]],world_axis_origin_mm=world(parameters[:3]),
                native_axis_direction=parameters[3:6],
                world_axis_direction=[sum(parameters[i+3]*transform[i*3+j] for i in range(3)) for j in range(3)],
                radius_mm=parameters[6]*1000,normal_same_as_surface=bool(member(face.FaceInSurfaceSense)),
                circular_trim_edges=circles,
                approximate_native_face_box_mm=[float(v)*1000 for v in member(face.GetBox)]))
    return dict(read_only=bool(member(document.IsOpenedReadOnly)),features=features,cylindrical_faces=cylinders,
                planar_faces=planes,conical_faces=cones,
                exact_world_box_mm=body_bounds_mm(document,transform),volume_mm3=volume_mm3(document),
                approximate_face_boxes_are_diagnostic_only=True,source_saved=False,geometry_modified=False)


def electrical_step_groups(source: Path, frozen_inputs: dict[str,Path]) -> list[dict]:
    """Reuse sealed native bodies/poses; separate C0 from actual conductors."""
    manifest=json.loads((source/'run_manifest.json').read_text(encoding='utf-8-sig'))
    if manifest['status']!='success' or manifest['project']!='parallel_mirror_dual_stripe_mr_tof':
        raise ValueError('Electrical STEP requires a successful project CAD source')
    records={Path(r['path']).resolve():r for r in manifest['outputs']}
    def sealed(path):
        row=records.get(path.resolve())
        if row is None or path.stat().st_size!=row['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest().lower()!=row['sha256'].lower():
            raise ValueError('Sealed electrical CAD source differs: '+str(path))
    for key,path in frozen_inputs.items():
        prior=source/'inputs'/({'geometry':'resolved_geometry.json','authority':'frozen_input.json',
            'materialization':'assembly_materialization.json'}[key])
        if path.read_bytes()!=prior.read_bytes():raise ValueError('Electrical CAD frozen input differs: '+key)
    for name in ('cad_validation.json','cad_parts_plan.json'):sealed(source/name)
    validation=json.loads((source/'cad_validation.json').read_text())
    specs=json.loads((source/'cad_parts_plan.json').read_text())
    if validation['status']!='PASS' or not validation.get('mounting_holes_omitted'):
        raise ValueError('Electrical STEP requires the accepted no-hole CAD variant')
    by_name={row['name']:row for row in validation['parts']};groups={}
    for spec in specs:
        row=copy.deepcopy(by_name[spec['name']]);native=Path(row['native']).resolve()
        if not native.is_relative_to(source.resolve()):raise ValueError('Native CAD is outside its sealed source')
        sealed(native)
        c0=spec['electrode_namespace']=='boundary'
        key=('c0',0) if c0 else ('voltage',float(spec['voltage_v']))
        if key not in groups:
            stem='c0_boundary_reference' if c0 else ('grounded_conductors' if key[1]==0 else 'potential_'+spec['name'])
            groups[key]=dict(name=stem,voltage_v=key[1],optional_boundary_reference=c0,parts=[],rows=[])
        groups[key]['parts'].append({k:spec[k] for k in ('name','electrode_namespace','electrode_id','voltage_v','geometry_kind')})
        groups[key]['rows'].append(row)
    return list(groups.values())


def individual_step_groups(groups: list[dict],prior: Path) -> list[dict]:
    """Reuse sealed native samples; independently export every physical body."""
    manifest=json.loads((prior/'run_manifest.json').read_text())
    if manifest['status']!='success':raise ValueError('Individual STEP requires a successful electrical source')
    records={Path(row['path']).resolve():row for row in manifest['outputs']}
    checked=set()
    def sealed(path):
        path=path.resolve()
        if path in checked:return
        record=records.get(path)
        if record is None or path.stat().st_size!=record['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest().lower()!=record['sha256'].lower():
            raise ValueError('Prior STEP evidence identity differs: '+str(path))
        checked.add(path)
    state=prior/'cad_api_state.json';sealed(state)
    previous=json.loads(state.read_text())['electrical_step_reopen']
    output=[];view_rows=[];view_parts=[]
    suffix={'x_0':'x_negative','x_1':'x_positive','y_0':'y_lower','y_1':'y_upper','z_0':'z_negative','z_1':'z_positive'}
    for group in groups:
        expected={row['name']:row for row in previous[group['name']]['expected']}
        for row,part in zip(group['rows'],group['parts'],strict=True):
            if row['solid_count']+row['sheet_count']!=1:raise ValueError('Disconnected bodies require explicit further splitting: '+row['name'])
            old=expected[row['name']]
            if old['project_transform']!=row['project_transform'] or old['project_box_mm']!=row['project_box_mm']:
                raise ValueError('Prior native sample world pose differs')
            row['trimmed_curve_sample_files']=old['trimmed_curve_sample_files']
            for path in row['trimmed_curve_sample_files']:sealed(Path(path))
            name=row['name']
            if group['optional_boundary_reference']:name='c0_reference_'+suffix[name.removeprefix('c0_reference_')]
            output.append(dict(name=name,voltage_v=part['voltage_v'],optional_boundary_reference=group['optional_boundary_reference'],parts=[part],rows=[row]))
            if not group['optional_boundary_reference']:view_rows.append(copy.deepcopy(row));view_parts.append(part)
    output.append(dict(name='mrtof_electrode_assembly',voltage_v=None,optional_boundary_reference=False,
        overview_only=True,parts=view_parts,rows=view_rows))
    return output


def export_parts(parts: list[dict], output: Path, *, smoke: bool=False,reuse: bool=False,exchange_format: str='step',
    inspect_machining_holes: bool=False,omit_holes: bool=False,machining_inventory: dict|None=None,
    electrical_groups: list[dict]|None=None,reuse_native_samples: bool=False) -> dict:
    """Save engineering parts and cold-read the declared neutral format."""
    import pythoncom
    import win32com.client
    from common.solidworks.installation import resolve_solidworks_2022_root
    from common.solidworks.import_step_to_solidworks import (
        CLEAN_PART_TEMPLATE,ASSEMBLY_TEMPLATE,document_title,save_native_document)
    install_root=resolve_solidworks_2022_root()
    pythoncom.CoInitialize();sw=None;started=False;rows=[];preferences=None
    try:
        try:sw=win32com.client.GetActiveObject('SldWorks.Application.30')
        except pythoncom.com_error:
            sw=win32com.client.dynamic.Dispatch('SldWorks.Application.30');started=True
        if not started:raise RuntimeError('CAD export requires its own SolidWorks instance; existing session retained unchanged')
        revision=str(member(sw.RevisionNumber))
        if not revision.startswith('30.'):raise RuntimeError('SolidWorks revision 30 required')
        # Same scoped installed-template policy as the shared STEP import bridge.
        preferences=(sw.GetUserPreferenceStringValue(8),sw.GetUserPreferenceStringValue(9),
                     bool(sw.GetUserPreferenceToggle(111)),bool(sw.GetUserPreferenceToggle(691)))
        output.mkdir(parents=True,exist_ok=True)
        api_state=dict(solidworks_revision=revision,original_preferences=dict(default_part_template=preferences[0],
            default_assembly_template=preferences[1],always_use_default_templates=preferences[2],
            enable_3d_interconnect=preferences[3]),preferences_restored=False,
            official_2022_manual=str(install_root/'api/sldworksapi.chm'),
            methods=['FeatureExtrusion2','FeatureCut3','InsertPlanarRefSurface','SaveAs','LoadFile4','GetExtremePoint',
                     'GetInterferences','DocumentVisible','OpenDoc6'],
            gui_counter_reference='https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getguiresources')
        api_state['solidworks_pid']=int(member(sw.GetProcessID))
        state_path=output.parent/'cad_api_state.json'
        state_path.write_text(json.dumps(api_state,indent=2)+'\n',encoding='utf-8')
        sw.SetUserPreferenceStringValue(8,str(CLEAN_PART_TEMPLATE))
        sw.SetUserPreferenceStringValue(9,str(ASSEMBLY_TEMPLATE))
        # Official LoadFile4: disabled Interconnect + 'r' imports into a new
        # document without an interactive translation dialog. No external links
        # or an unrequested native imported-assembly save are needed for validation.
        sw.SetUserPreferenceToggle(111,True);sw.SetUserPreferenceToggle(691,False)
        sw.Visible=True;output.mkdir(parents=True,exist_ok=True)
        if electrical_groups is not None:
            exported=[]
            for group in electrical_groups:
                print('ELECTRICAL_STEP_GROUP='+group['name'],flush=True)
                result=save_assembly(sw,group['rows'],output,group['name'],api_state,state_path,'step',electrical_step=True,reuse_native_samples=reuse_native_samples)
                exported.append({k:v for k,v in group.items() if k!='rows'}|result)
            return dict(status='PASS',solidworks_revision=revision,electrical_groups=exported,
                component_count=sum(len(g['parts']) for g in electrical_groups),
                coordinate_frame='global_project_xyz_mm__all_files_same_origin',
                mounting_holes_omitted=True,exchange_format='step',
                step_exchange_tolerance_mm=0.005,volume_deviations_reported_separately=True,
                qualification='engineering_geometry_only__manufacturing_and_simulation_formal_not_granted')
        for spec in (parts[:1] if smoke else parts):
            native=output/(spec['name']+'.SLDPRT')
            step=output/(spec['name']+('.x_t' if exchange_format=='parasolid' else '.step'))
            repair=None
            hole_variant=None;modify_original=omit_holes and spec['geometry_kind']=='original_native_solid'
            if reuse:
                doc,repair=reopen_owned_part(sw,native,allow_detector_property_repair=True,writable=modify_original)
            else:doc=sw.NewDocument(str(CLEAN_PART_TEMPLATE),1,0,0)
            if doc is None:raise RuntimeError('Clean part template failed')
            print('CAD_PART='+spec['name'],flush=True)
            try:
                if inspect_machining_holes:
                    observed=machining_feature_inventory(doc,spec.get('project_transform',PROJECT_TRANSFORM))
                    if not observed['read_only']:raise RuntimeError('Machining inventory requires read-only owned copies')
                    rows.append(dict(name=spec['name'],native=str(native),project_transform=spec['project_transform'],**observed))
                    continue
                if modify_original:
                    if Path(str(member(doc.GetPathName))).resolve()!=native.resolve() or member(doc.IsOpenedReadOnly):
                        raise RuntimeError('Hole suppression requires this new owned writable copy')
                    hole_variant=omit_mounting_holes(doc,spec,(machining_inventory or {}).get(spec['name']))
                if not reuse:
                    if spec['geometry_kind']=='reference_sheet':build_sheet(doc,spec['solids'][0]['box_mm'])
                    else:
                        for op in spec['solids']:build_operation(doc,op,False)
                        for op in spec['cuts']:build_operation(doc,op,True)
                    _=member(doc.EditRebuild3);doc.ClearSelection2(True)
                modified_holes=modify_original and not hole_variant['reused_saved_no_hole_geometry']
                ns=save_native_document(doc,native) if not reuse or repair or modified_holes else (0,0)
                ss=save_exchange_document(sw,doc,step) if exchange_format=='parasolid' or not reuse or spec.get('original_native') else (0,0)
                transform=spec.get('project_transform',PROJECT_TRANSFORM)
                box=body_bounds_mm(doc,transform)
                if ns[0] or ss[0]:raise RuntimeError('Part save error')
                if spec['geometry_kind']=='original_native_solid':
                    local=body_bounds_mm(doc,[1,0,0,0,1,0,0,0,1,0,0,0,1,0,0,0])
                    if max(abs(a-b) for a,b in zip(local,spec['original_exact_local_box_mm'],strict=True))>1e-5:
                        raise RuntimeError('Original native exact dimensions changed')
                elif max(abs(a-b) for a,b in zip(box,expected_bounds_mm(spec),strict=True))>1e-5:
                    raise RuntimeError('Native dimensions/pose differ from frozen geometry')
                volume=volume_mm3(doc)
                counts=dict(solid_count=len(doc.GetBodies2(0,False) or []),sheet_count=len(doc.GetBodies2(1,False) or []))
                expected_counts=dict(solid_count=int(spec['geometry_kind']!='reference_sheet'),sheet_count=int(spec['geometry_kind']=='reference_sheet'))
                if counts!=expected_counts:raise RuntimeError('Native body topology differs: '+spec['name'])
                reference_volume=hole_variant['reference_volume_mm3'] if hole_variant else spec.get('original_volume_mm3')
                if spec['geometry_kind']=='original_native_solid' and abs(volume-reference_volume)>max(1e-5,volume*1e-9):
                    raise RuntimeError('Original native solid volume changed')
                if spec['group']=='mirror' and spec['cuts']:
                    # Each resolved mirror box contains one rectangular through-slot.
                    outer=spec['solids'][0];hole=spec['cuts'][0]
                    o=outer['polygon_yz_mm'];h=hole['polygon_yz_mm']
                    expected=(outer['x'][1]-outer['x'][0])*(o[2][0]-o[0][0])*(o[2][1]-o[0][1])
                    expected-=(hole['x'][1]-hole['x'][0])*(h[2][0]-h[0][0])*(o[2][1]-o[0][1])
                    if abs(volume-expected)>max(1e-5,expected*1e-9):raise RuntimeError('Mirror through-slot volume differs')
                rows.append(dict(name=spec['name'],native=str(native),exchange=str(step),exchange_format=exchange_format,project_box_mm=box,
                                 native_save=list(ns) if not reuse or repair or modified_holes else None,
                                 exchange_save=list(ss) if exchange_format=='parasolid' or not reuse or spec.get('original_native') else None,volume_mm3=volume,
                                 reused_saved_part=reuse,custom_property_repair=repair,project_transform=transform,
                                 original_native_source=spec.get('original_native'),curve_matches=spec.get('original_curve_matches'),
                                 machining_hole_variant=hole_variant,**counts))
            finally:sw.CloseDoc(document_title(doc))
            if hole_variant:
                reopened,_=reopen_owned_part(sw,native)
                try:
                    if abs(volume_mm3(reopened)-volume)>max(1e-5,volume*1e-9):raise RuntimeError('Cold native no-hole reference volume changed')
                    if max(abs(a-b) for a,b in zip(body_bounds_mm(reopened,transform),box,strict=True))>1e-5:
                        raise RuntimeError('Cold native no-hole dimensions changed')
                    rows[-1]['machining_hole_variant']['native_cold_curve_validation']=verify_preserved_bspline_edges(
                        inspect_bspline_edges(reopened),spec['original_body_bspline_edges'])
                    cold=machining_feature_inventory(reopened,transform)
                    if cold['cylindrical_faces'] or cold['conical_faces']:raise RuntimeError('Cold native retains holes')
                    hole_variant['native_cold_remaining_circular_faces']=0
                finally:sw.CloseDoc(document_title(reopened))
            error=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_I4,0)
            null=win32com.client.VARIANT(pythoncom.VT_DISPATCH,None)
            reloaded=sw.LoadFile4(str(step),'r',null,error)
            if reloaded is None or error.value:raise RuntimeError('Neutral CAD reload failed: '+exchange_format)
            try:
                if counts!=dict(solid_count=len(reloaded.GetBodies2(0,False) or []),sheet_count=len(reloaded.GetBodies2(1,False) or [])):
                    raise RuntimeError('Neutral CAD body topology changed')
                box2=body_bounds_mm(reloaded,transform);rows[-1]['exchange_reload_box_mm']=box2
                if max(abs(a-b) for a,b in zip(box,box2,strict=True))>1e-5:raise RuntimeError('Neutral CAD bounds changed >10 nm')
                vol2=volume_mm3(reloaded);rows[-1]['exchange_reload_volume_mm3']=vol2
                if abs(volume-vol2)>max(1e-5,volume*1e-9):raise RuntimeError('Neutral CAD volume changed')
                if hole_variant:
                    rows[-1]['machining_hole_variant']['exchange_cold_curve_validation']=verify_preserved_bspline_edges(
                        inspect_bspline_edges(reloaded),spec['original_body_bspline_edges'])
                    cold=machining_feature_inventory(reloaded,transform)
                    if cold['cylindrical_faces'] or cold['conical_faces']:raise RuntimeError('Cold exchange retains holes')
                    hole_variant['exchange_cold_remaining_circular_faces']=0
            finally:sw.CloseDoc(document_title(reloaded))
            # Redirection may be lost with an externally killed stdout host.
            # This diagnostic count is written only after real cold-read gates;
            # complete delivery still requires cad_validation and the manifest.
            api_state['cold_part_roundtrip_count']=len(rows)
            api_state['last_verified_part']=spec['name']
            state_path.write_text(json.dumps(api_state,indent=2)+'\n',encoding='utf-8')
        if inspect_machining_holes:
            return dict(status='PASS',solidworks_revision=revision,parts=rows,component_count=len(rows),
                qualification='read_only_machining_feature_inventory__not_modified_cad',
                scope='exact_original_native_feature_and_cylinder_loci__no_hole_removal_or_delivery')
        if smoke:
            return dict(status='PASS',solidworks_revision=revision,parts=rows,component_count=len(rows),
                        scope='single_part_cold_roundtrip',exchange_format=exchange_format,subassemblies=[],
                        qualification='single_part_smoke_only__complete_delivery_not_granted')
        full=save_assembly(sw,rows,output,'mrtof_assembly',api_state,state_path,exchange_format)
        groups={}
        if not smoke:
            for spec,row in zip(parts,rows,strict=True):
                if spec['name'].startswith('oa_'):group='oa'
                elif spec['group']=='mirror' or spec['name'].startswith('mirror_'):group='mirror'
                elif spec['group']=='stripe' or spec['name']=='central_ion_foil_ground':group='stripe_and_central_ground'
                elif spec['name'].startswith(('p1_','p2_')):group='prisms_and_shields'
                elif spec['group']=='detector':group='detector'
                else:group='reference'
                groups.setdefault(group,[]).append(row)
        subassemblies=[save_assembly(sw,group_rows,output,'assembly_'+name,api_state,state_path,exchange_format) for name,group_rows in groups.items()]
        return dict(status='PASS',solidworks_revision=revision,parts=rows,**full,subassemblies=subassemblies,
                    mounting_holes_omitted=omit_holes,
                    qualification='engineering_geometry_only__manufacturing_and_simulation_formal_not_granted')
    finally:
        if sw is not None and preferences is not None:
            sw.DocumentVisible(True,1)
            api_state['part_document_visible_restored_true']=True
            sw.SetUserPreferenceStringValue(8,str(preferences[0]))
            sw.SetUserPreferenceStringValue(9,str(preferences[1]))
            sw.SetUserPreferenceToggle(111,preferences[2]);sw.SetUserPreferenceToggle(691,preferences[3])
            restored=(sw.GetUserPreferenceStringValue(8),sw.GetUserPreferenceStringValue(9),
                      bool(sw.GetUserPreferenceToggle(111)),bool(sw.GetUserPreferenceToggle(691)))
            api_state['restored_preferences_equal_original']=restored==preferences
            api_state['preferences_restored']=restored==preferences
            state_path.write_text(json.dumps(api_state,indent=2)+'\n',encoding='utf-8')
            if restored!=preferences:raise RuntimeError('CAD import preferences not restored')
        if sw is not None and started:
            document=member(sw.GetFirstDocument);foreign=[]
            while document is not None:
                foreign.append(str(member(document.GetPathName)) or document_title(document))
                document=member(document.GetNext)
            if preferences is not None:
                api_state['remaining_documents_retained']=foreign
                api_state['owned_process_exited']=not foreign
                state_path.write_text(json.dumps(api_state,indent=2)+'\n',encoding='utf-8')
            if not foreign:sw.ExitApp()
        pythoncom.CoUninitialize()


def delivery_paths(result: dict,root: Path,*,original_curves: bool) -> list[Path]:
    """One explicit external-delivery whitelist for CAD export and publication."""
    include=[Path(p[k]) for p in result['parts'] for k in ('native','exchange')]
    for assembly in [result]+result['subassemblies']:
        include.extend(Path(assembly[k]) for k in ('assembly_native','assembly_exchange'))
    include +=[root/n for n in ('cad_validation.json','cad_api_state.json','cad_parts_plan.json','bom.csv','DELIVERY_README.txt')]
    include +=[root/'inputs'/n for n in ('resolved_geometry.json','frozen_input.json',
        'assembly_materialization.json','field_manifest.json','assembly_manifest.json')]
    prior=root/'inputs/reused_cad_manifest.json'
    if prior.is_file():include.append(prior)
    for name in ('original_machining_hole_inventory.json','machining_hole_audit_manifest.json'):
        if (root/'inputs'/name).is_file():include.append(root/'inputs'/name)
    if original_curves:
        include +=[root/'inputs'/n for n in ('original_stripe_manifest.json','stripe_pose_manifest.json',
            'stripe_curve_contract.json','stripe_native_audit.json','stripe_parent_pose.json','stripe_child_pose.json','stripe_frame.json')]
    return include


def docx_document_text(path: Path) -> str:
    """Read real WordprocessingML paragraphs/table cells; layout QA is separate."""
    # Microsoft Learn, Structure of a WordprocessingML document (ISO 29500):
    # word/document.xml contains w:document/w:body, w:p/w:r/w:t text.
    if path.suffix.lower()!='.docx':raise ValueError('English overview must be a Word DOCX')
    namespace='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    with zipfile.ZipFile(path) as document:
        required={'[Content_Types].xml','_rels/.rels','word/document.xml'}
        if not required.issubset(document.namelist()) or document.testzip() is not None:
            raise ValueError('English overview is not a complete Word package')
        types=ET.fromstring(document.read('[Content_Types].xml'))
        if not any(e.get('PartName')=='/word/document.xml' and
            e.get('ContentType')=='application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml' for e in types):
            raise ValueError('English overview Word main content type is missing')
        main=ET.fromstring(document.read('word/document.xml'))
        body=main.find(namespace+'body')
        if main.tag!=namespace+'document' or body is None:raise ValueError('English overview Word body is missing')
        text='\n'.join(''.join(e.text or '' for e in p.iter(namespace+'t')) for p in body.iter(namespace+'p'))
    if not text.strip() or re.search('[\u3400-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f]',text):
        raise ValueError('English overview Word body must be nonempty and contain no CJK')
    return text


def publish_validated_delivery(source_run: Path,overview: Path,output: Path,
    physical_inputs: dict[str,Path],overview_manifest: Path,*,check_only: bool=False) -> dict:
    """Publish an English guide plus immutable validated ZIP bytes; never call CAD."""
    source_run=source_run.resolve()
    manifest=json.loads((source_run/'run_manifest.json').read_text(encoding='utf-8-sig'))
    if manifest.get('status')!='success' or manifest.get('project')!='parallel_mirror_dual_stripe_mr_tof':
        raise ValueError('Publication requires a sealed successful CAD source')
    records={Path(r['path']).resolve():r for r in [manifest['run_config'],*manifest['inputs'].values(),*manifest['outputs']]
             if isinstance(r,dict) and r.get('path')}
    def sealed_bytes(path):
        payload=path.read_bytes();record=records.get(path.resolve())
        if not record or len(payload)!=record['bytes'] or hashlib.sha256(payload).hexdigest().upper()!=record['sha256'].upper():
            raise ValueError('Published CAD source identity differs: '+str(path))
        return payload
    validation=json.loads(sealed_bytes(source_run/'cad_validation.json'))
    parts=validation['parts'];assemblies=[validation]+validation['subassemblies']
    if (validation.get('status')!='PASS' or validation.get('component_count')!=53 or len(parts)!=53 or len(assemblies)!=7
        or sum(p['solid_count'] for p in parts)!=45 or sum(p['sheet_count'] for p in parts)!=8
        or sum(bool(p.get('original_native_source')) for p in parts)!=5):
        raise ValueError('Publication requires complete exact-curve CAD validation')
    if (not validation.get('mounting_holes_omitted') or
        sum(bool(p.get('machining_hole_variant')) for p in parts)!=5):
        raise ValueError('Current simulation delivery requires five validated no-hole native instances')
    for key,path in physical_inputs.items():
        if hashlib.sha256(path.read_bytes()).hexdigest().upper()!=manifest['inputs'][key]['sha256'].upper():
            raise ValueError('Publication frozen physical inputs differ: '+key)
    names=[p['name'] for p in parts]+[a['name'] for a in assemblies]
    if not all(name.isascii() for name in names):raise ValueError('Delivery names must be ASCII English')
    overview_payload=overview.read_bytes()
    doc_manifest=json.loads(overview_manifest.read_text(encoding='utf-8-sig'))
    if doc_manifest.get('status')!='success':raise ValueError('Word overview requires a sealed successful document source')
    doc_records=[r for r in doc_manifest['outputs'] if Path(r['path']).resolve()==overview.resolve()]
    if (len(doc_records)!=1 or len(overview_payload)!=doc_records[0]['bytes'] or
        hashlib.sha256(overview_payload).hexdigest().upper()!=doc_records[0]['sha256'].upper()):
        raise ValueError('Word overview differs from its sealed document source')
    text=docx_document_text(overview)
    for name in names:
        if not re.search(r'(?<![A-Za-z0-9_])'+re.escape(name)+r'(?![A-Za-z0-9_])',text):
            raise ValueError('English CAD overview is missing a delivered name: '+name)
    paths=delivery_paths(validation,source_run,original_curves=True)
    expected={p.relative_to(source_run).as_posix():records.get(p.resolve()) for p in paths}
    if len(expected)!=len(paths) or any(r is None for r in expected.values()):raise ValueError('Delivery whitelist is not sealed')
    source_zip=source_run/'mrtof_cad_delivery.zip';sealed_bytes(source_zip)
    receipt=dict(status='PASS',source_run_id=manifest['run_id'],source_run=str(source_run),
        source_zip_sha256=records[source_zip.resolve()]['sha256'],part_count=53,assembly_count=7,
        solid_count=45,sheet_count=8,commercial_cad_performed=False,
        validation_scope='byte-identical_republication_of_sealed_cad__not_new_commercial_cold_read',
        qualification=validation['qualification'],english_overview_sha256=hashlib.sha256(overview_payload).hexdigest(),
        overview_source_run_id=doc_manifest['run_id'],overview_manifest_sha256=hashlib.sha256(overview_manifest.read_bytes()).hexdigest(),
        zip_member_count=len(expected)+1)
    with zipfile.ZipFile(source_zip) as original:
        infos=original.infolist();members=[info.filename for info in infos]
        if len(set(members))!=len(members) or set(members)!=set(expected) or not all(n.isascii() for n in members):
            raise ValueError('Sealed delivery ZIP whitelist/names differ')
        payloads={}
        for info in infos:
            payload=original.read(info);record=expected[info.filename]
            if len(payload)!=record['bytes'] or hashlib.sha256(payload).hexdigest().upper()!=record['sha256'].upper():
                raise ValueError('Sealed delivery ZIP member differs: '+info.filename)
            payloads[info.filename]=payload
        if check_only:return receipt
        output.mkdir(parents=True,exist_ok=True);target=output/'mrtof_cad_delivery.zip'
        if target.exists():raise FileExistsError('Publication output already exists')
        temporary=output/'.mrtof_cad_delivery.zip.part'
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as published:
            for info in infos:published.writestr(info,payloads[info.filename])
            published.writestr('CAD_OVERVIEW.docx',overview_payload)
        with zipfile.ZipFile(temporary) as published:
            if published.testzip() is not None or set(published.namelist())!=set(expected)|{'CAD_OVERVIEW.docx'}:
                raise RuntimeError('Published ZIP integrity failed')
            for name,payload in payloads.items():
                if published.read(name)!=payload:raise RuntimeError('Published CAD member bytes changed: '+name)
        temporary.replace(target)
    receipt.update(zip_path=str(target),zip_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),zip_bytes=target.stat().st_size)
    (output/'CAD_OVERVIEW.docx').write_bytes(overview_payload)
    (output/'delivery_publication.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    return receipt


def main() -> int:
    """Consume the frozen current field and actual assembly, never live config."""
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('geometry','authority','materialization','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--check-only',action='store_true');parser.add_argument('--smoke',action='store_true')
    parser.add_argument('--smoke-part',help='Existing frozen part name; requires --smoke')
    parser.add_argument('--reuse-saved-parts',action='store_true',help='Revalidate governed copied CAD parts; do not reconstruct')
    parser.add_argument('--original-stripe-run',type=Path)
    parser.add_argument('--stripe-pose-run',type=Path)
    parser.add_argument('--exchange-format',choices=('step','parasolid'),default='step')
    parser.add_argument('--publish-cad-run',type=Path)
    parser.add_argument('--english-overview',type=Path)
    parser.add_argument('--overview-manifest',type=Path)
    parser.add_argument('--inspect-machining-holes',action='store_true')
    parser.add_argument('--omit-mounting-holes',action='store_true')
    parser.add_argument('--machining-hole-audit-run',type=Path)
    parser.add_argument('--electrical-step-cad-run',type=Path,help='Export sealed native CAD by voltage in the global frame')
    parser.add_argument('--individual-step-delivery-run',type=Path,help='Split all physical bodies and add a 47-product overview; reuse sealed native sample evidence')
    args=parser.parse_args();g=json.loads(args.geometry.read_text(encoding='utf-8-sig'))
    a=json.loads(args.authority.read_text(encoding='utf-8-sig'));m=json.loads(args.materialization.read_text(encoding='utf-8-sig'))
    if m['analyzer_electrode_voltages_v']!=a['analyzer_electrode_voltages_v']:raise ValueError('Actual full20 authority differs')
    if m['detector_box_mm']!=g['detector']['box']:raise ValueError('Actual detector pose differs')
    for key in ('mirror_electrodes','mirror_ground_shields','mirror_e_closures','mirror_slot','mirror_inner_shield_slot',
                'stripe_electrodes','stripe_slot','central_ground_electrodes','central_ground_slots',
                'prism_electrodes','prism_ground_shields'):
        if m['collision_geometry'][key]!=g[key]:raise ValueError('Actual assembly geometry differs: '+key)
    if args.electrical_step_cad_run:
        if args.publish_cad_run or args.reuse_saved_parts or args.original_stripe_run or args.omit_mounting_holes:
            raise ValueError('Electrical STEP consumes sealed CAD without rebuilding parts')
        groups=electrical_step_groups(args.electrical_step_cad_run,
            dict(geometry=args.geometry,authority=args.authority,materialization=args.materialization))
        if args.individual_step_delivery_run:groups=individual_step_groups(groups,args.individual_step_delivery_run)
        if args.smoke:
            groups=[group for group in groups if group['name']==args.smoke_part]
            if len(groups)!=1:raise ValueError('Electrical STEP smoke requires one declared group name')
        if args.check_only:
            print(json.dumps(dict(status='PASS',groups=[{k:v for k,v in x.items() if k!='rows'} for x in groups])));return 0
        result=export_parts([],args.output,electrical_groups=groups,reuse_native_samples=args.individual_step_delivery_run is not None)
        if args.individual_step_delivery_run:
            result['component_count']=sum(len(group['parts']) for group in groups if not group.get('overview_only'))
            result['overview_component_count']=47
        (args.output.parent/'cad_validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        (args.output.parent/'electrode_groups.json').write_text(json.dumps(result['electrical_groups'],indent=2)+'\n',encoding='utf-8')
        with (args.output.parent/'electrode_groups.csv').open('w',newline='',encoding='utf-8') as file:
            writer=csv.writer(file);writer.writerow(['step_file','voltage_v','optional_c0','physical_component','namespace','electrode_id'])
            for group in result['electrical_groups']:
                if group.get('overview_only'):continue
                for part in group['parts']:writer.writerow([group['name']+'.step',group['voltage_v'],group['optional_boundary_reference'],part['name'],part['electrode_namespace'],part['electrode_id']])
        if not args.smoke:
            if bool(args.english_overview)!=bool(args.overview_manifest):raise ValueError('Optional existing overview and manifest must be paired')
            if args.english_overview:
                publish_validated_delivery(args.electrical_step_cad_run,args.english_overview,args.output.parent,
                    dict(geometry=args.geometry,authority=args.authority,materialization=args.materialization),args.overview_manifest,check_only=True)
            description=(
                '# MR-TOF STEP Electrode Delivery\n\n'
                'All STEP files use the same global assembly origin and axes: x transverse, y slow drift, z fast reflection. Units are millimetres. Import without translation or rotation; do not centre individual files.\n\n'
                'Electrode files use the voltages listed in electrode_groups.csv. Geometry and voltages are unchanged from the previously supplied CAD package and English overview; this package only changes the exchange format. Mirror E closure plates retain the mirror E voltage.\n\n'
                'Stripe and central-foil geometry is exported from the original continuous B-spline bodies, not polyline approximations. All circular mounting holes are omitted in this simulation variant. The 4 mm beam slot is retained. No proprietary CAD files are required.\n\n'
                '## Exchange accuracy\n\n'
                'This simulation STEP package uses an approved 0.005 mm (5 micrometre) engineering exchange tolerance. Each imported physical component is checked in the global frame for body counts, exact extrema and actual trimmed edge geometry; curved edges use 2001 samples and a 1001-point support comparison. Sampled maxima are not rigorous whole-surface error bounds. Native reference CAD is unchanged. Mass-property volume deviations are reported separately in step_geometry_validation.csv and are not forced to zero. This is exchange geometry qualification, not a field or trajectory accuracy certificate.\n\n'
                'The two OA ideal grid sheets are zero-thickness electrostatic boundaries; particles are modelled as crossing them transparently. They are included with the matching grid-support voltage, and are not C0. Do not thicken them or turn them into opaque particle walls without specifying a different physical model.\n\n'
                '## C0 and open-space BEM\n\n'
                'The optional reference/c0_boundary_reference.step contains six zero-thickness surfaces at x = +/-162.5 mm, y = -242/558 mm and z = +/-425 mm. In our finite-domain model these prescribe a 0 V enclosure boundary. They are reference surfaces, not confirmed chamber CAD, extra electrode components or a manufactured shell with thickness and ports. The complete exported geometry is bilateral; x=0 is not a grounded wall.\n\n'
                'For an initial open-space BEM calculation, omit only the C0 reference sheets and retain all actual grounded conductors and shields in grounded_conductors.step. This defines an open-boundary comparison model. We have not established that omitting the enclosure has negligible influence on the ion trajectories. Keep the optional reference separate so its influence can be studied if needed.\n\n'
                'The previously supplied English overview remains applicable: two linear acceleration regions, exit focus at z=0, source settings, K, mirror symmetry and nominal incidence are unchanged. Import the STEP files instead of the proprietary files mentioned there. This is simulation geometry, not manufacturing drawings or a numerical-accuracy certificate.\n')
            if args.individual_step_delivery_run:
                description += ('\n## Individual parts and assembly overview\n\nEach of the 47 physical components has its own STEP file, including separately named grounded shields, mirror partners and closure plates. The six optional C0 reference faces are also separate files. All files share the same global origin, so simultaneous import retains alignment without assembly mates.\n\nOpen assembly/mrtof_electrode_assembly.step to view all 47 physical components at once, without C0 obscuring the apparatus. This overview contains different voltages: use the individual files and CSV for solver potential assignments. STEP products are not a SolidWorks parametric mating model; an importer may choose an assembly or a multi-body representation.\n')
                description=description.replace('reference/c0_boundary_reference.step contains six','six optional reference/c0_reference_*.step files contain six').replace('grounded_conductors.step','the separately named grounded electrode files')
            root=args.output.parent;(root/'README.md').write_text(description,encoding='utf-8')
            with (root/'step_geometry_validation.csv').open('w',newline='',encoding='utf-8') as file:
                writer=csv.writer(file);writer.writerow(['step_file','physical_component','solid_count','sheet_count','max_extrema_delta_mm','max_sampled_edge_delta_mm','volume_delta_mm3','volume_delta_relative'])
                for group in result['electrical_groups']:
                    for leaf in group['exchange_reopen']['leaves']:
                        if group.get('overview_only'):continue
                        writer.writerow([group['name']+'.step',leaf['physical_component'],leaf['solid_count'],leaf['sheet_count'],leaf['max_extrema_delta_mm'],leaf['trimmed_edge_validation']['max_sampled_delta_mm'],leaf['volume_delta_mm3'],leaf['volume_delta_relative']])
            with zipfile.ZipFile(root/'mrtof_step_delivery.zip','w',zipfile.ZIP_DEFLATED) as archive:
                for group in result['electrical_groups']:
                    folder='assembly' if group.get('overview_only') else ('reference' if group['optional_boundary_reference'] else 'electrodes')
                    archive.write(group['assembly_exchange'],folder+'/'+group['name']+'.step')
                for name in ('README.md','electrode_groups.csv','step_geometry_validation.csv'):archive.write(root/name,name)
            with zipfile.ZipFile(root/'mrtof_step_delivery.zip') as archive:
                if archive.testzip() is not None:raise RuntimeError('STEP delivery ZIP integrity failed')
        print(json.dumps({k:v for k,v in result.items() if k!='electrical_groups'}));return 0
    if bool(args.publish_cad_run)!=bool(args.english_overview) or bool(args.publish_cad_run)!=bool(args.overview_manifest):
        raise ValueError('Publication source, Word overview and document manifest must be supplied together')
    if args.publish_cad_run:
        if args.smoke or args.reuse_saved_parts or args.original_stripe_run or args.stripe_pose_run:
            raise ValueError('Publication cannot create or revalidate CAD')
        result=publish_validated_delivery(args.publish_cad_run,args.english_overview,args.output.parent,
            dict(geometry=args.geometry,authority=args.authority,materialization=args.materialization),
            args.overview_manifest,check_only=args.check_only)
        print(json.dumps(result));return 0
    parts=compile_parts(g,a)
    if bool(args.original_stripe_run)!=bool(args.stripe_pose_run):raise ValueError('Original native and pose evidence must be paired')
    if not args.smoke and not args.original_stripe_run:raise ValueError('Current complete delivery requires original native Stripe curves')
    if args.original_stripe_run:
        nr=args.original_stripe_run;pr=args.stripe_pose_run
        parts=original_stripe_instances(parts,g,json.loads((nr/'inputs/curve_contract.json').read_text()),
            json.loads((nr/'results/native_geometry.json').read_text()),json.loads((pr/'results/native_geometry.json').read_text()),
            json.loads((pr/'inputs/child_pose.json').read_text(encoding='utf8')),json.loads((pr/'inputs/current_frame.json').read_text()))
    if args.smoke_part:
        if not args.smoke:raise ValueError('Named part validation requires smoke scope')
        parts=[p for p in parts if p['name']==args.smoke_part]
        if len(parts)!=1:raise ValueError('Smoke part must name one frozen physical/reference component')
    if args.inspect_machining_holes:
        if args.smoke or not args.original_stripe_run or not args.reuse_saved_parts and not args.check_only:
            raise ValueError('Machining inventory requires the five original owned native copies')
        parts=[p for p in parts if p['geometry_kind']=='original_native_solid']
        if len(parts)!=5:raise ValueError('Machining inventory requires exactly five audited physical instances')
    if args.omit_mounting_holes and (args.inspect_machining_holes or not args.original_stripe_run):
        raise ValueError('No-hole simulation variant requires original native evidence and modification scope')
    if args.omit_mounting_holes:
        for part in parts:
            if part['geometry_kind']=='original_native_solid':part['cad_variant']='simulation__circular_mounting_holes_omitted'
    machining_inventory=None
    if args.machining_hole_audit_run:
        if not args.omit_mounting_holes:raise ValueError('Machining audit reference requires no-hole variant')
        audit=json.loads((args.machining_hole_audit_run/'machining_hole_inventory.json').read_text())
        if audit.get('status')!='PASS' or audit.get('component_count')!=5:raise ValueError('Five original-hole reference instances required')
        machining_inventory={p['name']:p for p in audit['parts']}
    if args.check_only:
        print(json.dumps(dict(status='PASS',part_count=len(parts),names=[p['name'] for p in parts])));return 0
    result=export_parts(parts,args.output,smoke=args.smoke,reuse=args.reuse_saved_parts,exchange_format=args.exchange_format,
                        inspect_machining_holes=args.inspect_machining_holes,omit_holes=args.omit_mounting_holes,
                        machining_inventory=machining_inventory)
    if args.inspect_machining_holes:
        (args.output.parent/'machining_hole_inventory.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k!='parts'}));return 0
    (args.output.parent/'cad_validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    (args.output.parent/'cad_parts_plan.json').write_text(json.dumps(parts,indent=2)+'\n',encoding='utf-8')
    with (args.output.parent/'bom.csv').open('w',newline='',encoding='utf-8') as f:
        fields=['name','group','electrode_namespace','electrode_id','voltage_v','geometry_kind'];writer=csv.DictWriter(f,fieldnames=fields)
        writer.writeheader();writer.writerows({k:p[k] for k in fields} for p in (parts[:1] if args.smoke else parts))
    description=(
        'MR-TOF frozen resolved engineering CAD delivery\n'
        'Units: project millimetres; assembly frame x=transverse, y=drift, z=reflection.\n'
        'Original Stripe part axes remain source-native; other parts use (project y,project z,project x). Exact per-part transforms are in cad_parts_plan.json/cad_validation.json.\n'
        'Individual neutral files use those declared local axes; use assembly exchange files for world placement.\n'
        'Parasolid assembly exchange is flattened world geometry; editable hierarchy/references remain in SLDASM and the electrical grouping is retained in BOM.\n'
        'Stripe curves: exact original native B-splines, not refitted or polyline CAD. Circular mounting-hole omission is explicitly recorded per part; rectangular beam slots and other features are retained. Modified no-hole volumes use their own cold-verified references, not original perforated-part volumes.\n'
        'CAD parts are physical/electrical groups, not a complete manufacturing design.\n'
        'C0 reference faces and OA ideal transparent sheets are zero thickness.\n'
        'Detector is the simulation-declared envelope, not a detailed MCP construction.\n'
        'No invented materials, tolerances, fasteners, insulators, supports, C0 thickness or ports.\n'
        'Frozen source geometry, authority and actual assembly materialization are in inputs/.\n'
        'BOM retains voltage namespaces; no different-potential conductors are merged.\n'
        'Native and neutral reopen results, dimensions, volumes, topology, interference and original preferences: cad_validation.json/cad_api_state.json.\n'
        'Native part/assembly reopens are read-only validation; editable custom-property repair is not a manufacturing qualification.\n'
        'No simulation numerical or manufacturing Formal qualification is granted.\n')
    if args.smoke:description+='SMOKE ONLY: one named component; not the complete assembly delivery.\n'
    (args.output.parent/'DELIVERY_README.txt').write_text(description,encoding='utf-8')
    if not args.smoke:
        with zipfile.ZipFile(args.output.parent/'mrtof_cad_delivery.zip','w',zipfile.ZIP_DEFLATED) as archive:
            # Only the verified deliverables and declared reference metadata;
            # vendor error logs, internal launchers and temporary files stay in run.
            include=delivery_paths(result,args.output.parent,original_curves=bool(args.original_stripe_run))
            for f in include:
                if not f.is_file():raise RuntimeError('Validated delivery dependency missing: '+str(f))
                archive.write(f,f.relative_to(args.output.parent).as_posix())
    print(json.dumps({k:v for k,v in result.items() if k!='parts'}));return 0


if __name__=='__main__':raise SystemExit(main())
