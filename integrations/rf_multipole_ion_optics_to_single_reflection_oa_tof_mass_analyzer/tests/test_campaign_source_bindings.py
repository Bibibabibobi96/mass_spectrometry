from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.refresh_campaign_source_bindings import (
    compile_campaign,
    is_fresh,
    write_campaign,
)


class CampaignSourceBindingTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        repo = root / "simulation_repo"
        source = root / "artifacts/projects/source/runs/source_run"
        repo.mkdir()
        source.mkdir(parents=True)
        policy = repo / "config/policy.json"
        policy.parent.mkdir()
        policy.write_text('{"policy":1}\n', encoding="utf-8")
        for name in ("run_manifest.json", "state.csv", "source.csv", "metadata.json"):
            (source / name).write_text(name + "\n", encoding="utf-8")
        campaign = repo / "campaign.json"
        campaign.write_text(json.dumps({
            "execution_policy": {"path": "config/policy.json", "sha256": "0" * 64},
            "experiments": [{
                "run_id": "target_run",
                "source": {
                    "manifest": {"path": "artifacts/projects/source/runs/source_run/run_manifest.json", "sha256": "0" * 64},
                    "state": {"path": "artifacts/projects/source/runs/source_run/state.csv", "sha256": "0" * 64},
                    "particle_source": {"path": "artifacts/projects/source/runs/source_run/source.csv", "sha256": "0" * 64},
                    "metadata": {"path": "artifacts/projects/source/runs/source_run/metadata.json", "sha256": "0" * 64},
                },
            }],
        }, indent=2) + "\n", encoding="utf-8")
        return repo, campaign

    def test_refreshes_repository_and_artifact_identities(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, campaign = self._fixture(Path(directory))
            self.assertNotEqual(compile_campaign(repo, campaign), json.loads(campaign.read_text()))
            self.assertTrue(write_campaign(repo, campaign))
            self.assertTrue(is_fresh(repo, campaign))
            self.assertFalse(write_campaign(repo, campaign))

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

    def test_public_workflow_requires_fresh_source_bindings(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / "workflows/family_source_closure/execute.ps1"
        ).read_text(encoding="utf-8-sig")
        self.assertIn("refresh_campaign_source_bindings", workflow)
        self.assertIn("--campaign $campaignPath --check", workflow)


if __name__ == "__main__":
    unittest.main()
