from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from common.simion.pa_family_cache import CACHE_KEY_FIELDS
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_pa_family import (
    derive_local_pa_family_contract,
    local_pa_family_filenames,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_local_patch_geometry import (
    build_local_patch_gem,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


PROJECT = Path(__file__).resolve().parents[2]
CONTRACT = PROJECT / "config" / "simion_candidate_two_zone.json"


class AnalyzerLocalPaFamilyTest(unittest.TestCase):
    def test_dirichlet_builder_derives_source_basis_voltage(self) -> None:
        source = (
            PROJECT.parents[1] / "common" / "simion" / "build_dirichlet_patch_basis.lua"
        ).read_text(encoding="utf-8")
        self.assertIn("local function source_basis_voltage(pa)", source)
        self.assertIn("active[identifier] and basis_voltage or 0", source)
        self.assertNotIn("active[identifier] and 1 or 0", source)

    def fixture(self, root: Path) -> tuple[Path, Path, Path]:
        gem = root / "central.gem"
        gem.write_text(
            build_local_patch_gem(CONTRACT, "central_transport", 1.0),
            encoding="utf-8",
            newline="\n",
        )
        family = root / "global"
        family.mkdir()
        (family / "mrtof_analyzer.pa#").write_bytes(b"raw")
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        physical_ids = {
            identifier
            for identifiers in contract["simion"]["analyzer_spatial_convergence"]["response_voltage_groups"].values()
            for identifier in identifiers
        }
        for identifier in physical_ids:
            (family / f"mrtof_analyzer.pa{identifier}").write_bytes(f"basis-{identifier}".encode())
        executable = root / "simion.exe"
        executable.write_bytes(b"simion")
        return gem, family, executable

    def test_derives_complete_eight_group_recipe(self) -> None:
        with TemporaryDirectory() as directory:
            gem, family, executable = self.fixture(Path(directory))
            result = derive_local_pa_family_contract(
                CONTRACT, "central_transport", 1.0, gem, family, executable, "SIMION 2020",
            )
        self.assertEqual(len(result["response_recipes"]), 8)
        self.assertEqual(len(result["family_filenames"]), 10)
        self.assertEqual(result["response_recipes"][0]["physical_ids"], [2, 7])
        self.assertEqual(result["response_recipes"][-1]["local_id"], 8)
        self.assertEqual(result["patch_origin_project_mm"], [-29.0, -82.0, -105.0])
        self.assertEqual(set(result["identity"]), set(CACHE_KEY_FIELDS))
        self.assertIn("coarse_parent_family", result["identity"]["geometry"])
        self.assertIn("dirichlet_boundary", result["identity"]["refine_policy"])
        self.assertEqual(result["identity"]["refine_policy"]["mode"], "installed_default")
        self.assertEqual(
            local_pa_family_filenames("mirror_turn_positive", 2),
            ("mrtof_analyzer_local_mirror_turn_positive.pa#",
             "mrtof_analyzer_local_mirror_turn_positive.pa0",
             "mrtof_analyzer_local_mirror_turn_positive.pa1",
             "mrtof_analyzer_local_mirror_turn_positive.pa2"),
        )

    def test_rejects_noncanonical_gem(self) -> None:
        with TemporaryDirectory() as directory:
            gem, family, executable = self.fixture(Path(directory))
            gem.write_text("wrong\n", encoding="utf-8")
            with self.assertRaises(CandidateContractError):
                derive_local_pa_family_contract(
                    CONTRACT, "central_transport", 1.0, gem, family, executable, "SIMION 2020",
                )


if __name__ == "__main__":
    unittest.main()
