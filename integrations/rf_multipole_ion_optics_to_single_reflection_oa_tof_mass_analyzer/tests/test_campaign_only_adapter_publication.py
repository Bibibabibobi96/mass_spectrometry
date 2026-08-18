"""Tests for the campaign-only RF-multipole to oaTOF execution tail."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
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
                check=True,
                capture_output=True,
                text=True,
            )
            entries = list(cache_root.iterdir())
            self.assertEqual(len(entries), 1, result.stdout + result.stderr)
            manifest = json.loads(
                (entries[0] / "cache_manifest.json").read_text(encoding="utf-8-sig")
            )
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["cache_key"], entries[0].name)
            self.assertEqual(len(manifest["files"]), 3)

    def test_shared_cache_helper_verifies_hit_and_removes_invalid_v2_entry(self) -> None:
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
            key_input = json.dumps(identity, separators=(",", ":"))
            key = hashlib.sha256(key_input.encode()).hexdigest()
            entry = cache_root / key
            entry.mkdir(parents=True)
            records = []
            for name in ("frontend.gem", "frontend.pa#", "frontend.pa0"):
                path = entry / name
                path.write_text(f"{name}\n", encoding="utf-8")
                records.append(
                    {
                        "name": name,
                        "bytes": path.stat().st_size,
                        "sha256": file_sha256(path),
                    }
                )
            write_json(
                entry / "cache_manifest.json",
                {
                    "schema_version": 2,
                    "role": identity["role"],
                    "cache_key": key,
                    "provider_run_id": "fixture",
                    "cache_key_input": key_input,
                    "identity": identity,
                    "files": records,
                },
            )
            command = (
                f". '{RUN_ARTIFACTS_PATH}'; "
                f"Test-RfReusableCacheEntry -Python '{Path(sys.executable)}' "
                f"-RepoRoot '{REPO_ROOT}' -WorkspaceRoot '{workspace}' "
                f"-ProjectId '{INTEGRATION_ID}' -CacheRoot '{cache_root}' "
                f"-CacheKey '{key}' -Role '{identity['role']}'; exit 0"
            )
            first = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", command],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("True", first.stdout)
            (entry / "frontend.pa0").write_text("changed\n", encoding="utf-8")
            second = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", command],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("False", second.stdout)
            self.assertFalse(entry.exists())

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
            result = subprocess.run(["pwsh", "-NoProfile", "-Command", command], check=True, capture_output=True, text=True)
            self.assertIn("False", result.stdout)
            self.assertTrue(entry.is_dir())

    def test_build_policy_keeps_official_test_build_publish_chain(self) -> None:
        runner = (RUN_ARTIFACTS_PATH.parent / "run_single_flight.ps1").read_text(encoding="utf-8")
        test_index = runner.index("Test-RfReusableCacheEntry -Python $python")
        gem2pa_index = runner.index("'--nogui','--noprompt','gem2pa'", test_index)
        publish_index = runner.index("Publish-RfVerifiedCacheEntry -Python $python", gem2pa_index)
        self.assertLess(test_index, gem2pa_index)
        self.assertLess(gem2pa_index, publish_index)

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
                text=True, capture_output=True,
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
        self.assertIn(
            "[Parameter(Mandatory)][string]$ExperimentId", public_param_block
        )
        self.assertIn("[string]$OutputDirectory = ''", public_param_block)
        self.assertIn("$campaignRunId = [string]$experimentRows[0].run_id", execute_source)
        self.assertIn("Select exactly one of ValidateOnly", execute_source)
        self.assertIn("OutputDirectory is accepted only for PrepareOnly", execute_source)
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
