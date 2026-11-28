import copy
import hashlib
import json
import os
import subprocess
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, patch


from tools.repository.build_project_registry import resolve_project_root
from tools.repository.compile_execution_plan import compile_execution
from tools.repository.repository_root import REPO_ROOT
from msplatform.contracts.machine_contracts import load_json
from tools.repository.plan_design_request import build_plan


HERE = Path(__file__).resolve().parent


class ExecutionCompilerTests(unittest.TestCase):
    def setUp(self):
        self.binding_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.binding_directory.cleanup)
        self.registry = REPO_ROOT / "config" / "project_registry.json"
        self.run_id = "20260720_130000__analysis__repo__design-request"

    def binding_file(self, name):
        path = Path(self.binding_directory.name)/name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("{}", encoding="utf-8")
        return str(path)

    def copy_execution_resources(self, root):
        resources = root/"src/msplatform/execution/resources"
        shutil.copytree(REPO_ROOT/"src/msplatform/execution/resources", resources, dirs_exist_ok=True)
        return resources/"run_artifact_support.ps1"

    def compile_request(self, request, bindings=None, *, proposal=False, **options):
        with tempfile.TemporaryDirectory() as root:
            request_path = Path(root) / "request.json"
            plan_path = Path(root) / "design_plan.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            if proposal:
                from msplatform.contracts.machine_contracts import sha256
                (Path(root)/"candidate_proposal.json").write_text(json.dumps(dict(schema_version=1,
                    role="design_candidate_proposal", candidate_id="fixture_candidate",
                    project_id="single_reflection_oa_tof_mass_analyzer", request=dict(path=str(request_path),
                    sha256=sha256(request_path)), values=[])), encoding="utf-8")
            plan, _ = build_plan(request_path, self.registry, self.run_id)
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            return compile_execution(plan_path, self.registry, bindings, **options)

    def approved_rf_request(self):
        request = load_json(HERE / "fixtures" / "rf_quadrupole_transport.example.json")
        request["status"] = "approved"
        request["approval"] = {"approved_by": "owner", "approved_on": "2026-07-20"}
        request["operating_points"] = [{"mass": {"value": 100, "unit": "Da"}, "charge_state": 1}]
        request["design_variables"] = ["rf_amplitude", "rf_frequency"]
        return request

    def approved_functional_rf_request(self):
        request = self.approved_rf_request()
        return request

    def functional_bindings(self):
        return {
            "runtime_profile_id": "quadrupole_no_acceleration_full_length",
            "evidence_contract_path": self.binding_file('evidence.json'),
        }

    def ion_processor_bindings(self):
        root = Path(self.binding_directory.name)
        for name in ("workspace", "artifact_root"):
            (root/name).mkdir(exist_ok=True)
        return {"workspace": str(root/"workspace"),
                "execution_environment": self.binding_file("execution_environment.json"),
                "environment_profile": "fixture", "artifact_root": str(root/"artifact_root")}

    def ion_processor_request(self):
        request = self.approved_functional_rf_request()
        request["target"] = {
            "family_id": "rf_ion_accumulation_and_pulsed_extraction",
            "preferred_project_id": "ion_processor",
            "function": "ion_capture_cooling_and_extraction", "mode": "native_electrode_functional",
        }
        request["operating_points"] = [{"mass": {"value": 524, "unit": "Da"}, "charge_state": 1}]
        request["objectives"] = [{"metric": "extraction_fraction", "operator": "maximize", "value": None, "unit": "1", "tolerance": None}]
        request["design_variables"] = []
        request["constraints"] = []
        request["required_outputs"] = ["simulation_results", "simion_model", "validation_report", "interface_state"]
        return request

    def test_oa_and_variantless_mr_bind_the_actual_release_species_and_small_authorities(self):
        import contextlib
        from msplatform.backends.simion import oa_focus_plan, two_zone_candidate
        # Bind the consumer before patching the compiler so its import-time
        # reference cannot capture this test's temporary no-GEM sentinel.
        self.assertIs(oa_focus_plan.compile_closed_two_zone_accelerator,
                      two_zone_candidate.compile_closed_two_zone_accelerator)
        source = REPO_ROOT/"src/msplatform/components/multi_reflection_tof/config"
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as guards:
            root = Path(directory)
            release = root/"release.json"
            release.write_bytes((source/"accelerator_component_release_n100.json").read_bytes())
            condition = root/"condition.json"
            condition.write_text(json.dumps(dict(schema_version=1, role="mrtof_native_candidate_campaign_condition",
                                                 K=4.0, accelerator_y=-55.0)), encoding="utf-8")
            small = root/"definition.json"
            small.write_text("{}", encoding="utf-8")
            artifact = root/"artifacts"
            artifact.mkdir()
            context = root/"context.json"
            body = dict(schema_version=2, role="mrtof_native_candidate_condition_context")
            for key in ("contract_path", "fixed_grid_mirror_run_manifest", "geometry_review_run_path",
                        "native_corridor_bank_run_path", "native_system_runtime_bundle_path", "source_definition_path"):
                body[key] = str(small)
            body.update(oa_base_release_spec_path=str(release),
                        oa_request_path=str(source/"accelerator_component_request_n100.json"),
                        accelerator_component_contract_path=str(REPO_ROOT/"src/msplatform/components/orthogonal_accelerator/component_contract.json"),
                        accelerator_geometry_profile_id="closed_two_zone_compact_mr_axial_r3_gap1_4mm")
            context.write_text(json.dumps(body), encoding="utf-8")
            guards.enter_context(patch.object(two_zone_candidate, "compile_closed_two_zone_accelerator",
                                               side_effect=AssertionError("capability binding rendered GEM")))
            for owner, family, function, mode, metric, variant, bindings in (
                ("orthogonal_accelerator", "orthogonal_pulsed_accelerators", "orthogonal_acceleration",
                 "component_focus", "first_time_focus_distance", "two_zone",
                 dict(component_request_path=str(source/"accelerator_component_request_n100.json"), release_spec_path=str(release),
                      artifact_root=str(artifact))),
                ("multi_reflection_tof", "tof_mass_analyzers", "mass_analysis",
                 "native_condition", "detection_fraction", None,
                 dict(condition_path=str(condition), context_path=str(context), composition_plan_path=str(small),
                      artifact_root=str(artifact))),
            ):
                with self.subTest(owner=owner):
                    request = self.approved_functional_rf_request()
                    request["target"] = dict(family_id=family, preferred_project_id=owner, function=function, mode=mode)
                    if variant:
                        request["target"]["structural_variant_id"] = variant
                    request["design_variables"] = []
                    request["required_outputs"] = ["simulation_results"]
                    request["objectives"] = [dict(metric=metric, operator="maximize", value=None, unit="1", tolerance=None)]
                    request["operating_points"][0]["mass"]["value"] = 524
                    ready = self.compile_request(request, bindings)
                    self.assertEqual(ready["status"], "EXECUTION_READY", ready["blockers"])
                    arguments = ready["commands"][0]["arguments"]
                    for option, expected in (("-WorkspaceRoot", str(REPO_ROOT)),
                                             ("-ArtifactRoot", str(artifact)),
                                             ("-PythonExe", str(Path(sys.executable).resolve()))):
                        self.assertEqual(arguments[arguments.index(option) + 1], expected)
                    without_artifact = dict(bindings)
                    without_artifact.pop("artifact_root")
                    blocked = self.compile_request(request, without_artifact)
                    self.assertEqual(blocked["status"], "NEEDS_RUNTIME_INPUTS")
                    self.assertIn("artifact_root", " ".join(blocked["blockers"]))
                    self.assertFalse(blocked["safe_to_execute"])
                    protected = {row["path"] for row in ready["binding_authorities"]}
                    self.assertIn(str(release.resolve()), protected)
                    if owner == "orthogonal_accelerator":
                        self.assertIn(str((REPO_ROOT/"src/msplatform/components/orthogonal_accelerator/component_contract.json").resolve()), protected)
                    else:
                        self.assertIn(str(small.resolve()), protected)
                        self.assertIn(str(Path(body["accelerator_component_contract_path"]).resolve()), protected)
                    request["operating_points"][0]["mass"]["value"] = 100
                    refused = self.compile_request(request, bindings)
                    self.assertEqual(refused["status"], "NEEDS_RUNTIME_INPUTS")
                    self.assertIn("actual bound release species", " ".join(refused["blockers"]))
                    self.assertFalse(refused["safe_to_execute"])
                    if owner == "multi_reflection_tof":
                        body["native_corridor_bank_run_path"] = str(root/"missing-bank")
                        context.write_text(json.dumps(body), encoding="utf-8")
                        request["operating_points"][0]["mass"]["value"] = 524
                        needs_prepare = self.compile_request(request, bindings)
                        self.assertEqual(needs_prepare["status"], "NEEDS_SCIENTIFIC_PREPARATION")
                        self.assertIn("native_corridor_bank_run_path", " ".join(needs_prepare["blockers"]))
                        self.assertFalse(needs_prepare["safe_to_execute"])

    def test_retired_qualification_plan_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path = root / "request.json"
            request_path.write_text(json.dumps(self.approved_functional_rf_request()))
            plan, _ = build_plan(request_path, self.registry, self.run_id)
            plan_path = root / "plan.json"
            for legacy in ("plan", "static", "candidate", "formal"):
                plan["requested_evidence_level"] = legacy
                plan_path.write_text(json.dumps(plan))
                with self.assertRaisesRegex(ValueError, "retired qualification"):
                    compile_execution(plan_path, self.registry, self.functional_bindings())
            del plan["requested_evidence_level"]
            plan_path.write_text(json.dumps(plan))
            result = compile_execution(plan_path, self.registry, self.functional_bindings(), purpose="finite_transport")
            self.assertEqual(result["status"], "EXECUTION_READY")
            self.assertNotIn("requested_qualification", result)
            self.assertEqual(compile_execution(plan_path, self.registry, self.functional_bindings(), purpose="model_tree_build")["status"], "NEEDS_IMPLEMENTATION")

    def test_cli_rejects_retired_qualification_and_old_saved_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.json"
            path.write_text(json.dumps({"schema_version": 1, "role": "execution_dry_run",
                                        "safe_to_execute": True}), encoding="utf-8")
            for args in (("--qualification", "formal"), ("--execute-plan", str(path))):
                result = subprocess.run([sys.executable, "-m", "tools.repository.compile_execution_plan", *args],
                                        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertNotEqual(result.returncode, 0)

    def test_capability_view_includes_components_and_assemblies_without_a_pseudo_project(self):
        from tools.repository.build_project_registry import query_capabilities
        view = query_capabilities(load_json(self.registry))
        projects = {row["owner_id"]: row for row in view if row["owner_kind"] == "project"}
        self.assertEqual(len(projects), 8)
        self.assertEqual(projects["apertured_tube_electron_impact_ion_source"]["execution_support"], "no_registered_physical_entry")
        self.assertEqual(projects["orthogonal_accelerator"]["profiles"][0]["required_bindings"],
                         ["component_request_path", "release_spec_path", "artifact_root"])
        self.assertEqual(projects["multi_reflection_tof"]["profiles"][0]["profile_id"], "native_condition")
        assemblies = [row for row in view if row["owner_kind"] == "assembly"]
        self.assertEqual([row["owner_id"] for row in assemblies], ["instrument_assembly"])
        self.assertNotIn("instrument_assembly", projects)
        self.assertEqual({row["workflow_id"] for row in assemblies[0]["profiles"]},
                         {"oa_mr_flight"})
        with self.assertRaisesRegex(ValueError, "Unknown capability owner"):
            query_capabilities(load_json(self.registry), owner="missing")

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_native_registrations_match_actual_mandatory_powershell_parameters(self):
        registered = {}
        for project, profile_id in (
            ("multi_reflection_tof", "native_condition"),
            ("orthogonal_accelerator", "component_focus"),
        ):
            document = load_json(resolve_project_root(project)/"config/execution_profiles.json")
            profile = next(item for item in document["profiles"] if item["profile_id"] == profile_id)
            step = profile["steps"][0]
            registered[str(REPO_ROOT/step["entrypoint"])] = step["arguments"]
        assemblies = load_json(REPO_ROOT/"src/msplatform/workflows/config/assembly_registry.json")
        workflow = next(item for item in assemblies["assemblies"][0]["workflows"]
                        if item["workflow_id"] == "oa_mr_flight")
        registered[str(REPO_ROOT/workflow["entrypoint"])] = workflow["arguments"]
        script = r"""
$rows=@(foreach($path in $args){
  $command=Get-Command -Name $path -ErrorAction Stop
  $set=$command.DefaultParameterSet
  $required=@($command.Parameters.GetEnumerator()|Where-Object{
    @($_.Value.Attributes|Where-Object{
      $_-is[Management.Automation.ParameterAttribute]-and$_.Mandatory-and
      ($_.ParameterSetName-eq'__AllParameterSets'-or$_.ParameterSetName-eq$set)
    }).Count-gt0
  }|ForEach-Object{$_.Key})
  [pscustomobject]@{path=$path;parameters=@($command.Parameters.Keys);required=$required}
})
ConvertTo-Json -InputObject $rows -Depth 4 -Compress
"""
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory)/"inspect_parameters.ps1"
            harness.write_text(script, encoding="utf-8")
            completed = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-NonInteractive",
                                        "-File", str(harness), *registered], cwd=REPO_ROOT,
                                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        metadata = {row["path"]: row for row in json.loads(completed.stdout)}
        self.assertEqual(set(metadata), set(registered))
        for path, arguments in registered.items():
            with self.subTest(entrypoint=path):
                declared = {value[1:] for value in arguments if value.startswith("-")}
                self.assertLessEqual(declared, set(metadata[path]["parameters"]))
                self.assertLessEqual(set(metadata[path]["required"]), declared)
                self.assertIn("PythonExe", declared)

    def test_assembly_plans_freeze_real_entry_arguments_and_report_each_missing_input(self):
        from tools.repository.compile_execution_plan import compile_assembly_execution
        from tools.repository.build_project_registry import query_capabilities
        rows = query_capabilities(load_json(self.registry), owner="instrument_assembly")[0]["profiles"]
        for row in rows:
            with self.subTest(workflow=row["workflow_id"]):
                missing = compile_assembly_execution("instrument_assembly", row["workflow_id"], self.run_id, {})
                self.assertEqual(missing["status"], "NEEDS_RUNTIME_INPUTS")
                self.assertEqual(len(missing["blockers"]), len(row["required_bindings"]))
                bindings = {}
                for key, kind in row["binding_types"].items():
                    if kind in {"directory", "run_directory"}:
                        directory = Path(self.binding_directory.name)/key
                        directory.mkdir(exist_ok=True)
                        (directory/"run_manifest.json").write_text("{}")
                        bindings[key] = str(directory)
                    else:
                        bindings[key] = "123.5" if kind == "number" else self.binding_file(key+".json")
                result = compile_assembly_execution("instrument_assembly", row["workflow_id"], self.run_id, bindings)
                self.assertEqual(result["status"], "EXECUTION_READY")
                self.assertEqual(result["owner_kind"], "assembly")
                self.assertNotIn("project_id", result)
                self.assertEqual(Path(result["commands"][0]["entrypoint"]), REPO_ROOT/row["entrypoint"])
                self.assertFalse(any("{" in value for value in result["commands"][0]["arguments"]))
        with self.assertRaisesRegex(ValueError, "Unknown Assembly workflow"):
            compile_assembly_execution("instrument_assembly", "arbitrary_script", self.run_id, {})

    def test_fixed_input_consumers_freeze_compiled_values_instead_of_current_defaults(self):
        project = "dual_cone_tandem_quadrupole"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = load_json(resolve_project_root(project)/"config/execution_profiles.json")["profiles"][0]
            private = root/"compiled"
            records = []
            for name, path in profile["fixed_inputs"].items():
                source = private/path
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text('{"value":2}')
                from msplatform.io.manifest_records import file_record
                records.append(dict(file_record(source), name=name, relative_path=path))
            bundle = root/"resolved.json"
            bundle.write_text(json.dumps(dict(role="compiled_execution_inputs", project_id=project,
                                               root=str(private), files=records)))
            from msplatform.backends.comsol.gas_flow import compiled_gas_flow_paths
            selected = compiled_gas_flow_paths(bundle)
            self.assertEqual(len(selected), len(profile["fixed_inputs"]))
            for path in selected:
                self.assertEqual(json.loads(path.read_text())["value"], 2)

    def test_oa_mr_requires_real_accelerator_authority_and_transports_plan_context(self):
        from tools.repository.compile_execution_plan import compile_assembly_execution
        contract = REPO_ROOT/"src/msplatform/components/orthogonal_accelerator/component_contract.json"
        composition = REPO_ROOT/"src/msplatform/workflows/config/oa_mr_two_zone_gap30_plan.json"
        bindings = {
            "accelerator_component_contract_path": str(contract),
            "accelerator_geometry_profile_id": "closed_two_zone_compact_mr_axial_r3_gap1_4mm",
            "accelerator_provider_receipt_path": self.binding_file("provider.json"),
            "composition_plan_path": str(composition),
            "prism1_voltage_v": "-1.25",
            "prism2_voltage_v": "2.5",
        }
        for key in ("geometry_review_run_path", "mirror_run_path", "stripe_run_path"):
            directory = Path(self.binding_directory.name)/key
            directory.mkdir()
            (directory/"run_manifest.json").write_text("{}", encoding="utf-8")
            bindings[key] = str(directory)
        ready = compile_assembly_execution("instrument_assembly", "oa_mr_flight", self.run_id, bindings)
        self.assertEqual(ready["status"], "EXECUTION_READY", ready["blockers"])
        arguments = ready["commands"][0]["arguments"]
        for option, expected in (
            ("-AcceleratorComponentContractPath", str(contract)),
            ("-AcceleratorGeometryProfileId", bindings["accelerator_geometry_profile_id"]),
            ("-RepoRoot", str(REPO_ROOT)),
            ("-PythonExe", str(Path(sys.executable).resolve())),
        ):
            self.assertEqual(arguments[arguments.index(option) + 1], expected)
        self.assertIn(str(contract.resolve()),
                      {record["path"] for record in ready["binding_authorities"]})
        for key in ("accelerator_component_contract_path", "accelerator_geometry_profile_id"):
            with self.subTest(missing=key):
                incomplete = dict(bindings)
                incomplete.pop(key)
                result = compile_assembly_execution("instrument_assembly", "oa_mr_flight",
                                                    self.run_id, incomplete)
                self.assertEqual(result["status"], "NEEDS_RUNTIME_INPUTS")
                self.assertIn(key, " ".join(result["blockers"]))
                self.assertFalse(result["safe_to_execute"])
        missing_source = dict(bindings)
        missing_source["accelerator_component_contract_path"] = str(
            Path(self.binding_directory.name)/"missing-contract.json")
        result = compile_assembly_execution("instrument_assembly", "oa_mr_flight",
                                            self.run_id, missing_source)
        self.assertEqual(result["status"], "NEEDS_RUNTIME_INPUTS")
        self.assertIn("accelerator_component_contract_path: file is missing",
                      " ".join(result["blockers"]))

    def test_assembly_optional_bindings_use_existing_authority_and_owner(self):
        from tools.repository.compile_execution_plan import compile_assembly_execution, parse_bindings
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / "src/msplatform/workflows/resources/fixture.ps1"
            entry.parent.mkdir(parents=True)
            entry.write_text("param()\n", encoding="utf8")
            required = root / "request.json"
            required.write_text('{"required":true}', encoding="utf8")
            optional = root / "basis.json"
            optional.write_text('{"sample":"actual"}', encoding="utf8")
            workflow = dict(workflow_id="fixture", entrypoint="src/msplatform/workflows/resources/fixture.ps1",
                required_bindings=["request"], binding_types=dict(request="file", scalar_field_basis="file"),
                arguments=["-Request", "{request}"],
                optional_arguments={"scalar_field_basis": ["-ScalarFieldBasis", "{scalar_field_basis}"]},
                outputs=["trajectory_artifact_ref"], simulation_paths=["continuous_assembly"], recipes=[],
                limitations=[], purpose="assembly_propagation", action="run", tools=["python"],
                model="public stage", run_identity="backend_generated")
            registry = root / "src/msplatform/workflows/config/assembly_registry.json"
            def write_registry():
                registry.parent.mkdir(parents=True, exist_ok=True)
                registry.write_text(json.dumps(dict(schema_version=1, role="assembly_registry",
                    assemblies=[dict(assembly_id="instrument_assembly", workflows=[workflow])])), encoding="utf8")
            def compile_with(bindings):
                return compile_assembly_execution("instrument_assembly", "fixture", self.run_id, bindings)
            with patch("tools.repository.compile_execution_plan.REPO_ROOT", root), patch(
                "tools.repository.compile_execution_plan._msplatform_package_root",
                return_value=root/"src/msplatform",
            ):
                write_registry()
                absent = compile_with({"request": str(required)})
                self.assertTrue(absent["safe_to_execute"])
                self.assertEqual(absent["commands"][0]["arguments"], ["-Request", str(required)])
                self.assertEqual([x["name"] for x in absent["binding_authorities"]], ["request"])
                present = compile_with({"request": str(required), "scalar_field_basis": str(optional)})
                self.assertTrue(present["safe_to_execute"])
                self.assertEqual(present["commands"][0]["arguments"],
                    ["-Request", str(required), "-ScalarFieldBasis", str(optional)])
                self.assertEqual({x["name"] for x in present["binding_authorities"]}, {"request", "scalar_field_basis"})
                self.assertIn(str(optional.resolve()), present["binding_sources"])
                bare = root / "bare.pa"
                bare.write_bytes(b"fixture")
                unbound = compile_with({"request": str(required), "scalar_field_basis": str(bare)})
                self.assertEqual(unbound["status"], "NEEDS_SOURCE_FREEZE")
                self.assertIn("scalar_field_basis", unbound["source_freeze_required"])
                missing = compile_with({"request": str(required), "scalar_field_basis": str(root/"missing.json")})
                self.assertEqual(missing["status"], "NEEDS_RUNTIME_INPUTS")
                self.assertTrue(any("scalar_field_basis: file is missing" in x for x in missing["blockers"]))
                with self.assertRaisesRegex(ValueError, "Unexpected workflow bindings"):
                    compile_with({"request": str(required), "other": str(optional)})
                workflow["optional_arguments"]["request"] = ["-Duplicate", "{request}"]
                write_registry()
                with self.assertRaisesRegex(ValueError, "disjoint"):
                    compile_with({"request": str(required)})
                workflow["optional_arguments"].pop("request")
                workflow["optional_arguments"]["untyped"] = ["-Untyped", "{untyped}"]
                write_registry()
                with self.assertRaisesRegex(ValueError, "binding types"):
                    compile_with({"request": str(required)})
                workflow["optional_arguments"].pop("untyped")
                workflow["optional_arguments"]["scalar_field_basis"].append("{run_id}")
                write_registry()
                with self.assertRaisesRegex(ValueError, "cannot bind the planning run ID"):
                    compile_with({"request": str(required)})
            with self.assertRaisesRegex(ValueError, "duplicate"):
                parse_bindings(["request=a", "request=b"])

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_optional_saved_plan_and_directory_authority(self):
        from tools.repository.compile_execution_plan import compile_assembly_execution
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / "src/msplatform/workflows/resources/fixture.ps1"
            entry.parent.mkdir(parents=True)
            entry.write_text("param($Request,$Workspace,$ScalarFieldBasis)\nSet-Content -LiteralPath (Join-Path $Workspace 'called.txt') -Value $ScalarFieldBasis\n", encoding="utf8")
            request = root / "request.json"; request.write_text('{}', encoding="utf8")
            basis = root / "basis.json"; basis.write_text('{"sample":1}', encoding="utf8")
            workspace = root / "workspace"; workspace.mkdir()
            workflow = dict(workflow_id="fixture", entrypoint="src/msplatform/workflows/resources/fixture.ps1",
                required_bindings=["request", "workspace"], binding_types=dict(request="file", workspace="directory", scalar_field_basis="file"),
                arguments=["-Request", "{request}", "-Workspace", "{workspace}"],
                optional_arguments={"scalar_field_basis": ["-ScalarFieldBasis", "{scalar_field_basis}"]},
                outputs=["trajectory_artifact_ref"], simulation_paths=["continuous_assembly"], recipes=[],
                limitations=[], purpose="assembly_propagation", action="run", tools=["python"], model="public stage")
            registry = root / "src/msplatform/workflows/config/assembly_registry.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(json.dumps(dict(schema_version=1, role="assembly_registry",
                assemblies=[dict(assembly_id="instrument_assembly", workflows=[workflow])])), encoding="utf8")
            with patch("tools.repository.compile_execution_plan.REPO_ROOT", root), patch(
                "tools.repository.compile_execution_plan._msplatform_package_root",
                return_value=root/"src/msplatform",
            ):
                def plan(bindings):return compile_assembly_execution("instrument_assembly", "fixture", self.run_id, bindings)
                plain=plan(dict(request=str(request), workspace=str(workspace)))
                selected=plan(dict(request=str(request), workspace=str(workspace), scalar_field_basis=str(basis)))
                self.assertTrue(plain["safe_to_execute"]);self.assertTrue(selected["safe_to_execute"])
                workflow["binding_types"]["workspace"]="run_directory"
                registry.write_text(json.dumps(dict(schema_version=1, role="assembly_registry",
                    assemblies=[dict(assembly_id="instrument_assembly", workflows=[workflow])])), encoding="utf8")
                self.assertEqual(plan(dict(request=str(request), workspace=str(workspace)))["status"],"NEEDS_RUNTIME_INPUTS")
                (workspace/"run_manifest.json").write_text('{}', encoding="utf8")
                self.assertIn("workspace",[x['name'] for x in plan(dict(request=str(request), workspace=str(workspace)))['binding_authorities']])
                workflow["binding_types"]["workspace"]="directory"
                registry.write_text(json.dumps(dict(schema_version=1, role="assembly_registry",
                    assemblies=[dict(assembly_id="instrument_assembly", workflows=[workflow])])), encoding="utf8")
                (workspace/"run_manifest.json").unlink()
                plain=plan(dict(request=str(request), workspace=str(workspace)))
                selected=plan(dict(request=str(request), workspace=str(workspace), scalar_field_basis=str(basis)))
            harness = root / "execute.ps1"
            harness.write_text("param($Helper,$Plan,$Repository)\n$ErrorActionPreference='Stop';Set-StrictMode -Version Latest\n. $Helper\nInvoke-CompiledExecutionPlan -PlanPath $Plan -RepoRoot $Repository\n", encoding="utf8")
            target = root/"plan.json"
            self.assertFalse((workspace/"run_manifest.json").exists())
            def execute(value):
                target.write_text(json.dumps(value), encoding="utf8")
                return subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(harness),
                    str(self.copy_execution_resources(root)), str(target), str(root)],
                    cwd=REPO_ROOT,capture_output=True,text=True,encoding="utf8",errors="replace",timeout=30)
            for value in (plain, selected):
                result=execute(value);self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            changed=copy.deepcopy(selected);changed['commands'][0]['arguments'][-2]='-Changed'
            self.assertNotEqual(execute(changed).returncode,0)
            changed=copy.deepcopy(selected);changed['commands'][0]['arguments'][-1]=str(request)
            self.assertNotEqual(execute(changed).returncode,0)
            basis.unlink();self.assertNotEqual(execute(selected).returncode,0)

    def test_assembly_backend_generated_identity_is_not_a_planned_run(self):
        from tools.repository.compile_execution_plan import compile_assembly_execution
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / 'src/msplatform/workflows/resources/fixture.ps1'
            entry.parent.mkdir(parents=True)
            entry.write_text('param()\n', encoding='utf8')
            workflow = dict(workflow_id='fixture', entrypoint='src/msplatform/workflows/resources/fixture.ps1',
                required_bindings=[], binding_types={}, arguments=[], outputs=['trajectory_artifact_ref'],
                simulation_paths=['continuous_assembly'], recipes=[], limitations=[],
                purpose='assembly_propagation', action='run', tools=['python'], model='public stage',
                run_identity='backend_generated')
            registry = root / 'src/msplatform/workflows/config/assembly_registry.json'

            def write_registry():
                registry.parent.mkdir(parents=True, exist_ok=True)
                registry.write_text(json.dumps(dict(schema_version=1, role='assembly_registry',
                    assemblies=[dict(assembly_id='instrument_assembly', workflows=[workflow])])), encoding='utf8')

            with patch('tools.repository.compile_execution_plan.REPO_ROOT', root), patch(
                'tools.repository.compile_execution_plan._msplatform_package_root',
                return_value=root/'src/msplatform',
            ):
                write_registry()
                result = compile_assembly_execution('instrument_assembly', 'fixture', self.run_id, {})
                command = result['commands'][0]
                self.assertTrue(result['safe_to_execute'])
                self.assertIsNone(command['run_id'])
                self.assertEqual(command['planning_run_id'], self.run_id)
                self.assertEqual(command['run_identity'], 'backend_generated')
                self.assertNotIn(self.run_id, command['argv'])
                workflow['arguments'] = ['-RunId', '{run_id}']
                write_registry()
                with self.assertRaisesRegex(ValueError, 'cannot bind the planning run ID'):
                    compile_assembly_execution('instrument_assembly', 'fixture', self.run_id, {})
                workflow['run_identity'] = 'caller_selected'
                write_registry()
                command = compile_assembly_execution('instrument_assembly', 'fixture', self.run_id, {})['commands'][0]
                self.assertEqual(command['run_id'], self.run_id)
                self.assertIn(self.run_id, command['argv'])
                self.assertNotIn('planning_run_id', command)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_assembly_execution_reaches_its_real_declared_parameters(self):
        from tools.repository.compile_execution_plan import compile_assembly_execution
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workflows = root/"src/msplatform/workflows"
            entry = workflows/"resources/fixture.ps1"
            entry.parent.mkdir(parents=True)
            request = root/"request.json"
            request.write_text('{"source":"frozen"}')
            entry.write_text(r"""param($Request,[double]$PrismVoltage,$RunId,$RepoRoot,$PythonExe)
$ErrorActionPreference='Stop'
$input=Get-Content $Request -Raw|ConvertFrom-Json
& $PythonExe -c "import sys;print('ACTUAL_INTERPRETER='+sys.executable)"
if($LASTEXITCODE-ne0){throw 'planned interpreter failed'}
@{source=$input.source;voltage=$PrismVoltage;run_id=$RunId;repository=$RepoRoot}|ConvertTo-Json|Set-Content (Join-Path $PSScriptRoot 'actual.json')
""", encoding="utf-8")
            workflow = dict(workflow_id="fixture", entrypoint="src/msplatform/workflows/resources/fixture.ps1",
                required_bindings=["request", "voltage"], binding_types=dict(request="file", voltage="number"),
                arguments=["-Request", "{request}", "-PrismVoltage", "{voltage}", "-RunId", "{run_id}",
                           "-RepoRoot", "{repository_root}", "-PythonExe", "{python_exe}"],
                outputs=["receipt"], simulation_paths=["continuous_assembly"], recipes=[], limitations=[],
                purpose="assembly_propagation", action="run", tools=["python"], model="inert fixture")
            registry = root / "src/msplatform/workflows/config/assembly_registry.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(json.dumps(dict(schema_version=1, role="assembly_registry",
                assemblies=[dict(assembly_id="instrument_assembly", workflows=[workflow])])))
            with patch("tools.repository.compile_execution_plan.REPO_ROOT", root), patch(
                "tools.repository.compile_execution_plan._msplatform_package_root",
                return_value=root/"src/msplatform",
            ):
                result = compile_assembly_execution("instrument_assembly", "fixture", self.run_id,
                                                       dict(request=str(request), voltage="-123.5"))
            plan = root/"compiled.json"
            plan.write_text(json.dumps(result))
            harness = root/"execute.ps1"
            harness.write_text(r"""param($Helper,$Plan,$Repository)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. $Helper
Invoke-CompiledExecutionPlan -PlanPath $Plan -RepoRoot $Repository
""", encoding="utf-8")
            completed = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(harness),
                str(self.copy_execution_resources(root)), str(plan), str(root)],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
            actual = json.loads((entry.parent/"actual.json").read_text())
            self.assertEqual(actual, dict(source="frozen", voltage=-123.5, run_id=self.run_id,
                                          repository=str(root)))
            self.assertIn("ACTUAL_INTERPRETER=" + str(Path(sys.executable).resolve()), completed.stdout)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_installed_package_copy_rejects_checkout_code_substitution(self):
        from tools.repository.compile_execution_plan import compile_assembly_execution
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root/"checkout"
            package = root/"installed/msplatform"
            caller = root/"unrelated-caller"
            caller.mkdir()
            entry = package/"workflows/resources/fixture.ps1"
            entry.parent.mkdir(parents=True)
            entry.write_text(r"""param($Request,$PythonExe)
$ErrorActionPreference='Stop'
$input=Get-Content $Request -Raw|ConvertFrom-Json
& $PythonExe -I -B -c "import sys;print('ACTUAL_INTERPRETER='+sys.executable)"
if($LASTEXITCODE-ne0){throw 'planned interpreter failed'}
@{source=$input.source;entrypoint=$PSCommandPath}|ConvertTo-Json|Set-Content (Join-Path $PSScriptRoot 'actual.json')
""", encoding="utf-8")
            checkout_entry = checkout/"src/msplatform/workflows/resources/fixture.ps1"
            checkout_entry.parent.mkdir(parents=True)
            checkout_entry.write_text("Set-Content -LiteralPath (Join-Path $PSScriptRoot 'wrong-source.txt') -Value 'forbidden'\n",
                                      encoding="utf-8")
            self.assertNotEqual(entry.read_bytes(), checkout_entry.read_bytes())
            request = root/"request.json"
            request.write_text('{"source":"selected-package"}', encoding="utf-8")
            workflow = dict(workflow_id="fixture", entrypoint="src/msplatform/workflows/resources/fixture.ps1",
                required_bindings=["request"], binding_types={"request": "file"},
                arguments=["-Request", "{request}", "-PythonExe", "{python_exe}"],
                outputs=["receipt"], simulation_paths=["continuous_assembly"], recipes=[], limitations=[],
                purpose="assembly_propagation", action="run", tools=["python"], model="installed package fixture")
            registry = checkout/"src/msplatform/workflows/config/assembly_registry.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(json.dumps(dict(schema_version=1, role="assembly_registry",
                assemblies=[dict(assembly_id="instrument_assembly", workflows=[workflow])])), encoding="utf-8")
            with patch("tools.repository.compile_execution_plan.REPO_ROOT", checkout), patch(
                "tools.repository.compile_execution_plan._msplatform_package_root", return_value=package,
            ):
                result = compile_assembly_execution("instrument_assembly", "fixture", self.run_id,
                                                    {"request": str(request)})
            command = result["commands"][0]
            self.assertEqual(Path(command["entrypoint"]), entry.resolve())
            self.assertNotEqual(Path(command["entrypoint"]), checkout_entry.resolve())
            shutil.copytree(REPO_ROOT/"src/msplatform/execution/resources", package/"execution/resources")
            helper = package/"execution/resources/run_artifact_support.ps1"
            harness = root/"execute.ps1"
            harness.write_text("param($Helper,$Plan,$Repository)\n$ErrorActionPreference='Stop'\n"
                               ". $Helper\nInvoke-CompiledExecutionPlan -PlanPath $Plan -RepoRoot $Repository\n",
                               encoding="utf-8")
            plan_path = root/"compiled.json"

            def execute(value):
                plan_path.write_text(json.dumps(value), encoding="utf-8")
                environment = dict(os.environ)
                environment["PYTHONPATH"] = str(checkout/"src")
                environment["SIMULATION_PYTHON_EXE"] = str(root/"unavailable/python.exe")
                return subprocess.run([shutil.which("pwsh"), "-NoProfile", "-NonInteractive", "-File",
                                       str(harness), str(helper), str(plan_path), str(checkout)],
                                      cwd=caller, env=environment, capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=30)

            completed = execute(result)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            actual = json.loads((entry.parent/"actual.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(actual, {"source": "selected-package", "entrypoint": str(entry)})
            self.assertIn("ACTUAL_INTERPRETER=" + str(Path(sys.executable).resolve()), completed.stdout)
            self.assertFalse((checkout_entry.parent/"wrong-source.txt").exists())

            substituted = copy.deepcopy(result)
            substituted["commands"][0]["entrypoint"] = str(checkout_entry.resolve())
            refused = execute(substituted)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("Compiled command differs from declared entrypoint", refused.stdout + refused.stderr)
            self.assertFalse((checkout_entry.parent/"wrong-source.txt").exists())
            (entry.parent/"actual.json").unlink()
            entry.unlink()
            missing = execute(result)
            self.assertNotEqual(missing.returncode, 0)
            self.assertFalse((entry.parent/"actual.json").exists())
            self.assertFalse((checkout_entry.parent/"wrong-source.txt").exists())

            (package/"__init__.py").write_text("", encoding="utf-8")
            (package/"workflows/__init__.py").write_text("", encoding="utf-8")
            python_entry = package/"workflows/fixture.py"
            python_entry.write_text("from pathlib import Path\n"
                                    "Path(__file__).with_name('python_actual.json').write_text('selected-package')\n"
                                    "print('PYTHON_MODULE_SOURCE='+__file__)\n", encoding="utf-8")
            checkout_python = checkout/"src/msplatform/workflows/fixture.py"
            checkout_python.write_text("from pathlib import Path\n"
                                       "Path(__file__).with_name('wrong-python-source.txt').write_text('forbidden')\n",
                                       encoding="utf-8")
            project = checkout/"src/msplatform/components/fixture"
            (project/"config").mkdir(parents=True)
            (checkout/"config").mkdir()
            (checkout/"config/project_registry.json").write_text(json.dumps(dict(projects=[dict(
                project_id="fixture", contracts=dict(execution="config/execution_profiles.json"))])), encoding="utf-8")
            contract = project/"config/execution_profiles.json"
            contract_document = {"profiles": [{"profile_id": "fixture", "steps": [dict(
                step_id="python_run", shell="python",
                entrypoint="src/msplatform/workflows/fixture.py", arguments=[])]}]}
            contract.write_text(json.dumps(contract_document), encoding="utf-8")
            python_plan = dict(schema_version=2, role="execution_dry_run", status="EXECUTION_READY", safe_to_execute=True,
                python_executable=str(Path(sys.executable).resolve()), project_id="fixture", profile_id="fixture",
                execution_contract=dict(path=str(contract), sha256=hashlib.sha256(contract.read_bytes()).hexdigest().upper()),
                planning_sources=[], binding_authorities=[], binding_sources=[], resolved_inputs=[], resolved_runtime=None,
                commands=[dict(step_id="python_run", shell="python", entrypoint=str(python_entry.resolve()), arguments=[])])
            python_result = execute(python_plan)
            self.assertEqual(python_result.returncode, 0, python_result.stdout + python_result.stderr)
            self.assertIn("PYTHON_MODULE_SOURCE=" + str(python_entry), python_result.stdout)
            self.assertEqual((python_entry.parent/"python_actual.json").read_text(), "selected-package")
            self.assertFalse((checkout_python.parent/"wrong-python-source.txt").exists())
            python_plan["commands"][0]["entrypoint"] = str(checkout_python.resolve())
            refused_python = execute(python_plan)
            self.assertNotEqual(refused_python.returncode, 0)
            self.assertFalse((checkout_python.parent/"wrong-python-source.txt").exists())

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_compiled_executor_uses_frozen_definition_and_rejects_drift_or_other_entrypoint(self):
        from msplatform.execution.retention import file_record
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root/"src/msplatform/components/fixture"
            (project/"config").mkdir(parents=True)
            original = project/"config/science.json"
            original.write_text('{"value":2}')
            entry = project/"run.ps1"
            entry.write_text(r"""param($ResolvedInputsPath)
$ErrorActionPreference='Stop'
$bundle=Get-Content $ResolvedInputsPath -Raw|ConvertFrom-Json
$actual=Get-Content (Join-Path $bundle.root 'config/science.json') -Raw|ConvertFrom-Json
$blocked=$false
try{$writer=[IO.File]::Open($bundle.files[0].path,'Open','Write','ReadWrite');$writer.Dispose()}catch{$blocked=$true}
if(-not$blocked){throw 'source guard was not held until owner freeze'}
$actual|ConvertTo-Json|Set-Content (Join-Path $PSScriptRoot 'actual.json')
""", encoding="utf-8")
            (root/"config").mkdir()
            (root/"config/project_registry.json").write_text(json.dumps(dict(projects=[dict(project_id="fixture", contracts=dict(execution="config/execution_profiles.json"))])))
            contract = project/"config/execution_profiles.json"
            contract.write_text(json.dumps(dict(profiles=[dict(profile_id="fixture", fixed_inputs=dict(science="config/science.json"),
                steps=[dict(step_id="run", entrypoint="src/msplatform/components/fixture/run.ps1", shell="powershell", arguments=["-ResolvedInputsPath", "{resolved_inputs_path}"])])])))
            plan = dict(schema_version=2, role="execution_dry_run", status="EXECUTION_READY", safe_to_execute=True,
                python_executable=str(Path(sys.executable).resolve()),
                project_id="fixture", profile_id="fixture", execution_contract=file_record(contract),
                resolved_inputs=[dict(file_record(original), name="science", relative_path="config/science.json", content=original.read_text())],
                planning_sources=[], binding_authorities=[], binding_sources=[], resolved_runtime=None,
                commands=[dict(step_id="run", shell="powershell", entrypoint=str(entry), arguments=["-ResolvedInputsPath", "__COMPILED_INPUTS__"])])
            plan_path = root/"plan.json"
            harness = root/"execute.ps1"
            harness.write_text(r"""param($Helper,$Plan,$Repository)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. $Helper
Invoke-CompiledExecutionPlan -PlanPath $Plan -RepoRoot $Repository
""", encoding="utf-8")
            for mode in ("success", "drift", "content", "entrypoint", "missing_python", "unavailable_python", "legacy_version", "legacy_grade"):
                with self.subTest(mode=mode):
                    actual = copy.deepcopy(plan)
                    if mode == "legacy_version": actual["schema_version"] = 1
                    if mode == "legacy_grade": actual["requested_qualification"] = "candidate"
                    original.write_text('{"value":3}' if mode == "drift" else '{"value":2}')
                    if mode == "content": actual["resolved_inputs"][0]["content"] = '{"value":9}'
                    if mode == "entrypoint": actual["commands"][0]["entrypoint"] = str(root/"other.ps1")
                    if mode == "missing_python": del actual["python_executable"]
                    if mode == "unavailable_python": actual["python_executable"] = str(root/"missing/python.exe")
                    (project/"actual.json").unlink(missing_ok=True)
                    plan_path.write_text(json.dumps(actual))
                    completed = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(harness),
                        str(self.copy_execution_resources(root)), str(plan_path), str(root)],
                        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
                    if mode == "success":
                        self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
                        self.assertEqual(json.loads((project/"actual.json").read_text())["value"], 2)
                    else:
                        self.assertNotEqual(completed.returncode, 0)
                        self.assertFalse((project/"actual.json").exists())
                        if mode in ("missing_python", "unavailable_python"):
                            self.assertIn("recompile with the intended Python executable",
                                          completed.stdout + completed.stderr)
                    original.write_text('{"value":2}')  # release is observable after every branch

    def test_canonical_src_profile_compiles_to_installed_module_without_changing_project_mapping(self):
        request = load_json(HERE / "fixtures" / "oa_tof_500da_r30000.example.json")
        request["status"] = "approved"
        request["approval"] = {"approved_by": "owner", "approved_on": "2026-07-20"}
        request["target"]["mode"] = "design_candidate"
        request["operating_points"] = [{"mass": {"value": 524, "unit": "Da"}, "charge_state": 1}]
        request["objectives"] = [dict(metric="transmission_fraction", operator="maximize", value=None,
                                      unit="1", tolerance=None)]
        request["constraints"] = []
        request["design_variables"] = []
        original = self.compile_request(request, {"particle_source_seed": "20260720"}, proposal=True)
        self.assertEqual(original["status"], "EXECUTION_READY")
        self.assertEqual(original["commands"][0]["argv"][1:3],
                         ["-m", "msplatform.workflows.oa_candidate.run_candidate"])
        installed = REPO_ROOT / "src/msplatform/analysis/tof_error_budget.py"
        self.assertTrue(installed.is_file())
        execution = resolve_project_root("single_reflection_oa_tof_mass_analyzer") / "config/execution_profiles.json"

        def selected_load(path):
            document = load_json(path)
            if Path(path) == execution:
                document = copy.deepcopy(document)
                profile = next(item for item in document["profiles"]
                               if item["profile_id"] == "validated_structural_candidate")
                profile["steps"][0]["entrypoint"] = "src/msplatform/analysis/tof_error_budget.py"
            return document

        with patch("tools.repository.compile_execution_plan.load_json", side_effect=selected_load):
            selected = self.compile_request(request, {"particle_source_seed": "20260720"}, proposal=True)
        self.assertEqual(selected["status"], "EXECUTION_READY")
        self.assertEqual(selected["commands"][0]["argv"][1:3], ["-m", "msplatform.analysis.tof_error_budget"])
        self.assertEqual(Path(selected["commands"][0]["entrypoint"]), installed.resolve())
        original_arguments = original["commands"][0]["arguments"]
        selected_arguments = selected["commands"][0]["arguments"].copy()
        self.assertEqual(original_arguments[original_arguments.index("--request") + 1],
                         original["planning_sources"][2]["path"])
        self.assertEqual(selected_arguments[selected_arguments.index("--request") + 1],
                         selected["planning_sources"][2]["path"])
        selected_arguments[selected_arguments.index("--request") + 1] = original_arguments[original_arguments.index("--request") + 1]
        self.assertEqual(selected_arguments, original_arguments)

    def test_ordinary_profiles_compile_only_declared_scientific_steps_and_empty_ei_is_unavailable(self):
        from msplatform.contracts.machine_contracts import sha256, validate_schema
        projects = ("apertured_tube_electron_impact_ion_source", "dual_cone_tandem_quadrupole",
                    "ion_processor", "rf_multipole_ion_optics",
                    "single_reflection_oa_tof_mass_analyzer", "transverse_helical_filament_wehnelt_electron_gun")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root/"request.json"
            request.write_text("{}")
            plan_path = root/"plan.json"
            count = 0
            for project in projects:
                document = load_json(resolve_project_root(project)/"config/execution_profiles.json")
                validate_schema(document, "execution_profiles.schema.json")
                profiles = document["profiles"]
                if not profiles:
                    self.assertEqual(project, "apertured_tube_electron_impact_ion_source")
                for profile in profiles or [dict(capability_id="electron_impact_ionization_feasibility", mode="build_only_smoke")]:
                    plan = dict(schema_version=2, role="solver_neutral_design_plan", request_status="approved", project_id=project, capability_id=profile["capability_id"],
                        mode=profile["mode"], run_id=self.run_id, operating_points=[],
                        objectives=[], design_variables=[], constraints=[], required_outputs=[],
                        provenance=dict(request=dict(path=str(request), sha256=sha256(request)),
                                        project_registry=dict(sha256=sha256(self.registry))))
                    plan_path.write_text(json.dumps(plan))
                    result = compile_execution(plan_path, self.registry)
                    if not profiles:
                        self.assertEqual(result["status"], "NEEDS_IMPLEMENTATION")
                        self.assertFalse(result["safe_to_execute"])
                        self.assertEqual(result["commands"], [])
                        continue
                    count += 1
                    self.assertEqual([step["step_id"] for step in result["commands"]], [step["step_id"] for step in profile["steps"]])
                    self.assertFalse(any(step["step_id"] == "static_gate" for step in result["commands"]))
            self.assertEqual(count, 11)

    def test_ion_processor_functional_runner_requires_explicit_store_and_deployment(self):
        missing = self.compile_request(self.ion_processor_request())
        self.assertEqual(missing["status"], "NEEDS_RUNTIME_INPUTS")
        self.assertFalse(missing["safe_to_execute"])
        for name in ("workspace", "execution_environment", "environment_profile", "artifact_root"):
            self.assertIn(name, " ".join(missing["blockers"]))
        result = self.compile_request(self.ion_processor_request(), self.ion_processor_bindings())
        self.assertEqual(result["status"], "EXECUTION_READY")
        self.assertEqual(result["profile_id"], "native_functional")
        self.assertEqual([item["step_id"] for item in result["commands"]], ["native_run"])
        command = result["commands"][0]
        self.assertEqual(command["shell"], "python")
        self.assertEqual(command["argv"][:3],
                         [result["python_executable"], "-m", "msplatform.cli"])
        arguments = command["arguments"]
        self.assertEqual(arguments[:2], ["ion-processor-native-functional", "run"])
        self.assertEqual(arguments[arguments.index("--run-id") + 1], command["run_id"])
        self.assertEqual(arguments[arguments.index("--source-profile")+1], "functional")
        for option, binding in (("--workspace", "workspace"),
                                ("--execution-environment", "execution_environment"),
                                ("--environment-profile", "environment_profile"),
                                ("--artifact-root", "artifact_root")):
            self.assertEqual(arguments[arguments.index(option) + 1], self.ion_processor_bindings()[binding])
        self.assertTrue(any("Prototype" in message for message in result["limitations"]))

    def test_ion_processor_profile_rejects_unregistered_physics_and_higher_qualification(self):
        for mass, charge in ((500, 1), (524, -1)):
            request = self.ion_processor_request()
            request["operating_points"] = [{"mass": {"value": mass, "unit": "Da"}, "charge_state": charge}]
            result = self.compile_request(request)
            self.assertEqual(result["status"], "NEEDS_IMPLEMENTATION")
            self.assertFalse(result["safe_to_execute"])
        for level in ("static", "candidate", "formal"):
            request = self.ion_processor_request()
            request["evidence_level"] = level
            with self.assertRaisesRegex(ValueError, "NEEDS_CLARIFICATION"):
                self.compile_request(request)
        with self.assertRaisesRegex(ValueError, "Unexpected runtime bindings"):
            self.compile_request(self.ion_processor_request(), {"configuration_directory": "unregistered"})

    def test_approved_functional_rf_plan_is_execution_ready(self):
        result = self.compile_request(
            self.approved_functional_rf_request(), self.functional_bindings(),
        )
        self.assertEqual(result["status"], "EXECUTION_READY")
        self.assertTrue(result["safe_to_execute"])
        self.assertEqual(result["profile_id"], "quadrupole_transport_runtime_functional")
        self.assertEqual(len(result["commands"]), 2)
        self.assertEqual(
            [command["step_id"] for command in result["commands"]],
            ["comsol_run", "simion_run"],
        )
        self.assertFalse(
            any(command["step_id"] == "candidate_gate" for command in result["commands"])
        )
        self.assertIn("__sim__comsol__", result["commands"][0]["run_id"])
        for command in result["commands"]:
            self.assertIn("-ResolvedRuntimeProfilePath", command["argv"])
            self.assertEqual(result["resolved_runtime"]["runtime_profile_id"], "quadrupole_no_acceleration_full_length")
            self.assertNotIn("-ParticleSourcePath", command["argv"])
        self.assertIn(result["commands"][0]["run_id"], result["commands"][1]["argv"])
        self.assertTrue(any("does not inherit" in limitation for limitation in result["limitations"]))
        powershell_commands = [
            command for command in result["commands"] if command["shell"] == "powershell"
        ]
        self.assertTrue(powershell_commands)
        for command in powershell_commands:
            self.assertEqual(
                command["argv"][:4],
                ["pwsh.exe", "-NoProfile", "-NonInteractive", "-File"],
            )

    def test_supported_but_unapproved_request_awaits_approval(self):
        request = self.approved_functional_rf_request()
        request["status"] = "proposed"
        request["approval"] = None
        result = self.compile_request(
            request,
            self.functional_bindings(),
        )
        self.assertEqual(result["status"], "AWAITING_APPROVAL")
        self.assertFalse(result["safe_to_execute"])

    def test_old_qualification_argument_is_rejected(self):
        with self.assertRaises(TypeError):
            self.compile_request(self.approved_rf_request(), self.functional_bindings(), qualification="candidate")

    def test_functional_plan_requires_bound_runtime_and_rejects_free_source_override(self):
        request = self.approved_functional_rf_request()
        result = self.compile_request(request)
        self.assertEqual(result["status"], "NEEDS_RUNTIME_INPUTS")
        self.assertTrue(any("runtime_profile_id" in blocker for blocker in result["blockers"]))
        with self.assertRaisesRegex(ValueError, "Unexpected runtime bindings"):
            self.compile_request(request, {**self.functional_bindings(), "particle_source_path": self.binding_file('source.csv')})

    def test_functional_plan_rejects_unknown_empty_and_cross_structure_runtime(self):
        request = self.approved_functional_rf_request()
        for runtime in ("hexapole_no_acceleration_full_length", "octupole_no_acceleration_full_length"):
            with self.subTest(runtime=runtime), self.assertRaisesRegex(ValueError, "Runtime structural variant"):
                self.compile_request(request, {**self.functional_bindings(), "runtime_profile_id": runtime})
        for runtime, message in (("unknown_profile", "unknown runtime profile"), ("", "must name a registered")):
            with self.subTest(runtime=runtime), self.assertRaisesRegex(ValueError, message):
                self.compile_request(request, {**self.functional_bindings(), "runtime_profile_id": runtime})

    def test_runtime_structure_is_read_from_resolution_not_selector_spelling(self):
        from msplatform.workflows.rf_runtime_profiles import resolve_runtime_profile
        resolved = resolve_runtime_profile(REPO_ROOT, "rf_multipole_ion_optics",
                                           self.functional_bindings()["runtime_profile_id"])
        resolved["design_profile_resolution"]["profile"]["structural_variant_id"] = "octupole"
        with patch("msplatform.workflows.rf_runtime_profiles.resolve_runtime_profile", return_value=resolved):
            with self.assertRaisesRegex(ValueError, "Runtime structural variant"):
                self.compile_request(self.approved_functional_rf_request(), self.functional_bindings())

    def test_runtime_resolver_receives_only_declared_selectors(self):
        resolved = {"project_id": "rf_multipole_ion_optics", "structural_variant_id": "quadrupole",
                    "authorized_run_id": None}
        with patch("msplatform.workflows.rf_runtime_profiles.resolve_execution_binding",
                   return_value=resolved) as resolver:
            ready = self.compile_request(self.approved_functional_rf_request(), self.functional_bindings())
            self.assertEqual(ready["status"], "EXECUTION_READY")
            resolver.assert_called_once_with(REPO_ROOT, "rf_multipole_ion_optics",
                                            {"runtime_profile_id": self.functional_bindings()["runtime_profile_id"]}, request_path=ANY)

    def test_runtime_selection_is_checked_even_when_other_required_inputs_are_missing(self):
        with patch("msplatform.workflows.rf_runtime_profiles.resolve_execution_binding") as resolver:
            preview = self.compile_request(self.approved_functional_rf_request(), {"evidence_contract_path": "evidence.json"})
            self.assertEqual(preview["status"], "NEEDS_RUNTIME_INPUTS")
            resolver.assert_not_called()
        with self.assertRaisesRegex(ValueError, "unknown runtime profile"):
            self.compile_request(self.approved_functional_rf_request(), {"runtime_profile_id": "unknown_profile"})

    def test_profiles_without_runtime_resolver_do_not_load_project_code(self):
        with patch("tools.repository.compile_execution_plan.importlib.import_module") as loader:
            result = self.compile_request(self.ion_processor_request(), self.ion_processor_bindings())
            self.assertEqual(result["status"], "EXECUTION_READY")
            request = load_json(HERE / "fixtures" / "oa_tof_500da_r30000.example.json")
            self.assertEqual(self.compile_request(request)["status"], "NEEDS_IMPLEMENTATION")
            loader.assert_not_called()

    def test_runtime_binding_result_rejects_wrong_identity_types_and_extra_context(self):
        valid = {"project_id": "rf_multipole_ion_optics", "structural_variant_id": "quadrupole",
                 "authorized_run_id": None}
        invalid = [None, [], {}, {**valid, "run_id": self.run_id}, {**valid, "project_id": "other_project"}]
        for key in ("project_id", "structural_variant_id"):
            invalid.extend({**valid, key: value} for value in (None, 1, "", " quadrupole"))
        invalid.extend({**valid, "structural_variant_id": value} for value in ("unknown_structure", "hexapole"))
        invalid.extend({**valid, "authorized_run_id": value} for value in (True, 1, "", "forged", " " + self.run_id))
        for resolved in invalid:
            with self.subTest(resolved=resolved), patch(
                "msplatform.workflows.rf_runtime_profiles.resolve_execution_binding", return_value=resolved,
            ), self.assertRaises(ValueError):
                self.compile_request(self.approved_functional_rf_request(), self.functional_bindings())

    def test_runtime_binding_requires_the_declared_callable(self):
        with patch("msplatform.workflows.rf_runtime_profiles.resolve_execution_binding", None):
            with self.assertRaisesRegex(ValueError, "must define resolve_execution_binding"):
                self.compile_request(self.approved_functional_rf_request(), self.functional_bindings())

    def test_selected_runtime_tools_are_bounded_by_declared_capability(self):
        declared = load_json(REPO_ROOT / "src/msplatform/components/rf_multipole/config/execution_profiles.json")
        profile = next(item for item in declared["profiles"]
                       if item["profile_id"] == "hexapole_simion_transport_campaign_engineering")
        profile["tools"] = ["comsol", "matlab", "simion", "python"]
        real_load = load_json

        def selected_load(path):
            if Path(path) == REPO_ROOT / "src/msplatform/components/rf_multipole/config/execution_profiles.json":
                return declared
            return real_load(path)

        valid = dict(project_id="rf_multipole_ion_optics", structural_variant_id="hexapole",
                     authorized_run_id=self.run_id, tools=["simion", "python"])
        with patch("tools.repository.compile_execution_plan.load_json", side_effect=selected_load), patch(
            "msplatform.workflows.rf_runtime_profiles.resolve_execution_binding", return_value=valid,
        ):
            selected = self.compile_request(self.campaign_request("hexapole"), self.campaign_binding("hex"))
        self.assertEqual(selected["tools"], ["simion", "python"])
        self.assertEqual(len(selected["commands"]), 1)
        for tools in (None, [], "simion", ["simion", "simion"], [1], [""], ["unknown"]):
            with self.subTest(tools=tools), patch(
                "msplatform.workflows.rf_runtime_profiles.resolve_execution_binding",
                return_value={**valid, "tools": tools},
            ), self.assertRaisesRegex(ValueError, "Runtime tools"):
                self.compile_request(self.campaign_request("hexapole"), self.campaign_binding("hex"))

    def test_execution_contract_and_loaded_resolver_must_belong_to_the_selected_project(self):
        def changed_load(path):
            document = load_json(path)
            if Path(path).name == "execution_profiles.json":
                document["project_id"] = "other_project"
            return document

        with patch("tools.repository.compile_execution_plan.load_json", side_effect=changed_load):
            with self.assertRaisesRegex(ValueError, "contract project identity differs"):
                self.compile_request(self.approved_functional_rf_request(), self.functional_bindings())
        with patch("msplatform.workflows.rf_runtime_profiles.__file__", str(HERE / "machine_contracts.py")):
            with self.assertRaisesRegex(ValueError, "differs from its declared entrypoint"):
                self.compile_request(self.approved_functional_rf_request(), self.functional_bindings())

    def test_complete_bindings_cannot_leave_an_unexpanded_step_argument(self):
        def changed_load(path):
            document = load_json(path)
            if Path(path).name == "execution_profiles.json":
                document = copy.deepcopy(document)
                profile = next(p for p in document["profiles"] if p["profile_id"] == "quadrupole_transport_runtime_functional")
                profile["steps"][1]["arguments"].append("{unregistered_context}")
            return document
        with patch("tools.repository.compile_execution_plan.load_json", side_effect=changed_load):
            with self.assertRaisesRegex(ValueError, "Unresolved execution argument placeholder"):
                self.compile_request(self.approved_functional_rf_request(), self.functional_bindings())

    def mass_filter_request(self):
        request = self.approved_rf_request()
        request["target"]["function"] = "mass_filtering"
        request["target"]["mode"] = "quadrupole_mass_filter_reference"
        request["objectives"] = request["objectives"][:1]
        request["design_variables"] = []
        request["required_outputs"] = ["simulation_results", "simion_model", "validation_report"]
        return request

    def test_mass_filter_uses_its_generated_run_identity_without_overriding_plan(self):
        request = self.mass_filter_request()
        bindings = {"mass_filter_base_source_ion11_path": self.binding_file('source.ion'),
                    "simion_solver_numerics_contract_path": self.binding_file('numerics.json')}
        self.assertEqual(self.compile_request(request)["status"], "NEEDS_RUNTIME_INPUTS")
        result = self.compile_request(request, bindings)
        self.assertEqual(result["status"], "NEEDS_SOURCE_FREEZE")
        self.assertTrue(result["can_prepare_sources"])
        from tools.repository import compile_execution_plan as compiler
        with tempfile.TemporaryDirectory() as directory:
            frozen = Path(directory)/"compiled.json"
            frozen.write_text(json.dumps(result))
            with patch.object(sys, "argv", ["compiler", "--execute-plan", str(frozen)]), \
                 patch.object(compiler.subprocess, "run", side_effect=AssertionError("unfrozen source reached execution")), \
                 self.assertRaisesRegex(SystemExit, "source freeze required"):
                compiler.main()

        self.assertEqual(result["profile_id"], "quadrupole_mass_filter_simion_functional_reference")
        self.assertEqual([c["step_id"] for c in result["commands"]], ["simion_mass_response"])
        run = result["commands"][0]
        self.assertNotEqual(run["run_id"], self.run_id)
        self.assertEqual(run["argv"][run["argv"].index("-RunId") + 1], run["run_id"])
        with self.assertRaisesRegex(ValueError, "cannot override plan context"):
            self.compile_request(request, {**bindings, "run_id": "forged"})
        request["evidence_level"] = "candidate"
        with self.assertRaisesRegex(ValueError, "NEEDS_CLARIFICATION"):
            self.compile_request(request, bindings)

    def campaign_request(self, variant):
        request = self.approved_functional_rf_request()
        request["target"]["structural_variant_id"] = variant
        request["target"]["mode"] = variant + "_finite_3d_no_collision"
        request["objectives"] = request["objectives"][:1]
        request["design_variables"] = []
        return request

    def campaign_binding(self, short_variant):
        return {"campaign_path": str(REPO_ROOT / "src/msplatform/components/rf_multipole/config/campaigns/20260731__noacc_vs_segmented_h15_n100.json"),
                "experiment_id": short_variant + "_segmented_h15_n100"}

    def test_campaign_profiles_use_declared_run_identity_and_structure(self):
        for variant, short in (("hexapole", "hex"), ("octupole", "oct")):
            with self.subTest(variant=variant):
                request = self.campaign_request(variant)
                bindings = self.campaign_binding(short)
                document = load_json(Path(bindings["campaign_path"]))
                experiment = next(row for row in document["experiments"] if row["experiment_id"] == bindings["experiment_id"])
                result = self.compile_request(request, bindings)
                self.assertEqual(result["status"], "EXECUTION_READY")
                self.assertEqual(result["profile_id"], variant + "_simion_transport_campaign_engineering")
                self.assertEqual([c["step_id"] for c in result["commands"]], ["simion_campaign_run"])
                self.assertEqual(result["commands"][0]["run_id"], experiment["authorized_run_id"])
                for command in result["commands"]:
                    self.assertFalse(any("{" in argument for argument in command["argv"]))
                request["evidence_level"] = "candidate"
                with self.assertRaisesRegex(ValueError, "NEEDS_CLARIFICATION"):
                    self.compile_request(request, bindings)

    def test_current_campaign_previews_with_the_project_relative_runner(self):
        project_root = resolve_project_root("rf_multipole_ion_optics")
        path = project_root / "config/campaigns/20260731__noacc_vs_segmented_h15_n100.json"
        campaign = load_json(path)
        self.assertEqual(campaign["schema_version"], 7)
        experiment = next(row for row in campaign["experiments"] if row["experiment_id"] == "hex_segmented_h15_n100")
        self.assertIs(experiment["resource_authorization"]["authorized"], False)
        profiles = load_json(project_root / "config/execution_profiles.json")["profiles"]
        profile_id = "hexapole_simion_transport_campaign_engineering"
        profile = next(item for item in profiles if item["profile_id"] == profile_id)
        step = next(item for item in profile["steps"] if item["kind"] == "run")
        self.assertEqual(step["entrypoint"], "src/msplatform/workflows/resources/run_simion_transport_campaign.ps1")

        result = self.compile_request(
            self.campaign_request("hexapole"),
            {"campaign_path": str(path), "experiment_id": experiment["experiment_id"]},
        )
        self.assertEqual(result["status"], "EXECUTION_READY")
        self.assertEqual(result["profile_id"], profile_id)
        run = next(command for command in result["commands"] if command["step_id"] == "simion_campaign_run")
        self.assertEqual(run["run_id"], experiment["authorized_run_id"])
        self.assertEqual(
            Path(run["argv"][run["argv"].index("-File") + 1]).resolve(),
            (REPO_ROOT / "src/msplatform/workflows/resources/run_simion_transport_campaign.ps1").resolve(),
        )
        self.assertIn(experiment["experiment_id"], run["argv"])

    def test_cli_compiles_campaign_bindings_to_the_registered_run_identity(self):
        bindings = self.campaign_binding("hex")
        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "request.json"
            plan_path = Path(directory) / "plan.json"
            request_path.write_text(json.dumps(self.campaign_request("hexapole")), encoding="utf-8")
            plan, _ = build_plan(request_path, self.registry, self.run_id)
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            command = [sys.executable, "-m", "tools.repository.compile_execution_plan", str(plan_path),
                       "--registry", str(self.registry)]
            for key, value in bindings.items():
                command.extend(["--bind", f"{key}={value}"])
            completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True,
                                       encoding="utf-8", timeout=60, check=False)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result = json.loads(completed.stdout)
        campaign = load_json(Path(bindings["campaign_path"]))
        experiment = next(row for row in campaign["experiments"] if row["experiment_id"] == bindings["experiment_id"])
        self.assertEqual(result["status"], "EXECUTION_READY")
        self.assertEqual(result["commands"][0]["run_id"], experiment["authorized_run_id"])
        self.assertIn(bindings["experiment_id"], result["commands"][0]["argv"])

    def test_campaign_missing_binding_is_a_preview_blocker_not_an_invalid_run_id(self):
        request = self.campaign_request("hexapole")
        bindings = self.campaign_binding("hex")
        for missing in ({}, {"campaign_path": bindings["campaign_path"]}, {"experiment_id": bindings["experiment_id"]}):
            with self.subTest(bindings=missing):
                result = self.compile_request(request, missing)
                self.assertEqual(result["status"], "NEEDS_RUNTIME_INPUTS")
                self.assertFalse(result["safe_to_execute"])
                self.assertIsNone(result["commands"][0]["run_id"])

    def test_campaign_rejects_unknown_cross_structure_and_authorized_id_override(self):
        request = self.campaign_request("hexapole")
        with self.assertRaisesRegex(ValueError, "unknown campaign experiment"):
            self.compile_request(request, {**self.campaign_binding("hex"), "experiment_id": "unknown_experiment"})
        with self.assertRaisesRegex(ValueError, "Runtime structural variant"):
            self.compile_request(request, self.campaign_binding("oct"))
        with self.assertRaisesRegex(ValueError, "cannot override plan context"):
            self.compile_request(request, {**self.campaign_binding("hex"), "authorized_run_id": "forged"})

    def test_example_rf_request_exposes_implementation_gaps(self):
        request = load_json(HERE / "fixtures" / "rf_quadrupole_transport.example.json")
        result = self.compile_request(request)
        self.assertEqual(result["status"], "NEEDS_IMPLEMENTATION")
        self.assertTrue(any("operating points" in item for item in result["blockers"]))
        self.assertTrue(any("design variables" in item for item in result["blockers"]))
        self.assertNotIn("requested_qualification", result)

    def test_oa_design_request_does_not_masquerade_as_fixed_validation(self):
        request = load_json(HERE / "fixtures" / "oa_tof_500da_r30000.example.json")
        result = self.compile_request(request)
        self.assertEqual(result["status"], "NEEDS_IMPLEMENTATION")
        self.assertEqual(result["blockers"], ["No execution profile for single_reflection_mass_analysis/mass_spectrum"])
        self.assertFalse(result["safe_to_execute"])
        self.assertEqual(result["commands"], [])

    def test_oa_validated_structural_candidate_requires_explicit_seed(self):
        request = load_json(HERE / "fixtures" / "oa_tof_500da_r30000.example.json")
        request["status"] = "approved"
        request["approval"] = {"approved_by": "owner", "approved_on": "2026-07-20"}
        request["target"]["mode"] = "design_candidate"
        request["operating_points"] = [{"mass": {"value": 524, "unit": "Da"}, "charge_state": 1}]
        request["objectives"] = [
            {"metric": "transmission_fraction", "operator": "maximize", "value": None,
             "unit": "1", "tolerance": None}
        ]
        request["constraints"] = []
        request["design_variables"] = []
        result = self.compile_request(request)
        self.assertEqual(result["status"], "NEEDS_RUNTIME_INPUTS")
        missing_proposal = self.compile_request(request, {"particle_source_seed": "20260720"})
        self.assertEqual(missing_proposal["status"], "NEEDS_RUNTIME_INPUTS")
        self.assertIn("candidate_proposal.json", " ".join(missing_proposal["blockers"]))
        ready = self.compile_request(request, {"particle_source_seed": "20260720"}, proposal=True)
        self.assertEqual(ready["status"], "EXECUTION_READY")
        self.assertEqual(ready["profile_id"], "validated_structural_candidate")
        self.assertEqual(
            ready["commands"][0]["argv"][1:3],
            ["-m", "msplatform.workflows.oa_candidate.run_candidate"],
        )
        argv = ready["commands"][0]["argv"]
        self.assertIn("--request", argv)
        self.assertIn("--run-id", argv)
        self.assertIn(self.run_id, argv)
        self.assertIn("--particle-source-seed", argv)
        self.assertIn("20260720", argv)

        request["design_variables"] = ["reflectron_midgrid_voltage"]
        variable_ready = self.compile_request(
            request, {"particle_source_seed": "20260720"}, proposal=True
        )
        self.assertEqual(variable_ready["status"], "EXECUTION_READY")
        self.assertEqual(variable_ready["profile_id"], "validated_structural_candidate")

        request["design_variables"] = ["flight_length"]
        unsupported = self.compile_request(
            request, {"particle_source_seed": "20260720"}, proposal=True
        )
        self.assertEqual(unsupported["status"], "NEEDS_IMPLEMENTATION")

    def test_runtime_bindings_reject_unknown_and_plan_owned_context(self):
        request = load_json(HERE / "fixtures" / "oa_tof_500da_r30000.example.json")
        request["status"] = "approved"
        request["approval"] = {"approved_by": "owner", "approved_on": "2026-07-20"}
        request["target"]["mode"] = "design_candidate"
        request["operating_points"] = [
            {"mass": {"value": 524, "unit": "Da"}, "charge_state": 1}
        ]
        request["objectives"] = [
            {
                "metric": "transmission_fraction",
                "operator": "maximize",
                "value": None,
                "unit": "1",
                "tolerance": None,
            }
        ]
        request["constraints"] = []
        request["design_variables"] = []
        with self.assertRaisesRegex(ValueError, "Unexpected runtime bindings"):
            self.compile_request(
                request,
                {
                    "particle_source_seed": "20260720",
                    "unused_binding": "forbidden",
                },
            )
        for protected in ("request_path", "run_id"):
            with self.subTest(protected=protected), self.assertRaisesRegex(
                ValueError, "cannot override plan context"
            ):
                self.compile_request(
                    request,
                    {
                        "particle_source_seed": "20260720",
                        protected: "C:/forged",
                    },
                )

    def test_interface_profile_requires_explicit_runtime_bindings(self):
        request = self.approved_rf_request()
        request["target"]["mode"] = "quadrupole_transport_interface_readiness"
        result = self.compile_request(request)
        self.assertEqual(result["status"], "NEEDS_RUNTIME_INPUTS")
        limits = Path(self.binding_file('comsol_limits.json'))
        limits.write_text(json.dumps(dict(wall_clock_seconds=17, transient_run_directory_bytes=8192,
                                         process_tree_working_set_bytes=4096, minimum_system_available_memory_bytes=1024)), encoding="utf-8")
        bindings = {
            "comsol_particle_source_path": self.binding_file('source.csv'),
            "simion_particle_source_path": self.binding_file('source_canonical.csv'),
            "particle_bundle_metadata_path": self.binding_file('bundle.json'),
            "particle_source_family_path": self.binding_file('source_family.json'),
            "particle_distribution_path": self.binding_file('distribution.json'),
            "simion_solver_numerics_contract_path": self.binding_file('numerics.json'),
            "operating_point_id": "official_100amu_2eV",
            "comsol_execution_limits_path": self.binding_file('comsol_limits.json'),
            }
        missing_limits = dict(bindings)
        del missing_limits["comsol_execution_limits_path"]
        missing = self.compile_request(request, missing_limits)
        self.assertEqual(missing["status"], "NEEDS_RUNTIME_INPUTS")
        self.assertIn("comsol_execution_limits_path", ", ".join(missing["blockers"]))
        ready = self.compile_request(request, bindings)
        self.assertIn("comsol_execution_limits_path", ", ".join(result["blockers"]))
        self.assertEqual(ready["status"], "NEEDS_SOURCE_FREEZE")
        self.assertTrue(ready["can_prepare_sources"])
        self.assertIn(self.binding_file('source.csv'), ready["commands"][0]["argv"])
        argv = ready["commands"][0]["argv"]
        self.assertEqual(argv[argv.index("-LimitsPath")+1], self.binding_file('comsol_limits.json'))
        self.assertEqual(len(ready["commands"]), 3)
        for command in ready["commands"]:
            self.assertFalse(any("{" in argument for argument in command["argv"]))

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_powershell_command_consumes_the_actual_compiler_interpreter(self):
        compiled = self.compile_request(self.approved_functional_rf_request(), self.functional_bindings())
        interpreter = str(Path(sys.executable).resolve())
        command = next(item for item in compiled["commands"] if "-PythonExe" in item["arguments"])
        arguments = command["arguments"]
        self.assertEqual(arguments[arguments.index("-PythonExe") + 1], interpreter)
        self.assertEqual(compiled["python_executable"], interpreter)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness = root / "capture.ps1"
            harness.write_text("param([string]$PythonExe)\n"
                               "& $PythonExe -c \"import sys; print('ACTUAL_INTERPRETER='+sys.executable)\"\n"
                               "exit $LASTEXITCODE\n", encoding="utf-8")
            actual = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(harness),
                                     *arguments], cwd=root, capture_output=True, text=True,
                                    encoding="utf-8", timeout=30)
            self.assertEqual(actual.returncode, 0, actual.stdout + actual.stderr)
            self.assertIn("ACTUAL_INTERPRETER=" + interpreter, actual.stdout)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_python_owner_uses_compiler_interpreter_without_repo_venv_and_propagates_exit(self):
        import os
        from msplatform.execution.retention import file_record
        interpreter = str(Path(sys.executable).resolve())
        with tempfile.TemporaryDirectory() as directory:
            compile_root = Path(directory)
            request_path = compile_root / "request.json"
            request_path.write_text(json.dumps(self.ion_processor_request()), encoding="utf-8")
            planned, _ = build_plan(request_path, self.registry, self.run_id)
            planned_path = compile_root / "design_plan.json"
            planned_path.write_text(json.dumps(planned), encoding="utf-8")
            saved_path = compile_root / "compiled.json"
            compile_env = os.environ.copy()
            compile_env.pop("PYTHONPATH", None)
            compile_env["SIMULATION_PYTHON_EXE"] = str(compile_root / "poison/python.exe")
            compile_env["PYTHONPATH"] = os.pathsep.join((str(REPO_ROOT / "src"), str(REPO_ROOT)))
            preview = subprocess.run([interpreter, "-m", "tools.repository.compile_execution_plan",
                                      str(planned_path), "--output", str(saved_path)], cwd=REPO_ROOT,
                                     env=compile_env, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
            compiled = json.loads(saved_path.read_text(encoding="utf-8"))
        self.assertEqual(compiled["python_executable"], interpreter)
        for mode in ("success", "failure", "missing", "unavailable"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                repo = root / "repository"
                project = repo / "src/msplatform/components/fixture"
                (project / "config").mkdir(parents=True)
                (repo / "config").mkdir()
                (repo / "config/project_registry.json").write_text(json.dumps(dict(projects=[dict(
                    project_id="fixture", contracts=dict(execution="config/execution_profiles.json"))])), encoding="utf-8")
                entry = project / "owner.py"
                entry.write_text("import json,os,sys\nfrom pathlib import Path\n"
                                 "Path(__file__).with_name('actual.json').write_text(json.dumps(dict("
                                 "executable=sys.executable,cwd=os.getcwd())),encoding='utf-8')\n"
                                 "print('PYTHON_OWNER_ACTUAL_EXIT='+sys.argv[1],flush=True)\n"
                                 "sys.exit(int(sys.argv[1]))\n", encoding="utf-8")
                exit_code = "7" if mode == "failure" else "0"
                contract = project / "config/execution_profiles.json"
                contract.write_text(json.dumps(dict(profiles=[dict(profile_id="fixture", steps=[dict(
                    step_id="run", shell="python", entrypoint="owner.py", arguments=[exit_code])])])), encoding="utf-8")
                plan = dict(schema_version=2, role="execution_dry_run", status="EXECUTION_READY", safe_to_execute=True,
                            python_executable=compiled["python_executable"], project_id="fixture", profile_id="fixture",
                            execution_contract=file_record(contract), planning_sources=[], binding_authorities=[],
                            binding_sources=[], resolved_inputs=[], resolved_runtime=None,
                            commands=[dict(step_id="run", shell="python", entrypoint=str(entry), arguments=[exit_code])])
                if mode == "missing":
                    del plan["python_executable"]
                if mode == "unavailable":
                    plan["python_executable"] = str(root / "unavailable/python.exe")
                plan_path = root / "compiled.json"
                plan_path.write_text(json.dumps(plan), encoding="utf-8")
                harness = root / "execute.ps1"
                harness.write_text("param($Helper,$Plan,$Repository)\n$ErrorActionPreference='Stop'\n"
                                   ". $Helper\nInvoke-CompiledExecutionPlan -PlanPath $Plan -RepoRoot $Repository\n", encoding="utf-8")
                env = os.environ.copy()
                env["SIMULATION_PYTHON_EXE"] = str(root / "poison/python.exe")
                env.pop("PYTHONPATH", None)
                result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(harness),
                                         str(REPO_ROOT / "src/msplatform/execution/resources/run_artifact_support.ps1"),
                                         str(plan_path), str(repo)], cwd=root, env=env, capture_output=True,
                                        text=True, encoding="utf-8", errors="replace", timeout=30)
                self.assertFalse((repo / ".venv").exists())
                actual_path = project / "actual.json"
                if mode in ("missing", "unavailable"):
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(actual_path.exists())
                    self.assertIn("recompile with the intended Python executable", result.stdout + result.stderr)
                else:
                    self.assertTrue(actual_path.exists(), result.stdout + result.stderr)
                    actual = json.loads(actual_path.read_text(encoding="utf-8"))
                    self.assertEqual(Path(actual["executable"]).resolve(), Path(interpreter))
                    self.assertEqual(Path(actual["cwd"]).resolve(), repo.resolve())
                    self.assertIn("PYTHON_OWNER_ACTUAL_EXIT=" + exit_code, result.stdout)
                    if mode == "failure":
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("Compiled owner step failed: run (exit 7)", result.stdout + result.stderr)
                    else:
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        self.assertIn("COMPILED_EXECUTION=COMPLETED", result.stdout)



if __name__ == "__main__":
    unittest.main()
