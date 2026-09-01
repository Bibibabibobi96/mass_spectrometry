from __future__ import annotations

import copy
import unittest

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.pulse_reuse_identity_projection import (
    build_verified_pulse_reuse_projection,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    post_pulse_handoff_profile_identity,
)


def _fixture() -> dict[str, object]:
    contract = {
        "role": "rf_oatof_pre_pulse_time_series_screening_contract",
        "identities": {
            "campaign_id": "campaign_n100",
            "experiment_id": "experiment_n100",
            "experiment_row_sha256": "A" * 64,
            "resolved_source_contract_sha256": "B" * 64,
            "resolved_population_contract_sha256": "C" * 64,
            "mother_particle_source_sha256": "D" * 64,
            "ordered_particle_id_sha256": "E" * 64,
            "connection_profile_id": "gap_51p2",
            "source_profile_id": "canonical_real_octupole",
            "layout_profile_id": "three_zone",
            "architecture_generation_id": "three_zone_v1",
            "topology_id": "three_zone_topology",
            "geometry_id": "three_zone_geometry",
            "frontend_electrode_topology_id": "frontend_v1",
            "field_profile_id": "accelerator_real",
            "region_field_semantic_sha256": "F" * 64,
            "frontend_grid_profile_id": "frontend_020",
            "field_overlay_id": "overlay_z005",
            "oatof_numerical_profile_id": "formal_mesh",
            "trajectory_quality_profile_id": "tqual_8",
            "time_integration_profile_id": "dt160",
            "spatial_window_profile_id": "layout_xy2",
        },
        "rf_time_grid": {
            "waveform": "sin",
            "frequency_hz": 1_100_000.0,
            "phase_rad": 2.7,
            "rf_steps_per_period": 160,
            "period_us": 0.9090909090909091,
            "step_us": 0.005681818181818182,
            "time_grid_profile_id": "ballistic_seed_rf160_minus56_plus264_v1",
            "ballistic_seed_time_us": 52.0,
            "grid_origin_us": 51.68181818181818,
            "sample_count": 321,
        },
        "selection_order": ["eligible_count_desc", "spread_asc"],
        "pulse_disabled": True,
        "terminate_at_window_end": True,
        "resolution_claim_allowed": False,
    }
    source = {
        "role": "rf_multipole_oatof_source_contract",
        "upstream_project_id": "rf_octupole_ion_optics",
        "selector": {"event": "handoff", "status": "transmitted"},
        "canonical_state": {
            "frame_id": "multipole_cartesian_z_axis_v1",
            "clock_epoch_id": "instrument_clock_epoch_v1",
            "species_policy": "frozen_particle_source_mass_and_charge",
        },
        "source_branches": {
            "simion": {
                "source": {
                    "particle_count": 100,
                    "particle_source": {"sha256": "1" * 64},
                }
            }
        },
    }
    connection = {
        "selection": {"connection_profile_id": "gap_51p2"},
        "spatial_registration": {"translation_mm": [-200.0, 0.0, -18.0]},
        "connector": {"length_mm": 51.2},
        "port_geometry": {"clear_radius_mm": 0.45},
        "transition_aperture": {"width_mm": 1.0, "height_mm": 0.9},
        "effective_clear_radius_mm": 0.45,
        "potential_alignment": {"upstream_exit_V": 0.0},
        "clock_alignment": {"basis": "canonical_instrument_time_us"},
        "field_ownership_segments": [{"owner": "frontend", "z_mm": [0.0, 51.2]}],
    }
    geometry = {
        "role": "oa_tof_resolved_contract_do_not_edit",
        "coordinate_convention": {"frame_id": "oatof_global", "units": "mm"},
        "particle_source": {
            "center_x_mm": -69.0,
            "center_y_mm": 0.0,
            "center_z_mm": -61.5,
            "size_x_mm": 1.0,
            "size_y_mm": 1.0,
            "size_z_mm": 2.2,
        },
        "accelerator_topology": {
            "topology_id": "three_zone",
            "planes_global_z_mm": {
                "repeller": -63.0,
                "intermediate1": -59.75,
                "intermediate2": -54.65,
                "exit": -42.75,
            },
            "potentials_v": {
                "repeller": 2115.0,
                "intermediate1": 1865.0,
                "intermediate2": 1620.0,
                "exit": 0.0,
            },
        },
        "detector": {"x_mm": 69.0},
    }
    return {
        "screening_contract": contract,
        "resolved_source": source,
        "resolved_connection": connection,
        "resolved_geometry": geometry,
        "spatial_profile": {
            "profile_id": "layout_xy2",
            "x": {"full_width_mm": 2.0},
            "y": {"full_width_mm": 2.0},
        },
        "pa_cache_keys": {
            "frontend": "frontend-key",
            "accelerator_overlay": "overlay-key",
            "flight_tube": None,
            "reflectron": None,
        },
    }


