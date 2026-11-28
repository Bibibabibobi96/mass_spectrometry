"""Prepared-joint recorded analysis and lifecycle tests; no commercial solver."""

from msplatform.backends.simion.native_completion import retention_api as _manifest_retention_api
from msplatform.backends.simion.mr_prepared_field import compile_memory_consumer_crops, validate_candidate_binding
import json
import shutil
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from msplatform.backends.simion.mrtof_batch_flight import merge_measured_event_logs
from msplatform.workflows.prepared_joint.trial import compare_trajectory_representation


class PreparedJointBatchTests(unittest.TestCase):


    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_public_analysis_invoker_rejects_changed_frozen_source(self):
        repo = Path(__file__).resolve().parents[4]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "check.ps1"
            script.write_text(r"""param($Repo,$Destination,$Python)
$repoRoot=$Repo
. (Join-Path $Repo 'src/msplatform/execution/resources/dependencies.ps1')
. (Join-Path $Repo 'src/msplatform/execution/resources/run_artifact_support.ps1')
$frozen=Freeze-ConsumerDependencies -Python $Python -RepoRoot $Repo -ContractPath (Join-Path $Repo 'src/msplatform/workflows/config/runtime_dependencies.json') -InputDir $Destination -OwnerId instrument_assembly -ConsumerId prepared_joint
$source=Get-Content -LiteralPath (Join-Path $Repo 'src/msplatform/workflows/resources/prepared_joint_execute.ps1') -Raw
$tokens=$null;$errors=$null
$tree=[System.Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'launcher parser errors'}
$function=$tree.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Invoke-ProjectPython'},$true)
if($function.Count-ne1){throw 'launcher invoker not unique'}
. ([scriptblock]::Create($function[0].Extent.Text))
$script:pythonRoot=[string]$frozen.execution_root;$script:preparedPackage=$null
$module='msplatform.workflows.prepared_joint.trial'
$help=@('-m',$module,'--help')
$good=@(Invoke-ProjectPython -Arguments $help -FrozenPackage $frozen)-join "`n"
if($good-notmatch 'usage:'){throw 'real selected module did not return help'}
$identity=@($frozen.identities|Where-Object {$_.source_repo_path-ceq 'src/msplatform/workflows/prepared_joint/trial.py'})
if($identity.Count-ne1){throw 'selected source identity missing'}
$target=[string]$identity[0].snapshot_path;$original=[IO.File]::ReadAllBytes($target)
try{
  Remove-Item -LiteralPath $target
  try{Invoke-ProjectPython -Arguments $help -FrozenPackage $frozen|Out-Null;throw 'missing source accepted'}catch{if($_.Exception.Message-notmatch 'Frozen Python dependency is missing'){throw}}
  [IO.File]::WriteAllBytes($target,($original+[byte[]](1)))
  try{Invoke-ProjectPython -Arguments $help -FrozenPackage $frozen|Out-Null;throw 'changed source accepted'}catch{if($_.Exception.Message-notmatch 'Frozen Python dependency hash differs'){throw}}
}finally{[IO.File]::WriteAllBytes($target,$original)}
try{Invoke-ProjectPython -Arguments @('-m',$module,'--invalid-option') -FrozenPackage $frozen|Out-Null;throw 'bad arguments accepted'}catch{if($_.Exception.Message-notmatch '^Python stage failed:' -or $_.Exception.Data['exit_code'] -ne 2 -or $null -eq $_.Exception.InnerException){throw}}
# A junction is an execution alias for the same frozen tree; do not copy it.
$alias=Join-Path (Split-Path -Parent $Destination) 'projected_snapshot'
$null=New-Item -ItemType Junction -Path $alias -Target $frozen.execution_root
try{
  $script:preparedPackage=[pscustomobject]@{}
  function Get-RunNativeExecutionContext {param($Package,$Paths,$Tool) [pscustomobject]@{projected_paths=@($alias);environment=@{}}}
  $aliasHelp=@(Invoke-ProjectPython -Arguments $help -FrozenPackage $frozen)-join "`n"
  if($aliasHelp-notmatch 'usage:'){throw 'projected selected module did not return help'}
  [IO.File]::WriteAllBytes($target,($original+[byte[]](1)))
  try{Invoke-ProjectPython -Arguments $help -FrozenPackage $frozen|Out-Null;throw 'projected changed source accepted'}catch{if($_.Exception.Message-notmatch 'Frozen Python dependency hash differs'){throw}}
}finally{
  [IO.File]::WriteAllBytes($target,$original)
  Remove-Item -LiteralPath $alias
  $script:preparedPackage=$null
}
Write-Output 'FROZEN_ANALYSIS_INVOKER=PASS'
""", encoding="utf-8")
            result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(script), str(repo),
                                     str(root / "inputs"), sys.executable], cwd=root, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("FROZEN_ANALYSIS_INVOKER=PASS", result.stdout)



    def test_staged_adapter_reuses_json_phase_space_and_rejects_changed_evidence(self):
        from msplatform.workflows.mr_design.downstream_workpoint import (
            materialize_prepared_staged_adapter,
        )
        module="msplatform.workflows.mr_design.downstream_workpoint"
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); authority=root/"authority.json";authority.write_text('{}')
            state=dict(position_mm=(.1,-2.,33.),velocity_mm_per_us=(.01,1.4,40.))
            trial=dict(observation=dict(center_particle_prism_handoff_validation=dict(
                p2_low_field_reference_state=state)),materialization=dict(prism_voltages_v=[340.,-186.]))
            with patch(module+".load_prepared_centroid_trial",return_value=trial):
                first=materialize_prepared_staged_adapter(authority,authority,authority,root/"views")
                second=materialize_prepared_staged_adapter(authority,authority,authority,root/"views")
                self.assertEqual(first,second)
                path=Path(first["outputs"]["observation"]["path"])
                frozen=path.read_bytes()
                trial["observation"]["center_particle_prism_handoff_validation"][
                    "p2_low_field_reference_state"]["position_mm"]=(.1,-2.1,33.)
                with self.assertRaisesRegex(ValueError,"change existing stage evidence"):
                    materialize_prepared_staged_adapter(authority,authority,authority,root/"views")
                self.assertEqual(path.read_bytes(),frozen)

    def test_candidate_binding_keeps_ip_operator_and_reuses_new_parent(self):
        import copy
        from msplatform.components.multi_reflection_tof.candidate_voltage import candidate_authority
        authority = dict(analyzer_electrode_voltages_v=[0.0]*20,
                         component_voltages_v=[dict(namespace="ion_processor", id=i, value_v=i) for i in range(1,16)],
                         assembly=dict(native_operating_point=dict(lift_v=4480.04379)))
        baseline = dict(accelerator_provider="ion_processor", geometry=dict(IP="same"),
            authority=authority, sources=dict(scalar_pa="old_parent.pa"), grid=dict(origin_mm=[0,0,0]),
            instances=[dict(role=r,pa_path="old_parent.pa" if i==0 else r+".pa",origin_mm=[0,0,0])
                       for i,r in enumerate(["global_fallback","native_corridor","ion_processor_collision","detector"])])
        candidate = copy.deepcopy(baseline)
        candidate["authority"] = candidate_authority(authority, dict(s1=1,s2=2,p1=3,p2=4))
        candidate["sources"]["scalar_pa"]="new_parent.pa"
        candidate["instances"][0]["pa_path"]="new_parent.pa"
        module="msplatform.backends.simion.mr_prepared_field"
        overlay = copy.deepcopy(candidate)
        overlay["instances"].append(dict(role="analyzer_collision_patch",pa_path="patch.pa",origin_mm=[0,-4,-100]))
        with self.assertRaisesRegex(ValueError,"topology"):
            validate_candidate_binding(overlay,baseline)
        overlay.update(source_descriptor_path="sealed_source.json",collision_overlay=dict(
            schema_version=1,role="mrtof_analyzer_collision_overlay",patch_plan_path="sealed_plan.json"))
        with patch(module+".load_binding",return_value=candidate) as source_loader, \
             patch(module+".native_response_operator",return_value={}):
            self.assertEqual(validate_candidate_binding(overlay,baseline),dict(s1=1,s2=2,p1=3,p2=4))
            source_loader.assert_called_once_with(Path("sealed_source.json"))
            with self.assertRaisesRegex(ValueError,"silently remove"):
                validate_candidate_binding(candidate,overlay)
        with patch(module+".native_response_operator", return_value={}) as operator:
            self.assertEqual(validate_candidate_binding(candidate,baseline),dict(s1=1,s2=2,p1=3,p2=4))
            self.assertEqual(operator.call_count,2)
            candidate["instances"][0]["pa_path"]="old_parent.pa"
            with self.assertRaisesRegex(ValueError,"reuse"):
                validate_candidate_binding(candidate,baseline)
            candidate["instances"][0]["pa_path"]="new_parent.pa"
            candidate["authority"]["component_voltages_v"][0]["value_v"] += 1
            with self.assertRaisesRegex(ValueError,"IP15"):
                validate_candidate_binding(candidate,baseline)
        candidate=copy.deepcopy(baseline)
        with patch(module+".native_response_operator", side_effect=[dict(grid="different"),dict(grid="baseline")]):
            with self.assertRaisesRegex(ValueError,"numerical"):
                validate_candidate_binding(candidate,baseline)


    def test_explicit_slow_turn_reanchor_preserves_spent_budget_and_rejects_other_changes(self):
        import copy
        from msplatform.workflows.mr_design.downstream_workpoint import reanchor_prepared_target
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);old=root/"old.json";new=root/"new.json"
            original=dict(target_slow_turn_y_mm=360,energy=4359.32,source="same")
            old.write_text(json.dumps(original))
            target=dict(original,target_slow_turn_y_mm=340)
            new.write_text(json.dumps(target))
            trial=dict(frozen_problem=dict(source_center_projection="same",static_field_problem="same",
                                           selected_axial_energy_per_charge_v=4359.32))
            state=dict(stage="stripe_preclosure",candidate_count=16,flight_count=51,columns={"0":"old"},
                       attempts=[1],history=["keep"],prism_model_manifest="old",prediction_assessment={})
            saved=copy.deepcopy(state)
            module="msplatform.workflows.mr_design.downstream_workpoint"
            with patch(module+".load_prepared_centroid_trial",return_value=trial):
                reset=reanchor_prepared_target(state,anchor_manifest=old,target_path=new,contract_path=old,previous_target_path=old)
                self.assertEqual((reset["candidate_count"],reset["flight_count"]),(16,51))
                self.assertEqual(reset["history"],["keep"])
                self.assertEqual(reset["columns"],{})
                self.assertEqual(reset["attempts"],[])
                self.assertEqual(state,saved)
                new.write_text(json.dumps(dict(target,target_slow_turn_y_mm=351)))
                alternate=reanchor_prepared_target(state,anchor_manifest=old,target_path=new,contract_path=old,previous_target_path=old)
                self.assertEqual(alternate["flight_count"],51)
                with self.assertRaisesRegex(ValueError,"overwrite existing debit"):
                    reanchor_prepared_target(reset,anchor_manifest=old,target_path=new,contract_path=old,previous_target_path=old)
                for changed in (dict(target,energy=4360),dict(target,source="different"),dict(target,target_slow_turn_y_mm=360)):
                    new.write_text(json.dumps(changed))
                    with self.assertRaises(ValueError):
                        reanchor_prepared_target(state,anchor_manifest=old,target_path=new,contract_path=old,previous_target_path=old)
                new.write_text(json.dumps(target))
            other=copy.deepcopy(trial);other["frozen_problem"]["source_center_projection"]="changed"
            with patch(module+".load_prepared_centroid_trial",side_effect=[trial,other]):
                with self.assertRaisesRegex(ValueError,"source or operator"):
                    reanchor_prepared_target(state,anchor_manifest=old,target_path=new,contract_path=old,previous_target_path=old)


    def test_representation_comparison_preserves_every_prefix_event_and_sample(self):
        from msplatform.execution.retention import file_record
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, manifest = root / "reference.log", root / "reference_manifest.json"
            text = ("MRTOF_TRAJECTORY ion=7 phase=birth t_us=7500.57 x_mm=0.1\n"
                    "MRTOF_EVENT terminal ion=7 t_us=7501.57\n")
            baseline.write_text(text)
            manifest.write_text('{}')
            preparation = root / "preparation.json"
            preparation.write_text(json.dumps(dict(trajectory_equivalence_reference=dict(
                reference_log=file_record(baseline),reference_manifest=file_record(manifest),
                original_particle_ids=[7]))))
            current = root / "current.log"
            current.write_text(text+"MRTOF_EVENT terminal ion=9 t_us=7502\n")
            receipt = root / "equivalence.json"
            result = compare_trajectory_representation(preparation,current,receipt)
            self.assertEqual(result["status"],"pass")
            self.assertEqual(result["compared_line_count"],2)
            self.assertFalse(result["physical_matching_qualified"])
            current.write_text(text.replace("x_mm=0.1","x_mm=0.10000000000000002"))
            with self.assertRaisesRegex(ValueError,"differs"):
                compare_trajectory_representation(preparation,current,receipt)
            failure=json.loads(receipt.read_text())
            self.assertEqual(failure["status"],"fail")
            self.assertEqual(failure["first_mismatches"][0]["selected_line"],1)

    def test_memory_crop_uses_frozen_mirror_policy_without_changing_source(self):
        names = ["positive_integer_grid_a", "negative_integer_grid_a", "covered_local"]
        targets = [dict(pitch_mm=[.04,.2,.04],stored_xmax_mm=1.28),
                   dict(pitch_mm=[.04,.2,.04],stored_xmax_mm=1.28),dict(pitch_mm=[.25,.25,.1])]
        contract = dict(simion=dict(numerical_profiles=dict(native_static_field=dict(target_layout=dict(windows=targets)))))
        reference = dict(field_binding=dict(refinement_windows=[dict(name=name) for name in names]))
        windows = [dict(name=name,grid=dict(origin_mm=[0,-65,z],pitch_mm=[.04,.2,.04],
                       dimensions=[51,2126,11701]),active_box_mm=[[-1,1],[-64.75,359.75],[90.25,323.75]])
                   for name,z in zip(names[:2],[90,-324])]
        binding = dict(refinement_windows=[dict(name="ion_processor_local"),*windows])
        before = json.dumps(binding)
        result = compile_memory_consumer_crops(contract,reference,binding)
        self.assertEqual(json.dumps(binding),before)
        self.assertEqual(set(result),set(names[:2]))
        for descriptor in result.values():
            self.assertEqual(descriptor["source_dimensions"],[51,2126,11701])
            self.assertEqual(descriptor["consumer_dimensions"],[33,2126,11701])
            self.assertEqual(descriptor["width_grid"],[32,2125,11700])
        targets[0]["stored_xmax_mm"]=1.0
        with self.assertRaisesRegex(ValueError,"halo"):
            compile_memory_consumer_crops(contract,reference,binding)


    def test_public_manifest_and_stopped_payload_seal_above_light_budget(self):
        from msplatform.backends.simion.native_completion import apply_retention
        from msplatform.execution.capacity_ledger import initialize_capacity_ledger, load_capacity_ledger
        from msplatform.io.file_identity import file_sha256
        from msplatform.execution.run_capacity_lifecycle import finalize_ready, register_writing, seal_checkpoint
        from msplatform.execution.manifest_publication import build_run_manifest
        for status in ("success", "failed"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                initialize_capacity_ledger(root, objects=[])
                run = root / "projects/p/runs/20261016_200001__sim__simion__payload-fixture"
                run.mkdir(parents=True)
                config = run / "run_config.json"
                config.write_text(json.dumps(dict(schema_version=2,run_id=run.name,project="p",inputs={},
                    artifact_retention=dict(policy_version=1,**{"class":"solver_review"},reason="fixture trajectories"),
                    capacity_ledger_lifecycle=dict(schema_version=1,enabled=True,artifact_root=str(root),
                                                  light_evidence_budget_bytes=26214400))))
                summary = run / "summary.json"
                summary.write_text(json.dumps(dict(status=status)))
                register_writing(root,config)
                payload = run / "trajectory_samples.csv"
                with payload.open("wb") as handle:
                    handle.truncate(26214401)
                retained = apply_retention(config)
                manifest = run / "run_manifest.json"
                manifest.write_text(json.dumps(build_run_manifest(config,status,
                    output_paths=[summary,payload,retained], retention_api=_manifest_retention_api)))
                verify = subprocess.run([sys.executable,"-c", "from msplatform.execution.manifest_verification import main; from msplatform.backends.simion.native_completion import retention_api; main(retention_api=retention_api)",str(manifest),
                                         "--require-status",status],capture_output=True,text=True,
                                        cwd=Path(__file__).resolve().parents[4],timeout=60,
                                        encoding="utf-8",errors="replace",check=False)
                self.assertEqual(verify.returncode,0,verify.stdout+verify.stderr)
                identity = file_sha256(manifest)
                with self.assertRaisesRegex(ValueError,"cannot become light_evidence"):
                    finalize_ready(root,config)
                with self.assertRaises(ValueError):
                    seal_checkpoint(root,config,owner="wrong",writing_stopped=True,retain_payload=True,
                                    retention_reason="fixture trajectories")
                self.assertEqual(file_sha256(manifest),identity)
                receipt = seal_checkpoint(root,config,owner="p",writing_stopped=True,retain_payload=True,
                                          retention_reason="fixture trajectories")
                self.assertEqual(receipt["status"],"ready")
                entry = load_capacity_ledger(root)["objects"][0]
                self.assertEqual(entry["class"],"rebuildable_payload")
                self.assertEqual(entry["status"],"ready")
                self.assertGreater(entry["bytes"],26214400)
                self.assertEqual(file_sha256(manifest),identity)
                self.assertEqual(json.loads(manifest.read_text())["status"],status)

    def test_merge_preserves_noncontiguous_original_ids_and_absolute_clock(self):
        from msplatform.execution.retention import file_record
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preparation = root / "preparation.json"
            preparation.write_text(json.dumps(dict(expected_particle_ids=[1,7],mother_particle_count=3,
                                                   solver_epoch_instrument_time_us=7500.5)))
            batches = []
            for ordinal, identifier in enumerate([1,7], 1):
                batch_dir = root / f"batch{ordinal}"
                batch_dir.mkdir()
                log, receipt = batch_dir / "flight.log", batch_dir / "batch_receipt.json"
                fly = batch_dir / "joint.fly2"
                fly.write_text("particles { standard_beam { tob = 0.01, } }")
                log.write_text(f"MRTOF_TRAJECTORY ion={identifier} phase=birth t_us=7500.51\n"
                               f"MRTOF_EVENT terminal ion={identifier} t_us=7501.5 splat=-1\n"
                               "status,Fly completed. 1 splats\n")
                receipt.write_text(json.dumps(dict(schema_version=1, role="mrtof_measured_source_batch",
                                                   outputs=dict(source=file_record(fly)), count=1,original_particle_ids=[identifier],
                                                   solver_epoch_instrument_time_us=7500.5)))
                batches.append((log,receipt))
            result = merge_measured_event_logs(batches=batches, preparation_path=preparation,
                                               output_path=root/"merged.log", receipt_path=root/"merged.json")
            self.assertEqual(result["original_particle_ids"], [1,7])
            self.assertEqual(result["mother_particle_count"], 3)
            self.assertFalse(result["id_rebasing_applied"])
            self.assertEqual(result["preparation"], file_record(preparation))
            self.assertEqual(len(result["batches"]), 2)
            self.assertTrue(all("fly2" in row for row in result["batches"]))
            self.assertIn("ion=7 t_us=7501.5", (root/"merged.log").read_text())
            for changed in ("wrong_id", "missing_terminal", "wrong_epoch", "duplicate_batch"):
                with self.subTest(changed=changed):
                    log, receipt = batches[-1]
                    original_log, original_receipt = log.read_text(), receipt.read_text()
                    selected = batches
                    if changed == "wrong_id":
                        log.write_text(original_log.replace("ion=7", "ion=2"))
                    elif changed == "missing_terminal":
                        log.write_text(original_log.replace("MRTOF_EVENT terminal", "IGNORED terminal"))
                    elif changed == "wrong_epoch":
                        value=json.loads(original_receipt); value["solver_epoch_instrument_time_us"]=7500.6
                        receipt.write_text(json.dumps(value))
                    else:
                        selected = [batches[0],batches[0]]
                    with self.assertRaises(ValueError):
                        merge_measured_event_logs(batches=selected,preparation_path=preparation,
                                                  output_path=root/"bad.log",receipt_path=root/"bad.json")
                    log.write_text(original_log); receipt.write_text(original_receipt)
            fly = batches[-1][1].parent / "joint.fly2"
            original = fly.read_bytes()
            for content in (b"tampered", None):
                if content is None:
                    fly.unlink()
                else:
                    fly.write_bytes(content)
                with self.assertRaisesRegex(AssertionError, "actual launched batch FLY2"):
                    merge_measured_event_logs(batches=batches, preparation_path=preparation,
                                             output_path=root/"bad.log", receipt_path=root/"bad.json")
                fly.write_bytes(original)
