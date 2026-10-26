"""Pure static P/S binding identity and actual PowerShell trial-boundary tests."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint import (
    _native_static_binding_problem, _static_field_problem, _transport_invariants, assert_trial_matches_jacobian,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import CandidateContractError
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.two_prism_simion_trial import (
    _project_selected_center_observation, analyze_trial,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT = Path(__file__).resolve().parents[2]
RUNNER = PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"
MODULE = "projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint"


class NativeStaticIdentityTest(unittest.TestCase):
    def fixture(self):
        voltages = [0.] * 20
        for value, ids in ((-28., (11, 12)), (55., (13, 14)), (190., (16,)), (-190., (17,))):
            for electrode in ids:
                voltages[electrode - 1] = value
        grid = dict(origin_mm=[0, -242, -425], pitch_mm=[.5, 1, 1], dimensions=[326, 801, 851])
        binding = dict(mode="native_static_pa", authority=dict(analyzer_electrode_voltages_v=voltages),
                       grid=grid, refinement_windows=[dict(name="flight", grid=dict(pitch_mm=[.25, .2, .2]),
                                                          active_box_mm=[[0, 22.5], [-100, 390], [-325, 325]],
                                                          native_solver_numerics=dict(refine_stopping="installed_default"))],
                       native_solver_numerics=dict(refine_stopping="installed_default"),
                       instances=[dict(role=role, origin_mm=[0, 0, 0],
                                       record=dict(path=f"/{role}.pa0", bytes=20, sha256=role))
                                  for role in ("global_fallback", "native_corridor", "accelerator", "detector")])
        trial = dict(analyzer_electrode_voltages_v=copy.deepcopy(voltages),
                     stripe_biases_v=[-28., 55.], prism_voltages_v=[190., -190.])
        return binding, trial

    def test_changed_ps_voltages_preserve_scientific_problem_not_payload_paths(self):
        binding, trial = self.fixture()
        expected = _native_static_binding_problem(binding, trial)
        for value, ids in ((-29., (11, 12)), (56., (13, 14)), (189., (16,)), (-189., (17,))):
            for electrode in ids:
                binding["authority"]["analyzer_electrode_voltages_v"][electrode - 1] = value
                trial["analyzer_electrode_voltages_v"][electrode - 1] = value
        trial.update(stripe_biases_v=[-29., 56.], prism_voltages_v=[189., -189.])
        binding["instances"][0]["record"]["sha256"] = "changed_parent_voltage"
        binding["instances"][1]["record"]["path"] = "/same_asset/new_provenance.pa0"
        self.assertEqual(expected, _native_static_binding_problem(binding, trial))

    def test_grid_collision_and_fixed_voltage_changes_change_problem(self):
        binding, trial = self.fixture()
        expected = _native_static_binding_problem(binding, trial)
        for change in ("grid", "collision", "mirror", "numerics", "window_numerics"):
            other = copy.deepcopy(binding)
            materialization = copy.deepcopy(trial)
            if change == "grid":
                other["grid"]["pitch_mm"][0] = .25
            elif change == "collision":
                other["instances"][1]["record"]["sha256"] = "new_geometry"
            elif change == "numerics":
                other["native_solver_numerics"] = dict(refine_stopping="contract_convergence", convergence_v=1e-5)
            elif change == "window_numerics":
                other["refinement_windows"][0]["native_solver_numerics"] = dict(
                    refine_stopping="contract_convergence", convergence_v=1e-5)
            else:
                other["authority"]["analyzer_electrode_voltages_v"][1] = -6000.
                materialization["analyzer_electrode_voltages_v"][1] = -6000.
            self.assertNotEqual(expected, _native_static_binding_problem(other, materialization))

    def test_mismatched_consumed_voltages_fail(self):
        binding, trial = self.fixture()
        trial["stripe_biases_v"][0] += 1
        with self.assertRaisesRegex(CandidateContractError, "P/S voltages"):
            _native_static_binding_problem(binding, trial)


class StaticFieldIdentityTest(unittest.TestCase):
    def solver_fixture(self):
        return dict(active_mesh_tag="mesh2",fc_solver="i1",fc_active=True,iterative_active=True,
                    iterative_solver="cg",multigrid_active=True,mg_prefun="amg",mg_cycle="v",mg_amgauto=3,
                    mg_loweramg="off",mg_prefermatfree=False,stationary_control="stat",stationary_stol=1e-9,
                    study_usestol=True,study_stol=1e-9,scale_method="manual",scale_v=6011.74707853214,
                    field_scale_method="parent",rhob=400,errorchk="auto",prefuntype="left",nlinnormuse="off")

    def solver_tree(self, numerics):
        rows = {
            "sol1/s1":dict(control=numerics["stationary_control"],stol=numerics["stationary_stol"]),
            "sol1/s1/fc1":dict(linsolver=numerics["fc_solver"]),
            "sol1/s1/i1":dict(linsolver=numerics["iterative_solver"],rhob=numerics["rhob"],
                             errorchk=numerics["errorchk"],prefuntype=numerics["prefuntype"],nlinnormuse=numerics["nlinnormuse"]),
            "sol1/s1/i1/mg1":dict(prefun=numerics["mg_prefun"],mgcycle=numerics["mg_cycle"],amgauto=numerics["mg_amgauto"],
                                 loweramg=numerics["mg_loweramg"],prefermatfree=numerics["mg_prefermatfree"]),
            "sol1/v1":dict(scalemethod=numerics["scale_method"],scaleval=numerics["scale_v"]),
            "sol1/v1/comp1_V":dict(scalemethod=numerics["field_scale_method"]),
            "std1/stat":dict(mesh=["geom1",numerics["active_mesh_tag"]],usestol="on" if numerics["study_usestol"] else "off",
                             stol=numerics["study_stol"]),
        }
        nodes = {path:dict(path=path,is_active=True,children=[],properties=[
            dict(name=name,value=value,read_error="") for name,value in properties.items()]) for path,properties in rows.items()}
        for path,key in (("sol1/s1/fc1","fc_active"),("sol1/s1/i1","iterative_active"),("sol1/s1/i1/mg1","multigrid_active")):
            nodes[path]["is_active"] = numerics[key]
        return dict(solver=[node for path,node in nodes.items() if path!="std1/stat"],study_step=nodes["std1/stat"])

    def fixture(self):
        authority = dict(analyzer_electrode_voltages_v=list(range(20)), assembly={"origin": [0, 1, 2]})
        binding = dict(export_manifest="/candidate/run_manifest.json", authority=authority,
                       geometry={"detector": {"box": {}}},
                       records={"geometry_authority": {"sha256": "geometry"}},
                       assembly_manifest="/assembly/run_manifest.json", collision_manifest="/collision/run_manifest.json")
        plan = dict(role="mrtof_same_mesh_field_provider_request", source_field_manifest="/field/run_manifest.json",
                    active_mesh_tag="mesh2",source_mph_record={"sha256": "savedmesh", "bytes": 10},
                    source_dataset={"dataset_tag": "dset1", "solution_tag": "sol1"},
                    export_grid={"pitch_mm": [.25]*3, "origin_mm": [0, 0, 0], "dimensions":[21,2441,2321],"block_points": 8})
        binding["grid"] = copy.deepcopy(plan["export_grid"])
        materialization = dict(field_binding={"mode": "comsol_static_scalar_v", "path": "/candidate/binding.json"},
                               stripe_biases_v=[10, 12], prism_voltages_v=[15, 16],
                               analyzer_electrode_voltages_v=list(range(20)))
        # Both members of each Stripe group have one working voltage.
        for index in (11, 13):
            authority["analyzer_electrode_voltages_v"][index] -= 1
            materialization["analyzer_electrode_voltages_v"][index] -= 1
        return binding, plan, materialization

    def identity(self, binding, plan, materialization, numerics=None, ordinary=False, after=None):
        solver = self.solver_fixture()
        if numerics is not None:
            solver.update(numerics)
        compiled = copy.deepcopy(plan)
        compiled["candidate_authority"] = copy.deepcopy(binding["authority"])
        export_plan = dict(source_model_summary="/field/summary.json",artifact_retention={},resource_threshold_action="warn",
                           solve_memory_bytes=1,solve_seconds=1,artifact_budget_bytes=1) if ordinary else plan
        plan_name = "diagnostic_plan.json" if ordinary else "plan.json"
        def load(path):
            if path.name=="run_manifest.json":
                return dict(outputs=[dict(path="/field/solver_configured.json")],
                            inputs={"export_plan":dict(path=str(path.parent / "inputs" / plan_name))})
            if path.name==plan_name:
                return export_plan
            if path.name=="solver_configured.json":
                return self.solver_tree(solver)
            return solver if path.name=="solver_before.json" or after is None else after
        with patch(f"{MODULE}.load_binding", return_value=binding), patch(f"{MODULE}._record"), \
             patch(f"{MODULE}.compile_request",return_value=compiled),patch(f"{MODULE}._load_object",side_effect=load):
            return _static_field_problem(materialization)

    def test_ordinary_scalar_mesh2_and_provider_have_same_scientific_family(self):
        binding,plan,trial = self.fixture()
        self.assertEqual(self.identity(binding,plan,trial,ordinary=True),self.identity(binding,plan,trial))

    def test_active_mesh_mismatch_or_changed_after_solve_is_rejected(self):
        binding,plan,trial = self.fixture()
        with self.assertRaisesRegex(CandidateContractError,"actual solver mesh"):
            self.identity(binding,plan,trial,numerics={"active_mesh_tag":"mesh1"})
        after = self.solver_fixture();after["stationary_stol"] = 1e-8
        with self.assertRaisesRegex(CandidateContractError,"changed sealed solver"):
            self.identity(binding,plan,trial,after=after)

    def test_grid_and_geometry_changes_cannot_transport_same_jacobian(self):
        binding,plan,trial = self.fixture()
        baseline = self.identity(binding,plan,trial,ordinary=True)
        shifted_binding,shifted_plan = copy.deepcopy(binding),copy.deepcopy(plan)
        shifted_binding["grid"]["origin_mm"][1] += .125
        with self.assertRaisesRegex(CandidateContractError,"grid differs"):
            self.identity(shifted_binding,plan,trial)
        shifted_plan["export_grid"]["origin_mm"][1] += .125
        self.assertNotEqual(baseline,self.identity(shifted_binding,shifted_plan,trial))
        changed_binding = copy.deepcopy(binding)
        changed_binding["records"]["geometry_authority"]["sha256"] = "differentgeometry"
        changed_binding["geometry"]["detector"]["box"]["changed"] = True
        self.assertNotEqual(baseline,self.identity(changed_binding,plan,trial))

    def test_measured_jacobian_reuse_accepts_same_family_and_rejects_scientific_changes(self):
        binding,plan,trial = self.fixture()
        baseline_identity = self.identity(binding,plan,trial,ordinary=True)
        proposal = dict(baseline_manifest="/baseline/run_manifest.json",consumed_trials=[
            dict(manifest="/baseline/run_manifest.json",manifest_sha256="fixture")])
        def reuse(identity):
            baseline = dict(frozen_problem={"static_field_problem":baseline_identity,"trajectory_profile":"fixed"})
            child = dict(frozen_problem={"static_field_problem":identity,"trajectory_profile":"fixed"})
            with patch(f"{MODULE}.file_sha256",return_value="fixture"),patch(f"{MODULE}._trial",side_effect=[baseline,child]):
                return assert_trial_matches_jacobian(proposal,Path("/child/run_manifest.json"))
        self.assertEqual(reuse(self.identity(binding,plan,trial))["frozen_problem"]["static_field_problem"],baseline_identity)
        changed = []
        mesh = copy.deepcopy(plan);mesh["source_mph_record"]["sha256"] = "othermesh"
        changed.append(self.identity(binding,mesh,trial))
        changed.append(self.identity(binding,plan,trial,numerics={"stationary_stol":1e-8}))
        for field in ("geometry","collision","grid","non_ps_voltage","dataset"):
            b,p,t = copy.deepcopy(binding),copy.deepcopy(plan),copy.deepcopy(trial)
            if field=="geometry":
                b["records"]["geometry_authority"]["sha256"] = "other"
                b["geometry"]["detector"]["box"]["changed"] = True
            elif field=="collision":
                b["collision_manifest"] = "/other/run_manifest.json"
            elif field=="grid":
                b["grid"]["origin_mm"][1] += .125;p["export_grid"]["origin_mm"][1] += .125
            elif field=="dataset":
                p["source_dataset"]["solution_tag"] = "other"
            else:
                b["authority"]["analyzer_electrode_voltages_v"][1] += 1
                t["analyzer_electrode_voltages_v"][1] += 1
            changed.append(self.identity(b,p,t))
        for identity in changed:
            with self.assertRaisesRegex(CandidateContractError,"Jacobian frozen physical problem"):
                reuse(identity)

    def test_candidates_share_family_but_actual_voltage_must_match(self):
        binding, plan, materialization = self.fixture()
        baseline = self.identity(binding, plan, materialization)
        candidate_binding, candidate_trial = copy.deepcopy(binding), copy.deepcopy(materialization)
        candidate_binding["export_manifest"] = "/other-candidate/run_manifest.json"
        candidate_binding["authority"]["analyzer_electrode_voltages_v"][15] += 1
        candidate_trial["prism_voltages_v"][0] += 1
        candidate_trial["analyzer_electrode_voltages_v"][15] += 1
        self.assertEqual(baseline, self.identity(candidate_binding, plan, candidate_trial))
        with self.assertRaisesRegex(CandidateContractError, "voltages differ"):
            self.identity(binding, plan, candidate_trial)

    def test_saved_mesh_geometry_collision_and_numerics_remain_invariant(self):
        binding, plan, materialization = self.fixture()
        baseline = self.identity(binding, plan, materialization)
        changed = copy.deepcopy(plan)
        changed["source_mph_record"]["sha256"] = "othermesh"
        self.assertNotEqual(baseline, self.identity(binding, changed, materialization))
        changed = copy.deepcopy(binding)
        changed["collision_manifest"] = "/other-collision/run_manifest.json"
        self.assertNotEqual(baseline, self.identity(changed, plan, materialization))
        self.assertNotEqual(baseline, self.identity(binding, plan, materialization, {"stationary_stol": 1e-8}))

    def test_mirror_target_stays_in_fixed_ps_family_identity(self):
        binding, plan, materialization = self.fixture()
        baseline = self.identity(binding,plan,materialization)
        changed_binding, changed_trial = copy.deepcopy(binding),copy.deepcopy(materialization)
        for i in (1,6):
            changed_binding["authority"]["analyzer_electrode_voltages_v"][i] += 1
            changed_trial["analyzer_electrode_voltages_v"][i] += 1
        self.assertNotEqual(baseline,self.identity(changed_binding,plan,changed_trial))

    def test_native_projection_unchanged(self):
        self.assertIsNone(_static_field_problem({}))

    def test_sealed_small_provider_trial_identity_without_asset_rehash(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_corridor_field_provider import RefinementWindowProviderTest
        fixture = RefinementWindowProviderTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        run, plan = fixture.candidate()
        solver = self.solver_fixture()
        solver["active_mesh_tag"] = "mesh3"
        for name in ("solver_before.json", "solver_after.json"):
            fixture.write(run / "inputs" / name, solver)
        self.assertEqual(fixture.publish(run)["status"], "success")
        materialization = dict(
            field_binding={"mode":"comsol_static_scalar_v", "path":str(run / "inputs/field_binding.json")},
            stripe_biases_v=[-27,54], prism_voltages_v=[191,-190],
            analyzer_electrode_voltages_v=json.loads((run / "inputs/frozen_input.json").read_text())["analyzer_electrode_voltages_v"])
        with patch("common.contracts.file_identity.file_sha256", side_effect=AssertionError("No asset rehash")):
            identity = _static_field_problem(materialization)
        self.assertEqual(identity["solver_numerics"]["iterative_solver"], "cg")
        self.assertEqual(identity["export_grid"]["pitch_mm"], [.5]*3)
        self.assertGreater(identity["source_mesh_record"]["bytes"], 0)

    def test_candidate_metadata_is_not_solver_numerics(self):
        binding, plan, materialization = self.fixture()
        self.assertEqual(self.identity(binding, plan, materialization), self.identity(
            binding, plan, materialization,
            {"stationary_stol": 1e-9, "mg_loweramg": "off", "edited": True, "run_id": "other"},
        ))

    def test_transport_preserves_static_field_family_and_native_shape(self):
        names = ("targets", "mirror_voltages_v", "selected_axial_energy_per_charge_v",
                 "source_slow_kinetic_energy_per_charge_v", "drift_phase_contract",
                 "trajectory_profile", "nonaccelerator_mesh_mm_per_gu")
        frozen = {name: None for name in names}
        frozen["inputs"] = {name: name for name in (
            "fixed_mirror_stripe_authority_sha256", "mirror_summary_sha256",
            "reviewed_contract_sha256", "stripe_summary_sha256",
        )}
        self.assertNotIn("static_field_problem", _transport_invariants({"frozen_problem": frozen}))
        frozen["static_field_problem"] = {"source_mesh_record": "one"}
        before = _transport_invariants({"frozen_problem": frozen})
        frozen["static_field_problem"] = {"source_mesh_record": "two"}
        self.assertNotEqual(before, _transport_invariants({"frozen_problem": frozen}))


class SelectedCenterObservationTest(unittest.TestCase):
    def test_ordinary_volume_particle_one_is_not_promoted(self):
        result = {"status": "bunch_observed"}
        trial = {"source_cohort_role": "volume", "source_expected_particle_ids": [1],
                 "source_center_state": {"particle_id": 1},
                 "source_selection": {"role": "contiguous_frozen_source_diagnostic_selection"}}
        _project_selected_center_observation(result, trial, [])
        self.assertEqual(result, {"status": "bunch_observed"})

    def test_declared_center_without_return_is_incomplete(self):
        result = {"center_particle_workpoint_validation": {"status": "observed", "residuals": {}},
                  "cohort_analysis": {"event_integrity_passed": True}}
        trial = {"source_cohort_role": "controlled_diagnostic", "source_expected_particle_ids": [1],
                 "source_center_state": {"particle_id": 1}, "target_drift_period_ratio": 24.5,
                 "source_selection": {"role": "contiguous_frozen_source_diagnostic_selection"}}
        _project_selected_center_observation(result, trial, [])
        self.assertEqual(result["status"], "selected_center_observation_incomplete")
        self.assertFalse(result["static_return_diagnostic"]["event_contract_ok"])

    def test_real_common_center_reanalysis_preserves_exit_failure(self):
        run = PROJECT.parents[2] / "artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261006_030113__sim__simion__mrtof-comsol-p1-plus1-center"
        if not run.is_dir():
            self.skipTest("External sealed common-center fixture not installed")
        old = json.loads((run / "results/two_prism_trial_observation.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="mrtof-center-observation-") as directory:
            result = analyze_trial(log_path=run / "logs/native_two_prism_flight.log",
                                   trial_receipt_path=run / "results/two_prism_trial_materialization.json",
                                   output_path=Path(directory) / "observation.json")
        self.assertEqual(result["status"], "full_drift_observed")
        self.assertTrue(result["static_return_diagnostic"]["event_contract_ok"])
        self.assertEqual(result["residuals"], old["center_particle_workpoint_validation"]["residuals"])
        self.assertEqual(result["accelerator_geometric_exit_validation"], old["accelerator_geometric_exit_validation"])
        self.assertEqual(result["cohort_analysis"]["expected_particle_count"], 1)
        self.assertIn("not_formal", result["qualification"])


class PowerShellTrialBoundaryTest(unittest.TestCase):
    def test_frozen_center_receipt_keeps_original_producer_for_child(self):
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("PowerShell Core is unavailable")
        with tempfile.TemporaryDirectory(prefix="mrtof-center-freeze-") as directory:
            root = Path(directory)
            producer = root / "producer/results/bunch_source_receipt.json"
            producer.parent.mkdir(parents=True)
            producer.write_text('{"status":"materialized"}', encoding="utf-8")
            inputs = root / "parent/inputs"
            inputs.mkdir(parents=True)
            command = r"""param($Source,$Producer,$Inputs)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'production parse failed'}
