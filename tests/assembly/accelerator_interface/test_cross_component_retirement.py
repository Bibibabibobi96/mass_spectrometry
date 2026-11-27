"""Retired cross-component re-release fails before any native owner."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
RESOURCES = ROOT / 'src/msplatform/workflows/resources'


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell 7 required')
class CrossComponentRetirementTests(unittest.TestCase):
    def test_measured_and_centroid_flights_refuse_before_owner(self):
        entry = RESOURCES / 'prepared_joint_execute.ps1'
        self.assertNotIn('PreparedSourceMode', entry.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for source_mode in ('measured_population', 'centroid_probe'):
                result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-File', str(entry),
                    '-PreparedJointWorkbenchRunPath', str(root/'missing'), '-ContractPath', str(root/'contract'),
                    '-PreparedSourceMode', source_mode, '-RepoRoot', str(root)], cwd=root,
                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((root/'artifacts').exists())
            for args in (('-AnalyzeRunPath', 'missing', '-ContractPath', 'missing'),
                         ('-ResumeFinalization', '-RunId', 'historical')):
                result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-File', str(entry),
                    *args, '-RepoRoot', str(root), '-PythonExe', str(root/'missing-python')], cwd=root,
                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('measured-population re-release is retired', result.stdout+result.stderr)


    def test_full_joint_rejects_prepared_and_segmented_before_any_owner(self):
        entry = RESOURCES / 'accelerator_interface.ps1'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for arguments in ((),):
                result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-File', str(entry),
                    '-FullJoint', *arguments, '-RepoRoot', str(root)], cwd=root, capture_output=True,
                    text=True, encoding='utf-8', errors='replace', timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Legacy cross-component handoff and re-release are retired', result.stdout+result.stderr)
                self.assertFalse((root/'artifacts').exists())

    def test_continuous_owner_restores_root_context_on_success_and_failure(self):
        entry = RESOURCES / 'accelerator_interface.ps1'
        support = ROOT / 'src/msplatform/execution/resources/run_artifact_support.ps1'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = root / 'child.ps1'
            child.write_text("param($Fail)\n$env:MASS_SPECTROMETRY_ARTIFACT_ROOT='child-drift'\n"
                             "if($Fail){throw 'CONTINUOUS_CHILD_FAILURE'}\n", encoding='utf-8')
            harness = root / 'context.ps1'
            harness.write_text(r'''param($Entry,$Support,$Root,$Child)
. $Support
$ast=[Management.Automation.Language.Parser]::ParseFile($Entry,[ref]$null,[ref]$null)
$fn=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Invoke-JointOwnerStage'},$true)
Invoke-Expression $fn.Extent.Text
$sourceRoot=$Root;$pathEnvironment=@{MASS_SPECTROMETRY_ARTIFACT_ROOT='selected'}
$env:MASS_SPECTROMETRY_ARTIFACT_ROOT='parent'
foreach($fail in @($false,$true)){
 $caught=$false
 try{Invoke-JointOwnerStage -Script $Child -Arguments @{Fail=$fail}}catch{$caught=$_.Exception.Message-eq'CONTINUOUS_CHILD_FAILURE'}
 if($caught-ne$fail){throw 'child failure propagation differs'}
 if($env:MASS_SPECTROMETRY_ARTIFACT_ROOT-cne'parent'){throw 'child environment escaped the scoped context'}
}
Write-Output 'ROOT_CONTEXT=PASS'
''', encoding='utf-8')
            result = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-File', str(harness), str(entry),
                str(support), str(ROOT), str(child)], cwd=root, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('ROOT_CONTEXT=PASS', result.stdout)



if __name__ == '__main__':
    unittest.main()
