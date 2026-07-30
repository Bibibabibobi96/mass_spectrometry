from __future__ import annotations

import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
INTEGRATION_ROOT = (
    REPO_ROOT
    / "integrations"
    / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
)


class RfToOatofTransferRunnerTests(unittest.TestCase):
    def test_runner_orders_transfer_phases_and_forwards_source_runs(self) -> None:
        runner = (
            INTEGRATION_ROOT / "runtime" / "run_transfer.ps1"
        ).read_text(encoding="utf-8")
        pre_pulse_index = runner.index(
            "& $runtime.implementation.pre_pulse_runner"
        )
        pulse_capture_index = runner.index(
            "& $runtime.implementation.pulse_capture_runner"
        )
        analyzer_index = runner.index(
            "& $runtime.implementation.analyzer_transport_runner"
        )
        self.assertLess(pre_pulse_index, pulse_capture_index)
        self.assertLess(pulse_capture_index, analyzer_index)
        self.assertIn("-SourceRunId $prePulseRunId", runner)
        self.assertIn("-SourceRunId $pulseCaptureRunId", runner)
        self.assertIn("[Parameter(Mandatory)][string]$ConnectionProfileId", runner)
        self.assertIn("[Parameter(Mandatory)][string]$ResolvedConnection", runner)
        self.assertNotIn("ConnectorCaseId", runner)
        self.assertIn("[string]$PythonExe", runner)
        self.assertEqual(runner.count("-PythonExe $python"), 3)
        self.assertIn(
            "inputs\\runtime_snapshot", runner
        )
        self.assertIn(
            "common\\contracts\\verify_run_manifest.py", runner
        )
        self.assertIn(
            "Resolve-RfDirectChildDirectory -ParentRoot $artifactRoot", runner
        )
        self.assertIn("$env:PYTHONPATH = $snapshotRoot", runner)
        self.assertIn("$env:PYTHONNOUSERSITE = '1'", runner)
        self.assertIn("Push-Location -LiteralPath $snapshotRoot", runner)
        for requirement in (
            "--require-status success",
            "--require-run-id $case.run_id",
            "--require-project $upstreamProjectId",
            "--require-mode $case.mode",
        ):
            self.assertIn(requirement, runner)
        self.assertNotIn(
            "Join-Path $repoRoot 'common\\contracts\\verify_run_manifest.py'",
            runner,
        )

    def test_pulse_capture_requires_explicit_pre_pulse_source(self) -> None:
        runner = (
            INTEGRATION_ROOT
            / "stages"
            / "comsol"
            / "run_pulse_capture.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("[Parameter(Mandatory)][string]$SourceRunId", runner)
        self.assertIn("$sourceRunConfiguration.inputs.pre_pulse_contract", runner)
        self.assertNotIn("$pulse_captureDocument.source.timing_state_run_id", runner)
        self.assertIn("New-RfRunPackage -Python $python", runner)

    def test_pre_pulse_freezes_and_consumes_resolved_connection_without_fallback(
        self,
    ) -> None:
        runner = (
            INTEGRATION_ROOT
            / "stages"
            / "comsol"
            / "run_pre_pulse_interface_transport.ps1"
        ).read_text(encoding="utf-8")
        for required in (
            "resolved_connection = $frozenResolvedConnection",
            "RF_OATOF_RESOLVED_CONNECTION",
            "port_geometry.downstream.coordinate_frame.frame_id",
            "spatial_registration.actual_gap_mm",
            "connector.length_mm",
            "potential_alignment.mode",
            "clock_alignment.mode",
        ):
            self.assertIn(required, runner)
        for forbidden in (
            "resolve_spatial_registration",
            "resolve_s2_connector_case",
            "nominal_registration.connector_gap_mm",
            "passive_connector_geometry.length_mm",
            "ConnectorCaseId",
        ):
            self.assertNotIn(forbidden, runner)


if __name__ == "__main__":
    unittest.main()
