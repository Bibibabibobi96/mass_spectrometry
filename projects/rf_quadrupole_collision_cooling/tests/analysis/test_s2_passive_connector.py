from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from projects.rf_quadrupole_collision_cooling.analysis import validate_s2_passive_connector as module
from projects.rf_quadrupole_collision_cooling.analysis import resolve_spatial_registration as resolver


class S2PassiveConnectorTests(unittest.TestCase):
    def test_contract_inherits_shared_geometry_and_freezes_one_mm_gap(self) -> None:
        contract = module.validate_contract()
        registration = contract["nominal_registration"]
        geometry = contract["passive_connector_geometry"]
        self.assertEqual(registration["connector_gap_mm"], 1.0)
        self.assertEqual(registration["source_exit_center_instrument_mm"][0], -68.8)
        self.assertEqual(registration["target_entry_center_instrument_mm"][0], -67.8)
        self.assertEqual(geometry["upstream_clear_aperture"]["radius_mm"], 3.6)
        self.assertEqual(geometry["downstream_entry_aperture"]["full_width_y_mm"], 1.0)
        self.assertEqual(geometry["downstream_entry_aperture"]["full_height_z_mm"], 0.9)
        self.assertFalse(contract["field_ownership"]["oa_extraction_pulse_included"])
        self.assertTrue(contract["permissions"]["field_solve_allowed"])
        self.assertTrue(contract["permissions"]["particle_runtime_allowed"])
        self.assertFalse(
            contract["no_pulse_field_candidate"]["mesh"]["convergence_claim_allowed"]
        )
        rf = json.loads(
            (module.PROJECT_ROOT / contract["inputs"]["rf_resolved_geometry"]).read_text(
                encoding="utf-8"
            )
        )
        self.assertLess(
            contract["no_pulse_field_candidate"]["rf_off_axis_probe_radius_mm"],
            rf["geometry_mm"]["inscribed_radius_r0"],
        )
        evidence = contract["geometry_build_evidence"]
        self.assertEqual(evidence["status"], "PASS")
        self.assertEqual(evidence["connector_domain_count"], 1)
        self.assertEqual(evidence["port_domain_count"], 1)
        self.assertFalse(evidence["field_solved"])
        dependencies = json.loads(
            (module.PROJECT_ROOT / contract["inputs"]["explicit_dependencies"]).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(dependencies["schema_version"], 2)
        self.assertEqual(
            set(dependencies["consumer_ids"]), module.DEPENDENCY_CONSUMERS
        )
        s2_dependencies = {
            item["id"] for item in dependencies["dependencies"]
            if "s2_passive_connector" in item["consumers"]
        }
        self.assertEqual(s2_dependencies, module.S2_DEPENDENCY_IDS)
        self.assertEqual(
            {item["provider_scope"] for item in dependencies["dependencies"]},
            {"project", "repository_common"},
        )
        self.assertTrue(
            dependencies["runtime_policy"]["verify_source_and_frozen_sha256_equal"]
        )
        particle_evidence = contract["nominal_particle_evidence"]
        self.assertEqual(particle_evidence["source_particles"], 100)
        self.assertEqual(particle_evidence["oatof_entry_crossings"], 61)
        self.assertEqual(particle_evidence["downstream_entry_wall_losses"], 39)
        self.assertFalse(particle_evidence["s2_stage_passed"])

    def test_shared_physical_values_equal_the_extracted_source_exactly(self) -> None:
        shared = json.loads((
            module.PROJECT_ROOT / "config" /
            "rf_to_oatof_shared_physical_port_joint_geometry.json"
        ).read_text(encoding="utf-8"))
        expected = {
            "nominal_registration": {
                "instrument_frame": "oatof_global",
                "target_component_pose": {"rotation_component_to_instrument": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], "translation_mm": [0.0, 0.0, 0.0]},
                "source_component_pose": {"rotation_component_to_instrument": [[0.0, 0.0, 1.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], "translation_mm": [-158.0, 0.0, -18.42918680341103]},
                "source_exit_center_local_mm": [0.0, 0.0, 90.2],
                "source_exit_center_instrument_mm": [-67.8, 0.0, -18.42918680341103],
                "target_entry_center_instrument_mm": [-67.8, 0.0, -18.42918680341103],
                "direct_mating_gap_mm": 0.0,
                "axis_mapping": "RF +z -> oa +x; RF +x -> oa +y; RF +y -> oa +z",
            },
            "local_domain": {"rf_shield_inner_radius_mm": 19.776, "rf_shield_numerical_wall_thickness_mm": 1.0, "oatof_downstream_buffer_after_grid2_mm": 5.0},
            "port_sweep": {"shape": "rectangle", "center_z_mm": -18.42918680341103, "full_height_z_mm": 0.9, "selected_n100_candidate_full_width_y_mm": 1.0, "particle_release_offset_inside_outer_face_mm": 0.001},
            "field_basis": {"shared_geometry_required": True, "rf_unit": {"rod_differential_pattern_V": [100.0, -100.0, 100.0, -100.0], "all_oatof_electrodes_and_grounded_hardware_V": 0.0, "runtime_scale": "V_rf_peak/100[V] * sin(2*pi*f_rf*instrument_time + phase)"}},
        }
        for section, values in expected.items():
            self.assertEqual(set(shared[section]), set(values), section)
            for key, value in values.items():
                self.assertEqual(shared[section][key], value, f"{section}.{key}")

    def test_shared_boundary_and_electrical_sources_are_bound_per_key(self) -> None:
        shared = json.loads(resolver.SHARED_JOINT.read_text(encoding="utf-8"))
        rf = json.loads((module.PROJECT_ROOT / "config" / "resolved_design_official.json").read_text(encoding="utf-8"))
        oatof = json.loads((module.PROJECT_ROOT.parent / "oa_tof" / "config" / "baseline.json").read_text(encoding="utf-8"))
        source = shared["physical_boundaries"]["source_exit_surface"]
        self.assertEqual(source["bindings"]["local_center_z_mm"]["json_pointer"], "/interfaces_mm/exit/connector_z_max_mm")
        self.assertEqual(source["bindings"]["outward_normal"]["json_pointer"], "/coordinate/axial_axis")
        self.assertEqual(source["physical_aperture"]["source_binding"]["json_pointer"], "/interfaces_mm/exit/aperture_radius_mm")
        target = shared["physical_boundaries"]["target_entry_surface"]
        self.assertEqual(target["reference_binding"]["source_input"], "oatof_baseline")
        common_sources = {(item["source_input"], item["json_pointer"]) for item in shared["electrical_interface"]["common_potential_reference"]["required_equal_source_bindings"]}
        self.assertEqual(common_sources, {("rf_resolved_geometry", "/drive/common_mode_offset_V"), ("oatof_baseline", "/electrodes_V/shield")})
        resolver._validate_shared_authority(shared, rf, oatof)
        mutations = []
        for path, value in (
            (("physical_boundaries", "source_exit_surface", "local_center_mm", 2), 91.2),
            (("physical_boundaries", "source_exit_surface", "outward_normal", 2), -1.0),
            (("physical_boundaries", "source_exit_surface", "physical_aperture", "radius_mm"), 3.5),
            (("physical_boundaries", "target_entry_surface", "center_mm", 0), -67.7),
            (("electrical_interface", "common_potential_reference", "potential_V"), 1.0),
        ):
            changed = deepcopy(shared)
            cursor = changed
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] = value
            mutations.append(changed)
        for changed in mutations:
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    resolver._validate_shared_authority(changed, rf, oatof)

        for source_name, source_document in (
            ("rf", deepcopy(rf)),
            ("oatof", deepcopy(oatof)),
        ):
            if source_name == "rf":
                source_document["drive"]["common_mode_offset_V"] = 1.0
                changed_rf, changed_oatof = source_document, oatof
            else:
                source_document["electrodes_V"]["shield"] = 1.0
                changed_rf, changed_oatof = rf, source_document
            with self.subTest(common_potential_source=source_name):
                with self.assertRaisesRegex(ValueError, "common-potential"):
                    resolver._validate_shared_authority(
                        shared, changed_rf, changed_oatof
                    )

    def test_active_builder_is_build_only_and_consumes_shared_geometry(self) -> None:
        builder = (module.PROJECT_ROOT / "tests" / "comsol" / "build_s2_passive_connector_model.m").read_text(encoding="utf-8")
        self.assertIn("REPOSITORY_CONTRACT: MATLAB_BUILD_ONLY", builder)
        self.assertIn("sharedJoint.local_domain.rf_shield_inner_radius_mm", builder)
        self.assertIn("assert_supported_registration(registration, spatial)", builder)
        self.assertNotIn("expectedSourceRotation", builder)
        for token in ("runAll", "mesh.create", "physics.create", "mphsave", "model.save"):
            self.assertNotIn(token, builder)

    def test_builder_applies_full_resolved_pose_to_rf_cylinders(self) -> None:
        builder = (
            module.PROJECT_ROOT
            / "tests"
            / "comsol"
            / "build_s2_passive_connector_model.m"
        ).read_text(encoding="utf-8")

        # This proper rotation maps local +z away from the frozen legacy +x axis,
        # plus nonzero translation in all three instrument-frame components.
        rotation = ((0.0, -1.0, 0.0), (0.0, 0.0, -1.0), (1.0, 0.0, 0.0))
        translation = (11.0, 22.0, 33.0)
        local_position = (2.0, 3.0, 5.0)

        def rotate(vector: tuple[float, float, float]) -> tuple[float, float, float]:
            return tuple(
                sum(row[index] * vector[index] for index in range(3))
                for row in rotation
            )

        rotated_position = rotate(local_position)
        transformed_position = tuple(
            rotated_position[index] + translation[index] for index in range(3)
        )
        transformed_axis = rotate((0.0, 0.0, 1.0))
        old_hardcoded_position = (
            translation[0] + local_position[2],
            local_position[0],
            translation[2] + local_position[1],
        )

        self.assertEqual(transformed_position, (8.0, 17.0, 35.0))
        self.assertEqual(transformed_axis, (0.0, -1.0, 0.0))
        self.assertNotEqual(transformed_position, old_hardcoded_position)
        self.assertNotEqual(transformed_axis, (1.0, 0.0, 0.0))
        for token in (
            "sourceTranslation = sourcePose.translation_mm(:);",
            "sourceAxis = sourceRotation * [0.0; 0.0; 1.0];",
            "positionMm = (rotation*localPositionMm(:)+translation).';",
            "transform_source_position(sourcePose, localStart), sourceAxis",
            "gapMm, sourceCenter, sourceAxis, true",
            "sourceCenter(:)-",
            "targetCenter(:)-",
            "gapMm*sourceAxis(:)",
            "<= 1e-12,'all'",
            "sourceCenterMatches && targetCenterMatches && gapVectorMatches",
            "geom.feature(tag).set('axis', axisDirection(:).');",
        ):
            self.assertIn(token, builder)
        for forbidden in (
            "tx = sourcePose.translation_mm(1)",
            "tz = sourcePose.translation_mm(3)",
            "[tx, 0.0, tz]",
            "{'1','0','0'}",
            "targetCenter(1)-sourceCenter(1)-gapMm",
            "(targetCenter-sourceCenter).'",
        ):
            self.assertNotIn(forbidden, builder)

    def test_active_field_path_is_fail_closed_and_uses_shared_builder(self) -> None:
        field_builder = (module.PROJECT_ROOT / "tests" / "comsol" / "prepare_s2_joint_field_model.m").read_text(encoding="utf-8")
        solver = (module.PROJECT_ROOT / "tests" / "comsol" / "solve_s2_passive_connector_field.m").read_text(encoding="utf-8")
        runner = (module.PROJECT_ROOT / "tests" / "comsol" / "run_s2_passive_connector_field.ps1").read_text(encoding="utf-8")
        self.assertIn("build_s2_passive_connector_model", field_builder)
        self.assertIn("connector_gap_mm > 0", field_builder)
        self.assertIn("ChargedParticleTracing", solver)
        self.assertIn("particle_runtime_allowed", runner)
        self.assertIn("Complete-RfFrozenFailedRun", runner)
        self.assertIn("mesh_convergence_claimed = $false", runner)
        self.assertIn("'--shared-joint',$sharedJoint", runner)
        self.assertIn("connector-gap${gapLabel}__n100", runner)
        self.assertIn("field__gap${gapLabel}", runner)
        self.assertNotIn("$gapLabel__n100", runner)
        self.assertNotIn("rf_to_oatof_interface_candidate.json", runner)
        self.assertNotIn("--interface", runner)

    def test_shared_builder_supports_zero_gap_without_a_second_entrypoint(self) -> None:
        builder = (module.PROJECT_ROOT / "tests" / "comsol" / "build_s2_passive_connector_model.m").read_text(encoding="utf-8")
        self.assertIn("connectorPresent = gapMm > 0", builder)
        self.assertIn("if connectorPresent", builder)
        self.assertIn("connectorDomains = []", builder)
        contract = json.loads(module.DEFAULT_CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(contract["nominal_registration"]["connector_gap_mm"], 1.0)
        self.assertTrue(contract["passive_connector_geometry"]["zero_gap_supported"])

    def test_contract_rejects_a_gap_that_breaks_the_pose_derivation(self) -> None:
        contract = json.loads(module.DEFAULT_CONTRACT.read_text(encoding="utf-8"))
        contract["nominal_registration"]["connector_gap_mm"] = 2.0
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "gap"):
                module.validate_contract(path)

    def test_contract_rejects_disabled_particle_runtime_after_authorization(self) -> None:
        contract = json.loads(module.DEFAULT_CONTRACT.read_text(encoding="utf-8"))
        contract["permissions"]["particle_runtime_allowed"] = False
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "particle candidate"):
                module.validate_contract(path)

    def test_contract_rejects_source_y_translation_not_supported_by_geometry(self) -> None:
        contract = json.loads(module.DEFAULT_CONTRACT.read_text(encoding="utf-8"))
        contract["nominal_registration"]["source_component_pose"]["translation_mm"][1] = 0.1
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "NEEDS_IMPLEMENTATION"):
                module.validate_contract(path)

    def test_contract_rejects_target_entry_that_differs_from_interface(self) -> None:
        contract = json.loads(module.DEFAULT_CONTRACT.read_text(encoding="utf-8"))
        contract = deepcopy(contract)
        contract["nominal_registration"]["target_entry_center_instrument_mm"][1] = 0.1
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "NEEDS_IMPLEMENTATION"):
                module.validate_contract(path)


if __name__ == "__main__":
    unittest.main()
