"""Independent coverage and shape facts for the real complete Assembly."""
import copy
import unittest
import hashlib

from msplatform import assembly as assembly_api, components as component_api, examples as example_api
from msplatform.components.geometry_members import assembly_geometry_members
from msplatform.contracts.machine_contracts import ContractError
from msplatform.contracts.rigid_transform import RigidTransform, FramedPosition


def real_snapshot():
    case=example_api.load_example('rf_oatof_functional_v1')
    parts={name:component_api.resolve_component(req) for name,req in case.component_requests.items()}
    assembly=assembly_api.assemble(case.recipe,parts)
    return dict(composition_plan=assembly.composition_plan,components_resolved=assembly.components_resolved,
                components_source=assembly.components_source)


class GeometryMemberTests(unittest.TestCase):
    def test_complete_real_octupole_tof_physical_and_ideal_coverage(self):
        snapshot=real_snapshot();before=copy.deepcopy(snapshot)
        members=assembly_geometry_members(snapshot)
        self.assertEqual(snapshot,before)
        rf=[m for m in members if m['instance_id']=='multipole']
        self.assertEqual(len(rf),32)
        self.assertTrue(all(m['representation_role']=='physical_solid' for m in rf))
        tof=[m for m in members if m['instance_id']=='oatof']
        self.assertEqual(len([m for m in tof if m['representation_role']=='ideal_surface']),5)
        roles={m['member_id']:m for m in tof}
        self.assertIn('flight_tube_shield',roles);self.assertIn('detector',roles)
        self.assertEqual(len(roles['flight_tube_shield']['shape']['parts']),3)
        self.assertEqual({m['member_id'] for m in tof if m['electrode_group_id']=='common_ground'},
                         {'accelerator/grounded_shield','flight_tube_shield','reflectron_entry_grid','detector'})
        rings=snapshot['components_resolved']['oatof']['rings']
        expected=rings['accelerator_count']+rings['stage1_count']+rings['stage2_count']+5
        self.assertEqual(len([m for m in tof if m['representation_role']=='physical_solid']),expected)
        shield=roles['accelerator/grounded_shield']['shape']
        self.assertEqual(shield['kind'],'union')
        self.assertEqual(len(shield['parts'][0]['tools']),2)
        mechanical=snapshot['components_resolved']['oatof']['mechanical_side_opening']
        opening=shield['parts'][0]['tools'][1]
        self.assertEqual(opening['size_mm'][1:],[mechanical['width_mm'],mechanical['height_mm']])
        self.assertFalse(any('marker' in m['member_id'] or 'vacuum' in m['member_id'] for m in members))

    def test_existing_renderer_byte_goldens_survive_unique_physical_projection(self):
        from msplatform.backends.simion.accelerator_renderer import render_accelerator_local_geometry
        geometry=dict(axis_x_mm=2.,axis_y_mm=-3.,shield_center_z_mm=4.,shield_outer_width_mm=20.,shield_inner_width_mm=16.,shield_span_z_mm=12.,negative_x_face_mm=-8.,shield_wall_mm=2.,port_center_y_mm=-2.,port_center_z_mm=1.,numerical_port_width_mm=2.8,numerical_port_height_mm=3.,shield_back_z_mm=-2.,repeller_front_z_mm=0.,repeller_thickness_mm=1.,electrode_width_mm=12.,bore_width_mm=4.,ring_thickness_mm=.5,grid1_z_mm=2.,intermediate2_z_mm=6.,grid2_z_mm=10.,ring_count=2,ring_z_mm=[4.,8.])
        electrodes=dict(grounded_shield_id=1,accelerator_repeller_id=2,accelerator_grid1_id=3,accelerator_intermediate2_id=4,accelerator_grid2_id=5,accelerator_ring_ids=[6,7])
        # Square projections remain frozen; cylindrical entrance tools now
        # cross the curved inner wall instead of leaving off-axis metal.
        goldens=[('square', 'whole_accelerator', 'e82d16bfd40e0b4251f9554e122839ec82193d1f5eac0add1a58e4b1ff132241'), ('square', 'entrance', 'c3ec7b2765efbc268368f63e483aca1a70b333419f2d4d645b075884cb31c594'), ('square', 'intermediate2', '2ba572439d4c989990bf34ad8f376421a29228121d00fd0427cb633dfffc6d1f'), ('square', 'directed_corridor', 'c3ec7b2765efbc268368f63e483aca1a70b333419f2d4d645b075884cb31c594'), ('cylindrical', 'whole_accelerator', '182fa302e209221f690c77ad025ef721f531643895b39c59c8118065303aae9f'), ('cylindrical', 'entrance', '9cb3279758b72fbf13e42274718783d369642f8b5f60eced1506ff6fe07bd7db'), ('cylindrical', 'intermediate2', '989a7a945ebc0dc22f7f1bcc8570ee355eaea2874903631c0ea9f2d1bfc319fc'), ('cylindrical', 'directed_corridor', '9cb3279758b72fbf13e42274718783d369642f8b5f60eced1506ff6fe07bd7db')]
        for cross,region,digest in goldens:
            with self.subTest(cross=cross,region=region):
                lines=render_accelerator_local_geometry(dict(geometry,cross_section=cross),cell_x_mm=.2,cell_z_mm=.1,electrodes=electrodes,render_intermediate2_sheet=True,render_region=region)
                self.assertEqual(hashlib.sha256('\n'.join(lines).encode()).hexdigest(),digest)

    def test_missing_instance_unknown_provider_and_wrong_frame_fail(self):
        snapshot=real_snapshot()
        for mutate in ('missing','unknown','frame','nan'):
            changed=copy.deepcopy(snapshot)
            if mutate=='missing': changed['components_resolved'].pop('multipole')
            elif mutate=='unknown': changed['composition_plan']['components']['multipole']['project_id']='unknown'
            elif mutate=='frame': changed['composition_plan']['recipe']['instances'][0]['transform']['from_frame_id']='wrong'
            else: changed['components_resolved']['multipole']['segmentation']['segmented_rod_array']['electrodes'][0]['radius_mm']=float('nan')
            with self.subTest(mutate=mutate),self.assertRaises(ValueError): assembly_geometry_members(changed)

    def test_step_requires_sources_and_rejects_resolved_design_tampering(self):
        snapshot=real_snapshot()
        self.assertEqual(len(assembly_geometry_members(snapshot)),77)
        missing=copy.deepcopy(snapshot);missing.pop('components_source')
        with self.assertRaisesRegex(ValueError,'component sources'):
            assembly_geometry_members(missing)
        changed=copy.deepcopy(snapshot)
        changed['components_resolved']['oatof']['geometry_mm']['detector_radius'] += 5
        with self.assertRaisesRegex(ContractError,'source design documents'):
            assembly_geometry_members(changed)

    def test_explicit_local_scope_retains_parent_but_exports_only_selected_instance(self):
        from msplatform.assembly.resolve_assembly import compile_assembly_layout
        snapshot=real_snapshot();plan=snapshot['composition_plan']
        snapshot['composition_plan']=compile_assembly_layout(plan['recipe'],plan['components'],local_scope=dict(instance_ids=['multipole'],research_scope='RF physical solids only',boundary_assumptions='Explicitly omit downstream TOF solids; retain full parent source'))
        members=assembly_geometry_members(snapshot)
        self.assertEqual({m['instance_id'] for m in members},{'multipole'})
        self.assertEqual(len(members),32)
        snapshot['components_resolved'].pop('oatof')
        with self.assertRaises(ValueError): assembly_geometry_members(snapshot)

    def test_nonsymmetric_landmark_has_one_proper_pose(self):
        transform=RigidTransform('local','world',((0,0,1),(1,0,0),(0,1,0)),(17,-23,41))
        # Independent coordinate substitution, not inverse roundtrip.
        point=transform.transform_position(FramedPosition("local",(2,3,5))).coordinates_mm
        self.assertEqual(tuple(point),(22.,-21.,44.))
        snapshot=real_snapshot();members=assembly_geometry_members(snapshot)
        self.assertEqual({m['instance_id'] for m in members},{'multipole','oatof'})
        self.assertNotEqual(members[0]['transform'],members[-1]['transform'])


