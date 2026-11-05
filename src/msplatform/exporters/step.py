"""Optional STEP projection of a complete explicit Assembly snapshot."""
from __future__ import annotations
import copy
import math
import re
from importlib.metadata import version
from pathlib import Path, PureWindowsPath
from collections.abc import Mapping

from msplatform.contracts.rigid_transform import RigidTransform
from msplatform.assembly.resolve_assembly import compile_assembly_layout
from msplatform.components.rf_multipole.assembly_interface import build_assembly_interface as rf_interface
from msplatform.components.single_reflection_oa_tof.assembly_interface import resolve_assembly_interface as tof_interface
from msplatform.components.single_reflection_oa_tof.accelerator_geometry import resolve_accelerator_geometry, apply_side_opening
from msplatform.components.rf_multipole.geometry_members import iter_geometry_members as rf_members
from msplatform.components.single_reflection_oa_tof.geometry_members import iter_geometry_members as tof_members


def assembly_geometry_members(assembly: Mapping) -> tuple[dict, ...]:
    """Resolve full selected member coverage without importing a CAD engine.

    Local shapes are retained; the proper local-to-assembly transform is applied
    once only by the exporter. Source refs address the exact resolved snapshot.
    """
    if not isinstance(assembly,Mapping) or set(assembly)!={'composition_plan','components_resolved'}:
        raise ValueError('complete Assembly snapshot required')
    plan,components=assembly['composition_plan'],assembly['components_resolved']
    selected=plan['scope']['instance_ids']
    if not selected or set(plan['components'])!=set(components): raise ValueError('complete parent Assembly resolved coverage differs')
    if compile_assembly_layout(plan['recipe'],plan['components'],local_scope=plan.get('local_scope'))!=plan:
        raise ValueError('CAD Assembly plan differs from its canonical parent layout')
    poses={row['instance_id']:row['transform'] for row in plan['recipe']['instances']}
    result=[]
    for instance in selected:
        interface=plan['components'][instance]
        project=interface['project_id'];resolved=components[instance]
        if project=='rf_multipole_ion_optics':
            actual=rf_interface(resolved,geometry_profile_id=interface['geometry_profile_id'])
            members=rf_members(resolved)
        elif project=='single_reflection_oa_tof_mass_analyzer':
            if interface['variant_id']!='three_zone_square': raise ValueError('complete TOF STEP requires three_zone_square')
            projection=apply_side_opening(resolve_accelerator_geometry(resolved,variant_id=interface['variant_id']),side_opening=resolved['mechanical_side_opening'])
            actual=tof_interface(resolved,projection=projection,geometry_profile_id=interface['geometry_profile_id'])
            members=tof_members(resolved)
        else: raise ValueError('STEP provider not implemented: '+project)
        if actual!=interface: raise ValueError('CAD resolved design differs from its provider interface')
        transform=RigidTransform.from_contract(poses[instance])
        if transform.from_frame_id!=interface['local_frame_id']: raise ValueError('CAD source frame differs from interface')
        identities=set()
        for member in members:
            if member['member_id'] in identities: raise ValueError('duplicate physical member identity')
            identities.add(member['member_id'])
            if member['local_frame_id']!=transform.from_frame_id: raise ValueError('member frame differs from its actual pose')
            if member['representation_role'] not in {'physical_solid','ideal_surface'}: raise ValueError('unknown physical representation')
            for ref in member['source_refs']:
                value=resolved
                for token in ref.split('/')[1:]: value=value[int(token)] if isinstance(value,list) else value[token]
            _validate_shape(member['shape'],surface=member['representation_role']=='ideal_surface')
            result.append(dict(copy.deepcopy(member),instance_id=instance,transform=copy.deepcopy(poses[instance])))
    return tuple(result)


def _finite(values):
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in values): raise ValueError('CAD dimensions must be finite')


