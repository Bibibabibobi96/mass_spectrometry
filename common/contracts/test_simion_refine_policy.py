"""Reject unbound Refine overrides while preserving documented numerical inputs."""

from __future__ import annotations

from pathlib import Path
import re
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_CONVERGENCE_OVERRIDE = re.compile(
    r"\brefine\b[^\r\n]*(?:--?convergence|\bconvergence\s*=)",
    re.IGNORECASE,
)
FORBIDDEN_INITIALIZER_OVERRIDE = re.compile(
    r"(?:initialize_fast_adjust_pa_basis\.lua|\bbasisinitializer\b)[^\r\n]*(?:,\s*['\"]?[0-9])",
    re.IGNORECASE,
)
SKIPPED_PATH_PARTS = {"archive", "history", ".git", ".venv"}
# DEVELOPMENT_STANDARDS section 6 and common/simion/README.md permit explicit
# contract-owned stopping values. Scope permission to these exact data-flow calls,
# not whole files or all scripts in the consuming project.
CONTRACT_BOUND_CALLS = {
    "common/simion/build_dirichlet_patch_basis.lua":
        "if convergence then target:refine{convergence=convergence} else target:refine() end",
    "projects/parallel_mirror_dual_stripe_mr_tof/simion/run_native_static_field_provider.ps1":
        "$arguments=@('--nogui','--noprompt','refine',('--convergence='+$convergenceText),($basename+'.pa'))",
}


def _has_unbound_override(relative_path: str, line: str) -> bool:
    """Accept only the named, documented pass-through calls; literals stay rejected."""
    if FORBIDDEN_INITIALIZER_OVERRIDE.search(line):
        return True
    return bool(FORBIDDEN_CONVERGENCE_OVERRIDE.search(line)) and (
        line.strip() != CONTRACT_BOUND_CALLS.get(relative_path)
    )


class SimionRefinePolicyTests(unittest.TestCase):
    """Explicit stopping settings require a documented numerical input boundary."""

    def test_active_simion_refine_calls_use_default_or_bound_contract(self) -> None:
        violations: list[str] = []
        this_file = Path(__file__).resolve()
        for suffix in ("*.lua", "*.ps1"):
            for path in REPOSITORY_ROOT.rglob(suffix):
                if path.resolve() == this_file or set(path.parts).intersection(
                    SKIPPED_PATH_PARTS
                ):
                    continue
                for line_number, line in enumerate(
                    path.read_text(encoding="utf-8", errors="replace").splitlines(),
                    start=1,
                ):
                    # Project-owned stopping input; permit only this exact frozen-input call.
                    if (
                        path.relative_to(REPOSITORY_ROOT).as_posix()
                        in {"projects/dual_pressure_rectilinear_ion_processor/simion/run_functional.ps1",
                            "projects/dual_pressure_rectilinear_ion_processor/simion/prepare_gui_replay.ps1"}
                        and line.strip() == "@{name='refine';stage='pa_refine';arguments=@('--nogui','--noprompt','refine',\"--convergence=$($numerics.refine_convergence_v)\",'processor.pa#')},"
                    ):
                        continue
                    if _has_unbound_override(path.relative_to(REPOSITORY_ROOT).as_posix(), line):
                        violations.append(f"{path.relative_to(REPOSITORY_ROOT)}:{line_number}")
        self.assertEqual(violations, [], "SIMION Refine override lacks a named contract boundary")

    def test_named_calls_preserve_optional_default_and_frozen_input(self) -> None:
        common = (REPOSITORY_ROOT / "common/simion/build_dirichlet_patch_basis.lua").read_text(
            encoding="utf-8"
        )
        for fragment in (
            "local convergence",
            "if arg[6]~=nil then",
            "tonumber(arg[6])",
            "convergence==convergence and convergence>0 and convergence<math.huge",
            CONTRACT_BOUND_CALLS["common/simion/build_dirichlet_patch_basis.lua"],
        ):
            self.assertIn(fragment, common)
        provider_path = next(path for path in CONTRACT_BOUND_CALLS if path.startswith("projects/"))
        provider = (REPOSITORY_ROOT / provider_path).read_text(encoding="utf-8")
        for fragment in (
            "$convergenceText=([double]$plan.refine_options.convergence).ToString('R',[Globalization.CultureInfo]::InvariantCulture)",
            "$cfg.parameters.refine_options=$plan.refine_options",
            CONTRACT_BOUND_CALLS[provider_path],
        ):
            self.assertIn(fragment, provider)

    def test_unregistered_or_literal_overrides_remain_rejected(self) -> None:
        for path, call in CONTRACT_BOUND_CALLS.items():
            with self.subTest(path=path):
                self.assertFalse(_has_unbound_override(path, call))
                self.assertTrue(_has_unbound_override("projects/other/simion/copied.lua", call))
                self.assertTrue(_has_unbound_override(path, "target:refine{convergence=1e-5}"))
                self.assertTrue(_has_unbound_override(path, "simion refine --convergence=1e-5 file.pa"))
                self.assertTrue(_has_unbound_override(path, "initialize_fast_adjust_pa_basis.lua, '0.001'"))
        self.assertFalse(_has_unbound_override("common/simion/default.lua", "target:refine()"))


if __name__ == "__main__":
    unittest.main()
