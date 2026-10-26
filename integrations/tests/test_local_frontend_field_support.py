"""Artifact-free contracts and Plain Lua checks; never starts SIMION."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.write_run_manifest import file_record
from integrations.runtime.build_single_flight_program import (
    STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION,
    _resolve_standalone_dynamic_field_bank,
)

from integrations.runtime.single_flight_frontend import compile_frontend
from integrations.runtime.single_flight_electrode_contract import render_pa_plus_solution_model
from integrations.tests.frontend_fixtures import canonical_frontend_fixture, canonical_three_zone_frontend_fixture

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / 'integrations/runtime'
SUPPORT = RUNTIME / 'local_frontend_field_support.ps1'
LUA = Path('C:/Program Files/SIMION-2020/lua.exe')


def normalization_fixture(directory):
    """Small synthetic PA identity records, never used as vendor field evidence."""
    records=[]
    header='mode_id\tlabel\tx_gu\ty_gu\tz_gu\tpotential_v\telectrode\texpected_coefficient\tbasis_reference_v\tnormalized_coefficient\tpolicy'
    rows=['frontend_mode_normalization_v4','physical_count\t8\t8']+[f'physical\trod_{i}\t{i}\trod' for i in range(1,9)]+['measurements',header]
    for mode in range(28,33):
        path=directory/f'frontend.response_{mode}.pa';path.write_bytes(b'SYNTHETIC_NOT_PA')
        records.append(dict(response_id=mode,**file_record(path)))
        for rod in range(1,9):
            rows.append(f'{mode}\trod_{rod}\t1\t1\t1\t10000\ttrue\t1\t10000\t1\t'+('unity_anchor' if rod==1 else 'declared_sample'))
    path=directory/'standalone_mode_normalization.tsv';path.write_text('\n'.join(rows)+'\n')
    inventory=[dict(name=Path(r['path']).name,bytes=r['bytes'],sha256=r['sha256']) for r in records]
    identity=file_record(path);inventory.append(dict(name=path.name,bytes=identity['bytes'],sha256=identity['sha256']))
    (directory/'cache_manifest.json').write_text(json.dumps(dict(files=inventory)))
    return records


class LocalFrontendFieldSupportTests(unittest.TestCase):
    def prepare(self, directory, *, three_zone=False):
        upstream, connection, component = (canonical_three_zone_frontend_fixture if three_zone else canonical_frontend_fixture)()
        kwargs = dict(target_solver_frame='mrtof_global_cartesian') if three_zone else {}
        gem, frontend = compile_frontend(upstream, connection, cell_mm_xyz=dict(x=.1,y=.2,z=.1) if three_zone else dict(x=.5,y=.5,z=.1), accelerator_component=component, **kwargs)
        physical = {key: value for key, value in dict(geometry=frontend, gem=hashlib.sha256(gem.encode()).hexdigest().upper(), basis_namespace=frontend['pa_plus_solution_model'],
                     mesh=frontend['cell_mm_xyz'], grid_phase=frontend['instance_origin_mm'], surface='none', refine_policy='official_defaults').items()}
        for name, value in {'frontend_contract.json': frontend, 'guide_contract.json': upstream,
                            'numerics.json': {'refine_policy': 'official_defaults'}, 'cache_physical_inputs.json': physical}.items():
            (directory / name).write_text(json.dumps(value))
        (directory / 'frontend.gem').write_text(gem, newline='\n')
        (directory / 'frontend.pa+').write_text(render_pa_plus_solution_model(frontend['pa_plus_solution_model']), newline='\n')
        return frontend

    def embedded(self, name, arguments):
        source = re.search(r'\$' + name + r"=@'\n(.*?)\n'@", SUPPORT.read_text(), re.S)
        self.assertIsNotNone(source)
        output = io.StringIO()
        with patch.object(sys, 'argv', ['embedded', *map(str, arguments), '']), contextlib.redirect_stdout(output):
            exec(compile(source[1], str(SUPPORT) + ':' + name, 'exec'), {})
        return json.loads(output.getvalue())

    def test_real_five_mode_plan_uses_public_identity_and_all_rod_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            self.prepare(p)
            plan = self.embedded('planCode', [p, sys.executable, RUNTIME])
            self.assertEqual(plan['mode_ids'], list(range(28, 33)))
            self.assertEqual(len(plan['samples']), 60)
            self.assertEqual({row[1] for row in plan['samples']}, {f'rod_{i}' for i in range(1, 9)} | {'guide_axis_finite','repeller_metal','grid1_metal','grid2_metal'})
            self.assertEqual(len(plan['filenames']), 7)
            self.assertEqual(plan['identity']['refine_policy'], 'official_defaults')
            self.assertEqual(plan['recipe']['schema_version'],2)
            self.assertEqual(plan['recipe']['source_location'],'build_scratch')
            self.assertTrue(all(name.endswith('.pa') or name.endswith('.json') or name.endswith('.tsv') for name in plan['filenames']))
            for mode in plan['mode_ids']:
                anchors=[r for r in plan['samples'] if r[0]==mode and r[-1]=='unity_anchor']
                self.assertEqual(len(anchors),1)
                self.assertEqual(anchors[0][-2],1)
            self.assertIn('standalone_mode_normalization.tsv',plan['filenames'])
            self.assertEqual(set(plan['identity']), {'geometry', 'gem', 'basis_namespace', 'mesh', 'grid_phase', 'surface', 'simion_identity', 'refine_policy', 'builder_identity'})

    def test_real_bare_three_zone_plan_uses_actual_sheets_and_six_unity_anchors(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)
            frontend=self.prepare(p,three_zone=True)
            plan=self.embedded('planCode',[p,sys.executable,RUNTIME])
            self.assertEqual(plan['model_id'],'three_zone_linear_ring_bare_octupole_pa_plus_v1')
            self.assertEqual(plan['mode_count'],6)
            self.assertEqual(plan['mode_ids'],frontend['pa_plus_solution_model']['mode_ids'])
            self.assertEqual(len(plan['samples']),78)
            self.assertEqual(len(plan['filenames']),8)
            self.assertNotIn('grid_supports',frontend['accelerator_local_region']['canonical_electrodes'])
            endpoints={'repeller_metal','grid1_metal','intermediate2_metal','grid2_metal'}
            for mode in plan['mode_ids']:
                rows=[r for r in plan['samples'] if r[0]==mode]
                self.assertEqual(len(rows),13)
                self.assertTrue(endpoints.issubset({r[1] for r in rows}))
                anchors=[r for r in rows if r[-1]=='unity_anchor']
                self.assertEqual(len(anchors),1)
                self.assertEqual(anchors[0][-2],1)
            # A genuinely non-node-aligned ideal plane is rejected; no sheet padding.
            file=p/'frontend_contract.json'
            altered=json.loads(file.read_text())
            for key in ('z_min_mm','z_max_mm'):
                altered['accelerator_local_region']['canonical_electrodes']['ideal_sheets'][0]['sheet_box_mm'][key]+=.025
            file.write_text(json.dumps(altered))
            with self.assertRaisesRegex(ValueError,'node plane'):
                self.embedded('planCode',[p,sys.executable,RUNTIME])

    def test_composition_plan_retains_published_identities_for_runtime_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            self.prepare(p)
            records = normalization_fixture(p)
            selection = p / 'selection.json'
            selection.write_text(json.dumps({'records': records}))
            result = self.embedded('composeCode', [p, selection, p / 'output', p / 'standalone_mode_normalization.tsv'])
            self.assertEqual(len(result['compositions']), 3)
            self.assertNotIn('response_copies', result)
            self.assertEqual(result['field_bank']['runtime_representation'], 'standalone_operating_pa_explicit_dynamic_v1')
            self.assertEqual(result['field_bank']['dynamic_roles'][0]['instance_index'], 1)
            self.assertEqual(result['field_bank']['schema_version'], STANDALONE_DYNAMIC_FIELD_BANK_SCHEMA_VERSION)
            role = result['field_bank']['dynamic_roles'][0]
            self.assertEqual(role['rf_differential_pa_basenames'], ['coarse_frontend.rf_differential.pa'])
            self.assertEqual(role['rf_reference_voltage_v'], 1.0)
            self.assertNotIn('rf_differential_pa_basename', role)
            self.assertEqual(_resolve_standalone_dynamic_field_bank(
                result['field_bank'], {'coarse_frontend': 1}), [role])
            rf_job = next(job for job in result['compositions'] if job['kind'] == 'rf_differential_unit')
            # Raw test responses have a measured 10000 V anchor; the composed
            # response must retain exactly the requested per-volt state.
            physical_coefficients = {record['path']: 0.0 for record in records}
            physical_coefficients[rf_job['base']] = 1.0
            for term in rf_job['terms']:
                physical_coefficients[term['path']] += term['coefficient']
            for record in records:
                value = physical_coefficients[record['path']] * 10000.0
                expected = result['mode_states_v']['rf_differential_unit'][str(record['response_id'])]
                # Bound binary64 cancellation at the original basis scale;
                # this is arithmetic roundoff, not a PA accuracy allowance.
                self.assertLessEqual(abs(value-expected), 32 * math.ulp(10000.0))
            for job in result['compositions']:
                self.assertIn(job['base'], [r['path'] for r in records])

    def run_protected_composition(self, failure='none', mode_count=5):
        """Exercise real public copy/guard cleanup with a non-vendor callback."""
        pwsh=shutil.which('pwsh')
        if not pwsh:
            self.skipTest('PowerShell 7 unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            published=root/'published'
            published.mkdir()
            records=[]
            for mode in range(1,mode_count+1):
                path=published/f'response_{mode}.pa'
                path.write_bytes(f'SYNTHETIC_NOT_PA_{mode}'.encode())
                records.append(dict(response_id=mode,**file_record(path)))
            (published/'cache_manifest.json').write_text(json.dumps({'files':[
                dict(name=Path(r['path']).name,bytes=r['bytes'],sha256=r['sha256']) for r in records]}))
            selection=root/'selection.json'
            selection.write_text(json.dumps({'records':records}))
            jobs=[dict(kind=kind,base=records[0]['path'],output=str(root/f'{kind}.pa'),
                       terms=[dict(path=r['path'],coefficient=.125) for r in records[:count]])
                  for kind,count in (('carrier',1),('rf',2),('pulse',mode_count))]
            (root/'jobs.json').write_text(json.dumps(jobs))
            script=root/'check.ps1'
            script.write_text("""param([string]$Repo,[string]$Support,[string]$Root,[string]$Failure)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/simion/short_pa_path_support.ps1')