$freeze=@($ast.FindAll({param($n)
    $n -is [Management.Automation.Language.IfStatementAst] -and
    $n.Extent.Text.Contains('Copy-VerifiedRunInput') -and
    $n.Extent.Text.Contains("'center_source_receipt.json'")
},$true))
if($freeze.Count-ne1){throw 'expected one actual static input freeze block'}
$function=$ast.Find({param($n)
    $n -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $n.Name-eq'New-CenterTrialArguments'
},$true)
Invoke-Expression $function.Extent.Text
function Copy-VerifiedRunInput {param($Source,$Destination)
    Copy-Item -LiteralPath $Source -Destination $Destination
    return $Destination
}
$staticFieldMode=$true;$package=@{input_dir=$Inputs}
$CenterSourceReceiptPath=$Producer;$FieldProviderRequestPath=$Producer
$ResponseFieldBindingPath=''
$GeometryReviewRunPath='geometry';$MirrorRunPath='mirror';$StripeRunPath='stripe'
$TrajectoryStepScale=.25;$AcceleratorSourceYOffsetMm=0
$python='python';$capacitySession=$null;$AcceleratorProviderReceiptPath='oa-receipt'
$CompositionPlanPath='composition-plan';$LocalScopePath=''
$PulseAcceleratorUntilInitialExit=$false;$AcceleratorPulseSchedulePath=''
$TrajectoryProfileId='center_screening';$SimionExe=''
Invoke-Expression $freeze[0].Extent.Text
$child=New-CenterTrialArguments -Voltages @(-27,54,191,-190) -ChildRunId 'fixture'
@{child_source=$child.BunchSourceReceiptPath;minimum=$child.BunchParticleIdMin;
  maximum=$child.BunchParticleIdMax;frozen_source=$frozenCenterSourceReceipt;
  frozen_exists=(Test-Path -LiteralPath $frozenCenterSourceReceipt)}|ConvertTo-Json -Compress
