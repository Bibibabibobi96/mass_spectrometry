from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.contracts.capacity_ledger import initialize_capacity_ledger
from projects.rf_multipole_ion_optics.runtime import _transport_run_artifacts as artifacts
from projects.rf_multipole_ion_optics.runtime.run_round_rod_transport import execute as execute_round_rod
from projects.rf_multipole_ion_optics.runtime import run_round_rod_transport


ROOT = Path(__file__).parents[4]
PROJECT = ROOT / "projects/rf_multipole_ion_optics"
MODE = PROJECT / "config/modes/hexapole_transport_no_collision.json"


def _transport_run(run_id: str, outputs: tuple[str, ...]):
    return artifacts.transport_run(
        PROJECT, run_id, mode="transport_no_collision", run_config_role="fixture_config",
        design_profile_id="hexapole_no_acceleration_full_length",
        summary_role="fixture_summary", parameters={"model_level": "L1"},
        identity_inputs={"implementation": MODE}, output_names=outputs,
    )


class FailedRunManifestTest(unittest.TestCase):
    def test_new_run_package_emits_only_the_package_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capacity_root = Path(directory) / "artifacts"
            capacity_root.mkdir()
            initialize_capacity_ledger(capacity_root, objects=[])
            artifact_root = capacity_root / "projects" / "fixture"
            support = ROOT / "common/contracts/run_artifact_support.ps1"
            python = Path(sys.executable)
            command = (
                f". '{support}'; "
                f"$package=New-RunPackage -Python '{python}' "
                f"-RepoRoot '{ROOT}' -ArtifactRoot '{artifact_root}' "
                "-RetentionContractEnabled -CapacityLedgerLifecycleEnabled "
                "-RunId '20260723_120000__test__python__package-output' "
                "-Project 'fixture' -Mode 'package_output' -Software @('Python 3.11'); "
                "Write-Output $package.run_dir"
            )
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=ROOT,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            output_lines = [line for line in result.stdout.splitlines() if line.strip()]
            expected_run = (
                artifact_root
                / "runs"
                / "20260723_120000__test__python__package-output"
            )
            self.assertEqual(output_lines, [str(expected_run)])

    def test_failure_finalization_keeps_all_partial_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "runs" / "20260723_120000__sim__simion__partial-evidence"
            for relative in ("inputs/code", "results", "logs", "simion"):
                (run / relative).mkdir(parents=True)
            (run / "inputs/request.json").write_text("{}\n", encoding="utf-8")
            (run / "inputs/code/solver.lua").write_text("-- frozen\n", encoding="utf-8")
            (run / "results/metrics.json").write_text('{"status":"FAIL"}\n', encoding="utf-8")
            (run / "logs/native.txt").write_text("physical failure\n", encoding="utf-8")
            (run / "simion/model.pa0").write_bytes(b"partial-pa")
            config = run / "run_config.json"
            summary = run / "summary.json"
            config.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": run.name,
                        "project": "fixture",
                        "mode": "resolved_design_transport",
                        "project_root": str(run),
                        "inputs": {"request": str(run / "inputs/request.json")},
                        "formal_gate_passed": False,
                    }
                ),
                encoding="utf-8",
            )
            support = ROOT / "common/contracts/run_artifact_support.ps1"
            python = Path(sys.executable)
            command = (
                f". '{support}'; Complete-FailedRun -Python '{python}' "
                f"-RepoRoot '{ROOT}' -RunConfig '{config}' -Summary '{summary}' "
                "-SummaryRole 'fixture_summary' -Reason 'physical gate failed' "
                "-Software @('Python 3.11')"
            )
            subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=ROOT,
                timeout=30,
            )
            manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
            output_paths = {Path(item["path"]).name for item in manifest["outputs"]}
            self.assertEqual(manifest["status"], "failed")
            self.assertTrue({"metrics.json", "native.txt", "model.pa0", "summary.json"} <= output_paths)
            self.assertTrue(
                any(item["path"].endswith("solver.lua") for item in manifest["inputs"].values())
            )


