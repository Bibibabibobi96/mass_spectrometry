"""The installed SIMION compiler needs geometry, never a flight request/source."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from integrations.tests.test_single_reflection_zero_gap import direct_inputs, direct_source
from msplatform.backends.simion import CompiledSimionGeometry
from msplatform.backends.simion.compiler import compile_geometry
from msplatform.backends.simion.geometry import compile_frontend_geometry
from msplatform.backends.simion.resources import gem_template_path


def compiler_inputs(root):
    sources = {"multipole":direct_source(shell=True)}
    tof, options = direct_inputs(root, sources)
    assembly = dict(composition_plan=options["composition_plan"], components_resolved={**sources, "oatof":tof})
    numerics = dict(frontend_domains=options["numerical_domains"],
        geometry_build=copy.deepcopy(tof["simion_geometry_build"]),
        detector_marker=copy.deepcopy(tof["simion_detector_marker"]))
    # The old provider's field-sample convenience input is not a geometry dependency.
    del tof["particle_source"]
    return assembly, numerics, options


def independent_rf_inputs(request=None):
    """Build two real RF instances from package inputs, without a TOF placeholder."""
    from msplatform import assembly as assembly_api, components as component_api, examples as example_api
    from msplatform.contracts.rigid_transform import RigidTransform
    study = example_api.load_example('rf_oatof_functional_v1')
    request = study.component_requests['multipole'] if request is None else request
    parts = {name: component_api.resolve_component(request) for name in ('first', 'second')}
    registered = assembly_api.mate_ports(parts['first'].port('mechanical_exit'),
        parts['second'].port('mechanical_entrance'),
        rotation=[[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]], gap_mm=1.0)
    first_pose = RigidTransform(parts['first'].assembly_interface['local_frame_id'], 'rf_test_global',
        [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]], [0., 0., 0.])
    registered = registered.then(first_pose)
    recipe = dict(schema_version=1, role='assembly_recipe', integration_id='instrument_assembly',
        recipe_id='independent_rf_pair_test', assembly_frame_id='rf_test_global',
        position_tolerance_mm=1e-9, angular_tolerance_rad=1e-12,
        instances=[dict(instance_id='first', project_id='rf_multipole_ion_optics',
                        transform=RigidTransform(parts['first'].assembly_interface['local_frame_id'], 'rf_test_global',
                            [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]], [0., 0., 0.]).to_contract()),
                   dict(instance_id='second', project_id='rf_multipole_ion_optics', transform=registered.to_contract())],
        connections=[dict(connection_id='first_to_second', upstream=dict(instance_id='first', port_id='mechanical_exit'),
                          downstream=dict(instance_id='second', port_id='mechanical_entrance'), gap_mm=1.0,
                          coupling_mode='state_handoff')])
    instrument = assembly_api.assemble(recipe, parts)
    numerics = dict(component_domains={name:dict(cell_mm_xyz=dict(x=.2,y=.2,z=.1)) for name in parts})
    return instrument, numerics


class SimionGeometryCompilerTests(unittest.TestCase):
    def test_geometry_only_complete_specs_and_old_frontend_exact_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            assembly, numerics, options = compiler_inputs(Path(directory))
            original = copy.deepcopy((assembly, numerics))
            with patch("subprocess.Popen", side_effect=AssertionError("no native process")), \
                    patch.object(Path, "write_text", side_effect=AssertionError("no output writes")), \
                    patch.object(Path, "mkdir", side_effect=AssertionError("no run creation")):
                result = compile_geometry(assembly, numerics=numerics)
            self.assertIsInstance(result, CompiledSimionGeometry)
            self.assertEqual((assembly, numerics), original)
            self.assertEqual(set(result.frontend_gems), {"parent"})
            self.assertIn("pa_define(", result.frontend_gems["parent"])
            self.assertEqual([s["role"] for s in result.downstream_specs], ["flight_tube","reflectron","detector"])
            self.assertTrue(all(s["action"]=="gem2pa_only" for s in result.downstream_specs))
            self.assertTrue(all(s["template_context"]=="SIMION_GEM_Lua_global_var" for s in result.downstream_specs))
            for spec in result.downstream_specs:
                self.assertEqual(spec["template_text"].encode(), gem_template_path(spec["role"]).read_bytes())
                self.assertIn("pa_define(", spec["template_text"])
                self.assertNotIn("refine(", spec["template_text"])
                self.assertNotIn("fly(", spec["template_text"])
            self.assertEqual(set(result.downstream_specs[0]["template_variables"]), {"mmgu_axial","mmgu_radial","component"})
            detector = result.downstream_specs[2]["template_variables"]
            self.assertEqual(detector["radius"], assembly["components_resolved"]["oatof"]["geometry_mm"]["detector_radius"])
            # Expert transport of the same actual labels must reproduce old frontend text exactly.
            changed = copy.deepcopy(numerics)
            changed["electrode_group_native_ids"] = options["electrode_bindings"]
            result = compile_geometry(assembly, numerics=changed)
            legacy_gems, _ = compile_frontend_geometry(
                {"multipole":assembly["components_resolved"]["multipole"]}, assembly["components_resolved"]["oatof"], **options)
            self.assertEqual(result.frontend_gems, legacy_gems)
            for identity in result.provider_content_identities.values():
                self.assertEqual(set(identity), {"resolved_content_sha256", "component_interface_sha256"})
                self.assertTrue(all(len(value)==64 for value in identity.values()))

    def test_current_template_source_pins(self):
        expected = {
            "flight_tube": "55c4dd8e249ad3af532047f77b235c700eae47e15951a2828f1605dfc9841f1e",
            "reflectron": "6bc686c9a4827827dc45eef13590ea2ccdc578038a05f90d8132afbb00f7b2fb",
            "detector": "7c6212a9161745bc9319ac03a65edba1991109b6d8fb27cbee37823f95b386cd",
        }
        for role, digest in expected.items():
            with self.subTest(role=role):
                self.assertEqual(hashlib.sha256(gem_template_path(role).read_bytes()).hexdigest(), digest)

    def test_expert_native_map_and_geometry_contract_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            assembly, numerics, options = compiler_inputs(Path(directory))
            for bad in ("missing", "extra", "collision", "boolean", "capacity", "old_plan", "source"):
                changed, model = copy.deepcopy(numerics), copy.deepcopy(assembly)
                changed["electrode_group_native_ids"] = copy.deepcopy(options["electrode_bindings"])
                mapping = changed["electrode_group_native_ids"]["multipole"]
                keys = list(mapping)
                if bad == "missing": mapping.pop(keys[0])
                elif bad == "extra": mapping["not_a_scientific_group"] = 999
                elif bad == "collision": mapping[keys[0]] = mapping[keys[1]]
                elif bad == "boolean": mapping[keys[0]] = True
                elif bad == "capacity": mapping[keys[0]] = 1001
                elif bad == "old_plan": model["composition_plan"]["schema_version"] = 3
                else: model["source"] = dict(particle_count=1)
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    compile_geometry(model, numerics=changed)

    def test_numerical_marker_cannot_change_the_physical_detector(self):
        with tempfile.TemporaryDirectory() as directory:
            assembly, numerics, _ = compiler_inputs(Path(directory))
            numerics["detector_marker"]["active_radius_mm"] += 1.
            with self.assertRaisesRegex(ValueError, "physical detector"):
                compile_geometry(assembly, numerics=numerics)

    def test_mechanical_plan_cannot_reauthorize_a_changed_gap_or_check(self):
        with tempfile.TemporaryDirectory() as directory:
            assembly, numerics, _ = compiler_inputs(Path(directory))
            for kind in ("gap", "checks"):
                changed = copy.deepcopy(assembly)
                plan = changed["composition_plan"]
                if kind == "gap":
                    plan["recipe"]["connections"][0]["gap_mm"] = 1.
                else:
                    plan["connection_checks"] = []
                before = copy.deepcopy(changed)
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    compile_geometry(changed, numerics=numerics)
                self.assertEqual(changed, before)


    def test_public_independent_rf_pair_and_local_scope_compile_without_tof_or_native(self):
        from msplatform import assembly as assembly_api
        from msplatform.backends import simion as simion_api
        instrument, numerics = independent_rf_inputs()
        before = copy.deepcopy((instrument, numerics))
        with patch('subprocess.Popen', side_effect=AssertionError('no native process')), \
                patch.object(Path, 'write_text', side_effect=AssertionError('no output writes')), \
                patch.object(Path, 'mkdir', side_effect=AssertionError('no run creation')):
            result = simion_api.compile_geometry(instrument, numerics=numerics)
        self.assertEqual(set(result.frontend_gems), {'first', 'second'})
        self.assertEqual(result.downstream_specs, ())
        self.assertEqual(result.frontend_geometry['role'], 'simion_independent_rf_geometry')
        self.assertEqual(set(result.components_resolved), {'first', 'second'})
        self.assertIn('pa_define(', result.frontend_gems['first'])
        self.assertIn('parent_resolved_sha256=' + instrument.components_resolved['first']['resolved_sha256'],
                      result.frontend_gems['first'])
        self.assertNotIn('flight_tube', result.frontend_gems['first'])
        self.assertEqual(result.provider_content_identities.keys(), {'first', 'second'})
        self.assertEqual((instrument, numerics), before)
        local = assembly_api.assemble(instrument.composition_plan['recipe'], instrument.components,
            local_scope=dict(instance_ids=['second'], research_scope='second independent RF only',
                             boundary_assumptions='retain complete RF parent'))
        selected = simion_api.compile_geometry(local, numerics=dict(component_domains={
            'second': numerics['component_domains']['second']}))
        self.assertEqual(set(selected.frontend_gems), {'second'})
        self.assertEqual(set(selected.components_resolved), {'first', 'second'})

    def test_independent_rf_numerics_mapping_and_native_build_fail_closed(self):
        from msplatform.backends import simion as simion_api
        instrument, numerics = independent_rf_inputs()
        for bad in ({}, {'component_domains': {}},
                    {'component_domains': numerics['component_domains'], 'electrode_group_native_ids': {'unknown': {}}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                simion_api.compile_geometry(instrument, numerics=bad)
        changed = copy.deepcopy(numerics)
        mapping = simion_api.compile_geometry(instrument, numerics=numerics).frontend_geometry['electrode_bindings']['first']
        group = next(iter(mapping))
        changed['electrode_group_native_ids'] = {'first': dict(mapping, **{group: max(mapping.values()) + 1})}
        remapped = simion_api.compile_geometry(instrument, numerics=changed)
        self.assertNotEqual(remapped.frontend_gems['first'],
                            simion_api.compile_geometry(instrument, numerics=numerics).frontend_gems['first'])
        with self.assertRaisesRegex(ValueError, 'explicit available SIMION executable'):
            simion_api.build_geometry(remapped, context=None)


    def test_independent_rf_four_six_eight_poles_share_one_compiler(self):
        from msplatform import examples as example_api
        from msplatform.backends import simion as simion_api
        original = example_api.load_example('rf_oatof_functional_v1').component_requests['multipole']
        for variant, order, count in (('quadrupole', 2, 4), ('hexapole', 3, 6), ('octupole', 4, 8)):
            with self.subTest(variant=variant):
                request = copy.deepcopy(original)
                request['design']['identity'].update(radial_order_n=order, electrode_count=count)
                instrument, numerics = independent_rf_inputs(request)
                result = simion_api.compile_geometry(instrument, numerics=numerics)
                design = result.components_resolved['first']
                self.assertEqual(len(design['geometry_mm']['rod_array']['rods']), count)
                self.assertEqual(design['identity']['radial_order_n'], order)
                self.assertIn('pa_define(', result.frontend_gems['first'])


if __name__ == "__main__":
    unittest.main()