"""
            process = subprocess.run(
                [pwsh, "-NoProfile", "-Command", "& {" + command + "}",
                 str(RUNNER), str(producer), str(inputs)],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            result = json.loads(process.stdout)
            self.assertEqual(Path(result["child_source"]), producer)
            self.assertEqual((result["minimum"], result["maximum"]), (1, 1))
            self.assertEqual(Path(result["frozen_source"]), inputs / "center_source_receipt.json")
            self.assertTrue(result["frozen_exists"])
            self.assertEqual(Path(result["frozen_source"]).read_bytes(), producer.read_bytes())

    def run_fixture(self, mode, prism_only=False, provider_failure=False, mirror=False, same=False,
                    mirror_changed=False, preflight_failure=False, completed=""):
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("PowerShell Core is unavailable")
        with tempfile.TemporaryDirectory(prefix="mrtof-static-iteration-") as directory:
            root = Path(directory)
            provider = root / "provider.ps1"
            provider.write_text("""param($RequestPath,$RunDirectory,[switch]$Approved)
Add-Content $env:MRTOF_FIXTURE_ORDER 'provider'
if($env:MRTOF_FIXTURE_FAIL -eq 'true'){throw 'fixture provider failed'}
New-Item -ItemType Directory -Path $RunDirectory -Force|Out-Null
@{status='success';field_binding='candidate-binding.json'}|ConvertTo-Json|Set-Content (Join-Path $RunDirectory 'summary.json')
""", encoding="utf-8")
            trial = root / "trial.ps1"
            trial.write_text("""param($FieldBindingPath,$Stripe1VoltageV,$Stripe2VoltageV,$Prism1VoltageV,$Prism2VoltageV,$RunId,$CapacityWorkflowSession,$InheritedHostResourceLease,$MirrorVoltageVariationPath,$ContractPath)
