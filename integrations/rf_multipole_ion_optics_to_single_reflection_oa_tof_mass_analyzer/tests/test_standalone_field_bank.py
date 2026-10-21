from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path
import tempfile
from unittest.mock import patch
import contextlib
import io

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.standalone_field_bank import (
    MODE_IDS,
    _accelerator_plan,
    _selection_records,
    composition_terms,
    resolve_mode_states,
    read_response_normalization,
    main,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_electrode_contract import (
    TWO_ZONE_BARE_VARIANT, frontend_electrodes,
    resolve_two_zone_bare_pa_plus_solution_model,
)


class StandaloneFieldBankTests(unittest.TestCase):
    def test_measured_response_voltage_normalizes_before_base_subtraction(self):
        records = [{"response_id": 28, "path": "a.pa"}, {"response_id": 29, "path": "b.pa"}]
        base, terms = composition_terms(records, {28: 500., 29: -250.},
                                        response_normalization_v={28: 10000., 29: 5000.})
        self.assertEqual(base, "a.pa")
        self.assertEqual(terms, [{"path": "a.pa", "coefficient": -.95}, {"path": "b.pa", "coefficient": -.05}])
        # Including the composer's implicit base gives the requested physical volts.
        self.assertAlmostEqual((1 + terms[0]["coefficient"]) * 10000., 500.)
        self.assertAlmostEqual(terms[1]["coefficient"] * 5000., -250.)
        for invalid in ({28: 1.}, {28: 0., 29: 1.}, {28: float("nan"), 29: 1.}, {28: True, 29: 1.}):
            with self.assertRaises(ValueError):
                composition_terms(records, {28: 1., 29: 0.}, response_normalization_v=invalid)

    def test_measurement_is_inventory_bound_and_requires_all_modes(self):
        from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.tests.test_local_frontend_field_support import normalization_fixture
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = normalization_fixture(root)
            path = root / "standalone_mode_normalization.tsv"
            result = read_response_normalization(path, records)
            self.assertEqual(result["mode_reference_v"], {i: 10000. for i in range(28,33)})
            altered = deepcopy(records)
            altered[0]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "identities"):
                read_response_normalization(path, altered)
            path.write_text(path.read_text() + "changed")
            with self.assertRaisesRegex(ValueError, "inventory"):
                read_response_normalization(path, records)

    def test_native_composition_cli_refuses_implicit_unit_voltage(self):
        with patch("sys.argv", ["standalone_field_bank", "--upstream", "u", "--frontend", "f", "--oatof", "o", "--region-field", "r",
                                "--accelerator-main", "a", "--role-selection", "coarse_frontend=1=s", "--output-directory", "out",
                                "--plan", "plan", "--field-bank", "bank"]), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as stopped:
                main()
            self.assertEqual(stopped.exception.code, 2)

    def _bare_fixture(self):
        ids = frontend_electrodes(ring_count=3, three_zone=False, variant=TWO_ZONE_BARE_VARIANT)
        model = resolve_two_zone_bare_pa_plus_solution_model(
            ids, planes_global_z_mm={"repeller": 0, "grid1": 4, "exit": 34},
            ring_z_mm=[11.5, 19, 26.5],
        )
        on = {"9": 0., "10": 4500., "11": 4000., "12": 3000., "13": 2000., "14": 1000., "15": 0.}
        frontend = {"electrodes": ids, "accelerator_component": {"variant": "two_zone"},
                    "accelerator_local_region": {
                        "pulse_voltage_policy_id": "all_accelerator_electrodes_zero_before_pulse_v1",
                        "off_voltages_v": {key: 0. for key in on}, "operating_voltages_v": on,
                    }}
        upstream = {"role": "ion_processor_bare_guide_interface", "schema_version": 1,
                    "rod_array": {"rods": [{"physical_electrode_id": index,
                                             "electrode_group": 1 if index % 2 else 2} for index in range(1, 9)]},
                    "drive": {"waveform": "cosine", "frequency_hz": 3700000., "phase_rad": .2,
                              "rf_amplitude_v": 500., "group_dc_v": [0., 0.], "common_mode_v": -2.,
                              "group_polarities": {"1": 1, "2": -1}}}
        return upstream, frontend, model

    def test_canonical_two_zone_uses_actual_voltage_table_without_legacy_fields(self):
        upstream, frontend, model = self._bare_fixture()
        states = resolve_mode_states(upstream, frontend, {}, {}, model)
        self.assertEqual(tuple(states["carrier_off"]), tuple(model["mode_ids"]))
        by_name = {mode["name"]: mode["mode_id"] for mode in model["modes"]}
        self.assertEqual(states["carrier_off"][by_name["rod_common"]], -2)
        self.assertEqual(states["rf_differential_unit"][by_name["rod_differential"]], 1)
        self.assertEqual(states["pulse_delta"][by_name["repeller"]], 4500)
        self.assertEqual(states["pulse_delta"][by_name["grid1"]], 4000)
        self.assertEqual(states["pulse_delta"][by_name["grid2"]], 0)
        self.assertEqual(len(states["pulse_delta"]), 5)

    def test_canonical_table_rejects_missing_policy_coverage_or_invalid_voltages(self):
        upstream, frontend, model = self._bare_fixture()
        for mutate in (
            lambda r: r.pop("pulse_voltage_policy_id"),
            lambda r: r.pop("off_voltages_v"),
            lambda r: r["off_voltages_v"].pop("12"),
            lambda r: r["off_voltages_v"].update({"11": 1.}),
            lambda r: r["operating_voltages_v"].update({"9": 1.}),
            lambda r: r["operating_voltages_v"].update({"12": 2999.}),
            lambda r: r["operating_voltages_v"].update({"12": float("nan")}),
        ):
            changed = deepcopy(frontend)
            mutate(changed["accelerator_local_region"])
            with self.assertRaises(ValueError):
                resolve_mode_states(upstream, changed, {}, {}, model)
        model["model_id"] = "unknown"
        with self.assertRaisesRegex(ValueError, "unsupported"):
            resolve_mode_states(upstream, frontend, {}, {}, model)

    def test_existing_analyzer_plan_supports_true_two_zone_and_three_zone(self):
        analyzer = {"electrode_ids": {"repeller": 10, "grid1": 11, "grid2": 15, "rings": [12, 13, 14]},
                    "geometry": {"accelerator_grid1_z_mm": 4, "accelerator_grid2_z_mm": 34,
                                 "accelerator_ring_z_mm": [11.5, 19, 26.5]},
                    "voltages": {"repeller_v": 4500, "grid1_v": 4000, "exit_v": 0}}
        self.assertEqual(_accelerator_plan(analyzer, "on"), {10: 4500., 11: 4000., 15: 0., 12: 3000., 13: 2000., 14: 1000.})
        self.assertEqual(_accelerator_plan(analyzer, "off"), {key: 0. for key in (10, 11, 12, 13, 14, 15)})
        analyzer["electrode_ids"]["intermediate2"] = 18
        analyzer["geometry"]["accelerator_intermediate2_z_mm"] = 19
        analyzer["voltages"]["intermediate2_v"] = 1000
        self.assertEqual(_accelerator_plan(analyzer, "on"), {10: 4500., 11: 4000., 18: 1000., 15: 0., 12: 2500., 13: 1000., 14: 500.})

    def test_composition_accepts_model_driven_modes_and_exact_zero(self):
        _, _, model = self._bare_fixture()
        ids = model["mode_ids"]
        records = [{"response_id": i, "path": f"C:/response_{i}.pa"} for i in ids]
        base, terms = composition_terms(records, {i: 0. for i in ids})
        self.assertEqual(base, records[0]["path"])
        self.assertEqual(terms, [{"path": records[0]["path"], "coefficient": -1.}])
        coefficients = {i: float(i == ids[-1]) for i in ids}
        base, terms = composition_terms(records, coefficients)
        self.assertEqual(base, records[-1]["path"])
        self.assertEqual(terms, [{"path": records[0]["path"], "coefficient": 0.}])
        with self.assertRaises(ValueError):
            composition_terms(records + [records[0]], coefficients)

    def test_selection_accepts_only_the_explicit_ordered_model_modes(self):
        _, _, model = self._bare_fixture()
        records = [{"response_id": i, "name": f"frontend.response_{i}.pa",
                    "path": f"C:/cache/frontend.response_{i}.pa", "bytes": 10, "sha256": "A"*64}
                   for i in model["mode_ids"]]
        selection = {"schema_version": 1, "role": "rf_oatof_standalone_pa_response_selection",
                     "prefix": "frontend", "records": records}
        self.assertEqual(_selection_records("coarse_frontend", selection, mode_ids=model["mode_ids"]), records)
        with self.assertRaises(ValueError):
            _selection_records("coarse_frontend", selection)
        selection["records"] = list(reversed(records))
        with self.assertRaisesRegex(ValueError, "order"):
            _selection_records("coarse_frontend", selection, mode_ids=model["mode_ids"])

    def test_composition_uses_mode36_as_geometry_carrier(self) -> None:
        records = [
            {"response_id": mode_id, "path": f"C:/response_{mode_id}.pa"}
            for mode_id in MODE_IDS
        ]
        coefficients = {mode_id: 0.0 for mode_id in MODE_IDS}
        coefficients[36] = 12.0
        coefficients[42] = -3.0
        base, terms = composition_terms(records, coefficients)
        self.assertEqual(base, "C:/response_36.pa")
        self.assertEqual(
            terms,
            [
                {"path": "C:/response_36.pa", "coefficient": 11.0},
                {"path": "C:/response_42.pa", "coefficient": -3.0},
            ],
        )

    def test_composition_requires_exact_coefficient_mode_set(self) -> None:
        with self.assertRaisesRegex(ValueError, "coefficient mode set"):
            composition_terms(
                [{"response_id": 36, "path": "C:/response_36.pa"}],
                {mode_id: 0.0 for mode_id in MODE_IDS},
            )

    def test_composition_chooses_nonzero_base_and_preserves_negative_rf_sign(self) -> None:
        records = [
            {"response_id": mode_id, "path": f"C:/response_{mode_id}.pa"}
            for mode_id in MODE_IDS
        ]
        coefficients = {mode_id: 0.0 for mode_id in MODE_IDS}
        coefficients[37] = -1.0
        base, terms = composition_terms(records, coefficients)
        self.assertEqual(base, "C:/response_37.pa")
        self.assertEqual(
            terms,
            [{"path": "C:/response_37.pa", "coefficient": -2.0}],
        )

    def test_selection_schema_is_strict_and_role_bound(self) -> None:
        records = [
            {
                "response_id": mode_id,
                "name": f"frontend.response_{mode_id}.pa",
                "path": f"C:/cache/frontend.response_{mode_id}.pa",
                "bytes": 10,
                "sha256": "A" * 64,
            }
            for mode_id in MODE_IDS
        ]
        selection = {
            "schema_version": 1,
            "role": "rf_oatof_standalone_pa_response_selection",
            "prefix": "frontend",
            "records": records,
        }
        self.assertEqual(
            len(_selection_records("coarse_frontend", selection)), len(MODE_IDS)
        )
        selection["prefix"] = "accelerator_main"
        with self.assertRaisesRegex(ValueError, "identity differs"):
            _selection_records("coarse_frontend", selection)


if __name__ == "__main__":
    unittest.main()
