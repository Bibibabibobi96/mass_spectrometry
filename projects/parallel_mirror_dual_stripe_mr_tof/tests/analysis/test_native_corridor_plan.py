from __future__ import annotations

from pathlib import Path
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_corridor_plan import (
    derive_native_corridor_plan,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_corridor_response_bank import (
    NATIVE_RESPONSE_NAMES,
    RAW_NAME,
    RECEIPT_NAME,
    STANDALONE_RESPONSE_NAMES,
    response_bank_filenames,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_corridor_geometry import (
    build_native_corridor_gem,
)


PROJECT = Path(__file__).resolve().parents[2]
CONTRACT = PROJECT / 'config' / 'simion_candidate_two_zone.json'


class NativeCorridorPlanTest(unittest.TestCase):
    def test_native_corridor_is_derived_directly_from_resolved_geometry(self) -> None:
        plan = derive_native_corridor_plan(CONTRACT)
        self.assertEqual(plan['box_project_mm'], [-20.0, -147.0, -330.0, 20.0, 463.0, 330.0])
        self.assertNotIn('source_plan', plan)
        self.assertNotIn('source_boxes', plan)
        self.assertNotIn('comparison_profile', plan)
        self.assertEqual(plan['grid_shape'], [161, 2441, 2641])
        self.assertEqual(plan['native_family_members'], 10)
        self.assertEqual(plan['response_ids'], list(range(1, 9)))
        self.assertAlmostEqual(plan['family_bytes'] / 1024**3, 77.3307413608, places=6)
        self.assertEqual(plan['parity_bytes'], 0)
        self.assertEqual(plan['staging_worker_bytes'], 0)
        self.assertAlmostEqual(plan['peak_additional_bytes'] / 1024**3, 77.3307413608, places=6)
        source = (PROJECT / 'analysis' / 'native_corridor_plan.py').read_text(encoding='utf-8-sig')
        self.assertNotIn('analyzer_local_refinement_plan', source)

    def test_mr_cache_cannot_build_an_accelerator(self) -> None:
        source = (PROJECT / 'analysis' / 'simion_pa_family_cache.py').read_text(encoding='utf-8-sig')
        self.assertNotIn('"accelerator"', source)
        self.assertNotIn('standalone_response', source)
        self.assertNotIn('build_accelerator_gem', source)

    def test_native_response_bank_has_exact_runtime_inventory(self) -> None:
        names = response_bank_filenames()
        self.assertEqual(len(names), 18)
        self.assertEqual(names, (RAW_NAME, *NATIVE_RESPONSE_NAMES, *STANDALONE_RESPONSE_NAMES, RECEIPT_NAME))
        self.assertEqual(names[0], 'mrtof_analyzer_corridor.pa#')
        self.assertEqual(names[1], 'mrtof_analyzer_corridor.pa1')
        self.assertEqual(names[8], 'mrtof_analyzer_corridor.pa8')
        self.assertEqual(names[9], 'mrtof_analyzer_corridor.response1.pa')
        self.assertEqual(names[-1], 'mrtof_analyzer_corridor.standalone_responses.json')
        self.assertNotIn('mrtof_analyzer_corridor.pa0', names)

    def test_corridor_gem_is_emitted_from_resolved_contract(self) -> None:
        text = build_native_corridor_gem(CONTRACT)
        self.assertIn('grid_shape=161,2441,2641', text)
        self.assertIn('pa_define(161,2441,2641,', text)
        self.assertIn('locate(20,147,330)', text)
        self.assertIn('mesh_mm_per_gu=0.25,0.25,0.25', text)
        self.assertIn('e(16)', text)
        self.assertIn('e(17)', text)
        self.assertIn('Physical IDs 1..20', text)

    def test_iob_builder_declares_four_roles_and_full_table(self) -> None:
        source = (PROJECT / 'simion' / 'build_native_corridor_iob.lua').read_text(encoding='utf-8-sig')
        self.assertIn('4_instance_seed%.iob', source)
        self.assertIn("local expected_roles = {'global_fallback', 'native_corridor', 'accelerator', 'detector'}", source)
        self.assertIn('local role_instances = {}', source)
        self.assertIn('priority.corridor_voltage_groups', source)
        self.assertIn('assert_complete_local_voltage_table(corridor_values)', source)
        self.assertNotIn(':fast_adjust(', source)
        self.assertLess(source.index('assert_complete_local_voltage_table(corridor_values)'), source.index('wb:save(output)'))
        self.assertLess(source.index('wb:save(output)'), source.index('wb:load(output)'))
        self.assertIn('overlap_probe', source)
        self.assertIn('wb:find_at', source)
        self.assertIn("overlap_probe('global_intersection_corridor', role_instances.native_corridor", source)
        self.assertIn("overlap_probe('corridor_intersection_accelerator', role_instances.accelerator", source)
        self.assertIn("overlap_probe('corridor_intersection_detector', role_instances.detector", source)
        self.assertIn("output:gsub('%.iob$', '.mirror_cycle_counter.lua')", source)
        self.assertIn('instances=4 corridor_voltage_table_ids=1..8 fast_adjust=flight', source)
        self.assertNotIn('local_values[index - 1]', source)

    def test_candidate_consumes_role_sidecar_and_adjusts_native_corridor(self) -> None:
        source = (PROJECT / 'simion' / 'mrtof_candidate.lua').read_text(encoding='utf-8-sig')
        self.assertIn("program_path:gsub('%.lua$', '.priority.lua')", source)
        self.assertIn("native_corridor_instances[expected_role] = index", source)
        self.assertIn("adjustable V_mirror_B = mirror_voltages[2]", source)
        self.assertIn("adjustable V_mirror_E = mirror_voltages[5]", source)
        self.assertIn("simion.wb.instances[role_instance('native_corridor')].pa", source)
        self.assertIn('local requested = native_corridor_values(values.analyser)', source)
        self.assertIn('corridor:fast_adjust(requested)', source)
        self.assertIn('local accelerator_instance = accelerator_instance_number()', source)
        self.assertIn('local maximum_instance = maximum_instance_number()', source)
        self.assertNotIn('local accelerator_instance = local_refinement.enabled and 7 or 2', source)
        contract = (PROJECT / 'simion' / 'native_corridor_priority_contract.lua').read_text(encoding='utf-8-sig')
        self.assertIn('corridor_voltage_groups = {', contract)
        for group in ('{2, 7}', '{3, 8}', '{4, 9}', '{5, 10}', '{11, 12}', '{13, 14}', '{16}', '{17}'):
            self.assertIn(group, contract)

    def test_corridor_controller_and_verifier_require_exact_full_inventory(self) -> None:
        creator = (PROJECT / 'simion' / 'create_native_corridor_controller.lua').read_text(encoding='utf-8-sig')
        self.assertIn("assert(not seen[id], 'duplicate corridor electrode ID: ' .. id)", creator)
        self.assertIn("assert(seen[id], 'corridor controller is missing local electrode ID ' .. id)", creator)
        verifier = (PROJECT / 'simion' / 'verify_native_corridor_family.lua').read_text(encoding='utf-8-sig')
        self.assertIn('local function complete_values()', verifier)
        self.assertIn('local native_reference_voltage = 10000', verifier)
        self.assertIn('response:potentials_minmax()', verifier)
        self.assertIn('is not a canonical 10000 V native basis', verifier)
        self.assertIn('combination[id] * responses[id][index] / native_reference_voltage', verifier)
        self.assertIn('linear-combination mismatch', verifier)
        self.assertIn('reopen_combination[id] * responses[id][index] / native_reference_voltage', verifier)
        self.assertIn('Fast Adjust reopen mismatch', verifier)
        self.assertEqual(verifier.count(':fast_adjust(values)'), 2)

    def test_end_to_end_runner_produces_each_full_response_from_coarse_basis(self) -> None:
        source = (PROJECT / 'simion' / 'run_native_corridor_qualification.ps1').read_text(encoding='utf-8-sig')
        self.assertIn("common.simion.pa_family_cache", source)
        self.assertIn("--action','probe'", source)
        self.assertIn("'--action','advance-transaction'", source)
        self.assertIn("'--recovery-policy','none'", source)
        self.assertIn('$buildDirectory=[IO.Path]::GetFullPath([string]$State.build_directory)', source)
        self.assertIn('$scratchDirectory=[IO.Path]::GetFullPath([string]$State.scratch_directory)', source)
        self.assertIn('$missing=@($State.missing_files', source)
        self.assertLess(source.index("--action','probe'"), source.rindex('Invoke-NativeCorridorTransactionLoop'))
        self.assertIn('build_dirichlet_patch_basis.lua', source)
        self.assertIn("$coarseRawExecution $sourceActive '10000'", source)
        self.assertIn('response_recipes', source)
        self.assertIn('Get-NativeCorridorRemainingPeakBytes -Plan $plan -CacheKey $cacheKey', source)
        self.assertIn('$Plan.peak_additional_bytes-$landedPayloadBytes', source)
        self.assertNotIn('$plan.peak_additional_bytes+2*$memberEstimate', source)
        self.assertIn("-Stage dirichlet_response_refine", source)
        self.assertNotIn('Assert-HostResourceHeavyStage', source)
        self.assertIn('[Parameter(Mandatory)][pscustomobject]$CapacitySession', source)
        self.assertGreaterEqual(source.count('Update-ArtifactWorkflowCapacitySession'), 2)
        self.assertIn('Exit-ArtifactWorkflowCapacitySession', source)
        self.assertNotIn('CapacityBaselineReceipt', source)
        self.assertNotIn('CapacityProtectionLeaseId', source)
        self.assertNotIn('create-protection-lease', source)
        self.assertNotIn('renew-protection-lease', source)
        self.assertIn('$sourcePaths=@($record[0].source_basis_paths', source)
        self.assertIn('$buildAlias=New-RunExecutionAlias -TargetDirectory $buildDirectory', source)
        self.assertIn('$scratchAlias=New-RunExecutionAlias -TargetDirectory $scratchDirectory', source)
        self.assertIn('Remove-RunExecutionAlias -ExecutionAlias', source)
        self.assertNotIn('Remove-Item -LiteralPath $buildDirectory', source)
        self.assertNotIn('Remove-Item -LiteralPath $destination', source)
        self.assertIn('}finally{', source)
        self.assertNotIn('prepared_staging_directory', source)
        self.assertNotIn('Invoke-ArtifactCapacityGate', source)
        self.assertNotIn('RequiredHeadroomBytes', source)
        self.assertNotIn('MaximumNewArtifactBytes', source)
        self.assertIn('native_corridor_geometry', source)
        self.assertIn('remap_pa_electrode_ids.lua', source)
        self.assertNotIn('[Parameter(Mandatory)][string]$RawGeometryPath', source)
        fixture = (PROJECT / 'tests' / 'simion' / 'test_native_corridor_stream_fixture.lua').read_text(encoding='utf-8-sig')
        self.assertIn('full_corridor_workers=0', fixture)
        self.assertNotIn('[string[]]$ResponsePaths', source)


if __name__ == '__main__':
    unittest.main()
