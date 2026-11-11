"""Pure CAD parts plan for the complete resolved MR+OA physical assembly.

Inputs retain the frozen project millimetre geometry and explicit voltage
namespaces. Output separates solids, cuts and zero-thickness reference sheets;
it performs no I/O, CAD-engine work, native execution or owner creation.
This is not an MR-only component member resolver or a generic STEP provider.
"""
from __future__ import annotations

import copy
import math


def rectangle(box: list[float]) -> dict:
    """Represent a project box as an x-directed extrusion."""
    return dict(x=[box[0],box[3]],polygon_yz_mm=[
        [box[1],box[2]],[box[4],box[2]],[box[4],box[5]],[box[1],box[5]]])


def _mirror_operations(item: dict, legacy_cuts: tuple = ()) -> tuple[list[dict], list[dict]]:
    """Consume resolved mirror solids and slots, not their rotated AABBs."""
    if 'polygon_yz_mm' in item:
        solids = [dict(x=item['x'], polygon_yz_mm=item['polygon_yz_mm'])]
        cuts = [dict(x=hole['x'], polygon_yz_mm=hole['polygon_yz_mm'])
                for hole in item['holes']]
        return solids, cuts
    return [rectangle(item['box'])], [rectangle(box) for box in legacy_cuts]


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
        solids,cuts=_mirror_operations(e,(e['beam_slot'],))
        add(f"mirror_{side}_e{e['id']:02}",'mirror',e['id'],solids,cuts)
    for i,e in enumerate(geometry['mirror_ground_shields'],1):
        legacy_cuts=(geometry['mirror_inner_shield_slot'],) if e['role']=='inner_stripe_facing_4mm_slot' else ()
        solids,cuts=_mirror_operations(e,legacy_cuts)
        add(f'mirror_ground_shield_{i}','ground_shield',15,solids,cuts)
    for i,e in enumerate(geometry['mirror_e_closures'],1):
        solids,cuts=_mirror_operations(e)
        add(f'mirror_outer_closure_{i}','mirror',e['id'],solids,cuts)
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