def _validate_shape(spec, *, surface=False):
    kind=spec.get('kind')
    if kind=='union':
        if not spec.get('parts'): raise ValueError('empty physical union')
        for part in spec['parts']: _validate_shape(part,surface=surface)
    elif kind=='difference':
        _validate_shape(spec['base'],surface=surface)
        if not spec['tools']: raise ValueError('empty Boolean tool list')
        for tool in spec['tools']: _validate_shape(tool,surface=surface)
    elif kind=='box':
        _finite([*spec['center_mm'],*spec['size_mm']])
        if len(spec['center_mm'])!=3 or len(spec['size_mm'])!=3 or any(v<0 or (v==0 and not surface) for v in spec['size_mm']): raise ValueError('invalid box dimensions')
    elif kind=='cylinder':
        _finite([*spec['center_mm'],spec['radius_mm'],spec['height_mm']])
        if len(spec['center_mm'])!=3 or spec['radius_mm']<=0 or spec['height_mm']<0 or (spec['height_mm']==0 and not surface): raise ValueError('invalid cylinder dimensions')
    elif kind in {'rod','annulus'}:
        _finite([*spec['center_xy_mm'],spec['z_min_mm'],spec['z_max_mm']])
        if len(spec['center_xy_mm'])!=2 or spec['z_max_mm']<spec['z_min_mm'] or (spec['z_max_mm']==spec['z_min_mm'] and not surface): raise ValueError('invalid physical axial interval')
        if kind=='annulus':
            _finite([spec['inner_radius_mm'],spec['outer_radius_mm']])
            if not 0<=spec['inner_radius_mm']<spec['outer_radius_mm']: raise ValueError('invalid annulus radii')
        elif 'radius_mm' in spec:
            _finite([spec['radius_mm']])
            if spec['radius_mm']<=0: raise ValueError('invalid rod radius')
        else:
            _finite([spec[k] for k in ('semi_major_axis_mm','semi_minor_axis_mm','major_axis_angle_rad')])
            if not 0<spec['semi_minor_axis_mm']<=spec['semi_major_axis_mm']: raise ValueError('invalid ellipse axes')
    else: raise ValueError('unknown physical primitive')


def _shape(cq, spec):
    kind=spec['kind']
    if kind=='union':
        parts=[_shape(cq,p) for p in spec['parts']]
        if not parts: raise ValueError('empty physical union')
        result=parts[0]
        for part in parts[1:]: result=result.fuse(part)
        return result
    if kind=='difference':
        result=_shape(cq,spec['base'])
        for tool in spec['tools']: result=result.cut(_shape(cq,tool))
        return result
    if kind=='box':
        center,size=spec['center_mm'],spec['size_mm'];_finite([*center,*size])
        if min(size)<=0: raise ValueError('physical CAD box must have positive spans')
        return cq.Workplane('XY').box(*size).val().translate(tuple(center))
    if kind=='cylinder':
        x,y,z=spec['center_mm'];r,h=spec['radius_mm'],spec['height_mm'];_finite([x,y,z,r,h])
        if min(r,h)<=0: raise ValueError('physical CAD cylinder must have positive dimensions')
        return cq.Workplane('XY').circle(r).extrude(h).val().translate((x,y,z-h/2))
    if kind in {'rod','annulus'}:
        x,y=spec['center_xy_mm'];lo,hi=spec['z_min_mm'],spec['z_max_mm'];_finite([x,y,lo,hi])
        if hi<=lo: raise ValueError('physical CAD axial interval must be positive')
        work=cq.Workplane('XY')
        angle=0.
        if kind=='annulus':
            inner,outer=spec['inner_radius_mm'],spec['outer_radius_mm'];_finite([inner,outer])
            if not 0<=inner<outer: raise ValueError('invalid annulus radii')
            work=work.circle(outer)
            if inner>0: work=work.circle(inner)
        elif 'radius_mm' in spec:
            r=spec['radius_mm'];_finite([r])
            if r<=0: raise ValueError('rod radius must be positive')
            work=work.circle(r)
        else:
            a,b,angle=(spec[k] for k in ('semi_major_axis_mm','semi_minor_axis_mm','major_axis_angle_rad'));_finite([a,b,angle])
            if not 0<b<=a: raise ValueError('invalid ellipse axes')
            work=work.ellipse(a,b)
        result=work.extrude(hi-lo).val()
        if angle: result=result.rotate((0,0,0),(0,0,1),math.degrees(angle))
        return result.translate((x,y,lo))
    raise ValueError('unsupported physical CAD shape: '+str(kind))


