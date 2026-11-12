"""Saved-workbench qualification is an explicit action, separate from scientific flight."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from integrations.tests.test_single_reflection_preparation import fixture as single_fixture
from msplatform.workflows.single_reflection_flight.prepare import prepare



class SavedWorkbenchReplayPolicyTests(unittest.TestCase):


    def test_single_reflection_freezes_the_resolved_action_and_preserves_author_bytes(self):
        for requested in (None, False, True):
            with self.subTest(requested=requested), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path, run, request = single_fixture(root)
                if requested is not None:
                    request["verify_saved_workbench_replay"] = requested
                    path.write_text(json.dumps(request), encoding="utf-8")
                original = path.read_bytes()
                result = prepare(path, run)
                self.assertEqual(result["default_replay_requested"], bool(requested))
                self.assertEqual((run/"inputs/request.json").read_bytes(), original)
                self.assertEqual(path.read_bytes(), original)

    def test_single_reflection_rejects_truthy_non_boolean_action(self):
        with tempfile.TemporaryDirectory() as temporary:
            path, run, request = single_fixture(Path(temporary))
            request["verify_saved_workbench_replay"] = 1
            path.write_text(json.dumps(request), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "verify_saved_workbench_replay"):
                prepare(path, run)

    def test_unrequested_continuation_phase_does_not_consume_parent_evidence(self):
        from msplatform.workflows.single_reflection_flight import continuation

        preparation = dict(role="single_reflection_geometry_preparation", default_replay_requested=False)
        with tempfile.TemporaryDirectory() as temporary, patch.object(continuation, "_parent", side_effect=AssertionError("unrequested source access")):
            run = Path(temporary)
            self.assertIsNone(continuation.freeze_phase_inputs(preparation, run, "default_replay"))
            self.assertIsNone(continuation.recover_provisional_dispatch(preparation, "default_replay"))
            self.assertIsNone(continuation.prepare_phase_continuation(preparation, {}, run, "default_replay"))
            self.assertEqual(list(run.iterdir()), [])
