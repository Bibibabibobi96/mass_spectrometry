from __future__ import annotations

import json
import hashlib
from pathlib import Path
import subprocess
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
REPOSITORY = PROJECT.parents[1]
CONTRACT = PROJECT / "config" / "simion_candidate_two_zone.json"
RUNNER = PROJECT / "simion" / "run_analyzer_local_workbench.ps1"
FAMILY_SUPPORT = PROJECT / "simion" / "analyzer_local_family_support.ps1"


class AnalyzerLocalPaFamilyTest(unittest.TestCase):
    def test_local_family_support_pins_frozen_publication_generation(self) -> None:
        source = FAMILY_SUPPORT.read_text(encoding="utf-8-sig")
        self.assertIn("function Resolve-AnalyzerLocalFrozenPublicationGeneration", source)
        self.assertEqual(
            source.count("Resolve-AnalyzerLocalFrozenPublicationGeneration -Family $Family -CacheRoot $CacheRoot"),
            3,
        )
        self.assertIn("$publication.generation_sha256", source)
        self.assertIn("$publication.generation_directory", source)
        self.assertIn("Frozen local PA-family publication generation is missing", source)
        self.assertNotIn("current_generation.json", source)

    def test_local_family_support_ignores_a_drifted_current_pointer(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cache_key = "A" * 64
            generation_sha256 = "B" * 64
            generation = root / "cache" / cache_key / "generations" / generation_sha256
            generation.mkdir(parents=True)
            raw = generation / "family.pa#"
            raw.write_bytes(b"frozen raw geometry")
            raw.chmod(0o444)
            manifest = generation / "cache_manifest.json"
            manifest.write_text(json.dumps({
                "schema_version": 1,
                "role": "simion_pa_family_cache",
                "cache_key": cache_key,
                "generation_sha256": generation_sha256,
                "files": [{
                    "name": raw.name,
                    "bytes": raw.stat().st_size,
                    "sha256": __import__("hashlib").sha256(raw.read_bytes()).hexdigest().upper(),
                }],
            }), encoding="utf-8")
            manifest.chmod(0o444)
            publication = root / "publication.json"
            publication.write_text(json.dumps({
                "cache_key": cache_key,
                "generation_sha256": generation_sha256,
                "generation_directory": str(generation),
            }), encoding="utf-8")
            (root / "cache" / cache_key / "current_generation.json").write_text(
                json.dumps({"cache_key": cache_key, "generation_sha256": "C" * 64}),
                encoding="utf-8",
            )
            script = root / "probe.ps1"
            script.write_text(
                "& {\n"
                f". '{FAMILY_SUPPORT}'\n"
                "$family=[pscustomobject]@{label='fixture';cache_key='" + cache_key + "';"
                "frozen_publication='" + str(publication) + "';"
                "generation_directory='';contract=[pscustomobject]@{family_prefix='family'}}\n"
                "$result=Resolve-AnalyzerLocalRawGeometry -Family $family -CacheRoot '" + str(root / "cache") + "'\n"
                "if($result.path -ne '" + str(raw) + "'){throw 'wrong frozen generation'}\n"
                "}\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(script)],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
                cwd=REPOSITORY,
                timeout=20,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_gui_workbench_publishes_a_semantic_iob_name(self) -> None:
        source = RUNNER.read_text(encoding="utf-8-sig")
        self.assertIn("mrtof_complete_3d_candidate_gui_review.iob", source)
        self.assertIn("$publishedIobCompanions", source)
        for suffix in (
            ".lua", ".mirror_cycle_counter.lua", ".operating_point.lua",
            ".voltage_map.lua", ".local_refinement.lua", ".fly2",
        ):
            self.assertIn(f'"$publishedIobBase{suffix}"', source)
        self.assertNotIn("Join-Path $solverDir 'mrtof_local_replacement.iob'", source)

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

    def test_local_family_runner_limits_heavy_stage_to_refining_lua_calls(self) -> None:
        source = (PROJECT / "simion" / "run_analyzer_local_pa_family.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "Enter-HostExecutionLease -Role SIMION -Stage analyzer_local_pa_prepare",
            source,
        )
        self.assertEqual(source.count("-Stage pa_refine"), 4)
        self.assertEqual(source.count("-Stage analyzer_local_pa_prepare"), 5)
        self.assertIn("-Stage analyzer_local_pa_postprocess", source)
        self.assertNotIn("-Stage pa_prepare", source)
        self.assertLess(
            source.index("compile_local_patch_gem"), source.index("-Stage pa_refine")
        )
        self.assertLess(
            source.index("-Stage analyzer_local_pa_postprocess"),
            source.index("capacity_terminal"),
        )

    def test_local_family_runner_requires_stable_private_bytes_before_publication(self) -> None:
        source = (PROJECT / "simion" / "run_analyzer_local_pa_family.ps1").read_text(
            encoding="utf-8"
        )
        stability = source.index("verify_private_family_stability")
        publication = source.index("publish_local_family_cache")
        self.assertLess(stability, publication)
        self.assertIn("--require-stable-inventory", source)
        self.assertIn("private_family_stability.json", source)
        self.assertIn("$manifestOutputs+=$stabilityReceiptPath", source)

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

    def test_local_workbench_uses_light_prepare_without_refine_or_flight(self) -> None:
        source = (PROJECT / "simion" / "run_analyzer_local_workbench.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "Enter-HostExecutionLease -Role SIMION -Stage prepare", source
        )
        self.assertNotIn("-Stage pa_prepare", source)
        self.assertNotIn("-Stage pa_refine", source)
        self.assertNotIn("-Stage flight", source)

    def test_local_workbench_parallelizes_five_regions_inside_one_prepare_lease(self) -> None:
        source = (PROJECT / "simion" / "run_analyzer_local_workbench.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("function Invoke-ParallelSimionStageBatch", source)
        self.assertIn("[Diagnostics.ProcessStartInfo]::new()", source)
        self.assertIn("$startInfo.CreateNoWindow=$true", source)
        self.assertIn("five_local_electrode_inventories", source)
        self.assertIn("five_local_basis_normalizations", source)
        self.assertIn("five_complete_local_operating_pa_lanes", source)
        self.assertIn("compose_local_operating_pa_lane.ps1", source)
        self.assertIn("parallel_batches_within_one_prepare_lease", source)
        self.assertIn("$record.Process.Kill($true)", source)
        self.assertNotIn("ForEach-Object -Parallel", source)

    def test_local_workbench_combines_cached_basis_without_refine_or_junction(self) -> None:
        source = (PROJECT / "simion" / "run_analyzer_local_workbench.ps1").read_text(
            encoding="utf-8"
        )
        lane = (PROJECT / "simion" / "compose_local_operating_pa_lane.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("compose_standalone_pa.lua", source)
        self.assertIn("export_detached_standalone_pa.lua", source)
        self.assertIn("detach_accelerator_operating_pa", source)
        self.assertIn("New-ShortPaCopy -Source $sourceAccelerator", source)
        self.assertIn("[IO.Path]::GetExtension($sourceAccelerator)-ieq'.pa'", source)
        self.assertIn("Copy-VerifiedRunInput -Source $sourceAccelerator -Destination $localAccelerator", source)
        self.assertNotIn("Copy-VerifiedRunInput -Source $sourceAccelerator -Destination (Join-Path $solverDir 'iob_input_accelerator.pa')", source)
        self.assertIn("basis_voltage_v=$basisVoltage", source)
        self.assertIn("measure_pa_basis_voltage.lua", source)
        self.assertIn("inspect_pa_electrode_ids.lua", source)
        self.assertIn("raw_geometry.bin", source)
        self.assertIn("response.bin", source)
        self.assertIn('(\"r{0}.bin\"-f($index+1))', lane)
        self.assertIn("Resolve-AnalyzerLocalRawGeometry", source)
        self.assertIn("five_current_immutable_family_measurements", source)
        self.assertIn("retainedGuiInputs", source)
        self.assertIn("retained GUI $($entry[0]) PA", source)
        self.assertIn("canonical analyser GEM projection", source)
        self.assertIn("local-refinement partition projection", source)
        self.assertIn("family_build_baseline_contracts", source)
        self.assertIn("family_baseline_equivalence", source)
        self.assertIn("$poseCode $frozenBaseline $posePath", source)
        self.assertIn("Current baseline changes the analyser GEM used to build the local PA families", source)
        self.assertIn("Current baseline changes the local PA partition used by the cached families", source)
        self.assertIn("standalone_response_filename", source)
        self.assertIn("$responsePaths+=New-ShortPaCopy", lane)
        self.assertIn("-Source ([string]$response.source)", lane)
        self.assertIn("combine_local_operating_replacements_without_refine", source)
        self.assertIn("Resolve-AnalyzerLocalStandaloneResponseSubset", source)
        self.assertNotIn("Resolve-AnalyzerLocalFamilyCacheGeneration -Family $family", source)
        self.assertIn("$requiredResponseIdsByFamily", source)
        self.assertIn("-VerificationAttempts 3", source)
        self.assertIn("verified prior-workbench standalone delta-response composition", source)
        self.assertIn("changed_local_voltage_indices", source)
        self.assertIn("$localVoltageDeltas", source)
        self.assertIn("$requiredResponseIdsByFamily", source)
        self.assertIn("Resolve-AnalyzerLocalStandaloneResponseSubset", source)
        self.assertNotIn("Resolve-AnalyzerLocalFamilyCacheGeneration -Family $family", source)
        self.assertIn("base_local_workbench_manifest", source)
        self.assertIn("$responseId=$responseIndex+1", source)
        self.assertIn("$changedLocalIndices.Count-eq0-and-not$familyIdentityChanged", source)
        self.assertIn("$changedFamilyIndices", source)
        self.assertIn("$baseFamilyCacheKeys", source)
        self.assertIn("$localFamilyResponsesRequired=($null-eq$baseLocalWorkbench-or$changedLocalIndices.Count-gt0-or$changedFamilyIndices.Count-gt0)", source)
        self.assertIn("family-identity-aware absolute replacement", source)
        self.assertIn("changed_local_family_indices", source)
        self.assertIn("changed_local_family_labels", source)
        self.assertIn("if($localFamilyResponsesRequired)", source)
        self.assertIn("$capacityProtectedPaths", source)
        self.assertIn("$largestCompositionWorkingSet", source)
        self.assertIn("-MinimumFreeGiB ([double]([int64](500GB)+$requiredBytes+$transientBytes)/1GB)", source)
        self.assertIn("@($families.generation_directory)", source)
        self.assertIn("Assert-ManifestOutputIdentity", source)
        self.assertIn("Operating run declares a missing base local workbench manifest", source)
        self.assertIn("New-ShortPaCopy -Source $basePaSource", source)
        self.assertIn("New-ShortPaCopy -Source $sourceAnalyzer", source)
        self.assertIn("iob_input_analyzer.pa", source)
        self.assertIn("iob_input_local_$_.pa", source)
        self.assertIn("$iobPaths=@($paths)", source)
        self.assertNotIn("$iobPaths+=Copy-VerifiedRunInput", source)
        self.assertIn("global_analyzer_pa=Join-Path $artifactSimionDir 'iob_input_analyzer.pa'", source)
        self.assertIn("local_operating_pas=@($localNames", source)
        self.assertIn("accelerator_pa=Join-Path $artifactSimionDir 'iob_input_accelerator.pa'", source)
        self.assertIn("detector_pa=Join-Path $artifactSimionDir 'iob_input_detector.pa'", source)
        self.assertIn("Convert-OperatingPointFieldGateContract", source)
        self.assertIn("runtime_fast_adjust_accelerator_enable", source)
        self.assertIn("runtime_accelerator_field_gate_enable", source)
        self.assertIn("$text.Replace($legacyFieldName,$currentFieldName)", source)
        self.assertIn("operating_point_field_gate_projection", source)
        self.assertIn("Remove-IobSeedPlaceholderCompanions -Directory $solverDir -Count 10", source)
        self.assertIn("iob_seed_placeholder_cleanup=$seedPlaceholderCleanup", source)
        self.assertIn("local_family_contracts_frozen", source)
        self.assertIn("local_family_cache_identities_frozen", source)
        self.assertIn("local_family_cache_publications_frozen", source)
        self.assertIn("$frozenEvidenceOutputs", source)
        self.assertNotIn("$requiredBytes*=2", source)
        self.assertNotIn("global_analyzer_pa0=$sourceAnalyzer", source)
        self.assertEqual(source.count("-ProtectedCacheKeys @($families.cache_key)"), 2)
        self.assertNotIn("[IO.Path]::ChangeExtension($sourceAnalyzer,'.pa2')", source)
        self.assertNotIn("measure_global_basis_voltage", source)
        self.assertNotIn("$temporaryBasisDir", source)
        self.assertIn("short_pa_path_support.ps1", source)
        self.assertIn("$responseSpecifications", source)
        self.assertIn(
            '$arguments+=(\"{0},{1}\"-f$responsePaths[$index],$coefficient)', lane
        )
        self.assertIn("$coefficient=$numerator/$basisVoltage", source)
        self.assertIn("if($requiresAbsoluteResponses-and$voltageIndex-eq 0){$coefficient-=1.0}", source)
        self.assertNotIn("if($null-eq$baseLocalWorkbench-and$voltageIndex-eq 0){$coefficient-=1.0}", source)
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
        self.assertIn("compose_standalone_pa.lua", source)
        self.assertIn("frozen_global_standalone_plus_local_response_deltas__no_refine", source)
        self.assertIn("$changedIndices.Count-eq 0", source)
        self.assertIn("Resolve-AnalyzerLocalStandaloneResponseSubset", source)
        self.assertNotIn(
            "Resolve-AnalyzerLocalFamilyCacheGeneration -Family $family", source
        )
        self.assertIn("build_local_refinement_iob.lua", source)
        self.assertIn("flight_scope='complete_three_dimensional_static_return'", source)
        self.assertNotIn("ContinueMainDrift", source)
        self.assertNotIn("ConstrainXSymmetryPlane", source)
        self.assertNotIn("post_switch_global_fallback=true", source)
        self.assertIn("$config.parameters.local_extraction_field_handoff=$null", source)
        self.assertIn("standalone_response_filename", source)
        self.assertIn("$privateBasisPaths+=New-ShortPaCopy -Source $responseSource", source)
        self.assertIn("basis_projection='standalone_linear_response_composition'", source)
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
        self.assertIn("verified_frozen_workbench_global_standalone_plus_local_response_composition", source)
        self.assertIn("if(-not$reuseFrozenWorkbenchAnalyzer){", source)
        self.assertIn("Remove-ShortPaCopyDirectory -Path $basisLinkDir", source)
        self.assertIn("Remove-TemporarySolverDirectory -Path $temporarySolverDir", source)
        self.assertNotIn("$requiredBytes+=3*$baseOperatingBytes", source)
        self.assertNotIn("-ItemType Junction", source)
        self.assertIn("$localCacheSentinelHashes", source)
        self.assertIn("changed immutable local PA-family bookkeeping", source)
        self.assertIn("$localCacheSentinelHashes", source)
        self.assertIn("foreach($changedIndex in $changedIndices)", source)
        self.assertIn("$responseId=5+$changedIndex", source)
        self.assertIn("Resolve-AnalyzerLocalStandaloneResponseSubset", source)
        self.assertIn("$requiredResponseIds", source)
        self.assertNotIn(
            "Resolve-AnalyzerLocalFamilyCacheGeneration -Family $family", source
        )
        self.assertNotIn("--materialize-manifest", source)
        self.assertNotIn("$basisFamilyDir", source)
        self.assertIn("$startupProtectedCacheKeys=if($null-eq$localWorkbenchRun)", source)
        self.assertIn("$protectedCacheKeys=if($null-eq$localWorkbenchRun)", source)
        self.assertIn("$protectedCacheKeys+=$operatingCacheKey", source)

    def test_iob_builders_accept_verified_standalone_read_only_pa_inputs(self) -> None:
        three = (PROJECT / "simion" / "build_three_component_iob.lua").read_text(
            encoding="utf-8"
        )
        local = (PROJECT / "simion" / "build_local_refinement_iob.lua").read_text(
            encoding="utf-8"
        )
        inspector = (PROJECT / "simion" / "inspect_local_refinement_iob.lua").read_text(
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
        self.assertNotIn("pulsed_mixed_bindings", local)
        self.assertIn("iob_input_accelerator%.pa$", local)
        for index, token in enumerate((
            "iob_input_analyzer%.pa$",
            "iob_input_local_1%.pa$",
            "iob_input_local_2%.pa$",
            "iob_input_local_3%.pa$",
            "iob_input_local_4%.pa$",
            "iob_input_local_5%.pa$",
            "iob_input_accelerator%.pa$",
            "iob_input_detector%.pa$",
        ), start=1):
            self.assertIn(token, inspector, f"inspector role {index}")
        self.assertNotIn("mrtof_analyzer%.pa0$", inspector)
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

    def test_local_family_runner_requires_prepared_standalone_receipt_before_lease(self) -> None:
        source = (PROJECT / "simion" / "run_analyzer_local_pa_family.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("analyzer_prepared_source_support.ps1", source)
        self.assertIn("PreparedSourceReceiptPath is required", source)
        self.assertIn("New-PreparedAnalyzerSourceBinding", source)
        self.assertLess(
            source.index("Get-PreparedAnalyzerSourceReceipt -Path"),
            source.index("Enter-HostExecutionLease -Role SIMION"),
        )

    def test_local_family_runner_reserves_two_complete_published_families(self) -> None:
        source = (PROJECT / "simion" / "run_analyzer_local_pa_family.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("$refineArrayCount-ne10-or$estimatedRefineFamilyBytes%$refineArrayCount-ne0", source)
        self.assertIn("$filenames.Count-ne18", source)
        self.assertIn("$estimatedPublishedFamilyBytes", source)
        self.assertIn("2*$estimatedPublishedFamilyBytes", source)
        self.assertNotIn("2*$estimatedRefineFamilyBytes", source)

    def test_local_family_runner_stages_and_rechecks_prepared_standalone_sources(self) -> None:
        source = (PROJECT / "simion" / "run_analyzer_local_pa_family.ps1").read_text(
            encoding="utf-8"
        )
        support = (PROJECT / "simion" / "analyzer_prepared_source_support.ps1").read_text(encoding="utf-8")
        self.assertIn("analyzer_prepared_source_support.ps1", source)
        self.assertIn("function New-PreparedAnalyzerSourceBinding", support)
        self.assertIn("New-ShortPaCopy -Source $source", support)
        self.assertIn("Prepared analyzer copy identity differs", support)
        self.assertLess(source.index("derive_family_contract"), source.index("stage_prepared_analyzer_source"))
        self.assertLess(source.index("verify_prepared_analyzer_consumer_copies"), source.index("publish_local_family_cache"))
        self.assertIn("2*$estimatedPublishedFamilyBytes", source)
        self.assertIn("$sourceStagingBytes+2*$estimatedPublishedFamilyBytes", source)
        self.assertIn("simion_pa_links_mrtof_prepared_", source)
        self.assertIn("if($cacheDisposition-ne'hit'){", source)
        self.assertIn("$requiredBuildHeadroom=if($cacheDisposition-eq'hit'){0}", source)
        self.assertLess(
            source.index("stage_prepared_analyzer_source"),
            source.index("Enter-HostExecutionLease -Role SIMION"),
        )
        self.assertLess(
            source.index("Enter-HostExecutionLease -Role SIMION"),
            source.index("Invoke-SimionStage -Stage 'compile_local_patch_gem'"),
        )

    def test_source_staging_capacity_sums_object_member_bytes(self) -> None:
        completed = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", "$inventory=[ordered]@{members=@([ordered]@{bytes=7},[ordered]@{bytes=11})}; [int64]$sum=0; foreach($member in @($inventory.members)){$sum+=[int64]$member['bytes']}; $sum"],
            text=True, encoding="utf-8", errors="replace", capture_output=True, check=False,
            cwd=REPOSITORY, timeout=20,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "18")

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
            result["identity"]["builder_identity"]["private_family_stability_policy"],
            "two_consecutive_full_byte_inventories_before_cache_publication_v1",
        )
        self.assertEqual(
            local_pa_family_filenames("mirror_turn_positive", 2),
            ("mrtof_analyzer_local_mirror_turn_positive.pa#",
             "mrtof_analyzer_local_mirror_turn_positive.pa0",
             "mrtof_analyzer_local_mirror_turn_positive.pa1",
             "mrtof_analyzer_local_mirror_turn_positive.pa2",
             "mrtof_analyzer_local_mirror_turn_positive.response1.pa",
             "mrtof_analyzer_local_mirror_turn_positive.response2.pa"),
        )

    def test_prepared_receipt_probe_is_path_independent_and_payload_free(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            gem, family, executable = self.fixture(root)
            ids = sorted(int(path.name.removeprefix("mrtof_analyzer.pa")) for path in family.glob("mrtof_analyzer.pa[0-9]*"))
            def record(path: Path, physical_id: int | None = None) -> dict[str, object]:
                value = {"name": path.name, "bytes": path.stat().st_size,
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper()}
                if physical_id is not None:
                    value["physical_id"] = physical_id
                    value["name"] = f"prepared_response_{physical_id}.pa"
                return value
            prepared = root / "immutable-prepared"; raw = root / "immutable-raw"
            receipt = {
                "role": "mrtof_reviewed_analyzer_source_cache_receipt", "status": "success",
                "prepared_standalone_generation": {
                    "cache_key": "A" * 64, "generation_sha256": "B" * 64,
                    "generation_directory": str(prepared), "inventory": [record(family / f"mrtof_analyzer.pa{i}", i) for i in ids],
                    "responses_by_physical_id": {str(i): record(family / f"mrtof_analyzer.pa{i}", i) for i in ids},
                },
                "raw_geometry_generation": {
                    "cache_key": "C" * 64, "generation_sha256": "D" * 64,
                    "generation_directory": str(raw), "inventory": [record(family / "mrtof_analyzer.pa#")],
                    "raw_geometry": record(family / "mrtof_analyzer.pa#"),
                },
            }
            receipt_path = root / "receipt.json"; receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            result = derive_local_pa_family_contract(CONTRACT, "central_transport", 1.0, gem, family, executable, "SIMION 2020", receipt_path)
            self.assertEqual(result["identity"]["geometry"]["prepared_source"]["prepared_standalone_generation"]["cache_key"], "A" * 64)
            # No generation payload exists: successful derivation proves the
            # cache probe consumes receipt metadata only.
            self.assertFalse(prepared.exists())
            self.assertFalse(raw.exists())

    def test_bound_prepared_copies_preserve_probe_identity(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            gem, family, executable = self.fixture(root)
            ids = sorted(int(path.name.removeprefix("mrtof_analyzer.pa")) for path in family.glob("mrtof_analyzer.pa[0-9]*"))
            prepared, raw, copies = root / "prepared", root / "raw", root / "copies"
            prepared.mkdir(); raw.mkdir(); copies.mkdir()
            def response(i: int) -> dict[str, object]:
                payload = f"standalone-{i}".encode(); name = f"response_{i}.pa"
                (prepared / name).write_bytes(payload); (copies / name).write_bytes(payload)
                return {"physical_id": i, "name": name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest().upper()}
            raw_payload = b"raw"; (raw / "mrtof_analyzer.pa#").write_bytes(raw_payload); (copies / "mrtof_analyzer.pa#").write_bytes(raw_payload)
            responses = {str(i): response(i) for i in ids}
            receipt = {"role": "mrtof_reviewed_analyzer_source_cache_receipt", "status": "success",
                "prepared_standalone_generation": {"cache_key": "A" * 64, "generation_sha256": "B" * 64, "generation_directory": str(prepared), "inventory": list(responses.values()), "responses_by_physical_id": responses},
                "raw_geometry_generation": {"cache_key": "C" * 64, "generation_sha256": "D" * 64, "generation_directory": str(raw), "inventory": [{"name": "mrtof_analyzer.pa#", "bytes": 3, "sha256": hashlib.sha256(raw_payload).hexdigest().upper()}], "raw_geometry": {"name": "mrtof_analyzer.pa#", "bytes": 3, "sha256": hashlib.sha256(raw_payload).hexdigest().upper()}}}
            receipt_path = root / "receipt.json"; receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            binding = {"role": "mrtof_prepared_analyzer_source_binding", "status": "success",
                "prepared_standalone_generation": {"cache_key": "A" * 64, "generation_sha256": "B" * 64},
                "raw_geometry_generation": {"cache_key": "C" * 64, "generation_sha256": "D" * 64},
                "responses_by_physical_id": {str(i): {**responses[str(i)], "binding_path": str((copies / responses[str(i)]["name"]).resolve())} for i in ids},
                "raw_geometry": {**receipt["raw_geometry_generation"]["raw_geometry"], "binding_path": str((copies / "mrtof_analyzer.pa#").resolve())}}
            binding_path = root / "binding.json"; binding_path.write_text(json.dumps(binding), encoding="utf-8")
            initial = derive_local_pa_family_contract(CONTRACT, "central_transport", 1.0, gem, family, executable, "SIMION 2020", receipt_path)
            bound = derive_local_pa_family_contract(CONTRACT, "central_transport", 1.0, gem, family, executable, "SIMION 2020", receipt_path, binding_path)
            self.assertEqual(initial["identity"], bound["identity"])
            self.assertEqual(Path(bound["coarse_raw_pa_path"]), copies / "mrtof_analyzer.pa#")

    def test_consumer_runner_has_no_native_or_per_region_staging_path(self) -> None:
        source = (PROJECT / "simion" / "run_analyzer_local_pa_family.ps1").read_text(encoding="utf-8-sig")
        support = (PROJECT / "simion" / "analyzer_prepared_source_support.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("Get-PreparedAnalyzerSourceReceipt", support)
        self.assertIn("New-PreparedAnalyzerSourceBinding", support)
        self.assertIn("Assert-PreparedAnalyzerSourceBinding", support)
        self.assertIn("-GuardDestinationReadOnly", support)
        self.assertNotIn("Assert-ReviewedAnalyzerFamilyIdentity", source)
        self.assertNotIn("New-ReviewedAnalyzerSourceStaging", source)
        self.assertNotIn("mrtof_analyzer.pa1..PA20", source)
        self.assertLess(source.index("--action','probe'"), source.index("capacity_preflight"))
        self.assertIn("if($cacheDisposition-eq'hit'){0}", source)

    def test_batch_keeps_one_guarded_binding_in_the_calling_powershell_process(self) -> None:
        batch = (PROJECT / "simion" / "run_analyzer_local_family_batch.ps1").read_text(encoding="utf-8-sig")
        planner = (PROJECT / "analysis" / "analyzer_local_family_batch_plan.py").read_text(encoding="utf-8-sig")
        runner = (PROJECT / "simion" / "run_analyzer_local_pa_family.ps1").read_text(encoding="utf-8-sig")
        support = (PROJECT / "simion" / "analyzer_prepared_source_support.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("New-PreparedAnalyzerSourceBinding", batch)
        self.assertIn("Assert-PreparedAnalyzerSourceBinding", batch)
        self.assertIn("-PreparedSourceBindingPath $bindingPath", batch)
        self.assertIn("if($misses.Count-eq0)", batch)
        self.assertIn("-RequiredHeadroomBytes $copyBytes", batch)
        self.assertIn("mrtof_prepared_analyzer_binding_", batch)
        self.assertIn("prepared_standalone_generation.cache_key", batch)
        self.assertIn("raw_geometry_generation.cache_key", batch)
        self.assertIn("-ProtectedCacheKeys $protected", batch)
        self.assertIn("PreparedSourceBindingPath", runner)
        self.assertIn("Get-ShortPaCopyIdentity -Path $path", support)
        self.assertNotIn("Start-Process", batch)
        self.assertIn("Get-BatchChildRunId", batch)
        self.assertIn("unverified_hit_candidate", planner)
        self.assertNotIn("probe_pa_family_cache", planner)
        self.assertLess(runner.index("Assert-PreparedAnalyzerGeometrySource"), runner.index("Copy-VerifiedRunInput"))
        self.assertNotIn("verify_run_manifest.py') $geometryManifest", runner)

    def test_prepared_binding_cleans_prior_copies_when_later_copy_fails(self) -> None:
        support = PROJECT / "simion" / "analyzer_prepared_source_support.ps1"
        common = PROJECT.parents[1] / "common"
        short_support = common / "simion" / "short_pa_path_support.ps1"
        artifact_support = common / "contracts" / "run_artifact_support.ps1"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            sources = root / "sources"; sources.mkdir()
            records = []
            for name, payload, physical_id in (
                ("mrtof_analyzer.pa#", b"raw", None),
                ("prepared_response_2.pa", b"two", 2),
                ("prepared_response_3.pa", b"three", 3),
            ):
                path = sources / name; path.write_bytes(payload)
                records.append({
                    "kind": "raw" if physical_id is None else "response",
                    "physical_id": physical_id,
                    "name": name,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest().upper(),
                    "source_directory": str(sources),
                })
            records[-1]["sha256"] = "0" * 64
            receipt_path = root / "receipt.json"
            receipt_path.write_text(json.dumps({"members": records}), encoding="utf-8")
            copy_dir = Path(subprocess.check_output(
                ["pwsh", "-NoProfile", "-Command", "[IO.Path]::GetTempPath()"],
                text=True,
                cwd=REPOSITORY,
                timeout=20,
            ).strip()) / "simion_pa_links_mrtof_prepared_fixture_copy_failure"
            binding_path = root / "binding.json"
            command = (
                f". '{artifact_support}'; . '{short_support}'; . '{support}'; "
                f"$r=Get-Content -Raw '{receipt_path}'|ConvertFrom-Json -Depth 20; "
                f"try{{New-PreparedAnalyzerSourceBinding -Receipt $r -Directory '{copy_dir}' -Output '{binding_path}';exit 9}}"
                "catch{if((Test-Path -LiteralPath '" + str(copy_dir) + "')-or(Test-Path -LiteralPath '" + str(binding_path) + "')){exit 8};exit 0}"
            )
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", command], text=True,
                capture_output=True, encoding="utf-8", errors="replace",
                cwd=REPOSITORY, timeout=20,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual([path.read_bytes() for path in sorted(sources.iterdir())], [b"raw", b"two", b"three"])

    def test_external_binding_fails_without_the_creator_process_registry(self) -> None:
        support = PROJECT / "simion" / "analyzer_prepared_source_support.ps1"
        short_support = PROJECT.parents[1] / "common" / "simion" / "short_pa_path_support.ps1"
        with TemporaryDirectory() as directory:
            root = Path(directory); copies = root / "copies"; copies.mkdir()
            records, responses = [], {}
            for index, physical_id in enumerate((2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 16, 17), start=1):
                path = copies / f"response_{physical_id}.pa"; payload = bytes([index]); path.write_bytes(payload)
                record = {"name": path.name, "bytes": 1, "sha256": hashlib.sha256(payload).hexdigest().upper(), "binding_path": str(path)}
                responses[str(physical_id)] = record
                records.append({"kind": "response", "physical_id": physical_id, **record, "source_directory": str(copies)})
            raw = copies / "mrtof_analyzer.pa#"; raw.write_bytes(b"r")
            raw_record = {"name": raw.name, "bytes": 1, "sha256": hashlib.sha256(b"r").hexdigest().upper(), "binding_path": str(raw)}
            records.insert(0, {"kind": "raw", "physical_id": None, **raw_record, "source_directory": str(copies)})
            receipt = {"members": records}
            binding = {"role": "mrtof_prepared_analyzer_source_binding", "status": "success", "responses_by_physical_id": responses, "raw_geometry": raw_record}
            receipt_path = root / "receipt.json"; binding_path = root / "binding.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8"); binding_path.write_text(json.dumps(binding), encoding="utf-8")
            command = (
                f". '{short_support}'; . '{support}'; "
                f"$r=Get-Content -Raw '{receipt_path}'|ConvertFrom-Json -Depth 20; "
                f"try{{Assert-PreparedAnalyzerSourceBinding -Receipt $r -BindingPath '{binding_path}';exit 9}}catch{{if($_.Exception.Message -match 'not registered'){{exit 0}};throw}}"
            )
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", command], text=True,
                capture_output=True, encoding="utf-8", errors="replace",
                cwd=REPOSITORY, timeout=20,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

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