Add-Content $env:MRTOF_FIXTURE_ORDER 'trial'
@{binding=$FieldBindingPath;s1=$Stripe1VoltageV;s2=$Stripe2VoltageV;lease=$InheritedHostResourceLease;mirror=$MirrorVoltageVariationPath}|ConvertTo-Json -Compress
""", encoding="utf-8")
            fixture = root / "fixture.ps1"
            # Exercise the production Python expression and complete authority builder;
            # sealed-receipt I/O is covered by the provider's compiler fixtures.
            (root / "authority_fixture.py").write_text("""import json,sys
from pathlib import Path
from unittest.mock import patch
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider import candidate_authority
code, request_json = sys.argv[1:]
def compile_fixture(request):
    Path(__file__).with_name('checked_request.json').write_text(json.dumps(request))
    if request['fixture_preflight_failure']:
        raise ValueError('fixture authority parse failed')
    source = {'analyzer_electrode_voltages_v': [0]*10+[-27,-27,54,54,0,191,-190,0,0,0]}
    mirror = [0,1,0,0,0] if request['fixture_mirror_changed'] else [0]*5
    candidate = candidate_authority(source,request['candidate_voltages_v'],
        mirror_voltages_v=mirror if request.get('mirror_voltage_variation_path') else None)
    return {'source_authority':source,'candidate_authority':candidate}