. $Support
$records=@((Get-Content (Join-Path $Root 'selection.json') -Raw|ConvertFrom-Json).records)
$jobs=@(Get-Content (Join-Path $Root 'jobs.json') -Raw|ConvertFrom-Json)
$script:calls=@();$script:tempDirectories=@();$caught='';$result=$null
try {
 $result=Invoke-LocalFrontendFieldCompositions -SelectionPath (Join-Path $Root 'selection.json') -Compositions $jobs -ComposerPath 'SYNTHETIC_NOT_VENDOR.lua' -OutputDirectory $Root -InvokeNative {
  param($Arguments,$Directory,$Name)
  $paths=@([string]$Arguments[4])+@($Arguments|Select-Object -Skip 6|ForEach-Object{($_ -split ',')[0]})
  foreach($path in $paths){
   if($path-in@($records|ForEach-Object{$_.path})){throw 'published path passed to native callback'}
   if(-not(Test-Path -LiteralPath $path)){throw 'private input missing'}
   $script:tempDirectories+=Split-Path -Parent $path
  }
  foreach($record in $records){
   $blocked=$false
   try{$writer=[IO.File]::Open([string]$record.path,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite);$writer.Dispose()}
   catch [IO.IOException]{$blocked=$true}
   if(-not$blocked){throw 'published source was writable during native callback'}
  }
  $script:calls+=,@{name=$Name;paths=$paths;directory=$Directory}
  if($Failure-eq'native'){throw 'CONTROLLED_NATIVE_CALLBACK_FAILURE'}
  if($Failure-eq'private_mutation'){[IO.File]::WriteAllText($paths[0],'CONTROLLED_PRIVATE_COPY_MUTATION')}
  [IO.File]::WriteAllText([string]$Arguments[5],'SYNTHETIC_OUTPUT_NOT_PA')
 }
}catch{$caught=$_.Exception.Message}
foreach($record in $records){
 if((Get-FileHash -LiteralPath ([string]$record.path)).Hash-ne[string]$record.sha256){throw 'published bytes changed'}
 $writer=[IO.File]::Open([string]$record.path,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite);$writer.Dispose()
}
foreach($directory in @($script:tempDirectories|Select-Object -Unique)){
 if(Test-Path -LiteralPath $directory){throw 'temporary copies not cleaned'}
}
if($global:MassSpectrometryShortPaCopies.Count-or$global:MassSpectrometryShortPaSourceGuards.Count-or$global:MassSpectrometryImmutablePaSourceGuards.Count){throw 'guard registry leaked'}
@{caught=$caught;result=$result;calls=$script:calls;source_unchanged=$true;temporary_copies_removed=$true}|ConvertTo-Json -Depth 10 -Compress
""", encoding='utf-8', newline='\n')
            completed=subprocess.run([pwsh,'-NoProfile','-File',str(script),str(ROOT),str(SUPPORT),str(root),failure],
                                     capture_output=True,text=True,encoding='utf-8',check=False,cwd=ROOT,timeout=60)
            self.assertEqual(completed.returncode,0,completed.stderr)
            return json.loads(completed.stdout)

    def test_native_composition_uses_one_guarded_copy_set_for_all_working_points(self):
        for count in (5,6):
            with self.subTest(mode_count=count):
                output=self.run_protected_composition(mode_count=count)
                self.assertEqual(output['caught'],'')
                self.assertEqual(len(output['calls']),3)
                self.assertEqual(output['result']['response_copies'],count)
                self.assertEqual(len(output['result']['source_verification_after_native']),count)
                paths=[call['paths'][0] for call in output['calls']]
                self.assertEqual(len(set(paths)),1)
                self.assertTrue(output['result']['temporary_copies_removed'])

    def test_native_failure_and_private_mutation_preserve_sources_and_release_guards(self):
        for failure,message in (('native','CONTROLLED_NATIVE_CALLBACK_FAILURE'),
                                ('private_mutation','Short PA destination SHA256')):
            with self.subTest(failure=failure):
                output=self.run_protected_composition(failure)
                self.assertIn(message,output['caught'])
                self.assertEqual(len(output['calls']),1)
                self.assertTrue(output['source_unchanged'])
                self.assertTrue(output['temporary_copies_removed'])

    def test_rod_sample_interior_check_uses_common_radial_axes_in_native_mr(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            f = self.prepare(p)
            f['guide_registration']['rotation_upstream_to_downstream'] = [[0, -1, 0], [0, 0, 1], [-1, 0, 0]]
            f['guide_registration']['translation_mm'] = [0, .24, 0]
            f['instance_origin_mm'] = dict(x=-50, y=-50, z=-50)
            f['cell_mm_xyz'] = dict(x=.001, y=.5, z=.001)
            # This orientation-only fixture changes pitch/origin; keep its
            # declared numerical box consistent with those explicit changes.
            f['dimensions'] = {"n"+axis: round(200/f['cell_mm_xyz'][axis])+1 for axis in 'xyz'}
            for rod in f['guide_contract']['rod_array']['rods']:
                rod['radius_mm'] = .01
            (p / 'frontend_contract.json').write_text(json.dumps(f))
            physical = json.loads((p / 'cache_physical_inputs.json').read_text())
            physical.update(mesh=f['cell_mm_xyz'], grid_phase=f['instance_origin_mm'])
            (p / 'cache_physical_inputs.json').write_text(json.dumps(physical))
            plan = self.embedded('planCode', [p, sys.executable, RUNTIME])
            self.assertEqual(len(plan['samples']), 60)

    def test_prepared_gem_and_pa_plus_drift_are_rejected_before_native(self):
        for filename in ('frontend.gem', 'frontend.pa+'):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                p = Path(directory)
                self.prepare(p)
                with (p / filename).open('a') as stream:
                    stream.write('\n-- changed\n')
                with self.assertRaises(AssertionError):
                    self.embedded('planCode', [p, sys.executable, RUNTIME])

    @unittest.skipUnless(shutil.which('pwsh'), 'PowerShell 7 unavailable')
    def test_native_steps_warn_after_stage_wall_clock_without_mutating_frozen_limits(self):
        # Exercise the actual nested adapter, without running the large field
        # stage or a solver. Public process execution is explicitly inert.
        source=SUPPORT.read_text()
        start=source.index('  function Invoke-LocalFieldNative {')
        end=source.index('\n  }',start)+len('\n  }')
        with tempfile.TemporaryDirectory() as directory:
            script=Path(directory)/'shared_wall.ps1'
            script.write_text("""$ErrorActionPreference='Stop'
