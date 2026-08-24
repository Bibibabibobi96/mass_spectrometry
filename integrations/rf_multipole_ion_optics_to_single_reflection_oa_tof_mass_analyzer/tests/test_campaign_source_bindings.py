from __future__ import annotations

import json
import hashlib
from pathlib import Path
import tempfile
import unittest

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.refresh_campaign_source_bindings import (
    compile_campaign,
    expanded_campaign_semantic_sha256,
    is_fresh,
    write_campaign,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    _canonical_sha256,
    _derive_pulse_discovery_run_id,
)


class CampaignSourceBindingTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        repo = root / "simulation_repo"
        source = root / "artifacts/projects/source/runs/source_run"
        repo.mkdir()
        source.mkdir(parents=True)
        for name in ("run_manifest.json", "state.csv", "source.csv", "metadata.json"):
            (source / name).write_text(name + "\n", encoding="utf-8")
        campaign = repo / "campaign.json"
        campaign.write_text(json.dumps({
            "campaign_id": "fixture_campaign",
            "experiments": [{
                "run_id": "target_run",
                "experiment_id": "target_experiment",
                "source": {
                    "manifest": {"path": "artifacts/projects/source/runs/source_run/run_manifest.json", "sha256": "0" * 64},
                    "state": {"path": "artifacts/projects/source/runs/source_run/state.csv", "sha256": "0" * 64},
                    "particle_source": {"path": "artifacts/projects/source/runs/source_run/source.csv", "sha256": "0" * 64},
                    "metadata": {"path": "artifacts/projects/source/runs/source_run/metadata.json", "sha256": "0" * 64},
                },
            }],
        }, indent=2) + "\n", encoding="utf-8")
        return repo, campaign

    def _flat_fixture(self, root: Path) -> tuple[Path, Path]:
        repo, campaign = self._fixture(root)
        document = json.loads(campaign.read_text(encoding="utf-8"))
        shared = document["experiments"][0]
        document["experiments"] = {
            "shared": {
                key: value
                for key, value in shared.items()
                if key not in {"run_id", "experiment_id"}
            },
            "variation_axes": ["connection_profile_id"],
            "rows": [{
                "sequence": 1,
                "experiment_id": shared["experiment_id"],
                "run_id": shared["run_id"],
                "overrides": {},
            }],
        }
        campaign.write_text(
            json.dumps(document, indent=2) + "\n", encoding="utf-8"
        )
        return repo, campaign

    def _publish_receipt(
        self,
        repo: Path,
        campaign: Path,
        *,
        run_id: str | None = None,
        receipt_fields: dict[str, object] | None = None,
    ) -> Path:
        document = json.loads(campaign.read_text(encoding="utf-8-sig"))
        rendered = (
            json.dumps(document, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        run_id = run_id or document["experiments"][0]["run_id"]
        run = (
            repo.parent
            / "artifacts/projects/"
            "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
            "runs"
            / run_id
        )
        run.mkdir(parents=True, exist_ok=True)
        (run / "run_manifest.json").write_text("{}\n", encoding="utf-8")
        receipt = {
            "role": "integration_family_source_closure_execution_receipt",
            "integration_run_id": run_id,
            "campaign_path": campaign.relative_to(repo).as_posix(),
            "campaign_sha256": hashlib.sha256(rendered).hexdigest().upper(),
            "campaign_id": document["campaign_id"],
            "experiment_id": document["experiments"][0]["experiment_id"],
        }
        receipt.update(receipt_fields or {})
        (run / "execution_receipt.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
        )
        return run

    def _configure_automatic_pulse_row(self, campaign: Path) -> None:
        document = json.loads(campaign.read_text(encoding="utf-8-sig"))
        row = document["experiments"][0]
        row.update({
            "run_id": "20260819_002000__sim__cross__fixture-target__n100",
            "execution_strategy": "simion_single_flight",
        })
        campaign.write_text(
            json.dumps(document, indent=2) + "\n", encoding="utf-8"
        )

    def _publish_discovery_receipt(
        self,
        repo: Path,
        campaign: Path,
        *,
        run_id: str | None = None,
        receipt_overrides: dict[str, object] | None = None,
    ) -> Path:
        document = json.loads(campaign.read_text(encoding="utf-8-sig"))
        row = document["experiments"][0]
        parent_run_id = run_id or _derive_pulse_discovery_run_id(row["run_id"])
        run = (
            repo.parent
            / "artifacts"
            / "projects"
            / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"
            / "runs"
            / parent_run_id
        )
        run.mkdir(parents=True)
        plan_path = run / "composition_plan.json"
        plan_path.write_text(
            '{"pulse_timing_internal_stage":"pulse_timing_discovery"}\n',
            encoding="utf-8",
        )
        fields = {
            "experiment_row_sha256": _canonical_sha256(row),
            "execution_strategy": "simion_single_flight",
            "composition_plan_sha256": hashlib.sha256(
                plan_path.read_bytes()
            ).hexdigest().upper(),
        }
        fields.update(receipt_overrides or {})
        return self._publish_receipt(
            repo, campaign, run_id=parent_run_id, receipt_fields=fields
        )

    def test_refreshes_repository_and_artifact_identities(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, campaign = self._fixture(Path(directory))
            self.assertNotEqual(compile_campaign(repo, campaign), json.loads(campaign.read_text()))
            self.assertTrue(write_campaign(repo, campaign))
            self.assertTrue(is_fresh(repo, campaign))
            self.assertFalse(write_campaign(repo, campaign))

    def test_execution_controls_are_excluded_from_campaign_semantic_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, campaign = self._fixture(Path(directory))
            document = json.loads(campaign.read_text(encoding="utf-8"))
            baseline = expanded_campaign_semantic_sha256(document)
            document["execution_policy"] = {
                "path": "config/legacy-policy.json", "sha256": "A" * 64,
            }
            document["experiments"][0]["single_flight_batch_count"] = 8
            document["experiments"][0]["single_flight_batch_memory_policy"] = {
                "policy_id": "auto_memory_bound_from_observed_profile_v2",
                "reserve_available_memory_bytes": 1,
                "memory_safety_numerator": 105,
                "memory_safety_denominator": 100,
                "cpu_cores_per_batch": 2,
                "reserve_cpu_cores": 1,
            }
            self.assertEqual(expanded_campaign_semantic_sha256(document), baseline)

    def test_flat_campaign_refreshes_shared_source_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, campaign = self._flat_fixture(Path(directory))
            self.assertTrue(write_campaign(repo, campaign))
            self.assertTrue(is_fresh(repo, campaign))

            source = repo.parent / "artifacts/projects/source/runs/source_run/state.csv"
            source.write_text("changed state\n", encoding="utf-8")
            self.assertFalse(is_fresh(repo, campaign))
            self.assertTrue(write_campaign(repo, campaign))

            document = json.loads(campaign.read_text(encoding="utf-8"))
            shared_state = document["experiments"]["shared"]["source"]["state"]
            self.assertNotEqual(shared_state["sha256"], "0" * 64)
            self.assertTrue(is_fresh(repo, campaign))

    def test_flat_authoring_refreshes_shared_and_row_source_bindings(self) -> None:
        for source_location in ("shared", "overrides"):
            with self.subTest(source_location=source_location), tempfile.TemporaryDirectory() as directory:
                repo, campaign = self._fixture(Path(directory))
                document = json.loads(campaign.read_text(encoding="utf-8"))
                row = document["experiments"][0]
                source = row.pop("source")
                shared = {key: value for key, value in row.items() if key not in {
                    "sequence", "experiment_id", "run_id"
                }}
                overrides = {}
                if source_location == "shared":
                    shared["source"] = source
                else:
                    overrides["source"] = source
                document["experiments"] = {
                    "shared": shared,
                    "variation_axes": ["source"],
                    "rows": [{
                        "sequence": 1,
                        "experiment_id": document["experiments"][0]["experiment_id"],
                        "run_id": document["experiments"][0]["run_id"],
                        "overrides": overrides,
                    }],
                }
                campaign.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

                self.assertTrue(write_campaign(repo, campaign))
                self.assertTrue(is_fresh(repo, campaign))
                self.assertIsInstance(
                    json.loads(campaign.read_text(encoding="utf-8"))["experiments"], dict
                )
                (repo.parent / "artifacts/projects/source/runs/source_run/state.csv").write_text(
                    "changed\n", encoding="utf-8"
                )
                self.assertFalse(is_fresh(repo, campaign))
                self.assertTrue(write_campaign(repo, campaign))
                self.assertTrue(is_fresh(repo, campaign))

    def test_refuses_to_rebind_a_published_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, campaign = self._fixture(Path(directory))
            manifest = (
                repo.parent / "artifacts/projects/"
                "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/"
                "runs/target_run/run_manifest.json"
            )
            manifest.parent.mkdir(parents=True)
            manifest.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "immutable"):
                write_campaign(repo, campaign)

    def test_finalized_failed_parent_allows_binding_refresh_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, campaign = self._fixture(Path(directory))
            runs = (
                repo.parent / "artifacts/projects/"
                "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs"
            )

            def record(path: Path) -> dict[str, object]:
                return {
                    "path": str(path), "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
                }

            failed_parent = runs / "target_run"
            failed_parent.mkdir(parents=True)
            failed_config = failed_parent / "run_config.json"
            failed_config.write_text("{}\n", encoding="utf-8")
            failed_manifest = failed_parent / "run_manifest.json"
            failed_manifest.write_text(json.dumps({
                "role": "simulation_run_manifest", "status": "failed",
                "run_config": record(failed_config), "inputs": {}, "outputs": [],
            }), encoding="utf-8")
            receipt = runs / "child__r01" / "results" / "receipt.json"
            receipt.parent.mkdir(parents=True)
            receipt.write_text(json.dumps({
                "role": "rf_oatof_completed_single_flight_analysis_recovery_receipt",
                "status": "success", "solver_reexecuted": False,
                "source_failed_parent_manifest_sha256": hashlib.sha256(failed_manifest.read_bytes()).hexdigest().upper(),
                "campaign": {"experiment_id": "target_experiment"},
            }), encoding="utf-8")
            child = runs / "child__r01"
            child_config = child / "run_config.json"
            child_config.write_text(json.dumps({"inputs": {"failed_parent_manifest": str(failed_manifest)}}), encoding="utf-8")
            child_manifest = child / "run_manifest.json"
            child_manifest.write_text(json.dumps({
                "status": "success", "mode": "rf_to_oatof_simion_single_flight_analysis_recovery",
                "run_config": record(child_config), "inputs": {"failed_parent_manifest": record(failed_manifest)},
            }), encoding="utf-8")
            recovery_parent = runs / "target_run__r01"
            recovery_parent.mkdir()
            summary = recovery_parent / "summary.json"
            summary.write_text("{}\n", encoding="utf-8")
            parent_config = recovery_parent / "run_config.json"
            parent_config.write_text(json.dumps({"inputs": {
                "failed_parent_manifest": str(failed_manifest),
                "recovered_child_manifest": str(child_manifest),
                "recovery_receipt": str(receipt),
            }}), encoding="utf-8")
            (recovery_parent / "run_manifest.json").write_text(json.dumps({
                "role": "simulation_run_manifest", "status": "success",
                "mode": "multipole_family_source_closure_analysis_recovery",
                "run_config": record(parent_config),
                "inputs": {
                    "failed_parent_manifest": record(failed_manifest),
                    "recovered_child_manifest": record(child_manifest),
                    "recovery_receipt": record(receipt),
                }, "outputs": [record(summary)],
            }), encoding="utf-8")

            self.assertTrue(write_campaign(repo, campaign))
            self.assertTrue(is_fresh(repo, campaign))

    def test_normalizes_only_campaign_bytes_even_when_published(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, campaign = self._fixture(Path(directory))
            self.assertTrue(write_campaign(repo, campaign))
            canonical = campaign.read_bytes()
            self._publish_receipt(repo, campaign)
            campaign.write_bytes(canonical.replace(b"\n", b"\r\n"))

            self.assertFalse(is_fresh(repo, campaign))
            self.assertTrue(write_campaign(repo, campaign))
            self.assertEqual(campaign.read_bytes(), canonical)
            self.assertTrue(is_fresh(repo, campaign))

    def test_refuses_published_nonbinding_semantic_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, campaign = self._fixture(Path(directory))
            self.assertTrue(write_campaign(repo, campaign))
            self._publish_receipt(repo, campaign)
            document = json.loads(campaign.read_text(encoding="utf-8"))
            document["claim_limit"] = "mutated"
            campaign.write_bytes(
                (json.dumps(document, indent=2) + "\n").encode("utf-8")
            )

            self.assertFalse(is_fresh(repo, campaign))
            with self.assertRaisesRegex(ValueError, "identity differs"):
                write_campaign(repo, campaign)

    def test_published_receipt_accepts_only_an_equivalent_flat_authoring_successor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, campaign = self._fixture(Path(directory))
            fixture = json.loads(campaign.read_text(encoding="utf-8"))
            fixture["experiments"][0]["sequence"] = 1
            campaign.write_text(
                json.dumps(fixture, indent=2) + "\n", encoding="utf-8"
            )
            self.assertTrue(write_campaign(repo, campaign))
            original = json.loads(campaign.read_text(encoding="utf-8"))
            original_sha256 = hashlib.sha256(campaign.read_bytes()).hexdigest().upper()
            semantic_sha256 = expanded_campaign_semantic_sha256(original)
            self._publish_receipt(repo, campaign)
            row = original["experiments"][0]
            original["experiments"] = {
                "shared": {
                    key: value
                    for key, value in row.items()
                    if key not in {"sequence", "experiment_id", "run_id"}
                },
                "variation_axes": ["connection_profile_id"],
                "rows": [{
                    "sequence": 1,
                    "experiment_id": row["experiment_id"],
                    "run_id": row["run_id"],
                    "overrides": {},
                }],
            }
            original["published_authoring_identity"] = {
                "legacy_campaign_sha256": original_sha256,
                "semantic_sha256": semantic_sha256,
            }
            campaign.write_text(
                json.dumps(original, indent=2) + "\n", encoding="utf-8"
            )

            self.assertEqual(
                expanded_campaign_semantic_sha256(original), semantic_sha256
            )
            self.assertFalse(is_fresh(repo, campaign))
            self.assertTrue(write_campaign(repo, campaign))
            self.assertTrue(is_fresh(repo, campaign))
            self.assertFalse(write_campaign(repo, campaign))

            original["claim_limit"] = "semantic mutation"
            campaign.write_text(
                json.dumps(original, indent=2) + "\n", encoding="utf-8"
            )
            self.assertFalse(is_fresh(repo, campaign))
            with self.assertRaisesRegex(ValueError, "semantic projection differs"):
                write_campaign(repo, campaign)

    def test_refuses_published_run_id_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, campaign = self._fixture(Path(directory))
            self.assertTrue(write_campaign(repo, campaign))
            self._publish_receipt(repo, campaign)
            document = json.loads(campaign.read_text(encoding="utf-8"))
            document["experiments"][0]["run_id"] = "replacement_run"
            campaign.write_bytes(
                (json.dumps(document, indent=2) + "\n").encode("utf-8")
            )

            self.assertFalse(is_fresh(repo, campaign))
            with self.assertRaisesRegex(ValueError, "identity differs"):
                write_campaign(repo, campaign)

    def test_refuses_published_experiment_deletion_or_reordering(self) -> None:
        for mutation in ("deletion", "reordering"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                repo, campaign = self._fixture(Path(directory))
                document = json.loads(campaign.read_text(encoding="utf-8"))
                second = json.loads(json.dumps(document["experiments"][0]))
                second["run_id"] = "second_run"
                second["experiment_id"] = "second_experiment"
                document["experiments"].append(second)
                campaign.write_bytes(
                    (json.dumps(document, indent=2) + "\n").encode("utf-8")
                )
                self.assertTrue(write_campaign(repo, campaign))
                self._publish_receipt(repo, campaign)
                document = json.loads(campaign.read_text(encoding="utf-8"))
                if mutation == "deletion":
                    document["experiments"].pop()
                else:
                    document["experiments"].reverse()
                campaign.write_bytes(
                    (json.dumps(document, indent=2) + "\n").encode("utf-8")
                )

                self.assertFalse(is_fresh(repo, campaign))
                with self.assertRaisesRegex(ValueError, "identity differs"):
                    write_campaign(repo, campaign)

    def test_target_and_machine_bound_discovery_receipts_are_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, campaign = self._fixture(Path(directory))
            self._configure_automatic_pulse_row(campaign)
            self.assertTrue(write_campaign(repo, campaign))
            self._publish_receipt(repo, campaign)
            self._publish_discovery_receipt(repo, campaign)

            self.assertTrue(is_fresh(repo, campaign))
            self.assertFalse(write_campaign(repo, campaign))

    def test_refuses_unknown_or_forged_discovery_receipt(self) -> None:
        cases = (
            {
                "run_id": (
                    "20260819_002000__sim__cross__foreign-pulse-discovery__n100"
                ),
            },
            {"receipt_overrides": {"composition_plan_sha256": "0" * 64}},
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                repo, campaign = self._fixture(Path(directory))
                self._configure_automatic_pulse_row(campaign)
                self.assertTrue(write_campaign(repo, campaign))
                self._publish_discovery_receipt(repo, campaign, **case)

                self.assertFalse(is_fresh(repo, campaign))
                with self.assertRaisesRegex(ValueError, "identity differs"):
                    write_campaign(repo, campaign)

    def test_public_workflow_requires_fresh_source_bindings(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / "workflows/family_source_closure/execute.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertIn("refresh_campaign_source_bindings", workflow)
        self.assertIn("--campaign $campaignPath --check", workflow)


if __name__ == "__main__":
    unittest.main()
