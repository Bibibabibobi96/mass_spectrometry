"""Static checks for the unified oaTOF-shield multipole terminal."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from common.contracts.machine_contracts import validate_schema


INTEGRATION_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = INTEGRATION_ROOT.parents[1]
CONFIG_ROOT = INTEGRATION_ROOT / "config"
STAGE_ROOT = INTEGRATION_ROOT / "stages" / "comsol"


def load_json(path: Path) -> dict:
    """Load one UTF-8 integration contract."""
    return json.loads(path.read_text(encoding="utf-8"))


class UnifiedTerminalFieldBasisTests(unittest.TestCase):
    def test_one_integration_owned_terminal_profile_is_schema_valid(self) -> None:
        registry = load_json(CONFIG_ROOT / "downstream_terminal_profiles.json")
        validate_schema(registry, "multipole_downstream_terminal_profiles.schema.json")
        self.assertEqual(len(registry["profiles"]), 1)
        profile = registry["profiles"][0]
        self.assertEqual(profile["terminal_profile_id"], "oatof_shield_terminal")
        self.assertEqual(profile["outer_envelope"]["width_mm"], 38.0)
        self.assertEqual(profile["outer_envelope"]["height_mm"], 38.0)
        self.assertEqual(profile["electrode_thickness_mm"], 4.0)

    def test_shared_joint_freezes_one_downstream_terminal(self) -> None:
        joint = load_json(CONFIG_ROOT / "family_shared_physical_port_joint_geometry.json")
        terminal = joint["electrical_interface"]["terminal_electrode"]
        geometry = joint["terminal_geometry"]

        self.assertEqual(joint["schema_version"], 2)
        self.assertEqual(terminal["owner"], "downstream")
        self.assertEqual(terminal["geometry_tag"], "accelshield")
        self.assertTrue(terminal["serves_as_multipole_exit_aperture_electrode"])
        self.assertFalse(terminal["separate_upstream_exit_plate_allowed"])
        self.assertEqual(terminal["potential_V"], 0.0)
        self.assertEqual(geometry["rod_end_to_terminal_outer_face_mm"], 1.0)
        self.assertEqual(
            geometry["terminal_aperture_binding"],
            "rf_resolved_geometry:/downstream_terminal/aperture",
        )

    def test_local_exit_is_the_physical_grid2_surface(self) -> None:
        joint = load_json(CONFIG_ROOT / "family_shared_physical_port_joint_geometry.json")
        event = joint["diagnostic_events"]["local_accelerator_exit"]
        pulse = (STAGE_ROOT / "solve_pulse_capture.m").read_text(encoding="utf-8")

        self.assertEqual(event["physical_surface_role"], "accelerator_grid2")
        self.assertEqual(event["sampling_offset_mm"], 0.0)
        self.assertFalse(event["numerical_domain_boundary_allowed"])
        self.assertIn(
            "localPlane = oa.geometry_mm.accelerator_grid2_z;", pulse
        )
        self.assertNotIn(
            "accelerator_grid2_z+context.oatof_downstream_buffer_mm", pulse
        )

    def test_current_family_geometry_has_one_millimeter_rod_clearance(self) -> None:
        for family in ("quadrupole", "hexapole", "octupole"):
            project = f"rf_{family}_ion_optics"
            publication = load_json(
                REPO_ROOT
                / "projects"
                / project
                / "config"
                / "resolved_design_no_acceleration_full_length.json"
            )
            resolved = publication.get("resolved_design", publication)
            rods = resolved["geometry_mm"]["rod_array"]["rods"]
            rod_end_mm = max(float(rod["z_max_mm"]) for rod in rods)
            terminal_face_mm = float(
                resolved["interfaces_mm"]["exit"]["handoff_plane_z_mm"]
            )
            self.assertAlmostEqual(terminal_face_mm - rod_end_mm, 1.0, places=12)

    def test_builder_does_not_create_duplicate_rf_exit_plate(self) -> None:
        source = (STAGE_ROOT / "build_pre_pulse_interface_transport_model.m").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("add_annular_plate(geom, 'rfexit'", source)
        self.assertNotIn("'rfshield','rfentrance','rfexit'", source)
        self.assertIn("'terminal_electrode_tag', 'accelshield'", source)
        self.assertIn("~resolvedTerminal.upstream_terminal_electrode_present", source)

    def test_builder_materializes_the_governed_source_reference_sleeve(self) -> None:
        builder = (
            STAGE_ROOT / "build_pre_pulse_interface_transport_model.m"
        ).read_text(encoding="utf-8")
        preparer = (
            STAGE_ROOT / "prepare_pre_pulse_interface_transport_field_model.m"
        ).read_text(encoding="utf-8")
        joint = load_json(CONFIG_ROOT / "family_shared_physical_port_joint_geometry.json")

        for token in (
            "entrance_reference_sleeve",
            "source_reference_sleeve_v1",
            "functional_source_reference_not_shield",
            "sleeveUpstreamZ = rf.axial_dc.entrance_reference_sleeve.upstream_face_z_mm",
            "upstreamSurface.center_mm(3)-sleeveUpstreamZ",
            "rf.segmentation.segmented_rod_array.electrodes",
            "add_segmented_rf_rods",
            "segment_count*numel(g.rod_array.rods)",
            "'rf_axial_drive_topology', rf.axial_drive.topology",
            "'rf_entrance_plate_potential_V', rf.axial_dc.entrance_plate_potential_V",
            "geom.feature.create('refsleeve', 'Difference')",
            "'entrance_reference_sleeve_tag', 'refsleeve'",
        ):
            self.assertIn(token, builder)
        self.assertIn("set_potential(esAxial, 'source_reference_sleeve'", preparer)
        self.assertIn("set_potential(esAxial, 'entrance_plate'", preparer)
        self.assertIn("set_potential(esOatof, 'g_source_reference_sleeve'", preparer)
        self.assertIn("{context.entrance_reference_sleeve_tag}", preparer)
        self.assertEqual(
            joint["field_basis"]["axial_dc"][
                "entrance_reference_sleeve_potential_source"
            ],
            "rf_resolved_geometry:/axial_dc/entrance_reference_sleeve/potential_V",
        )

    def test_field_model_uses_three_orthogonal_bases(self) -> None:
        preparer = (
            STAGE_ROOT / "prepare_pre_pulse_interface_transport_field_model.m"
        ).read_text(encoding="utf-8")
        pre_pulse = (STAGE_ROOT / "solve_pre_pulse_interface_transport_field.m").read_text(
            encoding="utf-8"
        )
        pulse = (STAGE_ROOT / "solve_pulse_capture.m").read_text(encoding="utf-8")

        for token in ("es_axial_dc", "es_rf", "es_oatof_pulse"):
            self.assertIn(token, preparer)
        self.assertNotIn("es_static", preparer + pre_pulse + pulse)
        self.assertIn("-d(Vaxial,x)", pre_pulse)
        self.assertNotIn("Voatof", pre_pulse)
        self.assertIn("-d(Vaxial,x)", pulse)
        self.assertIn("-d(Voatof,x)", pulse)

    def test_phase_contracts_expose_basis_schedule(self) -> None:
        pre_pulse = load_json(CONFIG_ROOT / "family_pre_pulse_interface_transport.json")
        pulse = load_json(CONFIG_ROOT / "family_pulse_capture.json")
        self.assertEqual(
            pre_pulse["field_runtime"]["included_bases"],
            ["axial_dc", "time_dependent_rf"],
        )
        self.assertEqual(
            pulse["waveform"]["always_enabled_bases"],
            ["axial_dc", "time_dependent_rf"],
        )
        self.assertEqual(pulse["waveform"]["pulsed_basis"], "oatof_pulse")


if __name__ == "__main__":
    unittest.main()
