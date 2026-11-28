from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from queue import Empty, Queue
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHANGED_GATE = REPO_ROOT / "tools/repository" / "verify.ps1"
ROUTE_TABLE = REPO_ROOT / "tools/repository" / "gate_catalog.json"
PARALLEL_GATE_SUPPORT = REPO_ROOT / "tools/repository" / "parallel_gate_support.ps1"
LIGHTWEIGHT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "lightweight-gate.yml"
FROZEN_INPUT_CONTRACT_TESTS = {
    "tests/contracts/" + name for name in (
        "test_batch_processes.py", "test_execution_accounting_hold.py",
        "test_execution_runtime.py", "test_frozen_inputs.py",
        "test_immutable_input_process.py", "test_installed_scientific_core.py",
        "test_process_family_identity.py", "test_python_dependency_contract.py",
        "test_scientific_core_boundaries.py",
        "test_execution_module_sources.py", "test_dual_cone_iob.py",
        "test_canonical_rf_free_assembly.py",
        "test_generic_dynamic_model.py", "test_generic_scalar_binding.py",
        "test_generic_scalar_derived_tracking_managed.py", "test_generic_scalar_managed.py",
        "test_generic_scalar_tracking_managed.py", "test_generic_scalar_tracking_recovery.py",
        "test_generic_scalar_tracking_renamed.py", "test_neutral_sampled_iob.py",
        "test_neutral_sampled_renamed_managed.py", "test_scalar_pa_reinit.py",
        "test_sfi_scalar_binding.py", "test_simion_tracking_units.py", "test_static_world_model.py",
    )
} - {"tests/contracts/test_dual_cone_iob.py"} | {
    "tests/components/dual_cone_tandem_quadrupole/test_dual_cone_iob.py",
}


def contract_test_path(value: str) -> str:
    if value.startswith("tests."):
        return "tests/" + value.removeprefix("tests.").replace(".", "/") + ".py"
    return value


