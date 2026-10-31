"""Small inert seed-pair transport; no native field or Workbench qualification."""
from pathlib import Path
import json
import tempfile
import unittest

from common.simion.workbench_seed import freeze_workbench_seed


class WorkbenchSeedTests(unittest.TestCase):
    def test_pair_is_frozen_once_and_existing_bytes_must_still_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root/"source"
            source = repo/"common/simion/assets/iob_instance_seeds"
            source.mkdir(parents=True)
            (source/"1_instance_seed.iob").write_bytes(b"INERT_SEED_NOT_NATIVE")
            (source/"iob_seed_placeholder_01.pa0").write_bytes(b"INERT_PLACEHOLDER_NOT_A_FIELD")
            run = root/"artifacts/projects/example/runs/test"
            first = freeze_workbench_seed(run, repo)
            before = {key: Path(record["frozen"]["path"]).read_bytes() for key, record in first.items()}
            second = freeze_workbench_seed(run, repo)
            self.assertEqual(second, first)
            self.assertEqual(json.dumps(second), json.dumps(first))
            self.assertEqual(set(first), {"seed", "placeholder"})
            for key, record in first.items():
                self.assertEqual(Path(record["frozen"]["path"]).parent, run/"simion/iob_seed")
                self.assertEqual(Path(record["frozen"]["path"]).read_bytes(), before[key])
                self.assertEqual(record["frozen"]["sha256"], record["source"]["sha256"])
            Path(first["placeholder"]["frozen"]["path"]).write_bytes(b"CHANGED")
            with self.assertRaisesRegex(AssertionError, "byte count changed"):
                freeze_workbench_seed(run, repo)


if __name__ == "__main__":
    unittest.main()
