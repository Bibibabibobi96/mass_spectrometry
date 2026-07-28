from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import file_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from common.multipole.compile_design_request import (
    MultipoleDesignCompileError,
    apply_typed_operating_mode,
    compile_governed_design_request_file,
    validate_resolved_design,
)
from common.multipole.design_profile import resolve_design_profile
from common.multipole.test_compile_design_request import (
    design_request,
    multipole_catalog,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "rf_hexapole_ion_optics"


def operating_modes() -> dict:
    return {
        "schema_version": 1,
        "role": "multipole_typed_operating_mode_registry",
        "project_id": PROJECT_ID,
        "family_id": "rf_multipole_ion_optics",
        "modes": [
            {
                "mode_id": "none",
                "axial_drive_topology": "none",
                "rod_segment_entrance_common_mode_V": 0.0,
                "rod_segment_exit_common_mode_V": 0.0,
                "exit_aperture_plate_and_connector_V": 0.0,
            },
            {
                "mode_id": "exit_plate",
                "axial_drive_topology": "exit_aperture_plate_potential_step",
                "rod_segment_entrance_common_mode_V": 0.0,
                "rod_segment_exit_common_mode_V": 0.0,
                "exit_aperture_plate_and_connector_V": -3.0,
            },
            {
                "mode_id": "segmented",
                "axial_drive_topology": "segmented_rod_axial_acceleration",
                "rod_segment_entrance_common_mode_V": 0.0,
                "rod_segment_exit_common_mode_V": -3.0,
                "exit_aperture_plate_and_connector_V": -3.0,
            },
        ],
    }


class TypedOperatingModeTests(unittest.TestCase):
    def build_repository(self, root: Path) -> tuple[Path, dict]:
        project_root = root / "projects" / PROJECT_ID
        config = project_root / "config"
        requests = config / "requests"
        requests.mkdir(parents=True)
        (root / "config").mkdir()
        descriptor = json.loads(
            (
                REPO_ROOT / "projects" / PROJECT_ID / "config" / "project.json"
            ).read_text(encoding="utf-8")
        )
        (config / "project.json").write_text(
            json.dumps(descriptor), encoding="utf-8"
        )
        (root / "config" / "project_registry.json").write_text(
            json.dumps(
                {
                    "projects": [
                        {
                            "project_id": PROJECT_ID,
                            "family_id": "rf_multipole_ion_optics",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        base = json.loads(
            (
                REPO_ROOT
                / "projects"
                / PROJECT_ID
                / "config"
                / "requests"
                / "baseline.json"
            ).read_text(encoding="utf-8")
        )
        base_path = requests / "mechanical_base.json"
        catalog_path = config / "design_variables.json"
        envelope_path = config / "optimization_envelope.json"
        modes_path = config / "operating_modes.json"
        base_path.write_text(json.dumps(base), encoding="utf-8")
        catalog = multipole_catalog(
            PROJECT_ID,
            "config/requests/mechanical_base.json",
        )
        voltage_variables = (
            ("segment_entrance_v", "/segmentation/entrance_common_mode_V"),
            ("segment_exit_v", "/segmentation/exit_common_mode_V"),
            (
                "exit_interface_v",
                "/static_electrodes_V/exit_outer_endcap_aperture_plate_connector_V",
            ),
        )
        for variable_id, pointer in voltage_variables:
            variable = copy.deepcopy(catalog["variables"][0])
            variable.update(
                {
                    "variable_id": variable_id,
                    "label": variable_id,
                    "json_pointer": pointer,
                    "unit": "V",
                    "minimum": -10.0,
                    "maximum": 10.0,
                }
            )
            catalog["variables"].append(variable)
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        envelope_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "role": "project_optimization_envelope",
                    "project_id": PROJECT_ID,
                    "family_id": "rf_multipole_ion_optics",
                    "envelope_id": "mechanical_base",
                    "status": "candidate",
                    "policy": "The mechanical baseline is governed once.",
                    "reference": {
                        "design_request": "config/requests/mechanical_base.json",
                        "design_request_sha256": file_sha256(base_path),
                    },
                    "constraints": [
                        {
                            "constraint_id": "r0_bound",
                            "kind": "bounded_variable",
                            "request_json_pointers": [
                                variable["json_pointer"]
                                for variable in catalog["variables"]
                            ],
                            "description": "Keep r0 inside the governed catalog.",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        modes_path.write_text(json.dumps(operating_modes()), encoding="utf-8")
        common_hashes = {
            "design_request": file_sha256(base_path),
            "design_variables": file_sha256(catalog_path),
            "optimization_envelope": file_sha256(envelope_path),
        }
        profiles = {
            "schema_version": 2,
            "role": "multipole_design_profile_registry",
            "project_id": PROJECT_ID,
            "family_id": "rf_multipole_ion_optics",
            "operating_mode_registry": "config/operating_modes.json",
            "operating_mode_registry_sha256": file_sha256(modes_path),
            "profiles": [
                {
                    "design_profile_id": f"{mode['mode_id']}_profile",
                    "mode_id": mode["mode_id"],
                    "design_request": "config/requests/mechanical_base.json",
                    "design_variables": "config/design_variables.json",
                    "optimization_envelope": "config/optimization_envelope.json",
                    "sha256": copy.deepcopy(common_hashes),
                    "identity": copy.deepcopy(base["identity"]),
                    "topology": {
                        "enclosure_role": "full_length_grounded_shield",
                        "segmentation_strategy": "uniform",
                        "axial_drive_topology": mode["axial_drive_topology"],
                    },
                }
                for mode in operating_modes()["modes"]
            ],
        }
        validate_schema(profiles, "design_profiles.schema.json")
        (config / "design_profiles.json").write_text(
            json.dumps(profiles), encoding="utf-8"
        )
        return base_path, profiles

    def test_three_profiles_share_one_governed_mechanical_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base_path, profiles = self.build_repository(root)
            self.assertEqual(
                {profile["design_request"] for profile in profiles["profiles"]},
                {"config/requests/mechanical_base.json"},
            )
            self.assertEqual(
                {
                    profile["sha256"]["design_request"]
                    for profile in profiles["profiles"]
                },
                {file_sha256(base_path)},
            )
            resolved = {
                mode: resolve_design_profile(
                    root,
                    PROJECT_ID,
                    f"{mode}_profile",
                )["resolved_design"]
                for mode in ("none", "exit_plate", "segmented")
            }
            modes_sha256 = profiles["operating_mode_registry_sha256"]
            self.assertEqual(
                [item["geometry_mm"] for item in resolved.values()],
                [resolved["none"]["geometry_mm"]] * 3,
            )
            self.assertEqual(
                [item["interfaces_mm"] for item in resolved.values()],
                [resolved["none"]["interfaces_mm"]] * 3,
            )
            physical_segments = []
            for item in resolved.values():
                physical_segments.append(
                    [
                        {
                            key: value
                            for key, value in electrode.items()
                            if key != "common_mode_V"
                        }
                        for electrode in item["segmentation"][
                            "segmented_rod_array"
                        ]["electrodes"]
                    ]
                )
                self.assertEqual(item["drive"], resolved["none"]["drive"])
                self.assertEqual(
                    item["particle_source"],
                    resolved["none"]["particle_source"],
                )
                self.assertTrue(
                    any(
                        source["label"].startswith("operating_mode_registry__")
                        and source["sha256"] == modes_sha256
                        and source["path"].endswith(
                            "config/operating_modes.json"
                        )
                        for source in item["sources"]
                    )
                )
                self.assertTrue(
                    any(
                        source["label"] == "design_request"
                        and source["sha256"] == file_sha256(base_path)
                        for source in item["sources"]
                    )
                )
                validate_resolved_design(
                    item,
                    request_path=base_path,
                    source_root=root,
                    expected_identity=item["identity"],
                )
            self.assertEqual(physical_segments[0], physical_segments[1])
            self.assertEqual(physical_segments[1], physical_segments[2])
            for segment in resolved["segmented"]["segmentation"][
                "axial_acceleration"
            ]["derived"]["segments"]:
                self.assertAlmostEqual(
                    segment["z_max_mm"] - segment["z_min_mm"],
                    19.6,
                )
            self.assertEqual(
                [
                    segment["common_mode_V"]
                    for segment in resolved["segmented"]["segmentation"][
                        "axial_acceleration"
                    ]["derived"]["segments"]
                ],
                [0.0, -1.0, -2.0, -3.0],
            )
            for mode in ("none", "exit_plate"):
                self.assertEqual(
                    [
                        segment["common_mode_V"]
                        for segment in resolved[mode]["segmentation"][
                            "axial_acceleration"
                        ]["derived"]["segments"]
                    ],
                    [0.0, 0.0, 0.0, 0.0],
                )

    def test_mode_vocabulary_rejects_unknown_and_geometry_fields(self) -> None:
        base = design_request(
            PROJECT_ID,
            segmentation={
                "strategy": "uniform",
                "segment_count": 4,
                "intersegment_gap_mm": 0.4,
                "entrance_common_mode_V": 0.0,
                "exit_common_mode_V": 0.0,
                "output_reference_V": 0.0,
            },
        )
        invalid = operating_modes()
        invalid["modes"][0]["geometry_mm"] = {"rod_z_max": 100.0}
        with self.assertRaises(MultipoleDesignCompileError):
            apply_typed_operating_mode(base, invalid, "none")
        with self.assertRaisesRegex(
            MultipoleDesignCompileError,
            "not unique",
        ):
            apply_typed_operating_mode(base, operating_modes(), "unknown")
        profiles = {
            "schema_version": 2,
            "role": "multipole_design_profile_registry",
            "project_id": PROJECT_ID,
            "family_id": "rf_multipole_ion_optics",
            "profiles": [],
            "geometry_override": {},
        }
        with self.assertRaises(ContractError):
            validate_schema(profiles, "design_profiles.schema.json")

    def test_mode_voltage_cannot_bypass_governed_catalog_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base_path, _ = self.build_repository(root)
            config = root / "projects" / PROJECT_ID / "config"
            invalid_modes = operating_modes()
            invalid_modes["modes"][2][
                "rod_segment_exit_common_mode_V"
            ] = -100.0
            invalid_path = config / "invalid_operating_modes.json"
            invalid_path.write_text(json.dumps(invalid_modes), encoding="utf-8")
            with self.assertRaisesRegex(
                MultipoleDesignCompileError,
                "outside catalog bounds",
            ):
                compile_governed_design_request_file(
                    base_path,
                    config / "design_variables.json",
                    config / "optimization_envelope.json",
                    expected_identity=design_request(PROJECT_ID)["identity"],
                    provenance_root=root,
                    operating_mode_registry_path=invalid_path,
                    mode_id="segmented",
                )


if __name__ == "__main__":
    unittest.main()
