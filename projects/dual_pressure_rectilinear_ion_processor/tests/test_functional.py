"""Solver-free contracts for preparation and synthetic event normalization.

Synthetic events exercise validation and acceptance arithmetic; they are not
particle simulations or evidence for the device's physical performance.
"""

from __future__ import annotations

import copy
import csv
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from common.ion_release.release import generate_release_states
from projects.dual_pressure_rectilinear_ion_processor.analysis import functional


PROJECT = Path(__file__).resolve().parents[1]
RAW_COLUMNS = ["particle_id", "event", "reason", "t_us", "x_mm", "y_mm", "z_mm",
               "vx_mm_us", "vy_mm_us", "vz_mm_us"]
HS1_SOURCE_FIXTURE = """-- Inert source-shape fixture; not the official collision algorithm.
local HS1 = {segment={}}
adjustable _gas_mass_amu = 4
adjustable _temperature_k = 273
adjustable _pressure_pa = 0.53
adjustable _sigma_m2 = 2.27e-18
adjustable _mean_free_path_mm = -1
adjustable _steps_per_MFP = 20
adjustable _random_seed = 1
adjustable _mark_collisions = 1
adjustable _trace_level = 0
local max_timestep
local is_initialized = false
local ke_averages = {}
local last_collision_times = {}
local trace_count = 0
local function unchanged_collision_body(vx, vy, vz)
    -- Sentinel arithmetic is deliberately nonphysical and must stay unchanged.
    return vx + vy * vz
end
HS1.fixture_body = unchanged_collision_body
return HS1
"""


def load_config() -> dict:
    """Load the same current scientific inputs as the public prepare boundary."""
    config = {name: functional.read_json(PROJECT / "config" / f"{name}.json")
              for name in ("baseline", "numerics", "source", "acceptance", "native_operating_point")}
    config["source_profile"] = "functional"
    return config


def event_fixture(config: dict) -> list[dict]:
    """Construct explicit synthetic event rows with exact shared source states."""
    b = config["baseline"]
    g, s = b["geometry"], b["schedule"]
    rows = []
    for state in generate_release_states(config["source"]):
        initial = dict(particle_id=state["particle_id"], event="source", reason="none",
                       t_us=0, x_mm=state["x_mm"], y_mm=state["y_mm"], z_mm=state["z_mm"],
                       vx_mm_us=state["vx_m_s"] / 1000, vy_mm_us=state["vy_m_s"] / 1000,
                       vz_mm_us=state["vz_m_s"] / 1000)
        rows.append(initial)
        for name, time, x in (
            ("hp_enter", 100, g["guide_length_mm"]),
            ("capture", s["capture_end_us"], g["hp_center_mm"]),
            ("transfer", s["transfer_end_us"], g["lp_center_mm"]),
            ("pre_extraction", s["extraction_start_us"], g["lp_center_mm"]),
        ):
            rows.append({**initial, "event": name, "t_us": time, "x_mm": x,
                         "y_mm": 0, "z_mm": 0, "vx_mm_us": 0,
                         "vy_mm_us": 0, "vz_mm_us": 0})
        # Source energy is 5 eV, so multiplying the source speed by sqrt(800)
        # independently constructs a 4000 eV fixture without solver dynamics.
        speed = abs(initial["vx_mm_us"]) * (4000 / 5) ** 0.5
        exit_row = {**initial, "event": "extraction_exit", "reason": "acceptance_surface",
                    "t_us": s["extraction_start_us"] + 1, "x_mm": g["lp_center_mm"],
                    "y_mm": g["extraction_end_y_mm"], "z_mm": 0,
                    "vx_mm_us": 0, "vy_mm_us": speed, "vz_mm_us": 0}
        rows.extend([exit_row, {**exit_row, "event": "terminal"}])
    return rows


