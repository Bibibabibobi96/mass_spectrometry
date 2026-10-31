"""Known harmonic response samples for pure voltage-design analysis tests.

These are analytic reference vectors, never SIMION/native output or a claim
that the new HP design has reached a particular width. The explicit 0.4 mm
input is a design/test assumption, not a measured HP width.
"""
from __future__ import annotations

import copy
import itertools
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from common.contracts.particle_physics import AMU_KG, BOLTZMANN_CONSTANT_J_K, ELEMENTARY_CHARGE_C
from common.contracts.write_run_manifest import file_record
from integrations.workflows.cooled_frontend.field_design import (
    analyze_field_run, compose_samples, design_voltage_controls, project_member_samples,
)


def harmonic_response_fixture(*, rf_gradient: float = .1, cross_xy: float = 0.) -> dict[str, pd.DataFrame]:
    """Sample trace-free DC quadratics and a physical unit-RF quadrupole.

    DC phi(k)=k*(dy虏/2-x虏/4-dz虏/4), so its Laplacian is zero.
    RF phi=-a*(x虏-dz虏)/2 gives E=(a*x,0,-a*dz). Common-mode phi
    is affine and has a known 0.8 V drop between the two release references.
    """
    center = (0., 28., 32.)
    points = []
    for i, (x, y, z) in enumerate(itertools.product([-.4, -.2, 0., .2, .4], repeat=3)):
        name = "well_center" if (x, y, z) == (0., 0., 0.) else f"well_{i:03d}"
        points.append((name, x, y, z))
    points += [(f"axis_{i:03d}", 0., y, 0.) for i, y in enumerate([-4., -2., 0., 2., 4.])]
    points.append(("oa_entry", 0., 23.5, 0.))
    release_slope = -(2.+.5*.08*23.5**2)/23.5
    functions = {
        "carrier_off": lambda x, y, z: .05*(y*y/2-x*x/4-z*z/4)+cross_xy*x*y,
        "entry_close_delta": lambda x, y, z: .03*(y*y/2-x*x/4-z*z/4),
        "release_delta": lambda x, y, z: release_slope*y,
        "inner_auxiliary_unit": lambda x, y, z: -.2*(y*y/2-x*x/4-z*z/4),
        "hp_common_unit": lambda x, y, z: 1.-.8*y/23.5,
        "rf_differential_unit": lambda x, y, z: -rf_gradient*(x*x-z*z)/2,
    }
    responses = {}
    for mode, function in functions.items():
        rows = []
        for name, x, y, z in points:
            if mode in {"carrier_off", "entry_close_delta", "inner_auxiliary_unit"}:
                k = {"carrier_off": .05, "entry_close_delta": .03, "inner_auxiliary_unit": -.2}[mode]
                gamma = cross_xy if mode == "carrier_off" else 0.
                field = (k*x/2-gamma*y, -k*y-gamma*x, k*z/2)
            elif mode == "release_delta":
                field = (0., -release_slope, 0.)
            elif mode == "hp_common_unit":
                field = (0., .8/23.5, 0.)
            else:
                field = (rf_gradient*x, 0., -rf_gradient*z)
            rows.append(dict(name=name, x_mm=x+center[0], y_mm=y+center[1], z_mm=z+center[2],
                             potential_v=function(x, y, z),
                             ex_v_per_mm=field[0], ey_v_per_mm=field[1], ez_v_per_mm=field[2]))
        responses[mode] = pd.DataFrame(rows)
    return responses


def design_arguments() -> dict:
    return dict(center_mr_mm=[0., 28., 32.], mass_amu=524., charge_state=1, temperature_k=300.,
                rf_frequency_hz=3.7e6, guide_rf_amplitude_v=500., target_thermal_sigma_y_mm=.4,
                target_static_energy_gain_ev=5., release_reference_name="well_center", oa_entry_reference_name="oa_entry")