class ChangedGateContractTests(unittest.TestCase):
    def test_scalar_windows_select_admission_program_and_owner_consumers(self):
        required = {
            'tests.contracts.test_sfi_scalar_refinement',
            'tests.contracts.test_ip_mr_scalar_windows',
            'tests.contracts.test_ip_mr_tracking_program',
        }
        for name in ('scalar_sample_binding', 'sfi_scalar_binding', 'ip_mr_scalar_binding',
                     'tracking_program', 'rf_tracking_program', 'tracking_execution', 'operations'):
            with self.subTest(path=name):
                request, _ = self.plan('-ChangedPath', 'src/msplatform/backends/simion/' + name + '.py')
                modules = [value.removesuffix('.py').replace('/', '.')
                           for row in request['stages']
                           if row['selected'] and row['name'].startswith('machine_contracts')
                           for value in row['command']['arguments'][2:]]
                for module in required:
                    self.assertEqual(modules.count(module), 1)

    def test_stationary_workpoint_selects_actual_contract_and_recovery(self):
        prefix = "src/msplatform/backends/comsol/"
        required = {
            "tests.contracts.test_comsol_assembly_field_solution",
            "tests.contracts.test_comsol_stationary_recovery_managed",
        }
        for path in ("assembly_field_solution.py", "resources.py",
                     "matlab/solve_assembly_stationary.m", "matlab/assembly_mesh_identity.m"):
            with self.subTest(path=path):
                request, _ = self.plan("-ChangedPath", prefix + path)
                modules = [value.removesuffix(".py").replace("/", ".")
                           for row in request["stages"]
                           if row["selected"] and row["name"].startswith("machine_contracts")
                           for value in row["command"]["arguments"][2:]]
                self.assertTrue(required <= set(modules))
                for module in required:
                    self.assertEqual(modules.count(module), 1)

    def test_rf_batch_continuation_selects_actual_consumers_and_installation(self):
        request, _ = self.plan('-ChangedPath', 'src/msplatform/workflows/rf_batch_continuation.py')
        selected = [row for row in request['stages'] if row['selected']]
        domain = next(row for row in selected if row['name'] == 'rf_multipole_domain_tests')
        self.assertEqual(domain['command']['arguments'][:2], ['-m', 'tools.repository.gate_unittest'])
        modules = [value.removesuffix('.py').replace('/', '.')
                   for value in domain['command']['arguments'][2:]]
        self.assertCountEqual(modules, [
            'tests.components.rf_multipole_ion_optics.domain.test_simion_batch_continuation',
            'tests.components.rf_multipole_ion_optics.domain.test_simion_field_checkpoint',
            'tests.components.rf_multipole_ion_optics.domain.test_simion_runner_contract',
        ])
        self.assertEqual(len(modules), len(set(modules)))
        common = {value.removesuffix('.py').replace('/', '.') for row in selected
                  if row['name'].startswith('machine_contracts')
                  for value in row['command']['arguments'][2:]}
        self.assertIn('tests.contracts.test_installed_scientific_core', common)

    def test_detector_pipeline_preserves_owner_core_routes(self):
        backend = "src/msplatform/backends/simion/"
        workflow = "src/msplatform/backends/simion/downstream_fields.py"
        for path in (backend + "downstream.py", backend + "resources/oatof_detector_ground.gem",
                     backend + "resources/build_detector_variant.lua", workflow):
            with self.subTest(path=path):
                request, _ = self.plan("-ChangedPath", path)
                selected = [row for row in request["stages"] if row["selected"]]
                common = {value.removesuffix(".py").replace("/", ".")
                          for row in selected if row["name"].startswith("machine_contracts")
                          for value in row["command"]["arguments"][2:]}
                self.assertIn("tests.contracts.test_installed_scientific_core", common)
                if path != workflow:
                    self.assertIn("tests.contracts.test_detector_physical_projection", common)
                self.assertTrue(any(row["name"].startswith("instrument_assembly") for row in selected))
                if path != workflow:
                    self.assertTrue(any(row["name"].startswith("single_reflection_oa_tof_mass_analyzer_static") for row in selected))

    def test_ip_preparation_selects_both_actual_integration_consumers(self):
        request, _ = self.plan('-ChangedPath', 'src/msplatform/workflows/ion_processor/preparation.py')
        selected = [row for row in request['stages'] if row['selected']]
        modules = [module for row in selected
                   if row['name'].startswith('instrument_assembly')
                   for module in row['command']['parameters'].get('SelectedTestModules', [])]
        self.assertCountEqual(modules, [
            'tests.components.ion_processor.test_upstream_admission',
            'tests.assembly.accelerator_interface.test_accelerator_interface',
            'tests.execution.test_dependencies',
        ])
        self.assertEqual(len(modules), len(set(modules)))
        self.assertTrue(any(row['name'] == 'ion_processor_static' for row in selected))
        common = {value.removesuffix('.py').replace('/', '.') for row in selected
                  if row['name'].startswith('machine_contracts') for value in row['command']['arguments'][2:]}
        self.assertIn('tests.contracts.test_installed_scientific_core', common)

    def test_shared_oa_physical_consumers_select_the_actual_oa_stage(self):
        for path in (
            'tests/assembly/single_reflection_oa_tof_mass_analyzer/analysis/test_assembly_interface.py',
            'src/msplatform/components/single_reflection_oa_tof/accelerator_geometry.py',
            'src/msplatform/backends/simion/bare_frontend_geometry.py',
        ):
            with self.subTest(path=path):
                request, _ = self.plan('-ChangedPath', path)
                selected = [row for row in request['stages'] if row['selected']]
                stage = [row for row in selected if row['name'] == 'orthogonal_accelerator_static']
                self.assertEqual(len(stage), 1)
                self.assertEqual(stage[0]['command']['script'],
                                 'src/msplatform/workflows/resources/oa_verify.ps1')

    def test_static_field_comparison_selects_both_real_cli_consumers_and_installation(self):
        path = 'src/msplatform/analysis/field_comparison.py'
        request, _ = self.plan('-ChangedPath', path)
        selected = [row for row in request['stages'] if row['selected']]
        stage = [row for row in selected if row['name'] == 'static_field_comparison_tests']
        self.assertEqual(len(stage), 1)
        self.assertEqual(stage[0]['command']['arguments'][2:], [
            'tests.analysis.test_static_field_comparison',
            'tests.analysis.test_static_field_consumers',
        ])
        modules = {value.removesuffix('.py').replace('/', '.')
                   for row in selected if row['name'].startswith('machine_contracts')
                   for value in row['command']['arguments'][2:]}
        self.assertIn('tests.contracts.test_installed_scientific_core', modules)
        for caller in (
            'src/msplatform/workflows/rf_stationary.py',
            'src/msplatform/analysis/vector_field_samples.py',
        ):
            with self.subTest(caller=caller):
                self.assertIn('static_field_comparison_tests', self.routed_stages(caller))

    def test_installed_probe_support_selects_the_complete_installed_parent(self):
        path = 'tests/contracts/test_support/installed_static_field_probe.py'
        request, _ = self.plan('-ChangedPath', path)
        modules = {value.removesuffix('.py').replace('/', '.')
                   for row in request['stages'] if row['selected']
                   and row['name'].startswith('machine_contracts')
                   for value in row['command']['arguments'][2:]}
        self.assertIn('tests.contracts.test_installed_scientific_core', modules)
        for name in ('strict_json', 'workbench_seed', 'static_field', 'recorded_birth', 'sfi_consumer'):
            with self.subTest(helper=name):
                self.assertIn('machine_contracts', self.routed_stages(
                    'tests/contracts/test_support/installed_' + name + '_probe.py'))

    def test_public_recorded_birth_selects_current_sources_and_installed_boundaries(self):
        consumer = 'tests.contracts.test_public_recorded_birth'
        for path in ('src/msplatform/particle_release/authoring.py',
                     'src/msplatform/workflows/native_tracing.py',
                     'src/msplatform/backends/simion/operations.py',
                     'src/msplatform/backends/simion/compiler.py'):
            with self.subTest(path=path):
                request, _ = self.plan('-ChangedPath', path)
                selected = [row for row in request['stages'] if row['selected']]
                common = {value.removesuffix('.py').replace('/', '.') for row in selected
                          if row['name'].startswith('machine_contracts')
                          for value in row['command'].get('arguments', [])[2:]}
                self.assertIn(consumer, common)
                self.assertIn('tests.contracts.test_installed_scientific_core', common)

    def test_recorded_birth_selects_the_actual_receivers(self):
        request, _ = self.plan('-ChangedPath', 'src/msplatform/particle_release/authoring.py')
        modules = {value.removesuffix('.py').replace('/', '.')
                   for row in request['stages'] if row['selected']
                   and row['name'].startswith('machine_contracts')
                   for value in row['command']['arguments'][2:]}
        self.assertTrue({
            'tests.contracts.test_release_authoring', 'tests.contracts.test_platform_api',
            'tests.contracts.test_simion_tracking_execution',
            'tests.contracts.test_simion_tracking_units',
        } <= modules)
    def test_installed_tof_design_preserves_full_owner_and_host_entry_consumers(self):
        prefix = "src/msplatform/workflows/oa_tof_design/"
        owner = "single_reflection_oa_tof_mass_analyzer_static"
        host = "host_resource_scheduler_tests"
        for name in ("__init__", "source_comparison", "source_experiment", "numerical_case",
                     "acceptance_theory", "slope_scan", "figures"):
            with self.subTest(module=name):
                stages = self.routed_stages(prefix + name + ".py")
                self.assertIn(owner, stages)
                self.assertEqual(host in stages, name == "source_comparison")
        request, _ = self.plan("-ChangedPath", prefix + "source_comparison.py")
        actual = [module for row in request["stages"]
                  if row["name"].startswith(owner)
                  for module in row["command"].get("parameters", {}).get("SelectedTestModules", [])]
        tests = REPO_ROOT / "tests/components/single_reflection_oa_tof_mass_analyzer"
        expected = {".".join(path.relative_to(REPO_ROOT).with_suffix("").parts)
                    for path in tests.rglob("test_*.py")}
        self.assertTrue(expected)
        self.assertCountEqual(actual, expected)
        self.assertEqual(len(actual), len(set(actual)))
        selected = [row for row in request["stages"] if row["name"].startswith(host)]
        self.assertEqual(len(selected), 1)
        self.assertIn("tests.repository.test_host_resource_python", selected[0]["command"]["arguments"])

    def test_installed_probe_witnesses_select_installed_core(self):
        paths = (
            'tests/components/ion_processor/fixtures/ip_exporters_old_witness.json',
            'tests/components/rf_multipole_ion_optics/fixtures/rf_convergence_old_witness.json',
            'tests/components/ion_processor/fixtures/ip_reader_old_witness.json',
            'tests/components/single_reflection_oa_tof_mass_analyzer/fixtures/tof_mass_spectrum_old_witness.json',
            'tests/components/rf_multipole_ion_optics/fixtures/rf_event_old_capture.json',
            'tests/components/ion_processor/fixtures/ip_analyzer_old_witness.json',
            'tests/components/multi_reflection_tof/fixtures/mr_measured_source_old_witness.json',
            'tests/contracts/fixtures/strict_json_old_witness.json',
            'tests/components/multi_reflection_tof/fixtures/mr_prepared_field_old_witness.json',
            'tests/components/single_reflection_oa_tof_mass_analyzer/fixtures/ion_reader_old_witness.json',
            'tests/components/multi_reflection_tof/fixtures/mr_interface_coverage_vectors.json',
            'tests/components/single_reflection_oa_tof_mass_analyzer/test_support/detector_census_old_witness.json',
            'tests/components/rf_multipole_ion_optics/fixtures/rf_transport_comparison_old_witness.json',
            'tests/components/single_reflection_oa_tof_mass_analyzer/fixtures/reflectron_fit_capture.json',
        )
        for path in paths:
            with self.subTest(path=path):
                request, _ = self.plan("-ChangedPath", path)
                rows = [row for row in request["stages"] if row["selected"] and
                        (row["name"] == "machine_contracts" or row["name"].startswith("machine_contracts__tests_"))]
                self.assertTrue(rows)
                modules = {value.removesuffix(".py").replace("/", ".")
                           for row in rows for value in row["command"]["arguments"][2:]}
                self.assertIn("tests.contracts.test_installed_scientific_core", modules)

    def test_collision_overlay_and_binding_select_actual_consumers(self):
        for path in ('src/msplatform/backends/simion/collision_overlay.py',):
            with self.subTest(path=path):
                request, _ = self.plan("-ChangedPath", path)
                for stage, parameter, required in (
                    ("multi_reflection_tof_static", "ChangedTestModules", {"test_native_static_field_provider", "test_native_static_field_provider_runner", "test_static_field_binding"}),
                    ("instrument_assembly", "SelectedTestModules", {"test_accelerator_interface", "test_oa_mr_execute", "test_recorded_joint_trial"}),
                ):
                    modules = {value.rsplit(".", 1)[-1] for row in request["stages"]
                               if row["selected"] and row["name"].startswith(stage)
                               for value in row["command"].get("parameters", {}).get(parameter, [])}
                    self.assertTrue(required <= modules, (path, stage, modules))

    def test_static_field_binding_routes_to_all_consumer_owners(self):
        stages = self.routed_stages("src/msplatform/backends/comsol/static_field_binding.py")
        self.assertIn("multi_reflection_tof_static", stages)
        self.assertTrue(any(name == "instrument_assembly" or
                            name.startswith("instrument_assembly__tests_") for name in stages))

    def test_workbench_seed_paths_select_real_consumers(self):
        for path in ('src/msplatform/backends/simion/workbench_seed.py', 'src/msplatform/backends/simion/resources/1_instance_seed.iob', 'src/msplatform/backends/simion/workbench_seed.py'):
            with self.subTest(path=path):
                request, _ = self.plan("-ChangedPath", path)
                rows = [row for row in request["stages"] if row["selected"]]
                self.assertTrue(any(row["name"] == "ion_processor_static" or row["name"].startswith("ion_processor_static__tests_") for row in rows))
                simion = [row for row in rows if row["name"] == "simion_backend" or row["name"].startswith("simion_backend__tests_")]
                self.assertTrue(simion)
                modules = {v.removesuffix(".py").replace("/", ".") for row in simion for v in row["command"]["arguments"][2:]}
                self.assertIn("tests.simion.test_workbench_seed", modules)
                if path != 'src/msplatform/backends/simion/workbench_seed.py':
                    common = [row for row in rows if row["name"] == "machine_contracts" or row["name"].startswith("machine_contracts__tests_")]
                    self.assertTrue(common)
                    self.assertIn("tests.contracts.test_installed_scientific_core", {v.removesuffix(".py").replace("/", ".") for row in common for v in row["command"]["arguments"][2:]})

    def test_installed_detector_census_selects_actual_consumers(self):
        request, _ = self.plan("-ChangedPath", "src/msplatform/backends/simion/detector_census.py")
        modules = {value for row in request["stages"]
                   if row["name"].startswith("single_reflection_oa_tof_mass_analyzer_static")
                   for value in row["command"].get("parameters", {}).get("SelectedTestModules", [])}
        self.assertEqual(modules, {'tests.components.single_reflection_oa_tof_mass_analyzer.analysis.test_solver_diagnostics', 'tests.components.single_reflection_oa_tof_mass_analyzer.analysis.test_radial_compaction_campaign', 'tests.components.single_reflection_oa_tof_mass_analyzer.analysis.test_candidate_workflow', 'tests.components.single_reflection_oa_tof_mass_analyzer.analysis.test_candidate_causal_workflow', 'tests.components.single_reflection_oa_tof_mass_analyzer.analysis.test_candidate_postprocess_workflow'})

    def test_installed_particle_comparison_selects_both_real_analyzers(self):
        request, _ = self.plan(
            "-ChangedPath", "src/msplatform/analysis/particle_state_comparison.py"
        )
        modules = {
            value
            for row in request["stages"]
            if row["name"].startswith("rf_multipole_quadrupole_static")
            for value in row["command"].get("parameters", {}).get("ChangedTestModules", [])
        }
        self.assertEqual(modules, {
            "tests.components.rf_multipole_ion_optics.analysis.test_compare_particle_state_evidence",
            "tests.components.rf_multipole_ion_optics.analysis.test_same_solver_numerical_convergence",
            "tests.components.rf_multipole_ion_optics.analysis.test_cross_solver_gate_contract",
        })
        self.assertFalse(any(row["resource_role"] in {"SIMION", "COMSOL"}
                             for row in request["stages"]))

    def test_installed_rf_transport_metrics_selects_original_domain_owner(self):
        self.assertIn("rf_multipole_domain_tests",
                      self.routed_stages("src/msplatform/analysis/rf_transport_metrics.py"))

    def test_installed_connection_inputs_selects_existing_contract_owner(self):
        for path in ("src/msplatform/workflows/connection_inputs.py", "src/msplatform/io/file_identity.py"):
            with self.subTest(path=path):
                self.assertIn("assembly_contracts", self.routed_stages(path))

    def test_installed_source_models_reach_their_original_project_owner(self):
        behavior = {
            'tests.contracts.test_comsol_ei_model',
            'tests.contracts.test_comsol_wehnelt_model',
            'tests.contracts.test_platform_capabilities',
        }
        cases = (
            ("src/msplatform/backends/comsol/matlab/ms_stage1_ei_source.m",
             {"apertured_tube_electron_impact_ion_source_static"}, behavior),
            ("src/msplatform/components/apertured_tube_electron_impact_ion_source/resolve_contract.py",
             {"apertured_tube_electron_impact_ion_source_static"}, set()),
            ("src/msplatform/backends/comsol/matlab/build_wehnelt_model.m",
             {"transverse_helical_filament_wehnelt_electron_gun_static"}, behavior),
            ("src/msplatform/components/transverse_helical_filament_wehnelt_electron_gun/resolve_contract.py",
             {"transverse_helical_filament_wehnelt_electron_gun_static"}, set()),
            ("src/msplatform/backends/comsol/ei_model.py",
             {"apertured_tube_electron_impact_ion_source_static"}, behavior),
            ("src/msplatform/backends/comsol/wehnelt_model.py",
             {"transverse_helical_filament_wehnelt_electron_gun_static"}, behavior),
            ("src/msplatform/backends/comsol/model_execution.py",
             {"apertured_tube_electron_impact_ion_source_static",
              "transverse_helical_filament_wehnelt_electron_gun_static"}, behavior),
            ("src/msplatform/backends/comsol/native_execution.py",
             {"apertured_tube_electron_impact_ion_source_static",
              "transverse_helical_filament_wehnelt_electron_gun_static"},
             behavior | {'tests.contracts.test_installed_scientific_core'}),
        )
        for path, owners, expected_modules in cases:
            with self.subTest(path=path):
                self.assertTrue((REPO_ROOT / path).is_file(), path)
                plan, _ = self.plan('-ChangedPath', path)
                selected = [row for row in plan['stages'] if row['selected']]
                self.assertTrue(owners <= {row['name'] for row in selected}, path)
                modules = [value.removesuffix('.py').replace('/', '.') for row in selected
                           if row.get('command', {}).get('arguments', [])[:2] == ['-m', 'tools.repository.gate_unittest']
                           for value in row['command']['arguments'][2:]]
                self.assertTrue(expected_modules <= set(modules), (path, modules))
                self.assertEqual(len(modules), len(set(modules)), path)
        plan, _ = self.plan('-ChangedPath', 'src/msplatform/backends/comsol/resources.py')
        modules = [value.removesuffix('.py').replace('/', '.') for row in plan['stages'] if row['selected']
                   if row.get('command', {}).get('arguments', [])[:2] == ['-m', 'tools.repository.gate_unittest']
                   for value in row['command']['arguments'][2:]]
        self.assertIn('tests.contracts.test_installed_scientific_core', modules)

    def test_installed_wehnelt_report_selects_real_owner_plan(self):
        path = 'src/msplatform/backends/comsol/matlab/write_wehnelt_build_only_report.m'
        self.assertTrue((REPO_ROOT / path).is_file())
        request, _ = self.plan('-ChangedPath', path)
        selected = [row for row in request['stages'] if row['selected']]
        contract_rows = [row for row in selected if row['name'] == 'machine_contracts'
                         or row['name'].startswith('machine_contracts__tests_')]
        self.assertTrue(contract_rows)
        self.assert_complete_contract_modules(contract_rows, {
            'tests.contracts.test_installed_scientific_core', 'tests.contracts.test_comsol_wehnelt_model'})
        owner = [row for row in selected if row['name'] == 'transverse_helical_filament_wehnelt_electron_gun_static']
        self.assertEqual(len(owner), 1)
        command = owner[0]['command']
        self.assertEqual(command['script'],
            'src/msplatform/workflows/resources/wehnelt_verify.ps1')
        self.assertNotIn('SelectedTestModules', command.get('parameters', {}))
        self.assertNotIn('ChangedTestModules', command.get('parameters', {}))
        self.assertFalse(any(row['name'].startswith(('rf_multipole_',
            'apertured_tube_electron_impact_ion_source_static',
            'single_reflection_oa_tof_mass_analyzer_static')) for row in selected))

    def test_published_results_dependencies_select_the_reader_once(self):
        module = 'tests/contracts/test_artifact_reader.py'
        for path in ('src/msplatform/results/__init__.py', 'src/msplatform/results/artifacts.py',
                     'src/msplatform/io/manifest_records.py', 'src/msplatform/io/file_identity.py',
                     'src/msplatform/execution/terminal_publication.py'):
            with self.subTest(path=path):
                plan, _ = self.plan('-ChangedPath', path)
                modules = [contract_test_path(value) for row in plan['stages']
                           if row.get('command', {}).get('arguments', [])[:2] == ['-m', 'tools.repository.gate_unittest']
                           for value in row['command']['arguments'][2:]]
                self.assertEqual(modules.count(module), 1)

    def test_dirichlet_native_selection_has_one_public_simion_owner(self):
        module = 'tests/simion/test_dirichlet_patch_basis.py'
        for arguments in (('-Scope', 'Repository'),
                          ('-Scope', 'Owner', '-Owner', 'tests/simion'),
                          ('-ChangedPath', module),
                          ('-ChangedPath', 'tools/repository/resource_budget_support.ps1'),
                          ('-ChangedPath', 'src/msplatform/execution/host_resource_scheduler.py')):
            with self.subTest(arguments=arguments):
                plan, _ = self.plan(*arguments)
                native = [row for row in plan['stages'] if row['name'] == 'simion_dirichlet_native']
                self.assertEqual(len(native), 1)
                self.assertEqual(native[0]['resource_role'], 'SIMION')
                self.assertEqual(native[0]['resource_stage'], 'pa_refine')
                self.assertEqual(native[0]['command']['arguments'], ['-m', 'tools.repository.gate_unittest', module])
                occurrences = sum(module in row.get('command', {}).get('arguments', [])
                                  for row in plan['stages']
                                  if row.get('command', {}).get('arguments', [])[:2]
                                  == ['-m', 'tools.repository.gate_unittest'])
                self.assertEqual(occurrences, 1)
                for row in plan['stages']:
                    if row['resource_role'] == 'GATE':
                        self.assertEqual(row['resource_stage'], row['name'])
                    if row['name'].startswith('simion_backend'):
                        self.assertNotIn(module, row['command'].get('arguments', []))
                        self.assertNotIn('tests.simion.test_dirichlet_patch_basis',
                                         row['command'].get('arguments', []))

    def setUp(self) -> None:
        summary_directory = tempfile.TemporaryDirectory(prefix="changed_gate_summary_test_")
        self.addCleanup(summary_directory.cleanup)
        self.summary_path = str(Path(summary_directory.name) / "summary.json")

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = CHANGED_GATE.read_text(encoding="utf-8")
        cls.parallel_source = PARALLEL_GATE_SUPPORT.read_text(encoding="utf-8")
        cls.route_contract = json.loads(ROUTE_TABLE.read_text(encoding="utf-8"))
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            raise unittest.SkipTest("PowerShell Core is unavailable")
        result = subprocess.run(
            [pwsh, "-NoProfile", "-Command",
             ". ./tools/repository/gate_catalog_support.ps1; "
             "$routes=@(Read-GateCatalog -RepoRoot $PWD.Path); "
             "ConvertTo-Json -Depth 32 -Compress -InputObject $routes"],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.routes = json.loads(result.stdout)

    def plan(self, *arguments):
        cache = getattr(type(self), "_plans", {})
        if arguments not in cache:
            with tempfile.TemporaryDirectory(prefix="software_gate_plan_") as directory:
                request = Path(directory) / "request.json"
                result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(CHANGED_GATE),
                    "-PythonExe", sys.executable, "-PlanOnly", "-InternalRequestPath", str(request), *arguments],
                    cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=40)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                cache[arguments] = (json.loads(request.read_text(encoding="utf-8-sig")), result.stdout)
            type(self)._plans = cache
        return cache[arguments]

    def batch_plan_outputs(self, cases):
        # Exercise every real planner case; share only the PowerShell host.
        payload = json.dumps([{"paths":list(paths),"full":full} for paths,full in cases])
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        script = f"""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$cases={quote(payload)}|ConvertFrom-Json
$index=0
foreach($case in $cases){{
 $parameters=@{{PythonExe={quote(sys.executable)};PlanOnly=$true}}
 if($case.full){{$parameters.FullScope=$true}}else{{$parameters.ChangedPath=@($case.paths)}}
 $output=@(& {quote(CHANGED_GATE)} @parameters)
 if($LASTEXITCODE-ne0){{throw "Planner case $index failed"}}
 Write-Output ('PLAN_CASE_JSON='+(@{{index=$index;output=($output-join"`n")}}|ConvertTo-Json -Compress))
 $index++
}}
"""
        result = subprocess.run([shutil.which("pwsh"),"-NoProfile","-Command",script],cwd=REPO_ROOT,
            capture_output=True,text=True,encoding="utf-8",timeout=90)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        records=[json.loads(line.removeprefix("PLAN_CASE_JSON=")) for line in result.stdout.splitlines() if line.startswith("PLAN_CASE_JSON=")]
        self.assertEqual([record["index"] for record in records],list(range(len(cases))))
        return [record["output"] for record in records]

    def test_repository_and_full_changed_preserve_core_static_distinction(self):
        changed, _ = self.plan("-FullScope")
        repository, output = self.plan("-Scope", "Repository")
        self.assertIn("EXECUTION_MODE=REPOSITORY", output)
        for stage in ("rf_multipole_quadrupole_static",):
            core = next(row for row in changed["stages"] if row["name"] == stage)
            full = next(row for row in repository["stages"] if row["name"] == stage)
            self.assertEqual(core["command"]["parameters"]["Level"], "Core")
            self.assertEqual(full["command"]["parameters"]["Level"], "Static")
        self.assertEqual(len({row["name"] for row in repository["stages"]}), len(repository["stages"]))

    def test_sfi_owner_plan_retains_preflight_and_unique_test_shards(self):
        prefix = 'src/msplatform/components/single_reflection_oa_tof'
        stage = 'single_reflection_oa_tof_mass_analyzer_static'
        expected = {'.'.join(path.relative_to(REPO_ROOT).with_suffix('').parts)
                    for path in (REPO_ROOT / 'tests/components/single_reflection_oa_tof_mass_analyzer').rglob('test_*.py')}
        for arguments in (
            ('-Scope', 'Owner', '-Owner', 'single_reflection_oa_tof_mass_analyzer'),
            ('-ChangedPath', prefix + '/reflectron_dual_stage_solver.py'),
        ):
            with self.subTest(arguments=arguments):
                request, _ = self.plan(*arguments)
                rows = {row['name']: row for row in request['stages'] if row['selected']}
                self.assertEqual(rows[stage]['command']['runner'], 'powershell')
                self.assertTrue(rows[stage]['command']['parameters']['PreflightOnly'])
                shards = [row for name, row in rows.items() if name.startswith(stage + '__tests_')]
                route = next(row for row in self.routes if row['stage'] == stage)
                self.assertEqual(len(shards), route['repository_gate_partition']['count'])
                actual = [module for row in shards
                          for module in row['command']['parameters']['SelectedTestModules']]
                self.assertCountEqual(actual, expected)
                self.assertEqual(len(actual), len(set(actual)))
                for row in shards:
                    self.assertIn(stage, row['requires_stages'])
                    self.assertTrue(row['command']['parameters']['PreflightValidated'])
                    self.assertNotIn('PreflightOnly', row['command']['parameters'])
        changed = 'tests/components/single_reflection_oa_tof_mass_analyzer/analysis/test_simion_delivery_source.py'
        request, _ = self.plan('-ChangedPath', changed)
        rows = {row['name']: row for row in request['stages'] if row['selected']}
        self.assertEqual(rows[stage]['command']['runner'], 'python')
        self.assertEqual(rows[stage]['command']['arguments'], ['-m', 'tools.repository.gate_unittest', changed])
        self.assertFalse(any(name.startswith(stage + '__tests_') for name in rows))

    def test_owner_scope_selects_complete_owner_checks_without_unrelated_project_scan(self):
        request, _ = self.plan("-Scope", "Owner", "-Owner", "orthogonal_accelerator")
        stages = {row["name"]:row for row in request["stages"]}
        owner_route = next(route for route in self.routes if route.get("project_id")=="orthogonal_accelerator")
        self.assertIn(owner_route["stage"], stages)
        expected = owner_route.get("repository_gate_command", owner_route["command"])
        actual = stages[owner_route["stage"]]["command"]
        self.assertEqual(actual["script"], expected["script"])
        for key, value in expected.get("parameters", {}).items():
            if key != "PythonExe":
                self.assertEqual(actual["parameters"][key], value)
        unrelated = {route["stage"] for route in self.routes if route.get("project_id") not in (None,"orthogonal_accelerator")}
        self.assertFalse(unrelated.intersection(stages), unrelated.intersection(stages))
        lint = stages["ruff_changed_python"]["command"]["arguments"][3:]
        self.assertTrue(lint)
        owner_roots = tuple(REPO_ROOT / root for root in (
            "src/msplatform/components/orthogonal_accelerator",
            "tests/components/orthogonal_accelerator",
            "tests/assembly/orthogonal_accelerator",
        ))
        related_dependencies = {REPO_ROOT / value for value in (
            "src/msplatform/backends/simion/bare_frontend_geometry.py",
            "src/msplatform/backends/simion/gem_primitives.py",
            "src/msplatform/backends/simion/source.py",
            "src/msplatform/components/single_reflection_oa_tof/accelerator_geometry.py",
            "src/msplatform/contracts/expected_values.py",
            "tests/assembly/single_reflection_oa_tof_mass_analyzer/analysis/test_assembly_interface.py",
        )}
        self.assertTrue(all(
            any(Path(value).is_relative_to(root) for root in owner_roots)
            or Path(value) in related_dependencies for value in lint
        ), lint)
        standards = stages["development_standards"]["command"]["arguments"]
        self.assertIn("--path", standards)
        selected = [standards[index+1] for index,value in enumerate(standards) if value=="--path"]
        self.assertTrue(selected)
        standards_dependencies = {
            "src/msplatform/backends/simion/bare_frontend_geometry.py",
            "src/msplatform/backends/simion/gem_primitives.py",
            "src/msplatform/backends/simion/source.py",
            "src/msplatform/components/multi_reflection_tof/config/accelerator_dependency.json",
            "src/msplatform/components/single_reflection_oa_tof/accelerator_geometry.py",
            "src/msplatform/components/single_reflection_oa_tof/config/accelerator_dependency.json",
            "src/msplatform/contracts/expected_values.py",
            "tests/assembly/single_reflection_oa_tof_mass_analyzer/analysis/test_assembly_interface.py",
        }
        self.assertTrue(all(
            value.startswith((
                "src/msplatform/components/orthogonal_accelerator/",
                "tests/components/orthogonal_accelerator/",
                "tests/assembly/orthogonal_accelerator/",
            )) or value in standards_dependencies for value in selected
        ), selected)

    def test_owner_group_and_stage_alias_bind_the_actual_source_owner(self):
        contracts,_=self.plan("-Scope","Owner","-Owner","machine_contracts")
        self.assertIn("contracts_registry", {row["name"] for row in contracts["stages"]})
        actual = [module for row in contracts["stages"]
                  for module in row["command"].get("arguments", [])[2:]
                  if module.startswith("tests.contracts.")]
        route = next(row for row in self.routes if row["stage"] == "machine_contracts")
        expected = [".".join(path.relative_to(REPO_ROOT).with_suffix("").parts)
                    for root in route["test_selection"]["roots"]
                    for path in (REPO_ROOT / root).rglob("test_*.py")]
        self.assertCountEqual(actual, expected)
        project,_=self.plan("-Scope","Owner","-Owner","rf_multipole_ion_optics")
        self.assertIn("rf_multipole_domain_tests",{row["name"] for row in project["stages"]})
        alias,_=self.plan("-Scope","Owner","-Owner","rf_multipole_domain_tests")
        standards=next(row for row in alias["stages"] if row["name"]=="development_standards")
        arguments=standards["command"]["arguments"]
        selected=[arguments[index+1] for index,value in enumerate(arguments) if value=="--path"]
        self.assertIn("src/msplatform/workflows/rf_design_profiles.py",selected)
        canonical="src/msplatform/components/rf_multipole/ideal_transport.py"
        actual=self.routed_stages(canonical)
        self.assertTrue({"rf_multipole_domain_tests", "rf_multipole_hexapole_static",
                         "rf_multipole_octupole_static", "rf_multipole_quadrupole_static"} <= actual.keys())
        related_dependencies = {
            "src/msplatform/workflows/rf_campaign_analysis.py",
            "src/msplatform/analysis/mass_response.py",
            "src/msplatform/analysis/particle_census.py",
            "src/msplatform/analysis/particle_styles.py",
            "src/msplatform/analysis/rf_transport_metrics.py",
            "src/msplatform/backends/comsol/rf_finite_extraction.py",
            "src/msplatform/backends/comsol/rf_stationary_field.py",
            "src/msplatform/backends/comsol/rf_transport_metrics.py",
            "src/msplatform/backends/simion/resources/rf_drive.lua",
            "src/msplatform/backends/simion/resources/voltage_waveforms.lua",
            "src/msplatform/backends/simion/rf_observations.py",
            "src/msplatform/backends/simion/source.py",
            "src/msplatform/execution/inputs.py",
            "src/msplatform/execution/resources/__init__.py",
            "src/msplatform/execution/resources/frozen_python_package.ps1",
            "src/msplatform/io/strict_json.py",
            "src/msplatform/particle_release/paired_mass_scan.py",
            "src/msplatform/workflows/rf_batch_continuation.py",
            "src/msplatform/workflows/rf_design_profiles.py",
            "src/msplatform/workflows/rf_resource_budget.py",
            "src/msplatform/workflows/rf_runtime_profiles.py",
            "src/msplatform/workflows/rf_stationary.py",
            "tools/repository/resource_budget_support.ps1",
        }
        self.assertTrue(all(
            path.startswith((
                "src/msplatform/components/rf_multipole/",
                "tests/components/rf_multipole_ion_optics/",
            )) or path in related_dependencies for path in selected
        ), selected)

    def test_unknown_owner_is_rejected_during_selection_before_resource_admission(self):
        with tempfile.TemporaryDirectory(prefix="unknown_owner_plan_") as directory:
            ledger = Path(directory)/"ledger.sqlite3"
            result = subprocess.run([shutil.which("pwsh"),"-NoProfile","-File",str(CHANGED_GATE),
                "-PythonExe",sys.executable,"-Scope","Owner","-Owner","no_such_owner","-PlanOnly"],
                cwd=REPO_ROOT,capture_output=True,text=True,encoding="utf-8",timeout=30,
                env={**os.environ,"MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH":str(ledger)})
            self.assertNotEqual(result.returncode,0)
            self.assertIn("owner",result.stderr.lower())
            self.assertFalse(ledger.exists())

    def test_short_analysis_batches_preserve_each_declared_module_once(self):
        request, _ = self.plan("-Scope", "Repository")
        expected = [module for route in self.routes if route.get("execution_batch") == "analysis"
                    for module in route["command"]["arguments"][2:]]
        actual = [module for row in request["stages"] if row["name"].startswith("analysis_")
                  for module in row["command"]["arguments"][2:]]
        self.assertCountEqual(actual, expected)
        self.assertEqual(len(actual), len(set(actual)))

    def test_repository_lint_includes_installed_source_root(self):
        request, _ = self.plan("-Scope", "Repository")
        lint = next(row for row in request["stages"] if row["name"] == "ruff_changed_python")
        self.assertEqual(lint["command"]["arguments"],
                         ["-m", "ruff", "check", "src", "tests", "tools"])

    def test_plan_source_paths_map_installed_namespace_to_src(self):
        script = '''
. ./tools/repository/gate_catalog_support.ps1
$items = @(
    [pscustomobject]@{Run=$true;Command=[pscustomobject]@{
        runner='python';arguments=@('-m','msplatform.analysis.peak_metrics','msplatform.execution.capacity_ledger')
    }},
    [pscustomobject]@{Run=$false;Command=[pscustomobject]@{
        runner='python';arguments=@('-m','msplatform.unselected')
    }}
)
$paths = @(Get-GatePlanSourcePaths -Items $items)
ConvertTo-Json -Compress -InputObject $paths
'''
        result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script],
                                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        paths = json.loads(result.stdout)
        self.assertIn("src/msplatform/analysis/peak_metrics.py", paths)
        self.assertIn("src/msplatform/execution/capacity_ledger.py", paths)
        self.assertNotIn("msplatform/analysis/peak_metrics.py", paths)
        self.assertNotIn("src/msplatform/unselected.py", paths)
        self.assertEqual(len(paths), len(set(paths)))

    def test_workspace_paths_owner_and_sources_keep_protocol_and_workflow_coverage(self):
        module = "tests.contracts.test_run_artifact_workflow_sources"
        for path in ("src/msplatform/execution/resources/workspace_paths.py", "src/msplatform/execution/resources/workspace_paths.ps1"):
            with self.subTest(path=path):
                request, _ = self.plan("-ChangedPath", path)
                selected = [row for row in request["stages"] if row["selected"]]
                self.assertIn("workspace_paths_tests", {row["name"] for row in selected})
                modules = [value.removesuffix(".py").replace("/", ".")
                           for row in selected if row["name"].startswith("machine_contracts")
                           for value in row["command"]["arguments"][2:]]
                self.assertIn(module, modules)
                self.assertEqual(modules.count(module), 1)
        request, _ = self.plan("-Scope", "Owner", "-Owner", "tests/paths")
        owner = next(row for row in request["stages"] if row["name"] == "workspace_paths_tests")
        actual = {value.removesuffix(".py").replace("/", ".") for value in owner["command"]["arguments"][2:]}
        expected = {".".join(path.relative_to(REPO_ROOT).with_suffix("").parts)
                    for path in (REPO_ROOT / "tests/paths").glob("test_*.py")}
        self.assertEqual(actual, expected)
        request, _ = self.plan("-ChangedPath", "tests/paths/test_workspace_paths.py")
        owner = next(row for row in request["stages"] if row["name"] == "workspace_paths_tests")
        self.assertEqual(owner["command"]["arguments"][2:], ["tests/paths/test_workspace_paths.py"])

    def test_pure_gas_dependencies_select_actual_tests_without_native_stages(self):
        expected = {"tests/contracts/test_gas.py", "tests/contracts/test_gas_field_sampling.py",
                    "tests/contracts/test_gas_runtime.py"}
        for path in ("src/msplatform/contracts/gas.py", "src/msplatform/gas/field.py",
                     "src/msplatform/gas/thermodynamics.py", "src/msplatform/contracts/rigid_transform.py",
                     "src/msplatform/contracts/particle_physics.py", "src/msplatform/io/manifest_records.py",
                     "src/msplatform/backends/simion/gas_runtime.py"):
            with self.subTest(path=path):
                request, _ = self.plan("-ChangedPath", path)
                modules = [contract_test_path(value) for row in request["stages"]
                           if row["name"].startswith("machine_contracts")
                           for value in row["command"]["arguments"][2:]]
                self.assertTrue(expected <= set(modules))
                self.assertEqual(len(modules), len(set(modules)))
                self.assertFalse(any(row["resource_role"] in {"SIMION", "COMSOL"}
                                     for row in request["stages"]))
        for path in expected:
            with self.subTest(test=path):
                request, _ = self.plan("-ChangedPath", path)
                modules = [contract_test_path(value) for row in request["stages"]
                           if row["name"].startswith("machine_contracts")
                           for value in row["command"]["arguments"][2:]]
                if path == "tests/contracts/test_gas_field_sampling.py":
                    self.assertEqual(set(modules), expected)
                else:
                    self.assertEqual(modules, [path])

    def test_joint_gas_runtime_selects_actual_dual_cone_consumers(self):
        expected = {"tests/components/dual_cone_tandem_quadrupole/test_" + name + ".py" for name in (
            "dual_cone_transport_execution", "dual_cone_transport", "dual_cone_stages",
            "dual_cone_iob", "dual_cone_placement", "dual_cone_native_guards", "dual_cone_managed_stages")}
        paths = ("src/msplatform/components/dual_cone_tandem_quadrupole/gas_field.py",
                 "src/msplatform/backends/simion/resources/collision_sds_binding.lua",
                 "src/msplatform/backends/simion/gas_runtime.py", "src/msplatform/contracts/gas.py",
                 "src/msplatform/gas/field.py")
        for path in paths:
            with self.subTest(path=path):
                request, _ = self.plan("-ChangedPath", path)
                modules = [contract_test_path(value) for row in request["stages"] if row["name"].startswith("machine_contracts")
                           for value in row["command"]["arguments"][2:]]
                self.assertTrue(expected <= set(modules))
                self.assertTrue(all(modules.count(name) == 1 for name in expected))
                self.assertTrue(any(row["name"].startswith("dual_cone_tandem_quadrupole_static")
                                    for row in request["stages"]))
                self.assertFalse(any(row["resource_role"] in {"SIMION", "COMSOL"} for row in request["stages"]))

    def test_recorded_gas_structure_policy_and_reader_select_actual_consumers(self):
        expected = {"tests/components/dual_cone_tandem_quadrupole/test_comsol_gas_flow.py",
                    "tests/components/dual_cone_tandem_quadrupole/test_dual_cone_stages.py",
                    "tests/components/dual_cone_tandem_quadrupole/test_dual_cone_managed_stages.py",
                    "tests/components/dual_cone_tandem_quadrupole/test_dual_cone_transport_execution.py",
                    "tests/components/dual_cone_tandem_quadrupole/test_dual_cone_transport.py"}
        for path in ("src/msplatform/components/dual_cone_tandem_quadrupole/gas_field_validation.py",
                     "src/msplatform/contracts/gas_field.py", "src/msplatform/results/gas_field.py"):
            with self.subTest(path=path):
                request, _ = self.plan("-ChangedPath", path)
                modules = [contract_test_path(value) for row in request["stages"]
                           if row["name"].startswith("machine_contracts")
                           for value in row["command"]["arguments"][2:]]
                self.assertTrue(expected <= set(modules))
                self.assertTrue(all(modules.count(name) == 1 for name in expected))
                self.assertTrue(any(row["name"].startswith("dual_cone_tandem_quadrupole_static")
                                    for row in request["stages"]))
                self.assertFalse(any(row["resource_role"] in {"SIMION", "COMSOL"}
                                     for row in request["stages"]))




    def test_recorded_cooling_helper_selects_the_actual_analysis_consumers(self):
        from tests.contracts.test_changed_test_selection import write_planned_request

        helper = "src/msplatform/analysis/cooling_diagnostics.py"
        for paths in ((helper,), (helper, "src/msplatform/analysis/population_moments.py"),
                      (helper, "tests/analysis/test_population_moments.py")):
            with self.subTest(paths=paths):
                with tempfile.TemporaryDirectory(prefix="recorded_cooling_route_") as directory:
                    request_path = Path(directory) / "request.json"
                    write_planned_request(REPO_ROOT, request_path, list(paths))
                    request = json.loads(request_path.read_text(encoding="utf-8-sig"))
                units = [row for row in request["stages"] if row["name"] == "population_moments_tests"]
                self.assertEqual(len(units), 1)
                self.assertEqual(units[0]["command"]["arguments"],
                                 ["-m", "tools.repository.gate_unittest", "tests.analysis.test_population_moments"])
                common = [value for row in request["stages"] if row["name"].startswith("machine_contracts")
                          for value in row["command"].get("arguments", [])]
                self.assertNotIn("tests/analysis/test_population_moments.py", common)
                if len(paths) == 1:
                    integration = {value for row in request["stages"]
                                   if row["name"].startswith("instrument_assembly")
                                   for value in row["command"].get("parameters", {}).get("SelectedTestModules", [])}
                    self.assertEqual(integration, {"tests.execution.test_dependencies"})
                self.assertFalse(any(row["resource_role"] in {"SIMION", "COMSOL"} for row in request["stages"]))

    def test_mr_backend_geometry_keeps_one_original_software_owner(self):
        request, _ = self.plan(
            "-ChangedPath", "src/msplatform/backends/simion/mr_geometry.py"
        )
        mr = [row for row in request["stages"]
              if row["name"] == "multi_reflection_tof_static"]
        self.assertEqual(len(mr), 1)
        self.assertFalse(any(row["resource_role"] in {"SIMION", "COMSOL"}
                             for row in request["stages"]))

    def test_mr_neutral_geometry_keeps_full_owner_and_actual_integration_consumers(self):
        request, _ = self.plan(
            "-ChangedPath",
            "src/msplatform/components/multi_reflection_tof/resolved_geometry.py",
        )
        mr = [row for row in request["stages"]
              if row["name"] == "multi_reflection_tof_static"]
        self.assertEqual(len(mr), 1)
        params = mr[0]["command"]["parameters"]
        self.assertEqual(params["Level"], "Core")
        self.assertNotIn("SelectedTestModules", params)
        self.assertEqual(set(params["ChangedTestModules"]), {
            "tests.assembly.multi_reflection_tof.analysis.test_assembly_interface",
            "tests.components.multi_reflection_tof.analysis.test_simion_candidate_reference",
            "tests.components.multi_reflection_tof.analysis.test_mr_provider_freeze",
            "tests.components.multi_reflection_tof.analysis.test_mr_provider_trial_transport",
            "tests.components.multi_reflection_tof.analysis.test_two_prism_simion_trial",
            "tests.components.multi_reflection_tof.analysis.test_gap2_fixed_design"})
        self.assertEqual(len(params["ChangedTestModules"]), len(set(params["ChangedTestModules"])))
        verify = (REPO_ROOT / "src/msplatform/workflows/resources/mr_verify.ps1").read_text(encoding="utf-8")
        self.assertIn("$coreTests = @($coreTests + $ChangedTestModules | Sort-Object -Unique)", verify)
        self.assertTrue(any(row["name"].startswith("instrument_assembly")
                            for row in request["stages"]))
        self.assertFalse(any(row["resource_role"] in {"SIMION", "COMSOL"}
                             for row in request["stages"]))

    def test_mr_interface_selects_its_original_tests_and_real_composition_consumer(self):
        request, _ = self.plan("-ChangedPath",
            "src/msplatform/components/multi_reflection_tof/assembly_interface.py")
        mr_rows = [row for row in request["stages"]
                   if row["name"] == "multi_reflection_tof_static"]
        self.assertEqual(len(mr_rows), 1)
        mr = mr_rows[0]["command"]["parameters"]["ChangedTestModules"]
        self.assertEqual(set(mr), {
            "tests.assembly.multi_reflection_tof.analysis.test_assembly_interface",
            "tests.components.multi_reflection_tof.analysis.test_simion_candidate_reference",
            "tests.components.multi_reflection_tof.analysis.test_mr_provider_freeze",
            "tests.components.multi_reflection_tof.analysis.test_mr_provider_trial_transport",
            "tests.components.multi_reflection_tof.analysis.test_two_prism_simion_trial",
            "tests.components.multi_reflection_tof.analysis.test_gap2_fixed_design"})
        self.assertEqual(mr_rows[0]["command"]["parameters"]["Level"], "Core")
        self.assertNotIn("SelectedTestModules", mr_rows[0]["command"]["parameters"])
        self.assertEqual(len(mr), len(set(mr)))
        integration = {value for row in request["stages"]
                       if row["name"].startswith("instrument_assembly")
                       for value in row["command"].get("parameters", {}).get("SelectedTestModules", [])}
        self.assertEqual(integration, {"tests.assembly.accelerator_interface_geometry.test_accelerator_interface_geometry"})
        self.assertFalse(any(row["resource_role"] in {"SIMION", "COMSOL"} for row in request["stages"]))




    def test_ip_section_geometry_selects_actual_project_and_overlay_consumers(self):
        request, _ = self.plan("-ChangedPath",
            "src/msplatform/components/ion_processor/section_geometry.py")
        self.assertIn("ion_processor_static", {row["name"] for row in request["stages"]})
        modules = [contract_test_path(value) for row in request["stages"]
                   if row["name"].startswith("instrument_assembly")
                   for value in row["command"].get("parameters", {}).get("SelectedTestModules", [])]
        self.assertNotIn("tests.integration.test_local_frontend_analysis", modules)
        self.assertFalse(any(row["resource_role"] in {"SIMION", "COMSOL"} for row in request["stages"]))


    def test_ip_gas_dependencies_select_consumers_without_native_stages(self):
        for path in ("src/msplatform/components/ion_processor/gas_regions.py",
                     "src/msplatform/backends/simion/resources/collision_hs1_gas.lua",
                     "src/msplatform/backends/simion/gas_runtime.py"):
            with self.subTest(path=path):
                request, _ = self.plan("-ChangedPath", path)
                modules = [contract_test_path(value) for row in request["stages"]
                           if row["name"].startswith("machine_contracts")
                           for value in row["command"]["arguments"][2:]]
                self.assertTrue({"tests/contracts/test_ip_gas_regions.py",
                                 "tests/contracts/test_ip_preparation.py"} <= set(modules))
                self.assertTrue(any(row["name"].startswith("ion_processor_static")
                                    for row in request["stages"]))
                self.assertFalse(any(row["resource_role"] in {"SIMION", "COMSOL"}
                                     for row in request["stages"]))

    def test_common_contract_dependencies_select_modules_without_retired_routes(self):
        cases = (("src/msplatform/execution/inputs.py", "tests.contracts.test_frozen_inputs"),
                 ("src/msplatform/contracts/expected_values.py", "tests.contracts.test_expected_values"),
                 ("tools/repository/report_cloc_delta.ps1", "tests.contracts.test_report_cloc_delta"),
                 ("tools/repository/verify.ps1", "tests.contracts.test_verify_changed"),
                 ("pyproject.toml", "tests.contracts.test_python_dependency_contract"),
                 ("pyproject.toml", "tests.contracts.test_installed_scientific_core"),
                 ("src/msplatform/particle_release/release.py", "tests.contracts.test_installed_scientific_core"),
                 ("src/msplatform/particle_release/__init__.py", "tests.contracts.test_installed_scientific_core"),
                 ("src/msplatform/assembly/resolve_assembly.py", "tests.contracts.test_installed_scientific_core"),
                 ("src/msplatform/assembly/__init__.py", "tests.contracts.test_installed_scientific_core"),
                 ("src/msplatform/analysis/peak_metrics.py", "tests.contracts.test_installed_scientific_core"),
                 ("src/msplatform/contracts/particle_physics.py", "tests.contracts.test_installed_scientific_core"),
                 ("src/msplatform/contracts/schemas/composition_plan.schema.json", "tests.contracts.test_installed_scientific_core"),
                 ("src/msplatform/contracts/schemas/oatof_three_zone_stage_report.schema.json", "tests.contracts.test_machine_contracts_paths"))
        for path, module in cases:
            with self.subTest(path=path):
                request, _ = self.plan("-ChangedPath", path)
                owners = [row for row in request["stages"]
                          if row["name"] == "machine_contracts" or row["name"].startswith("machine_contracts__tests_")]
                self.assertTrue(owners, "public contract selection is missing")
                modules = [value.removesuffix(".py").replace("/", ".")
                           for owner in owners for value in owner["command"]["arguments"][2:]]
                self.assertIn(module, modules)
                self.assertEqual(len(modules), len(set(modules)))

    def test_frozen_input_dependency_keeps_its_real_seed_consumer_unique(self):
        request, _ = self.plan("-ChangedPath", "src/msplatform/execution/inputs.py")
        rows = {row["name"]: row for row in request["stages"]}
        arguments = [value for name, row in rows.items()
                     if name == "machine_contracts" or name.startswith("machine_contracts__tests_")
                     for value in row["command"]["arguments"]]
        self.assertEqual(arguments[:2], ["-m", "tools.repository.gate_unittest"])
        self.assertCountEqual([contract_test_path(value) for value in arguments[2:]
                              if value.startswith(("tests.contracts.", "tests/contracts/", "tests.components.", "tests/components/"))],
                             FROZEN_INPUT_CONTRACT_TESTS)
        self.assertEqual(rows["simion_backend"]["command"]["arguments"],
                         ["-m", "tools.repository.gate_unittest", "tests/simion/test_workbench_seed.py"])
        all_modules = [contract_test_path(module) for row in request["stages"]
                       for module in row["command"].get("arguments", [])[2:]]
        self.assertEqual(all_modules.count("tests/contracts/test_frozen_inputs.py"), 1)
        self.assertEqual(all_modules.count("tests/simion/test_workbench_seed.py"), 1)

    def test_resource_sampler_dependencies_keep_completion_and_drain_in_public_scope(self):
        request, _ = self.plan("-ChangedPath", "tools/repository/resource_budget_support.ps1")
        rows = {row["name"]: row for row in request["stages"]}
        self.assertIn("host_resource_scheduler_tests", rows)
        self.assertEqual(rows["simion_backend"]["command"]["arguments"],
                         ["-m", "tools.repository.gate_unittest", "tests/simion/test_managed_process_completion.py"])
        drain = "tests.repository.test_observed_preparation_drain"
        self.assertEqual(rows["host_resource_scheduler_tests"]["command"]["arguments"].count(drain), 1)
        changed_test, _ = self.plan("-ChangedPath", "tests/repository/test_observed_preparation_drain.py")
        self.assertIn("host_resource_scheduler_tests", {row["name"] for row in changed_test["stages"]})
        repository, _ = self.plan("-Scope", "Repository")
        self.assertEqual(sum(row["command"].get("arguments", []).count(drain)
                             for row in repository["stages"]), 1)

    def test_frozen_input_mapping_preserves_missing_unknown_and_full_selection(self):
        with tempfile.TemporaryDirectory(prefix="frozen_leaf_selection_") as directory:
            root = Path(directory)
            inputs = root / "tests/contracts"
            inputs.mkdir(parents=True)
            expected = {value for value in FROZEN_INPUT_CONTRACT_TESTS
                    if value.startswith("tests/contracts/")} | {
                "tests/contracts/test_other_contract.py", "tests/contracts/test_another_contract.py",
            }
            for relative in expected | {"src/msplatform/execution/inputs.py"}:
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                (root / relative).write_text("# selector metadata fixture; never imported\n", encoding="utf-8")
            literal = lambda value: "'" + str(value).replace("'", "''") + "'"
            script = f"""
$ErrorActionPreference='Stop'
. {literal(REPO_ROOT / 'tools/repository/gate_catalog_support.ps1')}
$route=(Get-Content -LiteralPath {literal(ROUTE_TABLE)} -Raw|ConvertFrom-Json -Depth 32).routes|Where-Object stage -eq machine_contracts
$root={literal(root)};$source='src/msplatform/execution/inputs.py'
$parameters=@{{Route=$route;KnownTestRoots=@('tests/contracts/');RepoRoot=$root}}
$results=[ordered]@{{known=@((Get-GateChangedTests @parameters -ChangedPaths @($source)).Modules)}}
$results.unknown=@((Get-GateChangedTests @parameters -ChangedPaths @('tests/contracts/future_unknown.py')).Modules)
Remove-Item -LiteralPath (Join-Path $root $source)
$results.deleted=$null-eq(Get-GateChangedTests @parameters -ChangedPaths @($source))
Set-Content -LiteralPath (Join-Path $root 'tests/contracts/renamed_frozen_inputs.py') -Value '# not executed'
$results.renamed=$null-eq(Get-GateChangedTests @parameters -ChangedPaths @($source,'tests/contracts/renamed_frozen_inputs.py'))
$results.full=@((Get-GateChangedTests @parameters -ChangedPaths @($source) -FullScope).Modules)
$results|ConvertTo-Json -Compress
"""
            result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script],
                                    cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            records = json.loads(result.stdout)
            self.assertCountEqual(records["known"], FROZEN_INPUT_CONTRACT_TESTS)
            # Canonical inputs.py is outside the contract test owner's scope.
            # A deleted/renamed authority returns no narrow selection, retaining
            # the original full-owner command instead of stale leaf mappings.
            for case in ("deleted", "renamed"):
                with self.subTest(case=case):
                    self.assertTrue(records[case])
            for case in ("unknown", "full"):
                with self.subTest(case=case):
                    self.assertEqual(set(records[case]), expected)
                    self.assertEqual(len(records[case]), len(expected))

    def routed_stages(self, path: str) -> dict[str, str]:
        selected: dict[str, str] = {}
        for route in self.routes:
            for match in route["matches"]:
                matched = (
                    ("exact" in match and path.casefold() == match["exact"].casefold())
                    or (
                        "prefix" in match
                        and path.casefold().startswith(match["prefix"].casefold())
                    )
                    or (
                        "regex" in match
                        and re.search(match["regex"], path, re.IGNORECASE) is not None
                    )
                )
                if matched:
                    selected[route["stage"]] = match["reason"]
                    break
        return selected




    def test_changed_ruff_argfile_handles_long_paths_and_cleans_after_failure(self) -> None:
        """Run the actual changed-file action with native Ruff, including F821."""
        pwsh = shutil.which("pwsh")
        with tempfile.TemporaryDirectory(prefix="changed_ruff_argfile_") as directory:
            root = Path(directory)
            temporary_files = root / "temporary arguments"
            temporary_files.mkdir()
            valid = root / "valid # 场 path.py"
            invalid = root / "invalid # 场 path.py"
            valid.write_text("value = 1\n", encoding="utf-8")
            invalid.write_text("missing_name()\n", encoding="utf-8")
            paths = [str(valid)]
            # Exercise more than CreateProcessW's 32,767 UTF-16 characters,
            # without creating hundreds of redundant fixture files.
            while sum(len(path) + 3 for path in paths) <= 32767:
                paths += paths
            for failed in (False, True):
                with self.subTest(failed=failed):
                    selected = paths + ([str(invalid)] if failed else [])
                    path_list = root / "paths.json"
                    path_list.write_text(json.dumps(selected), encoding="utf-8")
                    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
                    command = f"""
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$env:RUFF_NO_CACHE='true';$env:RAYON_NUM_THREADS='1'
$env:TMP={quote(temporary_files)};$env:TEMP={quote(temporary_files)}
$PythonExe={quote(sys.executable)}
$existingPythonFiles=@(Get-Content -Raw -LiteralPath {quote(path_list)}|ConvertFrom-Json)
. {quote(REPO_ROOT / 'tools/repository/gate_catalog_support.ps1')}
$command=[pscustomobject]@{{runner='python';arguments=@('-m','ruff','check')+$existingPythonFiles}}
try{{Invoke-GateCatalogCommand -Command $command -RepoRoot {quote(REPO_ROOT)} -PythonExe $PythonExe}}
catch{{if($LASTEXITCODE-ne{int(failed)}){{throw}}}}
$nativeExitCode=$LASTEXITCODE
if($nativeExitCode-ne{int(failed)}){{throw "Unexpected native Ruff exit $nativeExitCode"}}
if(@(Get-ChildItem -LiteralPath {quote(temporary_files)} -Force).Count){{throw 'Ruff argument file leaked'}}
Write-Output "CHANGED_RUFF_NATIVE_EXIT=$nativeExitCode"
exit 0
"""
                    completed = subprocess.run(
                        [pwsh, "-NoProfile", "-NonInteractive", "-Command", command],
                        cwd=REPO_ROOT, capture_output=True, text=True,
                        encoding="utf-8", timeout=30, check=False,
                    )
                    output = completed.stdout + completed.stderr
                    self.assertEqual(completed.returncode, 0, output)
                    self.assertIn(f"CHANGED_RUFF_NATIVE_EXIT={int(failed)}", output)
                    self.assertIn("F821" if failed else "All checks passed!", output)
                    self.assertEqual(list(temporary_files.iterdir()), [])

    def test_integration_documentation_action_forwards_selected_python(self) -> None:
        request, _ = self.plan("-Scope", "Repository")
        documentation = next(stage for stage in request["stages"] if stage["name"] == "documentation")
        self.assertEqual(documentation["command"]["parameters"]["PythonExe"], sys.executable)

    def test_documentation_only_fast_path_runs_without_project_gates(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        fixture_directory = tempfile.TemporaryDirectory(prefix="documentation_changed_gate_")
        self.addCleanup(fixture_directory.cleanup)
        fixture_root = Path(fixture_directory.name)
        common = fixture_root / "tools/repository"
        common.mkdir(parents=True)
        (fixture_root / "src/msplatform/components").mkdir(parents=True)
        for name in ("verify.ps1", "parallel_gate_support.ps1", "gate_catalog_support.ps1", "require_powershell7.ps1", "resource_process_support.ps1"):
            source = REPO_ROOT / ("src/msplatform/execution/resources" if name in ("require_powershell7.ps1", "resource_process_support.ps1") else "tools/repository") / name
            destination = fixture_root / ("src/msplatform/execution/resources" if name in ("require_powershell7.ps1", "resource_process_support.ps1") else "tools/repository") / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        (common / "host_execution_lease.ps1").write_text("function Get-HostResourceBudget {param($Role,$Stage) @{}}\nfunction Enter-HostResourceStage {param($Role,$Stage,$Budget) @{}}\nfunction Exit-HostResourceStage {param($Lease)}\n",encoding="utf-8")
        (common / "gate_catalog.json").write_text('{"schema_version":2,"role":"repository_gate_catalog","routes":[{"stage":"unrelated_project","dependency_profile":"locked","repository_gate_group":"regression","matches":[{"exact":"src/msplatform/components/unrelated/source.py","reason":"unrelated"}],"command":{"runner":"python","arguments":["-c","print(42)"]}}]}',encoding="utf-8")
        (common / "verify_repository_hygiene.ps1").write_text("Write-Output 'REPOSITORY_HYGIENE=PASS'\n",encoding="utf-8")
        (common / "verify_repository_text_bytes.py").write_text("print('TEXT_BYTES_FIXTURE=PASS')\n",encoding="utf-8")
        (common / "verify_documentation.ps1").write_text("param($PythonExe,[switch]$StructureOnly,[string[]]$ChangedPath)\nWrite-Output 'DOCUMENTATION_FIXTURE=PASS'\n",encoding="utf-8")
        completed = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-File",
                str(common / "verify.ps1"),
                "-PythonExe",
                sys.executable,
                "-ChangedPath",
                "CHANGELOG.md",
                "-SummaryPath", self.summary_path,
            ],
            cwd=fixture_root,
            capture_output=True,
            text=True, encoding="utf-8",
            # This executes all three real documentation gates under host
            # admission; it checks routing, not a 30-second performance SLA.
            timeout=180,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.count("REPOSITORY_HYGIENE=PASS"), 1)
        self.assertIn("GATE_STAGE=RUN NAME=documentation", completed.stdout)
        self.assertIn("GATE_STAGE=RUN NAME=repository_text_bytes", completed.stdout)
        self.assertLess(
            completed.stdout.index("GATE_STAGE=RUN NAME=repository_text_bytes"),
            completed.stdout.index("CHANGED_GATE_FAST_PATH=DOCUMENTATION_ONLY"),
        )
        self.assertIn("CHANGED_GATE_FAST_PATH=DOCUMENTATION_ONLY", completed.stdout)
        self.assertNotIn("GATE_STAGE=RUN NAME=rf_multipole_domain_tests", completed.stdout)
        self.assertNotIn(
            "GATE_STAGE=RUN NAME=rf_multipole_quadrupole_static",
            completed.stdout,
        )

    def test_accelerator_provider_and_shared_geometry_route_to_consumers(self) -> None:
        provider = self.routed_stages("src/msplatform/components/orthogonal_accelerator/accelerator_time_focus.py")
        self.assertTrue({
            "orthogonal_accelerator_static", "single_reflection_oa_tof_mass_analyzer_static",
                    } <= provider.keys())
        primitives = self.routed_stages("src/msplatform/backends/simion/gem_primitives.py")
        self.assertTrue({
            "simion_backend", "orthogonal_accelerator_static",
                    } <= primitives.keys())

    def test_accelerator_test_only_routes_preserve_actual_shared_fixture_consumers(self) -> None:
        downstream = {"instrument_assembly", "multi_reflection_tof_static",
                      "single_reflection_oa_tof_mass_analyzer_static"}
        prefix = "tests/components/orthogonal_accelerator/"
        for relative in ("analysis/test_component_focus_analysis.py",
                         "analysis/test_two_zone_geometry.py"):
            with self.subTest(relative=relative):
                stages = self.routed_stages(prefix + relative)
                self.assertIn("orthogonal_accelerator_static", stages)
                self.assertFalse(downstream & stages.keys())
        # The integration fixture imports this actual provider test module;
        # package initialization also affects that import boundary.
        for relative in ("analysis/test_bare_three_zone_component.py",
                         "__init__.py", "analysis/__init__.py"):
            with self.subTest(relative=relative):
                stages = self.routed_stages(prefix + relative)
                self.assertTrue(any(name == "instrument_assembly" or name.startswith("instrument_assembly__tests_") for name in stages), stages)
                self.assertIn("orthogonal_accelerator_static", stages)
                self.assertNotIn("multi_reflection_tof_static", stages)
                self.assertNotIn("single_reflection_oa_tof_mass_analyzer_static", stages)
        self.assertTrue(downstream <= self.routed_stages(
            "src/msplatform/components/orthogonal_accelerator/accelerator_time_focus.py").keys())
        for installed in ("src/msplatform/workflows/oa_focus_analysis.py",
                          "src/msplatform/workflows/oa_focus_fast_adjust.py",
                          "src/msplatform/workflows/oa_focus_mr_runtime_receipt.py"):
            with self.subTest(installed=installed):
                stages = self.routed_stages(installed)
                self.assertTrue(downstream <= stages.keys())
                self.assertIn("orthogonal_accelerator_static", stages)

    def test_ip_tests_preserve_actual_integration_fixture_consumers(self) -> None:
        prefix = "tests/components/ion_processor/"
        for relative in ("test_owner_finalization_recovery.py", "test_removed.py",
                         "analysis/test_unrelated.py", "nested/test_removed.py"):
            with self.subTest(relative=relative):
                stages = self.routed_stages(
                ("src/msplatform/components/ion_processor/"
                 if relative.startswith("analysis/") and not relative.startswith("analysis/test_") else prefix) + relative)
                self.assertIn("ion_processor_static", stages)
                self.assertNotIn("instrument_assembly", stages)
        for relative in ("test_component_exit.py",
                         "test_functional.py", "__init__.py",
                         "test_support/unknown_helper.py", "test_support/test_helper.py",
                         "nested/support/test_helper.py", "analysis/retained_provider.py",
                         "analysis/unknown_provider.py", "run_future.ps1"):
            with self.subTest(relative=relative):
                stages = self.routed_stages(
                ("src/msplatform/components/ion_processor/"
                 if relative.startswith("analysis/") and not relative.startswith("analysis/test_") else prefix) + relative)
                self.assertIn("ion_processor_static", stages)
                self.assertIn("instrument_assembly", stages)

    def test_extracted_mechanisms_keep_automatic_regression_routes(self) -> None:
        for implementation, stage, module in (
            ("src/msplatform/contracts/expected_values.py", "machine_contracts",
             "tests.contracts.test_expected_values"),
            ("src/msplatform/analysis/longitudinal_fit.py", "longitudinal_fit_tests",
             "tests.analysis.test_longitudinal_fit"),
        ):
            with self.subTest(implementation=implementation):
                self.assertIn(stage, self.routed_stages(implementation))
                route = next(row for row in self.routes if row["stage"] == stage)
                self.assertIn(route["repository_gate_group"], {"fast", "regression", "covered"})
                if stage == "machine_contracts":
                    request, _ = self.plan("-ChangedPath", implementation)
                    arguments = [arg for row in request["stages"] if row["name"] == stage or row["name"].startswith(stage + "__tests_") for arg in row["command"]["arguments"]]
                    self.assertIn(module, [arg.removesuffix(".py").replace("/", ".") for arg in arguments])
                else:
                    self.assertIn(module, route["command"]["arguments"])
        self.assertTrue({
            "single_reflection_oa_tof_mass_analyzer_static",
                    } <= self.routed_stages("src/msplatform/analysis/longitudinal_fit.py").keys())
        self.assertIn("orthogonal_accelerator_static",
                      self.routed_stages("src/msplatform/contracts/expected_values.py"))
        self.assertTrue({"single_reflection_oa_tof_mass_analyzer_static", "instrument_assembly"}
                        <= self.routed_stages("src/msplatform/analysis/field_comparison.py").keys())

    def test_host_scheduler_and_adapters_keep_regression_routes(self) -> None:
        for path, expected in (
            ("src/msplatform/execution/host_resource_scheduler.py", {"host_resource_scheduler_tests", "host_resource_adapter_tests"}),
            ("src/msplatform/execution/resources/host_resource_policy.json", {"host_resource_scheduler_tests", "host_resource_adapter_tests"}),
            ("src/msplatform/backends/comsol/launcher/run_comsol_r2025b.ps1", {"livelink_resource_stages_tests"}),
        ):
            with self.subTest(path=path):
                self.assertTrue(expected <= self.routed_stages(path).keys())
        gate_route = next(row for row in self.routes if row["stage"] == "machine_contracts")
        self.assertEqual(gate_route["command"]["runner"], "python")

    def test_python_host_bridge_uses_one_shared_scheduler_stage_in_l1_and_l2(self) -> None:
        stage = "host_resource_scheduler_tests"
        for path in ("src/msplatform/execution/host_resource_python.py", "src/msplatform/execution/resources/host_resource_python.ps1",
                     "tests/repository/test_host_resource_python.py"):
            expected = {stage}
            if path in ("src/msplatform/execution/host_resource_python.py", "src/msplatform/execution/resources/host_resource_python.ps1"):
                expected.update({"simion_dirichlet_native", "host_resource_adapter_tests", "machine_contracts"})
            if path == "src/msplatform/execution/host_resource_python.py":
                expected.add("instrument_assembly")
            self.assertEqual(set(self.routed_stages(path)), expected, path)
        routes = [route for route in self.routes if route["stage"] == stage]
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0]["dependency_profile"], "locked")
        self.assertEqual(routes[0]["repository_gate_group"], "fast")
        self.assertEqual(routes[0]["command"]["arguments"],
                         ["-m", "unittest", "tests.repository.test_host_resource_scheduler",
                          "tests.repository.test_host_resource_python", "tests.repository.test_observed_preparation_drain"])
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        result = subprocess.run([pwsh, "-NoProfile", "-File", str(CHANGED_GATE), "-PythonExe", sys.executable,
                                 "-PlanOnly", "-ChangedPath", "src/msplatform/execution/resources/host_resource_python.ps1"],
                                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
                                timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        selected = re.search(r"SELECTED_STAGES=([^\s]+)", result.stdout)
        self.assertIsNotNone(selected, result.stdout)
        self.assertEqual(selected[1].split(",").count(stage), 1)
        script = (f". '{REPO_ROOT}/tools/repository/gate_catalog_support.ps1';"
                  f"$routes=@(Read-GateCatalog -RepoRoot '{REPO_ROOT}');"
                  "$stages=@($routes|Where-Object repository_gate_group -eq 'fast'|ForEach-Object stage);"
                  "ConvertTo-Json -Compress -InputObject $stages")
        result = subprocess.run([pwsh, "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout).count(stage), 1)

    def test_integration_test_module_change_runs_only_that_module(self) -> None:
        request, _ = self.plan("-ChangedPath", "tests/execution/test_repository_bindings.py")
        integration = [row for row in request["stages"] if row["name"].startswith("instrument_assembly")]
        self.assertEqual(len(integration), 1)
        command = integration[0]["command"]
        parameters = command.get("parameters", {})
        self.assertNotIn("ChangedTestModules", parameters)
        modules = parameters.get("SelectedTestModules", command.get("arguments", [])[2:])
        modules = [value.removesuffix(".py").replace("/", ".") for value in modules]
        self.assertEqual(modules, ["tests.execution.test_repository_bindings"])
        self.assertFalse(command.get("parameters", {}).get("PreflightOnly", False))


    def test_integration_source_routes_full_gate(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        integration_root = "src/msplatform/workflows/"
        completed = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-File",
                str(CHANGED_GATE),
                "-PythonExe",
                sys.executable,
                "-ChangedPath",
                integration_root + "resources/oa_mr.ps1",
                "-PlanOnly",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True, encoding="utf-8",
            timeout=30,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("EXECUTION_MODE=FULL_CHANGED_SCOPE", completed.stdout)
        self.assertIn("instrument_assembly", completed.stdout)
        for index in range(1, 5):
            self.assertIn(f"instrument_assembly__tests_{index:02d}", completed.stdout)

    def test_routes_project_config_to_its_own_static_gate(self) -> None:
        registry = json.loads((REPO_ROOT / "config/project_registry.json").read_text(encoding="utf-8"))
        descriptors = {
            project["project_id"]: descriptor
            for project, descriptor in zip(
                registry["projects"], registry["generated_from"], strict=True
            )
        }
        project_routes = [route for route in self.routes if "project_id" in route]
        self.assertEqual({route["project_id"] for route in project_routes}, set(descriptors))
        self.assertEqual(
            len(project_routes),
            len({route["project_id"] for route in project_routes}),
        )
        for route in project_routes:
            project_id = route["project_id"]
            self.assertTrue((REPO_ROOT / route["command"]["script"]).is_file())
            selected = self.routed_stages(descriptors[project_id]["descriptor"])
            self.assertIn(route["stage"], selected)

    def test_retired_root_paths_do_not_match_the_current_catalog(self) -> None:
        retired_paths = (
            "projects/example/config/project.json",
            "projects/example/docs/history/retired_projects/former/config/project.json",
            "common/ion_release/test_release.py",
            "common/integration/__init__.py",
            "common/analysis/peak_metrics.py",
            "integrations/runtime/example.py",
        )
        for path in retired_paths:
            with self.subTest(path=path):
                self.assertEqual(self.routed_stages(path), {})

    def test_catalog_declares_dependency_and_l2_ownership_for_every_stage(self) -> None:
        self.assertEqual(self.route_contract["schema_version"], 2)
        self.assertEqual(self.route_contract["role"], "repository_gate_catalog")
        self.assertTrue({
            "contracts_registry", "machine_contracts", "simion_backend",
            "assembly_contracts", "instrument_assembly", "solidworks_exporter",
        } <= {route["stage"] for route in self.routes})
        for route in self.routes:
            self.assertIn(route["dependency_profile"], {"stdlib", "locked"})
            self.assertIn(
                route["repository_gate_group"],
                {"fast", "regression", "covered"},
            )
        integration_gates = sorted(
            path.relative_to(REPO_ROOT).as_posix()
            for path in (REPO_ROOT / "tools/repository").glob("verify_integration.ps1")
        )
        routed_integrations = sorted(
            route["command"]["script"]
            for route in self.routes
            if route["command"].get("script", "").startswith("tools/repository/")
        )
        self.assertEqual(routed_integrations, integration_gates)

    def test_multipole_variants_have_separate_routes_and_one_project_registration(self) -> None:
        stages = {f"rf_multipole_{variant}_static" for variant in ("quadrupole", "hexapole", "octupole")}
        project_routes = [route for route in self.routes if route.get("project_id") == "rf_multipole_ion_optics"]
        self.assertEqual([route["stage"] for route in project_routes], ["rf_multipole_generated_publications"])
        for variant in ("quadrupole", "hexapole", "octupole"):
            expected = f"rf_multipole_{variant}_static"
            test_directory = "analysis" if variant == "quadrupole" else variant
            paths = (
                f"src/msplatform/components/rf_multipole/variants/{variant}/config/requests/official.json",
                f"tests/components/rf_multipole_ion_optics/{test_directory}/test_contract.py",
            )
            for path in paths:
                with self.subTest(path=path):
                    selected = self.routed_stages(path)
                    self.assertEqual(stages.intersection(selected), {expected})
                    self.assertIn("rf_multipole_generated_publications", selected)
            route = next(route for route in self.routes if route["stage"] == expected)
            self.assertEqual(route["command"]["script"], "src/msplatform/workflows/resources/verify_project.ps1")
            self.assertEqual(route["command"]["parameters"]["StructuralVariant"], variant)
            self.assertEqual(route["requires_stages"], ["rf_multipole_generated_publications"])
        for path in (
            "src/msplatform/components/rf_multipole/config/project.json",
            "src/msplatform/components/rf_multipole/compile_design_request.py",
            "tests/components/rf_multipole_ion_optics/test_support/historical_contracts.py",
            "tests/components/rf_multipole_ion_optics/domain/run_production_probe.ps1",
        ):
            with self.subTest(path=path):
                self.assertTrue(stages.issubset(self.routed_stages(path)))
        for old in ("rf_quadrupole_ion_optics", "rf_hexapole_ion_optics", "rf_octupole_ion_optics"):
            self.assertFalse(any(route.get("project_id") == old for route in self.routes))
            self.assertFalse(any(route["command"].get("script") == f"projects/{old}/verify_project.ps1" for route in self.routes))

    def test_variant_plan_includes_freshness_and_only_its_static_selection(self) -> None:
        stages = {f"rf_multipole_{variant}_static" for variant in ("quadrupole", "hexapole", "octupole")}
        for variant in ("quadrupole", "hexapole", "octupole"):
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(CHANGED_GATE),
                 "-PythonExe", sys.executable, "-PlanOnly", "-ChangedPath",
                 f"src/msplatform/components/rf_multipole/variants/{variant}/config/requests/official.json"],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            selected = re.search(r"SELECTED_STAGES=([^\s]+)", completed.stdout)
            self.assertIsNotNone(selected, completed.stdout)
            selected_stages = set(selected.group(1).split(","))
            self.assertEqual(stages.intersection(selected_stages), {f"rf_multipole_{variant}_static"})
            self.assertIn("rf_multipole_generated_publications", selected_stages)


    def test_field_plan_dependency_uses_actual_selected_consumers_without_duplicates(self):
        source = 'src/msplatform/backends/simion/field_plan.py'
        route = next(row for row in self.routes if row['stage'] == 'instrument_assembly')
        roots = ('tests/assembly', 'tests/workflows', 'tests/execution')
        full = {'.'.join(path.relative_to(REPO_ROOT).with_suffix('').parts)
                for root in roots for path in (REPO_ROOT / root).rglob('test_*.py')}
        expected = {module for module in full
                    if (module.rsplit('.', 1)[-1].startswith('test_single_reflection_') and
                        not module.endswith('test_single_reflection_checkpoint_diagnostics')) or
                    module.rsplit('.', 1)[-1] in ('test_dependencies', 'test_native_path_consumers')}
        cases = [(('-ChangedPath', source), expected)]
        for parent, name in (
                ('src/msplatform/workflows/', 'pulse_execution.py'),
                ('src/msplatform/backends/simion/', 'downstream_fields.py'),
                ('src/msplatform/contracts/schemas/', 'single_reflection_request_v11.schema.json')):
            cases.append((('-ChangedPath', parent + name), expected))
        path = 'tests/assembly/oa_mr_execute/test_oa_mr_execute.py'
        cases.append((('-ChangedPath', source, path), expected | {path[:-3].replace('/', '.')}))
        retired = 'tests/workflows/paired_accelerator/test_paired_accelerator_static_field_execute.py'
        self.assertFalse((REPO_ROOT / retired).exists())
        cases.append((('-ChangedPath', source, retired), full))
        cases += [(('-Scope', 'Owner', '-Owner', 'instrument_assembly'), full),
                  (('-Scope', 'Repository'), full)]
        for arguments, wanted in cases:
            with self.subTest(arguments=arguments):
                if arguments[0] == '-ChangedPath' and len(arguments) == 3:
                    with tempfile.TemporaryDirectory(prefix='field_plan_mixed_') as directory:
                        request = Path(directory) / 'plan.json'
                        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
                        selected = ','.join(quote(value) for value in arguments[1:])
                        script = (f"& {quote(CHANGED_GATE)} -PythonExe {quote(sys.executable)} "
                                  f"-PlanOnly -PlanPath {quote(request)} -ChangedPath @({selected})")
                        process = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-Command', script],
                            cwd=REPO_ROOT, capture_output=True, text=True, encoding='utf-8', timeout=40)
                        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                        plan = json.loads(request.read_text(encoding='utf-8-sig'))
                else:
                    plan, _ = self.plan(*arguments)
                rows = [row for row in plan['stages']
                        if row['name'].startswith('instrument_assembly')]
                modules = []
                for row in rows:
                    command = row['command']
                    self.assertEqual(command['runner'], 'powershell')
                    parameters = command['parameters']
                    self.assertNotIn('ChangedTestModules', parameters)
                    if not parameters.get('PreflightOnly', False):
                        modules.extend(parameters['SelectedTestModules'])
                self.assertCountEqual(modules, wanted)
                self.assertEqual(len(modules), len(set(modules)))
                self.assertTrue(all(row['dependency_profile'] == route['dependency_profile'] for row in rows))

    def test_field_plan_mapping_keeps_missing_unknown_and_renamed_source_conservative(self):
        source = 'src/msplatform/backends/simion/field_plan.py'
        route = next(row for row in self.routes if row['stage'] == 'instrument_assembly')
        dependency = next(row for row in route['test_selection']['dependencies']
                          if any(match.get('exact') == source for match in row['matches']))
        expected = set(dependency['modules'])
        with tempfile.TemporaryDirectory(prefix='field_plan_selection_') as directory:
            root = Path(directory)
            paths = {path.relative_to(REPO_ROOT).as_posix()
                     for test_root in ('tests/assembly', 'tests/workflows', 'tests/execution')
                     for path in (REPO_ROOT / test_root).rglob('test_*.py')}
            for relative in paths | {source}:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('# inert selector input, never executed\n', encoding='utf-8')
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            script = f"""
$ErrorActionPreference='Stop'
. {quote(REPO_ROOT / 'tools/repository/gate_catalog_support.ps1')}
$route=(Get-Content {quote(ROUTE_TABLE)} -Raw|ConvertFrom-Json -Depth 64).routes|Where-Object stage -eq instrument_assembly
$root={quote(root)};$source={quote(source)}
$parameters=@{{Route=$route;KnownTestRoots=@('tests/assembly/','tests/workflows/','tests/execution/');RepoRoot=$root}}
$result=@{{known=@((Get-GateChangedTests @parameters -ChangedPaths @($source)).Modules)}}
$result.unknown=$null-eq(Get-GateChangedTests @parameters -ChangedPaths @('src/msplatform/workflows/future.py'))
Remove-Item -LiteralPath (Join-Path $root $source)
$result.deleted=$null-eq(Get-GateChangedTests @parameters -ChangedPaths @($source))
$result.renamed=$null-eq(Get-GateChangedTests @parameters -ChangedPaths @($source,'src/msplatform/workflows/renamed.py'))
$result.full=@((Get-GateChangedTests @parameters -ChangedPaths @($source) -FullScope).Modules)
$result|ConvertTo-Json -Compress
"""
            process = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-Command', script], cwd=root,
                capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            result = json.loads(process.stdout)
            self.assertEqual(set(result['known']), expected)
            # Outside test roots an unknown/deleted authority returns no narrow
            # selection; the normal planner then retains the complete owner.
            for name in ('unknown', 'deleted', 'renamed'):
                self.assertTrue(result[name])
            self.assertEqual(set(result['full']), paths)

    def test_direct_integration_gate_owns_only_its_tests(self) -> None:
        for path in ("tests/execution/test_dependencies.py",
                     "src/msplatform/workflows/config/runtime_dependencies.json",
                     "tools/repository/verify_integration.ps1",
                     "src/msplatform/execution/resources/dependencies.ps1",
                     "src/msplatform/workflows/native_tracing.py",
                     "src/msplatform/backends/simion/tracking_collection.py"):
            with self.subTest(path=path):
                expected = {"instrument_assembly"}
                if path in {
                    "src/msplatform/workflows/config/runtime_dependencies.json",
                    "src/msplatform/workflows/native_tracing.py",
                    "src/msplatform/backends/simion/tracking_collection.py",
                }:
                    expected.add("machine_contracts")
                elif path == "src/msplatform/execution/resources/dependencies.ps1":
                    expected.update(("machine_contracts", "host_resource_adapter_tests",
                                     "host_resource_scheduler_tests"))
                if path == "src/msplatform/backends/simion/tracking_collection.py":
                    expected.update(("simion_backend", "single_reflection_oa_tof_mass_analyzer_static",
                        "rf_multipole_domain_tests", "rf_multipole_generated_publications",
                        "rf_multipole_quadrupole_static", "rf_multipole_hexapole_static",
                        "rf_multipole_octupole_static"))
                self.assertEqual(set(self.routed_stages(path)), expected)


    def test_installed_paired_pulse_analysis_routes_real_consumers(self) -> None:
        for path in ("src/msplatform/analysis/paired_accelerator_pulse.py",
                     "src/msplatform/backends/comsol/prepulse_replay.py"):
            with self.subTest(path=path):
                self.assertEqual(set(self.routed_stages(path)),
                                 {"machine_contracts", "instrument_assembly"})


    def test_installed_bare_frontend_routes_all_actual_owners(self) -> None:
        self.assertEqual(set(self.routed_stages("src/msplatform/backends/simion/bare_frontend_geometry.py")),
                         {"instrument_assembly", "machine_contracts", "single_reflection_oa_tof_mass_analyzer_static",
                          "orthogonal_accelerator_static", "simion_backend", "rf_multipole_domain_tests",
                          "rf_multipole_generated_publications", "rf_multipole_quadrupole_static",
                          "rf_multipole_hexapole_static", "rf_multipole_octupole_static"})

    def test_direct_integration_gate_routes_its_declared_frozen_dependencies(self) -> None:
        inventory = json.loads((REPO_ROOT / "src/msplatform/workflows/config/runtime_dependencies.json").read_text(encoding="utf-8"))
        for group in inventory["providers"]:
            for dependency in group["files"] + group["python_modules"]:
                with self.subTest(dependency=dependency["source_repo_path"]):
                    self.assertIn("instrument_assembly", self.routed_stages(dependency["source_repo_path"]))
            for package in group["python_packages"]:
                for suffix in ("new_module.py", "nested/deleted_module.py"):
                    with self.subTest(package=package["source_repo_path"], suffix=suffix):
                        self.assertIn("instrument_assembly", self.routed_stages(package["source_repo_path"] + "/" + suffix))

    def test_installed_mesh_resources_real_plan_selects_exact_owner_modules(self) -> None:
        base = 'src/msplatform/backends/comsol/matlab/'
        for name in ('configure_comsol_mesh.m','add_comsol_size_feature.m','read_comsol_mesh_size_controls.m'):
            with self.subTest(name=name):
                request, _ = self.plan('-ChangedPath', base + name)
                selected = [row for row in request['stages'] if row['selected']]
                def rows_for(stage):
                    return [row for row in selected if row['name'] == stage or row['name'].startswith(stage + '__tests_')]
                contracts = rows_for('machine_contracts')
                self.assertTrue(contracts)
                self.assert_complete_contract_modules(contracts, {'tests.contracts.test_installed_scientific_core'})
                quad = rows_for('rf_multipole_quadrupole_static')
                self.assertTrue(quad)
                rf_modules = [contract_test_path(value) for row in quad for value in row['command'].get('parameters', {}).get('ChangedTestModules', [])]
                self.assertCountEqual(rf_modules, [
                    'tests/components/rf_multipole_ion_optics/analysis/test_frozen_matlab_closure.py',
                    'tests/components/rf_multipole_ion_optics/analysis/test_comsol_mesh_report.py'])
                shared = name != 'configure_comsol_mesh.m'
                oa = rows_for('single_reflection_oa_tof_mass_analyzer_static')
                integration = rows_for('instrument_assembly')
                self.assertEqual(bool(oa), shared); self.assertEqual(bool(integration), shared)
                if shared:
                    oa_modules = [contract_test_path(value) for row in oa for value in row['command'].get('parameters', {}).get('SelectedTestModules', [])]
                    self.assertCountEqual(oa_modules, [
                        'tests/components/single_reflection_oa_tof_mass_analyzer/analysis/test_candidate_workflow.py',
                        'tests/components/single_reflection_oa_tof_mass_analyzer/analysis/test_candidate_causal_workflow.py',
                        'tests/components/single_reflection_oa_tof_mass_analyzer/analysis/test_candidate_postprocess_workflow.py',
                        'tests/components/single_reflection_oa_tof_mass_analyzer/analysis/test_paired_accelerator_field_adapters.py'])
                    integration_modules = [contract_test_path(value) for row in integration for value in row['command'].get('parameters', {}).get('SelectedTestModules', [])]
                    self.assertEqual(integration_modules, ['tests/workflows/paired_accelerator/test_paired_accelerator_static_field_execute.py'])
                for stage in ('rf_multipole_domain_tests','rf_multipole_hexapole_static','rf_multipole_octupole_static',
                              'transverse_helical_filament_wehnelt_electron_gun_static','apertured_tube_electron_impact_ion_source_static'):
                    self.assertFalse(rows_for(stage), stage)

    def test_runtime_dependency_paths_select_the_real_integration_plan(self) -> None:
        # These newly consumed geometry/export paths previously escaped L1 routing.
        paths = [
            "src/msplatform/backends/comsol/matlab/add_comsol_size_feature.m",
            "src/msplatform/analysis/vector_field_samples.py",
            "src/msplatform/analysis/field_comparison.py",
            "src/msplatform/backends/comsol/matlab/build_and_export_paired_accelerator_field.m",
            "src/msplatform/backends/comsol/matlab/oatof_build_accelerator_geometry.m",
            "src/msplatform/backends/comsol/matlab/oatof_build_grid_geometry.m",
            "src/msplatform/backends/comsol/matlab/oatof_read_cartesian_release.m",
            "src/msplatform/backends/comsol/matlab/oatof_cpt_solver_policy.m",
            "src/msplatform/backends/comsol/matlab/run_paired_accelerator_pulse.m",
            "src/msplatform/backends/simion/resources/export_paired_accelerator_field.lua",
            "src/msplatform/backends/simion/resources/paired_accelerator_pulse.lua",
        ]
        for path in paths:
            with self.subTest(path=path):
                result = self._runtime_dependency_plan(REPO_ROOT, path)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                selected = re.search(r"SELECTED_STAGES=([^\s]+)", result.stdout)
                self.assertIsNotNone(selected, result.stdout)
                selected_stages = selected[1].split(",")
                if path.rsplit("/", 1)[-1] in {"build_and_export_paired_accelerator_field.m",
                        "oatof_build_accelerator_geometry.m", "oatof_build_grid_geometry.m"}:
                    self.assertFalse(any(name == "instrument_assembly" or name.startswith("instrument_assembly__tests_") for name in selected_stages), selected[1])
                    self.assertIn("single_reflection_oa_tof_mass_analyzer_static", selected_stages)
                    continue
                self.assertIn("instrument_assembly", result.stdout)
                self.assertTrue(any(name == "instrument_assembly" or name.startswith("instrument_assembly__tests_") for name in selected_stages), selected[1])

    @staticmethod
    def _runtime_dependency_plan(repo: Path, changed_path: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [shutil.which("pwsh"), "-NoProfile", "-File", str(repo / "tools/repository/verify.ps1"),
             "-PythonExe", sys.executable, "-PlanOnly", "-ChangedPath", changed_path],
            cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )


    def test_direct_integration_test_plan_selects_its_own_gate(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        completed = subprocess.run(
            [pwsh, "-NoProfile", "-File", str(CHANGED_GATE), "-PlanOnly",
             "-PythonExe", sys.executable, "-ChangedPath", "tests/execution/test_dependencies.py"],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        selected = re.search(r"SELECTED_STAGES=([^\s]+)", completed.stdout)
        self.assertIsNotNone(selected, completed.stdout)
        stages = selected.group(1).split(",")
        self.assertTrue(any(name == "instrument_assembly" or name.startswith("instrument_assembly__tests_") for name in stages), stages)
        self.assertNotIn("rf_multipole_to_single_reflection_oatof_integration", stages)

    def test_mrtof_uses_fast_changed_gate_and_complete_solver_free_l2_gate(self) -> None:
        route = next(
            item for item in self.routes
            if item.get("project_id") == "multi_reflection_tof"
        )
        self.assertEqual(
            route["command"]["parameters"],
            {"Level": "Core", "PythonExe": "{python}"},
        )
        self.assertEqual(
            route["repository_gate_command"]["parameters"],
            {"Level": "Static", "PythonExe": "{python}", "PreflightOnly": True},
        )
        self.assertEqual(route["repository_gate_partition"]["parameter"], "SelectedTestModules")
        self.assertNotIn("SimionExe", json.dumps(route))

    def test_l2_mr_partitions_cover_the_actual_owner_discovery_once(self) -> None:
        script = (". ./tools/repository/gate_catalog_support.ps1; "
                  "$route=@(Read-GateCatalog -RepoRoot $PWD.Path | Where-Object "
                  "stage -eq 'multi_reflection_tof_static')[0]; "
                  "$groups=@(Get-GateRepositoryTestPartitions -Route $route -RepoRoot $PWD.Path); "
                  "ConvertTo-Json -Compress -Depth 8 -InputObject @($groups | ForEach-Object { "
                  "[pscustomobject]@{modules=@($_.modules);seconds=$_.seconds} })")
        result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script],
                                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        groups = json.loads(result.stdout)
        names = [name for group in groups for name in group["modules"]]
        test_root = REPO_ROOT / "tests/components/multi_reflection_tof"
        expected = [".".join(path.relative_to(REPO_ROOT).with_suffix("").parts)
                    for path in test_root.rglob("test_*.py")]
        self.assertCountEqual(names, expected)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(groups), 4)
        self.assertTrue(all(group["seconds"] > 0 for group in groups))

    def test_l1_partitions_only_semantically_complete_owner_commands(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        script = r'''. ./tools/repository/gate_catalog_support.ps1
$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $PWD 'tools/repository/verify.ps1'),[ref]$null,[ref]$errors)
$node=$ast.Find({param($a)$a-is[Management.Automation.Language.FunctionDefinitionAst]-and$a.Name-eq'Test-CompletePartitionOwnerCommand'},$true)
Invoke-Expression $node.Extent.Text
$routes=@(Read-GateCatalog -RepoRoot $PWD.Path)
$mr=$routes|Where-Object stage -eq 'multi_reflection_tof_static'
$integration=$routes|Where-Object stage -eq 'instrument_assembly'
$full=$mr.repository_gate_command|ConvertTo-Json -Depth 16|ConvertFrom-Json -Depth 16
$full.parameters.PSObject.Properties.Remove('PreflightOnly')
@{mr_core=(Test-CompletePartitionOwnerCommand $mr $mr.command);mr_full=(Test-CompletePartitionOwnerCommand $mr $full);integration_full=(Test-CompletePartitionOwnerCommand $integration $integration.command)}|ConvertTo-Json -Compress
'''
        result = subprocess.run([pwsh, "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), dict(mr_core=False, mr_full=True, integration_full=True))
        result = subprocess.run([pwsh, "-NoProfile", "-File", str(CHANGED_GATE), "-PythonExe", sys.executable,
            "-PlanOnly", "-ChangedPath", "src/msplatform/backends/simion/native_corridor_plan.py"],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("multi_reflection_tof_static", result.stdout)
        self.assertNotIn("multi_reflection_tof_static__tests_", result.stdout)

    def test_mr_partition_preflight_cannot_claim_a_full_gate(self) -> None:
        gate = REPO_ROOT / "src/msplatform/workflows/resources/mr_verify.ps1"
        module = "tests.components.multi_reflection_tof.analysis.test_drift_phase_contract"
        script = ("& '" + str(gate).replace("'", "''") + "' -Level Static -PythonExe '" +
                  sys.executable.replace("'", "''") + "' -SelectedTestModules @('" + module +
                  "') -PreflightValidated")
        result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("MRTOF_TEST_PARTITION=PASS PREFLIGHT_PREVALIDATED=True FULL_PROJECT_GATE=False", result.stdout)
        self.assertNotIn("PROJECT_REGISTRY=PASS", result.stdout)
        self.assertNotIn("PROJECT_GATE=PASS", result.stdout)
        invalid = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(gate),
                                  "-Level", "Static", "-PreflightValidated"], cwd=REPO_ROOT,
                                 capture_output=True, text=True, encoding="utf-8", timeout=45)
        self.assertNotEqual(invalid.returncode, 0)

    def test_plan_mode_is_fail_closed_for_dependency_selection(self) -> None:
        cases=[("CHANGELOG.md","stdlib"),("README.md","stdlib"),
               ("src/msplatform/components/rf_multipole/README.md","stdlib"),("tools/repository/README.md","stdlib")]
        cases += [(path,"locked") for path in ("tools/repository/gate_catalog_support.ps1","tools/repository/verify.ps1",
                  "tests/contracts/test_verify_changed.py",".github/workflows/lightweight-gate.yml",
                  "pyproject.toml","config/project_registry.json","src/msplatform/components/rf_multipole/config/project.json")]
        outputs=self.batch_plan_outputs([((path,),False) for path,_ in cases])
        for (path,expected),output in zip(cases,outputs):
            with self.subTest(path=path):
                match=re.search(r"DEPENDENCY_PROFILE=(stdlib|locked)",output)
                self.assertIsNotNone(match,output)
                self.assertEqual(match.group(1),expected)


    def test_history_text_snapshots_use_only_the_documentation_fast_path(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        project = "projects/multi_reflection_tof/"
        snapshot = project + "docs/history/20261015__cad-exchange/CAD.before.txt"
        cases = (
            (("tools/repository/README.md",), False, True),
            (("docs/DEVELOPMENT_STANDARDS.md",), False, False),
            (("src/msplatform/execution/resources/artifact_capacity_policy.json",), False, False),
            (("config/unknown_scope.json",), False, False),
            ((project + "docs/CAD.md", snapshot), False, True),
            ((snapshot,), False, True),
            (("docs/history/20261015__milestone/PROJECT.before.txt",), False, True),
            (("integrations/example/docs/history/20261015__milestone/PROJECT.before.txt",), False, True),
            ((project + "docs/CAD.before.txt",), False, False),
            ((project + "config/project.json",), False, False),
            ((project + "docs/history/x/snapshot_manifest.json",), False, False),
            ((project + "docs/history/x/old.py",), False, False),
            ((project + "docs/history/x/nested/CAD.before.txt",), False, False),
            ((project + "docs/history/CAD.before.txt",), False, False),
            ((snapshot, project + "analysis/simion_event_analysis.py"), False, False),
            ((), True, False),
        )
        outputs=self.batch_plan_outputs([(paths,full) for paths,full,_ in cases])
        for (paths,full_scope,documentation_only),output in zip(cases,outputs):
            with self.subTest(paths=paths,full_scope=full_scope):
                mode = "DOCUMENTATION_ONLY" if documentation_only else "FULL_CHANGED_SCOPE"
                self.assertIn(f"EXECUTION_MODE={mode}", output)
                if documentation_only:
                    self.assertIn(
                        "EFFECTIVE_STAGES=repository_hygiene,repository_text_bytes,documentation",
                        output,
                    )
                    self.assertRegex(output, r"SELECTED_STAGES=[^\r\n]*\bdocumentation\b")
                else:
                    self.assertRegex(output, r"EFFECTIVE_STAGES=[^\r\n]*\bdevelopment_standards\b")

    def test_real_development_stage_uses_changed_paths_and_removes_transport_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="standards_changed_stage_") as directory:
            root = Path(directory)
            request, log = root / "request.json", root / "stage.log"
            from tests.contracts.test_changed_test_selection import write_planned_request
            write_planned_request(REPO_ROOT, request, ["tests/contracts/test_expected_values.py"])
            result = subprocess.run([
                shutil.which("pwsh"), "-NoProfile", "-File", str(CHANGED_GATE),
                "-InternalStage", "development_standards", "-InternalRequestPath", str(request),
                "-InternalLogPath", str(log),
            ], cwd=REPO_ROOT, timeout=60, capture_output=True, text=True, encoding="utf-8",
                env=dict(os.environ, TEMP=directory, TMP=directory, PYTHONDONTWRITEBYTECODE="1"))
            output = result.stdout + result.stderr + (log.read_text(encoding="utf-8") if log.exists() else "")
            self.assertEqual(result.returncode, 0, output)
            self.assertIn("DEVELOPMENT_SCOPE=CHANGED REASON=explicit_changed_paths", output)
            self.assertIn("GATE_STAGE=PASS NAME=development_standards", output)
            self.assertEqual(list(root.glob("tmp*.tmp")), [])

    def test_internal_stage_executes_resolved_command_without_replanning(self) -> None:
        from tests.contracts.test_changed_test_selection import write_planned_request
        with tempfile.TemporaryDirectory(prefix="resolved_gate_stage_") as directory:
            root = Path(directory)
            common = root / "tools/repository"
            common.mkdir(parents=True)
            (root / "src/msplatform/components").mkdir(parents=True)
            for name in ("verify.ps1", "parallel_gate_support.ps1", "gate_catalog_support.ps1",
                         "require_powershell7.ps1", "resource_process_support.ps1"):
                source = REPO_ROOT / ("src/msplatform/execution/resources" if name in ("require_powershell7.ps1", "resource_process_support.ps1") else "tools/repository") / name
                destination = root / ("src/msplatform/execution/resources" if name in ("require_powershell7.ps1", "resource_process_support.ps1") else "tools/repository") / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            (common / "host_execution_lease.ps1").write_text(
                "function Get-HostResourceBudget { param($Stage,$Role) return @{} }\n"
                "function Enter-HostResourceStage { param($Role,$Stage,$Budget) return @{} }\n"
                "function Exit-HostResourceStage { param($Lease) }\n", encoding="utf-8")
            catalog = {"schema_version": 2, "role": "repository_gate_catalog", "routes": [{
                "stage": "probe", "dependency_profile": "stdlib", "repository_gate_group": "fast",
                "matches": [{"exact": "probe.py", "reason": "probe_changed"}],
                "command": {"runner": "python", "arguments": ["-c", "print('RESOLVED_STAGE_RAN')"]},
            }]}
            catalog_path = common / "gate_catalog.json"
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
            request = root / "request.json"
            write_planned_request(root, request, ["probe.py"])
            # The already planned child must not rediscover catalog/routes or
            # enumerate unrelated test modules after the parent planned them.
            catalog_path.unlink()
            for failed in (False, True):
                planned = json.loads(request.read_text(encoding="utf-8-sig"))
                probe = next(stage for stage in planned["stages"] if stage["name"] == "probe")
                probe["command"]["arguments"][-1] = "print('RESOLVED_STAGE_RAN'); raise SystemExit(" + str(7 if failed else 0) + ")"
                request.write_text(json.dumps(planned), encoding="utf-8")
                for gate in ("verify.ps1",):
                    log = root / "stage.log"
                    result = subprocess.run(["pwsh", "-NoProfile", "-File", str(common / gate),
                        "-InternalStage", "probe", "-InternalRequestPath", str(request), "-InternalLogPath", str(log)],
                        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30)
                    self.assertEqual(result.returncode != 0, failed, result.stdout + result.stderr)
                    self.assertIn("RESOLVED_STAGE_RAN", log.read_text(encoding="utf-8"))
                    sidecar = json.loads(log.with_name("stage.log.result.json").read_text(encoding="utf-8"))
                    self.assertEqual(sidecar["status"], "FAIL" if failed else "PASS")

    def test_specialized_schemas_use_owner_and_metadata_without_directory_fanout(self) -> None:
        stages = self.routed_stages("src/msplatform/contracts/schemas/oatof_three_zone_stage_report.schema.json")
        self.assertEqual(set(stages), {"machine_contracts", "single_reflection_oa_tof_mass_analyzer_static",
                                      "instrument_assembly"})
        for path in ("src/msplatform/contracts/schemas/future_unknown.schema.json",
                     "src/msplatform/contracts/machine_contracts.py", "src/msplatform/execution/resources/run_artifact_support.ps1"):
            with self.subTest(path=path):
                self.assertIn("machine_contracts", self.routed_stages(path))
                self.assertIn("rf_multipole_quadrupole_static", self.routed_stages(path))
        actual_consumer = self.routed_stages("src/msplatform/contracts/schemas/multipole_resolved_design.schema.json")
        self.assertIn("instrument_assembly", actual_consumer)



    def test_ci_command_wall_clock_preserves_live_output_exit_and_summary(self) -> None:
        workflow = LIGHTWEIGHT_WORKFLOW.read_text(encoding="utf-8")
        programs = re.findall(r"(?ms)^          @'\n(.*?)^          '@ \| & \$python -$", workflow)
        self.assertEqual(len(programs), 1)
        self.assertEqual(workflow.count("run: *gate_command"), 1)
        projections = re.findall(r"PUBLIC_GATE_SCOPE_FILE: (\S+)\n          PUBLIC_GATE_OUTPUT_PREFIX: (\S+)", workflow)
        self.assertEqual(projections, [("changed_scope.json", "changed"), ("repository_scope.json", "repository")])
        fixture = r'''param($PlanPath,$MaxConcurrency,$ResourceWaitTimeoutSeconds,$SummaryPath)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
@{role='ci_gate_fixture';elapsed_seconds=0.005;stages=@()}|ConvertTo-Json|Set-Content -LiteralPath $SummaryPath -Encoding utf8
Write-Output ('CI_FIXTURE_ARGUMENTS='+(@{plan_path=$PlanPath}|ConvertTo-Json -Compress))
Write-Output 'CI_FIRST_OUTPUT_BEFORE_EXIT'
while(-not(Test-Path -LiteralPath $env:CI_FIXTURE_RELEASE)){Start-Sleep -Milliseconds 10}
if($env:CI_FIXTURE_EXIT-ne'0'){[Console]::Error.WriteLine('CI_NATIVE_FAILURE')}
exit ([int]$env:CI_FIXTURE_EXIT)
'''
        with tempfile.TemporaryDirectory(prefix="ci_command_clock_") as directory:
            root = Path(directory).resolve()
            common = root / "tools/repository"
            common.mkdir(parents=True)
            for name in ("verify.ps1",):
                (common / name).write_text(fixture, encoding="utf-8")
            # The real CI wrapper imports its pure report provider before scope
            # validation; keep that dependency in this detached software fixture.
            shutil.copyfile(REPO_ROOT / "tools/repository/gate_outcome_report.py", common / "gate_outcome_report.py")
            for job, full_scope, code in ((0, False, 0), (0, False, 7), (0, True, 0), (1, False, 0), (1, False, 7), (2, False, 0), (2, False, 7)):
                with self.subTest(job=job, full_scope=full_scope, code=code):
                    scope = {"full_scope": full_scope, "changed_paths": ["owner/含空格 file.py", "docs/README.md"]}
                    scope_file, prefix = projections[0 if job == 0 else 1]
                    if job == 1:
                        scope = {"scope": "Owner", "owner": "fixture_group"}
                    elif job == 2:
                        scope = {"scope": "Repository"}
                    (root / scope_file).write_text(json.dumps(scope), encoding="utf-8")
                    release = root / f"release_{job}_{full_scope}_{code}"
                    environment = dict(os.environ, RUNNER_TEMP=str(root), PUBLIC_GATE_POWERSHELL=shutil.which("pwsh"),
                        PUBLIC_GATE_SCOPE_FILE=scope_file, PUBLIC_GATE_OUTPUT_PREFIX=prefix,
                        CI_FIXTURE_RELEASE=str(release), CI_FIXTURE_EXIT=str(code))
                    process = subprocess.Popen([sys.executable, "-c", textwrap.dedent(programs[0])], cwd=root,
                        env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
                    lines: list[str] = []
                    observed: Queue[str] = Queue()

                    def read_output() -> None:
                        for line in process.stdout:
                            lines.append(line)
                            observed.put(line)

                    reader = threading.Thread(target=read_output, daemon=True)
                    reader.start()
                    try:
                        deadline = time.monotonic() + 30
                        found = False
                        while time.monotonic() < deadline and not found:
                            try:
                                found = "CI_FIRST_OUTPUT_BEFORE_EXIT" in observed.get(timeout=0.1)
                            except Empty:
                                if process.poll() is not None:
                                    break
                        self.assertTrue(found, "CI wrapper buffered or lost the running gate's output")
                        self.assertIsNone(process.poll(), "root exited before the live-output observation")
                    finally:
                        release.touch()
                        process.wait(timeout=30)
                        reader.join(timeout=5)
                    stderr = process.stderr.read()
                    process.stdout.close()
                    process.stderr.close()
                    self.assertEqual(process.returncode, code, "".join(lines) + stderr)
                    prefix = "changed" if job == 0 else "repository"
                    timing = json.loads((root / f"{prefix}_gate_command_timing.json").read_text())
                    self.assertEqual(timing["exit_code"], code)
                    self.assertGreater(timing["elapsed_wall_seconds"], 0.005)
                    self.assertEqual(timing["environment"]["python_executable"], sys.executable)
                    summary = json.loads(Path(timing["summary_path"]).read_text(encoding="utf-8-sig"))
                    self.assertEqual(summary, {"role": "ci_gate_fixture", "elapsed_seconds": 0.005, "stages": []})
                    outcomes = json.loads((root / f"{prefix}_gate_test_outcomes.json").read_text())
                    self.assertEqual(outcomes["role"], "gate_outcome_report")
                    self.assertEqual(outcomes["executions"], [])
                    arguments = json.loads(next(line.split("=", 1)[1] for line in lines if line.startswith("CI_FIXTURE_ARGUMENTS=")))
                    self.assertEqual(timing["scope"], scope)
                    self.assertEqual(Path(arguments["plan_path"]), root / "software_gate_plan.json")
                    if code:
                        self.assertIn("CI_NATIVE_FAILURE", stderr)
            for scope_file, prefix in projections:
                for invalid in ("missing", "malformed"):
                    with self.subTest(scope_file=scope_file, invalid=invalid):
                        scope_path = root / scope_file
                        if invalid == "missing":
                            scope_path.unlink(missing_ok=True)
                        else:
                            scope_path.write_text("{invalid-json", encoding="utf-8")
                        release = root / "invalid_scope_release"
                        release.touch()
                        environment = dict(os.environ, RUNNER_TEMP=str(root), PUBLIC_GATE_POWERSHELL=shutil.which("pwsh"),
                            PUBLIC_GATE_SCOPE_FILE=scope_file, PUBLIC_GATE_OUTPUT_PREFIX=prefix,
                            CI_FIXTURE_RELEASE=str(release), CI_FIXTURE_EXIT="0")
                        rejected = subprocess.run([sys.executable, "-c", textwrap.dedent(programs[0])], cwd=root,
                            env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30)
                        self.assertNotEqual(rejected.returncode, 0, rejected.stdout + rejected.stderr)
                        self.assertNotIn("CI_FIRST_OUTPUT_BEFORE_EXIT", rejected.stdout)
                        self.assertIn("FileNotFoundError" if invalid == "missing" else "JSONDecodeError", rejected.stderr)
        self.assertIn("${{ runner.temp }}/changed_gate_command_timing.json", workflow)
        self.assertIn("${{ runner.temp }}/repository_gate_command_timing.json", workflow)

    def test_ci_installs_checkout_core_before_planning_without_scientific_dependencies(self) -> None:
        workflow = LIGHTWEIGHT_WORKFLOW.read_text(encoding="utf-8")
        jobs = workflow.split("  changed_scope:\n", 1)[1].split("  repository_scope:\n", 1)
        self.assertEqual(len(jobs), 2)
        for job in jobs:
            with self.subTest(job=job.splitlines()[0]):
                steps = re.split(r"(?m)^      - name: ", job)[1:]
                install = [index for index, step in enumerate(steps)
                           if step.startswith("Install repository scientific core\n")]
                self.assertEqual(len(install), 1)
                setup = next(index for index, step in enumerate(steps)
                             if step.startswith("Set up Python 3.11\n"))
                planning = next(index for index, step in enumerate(steps) if "-PlanOnly" in step)
                self.assertLess(setup, install[0])
                self.assertLess(install[0], planning)
                step = steps[install[0]]
                self.assertIn("run: python -m pip install --disable-pip-version-check --no-deps .\n", step)
                self.assertNotIn("        if:", step, "stdlib planning also requires the checkout package")
                self.assertNotIn("PYTHONPATH", step)
                self.assertEqual(sum("-r requirements-lock.txt" in item for item in steps), 1)
        self.assertIn("if: steps.scope.outputs.dependency_profile == 'locked'", jobs[0])

    def test_ci_temp_setup_gives_python_canonical_fixture_paths(self) -> None:
        workflow = LIGHTWEIGHT_WORKFLOW.read_text(encoding="utf-8")
        scripts = re.findall(
            r"(?m)^      - name: Configure canonical test temporary directory\n"
            r"        shell: pwsh\n        run: \|\n((?:          .+\n)+)",
            workflow,
        )
        self.assertEqual(len(scripts), 2, "Both CI jobs must prepare their fixture root")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runner_temp = root / "runner temporary directory"
            runner_temp.mkdir()
            environment_file = root / "github_env"
            environment = {
                key: value for key, value in os.environ.items()
                if key.casefold() not in {"runner_temp", "github_env", "path"}
            }
            environment.update(
                RUNNER_TEMP=str(runner_temp), GITHUB_ENV=str(environment_file),
                PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""),
            )
            for index, script in enumerate(scripts):
                with self.subTest(job=index):
                    environment_file.write_text("", encoding="utf-8")
                    result = subprocess.run(
                        [shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-Command",
                         textwrap.dedent(script)], cwd=REPO_ROOT, env=environment,
                        capture_output=True, text=True, encoding="utf-8", timeout=30,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    exported = dict(
                        line.split("=", 1)
                        for line in environment_file.read_text(encoding="utf-8-sig").splitlines()
                    )
                    self.assertEqual(set(exported), {"TEMP", "TMP"})
                    child_environment = {
                        key: value for key, value in environment.items()
                        if key.casefold() not in {"temp", "tmp"}
                    }
                    child_environment.update(exported)
                    probe = subprocess.run(
                        [sys.executable, "-c",
                         "from pathlib import Path; import tempfile; "
                         "assert Path(tempfile.gettempdir()) == Path.cwd(); "
                         "assert Path(tempfile.mkdtemp()).parent == Path.cwd()"],
                        cwd=runner_temp, env=child_environment, capture_output=True,
                        text=True, encoding="utf-8", timeout=30,
                    )
                    self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)

    def test_documentation_gate_accepts_workspace_artifact_links(self) -> None:
        from tempfile import TemporaryDirectory

        from tools.repository.documentation_links import inspect_repository

        with TemporaryDirectory(prefix="documentation_gate_test_") as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "--quiet", str(root)], check=True, cwd=root, timeout=30)
            (root / "README.md").write_text(
                "# Entry\n[evidence](../artifacts/projects/example/runs/run/summary.json)\n"
                "[not evidence](../artifacts_other/missing.json)\n",
                encoding="utf-8",
            )
            report = inspect_repository(root)
            self.assertEqual(len(report["errors"]), 1)
            self.assertIn("artifacts_other/missing.json", report["errors"][0])

    def test_shared_dependencies_route_to_actual_consumers(self) -> None:
        multipole = self.routed_stages("src/msplatform/backends/simion/rf_particle_source.py")
        self.assertTrue(
            {
                "rf_multipole_domain_tests",
                "rf_multipole_generated_publications",
                "rf_multipole_quadrupole_static",
                "rf_multipole_hexapole_static",
                "rf_multipole_octupole_static",
            }.issubset(multipole)
        )
        self.assertIn("single_reflection_oa_tof_mass_analyzer_static", multipole)

        for shared_path in (
            "src/msplatform/backends/simion/source.py",
            "src/msplatform/backends/comsol/matlab/create_multipole_round_rods.m",
        ):
            routed = self.routed_stages(shared_path)
            self.assertIn("rf_multipole_domain_tests", routed)
            if shared_path == "src/msplatform/backends/simion/source.py":
                self.assertIn("instrument_assembly", routed)
                for consumer in (
                    "simion_backend", "rf_multipole_generated_publications",
                    "orthogonal_accelerator_static", "multi_reflection_tof_static",
                    "ion_processor_static",
                    "dual_cone_tandem_quadrupole_static",
                ):
                    self.assertIn(consumer, routed)
            for project_id in (
                "rf_multipole_quadrupole",
                "rf_multipole_hexapole",
                "rf_multipole_octupole",
            ):
                self.assertIn(f"{project_id}_static", routed)

    def test_machine_contracts_routes_to_declared_direct_consumers(self) -> None:
        routed = self.routed_stages("src/msplatform/contracts/machine_contracts.py")
        self.assertIn("machine_contracts", routed)
        self.assertIn("rf_multipole_generated_publications", routed)
        self.assertIn("instrument_assembly", routed)
        for project_id in (
            "single_reflection_oa_tof_mass_analyzer",
            "rf_multipole_quadrupole",
            "rf_multipole_hexapole",
            "rf_multipole_octupole",
            "dual_cone_tandem_quadrupole",
            "transverse_helical_filament_wehnelt_electron_gun",
            "apertured_tube_electron_impact_ion_source",
        ):
            self.assertIn(f"{project_id}_static", routed)

    def test_common_contract_tests_do_not_route_to_runtime_consumers(self) -> None:
        routed = self.routed_stages("tests/contracts/test_verify_changed.py")
        self.assertEqual(
            routed,
            {"machine_contracts": routed["machine_contracts"]},
        )

    def test_shared_workflow_fixture_selects_actual_consumers_and_unknown_stays_conservative(self) -> None:
        rf = "tests.components.rf_multipole_ion_optics.analysis."
        single = "tests.components.single_reflection_oa_tof_mass_analyzer.analysis."
        expected = {
            "instrument_assembly": ["tests.workflows.single_reflection.test_single_reflection_owner_recovery"],
            "rf_multipole_quadrupole_static": [rf + name for name in (
                "test_comsol_owner_finalization", "test_owner_finalization_recovery", "test_simion_powershell_owner")],
            "single_reflection_oa_tof_mass_analyzer_static": [single + name for name in (
                "test_candidate_workflow", "test_candidate_causal_workflow", "test_candidate_postprocess_workflow")],
        }

        def selected_modules(request, owner):
            return [module for row in request["stages"] if row["selected"] and
                    (row["name"] == owner or row["name"].startswith(owner + "__tests_"))
                    for parameter in ("SelectedTestModules", "ChangedTestModules")
                    for module in row["command"].get("parameters", {}).get(parameter, [])]

        for filename in ("run_artifact_workflow.py", "__init__.py"):
            with self.subTest(fixture=filename):
                request, _ = self.plan("-ChangedPath", "tests/contracts/test_support/" + filename)
                for owner, modules in expected.items():
                    self.assertCountEqual(selected_modules(request, owner), modules, owner)
                ip = next(row for row in request["stages"] if row["name"] == "ion_processor_static")
                self.assertTrue(ip["selected"])
                self.assertEqual(ip["command"]["script"],
                                 "src/msplatform/workflows/resources/ip_verify.ps1")
                self.assertFalse({"SelectedTestModules", "ChangedTestModules"} & ip["command"]["parameters"].keys())

        request, _ = self.plan("-ChangedPath", "tests/contracts/test_support/unknown_fixture.py")
        for owner in expected:
            full, _ = self.plan("-Scope", "Owner", "-Owner", owner)
            modules = selected_modules(request, owner)
            self.assertTrue(modules, owner)
            self.assertCountEqual(modules, selected_modules(full, owner), owner)

    def test_multipole_tests_do_not_route_to_runtime_consumers(self) -> None:
        initializer_routes = self.routed_stages("tests/components/rf_multipole_ion_optics/__init__.py")
        self.assertTrue({"rf_multipole_domain_tests", "rf_multipole_quadrupole_static",
                         "rf_multipole_hexapole_static", "rf_multipole_octupole_static"}.issubset(initializer_routes))
        for filename in ("test_simion_geometry.py", "test_simion_rf_drive.lua",
                         "test_comsol_stationary_solver_smoke.m"):
            with self.subTest(filename=filename):
                self.assertEqual(
                    self.routed_stages(f"tests/components/rf_multipole_ion_optics/domain/{filename}"),
                    {"rf_multipole_domain_tests": "rf_multipole_domain_tests_changed"},
                )

    def test_multipole_domain_and_shared_kernels_keep_actual_consumers(self) -> None:
        variants = {f"rf_multipole_{variant}_static" for variant in ("quadrupole", "hexapole", "octupole")}
        domain_stages = variants | {
            "rf_multipole_generated_publications", "rf_multipole_domain_tests",
        }
        for path in (
            "src/msplatform/components/rf_multipole/family_contract.py",
            "src/msplatform/workflows/rf_design_profiles.py",
            "src/msplatform/workflows/rf_campaign_analysis.py",
            "src/msplatform/backends/comsol/matlab/solve_finite_3d_transport.m",
            "src/msplatform/backends/simion/rf_finite_geometry.py",
            "src/msplatform/components/rf_multipole/family_contract.json",
            "src/msplatform/components/rf_multipole/config/sources/rf_multipole_family_mother_sample_v1.json",
        ):
            with self.subTest(path=path):
                self.assertTrue((REPO_ROOT / path).is_file(), path)
                self.assertTrue(domain_stages <= self.routed_stages(path).keys(), path)
        resource_consumers = domain_stages | {
            "livelink_resource_stages_tests", "instrument_assembly",
            "multi_reflection_tof_static",
            "single_reflection_oa_tof_mass_analyzer_static",
            "ion_processor_static",
            "dual_cone_tandem_quadrupole_static",
            "transverse_helical_filament_wehnelt_electron_gun_static",
        }
        self.assertTrue(resource_consumers <= self.routed_stages("tools/repository/resource_budget_support.ps1").keys())
        rf_consumers = domain_stages | {
            "simion_backend", "instrument_assembly",
            "ion_processor_static",
            "dual_cone_tandem_quadrupole_static",
        }
        self.assertTrue(rf_consumers <= self.routed_stages("src/msplatform/backends/simion/resources/rf_drive.lua").keys())
        serialized = json.dumps(self.route_contract)
        self.assertNotIn("common/multipole", serialized)
        self.assertNotIn("common.multipole", serialized)

    def test_domain_test_plan_avoids_production_and_freshness_stages(self) -> None:
        completed = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(CHANGED_GATE),
             "-PythonExe", sys.executable, "-PlanOnly", "-ChangedPath",
             "tests/components/rf_multipole_ion_optics/domain/test_simion_geometry.py"],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        selected = re.search(r"SELECTED_STAGES=([^\s]+)", completed.stdout)
        self.assertIsNotNone(selected, completed.stdout)
        domain_stages = {name for name in selected.group(1).split(",") if name.startswith("rf_multipole_")}
        self.assertEqual(domain_stages, {"rf_multipole_domain_tests"})

    def test_simion_tests_use_their_direct_test_stage(self) -> None:
        self.assertEqual(
            self.routed_stages("tests/simion/test_resource_scheduler.py"),
            {"simion_backend": "simion_tests_changed"},
        )

    def test_livelink_tests_use_their_direct_fast_stages(self) -> None:
        self.assertEqual(
            self.routed_stages("tests/comsol/test_livelink_resource_stages.py"),
            {"livelink_resource_stages_tests": "livelink_resource_tests_changed"},
        )
        for path in (
            "src/msplatform/backends/comsol/launcher/run_comsol_r2025b.ps1",
            "tests/comsol/test_unclassified_support.py",
        ):
            with self.subTest(path=path):
                self.assertIn("rf_multipole_domain_tests", self.routed_stages(path))
                self.assertIn("rf_multipole_generated_publications", self.routed_stages(path))
        self.assertEqual(
            self.routed_stages("tests/comsol/test_livelink_environment.ps1"),
            {"livelink_environment": "livelink_environment_test_changed"},
        )
        self.assertEqual(
            self.routed_stages(
                "tests/comsol/test_livelink_failure_classification.ps1"
            ),
            {
                "livelink_failure_classification": (
                    "livelink_failure_classifier_test_changed"
                )
            },
        )

    def test_cloc_entrypoint_routes_to_its_focused_contract_tests(self) -> None:
        routed = self.routed_stages("tools/repository/report_cloc_delta.ps1")
        self.assertEqual(set(routed), {"machine_contracts"})

    def test_comsol_readme_does_not_expand_mixed_changed_scope(self) -> None:
        self.assertEqual(self.routed_stages("docs/COMSOL_BACKEND.md"), {})
        consumers = {
            "rf_multipole_generated_publications", "rf_multipole_domain_tests",
            "single_reflection_oa_tof_mass_analyzer_static", "rf_multipole_quadrupole_static",
            "rf_multipole_hexapole_static", "rf_multipole_octupole_static",
            "transverse_helical_filament_wehnelt_electron_gun_static",
        }
        for path in ("src/msplatform/backends/comsol/launcher/run_comsol_r2025b.ps1", "src/msplatform/backends/comsol/launcher/livelink_environment.ps1"):
            self.assertTrue(consumers <= self.routed_stages(path).keys(), path)
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        command = (
            f"& '{CHANGED_GATE}' -PythonExe '{sys.executable}' -PlanOnly "
            "-ChangedPath @('tools/repository/gate_catalog.json',"
            "'tests/contracts/test_verify_changed.py','docs/COMSOL_BACKEND.md') "
            f"-InternalRequestPath '{self.summary_path}'"
        )
        result = subprocess.run([pwsh, "-NoProfile", "-Command", command], cwd=REPO_ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        selected = re.search(r"SELECTED_STAGES=([^\s]+)", result.stdout)
        self.assertIsNotNone(selected, result.stdout)
        request = json.loads(Path(self.summary_path).read_text(encoding="utf-8-sig"))
        contract_rows = [row for row in request["stages"]
                         if row["selected"] and (row["name"] == "machine_contracts"
                         or row["name"].startswith("machine_contracts__tests_"))]
        self.assertTrue(contract_rows)
        self.assertEqual(set(selected[1].split(",")), {
            "repository_hygiene", "repository_text_bytes", "documentation",
            "development_standards", "ruff_changed_python",
            *(row["name"] for row in contract_rows),
        })
        self.assert_complete_contract_modules(contract_rows, {
            "tests.contracts.test_changed_test_selection",
            "tests.contracts.test_parallel_gate_support", "tests.contracts.test_verify_changed",
            "tests.contracts.test_development_standards", "tests.contracts.test_gate_unittest",
        })





    def test_partial_contract_coverage_keeps_uncovered_modules(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        arguments = ("-ChangedPath", "tests/contracts/test_changed_test_selection.py")
        # This representative must execute the CLI even if another test warmed the cache.
        cache = dict(getattr(type(self), "_plans", {}))
        cache.pop(arguments, None)
        self.addCleanup(setattr, type(self), "_plans", getattr(type(self), "_plans", {}))
        type(self)._plans = cache
        request, output = self.plan(*arguments)
        selected = re.search(r"SELECTED_STAGES=([^\s]+)", output)
        self.assertIsNotNone(selected, output)
        contract_rows = [row for row in request["stages"]
                         if row["selected"] and (row["name"] == "machine_contracts"
                         or row["name"].startswith("machine_contracts__tests_"))]
        self.assertTrue(contract_rows)
        self.assertTrue({row["name"] for row in contract_rows} <= set(selected.group(1).split(",")))
        self.assert_complete_contract_modules(contract_rows, {
            "tests.contracts.test_changed_test_selection",
            "tests.contracts.test_parallel_gate_support", "tests.contracts.test_verify_changed",
            "tests.contracts.test_development_standards", "tests.contracts.test_gate_unittest",
        })

    def assert_complete_contract_modules(self, rows, expected):
        actual = [value.removesuffix(".py").replace("/", ".")
                  for row in rows for value in row["command"]["arguments"][2:]]
        self.assertCountEqual(actual, expected)
        self.assertEqual(len(actual), len(set(actual)))

    def test_declared_core_resources_route_with_delivery_exclusions(self):
        route = next(row for row in self.routes if row["stage"] == "instrument_assembly")
        matches = [match for match in route["matches"]
                   if match["reason"] == "declared_runtime_dependency_changed"
                   and "regex" in match and "src/msplatform" in match["regex"]]
        self.assertTrue(matches)
        for path, expected in (
            ("src/msplatform/contracts/schemas/declared.schema.json", True),
            ("src/msplatform/contracts/schemas/undeclared.json", False),
            ("src/msplatform/tests/declared.schema.json", False),
            ("src/msplatform/contracts/history/declared.schema.json", False),
            ("src/msplatform/contracts/__pycache__/declared.schema.json", False),
        ):
            with self.subTest(path=path):
                self.assertEqual(any(re.search(match["regex"], path, re.IGNORECASE)
                                     for match in matches), expected)

    def test_integration_changes_route_only_to_connection_gates(self) -> None:
        routed = self.routed_stages("src/msplatform/assembly/model.py")
        self.assertEqual(
            set(routed),
            {
                "assembly_contracts",
                "instrument_assembly",
                "machine_contracts",
            },
        )
        interface_route = self.routed_stages(
            "src/msplatform/components/rf_multipole/variants/hexapole/config/interfaces/output_port.json"
        )
        self.assertNotIn("rf_multipole_to_single_reflection_oatof_integration", interface_route)

        self.assertIn("machine_contracts", {route["stage"] for route in self.routes})


    def test_gate_entrypoints_run_their_contract_tests(self) -> None:
        for path in (
            "tools/repository/verify.ps1",
            "tools/repository/parallel_gate_support.ps1",
            "tools/repository/gate_catalog.json",
            "tools/repository/gate_catalog_support.ps1",
            "tests/contracts/test_verify_changed.py",
            "tools/repository/verify.ps1",
            "src/msplatform/execution/resources/require_powershell7.ps1",
            ".github/workflows/lightweight-gate.yml",
        ):
            self.assertIn("machine_contracts", self.routed_stages(path))

    def test_generated_publications_have_priority_and_explicit_successors(self) -> None:
        stage_order = [route["stage"] for route in self.routes]
        freshness = stage_order.index("rf_multipole_generated_publications")
        machine_contracts = stage_order.index("machine_contracts")
        rf_multipole_domain_tests = stage_order.index("rf_multipole_domain_tests")
        self.assertLess(freshness, machine_contracts)
        self.assertLess(freshness, rf_multipole_domain_tests)
        freshness_route = self.routes[freshness]
        self.assertEqual(
            freshness_route["command"]["parameters"],
            {"Level": "Freshness", "PythonExe": "{python}", "StructuralVariant": "All"},
        )

        self.assertEqual(
            freshness_route["repository_gate_group"], "fast"
        )
        quadrupole_route = next(
            route
            for route in self.routes
            if route["stage"] == "rf_multipole_quadrupole_static"
        )
        self.assertEqual(
            quadrupole_route["repository_gate_group"], "regression"
        )
        self.assertEqual(
            quadrupole_route["requires_stages"],
            ["rf_multipole_generated_publications"],
        )



    def test_excludes_commercial_and_formal_gate_levels(self) -> None:
        # Watching a launcher source path must select its mock regression, not
        # be confused with executing that launcher as a gate command.
        commands = [
            route[key] for route in self.routes
            for key in ("command", "repository_gate_command") if key in route
        ]
        serialized_commands = json.dumps(commands)
        for forbidden in (
            "-Level Candidate",
            "-Level Formal",
            "run_comsol_r2025b",
            "simion.exe",
        ):
            self.assertNotIn(forbidden, serialized_commands)
        for command in commands:
            level = str(command.get("parameters", {}).get("Level", "")).casefold()
            self.assertNotIn(level, {"candidate", "formal"})



    def test_parallel_scheduler_validates_temporary_cleanup_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cleanup_contract_") as directory:
            root = Path(directory)
            safe = root / "gate_fixture_safe"
            unrelated = root / "unrelated"
            safe.mkdir(); unrelated.mkdir()
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            script = f"""
$ErrorActionPreference='Stop'
. {quote(PARALLEL_GATE_SUPPORT)}
foreach($target in @({quote(unrelated)},{quote(REPO_ROOT)})){{
 $blocked=$false
 try{{Remove-GateTemporaryDirectory -Path $target -ExpectedNamePrefix 'gate_fixture_'}}catch{{$blocked=$true}}
 if(-not$blocked){{throw 'Unowned cleanup target accepted'}}
}}
Remove-GateTemporaryDirectory -Path {quote(safe)} -ExpectedNamePrefix 'gate_fixture_'
if(Test-Path -LiteralPath {quote(safe)}){{throw 'Owned cleanup failed'}}
if(-not(Test-Path -LiteralPath {quote(unrelated)})){{throw 'Unrelated folder deleted'}}
"""
            result = subprocess.run([shutil.which("pwsh"),"-NoProfile","-Command",script],
                cwd=REPO_ROOT,capture_output=True,text=True,encoding="utf-8",timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_mr_provider_sources_and_test_files_select_real_core_plan(self):
        base = 'src/msplatform/components/multi_reflection_tof/'
        sources = ('src/msplatform/components/catalog.py', base+'provider.py', base+'candidate_contract.py',
                   base+'assembly_interface.py', base+'resolved_geometry.py', 'src/msplatform/backends/simion/mr_geometry.py',
                   'src/msplatform/backends/simion/native_system_geometry.py')
        prefix = 'tests.components.multi_reflection_tof.analysis.'
        required = {prefix+name for name in ('test_mr_provider_freeze','test_mr_provider_trial_transport',
                    'test_simion_candidate_reference','test_two_prism_simion_trial')}
        required.add('tests.assembly.multi_reflection_tof.analysis.test_assembly_interface')
        for path in sources:
            with self.subTest(path=path):
                request, _ = self.plan('-ChangedPath',path)
                rows = [row for row in request['stages'] if row['selected'] and row['name']=='multi_reflection_tof_static']
                self.assertEqual(len(rows),1)
                command = rows[0]['command']; self.assertEqual(command['parameters']['Level'],'Core')
                self.assertNotIn('SelectedTestModules',command['parameters'])
                modules=command['parameters']['ChangedTestModules']
                self.assertTrue(required <= set(modules), (path,modules))
                if path == base+'candidate_contract.py':
                    self.assertIn(prefix+'test_gap2_fixed_design', modules)
                self.assertEqual(len(modules),len(set(modules)))
                if path.startswith('src/'):
                    common=[value for row in request['stages'] if row['selected'] and
                            (row['name']=='machine_contracts' or row['name'].startswith('machine_contracts__tests_'))
                            for value in row['command'].get('arguments',[])]
                    self.assertIn('tests.contracts.test_installed_scientific_core',
                                  [value.removesuffix('.py').replace('/','.') for value in common])
        for module in ('test_mr_provider_freeze','test_mr_provider_trial_transport'):
            path='tests/components/multi_reflection_tof/analysis/'+module+'.py'
            self.assertTrue((REPO_ROOT/path).is_file())
            request, _ = self.plan('-ChangedPath',path)
            owner=next(row for row in request['stages'] if row['selected'] and row['name']=='multi_reflection_tof_static')
            self.assertIn(prefix+module,owner['command']['parameters']['ChangedTestModules'])
            loader=unittest.TestLoader()
            suite=loader.loadTestsFromName(prefix+module)
            self.assertEqual(loader.errors,[])
            def discovered_ids(item):
                if isinstance(item, unittest.TestSuite):
                    return {test_id for child in item for test_id in discovered_ids(child)}
                return {item.id()}
            required_methods = {
                'test_mr_provider_freeze': (
                    'MrProviderFreezeTests.test_actual_oa_mr_selection_is_isolated_and_fail_closed',
                    'FrozenCollectionGateBoundaryTests.test_collection_gate_actual_executor_uses_frozen_identity',
                    'PublicFrozenCollectionGateTests.test_public_oa_mr_freezer_and_actual_gate_boundary',
                ),
                'test_mr_provider_trial_transport': (
                    'MRProviderTrialTransportTests.test_real_oa_mr_components_survive_json_and_reject_physical_tampering',
                    'MRProviderTrialTransportTests.test_real_materializer_plan5_and_legacy_preserve_controls',
                    'MRProviderTrialTransportTests.test_plan5_materializer_rejects_stale_mr_component',
                ),
            }
            expected_ids = {prefix + module + '.' + method for method in required_methods[module]}
            self.assertTrue(expected_ids <= discovered_ids(suite), (module, expected_ids - discovered_ids(suite)))
        verify=(REPO_ROOT/'src/msplatform/workflows/resources/mr_verify.ps1').read_text(encoding='utf-8')
        self.assertIn('$coreTests = @($coreTests + $ChangedTestModules | Sort-Object -Unique)',verify)
        self.assertIn('-m tools.repository.gate_unittest @coreTests',verify)

    def test_joint_model_and_rf_oa_public_changed_plan_selects_actual_consumers(self):
        def integration_modules(request):
            result = set()
            for row in request['stages']:
                if row['selected'] and row['name'].startswith('instrument_assembly'):
                    command = row['command']
                    values = [*command.get('parameters', {}).get('SelectedTestModules', []),
                              *command.get('arguments', [])]
                    result.update(value.removesuffix('.py').replace('/', '.').rsplit('.', 1)[-1]
                                  for value in values)
            return result
        cases = (
            ('src/msplatform/backends/simion/mr_model.py', {'test_oa_mr_model', 'test_rf_oa_geometry_iob'}, False),
            ('src/msplatform/backends/simion/rf_oa_compiler.py', {'test_oa_mr_model', 'test_rf_oa_geometry_iob'}, True),
            ('src/msplatform/backends/simion/resources/iob_core.lua', {'test_oa_mr_model', 'test_rf_oa_geometry_iob'}, True),
            ('tests/contracts/test_oa_mr_model.py', {'test_oa_mr_model'}, False),
            ('tests/contracts/test_rf_oa_geometry_iob.py', {'test_rf_oa_geometry_iob'}, False),
        )
        for path, required, integration in cases:
            with self.subTest(path=path):
                request, _ = self.plan('-ChangedPath', path)
                common = {value.removesuffix('.py').replace('/', '.').rsplit('.', 1)[-1]
                          for row in request['stages'] if row['selected'] and
                          (row['name'] == 'machine_contracts' or row['name'].startswith('machine_contracts__tests_'))
                          for value in row['command'].get('arguments', [])}
                self.assertTrue(required <= common, (path, required, common))
                if integration:
                    modules = integration_modules(request)
                    self.assertIn('test_rf_oa_compiler', modules, (path, modules))
        request, _ = self.plan('-ChangedPath', 'tests/assembly/rf_oa_compiler/test_rf_oa_compiler.py')
        modules = integration_modules(request)
        self.assertIn('test_rf_oa_compiler', modules)

    def test_continuous_rf_ip_public_changed_plan_selects_actual_consumers(self):
        required = {'test_rf_ip_' + name for name in
                    ('composed', 'gas_selection', 'tracking_iob', 'tracking_plan', 'tracking_program')}
        for path in ('src/msplatform/backends/simion/operations.py',
                     'src/msplatform/backends/simion/resources/rf_ip_tracking_hs1.lua',
                     'src/msplatform/components/ion_processor/gas_regions.py'):
            with self.subTest(path=path):
                request, _ = self.plan('-ChangedPath', path)
                common = {value.removesuffix('.py').replace('/', '.').rsplit('.', 1)[-1]
                          for row in request['stages'] if row['selected'] and
                          (row['name'] == 'machine_contracts' or row['name'].startswith('machine_contracts__tests_'))
                          for value in row['command'].get('arguments', [])}
                self.assertTrue(required <= common, (path, required, common))
        request, _ = self.plan('-ChangedPath', 'tests/contracts/test_rf_ip_composed.py')
        values = [value for row in request['stages'] if row['selected'] and
                  row['name'].startswith('machine_contracts')
                  for value in row['command'].get('arguments', [])]
        normalized = [value.removesuffix('.py').replace('/', '.') for value in values]
        self.assertIn('tests.contracts.test_rf_ip_composed', normalized)

    def test_installed_mr_phase_public_plan_preserves_core_and_full_integration(self):
        request, _ = self.plan('-ChangedPath',
            'src/msplatform/contracts/drift_phase_contract.py')
        rows = [row for row in request['stages']
                if row['name'] == 'multi_reflection_tof_static']
        self.assertEqual(len(rows), 1)
        command = rows[0]['command']
        self.assertEqual(command['runner'], 'powershell')
        self.assertEqual(command['script'],
                         'src/msplatform/workflows/resources/mr_verify.ps1')
        self.assertEqual(command['parameters']['Level'], 'Core')
        self.assertNotIn('SelectedTestModules', command['parameters'])
        prefix = 'tests.components.multi_reflection_tof.analysis.'
        expected = [prefix + name for name in (
            'test_downstream_fixed_grid_workpoint',
            'test_drift_phase_contract',
            'test_dual_stripe_l0_math',
            'test_fixed_grid_mirror_stripe_handoff',
            'test_ip_prism_distance_study',
            'test_joint_flight_preparation',
            'test_joint_mirror_stripe_l0',
            'test_mirror_exact_k_operating_point',
            'test_mirror_l0_l1_runner',
            'test_recorded_joint_trial',
            'test_prism_analytic',
            'test_prism_mirror_transport',
            'test_prism_runner_contract_matrix',
            'test_simion_candidate_reference',
            'test_simion_event_analysis',
            'test_static_field_binding',
            'test_static_workpoint_iteration',
            'test_two_prism_segmented_coverage',
            'test_two_prism_segmented_transport',
            'test_two_prism_segmented_voltage_continuation',
            'test_two_prism_segmented_voltage_seed',
            'test_two_prism_simion_trial',
        )]
        self.assertCountEqual(command['parameters']['ChangedTestModules'], expected)
        self.assertEqual(len(expected), len(set(expected)))
        self.assertTrue(any(row['name'].startswith('machine_contracts')
                            for row in request['stages']))
        self.assertTrue(any(row['name'].startswith('instrument_assembly')
                            for row in request['stages']))
        self.assertFalse(any(row['resource_role'] in {'SIMION', 'COMSOL'}
                             for row in request['stages']))

    def test_installed_operating_pa_composer_public_plan_preserves_existing_owners(self):
        request, _ = self.plan('-ChangedPath',
            'src/msplatform/backends/simion/resources/compose_standalone_pa.lua')
        rows = [row for row in request['stages']
                if row['name'] == 'multi_reflection_tof_static']
        self.assertEqual(len(rows), 1)
        command = rows[0]['command']
        self.assertEqual(command['runner'], 'powershell')
        self.assertEqual(command['script'],
                         'src/msplatform/workflows/resources/mr_verify.ps1')
        self.assertEqual(command['parameters']['Level'], 'Core')
        self.assertNotIn('SelectedTestModules', command['parameters'])
        self.assertEqual(command['parameters']['ChangedTestModules'], [
            'tests.components.multi_reflection_tof.analysis.test_static_field_binding'])
        common = [value for row in request['stages']
                  if row['name'].startswith('simion_backend')
                  for value in row['command'].get('arguments', [])]
        expected_common = ['tests/simion/' + name for name in (
            'test_operating_pa_cache.py', 'test_standalone_pa_composition_tools.py',
            'test_export_standalone_pa.py')]
        for module in expected_common:
            self.assertEqual(common.count(module), 1)
        integration = [value for row in request['stages']
                       if row['name'].startswith('instrument_assembly')
                       for value in row['command'].get('parameters', {}).get('SelectedTestModules', [])]
        self.assertCountEqual(integration, [
            'tests.execution.test_dependencies'])
        self.assertEqual(len(integration), len(set(integration)))
        self.assertTrue(any(row['name'].startswith('machine_contracts') for row in request['stages']))
        self.assertFalse(any(row['resource_role'] in {'SIMION', 'COMSOL'} for row in request['stages']))

    def test_installed_mr_stripe_public_plan_preserves_core_and_integration(self):
        request, _ = self.plan('-ChangedPath',
            'src/msplatform/components/multi_reflection_tof/dual_stripe_l0.py')
        rows = [row for row in request['stages']
                if row['name'] == 'multi_reflection_tof_static']
        self.assertEqual(len(rows), 1)
        command = rows[0]['command']
        self.assertEqual(command['runner'], 'powershell')
        self.assertEqual(command['script'],
                         'src/msplatform/workflows/resources/mr_verify.ps1')
        self.assertEqual(command['parameters']['Level'], 'Core')
        self.assertNotIn('SelectedTestModules', command['parameters'])
        prefix = 'tests.components.multi_reflection_tof.analysis.'
        expected = [prefix + name for name in [
            'test_downstream_fixed_grid_workpoint',
            'test_downstream_workpoint_iteration',
            'test_dual_stripe_l0_math',
            'test_fixed_grid_mirror_stripe_handoff',
            'test_joint_mirror_stripe_l0',
            'test_managed_analysis_runner_contracts',
            'test_measured_component_source',
            'test_mirror_exact_k_operating_point',
            'test_mirror_l0_l1_runner',
            'test_native_candidate_condition_runner',
            'test_recorded_joint_trial',
            'test_prism_runner_contract_matrix',
            'test_simion_candidate_reference',
            'test_static_field_binding',
            'test_static_workpoint_iteration',
            'test_two_prism_simion_trial',
        ]]
        self.assertCountEqual(command['parameters']['ChangedTestModules'], expected)
        self.assertEqual(len(expected), len(set(expected)))
        self.assertTrue(any(row['name'].startswith('machine_contracts') for row in request['stages']))
        self.assertTrue(any(row['name'].startswith('instrument_assembly')
                            for row in request['stages']))
        self.assertFalse(any(row['resource_role'] in {'SIMION', 'COMSOL'}
                             for row in request['stages']))

    def test_scalar_adapter_selects_original_core_and_actual_consumers(self):
        request, _ = self.plan(
            "-ChangedPath", "src/msplatform/backends/simion/resources/scalar_field_adapter.lua"
        )
        mr_rows = [row for row in request["stages"]
                   if row["name"] == "multi_reflection_tof_static"]
        self.assertEqual(len(mr_rows), 1)
        command = mr_rows[0]["command"]
        self.assertEqual(command["runner"], "powershell")
        self.assertEqual(command["script"],
                         "src/msplatform/workflows/resources/mr_verify.ps1")
        self.assertEqual(command["parameters"]["Level"], "Core")
        self.assertNotIn("SelectedTestModules", command["parameters"])
        modules = command["parameters"]["ChangedTestModules"]
        self.assertCountEqual(modules, [
            "tests.components.multi_reflection_tof.analysis." + name
            for name in ("test_static_field_binding", "test_native_memory_consumer_crop",
                         "test_recorded_joint_trial", "test_native_static_field_provider_runner")])
        self.assertEqual(len(modules), len(set(modules)))
        self.assertTrue(any(row["name"].startswith("machine_contracts")
                            for row in request["stages"]))
        self.assertTrue(any(row["name"].startswith("instrument_assembly")
                            for row in request["stages"]))
        self.assertFalse(any(row["resource_role"] in {"SIMION", "COMSOL"}
                             for row in request["stages"]))





class RuntimeInventoryRouteTests(unittest.TestCase):
    """Exercise the actual selector on a small declared author inventory."""

    def test_runtime_inventory_changes_route_without_editing_the_catalog(self) -> None:
        # Copy only the real plan/parser boundary; no gate stage or solver executes.
        with tempfile.TemporaryDirectory(prefix="gate_inventory_") as directory:
            repo = Path(directory)
            (repo / "tools/repository").mkdir(parents=True)
            (repo / "src/msplatform/components").mkdir(parents=True)
            for name in ("verify.ps1", "gate_catalog_support.ps1", "parallel_gate_support.ps1",
                         "host_execution_lease.ps1", "require_powershell7.ps1", "resource_process_support.ps1"):
                source = REPO_ROOT / ("src/msplatform/execution/resources" if name in ("require_powershell7.ps1", "resource_process_support.ps1") else "tools/repository") / name
                destination = repo / ("src/msplatform/execution/resources" if name in ("require_powershell7.ps1", "resource_process_support.ps1") else "tools/repository") / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            for name in ("host_execution_lease.ps1", "host_resource_policy.json"):
                relative = Path("src/msplatform/execution/resources") / name
                destination = repo / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(REPO_ROOT / relative, destination)
            gate = repo / "tools/repository/verify_integration.ps1"
            gate.write_text("throw 'PlanOnly must not execute stages'\n", encoding="utf-8")
            inventory_path = "src/msplatform/workflows/config/runtime_dependencies.json"
            route = dict(stage="instrument_assembly", dependency_profile="locked",
                         repository_gate_group="regression",
                         matches=[dict(prefix="src/msplatform/workflows/", reason="assembly_changed")],
                         runtime_dependencies_path=inventory_path,
                         command=dict(runner="powershell", script="tools/repository/verify_integration.ps1"))
            (repo / "tools/repository/gate_catalog.json").write_text(json.dumps(dict(
                schema_version=2, role="repository_gate_catalog", routes=[route])), encoding="utf-8")
            inventory = dict(schema_version=3, role="workflow_runtime_dependencies", providers=[
                dict(files=[dict(source_repo_path="src/msplatform/first_dependency.json")],
                     python_packages=[], python_modules=[])])
            target = repo / inventory_path
            target.parent.mkdir(parents=True, exist_ok=True)
            first = repo / "src/msplatform/first_dependency.json"
            added = repo / "src/msplatform/added_dependency.json"
            first.write_text("", encoding="utf-8")
            added.write_text("", encoding="utf-8")
            target.write_text(json.dumps(inventory), encoding="utf-8")
            result = ChangedGateContractTests._runtime_dependency_plan(repo, "src/msplatform/added_dependency.json")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            selected = re.search(r"SELECTED_STAGES=([^\s]+)", result.stdout)
            self.assertIsNotNone(selected, result.stdout)
            self.assertNotIn("instrument_assembly", selected[1].split(","))
            inventory["providers"][0]["files"].append(dict(source_repo_path="src/msplatform/added_dependency.json"))
            target.write_text(json.dumps(inventory), encoding="utf-8")
            result = ChangedGateContractTests._runtime_dependency_plan(repo, "src/msplatform/added_dependency.json")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("instrument_assembly", re.search(
                r"SELECTED_STAGES=([^\s]+)", result.stdout)[1].split(","))
            (repo / "src/msplatform/pkg").mkdir()
            entry = repo / "src/msplatform/pkg/deleted_module.py"
            entry.write_text("", encoding="utf-8")
            (repo / "src/msplatform/standalone.py").write_text("", encoding="utf-8")
            inventory["providers"][0]["python_packages"] = [dict(source_repo_path="src/msplatform/pkg")]
            inventory["providers"][0]["python_modules"] = [dict(source_repo_path="src/msplatform/standalone.py")]
            target.write_text(json.dumps(inventory), encoding="utf-8")
            entry.unlink()
            # These paths need no source-tree scan: newly added/deleted modules
            # and namespace initializers retain impact routing by author declaration.
            for changed_path, expected in (
                ("src/msplatform/pkg/new_module.py", True),
                ("src/msplatform/pkg/deleted_module.py", True),
                ("src/msplatform/__init__.py", True),
                ("src/msplatform/standalone.py", True),
                ("src/msplatform/standalone_extra.py", False),
                ("src/msplatform/pkg/notes.md", False),
                ("src/msplatform/pkg/assets/not_code.py", False),
                ("src/msplatform/pkg/tests/test_entry.py", False),
                ("src/msplatform/pkg_neighbor/module.py", False),
            ):
                with self.subTest(changed_path=changed_path):
                    result = ChangedGateContractTests._runtime_dependency_plan(repo, changed_path)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    stages = re.search(r"SELECTED_STAGES=([^\s]+)", result.stdout)
                    self.assertIsNotNone(stages, result.stdout)
                    self.assertEqual("instrument_assembly" in stages[1].split(","), expected)
            for case in ("missing_inventory", "unknown_schema", "unknown_role", "missing_source"):
                with self.subTest(case=case):
                    changed = json.loads(json.dumps(inventory))
                    if case == "missing_inventory":
                        target.unlink()
                    else:
                        if case == "unknown_schema":
                            changed["schema_version"] = 999
                        elif case == "unknown_role":
                            changed["role"] = "unknown_inventory"
                        else:
                            changed["providers"][0]["files"][0]["source_repo_path"] = "src/msplatform/missing.json"
                        target.write_text(json.dumps(changed), encoding="utf-8")
                    result = ChangedGateContractTests._runtime_dependency_plan(repo, "src/msplatform/added_dependency.json")
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("dependency", result.stderr)
                    self.assertNotIn("SELECTED_STAGES=", result.stdout)


if __name__ == "__main__":
    unittest.main()
