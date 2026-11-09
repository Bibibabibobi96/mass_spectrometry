from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from projects.single_reflection_oa_tof_mass_analyzer.analysis import publish_ideal_acceptance_aperture_comparison as publisher


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class PublishIdealAcceptanceApertureComparisonTest(unittest.TestCase):
    def _campaign_and_runs(self, root: Path, mode: str) -> tuple[Path, Path]:
        campaign_id = publisher.MODES[mode][0]
        rows = [{"run_id": f"arm-{index:02d}"} for index in range(1, 9)]
        campaign = root / f"{mode}.json"
        campaign.write_text(json.dumps({"campaign_id": campaign_id, "experiments": {"rows": rows}}), encoding="utf-8")
        runs = root / "runs"
        for row in rows:
            parent = runs / row["run_id"]
            parent.mkdir(parents=True)
            manifest: dict[str, object] = {"role": "simulation_run_manifest", "status": "success"}
            if mode == "full-flight":
                child = parent / "child_manifest.json"
                child.write_text(json.dumps({"role": "simulation_run_manifest", "status": "success"}), encoding="utf-8")
                manifest["inputs"] = {"single_flight_transport_manifest": {"path": str(child), "sha256": _sha(child)}}
            (parent / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return campaign, runs

    @staticmethod
    def _reader_result(campaign_path: Path, *, qualification: str) -> dict:
        return {
            "schema_version": 1,
            "role": "test_aperture_comparison",
            "qualification": qualification,
            "campaign": {"path": str(campaign_path.resolve()), "sha256": _sha(campaign_path)},
            "arms": [{"id": index} for index in range(8)],
        }

    def _run_dir(self, root: Path, name: str) -> Path:
        return root / "artifacts" / "projects" / publisher.PROJECT_ID / "runs" / name

    def test_publishes_pre_pulse_result_with_all_arm_manifest_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign, runs = self._campaign_and_runs(root, "pre-pulse")
            reader = lambda **_: self._reader_result(campaign, qualification="DETECTOR_BLIND_SOURCE_ONLY")
            with patch.dict(publisher.MODES, {"pre-pulse": (publisher.MODES["pre-pulse"][0], publisher.MODES["pre-pulse"][1], reader)}):
                summary = publisher.publish_aperture_comparison(
                    campaign_path=campaign, runs_root=runs,
                    run_dir=self._run_dir(root, "20260828_120000__analysis__python__aperture-pre-pulse"),
                    mode="pre-pulse", workspace_root=root,
                )
            run_dir = self._run_dir(root, "20260828_120000__analysis__python__aperture-pre-pulse")
            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
            result_exists = (run_dir / "results" / "ideal_acceptance_300mm_aperture_pre_pulse_comparison.json").is_file()
            snapshot = run_dir / "inputs" / "repository_snapshot"
            for name, relative in (
                ("longitudinal_fit_implementation", "src/msplatform/analysis/longitudinal_fit.py"),
                ("core_package_implementation", "src/msplatform/__init__.py"),
                ("analysis_package_implementation", "src/msplatform/analysis/__init__.py"),
                ("io_package_implementation", "src/msplatform/io/__init__.py"),
                ("io_file_identity_implementation", "src/msplatform/io/file_identity.py"),
            ):
                self.assertEqual(manifest["inputs"][name]["sha256"], _sha(snapshot / relative))
                self.assertEqual((snapshot / relative).read_bytes(),
                                 (publisher.REPOSITORY_ROOT / relative).read_bytes())
            # A real regular package later on sys.path must neither override the
            # frozen package nor fill a missing member. Editable-only environments
            # cannot expose that namespace-package fallback.
            installed = root / "installed-control"
            for relative in ("__init__.py", "analysis/__init__.py", "analysis/longitudinal_fit.py",
                             "io/__init__.py", "io/file_identity.py"):
                source = publisher.REPOSITORY_ROOT / "src/msplatform" / relative
                target = installed / "msplatform" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            command = (
                [sys.executable, "-I", "-S", "-c",
                 "import sys, sysconfig; from pathlib import Path; "
                 "venv = Path(sys.executable).resolve().parent.parent; "
                 "sys.path.append(sysconfig.get_paths(vars={'base': str(venv), 'platbase': str(venv)})['purelib']); "
                 "sys.path[:0] = [sys.argv[2], sys.argv[1]]; "
                 "sys.path.insert(2, sys.argv[3]); "
                 "import msplatform.analysis.longitudinal_fit as fit; "
                 "from msplatform.io.file_identity import file_sha256; "
                 "from projects.single_reflection_oa_tof_mass_analyzer.analysis import analyze_ideal_acceptance_aperture_campaign as pre, analyze_ideal_acceptance_aperture_full_flight as full; "
                 "import numpy as np; "
                 "assert Path(fit.__file__).resolve() == Path(sys.argv[2]) / 'msplatform/analysis/longitudinal_fit.py'; "
                 "assert Path(file_sha256.__code__.co_filename).resolve() == Path(sys.argv[2]) / 'msplatform/io/file_identity.py'; "
                 "assert pre._sha256 is file_sha256 and full._sha256 is file_sha256; "
                 "assert all(Path(module.__file__).resolve().is_relative_to(Path(sys.argv[2])) for name, module in sys.modules.items() if name == 'msplatform' or name.startswith('msplatform.')); "
                 "assert 'msplatform.execution' not in sys.modules; "
                 "assert abs(fit.fit_longitudinal_polynomial(np.arange(3.), np.arange(3.), 1).metrics['k_per_us'] - 1) < 1e-12",
                 str(snapshot), str(snapshot / "src"), str(installed)]
            )
            probe = subprocess.run(
                command,
                cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(probe.returncode, 0, probe.stderr)
            dependency = snapshot / "src/msplatform/io/file_identity.py"
            dependency.unlink()
            missing = subprocess.run(command, cwd=root, capture_output=True, text=True,
                                     encoding="utf-8", timeout=30)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("msplatform.io.file_identity", missing.stderr)

        self.assertEqual(summary["qualification"], "DETECTOR_BLIND_SOURCE_ONLY")
        self.assertEqual(len(manifest["inputs"]), 17)
        self.assertTrue(result_exists)
        self.assertFalse(manifest["formal_eligible"])

    def test_publishes_full_flight_and_binds_child_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign, runs = self._campaign_and_runs(root, "full-flight")
            reader = lambda **_: self._reader_result(campaign, qualification="REAL_FIELD_EXPLORATORY_ONLY")
            with patch.dict(publisher.MODES, {"full-flight": (publisher.MODES["full-flight"][0], publisher.MODES["full-flight"][1], reader)}):
                publisher.publish_aperture_comparison(
                    campaign_path=campaign, runs_root=runs,
                    run_dir=self._run_dir(root, "20260828_120100__analysis__python__aperture-full-flight"),
                    mode="full-flight", workspace_root=root,
                )
            manifest = json.loads((self._run_dir(root, "20260828_120100__analysis__python__aperture-full-flight") / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["inputs"]), 25)
        self.assertIn("arm_01_single_flight_manifest", manifest["inputs"])

    def test_installed_module_outside_checkout_is_frozen_from_actual_bytes(self) -> None:
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign, runs = self._campaign_and_runs(root, "pre-pulse")
            installed = root / "installed/msplatform/analysis/longitudinal_fit.py"
            installed.parent.mkdir(parents=True)
            installed.write_bytes((publisher.REPOSITORY_ROOT / "src/msplatform/analysis/longitudinal_fit.py").read_bytes())
            reader = lambda **_: self._reader_result(campaign, qualification="DETECTOR_BLIND_SOURCE_ONLY")
            run_dir = self._run_dir(root, "20260828_120050__analysis__python__aperture-installed")
            with (patch.object(publisher, "longitudinal_fit", SimpleNamespace(__file__=installed)),
                  patch.dict(publisher.MODES, {"pre-pulse": (publisher.MODES["pre-pulse"][0], publisher.MODES["pre-pulse"][1], reader)})):
                publisher.publish_aperture_comparison(campaign_path=campaign, runs_root=runs,
                    run_dir=run_dir, mode="pre-pulse", workspace_root=root)
            frozen = run_dir / "inputs/repository_snapshot/src/msplatform/analysis/longitudinal_fit.py"
            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(frozen.read_bytes(), installed.read_bytes())
            self.assertEqual(manifest["inputs"]["longitudinal_fit_implementation"]["sha256"], _sha(installed))

    def test_reader_failure_leaves_no_published_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign, runs = self._campaign_and_runs(root, "pre-pulse")
            run_dir = self._run_dir(root, "20260828_120200__analysis__python__aperture-reader-failure")
            def reject(**_: object) -> dict:
                raise ValueError("identity drift")
            with patch.dict(publisher.MODES, {"pre-pulse": (publisher.MODES["pre-pulse"][0], publisher.MODES["pre-pulse"][1], reject)}):
                with self.assertRaisesRegex(ValueError, "identity drift"):
                    publisher.publish_aperture_comparison(campaign_path=campaign, runs_root=runs, run_dir=run_dir, mode="pre-pulse", workspace_root=root)
            self.assertFalse(run_dir.exists())


if __name__ == "__main__":
    unittest.main()
