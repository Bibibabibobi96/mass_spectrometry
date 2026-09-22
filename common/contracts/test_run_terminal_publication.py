"""Behavior tests for replayable summary/manifest publication."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common.contracts.recorded_file_removal import write_json_atomic
from common.contracts import write_run_manifest as publication


class RunTerminalPublicationTests(unittest.TestCase):
    def documents(self) -> tuple[dict[str, object], dict[str, object]]:
        summary = {"status": "success", "value": 7}
        manifest = {
            "role": "simulation_run_manifest",
            "run_id": "20260920_120000__test__python__terminal-journal",
            "status": "success",
        }
        return summary, manifest

    def assert_replay_after_crash(self, crash_name: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json_atomic(root / "summary.json", {"status": "interrupted"})
            write_json_atomic(
                root / "run_manifest.json",
                {"run_id": "old", "status": "interrupted"},
            )
            summary, manifest = self.documents()

            def crash(path: Path, value: dict[str, object]) -> None:
                write_json_atomic(path, value)
                if path.name == crash_name:
                    raise RuntimeError(f"crash after {crash_name}")

            with (
                mock.patch.object(publication, "write_json_atomic", crash),
                self.assertRaisesRegex(RuntimeError, "crash after"),
            ):
                publication.publish_terminal_state(root, summary, manifest)

            self.assertTrue((root / publication.TERMINAL_JOURNAL_NAME).is_file())
            with self.assertRaisesRegex(ValueError, "publication is incomplete"):
                publication.require_completed_terminal_publication(
                    root / "run_manifest.json"
                )
            publication.replay_terminal_publication(root)
            publication.require_completed_terminal_publication(root / "run_manifest.json")
            self.assertEqual(publication.publish_terminal_state(root, summary, manifest), (summary, manifest))
            self.assertFalse((root / publication.TERMINAL_JOURNAL_NAME).exists())

    def test_replays_crash_after_summary(self) -> None:
        self.assert_replay_after_crash("summary.json")

    def test_replays_crash_after_manifest(self) -> None:
        self.assert_replay_after_crash("run_manifest.json")


if __name__ == "__main__":
    unittest.main()
