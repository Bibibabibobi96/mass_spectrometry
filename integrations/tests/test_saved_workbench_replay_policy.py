"""Saved-workbench qualification is an explicit action, separate from scientific flight."""
from pathlib import Path
import json
import tempfile
import shutil
import subprocess
import sys
import unittest

from integrations.tests.test_local_frontend_workflow import fixture as local_fixture
from integrations.tests.test_cooled_frontend import cooled_request_fixture
from integrations.workflows.local_frontend.prepare import prepare_local_frontend
from integrations.workflows.cooled_frontend.prepare import prepare_cooled_frontend

REPO = Path(__file__).resolve().parents[2]
FRONTEND = REPO/"integrations/runtime/frontend_flight_support.ps1"


class SavedWorkbenchReplayPolicyTests(unittest.TestCase):
    def test_local_default_and_explicit_actions_do_not_change_field_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, request = local_fixture(root)
            original = path.read_bytes()
            normal = prepare_local_frontend(path, None, root)
            self.assertFalse(normal["default_replay_requested"])
            request["verify_saved_workbench_replay"] = True
            path.write_text(json.dumps(request), encoding="utf-8")
            explicit = prepare_local_frontend(path, None, root)
            self.assertTrue(explicit["default_replay_requested"])
            self.assertEqual(normal["cache_physical_inputs"], explicit["cache_physical_inputs"])
            request["verify_saved_workbench_replay"] = "false"
            path.write_text(json.dumps(request), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be a boolean"):
                prepare_local_frontend(path, None, root)
            self.assertNotEqual(path.read_bytes(), original)


    def test_cooled_default_and_explicit_actions_do_not_change_member_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, request = cooled_request_fixture(root)
            normal = prepare_cooled_frontend(path, None, REPO, root)
            self.assertFalse(normal["default_replay_requested"])
            request["verify_saved_workbench_replay"] = True
            path.write_text(json.dumps(request), encoding="utf-8")
            explicit = prepare_cooled_frontend(path, None, REPO, root)
            self.assertTrue(explicit["default_replay_requested"])
            self.assertEqual(normal["field_plan"], explicit["field_plan"])
            request["verify_saved_workbench_replay"] = 1
            path.write_text(json.dumps(request), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be a boolean"):
                prepare_cooled_frontend(path, None, REPO, root)


    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell unavailable")
    def test_actual_public_replay_boundary_launch_counts_and_explicit_failure(self):
        code = r"""param($Repo,$Source,$Root,$Python)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-FrontendDefaultReplay'},$true)
Invoke-Expression $node.Extent.Text
function Write-RunJson {param($Path,$Value,$Depth)New-Item -ItemType Directory -Path (Split-Path -Parent $Path) -Force|Out-Null;$Value|ConvertTo-Json -Depth 100|Set-Content $Path}
function Get-RunNativeExecutionContext {param($Package,$Paths,$Tool)@{run_dir=$run;projected_paths=$Paths;environment=@{}}}
function Project-RunPath {param($Paths,$ArtifactRunDir,$RunDir,$Python)return $Paths}
function Get-HostResourceBudget {param($Role,$Stage)@{}}
function Update-HostResourceStage {param($Lease,$Stage,$Budget,$RetainedMemoryBytes)@{stage=$Stage}}
function Invoke-ResourceBudgetedProcess {param($Limits,$RunDir,$FilePath,$ArgumentList,$WorkingDirectory,$Environment,$UsagePath,$RedirectStandardOutput,$RedirectStandardError)
 $script:native++
 if(($ArgumentList-join'|')-ne'--nogui|--noprompt|fly|local.iob'){throw 'saved defaults changed'}
 @{resource_budget_exceeded=$false;exit_code=0}
}
function Invoke-FrontendRuntimePython {param($Python,$RepoRoot,$RunDirectory,$Name,$Arguments,[switch]$Json)
 if($Name-eq'saved_controls_verify'){$script:controls++;return @{scope='saved_controls_only';native_fly_performed=$false;controls_verified=$true}}
 if($Name-eq'default_replay_prepare'){return @{working_directory=$run;argument_list=@('--nogui','--noprompt','fly','local.iob');control_records=@();environment=@{};usage_path=(Join-Path $run usage.json);stdout=(Join-Path $run stdout.log);stderr=(Join-Path $run stderr.log)}}
 if($Name-eq'default_replay_compare'){return @{passed=($scenario-ne'mismatch')}}
 throw "Unexpected action $Name"
}
foreach($scenario in @('normal','explicit','mismatch','stochastic')){
 $run=Join-Path $Root $scenario;New-Item -ItemType Directory -Path $run|Out-Null
 $script:native=0;$script:controls=0
 $policy=@{scope=$(if($scenario-eq'normal'){'not_requested'}elseif($scenario-eq'stochastic'){'saved_controls_only'}else{'fresh_process'});comparison_policy=$(if($scenario-eq'stochastic'){'independent_stochastic_collisions'}else{'deterministic_trajectory_parity'})}
 $case=@{iob_path=(Join-Path $run local.iob);expected_particle_ids=@(1,2,3)}
 $materialized=@{receipt_path=(Join-Path $run materialization.json);gui_case=$case;batches=@(@{stdout=(Join-Path $run baseline.log)});default_replay_policy=$policy}
 $package=[pscustomobject]@{artifact_run_dir=$run;python=$Python};$lease=@{}
 $caughtFailure=$null
 try{$result=Invoke-FrontendDefaultReplay -Materialized $materialized -HostLease ([ref]$lease) -RunDirectory $run -RepoRoot $Repo -Python $Python -SimionExe INERT -Limits @{}}catch{$caughtFailure=$_}
 if($scenario-eq'mismatch'){
  if($null-eq$caughtFailure-or$caughtFailure.Exception.Message-notlike'*differs from scheduled mother evidence*'){throw 'explicit failure did not propagate'}
 }elseif($caughtFailure){throw $caughtFailure}
 $expected=if($scenario-in@('explicit','mismatch')){1}else{0}
 if($script:native-ne$expected){throw "Unexpected native count: $scenario $script:native"}
 if($scenario-eq'normal'){
  if($result.status-ne'not_requested'-or$result.native_fly_performed-or(Test-Path (Join-Path $run inputs/default_replay_gui_case.json))){throw 'unrequested replay performed preparation'}
 }
 if($scenario-eq'stochastic'-and($script:controls-ne1-or$result.scope-ne'saved_controls_only'-or$result.native_fly_performed)){throw 'stochastic controls policy changed'}
}
"""
        with tempfile.TemporaryDirectory() as temporary:
            script = Path(temporary)/"check.ps1"
            script.write_text(code, encoding="utf-8", newline="\n")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(REPO),
                str(FRONTEND), temporary, sys.executable],
                cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
