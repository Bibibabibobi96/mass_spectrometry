from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from common.contracts.capacity_protection import create_capacity_protection_lease
from common.contracts.capacity_ledger import initialize_capacity_ledger
from common.contracts.solver_review_retirement import (
    LEGACY_INITIALIZATION_SUMMARY,
    RetirementError,
    apply_retirement,
    main,
    plan_retirement,
    verify_retirement,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class SolverReviewRetirementTest(unittest.TestCase):
    compatibility_roles = (
        "candidate_contract", "resolved_prototype_contract", "analyzer_pa0",
        "accelerator_pa0", "detector_pa", "three_instance_seed",
    )
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.artifacts = self.root / "artifacts"
        self.repo.mkdir()
        self.runs = self.artifacts / "projects" / "p" / "runs"
        self.target = self._run("20260101_000000__build__simion__old", "2026-01-01T00:00:00Z")
        self.replacement = self._run("20260102_000000__build__simion__new", "2026-01-02T00:00:00Z")
        initialize_capacity_ledger(self.artifacts, objects=[])

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_host_lease_wrapper_forwards_role_mappings(self) -> None:
        wrapper = Path(__file__).with_name("invoke_solver_review_retirement.ps1")
        source = wrapper.read_text(encoding="utf-8-sig")
        self.assertIn("[string[]]$CompatibilityInputRoleMaps=@()", source)
        self.assertIn("$CompatibilityInputRoles.Count -eq 0", source)
        self.assertIn("$CompatibilityInputRoleMaps.Count -eq 0", source)
        self.assertIn("'--compatibility-input-role-map',$mapping", source)

    def _run(self, run_id: str, recorded: str, *, status: str = "success") -> Path:
        run = self.runs / run_id
        simion = run / "simion"
        simion.mkdir(parents=True, exist_ok=True)
        roles = {
            "candidate_contract": run / "candidate.json",
            "resolved_prototype_contract": run / "resolved.json",
            "analyzer_pa0": simion / "analyzer.pa0",
            "accelerator_pa0": simion / "accelerator.pa0",
            "detector_pa": simion / "detector.pa#",
            "three_instance_seed": simion / "seed.iob",
        }
        for name, path in roles.items():
            path.write_bytes(b"native" if path.suffix.lower().startswith(".pa") else name.encode())
        config = {"schema_version": 2, "run_id": run_id, "project": "p", "mode": "three_component_candidate_iob_assembly",
                  "inputs": {name: str(path) for name, path in roles.items()}, "formal_gate_passed": False,
                  "artifact_retention": {"policy_version": 1, "class": "solver_review", "reason": "GUI review"}}
        summary = {"run_id": run_id, "status": status}
        for name, value in (("run_config.json", config), ("summary.json", summary)):
            (run / name).write_text(json.dumps(value), encoding="utf-8")
        inputs = {name: {"path": str(path), "exists": True, "bytes": path.stat().st_size, "sha256": _sha(path)} for name, path in roles.items()}
        manifest = {"schema_version": 2, "run_id": run_id, "project": "p", "mode": config["mode"], "status": status,
                    "recorded_at_utc": recorded, "run_config": {"path": str(run / 'run_config.json'), "exists": True,
                    "bytes": (run / 'run_config.json').stat().st_size, "sha256": _sha(run / 'run_config.json')},
                    "inputs": inputs, "outputs": [{"path": str(run / 'summary.json'), "exists": True,
                    "bytes": (run / 'summary.json').stat().st_size, "sha256": _sha(run / 'summary.json'), "retention_role": "required_evidence"}],
                    "formal_eligible": False, "artifact_retention": config["artifact_retention"]}
        (run / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return run

    def _set_status(self, run: Path, status: str) -> None:
        summary_path = run / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["status"] = status
        summary_path.write_text(json.dumps(summary), encoding="utf-8")
        manifest_path = run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = status
        summary_record = next(
            item for item in manifest["outputs"]
            if Path(item["path"]).name == "summary.json"
        )
        summary_record["bytes"] = summary_path.stat().st_size
        summary_record["sha256"] = _sha(summary_path)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def _make_real_legacy_initialization_fixture(self, run: Path) -> None:
        """Match the historical success-manifest/unbound-init-summary shape."""

        (run / "summary.json").write_text(
            json.dumps(LEGACY_INITIALIZATION_SUMMARY), encoding="utf-8"
        )
        manifest_path = run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["outputs"] = [
            record
            for record in manifest["outputs"]
            if Path(record["path"]).name != "summary.json"
        ]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def _rename_input_role(self, run: Path, old: str, new: str) -> None:
        config_path = run / "run_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["inputs"][new] = config["inputs"].pop(old)
        config_path.write_text(json.dumps(config), encoding="utf-8")
        manifest_path = run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["inputs"][new] = manifest["inputs"].pop(old)
        manifest["run_config"]["bytes"] = config_path.stat().st_size
        manifest["run_config"]["sha256"] = _sha(config_path)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def _rewrite_input_identity(self, run: Path, role: str, payload: bytes) -> None:
        manifest_path = run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        input_path = Path(manifest["inputs"][role]["path"])
        input_path.write_bytes(payload)
        manifest["inputs"][role]["bytes"] = input_path.stat().st_size
        manifest["inputs"][role]["sha256"] = _sha(input_path)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def _add_config_inputs(self, run: Path, values: dict[str, object]) -> None:
        config_path = run / "run_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["inputs"].update(values)
        config_path.write_text(json.dumps(config), encoding="utf-8")
        manifest_path = run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["run_config"]["bytes"] = config_path.stat().st_size
        manifest["run_config"]["sha256"] = _sha(config_path)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def _replace_config_input(self, run: Path, role: str, value: object) -> None:
        config_path = run / "run_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["inputs"][role] = value
        config_path.write_text(json.dumps(config), encoding="utf-8")
        manifest_path = run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["run_config"]["bytes"] = config_path.stat().st_size
        manifest["run_config"]["sha256"] = _sha(config_path)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_plan_apply_and_retired_verification(self, _scan: mock.Mock) -> None:
        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "new successful GUI package supersedes old", self.compatibility_roles,
        )
        self.assertGreater(plan["bytes_to_release"], 0)
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            receipt = apply_retirement(plan)
        self.assertEqual(receipt["lifecycle_status"], "superseded_payload_retired")
        self.assertEqual(verify_retirement(self.target)["status"], "PASS")
        self.assertTrue((self.target / "run_manifest.json").is_file())
        self.assertTrue((self.target / "simion" / "seed.iob").is_file())
        self.assertFalse((self.target / "simion" / "analyzer.pa0").exists())

        receipt_path = self.target / "solver_review_retirement_receipt.json"
        legacy_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        legacy_receipt.pop("target_terminal_status")
        receipt_path.write_text(json.dumps(legacy_receipt), encoding="utf-8")
        self.assertEqual(
            verify_retirement(self.target)["target_terminal_status"], "success"
        )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_real_legacy_initialization_summary_can_use_superseded_entrypoint(
        self, _scan: mock.Mock,
    ) -> None:
        self._make_real_legacy_initialization_fixture(self.target)

        plan = plan_retirement(
            self.artifacts,
            self.repo,
            self.target,
            self.replacement,
            "new verified package supersedes legacy initialized solver review",
            self.compatibility_roles,
        )

        self.assertTrue(plan["target_legacy_initialization_summary"])
        self.assertGreater(plan["bytes_to_release"], 0)
        self.assertIn(
            "summary.json", {item["path"] for item in plan["preserved_files"]}
        )
        with mock.patch.dict(
            os.environ,
            {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"},
        ):
            receipt = apply_retirement(plan)
        self.assertTrue(receipt["target_legacy_initialization_summary"])
        self.assertEqual(verify_retirement(self.target)["status"], "PASS")
        self.assertEqual(
            json.loads((self.target / "summary.json").read_text(encoding="utf-8")),
            LEGACY_INITIALIZATION_SUMMARY,
        )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_legacy_initialization_summary_requires_exact_template(
        self, _scan: mock.Mock,
    ) -> None:
        mutations = {
            "extra_field": lambda value: value.update(unexpected=True),
            "reason_text": lambda value: value.update(
                reason=f"{value['reason']} "
            ),
            "role": lambda value: value.update(role="run_package_checkpoint_summary"),
            "schema": lambda value: value.update(schema_version=2),
            "running": lambda value: value.update(status="running"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                self._run(
                    self.target.name, "2026-01-01T00:00:00Z"
                )
                self._make_real_legacy_initialization_fixture(self.target)
                summary = dict(LEGACY_INITIALIZATION_SUMMARY)
                mutate(summary)
                (self.target / "summary.json").write_text(
                    json.dumps(summary), encoding="utf-8"
                )

                with self.assertRaisesRegex(
                    RetirementError, "target is not a complete"
                ):
                    plan_retirement(
                        self.artifacts,
                        self.repo,
                        self.target,
                        self.replacement,
                        "near-match is not legacy authority",
                        self.compatibility_roles,
                    )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_legacy_exception_does_not_admit_replacement_or_non_solver_review(
        self, _scan: mock.Mock,
    ) -> None:
        self._make_real_legacy_initialization_fixture(self.replacement)
        with self.assertRaisesRegex(
            RetirementError, "replacement is not a complete success"
        ):
            plan_retirement(
                self.artifacts,
                self.repo,
                self.target,
                self.replacement,
                "replacement must remain complete",
                self.compatibility_roles,
            )

        self._run(
            self.replacement.name, "2026-01-02T00:00:00Z"
        )
        self._make_real_legacy_initialization_fixture(self.target)
        config_path = self.target / "run_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["artifact_retention"] = {
            "policy_version": 1,
            "class": "compact",
            "reason": None,
        }
        config_path.write_text(json.dumps(config), encoding="utf-8")
        manifest_path = self.target / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["run_config"]["bytes"] = config_path.stat().st_size
        manifest["run_config"]["sha256"] = _sha(config_path)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(RetirementError, "not solver_review"):
            plan_retirement(
                self.artifacts,
                self.repo,
                self.target,
                self.replacement,
                "compact target is not eligible",
                self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_checkpoint_manifest_is_not_terminalized_from_success_summary(
        self, _scan: mock.Mock,
    ) -> None:
        manifest_path = self.target / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"] = "checkpoint"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaisesRegex(RetirementError, "target is not a complete"):
            plan_retirement(
                self.artifacts,
                self.repo,
                self.target,
                self.replacement,
                "summary cannot terminalize a checkpoint manifest",
                self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_active_lease_blocks_legacy_initialization_target(
        self, _scan: mock.Mock,
    ) -> None:
        self._make_real_legacy_initialization_fixture(self.target)
        create_capacity_protection_lease(
            self.artifacts,
            lease_id="active-producer-consumer-chain",
            owner="test",
            ttl_seconds=3600,
            protected_paths=[self.target],
        )

        with self.assertRaisesRegex(RetirementError, "active capacity protection lease"):
            plan_retirement(
                self.artifacts,
                self.repo,
                self.target,
                self.replacement,
                "active chain must remain protected",
                self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_failed_target_with_identity_equal_role_mapping_can_be_retired(
        self, _scan: mock.Mock,
    ) -> None:
        self._set_status(self.target, "failed")
        self._rename_input_role(
            self.target, "candidate_contract", "legacy_candidate_contract"
        )
        self._add_config_inputs(self.replacement, {
            "optional_input": None,
            "grouped_inputs": [
                str(self.replacement / "candidate.json"),
                str(self.replacement / "resolved.json"),
            ],
        })
        self._replace_config_input(
            self.replacement, "analyzer_pa0",
            str(self.root / "removed-short-alias" / "simion" / "analyzer.pa0"),
        )
        roles = tuple(
            role for role in self.compatibility_roles if role != "candidate_contract"
        )

        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "new successful GUI package supersedes failed legacy package", roles,
            (("legacy_candidate_contract", "candidate_contract"),),
        )

        self.assertEqual(plan["target_terminal_status"], "failed")
        self.assertEqual(
            plan["compatibility_checks"]["verified_input_role_mappings"][0][
                "target_role"
            ],
            "legacy_candidate_contract",
        )
        with mock.patch.dict(
            os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}
        ):
            receipt = apply_retirement(plan)
        self.assertEqual(receipt["target_terminal_status"], "failed")
        verification = verify_retirement(self.target)
        self.assertEqual(verification["target_terminal_status"], "failed")

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_unbound_configured_input_collection_is_rejected(self, _scan: mock.Mock) -> None:
        self._add_config_inputs(
            self.replacement,
            {"grouped_inputs": [str(self.replacement / "unrecorded-input.json")]},
        )

        with self.assertRaisesRegex(RetirementError, "input collection"):
            plan_retirement(
                self.artifacts, self.repo, self.target, self.replacement,
                "all configured input members remain bound", self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_short_alias_suffix_mismatch_is_rejected(self, _scan: mock.Mock) -> None:
        self._replace_config_input(
            self.replacement, "analyzer_pa0",
            str(self.root / "removed-short-alias" / "simion" / "other.pa0"),
        )

        with self.assertRaisesRegex(RetirementError, "configured input: analyzer_pa0"):
            plan_retirement(
                self.artifacts, self.repo, self.target, self.replacement,
                "short alias must map exactly", self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_failed_replacement_is_not_accepted(self, _scan: mock.Mock) -> None:
        self._set_status(self.target, "failed")
        self._set_status(self.replacement, "failed")

        with self.assertRaisesRegex(RetirementError, "replacement is not a complete success"):
            plan_retirement(
                self.artifacts, self.repo, self.target, self.replacement,
                "failed replacement is not authoritative", self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_role_mapping_requires_roles_at_both_ends(self, _scan: mock.Mock) -> None:
        self._set_status(self.target, "failed")

        with self.assertRaisesRegex(RetirementError, "mapping roles missing"):
            plan_retirement(
                self.artifacts, self.repo, self.target, self.replacement,
                "legacy roles must be explicit", (),
                (("missing_legacy_role", "candidate_contract"),),
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_role_mapping_requires_equal_manifest_identity(self, _scan: mock.Mock) -> None:
        self._set_status(self.target, "failed")
        self._rename_input_role(
            self.target, "candidate_contract", "legacy_candidate_contract"
        )
        replacement_input = self.replacement / "candidate.json"
        original = replacement_input.read_bytes()
        for payload in (b"x" * len(original), original + b"-different-size"):
            with self.subTest(payload_size=len(payload)):
                self._rewrite_input_identity(
                    self.replacement, "candidate_contract", payload
                )
                with self.assertRaisesRegex(RetirementError, "mapping identity differs"):
                    plan_retirement(
                        self.artifacts, self.repo, self.target, self.replacement,
                        "identity drift must fail closed", (),
                        (("legacy_candidate_contract", "candidate_contract"),),
                    )
                self._rewrite_input_identity(
                    self.replacement, "candidate_contract", original
                )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_role_mappings_must_be_one_to_one(self, _scan: mock.Mock) -> None:
        for mappings in (
            (
                ("candidate_contract", "candidate_contract"),
                ("candidate_contract", "resolved_prototype_contract"),
            ),
            (
                ("candidate_contract", "candidate_contract"),
                ("resolved_prototype_contract", "candidate_contract"),
            ),
        ):
            with self.subTest(mappings=mappings), self.assertRaisesRegex(
                RetirementError, "one-to-one"
            ):
                plan_retirement(
                    self.artifacts, self.repo, self.target, self.replacement,
                    "ambiguous mappings must fail closed", (), mappings,
                )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_cli_accepts_repeated_input_role_mappings(self, _scan: mock.Mock) -> None:
        self._set_status(self.target, "failed")
        self._rename_input_role(
            self.target, "candidate_contract", "legacy_candidate_contract"
        )
        output = io.StringIO()

        with redirect_stdout(output):
            status = main([
                "--artifact-root", str(self.artifacts),
                "--repository-root", str(self.repo),
                "--target-run", str(self.target),
                "--replacement-run", str(self.replacement),
                "--compatibility-assertion", "explicit legacy role migration",
                # Existing lease-owning PowerShell wrapper forwards mappings
                # through this older repeatable switch.
                "--compatibility-input-role",
                "legacy_candidate_contract=candidate_contract",
                "--compatibility-input-role-map",
                "analyzer_pa0=analyzer_pa0",
            ])

        self.assertEqual(status, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["target_terminal_status"], "failed")
        self.assertEqual(
            len(result["compatibility_checks"]["verified_input_role_mappings"]), 2
        )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=["docs/x.md"])
    def test_historical_document_reference_is_audited_not_a_heavy_dependency(
        self, _scan: mock.Mock,
    ) -> None:
        self._set_status(self.target, "failed")
        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "compatible", self.compatibility_roles,
        )
        self.assertEqual(plan["historical_document_references"], ["docs/x.md"])

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_capacity_protection_lease_blocks_failed_target(self, _scan: mock.Mock) -> None:
        self._set_status(self.target, "failed")
        create_capacity_protection_lease(
            self.artifacts, lease_id="protected-failed-target", owner="test",
            ttl_seconds=3600, protected_paths=[self.target],
        )

        with self.assertRaisesRegex(RetirementError, "active capacity protection lease"):
            plan_retirement(
                self.artifacts, self.repo, self.target, self.replacement,
                "protected targets remain immutable", self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_apply_rechecks_new_capacity_protection_lease(self, _scan: mock.Mock) -> None:
        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "lease changes must be rechecked", self.compatibility_roles,
        )
        create_capacity_protection_lease(
            self.artifacts, lease_id="late-protection", owner="test",
            ttl_seconds=3600, protected_paths=[self.target],
        )

        with mock.patch.dict(
            os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}
        ), self.assertRaisesRegex(RetirementError, "gained an active capacity"):
            apply_retirement(plan)
        self.assertFalse((self.target / "solver_review_retirement_receipt.json").exists())
        self.assertTrue((self.target / "simion" / "analyzer.pa0").is_file())

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_apply_rechecks_new_downstream_reference(self, _scan: mock.Mock) -> None:
        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "references must be rechecked", self.compatibility_roles,
        )
        downstream = self.runs / "20260103_000000__analysis__python__late-consumer"
        downstream.mkdir(parents=True)
        (downstream / "run_config.json").write_text(
            json.dumps({"source_run": self.target.name}), encoding="utf-8"
        )

        with mock.patch.dict(
            os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}
        ), self.assertRaisesRegex(RetirementError, "gained active references"):
            apply_retirement(plan)
        self.assertFalse((self.target / "solver_review_retirement_receipt.json").exists())
        self.assertTrue((self.target / "simion" / "analyzer.pa0").is_file())

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_apply_audits_late_terminal_downstream_reference_without_blocking(
        self, _scan: mock.Mock,
    ) -> None:
        plan = plan_retirement(
            self.artifacts,
            self.repo,
            self.target,
            self.replacement,
            "terminal references remain historical",
            self.compatibility_roles,
        )
        downstream = self.runs / "20260103_000000__analysis__python__late-history"
        downstream.mkdir(parents=True)
        config_path = downstream / "run_config.json"
        config_path.write_text(
            json.dumps({"source_run": str(self.target)}), encoding="utf-8"
        )
        (downstream / "run_manifest.json").write_text(
            json.dumps({"run_id": downstream.name, "status": "failed"}),
            encoding="utf-8",
        )

        with mock.patch.dict(
            os.environ,
            {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"},
        ):
            receipt = apply_retirement(plan)

        self.assertEqual(
            receipt["apply_historical_downstream_references"][0][
                "run_config_path"
            ],
            str(config_path),
        )
        self.assertFalse((self.target / "simion" / "analyzer.pa0").exists())

    def test_apply_records_new_historical_document_reference_without_blocking(self) -> None:
        with mock.patch(
            "common.contracts.solver_review_retirement._git_document_references",
            return_value=[],
        ) as scan:
            plan = plan_retirement(
                self.artifacts, self.repo, self.target, self.replacement,
                "document references must be rechecked", self.compatibility_roles,
            )
            scan.return_value = ["docs/new-reference.md"]
            with mock.patch.dict(
                os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}
            ):
                receipt = apply_retirement(plan)
        self.assertEqual(
            receipt["apply_historical_document_references"],
            ["docs/new-reference.md"],
        )
        self.assertFalse((self.target / "simion" / "analyzer.pa0").exists())

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_downstream_manifest_reference_preserves_light_evidence_only(self, _scan: mock.Mock) -> None:
        self._set_status(self.target, "failed")
        downstream = self.runs / "20260103_000000__analysis__python__consumer"
        downstream.mkdir(parents=True)
        (downstream / "run_config.json").write_text(
            json.dumps(
                {
                    "inputs": {
                        "source_manifest": str(self.target / "run_manifest.json")
                    }
                }
            ),
            encoding="utf-8",
        )
        (downstream / "run_manifest.json").write_text(
            json.dumps({"run_id": downstream.name, "status": "checkpoint"}),
            encoding="utf-8",
        )

        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "referenced manifest remains immutable", self.compatibility_roles,
        )
        self.assertEqual(
            plan["active_preserved_file_references"][0]["path"],
            "run_manifest.json",
        )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_active_reference_to_preserved_light_file_does_not_pin_heavy_payload(
        self, _scan: mock.Mock,
    ) -> None:
        downstream = self.runs / "20260103_000000__analysis__python__light-consumer"
        downstream.mkdir(parents=True)
        (downstream / "run_config.json").write_text(
            json.dumps({"source_summary": str(self.target / "summary.json")}),
            encoding="utf-8",
        )
        (downstream / "run_manifest.json").write_text(
            json.dumps({"run_id": downstream.name, "status": "checkpoint"}),
            encoding="utf-8",
        )

        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "preserved evidence remains available", self.compatibility_roles,
        )

        self.assertEqual(plan["active_preserved_file_references"][0]["path"], "summary.json")

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_active_reference_to_nested_heavy_file_blocks_retirement(
        self, _scan: mock.Mock,
    ) -> None:
        downstream = self.runs / "20260103_000000__analysis__python__payload-consumer"
        downstream.mkdir(parents=True)
        (downstream / "run_config.json").write_text(
            json.dumps({"source_pa": str(self.target / "simion" / "analyzer.pa0")}),
            encoding="utf-8",
        )
        (downstream / "run_manifest.json").write_text(
            json.dumps({"run_id": downstream.name, "status": "checkpoint"}),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(RetirementError, "active references"):
            plan_retirement(
                self.artifacts, self.repo, self.target, self.replacement,
                "active payload cannot retire", self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_terminal_downstream_reference_is_historical_audit_not_blocker(
        self, _scan: mock.Mock,
    ) -> None:
        downstream = self.runs / "20260103_000000__analysis__python__historical"
        downstream.mkdir(parents=True)
        config_path = downstream / "run_config.json"
        config_path.write_text(
            json.dumps({"source_run": self.target.name}), encoding="utf-8"
        )
        (downstream / "run_manifest.json").write_text(
            json.dumps({"run_id": downstream.name, "status": "success"}),
            encoding="utf-8",
        )

        plan = plan_retirement(
            self.artifacts,
            self.repo,
            self.target,
            self.replacement,
            "terminal consumers are historical evidence",
            self.compatibility_roles,
        )

        self.assertEqual(
            plan["historical_downstream_references"],
            [
                {
                    "run_config_path": str(config_path),
                    "manifest_status": "success",
                    "reason": "configured_target_run_dependency",
                }
            ],
        )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_unreadable_active_run_config_blocks_conservatively(
        self, _scan: mock.Mock,
    ) -> None:
        downstream = self.runs / "20260103_000000__analysis__python__uncertain"
        downstream.mkdir(parents=True)
        (downstream / "run_config.json").write_text("{", encoding="utf-8")
        (downstream / "run_manifest.json").write_text(
            json.dumps({"run_id": downstream.name, "status": "checkpoint"}),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            RetirementError, "run_config_unreadable_reference_uncertain"
        ):
            plan_retirement(
                self.artifacts,
                self.repo,
                self.target,
                self.replacement,
                "uncertain active consumers block",
                self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_corrupt_active_run_config_is_audit_only_when_manifest_identity_differs(
        self, _scan: mock.Mock,
    ) -> None:
        downstream = self.runs / "20260103_000000__analysis__python__corrupt-config"
        downstream.mkdir(parents=True)
        config_path = downstream / "run_config.json"
        original = json.dumps(
            {"source_pa": str(self.target / "simion" / "analyzer.pa0")},
            separators=(",", ":"),
        ).encode()
        config_path.write_bytes(original)
        manifest = {
            "run_id": downstream.name,
            "status": "checkpoint",
            "run_config": {
                "path": str(config_path),
                "exists": True,
                "bytes": len(original),
                "sha256": hashlib.sha256(original).hexdigest().upper(),
            },
        }
        (downstream / "run_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        # Simulate the observed all-zero/corrupt file while retaining the
        # manifest's last-known identity.
        config_path.write_bytes(b"\x00" * len(original))

        plan = plan_retirement(
            self.artifacts,
            self.repo,
            self.target,
            self.replacement,
            "corrupt downstream config is not usable evidence of a consumer",
            self.compatibility_roles,
        )

        self.assertEqual(plan["active_preserved_file_references"], [])
        self.assertEqual(
            plan["corrupt_run_config_reference_unavailable"][0]["reason"],
            "corrupt_run_config_reference_unavailable",
        )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_unreadable_active_run_config_with_matching_manifest_identity_still_blocks(
        self, _scan: mock.Mock,
    ) -> None:
        downstream = self.runs / "20260103_000000__analysis__python__matching-invalid-config"
        downstream.mkdir(parents=True)
        config_path = downstream / "run_config.json"
        invalid = b"{"
        config_path.write_bytes(invalid)
        manifest = {
            "run_id": downstream.name,
            "status": "checkpoint",
            "run_config": {
                "path": str(config_path),
                "exists": True,
                "bytes": len(invalid),
                "sha256": hashlib.sha256(invalid).hexdigest().upper(),
            },
        }
        (downstream / "run_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

        with self.assertRaisesRegex(
            RetirementError, "run_config_unreadable_reference_uncertain"
        ):
            plan_retirement(
                self.artifacts,
                self.repo,
                self.target,
                self.replacement,
                "matching but unparsable config remains uncertain",
                self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_declared_compatibility_role_must_exist_at_both_ends(self, _scan: mock.Mock) -> None:
        with self.assertRaisesRegex(RetirementError, "identity roles missing"):
            plan_retirement(
                self.artifacts, self.repo, self.target, self.replacement,
                "compatible", (*self.compatibility_roles, "project_specific_missing_role"),
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_apply_requires_host_lease(self, _scan: mock.Mock) -> None:
        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "compatible", self.compatibility_roles,
        )
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(RetirementError):
            apply_retirement(plan)

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_plan_rejects_missing_or_changed_recorded_evidence(self, _scan: mock.Mock) -> None:
        for run in (self.target, self.replacement):
            payload = run / "simion" / "analyzer.pa0"
            original = payload.read_bytes()
            for mutation in (None, b"drift!"):
                with self.subTest(run=run.name, mutation=mutation):
                    if mutation is None:
                        payload.unlink()
                    else:
                        payload.write_bytes(mutation)
                    with self.assertRaisesRegex(RetirementError, "identity differs"):
                        plan_retirement(
                            self.artifacts, self.repo, self.target, self.replacement,
                            "compatible", self.compatibility_roles,
                        )
                    payload.write_bytes(original)

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_replacement_cannot_omit_compatibility_input_record(self, _scan: mock.Mock) -> None:
        path = self.replacement / "run_manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        del manifest["inputs"]["analyzer_pa0"]
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(RetirementError, "does not bind configured input"):
            plan_retirement(
                self.artifacts, self.repo, self.target, self.replacement,
                "compatible", self.compatibility_roles,
            )

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_apply_rechecks_evidence_before_any_removal(self, _scan: mock.Mock) -> None:
        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "compatible", self.compatibility_roles,
        )
        for run, relative in (
            (self.replacement, "simion/analyzer.pa0"),
            (self.target, "summary.json"),
            (self.replacement, "run_manifest.json"),
        ):
            path = run / relative
            original = path.read_bytes()
            with self.subTest(run=run.name, relative=relative):
                path.write_bytes(original + b" ")
                with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
                    with self.assertRaises(RetirementError):
                        apply_retirement(plan)
                marker = json.loads(
                    (self.target / "solver_review_retirement_receipt.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(marker["status"], "preflight_pending")
                self.assertEqual(marker["lifecycle_status"], "retirement_pending")
                for item in plan["removed_files"]:
                    self.assertTrue((self.target / item["path"]).is_file())
                path.write_bytes(original)

    @mock.patch("common.contracts.solver_review_retirement._git_document_references", return_value=[])
    def test_pending_receipt_resumes_only_recorded_partial_removal(self, _scan: mock.Mock) -> None:
        plan = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "compatible", self.compatibility_roles,
        )
        first = plan["removed_files"][0]
        (self.target / first["path"]).unlink()
        pending = {
            **plan,
            "role": "solver_review_retirement_receipt",
            "lifecycle_status": "retirement_pending",
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        (self.target / "solver_review_retirement_receipt.json").write_text(json.dumps(pending), encoding="utf-8")
        resumed = plan_retirement(
            self.artifacts, self.repo, self.target, self.replacement,
            "compatible", self.compatibility_roles,
        )
        self.assertTrue(any(item.get("already_removed_before_resume") for item in resumed["removed_files"]))
        with mock.patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID": "123"}):
            apply_retirement(resumed)
        self.assertEqual(verify_retirement(self.target)["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
