from __future__ import annotations
import unittest
from pathlib import Path

from projects.orthogonal_accelerator.analysis.component_focus_pa_plan import derive
from projects.orthogonal_accelerator.analysis.component_focus_pa_cache import FILES, identity


class ComponentFocusPAPlanTests(unittest.TestCase):
    def test_focus_is_inside_domain_and_closed_end_is_padded(self) -> None:
        root=Path(__file__).resolve().parents[2]
        plan=derive(root/'config'/'two_zone_component_focus_campaign.json')
        domain=plan['numerical_domain']; layout=plan['layout']
        self.assertAlmostEqual(domain['focus_plane_local_z_mm'], domain['focus_plane_padding_mm'])
        self.assertGreater(domain['focus_plane_local_z_mm'], 0.0)
        self.assertGreaterEqual(domain['span_mm'][2], layout['local_exit_z_mm'] + layout['static_axial_length_mm'] + domain['positive_z_enclosure_padding_mm'])
        self.assertIn('Solid repeller; no coaxial return aperture', plan['gem'])
        self.assertEqual(plan['cache_policy'], 'one_native_fast_adjust_family_pa_hash_and_pa0_through_pa9__published_read_only_no_detached_response_bank')
        self.assertEqual(plan['geometry_profile_id'], 'closed_two_zone_compact_mr_axial_r3_gap1_4mm')
        self.assertEqual(plan['layout']['gap_1_mm'], 4.0)
        self.assertEqual(plan['layout']['gap_2_mm'], 30.0)
        self.assertEqual(plan['layout']['aperture_height_y_mm'], 16.0)
        self.assertEqual(plan['layout']['static_minimum_y_extent_mm'], 24.0)
        self.assertEqual(plan['layout']['static_axial_length_mm'], 38.0)
        self.assertEqual(plan['theory_seed']['source_center_exit_mm'], 32.0)
        self.assertAlmostEqual(plan['theory_seed']['nominal_energy_per_charge_v'], 4371.2351565, places=7)
        self.assertAlmostEqual(plan['theory_seed']['first_order_focus_drift_mm'], 0.0, places=7)

    def test_identity_excludes_response_bank_and_binds_plan(self) -> None:
        root=Path(__file__).resolve().parents[2]; plan=derive(root/'config'/'two_zone_component_focus_campaign.json')
        builder=root/'simion'/'build_component_focus_pa.lua'
        executable=Path(__file__) # identity only requires stable existing file for this static unit test
        value=identity(plan,builder,executable)
        self.assertEqual(FILES, ('orthogonal_accelerator_focus.pa#', *(f'orthogonal_accelerator_focus.pa{index}' for index in range(10))))
        self.assertEqual(value['refine_policy']['response_bank'], 'absent')
        self.assertEqual(value['basis_namespace']['native_solution_ids'], list(range(10)))
        self.assertEqual(value['basis_namespace']['runtime'], 'pa0_fast_adjust_only')

    def test_builder_preserves_adjustable_electrode_flags_and_uses_official_solution_pattern(self) -> None:
        root=Path(__file__).resolve().parents[2]
        builder=(root/'simion'/'build_component_focus_pa.lua').read_text(encoding='utf-8')
        self.assertNotIn(':potential(', builder)
        self.assertIn('family:refine{solutions={0}}', builder)
        self.assertIn('family:load(output)', builder)
        self.assertIn('family:refine{solutions={1,2,3,4,5,6,7,8,9}}', builder)
        self.assertIn("for solution=0,9 do", builder)

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


if __name__=='__main__': unittest.main()
