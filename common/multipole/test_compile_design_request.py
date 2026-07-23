from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.build_project_registry import validate_descriptor
from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError, REPO_ROOT, validate_schema
from common.multipole.axial_acceleration import MAX_SEGMENT_COUNT
from common.multipole.compile_design_request import (
    MultipoleDesignCompileError,
    compile_design_request,
    compile_design_request_file,
    compile_governed_design_request_file,
    resolved_design_sha256,
    validate_resolved_design,
)


PROJECT_IDENTITIES = {
    "rf_quadrupole_collision_cooling": (2, 4),
    "rf_hexapole_ion_guide": (3, 6),
    "rf_octupole_ion_guide": (4, 8),
}


def identity(project_id: str) -> dict:
    order, count = PROJECT_IDENTITIES[project_id]
    return {
        "project_id": project_id,
        "family_id": "rf_multipole_ion_optics",
        "radial_order_n": order,
        "electrode_count": count,
    }


def design_request(
    project_id: str = "rf_quadrupole_collision_cooling",
    segmentation: dict | None = None,
) -> dict:
    segmentation = segmentation or {"strategy": "off"}
    if project_id == "rf_quadrupole_collision_cooling":
        enclosure = {
            "role": "downstream_local_reference_enclosure",
            "model": "rectangular_reference_enclosure_v1",
            "working_region_radius_mm": 3.6,
            "vacuum_z_min_mm": 0.0,
            "vacuum_z_max_mm": 95.2,
            "outer_half_width_mm": 7.6,
            "inner_half_width_mm": 7.2,
            "exit_enclosure_z_min_mm": 89.4,
            "exit_enclosure_z_max_mm": 95.2,
            "exit_front_wall_end_z_mm": 90.2,
            "detector_radius_mm": 3.6,
            "detector_thickness_mm": 0.4,
        }
        static_electrodes = {
            "role": "rectangular_reference_static_electrodes",
            "entrance_plate_and_connector": 0.0,
            "exit_enclosure_and_connector": 0.0,
            "detector": 0.0,
        }
    else:
        enclosure = {
            "role": "full_length_grounded_shield",
            "model": "cylindrical_grounded_shield_v1",
            "working_region_radius_mm": 3.6,
            "vacuum_z_min_mm": 2.0,
            "vacuum_z_max_mm": 89.0,
            "shield_inner_radius_mm": 20.0,
            "shield_outer_radius_mm": 21.0,
            "entrance_endcap_z_min_mm": 2.0,
            "entrance_endcap_z_max_mm": 2.5,
            "exit_endcap_z_min_mm": 88.5,
            "exit_endcap_z_max_mm": 89.0,
        }
        static_electrodes = {
            "role": "cylindrical_shield_static_electrodes",
            "shield_and_entrance_endcap_and_connector": 0.0,
            "exit_endcap_and_connector": 0.0,
        }
    return {
        "schema_version": 1,
        "role": "multipole_design_request",
        "request_id": f"{project_id}_baseline",
        "identity": identity(project_id),
        "units": {
            "length": "mm",
            "voltage": "V",
            "frequency": "Hz",
            "phase": "rad",
            "energy": "eV",
        },
        "coordinate": {
            "coordinate_id": "multipole.cartesian.z_axis.v1",
            "axial_axis": "+z",
            "orientation_rad": 0.125,
        },
        "geometry_mm": {
            "inscribed_radius_r0": 4.0,
            "rod_radius_ratio": 0.5,
            "rod_z_min": 5.0,
            "rod_z_max": 85.0,
            "enclosure": enclosure,
            "entrance_interface": {
                "aperture_radius_mm": 3.0,
                "plate_thickness_mm": 0.5,
                "rod_clearance_mm": 0.25,
                "connector_length_mm": 1.25,
                "connector_shape": "cylindrical_bore",
                "particle_plane_distance_mm": 0.75,
            },
            "exit_interface": {
                "aperture_radius_mm": 3.25,
                "plate_thickness_mm": 0.75,
                "rod_clearance_mm": 0.5,
                "connector_length_mm": 1.5,
                "connector_shape": "rectangular_bore",
                "particle_plane_distance_mm": 1.0,
            },
        },
        "drive": {
            "waveform": "cosine",
            "rf_amplitude_V_zero_to_peak_per_group": 139.81792,
            "dc_amplitude_V_per_group": 2.5,
            "common_mode_offset_V": -8.0,
            "frequency_Hz": 1_100_000.0,
            "phase_rad": 0.3,
        },
        "axial_drive": {
            "topology": (
                "none"
                if segmentation["strategy"] == "off"
                else "segmented_rod_axial_acceleration"
            )
        },
        "static_electrodes_V": static_electrodes,
        "particle_source": {
            "energy_model": {
                "kind": "monoenergetic",
                "kinetic_energy_eV": 2.0,
            },
            "charge_state": 1,
        },
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
    def compile(self, request: dict) -> dict:
        return compile_design_request(
            request,
            expected_identity=request["identity"],
        )

    def test_quadrupole_hexapole_and_octupole_identity_is_locked(self) -> None:
        for project_id, (_, electrode_count) in PROJECT_IDENTITIES.items():
            with self.subTest(project_id=project_id):
                request = design_request(project_id)
                resolved = self.compile(request)
                self.assertEqual(resolved["identity"], identity(project_id))
                rods = resolved["geometry_mm"]["rod_array"]["rods"]
                self.assertEqual(len(rods), electrode_count)
                self.assertEqual(
                    [rod["electrode_group"] for rod in rods],
                    [1, 2] * (electrode_count // 2),
                )
                validate_schema(resolved, "multipole_resolved_design.schema.json")

        request = design_request()
        mismatches = (
            {**identity(request["identity"]["project_id"]), "electrode_count": 6},
            {**identity(request["identity"]["project_id"]), "radial_order_n": 3},
            {**identity(request["identity"]["project_id"]), "project_id": "wrong_project"},
        )
        for expected in mismatches:
            with self.subTest(expected=expected):
                with self.assertRaises(MultipoleDesignCompileError):
                    compile_design_request(request, expected_identity=expected)

    def test_geometry_interfaces_connectors_and_drive_are_compiled_once(self) -> None:
        request = design_request()
        resolved = self.compile(request)
        geometry = resolved["geometry_mm"]
        self.assertEqual(geometry["rod_radius"], 2.0)
        self.assertEqual(geometry["rod_center_radius"], 6.0)
        self.assertEqual(geometry["rod_length"], 80.0)
        self.assertEqual(geometry["rod_z_min"], 5.0)
        self.assertEqual(geometry["rod_z_max"], 85.0)
        entrance = resolved["interfaces_mm"]["entrance"]
        exit_interface = resolved["interfaces_mm"]["exit"]
        self.assertEqual(
            (
                entrance["plate_z_min_mm"],
                entrance["plate_z_max_mm"],
                entrance["connector_z_min_mm"],
                entrance["particle_plane_z_mm"],
            ),
            (4.25, 4.75, 3.0, 2.25),
        )
        self.assertEqual(
            (
                exit_interface["plate_z_min_mm"],
                exit_interface["plate_z_max_mm"],
                exit_interface["connector_z_max_mm"],
                exit_interface["particle_plane_z_mm"],
            ),
            (85.5, 86.25, 87.75, 88.75),
        )
        self.assertEqual(entrance["connector_shape"], "cylindrical_bore")
        self.assertEqual(exit_interface["connector_shape"], "rectangular_bore")
        self.assertEqual(
            geometry["enclosure"]["model"],
            "rectangular_reference_enclosure_v1",
        )
        self.assertEqual(resolved["drive"], request["drive"])

    def test_derived_plane_accepts_roundoff_equality_but_rejects_real_escape(self) -> None:
        exact_boundary = design_request()
        entrance = exact_boundary["geometry_mm"]["entrance_interface"]
        entrance["rod_clearance_mm"] = 4.0
        entrance["plate_thickness_mm"] = 0.8
        entrance["connector_length_mm"] = 0.0
        entrance["particle_plane_distance_mm"] = 1.0
        exact_boundary["geometry_mm"]["rod_z_min"] = 5.8
        exact_boundary["geometry_mm"]["enclosure"]["vacuum_z_min_mm"] = 0.0
        resolved = self.compile(exact_boundary)
        self.assertAlmostEqual(
            resolved["interfaces_mm"]["entrance"]["particle_plane_z_mm"],
            0.0,
        )

        escaped = copy.deepcopy(exact_boundary)
        escaped["geometry_mm"]["entrance_interface"]["particle_plane_distance_mm"] = 1.000001
        with self.assertRaisesRegex(MultipoleDesignCompileError, "vacuum z range"):
            self.compile(escaped)

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
            [
                (item["z_min_mm"], item["z_max_mm"])
                for item in explicit["axial_acceleration"]["derived"]["segments"]
            ],
            [(5.0, 25.0), (26.0, 45.0), (45.0, 85.0)],
        )

    def test_endplate_topology_uses_continuous_rods_and_static_references(self) -> None:
        request = design_request()
        request["drive"]["common_mode_offset_V"] = 0.0
        request["axial_drive"]["topology"] = "endplate_potential_step"
        request["static_electrodes_V"]["exit_enclosure_and_connector"] = -3.0
        request["static_electrodes_V"]["detector"] = -3.0
        resolved = self.compile(request)
        self.assertEqual(resolved["segmentation"]["strategy"], "off")
        self.assertIsNone(resolved["segmentation"]["segmented_rod_array"])
        self.assertEqual(
            resolved["axial_drive"],
            {
                "topology": "endplate_potential_step",
                "source_reference_V": 0.0,
                "output_reference_V": -3.0,
                "predicted_energy_gain_eV": 3.0,
                "predicted_output_energy_eV": 5.0,
            },
        )

        mismatched = copy.deepcopy(request)
        mismatched["segmentation"] = {
            "strategy": "uniform",
            "segment_count": 2,
            "intersegment_gap_mm": 0.0,
            "entrance_common_mode_V": 0.0,
            "exit_common_mode_V": -3.0,
            "output_reference_V": -3.0,
        }
        with self.assertRaisesRegex(
            MultipoleDesignCompileError, "continuous rods"
        ):
            self.compile(mismatched)

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
        with self.assertRaisesRegex(
            MultipoleDesignCompileError, "minimum energy exceeds"
        ):
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

    def test_unknown_units_nonfinite_and_negative_values_are_rejected(self) -> None:
        mutations = []
        unknown = design_request()
        unknown["geometry_mm"]["second_radius"] = 4.0
        mutations.append(unknown)
        units = design_request()
        units["units"]["length"] = "m"
        mutations.append(units)
        nonfinite = design_request()
        nonfinite["drive"]["phase_rad"] = float("nan")
        mutations.append(nonfinite)
        negative = design_request()
        negative["geometry_mm"]["rod_radius_ratio"] = -0.5
        mutations.append(negative)
        reversed_span = design_request()
        reversed_span["geometry_mm"]["rod_z_max"] = 4.0
        mutations.append(reversed_span)
        invalid_connector = design_request()
        invalid_connector["geometry_mm"]["entrance_interface"]["connector_shape"] = "cylindrical_annulus"
        mutations.append(invalid_connector)
        invalid_enclosure = design_request()
        invalid_enclosure["geometry_mm"]["enclosure"]["inner_half_width_mm"] = 8.0
        mutations.append(invalid_enclosure)
        for request in mutations:
            with self.subTest(request=request):
                with self.assertRaises(MultipoleDesignCompileError):
                    self.compile(request)

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
            expected = identity("rf_quadrupole_collision_cooling")
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

    def test_governed_bounds_hash_unit_and_portable_provenance(self) -> None:
        request = design_request(segmentation={"strategy": "off"})
        catalog = multipole_catalog(request["identity"]["project_id"], "unused")
        catalog["variables"][0].update(
            variable_id="rf_amplitude",
            label="RF amplitude",
            optimization_role="drive",
            json_pointer="/drive/rf_amplitude_V_zero_to_peak_per_group",
            unit="V",
            minimum=10.0,
            maximum=500.0,
        )
        request["drive"]["rf_amplitude_V_zero_to_peak_per_group"] = 500.0
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "provenance"
            root.mkdir()
            request_path = root / "request.json"
            catalog_path = root / "catalog.json"
            envelope_path = root / "envelope.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

            def write_envelope(request_hash: str) -> None:
                envelope = {
                    "schema_version": 1,
                    "role": "project_optimization_envelope",
                    "project_id": request["identity"]["project_id"],
                    "family_id": "rf_multipole_ion_optics",
                    "envelope_id": "governed_fixture",
                    "status": "candidate",
                    "policy": "Exact governed fixture.",
                    "reference": {
                        "design_request": "request.json",
                        "design_request_sha256": request_hash,
                    },
                    "constraints": [{
                        "constraint_id": "bounded_drive",
                        "kind": "bounded_variable",
                        "request_json_pointers": [
                            "/drive/rf_amplitude_V_zero_to_peak_per_group"
                        ],
                        "description": "RF remains inside catalog bounds.",
                    }],
                }
                envelope_path.write_text(json.dumps(envelope), encoding="utf-8")

            write_envelope(file_sha256(request_path))
            resolved = compile_governed_design_request_file(
                request_path,
                catalog_path,
                envelope_path,
                expected_identity=request["identity"],
                provenance_root=root,
            )
            self.assertEqual(
                [source["path"] for source in resolved["sources"]],
                ["request.json", "catalog.json", "envelope.json"],
            )
            self.assertFalse(any(":" in item["path"] for item in resolved["sources"]))

            outside = base / "outside-request.json"
            outside.write_text(json.dumps(request), encoding="utf-8")
            write_envelope(file_sha256(outside))
            with self.assertRaisesRegex(MultipoleDesignCompileError, "escapes"):
                compile_governed_design_request_file(
                    outside,
                    catalog_path,
                    envelope_path,
                    expected_identity=request["identity"],
                    provenance_root=root,
                )

            request["drive"]["rf_amplitude_V_zero_to_peak_per_group"] = 500.000001
            request_path.write_text(json.dumps(request), encoding="utf-8")
            write_envelope(file_sha256(request_path))
            with self.assertRaisesRegex(MultipoleDesignCompileError, "outside catalog bounds"):
                compile_governed_design_request_file(
                    request_path,
                    catalog_path,
                    envelope_path,
                    expected_identity=request["identity"],
                    provenance_root=root,
                )

            request["drive"]["rf_amplitude_V_zero_to_peak_per_group"] = 500.0
            request_path.write_text(json.dumps(request), encoding="utf-8")
            write_envelope("0" * 64)
            with self.assertRaisesRegex(MultipoleDesignCompileError, "hash is stale"):
                compile_governed_design_request_file(
                    request_path,
                    catalog_path,
                    envelope_path,
                    expected_identity=request["identity"],
                    provenance_root=root,
                )

            bad_catalog = copy.deepcopy(catalog)
            bad_catalog["variables"][0]["unit"] = "Hz"
            catalog_path.write_text(json.dumps(bad_catalog), encoding="utf-8")
            write_envelope(file_sha256(request_path))
            with self.assertRaisesRegex(MultipoleDesignCompileError, "unit differs"):
                compile_governed_design_request_file(
                    request_path,
                    catalog_path,
                    envelope_path,
                    expected_identity=request["identity"],
                    provenance_root=root,
                )
            missing_catalog = copy.deepcopy(catalog)
            missing_catalog["variables"][0]["json_pointer"] = "/drive/missing"
            catalog_path.write_text(json.dumps(missing_catalog), encoding="utf-8")
            with self.assertRaisesRegex(MultipoleDesignCompileError, "pointer is missing"):
                compile_governed_design_request_file(
                    request_path,
                    catalog_path,
                    envelope_path,
                    expected_identity=request["identity"],
                    provenance_root=root,
                )

    def test_frozen_resolved_design_rejects_hash_or_identity_drift(self) -> None:
        request = design_request()
        with tempfile.TemporaryDirectory() as directory:
            request_path = Path(directory) / "request.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            resolved = compile_design_request_file(
                request_path,
                expected_identity=request["identity"],
                source_root=Path(directory),
            )
            self.assertEqual(
                validate_resolved_design(
                    resolved,
                    request_path=request_path,
                    source_root=Path(directory),
                    expected_identity=request["identity"],
                ),
                resolved,
            )
            drifted = copy.deepcopy(resolved)
            drifted["drive"]["phase_rad"] = 1.0
            drifted["resolved_sha256"] = resolved_design_sha256(drifted)
            with self.assertRaisesRegex(MultipoleDesignCompileError, "recompilation"):
                validate_resolved_design(
                    drifted,
                    request_path=request_path,
                    source_root=Path(directory),
                    expected_identity=request["identity"],
                )
            wrong_identity = {**request["identity"], "project_id": "wrong_project"}
            with self.assertRaises(MultipoleDesignCompileError):
                validate_resolved_design(
                    resolved,
                    request_path=request_path,
                    source_root=Path(directory),
                    expected_identity=wrong_identity,
                )

    def test_axial_semantics_reject_length_and_voltage_mismatches(self) -> None:
        bad_length = design_request(
            segmentation={
                "strategy": "explicit",
                "segments": [
                    {"length_mm": 20.0, "common_mode_V": 0.0},
                    {"length_mm": 20.0, "common_mode_V": -3.0},
                ],
                "output_reference_V": -3.0,
            }
        )
        bad_output = design_request(
            segmentation={
                "strategy": "uniform",
                "segment_count": 4,
                "intersegment_gap_mm": 0.0,
                "entrance_common_mode_V": 0.0,
                "exit_common_mode_V": -3.0,
                "output_reference_V": -2.0,
            }
        )
        for request in (bad_length, bad_output):
            with self.assertRaises(Exception):
                self.compile(request)


