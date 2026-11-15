"""Bounded neutral Assembly to legacy GEM; geometry only, never solve or Fly."""
from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Mapping
from fractions import Fraction
from typing import Any

from msplatform.components.geometry_members import assembly_geometry_members
from msplatform.contracts.rigid_transform import RigidTransform
from .gem_primitives import centered_box3d, cylinder_z, format_number, grounded_pa_face_lines


def _vector(value: Any, name: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3 or any(type(x) not in (int, float) or not math.isfinite(x) for x in value):
        raise ValueError(name + ' requires three finite numbers')
    return [float(x) for x in value]


def _record_rounding(values: list[float], rounding: list[dict[str, Any]]) -> None:
    for value in values:
        text = format_number(value)
        if float(text) != value:
            rounding.append({'input': value, 'serialized': text})


def _world_primitive(shape: Mapping[str, Any], transform: RigidTransform, rounding: list[dict[str, Any]]) -> tuple[str, list[float], list[float]]:
    kind = shape.get('kind'); rotation = transform.rotation
    if kind == 'rod':
        if set(shape) != {'kind', 'center_xy_mm', 'z_min_mm', 'z_max_mm', 'radius_mm'}:
            raise ValueError('GEM supports only canonical round rods')
        center_xy = shape['center_xy_mm']; low = shape['z_min_mm']; high = shape['z_max_mm']
        if (not isinstance(center_xy, (list, tuple)) or len(center_xy) != 2
                or any(type(value) not in (int, float) or not math.isfinite(value)
                       for value in (*center_xy, low, high)) or high <= low):
            raise ValueError('GEM round rod requires finite center and positive axial extent')
        shape = dict(kind='cylinder', center_mm=[*center_xy, (low + high) / 2],
                     radius_mm=shape['radius_mm'], height_mm=high - low)
        kind = 'cylinder'
    if any(sum(abs(x) for x in row) != 1 or any(x not in (-1, 0, 1) for x in row) for row in rotation):
        raise ValueError('GEM pose requires a signed axis-permutation rotation')
    if kind in {'ip_box', 'ip_cylinder_x'}:
        from msplatform.components.dual_pressure_rectilinear_ion_processor.convex_geometry import shape_bounds
        from .ip_geometry import _primitive
        local = {'shape': kind[3:], **{key: value for key, value in shape.items() if key != 'kind'}}
        local_lo, local_hi = shape_bounds(local)
        center = [(a+b)/2 for a,b in zip(local_lo,local_hi,strict=True)]
        size = [b-a for a,b in zip(local_lo,local_hi,strict=True)]
        if kind == 'ip_cylinder_x':
            center = [(local['x_min_mm']+local['x_max_mm'])/2,local['center_y_mm'],local['center_z_mm']]
            size = [local['x_max_mm']-local['x_min_mm'],2*local['radius_mm'],2*local['radius_mm']]
        if any(value <= 0 for value in size): raise ValueError('GEM physical primitive requires positive extents')
        world = [sum(rotation[i][j]*center[j] for j in range(3))+transform.translation_mm[i] for i in range(3)]
        span = [sum(abs(rotation[i][j])*size[j] for j in range(3)) for i in range(3)]
        lower=[];upper=[]
        for i in range(3):
            j=next(j for j in range(3) if rotation[i][j])
            endpoints=[rotation[i][j]*value+transform.translation_mm[i] for value in (local_lo[j],local_hi[j])]
            lower.append(min(endpoints));upper.append(max(endpoints))
        if kind == 'ip_box':
            _record_rounding(world+span, rounding)
            return _primitive(dict(shape='box',min_mm=lower,max_mm=upper)),lower,upper
        radius = local['radius_mm']; axis = next(i for i in range(3) if abs(rotation[i][0]) == 1)
        height = local_hi[0]-local_lo[0]
        if axis == 0:
            _record_rounding([lower[0],upper[0],world[1],world[2],radius], rounding)
            return _primitive(dict(shape='cylinder_x',x_min_mm=lower[0],x_max_mm=upper[0],
                center_y_mm=world[1],center_z_mm=world[2],radius_mm=radius)),lower,upper
        top = list(world); top[axis] += height/2
        _record_rounding(top+[radius,height], rounding)
        if axis == 2:
            return cylinder_z(top[0],top[1],top[2],radius,height),lower,upper
        primitive = ('locate(' + ','.join(format_number(v) for v in top) + ') { rotate_x(-90) { '
                     + cylinder_z(0.,0.,0.,radius,height) + ' } }')
        return primitive,lower,upper
    center = _vector(shape.get('center_mm'), 'primitive center')
    world = [sum(rotation[i][j]*center[j] for j in range(3))+transform.translation_mm[i] for i in range(3)]
    if kind == 'box':
        size = _vector(shape.get('size_mm'), 'box size')
        if any(x <= 0 for x in size): raise ValueError('GEM physical box requires positive extents')
        span = [sum(abs(rotation[i][j])*size[j] for j in range(3)) for i in range(3)]
        _record_rounding(world+span, rounding)
        return centered_box3d(*world, *span), [world[i]-span[i]/2 for i in range(3)], [world[i]+span[i]/2 for i in range(3)]
    if kind == 'cylinder':
        radius, height = shape.get('radius_mm'), shape.get('height_mm')
        if any(type(x) not in (int,float) or not math.isfinite(x) or x <= 0 for x in (radius,height)):
            raise ValueError('GEM physical cylinder requires positive finite radius and height')
        radius, height = float(radius), float(height)
        axis = next(i for i in range(3) if abs(rotation[i][2]) == 1)
        span = [2 * radius] * 3; span[axis] = height
        low = [world[i] - span[i] / 2 for i in range(3)]
        high = [world[i] + span[i] / 2 for i in range(3)]
        top = list(world); top[axis] += height / 2
        if axis == 2:
            _record_rounding([world[0], world[1], radius, height, top[2]], rounding)
            primitive = cylinder_z(top[0], top[1], top[2], radius, height)
        else:
            _record_rounding(top + [radius, height], rounding)
            rotate = 'rotate_y(90)' if axis == 0 else 'rotate_x(-90)'
            primitive = ('locate(' + ','.join(format_number(v) for v in top) + ') { '
                         + rotate + ' { ' + cylinder_z(0., 0., 0., radius, height) + ' } }')
        return primitive, low, high
    raise ValueError('unsupported GEM physical primitive: '+str(kind))


def _pieces(shape: Mapping[str, Any], transform: RigidTransform, rounding: list[dict[str, Any]]) -> list[tuple[str,list[str],list[float],list[float]]]:
    if not isinstance(shape,Mapping): raise ValueError('GEM member shape must be a mapping')
    kind=shape.get('kind')
    if kind=='union':
        parts=shape.get('parts')
        if not isinstance(parts,(list,tuple)) or not parts: raise ValueError('GEM union requires nonempty parts')
        return [piece for part in parts for piece in _pieces(part,transform,rounding)]
    if kind=='difference':
        base=shape.get('base');tools=shape.get('tools')
        if not isinstance(base,Mapping) or not isinstance(tools,(list,tuple)) or not tools:
            raise ValueError('GEM difference requires a base and tools')
        def flatten_tool(tool):
            if not isinstance(tool,Mapping): raise ValueError('GEM difference tool must be a shape')
            if tool.get('kind')=='union':
                parts=tool.get('parts')
                if not isinstance(parts,(list,tuple)) or not parts: raise ValueError('GEM union requires nonempty parts')
                return [term for part in parts for term in flatten_tool(part)]
            if tool.get('kind')=='difference': raise ValueError('nested difference tool is not supported by GEM')
            return [_world_primitive(tool,transform,rounding)[0]]
        cuts=[term for tool in tools for term in flatten_tool(tool)]
        pieces=_pieces(base,transform,rounding)
        return [(primitive,prior+cuts,lo,hi) for primitive,prior,lo,hi in pieces]
    primitive,lo,hi=_world_primitive(shape,transform,rounding)
    return [(primitive,[],lo,hi)]


def render_assembly_gem(assembly: Mapping[str, Any], *, domain: Mapping[str, Any], pitch_mm: float,
                        boundary: str) -> dict[str, Any]:
    """Render the actual source-validated provider members."""
    members = assembly_geometry_members(assembly)
    return _render_assembly_members_gem(assembly, members, domain=domain, pitch_mm=pitch_mm, boundary=boundary)


def _render_assembly_members_gem(assembly: Mapping[str, Any], members, *, domain: Mapping[str, Any],
                                 pitch_mm: float, boundary: str) -> dict[str, Any]:
    """Render a source-validated neutral Assembly, without a native process.

    Only signed-permutation boxes and cylinders are admitted. Distinct
    conductor AABBs must be strictly separated; ambiguous overlap is refused.
    """
    if not isinstance(domain,Mapping) or set(domain)!={'frame_id','minimum_mm','maximum_mm'}:
        raise ValueError('explicit GEM world domain requires minimum_mm and maximum_mm')
    if not isinstance(assembly,Mapping) or domain['frame_id'] != assembly.get('composition_plan',{}).get('recipe',{}).get('assembly_frame_id'):
        raise ValueError('GEM world domain frame differs from Assembly')
    lo=_vector(domain['minimum_mm'],'domain minimum'); hi=_vector(domain['maximum_mm'],'domain maximum')
    if type(pitch_mm) not in (int,float) or not math.isfinite(pitch_mm) or pitch_mm <= 0:
        raise ValueError('GEM pitch must be positive and finite')
    if boundary not in {'grounded_faces','native_zero_neumann'}: raise ValueError('explicit GEM boundary policy unsupported')
    pitch=float(pitch_mm);counts=[]
    for left,right in zip(lo,hi,strict=True):
        cells=(Fraction(str(right))-Fraction(str(left)))/Fraction(str(pitch))
        if cells.denominator!=1 or cells<2: raise ValueError('GEM domain must have at least three grid nodes and exact pitch alignment')
        counts.append(int(cells)+1)
    rounding: list[dict[str, Any]] = []
    _record_rounding(lo+hi+[-x for x in lo]+[pitch], rounding)

    if not members: raise ValueError('GEM requires at least one physical member')
    groups={};witness=[];all_boxes=[]
    for member in members:
        if member['representation_role']!='physical_solid': raise ValueError('unsupported GEM representation: '+str(member['representation_role']))
        key=(member['instance_id'],member['electrode_group_id'])
        if any(not isinstance(x,str) or not x for x in key): raise ValueError('GEM physical member requires an explicit electrode group')
        transform=RigidTransform.from_contract(member['transform']);pieces=_pieces(member['shape'],transform,rounding)
        for primitive,cuts,lower,upper in pieces:
            if any(lower[i]<=lo[i] or upper[i]>=hi[i] for i in range(3)):
                raise ValueError('GEM physical member is not strictly inside the world domain')
            for previous,pl,pu in all_boxes:
                if previous!=key and all(lower[i]<=pu[i] and pl[i]<=upper[i] for i in range(3)):
                    raise ValueError('GEM cannot verify independent-conductor separation: bounding boxes overlap')
            all_boxes.append((key,lower,upper));groups.setdefault(key,[]).append((primitive,cuts))
        witness.append(dict(instance_id=key[0],electrode_group_id=key[1],member_id=member['member_id'],source_refs=copy.deepcopy(member['source_refs']),transform=copy.deepcopy(member['transform'])))
    ordered=sorted(groups);mapping=[dict(instance_id=a,electrode_group_id=b,native_id=i) for i,(a,b) in enumerate(ordered,1)]
    f=format_number
    lines=['; Neutral Assembly: physical solids; no solve or Fly.',f"pa_define({','.join(map(str,counts))},planar,none,electrostatic,,{f(pitch)},{f(pitch)},{f(pitch)},surface=fractional)",f"locate({','.join(f(-x) for x in lo)}) {{"]
    for row,key in zip(mapping,ordered,strict=True):
        lines.append('  e('+str(row['native_id'])+') {')
        for primitive,cuts in groups[key]:
            lines.append('    fill {');lines.append('      within { '+primitive+' }')
            lines.extend('      notin { '+cut+' }' for cut in cuts);lines.append('    }')
        lines.append('  }')
    if boundary=='grounded_faces':
        box={a+s:v for a,l,h in zip('xyz',lo,hi,strict=True) for s,v in (('_min',l),('_max',h))}
        for axis in range(3):
            for side in ('min', 'max'):
                lower, upper = list(lo), list(hi)
                lower[axis] = upper[axis] = box['xyz'[axis] + '_' + side]
                _record_rounding([(a+b)/2 for a,b in zip(lower,upper)] + [b-a for a,b in zip(lower,upper)], rounding)
        lines+=['  e(0) {',*grounded_pa_face_lines(box),'  }']
    lines+=['}',''];gem='\n'.join(lines)
    return dict(role='neutral_assembly_gem',gem=gem,gem_sha256=hashlib.sha256(gem.encode('utf8')).hexdigest(),domain=copy.deepcopy(dict(domain)),pitch_mm=pitch,boundary=boundary,dimensions=counts,electrode_mapping=mapping,members=witness,serialization=dict(convention='existing_gem_primitives_12_significant_digits',rounded_values=rounding),scope='geometry_only_not_native_or_field_qualification')
