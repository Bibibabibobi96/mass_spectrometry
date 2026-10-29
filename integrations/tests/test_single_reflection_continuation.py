"""Continuation uses published single-reflection workbenches, not a toy context."""
from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

from common.contracts.write_run_manifest import file_record
from common.simion.particle_batching import plan_single_wave_batches
from integrations.tests import test_single_reflection_runtime as runtime_tests
from integrations.workflows.single_reflection_flight import runtime
from integrations.workflows.single_reflection_flight.continuation import prepare_phase_continuation
from integrations.workflows.single_reflection_flight.collect import collect_log


_PUBLIC_FLY = r'''param($Repo,$Python,$OutputDirectory,$frozenExecutionRoot,$FieldReceipt,$workbenchPhase='full_instrument')
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $Repo 'integrations/runtime/frontend_flight_support.ps1')
function Write-RunJson {param($Path,$Value,$Depth=100) ConvertTo-Json -InputObject $Value -Depth $Depth|Set-Content -LiteralPath $Path -Encoding utf8}
function Invoke-RunToolRootContext {param($RepoRoot,$Operation) & $Operation}
function Get-HostResourceBudget {param($Role,$Stage) return @{}}
function Update-HostResourceStage {param($Lease,$Stage,$Budget,$RetainedMemoryBytes) if($Stage-eq'flight'){$script:heavy++};return @{}}
function Update-ArtifactWorkflowCapacitySession {param($Python,$RepoRoot,$Session,$ProtectedPaths,$RemainingCommittedNewBytes) if($ProtectedPaths){$script:protected+=@($ProtectedPaths)};if($PSBoundParameters.ContainsKey('RemainingCommittedNewBytes')){$Session.committed_new_bytes=$RemainingCommittedNewBytes};return @{session=$Session}}
function New-ShortPaCopy {param($Source,$Destination,$ExpectedBytes,$ExpectedSha256,[switch]$GuardDestinationReadOnly)
 New-Item -ItemType Directory -Path (Split-Path -Parent $Destination) -Force|Out-Null
 Copy-Item -LiteralPath $Source -Destination $Destination
 $script:copies++
}
function Publish-ShortPaCopyDestination {param($Path,[switch]$KeepDestinationGuard)}
function Protect-ImmutablePaSource {param($Source,$ExpectedBytes,$ExpectedSha256) $script:guardPaths+=@($Source)}
function Complete-ResourceUsage {param($RunDir,$UsagePath)}
function Write-InstrumentWallClockWarning {param($Limits,$Elapsed,$Stage)}
function Confirm-InstrumentFrontendIobRetention {
 # Explicit inert durable-retention boundary: no production ledger in this fixture.
 $script:pinChecks++
}
function Write-NativeExecutionEvidence {param($Records,$Path) Write-RunJson -Path $Path -Value @($Records)}
$script:builds=0;$script:flights=0;$script:heavy=0;$script:copies=0;$script:pinChecks=0;$script:protected=@();$script:guardPaths=@()
function Invoke-FrontendIobBuild {
 param($Case,$Phase,$RunDirectory,$SimionExe,$Limits,$Python,$RepoRoot)
 $script:builds++
 [IO.File]::WriteAllText([string]$Case.iob_path,'INERT_NOT_NATIVE_IOB')
 $value=& $Python -B -m integrations.workflows.single_reflection_flight.runtime --run $RunDirectory --verify-controls ([string]$Case.receipt_path)
 if($LASTEXITCODE-ne0){throw 'inert build binding failed'}
 $bound=$value|ConvertFrom-Json -Depth 100
 $Case.outputs|Add-Member -NotePropertyName iob -NotePropertyValue $bound.iob_record -Force
 $Case|Add-Member -NotePropertyName native_workbench_execution -NotePropertyValue @(@{exit_code=0}) -Force
 Write-RunJson -Path $Case.receipt_path -Value $Case
}
function Invoke-ResourceBudgetedProcesses {
 param($DispatchPlanPath,$RunDir,$UsagePath,$ProcessSpecifications,$ExistingProcessRecords=@())
 $records=@($ExistingProcessRecords)
 foreach($spec in $ProcessSpecifications){
  $script:flights++
  Copy-Item -LiteralPath (Join-Path $RunDir ('inputs/'+$spec.name+'.native.log')) -Destination $spec.stdout
  [IO.File]::WriteAllText([string]$spec.stderr,'')
  $records+=@{name=$spec.name;exit_code=0}
 }
 return @{resource_budget_exceeded=$false;processes=$records}
}
$frozen=@{execution_root=$Repo};$resultDirectory=Join-Path $OutputDirectory 'results/single_reflection'
$RepoRoot=$Repo;$configPath=Join-Path $OutputDirectory 'run_config.json';$capacity=@{committed_new_bytes=0}
$field=@{cache_receipt=$FieldReceipt};$decisionRecord=$null;$Fly=$true;$batchContinuation=$true
$phaseArguments=@('--phase',$workbenchPhase)
$runtimeArguments=@('-B','-m','integrations.workflows.single_reflection_flight.runtime','--preparation',
 (Join-Path $resultDirectory 'preparation_receipt.json'),'--run',$OutputDirectory,'--snapshot-root',$frozenExecutionRoot)
$flightLimits=@{instrument_flight=@{};instrument_default_replay=@{};instrument_pulse_discovery=@{}};$lease=@{};$simion='INERT_NOT_EXECUTABLE'
$paGuards=[Collections.Generic.List[string]]::new()
$allWorkbenchExecution=@();$flightExecution=@();$flightCollection=@();$phaseCollection=@();$baselineRecord=$null
$prefix=if($workbenchPhase-eq'discovery'){'discovery_'}else{''}
$workbenchReceiptPath=Join-Path $resultDirectory ($prefix+'workbench_preparation.json')
$workbenchEvidencePath=Join-Path $resultDirectory 'workbench_execution_records.json'
$nativePhases=if($workbenchPhase-eq'discovery'){@('discovery')}else{@('baseline','default_replay')}
function Copy-VerifiedRunInput {param($Source,$Destination) Copy-Item -LiteralPath $Source -Destination $Destination}
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $Repo 'integrations/workflows/single_reflection_flight/execute.ps1'),[ref]$null,[ref]$null)
$register=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Register-InstrumentContinuationInputs'},$true)
. ([scriptblock]::Create($register.Extent.Text))
$copyFunction=$ast.Find({param($n)$n-is[Management.Automation.Language.FunctionDefinitionAst]-and$n.Name-eq'Initialize-InstrumentIobPaCopies'},$true)
. ([scriptblock]::Create($copyFunction.Extent.Text))
$block=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and$n.Clauses[0].Item1.Extent.Text-eq'$Fly'-and$n.Extent.Text.Contains('$fullRuntimeInputs=')},$true)
if(-not$block){throw 'public Fly block missing'}
. ([scriptblock]::Create($block.Extent.Text))
Write-RunJson -Path (Join-Path $resultDirectory 'inert_counts.json') -Value @{builds=$script:builds;flights=$script:flights;heavy=$script:heavy;pin_checks=$script:pinChecks}
Write-RunJson -Path (Join-Path $resultDirectory 'inert_protected.json') -Value @($script:protected)
Write-RunJson -Path (Join-Path $resultDirectory 'inert_guard_paths.json') -Value @($script:guardPaths)
Write-RunJson -Path (Join-Path $resultDirectory 'inert_copy_count.json') -Value $script:copies
'''


class SingleReflectionContinuationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workbench_fixture = runtime_tests.WorkbenchMaterializationTests("run")
        self.workbench_fixture.setUp()
        self.addCleanup(self.workbench_fixture.doCleanups)
        self.run = self.workbench_fixture.run
        self.preparation = self.workbench_fixture.preparation
        self.flight = self.workbench_fixture.flight
        self.snapshot = self.workbench_fixture.snapshot
        self.field_receipt = self.workbench_fixture.field_receipt
        self.downstream_path = self.workbench_fixture.downstream_path
        request = Path(self.preparation["input_records"]["request"]["path"])
        author = json.loads(request.read_text(encoding="utf-8-sig"))
        runtime_tests.write_json(request, {**author, "flight": self.flight})
        self.preparation["input_records"]["request"] = file_record(request)

    def _current_workbench(self, phase: str = "full_instrument") -> dict:
        context = runtime._prepare_context(
            self.preparation, self.field_receipt, file_record(self.downstream_path), self.run,
            snapshot_root=self.snapshot, flight=self.flight, phase=phase,
        )
        workbench = runtime.materialize_batches(
            self.run, phase, plan_single_wave_batches(100, 2), context=context,
        )
        for case in workbench["batches"]:
            iob = Path(case["working_directory"]) / "instrument.iob"
            iob.write_bytes(b"INERT_SAVED_IOB_FOR_CONTINUATION_TEST")
            case["outputs"]["iob"] = file_record(iob)
        return workbench

    @staticmethod
    def _native_log(rows: list[dict[str, str]]) -> str:
        lines: list[str] = []
        for native_ion, row in enumerate(rows, 1):
            pid, time = int(row["particle_id"]), float(row["instrument_time_us"])
            state = " ".join(f"{axis}_mm={float(row[f'position_{axis}_mm']):.17g}" for axis in "xyz")
            state += " " + " ".join(f"v{axis}_mm_per_us={float(row[f'velocity_{axis}_m_s']) / 1000:.17g}" for axis in "xyz")
            lines.extend((
                f"TRACE: source_release ion={native_ion} particle_id={pid} instrument_time_us={time:.17g} {state}",
                f"TRACE: handoff_terminal_raw ion={native_ion} instance=3 instrument_time_us={time + 1:.17g} {state}",
                f"TRACE: non_detector_splat ion={native_ion} instance=3 t={time + 1:.17g} "
                + " ".join(f"{axis}={float(row[f'position_{axis}_mm']):.17g}" for axis in "xyz") + " zmax=0",
            ))
        return "\n".join([*lines, f"status,Fly completed. {len(rows)} splats", ""])

    def _parent(self, current: dict, *, missing_iob: bool = False) -> Path:
        parent = self.run.parent / "parent"
        if parent.exists():
            shutil.rmtree(parent)
        parent.mkdir()
        with Path(self.preparation["outputs"]["projected_source"]["path"]).open(encoding="utf-8-sig", newline="") as stream:
            source = list(csv.DictReader(stream))
        parent_cases = copy.deepcopy(current["batches"])
        phase = current["phase"]
        artifacts: list[Path] = []
        for case in parent_cases:
            current_directory = Path(case["working_directory"])
            copy_changes = []
            for transport in case.get("iob_pa_copies", []):
                old = Path(transport["destination"])
                target = parent / "simion/iob_fields" / old.name
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copyfile(transport["source_record"]["path"], target)
                copy_changes.append((old.as_posix(), target.as_posix()))
                transport["destination"] = str(target)
            for guard in case.get("iob_pa_guard_records", []):
                for old, new in copy_changes:
                    if Path(guard["path"]).as_posix() == old:
                        guard["path"] = str(Path(new))
            parent_directory = parent / "simion" / phase / case["case_id"]
            shutil.copytree(current_directory, parent_directory)
            for name, record in list(case["outputs"].items()):
                destination = parent_directory / Path(record["path"]).name
                if name == "build_spec":
                    destination.write_text(
                        destination.read_text(encoding="utf-8-sig").replace(
                            current_directory.resolve().as_posix(), parent_directory.resolve().as_posix()
                        ).replace(str(current_directory.resolve()), str(parent_directory.resolve())),
                        encoding="utf-8", newline="\n",
                    )
                case["outputs"][name] = file_record(destination)
                if name == "build_spec":
                    text = destination.read_text()
                    for old, new in copy_changes:
                        text = text.replace(old, new)
                    destination.write_text(text, encoding="utf-8", newline="\n")
                    case["outputs"][name] = file_record(destination)
                artifacts.append(destination)
            case["working_directory"] = str(parent_directory)
            low, high = case["source_row_range"]
            baseline = parent / "results" / ("discovery" if phase == "discovery" else "baseline") / f"{case['case_id']}.stdout.log"
            replay = parent / "results" / "default_replay" / f"{case['case_id']}.stdout.log"
            baseline.parent.mkdir(parents=True, exist_ok=True)
            replay.parent.mkdir(parents=True, exist_ok=True)
            log = self._native_log(source[low - 1:high])
            baseline.write_text(log, encoding="utf-8", newline="\n")
            replay.write_text(log, encoding="utf-8", newline="\n")
            case["stdout"], case["replay_stdout"] = str(baseline), str(replay)
            artifacts.extend((baseline, replay))
        parent_cases.reverse()  # Publication order is not an execution dependency.
        if missing_iob:
            next(case for case in parent_cases if case["source_row_range"] == [51, 100])["outputs"].pop("iob")
        parent_workbench = {**copy.deepcopy(current), "batches": parent_cases}
        parent_workbench["iob_pa_copies"] = parent_cases[0].get("iob_pa_copies", [])
        receipt = parent / "results" / "single_reflection" / ("discovery_workbench_preparation.json" if phase == "discovery" else "workbench_preparation.json")
        receipt.parent.mkdir(parents=True, exist_ok=True)
        runtime_tests.write_json(receipt, parent_workbench)
        dispatch = plan_single_wave_batches(100, 2)
        dispatch["coverage"] = "complete_population"
        dispatch_path = parent / "results" / f"{phase}.dispatch_plan.json"
        runtime_tests.write_json(dispatch_path, dispatch)
        config = parent / "run_config.json"
        runtime_tests.write_json(config, {"run_id": "parent", "mode": "analysis"})
        outputs = [file_record(path) for path in [receipt, dispatch_path, *artifacts] if path.is_file()]
        manifest = {
            "role": "simulation_run_manifest", "run_id": "parent", "status": "interrupted",
            "run_config": file_record(config),
            "inputs": {"projected_source": self.preparation["outputs"]["projected_source"]},
            "outputs": outputs,
        }
        manifest_path = parent / "run_manifest.json"
        runtime_tests.write_json(manifest_path, manifest)
        frozen = self.run / "inputs" / "continuation_parent_manifest.json"
        shutil.copyfile(manifest_path, frozen)
        self.preparation["input_records"]["continuation_parent_manifest"] = {
            **file_record(frozen), "source_path": str(manifest_path),
        }
        return parent

    def _materialize_cli(self, phase: str) -> dict:
        runtime_tests.write_json(self.workbench_fixture.root / "preparation.json", self.preparation)
        publication = self.workbench_fixture.root / "publication.json"
        runtime_tests.write_json(publication, dict(receipt_record=file_record(self.downstream_path)))
        return self.workbench_fixture.invoke_runtime("materialize-continuation", "--continuation-phase", phase,
            "--field-receipt", self.field_receipt, "--downstream-publication", publication)

    def test_cli_mixed_and_zero_missing_materialize_only_replayed_batches_and_collect(self) -> None:
        for missing in (False, True):
            with self.subTest(missing=missing):
                current = self._current_workbench()
                parent = self._parent(current, missing_iob=missing)
                shutil.rmtree(self.run / "simion/full_instrument")
                result = self._materialize_cli("baseline")
                self.assertEqual(len(result["reused_batches"]), 1 if missing else 2)
                self.assertEqual(result["instance_roles"], current["instance_roles"])
                with Path(self.preparation["outputs"]["projected_source"]["path"]).open(newline="") as stream:
                    rows = list(csv.DictReader(stream))
                for case in result["batches"]:
                    destination = self.run / "simion/full_instrument" / case["case_id"]
                    if "continuation_source" in case:
                        self.assertFalse(destination.exists())
                        self.assertTrue(Path(case["working_directory"]).is_relative_to(parent))
                    else:
                        self.assertTrue(destination.is_dir())
                        iob = Path(case["iob_path"])
                        iob.write_bytes(b"INERT_REPLAY_IOB")
                        case["outputs"]["iob"] = file_record(iob)
                        low, high = case["source_row_range"]
                        Path(case["stdout"]).parent.mkdir(parents=True, exist_ok=True)
                        Path(case["stdout"]).write_text(self._native_log(rows[low-1:high]), encoding="utf-8")
                collection = collect_log(self.preparation, result, self.run)
                self.assertEqual(len(collection["native_terminals"]), 100)
                bad = copy.deepcopy(result)
                bad["batches"][0].pop("continuation_source")
                with self.assertRaisesRegex(ValueError, "escapes"):
                    collect_log(self.preparation, bad, self.run)
                forged = copy.deepcopy(result)
                forged["batches"][0]["stdout"] = str(parent / "results/baseline" / (result["batches"][1]["case_id"] + ".stdout.log"))
                with self.assertRaisesRegex(ValueError, "native log must belong"):
                    collect_log(self.preparation, forged, self.run)
                shutil.rmtree(self.run / "inputs/continuation")
                shutil.rmtree(self.run / "simion/full_instrument", ignore_errors=True)

    def test_default_replay_cli_never_stages_batches_and_reuses_published_logs(self) -> None:
        current = self._current_workbench()
        self._parent(current)
        result = self._materialize_cli("baseline")
        receipt = self.run / "results/single_reflection/workbench_preparation.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        runtime_tests.write_json(receipt, result)
        shutil.rmtree(self.run / "simion/full_instrument")
        replay = self._materialize_cli("default_replay")
        self.assertFalse((self.run / "simion/full_instrument").exists())
        self.assertEqual(sum("replay_continuation_source" in case for case in replay["batches"]), 2)
        collection = collect_log(self.preparation, replay, self.run, replay=True)
        self.assertEqual(len(collection["native_terminals"]), 100)

    def test_retired_execution_alias_resolves_only_published_parent_controls(self) -> None:
        current = self._current_workbench()
        parent = self._parent(current)
        path = parent / "results/single_reflection/workbench_preparation.json"
        workbench = json.loads(path.read_text())
        alias = self.run.parent / "retired_execution_alias"
        for case in workbench["batches"]:
            iob = Path(case["outputs"]["iob"]["path"])
            case["iob_path"] = str(alias / iob.relative_to(parent))
            case["working_directory"] = str(Path(case["iob_path"]).parent)
            original_builder = Path(case["iob_builder_arguments"][3])
            builder = parent / "inputs/runtime_snapshot/integrations/workflows/single_reflection_flight/build_iob.lua"
            builder.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original_builder, builder)
            case["iob_builder_arguments"][3] = str(alias / builder.relative_to(parent))
            for key in ("stdout", "replay_stdout"):
                case[key] = str(alias / Path(case[key]).relative_to(parent))
        runtime_tests.write_json(path, workbench)
        manifest_path = parent / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["outputs"] = [record for record in manifest["outputs"] if Path(record["path"]) != path]
        manifest["outputs"].append(file_record(path))
        runtime_tests.write_json(manifest_path, manifest)
        frozen = self.run / "inputs/continuation_parent_manifest.json"
        shutil.copyfile(manifest_path, frozen)
        self.preparation["input_records"]["continuation_parent_manifest"] = {**file_record(frozen), "source_path": str(manifest_path)}
        result = self._materialize_cli("baseline")
        self.assertEqual(len(result["reused_batches"]), 2)
        self.assertTrue(all(Path(case["iob_path"]).is_file() for case in result["batches"]))
        self.assertFalse(alias.exists())

    def test_second_recovery_reuses_ancestor_and_direct_parent_only_when_rebound(self) -> None:
        current = self._current_workbench()
        original_parent = self._parent(current, missing_iob=True)
        shutil.rmtree(self.run / "simion/full_instrument")
        first = self._materialize_cli("baseline")
        result_dir = self.run / "results/single_reflection"
        result_dir.mkdir(parents=True)
        with Path(self.preparation["outputs"]["projected_source"]["path"]).open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        outputs = []
        for case in first["batches"]:
            if "continuation_source" in case:
                continue
            iob = Path(case["iob_path"])
            iob.write_bytes(b"INERT_COMPLETED_REPLAY_IOB")
            case["outputs"]["iob"] = file_record(iob)
            low, high = case["source_row_range"]
            Path(case["stdout"]).write_text(self._native_log(rows[low-1:high]), encoding="utf-8")
            outputs.extend([file_record(Path(case["stdout"])), *case["outputs"].values()])
        receipt = result_dir / "workbench_preparation.json"
        runtime_tests.write_json(receipt, first)
        dispatch = self.run / "results/full_instrument.dispatch_plan.json"
        shutil.copyfile(first["continuation"]["frozen_inputs"]["dispatch_record"]["path"], dispatch)
        config = self.run / "run_config.json"
        runtime_tests.write_json(config, dict(project="instrument_assembly", run_id="run", mode="single_reflection_fly"))
        borrowed = {f"continuation_artifact_baseline_{index}": file_record(Path(artifact["path"]))
            for index, artifact in enumerate(first["continuation"]["plan"]["units"][0]["terminal_outputs"])}
        manifest = self.run / "run_manifest.json"
        runtime_tests.write_json(manifest, dict(role="simulation_run_manifest", run_id="run", status="failed",
            run_config=file_record(config), inputs=borrowed, outputs=[file_record(receipt), file_record(dispatch), *outputs]))
        second = SingleReflectionContinuationTests("run")
        second.setUp()
        self.addCleanup(second.doCleanups)
        frozen = second.run / "inputs/continuation_parent_manifest.json"
        shutil.copyfile(manifest, frozen)
        second.preparation["input_records"]["continuation_parent_manifest"] = {**file_record(frozen), "source_path": str(manifest)}
        result = second._materialize_cli("baseline")
        self.assertEqual([unit["action"] for unit in result["continuation"]["plan"]["units"]], ["reuse", "reuse"])
        self.assertTrue(Path(result["batches"][0]["stdout"]).is_relative_to(original_parent))
        self.assertTrue(Path(result["batches"][1]["stdout"]).is_relative_to(self.run))
        self.assertFalse((second.run / "simion/full_instrument").exists())
        collection = collect_log(second.preparation, result, second.run)
        self.assertEqual(len(collection["native_terminals"]), 100)
        shutil.rmtree(second.run / "inputs/continuation")
        document = json.loads(manifest.read_text())
        document["inputs"] = {}
        runtime_tests.write_json(manifest, document)
        shutil.copyfile(manifest, frozen)
        second.preparation["input_records"]["continuation_parent_manifest"] = {**file_record(frozen), "source_path": str(manifest)}
        with self.assertRaisesRegex(ValueError, "not manifest-bound"):
            second._materialize_cli("baseline")

    def test_unstarted_parent_phase_falls_back_but_unpublished_receipt_rejects(self) -> None:
        current = self._current_workbench()
        parent = self._parent(current)
        manifest = parent / "run_manifest.json"
        document = json.loads(manifest.read_text())
        missing = {parent / "results/full_instrument.dispatch_plan.json", parent / "results/single_reflection/workbench_preparation.json"}
        document["outputs"] = [record for record in document["outputs"] if Path(record["path"]) not in missing]
        runtime_tests.write_json(manifest, document)
        frozen = self.run / "inputs/continuation_parent_manifest.json"
        shutil.copyfile(manifest, frozen)
        self.preparation["input_records"]["continuation_parent_manifest"] = {**file_record(frozen), "source_path": str(manifest)}
        with self.assertRaisesRegex(ValueError, "unpublished"):
            self._materialize_cli("baseline")
        for path in missing:
            path.unlink()
        self.assertIsNone(self._materialize_cli("baseline"))
        self.assertFalse((self.run / "inputs/continuation").exists())

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 unavailable")
    def test_public_fly_block_mixed_and_zero_missing_uses_real_cli_and_collector(self) -> None:
        """Native and retention admission are inert; executable continuation and collection are real."""
        for phase, missing, replay_missing in (("full_instrument", False, False), ("full_instrument", True, False), ("discovery", False, False), ("discovery", True, False), ("full_instrument", False, True)):
            with self.subTest(phase=phase, missing=missing, replay_missing=replay_missing):
                if phase != "discovery":
                    self.flight = copy.deepcopy(self.workbench_fixture.flight)
                    request = Path(self.preparation["input_records"]["request"]["path"])
                    author = json.loads(request.read_text())
                    runtime_tests.write_json(request, {**author, "flight": self.flight})
                    self.preparation["input_records"]["request"] = file_record(request)
                if phase == "discovery":
                    self.flight = {**self.flight, "pulse": dict(mode="discover", width_us=.1, candidate_times_us=[42.25, 42.5])}
                    request = Path(self.preparation["input_records"]["request"]["path"])
                    author = json.loads(request.read_text())
                    runtime_tests.write_json(request, {**author, "flight": self.flight})
                    self.preparation["input_records"]["request"] = file_record(request)
                current = self._current_workbench(phase)
                parent = self._parent(current, missing_iob=missing)
                parent_guard_paths = set()
                if replay_missing:
                    receipt_path = parent / "results/single_reflection/workbench_preparation.json"
                    parent_wb = json.loads(receipt_path.read_text())
                    next(case for case in parent_wb["batches"] if case["index"] == 2).pop("replay_stdout")
                    changes = []
                    for index, guard in enumerate(parent_wb["pa_guard_records"]):
                        source = Path(guard["path"])
                        destination = parent / "simion/private_fields" / source.parent.name / source.name
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, destination)
                        changes.append((source.as_posix(), destination.as_posix()))
                        guard.update(file_record(destination))
                        parent_guard_paths.add(str(destination))
                    for case in parent_wb["batches"]:
                        for transport in case.get("iob_pa_copies", []):
                            for old, new in changes:
                                if Path(transport["source_record"]["path"]).as_posix() == old:
                                    transport["source_record"]["path"] = str(Path(new))
                        copy_guards = [{**transport["source_record"], "path": transport["destination"]}
                            for transport in case.get("iob_pa_copies", [])]
                        parent_guard_paths.update(guard["path"] for guard in copy_guards)
                        case["iob_pa_guard_records"] = [*copy.deepcopy(parent_wb["pa_guard_records"]), *copy_guards]
                        program = Path(case["outputs"]["program"]["path"])
                        text = program.read_text()
                        for old, new in changes:
                            text = text.replace(json.dumps(Path(old).as_posix()), json.dumps(Path(new).as_posix()))
                        program.write_text(text, encoding="utf-8")
                        case["outputs"]["program"] = file_record(program)
                        spec = Path(case["outputs"]["build_spec"]["path"])
                        text = spec.read_text()
                        for old, new in changes:
                            text = text.replace(old, new)
                        spec.write_text(text, encoding="utf-8")
                        case["outputs"]["build_spec"] = file_record(spec)
                    runtime_tests.write_json(receipt_path, parent_wb)
                    manifest = parent / "run_manifest.json"
                    document = json.loads(manifest.read_text())
                    document["outputs"] = [file_record(Path(record["path"])) for record in document["outputs"]]
                    document["outputs"].extend(file_record(Path(path)) for path in parent_guard_paths)
                    runtime_tests.write_json(manifest, document)
                    frozen = self.run / "inputs/continuation_parent_manifest.json"
                    shutil.copyfile(manifest, frozen)
                    self.preparation["input_records"]["continuation_parent_manifest"] = {**file_record(frozen), "source_path": str(manifest)}
                parent_before = {path: path.read_bytes() for path in parent.rglob("*") if path.is_file()}
                shutil.rmtree(self.run / "simion" / phase)
                result_dir = self.run / "results/single_reflection"
                result_dir.mkdir(parents=True, exist_ok=True)
                (self.run / "logs").mkdir(exist_ok=True)
                runtime_tests.write_json(result_dir / "preparation_receipt.json", self.preparation)
                runtime_tests.write_json(self.run / "run_config.json", dict(project="instrument_assembly", inputs={}))
                runtime_tests.write_json(result_dir / "downstream_receipt.json", dict(receipt_record=file_record(self.downstream_path)))
                with Path(self.preparation["outputs"]["projected_source"]["path"]).open(newline="") as stream:
                    rows = list(csv.DictReader(stream))
                for case in current["batches"]:
                    low, high = case["source_row_range"]
                    (self.run / "inputs" / (case["case_id"] + ".native.log")).write_text(self._native_log(rows[low-1:high]), encoding="utf-8")
                script = self.workbench_fixture.root / "public_fly.ps1"
                script.write_text(_PUBLIC_FLY, encoding="utf-8", newline="\n")
                repo = Path(__file__).resolve().parents[2]
                process = subprocess.run(["pwsh", "-NoProfile", "-File", str(script), str(repo), sys.executable,
                    str(self.run), str(self.snapshot), str(self.field_receipt), phase], cwd=repo,
                    capture_output=True, text=True, encoding="utf-8", timeout=60)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr + '\n'.join(
                    p.read_text(encoding='utf-8-sig', errors='replace') for p in (self.run/'logs').glob('*.stderr.log')))
                counts = json.loads((result_dir / "inert_counts.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(counts.pop("pin_checks"), 1 if missing else 0)
                copy_count = json.loads((result_dir / "inert_copy_count.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(copy_count, len(current["iob_pa_copies"]) if missing else 0)
                native_count = 1 if replay_missing else (1 if phase == "discovery" else 2) if missing else 0
                self.assertEqual(counts, dict(builds=1 if missing else 0, flights=native_count, heavy=native_count))
                self.assertTrue((result_dir / ("discovery" if phase == "discovery" else "baseline") / "collection.json").is_file())
                if phase != "discovery":
                    self.assertTrue((result_dir / "default_replay/replay_comparison.json").is_file())
                published_wb = json.loads((result_dir / ("discovery_workbench_preparation.json" if phase == "discovery" else "workbench_preparation.json")).read_text(encoding="utf-8-sig"))
                borrowed = {artifact["path"] for name in ("continuation", "replay_continuation")
                    if name in published_wb for unit in published_wb[name]["plan"]["units"]
                    if unit["action"] == "reuse" for artifact in unit["terminal_outputs"]}
                config = json.loads((self.run / "run_config.json").read_text(encoding="utf-8-sig"))
                self.assertEqual({value for key, value in config["inputs"].items() if key.startswith("continuation_artifact_")}, borrowed)
                self.assertFalse(parent_guard_paths & set(config["inputs"].values()))
                self.assertEqual(set(json.loads((result_dir / "inert_protected.json").read_text(encoding="utf-8-sig"))), borrowed | parent_guard_paths)
                guarded = set(json.loads((result_dir / "inert_guard_paths.json").read_text(encoding="utf-8-sig")))
                if native_count == 0:
                    self.assertFalse(guarded)
                if replay_missing:
                    self.assertEqual(guarded, parent_guard_paths)
                self.assertEqual(parent_before, {path: path.read_bytes() for path in parent.rglob("*") if path.is_file()})
                shutil.rmtree(self.run / "inputs/continuation")
                shutil.rmtree(self.run / "simion" / phase, ignore_errors=True)
                for transport in (self.run / "simion/iob_fields").glob("*"):
                    if transport.is_file():
                        transport.chmod(0o600)
                shutil.rmtree(self.run / "simion/iob_fields", ignore_errors=True)
                shutil.rmtree(self.run / "results")
                (self.run / "inputs" / f"{phase}_dispatch_request.json").unlink(missing_ok=True)

    def _plan(self, *, missing_iob: bool = False, phase: str = "default_replay") -> tuple[dict, dict, Path]:
        current = self._current_workbench()
        parent = self._parent(current, missing_iob=missing_iob)
        return prepare_phase_continuation(self.preparation, current, self.run, phase), current, parent

    def test_unordered_complete_workbench_batches_reuse_with_actual_native_parser(self) -> None:
        result, _, _ = self._plan()
        self.assertEqual([row["is_complete"] for row in result["completion"]], [True, True])
        self.assertEqual([row["action"] for row in result["plan"]["units"]], ["reuse", "reuse"])
        self.assertEqual(len(result["reusable_parent_cases"]), 2)

    def test_missing_parent_iob_replays_only_that_whole_batch(self) -> None:
        result, _, _ = self._plan(missing_iob=True)
        self.assertEqual([row["action"] for row in result["plan"]["units"]], ["reuse", "replay"])
        self.assertEqual([row["is_complete"] for row in result["completion"]], [True, False])

    def test_default_replay_without_a_published_replay_log_replays_the_batch(self) -> None:
        current = self._current_workbench()
        parent = self._parent(current)
        receipt = parent / "results/single_reflection/workbench_preparation.json"
        workbench = json.loads(receipt.read_text(encoding="utf-8-sig"))
        next(case for case in workbench["batches"] if case["source_row_range"] == [51, 100]).pop("replay_stdout")
        runtime_tests.write_json(receipt, workbench)
        manifest_path = parent / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        manifest["outputs"] = [record for record in manifest["outputs"] if Path(record["path"]).resolve() != receipt.resolve()]
        manifest["outputs"].append(file_record(receipt))
        runtime_tests.write_json(manifest_path, manifest)
        frozen = self.run / "inputs/continuation_parent_manifest.json"
        shutil.copyfile(manifest_path, frozen)
        self.preparation["input_records"]["continuation_parent_manifest"] = {**file_record(frozen), "source_path": str(manifest_path)}
        result = prepare_phase_continuation(self.preparation, current, self.run, "default_replay")
        assert result is not None
        self.assertEqual([row["action"] for row in result["plan"]["units"]], ["reuse", "replay"])

    def test_program_pa_pose_source_or_ids_drift_is_rejected(self) -> None:
        for field, expected in (("program", "Program"), ("pa", "PA fields"), ("pose", "build specification"),
                                ("source", "source"), ("ids", "source-row")):
            with self.subTest(field=field):
                current = self._current_workbench()
                self._parent(current)
                if field == "program":
                    current["batches"][0]["outputs"]["program"] = {**current["batches"][0]["outputs"]["program"], "sha256": "A" * 64}
                elif field == "pa":
                    current["pa_guard_records"][0] = {**current["pa_guard_records"][0], "sha256": "C" * 64}
                elif field == "pose":
                    path = Path(current["batches"][0]["outputs"]["build_spec"]["path"])
                    path.write_text(path.read_text(encoding="utf-8-sig") + "-- pose-drift\n", encoding="utf-8", newline="\n")
                    current["batches"][0]["outputs"]["build_spec"] = file_record(path)
                elif field == "source":
                    current["source_record"] = {**current["source_record"], "sha256": "B" * 64}
                else:
                    current["batches"][0]["expected_particle_ids"] = list(reversed(current["batches"][0]["expected_particle_ids"]))
                with self.assertRaisesRegex(ValueError, expected):
                    prepare_phase_continuation(self.preparation, current, self.run, "baseline")
                shutil.rmtree(self.run / "inputs" / "continuation", ignore_errors=True)
                (self.run / "inputs" / "continuation_parent_manifest.json").unlink(missing_ok=True)
                shutil.rmtree(self.run.parent / "parent", ignore_errors=True)

    def test_parent_receipt_can_bind_same_identity_as_input_and_output(self) -> None:
        result, _, parent = self._plan()
        manifest = json.loads((parent / "run_manifest.json").read_text())
        receipt_record = file_record(parent / "results/single_reflection/workbench_preparation.json")
        manifest["inputs"]["parent_workbench_copy"] = receipt_record
        manifest["outputs"].append(receipt_record)
        runtime_tests.write_json(parent / "run_manifest.json", manifest)
        frozen = self.run / "inputs/continuation_parent_manifest.json"
        shutil.copyfile(parent / "run_manifest.json", frozen)
        self.preparation["input_records"]["continuation_parent_manifest"] = {**file_record(frozen), "source_path": str(parent / "run_manifest.json")}
        shutil.rmtree(self.run / "inputs" / "continuation")
        current = self._current_workbench()
        repeated = prepare_phase_continuation(self.preparation, current, self.run, "default_replay")
        self.assertEqual(result["plan"]["units"], repeated["plan"]["units"])

    def test_freeze_does_not_copy_pa_or_log_or_mutate_external_source(self) -> None:
        source = Path(self.preparation["outputs"]["projected_source"]["path"])
        before = source.read_bytes()
        result, _, _ = self._plan()
        frozen = self.run / "inputs" / "continuation" / "default_replay"
        self.assertEqual(sorted(path.suffix for path in frozen.iterdir()), [".json", ".json", ".json"])
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(result["source_record"], self.preparation["outputs"]["projected_source"])


if __name__ == "__main__":
    unittest.main()
