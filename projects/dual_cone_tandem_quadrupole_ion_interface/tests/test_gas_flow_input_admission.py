"""Real frozen original geometry check; no COMSOL or active source fallback."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parents[1]


class GasFlowInputAdmissionTests(unittest.TestCase):
    def test_frozen_geometry_pair_and_stale_failure_stop_downstream(self):
        source = (PROJECT / "workflows/gas_assisted_transport/run_axisymmetric_gas_flow.ps1").read_text(encoding="utf-8")
        start = source.index("  $geometrySnapshotRoot=Join-Path")
        end = source.index("  foreach($key in $schedulerFiles.Keys){", start)
        block = source[start:end]
        code_paths = (
            "projects/dual_cone_tandem_quadrupole_ion_interface/analysis/resolve_geometry.py",
            "projects/dual_cone_tandem_quadrupole_ion_interface/analysis/__init__.py",
            "projects/rf_multipole_ion_optics/core/round_rod_geometry.py",
            "projects/rf_multipole_ion_optics/core/__init__.py",
        )
        for scenario in ("normal", "stale", "source_changed"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source_root = root / "active_source"
                for relative in code_paths:
                    target = source_root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(REPO / relative, target)
                frozen_config = root / "inputs/project_snapshot/config"
                frozen_config.mkdir(parents=True)
                for filename in ("baseline.json", "resolved_geometry.json"):
                    (frozen_config / filename).write_bytes((PROJECT / "config" / filename).read_bytes())
                if scenario == "stale":
                    with (frozen_config / "resolved_geometry.json").open("a", encoding="utf-8") as stream:
                        stream.write(" ")
                fixture = root / "admit.ps1"
                fixture.write_text(r'''param($PublicRepo,$Python,$Root,$SourceRoot,$Scenario)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $PublicRepo 'common/contracts/run_artifact_support.ps1')
$realCopy=(Get-Command Copy-VerifiedRunInput).ScriptBlock
$script:copies=0
function Copy-VerifiedRunInput {param($Source,$Destination)
 $result=& $realCopy -Source $Source -Destination $Destination
 $script:copies++
 if($Scenario-eq'source_changed'-and$script:copies-eq4){
  foreach($p in Get-ChildItem -LiteralPath $SourceRoot -Recurse -File -Filter '*.py'){
   [IO.File]::WriteAllText($p.FullName,"raise RuntimeError('ACTIVE_REPO_FALLBACK')")
  }
 }
 return $result
}
$repoRoot=$SourceRoot;$python=$Python;$package=@{input_dir=(Join-Path $Root 'inputs')}
$env:PYTHONPATH=$SourceRoot
$frozen=@{geometry_baseline=(Join-Path $Root 'inputs/project_snapshot/config/baseline.json');resolved_geometry=(Join-Path $Root 'inputs/project_snapshot/config/resolved_geometry.json')}
$downstream=0;$caught=$null
Push-Location $SourceRoot
try{
 try{
''' + block + r'''
  $downstream++
 }catch{$caught=$_.Exception.Message}
}finally{Pop-Location}
if($Scenario-eq'stale'){
 if($caught-cne'Frozen dual-cone baseline and resolved geometry differ.'-or$downstream-ne0){throw 'Stale input did not stop prepare'}
}else{
 if($caught-or$downstream-ne1){throw ('Valid frozen input rejected: '+$caught)}
 if(-not$geometryValidationEnvironment.numpy.version-or-not$geometryValidationEnvironment.numpy.module_path){throw 'Actual NumPy dependency was not recorded'}
 foreach($entry in $geometryValidationEnvironment.owned_modules.PSObject.Properties){
  foreach($path in $entry.Value){if(-not[IO.Path]::GetFullPath($path).StartsWith([IO.Path]::GetFullPath($geometrySnapshotRoot)+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Owned module escaped frozen snapshot'}}
 }
}
if($script:copies-ne4-or$failureStage-cne'geometry_input_freshness'){throw 'Incorrect frozen closure or failure stage'}
@{scenario=$Scenario;copies=$script:copies;downstream=$downstream;source_poisoned=($Scenario-eq'source_changed');numpy_version=$(if($Scenario-ne'stale'){$geometryValidationEnvironment.numpy.version}else{$null})}|ConvertTo-Json -Compress
'GEOMETRY_INPUT_ADMISSION=PASS'
''', encoding="utf-8")
                result = subprocess.run(["pwsh", "-NoProfile", "-File", str(fixture), str(REPO),
                                         sys.executable, str(root), str(source_root), scenario], cwd=root,
                                        capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("GEOMETRY_INPUT_ADMISSION=PASS", result.stdout)
                self.assertNotIn("ACTIVE_REPO_FALLBACK", result.stdout + result.stderr)
                self.assertIn("stale_or_missing=" if scenario == "stale" else "RESOLVED_GEOMETRY=PASS",
                              result.stdout + result.stderr)
                facts = json.loads(result.stdout.splitlines()[-2])
                self.assertEqual(facts["copies"], len(code_paths))
                self.assertEqual(facts["downstream"], 0 if scenario == "stale" else 1)
                print("GEOMETRY_ADMISSION_CASE=" + json.dumps(facts, sort_keys=True), flush=True)


    def test_current_compiler_baseline_pair_and_missing_old_bundle(self):
        from common.contracts.compile_execution_plan import compile_execution
        from common.contracts.machine_contracts import sha256
        registry_path = REPO / "config/project_registry.json"
        # Same compiler-boundary plan fixture used by the current common owner;
        # this does not claim the scientific request planner accepts a gas metric.
        owner = PROJECT / "workflows/gas_assisted_transport/run_axisymmetric_gas_flow.ps1"
        for scenario in ("compiled_pair", "missing_baseline", "stale_resolved"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                request_path = root / "request.json"
                request_path.write_text("{}", encoding="utf-8")
                plan = dict(role="solver_neutral_design_plan", request_status="approved",
                            project_id=PROJECT.name, capability_id="axisymmetric_gas_flow_field_generation",
                            mode="axisymmetric_gas_flow_screening", requested_evidence_level="plan",
                            run_id="20260720_130000__analysis__repo__design-request", operating_points=[],
                            objectives=[], design_variables=[], constraints=[], required_outputs=[],
                            provenance=dict(request=dict(path=str(request_path), sha256=sha256(request_path)),
                                            project_registry=dict(sha256=sha256(registry_path))))
                plan_path = root / "plan.json"
                plan_path.write_text(json.dumps(plan), encoding="utf-8")
                compiled = compile_execution(plan_path, registry_path, purpose="field_generation", qualification="none")
                self.assertEqual(compiled["status"], "EXECUTION_READY", compiled.get("blockers"))
                expected = {"geometry_baseline", "resolved_geometry", "gas_flow_science", "comsol_solver_numerics"}
                self.assertEqual({row["name"] for row in compiled["resolved_inputs"]}, expected)
                private = root / "compiled"
                records = []
                for row in compiled["resolved_inputs"]:
                    target = private / row["relative_path"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(row["content"], encoding="utf-8", newline="")
                    records.append({**row, "path": str(target)})
                if scenario == "missing_baseline":
                    records = [row for row in records if row["name"] != "geometry_baseline"]
                if scenario == "stale_resolved":
                    record = next(row for row in records if row["name"] == "resolved_geometry")
                    with Path(record["path"]).open("a", encoding="utf-8") as stream:
                        stream.write(" ")
                bundle = root / "compiled_inputs.json"
                bundle.write_text(json.dumps(dict(role="compiled_execution_inputs", project_id=PROJECT.name,
                                                 root=str(private), files=records)), encoding="utf-8")
                script = root / "compiled_pair.ps1"
                script.write_text(r"""param($Repo,$Python,$Owner,$Root,$Bundle,$Scenario)
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$repoRoot=$Repo;$python=$Python;$projectId='dual_cone_tandem_quadrupole_ion_interface'
$projectRoot=Join-Path $Root 'today';$ResolvedInputsPath=$Bundle;$compiledInputs=$null
$package=@{input_dir=(Join-Path $Root 'inputs')};$frozen=[ordered]@{}
$ast=[Management.Automation.Language.Parser]::ParseFile($Owner,[ref]$null,[ref]$null)
$assignment=$ast.Find({param($n)$n-is[Management.Automation.Language.AssignmentStatementAst]-and$n.Left.Extent.Text-eq'$sourceFiles'},$true)
$selection=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and$n.Clauses[0].Item1.Extent.Text-eq'$ResolvedInputsPath'},$true)
$loop=$ast.Find({param($n)$n-is[Management.Automation.Language.ForEachStatementAst]-and$n.Condition.Extent.Text-eq'$sourceFiles.Keys'},$true)
if($null-eq$assignment-or$null-eq$selection-or$null-eq$loop){throw 'Actual compiled selection boundary missing'}
Invoke-Expression $assignment.Extent.Text
# Poison today's defaults. Only the exact four compiler-captured definitions are usable.
foreach($relative in $sourceFiles.Values){$p=Join-Path $projectRoot $relative;New-Item -ItemType Directory -Force -Path (Split-Path $p)|Out-Null;[IO.File]::WriteAllText($p,'{}')}
$source=[IO.File]::ReadAllText($Owner)
$start=$source.IndexOf('  $geometrySnapshotRoot=Join-Path')
$end=$source.IndexOf('  foreach($key in $schedulerFiles.Keys){',$start)
$admission=$source.Substring($start,$end-$start)
$downstream=0;$caught=$null
try{
 Invoke-Expression $selection.Extent.Text
 Invoke-Expression $loop.Extent.Text
 Invoke-Expression $admission
 $downstream++
}catch{$caught=$_.Exception.Message}
switch($Scenario){
 'missing_baseline' {if($caught-notlike'*geometry_baseline*recompile*'-or$downstream-ne0){throw ('Old bundle silently used today baseline: '+$caught)}}
 'stale_resolved' {if($caught-cne'Frozen dual-cone baseline and resolved geometry differ.'-or$downstream-ne0){throw ('Mismatched pair entered downstream: '+$caught)}}
 default {
  if($caught-or$downstream-ne1){throw ('Real compiler pair rejected: '+$caught)}
  foreach($record in $compiledInputs.files){if([IO.File]::ReadAllText($frozen[$record.name])-cne[IO.File]::ReadAllText((Join-Path $compiledInputs.root $record.relative_path))){throw 'Runner substituted a compiled definition'}}
 }
}
'CURRENT_COMPILED_PAIR=PASS'
""", encoding="utf-8")
                result = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(REPO),
                                         sys.executable, str(owner), str(root), str(bundle), scenario],
                                        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("CURRENT_COMPILED_PAIR=PASS", result.stdout)
