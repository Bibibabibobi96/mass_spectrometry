"""Independent coverage and shape facts for the real complete Assembly."""
import copy
import unittest
import hashlib

from msplatform import api
from msplatform.exporters.step import assembly_geometry_members
from msplatform.contracts.rigid_transform import RigidTransform, FramedPosition


def real_snapshot():
    case=api.load_example('rf_oatof_functional_v1')
    parts={name:api.resolve_component(req) for name,req in case.component_requests.items()}
    assembly=api.compile_assembly(case.recipe,parts)
    return dict(composition_plan=assembly.composition_plan,components_resolved=assembly.components_resolved)


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
        # Frozen from the original Git-owned sectioned_accelerator implementation.
        goldens=[('square', 'whole_accelerator', 'e82d16bfd40e0b4251f9554e122839ec82193d1f5eac0add1a58e4b1ff132241'), ('square', 'entrance', 'c3ec7b2765efbc268368f63e483aca1a70b333419f2d4d645b075884cb31c594'), ('square', 'intermediate2', '2ba572439d4c989990bf34ad8f376421a29228121d00fd0427cb633dfffc6d1f'), ('square', 'directed_corridor', 'c3ec7b2765efbc268368f63e483aca1a70b333419f2d4d645b075884cb31c594'), ('cylindrical', 'whole_accelerator', '240af4000bb05021cf53d2a2f5f5d1c61697991fd76a20557805c1e93ac92741'), ('cylindrical', 'entrance', '48714984a568d6b99b4384ea1b595e22667de67d73fb975a671f732e3e82efd6'), ('cylindrical', 'intermediate2', '989a7a945ebc0dc22f7f1bcc8570ee355eaea2874903631c0ea9f2d1bfc319fc'), ('cylindrical', 'directed_corridor', '48714984a568d6b99b4384ea1b595e22667de67d73fb975a671f732e3e82efd6')]
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


if __name__=='__main__': unittest.main()
