import copy
import json
import subprocess
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, patch


from common.contracts.compile_execution_plan import compile_execution
from common.contracts.machine_contracts import REPO_ROOT, load_json
from common.contracts.plan_design_request import build_plan


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

    def compile_request(self, request, bindings=None, *, proposal=False, **options):
        with tempfile.TemporaryDirectory() as root:
            request_path = Path(root) / "request.json"
            plan_path = Path(root) / "design_plan.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            if proposal:
                from common.contracts.machine_contracts import sha256
                (Path(root)/"candidate_proposal.json").write_text(json.dumps(dict(schema_version=1,
                    role="design_candidate_proposal", candidate_id="fixture_candidate",
                    project_id="single_reflection_oa_tof_mass_analyzer", request=dict(path=str(request_path),
                    sha256=sha256(request_path)), values=[])), encoding="utf-8")
            plan, _ = build_plan(request_path, self.registry, self.run_id)
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            return compile_execution(plan_path, self.registry, bindings, **options)

    def approved_rf_request(self):
        request = load_json(HERE / "examples" / "rf_quadrupole_transport.example.json")
        request["status"] = "approved"
        request["approval"] = {"approved_by": "owner", "approved_on": "2026-07-20"}
        request["operating_points"] = [{"mass": {"value": 100, "unit": "Da"}, "charge_state": 1}]
        request["design_variables"] = ["rf_amplitude", "rf_frequency"]
        return request

    def approved_functional_rf_request(self):
        request = self.approved_rf_request()
        request["evidence_level"] = "plan"
        return request

    def functional_bindings(self):
        return {
            "runtime_profile_id": "quadrupole_no_acceleration_full_length",
            "evidence_contract_path": self.binding_file('evidence.json'),
        }

    def ion_processor_request(self):
        request = self.approved_functional_rf_request()
        request["target"] = {
            "family_id": "rf_ion_accumulation_and_pulsed_extraction",
            "preferred_project_id": "dual_pressure_rectilinear_ion_processor",
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
        from projects.orthogonal_accelerator.simion import two_zone_candidate
        source = REPO_ROOT/"projects/parallel_mirror_dual_stripe_mr_tof/config"
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as guards:
            root = Path(directory)
            release = root/"release.json"
            release.write_bytes((source/"accelerator_component_release_n100.json").read_bytes())
            condition = root/"condition.json"
            condition.write_text(json.dumps(dict(schema_version=1, role="mrtof_native_candidate_campaign_condition",
                                                 K=4.0, accelerator_y=-55.0)), encoding="utf-8")
            small = root/"definition.json"
            small.write_text("{}", encoding="utf-8")
            context = root/"context.json"
            body = dict(schema_version=1, role="mrtof_native_candidate_condition_context")
            for key in ("contract_path", "fixed_grid_mirror_run_manifest", "geometry_review_run_path",
                        "native_corridor_bank_run_path", "native_system_runtime_bundle_path", "source_definition_path"):
                body[key] = str(small)
            body.update(oa_base_release_spec_path=str(release),
                        oa_request_path=str(source/"accelerator_component_request_n100.json"))
            context.write_text(json.dumps(body), encoding="utf-8")
            guards.enter_context(patch.object(two_zone_candidate, "compile_closed_two_zone_accelerator",
                                               side_effect=AssertionError("capability binding rendered GEM")))
            for owner, family, function, mode, metric, variant, bindings in (
                ("orthogonal_accelerator", "orthogonal_pulsed_accelerators", "orthogonal_acceleration",
                 "component_focus", "first_time_focus_distance", "two_zone",
                 dict(component_request_path=str(source/"accelerator_component_request_n100.json"), release_spec_path=str(release))),
                ("parallel_mirror_dual_stripe_mr_tof", "tof_mass_analyzers", "mass_analysis",
                 "native_condition", "detection_fraction", None,
                 dict(condition_path=str(condition), context_path=str(context), composition_plan_path=str(small))),
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
                    protected = {row["path"] for row in ready["binding_authorities"]}
                    self.assertIn(str(release.resolve()), protected)
                    if owner == "orthogonal_accelerator":
                        self.assertIn(str((REPO_ROOT/"projects"/owner/"config/component_contract.json").resolve()), protected)
                    else:
                        self.assertIn(str(small.resolve()), protected)
                    request["operating_points"][0]["mass"]["value"] = 100
                    refused = self.compile_request(request, bindings)
                    self.assertEqual(refused["status"], "NEEDS_RUNTIME_INPUTS")
                    self.assertIn("actual bound release species", " ".join(refused["blockers"]))
                    self.assertFalse(refused["safe_to_execute"])
                    if owner == "parallel_mirror_dual_stripe_mr_tof":
                        body["native_corridor_bank_run_path"] = str(root/"missing-bank")
                        context.write_text(json.dumps(body), encoding="utf-8")
                        request["operating_points"][0]["mass"]["value"] = 524
                        needs_prepare = self.compile_request(request, bindings)
                        self.assertEqual(needs_prepare["status"], "NEEDS_SCIENTIFIC_PREPARATION")
                        self.assertIn("native_corridor_bank_run_path", " ".join(needs_prepare["blockers"]))
                        self.assertFalse(needs_prepare["safe_to_execute"])

    def test_legacy_qualification_intent_is_preserved_without_inferring_actions_from_plan_static(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path = root/"request.json"
            request_path.write_text(json.dumps(self.approved_functional_rf_request()))
            plan, _ = build_plan(request_path, self.registry, self.run_id)
            plan_path = root/"plan.json"
            actions = []
            for legacy in ("plan", "static", "candidate", "formal"):
                plan["requested_evidence_level"] = legacy
                plan_path.write_text(json.dumps(plan))
                if legacy in ("candidate", "formal"):
                    with patch("projects.rf_multipole_ion_optics.runtime.runtime_profile.resolve_execution_binding", side_effect=AssertionError("unsupported qualification resolved scientific inputs")):
                        result = compile_execution(plan_path, self.registry, self.functional_bindings())
                else:
                    result = compile_execution(plan_path, self.registry, self.functional_bindings())
                if legacy in ("candidate", "formal"):
                    self.assertEqual(result["status"], "NEEDS_IMPLEMENTATION")
                    self.assertEqual(result["requested_qualification"], legacy)
                    self.assertIn("Qualification is not supported: "+legacy, result["blockers"])
                    self.assertFalse(result["safe_to_execute"])
                else:
                    self.assertEqual(result["status"], "EXECUTION_READY")
                    actions.append((result["requested_action"], result["commands"]))
                self.assertEqual(result["execution_status"], "not_started")
                self.assertEqual(result["science_status"], "not_evaluated")
            self.assertEqual(actions[0], actions[1])
            explicit = compile_execution(plan_path, self.registry, self.functional_bindings(),
                                         purpose="finite_transport", qualification="none")
            self.assertEqual(explicit["status"], "EXECUTION_READY")
            wrong = compile_execution(plan_path, self.registry, self.functional_bindings(),
                                      purpose="model_tree_build", qualification="none")
            self.assertEqual(wrong["status"], "NEEDS_IMPLEMENTATION")

    def test_capability_view_includes_components_and_assemblies_without_a_pseudo_project(self):
        from common.contracts.build_project_registry import query_capabilities
        view = query_capabilities(load_json(self.registry))
        projects = {row["owner_id"]: row for row in view if row["owner_kind"] == "project"}
        self.assertEqual(len(projects), 8)
        self.assertEqual(projects["apertured_tube_electron_impact_ion_source"]["execution_support"], "no_registered_physical_entry")
        self.assertEqual(projects["orthogonal_accelerator"]["profiles"][0]["required_bindings"], ["component_request_path", "release_spec_path"])
        self.assertEqual(projects["parallel_mirror_dual_stripe_mr_tof"]["profiles"][0]["profile_id"], "native_condition")
        assemblies = [row for row in view if row["owner_kind"] == "integration"]
        self.assertEqual([row["owner_id"] for row in assemblies], ["instrument_assembly"])
        self.assertNotIn("instrument_assembly", projects)
        self.assertEqual({row["workflow_id"] for row in assemblies[0]["profiles"]},
                         {"single_reflection_flight", "prepared_joint_flight", "ip_mr_chain", "oa_mr_flight"})
        with self.assertRaisesRegex(ValueError, "Unknown capability owner"):
            query_capabilities(load_json(self.registry), owner="missing")

    def test_integration_plans_freeze_real_entry_arguments_and_report_each_missing_input(self):
        from common.contracts.compile_execution_plan import compile_integration_execution
        from common.contracts.build_project_registry import query_capabilities
        rows = query_capabilities(load_json(self.registry), owner="instrument_assembly")[0]["profiles"]
        for row in rows:
            with self.subTest(workflow=row["workflow_id"]):
                missing = compile_integration_execution("instrument_assembly", row["workflow_id"], self.run_id, {})
                self.assertEqual(missing["status"], "NEEDS_RUNTIME_INPUTS")
                self.assertEqual(len(missing["blockers"]), len(row["required_bindings"]))
                bindings = {}
                for key, kind in row["binding_types"].items():
                    if kind == "directory":
                        directory = Path(self.binding_directory.name)/key
                        directory.mkdir(exist_ok=True)
                        (directory/"run_manifest.json").write_text("{}")
                        bindings[key] = str(directory)
                    else:
                        bindings[key] = "123.5" if kind == "number" else self.binding_file(key+".json")
                result = compile_integration_execution("instrument_assembly", row["workflow_id"], self.run_id, bindings)
                self.assertEqual(result["status"], "EXECUTION_READY")
                self.assertEqual(result["owner_kind"], "integration")
                self.assertNotIn("project_id", result)
                self.assertEqual(Path(result["commands"][0]["entrypoint"]), REPO_ROOT/row["entrypoint"])
                self.assertFalse(any("{" in value for value in result["commands"][0]["arguments"]))
        with self.assertRaisesRegex(ValueError, "Unknown integration workflow"):
            compile_integration_execution("instrument_assembly", "arbitrary_script", self.run_id, {})

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_fixed_input_consumers_freeze_compiled_values_instead_of_current_defaults(self):
        cases = (("dual_cone_tandem_quadrupole_ion_interface", "workflows/gas_assisted_transport/run_axisymmetric_gas_flow.ps1", "sourceFiles"),
                 ("transverse_helical_filament_wehnelt_electron_gun", "run_build_only_smoke.ps1", "projectFrozenFiles"))
        for project, relative, variable in cases:
            with self.subTest(project=project), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                profile = load_json(REPO_ROOT/"projects"/project/"config/execution_profiles.json")["profiles"][0]
                private = root/"compiled"
                records = []
                for name, path in profile["fixed_inputs"].items():
                    source = private/path
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_text('{"value":2}')
                    records.append(dict(name=name, relative_path=path))
                bundle = root/"resolved.json"
                bundle.write_text(json.dumps(dict(role="compiled_execution_inputs", project_id=project, root=str(private), files=records)))
                harness = root/"freeze.ps1"
                harness.write_text(r"""param($Repo,$Entry,$Project,$Root,$Bundle,$Variable)
Set-StrictMode -Version Latest;$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$ast=[Management.Automation.Language.Parser]::ParseFile($Entry,[ref]$null,[ref]$null)
$assignment=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left-is[Management.Automation.Language.VariableExpressionAst]-and$n.Left.VariablePath.UserPath-eq$Variable},$true)
$selection=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and$n.Clauses[0].Item1.Extent.Text-eq'$ResolvedInputsPath'},$true)
$loop=$ast.Find({param($n)$n-is[Management.Automation.Language.ForEachStatementAst]-and$n.Condition.Extent.Text-in@('$sourceFiles.Keys','$projectFrozenFiles.GetEnumerator()')},$true)
if($null-eq$assignment-or$null-eq$selection-or$null-eq$loop){throw 'real prepare selection or freeze boundary missing'}
$projectRoot=Join-Path $Root 'current';$codeRoot=Join-Path $Root 'frozen';$projectId=$Project
$package=@{input_dir=(Join-Path $Root 'inputs')};$frozen=[ordered]@{};$frozenInputs=[ordered]@{}
$ResolvedInputsPath=$Bundle;$compiledInputs=$null
Invoke-Expression $assignment.Extent.Text
$files=Get-Variable -Name $Variable -ValueOnly
foreach($path in $files.Values){$file=Join-Path $projectRoot $path;New-Item -ItemType Directory -Force -Path (Split-Path -Parent $file)|Out-Null;Set-Content $file '{"value":1}'}
Invoke-Expression $selection.Extent.Text
Invoke-Expression $loop.Extent.Text
$actual=if($Variable-eq'sourceFiles'){$frozen}else{$frozenInputs}
foreach($record in $compiledInputs.files){
 $value=Get-Content -LiteralPath ([string]$actual[$record.name]) -Raw|ConvertFrom-Json
 if($value.value-ne2){throw "consumer reread its current default: $($record.name)"}
}
'COMPILED_CONSUMER_FREEZE=PASS'
""", encoding="utf-8")
                result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(harness), str(REPO_ROOT),
                    str(REPO_ROOT/"projects"/project/relative), project, str(root), str(bundle), variable],
                    cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                self.assertIn("COMPILED_CONSUMER_FREEZE=PASS", result.stdout)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_integration_execution_reaches_its_real_declared_parameters(self):
        from common.contracts.compile_execution_plan import compile_integration_execution
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            integration = root/"integrations"
            entry = integration/"workflows/fixture/run.ps1"
            entry.parent.mkdir(parents=True)
            request = root/"request.json"
            request.write_text('{"source":"frozen"}')
            entry.write_text(r"""param($Request,[double]$PrismVoltage,$RunId)
$ErrorActionPreference='Stop'
$input=Get-Content $Request -Raw|ConvertFrom-Json
@{source=$input.source;voltage=$PrismVoltage;run_id=$RunId}|ConvertTo-Json|Set-Content (Join-Path $PSScriptRoot 'actual.json')
""", encoding="utf-8")
            workflow = dict(workflow_id="fixture", entrypoint="integrations/workflows/fixture/run.ps1",
                required_bindings=["request", "voltage"], binding_types=dict(request="file", voltage="number"),
                arguments=["-Request", "{request}", "-PrismVoltage", "{voltage}", "-RunId", "{run_id}"],
                outputs=["receipt"], simulation_paths=["continuous_assembly"], recipes=[], limitations=[],
                purpose="assembly_propagation", action="run", tools=["python"], model="inert fixture")
            (integration/"registry.json").write_text(json.dumps(dict(schema_version=1, role="integration_registry",
                integrations=[dict(integration_id="instrument_assembly", root="integrations", workflows=[workflow])])))
            with patch("common.contracts.compile_execution_plan.REPO_ROOT", root):
                result = compile_integration_execution("instrument_assembly", "fixture", self.run_id,
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
                str(REPO_ROOT/"common/contracts/run_artifact_support.ps1"), str(plan), str(root)],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
            actual = json.loads((entry.parent/"actual.json").read_text())
            self.assertEqual(actual, dict(source="frozen", voltage=-123.5, run_id=self.run_id))

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_compiled_executor_uses_frozen_definition_and_rejects_drift_or_other_entrypoint(self):
        from common.contracts.write_run_manifest import file_record
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root/"projects/fixture"
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
                steps=[dict(step_id="run", entrypoint="run.ps1", shell="powershell", arguments=["-ResolvedInputsPath", "{resolved_inputs_path}"])])])))
            plan = dict(role="execution_dry_run", status="EXECUTION_READY", safe_to_execute=True,
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
            for mode in ("success", "drift", "content", "entrypoint"):
                with self.subTest(mode=mode):
                    actual = copy.deepcopy(plan)
                    original.write_text('{"value":3}' if mode == "drift" else '{"value":2}')
                    if mode == "content": actual["resolved_inputs"][0]["content"] = '{"value":9}'
                    if mode == "entrypoint": actual["commands"][0]["entrypoint"] = str(root/"other.ps1")
                    (project/"actual.json").unlink(missing_ok=True)
                    plan_path.write_text(json.dumps(actual))
                    completed = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(harness),
                        str(REPO_ROOT/"common/contracts/run_artifact_support.ps1"), str(plan_path), str(root)],
                        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
                    if mode == "success":
                        self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
                        self.assertEqual(json.loads((project/"actual.json").read_text())["value"], 2)
                    else:
                        self.assertNotEqual(completed.returncode, 0)
                        self.assertFalse((project/"actual.json").exists())
                    original.write_text('{"value":2}')  # release is observable after every branch

    def test_ordinary_profiles_compile_only_declared_scientific_steps_and_empty_ei_is_unavailable(self):
        from common.contracts.machine_contracts import sha256, validate_schema
        projects = ("apertured_tube_electron_impact_ion_source", "dual_cone_tandem_quadrupole_ion_interface",
                    "dual_pressure_rectilinear_ion_processor", "rf_multipole_ion_optics",
                    "single_reflection_oa_tof_mass_analyzer", "transverse_helical_filament_wehnelt_electron_gun")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root/"request.json"
            request.write_text("{}")
            plan_path = root/"plan.json"
            count = 0
            for project in projects:
                document = load_json(REPO_ROOT/"projects"/project/"config/execution_profiles.json")
                validate_schema(document, "execution_profiles.schema.json")
                profiles = document["profiles"]
                if not profiles:
                    self.assertEqual(project, "apertured_tube_electron_impact_ion_source")
                for profile in profiles or [dict(capability_id="electron_impact_ionization_feasibility", mode="build_only_smoke")]:
                    plan = dict(role="solver_neutral_design_plan", request_status="approved", project_id=project, capability_id=profile["capability_id"],
                        mode=profile["mode"], run_id=self.run_id, requested_evidence_level="plan", operating_points=[],
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
            self.assertEqual(count, 12)

    def test_ion_processor_existing_functional_runner_is_discoverable_without_budget_bindings(self):
        result = self.compile_request(self.ion_processor_request())
        self.assertEqual(result["status"], "EXECUTION_READY")
        self.assertEqual(result["profile_id"], "native_functional")
        self.assertEqual([item["step_id"] for item in result["commands"]], ["native_run"])
        command = result["commands"][0]
        self.assertTrue(command["argv"][4].replace("\\", "/").endswith("/simion/run_functional.ps1"))
        self.assertEqual(command["argv"][command["argv"].index("-RunId") + 1], command["run_id"])
        self.assertEqual(command["argv"][command["argv"].index("-SourceProfile")+1], "functional")
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
            with self.assertRaisesRegex(ValueError, "NEEDS_PROJECT_COMPLETION"):
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

    def test_functional_profile_does_not_satisfy_candidate_scientific_request(self):
        request = self.approved_rf_request()
        self.assertEqual(request["evidence_level"], "candidate")
        result = self.compile_request(request, self.functional_bindings(), qualification="candidate")
        self.assertEqual(result["status"], "NEEDS_IMPLEMENTATION")
        self.assertFalse(result["safe_to_execute"])
        self.assertIn("Qualification is not supported: candidate", result["blockers"])

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
        from projects.rf_multipole_ion_optics.runtime.runtime_profile import resolve_runtime_profile
        resolved = resolve_runtime_profile(REPO_ROOT, "rf_multipole_ion_optics",
                                           self.functional_bindings()["runtime_profile_id"])
        resolved["design_profile_resolution"]["profile"]["structural_variant_id"] = "octupole"
        with patch("projects.rf_multipole_ion_optics.runtime.runtime_profile.resolve_runtime_profile", return_value=resolved):
            with self.assertRaisesRegex(ValueError, "Runtime structural variant"):
                self.compile_request(self.approved_functional_rf_request(), self.functional_bindings())

    def test_runtime_resolver_receives_only_declared_selectors(self):
        resolved = {"project_id": "rf_multipole_ion_optics", "structural_variant_id": "quadrupole",
                    "authorized_run_id": None}
        with patch("projects.rf_multipole_ion_optics.runtime.runtime_profile.resolve_execution_binding",
                   return_value=resolved) as resolver:
            ready = self.compile_request(self.approved_functional_rf_request(), self.functional_bindings())
            self.assertEqual(ready["status"], "EXECUTION_READY")
            resolver.assert_called_once_with(REPO_ROOT, "rf_multipole_ion_optics",
                                            {"runtime_profile_id": self.functional_bindings()["runtime_profile_id"]}, request_path=ANY)

    def test_runtime_selection_is_checked_even_when_other_required_inputs_are_missing(self):
        with patch("projects.rf_multipole_ion_optics.runtime.runtime_profile.resolve_execution_binding") as resolver:
            preview = self.compile_request(self.approved_functional_rf_request(), {"evidence_contract_path": "evidence.json"})
            self.assertEqual(preview["status"], "NEEDS_RUNTIME_INPUTS")
            resolver.assert_not_called()
        with self.assertRaisesRegex(ValueError, "unknown runtime profile"):
            self.compile_request(self.approved_functional_rf_request(), {"runtime_profile_id": "unknown_profile"})

    def test_profiles_without_runtime_resolver_do_not_load_project_code(self):
        with patch("common.contracts.compile_execution_plan.importlib.import_module") as loader:
            result = self.compile_request(self.ion_processor_request())
            self.assertEqual(result["status"], "EXECUTION_READY")
            request = load_json(HERE / "examples" / "oa_tof_500da_r30000.example.json")
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
                "projects.rf_multipole_ion_optics.runtime.runtime_profile.resolve_execution_binding", return_value=resolved,
            ), self.assertRaises(ValueError):
                self.compile_request(self.approved_functional_rf_request(), self.functional_bindings())

    def test_runtime_binding_requires_the_declared_callable(self):
        with patch("projects.rf_multipole_ion_optics.runtime.runtime_profile.resolve_execution_binding", None):
            with self.assertRaisesRegex(ValueError, "must define resolve_execution_binding"):
                self.compile_request(self.approved_functional_rf_request(), self.functional_bindings())

    def test_selected_runtime_tools_are_bounded_by_declared_capability(self):
        declared = load_json(REPO_ROOT / "projects/rf_multipole_ion_optics/config/execution_profiles.json")
        profile = next(item for item in declared["profiles"]
                       if item["profile_id"] == "hexapole_simion_transport_campaign_engineering")
        profile["tools"] = ["comsol", "matlab", "simion", "python"]
        real_load = load_json

        def selected_load(path):
            if Path(path) == REPO_ROOT / "projects/rf_multipole_ion_optics/config/execution_profiles.json":
                return declared
            return real_load(path)

        valid = dict(project_id="rf_multipole_ion_optics", structural_variant_id="hexapole",
                     authorized_run_id=self.run_id, tools=["simion", "python"])
        with patch("common.contracts.compile_execution_plan.load_json", side_effect=selected_load), patch(
            "projects.rf_multipole_ion_optics.runtime.runtime_profile.resolve_execution_binding", return_value=valid,
        ):
            selected = self.compile_request(self.campaign_request("hexapole"), self.campaign_binding("hex"))
        self.assertEqual(selected["tools"], ["simion", "python"])
        self.assertEqual(len(selected["commands"]), 1)
        for tools in (None, [], "simion", ["simion", "simion"], [1], [""], ["unknown"]):
            with self.subTest(tools=tools), patch(
                "projects.rf_multipole_ion_optics.runtime.runtime_profile.resolve_execution_binding",
                return_value={**valid, "tools": tools},
            ), self.assertRaisesRegex(ValueError, "Runtime tools"):
                self.compile_request(self.campaign_request("hexapole"), self.campaign_binding("hex"))

    def test_execution_contract_and_loaded_resolver_must_belong_to_the_selected_project(self):
        def changed_load(path):
            document = load_json(path)
            if Path(path).name == "execution_profiles.json":
                document["project_id"] = "other_project"
            return document

        with patch("common.contracts.compile_execution_plan.load_json", side_effect=changed_load):
            with self.assertRaisesRegex(ValueError, "contract project identity differs"):
                self.compile_request(self.approved_functional_rf_request(), self.functional_bindings())
        with patch("projects.rf_multipole_ion_optics.runtime.runtime_profile.__file__", str(HERE / "machine_contracts.py")):
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
        with patch("common.contracts.compile_execution_plan.load_json", side_effect=changed_load):
            with self.assertRaisesRegex(ValueError, "Unresolved execution argument placeholder"):
                self.compile_request(self.approved_functional_rf_request(), self.functional_bindings())

    def mass_filter_request(self):
        request = self.approved_rf_request()
        request["target"]["function"] = "mass_filtering"
        request["target"]["mode"] = "quadrupole_mass_filter_reference"
        request["evidence_level"] = "static"
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
        from common.contracts import compile_execution_plan as compiler
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
        with self.assertRaisesRegex(ValueError, "NEEDS_PROJECT_COMPLETION"):
            self.compile_request(request, bindings)

    def campaign_request(self, variant):
        request = self.approved_functional_rf_request()
        request["target"]["structural_variant_id"] = variant
        request["target"]["mode"] = variant + "_finite_3d_no_collision"
        request["objectives"] = request["objectives"][:1]
        request["design_variables"] = []
        return request

    def campaign_binding(self, short_variant):
        return {"campaign_path": str(REPO_ROOT / "projects/rf_multipole_ion_optics/config/campaigns/20260731__noacc_vs_segmented_h15_n100.json"),
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
                with self.assertRaisesRegex(ValueError, "NEEDS_PROJECT_COMPLETION"):
                    self.compile_request(request, bindings)

    def test_current_campaign_previews_with_the_project_relative_runner(self):
        project_root = REPO_ROOT / "projects" / "rf_multipole_ion_optics"
        path = project_root / "config/campaigns/20260731__noacc_vs_segmented_h15_n100.json"
        campaign = load_json(path)
        self.assertEqual(campaign["schema_version"], 7)
        experiment = next(row for row in campaign["experiments"] if row["experiment_id"] == "hex_segmented_h15_n100")
        self.assertIs(experiment["resource_authorization"]["authorized"], False)
        profiles = load_json(project_root / "config/execution_profiles.json")["profiles"]
        profile_id = "hexapole_simion_transport_campaign_engineering"
        profile = next(item for item in profiles if item["profile_id"] == profile_id)
        step = next(item for item in profile["steps"] if item["kind"] == "run")
        self.assertEqual(step["entrypoint"], "runtime/run_simion_transport_campaign.ps1")

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
            (project_root / "runtime/run_simion_transport_campaign.ps1").resolve(),
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
            command = [sys.executable, "-m", "common.contracts.compile_execution_plan", str(plan_path),
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
        request = load_json(HERE / "examples" / "rf_quadrupole_transport.example.json")
        result = self.compile_request(request, qualification="candidate")
        self.assertEqual(result["status"], "NEEDS_IMPLEMENTATION")
        self.assertTrue(any("operating points" in item for item in result["blockers"]))
        self.assertTrue(any("design variables" in item for item in result["blockers"]))
        self.assertIn("Qualification is not supported: candidate", result["blockers"])

    def test_oa_design_request_does_not_masquerade_as_fixed_validation(self):
        request = load_json(HERE / "examples" / "oa_tof_500da_r30000.example.json")
        result = self.compile_request(request)
        self.assertEqual(result["status"], "NEEDS_IMPLEMENTATION")
        self.assertTrue(any("objectives" in item for item in result["blockers"]))
        self.assertTrue(any("constraints" in item for item in result["blockers"]))
        self.assertTrue(any("outputs" in item for item in result["blockers"]))

    def test_oa_validated_structural_candidate_requires_explicit_seed(self):
        request = load_json(HERE / "examples" / "oa_tof_500da_r30000.example.json")
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
            ["-m", "projects.single_reflection_oa_tof_mass_analyzer.workflows.design_candidate.run_candidate"],
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
        request = load_json(HERE / "examples" / "oa_tof_500da_r30000.example.json")
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
        from common.contracts.compile_execution_plan import compile_integration_execution
        from common.contracts.write_run_manifest import file_record
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
            preview = subprocess.run([interpreter, "-m", "common.contracts.compile_execution_plan",
                                      str(planned_path), "--output", str(saved_path)], cwd=REPO_ROOT,
                                     env=compile_env, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
            compiled = json.loads(saved_path.read_text(encoding="utf-8"))
        self.assertEqual(compiled["python_executable"], interpreter)
        integration = compile_integration_execution("instrument_assembly", "single_reflection_flight", self.run_id, {})
        self.assertEqual(integration["python_executable"], interpreter)
        for mode in ("success", "failure", "missing", "unavailable"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                repo = root / "repository"
                project = repo / "projects/fixture"
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
                plan = dict(role="execution_dry_run", status="EXECUTION_READY", safe_to_execute=True,
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
                                         str(REPO_ROOT / "common/contracts/run_artifact_support.ps1"),
                                         str(plan_path), str(repo)], cwd=root, env=env, capture_output=True,
                                        text=True, encoding="utf-8", errors="replace", timeout=30)
                self.assertFalse((repo / ".venv").exists())
                actual_path = project / "actual.json"
                if mode in ("missing", "unavailable"):
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(actual_path.exists())
                    self.assertIn("recompile with the intended Python executable", result.stdout + result.stderr)
                else:
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