class CooledFrontendFieldDesignTests(unittest.TestCase):
    def test_pulse_projection_preserves_raw_probe_and_coordinates(self):
        raw = harmonic_response_fixture()["hp_common_unit"]
        original = raw.copy(deep=True)
        for scale in (2., 0., -1.):
            projected = project_member_samples(raw, "pulse_delta", scale)
            pd.testing.assert_frame_equal(raw, original)
            pd.testing.assert_frame_equal(projected[["name", "x_mm", "y_mm", "z_mm"]],
                                          raw[["name", "x_mm", "y_mm", "z_mm"]])
            for column in ("potential_v", "ex_v_per_mm", "ey_v_per_mm", "ez_v_per_mm"):
                np.testing.assert_array_equal(projected[column], raw[column] * scale)
        for kind, scale in (("carrier_off", 2.), ("pulse_delta", float("nan")), ("pulse_delta", True)):
            with self.subTest(kind=kind, scale=scale), self.assertRaises(ValueError):
                project_member_samples(raw, kind, scale)

    def test_checkpoint_owner_can_publish_field_proposal_and_bound_records(self):
        # Temporary analytic samples exercise the actual run adapter, not a
        # solver or a manufactured native field result.
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)/"20261022_000000__analysis__python__harmonic-reference"
            inputs = run/"inputs"
            probes = run/"results/cooled_field_probe"
            inputs.mkdir(parents=True)
            probes.mkdir(parents=True)
            responses = harmonic_response_fixture()
            responses["pulse_delta"] = responses["hp_common_unit"].copy()
            for values in responses.values():
                values["name"] = values["name"].replace({"well_center":"well_62", "oa_entry":"oa_side_entry"})
            payloads = {
                "cooled_design_targets.json":dict(thermal_sigma_y_mm=.4, static_release_energy_gain_ev=5.),
                "conditioner_contract.json":dict(geometry=dict(trap_center_mr_mm=[0.,28.,32.]),
                    gas=dict(parameters=dict(temperature_k=300.))),
                "guide_contract.json":dict(drive=dict(frequency_hz=3.7e6,rf_amplitude_v=500.)),
                "cooled_field_plan.json":dict(working_points=[dict(kind=kind) for kind in responses]),
                "cooled_frontend_field_stage_receipt.json": dict(working_points=[
                    dict(kind=kind, field_scale=2. if kind == "pulse_delta" else 1.)
                    for kind in ("carrier_off", "rf_differential_unit", "entry_close_delta",
                                 "release_delta", "pulse_delta", "inner_auxiliary_unit", "hp_common_unit")]),
            }
            for name, payload in payloads.items():
                (inputs/name).write_text(json.dumps(payload), encoding="utf-8")
            pd.DataFrame([dict(particle_id=3,mass_amu=524.,charge_state=1)]).to_csv(inputs/"release_global.csv",index=False)
            for kind, values in responses.items():
                values.to_csv(probes/(kind+".csv"),index=False)
            manifest = run/"run_manifest.json"
            manifest.write_text(json.dumps(dict(status="checkpoint")),encoding="utf-8")
            before = manifest.read_bytes()
            result = analyze_field_run(run)
            self.assertEqual(result["design_status"],"proposal_computed")
            self.assertAlmostEqual(result["voltage_calibration"]["release_hp_common_correction_v"],3.75)
            self.assertEqual(result["target_record"],file_record(inputs/"cooled_design_targets.json"))
            self.assertEqual(result["native_probe_records"],
                {kind:file_record(probes/(kind+".csv")) for kind in responses})
            self.assertEqual(json.loads((run/"results/cooled_field_design/voltage_design.json").read_text()),result)
            self.assertEqual(manifest.read_bytes(),before)

    def test_success_and_failed_sealed_owners_reject_analysis_before_writes(self):
        for status in ("success","failed"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                run = Path(temporary)
                manifest = run/"run_manifest.json"
                manifest.write_text(json.dumps(dict(status=status)),encoding="utf-8")
                before = manifest.read_bytes()
                with self.assertRaisesRegex(ValueError,"immutable owner"):
                    analyze_field_run(run)
                self.assertEqual(manifest.read_bytes(),before)
                self.assertEqual({path.name for path in run.iterdir()},{"run_manifest.json"})

    def test_known_curvature_and_static_energy_controls_are_independent(self):
        responses = harmonic_response_fixture()
        original = copy.deepcopy(responses)
        result = design_voltage_controls(responses, **design_arguments())
        kt_ev = BOLTZMANN_CONSTANT_J_K*300/ELEMENTARY_CHARGE_C
        target_curvature = kt_ev/.4**2
        self.assertAlmostEqual(result["voltage_calibration"]["inner_correction_v"], (target_curvature-.08)/-.2)
        self.assertAlmostEqual(result["voltage_calibration"]["release_hp_common_correction_v"], (5.-2.)/.8)
        self.assertAlmostEqual(result["release_design"]["seed_static_gain_ev"], 2.)
        self.assertAlmostEqual(result["release_design"]["energy_gain_response_ev_per_v"], .8)
        well = result["calibrated_closed_well"]
        self.assertTrue(well["locally_positive_effective_curvature"])
        self.assertTrue(well["equilibrium_within_sample_bounds"])
        self.assertAlmostEqual(well["thermal_sigma_xyz_mm"][1], .4)
        for mode in responses:
            pd.testing.assert_frame_equal(responses[mode], original[mode])

    def test_response_row_order_uses_identity_without_coordinate_or_data_changes(self):
        responses = harmonic_response_fixture()
        expected = compose_samples(responses, dict(carrier_off=1., entry_close_delta=1.), rf_amplitude_v=500.)
        responses["carrier_off"] = responses["carrier_off"].iloc[::-1]
        actual = compose_samples(responses, dict(carrier_off=1., entry_close_delta=1.), rf_amplitude_v=500.)
        pd.testing.assert_frame_equal(actual, expected)

    def test_dc_coordinate_and_point_identity_mismatches_fail(self):
        for dimension in ("x_mm", "name"):
            responses = harmonic_response_fixture()
            responses["carrier_off"].loc[0, dimension] = 123. if dimension == "x_mm" else "foreign_id"
            with self.subTest(dimension=dimension), self.assertRaises(ValueError):
                design_voltage_controls(responses, **design_arguments())

    def test_hp_common_energy_response_cannot_bypass_coordinate_validation(self):
        responses = harmonic_response_fixture()
        responses["hp_common_unit"].loc[responses["hp_common_unit"].name.eq("oa_entry"), "y_mm"] += 1.
        with self.assertRaisesRegex(ValueError, "coordinate"):
            design_voltage_controls(responses, **design_arguments())

    def test_missing_reference_identity_and_zero_control_responses_fail(self):
        responses = harmonic_response_fixture()
        for mode in ("inner_auxiliary_unit", "hp_common_unit"):
            wrong = copy.deepcopy(responses)
            wrong[mode]["potential_v"] = 0.
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "response"):
                design_voltage_controls(wrong, **design_arguments())
        with self.assertRaises((KeyError, ValueError)):
            design_voltage_controls(responses, **dict(design_arguments(), oa_entry_reference_name="missing"))

    def test_weak_rf_cannot_turn_an_unstable_3d_well_into_a_thermal_width(self):
        # Positive radial curvature permits k_y < 2*F. At this weak RF the
        # requested kBT/sigma_y虏 exceeds that limit: no stable target exists.
        # A root near det(H)=cofactor_yy(H)=0 must not be accepted as closure.
        with self.assertRaisesRegex(ValueError, "stable|covariance|solution"):
            design_voltage_controls(harmonic_response_fixture(rf_gradient=.001), **design_arguments())

    def test_coupled_hessian_requires_schur_complement_for_requested_y_width(self):
        gamma = .1
        result = design_voltage_controls(harmonic_response_fixture(cross_xy=gamma), **design_arguments())
        kt_ev = BOLTZMANN_CONSTANT_J_K*300/ELEMENTARY_CHARGE_C
        target = kt_ev/.4**2
        mass = 524*AMU_KG
        rf_curvature = ELEMENTARY_CHARGE_C*500**2*.1**2*1e6/(2*mass*(2*math.pi*3.7e6)**2)
        # Solve (k-target)*(F-k/2)=gamma虏 for the stable root near target.
        curvature = (2*rf_curvature+target-math.sqrt((2*rf_curvature-target)**2-8*gamma**2))/2
        self.assertAlmostEqual(result["voltage_calibration"]["inner_correction_v"], (curvature-.08)/-.2)
        self.assertAlmostEqual(result["calibrated_closed_well"]["thermal_sigma_xyz_mm"][1], .4)

    def test_nonfinite_target_and_repeated_point_identity_fail(self):
        responses = harmonic_response_fixture()
        with self.assertRaises(ValueError):
            design_voltage_controls(responses, **dict(design_arguments(), target_static_energy_gain_ev=np.nan))
        responses["carrier_off"].loc[0, "name"] = responses["carrier_off"].loc[1, "name"]
        with self.assertRaises(ValueError):
            design_voltage_controls(responses, **design_arguments())


if __name__ == "__main__":
    unittest.main()
