"""Three physical operating tables from real providers, without a vendor run."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import tempfile
import unittest

from integrations.tests.test_single_reflection_preparation import fixture, release_fixture, write_json, rename_author_instances
from integrations.workflows.single_reflection_flight.prepare import prepare
from integrations.workflows.single_reflection_flight.fields import prepare_field_design, POLICY
from projects.rf_multipole_ion_optics.core.compile_design_request import compile_design_request
from projects.rf_multipole_ion_optics.tests.domain.test_compile_design_request import identity
from integrations.runtime.single_flight_frontend import native_frontend_instances
from integrations.tests.test_single_reflection_geometry import candidate_300mm_fixture, multi_inputs, multipole_source as chained_source, quadrupole_source
from common.contracts.verify_run_manifest import record_path
from common.contracts.rigid_transform import FramedPosition, RigidTransform, relative_transform


def multipole_source(project):
    """Compile a compatible mechanical test design through the real provider.

    These four-segment fixtures are not approved physical operating points.
    """
    root = Path(__file__).resolve().parents[2]
    request = json.loads((root / 'projects/rf_multipole_ion_optics/variants/octupole/config/requests/through_exit.json').read_text())
    request['identity'] = identity(project)
    request['request_id'] = 'test_' + project
    return compile_design_request(request, expected_identity=request['identity'])


class SingleReflectionFieldsTests(unittest.TestCase):
    def test_two_zone_geometry_is_not_claimed_as_a_supported_native_field_driver(self):
        with self.assertRaisesRegex(ValueError,'field/drive execution supports only three_zone_square'):
            prepare_field_design(None,{}, {},variant_id='two_zone_square',pulse_voltage_policy_id=POLICY,
                boundary_policy='native_zero_neumann',frontend_domains={})

    def test_local_oatof_uses_only_real_oa_metal_and_provider_voltages_without_rf_model(self):
        results = []
        for local in (False, True):
            with self.subTest(local=local), tempfile.TemporaryDirectory() as directory:
                path, run, request, _ = release_fixture(Path(directory), local=local)
                rename_author_instances(path,request)
                prepare(path, run)
                load = lambda name:json.loads((run/'inputs'/name).read_text())
                geometry, design = load('frontend_geometry.json'), load('frontend_field_design.json')
                self.assertNotIn('accelerator_electrodes', geometry)
                self.assertNotIn('multipole_electrode_ids', geometry)
                self.assertEqual(set(geometry['electrode_bindings']),
                                 set(geometry['composition_plan']['scope']['instance_ids']))
                if local:
                    self.assertEqual(design['scope'], 'accelerator_domain_only')
                    self.assertNotIn('rf_reference_voltage_v', design)
                    self.assertNotIn('pa_plus_solution_model', geometry)
                    self.assertNotIn('multipole_electrode_ids', geometry)
                    self.assertEqual([p['kind'] for p in design['working_points']], ['carrier_off','pulse_delta'])
                    self.assertEqual(len(design['domains'][0]['physical_samples']),25)
                    self.assertEqual({s['electrode_id'] for s in design['domains'][0]['physical_samples']},set(range(11,36)))
                    self.assertFalse(any(s['kind']=='rod' for s in design['domains'][0]['physical_samples']))
                    off, pulse = [p['electrode_voltages_v'] for p in design['working_points']]
                    self.assertEqual(set(off),{str(i) for i in range(11,36)})
                    self.assertTrue(all(v==0. for v in off.values()))
                    self.assertEqual(pulse,design['accelerator_voltage_states']['operating_voltages_v'])
                    # OA-only scope has no multipole provider or RF response authority.
                    oatof_id=native_frontend_instances(geometry['composition_plan'])[1]
                    repeated = prepare_field_design({},load(f'components/{oatof_id}/resolved_design.json'),geometry,
                        variant_id='three_zone_square',pulse_voltage_policy_id=POLICY,**request['numerics'])
                    self.assertEqual(repeated['working_points'],design['working_points'])
                results.append(design)
        full, local = results
        self.assertEqual(local['domains'][0]['physical_samples'],[
            row for row in full['domains'][0]['physical_samples'] if row['electrode_id']>=11])
        self.assertEqual(local['accelerator_voltage_states']['operating_voltages_v'],
                         {k:v for k,v in full['accelerator_voltage_states']['operating_voltages_v'].items() if int(k)>=11})

    def test_entrance_samples_actual_ring_intersection_not_parent_representative(self):
        with tempfile.TemporaryDirectory() as directory:
            path, run, request = fixture(Path(directory), entrance_refinement=True)
            from integrations.workflows.single_reflection_flight.geometry import compile_frontend_geometry
            source = json.loads((path.parent/'multipole.json').read_text())
            oatof = json.loads((path.parent/'oatof.json').read_text())
            plan=json.loads(record_path(request['composition_plan'],base_dir=path.parent).read_text())
            oatof_id=native_frontend_instances(plan)[1]
            _, geometry = compile_frontend_geometry({'multipole': source}, oatof, composition_plan=plan,
                numerical_domains=request['numerics']['frontend_domains'],
                electrode_bindings={key:value['electrode_bindings'] for key,value in request['providers']['instances'].items()},
                accelerator_variant=request['providers']['instances'][oatof_id]['geometry']['accelerator_variant'])
            projection = geometry['accelerator_projection']
            ring_z = projection['ring_z_mm'][1]
            lower = ring_z-projection['ring_thickness_mm']/2
            fine = request['numerics']['frontend_domains']['entrance_refinement']
            pitch = fine['cell_mm_xyz']['z']
            origin = fine['pa_bounds_mm']['z_min']
            # Keep two guard cells outside the actual sampled ring slice.
            fine['pa_bounds_mm']['z_max'] = origin+(math.floor((lower-origin)/pitch)+4)*pitch
            self.assertLess(fine['pa_bounds_mm']['z_max'], ring_z)
            write_json(path, request)
            prepare(path, run)
            design = json.loads((run/'inputs/frontend_field_design.json').read_text())
            parent, local = design['domains']
            for label in ('accelerator_ring_2','accelerator_shield'):
                original = next(s for s in parent['physical_samples'] if s['label']==label)
                sample = next(s for s in local['physical_samples'] if s['label']==label)
                original_z = parent['instance_origin_mm']['z']+original['gu'][2]*parent['cell_mm_xyz']['z']
                sample_z = local['instance_origin_mm']['z']+sample['gu'][2]*local['cell_mm_xyz']['z']
                self.assertGreater(original_z, local['bounds_mm']['z_max'])
                self.assertLessEqual(sample_z, local['bounds_mm']['z_max'])
                if label == 'accelerator_ring_2':
                    self.assertGreater(sample_z, lower)
                    self.assertLess(sample_z, ring_z+projection['ring_thickness_mm']/2)
            self.assertNotIn('accelerator_ring_3', {s['label'] for s in local['physical_samples']})
            self.assertEqual(len([s for s in local['physical_samples'] if s['kind']=='rod']), 32)

    def test_box_intersection_distinguishes_absent_metal_and_unrepresented_metal(self):
        from integrations.runtime.frontend_field_plan import box_sample
        box = dict(x_min_mm=-2.,x_max_mm=2.,y_min_mm=-2.,y_max_mm=2.,z_min_mm=.2,z_max_mm=.3)
        kwargs = dict(rotation=[[1,0,0],[0,1,0],[0,0,1]], translation=[0.,0.,0.],
                      origin=dict(x=-3.,y=-3.,z=0.),pitch=dict(x=1.,y=1.,z=1.),dimensions=dict(nx=7,ny=7,nz=3))
        bounds = dict(x_min=-3.,x_max=3.,y_min=-3.,y_max=3.,z_min=1.,z_max=2.)
        self.assertIsNone(box_sample(box,None,**kwargs,local_bounds_mm=bounds))
        bounds.update(z_min=0.,z_max=1.)
        with self.assertRaisesRegex(ValueError,'strictly inside'):
            box_sample(box,None,**kwargs,local_bounds_mm=bounds)

    def test_narrow_box_intersection_samples_present_metal_and_skips_absent_axes(self):
        from integrations.runtime.frontend_field_plan import box_sample
        box = dict(x_min_mm=-4.,x_max_mm=4.,y_min_mm=-4.,y_max_mm=4.,z_min_mm=-1.,z_max_mm=1.)
        hole = dict(x_min_mm=-2.,x_max_mm=2.,y_min_mm=-2.,y_max_mm=2.,z_min_mm=-2.,z_max_mm=2.)
        bounds = dict(x_min=-4.,x_max=-2.5,y_min=-1.,y_max=1.,z_min=-1.,z_max=1.)
        kwargs = dict(rotation=[[1,0,0],[0,1,0],[0,0,1]],translation=[0.,0.,0.],
            origin=dict(x=-4.,y=-4.,z=-2.),pitch=dict(x=.5,y=.5,z=.5),dimensions=dict(nx=17,ny=17,nz=9))
        gu = box_sample(box,hole,**kwargs,local_bounds_mm=bounds)
        self.assertLess(-4.+gu[0]*.5,-2.)
        self.assertIsNone(box_sample(box,hole,**kwargs,local_bounds_mm=dict(bounds,x_min=5.,x_max=6.)))
        self.assertIsNone(box_sample(box,hole,**kwargs,local_bounds_mm=dict(bounds,y_min=5.,y_max=6.)))
        self.assertIsNone(box_sample(box,hole,**kwargs,local_bounds_mm=dict(bounds,x_min=-1.,x_max=1.)))
        # There is real metal here, but neither neighboring grid node belongs
        # to this numerical intersection. A guard node must not substitute.
        with self.assertRaisesRegex(ValueError,'local numerical bounds'):
            box_sample(box,None,**kwargs,local_bounds_mm=dict(bounds,x_min=.2,x_max=.3))

    def test_four_six_eight_provider_preparation_and_invalid_pieces(self):
        from integrations.workflows.single_reflection_flight.geometry import compile_frontend_geometry
        from integrations.tests.test_single_reflection_geometry import candidate_300mm_fixture, inputs

        for project, rod_count in [('quadrupole', 4), ('hexapole', 6),
                                   ('octupole', 8)]:
            source = multipole_source(project)
            with self.subTest(project=project), tempfile.TemporaryDirectory() as directory:
                path, run, _ = fixture(Path(directory), source=source)
                prepare(path, run)
                design = json.loads((run / 'inputs/frontend_field_design.json').read_text())
                self.assertEqual(len(design['domains'][0]['physical_samples']), 4 * rod_count + 27)
                rod_samples = [row for row in design['domains'][0]['physical_samples'] if row['kind'] == 'rod']
                self.assertEqual(len(rod_samples), 4 * rod_count)
                self.assertEqual(len(design['working_points'][0]['electrode_voltages_v']), 35)
            for change in ('missing', 'duplicate', 'wrong_group'):
                invalid = copy.deepcopy(source)
                pieces = invalid['segmentation']['segmented_rod_array']['electrodes']
                if change == 'missing': pieces.pop()
                elif change == 'duplicate': pieces[-1] = copy.deepcopy(pieces[0])
                else: pieces[0]['electrode_group'] = 2
                oatof = candidate_300mm_fixture()
                with self.subTest(project=project, change=change), self.assertRaises(ValueError):
                    kw = inputs(invalid, oatof)
                    kw['electrode_bindings']['multipole'] = {i: i for i in range(1, 11)}
                    compile_frontend_geometry(invalid, oatof, **kw)

    def test_two_and_three_provider_dc_and_rf_tables_are_independent(self):
        from integrations.workflows.single_reflection_flight.geometry import compile_frontend_geometry
        oatof = candidate_300mm_fixture()
        sources = [chained_source('octupole'), chained_source('hexapole'), chained_source('quadrupole')]
        for count in (2, 3):
            names = [f'mp_{index}' for index in range(count)]
            kw = multi_inputs(sources[:count], oatof, names=names)
            _, geometry = compile_frontend_geometry(dict(zip(names, sources[:count], strict=True)), oatof, **kw)
            design = prepare_field_design(dict(zip(names, sources[:count], strict=True)), oatof, geometry,
                variant_id='three_zone_square', pulse_voltage_policy_id=POLICY,
                boundary_policy='native_zero_neumann', frontend_domains={
                    'parent': {'refine_convergence_v': {'carrier_off': .1, 'rf_reference': .1, 'pulse_delta': .1}}},
                rf_reference_voltage_v=10000.)
            self.assertEqual([point['kind'] for point in design['working_points']],
                             ['carrier_off', *(['rf_reference'] * count), 'pulse_delta'])
            self.assertEqual([point['working_point_id'] for point in design['working_points'][1:-1]],
                             [f'rf_reference_{index:02d}' for index in range(1, count + 1)])
            carrier = design['working_points'][0]['electrode_voltages_v']
            domain = design['domains'][0]
            poses = {row['instance_id']: RigidTransform.from_contract(row['transform'])
                     for row in geometry['composition_plan']['recipe']['instances']}
            downstream = native_frontend_instances(geometry['composition_plan'])[1]
            for name, source in zip(names, sources[:count], strict=True):
                inverse = relative_transform(poses[name], poses[downstream]).inverse()
                mapping = geometry['electrode_bindings'][name]
                for native_id in (9, 10):
                    sample = next(row for row in domain['physical_samples']
                                  if row['label'] == f'static_e{mapping[native_id]}')
                    xyz = tuple(domain['instance_origin_mm'][axis] + gu * domain['cell_mm_xyz'][axis]
                                for axis, gu in zip('xyz', sample['gu'], strict=True))
                    local = inverse.transform_position(FramedPosition(inverse.from_frame_id, xyz)).coordinates_mm
                    enclosure = source['geometry_mm']['enclosure']
                    # Neither audit anchor may land on a component mating cap.
                    self.assertGreater(local[2], enclosure['entrance_outer_endcap_downstream_face_z_mm'])
                    self.assertLess(local[2], enclosure['exit_outer_endcap_upstream_face_z_mm'])
            for ordinal, point in enumerate(design['working_points'][1:-1]):
                active = {key for key, value in point['electrode_voltages_v'].items() if value}
                provider_ids = {str(value) for value in geometry['electrode_bindings'][names[ordinal]].values()}
                self.assertTrue(active <= provider_ids)
                self.assertTrue(active)
                self.assertTrue(all(carrier[key] == point['electrode_voltages_v'][key] == 0. or key in active
                                    for key in carrier if key not in provider_ids))

    def test_narrow_fine_fields_sample_actual_entry_wall_and_all_multipole_groups(self):
        from integrations.workflows.single_reflection_flight.geometry import compile_frontend_geometry
        oatof = candidate_300mm_fixture()
        sources = [chained_source(project) for project in
                   ('octupole','hexapole','quadrupole')]
        for count in (2,3):
            with self.subTest(count=count):
                names = [f'mp_{i}' for i in range(count)]
                providers = dict(zip(names,sources[:count],strict=True))
                kw = multi_inputs(sources[:count],oatof,names=names)
                kw['numerical_domains']['parent']['pa_bounds_mm']['x_min'] = -1000.
                kw['numerical_domains']['parent']['cell_mm_xyz']['x'] = .5
                fine = copy.deepcopy(kw['numerical_domains']['parent'])
                fine.update(cell_mm_xyz=dict(x=.25,y=.5,z=.05),guard_cells=1)
                repeller = oatof['accelerator_topology']['planes_global_z_mm']['repeller']
                fine['pa_bounds_mm'].update(x_max=-115.,y_min=-40.,y_max=40.,z_max=repeller+40.)
                kw['numerical_domains']['entrance_refinement'] = fine
                _, geometry = compile_frontend_geometry(providers,oatof,**kw)
                convergence = dict(carrier_off=.1,rf_reference=.1,pulse_delta=.1)
                design = prepare_field_design(providers,oatof,geometry,variant_id='three_zone_square',
                    pulse_voltage_policy_id=POLICY,boundary_policy='native_zero_neumann',
                    frontend_domains={name:dict(refine_convergence_v=convergence) for name in kw['numerical_domains']},
                    rf_reference_voltage_v=10000.)
                parent, local = design['domains']
                shield = next(s for s in local['physical_samples'] if s['label']=='accelerator_shield')
                world_x = local['instance_origin_mm']['x']+shield['gu'][0]*local['cell_mm_xyz']['x']
                self.assertLess(world_x,geometry['accelerator_projection']['axis_x_mm'])
                mp_ids = {eid for name in names for eid in geometry['electrode_bindings'][name].values()}
                self.assertTrue(mp_ids <= {s['electrode_id'] for s in local['physical_samples']})
                self.assertGreater(len(parent['physical_samples']),len(local['physical_samples']))

    def test_three_quadrupoles_have_three_disjoint_rf_responses_and_real_dc(self):
        oatof = candidate_300mm_fixture()
        sources = [quadrupole_source(r0=r0, dc=dc, frequency_hz=freq, phase_rad=phase)
                   for r0, dc, freq, phase in ((4., 1., 1_000_000., .1), (4.5, 2., 1_100_000., .2), (5., 3., 1_200_000., .3))]
        names = ['q1', 'q2', 'q3']
        kw = multi_inputs(sources, oatof, names=names)
        from integrations.workflows.single_reflection_flight.geometry import compile_frontend_geometry
        _, geometry = compile_frontend_geometry(dict(zip(names, sources, strict=True)), oatof, **kw)
        design = prepare_field_design(dict(zip(names, sources, strict=True)), oatof, geometry,
            variant_id='three_zone_square', pulse_voltage_policy_id=POLICY, boundary_policy='native_zero_neumann',
            frontend_domains={'parent': {'refine_convergence_v': {'carrier_off': .1, 'rf_reference': .1, 'pulse_delta': .1}}}, rf_reference_voltage_v=10000.)
        carrier, *responses, pulse = design['working_points']
        self.assertEqual([point['working_point_id'] for point in responses], ['rf_reference_01','rf_reference_02','rf_reference_03'])
        for index, point in enumerate(responses):
            provider = {str(value) for value in geometry['electrode_bindings'][names[index]].values()}
            active = {key for key, value in point['electrode_voltages_v'].items() if value}
            self.assertTrue(active <= provider)
            dc = float(index + 1)
            self.assertTrue({dc, -dc} <= {carrier['electrode_voltages_v'][key] for key in provider})
        self.assertTrue(all(value == 0. for key, value in pulse['electrode_voltages_v'].items() if int(key) < 100))

    def prepared(self, directory):
        request, run, author = fixture(directory)
        prepare(request, run)
        inputs = run / 'inputs'
        load = lambda name: json.loads((inputs / name).read_text())
        geometry = load('frontend_geometry.json')
        multipoles,oatof=native_frontend_instances(geometry['composition_plan'])
        multipole = multipoles[0]
        return (multipole, load(f'components/{multipole}/resolved_design.json'), load(f'components/{oatof}/resolved_design.json'),
                geometry, author['numerics'], load('frontend_field_design.json'))

    def test_actual_32_pieces_35_electrical_groups_and_provider_voltages(self):
        with tempfile.TemporaryDirectory() as directory:
            multipole, upstream, _, _, numerics, design = self.prepared(Path(directory))
            self.assertEqual(design['schema_version'], 3)
            self.assertEqual(design['domains'][0]['boundary_policy'], 'native_zero_neumann')
            self.assertEqual(design['rf_reference_voltage_v'], numerics['rf_reference_voltage_v'])
            for obsolete in ('samples', 'mode_states_v', 'pa_plus_solution_model', 'refine_policy'):
                self.assertNotIn(obsolete, design)
            physical = design['domains'][0]['physical_samples']
            self.assertTrue(all('anchor_modes' not in row for row in physical))
            self.assertEqual({row['label'] for row in physical if row['kind'] == 'ideal_sheet'},
                             {'grid1_metal', 'intermediate2_metal', 'grid2_metal'})
            self.assertEqual([row['label'] for row in physical if row['kind'] == 'endpoint'], ['repeller_metal'])
            rods = [row for row in physical if row['kind'] == 'rod']
            self.assertEqual(len(rods), 32)
            self.assertEqual({(r['segment_id'], r['parent_rod_id']) for r in rods},
                             {(s, r) for s in range(1, 5) for r in range(1, 9)})
            self.assertEqual({r['electrode_id'] for r in physical}, set(range(1, 36)))
            self.assertEqual(len(physical), 59)
            self.assertEqual([p['kind'] for p in design['working_points']],
                             ['carrier_off', 'rf_reference', 'pulse_delta'])
            for point in design['working_points']:
                values = point['electrode_voltages_v']
                self.assertEqual(set(values), {str(i) for i in range(1, 36)})
                self.assertEqual([values[str(i)] for i in (9, 10, 11)], [0., 0., 0.])
                self.assertNotIn('refine_convergence_v', point)
                self.assertEqual(design['domains'][0]['refine_convergence_v'], numerics['frontend_domains']['parent']['refine_convergence_v'])
            off, rf, pulse = [p['electrode_voltages_v'] for p in design['working_points']]
            self.assertEqual([rf[str(i)] for i in range(1, 9)], [10000., -10000.] * 4)
            self.assertTrue(all(rf[str(i)] == 0 for i in range(9, 36)))
            for piece in upstream['segmentation']['segmented_rod_array']['electrodes']:
                sign = 1 if piece['electrode_group'] == 1 else -1
                self.assertEqual(off[str(piece['electrode_id'])], piece['common_mode_V']
                                 + sign * upstream['drive']['dc_amplitude_V_per_group'])
            self.assertTrue(all(off[str(i)] == 0 for i in range(9, 36)))
            self.assertTrue(all(pulse[str(i)] == 0 for i in range(1, 12)))
            for eid, value in design['accelerator_voltage_states']['operating_voltages_v'].items():
                self.assertAlmostEqual(pulse[eid], value, places=9)

    def test_reference_scale_changes_only_rf_field_not_provider_or_actual_dc(self):
        with tempfile.TemporaryDirectory() as directory:
            multipole, upstream, oatof, geometry, numerics, _ = self.prepared(Path(directory))
            for row in upstream['segmentation']['segmented_rod_array']['electrodes']:
                row['common_mode_V'] = 3.
            upstream['drive']['dc_amplitude_V_per_group'] = 2.
            original = copy.deepcopy(upstream)
            results = [prepare_field_design({multipole: upstream}, oatof, geometry, variant_id='three_zone_square',
                       pulse_voltage_policy_id=POLICY, **{**numerics, 'rf_reference_voltage_v': reference})
                       for reference in (10000., 250.)]
            self.assertEqual(upstream, original)
            self.assertEqual(results[0]['domains'][0]['physical_samples'], results[1]['domains'][0]['physical_samples'])
            for index in (0, 2):
                self.assertEqual(results[0]['working_points'][index], results[1]['working_points'][index])
            self.assertEqual([results[0]['working_points'][0]['electrode_voltages_v'][str(i)]
                              for i in range(1, 9)], [5., 1.] * 4)
            for eid, value in results[0]['working_points'][1]['electrode_voltages_v'].items():
                self.assertEqual(value / 40, results[1]['working_points'][1]['electrode_voltages_v'][eid])

    def test_missing_duplicate_wrong_group_and_non_node_sheet_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            multipole, upstream, oatof, geometry, numerics, _ = self.prepared(Path(directory))
            for change in ('missing', 'duplicate', 'wrong_group', 'sheet'):
                u, g = copy.deepcopy(upstream), copy.deepcopy(geometry)
                rods = u['segmentation']['segmented_rod_array']['electrodes']
                if change == 'missing': rods.pop()
                elif change == 'duplicate': rods[-1] = copy.deepcopy(rods[0])
                elif change == 'wrong_group': rods[0]['electrode_group'] = 2
                else: g['numerical_domains']['parent']['instance_origin_mm']['z'] += .025
                with self.subTest(change=change), self.assertRaises((ValueError, KeyError)):
                    prepare_field_design(u, oatof, g, variant_id='three_zone_square',
                                         pulse_voltage_policy_id=POLICY, **numerics)

    def test_instance_binding_missing_wrong_instance_collision_and_wrong_group_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            multipole, upstream, oatof, geometry, numerics, _ = self.prepared(Path(directory))
            edge = geometry['composition_plan']['recipe']['connections'][0]
            first, second = edge['upstream']['instance_id'], edge['downstream']['instance_id']
            original = copy.deepcopy(geometry)
            for change in ('missing_instance', 'unknown_instance', 'swapped_instances', 'duplicate_native',
                           'missing_native', 'missing_role', 'collision', 'wrong_group'):
                g = copy.deepcopy(geometry)
                bindings = g['electrode_bindings']
                if change == 'missing_instance': del bindings[first]
                elif change == 'unknown_instance': bindings['unselected'] = bindings.pop(first)
                elif change == 'swapped_instances': bindings[first], bindings[second] = bindings[second], bindings[first]
                elif change == 'duplicate_native': bindings[first][1] = bindings[first]['1']
                elif change == 'missing_native': del bindings[first]['1']
                elif change == 'missing_role': del bindings[second]['accelerator_repeller_id']
                elif change == 'collision': bindings[second]['grounded_shield_id'] = 1
                else: bindings[first]['1'], bindings[first]['2'] = bindings[first]['2'], bindings[first]['1']
                with self.subTest(change=change), self.assertRaises(ValueError):
                    prepare_field_design(upstream, oatof, g, variant_id='three_zone_square',
                                         pulse_voltage_policy_id=POLICY, **numerics)
            self.assertEqual(geometry, original)

    def test_invalid_numeric_values_rejected_by_pure_field_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            multipole, upstream, oatof, geometry, numerics, _ = self.prepared(Path(directory))
            for target in ('rf_reference_voltage_v', 'carrier_off', 'rf_reference', 'pulse_delta'):
                for value in (0, -1, True, float('inf'), float('nan'), '0.1'):
                    bad = copy.deepcopy(numerics)
                    if target == 'rf_reference_voltage_v': bad[target] = value
                    else: bad['frontend_domains']['parent']['refine_convergence_v'][target] = value
                    with self.subTest(target=target, value=value), self.assertRaisesRegex(ValueError, 'finite and positive'):
                        prepare_field_design({multipole: upstream}, oatof, geometry, variant_id='three_zone_square',
                                             pulse_voltage_policy_id=POLICY, **bad)

    def test_current_author_contract_rejects_missing_extra_and_old_numerics_before_products(self):
        mutations = [lambda r: r.update(schema_version=3),
                     lambda r: r.update(numerics={'refine_policy': 'official_defaults'}),
                     lambda r: r['numerics'].update(boundary_policy='zero_dirichlet'),
                     lambda r: r['numerics'].pop('rf_reference_voltage_v'),
                     lambda r: r['numerics']['frontend_domains']['parent']['refine_convergence_v'].pop('pulse_delta'),
                     lambda r: r['numerics']['frontend_domains']['parent']['refine_convergence_v'].update(extra=0.1)]
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index), tempfile.TemporaryDirectory() as directory:
                path, run, request = fixture(Path(directory))
                mutate(request)
                write_json(path, request)
                with self.assertRaises(ValueError):
                    prepare(path, run)
                for name in ('frontend.gem', 'frontend_field_design.json', 'projected_source.csv', 'frontend.pa+'):
                    self.assertFalse((run / 'inputs' / name).exists())

    def test_only_whole_author_held_off_omits_pulse_and_preserves_two_three_rf_members(self):
        from integrations.workflows.single_reflection_flight.geometry import compile_frontend_geometry
        oatof = candidate_300mm_fixture()
        sources = [chained_source('octupole'), chained_source('hexapole'), chained_source('quadrupole')]
        for count in (2, 3):
            names = [f'mp_{i}' for i in range(count)]
            providers = dict(zip(names, sources[:count], strict=True))
            _, geometry = compile_frontend_geometry(providers, oatof, **multi_inputs(sources[:count], oatof, names=names))
            options = dict(variant_id='three_zone_square', pulse_voltage_policy_id=POLICY,
                boundary_policy='native_zero_neumann', frontend_domains={'parent': {'refine_convergence_v':
                    {'carrier_off': .1, 'rf_reference': .2, 'pulse_delta': .3}}}, rf_reference_voltage_v=10000.)
            complete = prepare_field_design(providers, oatof, geometry, **options)
            for author in (None, {'pulse': {'mode': 'timed'}}, {'pulse': {'mode': 'discover'}}, {'pulse': {'mode': 'held_off'}}):
                with self.subTest(count=count, author=author):
                    actual = prepare_field_design(providers, oatof, geometry, flight=author, **options)
                    held = author is not None and author['pulse']['mode']=='held_off'
                    self.assertEqual(actual['working_points'], complete['working_points'][:-1] if held else complete['working_points'])
                    self.assertEqual(actual['domains'][0]['physical_samples'], complete['domains'][0]['physical_samples'])
                    self.assertEqual(actual['accelerator_voltage_states'], complete['accelerator_voltage_states'])
                    self.assertEqual([p['working_point_id'] for p in actual['working_points'] if p['kind']=='rf_reference'],
                                     [f'rf_reference_{i:02d}' for i in range(1,count+1)])


if __name__ == '__main__':
    unittest.main()
