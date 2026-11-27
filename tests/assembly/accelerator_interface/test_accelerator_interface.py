"""Accelerator interface ownership and detached preparation; no vendor solver."""

from msplatform.backends.simion.native_completion import retention_api as _manifest_retention_api
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


from msplatform.execution.manifest_publication import build_run_manifest
from msplatform.execution.retention import file_record
from msplatform.workflows.accelerator_interface.prepare import (
    prepare_interface, verified_preparation_reference,
)

REPO = Path(__file__).resolve().parents[3]
MR = REPO / "src/msplatform/components/multi_reflection_tof"


def reference_fixture(root, *, frame_id="astral.xyz.v2"):
    reference = root / "reference"
    (reference / "simion").mkdir(parents=True)
    config = reference / "run_config.json"
    config.write_text(json.dumps(dict(project=MR.name, inputs={})))
    trajectory = reference / "simion/trajectory_contract.json"
    trajectory.write_text(json.dumps(dict(coordinate_system=dict(frame_id=frame_id),
        accelerator=dict(focus_y_anchor=dict(project_y_mm=-55)))))
    provider = reference / "simion/accelerator_provider_runtime_receipt.json"
    provider.write_text(json.dumps(dict(mrtof_projection=dict(target_axial_energy_per_charge_v=4372))))
    (reference / "run_manifest.json").write_text(json.dumps(dict(project=MR.name, status="success",
        run_config=file_record(config), inputs={}, outputs=[file_record(trajectory), file_record(provider)])))
    return reference