def independent_oa_objects():
    """Load the versioned two/three-zone OA study without checkout or placeholders."""
    study = example_api.load_example('oa_two_three_geometric_v1')
    parts = {name: component_api.resolve_component(request)
             for name, request in study.component_requests.items()}
    instrument = assembly_api.assemble(study.recipe, parts)
    snapshot = dict(composition_plan=instrument.composition_plan, components_resolved=instrument.components_resolved,
                    components_source=instrument.components_source)
    return parts, instrument, snapshot


def independent_oa_snapshot():
    return independent_oa_objects()[2]


class IndependentOAProviderTests(unittest.TestCase):
    def test_two_and_three_zone_designs_interfaces_and_members_are_independent(self):
        parts, instrument, snapshot = independent_oa_objects()
        self.assertEqual(set(parts), {'two', 'three'})
        self.assertNotIn('single_reflection_oa_tof', snapshot['components_resolved'])
        self.assertEqual(set(parts['two'].assembly_interface['ports']), {'axial_exit', 'side_entry'})
        self.assertEqual(set(parts['three'].assembly_interface['ports']), {'side_entry'})
        self.assertEqual(parts['two'].assembly_interface['component_electrodes'][1],
                         {'electrode_group_id': 'repeller', 'role': 'repeller'})
        self.assertEqual([row['electrode_group_id'] for row in parts['three'].assembly_interface['component_electrodes'][1:5]],
                         ['repeller', 'intermediate_grid_1', 'intermediate_grid_2', 'exit_grid'])
        self.assertEqual(instrument.composition_plan['schema_version'], 5)
        members = assembly_geometry_members(snapshot)
        self.assertEqual(len(members), 30)
        self.assertEqual(len([m for m in members if m['representation_role'] == 'physical_solid']), 25)
        self.assertEqual(len([m for m in members if m['representation_role'] == 'ideal_surface']), 5)
        self.assertEqual({m['local_frame_id'] for m in members},
                         {'orthogonal_accelerator_exit_origin_v1', 'sectioned_accelerator_cartesian'})
        shield = next(m for m in members if m['instance_id'] == 'two' and m['member_id'] == 'grounded_shield')
        self.assertIn('/local_exit_z_mm', shield['source_refs'])

    def test_local_scope_retains_complete_oa_parent_and_inputs_remain_independent(self):
        parts, instrument, snapshot = independent_oa_objects()
        before = copy.deepcopy(snapshot)
        local = assembly_api.assemble(instrument.composition_plan['recipe'], parts,
            local_scope=dict(instance_ids=['three'], research_scope='three-zone OA only',
                             boundary_assumptions='Explicit local CAD scope; retain full parent'))
        selected = dict(composition_plan=local.composition_plan, components_resolved=local.components_resolved,
                        components_source=local.components_source)
        members = assembly_geometry_members(selected)
        self.assertEqual({m['instance_id'] for m in members}, {'three'})
        self.assertEqual(len(members), 9)
        self.assertEqual(set(local.composition_plan['components']), {'two', 'three'})
        self.assertEqual(snapshot, before)
        changed = parts['two'].resolved_design
        changed['enclosure'].clear()
        self.assertNotEqual(parts['two'].resolved_design, changed)

    def test_two_zone_persisted_assembly_roundtrip_preserves_physics_and_rejects_tampering(self):
        import json
        import tempfile
        from dataclasses import asdict
        from pathlib import Path
        from msplatform.components.orthogonal_accelerator.two_zone_geometry import resolve_closed_two_zone_geometry

        parts, instrument, snapshot = independent_oa_objects()
        before = assembly_geometry_members(snapshot)
        source = parts['two'].source_design
        profile = parts['two'].assembly_interface['geometry_profile_id']
        legacy = asdict(resolve_closed_two_zone_geometry(source['requirements'],
            geometry_profile_id=profile, geometry_profile=source['geometry_profile']))
        legacy.update(schema_version=1, role='orthogonal_accelerator_two_zone_geometry',
                      variant_id='two_zone', geometry_profile_id=profile)
        encode = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        self.assertEqual(encode(legacy), encode(parts['two'].resolved_design))
        self.assertIsInstance(parts['two'].resolved_design['grid_supports'], list)
        self.assertIsInstance(parts['two'].resolved_design['rings'], list)
        payload = dict(recipe=instrument.composition_plan['recipe'], components={name:dict(
            provider_id=item.provider_id, resolved_design=item.resolved_design,
            assembly_interface=item.assembly_interface, source_design=item.source_design)
            for name,item in parts.items()})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'assembly.json'
            path.write_bytes(encode(payload))
            restored = json.loads(path.read_bytes())
        decoded = {name:component_api.ResolvedComponent(value['provider_id'], value['resolved_design'],
            value['assembly_interface'], source_design=value['source_design'])
            for name,value in restored['components'].items()}
        rebuilt = assembly_api.assemble(restored['recipe'], decoded)
        actual = dict(composition_plan=rebuilt.composition_plan, components_resolved=rebuilt.components_resolved,
                      components_source=rebuilt.components_source)
        self.assertEqual(actual, snapshot)
        self.assertEqual(assembly_geometry_members(actual), before)
        with tempfile.TemporaryDirectory() as directory:
            snapshot_path = Path(directory) / 'export_snapshot.json'
            snapshot_path.write_bytes(encode(snapshot))
            persisted_snapshot = json.loads(snapshot_path.read_bytes())
        self.assertEqual(assembly_geometry_members(persisted_snapshot), before)
        self.assertEqual(actual['composition_plan']['components']['two']['ports'],
                         snapshot['composition_plan']['components']['two']['ports'])
        self.assertEqual(actual['composition_plan']['components']['two']['component_electrodes'],
                         snapshot['composition_plan']['components']['two']['component_electrodes'])
        for family in ('grid_supports','rings'):
            changed = copy.deepcopy(restored['components'])
            field = 'grid_z_mm' if family == 'grid_supports' else 'center_z_mm'
            changed['two']['resolved_design'][family][0][field] += 0.125
            tampered = {name:component_api.ResolvedComponent(value['provider_id'], value['resolved_design'],
                value['assembly_interface'], source_design=value['source_design']) for name,value in changed.items()}
            with self.subTest(family=family), self.assertRaises(ValueError):
                assembly_api.assemble(restored['recipe'], tampered)

    def test_oa_source_and_interface_mismatch_fail_at_public_boundaries(self):
        parts, instrument, _ = independent_oa_objects()
        request = {'provider_id': 'orthogonal_accelerator', 'geometry_profile_id': 'closed_two_zone_compact_mr_axial_r3_gap1_4mm',
                   'design': {'requirements': parts['two'].source_design['requirements']}}
        with self.assertRaisesRegex(ValueError, 'geometry_profile content'):
            component_api.resolve_component(request)
        interface = parts['three'].assembly_interface
        interface['ports']['side_entry']['center_mm'][1] += 1
        direct = component_api.ResolvedComponent('orthogonal_accelerator', parts['three'].resolved_design, interface,
                                                 source_design=parts['three'].source_design)
        with self.assertRaisesRegex(ContractError, 'interface differs'):
            assembly_api.assemble(instrument.composition_plan['recipe'], {'two': parts['two'], 'three': direct})
        invalid_design = parts['three'].resolved_design
        invalid_design['geometry']['ring_thickness_mm'] = 10.0
        invalid_component = component_api.ResolvedComponent('orthogonal_accelerator', invalid_design,
            parts['three'].assembly_interface, source_design=parts['three'].source_design)
        with self.assertRaises(ValueError):
            assembly_api.Assembly(instrument.composition_plan,
                                  {'two': parts['two'], 'three': invalid_component})
        from msplatform.components.orthogonal_accelerator.assembly_interface import resolve_assembly_interface
        for kwargs in ({'geometry_profile_id': 'unconsumed'},
                       {'geometry_profile_id': None, 'geometry_profile': {}}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, 'not a geometric input'):
                resolve_assembly_interface(parts['three'].source_design['requirements'], **kwargs)


if __name__=='__main__': unittest.main()
