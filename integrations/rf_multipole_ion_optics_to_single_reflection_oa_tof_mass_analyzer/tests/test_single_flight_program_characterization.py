from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.build_single_flight_program import (
    build_successor_program,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.tests.test_support.legacy_single_flight_program import (
    bind_oatof_adjustables,
    build_extension,
    disable_redundant_ground_fast_adjust,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.resolved_region_field import (
    build_resolved_region_field_contract,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.tests.test_support.legacy_single_flight_program import (
    resolved_region_field_lua,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.tests.test_single_flight_program import (
    _minimal_program_contracts,
)


REPO = Path(__file__).resolve().parents[3]
TESTS = Path(__file__).resolve().parent
RECEIPT = TESTS / "fixtures/legacy_single_flight_program_characterization.json"
HARNESS = TESTS / "test_single_flight_program_callbacks.lua"
FORMAL = REPO / "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/formal/oatof_ideal_grounded.lua"
PULSE = REPO / "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/candidates/oatof_handoff_pulse.lua"
GEOMETRY = REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json"
KERNEL = REPO / "common/multipole/simion_rf_drive.lua"
ANALYZER = REPO / "projects/single_reflection_oa_tof_mass_analyzer/simion/workbench/candidates/oatof_analyzer_component.lua"
PULSE_HOOK = REPO / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runtime/single_flight_pulse_hook.lua"
FRONTEND_HOOK = REPO / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runtime/single_flight_frontend_hook.lua"
SIMION = Path(r"C:\Program Files\SIMION-2020\simion.exe")

TEST_CONTROL = """
segment.__legacy_test_set_adjustable=function(name,value)
  assert(type(name)=='string' and type(value)=='number',
    'legacy test adjustable control requires one string and one number')
  if name=='handoff_pulse_mode' then handoff_pulse_mode=value
  elseif name=='handoff_pulse_time_us' then handoff_pulse_time_us=value
  elseif name=='handoff_pulse_width_us' then handoff_pulse_width_us=value
  elseif name=='trajectory_log_enable' then trajectory_log_enable=value
  else error('legacy test adjustable name is not authorized: '..name) end
end
segment.__legacy_test_get_value=function(name)
  if name=='V_repeller' then return V_repeller
  elseif name=='V_grid1' then return V_grid1
  elseif name=='accelerator_grid1_z_mm' then return accelerator_grid1_z_mm
  elseif name=='accelerator_grid2_z_mm' then return accelerator_grid2_z_mm
  elseif name=='accelerator_repeller_front_z_mm' then return accelerator_repeller_front_z_mm
  else error('legacy test value name is not authorized: '..tostring(name)) end
end
"""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _legacy_program(
    directory: Path, *, test_control: bool = False
) -> tuple[str, dict[str, object]]:
    oatof = json.loads(GEOMETRY.read_text(encoding="utf-8"))
    formal = disable_redundant_ground_fast_adjust(
        bind_oatof_adjustables(FORMAL.read_text(encoding="utf-8"), oatof)
    )
    upstream, frontend = _minimal_program_contracts()
    extension = build_extension(
        upstream,
        frontend,
        birth_times_us=[0.25, 1.0],
        rf_drive_kernel_source=KERNEL.read_text(encoding="utf-8"),
        rf_steps_per_period=160,
    )
    region = build_resolved_region_field_contract(
        GEOMETRY, directory / "resolved_region.json", "accelerator_real_pa"
    )
    output = formal.rstrip() + "\n\n" + PULSE.read_text(encoding="utf-8").strip()
    output += "\n" + extension
    output += "\n-- BEGIN RESOLVED REGION FIELD CONTRACT\n"
    output += resolved_region_field_lua(
        region, enable_expression="single_flight_pulse_is_on()"
    )
    output += "\n-- END RESOLVED REGION FIELD CONTRACT\n"
    if test_control:
        output += TEST_CONTROL
    return output, region


def _successor_program(
    directory: Path, *, test_control: bool = False,
    profile_id: str = "accelerator_real_pa",
    overlay: dict[str, object] | None = None,
) -> str:
    oatof = json.loads(GEOMETRY.read_text(encoding="utf-8"))
    upstream, frontend = _minimal_program_contracts()
    region = build_resolved_region_field_contract(
        GEOMETRY, directory / "successor_resolved_region.json", profile_id
    )
    output = build_successor_program(
        upstream,
        frontend,
        oatof,
        region,
        birth_times_us=[0.25, 1.0],
        analyzer_component_source=ANALYZER.read_text(encoding="utf-8"),
        pulse_hook_source=PULSE_HOOK.read_text(encoding="utf-8"),
        frontend_hook_source=FRONTEND_HOOK.read_text(encoding="utf-8"),
        rf_drive_kernel_source=KERNEL.read_text(encoding="utf-8"),
        rf_steps_per_period=160,
        overlay=overlay,
    )
    if test_control:
        output += TEST_CONTROL
    return output


class LegacySingleFlightProgramCharacterizationTests(unittest.TestCase):
    def test_complete_program_identity_and_callback_counts_are_frozen(self) -> None:
        receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            program, region = _legacy_program(Path(temporary))
        self.assertEqual(_sha(FORMAL), receipt["inputs"]["formal_sha256"])
        self.assertEqual(_sha(PULSE), receipt["inputs"]["pulse_sha256"])
        self.assertEqual(_sha(GEOMETRY), receipt["inputs"]["resolved_geometry_sha256"])
        self.assertEqual(_sha(KERNEL), receipt["inputs"]["rf_drive_kernel_sha256"])
        self.assertEqual(
            region["semantic_sha256"], receipt["inputs"]["region_semantic_sha256"]
        )
        encoded = program.encode()
        self.assertEqual(len(encoded), receipt["complete_program"]["utf8_bytes"])
        self.assertEqual(
            hashlib.sha256(encoded).hexdigest().upper(),
            receipt["complete_program"]["sha256"],
        )
        self.assertEqual(program.count("simion.workbench_program()"), 1)
        for name, expected in receipt["complete_program"][
            "callback_definition_counts"
        ].items():
            actual = len(
                re.findall(rf"function\s+segment\.{re.escape(name)}\s*\(", program)
            )
            self.assertEqual(actual, expected, name)

    @unittest.skipUnless(SIMION.is_file(), "official SIMION Lua CLI unavailable")
    def test_official_simion_cli_freezes_legacy_callback_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            program, _ = _legacy_program(directory, test_control=True)
            program_path = directory / "legacy_single_flight.lua"
            program_path.write_text(program, encoding="utf-8", newline="\n")
            result = subprocess.run(
                [
                    str(SIMION),
                    "--nogui",
                    "--noprompt",
                    "lua",
                    str(HARNESS),
                    str(program_path),
                ],
                cwd=REPO,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("LEGACY_SINGLE_FLIGHT_CALLBACKS=PASS", result.stdout)

    def test_successor_program_has_one_complete_callback_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            program = _successor_program(Path(temporary))
        self.assertEqual(program.count("simion.workbench_program()"), 1)
        for name in ("load", "initialize_run", "efield_adjust", "fast_adjust",
                     "instance_adjust", "initialize", "tstep_adjust",
                     "other_actions", "terminate"):
            self.assertEqual(len(re.findall(rf"function\s+segment\.{name}\s*\(", program)), 1, name)

    @unittest.skipUnless(SIMION.is_file(), "official SIMION Lua CLI unavailable")
    def test_official_simion_cli_matches_legacy_callback_vectors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            program_path = directory / "successor_single_flight.lua"
            program_path.write_text(
                _successor_program(directory, test_control=True),
                encoding="utf-8",
                newline="\n",
            )
            result = subprocess.run(
                [str(SIMION), "--nogui", "--noprompt", "lua", str(HARNESS),
                 str(program_path), "successor"],
                cwd=REPO,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, "OATOF_ACCELERATOR_PA_OVERRIDE": "mock_combined_frontend.pa0"},
                timeout=20,
            )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("SUCCESSOR_SINGLE_FLIGHT_CALLBACKS=PASS", result.stdout)

    @unittest.skipUnless(SIMION.is_file(), "official SIMION Lua CLI unavailable")
    def test_official_simion_cli_full_ideal_field_vector(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            program_path = directory / "successor_full_ideal.lua"
            program_path.write_text(
                _successor_program(
                    directory,
                    test_control=True,
                    profile_id="full_domain_piecewise_ideal_field",
                ),
                encoding="utf-8",
                newline="\n",
            )
            result = subprocess.run(
                [str(SIMION), "--nogui", "--noprompt", "lua", str(HARNESS),
                 str(program_path), "successor_full_ideal"],
                cwd=REPO, check=False, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                env={**os.environ, "OATOF_ACCELERATOR_PA_OVERRIDE": "mock_combined_frontend.pa0"},
                timeout=20,
            )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("SUCCESSOR_SINGLE_FLIGHT_CALLBACKS=PASS", result.stdout)

    @unittest.skipUnless(SIMION.is_file(), "official SIMION Lua CLI unavailable")
    def test_official_simion_cli_overlay_vector(self) -> None:
        overlay: dict[str, object] = {
            "role": "rf_oatof_simion_accelerator_overlay_contract",
            "instance_origin_mm": {"x": 10.0, "y": 20.0, "z": 30.0},
            "active_bounds_mm": {
                "x_min": 0.0, "x_max": 100.0,
                "y_min": 0.0, "y_max": 100.0,
                "z_min": 0.0, "z_max": 100.0,
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            program_path = directory / "successor_overlay.lua"
            program_path.write_text(
                _successor_program(
                    directory, test_control=True, overlay=overlay
                ),
                encoding="utf-8",
                newline="\n",
            )
            result = subprocess.run(
                [str(SIMION), "--nogui", "--noprompt", "lua", str(HARNESS),
                 str(program_path), "successor_overlay"],
                cwd=REPO, check=False, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                env={**os.environ, "OATOF_ACCELERATOR_PA_OVERRIDE": "mock_combined_frontend.pa0"},
                timeout=20,
            )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("SUCCESSOR_SINGLE_FLIGHT_CALLBACKS=PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
