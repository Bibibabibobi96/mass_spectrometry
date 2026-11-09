"""Explicit observation cadence changes preparation only; no native trajectory."""

import json
from pathlib import Path
import tempfile
import unittest
from msplatform.backends.simion.dual_cone_transport import prepare_transport

PROJECT = Path(__file__).resolve().parents[2] / "projects/dual_cone_tandem_quadrupole_ion_interface"


class ObservationCadenceTests(unittest.TestCase):
    def arguments(self, numerical_path):
        config = PROJECT / "config"
        return dict(
            mode="c0_gem_smoke",
            resolved_path=config / "resolved_geometry.json",
            numerics_path=numerical_path,
            science_path=config / "ion_transport_science.json",
            interface_path=config / "gas_field_interface.json",
            gas_science_path=config / "gas_flow_science.json",
            source_spec_path=config / "cylindrical_ion_source.json",
        )

    def test_explicit_one_and_two_change_only_rendered_observation_interval(self):
        original = json.loads((PROJECT / "config/simion_solver_numerics.json").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outputs = []
            for interval in (1, 2):
                numerical = json.loads(json.dumps(original))
                numerical["trajectory"]["sample_interval_us"] = interval
                path = root / (str(interval) + ".json")
                path.write_text(json.dumps(numerical), encoding="utf-8")
                output = root / ("case" + str(interval))
                receipt = prepare_transport(output, **self.arguments(path))
                self.assertFalse(receipt["qualified_evidence"])
                self.assertEqual(receipt["collision_model"], "none")
                self.assertEqual(list(output.rglob("*.pa*")), [])
                outputs.append(output)
            for name in (
                "dual_cone_tandem.gem",
                "c0_smoke.fly2",
                "source_states.lua",
                "simion_rf_drive.lua",
                "gas_assisted_transport.lua",
            ):
                self.assertEqual(
                    (outputs[0] / "solver/simion" / name).read_bytes(),
                    (outputs[1] / "solver/simion" / name).read_bytes(),
                )
            configs = [
                (output / "solver/simion/run_config.lua").read_text().replace(str(output), "<RUN>")
                for output in outputs
            ]
            self.assertIn("trajectory_sample_interval_us=1,", configs[0])
            self.assertIn("trajectory_sample_interval_us=2,", configs[1])
            self.assertEqual(
                configs[0].replace("trajectory_sample_interval_us=1,", "trajectory_sample_interval_us=2,"), configs[1]
            )

    def test_missing_or_invalid_interval_rejected_before_outputs(self):
        original = json.loads((PROJECT / "config/simion_solver_numerics.json").read_text())
        for value in ("MISSING", None, True, False, 0, -1, float("nan"), float("inf"), "2"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                numerical = json.loads(json.dumps(original))
                if value == "MISSING":
                    numerical["trajectory"].pop("sample_interval_us")
                else:
                    numerical["trajectory"]["sample_interval_us"] = value
                path = root / "numerics.json"
                path.write_text(json.dumps(numerical), encoding="utf-8")
                output = root / "must-not-exist"
                with self.assertRaisesRegex(ValueError, "sample_interval_us"):
                    prepare_transport(output, **self.arguments(path))
                self.assertFalse(output.exists())
