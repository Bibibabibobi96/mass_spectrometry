"""Execute provider orchestration and official crop with pure process/PA mocks."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parents[4]
SIMION_ROOT = REPO_ROOT / 'projects/parallel_mirror_dual_stripe_mr_tof/simion'
RUNNER = SIMION_ROOT / 'run_native_static_field_provider.ps1'
CROP = SIMION_ROOT / 'crop_native_static_field.lua'
PWSH = shutil.which('pwsh') or 'C:/Program Files/PowerShell/7/pwsh.exe'
LUA = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'SIMION-2020/lua.exe'


@unittest.skipUnless(Path(PWSH).is_file(), 'PowerShell Core required for AST fixtures')
class NativeProviderRunnerTest(unittest.TestCase):
    @unittest.skipUnless(LUA.is_file(), 'Installed standalone Lua required')
    def test_iob_ordinary_collision_is_only_allowed_for_static_field(self):
        source = (SIMION_ROOT / 'build_native_corridor_iob.lua').read_text(encoding='utf-8-sig')
        start = source.index('if operating.static_field then')
        # Stop before the following OA-only branch, retaining exactly the
        # shared static/family suffix guard as a complete Lua statement.
        block = source[start:source.index('\nif not measured_mode then', start)]
        code = ('local function check(path, static)\nlocal paths={[2]=path}; '
                'local operating={static_field=static}; local function invoke()\n' + block +
                '\nend; return pcall(invoke) end\n'
                "assert(check('collision.pa',{})); assert(check('legacy.pa0',{})); "
                "assert(check('family.pa0',nil)); assert(not check('collision.pa',nil)); "
                "assert(not check('response.pa1',{})); print('STATIC_COLLISION_SUFFIX=PASS')")
        result = subprocess.run([str(LUA), '-e', code], cwd=REPO_ROOT, timeout=30,
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('STATIC_COLLISION_SUFFIX=PASS', result.stdout)

    def test_new_geometry_collision_step_only_gem2pa_no_refine_or_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / 'collision.ps1'
            script.write_text(r'''
param($Runner,$Root)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$blocks=@($ast.FindAll({param($n) $n-is[Management.Automation.Language.ForEachStatementAst]-and $n.Extent.Text.StartsWith("foreach(`$occupancyName in @('collision','ip_collision','detector'))")-and $n.Extent.Text.Contains("`$stage=`$occupancyName+'_gem2pa'")},$true))
if($blocks.Count-ne1){throw 'Collision-only block not unique'}
$plan=@{collision_build=@{pa_bytes=8};ip_collision_build=@{pa_bytes=8};detector_build=@{pa_bytes=8};levels=@{parent=@{resource_limits=@{process_tree_working_set_bytes=16}}};committed_new_bytes=32;final_retained_estimate_bytes=24}
$RunDirectory=$Root;$pkg=@{run_dir=$Root};$runId='pure-collision';$exe='mock-simion';$lease=$null
$levelStatus=[ordered]@{};$timings=[ordered]@{};$script:calls=@();$script:exits=0
foreach($name in @('collision','ip_collision','detector')){$null=New-Item -ItemType Directory -Path (Join-Path $Root ('simion/'+$name))}
function Get-HostResourceBudget {param($Role,$Stage) if($Role-ne'SIMION'-or$Stage-ne'prepare'){throw 'Wrong host stage'};return @{memory_bytes=16}}
function Enter-HostResourceStage {param($Role,$Stage,$Budget,$RunId) return @{}}
function Exit-HostResourceStage {param($Lease) $script:exits++}
function Update-HostResourceStage {throw 'Collision must not Refine'}
function Write-RunJson {throw "Unexpected budget transport materialization"}
function Invoke-ResourceBudgetedProcess {
 param($Limits,$RunDir,$UsagePath,$FilePath,$WorkingDirectory,$ArgumentList,$RedirectStandardOutput,$RedirectStandardError)
 $script:calls+=,@($ArgumentList)
 $name=Split-Path -Leaf $WorkingDirectory
 if($name-notin@('collision','ip_collision','detector')-or($ArgumentList-join',')-ne('--nogui,--noprompt,gem2pa,'+$name+'.gem,'+$name+'.pa')){throw 'Unexpected Refine/Fast Adjust/copy'}
 [IO.File]::WriteAllBytes((Join-Path $WorkingDirectory ($name+'.pa')),[byte[]]::new(8))
 return @{exit_code=0}
}
. ([scriptblock]::Create($blocks[0].Extent.Text))
@{calls=$script:calls;statuses=$levelStatus;exits=$script:exits}|ConvertTo-Json -Depth 10 -Compress
''', encoding='utf-8')
            result = subprocess.run([PWSH, '-NoProfile', '-File', str(script), str(RUNNER), str(root)],
                                    cwd=REPO_ROOT, timeout=30, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(set(value['statuses']), {'collision', 'ip_collision', 'detector'})
            for status in value['statuses'].values():
                self.assertTrue(status['completed'])
                self.assertFalse(status['refine_completed'])
            self.assertEqual(value['exits'], 3)
            self.assertEqual(len(value['calls']), 3)

    def execute_composition(self, failure=''):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / 'composition.ps1'
            script.write_text(r'''
param($Runner,$Root,$Failure)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$mode=@($ast.FindAll({param($node) $node-is[Management.Automation.Language.AssignmentStatementAst]-and $node.Left.Extent.Text-eq'$isComposition'},$true))
$choice=@($ast.FindAll({param($node) $node-is[Management.Automation.Language.IfStatementAst]-and $node.Extent.Text.Contains("$"+'stage='+"'compose_static_fields'")},$true))
if($mode.Count-ne1-or$choice.Count-ne1){throw 'Composition assignment/branch not unique'}
$RunDirectory=$Root;$repo=$Root;$runId='fixture';$python=Join-Path $Root 'python.exe';$module='native_provider'
$planPath=Join-Path $Root 'plan.json'
$labels=@('parent','window_2','window_0','window_1')
$receipts=@{};foreach($label in $labels){$receipts[$label]=Join-Path $Root ('results/'+$label+'_receipt.json')}
$plan=@{operation='compose';execution_order=$labels;committed_new_bytes=10000;final_retained_estimate_bytes=9000;materialization=@{receipts=$receipts};levels=@{parent=@{resource_limits=@{process_tree_working_set_bytes=1024}}}}
$lease=$null;$timings=[ordered]@{};$levelStatus=[ordered]@{};$parentDone=$false;$windowDone=$false
$script:calls=@();$script:stages=@();$script:exits=0
foreach($name in @('inputs','results','logs')){$null=New-Item -ItemType Directory -Path (Join-Path $Root $name)}
function Get-HostResourceBudget {param($Role,$Stage) $script:stages+=@{action='budget';role=$Role;stage=$Stage};return @{}}
function Enter-HostResourceStage {param($Role,$Stage,$Budget,$RunId) $script:stages+=@{action='enter';role=$Role;stage=$Stage};return @{stage=$Stage}}
function Update-HostResourceStage {throw 'Composition must not switch to Refine/crop'}
function Exit-HostResourceStage {param($Lease) $script:exits++}
function Write-RunJson {throw "Unexpected budget transport materialization"}
function Invoke-ResourceBudgetedProcess {
 param($Limits,$RunDir,$UsagePath,$FilePath,$WorkingDirectory,$ArgumentList,$RedirectStandardOutput,$RedirectStandardError)
 if($FilePath-ne$python-or$WorkingDirectory-ne$repo-or$ArgumentList[-1]-ne'--compose'){throw 'Unexpected commercial/GEM/Refine/crop process'}
 $script:calls+=@{file=$FilePath;arguments=@($ArgumentList);working_directory=$WorkingDirectory}
 if($Failure-eq'exit_nonzero'){return @{exit_code=1}}
 foreach($label in $plan.execution_order){
  if($Failure-eq'missing_receipt'-and$label-eq'window_1'){continue}
  @{status='PASS'}|ConvertTo-Json|Set-Content -LiteralPath $plan.materialization.receipts[$label]
 }
 return @{exit_code=0}
}
$errorText=$null
try{
 . ([scriptblock]::Create($mode[0].Extent.Text))
 . ([scriptblock]::Create($choice[0].Extent.Text))
}catch{$errorText=$_.Exception.Message}
finally{if($lease){Exit-HostResourceStage -Lease $lease}}
@{calls=$script:calls;stages=$script:stages;levels=$levelStatus;error=$errorText;exits=$script:exits;composition=$isComposition;parent_refine=$parentDone;local_refine=$windowDone}|ConvertTo-Json -Depth 15 -Compress
''', encoding='utf-8')
            result = subprocess.run([PWSH, '-NoProfile', '-File', str(script), str(RUNNER),
                                     str(root), failure], cwd=REPO_ROOT, timeout=30,
                                    capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

    def test_composition_executes_one_python_materialization_in_gate_prepare(self):
        result = self.execute_composition()
        self.assertIsNone(result['error'])
        self.assertTrue(result['composition'])
        self.assertEqual(result['stages'], [dict(action='budget', role='GATE', stage='prepare'),
                                            dict(action='enter', role='GATE', stage='prepare')])
        self.assertEqual(len(result['calls']), 1)
        arguments = result['calls'][0]['arguments']
        self.assertEqual(arguments[:3], ['-B', '-m', 'native_provider'])
        self.assertEqual(arguments[3], '--plan')
        self.assertEqual(arguments[5], '--run-directory')
        self.assertEqual(arguments[7:], ['--compose'])
        self.assertEqual(result['exits'], 1)
        self.assertEqual(set(result['levels']), {'parent', 'window_0', 'window_1', 'window_2'})
        for level in result['levels'].values():
            self.assertEqual(level, dict(refine_completed=False, crop_completed=False,
                                         completed=True, materialized=True))
        self.assertFalse(result['parent_refine'])
        self.assertFalse(result['local_refine'])

    def test_composition_nonzero_exit_or_missing_receipt_fail_closed(self):
        nonzero = self.execute_composition('exit_nonzero')
        self.assertIn('materialization failed', nonzero['error'])
        self.assertEqual(nonzero['levels'], {})
        missing = self.execute_composition('missing_receipt')
        self.assertIn('Missing materialization receipt: window_1', missing['error'])
        self.assertNotIn('window_1', missing['levels'])
        for result in (nonzero, missing):
            self.assertEqual(len(result['calls']), 1)
            self.assertEqual(result['exits'], 1)
            self.assertFalse(result['parent_refine'])
            self.assertFalse(result['local_refine'])

    def test_response_publication_does_not_advertise_a_fly_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'publication.ps1'
            script.write_text(r'''
param($Runner,$Root)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$choice=@($ast.FindAll({param($node) $node-is[Management.Automation.Language.IfStatementAst]-and $node.Extent.Text.Contains('$responseBasis=Join-Path')},$true))
if($choice.Count-ne1){throw 'Response publication choice not unique.'}
$mode=@($ast.FindAll({param($node) $node-is[Management.Automation.Language.AssignmentStatementAst]-and $node.Left.Extent.Text-eq'$isResponse'},$true))
if($mode.Count-ne1){throw 'Response mode assignment not unique.'}
$RunDirectory=$Root
$rows=@()
foreach($plan in @(@{},@{response_basis=$null},@{response_basis=@{axis='s1'}})){
 . ([scriptblock]::Create($mode[0].Extent.Text))
 $fieldBinding=$null;$responseBasis=$null
 . ([scriptblock]::Create($choice[0].Extent.Text))
 $rows+=@{response=$isResponse;field_binding=$fieldBinding;response_basis=$responseBasis}
}
$rows|ConvertTo-Json -Compress
''', encoding='utf-8')
            result = subprocess.run([PWSH, '-NoProfile', '-File', str(script), str(RUNNER), directory],
                                    cwd=REPO_ROOT, timeout=30, capture_output=True,
                                    text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            ordinary, ordinary_null, basis = json.loads(result.stdout)
            self.assertEqual(ordinary, ordinary_null)
            self.assertTrue(ordinary['field_binding'].endswith('field_binding.json'))
            self.assertIsNone(ordinary['response_basis'])
            self.assertIsNone(basis['field_binding'])
            self.assertTrue(basis['response_basis'].endswith('response_basis.json'))

    def execute(self, order, parents, crops=(), failure='', reused=()):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            levels = {}
            for label in order:
                level = dict(parent_label=parents.get(label), resource_budget={},
                             resource_limits=dict(wall_clock_seconds_by_solver=dict(simion=100),
                                                  process_tree_working_set_bytes=1024),
                             box_mm=[0, -1, -2, 4, 4, 4], dimensions=[9, 7, 9],
                             pitch_mm=[.5, .5, .5])
                if label in crops:
                    level['crop'] = dict(method='pa:crop', persist=False,
                                         overwrite_private_working_pa=True, refine_after_crop=False,
                                         start_grid=[0, 0, 0], width_grid=[4, 6, 8],
                                         consumer_dimensions=[5, 7, 9], expected_consumer_pa_bytes=64)
                levels[label] = level
                if label in reused:
                    sealed = root / f'sealed_{label}.pa'
                    sealed.write_bytes(b'sealed readonly parent')
                    level['reuse_source'] = dict(pa_path=str(sealed), manifest=str(root / 'sealed.json'))
            plan = dict(levels=levels, execution_order=order,
                        window_labels=[label for label in order if label != 'parent'],
                        committed_new_bytes=10000, final_retained_estimate_bytes=9000,
                        refine_options=dict(convergence=1e-5))
            (root / 'plan.json').write_text(json.dumps(plan), encoding='utf-8')
            script = root / 'fixture.ps1'
            script.write_text(r'''
param($Runner,$Root,$Failure)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Runner,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$loop=@($ast.FindAll({param($node) $node-is[Management.Automation.Language.ForEachStatementAst]-and $node.Extent.Text.Contains('$level=$plan.levels[$label]')},$true))
if($loop.Count-ne1){throw 'Execution loop not unique.'}
$plan=Get-Content -LiteralPath (Join-Path $Root 'plan.json') -Raw|ConvertFrom-Json -AsHashtable
$isConsumerView=$false
$RunDirectory=$Root;$pkg=@{run_dir=$Root};$runId='fixture';$exe='mock';$frozen=@{builder='builder.lua';crop_adapter='crop.lua'}
$lease=$null;$parentGuard=$null;$parentDone=$false;$windowDone=$false
$timings=[ordered]@{};$levelStatus=[ordered]@{};$script:calls=@()
foreach($name in @('inputs','logs','results')){$null=New-Item -ItemType Directory -Path (Join-Path $Root $name)}
foreach($label in $plan.execution_order){$null=New-Item -ItemType Directory -Path (Join-Path $Root ('simion/'+$label))}
function Get-HostResourceBudget {param($Role,$Stage) return @{}}
function Enter-HostResourceStage {param($Role,$Stage,$Budget,$RunId) return @{stage=$Stage}}
function Update-HostResourceStage {param($Lease,$Stage,$Budget,$RetainedMemoryBytes) return @{stage=$Stage}}
function Exit-HostResourceStage {param($Lease)}
function Write-RunJson {param($Path,$Value,$Depth) $Value|ConvertTo-Json -Depth $Depth|Set-Content -LiteralPath $Path}
function Invoke-ResourceBudgetedProcess {
 param($Limits,$RunDir,$UsagePath,$FilePath,$WorkingDirectory,$ArgumentList,$RedirectStandardOutput,$RedirectStandardError)
 $script:calls+=,@($ArgumentList)
 @{wall_clock_seconds=1;peak_process_tree_working_set_bytes=1}|ConvertTo-Json|Set-Content -LiteralPath $UsagePath
 $label=Split-Path -Leaf $WorkingDirectory
 if($ArgumentList[2]-eq'gem2pa'){
  $pa=Join-Path $WorkingDirectory $ArgumentList[4]
  [IO.File]::WriteAllBytes($pa,(New-Object byte[] 64))
  [IO.File]::WriteAllText($pa+'-surf','surface')
 }elseif($ArgumentList[2]-eq'lua'-and$ArgumentList[3]-eq'crop.lua'){
  $dimensions=@($ArgumentList[10]-split','|ForEach-Object{[int]$_+1})
  if($Failure-eq'crop_dimensions'){$dimensions[0]++}
  @{status='PASS';refine_after_crop=$false;consumer_dimensions=$dimensions}|ConvertTo-Json|Set-Content -LiteralPath $ArgumentList[6]
  if($Failure-eq'surface_lost'){Remove-Item -LiteralPath ($ArgumentList[4]+'-surf')}
 }elseif($Failure-eq'refine_failure'-and$label-eq'window_0'){return @{exit_code=1}}
 return @{exit_code=0}
}
$errorText=$null
try{& ([scriptblock]::Create($loop[0].Extent.Text))}catch{$errorText=$_.Exception.Message}
finally{if($parentGuard){$parentGuard.Dispose()}}
@{calls=$script:calls;levels=$levelStatus;error=$errorText;parent_completed=$parentDone}|ConvertTo-Json -Depth 15 -Compress
''', encoding='utf-8')
            result = subprocess.run([PWSH, '-NoProfile', '-File', str(script), str(RUNNER),
                                     str(root), failure], cwd=REPO_ROOT, timeout=30,
                                    capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

    def test_three_windows_use_execution_parent_and_crop_after_full_refine(self):
        result = self.execute(['parent', 'window_2', 'window_0', 'window_1'],
                              {'window_2': 'parent', 'window_0': 'window_2', 'window_1': 'window_2'},
                              ['window_0', 'window_1'])
        self.assertIsNone(result['error'])
        self.assertEqual([call[2] for call in result['calls']],
                         ['gem2pa', 'refine', 'gem2pa', 'lua', 'gem2pa', 'lua', 'lua', 'gem2pa', 'lua', 'lua'])
        builders = [call for call in result['calls'] if len(call) > 3 and call[3] == 'builder.lua']
        self.assertIn('parent', builders[0][5])
        self.assertTrue(all('window_2' in call[5] for call in builders[1:]))
        self.assertTrue(all(call[-1] == '1E-05' for call in builders))
        self.assertTrue(all(level['completed'] for level in result['levels'].values()))
        self.assertTrue(result['levels']['window_0']['crop_completed'])
        self.assertFalse(result['levels']['window_2']['crop_completed'])

    def test_single_window_keeps_same_execution_path(self):
        result = self.execute(['parent', 'window'], {'window': 'parent'})
        self.assertIsNone(result['error'])
        self.assertEqual(len(result['calls']), 4)
        self.assertTrue(result['levels']['window']['completed'])

    def test_reused_parent_and_central_skip_solver_and_supply_original_boundary(self):
        result = self.execute(['parent', 'window_2', 'window_0', 'window_1'],
                              {'window_2': 'parent', 'window_0': 'window_2', 'window_1': 'window_2'},
                              ['window_0', 'window_1'], reused=['parent', 'window_2'])
        self.assertIsNone(result['error'])
        self.assertEqual([call[2] for call in result['calls']],
                         ['gem2pa', 'lua', 'lua', 'gem2pa', 'lua', 'lua'])
        builders = [call for call in result['calls'] if call[3] == 'builder.lua']
        self.assertEqual(len(builders), 2)
        self.assertTrue(all(call[5].endswith('sealed_window_2.pa') for call in builders))
        self.assertFalse(result['parent_completed'])
        for label in ('parent', 'window_2'):
            self.assertTrue(result['levels'][label]['reused'])
            self.assertFalse(result['levels'][label]['refine_completed'])

    def test_failure_stops_remaining_levels_without_completion(self):
        for failure in ('refine_failure', 'crop_dimensions', 'surface_lost'):
            with self.subTest(failure=failure):
                result = self.execute(['parent', 'window_2', 'window_0', 'window_1'],
                                      {'window_2': 'parent', 'window_0': 'window_2', 'window_1': 'window_2'},
                                      ['window_0', 'window_1'], failure)
                self.assertIsNotNone(result['error'])
                self.assertFalse(result['levels']['window_0']['completed'])
                self.assertNotIn('window_1', result['levels'])

    def test_unfinished_or_cropped_parent_rejected(self):
        result = self.execute(['parent', 'window_0', 'window_2'],
                              {'window_0': 'window_2', 'window_2': 'parent'})
        self.assertIn('completed declared parent', result['error'])
        result = self.execute(['parent', 'window_2', 'window_0'],
                              {'window_2': 'parent', 'window_0': 'window_2'}, ['window_2'])
        self.assertIn('cropped consumer', result['error'])


@unittest.skipUnless(LUA.is_file(), 'installed Lua interpreter required; no SIMION process')
class NativeCropTest(unittest.TestCase):
    def execute(self, failure=''):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / 'fixture.lua'
            script.write_text(r'''
local adapter,root,failure=arg[1],arg[2],arg[3]
local opens,crops=0,0
local function object(nx)
 local p={nx=nx,ny=7,nz=9,dx_mm=.5,dy_mm=.5,dz_mm=.5,symmetry='3dplanar[x]',refined=true,refinable=true}
 function p:point(x,y,z) return x+y+z+(self.bad and 1 or 0),x==0 end
 function p:potential_vc(x,y,z) return math.abs(x)+y+z end
 function p:field_vc(x,y,z) return x<0 and -1 or 1,2,3 end
 function p:surface_info(x,y,z) if x==0 and y==1 and z==2 then return .5,nil,.25 end end
 function p:crop(x,y,z,wx,wy,wz,persist)
  assert(x==0 and y==0 and z==0 and not persist)
  crops=crops+1;self.nx=wx+1;self.ny=wy+1;self.nz=wz+1
  if failure=='node_changed' then self.bad=true end
 end
 function p:save(path) if failure=='save_failure' then return false,'save refused' end return true end
 function p:close() end
 function p:refine() error('crop must never Refine') end
 return p
end
simion={pas={}}
function simion.pas:open(path)
 opens=opens+1;local p=object(opens==1 and 9 or 5)
 if failure=='reload_pitch' and opens==2 then p.dx_mm=.25 end
 return p
end
arg={root..'/private.pa',root..'/samples.csv',root..'/receipt.json','9,7,9','0.5,0.5,0.5','0,0,0','4,6,8'}
assert(loadfile(adapter))()
assert(opens==2 and crops==1)
''', encoding='utf-8')
            result = subprocess.run([str(LUA), str(script), str(CROP), str(root), failure],
                                    cwd=REPO_ROOT, timeout=30, capture_output=True,
                                    text=True, encoding='utf-8')
            receipt = json.loads((root / 'receipt.json').read_text()) if result.returncode == 0 else None
            return result, receipt

    def test_official_crop_preserves_signed_field_nodes_flags_and_fractional_samples(self):
        result, receipt = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(receipt['status'], 'PASS')
        self.assertEqual(receipt['consumer_dimensions'], [5, 7, 9])
        self.assertEqual(receipt['retained_sample_count'], 56)
        self.assertGreater(receipt['fractional_witness_count'], 0)
        self.assertFalse(receipt['refine_after_crop'])
        self.assertFalse(receipt['qualification'])

    def test_crop_change_save_failure_and_reload_identity_fail_closed(self):
        for failure in ('node_changed', 'save_failure', 'reload_pitch'):
            with self.subTest(failure=failure):
                result, receipt = self.execute(failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(receipt)


if __name__ == '__main__':
    unittest.main()
