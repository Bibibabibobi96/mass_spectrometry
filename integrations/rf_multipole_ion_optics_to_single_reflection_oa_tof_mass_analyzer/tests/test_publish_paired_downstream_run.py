"""Tests for compact paired downstream production publication."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis import (
    publish_paired_downstream_run as publisher,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.tests.test_paired_downstream_analysis import (
    Fixture,
    record,
    write_json,
)


PROFILES = (
    "rf_quadrupole_no_acceleration_full_length_direct_mating_gap_0mm",
    "rf_hexapole_no_acceleration_full_length_direct_mating_gap_0mm",
    "rf_octupole_no_acceleration_full_length_direct_mating_gap_0mm",
)


class PublisherFixture:
    def __init__(self, root: Path) -> None:
        self.actual_repo = Path(__file__).resolve().parents[3]
        self.workspace = root / "workspace"
        self.repo = self.workspace / "simulation_repo"
        self.pairs: list[tuple[str, str, str]] = []
        self.parent_configs: dict[tuple[str, str], Path] = {}
        self._prepare_repo_inputs()
        evidence = Fixture(self.workspace / "evidence")
        for index, (profile_id, short_id) in enumerate(
            zip(PROFILES, ("q", "h", "o"), strict=True),
            start=1,
        ):
            evidence.add_candidate(short_id, index / 100)
            candidate = evidence.request["candidates"][-1]
            self._bind_profile(candidate, profile_id)
            parents = {
                solver: self._publish_terminal_and_parent(
                    candidate,
                    profile_id,
                    short_id,
                    solver,
                    index,
                )
                for solver in publisher.SOLVERS
            }
            self.pairs.append(
                (profile_id, parents["comsol"], parents["simion"])
            )

    def _prepare_repo_inputs(self) -> None:
        shutil.copytree(self.actual_repo / "common", self.repo / "common")
        prereg_relative = Path(publisher.PREREGISTRATION_RELATIVE_PATH)
        prereg_target = self.repo / prereg_relative
        prereg_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.actual_repo / prereg_relative, prereg_target)
        (self.repo / "requirements-lock.txt").write_text(
            "unit-test-lock\n", encoding="utf-8"
        )
        for relative in (
            publisher.ANALYZER_RELATIVE_PATH,
            publisher.PUBLISHER_RELATIVE_PATH,
        ):
            target = self.repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.actual_repo / relative, target)

    @staticmethod
    def _bind_profile(candidate: dict[str, object], profile_id: str) -> None:
        branch = candidate["comsol"]
        assert isinstance(branch, dict)
        runtime_path = Path(branch["runtime_binding"]["path"])
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        runtime["connection_profile_id"] = profile_id
        write_json(runtime_path, runtime)
        resolved_path = Path(branch["resolved_connection"]["path"])
        resolved = json.loads(resolved_path.read_text(encoding="utf-8"))
        resolved["selection"]["connection_profile_id"] = profile_id
        write_json(resolved_path, resolved)

    def _publish_terminal_and_parent(
        self,
        candidate: dict[str, object],
        profile_id: str,
        short_id: str,
        solver: str,
        index: int,
    ) -> str:
        branch = candidate[solver]
        assert isinstance(branch, dict)
        old_manifest_path = Path(branch["manifest"]["path"])
        old_manifest = json.loads(old_manifest_path.read_text(encoding="utf-8"))
        old_config_path = Path(old_manifest["run_config"]["path"])
        config = json.loads(old_config_path.read_text(encoding="utf-8"))
        terminal_id = (
            f"20260730_12{index:02d}0{1 if solver == 'comsol' else 2}"
            f"__sim__{solver}__terminal-{short_id}"
        )
        terminal_root = self.workspace / "stages" / terminal_id
        config_path = terminal_root / "run_config.json"
        config["run_id"] = terminal_id
        # The terminal count is the post-capture cohort, not the N=100
        # mother-source count frozen by the parent and preregistration.
        config["parameters"]["particle_count"] = 6
        write_json(config_path, config)
        terminal_manifest = dict(old_manifest)
        terminal_manifest["run_id"] = terminal_id
        terminal_manifest["run_config"] = record(config_path)
        terminal_manifest["formal_eligible"] = False
        terminal_manifest["inputs"] = {
            name: record(Path(path))
            for name, path in config["inputs"].items()
        }
        terminal_manifest_path = terminal_root / "run_manifest.json"
        write_json(terminal_manifest_path, terminal_manifest)

        parent_id = (
            f"20260730_13{index:02d}0{1 if solver == 'comsol' else 2}"
            f"__sim__{solver}__parent-{short_id}"
        )
        parent_root = (
            self.workspace
            / "artifacts"
            / "projects"
            / publisher.INTEGRATION_ID
            / "runs"
            / parent_id
        )
        parent_config_path = parent_root / "run_config.json"
        terminal_portable = terminal_manifest_path.relative_to(
            self.workspace
        ).as_posix()
        parent_config = {
            "schema_version": 2,
            "run_id": parent_id,
            "project": publisher.INTEGRATION_ID,
            "mode": publisher.PARENT_MODE,
            "project_root": str(self.workspace),
            "inputs": {"analyzer_transport_manifest": terminal_portable},
            "connection_profile_id": profile_id,
            "source_branch_id": solver,
            "source_particle_identity": config["upstream_source_identity"],
            "stage_runs": [
                {
                    "phase": "analyzer_transport",
                    "run_id": terminal_id,
                    "path": terminal_root.relative_to(self.workspace).as_posix(),
                    "manifest_sha256": file_sha256(terminal_manifest_path),
                }
            ],
            "artifact_retention": {
                "policy_version": 1,
                "class": "compact",
                "reason": None,
            },
            "formal_gate_passed": False,
        }
        write_json(parent_config_path, parent_config)
        parent_manifest_path = parent_root / "run_manifest.json"
        write_json(
            parent_manifest_path,
            {
                "schema_version": 2,
                "role": "simulation_run_manifest",
                "run_id": parent_id,
                "project": publisher.INTEGRATION_ID,
                "mode": publisher.PARENT_MODE,
                "status": "success",
                "run_config": record(parent_config_path),
                "inputs": {
                    "analyzer_transport_manifest": record(
                        terminal_manifest_path
                    )
                },
                "outputs": [],
                "formal_eligible": False,
            },
        )
        self.parent_configs[(profile_id, solver)] = parent_config_path
        return parent_id

class PublishPairedDownstreamRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = PublisherFixture(Path(self.temporary.name))

    def test_publishes_compact_diagnostic_only_run(self) -> None:
        run_id = "20260730_140000__analysis__cross__paired-family__n100"
        manifest_path = publisher.publish_paired_downstream_run(
            repo_root=self.fixture.repo,
            run_id=run_id,
            pairs=self.fixture.pairs,
        )
        run_root = manifest_path.parent
        self.assertEqual(
            {path.relative_to(run_root).as_posix() for path in run_root.rglob("*") if path.is_file()},
            {
                "inputs/paired_analysis_request.json",
                "results/paired_downstream_analysis.json",
                "run_config.json",
                "summary.json",
                "run_manifest.json",
            },
        )
        config = json.loads((run_root / "run_config.json").read_text(encoding="utf-8"))
        summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(config["mode"], publisher.OUTPUT_MODE)
        self.assertEqual(config["parameters"]["particle_count"], 100)
        self.assertEqual(config["parameters"]["profile_ids"], sorted(PROFILES))
        self.assertEqual(len(config["parameters"]["parent_run_ids"]), 3)
        self.assertFalse(config["formal_gate_passed"])
        self.assertEqual(summary["analysis_status"], "INCONCLUSIVE_DIAGNOSTIC_ONLY")
        self.assertEqual(summary["candidate_count"], 3)
        self.assertFalse(summary["acceptance_thresholds_applied"])
        self.assertFalse(summary["qualification_decision_made"])
        self.assertEqual(manifest["status"], "success")
        self.assertFalse(manifest["formal_eligible"])
        self.assertIn("paired_analysis_request", manifest["inputs"])
        self.assertNotIn(
            "paired_analysis_request.json",
            {Path(item["path"]).name for item in manifest["outputs"]},
        )

    def test_analyzer_starts_only_after_interrupted_publication(self) -> None:
        run_id = "20260730_140003__analysis__cross__paired-family__n100"
        real_analyze = publisher.analyze_request

        def inspect_lifecycle(request: object, workspace: Path) -> object:
            run_root = self.workspace_runs / run_id
            manifest = json.loads(
                (run_root / "run_manifest.json").read_text(encoding="utf-8")
            )
            summary = json.loads(
                (run_root / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["status"], "interrupted")
            self.assertEqual(summary["status"], "interrupted")
            self.assertIn("paired_analysis_request", manifest["inputs"])
            self.assertEqual(
                {Path(item["path"]).name for item in manifest["outputs"]},
                {"summary.json"},
            )
            return real_analyze(request, workspace)

        with mock.patch.object(
            publisher,
            "analyze_request",
            side_effect=inspect_lifecycle,
        ):
            publisher.publish_paired_downstream_run(
                repo_root=self.fixture.repo,
                run_id=run_id,
                pairs=self.fixture.pairs,
            )

    def test_duplicate_parent_analyzer_stage_fails_before_output(self) -> None:
        profile_id = PROFILES[0]
        config_path = self.fixture.parent_configs[(profile_id, "comsol")]
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["stage_runs"].append(dict(config["stage_runs"][0]))
        write_json(config_path, config)
        parent_id = self.fixture.pairs[0][1]
        parent_manifest_path = config_path.parent / "run_manifest.json"
        parent_manifest = json.loads(parent_manifest_path.read_text(encoding="utf-8"))
        parent_manifest["run_config"] = record(config_path)
        write_json(parent_manifest_path, parent_manifest)
        run_id = "20260730_140001__analysis__cross__paired-family__n100"
        with self.assertRaisesRegex(ContractError, "one analyzer stage"):
            publisher.publish_paired_downstream_run(
                repo_root=self.fixture.repo,
                run_id=run_id,
                pairs=self.fixture.pairs,
            )
        self.assertFalse(
            (
                self.workspace_runs
                / run_id
            ).exists()
        )
        self.assertTrue(parent_id)

    def test_manifest_failure_never_leaves_success_manifest(self) -> None:
        run_id = "20260730_140002__analysis__cross__paired-family__n100"
        real_publish = publisher._publish_manifest

        def fail_success(**kwargs: object) -> None:
            if kwargs["status"] == "success":
                raise ContractError("injected publication failure")
            real_publish(**kwargs)

        with mock.patch.object(
            publisher,
            "_publish_manifest",
            side_effect=fail_success,
        ):
            with self.assertRaisesRegex(ContractError, "injected"):
                publisher.publish_paired_downstream_run(
                    repo_root=self.fixture.repo,
                    run_id=run_id,
                    pairs=self.fixture.pairs,
                )
        run_root = self.workspace_runs / run_id
        self.assertTrue(run_root.is_dir())
        manifest = json.loads(
            (run_root / "run_manifest.json").read_text(encoding="utf-8")
        )
        summary = json.loads(
            (run_root / "summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(summary["status"], "failed")
        self.assertNotEqual(summary["status"], "success")
        self.assertEqual(
            summary["failure_stage"], "success_manifest_publication"
        )
        self.assertEqual(summary["error_type"], "ContractError")
        self.assertEqual(summary["reason"], "injected publication failure")

    def test_failed_terminalization_restores_interrupted_authority(self) -> None:
        run_id = "20260730_140004__analysis__cross__paired-family__n100"
        real_publish = publisher._publish_manifest

        def fail_terminal_status(**kwargs: object) -> None:
            if kwargs["status"] in {"success", "failed"}:
                raise ContractError("injected terminal publication failure")
            real_publish(**kwargs)

        with mock.patch.object(
            publisher,
            "_publish_manifest",
            side_effect=fail_terminal_status,
        ):
            with self.assertRaisesRegex(ContractError, "injected"):
                publisher.publish_paired_downstream_run(
                    repo_root=self.fixture.repo,
                    run_id=run_id,
                    pairs=self.fixture.pairs,
                )
        run_root = self.workspace_runs / run_id
        manifest = json.loads(
            (run_root / "run_manifest.json").read_text(encoding="utf-8")
        )
        summary = json.loads(
            (run_root / "summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["status"], "interrupted")
        self.assertEqual(summary["status"], "interrupted")

    def test_process_interrupts_preserve_interrupted_authority(self) -> None:
        cases = (
            (
                "20260730_140005__analysis__cross__paired-family__n100",
                KeyboardInterrupt,
            ),
            (
                "20260730_140006__analysis__cross__paired-family__n100",
                SystemExit,
            ),
        )
        for run_id, signal in cases:
            with self.subTest(signal=signal.__name__):
                with mock.patch.object(
                    publisher,
                    "analyze_request",
                    side_effect=signal(),
                ):
                    with self.assertRaises(signal):
                        publisher.publish_paired_downstream_run(
                            repo_root=self.fixture.repo,
                            run_id=run_id,
                            pairs=self.fixture.pairs,
                        )
                run_root = self.workspace_runs / run_id
                manifest = json.loads(
                    (run_root / "run_manifest.json").read_text(
                        encoding="utf-8"
                    )
                )
                summary = json.loads(
                    (run_root / "summary.json").read_text(encoding="utf-8")
                )
                self.assertEqual(manifest["status"], "interrupted")
                self.assertEqual(summary["status"], "interrupted")
                self.assertNotIn("failure_stage", summary)

    @property
    def workspace_runs(self) -> Path:
        return (
            self.fixture.workspace
            / "artifacts"
            / "projects"
            / publisher.INTEGRATION_ID
            / "runs"
        )


if __name__ == "__main__":
    unittest.main()
