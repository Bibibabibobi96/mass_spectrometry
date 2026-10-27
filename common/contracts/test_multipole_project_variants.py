"""Preserve multipole physical inputs and reject mixed structural identities."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from common.contracts.build_project_registry import validate_descriptor, validate_structural_variants
from common.contracts.machine_contracts import ContractError
from projects.rf_multipole_ion_optics.core.compile_design_request import (
    compile_governed_design_request_file,
)
from projects.rf_multipole_ion_optics.runtime.design_profile import (
    resolve_design_profile, validate_design_profile_structures,
)
from projects.rf_multipole_ion_optics.runtime.runtime_profile import resolve_runtime_profile


REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "rf_multipole_ion_optics"
PROJECT_ROOT = REPO_ROOT / "projects" / PROJECT_ID


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def compile_profile(profile_id: str) -> dict:
    selection = resolve_design_profile(REPO_ROOT, PROJECT_ID, profile_id)
    return selection.get("resolved_design") or compile_governed_design_request_file(
        selection["paths"]["design_request"],
        selection["paths"]["design_variables"],
        selection["paths"]["optimization_envelope"],
        expected_identity=selection["profile"]["identity"],
        provenance_root=REPO_ROOT,
    )


def physical_projection(document: dict) -> dict:
    """Exclude only moved ownership/provenance; retain all physical scalars."""
    value = copy.deepcopy(document)
    for key in ("compiler", "governance", "request", "sources", "resolved_sha256"):
        value.pop(key, None)
    value["identity"].pop("project_id")
    if value["segmentation"]["axial_acceleration"] is not None:
        value["segmentation"]["axial_acceleration"].pop("project_id")
    energy_model = value.get("particle_source", {}).get("energy_model", {})
    if "authority" in energy_model:
        energy_model["authority"] = Path(energy_model["authority"]).name
    return value


class MultipoleStructuralVariantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.descriptor = load(PROJECT_ROOT / "config/project.json")
        self.profiles = load(PROJECT_ROOT / "config/design_profiles.json")["profiles"]

    def test_isolated_frozen_resolver_includes_public_and_project_schema_resources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ignore = shutil.ignore_patterns("__pycache__", "test_*.py", "fixtures", "examples")
            for relative in ("common/contracts", f"projects/{PROJECT_ID}/core", f"projects/{PROJECT_ID}/config"):
                shutil.copytree(REPO_ROOT / relative, root / relative, ignore=ignore)
            runtime = root / "projects" / PROJECT_ID / "runtime"
            runtime.mkdir()
            shutil.copyfile(PROJECT_ROOT / "runtime/design_profile.py", runtime / "design_profile.py")
            for variant in ("quadrupole", "hexapole", "octupole"):
                relative = f"projects/{PROJECT_ID}/variants/{variant}/config"
                shutil.copytree(REPO_ROOT / relative, root / relative, ignore=ignore)
            (root / "config").mkdir()
            shutil.copyfile(REPO_ROOT / "config/project_registry.json", root / "config/project_registry.json")
            code = (
                "import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
                "from projects.rf_multipole_ion_optics.runtime.design_profile import resolve_design_profile; "
                "results=[resolve_design_profile(Path(sys.argv[1]),'rf_multipole_ion_optics',v+'_no_acceleration_full_length') "
                "for v in ('quadrupole','hexapole','octupole')]; "
                "assert [r['resolved_design']['identity']['electrode_count'] for r in results]==[4,6,8]; "
                "print('FROZEN_DESIGN_PROFILE=PASS STRUCTURES=3')"
            )
            result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(root)],
                                    cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("FROZEN_DESIGN_PROFILE=PASS", result.stdout)

    def test_all_structures_are_discoverable_and_bound_to_their_own_capabilities(self) -> None:
        validate_structural_variants(self.descriptor, self.profiles, PROJECT_ROOT)
        self.assertEqual(
            {v["variant_id"] for v in self.descriptor["structural_variants"]},
            {"quadrupole", "hexapole", "octupole"},
        )
        validate_design_profile_structures(self.descriptor, self.profiles, PROJECT_ROOT)

    def test_wrong_pole_count_and_undeclared_structure_fail_closed(self) -> None:
        changed = copy.deepcopy(self.profiles)
        changed[0]["identity"]["electrode_count"] = 8
        with self.assertRaisesRegex(ContractError, "structural identity"):
            validate_design_profile_structures(self.descriptor, changed, PROJECT_ROOT)
        changed[0]["structural_variant_id"] = "undeclared"
        with self.assertRaisesRegex(ContractError, "declared structural variant"):
            validate_structural_variants(self.descriptor, changed, PROJECT_ROOT)

    def test_capability_cannot_inherit_another_structure_owner(self) -> None:
        self.descriptor["structural_variants"][1]["capability_ids"].append(
            self.descriptor["structural_variants"][0]["capability_ids"][0]
        )
        with self.assertRaisesRegex(ContractError, "capability ownership"):
            validate_structural_variants(self.descriptor, self.profiles, PROJECT_ROOT)

    def test_capability_variables_must_exist_in_the_selected_structure_catalog(self) -> None:
        capability_id = self.descriptor["structural_variants"][1]["capability_ids"][0]
        capability = next(item for item in self.descriptor["capabilities"] if item["capability_id"] == capability_id)
        capability["design_variables"].append("not_a_catalog_variable")
        with self.assertRaisesRegex(ContractError, "structural variant capability variables are unsupported"):
            validate_descriptor(self.descriptor, PROJECT_ROOT / "config/project.json", REPO_ROOT)

    def test_independent_rectangular_references_preserve_existing_physical_fixture(self) -> None:
        fixture = load(Path(__file__).with_name("fixtures") / "multipole_structural_variant_migration.json")
        references = {"quadrupole_official_transport", "quadrupole_interface_readiness", "quadrupole_mass_filter_reference", "quadrupole_explicit_axial_reference"}
        for record in fixture["profiles"]:
            if record["design_profile_id"] not in references:
                continue
            with self.subTest(profile=record["design_profile_id"]):
                value = physical_projection(compile_profile(record["design_profile_id"]))
                self.assertEqual(value["geometry_mm"]["enclosure"]["model"],"rectangular_reference_enclosure_v1")
                # The fixture predates schema3. Only its serialization version is
                # normalized; every geometric, voltage and source scalar remains.
                # This test-only comparison is not a production schema-compatibility path.
                value["schema_version"] = 2
                payload = json.dumps(value,sort_keys=True,separators=(",", ":"),ensure_ascii=False).encode()
                self.assertEqual(hashlib.sha256(payload).hexdigest().upper(),record["physical_projection_sha256"])

    def test_current_bare_providers_do_not_inherit_retired_shell_qualification(self) -> None:
        fixture_path = Path(__file__).with_name("fixtures") / "multipole_structural_variant_migration.json"
        original = fixture_path.read_bytes()
        records = {row["design_profile_id"]:row for row in load(fixture_path)["profiles"]}
        for variant in ("quadrupole", "hexapole", "octupole"):
            name = variant + "_no_acceleration_full_length"
            current = compile_profile(name)
            self.assertEqual(current["geometry_mm"]["enclosure"], {"model":"bare"})
            self.assertEqual(current["geometry_mm"]["enclosure_layout"]["bodies"], [])
            self.assertNotIn("interfaces_mm",current)
            value=physical_projection(current)
            value["schema_version"]=2
            payload=json.dumps(value,sort_keys=True,separators=(",", ":"),ensure_ascii=False).encode()
            self.assertNotEqual(hashlib.sha256(payload).hexdigest().upper(),records[name]["physical_projection_sha256"])
        self.assertEqual(fixture_path.read_bytes(),original)

    def test_each_runtime_resolves_explicit_structure_and_its_original_inputs(self) -> None:
        registry = load(PROJECT_ROOT / "config/runtime_profiles.json")
        for name, profile in registry["profiles"].items():
            with self.subTest(runtime=name):
                runtime = resolve_runtime_profile(REPO_ROOT, PROJECT_ID, name)
                selected = runtime["design_profile_resolution"]["profile"]
                self.assertEqual(selected["identity"]["project_id"], PROJECT_ID)
                self.assertEqual(runtime["design_profile_id"], profile["design_profile_id"])
                self.assertEqual(runtime["particle_source"]["profile_id"], profile["particle_source_profile_id"])
                self.assertEqual(runtime["solver_numerics"]["simion"]["profile_id"], profile["simion_solver_numerics_profile_id"])
        with self.assertRaisesRegex(ValueError, "unknown runtime profile"):
            resolve_runtime_profile(REPO_ROOT, PROJECT_ID, "no_acceleration_full_length")

    def test_shared_source_identity_and_csv_bytes_are_not_duplicated_or_relabelled(self) -> None:
        fixture = load(Path(__file__).with_name("fixtures") / "multipole_structural_variant_migration.json")
        registry = load(PROJECT_ROOT / "config/particle_source_profiles.json")["profiles"]
        for source in fixture["shared_particle_sources"]:
            name = source["profile_id"]
            self.assertIn(name, registry)
            self.assertFalse(any(f"{variant}_{name}" in registry for variant in ("quadrupole", "hexapole", "octupole")))
            self.assertEqual(hashlib.sha256((REPO_ROOT / registry[name]["path"]).read_bytes()).hexdigest().upper(), source["bytes_sha256"])


if __name__ == "__main__":
    unittest.main()
