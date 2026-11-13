"""IP COMSOL physical projection only; no native solver qualification."""
import copy
import unittest

from common.contracts.test_ip_step_projection import snapshot
from integrations.tests import test_ip_compiler as fixtures
from projects.dual_pressure_rectilinear_ion_processor.tests import test_electrode_contours as contours
from msplatform.assembly.factory import assemble
from msplatform.components.catalog import resolve_component
from msplatform.components.geometry_members import assembly_geometry_members
from msplatform.backends.comsol.assembly_geometry import project_assembly_geometry
from msplatform.backends.comsol.ip_prism import certify_ip_prism


class IpComsolProjectionTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.IpCompilerTests(); fixture.setUp(); self.assembly = fixture.assembly
        self.box = {'min':[-10000]*3, 'max':[10000]*3}

    def check(self, assembly):
        data = snapshot(assembly); before = copy.deepcopy(data)
        projected = project_assembly_geometry(data, outer_box_mm=self.box)
        self.assertEqual(data, before)
        self.assertEqual(projected['members'], list(assembly_geometry_members(data)))
        ip = [m for m in projected['members'] if m['instance_id'] == 'ion_processor']
        self.assertEqual(len(ip), 15)
        self.assertEqual(len({m['electrode_group_id'] for m in ip}), 15)
        self.assertEqual(len(projected['native_shapes']), len(projected['members']))
        def check_shape(source, native):
            kind=source['kind']
            if kind=='difference':
                self.assertEqual(native['kind'],kind)
                check_shape(source['base'],native['base'])
                self.assertEqual(len(source['tools']),len(native['tools']))
                for left,right in zip(source['tools'],native['tools'],strict=True): check_shape(left,right)
            elif kind=='union':
                self.assertEqual(native['kind'],kind)
                self.assertEqual(len(source['parts']),len(native['parts']))
                for left,right in zip(source['parts'],native['parts'],strict=True): check_shape(left,right)
            elif kind=='ip_convex_polyhedron':
                self.assertEqual(native['kind'],'ip_certified_prism')
                self.assertLessEqual(native['reconstruction_residual_mm'],native['arithmetic_bound_mm'])
            else:
                self.assertEqual(native,source)
        for member,native in zip(projected['members'],projected['native_shapes'],strict=True):
            check_shape(member['shape'],native)
        return projected

    def test_public_request_retains_complete_rf_ip_assembly(self):
        from msplatform.backends.comsol.geometry_execution import resolve_geometry_request
        before = snapshot(self.assembly)
        expected = list(assembly_geometry_members(before))
        result = resolve_geometry_request(self.assembly, outer_box_mm=self.box,
            geometry_validation={'position_mm': 1e-6, 'normal_abs': 1e-9})
        self.assertEqual(result['assembly'], before)
        self.assertEqual(result['projection']['members'], expected)
        self.assertEqual({m['instance_id'] for m in expected}, {'multipole', 'ion_processor'})
        self.assertEqual(len([m for m in expected if m['instance_id'] == 'ion_processor']), 15)
        expected_groups = {(m['instance_id'], m['electrode_group_id']) for m in expected}
        self.assertEqual({(g['instance_id'], g['electrode_group_id']) for g in result['projection']['electrode_groups']}, expected_groups)
        self.assertEqual(len(result['projection']['native_shapes']), len(expected))
        self.assertEqual(snapshot(self.assembly), before)

    def test_synthetic_mixed_dispatch_preserves_real_mr_and_ideal_members(self):
        """Exercise backend dispatch only, without claiming an IP–MR layout."""
        from pathlib import Path
        from unittest.mock import patch
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_mr_provider_trial_transport import _plans
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.test_support.mr_geometry_inputs import geometry_authority
        _, plan, contract = _plans()
        authority = geometry_authority(contract)
        oa = resolve_component({'provider_id': 'orthogonal_accelerator',
            'design': {'requirements': authority['accelerator_requirements'], 'geometry_profile': authority['geometry_profile']},
            'geometry_profile_id': authority['geometry_profile_id']})
        mr = resolve_component({'provider_id': 'parallel_mirror_dual_stripe_mr_tof',
            'design': {'contract': contract, 'accelerator_requirements': authority['accelerator_requirements'],
                       'geometry_profile': authority['geometry_profile']},
            'geometry_profile_id': authority['geometry_profile_id']})
        downstream = assemble(plan['recipe'], {name: (oa if row['project_id'] == 'orthogonal_accelerator' else mr)
                                              for name, row in plan['components'].items()})
        upstream_members = list(assembly_geometry_members(snapshot(self.assembly)))
        downstream_members = list(assembly_geometry_members(snapshot(downstream)))
        mixed = upstream_members + downstream_members
        before = copy.deepcopy(mixed)
        with patch('msplatform.backends.comsol.assembly_geometry.assembly_geometry_members', return_value=mixed):
            result = project_assembly_geometry({'composition_plan': {'assembly_frame_id': 'synthetic-dispatch-only'}},
                                               outer_box_mm=self.box)
        self.assertEqual(mixed, before)
        self.assertEqual(result['members'], before)
        self.assertEqual(len(result['native_shapes']), len(before))
        groups = {(m['instance_id'], m['electrode_group_id']) for m in before}
        actual = {(g['instance_id'], g['electrode_group_id']) for g in result['electrode_groups']}
        self.assertEqual(actual, groups)
        self.assertEqual(sum(len(g['member_ids']) for g in result['electrode_groups']), len(before))
        mr_ids = {name for name, row in plan['components'].items()
                  if row['project_id'] == 'parallel_mirror_dual_stripe_mr_tof'}
        indices = [i for i, member in enumerate(before) if member['instance_id'] in mr_ids]
        self.assertTrue(indices)
        self.assertTrue(any('extruded_yz_polygon' in repr(before[i]['shape']) for i in indices))
        self.assertTrue(any(before[i]['shape']['kind'] in {'union', 'difference'} for i in indices))
        for i in indices:
            self.assertEqual(result['native_shapes'][i], before[i]['shape'])
        ideal = [i for i, member in enumerate(before) if member['representation_role'] == 'ideal_surface']
        self.assertTrue(ideal)
        for i in ideal:
            self.assertEqual(result['native_shapes'][i], before[i]['shape'])
        builder = Path(__file__).resolve().parents[2] / 'src/msplatform/backends/comsol/matlab/build_assembly_reference_geometry.m'
        self.assertIn("tag=emitSheet(member.shape,R,T);", builder.read_text(encoding='utf-8'))

    def test_complete_actual_base_and_formed_contours(self):
        self.check(self.assembly)
        for mode in ('formed_extraction', 'formed_extraction_continuous_aux',
                     'formed_extraction_continuous_aux_parabolic_inner'):
            for variation in (False, True):
                fixture = contours.ElectrodeContourTests(); fixture.setUp()
                fixture.c['mode'] = mode
                if variation:
                    fixture.b['geometry']['r0_mm'] += .2
                    fixture.c['nose_halfwidth_mm'] = .9
                if mode.endswith('parabolic_inner'): fixture.c['inner_parabola_sag_mm'] = .1
                fixture.b['physical_design_selection'] = {'native_grid_mm':.1, 'native_aux_segments':60}
                ip = resolve_component(dict(provider_id='dual_pressure_rectilinear_ion_processor',
                                            design=dict(baseline=fixture.b)))
                a = assemble(self.assembly.composition_plan['recipe'], dict(self.assembly.components, ion_processor=ip))
                with self.subTest(mode=mode, perturbed=variation):
                    value = self.check(a)
                    self.assertIn('ip_certified_prism', repr(value['native_shapes']))

    def test_perturbed_design_and_two_instance_poses_preserve_source(self):
        baseline = copy.deepcopy(self.assembly.components_source['ion_processor']['baseline'])
        baseline['geometry']['r0_mm'] += .2
        ip = resolve_component(dict(provider_id='dual_pressure_rectilinear_ion_processor',
                                    design=dict(baseline=baseline)))
        recipe = copy.deepcopy(self.assembly.composition_plan['recipe'])
        row = copy.deepcopy(next(r for r in recipe['instances'] if r['instance_id']=='ion_processor'))
        row['instance_id']='ion_processor_2'; row['transform']['translation_mm'][0] += 500
        row['transform']['rotation']=[[0,-1,0],[1,0,0],[0,0,1]]
        recipe['instances'].append(row)
        combined = assemble(recipe,dict(self.assembly.components,ion_processor=ip,ion_processor_2=ip))
        value = self.check(combined)
        first=[m for m in value['members'] if m['instance_id']=='ion_processor']
        second=[m for m in value['members'] if m['instance_id']=='ion_processor_2']
        self.assertEqual(len(second),15)
        self.assertEqual([m['shape'] for m in first],[m['shape'] for m in second])
        self.assertNotEqual(first[0]['transform'],second[0]['transform'])
        original=[m for m in assembly_geometry_members(snapshot(self.assembly)) if m['instance_id']=='ion_processor']
        self.assertNotEqual([m['shape'] for m in first],[m['shape'] for m in original])

    def test_skewed_prism_uses_pose_once_and_records_residual(self):
        vertices=[[x,y+x,z] for x in (0,2) for y,z in ((0,0),(1,0),(0,1))]
        pose=dict(rotation=[[0,-1,0],[1,0,0],[0,0,1]],translation_mm=[11,17,23])
        result=certify_ip_prism(dict(kind='ip_convex_polyhedron',vertices_mm=vertices),pose)
        self.assertLessEqual(result['reconstruction_residual_mm'],result['arithmetic_bound_mm'])
        self.assertEqual(result['plane'],'zx')
        self.assertEqual(result['offset_mm'],17)
        self.assertEqual(result['distance_mm'],2)
        self.assertEqual(result['displacement_mm'],[0,-2])

    def test_extrude_selects_its_parent_workplane(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[2]
        text=(root/'src/msplatform/backends/comsol/matlab/build_assembly_reference_geometry.m').read_text(encoding='utf-8')
        self.assertIn("geom.feature(tag).set('workplane',wp);",text)
        self.assertIn("geom.feature(tag).selection('input').set({wp});",text)
        self.assertNotIn("geom.feature(tag).selection('input').set({'section'});",text)

    def test_valid_nonprism_uses_original_vertex_tetrahedron(self):
        shape = dict(kind='ip_convex_polyhedron', vertices_mm=[[0,0,0],[1,0,0],[0,1,0],[0,0,1]])
        pose = dict(rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[0,0,0])
        result=certify_ip_prism(shape, pose)
        self.assertEqual(result['kind'],'ip_certified_tetra_union')
        self.assertEqual(len(result['tetrahedra']),1)
        self.assertEqual({tuple(v) for v in result['tetrahedra'][0]}, {tuple(v) for v in shape['vertices_mm']})

    def test_deformed_hull_tetrahedra_preserve_actual_source_vertices(self):
        vertices=[[x,y,z] for x in (0.,1.) for y in (0.,1.) for z in (0.,1.)]
        vertices[-1][0]=1.125
        pose = dict(rotation=[[0,-1,0],[1,0,0],[0,0,1]],translation_mm=[11,17,23])
        result=certify_ip_prism(dict(kind='ip_convex_polyhedron',vertices_mm=vertices),pose)
        self.assertEqual(result['kind'],'ip_certified_tetra_union')
        self.assertEqual(result['source_vertex_count'],8)
        used={tuple(v) for tetra in result['tetrahedra'] for v in tetra}
        self.assertIn((1.125,1.,1.),used)
        self.assertTrue(used.issubset({tuple(v) for v in vertices}))
        self.assertGreater(len(result['tetrahedra']),1)

    def test_independent_sub_bound_endpoint_deformation_never_becomes_prism(self):
        vertices=[[x,y,z] for x in (0.,1.) for y in (0.,1.) for z in (0.,1.)]
        vertices[-1][1] += 1e-14
        pose = dict(rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[0,0,0])
        try:
            result=certify_ip_prism(dict(kind='ip_convex_polyhedron',vertices_mm=vertices),pose)
        except ValueError as error:
            self.assertIn('exact supporting plane',str(error))
        else:
            self.assertEqual(result['kind'],'ip_certified_tetra_union')
            self.assertIn(tuple(vertices[-1]), {tuple(v) for tetra in result['tetrahedra'] for v in tetra})

    def test_tiny_source_deformation_is_not_certified_as_prism(self):
        import math
        vertices=[[x,y,z] for x in (0.,1.) for y in (0.,1.) for z in (0.,1.)]
        vertices[-1][0]=math.nextafter(1.,2.)
        pose = dict(rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[0,0,0])
        try:
            result=certify_ip_prism(dict(kind='ip_convex_polyhedron',vertices_mm=vertices),pose)
        except ValueError as error:
            self.assertIn('exact supporting plane',str(error))
        else:
            self.assertEqual(result['kind'],'ip_certified_tetra_union')

    def test_pose_that_collapses_distinct_vertices_refuses(self):
        vertices=[[x,y,z] for x in (0.,1.) for y in (0.,1.) for z in (0.,1.)]
        pose=dict(rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[1e18,0,0])
        with self.assertRaisesRegex(ValueError,'transformed source vertices collapse'):
            certify_ip_prism(dict(kind='ip_convex_polyhedron',vertices_mm=vertices),pose)

    def test_resolved_source_tamper_refuses(self):
        data = snapshot(self.assembly)
        data['components_resolved']['ion_processor']['projection']['electrodes'][4]['cutouts'][0]['min_mm'][1] += .1
        with self.assertRaises(ValueError): project_assembly_geometry(data, outer_box_mm=self.box)