class MultipoleGovernanceSchemaTest(unittest.TestCase):
    def test_existing_oatof_catalog_and_envelope_remain_valid(self) -> None:
        validate_schema(
            json.loads(
                (REPO_ROOT / "projects/oa_tof/config/design_variables.json").read_text(
                    encoding="utf-8"
                )
            ),
            "design_variable_catalog.schema.json",
        )
        validate_schema(
            json.loads(
                (REPO_ROOT / "projects/oa_tof/config/optimization_envelope.json").read_text(
                    encoding="utf-8"
                )
            ),
            "optimization_envelope.schema.json",
        )

    def test_registry_validates_quadrupole_hexapole_and_octupole_fixtures(self) -> None:
        for project_id in PROJECT_IDENTITIES:
            with self.subTest(project_id=project_id), tempfile.TemporaryDirectory() as directory:
                repo_root = Path(directory)
                project_root = repo_root / "projects" / project_id
                config = project_root / "config"
                requests = config / "requests"
                requests.mkdir(parents=True)
                request_relative = "config/requests/baseline.json"
                request_path = project_root / request_relative
                request_path.write_text(
                    json.dumps(design_request(project_id), indent=2) + "\n",
                    encoding="utf-8",
                )
                baseline = {
                    "multipole": {
                        "radial_order_n": identity(project_id)["radial_order_n"],
                        "electrode_count": identity(project_id)["electrode_count"],
                    }
                }
                (config / "baseline.json").write_text(
                    json.dumps(baseline) + "\n",
                    encoding="utf-8",
                )
                catalog = multipole_catalog(project_id, request_relative)
                (config / "design_variables.json").write_text(
                    json.dumps(catalog, indent=2) + "\n",
                    encoding="utf-8",
                )
                envelope = {
                    "schema_version": 1,
                    "role": "project_optimization_envelope",
                    "project_id": project_id,
                    "family_id": "rf_multipole_ion_optics",
                    "envelope_id": f"{project_id}_candidate",
                    "status": "candidate",
                    "policy": "Candidates remain inside compiled request bounds.",
                    "reference": {
                        "design_request": request_relative,
                        "design_request_sha256": file_sha256(request_path),
                    },
                    "constraints": [
                        {
                            "constraint_id": "identity_lock",
                            "kind": "immutable_identity",
                            "request_json_pointers": [
                                "/identity/radial_order_n",
                                "/identity/electrode_count",
                            ],
                            "description": "Pole count and radial order are immutable project identity.",
                        }
                    ],
                }
                (config / "optimization_envelope.json").write_text(
                    json.dumps(envelope, indent=2) + "\n",
                    encoding="utf-8",
                )
                descriptor = {
                    "schema_version": 1,
                    "project_id": project_id,
                    "family_id": "rf_multipole_ion_optics",
                    "display_name": project_id,
                    "purpose": "registry fixture",
                    "lifecycle_status": "static",
                    "toolchains": ["python"],
                    "contracts": {
                        "baseline": "config/baseline.json",
                        "resolved": None,
                        "analysis": None,
                        "interface": None,
                        "execution": None,
                        "design_variables": "config/design_variables.json",
                        "optimization_envelope": "config/optimization_envelope.json",
                    },
                    "capabilities": [
                        {
                            "capability_id": "multipole_fixture",
                            "function": "ion_transport",
                            "status": "static",
                            "modes": [],
                            "metrics": [],
                            "design_variables": ["r0"],
                        }
                    ],
                    "formal_assets": {
                        "status": "none",
                        "types": [],
                        "identity_contract": None,
                    },
                    "known_gaps": [],
                }
                descriptor_path = config / "project.json"
                validate_descriptor(descriptor, descriptor_path, repo_root)

    def test_multipole_governance_schemas_reject_unknown_fields(self) -> None:
        request = design_request()
        catalog = multipole_catalog(
            "rf_quadrupole_collision_cooling",
            "config/requests/baseline.json",
        )
        validate_schema(catalog, "design_variable_catalog.schema.json")
        envelope = {
            "schema_version": 1,
            "role": "project_optimization_envelope",
            "project_id": "rf_quadrupole_collision_cooling",
            "family_id": "rf_multipole_ion_optics",
            "envelope_id": "quadrupole_candidate",
            "status": "candidate",
            "policy": "Candidate compilation bounds.",
            "reference": {
                "design_request": "config/requests/baseline.json",
                "design_request_sha256": "0" * 64,
            },
            "constraints": [
                {
                    "constraint_id": "identity_lock",
                    "kind": "immutable_identity",
                    "request_json_pointers": ["/identity/electrode_count"],
                    "description": "Immutable pole count.",
                }
            ],
        }
        validate_schema(request, "multipole_design_request.schema.json")
        validate_schema(envelope, "optimization_envelope.schema.json")
        invalid_catalog = copy.deepcopy(catalog)
        invalid_catalog["variables"][0]["second_unit"] = "cm"
        with self.assertRaises(ContractError):
            validate_schema(invalid_catalog, "design_variable_catalog.schema.json")
        invalid_envelope = copy.deepcopy(envelope)
        invalid_envelope["tof_limits"] = {}
        with self.assertRaises(ContractError):
            validate_schema(invalid_envelope, "optimization_envelope.schema.json")


if __name__ == "__main__":
    unittest.main()
