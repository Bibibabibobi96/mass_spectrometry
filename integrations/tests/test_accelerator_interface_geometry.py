"""Actual IP/MR mechanical plan consumption and pre-migration CSG vectors."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import copy
from common.integration.resolve_assembly import compile_assembly_layout, derive_assembly_scope
from common.contracts.write_run_manifest import file_record
from common.contracts.rigid_transform import RigidTransform
from integrations.workflows.accelerator_interface import geometry
from integrations.tests import test_multipole_ip_prepare as multipole_tests
from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis import test_ion_processor_assembly as assembly_tests


class AcceleratorGeometryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = assembly_tests.AssemblyTests("test_seed_target_geometry_and_oa_removed")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_whole_parent_motion_keeps_joint_geometry_and_gems_provider_local(self):
        expected = None
        for rotation in ([[1,0,0],[0,1,0],[0,0,1]], [[0,-1,0],[1,0,0],[0,0,1]]):
            fixture = assembly_tests.AssemblyTests("test_seed_target_geometry_and_oa_removed")
            fixture.setUp()
            self.addCleanup(fixture.doCleanups)
            parent = fixture.request["composition_plan"]
            original = copy.deepcopy(parent)
            local_registration = copy.deepcopy(parent["recipe"]["instances"][0]["transform"])
            source_bytes = json.dumps(fixture.source)
            fixture.prepare()
            names = ("parent/assembly.gem", "collision.gem", "ion_processor_seed/processor.gem", "detector.gem", "assembly_geometry.json")
            before = {name: (fixture.root / "output" / name).read_bytes() for name in names}
            if expected is None:
                expected = before
            self.assertEqual(before, expected)
            recipe = copy.deepcopy(parent["recipe"])
            movement = RigidTransform.from_contract(dict(schema_version=1, role="rigid_transform",
                from_frame_id=recipe["assembly_frame_id"], to_frame_id="instrument.assembly",
                rotation=rotation, translation_mm=[32,-16,8]))
            recipe["assembly_frame_id"] = movement.to_frame_id
            for item in recipe["instances"]:
                item["transform"] = RigidTransform.from_contract(item["transform"]).then(movement).to_contract()
            moved = compile_assembly_layout(recipe, parent["components"])
            fixture.request["composition_plan"] = moved
            shutil.rmtree(fixture.root / "output")
            report = fixture.prepare()
            self.assertEqual(report["assembly_coordinate_transform"], local_registration)
            self.assertEqual({name: (fixture.root / "output" / name).read_bytes() for name in names}, before)
            self.assertEqual(json.dumps(fixture.source), source_bytes)
            self.assertEqual(parent, original)
            self.assertEqual(moved["recipe"], recipe)

    def test_one_three_component_parent_drives_both_local_preparations(self):
        multipole = multipole_tests.MultipoleIPPreparationTests('test_one_pose_preserves_sparse_ids_species_birth_arrival_and_unknown_terminal')
        multipole.setUp()
        self.addCleanup(multipole.doCleanups)
        multipole.execute()
        source_run = multipole.run
        self.fixture.prepare()
        expected_gems = {name: (self.fixture.root / 'output' / name).read_bytes() for name in (
            'parent/assembly.gem', 'collision.gem', 'ion_processor_seed/processor.gem', 'detector.gem')}
        joint = assembly_tests.AssemblyTests('test_seed_target_geometry_and_oa_removed')
        joint.setUp()
        self.addCleanup(joint.doCleanups)
        parent = copy.deepcopy(joint.request['composition_plan'])
        ip, mr = parent['recipe']['instances']
        old_ip = ip['instance_id']
        ip['instance_id'] = 'ion_processor'
        self.assertEqual(parent['components'][old_ip], multipole.parent['components']['ion_processor'])
        guide = copy.deepcopy(multipole.parent['recipe']['instances'][0])
        guide['transform'] = RigidTransform.from_contract(guide['transform']).then(
            RigidTransform.from_contract(ip['transform'])).to_contract()
        recipe = parent['recipe']
        recipe['recipe_id'] = 'multipole_ip_mr_shared_parent'
        recipe['instances'] = [guide, ip, mr]
        recipe['connections'][0]['upstream']['instance_id'] = 'ion_processor'
        recipe['connections'].append(copy.deepcopy(multipole.parent['recipe']['connections'][0]))
        full = compile_assembly_layout(recipe, dict(
            multipole=multipole.parent['components']['multipole'],
            ion_processor=parent['components'][old_ip],
            **{mr['instance_id']: parent['components'][mr['instance_id']]}))
        multipole.parent = full
        multipole.request['local_scope'] = dict(instance_ids=['multipole', 'ion_processor'],
            research_scope='upstream measured state handoff', boundary_assumptions='MR excluded from IP-native injection')
        multipole.run = multipole.root / 'three_component_parent'
        (multipole.run / 'inputs').mkdir(parents=True)
        multipole.execute()
        for name in ('source_states.csv', 'mother_fates.csv', 'mother_census.json'):
            self.assertEqual((multipole.run / 'results/multipole_ip' / name).read_bytes(),
                             (source_run / 'results/multipole_ip' / name).read_bytes())
        for name in ('clock_authority.json', 'instrument_epoch.json'):
            self.assertEqual((multipole.run / 'inputs' / name).read_bytes(), (source_run / 'inputs' / name).read_bytes())
        joint.request['composition_plan'] = derive_assembly_scope(full, local_scope=dict(
            instance_ids=['ion_processor', mr['instance_id']], research_scope='downstream joint field',
            boundary_assumptions='upstream recorded source; multipole metal excluded from this numerical domain'))
        joint.prepare()
        for name, expected in expected_gems.items():
            self.assertEqual((joint.root / 'output' / name).read_bytes(), expected)
        self.assertEqual(joint.request['composition_plan']['recipe'], full['recipe'])
        self.assertEqual(json.loads((multipole.run / 'inputs/parent_composition_plan.json').read_text()), full)

    def test_other_port_and_electrical_group_drift_are_rejected(self):
        original = copy.deepcopy(self.fixture.request['composition_plan'])
        for change in ('guide_port', 'electrical_group'):
            with self.subTest(change=change):
                parent = copy.deepcopy(original)
                interface = parent['components']['ip_exit_shield']
                if change == 'guide_port':
                    interface['ports']['guide_inlet']['center_mm'][0] += 1.
                else:
                    interface['component_electrodes'][0]['electrical_group_id'] += 1
                self.fixture.request['composition_plan'] = compile_assembly_layout(parent['recipe'], parent['components'])
                with self.assertRaisesRegex(ValueError, 'resolved mechanical interface differs'):
                    self.fixture.prepare()
                self.assertFalse((self.fixture.root / 'output').exists())

    def test_larger_parent_keeps_selected_joint_gems_and_rejects_unsupported_full_scope(self):
        reference = None
        for count in (2, 3, 4):
            with self.subTest(parent_instances=count):
                fixture = assembly_tests.AssemblyTests('test_seed_target_geometry_and_oa_removed')
                fixture.setUp()
                self.addCleanup(fixture.doCleanups)
                parent = fixture.request['composition_plan']
                selected = list(parent['scope']['instance_ids'])
                for number in range(2, count):
                    instance = copy.deepcopy(parent['recipe']['instances'][0])
                    instance['instance_id'] = f'extra_{number}'
                    instance['transform']['translation_mm'][1] -= number * 1000
                    parent['recipe']['instances'].append(instance)
                    parent['components'][instance['instance_id']] = copy.deepcopy(parent['components'][selected[0]])
                parent = compile_assembly_layout(parent['recipe'], parent['components'])
                declaration = dict(instance_ids=selected, research_scope='IP/MR pair',
                    boundary_assumptions='Additional upstream metal excluded explicitly')
                fixture.request['composition_plan'] = derive_assembly_scope(parent, local_scope=declaration)
                fixture.prepare()
                actual = tuple((fixture.root/'output'/name).read_bytes() for name in (
                    'parent/assembly.gem', 'collision.gem', 'ion_processor_seed/processor.gem', 'detector.gem'))
                if reference is None:
                    reference = actual
                self.assertEqual(actual, reference)
                if count > 2:
                    from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff import resolve_ip_mr_connection
                    with self.assertRaisesRegex(ValueError, 'selected scope'):
                        resolve_ip_mr_connection(parent)

    def test_plan_gates_publication_and_retains_original_gem_bytes(self):
        fixture = self.fixture
        original_compiler = geometry.ip_interface
        def compile_before_write(projection):
            self.assertFalse((fixture.root / "output").exists())
            return original_compiler(projection)
        with patch.object(geometry, "ip_interface", side_effect=compile_before_write) as compiler:
            report = fixture.prepare()
        compiler.assert_called_once()
        plan = report["composition_plan"]
        check = plan["connection_checks"][0]
        self.assertEqual(check["upstream_center_mm"][:2], [0, -55])
        self.assertAlmostEqual(check["upstream_center_mm"][2], 6.3)
        self.assertAlmostEqual(check["downstream_center_mm"][2], 5.3)
        self.assertEqual(check["gap_mm"], 1)
        self.assertEqual([i["instance_id"] for i in plan["recipe"]["instances"]], ["ip_exit_shield", "mr_entry_frame"])
        self.assertEqual(report["assembly_coordinate_transform"], plan["recipe"]["instances"][0]["transform"])
        self.assertNotIn("namespace_map", report)
        self.assertNotIn("ion_processor_instance_id", json.loads(Path(report["assembly_geometry_path"]).read_text()))
        # Captured before moving the real materializer; includes every conductor,
        # voltage, numerical boundary, and independently rendered provider seed.
        expected = {
            "parent/assembly.gem": "b15310d8960c9e288d848315917a07e5414114234020cff9d0a8ede23554a691",
            "collision.gem": "52bbd4a4985878a29777182aa599c22577d342d5f5bc01d75e5dfdc0bd9e45d9",
            "ion_processor_seed/processor.gem": "f96a5284b324f84d66f536b99cdb03cb1ea726e45ef8ddf8502c208bb8889a9a",
            "detector.gem": "8956f768dc716a32c3d163b930d41924fd174abf91748b9fb04a6a1c50331b68",
        }
        for relative, digest in expected.items():
            self.assertEqual(hashlib.sha256((fixture.root / "output" / relative).read_bytes()).hexdigest(), digest, relative)

    def test_renamed_instances_reach_the_same_actual_geometry(self):
        recipe = self.fixture.request["composition_plan"]["recipe"]
        for instance, name in zip(recipe["instances"], ("processor_a", "analyzer_b")):
            instance["instance_id"] = name
        recipe["connections"][0]["upstream"]["instance_id"] = "processor_a"
        recipe["connections"][0]["downstream"]["instance_id"] = "analyzer_b"
        self.fixture.rebuild_parent()
        report = self.fixture.prepare()
        self.assertEqual([row["instance_id"] for row in report["composition_plan"]["recipe"]["instances"]],
                         ["processor_a", "analyzer_b"])
        self.assertNotIn("ion_processor_instance_id", json.loads(Path(report["assembly_geometry_path"]).read_text()))
        self.assertEqual(hashlib.sha256((self.fixture.root / "output/parent/assembly.gem").read_bytes()).hexdigest(),
                         "b15310d8960c9e288d848315917a07e5414114234020cff9d0a8ede23554a691")

    def test_nonzero_declared_translation_reaches_real_csg_once(self):
        fixture = self.fixture
        fixture.request["composition_plan"]["recipe"]["instances"][0]["transform"]["translation_mm"][0] = 1
        for shield in fixture.geometry["prism_ground_shields"]:
            shield["x"] = [v + 1 for v in shield["x"]]
            for body in shield["body_sections"]:
                body["x"] = [v + 1 for v in body["x"]]
            for slot in shield["rectangular_slots_mm"]:
                slot[0] += 1
                slot[3] += 1
        record = fixture.request["field_assembly_reference"]["geometry_authority"]
        path = Path(record["path"])
        path.write_text(json.dumps(fixture.geometry))
        fixture.request["field_assembly_reference"]["geometry_authority"] = file_record(path)
        fixture.rebuild_parent()
        report = fixture.prepare()
        check = report["composition_plan"]["connection_checks"][0]
        self.assertEqual(check["upstream_center_mm"][:2], [1, -55])
        self.assertEqual(check["downstream_center_mm"][:2], [1, -55])
        actual = json.loads(Path(report["assembly_geometry_path"]).read_text())
        shield = next(e for e in actual["ion_processor_electrodes"] if e["electrode_id"] == 14)
        self.assertEqual(shield["cutouts"][0]["min_mm"][:2], [.6, -59])
        self.assertEqual(shield["cutouts"][0]["max_mm"][:2], [1.4, -51])
        # The rendered joint CSG consumes these same globally registered solids.
        self.assertIn("centered_box3D(1,-64.25,6.55,7,60.5,0.5)", Path(report["parent_gem_path"]).read_text())

    def test_wrong_mechanical_face_fails_before_any_geometry_or_seed_output(self):
        actual = geometry.ip_interface
        def wrong_face(projection):
            interface = actual(projection)
            interface["ports"]["extraction_exit"]["center_mm"][1] -= .25
            return interface
        with patch.object(geometry, "ip_interface", side_effect=wrong_face):
            with self.assertRaisesRegex(ValueError, "resolved mechanical interface differs"):
                self.fixture.prepare()
        self.assertFalse((self.fixture.root / "output").exists())

    def test_larger_recipe_gap_changes_p1_only_and_keeps_lp_minimum(self):
        fixture = self.fixture
        fixture.request["composition_plan"]["recipe"]["connections"][0]["gap_mm"] = 2
        fixture.rebuild_parent()
        report = fixture.prepare()
        self.assertEqual(report["composition_plan"]["connection_checks"][0]["gap_mm"], 2)
        self.assertEqual(report["geometry_changes"]["lp_length_after_mm"], 61.5)
        self.assertEqual(report["geometry_changes"]["clearance_mm"], 1)
        self.assertEqual(report["geometry_changes"]["extraction_gap_mm"], 2)
        self.assertAlmostEqual(report["geometry_changes"]["p1_extension_end_after_z_mm"], 4.3)
        self.assertEqual(hashlib.sha256((fixture.root / "output/ion_processor_seed/processor.gem").read_bytes()).hexdigest(),
                         "f96a5284b324f84d66f536b99cdb03cb1ea726e45ef8ddf8502c208bb8889a9a")

    def test_unsupported_coupling_or_gap_below_minimum_has_no_output(self):
        for mutation in ("gap", "coupling", "orientation"):
            with self.subTest(mutation=mutation):
                recipe = self.fixture.request["composition_plan"]["recipe"]
                edge = recipe["connections"][0]
                edge["gap_mm"] = .5 if mutation == "gap" else 1
                edge["coupling_mode"] = "state_handoff" if mutation == "coupling" else "monolithic_joint_solve"
                recipe["instances"][0]["transform"]["rotation"] = ([[1,0,0],[0,1,0],[0,0,1]] if mutation == "orientation"
                    else [[0,0,-1],[1,0,0],[0,-1,0]])
                with self.assertRaisesRegex(ValueError, "minimum clearance|monolithic_joint_solve|supported native orientation"):
                    self.fixture.prepare()
                self.assertFalse((self.fixture.root / "output").exists())

    def test_frozen_snapshot_materializes_actual_mechanical_plan_without_repository(self):
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        repo = Path(__file__).resolve().parents[2]
        fixture = self.fixture
        paths = [fixture.write(name + ".json", value) for name, value in
                 (("source", fixture.source), ("trajectory", fixture.trajectory), ("request", fixture.request))]
        inputs = fixture.root / "inputs"
        inputs.mkdir()
        command = f"""
