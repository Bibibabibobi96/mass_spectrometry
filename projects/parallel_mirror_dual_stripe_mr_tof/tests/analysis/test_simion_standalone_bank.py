"""Tests for detached accelerator response-bank validation."""
from __future__ import annotations

import json
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest

from common.simion.pa_family_cache import PAFamilyCacheError, publish_pa_family_cache
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_pa_family_cache import (
    accelerator_standalone_response_contract,
    component_pa_cache_filenames,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_standalone_bank import (
    validate_accelerator_standalone_bank,
)


def identity() -> dict[str, object]:
    return {
        "geometry": {"sha256": "A" * 64},
        "gem": {"sha256": "B" * 64},
        "basis_namespace": {"ids": list(range(1, 10))},
        "mesh": {"mm_per_gu": [0.25, 0.25, 0.1]},
        "grid_phase": {"origin_mm": [0, 0, 0]},
        "surface": "none",
        "simion_identity": {"release": "2020"},
        "refine_policy": {"mode": "test"},
        "builder_identity": {"sha256": "C" * 64},
    }


class SimionStandaloneBankTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        for name in component_pa_cache_filenames("accelerator"):
            (self.source / name).write_bytes(name.encode("ascii"))
        self.cache = self.root / "cache"
        self.published = publish_pa_family_cache(
            self.cache,
            identity(),
            self.source,
            component_pa_cache_filenames("accelerator"),
        )
        self.publication = self.root / "publication.json"
        self.publication.write_text(
            json.dumps(
                {
                    "cache_key": self.published.cache_key,
                    "generation_sha256": self.published.generation_sha256,
                    "generation_directory": str(self.published.generation_directory),
                    "standalone_response_contract": accelerator_standalone_response_contract(),
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_validates_detached_bank_after_unused_native_member_changes(self) -> None:
        native = self.published.generation_directory / "mrtof_accelerator.pa0"
        native.chmod(native.stat().st_mode | stat.S_IWUSR)
        native.write_bytes(b"changed-native-member")
        receipt = validate_accelerator_standalone_bank(self.cache, self.publication)
        self.assertEqual(receipt["disposition"], "hit")
        self.assertFalse(receipt["native_family_members_opened"])
        self.assertFalse(receipt["complete_native_generation_qualified"])
        self.assertEqual(len(receipt["validated_filenames"]), 20)

    def test_rejects_a_changed_consumed_response(self) -> None:
        response = self.published.generation_directory / "mrtof_accelerator.response4.pa"
        response.chmod(response.stat().st_mode | stat.S_IWUSR)
        response.write_bytes(b"changed-response")
        with self.assertRaisesRegex(PAFamilyCacheError, "response4"):
            validate_accelerator_standalone_bank(self.cache, self.publication)

    def test_rejects_pointer_or_publication_path_drift(self) -> None:
        pointer = self.published.generation_directory.parents[1] / "current_generation.json"
        pointer.write_text(
            json.dumps(
                {
                    "cache_key": self.published.cache_key,
                    "generation_sha256": "D" * 64,
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(PAFamilyCacheError, "pointer differs"):
            validate_accelerator_standalone_bank(self.cache, self.publication)


if __name__ == "__main__":
    unittest.main()
