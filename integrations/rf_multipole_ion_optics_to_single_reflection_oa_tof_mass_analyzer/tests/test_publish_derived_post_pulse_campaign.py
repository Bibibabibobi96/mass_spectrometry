from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure import (
    publish_derived_post_pulse_campaign as subject,
)


class PublishDerivedPostPulseCampaignTests(unittest.TestCase):
    def test_requires_exactly_one_restart_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common = {
                "repo_root": root,
                "parent_manifest": root / "parent_manifest.json",
                "output_run_dir": root / (
                    "20260904_120000__analysis__python__derived-post-pulse__n1"
                ),
            }
            with self.assertRaisesRegex(ContractError, "exactly one restart evidence"):
                subject.publish(**common)
            with self.assertRaisesRegex(ContractError, "exactly one restart evidence"):
                subject.publish(
                    **common,
                    compact_receipt=root / "compact_receipt.json",
                    materialization_manifest=root / "materialization_manifest.json",
                )

    def test_forwards_each_evidence_kind_and_records_its_role(self) -> None:
        expected_campaign = {
            "campaign_id": "fixture_derived_post_pulse",
            "experiments": {
                "rows": [{"experiment_id": "fixture_post_pulse"}],
                "shared": {"source_release_mode": "pre_pulse_restart"},
            },
        }
        for evidence_keyword, evidence_role, derive_keyword in (
            ("compact_receipt", "compact_receipt", "compact_receipt_path"),
            (
                "materialization_manifest",
                "materialization_manifest",
                "materialization_manifest_path",
            ),
        ):
            with self.subTest(evidence_role=evidence_role), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                parent = root / "parent_manifest.json"
                evidence = root / f"{evidence_role}.json"
                parent.write_text("{}\n", encoding="utf-8")
                evidence.write_text("{}\n", encoding="utf-8")
                output = root / (
                    "20260904_120000__analysis__python__derived-post-pulse__n1"
                )
                with (
                    patch.object(subject, "derive_campaign", return_value=expected_campaign) as derive,
                    patch.object(
                        subject.subprocess,
                        "run",
                        return_value=SimpleNamespace(returncode=0, stderr="", stdout=""),
                    ),
                ):
                    campaign_path = subject.publish(
                        repo_root=root,
                        parent_manifest=parent,
                        output_run_dir=output,
                        **{evidence_keyword: evidence},
                    )

                self.assertEqual(campaign_path, output / "results" / "derived_post_pulse_campaign.json")
                arguments = derive.call_args.kwargs
                self.assertEqual(arguments[derive_keyword], evidence.resolve())
                self.assertIsNone(
                    arguments[
                        "materialization_manifest_path"
                        if derive_keyword == "compact_receipt_path"
                        else "compact_receipt_path"
                    ]
                )
                run_config = json.loads((output / "run_config.json").read_text(encoding="utf-8"))
                self.assertEqual(
                    run_config["inputs"],
                    {
                        "parent_manifest": str(parent.resolve()),
                        evidence_role: str(evidence.resolve()),
                    },
                )


if __name__ == "__main__":
    unittest.main()
