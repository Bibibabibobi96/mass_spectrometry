"""Public focus authority comes from the guarded original campaign and model."""
import base64
from contextlib import ExitStack
import copy
import os
from pathlib import Path
import tempfile
import unittest

from msplatform.io.file_identity import canonical_json_sha256
from msplatform.recipes import load_recipe
from msplatform.workflows.native_tracing import _guarded_focus_authority, compile_simion_model
from msplatform.recipes.native import _study
from tests.contracts.test_support.oa_focus_study import make_focus_recipe


class PublicOaFocusAuthorityTests(unittest.TestCase):
    def test_guarded_projection_binds_campaign_contract_and_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            author, original_study, _ = make_focus_recipe(root)
            recipe = load_recipe(author).to_dict()
            duplicate = copy.deepcopy(original_study)
            duplicate["release"] = copy.deepcopy(recipe["study"]["document"]["release"])
            with self.assertRaisesRegex(ValueError, "sole birth request"):
                _study(duplicate, "simion")
            frozen = root / "frozen"
            frozen.mkdir()
            campaign = frozen / "oa_focus_campaign.json"
            campaign.write_bytes(base64.b64decode(recipe["resource_snapshots"]["oa_focus_campaign.json"]["bytes_base64"]))
            model = compile_simion_model(recipe)
            with ExitStack() as stack:
                authority = _guarded_focus_authority(recipe, model, resource_root=frozen, stack=stack)
                self.assertEqual(authority["role"], "oa_focus_plane_authority")
                self.assertEqual(authority["model_sha256"], canonical_json_sha256(model.document))
                from msplatform.backends.simion.operations import _guard_focus_tracking_authority
                with ExitStack() as operation_stack:
                    records = _guard_focus_tracking_authority(authority, model.document, {"lifetime": operation_stack})
                    self.assertEqual({record["path"] for record in records},
                                     {authority["campaign"]["path"], authority["component_contract"]["path"]})
                    forged = copy.deepcopy(authority)
                    forged["focus_z_mm"] += 1
                    with self.assertRaises(ValueError):
                        _guard_focus_tracking_authority(forged, model.document, {"lifetime": operation_stack})
                if os.name == "nt":
                    with self.assertRaises(PermissionError):
                        campaign.unlink()
            from types import SimpleNamespace
            from msplatform.workflows.native_tracing import preflight_native
            exe = root / "simion.exe"
            exe.write_bytes(b"INERT_NOT_SIMION")
            testplane = root / "examples/test_plane/testplanelib.lua"
            testplane.parent.mkdir(parents=True)
            testplane.write_text("-- inert TestPlane fixture", encoding="utf-8")
            context = SimpleNamespace(tools={"simion": exe}, python_executable=exe, powershell_executable=exe,
                                      workspace=root)
            report = preflight_native(recipe, context=context)
            self.assertFalse(report["native_verified"])
            self.assertEqual(report["verification_scope"], "scientific_compilation_only")
            testplane.unlink()
            with self.assertRaisesRegex(ValueError, "TestPlane"):
                preflight_native(recipe, context=context)
            changed = copy.deepcopy(recipe)
            changed["study"]["document"]["component_requests"]["oa"]["design"]["geometry_profile"]["profile_id"] = "forged"
            with self.assertRaises(ValueError), ExitStack() as stack:
                _guarded_focus_authority(changed, model, resource_root=frozen, stack=stack)
            campaign.write_bytes(b"tamper")
            with self.assertRaises((ValueError, OSError)), ExitStack() as stack:
                _guarded_focus_authority(recipe, model, resource_root=frozen, stack=stack)
