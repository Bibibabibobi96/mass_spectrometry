"""Regression coverage for distinct MR-TOF SIMION manifest scopes."""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_simion_run_manifest import (
    build_manifest as build_split_manifest,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.three_component_simion_run_manifest import (
    build_manifest as build_three_component_manifest,
)


PROJECT = Path(__file__).resolve().parents[2]


def write_assembly_artifacts(root: Path) -> tuple[Path, Path]:
    """Create minimal byte artifacts for a solver-free manifest test."""
    for stem, identifiers in (
        ("mrtof_analyzer", range(1, 21)),
        ("mrtof_accelerator", (22, 23, 24, 26, 27, 28, 29, 30)),
    ):
        (root / f"{stem}.pa0").write_bytes(b"pa0")
        for identifier in identifiers:
            (root / f"{stem}.pa{identifier}").write_bytes(str(identifier).encode("ascii"))
    # The historical two-instance receipt refers to project IDs, whereas the
    # independent accelerator PA in the active three-instance assembly has a
    # local basis namespace 1..9.
    for identifier in range(1, 10):
        (root / f"mrtof_accelerator.pa{identifier}").write_bytes(str(identifier).encode("ascii"))
    (root / "mrtof_detector.pa#").write_bytes(b"detector")
    iob = root / "geometry.iob"
    iob.write_bytes(b"iob")
    for suffix in (".lua", ".operating_point.lua", ".voltage_map.lua"):
        iob.with_suffix(suffix).write_text("-- frozen\n", encoding="utf-8")
    report = root / "iob_structure_report.txt"
    report.write_text("STATUS=PASS\nPARTICLE_FLY_EXECUTED=false\n", encoding="utf-8")
    return iob, report


class SimionManifestWriterTest(unittest.TestCase):
    def test_two_and_three_component_receipts_remain_distinct(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            iob, report = write_assembly_artifacts(root)
            split = build_split_manifest(PROJECT / "config/simion_candidate_two_zone.json", root, iob, report)
            three = build_three_component_manifest(PROJECT / "config/simion_candidate_two_zone.json", root, iob, report)
        self.assertEqual(split["workbench"]["instance_count"], 2)
        self.assertNotIn("geometry", split)
        self.assertEqual(len(split["instances"]), 2)
        self.assertEqual(three["workbench"]["instance_count"], 3)
        self.assertIn("geometry", three)
        self.assertEqual(three["instances"][2]["role"], "detector")

    def test_rejects_a_structure_report_that_records_flight(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            iob, report = write_assembly_artifacts(root)
            report.write_text("STATUS=PASS\nPARTICLE_FLY_EXECUTED=true\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_split_manifest(PROJECT / "config/simion_candidate_two_zone.json", root, iob, report)
            with self.assertRaises(ValueError):
                build_three_component_manifest(PROJECT / "config/simion_candidate_two_zone.json", root, iob, report)


if __name__ == "__main__":
    unittest.main()
