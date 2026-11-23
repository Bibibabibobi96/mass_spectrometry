"""Bounded optional-CAD pair and equal-static contact contracts."""
import copy
import importlib.util
import unittest
from unittest.mock import patch

from msplatform.backends.simion import assembly_geometry, model, generic_scalar_binding, rf_field_execution
from msplatform.components import cad_geometry


def member(shape, translation=(0, 0, 0)):
    return dict(shape=shape, transform=dict(schema_version=1, role='rigid_transform',
        from_frame_id='local', to_frame_id='world', rotation=[[1,0,0],[0,1,0],[0,0,1]],
        translation_mm=list(translation)))


def polygon(y0, y1):
    return dict(kind='extruded_yz_polygon', x=[-2,2],
                polygon_yz_mm=[[y0,0],[y1,0],[y1,2],[y0,2]])


class ContactGeometryTests(unittest.TestCase):
    def test_canonical_edge_and_serialized_edge_require_separation(self):
        a=member(polygon(0,2));b=member(polygon(2,4))
        self.assertTrue(assembly_geometry._polygon_contact_proof(a,b))
        overlapping=member(polygon(1,4))
        self.assertFalse(assembly_geometry._polygon_contact_proof(a,overlapping))
        shifted=member(polygon(2,4),translation=(0,1,0))
        self.assertFalse(assembly_geometry._polygon_contact_proof(a,shifted))
        cut=copy.deepcopy(b)
        cut['shape']=dict(kind='difference',base=cut['shape'],tools=[polygon(1,3)])
        self.assertFalse(assembly_geometry._polygon_contact_proof(a,cut))

    def test_exact_equal_static_required(self):
        contacts=[dict(first=dict(instance_id='a',electrode_group_id='x'),
                       second=dict(instance_id='b',electrode_group_id='y'))]
        groups={'a':{'x':dict(kind='static',voltage_v=0.)},'b':{'y':dict(kind='static',voltage_v=0.)}}
        model._validate_static_contacts(contacts,groups)
        for bad in (dict(kind='static',voltage_v=1.),dict(kind='rf',voltage_v=0.)):
            changed=copy.deepcopy(groups);changed['b']['y']=bad
            with self.subTest(bad=bad),self.assertRaisesRegex(ValueError,'equal static'):
                model._validate_static_contacts(contacts,changed)

    def test_existing_primitive_serialized_bounds_on_all_axes(self):
        from msplatform.contracts.rigid_transform import RigidTransform
        rotations=(((1,0,0),(0,1,0),(0,0,1)),((0,0,1),(0,1,0),(-1,0,0)),((1,0,0),(0,0,1),(0,-1,0)))
        shapes=(dict(kind='box',center_mm=[0,0,0],size_mm=[2,4,6]),
                dict(kind='cylinder',center_mm=[0,0,0],radius_mm=1,height_mm=4),
                dict(kind='ip_cylinder_x',x_min_mm=-2,x_max_mm=2,center_y_mm=0,center_z_mm=0,radius_mm=1))
        for rotation in rotations:
            transform=RigidTransform('local','world',rotation,(0,0,0))
            for shape in shapes:
                with self.subTest(rotation=rotation,kind=shape['kind']):
                    primitive,lo,hi=assembly_geometry._world_primitive(shape,transform,[])
                    actual_lo,actual_hi=assembly_geometry._serialized_primitive_bounds(primitive)
                    self.assertTrue(all(actual_lo[i]<=lo[i] and actual_hi[i]>=hi[i] for i in range(3)))
        with self.assertRaisesRegex(ValueError,'unsupported serialized'):
            assembly_geometry._serialized_primitive_bounds('unknown(1,2,3)')

    def test_serialized_domain_containment_uses_exact_bounds(self):
        row=member(dict(kind='box',center_mm=[8.999999999999,0,0],size_mm=[2,2,2]))
        row.update(instance_id='a',electrode_group_id='metal',member_id='body',
                   representation_role='physical_solid',source_refs=[])
        snapshot=dict(composition_plan=dict(recipe=dict(assembly_frame_id='world')))
        domain=dict(frame_id='world',minimum_mm=[-10,-10,-10],maximum_mm=[10,10,10])
        with self.assertRaisesRegex(ValueError,'serialized GEM physical member'):
            assembly_geometry._render_assembly_members_gem(snapshot,[row],domain=domain,pitch_mm=1,boundary='native_zero_neumann')
        row['shape']['center_mm'][0]=8.
        assembly_geometry._render_assembly_members_gem(snapshot,[row],domain=domain,pitch_mm=1,boundary='native_zero_neumann')
        exact_lo,exact_hi=assembly_geometry._serialized_primitive_bounds('centered_box3D(0,0,0,2,2,2)',exact=True)
        from fractions import Fraction
        self.assertEqual((exact_lo[0],exact_hi[0]),(Fraction(-1),Fraction(1)))

    def test_nonoverlap_needs_no_optional_cad(self):
        rows=[]
        for name, x in (('left', -3), ('right', 3)):
            row=member(dict(kind='box',center_mm=[x,0,0],size_mm=[2,2,2]))
            row.update(instance_id=name,electrode_group_id='metal',member_id='body',
                       representation_role='physical_solid',source_refs=[])
            rows.append(row)
        snapshot=dict(composition_plan=dict(recipe=dict(assembly_frame_id='world')))
        with patch.object(cad_geometry,'placed_physical_solid',side_effect=AssertionError('unexpected CAD')):
            rendered=assembly_geometry._render_assembly_members_gem(snapshot,rows,
                domain=dict(frame_id='world',minimum_mm=[-10,-10,-10],maximum_mm=[10,10,10]),
                pitch_mm=1,boundary='native_zero_neumann')
        self.assertEqual(len(rendered['electrode_mapping']),2)
        self.assertNotIn('contact_obligations',rendered)

    def test_every_sample_workpoint_must_respect_contacts(self):
        contacts=[dict(first=dict(instance_id='a',electrode_group_id='x'),
                       second=dict(instance_id='b',electrode_group_id='y'))]
        def row(x,y):
            return dict(request=dict(group_voltages=[dict(instance_id='a',electrode_group_id='x',voltage_v=x),
                                                    dict(instance_id='b',electrode_group_id='y',voltage_v=y)]))
        generic_scalar_binding._validate_contact_sample_workpoints(contacts,{'first':row(0.,0.),'second':row(3.,3.)})
        with self.assertRaisesRegex(ValueError,'equal-potential'):
            generic_scalar_binding._validate_contact_sample_workpoints(contacts,{'valid':row(0.,0.),'invalid':row(1.,0.)})
        with self.assertRaisesRegex(ValueError,'equal-potential'):
            generic_scalar_binding._validate_contact_sample_workpoints(contacts,{'missing':dict(request=dict(group_voltages=[]))})

    def test_independent_unit_family_and_reuse_refuse_contact(self):
        from types import SimpleNamespace
        geometry=dict(role='simion_neutral_world_collision_geometry',contact_obligations=[{'first':{},'second':{}}])
        with patch.object(rf_field_execution,'model_geometry',return_value=SimpleNamespace(frontend_geometry=geometry)), \
             patch.object(rf_field_execution,'_field_contract'), \
             patch.object(rf_field_execution,'require_prepared_model',return_value={'physics':rf_field_execution.RF_PHYSICS}):
            for reuse in (None,{'manifest':'existing'}):
                with self.subTest(reuse=reuse),self.assertRaisesRegex(ValueError,'independent electrode field family'):
                    rf_field_execution.plan_rf_fields(object(),numerics={'refine_policy':'vendor_default'},reuse_fields_reference=reuse)

    def test_optional_cad_missing_is_explicit(self):
        real_import=__import__
        def deny(name,*args,**kwargs):
            if name=='cadquery':raise ImportError('controlled missing dependency')
            return real_import(name,*args,**kwargs)
        with patch('builtins.__import__',side_effect=deny),self.assertRaisesRegex(RuntimeError,'optional cad-step'):
            cad_geometry.placed_physical_solid(member(polygon(0,2)))

    @unittest.skipUnless(importlib.util.find_spec('cadquery'), 'optional cad-step unavailable')
    def test_source_gap_rounded_into_contact_is_not_fast_pathed(self):
        for case,left,right,width in (('contact',0.,2.000000000001,2.),
                                      ('overlap',1.0000000000051,3.000000000011,2.0000000000051)):
            rows=[]
            for name,x in (('left',left),('right',right)):
                row=member(dict(kind='box',center_mm=[x,0,0],size_mm=[width,2,2]))
                row.update(instance_id=name,electrode_group_id='metal',member_id='body',
                           representation_role='physical_solid',source_refs=[])
                rows.append(row)
            with self.subTest(case=case),self.assertRaisesRegex(ValueError,'ambiguous'):
                assembly_geometry._render_assembly_members_gem(
                    dict(composition_plan=dict(recipe=dict(assembly_frame_id='world'))),rows,
                    domain=dict(frame_id='world',minimum_mm=[-10,-10,-10],maximum_mm=[10,10,10]),
                    pitch_mm=1,boundary='native_zero_neumann')

    @unittest.skipUnless(importlib.util.find_spec('cadquery'), 'optional cad-step unavailable')
    def test_serialized_existing_primitive_solids_preserve_axes_and_pose(self):
        rotations=(((1,0,0),(0,1,0),(0,0,1)),((0,0,1),(0,1,0),(-1,0,0)),((1,0,0),(0,0,1),(0,-1,0)))
        shapes=(dict(kind='box',center_mm=[1,2,3],size_mm=[2,4,6]),
                dict(kind='ip_box',min_mm=[-1,-2,-3],max_mm=[1,2,3]),
                dict(kind='cylinder',center_mm=[1,2,3],radius_mm=1,height_mm=4),
                dict(kind='ip_cylinder_x',x_min_mm=-2,x_max_mm=2,center_y_mm=1,center_z_mm=2,radius_mm=1),
                dict(kind='rod',center_xy_mm=[1,2],z_min_mm=-2,z_max_mm=2,radius_mm=1))
        for rotation in rotations:
            for shape in shapes:
                with self.subTest(rotation=rotation,kind=shape['kind']):
                    row=member(shape,translation=(3,4,5));row['transform']['rotation']=[list(x) for x in rotation]
                    original=cad_geometry.placed_physical_solid(row)
                    represented=assembly_geometry._serialized_member_solid(row)
                    self.assertAlmostEqual(original.Volume(),represented.Volume(),places=8)
                    a,b=original.BoundingBox(),represented.BoundingBox()
                    for key in ('xmin','xmax','ymin','ymax','zmin','zmax'):
                        self.assertAlmostEqual(getattr(a,key),getattr(b,key),places=8)

    @unittest.skipUnless(importlib.util.find_spec('cadquery'), 'optional cad-step unavailable')
    def test_renderer_records_contact_without_merging_groups(self):
        rows=[]
        for name, shape in (('left',polygon(0,2)),('right',polygon(2,4))):
            row=member(shape);row.update(instance_id=name,electrode_group_id='metal',member_id='body',
                                         representation_role='physical_solid',source_refs=[])
            rows.append(row)
        rendered=assembly_geometry._render_assembly_members_gem(
            dict(composition_plan=dict(recipe=dict(assembly_frame_id='world'))),rows,
            domain=dict(frame_id='world',minimum_mm=[-10,-10,-10],maximum_mm=[10,10,10]),
            pitch_mm=1,boundary='native_zero_neumann')
        self.assertEqual(len(rendered['electrode_mapping']),2)
        self.assertEqual(rendered['contact_obligations'],[dict(first=dict(instance_id='left',electrode_group_id='metal'),
                                                               second=dict(instance_id='right',electrode_group_id='metal'))])

    @unittest.skipUnless(importlib.util.find_spec('cadquery'), 'optional cad-step unavailable')
    def test_full_csg_rejects_overlap_and_uncertainty(self):
        a=cad_geometry.placed_physical_solid(member(polygon(0,2)))
        b=cad_geometry.placed_physical_solid(member(polygon(2,4)))
        self.assertEqual(cad_geometry.classify_solid_pair(a,b,proven_contact=True),'contact')
        with self.assertRaisesRegex(ValueError,'topology is unproved'):
            cad_geometry.classify_solid_pair(a,b)
        with self.assertRaisesRegex(ValueError,'overlap'):
            cad_geometry.classify_solid_pair(a,cad_geometry.placed_physical_solid(member(polygon(1,4))))
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            cad_geometry.classify_solid_pair(a,cad_geometry.placed_physical_solid(member(polygon(2.0000005,4))))


    @unittest.skipUnless(importlib.util.find_spec('cadquery'), 'optional cad-step unavailable')
    def test_selected_canonical_mr_pair_relations(self):
        import json
        from pathlib import Path
        from msplatform.assembly.factory import assemble
        from msplatform.components.catalog import resolve_component
        from msplatform.components.geometry_members import assembly_geometry_members
        root=Path(__file__).resolve().parents[2]
        fixture=json.loads((root/'tests/contracts/test_support/ip_mr_lp60_requests.json').read_text(encoding='utf8'))
        assembly=assemble(fixture['recipe'],{k:resolve_component(v) for k,v in fixture['component_requests'].items()})
        snapshot=dict(composition_plan=assembly.composition_plan,components_resolved=assembly.components_resolved,
                      components_source=assembly.components_source)
        members={m['member_id']:m for m in assembly_geometry_members(snapshot) if m['instance_id']=='mrtof'}
        pairs=[('central_ground_electrodes','prism_ground_shields/1'),('central_ground_electrodes','stripe_electrodes/2'),
               ('central_ground_electrodes','stripe_electrodes/3'),('mirror_electrodes/0','mirror_ground_shields/0'),
               ('mirror_electrodes/1','mirror_ground_shields/1'),('prism_electrodes/0','prism_ground_shields/0'),
               ('prism_electrodes/1','prism_ground_shields/1'),('prism_ground_shields/1','stripe_electrodes/0'),
               ('prism_ground_shields/1','stripe_electrodes/1'),('prism_ground_shields/1','stripe_electrodes/2'),
               ('prism_ground_shields/1','stripe_electrodes/3'),('stripe_electrodes/0','stripe_electrodes/2'),
               ('stripe_electrodes/1','stripe_electrodes/3')]
        contacts={('mirror_electrodes/0','mirror_ground_shields/0'),('mirror_electrodes/1','mirror_ground_shields/1')}
        original={};serialized={}
        for left,right in pairs:
            with self.subTest(left=left,right=right):
                a,b=members[left],members[right]
                for name,row in ((left,a),(right,b)):
                    if name not in original:original[name]=cad_geometry.placed_physical_solid(row)
                proof=assembly_geometry._polygon_contact_proof(a,b)
                expected='contact' if (left,right) in contacts else 'separated'
                self.assertEqual(cad_geometry.classify_solid_pair(original[left],original[right],proven_contact=proof),expected)
                if expected=='contact':self.assertTrue(proof)
                else:
                    for name,row in ((left,a),(right,b)):
                        if name not in serialized:
                            serialized[name]=assembly_geometry._serialized_member_solid(row)
                    self.assertEqual(cad_geometry.classify_solid_pair(serialized[left],serialized[right]),'separated')
