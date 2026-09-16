from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import tempfile
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.accelerator_exit_simion_analysis import (
    analyze_exit,
    materialize_source,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


REPO = Path(__file__).resolve().parents[4]
BASELINE = REPO / "projects/parallel_mirror_dual_stripe_mr_tof/config/simion_candidate_two_zone.json"


class AcceleratorExitSimionAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        self.current = self.root / "current.json"
        self.reviewed = self.root / "reviewed.json"
        self.trial = self.root / "trial.json"
        self.fly2 = self.root / "source.fly2"
        self.receipt = self.root / "source.json"
        self.log = self.root / "flight.log"
        self.output = self.root / "observation.json"
        self._write(self.current, baseline)
        self._write(self.reviewed, baseline)
        trial = copy.deepcopy(baseline)
        trial["candidate_derivation"] = {
            "role": "fixed_reviewed_geometry_accelerator_voltage_trial",
            "physical_placement_source": "reviewed_contract_not_trial_focus",
        }
        self._write(self.trial, trial)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _write(path: Path, value: object) -> None:
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def _materialize(self) -> dict[str, object]:
        return materialize_source(
            contract_path=self.current,
            reviewed_contract_path=self.reviewed,
            voltage_trial_path=self.trial,
            fly2_path=self.fly2,
            receipt_path=self.receipt,
        )

    @staticmethod
    def _log_text(instance: int, *, from_instance: int | None = None, vz: float = -4.0) -> str:
        source = instance if from_instance is None else from_instance
        return (
            f"MRTOF_EVENT accelerator_layout accelerator_instance={instance}\n"
            "MRTOF_EVENT accelerator_source ion=1 t_us=0 x_mm=0 y_mm=-55.328 "
            "z_mm=36.8583736068 vx_mm_us=0 vy_mm_us=1.35695365245 vz_mm_us=0 "
            "mass_th=524 charge_state=1 kinetic_energy_ev_native=5\n"
            "MRTOF_EVENT accelerator_safe_exit ion=1 t_us=1.25 "
            f"from_instance={source} to_instance=0 x_mm=0.01 y_mm=-53 z_mm=0.2 "
            f"vx_mm_us=0.02 vy_mm_us=1.35 vz_mm_us={vz}\n"
            "MRTOF_EVENT terminal ion=1 splat=1 t_us=1.25 turns=0 x_mm=0.01 "
            f"y_mm=-53 z_mm=0.2 vx_mm_us=0.02 vy_mm_us=1.35 vz_mm_us={vz} "
            "central_crossings=0\n"
            "status,Fly completed. 1 splats\n"
        )

    def test_materializes_real_contract_owned_center_source(self) -> None:
        result = self._materialize()
        self.assertEqual(result["particle_mass_th"], 524.0)
        self.assertEqual(result["charge_state"], 1)
        self.assertEqual(result["source_slow_kinetic_energy_per_charge_v"], 5.0)
        self.assertEqual(result["source_direction_project"], [0.0, 1.0, 0.0])
        self.assertEqual(result["source_position_project_mm"], [0.0, -55.328, 36.858373606822035])
        source_state = result["source_release_state"]
        self.assertEqual(source_state["kinetic_energy_ev"], 5.0)
        self.assertEqual(source_state["velocity_mm_per_us"][0], 0.0)
        self.assertGreater(source_state["velocity_mm_per_us"][1], 0.0)
        self.assertEqual(source_state["velocity_mm_per_us"][2], 0.0)
        text = self.fly2.read_text(encoding="utf-8")
        self.assertIn("mass = 524", text)
        self.assertIn("charge = 1", text)
        self.assertIn("ke = 5", text)
        self.assertIn("direction = vector(0, 1, 0)", text)

    def test_corrected_voltage_trial_keeps_exact_k_as_exit_target(self) -> None:
        trial = json.loads(self.trial.read_text(encoding="utf-8"))
        target = trial["nominal"]["energy_per_charge_v"]
        correction = 0.75
        trial["candidate_derivation"].update({
            "target_axial_energy_per_charge_v": target,
            "finite_3d_gain_correction_v": correction,
        })
        trial["nominal"]["energy_per_charge_v"] = target + correction
        trial["accelerator_energy_contract"][
            "net_gain_reference_center_per_charge_v"
        ] = target + correction
        self._write(self.trial, trial)
        result = self._materialize()
        self.assertEqual(result["selected_axial_energy_per_charge_v"], target)

    def test_materialization_rejects_unreviewed_or_changed_source_contract(self) -> None:
        trial = json.loads(self.trial.read_text(encoding="utf-8"))
        del trial["candidate_derivation"]
        self._write(self.trial, trial)
        with self.assertRaisesRegex(CandidateContractError, "reviewed voltage trial"):
            self._materialize()

        trial["candidate_derivation"] = {
            "role": "fixed_reviewed_geometry_accelerator_voltage_trial",
            "physical_placement_source": "reviewed_contract_not_trial_focus",
        }
        trial["particle_source"]["species"]["mass_th"] = 100
        self._write(self.trial, trial)
        with self.assertRaisesRegex(CandidateContractError, "species differs"):
            self._materialize()

    def test_analyzes_discovered_instance_two_and_seven_without_fabricating_source(self) -> None:
        source = self._materialize()
        for instance in (2, 7):
            with self.subTest(instance=instance):
                self.log.write_text(self._log_text(instance), encoding="utf-8")
                result = analyze_exit(
                    log_path=self.log,
                    source_receipt_path=self.receipt,
                    output_path=self.output,
                )
                self.assertEqual(result["accelerator_layout"]["accelerator_instance"], instance)
                self.assertEqual(result["safe_exit_state"]["from_instance"], instance)
                self.assertLess(result["safe_exit_state"]["velocity_mm_per_us"][2], 0.0)
                energy = result["recorded_kinetic_energy_components_ev"]
                self.assertTrue(math.isclose(energy["total"], energy["x"] + energy["y"] + energy["z"]))
                self.assertEqual(result["safe_exit_state"]["kinetic_energy_ev"], energy["total"])
                self.assertEqual(
                    result["source_release_state"]["velocity_mm_per_us"],
                    source["source_release_state"]["velocity_mm_per_us"],
                )
                conversion = result["source_velocity_conversion_diagnostic"]
                self.assertEqual(conversion["native_kinetic_energy_ev"], 5.0)
                self.assertNotEqual(
                    conversion["recorded_native_velocity_mm_per_us"][1],
                    conversion["theoretical_velocity_mm_per_us"][1],
                )
                self.assertNotEqual(
                    conversion["native_minus_theoretical_velocity_mm_per_us"][1], 0.0,
                )

    def test_analysis_fails_closed_on_layout_identity_and_exit_direction(self) -> None:
        self._materialize()
        cases = (
            ("missing", self._log_text(2).split("\n", 1)[1], "exactly one accelerator layout"),
            ("duplicate", self._log_text(2) + "MRTOF_EVENT accelerator_layout accelerator_instance=2\n", "exactly one accelerator layout"),
            ("missing_source", "\n".join(self._log_text(2).splitlines()[0:1] + self._log_text(2).splitlines()[2:]), "exactly one accelerator source"),
            ("zero", self._log_text(0), "positive integer"),
            ("fraction", self._log_text(2).replace("accelerator_instance=2", "accelerator_instance=2.5"), "positive integer"),
            ("mismatch", self._log_text(2, from_instance=7), "disagrees"),
            ("wrong_direction", self._log_text(2, vz=0.0), "negative project z"),
        )
        for label, text, message in cases:
            with self.subTest(label=label):
                self.log.write_text(text, encoding="utf-8")
                with self.assertRaisesRegex(CandidateContractError, message):
                    analyze_exit(
                        log_path=self.log,
                        source_receipt_path=self.receipt,
                        output_path=self.output,
                    )

    def test_analysis_rejects_invalid_source_receipt_and_nonunique_exit(self) -> None:
        self._materialize()
        source = json.loads(self.receipt.read_text(encoding="utf-8"))
        source["qualification"] = "formal"
        self._write(self.receipt, source)
        self.log.write_text(self._log_text(2), encoding="utf-8")
        with self.assertRaisesRegex(CandidateContractError, "receipt identity"):
            analyze_exit(
                log_path=self.log,
                source_receipt_path=self.receipt,
                output_path=self.output,
            )

    def test_analysis_requires_measured_source_completion_and_terminal_order(self) -> None:
        self._materialize()
        valid = self._log_text(2)
        lines = valid.splitlines()
        terminal_before_exit = "\n".join((lines[0], lines[1], lines[3], lines[2], lines[4])) + "\n"
        cases = (
            (
                "source_energy_mismatch",
                valid.replace("kinetic_energy_ev_native=5", "kinetic_energy_ev_native=6"),
                "native source kinetic energy differs",
            ),
            (
                "source_wrong_direction",
                valid.replace("vy_mm_us=1.35695365245", "vy_mm_us=-1.35695365245"),
                "not directed along positive project y",
            ),
            (
                "source_transverse_velocity",
                valid.replace("vx_mm_us=0", "vx_mm_us=0.001", 1),
                "not directed along positive project y",
            ),
            (
                "source_position_mismatch",
                valid.replace("y_mm=-55.328", "y_mm=-55.3", 1),
                "recorded accelerator source differs",
            ),
            (
                "no_completion",
                valid.replace("status,Fly completed. 1 splats\n", ""),
                "complete with exactly one splat",
            ),
            (
                "terminal_before_exit",
                terminal_before_exit,
                "successful post-exit termination",
            ),
        )
        for label, text, message in cases:
            with self.subTest(label=label):
                self.log.write_text(text, encoding="utf-8")
                with self.assertRaisesRegex(CandidateContractError, message):
                    analyze_exit(
                        log_path=self.log,
                        source_receipt_path=self.receipt,
                        output_path=self.output,
                    )

        self._materialize()
        event = self._log_text(2).splitlines()[2]
        self.log.write_text(self._log_text(2) + event + "\n", encoding="utf-8")
        with self.assertRaisesRegex(CandidateContractError, "exactly one accelerator safe-exit"):
            analyze_exit(
                log_path=self.log,
                source_receipt_path=self.receipt,
                output_path=self.output,
            )


if __name__ == "__main__":
    unittest.main()
