from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from projects.single_reflection_oa_tof_mass_analyzer.analysis import (
    publish_formal_release as promotion,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis import (
    verify_formal_validation as validation_gate,
)


CANDIDATE_ID = "20260729_100000__build__cross__formal-vnext-candidate__n100"
VALIDATION_ID = "20260729_110000__sim__cross__formal-vnext-validation__n1000"
EVIDENCE_ID = "20260729_120000__test__cross__formal-vnext-gui-evidence__n1000"
SIMION_SOURCES = {
    "simion_iob": ("model.iob", "oatof_ideal_grounded.iob"),
    "simion_con": ("model.con", "oatof_ideal_grounded.con"),
    "simion_program": ("model.lua", "oatof_ideal_grounded.lua"),
    "simion_fly2": ("model.fly2", "oatof_ideal_grounded.fly2"),
    "shared_particle_table": ("source_N1000.ion", "oatof_comsol_524amu_gaussian_N1000.ion"),
}
PA_FILES = ("accelerator.pa#", "accelerator.pa0", "reflectron.pa#",
            "detector_ground.pa#", "flight_tube_ground.pa#")
PARTIAL_SIMION_FILES = {
    *(canonical for _, canonical in SIMION_SOURCES.values()),
    "run_manifest.json",
    "SHA256SUMS.csv",
}
DESTINATIONS = {
    **promotion.CANONICAL_DESTINATIONS,
    "comsol_particles": "results/comsol_particles.csv",
    "comsol_report": "results/comsol_report.txt",
    "simion_particles": "results/simion_particles.csv",
    "simion_summary": "results/simion_summary.json",
    "comparison": "results/comparison_metrics.json",
}
RUN_JSON = {
    ("candidate", "summary.json"): {
        "role": "oa_tof_candidate_run_summary", "status": "success",
        "candidate_decision": "candidate_accepted_not_promoted",
        "formal_modified": False, "promotion_authorized": False},
    ("candidate", "inputs/candidate_diff.json"): {
        "zero_change_reference_reproduction": True,
        "changed_variables": [], "derived_changes": []},
    ("candidate", "results/candidate_acceptance.json"): {
        "role": "oa_tof_candidate_acceptance", "status": "success",
        "formal_modified": False, "promotion_authorized": False},
    ("validation", "summary.json"): {
        "role": "oa_tof_formal_vnext_validation_summary", "status": "success",
        "particles": 1000, "formal_modified": False, "promotion_authorized": False},
    ("evidence", "summary.json"): {
        "role": "oa_tof_formal_vnext_gui_evidence_summary", "status": "success"},
}


def write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return path


def manifest_record(path: Path) -> dict:
    return {"path": str(path.resolve()), "bytes": path.stat().st_size,
            "sha256": promotion.sha256(path)}


class FormalReleasePublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifact = self.root / "artifacts" / promotion.PROJECT_ID
        self.runs = self.artifact / "runs"
        self.candidate = self.runs / CANDIDATE_ID
        self.validation = self.runs / VALIDATION_ID
        self.evidence = self.runs / EVIDENCE_ID
        self.repository = self.root / "repository"
        self.project = self.repository / "projects" / promotion.PROJECT_ID
        self.config_paths = {name: self.project / "config" / f"{name}.json"
                             for name in promotion.CONFIG_PATHS}
        for name, path in self.config_paths.items():
            write_json(path, self._initial_config(name))
        for target, value in (
            ("CONFIG_PATHS", self.config_paths),
            ("PROJECT_ROOT", self.project),
            ("REPOSITORY_ROOT", self.repository),
        ):
            patcher = mock.patch.object(promotion, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        write_json(self.project / "config" / "baseline.json", {"baseline": 1})
        write_json(self.project / "config/analysis_contract.json", {"analysis": 1})
        self.request = self._make_fixture()

    @staticmethod
    def _initial_config(name: str) -> dict:
        if name != "project":
            return {"original": name}
        return {
            "schema_version": 1, "project_id": promotion.PROJECT_ID,
            "lifecycle_status": "formal_revalidation_pending",
            "capabilities": [{
                "capability_id": "single_reflection_mass_analysis", "status": "candidate",
            }],
            "formal_assets": {"status": "candidate"},
        }

    @staticmethod
    def _comparison(left_csv: Path, right_csv: Path) -> dict:
        def side(label: str, path: Path, resolution: float) -> dict:
            detector = {
                "impact_centroid_x_mm": 0.0, "impact_centroid_y_mm": 0.0,
                "impact_rms_radius_mm": 4.0,
            }
            return {
                "label": label, "sha256": promotion.sha256(path),
                "import": {"hit_fraction": 1.0},
                "metrics": {
                    "particles": 1000, "mean_tof_us": 71.35,
                    "direct_fwhm_tof_ns": 0.8, "direct_fwhm_mass_Da": 0.012,
                    "mass_resolution": resolution, "tof_skewness": 0.0,
                    "hwhm_asymmetry_right_over_left": 1.0,
                    "significant_kde_modes": 1, "detector": detector,
                },
            }

        landing = {
            "centroid_distance_mm": 0.1, "paired_mean_landing_distance_mm": 0.2,
            "paired_rms_landing_distance_mm": 0.3,
            "paired_max_landing_distance_mm": 0.4,
        }
        return {
            "schema_version": 3, "status": "PASS",
            "left": side("COMSOL", left_csv, 42000.0),
            "right": side("SIMION", right_csv, 48000.0),
            "comparison": {
                "mean_tof_difference_right_minus_left_ns": 0.7,
                "standardized_kde_overlap": 0.7, "standardized_ks_distance": 0.1,
                "standardized_ks_pvalue": 0.2,
                "paired_standardized_tof_correlation": 0.8,
                "bootstrap_absolute_resolution_difference_pct_p2p5": 8.0,
                "bootstrap_absolute_resolution_difference_pct_median": 12.0,
                "bootstrap_absolute_resolution_difference_pct_p97p5": 16.0,
                "paired_bootstrap": {"resamples_valid": 100, "seed": 20260729},
                "paired_tof_difference": {"rms_ns": 1.0},
                "detector_landing": landing,
            },
        }

    def _asset(self, run: Path, relative: str, content: bytes = b"asset") -> Path:
        path = run / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def _write_run_manifest(self, run: Path, run_id: str) -> None:
        config = run / "run_config.json"
        if not config.exists():
            write_json(
                config,
                {"schema_version": 1, "run_id": run_id,
                 "project": promotion.PROJECT_ID},
            )
        outputs = [
            manifest_record(path)
            for path in sorted(run.rglob("*"))
            if path.is_file()
            and path.name not in {"run_config.json", "run_manifest.json"}
        ]
        write_json(
            run / "run_manifest.json",
            {
                "schema_version": 1, "status": "success", "run_id": run_id,
                "project": promotion.PROJECT_ID,
                "run_config": manifest_record(config), "outputs": outputs,
            },
        )

    def _make_fixture(self) -> Path:
        run_roots = {"candidate": self.candidate, "validation": self.validation,
                     "evidence": self.evidence}
        for (scope, relative), payload in RUN_JSON.items():
            write_json(run_roots[scope] / relative, payload)
        source_assets = {
            "comsol_model": ("candidate",
                             self._asset(self.candidate, "comsol/candidate.mph")),
            "solidworks_assembly": (
                "candidate", self._asset(self.candidate, "cad/model.SLDASM")),
        }
        cad_report = write_json(
            self.candidate / "cad/report.json",
            {
                "solidWorks": {
                    "solidWorksRevision": "30.5.0", "partCount": 25,
                    "assembly": {"componentCount": 25, "saveErrors": 0,
                                 "saveWarnings": 0},
                }
            },
        )
        source_assets["cad_export_report"] = ("candidate", cad_report)
        validation_assets = {
            "comsol_particles": self._asset(
                self.validation, "results/comsol.csv", b"id,tof\n1,1\n"),
            "simion_particles": self._asset(
                self.validation, "results/simion.csv", b"id,tof\n1,1\n"),
        }
        validation_assets["comsol_report"] = self._asset(
            self.validation, "results/comsol_report.txt",
            b"STATUS=PASS\nMESH_ELEMENTS=336867\n",
        )
        validation_assets["simion_summary"] = write_json(
            self.validation / "results/simion_summary.json", {"Hit": 1000, "Emitted": 1000},
        )
        validation_assets["comparison"] = write_json(
            self.validation / "results/comparison.json",
            self._comparison(validation_assets["comsol_particles"],
                             validation_assets["simion_particles"]),
        )

        bundle = self.validation / "inputs/simion"
        for role, (source_name, canonical_name) in SIMION_SOURCES.items():
            content = (
                ("\n".join(map(str, range(1000))) + "\n").encode()
                if role == "shared_particle_table"
                else b"asset"
            )
            candidate_source = self._asset(
                self.candidate, f"simion/{source_name}", content)
            bundled = self._asset(
                self.validation, f"inputs/simion/{canonical_name}",
                candidate_source.read_bytes(),
            )
            source_assets[role] = ("validation", bundled)
        for name in PA_FILES:
            self._asset(self.validation, f"inputs/simion/{name}", name.encode())
        promotion.write_hash_list(bundle)
        source_assets.update({role: ("validation", path)
                              for role, path in validation_assets.items()})

        for name, (evidence_role, reviewed_roles) in promotion.GUI_CONTRACTS.items():
            write_json(
                self.evidence / f"{name}.json",
                {
                    "schema_version": 1, "role": evidence_role,
                    "project": promotion.PROJECT_ID, "status": "PASS",
                    "reviewed_assets": {
                        role: promotion.sha256(source_assets[role][1])
                        for role in reviewed_roles
                    },
                },
            )
        for run, run_id in (
            (self.candidate, CANDIDATE_ID),
            (self.validation, VALIDATION_ID),
            (self.evidence, EVIDENCE_ID),
        ):
            self._write_run_manifest(run, run_id)

        request = self.root / "promotion_request.json"
        evidence = {
            "candidate_acceptance": {
                "source_run": "candidate", "path": "results/candidate_acceptance.json",
            },
            **{name: {"source_run": "evidence", "path": f"{name}.json"}
               for name in promotion.GUI_CONTRACTS},
        }
        assets = [
            {
                "role": role, "source_run": scope,
                "source": path.relative_to(
                    self.candidate if scope == "candidate" else self.validation
                ).as_posix(),
                "destination": DESTINATIONS[role],
            }
            for role, (scope, path) in source_assets.items()
        ]
        write_json(
            request,
            {
                "schema_version": 1, "role": "oa_tof_formal_vnext_promotion_request",
                "project": promotion.PROJECT_ID,
                "candidate_run_id": CANDIDATE_ID, "validation_run_id": VALIDATION_ID,
                "evidence_run_id": EVIDENCE_ID, "evidence": evidence, "assets": assets,
                "simion_bundle": {
                    "source_run": "validation", "source_root": "inputs/simion",
                    "destination": "simion",
                }
            },
        )
        return request

    def _config_snapshot(self) -> dict[str, bytes]:
        return {name: path.read_bytes() for name, path in self.config_paths.items()}

    def _assert_rejected(self, message: str) -> None:
        with self.assertRaisesRegex((ValueError, FileNotFoundError), message):
            promotion.promote(self.request, self.artifact)
        self.assertFalse((self.artifact / "formal").exists())

    def _rewrite_evidence_sha(self, evidence_name: str, role: str) -> None:
        path = self.evidence / f"{evidence_name}.json"
        evidence = json.loads(path.read_text())
        evidence["reviewed_assets"][role] = "0" * 64
        write_json(path, evidence)
        self._write_run_manifest(self.evidence, EVIDENCE_ID)

    @staticmethod
    def _failing_replace(fail_on: int, message: str):
        calls = 0

        def replace(source: os.PathLike, destination: os.PathLike) -> None:
            nonlocal calls
            calls += 1
            if calls == fail_on:
                raise OSError(message)
            os.replace(source, destination)

        return replace

    def _make_current_release_partial(self) -> None:
        formal = self.artifact / "formal"
        simion = formal / "simion"
        for path in simion.iterdir():
            if path.name not in PARTIAL_SIMION_FILES:
                path.unlink()
        sha_manifest = promotion.write_hash_list(
            simion, exclude=frozenset({"run_manifest.json"})
        )
        delivery = write_json(
            simion / "run_manifest.json",
            {
                "schema_version": 1, "role": "oa_tof_simion_formal_delivery_manifest",
                "project": promotion.PROJECT_ID, "release_id": VALIDATION_ID,
                "status": "success", "assets": {},
            },
        )
        validation = json.loads(self.config_paths["formal_validation"].read_text())
        validation["simion"]["delivery_manifest_sha256"] = promotion.sha256(delivery)
        write_json(self.config_paths["formal_validation"], validation)
        manifest = json.loads((formal / "asset_manifest.json").read_text())
        manifest["assets"] = {
            role: item
            for role, item in manifest["assets"].items()
            if not item["path"].startswith("simion/")
            or Path(item["path"]).name in PARTIAL_SIMION_FILES
        }
        for role, path in (("simion_delivery_manifest", delivery),
                           ("simion_sha256_manifest", sha_manifest)):
            manifest["assets"][role] = promotion.file_record(path, formal)
        validation_bytes = self.config_paths["formal_validation"].read_bytes()
        manifest["validation_contract"].update(
            bytes=len(validation_bytes),
            sha256=hashlib.sha256(validation_bytes).hexdigest().upper(),
        )
        write_json(formal / "asset_manifest.json", manifest)
        stable = json.loads(self.config_paths["simion_stable_entry"].read_text())
        stable["entries"][0]["manifests"] = {
            "formal_asset_manifest": promotion.file_record(
                formal / "asset_manifest.json", formal, key="relative_path"),
            "simion_delivery_manifest": promotion.file_record(delivery, formal, key="relative_path"),
        }
        write_json(self.config_paths["simion_stable_entry"], stable)

    def test_success_publishes_atomic_release_and_updates_four_contracts(self) -> None:
        source_manifests = (
            self.candidate / "run_manifest.json",
            self.validation / "run_manifest.json",
        )
        immutable_hashes = {path: promotion.sha256(path) for path in source_manifests}
        result = promotion.promote(self.request, self.artifact)
        formal = self.artifact / "formal"
        self.assertEqual(result["status"], "success")
        self.assertEqual(set(self.config_paths),
                         {"formal_assets", "simion_stable_entry",
                          "formal_validation", "project"})
        self.assertTrue(
            all(json.loads(path.read_text()) != self._initial_config(name)
                for name, path in self.config_paths.items())
        )
        project = json.loads(self.config_paths["project"].read_text())
        validation = json.loads(self.config_paths["formal_validation"].read_text())
        stable = json.loads(self.config_paths["simion_stable_entry"].read_text())
        manifest = json.loads((formal / "asset_manifest.json").read_text())
        self.assertEqual(project["lifecycle_status"], "formal")
        self.assertEqual(validation["schema_version"], 5)
        self.assertEqual(validation["shared_particles"]["particles"], 1000)
        evidence_path = validation["promotion_evidence"][
            "evidence_run_manifest_artifact_relative_path"
        ]
        self.assertIn(f"runs/{EVIDENCE_ID}/run_manifest.json", evidence_path)
        self.assertEqual(immutable_hashes,
                         {path: promotion.sha256(path) for path in source_manifests})
        entry = stable["entries"][0]
        self.assertNotIn("assets", entry)
        manifest_paths = {"formal_asset_manifest": formal / "asset_manifest.json",
                          "simion_delivery_manifest": formal / "simion/run_manifest.json"}
        for name, path in manifest_paths.items():
            self.assertEqual(entry["manifests"][name],
                             promotion.file_record(path, formal, key="relative_path"))
        self.assertEqual(set(entry["required_assets"].values()), set(SIMION_SOURCES))
        self.assertTrue((formal / "simion/accelerator.pa#").is_file())
        self.assertTrue((formal / "simion/source_SHA256SUMS.csv").is_file())
        self.assertEqual(manifest["validation_contract"]["sha256"],
                         promotion.sha256(self.config_paths["formal_validation"]))
        with (
            mock.patch.object(validation_gate, "PROJECT_DIR", self.project),
            mock.patch.object(validation_gate, "ARTIFACT_ROOT", self.artifact),
            mock.patch.object(validation_gate, "CONFIG_PATH",
                              self.config_paths["formal_validation"]),
        ):
            validation_gate.main()

    def test_candidate_source_tamper_fails_before_publication(self) -> None:
        (self.candidate / "comsol/candidate.mph").write_bytes(b"tampered")
        self._assert_rejected("manifest record changed")

    def test_comsol_gui_reviewed_asset_sha_mismatch_is_rejected(self) -> None:
        self._rewrite_evidence_sha("comsol_gui", "comsol_model")
        self._assert_rejected("comsol_gui evidence SHA differs")

    def test_cad_reviewed_asset_sha_mismatch_is_rejected(self) -> None:
        self._rewrite_evidence_sha("cad", "solidworks_assembly")
        self._assert_rejected("cad evidence SHA differs")

    def test_simion_bundle_missing_required_pa_family_is_rejected(self) -> None:
        (self.validation / "inputs/simion/accelerator.pa#").unlink()
        promotion.write_hash_list(self.validation / "inputs/simion")
        self._write_run_manifest(self.validation, VALIDATION_ID)
        self._assert_rejected("lacks required PA")

    def test_request_missing_delivery_asset_role_is_rejected(self) -> None:
        request = json.loads(self.request.read_text())
        request["assets"] = [
            item for item in request["assets"] if item["role"] != "simion_fly2"
        ]
        write_json(self.request, request)
        self._assert_rejected("promotion request lacks roles")

    def test_same_release_partial_formal_is_repaired_without_deletion(self) -> None:
        promotion.promote(self.request, self.artifact)
        self._make_current_release_partial()
        result = promotion.promote(self.request, self.artifact)
        backup = Path(result["repair_backup"])
        self.assertTrue(
            (self.artifact / "formal/simion/accelerator.pa#").is_file()
        )
        self.assertTrue((backup / "archive_manifest.json").is_file())
        self.assertEqual({path.name for path in (backup / "simion").iterdir()},
                         PARTIAL_SIMION_FILES)

    def test_same_release_repair_rolls_back_formal_swap_and_configs(self) -> None:
        promotion.promote(self.request, self.artifact)
        self._make_current_release_partial()
        original_configs = self._config_snapshot()
        with self.assertRaisesRegex(OSError, "injected repair"):
            promotion.promote(
                self.request,
                self.artifact,
                replace=self._failing_replace(3, "injected repair config failure"),
            )
        self.assertEqual(
            {path.name for path in (self.artifact / "formal/simion").iterdir()},
            PARTIAL_SIMION_FILES,
        )
        self.assertEqual(original_configs, self._config_snapshot())

    def test_unrecognized_existing_formal_root_fails_closed(self) -> None:
        formal = self.artifact / "formal"
        formal.mkdir(parents=True)
        original_configs = self._config_snapshot()
        with self.assertRaises(FileExistsError):
            promotion.promote(self.request, self.artifact)
        self.assertEqual(list(formal.iterdir()), [])
        self.assertEqual(original_configs, self._config_snapshot())

    def test_config_replace_failure_rolls_back_release_and_contracts(self) -> None:
        original_configs = self._config_snapshot()
        with self.assertRaisesRegex(OSError, "injected config"):
            promotion.promote(
                self.request,
                self.artifact,
                replace=self._failing_replace(3, "injected config replace failure"),
            )
        self.assertFalse((self.artifact / "formal").exists())
        self.assertEqual(original_configs, self._config_snapshot())
        self.assertEqual(
            len(list(self.artifact.glob(".formal-vnext-staging-*"))), 1
        )


if __name__ == "__main__":
    unittest.main()
