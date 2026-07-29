from __future__ import annotations

import json
import unittest
from pathlib import Path, PurePosixPath

from projects.rf_quadrupole_ion_optics.analysis import (
    validate_pre_pulse_interface_transport as validator,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
DEPENDENCIES = (
    PROJECT_ROOT / "config" / "rf_to_oatof_pre_pulse_dependencies.json"
)


class SemanticTransferDependencySnapshotTests(unittest.TestCase):
    def test_repository_dependency_contract_passes(self) -> None:
        validator.validate_contract()

    def test_every_declared_source_exists_and_snapshot_path_is_nested(self) -> None:
        document = json.loads(DEPENDENCIES.read_text(encoding="utf-8"))
        for record in document["dependencies"]:
            source = PurePosixPath(record["source_repo_path"])
            frozen = PurePosixPath(record["frozen_filename"])
            self.assertTrue(REPO_ROOT.joinpath(*source.parts).is_file(), source)
            self.assertEqual(
                frozen, PurePosixPath("runtime_snapshot") / source
            )

    def test_active_dependencies_do_not_consume_history_or_old_stage_names(self) -> None:
        text = DEPENDENCIES.read_text(encoding="utf-8")
        for forbidden in (
            "docs/history",
            "rf_to_oatof_s2",
            "rf_to_oatof_s3",
            "audit_s3",
            "analyze_s3",
            "build_s3",
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
