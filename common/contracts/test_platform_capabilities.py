"""Real pure capability requests; tool presence never implies qualification."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from msplatform import assembly as assembly_api, capabilities as capability_api, components as component_api, examples as example_api
from msplatform import ion_release as ion_release_api
from msplatform.backends import simion as simion_api
from msplatform.backends.simion.model import compile_prepared_model, project_resolved_drive, PHYSICS


class EIBuildCapabilitiesTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2] / "projects/apertured_tube_electron_impact_ion_source/config"
        self.arguments = dict(baseline=json.loads((root / "baseline.json").read_text(encoding="utf-8")),
            modes=json.loads((root / "numerical_modes.json").read_text(encoding="utf-8")),
            mode_id="build_only_smoke")

    def query(self, arguments):
        return capability_api.capabilities(dict(schema_version=1, operation="build_ei_model", arguments=arguments))

    def test_ei_query_uses_actual_operation_validator_without_native_or_writes(self):
        before = copy.deepcopy(self.arguments)
        with patch("subprocess.Popen", side_effect=AssertionError("native process")), \
             patch("shutil.which", side_effect=AssertionError("tool discovery")), \
             patch.object(Path, "mkdir", side_effect=AssertionError("workspace")), \
             patch.object(Path, "write_text", side_effect=AssertionError("write")):
            result = self.query(self.arguments)
        self.assertEqual(result["contract_status"], "accepted", result)
        self.assertEqual(result["validator"], "msplatform.backends.comsol.ei_model.resolve_ei_build_request")
        self.assertEqual(result["execution_readiness"], "not_assessed")
        self.assertEqual(result["native_qualification"], "not_granted")
        self.assertIn("native_save_and_fresh_reopen", result["execution_prerequisites"])
        self.assertEqual(self.arguments, before)

    def test_ei_query_rejects_invalid_and_unimplemented_operation_modes(self):
        invalid = copy.deepcopy(self.arguments)
        invalid["baseline"]["unexpected_scientific_input"] = True
        self.assertEqual(self.query(invalid)["contract_status"], "rejected")
        full = dict(self.arguments, mode_id="functional_reference", evidence_particle_count=100)
        self.assertEqual(self.query(full)["contract_status"], "rejected")
        missing = dict(self.arguments)
        del missing["mode_id"]
        self.assertEqual(self.query(missing)["missing_arguments"], ["mode_id"])


class WehneltBuildCapabilitiesTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2] / "projects/transverse_helical_filament_wehnelt_electron_gun/config"
        self.arguments = dict(baseline=json.loads((root / "baseline.json").read_text(encoding="utf-8")),
            modes=json.loads((root / "numerical_modes.json").read_text(encoding="utf-8")),
            mode_id="build_only_smoke", evidence_particle_count=3)

    def query(self, arguments):
        return capability_api.capabilities(dict(schema_version=1, operation="build_wehnelt_model", arguments=arguments))

    def test_actual_wehnelt_request_does_not_start_or_discover_commercial_tools(self):
        original = copy.deepcopy(self.arguments)
        with patch("subprocess.Popen", side_effect=AssertionError("native process")), \
             patch("shutil.which", side_effect=AssertionError("host discovery")), \
             patch.object(Path, "mkdir", side_effect=AssertionError("workspace")), \
             patch.object(Path, "write_text", side_effect=AssertionError("write")):
            result = self.query(self.arguments)
        self.assertEqual(result["contract_status"], "accepted", result)
        self.assertEqual(result["validator"], "msplatform.backends.comsol.wehnelt_model.resolve_wehnelt_build_request")
        self.assertEqual(result["native_qualification"], "not_granted")
        self.assertEqual(result["execution_readiness"], "not_assessed")
        self.assertEqual(self.arguments, original)

    def test_count_and_electron_contract_are_required_and_full_mode_is_not_build_only(self):
        missing = dict(self.arguments)
        del missing["evidence_particle_count"]
        self.assertEqual(self.query(missing)["missing_arguments"], ["evidence_particle_count"])
        invalid = copy.deepcopy(self.arguments)
        invalid["baseline"]["particle"]["charge_state"] = 1
        self.assertEqual(self.query(invalid)["contract_status"], "rejected")
        full = dict(self.arguments, mode_id="functional_reference", evidence_particle_count=100)
        self.assertEqual(self.query(full)["contract_status"], "rejected")


class PlatformCapabilitiesTests(unittest.TestCase):
    def setUp(self):
        self.case = example_api.load_example("rf_oatof_functional_v1")
        self.components = {name: component_api.resolve_component(request) for name, request in self.case.component_requests.items()}
        self.assembly = assembly_api.assemble(self.case.recipe, self.components)
        self.compiled = simion_api.compile_geometry(self.assembly, numerics=self.case.geometry_numerics)
        self.drive = project_resolved_drive(self.compiled, self.compiled.components_resolved,
            pulse=dict(mode="timed", time_us=10., width_us=2.),
            clock=dict(clock_epoch_id="epoch", authority_sha256="A" * 64, phase_reference_instrument_time_us=0.))
        self.model = compile_prepared_model(self.compiled, self.compiled.components_resolved,
                                          drive=self.drive, physics=PHYSICS)

    def query(self, operation, arguments, **kwargs):
        return capability_api.capabilities(dict(schema_version=1, operation=operation, arguments=arguments), **kwargs)

    def test_actual_provider_assembly_and_geometry_compile_without_native_claim(self):
        cases = [("resolve_component", dict(request=next(iter(self.case.component_requests.values())))),
                 ("compile_assembly", dict(recipe=self.case.recipe, components=self.components)),
                 ("compile_geometry", dict(assembly=self.assembly, numerics=self.case.geometry_numerics))]
        for operation, arguments in cases:
            with self.subTest(operation=operation):
                before = copy.deepcopy(arguments)
                result = self.query(operation, arguments)
                self.assertEqual(result["contract_status"], "accepted")
                self.assertEqual(result["native_qualification"], "not_granted")
                self.assertEqual(result["environment_status"], "not_supplied")
                self.assertEqual(result["execution_readiness"], "not_assessed")
                self.assertEqual(arguments, before)
        from common.contracts.test_geometry_members import independent_oa_objects
        oa_parts, _, _ = independent_oa_objects()
        request = dict(provider_id="orthogonal_accelerator",
                       geometry_profile_id=oa_parts["two"].assembly_interface["geometry_profile_id"],
                       design=oa_parts["two"].source_design)
        result = self.query("resolve_component", dict(request=request))
        self.assertEqual(result["contract_status"], "accepted", result)
        self.assertEqual(result["native_qualification"], "not_granted")

    def test_real_model_field_and_tracking_planners_are_distinct_from_execution(self):
        packet = ion_release_api.sample_release(self.case.release).to_dict()
        clock = packet["clock"]
        clocks = {key:dict(path="C:/explicit-declaration-only/"+key+".json",exists=True,bytes=32,
            sha256=clock["authority_sha256"] if key=="instrument_epoch" else "A"*64)
            for key in ("clock_authority", "instrument_epoch")}
        # These are caller declarations for the pure planner only, not actual
        # authority files; the result must never say ready to execute.
        drive = project_resolved_drive(self.compiled,self.compiled.components_resolved,
            pulse=dict(mode="timed",time_us=10.,width_us=2.),clock=dict(clock,phase_reference_instrument_time_us=0.))
        model = compile_prepared_model(self.compiled,self.compiled.components_resolved,drive=drive,physics=PHYSICS)
        cases = [("prepare_model", dict(compiled=self.compiled, components_resolved=self.compiled.components_resolved,
                                       drive=drive, physics=PHYSICS)),
                 ("solve_fields", dict(model=model, numerics=self.case.field_numerics)),
                 ("track", dict(model=model, particles=packet, clock_records=clocks,
                    propagation=dict(schema_version=1,scope="continuous_assembly",end_policy=dict(maximum_particle_age_us=200.),
                                     consumed_plane_events=[],stop=None),
                    observations=dict(plane_observations=[]),
                    numerics=dict(maximum_step_us=.001,trajectory_quality=17,rf_steps_per_period=80)))]
        for operation, arguments in cases:
            with self.subTest(operation=operation):
                result = self.query(operation, arguments)
                self.assertEqual(result["contract_status"], "accepted", result)
                self.assertEqual(result["execution_readiness"], "not_assessed")
                self.assertTrue(result["execution_prerequisites"])
                self.assertEqual(result["query_scope"], "compile_or_plan_only_not_execution_signature")
                if operation == "track":
                    self.assertEqual(result["native_qualification"], "not_granted")
                    self.assertIn("whole_unit", result["software_scope"])
                    self.assertIn("incomplete_units_replay_whole_not_process_checkpoint_resume", result["limitations"])
                    partitioned = self.query(operation, dict(arguments, unit_size=25,
                        reused_unit_keys=["unit_0001"]))
                    self.assertEqual(partitioned["contract_status"], "accepted", partitioned)
                    self.assertEqual(partitioned["execution_readiness"], "not_assessed")
                    self.assertEqual(partitioned["native_qualification"], "not_granted")

    def test_step_members_and_shared_options_validate_without_loading_cad_engine(self):
        result = self.query("export_cad", dict(assembly=self.assembly,format="step",options=self.case.cad_export))
        self.assertEqual(result["contract_status"], "accepted", result)
        self.assertIn("not_exported", result["software_scope"])
        self.assertIn("cad-step_optional_dependencies", result["execution_prerequisites"])
        from msplatform.exporters.operations import _validate_step_export_options
        with self.assertRaises(ValueError):
            _validate_step_export_options(self.assembly,"step",dict(self.case.cad_export,precision_mode=True))
        rejected = self.query("export_cad", dict(assembly=self.assembly,format="step",options=dict(self.case.cad_export,precision_mode=True)))
        self.assertEqual(rejected["contract_status"], "rejected")

    def test_explicit_environment_is_separate_and_no_discovery_or_writes(self):
        args = dict(assembly=self.assembly,numerics=self.case.geometry_numerics)
        environment = dict(schema_version=1,tools=dict(simion=dict(available=False,release="SIMION 2020")))
        with patch("subprocess.Popen",side_effect=AssertionError("tool")), \
             patch("shutil.which",side_effect=AssertionError("host discovery")), \
             patch.object(Path,"mkdir",side_effect=AssertionError("mkdir")), \
             patch.object(Path,"write_text",side_effect=AssertionError("write")):
            result = self.query("compile_geometry",args,environment=environment)
        self.assertEqual(result["contract_status"], "accepted")
        self.assertEqual(result["environment_status"], "declared_unavailable")
        self.assertEqual(result["environment_compatibility"], "not_validated")
        environment["tools"]["simion"]["available"] = True
        self.assertFalse(result["environment"]["tools"]["simion"]["available"])
        with self.assertRaises(ValueError):
            self.query("compile_geometry",args,environment=dict(schema_version=1,tools=dict(simion=dict(available="yes"))))

    def test_missing_native_transport_is_explicit_not_fabricated(self):
        result = self.query("build_geometry", dict(compiled=self.compiled))
        self.assertEqual(result["contract_status"], "insufficient_request")
        self.assertEqual(set(result["missing_arguments"]), {"run_directory", "seed_record", "native_path_resource"})
        self.assertEqual(result["software_scope"], "not_validated")
        self.assertEqual(result["native_qualification"], "not_granted")

    def test_unsupported_request_does_not_borrow_legacy_project_support(self):
        unsupported = self.query("open_unknown_solver", {})
        self.assertEqual(unsupported["contract_status"], "unsupported")
        rejected = self.query("resolve_component",dict(request=dict(provider_id="unknown_provider",design={})))
        self.assertEqual(rejected["contract_status"], "rejected")
        self.assertIn("unsupported component provider", rejected["reason"]["message"])
        rejected = self.query("compile_geometry",dict(assembly=None,numerics=self.case.geometry_numerics))
        self.assertEqual(rejected["contract_status"], "rejected")
        self.assertIn("explicitly assembled design", rejected["reason"]["message"])
        with self.assertRaises(ValueError):
            capability_api.capabilities(dict(schema_version=2,operation="track",arguments={}))
