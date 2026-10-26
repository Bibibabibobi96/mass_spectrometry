"""Public preparation freezes the actual executable closure in a managed run."""
from __future__ import annotations

import copy
from collections import Counter
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from common.simion.process_observation import run_observed_process
from integrations.tests.test_single_reflection_preparation import fixture, release_fixture, rename_author_instances

REPO = Path(__file__).resolve().parents[2]
EXECUTE = REPO / 'integrations/workflows/single_reflection_flight/execute.ps1'


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell 7 is required')
class SingleReflectionExecuteTests(unittest.TestCase):
    def test_public_prepare_registers_field_continuation_frozen_closure(self):
        from common.contracts.write_run_manifest import file_record
        from integrations.tests.test_single_reflection_preparation import (
            frontend_field_source_fixture, downstream_field_source_fixture, write_json,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path, _, request = fixture(root)
            frontend_field_source_fixture(root, request_path, request, fine=False)
            downstream_field_source_fixture(root, request_path, request)
            request['providers']['frontend_field_reuse_members'] = ['carrier_off', 'rf_reference']
            parent = root / 'parent'
            parent.mkdir()
            write_json(parent / 'run_config.json', dict(schema_version=2, project='instrument_assembly',
                run_id='parent', mode='single_reflection_fly'))
            write_json(parent / 'run_manifest.json', dict(schema_version=2, role='simulation_run_manifest',
                project='instrument_assembly', run_id='parent', mode='single_reflection_fly', status='checkpoint',
                run_config=file_record(parent / 'run_config.json'), inputs={}, outputs=[]))
            transaction, stopped = root / 'transaction.json', root / 'stopped.json'
            write_json(transaction, dict(fixture='transaction source'))
            write_json(stopped, dict(schema_version=1, role='run_capacity_lifecycle_receipt', action='seal_stopped_payload',
                status='ready', run_status='checkpoint', run_directory=str(parent.resolve()),
                run_config=file_record(parent / 'run_config.json')))
            request['continuation'] = dict(predecessor_run_manifest=file_record(parent / 'run_manifest.json'),
                stopped_receipt=file_record(stopped), frontend_field_transactions=[dict(domain_id='parent',
                    member_id='pulse_delta', transaction_record=file_record(transaction))])
            write_json(request_path, request)
            script = root / 'prepare.ps1'
            script.write_text(r'''
param($Repo,$Python,$Root,$Request)
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$package=New-RunPackage -Python $Python -RepoRoot $Repo -ArtifactRoot (Join-Path $Root 'packages') `
  -RunId '20261025_010000__analysis__python__field-continuation-test' -Project instrument_assembly `
  -Mode single_reflection_preparation -Software @('Python 3.11')
$ownerSession=[pscustomobject]@{status='active';committed_new_bytes=17;lease_id='prepare-only-unused'}
& (Join-Path $Repo 'integrations/workflows/single_reflection_flight/execute.ps1') `
  -Request $Request -PrepareOnly -OutputDirectory $package.run_dir -RepoRoot $Repo -Python $Python -WorkflowCapacitySession $ownerSession
if($ownerSession.status-ne'active'-or$ownerSession.committed_new_bytes-ne17){throw 'PrepareOnly changed the owner capacity session'}
''', encoding='utf-8', newline='\n')
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), str(REPO), sys.executable,
                str(root), str(request_path)], cwd=REPO, capture_output=True, text=True, encoding='utf-8', timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            run = next((root / 'packages/runs').iterdir())
            config = json.loads((run / 'run_config.json').read_text())
            receipt = json.loads((run / 'results/single_reflection/preparation_receipt.json').read_text())
            for name, record in receipt['input_records'].items():
                self.assertEqual(config['inputs'][name], record['path'])
                self.assertTrue(Path(record['path']).is_relative_to(run / 'inputs'))
            self.assertTrue(Path(config['inputs']['code_inventory']).is_file())
            self.assertTrue(Path(config['inputs']['dependency_contract']).is_file())
            for name, original in (('continuation_stopped_receipt', stopped),
                                   ('continuation_field_transaction_001', transaction)):
                expected = original.read_bytes()
                original.unlink()
                self.assertEqual(Path(config['inputs'][name]).read_bytes(), expected)

    def test_declared_downstream_publication_skips_native_and_evidence_republication(self):
        code = r'''param($Execute)
$ErrorActionPreference='Stop'
$ast=[Management.Automation.Language.Parser]::ParseFile($Execute,[ref]$null,[ref]$null)
$branch=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and$n.Clauses[0].Item1.Extent.Text-eq"`$downstreamPlan.ContainsKey('publication')"},$true)
if(-not$branch){throw 'source publication boundary missing'}
function Invoke-ResourceBudgetedProcess {throw 'source entered native solver'}
function Write-NativeExecutionEvidence {throw 'source rewrote native execution evidence'}
function Invoke-RunToolRootContext {throw 'source republished original native fields'}
$publication=@{receipt_record=@{path='frozen_source_receipt.json';bytes=12;sha256='producer-identity'};receipt=@{status='success'}}
$downstreamPlan=@{steps=@();publication=$publication}
. ([scriptblock]::Create($branch.Extent.Text))
if(-not[object]::ReferenceEquals($published,$publication)){throw 'source publication was rebuilt'}
'DOWNSTREAM_SOURCE_PUBLIC_BRANCH=PASS'
'''
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'source.ps1'
            script.write_text(code, encoding='utf-8', newline='\n')
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), str(EXECUTE)],
                cwd=REPO, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('DOWNSTREAM_SOURCE_PUBLIC_BRANCH=PASS', result.stdout)

    def test_explicit_field_source_reserves_private_payload_and_protects_producer(self):
        code = r'''param($Execute,$Producer)
$ErrorActionPreference='Stop'
$ast=[Management.Automation.Language.Parser]::ParseFile($Execute,[ref]$null,[ref]$null)
$body=$ast.Find({param($n)$n-is[Management.Automation.Language.TryStatementAst]-and$n.Body.Extent.Text.Contains('$commitment=')},$true).Body
$statements=@();$collect=$false
foreach($statement in $body.Statements){
 if($statement.Extent.Text.StartsWith('$commitment=')){$collect=$true}
 if($collect){$statements+=$statement.Extent.Text}
 if($collect-and$statement.Extent.Text.StartsWith('if($ownsCapacity)')){break}
}
if(-not$statements.Count){throw 'capacity boundary not found'}
$admit=[scriptblock]::Create(($statements-join"`n"))
function Enter-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$ArtifactRoot,$RunDirectory,$CommittedNewBytes,$ProtectedPaths)
 $script:admission=@{bytes=$CommittedNewBytes;protected=@($ProtectedPaths)}
 return @{}
}
$Fly=$false;$Python='INERT';$RepoRoot='INERT';$artifacts='INERT';$OutputDirectory='INERT_NEW_RUN';$ownsCapacity=$true
$downstreamPlan=@{reserved_run_array_payload_bytes=41;frontend_resource_lower_bounds=@{cache_miss_new_disk_payload_bytes_lower_bound=73}}
foreach($reuseMode in @('none','partial','all')){
$reuse=$reuseMode-ne'none'
$floor=if($reuseMode-eq'none'){73}elseif($reuseMode-eq'partial'){37}else{0}
$downstreamPlan.frontend_resource_lower_bounds.cache_miss_new_disk_payload_bytes_lower_bound=$floor
foreach($downstreamReuse in @($false,$true)){
 $receipt=@{input_records=@{}}
 if($reuse){$receipt.input_records.frontend_fields=@{};$receipt.input_records.frontend_fields_manifest=@{source_path=Join-Path $Producer 'run_manifest.json'}}
 if($downstreamReuse){$receipt.input_records.downstream_fields_manifest=@{source_path=Join-Path (Join-Path $Producer 'downstream') 'run_manifest.json'}}
 . $admit
 if($script:admission.bytes-ne(41+$floor)){throw 'incorrect private/cold-cache reservation'}
 $expected=@($OutputDirectory);if($reuse){$expected+=$Producer}
 if($downstreamReuse){$expected+=Join-Path $Producer 'downstream'}
 if(($script:admission.protected-join'|')-ne($expected-join'|')){throw 'source producer protection differs'}
}
}
'FROZEN_FIELD_SOURCE_CAPACITY=PASS'
'''
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'capacity.ps1'
            script.write_text(code, encoding='utf-8', newline='\n')
            producer = Path(directory) / 'producer'
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), str(EXECUTE), str(producer)],
                cwd=REPO, capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('FROZEN_FIELD_SOURCE_CAPACITY=PASS', result.stdout)

    def test_field_design_public_stage_consumes_frozen_plan_and_releases_failure(self):
        """Real public freezer/preparation/budget with explicit inert native boundary."""
        self._check_public_cases(('none','native','population','downstream','elapsed','old_budget','planning','disk_floor','ram_floor',
            'workbench','missing_flight','missing_workbench_budget','workbench_build','workbench_verify','workbench_drift','field_drift','publication_pin'))

    def test_native_stage_uses_one_session_for_standalone_or_borrowed_owner(self):
        for borrowed in (False, True):
            with self.subTest(borrowed=borrowed):
                self._check_public_cases(('none', 'native', 'planning'), borrowed_capacity=borrowed)

    def test_priority_point_marker_is_required_before_public_validation(self):
        self._check_public_cases(('workbench', 'workbench_priority_marker', 'workbench_priority_duplicate', 'workbench_priority_truncated', 'workbench_priority_count'))

    def test_batch_priority_point_evidence_is_bound_before_any_fly(self):
        self._check_public_cases(('fly', 'flight_priority_marker'))

    def test_full_mother_fly_and_default_replay_public_stage(self):
        self._check_public_cases(('fly','missing_fly_budget','missing_replay_budget','flight_ram_floor',
            'flight_native','replay_native','flight_controls','flight_native_controls','flight_marker','flight_mismatch'))

    def test_held_off_workbench_and_fly_guard_only_required_fields(self):
        self._check_public_cases(('workbench_held_off','fly_held_off'))

    def test_refinement_fly_uses_six_fields_and_rejects_insufficient_flight_budget(self):
        self._check_public_cases(('fly_refinement','refinement_flight_ram_floor'))

    def test_local_oatof_complete_mother_uses_two_fields_and_default_replay(self):
        self._check_public_cases(('local_fly',))

    def test_discovery_complete_full_and_local_mothers_then_default_replay(self):
        self._check_public_cases(('discovery_fly','local_discovery_fly'))

    def test_renamed_full_and_local_keep_the_same_oa_source_and_clock(self):
        self._check_public_cases(('discovery_fly','local_discovery_fly'), rename_instances=True)

    def test_discovery_missing_candidates_retains_negative_without_timed_successor(self):
        self._check_public_cases(('discovery_missing',))

    def test_discovery_budget_is_required_before_any_native_boundary(self):
        self._check_public_cases(('missing_discovery_budget',))

    def test_explicit_downstream_source_full_mother_and_default_replay(self):
        self._check_public_cases(('downstream_source_fly',))

    def _assert_pa_guard_lifecycle(self, run, events, *, local, refinement=False, borrowed_downstream=False):
        """Every actual PA has one guard and release, including saved-IOB carriers.

        Published dynamic responses remain direct inputs. Only the carrier of
        each frontend domain and any external downstream slots need transport.
        """
        frontend = json.loads((run/'inputs/inert_field_receipt.json').read_text())
        publication = json.loads((run/'results/single_reflection/downstream_receipt.json').read_text())
        downstream = json.loads(Path(publication['receipt_record']['path']).read_text())
        author = json.loads((run/'inputs/request.json').read_text())
        field_names = ['carrier_off'] if local else ['carrier_off', 'rf_reference']
        if author.get('flight', {}).get('pulse', {}).get('mode') != 'held_off':
            field_names.append('pulse_delta')
        stems = ['frontend', 'frontend_entrance_refinement'] if refinement else ['frontend']
        self.assertEqual([row['domain_id'] for row in frontend['domains']],
                         ['parent', 'entrance_refinement'] if refinement else ['parent'])
        originals = set()
        copies = set()
        for domain, stem in zip(frontend['domains'], stems, strict=True):
            self.assertEqual({Path(row['path']).name for row in domain['working_points']},
                             {f'{stem}.{kind}.pa' for kind in field_names})
            originals.update(Path(row['path']).resolve() for row in domain['working_points'])
            copies.add(run/'simion/iob_fields'/f'{stem}.carrier_off.pa')
        self.assertEqual({asset['role'] for asset in downstream['assets']}, {'flight_tube', 'reflectron', 'detector'})
        manifest = (json.loads((run/'inputs/downstream_field_source_manifest.json').read_text())
                    if borrowed_downstream else None)
        for asset in downstream['assets']:
            records = [asset['carrier_record'], *asset.get('family_records', [])]
            for row in records:
                if manifest is not None:
                    matches = [record for record in manifest['outputs']
                               if Path(record['path']).name == Path(row['path']).name
                               and all(record[key] == row[key] for key in ('bytes', 'sha256'))]
                    self.assertEqual(len(matches), 1, row)
                    originals.add(Path(matches[0]['path']).resolve())
                else:
                    originals.add(Path(row['path']).resolve())
            if borrowed_downstream:
                copies.add(run/'simion/iob_fields'/Path(asset['carrier_record']['path']).name)
        expected = originals | {path.resolve() for path in copies}
        acquired = [Path(line.split(':', 1)[1]).resolve() for line in events.splitlines() if line.startswith('guard_source:')]
        released = [Path(line.split(':', 1)[1]).resolve() for line in events.splitlines() if line.startswith('guard_release_source:')]
        self.assertEqual(Counter(acquired), Counter({path: 1 for path in expected}))
        self.assertEqual(Counter(released), Counter(acquired))
        self.assertEqual(events.count('guard_acquired'), len(acquired))
        self.assertEqual(events.count('guard_released'), len(released))
        for path in expected:
            self.assertTrue(path.is_file(), str(path))
            self.assertIn(path.suffix.lower(), {'.pa', '.pa#', '.pa0', '.pa1', '.pa-surf'})
        self.assertEqual({path.resolve() for path in (run/'simion/iob_fields').iterdir()},
                         {path.resolve() for path in copies})

    def _check_public_cases(self, cases, *, rename_instances=False, borrowed_capacity=False):
        contract=json.loads((REPO/'integrations/config/runtime_dependencies.json').read_text())
        full_source = None
        for failure in cases:
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                discovery = failure in {'discovery_fly','local_discovery_fly','discovery_missing','missing_discovery_budget'}
                local = failure in {'local_fly','local_discovery_fly'}
                if local or discovery:
                    request,empty_run,author,_ = release_fixture(root, instance_id='oatof')
                    if local:
                        author['providers']['instances'].pop('multipole')
                        author['local_scope'] = dict(instance_ids=['oatof'], research_scope='OA birth through detector',
                            boundary_assumptions='Omit upstream multipole metal and fields; retain the actual open side entry.')
                        author['numerics'].pop('rf_reference_voltage_v')
                        author['numerics']['frontend_domains']['parent']['refine_convergence_v'].pop('rf_reference')
                else:
                    request,empty_run,author=fixture(root)
                if rename_instances:
                    rename_author_instances(request, author)
                flight=discovery or failure in {'downstream_source_fly','local_fly','fly','fly_held_off','fly_refinement','refinement_flight_ram_floor','missing_fly_budget','missing_replay_budget','flight_ram_floor','flight_native','replay_native','flight_controls','flight_native_controls','flight_marker','flight_mismatch','flight_priority_marker'}
                workbench=flight or failure in {'workbench','workbench_held_off','missing_flight','missing_workbench_budget','workbench_build','workbench_verify','workbench_drift','field_drift','publication_pin','workbench_priority_marker','workbench_priority_duplicate','workbench_priority_truncated','workbench_priority_count'}
                if workbench and failure!='missing_flight':
                    author['flight']=dict(pulse=dict(mode='held_off') if failure in ('workbench_held_off','fly_held_off') else
                                          dict(mode='timed',time_us=10.,width_us=3.),maximum_flight_us=200.,
                                          maximum_step_us=.001,trajectory_quality=17,rf_steps_per_period=80)
                    if discovery:
                        author['flight']['pulse']=dict(mode='discover',width_us=.1,candidate_times_us=[42.25,42.5])
                    if local:
                        author['flight'].pop('rf_steps_per_period')
                    request.write_text(json.dumps(author),encoding='utf-8',newline='\n')
                domains=author['numerics']['frontend_domains']
                if failure in ('fly_refinement','refinement_flight_ram_floor'):
                    domains['entrance_refinement']={**copy.deepcopy(domains['parent']),'guard_cells':1}
                    request.write_text(json.dumps(author),encoding='utf-8',newline='\n')
                if failure=='downstream_source_fly':
                    from integrations.tests.test_single_reflection_preparation import downstream_field_source_fixture
                    downstream_field_source_fixture(root, request, author)
                counts=[]
                for domain in domains.values():
                    bounds,pitch=domain['pa_bounds_mm'],domain['cell_mm_xyz']
                    counts.append(math.prod(math.ceil((bounds[axis+'_max']-bounds[axis+'_min'])/pitch[axis])+1 for axis in 'xyz'))
                nodes=sum(counts)
                # Inert execution allocates no PA. Budget the direct field
                # construction and the actual private runtime fields honestly.
                field_count = (1 if local else 2) + int(author.get('flight', {}).get('pulse', {}).get('mode') != 'held_off')
                disk_budget=nodes*8*field_count*2+1024**2
                ram_budget=max(20*counts[0],10*nodes,20*counts[1] if len(counts)>1 else 0)+1024**2
                (empty_run/'inputs').rmdir();empty_run.rmdir()
                repo=root/'repo'
                paths={row['source_repo_path'] for group in contract['providers'] for row in group['files']
                       if 'single_reflection_flight' in row['consumers']}
                paths.update({'integrations/config/runtime_dependencies.json','integrations/registry.json',
                              'integrations/runtime/dependencies.ps1','common/contracts/artifact_naming.py'})
                for relative in paths:
                    target=repo/relative;target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(REPO/relative,target)
                # Only the isolated test repository's solver/capacity boundary is inert.
                support=repo/'integrations/workflows/single_reflection_flight/field_stage.ps1'
                support.write_text(r'''
if($env:TEST_FIELD_FAILURE-eq'planning'){
 # Deliberately corrupt only this inert fixture's already-frozen closure.
 $snapshot=Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
 Remove-Item -LiteralPath (Join-Path $snapshot 'projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/oatof_detector_ground.gem')
}
function Enter-ArtifactWorkflowCapacitySession { param($Python,$RepoRoot,$ArtifactRoot,$RunDirectory,$CommittedNewBytes,$ProtectedPaths)
 if($env:TEST_BORROWED_CAPACITY-eq'1'){throw 'borrowed workflow created a second capacity session'}
 [IO.File]::AppendAllText((Join-Path $RunDirectory 'boundary.txt'),"capacity:$CommittedNewBytes`n")
 return @{committed_new_bytes=$CommittedNewBytes;run=$RunDirectory}
}
function Exit-ArtifactWorkflowCapacitySession { param($Python,$RepoRoot,$Session)
 if($env:TEST_BORROWED_CAPACITY-eq'1'){throw 'borrowed workflow exited the owner session'}
 $Session.status='released'
 [IO.File]::AppendAllText((Join-Path $Session.run 'boundary.txt'),"capacity_released`n")
}
function Update-ArtifactWorkflowCapacitySession { param($Python,$RepoRoot,$Session,$RemainingCommittedNewBytes,$ProtectedPaths)
 $Session.committed_new_bytes=$RemainingCommittedNewBytes
 if($ProtectedPaths){[IO.File]::AppendAllText((Join-Path $Session.run 'boundary.txt'),"capacity:$RemainingCommittedNewBytes`n")}
 [IO.File]::AppendAllText((Join-Path $Session.run 'boundary.txt'),"capacity_updated:$RemainingCommittedNewBytes`n")
 return @{session=$Session}
}
function Enter-HostExecutionLease { param($Role,$Stage) [IO.File]::AppendAllText($env:TEST_BOUNDARY,"lease_entered`n");return @{inert=$true} }
function Exit-HostExecutionLease { param($Lease,$Outcome,$RunId)
 [IO.File]::AppendAllText($env:TEST_BOUNDARY,"lease_released:$Outcome`n")
}
function Update-HostResourceStage { param($Lease,$Stage,$Budget,$RetainedMemoryBytes) return $Lease }
function Get-HostResourceBudget { param($Role,$Stage) return @{inert=$true} }
$originalRunContext=${function:Invoke-RunToolRootContext}
function Invoke-RunToolRootContext {
 param($RepoRoot,$Operation)
 # This fixture has inert capacity ownership, so durable pin admission is
 # also an explicit inert boundary, not evidence of a production ledger pin.
 if($Operation.ToString().Contains('Persistent frontend IOB requires')){
   [IO.File]::AppendAllText($env:TEST_BOUNDARY,"publication_pin_checked`n")
   if($env:TEST_FIELD_FAILURE-eq'publication_pin'){throw 'INERT_UNPINNED_GENERATION'}
   return
 }
 $contextTimer=[Diagnostics.Stopwatch]::StartNew()
 $contextLabel=($Operation.ToString().Trim()-split "`n")[0].Trim()
 [Console]::Error.WriteLine("FIXTURE_CONTEXT_START=$contextLabel")
 try { & $originalRunContext -RepoRoot $RepoRoot -Operation $Operation }
 finally { [Console]::Error.WriteLine("FIXTURE_CONTEXT_END=$contextLabel SECONDS=$($contextTimer.Elapsed.TotalSeconds)") }
}
$originalProtect=${function:Protect-ImmutablePaSource}
$originalUnprotect=${function:Unprotect-ImmutablePaSource}
function Protect-ImmutablePaSource {
 param($Source,$ExpectedBytes,$ExpectedSha256)
 $result=& $originalProtect -Source $Source -ExpectedBytes $ExpectedBytes -ExpectedSha256 $ExpectedSha256
 [IO.File]::AppendAllText($env:TEST_BOUNDARY,"guard_acquired`nguard_source:$Source`n")
 return $result
}
function Unprotect-ImmutablePaSource {
 param($Source)
 $result=& $originalUnprotect -Source $Source
 [IO.File]::AppendAllText($env:TEST_BOUNDARY,"guard_released`nguard_release_source:$Source`n")
 return $result
}
function Invoke-ResourceBudgetedProcess {
 param($Limits,$RunDir,$UsagePath,$FilePath,$WorkingDirectory,$ArgumentList,$RedirectStandardOutput,$RedirectStandardError)
 # Explicit inert vendor boundary: these payloads are not usable PA fields.
 $name=[IO.Path]::GetFileName([string]$ArgumentList[3])
 $marker='BUILD: PASS';$code=0
 if($ArgumentList[2]-eq'fly'){
   $phase=Split-Path -Leaf (Split-Path -Parent $RedirectStandardOutput)
   $caseFile=Join-Path $WorkingDirectory workbench.json
   $batch=$null
   if(Test-Path -LiteralPath $caseFile){
    $batch=Get-Content -LiteralPath $caseFile -Raw|ConvertFrom-Json -Depth 100
    if($phase-ne'default_replay'){$phase=if($batch.phase-eq'discovery'){'discovery'}else{'baseline'}}
   }
   [IO.File]::AppendAllText((Join-Path $RunDir 'boundary.txt'),"flight_native:$phase`n")
   if(($env:TEST_FIELD_FAILURE-in@('flight_native','flight_native_controls')-and$phase-eq'baseline')-or
      ($env:TEST_FIELD_FAILURE-eq'replay_native'-and$phase-eq'default_replay')){$code=1}
   # Synthetic native-format data test collection; no physical flight occurs.
   $lines=[Collections.Generic.List[string]]::new()
   $nativeId=0
   $g=if($phase-eq'discovery'){(Get-Content (Join-Path $RunDir 'inputs/frontend_geometry.json') -Raw|ConvertFrom-Json -Depth 100).accelerator_projection}else{$null}
   foreach($row in (Import-Csv (Join-Path $RunDir 'inputs/projected_source.csv'))){
     if($null-ne$batch-and[int]$row.particle_id-notin$batch.expected_particle_ids){continue}
     $nativeId++;$lineStart=$lines.Count
     $id=[int]$row.particle_id
     $time=[double]$row.instrument_time_us
     $state=@($time,$row.position_x_mm,$row.position_y_mm,$row.position_z_mm,
       ([double]$row.velocity_x_m_s/1000),([double]$row.velocity_y_m_s/1000),([double]$row.velocity_z_m_s/1000))|
       ForEach-Object{([double]$_).ToString('G17',[Globalization.CultureInfo]::InvariantCulture)}
     $lines.Add(('TRACE: source_release ion={0} particle_id={0} instrument_time_us={1} x_mm={2} y_mm={3} z_mm={4} vx_mm_per_us={5} vy_mm_per_us={6} vz_mm_per_us={7}'-f$id,@($state)[0],@($state)[1],@($state)[2],@($state)[3],@($state)[4],@($state)[5],@($state)[6]))
     if($phase-eq'discovery'-and$env:TEST_FIELD_FAILURE-ne'discovery_missing'){
       # Explicit synthetic accepted native states inside the actual OA first
       # gap, not a real solver trajectory or a source replacement.
       $sx=([double]$g.axis_x_mm+.01*($id%3-1)).ToString('G17',[Globalization.CultureInfo]::InvariantCulture)
       $sy=([double]$g.axis_y_mm+.01*($id%5-2)).ToString('G17',[Globalization.CultureInfo]::InvariantCulture)
       foreach($candidate in @(42.25,42.5)){
         $t=$candidate.ToString('G17',[Globalization.CultureInfo]::InvariantCulture)
         $sz=(([double]$g.repeller_front_z_mm+[double]$g.grid1_z_mm)/2+.01*($id%7-3)).ToString('G17',[Globalization.CultureInfo]::InvariantCulture)
         $lines.Add(('TRACE: native_shared_time ion={0} particle_id={0} candidate_time_us={1} instrument_time_us={1} x_mm={2} y_mm={3} z_mm={4} vx_mm_per_us={5} vy_mm_per_us={6} vz_mm_per_us={7} kinetic_energy_eV=2 instance=3'-f$id,$t,$sx,$sy,$sz,$state[4],$state[5],$state[6]))
       }
     }
     $end=($time+1).ToString('G17',[Globalization.CultureInfo]::InvariantCulture)
     $lines.Add(('TRACE: handoff_terminal_raw ion={0} instance=3 instrument_time_us={1} x_mm={2} y_mm={3} z_mm={4} vx_mm_per_us={5} vy_mm_per_us={6} vz_mm_per_us={7}'-f$id,$end,$state[1],$state[2],$state[3],$state[4],$state[5],$state[6]))
     $x=if($phase-eq'default_replay'-and$env:TEST_FIELD_FAILURE-eq'flight_mismatch'-and$id-eq1){'999'}else{$state[1]}
     $lines.Add(('TRACE: non_detector_splat ion={0} instance=3 t={1} x={2} y={3} z={4} zmax={4}'-f$id,$end,$x,$state[2],$state[3]))
     for($lineIndex=$lineStart;$lineIndex-lt$lines.Count;$lineIndex++){$lines[$lineIndex]=$lines[$lineIndex]-replace ('(?<!\w)ion='+$id+'(?=\s)'),('ion='+$nativeId)}
   }
   if($env:TEST_FIELD_FAILURE-ne'flight_marker'){$lines.Add("status,Fly completed. $nativeId splats")}
   $marker=$lines-join"`n"
   if($env:TEST_FIELD_FAILURE-in@('flight_controls','flight_native_controls')){
     [IO.File]::AppendAllText((Join-Path $WorkingDirectory 'instrument.lua'),'DRIFT')
   }
 }elseif($name-eq'build_iob.lua'){
   if($ArgumentList.Count-eq6){
     $operation='verify';$marker='SINGLE_REFLECTION_IOB_REOPEN=PASS'
     $casePath=Join-Path $WorkingDirectory 'workbench.json'
     if(-not(Test-Path $casePath)){$casePath=Join-Path $RunDir 'results/single_reflection/workbench_preparation.json'}
     $counts=(Get-Content $casePath -Raw|ConvertFrom-Json -Depth 100).native_priority_occupancy_expected_counts
     $pointMarker="SINGLE_REFLECTION_NATIVE_PRIORITY_OCCUPANCY=PASS CHECKED=$($counts.checked_points) OBSERVED=$($counts.observation_only_points) SCOPE=declared_points_only"
     if($env:TEST_FIELD_FAILURE-notin@('workbench_priority_marker','flight_priority_marker')){$marker+="`n$pointMarker"}
     if($env:TEST_FIELD_FAILURE-eq'workbench_priority_duplicate'){$marker+="`n$pointMarker"}
     if($env:TEST_FIELD_FAILURE-eq'workbench_priority_truncated'){$marker=$marker.Replace($pointMarker,'SINGLE_REFLECTION_NATIVE_PRIORITY_OCCUPANCY=PASS CHECKED=2')}
     if($env:TEST_FIELD_FAILURE-eq'workbench_priority_count'){$marker=$marker.Replace("CHECKED=$($counts.checked_points)",'CHECKED=1')}
   }
   else{$operation='build';$marker='SINGLE_REFLECTION_IOB=PASS'}
   if($operation-eq'build'){[IO.File]::WriteAllText((Join-Path $WorkingDirectory 'instrument.iob'),'INERT_IOB_NOT_NATIVE')}
   if($env:TEST_FIELD_FAILURE-eq"workbench_$operation"){$code=1;$marker='INERT_IOB_FAILURE'}
   if($env:TEST_FIELD_FAILURE-eq'workbench_drift'-and$operation-eq'verify'){
     [IO.File]::AppendAllText((Join-Path $WorkingDirectory 'instrument.lua'),'DRIFT')
   }
   [IO.File]::AppendAllText((Join-Path $RunDir 'boundary.txt'),"workbench_native:$operation`n")
 }elseif($name-eq'export_standalone_pa.lua'){
   [IO.File]::WriteAllText([string]$ArgumentList[5],'INERT_NOT_PA');$marker='STANDALONE_PA_EXPORT=PASS'
 }elseif($name-eq'audit_downstream_fields.lua'){
   $plan=Get-Content (Join-Path $WorkingDirectory 'command_plan.json') -Raw|ConvertFrom-Json -Depth 100
   $rows=@($plan.assets|ForEach-Object{@{role=$_.role;grid=$_.grid}})
   Write-RunJson -Path $plan.audit_output -Value @{role='single_reflection_downstream_native_audit';status='success';checked_assets=$rows} -Depth 100
   $marker='DOWNSTREAM_NATIVE_AUDIT=PASS'
 }else{
   $stem=([string]$ArgumentList[5])-replace '\.pa#$',''
   foreach($suffix in @('.pa#','.pa0','.pa1','.pa-surf')){
     if($name-eq'build_reflectron_variant.lua'-and$suffix-eq'.pa-surf'){continue}
     [IO.File]::WriteAllText($stem+$suffix,'INERT_NOT_PA')
   }
 }
 if($env:TEST_FIELD_FAILURE-eq'downstream'){$code=1;$marker='INERT_NATIVE_FAILURE'}
 [IO.File]::WriteAllText($RedirectStandardOutput,$marker)
 [IO.File]::WriteAllText($RedirectStandardError,'')
 Write-RunJson -Path $UsagePath -Value @{role='multipole_resource_usage';status=$(if($code){'process_failed'}else{'running'});failure_class=$null;limit_name=$null;peak_run_directory_bytes=0;inert_limit_seconds=$Limits.wall_clock_seconds}
 [IO.File]::AppendAllText((Join-Path $RunDir 'boundary.txt'),"inert_downstream:$name`n")
 return @{exit_code=$code;resource_budget_exceeded=$false}
}
$script:originalFrontendRuntime=${function:Invoke-FrontendRuntimePython}
function Invoke-FrontendRuntimePython {
 param($Python,$RepoRoot,$RunDirectory,$Name,$Arguments,[switch]$Json)
 if($Name-like'*.resource-profile-discover'-or$Name-like'*.resource-profile-publish'){return}
 if($Name-like'*.dispatch-plan'-or$Name-like'*.dispatch-followup'){
  $observed=$Name-like'*.dispatch-followup'
  $phase=$Name.Split('.')[0]
  $count=@(Import-Csv (Join-Path $RunDirectory inputs/projected_source.csv)).Count
  $first=[Math]::Max(1,[int][Math]::Ceiling($count/10))
  $batches=@(@{index=1;count=$first;particle_id_min=1;particle_id_max=$first;simion_particle_id_offset=0})
  if($observed){
   $middle=$first+[int][Math]::Ceiling(($count-$first)/2)
   if($middle-gt$first){$batches+=@{index=2;count=$middle-$first;particle_id_min=$first+1;particle_id_max=$middle;simion_particle_id_offset=$first}}
   if($middle-lt$count){$batches+=@{index=3;count=$count-$middle;particle_id_min=$middle+1;particle_id_max=$count;simion_particle_id_offset=$middle}}
  }
  Write-RunJson -Path (Join-Path $RunDirectory "results/$phase.dispatch_plan.json") -Depth 100 -Value @{
   role='simion_repository_dispatch_plan';particle_count=$count;estimation=@{kind=$(if($observed){'observed'}else{'formal_first_batch_observation'})};
   waves=@(@{coverage=$(if($observed){'complete_population'}else{'initial_formal_batch_only'});batches=$batches})}
  [IO.File]::AppendAllText((Join-Path $RunDirectory boundary.txt),"dispatch:$Name`n")
  return
 }
 $timer=[Diagnostics.Stopwatch]::StartNew()
 [Console]::Error.WriteLine("FIXTURE_RUNTIME_START=$Name")
 try { return & $script:originalFrontendRuntime @PSBoundParameters }
 finally { [Console]::Error.WriteLine("FIXTURE_RUNTIME_END=$Name SECONDS=$($timer.Elapsed.TotalSeconds)") }
}
function Start-ObservedFormalProcess {
 param($DispatchPlanPath,$ProcessSpecification,[switch]$WaitForNaturalCompletionAfterObservation)
 $run=Split-Path -Parent (Split-Path -Parent $DispatchPlanPath)
 [IO.File]::AppendAllText((Join-Path $run boundary.txt),"observed_first_batch`n")
 $spec=$ProcessSpecification
 $native=Invoke-ResourceBudgetedProcess -Limits @{wall_clock_seconds=90} -RunDir $run -UsagePath (Join-Path $run results/observed.resource_usage.json) `
  -FilePath $spec.file_path -WorkingDirectory $spec.working_directory -ArgumentList $spec.argument_list `
  -RedirectStandardOutput $spec.stdout -RedirectStandardError $spec.stderr
 return @{process_record=@{name=$spec.name;completed=$true;exit_code=$native.exit_code};completed_naturally=$true;resource_budget_exceeded=$false;exit_code=$native.exit_code;
  observed_peak_process_tree_working_set_bytes=1024;observed_process_cpu_percent=5;observed_background_cpu_percent=0;available_memory_bytes=1000000000;total_physical_memory_bytes=2000000000}
}
function Invoke-ResourceBudgetedProcesses {
 param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications,$ExistingProcessRecords=@())
 $records=@($ExistingProcessRecords)
 [IO.File]::AppendAllText((Join-Path $RunDir boundary.txt),"scheduled_wave:$(@($ProcessSpecifications).Count)`n")
 foreach($spec in $ProcessSpecifications){
  $native=Invoke-ResourceBudgetedProcess -Limits @{wall_clock_seconds=90} -RunDir $RunDir -UsagePath $UsagePath `
   -FilePath $spec.file_path -WorkingDirectory $spec.working_directory -ArgumentList $spec.argument_list `
   -RedirectStandardOutput $spec.stdout -RedirectStandardError $spec.stderr
  $records+=@{name=$spec.name;completed=$true;exit_code=$native.exit_code}
 }
 Write-RunJson -Path $UsagePath -Value @{role='multipole_resource_usage';status='running';failure_class=$null;limit_name=$null;peak_run_directory_bytes=0}
 return @{processes=$records;resource_budget_exceeded=$false}
}
function Invoke-SingleReflectionFrontendFieldStage {
 param($Python,$RepoRoot,$RunDirectory,$PreparedDirectory,$SimionExe,$HostLease,$CapacitySession,$Limits,$CacheRoot,$StageElapsed,$ReservedRunPayloadBytes)
 if($RepoRoot-notlike'*runtime_snapshot'){throw 'LIVE_SOURCE_FALLBACK'}
 if($env:TEST_BORROWED_CAPACITY-eq'1'-and($CapacitySession.Value.lease_id-ne'owner-lease'-or$CapacitySession.Value.owner-ne'owner-workflow')){throw 'field stage changed the owner capacity identity'}
 $plan=Get-Content (Join-Path $PreparedDirectory 'inputs/frontend_field_design.json') -Raw|ConvertFrom-Json -Depth 100
 $local=$env:TEST_FIELD_FAILURE-in@('local_fly','local_discovery_fly')
 $sampleCount=if($local){25}else{59}
 $author=Get-Content (Join-Path $PreparedDirectory 'inputs/request.json') -Raw|ConvertFrom-Json -AsHashtable
 $pulseMode=if($author.ContainsKey('flight')){$author.flight.pulse.mode}else{''}
 $fieldCount=$(if($local){1}else{2})+$(if($pulseMode-eq'held_off'){0}else{1})
 if($plan.domains[0].physical_samples.Count-ne$sampleCount-or$plan.working_points.Count-ne$fieldCount){throw 'INCOMPLETE_PHYSICAL_INPUTS'}
 if($ReservedRunPayloadBytes-lt0){throw 'NEGATIVE_RUN_PAYLOAD_RESERVATION'}
 if(Test-Path (Join-Path $PreparedDirectory 'inputs/frontend.pa+')){throw 'UNNECESSARY_PA_PLUS'}
 [IO.File]::AppendAllText((Join-Path $RunDirectory 'boundary.txt'),"frozen_field_design_consumed`n")
 if($null-eq$StageElapsed){throw 'MISSING_SHARED_STAGE_CLOCK'}
 if($env:TEST_FIELD_FAILURE-eq'elapsed'){Start-Sleep -Milliseconds 1200}
 if($env:TEST_FIELD_FAILURE-eq'native'){throw 'CONTROLLED_NATIVE_BOUNDARY_FAILURE'}
 if($env:TEST_WORKBENCH-eq'1'){
  $code=@'
import json,sys,stat
from pathlib import Path
from common.contracts.write_run_manifest import file_record
from common.simion.pa_family_cache import publish_pa_family_cache
from integrations.workflows.single_reflection_flight.field_plan import build_field_plan,bind_parent_fields,field_bank
run,exe,repo=map(Path,sys.argv[1:]);plan=build_field_plan(run/'inputs',exe,repo)
out=run/'simion/frontend_fields';out.mkdir(parents=True)
write=lambda p,v:p.write_text(json.dumps(v),encoding='utf-8',newline='\n')
domains=[];parent_fields={}
for unbound in plan['domains']:
    domain=bind_parent_fields(unbound,parent_fields) if unbound['domain_id']=='entrance_refinement' else unbound
    records=[]
    for member in domain['members']:
        point=member['working_points'][0]
        identity=run/'inputs'/('inert_'+domain['domain_id']+'_'+member['member_id']+'_identity.json')
        write(identity,member['identity'])
        payload=run.parent/'inert_staging'/domain['domain_id']/member['member_id'];payload.mkdir(parents=True)
        p=payload/point['filename'];p.write_bytes(b'INERT_NOT_A_PA');p.chmod(stat.S_IREAD)
        publication=publish_pa_family_cache(run.parent/'inert_cache',member['identity'],payload,member['filenames'],recovery_policy='none')
        audit=run/'inputs'/('inert_'+domain['domain_id']+'_'+member['member_id']+'_audit.json')
        write(audit,dict(status='pass',fixture='not native evidence'))
        record=dict(file_record(publication.generation_directory/p.name),kind=point['kind'],read_only=True,
            cache_key=member['cache_key'],generation_directory=str(publication.generation_directory),
            cache_identity_record=file_record(identity),cache_filenames=member['filenames'],source_schema_version=3,audit_record=file_record(audit))
        if point.get('working_point_id'): record['working_point_id']=point['working_point_id']
        records.append(record)
        if domain['domain_id']=='parent': parent_fields[member['member_id']]=dict(cache_key=record['cache_key'],record=record)
    domains.append(dict(domain_id=domain['domain_id'],working_points=records))
reference=plan.get('rf_reference_voltage_v')
bank=out/'bank.json';write(bank,field_bank(json.loads((run/'inputs/frontend_field_design.json').read_text()),[row['domain_id'] for row in domains]))
receipt=run/'inputs/inert_field_receipt.json'
write(receipt,dict(schema_version=3,role='single_reflection_frontend_working_fields',status='success',
    domains=domains,field_bank_record=file_record(bank),**({'rf_reference_voltage_v':reference} if reference is not None else {})))
print(json.dumps(dict(cache_receipt=str(receipt))))
'@
  $result=Invoke-RunToolRootContext -RepoRoot $RepoRoot -Operation {
    $raw=& $Python -B -c $code $RunDirectory $SimionExe $RepoRoot
    if($LASTEXITCODE-ne0){throw 'INERT_FIELD_PUBLICATION_FAILED'}
    return $raw|ConvertFrom-Json -AsHashtable
  }
  if($env:TEST_FIELD_FAILURE-eq'field_drift'){
    $value=Get-Content $result.cache_receipt -Raw|ConvertFrom-Json -AsHashtable
    $value.domains[0].working_points[0].cache_key='0'*64;Write-RunJson -Path $result.cache_receipt -Value $value -Depth 100
  }
  return $result
 }
 return @{scope='INERT_NATIVE_BOUNDARY_ONLY';fly_performed=$false}
}
''',encoding='utf-8',newline='\n')
                budget=root/'budget.json'
                budget_document=dict(schema_version=2,role='integration_resolved_engineering_budget',
                    integration_id='instrument_assembly',workflow_id='single_reflection_flight',retention_class='solver_review',
                    particle_count=99 if failure=='population' else 100,stage_limits={('frontend_field_design' if failure=='old_budget' else 'instrument_field_design'):dict(
                        solver='simion',automatic_retry_count=0,wall_clock_seconds=1 if failure=='elapsed' else 60,transient_run_directory_bytes=1 if failure=='disk_floor' else disk_budget,
                        process_tree_working_set_bytes=1 if failure=='ram_floor' else ram_budget,minimum_system_available_memory_bytes=1000000,
                        compact_final_retained_bytes=1000000)})
                if workbench and failure!='missing_workbench_budget':
                    budget_document['stage_limits']['instrument_workbench_preparation']=dict(
                        budget_document['stage_limits']['instrument_field_design'],wall_clock_seconds=90)
                if flight:
                    for stage,missing in (('instrument_flight','missing_fly_budget'),('instrument_default_replay','missing_replay_budget')):
                        if failure!=missing:
                            budget_document['stage_limits'][stage]=dict(
                                budget_document['stage_limits']['instrument_field_design'],wall_clock_seconds=90,
                                process_tree_working_set_bytes=nodes*10*field_count+(0 if failure in ('flight_ram_floor','refinement_flight_ram_floor') else 1024**2))
                if discovery and failure!='missing_discovery_budget':
                    budget_document['stage_limits']['instrument_pulse_discovery']=dict(
                        budget_document['stage_limits']['instrument_flight'])
                budget.write_text(json.dumps(budget_document),encoding='utf-8',newline='\n')
                fake_exe=root/'ProgramFiles/SIMION-2020/simion.exe';fake_exe.parent.mkdir(parents=True)
                fake_exe.write_bytes(b'INERT_NOT_EXECUTABLE')
                script=root/'run.ps1'
                script.write_text(r'''
param($ActualRepo,$Repo,$Python,$Root,$Request,$Budget)
. (Join-Path $ActualRepo 'common/contracts/run_artifact_support.ps1')
$package=New-RunPackage -Python $Python -RepoRoot $ActualRepo -ArtifactRoot (Join-Path $Root 'packages') `
 -RunId '20261023_010001__build__simion__single-reflection-test' -Project instrument_assembly `
 -Mode single_reflection_field_design -Software @('Python 3.11')
$env:TEST_BOUNDARY=Join-Path $package.run_dir 'boundary.txt'
$selection=if($env:TEST_FLY-eq'1'){@{Fly=$true}}elseif($env:TEST_WORKBENCH-eq'1'){@{WorkbenchOnly=$true}}else{@{FieldDesignOnly=$true}}
if($env:TEST_BORROWED_CAPACITY-eq'1'){
 $ownerSession=[pscustomobject]@{status='active';committed_new_bytes=0;run=$package.run_dir;lease_id='owner-lease';owner='owner-workflow'}
 $selection.WorkflowCapacitySession=$ownerSession
}
try {
& (Join-Path $Repo 'integrations/workflows/single_reflection_flight/execute.ps1') `
 -Request $Request @selection -OutputDirectory $package.run_dir -ExecutionBudgetPath $Budget -RepoRoot $Repo -Python $Python
} finally {
 if($env:TEST_BORROWED_CAPACITY-eq'1'){
   if($ownerSession.status-ne'active'-or$ownerSession.committed_new_bytes-ne0){throw 'borrowed session was released or retained payload commitment'}
   [IO.File]::AppendAllText($env:TEST_BOUNDARY,"borrowed_session_retained`n")
   # Only this caller owns its inert session. execute's solver-boundary mocks
   # are child-script scoped; never pass this fixture object to the real ledger.
   $ownerSession.status='released'
   [IO.File]::AppendAllText($env:TEST_BOUNDARY,"capacity_released`n")
 }
}
''',encoding='utf-8',newline='\n')
                env=dict(os.environ,ProgramFiles=str(root/'ProgramFiles'),TEST_FIELD_FAILURE=failure,
                         TEST_WORKBENCH='1' if workbench else '0',TEST_FLY='1' if flight else '0',
                         TEST_BORROWED_CAPACITY='1' if borrowed_capacity else '0')
                # The public fixture runs complete phases, each containing real
                # Python contract boundaries. Scale the former total 90-second
                # fixture window by the actual expected number of phases.
                complete_flight = failure in {
                    'downstream_source_fly','local_fly','fly','fly_held_off','fly_refinement',
                    'discovery_fly','local_discovery_fly','replay_native','flight_mismatch'}
                phase_count = (3 if discovery else 2) if complete_flight else 1
                fixture_timeout = 90 * phase_count
                command=['pwsh','-NoProfile','-File',str(script),str(REPO),str(repo),sys.executable,
                         str(root),str(request),str(budget)]
                stdout_path,stderr_path=root/'fixture.stdout.log',root/'fixture.stderr.log'
                try:
                    completed,_=run_observed_process(command,cwd=REPO,stdout=stdout_path,
                        stderr=stderr_path,environment=env,hard_deadline_seconds=fixture_timeout,
                        hard_deadline_action='terminate_process_tree')
                except subprocess.TimeoutExpired:
                    stdout=stdout_path.read_text(encoding='utf-8',errors='replace')
                    stderr=stderr_path.read_text(encoding='utf-8',errors='replace')
                    self.fail(f'{failure} timed out after {fixture_timeout}s ({phase_count} phases); '
                              f'public observer reaped fixture tree.\n{stdout}\n{stderr}')
                result=subprocess.CompletedProcess(command,completed.returncode,
                    stdout_path.read_text(encoding='utf-8',errors='replace'),
                    stderr_path.read_text(encoding='utf-8',errors='replace'))
                if discovery:
                    print(result.stderr,flush=True)
                self.assertEqual(result.returncode==0,failure in ('downstream_source_fly','none','elapsed','workbench','workbench_held_off','local_fly','fly','fly_held_off','fly_refinement','discovery_fly','local_discovery_fly'),result.stdout+result.stderr)
                run=next((root/'packages/runs').iterdir())
                if borrowed_capacity:
                    lifecycle=(run/'boundary.txt').read_text()
                    self.assertIn('borrowed_session_retained',lifecycle)
                    self.assertEqual(lifecycle.count('capacity_released'),1)
                config=json.loads((run/'run_config.json').read_text())
                values=list(config['inputs'].values())
                self.assertEqual(len(values),len(set(values)))
                if failure.startswith('workbench_priority_'):
                    self.assertIn('point evidence missing', result.stderr)
                    events=(run/'boundary.txt').read_text()
                    self.assertIn('lease_released', events)
                    self.assertIn('capacity_released', events)
                    self._assert_pa_guard_lifecycle(run, events, local=local)
                    self.assertNotIn('flight_native:', events)
                    self.assertNotIn('SINGLE_REFLECTION_WORKBENCH=PASS', result.stdout)
                    failed_workbench=json.loads((run/'results/single_reflection/workbench_preparation.json').read_text())
                    self.assertEqual(failed_workbench['native_validation']['status'], 'failed')
                    point_evidence=failed_workbench['native_validation']['native_priority_occupancy_validation']
                    self.assertEqual(point_evidence['status'], 'failed')
                    self.assertEqual(point_evidence['checked_points'], 0)
                    self.assertEqual(point_evidence['observation_only_points'], 0)
                    continue
                self.assertIn(str(run/'inputs/resolved_integration_engineering_budget.json'),values)
                if rename_instances:
                    geometry=json.loads((run/'inputs/frontend_geometry.json').read_text())
                    selected=set(geometry['composition_plan']['scope']['instance_ids'])
                    self.assertEqual(selected, {'tof_b'} if local else {'guide_a','tof_b'})
                    provenance=json.loads((run/'inputs/source_provenance.json').read_text())
                    self.assertEqual(provenance['source_instance_id'], 'tof_b')
                    source=tuple((run/'inputs'/name).read_bytes() for name in
                                 ('projected_source.csv','clock_authority.json','instrument_epoch.json'))
                    if local:
                        self.assertEqual(source, full_source)
                    else:
                        full_source=source
                if discovery:
                    if failure=='missing_discovery_budget':
                        self.assertIn('omits stage: instrument_pulse_discovery',result.stderr)
                        self.assertFalse((run/'boundary.txt').exists())
                        self.assertFalse((run/'simion/discovery').exists())
                        continue
                    events=(run/'boundary.txt').read_text()
                    self.assertIn('lease_released',events);self.assertIn('capacity_released',events)
                    self._assert_pa_guard_lifecycle(run, events, local=local)
                    self.assertEqual(events.count('frozen_field_design_consumed'),1)
                    decision=json.loads((run/'results/single_reflection/discovery/pulse_decision.json').read_text())
                    off=json.loads((run/'results/single_reflection/discovery_workbench_preparation.json').read_text())
                    collection=json.loads((run/'results/single_reflection/discovery/collection.json').read_text())
                    self.assertIn(str(run/'results/single_reflection/discovery/collection.json'),values)
                    self.assertEqual(off['phase'],'discovery')
                    self.assertEqual(off['particle_count'],100)
                    self.assertTrue(collection['native_complete'])
                    self.assertEqual(len(collection['native_terminals']),100)
                    self.assertEqual({r['particle_id'] for r in collection['native_terminals']},set(range(1,101)))
                    self.assertEqual({r['instrument_time_us'] for r in collection['canonical_events'] if r['event']=='source_release'},{42.125})
                    self.assertEqual(off['flight']['pulse'],dict(mode='held_off'))
                    self.assertTrue(all(case['flight']==off['flight'] for case in off['batches']))
                    self.assertFalse(list((run/'simion').rglob('flight.json')))
                    self.assertNotIn('adjustable handoff_pulse_time_us',Path(off['batches'][0]['outputs']['program']['path']).read_text())
                    records=json.loads((run/'results/single_reflection/flight_execution_records.json').read_text())
                    expected=['discovery']*3 if failure=='discovery_missing' else ['discovery']*3+['baseline']*3+['default_replay']*3
                    self.assertEqual([r['phase'] for r in records],expected)
                    self.assertEqual(events.count('flight_native:'),len(expected))
                    self.assertTrue(all(r['controls_unchanged'] for r in records))
                    self.assertEqual(events.count('flight_native:discovery'),3)
                    self.assertEqual(off['source_record'],collection['source_record'])
                    if failure=='discovery_missing':
                        self.assertEqual(decision['status'],'no_supported_candidate')
                        self.assertNotIn('actual_pulse_time_us',decision)
                        self.assertFalse((run/'simion/full_instrument').exists())
                        self.assertFalse((run/'results/single_reflection/baseline').exists())
                        self.assertEqual(collection['native_shared_states'],[])
                        self.assertIn('no supported pulse candidate',result.stderr)
                        self.assertEqual(events.count('workbench_native:'),6)
                    else:
                        self.assertEqual(decision['status'],'success')
                        self.assertIn(decision['actual_pulse_time_us'],[42.25,42.5])
                        self.assertEqual(len(collection['native_shared_states']),200)
                        timed=json.loads((run/'results/single_reflection/workbench_preparation.json').read_text())
                        self.assertEqual(off['pa_guard_records'],timed['pa_guard_records'])
                        self.assertEqual(off['source_record'],timed['source_record'])
                        self.assertNotEqual(off['batches'][0]['iob_path'],timed['batches'][0]['iob_path'])
                        self.assertEqual(Path(off['batches'][0]['outputs']['particles']['path']).read_bytes(),Path(timed['batches'][0]['outputs']['particles']['path']).read_bytes())
                        self.assertEqual(events.count('workbench_native:'),12)
                        self.assertEqual(timed['flight']['pulse'],
                                         dict(mode='timed',time_us=decision['actual_pulse_time_us'],width_us=.1))
                        self.assertTrue(all(case['flight']==timed['flight'] for case in timed['batches']))
                        replay=json.loads((run/'results/single_reflection/default_replay/replay_comparison.json').read_text())
                        self.assertTrue(replay['passed'])
                        self.assertEqual(replay['execution_cohort_count'],100)
                        self.assertIn('SINGLE_REFLECTION_FLIGHT=PASS DEFAULT_REPLAY=PASS',result.stdout)
                    # Only one set of the actual frontend working fields exists.
                    self.assertEqual(list((run/'simion/frontend_fields').glob('*.pa')), [])
                    continue
                if workbench:
                    if failure in ('missing_flight','missing_workbench_budget','missing_fly_budget','missing_replay_budget','flight_ram_floor','refinement_flight_ram_floor'):
                        self.assertFalse((run/'boundary.txt').exists())
                        expected_error={'missing_flight':'native flight','missing_workbench_budget':'omits stage: instrument_workbench_preparation',
                                        'missing_fly_budget':'omits stage: instrument_flight','missing_replay_budget':'omits stage: instrument_default_replay',
                                        'flight_ram_floor':'frontend working-field RAM lower bound',
                                        'refinement_flight_ram_floor':'frontend working-field RAM lower bound'}[failure]
                        self.assertIn(expected_error,result.stderr)
                        continue
                    events=(run/'boundary.txt').read_text()
                    self.assertIn('lease_released',events);self.assertIn('capacity_released',events)
                    if failure=='publication_pin':
                        self.assertIn('INERT_UNPINNED_GENERATION', result.stderr)
                        self.assertIn('publication_pin_checked', events)
                        self.assertNotIn('workbench_native:', events)
                        self.assertNotIn('guard_acquired', events)
                        continue
                    if failure=='field_drift':
                        self.assertNotIn('workbench_native:',events)
                        self.assertFalse((run/'simion/full_instrument').exists())
                        continue
                    if failure=='downstream_source_fly':
                        # The three external downstream carriers and frontend
                        # carrier share one persistent copy per slot across batches.
                        self.assertEqual(events.count('capacity_updated:'),5)
                        self.assertEqual([line for line in events.splitlines() if line.startswith('inert_downstream:')],
                            ['inert_downstream:build_iob.lua','inert_downstream:build_iob.lua','inert_downstream:instrument.iob']+['inert_downstream:build_iob.lua']*4+['inert_downstream:instrument.iob']*5)
                        self.assertFalse((run/'simion/downstream_fields').exists())
                        self.assertFalse((run/'results/single_reflection/downstream_execution_records.json').exists())
                        for key in ('downstream_field_source_receipt.json','downstream_field_source_manifest.json','downstream_field_source_command_plan.json'):
                            self.assertIn(str(run/'inputs'/key),values)
                    if failure=='flight_priority_marker':
                        self.assertNotIn('flight_native:',events)
                        self.assertIn('point evidence missing',result.stderr)
                        case_path=next((run/'simion/full_instrument').rglob('workbench.json'))
                        case=json.loads(case_path.read_text())
                        verify=case['native_workbench_execution'][-1]
                        self.assertEqual(verify['operation'],'verify')
                        self.assertNotIn('native_priority_occupancy_validation',verify)
                        continue
                    self._assert_pa_guard_lifecycle(run, events, local=local,
                        refinement=failure=='fly_refinement', borrowed_downstream=failure=='downstream_source_fly')
                    if flight:
                        self.assertIn('observed_first_batch',events)
                        self.assertNotIn('instrument.iob\nflight_native:gui',events)
                        published_path=run/'results/single_reflection/workbench_preparation.json'
                        if not published_path.exists():
                            self.assertIn(failure,('flight_native','flight_native_controls','flight_controls'))
                            cases=list((run/'simion/full_instrument').rglob('workbench.json'))
                            self.assertEqual(len(cases),3 if failure=='flight_controls' else 1)
                            self.assertTrue(all(str(case) in values for case in cases))
                            self.assertTrue(list((run/'results').glob('*.stdout.log')))
                            continue
                        published_workbench=json.loads(published_path.read_text())
                        self.assertEqual(len(published_workbench['batches']),3)
                        self.assertEqual([pid for case in published_workbench['batches'] for pid in case['expected_particle_ids']],list(range(1,101)))
                        self.assertIsNone(published_workbench['gui_case'])
                        self.assertEqual(events.count('workbench_native:'),6)
                        self.assertTrue(published_workbench['native_execution_performed'])
                        success=failure in ('downstream_source_fly','local_fly','fly','fly_held_off','fly_refinement')
                        self.assertEqual(published_workbench['flight_validation']['status'],'success' if success else 'failed')
                        if success:
                            self.assertTrue(all(row['native_priority_occupancy_validation']['status']=='success'
                                for case in published_workbench['batches']
                                for row in case['native_workbench_execution'] if row['operation']=='verify'))
                            self.assertIn('scheduled_wave:2',events)
                            self.assertIn('scheduled_wave:3',events)
                            self.assertEqual(events.count('flight_native:'),6)
                            comparison=json.loads((run/'results/single_reflection/default_replay/replay_comparison.json').read_text())
                            self.assertTrue(comparison['passed'])
                            self.assertEqual(comparison['execution_cohort_count'],100)
                            self.assertEqual(published_workbench['flight_validation']['completed_collection_count'],2)
                            self.assertIn('SINGLE_REFLECTION_FLIGHT=PASS DEFAULT_REPLAY=PASS',result.stdout)
                        else:
                            self.assertTrue(result.stderr)
                            self.assertTrue(list((run/'logs').glob('*.stdout.log')))
                        continue
                    self.assertEqual(events.count('publication_pin_checked'), 1)
                    expected=['build'] if failure=='workbench_build' else ['build','verify']
                    evidence=json.loads((run/'results/single_reflection/workbench_execution_records.json').read_text())
                    self.assertEqual([row['operation'] for row in evidence],expected)
                    self.assertEqual(events.count('workbench_native:'),len(expected))
                    published_workbench=json.loads((run/'results/single_reflection/workbench_preparation.json').read_text())
                    self.assertTrue(published_workbench['native_execution_performed'])
                    self.assertFalse(published_workbench['fly_ready'])
                    self.assertNotIn('actual_field_overlap_validated',published_workbench['native_validation'])
                    priority=published_workbench['native_validation']['native_priority_occupancy_validation']
                    self.assertEqual(priority['status'],'success' if flight or failure in ('workbench','workbench_held_off') else 'failed')
                    self.assertIn('not_dynamic_fields_continuity',priority['scope'])
                    self.assertEqual(published_workbench['native_validation']['status'],'success' if flight or failure in ('workbench','workbench_held_off') else 'failed')
                    self.assertNotIn('flight',published_workbench['inputs'])
                    self.assertFalse(list(run.rglob('flight.json')))
                    if failure in ('workbench','workbench_held_off'):
                        self.assertIn('SINGLE_REFLECTION_WORKBENCH=PASS FLY_EXECUTED=False',result.stdout)
                        self.assertEqual(published_workbench['pending_validation'],['real_full_population_flight_validation'])
                        self.assertIn('iob',published_workbench['outputs'])
                        self.assertEqual(published_workbench['flight'],author['flight'])
                        from integrations.runtime.single_flight_source import render_restart_fly2
                        import csv
                        with (run/'inputs/projected_source.csv').open(newline='') as stream:
                            rows=list(csv.DictReader(stream))
                        self.assertEqual(len(rows),100)
                        self.assertEqual([int(row['particle_id']) for row in rows],list(range(1,101)))
                        self.assertEqual((run/'simion/full_instrument/instrument.fly2').read_text(),render_restart_fly2(rows))
                    continue
                if failure in ('population','old_budget','planning','disk_floor','ram_floor'):
                    self.assertIn({'population':'population differs','old_budget':'omits stage: instrument_field_design','planning':'frozen downstream provider resources are incomplete','disk_floor':'frontend mandatory PA lower bound transient_run_directory_bytes','ram_floor':'frontend mandatory PA lower bound process_tree_working_set_bytes'}[failure],result.stderr)
                    if borrowed_capacity:
                        events=(run/'boundary.txt').read_text()
                        self.assertNotIn('lease_entered',events)
                        self.assertNotIn('frozen_field_design_consumed',events)
                        self.assertNotIn('inert_downstream:',events)
                    else:
                        self.assertFalse((run/'boundary.txt').exists())
                    if failure in ('disk_floor','ram_floor'):
                        self.assertFalse((run/'simion/downstream_fields').exists())
                else:
                    events=(run/'boundary.txt').read_text()
                    plan=json.loads((run/'simion/downstream_fields/command_plan.json').read_text())
                    expected_commitment=(plan['reserved_run_array_payload_bytes']+
                        plan['frontend_resource_lower_bounds']['cache_miss_new_disk_payload_bytes_lower_bound'])
                    self.assertIn(f'capacity:{expected_commitment}',events)
                    self.assertIn('frozen_field_design_consumed',events)
                    self.assertIn('lease_released',events);self.assertIn('capacity_released',events)
                    self.assertEqual((run/'results/single_reflection/field_receipt.json').exists(),failure in ('none','elapsed','downstream'))
                    self.assertEqual((run/'results/single_reflection/downstream_receipt.json').exists(),failure in ('none','elapsed'))
                    self.assertFalse((run/'simion/full_instrument').exists())
                    if failure in ('none','elapsed'):
                        evidence=json.loads((run/'results/single_reflection/downstream_execution_records.json').read_text())
                        self.assertEqual(len(evidence),5)
                        limits=[json.loads(Path(row['usage_record']['path']).read_text())['inert_limit_seconds'] for row in evidence]
                        self.assertEqual(limits,[60 if failure=='none' else 1]*5)
                        for row in evidence:
                            for key in ('stdout_record','stderr_record','usage_record'):
                                self.assertIn(row[key]['path'],values)
                    elif failure=='downstream':
                        evidence=json.loads((run/'results/single_reflection/downstream_execution_records.json').read_text())
                        self.assertEqual(len(evidence),1)
                        self.assertEqual(evidence[0]['exit_code'],1)
                    if failure=='elapsed':
                        self.assertIn('RESOURCE_BUDGET_WARNING=wall_clock_seconds',result.stdout+result.stderr)

    def test_public_managed_preparation_and_detached_closure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request, empty_run, _ = fixture(root)
            (empty_run / 'inputs').rmdir()
            empty_run.rmdir()
            script = root / 'prepare.ps1'
            script.write_text(r'''
param($Repo,$Python,$Root,$Request)
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$package=New-RunPackage -Python $Python -RepoRoot $Repo -ArtifactRoot (Join-Path $Root 'packages') `
  -RunId '20261023_010000__analysis__python__single-reflection-test' -Project instrument_assembly `
  -Mode single_reflection_preparation -Software @('Python 3.11')
& (Join-Path $Repo 'integrations/workflows/single_reflection_flight/execute.ps1') `
  -Request $Request -PrepareOnly -OutputDirectory $package.run_dir -RepoRoot $Repo -Python $Python
''', encoding='utf-8')
            result = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), str(REPO),
                                     sys.executable, str(root), str(request)], cwd=REPO,
                                    capture_output=True, text=True, encoding='utf-8', timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('SINGLE_REFLECTION_PREPARATION=PASS', result.stdout)
            run = next((root / 'packages/runs').iterdir())
            config = json.loads((run / 'run_config.json').read_text())
            receipt = json.loads((run / 'results/single_reflection/preparation_receipt.json').read_text())
            self.assertEqual(receipt['particle_count'], 100)
            self.assertEqual(receipt['stage'], 'geometry_preparation_only')
            self.assertNotIn('composition_plan', receipt['outputs'])
            self.assertTrue((run/'inputs/composition_plan.json').exists())
            geometry=json.loads(Path(receipt['outputs']['frontend_geometry']['path']).read_text())
            self.assertEqual(geometry['composition_plan']['scope']['kind'], 'full')
            for name, record in receipt['input_records'].items():
                self.assertEqual(config['inputs'][name], record['path'])
                expected_parent = (run/'inputs/components'/name.removeprefix('instance_design__')
                                   if name.startswith('instance_design__') else run/'inputs')
                self.assertEqual(Path(record['path']).parent, expected_parent)
            self.assertEqual((run / 'inputs/request.json').read_bytes(), request.read_bytes())
            snapshot = run / 'inputs/runtime_snapshot'
            environment = dict(os.environ, PYTHONPATH=str(snapshot), PYTHONNOUSERSITE='1')
            command = [sys.executable, '-B', '-s', '-m',
                       'integrations.workflows.single_reflection_flight.prepare', '--help']
            imported = subprocess.run(command, cwd=snapshot, env=environment,
                                      capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(imported.returncode, 0, imported.stderr)
            preflight_help=subprocess.run([sys.executable,'-B','-s','-m',
                'integrations.workflows.single_reflection_flight.downstream_fields','--help'],
                cwd=snapshot,env=environment,capture_output=True,text=True,encoding='utf-8',timeout=30)
            self.assertEqual(preflight_help.returncode,0,preflight_help.stderr)
            self.assertIn('--engineering-budget',preflight_help.stdout)
            (snapshot / 'projects/orthogonal_accelerator/simion/sectioned_accelerator.py').unlink()
            missing = subprocess.run(command, cwd=snapshot, env=environment,
                                     capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn('sectioned_accelerator', missing.stderr)
            manifest = run / 'run_manifest.json'
            value = json.loads(manifest.read_text())
            value['status'] = 'success'
            manifest.write_text(json.dumps(value), encoding='utf-8')
            refused = subprocess.run(['pwsh', '-NoProfile', '-File', str(EXECUTE),
                '-Request', str(request), '-PrepareOnly', '-OutputDirectory', str(run),
                '-RepoRoot', str(REPO), '-Python', sys.executable], cwd=REPO,
                capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn('cannot modify a terminal run', refused.stderr)

            failed_root = root / 'failure'
            failed_root.mkdir()
            bad_request, _, document = fixture(failed_root)
            document['source']['particle_source']['sha256'] = '0' * 64
            bad_request.write_text(json.dumps(document), encoding='utf-8')
            failed = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), str(REPO),
                sys.executable, str(failed_root), str(bad_request)], cwd=REPO,
                capture_output=True, text=True, encoding='utf-8', timeout=90)
            self.assertNotEqual(failed.returncode, 0)
            failed_run = next((failed_root / 'packages/runs').iterdir())
            failed_config = json.loads((failed_run / 'run_config.json').read_text())
            for name in receipt['input_records']:
                self.assertTrue(Path(failed_config['inputs'][name]).is_file(), name)
            seal_script = root / 'seal_failure.ps1'
            seal_script.write_text(r'''
param($Repo,$Python,$Run)
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
Complete-FailedRun -Python $Python -RepoRoot $Repo -RunConfig (Join-Path $Run 'run_config.json') `
  -Summary (Join-Path $Run 'summary.json') -SummaryRole single_reflection_preparation_summary `
  -Reason 'Frozen source identity mismatch' -Software @('Python 3.11') -Status failed -FailureStage preparation
''', encoding='utf-8')
            sealed = subprocess.run(['pwsh', '-NoProfile', '-File', str(seal_script), str(REPO),
                sys.executable, str(failed_run)], cwd=REPO,
                capture_output=True, text=True, encoding='utf-8', timeout=60)
            self.assertEqual(sealed.returncode, 0, sealed.stdout + sealed.stderr)
            failed_manifest = json.loads((failed_run / 'run_manifest.json').read_text())
            self.assertEqual(failed_manifest['status'], 'failed')
            self.assertTrue(set(receipt['input_records']) <= set(failed_manifest['inputs']))


if __name__ == '__main__':
    unittest.main()
