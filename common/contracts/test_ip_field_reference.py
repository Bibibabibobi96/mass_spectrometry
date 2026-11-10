"""Existing owner-manifest projections; every PA here is inert test data."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
from unittest.mock import patch
import tempfile
import unittest

from msplatform.workflows.ion_processor import field_reference as reference
from projects.dual_pressure_rectilinear_ion_processor.tests import test_functional as fixtures


class IpFieldReferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ip_field_reference_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def fixture(self, name: str = "case", status: str = "success") -> tuple:
        root = self.root / name
        root.mkdir()
        return fixtures.NativeFieldReferenceTests().make_family_fixture(root, status)

    def test_adoption_updates_existing_inputs_with_the_original_owner_reference(self) -> None:
        parent, child, model, family = self.fixture()
        (child / "inputs/resolved_model.json").write_text(json.dumps(model), encoding="utf-8")
        (child / "run_config.json").write_text(json.dumps({"inputs": {"existing": "preserved"}}), encoding="utf-8")
        before = {path: path.read_bytes() for path in family}
        with patch.object(sys, "argv", ["functional", "adopt-native-field", "--run", str(child),
                                        "--native-field-run", str(parent)]):
            fixtures.functional.main()
        config = json.loads((child / "inputs/resolved_model.json").read_text())
        self.assertEqual(config["native_field"]["directory"], str(parent / "simion"))
        self.assertIn('ion_processor_native_field_v1', (child / "simion/frozen_config.lua").read_text())
        inputs = json.loads((child / "run_config.json").read_text())["inputs"]
        self.assertEqual(inputs["existing"], "preserved")
        self.assertEqual(inputs["native_field_manifest"], str(parent / "run_manifest.json"))
        self.assertEqual({path: path.read_bytes() for path in family}, before)
        self.assertFalse(any((child / "simion").glob("*.pa*")))

    def test_original_failed_owner_with_completed_refine_remains_explicitly_usable(self) -> None:
        parent, child, model, family = self.fixture(status="failed")
        result = reference.bind_native_field(child, model, parent)
        self.assertEqual(result["native_field_manifest"], str(parent / "run_manifest.json"))
        self.assertEqual(len(json.loads((child / "inputs/native_field_consumption.json").read_text())["family_records"]), len(family))

    def test_scientific_refine_gem_and_member_metadata_mismatches_reject(self) -> None:
        for mode in ("projection", "refine", "gem", "missing_member", "duplicate_member"):
            with self.subTest(mode=mode):
                parent, child, model, family = self.fixture(mode)
                if mode == "projection":
                    model["native_projection"]["electrode_ids"] = [1]
                elif mode == "refine":
                    model["numerics"]["refine_convergence_v"] = 1e-3
                elif mode == "gem":
                    (child / "simion/processor.gem").write_text("different geometry", encoding="utf-8")
                elif mode == "missing_member":
                    family[-1].unlink()
                else:
                    manifest_path = parent / "run_manifest.json"
                    manifest = json.loads(manifest_path.read_text())
                    manifest["outputs"].append(copy.deepcopy(manifest["outputs"][0]))
                    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with self.assertRaises(ValueError):
                    reference.bind_native_field(child, model, parent)
                self.assertFalse((child / "inputs/native_field_consumption.json").exists())

    def test_incomplete_terminal_publication_propagates_actual_verifier_error(self) -> None:
        parent, child, model, _ = self.fixture()
        (parent / ".run_terminal_publication.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "run terminal publication is incomplete; replay its journal"):
            reference.bind_native_field(child, model, parent)
        self.assertFalse((child / "inputs/native_field_consumption.json").exists())
