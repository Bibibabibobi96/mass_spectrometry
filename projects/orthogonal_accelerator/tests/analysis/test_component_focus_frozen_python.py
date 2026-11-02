"""Real leaf Python snapshot preparation/analysis; no SIMION process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from projects.orthogonal_accelerator.tests.analysis import test_component_focus_analysis as fixtures
from projects.orthogonal_accelerator.analysis.component_focus_simion_source import materialize
from projects.orthogonal_accelerator.analysis.component_focus_analysis import analyze
from common.contracts.write_run_manifest import build_run_manifest

REPO = Path(__file__).resolve().parents[4]
ENTRY = REPO / "projects/orthogonal_accelerator/simion/run_component_focus_flight.ps1"

SCRIPT = r'''param($Repo,$Entry,$Root,$Python,$Data,$Mode)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$support=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'common/contracts/run_artifact_support.ps1'),[ref]$null,[ref]$null)
$node=$support.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Copy-VerifiedRunInput'},$true)
Invoke-Expression $node.Extent.Text
$ast=[Management.Automation.Language.Parser]::ParseFile($Entry,[ref]$null,[ref]$null)
$prepare=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.CommandAst]-and$n.GetCommandName()-eq'Initialize-FocusFrozenPython'},$true))
$native=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.CommandAst]-and$n.CommandElements[0].Extent.Text-eq'$SimionExe'},$true))
if($prepare.Count-ne1-or$native.Count-ne2-or$prepare[0].Extent.StartOffset-ge$native[0].Extent.StartOffset){throw 'Actual frozen preparation must precede either native command'}
foreach($name in @('Invoke-FocusFrozenPython','Initialize-FocusFrozenPython')){
 $node=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq$name},$true)
 Invoke-Expression $node.Extent.Text
}
$modules=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.CommandAst]-and$n.GetCommandName()-eq'Invoke-FocusFrozenPython'},$true)|ForEach-Object{
 $elements=@($_.CommandElements);for($i=0;$i-lt$elements.Count-1;$i++){if($elements[$i].Extent.Text-eq'-Module'){$elements[$i+1].Extent.Text}}
})
if(($modules-join',')-ne'msplatform.ion_release.cylinder,projects.orthogonal_accelerator.analysis.component_focus_simion_source,projects.orthogonal_accelerator.analysis.component_focus_analysis'){throw 'Actual leaf scientific invocations differ'}
New-Item -ItemType Directory -Path (Join-Path $Root inputs),(Join-Path $Root results),(Join-Path $Root simion) -Force|Out-Null
$dataFiles=Get-Content $Data -Raw|ConvertFrom-Json -AsHashtable
foreach($pair in $dataFiles.GetEnumerator()){Copy-VerifiedRunInput $pair.Value (Join-Path $Root ('inputs/'+$pair.Key))|Out-Null}
$config=Join-Path $Root 'run_config.json'
@{schema_version=2;project='orthogonal_accelerator';run_id='20261031_010000__test__python__focus-snapshot';mode='component_focus_flight';inputs=@{};parameters=@{sentinel='preserve'};paths=@{artifact_root='sentinel-frozen-root'};artifact_retention=@{policy_version=1;class='compact';reason=$null};capacity_ledger_lifecycle=@{enabled=$true;light_evidence_budget_bytes=26214400}}|ConvertTo-Json -Depth 20|Set-Content $config -Encoding utf8
$oldPath=$env:PYTHONPATH;$env:PYTHONPATH=$Repo
try{
 $sourceAlias=Join-Path (Split-Path -Parent $Root) '中文源码'
 $OutputEncoding=[Text.Encoding]::ASCII
 $savedEncoding=$OutputEncoding
 New-Item -ItemType Junction -Path $sourceAlias -Target $Repo|Out-Null
 try{
  $context=Initialize-FocusFrozenPython -RepoRoot $sourceAlias -RunConfig $config -Python $Python -CampaignPath (Join-Path $Root 'inputs/campaign.json')
 }finally{Remove-Item -LiteralPath $sourceAlias -Force}
 if(-not[object]::ReferenceEquals($OutputEncoding,$savedEncoding)){throw 'Package enumeration changed caller OutputEncoding'}
 if($Mode-eq'failure'){
  $cases=@()
  foreach($relative in @('projects/orthogonal_accelerator/config/component_contract.json','projects/orthogonal_accelerator/analysis/accelerator_time_focus.py','src/msplatform/ion_release/cylinder.py')){
   $path=Join-Path $context.code_root $relative;$bytes=[IO.File]::ReadAllBytes($path);Remove-Item -LiteralPath $path
   try{
    $vendorCalls=0
    Invoke-FocusFrozenPython -Python $Python -CodeRoot $context.code_root -OriginsPath $context.origins_path -Arguments @((Join-Path $Root 'inputs/campaign.json'))
    $exitCode=$LASTEXITCODE
    if($exitCode-eq0){$vendorCalls++;throw 'Missing frozen dependency fell back to checkout'}
    $cases+=@{relative=$relative;exit_code=$exitCode;vendor_calls=$vendorCalls}
   }finally{[IO.File]::WriteAllBytes($path,$bytes)}
  }
  $cases|ConvertTo-Json -Depth 10|Set-Content (Join-Path $Root 'results/failure_cases.json') -Encoding utf8
 }else{
  $receipt=Join-Path $Root 'inputs/release_receipt.json';$release=Join-Path $Root 'inputs/release.csv'
  Invoke-FocusFrozenPython -Python $Python -CodeRoot $context.code_root -OriginsPath $context.origins_path -Module msplatform.ion_release.cylinder -Arguments @('--materialize',(Join-Path $Root 'inputs/release_spec.json'),'--state-table',$release,'--receipt',$receipt)
  if($LASTEXITCODE-ne0){throw 'Frozen release failed'}
  Invoke-FocusFrozenPython -Python $Python -CodeRoot $context.code_root -OriginsPath $context.origins_path -Module projects.orthogonal_accelerator.analysis.component_focus_simion_source -Arguments @('--release-receipt',$receipt,'--campaign',(Join-Path $Root 'inputs/campaign.json'),'--provider-plan',(Join-Path $Root 'inputs/component_focus_pa_plan.json'),'--resolved-projection',(Join-Path $Root 'inputs/resolved_projection.json'),'--fly2',(Join-Path $Root 'simion/source.fly2'),'--source-states',(Join-Path $Root 'simion/source.lua'),'--receipt',(Join-Path $Root 'results/source_projection.json'))
  if($LASTEXITCODE-ne0){throw 'Frozen projection failed'}
  Invoke-FocusFrozenPython -Python $Python -CodeRoot $context.code_root -OriginsPath $context.origins_path -Module projects.orthogonal_accelerator.analysis.component_focus_analysis -Arguments @('--events',(Join-Path $Root 'inputs/events.csv'),'--release-receipt',$receipt,'--campaign',(Join-Path $Root 'inputs/campaign.json'),'--output',(Join-Path $Root 'results/analysis.json'))
  if($LASTEXITCODE-ne0){throw 'Frozen scientific analysis failed'}
 }
 if($env:PYTHONPATH-cne$Repo){throw 'Scientific adapter changed caller environment'}
}finally{$env:PYTHONPATH=$oldPath}
'''


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
class FocusFrozenPythonTests(unittest.TestCase):
    def data(self, root: Path) -> tuple[dict[str, str], dict, dict[str, Path]]:
        """Use an explicit sealed reference for native replay, ordinary small fixture otherwise."""
        reference = os.environ.get("OA_FOCUS_FROZEN_REFERENCE_RUN")
        if reference:
            parent = Path(reference)
            expected = json.loads((parent / "results/focus_analysis.json").read_text(encoding="utf-8-sig"))
            pairs = {name: str(parent / "inputs" / name) for name in (
                "campaign.json", "campaign_template.json", "release_spec.json",
                "component_focus_pa_plan.json", "resolved_projection.json")}
            pairs["events.csv"] = str(parent / "simion/component_focus.events.csv")
            outputs = {"inputs/release.csv": parent / "inputs/release.csv",
                       "simion/source.fly2": parent / "simion/component_focus_input.fly2",
                       "simion/source.lua": parent / "simion/component_focus.source_states.lua"}
            return pairs, expected, outputs
        fixture = fixtures.ComponentFocusAnalysisTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        campaign = json.loads(fixture.campaign.read_text(encoding="utf-8"))
        spec = root / "spec.json"
        spec.write_text(json.dumps(campaign["release_spec"]), encoding="utf-8")
        plan = root / "plan.json"
        plan.write_text(json.dumps({"role": "orthogonal_accelerator_component_focus_pa_plan",
            "numerical_domain": {"local_exit_z_mm": 6}, "layout": {"gap_1_mm": 4, "gap_2_mm": 30}}), encoding="utf-8")
        projection = root / "projection.json"
        projection.write_text(json.dumps(campaign["simion_projection"]), encoding="utf-8")
        events = fixture.write_events()
        expected = analyze(events, fixture.receipt, fixture.campaign)
        fly, source = root / "expected.fly2", root / "expected.lua"
        materialize(fixture.receipt, fixture.campaign, plan, fly, source, campaign["simion_projection"])
        return {"campaign.json": str(fixture.campaign), "campaign_template.json": str(fixture.campaign),
                "release_spec.json": str(spec), "component_focus_pa_plan.json": str(plan),
                "resolved_projection.json": str(projection), "events.csv": str(events)}, expected, {
                    "inputs/release.csv": fixture.state, "simion/source.fly2": fly, "simion/source.lua": source}

    def invoke(self, base: Path, mode: str):
        sources, expected, outputs = self.data(base)
        request = base / "data.json"
        request.write_text(json.dumps(sources), encoding="utf-8")
        script = base / "fixture.ps1"
        script.write_text(SCRIPT, encoding="utf-8")
        run = base / "run"
        actual = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(script),
            str(REPO), str(ENTRY), str(run), sys.executable, str(request), mode], cwd=base,
            capture_output=True, text=True, encoding="utf-8", timeout=90)
        self.assertEqual(actual.returncode, 0, actual.stdout + actual.stderr)
        return run, expected, outputs

    def test_snapshot_executes_real_prepare_and_analysis_without_checkout_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            run, expected, outputs = self.invoke(Path(directory), "success")
            actual = json.loads((run / "results/analysis.json").read_text(encoding="utf-8"))
            self.assertEqual({k: v for k, v in actual.items() if k != "identity"},
                             {k: v for k, v in expected.items() if k != "identity"})
            for relative, path in outputs.items():
                self.assertEqual((run / relative).read_bytes(), path.read_bytes(), relative)
            config = json.loads((run / "run_config.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(config["schema_version"], 2)
            self.assertEqual(config["parameters"]["sentinel"], "preserve")
            self.assertEqual(config["paths"]["artifact_root"], "sentinel-frozen-root")
            self.assertEqual(config["capacity_ledger_lifecycle"]["light_evidence_budget_bytes"], 26214400)
            code = (run / "inputs/code").resolve()
            copied = list(code.rglob("*.py")) + list(code.rglob("*.json"))
            recorded = {Path(value) for key, value in config["inputs"].items() if key.startswith("python_code__")}
            self.assertEqual(set(copied), recorded)
            manifest = build_run_manifest(run / "run_config.json", "success",
                output_paths=[run / "results/python_execution.json"])
            self.assertEqual(set(manifest["inputs"]), set(config["inputs"]))
            self.assertTrue(all(row["exists"] and row["bytes"] >= 0 and row["sha256"]
                                for row in manifest["inputs"].values()))
            self.assertFalse(any(path.name.startswith("test_") for path in copied))
            origins = json.loads((run / "results/python_execution.json").read_text(encoding="utf-8"))
            self.assertEqual([row["module"] for row in origins], ["preflight", "msplatform.ion_release.cylinder",
                "projects.orthogonal_accelerator.analysis.component_focus_simion_source",
                "projects.orthogonal_accelerator.analysis.component_focus_analysis"])
            self.assertTrue(all(Path(path).is_relative_to(code) for row in origins for path in row["module_paths"].values()))
            self.assertTrue(all(Path(row["geometry_contract_path"]).is_relative_to(code) for row in origins))

    def test_missing_snapshot_code_or_geometry_fails_before_vendor_despite_active_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            run, _, _ = self.invoke(Path(directory), "failure")
            cases = json.loads((run / "results/failure_cases.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(len(cases), 3)
            self.assertTrue(all(row["exit_code"] != 0 and row["vendor_calls"] == 0 for row in cases))
