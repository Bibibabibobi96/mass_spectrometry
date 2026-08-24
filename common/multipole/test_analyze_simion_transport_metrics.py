import tempfile
import unittest
from pathlib import Path

from common.multipole.analyze_simion_transport_metrics import evaluate


HEADER = "particle_id,event,status\n"


class AnalyzeSimionTransportMetricsTests(unittest.TestCase):
    @staticmethod
    def summary(transmission: float = 0.5) -> dict:
        return {"solver": "SIMION 2020", "particles": 4, "transmission": transmission}

    def test_base_paired_preserves_summary_transmission_difference(self) -> None:
        result = evaluate(
            metric_kind="base_paired", project_id="fixture", parent_resolved_design_sha256="A" * 64,
            case_set="primary_and_zero_axial_control", primary_case_id="rf_on",
            primary_summary=self.summary(0.75), primary_state=None,
            control_case_id="zero_rf_control", control_summary=self.summary(0.25), control_state=None,
        )
        self.assertEqual(result["role"], "multipole_simion_finite_3d_transport_metrics")
        self.assertEqual(result["cases"]["rf_on"]["transmission_fraction"], 0.75)
        self.assertEqual(result["rf_minus_zero_transmission"], 0.5)

    def test_primary_and_rf_off_count_only_canonical_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary, control = root / "primary.csv", root / "control.csv"
            primary.write_text(HEADER + "1,handoff,transmitted\n2,terminal,transmitted\n")
            control.write_text(HEADER + "1,handoff,transmitted\n2,handoff,transmitted\n")
            primary_result = evaluate(
                metric_kind="primary", project_id="fixture", parent_resolved_design_sha256="A" * 64,
                case_set="primary_only", primary_case_id="rf_on", primary_summary=self.summary(),
                primary_state=primary,
            )
            control_result = evaluate(
                metric_kind="rf_off_energy_control", project_id="fixture", parent_resolved_design_sha256="A" * 64,
                case_set="primary_and_rf_off_energy_control", primary_case_id="rf_on",
                primary_summary=self.summary(), primary_state=primary,
                control_case_id="rf_off", control_summary=self.summary(), control_state=control,
            )
        self.assertEqual(primary_result["primary_handoff_transmission"], 0.25)
        self.assertEqual(control_result["primary_handoff_transmission"], 0.25)
        self.assertEqual(control_result["control_handoff_transmission"], 0.5)

    def test_base_primary_preserves_its_existing_no_control_contract(self) -> None:
        result = evaluate(
            metric_kind="base_primary", project_id="fixture", parent_resolved_design_sha256="A" * 64,
            case_set="primary_only", primary_case_id="rf_on", primary_summary=self.summary(),
            primary_state=None,
        )
        self.assertNotIn("primary_handoff_transmission", result)
        self.assertIn("no zero-RF control", result["claim_limit"])
