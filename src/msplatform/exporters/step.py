"""Optional STEP projection of a complete explicit Assembly snapshot."""
from __future__ import annotations
import math
import re
from importlib.metadata import version
from pathlib import Path, PureWindowsPath
from collections.abc import Mapping

from msplatform.components.geometry_members import assembly_geometry_members as _assembly_geometry_members








from msplatform.components.cad_geometry import (
    _finite, _validate_shape, _shape, _cad_precision_profile, _member_location,
)


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
    qualify that label. TOF and OA source member roles carry their actual bodies.
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
        elif project in {'single_reflection_oa_tof_mass_analyzer', 'orthogonal_accelerator', 'dual_cone_tandem_quadrupole', 'ion_processor', 'multi_reflection_tof'}:
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
    members=_assembly_geometry_members(assembly)
    for member in members: _validate_shape(member['shape'],surface=member['representation_role']=='ideal_surface')
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


def _probe_solid_bounds(solids):
    """Cache conservative world-space CadQuery bounds for explicit probes."""
    cached = []
    for solid in solids:
        box = solid.BoundingBox()
        bounds = (box.xmin, box.xmax, box.ymin, box.ymax, box.zmin, box.zmax)
        cached.append((solid, bounds))
    return cached


def _probe_inside(cached, point, tolerance):
    """Use isInside unchanged for every solid whose expanded bounds admit point."""
    for solid, bounds in cached:
        # Nonfinite bounds cannot safely exclude a point; retain the original call.
        if all(math.isfinite(value) for value in bounds) and all(
            bounds[2 * axis] <= bounds[2 * axis + 1] for axis in range(3)
        ):
            if any(point[axis] < bounds[2*axis] - tolerance or
                   point[axis] > bounds[2*axis+1] + tolerance for axis in range(3)):
                continue
        if solid.isInside(point, tolerance):
            return True
    return False


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
    members = _assembly_geometry_members(assembly)
    for member in members: _validate_shape(member['shape'],surface=member['representation_role']=='ideal_surface')
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
    if points:
        source_solids = _probe_solid_bounds(solid for shape in shapes for solid in shape.Solids())
        imported_solids = _probe_solid_bounds(solids)
    for probe in points:
        point = tuple(probe['point_mm'])
        expected = _probe_inside(source_solids, point, profile['occt_confusion'])
        actual = _probe_inside(imported_solids, point, profile['occt_confusion'])
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
