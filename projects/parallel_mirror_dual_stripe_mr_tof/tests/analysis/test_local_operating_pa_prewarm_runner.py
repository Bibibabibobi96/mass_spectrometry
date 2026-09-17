"""Static contract tests for the managed local operating-PA prewarm runner."""
from __future__ import annotations

from pathlib import Path
import unittest


class LocalOperatingPAPrewarmRunnerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (
            Path(__file__).resolve().parents[2]
            / "simion" / "run_local_operating_pa_prewarm.ps1"
        ).read_text(encoding="utf-8-sig")

    def test_runner_uses_managed_identity_capacity_and_resource_boundaries(self) -> None:
        self.assertIn("--action','plan'", self.source)
        self.assertIn("--action','probe'", self.source)
        self.assertIn("Invoke-ArtifactCapacityGate", self.source)
        self.assertIn("Enter-HostExecutionLease -Role SIMION -Stage prepare", self.source)
        self.assertIn("Write-VerifiedRunManifest", self.source)
        self.assertIn("Complete-FailedRun", self.source)
        self.assertIn("'{0:R}'", self.source)
        self.assertIn("function ConvertTo-ArtifactRunPath", self.source)
        self.assertIn("cache_adapter_implementation=", self.source)
        self.assertIn("identity_output=", self.source)
        self.assertIn("source_family_cache_key", self.source)
        self.assertIn("$protectedCacheKeys=@($cacheKey)+$sourceFamilyCacheKeys", self.source)
        self.assertEqual(self.source.count("-ProtectedCacheKeys $protectedCacheKeys"), 2)
        self.assertNotIn("local_operating_pa_cache_identity=ConvertTo-ArtifactRunPath", self.source)

    def test_hit_path_performs_zero_composition_and_miss_publishes_one_group(self) -> None:
        self.assertIn("if($probe.disposition-eq'miss')", self.source)
        self.assertIn("Start-LaneBatch -Plans $lanePlans", self.source)
        self.assertIn("--action','publish'", self.source)
        self.assertIn("composition_lane_count=$lanePlans.Count", self.source)
        self.assertIn("$lanePlans|ForEach-Object{[string]$_.path}", self.source)
        self.assertNotIn("$lanePlans.path", self.source)
        self.assertNotIn("refine", self.source.casefold())

    def test_exact_five_names_and_corrupt_fail_closed_are_explicit(self) -> None:
        for name in (
            "local_negative_mirror.pa", "local_negative_bridge.pa", "local_central.pa",
            "local_positive_bridge.pa", "local_positive_mirror.pa",
        ):
            self.assertIn(name, self.source)
        self.assertIn("$probe.disposition-eq'corrupt'", self.source)
        self.assertIn("did not verify as an exact hit after prewarm", self.source)

    def test_optional_mirror_adjustment_is_all_or_none_and_contract_bound(self) -> None:
        for name in (
            "MirrorBVoltageV", "MirrorCVoltageV", "MirrorDVoltageV", "MirrorEVoltageV",
        ):
            self.assertIn(name, self.source)
        self.assertIn("$mirrorValueCount-notin@(0,4)", self.source)
        self.assertIn("--target-mirror-voltages-v=$mirrorText", self.source)
        self.assertIn("target_mirror_voltage_vector_v=", self.source)


if __name__ == "__main__":
    unittest.main()
