"""Pure descriptive energy comparison; no statistical acceptance is invented."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from common.contracts.component_particle_state import write_component_particle_state_csv
from common.contracts.particle_physics import kinetic_energy_ev
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.ion_processor_handoff import compare_measured_exit_energy
from projects.parallel_mirror_dual_stripe_mr_tof.tests.analysis import test_ion_processor_handoff as fixtures


class IonProcessorEnergyComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fixtures.IonProcessorHandoffTests("test_preserves_full_state_clock_identity_and_complete_census")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.reference = self.fixture.root / "reference"
        self.reference.mkdir()
        self.fixture._write(self.reference / "run_manifest.json", {"status": "synthetic_fixture"})
        self.provider = self.reference / "provider.json"
        self.fixture._write(self.provider, {"mrtof_projection": {"target_axial_energy_per_charge_v": 4372.010347796}})
        self.states = self.reference / "states.csv"
        self.states.write_text("particle_id,mass_th,charge_e,kinetic_energy_ev\n7,524,1,5.2\n64,524,1,5.5\n", encoding="utf-8")
        self.source = self.reference / "source.json"
        self.fixture._write(self.source, {"expected_particle_ids": [7, 64], "particle_count": 2,
                                         "state_table": self.fixture._identity(self.states),
                                         "release_energy_distribution": {"kind": "gaussian", "sigma_ev": .15}})
        self.log = self.reference / "flight.log"
        self.log.write_text("\n".join(
            f"MRTOF_EVENT accelerator_geometric_exit ion={particle} localization=linear_bracket t_us=1.5 x_mm=0 y_mm=-55 z_mm=0 vx_mm_us=0 vy_mm_us={vy} vz_mm_us={vz}"
            for particle, vy, vz in ((7, 1.4, -40), (64, 1.5, -40.2))) + "\n", encoding="utf-8")
        self.paths = {"simion/accelerator_provider_runtime_receipt.json": self.provider,
                      "simion/bunch_source_receipt.json": self.source,
                      "logs/native_two_prism_flight.log": self.log}

    def _compare(self) -> dict:
        with patch("projects.parallel_mirror_dual_stripe_mr_tof.analysis.prepare_accelerator_interface.verified_reference",
                   side_effect=lambda run, name: self.paths[name]):
            return compare_measured_exit_energy(self.fixture.receipt_path, self.reference)

    def test_axis_total_census_and_reference_distinction(self) -> None:
        before = self.fixture.source.read_bytes()
        report = self._compare()
        self.assertEqual(report["ip_counts"], {"source": 3, "transferred": 2, "not_transferred": 1})
        self.assertEqual(report["ip_lost_particle_ids"], [9])
        self.assertEqual(report["ip_transferred_particle_ids"], [1, 7])
        self.assertIsNone(report["centroid_match_accepted"])
        measured = report["ip_exit"]["directional_energy"]
        expected = kinetic_energy_ev(524, 0, 0, -37800)
        self.assertEqual(measured["z"]["mean"], expected)
        self.assertNotEqual(report["ip_exit"]["total_energy"]["mean"], expected)
        self.assertEqual(report["centroid_residual_to_target"], expected-4372.010347796)
        self.assertNotEqual(report["centroid_residual_to_target"], report["centroid_residual_to_reference_oa_mean"])
        self.assertEqual(report["reference_oa"]["counts"], {"source": 2, "geometric_exit": 2})
        self.assertAlmostEqual(report["reference_oa"]["source_release_total_energy_per_charge"]["population_sigma"], .15)
        self.assertEqual(report["reference_oa"]["exit"]["velocity"]["z"]["mean"], -40100)
        self.assertEqual(report["total_energy_centroid_difference_to_reference_oa"],
                         report["ip_exit"]["total_energy"]["mean"]-report["reference_oa"]["exit"]["total_energy"]["mean"])
        self.assertEqual(report["directional_energy_centroid_difference_to_reference_oa"]["y"],
                         measured["y"]["mean"]-report["reference_oa"]["exit"]["directional_energy"]["y"]["mean"])
        self.assertIsNone(report["nominal_total_energy_target"]["value"])
        self.assertIn("undefined", report["nominal_total_energy_target"]["status"])
        self.assertFalse(report["electrostatic_energy_reference"]["potential_difference_compensated"])
        self.assertIn("historical_OA", report["target_basis"])
        self.assertIn("no tolerance or acceptance", report["matching_criterion"])
        self.assertTrue(any("not a mismatch" in caveat for caveat in report["caveats"]))
        self.assertEqual(self.fixture.source.read_bytes(), before)

    def test_wrong_direction_and_changed_source_bytes_rejected(self) -> None:
        self.fixture.rows[0]["velocity_z_m_s"] *= -1
        write_component_particle_state_csv(self.fixture.source, self.fixture.rows)
        self.fixture.receipt["outputs"]["component_states"] = self.fixture._identity(self.fixture.source)
        self.fixture._write(self.fixture.receipt_path, self.fixture.receipt)
        with self.assertRaisesRegex(ValueError, "negative-z"):
            self._compare()
        self.fixture.source.write_bytes(self.fixture.source.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self._compare()

    def test_missing_reference_exit_rejected(self) -> None:
        self.log.write_text(self.log.read_text().splitlines()[0] + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "geometric-exit IDs"):
            self._compare()

    def test_incomplete_upstream_census_rejected(self) -> None:
        self.fixture.receipt["counts"]["source"] = 2
        self.fixture._write(self.fixture.receipt_path, self.fixture.receipt)
        with self.assertRaisesRegex(ValueError, "mother census"):
            self._compare()

    def test_per_charge_energy_uses_primary_velocity_not_total_scalar(self) -> None:
        rows = self.fixture.rows
        for row in rows:
            row["charge_state"] = 2
            row["mass_to_charge_Th"] = 262
        write_component_particle_state_csv(self.fixture.source, rows)
        self.fixture.receipt["outputs"]["component_states"] = self.fixture._identity(self.fixture.source)
        self.fixture._write(self.fixture.receipt_path, self.fixture.receipt)
        report = self._compare()
        self.assertEqual(report["ip_exit"]["directional_energy"]["z"]["mean"], kinetic_energy_ev(524, 0, 0, -37800)/2)
        self.assertEqual(report["ip_exit"]["velocity"]["z"]["mean"], -37800)


if __name__ == "__main__":
    unittest.main()