$Limits=[pscustomobject]@{wall_clock_seconds=2}
$StageElapsed=[Diagnostics.Stopwatch]::StartNew()
$run=$log=$PSScriptRoot;$SimionExe='INERT_NOT_VENDOR.exe'
$wallClockWarningNames=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
$script:observed=@()
function Invoke-ResourceBudgetedProcess {
 param($Limits,$RunDir,$UsagePath,$FilePath,$WorkingDirectory,$ArgumentList,$RedirectStandardOutput,$RedirectStandardError)
 $script:observed+=@($Limits.wall_clock_seconds)
 Start-Sleep -Milliseconds 1100
 return @{exit_code=0;resource_budget_exceeded=$false}
}
"""+source[start:end]+"""
Invoke-LocalFieldNative -Arguments @('INERT') -Directory $PSScriptRoot -Name 'one'
Invoke-LocalFieldNative -Arguments @('INERT') -Directory $PSScriptRoot -Name 'two'
Invoke-LocalFieldNative -Arguments @('INERT') -Directory $PSScriptRoot -Name 'expired'
@{limits=$script:observed;frozen_limit=$Limits.wall_clock_seconds}|ConvertTo-Json -Compress
""",encoding='utf-8',newline='\n')
            result=subprocess.run(['pwsh','-NoProfile','-File',str(script)],capture_output=True,text=True,encoding='utf-8',cwd=directory,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        evidence=json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(evidence['frozen_limit'],2)
        self.assertEqual(evidence['limits'],[2,2,2])
        self.assertIn('RESOURCE_BUDGET_WARNING=wall_clock_seconds',result.stdout+result.stderr)

    def test_powershell_parses_and_source_declares_one_refine_no_fly(self):
        pwsh = shutil.which('pwsh')
        if not pwsh:
            self.skipTest('PowerShell 7 unavailable')
        command = "param([string]$Source)\n$e=$null;$t=$null;[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$t,[ref]$e)|Out-Null;if($e.Count){$e|Out-String|Write-Error;exit 1}"
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'parse.ps1'
            script.write_text(command)
            result = subprocess.run([pwsh, '-NoProfile', '-File', str(script), str(SUPPORT)], capture_output=True, text=True, encoding='utf-8', check=False, cwd=ROOT, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = SUPPORT.read_text()
        self.assertEqual(text.count("-Name 'local_field_refine_declared_modes'"), 1)
        self.assertNotIn("@('--nogui','--noprompt','fly'", text)
        self.assertIn('common.simion.pa_family_cache', text)
        self.assertIn('--response-receipt', text)

    def test_frozen_stage_retains_live_public_host_context_before_python_boundary(self):
        pwsh = shutil.which('pwsh')
        if not pwsh:
            self.skipTest('PowerShell 7 unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / 'snapshot/integrations/runtime'
            common = root / 'snapshot/common/simion'
            runtime.mkdir(parents=True)
            common.mkdir(parents=True)
            for name in ('local_frontend_field_support.ps1', 'initialize_fast_adjust_pa_basis.lua', 'verify_local_frontend_fields.lua'):
                shutil.copyfile(RUNTIME / name, runtime / name)
            for name in ('export_standalone_pa.lua', 'compose_standalone_pa.lua'):
                shutil.copyfile(ROOT / 'common/simion' / name, common / name)
            run = root / 'run'
            for name in ('inputs', 'logs'):
                (run / name).mkdir(parents=True, exist_ok=True)
            (run / 'run_config.json').write_text('{}')
            script = root / 'check.ps1'
            script.write_text("""param([string]$Repo,[string]$Snapshot,[string]$Run,[string]$Python)
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
. (Join-Path $Repo 'common/resource_budget_support.ps1')
. (Join-Path $Repo 'common/simion/short_pa_path_support.ps1')
$before=$script:HostResourceStatePath
$source=(Get-Command Get-HostResourceBudget).ScriptBlock.File
$shortSource=(Get-Command New-ShortPaCopy).ScriptBlock.File
$script:ledgerCalls=0
function Invoke-HostResourceTransaction {param($Request,$StatePath)$script:ledgerCalls++;throw 'Unexpected host ledger transaction in pure preflight'}
. (Join-Path $Snapshot 'integrations/runtime/local_frontend_field_support.ps1')
function Invoke-RunToolRootContext {param($RepoRoot,$Operation)throw 'STOP_BEFORE_PYTHON_AND_NATIVE'}
$lease=[pscustomobject]@{state_path=$before};$capacity=[pscustomobject]@{status='active'}
try{Invoke-LocalFrontendFieldStage -Python $Python -RepoRoot $Snapshot -RunDirectory $Run -PreparedDirectory $Run -SimionExe 'NOT_STARTED.exe' -HostLease ([ref]$lease) -CapacitySession ([ref]$capacity) -Limits @{};throw 'boundary not reached'}catch{if($_.Exception.Message-ne'STOP_BEFORE_PYTHON_AND_NATIVE'){throw}}
if($script:HostResourceStatePath-ne$before-or(Get-Command Get-HostResourceBudget).ScriptBlock.File-ne$source){throw 'live public host context was replaced'}
if((Get-Command New-ShortPaCopy).ScriptBlock.File-ne$shortSource){throw 'live public PA input context was replaced'}
if($script:ledgerCalls-ne0){throw 'read-only preflight attempted a host ledger transaction'}
if(Test-Path (Join-Path $Snapshot 'artifacts')){throw 'private host ledger created'}
'LIVE_HOST_CONTEXT=PASS'
""", encoding='utf-8', newline='\n')
            result = subprocess.run([pwsh, '-NoProfile', '-File', str(script), str(ROOT), str(root / 'snapshot'), str(run), sys.executable],
                                    capture_output=True, text=True, encoding='utf-8', check=False, cwd=ROOT, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('LIVE_HOST_CONTEXT=PASS', result.stdout)

    def run_verifier(self, failure, mode_count=5):
        if not LUA.is_file():
            self.skipTest('Installed standalone Lua unavailable')
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            first=28 if mode_count==5 else 29
            ids=list(range(first,first+mode_count))
            model=('two' if mode_count==5 else 'three')+'_zone_linear_ring_bare_octupole_pa_plus_v1'
            if failure=='model': model='unsupported'
            count=mode_count+1 if failure=='count' else mode_count
            spec = ['local_frontend_response_verification_v4', f'model\t{model}\t{count}\t'+'\t'.join(map(str,ids)), 'grid\t16\t4\t4\t.1\t.1\t.1']
            spec.append('physical_count\t9\t8')
            spec += [f'physical\trod_{i}\t{i}\trod\t{i}\t1\t1' for i in range(1,9)]
            spec.append('physical\tendpoint_metal\t9\tendpoint\t9\t1\t1')
            for mode in ids:
                spec.append(f'response\t{mode}\tmode_{mode}.pa')
                for i in range(1, 9):
                    expected = 0 if mode >= first+2 else (-1 if mode == first+1 and i % 2 == 0 else 1)
                    policy = 'unity_anchor' if mode < first+2 and i == 1 else 'declared_sample'
                    if failure == 'missing_anchor': policy = 'declared_sample'
                    spec.append(f'sample\t{mode}\trod_{i}\t{i}\t1\t1\t1\t{expected}\t{policy}')
                policy = 'unity_anchor' if mode>=first+2 and failure!='missing_anchor' else 'declared_sample'
                expected=1 if mode>=first+2 else 0
                spec.append(f'sample\t{mode}\tendpoint_metal\t9\t1\t1\t1\t{expected}\t{policy}')
            (p / 'spec.tsv').write_text('\n'.join(spec) + '\n')
            driver = p / 'test.lua'
            driver.write_text("""local failure=arg[1];local first=assert(tonumber(arg[2]))