class AcceleratorInterfaceTests(unittest.TestCase):
    def test_preparation_freezes_the_selected_package_not_workspace_sources(self):
        source = (REPO / "src/msplatform/workflows/resources/accelerator_interface.ps1").read_text(encoding="utf-8")
        self.assertIn("$dependencyPath=Join-Path $packageRoot 'workflows/config/runtime_dependencies.json'", source)
        self.assertIn("-RepoRoot $repoRoot -CorePackageRoot $packageRoot -ContractPath $dependencyPath", source)
        self.assertNotIn("-RepoRoot $sourceRoot -ContractPath $dependencyPath", source)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_default_entry_uses_selected_package_and_rejects_missing_or_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "installation/Lib/site-packages/msplatform"
            shutil.copytree(REPO / "src/msplatform", package)
            python_home = root / "python"
            subprocess.run([sys._base_executable, "-m", "venv", "--system-site-packages", str(python_home)],
                           check=True, capture_output=True, text=True, timeout=60, cwd=root)
            python = python_home / "Scripts/python.exe"
            selection = python_home / "Lib/site-packages/selected-msplatform.pth"
            selection.write_text(str(package.parent) + "\n", encoding="utf-8")
            workspace = root / "workspace"
            workspace.mkdir()
            environment = {key: value for key, value in os.environ.items()
                           if key not in {"PYTHONPATH", "SIMULATION_PYTHON_EXE"}}
            command = [shutil.which("pwsh"), "-NoProfile", "-File",
                       str(package / "workflows/resources/accelerator_interface.ps1"), "-PythonExe", str(python)]
            boundary = subprocess.run(command, cwd=workspace, env=environment, capture_output=True,
                                      text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertNotEqual(boundary.returncode, 0)
            self.assertIn("ReferenceMrRunPath is required", boundary.stdout + boundary.stderr)
            self.assertFalse((workspace / "artifacts").exists())

            selection.write_text(str(REPO / "src") + "\n", encoding="utf-8")
            mismatch = subprocess.run(command, cwd=workspace, env=environment, capture_output=True,
                                      text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertNotEqual(mismatch.returncode, 0)
            self.assertIn("package differs from the entry package", mismatch.stdout + mismatch.stderr)

            empty_python_home = root / "empty-python"
            subprocess.run([sys._base_executable, "-m", "venv", str(empty_python_home)],
                           check=True, capture_output=True, text=True, timeout=60, cwd=root)
            missing_command = command.copy()
            missing_command[-1] = str(empty_python_home / "Scripts/python.exe")
            missing = subprocess.run(missing_command, cwd=workspace, env=environment, capture_output=True,
                                     text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("Installed msplatform package is unavailable", missing.stdout + missing.stderr)

    def test_entry_requires_explicit_python(self):
        environment = {key: value for key, value in os.environ.items() if key != "SIMULATION_PYTHON_EXE"}
        result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File",
                                 str(REPO / "src/msplatform/workflows/resources/accelerator_interface.ps1")],
            cwd=REPO, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SIMULATION_PYTHON_EXE is required", result.stdout + result.stderr)




    def test_runner_publishes_consumed_paths_through_public_manifest_writer(self):
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = reference_fixture(root)
            run = root / "20261022_210000__analysis__python__interface-publication"
            (run / "inputs").mkdir(parents=True)
            (run / "results").mkdir()
            receipt = prepare_interface(reference_mr_run=reference, run_directory=run,
                                        provider="orthogonal_accelerator")
            receipt_path = run / "results/accelerator_interface_preparation.json"
            config = run / "run_config.json"
            config.write_text(json.dumps(dict(schema_version=2, run_id=run.name,
                project="instrument_assembly", mode="accelerator_interface_preparation", inputs={},
                artifact_retention=dict(policy_version=1, **{"class": "compact"}, reason=None))))
            # Execute the actual runner's publication projection, without its solver stages.
            command = f"""
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile('{REPO / 'src/msplatform/workflows/resources/accelerator_interface.ps1'}',[ref]$tokens,[ref]$errors)
if($errors.Count){{throw 'Runner parsing failed'}}
$loops=@($ast.FindAll({{param($node) $node -is [System.Management.Automation.Language.ForEachStatementAst] -and $node.Condition.Extent.Text -eq '$receipt.inputs.Keys'}},$true))
if($loops.Count-ne1){{throw 'Expected one consumed-input publication boundary'}}
$receipt=Get-Content -LiteralPath '{receipt_path}' -Raw|ConvertFrom-Json -AsHashtable
$configuration=Get-Content -LiteralPath '{config}' -Raw|ConvertFrom-Json -AsHashtable
. ([scriptblock]::Create($loops[0].Extent.Text))
$configuration|ConvertTo-Json -Depth 50|Set-Content -LiteralPath '{config}' -Encoding utf8
"""
            completed = subprocess.run([pwsh, "-NoProfile", "-Command", command], cwd=REPO,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
            manifest = build_run_manifest(config, "success", output_paths=[receipt_path], retention_api=_manifest_retention_api)
            self.assertEqual(set(manifest["inputs"]), set(receipt["inputs"]))
            (run / "run_manifest.json").write_text(json.dumps(manifest))
            for name, record in receipt["inputs"].items():
                with self.subTest(input=name):
                    self.assertEqual(manifest["inputs"][name]["sha256"], record["sha256"])
                    path = Path(record["path"])
                    self.assertEqual(verified_preparation_reference(run, str(path.relative_to(run))), path)
            request = run / "inputs/accelerator_request.json"
            request.write_text('{"changed":true}')
            with self.assertRaisesRegex(AssertionError, "byte count|SHA-256"):
                verified_preparation_reference(run, "inputs/accelerator_request.json")

    def test_runner_preserves_published_success_when_capacity_handoff_fails(self):
        """Execute the real terminal block/catch and public writer; no vendor calls."""
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        harness = r"""param($Repo,$Python,$Run,$Scenario)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'src/msplatform/execution/resources/run_artifact_support.ps1')
$errors=$null;$tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'src/msplatform/workflows/resources/accelerator_interface.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$owner=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.TryStatementAst]-and$n.CatchClauses.Count-gt0},$false))[0]
$statements=@($owner.Body.Statements)
$start=@(0..($statements.Count-1)|Where-Object{$statements[$_].Extent.Text-eq"`$stage='terminal_publication'"})
if($start.Count-ne1){throw 'terminal publication boundary missing'}
$publish=[scriptblock]::Create(($statements[$start[0]..($statements.Count-1)]|ForEach-Object{$_.Extent.Text})-join"`n")
$handler=[scriptblock]::Create(($owner.CatchClauses[0].Body.Statements.Extent.Text)-join"`n")
$finalizer=[scriptblock]::Create(($owner.Finally.Statements.Extent.Text)-join"`n")
$package=@{run_config=(Join-Path $Run 'run_config.json');summary=(Join-Path $Run 'summary.json');result_dir=(Join-Path $Run 'results');artifact_run_dir=$Run}
$repoRoot=$Repo;$sourceRoot=$Repo;$workspaceRoot=Split-Path -Parent $Run;$python=$Python
$expectedArtifactRoot=[string](Get-Content $package.run_config -Raw|ConvertFrom-Json).capacity_ledger_lifecycle.artifact_root
$artifactRoot=$expectedArtifactRoot
$terminalized=$false;$stage='fixture';$software=@('Python inert boundary');$extraOutputs=@()
$AcceleratorProvider='orthogonal_accelerator';$RunId=Split-Path -Leaf $Run
$receipt=@{status='prepared'}
$capacitySession=@{active=$true};$lease=$null;$paGuards=[Collections.Generic.List[IO.FileStream]]::new()
$log=Join-Path $Run 'logs/prepare.log'
$script:firstRetention=$true;$script:released=$false;$script:finalized=$false
function Apply-RunArtifactRetention {
 param($Python,$RepoRoot,$RunConfig)
 if($Scenario-eq'prepublish'-and$script:firstRetention){$script:firstRetention=$false;throw 'INERT_PREPUBLICATION_FAILURE'}
 $path=Join-Path (Split-Path -Parent $RunConfig) 'retention_actions.json'
 [IO.File]::WriteAllText($path,'{}');return $path
}
function Update-ArtifactWorkflowCapacitySession {
 param($Python,$RepoRoot,$Session,$RemainingCommittedNewBytes)
 return @{session=$Session}
}
function Invoke-RunCapacityLifecycleAdapter {
 param($Python,$RepoRoot,$Action,$ArtifactRoot,$RunConfig)
 if($ArtifactRoot-cne$expectedArtifactRoot){throw 'Actual lifecycle root differs from frozen run'}
 if($Action-eq'assert-retention'){return @{status='retention_valid'}}
 if($Action-ne'finalize-ready'){throw 'unexpected lifecycle action'}
 $script:finalized=$true
 if($Scenario-eq'postpublish'){
  foreach($name in @('summary.json','run_manifest.json')){
   [IO.File]::WriteAllBytes((Join-Path $Run ($name+'.published')),[IO.File]::ReadAllBytes((Join-Path $Run $name)))
  }
  throw 'INERT_CAPACITY_FINALIZATION_FAILURE'
 }
 return @{light_evidence_budget_exceeded=$false}
}
function Exit-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session)$script:released=$true}
$caught=''
$execution=[scriptblock]::Create("try{`n"+$publish.ToString()+"`n}catch{`n"+$handler.ToString()+"`n}finally{`n"+$finalizer.ToString()+"`n}")
try{. $execution}catch{$caught=$_.Exception.Message}
@{caught=$caught;released=$script:released;finalized=$script:finalized;terminalized=$terminalized}|ConvertTo-Json -Compress
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "terminal_boundary.ps1"
            script.write_text(harness, encoding="utf-8", newline="\n")
            for index, scenario in enumerate(("postpublish", "prepublish", "success")):
                with self.subTest(scenario=scenario):
                    run = root / f"20261025_10000{index}__test__python__interface-terminal"
                    for child in ("inputs", "results", "logs"):
                        (run / child).mkdir(parents=True)
                    (run / "logs/prepare.log").write_text("inert preparation completed\n", encoding="utf-8")
                    (run / "summary.json").write_text(json.dumps(dict(status="success", science="preserved")), encoding="utf-8")
                    (run / "run_config.json").write_text(json.dumps(dict(schema_version=1,
                        run_id=run.name, project="instrument_assembly", mode="accelerator_interface_preparation", inputs={},
                        capacity_ledger_lifecycle=dict(enabled=True, artifact_root=str(root / "artifacts")))), encoding="utf-8")
                    result = subprocess.run([pwsh, "-NoProfile", "-File", str(script), str(REPO), sys.executable,
                        str(run), scenario], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    report = json.loads(result.stdout.strip().splitlines()[-1])
                    self.assertTrue(report["released"])
                    self.assertTrue(report["finalized"])
                    expected = "failed" if scenario == "prepublish" else "success"
                    self.assertEqual(json.loads((run / "summary.json").read_text())["status"], expected)
                    self.assertEqual(json.loads((run / "run_manifest.json").read_text())["status"], expected)
                    error = {"postpublish": "INERT_CAPACITY_FINALIZATION_FAILURE", "prepublish": "INERT_PREPUBLICATION_FAILURE", "success": ""}[scenario]
                    self.assertEqual(report["caught"], error)
                    if scenario == "postpublish":
                        self.assertIn("capacity handoff failed", result.stdout)
                        for name in ("summary.json", "run_manifest.json"):
                            self.assertEqual((run / name).read_bytes(), (run / (name + ".published")).read_bytes())

    def test_runner_python_commands_disable_snapshot_bytecode(self):
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        command = r"""param($Source,$Python)
$ErrorActionPreference='Stop'
$errors=$null;$tokens=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($Source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw ($errors|Out-String)}
$commands=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.CommandAst]-and$n.CommandElements[0].Extent.Text-eq'$python'},$true))
if($commands.Count-eq0){throw 'expected Python calls in accelerator interface owner'}
foreach($call in $commands){if($call.CommandElements.Extent.Text-notcontains'-B'){throw 'snapshot call permits bytecode'}}
$python=$Python;$arguments=@('-c','import sys; assert sys.dont_write_bytecode; print("SNAPSHOT_BYTECODE_DISABLED=PASS")')
$preparation=@($commands|Where-Object{$_.Extent.Text.Contains('@arguments')})
if($preparation.Count-ne1){throw 'actual preparation command missing'}
. ([scriptblock]::Create($preparation[0].Extent.Text))
if($LASTEXITCODE-ne0){throw 'actual preparation command did not disable bytecode'}
"""
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "bytecode.ps1"
            script.write_text(command, encoding="utf-8", newline="\n")
            result = subprocess.run([pwsh, "-NoProfile", "-File", str(script),
                str(REPO / "src/msplatform/workflows/resources/accelerator_interface.ps1"), sys.executable],
                cwd=directory, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("SNAPSHOT_BYTECODE_DISABLED=PASS", result.stdout)

    def test_new_preparation_consumes_only_unique_manifest_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "value.json"
            data.write_text("{}")
            manifest = dict(project="instrument_assembly", mode="accelerator_interface_preparation",
                            status="success", inputs={"value": file_record(data)}, outputs=[])
            # A run_config path is deliberately absent: it is not a second record authority.
            self.assertEqual(verified_preparation_reference(root, data.name, manifest=manifest), data)
            for owner, mode in ((MR.name, "accelerator_interface_preparation"),
                                ("instrument_assembly", "prepared_joint")):
                with self.assertRaisesRegex(ValueError, "successful instrument_assembly"):
                    verified_preparation_reference(root, data.name, manifest=dict(manifest, project=owner, mode=mode))
            with self.assertRaisesRegex(ValueError, "exactly one"):
                verified_preparation_reference(root, data.name, manifest=dict(manifest, outputs=[file_record(data)]))
            data.write_text('{"changed":true}')
            with self.assertRaisesRegex(AssertionError, "byte count|SHA-256"):
                verified_preparation_reference(root, data.name, manifest=manifest)

    def test_ip_proposal_preserves_manifest_bound_energy_and_position(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = reference_fixture(root)
            run = root / 'ip-proposal'
            (run / 'inputs').mkdir(parents=True)
            (run / 'results').mkdir()
            receipt = prepare_interface(reference_mr_run=reference, run_directory=run, provider='ion_processor')
            self.assertEqual(receipt['reference_requirements']['axial_energy_per_charge_v'], 4372)
            self.assertEqual(receipt['reference_requirements']['project_y_mm'], -55)
            self.assertEqual(receipt['reference_requirements']['frame_id'], 'astral.xyz.v2')
            self.assertEqual(receipt['next_action'], 'author_original_birth_simulation_recipe')
            self.assertFalse(receipt['solver_executed'])
            self.assertFalse((run / 'results/mrtof_handoff').exists())
            with self.assertRaises(TypeError):
                prepare_interface(reference_mr_run=reference, run_directory=run, provider='ion_processor', source_run=root)

    def test_oa_requirement_preparation_uses_real_mr_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = reference_fixture(root)
            run = root / "prepared"
            (run / "inputs").mkdir(parents=True)
            (run / "results").mkdir()
            receipt = prepare_interface(reference_mr_run=reference, run_directory=run,
                                        provider="orthogonal_accelerator")
            self.assertEqual(receipt["reference_requirements"]["frame_id"], "astral.xyz.v2")
            self.assertEqual(receipt["reference_requirements"]["project_y_mm"], -55)
            self.assertEqual(receipt["reference_requirements"]["axial_energy_per_charge_v"], 4372)
            self.assertEqual(receipt["next_action"], "author_original_birth_simulation_recipe")
            self.assertFalse(list((run / "inputs").glob("*.py")))






    def test_public_prepare_cli_rejects_foreign_destination_before_writing(self):
        from msplatform.workflows.accelerator_interface import prepare as interface
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for module, mode, operation, arguments in (
                (interface, "accelerator_interface_preparation", "prepare_interface",
                 ["--provider", "orthogonal_accelerator", "--reference-mr-run", "missing"]),
            ):
                run = root / mode
                run.mkdir()
                config = run / "run_config.json"
                identity = dict(project="instrument_assembly", mode=mode, run_id=run.name)
                for invalid in (None, dict(identity, project=MR.name), dict(identity, mode="foreign"),
                                dict(identity, run_id="another-run")):
                    with self.subTest(mode=mode, invalid=invalid):
                        if invalid is not None:
                            config.write_text(json.dumps(invalid))
                        before = {item.name: item.read_bytes() for item in run.iterdir()}
                        with patch.object(module, operation) as materialize, patch.object(
                                sys, "argv", ["prepare", *arguments, "--run-directory", str(run)]):
                            with self.assertRaises((ValueError, FileNotFoundError)):
                                module.main()
                            materialize.assert_not_called()
                        self.assertEqual({item.name: item.read_bytes() for item in run.iterdir()}, before)
                config.write_text(json.dumps(identity))
                with patch.object(module, operation) as materialize, patch.object(
                        sys, "argv", ["prepare", *arguments, "--run-directory", str(run)]):
                    module.main()
                    materialize.assert_called_once()

    def test_declared_snapshot_prepares_oa_without_repository(self):
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell 7 is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = reference_fixture(root)
            run = root / "prepared"
            (run / "inputs").mkdir(parents=True)
            (run / "results").mkdir()
            (run / "run_config.json").write_text(json.dumps(dict(project="instrument_assembly",
                mode="accelerator_interface_preparation", run_id=run.name)))
            command = f"""