def _cad_precision_profile():
    from OCP.Precision import Precision
    approximation,confusion=Precision.Approximation_s(),Precision.Confusion_s()
    if approximation!=1e-6 or confusion!=1e-7:
        raise RuntimeError('OCCT precision differs from the predeclared millimetre CAD profile')
    return dict(profile_id='physical_solids_occt_approximation_v1', length_error_bound_mm=1e-6,
                occt_approximation=approximation, occt_confusion=confusion)


def _member_location(cq, transform):
    t = RigidTransform.from_contract(transform)
    r = t.rotation
    return cq.Location(cq.Plane(origin=t.translation_mm, xDir=(r[0][0],r[1][0],r[2][0]),
                               normal=(r[0][2],r[1][2],r[2][2])))


def step_export_filename(options: Mapping) -> str:
    """Validate the sole CAD option boundary and return its owned STEP leaf.

    Optional name is a user file stem and root product display name. Win32
    filename restrictions apply only here; export names are printable ASCII
    per the caller display contract. Source/member display labels are not
    filesystem paths. No case, Unicode normalization or lossy slugging is used.
    """
    if (not isinstance(options, Mapping)
            or not {'write_pcurves', 'precision_mode'} <= set(options)
            or set(options) - {'write_pcurves', 'precision_mode', 'name'}):
        raise ValueError('explicit STEP write_pcurves and precision_mode required')
    if (type(options['write_pcurves']) is not bool or type(options['precision_mode']) is not int
            or options['precision_mode'] not in (-1, 0, 1)):
        raise ValueError('invalid STEP export options')
    if 'name' not in options:
        return 'assembly.step'
    name = options['name']
    if isinstance(name, str) and any(not 32 <= ord(c) <= 126 for c in name):
        raise ValueError('STEP name requires printable English/ASCII characters')
    # Microsoft Win32 Naming Files, Paths and Namespaces. PureWindowsPath owns
    # reserved DOS device recognition; the existing RunSession owns containment.
    if (not isinstance(name, str) or not name or name in {'.', '..'}
            or name[-1:] in {' ', '.'} or name[:1] == ' '
            or any(ord(c) < 32 or c in '<>:"/\\|?*' for c in name)
            or PureWindowsPath(name).is_reserved()):
        raise ValueError('STEP name must be a legal single Windows filename stem')
    return name + '.step'


def _label_token(value: str) -> str:
    """Injectively encode a source token; dot separates tokens, not identity."""
    if not isinstance(value, str) or not value:
        raise ValueError('STEP label requires a nonempty source identity token')
    return ''.join(chr(byte) if (48 <= byte <= 57 or 65 <= byte <= 90
                    or 97 <= byte <= 122 or byte in (45, 95)) else f'%{byte:02X}'
                   for byte in value.encode('utf-8'))


def step_member_names(assembly: Mapping, members) -> dict[tuple[str, str], str]:
    """Name actual instance/member products, independently of iteration order.

    RF references supply physical rod/segment identity; electrical groups only
    qualify that label. TOF's complete source member role carries stage/ring.
    A compound stays one named product and retains all its physical solids.
    """
    names, used = {}, set()
    for member in members:
        instance, identity = member['instance_id'], member['member_id']
        key = (instance, identity)
        project = assembly['composition_plan']['components'][instance]['project_id']
        if project == 'rf_multipole_ion_optics':
            row = assembly['components_resolved'][instance]
            for part in identity.split('/')[1:]:
                row = row[int(part)] if isinstance(row, list) else row[part]
            if 'rod_id' in row or 'parent_rod_id' in row:
                tokens = ([f"segment_{row['segment_id']:04d}"] if 'segment_id' in row else [])
                rod = row['parent_rod_id'] if 'parent_rod_id' in row else row['rod_id']
                tokens += [f'rod_{rod:04d}', f"rf_group_{row['electrode_group']}"]
            else:
                tokens = [row['role']]
        elif project == 'single_reflection_oa_tof_mass_analyzer':
            tokens = identity.split('/')
        else:
            raise ValueError('STEP naming provider is unsupported: ' + project)
        label = '.'.join(_label_token(value) for value in [instance, *tokens])
        if key in names or label.casefold() in used:
            raise ValueError('duplicate STEP physical member display name')
        names[key] = label
        used.add(label.casefold())
    return names


