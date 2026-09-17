from __future__ import annotations

import unittest
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_profile import REGIONS


PROJECT = Path(__file__).resolve().parents[2]


class MirrorRealFieldProfileTest(unittest.TestCase):
    def test_regions_cover_axis_once_without_gaps(self) -> None:
        values = [z for _, _, lower, upper in REGIONS for z in range(lower, upper + 1)]
        self.assertEqual(values, list(range(-319, 320)))
        self.assertEqual(len(values), len(set(values)))

    def test_fixed_quarter_mm_runner_refines_only_two_operating_points(self) -> None:
        source = (PROJECT / "simion" / "run_mirror_turn_fixed_grid_validation.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("build_dirichlet_patch_operating_pa.lua", source)
        self.assertIn("mirror_turn_negative", source)
        self.assertIn("mirror_turn_positive", source)
        self.assertIn("response_family_not_built=$true", source)
        self.assertIn("fixed_dirichlet_operating_pa_cache", source)
        self.assertIn('("--target-mirror-voltages-v={0}"-f$targetMirrorVoltages)', source)
        self.assertNotIn("'--target-mirror-voltages-v',$targetMirrorVoltages", source)
        self.assertIn('$outputName="local_{0}.pa0"-f$label', source)
        self.assertIn("z_range_mm[0]-$fixedSampleStep", source)
        self.assertIn("sample_step_mm=$fixedSampleStep", source)
        self.assertIn("sample_fixed_operating_field_slice.lua", source)
        self.assertIn("mirror_fixed_operating_field_l1", source)
        self.assertIn("validation_diagnostic__acceptance_gates_remain_open", source)
        self.assertIn("$operatingCacheKey=[string]$operatingCacheProbe.cache_key", source)
        self.assertIn("local_operating_pa_cache_final_probe.json", source)
        self.assertIn("$pinnedGenerationSha256=Split-Path -Leaf", source)
        self.assertIn("--expected-generation-sha256',$pinnedGenerationSha256", source)
        self.assertIn("parent_operating_pa_generation.json", source)
        self.assertIn("references no available frozen operating-PA generation", source)
        self.assertIn("parent_operating_pa_generation=$parentGenerationContract", source)
        self.assertEqual(source.count("-ProtectedCacheKeys @($operatingCacheKey)"), 2)
        self.assertNotIn("0p25mm__other_regions_at_0p5mm__candidate", source)
        self.assertNotIn("--lua-output", source)
        self.assertNotIn("build_component_basis.lua", source)

    def test_fixed_mirror_cache_misses_use_repository_scheduling_and_serial_publish(self) -> None:
        source = (PROJECT / "simion" / "run_mirror_turn_fixed_grid_validation.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("work_item_count=$fixedMisses.Count", source)
        self.assertIn("independent_work_items=$true", source)
        self.assertIn("Start-ObservedFormalProcess", source)
        self.assertIn("Invoke-ResourceBudgetedProcesses", source)
        self.assertIn("private_compile_remap_solve_then_serial_cache_publish", source)
        self.assertNotIn("$fixedMisses.Count-eq1){\n      $single", source)
        self.assertIn("-WaitForNaturalCompletionAfterObservation:$oneMiss", source)
        self.assertIn("sibling work will not start", source)
        self.assertIn("if($didFormalObservation){", source)
        self.assertIn("Stop-ManagedSolverProcesses -ProcessIds @($fixedFormalRecord.tracked_process_ids)", source)
        self.assertIn("$fixedTransientBytes+=$parentBytes*16", source)
        self.assertIn("artifact_capacity_gate_fixed_pa_dispatch.json", source)
        self.assertLess(
            source.index("Invoke-ResourceBudgetedProcesses"),
            source.index("'--action','publish','--source-directory',$miss.output_directory"),
        )
        self.assertNotIn("maximum_parallel", source)

    def test_fixed_mirror_worker_reclaims_large_intermediates(self) -> None:
        source = (PROJECT / "simion" / "run_fixed_dirichlet_mirror_worker.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("Remove-Item -LiteralPath $PhysicalPaPath", source)
        self.assertIn("Remove-Item -LiteralPath $GroupedPaPath", source)
        self.assertIn("Fixed-mirror worker did not produce its operating PA0", source)
        self.assertNotIn("fixed_dirichlet_operating_pa_cache", source)

    def test_fixed_grid_runner_can_reuse_its_iob_for_native_transverse_l1(self) -> None:
        source = (PROJECT / "simion" / "run_mirror_turn_fixed_grid_validation.ps1").read_text(
            encoding="utf-8"
        )
        program = (PROJECT / "simion" / "mrtof_mirror_transverse_l1_validation.lua").read_text(
            encoding="utf-8"
        )
        self.assertIn("[switch]$NativeTransverseL1", source)
        self.assertIn("mirror_native_transverse_l1", source)
        self.assertIn("native_transverse_l1_probe_contract.json", source)
        self.assertIn("native_transverse_l1.log", source)
        self.assertIn("native_transverse_l1=[bool]$NativeTransverseL1", source)
        self.assertIn("if($useRealField -and -not $NativeTransverseL1){", source)
        self.assertIn("if($useRealField){\n    if($useVoltagePoint)", source)
        self.assertIn("phase=first_return", program)
        self.assertIn("phase=full_return", program)
        self.assertNotIn("fast_adjust", program.lower())
        self.assertNotIn(":refine", program.lower())


if __name__ == "__main__":
    unittest.main()
