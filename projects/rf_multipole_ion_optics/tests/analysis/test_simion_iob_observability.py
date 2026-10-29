from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
EXECUTION_SUPPORT = PROJECT_ROOT / "runtime" / "simion_execution.ps1"
INSPECT_SCRIPT = PROJECT_ROOT / "simion" / "workbench" / "inspect_builtin_quad_reference.lua"
ARTIFACT_SUPPORT = REPO_ROOT / "common" / "contracts" / "run_artifact_support.ps1"
INTERFACE_RUNNER = PROJECT_ROOT / "workflows" / "interface_readiness" / "run_simion.ps1"
MASS_FILTER_RUNNER = PROJECT_ROOT / "workflows" / "mass_filter_reference" / "run_simion.ps1"

IOB_EVIDENCE_NAMES = (
    "simion_iob_stdout.txt",
    "simion_iob_stderr.txt",
    "simion_iob_exit_code.txt",
    "simion_iob_contract.txt",
)


class SimionIobObservabilityTests(unittest.TestCase):
    def test_iob_probe_redirects_stdout_stderr_and_persists_exit_code(self) -> None:
        source = EXECUTION_SUPPORT.read_text(encoding="utf-8")
        for token in (
            "$iobStdoutPath = Join-Path $LogDir 'simion_iob_stdout.txt'",
            "$iobStderrPath = Join-Path $LogDir 'simion_iob_stderr.txt'",
            "$iobExitCodePath = Join-Path $LogDir 'simion_iob_exit_code.txt'",
            "$inspectProcess=Invoke-RfSimionPreparationProcess -Name inspect_runtime_iob",
            "-Stdout $iobStdoutPath -Stderr $iobStderrPath",
            "Set-Content -LiteralPath $iobExitCodePath -Encoding ASCII",
            "SIMION IOB runtime contract failed with exit code",
        ):
            self.assertIn(token, source)
        self.assertNotIn("& $SimionExe --nogui --noprompt lua $InspectScript", source)

    def test_managed_inspection_keeps_kernel_exit_code_and_stopped_facts(self) -> None:
        script = r"""
$ErrorActionPreference='Stop'
. (Join-Path $PWD 'common/contracts/run_artifact_support.ps1')
. (Join-Path $PWD 'projects/rf_multipole_ion_optics/runtime/simion_execution.ps1')
function Invoke-ResourceBudgetedProcess {
 param($ArgumentList,$Environment,$RedirectStandardOutput,$RedirectStandardError)
 if($Environment.MULTIPOLE_SIMION_RF_DRIVE_KERNEL_LUA-cne'kernel.lua'){throw 'Kernel input was not explicit'}
 $inspect=$ArgumentList-contains'inspect.lua'
 if($inspect-and(Test-Path (Join-Path $env:RF_TEST_TEMP 'fixture.pa0'))){throw 'placeholder survived into true IOB inspection'}
 if(-not$inspect-and-not(Test-Path (Join-Path $env:RF_TEST_TEMP 'fixture.pa0'))){throw 'template load companion absent'}
 if(-not$inspect-and$ArgumentList[-1]-cne'C:\permanent\quad_monolithic.pa0'){throw 'IOB lost permanent producer controller'}
 'fixture probe'|Set-Content $RedirectStandardOutput
 ''|Set-Content $RedirectStandardError
 [pscustomobject]@{exit_code=$(if($inspect){7}else{0});resource_budget_exceeded=$false;root_process_id=44;root_process_started_at_utc_ticks=123}
}
$seed=Join-Path $env:RF_TEST_TEMP 'registered_seed.pa0';'software-only seed'|Set-Content $seed
$operations=[Collections.Generic.List[object]]::new();$caught=$false
try{Initialize-RfSimionPreparedBatch -SimionExe unused -CandidateDir $env:RF_TEST_TEMP -IobPath (Join-Path $env:RF_TEST_TEMP 'fixture.iob') -Fly2Path source.fly2 `
 -IobBuilderScript builder.lua -ProgramSourcePath program.lua -RunConfigLua config.lua -InspectScript inspect.lua -IobReport report.txt `
 -LogDir $env:RF_TEST_TEMP -RfDriveKernelPath kernel.lua -ControllerPath 'C:\permanent\quad_monolithic.pa0' -NativeOperations $operations -TemplateSeedPaPath $seed}
catch{if(-not$_.Exception.Message.Contains('IOB runtime contract failed with exit code 7')){throw};$caught=$true}
if(-not$caught-or(Get-Content (Join-Path $env:RF_TEST_TEMP 'simion_iob_exit_code.txt') -Raw).Trim()-cne'7'){throw 'Probe exit was not retained'}
if($operations.Count-ne2-or-not$operations[0].observation.exit_confirmed-or$operations[0].observation.returncode-ne0-or$operations[1].observation.returncode-ne7){throw 'Managed native completion facts changed'}
'MANAGED_IOB=PASS'
"""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(["pwsh", "-NoProfile", "-Command", script], cwd=REPO_ROOT,
                env={**os.environ, "RF_TEST_TEMP": directory}, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("MANAGED_IOB=PASS", result.stdout)

    def test_iob_report_is_opened_and_flushed_before_runtime_load(self) -> None:
        source = INSPECT_SCRIPT.read_text(encoding="utf-8")
        ordered_tokens = (
            "local report = assert(io.open(report_path, 'w'))",
            "record('STAGE=report_opened')",
            "record('STAGE=before_run_config_load')",
            "record('STAGE=after_run_config_load')",
            "record('STAGE=before_iob_open')",
            'simion.command(\'"\' .. iob_path .. \'"\')',
            "record('STAGE=after_iob_open')",
            "record('STAGE=before_instance_count_check')",
            "record('STAGE=after_instance_count_check')",
            "record('STATUS=PASS')",
        )
        positions = [source.index(token) for token in ordered_tokens]
        self.assertEqual(positions, sorted(positions))
        record_body = source[source.index("local function record") : source.index("end\n\nrecord")]
        self.assertIn("report:flush()", record_body)

    def test_success_manifests_register_all_iob_runtime_evidence(self) -> None:
        for runner in (INTERFACE_RUNNER, MASS_FILTER_RUNNER):
            source = runner.read_text(encoding="utf-8")
            for name in IOB_EVIDENCE_NAMES:
                self.assertIn(name, source, f"{runner.name} does not register {name}")

    def test_failed_run_manifest_recovers_iob_evidence_from_logs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "runs" / (
                "20260725_000000__test__simion__iob-observability"
            )
            log_dir = run_dir / "logs"
            log_dir.mkdir(parents=True)
            run_config = run_dir / "run_config.json"
            summary = run_dir / "summary.json"
            run_config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": run_dir.name,
                        "project": "rf_multipole_ion_optics",
                        "mode": "iob_observability_test",
                        "project_root": str(REPO_ROOT),
                        "inputs": {},
                        "formal_gate_passed": False,
                    }
                ),
                encoding="utf-8",
            )
            for name in IOB_EVIDENCE_NAMES:
                (log_dir / name).write_text(f"evidence={name}\n", encoding="utf-8")

            environment = os.environ.copy()
            environment.update(
                {
                    "RF_ARTIFACT_SUPPORT": str(ARTIFACT_SUPPORT),
                    "RF_TEST_PYTHON": sys.executable,
                    "RF_TEST_REPO": str(REPO_ROOT),
                    "RF_TEST_CONFIG": str(run_config),
                    "RF_TEST_SUMMARY": str(summary),
                }
            )
            command = (
                ". $env:RF_ARTIFACT_SUPPORT; "
                "Complete-FailedRun -Python $env:RF_TEST_PYTHON "
                "-RepoRoot $env:RF_TEST_REPO -RunConfig $env:RF_TEST_CONFIG "
                "-Summary $env:RF_TEST_SUMMARY -SummaryRole iob_observability_test "
                "-Reason 'simulated IOB failure' -Software @('test')"
            )
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
            output_names = {Path(item["path"]).name for item in manifest["outputs"]}
            self.assertTrue(set(IOB_EVIDENCE_NAMES).issubset(output_names))
            self.assertEqual(manifest["status"], "failed")
            self.assertTrue(all(item["exists"] for item in manifest["outputs"]))


if __name__ == "__main__":
    unittest.main()
