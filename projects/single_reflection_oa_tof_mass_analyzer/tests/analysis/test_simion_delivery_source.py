"""Exercise the existing producer's frozen-ION boundary without SIMION."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[4]
PROJECT = ROOT / "projects/single_reflection_oa_tof_mass_analyzer"


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell required")
class FrozenIonDeliveryTests(unittest.TestCase):
    def test_long_frozen_lua_uses_public_code_alias_without_changing_canonical_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code = root / ("frozen-code-" + "x"*70) / ("nested-" + "y"*70)
            lua = code / "projects/analyzer/simion/verify_iob_runtime_contract.lua"
            lua.parent.mkdir(parents=True)
            lua.write_text("frozen verifier bytes", encoding="utf-8")
            self.assertGreaterEqual(len(str(lua)), 260)
            script = root / "check.ps1"
            script.write_text(r'''param($Repo,$Code,$Lua,$Artifacts)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/build_formal_delivery.ps1'),[ref]$null,[ref]$null)
$node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-SimionLua'},$true)
Invoke-Expression $node.Extent.Text
$repoRoot=$Code;$expectedRunRoot=$Artifacts;$script:codeExecutionAlias=$null
[IO.Directory]::CreateDirectory($expectedRunRoot)|Out-Null
Write-RunJson -Path (Join-Path $expectedRunRoot 'run_config.json') -Value @{paths=@{execution_root=(Join-Path $Artifacts 'common/execution_aliases')}}
$script:nativeSequence=0;$nativeOperations=[Collections.Generic.List[object]]::new()
function Invoke-OwnedSimionArguments {param($ArgumentList,$OperationId)
  if($ArgumentList[3].Length-ge260){throw 'Native script still exceeds MAX_PATH'}
  if([IO.File]::ReadAllText($ArgumentList[3])-cne'frozen verifier bytes'){throw 'Frozen script transport changed bytes'}
  if($ArgumentList[4]-cne'canonical-iob-path'){throw 'Canonical native input was rewritten'}
  return @{observation=@{exit_confirmed=$true;returncode=0};managed_process_completion=@{}}
}
try{Invoke-SimionLua $Lua @('canonical-iob-path')
  if($null-eq$script:codeExecutionAlias-or$nativeOperations.Count-ne1){throw 'Owned code transport missing'}
}finally{if($null-ne$script:codeExecutionAlias){Remove-RunExecutionAlias -ExecutionAlias $script:codeExecutionAlias.execution_alias -TargetDirectory $Code}}
if(-not(Test-Path -LiteralPath $Lua)){throw 'Frozen input was deleted'}
''', encoding="utf-8", newline="\n")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(ROOT), str(code), str(lua), str(root / "artifacts")],
                                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(list((root / "artifacts/common/execution_aliases").glob("run_*")))

    def test_original_rows_clocks_and_bytes_are_copied_and_invalid_sources_fail_before_native(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "inputs"
            inputs.mkdir()
            good = "0.125,524,1,1,2,3,4,5,6,1,0\n0.875,524,1,7,8,9,10,11,12,1,0\n"
            (inputs / "good.ion").write_text(good, encoding="ascii", newline="\n")
            for name, value in {"count": good.splitlines()[0]+"\n", "mass": good.replace(",524,", ",525,"),
                                "charge": good.replace(",524,1,", ",524,-1,"),
                                "finite": good.replace(",4,5,", ",nan,5,")}.items():
                (inputs / (name+".ion")).write_text(value, encoding="ascii")
            (root / "outside.ion").write_text(good, encoding="ascii")
            script = r'''
param($Repo,$Producer,$RunRoot,$Python)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$ast=[Management.Automation.Language.Parser]::ParseFile($Producer,[ref]$null,[ref]$null)
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name-eq'Copy-ComponentFrozenIon'},$true)
Invoke-Expression $function.Extent.Text
$results=@{}
foreach($name in @('good','count','mass','charge','finite','outside')){
 $source=if($name-eq'outside'){Join-Path $RunRoot 'outside.ion'}else{Join-Path $RunRoot ('inputs/'+$name+'.ion')}
 $target=Join-Path $RunRoot ('simion/'+$name+'.ion')
 try{$identity=Copy-ComponentFrozenIon -Source $source -Destination $target -RunRoot $RunRoot -Count 2 -MassAmu 524 -Charge 1 -Python $Python -RepoRoot $Repo
  $results[$name]=@{ok=$true;identity=$identity}
 }catch{$results[$name]=@{ok=$false;error=$_.Exception.Message}}
}
$results|ConvertTo-Json -Depth 8
'''
            command = root / "exercise.ps1"
            command.write_text(script, encoding="utf-8", newline="\n")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(command), str(ROOT),
                str(PROJECT / "simion/workbench/build_formal_delivery.ps1"), str(root), sys.executable],
                cwd=ROOT, timeout=120, check=True, capture_output=True, text=True, encoding="utf-8")
            facts = json.loads(result.stdout)
            self.assertTrue(facts["good"]["ok"], facts["good"])
            self.assertEqual((root / "simion/good.ion").read_bytes(), (inputs / "good.ion").read_bytes())
            self.assertEqual(facts["good"]["identity"]["bytes"], len(good.encode("ascii")))
            for name in ("count", "mass", "charge", "finite", "outside"):
                with self.subTest(name=name):
                    self.assertFalse(facts[name]["ok"])
                    self.assertFalse((root / f"simion/{name}.ion").exists())


if __name__ == "__main__":
    unittest.main()
