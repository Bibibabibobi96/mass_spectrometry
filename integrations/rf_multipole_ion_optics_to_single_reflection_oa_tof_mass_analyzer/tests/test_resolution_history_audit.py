"""Tests for the explicit oaTOF historical resolution evidence audit."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis import (
    audit_resolution_history as audit,
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class ResolutionHistoryAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _record(
        self,
        record_id: str,
        board: str,
        source_class: str,
        resolution: float,
        *,
        time_basis: str = audit.PULSE_EFFECTIVE_BASIS,
        metric_role: str = "pulse_effective_peak",
        fwhm_method: str = audit.DIRECT_FWHM_METHOD,
        contract: str | None = "controlled_matrix_v1",
        allowed_axes: list[str] | None = None,
        field_id: str = "real_field",
        evidence_updates: dict[str, object] | None = None,
    ) -> dict[str, object]:
        evidence = {
            "schema_version": 1,
            "role": "fixture_resolution_evidence",
            "status": "success",
            "pulse_effective_peak": {
                "particles": 100,
                "mean_tof_us": 31.0,
                "direct_fwhm_tof_ns": 31000.0 / resolution,
                "mass_resolution": resolution,
                "significant_kde_modes": 1,
            },
            "instrument_clock_peak_is_resolution_claim": False,
        }
        if evidence_updates:
            evidence.update(evidence_updates)
        evidence_path = self.root / f"{record_id}.json"
        write_json(evidence_path, evidence)
        digest = "A" * 64
        identities = {
            "source": {"id": source_class, "sha256": digest},
            "field": {"id": field_id, "sha256": digest},
            "architecture": {"id": "long_focus_2p2mm", "sha256": digest},
            "geometry": {"id": "geometry_g2", "sha256": digest},
            "grid": {"id": "grid_005", "sha256": digest},
        }
        return {
            "record_id": record_id,
            "label": record_id,
            "run_id": f"20260813_120000__analysis__python__{record_id}",
            "leaderboard": board,
            "source_class": source_class,
            "evidence_path": evidence_path.name,
            "evidence_sha256": file_sha256(evidence_path),
            "metric_json_pointer": "/pulse_effective_peak",
            "identities": identities,
            "claim": {
                "resolution_time_basis": time_basis,
                "metric_role": metric_role,
                "fwhm_method": fwhm_method,
                "population_basis": "all_pulse_eligible",
                "nominal_mass_da": 100.0,
                "charge_state": 1,
                "comparison_contract_id": contract,
                "allowed_variation_axes": allowed_axes or [],
            },
        }

    def _inventory(self, records: list[dict[str, object]]) -> dict[str, object]:
        return {
            "schema_version": 1,
            "role": audit.REQUEST_ROLE,
            "records": records,
        }

    def test_emits_three_independent_reported_maxima_boards(self) -> None:
        records = [
            self._record("real_low", "real_beam_pulse_effective", "real_multipole_beam", 5000),
            self._record("real_high", "real_beam_pulse_effective", "real_multipole_beam", 7000),
            self._record("finite", "finite_ideal_source", "finite_ideal_source", 26000),
            self._record(
                "oracle",
                "numerical_oracle",
                "axial_ideal_source",
                47000,
                metric_role="analytic_pulse_effective_peak",
            ),
        ]
        result = audit.audit_history(self._inventory(records), inventory_dir=self.root)
        self.assertEqual(result["eligible_record_count"], 4)
        self.assertEqual(
            result["leaderboards"]["real_beam_pulse_effective"][0]["record_id"],
            "real_high",
        )
        self.assertEqual(
            result["leaderboards"]["finite_ideal_source"][0]["record_id"],
            "finite",
        )
        self.assertEqual(
            result["leaderboards"]["numerical_oracle"][0]["record_id"],
            "oracle",
        )
        report = audit.render_markdown(result)
        self.assertIn("Absolute-birth-time", report)
        self.assertIn("`oracle`", report)

    def test_explicitly_excludes_absolute_birth_and_instrument_clock_claims(self) -> None:
        birth = self._record(
            "birth",
            "real_beam_pulse_effective",
            "real_multipole_beam",
            999999,
            time_basis="absolute_birth_time",
        )
        instrument = self._record(
            "instrument",
            "real_beam_pulse_effective",
            "real_multipole_beam",
            888888,
            metric_role="instrument_clock_peak",
        )
        result = audit.audit_history(
            self._inventory([birth, instrument]), inventory_dir=self.root
        )
        self.assertEqual(result["eligible_record_count"], 0)
        self.assertEqual(result["excluded_absolute_birth_time_claim_count"], 1)
        reasons = {
            row["record_id"]: row["claim_exclusion_reasons"]
            for row in result["records"]
        }
        self.assertIn("absolute_birth_time_resolution_claim_excluded", reasons["birth"])
        self.assertIn("absolute_instrument_clock_metric_excluded", reasons["instrument"])
        self.assertIn(
            "one_or_both_resolution_claims_excluded",
            result["pairwise_comparability"][0]["incomparability_reasons"],
        )

    def test_records_missing_identity_as_incomparability_not_rank_exclusion(self) -> None:
        complete = self._record(
            "complete", "finite_ideal_source", "finite_ideal_source", 20000
        )
        incomplete = self._record(
            "incomplete", "finite_ideal_source", "finite_ideal_source", 21000
        )
        incomplete["identities"]["grid"] = {"id": None, "sha256": None}
        result = audit.audit_history(
            self._inventory([complete, incomplete]), inventory_dir=self.root
        )
        self.assertEqual(result["eligible_record_count"], 2)
        row = next(row for row in result["records"] if row["record_id"] == "incomplete")
        self.assertFalse(row["strict_comparability_ready"])
        self.assertIn("missing_grid_identity", row["comparability_limitations"])
        pair = result["pairwise_comparability"][0]
        self.assertFalse(pair["strictly_comparable"])
        self.assertIn("grid_identity_incomplete", pair["incomparability_reasons"])

    def test_pair_is_comparable_only_when_identity_difference_is_controlled(self) -> None:
        real = self._record(
            "real_field",
            "finite_ideal_source",
            "finite_ideal_source",
            21000,
            allowed_axes=["field"],
        )
        ideal = self._record(
            "ideal_field",
            "finite_ideal_source",
            "finite_ideal_source",
            30000,
            allowed_axes=["field"],
            field_id="ideal_field",
        )
        result = audit.audit_history(self._inventory([real, ideal]), inventory_dir=self.root)
        pair = result["pairwise_comparability"][0]
        self.assertTrue(pair["strictly_comparable"])
        self.assertEqual(pair["controlled_differing_axes"], ["field"])

        ideal["claim"]["allowed_variation_axes"] = []
        result = audit.audit_history(self._inventory([real, ideal]), inventory_dir=self.root)
        self.assertIn(
            "allowed_variation_axes_differ",
            result["pairwise_comparability"][0]["incomparability_reasons"],
        )

    def test_rejects_tampered_evidence_and_unknown_inventory_fields(self) -> None:
        record = self._record(
            "tamper", "real_beam_pulse_effective", "real_multipole_beam", 5000
        )
        evidence_path = self.root / "tamper.json"
        evidence_path.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(ContractError, "evidence SHA differs"):
            audit.audit_history(self._inventory([record]), inventory_dir=self.root)

        record = self._record(
            "unknown", "real_beam_pulse_effective", "real_multipole_beam", 5000
        )
        record["inferred_geometry"] = "forbidden"
        with self.assertRaisesRegex(ContractError, "unknown=.*inferred_geometry"):
            audit.validate_inventory(self._inventory([record]))

    def test_proxy_and_multimodal_metrics_are_not_ranked(self) -> None:
        proxy = self._record(
            "proxy",
            "finite_ideal_source",
            "finite_ideal_source",
            100000,
            fwhm_method="gaussian_sigma_proxy",
        )
        multimodal = self._record(
            "multi",
            "finite_ideal_source",
            "finite_ideal_source",
            200000,
            evidence_updates={
                "pulse_effective_peak": {
                    "particles": 100,
                    "mean_tof_us": 31.0,
                    "direct_fwhm_tof_ns": 0.1,
                    "mass_resolution": 200000,
                    "significant_kde_modes": 5,
                }
            },
        )
        result = audit.audit_history(
            self._inventory([proxy, multimodal]), inventory_dir=self.root
        )
        self.assertEqual(result["leaderboards"]["finite_ideal_source"], [])
        reasons = {
            row["record_id"]: row["claim_exclusion_reasons"]
            for row in result["records"]
        }
        self.assertIn("noncanonical_or_proxy_fwhm_excluded", reasons["proxy"])
        self.assertIn("peak_not_unimodal", reasons["multi"])

    def test_writes_json_and_markdown_outputs(self) -> None:
        record = self._record(
            "published", "real_beam_pulse_effective", "real_multipole_beam", 6000
        )
        inventory_path = self.root / "inventory.json"
        output_path = self.root / "results" / "audit.json"
        report_path = self.root / "results" / "audit.md"
        write_json(inventory_path, self._inventory([record]))
        result = audit.write_audit_outputs(inventory_path, output_path, report_path)
        self.assertEqual(result["eligible_record_count"], 1)
        self.assertEqual(
            json.loads(output_path.read_text(encoding="utf-8"))["role"],
            audit.RESULT_ROLE,
        )
        self.assertIn("## Excluded claims", report_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