simion={pas={close=function() end,open=function(self,path)
 local mode=assert(tonumber(path:match('mode_(%d+)')))
 local scale=10000+mode
 if failure=='negative' then scale=-scale end
 local p={nx=16,ny=4,nz=4,dx_mm=.1,dy_mm=.1,dz_mm=.1,potential_type='electric'}
 if failure=='grid' then p.nx=17 end
 function p:point(x)
  if failure=='nonfinite' then return 0/0,true elseif failure=='flag' then return scale,false elseif failure=='zero' then return 0,true end
  local expected
  if mode>=first+2 then expected=x==9 and 1 or 0 else expected=x==9 and 0 or (mode==first+1 and x%2==0 and -1 or 1) end
  if failure=='basis' and x==2 then expected=expected+.5 end
  return scale*expected,true
 end
 function p:close() end
 return p
end}}
arg={""" + json.dumps(str(p / 'spec.tsv').replace('\\', '/')) + ',' + json.dumps(str(p / 'output.tsv').replace('\\', '/')) + '}\n' + 'dofile(' + json.dumps(str(RUNTIME / 'verify_local_frontend_fields.lua').replace('\\', '/')) + ')\n')
            result = subprocess.run([str(LUA), str(driver), failure, str(first)], capture_output=True, text=True, check=False, cwd=p, timeout=30)
            if result.returncode == 0:
                result.measurements = (p / 'output.tsv').read_text()
            return result

    def test_plain_lua_reopens_all_five_and_accepts_valid_declared_samples(self):
        for scale in ('none','negative'):
            result = self.run_verifier(scale)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('scope=grid_and_declared_samples_only', result.stdout)
            self.assertIn('basis_reference_v',result.measurements)
            self.assertIn('10028',result.measurements)

    def test_plain_lua_accepts_declared_three_zone_six_measured_modes(self):
        for sign in ('none','negative'):
            result=self.run_verifier(sign,mode_count=6)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('modes=6',result.stdout)
            self.assertIn('three_zone_linear_ring_bare_octupole_pa_plus_v1',result.stdout)
            self.assertEqual(result.measurements.count('unity_anchor'),6)

    def test_plain_lua_rejects_grid_nonfinite_basis_and_electrode_mismatch(self):
        for failure in ('grid', 'nonfinite', 'basis', 'flag', 'zero', 'missing_anchor', 'model', 'count'):
            with self.subTest(failure=failure):
                result = self.run_verifier(failure)
                self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
