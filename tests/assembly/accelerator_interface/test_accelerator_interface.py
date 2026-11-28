"""Assembly-owned accelerator interface preparation through a real Store."""

import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from msplatform.workflows.mr_design.accelerator_interface import (
    prepare_interface, verified_preparation_reference,
)
from msplatform.execution.context import ExecutionContext
from msplatform.execution.native_source_guard import guard_historical_run
from msplatform.execution.retention import file_record
from msplatform.storage import ArtifactStore

REPO = Path(__file__).resolve().parents[3]
MR = REPO / "src/msplatform/components/multi_reflection_tof"
RETENTION = {"policy_version": 1, "class": "compact", "reason": None}


def reference_fixture(root: Path, *, frame_id="astral.xyz.v2") -> Path:
    reference = root / "20261022_200000__analysis__python__mr-reference"
    (reference / "simion").mkdir(parents=True)
    config = reference / "run_config.json"
    config.write_text(json.dumps(dict(
        run_id=reference.name, project=MR.name, mode="reference_trajectory", inputs={})), encoding="utf-8")
    trajectory = reference / "simion/trajectory_contract.json"
    trajectory.write_text(json.dumps(dict(coordinate_system=dict(frame_id=frame_id),
        accelerator=dict(focus_y_anchor=dict(project_y_mm=-55)))), encoding="utf-8")
    provider = reference / "simion/accelerator_provider_runtime_receipt.json"
    provider.write_text(json.dumps(dict(
        mrtof_projection=dict(target_axial_energy_per_charge_v=4372))), encoding="utf-8")
    (reference / "run_manifest.json").write_text(json.dumps(dict(
        schema_version=2, role="simulation_run_manifest", run_id=reference.name,
        project=MR.name, mode="reference_trajectory", status="success",
        run_config=file_record(config), inputs={},
        outputs=[file_record(trajectory), file_record(provider)])), encoding="utf-8")
    return reference


def execution_context(root: Path) -> ExecutionContext:
    powershell = shutil.which("pwsh") or sys.executable
    return ExecutionContext(workspace=(root / "workspace").resolve(),
        python_executable=Path(sys.executable).resolve(),
        powershell_executable=Path(powershell).resolve(), tools={},
        host_state_path=(root / "host.sqlite3").resolve(),
        policy_path=(root / "host-policy.json").resolve())


def prepare(root: Path, reference: Path, *, provider="orthogonal_accelerator", run_id=None):
    store = ArtifactStore(root / "store")
    result = prepare_interface(execution_context(root), reference_mr_run=reference,
        artifact_store=store, run_id=run_id or "20261128_120000__analysis__python__interface-preparation",
        committed_new_bytes=16 * 1024 * 1024, retention=RETENTION, provider=provider)
    return store, result


def source_bytes(reference: Path) -> dict[Path, bytes]:
    paths = [reference / name for name in (
        "run_manifest.json", "run_config.json", "simion/trajectory_contract.json",
        "simion/accelerator_provider_runtime_receipt.json")]
    paths += [MR / "config" / name for name in (
        "accelerator_interfaces.json", "accelerator_dependency.json",
        "accelerator_component_request_n100.json", "ion_processor_dependency.json")]
    return {path: path.read_bytes() for path in paths}


