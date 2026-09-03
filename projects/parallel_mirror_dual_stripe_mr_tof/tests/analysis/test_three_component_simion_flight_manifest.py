"""Focused unit tests for the solver-free three-component flight receipt."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from common.contracts.file_identity import file_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.materialize_simion_prototype import (
    _particle_source_record,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.three_component_simion_flight_manifest import (
    FlightReceiptError,
    build_flight_receipt,
    write_flight_receipt,
)


def record(path: Path) -> dict[str, object]:
    return {"name": path.name, "bytes": path.stat().st_size, "sha256": file_sha256(path)}


def write_fixture(root: Path) -> dict[str, Path]:
    geometry = root / "geometry"
    geometry.mkdir()
    workbench: dict[str, dict[str, object]] = {}
    for key, name in (
        ("iob", "three_component.iob"),
        ("program", "three_component.lua"),
        ("operating_point", "three_component.operating_point.lua"),
        ("voltage_map", "three_component.voltage_map.lua"),
    ):
        path = geometry / name
        path.write_text(f"{key}\n", encoding="utf-8")
        workbench[key] = record(path)
    report = geometry / "iob_structure_report.txt"
    report.write_text(
        "STATUS=PASS\nPHYSICAL_MODEL=false\nPARTICLE_FLY_EXECUTED=false\n",
        encoding="utf-8",
    )
    workbench["structure_report"] = record(report)
    geometry_manifest = geometry / "three_component_geometry_review.json"
    geometry_manifest.write_text(json.dumps({
        "schema_version": 1,
        "project_id": "parallel_mirror_dual_stripe_mr_tof",
        "status": "prototype_geometry_review_only",
        "workbench": {"instance_count": 3, **workbench},
    }), encoding="utf-8")

    source_root = root / "source"
    source_root.mkdir()
    contract = {
        "particle_source": {"center_particle_count": 1},
        "nominal": {"target_oscillation_count": 25},
    }
    contract_path = source_root / "simion_prototype_contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    fly2 = source_root / "center.fly2"
    fly2.write_text("particles { standard_beam { n = 1 } }\n", encoding="utf-8")
    source_manifest = source_root / "prototype_input_manifest.json"
    source_manifest.write_text(json.dumps({
        "schema_version": 2,
        "derived_contract": {"filename": contract_path.name, "sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest()},
        "center_fly2": _particle_source_record(fly2, contract["particle_source"], "center_particle_count"),
    }), encoding="utf-8")

    raw_log = root / "raw_simion.log"
    raw_log.write_text("MRTOF_EVENT terminal ion=1 splat=-1 t_us=1 turns=2 x_mm=0 y_mm=0 z_mm=0 vx_mm_us=0 vy_mm_us=0 vz_mm_us=0 central_crossings=2\nstatus,Fly completed. 1 splats, 1 seconds\n", encoding="utf-8")
    event = root / "event_analysis.json"
    event.write_text(json.dumps({
        "schema_version": 2,
        "event_integrity_passed": True,
        "log_sha256": hashlib.sha256(raw_log.read_bytes()).hexdigest(),
        "source": {
            "input_manifest_sha256": hashlib.sha256(source_manifest.read_bytes()).hexdigest(),
            "source_key": "center_fly2",
            "fly2_filename": fly2.name,
            "fly2_sha256": hashlib.sha256(fly2.read_bytes()).hexdigest(),
            "expected_particle_ids_sha256": hashlib.sha256(b"[1]").hexdigest(),
            "derived_contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
        },
    }), encoding="utf-8")
    consumed_fly2 = root / "three_component.fly2"
    consumed_fly2.write_bytes(fly2.read_bytes())
    return {"geometry_manifest": geometry_manifest, "source_manifest": source_manifest,
            "raw_log": raw_log, "event": event, "consumed_fly2": consumed_fly2}


class ThreeComponentSimionFlightManifestTest(unittest.TestCase):
    def build(self, paths: dict[str, Path]) -> dict[str, object]:
        return build_flight_receipt(
            paths["geometry_manifest"], paths["source_manifest"], "center_fly2",
            paths["raw_log"], paths["event"],
            paths["consumed_fly2"],
        )

    def test_binds_complete_evidence_without_copying_metrics(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            paths = write_fixture(Path(temporary_directory))
            receipt = self.build(paths)
            output = Path(temporary_directory) / "receipt.json"
            written = write_flight_receipt(
                output_path=output, geometry_review_manifest_path=paths["geometry_manifest"],
                source_input_manifest_path=paths["source_manifest"], source_key="center_fly2",
                raw_log_path=paths["raw_log"], event_analysis_path=paths["event"],
                consumed_fly2_path=paths["consumed_fly2"],
            )
        self.assertFalse(receipt["formal_eligible"])
        self.assertEqual(receipt["status"], "candidate_prototype_flight_receipt")
        self.assertTrue(receipt["flight_evidence"]["event_integrity_passed"])
        self.assertEqual(receipt, written)
        self.assertNotIn("mass_resolution_t_over_2fwhm", json.dumps(receipt))

    def test_rejects_invalid_event_integrity_or_log_identity(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            paths = write_fixture(Path(temporary_directory))
            event = json.loads(paths["event"].read_text(encoding="utf-8"))
            event["event_integrity_passed"] = False
            paths["event"].write_text(json.dumps(event), encoding="utf-8")
            with self.assertRaisesRegex(FlightReceiptError, "event integrity"):
                self.build(paths)
            event["event_integrity_passed"] = True
            event["log_sha256"] = "0" * 64
            paths["event"].write_text(json.dumps(event), encoding="utf-8")
            with self.assertRaisesRegex(FlightReceiptError, "raw SIMION log"):
                self.build(paths)

    def test_rejects_wrong_geometry_review_flags_and_altered_iob(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            paths = write_fixture(Path(temporary_directory))
            report = paths["geometry_manifest"].parent / "iob_structure_report.txt"
            report.write_text("STATUS=PASS\nPHYSICAL_MODEL=true\nPARTICLE_FLY_EXECUTED=false\n", encoding="utf-8")
            with self.assertRaisesRegex(FlightReceiptError, "workbench.structure_report bytes"):
                self.build(paths)
            manifest = json.loads(paths["geometry_manifest"].read_text(encoding="utf-8"))
            manifest["workbench"]["structure_report"] = record(report)
            paths["geometry_manifest"].write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(FlightReceiptError, "PHYSICAL_MODEL=false"):
                self.build(paths)
            iob = paths["geometry_manifest"].parent / "three_component.iob"
            iob.write_text("altered\n", encoding="utf-8")
            with self.assertRaisesRegex(FlightReceiptError, "workbench.iob bytes"):
                self.build(paths)

    def test_rejects_a_workbench_fly2_that_is_not_the_selected_source(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            paths = write_fixture(Path(temporary_directory))
            paths["consumed_fly2"].write_text("different source\n", encoding="utf-8")
            with self.assertRaisesRegex(FlightReceiptError, "consumed Fly2 differs"):
                self.build(paths)


if __name__ == "__main__":
    unittest.main()
