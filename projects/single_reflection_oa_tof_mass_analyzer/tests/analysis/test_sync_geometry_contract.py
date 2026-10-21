from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from projects.single_reflection_oa_tof_mass_analyzer.analysis.sync_geometry_contract import (
    PROJECT_ROOT,
    frozen_fly2_seed,
    load_contract,
    render_authority_document,
    render_fly2,
    render_optimization_envelope,
    render_resolved_lua,
)
from common.contracts.machine_contracts import sha256
from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import (
    NUMERICS_PATH,
    resolve_contract,
)


class SyncGeometryContractTests(unittest.TestCase):
    def test_resolved_runtime_preserves_the_author_time_step_policy(self) -> None:
        numerics = json.loads(NUMERICS_PATH.read_text(encoding="utf-8"))
        numerics["comsol"]["solver_steps"] = "strict"
        numerics["comsol"]["times_to_store"] = "tlist"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "numerics.json"
            path.write_text(json.dumps(numerics), encoding="utf-8")
            actual = resolve_contract(numerics_path=path)["comsol_runtime"]
        self.assertEqual(actual["solver_steps"], "strict")
        self.assertEqual(actual["times_to_store"], "tlist")

    def test_invalid_or_missing_time_step_policy_is_rejected_before_resolution(self) -> None:
        for field, value in (
            ("solver_steps", None), ("solver_steps", "unknown"),
            ("solver_steps", "manual"), ("solver_steps", ["free"]),
            ("times_to_store", None), ("times_to_store", "unknown"),
            ("times_to_store", "tsteps"), ("times_to_store", "tstepsclosest"),
        ):
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as directory:
                numerics = json.loads(NUMERICS_PATH.read_text(encoding="utf-8"))
                if value is None:
                    del numerics["comsol"][field]
                else:
                    numerics["comsol"][field] = value
                path = Path(directory) / "numerics.json"
                path.write_text(json.dumps(numerics), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, field):
                    resolve_contract(numerics_path=path)

    def test_grid_policy_names_the_official_zero_width_one_row_model(self) -> None:
        contract = load_contract()
        expected = (
            "zero-grid-unit-thick one-row full-aperture 100%-transmission "
            "ideal electrode sheet"
        )
        self.assertEqual(contract["grid_policy"]["baseline"], expected)
        self.assertIn(f'baseline="{expected}"', render_resolved_lua(contract))

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

    def test_campaign_authorities_are_compiled_by_the_same_sync_chain(self) -> None:
        campaign = PROJECT_ROOT / "config" / "experiment_campaign.json"
        envelope_source = render_optimization_envelope()
        rendered = json.loads(render_authority_document(campaign, envelope_source))
        self.assertEqual(
            rendered["authorities"]["baseline"]["sha256"],
            sha256(PROJECT_ROOT / "config" / "baseline.json"),
        )
        self.assertEqual(
            rendered["authorities"]["solver_numerics"]["sha256"],
            sha256(PROJECT_ROOT / "config" / "formal_solver_numerics.json"),
        )
        self.assertEqual(
            rendered["authorities"]["optimization_envelope"]["sha256"],
            sha256(PROJECT_ROOT / "config" / "optimization_envelope.json"),
        )


if __name__ == "__main__":
    unittest.main()
