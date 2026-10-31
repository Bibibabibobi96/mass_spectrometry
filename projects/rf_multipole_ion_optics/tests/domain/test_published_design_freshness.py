"""Exercise fixed-profile admission using the original frozen resolver."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[2]
REPO = PROJECT.parents[1]


class PublishedDesignFreshnessTests(unittest.TestCase):
    def test_selected_profiles_reject_stale_and_ignore_future_live_sources(self):
        for profile in ("interface", "mass_filter"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                script = root / "check.ps1"
                script.write_text(r'''param($Repo,$Python,$Root,$Profile)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
. (Join-Path $Repo 'projects/rf_multipole_ion_optics/runtime/frozen_python_package.ps1')
$snapshot=Join-Path $Root 'snapshot'
$facts=New-RfPublishedDesignFreshnessPackage -Python $Python -SourceRoot $Repo -SnapshotRoot $snapshot -Profile $Profile
if($facts.profile-cne$Profile-or-not(Test-Path $facts.resolved_path)){throw 'Lost selected checked publication'}
if($facts.execution.module_stdout-notlike'*RESOLVED_DESIGN=PASS*'){throw 'Original checker did not execute'}
$request=@($facts.package.files|Where-Object{$_.relative_path-like'*/requests/*.json'})
if($request.Count-ne1){throw 'More than the selected governance request was frozen'}
$source=Join-Path $Root 'source'
foreach($entry in $facts.package.files){
 $target=Join-Path $source $entry.relative_path
 New-Item -ItemType Directory -Force -Path (Split-Path $target)|Out-Null
 Copy-Item -LiteralPath $entry.path -Destination $target
}
$sourceFacts=New-RfPublishedDesignFreshnessPackage -Python $Python -SourceRoot $source -SnapshotRoot (Join-Path $Root 'source_good') -Profile $Profile
$resolvedRelative=[IO.Path]::GetRelativePath($snapshot,$facts.resolved_path)
[IO.File]::AppendAllText((Join-Path $source $resolvedRelative),' ')
$failed=$false
try{New-RfPublishedDesignFreshnessPackage -Python $Python -SourceRoot $source -SnapshotRoot (Join-Path $Root 'bad') -Profile $Profile|Out-Null}catch{$failed=$true}
if(-not$failed){throw 'Stale selected publication was accepted'}
# A subsequent live/default change cannot rebind the completed frozen check.
[IO.File]::WriteAllText((Join-Path $source $request[0].relative_path),'{}')
$recheck=Invoke-IsolatedFrozenPythonModule -Python $Python -Package $sourceFacts.package `
 -Module 'projects.rf_multipole_ion_optics.analysis.resolve_contract' `
 -Arguments @('--profile',$Profile,'--check') -RequiredModuleNames @('projects.rf_multipole_ion_optics.analysis.resolve_contract') `
 -ForbiddenRoots @($Repo,$source)
if($recheck.module_stdout-notlike'*RESOLVED_DESIGN=PASS*'){throw 'Frozen check read later defaults'}
@{profile=$Profile;files=$facts.package.files.Count;resolved=$resolvedRelative;stale_rejected=$failed}|ConvertTo-Json -Compress
''', encoding="utf-8")
                result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(REPO),
                                         sys.executable, str(root), profile], cwd=root,
                                        capture_output=True, text=True, encoding="utf-8", timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("STALE=", result.stdout + result.stderr)
                facts = json.loads(result.stdout.splitlines()[-1])
                self.assertEqual(facts["profile"], profile)
                self.assertTrue(facts["stale_rejected"])

    def test_consumers_use_only_their_checked_snapshot_and_propagate_failure(self):
        paths = (("interface_readiness/run_comsol.ps1", "interface"),
                 ("interface_readiness/run_simion.ps1", "interface"),
                 ("mass_filter_reference/run_simion.ps1", "mass_filter"))
        for relative, profile in paths:
            source = (PROJECT / "workflows" / relative).read_text(encoding="utf-8")
            start = source.index("    $publishedDesignFreshness = New-RfPublishedDesignFreshnessPackage")
            end = source.index("-Depth 16", start) + len("-Depth 16")
            block = source[start:end]
            with self.subTest(consumer=relative), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                script = root / "wire.ps1"
                script.write_text(r'''param($InputRoot,$Python,$Expected)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$inputDir=$InputRoot;$repoRoot='selected-source';$python=$Python;$script:expectedPython=$Python
$script:observed=@();$script:fail=$false
function New-RfPublishedDesignFreshnessPackage {param($Python,$SourceRoot,$SnapshotRoot,$Profile)
 if($Profile-cne$Expected-or$SourceRoot-cne'selected-source'-or$Python-cne$script:expectedPython){throw 'Wrong admission parameters'}
 $script:observed+=@($Profile)
 if($script:fail){throw 'INJECTED_FRESHNESS_FAILURE'}
 return @{resolved_path=(Join-Path $SnapshotRoot 'checked.json')}
}
function Write-RunJson {param($Path,$Value,$Depth)}
''' + block + r'''
if($frozenResolved-cne(Join-Path (Join-Path $inputDir 'published_design_snapshot') 'checked.json')){throw 'Consumer bypassed checked resolved'}
$script:fail=$true;$downstream=0;$caught=$null
try{
''' + block + r'''
 $downstream++
}catch{$caught=$_.Exception.Message}
if($caught-cne'INJECTED_FRESHNESS_FAILURE'-or$downstream-ne0-or$script:observed.Count-ne2){throw 'Admission failure did not stop consumer'}
'CONSUMER_ADMISSION=PASS'
''', encoding="utf-8")
                result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(root),
                                         sys.executable, profile], cwd=root, capture_output=True, text=True,
                                        encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("CONSUMER_ADMISSION=PASS", result.stdout)
