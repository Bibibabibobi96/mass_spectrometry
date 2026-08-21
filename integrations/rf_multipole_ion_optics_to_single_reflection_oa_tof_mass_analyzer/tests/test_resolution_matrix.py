"""Focused tests for the explicit gap/field/source resolution matrix."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis import (
    resolution_matrix as matrix,
)


class ResolutionMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _inventory(self, specs: list[tuple[str, float, str, str]]) -> dict[str, object]:
        rows = []
        for record_id, gap, field, population in specs:
            evidence = {
                "status": "success",
                "pulse_effective_peak": {
                    "particles": 100,
                    "mean_tof_us": 50.0 + gap,
                    "direct_fwhm_tof_ns": 2.0,
                    "mass_resolution": 12500.0,
                    "significant_kde_modes": 1,
                },
            }
            path = self.root / f"{record_id}.json"
            path.write_text(json.dumps(evidence) + "\n", encoding="utf-8")
            digest = "A" * 64
            rows.append({
                "record_id": record_id,
                "run_id": f"run-{record_id}",
                "gap_mm": gap,
                "field_condition": field,
                "source_population": population,
                "evidence_path": path.name,
                "evidence_sha256": file_sha256(path),
                "metric_json_pointer": "/pulse_effective_peak",
                "nominal_mass_da": 100.0,
                "charge_state": 1,
                "resolution_time_basis": matrix.PULSE_EFFECTIVE_BASIS,
                "metric_role": "pulse_effective_peak",
                "fwhm_method": matrix.DIRECT_FWHM_METHOD,
                "comparison_contract_id": "matrix-v1",
                "source_identity": {"id": "source-1", "sha256": digest},
                "geometry_identity": {"id": "geometry-1", "sha256": digest},
                "grid_identity": {"id": "grid-1", "sha256": digest},
            })
        return {"schema_version": 1, "role": matrix.REQUEST_ROLE, "rows": rows}

    def test_aggregates_gap_field_and_population_axes(self) -> None:
        result = matrix.aggregate_matrix(
            self._inventory([
                ("g0-real", 0.0, "real_field", "full_domain"),
                ("g51-accelerator-ideal", 51.2, "accelerator_ideal_field", "ideal_source_region"),
                ("g51-reflectron-ideal", 51.2, "reflectron_ideal_field", "full_domain"),
                ("g102-full", 102.4, "full_ideal_field", "full_domain"),
            ]),
            inventory_dir=self.root,
        )
        self.assertEqual(result["row_count"], 4)
        self.assertEqual(result["gap_values_mm"], [0.0, 51.2, 102.4])
        self.assertEqual(len(result["groups_by_gap_mm"]["102.4"]), 1)
        row = result["rows"][1]
        self.assertEqual(row["source_population"], "ideal_source_region")
        self.assertEqual(row["field_condition"], "accelerator_ideal_field")
        self.assertEqual(result["rows"][2]["field_condition"], "reflectron_ideal_field")

    def test_rejects_tampered_evidence_and_unknown_axes(self) -> None:
        inventory = self._inventory([("one", 0.0, "real_field", "full_domain")])
        path = self.root / "one.json"
        path.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "evidence SHA differs"):
            matrix.aggregate_matrix(inventory, inventory_dir=self.root)
        inventory = self._inventory([("two", 0.0, "real_field", "full_domain")])
        inventory["rows"][0]["field_condition"] = "partial_ideal_field"
        with self.assertRaisesRegex(ContractError, "field_condition is unknown"):
            matrix.validate_inventory(inventory)

    def test_writes_auditable_json_and_csv(self) -> None:
        inventory_path = self.root / "inventory.json"
        inventory_path.write_text(
            json.dumps(self._inventory([("one", 102.4, "full_ideal_field", "ideal_source_region")])),
            encoding="utf-8",
        )
        output_json = self.root / "out" / "matrix.json"
        output_csv = self.root / "out" / "matrix.csv"
        result = matrix.write_matrix_outputs(inventory_path, output_json, output_csv)
        self.assertEqual(result["role"], matrix.RESULT_ROLE)
        self.assertIn("evidence_sha256", output_csv.read_text(encoding="utf-8"))
        self.assertEqual(json.loads(output_json.read_text(encoding="utf-8"))["row_count"], 1)


if __name__ == "__main__":
    unittest.main()
