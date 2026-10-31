"""Thin real-wrapper MATLAB closure transport; no commercial invocation."""
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[4]
PROJECT = Path(__file__).resolve().parents[2]


def ps(value):
    return "'" + str(value).replace("'", "''") + "'"


class FrozenMatlabClosureTests(unittest.TestCase):
    def run_boundary(self, workflow, missing=False, release_gate=False):
        missing_path = ('projects/rf_multipole_ion_optics/comsol/visit_rf_particle_windows.m'
                        if missing is True else missing if missing else None)
        runner = PROJECT / 'workflows' / workflow / 'run_comsol.ps1'
        support = REPO / 'projects/rf_multipole_ion_optics/runtime/frozen_python_package.ps1'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / 'fixture.ps1'
            # Use actual parsed production assignments/command, not a second declaration.
            script.write_text(r'''
$ErrorActionPreference='Stop'
. SUPPORT
function Copy-VerifiedRunInput {param($Source,$Destination)
 New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination)|Out-Null
 Copy-Item -LiteralPath $Source -Destination $Destination -ErrorAction Stop
}
function Get-RunFileSha256 {param($Path) (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash}
$root=ROOT;$repoRoot=Join-Path $root 'active';$frozenCodeRoot=Join-Path $root 'inputs/code'
$inputDir=Join-Path $root 'inputs';$analysisFiles=@();$frozenPythonRelativePaths=@()
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile(RUNNER,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'wrapper parse failed'}
$declaration=@($ast.FindAll({param($node) $node-is[System.Management.Automation.Language.AssignmentStatementAst]-and$node.Left-is[System.Management.Automation.Language.VariableExpressionAst]-and$node.Left.VariablePath.UserPath-eq'frozenMatlabRelativePaths'},$true))
Invoke-Expression $declaration[0].Extent.Text
foreach($relative in $frozenMatlabRelativePaths){
 $source=Join-Path REPO $relative
 $prefix='projects/rf_multipole_ion_optics/'
 if($relative.StartsWith($prefix)){
  $overlay=Join-Path PROJECT $relative.Substring($prefix.Length)
  if(Test-Path -LiteralPath $overlay -PathType Leaf){$source=$overlay}
 }
 $target=Join-Path $repoRoot $relative
 New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target)|Out-Null
 Copy-Item -LiteralPath $source -Destination $target
}
$missingDependency=MISSING_DEPENDENCY
if($missingDependency){Remove-Item -LiteralPath (Join-Path $repoRoot $missingDependency)}
$normal=@($ast.FindAll({param($node) $node-is[System.Management.Automation.Language.AssignmentStatementAst]-and$node.Left-is[System.Management.Automation.Language.VariableExpressionAst]-and$node.Left.VariablePath.UserPath-in@('frozenPythonPackage','frozenAnalysisPackage')},$true))
$command=@($normal|ForEach-Object{$_.FindAll({param($node) $node-is[System.Management.Automation.Language.CommandAst]-and$node.GetCommandName()-eq'New-FrozenPythonPackage'},$true)})
if($command.Count-ne1){throw 'normal MATLAB closure command is not unique'}
try{$package=& ([scriptblock]::Create($command[0].Extent.Text))}catch{if($missingDependency-and$_.Exception.Message.Contains((Split-Path -Leaf $missingDependency))){exit 0};throw}
if($missingDependency){throw 'missing MATLAB dependency was accepted'}
Assert-FrozenPythonPackage -Package $package
$reader=Get-FrozenPythonPackageFile -Package $package -RelativePath 'common/comsol/read_comsol_mesh_size_controls.m'
if(-not(Test-Path -LiteralPath (Join-Path $package.code_root 'projects/rf_multipole_ion_optics/comsol/plan_rf_exact_birth_releases.m'))){throw 'group helper absent from real frozen closure'}
[IO.Directory]::Move($repoRoot,$repoRoot+'.disabled')
if(-not(Test-Path -LiteralPath $reader -PathType Leaf)-or$reader.StartsWith($repoRoot+[IO.Path]::DirectorySeparatorChar)){throw 'Typed size reader escaped frozen closure after active-source removal'}
$frozenAnalysisPackage=$package;$ReleaseConstructionGate=RELEASE_GATE
$name=if(WORKFLOW-eq'interface_readiness'){'taskScript'}else{'massScanTask'}
$assignments=@($ast.FindAll({param($node) $node-is[System.Management.Automation.Language.AssignmentStatementAst]-and$node.Left-is[System.Management.Automation.Language.VariableExpressionAst]-and$node.Left.VariablePath.UserPath-eq$name},$true))
Invoke-Expression $assignments[-1].Extent.Text
$selected=if($name-eq'taskScript'){$taskScript}else{$massScanTask}
if(-not$selected.StartsWith($package.code_root+[IO.Path]::DirectorySeparatorChar)-or-not(Test-Path -LiteralPath $selected -PathType Leaf)){throw 'native task escaped frozen closure'}
Assert-FrozenPythonPackage -Package $package
exit 0
'''.replace('SUPPORT', ps(support)).replace('ROOT', ps(root)).replace('RUNNER', ps(runner))
.replace('REPO', ps(REPO)).replace('PROJECT', ps(PROJECT)).replace('MISSING_DEPENDENCY', ps(missing_path) if missing_path else '$null')
.replace('RELEASE_GATE', '$true' if release_gate else '$false').replace('WORKFLOW', ps(workflow)), encoding='utf-8', newline='\n')
            result = subprocess.run(['pwsh','-NoProfile','-File',str(script)], cwd=root,
                                    timeout=30,capture_output=True,text=True,encoding='utf-8',errors='replace')
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_real_wrapper_selects_only_frozen_matlab_task_after_source_removal(self):
        self.run_boundary('interface_readiness')
        self.run_boundary('interface_readiness',release_gate=True)
        self.run_boundary('mass_filter_reference')

    def test_missing_matlab_dependency_fails_before_native_selection(self):
        for workflow in ('interface_readiness','mass_filter_reference'):
            for missing in (True, 'common/comsol/read_comsol_mesh_size_controls.m'):
                with self.subTest(workflow=workflow, missing=missing):
                    self.run_boundary(workflow,missing=missing)


if __name__=='__main__':
    unittest.main()
