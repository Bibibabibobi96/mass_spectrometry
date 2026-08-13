from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from projects.single_reflection_oa_tof_mass_analyzer.analysis.sync_geometry_contract import (
    PROJECT_ROOT,
    frozen_fly2_seed,
    load_contract,
    render_fly2,
    render_numerics_authority_document,
)
from common.contracts.machine_contracts import sha256


class SyncGeometryContractTests(unittest.TestCase):
    def test_fly2_seed_remains_a_run_instance_binding(self) -> None:
        contract = load_contract()
        self.assertNotIn("seed", contract["particle_source"])

        rendered = render_fly2(contract, particle_source_seed=20260729)

        self.assertIn("seed(20260729)", rendered)
        self.assertNotIn("seed", contract["particle_source"])

    def test_fly2_rendering_rejects_an_implicit_or_noninteger_seed(self) -> None:
        contract = load_contract()
        for invalid in (None, "20260729", True):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "explicit integer"):
                    render_fly2(contract, particle_source_seed=invalid)

    def test_freshness_reads_one_existing_frozen_seed_without_deriving_it_from_physics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fly2 = Path(directory) / "source.fly2"
            fly2.write_text("seed(20260713)\n", encoding="utf-8")
            self.assertEqual(frozen_fly2_seed(fly2), 20260713)

            fly2.write_text("seed(1)\nseed(2)\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exactly one"):
                frozen_fly2_seed(fly2)

    def test_campaign_numerics_authority_is_compiled_by_the_same_sync_chain(self) -> None:
        campaign = PROJECT_ROOT / "config" / "experiment_campaign.json"
        rendered = json.loads(render_numerics_authority_document(campaign))
        self.assertEqual(
            rendered["authorities"]["solver_numerics"]["sha256"],
            sha256(PROJECT_ROOT / "config" / "formal_solver_numerics.json"),
        )


if __name__ == "__main__":
    unittest.main()
