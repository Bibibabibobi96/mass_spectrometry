from __future__ import annotations
import unittest
from pathlib import Path

from projects.orthogonal_accelerator.analysis.component_focus_pa_plan import derive
from projects.orthogonal_accelerator.analysis.component_focus_pa_cache import expected_files, identity


class ComponentFocusPAPlanTests(unittest.TestCase):
    def test_focus_is_inside_domain_and_closed_end_is_padded(self) -> None:
        root=Path(__file__).resolve().parents[2]
        plan=derive(root/'config'/'two_zone_component_focus_campaign.json')
        domain=plan['numerical_domain']; layout=plan['layout']
        self.assertAlmostEqual(domain['focus_plane_local_z_mm'], domain['focus_plane_padding_mm'])
        self.assertGreater(domain['focus_plane_local_z_mm'], 0.0)
        self.assertGreaterEqual(domain['span_mm'][2], layout['local_exit_z_mm'] + layout['static_axial_length_mm'] + domain['positive_z_enclosure_padding_mm'])
        self.assertIn('Solid repeller; no coaxial return aperture', plan['gem'])
        self.assertEqual(plan['cache_policy'], 'one_native_fast_adjust_family__manifest_bound_standalone_runtime_responses')
        self.assertEqual(plan['electrode_count'], 19)
        self.assertEqual(plan['geometry_profile_id'], 'closed_two_zone_compact_mr_axial_r3_gap1_4mm')
        self.assertEqual(plan['layout']['gap_1_mm'], 4.0)
        self.assertEqual(plan['layout']['gap_2_mm'], 30.0)
        self.assertEqual(plan['layout']['aperture_height_y_mm'], 26.0)
        self.assertEqual(plan['layout']['static_minimum_y_extent_mm'], 34.0)
        self.assertEqual(domain['span_mm'], [44.5, 34.5, 50.0])
        self.assertEqual(domain['stored_span_mm'], [22.25, 34.5, 50.0])
        self.assertEqual(domain['mirror_axes'], ['x'])
        self.assertEqual(domain['iob_origin_mm'], [0.0, -17.25, 0.0])
        self.assertIn('pa_define($(nx),$(ny),$(nz),planar,x,electrostatic', plan['gem'])
        self.assertIn('locate(0,$(y_span/2),0)', plan['gem'])
        self.assertIn('local nx = math.floor(stored_x_span/mmgu_x + 0.5) + 1', plan['gem'])
        self.assertEqual(plan['layout']['static_axial_length_mm'], 38.0)
        self.assertEqual(plan['theory_seed']['source_center_exit_mm'], 32.0)
        self.assertAlmostEqual(plan['theory_seed']['nominal_energy_per_charge_v'], 4371.2351565, places=7)
        self.assertAlmostEqual(plan['theory_seed']['first_order_focus_drift_mm'], 0.0, places=7)

    def test_identity_includes_dynamic_standalone_response_bank(self) -> None:
        root=Path(__file__).resolve().parents[2]; plan=derive(root/'config'/'two_zone_component_focus_campaign.json')
        builder=root/'simion'/'build_component_focus_pa.lua'
        executable=Path(__file__) # identity only requires stable existing file for this static unit test
        value=identity(plan,builder,executable)
        self.assertEqual(expected_files(plan), tuple(sorted((
            'orthogonal_accelerator_focus.pa#',
            *(f'orthogonal_accelerator_focus.pa{index}' for index in range(20)),
            *(f'orthogonal_accelerator_focus.response{index}.pa' for index in range(1, 20)),
            'orthogonal_accelerator_focus.standalone_responses.json',
        ))))
        self.assertEqual(value['refine_policy']['response_bank'], 'new_pa_object_standalone_responses_1_through_electrode_count')
        self.assertEqual(value['basis_namespace']['native_solution_ids'], list(range(20)))
        self.assertEqual(value['basis_namespace']['electrode_ids'], list(range(1, 20)))
        self.assertEqual(value['basis_namespace']['runtime'], 'manifest_bound_standalone_responses__private_native_fast_adjust_family')
        self.assertEqual(value['grid_phase']['stored_span_mm'], [22.25, 34.5, 50.0])
        self.assertEqual(value['grid_phase']['pa_span_mm'], [44.5, 34.5, 50.0])
        self.assertEqual(value['grid_phase']['mirror_axes'], ['x'])

    def test_builder_preserves_adjustable_electrode_flags_and_uses_official_solution_pattern(self) -> None:
        root=Path(__file__).resolve().parents[2]
        builder=(root/'simion'/'build_component_focus_pa.lua').read_text(encoding='utf-8')
        self.assertNotIn(':potential(', builder)
        self.assertIn('family:refine{solutions={0}}', builder)
        self.assertIn('family:load(output)', builder)
        self.assertIn('for solution=1,electrode_count do', builder)
        self.assertIn('family:refine{solutions=solutions}', builder)
        self.assertIn("for solution=0,electrode_count do", builder)

    def test_runner_applies_retention_before_private_pa_build_and_publishes_receipt(self) -> None:
        root=Path(__file__).resolve().parents[2]
        runner=(root/'simion'/'run_component_focus_pa.ps1').read_text(encoding='utf-8')
        apply=runner.index('Apply-RunArtifactRetention')
        native=runner.index("$stage='native_build'")
        publish=runner.index("$stage='publish'")
        manifest=runner.index('Write-VerifiedRunManifest')
        self.assertLess(apply, native)
        self.assertLess(apply, publish)
        self.assertLess(apply, manifest)
        self.assertIn('$outputs=@($package.summary,$result,$plan,$identity,$retention,', runner)
        self.assertIn('$failureDetail=$_.Exception.Message;throw', runner)
        self.assertIn('Focus PA build failed at $stage.', runner)
        self.assertIn('$reason+=" $failureDetail"', runner)
        self.assertIn('-Outputs $outputs', runner[manifest:])
        self.assertIn("--action','advance-transaction'", runner)
        self.assertIn("$stage='transaction_start'", runner)
        self.assertIn("$stage='seal_and_verify'", runner)
        self.assertIn('simion_pa_family_verification', runner)
        self.assertIn('verify_component_focus_pa.lua', runner)
        self.assertIn("'--owner',$capacity.owner", runner)
        self.assertNotIn("--action','publish'", runner)
        self.assertNotIn('--source-directory', runner)
        self.assertIn("$temporary=[string]$transaction.scratch_directory", runner)
        self.assertNotIn('[IO.Path]::GetTempPath()', runner)
        self.assertIn('Remove-Item -LiteralPath $temporary -Recurse -Force', runner)
        self.assertIn('$electrodeCount=[int]$planDocument.electrode_count', runner)
        self.assertIn('$frozenBuilder $gem $raw $electrodeCount', runner)
        self.assertIn('export_standalone_pa.lua', runner)
        self.assertIn('orthogonal_accelerator_focus.standalone_responses.json', runner)
        self.assertIn("'--response-receipt',$responseReceiptRecipe", runner)
        self.assertIn('$domain=$probe.identity.grid_phase.stored_span_mm', runner)
        self.assertIn('$frozenVerifier $raw $electrodeCount $grid[0] $grid[1] $grid[2]', runner)
        self.assertIn("$cacheRoot=Join-Path $artifactRoot 'common\\simion\\pa_family_cache'", runner)
        self.assertNotIn("$cacheRoot=Join-Path $artifactRoot 'oa_pa_cache'", runner)
        self.assertIn("$runtimeOwnerRun=$package.artifact_run_dir", runner)
        self.assertNotIn("GetFullPath($package.run_dir)", runner)

    def test_cache_adapter_forbids_direct_artifact_publication(self) -> None:
        root=Path(__file__).resolve().parents[2]
        adapter=(root/'analysis'/'component_focus_pa_cache.py').read_text(encoding='utf-8')
        self.assertIn('advance_pa_family_cache_transaction', adapter)
        self.assertNotIn('publish_pa_family_cache', adapter)
        self.assertIn('verification_evidence=evidence', adapter)

    def test_cache_hit_manifest_only_includes_the_build_log_when_it_exists(self) -> None:
        root=Path(__file__).resolve().parents[2]
        runner=(root/'simion'/'run_component_focus_pa.ps1').read_text(encoding='utf-8')
        self.assertIn("$buildLog=Join-Path $package.log_dir 'build_component_focus_pa.log'", runner)
        self.assertIn('if(Test-Path -LiteralPath $buildLog -PathType Leaf){$outputs+=@($buildLog)}', runner)
        manifest=runner[runner.index('Write-VerifiedRunManifest'):]
        self.assertIn('-Outputs $outputs', manifest)
        self.assertNotIn("-Outputs @($package.summary,$result,$plan,$identity,$retention", manifest)

    def test_published_generation_can_acquire_a_new_run_owned_runtime(self) -> None:
        root=Path(__file__).resolve().parents[2]
        runner=(root/'simion'/'run_component_focus_pa.ps1').read_text(encoding='utf-8')
        runtime=runner[runner.index("$stage='prepare_shared_private_runtime'"):]
        self.assertIn("[string]$RuntimeCheckpointPath=''", runner)
        self.assertIn('$runtimeOwnerRun=$package.artifact_run_dir', runtime)
        self.assertIn('if($needsRuntime){($electrodeCount+1)*$nodes*8}else{0}', runner)
        self.assertIn('New-NativeFastAdjustRuntimeFamily', runtime)
        self.assertNotIn('transactionRecord.producer.run_config_path', runtime)
        self.assertNotIn('original producer runtime checkpoint', runtime)

    def test_explicit_runtime_checkpoint_is_reused_without_materialization(self) -> None:
        root=Path(__file__).resolve().parents[2]
        runner=(root/'simion'/'run_component_focus_pa.ps1').read_text(encoding='utf-8')
        runtime=runner[runner.index("$stage='prepare_shared_private_runtime'"):]
        reuse=runtime[runtime.index('if($RuntimeCheckpointPath){'):runtime.index('}else{')]
        create=runtime[runtime.index('}else{'):runtime.index('$runtimeState=Get-Content')]
        self.assertIn('(Resolve-Path -LiteralPath $RuntimeCheckpointPath).Path', reuse)
        self.assertIn('$savedRuntime.directory', reuse)
        self.assertNotIn('New-NativeFastAdjustRuntimeFamily', reuse)
        self.assertIn('New-NativeFastAdjustRuntimeFamily', create)


if __name__=='__main__': unittest.main()
