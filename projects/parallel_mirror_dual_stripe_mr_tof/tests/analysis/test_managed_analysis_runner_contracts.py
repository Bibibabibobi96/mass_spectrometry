"""Table-driven source contracts for lightweight MR-TOF analysis runners."""

from __future__ import annotations

import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]


CASES = {
    "freeze_bunch_schedule": {
        "path": "analysis/run_freeze_bunch_pulse_schedule.ps1",
        "session": True,
        "required": (
            "[Parameter(Mandatory)][string]$BunchSourceRunManifest",
            "[Parameter(Mandatory)][string]$StaticPilotRunManifest",
            "[Parameter(Mandatory)][ValidateRange(0.0,[double]::MaxValue)][double]$GuardUs",
            "[Nullable[double]]$PulseOffTimeUs=$null",
            "--require-mode deterministic_bunch_source_materialization",
            "Get-VerifiedOutputRecord",
            "static pilot trial receipt",
            "static pilot log",
            "Copy-VerifiedRunInput",
            "--pulse-off-time-us",
            "caller_common_envelope_verified_against_this_cohort",
            "bunch_source_and_schedule",
            "freeze-schedule",
            "bunch_global_pulse_schedule.json",
            "solver_execution='none'",
        ),
        "forbidden": ("$GuardUs=", "simion.exe", "run_iob", "refine"),
    },
    "source_z_timing_diagnostic": {
        "path": "analysis/run_source_z_energy_timing_diagnostic.ps1",
        "session": True,
        "required": (
            "[Parameter(Mandatory)][string]$FlightRunPath",
            "--require-mode finite_3d_two_prism_voltage_trial",
            "Copy-VerifiedRunInput",
            "Apply-RunArtifactRetention",
            "source_z_energy_timing_diagnostic",
            "terminal_plane_diagnostic=$data.terminal_plane_diagnostic",
            "central_plane_focus_history=$data.central_plane_focus_history",
            "solver_execution='none'",
            "source_or_peak_filtering='none'",
            "-RetentionClass compact",
        ),
        "forbidden": ("simion.exe", "run_iob_flight", "pa:refine", "Remove-Item"),
    },
    "publish_bunch_source": {
        "path": "analysis/run_publish_bunch_source.ps1",
        "session": True,
        "required": (
            "[Parameter(Mandatory)][string]$SourceDefinitionPath",
            "[Parameter(Mandatory)][string]$GeometryContractPath",
            "Copy-VerifiedRunInput -Source $sourceDefinition",
            "Copy-VerifiedRunInput -Source $geometryContract",
            "--geometry-contract $frozenGeometry",
            "Apply-RunArtifactRetention",
            "bunch_source_states.csv",
            "bunch_source.fly2",
            "bunch_source_receipt.json",
            "solver_execution='none'",
        ),
        "forbidden": ("simion.exe", "run_iob", "refine"),
    },
    "single_center_timestep": {
        "path": "analysis/run_single_center_timestep_convergence.ps1",
        "session": True,
        "required": (
            "[ValidateCount(3,3)]",
            "verify_run_manifest.py",
            "--require-mode finite_3d_two_prism_voltage_trial",
            "Copy-VerifiedRunInput",
            "single_center_timestep_convergence",
            "acceptance_threshold=$null",
            "Apply-RunArtifactRetention",
        ),
        "forbidden": ("SIMION.exe", "refine"),
    },
    "accelerator_pulse_schedule": {
        "path": "analysis/run_freeze_accelerator_pulse_schedule.ps1",
        "session": True,
        "required": (
            "CenterRunManifest",
            "finite_3d_two_prism_voltage_trial",
            "accelerator_global_pulse_schedule_freeze",
            "Copy-VerifiedRunInput",
            "freeze-pulse-schedule",
            "ion_time_of_flight_us_from_common_tob_zero_release",
            "pending_multi_particle_safe_exit_envelope",
        ),
        "forbidden": ("AcceleratorPulseOffTimeUs", "SIMION-2020"),
    },
    "target_operating_chain": {
        "path": "analysis/run_target_operating_point_chain.ps1",
        "required": (
            "run_mirror_exact_k_operating_point.ps1",
            "run_dual_stripe_operating_seed.ps1",
            "ExactKRunManifest = $exactManifest",
            "target_drift_period_ratio",
            "target_half_oscillation_count",
            "qualification = [string]$stripeSummary.qualification",
            "ContractPath",
            "refuses to overwrite",
        ),
        "forbidden": ("[double]$K", "25.5"),
    },
    "recover_bunch": {
        "path": "analysis/run_recover_completed_bunch_flight.ps1",
        "session": True,
        "required": (
            "Enter-ArtifactWorkflowCapacitySession",
            "Update-ArtifactWorkflowCapacitySession",
            "Exit-ArtifactWorkflowCapacitySession",
        ),
        "forbidden": (
            "CapacityTargetGiB",
            "CapacityMinimumFreeGiB",
            "Invoke-ArtifactCapacityGate",
        ),
    },
}


class ManagedAnalysisRunnerContractTests(unittest.TestCase):
    def test_runner_contract_matrix(self) -> None:
        for name, case in CASES.items():
            with self.subTest(case=name):
                source = (PROJECT / case["path"]).read_text(encoding="utf-8-sig")
                for token in case["required"]:
                    self.assertIn(token, source, token)
                if case.get("session"):
                    for token in (
                        "Enter-ArtifactWorkflowCapacitySession",
                        "Update-ArtifactWorkflowCapacitySession",
                        "Exit-ArtifactWorkflowCapacitySession",
                        "-RemainingCommittedNewBytes 0",
                    ):
                        self.assertIn(token, source, token)
                lowered = source.lower()
                for token in case["forbidden"]:
                    haystack = lowered if token.lower() == token else source
                    self.assertNotIn(token, haystack, token)

if __name__ == "__main__":
    unittest.main()
