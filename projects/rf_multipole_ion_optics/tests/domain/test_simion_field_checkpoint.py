"""Original fractional producer checkpoints, using inert software payloads."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.write_run_manifest import build_run_manifest
from projects.rf_multipole_ion_optics.runtime.simion_field_checkpoint import read_checkpoint, write_checkpoint

REPO = Path(__file__).resolve().parents[4]
NATIVE_SUCCESS = {"exit_confirmed": True, "returncode": 0, "process_id": 11, "process_started_at_utc_ticks": 123456}


class FieldCheckpointTests(unittest.TestCase):
    def run_powershell(self, script: str, root: Path) -> None:
        process = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script], cwd=REPO,
            env={**os.environ, "RF_TEST_REPO": str(REPO), "RF_TEST_ROOT": str(root),
                "SIMULATION_PYTHON_EXE": sys.executable}, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_actual_include_identity_preserves_provenance_but_detects_geometry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "root.gem").write_text('; resolved_design_sha256=first\npa_define(5,5,5,planar,xyz, surface=fractional)\ninclude(quad_include.gem)\n')
            (root / "quad_include.gem").write_text('; Generated from first; do not edit.\ne(1){fill{within{box(1,1,1,2,2,2)}}}\n')
            self.run_powershell(r'''
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $env:RF_TEST_REPO 'projects/rf_multipole_ion_optics/runtime/simion_field_checkpoint_support.ps1')
$root=$env:RF_TEST_ROOT;$gem=Join-Path $root 'root.gem';$include=Join-Path $root 'quad_include.gem'
$a=@{GemPath=$gem;SimionExe=$gem;Grid=@(5,5,5);CellMm=@(1,1,1);ResponseIds=@(1);GemIncludePaths=@($include);Gem2PaArguments=@('gem2pa','root.gem');RefineArguments=@('refine','root.pa#')}
$first=New-RfSimionFieldIdentity @a
$a.SimionExe=(Get-Process -Id $PID).Path
$first=New-RfSimionFieldIdentity @a
(Get-Content $gem -Raw).Replace('first','second')|Set-Content $gem -NoNewline
(Get-Content $include -Raw).Replace('first','second')|Set-Content $include -NoNewline
$second=New-RfSimionFieldIdentity @a
if(($first|ConvertTo-Json -Depth 12)-cne($second|ConvertTo-Json -Depth 12)){throw 'provenance changed field'}
(Get-Content $include -Raw).Replace('box(1,1,1,2,2,2)','box(1,1,1,3,2,2)')|Set-Content $include -NoNewline
$third=New-RfSimionFieldIdentity @a
if($third.gem_includes['quad_include.gem']-ceq$first.gem_includes['quad_include.gem']){throw 'include geometry was ignored'}
$a.GemIncludePaths=@();$blocked=$false;try{New-RfSimionFieldIdentity @a|Out-Null}catch{$blocked=$true};if(-not$blocked){throw 'unbound include accepted'}
''', root)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_finite_missing_fly_uses_shared_field_without_refine(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.run_powershell(r'''
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$root=$env:RF_TEST_ROOT;$physicalRunDir=$root;$solverDir=$root;$runConfig=Join-Path $root 'run_config.json'
New-Item -ItemType Directory (Join-Path $root 'inputs')|Out-Null
'{"inputs":{}}'|Set-Content $runConfig
$workflowRequestPath=Join-Path $root 'request.json';$workflowRequest=@{capacity=@{protected_paths=@()}}
$continuationCapacity=@{};$continuationChain=@();$continuationPredecessor='';$NativeFieldRunPath='explicit-producer'
$gem='gem';$simion='exe';$python='python';$codeRoot=$env:RF_TEST_REPO;$repoRoot=$codeRoot
$gridAuditDocument=@{nx=5;ny=5;nz=5};$resolvedCellMmX=1;$resolvedCellMmY=1;$resolvedCellMmZ=1;$paBasisElectrodeIds=@(1)
$flyPhysics=@{gem2pa_args=@('gem2pa');refine_args=@('refine');iob_args=@('build')}
$templateIob=Join-Path $root 'template.iob';$templateCon=Join-Path $root 'template.con'
$RetentionClass='solver_review';$nativeOperations=@();$fieldCheckpointOutputs=@();$continuationAllReuse=$false
$script:reads=0;$script:protects=0
function New-RfSimionFieldIdentity {return @{field='fixture'}}
function Write-RunJson {param($Path,$Value,$Depth,[switch]$Atomic) $Value|ConvertTo-Json -Depth 30|Set-Content $Path}
function Read-RfSimionFieldCheckpoint {$script:reads++;return @{protected_paths=@('original');checkpoint_path='receipt';producer_manifest='producer-manifest';iob_path='original.iob';requires_iob_rebind=$false}}
function Update-ArtifactWorkflowCapacitySession {return @{session=@{}}}
function Protect-RfSimionFieldCheckpoint {$script:protects++;return @{guard='held'}}
function Invoke-SimionStep {throw 'valid field unexpectedly recomputed or rebound'}
function Write-RfSimionFieldCheckpoint {throw 'child overwrote original checkpoint'}
$runner=Join-Path $codeRoot 'projects/rf_multipole_ion_optics/runtime/run_simion_finite_3d_transport.ps1'
$text=Get-Content $runner -Raw
$start=$text.IndexOf('  if(-not$continuationAllReuse){', $text.IndexOf("Set-RfRunPhase 'field_and_layout'"))
$end=$text.IndexOf("  Set-RfRunPhase 'flight_and_case_analysis'",$start)
&([scriptblock]::Create($text.Substring($start,$end-$start)))
if($script:reads-ne1-or$script:protects-ne1){throw 'finite consumer bypassed shared field owner'}
$config=Get-Content $runConfig -Raw|ConvertFrom-Json
if($config.inputs.simion_field_producer_manifest-cne'producer-manifest'){throw 'field producer reference omitted'}
''', Path(temporary))

    def test_normal_wrapper_routes_field_only_option_without_changing_comsol_default(self):
        folder = REPO / "projects/rf_multipole_ion_optics"
        wrapper = (folder / "workflows/no_collision_transport/run_simion.ps1").read_text(encoding="utf-8-sig")
        launcher = (folder / "runtime/project_transport_launcher_support.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("NativeFieldRunPath = $NativeFieldRunPath", wrapper)
        self.assertIn("[string]$RetentionClass = 'solver_review'", wrapper)
        self.assertIn("$arguments.Remove('RetentionClass')", wrapper)
        self.assertIn("[string]$RetentionClass = 'compact'", launcher)
        comsol, simion = launcher.split("if ($Solver -eq 'comsol') {", 1)[1].split("    } else {", 1)
        self.assertNotIn("NativeFieldRunPath", comsol)
        self.assertIn("$arguments.NativeFieldRunPath = $NativeFieldRunPath", simion)
        self.assertIn("$RetentionClass = [string]$profile.retention_class", launcher)

    def test_finite_inspects_permanent_layout_with_actual_case_before_ready_receipt(self):
        project = REPO / "projects/rf_multipole_ion_optics"
        finite = (project / "runtime/run_simion_finite_3d_transport.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("$iobBuildArguments[4]=$flightIobPath", finite)
        layout = finite[finite.index("  $iobBuildArguments=@($flyPhysics.iob_args)"):]
        self.assertLess(layout.index("New-RfSimionLayoutSeedCompanion"), layout.index("Invoke-SimionStep 'build_runtime_iob'"))
        self.assertLess(layout.index("Invoke-SimionStep 'build_runtime_iob'"), layout.index("Remove-RfSimionLayoutSeedCompanion"))
        self.assertIn("-BuildObservation $buildFact.observation", layout)
        inspect = finite[finite.index("    if($script:layoutInspectionRequired){"):]
        self.assertIn("local config=dofile([[$($batchRuns[0].lua_config)]])", inspect)
        self.assertIn("RFQUAD_SIMION_REFERENCE_IOB=$flightIobPath", inspect)
        self.assertIn("MULTIPOLE_SIMION_RF_DRIVE_KERNEL_LUA=$rfDriveKernelLua", inspect)
        self.assertLess(inspect.index("Invoke-SimionStep 'inspect_runtime_iob'"), inspect.index("Write-RfSimionFieldCheckpoint"))
        lua = (project / "simion/workbench/inspect_builtin_quad_reference.lua").read_text()
        self.assertIn("if cell_x ~= nil or cell_y ~= nil or cell_z ~= nil then", lua)
        self.assertIn("type(cell_x) == 'number' and type(cell_y) == 'number' and type(cell_z) == 'number'", lua)
        self.assertIn("cell_y, cell_z = cell_x, cell_x", lua)
        for axis, cell in (("dx", "cell_x"), ("dy", "cell_y"), ("dz", "cell_z")):
            self.assertIn(f"math.abs(pa.{axis}_mm - {cell}) < 1e-12", lua)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_actual_producer_write_accepts_collector_list_and_completes_same_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run, _, _ = self.fixture(root)
            self.run_powershell(r'''
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $env:RF_TEST_REPO 'projects/rf_multipole_ion_optics/runtime/simion_field_checkpoint_support.ps1')
$run=Join-Path $env:RF_TEST_ROOT '20261030_000000__sim__simion__field-producer'
$native=[Collections.Generic.List[object]]::new()
$native.Add(@{operation_id='refine';observation=@{exit_confirmed=$true;returncode=0;process_id=11;process_started_at_utc_ticks=123456}})
$args=@{RunDirectory=$run;IdentityPath=(Join-Path $run 'inputs/simion_field_identity.json');IobPath=(Join-Path $run 'simion/quad_monolithic.iob');NativeOperations=$native;Python=$env:SIMULATION_PYTHON_EXE;RepoRoot=$env:RF_TEST_REPO}
$first=Write-RfSimionFieldCheckpoint @args
if((Get-Content $first.checkpoint_path -Raw|ConvertFrom-Json).iob_path){throw 'layout falsely ready'}
$native.Add(@{operation_id='build_runtime_iob';observation=@{exit_confirmed=$true;returncode=0;process_id=12;process_started_at_utc_ticks=123457}})
$native.Add(@{operation_id='inspect_runtime_iob';observation=@{exit_confirmed=$true;returncode=0;process_id=13;process_started_at_utc_ticks=123458}})
$second=Write-RfSimionFieldCheckpoint @args
if($first.checkpoint_path-cne$second.checkpoint_path){throw 'second checkpoint created'}
if(-not(Get-Content $second.checkpoint_path -Raw|ConvertFrom-Json).iob_path){throw 'completed layout omitted'}
foreach($path in $second.output_paths|Where-Object{$_-ne$second.checkpoint_path}){if(-not(Get-Item $path).IsReadOnly){throw 'producer did not seal member'}}
''', root)
            self.assertEqual(json.loads((run / "results/simion_field_checkpoint.json").read_text())["status"], "prepared")

    def fixture(self, root: Path, *, layout: bool = True) -> tuple[Path, Path, Path]:
        run = root / "20261030_000000__sim__simion__field-producer"
        for folder in ("inputs", "results", "simion"):
            (run / folder).mkdir(parents=True)
        identity = run / "inputs/simion_field_identity.json"
        identity.write_text(json.dumps({"schema_version": 1, "role": "multipole_simion_field_identity",
            "gem_sha256": "A"*64, "gem_includes": {}, "grid": [5, 5, 5], "cell_mm": [1., 1., 1.], "surface": "fractional",
            "response_ids": [1, 2], "simion_executable_sha256": "B"*64,
            "gem2pa_arguments": ["gem2pa", "quad_monolithic.gem", "quad_monolithic.pa#"],
            "refine_arguments": ["refine", "quad_monolithic.pa#"]}), encoding="utf-8")
        config = {"schema_version": 2, "run_id": run.name, "project": "rf_multipole_ion_optics",
            "mode": "resolved_design_transport", "inputs": {"simion_field_identity": str(identity)},
            "formal_gate_passed": False,
            "artifact_retention": {"policy_version": 1, "class": "solver_review", "reason": "inert checkpoint fixture"}}
        (run / "run_config.json").write_text(json.dumps(config), encoding="utf-8")
        (run / "run_manifest.json").write_text(json.dumps(build_run_manifest(run / "run_config.json", "checkpoint")), encoding="utf-8")
        for suffix in ("pa#", "pa0", "pa1", "pa2", "pa-surf", *( ("iob", "lua", "fly2", "con") if layout else () )):
            (run / "simion" / ("quad_monolithic." + suffix)).write_bytes(("inert " + suffix).encode())
        return run, identity, run / "simion/quad_monolithic.iob"

    def publish(self, run: Path, result: dict) -> None:
        for path in map(Path, result["output_paths"]):
            if path.suffix != ".json":
                path.chmod(path.stat().st_mode & ~stat.S_IWRITE)
        (run / "run_manifest.json").write_text(json.dumps(build_run_manifest(run / "run_config.json", "failed",
            output_paths=list(map(Path, result["output_paths"])))), encoding="utf-8")

    def test_original_fractional_family_is_metadata_bound_without_pa_reads(self):
        with tempfile.TemporaryDirectory() as temporary:
            run, identity, iob = self.fixture(Path(temporary))
            result = write_checkpoint(run, identity, iob, [
                {"operation_id": name, "observation": dict(NATIVE_SUCCESS)}
                for name in ("refine", "build_runtime_iob", "inspect_runtime_iob")])
            self.publish(run, result)
            from common.contracts import write_run_manifest as writer
            original = writer.file_record
            def no_pa(path, *args, **kwargs):
                if ".pa" in Path(path).name:
                    raise AssertionError("protected field was reread by metadata projection")
                return original(path, *args, **kwargs)
            with patch("common.contracts.verify_run_manifest.file_record", side_effect=no_pa):
                plan = read_checkpoint(run, identity, iob.with_suffix(".lua"))
            self.assertFalse(plan["requires_iob_rebind"])
            self.assertEqual(plan["controller_path"], str(iob.with_suffix(".pa0")))
            self.assertTrue(any(r["path"].endswith(".pa-surf") for r in plan["payload_records"]))
            changed_program = Path(temporary) / "new_program.lua"
            changed_program.write_text("new program", encoding="utf-8")
            self.assertTrue(read_checkpoint(run, identity, changed_program)["requires_iob_rebind"])

    def test_completed_refine_survives_missing_layout_and_field_mismatch_rejects(self):
        with tempfile.TemporaryDirectory() as temporary:
            run, identity, iob = self.fixture(Path(temporary), layout=False)
            result = write_checkpoint(run, identity, iob, [{"operation_id": "refine", "observation": dict(NATIVE_SUCCESS)}])
            self.publish(run, result)
            plan = read_checkpoint(run, identity, Path(temporary) / "unused.lua")
            self.assertTrue(plan["requires_iob_rebind"])
            self.assertIsNone(plan["iob_path"])
            altered = Path(temporary) / "other_identity.json"
            value = json.loads(identity.read_text()); value["cell_mm"][0] = .5
            altered.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "identity differs"):
                read_checkpoint(run, altered, Path(temporary) / "unused.lua")

    def test_uninspected_legacy_iob_requires_rebind_without_discarding_field(self):
        with tempfile.TemporaryDirectory() as temporary:
            run, identity, iob = self.fixture(Path(temporary))
            facts = [{"operation_id": name, "observation": dict(NATIVE_SUCCESS)}
                for name in ("refine", "build_runtime_iob", "inspect_runtime_iob")]
            result = write_checkpoint(run, identity, iob, facts)
            receipt = Path(result["checkpoint_path"])
            legacy = json.loads(receipt.read_text())
            legacy["native_operations"] = facts[:2]
            receipt.write_text(json.dumps(legacy))
            self.publish(run, result)
            plan = read_checkpoint(run, identity, iob.with_suffix(".lua"))
            self.assertTrue(plan["requires_iob_rebind"])
            self.assertEqual(plan["controller_path"], str(iob.with_suffix(".pa0")))

    def test_field_only_child_keeps_original_producer_reference_for_next_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            producer, identity, iob = self.fixture(root, layout=False)
            result = write_checkpoint(producer, identity, iob, [{"operation_id": "refine", "observation": dict(NATIVE_SUCCESS)}])
            self.publish(producer, result)
            child = root / "20261030_000001__sim__simion__field-child"
            child.mkdir()
            config = json.loads((producer / "run_config.json").read_text())
            config["run_id"] = child.name
            config["inputs"].update(simion_field_checkpoint=result["checkpoint_path"],
                simion_field_producer_manifest=str(producer / "run_manifest.json"))
            (child / "run_config.json").write_text(json.dumps(config))
            (child / "run_manifest.json").write_text(json.dumps(build_run_manifest(child / "run_config.json", "success")))
            plan = read_checkpoint(child, identity, root / "unused.lua")
            self.assertEqual(plan["producer_manifest"], str(producer / "run_manifest.json"))
            self.assertIn(str(producer), plan["protected_paths"])
            del config["inputs"]["simion_field_producer_manifest"]
            (child / "run_config.json").write_text(json.dumps(config))
            (child / "run_manifest.json").write_text(json.dumps(build_run_manifest(child / "run_config.json", "success")))
            with self.assertRaisesRegex(ValueError, "manifest bound"):
                read_checkpoint(child, identity, root / "unused.lua")

    def test_unknown_native_completion_and_compact_retention_are_not_field_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            run, identity, iob = self.fixture(Path(temporary))
            with self.assertRaisesRegex(ValueError, "confirmed successful"):
                write_checkpoint(run, identity, iob, [{"operation_id": "refine", "observation": {"exit_confirmed": False, "returncode": 0}}])
            for key in ("process_id", "process_started_at_utc_ticks"):
                for value in (None, True, 0):
                    facts = {**NATIVE_SUCCESS, key: value}
                    with self.assertRaisesRegex(ValueError, key):
                        write_checkpoint(run, identity, iob, [{"operation_id": "refine", "observation": facts}])
            config = json.loads((run / "run_config.json").read_text()); config["artifact_retention"]["class"] = "compact"
            (run / "run_config.json").write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "retention"):
                write_checkpoint(run, identity, iob, [])

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PA guards required")
    def test_public_pa_guard_reads_once_and_holds_original_members_until_close(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); run, identity, iob = self.fixture(root)
            result = write_checkpoint(run, identity, iob, [
                {"operation_id": name, "observation": dict(NATIVE_SUCCESS)}
                for name in ("refine", "build_runtime_iob", "inspect_runtime_iob")])
            self.publish(run, result)
            plan = read_checkpoint(run, identity, iob.with_suffix(".lua"))
            plan_path = root / "plan.json"; plan_path.write_text(json.dumps(plan), encoding="utf-8")
            script = r'''
$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
. (Join-Path $env:RF_TEST_REPO 'projects/rf_multipole_ion_optics/runtime/simion_field_checkpoint_support.ps1')
$plan=Get-Content $env:RF_TEST_PLAN -Raw|ConvertFrom-Json
$original=(Get-Command Get-ImmutablePaSourceVerificationSha256).ScriptBlock;$script:reads=0
function Get-ImmutablePaSourceVerificationSha256 {param($Stream,$Length) $script:reads++;&$original -Stream $Stream -Length $Length}
$context=Protect-RfSimionFieldCheckpoint -Checkpoint $plan
try{
 if($script:reads-ne5){throw 'field payload was not verified exactly once'}
 foreach($record in $context.pa_records){
  $blocked=$false;try{$writer=[IO.File]::Open($record.path,'Open','Write','ReadWrite');$writer.Dispose()}catch{$blocked=$true}
  if(-not$blocked){throw 'original field remained writable'}
 }
}finally{Close-RfSimionFieldCheckpointGuard -Context $context}
if($global:MassSpectrometryImmutablePaSourceGuards.Count){throw 'field guard leaked'}
'''
            process = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-Command", script], cwd=REPO,
                env={**os.environ, "RF_TEST_REPO": str(REPO), "RF_TEST_PLAN": str(plan_path),
                    "SIMULATION_PYTHON_EXE": sys.executable}, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