class TransportRunArtifactsTest(unittest.TestCase):
    def test_l1_l2_rejects_unsupported_designs_before_creating_run(self) -> None:
        profiles = (
            "quadrupole_no_acceleration_full_length",
            "hexapole_segmented_rod_axial_acceleration",
            "octupole_exit_aperture_plate_acceleration",
            "octupole_through_exit_no_acceleration",
            "octupole_through_entrance_exit_no_acceleration",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(artifacts, "ARTIFACT_PROJECTS_ROOT", root):
                for profile in profiles:
                    with self.subTest(profile=profile):
                        with self.assertRaisesRegex(ValueError, "L1/L2 transport only supports"):
                            with artifacts.transport_run(
                                PROJECT, "20260729_120001__test__python__unsupported-design",
                                mode="transport_no_collision", run_config_role="fixture_config",
                                design_profile_id=profile, summary_role="fixture_summary",
                                parameters={}, identity_inputs={}, output_names=(),
                            ):
                                self.fail("unsupported design reached a run context")
                        self.assertEqual(list(root.iterdir()), [])

    def test_round_rod_screen_rejects_another_structure_with_same_project_owner(self) -> None:
        project_id = "rf_multipole_ion_optics"
        run_id = "20260729_120001__test__python__field-screen-identity"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / project_id / "runs" / run_id
            (source / "inputs").mkdir(parents=True)
            (source / "run_manifest.json").write_text(json.dumps({"status": "success", "project": project_id}))
            identity = {"project_id": project_id, "family_id": project_id, "radial_order_n": 3, "electrode_count": 6}
            (source / "inputs/multipole_resolved_design.json").write_text(json.dumps({"identity": identity}))
            expected = {**identity, "radial_order_n": 4, "electrode_count": 8}
            with patch.object(run_round_rod_transport, "ARTIFACT_PROJECTS_ROOT", root):
                with self.assertRaisesRegex(ValueError, "structural identity"):
                    run_round_rod_transport._load_source(project_id, run_id, expected_identity=expected)

    def test_success_freezes_inputs_and_terminalizes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(artifacts, "ARTIFACT_PROJECTS_ROOT", root / "artifacts/projects"):
                with _transport_run("20260729_120000__test__python__transport-success", ("metrics.json",)) as run:
                    provisional = json.loads((run.run_dir / "run_manifest.json").read_text(encoding="utf-8"))
                    self.assertEqual(provisional["status"], "interrupted")
                    run.outputs[0].write_text('{"status":"PASS"}\n', encoding="utf-8")
                    run.complete({"project_id": "rf_multipole_ion_optics"})
            manifest = json.loads((run.run_dir / "run_manifest.json").read_text(encoding="utf-8"))
            config = json.loads((run.run_dir / "run_config.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "success")
            self.assertEqual(config["inputs"]["mode"], str(run.run_dir / "inputs/transport_no_collision.json"))
            self.assertEqual([Path(item["path"]).name for item in manifest["outputs"]], ["metrics.json", "summary.json"])

    def test_exception_replaces_interrupted_state_with_failed_partial_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(artifacts, "ARTIFACT_PROJECTS_ROOT", root / "artifacts/projects"):
                with self.assertRaisesRegex(RuntimeError, "scientific failure"):
                    with _transport_run(
                        "20260729_120001__test__python__transport-failure", ("partial.json", "absent.json")
                    ) as run:
                        run.outputs[0].write_text("{}\n", encoding="utf-8")
                        raise RuntimeError("scientific failure")
            manifest = json.loads((run.run_dir / "run_manifest.json").read_text(encoding="utf-8"))
            summary = json.loads((run.run_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual((manifest["status"], summary["reason"]), ("failed", "scientific failure"))
            self.assertEqual([Path(item["path"]).name for item in manifest["outputs"]], ["summary.json", "partial.json"])

    def test_round_rod_runner_rejects_destination_identity_before_source_access(self) -> None:
        with self.assertRaisesRegex(ValueError, "run_id"):
            execute_round_rod(Path("missing-project"), "missing-source", "invalid-run-id",
                              design_profile_id="hexapole_no_acceleration_full_length")


if __name__ == "__main__":
    unittest.main()
