"""Tests for the campaign-only RF-multipole to oaTOF execution tail."""

from __future__ import annotations

import concurrent.futures
import json
import hashlib
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from common.contracts.file_identity import file_sha256, repository_text_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.publish_run import (
    INTEGRATION_ID,
    SINGLE_FLIGHT_STAGES,
    STAGES,
    stage_project_id,
    publish_family_source_closure_failure,
    publish_family_source_closure_run,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
ADAPTER_PATH = (
    REPO_ROOT
    / "integrations"
    / INTEGRATION_ID
    / "workflows"
    / "family_source_closure"
    / "adapter.ps1"
)
WORKFLOW_ROOT = ADAPTER_PATH.parent
RUN_ARTIFACTS_PATH = (
    REPO_ROOT / "integrations" / INTEGRATION_ID / "runtime" / "run_artifacts.ps1"
)


class JointSingleFlightOwnershipTests(unittest.TestCase):
    def test_new_single_flight_stage_is_integration_owned(self) -> None:
        upstream = "rf_octupole_ion_optics"
        self.assertEqual(
            stage_project_id("simion_single_flight", upstream), INTEGRATION_ID
        )
        self.assertEqual(
            stage_project_id("staged_three_stage", upstream), upstream
        )
        with self.assertRaisesRegex(ContractError, "unsupported"):
            stage_project_id("unknown", upstream)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def record(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def make_single_flight_publication_fixture(
    workspace: Path, *, staged: bool
) -> dict[str, object]:
    fixture_repo = workspace / "simulation_repo"
    campaign = fixture_repo / "integrations" / INTEGRATION_ID / "config/campaign.json"
    campaign.parent.mkdir(parents=True)
    write_json(campaign, {"role": "campaign_fixture"})
    run_id = "20260815_140000__sim__cross__publisher-test__n34__r08"
    run_dir = workspace / "artifacts/projects" / INTEGRATION_ID / "runs" / run_id
    run_dir.mkdir(parents=True)
    profile_id = "rf_octupole_oatof_direct_mating_gap_0mm"
    canonical = {
        "authority_role": "staged_grid2_canonical_source_state",
        "source_branch_id": "simion",
        "solver_id": "simion",
        "run_id": "canonical_grid2_run",
        "project_id": "rf_octupole_ion_optics",
        "manifest_sha256": "A" * 64,
        "event_sha256": "B" * 64,
        "particle_source_sha256": "B" * 64,
        "metadata_sha256": "B" * 64,
        "state_event": "local_accelerator_exit",
        "clock_epoch_id": "instrument_clock_epoch_v1",
    }
    lineage_identity = {
        "source_branch_id": "simion",
        "solver_id": "simion",
        "run_id": "upstream_connection_run",
        "project_id": "rf_octupole_ion_optics",
        "manifest_sha256": "C" * 64,
        "event_sha256": "D" * 64,
        "particle_source_sha256": "E" * 64,
        "metadata_sha256": "F" * 64,
    }
    lineage = {
        "authority_scope": "connection_lineage_only",
        "identity": lineage_identity,
    }
    runtime = run_dir / "runtime.json"
    resolved = run_dir / "resolved_connection.json"
    plan = run_dir / "composition_plan.json"
    budget = run_dir / "resolved_engineering_budget.json"
    receipt = run_dir / "execution_receipt.json"
    source_contract = run_dir / "resolved_source_contract.json"
    design = run_dir / "upstream_resolved_design.json"
    population = run_dir / "resolved_population_contract.json"
    write_json(runtime, {"role": "runtime_fixture"})
    write_json(
        resolved,
        {
            "integration_id": INTEGRATION_ID,
            "connector": {"length_mm": 0.0},
            "selection": {
                "connection_profile_id": profile_id,
                "upstream_project_id": "rf_octupole_ion_optics",
            },
        },
    )
    write_json(
        plan,
        {
            "integration_id": INTEGRATION_ID,
            "selection": {"connection_profile_id": profile_id},
        },
    )
    write_json(design, {"role": "design_fixture"})
    write_json(
        source_contract,
        {
            "role": "rf_multipole_oatof_source_contract",
            "authority_scope": "connection_lineage_only",
            "source_branches": {
                "simion": {
                    "solver_id": "simion",
                    "recorded_project_id": lineage_identity["project_id"],
                    "source": {
                        "run_id": lineage_identity["run_id"],
                        "manifest": {"sha256": lineage_identity["manifest_sha256"]},
                        "state": {"sha256": lineage_identity["event_sha256"]},
                        "particle_source": {
                            "sha256": lineage_identity["particle_source_sha256"]
                        },
                        "metadata": {"sha256": lineage_identity["metadata_sha256"]},
                    },
                }
            },
        },
    )
    write_json(
        population,
        {
            "role": "rf_oatof_resolved_population_contract",
            "campaign_id": "publisher_test",
            "experiment_id": "staged" if staged else "pre_pulse",
            "experiment_row_sha256": "1" * 64,
            "source_release_mode": (
                "staged_grid2_restart" if staged else "pre_pulse_restart"
            ),
            "execution_population": {"particle_count": 34},
        },
    )
    campaign_identity = {
        "campaign_id": "publisher_test",
        "experiment_id": "staged" if staged else "pre_pulse",
        "experiment_row_sha256": "1" * 64,
        "launched_particle_count": 34,
        "particle_count": 34,
        "policy_id": "compact_serial_commercial_solvers",
        "retention_class": "compact",
    }
    write_json(
        budget,
        {
            "connection_profile_id": profile_id,
            "execution_strategy": "simion_single_flight",
            "source_identity": canonical,
            **campaign_identity,
        },
    )
    stage_id = (
        run_id[:15]
        + SINGLE_FLIGHT_STAGES["single_flight_transport"]["run_stem"]
        + "34__r08"
    )
    stage_dir = workspace / "artifacts/projects" / INTEGRATION_ID / "runs" / stage_id
    stage_dir.mkdir(parents=True)
    stage_config = {
        "schema_version": 2,
        "run_id": stage_id,
        "project": INTEGRATION_ID,
        "mode": SINGLE_FLIGHT_STAGES["single_flight_transport"]["mode"],
        "parameters": {
            "connection_profile_id": profile_id,
            "source_branch_id": "simion",
        },
        "inputs": {
            "runtime_binding": str(runtime.resolve()),
            "resolved_connection": str(resolved.resolve()),
            "resolved_population_contract": str(population.resolve()),
        },
        ("source_identity" if staged else "upstream_source_identity"): canonical,
    }
    if staged:
        stage_config["connection_lineage"] = lineage
    write_json(stage_dir / "run_config.json", stage_config)
    write_json(
        stage_dir / "run_manifest.json",
        {
            "role": "simulation_run_manifest",
            "run_id": stage_id,
            "project": INTEGRATION_ID,
            "mode": SINGLE_FLIGHT_STAGES["single_flight_transport"]["mode"],
            "status": "success",
            "run_config": record(stage_dir / "run_config.json"),
        },
    )
    write_json(stage_dir / "summary.json", {"census": {"detector": 34}})
    receipt_value = {
        "role": "integration_family_source_closure_execution_receipt",
        "integration_run_id": run_id,
        "execution_status": "completed_pending_paired_analysis",
        "execution_strategy": "simion_single_flight",
        "connection_profile_id": profile_id,
        "campaign_path": campaign.relative_to(fixture_repo).as_posix(),
        "campaign_sha256": repository_text_sha256(campaign),
        "resolved_source_contract_filename": source_contract.name,
        "resolved_source_contract_sha256": file_sha256(source_contract),
        "upstream_resolved_design_filename": design.name,
        "upstream_resolved_design_sha256": file_sha256(design),
        "resolved_population_contract_filename": population.name,
        "resolved_population_contract_sha256": file_sha256(population),
        "source_branch_id": "simion",
        "source_identity": canonical,
        "resolved_connection_sha256": file_sha256(resolved),
        "stage_run_ids": {"single_flight_transport": stage_id},
        "stage_runtime_binding_sha256s": {
            "single_flight_transport": file_sha256(runtime)
        },
        **campaign_identity,
    }
    if staged:
        receipt_value["connection_lineage"] = lineage
    write_json(receipt, receipt_value)
    return {
        "repo": fixture_repo,
        "run_dir": run_dir,
        "receipt": receipt,
        "resolved": resolved,
        "plan": plan,
        "budget": budget,
        "stage_config": stage_dir / "run_config.json",
        "canonical": canonical,
        "lineage": lineage,
    }


class CampaignOnlyAdapterPublicationTests(unittest.TestCase):
    def _publish_single_flight_fixture(self, fixture: dict[str, object]) -> None:
        with patch(
            "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.publish_run.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
        ):
            publish_family_source_closure_run(
                repo_root=fixture["repo"],
                workspace_root=fixture["repo"].parent,
                integration_run_dir=fixture["run_dir"],
                receipt_path=fixture["receipt"],
                resolved_path=fixture["resolved"],
                plan_path=fixture["plan"],
                budget_path=fixture["budget"],
            )

    def test_staged_single_flight_publishes_one_canonical_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = make_single_flight_publication_fixture(
                Path(directory), staged=True
            )
            self._publish_single_flight_fixture(fixture)
            parent = json.loads(
                (fixture["run_dir"] / "run_config.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(parent["source_identity"], fixture["canonical"])
            self.assertEqual(parent["connection_lineage"], fixture["lineage"])
            self.assertNotIn("upstream_source_identity", parent)
            self.assertNotIn("source_particle_identity", parent)

    def test_staged_single_flight_rejects_canonical_lineage_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = make_single_flight_publication_fixture(
                Path(directory), staged=True
            )
            stage = json.loads(fixture["stage_config"].read_text(encoding="utf-8"))
            stage["source_identity"] = fixture["lineage"]["identity"]
            stage["connection_lineage"] = {
                "authority_scope": "connection_lineage_only",
                "identity": fixture["canonical"],
            }
            write_json(fixture["stage_config"], stage)
            stage_manifest = fixture["stage_config"].with_name("run_manifest.json")
            manifest = json.loads(stage_manifest.read_text(encoding="utf-8"))
            manifest["run_config"] = record(fixture["stage_config"])
            write_json(stage_manifest, manifest)
            with self.assertRaisesRegex(ContractError, "source identities differ"):
                self._publish_single_flight_fixture(fixture)

    def test_staged_single_flight_rejects_connection_lineage_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = make_single_flight_publication_fixture(
                Path(directory), staged=True
            )
            receipt = json.loads(fixture["receipt"].read_text(encoding="utf-8"))
            receipt["connection_lineage"]["identity"]["event_sha256"] = "9" * 64
            write_json(fixture["receipt"], receipt)
            with self.assertRaisesRegex(ContractError, "connection lineage differs"):
                self._publish_single_flight_fixture(fixture)

    def test_nonstaged_single_flight_keeps_upstream_source_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = make_single_flight_publication_fixture(
                Path(directory), staged=False
            )
            self._publish_single_flight_fixture(fixture)
            parent = json.loads(
                (fixture["run_dir"] / "run_config.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                parent["source_particle_identity"], fixture["canonical"]
            )
            self.assertNotIn("connection_lineage", parent)

    def test_shared_cache_publisher_creates_verified_atomic_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            cache_root = (
                workspace / "artifacts" / "projects" / INTEGRATION_ID / "cache"
                / "simion_single_flight_frontend"
            )
            identity_path = workspace / "identity.json"
            identity = {
                "schema_version": 2,
                "role": "simion_single_flight_frontend_pa_cache",
                "project_id": INTEGRATION_ID,
                "solver": {
                    "name": "SIMION",
                    "product_version": "2020",
                    "executable_sha256": "B" * 64,
                },
                "critical_options": {"refine": ["--nogui", "refine"]},
            }
            write_json(identity_path, identity)
            command = (
                f". '{RUN_ARTIFACTS_PATH}'; "
                f"$identity=Get-Content -Raw -LiteralPath '{identity_path}' | ConvertFrom-Json; "
                f"$key=Get-RfContentIdentitySha256 -Identity $identity; "
                f"$staging=New-RfCacheStagingDirectory -CacheRoot '{cache_root}'; "
                "'frontend.gem','frontend.pa#','frontend.pa0' | ForEach-Object { "
                "[IO.File]::WriteAllText((Join-Path $staging $_),$_) }; "
                f"Publish-RfVerifiedCacheEntry -Python '{Path(sys.executable)}' "
                f"-RepoRoot '{REPO_ROOT}' -WorkspaceRoot '{workspace}' "
                f"-ProjectId '{INTEGRATION_ID}' -CacheRoot '{cache_root}' "
                "-CacheKey $key -Role $identity.role -Identity $identity "
                "-StagingDirectory $staging -ProviderRunId fixture"
            )
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", command],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            entries = list(cache_root.iterdir())
            self.assertEqual(len(entries), 1, result.stdout + result.stderr)
            key_directory = entries[0]
            pointer = json.loads(
                (key_directory / "current_generation.json").read_text(
                    encoding="utf-8-sig"
                )
            )
            entry = key_directory / pointer["generation_relative_path"]
            manifest = json.loads(
                (entry / "cache_manifest.json").read_text(encoding="utf-8-sig")
            )
            self.assertEqual(manifest["schema_version"], 3)
            self.assertEqual(manifest["cache_key"], key_directory.name)
            self.assertEqual(manifest["generation_sha256"], pointer["generation_sha256"])
            self.assertEqual(manifest["payload_sha256"], pointer["payload_sha256"])
            self.assertEqual(len(manifest["files"]), 3)
            for name in ("frontend.gem", "frontend.pa#", "frontend.pa0"):
                self.assertTrue(
                    (entry / name).stat().st_file_attributes
                    & stat.FILE_ATTRIBUTE_READONLY
                )
            self.assertFalse(
                (entry / "cache_manifest.json").stat().st_file_attributes
                & stat.FILE_ATTRIBUTE_READONLY
            )

    def test_legacy_v2_cache_promotion_rehashes_and_preserves_legacy_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            cache_root = (
                workspace / "artifacts" / "projects" / INTEGRATION_ID / "cache"
                / "simion_single_flight_frontend"
            )
            identity = {
                "schema_version": 2,
                "role": "simion_single_flight_frontend_pa_cache",
                "project_id": INTEGRATION_ID,
                "solver": {
                    "name": "SIMION",
                    "product_version": "2020",
                    "executable_sha256": "C" * 64,
                },
                "critical_options": {"refine": ["--nogui", "refine"]},
            }
            identity_path = workspace / "identity.json"
            write_json(identity_path, identity)
            key = hashlib.sha256(
                json.dumps(identity, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            legacy = cache_root / key
            legacy.mkdir(parents=True)
            payload = {
                "frontend.gem": b"legacy-gem",
                "frontend.pa#": b"legacy-pa-sharp",
                "frontend.pa0": b"legacy-pa-zero",
            }
            for name, value in payload.items():
                (legacy / name).write_bytes(value)
            legacy_manifest = {
                "schema_version": 2,
                "role": identity["role"],
                "cache_key": key,
                "provider_run_id": "legacy-provider",
                "cache_key_input": json.dumps(identity, separators=(",", ":")),
                "identity": identity,
                "files": [
                    {
                        "name": name,
                        "bytes": len(value),
                        "sha256": hashlib.sha256(value).hexdigest().upper(),
                    }
                    for name, value in payload.items()
                ],
            }
            write_json(legacy / "cache_manifest.json", legacy_manifest)
            command = (
                f". '{RUN_ARTIFACTS_PATH}'; "
                f"$identity=Get-Content -Raw -LiteralPath '{identity_path}' | ConvertFrom-Json; "
                f"Promote-RfVerifiedLegacyV2CacheEntry -Python '{Path(sys.executable)}' "
                f"-RepoRoot '{REPO_ROOT}' -WorkspaceRoot '{workspace}' "
                f"-ProjectId '{INTEGRATION_ID}' -CacheRoot '{cache_root}' "
                f"-CacheKey '{key}' -Role $identity.role -Identity $identity | Out-Null"
            )
            subprocess.run(
                ["pwsh", "-NoProfile", "-Command", command], cwd=REPO_ROOT,
                check=True, capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(
                json.loads((legacy / "cache_manifest.json").read_text(encoding="utf-8")),
                legacy_manifest,
            )
            for name, value in payload.items():
                self.assertEqual((legacy / name).read_bytes(), value)
            pointer = json.loads(
                (legacy / "current_generation.json").read_text(encoding="utf-8-sig")
            )
            generation = legacy / pointer["generation_relative_path"]
            promoted = json.loads(
                (generation / "cache_manifest.json").read_text(encoding="utf-8-sig")
            )
            self.assertEqual(promoted["schema_version"], 3)
            self.assertEqual(promoted["provider_run_id"], "legacy-provider")
            self.assertEqual(promoted["identity"], legacy_manifest["identity"])
            for name, value in payload.items():
                self.assertEqual((generation / name).read_bytes(), value)
                self.assertTrue(
                    (generation / name).stat().st_file_attributes
                    & stat.FILE_ATTRIBUTE_READONLY
                )

    def test_legacy_v2_cache_promotion_requires_exact_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            cache_root = (
                workspace / "artifacts" / "projects" / INTEGRATION_ID / "cache"
                / "simion_single_flight_frontend"
            )
            legacy_identity = {
                "schema_version": 2,
                "role": "simion_single_flight_frontend_pa_cache",
                "project_id": INTEGRATION_ID,
                "solver": {"name": "SIMION", "product_version": "2020", "executable_sha256": "D" * 64},
                "critical_options": {"refine": ["--nogui", "refine"]},
            }
            key = hashlib.sha256(
                json.dumps(legacy_identity, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            legacy = cache_root / key
            legacy.mkdir(parents=True)
            value = b"legacy-pa"
            (legacy / "frontend.pa0").write_bytes(value)
            write_json(legacy / "cache_manifest.json", {
                "schema_version": 2, "role": legacy_identity["role"],
                "cache_key": key, "provider_run_id": "legacy-provider",
                "cache_key_input": json.dumps(legacy_identity, separators=(",", ":")),
                "identity": legacy_identity,
                "files": [{"name": "frontend.pa0", "bytes": len(value),
                           "sha256": hashlib.sha256(value).hexdigest().upper()}],
            })
            incompatible = dict(legacy_identity)
            incompatible["critical_options"] = {"refine": ["--nogui", "other"]}
            identity_path = workspace / "identity.json"
            write_json(identity_path, incompatible)
            command = (
                f". '{RUN_ARTIFACTS_PATH}'; "
                f"$identity=Get-Content -Raw -LiteralPath '{identity_path}' | ConvertFrom-Json; "
                f"$result=Promote-RfVerifiedLegacyV2CacheEntry -Python '{Path(sys.executable)}' "
                f"-RepoRoot '{REPO_ROOT}' -WorkspaceRoot '{workspace}' "
                f"-ProjectId '{INTEGRATION_ID}' -CacheRoot '{cache_root}' "
                f"-CacheKey '{key}' -Role $identity.role -Identity $identity; "
                "if ($null -ne $result) { throw 'unexpected promotion' }"
            )
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", command], cwd=REPO_ROOT,
                capture_output=True, text=True, timeout=120,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((legacy / "current_generation.json").exists())
            self.assertEqual((legacy / "frontend.pa0").read_bytes(), value)

    def test_required_existing_normal_cache_path_reuses_verified_legacy_and_rejects_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)

            def write_legacy(cache_root: Path, identity: dict, payload: bytes) -> tuple[str, Path]:
                key = hashlib.sha256(
                    json.dumps(identity, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                legacy = cache_root / key
                legacy.mkdir(parents=True)
                files = {
                    "frontend.gem": payload + b"-gem",
                    "frontend.pa#": payload + b"-sharp",
                    "frontend.pa0": payload,
                }
                for name, value in files.items():
                    (legacy / name).write_bytes(value)
                write_json(legacy / "cache_manifest.json", {
                    "schema_version": 2, "role": identity["role"],
                    "cache_key": key, "provider_run_id": "legacy-provider",
                    "cache_key_input": json.dumps(identity, separators=(",", ":")),
                    "identity": identity,
                    "files": [
                        {"name": name, "bytes": len(value),
                         "sha256": hashlib.sha256(value).hexdigest().upper()}
                        for name, value in files.items()
                    ],
                })
                return key, legacy

            exact_identity = {
                "schema_version": 2,
                "role": "simion_single_flight_frontend_pa_cache",
                "project_id": INTEGRATION_ID,
                "solver": {"name": "SIMION", "product_version": "2020", "executable_sha256": "E" * 64},
                "critical_options": {"refine": ["--nogui", "refine"]},
            }
            exact_root = workspace / "artifacts" / "projects" / INTEGRATION_ID / "cache" / "simion_single_flight_frontend"
            exact_key, exact_legacy = write_legacy(exact_root, exact_identity, b"exact-legacy")
            exact_identity_path = workspace / "exact_identity.json"
            write_json(exact_identity_path, exact_identity)
            exact_command = (
                f". '{RUN_ARTIFACTS_PATH}'; "
                f"$identity=Get-Content -Raw -LiteralPath '{exact_identity_path}' | ConvertFrom-Json; "
                f"$directory=Resolve-RfReusableCacheDirectory -Python '{Path(sys.executable)}' "
                f"-RepoRoot '{REPO_ROOT}' -WorkspaceRoot '{workspace}' "
                f"-ProjectId '{INTEGRATION_ID}' -CacheRoot '{exact_root}' "
                f"-CacheKey '{exact_key}' -Role $identity.role -Identity $identity "
                "-InvalidEntryAction preserve; "
                "if ($null -eq $directory) { throw 'verified legacy cache was not reusable' }; "
                f"if ($directory -ne '{exact_legacy}') {{ throw 'legacy cache did not remain direct' }}"
            )
            subprocess.run(
                ["pwsh", "-NoProfile", "-Command", exact_command],
                cwd=REPO_ROOT, check=True, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=120,
            )
            self.assertFalse((exact_legacy / "current_generation.json").exists())
            self.assertEqual(
                json.loads((exact_legacy / "cache_manifest.json").read_text(encoding="utf-8")),
                {
                    "schema_version": 2, "role": exact_identity["role"],
                    "cache_key": exact_key, "provider_run_id": "legacy-provider",
                    "cache_key_input": json.dumps(exact_identity, separators=(",", ":")),
                    "identity": exact_identity,
                    "files": [
                        {"name": name, "bytes": len(value),
                         "sha256": hashlib.sha256(value).hexdigest().upper()}
                        for name, value in {
                            "frontend.gem": b"exact-legacy-gem",
                            "frontend.pa#": b"exact-legacy-sharp",
                            "frontend.pa0": b"exact-legacy",
                        }.items()
                    ],
                },
            )
            self.assertEqual((exact_legacy / "frontend.pa0").read_bytes(), b"exact-legacy")

            mismatch_identity = dict(exact_identity)
            mismatch_identity["solver"] = dict(exact_identity["solver"])
            mismatch_identity["solver"]["executable_sha256"] = "F" * 64
            mismatch_root = exact_root
            mismatch_key, mismatch_legacy = write_legacy(mismatch_root, mismatch_identity, b"mismatch-legacy")
            incompatible = dict(mismatch_identity)
            incompatible["solver"] = dict(mismatch_identity["solver"])
            incompatible["solver"]["executable_sha256"] = "0" * 64
            incompatible_path = workspace / "incompatible_identity.json"
            write_json(incompatible_path, incompatible)
            mismatch_command = (
                f". '{RUN_ARTIFACTS_PATH}'; "
                f"$identity=Get-Content -Raw -LiteralPath '{incompatible_path}' | ConvertFrom-Json; "
                f"$directory=Resolve-RfReusableCacheDirectory -Python '{Path(sys.executable)}' "
                f"-RepoRoot '{REPO_ROOT}' -WorkspaceRoot '{workspace}' "
                f"-ProjectId '{INTEGRATION_ID}' -CacheRoot '{mismatch_root}' "
                f"-CacheKey '{mismatch_key}' -Role $identity.role -Identity $identity "
                "-InvalidEntryAction preserve; "
                "if ($null -ne $directory) { throw 'mismatched legacy cache was reusable' }"
            )
            mismatch = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", mismatch_command],
                cwd=REPO_ROOT, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=120,
            )
            self.assertEqual(mismatch.returncode, 0, mismatch.stderr)
            self.assertFalse((mismatch_legacy / "current_generation.json").exists())
            self.assertEqual((mismatch_legacy / "frontend.pa0").read_bytes(), b"mismatch-legacy")

    def test_shared_cache_helper_verifies_hit_and_removes_invalid_generation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            cache_root = (
                workspace / "artifacts" / "projects" / INTEGRATION_ID / "cache"
                / "simion_single_flight_frontend"
            )
            identity = {
                "schema_version": 2,
                "role": "simion_single_flight_frontend_pa_cache",
                "project_id": INTEGRATION_ID,
                "solver": {
                    "name": "SIMION",
                    "product_version": "2020",
                    "executable_sha256": "A" * 64,
                },
                "critical_options": {"refine": ["--nogui", "refine"]},
            }
            identity_path = workspace / "identity.json"
            write_json(identity_path, identity)
            publish = (
                f". '{RUN_ARTIFACTS_PATH}'; "
                f"$identity=Get-Content -Raw -LiteralPath '{identity_path}' | ConvertFrom-Json; "
                "$key=Get-RfContentIdentitySha256 -Identity $identity; "
                f"$staging=New-RfCacheStagingDirectory -CacheRoot '{cache_root}'; "
                "'frontend.gem','frontend.pa#','frontend.pa0' | ForEach-Object { "
                "[IO.File]::WriteAllText((Join-Path $staging $_), $_) }; "
                f"Publish-RfVerifiedCacheEntry -Python '{Path(sys.executable)}' "
                f"-RepoRoot '{REPO_ROOT}' -WorkspaceRoot '{workspace}' "
                f"-ProjectId '{INTEGRATION_ID}' -CacheRoot '{cache_root}' "
                "-CacheKey $key -Role $identity.role -Identity $identity "
                "-StagingDirectory $staging -ProviderRunId fixture | Out-Null"
            )
            subprocess.run(["pwsh", "-NoProfile", "-Command", publish], cwd=REPO_ROOT,
                           check=True, capture_output=True, text=True, timeout=120)
            key = next(cache_root.iterdir()).name
            pointer = json.loads((cache_root / key / "current_generation.json").read_text(encoding="utf-8-sig"))
            entry = cache_root / key / pointer["generation_relative_path"]
            command = (
                f". '{RUN_ARTIFACTS_PATH}'; "
                f"Test-RfReusableCacheEntry -Python '{Path(sys.executable)}' "
                f"-RepoRoot '{REPO_ROOT}' -WorkspaceRoot '{workspace}' "
                f"-ProjectId '{INTEGRATION_ID}' -CacheRoot '{cache_root}' "
                f"-CacheKey '{key}' -Role '{identity['role']}'; exit 0"
            )
            first = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", command],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertIn("True", first.stdout)
            for name in ("frontend.gem", "frontend.pa#", "frontend.pa0"):
                self.assertTrue(
                    (entry / name).stat().st_file_attributes
                    & stat.FILE_ATTRIBUTE_READONLY
                )
            changed = entry / "frontend.pa0"
            changed.chmod(stat.S_IWRITE)
            changed.write_text("changed\n", encoding="utf-8")
            changed.chmod(stat.S_IREAD)
            second = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", command],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertIn("False", second.stdout)
            self.assertFalse(entry.exists())
            self.assertTrue((cache_root / key).exists())

    def test_rebuild_publishes_new_generation_without_overwriting_prior_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            cache_root = (
                workspace / "artifacts" / "projects" / INTEGRATION_ID / "cache"
                / "simion_single_flight_frontend"
            )
            identity = {
                "schema_version": 2,
                "role": "simion_single_flight_frontend_pa_cache",
                "project_id": INTEGRATION_ID,
                "solver": {"name": "SIMION", "product_version": "2020", "executable_sha256": "D" * 64},
                "critical_options": {"refine": ["--nogui", "refine"]},
            }
            identity_path = workspace / "identity.json"
            write_json(identity_path, identity)

            def publish(label: str) -> None:
                command = (
                    f". '{RUN_ARTIFACTS_PATH}'; "
                    f"$identity=Get-Content -Raw -LiteralPath '{identity_path}' | ConvertFrom-Json; "
                    "$key=Get-RfContentIdentitySha256 -Identity $identity; "
                    f"$staging=New-RfCacheStagingDirectory -CacheRoot '{cache_root}'; "
                    "'frontend.gem','frontend.pa#','frontend.pa0' | ForEach-Object { "
                    f"[IO.File]::WriteAllText((Join-Path $staging $_), '{label}:' + $_) }}; "
                    f"Publish-RfVerifiedCacheEntry -Python '{Path(sys.executable)}' "
                    f"-RepoRoot '{REPO_ROOT}' -WorkspaceRoot '{workspace}' "
                    f"-ProjectId '{INTEGRATION_ID}' -CacheRoot '{cache_root}' "
                    "-CacheKey $key -Role $identity.role -Identity $identity "
                    f"-StagingDirectory $staging -ProviderRunId '{label}' | Out-Null"
                )
                subprocess.run(["pwsh", "-NoProfile", "-Command", command], cwd=REPO_ROOT,
                               check=True, capture_output=True, text=True, timeout=120)

            publish("first")
            key_directory = next(cache_root.iterdir())
            first_pointer = json.loads((key_directory / "current_generation.json").read_text(encoding="utf-8-sig"))
            first_entry = key_directory / first_pointer["generation_relative_path"]
            first_payload = (first_entry / "frontend.pa0").read_text(encoding="utf-8")
            publish("second")
            second_pointer = json.loads((key_directory / "current_generation.json").read_text(encoding="utf-8-sig"))
            second_entry = key_directory / second_pointer["generation_relative_path"]
            self.assertNotEqual(first_pointer["generation_sha256"], second_pointer["generation_sha256"])
            self.assertNotEqual(first_pointer["payload_sha256"], second_pointer["payload_sha256"])
            self.assertTrue(first_entry.is_dir())
            self.assertEqual((first_entry / "frontend.pa0").read_text(encoding="utf-8"), first_payload)
            self.assertEqual((second_entry / "frontend.pa0").read_text(encoding="utf-8"), "second:frontend.pa0")
            self.assertEqual(len(list((key_directory / "generations").iterdir())), 2)

    def test_materialized_cache_copy_is_writable_without_mutating_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pa0"
            target = root / "target.pa0"
            source.write_bytes(b"immutable-cache-payload")
            source_hash = file_sha256(source)
            source.chmod(stat.S_IREAD)
            command = (
                f". '{RUN_ARTIFACTS_PATH}'; "
                f"Copy-Item -LiteralPath '{source}' -Destination '{target}'; "
                f"Set-RfMaterializedCacheFileWritable -Path '{target}'"
            )
            subprocess.run(
                ["pwsh", "-NoProfile", "-Command", command],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertTrue(
                source.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY
            )
            self.assertFalse(
                target.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY
            )
            target.write_bytes(b"private-run-copy")
            self.assertEqual(file_sha256(source), source_hash)

    def test_require_existing_preserves_a_damaged_cache_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            cache_root = workspace / "artifacts" / "projects" / INTEGRATION_ID / "cache" / "simion_single_flight_frontend"
            key = "a" * 64
            entry = cache_root / key
            entry.mkdir(parents=True)
            write_json(entry / "cache_manifest.json", {
                "schema_version": 2, "role": "simion_single_flight_frontend_pa_cache",
                "cache_key": key, "provider_run_id": "fixture", "cache_key_input": "{}",
                "identity": {}, "files": [],
            })
            command = (
                f". '{RUN_ARTIFACTS_PATH}'; "
                f"Test-RfReusableCacheEntry -Python '{Path(sys.executable)}' "
                f"-RepoRoot '{REPO_ROOT}' -WorkspaceRoot '{workspace}' "
                f"-ProjectId '{INTEGRATION_ID}' -CacheRoot '{cache_root}' "
                "-CacheKey '" + key + "' -Role 'simion_single_flight_frontend_pa_cache' "
                "-InvalidEntryAction preserve; exit 0"
            )
            result = subprocess.run(["pwsh", "-NoProfile", "-Command", command], cwd=REPO_ROOT, check=True, capture_output=True, text=True, timeout=120)
            self.assertIn("False", result.stdout)
            self.assertTrue(entry.is_dir())

    def test_cache_key_lock_serializes_concurrent_verify_build_publish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            cache_root = (
                workspace / "artifacts" / "projects" / INTEGRATION_ID / "cache"
                / "simion_single_flight_frontend"
            )
            identity = {
                "schema_version": 2,
                "role": "simion_single_flight_frontend_pa_cache",
                "project_id": INTEGRATION_ID,
                "solver": {
                    "name": "SIMION",
                    "product_version": "2020",
                    "executable_sha256": "C" * 64,
                },
                "critical_options": {"refine": ["--nogui", "refine"]},
            }
            identity_path = workspace / "identity.json"
            marker = workspace / "builds.txt"
            write_json(identity_path, identity)

            def publisher(label: str) -> subprocess.CompletedProcess[str]:
                command = (
                    f". '{RUN_ARTIFACTS_PATH}'; "
                    f"$identity=Get-Content -Raw -LiteralPath '{identity_path}' | ConvertFrom-Json; "
                    "$key=Get-RfContentIdentitySha256 -Identity $identity; "
                    f"$lock=Enter-RfCacheKeyLock -CacheRoot '{cache_root}' -CacheKey $key; "
                    "try { "
                    f"$hit=Test-RfReusableCacheEntry -Python '{Path(sys.executable)}' "
                    f"-RepoRoot '{REPO_ROOT}' -WorkspaceRoot '{workspace}' "
                    f"-ProjectId '{INTEGRATION_ID}' -CacheRoot '{cache_root}' "
                    "-CacheKey $key -Role $identity.role; "
                    "if (-not $hit) { "
                    f"[IO.File]::AppendAllText('{marker}', '{label}`n'); "
                    "Start-Sleep -Milliseconds 800; "
                    f"$staging=New-RfCacheStagingDirectory -CacheRoot '{cache_root}'; "
                    "'frontend.gem','frontend.pa#','frontend.pa0' | ForEach-Object { "
                    "[IO.File]::WriteAllText((Join-Path $staging $_), $_) }; "
                    f"Publish-RfVerifiedCacheEntry -Python '{Path(sys.executable)}' "
                    f"-RepoRoot '{REPO_ROOT}' -WorkspaceRoot '{workspace}' "
                    f"-ProjectId '{INTEGRATION_ID}' -CacheRoot '{cache_root}' "
                    "-CacheKey $key -Role $identity.role -Identity $identity "
                    f"-StagingDirectory $staging -ProviderRunId '{label}' | Out-Null "
                    "} "
                    "} finally { Exit-RfCacheKeyLock -Mutex $lock }"
                )
                return subprocess.run(
                    ["pwsh", "-NoProfile", "-Command", command],
                    cwd=REPO_ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=120,
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                first, second = executor.map(publisher, ("first", "second"))
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(len(marker.read_text(encoding="utf-8").splitlines()), 1)

    def test_build_policy_uses_direct_reuse_then_official_build_publish_fallback(self) -> None:
        runner = (RUN_ARTIFACTS_PATH.parent / "run_single_flight.ps1").read_text(encoding="utf-8")
        lock_index = runner.index("Enter-RfCacheKeyLock -CacheRoot $cacheRoot")
        test_index = runner.index(
            "Resolve-RfReusableCacheDirectory -Python $python"
        )
        gem2pa_index = runner.index(
            "-ArgumentList @('--nogui','--noprompt','gem2pa'", test_index
        )
        publish_index = runner.index("Publish-RfVerifiedCacheEntry -Python $python", gem2pa_index)
        unlock_index = runner.index("Exit-RfCacheKeyLock -Mutex $frontendCacheLock")
        self.assertLess(lock_index, test_index)
        self.assertLess(test_index, gem2pa_index)
        self.assertLess(gem2pa_index, publish_index)
        self.assertLess(publish_index, unlock_index)
        self.assertNotIn("-PromoteLegacyV2:$true", runner)

    def test_construction_time_frontend_recheck_uses_the_same_reuse_resolver(self) -> None:
        runner = (RUN_ARTIFACTS_PATH.parent / "run_single_flight.ps1").read_text(encoding="utf-8")
        message = "Frontend PA cache changed during construction-time SIMION access."
        recheck_start = runner.rfind("Resolve-RfReusableCacheDirectory -Python $python", 0, runner.index(message))
        self.assertGreaterEqual(recheck_start, 0)
        self.assertNotIn(
            "Test-RfReusableCacheEntry -Python $python",
            runner[recheck_start:runner.index(message)],
        )

    def test_ordinary_cache_freeze_accepts_verified_v2_but_strict_pairing_requires_v3(self) -> None:
        runner = (RUN_ARTIFACTS_PATH.parent / "run_single_flight.ps1").read_text(encoding="utf-8")
        freeze_block = runner[
            runner.index("foreach ($binding in $cacheManifestBindings)"):
            runner.index("$program = Join-Path $runtimeDir", runner.index("foreach ($binding in $cacheManifestBindings)"))
        ]
        self.assertIn("if ($hasRequiredPaCacheGenerationBinding)", freeze_block)
        self.assertIn("schema_version -notin @(2,3)", freeze_block)
        self.assertIn("lacks immutable generation identity", freeze_block)

    def test_campaign_repository_text_identity_is_newline_neutral_but_content_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lf = root / "campaign_lf.json"
            crlf = root / "campaign_crlf.json"
            changed = root / "campaign_changed.json"
            lf.write_bytes(b'{\n  "role": "campaign_fixture"\n}\n')
            crlf.write_bytes(b'{\r\n  "role": "campaign_fixture"\r\n}\r\n')
            changed.write_bytes(b'{\n  "role": "different_campaign"\n}\n')
            self.assertEqual(
                repository_text_sha256(lf), repository_text_sha256(crlf)
            )
            self.assertNotEqual(
                repository_text_sha256(lf), repository_text_sha256(changed)
            )

    def test_materialized_source_crosses_only_the_parent_child_run_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            parent = (
                workspace / "artifacts" / "projects" / INTEGRATION_ID /
                "runs" / "parent_run" / "inputs"
            )
            child = workspace / "child" / "inputs"
            parent.mkdir(parents=True)
            child.mkdir(parents=True)
            source = parent / "single_flight_materialized_particle_source.csv"
            receipt = parent / "single_flight_source_materialization_receipt.json"
            source.write_text("particle_id\n1\n", encoding="utf-8")
            receipt.write_text("{}\n", encoding="utf-8")
            frozen_source = child / "mother_particle_source.csv"
            frozen_receipt = child / "single_flight_source_materialization_receipt.json"
            command = (
                f". '{RUN_ARTIFACTS_PATH}'; "
                f"$root=Resolve-RfMaterializedMotherSourceRunRoot -WorkspaceRoot '{workspace}' "
                f"-SourcePath '{source}' -ReceiptPath '{receipt}'; "
                f"Copy-RfStableFile -SourceRunRoot $root -SourcePath '{source}' "
                f"-Destination '{frozen_source}' -Role source | Out-Null; "
                f"Copy-RfStableFile -SourceRunRoot $root -SourcePath '{receipt}' "
                f"-Destination '{frozen_receipt}' -Role receipt | Out-Null"
            )
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", command],
                cwd=REPO_ROOT,
                text=True, capture_output=True,
                timeout=120,
            )
            frozen_source_text = frozen_source.read_text(encoding="utf-8")
            frozen_receipt_text = frozen_receipt.read_text(encoding="utf-8")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(frozen_source_text, "particle_id\n1\n")
        self.assertEqual(frozen_receipt_text, "{}\n")

    def test_public_entry_and_prepare_are_campaign_only(self) -> None:
        execute_source = (WORKFLOW_ROOT / "execute.ps1").read_text(
            encoding="utf-8-sig"
        )
        prepare_source = (WORKFLOW_ROOT / "prepare.py").read_text(
            encoding="utf-8-sig"
        )
        param_start = execute_source.index("param(")
        param_depth = 0
        param_end = None
        for index in range(param_start, len(execute_source)):
            character = execute_source[index]
            if character == "(":
                param_depth += 1
            elif character == ")":
                param_depth -= 1
                if param_depth == 0:
                    param_end = index + 1
                    break
        self.assertIsNotNone(param_end)
        public_param_block = execute_source[param_start:param_end]

        self.assertIn("[Parameter(Mandatory)][string]$Campaign", public_param_block)
        self.assertIn("[string]$ExperimentId = ''", public_param_block)
        self.assertIn("[switch]$AllExperiments", public_param_block)
        self.assertIn(
            "ExperimentId is required unless AllExperiments is selected.", execute_source
        )
        self.assertIn(
            "AllExperiments and ExperimentId are mutually exclusive.", execute_source
        )
        self.assertIn("[string]$OutputDirectory = ''", public_param_block)
        self.assertIn("$campaignRunId = [string]$experimentRows[0].run_id", execute_source)
        self.assertIn("Select exactly one of ValidateOnly", execute_source)
        self.assertIn("OutputDirectory is accepted only for PrepareOnly", execute_source)
        self.assertIn("INTEGRATION_EXECUTION=ALREADY_SUCCESS", execute_source)
        self.assertIn("$publishedManifest.status -eq 'success'", execute_source)
        self.assertIn(
            "$publishedCampaignSha256.ToUpperInvariant() -eq $campaignSha256.ToUpperInvariant()",
            execute_source,
        )
        self.assertIn("'scratch'", execute_source)
        self.assertIn("__repo__family-source-validation-", execute_source)
        self.assertNotIn("validation_tmp", execute_source)
        self.assertIn("Remove-Item -LiteralPath $outputRoot -Recurse -Force", execute_source)
        for obsolete in (
            "[string]$RunId",
            "SourceRevisionId",
            "ConnectionProfileId",
            "SourceBranchId",
        ):
            self.assertNotIn(obsolete, public_param_block)
        for obsolete in ("preregistration", "revision-registry"):
            self.assertNotIn(obsolete, execute_source)
        self.assertIn(
            'shutil.copyfile(design_evidence["resolved_design_path"]',
            prepare_source,
        )
        self.assertIn('resolved_upstream.pop("port_binding", None)', prepare_source)
        self.assertIn(
            '"upstream_resolved_design_filename=upstream_resolved_design.json"',
            prepare_source,
        )

    def test_adapter_has_one_campaign_argument_contract(self) -> None:
        source = ADAPTER_PATH.read_text(encoding="utf-8-sig")
        required = (
            "campaign_path",
            "campaign_sha256",
            "campaign_id",
            "experiment_id",
            "experiment_row_sha256",
            "resolved_source_contract_filename",
            "upstream_resolved_design_filename",
        )
        for name in required:
            self.assertIn(f"'{name}'", source)
        for obsolete in (
            "campaignMode",
            "sourceRevision",
            "source_revision",
            "preregistration",
        ):
            self.assertNotIn(obsolete, source)
        self.assertIn("json.dumps(rows[0], ensure_ascii=False, sort_keys=True", source)
        self.assertIn("$stageParticleCount = [int]$budget.particle_count", source)
        self.assertIn("$retrySuffix = if ($RunId -match", source)

    def test_materialized_source_freezes_every_solver_consumed_property(self) -> None:
        source = ADAPTER_PATH.read_text(encoding="utf-8-sig")
        prepare_exit = source.index("if ($PrepareOnly)")
        population_validation = source.index(
            "$resolvedPopulation.role -ne 'rf_oatof_resolved_population_contract'"
        )
        solver_use = source.index("$runnerArguments.ResolvedPopulationContract =")
        self.assertLess(population_validation, prepare_exit)
        self.assertLess(prepare_exit, solver_use)
        self.assertNotIn("single_flight_sampling_mode", source)

    def test_parent_publication_is_n_neutral_and_preserves_both_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            fixture_repo = workspace / "simulation_repo"
            fixture_campaign = (
                fixture_repo
                / "integrations"
                / INTEGRATION_ID
                / "config"
                / "experiment_campaign.json"
            )
            fixture_campaign.parent.mkdir(parents=True)
            fixture_campaign.write_bytes(
                b'{\r\n  "role": "campaign_fixture"\r\n}\r\n'
            )
            run_id = "20260803_220000__sim__cross__campaign-parent__n1000__r02"
            run_dir = (
                workspace
                / "artifacts"
                / "projects"
                / INTEGRATION_ID
                / "runs"
                / run_id
            )
            run_dir.mkdir(parents=True)
            profile_id = (
                "rf_octupole_oatof_shield_terminal_direct_mating_gap_0mm"
            )
            project_id = "rf_octupole_ion_optics"
            launched_count = 1000
            selected_count = 41
            source_identity = {
                "source_branch_id": "simion",
                "solver_id": "simion",
                "run_id": "source_run",
                "project_id": project_id,
                "manifest_sha256": "A" * 64,
                "event_sha256": "B" * 64,
                "particle_source_sha256": "C" * 64,
                "metadata_sha256": "D" * 64,
            }
            runtime = run_dir / "runtime.json"
            resolved_source_contract = run_dir / "resolved_source_contract.json"
            upstream_resolved_design = run_dir / "upstream_resolved_design.json"
            resolved = run_dir / "resolved.json"
            plan = run_dir / "plan.json"
            budget = run_dir / "budget.json"
            receipt = run_dir / "receipt.json"
            write_json(runtime, {"role": "runtime_fixture"})
            write_json(resolved_source_contract, {"role": "source_fixture"})
            write_json(upstream_resolved_design, {"role": "design_fixture"})
            write_json(
                resolved,
                {
                    "integration_id": INTEGRATION_ID,
                    "selection": {
                        "connection_profile_id": profile_id,
                        "upstream_project_id": project_id,
                    },
                },
            )
            write_json(
                plan,
                {
                    "integration_id": INTEGRATION_ID,
                    "selection": {"connection_profile_id": profile_id},
                },
            )
            campaign_identity = {
                "campaign_id": "campaign_identity_test",
                "experiment_id": "octupole_segmented_test",
                "experiment_row_sha256": "E" * 64,
                "launched_particle_count": launched_count,
                "particle_count": selected_count,
                "policy_id": "compact_serial_commercial_solvers",
                "retention_class": "compact",
            }
            write_json(
                budget,
                {
                    "connection_profile_id": profile_id,
                    "execution_strategy": "staged_three_stage",
                    "source_identity": source_identity,
                    **campaign_identity,
                },
            )
            stage_ids = {
                phase: (
                    run_id[:15]
                    + contract["run_stem"]
                    + str(selected_count)
                    + "__r02"
                )
                for phase, contract in STAGES.items()
            }
            runtime_sha = file_sha256(runtime)
            write_json(
                receipt,
                {
                    "role": "integration_family_source_closure_execution_receipt",
                    "integration_run_id": run_id,
                    "execution_status": "completed_pending_paired_analysis",
                    "execution_strategy": "staged_three_stage",
                    "connection_profile_id": profile_id,
                    "campaign_path": (
                        "integrations/"
                        + INTEGRATION_ID
                        + "/config/experiment_campaign.json"
                    ),
                    "campaign_sha256": repository_text_sha256(
                        fixture_campaign
                    ),
                    "resolved_source_contract_filename": (
                        resolved_source_contract.name
                    ),
                    "resolved_source_contract_sha256": file_sha256(
                        resolved_source_contract
                    ),
                    "upstream_resolved_design_filename": (
                        upstream_resolved_design.name
                    ),
                    "upstream_resolved_design_sha256": file_sha256(
                        upstream_resolved_design
                    ),
                    "source_branch_id": "simion",
                    "source_identity": source_identity,
                    "resolved_connection_sha256": file_sha256(resolved),
                    "stage_run_ids": stage_ids,
                    "stage_runtime_binding_sha256s": {
                        phase: runtime_sha for phase in STAGES
                    },
                    **campaign_identity,
                },
            )
            stage_root = (
                workspace / "artifacts" / "projects" / project_id / "runs"
            )
            for phase, contract in STAGES.items():
                stage = stage_root / stage_ids[phase]
                stage.mkdir(parents=True)
                source_field = (
                    "source_particle_identity"
                    if phase == "pre_pulse_interface_transport"
                    else "upstream_source_identity"
                )
                stage_config = {
                    "schema_version": 2,
                    "run_id": stage.name,
                    "project": project_id,
                    "mode": contract["mode"],
                    "parameters": {
                        "connection_profile_id": profile_id,
                        "source_branch_id": "simion",
                    },
                    "inputs": {
                        "runtime_binding": str(runtime.resolve()),
                        "resolved_connection": str(resolved.resolve()),
                    },
                    source_field: source_identity,
                }
                write_json(stage / "run_config.json", stage_config)
                write_json(
                    stage / "run_manifest.json",
                    {
                        "role": "simulation_run_manifest",
                        "run_id": stage.name,
                        "project": project_id,
                        "mode": contract["mode"],
                        "status": "success",
                        "run_config": record(stage / "run_config.json"),
                    },
                )
                if phase == "analyzer_transport":
                    write_json(stage / "summary.json", {"census": {}})

            with patch(
                "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.publish_run.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
            ):
                publish_family_source_closure_run(
                    repo_root=fixture_repo,
                    workspace_root=workspace,
                    integration_run_dir=run_dir,
                    receipt_path=receipt,
                    resolved_path=resolved,
                    plan_path=plan,
                    budget_path=budget,
                )

            parent_config = json.loads(
                (run_dir / "run_config.json").read_text(encoding="utf-8")
            )
            parent_summary = json.loads(
                (run_dir / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(parent_config["mode"], "multipole_family_source_closure")
            self.assertEqual(parent_config["launched_particle_count"], 1000)
            self.assertEqual(parent_config["particle_count"], 41)
            self.assertEqual(parent_summary["launched_particle_count"], 1000)
            self.assertEqual(parent_summary["particle_count"], 41)
            self.assertNotIn("source_revision_id", parent_config)
            self.assertNotIn("source_revision_id", parent_summary)

    def test_failed_parent_publication_preserves_prepared_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            fixture_repo = workspace / "simulation_repo"
            fixture_repo.mkdir()
            run_id = "20260811_120000__sim__cross__failed-parent__n100__r01"
            run_dir = (
                workspace
                / "artifacts"
                / "projects"
                / INTEGRATION_ID
                / "runs"
                / run_id
            )
            run_dir.mkdir(parents=True)
            profile_id = "rf_octupole_oatof_direct_mating_gap_0mm"
            resolved = run_dir / "resolved_connection.json"
            plan = run_dir / "composition_plan.json"
            budget = run_dir / "resolved_engineering_budget.json"
            write_json(
                resolved,
                {
                    "integration_id": INTEGRATION_ID,
                    "selection": {"connection_profile_id": profile_id},
                },
            )
            write_json(
                plan,
                {
                    "integration_id": INTEGRATION_ID,
                    "selection": {"connection_profile_id": profile_id},
                },
            )
            write_json(
                budget,
                {
                    "connection_profile_id": profile_id,
                    "campaign_id": "failure_test",
                    "experiment_id": "failure_row",
                    "experiment_row_sha256": "A" * 64,
                    "execution_strategy": "simion_single_flight",
                    "launched_particle_count": 100,
                    "particle_count": 100,
                    "retention_class": "compact",
                },
            )
            with patch(
                "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.publish_run.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
            ):
                publish_family_source_closure_failure(
                    repo_root=fixture_repo,
                    workspace_root=workspace,
                    integration_run_dir=run_dir,
                    resolved_path=resolved,
                    plan_path=plan,
                    budget_path=budget,
                    terminal_status="failed",
                    reason="governed child failed",
                )
            config = json.loads(
                (run_dir / "run_config.json").read_text(encoding="utf-8")
            )
            summary = json.loads(
                (run_dir / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(config["inputs"]["composition_plan"], (
                f"artifacts/projects/{INTEGRATION_ID}/runs/{run_id}/"
                "composition_plan.json"
            ))
            self.assertEqual(summary["status"], "failed")
            self.assertFalse(summary["threshold_result_eligible"])
            self.assertEqual(summary["reason"], "governed child failed")


if __name__ == "__main__":
    unittest.main()
