import unittest
import tempfile
from pathlib import Path

from common.simion.native_completion import (
    FlyCompletion, has_recoverable_batch_completion, parse_fly_completed_line,
    recoverable_batch_logs, require_one_fly_completion,
)


class NativeCompletionTests(unittest.TestCase):
    def test_parses_observed_simion_2020_completion_with_elapsed_seconds(self) -> None:
        self.assertEqual(
            parse_fly_completed_line("status,Fly completed. 9 splats, 269.62 seconds\n"),
            FlyCompletion(splats=9, elapsed_seconds=269.62),
        )

    def test_parses_merged_completion_without_elapsed_seconds(self) -> None:
        self.assertEqual(
            parse_fly_completed_line("status,Fly completed. 100 splats\r\n"),
            FlyCompletion(splats=100, elapsed_seconds=None),
        )

    def test_rejects_prefix_only_old_or_malformed_completion_lines(self) -> None:
        for line in (
            "status,Fly completed.\n",
            "status,Fly completed. 9 splats, nan seconds\n",
            "status,Fly completed. 9 splats trailing\n",
            "status,Fly'm complete. Splats: 9\n",
        ):
            self.assertIsNone(parse_fly_completed_line(line))

    def test_requires_one_completion_from_a_stream_without_owning_the_stream(self) -> None:
        lines = iter((
            "status,Flying particles.\n",
            "TRACE: terminal ion=1\n",
            "status,Fly completed. 1 splats, 0.01 seconds\n",
        ))
        self.assertEqual(require_one_fly_completion(lines), FlyCompletion(1, 0.01))

    def test_requires_one_completion_rejects_missing_or_duplicate_facts(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one"):
            require_one_fly_completion(("status,Fly completed.\n",))
        with self.assertRaisesRegex(ValueError, "exactly one"):
            require_one_fly_completion((
                "status,Fly completed. 1 splats\n",
                "status,Fly completed. 1 splats\n",
            ))

    def test_recovery_tail_distinguishes_trace_from_native_stdout_without_rewriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            logs = run / "logs"
            logs.mkdir()
            for kind, line, expected in (
                ("trace", "status,Fly completed.", True),
                ("stdout", "status,Fly completed. 9 splats, 269.62 seconds", True),
                ("stdout", "status,Fly completed. 100 splats", True),
                ("stdout", "status,Fly completed.", False),
                ("stdout", "status,Fly completed. invalid", False),
                ("stdout", "status,Fly completed. 9 splats, nan seconds", False),
                ("stdout", "status,Fly completed. 9 splats trailing", False),
                ("trace", "status,Fly completed. 9 splats", False),
            ):
                with self.subTest(kind=kind, line=line):
                    path = logs / f"simion__batch01.{kind}.log"
                    original = ("original body\n" + line + "\r\n").encode("utf-8")
                    path.write_bytes(original)
                    self.assertEqual(has_recoverable_batch_completion(path), expected)
                    self.assertEqual(path.read_bytes(), original)
            unrelated = logs / "other.stdout.log"
            unrelated.write_text("status,Fly completed. 9 splats\n", encoding="utf-8")
            self.assertFalse(has_recoverable_batch_completion(unrelated))
            self.assertEqual(recoverable_batch_logs(run), {
                (logs / "simion__batch01.trace.log").resolve(),
                (logs / "simion__batch01.stdout.log").resolve(),
            })
