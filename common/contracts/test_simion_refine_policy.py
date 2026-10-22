"""Reject unbound Refine overrides while preserving documented numerical inputs."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
import tempfile
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
    "common/simion/build_dirichlet_patch_operating_pa.lua":
        "if convergence then solved:refine{convergence=convergence} else solved:refine() end",
    "common/simion/build_dirichlet_patch_basis.lua":
        "elseif convergence then target:refine{convergence=convergence} else target:refine() end",
    "projects/parallel_mirror_dual_stripe_mr_tof/simion/run_native_static_field_provider.ps1":
        "$arguments=@('--nogui','--noprompt','refine',('--convergence='+$convergenceText),($basename+'.pa'))",
    "projects/parallel_mirror_dual_stripe_mr_tof/simion/run_ip_prism_local_case.lua":
        "pa:refine{convergence=c.convergence_v}",
}
CONTRACT_BOUND_SKIPPED_POINT_CALL = "if skipped_point~=nil then target:refine{convergence=convergence,skipped_point=skipped_point}"


def _has_unbound_override(relative_path: str, line: str) -> bool:
    """Accept only the named, documented pass-through calls; literals stay rejected."""
    if FORBIDDEN_INITIALIZER_OVERRIDE.search(line):
        return True
    return bool(FORBIDDEN_CONVERGENCE_OVERRIDE.search(line)) and (
        line.strip() != CONTRACT_BOUND_CALLS.get(relative_path)
        and not (relative_path == "common/simion/build_dirichlet_patch_basis.lua"
                 and line.strip() == CONTRACT_BOUND_SKIPPED_POINT_CALL)
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
            CONTRACT_BOUND_SKIPPED_POINT_CALL,
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

    def test_operating_patch_stopping_is_bound_to_optional_finite_input(self) -> None:
        path = "common/simion/build_dirichlet_patch_operating_pa.lua"
        source = (REPOSITORY_ROOT / path).read_text(encoding="utf-8")
        for fragment in (
            "if arg[7]~=nil then",
            "tonumber(arg[7])",
            "convergence==convergence and convergence>0 and convergence<math.huge",
            "assert(arg[8]==nil",
            CONTRACT_BOUND_CALLS[path],
        ):
            self.assertIn(fragment, source)

    def test_official_skipped_point_option_reaches_fake_pa_without_changing_defaults(self) -> None:
        lua = Path("C:/Program Files/SIMION-2020/lua.exe")
        if not lua.is_file():
            self.skipTest("installed Lua interpreter required; no SIMION process")
        adapter = REPOSITORY_ROOT / "common/simion/build_dirichlet_patch_basis.lua"
        code = r'''
local adapter,mode=arg[1],arg[2]
local source={dx_mm=1,dy_mm=1,dz_mm=1}
function source:inside_vc() return true end
function source:potential_vc() return 3 end
function source:close() end
local target={nx=3,ny=3,nz=3,dx_mm=1,dy_mm=1,dz_mm=1}
function target:point(x,y,z,p,e) if p==nil then return 0,false end end
function target:save() end
function target:close() end
function target:refine(options)
 if mode=='default' then assert(options==nil)
 elseif mode=='convergence' then assert(options.convergence==1e-5 and options.skipped_point==nil)
 else assert(options.convergence==1e-5 and options.skipped_point==(mode=='1')) end
 print('MOCK_REFINE_POLICY=PASS')
end
simion={pas={}}
function simion.pas:open(path) return path=='target.pa' and target or source end
arg={'target.pa','source.pa','0,0,0','0,0,0','x_mirror_five_faces'}
if mode~='default' then arg[6]='1e-5' end
if mode~='default' and mode~='convergence' then arg[7]=mode end
dofile(adapter)
'''
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "fixture.lua"
            fixture.write_text(code, encoding="utf-8")
            for mode in ("default", "convergence", "0", "1", "false", "2"):
                with self.subTest(mode=mode):
                    run = subprocess.run([str(lua), str(fixture), str(adapter), mode], cwd=directory,
                                         capture_output=True, text=True, timeout=30)
                    if mode in ("false", "2"):
                        self.assertNotEqual(run.returncode, 0)
                        self.assertIn("must be 0 or 1", run.stderr)
                    else:
                        self.assertEqual(run.returncode, 0, run.stdout+run.stderr)
                        self.assertIn("MOCK_REFINE_POLICY=PASS", run.stdout)


if __name__ == "__main__":
    unittest.main()