def load_fixture(path, **kwargs):
    return {'authority': {'analyzer_electrode_voltages_v': [0]*10+[-27,-27,54,54,0,191,-190,0,0,0]}}
def derive_fixture(request, source):
    return compile_fixture(request)['candidate_authority'], {}
with patch('projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding.load_binding',load_fixture), \
     patch('projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider.derive_candidate_authority',derive_fixture):
    sys.argv = ['authority',request_json]
    exec(code)
""", encoding="utf-8")
            fixture.write_text("""param($Source,$Root,$Mode,$PrismOnly,$ProviderFailure,$Mirror,$Same,$MirrorChanged,$PreflightFailure,$PythonExe,$Completed)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'production parse failed'}
$function=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Invoke-CenterTrial'},$true)
Invoke-Expression $function.Extent.Text
function Write-RunJson {param($Path,$Depth,$Value) $Value|ConvertTo-Json -Depth $Depth|Set-Content $Path}
function Update-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session,$ProtectedPaths)
    @($ProtectedPaths)|ConvertTo-Json -AsArray|Set-Content (Join-Path $Root 'protected.json')
    return @{session=$Session}
}
function Invoke-RunToolRootContext {param($RepoRoot,$Operation) & $Operation}
function Invoke-FixturePython {
    $supplied=@($args)
    if($supplied[0]-eq'-m'){
        if($supplied[1]-ne'projects.parallel_mirror_dual_stripe_mr_tof.analysis.corridor_field_provider'-or
           $supplied[2]-ne'--resolve-completed-request'-or$supplied[4]-ne'--completed-provider-manifest'){
            throw 'unexpected completed-provider CLI boundary'
        }
        if(-not(Test-Path -LiteralPath $supplied[3])-or$supplied[5]-ne$CompletedFieldProviderManifest){throw 'completed-provider input transport differs'}
        $global:LASTEXITCODE=if($Completed-eq'invalid'){1}else{0}
        @{binding=$(if($Completed-eq'match'){'completed-binding.json'}else{$null})}|ConvertTo-Json -Compress
        return
    }
    & $PythonExe (Join-Path $Root 'authority_fixture.py') $supplied[1] $supplied[2]
}
$staticFieldMode=$Mode -eq 'static';$python='Invoke-FixturePython';$repoRoot='unused'
$ResponseFieldBindingPath=''
$capacitySession=@{status='active'};$package=@{input_dir=$Root};$artifactRoot=$Root
$fieldProviderRequest=@{role='mrtof_same_mesh_field_provider_request';source_binding_path='source-binding.json';candidate_voltages_v=@{s1=-27;s2=54;p1=191;p2=-190}}
$fieldProviderRequest.fixture_mirror_changed=$MirrorChanged-eq'true'
$fieldProviderRequest.fixture_preflight_failure=$PreflightFailure-eq'true'
$staticBinding=@{authority=@{analyzer_electrode_voltages_v=@(0,0,0,0,0,0,0,0,0,0,-27,-27,54,54,0,191,-190,0,0,0)}}
$fieldProviderRunner=Join-Path $Root 'provider.ps1';$trialRunner=Join-Path $Root 'trial.ps1'
$CompletedFieldProviderManifest=if($Completed){Join-Path $Root 'completed/run_manifest.json'}else{''}
$env:MRTOF_FIXTURE_ORDER=Join-Path $Root 'order.txt';$env:MRTOF_FIXTURE_FAIL=$ProviderFailure
$arguments=@{RunId='fixture';Prism1VoltageV=192;Prism2VoltageV=-191;ContractPath='frozen-contract.json'}
if($PrismOnly-ne'true'){$arguments.Stripe1VoltageV=-28;$arguments.Stripe2VoltageV=55}
if($Same-eq'true'){$arguments.Prism1VoltageV=191;$arguments.Prism2VoltageV=-190;$arguments.Stripe1VoltageV=-27;$arguments.Stripe2VoltageV=54}
if($Mirror-eq'true'){
  $fieldProviderRequest.mirror_reference_trial_manifest='original-reference.json'
  $arguments.MirrorVoltageVariationPath='frozen-absolute-target.json';$arguments.ContractPath='frozen-contract.json'
}
Invoke-CenterTrial -Arguments $arguments
""", encoding="utf-8")
            process = subprocess.run([pwsh, "-NoProfile", "-File", str(fixture), str(RUNNER), str(root), mode,
                                      str(prism_only).lower(), str(provider_failure).lower(), str(mirror).lower(), str(same).lower(),
                                      str(mirror_changed).lower(), str(preflight_failure).lower(), sys.executable, completed],
                                     cwd=REPO_ROOT, env={**os.environ,"PYTHONPATH":str(REPO_ROOT)},
                                     capture_output=True, text=True, encoding="utf-8", timeout=30)
            order_path = root / "order.txt"
            order = order_path.read_text(encoding="utf-8-sig").splitlines() if order_path.exists() else []
            if mirror and process.returncode == 0:
                request = json.loads((root / "checked_request.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(request["mirror_voltage_variation_path"],"frozen-absolute-target.json")
                self.assertEqual(request["mirror_reference_trial_manifest"],"original-reference.json")
                self.assertEqual(request["mirror_contract_path"],"frozen-contract.json")
            if completed == "match" and process.returncode == 0:
                protected = json.loads((root / "protected.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(protected, [str(root / "completed")])
            return process, order

    def test_completed_provider_match_skips_solver_and_protects_source(self):
        process, order = self.run_fixture("static", completed="match")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(order, ["trial"])
        self.assertEqual(json.loads(process.stdout)["binding"], "completed-binding.json")

    def test_completed_provider_nonmatch_keeps_normal_provider_path(self):
        process, order = self.run_fixture("static", completed="nonmatch")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(order, ["provider", "trial"])
        self.assertEqual(json.loads(process.stdout)["binding"], "candidate-binding.json")

    def test_invalid_completed_provider_never_solves_or_flies(self):
        process, order = self.run_fixture("static", completed="invalid")
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(order, [])
        self.assertIn("Completed field provider validation failed", process.stderr)

    def test_mirror_reference_and_target_are_sent_before_original_trial(self):
        process,order = self.run_fixture("static",mirror=True,same=True,mirror_changed=True)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertEqual(order,["provider","trial"])
        self.assertEqual(json.loads(process.stdout)["mirror"],"frozen-absolute-target.json")

    def test_identical_absolute_mirror_target_reuses_source_and_keeps_variation(self):
        process,order = self.run_fixture("static",mirror=True,same=True)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertEqual(order,["trial"])
        result = json.loads(process.stdout)
        self.assertEqual(result["binding"],"source-binding.json")
        self.assertEqual(result["mirror"],"frozen-absolute-target.json")

    def test_ps_change_with_same_mirror_target_still_updates_field(self):
        process,order = self.run_fixture("static",mirror=True)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertEqual(order,["provider","trial"])

    def test_authority_preflight_failure_never_calls_provider_or_flies(self):
        process,order = self.run_fixture("static",mirror=True,same=True,preflight_failure=True)
        self.assertNotEqual(process.returncode,0)
        self.assertEqual(order,[])
        self.assertIn("Candidate field authority preflight failed",process.stderr)

    def test_unchanged_source_field_reuses_binding_without_provider(self):
        process,order = self.run_fixture("static",same=True)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertEqual(order,["trial"])
        self.assertEqual(json.loads(process.stdout)["binding"],"source-binding.json")

    def test_static_provider_precedes_trial_and_prism_only_inherits_real_stripes(self):
        process, order = self.run_fixture("static", prism_only=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(order, ["provider", "trial"])
        result = json.loads(process.stdout)
        self.assertEqual((result["s1"], result["s2"]), (-27, 54))
        self.assertEqual(result["binding"], "candidate-binding.json")
        self.assertIsNone(result["lease"])

    def test_provider_failure_never_flies(self):
        process, order = self.run_fixture("static", provider_failure=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(order, ["provider"])

    def test_native_boundary_does_not_call_provider(self):
        process, order = self.run_fixture("native")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(order, ["trial"])


if __name__ == "__main__":
    unittest.main()
