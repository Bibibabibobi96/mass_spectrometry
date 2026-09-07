"""Opt-in SIMION 2020 compiled-PA regressions for the CAD finite slots.

Set SIMION_EXE to the installed executable and run under the repository host
execution lease. Temporary GEM/PA files are test fixtures, not field solutions
or released review assets. The installed vendor Python PA reader is read-only.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.full_candidate_geometry import (
    _mirror_lines,
    _prism_ground_shield_lines,
    _stripe_lines,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import resolve_geometry
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import load_contract


PROJECT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get("SIMION_EXE"), "native SIMION executable not selected")
class NativeGemSlotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not os.environ.get("MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID"):
            raise RuntimeError("native geometry regression requires the host execution lease")
        cls.executable = Path(os.environ["SIMION_EXE"]).resolve(strict=True)
        reader = cls.executable.parent / "lib/python/SIMION/PA.py"
        spec = importlib.util.spec_from_file_location("simion_vendor_pa_reader", reader)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"installed SIMION Python PA reader unavailable: {reader}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.pa_type = module.PA
        cls.resolved = resolve_geometry(load_contract(PROJECT / "config/simion_candidate_two_zone.json"))

    def compile_shapes(self, lines: list[str], origin: tuple[float, float, float],
                       dimensions: tuple[int, int, int], mesh_mm: tuple[float, float, float] = (2.0, 2.0, 2.0)):
        """Compile production fragments at an explicit frozen analyser grid phase."""
        temporary = tempfile.TemporaryDirectory(prefix="mrtof-native-slot-test-")
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name)
        gem, pa = folder / "slot.gem", folder / "slot.pa#"
        header = (
            f"pa_define({dimensions[0]},{dimensions[1]},{dimensions[2]},"
            f"planar,none,electrostatic,,{mesh_mm[0]},{mesh_mm[1]},{mesh_mm[2]},surface=none)\n"
            f"locate({-origin[0]},{-origin[1]},{-origin[2]}) {{\n"
        )
        gem.write_text(header + "\n".join(lines) + "\n}\n", encoding="utf-8")
        result = subprocess.run(
            [str(self.executable), "--nogui", "gem2pa", str(gem), str(pa)],
            cwd=folder, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=300, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(pa.is_file(), result.stdout + result.stderr)
        return self.pa_type(file=str(pa))

    def assert_node(self, pa, origin, position, expected_id: int | None,
                    mesh_mm: tuple[float, float, float] = (2.0, 2.0, 2.0)) -> None:
        indices = tuple(round((position[i] - origin[i]) / mesh_mm[i]) for i in range(3))
        self.assertEqual(tuple(origin[i] + mesh_mm[i] * indices[i] for i in range(3)), position)
        actual = int(pa.potential(*indices)) if pa.electrode(*indices) else None
        self.assertEqual(actual, expected_id, f"project-mm={position}; grid={indices}")

    def test_short_prism_shield_retains_end_lands_and_open_reflection_channel(self) -> None:
        shield = next(item for item in self.resolved["prism_ground_shields"] if item["id"] == 18)
        origin = (-26.0, 32.0, -102.0)
        pa = self.compile_shapes(_prism_ground_shield_lines({"prism_ground_shields": [shield]}),
                                 origin, (21, 25, 39))
        for y in (34.0, 76.0):
            for z in (-98.0, -80.0, -64.0, -40.0, -32.0):
                for x in (-4.0, 0.0, 4.0):
                    self.assert_node(pa, origin, (x, y, z), 18)
        for z in (-100.0, -80.0, -64.0, -40.0, -30.0):
            self.assert_node(pa, origin, (0.0, 36.0, z), None)

    def test_curved_stripe_is_one_slotted_body_with_two_finite_end_lands(self) -> None:
        stripe = next(item for item in self.resolved["stripe_electrodes"] if item["id"] == 11)
        origin = (-14.0, -392.0, 30.0)
        pa = self.compile_shapes(_stripe_lines({"stripe_electrodes": [stripe],
                                               "stripe_slot": self.resolved["stripe_slot"]}),
                                 origin, (29, 198, 36), (1.0, 2.0, 2.0))
        for y in (-390.0, -388.0, -386.0, 2.0):
            for x in (-4.0, -2.0, 0.0, 2.0, 4.0):
                self.assert_node(pa, origin, (x, y, 90.0), 11, (1.0, 2.0, 2.0))
        for y in (-384.0, -4.0, -2.0):
            for x in (-1.0, 0.0, 1.0):
                self.assert_node(pa, origin, (x, y, 90.0), None, (1.0, 2.0, 2.0))
        # ``y=0`` is the CAD end face of the retained 2-mm bridge, not part
        # of the finite interior slot.
        self.assert_node(pa, origin, (0.0, 0.0, 90.0), 11, (1.0, 2.0, 2.0))

    def test_central_prism_shield_has_cross_slot_and_local_body_extensions(self) -> None:
        shield = next(item for item in self.resolved["prism_ground_shields"] if item["id"] == 20)
        origin = (-26.0, -6.0, -100.0)
        pa = self.compile_shapes(_prism_ground_shield_lines({"prism_ground_shields": [shield]}),
                                 origin, (21, 21, 101))
        for position in ((4., 0., 60.), (-18., 4., 30.), (0., 4., 30.),
                         (0., 10., 60.), (4., 24., 24.)):
            self.assert_node(pa, origin, position, None)
        for position in ((4., 0., 10.), (-18., 4., 60.), (0., 4., 60.)):
            self.assert_node(pa, origin, position, 20)

    def test_mirror_30mm_slot_does_not_remove_nodes_outside_cad_aperture(self) -> None:
        mirror = self.resolved["mirror_electrodes"][0]
        # At the active 1-mm x grid, a 30-mm CAD slot has first metal nodes
        # at ±15 mm (not ±16); the open nodes are -14..14.
        z = 2.0 * round((mirror["box"][2] + mirror["box"][5]) / 4.0)
        origin = (-20.0, -2.0, z - 2.0)
        pa = self.compile_shapes(_mirror_lines({"mirror_electrodes": [mirror]}),
                                 origin, (41, 3, 3), (1.0, 2.0, 2.0))
        for x in (-14., 0., 14.):
            self.assert_node(pa, origin, (x, 0., z), None, (1.0, 2.0, 2.0))
        for x in (-15., 15.):
            self.assert_node(pa, origin, (x, 0., z), mirror["id"], (1.0, 2.0, 2.0))

    def test_detector_builder_retains_terminal_mask_with_zero_voltage_without_refine(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mrtof-native-detector-test-") as temporary:
            folder = Path(temporary)
            gem, raw = folder / "detector.gem", folder / "detector.pa#"
            gem.write_text("pa_define(7,7,5,planar,none,electrostatic,,1,1,1,surface=none)\n"
                           "e(25) { box3D(1,1,2,5,5,2) }\n", encoding="utf-8")
            result = subprocess.run(
                [str(self.executable), "--nogui", "lua", str(PROJECT / "simion/build_component_pa.lua"),
                 str(gem), str(raw), "1", "1", "1", "25", "0"],
                cwd=folder, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=300, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("GEOMETRY_ONLY_ZERO_VOLTAGE_RAW_PA", result.stdout)
            self.assertFalse(raw.with_suffix(".pa0").exists())
            pa = self.pa_type(file=str(raw))
            self.assertTrue(pa.electrode(3, 3, 2))
            self.assertFalse(pa.electrode(0, 0, 0))
            for z in range(5):
                for y in range(7):
                    for x in range(7):
                        self.assertEqual(pa.potential(x, y, z), 0.0)

    def test_sparse_basis_keeps_zero_response_mask_and_saved_fast_adjust(self) -> None:
        """A numbering hole is a zero basis, not an extra physical electrode."""
        with tempfile.TemporaryDirectory(prefix="mrtof-native-sparse-basis-test-") as temporary:
            folder = Path(temporary)
            # Keep the fixture small without using the 5-cube initialization
            # case that exceeded 300 s in SIMION 2020 before reaching basis code.
            nodes = 21
            edge = nodes - 1
            gem, raw_path = folder / "sparse.gem", folder / "sparse.pa#"
            gem.write_text(f"pa_define({nodes},{nodes},{nodes},planar,none,electrostatic,,1,1,1,surface=none)\n"
                           f"e(1) {{ box3D(0,0,0,0,{edge},{edge}) }}\n"
                           f"e(3) {{ box3D({edge},0,0,{edge},{edge},{edge}) }}\n", encoding="utf-8")

            def native(*arguments: str) -> str:
                try:
                    result = subprocess.run(
                        [str(self.executable), "--nogui", *arguments], cwd=folder,
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                        timeout=300, check=False,
                    )
                except subprocess.TimeoutExpired as error:
                    self.fail(f"native fixture timed out: {error}\n{error.output!r}\n{error.stderr!r}")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result.stdout + result.stderr

            native("lua", str(PROJECT / "simion/build_component_pa.lua"),
                   str(gem), str(raw_path), "1", "1", "1", "1,3", "1")
            output = native("lua", str(PROJECT / "simion/build_component_basis.lua"),
                            str(raw_path), "1,2,3")
            for electrode_id in (1, 2, 3):
                self.assertIn(f"COMPONENT_BASIS PASS id={electrode_id}", output)
                self.assertTrue(raw_path.with_suffix(f".pa{electrode_id}").is_file())
            raw = self.pa_type(file=str(raw_path))
            zero = self.pa_type(file=str(raw_path.with_suffix(".pa2")))
            electrode_ids = set()
            for z in range(nodes):
                for y in range(nodes):
                    for x in range(nodes):
                        self.assertEqual(zero.potential(x, y, z), 0.0)
                        self.assertEqual(zero.electrode(x, y, z), raw.electrode(x, y, z))
                        if raw.electrode(x, y, z):
                            electrode_ids.add(raw.potential(x, y, z))
            self.assertEqual(electrode_ids, {1, 3})

            # Independent explicit test voltages, not MR Candidate settings.
            voltages = {1: 17.25, 3: -6.5}
            adjust = folder / "adjust.lua"
            table = "{" + ",".join(f"[{key}]={value}" for key, value in voltages.items()) + "}"
            adjust.write_text(
                "local path=assert(arg[1])\n"
                "local pa=assert(simion.pas:open(path))\n"
                f"pa:fast_adjust{table}\n"
                "pa:save(path)\npa:close()\n"
                "local reopened=assert(simion.pas:open(path))\n"
                f"assert(reopened.nx=={nodes} and reopened.ny=={nodes} and reopened.nz=={nodes})\n"
                "reopened:close()\nprint('SPARSE_BASIS_FAST_ADJUST_RELOAD=PASS')\n",
                encoding="utf-8",
            )
            adjusted_path = raw_path.with_suffix(".pa0")
            output = native("lua", str(adjust), str(adjusted_path))
            self.assertIn("SPARSE_BASIS_FAST_ADJUST_RELOAD=PASS", output)
            adjusted = self.pa_type(file=str(adjusted_path))
            # Official SIMION PA floating-point encoding starts at 100000 V;
            # budget encoding roundoff only, not numerical field convergence.
            tolerance = 16 * 2**-52 * max(100000, *map(abs, voltages.values()))
            for z in range(nodes):
                for y in range(nodes):
                    for x in range(nodes):
                        self.assertEqual(adjusted.electrode(x, y, z), raw.electrode(x, y, z))
                        if raw.electrode(x, y, z):
                            self.assertAlmostEqual(adjusted.potential(x, y, z),
                                                   voltages[raw.potential(x, y, z)], delta=tolerance)
            total_bytes = sum(path.stat().st_size for path in folder.rglob("*") if path.is_file())
            self.assertLess(total_bytes, 1024 * 1024, "sparse basis fixture exceeds 1 MiB")
            print(f"SIMION_NATIVE_SPARSE_BASIS PASS ids=1,3 zero_basis=2 fixture_bytes={total_bytes}")
        self.assertFalse(folder.exists(), "test-owned temporary files were not cleaned")


if __name__ == "__main__":
    unittest.main()
