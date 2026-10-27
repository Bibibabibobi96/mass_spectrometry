"""Pure direct-body assembly regression, with independent mechanical vectors."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from common.contracts.machine_contracts import ContractError
from common.contracts.rigid_transform import FramedPosition, RigidTransform
from projects.rf_multipole_ion_optics.core.compile_design_request import compile_design_request
from projects.rf_multipole_ion_optics.simion.simion_geometry import render_physical_gem, physical_electrode_view
from projects.rf_multipole_ion_optics.tests.domain.test_compile_design_request import design_request
from common.integration.resolve_assembly import compile_assembly_layout
from projects.rf_multipole_ion_optics.core.component_port import build_assembly_interface
from integrations.workflows.single_reflection_flight.geometry import (
    compile_frontend_geometry, render_frontend_body, render_frontend_domain,
)
from integrations.tests.frontend_fixtures import compile_geometry_and_port
from projects.orthogonal_accelerator.simion.sectioned_accelerator import render_accelerator_local_geometry
from projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.test_assembly_interface import candidate_300mm_fixture as accelerator_fixture
from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_geometry import project_side_opening, resolve_accelerator_geometry
from projects.single_reflection_oa_tof_mass_analyzer.analysis.assembly_interface import resolve_assembly_interface


def candidate_300mm_fixture():
    """Compile a complete explicit synthetic instrument, without run artifacts.

    This preserves the independent accelerator vectors of the original fixture;
    it is not the historical 300-mm Candidate or its author-selected layout.
    """
    project = Path(__file__).resolve().parents[2]/"projects/single_reflection_oa_tof_mass_analyzer"
    baseline = json.loads((project/"config/resolved_geometry.json").read_text())
    partial = accelerator_fixture()
    baseline["geometry_mm"].update(partial["geometry_mm"])
    baseline["rings"].update(partial["rings"])
    port = json.loads((project/"config/interfaces/required/oatof_accelerator_entry.json").read_text())
    port["mating_surface"]["center_mm"][0] = -122.8
    candidate = dict(role="oatof_three_zone_simion_candidate_resolved", qualification="CANDIDATE_ONLY",
        compiler_mode="T5_FROZEN_PRIMARY_AND_BRANCH_ONLY", campaign=dict(campaign_id="test_explicit_instrument"),
        t5_evidence=dict(plan_sha256="A"*64), source_identity=dict(frozen_source=dict(center_x_mm=3.5, nominal_energy_per_charge_v=2000.)),
        identities=dict(topology_id="three_zone_accelerator_ideal_v1", geometry_id="three_zone_focus_origin_planes_v1",
                        field_id="three_zone_piecewise_uniform_ideal_field_v1"),
        accelerator_topology=partial["accelerator_topology"], accelerator_physics=dict(
            lengths_mm=dict(d1=7.,d2=56.1,d3=236.9),focus_drift_after_exit_mm=42.742615461548496),
        reflectron=dict(u_r1_v=1600.,f_r2_v_per_mm=10.))
    profile = dict(layout_profile_id="test_explicit_instrument",architecture_generation_id="test_explicit_instrument",
        method="t5_frozen_three_zone_candidate_v1",reference_injection_energy_eV=5.,target_injection_energy_eV=5.,
        topology_id="three_zone_accelerator_ideal_v1",geometry_id="three_zone_focus_origin_planes_v1",
        source_release_full_width_mm=4.,focus_to_reflectron_mm=600.,candidate_field_id="three_zone_piecewise_uniform_ideal_field_v1",
        claim_status="CANDIDATE_ONLY",accelerator_ring_placement_policy=dict(policy_id="three_zone_zonewise_equal_subdivision_v1",
            zone2_ring_count=4,zone3_ring_count=16,minimum_grid_to_ring_edge_clearance_mm=1.))
    resolved, _, _ = compile_geometry_and_port(baseline,port,profile,three_zone_candidate=candidate,
        three_zone_candidate_binding=dict(path="test_candidate.json",sha256="B"*64))
    return resolved


def multipole_source(project, *, shell=False):
    """Compile a current bare, segmented provider; no hidden optical geometry."""
    root = Path(__file__).resolve().parents[2]
    request = json.loads((root / 'projects/rf_multipole_ion_optics/variants/octupole/config/requests/mechanical_base.json').read_text())
    request['identity'] = design_request(project)['identity']
    request['request_id'] = 'test_' + project
    if shell:
        request['geometry_mm']['enclosure'] = dict(model='cylindrical_grounded_shell',
            inner_radius_mm=20., wall_thickness_mm=1., z_min_mm=-2.5, z_max_mm=82.1,
            endcaps=dict(entrance=dict(aperture_radius_mm=3.6, thickness_mm=.5),
                         exit=dict(aperture_radius_mm=3.6, thickness_mm=.5)))
        request['static_electrodes_V'] = dict(role='grounded_shell_static_electrodes', ground_V=0.)
    return compile_design_request(request, expected_identity=request['identity'])


def quadrupole_source(*, r0, dc, frequency_hz, phase_rad):
    root = Path(__file__).resolve().parents[2]
    request = json.loads((root / 'projects/rf_multipole_ion_optics/variants/octupole/config/requests/mechanical_base.json').read_text())
    request['identity'] = design_request('quadrupole')['identity']
    request['request_id'] = f'test_quad_{r0}_{dc}_{frequency_hz}_{phase_rad}'
    request['geometry_mm']['inscribed_radius_r0'] = r0
    request['drive'].update(dc_amplitude_V_per_group=dc, frequency_Hz=frequency_hz, phase_rad=phase_rad)
    return compile_design_request(request, expected_identity=request['identity'])


def source_fixture(segmentation=None, *, entrance_aperture_radius_mm=3.):
    """An explicit two-cap housing, distinct from the default bare provider."""
    request = design_request("octupole", segmentation=segmentation)
    request["geometry_mm"]["enclosure"] = dict(model="cylindrical_grounded_shell",
        inner_radius_mm=20., wall_thickness_mm=1., z_min_mm=2., z_max_mm=89.,
        endcaps=dict(entrance=dict(aperture_radius_mm=entrance_aperture_radius_mm, thickness_mm=.5),
                     exit=dict(aperture_radius_mm=3.25, thickness_mm=.5)))
    request["geometry_mm"]["numerical_domain"].update(z_min_mm=1., z_max_mm=90.)
    request["geometry_mm"]["observations"].update(release_plane_z_mm=3., handoff_plane_z_mm=89., census_plane_z_mm=89.5, acceptance_radius_mm=3.)
    request["static_electrodes_V"] = dict(role="grounded_shell_static_electrodes", ground_V=0.)
    return compile_design_request(request, expected_identity=request["identity"])


def native_mapping(source):
    return {row['native_electrode_id']: row['native_electrode_id']
            for row in physical_electrode_view(source)}


def inputs(source, oatof, *, accelerator_variant="three_zone_square"):
    projection = resolve_accelerator_geometry(oatof, variant_id=accelerator_variant)
    z = projection.local_region["repeller_front_z_mm"] + 2
    exit_z = build_assembly_interface(source, geometry_profile_id=None)["ports"]["mechanical_exit"]["center_mm"][2]
    gap = 1. if source["geometry_mm"]["enclosure"]["model"] == "bare" else 0.
    def pose(frame, rotation, translation):
        return dict(schema_version=1, role="rigid_transform", from_frame_id=frame, to_frame_id="oatof_global",
                    rotation=rotation, translation_mm=translation)
    recipe = dict(schema_version=1, role="assembly_recipe", integration_id="instrument_assembly", recipe_id="native_bodies",
        assembly_frame_id="oatof_global", position_tolerance_mm=1e-9, angular_tolerance_rad=1e-9,
        instances=[dict(instance_id="multipole", project_id=source["identity"]["project_id"],
            transform=pose(source["coordinate"]["coordinate_id"], [[0,0,1],[1,0,0],[0,1,0]], [-122.8-exit_z-gap,0,z])),
            dict(instance_id="oatof", project_id="single_reflection_oa_tof_mass_analyzer",
                 transform=pose("oatof_global", [[1,0,0],[0,1,0],[0,0,1]], [0,0,0]))],
        connections=[dict(connection_id="entrance", upstream=dict(instance_id="multipole", port_id="mechanical_exit"),
            downstream=dict(instance_id="oatof", port_id="side_entry"), gap_mm=gap, coupling_mode="monolithic_joint_solve")])
    project_side_opening(projection.local_region,
        side_opening=dict(center_mm=[-122.8,0,z],width_mm=1.,height_mm=4.),
        cell_mm_xyz=dict(x=.3,y=.25,z=.1),pa_origin_mm=dict(x=-300.,y=-80.,z=-380.))
    components=dict(multipole=build_assembly_interface(source,geometry_profile_id=None),
                    oatof=resolve_assembly_interface(oatof,projection=projection,geometry_profile_id=None))
    return dict(composition_plan=compile_assembly_layout(recipe,components), accelerator_variant=accelerator_variant,
        numerical_domains=dict(parent=dict(cell_mm_xyz=dict(x=.3,y=.25,z=.1),
        pa_bounds_mm=dict(x_min=-300.,x_max=60.,y_min=-80.,y_max=80.,z_min=-380.,z_max=-30.))),
        electrode_bindings=dict(multipole=native_mapping(source), oatof=dict(
            grounded_shield_id=11, accelerator_repeller_id=12, accelerator_grid1_id=13,
            accelerator_intermediate2_id=14, accelerator_grid2_id=15,
            accelerator_ring_ids=list(range(20, 20+projection.local_region["ring_count"])))))


def multi_inputs(sources, oatof, *, names, multipole_gap_mm=1.):
    """Declare positive clearance for bare rod ends in both poses and connections."""
    base = inputs(sources[0], oatof)
    recipe = base['composition_plan']['recipe']
    z = recipe['instances'][0]['transform']['translation_mm'][2]
    oa = recipe['instances'][1]
    instances = []
    downstream_x = -122.8
    for name, source in reversed(list(zip(names, sources, strict=True))):
        exit_z = build_assembly_interface(source, geometry_profile_id=None)['ports']['mechanical_exit']['center_mm'][2]
        entrance_z = build_assembly_interface(source, geometry_profile_id=None)['ports']['mechanical_entrance']['center_mm'][2]
        gap = (1. if source["geometry_mm"]["enclosure"]["model"] == "bare" else 0.) if name == names[-1] else multipole_gap_mm
        tx = downstream_x - exit_z - gap
        instances.append(dict(instance_id=name, project_id=source['identity']['project_id'],
            transform=dict(recipe['instances'][0]['transform'], translation_mm=[tx, 0., z])))
        downstream_x = tx + entrance_z
    instances.reverse()
    recipe = dict(recipe, instances=[*instances, oa], connections=[])
    for index, name in enumerate(names):
        target = 'oatof' if index + 1 == len(names) else names[index + 1]
        recipe['connections'].append(dict(connection_id='chain_'+str(index+1),
            upstream=dict(instance_id=name, port_id='mechanical_exit'),
            downstream=dict(instance_id=target, port_id='side_entry' if target == 'oatof' else 'mechanical_entrance'),
            gap_mm=(1. if sources[index]['geometry_mm']['enclosure']['model'] == 'bare' else 0.) if target == 'oatof' else multipole_gap_mm, coupling_mode='monolithic_joint_solve'))
    components = {name: build_assembly_interface(source, geometry_profile_id=None)
                  for name, source in zip(names, sources, strict=True)}
    components['oatof'] = base['composition_plan']['components']['oatof']
    bindings, next_id = {}, 1
    for name, source in zip(names, sources, strict=True):
        native = [row['native_electrode_id'] for row in physical_electrode_view(source)]
        bindings[name] = {eid: next_id + index for index, eid in enumerate(native)}
        next_id += len(native)
    oa_binding = base['electrode_bindings']['oatof']
    bindings['oatof'] = {key: ([value + 100 for value in value] if key == 'accelerator_ring_ids' else value + 100)
                         for key, value in oa_binding.items()}
    numerical_domains = copy.deepcopy(base['numerical_domains'])
    numerical_domains['parent']['pa_bounds_mm']['x_min'] = -999.9
    repeller = oatof['accelerator_topology']['planes_global_z_mm']['repeller']
    numerical_domains['parent']['pa_bounds_mm'].update(z_min=repeller - 40., z_max=repeller + 310.)
    return dict(composition_plan=compile_assembly_layout(recipe, components),
                accelerator_variant=base['accelerator_variant'], numerical_domains=numerical_domains,
                electrode_bindings=bindings)


def reframe_parent(plan, *, rotation=((1.,0.,0.),(0.,1.,0.),(0.,0.,1.)), translation=(0.,0.,0.)):
    """Change only the parent reference; preserve every physical relative pose."""
    recipe = copy.deepcopy(plan['recipe'])
    parent = RigidTransform(recipe['assembly_frame_id'], 'laboratory', rotation, translation)
    recipe['assembly_frame_id'] = parent.to_frame_id
    for instance in recipe['instances']:
        instance['transform'] = RigidTransform.from_contract(instance['transform']).then(parent).to_contract()
    return compile_assembly_layout(recipe, plan['components'], local_scope=plan.get('local_scope'))


class SingleReflectionGeometryTests(unittest.TestCase):
    def setUp(self):
        self.source, self.oatof = source_fixture(), candidate_300mm_fixture()
        self.kw = inputs(self.source, self.oatof)

    def compile(self):
        from common.integration.resolve_assembly import compile_assembly_layout
        from integrations.runtime.single_flight_frontend import native_frontend_instances
        plan = self.kw['composition_plan']
        self.kw['composition_plan'] = compile_assembly_layout(plan['recipe'], plan['components'], local_scope=plan.get('local_scope'))
        multipoles, _ = native_frontend_instances(self.kw['composition_plan'])
        gems, geometry = compile_frontend_geometry({instance_id: self.source for instance_id in multipoles}, self.oatof, **self.kw)
        self.assertNotIn(' within {', gems['parent'])
        self.assertIn(' within_inside_or_on {', gems['parent'])
        return gems['parent'], geometry

    def test_renamed_and_reordered_instances_preserve_bodies_and_reject_other_topology(self):
        from integrations.tests.test_single_reflection_preparation import rename_recipe_instances
        gem, original = self.compile()
        plan=self.kw['composition_plan']
        names = rename_recipe_instances(plan['recipe'])
        plan['components']={names[key]:value for key,value in plan['components'].items()}
        self.kw['electrode_bindings']={names[key]:value for key,value in self.kw['electrode_bindings'].items()}
        renamed_gem, renamed = self.compile()
        self.assertEqual(gem,renamed_gem)
        self.assertEqual({k:v for k,v in original.items() if k not in ('composition_plan','electrode_bindings')},
                         {k:v for k,v in renamed.items() if k not in ('composition_plan','electrode_bindings')})
        self.assertEqual(renamed['electrode_bindings'],
                         {names[key]: value for key,value in original['electrode_bindings'].items()})
        self.assertEqual(set(renamed['composition_plan']['components']),set(names.values()))
        recipe = copy.deepcopy(self.kw['composition_plan']['recipe'])
        for failure in ('extra_instance','extra_edge','provider','port','coupling','gap'):
            self.kw['composition_plan']['recipe'] = copy.deepcopy(recipe)
            current = self.kw['composition_plan']['recipe']
            if failure=='extra_instance': current['instances'].append(dict(current['instances'][0],instance_id='extra'))
            elif failure=='extra_edge': current['connections'].append(dict(current['connections'][0],connection_id='extra'))
            elif failure=='provider': current['instances'][0]['project_id']='rf_multipole_ion_optics'
            elif failure=='port': current['connections'][0]['downstream']['port_id']='mechanical_exit'
            elif failure=='coupling': current['connections'][0]['coupling_mode']='state_handoff'
            else: current['connections'][0]['gap_mm']=-1.
            with self.subTest(failure=failure),self.assertRaises(ValueError): self.compile()

    def test_local_oatof_removes_only_native_multipole_body_without_remapping(self):
        from integrations.tests.test_single_reflection_fields import multipole_source
        self.source = multipole_source('octupole')
        self.kw = inputs(self.source, self.oatof)
        self.kw['electrode_bindings']['multipole'] = native_mapping(self.source)
        self.kw['electrode_bindings']['oatof']['accelerator_ring_ids'] = list(range(16,36))
        from integrations.tests.test_single_reflection_preparation import rename_recipe_instances
        plan=self.kw['composition_plan']
        names=rename_recipe_instances(plan['recipe'])
        plan['components']={names[key]:value for key,value in plan['components'].items()}
        self.kw['electrode_bindings']={names[key]:value for key,value in self.kw['electrode_bindings'].items()}
        full_gem, full = self.compile()
        declaration = dict(instance_ids=['tof_b'], research_scope='OA and TOF only',
                           boundary_assumptions='Omit multipole metal and fields at the unchanged side aperture')
        full_bindings=copy.deepcopy(self.kw['electrode_bindings'])
        self.kw['composition_plan']['local_scope'] = declaration
        self.kw['electrode_bindings']={'tof_b':full_bindings['tof_b']}
        with patch('integrations.workflows.single_reflection_flight.geometry.render_physical_gem') as native:
            local_gem, local = self.compile()
            native.assert_not_called()
        self.assertEqual(local['composition_plan']['recipe'], full['composition_plan']['recipe'])
        for key in ('accelerator_projection','downstream_pa_instances','numerical_domains'):
            self.assertEqual(local[key], full[key], key)
        self.assertEqual(local['electrode_bindings'], {'tof_b': full['electrode_bindings']['tof_b']})
        self.assertNotIn('pa_plus_solution_model', local)
        self.assertNotIn('multipole_electrode_ids', local)
        local_body = '\n'.join(local_gem.splitlines()[3:-1])
        self.assertTrue(full_gem.endswith(local_body+'\n}\n'))
        for eid in full_bindings[names['multipole']].values():
            self.assertNotIn(f'e({eid})', local_body)
        for eid in range(11,36):
            self.assertIn(f'e({eid})', local_body)
        # A declared local numerical box may exclude the absent upstream body.
        self.kw['numerical_domains']['parent']['pa_bounds_mm']['x_min'] = -129.9
        self.compile()
        del self.kw['composition_plan']['local_scope']
        self.kw['electrode_bindings']=full_bindings
        with self.assertRaisesRegex(ValueError, 'clip a provider'):
            self.compile()

    def test_local_oatof_rejects_entrance_refinement_and_other_selections(self):
        declaration = dict(instance_ids=['oatof'], research_scope='OA and TOF only',
                           boundary_assumptions='Omit upstream metal and fields')
        self.kw['composition_plan']['local_scope']={**declaration,'instance_ids':['multipole']}
        self.kw['electrode_bindings']={'multipole':self.kw['electrode_bindings']['multipole']}
        with self.assertRaisesRegex(ValueError, 'requires one oaTOF'):
            self.compile()
        self.kw=inputs(self.source,self.oatof)
        self.kw['composition_plan']['local_scope'] = declaration
        self.kw['electrode_bindings']={'oatof':self.kw['electrode_bindings']['oatof']}
        self.kw['numerical_domains']['entrance_refinement'] = dict(
            copy.deepcopy(self.kw['numerical_domains']['parent']),guard_cells=1)
        with self.assertRaisesRegex(ValueError, 'cannot use multipole entrance_refinement'):
            self.compile()

    def test_exact_provider_bodies_unique_pose_real_cap_hole_and_ring_ids(self):
        before = copy.deepcopy((self.source, self.oatof, self.kw))
        gem, geometry = self.compile()
        self.assertEqual((self.source, self.oatof, self.kw), before)
        self.assertEqual(gem.count("pa_define("), 1)
        self.assertEqual(gem.count(",1,90,90,0) {"), 1)
        self.assertIn("locate(300,80,380) {", gem)
        self.assertIn("locate(-211.8,0,-340.742615462,1,90,90,0) {", gem)
        native_cells = dict(x=.25,y=.1,z=.3)
        self.assertEqual(geometry["numerical_domains"]["parent"]["cell_mm_xyz"], dict(x=.3,y=.25,z=.1))
        provider_syntax = gem.replace(" within_inside_or_on {", " within {")
        self.assertIn(render_physical_gem(self.source, native_cells, electrode_ids=native_mapping(self.source)).rstrip(), provider_syntax)
        self.assertIn("cylinder(0,0,89,20,,0.5)", gem)  # actual endcap
        self.assertIn("cylinder(0,0,89.3,3.25,,1.1)", gem)  # original hole overrun
        self.assertNotIn("numerical absorber", gem)
        self.assertNotIn("Integration-owned", gem)
        expected_oa = render_accelerator_local_geometry(geometry["accelerator_projection"], cell_x_mm=.3,
            cell_z_mm=.1, electrodes=self.kw['electrode_bindings']['oatof'], render_intermediate2_sheet=True)
        self.assertIn("\n".join(expected_oa), provider_syntax)
        for electrode in [11,12,13,14,15,*range(20,40)]:
            self.assertIn(f"e({electrode})", gem)
        check = geometry["composition_plan"]["connection_checks"][0]
        for actual, expected in zip(check["upstream_center_mm"], check["downstream_center_mm"]):
            self.assertAlmostEqual(actual, expected, places=12)
        self.assertEqual(check["upstream_outward_normal"], [1,0,0])

    def test_non_axis_symmetric_native_point_and_electrical_identity(self):
        gem, geometry = self.compile()
        transform = RigidTransform.from_contract(self.kw['composition_plan']['recipe']["instances"][0]["transform"])
        point = transform.transform_position(FramedPosition(transform.from_frame_id, (2,3,5))).coordinates_mm
        self.assertEqual(point, (-206.8,2.,-337.74261546154855))
        # Orientation .125 in the real source fixture gives non-symmetric rod centres.
        rod = self.source["geometry_mm"]["rod_array"]["rods"][0]
        self.assertNotEqual(rod["center_x_mm"], rod["center_y_mm"])
        self.assertIn(f"e({geometry['electrode_bindings']['multipole'][rod['electrode_group']]})", gem)

    def test_numerical_domains_reuse_the_exact_complete_body_without_rendering_again(self):
        module = "integrations.workflows.single_reflection_flight.geometry"
        with patch(module + ".render_frontend_body", wraps=render_frontend_body) as renderer:
            gem, geometry = self.compile()
            renderer.assert_called_once()
        # Extract only the existing PA wrapper; all physical locate/CSG stays intact.
        body = "\n".join(gem.splitlines()[3:-1])
        self.assertIn("e(14)", body)  # actual intermediate2 sheet
        for electrode in [11,12,13,14,15,*range(20,40)]:
            self.assertIn(f"e({electrode})", body)
        with patch(module + ".render_physical_gem") as multipole, patch(module + ".render_accelerator_local_geometry") as oa:
            original = render_frontend_domain(body, dimensions=geometry["numerical_domains"]["parent"]["dimensions"],
                cell_mm_xyz=geometry["numerical_domains"]["parent"]["cell_mm_xyz"], pa_origin_mm=geometry["numerical_domains"]["parent"]["instance_origin_mm"])
            alternate = render_frontend_domain(body, dimensions=dict(nx=101,ny=81,nz=61),
                cell_mm_xyz=dict(x=.15,y=.125,z=.05), pa_origin_mm=dict(x=-130.,y=-5.,z=-345.))
            self.assertEqual(original, gem)
            self.assertEqual("\n".join(alternate.splitlines()[3:-1]), body)
            self.assertIn("pa_define(101,81,61,planar,none,electrostatic,,0.15,0.125,0.05,surface=none)", alternate)
            self.assertIn("locate(130,5,345) {", alternate)
            multipole.assert_not_called()
            oa.assert_not_called()

    def test_none_domain_fills_physical_nodes_without_changing_hole_operators(self):
        body = "\n".join([
            "e(1) { fill { within { cylinder(0,0,1,2,,1) }",
            " notin { cylinder(0,0,1,1,,1) }",
            " notin_inside { cylinder(0,0,1,.5,,1) }",
            " notin_inside_or_on { cylinder(0,0,1,.25,,1) } } }",
            "e(2) { fill { within_inside { box3d(0,0,0,1,1,1) } } }",
            "e(3) { fill { within_inside_or_on { box3d(0,0,0,1,1,1) } } }",
        ])
        original = body
        domain = dict(dimensions=dict(nx=7, ny=7, nz=7),
                      cell_mm_xyz=dict(x=.5, y=1., z=.05),
                      pa_origin_mm=dict(x=0., y=0., z=0.))
        gem = render_frontend_domain(body, **domain)
        self.assertEqual(body, original)
        self.assertNotIn(" within {", gem)
        self.assertIn("within_inside_or_on { cylinder(0,0,1,2,,1)", gem)
        for line in original.splitlines()[1:]:
            self.assertIn(line, gem)
        strict_body = "\n".join(gem.splitlines()[3:-1])
        self.assertEqual(render_frontend_domain(strict_body, **domain), gem)


    def test_two_zone_renderer_does_not_invent_intermediate_sheet(self):
        planes = self.oatof.pop("accelerator_topology")["planes_global_z_mm"]
        self.oatof["geometry_derivation"]["accelerator"].update(
            canonical_repeller_z_mm=planes["repeller"], canonical_grid1_z_mm=planes["intermediate1"],
            canonical_grid2_z_mm=planes["exit"], d2_mm=planes["exit"]-planes["intermediate1"])
        self.oatof["rings"].update(accelerator_count=5)
        self.oatof["rings"].pop("accelerator_placement")
        self.oatof["electrodes_V"].pop("intermediate2")
        self.kw = inputs(self.source, self.oatof, accelerator_variant="two_zone_square")
        self.kw['electrode_bindings']['oatof'].pop("accelerator_intermediate2_id")
        self.kw['electrode_bindings']['oatof']["accelerator_ring_ids"] = list(range(20,25))
        gem, _ = self.compile()
        self.assertNotIn("e(14)", gem)
        self.assertIn("e(24)", gem)

    def test_downstream_domains_use_final_nonzero_axis_and_numerical_detector_plane(self):
        self.oatof["coordinate_convention"].update(reflectron_axis=[7.,-9.],detector_x=81.)
        self.oatof["simion_detector_marker"]["active_plane_z_mm"] = 12.5
        _, geometry = self.compile()
        domains = {item["role"]:item for item in geometry["downstream_pa_instances"]}
        self.assertEqual(set(domains), {"flight_tube_shield","reflectron","detector"})
        tube, mirror, detector = (domains[role] for role in ("flight_tube_shield","reflectron","detector"))
        self.assertEqual((tube["x_mm"],tube["y_mm"],tube["az_deg"]), (7.,-9.,-90.))
        self.assertEqual((mirror["x_mm"],mirror["y_mm"],mirror["z_mm"],mirror["az_deg"]), (7.,-9.,600.,-90.))
        self.assertEqual((tube["nz"],mirror["nz"]),(1,1))
        self.assertEqual(mirror["grid_numerics"]["cell_axial_mm"],.25)
        self.assertEqual(mirror["grid_numerics"]["cell_radial_mm"],1.)
        self.assertEqual((detector["x_mm"],detector["y_mm"]),(40.,-41.))
        self.assertAlmostEqual(detector["z_mm"],12.35)
        self.assertEqual((detector["nx"],detector["ny"],detector["nz"]),(165,165,36))
        marker = detector["numerical_marker"]
        self.assertEqual(marker["active_plane_z_mm"],12.5)
        self.assertEqual(marker["capture_depth_mm"],.02)
        self.assertAlmostEqual(detector["z_mm"]+marker["back_margin_z_mm"]+marker["absorber_thickness_mm"],12.5)
        self.assertEqual(detector["scope"],"numerical_detector_marker__not_mechanical_detector")
        self.assertEqual({item["frame_id"] for item in domains.values()},{"oatof_global"})

    def test_stale_derived_instances_and_samples_do_not_move_current_domains(self):
        baseline_gem, baseline = self.compile()
        self.oatof["simion_instances"] = [dict(role="reflectron",x_mm=999.,nx=1)]
        self.oatof["field_sample_points_mm"] = dict(source_center=[999.,999.,999.])
        gem, actual = self.compile()
        self.assertEqual(gem,baseline_gem)
        self.assertEqual(actual,baseline)

    def test_wrong_pose_or_mismatched_declared_gap_is_rejected(self):
        for mutation in (
            lambda k: k['composition_plan']['recipe']["instances"][0]["transform"]["translation_mm"].__setitem__(0,-212.8),
            lambda k: k['composition_plan']['recipe']["instances"][1]["transform"]["translation_mm"].__setitem__(1,1),
            lambda k: k['composition_plan']['recipe']["instances"][0]["transform"].update(rotation=[[0,0,1],[0,1,0],[-1,0,0]]),
            lambda k: (k['composition_plan']['recipe']["connections"][0].update(gap_mm=1),
                       k['composition_plan']['recipe']["instances"][0]["transform"]["translation_mm"].__setitem__(0,-213.8)),
        ):
            original = copy.deepcopy(self.kw)
            mutation(self.kw)
            with self.assertRaises((ValueError, ContractError)):
                self.compile()
            self.kw = original

    def test_explicit_aperture_not_source_or_reference_hole(self):
        port=self.kw['composition_plan']['components']['oatof']['ports']['side_entry']
        port['cross_section'].update(width_mm=2.5,height_mm=6.)
        _, geometry = self.compile()
        interface = geometry["composition_plan"]["components"]["oatof"]["ports"]["side_entry"]
        self.assertEqual((interface["cross_section"]["width_mm"], interface["cross_section"]["height_mm"]), (2.5,6.))
        self.kw['composition_plan']['components']['oatof']['ports']['side_entry']['center_mm'][0] += .1
        with self.assertRaises((ValueError,ContractError)):
            self.compile()

    def test_electrode_collisions_missing_map_wrong_numerics_fail(self):
        for mutation in (
            lambda k: k['electrode_bindings']['oatof'].update(grounded_shield_id=3),
            lambda k: k['electrode_bindings']['oatof']["accelerator_ring_ids"].pop(),
            lambda k: k['electrode_bindings']['multipole'].pop(2),
            lambda k: k["numerical_domains"]["parent"]["cell_mm_xyz"].update(x=0),
            lambda k: k["numerical_domains"]["parent"]["pa_bounds_mm"].update(x_min=-180.),
            lambda k: k["numerical_domains"]["parent"]["pa_bounds_mm"].update(x_max=60.1),
        ):
            original = copy.deepcopy(self.kw)
            mutation(self.kw)
            with self.assertRaises(ValueError):
                self.compile()
            self.kw = original

    def test_distinct_providers_form_one_chain_with_explicit_rod_clearance(self):
        sources = [source_fixture(), multipole_source('hexapole'), multipole_source('quadrupole')]
        for count in (2, 3):
            names = [f'mp_{index}' for index in range(count)]
            kw = multi_inputs(sources[:count], self.oatof, names=names)
            gems, geometry = compile_frontend_geometry(dict(zip(names, sources[:count], strict=True)), self.oatof, **kw)
            self.assertNotIn(' within {', gems['parent'])
            self.assertIn(' within_inside_or_on {', gems['parent'])
            self.assertTrue(set(names) <= set(geometry['electrode_bindings']))
            self.assertEqual(gems['parent'].count('pa_define('), 1)
            self.assertEqual(len([row for row in geometry['composition_plan']['connection_checks']
                                  if row['connection_id'].startswith('chain_')]), count)
            bound = {value for name in names for value in geometry['electrode_bindings'][name].values()}
            self.assertTrue(bound.isdisjoint(set(geometry['electrode_bindings']['oatof']['accelerator_ring_ids'])))
            if count == 3:
                renamed = copy.deepcopy(kw)
                aliases = {name: f'renamed_{index}' for index, name in enumerate(names, 1)} | {'oatof': 'detector_body'}
                recipe = renamed['composition_plan']['recipe']
                for instance in recipe['instances']:
                    instance['instance_id'] = aliases[instance['instance_id']]
                for edge in recipe['connections']:
                    edge['upstream']['instance_id'] = aliases[edge['upstream']['instance_id']]
                    edge['downstream']['instance_id'] = aliases[edge['downstream']['instance_id']]
                renamed['composition_plan']['components'] = {aliases[key]: value for key, value in renamed['composition_plan']['components'].items()}
                renamed['electrode_bindings'] = {aliases[key]: value for key, value in renamed['electrode_bindings'].items()}
                renamed['composition_plan'] = compile_assembly_layout(recipe, renamed['composition_plan']['components'])
                renamed_sources = {aliases[key]: value for key, value in zip(names, sources[:count], strict=True)}
                renamed_gems, renamed_geometry = compile_frontend_geometry(renamed_sources, self.oatof, **renamed)
                self.assertEqual(gems['parent'], renamed_gems['parent'])
                self.assertEqual(geometry['accelerator_projection'], renamed_geometry['accelerator_projection'])

    def test_zero_gap_bare_rods_to_oa_are_rejected(self):
        source = multipole_source('octupole')
        kw = inputs(source, self.oatof)
        recipe = kw['composition_plan']['recipe']
        recipe['connections'][0]['gap_mm'] = 0.
        recipe['instances'][0]['transform']['translation_mm'][0] += 1.
        kw['composition_plan'] = compile_assembly_layout(recipe, kw['composition_plan']['components'])
        with self.assertRaisesRegex(ValueError, r'multipole rod electrode \d+ contacts oatof grounded_shield electrode'):
            compile_frontend_geometry({'multipole': source}, self.oatof, **kw)

    def test_zero_gap_bare_rods_with_independent_drives_are_rejected(self):
        sources = [multipole_source('quadrupole'), multipole_source('quadrupole')]
        names = ['q1', 'q2']
        kw = multi_inputs(sources, self.oatof, names=names, multipole_gap_mm=0.)
        with self.assertRaisesRegex(ValueError, r'q1 rod electrode \d+ contacts q2 rod electrode'):
            compile_frontend_geometry(dict(zip(names, sources, strict=True)), self.oatof, **kw)

    def test_zero_gap_distinct_size_rods_without_contact_are_allowed(self):
        sources = [quadrupole_source(r0=r0, dc=0., frequency_hz=1e6, phase_rad=0.) for r0 in (4.,10.)]
        names = ['small', 'large']
        kw = multi_inputs(sources, self.oatof, names=names, multipole_gap_mm=0.)
        gems, _ = compile_frontend_geometry(dict(zip(names,sources,strict=True)), self.oatof, **kw)
        self.assertIn('pa_define(',gems['parent'])

    def test_zero_gap_rods_are_compared_with_actual_shell_endcap_annulus(self):
        for aperture in (3.,10.):
            sources = [multipole_source('octupole'), source_fixture(entrance_aperture_radius_mm=aperture)]
            names = ['bare', 'housing']
            kw = multi_inputs(sources,self.oatof,names=names,multipole_gap_mm=0.)
            with self.subTest(aperture=aperture):
                if aperture == 3.:
                    with self.assertRaisesRegex(ValueError,r'bare rod electrode \d+ contacts housing entrance_endcap electrode'):
                        compile_frontend_geometry(dict(zip(names,sources,strict=True)),self.oatof,**kw)
                else:
                    gems, _ = compile_frontend_geometry(dict(zip(names,sources,strict=True)),self.oatof,**kw)
                    self.assertIn('pa_define(',gems['parent'])

    def test_zero_gap_rods_inside_real_large_oa_hole_are_allowed(self):
        source = multipole_source('octupole')
        kw = inputs(source,self.oatof)
        plan = kw['composition_plan']
        recipe = copy.deepcopy(plan['recipe'])
        components = copy.deepcopy(plan['components'])
        recipe['connections'][0]['gap_mm'] = 0.
        recipe['instances'][0]['transform']['translation_mm'][0] += 1.
        # This is an explicit different mechanical opening, clear of the rear plate.
        recipe['instances'][0]['transform']['translation_mm'][2] += 30.
        port = components['oatof']['ports']['side_entry']
        port['center_mm'][2] += 30.
        port['cross_section'].update(width_mm=40.,height_mm=40.)
        kw['composition_plan'] = compile_assembly_layout(recipe,components)
        gems, _ = compile_frontend_geometry({'multipole':source},self.oatof,**kw)
        self.assertIn('pa_define(',gems['parent'])

    def test_three_quadrupoles_keep_distinct_geometry_drive_and_rename_order_invariant(self):
        sources = [quadrupole_source(r0=r0, dc=dc, frequency_hz=freq, phase_rad=phase)
                   for r0, dc, freq, phase in ((4., 1., 1_000_000., .1), (4.5, 2., 1_100_000., .2), (5., 3., 1_200_000., .3))]
        names = ['q1', 'q2', 'q3']
        kw = multi_inputs(sources, self.oatof, names=names)
        gems, geometry = compile_frontend_geometry(dict(zip(names, sources, strict=True)), self.oatof, **kw)
        self.assertEqual([source['geometry_mm']['inscribed_radius_r0'] for source in sources], [4., 4.5, 5.])
        self.assertEqual([source['drive']['dc_amplitude_V_per_group'] for source in sources], [1., 2., 3.])
        self.assertEqual([source['drive']['frequency_Hz'] for source in sources], [1_000_000., 1_100_000., 1_200_000.])
        self.assertEqual([source['drive']['phase_rad'] for source in sources], [.1, .2, .3])
        self.assertEqual(len(gems['parent'].split('pa_define(')) - 1, 1)
        self.assertEqual(len(geometry['composition_plan']['connection_checks']), 3)

    def test_two_and_three_multipoles_share_one_fine_domain_without_changing_parent(self):
        sources = [multipole_source(project) for project in
                   ('octupole', 'hexapole', 'quadrupole')]
        for count in (2, 3):
            with self.subTest(count=count):
                names = [f'mp_{index}' for index in range(count)]
                providers = dict(zip(names, sources[:count], strict=True))
                kw = multi_inputs(sources[:count], self.oatof, names=names)
                kw['numerical_domains']['parent']['pa_bounds_mm']['x_min'] = -1000.
                kw['numerical_domains']['parent']['cell_mm_xyz']['x'] = .5
                baseline, geometry = compile_frontend_geometry(providers, self.oatof, **kw)
                fine = copy.deepcopy(kw['numerical_domains']['parent'])
                fine.update(cell_mm_xyz=dict(x=.25, y=.5, z=.05), guard_cells=1)
                repeller = self.oatof['accelerator_topology']['planes_global_z_mm']['repeller']
                fine['pa_bounds_mm'].update(x_max=-115., y_min=-40., y_max=40., z_max=repeller+40.)
                kw['numerical_domains']['entrance_refinement'] = fine
                gems, actual = compile_frontend_geometry(providers, self.oatof, **kw)
                self.assertEqual(gems['parent'], baseline['parent'])
                for key in ('composition_plan', 'electrode_bindings', 'accelerator_projection'):
                    self.assertEqual(actual[key], geometry[key])
                self.assertEqual(actual['numerical_domains']['parent'], geometry['numerical_domains']['parent'])
                self.assertEqual(gems['parent'].splitlines()[3:], gems['entrance_refinement'].splitlines()[3:])
                self.assertEqual(actual['numerical_domains']['entrance_refinement']['cell_mm_xyz'],
                                 dict(x=.25, y=.5, z=.05))
                fine['pa_bounds_mm']['x_min'] = -150.
                with self.assertRaisesRegex(ValueError, 'clip a provider physical envelope'):
                    compile_frontend_geometry(providers, self.oatof, **kw)

    def test_fine_active_window_contains_true_wall_slab_and_guard_not_whole_oa(self):
        from integrations.workflows.single_reflection_flight.geometry import _require_domain_contains
        accelerator = dict(shield_outer_width_mm=20., axis_x_mm=0., axis_y_mm=0.,
                           shield_back_z_mm=-10., grid2_z_mm=20., shield_wall_mm=2.)
        opening = dict(center_mm=[-10., 3., 4.], width_mm=4., height_mm=6.)
        box = dict(x_min=-10., x_max=-8., y_min=1., y_max=5., z_min=1., z_max=7.)
        _require_domain_contains(box, [], accelerator, entrance_opening=opening)
        with self.assertRaisesRegex(ValueError, 'clip a provider physical envelope'):
            _require_domain_contains(box, [], accelerator)
        for key, shift in (('x_min', .1), ('x_max', -.1), ('y_min', .1),
                           ('y_max', -.1), ('z_min', .1), ('z_max', -.1)):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'clip a provider physical envelope'):
                _require_domain_contains(dict(box, **{key: box[key]+shift}), [], accelerator,
                                         entrance_opening=opening)
        kw = inputs(self.source, self.oatof)
        fine = copy.deepcopy(kw['numerical_domains']['parent'])
        fine['guard_cells'] = 1
        # Raw coverage is valid but an oversized guard excludes physical metal.
        fine['cell_mm_xyz'] = dict(x=30., y=20., z=10.)
        fine['guard_cells'] = 2
        kw['numerical_domains']['entrance_refinement'] = fine
        with self.assertRaisesRegex(ValueError, 'clip a provider physical envelope'):
            compile_frontend_geometry({'multipole': self.source}, self.oatof, **kw)
