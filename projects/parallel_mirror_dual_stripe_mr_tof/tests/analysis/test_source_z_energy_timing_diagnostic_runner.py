from __future__ import annotations

from pathlib import Path
import unittest


RUNNER = (
    Path(__file__).resolve().parents[2]
    / "analysis"
    / "run_source_z_energy_timing_diagnostic.ps1"
)


class SourceZEnergyTimingDiagnosticRunnerTests(unittest.TestCase):
    def test_runner_is_read_only_compact_analysis(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        for token in (
            "[Parameter(Mandatory)][string]$FlightRunPath",
            "--require-mode finite_3d_two_prism_voltage_trial",
            "Copy-VerifiedRunInput",
            "Invoke-ArtifactCapacityGate",
            "Apply-RunArtifactRetention",
            "Write-VerifiedRunManifest",
            "source_z_energy_timing_diagnostic",
            "terminal_plane_diagnostic=$data.terminal_plane_diagnostic",
            "solver_execution='none'",
            "source_or_peak_filtering='none'",
            "-RetentionClass compact",
            "[Nullable[double]]$CapacityTargetGiB=$null",
            "[Nullable[double]]$CapacityMinimumFreeGiB=$null",
            "$capacityStartupParameters.TargetGiB",
            "$capacityTerminalParameters.TargetGiB",
            "capacity_target_gib=",
            "capacity_minimum_free_gib=",
        ):
            self.assertIn(token, source)
        for forbidden in ("simion.exe", "run_iob_flight", "pa:refine", "Remove-Item"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
