from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.machine_contracts import ContractError, REPO_ROOT, file_sha256
from projects.rf_multipole_ion_optics.core.axial_acceleration import MAX_SEGMENT_COUNT
from projects.rf_multipole_ion_optics.core.compile_design_request import (
    MultipoleDesignCompileError,
    compile_design_request,
    compile_design_request_file,
    resolved_design_sha256,
    validate_resolved_design,
)


STRUCTURAL_IDENTITIES = {
    "quadrupole": (2, 4),
    "hexapole": (3, 6),
    "octupole": (4, 8),
}


def identity(structural_variant_id: str) -> dict:
    order, count = STRUCTURAL_IDENTITIES[structural_variant_id]
    return {
        "project_id": "rf_multipole_ion_optics",
        "family_id": "rf_multipole_ion_optics",
        "radial_order_n": order,
        "electrode_count": count,
    }


def design_request(structural_variant_id: str = "quadrupole", segmentation: dict | None = None) -> dict:
    """Current bare provider fixture; shell and numerical/source choices are explicit."""
    segmentation = segmentation or {"strategy": "off"}
    return {
        "schema_version": 3,
        "role": "multipole_design_request",
        "request_id": structural_variant_id + "_bare",
        "identity": identity(structural_variant_id),
        "units": dict(length="mm", voltage="V", frequency="Hz", phase="rad", energy="eV"),
        "coordinate": dict(coordinate_id="multipole.cartesian.z_axis.v1", axial_axis="+z", orientation_rad=0.125),
        "geometry_mm": dict(
            inscribed_radius_r0=4.0,
            rod_radius_ratio=0.5,
            rod_z_min=5.0,
            rod_z_max=85.0,
            numerical_domain=dict(radius_mm=21.0, z_min_mm=2.0, z_max_mm=90.0, working_region_radius_mm=3.6),
            observations=dict(
                release_plane_z_mm=3.0, handoff_plane_z_mm=86.0, census_plane_z_mm=87.0, acceptance_radius_mm=3.25
            ),
        ),
        "drive": dict(
            waveform="cosine",
            rf_amplitude_V_zero_to_peak_per_group=139.81792,
            dc_amplitude_V_per_group=2.5,
            common_mode_offset_V=-8.0,
            frequency_Hz=1_100_000.0,
            phase_rad=0.3,
        ),
        "axial_drive": dict(
            topology="none" if segmentation["strategy"] == "off" else "segmented_rod_axial_acceleration"
        ),
        "static_electrodes_V": dict(role="bare_multipole_static_electrodes"),
        "particle_source": dict(energy_model=dict(kind="monoenergetic", kinetic_energy_eV=2.0), charge_state=1),
        "segmentation": segmentation,
    }


def multipole_catalog(project_id: str, request_contract: str) -> dict:
    return {
        "schema_version": 1,
        "role": "project_design_variable_catalog",
        "project_id": project_id,
        "family_id": "rf_multipole_ion_optics",
        "optimization_strategy": "multipole_design_request_compilation",
        "range_policy": "Only request values inside these compilation bounds are eligible.",
        "variables": [
            {
                "variable_id": "r0",
                "label": "Inscribed radius",
                "kind": "continuous",
                "optimization_role": "geometry",
                "json_pointer": "/geometry_mm/inscribed_radius_r0",
                "unit": "mm",
                "minimum": 1.0,
                "maximum": 10.0,
                "compile_status": "candidate_contract",
                "rebuild_effects": [
                    "resolved",
                    "comsol",
                    "simion",
                    "spatial_interface",
                ],
            }
        ],
        "invariants": [
            "project_identity_locked",
            "electrode_count_equals_twice_radial_order",
            "rod_span_positive",
            "interface_nonoverlap",
            "segment_length_conservation",
            "connector_shape_supported",
        ],
    }


