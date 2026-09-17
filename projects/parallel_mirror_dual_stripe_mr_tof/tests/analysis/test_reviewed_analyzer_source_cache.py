from __future__ import annotations

import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.file_identity import canonical_json_sha256, file_sha256
from common.simion.pa_family_cache import PAFamilyCacheError
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.reviewed_analyzer_source_cache import (
    NATIVE_FILENAMES,
    PHYSICAL_RESPONSE_IDS,
    RESPONSE_FILENAMES,
    export_plan,
    inspect_reviewed_sources,
    publish_prepared,
    receipt_from_hit,
    stage_native_source,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis import reviewed_analyzer_source_cache as adapter


REPOSITORY = Path(__file__).resolve().parents[4]


def _record(path: Path) -> dict[str, object]:
    return {"path": str(path), "exists": True, "bytes": path.stat().st_size, "sha256": file_sha256(path)}


class ReviewedAnalyzerSourceCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.provider = self._make_run("r41", b"provider-pa0")
        self.reviewed = self._make_run("r51", b"reviewed-pa0", create_payload=False)
        self.simion = self.root / "simion.exe"
        self.simion.write_bytes(b"synthetic-simion-2020")
        self.cache = self.root / "cache"
        self.inspection = inspect_reviewed_sources(
            self.provider, self.reviewed, self.simion, "SIMION 2020", self.cache
        )
        self.inspection_path = self.root / "inspection.json"
        self.inspection_path.write_text(json.dumps(self.inspection), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _make_run(self, run_id: str, pa0: bytes, *, create_payload: bool = True) -> Path:
        run = self.root / run_id
        simion = run / "simion"
        inputs = run / "inputs"
        simion.mkdir(parents=True)
        inputs.mkdir()
        gem = simion / "mrtof_analyzer.gem"
        raw = simion / "mrtof_analyzer.pa#"
        contract = inputs / "simion_candidate_two_zone.json"
        gem.write_bytes(b"same-gem")
        raw.write_bytes(b"same-raw")
        contract.write_text(json.dumps({"simion": {"component_mesh_mm_per_gu": {"analyzer": [1.0, 1.0, 1.0]}}}), encoding="utf-8")
        pa0_path = simion / "mrtof_analyzer.pa0"
        if create_payload:
            pa0_path.write_bytes(pa0)
            for identifier in range(1, 21):
                (simion / f"mrtof_analyzer.pa{identifier}").write_bytes(
                    f"basis-{identifier}".encode()
                )
        basis = [
            {
                "name": f"mrtof_analyzer.pa{identifier}",
                "bytes": len(f"basis-{identifier}".encode()),
                "sha256": file_sha256(self.provider / "simion" / f"mrtof_analyzer.pa{identifier}")
                if hasattr(self, "provider") else __import__("hashlib").sha256(f"basis-{identifier}".encode()).hexdigest().upper(),
            }
            for identifier in range(1, 21)
        ]
        pa0_record = {
            "name": "mrtof_analyzer.pa0", "bytes": len(pa0),
            "sha256": __import__("hashlib").sha256(pa0).hexdigest().upper(),
        }
        review = {
            "schema_version": 1, "project_id": "parallel_mirror_dual_stripe_mr_tof",
            "status": "prototype_geometry_review_only",
            "geometry": {"resolved_geometry_sha256": "A" * 64},
            "instances": [{"role": "analyzer", "origin_mm": [-90.0, -162.0, -360.0],
                           "physical_electrode_ids": [*range(1, 19), 20],
                           "pa0": pa0_record, "basis_arrays": basis}],
        }
        review_path = simion / "three_component_geometry_review.json"
        review_path.write_text(json.dumps(review), encoding="utf-8")
        manifest = {
            "schema_version": 2, "role": "simulation_run_manifest", "run_id": run_id,
            "project": "parallel_mirror_dual_stripe_mr_tof",
            "mode": "three_component_candidate_iob_assembly", "status": "success",
            "inputs": {
                "analyzer_gem": _record(gem), "analyzer_raw_pa": _record(raw),
                "analyzer_pa0": {"path": str(pa0_path), **pa0_record},
                "candidate_contract": _record(contract),
            },
            "outputs": [_record(review_path)],
        }
        (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return run

    def _stage_and_outputs(self) -> tuple[Path, Path]:
        staging, outputs = self.root / "staging", self.root / "outputs"
        staging.mkdir(); outputs.mkdir()
        staged = stage_native_source(self.inspection_path, staging)
        self.assertEqual(len(staged["inventory"]), 22)
        plan = export_plan(self.inspection_path, staging, outputs)
        self.assertEqual([item["physical_id"] for item in plan["exports"]], list(PHYSICAL_RESPONSE_IDS))
        for item in plan["exports"]:
            identifier = item["physical_id"]
            output = outputs / RESPONSE_FILENAMES[identifier]
            output.write_bytes(f"standalone-{identifier}".encode())
            receipt = output.with_name(output.name + ".boundary_mask_restoration.json")
            receipt.write_text(json.dumps({"status": "pass", "output_basename": output.name}), encoding="utf-8")
        return staging, outputs

    def _caller_cleanup(self, path: Path) -> None:
        repository = Path(__file__).resolve().parents[4]
        support = repository / "common" / "parallel_gate_support.ps1"
        command = (
            f". '{support}'; Remove-GateTemporaryDirectory -Path '{path}' "
            "-ExpectedNamePrefix 'mrtof_reviewed_analyzer_native_'"
        )
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", command],
            capture_output=True, encoding="utf-8", errors="replace", check=False,
            cwd=REPOSITORY, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_stage_rejects_missing_provider_member(self) -> None:
        (self.provider / "simion" / "mrtof_analyzer.pa20").unlink()
        staging = self.root / "mrtof_reviewed_analyzer_native_missing"
        staging.mkdir()
        try:
            with self.assertRaisesRegex(PAFamilyCacheError, "cannot stage reviewed provider member"):
                stage_native_source(self.inspection_path, staging)
        finally:
            self._caller_cleanup(staging)
        self.assertFalse(staging.exists())

    def test_stage_rejects_provider_sha_mismatch(self) -> None:
        victim = self.provider / "simion" / "mrtof_analyzer.pa8"
        victim.write_bytes(b"X" * victim.stat().st_size)
        staging = self.root / "mrtof_reviewed_analyzer_native_sha"
        staging.mkdir()
        try:
            with self.assertRaisesRegex(PAFamilyCacheError, "differs from its own geometry review"):
                stage_native_source(self.inspection_path, staging)
        finally:
            self._caller_cleanup(staging)
        self.assertFalse(staging.exists())

    def test_third_copy_failure_is_cleaned_by_caller_without_mutating_provider(self) -> None:
        provider_files = [self.provider / "simion" / name for name in NATIVE_FILENAMES]
        before = [(path.name, path.stat().st_size, file_sha256(path)) for path in provider_files]
        staging = self.root / "mrtof_reviewed_analyzer_native_injected"
        staging.mkdir()
        original = adapter.copy_verified_file
        calls = 0

        def fail_third(source: Path, destination: Path) -> dict[str, object]:
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("injected third-copy failure")
            return original(source, destination)

        try:
            with patch.object(adapter, "copy_verified_file", side_effect=fail_third):
                with self.assertRaisesRegex(PAFamilyCacheError, "cannot stage reviewed provider member"):
                    stage_native_source(self.inspection_path, staging)
        finally:
            self._caller_cleanup(staging)
        after = [(path.name, path.stat().st_size, file_sha256(path)) for path in provider_files]
        self.assertFalse(staging.exists())
        self.assertEqual(after, before)

    def test_inspection_excludes_pa0_and_builds_fourteen_one_hot_members(self) -> None:
        self.assertFalse(self.inspection["evidence"]["compatibility"]["pa0_equal"])
        self.assertEqual(self.inspection["evidence"]["compatibility"]["explicitly_excluded"], ["analyzer_pa0"])
        self.assertEqual(len(self.inspection["source_inventory"]), len(NATIVE_FILENAMES))
        members = self.inspection["operating_identity"]["members"]
        self.assertEqual(len(members), 14)
        for member in members:
            table = {item["electrode_id"]: item["voltage_v"] for item in member["electrode_voltages_v"]}
            self.assertEqual(len(table), 19)
            self.assertNotIn(19, table)
            self.assertEqual(sum(table.values()), 1.0)

    def test_publish_rejects_equal_length_staging_tamper_before_either_generation(self) -> None:
        staging, outputs = self._stage_and_outputs()
        victim = staging / "mrtof_analyzer.pa9"
        victim.write_bytes(b"X" * victim.stat().st_size)
        with self.assertRaisesRegex(PAFamilyCacheError, "22-member source inventory"):
            publish_prepared(self.cache, self.inspection_path, staging, outputs)
        self.assertFalse((self.cache / self.inspection["prepared_cache_key"]).exists())
        self.assertFalse((self.cache / self.inspection["raw_cache_key"]).exists())

    def test_publish_receipt_freezes_raw_and_physical_response_inventories(self) -> None:
        staging, outputs = self._stage_and_outputs()
        receipt = publish_prepared(self.cache, self.inspection_path, staging, outputs)
        self.assertFalse(receipt["native_generation_published"])
        self.assertEqual(set(receipt["prepared_standalone_generation"]["responses_by_physical_id"]), {str(value) for value in PHYSICAL_RESPONSE_IDS})
        self.assertEqual(receipt["raw_geometry_generation"]["raw_geometry"]["name"], "mrtof_analyzer.pa#")
        self.assertEqual(len(receipt["prepared_standalone_generation"]["export_receipts"]), 14)

    def test_hit_receipt_uses_pinned_generation_and_never_follows_new_current(self) -> None:
        staging, outputs = self._stage_and_outputs()
        publish_prepared(self.cache, self.inspection_path, staging, outputs)
        pinned = inspect_reviewed_sources(self.provider, self.reviewed, self.simion, "SIMION 2020", self.cache)
        prepared_pin = pinned["cache_probe"]["prepared"]
        generation_a = Path(prepared_pin["generation_directory"])
        generation_b_stage = self.root / "generation-b"
        shutil.copytree(generation_a, generation_b_stage)
        payload = generation_b_stage / RESPONSE_FILENAMES[2]
        payload.chmod(payload.stat().st_mode | stat.S_IWUSR)
        payload.write_bytes(b"valid-alternate-content")
        manifest_path = generation_b_stage / "cache_manifest.json"
        manifest_path.chmod(manifest_path.stat().st_mode | stat.S_IWUSR)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for record in manifest["files"]:
            if record["name"] == payload.name:
                record.update(bytes=payload.stat().st_size, sha256=file_sha256(payload))
        generation_b = canonical_json_sha256({"cache_key": manifest["cache_key"], "files": manifest["files"]})
        manifest["generation_sha256"] = generation_b
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        destination = generation_a.parent / generation_b
        generation_b_stage.replace(destination)
        pointer = self.cache / pinned["prepared_cache_key"] / "current_generation.json"
        pointer.write_text(json.dumps({"cache_key": pinned["prepared_cache_key"], "generation_sha256": generation_b}), encoding="utf-8")
        receipt = receipt_from_hit(self.cache, pinned)
        self.assertEqual(receipt["prepared_standalone_generation"]["generation_directory"], str(generation_a.resolve()))
        corrupt = generation_a / RESPONSE_FILENAMES[2]
        corrupt.chmod(corrupt.stat().st_mode | stat.S_IWUSR)
        corrupt.write_bytes(b"corrupt-a")
        with self.assertRaises(PAFamilyCacheError):
            receipt_from_hit(self.cache, pinned)

    def test_runner_parses_and_parallel_gate_cleanup_function_is_callable(self) -> None:
        repository = Path(__file__).resolve().parents[4]
        runner = repository / "projects" / "parallel_mirror_dual_stripe_mr_tof" / "simion" / "run_prepare_reviewed_analyzer_source.ps1"
        support = repository / "common" / "parallel_gate_support.ps1"
        scratch = self.root / "mrtof_reviewed_analyzer_native_fixture"
        scratch.mkdir()
        command = (
            f"$null=[scriptblock]::Create((Get-Content -Raw -LiteralPath '{runner}')); "
            f". '{support}'; Remove-GateTemporaryDirectory -Path '{scratch}' "
            "-ExpectedNamePrefix 'mrtof_reviewed_analyzer_native_'; "
            "if(Test-Path -LiteralPath '" + str(scratch) + "'){exit 7}"
        )
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", command], capture_output=True,
            encoding="utf-8", errors="replace", check=False,
            cwd=REPOSITORY, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_runner_retention_inputs_are_run_local_files_and_apply_successfully(self) -> None:
        repository = Path(__file__).resolve().parents[4]
        runner = repository / "projects" / "parallel_mirror_dual_stripe_mr_tof" / "simion" / "run_prepare_reviewed_analyzer_source.ps1"
        support = repository / "common" / "contracts" / "run_artifact_support.ps1"
        text = runner.read_text(encoding="utf-8")
        self.assertNotIn("provider_run=$provider", text)
        self.assertNotIn("reviewed_run=$reviewed", text)
        for key in (
            "provider_run_manifest", "provider_geometry_review",
            "reviewed_run_manifest", "reviewed_geometry_review",
        ):
            self.assertIn(key, text)
        artifact_root = self.root / "retention-fixture"
        source_files = [
            self.provider / "run_manifest.json",
            self.provider / "simion" / "three_component_geometry_review.json",
            self.reviewed / "run_manifest.json",
            self.reviewed / "simion" / "three_component_geometry_review.json",
        ]
        quoted_sources = ",".join(f"'{path}'" for path in source_files)
        command = (
            f". '{support}'; "
            f"$p=New-RunPackage -Python '{sys.executable}' -RepoRoot '{repository}' "
            f"-ArtifactRoot '{artifact_root}' -RunId '20260917_000000__test__python__retention-shape' -Project 'fixture' "
            "-Mode 'fixture' -Software @('Python') -RetentionContractEnabled "
            "-RetentionClass solver_review -RetentionReason 'fixture'; "
            f"$sources=@({quoted_sources}); $inputs=[ordered]@{{}}; $i=0; "
            "foreach($source in $sources){$i+=1; $destination=Join-Path $p.input_dir ('evidence_'+$i+'.json'); "
            "$inputs['evidence_'+$i]=Copy-VerifiedRunInput -Source $source -Destination $destination}; "
            "$config=Get-Content -Raw -LiteralPath $p.run_config|ConvertFrom-Json -AsHashtable; "
            "$config.inputs=$inputs; Write-RunJson -Path $p.run_config -Value $config; "
            f"$receipt=Apply-RunArtifactRetention -Python '{sys.executable}' -RepoRoot '{repository}' -RunConfig $p.run_config; "
            "if(-not(Test-Path -LiteralPath $receipt -PathType Leaf)){exit 9}"
        )
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", command],
            capture_output=True, encoding="utf-8", errors="replace", check=False,
            cwd=REPOSITORY, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
