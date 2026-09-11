from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from common.simion.pa_family_cache import CACHE_KEY_FIELDS
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_pa_family import (
    derive_local_pa_family_contract,
    local_pa_family_filenames,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_patch_geometry import (
    build_local_patch_gem,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


PROJECT = Path(__file__).resolve().parents[2]
CONTRACT = PROJECT / "config" / "simion_candidate_two_zone.json"


class AnalyzerLocalPaFamilyTest(unittest.TestCase):
    def test_dirichlet_builder_derives_basis_voltage_from_named_geometry_electrodes(self) -> None:
        source = (
            PROJECT.parents[1] / "common" / "simion" / "build_dirichlet_patch_basis.lua"
        ).read_text(encoding="utf-8")
        self.assertIn("local function legacy_source_basis_voltage(pa)", source)
        self.assertIn("source_active_ids", source)
        self.assertIn("active source geometry electrode is not physical", source)
        self.assertIn("source active electrode IDs must align one-to-one", source)
        self.assertIn("active[identifier] and basis_voltage or 0", source)
        self.assertNotIn("active[identifier] and 1 or 0", source)

    def test_local_family_runner_passes_source_raw_pa_and_physical_ids(self) -> None:
        source = (PROJECT / "simion" / "run_analyzer_local_pa_family.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("$sourcePhysicalIds=@($recipe.physical_ids", source)
        self.assertIn("([string]$familyContract.coarse_raw_pa_path),$sourcePhysicalIds", source)

    def test_operating_patch_builder_samples_parent_and_refines_once(self) -> None:
        source = (
            PROJECT.parents[1] / "common" / "simion" / "build_dirichlet_patch_operating_pa.lua"
        ).read_text(encoding="utf-8")
        self.assertIn("source:potential_vc(sx,sy,sz)", source)
        self.assertIn("identifier==0 and 0 or voltages[identifier]", source)
        self.assertIn("solved:refine()", source)
        self.assertNotIn("fast_adjust", source)

    def test_generic_voltageizer_uses_native_family_without_refine(self) -> None:
        source = (
            PROJECT.parents[1] / "common" / "simion" / "voltageize_pa0.lua"
        ).read_text(encoding="utf-8")
        self.assertIn("pa:fast_adjust(values)", source)
        self.assertIn("source~=output", source)
        self.assertNotIn(":refine", source)

    def test_local_workbench_publishes_final_artifact_input_paths(self) -> None:
        source = (
            PROJECT / "simion" / "run_analyzer_local_workbench.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("$artifactReviewed=Join-Path $package.artifact_run_dir", source)
        self.assertIn("$artifactMaterialization=Join-Path $package.artifact_run_dir", source)
        config_line = next(
            line for line in source.splitlines()
            if "$configuration.inputs=[ordered]" in line
        )
        self.assertIn("reviewed_geometry_contract=$artifactReviewed", config_line)
        self.assertIn("operating_point_materialization=$artifactMaterialization", config_line)
        self.assertNotIn("reviewed_geometry_contract=$frozenReviewed", config_line)
        self.assertNotIn("operating_point_materialization=$frozenMaterialization", config_line)

    def test_local_workbench_combines_cached_basis_without_refine_or_junction(self) -> None:
        source = (PROJECT / "simion" / "run_analyzer_local_workbench.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("adjust_operating_pa_from_basis.lua", source)
        self.assertIn("measure_pa_basis_voltage.lua", source)
        self.assertIn("standalone_response_filename", source)
        self.assertIn("$responsePaths+=New-ShortPaCopy -Source $responseSource", source)
        self.assertIn("combine_local_operating_replacements_without_refine", source)
        self.assertIn("Assert-AnalyzerLocalFamilyCacheReadOnly", source)
        self.assertIn("-VerificationAttempts 3", source)
        self.assertIn("verified prior-workbench delta basis superposition", source)
        self.assertIn("changed_local_voltage_indices", source)
        self.assertIn("$localVoltageDeltas", source)
        self.assertIn("base_local_workbench_manifest", source)
        self.assertIn("$responseId=$changedIndex+1", source)
        self.assertIn("$changedLocalIndices.Count-eq0", source)
        self.assertIn("$capacityProtectedPaths", source)
        self.assertIn("@($families.generation_directory)", source)
        self.assertEqual(source.count("-ProtectedCacheKeys @($families.cache_key)"), 2)
        self.assertIn("([IO.Path]::ChangeExtension($sourceAnalyzer,'.pa2'))", source)
        self.assertNotIn(
            "Copy-VerifiedRunInput -Source ([IO.Path]::ChangeExtension($sourceAnalyzer,'.pa2'))",
            source,
        )
        self.assertNotIn("$temporaryBasisDir", source)
        self.assertIn("short_pa_path_support.ps1", source)
        self.assertIn("$privateBase,$operatingLocal,($responsePaths-join'|')", source)
        self.assertNotIn("--materialize-manifest", source)
        self.assertNotIn("$basisFamilyDir", source)
        self.assertNotIn("$globalSourceStandalone", source)
        self.assertNotIn("-ItemType Junction", source)
        self.assertNotIn("build_dirichlet_patch_operating_pa.lua", source)

    def test_local_workbench_can_rebase_onto_new_family_zero_responses(self) -> None:
        source = (PROJECT / "simion" / "run_analyzer_local_workbench.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("[switch]$RebuildFromFamilyZeroBase", source)
        self.assertIn("if($RebuildFromFamilyZeroBase)", source)
        self.assertIn("$baseMaterialization=$null", source)
        self.assertIn("rebuild_from_family_zero_base=[bool]$RebuildFromFamilyZeroBase", source)

    def test_two_prism_trial_reuses_local_basis_without_refine(self) -> None:
        source = (PROJECT / "simion" / "run_two_prism_trial.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("$LocalWorkbenchRunPath", source)
        self.assertIn("adjust_operating_pa_from_basis.lua", source)
        self.assertIn("global_fast_adjust_plus_nonzero_local_basis_deltas__no_refine", source)
        self.assertIn("$changedIndices.Count-eq 0", source)
        self.assertIn("Resolve-AnalyzerLocalFamilyCacheGeneration", source)
        self.assertIn("build_local_refinement_iob.lua", source)
        self.assertIn("extraction must use the unchanged static prism voltages", source)
        self.assertNotIn("post_switch_global_fallback=true", source)
        self.assertIn("$config.parameters.local_extraction_field_handoff=$null", source)
        self.assertIn("standalone_response_filename", source)
        self.assertIn("$privateBasisPaths+=New-ShortPaCopy -Source $responseSource", source)
        self.assertIn("basis_projection='independently_constructed_standalone_response'", source)
        self.assertIn("native_family_member_opened=$false", source)
        self.assertIn("transient_miss_not_published", source)
        self.assertIn("$privateOperatingBase", source)
        self.assertIn("[int64]$requiredBytes=0;[int64]$transientBytes=0", source)
        self.assertIn("$transientBytes+=$localOperatingBytes+$perRegionProjectionBytes", source)
        self.assertIn("$minimumFreeGiB=([double]([int64](500GB)+$requiredBytes+$transientBytes)/1GB)", source)
        self.assertIn("-MinimumFreeGiB $minimumFreeGiB", source)
        self.assertIn("if($reuseFrozenWorkbenchAnalyzer)", source)
        self.assertIn("}elseif($earlyOperatingCacheHit){", source)
        self.assertIn("if($earlyChangedIndexCount-gt 0)", source)
        self.assertIn("$reuseFrozenWorkbenchAnalyzer", source)
        self.assertIn("verified_frozen_workbench_global_and_local_pa0_reuse", source)
        self.assertIn("if(-not$reuseFrozenWorkbenchAnalyzer){", source)
        self.assertIn("Remove-Item -LiteralPath $scratchPath -Force", source)
        self.assertNotIn("$requiredBytes+=3*$baseOperatingBytes", source)
        self.assertNotIn("-ItemType Junction", source)
        self.assertIn("$localCacheSentinelHashes", source)
        self.assertIn("changed immutable local PA-family bookkeeping", source)
        self.assertIn("$localCacheSentinelHashes", source)
        self.assertIn("immutable local PA cache sentinel", source)
        self.assertIn("foreach($changedIndex in $changedIndices)", source)
        self.assertIn("$responseId=5+$changedIndex", source)
        self.assertIn("Assert-AnalyzerLocalFamilyCacheReadOnly", source)
        self.assertIn("-VerificationAttempts 3", source)
        self.assertNotIn("--materialize-manifest", source)
        self.assertNotIn("$basisFamilyDir", source)
        self.assertIn("$startupProtectedCacheKeys=if($earlyOperatingCacheHit)", source)
        self.assertIn("$protectedCacheKeys=@($localFamilies.cache_key)", source)
        self.assertIn("$protectedCacheKeys+=$operatingCacheKey", source)

    def test_iob_builders_accept_verified_standalone_read_only_pa_inputs(self) -> None:
        three = (PROJECT / "simion" / "build_three_component_iob.lua").read_text(
            encoding="utf-8"
        )
        local = (PROJECT / "simion" / "build_local_refinement_iob.lua").read_text(
            encoding="utf-8"
        )
        for token in (
            "iob_input_analyzer%.pa$",
            "iob_input_accelerator%.pa$",
            "iob_input_detector%.pa$",
        ):
            self.assertIn(token, three)
            self.assertIn(token, local)
        self.assertIn("pa_mode=='read_only_voltageized' and projected_bindings", three)
        self.assertIn("iob_input_local_'..(index-1)..'%.pa$'", local)
        self.assertIn("pulsed_mixed_bindings", local)
        self.assertIn("mrtof_accelerator%.pa0$", local)
        program = (PROJECT / "simion" / "mrtof_candidate.lua").read_text(
            encoding="utf-8"
        )
        for token in (
            "iob_input_analyzer%.pa$",
            "iob_input_accelerator%.pa$",
            "iob_input_detector%.pa$",
            "iob_input_local_5%.pa$",
        ):
            self.assertIn(token, program)

    def test_local_family_builder_protects_its_published_cache_at_terminal_gate(self) -> None:
        source = (PROJECT / "simion" / "run_analyzer_local_pa_family.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "$terminalProtectedCacheKeys=@($ProtectedCacheKeys)+@([string]$publication.cache_key)",
            source,
        )
        self.assertIn("-ProtectedCacheKeys $startupProtectedCacheKeys", source)
        self.assertIn("$startupProtectedCacheKeys+=([string]$probe.cache_key)", source)
        self.assertIn("-ProtectedCacheKeys $terminalProtectedCacheKeys", source)

    def test_local_family_builder_does_not_reserve_build_headroom_for_a_cache_hit(self) -> None:
        source = (PROJECT / "simion" / "run_analyzer_local_pa_family.ps1").read_text(
            encoding="utf-8"
        )
        self.assertLess(source.index("--action','probe'"), source.index("capacity_preflight"))
        self.assertIn(
            "$requiredBuildHeadroom=if($cacheDisposition-eq'hit'){0}",
            source,
        )
        self.assertIn(
            "$startupProtectedCacheKeys+=([string]$probe.cache_key)",
            source,
        )
        self.assertIn("-RequiredHeadroomBytes $requiredBuildHeadroom", source)
        self.assertIn("-ProtectedCacheKeys $startupProtectedCacheKeys", source)

    def fixture(self, root: Path) -> tuple[Path, Path, Path]:
        gem = root / "central.gem"
        gem.write_text(
            build_local_patch_gem(CONTRACT, "central_transport", 1.0),
            encoding="utf-8",
            newline="\n",
        )
        family = root / "global"
        family.mkdir()
        (family / "mrtof_analyzer.pa#").write_bytes(b"raw")
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        physical_ids = {
            identifier
            for identifiers in contract["simion"]["analyzer_spatial_convergence"]["response_voltage_groups"].values()
            for identifier in identifiers
        }
        for identifier in physical_ids:
            (family / f"mrtof_analyzer.pa{identifier}").write_bytes(f"basis-{identifier}".encode())
        executable = root / "simion.exe"
        executable.write_bytes(b"simion")
        return gem, family, executable

    def test_derives_complete_eight_group_recipe(self) -> None:
        with TemporaryDirectory() as directory:
            gem, family, executable = self.fixture(Path(directory))
            result = derive_local_pa_family_contract(
                CONTRACT, "central_transport", 1.0, gem, family, executable, "SIMION 2020",
            )
        self.assertEqual(len(result["response_recipes"]), 8)
        self.assertEqual(len(result["family_filenames"]), 18)
        self.assertEqual(result["response_recipes"][0]["physical_ids"], [2, 7])
        self.assertEqual(result["response_recipes"][-1]["local_id"], 8)
        self.assertEqual(
            result["response_recipes"][-1]["standalone_response_filename"],
            f"{result['family_prefix']}.response8.pa",
        )
        self.assertIn(f"{result['family_prefix']}.response8.pa", result["family_filenames"])
        self.assertEqual(result["patch_origin_project_mm"], [-29.0, -82.0, -105.0])
        self.assertEqual(result["coarse_raw_pa_path"], str((family / "mrtof_analyzer.pa#").resolve()))
        self.assertEqual(set(result["identity"]), set(CACHE_KEY_FIELDS))
        self.assertIn("coarse_parent_family", result["identity"]["geometry"])
        self.assertIn("dirichlet_boundary", result["identity"]["refine_policy"])
        self.assertEqual(result["identity"]["refine_policy"]["mode"], "installed_default")
        self.assertEqual(
            local_pa_family_filenames("mirror_turn_positive", 2),
            ("mrtof_analyzer_local_mirror_turn_positive.pa#",
             "mrtof_analyzer_local_mirror_turn_positive.pa0",
             "mrtof_analyzer_local_mirror_turn_positive.pa1",
             "mrtof_analyzer_local_mirror_turn_positive.pa2",
             "mrtof_analyzer_local_mirror_turn_positive.response1.pa",
             "mrtof_analyzer_local_mirror_turn_positive.response2.pa"),
        )

    def test_rejects_noncanonical_gem(self) -> None:
        with TemporaryDirectory() as directory:
            gem, family, executable = self.fixture(Path(directory))
            gem.write_text("wrong\n", encoding="utf-8")
            with self.assertRaises(CandidateContractError):
                derive_local_pa_family_contract(
                    CONTRACT, "central_transport", 1.0, gem, family, executable, "SIMION 2020",
                )


if __name__ == "__main__":
    unittest.main()