class FunctionalContractTests(unittest.TestCase):
    """Exercise current configuration, frozen projections, and full source IDs."""

    def setUp(self) -> None:
        self.config = load_config()
        self.temporary = tempfile.TemporaryDirectory(prefix="ion_processor_contract_test_")
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name) / "run"
        for name in ("inputs", "simion", "results"):
            (self.run / name).mkdir(parents=True, exist_ok=True)

    def write_events(self, rows: list[dict]) -> None:
        """Materialize only the documented raw CSV boundary for the analyzer."""
        functional.write_json(self.run / "inputs/resolved_model.json", self.config)
        with (self.run / "simion/events.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=RAW_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

    def test_validate_current_config(self) -> None:
        functional.validate_configs(self.config)

    def test_functional_profile_rejects_small_cohort(self) -> None:
        self.config["source"]["particle_count"] = 10
        with self.assertRaisesRegex(ValueError, "standard particle count"):
            functional.validate_configs(self.config)
        self.write_events(event_fixture(self.config))
        with self.assertRaisesRegex(ValueError, "standard particle count"):
            functional.analyze(self.run)

    def test_exploration_is_exact_common_source_prefix(self) -> None:
        exploration = functional.read_json(PROJECT / "config/source_exploration.json")
        self.assertEqual(self.config["source"]["particle_count"], 100)
        self.assertEqual(exploration["particle_count"], 10)
        self.assertEqual(exploration["mother_particle_count"], 100)
        normalized = {**exploration, "particle_count": self.config["source"]["particle_count"]}
        self.assertEqual(normalized, self.config["source"])
        self.assertEqual(generate_release_states(exploration),
                         generate_release_states(self.config["source"])[:10])

    def test_exploration_analysis_never_claims_functional_pass(self) -> None:
        self.config["source"] = functional.read_json(PROJECT / "config/source_exploration.json")
        self.config["source_profile"] = "exploration"
        functional.validate_configs(self.config)
        rows = event_fixture(self.config)
        self.write_events(rows)
        result = functional.analyze(self.run)
        self.assertEqual(result["functional_status"], "exploration_pass")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["source_profile"], "exploration")
        self.assertFalse(result["functional_baseline_eligible"])
        self.assertEqual(result["actual_particle_count"], 10)
        for row in rows:
            if row["event"] in {"extraction_exit", "terminal"}:
                row["vy_mm_us"] *= 0.9
        self.write_events(rows)
        result = functional.analyze(self.run)
        self.assertEqual(result["functional_status"], "exploration_incomplete")
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["checks"]["extraction_energy"])

    def test_hs1_adapter_preserves_original_body_and_adds_only_lifetime_hook(self) -> None:
        original = HS1_SOURCE_FIXTURE
        adapted = functional.adapt_hs1_for_repeat_fly(original)
        before_return, after_return = original.split("return HS1")
        marker = "-- Project lifecycle adapter: no change to collision equations or sampling."
        self.assertTrue(adapted.startswith(before_return + marker))
        self.assertTrue(adapted.endswith("return HS1" + after_return))
        # The complete input prefix includes every original declaration and body;
        # exact string equality prevents changing equations or sampling code.
        self.assertEqual(adapted.split(marker, 1)[0], before_return)
        self.assertEqual(adapted.count("function HS1.reset_run_state()"), 1)
        for statement in ("is_initialized = false", "max_timestep = nil", "ke_averages = {}",
                          "last_collision_times = {}", "trace_count = 0"):
            self.assertIn(statement, adapted[len(before_return):])

    def test_hs1_bound_getter_is_read_only_and_in_original_module_scope(self) -> None:
        adapted = functional.adapt_hs1_for_repeat_fly(HS1_SOURCE_FIXTURE)
        self.assertEqual(adapted.count("function HS1.bound_parameters()"), 1)
        getter = adapted.split("function HS1.bound_parameters()", 1)[1].split("\nend", 1)[0]
        expected = {
            "gas_mass_amu": "_gas_mass_amu", "temperature_k": "_temperature_k",
            "pressure_pa": "_pressure_pa", "sigma_m2": "_sigma_m2",
            "mean_free_path_mm": "_mean_free_path_mm", "steps_per_mfp": "_steps_per_MFP",
            "random_seed": "_random_seed", "mark_collisions": "_mark_collisions",
            "trace_level": "_trace_level",
        }
        assignments = dict(re.findall(r"(?m)^        (\w+) = (\w+),$", getter))
        self.assertEqual(assignments, expected)
        self.assertEqual(getter.strip().splitlines()[0], "return {")
        self.assertEqual(len(getter.strip().splitlines()), len(expected) + 2)
        # The getter is inserted before the original module return, after all
        # adjustable declarations. These source-shape checks do not claim native
        # SIMION binding proof; the separate actual getter audit owns that claim.
        for name in expected.values():
            self.assertLess(adapted.index("adjustable " + name), adapted.index("function HS1.bound_parameters()"))
        self.assertLess(adapted.index("function HS1.bound_parameters()"), adapted.rindex("return HS1"))

    def test_hs1_bound_getter_rejects_missing_or_pre_adapted_source(self) -> None:
        for name in ("_gas_mass_amu", "_temperature_k", "_pressure_pa", "_sigma_m2",
                     "_mean_free_path_mm", "_steps_per_MFP", "_random_seed", "_mark_collisions", "_trace_level"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "bound parameter declaration missing"):
                functional.adapt_hs1_for_repeat_fly(HS1_SOURCE_FIXTURE.replace("adjustable " + name, "local " + name))
        with self.assertRaisesRegex(ValueError, "already contains"):
            functional.adapt_hs1_for_repeat_fly(functional.adapt_hs1_for_repeat_fly(HS1_SOURCE_FIXTURE))

    def test_hs1_adapter_rejects_unsupported_source_structures(self) -> None:
        declarations = ("local max_timestep", "local is_initialized", "local ke_averages",
                        "local last_collision_times", "local trace_count")
        for declaration in declarations:
            with self.subTest(missing=declaration):
                with self.assertRaisesRegex(ValueError, "missing"):
                    functional.adapt_hs1_for_repeat_fly(HS1_SOURCE_FIXTURE.replace(declaration, "local changed", 1))
        for returns in ("", "return HS1\nreturn HS1"):
            with self.subTest(returns=returns):
                with self.assertRaisesRegex(ValueError, "return structure"):
                    functional.adapt_hs1_for_repeat_fly(HS1_SOURCE_FIXTURE.replace("return HS1", returns))

    def test_validate_rejects_invalid_scientific_inputs(self) -> None:
        mutations = [
            ("RNG policy", lambda c: c["numerics"].update(collision_rng_policy="shared")),
            ("boolean seed", lambda c: c["numerics"].update(seed=True)),
            ("zero seed", lambda c: c["numerics"].update(seed=0)),
            ("overflow global seed", lambda c: c["numerics"].update(seed=2**31-2)),
            ("unordered clock", lambda c: c["baseline"]["schedule"].update(transfer_end_us=100)),
            ("source frame", lambda c: c["source"].update(frame_id="another_frame")),
            ("birth clock", lambda c: c["source"].update(common_time_of_birth_s=1)),
            ("epoch", lambda c: c["baseline"]["clock"].update(epoch_us=1)),
            ("NaN", lambda c: c["baseline"]["electric"].update(lift_v=float("nan"))),
            ("missing geometry", lambda c: c["baseline"]["geometry"].pop("r0_mm")),
            ("unknown physics", lambda c: c["baseline"]["electric"].update(secret_voltage=1)),
            ("insufficient RF resolution", lambda c: c["numerics"].update(dt_us=1)),
            ("inverted acceptance range", lambda c: c["acceptance"].update(minimum_extraction_mean_energy_ev=9000)),
            ("native voltage NaN", lambda c: c["native_operating_point"].update(lift_v=float("nan"))),
            ("native geometry missing", lambda c: c["baseline"]["native_geometry"].pop("guide_rod_radius_mm")),
        ]
        for label, mutate in mutations:
            with self.subTest(label=label):
                config = copy.deepcopy(self.config)
                mutate(config)
                with self.assertRaises((ValueError, AssertionError, KeyError)):
                    functional.validate_configs(config)

    def make_prepare_fixture(self) -> tuple[Path, Path]:
        """Create inert source-copy inputs, without executing vendor code."""
        repo = Path(self.temporary.name) / "fixture_repo"
        project = repo / "projects" / functional.PROJECT
        (project / "config").mkdir(parents=True)
        (project / "simion").mkdir()
        policy = repo / "common/contracts" / functional.POLICY_PATH.name
        policy.parent.mkdir(parents=True)
        shutil.copyfile(functional.POLICY_PATH, policy)
        shutil.copyfile(PROJECT.parents[1] / "common/host_resource_policy.json", repo / "common/host_resource_policy.json")
        for name in ("baseline", "numerics", "source", "acceptance", "native_operating_point"):
            value = self.config[name]
            functional.write_json(project / "config" / f"{name}.json", value)
        for name in ("diagnostics", "field_diagnostics"):
            functional.write_json(project / "config" / f"{name}.json",
                                  functional.read_json(PROJECT / "config" / f"{name}.json"))
        functional.write_json(project / "config/source_exploration.json",
                              functional.read_json(PROJECT / "config/source_exploration.json"))
        for name in ("runtime.lua", "native_drive.lua", "build_workbench.lua", "probe_native_field.lua"):
            (project / "simion" / name).write_text("-- inert copy fixture\n", encoding="utf-8")
        vendor = Path(self.temporary.name) / "vendor_copy_fixture"
        fixture_paths = [repo / "common/multipole/simion_rf_drive.lua",
                         repo / "common/simion/assets/iob_instance_seeds/1_instance_seed.iob",
                         vendor / "examples/collision_hs1/collision_hs1.lua"]
        for path in fixture_paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("inert copy fixture\n", encoding="utf-8")
        (vendor / "examples/collision_hs1/collision_hs1.lua").write_text(HS1_SOURCE_FIXTURE, encoding="utf-8")
        functional.write_json(self.run / "run_config.json", {"schema_version": 1})
        return project, vendor

    def test_prepare_preserves_source_identity_in_fly2_projection(self) -> None:
        """Synthetic source files test copying only; no vendor code is executed."""
        project, vendor = self.make_prepare_fixture()
        functional.prepare(self.run, project, vendor)
        fly2 = (self.run / "simion/processor.fly2").read_text(encoding="utf-8")
        positions = re.findall(r"position = vector\(([^)]+)\)", fly2)
        directions = re.findall(r"direction = vector\(([^)]+)\)", fly2)
        energies = [float(value) for value in re.findall(r"ke = ([^,]+),", fly2)]
        states = generate_release_states(self.config["source"])
        self.assertEqual(len(positions), len(states))
        self.assertEqual(len(directions), len(states))
        self.assertEqual(len(energies), len(states))
        for state, position, direction, energy in zip(states, positions, directions, energies):
            for value, name in zip(map(float, position.split(",")), ("x_mm", "y_mm", "z_mm")):
                self.assertAlmostEqual(value, state[name], places=12)
            for value, name in zip(map(float, direction.split(",")), ("vx_m_s", "vy_m_s", "vz_m_s")):
                self.assertAlmostEqual(value, state[name], places=9)
            self.assertAlmostEqual(energy, 5, places=10)
        with (self.run / "inputs/release.csv").open(encoding="utf-8", newline="") as handle:
            released = list(csv.DictReader(handle))
        self.assertEqual([int(row["particle_id"]) for row in released],
                         [state["particle_id"] for state in states])
        config = json.loads((self.run / "run_config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["parameters"]["actual_particle_count"], len(states))
        self.assertEqual(config["parameters"]["workflow"], "native_electrode_functional")
        self.assertTrue((self.run / "simion/processor.gem").is_file())
        self.assertEqual((self.run / "inputs/collision_hs1_original.lua").read_text(encoding="utf-8"),
                         HS1_SOURCE_FIXTURE)
        self.assertEqual((self.run / "simion/collision_hs1.lua").read_text(encoding="utf-8"),
                         functional.adapt_hs1_for_repeat_fly(HS1_SOURCE_FIXTURE))
        adapter = functional.read_json(self.run / "inputs/collision_adapter.json")
        self.assertFalse(adapter["algorithm_changed"])
        self.assertEqual(adapter["role"], "hs1_repeat_fly_lifecycle_adapter")
        self.assertEqual(adapter["adapter_hooks"], ["reset_run_state", "bound_parameters"])
        self.assertTrue(adapter["bound_parameters_read_only"])

    def test_project_frame_preparation_rotates_source_without_resampling(self) -> None:
        project, vendor = self.make_prepare_fixture()
        contract = functional.read_json(PROJECT / "config/coordinate_transform.json")
        functional.write_json(project / "config/coordinate_transform.json", contract)
        functional.prepare(self.run, project, vendor)
        resolved = functional.read_json(self.run / "inputs/resolved_model.json")
        self.assertEqual(resolved["coordinate_transform"], contract)
        fly2 = (self.run / "simion/processor.fly2").read_text(encoding="utf-8")
        positions = re.findall(r"position = vector\(([^)]+)\)", fly2)
        directions = re.findall(r"direction = vector\(([^)]+)\)", fly2)
        for state, position, direction in zip(generate_release_states(self.config["source"]), positions, directions):
            actual_p = tuple(map(float, position.split(",")))
            actual_v = tuple(map(float, direction.split(",")))
            expected_p = (-state["z_mm"], state["x_mm"], 9.8-state["y_mm"])
            expected_v = (-state["vz_m_s"], state["vx_m_s"], -state["vy_m_s"])
            for actual, expected in zip((*actual_p, *actual_v), (*expected_p, *expected_v)):
                self.assertAlmostEqual(actual, expected, places=9)
            self.assertAlmostEqual(sum(v*v for v in actual_v), sum(state[k]**2 for k in ("vx_m_s", "vy_m_s", "vz_m_s")), places=7)
        companion = (self.run / "simion/source_states.lua").read_text(encoding="utf-8")
        self.assertIn('x=1', companion.replace(' ', ''))
        self.assertEqual(functional.read_json(self.run / "inputs/source.json"), self.config["source"])

    def test_rotated_analysis_uses_world_canonical_and_local_occupation(self) -> None:
        rows = event_fixture(self.config)
        self.config["coordinate_transform"] = functional.read_json(PROJECT / "config/coordinate_transform.json")
        for row in rows:
            if row["event"] == "pre_extraction":
                row["x_mm"] += 0.5 if row["particle_id"] % 2 else -0.5
            x, y, z = (row[k] for k in ("x_mm", "y_mm", "z_mm"))
            vx, vy, vz = (row[k] for k in ("vx_mm_us", "vy_mm_us", "vz_mm_us"))
            row.update(x_mm=-z, y_mm=x, z_mm=9.8-y, vx_mm_us=-vz, vy_mm_us=vx, vz_mm_us=-vy)
        self.write_events(rows)
        result = functional.analyze(self.run)
        self.assertEqual(result["functional_status"], "functional_pass")
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["checks"]["lp_occupation"])
        self.assertEqual(result["frame_id"], self.config["coordinate_transform"]["to_frame_id"])
        self.assertEqual(result["metrics"]["pre_extraction"]["slow_sigma_y_mm"], 0.5)
        with (self.run / "results/particle_state.csv").open(encoding="utf-8", newline="") as handle:
            canonical = list(csv.DictReader(handle))
        source = canonical[0]
        self.assertAlmostEqual(float(source["transverse_y_mm"]), 1)
        self.assertGreater(float(source["velocity_y_m_s"]), 0)
        self.assertAlmostEqual(float(source["radial_position_mm"]), math.hypot(float(source["transverse_x_mm"]), 1))
        self.assertAlmostEqual(float(source["divergence_angle_deg"]), 90)
        self.assertIn("not a world-origin cylinder", result["canonical_column_semantics"]["max_rod_radius_mm"])
        self.assertEqual(result["native_acceptance_domain"]["boundary_radius_mm"], self.config["baseline"]["geometry"]["boundary_radius_mm"])
        exit_row = next(r for r in canonical if r["event"] == "extraction_exit")
        self.assertAlmostEqual(float(exit_row["axial_z_mm"]), 0)
        self.assertLess(float(exit_row["velocity_axial_m_s"]), 0)
        self.assertAlmostEqual(float(exit_row["radial_position_mm"]), self.config["baseline"]["geometry"]["lp_center_mm"])
        self.assertAlmostEqual(float(exit_row["divergence_angle_deg"]), 0)
        self.assertGreater(float(exit_row["radial_position_mm"]), float(exit_row["max_rod_radius_mm"]))
        # A false world-Z-based occupancy would reject every capture at z~9.8.
        for row in rows:
            if row["event"] == "capture":
                row["y_mm"] = 170
        self.write_events(rows)
        self.assertFalse(functional.analyze(self.run)["checks"]["capture_fraction"])

    def test_frozen_closure_loads_particle_count_policy_in_independent_python(self) -> None:
        # Use the real loaded repository closure but inert vendor input. A fresh
        # interpreter cannot benefit from this unittest process's import cache.
        _, vendor = self.make_prepare_fixture()
        functional.prepare(self.run, PROJECT, vendor)
        closure = self.run / "inputs/code"
        frozen_policy = closure / "common/contracts" / functional.POLICY_PATH.name
        self.assertEqual(frozen_policy.read_bytes(), functional.POLICY_PATH.read_bytes())
        code = ("from common.contracts import particle_count_policy as p; "
                "print(p.POLICY_PATH.resolve()); "
                "assert p.validate_standard_particle_count(100) == 100; "
                "from common.simion import resource_scheduler, resource_profile, particle_batching; "
                "assert resource_profile.PROFILE_ROLE == 'simion_resource_profile'; "
                "print('FROZEN_POLICY_PASS')")
        env = {**os.environ, "PYTHONPATH": str(closure), "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=self.run,
                                env=env, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(str(frozen_policy.resolve()), result.stdout)
        self.assertIn("FROZEN_POLICY_PASS", result.stdout)
        config = functional.read_json(self.run / "run_config.json")
        self.assertIn(str(frozen_policy), config["inputs"].values())
        resolved = functional.read_json(self.run / "inputs/resolved_model.json")
        self.assertEqual(resolved["numerical_boundaries"], {
            "downstream_exit_x_mm": 211.25, "classification": "numerical_observation_not_metal"})
        self.assertEqual(resolved["native_projection"], functional.native_projection(
            self.config["baseline"], self.config["numerics"]))

    def downstream_fixture(self) -> list[dict]:
        """Use synthetic states to test a local numerical exit, never a metal hit."""
        projection = functional.native_projection(self.config["baseline"], self.config["numerics"])
        self.config["native_projection"] = projection
        self.config["numerical_boundaries"] = functional.derive_numerical_boundaries(projection)
        rows = [row for row in event_fixture(self.config)
                if row["particle_id"] != 1 or row["t_us"] <= 4000]
        rows.append(dict(particle_id=1, event="terminal", reason="downstream_domain_exit",
                         t_us=4100, x_mm=211.25, y_mm=0, z_mm=0,
                         vx_mm_us=1, vy_mm_us=0, vz_mm_us=0))
        return rows

    def test_downstream_exit_validates_local_plane_with_world_coordinates(self) -> None:
        rows = self.downstream_fixture()
        self.config["coordinate_transform"] = functional.read_json(PROJECT / "config/coordinate_transform.json")
        for row in rows:
            x, y, z = (row[k] for k in ("x_mm", "y_mm", "z_mm"))
            vx, vy, vz = (row[k] for k in ("vx_mm_us", "vy_mm_us", "vz_mm_us"))
            row.update(x_mm=-z, y_mm=x, z_mm=9.8-y, vx_mm_us=-vz, vy_mm_us=vx, vz_mm_us=-vy)
        self.write_events(rows)
        result = functional.analyze(self.run)
        self.assertEqual(result["terminal_reasons"]["downstream_domain_exit"], 1)
        self.assertEqual(result["identity_validation"]["status"], "PASS")
        self.assertNotIn("downstream_domain_exit", functional.ENUMS["terminal_reason"])

    def test_downstream_exit_rejects_false_plane_direction_and_missing_authority(self) -> None:
        for mutation in ("position", "velocity", "missing", "unbound", "event"):
            with self.subTest(mutation=mutation):
                rows = self.downstream_fixture()
                if mutation == "position":
                    rows[-1]["x_mm"] += 0.01
                elif mutation == "velocity":
                    rows[-1]["vx_mm_us"] = -1
                elif mutation == "missing":
                    self.config.pop("numerical_boundaries")
                elif mutation == "unbound":
                    self.config["numerical_boundaries"]["downstream_exit_x_mm"] += 0.01
                else:
                    rows[-1]["event"] = "transfer"
                    rows[-1]["t_us"] = 4000
                self.write_events(rows)
                with self.assertRaisesRegex(ValueError, "downstream"):
                    functional.analyze(self.run)

    def test_downstream_derivation_rejects_lens_outside_domain(self) -> None:
        projection = functional.native_projection(self.config["baseline"], self.config["numerics"])
        projection["maximum_mm"][0] = 210.5
        with self.assertRaisesRegex(ValueError, "after lens and inside PA"):
            functional.derive_numerical_boundaries(projection)

    def test_prepare_exploration_freezes_selected_profile_and_source(self) -> None:
        project, vendor = self.make_prepare_fixture()
        functional.prepare(self.run, project, vendor, source_profile="exploration")
        resolved = functional.read_json(self.run / "inputs/resolved_model.json")
        config = functional.read_json(self.run / "run_config.json")
        expected = functional.read_json(PROJECT / "config/source_exploration.json")
        self.assertEqual(resolved["source_profile"], "exploration")
        self.assertEqual(resolved["source_authority_file"], "source_exploration.json")
        self.assertEqual(resolved["source"], expected)
        self.assertEqual(functional.read_json(self.run / "inputs/source.json"), expected)
        self.assertEqual(config["parameters"]["source_profile"], "exploration")
        self.assertEqual(config["parameters"]["actual_particle_count"], 10)
        self.assertEqual(config["parameters"]["source_authority_file"], "source_exploration.json")

    def test_analyze_accepts_complete_synthetic_cohort(self) -> None:
        self.write_events(event_fixture(self.config))
        result = functional.analyze(self.run)
        self.assertEqual(result["identity_validation"]["status"], "PASS")
        self.assertEqual(result["actual_particle_count"], self.config["source"]["particle_count"])
        self.assertEqual(result["capture_fraction"], 1)
        self.assertEqual(result["extraction_fraction"], 1)
        self.assertEqual(result["functional_status"], "functional_pass")
        self.assertEqual(result["status"], "success")
        self.assertAlmostEqual(result["metrics"]["extraction_exit"]["mean_kinetic_energy_ev"],
                               4000, places=8)

    def test_analyze_rejects_missing_terminal(self) -> None:
        rows = event_fixture(self.config)
        rows.pop()
        self.write_events(rows)
        with self.assertRaisesRegex(AssertionError, "lacks source or terminal"):
            functional.analyze(self.run)

    def test_analyze_rejects_duplicate_particle_event(self) -> None:
        rows = event_fixture(self.config)
        rows.append(copy.deepcopy(rows[-1]))
        self.write_events(rows)
        with self.assertRaisesRegex(AssertionError, "duplicate event"):
            functional.analyze(self.run)

    def test_analyze_rejects_changed_source_identity(self) -> None:
        rows = event_fixture(self.config)
        rows[0]["x_mm"] += 0.01
        self.write_events(rows)
        with self.assertRaisesRegex(AssertionError, "source axial_z_mm"):
            functional.analyze(self.run)

    def test_analyze_rejects_foreign_particle_id(self) -> None:
        rows = event_fixture(self.config)
        for row in rows:
            if row["particle_id"] == 1:
                row["particle_id"] = 999999
        self.write_events(rows)
        with self.assertRaisesRegex(AssertionError, "particle IDs"):
            functional.analyze(self.run)

    def test_analyze_rejects_event_outside_stage_clock(self) -> None:
        rows = event_fixture(self.config)
        next(row for row in rows if row["event"] == "capture")["t_us"] = 0
        self.write_events(rows)
        with self.assertRaises((ValueError, AssertionError)):
            functional.analyze(self.run)

    def test_analyze_rejects_exit_off_acceptance_plane(self) -> None:
        rows = event_fixture(self.config)
        next(row for row in rows if row["event"] == "extraction_exit")["y_mm"] = 0
        self.write_events(rows)
        with self.assertRaises((ValueError, AssertionError)):
            functional.analyze(self.run)

    def test_analyze_rejects_nonfinite_raw_state(self) -> None:
        rows = event_fixture(self.config)
        next(row for row in rows if row["event"] == "capture")["x_mm"] = float("nan")
        self.write_events(rows)
        with self.assertRaises((ValueError, AssertionError)):
            functional.analyze(self.run)


if __name__ == "__main__":
    unittest.main()
