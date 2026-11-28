"""Wehnelt public model wiring; every native observation here is explicitly inert."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from msplatform import cli
from msplatform.backends.comsol import model_execution, wehnelt_model
from tests.components.transverse_helical_filament_wehnelt_electron_gun.test_input_admission import write_compiled_inputs
from tests.contracts.test_support.comsol_model import InertComsolSession

PROJECT = Path(__file__).resolve().parents[2] / "src/msplatform/components/transverse_helical_filament_wehnelt_electron_gun"


def inputs():
    return tuple(json.loads((PROJECT / "config" / name).read_text(encoding="utf-8"))
                 for name in ("baseline.json", "numerical_modes.json"))


class WehneltModelTests(unittest.TestCase):
    def test_request_preserves_editable_design_and_explicit_electron_inlet_count(self):
        baseline, modes = inputs()
        baseline["filament"]["temperature_K"] += 10
        original = copy.deepcopy((baseline, modes))
        resolved = wehnelt_model.resolve_wehnelt_build_request(baseline, modes,
            mode_id="build_only_smoke", evidence_particle_count=3)
        self.assertEqual(resolved["evidence"]["requested_particle_count"], 3)
        self.assertEqual(resolved["physical"]["particle"]["charge_state"], -1)
        self.assertEqual(resolved["physical"]["filament"]["temperature_K"], baseline["filament"]["temperature_K"])
        self.assertEqual((baseline, modes), original)
        with self.assertRaisesRegex(ValueError, "explicit particle count"):
            wehnelt_model.resolve_wehnelt_build_request(baseline, modes,
                mode_id="build_only_smoke", evidence_particle_count=None)
        with self.assertRaisesRegex(ValueError, "build_only"):
            wehnelt_model.resolve_wehnelt_build_request(baseline, modes,
                mode_id="functional_reference", evidence_particle_count=100)

    def test_three_saved_stages_use_same_owner_transport_and_separate_cold_process(self):
        with tempfile.TemporaryDirectory() as directory:
            session = InertComsolSession(Path(directory), model_relative_paths=wehnelt_model.NATIVE_MODEL.model_relative_paths)
            resolved = wehnelt_model.resolve_wehnelt_build_request(*inputs(),
                mode_id="build_only_smoke", evidence_particle_count=3)
            result = model_execution.execute_unsolved_model(session, resolved=resolved,
                limits={"explicit": 1}, spec=wehnelt_model.NATIVE_MODEL)
            self.assertEqual([row[0] for row in session.calls], ["build_model", "verify_model"])
            task = (session.input_dir / "build_model.m").read_text(encoding="utf-8")
            self.assertIn("result=build_wehnelt_model(", task)
            self.assertNotIn(".runAll", task)
            product = result["manifest_extra_fields"]["products"]["model"]
            self.assertEqual(product["kind"], "prepared_model")
            self.assertEqual(product["metadata"]["field_status"], "not_solved")
            self.assertEqual(product["metadata"]["scientific_qualification"], "not_granted")
            self.assertTrue({"model", "model_stage_1", "model_stage_2"} <= product["data"].keys())
            self.assertEqual(len(session.calls[1][1]["immutable_input_records"]),
                             len(session.calls[0][1]["immutable_input_records"]) + 3)
            for path in session.run_dir.rglob("*"):
                if path.is_file() and path != session.run_config:
                    session.classify_file(path)

    def test_registered_entry_loads_context_and_explicit_store(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = write_compiled_inputs(root)
            environment = root / "environment.json"
            workspace = root / "workspace"
            artifact_root = root / "store"
            context = object()
            product = Mock(reference={"product_id": "model"})
            with patch("msplatform.execution.context.load_environment", return_value=context) as load, \
                    patch("msplatform.storage.ArtifactStore") as store_type, \
                    patch.object(wehnelt_model, "build_wehnelt_model", return_value=product) as operation, \
                    patch("builtins.print"):
                status = cli.main([
                    "wehnelt-build-only",
                    "--compiled-inputs", str(bundle),
                    "--execution-environment", str(environment),
                    "--environment-profile", "local",
                    "--workspace", str(workspace),
                    "--artifact-root", str(artifact_root),
                ])
            self.assertEqual(status, 0)
            load.assert_called_once_with(environment.absolute(), workspace=workspace.absolute(), profile="local")
            store_type.assert_called_once_with(artifact_root.absolute())
            baseline, modes = inputs()
            operation.assert_called_once_with(
                baseline, modes, mode_id="build_only_smoke", evidence_particle_count=1,
                context=context, artifact_store=store_type.return_value,
            )

    def test_registered_entry_rejects_stale_input_before_creating_store(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = write_compiled_inputs(root, stale_resolved=True)
            with patch("msplatform.storage.ArtifactStore") as store_type, \
                    patch.object(wehnelt_model, "build_wehnelt_model") as operation:
                with self.assertRaises(SystemExit) as caught:
                    cli.main([
                        "wehnelt-build-only", "--compiled-inputs", str(bundle),
                        "--execution-environment", str(root / "environment.json"),
                        "--environment-profile", "local", "--workspace", str(root / "workspace"),
                        "--artifact-root", str(root / "store"),
                    ])
            self.assertEqual(caught.exception.code, 2)
            store_type.assert_not_called()
            operation.assert_not_called()

    def test_readback_cannot_rewrite_intermediate_stage_or_accept_solved_data(self):
        for failure, message in (("tamper_stage", "changed"), ("solved", "unsolved")):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                session = InertComsolSession(Path(directory),
                    model_relative_paths=wehnelt_model.NATIVE_MODEL.model_relative_paths, failure=failure)
                resolved = wehnelt_model.resolve_wehnelt_build_request(*inputs(),
                    mode_id="build_only_smoke", evidence_particle_count=3)
                with self.assertRaisesRegex((ValueError, AssertionError), message):
                    model_execution.execute_unsolved_model(session, resolved=resolved,
                        limits={}, spec=wehnelt_model.NATIVE_MODEL)


if __name__ == "__main__":
    unittest.main()
