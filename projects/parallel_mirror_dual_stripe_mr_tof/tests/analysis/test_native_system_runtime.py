"""Tests for the compact native system dependency receipt."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_system_runtime import (
    build_native_system_runtime_bundle,
    rebind_accelerator_provider,
    resolve_native_system_runtime_bundle,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import CandidateContractError


def _receipt() -> dict[str, object]:
    return {"schema_version": 1, "role": "mrtof_private_native_corridor_family", "status": "prepared",
            "response_refine_performed": False, "published_native_members_opened": False,
            "controller_refine": "solutions={0}", "cache_key": "A" * 64, "generation_sha256": "B" * 64}


class NativeSystemRuntimeTest(unittest.TestCase):
    def _request(self, root: Path, role: str) -> dict[str, str]:
        pa = root / f"{role}.pa"
        pa.write_bytes(role.encode("ascii"))
        manifest = root / f"{role}.manifest.json"
        manifest.write_text(json.dumps({"status": "success", "project": "parallel_mirror_dual_stripe_mr_tof", "outputs": [{
            "path": str(pa), "bytes": pa.stat().st_size,
            "sha256": hashlib.sha256(pa.read_bytes()).hexdigest().upper(),
        }]}), encoding="utf-8")
        return {"manifest_path": str(manifest), "pa_path": str(pa)}

    def _provider(self, root: Path) -> Path:
        controller = root / "oa.pa0"
        controller.write_bytes(b"provider-controller")
        receipt = root / "provider.json"
        receipt.write_text(json.dumps({
            "role": "orthogonal_accelerator_mrtof_runtime_receipt", "status": "published_read_only",
            "read_only_controller_pa0": {"path": str(controller), "bytes": controller.stat().st_size,
                                           "sha256": hashlib.sha256(controller.read_bytes()).hexdigest()},
            "pa_family": {"cache_key": "C" * 64, "generation_sha256": "D" * 64},
        }), encoding="utf-8")
        return receipt

    def test_binds_existing_pa_identities_without_reading_payload_hashes(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            provider = self._provider(root)
            requests = {role: self._request(root, role) for role in ("global_fallback", "detector")}
            original_read_bytes = Path.read_bytes

            def reject_pa_reads(path: Path) -> bytes:
                if path.suffix.lower() in (".pa", ".pa0"):
                    raise AssertionError("bundle construction must not read PA payloads")
                return original_read_bytes(path)

            with patch.object(Path, "read_bytes", reject_pa_reads):
                bundle = build_native_system_runtime_bundle(native_corridor_runtime_receipt=_receipt(), component_requests=requests,
                                                            accelerator_provider_receipt=provider)
            bundle_path = root / "native_system_runtime_bundle.json"
            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
            paths = resolve_native_system_runtime_bundle(bundle_path, native_corridor_runtime_receipt=_receipt())
        self.assertEqual(paths["accelerator"].name, "oa.pa0")
        self.assertFalse(bundle["pa_copy_performed"])
        self.assertFalse(bundle["pa_refine_performed"])

    def test_requires_bundle_and_detects_changed_static_manifest(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(CandidateContractError, "bundle is required"):
                resolve_native_system_runtime_bundle(None, native_corridor_runtime_receipt=_receipt())
            requests = {role: self._request(root, role) for role in ("global_fallback", "detector")}
            bundle = build_native_system_runtime_bundle(native_corridor_runtime_receipt=_receipt(), component_requests=requests,
                                                        accelerator_provider_receipt=self._provider(root))
            bundle_path = root / "native_system_runtime_bundle.json"
            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
            Path(requests["detector"]["manifest_path"]).write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(CandidateContractError, "source manifest identity changed"):
                resolve_native_system_runtime_bundle(bundle_path, native_corridor_runtime_receipt=_receipt())

    def test_provider_accelerator_reuses_its_receipt_without_reading_pa_payload(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = root / "oa.pa0"
            controller.write_bytes(b"provider-controller")
            provider = root / "provider.json"
            provider.write_text(json.dumps({
                "role": "orthogonal_accelerator_mrtof_runtime_receipt", "status": "published_read_only",
                "read_only_controller_pa0": {"path": str(controller), "bytes": controller.stat().st_size,
                                               "sha256": hashlib.sha256(controller.read_bytes()).hexdigest()},
                "pa_family": {"cache_key": "C" * 64, "generation_sha256": "D" * 64},
            }), encoding="utf-8")
            requests = {role: self._request(root, role) for role in ("global_fallback", "detector")}
            original_read_bytes = Path.read_bytes

            def reject_provider_pa(path: Path) -> bytes:
                if path == controller:
                    raise AssertionError("provider PA payload must not be read by MR bundle binding")
                return original_read_bytes(path)

            with patch.object(Path, "read_bytes", reject_provider_pa):
                bundle = build_native_system_runtime_bundle(native_corridor_runtime_receipt=_receipt(),
                                                            component_requests=requests,
                                                            accelerator_provider_receipt=provider)
            bundle_path = root / "bundle.json"
            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
            self.assertEqual(resolve_native_system_runtime_bundle(bundle_path, native_corridor_runtime_receipt=_receipt())["accelerator"], controller)

    def test_rebind_replaces_only_provider_and_retains_static_records(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            requests = {role: self._request(root, role) for role in ("global_fallback", "detector")}
            provider = self._provider(root)
            bundle = build_native_system_runtime_bundle(
                native_corridor_runtime_receipt=_receipt(), component_requests=requests,
                accelerator_provider_receipt=provider,
            )
            bundle_path = root / "bundle.json"
            bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
            rebound = rebind_accelerator_provider(
                base_bundle_path=bundle_path, native_corridor_runtime_receipt=_receipt(),
                accelerator_provider_receipt=provider,
            )
            self.assertEqual(rebound["components"][0], bundle["components"][0])
            self.assertEqual(rebound["components"][2], bundle["components"][2])
            self.assertFalse(rebound["pa_copy_performed"])
            self.assertFalse(rebound["pa_refine_performed"])

    def test_cli_builds_and_resolves_explicit_identity_paths_without_payload_read(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt_path = root / "native-receipt.json"
            receipt_path.write_text(json.dumps(_receipt()), encoding="utf-8")
            provider = self._provider(root)
            requests = {role: self._request(root, role) for role in ("global_fallback", "detector")}
            bundle_path = root / "native-system-bundle.json"
            build = [sys.executable, "-m", "projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_system_runtime",
                     "build", "--native-corridor-runtime-receipt", str(receipt_path), "--bundle-output", str(bundle_path),
                     "--accelerator-provider-receipt", str(provider)]
            for role, request in requests.items():
                option = role.replace("_", "-")
                build.extend([f"--{option}-manifest", request["manifest_path"], f"--{option}-pa", request["pa_path"]])
            built = subprocess.run(build, cwd=Path(__file__).resolve().parents[4], text=True, capture_output=True, check=False, timeout=30)
            self.assertEqual(built.returncode, 0, built.stderr)
            self.assertEqual(json.loads(built.stdout)["status"], "prepared")
            self.assertTrue(bundle_path.is_file())
            resolved = subprocess.run([
                sys.executable, "-m", "projects.parallel_mirror_dual_stripe_mr_tof.analysis.native_system_runtime",
                "resolve", "--native-corridor-runtime-receipt", str(receipt_path), "--bundle", str(bundle_path),
            ], cwd=Path(__file__).resolve().parents[4], text=True, capture_output=True, check=False, timeout=30)
            self.assertEqual(resolved.returncode, 0, resolved.stderr)
            self.assertEqual(Path(json.loads(resolved.stdout)["accelerator"]), (root / "oa.pa0").resolve())


if __name__ == "__main__":
    unittest.main()
