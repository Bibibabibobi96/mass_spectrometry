"""Tests for governed three-arm source-revision publication."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common.contracts.file_identity import file_sha256
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis import (
    publish_source_revision_comparison_run as publisher,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.tests.test_publish_paired_downstream_run import (
    PROFILES,
    PublisherFixture,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.tests.test_paired_downstream_analysis import (
    record,
    write_json,
)


class SourceRevisionPublisherFixture:
    def __init__(self, root: Path) -> None:
        self.base = PublisherFixture(root)
        self.repo = self.base.repo
        self.workspace = self.base.workspace
        source = self.base.actual_repo / publisher.SOURCE_COMPARISON_RELATIVE_PATH
        target = self.repo / publisher.SOURCE_COMPARISON_RELATIVE_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        self.comparisons: list[tuple[str, str, str, str, str, str]] = []
        pairs = {profile: (comsol, simion) for profile, comsol, simion in self.base.pairs}
        for index, profile_id in enumerate(PROFILES, start=1):
            family = profile_id.split("_", 2)[1]
            revision_id = f"{family}_hybrid_reference"
            baseline_comsol, baseline_simion = pairs[profile_id]
            hybrid_comsol = self._clone_hybrid_parent(
                profile_id,
                baseline_comsol,
                revision_id,
                index,
            )
            prereg_relative = (
                Path("integrations")
                / publisher.INTEGRATION_ID
                / "config"
                / f"{revision_id}_source_revision_preregistration.json"
            )
            preregistration = self.repo / prereg_relative
            write_json(
                preregistration,
                {
                    "schema_version": 1,
                    "role": "integration_family_source_revision_preregistration",
                    "integration_id": publisher.INTEGRATION_ID,
                    "source_revision_id": revision_id,
                    "preregistered_before_run": True,
                    "execution_status": "NOT_RUN",
                    "profile": {
                        "connection_profile_id": profile_id,
                        "source_branch_ids": ["comsol"],
                        "particle_count": 100,
                    },
                    "comparison": {
                        "baseline_parent_run_id": baseline_comsol,
                        "only_changed_variable": "upstream_comsol_source_revision",
                        "required_metrics": list(publisher.REQUIRED_METRICS),
                    },
                },
            )
            self.comparisons.append(
                (
                    profile_id,
                    revision_id,
                    prereg_relative.as_posix(),
                    baseline_comsol,
                    hybrid_comsol,
                    baseline_simion,
                )
            )

    def _clone_hybrid_parent(
        self,
        profile_id: str,
        baseline_parent_id: str,
        revision_id: str,
        index: int,
    ) -> str:
        runs = (
            self.workspace
            / "artifacts"
            / "projects"
            / publisher.INTEGRATION_ID
            / "runs"
        )
        hybrid_id = (
            f"20260730_15{index:02d}00__sim__comsol__hybrid-{profile_id.split('_', 2)[1]}"
        )
        source_root = runs / baseline_parent_id
        hybrid_root = runs / hybrid_id
        shutil.copytree(source_root, hybrid_root)
        config_path = hybrid_root / "run_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["run_id"] = hybrid_id
        config["source_revision_id"] = revision_id
        write_json(config_path, config)
        manifest_path = hybrid_root / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["run_id"] = hybrid_id
        manifest["run_config"] = record(config_path)
        write_json(manifest_path, manifest)
        return hybrid_id


def write_fake_figure(
    *,
    output: Path,
    manifest: Path,
    **_: object,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"fake diagnostic PNG")
    write_json(
        manifest,
        {
            "schema_version": 1,
            "role": "multipole_exit_state_figure_manifest",
            "figure": {
                "path": str(output),
                "sha256": file_sha256(output),
            },
            "bin_count": publisher.PLOT_BIN_COUNT,
            "series": [{}, {}, {}],
        },
    )


class PublishSourceRevisionComparisonRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture = SourceRevisionPublisherFixture(Path(self.temporary.name))

    def _publish(self, run_id: str) -> Path:
        with mock.patch.object(
            publisher,
            "_render_source_triangle",
            side_effect=write_fake_figure,
        ):
            return publisher.publish_source_revision_comparison_run(
                repo_root=self.fixture.repo,
                run_id=run_id,
                comparisons=self.fixture.comparisons,
            )

    def test_publishes_schema_v2_triangle_figures_and_success_manifest(self) -> None:
        manifest_path = self._publish(
            "20260730_160000__analysis__cross__source-triangle__n100"
        )
        run_root = manifest_path.parent
        result = json.loads(
            (run_root / "results/source_revision_comparison.json").read_text(
                encoding="utf-8"
            )
        )
        summary = json.loads(
            (run_root / "summary.json").read_text(encoding="utf-8")
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["analysis_class"], "POSTHOC_DESCRIPTIVE")
        self.assertEqual(len(result["comparisons"]), 3)
        for comparison in result["comparisons"]:
            self.assertEqual(
                set(comparison["branches"]),
                set(publisher.BRANCH_LABELS),
            )
            self.assertEqual(
                set(comparison["pairwise_edges"]),
                {name for name, _, _ in publisher.PAIR_DEFINITIONS},
            )
            for edge in comparison["pairwise_edges"].values():
                self.assertEqual(
                    edge["pair"]["difference_convention"],
                    "right_minus_left",
                )
                self.assertIn(
                    "particle_sets",
                    edge["local_accelerator_exit"],
                )
                self.assertIn("hit_particle_sets", edge["detector"])
        self.assertEqual(summary["status"], "success")
        self.assertEqual(len(summary["figures"]), 3)
        self.assertEqual(manifest["status"], "success")
        output_names = {Path(item["path"]).name for item in manifest["outputs"]}
        self.assertIn("source_revision_comparison.json", output_names)
        self.assertEqual(
            len([name for name in output_names if name.endswith(".png")]),
            3,
        )
        self.assertEqual(
            len(
                [
                    name
                    for name in output_names
                    if name.endswith(".figure.json")
                ]
            ),
            3,
        )

    def test_analysis_observes_interrupted_manifest_before_work(self) -> None:
        run_id = "20260730_160001__analysis__cross__source-triangle__n100"
        real_comparison = publisher._comparison_result

        def inspect_interrupted(**kwargs: object) -> dict[str, object]:
            manifest = (
                self.fixture.workspace
                / "artifacts"
                / "projects"
                / publisher.INTEGRATION_ID
                / "runs"
                / run_id
                / "run_manifest.json"
            )
            self.assertEqual(
                json.loads(manifest.read_text(encoding="utf-8"))["status"],
                "interrupted",
            )
            return real_comparison(**kwargs)

        with (
            mock.patch.object(
                publisher,
                "_comparison_result",
                side_effect=inspect_interrupted,
            ),
            mock.patch.object(
                publisher,
                "_render_source_triangle",
                side_effect=write_fake_figure,
            ),
        ):
            manifest = publisher.publish_source_revision_comparison_run(
                repo_root=self.fixture.repo,
                run_id=run_id,
                comparisons=self.fixture.comparisons,
            )
        self.assertEqual(
            json.loads(manifest.read_text(encoding="utf-8"))["status"],
            "success",
        )

    def test_analysis_failure_terminalizes_failed_manifest(self) -> None:
        run_id = "20260730_160002__analysis__cross__source-triangle__n100"
        with (
            mock.patch.object(
                publisher,
                "_comparison_result",
                side_effect=RuntimeError("injected triangle failure"),
            ),
            self.assertRaisesRegex(RuntimeError, "injected triangle failure"),
        ):
            publisher.publish_source_revision_comparison_run(
                repo_root=self.fixture.repo,
                run_id=run_id,
                comparisons=self.fixture.comparisons,
            )
        run_root = (
            self.fixture.workspace
            / "artifacts"
            / "projects"
            / publisher.INTEGRATION_ID
            / "runs"
            / run_id
        )
        manifest = json.loads(
            (run_root / "run_manifest.json").read_text(encoding="utf-8")
        )
        summary = json.loads(
            (run_root / "summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["error_type"], "RuntimeError")

    def test_process_interrupt_restores_interrupted_manifest(self) -> None:
        run_id = "20260730_160003__analysis__cross__source-triangle__n100"
        with (
            mock.patch.object(
                publisher,
                "_comparison_result",
                side_effect=KeyboardInterrupt,
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            publisher.publish_source_revision_comparison_run(
                repo_root=self.fixture.repo,
                run_id=run_id,
                comparisons=self.fixture.comparisons,
            )
        run_root = (
            self.fixture.workspace
            / "artifacts"
            / "projects"
            / publisher.INTEGRATION_ID
            / "runs"
            / run_id
        )
        manifest = json.loads(
            (run_root / "run_manifest.json").read_text(encoding="utf-8")
        )
        summary = json.loads(
            (run_root / "summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["status"], "interrupted")
        self.assertEqual(summary["status"], "interrupted")


if __name__ == "__main__":
    unittest.main()