class MultipoleDesignCompilerTest(unittest.TestCase):
    def compile(self, request):
        return compile_design_request(request, expected_identity=request["identity"])

    def shell_request(self):
        request = design_request("octupole")
        request["geometry_mm"]["enclosure"] = dict(
            model="cylindrical_grounded_shell", inner_radius_mm=20.0, wall_thickness_mm=1.0, z_min_mm=2.0, z_max_mm=89.0
        )
        request["static_electrodes_V"] = dict(role="grounded_shell_static_electrodes", ground_V=0.0)
        return request

    def test_all_structures_default_to_bare_with_independent_observations(self):
        for variant in STRUCTURAL_IDENTITIES:
            with self.subTest(variant=variant):
                request = design_request(variant)
                resolved = self.compile(request)
                self.assertEqual(resolved["geometry_mm"]["enclosure"], {"model": "bare"})
                self.assertEqual(resolved["geometry_mm"]["enclosure_layout"]["bodies"], [])
                self.assertEqual(resolved["geometry_mm"]["observations"], request["geometry_mm"]["observations"])
                self.assertNotIn("interfaces_mm", resolved)
                self.assertEqual(resolved["identity"], identity(variant))
                self.assertEqual(
                    len(resolved["geometry_mm"]["rod_array"]["rods"]), identity(variant)["electrode_count"]
                )

    def test_shell_open_and_endcap_cases_share_ground_without_positive_overlap(self):
        for sides in ((), ("entrance",), ("exit",), ("entrance", "exit")):
            request = self.shell_request()
            request["geometry_mm"]["enclosure"]["endcaps"] = {
                side: dict(aperture_radius_mm=3.6, thickness_mm=0.5) for side in sides
            }
            resolved = self.compile(request)
            layout = resolved["geometry_mm"]["enclosure_layout"]
            self.assertEqual(len(layout["bodies"]), 1 + len(sides))
            shell = layout["bodies"][0]
            for cap in layout["bodies"][1:]:
                self.assertEqual(cap["outer_radius_mm"], shell["inner_radius_mm"])
                self.assertGreater(cap["z_max_mm"], cap["z_min_mm"])
            for side in ("entrance", "exit"):
                port = layout["ports"]["mechanical_" + side]
                self.assertEqual(port["cross_section"]["radius_mm"], 3.6 if side in sides else 20.0)
                self.assertEqual(port["center_mm"][2], 2.0 if side == "entrance" else 89.0)

    def test_shell_does_not_control_source_or_numeric_domain(self):
        request = self.shell_request()
        first = self.compile(request)
        request["geometry_mm"]["numerical_domain"]["z_max_mm"] = 200.0
        second = self.compile(request)
        self.assertEqual(first["geometry_mm"]["enclosure_layout"], second["geometry_mm"]["enclosure_layout"])
        self.assertEqual(first["geometry_mm"]["observations"], second["geometry_mm"]["observations"])

    def test_endcap_radius_and_real_rod_intersection_are_rejected(self):
        for cap in (dict(aperture_radius_mm=20.0, thickness_mm=0.5), dict(aperture_radius_mm=3.0, thickness_mm=10.0)):
            request = self.shell_request()
            request["geometry_mm"]["enclosure"]["endcaps"] = {"entrance": cap}
            with self.assertRaises(MultipoleDesignCompileError):
                self.compile(request)
        request = self.shell_request()
        request["geometry_mm"]["enclosure"]["endcaps"] = {"entrance": dict(aperture_radius_mm=12.0, thickness_mm=10.0)}
        self.compile(request)  # A wide hole actually clears all rods.

    def test_grounded_endcap_cannot_touch_rod_endface_or_radial_surface(self):
        for aperture, thickness in ((3., 3.), (8., 4.)):
            with self.subTest(aperture=aperture, thickness=thickness):
                request = self.shell_request()
                request["geometry_mm"]["enclosure"]["endcaps"] = {
                    "entrance": dict(aperture_radius_mm=aperture, thickness_mm=thickness)
                }
                with self.assertRaisesRegex(MultipoleDesignCompileError,"endcap intersects"):
                    self.compile(request)

    def test_retired_geometry_and_optical_fields_are_rejected(self):
        for change in (
            lambda g: g.update(entrance_interface={}),
            lambda g: g.update(enclosure={"model": "cylindrical_grounded_shield_v1"}),
            lambda g: g.update(exit_electrode_radial_gap_mm=1.0),
        ):
            request = design_request()
            change(request["geometry_mm"])
            with self.assertRaises(ContractError):
                self.compile(request)
        request = design_request()
        request["axial_drive"]["topology"] = "exit_aperture_plate_potential_step"
        with self.assertRaises(ContractError):
            self.compile(request)

    def test_bare_has_no_static_shell_voltage(self):
        request = design_request()
        request["static_electrodes_V"] = dict(role="grounded_shell_static_electrodes", ground_V=0.0)
        with self.assertRaisesRegex(ContractError, "static-electrode topology"):
            self.compile(request)

    def test_identity_units_finiteness_and_domain_bounds_are_checked(self):
        for mutate in (
            lambda q: q["units"].update(length="m"),
            lambda q: q["geometry_mm"].update(rod_z_max=4.0),
            lambda q: q["geometry_mm"]["numerical_domain"].update(radius_mm=1.0),
            lambda q: q["geometry_mm"]["observations"].update(census_plane_z_mm=100.0),
            lambda q: q["drive"].update(frequency_Hz=float("nan")),
        ):
            request = design_request()
            mutate(request)
            with self.assertRaises((ContractError, ValueError)):
                self.compile(request)
        request = design_request()
        with self.assertRaises(ContractError):
            compile_design_request(request, expected_identity=identity("octupole"))

    def test_segmented_drive_retains_physical_rods(self):
        request = design_request(
            segmentation=dict(
                strategy="uniform",
                segment_count=4,
                intersegment_gap_mm=0.4,
                entrance_common_mode_V=3.0,
                exit_common_mode_V=0.0,
                output_reference_V=0.0,
            )
        )
        resolved = self.compile(request)
        self.assertEqual(resolved["axial_drive"]["predicted_energy_gain_eV"], 3.0)
        self.assertEqual(resolved["segmentation"]["segmented_rod_array"]["segment_count"], 4)
        self.assertEqual(resolved["geometry_mm"]["enclosure_layout"]["bodies"], [])

    def test_source_and_resolved_identities_are_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "request.json"
            request = design_request()
            path.write_text(json.dumps(request), encoding="utf-8")
            result = compile_design_request_file(path, expected_identity=request["identity"], source_root=root)
            self.assertEqual(result["resolved_sha256"], resolved_design_sha256(result))
            self.assertEqual(
                result,
                validate_resolved_design(
                    result, request_path=path, source_root=root, expected_identity=request["identity"]
                ),
            )
            result["geometry_mm"]["observations"]["handoff_plane_z_mm"] += 0.1
            with self.assertRaises(ContractError):
                validate_resolved_design(
                    result, request_path=path, source_root=root, expected_identity=request["identity"]
                )

    def test_explicit_rectangular_reference_remains_independent(self):
        path = REPO_ROOT / "projects/rf_multipole_ion_optics/variants/quadrupole/config/requests/official.json"
        request = json.loads(path.read_text(encoding="utf-8-sig"))
        resolved = self.compile(request)
        self.assertEqual(resolved["geometry_mm"]["enclosure"]["model"], "rectangular_reference_enclosure_v1")
        self.assertIn("interfaces_mm", resolved)
        self.assertNotIn("enclosure_layout", resolved["geometry_mm"])

    def test_off_uniform_and_explicit_segmentation_use_shared_resolver(self) -> None:
        off = self.compile(design_request())["segmentation"]
        self.assertEqual(off["strategy"], "off")
        self.assertIsNone(off["axial_acceleration"])
        self.assertIsNone(off["segmented_rod_array"])

        uniform_request = design_request(
            segmentation={
                "strategy": "uniform",
                "segment_count": 4,
                "intersegment_gap_mm": 0.5,
                "entrance_common_mode_V": 0.0,
                "exit_common_mode_V": -3.0,
                "output_reference_V": -3.0,
            }
        )
        uniform = self.compile(uniform_request)["segmentation"]
        self.assertEqual(uniform["strategy"], "uniform")
        self.assertEqual(
            [item["common_mode_V"] for item in uniform["axial_acceleration"]["derived"]["segments"]],
            [0.0, -1.0, -2.0, -3.0],
        )
        self.assertEqual(uniform["segmented_rod_array"]["segment_count"], 4)
        self.assertEqual(len(uniform["segmented_rod_array"]["electrodes"]), 16)

        explicit_request = design_request(
            segmentation={
                "strategy": "explicit",
                "segments": [
                    {"length_mm": 20.0, "gap_after_mm": 1.0, "common_mode_V": 0.0},
                    {"length_mm": 19.0, "common_mode_V": -1.0},
                    {"length_mm": 40.0, "common_mode_V": -3.0},
                ],
                "output_reference_V": -3.0,
            }
        )
        explicit = self.compile(explicit_request)["segmentation"]
        self.assertEqual(explicit["strategy"], "explicit")
        self.assertEqual(
            [(item["z_min_mm"], item["z_max_mm"]) for item in explicit["axial_acceleration"]["derived"]["segments"]],
            [(5.0, 25.0), (26.0, 45.0), (45.0, 85.0)],
        )

    def test_legacy_scalar_particle_energy_is_rejected(self) -> None:
        request = design_request()
        request["particle_source"] = {
            "kinetic_energy_eV": 2.0,
            "charge_state": 1,
        }
        with self.assertRaises(MultipoleDesignCompileError):
            self.compile(request)

    def test_bounded_energy_model_requires_ordered_bounds_and_nominal(self) -> None:
        request = design_request()
        request["particle_source"]["energy_model"] = {
            "kind": "bounded_distribution",
            "minimum_energy_eV": 1.8,
            "maximum_energy_eV": 2.2,
            "nominal_energy_eV": 2.0,
            "authority": "fixture.json",
        }
        resolved = self.compile(request)
        self.assertEqual(
            resolved["particle_source"]["energy_model"],
            request["particle_source"]["energy_model"],
        )
        request["particle_source"]["energy_model"]["minimum_energy_eV"] = 2.3
        with self.assertRaisesRegex(MultipoleDesignCompileError, "minimum energy exceeds"):
            self.compile(request)

    def test_499_segments_compile_and_500_are_rejected(self) -> None:
        maximum = design_request(
            segmentation={
                "strategy": "uniform",
                "segment_count": MAX_SEGMENT_COUNT,
                "intersegment_gap_mm": 0.0,
                "entrance_common_mode_V": 0.0,
                "exit_common_mode_V": -1.0,
                "output_reference_V": -1.0,
            }
        )
        resolved = self.compile(maximum)
        self.assertEqual(
            resolved["segmentation"]["segmented_rod_array"]["segment_count"],
            MAX_SEGMENT_COUNT,
        )
        invalid = copy.deepcopy(maximum)
        invalid["segmentation"]["segment_count"] = MAX_SEGMENT_COUNT + 1
        with self.assertRaises(MultipoleDesignCompileError):
            self.compile(invalid)

        explicit = design_request(
            segmentation={
                "strategy": "explicit",
                "segments": [
                    {
                        "length_mm": 80.0 / (MAX_SEGMENT_COUNT + 1),
                        "common_mode_V": -index / MAX_SEGMENT_COUNT,
                    }
                    for index in range(MAX_SEGMENT_COUNT + 1)
                ],
                "output_reference_V": -1.0,
            }
        )
        with self.assertRaises(MultipoleDesignCompileError):
            self.compile(explicit)

    def test_source_hashes_and_resolved_hash_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request_path = root / "request.json"
            auxiliary = root / "mode.json"
            request_path.write_text(
                json.dumps(design_request(), indent=2) + "\n",
                encoding="utf-8",
            )
            auxiliary.write_text('{"mode":"test"}\n', encoding="utf-8")
            expected = identity("quadrupole")
            first = compile_design_request_file(
                request_path,
                expected_identity=expected,
                source_files={"mode": auxiliary},
            )
            second = compile_design_request_file(
                request_path,
                expected_identity=expected,
                source_files={"mode": auxiliary},
            )
            self.assertEqual(first, second)
            self.assertEqual(first["resolved_sha256"], resolved_design_sha256(first))
            self.assertEqual(
                [record["label"] for record in first["sources"]],
                ["design_request", "mode"],
            )
            self.assertEqual(
                {record["label"]: record["sha256"] for record in first["sources"]},
                {
                    "design_request": file_sha256(request_path),
                    "mode": file_sha256(auxiliary),
                },
            )
            auxiliary.write_text('{"mode":"changed"}\n', encoding="utf-8")
            changed = compile_design_request_file(
                request_path,
                expected_identity=expected,
                source_files={"mode": auxiliary},
            )
            self.assertNotEqual(
                first["sources"][1]["sha256"],
                changed["sources"][1]["sha256"],
            )
            self.assertNotEqual(first["resolved_sha256"], changed["resolved_sha256"])


if __name__ == "__main__":
    unittest.main()
