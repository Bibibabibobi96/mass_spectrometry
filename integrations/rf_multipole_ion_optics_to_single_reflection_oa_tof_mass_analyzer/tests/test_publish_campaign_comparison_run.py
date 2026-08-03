"""Tests for descriptive multipole-to-oaTOF campaign comparison publication."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis import (
    publish_campaign_comparison_run as publisher,
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def record(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def build_current_parent(root: Path) -> tuple[Path, Path, str]:
    workspace = root / "workspace"
    repo = workspace / "simulation_repo"
    runs = (
        workspace
        / "artifacts"
        / "projects"
        / publisher.INTEGRATION_ID
        / "runs"
    )
    parent_id = "20260803_210000__sim__cross__current-campaign-parent"
    terminal_id = "20260803_205500__sim__simion__current-analyzer"
    profile_id = "rf_hexapole_oatof_shield_terminal_direct_mating_gap_0mm"
    source_identity = {
        "source_branch_id": "simion",
        "solver_id": "simion",
        "run_id": "20260803_200000__sim__simion__source",
        "project_id": "rf_hexapole_ion_optics",
        "manifest_sha256": "A" * 64,
        "event_sha256": "B" * 64,
        "particle_source_sha256": "C" * 64,
        "metadata_sha256": "D" * 64,
    }
    experiment = {
        "sequence": 7,
        "experiment_id": "hexapole_current",
        "connection_profile_id": profile_id,
        "run_id": parent_id,
        "source": {
            "run_id": source_identity["run_id"],
            "launched_particle_count": 100,
            "particle_count": 10,
            "manifest": {"sha256": source_identity["manifest_sha256"]},
            "state": {"sha256": source_identity["event_sha256"]},
            "particle_source": {
                "sha256": source_identity["particle_source_sha256"]
            },
            "metadata": {"sha256": source_identity["metadata_sha256"]},
        },
    }
    campaign_path = repo / "campaign.json"
    write_json(
        campaign_path,
        {
            "schema_version": 1,
            "role": "rf_multipole_oatof_experiment_campaign",
            "integration_id": publisher.INTEGRATION_ID,
            "campaign_id": "current_campaign",
            "experiments": [experiment],
        },
    )

    terminal_root = runs / terminal_id
    terminal_config_path = terminal_root / "run_config.json"
    write_json(
        terminal_config_path,
        {
            "schema_version": 2,
            "run_id": terminal_id,
            "project": source_identity["project_id"],
            "mode": publisher.TERMINAL_MODE,
            "upstream_source_identity": source_identity,
            "parameters": {
                "connection_profile_id": profile_id,
                "source_branch_id": "simion",
            },
        },
    )
    terminal_metrics = terminal_root / "analyzer_transport_metrics.json"
    downstream = terminal_root / "simion_downstream_particles.csv"
    write_json(terminal_metrics, {"census": {}})
    downstream.write_text("Ion,TofUs,RadiusMm,Hit\n", encoding="utf-8")
    terminal_manifest_path = terminal_root / "run_manifest.json"
    write_json(
        terminal_manifest_path,
        {
            "schema_version": 2,
            "role": "simulation_run_manifest",
            "run_id": terminal_id,
            "project": source_identity["project_id"],
            "mode": publisher.TERMINAL_MODE,
            "status": "success",
            "run_config": record(terminal_config_path),
            "outputs": [record(terminal_metrics), record(downstream)],
        },
    )

    parent_root = runs / parent_id
    parent_config_path = parent_root / "run_config.json"
    parent_summary_path = parent_root / "summary.json"
    row_sha256 = publisher._canonical_sha256(experiment)
    write_json(
        parent_config_path,
        {
            "schema_version": 2,
            "run_id": parent_id,
            "project": publisher.INTEGRATION_ID,
            "mode": publisher.PARENT_MODE,
            "inputs": {
                "analyzer_transport_manifest": str(terminal_manifest_path)
            },
            "connection_profile_id": profile_id,
            "campaign_path": str(campaign_path),
            "campaign_sha256": file_sha256(campaign_path),
            "campaign_id": "current_campaign",
            "experiment_id": experiment["experiment_id"],
            "experiment_row_sha256": row_sha256,
            "source_branch_id": "simion",
            "launched_particle_count": 100,
            "particle_count": 10,
            "source_particle_identity": source_identity,
            "stage_runs": [
                {
                    "phase": "analyzer_transport",
                    "run_id": terminal_id,
                    "path": str(terminal_root),
                    "manifest_sha256": file_sha256(terminal_manifest_path),
                }
            ],
            "formal_gate_passed": False,
        },
    )
    write_json(
        parent_summary_path,
        {
            "schema_version": 1,
            "role": "integration_family_source_closure_summary",
            "status": "success",
            "connection_profile_id": profile_id,
            "campaign_id": "current_campaign",
            "experiment_id": experiment["experiment_id"],
            "experiment_row_sha256": row_sha256,
            "source_branch_id": "simion",
            "launched_particle_count": 100,
            "particle_count": 10,
            "formal_gate_passed": False,
        },
    )
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
            "inputs": {"analyzer": record(terminal_manifest_path)},
            "outputs": [record(parent_summary_path)],
        },
    )
    return repo, runs, parent_id


class CampaignComparisonFixture:
    def __init__(self, root: Path, label: str, offset: float = 0.0) -> None:
        self.root = root / label.replace(" ", "_")
        self.parent_manifest = self.root / "parent_manifest.json"
        self.parent_summary = self.root / "parent_summary.json"
        self.terminal_manifest = self.root / "terminal_manifest.json"
        self.terminal_metrics = self.root / "terminal_metrics.json"
        self.downstream_particles = self.root / "downstream.csv"
        census = {
            "rf_exit": 8,
            "oatof_entry": 8,
            "active_at_pulse": 5,
            "local_accelerator_exit": 4,
            "detector_crossing": 2,
            "detector_hit": 2,
        }
        write_json(self.parent_manifest, {})
        write_json(self.terminal_manifest, {})
        write_json(
            self.parent_summary,
            {
                "status": "success",
                "claim_status": "FUNCTIONAL_SCREEN_ONLY",
                "census": census,
            },
        )
        write_json(self.terminal_metrics, {"census": census})
        self.downstream_particles.parent.mkdir(parents=True, exist_ok=True)
        with self.downstream_particles.open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(
                handle, fieldnames=["Ion", "TofUs", "RadiusMm", "Hit"]
            )
            writer.writeheader()
            writer.writerows(
                [
                    {"Ion": 1, "TofUs": 10 + offset, "RadiusMm": 2, "Hit": True},
                    {"Ion": 2, "TofUs": "", "RadiusMm": "", "Hit": False},
                    {"Ion": 3, "TofUs": 12 + offset, "RadiusMm": 4, "Hit": True},
                    {"Ion": 4, "TofUs": "", "RadiusMm": "", "Hit": False},
                ]
            )
        self.inputs = publisher.CaseInputs(
            label=label,
            parent_run_id=f"20260803_19{int(offset):02d}00__sim__cross__fixture",
            parent_manifest=self.parent_manifest,
            parent_summary=self.parent_summary,
            parent_config={
                "campaign_id": "fixture_campaign",
                "experiment_id": label.replace(" ", "_").lower(),
                "experiment_row_sha256": "E" * 64,
                "connection_profile_id": "rf_fixture_direct_mating_gap_0mm",
                "source_branch_id": "simion",
                "source_particle_identity": {
                    "run_id": "20260803_180000__sim__simion__fixture",
                    "project_id": "rf_fixture_ion_optics",
                },
            },
            campaign_sequence=int(offset) + 1,
            terminal_manifest=self.terminal_manifest,
            terminal_metrics=self.terminal_metrics,
            downstream_particles=self.downstream_particles,
        )


class PublishCampaignComparisonRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.first = CampaignComparisonFixture(root, "Octupole segmented", 0.0)
        self.second = CampaignComparisonFixture(root, "Quadrupole no acceleration", 1.0)

    def test_computes_normalized_census_and_explicit_tof_proxy(self) -> None:
        result = publisher._compute_case(self.first.inputs)
        self.assertEqual(result["census"]["detector_hit"], 2)
        self.assertEqual(result["cumulative_retention_fraction"]["active_at_pulse"], 0.625)
        metrics = result["analyzer_metrics"]
        self.assertEqual(metrics["detector_hit_fraction_of_rf_exit"], 0.25)
        self.assertEqual(metrics["mean_analyzer_tof_us"], 11.0)
        self.assertAlmostEqual(metrics["sample_sigma_analyzer_tof_ns"], 1414.213562373095)
        self.assertAlmostEqual(metrics["gaussian_fwhm_tof_proxy_ns"], 3330.2184446307908)
        self.assertIn("not direct FWHM", metrics["tof_proxy_scope"])

    def test_loads_only_current_campaign_parent_and_verifies_campaign_row(self) -> None:
        repo, runs, parent_id = build_current_parent(Path(self.temporary.name))
        loaded = publisher._load_case_inputs(
            repo_root=repo / ".." / "simulation_repo",
            workspace_root=repo.parent / "simulation_repo" / "..",
            runs_root=runs / ".." / "runs",
            label="current",
            parent_run_id=parent_id,
        )
        self.assertEqual(loaded.parent_config["campaign_id"], "current_campaign")
        self.assertEqual(loaded.parent_config["experiment_id"], "hexapole_current")

        manifest_path = runs / parent_id / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["mode"] = "multipole_family_source_closure_n100"
        write_json(manifest_path, manifest)
        with self.assertRaisesRegex(ContractError, "parent manifest identity"):
            publisher._load_case_inputs(
                repo_root=repo,
                workspace_root=repo.parent,
                runs_root=runs,
                label="historical",
                parent_run_id=parent_id,
            )

    def test_rejects_csv_census_mismatch(self) -> None:
        summary = json.loads(self.first.parent_summary.read_text(encoding="utf-8"))
        summary["census"]["detector_crossing"] = 3
        summary["census"]["detector_hit"] = 3
        write_json(self.first.parent_summary, summary)
        metrics = json.loads(self.first.terminal_metrics.read_text(encoding="utf-8"))
        metrics["census"]["detector_crossing"] = 3
        metrics["census"]["detector_hit"] = 3
        write_json(self.first.terminal_metrics, metrics)
        with self.assertRaisesRegex(ContractError, "CSV census differs"):
            publisher._compute_case(self.first.inputs)

    def test_figure_uses_distinct_redundant_encodings_and_external_legend(self) -> None:
        import matplotlib.pyplot as plt

        cases = [
            publisher._compute_case(self.first.inputs),
            publisher._compute_case(self.second.inputs),
        ]
        figure, axes = publisher.build_campaign_comparison_figure(cases)
        try:
            self.assertEqual(len(axes), 3)
            self.assertEqual(len(figure.legends), 1)
            self.assertIsNone(axes[0].get_legend())
            lines = axes[0].get_lines()
            self.assertNotEqual(lines[0].get_color(), lines[1].get_color())
            self.assertNotEqual(lines[0].get_marker(), lines[1].get_marker())
            self.assertNotEqual(lines[0].get_linestyle(), lines[1].get_linestyle())
            self.assertIn("sample σ", axes[2].get_ylabel())
        finally:
            plt.close(figure)

    def test_exports_traceable_png_and_claim_limited_report(self) -> None:
        cases = [
            publisher._compute_case(self.first.inputs),
            publisher._compute_case(self.second.inputs),
        ]
        output = Path(self.temporary.name) / "comparison.png"
        manifest = Path(self.temporary.name) / "comparison.figure.json"
        publisher._export_figure(cases=cases, output=output, figure_manifest=manifest)
        figure_record = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertTrue(output.is_file())
        self.assertEqual(figure_record["dimensions_mm"], {"width": 183, "height": 90})
        self.assertEqual(figure_record["dpi"], 300)
        self.assertFalse(figure_record["qualification_decision_made"])
        report = publisher._render_report_markdown(cases)
        self.assertIn("must not be used to rank performance", report)
        self.assertIn("INCONCLUSIVE_DIAGNOSTIC_ONLY", report)


if __name__ == "__main__":
    unittest.main()
