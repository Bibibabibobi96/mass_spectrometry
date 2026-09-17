"""Static contract tests for the read-only SIMION L1 response-slice sampler."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


SAMPLER = (
    Path(__file__).resolve().parents[2]
    / "simion"
    / "sample_mirror_l1_response_slice.lua"
)
EXPECTED_COLUMNS = (
    "x_mm,z_mm,is_electrode,"
    "mirror_B_potential_v,mirror_B_ex_v_per_mm,mirror_B_ey_v_per_mm,mirror_B_ez_v_per_mm,"
    "mirror_C_potential_v,mirror_C_ex_v_per_mm,mirror_C_ey_v_per_mm,mirror_C_ez_v_per_mm,"
    "mirror_D_potential_v,mirror_D_ex_v_per_mm,mirror_D_ey_v_per_mm,mirror_D_ez_v_per_mm,"
    "mirror_E_potential_v,mirror_E_ex_v_per_mm,mirror_E_ey_v_per_mm,mirror_E_ez_v_per_mm"
)


class MirrorRealFieldL1SamplerTests(unittest.TestCase):
    """Keep the supplier script read-only and its compact CSV contract stable."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SAMPLER.read_text(encoding="utf-8")

    def test_uses_only_demonstrated_read_only_pa_operations(self) -> None:
        for operation in (
            "simion.pas:open",
            ":point(",
            ":potential_vc(",
            ":field_vc(",
            ":inside_vc(",
            ":close()",
        ):
            self.assertIn(operation, self.source)
        self.assertIsNone(
            re.search(
                r":(?:save|refine|fast_adjust|potential_add|copy)\s*\(",
                self.source,
            )
        )
        self.assertNotRegex(self.source, r"(?<!_)\:potential\s*\(")

    def test_requires_generated_spec_output_path_and_explicit_ranges(self) -> None:
        self.assertIn("assert(#arg == 2", self.source)
        self.assertIn("loadfile(spec_path)", self.source)
        self.assertIn("io.open(output_path, 'w')", self.source)
        for field in (
            "schema_version",
            "project_frame",
            "region_id",
            "region_origin_project_mm",
            "slice_y_mm",
            "x_range_mm",
            "z_range_mm",
            "standalone_pa_path",
            "normalization_v",
        ):
            self.assertIn(field, self.source)
        self.assertNotRegex(self.source, r"\b(?:280|340|390)\b")

    def test_emits_exact_compact_four_response_schema(self) -> None:
        columns = re.findall(r"'([^']+)'", self.source.split("local CSV_HEADER", 1)[1].split("}, ','", 1)[0])
        self.assertEqual(",".join(columns), EXPECTED_COLUMNS)
        self.assertEqual(
            re.search(r"local GROUPS = \{([^\n]+)\}", self.source).group(1),
            "'B', 'C', 'D', 'E'",
        )
        self.assertIn("#spec.responses == #GROUPS", self.source)
        self.assertIn("responses must be ordered exactly B,C,D,E", self.source)
        self.assertIn("B--E responses must share one normalization_v", self.source)
        self.assertIn("local ex, ey, ez = response.pa:field_vc", self.source)

    def test_samples_native_nodes_and_fails_closed_on_grid_mismatch(self) -> None:
        self.assertIn("must lie on a native PA grid node", self.source)
        self.assertIn("response PA dimensions differ", self.source)
        self.assertIn("response PA scales differ", self.source)
        self.assertIn("lies outside PA grid", self.source)
        self.assertIn("lies outside PA interpolation domain", self.source)
        self.assertIn("for iz = iz_min, iz_max do", self.source)
        self.assertIn("for ix = ix_min, ix_max do", self.source)

    def test_requires_one_consistent_electrode_mask_and_closes_handles(self) -> None:
        self.assertIn(
            "B--E response electrode masks differ at requested native grid node",
            self.source,
        )
        protected_call = self.source.index("local ok, failure = pcall(run)")
        cleanup = self.source.index("for index = #opened_pas, 1, -1 do")
        rethrow = self.source.index("if not ok then error(failure, 0) end")
        self.assertLess(protected_call, cleanup)
        self.assertLess(cleanup, rethrow)
        self.assertIn("samples=%d vacuum=%d electrode=%d", self.source)


if __name__ == "__main__":
    unittest.main()
