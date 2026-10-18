"""Pure PowerShell regression for completed-flight publication recovery."""

from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[4]
RUNNER = REPO / "projects/parallel_mirror_dual_stripe_mr_tof/analysis/run_recover_completed_bunch_flight.ps1"


class CompletedBunchRecoveryTests(unittest.TestCase):
    def run_ps(self, script: str) -> dict:
        shell = shutil.which("pwsh")
        if shell is None:
            self.skipTest("PowerShell 7 is required")
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(REPO) + os.pathsep + environment.get("PYTHONPATH", "")
        unintended = REPO / "System.Collections.Hashtable"
        before = unintended.read_bytes() if unintended.exists() else None
        # Public helpers and native child commands resolve inputs absolutely.
        # Unexpected relative outputs must remain isolated even when a fixture
        # fails before its assertions or terminal manifest can be published.
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [shell, "-NoProfile", "-Command", script], text=True,
                capture_output=True, encoding="utf-8", errors="replace", timeout=90,
                check=False, cwd=directory, env=environment,
            )
            self.assertEqual(list(Path(directory).iterdir()), [],
                             "Recovery fixture wrote an unintended relative output")
        after = unintended.read_bytes() if unintended.exists() else None
        self.assertEqual(after, before, "Recovery fixture changed a repository-root output")
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        import json
        return json.loads(completed.stdout.strip().splitlines()[-1])

    def test_public_json_helper_named_arguments_do_not_capture_path_as_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "retention_actions.json"
            result = self.run_ps(f"""
            . '{(REPO / 'common/contracts/run_artifact_support.ps1').as_posix()}'
            function Write-FixtureRetention {{
              $fixtureRetentionPath='{output.as_posix()}'
              Write-RunJson -Path $fixtureRetentionPath -Value @{{retained=$true}}
              return $fixtureRetentionPath
            }}
            $written=Write-FixtureRetention
            if($written-ne'{output.as_posix()}'){{throw 'Retention path was captured'}}
            if(Test-Path -LiteralPath 'System.Collections.Hashtable'){{throw 'Hashtables became paths'}}
            @{{retained=(Get-Content -LiteralPath $written -Raw|ConvertFrom-Json).retained}}|ConvertTo-Json -Compress
            """)
            self.assertEqual(result, {"retained": True})
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ["retention_actions.json"])

    def functions(self) -> str:
        return f"""
        $errors=$null;$tokens=$null
        $ast=[Management.Automation.Language.Parser]::ParseFile('{RUNNER.as_posix()}',[ref]$tokens,[ref]$errors)
        if($errors.Count){{throw 'Runner AST invalid'}}
        foreach($node in $ast.FindAll({{param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]}},$true)){{
          if($node.Name-in@('Assert-CompletedBunchRecovery','Restore-CompletedBunchGui','Assert-PreparedJointRecovery','Copy-PreparedRecoveryRecord','Get-VerifiedSourceOutput','Invoke-PreparedJointRecovery')){{Invoke-Expression $node.Extent.Text}}
        }}
        """

    def test_completed_only_postanalysis_and_dispatch_admission(self) -> None:
        result = self.run_ps(self.functions() + """
        $plan=[pscustomobject]@{coverage='complete_population';particle_count=100}
        $complete=[pscustomobject]@{cohort_analysis=[pscustomobject]@{event_integrity_passed=$true;expected_particle_count=100}}
        $cases=@(
          @('plan_bunch_dispatch',$plan,$null,$true),
          @('analyze_trial',$plan,$complete,$true),
          @('native_two_prism_flight',$plan,$complete,$false),
          @('analyze_trial',$plan,$null,$false),
          @('analyze_trial',[pscustomobject]@{coverage='partial';particle_count=100},$complete,$false),
          @('analyze_trial',[pscustomobject]@{coverage='complete_population';particle_count=99},$complete,$false)
        )
        foreach($case in $cases){
          $passed=$true
          try{Assert-CompletedBunchRecovery ([pscustomobject]@{failure_stage=$case[0]}) $case[1] $case[2]}catch{$passed=$false}
          if($passed-ne$case[3]){throw "Wrong admission for $($case[0])"}
        }
        @{scenarios=$cases.Count;passed=$true}|ConvertTo-Json -Compress
        """)
        self.assertEqual(result, {"scenarios": 6, "passed": True})

    def test_prepared_admission_requires_completed_merge_and_original_ids(self) -> None:
        result = self.run_ps(self.functions() + """
        $summary=@{status='failed';failure_stage='automatic_joint_diagnostics'}
        $prepared=@{role='mrtof_prepared_joint_trial';launched_particle_count=2;mother_particle_count=3;expected_particle_ids=@(1,7)}
        $plan=@{coverage='complete_population';particle_count=2}
        $merge=@{role='mrtof_measured_batch_log_merge';status='success';particle_count=2;mother_particle_count=3;original_particle_ids=@(1,7)}
        Assert-PreparedJointRecovery $summary $prepared $plan $merge
        $cases=@(@('summary','failure_stage','native_two_prism_flight'),@('plan','coverage','partial'),
          @('merge','particle_count',1),@('merge','mother_particle_count',2),@('merge','original_particle_ids',@(1,2)))
        foreach($case in $cases){
          $target=Get-Variable -Name $case[0] -ValueOnly;$old=$target[$case[1]];$target[$case[1]]=$case[2]
          $rejected=$false
          try{Assert-PreparedJointRecovery $summary $prepared $plan $merge}catch{$rejected=$true}
          $target[$case[1]]=$old;if(-not$rejected){throw 'Incomplete source was accepted'}
        }
        @{passed=$true;rejections=$cases.Count}|ConvertTo-Json -Compress
        """)
        self.assertEqual(result, {"passed": True, "rejections": 5})

    def test_prepared_recovery_runs_real_merge_diagnostics_equivalence_and_manifest(self) -> None:
        from common.contracts.write_run_manifest import build_run_manifest, file_record
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.measured_component_source import materialize_measured_source_slice
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mrtof_batch_flight import merge_measured_event_logs
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_prepared_joint_diagnostics import PreparedJointDiagnosticsTests
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_static_field_binding import IonProcessorNativeBindingTest
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding import load_binding
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.standalone_pa_composition import PaHeader

        fixture = PreparedJointDiagnosticsTests("test_initialize_zero_clock_projects_only_birth_in_full_pipeline")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        root = fixture.root
        # The recovery CLI is a separate Python process: the in-process geometry
        # mock in the diagnostics unit fixture cannot authorize its field input.
        # Reuse the complete small IP binding/assembly fixture and seal real
        # records. These zero-field assets exercise loading, not solver physics.
        assets = root / "native_binding"
        assets.mkdir()
        native_fixture = IonProcessorNativeBindingTest()
        descriptor, binding_path, owner = native_fixture.fixture(assets, detector_box=[20,20,20,21,21,21])
        frame = json.loads((fixture.source / "source_receipt.json").read_text())["frame_id"]
        geometry_path = assets / "assembly_geometry.json"
        geometry = json.loads(geometry_path.read_text())
        geometry.update(frame_id=frame, detector=dict(id=25,box=[20,20,20,21,21,21]))
        for key in ("mirror_electrodes", "mirror_slot", "mirror_inner_shield_slot", "mirror_ground_shields",
                    "mirror_e_closures", "stripe_electrodes", "stripe_slot", "central_ground_electrodes",
                    "central_ground_slots", "prism_electrodes", "prism_ground_shields"):
            geometry[key] = []
        geometry_path.write_text(json.dumps(geometry))
        replacement_path = assets / "replacement.json"
        replacement = json.loads(replacement_path.read_text())
        replacement["assembly_coordinate_transform"]["to_frame_id"] = frame
        replacement_path.write_text(json.dumps(replacement))
        design_owner = assets / "design_manifest.json"
        design_owner.write_text(json.dumps(dict(status="success", outputs=[file_record(path)
            for path in (replacement_path,assets/"point.json",geometry_path)])))
        descriptor["replacement_assembly"] = file_record(replacement_path)
        for level in (descriptor["parent"],*descriptor["refinement_windows"]):
            Path(level["geometry_authority_path"]).write_text(json.dumps(geometry))
            path = Path(level["voltage_authority_path"])
            authority = json.loads(path.read_text())
            authority["assembly"].update(detector=geometry["detector"],
                ion_processor_registration=replacement["assembly_coordinate_transform"],
                replacement_assembly=file_record(replacement_path), replacement_assembly_manifest=file_record(design_owner))
            path.write_text(json.dumps(authority))
        for instance in descriptor["instances"]:
            header = PaHeader(-2,1,100000.,11,11,11,1,.5,1.,1.)
            Path(instance["pa_path"]).write_bytes(header.pack()+b"\0"*(header.node_count*8))
        binding_path.write_text(json.dumps(descriptor))
        native_fixture.seal(assets,owner)
        # No load_binding or diagnostics patch is installed in the subprocess.
        self.assertEqual(load_binding(binding_path)["geometry"]["frame_id"],frame)
        source = root / "failed"
        results, logs = source / "results", source / "logs"
        results.mkdir(parents=True)
        logs.mkdir()
        shutil.copytree(fixture.source, results / "measured_source")
        prepared = dict(fixture.prepared, launched_particle_count=2,
                        measured_source_directory=str(results / "measured_source"),
                        source_receipt=file_record(results / "measured_source/source_receipt.json"),
                        field_binding=file_record(binding_path))
        pairs = []
        epoch = prepared["solver_epoch_instrument_time_us"]
        for index, particle in enumerate((1, 7), 1):
            batch = results / f"batches/batch_{index:03d}"
            batch.mkdir(parents=True)
            receipt = materialize_measured_source_slice(fixture.source, batch / "measured_source", index, index)
            shutil.copyfile(batch / "measured_source/source.fly2", batch / "joint.fly2")
            receipt_path = batch / "batch_receipt.json"
            receipt_path.write_text(json.dumps(receipt))
            lines = [line for line in fixture.original_lines if f"ion={particle} " in line]
            lines[0] = lines[0].replace(lines[0].split("t_us=")[1].split()[0], f"{epoch:.17g}", 1)
            log = logs / f"joint_flight_batch_{index:03d}.log"
            log.write_text("\n".join(lines)+"\nstatus,Fly completed. 1 splats\n")
            pairs.append((log, receipt_path))
        baseline = root / "baseline.log"
        baseline_manifest = root / "baseline_manifest.json"
        baseline_manifest.write_text("{}")
        prepared["trajectory_equivalence_reference"] = dict(reference_log=file_record(baseline_manifest),
            reference_manifest=file_record(baseline_manifest), original_particle_ids=[1])
        preparation = results / "prepared_joint_trial.json"
        preparation.write_text(json.dumps(prepared))
        merged = logs / "native_two_prism_flight.log"
        merge_measured_event_logs(batches=pairs, preparation_path=preparation, output_path=merged,
                                 receipt_path=results / "batch_log_merge_receipt.json")
        shutil.copyfile(merged, baseline)
        prepared["trajectory_equivalence_reference"]["reference_log"] = file_record(baseline)
        preparation.write_text(json.dumps(prepared))
        (results / "simion_execution_batch_plan.json").write_text(json.dumps(dict(
            coverage="complete_population", particle_count=2, batches=[dict(index=1), dict(index=2)])))
        (source / "summary.json").write_text(json.dumps(dict(status="failed", failure_stage="automatic_joint_diagnostics")))
        config = source / "run_config.json"
        config.write_text(json.dumps(dict(run_id="20261016_210000__sim__simion__recovery-fixture", project="parallel_mirror_dual_stripe_mr_tof", inputs={})))
        (source / "run_manifest.json").write_text(json.dumps(build_run_manifest(config, "failed",
            output_paths=[p for p in source.rglob("*") if p.is_file() and p != config])))
        recovery = root / "recovered"
        result = self.run_ps(f"""
        . '{(REPO / 'common/contracts/run_artifact_support.ps1').as_posix()}'
        """ + self.functions() + f"""
        $ErrorActionPreference='Stop';Set-StrictMode -Version Latest
        $repoRoot='{REPO.as_posix()}';$workspaceRoot='{root.as_posix()}';$python='{Path(sys.executable).as_posix()}'
        $sourceRun='{source.as_posix()}';$sourceManifest=Join-Path $sourceRun 'run_manifest.json'
        $RunId='20261016_210001__analysis__python__recovery-fixture';$projectId='parallel_mirror_dual_stripe_mr_tof'
        function New-RunPackage {{
          param($Python,$RepoRoot,$ArtifactRoot,$RunId,$Project,$Mode,$Software,[switch]$RetentionContractEnabled,$RetentionClass,$RetentionReason,[switch]$CapacityLedgerLifecycleEnabled)
          $r='{recovery.as_posix()}';$i=Join-Path $r 'inputs';$o=Join-Path $r 'results';$l=Join-Path $r 'logs'
          New-Item -ItemType Directory -Path $i,$o,$l|Out-Null
          $c=Join-Path $r 'run_config.json';Write-RunJson -Path $c -Value @{{run_id=$RunId;project=$Project;inputs=@{{}}}}
          return @{{artifact_run_dir=$r;input_dir=$i;result_dir=$o;log_dir=$l;run_config=$c;summary=(Join-Path $r 'summary.json')}}
        }}
        function Enter-ArtifactWorkflowCapacitySession {{return @{{status='active'}}}}
        function Exit-ArtifactWorkflowCapacitySession {{$script:released=$true}}
        function Enter-HostExecutionLease {{param($Role) if($Role-ne'GATE'){{throw 'Commercial lease forbidden'}};return @{{role=$Role}}}}
        function Exit-HostExecutionLease {{}}
        function Restore-CompletedBunchGui {{throw 'Prepared recovery must never rebuild GUI'}}
        function Apply-RunArtifactRetention {{
          $p='{(recovery / 'retention_actions.json').as_posix()}';Write-RunJson -Path $p -Value @{{retained=$true}};return $p
        }}
        function Invoke-RunToolRootContext {{
          param($RepoRoot,$Operation)
          if($Operation.ToString()-match'common.contracts.run_capacity_lifecycle'){{
            if(-not$script:released){{throw 'Capacity not released before seal'}}
            $script:sealed=$true;return
          }}
          & $Operation
        }}
        Invoke-PreparedJointRecovery
        if(-not$script:sealed){{throw 'Missing stopped-payload seal'}}
        $m=Get-Content '{(recovery / 'run_manifest.json').as_posix()}' -Raw|ConvertFrom-Json
        if($m.status-ne'success'){{throw 'Public manifest did not publish success'}}
        @{{status=$m.status;sealed=$script:sealed}}|ConvertTo-Json -Compress
        """)
        self.assertEqual(result, {"status": "success", "sealed": True})
        self.assertEqual(merged.read_bytes(), (recovery / "logs/native_two_prism_flight.log").read_bytes())
        proof = json.loads((recovery / "results/prepared_joint_trial.json").read_text(encoding="utf-8-sig"))
        recovered_binding = Path(proof["field_binding"]["path"])
        self.assertEqual(recovered_binding.read_bytes(),binding_path.read_bytes())
        self.assertEqual(load_binding(recovered_binding)["geometry"],geometry)
        self.assertEqual(len(proof["completed_source_batches"]), 2)
        self.assertTrue(all(Path(b["fly2"]["path"]).is_file() for b in proof["completed_source_batches"]))
        self.assertTrue((recovery / "results/diagnostics/birth_clock_projection.json").is_file())
        comparison = json.loads((recovery / "results/trajectory_equivalence_receipt.json").read_text())
        self.assertEqual(comparison["status"], "pass")
        self.assertFalse(comparison["physical_matching_qualified"])

    def test_gui_reuses_small_companions_and_registers_light_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory)
            source = task / "source/simion/gui_workbench"
            source.mkdir(parents=True)
            for name in (
                "4_instance_seed.iob", "mrtof_three_component_candidate.iob",
                "mrtof_three_component_candidate.lua", "mrtof_three_component_candidate.fly2",
                "mrtof_three_component_candidate.priority.lua",
                "mrtof_three_component_candidate.operating_point.lua",
                "mrtof_three_component_candidate.voltage_map.lua",
            ):
                (source / name).write_text("fixture", encoding="utf-8")
            (source / "never_copy.pa").write_bytes(b"not a recovery input")
            script = self.functions().replace(
                "Invoke-Expression $node.Extent.Text",
                "Invoke-Expression ($node.Extent.Text.Replace('[Diagnostics.Process]::Start($start)','(Start-FakeRecoveryBuilder $start)'))",
            )
            result = self.run_ps(script + f"""
            $repoRoot='{REPO.as_posix()}'
            function Copy-VerifiedRunInput($Source,$Destination){{Copy-Item -LiteralPath $Source -Destination $Destination;return $Destination}}
            function Enter-HostExecutionLease($Role,$RunId,$Stage){{
              if($Role-ne'SIMION'-or$Stage-ne'rebind_retained_gui_iob'){{throw 'Wrong light stage'}}
              return @{{role=$Role;stage=$Stage}}
            }}
            function Register-HostResourceProcess($Lease,$ProcessId){{$script:registered=$ProcessId}}
            function Exit-HostExecutionLease($Lease,$Outcome,$RunId){{$script:outcome=$Outcome}}
            function Remove-IobSeedPlaceholderCompanions($Directory,$Count){{
              foreach($index in 1..$Count){{Remove-Item -LiteralPath (Join-Path $Directory ('iob_seed_placeholder_{{0:D2}}.pa0'-f$index))}}
            }}
            function Write-RunJson($Path,$Depth,$Value){{$script:receipt=$Value}}
            function Start-FakeRecoveryBuilder($Start){{
              $script:arguments=@($Start.ArgumentList)
              if(@($script:arguments|Where-Object{{$_-in@('fly','refine')}}).Count){{throw 'Recovery invoked physics'}}
              $pipe=[pscustomobject]@{{}}
              $pipe|Add-Member ScriptMethod ReadToEndAsync {{return [Threading.Tasks.Task]::FromResult('MRTOF_NATIVE_CORRIDOR_IOB_BUILD=PASS')}}
              $p=[pscustomobject]@{{Id=123;HasExited=$false;ExitCode=0;StandardOutput=$pipe;StandardError=$pipe}}
              $p|Add-Member ScriptMethod WaitForExit {{$this.HasExited=$true}}
              $p|Add-Member ScriptMethod Dispose {{}}
              return $p
            }}
            $binding=[pscustomobject]@{{instances=@(
              [pscustomobject]@{{pa_path='parent.pa';origin_mm=@(0,-242,-425)}},
              [pscustomobject]@{{pa_path='collision.pa0';origin_mm=@(0,-242,-425)}},
              [pscustomobject]@{{pa_path='oa.pa0';origin_mm=@(0,-72.25,-6)}},
              [pscustomobject]@{{pa_path='detector.pa';origin_mm=@(-32,-94,92)}}
            );records=[pscustomobject]@{{scalar_pa=@{{path='parent.pa'}}}};refinement_windows=@()}}
            Restore-CompletedBunchGui -SourceDirectory '{(task / 'source').as_posix()}' -DestinationDirectory '{(task / 'gui').as_posix()}' `
              -ResultDirectory '{task.as_posix()}' -LogDirectory '{task.as_posix()}' -RecoveryRunId fixture -Binding $binding
            if(Test-Path '{(task / 'gui/never_copy.pa').as_posix()}'){{throw 'PA was copied'}}
            if($script:registered-ne123-or$script:outcome-ne'success'){{throw 'Lease lifecycle incomplete'}}
            if($script:receipt.files.Count-ne7){{throw 'Small companion count changed'}}
            @{{registered=$script:registered;outcome=$script:outcome;arguments=$script:arguments.Count}}|ConvertTo-Json -Compress
            """)
            self.assertEqual(result["registered"], 123)
            self.assertEqual(result["outcome"], "success")
            self.assertEqual(result["arguments"], 28)


if __name__ == "__main__":
    unittest.main()
