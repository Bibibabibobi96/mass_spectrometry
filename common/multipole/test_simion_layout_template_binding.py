from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.artifact_identity_archive import legacy_artifact_location
from common.multipole.simion_layout_template import resolve_simion_layout_template


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_REGISTRY_PATH = REPO_ROOT / "common/multipole/simion_layout_template.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class SimionLayoutTemplateBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        fixture_root = Path(self.temporary_directory.name)
        self.repo_root = fixture_root / "simulation_repo"

        registry = json.loads(SOURCE_REGISTRY_PATH.read_text(encoding="utf-8"))
        provider = registry["provider_project_id"]
        source_descriptor = json.loads(
            (
                REPO_ROOT / "projects" / provider / "config/project.json"
            ).read_text(encoding="utf-8")
        )
        archived_descriptor = {
            "project_id": source_descriptor["project_id"],
            "legacy_identities": source_descriptor["legacy_identities"],
        }
        provider_descriptor = json.loads(json.dumps(archived_descriptor))
        provider_mapping = provider_descriptor["legacy_identities"][0]
        provider_mapping["artifact_location"]["state"] = "source_pending_relocation"
        provider_mapping["artifact_location"]["source_root"] = (
            f"artifacts/projects/{provider_mapping['project_id']}"
        )
        _write_json(
            self.repo_root / "projects" / provider / "config/project.json",
            provider_descriptor,
        )

        evidence_identity = registry["legacy_evidence_identity"]
        artifact_root = legacy_artifact_location(
            provider_mapping, provider_descriptor["project_id"]
        )["active_root"]
        current_artifact_root = (
            fixture_root / "artifacts" / "projects" / provider
        )
        current_artifact_root.mkdir(parents=True)
        run_root = (
            fixture_root
            / artifact_root
            / "runs"
            / registry["registration_run_id"]
        )
        iob_path = run_root / "inputs/template/shared_single_pa.iob"
        con_path = run_root / "inputs/template/shared_single_pa.con"
        iob_path.parent.mkdir(parents=True, exist_ok=True)
        iob_path.write_bytes(b"minimal registered IOB fixture\n")
        con_path.write_bytes(b"minimal registered CON fixture\n")

        _write_json(
            run_root / "run_config.json",
            {
                "role": "multipole_simion_layout_template_build",
                "project": evidence_identity["recorded_project_id"],
                "run_id": registry["registration_run_id"],
                "mode": "simion_layout_template_build",
                "physical_model": False,
                "structural_contract": {
                    "instance_count": 1,
                    "pa_basename": "quad_monolithic.pa0",
                    "transform": {
                        "x": 0,
                        "y": 0,
                        "z": 0,
                        "az": -90,
                        "el": 0,
                        "rt": 180,
                        "scale": 1,
                    },
                },
            },
        )
        _write_json(
            run_root / "summary.json",
            {
                "status": "success",
                "runtime_structure_verified": True,
                "program_executed": False,
                "particle_fly_executed": False,
            },
        )
        report_path = run_root / "logs/simion_layout_structure_report.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            "\n".join(
                (
                    "STATUS=PASS",
                    "INSTANCE_COUNT=1",
                    "INSTANCE_1_TRANSFORM=0,0,0,-90,0,180,1",
                    "PROGRAM_EXECUTED=false",
                    "PARTICLE_FLY_EXECUTED=false",
                )
            )
            + "\n",
            encoding="utf-8",
        )
        manifest_path = run_root / "run_manifest.json"
        _write_json(
            manifest_path,
            {
                "status": "success",
                "run_id": registry["registration_run_id"],
                "project": evidence_identity["recorded_project_id"],
                "inputs": {
                    "template_iob": {
                        "path": str(iob_path),
                        "sha256": _sha256(iob_path),
                    },
                    "template_con": {
                        "path": str(con_path),
                        "sha256": _sha256(con_path),
                    },
                },
            },
        )
        registry["run_manifest_sha256"] = _sha256(manifest_path)
        registry["iob_sha256"] = _sha256(iob_path)
        registry["con_sha256"] = _sha256(con_path)
        self.registry = registry
        self.registry_path = (
            self.repo_root / "common/multipole/simion_layout_template.json"
        )
        _write_json(self.registry_path, registry)

    def _write_modified_registry(self, modified: dict, name: str) -> Path:
        registry_path = self.repo_root / "test_registries" / name
        _write_json(registry_path, modified)
        return registry_path

    def test_active_template_resolves_approved_registration(self) -> None:
        result = resolve_simion_layout_template(self.repo_root)
        self.assertEqual(result["template_id"], "shared_single_pa_v1")
        self.assertEqual(
            result["registration_run_id"],
            "20260727_232047__build__simion__multipole-layout-template",
        )
        self.assertEqual(result["manual_gui_review"]["status"], "pass")
        self.assertEqual(
            result["legacy_evidence_identity"],
            {
                "mapping_id": "rf_quad_rename_20260728",
                "recorded_project_id": "rf_quadrupole_collision_cooling",
                "artifact_access": "read_only",
            },
        )
        self.assertEqual(Path(result["bundle"]["iob"]["path"]).suffix, ".iob")
        self.assertEqual(Path(result["bundle"]["con"]["path"]).suffix, ".con")

    def test_review_drift_fails_closed(self) -> None:
        cases = (
            ("status", "pending", "manual GUI review"),
            ("scope", "different", "manual GUI review"),
        )
        for key, value, message in cases:
            with self.subTest(key=key):
                modified = json.loads(json.dumps(self.registry))
                modified["manual_gui_review"][key] = value
                registry = self._write_modified_registry(
                    modified, f"review_{key}.json"
                )
                with self.assertRaisesRegex(ValueError, message):
                    resolve_simion_layout_template(self.repo_root, registry)

    def test_evidence_drift_fails_closed(self) -> None:
        modified = json.loads(json.dumps(self.registry))
        modified["run_manifest_sha256"] = "0" * 64
        registry = self._write_modified_registry(modified, "manifest_drift.json")
        with self.assertRaisesRegex(ValueError, "manifest SHA-256"):
            resolve_simion_layout_template(self.repo_root, registry)

        modified = json.loads(json.dumps(self.registry))
        modified["legacy_evidence_identity"]["recorded_project_id"] = (
            "rf_quadrupole_ion_optics"
        )
        registry = self._write_modified_registry(
            modified, "legacy_identity_drift.json"
        )
        with self.assertRaisesRegex(ValueError, "legacy evidence identity"):
            resolve_simion_layout_template(self.repo_root, registry)


if __name__ == "__main__":
    unittest.main()