. '{repo / 'integrations/runtime/dependencies.ps1'}'
$path='{repo / 'integrations/config/runtime_dependencies.json'}'
$null=Freeze-ConsumerDependencies -RepoRoot '{repo}' -ContractPath $path -InputDir '{inputs}' -OwnerId instrument_assembly -ConsumerId accelerator_interface
"""
        frozen = subprocess.run([pwsh, "-NoProfile", "-Command", command], cwd=repo,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(frozen.returncode, 0, frozen.stdout + frozen.stderr)
        program = """
import json, sys
from pathlib import Path
from unittest.mock import patch
from integrations.workflows.accelerator_interface.geometry import prepare_ion_processor_assembly
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff import resolve_ip_mr_connection
paths = list(map(Path, sys.argv[1:4]))
values = [json.loads(path.read_text()) for path in paths]
# Independent fixture supplies minimal MR conductors; only its renderer is stubbed.
with patch('projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_assembly._analyzer_geometry_lines', return_value=['e(2) { box3d(1,2,3,4,5,6) }']):
    prepare_ion_processor_assembly(*values, connection=resolve_ip_mr_connection(values[2]["composition_plan"]), input_paths=paths, output_directory=Path(sys.argv[4]))
"""
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        output = fixture.root / "detached"
        completed = subprocess.run([sys.executable, "-B", "-s", "-c", program, *map(str, paths), str(output)],
            cwd=inputs / "runtime_snapshot", env=environment, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        report = json.loads((output / "assembly_preparation.json").read_text())
        self.assertEqual(report["composition_plan"]["connection_checks"][0]["gap_mm"], 1)
        self.assertEqual(hashlib.sha256((output / "parent/assembly.gem").read_bytes()).hexdigest(),
                         "b15310d8960c9e288d848315917a07e5414114234020cff9d0a8ede23554a691")