def export_assembly_step(assembly: Mapping, *, destination: Path, representation: str, options: Mapping) -> dict:
    """Write explicit physical_solids STEP only; never open GUI or launch a solver.

    Requires the optional CadQuery installation. Caller owns workspace/capacity/
    publication and freezes the returned member/exclusion list with its output.
    Assembly locations apply proper R+t once, in mm; no manufacturing thickness
    is invented for ideal sheets. Export tolerance settings must be explicit.
    """
    if representation!='physical_solids': raise ValueError('only physical_solids STEP is implemented')
    filename = step_export_filename(options)
    members=assembly_geometry_members(assembly)
    names=step_member_names(assembly,members)
    root_name = options.get('name', 'mass_spectrometry')
    if any(root_name == names[(member['instance_id'], member['member_id'])]
           for member in members if member['representation_role'] == 'physical_solid'):
        raise ValueError('STEP root name matches an exported physical member; choose another export name')
    destination=Path(destination)
    if 'name' in options and destination.name != filename:
        raise ValueError('STEP destination differs from the explicit export name')
    if destination.exists() or destination.suffix.lower() not in {'.step','.stp'}: raise ValueError('new STEP destination required')
    try: import cadquery as cq
    except ImportError as error: raise RuntimeError('STEP export requires the optional cad-step CadQuery dependency') from error
    profile = _cad_precision_profile()
    model=cq.Assembly(name=root_name)
    exported,excluded=[],[]
    for member in members:
        if member['representation_role']=='ideal_surface':
            excluded.append(dict(instance_id=member['instance_id'],member_id=member['member_id'],source_refs=member['source_refs'],reason='ideal_zero_thickness_surface_not_mechanical_solid'))
            continue
        shape=_shape(cq,member['shape'])
        if not shape.isValid() or not shape.Solids() or shape.Volume()<=0: raise ValueError('invalid or empty physical member: '+member['member_id'])
        location = _member_location(cq, member['transform'])
        name=names[(member['instance_id'],member['member_id'])]
        model.add(shape,name=name,loc=location)
        exported.append(dict(instance_id=member['instance_id'],member_id=member['member_id'],step_name=name,
            electrode_group_id=member['electrode_group_id'],representation_role='physical_solid',source_refs=member['source_refs'],transform=member['transform'],
            volume_mm3=shape.Volume(),surface_area_mm2=shape.Area(),solid_count=len(shape.Solids())))
    if not exported: raise ValueError('no actual physical solids selected')
    destination.parent.mkdir(parents=True,exist_ok=True)
    try:
        model.export(str(destination),exportType='STEP',mode='default',write_pcurves=options['write_pcurves'],precision_mode=options['precision_mode'])
        if not destination.is_file() or destination.stat().st_size==0: raise RuntimeError('STEP exporter produced no data')
    except BaseException:
        if destination.exists(): destination.unlink()
        raise
    return dict(schema_version=1,role='assembly_step_projection',representation=representation,length_unit='mm',
        parent_instance_ids=list(assembly['composition_plan']['components']),
        selected_instance_ids=list(assembly['composition_plan']['scope']['instance_ids']),
        source_member_count=len(members),boolean_tool_policy='nested_CSG_tools_not_exported_as_separate_members',
        transform_policy='local_bodies_plus_single_assembly_location',
        cad_profile=profile,exported_members=exported,excluded_members=excluded,
        step_path=str(destination),engine=dict(cadquery=cq.__version__,cadquery_ocp=version('cadquery-ocp')),
        step_file_schema=re.search(r'FILE_SCHEMA\s*\((.*?)\);',destination.read_text(encoding='utf-8'),re.S).group(1),options=dict(options),
        claim='parameterized simplified physical geometry; not manufacturing or field qualification')


def _inspection_probes(probes):
    points, seen = [], set()
    for probe in probes:
        if (not isinstance(probe, Mapping) or set(probe) != {"probe_id", "point_mm"}
                or not isinstance(probe["probe_id"], str) or not probe["probe_id"] or probe["probe_id"] in seen
                or not isinstance(probe["point_mm"], (list,tuple)) or len(probe["point_mm"]) != 3):
            raise ValueError("STEP probes require unique explicit IDs and world point_mm")
        _finite(probe["point_mm"])
        seen.add(probe["probe_id"]); points.append(dict(probe_id=probe["probe_id"],point_mm=list(probe["point_mm"])))
    return points


