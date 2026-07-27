from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common.multipole.simion_layout_template import resolve_simion_layout_template


REPO_ROOT = Path(__file__).resolve().parents[2]


class SimionLayoutTemplateBindingTests(unittest.TestCase):
    def test_active_template_resolves_approved_registration(self) -> None:
        result = resolve_simion_layout_template(REPO_ROOT)
        self.assertEqual(result["template_id"], "shared_single_pa_v1")
        self.assertEqual(
            result["registration_run_id"],
            "20260727_232047__build__simion__multipole-layout-template",
        )
        self.assertEqual(result["manual_gui_review"]["status"], "pass")
        self.assertEqual(Path(result["bundle"]["iob"]["path"]).suffix, ".iob")
        self.assertEqual(Path(result["bundle"]["con"]["path"]).suffix, ".con")

    def test_review_or_evidence_drift_fails_closed(self) -> None:
        source = json.loads(
            (
                REPO_ROOT / "common/multipole/simion_layout_template.json"
            ).read_text(encoding="utf-8")
        )
        cases = (
            ("status", "pending", "manual GUI review"),
            ("scope", "different", "manual GUI review"),
        )
        for key, value, message in cases:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                modified = json.loads(json.dumps(source))
                modified["manual_gui_review"][key] = value
                registry = Path(directory) / "registry.json"
                registry.write_text(json.dumps(modified), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    resolve_simion_layout_template(REPO_ROOT, registry)

        with tempfile.TemporaryDirectory() as directory:
            modified = json.loads(json.dumps(source))
            modified["run_manifest_sha256"] = "0" * 64
            registry = Path(directory) / "registry.json"
            registry.write_text(json.dumps(modified), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifest SHA-256"):
                resolve_simion_layout_template(REPO_ROOT, registry)


if __name__ == "__main__":
    unittest.main()
