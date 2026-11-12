"""Shared actual OA/TOF mechanical paths; pure software geometry only."""
import copy
import unittest

from msplatform.backends.simion.accelerator_renderer import render_accelerator_local_geometry
from msplatform.backends.simion.bare_frontend_geometry import _canonical_three_zone_component
from msplatform.components.orthogonal_accelerator.assembly_interface import build_assembly_interface
from msplatform.components.orthogonal_accelerator.geometry_members import iter_geometry_members
from msplatform.components.orthogonal_accelerator.sectioned_geometry import resolve_bare_three_zone_component, project_instrument_sectioned_mechanics
from msplatform.components.single_reflection_oa_tof.accelerator_geometry import resolve_oa_provider
from projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.test_assembly_interface import candidate_300mm_fixture, projected_candidate


def request(geometry):
    return dict(schema_version=1,role='orthogonal_accelerator_bare_three_zone_requirements',
                variant_id='three_zone',geometry=copy.deepcopy(geometry))


def source(geometry):
    return dict(schema_version=1,role='oatof_validated_sectioned_accelerator_geometry',
                producer='any_explicit_source',frame_id='oatof_global',geometry=copy.deepcopy(geometry))


class SharedOAPhysicalPolicyTests(unittest.TestCase):
    def test_real_tof_and_standalone_physical_body_gem_and_cad_members_match(self):
        tof=resolve_oa_provider(candidate_300mm_fixture(),projection=projected_candidate(),geometry_profile_id=None)
        geometry=tof['source']['geometry']; before=copy.deepcopy(geometry)
        standalone=resolve_bare_three_zone_component(request(geometry)); instrument=tof['mechanical']
        for key,value in standalone.items():
            if key!='role': self.assertEqual(value,instrument[key],key)
        self.assertEqual(iter_geometry_members(standalone),iter_geometry_members(instrument))
        ids={'grounded_shield_id':71,'accelerator_repeller_id':72,'accelerator_grid1_id':73,
             'accelerator_intermediate2_id':74,'accelerator_grid2_id':75,
             'accelerator_ring_ids':list(range(80,80+geometry['ring_count']))}
        def gem(value):
            return render_accelerator_local_geometry(value['geometry'],cell_x_mm=.25,cell_z_mm=.1,
                                                     electrodes=ids,render_intermediate2_sheet=True)
        self.assertEqual(gem(standalone),gem(instrument))
        # This physical port touches the first-gap plane; TOF may use it but
        # a standalone first-gap port/study must reject it.
        with self.assertRaisesRegex(ValueError,'first gap'):
            build_assembly_interface(standalone,geometry_profile_id=None)
        component=dict(schema_version=1,role='rf_oatof_accelerator_component',variant_id='three_zone',
            geometry_profile_id='explicit',requirements=request(geometry),
            transform=dict(rotation=[[1,0,0],[0,1,0],[0,0,1]],translation_mm=[0,0,0]),
            local_electrode_ids={},electrode_voltages_v={},pulse_voltage_policy_id='explicit')
        with self.assertRaisesRegex(ValueError,'first gap'):
            _canonical_three_zone_component(component,cells={'x':.25,'y':.25,'z':.1},target_solver_frame=None)
        self.assertEqual(geometry,before)

    def test_shared_perturbations_and_instance_isolation(self):
        g=resolve_oa_provider(candidate_300mm_fixture(),projection=projected_candidate(),geometry_profile_id=None)['source']['geometry']
        baseline=resolve_bare_three_zone_component(request(g)); original=copy.deepcopy(baseline)
        for key,delta in (('axis_y_mm',.125),('port_center_y_mm',.125),('numerical_port_width_mm',.125),('ring_thickness_mm',.05)):
            changed=copy.deepcopy(g); changed[key]+=delta
            standalone=resolve_bare_three_zone_component(request(changed))
            instrument=project_instrument_sectioned_mechanics(source(changed))
            for field,value in standalone.items():
                if field!='role': self.assertEqual(value,instrument[field],field)
            self.assertNotEqual(standalone['geometry'],baseline['geometry'])
            self.assertEqual(iter_geometry_members(standalone),iter_geometry_members(instrument))
            self.assertEqual(baseline,original)

    def test_physical_boundaries_and_nonfinite_are_shared(self):
        g=resolve_oa_provider(candidate_300mm_fixture(),projection=projected_candidate(),geometry_profile_id=None)['source']['geometry']
        for change in ({'port_center_y_mm':1e6},{'port_center_z_mm':g['shield_back_z_mm']},
                       {'numerical_port_width_mm':float('nan')},{'shield_wall_mm':0.},
                       {'negative_x_face_mm':0.},{'ring_z_mm':[g['grid1_z_mm']]*g['ring_count']}):
            bad=copy.deepcopy(g);bad.update(change)
            with self.subTest(change=change):
                with self.assertRaises(ValueError): resolve_bare_three_zone_component(request(bad))
                with self.assertRaises(ValueError): project_instrument_sectioned_mechanics(source(bad))


if __name__=='__main__': unittest.main()