def inspect_assembly_step(step_path: Path, *, assembly: Mapping, export_report: Mapping,
                          probes=()) -> dict:
    """Cold-read an existing STEP; compare only named source/serialization checks.

    No export, file write, GUI or solver runs. Explicit probes compare the
    imported full assembly against source-owned CSG at world points in mm;
    they do not certify every aperture, manufacturing dimension or topology.
    """
    projection = export_report["projection"]
    if (type(export_report.get("schema_version")) is not int or export_report.get("schema_version") != 1 or export_report.get("role") != "owned_assembly_step_export"
            or type(projection.get("schema_version")) is not int or projection.get("schema_version") != 1 or projection.get("role") != "assembly_step_projection"
            or projection.get("representation") != "physical_solids" or projection.get("length_unit") != "mm"):
        raise ValueError("current physical-solids STEP report required")
    points = _inspection_probes(probes)
    members = assembly_geometry_members(assembly)
    try: import cadquery as cq
    except ImportError as error: raise RuntimeError("STEP inspection requires the optional cad-step CadQuery dependency") from error
    profile = _cad_precision_profile()
    if projection["cad_profile"] != profile:
        raise ValueError("STEP report precision profile differs from the canonical serialization profile")
    physical = [member for member in members if member['representation_role'] == 'physical_solid']
    expected_keys = [(member['instance_id'],member['member_id']) for member in physical]
    if [(member['instance_id'],member['member_id']) for member in projection['exported_members']] != expected_keys:
        raise ValueError("STEP report member coverage differs from the authoritative source")
    shapes = [_shape(cq,member['shape']).moved(_member_location(cq,member['transform'])) for member in physical]
    expected_volume = sum(shape.Volume() for shape in shapes)
    expected_area = sum(shape.Area() for shape in shapes)
    expected_solids = sum(len(shape.Solids()) for shape in shapes)
    loaded = cq.importers.importStep(str(step_path)).val()
    solids = loaded.Solids()
    volume = loaded.Volume()
    residual = volume - expected_volume
    bound = profile['length_error_bound_mm'] * expected_area
    failed = []
    if not loaded.isValid() or not solids or not math.isfinite(volume) or volume <= 0:
        failed.append('invalid_or_empty_imported_brep')
    if len(solids) != expected_solids: failed.append('solid_count_differs')
    if abs(residual) > bound: failed.append('source_volume_serialization_bound_exceeded')
    probe_results = []
    for probe in points:
        expected = any(solid.isInside(tuple(probe['point_mm']),profile['occt_confusion'])
                       for shape in shapes for solid in shape.Solids())
        actual = any(solid.isInside(tuple(probe['point_mm']),profile['occt_confusion']) for solid in solids)
        if actual != expected: failed.append('probe:' + probe['probe_id'])
        probe_results.append(dict(probe,expected_source_inside=expected,actual_step_inside=actual,matches=actual==expected))
    box = loaded.BoundingBox()
    return dict(schema_version=1,role='assembly_step_semantic_inspection',status='mismatch' if failed else 'consistent',
        checks_performed=['cold_step_brep_validity','solid_count','source_volume_serialization_bound','explicit_world_point_probes'],
        failed_checks=failed,solid_count=len(solids),expected_solid_count=expected_solids,
        volume_mm3=volume,expected_source_volume_mm3=expected_volume,volume_residual_mm3=residual,
        volume_serialization_bound_mm3=bound,bounds_mm=dict(xmin=box.xmin,xmax=box.xmax,ymin=box.ymin,ymax=box.ymax,zmin=box.zmin,zmax=box.zmax),
        probes=probe_results,cad_profile=profile,engine=dict(cadquery=cq.__version__,cadquery_ocp=version('cadquery-ocp')),
        unavailable_checks=['all_holes_and_dimensions','per_member_topology_mapping','manufacturing_or_scientific_qualification'],
        scientific_qualification='not_granted',gui_calls=0,export_calls=0)
