from __future__ import annotations

from pathlib import Path
import unittest


RUNTIME = Path(__file__).resolve().parents[1] / "runtime"
BUILDER = RUNTIME / "build_accelerator_pa_plus_basis.lua"


class AcceleratorPaPlusBasisBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = BUILDER.read_text(encoding="utf-8")

    def test_default_source_is_an_explicit_standalone_mode_map(self) -> None:
        self.assertIn(
            "local source_policy=arg[11] or 'standalone_mode_map_v1'",
            self.source,
        )
        self.assertIn("header=='standalone_pa_mode_map_v1'", self.source)
        self.assertIn("standalone_paths=parse_standalone_mode_map(source_input,modes)", self.source)
        self.assertIn("simion.pas:open(source_path(term.id))", self.source)
        self.assertNotIn("simion.pas:open(indexed(source_pa0,term.id))", self.source)

    def test_map_rejects_family_members_and_requires_exact_term_coverage(self) -> None:
        self.assertIn("not lower:match('%.pa%d+$')", self.source)
        self.assertIn("not lower:match('%.pa0$')", self.source)
        self.assertIn("not lower:match('%.pa[+_]$')", self.source)
        self.assertIn("paths[term.id]~=nil", self.source)
        self.assertIn("standalone source mode map contains an unused response id", self.source)
        self.assertIn("mapped_count==required_count", self.source)

    def test_native_family_lookup_requires_explicit_writable_staging_policy(self) -> None:
        self.assertIn("'writable_staging_native_family_v1'", self.source)
        self.assertIn(
            "writable staging native-family source must end in .pa0",
            self.source,
        )
        self.assertIn("return indexed(source_input,id)", self.source)

    def test_existing_disjoint_boundary_and_default_refine_contract_are_unchanged(self) -> None:
        self.assertIn("for ix=1,fine.nx-2 do", self.source)
        self.assertIn("for iy=1,fine.ny-2 do", self.source)
        self.assertIn("disjoint PA+ boundary traversal", self.source)
        self.assertNotIn("convergence=", self.source)


if __name__ == "__main__":
    unittest.main()
