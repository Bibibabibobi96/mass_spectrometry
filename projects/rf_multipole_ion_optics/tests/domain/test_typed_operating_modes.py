from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from common.contracts.file_identity import repository_text_sha256
from common.contracts.machine_contracts import ContractError, validate_schema
from projects.rf_multipole_ion_optics.core.compile_design_request import (
    MultipoleDesignCompileError,
    apply_typed_operating_mode,
    compile_governed_design_request_file,
    validate_resolved_design,
)
from projects.rf_multipole_ion_optics.runtime.design_profile import resolve_design_profile
from projects.rf_multipole_ion_optics.tests.domain.test_compile_design_request import (
    design_request,
    multipole_catalog,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_ID = "rf_multipole_ion_optics"


def operating_modes() -> dict:
    return {
        "schema_version":2,"role":"multipole_typed_operating_mode_registry",
        "project_id":PROJECT_ID,"family_id":PROJECT_ID,"terminal_reference_V":0.,
        "modes":[
            {"mode_id":"none","axial_drive_topology":"none","rod_entrance_relative_to_terminal_V":0.,"rod_exit_relative_to_terminal_V":0.},
            {"mode_id":"segmented","axial_drive_topology":"segmented_rod_axial_acceleration","rod_entrance_relative_to_terminal_V":3.,"rod_exit_relative_to_terminal_V":0.},
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
        descriptor["structural_variants"] = [
            row for row in descriptor["structural_variants"] if row["variant_id"] == "hexapole"
        ]
        capability_ids = set(descriptor["structural_variants"][0]["capability_ids"])
        descriptor["capabilities"] = [row for row in descriptor["capabilities"] if row["capability_id"] in capability_ids]
        family = json.loads((REPO_ROOT / "projects" / PROJECT_ID / "config/contracts/family_contract.json").read_text(encoding="utf-8"))
        family["structural_variants"] = {"hexapole": family["structural_variants"]["hexapole"]}
        (config / "contracts").mkdir()
        (config / "contracts/family_contract.json").write_text(json.dumps(family), encoding="utf-8")
        shutil.copyfile(
            REPO_ROOT / "projects" / PROJECT_ID / "config/contracts/design_profiles.schema.json",
            config / "contracts/design_profiles.schema.json",
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
                / "variants"
                / "hexapole"
                / "config"
                / "requests"
                / "baseline.json"
            ).read_text(encoding="utf-8")
        )
        base_path = requests / "mechanical_base.json"
        catalog_path = config / "design_variables.json"
        envelope_path = config / "optimization_envelope.json"
        modes_path = config / "operating_modes.json"
        base_path.write_text(
            json.dumps(base, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        catalog = multipole_catalog(
            PROJECT_ID,
            "config/requests/mechanical_base.json",
        )
        voltage_variables = (
            ("segment_entrance_v", "/segmentation/entrance_common_mode_V"),
            ("segment_exit_v", "/segmentation/exit_common_mode_V"),
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
        catalog_path.write_text(
            json.dumps(catalog, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
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
                        "design_request_sha256": repository_text_sha256(base_path),
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
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        modes_path.write_text(
            json.dumps(operating_modes(), indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        common_hashes = {
            "design_request": repository_text_sha256(base_path),
            "design_variables": repository_text_sha256(catalog_path),
            "optimization_envelope": repository_text_sha256(envelope_path),
        }
        profiles = {
            "schema_version": 3,
            "role": "project_design_profile_registry",
            "project_id": PROJECT_ID,
            "family_id": "rf_multipole_ion_optics",
            "operating_mode_registry": "config/operating_modes.json",
            "operating_mode_registry_sha256": repository_text_sha256(modes_path),
            "profiles": [
                {
                    "design_profile_id": f"{mode['mode_id']}_profile",
                    "structural_variant_id": "hexapole",
                    "mode_id": mode["mode_id"],
                    "design_request": "config/requests/mechanical_base.json",
                    "design_variables": "config/design_variables.json",
                    "optimization_envelope": "config/optimization_envelope.json",
                    "sha256": copy.deepcopy(common_hashes),
                    "identity": copy.deepcopy(base["identity"]),
                    "topology": {
                        "enclosure_model": "bare",
                        "segmentation_strategy": "uniform",
                        "axial_drive_topology": mode["axial_drive_topology"],
                    },
                }
                for mode in operating_modes()["modes"]
            ],
        }
        for profile in profiles["profiles"]:
            profile["project_options"] = {"topology": profile.pop("topology")}
        validate_schema(profiles, "design_profiles.schema.json")
        (config / "design_profiles.json").write_text(
            json.dumps(profiles), encoding="utf-8"
        )
        return base_path, profiles

    def test_profile_resolution_accepts_crlf_repository_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.build_repository(root)
            config = root / "projects" / PROJECT_ID / "config"
            source_paths = (
                config / "requests" / "mechanical_base.json",
                config / "design_variables.json",
                config / "optimization_envelope.json",
                config / "operating_modes.json",
            )
            for path in source_paths:
                path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
            resolved = resolve_design_profile(
                root,
                PROJECT_ID,
                "segmented_profile",
            )["resolved_design"]
            source_hashes = {
                source["sha256"] for source in resolved["sources"]
            }
            self.assertEqual(
                source_hashes,
                {repository_text_sha256(path) for path in source_paths},
            )

    def test_two_rod_modes_share_one_governed_mechanical_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            base_path,profiles=self.build_repository(root)
            self.assertEqual({p["design_request"] for p in profiles["profiles"]},{"config/requests/mechanical_base.json"})
            self.assertEqual({p["sha256"]["design_request"] for p in profiles["profiles"]},{repository_text_sha256(base_path)})
            resolved={mode:resolve_design_profile(root,PROJECT_ID,mode+"_profile")["resolved_design"] for mode in ("none","segmented")}
            first=resolved["none"]
            for mode,item in resolved.items():
                self.assertEqual(item["geometry_mm"],first["geometry_mm"])
                self.assertNotIn("interfaces_mm",item)
                self.assertEqual(item["geometry_mm"]["enclosure"],{"model":"bare"})
                self.assertEqual(item["static_electrodes_V"],{"role":"bare_multipole_static_electrodes"})
                self.assertEqual(item["particle_source"],first["particle_source"])
                self.assertEqual({k:v for k,v in item["drive"].items() if k!="common_mode_offset_V"},{k:v for k,v in first["drive"].items() if k!="common_mode_offset_V"})
                segments=item["segmentation"]["axial_acceleration"]["derived"]["segments"]
                self.assertEqual([segment["common_mode_V"] for segment in segments],[0.,0.,0.,0.] if mode=="none" else [3.,2.,1.,0.])
                self.assertTrue(all(abs(segment["z_max_mm"]-segment["z_min_mm"]-19.6)<1e-12 for segment in segments))
                self.assertTrue(any(source["label"].startswith("operating_mode_registry__") and source["sha256"]==profiles["operating_mode_registry_sha256"] for source in item["sources"]))
                validate_resolved_design(item,request_path=base_path,source_root=root,expected_identity=item["identity"],repository_text_sources=True)
            def physical_segments(value):
                return [{k:v for k,v in row.items() if k!="common_mode_V"} for row in value["segmentation"]["segmented_rod_array"]["electrodes"]]
            self.assertEqual(physical_segments(first),physical_segments(resolved["segmented"]))

    def test_mode_vocabulary_rejects_unknown_and_geometry_fields(self) -> None:
        base = design_request("hexapole",
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
            "schema_version": 3,
            "role": "project_design_profile_registry",
            "project_id": PROJECT_ID,
            "family_id": "rf_multipole_ion_optics",
            "profiles": [],
            "geometry_override": {},
        }
        with self.assertRaises(ContractError):
            validate_schema(profiles, "design_profiles.schema.json")

    def test_legacy_registry_and_typed_exit_plate_are_rejected(self) -> None:
        base = design_request("hexapole",segmentation={
            "strategy":"uniform","segment_count":4,"intersegment_gap_mm":.4,
            "entrance_common_mode_V":0.,"exit_common_mode_V":0.,"output_reference_V":0.,
        })
        legacy = {
            "schema_version":1,"role":"multipole_typed_operating_mode_registry",
            "project_id":PROJECT_ID,"family_id":PROJECT_ID,
            "modes":[{"mode_id":"none","axial_drive_topology":"none",
                "rod_segment_entrance_common_mode_V":0.,"rod_segment_exit_common_mode_V":0.,
                "exit_aperture_plate_and_connector_V":0.}],
        }
        exit_plate = operating_modes()
        exit_plate["modes"][0].update(axial_drive_topology="exit_aperture_plate_potential_step",
            rod_entrance_relative_to_terminal_V=3.,rod_exit_relative_to_terminal_V=3.)
        for registry in (legacy,exit_plate):
            with self.subTest(version=registry["schema_version"]):
                with self.assertRaises(ContractError):
                    validate_schema(registry,"multipole_operating_modes.schema.json")
                with self.assertRaises(MultipoleDesignCompileError):
                    apply_typed_operating_mode(base,registry,"none")

    def test_mode_voltage_cannot_bypass_governed_catalog_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base_path, _ = self.build_repository(root)
            config = root / "projects" / PROJECT_ID / "config"
            invalid_modes = operating_modes()
            invalid_modes["modes"][1]["rod_entrance_relative_to_terminal_V"] = 100.0
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
                    expected_identity=design_request("hexapole")["identity"],
                    provenance_root=root,
                    operating_mode_registry_path=invalid_path,
                    mode_id="segmented",
                )


if __name__ == "__main__":
    unittest.main()