class AcceleratorInterfaceTests(unittest.TestCase):
    def test_public_prepare_preserves_scientific_proposal_and_original_bytes(self):
        for provider in ("orthogonal_accelerator", "ion_processor"):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                reference = reference_fixture(root)
                before = source_bytes(reference)
                store, result = prepare(root, reference, provider=provider)
                receipt = result["preparation"]
                self.assertEqual(receipt["reference_requirements"], dict(
                    axial_energy_per_charge_v=4372,
                    energy_definition="exit_axial_kinetic_energy_per_charge",
                    project_y_mm=-55, frame_id="astral.xyz.v2",
                    source="manifest_bound_frozen_reference_not_live_candidate_defaults"))
                self.assertEqual(receipt["selected_provider"], provider)
                self.assertEqual(receipt["next_action"], "author_original_birth_simulation_recipe")
                self.assertFalse(receipt["solver_executed"])
                self.assertFalse(receipt["joint_simulation_executed"])
                self.assertEqual(source_bytes(reference), before)
                self.assertEqual(store.inspect_run(result["store_run_id"]), Path(result["store_run_path"]))
                with guard_historical_run(result["manifest"], expected_project="instrument_assembly",
                                          expected_mode="accelerator_interface_preparation") as published:
                    receipt_path = Path(published.output(
                        "results/accelerator_interface_preparation.json")["path"])
                    self.assertEqual(verified_preparation_reference(published.root,
                        "results/accelerator_interface_preparation.json"), receipt_path)
                    for name, record in receipt["inputs"].items():
                        with self.subTest(provider=provider, input=name):
                            frozen = Path(record["path"])
                            self.assertEqual(frozen.read_bytes(), before[Path(record["source_path"])])
                            self.assertEqual(verified_preparation_reference(published.root,
                                str(frozen.relative_to(published.root))), frozen)

    def test_missing_or_tampered_reference_is_rejected_before_run_admission(self):
        for failure in ("missing_manifest", "missing_trajectory", "tampered_trajectory", "tampered_provider"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                reference = reference_fixture(root)
                target = {
                    "missing_manifest": reference / "run_manifest.json",
                    "missing_trajectory": reference / "simion/trajectory_contract.json",
                    "tampered_trajectory": reference / "simion/trajectory_contract.json",
                    "tampered_provider": reference / "simion/accelerator_provider_runtime_receipt.json",
                }[failure]
                if failure.startswith("missing"):
                    target.unlink()
                else:
                    target.write_text(target.read_text(encoding="utf-8") + " ", encoding="utf-8")
                store = ArtifactStore(root / "store")
                with self.assertRaises((AssertionError, FileNotFoundError, ValueError)):
                    prepare_interface(execution_context(root), reference_mr_run=reference,
                        artifact_store=store, run_id="20261128_120100__analysis__python__interface-negative",
                        committed_new_bytes=16 * 1024 * 1024, retention=RETENTION)
                self.assertFalse(any((store.root / "runs").iterdir()))
                self.assertFalse(any((store.root / "assets").iterdir()))

    def test_unknown_provider_and_implicit_owner_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = reference_fixture(root)
            store = ArtifactStore(root / "store")
            with self.assertRaisesRegex(ValueError, "unknown accelerator provider"):
                prepare_interface(execution_context(root), reference_mr_run=reference,
                    artifact_store=store, run_id="20261128_120200__analysis__python__interface-provider",
                    committed_new_bytes=16 * 1024 * 1024, retention=RETENTION, provider="unknown")
            with self.assertRaisesRegex(TypeError, "explicit ExecutionContext and ArtifactStore"):
                prepare_interface(None, reference_mr_run=reference, artifact_store=store,
                    run_id="20261128_120201__analysis__python__interface-context",
                    committed_new_bytes=16 * 1024 * 1024, retention=RETENTION)
            with self.assertRaisesRegex(TypeError, "explicit ExecutionContext and ArtifactStore"):
                prepare_interface(execution_context(root), reference_mr_run=reference, artifact_store=None,
                    run_id="20261128_120202__analysis__python__interface-store",
                    committed_new_bytes=16 * 1024 * 1024, retention=RETENTION)
            self.assertFalse(any((store.root / "runs").iterdir()))

    def test_duplicate_run_id_preserves_existing_publication_and_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = reference_fixture(root)
            store, first = prepare(root, reference)
            before = source_bytes(reference)
            manifest_bytes = Path(first["manifest"]["path"]).read_bytes()
            with self.assertRaises((FileExistsError, ValueError)):
                prepare_interface(execution_context(root), reference_mr_run=reference,
                    artifact_store=store, run_id="20261128_120000__analysis__python__interface-preparation",
                    committed_new_bytes=16 * 1024 * 1024, retention=RETENTION)
            self.assertEqual(Path(first["manifest"]["path"]).read_bytes(), manifest_bytes)
            self.assertEqual(source_bytes(reference), before)
            self.assertEqual(store.inspect_run(first["store_run_id"]), Path(first["store_run_path"]))

    def test_replaced_private_entry_module_and_container_are_absent(self):
        self.assertFalse((REPO / "src/msplatform/workflows/resources/accelerator_interface.ps1").exists())
        self.assertIsNone(importlib.util.find_spec("msplatform.workflows.accelerator_interface"))


if __name__ == "__main__":
    unittest.main()
