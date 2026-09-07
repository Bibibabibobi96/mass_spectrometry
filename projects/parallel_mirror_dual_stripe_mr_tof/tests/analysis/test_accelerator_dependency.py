"""Regression for the MR run-local independent accelerator source receipt."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from common.contracts.file_identity import file_sha256, repository_text_sha256
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.materialize_simion_prototype import (
    CandidateContractError,
    _freeze_accelerator_dependency,
    load_accelerator_dependency,
)


class AcceleratorDependencyTest(unittest.TestCase):
    def test_freezes_declared_provider_sources_and_exact_byte_identities(self) -> None:
        repo = Path(__file__).resolve().parents[4]
        with TemporaryDirectory() as temporary:
            output = Path(temporary)
            receipt = _freeze_accelerator_dependency(output)
            self.assertEqual(receipt["provider_project_id"], "orthogonal_accelerator")
            self.assertEqual(receipt["api_version"], 1)
            filenames = {row["source"] for row in receipt["files"]}
            self.assertIn("projects/orthogonal_accelerator/analysis/accelerator_time_focus.py", filenames)
            self.assertIn("projects/orthogonal_accelerator/simion/rectangular_accelerator.py", filenames)
            self.assertIn("projects/orthogonal_accelerator/analysis/component_contract.py", filenames)
            for row in receipt["files"]:
                self.assertEqual(file_sha256(repo / row["source"]), row["sha256"])
                self.assertEqual(file_sha256(output / row["frozen"]), row["sha256"])
                self.assertEqual(repository_text_sha256(repo / row["source"]), row["repository_text_sha256"])
                self.assertTrue((output / row["frozen"]).is_relative_to(output / "inputs"))

    def test_production_freeze_uses_shared_contract_validation(self) -> None:
        with TemporaryDirectory() as temporary, patch(
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis.materialize_simion_prototype."
            "load_accelerator_dependency", wraps=load_accelerator_dependency,
        ) as validator:
            _freeze_accelerator_dependency(Path(temporary))
            self.assertEqual(validator.call_count, 1)
            self.assertEqual(validator.call_args.kwargs["required_variant"], "two_zone")

    def test_invalid_component_fails_before_freezing(self) -> None:
        with TemporaryDirectory() as temporary, patch(
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis.materialize_simion_prototype."
            "load_accelerator_dependency", side_effect=ValueError("API version differs"),
        ):
            with self.assertRaisesRegex(CandidateContractError, "API version differs"):
                _freeze_accelerator_dependency(Path(temporary))
            self.assertEqual(list(Path(temporary).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
