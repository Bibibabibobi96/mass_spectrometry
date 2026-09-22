"""Atomic evidence publication retries only bounded Windows replace conflicts."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common.contracts import recorded_file_removal as removal


class AtomicJsonPublicationTest(unittest.TestCase):
    @staticmethod
    def _windows_error(code: int) -> OSError:
        error = OSError("fixture replace conflict")
        error.winerror = code
        return error

    def test_windows_conflict_retries_same_flushed_candidate_then_succeeds(self):
        for code in (5, 32, 33):
            with self.subTest(winerror=code), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                destination = root / "ledger.json"
                destination.write_text('{"old": true}')
                replace = removal.os.replace
                candidates = []

                def once(source, target):
                    candidates.append(str(source))
                    self.assertEqual(json.loads(Path(source).read_text()), {"new": True})
                    self.assertEqual(json.loads(destination.read_text()), {"old": True})
                    if len(candidates) == 1:
                        raise self._windows_error(code)
                    return replace(source, target)

                with patch.object(removal.os, "replace", side_effect=once), patch.object(removal.time, "sleep") as sleep:
                    removal.write_json_atomic(destination, {"new": True})
                self.assertEqual(len(candidates), 2)
                self.assertEqual(candidates[0], candidates[1])
                sleep.assert_called_once_with(0.05)
                self.assertEqual(json.loads(destination.read_text()), {"new": True})
                self.assertEqual(list(root.iterdir()), [destination])

    def test_persistent_windows_denial_preserves_old_evidence_and_cleans_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "ledger.json"
            original = b'{"old":true}\n'
            destination.write_bytes(original)
            error = self._windows_error(5)
            with (patch.object(removal.os, "replace", side_effect=error) as replace,
                  patch.object(removal.time, "sleep") as sleep):
                with self.assertRaises(OSError) as raised:
                    removal.write_json_atomic(destination, {"new": True})
            self.assertIs(raised.exception, error)
            self.assertEqual(replace.call_count, 5)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.05, 0.1, 0.2, 0.4])
            self.assertEqual(destination.read_bytes(), original)
            self.assertEqual(list(root.iterdir()), [destination])

    def test_unrelated_error_and_non_windows_permission_error_are_not_retried(self):
        for error in (self._windows_error(112), PermissionError("ordinary denial")):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                destination = root / "ledger.json"
                with (patch.object(removal.os, "replace", side_effect=error) as replace,
                      patch.object(removal.time, "sleep") as sleep):
                    with self.assertRaises(OSError) as raised:
                        removal.write_json_atomic(destination, {"new": True})
                self.assertIs(raised.exception, error)
                replace.assert_called_once()
                sleep.assert_not_called()
                self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
