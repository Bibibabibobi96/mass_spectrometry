"""Exercise the production stencil dispatcher without invoking a solver."""
from pathlib import Path
import hashlib
import json
import io
import re
from contextlib import redirect_stdout
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[2]


class WorkpointBootstrapTests(unittest.TestCase):
    def test_restored_stage_axes_keep_original_profile_and_stage_boundaries(self):
        script = r'''
param($Source,$Python,$RepoRoot)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
foreach($name in @('Invoke-WorkpointControllerRequest','Get-ActiveStripeAxisIndices','Get-StagedColumnAxisIndices')){
 $node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true);Invoke-Expression $node.Extent.Text
}
$cases=[Console]::In.ReadToEnd()|ConvertFrom-Json -AsHashtable -Depth 100
$results=@();foreach($case in $cases){try{$axes=@(Get-StagedColumnAxisIndices -Stage $case.stage -Profile $case.profile);$results+=,@{axes=$axes;failed=$false}}catch{$results+=,@{axes=$null;failed=$true}}}
$results|ConvertTo-Json -Depth 10 -Compress
'''
        single = dict(active_stripe_axes=['stripe_1_voltage_v'])
        dual = dict(active_stripe_axes=['stripe_1_voltage_v', 'stripe_2_voltage_v'])
        cases = [('prism_preclosure', {}, [2, 3]), ('stripe_preclosure', single, [0]),
                 ('stripe_preclosure', dual, [0, 1]),
                 ('stripe_preclosure', dict(single, single_stripe_refinement_mode='joint_ps_constrained'), [0, 2, 3]),
                 ('stripe_preclosure', dict(dual, single_stripe_refinement_mode='joint_ps_constrained'), None),
                 ('stripe_preclosure', dict(single, single_stripe_refinement_mode='other'), None),
                 ('PRISM_PRECLOSURE', {}, [2, 3]), ('saved_unknown_stage', single, [0]),
                 ('stripe_preclosure', dict(active_stripe_axes=['STRIPE_1_VOLTAGE_V']), [-1])]
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'axes.ps1'; path.write_text(script, encoding='utf-8')
            process = subprocess.run(['pwsh', '-NoProfile', '-File', str(path),
                str(PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1'), sys.executable, str(PROJECT.parents[1])],
                input=json.dumps([dict(stage=stage, profile=profile) for stage, profile, _ in cases]),
                cwd=PROJECT.parents[1], capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertEqual(json.loads(process.stdout), [dict(axes=expected, failed=expected is None) for _, _, expected in cases])

    def test_main_iteration_budget_keeps_actual_terminal_and_pending_recovery_boundaries(self):
        script = r'''
param($Source,$Root,$Python,$RepoRoot)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$sourceText=Get-Content -LiteralPath $Source -Raw
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-WorkpointControllerRequest'},$true);Invoke-Expression $node.Extent.Text
$start=$sourceText.IndexOf('  $maximumIterations =');$end=$sourceText.IndexOf('  if($null-eq$terminalDecision-and$null-ne$pendingRecoveryDecision)', $start)
$initial=$sourceText.Substring($start,$end-$start)
$post=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and$n.Extent.Text.StartsWith('if ($null -eq $terminalDecision)')-and($n.Extent.Text.Contains('iteration=$maximumFlightAttempts')-or$n.Extent.Text.Contains("phase='exhausted'"))},$true)
$loop=$ast.Find({param($n)$n-is[Management.Automation.Language.ForStatementAst]-and$n.Extent.Text.StartsWith('for ($iteration = $startIteration;')},$true)
$loopHeader=$loop.Extent.Text.Substring(0,$loop.Body.Extent.StartOffset-$loop.Extent.StartOffset)
$frozenContract=Join-Path $Root 'contract.json'
@{downstream_fixed_grid_workpoint_profile=@{automatic_iteration=@{maximum_iterations=8}}}|ConvertTo-Json -Depth 10|Set-Content $frozenContract
$cases=[Console]::In.ReadToEnd()|ConvertFrom-Json -AsHashtable
$results=@();foreach($case in $cases){
 $terminalDecision=$case.terminal;$priorTerminal=$terminalDecision;$startIteration=$case.start;$pendingRecoveryDecision=@{identity='pending-recovery'}
 Invoke-Expression $initial
 $before=$terminalDecision
 $flights=@();Invoke-Expression ($loopHeader+'{ $flights+=,$iteration }')
 if($case.complete){Invoke-Expression $post.Extent.Text}
 $sameIdentity=if($null-ne$priorTerminal){[object]::ReferenceEquals($priorTerminal,$terminalDecision)}else{$null}
 $results+=,@{before=$before;after=$terminalDecision;maximum=$maximumFlightAttempts;flights=$flights;pending=$pendingRecoveryDecision;same_identity=$sameIdentity}
}
$results|ConvertTo-Json -Depth 20 -Compress
'''
        prior = dict(state='terminal', terminal_reason='existing_scientific_decision', iteration=2)
        cases = [(1, None, False), (8, None, False), (9, None, False), (12, None, False),
                 (12, prior, False), (1, None, True), (8, None, True), (9, None, True), (1, prior, True)]
        def terminal(iteration):
            return dict(schema_version=1, role='mrtof_downstream_workpoint_iteration_decision', state='terminal',
                        terminal_reason='maximum_iterations', iteration=iteration,
                        detail='maximum main real centre-flight count 8 reached')
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'budget.ps1'; path.write_text(script, encoding='utf-8')
            process = subprocess.run(['pwsh', '-NoProfile', '-File', str(path),
                str(PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1'), directory, sys.executable, str(PROJECT.parents[1])],
                input=json.dumps([dict(start=start, terminal=value, complete=complete) for start, value, complete in cases]),
                cwd=PROJECT.parents[1], capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            for result, (start, value, complete) in zip(json.loads(process.stdout), cases, strict=True):
                before = value if value is not None else terminal(start - 1) if start > 8 else None
                after = terminal(8) if complete and before is None else before
                self.assertEqual(result, dict(before=before, after=after, maximum=8,
                                             flights=list(range(start, 9)) if before is None else [],
                                             pending=dict(identity='pending-recovery'), same_identity=True if value is not None else None))

    def test_recovery_model_completion_preserves_provisional_policy_and_save_order(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.workpoint_controller_state import (
            prepare_recovery_state, advance_recovery_round,
        )
        script = r'''
param($Source,$Root,$RealPython,$RealRepo)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-SLocalModelRecovery'},$true);Invoke-Expression $node.Extent.Text
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-WorkpointControllerRequest'},$true)
Invoke-Expression ($node.Extent.Text.Replace('function Invoke-WorkpointControllerRequest','function Invoke-RealControllerRequest'))
function Invoke-WorkpointControllerRequest {param($Request,$Python,$RepoRoot)Invoke-RealControllerRequest -Request $Request -Python $RealPython -RepoRoot $RealRepo}
$cases=[Console]::In.ReadToEnd()|ConvertFrom-Json -AsHashtable -Depth 100
foreach($case in $cases){
 $caseTimer=[Diagnostics.Stopwatch]::StartNew()
 $value=& {param($fixture,$Root)
$script:flights=@();$script:saves=@();$script:refresh=$null
function Find-AcceptedRecoveryAnchorEvidence {param($History,$Lineage,$Anchor)@{materialization='anchor.json';observation='observation.json'}}
function Save-IterationRecoveryState {param($State,$Path)
 $script:saves+=,($State|ConvertTo-Json -Depth 100|ConvertFrom-Json -AsHashtable)
 $State|ConvertTo-Json -Depth 100|Set-Content -LiteralPath $Path
}
function New-CenterTrialArguments {param($Voltages,$ChildRunId)@{voltages=@($Voltages);run_id=$ChildRunId}}
function Invoke-CenterTrial {param($Arguments)$script:flights+=,$Arguments}
function Get-CenterTrialPhysicalEvidence {param($Manifest,$Voltages)@{passed=$true;observation_path='probe-observation.json';materialization_path='probe-materialization.json'}}
function Write-RunJson {param($Path,$Depth,$Value)$Value|ConvertTo-Json -Depth $Depth|Set-Content -LiteralPath $Path}
function Invoke-MockRefresh {
 $output=[array]::IndexOf($args,'--output');$radius=[array]::IndexOf($args,'--refresh-trusted-radius-linf-v');$directions=[array]::IndexOf($args,'--refresh-supported-directions')
 $script:refresh=@{radius=[double]$args[$radius+1];directions=@([int]$args[$directions+1],[int]$args[$directions+2])}
 Write-RunJson -Path $args[$output+1] -Depth 30 -Value $fixture.model
 $global:LASTEXITCODE=0
}
$python='Invoke-MockRefresh';$repoRoot=$RealRepo;$RunId='recovery';$trialArtifactRoot=$Root;$frozenProposal='proposal.json';$frozenContract='contract.json'
$statePath=Join-Path $Root 'state.json';$historyPath=Join-Path $Root 'history.json'
$fixture.stored|ConvertTo-Json -Depth 100|Set-Content -LiteralPath $statePath
$failure=$null;$state=$null
try{$state=Invoke-SLocalModelRecovery -Decision $fixture.decision -History $fixture.history -Lineage @{} -StatePath $statePath -HistoryPath $historyPath -ContractDocument $fixture.contract -RecoveryPolicy $fixture.policy}catch{$failure=$_.Exception.Message}
$modelPath=Join-Path $Root 'iteration_local_s_model.json'
@{state=$state;failure=$failure;flights=$script:flights;saves=$script:saves;refresh=$script:refresh;model=(Get-Content $modelPath -Raw|ConvertFrom-Json -AsHashtable);model_sha=(Get-FileHash $modelPath).Hash.ToLowerInvariant()}
 } $case.fixture $case.root
 $line=@{name=$case.name;case_seconds=$caseTimer.Elapsed.TotalSeconds;observation=$value}|ConvertTo-Json -Depth 100 -Compress
 [Console]::Out.WriteLine($line)
 [Console]::Out.Flush()
}
'''
        contract = json.loads((PROJECT / 'config/simion_candidate_two_zone.json').read_text(encoding='utf-8'))
        policy = json.loads((PROJECT / 'config/local_model_recovery_policy.json').read_text(encoding='utf-8'))
        anchor = dict(voltages_v=[-27., 54., 190., -190.], maximum_scaled_abs_residual=20.)
        decision = dict(iteration=6, recovery_state=dict(accepted_anchor=anchor, model_invalid_reason='topology_loss'))
        history = dict(decisions=[])
        cases = (
            ('validated_history', True, 2, 1, 'validated'),
            ('retry_failed_history', False, 2, 1, 'retry'),
            ('retry_no_history', False, 0, 1, 'retry'),
            ('provisional_no_history', False, 0, 3, 'provisional'),
            ('terminal_failed_history', False, 2, 3, 'terminal'),
            ('terminal_string_false', 'false', 0, 3, 'terminal'),
            ('provisional_missing_validation', None, 0, 3, 'provisional'),
            ('invalid_missing_validation', None, None, 3, 'invalid'),
        )
        with TemporaryDirectory() as directory:
            batch_root = Path(directory)
            probes, expected_cases = [], []
            for name, passed, eligible, round_number, expected in cases:
                root = batch_root / name
                root.mkdir()
                stored = prepare_recovery_state(decision, dict(materialization='anchor.json', observation='observation.json'),
                                                None, contract['downstream_fixed_grid_workpoint_profile'], policy, history)
                for _ in range(1, round_number):
                    stored = advance_recovery_round(stored, contract['downstream_fixed_grid_workpoint_profile'])
                validation = dict(passed=passed, eligible_observation_count=eligible) if eligible is not None else None
                model = dict(history_validation=validation, local_s_physical_jacobian_columns=[[1., 0.], [0., 1.], [1., 1.], [2., 2.]])
                probes.append(dict(name=name, root=str(root), fixture=dict(decision=decision,
                    history=history, contract=contract, policy=policy, stored=stored, model=model)))
                expected_cases.append((name, passed, eligible, round_number, expected, stored, model))
            fixture = batch_root / 'model.ps1'
            fixture.write_text(script, encoding='utf-8')
            stderr_path = batch_root / 'model.stderr.log'
            received = []
            with stderr_path.open('w', encoding='utf-8') as stderr:
                process = subprocess.Popen(['pwsh', '-NoProfile', '-File', str(fixture),
                    str(PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1'), str(batch_root),
                    sys.executable, str(PROJECT.parents[1])], cwd=PROJECT.parents[1],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
                    text=True, encoding='utf-8', bufsize=1)
                try:
                    json.dump(probes, process.stdin)
                    process.stdin.close()
                    process.stdin = None
                    for line in process.stdout:
                        self.assertLess(len(received), len(expected_cases), 'Unexpected duplicate/extra case row.')
                        row = json.loads(line)
                        name, passed, eligible, round_number, expected, stored, model = expected_cases[len(received)]
                        self.assertEqual(row['name'], name, 'Duplicate or out-of-order case row.')
                        received.append(name)
                        with self.subTest(case=name, passed=passed, eligible=eligible, round_number=round_number):
                            print(f"RECOVERY_CASE_SECONDS={row['case_seconds']:.6f} CASE={name}", flush=True)
                            observed = row['observation']
                            self.assertEqual(len(observed['flights']), 2)
                            self.assertEqual([s['probe_budget_remaining'] for s in observed['saves'][:5]], [12, 11, 11, 10, 10])
                            self.assertEqual([s['probes'][-1]['status'] for s in observed['saves'][1:5]],
                                             ['started', 'accepted_physical_probe', 'started', 'accepted_physical_probe'])
                            self.assertEqual(observed['refresh'], dict(radius=max(stored['probe_steps_v']), directions=[1, 1]))
                            if expected == 'invalid':
                                self.assertTrue(observed['failure'])
                                self.assertIsNone(observed['state'])
                                self.assertEqual(len(observed['saves']), 5)
                                continue
                            self.assertIsNone(observed['failure'])
                            state = observed['state']
                            self.assertEqual(state['status'], 'validated' if expected == 'provisional' else expected)
                            self.assertEqual(len(observed['saves']), 6)
                            self.assertEqual(state['probe_budget_remaining'], 12 if expected == 'retry' else 10)
                            if state['status'] == 'validated':
                                self.assertEqual(state['model']['sha256'], observed['model_sha'])
                                self.assertEqual(state['model']['supported_directions'], [1, 1])
                                self.assertEqual(state['model']['trusted_radius_linf_v'], max(stored['probe_steps_v']))
                            if expected == 'provisional':
                                actual = observed['model']['history_validation']
                                self.assertIs(actual['passed'], True)
                                self.assertEqual(actual['validation_status'], 'provisional_no_nearby_history')
                                self.assertIs(actual['first_correction_requires_real_prediction_acceptance'], True)
                                self.assertEqual(actual['first_correction_max_linf_v'], max(stored['probe_steps_v']))
                            else:
                                self.assertEqual(observed['model'], model)

                finally:
                    # Drain stdout and wait even if parsing/assertions fail. stderr
                    # has its own file, so a healthy child cannot block on a pipe.
                    process.communicate()
            self.assertEqual(process.returncode, 0, stderr_path.read_text(encoding='utf-8'))
            self.assertEqual(received, [case[0] for case in expected_cases], 'Missing case rows.')

    def test_recovery_round_json_transport_preserves_probe_order_debits_and_terminal_resume(self):
        script = r'''
param($Source,$Root,$RealPython,$RealRepo)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
foreach($name in @('Invoke-SLocalModelRecovery','Get-InterruptedSOnlyTopologyRecoveryDecision')){
 $node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)
 Invoke-Expression $node.Extent.Text
}
$transport=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-WorkpointControllerRequest'},$true)
Invoke-Expression ($transport.Extent.Text.Replace('function Invoke-WorkpointControllerRequest','function Invoke-RealControllerRequest'))
$script:actions=@();$script:flights=@();$script:saves=@()
function Invoke-WorkpointControllerRequest {param($Request,$Python,$RepoRoot)
 $script:actions+=,$Request.action
 Invoke-RealControllerRequest -Request $Request -Python $RealPython -RepoRoot $RealRepo
}
function Find-AcceptedRecoveryAnchorEvidence {param($History,$Lineage,$Anchor)@{materialization='anchor.json';observation='observation.json'}}
function Save-IterationRecoveryState {param($State,$Path)
 $script:saves+=,($State|ConvertTo-Json -Depth 100|ConvertFrom-Json -AsHashtable)
 $State|ConvertTo-Json -Depth 100|Set-Content -LiteralPath $Path
}
function New-CenterTrialArguments {param($Voltages,$ChildRunId)@{voltages=$Voltages;run_id=$ChildRunId}}
function Invoke-CenterTrial {param($Arguments)$script:flights+=,$Arguments}
function Get-CenterTrialPhysicalEvidence {param($Manifest,$Voltages)@{passed=$false}}
$fixture=[Console]::In.ReadToEnd()|ConvertFrom-Json -AsHashtable -Depth 100
$python=$RealPython;$repoRoot=$RealRepo;$RunId='recovery';$trialArtifactRoot=$Root
$statePath=Join-Path $Root 'state.json';$historyPath=Join-Path $Root 'history.json'
$states=@()
foreach($round in 1..4){
 $state=Invoke-SLocalModelRecovery -Decision $fixture.decision -History $fixture.history -Lineage @{} -StatePath $statePath -HistoryPath $historyPath -ContractDocument $fixture.contract -RecoveryPolicy $fixture.policy
 $states+=,$state
}
$topology=Get-InterruptedSOnlyTopologyRecoveryDecision -History @{decisions=@()}
@{states=$states;actions=$script:actions;flights=$script:flights;saves=$script:saves;topology=$topology}|ConvertTo-Json -Depth 100 -Compress
'''
        profile = json.loads((PROJECT / 'config/simion_candidate_two_zone.json').read_text(encoding='utf-8'))
        policy = json.loads((PROJECT / 'config/local_model_recovery_policy.json').read_text(encoding='utf-8'))
        anchor = dict(voltages_v=[-27., 54., 190., -190.], maximum_scaled_abs_residual=20.)
        for hint in (None, [-1, 1]):
            with self.subTest(hint=hint), TemporaryDirectory() as temporary:
                root = Path(temporary)
                decision = dict(iteration=6, recovery_state=dict(accepted_anchor=anchor, model_invalid_reason='topology_loss'))
                if hint:
                    decision['recovery_state']['initial_probe_directions'] = hint
                # This document intentionally contains an opposite historical side;
                # the current dictionary call keeps defaults rather than traversing it.
                history = dict(decisions=[dict(observation_record=dict(voltages_v=[-28., 53., 190., -190.]))])
                fixture = root / 'recovery.ps1'; fixture.write_text(script, encoding='utf-8')
                process = subprocess.run(['pwsh', '-NoProfile', '-File', str(fixture),
                    str(PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1'), str(root), sys.executable, str(PROJECT.parents[1])],
                    input=json.dumps(dict(decision=decision, history=history, contract=profile, policy=policy)),
                    cwd=PROJECT.parents[1], capture_output=True, text=True, encoding='utf-8', timeout=40)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                observed = json.loads(process.stdout)
                self.assertEqual([s['status'] for s in observed['states']], ['retry', 'retry', 'terminal', 'terminal'])
                self.assertEqual([s['probe_budget_remaining'] for s in observed['states']], [10, 8, 6, 6])
                self.assertEqual(observed['states'][2], observed['states'][3])
                self.assertEqual(observed['actions'],
                    (['prepare_recovery_state'] + ['plan_recovery_probe'] * 3) * 3
                    + ['prepare_recovery_state', 'interrupted_topology_recovery_decision'])
                direction = -1 if hint else 1
                expected = [-27. + direction * step for step in (.27, -.27, .0675, -.0675, .0135, -.0135)]
                self.assertEqual([f['voltages'][0] for f in observed['flights']], expected)
                self.assertEqual(len(observed['flights']), 6)
                labels = ('n', 'p') if hint else ('p', 'n')
                self.assertEqual([f['run_id'] for f in observed['flights']],
                                 [f'recovery-ri06r{round_number}-s1{label}'
                                  for round_number in (1, 2, 3) for label in labels])
                self.assertIsNone(observed['topology'])
                started = [s for s in observed['saves'] if s['probes'] and s['probes'][-1]['status'] == 'started']
                self.assertEqual([s['probe_budget_remaining'] for s in started], [11, 10, 9, 8, 7, 6])

    def test_prediction_decision_file_transport_handles_large_inputs_and_rejects_damage(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis.test_downstream_workpoint_iteration import DownstreamWorkpointIterationTests
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration import _stripe_stage_record, assess_staged_prediction
        import copy
        fixture_case=DownstreamWorkpointIterationTests()
        baseline,current,_,contract,_=fixture_case.stripe_preclosure_fixtures()
        record=_stripe_stage_record(current,contract['downstream_fixed_grid_workpoint_profile'])
        current['voltages_v']=record['voltages_v']
        policy=json.loads((PROJECT/'config/prism_controller_policy.json').read_text(encoding='utf-8-sig'))
        script=r'''
param($Source,$Root,$Repo,$RealPython,$Scenario)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Complete-StagedTrial'},$true);Invoke-Expression $node.Extent.Text
$transport=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-WorkpointControllerRequest'},$true)
Invoke-Expression ($transport.Extent.Text.Replace('function Invoke-WorkpointControllerRequest','function Invoke-RealControllerRequest'))
function Invoke-WorkpointControllerRequest {param($Request,$Python,$RepoRoot) Invoke-RealControllerRequest -Request $Request -Python $RealPython -RepoRoot $Repo}
$repoRoot=$Repo;$python='Invoke-TestPython';$frozenContract=Join-Path $Root 'contract.json';$package=@{result_dir=$Root}
$child=Join-Path $Root 'child.json';$anchor=Join-Path $Root 'anchor.json';$mat=Join-Path $Root 'mat.json'
$pending=Get-Content (Join-Path $Root 'pending.json') -Raw|ConvertFrom-Json -AsHashtable -Depth 100
$pending.child_manifest=$child;$pending.anchor_manifest=$anchor
$state=@{stage='stripe_preclosure';anchor_manifest=$anchor;flight_count=18;candidate_count=5;columns=@{};attempts=@();step_factor=.5;completion_attempted=$false;pending_trial=$pending}
$history=@{decisions=@()};$lineage=@{children=@()}
function Get-ManifestOutputPath {param($ManifestPath,$FileName)$mat}
function Write-RunJson {param($Path,$Depth,$Value)$Value|ConvertTo-Json -Depth $Depth|Set-Content -LiteralPath $Path -Encoding UTF8}
function Invoke-RunToolRootContext {param($RepoRoot,$Operation)&$Operation}
function Invoke-PreclosureDecision {param($Stage,$Anchor,$Columns,$OutputPath,$Context)@{status='needs_stencil';next_action='measure_stencil';full_workpoint_qualified=$false;maximum_scaled_abs_residual=2.}}
function Invoke-TestPython {
 param([Parameter(ValueFromRemainingArguments=$true)][object[]]$Arguments)
 $script:argumentChars=($Arguments|ForEach-Object{([string]$_).Length}|Measure-Object -Sum).Sum
 $script:inputPath=[string]$Arguments[4];$script:expectedBytes=[long]$Arguments[7];$script:expectedSha=[string]$Arguments[8]
 if($Scenario-eq'missing'){Remove-Item -LiteralPath $inputPath}
 if($Scenario-eq'changed'){
  $text=[IO.File]::ReadAllText($inputPath).Replace(('x'*200000),('y'+('x'*199999)))
  [IO.File]::WriteAllText($inputPath,$text,[Text.UTF8Encoding]::new($false))
 }
 $prefix='import json;from pathlib import Path;import projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_workpoint_iteration as m;m._load_stage_trial=lambda p:json.loads(Path(p).read_text(encoding="utf-8-sig"))'
 $Arguments[1]=$prefix+';'+$Arguments[1]
 & $RealPython @Arguments
}
$failure=$null
try{Complete-StagedTrial -Context @{repo_root=$repoRoot;python=$python;contract_path=$frozenContract;result_directory=$package.result_dir;prepared_staged=$false;target_authority_path=''} -State $state -History $history -Lineage $lineage -Pending $pending -Loop @{minimum_relative_improvement=.01} -Tiers @() -ControllerPolicyPath (Join-Path $Root 'policy.json')}catch{$failure=$_.Exception.Message}
@{failure=$failure;argument_characters=$script:argumentChars;input_path=$script:inputPath;expected_bytes=$script:expectedBytes;expected_sha=$script:expectedSha;state=$state;history=$history;lineage=$lineage}|ConvertTo-Json -Depth 100|Set-Content (Join-Path $Root 'result.json')
'''
        for scenario in ('short','large','missing','changed'):
            with self.subTest(scenario=scenario),TemporaryDirectory() as directory:
                root=Path(directory)
                decision=dict(status='proposed',next_action='run_S_candidate',maximum_scaled_abs_residual=4.,backtrack_multiplier=.5,
                    next_voltages_v=record['voltages_v'],predicted_physical_acceptance_residuals=copy.deepcopy(record['physical_acceptance_residuals']),
                    unicode_evidence_label='阶段候选核验', frozen_geometry_evidence='x'*200_000 if scenario!='short' else 'short')
                key=list(decision['predicted_physical_acceptance_residuals'])[-1]
                decision['predicted_physical_acceptance_residuals'][key]+=.02
                expected=assess_staged_prediction(decision,baseline,current,contract,dict(policy,path=str(root/'policy.json')))
                for name,value in (('anchor',baseline),('child',dict(current,status='success',run_id='child')),
                                   ('contract',contract),('policy',policy),('mat',current['materialization']),
                                   ('pending',dict(child_run_id='child',stage='stripe_preclosure',voltages_v=record['voltages_v'],decision=decision))):
                    (root/(name+'.json')).write_text(json.dumps(value),encoding='utf-8')
                path=root/'transport.ps1';path.write_text(script)
                result=subprocess.run(['pwsh','-NoProfile','-File',str(path),str(PROJECT/'analysis/run_downstream_workpoint_iteration.ps1'),
                    str(root),str(PROJECT.parents[1]),sys.executable,scenario],cwd=PROJECT.parents[1],capture_output=True,text=True,encoding='utf-8',timeout=35)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                observed=json.loads((root/'result.json').read_text(encoding='utf-8-sig'))
                self.assertLess(observed['argument_characters'],8000)
                if scenario in ('short','large'):
                    self.assertIsNone(observed['failure'])
                    self.assertEqual(observed['state']['prediction_assessment'],expected)
                    saved=Path(observed['input_path'])
                    self.assertEqual(json.loads(saved.read_text(encoding='utf-8-sig')),decision)
                    self.assertEqual(saved.stat().st_size,observed['expected_bytes'])
                    self.assertEqual(hashlib.sha256(saved.read_bytes()).hexdigest(),observed['expected_sha'].lower())
                    if scenario=='large':self.assertGreater(saved.stat().st_size,32767)
                    self.assertNotIn('pending_trial',observed['state'])
                else:
                    self.assertEqual(observed['failure'],'Pending stage child identity validation failed.')
                    self.assertEqual(observed['lineage']['children'],[])
                    self.assertIn('pending_trial',observed['state'])
                    if scenario=='changed':
                        saved=Path(observed['input_path'])
                        self.assertEqual(saved.stat().st_size,observed['expected_bytes'])
                        self.assertNotEqual(hashlib.sha256(saved.read_bytes()).hexdigest(),observed['expected_sha'].lower())

    def test_explicit_target_reanchor_validates_old_authority_and_publishes_once(self):
        script=r'''
param($Source,$Root,$Scenario)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Restore-PreparedOriginalStages'},$true)
Invoke-Expression $node.Extent.Text
$repoRoot=$Root;$project='parallel_mirror_dual_stripe_mr_tof';$python='mock-python';$RunId='new-parent'
$PreparedFieldBuildMode='composition';$ResumeSuccessfulChildManifest='';$PreparedTargetReanchor=$true
$parent=Join-Path $Root 'old';$inputs=Join-Path $Root 'inputs';$results=Join-Path $Root 'results'
New-Item -ItemType Directory -Path $parent,$inputs,$results|Out-Null
$package=@{input_dir=$inputs;result_dir=$results;run_config=(Join-Path $Root 'run_config.json')};$ResumeParentCheckpoint=$parent
$same=Join-Path $Root 'same.json';'{}'|Set-Content $same
$oldTarget=Join-Path $Root 'oldtarget.json';'{"L":360}'|Set-Content $oldTarget
$newTarget=Join-Path $Root 'newtarget.json';'{"L":340}'|Set-Content $newTarget
$anchor=Join-Path $Root 'anchor.json';'{}'|Set-Content $anchor
$old=@{inputs=@{};parameters=@{workflow_branch='measured_source_original_P_S_P_stages';field_build_mode='composition'}}
$cfg=@{inputs=@{};parameters=@{}}
foreach($key in @('prepared_manifest','seed_manifest','trajectory_contract','prepared_target_authority','prepared_initial_proposal','p1_response','p2_response','prism_controller_policy')){$old.inputs[$key]=$same;$cfg.inputs[$key]=$same}
$old.inputs.prepared_target_authority=$oldTarget;$cfg.inputs.prepared_target_authority=$newTarget;$cfg.inputs.seed_manifest=$anchor
$seedManifest=$anchor;$frozenContract=$same;$frozenPreparedTargetAuthorityPath=$newTarget
if($Scenario-eq'unknown_anchor'){$seedManifest=Join-Path $Root 'unknown.json'}
if($Scenario-eq'changed_science'){$cfg.inputs.trajectory_contract=$newTarget}
@{status='interrupted';run_id='old-parent'}|ConvertTo-Json|Set-Content (Join-Path $parent 'run_manifest.json')
$stop=@{stopped_parent_process_id=2147483647;stopped_parent_verified_absent=$true;stopped_children_verified_absent=$true;pending_trial_executed=$false}
if($Scenario-eq'live'){$stop.stopped_parent_process_id=$PID}
if($Scenario-eq'unknown_stop'){$stop.stopped_parent_verified_absent=$false}
$stop|ConvertTo-Json|Set-Content (Join-Path $parent 'summary.json')
$old|ConvertTo-Json -Depth 20|Set-Content (Join-Path $parent 'run_config.json')
$pending=@{child_manifest=(Join-Path $Root 'unflown/run_manifest.json');child_run_id='old-stage-051';decision=@{science='unchanged'}}
if($Scenario-eq'existing_trial'){New-Item -ItemType Directory -Path (Split-Path $pending.child_manifest)|Out-Null}
$prior=@{role='mrtof_downstream_workpoint_bootstrap';source_projection='measured_exit_centroid'
 stage_state=@{stage='stripe_preclosure';anchor_manifest=$anchor;candidate_count=16;flight_count=51;step_factor=.125;pending_trial=$pending
 columns=@{'0'='old-S1'};attempts=@('old');prism_model_manifest='old-model'}
 stage_history=@{decisions=@('old-decision')};stage_lineage=@{root_workpoint_manifest=@{path=$same};children=@(@{child_manifest=$anchor})}}
if($Scenario-eq'already_reanchored'){$prior.stage_state.target_reanchor=@{abandoned_pending='sealed-evidence'}}
$prior|ConvertTo-Json -Depth 100|Set-Content (Join-Path $parent 'workpoint_bootstrap.json')
function Invoke-RunToolRootContext {param($RepoRoot,$Operation)&$Operation}
function mock-python {
 if($args[0]-eq'-c'-and$args[1]-match'reanchor_prepared_target\(read'){
  $state=Get-Content $args[2] -Raw|ConvertFrom-Json -AsHashtable -Depth 100
  if($state.Contains('pending_trial')){throw 'Pending was not archived before pure reanchor'}
  $state.columns=@{};$state.attempts=@();$state.Remove('prism_model_manifest')|Out-Null
  $state.stage='prism_preclosure';$state.target_reanchor=@{source_unchanged=$true};$state.anchor_manifest=$args[3]
  $global:LASTEXITCODE=0;return ($state|ConvertTo-Json -Depth 100)
 }
 if($args[0]-eq'-c'-and$args[1]-match'children=\[e'){
  if($args[3]-ne$same-or$args[4]-ne$oldTarget){throw 'Historical evidence reinterpreted with new authority'}
  $script:oldScienceValidated=$true
 }
 $global:LASTEXITCODE=0
}
function Get-ManifestOutputPath {param($ManifestPath,$FileName)Join-Path (Split-Path $ManifestPath) $FileName}
function Copy-VerifiedRunInput {param($Source,$Destination)Copy-Item $Source $Destination;return $Destination}
function Write-RunJson {param($Path,$Depth,$Value)$Value|ConvertTo-Json -Depth 100|Set-Content $Path}
function Save-WorkpointBootstrap {param($Bootstrap,$BootstrapPath)$script:saves+=,($Bootstrap|ConvertTo-Json -Depth 100|ConvertFrom-Json -AsHashtable -Depth 100)}
function Restore-StagedWorkpointChildren {param($Bootstrap,$SourceLineage,$BootstrapPath,$PriorState,[switch]$DeferSave)
 if(-not$DeferSave-or$seedManifest-ne$same-or-not$PriorState.Contains('pending_trial')-or$PriorState.candidate_count-ne16-or$PriorState.flight_count-ne51){throw 'Original checkpoint was modified before strict restore'}
 $script:restored=$true
}
function Update-StagedAnchorFieldProtection {param($State)}
$script:saves=@();$script:restored=$false;$script:oldScienceValidated=$false;$b=@{};$failure=$null
try{Restore-PreparedOriginalStages -Bootstrap $b -BootstrapPath 'unused' -Configuration $cfg}catch{$failure=$_.Exception.Message}
@{failure=$failure;bootstrap=$b;saves=$saves;restored=$restored;oldScienceValidated=$oldScienceValidated}|ConvertTo-Json -Depth 100
'''
        for scenario in ('success','unknown_anchor','changed_science','live','unknown_stop','existing_trial','already_reanchored'):
            with self.subTest(scenario=scenario),TemporaryDirectory() as directory:
                root=Path(directory);fixture=root/'reanchor.ps1';fixture.write_text(script)
                result=subprocess.run(['pwsh','-NoProfile','-File',str(fixture),str(PROJECT/'analysis/run_downstream_workpoint_iteration.ps1'),str(root),scenario],
                    capture_output=True,text=True,encoding='utf-8',timeout=35,cwd=PROJECT.parents[1])
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                value=json.loads(result.stdout)
                if scenario=='success':
                    self.assertIsNone(value['failure'])
                    self.assertTrue(value['oldScienceValidated']);self.assertTrue(value['restored'])
                    self.assertEqual(len(value['saves']),1)
                    state=value['saves'][0]['stage_state']
                    self.assertEqual((state['candidate_count'],state['flight_count']),(16,51))
                    self.assertEqual(state['columns'],{});self.assertNotIn('pending_trial',state)
                    self.assertEqual(state['target_reanchor']['abandoned_pending']['pending_trial']['child_run_id'],'old-stage-051')
                    self.assertEqual(value['bootstrap']['stage_history'],{'decisions':['old-decision']})
                else:
                    self.assertIsNotNone(value['failure']);self.assertEqual(value['saves'],[])

    def test_explicit_repository_policy_adoption_preserves_debits_and_only_clears_current_model(self):
        script=r'''
param($Source,$Root,$Repo,$RealPython,$Scenario)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Restore-PreparedOriginalStages'},$true)
Invoke-Expression $node.Extent.Text
$repoRoot=$Repo;$project='parallel_mirror_dual_stripe_mr_tof';$python='mock-python';$RunId='new-parent'
$PreparedFieldBuildMode='composition';$ResumeSuccessfulChildManifest=''
$parent=Join-Path $Root 'old';$inputs=Join-Path $Root 'inputs';$results=Join-Path $Root 'results'
New-Item -ItemType Directory -Path $parent,$inputs,$results|Out-Null
$package=@{input_dir=$inputs;result_dir=$results;run_config=(Join-Path $Root 'run_config.json')}
$ResumeParentCheckpoint=$parent
$same=Join-Path $Root 'same.json';'{}'|Set-Content $same
$old=@{inputs=@{};parameters=@{workflow_branch='measured_source_original_P_S_P_stages';field_build_mode='composition'}}
$cfg=@{inputs=@{};parameters=@{}}
foreach($key in @('prepared_manifest','seed_manifest','trajectory_contract','prepared_target_authority','prepared_initial_proposal','p1_response','p2_response')){$old.inputs[$key]=$same;$cfg.inputs[$key]=$same}
$canonical=Join-Path $Repo 'projects/parallel_mirror_dual_stripe_mr_tof/config/prism_controller_policy.json'
$policy=Join-Path $inputs 'prism_controller_policy.json';Copy-Item $canonical $policy
$cfg.inputs.prism_controller_policy=$policy
if($Scenario-eq'wrong_policy'){'{}'|Set-Content $policy}
if($Scenario-in@('replace','same_existing','remove_existing')){
 $oldPolicy=Join-Path $parent 'policy.json';Copy-Item $canonical $oldPolicy;$old.inputs.prism_controller_policy=$oldPolicy
 if($Scenario-eq'replace'){'{}'|Set-Content $oldPolicy}
 if($Scenario-eq'remove_existing'){$cfg.inputs.Remove('prism_controller_policy')|Out-Null}
}
if($Scenario-eq'science_changed'){$wrong=Join-Path $inputs 'wrong.json';'{"velocity":99}'|Set-Content $wrong;$cfg.inputs.prepared_manifest=$wrong}
$seedManifest=$same;$frozenContract=$same;$frozenPreparedTargetAuthorityPath=$same
@{status='failed';run_id='old-parent'}|ConvertTo-Json|Set-Content (Join-Path $parent 'run_manifest.json')
$old|ConvertTo-Json -Depth 20|Set-Content (Join-Path $parent 'run_config.json')
$prior=@{role='mrtof_downstream_workpoint_bootstrap';source_projection='measured_exit_centroid'
 stage_state=@{stage='prism_preclosure';anchor_manifest='unchanged-anchor';candidate_count=3;flight_count=13;step_factor=.5
 columns=@{'2'='old-P1';'3'='old-P2'};attempts=@(@{axis=2;signed_step_v=1});prism_model_manifest='old-model';prediction_assessment=@{status='old'}}
 stage_history=@{decisions=@('old-decision')};stage_lineage=@{children=@('old-lineage')}}
if($Scenario-eq'pending'){$prior.stage_state.pending_trial=@{child_manifest='pending';child_run_id='pending'}}
if($Scenario-eq'stripe'){$prior.stage_state.stage='stripe_preclosure'}
$prior|ConvertTo-Json -Depth 30|Set-Content (Join-Path $parent 'workpoint_bootstrap.json')
function Invoke-RunToolRootContext {param($RepoRoot,$Operation)&$Operation}
function mock-python {
 if($args[0]-eq'-c'-and$args[1]-match'print\(json.dumps\(resolve_prism_controller_policy') {& $RealPython @args;return}
 $global:LASTEXITCODE=0
}
function Get-ManifestOutputPath {param($ManifestPath,$FileName)Join-Path (Split-Path $ManifestPath) $FileName}
function Copy-VerifiedRunInput {param($Source,$Destination)Copy-Item $Source $Destination;return $Destination}
function Write-RunJson {param($Path,$Depth,$Value)
 if($Scenario-eq'receipt_failed'-and[IO.Path]::GetFileName($Path)-eq'iteration_prism_policy_adoption.json'){throw 'receipt failed'}
 $Value|ConvertTo-Json -Depth 100|Set-Content $Path
}
function Save-WorkpointBootstrap {param($Bootstrap,$BootstrapPath)
 $script:saves+=,($Bootstrap|ConvertTo-Json -Depth 100|ConvertFrom-Json -AsHashtable)
 if($Scenario-eq'save_failed'){throw 'capacity renewal failed after complete checkpoint'}
}
function Restore-StagedWorkpointChildren {param($Bootstrap,$SourceLineage,$BootstrapPath,$PriorState,[switch]$DeferSave)
 if($PriorState.columns.Count-ne2-or$PriorState.prism_model_manifest-ne'old-model'-or$PriorState.candidate_count-ne3-or$PriorState.flight_count-ne13){throw 'Old checkpoint modified before strict validation'}
 if($Scenario-eq'restore_failed'){throw 'old strict restore failed'}
 $script:validated=$true
 if(-not$DeferSave){Save-WorkpointBootstrap -Bootstrap $Bootstrap -BootstrapPath $BootstrapPath}
}
function Update-StagedAnchorFieldProtection {param($State)}
$script:validated=$false;$script:saves=@();$b=@{};$failure=$null
try{Restore-PreparedOriginalStages -Bootstrap $b -BootstrapPath 'not-written' -Configuration $cfg}catch{$failure=$_.Exception.Message}
$receipt=Join-Path $results 'iteration_prism_policy_adoption.json'
@{failure=$failure;validated=$validated;bootstrap=$b;config=$cfg;saves=$saves;receipt=$(if(Test-Path $receipt){Get-Content $receipt -Raw|ConvertFrom-Json -AsHashtable}else{$null})}|ConvertTo-Json -Depth 100
'''
        for scenario in ('adopt','same_existing','pending','stripe','wrong_policy','replace','remove_existing',
                         'science_changed','restore_failed','receipt_failed','save_failed'):
            with self.subTest(scenario=scenario),TemporaryDirectory() as directory:
                root=Path(directory);fixture=root/'adopt.ps1';fixture.write_text(script)
                result=subprocess.run(['pwsh','-NoProfile','-File',str(fixture),str(PROJECT/'analysis/run_downstream_workpoint_iteration.ps1'),
                    str(root),str(PROJECT.parents[1]),sys.executable,scenario],cwd=PROJECT.parents[1],capture_output=True,text=True,encoding='utf-8',timeout=35)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                observed=json.loads(result.stdout)
                if scenario in ('adopt','save_failed'):
                    state=observed['bootstrap']['stage_state']
                    self.assertTrue(observed['validated'])
                    self.assertEqual((state['stage'],state['anchor_manifest'],state['candidate_count'],state['flight_count'],state['step_factor']),
                                     ('prism_preclosure','unchanged-anchor',3,13,.5))
                    self.assertEqual(state['columns'],{});self.assertEqual(state['attempts'],[])
                    self.assertNotIn('prism_model_manifest',state);self.assertNotIn('prediction_assessment',state)
                    self.assertEqual(observed['bootstrap']['stage_history'],{'decisions':['old-decision']})
                    self.assertEqual(observed['bootstrap']['stage_lineage'],{'children':['old-lineage']})
                    self.assertEqual(observed['receipt']['cleared_local_evidence']['columns'],{'2':'old-P1','3':'old-P2'})
                    self.assertEqual(observed['receipt']['cleared_local_evidence']['prism_model_manifest'],'old-model')
                    self.assertEqual(len(observed['saves']),1)
                    self.assertEqual(observed['saves'][0]['stage_state']['columns'],{})
                    self.assertEqual(observed['config']['parameters']['imported_columns'],0)
                    self.assertEqual(observed['failure'],None if scenario=='adopt' else 'capacity renewal failed after complete checkpoint')
                elif scenario=='same_existing':
                    self.assertIsNone(observed['failure']);self.assertIsNone(observed['receipt'])
                    self.assertEqual(observed['bootstrap']['stage_state']['columns'],{'2':'old-P1','3':'old-P2'})
                else:
                    self.assertIsNotNone(observed['failure'])
                    self.assertEqual(observed['saves'],[])

    def test_prepared_checkpoint_reuses_original_restore_and_rejects_changed_authority(self):
        script=r'''
param($Source,$Root,$Scenario,$RealPython)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Restore-PreparedOriginalStages'},$true)
Invoke-Expression $node.Extent.Text
$repoRoot=$Root;$project='parallel_mirror_dual_stripe_mr_tof';$python='mock-python';$RunId='new-parent'
$PreparedFieldBuildMode='composition';$ResumeSuccessfulChildManifest=''
$parent=Join-Path $Root 'old';$inputs=Join-Path $Root 'new-inputs'
New-Item -ItemType Directory -Path $parent,$inputs|Out-Null
$package=@{input_dir=$inputs;run_config=(Join-Path $Root 'new-config.json')}
$ResumeParentCheckpoint=$parent
$keys=@('prepared_manifest','seed_manifest','trajectory_contract','prepared_target_authority','prepared_initial_proposal','p1_response','p2_response','prism_controller_policy')
$old=@{inputs=@{};parameters=@{workflow_branch='measured_source_original_P_S_P_stages';field_build_mode='composition'}}
$cfg=@{inputs=@{};parameters=@{imported_columns=0}}
foreach($key in $keys){
 $oldPath=Join-Path $parent ($key+'.json');$newPath=Join-Path $inputs ($key+'.json')
 '{}'|Set-Content $oldPath;'{}'|Set-Content $newPath
 $old.inputs[$key]=$oldPath;$cfg.inputs[$key]=$newPath
 if($Scenario-eq$key){'{"changed":true}'|Set-Content $newPath}
}
$cfg.inputs.s1_response=Join-Path $inputs 'new-S1.json';'{}'|Set-Content $cfg.inputs.s1_response
if($Scenario-like'budget_*'){
 $contract=@{physics=@{source='same';grid=.1};downstream_fixed_grid_workpoint_profile=@{automatic_iteration=@{advance_multiplier=1.;damping_factor=.5;maximum_iterations=5}}}
 $contract|ConvertTo-Json -Depth 20|Set-Content $old.inputs.trajectory_contract
 $contract.downstream_fixed_grid_workpoint_profile.automatic_iteration.maximum_iterations=if($Scenario-eq'budget_decrease'){4}else{30}
 if($Scenario-eq'budget_wrong_field'){$contract.physics.grid=.2}
 $contract|ConvertTo-Json -Depth 20|Set-Content $cfg.inputs.trajectory_contract
}
$seedManifest=$cfg.inputs.seed_manifest;$frozenContract=$cfg.inputs.trajectory_contract;$frozenPreparedTargetAuthorityPath=$cfg.inputs.prepared_target_authority
$manifest=Join-Path $parent 'run_manifest.json'
@{status='failed';run_id=$(if($Scenario-eq'same_id'){$RunId}else{'old-parent'})}|ConvertTo-Json|Set-Content $manifest
$old|ConvertTo-Json -Depth 20|Set-Content (Join-Path $parent 'run_config.json')
$prior=@{role='mrtof_downstream_workpoint_bootstrap';source_projection='measured_exit_centroid'
 stage_state=@{candidate_count=3;columns=@{'2'='sealed-P1-child'};pending_trial=@{child_manifest='old-failed-P2';child_run_id='old-stage-002'}}
 stage_history=@{decisions=@('sealed-P1-decision')};stage_lineage=@{children=@('sealed-P1-lineage')}}
$prior|ConvertTo-Json -Depth 20|Set-Content (Join-Path $parent 'workpoint_bootstrap.json')
function Invoke-RunToolRootContext {param($RepoRoot,$Operation)&$Operation}
function mock-python {
 if($args[0]-eq'-m'){$script:verified=$true}
 elseif($args[0]-eq'-c'-and$args[1]-match'assert_bounded_controller_resume'){& $RealPython @args;return}
 elseif($args[0]-eq'-c'){$script:replayed=$true}else{throw 'Wrong public verifier entry'}
 $global:LASTEXITCODE=0
}
function Get-ManifestOutputPath {param($ManifestPath,$FileName)Join-Path (Split-Path $ManifestPath) $FileName}
function Copy-VerifiedRunInput {param($Source,$Destination)Copy-Item -LiteralPath $Source -Destination $Destination;return $Destination}
function Write-RunJson {param($Path,$Depth,$Value)$Value|ConvertTo-Json -Depth 100|Set-Content $Path}
function Restore-StagedWorkpointChildren {
 param($Bootstrap,$SourceLineage,$BootstrapPath,$PriorState)
 if($PriorState.columns['2']-ne'sealed-P1-child'-or$PriorState.pending_trial.child_run_id-ne'old-stage-002'-or
    $Bootstrap.stage_history.decisions[0]-ne'sealed-P1-decision'-or$SourceLineage.children[0]-ne'sealed-P1-lineage'){throw 'Original checkpoint state lost'}
 $script:restored=$true
}
function Update-StagedAnchorFieldProtection {param($State)$script:protected=$true}
$script:verified=$false;$script:replayed=$false;$script:restored=$false;$script:protected=$false;$failure=$null
$bootstrap=@{}
try{Restore-PreparedOriginalStages -Bootstrap $bootstrap -BootstrapPath 'new-bootstrap' -Configuration $cfg}catch{$failure=$_.Exception.Message}
@{failure=$failure;verified=$verified;replayed=$replayed;restored=$restored;protected=$protected;config=$cfg}|ConvertTo-Json -Depth 20
'''
        for scenario in ('valid','budget_valid','budget_decrease','budget_wrong_field','same_id','prepared_manifest','seed_manifest','trajectory_contract',
                         'prepared_target_authority','prepared_initial_proposal','p1_response','p2_response','prism_controller_policy'):
            with self.subTest(scenario=scenario),TemporaryDirectory() as directory:
                root=Path(directory);fixture=root/'resume.ps1';fixture.write_text(script)
                result=subprocess.run(['pwsh','-NoProfile','-File',str(fixture),str(PROJECT/'analysis/run_downstream_workpoint_iteration.ps1'),str(root),scenario,sys.executable],
                    cwd=PROJECT.parents[1],capture_output=True,text=True,encoding='utf-8',timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                observed=json.loads(result.stdout)
                if scenario in ('valid','budget_valid'):
                    self.assertIsNone(observed['failure'])
                    self.assertTrue(all(observed[k] for k in ('verified','replayed','restored','protected')))
                    self.assertEqual(observed['config']['parameters']['imported_columns'],1)
                    self.assertTrue(Path(observed['config']['inputs']['resume_parent_bootstrap']).exists())
                    if scenario=='budget_valid':
                        change=observed['config']['parameters']['controller_resume_changes']
                        self.assertEqual(change['preserved_candidate_count'],3)
                        self.assertEqual(change['maximum_iterations'],dict(previous=5,current=30))
                        self.assertTrue(Path(observed['config']['inputs']['previous_controller_contract']).exists())
                else:
                    self.assertIsNotNone(observed['failure'])
                    self.assertFalse(observed['restored'])

    def test_prepared_checkpoint_replay_validates_full_frozen_problem_without_pa_reads(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import downstream_workpoint_iteration as controller
        source=(PROJECT/'analysis/run_downstream_workpoint_iteration.ps1').read_text(encoding='utf-8-sig')
        code=re.search(r"\$replayCode=@'\n(.*?)\n'@",source,re.S).group(1)
        for scenario in ('valid','source','target','operator','numerics'):
            with self.subTest(scenario=scenario),TemporaryDirectory() as directory:
                root=Path(directory);parent=root/'bootstrap.json';pending=root/'pending.json'
                pending.write_text(json.dumps({'status':'success'}))
                parent.write_text(json.dumps({'stage_lineage':{'children':[{'child_manifest':'P1'}]},
                    'stage_state':{'pending_trial':{'child_manifest':str(pending)}}}))
                identity=dict(source='frozen-6D',target='frozen-target',operator='frozen-grid-operator',numerics='frozen-steps')
                changed=dict(identity)
                if scenario!='valid':changed[scenario]='changed'
                values=[{'frozen_problem':identity},{'frozen_problem':changed},{'frozen_problem':identity}]
                with patch.object(sys,'argv',['resume',str(parent),'seed','target','contract']),\
                     patch.object(controller,'load_prepared_centroid_trial',side_effect=values) as load:
                    if scenario=='valid':
                        exec(compile(code,'prepared-replay','exec'),{})
                        self.assertEqual(load.call_count,3)
                    else:
                        with self.assertRaisesRegex(AssertionError,'differs'):
                            exec(compile(code,'prepared-replay','exec'),{})

    def test_prepared_direct_candidate_dispatch_uses_same_public_provider_and_original_source(self):
        script=r'''
param($Source,$Root,$FailureMode)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
foreach($name in @('New-CenterTrialArguments','Invoke-CenterTrial','New-StagedComposeProviderReference')){
 $node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)
 Invoke-Expression $node.Extent.Text
}
$script:preparedStagedMode=$true;$script:PreparedFieldBuildMode='refine'
$repoRoot=$Root;$artifactRoot=$Root;$RunId='parent';$project='parallel_mirror_dual_stripe_mr_tof';$python='mock-python'
$trialArtifactRoot=$artifactRoot
$package=@{input_dir=(Join-Path $Root 'inputs')};New-Item -ItemType Directory -Path $package.input_dir|Out-Null
$staticFieldMode=$true;$staticBinding=@{authority=@{analyzer_electrode_voltages_v=@(0,0,0,0,0,0,0,0,0,0,-27,-27,0,0,0,343,-186,0,0,0)}}
$fieldProviderRequest=@{schema_version=1;role='mrtof_native_static_field_provider_request';source_binding_path='sealed-IP-baseline';source_field_manifest='sealed-IP-manifest'}
$CompletedFieldProviderManifest='';$ResponseFieldBindingPath='';$capacitySession=@{id='public'}
$PreparedJointWorkbenchRunPath='same-audited-prepared-source';$frozenContract='same-frozen-contract';$SimionExe=''
$script:providerCalls=0;$script:flights=@();$script:request=$null
function Invoke-RunToolRootContext {param($RepoRoot,$Operation)&$Operation}
function Write-RunJson {param($Path,$Depth,$Value)$Value|ConvertTo-Json -Depth 100|Set-Content $Path}
function mock-python {$global:LASTEXITCODE=0;if($args-contains'common.contracts.verify_run_manifest'){return};'false'}
function Update-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session,$ProtectedPaths)return @{session=$Session}}
function Save-WorkpointBootstrap {param($Bootstrap,$BootstrapPath)}
function public-provider {
 param($RequestPath,$RunDirectory,[switch]$Approved)
 if(-not$Approved){throw 'Public provider not authorized'}
 $script:providerCalls++;$script:request=Get-Content $RequestPath -Raw|ConvertFrom-Json -AsHashtable
 if($request.source_binding_path-ne'sealed-IP-baseline'-or$request.numerical_contract_path-ne'same-frozen-contract'){throw 'Baseline/numerical authority changed'}
 foreach($key in @('response_basis_paths','response_axis','te1_reference_path','consumer_view_source_path','reuse_source_levels')){
   if($request.Contains($key)){throw 'Unexpected response/private path'}
 }
 New-Item -ItemType Directory -Path $RunDirectory -Force|Out-Null
 $cfg=Join-Path $RunDirectory 'run_config.json';@{parameters=@{operation='refine'}}|ConvertTo-Json|Set-Content $cfg
 $manifest=@{status=$(if($FailureMode-eq'success'){'success'}else{'failed'});project=$project;mode='native_static_field_provider';run_id=$request.run_id
   inputs=@{request=@{path=$RequestPath;sha256=(Get-FileHash $RequestPath -Algorithm SHA256).Hash}}
   run_config=@{sha256=(Get-FileHash $cfg -Algorithm SHA256).Hash}}
 $manifest|ConvertTo-Json -Depth 20|Set-Content (Join-Path $RunDirectory 'run_manifest.json')
 if($FailureMode-eq'success'){
   @{status='success';field_binding='new-direct-five-layer-binding'}|ConvertTo-Json|Set-Content (Join-Path $RunDirectory 'summary.json')
 }else{
   $message=if($FailureMode-eq'capacity'){'Artifact capacity gate blocked startup: CAPACITY_TARGET_NOT_MET'}else{'Synthetic Refine failure'}
   @{status='failed';failure_stage=$(if($FailureMode-eq'capacity'){'capacity_startup'}else{'parent_refine'});error=$message}|ConvertTo-Json|Set-Content (Join-Path $RunDirectory 'summary.json')
   throw $message
 }
}
function prepared-public-trial {
 param($PreparedJointWorkbenchRunPath,$PreparedSourceMode,$FieldBindingPath,$ContractPath,$RunId,$PythonExe)
 if($PreparedJointWorkbenchRunPath-ne'same-audited-prepared-source'-or$PreparedSourceMode-ne'centroid_probe'){throw 'Resampled or wrong source'}
 $script:flights+=,@{binding=$FieldBindingPath;source=$PreparedJointWorkbenchRunPath;source_mode=$PreparedSourceMode}
}
$fieldProviderRunner='public-provider';$trialRunner='prepared-public-trial'
$arguments=New-CenterTrialArguments -Voltages @(-28,0,344,-187) -ChildRunId 'parent-stage-001'
$pending=@{}
$bootstrap=@{stage_state=@{}}
$failure=$null
try{Invoke-CenterTrial -Arguments $arguments -StagedPending $pending -Bootstrap $bootstrap -BootstrapPath 'checkpoint'}catch{$failure=$_.Exception.Message}
@{provider_calls=$providerCalls;flights=$flights;request=$request;reference=$(if($pending.Contains('provider_reference')){$pending.provider_reference}else{$null});state=$bootstrap.stage_state;failure=$failure}|ConvertTo-Json -Depth 40
'''
        for failure_mode in ("success","capacity","refine_failure"):
            with self.subTest(failure_mode=failure_mode),TemporaryDirectory() as directory:
                root=Path(directory);script_path=root/"direct.ps1";script_path.write_text(script)
                result=subprocess.run(["pwsh","-NoProfile","-File",str(script_path),str(PROJECT/"analysis/run_downstream_workpoint_iteration.ps1"),str(root),failure_mode],
                    cwd=PROJECT.parents[1],timeout=40,capture_output=True,text=True,encoding="utf-8")
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                observed=json.loads(result.stdout)
                self.assertEqual(observed["provider_calls"],1)
                self.assertEqual(observed["request"]["candidate_voltages_v"],dict(s1=-28,s2=0,p1=344,p2=-187))
                if failure_mode=="success":
                    self.assertIsNone(observed["failure"])
                    self.assertEqual(len(observed["flights"]),1)
                    self.assertEqual(observed["flights"][0]["binding"],"new-direct-five-layer-binding")
                    self.assertEqual(observed["reference"]["operation"],"refine")
                elif failure_mode=="capacity":
                    self.assertIsNone(observed["failure"])
                    self.assertEqual(observed["flights"],[])
                    self.assertTrue(observed["state"]["capacity_lifecycle_blocked"]["no_private_delete"])
                    self.assertFalse(observed["state"]["capacity_lifecycle_blocked"]["candidate_flight_executed"])
                else:
                    self.assertEqual(observed["failure"],"Synthetic Refine failure")
                    self.assertNotIn("capacity_lifecycle_blocked",observed["state"])
                    self.assertEqual(observed["flights"],[])

    def test_prepared_refine_preflight_keeps_five_layer_ip_operator_identity(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import static_field_binding as fields
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import downstream_workpoint_iteration as controller
        source=(PROJECT/"analysis/run_downstream_workpoint_iteration.ps1").read_text(encoding="utf-8-sig")
        code=re.search(r"\$loadCode=@'\n(.*?)\n'@",source,re.S).group(1)
        actual=dict(ip15=list(range(15)),fixed_analyzer20=list(range(20)),actual_grid="five sealed grids")
        for scenario in ("valid","wrong_ip15","wrong_fixed_voltage","wrong_grid","wrong_layer_count","wrong_provider","consumer_view"):
            with self.subTest(scenario=scenario):
                import copy
                binding=dict(accelerator_provider="dual_pressure_rectilinear_ion_processor",refinement_windows=[{}]*4,
                             authority=copy.deepcopy(actual),operator=copy.deepcopy(actual))
                if scenario=="wrong_provider":
                    binding["accelerator_provider"]="orthogonal_accelerator"
                if scenario=="wrong_layer_count":
                    binding["refinement_windows"].pop()
                if scenario=="consumer_view":
                    binding["consumer_view"]={"crop":"unfit solve source"}
                if scenario=="wrong_ip15":
                    binding["operator"]["ip15"][0]+=1
                if scenario=="wrong_fixed_voltage":
                    binding["operator"]["fixed_analyzer20"][0]+=1
                if scenario=="wrong_grid":
                    binding["operator"]["actual_grid"]="different"
                with patch.object(sys,"argv",["preflight","seed","target","contract","base","__none__","refine"]),\
                     patch.object(controller,"load_prepared_centroid_trial",return_value={"frozen_problem":{"static_field_problem":actual}}),\
                     patch.object(fields,"load_binding",return_value=binding),\
                     patch.object(fields,"native_response_operator",side_effect=lambda b,a:b["operator"]):
                    if scenario=="valid":
                        with redirect_stdout(io.StringIO()):
                            exec(compile(code,"prepared-field-preflight","exec"),{})
                    else:
                        with self.assertRaises(AssertionError):
                            exec(compile(code,"prepared-field-preflight","exec"),{})

    def test_prepared_original_stages_freeze_target_and_call_existing_bootstrap(self):
        script=r'''
param($Source,$Root,$BuildMode)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$handoffParameter=$ast.ParamBlock.Parameters|Where-Object{$_.Name.VariablePath.UserPath-eq'PrismHandoffReplayManifest'}
$PrismHandoffReplayManifest=$handoffParameter.DefaultValue.SafeGetValue()
if($PrismHandoffReplayManifest-cne''){throw 'Prepared fixture requires the actual empty public handoff default'}
foreach($name in @('Invoke-PreparedOriginalStagedWorkflow','New-CenterTrialArguments')){
 $node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)
 Invoke-Expression $node.Extent.Text
}
$repoRoot=$Root;$artifactRoot=$Root;$artifactWorkspaceRoot=$Root;$project='parallel_mirror_dual_stripe_mr_tof'
$trialArtifactRoot=$artifactRoot
$inputFile=Join-Path $Root 'input.json';'{}'|Set-Content $inputFile
$PreparedJointWorkbenchRunPath=$Root;$PreparedPrism1ResponseBasisPath=$inputFile;$PreparedPrism2ResponseBasisPath=$inputFile
$PreparedInitialProposalPath=$inputFile;$PreparedTargetAuthorityPath=$inputFile;$PreparedSeedTrialManifest=$inputFile
$PSScriptRoot=$Root
$PreparedStripe1ResponseBasisPath='';$ContractPath=$inputFile;$RunId='prepared-parent';$python='mock-python'
$ResumeParentCheckpoint='';$ResumeSuccessfulChildManifest='';$PreparedTargetReanchor=$false
$PreparedFieldBuildMode=$BuildMode
$preparedCallerParameters=@();$PrismControllerPolicyPath='';$frozenPrismControllerPolicyPath=''
$preparedProviderRunner='public-provider';$SimionExe='';$script:preparedStagedMode=$true
function Write-RunJson {param($Path,$Depth,$Value)$Value|ConvertTo-Json -Depth 100|Set-Content $Path}
function New-RunPackage {
 $i=Join-Path $Root 'inputs';$o=Join-Path $Root 'results';New-Item -ItemType Directory -Path $i,$o|Out-Null
 $c=Join-Path $Root 'run_config.json';'{}'|Set-Content $c
 return @{input_dir=$i;result_dir=$o;run_config=$c;artifact_run_dir=$Root;summary=(Join-Path $Root 'summary.json')}
}
function Enter-ArtifactWorkflowCapacitySession {return @{id='public'}}
function Exit-ArtifactWorkflowCapacitySession {$script:exited=$true}
function Copy-VerifiedRunInput {param($Source,$Destination)'frozen-source'|Set-Content $Destination;return $Destination}
function Invoke-RunToolRootContext {param($RepoRoot,$Operation)&$Operation}
function mock-python {
 if($args[1]-match 'prepare_measured_centroid_acquisition'){
  $i=$args[-1];'{}'|Set-Content (Join-Path $i 'trajectory_contract.json');'{}'|Set-Content (Join-Path $i 'initial_proposal.json')
  $request=@{source_binding_path='baseline-binding';response_basis_paths=@{p1='P1';p2='P2'}}
  if($BuildMode-eq'refine'){
    foreach($key in @('response_axis','te1_reference_path','consumer_view_source_path','reuse_source_levels')){$request[$key]='must-not-survive'}
  }
  $request|ConvertTo-Json|Set-Content (Join-Path $i 'acquisition_field_request.json')
 }elseif($args[1]-match 'load_prepared_centroid_trial'){
  if($args[-2]-ne'__none__'-or$args[-1]-ne$BuildMode){throw 'Source/mode argument lost'}
  '{"mode":"native_static_pa"}'
 }elseif($args[1]-ne'common.contracts.verify_run_manifest'){throw 'Unexpected Python entry'}
 $global:LASTEXITCODE=0
}
function Invoke-StagedWorkpointBootstrap {
 param($Bootstrap,$BootstrapPath)
 if($controllerContext.prism_handoff_replay_manifest-cne$PrismHandoffReplayManifest){throw 'Prepared Context lost the public parameter default'}
 if($Bootstrap.source_projection-ne'measured_exit_centroid'-or$Bootstrap.Contains('stage_state')){throw 'Not a fresh measured P anchor'}
 if((Get-Content $frozenPreparedTargetAuthorityPath -Raw).Trim()-ne'{}'){throw 'Target not frozen'}
 if($fieldProviderRequest.source_binding_path-ne'baseline-binding'){throw 'Wrong fixed rebuild authority'}
 if($BuildMode-eq'refine'){
   foreach($key in @('response_basis_paths','response_axis','te1_reference_path','consumer_view_source_path','reuse_source_levels')){
     if($fieldProviderRequest.Contains($key)){throw "Direct request retained $key"}
   }
 }elseif(-not$fieldProviderRequest.response_basis_paths.Contains('p1')){throw 'Default composition changed'}
 $a=New-CenterTrialArguments -Voltages @(1,0,343,-186) -ChildRunId 'candidate'
 if($a.PreparedSourceMode-ne'centroid_probe'-or$a.Contains('AcceleratorProviderReceiptPath')){throw 'Wrong actual source branch'}
 return @{terminal_decision=@{state='checkpoint';terminal_reason='needs_s1_response';full_workpoint_qualified=$false}}
}
function Apply-RunArtifactRetention {return $inputFile}
function Write-RunManifest {param($Status)if($Status-ne'success'){throw ('Unexpected publisher status: '+(Get-Content $package.summary -Raw))}}
Invoke-PreparedOriginalStagedWorkflow
if(-not$exited){throw 'Public session not exited'}
$summary=Get-Content (Join-Path $Root 'summary.json') -Raw|ConvertFrom-Json
if($summary.N100_executed-or$summary.gui_executed-or$summary.final_decision.full_workpoint_qualified){throw 'False qualification'}
'PREPARED_ORIGINAL_STAGES_PASS'
'''
        for mode in ("composition","refine"):
            with self.subTest(mode=mode),TemporaryDirectory() as directory:
                root=Path(directory);path=root/"stages.ps1";path.write_text(script)
                result=subprocess.run(["pwsh","-NoProfile","-File",str(path),str(PROJECT/"analysis/run_downstream_workpoint_iteration.ps1"),str(root),mode],
                    cwd=PROJECT.parents[1],capture_output=True,text=True,encoding="utf-8",timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn("PREPARED_ORIGINAL_STAGES_PASS",result.stdout)
                config=json.loads((root/"run_config.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(config["parameters"]["field_build_mode"],mode)
                template=json.loads(Path(config["inputs"]["candidate_field_request_template"]).read_text(encoding="utf-8-sig"))
                self.assertEqual("response_basis_paths" in template,mode=="composition")

    def test_prepared_acquisition_calls_public_provider_and_n1_then_checkpoints(self):
        script=r'''
param($Source,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-PreparedWorkpointAcquisition'},$true)
Invoke-Expression $node.Extent.Text
$repoRoot=$Root;$artifactRoot=Join-Path $Root 'artifacts';$artifactWorkspaceRoot=$artifactRoot;$project='parallel_mirror_dual_stripe_mr_tof'
$trialArtifactRoot=$artifactRoot
$python='mock-python';$RunId='test-parent';$SimionExe='';$PSScriptRoot=Join-Path $Root 'analysis'
New-Item -ItemType Directory -Path $PSScriptRoot,(Join-Path $Root 'simion')|Out-Null
$input=Join-Path $Root 'input.json';'{}'|Set-Content $input
$PreparedJointWorkbenchRunPath=$Root;$PreparedPrism1ResponseBasisPath=$input;$PreparedPrism2ResponseBasisPath=$input;$PreparedInitialProposalPath=$input;$ContractPath=$input
$preparedCallerParameters=@('PreparedJointWorkbenchRunPath','PreparedPrism1ResponseBasisPath','PreparedPrism2ResponseBasisPath','PreparedInitialProposalPath','ContractPath','RunId')
function Write-RunJson {param($Path,$Depth,$Value)$Value|ConvertTo-Json -Depth 100|Set-Content $Path}
function New-RunPackage {
 $r=Join-Path $Root 'parent';$i=Join-Path $r 'inputs';$o=Join-Path $r 'results';New-Item -ItemType Directory -Path $i,$o|Out-Null
 $cfg=Join-Path $r 'run_config.json';'{}'|Set-Content $cfg
 return @{artifact_run_dir=$r;input_dir=$i;result_dir=$o;run_config=$cfg;summary=(Join-Path $r 'summary.json')}
}
function Enter-ArtifactWorkflowCapacitySession {return @{status='active'}}
function Exit-ArtifactWorkflowCapacitySession {$script:exited=$true}
function Apply-RunArtifactRetention {return 'mock-retention.json'}
function Write-RunManifest {param($Status)$script:terminal=$Status}
function Invoke-RunToolRootContext {
 # The pure Python API has its own tests. Here exercise actual public-stage
 # control flow without invoking a commercial process or replacing the body.
 '{}'|Set-Content (Join-Path $Root 'parent/inputs/acquisition_field_request.json')
}
$provider=Join-Path $Root 'simion/run_native_static_field_provider.ps1'
$preparedProviderRunner=$provider
@'
param($RequestPath,$RunDirectory,[switch]$Approved)
if(-not$Approved-or-not(Test-Path $RequestPath)){throw 'Public provider request missing'}
New-Item -ItemType Directory -Path $RunDirectory -Force|Out-Null
@{status='success';field_binding='actual-candidate-binding.json'}|ConvertTo-Json|Set-Content (Join-Path $RunDirectory 'summary.json')
'public-compose'|Set-Content (Join-Path (Split-Path (Split-Path $RunDirectory -Parent) -Parent) 'provider-called.txt')
'@|Set-Content $provider
$trialRunner=Join-Path $Root 'trial.ps1'
@'
param($PreparedJointWorkbenchRunPath,$PreparedSourceMode,$FieldBindingPath,$ContractPath,$RunId,$PythonExe)
if($PreparedSourceMode-ne'centroid_probe'-or$FieldBindingPath-ne'actual-candidate-binding.json'){throw 'Probe source or actual field was replaced'}
$child=Join-Path $PreparedJointWorkbenchRunPath ('artifacts/runs/'+$RunId+'/results/diagnostics')
New-Item -ItemType Directory -Path $child -Force|Out-Null
@{observation=@{events=@(@{kind='terminal';ion=1;splat=-1})}}|ConvertTo-Json -Depth 100|Set-Content (Join-Path $child 'controller_projection.json')
'@|Set-Content $trialRunner
Invoke-PreparedWorkpointAcquisition
$checkpoint=Get-Content (Join-Path $Root 'parent/results/prepared_acquisition_checkpoint.json') -Raw|ConvertFrom-Json
if($checkpoint.state-ne'needs_clean_reference_audit_and_target_authority'-or$checkpoint.full_workpoint_qualified-or$checkpoint.target_assigned){throw 'Acquisition incorrectly claimed closure'}
if($checkpoint.observation.events[0].splat-ne-1){throw 'Real collision evidence was discarded'}
if($script:terminal-ne'success'-or-not$script:exited){throw 'Public lifecycle did not publish the stage'}
'PREPARED_ACQUISITION_STAGE=PASS'
'''
        with TemporaryDirectory() as directory:
            root=Path(directory);path=root/"mock.ps1";path.write_text(script)
            result=subprocess.run(["pwsh","-NoProfile","-File",str(path),str(PROJECT/"analysis/run_downstream_workpoint_iteration.ps1"),str(root)],
                cwd=PROJECT.parents[1],capture_output=True,text=True,encoding="utf-8",timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn("PREPARED_ACQUISITION_STAGE=PASS",result.stdout)

    def test_normal_and_resumed_candidate_completion_transport_quality_authority(self):
        script = r'''
param($Source)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$normal=$ast.Find({param($n)$n-is[Management.Automation.Language.CommandAst]-and$n.GetCommandName()-eq'Complete-StagedTrial'-and$n.Extent.Text.Contains('-Pending $state.pending_trial')},$true)
if($null-eq$normal){throw 'Normal candidate completion call is missing'}
$controllerContext=@{};$ControllerPolicyPath='sealed-policy.json';$state=@{pending_trial=@{}};$pending=$state.pending_trial;$history=@{};$lineage=@{};$loop=@{};$tiers=@()
function Complete-StagedTrial {param($State,$History,$Lineage,$Pending,$Loop,$Tiers,$ControllerPolicyPath,$Context)$script:captured=$ControllerPolicyPath}
Invoke-Expression $normal.Extent.Text
if($script:captured-ne$ControllerPolicyPath){throw 'Normal candidate completion omitted prediction authority'}
$resumed=$ast.Find({param($n)$n-is[Management.Automation.Language.CommandAst]-and$n.GetCommandName()-eq'Complete-StagedTrial'-and$n.Extent.Text.Contains('-Pending $pending')-and$n.Extent.Text.Contains('-ControllerPolicyPath')},$true)
Invoke-Expression $resumed.Extent.Text
if($script:captured-ne$ControllerPolicyPath){throw 'Resumed candidate completion omitted prediction authority'}
'COMPLETION_POLICY_TRANSPORT=PASS'
'''
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "calls.ps1"
            path.write_text(script)
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(path),
                str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1")],
                cwd=PROJECT.parents[1], capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("COMPLETION_POLICY_TRANSPORT=PASS", result.stdout)

    def test_staged_handoff_context_rebinds_to_frozen_input_before_decision(self):
        script = r'''
param($Source,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$freeze=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and$n.Extent.Text.StartsWith('if($PrismHandoffReplayManifest)')-and$n.Extent.Text.Contains("'prism_handoff_replay_manifest.json'")},$true)
$helper=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-PreclosureDecision'},$true)
Invoke-Expression $helper.Extent.Text
$inputs=Join-Path $Root 'inputs';New-Item -ItemType Directory $inputs|Out-Null
$original=Join-Path $Root 'original.json';'{"marker":"frozen"}'|Set-Content $original
$PrismHandoffReplayManifest=$original;$package=@{input_dir=$inputs}
$controllerContext=@{repo_root=$Root;python='Invoke-MockController';contract_path='contract.json';prepared_staged=$false;prism_handoff_replay_manifest=$original}
function Copy-VerifiedRunInput {param($Source,$Destination)Copy-Item -LiteralPath $Source -Destination $Destination;return $Destination}
function Invoke-RunToolRootContext {param($RepoRoot,$Operation)&$Operation}
function Invoke-MockController {
 param([Parameter(ValueFromRemainingArguments=$true)][object[]]$Arguments)
 $handoff=$Arguments[[array]::IndexOf($Arguments,'--prism-handoff-replay-manifest')+1]
 if($handoff-ne(Join-Path $inputs 'prism_handoff_replay_manifest.json')){throw 'Decision read unfrozen handoff path'}
 if((Get-Content $handoff -Raw|ConvertFrom-Json).marker-ne'frozen'){throw 'Decision read changed external authority'}
 '{}'|Set-Content $Arguments[[array]::IndexOf($Arguments,'--output')+1]
 $global:LASTEXITCODE=0
}
Invoke-Expression $freeze.Extent.Text
'{"marker":"changed"}'|Set-Content $original
Invoke-PreclosureDecision -Context $controllerContext -Stage stripe_preclosure -Anchor child -Columns @{} -OutputPath (Join-Path $Root 'decision.json')|Out-Null
'FROZEN_HANDOFF_CONTEXT=PASS'
'''
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'handoff.ps1'
            path.write_text(script, encoding='utf-8')
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(path),
                str(PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1'), str(root)],
                cwd=PROJECT.parents[1], capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('FROZEN_HANDOFF_CONTEXT=PASS', result.stdout)

    def test_accepted_staged_candidate_quality_controls_next_step_factor(self):
        script = r'''
param($Source,$Root,$Quality,$Repo,$RealPython)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Complete-StagedTrial'},$true);Invoke-Expression $node.Extent.Text
$transport=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-WorkpointControllerRequest'},$true)
Invoke-Expression ($transport.Extent.Text.Replace('function Invoke-WorkpointControllerRequest','function Invoke-RealControllerRequest'))
function Invoke-WorkpointControllerRequest {param($Request,$Python,$RepoRoot) Invoke-RealControllerRequest -Request $Request -Python $RealPython -RepoRoot $Repo}
foreach($name in @('Invoke-PreclosureDecision','Assert-StagedComposeProviderReference')){
 $node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true);Invoke-Expression $node.Extent.Text
}
$child=Join-Path $Root 'child.json';@{status='success';run_id='parent-stage-003'}|ConvertTo-Json|Set-Content $child
$mat=Join-Path $Root 'mat.json';@{stripe_biases_v=@(-27.,0.);prism_voltages_v=@(190.,-190.)}|ConvertTo-Json|Set-Content $mat
function Get-ManifestOutputPath {param($ManifestPath,$FileName)$mat}
function Invoke-RunToolRootContext {param($RepoRoot,$Operation)& $Operation}
function Invoke-MockPython {
 param([Parameter(ValueFromRemainingArguments=$true)][object[]]$Arguments)
 $global:LASTEXITCODE=0
 if($Arguments-contains'--control-stage'){
  foreach($pair in @(@('--contract','contract.json'),@('--prepared-target-authority','target.json'),@('--prepared-initial-proposal','proposal.json'),@('--prism-handoff-replay-manifest','handoff.json'))){
   $index=[array]::IndexOf($Arguments,$pair[0]);if($index-lt0-or$Arguments[$index+1]-ne$pair[1]){throw 'Decision read ambient authority instead of Context'}
  }
  $output=$Arguments[[array]::IndexOf($Arguments,'--output')+1]
  @{status='needs_stencil';next_action='measure_stencil';full_workpoint_qualified=$false;maximum_scaled_abs_residual=2.}|ConvertTo-Json|Set-Content $output
  return
 }
 @{status=$Quality}|ConvertTo-Json -Compress
}
function Write-RunJson {param($Path,$Depth,$Value)$Value|ConvertTo-Json -Depth $Depth|Set-Content $Path}
$context=@{repo_root=$Root;python='Invoke-MockPython';contract_path='contract.json';result_directory=$Root;prepared_staged=$true;target_authority_path='target.json';initial_proposal_path='proposal.json';prism_handoff_replay_manifest='handoff.json';run_id='parent';artifact_root=$Root;prepared_field_build_mode='composition'}
$script:preparedStagedMode=$false;$script:frozenPreparedTargetAuthorityPath='wrong-target';$script:frozenPreparedInitialProposalPath='wrong-proposal'
$script:PrismHandoffReplayManifest='wrong-handoff';$script:RunId='wrong-parent';$script:artifactRoot='wrong-artifact-root'
$provider=Join-Path $Root 'runs/parent-stage-003-field';New-Item -ItemType Directory -Path $provider -Force|Out-Null
$providerManifest=Join-Path $provider 'run_manifest.json';'{}'|Set-Content $providerManifest
$request=Join-Path $provider 'request.json';'{}'|Set-Content $request
$reference=@{parent_run_id='parent';child_run_id='parent-stage-003';operation='compose';provider_run=$provider;provider_manifest=$providerManifest;request_path=$request;provider_manifest_sha256=(Get-FileHash $providerManifest).Hash.ToLowerInvariant();request_sha256=(Get-FileHash $request).Hash.ToLowerInvariant()}
$state=@{stage='stripe_preclosure';anchor_manifest='anchor';flight_count=3;candidate_count=1;columns=@{};attempts=@();step_factor=.5;completion_attempted=$false}
$pending=@{provider_reference=$reference;child_manifest=$child;child_run_id='parent-stage-003';anchor_manifest='anchor';stage='stripe_preclosure';voltages_v=@(-27.,0.,190.,-190.);decision=@{status='proposed';next_action='run_S_candidate';maximum_scaled_abs_residual=4.;backtrack_multiplier=.5}}
$state.pending_trial=$pending;$history=@{decisions=@()};$lineage=@{children=@()}
Complete-StagedTrial -Context $context -State $state -History $history -Lineage $lineage -Pending $pending -Loop @{minimum_relative_improvement=.01} -Tiers @() -ControllerPolicyPath 'policy.json'
@{factor=$state.step_factor;anchor=$state.anchor_manifest;quality=$state.prediction_assessment.status;history_quality=$history.decisions[0].prediction_assessment.status;flight=$state.flight_count;candidate=$state.candidate_count}|ConvertTo-Json -Compress
'''
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "quality.ps1"
            path.write_text(script)
            for quality, factor in (("trusted", 1.), ("poor", .25), ("unmeasured", 1.)):
                result = subprocess.run(["pwsh", "-NoProfile", "-File", str(path),
                    str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"), str(root), quality, str(PROJECT.parents[1]), sys.executable],
                    cwd=PROJECT.parents[1], capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                value = json.loads(result.stdout)
                self.assertEqual(value["factor"], factor)
                self.assertEqual(value["anchor"], str(root / "child.json"))
                self.assertEqual(value["quality"], quality)
                self.assertEqual(value["history_quality"], quality)
                self.assertEqual((value["flight"], value["candidate"]), (3, 1))

    def test_actual_controller_only_resume_keeps_pending_and_physics_identity(self):
        parent = PROJECT.parents[1].parent / "artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_124957__sim__simion__converging-te1-reclose-01-resume__r03"
        if not (parent / "run_manifest.json").exists():
            self.skipTest("sealed local TE1 resume evidence is unavailable")
        old = json.loads((parent / "inputs/contract.json").read_text(encoding="utf-8-sig"))
        new = json.loads(json.dumps(old))
        new["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"].update(
            advance_multiplier=1., maximum_iterations=6)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "new.json"
            contract.write_text(json.dumps(new))
            script = r'''
param($Source,$Parent,$Contract,$Python,$RepoRoot)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
foreach($name in @('Invoke-WorkpointControllerRequest','Get-ActiveStripeAxisIndices','Get-StagedColumnAxisIndices','Assert-ActiveStripeVoltages','Restore-StagedWorkpointChildren')){
 $node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true);Invoke-Expression $node.Extent.Text
}
function Save-WorkpointBootstrap {param($Bootstrap,$BootstrapPath)}
$b=Get-Content (Join-Path $Parent 'results/workpoint_bootstrap.json') -Raw|ConvertFrom-Json -AsHashtable
$seedManifest=$b.seed_manifest;$frozenContract=$Contract
$sourceLineage=$b.stage_lineage|ConvertTo-Json -Depth 100|ConvertFrom-Json -Depth 100
$before=$b|ConvertTo-Json -Depth 100 -Compress
Restore-StagedWorkpointChildren -Bootstrap $b -SourceLineage $sourceLineage -BootstrapPath unused -PriorState $b.stage_state
if(($b|ConvertTo-Json -Depth 100 -Compress)-ne$before){throw 'Actual resume rewrote pending, history, columns, anchor or debits'}
@{flight=$b.stage_state.flight_count;candidate=$b.stage_state.candidate_count;pending=$b.stage_state.pending_trial.child_run_id}|ConvertTo-Json -Compress
'''
            path = root / "actual.ps1"
            path.write_text(script)
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(path),
                str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"), str(parent), str(contract), sys.executable, str(PROJECT.parents[1])],
                cwd=PROJECT.parents[1], capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual((value["flight"], value["candidate"]), (10, 4))
            self.assertTrue(value["pending"].endswith("r03-stage-010"))
            from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint import _trajectory_physics_identity
            old_path = parent / "inputs/contract.json"
            from common.contracts.file_identity import file_sha256
            identities = []
            for p in (old_path, contract):
                sha = file_sha256(p)
                identities.append(_trajectory_physics_identity({"inputs": {"trajectory_numerics_contract": {
                    "path": str(p), "bytes": p.stat().st_size, "sha256": sha}}}, sha))
            self.assertEqual(*identities)

    def test_bounded_controller_resume_guard_records_both_contracts_without_rewriting_pending(self):
        old = {"source": 5.374, "downstream_fixed_grid_workpoint_profile": {"automatic_iteration": {
            "damping_factor": .5, "maximum_iterations": 5}}}
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "old.json").write_text(json.dumps(old))
            state = dict(stage_state=dict(candidate_count=5, flight_count=12,
                                          pending_trial=dict(voltages_v=[1, 2], decision=dict(advance=.5))))
            (root / "bootstrap.json").write_text(json.dumps(state))
            script = r'''
param($Source,$Root,$Repo,$Python,$Kind)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and$n.Extent.Text.StartsWith('if((Get-FileHash $oldPath')},$true)
$oldPath=Join-Path $Root 'old.json';$pair=@($Kind,(Join-Path $Root 'new.json'))
$resumeBootstrapPath=Join-Path $Root 'bootstrap.json';$repoRoot=$Repo;$python=$Python
$configuration=@{inputs=@{contract=$pair[1]};parameters=@{}};$package=@{run_config=(Join-Path $Root 'config.json')}
function Invoke-RunToolRootContext {param($RepoRoot,$Operation)Push-Location $RepoRoot;try{& $Operation}finally{Pop-Location}}
function Write-RunJson {param($Path,$Depth,$Value)$Value|ConvertTo-Json -Depth $Depth|Set-Content $Path}
$errorText=$null
try{Invoke-Expression $node.Extent.Text}catch{$errorText=$_.Exception.Message}
@{failure=$errorText;config=$configuration;state=(Get-Content $resumeBootstrapPath -Raw|ConvertFrom-Json -AsHashtable)}|ConvertTo-Json -Depth 100
'''
            path = root / "guard.ps1"
            path.write_text(script)
            for scenario in ("allowed", "same", "source_record", "other_physics", "too_many"):
                new = json.loads(json.dumps(old))
                if scenario != "same":
                    new["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"].update(
                        advance_multiplier=1., maximum_iterations=6)
                if scenario == "other_physics":
                    new["source"] = 6.
                if scenario == "too_many":
                    new["downstream_fixed_grid_workpoint_profile"]["automatic_iteration"]["maximum_iterations"] = 7
                (root / "new.json").write_text(json.dumps(new))
                with self.subTest(scenario=scenario):
                    result = subprocess.run(["pwsh", "-NoProfile", "-File", str(path),
                        str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"), str(root),
                        str(PROJECT.parents[1]), sys.executable,
                        "center_source_receipt" if scenario == "source_record" else "contract"],
                        cwd=PROJECT.parents[1], capture_output=True, text=True, encoding="utf-8", timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    value = json.loads(result.stdout)
                    self.assertEqual(value["state"], state)
                    if scenario in ("allowed", "same"):
                        self.assertIsNone(value["failure"])
                    else:
                        self.assertIsNotNone(value["failure"])
                    if scenario == "allowed":
                        self.assertEqual(value["config"]["inputs"]["previous_controller_contract"], str(root / "old.json"))
                        self.assertEqual(value["config"]["parameters"]["controller_resume_changes"]["preserved_candidate_count"], 5)

    def _restore_saved_checkpoint(self, scenario):
        """Exercise saved-state restore and normal pending consumption without a solver."""
        script = r'''
param($Source,$Root,$Scenario,$Repo,$RealPython)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
foreach($name in @('Get-ActiveStripeAxisIndices','Get-StagedColumnAxisIndices','Assert-ActiveStripeVoltages','Restore-StagedWorkpointChildren','Complete-StagedTrial','Invoke-StagedWorkpointBootstrap')){
 $node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)
 Invoke-Expression $node.Extent.Text
}
$transport=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-WorkpointControllerRequest'},$true)
Invoke-Expression ($transport.Extent.Text.Replace('function Invoke-WorkpointControllerRequest','function Invoke-RealControllerRequest'))
$script:restoreRequests=0
function Invoke-WorkpointControllerRequest {param($Request,$Python,$RepoRoot)
 if($Request.action-eq'restored_stage_columns'){$script:restoreRequests++}
 Invoke-RealControllerRequest -Request $Request -Python $RealPython -RepoRoot $Repo
}
$seedManifest=Join-Path $Root 'seed.json';'{}'|Set-Content $seedManifest
$policyPath=Join-Path $Root 'old-policy.json';'{"trusted_advance_multiplier":0.5}'|Set-Content $policyPath
$futurePolicy=Join-Path $Root 'future-policy.json';'{"trusted_advance_multiplier":1.0}'|Set-Content $futurePolicy
$artifactRoot=$Root;$repoRoot=$Root;$RunId='new';$python='Invoke-IdentityFixture'
$trialArtifactRoot=$artifactRoot
$PrismHandoffReplayManifest='';$PriorPrismDecisionManifest='';$stripeSeedColumns=@{}
$package=@{result_dir=$Root};$frozenContract=Join-Path $Root 'contract.json'
$controllerContext=@{repo_root=$repoRoot;python=$python;contract_path=$frozenContract;result_directory=$Root;prepared_staged=$false;target_authority_path=''}
@{downstream_fixed_grid_workpoint_profile=@{active_stripe_axes=@('stripe_1_voltage_v','stripe_2_voltage_v');automatic_iteration=@{maximum_iterations=8;minimum_relative_improvement=.1;maximum_consecutive_non_improving_iterations=3};jacobian_relative_step_tiers=@{coarse=.01;medium=.0025;fine=.0005}}}|ConvertTo-Json -Depth 10|Set-Content $frozenContract
$childDir=New-Item -ItemType Directory (Join-Path $Root 'child')
$child=Join-Path $childDir 'run_manifest.json';@{run_id='child';status='success'}|ConvertTo-Json|Set-Content $child
$u=@(-27.,54.,189.,-190.);$target=@(-28.,56.,189.,-190.)
$entry=@{iteration=1;run_id='child';child_manifest=$child;child_manifest_sha256=(Get-FileHash $child).Hash.ToLowerInvariant();parent_manifest=$seedManifest;prism_controller_policy=@{path=$policyPath;sha256=(Get-FileHash $policyPath).Hash.ToLowerInvariant()}}
$lineage=@{schema_version=1;role='mrtof_downstream_workpoint_iteration_lineage';root_workpoint_manifest=@{path=$seedManifest;sha256=(Get-FileHash $seedManifest).Hash.ToLowerInvariant()};children=@($entry)}
$history=@{schema_version=1;role='mrtof_downstream_workpoint_iteration_history';decisions=@(@{status='proposed';prism_controller_policy=$entry.prism_controller_policy})}
$state=@{stage='stripe_preclosure';anchor_manifest=$child;columns=@{};attempts=@();flight_count=2;candidate_count=2;step_factor=.5;completion_attempted=$false;local_model_tier_index=0;consecutive_candidate_rejections=0}
$pendingDir=New-Item -ItemType Directory (Join-Path $Root 'old-pending')
$pending=Join-Path $pendingDir 'run_manifest.json'
@{status=$(if($Scenario-eq'success'){'success'}else{'failed'});run_id='pending'}|ConvertTo-Json|Set-Content $pending
@{stripe_biases_v=@(-28.,56.);prism_voltages_v=@(189.,-190.)}|ConvertTo-Json|Set-Content (Join-Path $pendingDir 'two_prism_trial_materialization.json')
$state.pending_trial=@{child_manifest=$pending;child_run_id='pending';anchor_manifest=$child;stage=$state.stage;voltages_v=$target;selected=$null;decision=@{status='proposed';next_action='run_S_candidate';voltages_v=$u;next_voltages_v=@(-29.,58.,189.,-190.);maximum_scaled_abs_residual=10.;backtrack_multiplier=.5;prism_controller_policy=$entry.prism_controller_policy}}
switch($Scenario){
 'missing' {Remove-Item $pending}
 'bad_anchor' {$state.anchor_manifest='absent'}
 'bad_column' {$state.columns['0']='absent'}
 'bad_model' {$state.prism_model_manifest=Join-Path $Root 'absent-model/run_manifest.json'}
 'bad_budget' {$state.flight_count=1}
 'bad_voltage' {$state.pending_trial.voltages_v[0]=-29.}
 'bad_policy' {'changed'|Set-Content $policyPath}
 'bad_child' {$entry.child_manifest_sha256='bad'}
 'future_policy' {$state.Remove('pending_trial');$state.flight_count=1;$state.candidate_count=1;$state.stage='prism_preclosure'}
 'inactive_s2_column' {
  $config=Get-Content $frozenContract -Raw|ConvertFrom-Json -AsHashtable
  $config.downstream_fixed_grid_workpoint_profile.active_stripe_axes=@('stripe_1_voltage_v')
  $config|ConvertTo-Json -Depth 10|Set-Content $frozenContract
  $columnDir=New-Item -ItemType Directory (Join-Path $Root 'column')
  $column=Join-Path $columnDir 'run_manifest.json'
  @{run_id='column';status='success'}|ConvertTo-Json|Set-Content $column
  $lineage.children+=,@{iteration=2;run_id='column';parent_manifest=$child;child_manifest=$column;child_manifest_sha256=(Get-FileHash $column).Hash.ToLowerInvariant()}
  $state.Remove('pending_trial');$state.columns['1']=$column
 }
 'joint_columns' {
  $config=Get-Content $frozenContract -Raw|ConvertFrom-Json -AsHashtable
  $config.downstream_fixed_grid_workpoint_profile.active_stripe_axes=@('stripe_1_voltage_v')
  $config.downstream_fixed_grid_workpoint_profile.single_stripe_refinement_mode='joint_ps_constrained'
  $config|ConvertTo-Json -Depth 10|Set-Content $frozenContract
  $state.Remove('pending_trial');$state.flight_count=4;$state.candidate_count=1
  $iteration=1
  foreach($axis in @(0,2,3)){
   $iteration++
   $columnDir=New-Item -ItemType Directory (Join-Path $Root "column$axis")
   $column=Join-Path $columnDir 'run_manifest.json'
   @{run_id="column$axis";status='success'}|ConvertTo-Json|Set-Content $column
   $lineage.children+=,@{iteration=$iteration;run_id="column$axis";parent_manifest=$child;child_manifest=$column;child_manifest_sha256=(Get-FileHash $column).Hash.ToLowerInvariant()}
   $state.columns[[string]$axis]=$column
  }
 }
 'joint_p_rejected' {
  $config=Get-Content $frozenContract -Raw|ConvertFrom-Json -AsHashtable
  $config.downstream_fixed_grid_workpoint_profile.active_stripe_axes=@('stripe_1_voltage_v')
  $config.downstream_fixed_grid_workpoint_profile.single_stripe_refinement_mode='joint_ps_constrained'
  $config|ConvertTo-Json -Depth 10|Set-Content $frozenContract
  $state.pending_trial.voltages_v[1]=0.
  $state.pending_trial.decision.voltages_v[1]=0.
  $state.pending_trial.decision.next_voltages_v[1]=0.
  @{stripe_biases_v=@(-28.,0.);prism_voltages_v=@(189.,-190.)}|ConvertTo-Json|Set-Content (Join-Path $pendingDir 'two_prism_trial_materialization.json')
  $state.pending_trial.decision.refinement_mode='joint_ps_constrained'
 }
}
if($Scenario-like'abandoned*'){
 $state.pending_trial.child_manifest=Join-Path $Root 'never-created/run_manifest.json'
 $originalCheckpoint=Join-Path $Root 'original-checkpoint.json'
 @{stage_state=$state}|ConvertTo-Json -Depth 100|Set-Content $originalCheckpoint
 $stopPath=Join-Path $Root 'stopped-summary.json'
 @{stopped_parent_verified_absent=$true;stopped_children_verified_absent=$true;pending_trial_executed=$false}|ConvertTo-Json|Set-Content $stopPath
 $abandoned=@{flight_count=2;pending_trial=$state.pending_trial
  source_checkpoint=@{path=$originalCheckpoint;bytes=(Get-Item $originalCheckpoint).Length;sha256=(Get-FileHash $originalCheckpoint).Hash}
  stopped_parent_summary=@{path=$stopPath;bytes=(Get-Item $stopPath).Length;sha256=(Get-FileHash $stopPath).Hash}}
 $state.Remove('pending_trial')|Out-Null;$state.target_reanchor=@{abandoned_pending=$abandoned}
 if($Scenario-eq'abandoned_tampered'){'{}'|Set-Content $stopPath}
 if($Scenario-eq'abandoned_reset'){$state.flight_count=1}
 if($Scenario-eq'abandoned_after_child'){
  $next=Join-Path $Root 'next-manifest.json';@{status='success';run_id='next'}|ConvertTo-Json|Set-Content $next
  $lineage.children+=,@{iteration=3;run_id='next';parent_manifest=$child;child_manifest=$next;child_manifest_sha256=(Get-FileHash $next).Hash.ToLowerInvariant()}
  $state.anchor_manifest=$next;$state.flight_count=3
 }
}
$bootstrap=@{stage_state=$state;stage_history=$history;stage_lineage=$lineage}
$sourceLineage=$lineage|ConvertTo-Json -Depth 100|ConvertFrom-Json -Depth 100
$script:saves=0;$script:flights=@();$script:consumptions=0;$script:futurePolicies=@()
function Save-WorkpointBootstrap {param($Bootstrap,$BootstrapPath) $script:saves++}
function Write-RunJson {param($Path,$Depth,$Value) $Value|ConvertTo-Json -Depth $Depth|Set-Content $Path}
function Get-ManifestOutputPath {param($ManifestPath,$FileName)
 $path=Join-Path (Split-Path $ManifestPath) $FileName
 if(-not(Test-Path $path)){throw 'Saved model or child output is missing'}
 return $path
}
function Invoke-RunToolRootContext {param($RepoRoot,$Operation) & $Operation}
function Invoke-IdentityFixture {
 param([Parameter(ValueFromRemainingArguments=$true)][object[]]$Arguments)
 $global:LASTEXITCODE=0
 if([string]$Arguments[1]-like'*assess_staged_prediction*'){@{status='unmeasured';reason='fixture identity boundary'}|ConvertTo-Json -Compress}
}
function Invoke-StagedPreclosureDecision {param($State,$OutputPath,$ControllerPolicyPath)
 $script:futurePolicies+=,$ControllerPolicyPath
 return @{status='terminal';terminal_reason='stop_fixture';full_workpoint_qualified=$false}
}
function Invoke-PreclosureDecision {param($Stage,$Anchor,$Columns,$OutputPath,$Context)
 $script:consumptions++
 if($Scenario-eq'joint_p_rejected'){return @{status='stage_required';next_action='prism_preclosure';full_workpoint_qualified=$false;maximum_scaled_abs_residual=2.}}
 return @{status='terminal';next_action='stop_preclosure';terminal_reason='success';full_workpoint_qualified=$true;maximum_scaled_abs_residual=0.}
}
function New-CenterTrialArguments {param($Voltages,$ChildRunId) @{Voltages=$Voltages;ChildRunId=$ChildRunId}}
function Invoke-CenterTrial {param($Arguments,$StagedPending,$Bootstrap,$BootstrapPath)
 $script:flights+=,$Arguments
 $dir=New-Item -ItemType Directory (Join-Path $Root ('runs/'+$Arguments.ChildRunId))
 @{run_id=$Arguments.ChildRunId;status='success'}|ConvertTo-Json|Set-Content (Join-Path $dir 'run_manifest.json')
 @{stripe_biases_v=@($Arguments.Voltages[0],$Arguments.Voltages[1]);prism_voltages_v=@($Arguments.Voltages[2],$Arguments.Voltages[3])}|ConvertTo-Json|Set-Content (Join-Path $dir 'two_prism_trial_materialization.json')
}
function Reclaim-StagedComposeProviders {param($State,$Lineage)}
$before=$bootstrap|ConvertTo-Json -Depth 100 -Compress;$errorText=$null;$restored=$null
try{
 Restore-StagedWorkpointChildren -Bootstrap $bootstrap -SourceLineage $sourceLineage -PriorState $state -BootstrapPath unused -DeferSave:($Scenario-eq'deferred_save')
 $restored=$bootstrap|ConvertTo-Json -Depth 100|ConvertFrom-Json -AsHashtable
 if(($bootstrap|ConvertTo-Json -Depth 100 -Compress)-ne$before){throw 'Restore rewrote saved state'}
 if($Scenario-in@('success','failed','missing','future_policy','joint_p_rejected')){
  $null=Invoke-StagedWorkpointBootstrap -Bootstrap $bootstrap -BootstrapPath unused -ControllerPolicyPath $futurePolicy
 }
}catch{$errorText=$_.Exception.Message}
@{failure=$errorText;restored=$restored;bootstrap=$bootstrap;restore_requests=$script:restoreRequests;saves=$script:saves;consumptions=$script:consumptions;flights=$script:flights;future_policies=$script:futurePolicies;old_pending=(Get-Content $pending -Raw -ErrorAction SilentlyContinue)}|ConvertTo-Json -Depth 100|Set-Content (Join-Path $Root 'output.json')
'''
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "restore.ps1"
            path.write_text(script, encoding="utf-8")
            result = subprocess.run([
                "pwsh", "-NoProfile", "-File", str(path),
                str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"), temporary, scenario, str(PROJECT.parents[1]), sys.executable,
            ], cwd=PROJECT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads((root / "output.json").read_text(encoding="utf-8-sig"))

    def test_saved_checkpoint_pending_preserves_debits_and_consumes_success_once(self):
        for status in ("success", "failed", "missing"):
            with self.subTest(status=status):
                result = self._restore_saved_checkpoint(status)
                self.assertIsNone(result["failure"])
                self.assertEqual(result["restored"]["stage_state"]["flight_count"], 2)
                self.assertEqual(result["restored"]["stage_state"]["candidate_count"], 2)
                self.assertEqual(result["bootstrap"]["stage_state"]["flight_count"], 2)
                self.assertEqual(result["bootstrap"]["stage_state"]["candidate_count"], 2)
                self.assertEqual(result["consumptions"], 1)
                self.assertEqual(len(result["flights"]), 0 if status == "success" else 1)
                self.assertEqual(len(result["bootstrap"]["stage_lineage"]["children"]), 2)
                self.assertNotIn("pending_trial", result["bootstrap"]["stage_state"])
                if status == "failed":
                    self.assertEqual(json.loads(result["old_pending"])["status"], "failed")
                    self.assertEqual(result["flights"][0]["ChildRunId"], "new-stage-002")

    def test_original_restore_can_defer_only_publication_without_skipping_validation(self):
        for scenario,expected_saves in (('restore_only',1),('deferred_save',0)):
            with self.subTest(scenario=scenario):
                result=self._restore_saved_checkpoint(scenario)
                self.assertIsNone(result['failure'])
                self.assertEqual(result['saves'],expected_saves)
                self.assertEqual(result['flights'],[])
                self.assertEqual(result['consumptions'],0)
                self.assertEqual(result['restored'],result['bootstrap'])
                self.assertEqual(result['restored']['stage_state']['candidate_count'],2)

    def test_abandoned_unflown_debit_restores_before_and_after_future_child(self):
        for scenario,count in (("abandoned",2),("abandoned_after_child",3)):
            result=self._restore_saved_checkpoint(scenario)
            self.assertIsNone(result["failure"])
            self.assertEqual(result["restored"]["stage_state"]["flight_count"],count)
            self.assertEqual(result["restored"]["stage_state"]["candidate_count"],2)
            self.assertEqual(result["flights"],[])
        for scenario in ("abandoned_tampered","abandoned_reset"):
            result=self._restore_saved_checkpoint(scenario)
            self.assertIsNotNone(result["failure"])
            self.assertIsNone(result["restored"])

    def test_saved_checkpoint_policy_is_preserved_and_new_policy_only_controls_future(self):
        result = self._restore_saved_checkpoint("future_policy")
        self.assertIsNone(result["failure"])
        old = result["restored"]["stage_history"]["decisions"][0]
        self.assertTrue(old["prism_controller_policy"]["path"].endswith("old-policy.json"))
        self.assertTrue(result["future_policies"][0].endswith("future-policy.json"))
        self.assertEqual(result["flights"], [])

    def test_joint_three_columns_restore_without_budget_or_identity_rewrite(self):
        result = self._restore_saved_checkpoint("joint_columns")
        self.assertIsNone(result["failure"])
        state = result["restored"]["stage_state"]
        self.assertEqual(set(state["columns"]), {"0", "2", "3"})
        self.assertEqual((state["flight_count"], state["candidate_count"]), (4, 1))
        self.assertEqual(result["flights"], [])
        self.assertEqual(result["restore_requests"], 1)

    def test_joint_candidate_outside_prism_window_is_rejected_not_promoted(self):
        result = self._restore_saved_checkpoint("joint_p_rejected")
        self.assertIsNone(result["failure"])
        state = result["bootstrap"]["stage_state"]
        self.assertEqual(Path(state["anchor_manifest"]).parent.name, "child")
        self.assertEqual(state["step_factor"], .25)
        self.assertEqual(state["consecutive_candidate_rejections"], 1)
        self.assertEqual((state["flight_count"], state["candidate_count"]), (2, 2))

    def test_saved_checkpoint_rejects_changed_identity_reference_budget_and_pending_voltage(self):
        for scenario in ("bad_anchor", "bad_column", "bad_model", "bad_budget", "bad_voltage", "bad_policy", "bad_child"):
            with self.subTest(scenario=scenario):
                result = self._restore_saved_checkpoint(scenario)
                self.assertIsNotNone(result["failure"])
                self.assertEqual(result["saves"], 0)
                self.assertEqual(result["flights"], [])

    def test_recovered_foreign_anchor_protects_all_live_levels_and_refuses_retirement(self):
        script = r'''
param($Source,$Root,$Refuse)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Update-StagedAnchorFieldProtection'},$true)
Invoke-Expression $node.Extent.Text
$staticFieldMode=$true;$staticBindingMode='native_static_pa';$repoRoot=$Root;$python='Read-BindingMock'
$script:capacitySession=@{lease_id='old';protected_paths=@('immutable_bank')}
$old=$script:capacitySession;$script:seenBinding=$null;$script:retired=$false
$script:restoredAnchorFieldProtection=$null
$owner=Join-Path $Root 'foreign-field'
$paths=@((Join-Path $owner 'run_manifest.json'))
foreach($level in @('parent','window_0','window_1','window_2')){
 $paths+=@(Join-Path $owner "$level/field.pa"),@(Join-Path $owner "$level/field.pa-surf")
}
$old.protected_paths+=,$paths[0]
$binding=Join-Path $owner 'results/field_binding.json'
$child=Join-Path $Root 'foreign-child';$null=New-Item -ItemType Directory $child
'{}'|Set-Content (Join-Path $child 'run_manifest.json')
$anchor=Join-Path $child 'run_manifest.json'
$materialization=Join-Path $Root 'materialization.json'
@{field_binding=@{path=$binding}}|ConvertTo-Json -Depth 10|Set-Content $materialization
function Get-ManifestOutputPath {param($ManifestPath,$FileName)
 if($ManifestPath-ne$anchor-or$FileName-ne'two_prism_trial_materialization.json'){throw 'Wrong anchor'}
 return $materialization
}
function Invoke-RunToolRootContext {param($RepoRoot,$Operation) & $Operation}
function Read-BindingMock {
 param([Parameter(ValueFromRemainingArguments=$true)][object[]]$Arguments)
 if($Arguments[2]-notlike'*load_binding*'-or$Arguments[2]-notlike'*refinement_windows*'){throw 'Not the live binding validator'}
 $script:seenBinding=$Arguments[3];$global:LASTEXITCODE=0
 $paths|ConvertTo-Json -Compress
}
function Update-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session,$ProtectedPaths)
 if($Refuse-eq'yes'){throw 'public protection update refused'}
 return @{session=@{lease_id='renewed';protected_paths=@(@($Session.protected_paths)+@($ProtectedPaths)|Select-Object -Unique)}}
}
function Invoke-PublicRetirement {
 param($Target)
 if(@($script:capacitySession.protected_paths|Where-Object{$_-eq$Target}).Count){throw 'public dependency refuses retirement'}
 $script:retired=$true
}
$errorText=$null;$retirementError=$null
try{Update-StagedAnchorFieldProtection -State @{anchor_manifest=$anchor}}catch{$errorText=$_.Exception.Message}
if(-not$errorText){try{Invoke-PublicRetirement -Target $paths[1]}catch{$retirementError=$_.Exception.Message}}
@{error=$errorText;retirement_error=$retirementError;retired=$script:retired;binding=$script:seenBinding;session=$script:capacitySession;old=$old;paths=$paths;added=$(if($errorText){@()}else{$script:restoredAnchorFieldProtection.groups[0].paths})}|ConvertTo-Json -Depth 20|Set-Content (Join-Path $Root 'output.json')
'''
        for refused in (False, True):
            with self.subTest(refused=refused), TemporaryDirectory() as temporary:
                root = Path(temporary)
                path = root / 'protection.ps1'
                path.write_text(script, encoding='utf-8')
                result = subprocess.run(['pwsh', '-NoProfile', '-File', str(path),
                                         str(PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1'),
                                         temporary, 'yes' if refused else 'no'], cwd=PROJECT,
                                        timeout=30, capture_output=True, text=True,
                                        encoding='utf-8', errors='replace')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                report = json.loads((root / 'output.json').read_text(encoding='utf-8-sig'))
                self.assertFalse(report['retired'])
                if refused:
                    self.assertIn('update refused', report['error'])
                    self.assertEqual(report['session']['lease_id'], 'old')
                else:
                    self.assertIsNone(report['error'])
                    self.assertEqual(report['session']['protected_paths'],
                                     ['immutable_bank', *report['paths']])
                    self.assertEqual(report['added'], report['paths'][1:])
                    self.assertIn('dependency refuses', report['retirement_error'])
                    self.assertTrue(report['binding'].endswith('field_binding.json'))

    def test_restored_final_anchor_and_successful_pending_are_live_consumers_only(self):
        script = r'''
param($Source,$Root,$PendingStatus)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Update-StagedAnchorFieldProtection'},$true)
Invoke-Expression $node.Extent.Text
$staticFieldMode=$true;$staticBindingMode='native_static_pa';$repoRoot=$Root;$python='Read-BindingMock'
$script:capacitySession=@{lease_id='old';protected_paths=@('shared_collision','immutable_bank')}
$script:restoredAnchorFieldProtection=$null;$script:calls=@();$manifests=@{}
foreach($id in @('003','006')){
 $dir=Join-Path $Root $id;$null=New-Item -ItemType Directory $dir
 $manifest=Join-Path $dir 'run_manifest.json';$manifests[$id]=$manifest
 @{status=$(if($id-eq'006'){$PendingStatus}else{'success'})}|ConvertTo-Json|Set-Content $manifest
 @{field_binding=@{path=$id}}|ConvertTo-Json -Depth 10|Set-Content (Join-Path $dir 'materialization.json')
}
function Get-ManifestOutputPath {param($ManifestPath,$FileName) Join-Path (Split-Path $ManifestPath) 'materialization.json'}
function Invoke-RunToolRootContext {param($RepoRoot,$Operation) & $Operation}
function Read-BindingMock {
 param([Parameter(ValueFromRemainingArguments=$true)][object[]]$Arguments)
 $id=$Arguments[3];$script:calls+=,$id;$global:LASTEXITCODE=0
 @('shared_collision',"$id-owner", "$id-parent.pa", "$id-parent.pa-surf", "$id-window0.pa", "$id-window0.pa-surf", "$id-window1.pa", "$id-window1.pa-surf", "$id-window2.pa", "$id-window2.pa-surf")|ConvertTo-Json -Compress
}
function Update-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session,$ProtectedPaths)
 @{session=@{lease_id='renewed';protected_paths=@(@($Session.protected_paths)+@($ProtectedPaths)|Select-Object -Unique)}}
}
$state=@{anchor_manifest=$manifests['003'];pending_trial=@{child_manifest=$manifests['006']}}
Update-StagedAnchorFieldProtection -State $state
if($PendingStatus-eq'success'){
 # After normal Complete -> Save, 006 is the anchor while 007 is unfinished.
 $state.anchor_manifest=$manifests['006'];$state.pending_trial.child_manifest=Join-Path $Root '007/run_manifest.json'
 Update-StagedAnchorFieldProtection -State $state
}
@{calls=$script:calls;paths=$script:capacitySession.protected_paths;groups=$script:restoredAnchorFieldProtection.groups}|ConvertTo-Json -Depth 20|Set-Content (Join-Path $Root 'output.json')
'''
        for status in ('success', 'failed'):
            with self.subTest(status=status), TemporaryDirectory() as temporary:
                root = Path(temporary)
                path = root / 'pending.ps1'
                path.write_text(script, encoding='utf-8')
                result = subprocess.run(['pwsh', '-NoProfile', '-File', str(path),
                                         str(PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1'),
                                         temporary, status], cwd=PROJECT, timeout=30,
                                        capture_output=True, text=True, encoding='utf-8', errors='replace')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                report = json.loads((root / 'output.json').read_text(encoding='utf-8-sig'))
                self.assertEqual(report['calls'], ['003', '006'] if status == 'success' else ['003'])
                self.assertNotIn('001', report['calls'])  # Retired historical accepted trial never loads.
                self.assertIn('immutable_bank', report['paths'])
                self.assertEqual(len(report['groups']), 2 if status == 'success' else 1)
                if status == 'success':
                    self.assertIn('006-window2.pa-surf', report['paths'])
        source = (PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1').read_text(encoding='utf-8')
        complete = source.split('function Complete-StagedTrial {', 1)[1].split('function Update-StagedAnchorFieldProtection', 1)[0]
        self.assertNotIn('Update-StagedAnchorFieldProtection', complete)

    def test_staged_compose_public_owner_sequence_and_completed_receipt_resume(self):
        script = r'''
param($Source,$Root,$Refuse,$Completed,$Support)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. $Support
$callerLocation=(Get-Location).Path
$env:PYTHONPATH='caller-python-path';$env:PYTHONNOUSERSITE='caller-site'
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-StagedComposeRetirement'},$true)
Invoke-Expression $node.Extent.Text
$repoRoot=$Root;$artifactWorkspaceRoot=$Root;$RunId='parent';$project='parallel_mirror_dual_stripe_mr_tof';$python='Invoke-PublicMock'
$target=Join-Path $Root 'provider';$null=New-Item -ItemType Directory -Path $target
$owner=@{provider_run=$target;child_run_id='parent-stage-001';operation='compose'}
if($Completed-eq'yes'){@{lifecycle_status='completed_experiment_payload_retired'}|ConvertTo-Json|Set-Content (Join-Path $target 'solver_review_retirement_receipt.json')}
function Invoke-PublicMock {
 param([Parameter(ValueFromRemainingArguments=$true)][object[]]$Arguments)
 if((Get-Location).Path-ne$Root-or$env:PYTHONPATH-ne$Root-or$env:PYTHONNOUSERSITE-ne'1'){throw 'Public CLI repository context differs'}
 if($Arguments-contains'--verify'){'verify'|Add-Content (Join-Path $Root 'calls.txt')}
 elseif($Arguments-contains'finalize-ready'){'finalize'|Add-Content (Join-Path $Root 'calls.txt');@{status='ready';action='finalize_ready'}|ConvertTo-Json -Compress}
 else{throw 'Unknown public CLI'}
 if(($Refuse-eq'verify'-and$Arguments-contains'--verify')-or($Refuse-eq'finalize'-and$Arguments-contains'finalize-ready')){$global:LASTEXITCODE=2;return}
 $global:LASTEXITCODE=0
}
$errorText=$null;$result=$null
try{$result=Invoke-StagedComposeRetirement -Owner $owner -Disposition stencil}catch{$errorText=$_.Exception.Message}
@{error=$errorText;calls=@(Get-Content (Join-Path $Root 'calls.txt'));result=$result;location=(Get-Location).Path;caller=$callerLocation;pythonpath=$env:PYTHONPATH;nouser=$env:PYTHONNOUSERSITE;receipt=$(if(Test-Path (Join-Path $target 'solver_review_retirement_receipt.json')){Get-Content (Join-Path $target 'solver_review_retirement_receipt.json') -Raw|ConvertFrom-Json}else{$null})}|ConvertTo-Json -Depth 20|Set-Content (Join-Path $Root 'output.json')
'''
        wrapper = r'''
[CmdletBinding(SupportsShouldProcess)]
param($ArtifactRoot,$RepositoryRoot,$TargetRun,$Owner,$OwnerAbandonmentReason,[switch]$Apply)
if((Get-Location).Path-ne$RepositoryRoot-or$env:PYTHONPATH-ne$RepositoryRoot-or$env:PYTHONNOUSERSITE-ne'1'){throw 'Retirement wrapper repository context differs'}
if($Owner-ne'parallel_mirror_dual_stripe_mr_tof'-or-not$OwnerAbandonmentReason.Contains('parent/parent-stage-001')){throw 'Owner scope differs'}
$(if($Apply){'apply'}else{'plan'})|Add-Content (Join-Path $RepositoryRoot 'calls.txt')
if(Test-Path (Join-Path $RepositoryRoot 'refuse')){exit 2}
if($Apply){@{lifecycle_status='completed_experiment_payload_retired';preserved_files=@(@{path='evidence.json';bytes=123;sha256='sealed-small-evidence'});removed_files=@(@{path='field.pa';bytes=999;sha256='sealed-payload'})}|ConvertTo-Json -Depth 10|Set-Content (Join-Path $TargetRun 'solver_review_retirement_receipt.json')}
exit 0
'''
        for refused, completed in (('', False), ('apply', False), ('', True), ('verify', False), ('finalize', False)):
            with self.subTest(refused=refused, completed=completed), TemporaryDirectory() as temporary:
                root = Path(temporary)
                public = root / 'common/contracts'
                public.mkdir(parents=True)
                (public / 'invoke_solver_review_retirement.ps1').write_text(wrapper, encoding='utf-8')
                if refused == 'apply':
                    (root / 'refuse').write_text('active consumer', encoding='utf-8')
                path = root / 'owner.ps1'
                path.write_text(script, encoding='utf-8')
                caller = root / 'outside-repository'
                caller.mkdir()
                result = subprocess.run(['pwsh', '-NoProfile', '-File', str(path),
                                         str(PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1'),
                                         temporary, refused or 'no', 'yes' if completed else 'no',
                                         str(PROJECT.parents[1] / 'common/contracts/run_artifact_support.ps1')],
                                        cwd=caller, timeout=30, capture_output=True, text=True,
                                        encoding='utf-8', errors='replace')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                report = json.loads((root / 'output.json').read_text(encoding='utf-8-sig'))
                self.assertEqual(Path(report['location']), caller)
                self.assertEqual(report['location'], report['caller'])
                self.assertEqual(report['pythonpath'], 'caller-python-path')
                self.assertEqual(report['nouser'], 'caller-site')
                if refused:
                    self.assertIn({'apply': 'apply failed', 'verify': 'verification failed',
                                   'finalize': 'finalize failed'}[refused], report['error'])
                    self.assertEqual(report['calls'], {'apply': ['apply'],
                        'verify': ['apply', 'verify'], 'finalize': ['apply', 'verify', 'finalize']}[refused])
                    self.assertIsNone(report['result'])
                else:
                    self.assertIsNone(report['error'])
                    self.assertEqual(report['calls'], ['verify', 'finalize'] if completed else
                                     ['apply', 'verify', 'finalize'])
                    self.assertEqual(report['result']['capacity_finalization']['status'], 'ready')
                    if not completed:
                        self.assertEqual(report['receipt']['preserved_files'], [
                            {'path': 'evidence.json', 'bytes': 123, 'sha256': 'sealed-small-evidence'}])
                        self.assertEqual(report['receipt']['removed_files'], [
                            {'path': 'field.pa', 'bytes': 999, 'sha256': 'sealed-payload'}])

    def _run_compose_reclamation_fixture(self, *, failure='', foreign=False, tampered=False, resume=False,
                                         accepted=False, unknown_best=False, restored='', imported=False,
                                         retired=False, cross_project=False, measured=False, operation='compose',explicit_refine=True):
        script = r'''
param($Source,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
foreach($name in @('New-StagedComposeProviderReference','Assert-StagedComposeProviderReference','Resolve-StagedComposeRetirementOwner','Reclaim-StagedComposeProviders')){
 $node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)
 Invoke-Expression $node.Extent.Text
}
$fixture=Get-Content (Join-Path $Root 'fixture.json') -Raw|ConvertFrom-Json -AsHashtable
$script:preparedStagedMode=[bool]$fixture.measured
$script:PreparedFieldBuildMode=if($fixture.explicit_refine){$fixture.operation}else{'composition'}
$RunId='parent';$project='parallel_mirror_dual_stripe_mr_tof';$artifactRoot=$Root;$artifactWorkspaceRoot=$Root;$repoRoot=$Root;$python='mock'
$controllerContext=@{run_id=$RunId;artifact_root=$artifactRoot;prepared_staged=$script:preparedStagedMode;prepared_field_build_mode=$script:PreparedFieldBuildMode}
$trialArtifactRoot=$artifactRoot
$staticFieldMode=$true;$staticBindingMode='native_static_pa'
$package=@{input_dir=(Join-Path $Root 'inputs');result_dir=(Join-Path $Root 'results');artifact_run_dir=(Join-Path $Root 'runs/parent')}
foreach($path in @($package.input_dir,$package.result_dir,$package.artifact_run_dir)){$null=New-Item -ItemType Directory -Path $path -Force}
$script:events=@('checkpoint');$script:entered=$null;$script:retired=@();$script:protectionReceipts=@()
$script:restoredAnchorFieldProtection=$null
function Write-RunJson {param($Path,$Value,$Depth) $Value|ConvertTo-Json -Depth $Depth|Set-Content -LiteralPath $Path}
function Enter-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$ArtifactRoot,$RunDirectory,$Owner,$LeaseTtlSeconds,$CommittedNewBytes,$ProtectedPaths,$ProtectedCacheKeys)
 $script:events+='enter_new'
 if($fixture.failure-eq'new_lease'){throw 'new lease refused'}
 $script:entered=@{status='active';lease_id='new';owner=$Owner;lease_ttl_seconds=$LeaseTtlSeconds;committed_new_bytes=$CommittedNewBytes;protected_paths=@($ProtectedPaths);protected_cache_keys=@($ProtectedCacheKeys)}
 return $script:entered
}
function Exit-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session) $script:events+='exit_'+$Session.lease_id;$Session.status='released'}
function Save-NativeWorkflowCheckpoint {param($Reason,$WorkflowOutcome)}
function Get-ManifestOutputPath {param($ManifestPath,$FileName)$script:events+='freeze_light';return $ManifestPath}
function Invoke-PreclosureDecision {
 param($Stage,$Anchor,$Columns,$OutputPath,$Context)
 if($Anchor.EndsWith('parent-stage-009/run_manifest.json')-or$Anchor.EndsWith('parent-stage-009\run_manifest.json')){
  if($fixture.restored-eq'unknown'){return @{}}
  return @{full_workpoint_qualified=($fixture.restored-eq'best')}
 }
 if($Anchor.EndsWith('parent-stage-007/run_manifest.json')-or$Anchor.EndsWith('parent-stage-007\run_manifest.json')){
  if($fixture.unknown_best){return @{}}
  return @{full_workpoint_qualified=$true}
 }
 return @{full_workpoint_qualified=$false}
}
function Invoke-StagedComposeRetirement {
 param($Owner,$Disposition)
 $script:events+='plan_'+$Owner.child_run_id
 if($fixture.failure-eq'dependency'){throw 'public dependency refuses retirement'}
 $receipt=Join-Path $Owner.provider_run 'solver_review_retirement_receipt.json'
 if(Test-Path $receipt){return @{retirement_receipt=@{path=$receipt;bytes=(Get-Item $receipt).Length;sha256=(Get-FileHash $receipt -Algorithm SHA256).Hash.ToLowerInvariant()};capacity_finalization=@{status='ready'}}}
 $script:events+='apply_'+$Owner.child_run_id;$script:events+='verify_'+$Owner.child_run_id;$script:events+='finalize_'+$Owner.child_run_id
 $script:retired+=$Owner.provider_run
 $receipt=Join-Path $Owner.provider_run 'solver_review_retirement_receipt.json';'{}'|Set-Content -LiteralPath $receipt
 return @{retirement_receipt=@{path=$receipt;bytes=(Get-Item $receipt).Length;sha256=(Get-FileHash $receipt -Algorithm SHA256).Hash.ToLowerInvariant()};capacity_finalization=@{status='ready'}}
}
$entries=@();$paths=@('fixed_bank','baseline','unrelated_provider');$references=@{}
$producer=if($fixture.imported){'old_parent'}else{'parent'}
$producerInputs=if($fixture.imported){Join-Path $Root 'runs/old_parent/inputs'}else{$package.input_dir}
if($fixture.imported){
 $null=New-Item -ItemType Directory -Path $producerInputs -Force
 $parentCfg=Join-Path $Root 'runs/old_parent/run_config.json';'{}'|Set-Content $parentCfg
 @{run_id='old_parent';project=$(if($fixture.cross_project){'another_project'}else{$project});mode='downstream_fixed_grid_workpoint_iteration';run_config=@{sha256=(Get-FileHash $parentCfg -Algorithm SHA256).Hash}}|ConvertTo-Json -Depth 10|Set-Content (Join-Path $Root 'runs/old_parent/run_manifest.json')
}
foreach($i in 1..$(if($fixture.accepted){9}else{5})){
 $childId=$producer+'-stage-00'+$i;$provider=Join-Path $Root ('runs/'+$childId+'-field');$child=Join-Path $Root ('runs/'+$childId)
 $null=New-Item -ItemType Directory -Path $provider,$child -Force
 $request=Join-Path $producerInputs ($childId+'-field_request.json');'{}'|Set-Content -LiteralPath $request
 $cfg=Join-Path $provider 'run_config.json';@{parameters=@{operation=$fixture.operation}}|ConvertTo-Json -Depth 10|Set-Content -LiteralPath $cfg
 $sha=(Get-FileHash $request -Algorithm SHA256).Hash
 @{status='success';project=$project;mode='native_static_field_provider';run_id=($childId+'-field');inputs=@{request=@{path=$request;sha256=$sha}};run_config=@{sha256=(Get-FileHash $cfg -Algorithm SHA256).Hash}}|ConvertTo-Json -Depth 15|Set-Content (Join-Path $provider 'run_manifest.json')
 $reference=New-StagedComposeProviderReference -ChildRunId $childId -ProviderRun $provider -RequestPath $request -ParentRunId $producer
 $references[[string]$i]=$reference
 $parameters=@{gui_workbench_retained=($i-eq4-or($i-eq9-and$fixture.restored-eq'gui'))}
 if($fixture.measured){$parameters['source_mode']='centroid_probe';$parameters['gui_executed']=$false}
 @{parameters=$parameters}|ConvertTo-Json -Depth 10|Set-Content (Join-Path $child 'run_config.json')
 @{run_config=@{sha256=(Get-FileHash (Join-Path $child 'run_config.json') -Algorithm SHA256).Hash}}|ConvertTo-Json -Depth 10|Set-Content (Join-Path $child 'run_manifest.json')
 $use=if($i-eq2){'rejected_candidate'}elseif($i-eq3-or$i-ge6){'keep'}else{'stencil'}
 $entries+=,@{iteration=$i;run_id=$childId;child_manifest=(Join-Path $child 'run_manifest.json');child_manifest_sha256=(Get-FileHash (Join-Path $child 'run_manifest.json') -Algorithm SHA256).Hash.ToLowerInvariant();parent_manifest='root.json';compose_payload_use=$use;provider_reference=$reference}
 $paths+=@($provider,(Join-Path $provider 'results/field_binding.json'))
}
$state=@{anchor_manifest=$entries[2].child_manifest;pending_trial=@{child_manifest=$entries[4].child_manifest};columns=@{}}
if($fixture.accepted){
 $entries[2].parent_manifest=$entries[5].child_manifest
 $state.pending_trial.anchor_manifest=$entries[7].child_manifest
 if(-not$fixture.imported){$entries[8].provider_reference.parent_run_id='old_parent'}
}
if($fixture.restored){
 $foreign=$entries[8]
 $foreignPaths=@($foreign.provider_reference.provider_run,(Join-Path $foreign.provider_reference.provider_run 'results/field_binding.json'))
 $script:restoredAnchorFieldProtection=@{groups=@(@{anchor_manifest=$foreign.child_manifest;manifest_sha256=$foreign.child_manifest_sha256;paths=$foreignPaths;all_paths=$foreignPaths})}
 if($fixture.restored-eq'current'){$state.anchor_manifest=$foreign.child_manifest}
 if($fixture.restored-eq'pending'){$state.pending_trial.anchor_manifest=$foreign.child_manifest}
 if($fixture.restored-eq'column'){$state.columns['0']=$foreign.child_manifest}
 if($fixture.restored-eq'shared'){
  $script:restoredAnchorFieldProtection.groups+=,@{anchor_manifest=$entries[2].child_manifest;manifest_sha256=$entries[2].child_manifest_sha256;paths=@();all_paths=@($foreignPaths[1])}
 }
}
if($fixture.imported-and$fixture.restored-eq'consumed_column'){
 $consumed=$entries[0];$state.columns['0']=$consumed.child_manifest
 $columnPaths=@($consumed.provider_reference.provider_run,(Join-Path $consumed.provider_reference.provider_run 'results/field_binding.json'))
 $script:restoredAnchorFieldProtection=@{groups=@(@{anchor_manifest=$consumed.child_manifest;manifest_sha256=$consumed.child_manifest_sha256;paths=$columnPaths;all_paths=$columnPaths})}
}
if($fixture.foreign){$entries[0].provider_reference.parent_run_id='old_parent'}
if($fixture.tampered){$entries[0].provider_reference.request_sha256='bad'}
if($fixture.retired){'{}'|Set-Content (Join-Path $entries[0].provider_reference.provider_run 'solver_review_retirement_receipt.json')}
if($fixture.resume){$references=$references|ConvertTo-Json -Depth 20|ConvertFrom-Json -AsHashtable;$entries=$entries|ConvertTo-Json -Depth 20|ConvertFrom-Json -AsHashtable}
$old=@{status='active';lease_id='old';owner='parent-owner';lease_ttl_seconds=600;committed_new_bytes=0;protected_paths=$paths;protected_cache_keys=@('immutable-bank')}
$script:capacitySession=$old;$errorText=$null
try{
 Reclaim-StagedComposeProviders -State $state -Lineage @{children=$entries}
 if($fixture.resume){Reclaim-StagedComposeProviders -State $state -Lineage @{children=$entries}}
}catch{$errorText=$_.Exception.Message}
@{events=$script:events;retired=$script:retired;old_status=$old.status;session=$script:capacitySession;error=$errorText;root=$Root;state=$state}|ConvertTo-Json -Depth 30|Set-Content (Join-Path $Root 'output.json')
'''
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'fixture.json').write_text(json.dumps(dict(failure=failure, foreign=foreign,
                                                               tampered=tampered, resume=resume,
                                                               accepted=accepted, unknown_best=unknown_best,
                                                               restored=restored, imported=imported,
                                                               retired=retired, cross_project=cross_project,measured=measured,
                                                               operation=operation,explicit_refine=explicit_refine)), encoding='utf-8')
            path = root / 'reclamation.ps1'
            path.write_text(script, encoding='utf-8')
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(path),
                                     str(PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1'), temporary],
                                    cwd=PROJECT, timeout=40, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads((root / 'output.json').read_text(encoding='utf-8-sig'))

    def test_measured_retirement_requires_light_projection_keeps_gui_and_honors_public_refusal(self):
        result=self._run_compose_reclamation_fixture(measured=True)
        self.assertIsNone(result['error'])
        self.assertEqual(len(result['retired']),3)
        self.assertTrue(result['retired'][-1].endswith('parent-stage-003-field'))
        self.assertLess(result['events'].index('freeze_light'),result['events'].index('enter_new'))
        for i in (4,5):
            self.assertTrue(any(p.endswith(f'parent-stage-00{i}-field') for p in result['session']['protected_paths']))
        blocked=self._run_compose_reclamation_fixture(measured=True,failure='dependency')
        self.assertIsNone(blocked['error'])
        self.assertEqual(blocked['retired'],[])
        self.assertTrue(blocked['state']['capacity_lifecycle_blocked']['no_private_delete'])
        self.assertFalse(any(e.startswith('apply_') for e in blocked['events']))
        refused=self._run_compose_reclamation_fixture(measured=True,failure='new_lease')
        self.assertIsNone(refused['error'])
        self.assertEqual(refused['old_status'],'active')
        self.assertTrue(refused['state']['capacity_lifecycle_blocked']['old_protection_preserved'])
        self.assertFalse(any(e.startswith(('apply_','exit_')) for e in refused['events']))

    def test_explicit_prepared_refine_lifecycle_is_not_labelled_compose_and_keeps_public_gates(self):
        direct=self._run_compose_reclamation_fixture(measured=True,operation='refine')
        self.assertIsNone(direct['error'])
        self.assertEqual(len(direct['retired']),3)
        self.assertIn('freeze_light',direct['events'])
        unselected=self._run_compose_reclamation_fixture(measured=True,operation='refine',explicit_refine=False)
        self.assertEqual(unselected['retired'],[])
        self.assertNotIn('enter_new',unselected['events'])
        refused=self._run_compose_reclamation_fixture(measured=True,operation='refine',failure='dependency')
        self.assertTrue(refused['state']['capacity_lifecycle_blocked']['no_private_delete'])
        self.assertFalse(any(e.startswith('apply_') for e in refused['events']))

    def test_staged_compose_reclaims_only_consumed_owned_fields_after_new_protection(self):
        for resume in (False, True):
            with self.subTest(resume=resume):
                result = self._run_compose_reclamation_fixture(resume=resume)
                self.assertIsNone(result['error'])
                self.assertEqual(result['events'][:3], ['checkpoint', 'enter_new', 'exit_old'])
                self.assertEqual(len(result['retired']), 2)
                self.assertTrue(result['retired'][0].endswith('parent-stage-001-field'))
                self.assertTrue(result['retired'][1].endswith('parent-stage-002-field'))
                keep = result['session']['protected_paths']
                self.assertIn('fixed_bank', keep)
                self.assertIn('unrelated_provider', keep)
                for index in (3, 4, 5):
                    self.assertTrue(any(p.endswith(f'parent-stage-00{index}-field') for p in keep))
                self.assertFalse(any(p.endswith('parent-stage-001-field') for p in keep))
                self.assertEqual(result['session']['protected_cache_keys'], ['immutable-bank'])
                self.assertEqual(result['old_status'], 'released')
                self.assertEqual(result['events'][3:7], ['plan_parent-stage-001', 'apply_parent-stage-001',
                                                        'verify_parent-stage-001', 'finalize_parent-stage-001'])

    def test_restored_compose_uses_original_owner_and_keeps_current_pending_gui(self):
        result = self._run_compose_reclamation_fixture(imported=True, resume=True,
                                                       accepted=True, restored='consumed_column')
        self.assertIsNone(result['error'])
        self.assertTrue(len(result['retired']) >= 2)
        for index in (1, 2):
            self.assertTrue(any(p.endswith(f'old_parent-stage-00{index}-field')
                                for p in result['retired']))
        for index in (3, 4, 5):
            self.assertTrue(any(p.endswith(f'old_parent-stage-00{index}-field')
                                for p in result['session']['protected_paths']))
        self.assertIn('fixed_bank', result['session']['protected_paths'])
        self.assertIn('baseline', result['session']['protected_paths'])

    def test_restored_compose_public_retired_receipt_skips_apply_and_bad_authority_rejects(self):
        result = self._run_compose_reclamation_fixture(imported=True, retired=True, resume=True)
        self.assertIsNone(result['error'])
        self.assertNotIn('apply_old_parent-stage-001', result['events'])
        self.assertEqual(result['events'].count('apply_old_parent-stage-002'), 1)
        for options, message in ((dict(cross_project=True), 'parent authority differs'),
                                 (dict(tampered=True), 'provider reference differs')):
            with self.subTest(options=options):
                rejected = self._run_compose_reclamation_fixture(imported=True, **options)
                self.assertIn(message, rejected['error'])
                self.assertEqual(rejected['retired'], [])

    def test_restored_superseded_anchor_can_retire_before_next_compose(self):
        result = self._run_compose_reclamation_fixture(imported=True, accepted=True)
        self.assertIsNone(result['error'])
        self.assertTrue(any(p.endswith('old_parent-stage-006-field') for p in result['retired']))
        source = (PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1').read_text(encoding='utf-8')
        bootstrap = source[source.index('function Invoke-StagedWorkpointBootstrap'):]
        self.assertLess(bootstrap.index("Reclaim-StagedComposeProviders -State $state -Lineage $lineage"),
                        bootstrap.index('while($null-eq$terminal)'))

    def test_restored_anchor_protection_rotates_only_after_last_live_consumer(self):
        for use in ('current', 'pending', 'column', 'best', 'gui', 'unknown', 'obsolete', 'shared'):
            with self.subTest(use=use):
                result = self._run_compose_reclamation_fixture(accepted=True, restored=use)
                self.assertIsNone(result['error'])
                keep = result['session']['protected_paths']
                foreign_kept = any(p.endswith('parent-stage-009-field') for p in keep)
                self.assertEqual(foreign_kept, use not in ('obsolete', 'shared'))
                if use == 'shared':
                    self.assertTrue(any(p.endswith('parent-stage-009-field\\results/field_binding.json')
                                        or p.endswith('parent-stage-009-field\\results\\field_binding.json')
                                        for p in keep))
                self.assertFalse(any(p.endswith('parent-stage-009-field') for p in result['retired']))
                self.assertIn('fixed_bank', keep)
                self.assertIn('baseline', keep)
                self.assertTrue(any(p.endswith('parent-stage-005-field') for p in keep))

    def test_restored_anchor_new_lease_refusal_keeps_old_protection(self):
        result = self._run_compose_reclamation_fixture(accepted=True, restored='obsolete', failure='new_lease')
        self.assertIn('new lease refused', result['error'])
        self.assertEqual(result['old_status'], 'active')
        self.assertTrue(any(p.endswith('parent-stage-009-field') for p in result['session']['protected_paths']))
        self.assertEqual(result['retired'], [])

    def test_staged_compose_reclaims_superseded_accepted_anchor_but_keeps_live_and_best_fields(self):
        for resume, unknown_best in ((False, False), (True, False), (False, True)):
            with self.subTest(resume=resume, unknown_best=unknown_best):
                result = self._run_compose_reclamation_fixture(accepted=True, resume=resume,
                                                               unknown_best=unknown_best)
                self.assertIsNone(result['error'])
                self.assertEqual(len(result['retired']), 3)
                self.assertTrue(any(p.endswith('parent-stage-006-field') for p in result['retired']))
                keep = result['session']['protected_paths']
                for index in (3, 4, 5, 7, 8, 9):
                    self.assertTrue(any(p.endswith(f'parent-stage-00{index}-field') for p in keep))
                self.assertIn('fixed_bank', keep)
                self.assertIn('unrelated_provider', keep)
                self.assertFalse(any(p.endswith('parent-stage-006-field') for p in keep))

    def test_superseded_accepted_anchor_public_dependency_refusal_remains_closed(self):
        result = self._run_compose_reclamation_fixture(accepted=True, failure='dependency')
        self.assertIn('dependency refuses', result['error'])
        self.assertFalse(any(event.startswith('apply_') for event in result['events']))
        self.assertEqual(result['retired'], [])
        self.assertEqual(result['session']['status'], 'active')

    def test_staged_compose_new_lease_refusal_preserves_old_and_dependency_refusal_never_applies(self):
        result = self._run_compose_reclamation_fixture(failure='new_lease')
        self.assertIn('new lease refused', result['error'])
        self.assertEqual(result['old_status'], 'active')
        self.assertEqual(result['session']['lease_id'], 'old')
        self.assertEqual(result['events'], ['checkpoint', 'enter_new'])
        self.assertEqual(result['retired'], [])
        result = self._run_compose_reclamation_fixture(failure='dependency')
        self.assertIn('dependency refuses', result['error'])
        self.assertFalse(any(event.startswith('apply_') for event in result['events']))
        self.assertEqual(result['retired'], [])
        self.assertEqual(result['session']['status'], 'active')

    def test_staged_compose_foreign_and_conflicting_reference_never_retired(self):
        result = self._run_compose_reclamation_fixture(foreign=True)
        self.assertIsNone(result['error'])
        self.assertEqual(len(result['retired']), 1)
        self.assertTrue(result['retired'][0].endswith('parent-stage-002-field'))
        result = self._run_compose_reclamation_fixture(tampered=True)
        self.assertIn('reference differs', result['error'])
        self.assertEqual(result['events'], ['checkpoint'])
        self.assertEqual(result['old_status'], 'active')

    def test_terminal_replay_optional_handoff_is_symmetric_and_required_inputs_stay_strict(self):
        script = r"""
param($Source,$File,$Old,$New,$MissingRequired)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.ForEachStatementAst]-and
 $n.Extent.Text.Contains('Stage replay source, contract or stage replay evidence differs.')},$true)
$inputs=@{contract=$File;center_source_receipt=$File}
if($Old-eq'yes'){$inputs.prism_handoff_replay_manifest=$File}
if($MissingRequired-eq'yes'){$inputs.Remove('contract')}
$oldConfig=[pscustomobject]@{inputs=[pscustomobject]$inputs}
$frozenContract=$File;$frozenCenterSourceReceipt=$File
$PrismHandoffReplayManifest=if($New-eq'yes'){$File}else{''}
Invoke-Expression $node.Extent.Text
Write-Output 'PASS'
"""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture, evidence = root / "fixture.ps1", root / "sealed.json"
            fixture.write_text(script, encoding="utf-8")
            evidence.write_text("{}", encoding="utf-8")
            for old, new, missing, passed in (("no", "no", "no", True),
                                              ("yes", "yes", "no", True),
                                              ("yes", "no", "no", False),
                                              ("no", "yes", "no", False),
                                              ("no", "no", "yes", False)):
                result = subprocess.run(["pwsh", "-NoProfile", "-File", str(fixture),
                    str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"),
                    str(evidence), old, new, missing], cwd=PROJECT, capture_output=True,
                    text=True, encoding="utf-8", errors="replace", timeout=20)
                self.assertEqual(result.returncode == 0, passed, result.stdout + result.stderr)

    def test_real_authority_preflight_needs_no_model_metadata_and_keeps_mirror_checks(self):
        source = (PROJECT / "analysis/run_downstream_workpoint_iteration.ps1").read_text(encoding="utf-8-sig")
        line = next(line.strip() for line in source.splitlines() if line.strip().startswith('$authorityCode="'))
        code = line.split('"', 1)[1][:-1]
        self.assertNotIn("compile_request", code)
        authority = dict(analyzer_electrode_voltages_v=[0.] * 10 + [-27., -27., 54., 54., 0., 190., -190., 0., 0., 0.])
        request = dict(schema_version=1, role="mrtof_same_mesh_field_provider_request",
                       source_binding_path="scalar-only.json",
                       candidate_voltages_v=dict(s1=-27., s2=54., p1=190., p2=-190.))
        fixture = (
            "import json,sys; from unittest.mock import patch; "
            "code=sys.argv[1]; request=sys.argv[2]; authority=json.loads(sys.argv[3]); "
            "sys.argv=['authority',request]; "
            "from contextlib import ExitStack; "
            "stack=ExitStack(); "
            "stack.enter_context(patch('projects.parallel_mirror_dual_stripe_mr_tof.analysis."
            "corridor_field_provider.compile_request',side_effect=AssertionError('Unused model metadata'))); "
            "stack.enter_context(patch('projects.parallel_mirror_dual_stripe_mr_tof.analysis."
            "static_field_binding.load_binding',return_value={'authority':authority})); "
            "exec(code)"
        )
        for changed, expected in ((False, "true"), (True, "false")):
            target = {**request, "candidate_voltages_v": {**request["candidate_voltages_v"]}}
            if changed:
                target["candidate_voltages_v"]["s1"] = -28.
            result = subprocess.run([sys.executable, "-B", "-c", fixture, code,
                                     json.dumps(target), json.dumps(authority)],
                                    cwd=PROJECT.parents[1], capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), expected)
        request["mirror_voltage_variation_path"] = "variation.json"
        result = subprocess.run([sys.executable, "-B", "-c", fixture, code,
                                 json.dumps(request), json.dumps(authority)],
                                cwd=PROJECT.parents[1], capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mirror_reference_trial_manifest", result.stderr)

    def test_native_same_voltage_reuse_requires_every_level_stopping_match(self):
        source = (PROJECT / "analysis/run_downstream_workpoint_iteration.ps1").read_text(encoding="utf-8-sig")
        line = next(line.strip() for line in source.splitlines() if line.strip().startswith('$authorityCode="'))
        code = line.split('"', 1)[1][:-1]
        authority = dict(analyzer_electrode_voltages_v=[0.] * 10 + [-27., -27., 54., 54., 0., 190., -190., 0., 0., 0.])
        with TemporaryDirectory() as temporary:
            contract = Path(temporary) / "contract.json"
            contract.write_text(json.dumps({"simion": {"numerical_profiles": {"native_static_field": {
                "refine": {"convergence_v": 1e-5}}}}}), encoding="utf-8")
            request = dict(schema_version=1, role="mrtof_native_static_field_provider_request",
                           source_binding_path="native.json", numerical_contract_path=str(contract),
                           candidate_voltages_v=dict(s1=-27., s2=54., p1=190., p2=-190.))
            strict = dict(refine_stopping="contract_convergence", convergence_v=1e-5)
            fixture = (
                "import json,sys; from unittest.mock import patch; "
                "code,request,binding=sys.argv[1:];sys.argv=['check',request]; "
                "from projects.parallel_mirror_dual_stripe_mr_tof.analysis import static_field_binding; "
                "with_context=patch.object(static_field_binding,'load_binding',return_value=json.loads(binding)); "
                "with_context.start();exec(code)"
            )
            for changed_level in (None, "parent", "window"):
                binding = dict(mode="native_static_pa", authority=authority,
                               native_solver_numerics=dict(strict),
                               refinement_windows=[dict(native_solver_numerics=dict(strict))])
                if changed_level == "parent":
                    binding["native_solver_numerics"] = dict(refine_stopping="installed_default")
                if changed_level == "window":
                    binding["refinement_windows"][0]["native_solver_numerics"]["convergence_v"] = 1e-7
                result = subprocess.run([sys.executable, "-B", "-c", fixture, code,
                                         json.dumps(request), json.dumps(binding)],
                                        cwd=PROJECT.parents[1], capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "true" if changed_level is None else "false")
            contract.write_text("{}", encoding="utf-8")
            result = subprocess.run([sys.executable, "-B", "-c", fixture, code,
                                     json.dumps(request), json.dumps(binding)],
                                    cwd=PROJECT.parents[1], capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)

    def test_native_trial_request_uses_actual_argument_contract_not_stale_request(self):
        source = (PROJECT / "analysis/run_downstream_workpoint_iteration.ps1").read_text(encoding="utf-8-sig")
        start = source.index("    $request=$fieldProviderRequest|", source.index("function Invoke-CenterTrial"))
        statements = source[start:source.index("    $authorityCode=", start)]
        script = ("Set-StrictMode -Version Latest;$ErrorActionPreference='Stop';"
                  "$staticBinding=@{};"
                  "$fieldProviderRequest=@{role='mrtof_native_static_field_provider_request';numerical_contract_path='stale.json';response_basis_paths=@{s1='bank/s1.json';s2='bank/s2.json'}};"
                  "$Arguments=@{ContractPath='actual-frozen-contract.json';Stripe1VoltageV=-27;Stripe2VoltageV=54;Prism1VoltageV=190;Prism2VoltageV=-190};"
                  + statements + "$request|ConvertTo-Json -Compress")
        result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
                                cwd=PROJECT, capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        request = json.loads(result.stdout)
        self.assertEqual(request["numerical_contract_path"], "actual-frozen-contract.json")
        self.assertEqual(request["candidate_voltages_v"], dict(s1=-27, s2=54, p1=190, p2=-190))
        self.assertEqual(request["response_basis_paths"], dict(s1="bank/s1.json", s2="bank/s2.json"))
        result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command",
                                 script.replace("$staticBinding=@{};", "$staticBinding=@{consumer_view=@{kind='x_symmetry_plane';stored_x_nodes=5}};")],
                                cwd=PROJECT, capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["numerical_contract_path"], "stale.json")

    def test_native_bank_initial_protection_compiles_only_declared_bank(self):
        script = r"""
param($Source,$Enabled)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and
 $n.Extent.Text.StartsWith("if(`$fieldProviderRequest.Contains('response_basis_paths'))")},$true)
if($null-eq$node){throw 'Bank protection branch missing'}
$fieldProviderRequest=@{role='mrtof_native_static_field_provider_request';numerical_contract_path='stale.json'}
$staticBinding=@{}
if($Enabled-eq'yes'){$fieldProviderRequest.response_basis_paths=@{s1='bank/s1.json'}}
$workflowInputPaths=@('source.json');$contract='actual.json';$repoRoot='repo';$python='Invoke-MockPython';$script:calls=0
function Invoke-RunToolRootContext {param($RepoRoot,[scriptblock]$Operation)& $Operation}
function Invoke-MockPython {
 param([Parameter(ValueFromRemainingArguments=$true)][object[]]$TestArguments)
 $script:calls++;$global:LASTEXITCODE=0
 if($TestArguments[2]-notlike'*compile_request*protected_paths*'){throw 'Not the existing compiler'}
 $r=$TestArguments[3]|ConvertFrom-Json -AsHashtable
 if($r.numerical_contract_path-ne'actual.json'-or$r.response_basis_paths.s1-ne'bank/s1.json'){throw 'Bank request changed'}
 @('bank/base.json','bank/base.pa','bank/s1.json','bank/s1.pa')|ConvertTo-Json -Compress
}
Invoke-Expression $node.Extent.Text
@{paths=$workflowInputPaths;calls=$script:calls}|ConvertTo-Json -Compress
"""
        with TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "bank-protection.ps1"
            fixture.write_text(script, encoding="utf-8")
            for enabled in ("yes", "no"):
                result = subprocess.run(["pwsh", "-NoProfile", "-File", str(fixture),
                    str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"), enabled],
                    cwd=PROJECT, capture_output=True, text=True, encoding="utf-8", timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                output = json.loads(result.stdout)
                self.assertEqual(output["calls"], int(enabled == "yes"))
                self.assertEqual(output["paths"], ["source.json"] + (
                    ["bank/base.json", "bank/base.pa", "bank/s1.json", "bank/s1.pa"] if enabled == "yes" else []))

    def test_native_bank_same_voltage_reuses_source_without_materialization(self):
        script = r"""
param($Source,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-CenterTrial'},$true)
Invoke-Expression $node.Extent.Text
$staticFieldMode=$true;$python='Invoke-MockPython';$repoRoot=$Root;$script:flights=0;$script:providers=0
$fieldProviderRequest=@{role='mrtof_native_static_field_provider_request';source_binding_path='base.json';response_basis_paths=@{s1='axis.json'}}
$staticBinding=@{};$fieldProviderRunner='Invoke-MockProvider';$trialRunner='Invoke-MockTrial'
function Invoke-RunToolRootContext {param($RepoRoot,[scriptblock]$Operation)& $Operation}
function Invoke-MockPython {
 param([Parameter(ValueFromRemainingArguments=$true)][object[]]$TestArguments)
 $global:LASTEXITCODE=0;$r=$TestArguments[2]|ConvertFrom-Json -AsHashtable
 if($r.response_basis_paths.s1-ne'axis.json'-or$r.candidate_voltages_v.s1-ne-27){throw 'Request lost bank/target'}
 Write-Output 'true'
}
function Invoke-MockProvider {$script:providers++;throw 'Same field must not be materialized'}
function Invoke-MockTrial {
 param($ContractPath,$RunId,$Stripe1VoltageV,$Stripe2VoltageV,$Prism1VoltageV,$Prism2VoltageV,$FieldBindingPath)
 if($FieldBindingPath-ne'base.json'){throw 'Wrong same-U field'};$script:flights++
}
Invoke-CenterTrial -Arguments @{ContractPath='actual.json';RunId='candidate';Stripe1VoltageV=-27.;Stripe2VoltageV=54.;Prism1VoltageV=190.;Prism2VoltageV=-190.}
@{flights=$script:flights;providers=$script:providers}|ConvertTo-Json -Compress
"""
        with TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "same-bank.ps1"
            fixture.write_text(script, encoding="utf-8")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(fixture),
                str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"), temporary],
                cwd=PROJECT, capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout), dict(flights=1, providers=0))

    def test_resume_reads_light_state_without_changing_terminal_or_lineage(self):
        script = r"""
param($Source,$StatePath,$Python,$RepoRoot)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and
 $n.Extent.Text.Contains('Saved workpoint state could not be read.')-and
 $n.Extent.Text.StartsWith('if($resumeBootstrapPath)')},$true)
function Invoke-RunToolRootContext {param($RepoRoot,[scriptblock]$Operation)
 Push-Location $RepoRoot;try{& $Operation}finally{Pop-Location}}
$resumeBootstrapPath=$StatePath;$python=$Python;$repoRoot=$RepoRoot
$seedVoltages=@(1,2,3,4);$steps=@(.01,.02,.03,.04)
$bootstrap=@{children=@()};$replayTerminalStages=$false
Invoke-Expression $node.Extent.Text
$bootstrap|ConvertTo-Json -Depth 100 -Compress
"""
        record = {"voltages_v": [1, 2, 3, 4], "residuals": {"s": 5.0},
                  "field_binding": {"mode": "comsol_static_scalar_v", "path": "real.json",
                    "response_weight_l1_norm": 2.0, "response_terms": [
                        {"coefficient": 1.0, "binding_path": "base.json",
                         "binding": {"geometry": "x" * 100000}}]}}
        state = {"schema_version": 1, "role": "mrtof_native_workpoint_bootstrap",
                 "seed_voltages_v": [1, 2, 3, 4], "forward_steps_v": [.01, .02, .03, .04],
                 "children": [], "stage_state": {"candidate_count": 8, "flight_count": 17},
                 "stage_history": {"decisions": [{"observation_record": record,
                    "stage_observation_record": record, "full_workpoint_qualified": False,
                    "terminal_reason": "model_recovery_exhausted"}]},
                 "stage_lineage": {"children": [{"child_manifest": "sealed-child.json"}]}}
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            command, saved = root / "resume.ps1", root / "state.json"
            command.write_text(script, encoding="utf-8")
            saved.write_text(json.dumps(state), encoding="utf-8")
            before = saved.read_bytes()
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(command),
                str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"),
                str(saved), sys.executable, str(PROJECT.parents[1])],
                cwd=PROJECT.parents[1], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(saved.read_bytes(), before)
            restored = json.loads(result.stdout)
            self.assertEqual(restored["stage_state"], state["stage_state"])
            self.assertEqual(restored["stage_lineage"], state["stage_lineage"])
            decision = restored["stage_history"]["decisions"][0]
            self.assertFalse(decision["full_workpoint_qualified"])
            self.assertEqual(decision["terminal_reason"], "model_recovery_exhausted")
            self.assertNotIn("stage_observation_record", decision)
            self.assertLess(len(result.stdout), 2500)

    def test_response_capacity_protects_actual_assets_not_unfrozen_declaration_source(self):
        script = r"""
param($Source)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and
 $n.Extent.Text.Contains('foreach($term in $responseBinding.response_terms)')},$true)
$ResponseFieldBindingPath='repository/scratch/mrtof_s_response_once.json';$workflowInputPaths=@()
$terms=@(0..2|ForEach-Object{
 $binding=@{export_manifest="artifact/$_/export.json";assembly_manifest="artifact/$_/assembly.json";
 collision_manifest="artifact/$_/collision.json";sources=@{potential="artifact/$_/field.pa";valid="artifact/$_/valid.pa"}}
 if($_-ne1){$binding.refinement_windows=@(@{sources=@{potential="artifact/$_/window.pa";valid="artifact/$_/window-valid.pa"}})}
 @{binding_path="artifact/$_/binding.json";binding=$binding}
})
$responseBinding=@{response_terms=$terms}
Invoke-Expression $node.Extent.Text
$workflowInputPaths|ConvertTo-Json
"""
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "capacity.ps1"
            path.write_text(script, encoding="utf-8")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(path),
                str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1")],
                cwd=PROJECT.parents[1], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            protected = json.loads(result.stdout)
            self.assertNotIn("repository/scratch/mrtof_s_response_once.json", protected)
            self.assertEqual(len(protected), 22)
            for index in range(3):
                self.assertIn(f"artifact/{index}/binding.json", protected)
                self.assertIn(f"artifact/{index}/field.pa", protected)
                self.assertIn(f"artifact/{index}/valid.pa", protected)
            source = (PROJECT / "analysis/run_downstream_workpoint_iteration.ps1").read_text(encoding="utf-8-sig")
            self.assertIn("Copy-VerifiedRunInput -Source $ResponseFieldBindingPath", source)

    def _run_response_dispatch_fixture(self, *, fixed_mismatch=False, same_source=False, completed=False, p1_response=False, retained=False, retained_invalid=False):
        """Execute the real centre dispatcher, replacing only solver/CLI boundaries."""
        script = r"""
param($Source,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-CenterTrial'},$true)
Invoke-Expression $node.Extent.Text
$fixture=Get-Content (Join-Path $Root 'fixture.json') -Raw|ConvertFrom-Json -AsHashtable
$repoRoot=$Root;$artifactRoot=$Root;$package=@{input_dir=$Root};$capacitySession=@{}
$trialArtifactRoot=$artifactRoot
$staticFieldMode=$true;$python='Invoke-MockPython';$script:flights=@();$script:providerCalls=0;$script:bindingChecks=0
$ResponseFieldBindingPath='declared.json';$CompletedFieldProviderManifest=if($fixture.completed){Join-Path $Root 'completed.json'}else{''}
$responseDeclaration=@{schema_version=2;role='mrtof_static_comsol_field_binding';baseline_binding='base.json';voltage_responses=@{s1=@{binding='s1.json'};s2=@{binding='s2.json'}};target_ps_voltages_v=@{s1=-27.;s2=54.;p1=189.;p2=-190.}}
if($fixture.p1_response){$responseDeclaration.voltage_responses.p1=@{binding='p1.json'}}
$fieldProviderRequest=@{role='mrtof_same_mesh_field_provider_request';source_binding_path='source.json';candidate_voltages_v=@{s1=-27.;s2=54.;p1=189.;p2=-190.}}
if($fixture.retained){$fieldProviderRequest.role='mrtof_native_static_field_provider_request'}
$staticBinding=@{authority=@{analyzer_electrode_voltages_v=@(0,0,0,0,0,0,0,0,0,0,-27,-27,54,54,0,189,-190,0,0,0)}}
function Invoke-RunToolRootContext {param($RepoRoot,[scriptblock]$Operation)& $Operation}
function Write-RunJson {param($Path,$Depth,$Value)$Value|ConvertTo-Json -Depth $Depth|Set-Content $Path}
function Update-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session,$ProtectedPaths)@{session=$Session}}
function Invoke-MockPython {
 param([Parameter(ValueFromRemainingArguments=$true)][object[]]$TestArguments)
 $CommandArgs=$TestArguments
 $global:LASTEXITCODE=0
 if([string]$CommandArgs[1]-like'*Retained provider ownership differs*'){
  if($fixture.retained_invalid){$global:LASTEXITCODE=1;return}
  'retained-binding.json'|ConvertTo-Json;return
 }
 if($CommandArgs-contains'--resolve-completed-request'){@{binding='completed-binding.json'}|ConvertTo-Json;return}
 if($CommandArgs-contains'--binding'){
  $script:bindingChecks++
  $path=[string]$CommandArgs[[array]::IndexOf($CommandArgs,'--binding')+1]
  $descriptor=Get-Content $path -Raw|ConvertFrom-Json -AsHashtable
  $u=@($staticBinding.authority.analyzer_electrode_voltages_v)
  $u[10]=$u[11]=$descriptor.target_ps_voltages_v.s1;$u[12]=$u[13]=$descriptor.target_ps_voltages_v.s2
  if($descriptor.voltage_responses.ContainsKey('p1')){$u[15]=$descriptor.target_ps_voltages_v.p1}
  if($fixture.fixed_mismatch){$u[15]+=1.}
  @{authority=@{analyzer_electrode_voltages_v=$u};response_weight_l1_norm=4.}|ConvertTo-Json -Depth 20;return
 }
 if([string]$CommandArgs[1]-like'*print(json.dumps*'){
  ([bool]$fixture.same_source)|ConvertTo-Json -Compress;return
 }
 $request=[string]$CommandArgs[2]|ConvertFrom-Json -AsHashtable
 $descriptor=Get-Content ([string]$CommandArgs[3]) -Raw|ConvertFrom-Json -AsHashtable
 $authority=@{analyzer_electrode_voltages_v=@($staticBinding.authority.analyzer_electrode_voltages_v)}
 if($descriptor.voltage_responses.ContainsKey('p1')){$authority.analyzer_electrode_voltages_v[15]=$descriptor.target_ps_voltages_v.p1}
 if($fixture.fixed_mismatch){$authority.analyzer_electrode_voltages_v[15]+=1.}
 if($authority.analyzer_electrode_voltages_v[15]-ne$request.candidate_voltages_v.p1-or
    $authority.analyzer_electrode_voltages_v[16]-ne$request.candidate_voltages_v.p2){$global:LASTEXITCODE=1}
}
function Invoke-MockProvider {param($RequestPath,$RunDirectory,[switch]$Approved)$script:providerCalls++;throw 'Unexpected commercial field request'}
function Invoke-MockTrial {
 param($RunId,$Prism1VoltageV,$Prism2VoltageV,$Stripe1VoltageV,$Stripe2VoltageV,$FieldBindingPath,$CapacityWorkflowSession)
 $script:flights+=,@{binding=$FieldBindingPath;voltages=@($Stripe1VoltageV,$Stripe2VoltageV,$Prism1VoltageV,$Prism2VoltageV)}
}
$fieldProviderRunner='Invoke-MockProvider';$trialRunner='Invoke-MockTrial'
$arguments=@{ContractPath='frozen.json';RunId='candidate';Prism1VoltageV=189.;Prism2VoltageV=-190.;Stripe1VoltageV=-28.;Stripe2VoltageV=55.}
if($fixture.p1_response){$arguments.Prism1VoltageV=191.}
$failure=$null
$pending=if($fixture.retained){@{provider_reference=@{operation='compose';provider_manifest=(Join-Path $Root 'old-field/run_manifest.json')}}}else{$null}
try{Invoke-CenterTrial -Arguments $arguments -StagedPending $pending}catch{$failure=$_.Exception.Message}
$descriptorPath=Join-Path $Root 'candidate-field_response_binding.json'
$descriptor=if(Test-Path $descriptorPath){Get-Content $descriptorPath -Raw|ConvertFrom-Json -AsHashtable}else{$null}
@{flights=$script:flights;provider_calls=$script:providerCalls;binding_checks=$script:bindingChecks;failure=$failure;descriptor=$descriptor}|ConvertTo-Json -Depth 100|Set-Content (Join-Path $Root 'output.json')
"""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "fixture.json").write_text(json.dumps(dict(
                fixed_mismatch=fixed_mismatch, same_source=same_source, completed=completed, p1_response=p1_response,
                retained=retained, retained_invalid=retained_invalid
            )), encoding="utf-8")
            fixture = root / "dispatch.ps1"
            fixture.write_text(script, encoding="utf-8")
            result = subprocess.run([
                "pwsh", "-NoProfile", "-File", str(fixture),
                str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"), temporary,
            ], cwd=PROJECT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=40)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads((root / "output.json").read_text(encoding="utf-8-sig"))

    def test_pending_successful_provider_dispatch_reuses_field_without_composition(self):
        result = self._run_response_dispatch_fixture(retained=True)
        self.assertIsNone(result["failure"])
        self.assertEqual(result["provider_calls"], 0)
        self.assertEqual(result["binding_checks"], 0)
        self.assertEqual(result["flights"][0]["binding"], "retained-binding.json")

    def test_pending_invalid_provider_fails_before_flight_or_composition(self):
        result = self._run_response_dispatch_fixture(retained=True, retained_invalid=True)
        self.assertEqual(result["failure"], "Retained pending provider validation failed.")
        self.assertEqual(result["flights"], [])
        self.assertEqual(result["provider_calls"], 0)

    def test_retained_provider_selector_checks_target_operator_and_unflown_identity(self):
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import static_field_binding as fields
        from projects.parallel_mirror_dual_stripe_mr_tof.analysis import corridor_field_provider as provider
        source = (PROJECT / "analysis/run_downstream_workpoint_iteration.ps1").read_text(encoding="utf-8-sig")
        code = re.search(r"\$retainedCode=@'\n(.*?)\n'@", source, re.S).group(1)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            owner = root / "old-stage-001-field"
            owner.mkdir()
            request_path = root / "request.json"
            request_path.write_text("{}", encoding="utf-8")
            binding_path = owner / "binding.json"
            binding_path.write_text("{}", encoding="utf-8")
            summary = owner / "summary.json"
            summary.write_text(json.dumps({"field_binding": str(binding_path)}), encoding="utf-8")
            record = lambda p: dict(path=str(p), bytes=p.stat().st_size,
                                    sha256=hashlib.sha256(p.read_bytes()).hexdigest())
            config_path=owner/"run_config.json"
            config_text=json.dumps(dict(parameters=dict(operation="refine")))
            config_path.write_text(config_text,encoding="utf-8")
            manifest_path = owner / "run_manifest.json"
            manifest = dict(status="success", mode="native_static_field_provider", run_id=owner.name,
                            inputs={"request": record(request_path)},
                            run_config=record(config_path),
                            outputs=[record(summary), record(binding_path)])
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            reference = dict(operation="compose", child_run_id="old-stage-001", provider_manifest=str(manifest_path),
                             request_path=str(request_path), provider_manifest_sha256=record(manifest_path)["sha256"],
                             request_sha256=record(request_path)["sha256"])
            request = dict(source_binding_path=str(root / "source.json"), numerical_contract_path="contract.json")
            authority = {"voltages": [1, 2, 3]}
            baseline = {"authority": authority, "operator": "fixed"}
            for scenario in ("valid", "wrong_voltage", "wrong_operator", "wrong_numerics", "already_flown", "changed_manifest",
                             "refine_valid","refine_response_request","refine_config_tampered",
                             "prepared_failed","prepared_interrupted","prepared_success","legacy_failed","prepared_wrong_identity"):
                with self.subTest(scenario=scenario):
                    config_path.write_text(config_text,encoding="utf-8")
                    retained = dict(authority=authority, operator="fixed")
                    if scenario == "wrong_voltage":
                        retained["authority"] = {"voltages": [1, 2, 4]}
                    if scenario == "wrong_operator":
                        retained["operator"] = "different"
                    old_trial = root / "old-stage-001" / "run_manifest.json"
                    if scenario == "already_flown":
                        old_trial.parent.mkdir(exist_ok=True)
                        old_trial.write_text("{}", encoding="utf-8")
                    if scenario.startswith(('prepared_','legacy_')):
                        old_trial.parent.mkdir(exist_ok=True)
                        old_trial.write_text(json.dumps({'run_id':'wrong' if scenario=='prepared_wrong_identity' else 'old-stage-001',
                            'status':scenario.split('_')[-1] if scenario!='prepared_wrong_identity' else 'failed'}))
                    selected_ref = dict(reference)
                    selected_request=dict(request)
                    if scenario.startswith("refine_"):
                        selected_ref["operation"]="refine"
                    if scenario=="refine_response_request":
                        selected_request["response_basis_paths"]={"p1":"response.json"}
                    if scenario=="refine_config_tampered":
                        config_path.write_text(json.dumps(dict(parameters=dict(operation="compose"))))
                    if scenario == "changed_manifest":
                        selected_ref["provider_manifest_sha256"] = "0" * 64
                    with patch.object(sys, "argv", ["selector", json.dumps(selected_request), json.dumps(selected_ref),
                                                   'prepared' if scenario.startswith('prepared_') else 'legacy']), \
                            patch.object(fields, "load_binding", side_effect=lambda p, **kw: retained if p == binding_path else baseline), \
                            patch.object(fields, "native_numerics_match", return_value=scenario != "wrong_numerics"), \
                            patch.object(fields, "native_response_operator", side_effect=lambda b, a: b["operator"]), \
                            patch.object(provider, "derive_candidate_authority", return_value=(authority, None)):
                        if scenario in {"valid","refine_valid","prepared_failed","prepared_interrupted"}:
                            output = io.StringIO()
                            with redirect_stdout(output):
                                exec(compile(code, "retained-selector", "exec"), {})
                            self.assertEqual(json.loads(output.getvalue()), str(binding_path))
                        else:
                            with self.assertRaises(AssertionError):
                                exec(compile(code, "retained-selector", "exec"), {})
                    if old_trial.exists():
                        old_trial.unlink()

    def test_explicit_response_dispatch_derives_trial_target_without_solving(self):
        result = self._run_response_dispatch_fixture()
        self.assertIsNone(result["failure"])
        self.assertEqual(result["provider_calls"], 0)
        self.assertEqual(result["binding_checks"], 1)
        self.assertEqual(result["descriptor"]["target_ps_voltages_v"], dict(s1=-28., s2=55., p1=189., p2=-190.))
        self.assertEqual(result["flights"][0]["voltages"], [-28., 55., 189., -190.])

    def test_response_fixed_authority_mismatch_rejects_before_flight(self):
        result = self._run_response_dispatch_fixture(fixed_mismatch=True)
        self.assertIn("cannot supply this candidate", result["failure"])
        self.assertEqual(result["flights"], [])
        self.assertEqual(result["provider_calls"], 0)

    def test_response_p1_candidate_transports_actual_four_axis_target_without_solving(self):
        result = self._run_response_dispatch_fixture(p1_response=True)
        self.assertIsNone(result["failure"])
        self.assertEqual(result["provider_calls"], 0)
        self.assertEqual(result["descriptor"]["target_ps_voltages_v"], dict(s1=-28., s2=55., p1=191., p2=-190.))
        self.assertEqual(result["flights"][0]["voltages"], [-28., 55., 191., -190.])

    def test_source_and_completed_direct_fields_take_precedence_over_response(self):
        for options, expected in ((dict(same_source=True), "source.json"),
                                  (dict(completed=True), "completed-binding.json")):
            result = self._run_response_dispatch_fixture(**options)
            self.assertIsNone(result["failure"])
            self.assertEqual(result["binding_checks"], 0)
            self.assertEqual(result["flights"][0]["binding"], expected)

    def test_response_resume_allows_explicit_first_enable_but_rejects_basis_drift(self):
        script = r"""
param($Source,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Assert-ResponseFieldResumeDeclaration'},$true)
Invoke-Expression $node.Extent.Text
$declaration=[ordered]@{schema_version=2;baseline_binding='base.json';voltage_responses=@{s1=@{binding='s1.json'};s2=@{binding='s2.json'}};target_ps_voltages_v=@{s1=-27.;s2=54.;p1=189.;p2=-190.}}
Assert-ResponseFieldResumeDeclaration -ParentRun $Root -BindingPath 'explicit.json' -Declaration $declaration
Assert-ResponseFieldResumeDeclaration -ParentRun $Root -BindingPath '' -Declaration $null
$inputs=New-Item -ItemType Directory (Join-Path $Root 'inputs')
$declaration|ConvertTo-Json -Depth 20|Set-Content (Join-Path $inputs 'response_field_binding.json')
$declared=Get-Content (Join-Path $inputs 'response_field_binding.json') -Raw|ConvertFrom-Json -AsHashtable
Assert-ResponseFieldResumeDeclaration -ParentRun $Root -BindingPath 'frozen-copy.json' -Declaration $declared
$reordered=[ordered]@{schema_version=2;target_ps_voltages_v=@{s1=-28.;s2=55.;p1=189.;p2=-190.};voltage_responses=@{s2=@{binding='./s2.json'};s1=@{binding='s1.json'}};baseline_binding='./base.json'}
Assert-ResponseFieldResumeDeclaration -ParentRun $Root -BindingPath 'reordered.json' -Declaration $reordered
$reordered.voltage_responses.s1.baseline_binding='./base.json'
Assert-ResponseFieldResumeDeclaration -ParentRun $Root -BindingPath 'explicit-origin.json' -Declaration $reordered
$declared.voltage_responses.s1.baseline_binding='old-base.json'
$declared|ConvertTo-Json -Depth 20|Set-Content (Join-Path $inputs 'response_field_binding.json')
$reordered.voltage_responses.s1.baseline_binding='./old-base.json'
Assert-ResponseFieldResumeDeclaration -ParentRun $Root -BindingPath 'same-cross-origin.json' -Declaration $reordered
$reordered.voltage_responses.s1.baseline_binding='other-origin.json'
try{Assert-ResponseFieldResumeDeclaration -ParentRun $Root -BindingPath 'changed-origin.json' -Declaration $reordered;throw 'origin drift accepted'}catch{if($_.Exception.Message-notlike'*basis differs*'){throw}}
$reordered.voltage_responses.s1.Remove('baseline_binding')
try{Assert-ResponseFieldResumeDeclaration -ParentRun $Root -BindingPath 'dropped-origin.json' -Declaration $reordered;throw 'cross origin dropped'}catch{if($_.Exception.Message-notlike'*basis differs*'){throw}}
$declared.voltage_responses.s1.Remove('baseline_binding')
$declared|ConvertTo-Json -Depth 20|Set-Content (Join-Path $inputs 'response_field_binding.json')
$declared.voltage_responses.p1=@{binding='p1.json'}
try{Assert-ResponseFieldResumeDeclaration -ParentRun $Root -BindingPath 'extra-axis.json' -Declaration $declared;throw 'axis drift accepted'}catch{if($_.Exception.Message-notlike'*basis differs*'){throw}}
$declared|ConvertTo-Json -Depth 20|Set-Content (Join-Path $inputs 'response_field_binding.json')
try{Assert-ResponseFieldResumeDeclaration -ParentRun $Root -BindingPath 'drop-axis.json' -Declaration $reordered;throw 'P1 identity dropped'}catch{if($_.Exception.Message-notlike'*basis differs*'){throw}}
$declared.voltage_responses.Remove('p1')
$declared|ConvertTo-Json -Depth 20|Set-Content (Join-Path $inputs 'response_field_binding.json')
try{Assert-ResponseFieldResumeDeclaration -ParentRun $Root -BindingPath '' -Declaration $null;throw 'missing declaration accepted'}catch{if($_.Exception.Message-notlike'*must retain*'){throw}}
$declared.baseline_binding='other-base.json'
try{Assert-ResponseFieldResumeDeclaration -ParentRun $Root -BindingPath 'changed.json' -Declaration $declared;throw 'drift accepted'}catch{if($_.Exception.Message-notlike'*basis differs*'){throw}}
'RESPONSE_RESUME=PASS'
"""
        with TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "resume.ps1"
            fixture.write_text(script, encoding="utf-8")
            result = subprocess.run([
                "pwsh", "-NoProfile", "-File", str(fixture),
                str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"), temporary,
            ], cwd=PROJECT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=40)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("RESPONSE_RESUME=PASS", result.stdout)

    def test_prism_model_publication_uses_public_light_lifecycle_and_seals_original_inputs(self):
        script = r"""
param($Source,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Publish-StagedPrismModel'},$true)
Invoke-Expression $node.Extent.Text
$python='python';$repoRoot=$Root;$artifactRoot=$Root;$artifactWorkspaceRoot=$Root
$trialArtifactRoot=$artifactRoot
$project='parallel_mirror_dual_stripe_mr_tof';$frozenContract='frozen-contract.json';$controllerSource='frozen-controller.py';$controllerStateSource='frozen-controller-state.py'
$script:statuses=@();$script:retentions=0
function New-RunPackage {
 param($Python,$RepoRoot,$ArtifactRoot,$RunId,$Project,$Mode,$Software,
       [switch]$RetentionContractEnabled,[switch]$CapacityLedgerLifecycleEnabled,$CapacityLedgerArtifactRoot)
 if(-not$RetentionContractEnabled-or-not$CapacityLedgerLifecycleEnabled-or$Mode-ne'prism_preclosure_analysis'){throw 'Missing public light lifecycle'}
 $dir=Join-Path $Root $RunId;New-Item -ItemType Directory $dir|Out-Null
 @{inputs=@{}}|ConvertTo-Json|Set-Content (Join-Path $dir 'run_config.json')
 return @{artifact_run_dir=$dir;result_dir=$dir;run_config=(Join-Path $dir 'run_config.json');summary=(Join-Path $dir 'summary.json')}
}
function Write-RunJson {param($Path,$Depth,$Value)$Value|ConvertTo-Json -Depth 100|Set-Content $Path}
function Apply-RunArtifactRetention {param($Python,$RepoRoot,$RunConfig)$script:retentions++;return Join-Path (Split-Path $RunConfig) 'retention_actions.json'}
function Write-VerifiedRunManifest {
 param($Python,$RepoRoot,$RunConfig,$Status,$Software,$Outputs)
 $script:statuses+=,@{status=$Status;outputs=@($Outputs)}
 if($Root.EndsWith('failed')-and$Status-eq'success'){throw 'sealed model publication failed'}
 @{status=$Status}|ConvertTo-Json|Set-Content (Join-Path (Split-Path $RunConfig) 'run_manifest.json')
}
$state=@{flight_count=2;anchor_manifest='measured-anchor.json';columns=@{'2'='p1-flight.json';'3'='p2-flight.json'}}
$decision=@{role='mrtof_prism_preclosure_decision';status='proposed';anchor_manifest=$state.anchor_manifest}
$errorMessage=$null;$manifest=$null
try{$manifest=Publish-StagedPrismModel -State $state -Decision $decision}catch{$errorMessage=$_.Exception.Message}
$dir=(Get-ChildItem -LiteralPath $Root -Directory|Select-Object -First 1).FullName
@{manifest=$manifest;failure=$errorMessage;statuses=$script:statuses;retentions=$script:retentions;
 config=(Get-Content (Join-Path $dir 'run_config.json') -Raw|ConvertFrom-Json);
 decision=(Get-Content (Join-Path $dir 'prism_preclosure_decision.json') -Raw|ConvertFrom-Json)}|ConvertTo-Json -Depth 100|Set-Content (Join-Path $Root 'output.json')
"""
        for failed in (False, True):
            with self.subTest(failed=failed), TemporaryDirectory() as temporary:
                root = Path(temporary) / ("failed" if failed else "success")
                root.mkdir()
                fixture = root / "publication.ps1"
                fixture.write_text(script, encoding="utf-8")
                process = subprocess.run([
                    "pwsh", "-NoProfile", "-File", str(fixture),
                    str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"), str(root),
                ], cwd=PROJECT, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=40)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                result = json.loads((root / "output.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(result["config"]["inputs"], {
                    "baseline_manifest": "measured-anchor.json", "workpoint_contract": "frozen-contract.json",
                    "controller_source": "frozen-controller.py", "p1_child_manifest": "p1-flight.json",
                    "controller_state_source": "frozen-controller-state.py",
                    "p2_child_manifest": "p2-flight.json"})
                self.assertEqual(result["decision"]["anchor_manifest"], "measured-anchor.json")
                self.assertEqual([s["status"] for s in result["statuses"]],
                                 ["success", "failed"] if failed else ["success"])
                self.assertEqual(result["retentions"], 2 if failed else 1)
                self.assertEqual(result["failure"], "sealed model publication failed" if failed else None)
                self.assertEqual(len(result["statuses"][-1]["outputs"]), 3)

    def _run_stage_fixture(self, decisions, state=None, *, interrupt_after_publish=False, corrupt_voltage=False,
                           replay_manifest="measured-P-replay.json",
                           initial_model="", imported_columns=None, compose_owned=False,
                           stencil_gate=None, controller_policy=None, active_stripe_axes=None, expected_failure=False,
                           single_stripe_refinement_mode=None,prepared_build_mode=None,provider_capacity_block=False):
        """Execute the production AST functions; mock only flights and CLI I/O."""
        script = r"""
param($Source,$Root,$RealPython,$RealRepo)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
foreach($name in @('Get-ActiveStripeAxisIndices','Get-StagedColumnAxisIndices','Assert-ActiveStripeVoltages','Invoke-PreclosureDecision','Invoke-StagedPreclosureDecision','Complete-StagedTrial','Restore-StagedWorkpointChildren','Import-StagedStripeColumns','Invoke-StagedWorkpointBootstrap')){
  $node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)
  Invoke-Expression $node.Extent.Text
}
$fixture=Get-Content (Join-Path $Root 'fixture.json') -Raw|ConvertFrom-Json -AsHashtable
$script:preparedStagedMode=$null-ne$fixture.prepared_build_mode
$script:PreparedFieldBuildMode=$fixture.prepared_build_mode
$frozenPreparedTargetAuthorityPath='frozen-target';$frozenPreparedInitialProposalPath='frozen-proposal'
$fieldProviderRequest=@{}
if($fixture.prepared_build_mode-eq'composition'){$fieldProviderRequest['response_basis_paths']=@{p1='p1';p2='p2'}}
$script:queue=@($fixture.decisions);$script:requests=@();$script:flights=@();$script:saves=@();$script:models=@();$script:controllerActions=@()
$repoRoot=$Root;$artifactRoot=$Root;$RunId='stage';$python='Invoke-MockController'
$trialArtifactRoot=$artifactRoot
$package=@{result_dir=$Root};$seedManifest=Join-Path $Root 'seed.json';'{}'|Set-Content $seedManifest
$PrismHandoffReplayManifest=[string]$fixture.replay_manifest
$PriorPrismDecisionManifest=[string]$fixture.initial_model
$frozenContract=Join-Path $Root 'contract.json'
$controllerContext=@{repo_root=$repoRoot;python=$python;contract_path=$frozenContract;result_directory=$Root;prepared_staged=$script:preparedStagedMode;target_authority_path=$frozenPreparedTargetAuthorityPath;initial_proposal_path=$frozenPreparedInitialProposalPath;prism_handoff_replay_manifest=$PrismHandoffReplayManifest;run_id=$RunId;artifact_root=$artifactRoot;prepared_field_build_mode=$PreparedFieldBuildMode}
$policyPath=''
if($fixture.controller_policy){
 $policyPath=Join-Path $Root 'policy.json'
 $fixture.controller_policy|ConvertTo-Json|Set-Content $policyPath
}
@{downstream_fixed_grid_workpoint_profile=@{
 active_stripe_axes=@($fixture.active_stripe_axes)
 automatic_iteration=@{maximum_iterations=8;minimum_step_linf_v=.00001;minimum_relative_improvement=.1;maximum_consecutive_non_improving_iterations=3}
 jacobian_relative_step_tiers=@{coarse=.01;medium=.0025;fine=.0005;medium_maximum_scaled_residual=5.;fine_maximum_scaled_residual=2.}
}}|ConvertTo-Json -Depth 10|Set-Content $frozenContract
if($fixture.single_stripe_refinement_mode){
 $contract=Get-Content $frozenContract -Raw|ConvertFrom-Json -AsHashtable
 $contract.downstream_fixed_grid_workpoint_profile.single_stripe_refinement_mode=$fixture.single_stripe_refinement_mode
 $contract|ConvertTo-Json -Depth 10|Set-Content $frozenContract
}
$transport=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-WorkpointControllerRequest'},$true)
Invoke-Expression ($transport.Extent.Text.Replace('function Invoke-WorkpointControllerRequest','function Invoke-RealControllerRequest'))
function Invoke-WorkpointControllerRequest {param($Request,$Python,$RepoRoot) $script:controllerActions+=,@{action=$Request.action;phase=$Request['phase']};Invoke-RealControllerRequest -Request $Request -Python $RealPython -RepoRoot $RealRepo}
function Invoke-RunToolRootContext {param($RepoRoot,[scriptblock]$Operation)& $Operation}
function Write-RunJson {param($Path,$Depth,$Value)$Value|ConvertTo-Json -Depth $Depth|Set-Content $Path}
function Save-WorkpointBootstrap {
 param($Bootstrap,$BootstrapPath)
 $script:saves+=,($Bootstrap|ConvertTo-Json -Depth 100|ConvertFrom-Json -AsHashtable)
}
function Reclaim-StagedComposeProviders {param($State,$Lineage)}
function Assert-StagedComposeProviderReference {param($Reference,$ChildRunId,$Context) return $Reference}
function Publish-StagedPrismModel {
 param($State,$Decision)
 $script:models+=,@{anchor=$State.anchor_manifest;columns=($State.columns|ConvertTo-Json|ConvertFrom-Json -AsHashtable);decision=$Decision}
 return Join-Path $Root ('measured-model-'+$script:models.Count+'/run_manifest.json')
}
function New-CenterTrialArguments {param($Voltages,$ChildRunId)@{Voltages=@($Voltages);ChildRunId=$ChildRunId}}
function Get-ManifestOutputPath {param($ManifestPath,$FileName)Join-Path (Split-Path $ManifestPath) $FileName}
function Invoke-CenterTrial {
 param($Arguments,$StagedPending,$Bootstrap,$BootstrapPath)
 if($fixture.provider_capacity_block){
  $Bootstrap.stage_state['capacity_lifecycle_blocked']=@{reason='public startup refusal';candidate_flight_executed=$false;no_private_delete=$true}
  return
 }
 if($fixture.compose_owned){$StagedPending['provider_reference']=@{parent_run_id='stage';child_run_id=$Arguments.ChildRunId;operation='compose'}}
 $script:flights+=,$Arguments
 $dir=Join-Path $Root ('runs/'+$Arguments.ChildRunId);New-Item -ItemType Directory $dir -Force|Out-Null
 @{status='success';run_id=$Arguments.ChildRunId}|ConvertTo-Json|Set-Content (Join-Path $dir 'run_manifest.json')
 $u=@($Arguments.Voltages)
 if($fixture.corrupt_voltage){$u[0]+=1.}
 @{stripe_biases_v=@($u[0],$u[1]);prism_voltages_v=@($u[2],$u[3])}|ConvertTo-Json|Set-Content (Join-Path $dir 'two_prism_trial_materialization.json')
 if($fixture.interrupt_after_publish){$fixture.interrupt_after_publish=$false;throw 'published child interruption'}
}
function Invoke-MockController {
 param([Parameter(ValueFromRemainingArguments=$true)][object[]]$TestArguments)
 $CommandArgs=$TestArguments
 if($CommandArgs-contains'-c'){$global:LASTEXITCODE=0;return}
 $request=[ordered]@{}
 foreach($flag in @('--control-stage','--child-manifest','--s1-child-manifest','--s2-child-manifest','--p1-child-manifest','--p2-child-manifest','--prism-handoff-replay-manifest','--prior-prism-decision-manifest','--prism-controller-policy')){
  $index=[array]::IndexOf($CommandArgs,$flag)
  if($index-ge0){$request[$flag]=[string]$CommandArgs[$index+1]}
 }
 $index=[array]::IndexOf($CommandArgs,'--output')
 if(-not$fixture.compose_owned-and[IO.Path]::GetFileName([string]$CommandArgs[$index+1])-like'iteration_staged_payload_*'){
  $gate=if($fixture.stencil_gate){$fixture.stencil_gate}else{@{full_workpoint_qualified=$false}}
  Write-RunJson -Path ([string]$CommandArgs[$index+1]) -Depth 100 -Value $gate
  $global:LASTEXITCODE=0;return
 }
 $script:requests+=,$request
 if($script:queue.Count-eq0){throw 'Unexpected extra controller call'}
 $decision=$script:queue[0];$script:queue=@($script:queue|Select-Object -Skip 1)
 if($request.Contains('--prism-controller-policy')){
  $p=$request['--prism-controller-policy']
  $decision['prism_controller_policy']=@{path=$p;sha256=(Get-FileHash $p -Algorithm SHA256).Hash.ToLowerInvariant()}
 }
 $index=[array]::IndexOf($CommandArgs,'--output')
 Write-RunJson -Path ([string]$CommandArgs[$index+1]) -Depth 100 -Value $decision
 $global:LASTEXITCODE=0
}
$bootstrap=[ordered]@{}
$stripeSeedColumns=[ordered]@{}
foreach($axis in $fixture.imported_columns.Keys){
 $saved=$fixture.imported_columns[$axis];$dir=New-Item -ItemType Directory (Join-Path $Root ('imported-'+$axis))
 $path=Join-Path $dir 'run_manifest.json'
 @{status='success';run_id=('imported-'+$axis)}|ConvertTo-Json|Set-Content $path
 @{stripe_biases_v=@($saved[0],$saved[1]);prism_voltages_v=@($saved[2],$saved[3])}|ConvertTo-Json|Set-Content (Join-Path $dir 'two_prism_trial_materialization.json')
 $stripeSeedColumns[$axis]=$path
}
if($fixture.state){
 $bootstrap.stage_state=$fixture.state
 $bootstrap.stage_state.anchor_manifest=$seedManifest
  if($bootstrap.stage_state.Contains('pending_trial')){$bootstrap.stage_state.pending_trial.anchor_manifest=$seedManifest}
 foreach($key in @($bootstrap.stage_state.columns.Keys)){
  $path=Join-Path $Root ([string]$bootstrap.stage_state.columns[$key]);'{}'|Set-Content $path
  $bootstrap.stage_state.columns[$key]=$path
 }
}
$failure=$null;$result=$null
try{
 $result=Invoke-StagedWorkpointBootstrap -Bootstrap $bootstrap -BootstrapPath 'checkpoint' -ControllerPolicyPath $policyPath
}
catch{
 if($_.Exception.Message-eq'published child interruption'){
  $bootstrap=$script:saves[-1]|ConvertTo-Json -Depth 100|ConvertFrom-Json -AsHashtable
  $RunId='restart'
  $result=Invoke-StagedWorkpointBootstrap -Bootstrap $bootstrap -BootstrapPath 'checkpoint'
 }elseif($fixture.corrupt_voltage-or$fixture.imported_columns.Count-or$fixture.expected_failure){$failure=$_.Exception.Message}else{throw}
}
if(-not$failure-and$script:queue.Count-ne0){throw 'Unconsumed controller decisions'}
@{result=$result;failure=$failure;bootstrap=$bootstrap;requests=$script:requests;flights=$script:flights;saves=$script:saves;models=$script:models;controller_actions=$script:controllerActions}|ConvertTo-Json -Depth 100|Set-Content (Join-Path $Root 'output.json')
"""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "fixture.json").write_text(
                json.dumps({"decisions": decisions, "state": state,
                            "interrupt_after_publish": interrupt_after_publish,
                            "replay_manifest": replay_manifest,
                            "initial_model": initial_model,
                            "imported_columns": imported_columns or {},
                            "compose_owned": compose_owned, "stencil_gate": stencil_gate,
                            "controller_policy": controller_policy,
                            "active_stripe_axes": active_stripe_axes if active_stripe_axes is not None else
                                ["stripe_1_voltage_v", "stripe_2_voltage_v"],
                            "expected_failure": expected_failure,
                            "single_stripe_refinement_mode": single_stripe_refinement_mode,
                            "prepared_build_mode":prepared_build_mode,
                            "provider_capacity_block":provider_capacity_block,
                            "corrupt_voltage": corrupt_voltage}), encoding="utf-8"
            )
            fixture = root / "fixture.ps1"
            fixture.write_text(script, encoding="utf-8")
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(fixture),
                 str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"), temporary, sys.executable, str(PROJECT.parents[1])],
                cwd=PROJECT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=40,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads((root / "output.json").read_text(encoding="utf-8-sig"))

    def test_staged_payload_disposition_keeps_qualified_or_ambiguous_and_marks_only_explicit_rejection(self):
        d = self._stage_decision
        for qualified, expected in ((True, 'keep'), (False, 'stencil')):
            with self.subTest(stencil_full_qualified=qualified):
                result = self._run_stage_fixture([
                    d('needs_stencil', required_axes=[2]),
                    d('terminal', full_workpoint_qualified=qualified),
                    d('terminal', terminal_reason='stop_fixture'),
                ], compose_owned=True)
                self.assertEqual(result['bootstrap']['stage_lineage']['children'][0]['compose_payload_use'], expected)
        for checked, expected in ((d('terminal', full_workpoint_qualified=False), 'rejected_candidate'),
                                  (d('terminal', full_workpoint_qualified=True), 'keep'),
                                  (d('needs_stencil', maximum_scaled_abs_residual=9.5), 'keep')):
            with self.subTest(candidate_status=checked['status'], expected=expected):
                result = self._run_stage_fixture([
                    d('proposed', next_action='evaluate', maximum_scaled_abs_residual=10,
                      next_voltages_v=[-28., 56., 189., -190.]),
                    checked, d('terminal', terminal_reason='stop_fixture'),
                ], compose_owned=True)
                self.assertEqual(result['bootstrap']['stage_lineage']['children'][0]['compose_payload_use'], expected)

    @staticmethod
    def _stage_decision(status, **changes):
        decision = {
            "status": status, "next_action": "measure_stencil",
            "voltages_v": [-27., 54., 189., -190.],
            "next_voltages_v": [-27., 54., 189., -190.],
            "required_axes": [], "full_workpoint_qualified": False,
            "maximum_scaled_abs_residual": 10., "backtrack_multiplier": .5,
            "resolved_numerics": {"lower_bounds_v": [-100., -100., 100., -300.],
                                  "upper_bounds_v": [100., 100., 300., -100.]},
        }
        decision.update(changes)
        return decision

    def test_only_composition_requires_s1_bank_after_actual_p_anchor(self):
        def decision(status,**changes):
            return self._stage_decision(status,voltages_v=[-27.,0.,189.,-190.],
                next_voltages_v=[-27.,0.,189.,-190.],**changes)
        first=[decision('stage_passed',next_action='stripe_preclosure'),decision('needs_stencil',required_axes=[0])]
        common=dict(active_stripe_axes=['stripe_1_voltage_v'],single_stripe_refinement_mode='joint_ps_constrained',replay_manifest='')
        composed=self._run_stage_fixture(first,prepared_build_mode='composition',**common)
        self.assertEqual(composed['result']['terminal_decision']['terminal_reason'],'needs_s1_response')
        self.assertEqual(composed['flights'],[])
        refined=self._run_stage_fixture([*first,decision('terminal',terminal_reason='fixture_stop')],prepared_build_mode='refine',**common)
        self.assertEqual(refined['result']['terminal_decision']['terminal_reason'],'fixture_stop')
        self.assertEqual(len(refined['flights']),1)
        self.assertEqual(refined['flights'][0]['Voltages'][1],0)
        self.assertNotEqual(refined['flights'][0]['Voltages'][0],-27.)
        capacity=self._run_stage_fixture(first,prepared_build_mode='refine',provider_capacity_block=True,**common)
        self.assertEqual(capacity['result']['terminal_decision']['terminal_reason'],'capacity_lifecycle_blocked')
        self.assertEqual(capacity['flights'],[])
        self.assertIn('pending_trial',capacity['bootstrap']['stage_state'])

    def test_cleared_policy_model_requires_both_fresh_prism_columns_without_resetting_counts(self):
        def decision(status,**changes):
            return self._stage_decision(status,voltages_v=[-27.,0.,189.,-190.],
                next_voltages_v=[-27.,0.,189.,-190.],**changes)
        policy=json.loads((PROJECT/'config/prism_controller_policy.json').read_text(encoding='utf-8-sig'))
        state=dict(stage='prism_preclosure',anchor_manifest='overridden-by-fixture',candidate_count=3,
                   flight_count=13,step_factor=.5,columns={},attempts=[],completion_attempted=False)
        result=self._run_stage_fixture([
            decision('needs_stencil',required_axes=[2,3]),
            decision('needs_stencil',required_axes=[3]),
            decision('terminal',terminal_reason='fixture_stop'),
        ],state,controller_policy=policy,active_stripe_axes=['stripe_1_voltage_v'],
            prepared_build_mode='composition',replay_manifest='')
        self.assertIsNone(result['failure'])
        self.assertEqual(len(result['flights']),2)
        self.assertEqual(set(result['bootstrap']['stage_state']['columns']),{'2','3'})
        self.assertEqual(result['bootstrap']['stage_state']['candidate_count'],3)
        self.assertEqual(result['bootstrap']['stage_state']['flight_count'],15)
        self.assertEqual(result['bootstrap']['stage_state']['step_factor'],.5)

    def test_full_qualified_stencil_accepts_actual_child_without_another_column(self):
        d = self._stage_decision
        full = d('terminal', full_workpoint_qualified=True, stage_only=False,
                 terminal_reason='success', next_action='complete')
        result = self._run_stage_fixture([
            d('stage_passed', next_action='stripe_preclosure'),
            d('needs_stencil', required_axes=[0]), full,
        ], stencil_gate=full)
        self.assertEqual(len(result['flights']), 1)
        state = result['bootstrap']['stage_state']
        self.assertTrue(state['anchor_manifest'].endswith('stage-stage-001/run_manifest.json')
                        or state['anchor_manifest'].endswith('stage-stage-001\\run_manifest.json'))
        self.assertEqual(state['columns'], {})
        self.assertEqual(state['attempts'], [])
        self.assertTrue(result['result']['terminal_decision']['full_workpoint_qualified'])

    def test_unqualified_or_missing_event_stencil_keeps_original_column_workflow(self):
        d = self._stage_decision
        for gate in (d('needs_stencil'), d('terminal', terminal_reason='missing_target_phase'),
                     d('terminal', terminal_reason='collision_or_invalid_topology'),
                     {'status': 'stage_passed'}):
            with self.subTest(gate=gate):
                result = self._run_stage_fixture([
                    d('stage_passed', next_action='stripe_preclosure'),
                    d('needs_stencil', required_axes=[0]),
                    d('needs_stencil', required_axes=[1]),
                    d('terminal', terminal_reason='stop_fixture'),
                ], stencil_gate=gate)
                self.assertEqual(len(result['flights']), 2)
                self.assertTrue(result['bootstrap']['stage_state']['anchor_manifest'].endswith('seed.json'))
                self.assertEqual(set(result['bootstrap']['stage_state']['columns']), {'0', '1'})


    def test_single_stripe_restore_rejects_inactive_saved_column(self):
        result = self._restore_saved_checkpoint("inactive_s2_column")
        self.assertIn("Saved stage column differs", result["failure"])
        self.assertEqual(result["flights"], [])

    def test_single_stripe_staged_probe_and_proposal_never_change_s2(self):
        def d(status, **changes):
            changes.setdefault("voltages_v", [-27., 0., 189., -190.])
            changes.setdefault("next_voltages_v", [-27., 0., 189., -190.])
            return self._stage_decision(status, **changes)
        result = self._run_stage_fixture([
            d("stage_passed", next_action="stripe_preclosure"),
            d("needs_stencil", required_axes=[0]),
            d("proposed", next_action="evaluate", next_voltages_v=[-27.2, 0., 189., -190.]),
            d("observed", next_action="evaluate", maximum_scaled_abs_residual=8.),
            d("terminal", terminal_reason="success", full_workpoint_qualified=True),
        ], active_stripe_axes=["stripe_1_voltage_v"], interrupt_after_publish=True)
        self.assertIsNone(result["failure"])
        self.assertEqual(len(result["flights"]), 2)
        self.assertTrue(all(f["Voltages"][1] == 0. for f in result["flights"]))
        self.assertTrue(all("--s2-child-manifest" not in r for r in result["requests"]))
        self.assertEqual(result["flights"][-1]["Voltages"], [-27.2, 0., 189., -190.])
        self.assertTrue(result["result"]["terminal_decision"]["full_workpoint_qualified"])

    def test_joint_probe_dispatch_transports_prism_columns_without_activating_s2(self):
        def d(status, **changes):
            changes.setdefault("voltages_v", [-27., 0., 189., -190.])
            changes.setdefault("next_voltages_v", [-27., 0., 189., -190.])
            return self._stage_decision(status, **changes)
        result = self._run_stage_fixture([
            d("stage_passed", next_action="stripe_preclosure"),
            d("needs_stencil", required_axes=[0]),
            d("needs_stencil", required_axes=[2, 3]),
            d("needs_stencil", required_axes=[3]),
            d("terminal", terminal_reason="stop_fixture"),
        ], active_stripe_axes=["stripe_1_voltage_v"],
            single_stripe_refinement_mode="joint_ps_constrained")
        self.assertIsNone(result["failure"])
        self.assertEqual(len(result["flights"]), 3)
        self.assertEqual(set(result["bootstrap"]["stage_state"]["columns"]), {"0", "2", "3"})
        self.assertTrue(all(f["Voltages"][1] == 0. for f in result["flights"]))
        self.assertIn("--p1-child-manifest", result["requests"][-1])
        self.assertIn("--p2-child-manifest", result["requests"][-1])
        self.assertTrue(all("--s2-child-manifest" not in r for r in result["requests"]))

    def test_single_stripe_blocks_inactive_probe_and_nonzero_s2_proposal(self):
        for decision, message in (
            (self._stage_decision("needs_stencil", required_axes=[1],
                                 voltages_v=[-27., 0., 189., -190.],
                                 next_voltages_v=[-27., 0., 189., -190.]), "inactive stage stencil"),
            (self._stage_decision("proposed", voltages_v=[-27., 0., 189., -190.],
                                 next_voltages_v=[-27., 0.1, 189., -190.]), "Inactive S2"),
        ):
            with self.subTest(message=message):
                result = self._run_stage_fixture([
                    self._stage_decision("stage_passed", next_action="stripe_preclosure",
                                         voltages_v=[-27., 0., 189., -190.],
                                         next_voltages_v=[-27., 0., 189., -190.]),
                    decision,
                ], active_stripe_axes=["stripe_1_voltage_v"], expected_failure=True)
                self.assertIn(message, result["failure"])
                if message == "inactive stage stencil":
                    for diagnostic in ("action=plan_staged_trial", "stage=stripe_preclosure", "exit_code=1",
                                       "workpoint_controller_state.py", "CandidateContractError"):
                        self.assertIn(diagnostic, result["failure"])
                self.assertEqual(result["flights"], [])

    def test_stage_passed_prism_uses_same_anchor_stripe_columns_and_reverse(self):
        d = self._stage_decision
        result = self._run_stage_fixture([
            d("stage_passed", next_action="stripe_preclosure"),
            d("needs_stencil", required_axes=[0]),
            d("needs_stencil", required_axes=[1]),
            d("needs_stencil", required_axes=[1]),
            d("terminal", terminal_reason="stage_model_unavailable"),
        ])
        flights, requests = result["flights"], result["requests"]
        self.assertEqual(len(flights), 3)
        for flight in flights:
            self.assertEqual(flight["Voltages"][2:], [189., -190.])
        self.assertAlmostEqual(flights[0]["Voltages"][0], -26.73)
        self.assertAlmostEqual(flights[1]["Voltages"][1], 54.54)
        self.assertAlmostEqual(flights[2]["Voltages"][1], 53.46)
        self.assertEqual({r["--child-manifest"] for r in requests},
                         {requests[0]["--child-manifest"]})
        self.assertEqual(requests[2]["--s1-child-manifest"], requests[3]["--s1-child-manifest"])
        self.assertEqual(requests[3]["--s1-child-manifest"], requests[4]["--s1-child-manifest"])
        self.assertNotEqual(requests[3]["--s2-child-manifest"], requests[4]["--s2-child-manifest"])
        self.assertTrue(all("--p1-child-manifest" not in r and
                            "--p2-child-manifest" not in r for r in requests))
        self.assertFalse(result["result"]["terminal_decision"]["full_workpoint_qualified"])

    def test_stage_worse_candidate_damps_without_discarding_best_anchor(self):
        d = self._stage_decision
        proposal = d("proposed", next_action="evaluate", next_voltages_v=[-28., 56., 189., -190.])
        result = self._run_stage_fixture([
            d("stage_passed", next_action="stripe_preclosure"), proposal,
            d("observed", next_action="stripe_preclosure", maximum_scaled_abs_residual=11.), proposal,
            d("observed", next_action="evaluate", maximum_scaled_abs_residual=8.),
            d("terminal", terminal_reason="success", full_workpoint_qualified=True),
        ])
        self.assertEqual([f["Voltages"] for f in result["flights"]],
                         [[-28., 56., 189., -190.], [-27.5, 55., 189., -190.]])
        requests = result["requests"]
        self.assertEqual(requests[1]["--child-manifest"], requests[3]["--child-manifest"])
        self.assertTrue(requests[5]["--child-manifest"].replace("\\", "/").endswith("stage-stage-002/run_manifest.json"))
        self.assertTrue(all(r["--prism-handoff-replay-manifest"] == "measured-P-replay.json"
                            for r in requests))
        self.assertEqual(result["saves"][-1]["stage_state"]["anchor_manifest"],
                         requests[5]["--child-manifest"])
        self.assertTrue(result["result"]["terminal_decision"]["full_workpoint_qualified"])

    def test_explicit_sealed_prism_model_is_consumed_before_any_new_column(self):
        d = self._stage_decision
        proposed = d("proposed", next_action="run_P_candidate",
                     next_voltages_v=[-27., 54., 188.8, -190.1],
                     model_representation="transported_local_approximation")
        result = self._run_stage_fixture([
            proposed, d("needs_stencil", maximum_scaled_abs_residual=8.),
            d("terminal", terminal_reason="finite_P_test"),
        ], initial_model="original-sealed-P/run_manifest.json")
        self.assertEqual(len(result["flights"]), 1)
        self.assertEqual(result["models"], [])
        self.assertEqual(result["requests"][0]["--prior-prism-decision-manifest"],
                         "original-sealed-P/run_manifest.json")
        self.assertNotIn("--prism1-manifest", result["requests"][0])
        self.assertNotIn("--prism2-manifest", result["requests"][0])
        self.assertEqual(result["bootstrap"]["stage_state"]["prism_model_manifest"],
                         "original-sealed-P/run_manifest.json")
        source = (PROJECT / "analysis/run_downstream_workpoint_iteration.ps1").read_text(encoding="utf-8")
        self.assertIn("[string]$PriorPrismDecisionManifest = ''", source)
        self.assertIn("Split-Path -Parent $PriorPrismDecisionManifest", source)
        self.assertIn("configuration.inputs.prior_prism_decision_manifest=$frozenPrismModel", source)

    def test_prism_measured_model_survives_improving_candidates_without_new_columns(self):
        d = self._stage_decision
        measured = d("proposed", next_action="run_P_candidate",
                     next_voltages_v=[-27., 54., 188.8, -190.1],
                     physical_jacobian_rows=[[1., 0.], [0., 1.]],
                     finite_difference_steps_v=[1.89, 1.90])
        transported = d("proposed", next_action="run_P_candidate",
                        voltages_v=measured["next_voltages_v"],
                        next_voltages_v=[-27., 54., 188.6, -190.2],
                        maximum_scaled_abs_residual=8.,
                        model_representation="transported_local_approximation",
                        physical_jacobian_rows=[[1., 0.], [0., 1.]])
        result = self._run_stage_fixture([
            d("needs_stencil", required_axes=[2]),
            d("needs_stencil", required_axes=[3]), measured,
            d("needs_stencil", maximum_scaled_abs_residual=8.), transported,
            d("needs_stencil", maximum_scaled_abs_residual=6.),
            d("stage_passed", next_action="stripe_preclosure"),
            d("terminal", terminal_reason="S_unavailable"),
        ])
        self.assertEqual(len(result["flights"]), 4)  # Two original columns, two corrections.
        self.assertEqual(len(result["models"]), 1)
        self.assertEqual(result["models"][0]["decision"], measured)
        self.assertEqual(set(result["models"][0]["columns"]), {"2", "3"})
        reused = [r for r in result["requests"] if "--prior-prism-decision-manifest" in r]
        self.assertEqual(len(reused), 2)
        self.assertEqual(reused[0]["--prior-prism-decision-manifest"],
                         reused[1]["--prior-prism-decision-manifest"])
        self.assertTrue(all("--p1-child-manifest" not in r and "--p2-child-manifest" not in r
                            for r in reused))
        self.assertNotIn("--prior-prism-decision-manifest", result["requests"][-1])
        self.assertNotIn("prism_model_manifest", result["bootstrap"]["stage_state"])

    def test_prism_model_rejection_compares_last_accepted_point_not_original_anchor(self):
        d = self._stage_decision
        state = {"stage": "prism_preclosure", "anchor_manifest": "seed", "columns": {},
                 "attempts": [], "flight_count": 4, "candidate_count": 2, "step_factor": 1.,
                 "completion_attempted": False, "prism_model_manifest": "original-P-model.json"}
        proposal = d("proposed", next_action="run_P_candidate", maximum_scaled_abs_residual=6.,
                     next_voltages_v=[-27., 54., 188.8, -190.1],
                     model_representation="transported_local_approximation")
        result = self._run_stage_fixture([
            proposal, d("needs_stencil", maximum_scaled_abs_residual=6.5),
            proposal, d("needs_stencil", maximum_scaled_abs_residual=5.),
            d("terminal", terminal_reason="fixture_stop"),
        ], state)
        self.assertEqual(len(result["models"]), 0)
        self.assertEqual(len(result["flights"]), 2)
        self.assertEqual(result["flights"][1]["Voltages"], [-27., 54., 188.9, -190.05])
        self.assertEqual(result["requests"][0]["--child-manifest"],
                         result["requests"][2]["--child-manifest"])
        self.assertEqual(result["bootstrap"]["stage_state"]["prism_model_manifest"],
                         "original-P-model.json")

    def test_prism_extent_refresh_drops_old_model_and_measures_at_current_anchor(self):
        d = self._stage_decision
        state = {"stage": "prism_preclosure", "anchor_manifest": "seed", "columns": {},
                 "attempts": [], "flight_count": 4, "candidate_count": 2, "step_factor": 1.,
                 "completion_attempted": False, "prism_model_manifest": "original-P-model.json"}
        result = self._run_stage_fixture([
            d("needs_stencil", required_axes=[2], model_refresh_reason="outside_measured_P_extent"),
            d("terminal", terminal_reason="fixture_stop"),
        ], state)
        self.assertEqual(len(result["flights"]), 1)
        self.assertIn("--prior-prism-decision-manifest", result["requests"][0])
        self.assertNotIn("--prior-prism-decision-manifest", result["requests"][1])
        self.assertNotIn("prism_model_manifest", result["bootstrap"]["stage_state"])
        self.assertIn("--p1-child-manifest", result["requests"][1])

    def test_prism_pending_child_resume_keeps_original_model_without_reflying(self):
        d = self._stage_decision
        state = {"stage": "prism_preclosure", "anchor_manifest": "seed", "columns": {},
                 "attempts": [], "flight_count": 4, "candidate_count": 2, "step_factor": 1.,
                 "completion_attempted": False, "prism_model_manifest": "original-P-model.json"}
        result = self._run_stage_fixture([
            d("proposed", next_action="run_P_candidate", next_voltages_v=[-27., 54., 188.8, -190.1],
              model_representation="transported_local_approximation"),
            d("needs_stencil", maximum_scaled_abs_residual=8.),
            d("terminal", terminal_reason="fixture_stop"),
        ], state, interrupt_after_publish=True)
        self.assertEqual(len(result["flights"]), 1)
        self.assertEqual(result["models"], [])
        self.assertEqual(result["bootstrap"]["stage_state"]["prism_model_manifest"],
                         "original-P-model.json")
        self.assertEqual(result["result"]["lineage"]["children"][0]["prism_model_manifest"],
                         "original-P-model.json")


    def test_prism_reuse_still_obeys_parent_iteration_budget(self):
        d = self._stage_decision
        state = {"stage": "prism_preclosure", "anchor_manifest": "seed", "columns": {},
                 "attempts": [], "flight_count": 10, "candidate_count": 8, "step_factor": 1.,
                 "completion_attempted": False, "prism_model_manifest": "original-P-model.json"}
        result = self._run_stage_fixture([
            d("proposed", next_action="run_P_candidate", next_voltages_v=[-27., 54., 188.8, -190.1],
              model_representation="transported_local_approximation"),
        ], state)
        self.assertEqual(result["flights"], [])
        self.assertEqual(result["result"]["terminal_decision"]["terminal_reason"], "maximum_iterations")

    def test_terminal_s_candidate_p_metric_damps_and_keeps_anchor_and_columns(self):
        d = self._stage_decision
        state = {"stage": "stripe_preclosure", "anchor_manifest": "seed",
                 "columns": {"0": "prior-s1.json", "1": "prior-s2.json"},
                 "attempts": [], "flight_count": 2, "candidate_count": 0,
                 "step_factor": 1., "completion_attempted": False}
        proposal = d("proposed", next_action="run_S_candidate",
                     maximum_scaled_abs_residual=58.05763812,
                     next_voltages_v=[-28., 56., 189., -190.])
        result = self._run_stage_fixture([
            proposal,
            d("terminal", next_action="stop_preclosure",
              terminal_reason="collision_or_invalid_topology",
              maximum_scaled_abs_residual=.917449559),
            proposal,
            d("needs_stencil", maximum_scaled_abs_residual=40.),
            d("terminal", terminal_reason="success", full_workpoint_qualified=True),
        ], state)
        self.assertEqual([f["Voltages"] for f in result["flights"]],
                         [[-28., 56., 189., -190.], [-27.5, 55., 189., -190.]])
        first, retried = result["requests"][0], result["requests"][2]
        for field in ("--child-manifest", "--s1-child-manifest", "--s2-child-manifest"):
            self.assertEqual(first[field], retried[field])
        rejected_state = next(s["stage_state"] for s in result["saves"]
                              if s["stage_state"]["step_factor"] == .5)
        self.assertEqual(rejected_state["anchor_manifest"], first["--child-manifest"])
        self.assertEqual(len(rejected_state["columns"]), 2)
        self.assertTrue(result["requests"][-1]["--child-manifest"].replace("\\", "/").endswith(
            "stage-stage-004/run_manifest.json"))
        self.assertTrue(result["result"]["terminal_decision"]["full_workpoint_qualified"])













    def test_terminal_source_is_allowed_only_for_static_fresh_stage_replay(self):
        script = r"""
param($Source)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$assignment=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$replayTerminalStages'-and$n.Right.Extent.Text-like'*resumeStatus*'},$true)
$guard=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and$n.Extent.Text-like"if(`$resumeStatus-ne'checkpoint'-and-not`$replayTerminalStages)*"},$true)
foreach($stagedBootstrap in $false,$true){foreach($resumeStatus in 'checkpoint','success','failed','interrupted'){
 $rejected=$false
 try{Invoke-Expression $assignment.Extent.Text;Invoke-Expression $guard.Extent.Text}catch{$rejected=$true}
 if($rejected-ne(-not$stagedBootstrap-and$resumeStatus-ne'checkpoint')){throw 'Terminal resume boundary differs'}
}}
'TERMINAL_RESUME_BOUNDARY=PASS'
"""
        with TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "terminal-resume.ps1"
            fixture.write_text(script, encoding="utf-8")
            result = subprocess.run([
                "pwsh", "-NoProfile", "-File", str(fixture),
                str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"),
            ], cwd=PROJECT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("TERMINAL_RESUME_BOUNDARY=PASS", result.stdout)

    def test_s_model_refresh_measures_medium_columns_and_keeps_tier_after_acceptance(self):
        d = self._stage_decision
        state = {"stage": "stripe_preclosure", "anchor_manifest": "seed",
                 "columns": {"0": "prior-s1.json", "1": "prior-s2.json"}, "attempts": [],
                 "flight_count": 5, "candidate_count": 3, "step_factor": .125,
                 "local_model_tier_index": 0, "consecutive_candidate_rejections": 3,
                 "completion_attempted": False}
        result = self._run_stage_fixture([
            d("needs_stencil", required_axes=[0]), d("needs_stencil", required_axes=[1]),
            d("proposed", next_action="run_S_candidate", next_voltages_v=[-28., 56., 189., -190.]),
            d("needs_stencil", maximum_scaled_abs_residual=8.),
            d("terminal", terminal_reason="success", full_workpoint_qualified=True),
        ], state)
        flights = result["flights"]
        self.assertEqual(len(flights), 3)
        self.assertAlmostEqual(flights[0]["Voltages"][0], -27. + .0025 * 27.)
        self.assertAlmostEqual(flights[1]["Voltages"][1], 54. + .0025 * 54.)
        self.assertEqual(flights[2]["Voltages"], [-28., 56., 189., -190.])
        final = result["bootstrap"]["stage_state"]
        self.assertEqual((final["local_model_tier_index"], final["step_factor"],
                          final["consecutive_candidate_rejections"]), (1, 1., 0))
        refresh = result["bootstrap"]["stage_history"]["decisions"][0]
        self.assertEqual(refresh["status"], "local_model_refresh")
        self.assertEqual(len(refresh["previous_columns"]), 2)
        self.assertEqual([a for a in result["controller_actions"] if a["action"] == "plan_staged_trial"],
                         [dict(action="plan_staged_trial", phase="prepare")] +
                         [dict(action="plan_staged_trial", phase=None)] * 3)
        self.assertNotIn("voltage_stencil_steps", [a["action"] for a in result["controller_actions"]])
        reset_checkpoint = result["saves"][0]["stage_state"]
        self.assertEqual((reset_checkpoint["flight_count"], reset_checkpoint["candidate_count"]), (5, 3))
        self.assertEqual(reset_checkpoint["columns"], {})

    def test_explicit_stripe_columns_rejoin_seed_without_column_flights(self):
        d = self._stage_decision
        proposal = d("proposed", next_action="run_S_candidate", next_voltages_v=[-27.01, 54.05, 189., -190.])
        result = self._run_stage_fixture([
            d("stage_passed", next_action="stripe_preclosure"),
            d("needs_stencil", required_axes=[0, 1]), proposal, proposal,
            d("observed", next_action="evaluate", maximum_scaled_abs_residual=8.),
            d("terminal", terminal_reason="fixture_stop"),
        ], imported_columns={"0": [-26.9325, 54., 189., -190.],
                             "1": [-27., 54.135, 189., -190.]})
        self.assertIsNone(result["failure"])
        self.assertEqual([f["Voltages"] for f in result["flights"]], [[-27.01, 54.05, 189., -190.]])
        self.assertEqual(len(result["bootstrap"]["stage_lineage"]["children"]), 3)
        self.assertEqual(result["bootstrap"]["stage_state"]["candidate_count"], 1)
        self.assertTrue(result["requests"][3]["--s1-child-manifest"].endswith("run_manifest.json"))
        self.assertIn("--s2-child-manifest", result["requests"][3])
        self.assertEqual(sum(a["action"] == "prepare_imported_stencil_column" for a in result["controller_actions"]), 2)

    def test_explicit_single_stripe_column_measures_only_missing_axis(self):
        d = self._stage_decision
        result = self._run_stage_fixture([
            d("stage_passed", next_action="stripe_preclosure"),
            d("needs_stencil", required_axes=[0, 1]),
            d("needs_stencil", required_axes=[1], maximum_scaled_abs_residual=3.),
            d("needs_stencil", required_axes=[1], maximum_scaled_abs_residual=3.),
            d("terminal", terminal_reason="fixture_stop"),
        ], imported_columns={"0": [-26.9325, 54., 189., -190.]})
        self.assertIsNone(result["failure"])
        self.assertEqual(len(result["flights"]), 1)
        self.assertEqual(result["flights"][0]["Voltages"], [-27., 54.135, 189., -190.])
        self.assertEqual(sum(a["action"] == "prepare_imported_stencil_column" for a in result["controller_actions"]), 1)


    def test_explicit_stripe_column_controller_rejections_prevent_any_flight(self):
        d = self._stage_decision
        for reason in ("different anchor", "different local phase/direction", "P not qualified"):
            with self.subTest(reason=reason):
                result = self._run_stage_fixture([
                    d("stage_passed", next_action="stripe_preclosure"),
                    d("needs_stencil", required_axes=[0, 1]),
                    d("needs_stencil", required_axes=[0, 1], stencil_rejections={"0": reason}),
                ], imported_columns={"0": [-26.9325, 54., 189., -190.]})
                self.assertIn("was not accepted", result["failure"])
                self.assertEqual(result["flights"], [])
                self.assertFalse(any(a["action"] == "prepare_imported_stencil_column" for a in result["controller_actions"]))

    def test_explicit_stripe_wrong_axis_and_duplicate_point_prevent_any_flight(self):
        d = self._stage_decision
        for columns in ({"0": [-27., 54.135, 189., -190.]},
                        {"0": [-26.9325, 54., 189., -190.], "1": [-26.9325, 54., 189., -190.]}):
            with self.subTest(columns=columns):
                result = self._run_stage_fixture([
                    d("stage_passed", next_action="stripe_preclosure"),
                    d("needs_stencil", required_axes=[0, 1]),
                    d("proposed", next_action="run_S_candidate"),
                ], imported_columns=columns)
                self.assertIn("only its declared seed axis", result["failure"])
                self.assertEqual(result["flights"], [])
                imported = len(columns) - 1
                self.assertEqual(result["bootstrap"]["stage_state"]["flight_count"], imported)
                self.assertEqual(len(result["bootstrap"]["stage_lineage"]["children"]), imported)
                self.assertEqual(sum(a["action"] == "prepare_imported_stencil_column" for a in result["controller_actions"]), imported)

    def test_staged_stencil_starts_at_contract_residual_tier(self):
        d = self._stage_decision
        for residual, relative in ((11., .01), (3., .0025), (1.5, .0005)):
            with self.subTest(residual=residual):
                result = self._run_stage_fixture([
                    d("stage_passed", next_action="stripe_preclosure"),
                    d("needs_stencil", required_axes=[0], maximum_scaled_abs_residual=residual),
                    d("terminal", terminal_reason="fixture_stop"),
                ])
                self.assertAlmostEqual(result["flights"][0]["Voltages"][0], -27. + relative * 27.)

    def test_rejected_stencil_finer_tier_does_not_rescale_candidate(self):
        d = self._stage_decision
        result = self._run_stage_fixture([
            d("stage_passed", next_action="stripe_preclosure"),
            d("needs_stencil", required_axes=[0]),
            d("needs_stencil", required_axes=[0]),
            d("needs_stencil", required_axes=[0]),
            d("proposed", next_action="run_S_candidate", next_voltages_v=[-27.02, 54.04, 189., -190.]),
            d("observed", next_action="evaluate", maximum_scaled_abs_residual=8.),
            d("terminal", terminal_reason="fixture_stop"),
        ])
        self.assertAlmostEqual(result["flights"][2]["Voltages"][0], -26.9325)
        self.assertEqual(result["flights"][3]["Voltages"], [-27.02, 54.04, 189., -190.])
        self.assertEqual(result["bootstrap"]["stage_state"]["local_model_tier_index"], 1)



    def test_finest_s_model_rejections_end_without_another_flight(self):
        state = {"stage": "stripe_preclosure", "anchor_manifest": "seed", "columns": {}, "attempts": [],
                 "flight_count": 12, "candidate_count": 9, "step_factor": .00625,
                 "local_model_tier_index": 2, "consecutive_candidate_rejections": 3,
                 "completion_attempted": False}
        result = self._run_stage_fixture([], state)
        self.assertEqual(result["flights"], [])
        self.assertEqual(result["result"]["terminal_decision"]["terminal_reason"], "model_recovery_exhausted")

    def test_stage_checkpoint_reuses_qualified_column_without_reflying_anchor(self):
        d = self._stage_decision
        state = {"stage": "stripe_preclosure", "anchor_manifest": "seed", "columns": {"0": "prior-s1.json"},
                 "attempts": [{"axis": 0, "signed_step_v": .27}], "flight_count": 1,
                 "candidate_count": 0, "step_factor": 1., "completion_attempted": False}
        result = self._run_stage_fixture([
            d("needs_stencil", required_axes=[1]),
            d("terminal", terminal_reason="stage_model_unavailable"),
        ], state)
        self.assertEqual(len(result["flights"]), 1)
        self.assertEqual(result["flights"][0]["ChildRunId"], "stage-stage-002")
        self.assertEqual(result["requests"][0]["--s1-child-manifest"],
                         result["requests"][1]["--s1-child-manifest"])
        self.assertEqual(result["bootstrap"]["stage_state"]["flight_count"], 2)

    def test_stage_completion_requires_full_qualification_and_is_not_repeated(self):
        d = self._stage_decision
        for qualified in (False, True):
            with self.subTest(qualified=qualified):
                decisions = [d("stage_passed", next_action="complete_N1"),
                             d("observed", next_action="complete_N1")]
                decisions.append(d("terminal", terminal_reason="success", full_workpoint_qualified=True)
                                 if qualified else d("stage_passed", next_action="complete_N1"))
                result = self._run_stage_fixture(decisions)
                self.assertEqual(len(result["flights"]), 1)
                terminal = result["result"]["terminal_decision"]
                self.assertEqual(terminal["full_workpoint_qualified"], qualified)
                self.assertEqual(terminal["terminal_reason"], "success" if qualified else "missing_target_phase")

    def test_stage_published_child_replays_checkpoint_without_another_flight(self):
        d = self._stage_decision
        result = self._run_stage_fixture([
            d("stage_passed", next_action="stripe_preclosure"),
            d("needs_stencil", required_axes=[0]),
            d("terminal", terminal_reason="stage_model_unavailable"),
        ], interrupt_after_publish=True)
        self.assertEqual(len(result["flights"]), 1)
        self.assertEqual(len(result["result"]["lineage"]["children"]), 1)
        self.assertTrue(result["requests"][-1]["--s1-child-manifest"].replace("\\", "/").endswith(
            "stage-stage-001/run_manifest.json"))
        pending = [s["stage_state"]["pending_trial"] for s in result["saves"]
                   if "pending_trial" in s["stage_state"]]
        self.assertEqual(pending[0]["voltages_v"], result["flights"][0]["Voltages"])
        self.assertNotIn("pending_trial", result["bootstrap"]["stage_state"])

    def test_restored_unexecuted_stencil_is_replaced_only_by_verified_replay_column(self):
        d = self._stage_decision
        state = {"stage": "stripe_preclosure", "anchor_manifest": "seed", "columns": {"0": "prior-s1.json"},
                 "attempts": [], "flight_count": 2, "candidate_count": 0, "step_factor": 1.,
                 "completion_attempted": False, "pending_trial": {
                     "child_run_id": "old-stage-002", "child_manifest": "unexecuted-old.json",
                     "anchor_manifest": "seed", "stage": "stripe_preclosure",
                     "voltages_v": [-27.27, 54., 189., -190.],
                     "decision": d("needs_stencil", required_axes=[0]),
                     "selected": {"axis": 0, "signed_step_v": -.27}}}
        result = self._run_stage_fixture([
            d("needs_stencil", required_axes=[1], replayed_stage_axes=[0]),
            d("needs_stencil", required_axes=[1]), d("terminal", terminal_reason="stop")], state)
        self.assertEqual(len(result["flights"]), 1)
        self.assertEqual(result["flights"][0]["Voltages"], [-27., 54.54, 189., -190.])
        self.assertEqual(result["bootstrap"]["stage_state"]["flight_count"], 3)
        self.assertEqual(result["result"]["history"]["decisions"][0]["status"], "pending_plan_not_executed")
        for replay, registered, required in (("", True, False), ("measured-P-replay.json", False, False),
                                              ("measured-P-replay.json", True, True)):
            with self.subTest(replay=replay, registered=registered, required=required):
                decisions = [] if not replay else [d("needs_stencil", required_axes=[0] if required else [1],
                    replayed_stage_axes=[0] if registered else [])]
                decisions.append(d("terminal", terminal_reason="stop"))
                kept = self._run_stage_fixture(decisions, state, replay_manifest=replay)
                self.assertEqual(kept["flights"][0]["Voltages"], [-27.27, 54., 189., -190.])
                self.assertNotIn("pending_plan_not_executed", [r["status"] for r in kept["result"]["history"]["decisions"]])

    def test_restored_stencil_is_retired_when_replay_completes_both_columns(self):
        d = self._stage_decision
        state = {"stage": "stripe_preclosure", "anchor_manifest": "seed",
                 "columns": {"0": "prior-s1.json", "1": "prior-s2.json"},
                 "attempts": [], "flight_count": 4, "candidate_count": 0,
                 "step_factor": 1., "completion_attempted": False,
                 "pending_trial": {"child_run_id": "old-stage-004",
                     "child_manifest": "interrupted-old.json", "anchor_manifest": "seed",
                     "stage": "stripe_preclosure", "voltages_v": [-27., 53.46, 189., -190.],
                     "decision": d("needs_stencil", required_axes=[1]),
                     "selected": {"axis": 1, "signed_step_v": -.54}}}
        proposal = d("proposed", next_action="evaluate", replayed_stage_axes=[0, 1],
                     next_voltages_v=[-26.8, 54.5, 189., -190.])
        proposal.pop("required_axes")
        result = self._run_stage_fixture([proposal, proposal,
            d("observed", next_action="evaluate", maximum_scaled_abs_residual=8.),
            d("terminal", terminal_reason="stop")], state)
        self.assertEqual([f["Voltages"] for f in result["flights"]],
                         [[-26.8, 54.5, 189., -190.]])
        self.assertEqual(result["result"]["history"]["decisions"][0]["status"],
                         "pending_plan_not_executed")
        self.assertEqual(result["result"]["history"]["decisions"][0]["required_axes"], [])

    def test_stage_child_with_wrong_actual_voltage_is_not_adopted(self):
        d = self._stage_decision
        result = self._run_stage_fixture([
            d("stage_passed", next_action="stripe_preclosure"),
            d("needs_stencil", required_axes=[0]),
        ], corrupt_voltage=True)
        self.assertEqual(result["failure"], "Pending stage child voltages differ from the persisted trial.")
        self.assertEqual(result["bootstrap"]["stage_state"]["columns"], {})
        self.assertIn("pending_trial", result["saves"][-1]["stage_state"])

    def test_read_only_runtime_asset_survives_successful_owner_terminalization(self):
        source = (PROJECT / "analysis/run_downstream_workpoint_iteration.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("$runtimeOwnerStatus-notin@('checkpoint','success')", source)
        self.assertIn("--require-status $runtimeOwnerStatus", source)
        self.assertIn("if($runtimeOwnerRun-and$runtimeOwnerStatus-ne'success')", source)
        self.assertIn("if($ownerStatus-notin@('checkpoint','success'))", source)
        self.assertIn("-FinalDecision $caughtDecision", source)
        self.assertNotIn("Native runtime owner is already terminal.", source)

    def test_fresh_chain_derives_grouped_candidate_without_replaying_baseline(self):
        script = r"""
param($Source,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'New-InitialGroupedWorkpointDecision'},$true)
Invoke-Expression $node.Extent.Text
$repoRoot=$Root;$python='Invoke-MockController'
function Invoke-RunToolRootContext {param($RepoRoot,[scriptblock]$Operation)& $Operation}
function Get-ManifestOutputPath {
  param($ManifestPath,$FileName)
  return Join-Path $Root $FileName
}
function Invoke-MockController {
  param([Parameter(ValueFromRemainingArguments=$true)][object[]]$CommandArgs)
  $outputIndex=[array]::IndexOf($CommandArgs,'--output')
  if($outputIndex-lt0){throw 'controller output missing'}
  $decision=@{
    schema_version=1;role='mrtof_downstream_workpoint_iteration_decision';state='continue'
    terminal_reason=$null;iteration=1;coordinate_group='prism_1_prism_2'
    proposed_voltages_v=@(-25.,50.,201.,-202.)
  }
  $decision|ConvertTo-Json -Depth 10|Set-Content -LiteralPath ([string]$CommandArgs[$outputIndex+1])
  Write-Output 'MOCK_CONTROLLER=PASS'
  $global:LASTEXITCODE=0
}
$baselineManifest=Join-Path $Root 'baseline-run-manifest.json';'{}'|Set-Content $baselineManifest
'{}'|Set-Content (Join-Path $Root 'two_prism_trial_observation.json')
@{stripe_biases_v=@(-25.,50.);prism_voltages_v=@(200.,-200.)}|ConvertTo-Json|Set-Content (Join-Path $Root 'two_prism_trial_materialization.json')
$history=Join-Path $Root 'history.json';@{decisions=@()}|ConvertTo-Json|Set-Content $history
$proposalPath=Join-Path $Root 'proposal.json'
$proposal=@{baseline_manifest=$baselineManifest;proposed_voltages_v=@(-24.,51.,205.,-205.)}
$proposal|ConvertTo-Json|Set-Content $proposalPath
$result=New-InitialGroupedWorkpointDecision -Proposal $proposal -ProposalPath $proposalPath `
  -ContractPath (Join-Path $Root 'contract.json') -HistoryPath $history -OutputPath (Join-Path $Root 'initial.json')
if($result.coordinate_group-ne'prism_1_prism_2'){throw 'initial decision did not preserve P-first grouping'}
if($result.proposed_voltages_v[0]-ne-25-or$result.proposed_voltages_v[1]-ne50){throw 'initial decision changed Stripe voltages'}
if($result.proposed_voltages_v[2]-eq200-and$result.proposed_voltages_v[3]-eq-200){throw 'initial decision replayed the baseline'}
if(@((Get-Content $history -Raw|ConvertFrom-Json).decisions).Count-ne0){throw 'bootstrap decision polluted iteration history'}
'INITIAL_GROUPED_DECISION=PASS'
"""
        source = PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"
        runner_source = source.read_text(encoding="utf-8-sig")
        self.assertIn("if (-not $resumeIterationCheckpoint) {", runner_source)
        self.assertIn(
            "$current = @($initialGroupedDecision.proposed_voltages_v",
            runner_source,
        )
        with TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "initial-grouped-decision.ps1"
            fixture.write_text(script, encoding="utf-8")
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(fixture), str(source), temporary],
                cwd=PROJECT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=40,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("INITIAL_GROUPED_DECISION=PASS", result.stdout)

    def test_terminal_mirror_variation_is_forwarded_to_every_center_trial(self):
        source = (PROJECT / "analysis/run_downstream_workpoint_iteration.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("[string]$MirrorVoltageVariationPath = ''", source)
        self.assertIn("$arguments.MirrorVoltageVariationPath = $variationVariable.Value", source)
        self.assertIn("terminal_time_mirror_voltage_variation.json", source)

    def test_bootstrap_checkpoint_without_iteration_lineage_resumes_stencil(self):
        source = (PROJECT / "analysis/run_downstream_workpoint_iteration.ps1").read_text(
            encoding="utf-8-sig"
        )
        self.assertEqual(
            source.count("$auditRunner = Join-Path $PSScriptRoot 'run_downstream_fixed_grid_workpoint.ps1'"),
            1,
        )
        self.assertIn(
            "$resumeIterationCheckpoint=[bool]($ResumeParentCheckpoint-and-not$freshBootstrap)",
            source,
        )
        self.assertIn("$resumeLineageOutputs.Count-eq0", source)
        self.assertIn(
            "$InitialWorkpointManifest=Invoke-WorkpointStencil -Bootstrap $bootstrap",
            source,
        )
        self.assertIn("$resumeIterationCheckpoint=$true", source)
        self.assertIn(
            "$configuration.inputs.resume_parent_checkpoint=$frozenResumeParentManifest",
            source,
        )

    def test_continuation_transport_seed_uses_contract_neighborhood(self):
        script = r"""
param($Source,$Root,$FixturePython)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
foreach($name in @('Find-ContinuationTransportSeed','Invoke-CenterTrial','Invoke-WorkpointControllerRequest')){
  $node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true);Invoke-Expression $node.Extent.Text
}
$staticFieldMode=$false;$stagedBootstrap=$false
$repoRoot=(Get-Item $Source).Directory.Parent.Parent.Parent.FullName
$python=$FixturePython
$RunId='auto';$RetainBaselineGuiWorkbench=$false;$artifactRoot=$Root;$script:flights=@()
$trialArtifactRoot=$artifactRoot
function New-CenterTrialArguments {param($PrismVoltages,$ChildRunId)@{PrismVoltages=$PrismVoltages;ChildRunId=$ChildRunId}}
function Invoke-MockTrial {param($PrismVoltages,$ChildRunId)$script:flights+=,@($PrismVoltages);$d=Join-Path $artifactRoot ('runs/'+$ChildRunId);New-Item -ItemType Directory -Path $d -Force|Out-Null;@{stripe_biases_v=@(-25.,50.);prism_voltages_v=@($PrismVoltages)}|ConvertTo-Json|Set-Content (Join-Path $d 'm.json')}
function Get-ManifestOutputPath {param($ManifestPath,$FileName)Join-Path (Split-Path $ManifestPath) 'm.json'}
function Get-WorkpointBootstrapEvidence {param($Manifest,$Voltages)@{passed=([math]::Abs($Voltages[2]-221.253125)-lt1e-9);reasons=@('incomplete')}}
$trialRunner='Invoke-MockTrial';$seed=[pscustomobject]@{prism_voltages_v=@(219.0625,-173.75);prism_voltage_bounds_v=@(@(120.,280.),@(-200.,400.))};$profile=[pscustomobject]@{jacobian_relative_step_tiers=[pscustomobject]@{coarse=.01;medium=.0025;fine=.0005}}
$result=Find-ContinuationTransportSeed $seed $profile
if($script:flights.Count-ne2-or$result.attempts.Count-ne2-or[math]::Abs($script:flights[1][0]-221.253125)-gt1e-9){throw 'wrong bounded search'}
if($result.voltages_v[0]-ne-25-or$result.voltages_v[1]-ne50){throw 'stripe authority lost'}
function Get-WorkpointBootstrapEvidence {param($Manifest,$Voltages)@{passed=$false;reasons=@('reference')}}
$script:flights=@();$stagedBootstrap=$true
$result=Find-ContinuationTransportSeed $seed $profile
if($script:flights.Count-ne1-or$result.attempts[0].passed){throw 'Staged bootstrap no longer returns its rejected baseline'}
$script:flights=@();$stagedBootstrap=$false;$failure=$null
try{$null=Find-ContinuationTransportSeed $seed $profile}catch{$failure=$_.Exception.Message}
if($script:flights.Count-ne13-or$failure-notlike'No physical transport seed*'){throw 'Exhausted transport changed its dispatch trace'}
'CONTINUATION_TRANSPORT_SEED=PASS'
"""
        with TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "continuation-seed.ps1"
            fixture.write_text(script, encoding="utf-8")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(fixture), str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"), temporary, sys.executable], cwd=PROJECT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("CONTINUATION_TRANSPORT_SEED=PASS", result.stdout)

    def test_continuation_entry_delegates_stripe_authority(self):
        source = (PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('$continuation=$summary.continuation', source)
        self.assertIn('New-CenterTrialArguments -PrismVoltages $prisms', source)
        self.assertNotIn('221.253125', source)

    def test_continuation_pair_identity_binds_contract_stripe_k_and_y(self):
        script = r"""
param($Source,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
foreach($name in @('Resolve-RunRecordPath','Assert-ContinuationPairIdentity')){
  $node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)
  Invoke-Expression $node.Extent.Text
}
$project='parallel_mirror_dual_stripe_mr_tof'
function Write-Json($Path,$Value){$Value|ConvertTo-Json -Depth 20|Set-Content -LiteralPath $Path}
$stripeDir=Join-Path $Root 'stripe';New-Item -ItemType Directory -Path $stripeDir|Out-Null
$stripeManifest=Join-Path $stripeDir 'run_manifest.json'
Write-Json $stripeManifest @{schema_version=2;run_id='stripe-k24p5';status='success';project=$project;mode='dual_stripe_fixed_grid_native_downstream_seed'}
$frozenStripeManifest=Join-Path $Root 'frozen-stripe.json'
Write-Json $frozenStripeManifest @{schema_version=2;run_id='stripe-k24p5';status='success';project=$project;mode='dual_stripe_fixed_grid_native_downstream_seed'}
$contract=Join-Path $Root 'contract.json'
Write-Json $contract @{nominal=@{target_drift_period_ratio=24.5};accelerator=@{focus_y_anchor=@{project_y_mm=-45.0}}}
$coverage=Join-Path $Root 'coverage.json'
Write-Json $coverage @{schema_version=2;run_id='coverage-k24p5-yminus45';status='success';project=$project;mode='two_prism_segmented_voltage_branch_coverage'}
$continuationSummary=Join-Path $Root 'summary.json'
Write-Json $continuationSummary @{inputs=@{
  accelerator_exit_source_receipt=@{pair_identity=@{target_drift_period_ratio=24.5;accelerator_y_anchor_mm=-45.0}}
  stripe_seed=@{source_stripe_run_id='stripe-k24p5'}
}}
$continuation=Join-Path $Root 'continuation.json'
Write-Json $continuation @{outputs=@(@{path=$continuationSummary});inputs=@{
  parent_coverage_run_manifest=@{path=$coverage}
  downstream_contract=@{path=$contract}
  parent_fixed_mirror_stripe_run_manifest=@{path=$frozenStripeManifest}
}}
$result=Assert-ContinuationPairIdentity $continuation $contract $stripeDir
if($result.target_drift_period_ratio-ne24.5-or$result.accelerator_y_anchor_mm-ne-45.0-or$result.stripe_run_id-ne'stripe-k24p5'){throw 'pair identity lost'}
$otherContract=Join-Path $Root 'other-contract.json'
Write-Json $otherContract @{nominal=@{target_drift_period_ratio=23.5};accelerator=@{focus_y_anchor=@{project_y_mm=-45.0}}}
try{$null=Assert-ContinuationPairIdentity $continuation $otherContract $stripeDir;throw 'K mismatch accepted'}catch{if($_.Exception.Message-notlike'*target K differs*'){throw}}
Write-Json $otherContract @{nominal=@{target_drift_period_ratio=24.5};accelerator=@{focus_y_anchor=@{project_y_mm=-50.0}}}
try{$null=Assert-ContinuationPairIdentity $continuation $otherContract $stripeDir;throw 'y mismatch accepted'}catch{if($_.Exception.Message-notlike'*y anchor differs*'){throw}}
Write-Json $stripeManifest @{schema_version=2;run_id='other-stripe';status='success';project=$project;mode='dual_stripe_fixed_grid_native_downstream_seed'}
try{$null=Assert-ContinuationPairIdentity $continuation $contract $stripeDir;throw 'Stripe mismatch accepted'}catch{if($_.Exception.Message-notlike'*Stripe authority differs*'){throw}}
'CONTINUATION_PAIR_IDENTITY=PASS'
"""
        with TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "continuation-pair.ps1"
            fixture.write_text(script, encoding="utf-8")
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(fixture),
                 str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"), temporary],
                cwd=PROJECT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=40,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("CONTINUATION_PAIR_IDENTITY=PASS", result.stdout)

    def test_parent_owns_one_host_lease_for_all_child_trials(self):
        source = (PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1').read_text(encoding='utf-8-sig')
        self.assertEqual(source.count("Enter-HostResourceStage -Role SIMION"), 1)
        self.assertEqual(source.count("Update-HostResourceStage -Lease $resourceLease"), 1)
        self.assertIn("$preparedRuntime=Get-NativeCorridorRuntimeFamily", source)
        self.assertLess(
            source.index("$preparedRuntime=Get-NativeCorridorRuntimeFamily"),
            source.index("Update-HostResourceStage -Lease $resourceLease"),
        )
        self.assertLess(
            source.index("Update-HostResourceStage -Lease $resourceLease"),
            source.index("$InitialWorkpointManifest=Invoke-WorkpointStencil"),
        )
        self.assertIn("$arguments.InheritedHostResourceLease=$script:resourceLease", source)
        self.assertIn("Exit-HostResourceStage -Lease $resourceLease", source)
        self.assertLess(
            source.index("Enter-HostResourceStage -Role SIMION"),
            source.index("$InitialWorkpointManifest=Invoke-WorkpointStencil"),
        )
        self.assertLess(
            source.rindex("Exit-HostResourceStage -Lease $resourceLease"),
            source.rindex("Invoke-HostExecutionCompletionNotification"),
        )

    def test_accelerator_y_anchor_is_a_run_local_contract_variable(self):
        source = (PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('[Nullable[double]]$AcceleratorYAnchorMm = $null', source)
        self.assertIn('$resolvedContract.accelerator.focus_y_anchor.project_y_mm=[double]$AcceleratorYAnchorMm', source)
        self.assertIn('$script:contract=$frozenContract', source)
        self.assertIn('$arguments.ContractPath=$script:contract', source)

    def test_prism_discovery_window_is_a_complete_run_input(self):
        source = (PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('[Nullable[double]]$Prism1SearchMaximumV = $null', source)
        self.assertIn('Prism search-window override requires four finite bounds.', source)
        self.assertIn('$window.prism_1=@([double]$Prism1SearchMinimumV,[double]$Prism1SearchMaximumV)', source)
        self.assertIn('$window.prism_2=@([double]$Prism2SearchMinimumV,[double]$Prism2SearchMaximumV)', source)

    def test_recovery_anchor_binds_the_matching_child_materialization(self):
        script = r"""
param($Source,$Root)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name-eq'Find-AcceptedRecoveryAnchorEvidence'},$true)
Invoke-Expression $node.Extent.Text
function Write-Json($Path,$Value){$Value|ConvertTo-Json -Depth 10|Set-Content -LiteralPath $Path}
function New-Child($Name,$Voltages){
  $dir=Join-Path $Root $Name;New-Item -ItemType Directory -Path $dir|Out-Null
  $observation=Join-Path $dir 'observation.json';$materialization=Join-Path $dir 'materialization.json'
  Write-Json $observation @{residuals=@{}};Write-Json $materialization @{stripe_biases_v=@($Voltages[0],$Voltages[1]);prism_voltages_v=@($Voltages[2],$Voltages[3])}
  return @{observation=$observation;materialization=$materialization;child_manifest=(Join-Path $dir 'run_manifest.json');child_manifest_sha256='identity';decision=(Join-Path $dir 'decision.json')}
}
$anchor=@(-1.,2.,3.,4.);$accepted=New-Child 'accepted' $anchor;$rejected=New-Child 'rejected' @(-1.1,2.,3.,4.)
# A later rejected decision still carries the accepted workpoint.  It must not
# redirect the anchor's observation/materialization identity.
Write-Json $accepted.decision @{observation_record=@{voltages_v=$anchor}}
Write-Json $rejected.decision @{accepted_workpoint=@{voltages_v=$anchor};observation_record=@{voltages_v=@(-1.1,2.,3.,4.)}}
$result=Find-AcceptedRecoveryAnchorEvidence -History @{} -Lineage @{children=@($accepted,$rejected)} -Anchor @{voltages_v=$anchor}
if($result.materialization-ne$accepted.materialization){throw 'Recovery anchor was rebound to a rejected child'}
Write-Output 'RECOVERY_ANCHOR_BINDING=PASS'
"""
        with TemporaryDirectory() as temporary:
            fixture = Path(temporary) / 'recovery-anchor.ps1'
            fixture.write_text(script, encoding='utf-8')
            result = subprocess.run(
                ['pwsh', '-NoProfile', '-File', str(fixture),
                 str(PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1'), temporary],
                cwd=PROJECT, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=40,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('RECOVERY_ANCHOR_BINDING=PASS', result.stdout)

    def test_recovery_handoffs_renew_parent_capacity_session(self):
        source = (PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1').read_text(encoding='utf-8-sig')
        self.assertEqual(source.count('$recoveryCapacity=Update-ArtifactWorkflowCapacitySession'), 2)
        self.assertEqual(source.count('$capacitySession=$recoveryCapacity.session'), 2)
        self.assertEqual(source.count('$protectionReceipts += $recoveryCapacityPath'), 2)

    def test_physical_gate_reverse_fallback_resume_and_voltage_binding(self):
        script = r"""
param($Source,$Root,$Scenario,$FixturePython)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
foreach($name in @('Get-WorkpointBootstrapEvidence','Save-WorkpointBootstrap','Invoke-WorkpointStencil','Invoke-CenterTrial','Invoke-WorkpointControllerRequest')){
  $node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name-eq$name},$true)
  Invoke-Expression $node.Extent.Text
}
$repoRoot=(Get-Item $Source).Directory.Parent.Parent.Parent.FullName
$project='fixture';$python='Invoke-MockPython';$frozenContract='frozen'
$script:feedbackCalls=0;$script:verificationCalls=0;$script:stencilPlans=0
$staticFieldMode=$false
$capacitySession=@{lease_id='owner'};$nativeRuntimeSession=@{checkpoint_path=(Join-Path $Root 'family.json')}
[IO.File]::WriteAllText($nativeRuntimeSession.checkpoint_path,'{}')
function Invoke-MockPython {
  if($args[0]-eq'-X'){
    $payload=@($input)
    if(($payload-join''|ConvertFrom-Json).action-eq'center_trial_physical_gate'){$script:feedbackCalls++}else{$script:stencilPlans++}
    $payload | & $FixturePython @args
    return
  }
  if($args[3]-ne'success'-or$args[4]-ne'--require-project'-or$args[5]-ne'instrument_assembly'-or
     $args[6]-ne'--require-mode'-or$args[7]-ne'oa_mr'){
    throw 'Ordinary MR bootstrap used a foreign run identity'
  }
  $script:verificationCalls++
  $global:LASTEXITCODE=0
}
function Get-ManifestOutputPath {param($ManifestPath,$FileName) return (Join-Path (Split-Path $ManifestPath) $FileName)}
function Write-RunJson {param($Path,$Depth,$Value) $Value|ConvertTo-Json -Depth 30|Set-Content -LiteralPath $Path}
function Save-NativeWorkflowCheckpoint {param($Reason,$WorkflowOutcome) $script:checkpoints++}
function New-CenterTrialArguments {param($Voltages,$ChildRunId) return @{Voltages=$Voltages;ChildRunId=$ChildRunId}}
function New-FixtureChild {
  param($ChildRunId,$Voltages,[bool]$Valid)
  $dir=Join-Path $artifactRoot ('runs/'+$ChildRunId);New-Item -ItemType Directory -Path $dir -Force|Out-Null
  Write-RunJson (Join-Path $dir 'run_manifest.json') 30 @{status='success';run_id=$ChildRunId}
  $actual=@($Voltages);if($script:scenario-eq'wrong_voltage'){$actual[0]+=1}
  Write-RunJson (Join-Path $dir 'two_prism_trial_materialization.json') 30 @{stripe_biases_v=@($actual[0],$actual[1]);prism_voltages_v=@($actual[2],$actual[3])}
  $observation=@{status='full_drift_observed';prism_voltages_v=@($actual[2],$actual[3]);termination_diagnostic=@{physical_collision=(-not$Valid)};residuals=@{};static_return_diagnostic=@{status='detector_not_observed';event_contract_ok=$false}}
  if($Valid){$observation.residuals.Stripe_target_phase_y_minus_origin_mm=1.;$observation.static_return_diagnostic=@{status='detector_hit';event_contract_ok=$true}}
  Write-RunJson (Join-Path $dir 'two_prism_trial_observation.json') 30 $observation
  return Join-Path $dir 'run_manifest.json'
}
function Invoke-MockTrial {
  param($Voltages,$ChildRunId)
  $script:flights+=,@{id=$ChildRunId;voltages=@($Voltages)}
  $valid=$ChildRunId-notlike'*-stencil-2'
  if($script:scenario-eq'reverse_failure'-and$ChildRunId-like'*-stencil-2-reverse'){$valid=$false}
  if($script:scenario-eq'baseline_failure'-and$ChildRunId-like'*-baseline'){$valid=$false}
  $null=New-FixtureChild $ChildRunId $Voltages $valid
}
function Invoke-MockAudit {param($BaselineManifest,$Stripe1PerturbationManifest,$Stripe2PerturbationManifest,$Prism1PerturbationManifest,$Prism2PerturbationManifest,$ContractPath,$RunId,$PythonExe,$CapacityWorkflowSession)
  if($Stripe2PerturbationManifest-notlike'*-stencil-2-reverse*'){throw 'Invalid forward stencil reached audit'}
  $script:audits++
}
$trialRunner='Invoke-MockTrial';$auditRunner='Invoke-MockAudit'
$script:scenario=$Scenario
  $artifactRoot=Join-Path $Root $script:scenario;New-Item -ItemType Directory -Path $artifactRoot|Out-Null
$trialArtifactRoot=$artifactRoot
  $RunId='new-parent';$script:flights=@();$script:audits=0;$script:checkpoints=0
  $bootstrap=[ordered]@{schema_version=1;seed_voltages_v=@(1.,2.,3.,4.);forward_steps_v=@(.1,.1,.1,.1);children=@()}
  if($script:scenario-eq'resume'){
    $bootstrap.children+=New-FixtureChild 'old-baseline' @(1.,2.,3.,4.) $true
    $bootstrap.children+=New-FixtureChild 'old-stencil-1' @(1.1,2.,3.,4.) $true
    $bootstrap.children+=New-FixtureChild 'old-stencil-2' @(1.,2.1,3.,4.) $false
  }
  $checkpoint=Join-Path $artifactRoot 'bootstrap.json';$failure=$null
  try{$null=Invoke-WorkpointStencil -Bootstrap $bootstrap -BootstrapPath $checkpoint}catch{$failure=$_.Exception.Message}
  if($script:scenario-in@('reverse_success','resume')){
    if($failure-or$script:audits-ne1-or$bootstrap.children.Count-ne5-or$bootstrap.signed_steps_v[1]-ne-.1){throw "Fallback failed: $failure"}
    if($script:scenario-eq'resume'-and($script:flights.Count-ne3-or$bootstrap.children[0]-notlike'*old-baseline*'-or$bootstrap.children[1]-notlike'*old-stencil-1*')){throw 'Resume reran valid children'}
    $invalid=@($bootstrap.attempts|Where-Object{-not$_.passed})
    if($invalid.Count-ne1-or-not$invalid[0].observation_sha256-or$bootstrap.children-contains$invalid[0].child_manifest){throw 'Invalid observation evidence was lost or accepted'}
    $before=$script:flights.Count
    $null=Invoke-WorkpointStencil -Bootstrap $bootstrap -BootstrapPath $checkpoint
    if($script:flights.Count-ne$before){throw 'Completed reverse attempt was repeated'}
  }elseif($script:scenario-eq'reverse_failure'){
    if(-not$failure-or$script:flights.Count-ne4-or$script:audits-ne0-or$bootstrap.children.Count-ne2-or$bootstrap.attempts.Count-ne4){throw 'Reverse failure did not stop immediately'}
  }elseif($script:scenario-eq'baseline_failure'){
    if(-not$failure-or$script:flights.Count-ne1-or$script:audits-ne0-or$bootstrap.children.Count-ne0){throw 'Invalid baseline allowed stencil'}
  }else{if($failure-notlike'*voltages differ*'-or$script:flights.Count-ne1-or$script:audits-ne0){throw 'Wrong materialized voltage was accepted'}}
  if($script:scenario-ne'wrong_voltage'-and($script:checkpoints-lt1-or-not(Test-Path $checkpoint))){throw 'Physical attempt was not checkpointed'}
@{feedback=$script:feedbackCalls;verifier=$script:verificationCalls;plans=$script:stencilPlans}|ConvertTo-Json -Compress
'PHYSICAL_BOOTSTRAP=PASS'
"""
        totals = dict(feedback=0, verifier=0, plans=0)
        with TemporaryDirectory() as temporary:
            fixture = Path(temporary) / 'physical.ps1'
            fixture.write_text(script, encoding='utf-8', newline='\n')
            for scenario in ('reverse_success', 'reverse_failure', 'resume',
                             'baseline_failure', 'wrong_voltage'):
                with self.subTest(scenario=scenario):
                    result = subprocess.run(
                        ['pwsh', '-NoProfile', '-File', str(fixture),
                         str(PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1'),
                         temporary, scenario, sys.executable],
                        cwd=PROJECT, capture_output=True, text=True, encoding='utf-8', timeout=40,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('PHYSICAL_BOOTSTRAP=PASS', result.stdout)
                    counts = json.loads(result.stdout.splitlines()[-2])
                    for key in totals:
                        totals[key] += counts[key]
        self.assertEqual(totals, dict(feedback=29, verifier=30, plans=7))

    def test_stencil_plan_preserves_save_trace_and_late_identity_failure(self):
        script = r"""
param($Source,$Root,$FixturePython)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
foreach($name in @('Invoke-WorkpointStencil','Invoke-WorkpointControllerRequest')){
  $node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)
  Invoke-Expression $node.Extent.Text
}
$repoRoot=(Get-Item $Source).Directory.Parent.Parent.Parent.FullName
$python=$FixturePython
$RunId='reference';$artifactRoot=$Root;$trialArtifactRoot=$Root;$frozenContract='frozen';$capacitySession=@{}
$script:flights=@();$script:saves=@();$script:lastTier=$true
function New-CenterTrialArguments {param($Voltages,$ChildRunId)@{Voltages=$Voltages;ChildRunId=$ChildRunId}}
function Invoke-CenterTrial {param($Arguments)$script:flights+=,@($Arguments.Voltages)}
function Get-WorkpointBootstrapEvidence {param($Manifest,$Voltages)
  @{passed=(-not$script:lastTier-or$Manifest-like'*-baseline*'-or$Manifest-like'*-tier-3-reverse*');reasons=@();child_manifest=$Manifest;child_manifest_sha256='M';materialization_sha256='A';observation_sha256='B'}
}
function Save-WorkpointBootstrap {param($Bootstrap,$BootstrapPath)$script:saves+=@{attempts=$Bootstrap.attempts.Count;children=$Bootstrap.children.Count;signed_steps=@($Bootstrap.signed_steps_v)}}
function Invoke-ReferenceAudit {}
$auditRunner='Invoke-ReferenceAudit'
$bootstrap=[ordered]@{seed_voltages_v=@(-27.,54.,190.,-190.);forward_steps_v=@(.27,.54,1.9000000000000001,1.9000000000000001);stencil_step_scales=@(1.,.25,.05);children=@()}
$null=Invoke-WorkpointStencil -Bootstrap $bootstrap -BootstrapPath 'unused'
if($script:flights.Count-ne25-or$script:saves.Count-ne25){throw 'Changed full-tier dispatch/save count'}
$expectedChildren=@(1,1,1,1,1,1,2,2,2,2,2,2,3,3,3,3,3,3,4,4,4,4,4,4,5)
for($i=0;$i-lt25;$i++){
  if($script:saves[$i].attempts-ne($i+1)-or$script:saves[$i].children-ne$expectedChildren[$i]){throw 'Save moved before/after its physical acceptance'}
}
$expected=@(-.013500000000000002,-.027000000000000003,-.09500000000000001,-.09500000000000001)
for($i=0;$i-lt4;$i++){if([double]$bootstrap.signed_steps_v[$i]-ne$expected[$i]){throw 'Signed step multiplication order changed'}}
$script:flights=@();$script:saves=@();$script:lastTier=$false
$bootstrap=[ordered]@{seed_voltages_v=@(-27.,54.,190.,-190.);forward_steps_v=@(.27,.54,1.9000000000000001,1.9000000000000001);children=@();attempts=@(@{axis=3;direction=1;signed_step_v=99.;child_manifest='later';child_manifest_sha256='M';observation_sha256='B';materialization_sha256='A';passed=$true})}
$failure=$null
try{$null=Invoke-WorkpointStencil -Bootstrap $bootstrap -BootstrapPath 'unused'}catch{$failure=$_.Exception.Message}
if($failure-notlike'*recorded signed step differs*'-or$script:flights.Count-ne4-or$script:saves.Count-ne4-or$bootstrap.children.Count-ne4){throw 'Future identity error moved before prior dispatch/checkpoints'}
'STENCIL_SAVE_TRACE=PASS'
"""
        with TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "stencil-trace.ps1"
            fixture.write_text(script, encoding="utf-8")
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(fixture), str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"), temporary, sys.executable],
                cwd=PROJECT, capture_output=True, text=True, encoding="utf-8", timeout=40,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("STENCIL_SAVE_TRACE=PASS", result.stdout)

    def test_resume_skips_completed_stencil_and_checkpoint_preserves_owner(self):
        script = r"""
param($Source,$Root,$FixturePython)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
foreach($name in @('Invoke-WorkpointStencil','Save-WorkpointBootstrap','Save-NativeWorkflowCheckpoint','Invoke-CenterTrial','Invoke-WorkpointControllerRequest')){
  $node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name-eq$name},$true)
  Invoke-Expression $node.Extent.Text
}
$staticFieldMode=$false
$RunId='new-parent';$artifactRoot=$Root;$repoRoot=(Get-Item $Source).Directory.Parent.Parent.Parent.FullName;$project='fixture';$python='Invoke-MockPython'
$trialArtifactRoot=$artifactRoot
$frozenContract='frozen';$capacitySession=[pscustomobject]@{lease_id='new-lease'}
$script:flights=@();$script:audit=0;$script:checks=0;$script:events=@()
function Invoke-MockPython {
  if($args[0]-eq'-X'){$input | & $FixturePython @args;return}
  $script:checks++;$global:LASTEXITCODE=0
}
function Get-WorkpointBootstrapEvidence {param($Manifest,$Voltages) $script:checks++;return @{passed=$true;reasons=@();observation_sha256='A';materialization_sha256='B';child_manifest_sha256='C';child_manifest=$Manifest}}
function Get-ManifestOutputPath {param($ManifestPath,$FileName) return (Join-Path $Root 'materialization.json')}
[IO.File]::WriteAllText((Join-Path $Root 'materialization.json'),' {"stripe_biases_v":[1,2],"prism_voltages_v":[3,4]} ')
function New-CenterTrialArguments {param($Voltages,$ChildRunId) return @{Voltages=$Voltages;ChildRunId=$ChildRunId}}
function Invoke-MockTrial {param($Voltages,$ChildRunId) $script:flights+=,$ChildRunId}
function Invoke-MockAudit {param($BaselineManifest,$Stripe1PerturbationManifest,$Stripe2PerturbationManifest,$Prism1PerturbationManifest,$Prism2PerturbationManifest,$ContractPath,$RunId,$PythonExe,$CapacityWorkflowSession)
  if($BaselineManifest-ne'old-parent-baseline'){throw 'Completed baseline was discarded'}
  $script:audit++
}
function Write-RunJson {param($Path,$Depth,$Value) $script:events+=,@('json',$Path,$Value)}
$trialRunner='Invoke-MockTrial';$auditRunner='Invoke-MockAudit'
$bootstrap=[ordered]@{seed_voltages_v=@(1.,2.,3.,4.);forward_steps_v=@(.1,.1,.1,.1);children=@('old-parent-baseline')}
$null=Invoke-WorkpointStencil -Bootstrap $bootstrap -BootstrapPath 'unused'
if($script:flights.Count-ne4-or$script:flights[0]-ne'new-parent-stencil-1'-or$script:audit-ne1-or$script:checks-ne5){throw 'Resume duplicated a successful flight or reused failed ID'}
$package=@{result_dir=$Root;summary=(Join-Path $Root 'summary.json');run_config='current-config'}
$artifactWorkspaceRoot=$Root;$failureStage='bootstrap_center_1'
$nativeRuntimeSession=[pscustomobject]@{directory=$Root;owner_run_config='original-owner-config';owner_run_directory='original-owner';checkpoint_path=(Join-Path $Root 'family-receipt.json')}
[IO.File]::WriteAllText($nativeRuntimeSession.checkpoint_path,'{}')
function Invoke-RunCapacityLifecycleAdapter {param($Python,$RepoRoot,$Action,$ArtifactRoot,$RunConfig) $script:events+=,@('resident',$RunConfig)}
function Write-VerifiedRunManifest {param($Python,$RepoRoot,$RunConfig,$Status,$Software,$Outputs)
  if($Status-ne'checkpoint'-or$Outputs-notcontains$nativeRuntimeSession.checkpoint_path){throw 'Family was not checkpointed'}
  $script:events+=,@('manifest',$Status)
  Write-Output 'RUN_MANIFEST_VERIFY=PASS'
}
function Update-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session,$RemainingCommittedNewBytes)
  if($RemainingCommittedNewBytes-ne0-or$script:events[-1][0]-ne'resident'){throw 'Commitment dropped before resident update'}
  $script:events+=,@('commitment',0)
}
$script:events=@()
$checkpointOutput=@(Save-NativeWorkflowCheckpoint -Reason 'real child IOB failure')
if($checkpointOutput.Count-ne0){throw 'Checkpoint logging polluted the stencil return value'}
if($script:events[0][1]-ne'original-owner-config'-or-not(Test-Path $nativeRuntimeSession.checkpoint_path)){throw 'Old owner asset was lost'}
$summary=@($script:events|Where-Object{$_[0]-eq'json'})[0][2]
if($summary.reason-ne'real child IOB failure'-or$summary.external_interruption-or-not$summary.resume_requires_new_run_id){throw 'Handled failure provenance differs'}
$script:events=@()
Save-NativeWorkflowCheckpoint -Reason 'external interruption' -ExternalInterruption
$summary=@($script:events|Where-Object{$_[0]-eq'json'})[0][2]
if(-not$summary.external_interruption){throw 'External interruption was disguised'}
$script:events=@()
Save-NativeWorkflowCheckpoint -Reason 'success' -WorkflowOutcome workpoint_complete_downstream_pending -FinalDecision @{terminal_reason='success'}
$summary=@($script:events|Where-Object{$_[0]-eq'json'})[0][2]
if($summary.status-ne'checkpoint'-or$summary.workflow_outcome-ne'workpoint_complete_downstream_pending'-or
   $summary.final_decision.terminal_reason-ne'success'-or-not(Test-Path $nativeRuntimeSession.checkpoint_path)){throw 'Workpoint completion retired the pending downstream family'}
Write-Output 'RESUME_CHECKPOINT=PASS'
"""
        with TemporaryDirectory() as temporary:
            fixture = Path(temporary) / 'resume.ps1'
            fixture.write_text(script, encoding='utf-8')
            result = subprocess.run(
                ['pwsh', '-NoProfile', '-File', str(fixture),
                 str(PROJECT / 'analysis/run_downstream_workpoint_iteration.ps1'), temporary, sys.executable],
                cwd=PROJECT, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=40,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('RESUME_CHECKPOINT=PASS', result.stdout)

    def test_seed_projection_ignores_unused_pa_but_rejects_changed_receipt(self):
        repo = PROJECT.parents[1]
        script = r"""
param($Source,$repoRoot,$python,$SeedTrialManifest,$Inputs)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. (Join-Path $repoRoot 'common/contracts/run_artifact_support.ps1')
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
$node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name-eq'Get-ManifestOutputPath'},$true)
Invoke-Expression $node.Extent.Text
$project='parallel_mirror_dual_stripe_mr_tof'
$package=@{input_dir=$Inputs}
$sourceText=Get-Content -LiteralPath $Source -Raw
$start=$sourceText.IndexOf('$seedManifest=(Resolve-Path')
$end=$sourceText.IndexOf('$seedVoltages=', $start)
Invoke-Expression $sourceText.Substring($start,$end-$start)
if($seed.stripe_biases_v[0]-ne-24-or$seed.prism_voltages_v[1]-ne-195){throw 'Wrong seed voltages'}
if($seedProjection.assertion_scope-notlike'*other_historical_records_not_asserted'){throw 'Missing projection scope'}
Write-Output 'SEED_PROJECTION=PASS'
"""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "inputs"
            inputs.mkdir()
            config = root / "run_config.json"
            config.write_text(json.dumps({"schema_version": 1, "project": "parallel_mirror_dual_stripe_mr_tof",
                                          "mode": "finite_3d_two_prism_voltage_trial"}))
            receipt = root / "two_prism_trial_materialization.json"
            receipt.write_text(json.dumps({"stripe_biases_v": [-24, 51], "prism_voltages_v": [196, -195]}))

            def record(path):
                return {"path": str(path), "bytes": path.stat().st_size,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper()}

            manifest = root / "run_manifest.json"
            manifest.write_text(json.dumps({
                "schema_version": 1, "status": "success", "project": "parallel_mirror_dual_stripe_mr_tof",
                "mode": "finite_3d_two_prism_voltage_trial", "run_config": record(config),
                "inputs": {"read_only_analyzer_pa": {"path": str(root / "missing_old.pa"), "bytes": 100, "sha256": "A" * 64}},
                "outputs": [record(receipt)],
            }))
            fixture = root / "fixture.ps1"
            fixture.write_text(script)
            command = ["pwsh", "-NoProfile", "-File", str(fixture),
                       str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"), str(repo),
                       sys.executable, str(manifest), str(inputs)]
            good = subprocess.run(command, cwd=PROJECT, capture_output=True, text=True, encoding="utf-8", check=False, timeout=40)
            self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
            self.assertIn("SEED_PROJECTION=PASS", good.stdout)
            document = json.loads(manifest.read_text(encoding='utf-8'))
            old_owner, old_mode = document["project"], document["mode"]
            for owner, mode, accepted in (
                ("instrument_assembly", "oa_mr", True),
                (old_owner, "oa_mr", False),
                ("instrument_assembly", old_mode, False),
            ):
                with self.subTest(owner=owner, mode=mode):
                    config.write_text(json.dumps({"schema_version": 1, "project": owner, "mode": mode}))
                    document.update(project=owner, mode=mode, run_config=record(config))
                    manifest.write_text(json.dumps(document))
                    checked = subprocess.run(command, cwd=PROJECT, capture_output=True,
                                             text=True, encoding="utf-8", timeout=40)
                    self.assertEqual(checked.returncode == 0, accepted, checked.stdout + checked.stderr)
                    if not accepted:
                        self.assertIn("unsupported flight owner/mode pair", checked.stderr)
            config.write_text(json.dumps({"schema_version": 1, "project": old_owner, "mode": old_mode}))
            document.update(project=old_owner, mode=old_mode, run_config=record(config))
            manifest.write_text(json.dumps(document))
            receipt.write_text("{}")
            bad = subprocess.run(
                command,
                cwd=PROJECT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=40,
            )
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("Manifest output hash differs", bad.stdout)
        source = (PROJECT / "analysis/run_downstream_workpoint_iteration.ps1").read_text(encoding='utf-8')
        self.assertIn("$configuration.parameters.voltage_seed_consumer_projection=$seedProjection", source)
        self.assertIn("$configuration.inputs.voltage_seed_materialization=$frozenSeedMaterialization", source)

    def test_native_stencil_dispatch_and_failure_stop(self):
        script = r"""
param($Source,$Root,$FixturePython)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$ast=[System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$null,[ref]$null)
foreach($name in @('New-CenterTrialArguments','Invoke-WorkpointStencil','Save-WorkpointBootstrap','Invoke-CenterTrial','Invoke-WorkpointControllerRequest')){
  $node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name-eq$name},$true)
  Invoke-Expression $node.Extent.Text
}
$staticFieldMode=$false
$GeometryReviewRunPath='geometry';$MirrorRunPath='mirror';$StripeRunPath='stripe';$AcceleratorProviderReceiptPath='provider-receipt'
$NativeSystemRuntimeBundlePath='native-system-bundle.json';$TrajectoryStepScale=1.;$AcceleratorSourceYOffsetMm=-1.7
$repoRoot=(Get-Item $Source).Directory.Parent.Parent.Parent.FullName
$python=$FixturePython;$capacitySession=[pscustomobject]@{lease_id='owner'}
$nativeRuntimeSession=[pscustomobject]@{lease_id='owner';directory=$null;runtime=$null;checkpoint_path=(Join-Path $Root 'not-yet-created.json')}
$NativeCorridorBankRunPath='native-bank'
$SimionExe='simion';$PulseAcceleratorUntilInitialExit=$true;$AcceleratorPulseSchedulePath=''
$TrajectoryProfileId='center_screening'
$artifactRoot=$Root;$RunId='auto';$frozenContract='frozen.json'
$trialArtifactRoot=$artifactRoot
$CompositionPlanPath='parent-plan';$LocalScopePath=''
$script:flights=@();$script:audits=0;$script:failAt=0
function Write-RunJson {param($Path,$Depth,$Value)}
function Get-WorkpointBootstrapEvidence {param($Manifest,$Voltages) return @{passed=$true;reasons=@();observation_sha256='A';materialization_sha256='B';child_manifest_sha256='C';child_manifest=$Manifest}}
function Invoke-MockTrial {
  param($GeometryReviewRunPath,$MirrorRunPath,$StripeRunPath,$AcceleratorProviderReceiptPath,$Prism1VoltageV,$Prism2VoltageV,$Stripe1VoltageV,$Stripe2VoltageV,$NativeSystemRuntimeBundlePath,$TrajectoryStepScale,$AcceleratorSourceYOffsetMm,$RunId,$PythonExe,$CapacityWorkflowSession,$NativeCorridorBankRunPath,$NativeCorridorRuntimeSession,$SimionExe,[switch]$PulseAcceleratorUntilInitialExit,$TrajectoryProfileId,$CompositionPlanPath,$LocalScopePath)
  if($NativeCorridorBankRunPath-ne'native-bank'-or$NativeSystemRuntimeBundlePath-ne'native-system-bundle.json'-or$CapacityWorkflowSession.lease_id-ne'owner'){throw 'Lost field, native-system, or owner binding'}
  $script:flights+=,@($Stripe1VoltageV,$Stripe2VoltageV,$Prism1VoltageV,$Prism2VoltageV)
  if($script:failAt-eq$script:flights.Count){throw 'injected solver failure'}
}
function Invoke-MockAudit {
  param($BaselineManifest,$Stripe1PerturbationManifest,$Stripe2PerturbationManifest,$Prism1PerturbationManifest,$Prism2PerturbationManifest,$ContractPath,$RunId,$PythonExe,$CapacityWorkflowSession)
  $script:audits++
  if($script:flights.Count-ne5-or$ContractPath-ne'frozen.json'-or$CapacityWorkflowSession.lease_id-ne'owner'){throw 'Audit ran before the full stencil'}
  if($BaselineManifest-notlike'*auto-baseline*'-or$Prism2PerturbationManifest-notlike'*auto-stencil-4*'){throw 'Wrong lineage'}
}
$trialRunner='Invoke-MockTrial';$auditRunner='Invoke-MockAudit'
$bootstrap=[ordered]@{seed_voltages_v=@(-24.,51.,196.,-195.);forward_steps_v=@(.1,.1,.1,.1);children=@()}
$result=Invoke-WorkpointStencil -Bootstrap $bootstrap -BootstrapPath 'unused'
if($script:audits-ne1-or$result-notlike'*auto-jacobian*'){throw 'Missing automatic audit'}
for($i=0;$i-lt5;$i++){for($j=0;$j-lt4;$j++){
  $expected=$bootstrap.seed_voltages_v[$j]+$(if($i-eq($j+1)){.1}else{0})
  if([math]::Abs($script:flights[$i][$j]-$expected)-gt1e-12){throw 'Wrong independent perturbation'}
}}
$script:flights=@();$script:audits=0;$script:failAt=2;$bootstrap.children=@();$bootstrap.attempts=@()
try{$null=Invoke-WorkpointStencil -Bootstrap $bootstrap -BootstrapPath 'unused';throw 'Failure was swallowed'}
catch{if($_.Exception.Message-ne'injected solver failure'){throw}}
if($script:flights.Count-ne2-or$script:audits-ne0){throw 'Failed flight must stop downstream work'}
Write-Output 'BOOTSTRAP=PASS'
"""
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "fixture.ps1"
            path.write_text(script, encoding="utf-8")
            result = subprocess.run(
                ["C:/Program Files/PowerShell/7/pwsh.exe", "-NoProfile", "-File", str(path),
                 str(PROJECT / "analysis/run_downstream_workpoint_iteration.ps1"), temporary, sys.executable],
                cwd=PROJECT, capture_output=True, text=True, encoding='utf-8', errors='replace', check=False, timeout=40,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BOOTSTRAP=PASS", result.stdout)

    def test_requires_and_forwards_native_system_runtime_bundle(self):
        source = (PROJECT / "analysis/run_downstream_workpoint_iteration.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("NativeCorridorBankRunPath requires NativeSystemRuntimeBundlePath.", source)
        self.assertIn("$arguments.NativeSystemRuntimeBundlePath=$NativeSystemRuntimeBundlePath", source)
        self.assertIn("native_system_runtime_bundle=(Resolve-Path -LiteralPath $NativeSystemRuntimeBundlePath).Path", source)

    def test_gui_retention_is_limited_to_bootstrap_baseline(self):
        source = (PROJECT / "analysis/run_downstream_workpoint_iteration.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("[switch]$RetainBaselineGuiWorkbench", source)
        self.assertIn(
            "if($axis-lt0-and$RetainBaselineGuiWorkbench){$arguments.RetainGuiWorkbench=$true}",
            source,
        )
        self.assertNotIn("$trialArguments.RetainGuiWorkbench", source)

    def test_direct_native_checkpoint_reuse_is_independent_of_iob_pose(self):
        source = (PROJECT / "analysis/run_downstream_workpoint_iteration.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("Open-NativeCorridorRuntimeCheckpoint", source)
        self.assertIn("IOB\n  # poses", source)
        self.assertNotIn("Native runtime physical problem differs", source)

    def test_resume_compares_bundle_content_not_run_local_copy_path(self):
        source = (PROJECT / "analysis/run_downstream_workpoint_iteration.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("if($key-ne'native_system_runtime_bundle')", source)
        self.assertIn("Test-RunFilesIdentical -Left $priorBundle -Right $currentBundle", source)

    def test_provider_receipt_is_preserved_through_workpoint_and_bunch_handoff(self):
        source = (PROJECT / "analysis/run_downstream_workpoint_iteration.ps1").read_text(encoding="utf-8-sig")
        bunch = (PROJECT / "analysis/run_native_corridor_bunch_screening.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("AcceleratorProviderReceiptPath", source)
        self.assertNotIn("AcceleratorRunPath", source)
        self.assertIn("accelerator_provider_receipt=(Resolve-Path -LiteralPath $AcceleratorProviderReceiptPath).Path", source)
        self.assertIn("$arguments.AcceleratorProviderReceiptPath=$AcceleratorProviderReceiptPath", source)
        self.assertIn("$problem.accelerator_provider_receipt", bunch)
        self.assertIn("$cohortArguments.AcceleratorProviderReceiptPath=$providerReceipt", bunch)
        self.assertIn("$cohortArguments.AcceleratorProviderReceiptPath=$providerReceipt", bunch)
        for obsolete in (
            "LocalWorkbenchRunPath", "LocalResponseFamilyRunPath",
            "LocalRegionOverrideWorkbenchRunPath", "LocalRegionOverrideRegions",
            "LocalHandoffSelectionRunPath", "RuntimeCentralStripeResponse",
            "BootstrapGlobalOperatingPa", "$useNativeCorridor",
        ):
            self.assertNotIn(obsolete, source)

    def test_iteration_parent_consumes_only_named_child_evidence(self):
        source = (PROJECT / "analysis/run_downstream_workpoint_iteration.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("mrtof_downstream_iteration_child_v1", source)
        self.assertIn("'--consumed-output',$observation", source)
        self.assertIn("'--consumed-output',$materialization", source)
        self.assertIn("'--consumed-output',$cacheIdentity", source)
        self.assertIn("'--consumed-output',$childProtectionPath", source)

    def test_success_can_continue_directly_to_standard_bunch_screening(self):
        source = (PROJECT / "analysis/run_downstream_workpoint_iteration.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("[string]$BunchSourceReceiptPath = ''", source)
        self.assertIn("$terminalDecision.terminal_reason-eq'success'", source)
        self.assertIn("Suspend-NativeCorridorRuntimeSession -Session $nativeRuntimeSession", source)
        self.assertIn("$capacitySession=$null", source)
        self.assertIn("BunchSourceReceiptPath=$BunchSourceReceiptPath", source)
        self.assertIn("& $bunchScreeningRunner @screeningArguments", source)


if __name__ == "__main__":
    unittest.main()
