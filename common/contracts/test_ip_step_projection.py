"""Canonical IP STEP planning: pure source identity, not a CAD qualification."""
from msplatform.components.geometry_members import assembly_geometry_members
import copy
import unittest
from integrations.tests import test_ip_compiler as fixtures
from projects.dual_pressure_rectilinear_ion_processor.tests import test_electrode_contours as contours
from msplatform.assembly.factory import assemble
from msplatform.components.catalog import resolve_component
from msplatform.exporters import step


def snapshot(assembly):
    return dict(composition_plan=assembly.composition_plan, components_resolved=assembly.components_resolved,
                components_source=assembly.components_source)


def original(shape):
    return dict(shape=shape['kind'][3:], **{k:copy.deepcopy(v) for k,v in shape.items() if k!='kind'})


class IpStepProjectionTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.IpCompilerTests(); fixture.setUp(); self.assembly=fixture.assembly

    def check_source(self, assembly, instance):
        data=snapshot(assembly); before=copy.deepcopy(data)
        members=assembly_geometry_members(data)
        selected=[m for m in members if m['instance_id']==instance]
        electrodes=data['components_resolved'][instance]['projection']['electrodes']
        self.assertEqual(len(selected),15)
        self.assertEqual([m['electrode_group_id'] for m in selected],[e['name'] for e in electrodes])
        pose=next(r['transform'] for r in data['composition_plan']['recipe']['instances'] if r['instance_id']==instance)
        for index,(member,electrode) in enumerate(zip(selected,electrodes,strict=True)):
            self.assertEqual(member['transform'],pose)
            self.assertEqual(member['source_refs'],[f'/projection/electrodes/{index}'])
            shape=member['shape']; base=shape['base'] if electrode['cutouts'] else shape
            parts=base['parts'] if len(electrode['solids'])>1 else [base]
            self.assertEqual([original(p) for p in parts],electrode['solids'])
            if electrode['cutouts']: self.assertEqual([original(p) for p in shape['tools']],electrode['cutouts'])
        self.assertEqual(len(step.step_member_names(data,members)),len(members))
        self.assertEqual(data,before)
        return selected

    def test_real_selected_ip_all_solids_tools_and_two_instance_pose(self):
        a=self.assembly; recipe=copy.deepcopy(a.composition_plan['recipe'])
        row=copy.deepcopy(next(r for r in recipe['instances'] if r['instance_id']=='ion_processor'))
        row['instance_id']='ion_processor_2'; row['transform']['translation_mm'][0]+=500
        recipe['instances'].append(row)
        joined=assemble(recipe,dict(a.components,ion_processor_2=a.components['ion_processor']))
        first=self.check_source(joined,'ion_processor'); second=self.check_source(joined,'ion_processor_2')
        self.assertEqual([r['shape'] for r in first],[r['shape'] for r in second])
        self.assertNotEqual(first[0]['transform'],second[0]['transform'])

    def test_real_formed_contour_keeps_convex_vertices_and_cuts(self):
        fixture=contours.ElectrodeContourTests(); fixture.setUp()
        fixture.b['physical_design_selection']={'native_grid_mm':.1,'native_aux_segments':60}
        ip=resolve_component(dict(provider_id='dual_pressure_rectilinear_ion_processor',design=dict(baseline=fixture.b)))
        a=self.assembly; joined=assemble(a.composition_plan['recipe'],dict(a.components,ion_processor=ip))
        rows=self.check_source(joined,'ion_processor')
        self.assertIn('ip_convex_polyhedron',repr([r['shape'] for r in rows]))

    def test_unknown_and_degenerate_shape_refuse(self):
        for value in [dict(kind='ip_unknown'),dict(kind='ip_convex_polyhedron',vertices_mm=[[0,0,0]]*4)]:
            with self.subTest(value=value),self.assertRaises(ValueError): step._validate_shape(value)
    def test_parameter_change_reaches_real_step_members(self):
        a=self.assembly; baseline=copy.deepcopy(a.components_source['ion_processor']['baseline'])
        baseline['geometry']['r0_mm']+=.2
        ip=resolve_component(dict(provider_id='dual_pressure_rectilinear_ion_processor',design=dict(baseline=baseline)))
        changed=assemble(a.composition_plan['recipe'],dict(a.components,ion_processor=ip))
        old=self.check_source(a,'ion_processor'); new=self.check_source(changed,'ion_processor')
        self.assertNotEqual([r['shape'] for r in old],[r['shape'] for r in new])

    def test_public_export_cad_plans_selected_ip_before_owner(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from msplatform.exporters import operations
        context=SimpleNamespace()
        stage=dict(runtime={},limits={'transient_run_directory_bytes':1},artifact_retention={})
        with patch('msplatform.execution.stage_policy.read_stage_policy',return_value=(stage,{})), \
             patch('msplatform.execution.owner.run_managed_stage',return_value={'manifest':{}}) as owner, \
             patch('msplatform.results.artifacts.open_artifact',return_value='OPENED'):
            result=operations.export_cad(self.assembly,format='step',options=dict(representation='physical_solids',write_pcurves=True,precision_mode=0),context=context)
        self.assertEqual(result,'OPENED')
        call=owner.call_args.kwargs
        self.assertEqual(call['expected_operation_ids'],('export_step',))
        self.assertEqual(call['payload']['assembly']['components_resolved']['ion_processor'],self.assembly.components_resolved['ion_processor'])
    def test_changed_selected_csg_or_source_is_rejected(self):
        for target in ('resolved','source'):
            data=copy.deepcopy(snapshot(self.assembly))
            if target=='resolved':
                data['components_resolved']['ion_processor']['projection']['electrodes'][4]['cutouts'][0]['min_mm'][1]+=.1
            else:
                data['components_source']['ion_processor']['baseline']['geometry']['r0_mm']+=.1
            with self.subTest(target=target),self.assertRaises(ValueError): assembly_geometry_members(data)
    def test_zero_extent_ip_solids_refuse_before_kernel(self):
        shapes=[dict(kind='ip_box',min_mm=[0,0,0],max_mm=[0,1,1]),
                dict(kind='ip_cylinder_x',x_min_mm=0,x_max_mm=0,center_y_mm=0,center_z_mm=0,radius_mm=1)]
        for value in shapes:
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'strictly positive extents'):
                step._validate_shape(value)