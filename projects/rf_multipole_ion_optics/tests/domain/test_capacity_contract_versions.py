"""Public author compilation separates legacy limits from neutral capacity."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from msplatform.contracts.machine_contracts import ContractError
from projects.rf_multipole_ion_optics.core.compile_design_request import (
    compile_design_request, compile_design_request_file, compile_governed_design_request_file,
    validate_design_request, validate_resolved_design, validate_resolved_design_contract,
)
from projects.rf_multipole_ion_optics.core.electrode_topology import build_electrode_topology
from msplatform.backends.simion.rf_electrode_mapping import build_simion_electrode_map
from projects.rf_multipole_ion_optics.simion.simion_geometry import render_physical_gem
from projects.rf_multipole_ion_optics.tests.domain.test_compile_design_request import design_request, multipole_catalog


def request(version=4, count=501, *, explicit=False):
    value = design_request()
    value["schema_version"] = version
    value["axial_drive"]["topology"] = "none"
    value["segmentation"] = dict(strategy="uniform", segment_count=count, intersegment_gap_mm=0.,
                                 entrance_common_mode_V=-8., exit_common_mode_V=-8., output_reference_V=-8.)
    if explicit:
        value["segmentation"] = dict(strategy="explicit", output_reference_V=-8.,
            segments=[dict(length_mm=80./count, common_mode_V=-8.) for _ in range(count)])
    return value


class CapacityContractVersionTests(unittest.TestCase):
    def test_public_compiler_500_501_neutral_oracle_and_native_capacity(self):
        for count in (500, 501):
            for explicit in (False, True):
                with self.subTest(count=count, explicit=explicit):
                    author = request(count=count, explicit=explicit)
                    result = compile_design_request(author, expected_identity=author["identity"])
                    validate_resolved_design_contract(result)
                    self.assertEqual((result["schema_version"], result["compiler"]["version"]), (4, 4))
                    axial = result["segmentation"]["axial_acceleration"]
                    self.assertEqual((axial["schema_version"], axial["model_id"]),
                                     (3, "multipole.segmented_rod_common_mode_staircase.v3"))
                    table = result["segmentation"]["segmented_rod_array"]
                    self.assertEqual(table["schema_version"], 2)
                    self.assertEqual(len(table["electrodes"]), 4*count)
                    self.assertFalse(any("electrode_id" in member for member in table["electrodes"]))
                    segments = axial["derived"]["segments"]
                    self.assertAlmostEqual(sum(s["z_max_mm"]-s["z_min_mm"] for s in segments), 80.)
                    self.assertAlmostEqual(segments[0]["z_min_mm"], 5.)
                    self.assertAlmostEqual(segments[-1]["z_max_mm"], 85.)
                    self.assertEqual({s["common_mode_V"] for s in segments}, {-8.})
                    self.assertEqual(result["drive"], author["drive"])
                    self.assertEqual(result["particle_source"], author["particle_source"])
                    topology = build_electrode_topology(result)
                    self.assertEqual(len(topology), 2*count)
                    if count == 500:
                        mapping = build_simion_electrode_map(result, topology)
                        self.assertEqual(set(mapping.values()), set(range(1, 1001)))
                    else:
                        with self.assertRaisesRegex(ValueError, "capacity"):
                            build_simion_electrode_map(result, topology)

    def test_legacy_still_rejects_500_but_keeps_original_small_native_contract(self):
        for explicit in (False, True):
            author = request(3, 500, explicit=explicit)
            with self.assertRaises(ContractError):
                compile_design_request(author, expected_identity=author["identity"])
        author = request(3, 2)
        result = compile_design_request(author, expected_identity=author["identity"])
        self.assertEqual(result["compiler"]["version"], 3)
        self.assertEqual(result["segmentation"]["axial_acceleration"]["schema_version"], 2)
        self.assertEqual({m["electrode_id"] for m in result["segmentation"]["segmented_rod_array"]["electrodes"]}, {1,2,3,4})

    def test_unknown_and_mixed_versions_are_rejected(self):
        for version in (True, 2, 5, "4"):
            author = request(); author["schema_version"] = version
            with self.subTest(version=version), self.assertRaises(ContractError):
                validate_design_request(author)
        author = request(count=2)
        result = compile_design_request(author, expected_identity=author["identity"])
        for mutate in (lambda r: r.update(schema_version=3),
                       lambda r: r["segmentation"]["axial_acceleration"].update(schema_version=2),
                       lambda r: r["segmentation"]["segmented_rod_array"].update(schema_version=1),
                       lambda r: r["segmentation"]["segmented_rod_array"]["electrodes"][0].update(electrode_id=1)):
            bad = copy.deepcopy(result); mutate(bad)
            with self.assertRaises(ContractError):
                validate_resolved_design_contract(bad)

    def test_new_table_explicitly_rejected_before_legacy_native_field_access(self):
        author = request(count=2)
        result = compile_design_request(author, expected_identity=author["identity"])
        with self.assertRaisesRegex(ValueError, "unsupported.*explicit backend compilation"):
            render_physical_gem(result, .2)

    def test_file_and_governed_compilation_and_provenance_use_same_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); author = request(count=2); path = root/"request.json"
            path.write_text(json.dumps(author), encoding="utf-8")
            result = compile_design_request_file(path, expected_identity=author["identity"], source_root=root)
            self.assertEqual(validate_resolved_design(result, request_path=path, source_root=root,
                              expected_identity=author["identity"]), result)
            variables = root/"variables.json"; variables.write_text(json.dumps(multipole_catalog(
                author["identity"]["project_id"], "request.json")), encoding="utf-8")
            envelope = root/"envelope.json"
            envelope.write_text(json.dumps(dict(schema_version=1, role="project_optimization_envelope",
                project_id=author["identity"]["project_id"], family_id="rf_multipole_ion_optics",
                envelope_id="capacity_test", status="candidate", policy="Controlled software fixture",
                reference=dict(design_request="request.json", design_request_sha256=hashlib.sha256(path.read_bytes()).hexdigest().upper()),
                constraints=[dict(constraint_id="r0", kind="bounded_variable",
                    request_json_pointers=["/geometry_mm/inscribed_radius_r0"], description="original radius bounds")]
            )), encoding="utf-8")
            governed = compile_governed_design_request_file(path, design_variables_path=variables,
                optimization_envelope_path=envelope, expected_identity=author["identity"], provenance_root=root)
            self.assertEqual(governed["schema_version"], 4)
            self.assertEqual(validate_resolved_design(governed, request_path=path, source_root=root,
                expected_identity=author["identity"]), governed)


if __name__ == "__main__":
    unittest.main()