class PulseReuseIdentityProjectionTests(unittest.TestCase):
    def _key(self, fixture: dict[str, object]) -> str:
        _, key = build_verified_pulse_reuse_projection(**fixture)
        return key

    def test_population_files_count_order_and_batch_do_not_change_key(self) -> None:
        baseline = _fixture()
        varied = copy.deepcopy(baseline)
        identities = varied["screening_contract"]["identities"]
        identities["campaign_id"] = "campaign_n1000"
        identities["resolved_population_contract_sha256"] = "9" * 64
        identities["mother_particle_source_sha256"] = "8" * 64
        identities["ordered_particle_id_sha256"] = "7" * 64
        varied["screening_contract"]["consumer_batch_count"] = 5
        varied["resolved_source"]["source_branches"]["simion"]["source"] = {
            "particle_count": 1000,
            "particle_source": {"sha256": "6" * 64},
        }
        self.assertEqual(self._key(baseline), self._key(varied))

    def test_provider_prepulse_quality_remains_evidence(self) -> None:
        baseline = _fixture()
        varied = copy.deepcopy(baseline)
        varied["screening_contract"]["identities"][
            "time_integration_profile_id"
        ] = "dt80"
        self.assertNotEqual(self._key(baseline), self._key(varied))

    def test_post_pulse_potentials_and_downstream_geometry_do_not_change_key(self) -> None:
        baseline = _fixture()
        varied = copy.deepcopy(baseline)
        varied["resolved_geometry"]["accelerator_topology"]["potentials_v"] = {
            "repeller": 0.0,
            "intermediate1": 0.0,
            "intermediate2": 0.0,
            "exit": 0.0,
        }
        varied["resolved_geometry"]["detector"] = {"x_mm": 1234.0}
        self.assertEqual(self._key(baseline), self._key(varied))

    def test_pulse_before_connector_rf_clock_pa_and_selector_change_key(self) -> None:
        mutations = (
            lambda item: item["resolved_connection"]["connector"].update(
                length_mm=25.6
            ),
            lambda item: item["screening_contract"]["rf_time_grid"].update(
                phase_rad=2.8
            ),
            lambda item: item["resolved_connection"]["clock_alignment"].update(
                basis="other_clock"
            ),
            lambda item: item["pa_cache_keys"].update(frontend="other-frontend"),
            lambda item: item["spatial_profile"].update(profile_id="other_selector"),
            lambda item: item["screening_contract"].update(
                selection_order=["spread_asc"]
            ),
        )
        baseline = _fixture()
        baseline_key = self._key(baseline)
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                varied = copy.deepcopy(baseline)
                mutate(varied)
                self.assertNotEqual(baseline_key, self._key(varied))

    def test_only_frontend_and_overlay_pa_roles_are_accepted(self) -> None:
        fixture = _fixture()
        fixture["pa_cache_keys"]["flight_tube"] = "downstream-key"
        with self.assertRaisesRegex(ValueError, "frontend and accelerator-overlay"):
            build_verified_pulse_reuse_projection(**fixture)

    def test_two_local_overlay_keys_enter_verified_reuse_identity(self) -> None:
        fixture = _fixture()
        fixture["pa_cache_keys"] = {
            "frontend": "frontend-key",
            "accelerator_entrance_overlay": "entrance-key",
            "accelerator_intermediate_overlay": "intermediate-key",
            "flight_tube": None,
            "reflectron": None,
        }
        basis, baseline_key = build_verified_pulse_reuse_projection(**fixture)
        self.assertEqual(basis["pa_cache_keys"], {
            "frontend": "frontend-key",
            "accelerator_entrance_overlay": "entrance-key",
            "accelerator_intermediate_overlay": "intermediate-key",
        })
        for role in (
            "accelerator_entrance_overlay",
            "accelerator_intermediate_overlay",
        ):
            varied = copy.deepcopy(fixture)
            varied["pa_cache_keys"][role] = "other-key"
            self.assertNotEqual(
                baseline_key,
                build_verified_pulse_reuse_projection(**varied)[1],
            )

    def test_two_local_overlay_identity_rejects_incomplete_or_mixed_keys(self) -> None:
        fixture = _fixture()
        fixture["pa_cache_keys"] = {
            "frontend": "frontend-key",
            "accelerator_entrance_overlay": "entrance-key",
            "flight_tube": None,
            "reflectron": None,
        }
        with self.assertRaisesRegex(ValueError, "both local"):
            build_verified_pulse_reuse_projection(**fixture)
        fixture["pa_cache_keys"]["accelerator_intermediate_overlay"] = "intermediate-key"
        fixture["pa_cache_keys"]["accelerator_overlay"] = "legacy-key"
        with self.assertRaisesRegex(ValueError, "layout is ambiguous"):
            build_verified_pulse_reuse_projection(**fixture)

    def test_domain_split_uses_its_prepulse_pa_keys_and_ignores_downstream(self) -> None:
        fixture = _fixture()
        fixture["pa_cache_keys"] = {
            "full_coarse_bridge": "coarse-key",
            "fine_upstream": "upstream-key",
            "accelerator_main": "main-key",
            "accelerator_intermediate2_overlay": "intermediate2-key",
            # These are loaded by the IOB but cannot affect the pulse-before
            # screen.  They therefore must not prevent reuse of its evidence.
            "flight_tube": "downstream-key",
            "reflectron": "reflectron-key",
        }
        basis, baseline_key = build_verified_pulse_reuse_projection(**fixture)
        self.assertEqual(
            basis["pa_cache_keys"],
            {
                "full_coarse_bridge": "coarse-key",
                "fine_upstream": "upstream-key",
                "accelerator_main": "main-key",
                "accelerator_intermediate2_overlay": "intermediate2-key",
            },
        )
        varied = copy.deepcopy(fixture)
        varied["pa_cache_keys"]["accelerator_main"] = "other-main-key"
        self.assertNotEqual(
            baseline_key,
            build_verified_pulse_reuse_projection(**varied)[1],
        )

    def test_consumer_numerics_do_not_enter_post_pulse_handoff_identity(self) -> None:
        experiment = {
            "connection_profile_id": "gap_51p2",
            "source_profile_id": "canonical_real_octupole",
            "single_flight_layout_profile_id": "three_zone",
            "architecture_generation_id": "three_zone_v1",
            "field_overlay_id": "overlay_z005",
            "single_flight_frontend_grid_profile_id": "frontend_020",
            "single_flight_oatof_numerical_profile_id": "formal_mesh",
            "single_flight_trajectory_quality_profile_id": "tqual_8",
            "single_flight_time_integration_profile_id": "dt160",
        }
        baseline = post_pulse_handoff_profile_identity(experiment)
        for name, value in (
            ("single_flight_frontend_grid_profile_id", "frontend_010"),
            ("single_flight_oatof_numerical_profile_id", "refined_mesh"),
            ("single_flight_trajectory_quality_profile_id", "tqual_108"),
            ("single_flight_time_integration_profile_id", "dt40"),
        ):
            with self.subTest(name=name):
                varied = dict(experiment)
                varied[name] = value
                self.assertEqual(baseline, post_pulse_handoff_profile_identity(varied))
        changed_physics = dict(experiment)
        changed_physics["connection_profile_id"] = "gap_25p6"
        self.assertNotEqual(baseline, post_pulse_handoff_profile_identity(changed_physics))


if __name__ == "__main__":
    unittest.main()