. '{REPO / 'src/msplatform/execution/resources/dependencies.ps1'}'
$path='{REPO / 'src/msplatform/workflows/config/runtime_dependencies.json'}'
$null=Freeze-ConsumerDependencies -Python '{sys.executable}' -RepoRoot '{REPO}' -ContractPath $path -InputDir '{run / 'inputs'}' -OwnerId instrument_assembly -ConsumerId accelerator_interface
"""
            completed = subprocess.run([pwsh, "-NoProfile", "-Command", command], cwd=REPO,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
            snapshot = run / "inputs/runtime_snapshot"
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(snapshot / "src") + os.pathsep + str(snapshot)
            completed = subprocess.run([sys.executable, "-B", "-s", "-m", "msplatform.workflows.accelerator_interface.prepare",
                "--provider", "orthogonal_accelerator", "--reference-mr-run", str(reference), "--run-directory", str(run)],
                cwd=snapshot, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
            receipt = json.loads((run / "results/accelerator_interface_preparation.json").read_text())
            self.assertEqual(receipt["reference_requirements"]["frame_id"], "astral.xyz.v2")
            self.assertNotIn("joint_code_inventory", receipt["inputs"])
            self.assertFalse(list(snapshot.rglob("__pycache__")))



    def test_interface_capacity_transports_explicit_parent_manifest_authority(self):
        if not shutil.which("pwsh"):
            self.skipTest("PowerShell 7 required")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parents = [root / "other-root" / name for name in ("reference", "ip", "design", "field")]
            for parent in parents:
                parent.mkdir(parents=True)
                (parent / "run_manifest.json").write_text('{"status":"success"}', encoding="utf-8")
            original = {str(parent): (parent / "run_manifest.json").read_bytes() for parent in parents}
            driver = root / "capacity.ps1"
            driver.write_text(r"""param($Repo,$Entry,$Python,$Root)
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'src/msplatform/execution/resources/run_artifact_support.ps1')
$repoRoot=$Repo;$sourceRoot=$Repo;$artifactRoot=Join-Path $Root 'selected';$package=@{artifact_run_dir=(Join-Path $artifactRoot 'assemblies/instrument_assembly/runs/new')};$RunId='new';$python=$Python
$reference,$sourceRun,$designRun,$fieldRun=@('reference','ip','design','field')|ForEach-Object{Join-Path $Root "other-root/$_"}
$pathEnvironment=@{MASS_SPECTROMETRY_ARTIFACT_ROOT=$artifactRoot};$script:admissions=0
function Enter-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$ArtifactRoot,$RunDirectory,$CommittedNewBytes,$ProtectedPaths,$SourceReferences,$Owner)
 if($ProtectedPaths.Count-ne1-or$ProtectedPaths[0]-cne$RunDirectory){throw 'foreign parent entered child protection paths'}
 if($SourceReferences.Count-ne1){throw "source reference count differs: $($SourceReferences.Count)"}
 foreach($ref in $SourceReferences){
  if($ref.manifest_record-isnot[Collections.IDictionary]-or-not$ref.manifest_record.exists-or$ref.protected_paths.Count-ne1){throw 'SOURCE_MANIFEST_MISSING'}
  if($ref.manifest_record.path-cne(Join-Path $ref.protected_paths[0] 'run_manifest.json')){throw 'parent identity differs'}
 }
 $script:admissions++
 $SourceReferences|ConvertTo-Json -Depth 20|Set-Content (Join-Path $Root 'references.json')
}
$ast=[Management.Automation.Language.Parser]::ParseFile($Entry,[ref]$null,[ref]$null)
$body=$ast.Find({param($n)$n-is[Management.Automation.Language.TryStatementAst]-and$n.Body.Extent.Text-match'\$parents='},$true).Body
$selected=@($body.Statements|Where-Object{$_.Extent.Text-match'^\$(parents|sourceRecords|sourceReferences)=|^\$capacitySession=Enter-'})
if($selected.Count-ne4){throw 'actual source admission boundary not found'}
foreach($statement in $selected){Invoke-Expression $statement.Extent.Text}
if($script:admissions-ne1){throw 'actual admission was not reached'}
Remove-Item (Join-Path $reference 'run_manifest.json')
$failed=$false;try {foreach($statement in $selected){Invoke-Expression $statement.Extent.Text}}catch{if($_.Exception.Message-notmatch'SOURCE_MANIFEST_MISSING'){throw};$failed=$true}
if(-not$failed-or$script:admissions-ne1){throw 'missing parent did not reject before admission'}
""", encoding="utf-8")
            result = subprocess.run(["pwsh", "-NoProfile", "-File", str(driver), str(REPO),
                str(REPO / "src/msplatform/workflows/resources/accelerator_interface.ps1"), sys.executable, str(root)],
                cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            references = json.loads((root / "references.json").read_text(encoding="utf-8-sig"))
            references = references if isinstance(references, list) else [references]
            self.assertEqual(len(references), 1)
            self.assertEqual(references[0]['manifest_record']['path'], str(parents[0] / 'run_manifest.json'))
            self.assertEqual(references[0]['protected_paths'], [str(parents[0])])
            self.assertEqual({str(parent): (parent / 'run_manifest.json').read_bytes() for parent in parents[1:]},
                             {str(parent): original[str(parent)] for parent in parents[1:]})
