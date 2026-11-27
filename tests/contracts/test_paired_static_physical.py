"""Physical and exact-coordinate contracts retained after old owner retirement."""
import copy
import math
from pathlib import Path
import tempfile
import unittest

from msplatform.backends.comsol import paired_static_model as paired_accelerator_model
from msplatform.analysis.paired_static_samples import validate_samples

class PairedStaticPhysicalTests(unittest.TestCase):
    def test_versioned_oa_voltage_projection_rejects_ambiguous_inputs(self):
        canonical = {'common_ground': 1, 'accelerator_repeller': 2,
                     'accelerator_intermediate_grid_1': 3, 'accelerator_intermediate_grid_2': 4,
                     'accelerator_exit_grid': 5, 'accelerator_ring_0001': 6, 'accelerator_ring_0002': 7}
        legacy = {'grounded_shield_id': 1, 'accelerator_repeller_id': 2, 'accelerator_grid1_id': 3,
                  'accelerator_intermediate2_id': 4, 'accelerator_grid2_id': 5, 'accelerator_ring_ids': [6, 7]}
        def plan(version, binding):
            return {'composition_plan': {'schema_version': version}, 'accelerator_variant': 'three_zone_square',
                    'oatof_instance_id': 'oa', 'native_geometry_compilation': {'electrode_bindings': {'oa': binding}},
                    'static_on_electrode_voltages_v': dict(zip(map(str, range(1, 8)), [0, 10, 8, 4, 0, 7, 6])),
                    'accelerator_electrical': {'operating_voltages_v': dict(shield=0, repeller=10, grid1=8,
                        intermediate2=4, grid2=0, rings=[7, 6])}}
        modern = plan(5, canonical)
        old = plan(3, legacy)
        expected = paired_accelerator_model._role_voltages(modern)
        self.assertEqual(paired_accelerator_model._role_voltages(old), expected)
        mutations = [lambda p: p['native_geometry_compilation']['electrode_bindings']['oa'].pop('grounded_shield_id'),
                     lambda p: p['native_geometry_compilation']['electrode_bindings']['oa'].update(common_ground=1),
                     lambda p: p['native_geometry_compilation']['electrode_bindings']['oa'].update(accelerator_ring_ids=[7, 6]),
                     lambda p: p['native_geometry_compilation']['electrode_bindings']['oa'].update(accelerator_ring_ids=[6, 6]),
                     lambda p: p['native_geometry_compilation']['electrode_bindings']['oa'].update(accelerator_ring_ids=[6]),
                     lambda p: p['native_geometry_compilation']['electrode_bindings']['oa'].update(accelerator_grid1_id=2),
                     lambda p: p['static_on_electrode_voltages_v'].update({'1': 1}),
                     lambda p: p['static_on_electrode_voltages_v'].pop('7'),
                     lambda p: p['composition_plan'].update(schema_version=5),
                     lambda p: p['composition_plan'].update(schema_version=4)]
        for mutate in mutations:
            changed = copy.deepcopy(old)
            mutate(changed)
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                paired_accelerator_model._role_voltages(changed)
        for mutate in (lambda p: p['native_geometry_compilation']['electrode_bindings']['oa'].pop('common_ground'),
                       lambda p: p['native_geometry_compilation']['electrode_bindings']['oa'].update(grounded_shield_id=1)):
            changed = copy.deepcopy(modern)
            mutate(changed)
            with self.subTest(modern_mutate=mutate), self.assertRaises(ValueError):
                paired_accelerator_model._role_voltages(changed)

    def test_sample_coordinates_round_trip_exactly_and_reject_a_true_ulp_change(self):
        pairs=[('89.94434260835371','89.944342608353708'),
               ('201.4266955495302','201.42669554953019')]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);expected=root/'prepared.csv';actual=root/'native.csv'
            expected.write_text('point_id,x_mm,y_mm,z_mm\n'+
                ''.join(f'{i},0,0,{prepared}\n' for i,(prepared,_) in enumerate(pairs,1)),encoding='utf-8')
            header='point_id,x_mm,y_mm,z_mm,Ex_V_per_m,Ey_V_per_m,Ez_V_per_m\n'
            rows=[f'{i},0,0,{native},0,0,0\n' for i,(_,native) in enumerate(pairs,1)]
            actual.write_text(header+''.join(rows),encoding='utf-8')
            plan={'sample_points':{'path':str(expected)}}
            for prepared,native in pairs:self.assertEqual(float(prepared).hex(),float(native).hex())
            validate_samples(plan,actual)
            for index,(_,native) in enumerate(pairs):
                with self.subTest(coordinate=native):
                    changed=rows.copy()
                    changed[index]=f'{index+1},0,0,{math.nextafter(float(native),math.inf):.17g},0,0,0\n'
                    actual.write_text(header+''.join(changed),encoding='utf-8')
                    with self.assertRaisesRegex(ValueError,'coverage differs'):
                        validate_samples(plan,actual)

    def test_saved_bvp_reuses_only_equivalent_physical_inputs(self):
        from msplatform.backends.comsol.paired_static_field import prepare
        from tests.components.single_reflection_oa_tof_mass_analyzer.analysis import test_paired_accelerator_static_field_prepare as fixtures
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);fixture=fixtures.PairedAcceleratorStaticFieldPrepareTests()
            request=fixture._request(root);plan=prepare(fixture._write_request(root,request),root/'prepared')
            original=paired_accelerator_model.paired_comsol_inputs(plan)
            raster=copy.deepcopy(plan)
            raster['numerical_domain']['cell_mm_xyz']['x']/=2
            raster['accelerator_geometry']['numerical_port_width_mm']*=2
            self.assertEqual(paired_accelerator_model.paired_comsol_inputs(raster),original)
            for name in ('box','mesh','metal','port','voltage'):
                with self.subTest(name=name):
                    changed=copy.deepcopy(plan)
                    if name=='box':changed['numerical_domain']['pa_bounds_mm']['x_min']-=1
                    elif name=='mesh':changed['numerical_domain']['comsol_mesh']['global_automatic_level']+=1
                    elif name=='metal':changed['accelerator_geometry']['shield_outer_width_mm']+=1
                    elif name=='port':changed['composition_plan']['components'][plan['oatof_instance_id']]['ports']['side_entry']['cross_section']['width_mm']+=1
                    else:changed['accelerator_electrical']['operating_voltages_v']['repeller']+=1
                    try:
                        self.assertNotEqual(paired_accelerator_model.paired_comsol_inputs(changed),original)
                    except ValueError:
                        pass  # Conflicting physical voltage records must also fail closed.
