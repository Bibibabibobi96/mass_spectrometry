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
from unittest.mock import patch

from common.simion.collision_hs1 import adapt_hs1_for_repeat_fly
from common.contracts.particle_count_policy import POLICY_PATH
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
    config["native_timing"] = functional.derive_native_timing(config["baseline"])
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
            ("pre_extraction", config["native_timing"]["primary_quench_us"], g["lp_center_mm"]),
        ):
            rows.append({**initial, "event": name, "t_us": time, "x_mm": x,
                         "y_mm": 0, "z_mm": 0, "vx_mm_us": 0,
                         "vy_mm_us": 0, "vz_mm_us": 0})
        # Construct an explicit 4000 eV fixture independent of source spread;
        # this prescribed state is never presented as solver dynamics.
        speed = math.sqrt(2*4000*1.602176634e-19/(state["mass_amu"]*1.66053906660e-27))/1000
        exit_row = {**initial, "event": "extraction_exit", "reason": "acceptance_surface",
                    "t_us": s["extraction_start_us"] + 1, "x_mm": g["lp_center_mm"],
                    "y_mm": g["extraction_end_y_mm"], "z_mm": 0,
                    "vx_mm_us": 0, "vy_mm_us": speed, "vz_mm_us": 0}
        rows.extend([exit_row, {**exit_row, "event": "terminal"}])
    return rows


class FunctionalContractTests(unittest.TestCase):
    def test_current_author_inputs_require_explicit_shield_aperture(self) -> None:
        config = load_config()
        del config["baseline"]["native_geometry"]["shield_extraction_slit_width_mm"]
        with self.assertRaisesRegex(ValueError, "explicit shield extraction aperture"):
            functional.validate_configs(config)

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

    def test_native_timing_aligns_both_switches_and_preserves_lift_end(self) -> None:
        baseline = copy.deepcopy(self.config["baseline"])
        baseline["electric"]["rf_quench_alignment"] = "next_cosine_zero"
        timing = functional.derive_native_timing(baseline)
        self.assertAlmostEqual(timing["primary_quench_us"], 7500 + .25/3.7, places=9)
        self.assertAlmostEqual(timing["pulse_start_us"], 7500 + .75/3.7, places=9)
        self.assertGreater(timing["primary_quench_us"], baseline["schedule"]["lift_end_us"])
        self.assertEqual(timing["pulse_start_us"], timing["side_quench_us"])
        for phase in (0, .7, -.9):
            b = copy.deepcopy(baseline)
            b["clock"]["rf_phase_rad"] = phase
            for frequency in (3.7e6, 2.1e6):
                b["electric"]["rf_frequency_hz"] = frequency
                result = functional.derive_native_timing(b)
                for key in ("primary_quench_us", "side_quench_us"):
                    angle = 2*math.pi*frequency*1e-6*result[key]+phase
                    self.assertLess(abs(math.cos(angle)), 1e-9)

    def test_native_timing_zero_roundoff_and_invalid_resolved_times(self) -> None:
        b = copy.deepcopy(self.config["baseline"])
        b["electric"]["rf_quench_alignment"] = "next_cosine_zero"
        zero = functional.derive_native_timing(b)["primary_quench_us"]
        b["schedule"]["extraction_start_us"] = zero
        self.assertEqual(functional.derive_native_timing(b)["primary_quench_us"], zero)
        for offset in (-1e-6, 1e-6):
            b["schedule"]["extraction_start_us"] = zero + offset
            result = functional.derive_native_timing(b)
            self.assertGreaterEqual(result["primary_quench_us"], zero + offset)
            self.assertAlmostEqual(result["primary_quench_us"], zero if offset < 0 else zero+.5/3.7)
        b["electric"]["rf_quench_delay_cycles"] = .3
        with self.assertRaisesRegex(ValueError, "half-cycles"):
            functional.derive_native_timing(b)
        b = copy.deepcopy(self.config["baseline"])
        b["schedule"]["terminal_us"] = zero + .01
        with self.assertRaisesRegex(ValueError, "precede terminal"):
            functional.derive_native_timing(b)
        self.config["native_timing"]["primary_quench_us"] += .01
        with self.assertRaisesRegex(ValueError, "native timing differs"):
            functional.validate_configs(self.config)

    def test_requested_time_policy_keeps_authored_clock_and_arbitrary_positive_delay(self) -> None:
        b = copy.deepcopy(self.config["baseline"])
        b["electric"]["rf_quench_alignment"] = "requested_time"
        b["electric"]["rf_quench_delay_cycles"] = .3
        b["clock"]["rf_phase_rad"] = .7
        result = functional.derive_native_timing(b)
        self.assertEqual(result["policy"], "requested_instrument_time_v1")
        self.assertEqual(result["primary_quench_us"], b["schedule"]["extraction_start_us"])
        self.assertEqual(result["alignment_roundoff_us"], 0)
        self.assertAlmostEqual(result["pulse_start_us"], result["primary_quench_us"]+.3/3.7)
        for invalid in ("unknown", False, 1, [], {}):
            c = copy.deepcopy(self.config)
            c["baseline"]["electric"]["rf_quench_alignment"] = invalid
            with self.assertRaisesRegex(ValueError, "rf_quench_alignment"):
                functional.validate_configs(c)

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
        adapted = adapt_hs1_for_repeat_fly(original)
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
        adapted = adapt_hs1_for_repeat_fly(HS1_SOURCE_FIXTURE)
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
                adapt_hs1_for_repeat_fly(HS1_SOURCE_FIXTURE.replace("adjustable " + name, "local " + name))
        with self.assertRaisesRegex(ValueError, "already contains"):
            adapt_hs1_for_repeat_fly(adapt_hs1_for_repeat_fly(HS1_SOURCE_FIXTURE))

    def test_hs1_adapter_rejects_unsupported_source_structures(self) -> None:
        declarations = ("local max_timestep", "local is_initialized", "local ke_averages",
                        "local last_collision_times", "local trace_count")
        for declaration in declarations:
            with self.subTest(missing=declaration):
                with self.assertRaisesRegex(ValueError, "missing"):
                    adapt_hs1_for_repeat_fly(HS1_SOURCE_FIXTURE.replace(declaration, "local changed", 1))
        for returns in ("", "return HS1\nreturn HS1"):
            with self.subTest(returns=returns):
                with self.assertRaisesRegex(ValueError, "return structure"):
                    adapt_hs1_for_repeat_fly(HS1_SOURCE_FIXTURE.replace("return HS1", returns))

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
        policy = repo / "common/contracts" / POLICY_PATH.name
        policy.parent.mkdir(parents=True)
        shutil.copyfile(POLICY_PATH, policy)
        schema = Path("common/contracts/schemas/simion_batch_continuation.schema.json")
        (repo / schema).parent.mkdir(parents=True)
        shutil.copyfile(PROJECT.parents[1] / schema, repo / schema)
        shutil.copyfile(PROJECT.parents[1] / "common/host_resource_policy.json", repo / "common/host_resource_policy.json")
        for relative in ("common/contracts/artifact_retention.json",
                         "common/contracts/schemas/canonical_clock_authority.schema.json"):
            target = repo / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PROJECT.parents[1] / relative, target)
        for name in ("baseline", "numerics", "source", "acceptance", "native_operating_point"):
            value = self.config[name]
            functional.write_json(project / "config" / f"{name}.json", value)
        for name in ("diagnostics", "field_diagnostics"):
            functional.write_json(project / "config" / f"{name}.json",
                                  functional.read_json(PROJECT / "config" / f"{name}.json"))
        shutil.copyfile(PROJECT / "config/source_parameter_sources.json", project / "config/source_parameter_sources.json")
        functional.write_json(project / "config/source_exploration.json",
                              functional.read_json(PROJECT / "config/source_exploration.json"))
        for name in ("runtime.lua", "native_drive.lua", "build_workbench.lua", "probe_native_field.lua", "extraction_force_audit.lua"):
            (project / "simion" / name).write_text("-- inert copy fixture\n", encoding="utf-8")
        vendor = Path(self.temporary.name) / "vendor_copy_fixture"
        fixture_paths = [repo / "common/simion/rf_drive.lua",
                         repo / "common/simion/voltage_waveforms.lua",
                         repo / "common/simion/scientific_event_csv.lua",
                         repo / "common/paths/native_run_path.lua",
                         repo / "common/simion/assets/iob_instance_seeds/1_instance_seed.iob",
                         repo / "common/simion/assets/iob_instance_seeds/iob_seed_placeholder_01.pa0",
                         vendor / "examples/collision_hs1/collision_hs1.lua"]
        for path in fixture_paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("inert copy fixture\n", encoding="utf-8")
        (vendor / "examples/collision_hs1/collision_hs1.lua").write_text(HS1_SOURCE_FIXTURE, encoding="utf-8")
        functional.write_json(self.run / "run_config.json", {"schema_version": 1})
        return project, vendor

    def test_external_candidate_configuration_uses_explicit_voltage_geometry_and_frame(self) -> None:
        project, vendor = self.make_prepare_fixture()
        candidate = Path(self.temporary.name) / "candidate_inputs"
        shutil.copytree(project / "config", candidate)
        baseline = functional.read_json(candidate / "baseline.json")
        baseline["geometry"]["lp_length_mm"] = 61.5
        baseline["electric"]["lift_v"] = 4480.043790844389
        functional.write_json(candidate / "baseline.json", baseline)
        point = functional.read_json(candidate / "native_operating_point.json")
        point["lift_v"] = baseline["electric"]["lift_v"]
        functional.write_json(candidate / "native_operating_point.json", point)
        shutil.copyfile(PROJECT / "config/coordinate_transform.json", candidate / "coordinate_transform.json")
        original = (project / "config/baseline.json").read_bytes()
        functional.prepare(self.run, project, vendor, configuration_directory=candidate)
        frozen = functional.read_json(self.run / "inputs/resolved_model.json")
        self.assertEqual(frozen["baseline"]["geometry"]["lp_length_mm"], 61.5)
        self.assertEqual(frozen["native_operating_point"]["lift_v"], 4480.043790844389)
        self.assertEqual((project / "config/baseline.json").read_bytes(), original)
        self.assertEqual(functional.read_json(self.run / "run_config.json")["parameters"]["configuration_directory"], str(candidate.resolve()))

    def test_external_configuration_does_not_fall_back_to_project_transform(self) -> None:
        project, vendor = self.make_prepare_fixture()
        with self.assertRaisesRegex(ValueError, "explicit coordinate"):
            functional.prepare(self.run, project, vendor, configuration_directory=project / "config")

    def test_loaded_source_aliases_freeze_once_without_test_dependencies(self) -> None:
        _, vendor = self.make_prepare_fixture()
        with patch.dict(sys.modules, dict(
                ip_functional_alias= functional,
                ip_test_alias=sys.modules[__name__])):
            # Prove prepare admits the helper before its loaded-source snapshot,
            # even when another test has not already imported the analysis.
            for name in ("population_moments", "plane_crossings", "particle_census",
                         "beam_focus_diagnostics", "figure_export"):
                sys.modules.pop(f"common.analysis.{name}", None)
            functional.prepare(self.run, PROJECT, vendor)
        code = self.run / 'inputs/code'
        frozen = code / 'projects/dual_pressure_rectilinear_ion_processor/analysis/functional.py'
        self.assertEqual(frozen.read_bytes(), Path(functional.__file__).read_bytes())
        self.assertTrue((code / 'common/simion/collision_hs1.py').is_file())
        self.assertFalse((code / 'projects/dual_pressure_rectilinear_ion_processor/tests/test_functional.py').exists())
        self.assertEqual((code / 'common/contracts/rigid_transform.py').read_bytes(),
                         (PROJECT.parents[1] / 'common/contracts/rigid_transform.py').read_bytes())
        population_program = (
            "import json, pathlib, sys; "
            "sys.path.insert(0, sys.argv[1]); "
            "from common.analysis import population_moments as m; "
            "assert pathlib.Path(m.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve()); "
            "print(json.dumps(m.population_pair_moments([0., 2.], [3., 1.])))"
        )
        figure_program = """
import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
from common.analysis import figure_export as export
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
assert pathlib.Path(export.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve())
figure=Figure(figsize=(2.,1.)); FigureCanvasAgg(figure)
figure.subplots().plot([0,1],[0,1])
records=export.export_figures({pathlib.Path(sys.argv[2])/'frozen':figure},
                            formats=('png','svg'),dpi=80.,facecolor='white')
assert all(pathlib.Path(row['path']).stat().st_size==row['bytes']>0 for row in records)
assert all(row['savefig_dpi']==80. and row['size_inches']==[2.,1.] for row in records)
print(json.dumps([row['format'] for row in records]))
"""
        figure_output = Path(self.temporary.name)/'frozen figures'
        figure_output.mkdir()
        beam_program = """
import json, math, pathlib, sys
sys.path.insert(0, sys.argv[1])
from common.analysis import beam_focus_diagnostics as beam
assert pathlib.Path(beam.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve())
rows = [dict(particle_id=pid, plane_z_mm=0., status='alive', t_us=time,
             x_mm=x, y_mm=0., z_mm=0., vx_mm_us=0., vy_mm_us=0., vz_mm_us=-1.)
        for pid, time, x in ((7, 1., 0.), (19, 3., 2.))]
case = dict(label='frozen', sources={7: {}, 19: {}}, exits={7: {}, 19: {}},
            particle_weights={7: 1., 19: 3.}, states=rows)
prepared = beam.prepare_focus_diagnostics([case], [0.], [7, 19])
row = next(r for r in prepared['plane_statistics'] if r['cohort']=='common_extracted_ids')
assert math.isclose(row['sigma_x_mm'], math.sqrt(.75))
assert row['mean_x_mm']==1.5 and row['weight_sum']==4.
assert row['available_ids']==[7,19]
print(json.dumps(dict(version=prepared['schema_version'], effective=row['effective_sample_count'])))
"""
        census_program = """
import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
from common.analysis import particle_census as c
from projects.dual_pressure_rectilinear_ion_processor.analysis.diagnostics import census
assert pathlib.Path(c.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve())
row = dict(t_us=0., kinetic_energy_ev=0., x_mm=0., y_mm=0., z_mm=0.,
           vx_mm_us=0., vy_mm_us=0., vz_mm_us=0.)
data = dict(config=dict(baseline=dict(geometry={})), sources={7: row},
            terminals={}, tracks={7: [row]}, times={7: [0.]}, census_weights=None)
counts, rows = census(data, 1.)
assert rows[0]["reason"] == "missing_bracket"
print(json.dumps(dict(unknown=counts["unknown"], alive=counts["alive"],
                     count=counts["source_count"], version=counts["census_schema_version"])))
"""
        crossing_program = """
import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
from common.analysis import plane_crossings as c
from common.contracts.rigid_transform import PhaseSpaceState, PlaneSurface
assert pathlib.Path(c.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1]).resolve())
samples = [c.CrossingSample(7, 2, PhaseSpaceState('f', (0., 0., 2.), (0., 0., -1000.), 10.)),
           c.CrossingSample(7, 'exit', PhaseSpaceState('f', (0., 0., 0.), (0., 0., -1000.), 10.5))]
rows = list(c.iter_bounded_plane_crossings(samples, particle_ids=[7],
    planes={'middle': PlaneSurface('f', (0., 0., 1.), (0., 0., -1.))},
    minimum_time_us=10., maximum_gap_us=.5, gap_tolerance_us=1e-12))
assert len(rows) == 1
print(json.dumps(dict(alpha=rows[0].interpolation_alpha, lower=rows[0].lower_anchor,
                     upper=rows[0].upper_anchor, version=rows[0].schema_version)))
"""
        # Delete population last: the beam probe must first exercise that dependency.
        cases = (
            ('figure_export', figure_program, ['png', 'svg'], [str(figure_output)]),
            ('beam_focus_diagnostics', beam_program, dict(version=2, effective=1.6), []),
            ('particle_census', census_program, dict(unknown=1, alive=0, count=1, version=1), []),
            ('plane_crossings', crossing_program, dict(alpha=.5, lower=2, upper='exit', version=1), []),
            ('population_moments', population_program,
             dict(variance_first=1., variance_second=1., covariance=-1., correlation=-1.), []),
        )
        for name, program, expected, extra_args in cases:
            with self.subTest(module=name):
                helper = code / f'common/analysis/{name}.py'
                self.assertEqual(helper.read_bytes(),
                                 (PROJECT.parents[1] / f'common/analysis/{name}.py').read_bytes())
                # -I excludes editable repository/cwd and PYTHONPATH import fallback.
                command = [sys.executable, '-B', '-I', '-c', program, str(code), *extra_args]
                detached = subprocess.run(command, cwd=self.temporary.name, capture_output=True, text=True,
                                          encoding='utf-8', timeout=60, check=True)
                self.assertEqual(json.loads(detached.stdout), expected)
                helper.unlink()
                refused = subprocess.run(command, cwd=self.temporary.name, capture_output=True, text=True,
                                         encoding='utf-8', timeout=60)
                self.assertNotEqual(refused.returncode, 0)
                self.assertIn(name, refused.stderr)

    def test_prepare_preserves_source_identity_in_fly2_projection(self) -> None:
        """Synthetic source files test copying only; no vendor code is executed."""
        project, vendor = self.make_prepare_fixture()
        functional.prepare(self.run, project, vendor)
        audit=functional.read_json(self.run/"inputs/resolved_model.json")["extraction_force_audit"]
        self.assertEqual(audit["schema_version"],1)
        self.assertEqual(audit["role"],"native_extraction_force_audit")
        self.assertEqual(audit["field_basis_count"],15)
        self.assertEqual(audit["start_reference"],"native_timing.primary_quench_us")
        self.assertEqual(audit["step_state_scope"],"actual_pre_and_post_HS1")
        self.assertEqual(audit["integration"],"Hermite_composite_Simpson_5_vs_3")
        self.assertEqual((self.run/"simion/extraction_force_audit.lua").read_bytes(),
                         (project/"simion/extraction_force_audit.lua").read_bytes())
        self.assertEqual(functional.read_json(self.run/"inputs/source_parameter_sources.json"),
                         functional.read_json(PROJECT/"config/source_parameter_sources.json"))
        self.assertEqual(functional.read_json(self.run/"inputs/native_timing.json"),
                         functional.read_json(self.run/"inputs/resolved_model.json")["native_timing"])
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
            expected_energy=functional.kinetic_energy_ev(state["mass_amu"],*(state[key] for key in ("vx_m_s","vy_m_s","vz_m_s")))
            self.assertAlmostEqual(energy, expected_energy, places=10)
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
                         adapt_hs1_for_repeat_fly(HS1_SOURCE_FIXTURE))
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

    def test_frozen_closure_performs_actual_prepare_without_active_source_fallback(self) -> None:
        _, vendor = self.make_prepare_fixture()
        functional.prepare(self.run, PROJECT, vendor)
        closure = self.run / "inputs/code"
        detached = Path(self.temporary.name)/"detached"
        for name in ("inputs","simion","results"):(detached/name).mkdir(parents=True)
        functional.write_json(detached/"run_config.json", {"schema_version":1})
        from common.contracts.frozen_inputs import freeze_file
        freeze_file(PROJECT/"config/runtime_profiles.json",detached/"inputs/runtime_profiles.json")
        code = """from pathlib import Path
import sys
from projects.dual_pressure_rectilinear_ion_processor.analysis import functional
closure,run,vendor=map(Path,sys.argv[1:4])
Path(functional.__file__).resolve().relative_to(closure.resolve())
project=closure/'projects/dual_pressure_rectilinear_ion_processor'
functional.prepare(run,project,vendor)
assert (run/'simion/native_run_path.lua').is_file()
assert (run/'simion/iob_seed/1_instance_seed.iob').is_file()
assert (run/'simion/iob_seed/iob_seed_placeholder_01.pa0').is_file()
assert not (run/'simion/processor.iob').exists()
# Existing inert template fixture tests metadata/copy wiring only, never vendor IOB validity.
from common.simion.particle_batching import plan_single_wave_batches
from projects.dual_pressure_rectilinear_ion_processor.analysis import batching
import shutil
shutil.copyfile(run/'simion/runtime.lua',run/'simion/processor.lua')
plan=plan_single_wave_batches(100,2)
plan_path=run/'inputs/test_batch_plan.json'
functional.write_json(plan_path,plan)
for batch in plan['batches']:
    folder=run/('simion_batch_%04d'%batch['index']);folder.mkdir()
    (folder/'processor.iob').write_bytes(b'INERT_ONLY_NOT_NATIVE_IOB')
result=batching.materialize_batches(run,plan_path)
for batch in plan['batches']:
    target=run/('simion_batch_%04d'%batch['index'])/'scientific_event_csv.lua'
    assert target.read_bytes()==(run/'simion/scientific_event_csv.lua').read_bytes()
print('FROZEN_ACTUAL_PREPARE=PASS NATIVE=0 TASKS=2 IOB=INERT_TEST_FIXTURE')
"""
        result=subprocess.run([sys.executable,'-B','-s','-c',code,str(closure),str(detached),str(vendor)],cwd=detached,
            env={**os.environ,'PYTHONPATH':str(closure),'PYTHONNOUSERSITE':'1'},capture_output=True,text=True,encoding='utf-8',timeout=45)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('FROZEN_ACTUAL_PREPARE=PASS',result.stdout)
        self.assertEqual((self.run/'simion/processor.gem').read_bytes(),(detached/'simion/processor.gem').read_bytes())
        self.assertEqual((self.run/'inputs/release.csv').read_bytes(),(detached/'inputs/release.csv').read_bytes())

    def test_frozen_closure_loads_particle_count_policy_in_independent_python(self) -> None:
        # Use the real loaded repository closure but inert vendor input. A fresh
        # interpreter cannot benefit from this unittest process's import cache.
        _, vendor = self.make_prepare_fixture()
        functional.prepare(self.run, PROJECT, vendor)
        closure = self.run / "inputs/code"
        frozen_policy = closure / "common/contracts" / POLICY_PATH.name
        self.assertEqual(frozen_policy.read_bytes(), POLICY_PATH.read_bytes())
        code = ("from common.contracts import particle_count_policy as p; "
                "print(p.POLICY_PATH.resolve()); "
                "assert p.validate_standard_particle_count(100) == 100; "
                "from common.contracts.frozen_inputs import freeze_file; "
                "from pathlib import Path; "
                "frozen = freeze_file(p.POLICY_PATH, Path('isolated_policy.json')); "
                "assert frozen['source_path'] == str(p.POLICY_PATH.resolve()); "
                "from common.simion import resource_scheduler, resource_profile, particle_batching; "
                "assert resource_profile.PROFILE_ROLE == 'simion_resource_profile'; "
                "from projects.dual_pressure_rectilinear_ion_processor.analysis import batching; "
                "completion = batching.require_one_fly_completion(['status,Fly completed. 10 splats, 2.19 seconds']); "
                "assert completion.splats == 10 and completion.elapsed_seconds == 2.19; "
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
        self.assertIn(str(closure / "common/simion/native_completion.py"), config["inputs"].values())
        resolved = functional.read_json(self.run / "inputs/resolved_model.json")
        self.assertEqual(resolved["numerical_boundaries"], {
            "schema_version": 2, "role": "native_numerical_observation_boundaries",
            "upstream_exit_x_mm": -1.9, "downstream_exit_x_mm": 211.25,
            "classification": "numerical_observation_not_metal"})
        self.assertEqual(resolved["native_projection"], functional.native_projection(
            self.config["baseline"], self.config["numerics"]))

    def downstream_fixture(self) -> list[dict]:
        """Use synthetic states to test a local numerical exit, never a metal hit."""
        projection = functional.native_projection(self.config["baseline"], self.config["numerics"])
        self.config["native_projection"] = projection
        self.config["numerical_boundaries"] = functional.derive_numerical_boundaries(projection)
        transfer = self.config["baseline"]["schedule"]["transfer_end_us"]
        rows = [row for row in event_fixture(self.config)
                if row["particle_id"] != 1 or row["t_us"] <= transfer]
        rows.append(dict(particle_id=1, event="terminal", reason="downstream_domain_exit",
                         t_us=transfer+100, x_mm=211.25, y_mm=0, z_mm=0,
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
                    rows[-1]["t_us"] = self.config["baseline"]["schedule"]["transfer_end_us"]
                self.write_events(rows)
                with self.assertRaisesRegex(ValueError, "downstream"):
                    functional.analyze(self.run)

    def test_downstream_derivation_rejects_lens_outside_domain(self) -> None:
        projection = functional.native_projection(self.config["baseline"], self.config["numerics"])
        projection["maximum_mm"][0] = 210.5
        with self.assertRaisesRegex(ValueError, "after lens and inside PA"):
            functional.derive_numerical_boundaries(projection)

    def test_observation_schema_requires_active_upstream_but_preserves_explicit_recorded_contract(self) -> None:
        projection = functional.native_projection(self.config["baseline"], self.config["numerics"])
        boundaries = functional.derive_numerical_boundaries(projection)
        self.assertEqual(boundaries["upstream_exit_x_mm"], projection["origin_mm"][0]+projection["grid_mm"])
        functional.validate_numerical_boundaries(boundaries, projection)
        legacy = {key: boundaries[key] for key in ("downstream_exit_x_mm", "classification")}
        with self.assertRaisesRegex(ValueError, "derived authority"):
            functional.validate_numerical_boundaries(legacy, projection)
        functional.validate_numerical_boundaries(legacy, projection, recorded=True)
        for malformed in ({**legacy,"downstream_exit_x_mm":0}, {**legacy,"schema_version":1},
                          {**boundaries,"upstream_exit_x_mm":projection["origin_mm"][0]}):
            with self.subTest(malformed=malformed), self.assertRaisesRegex(ValueError,"derived authority"):
                functional.validate_numerical_boundaries(malformed, projection, recorded=True)

    def test_prepare_refuses_birth_on_internal_upstream_observation(self) -> None:
        project, vendor = self.make_prepare_fixture()
        source = functional.read_json(project / "config/source.json")
        source["geometry"]["center_mm"][0] = -1.9
        functional.write_json(project / "config/source.json", source)
        with self.assertRaisesRegex(ValueError, "strictly inside the upstream"):
            functional.prepare(self.run, project, vendor)

    def test_upstream_exit_validates_derived_inside_plane_and_negative_direction(self) -> None:
        for mutation in (None, "position", "velocity", "missing", "event"):
            with self.subTest(mutation=mutation):
                rows = self.downstream_fixture()
                rows[-1].update(reason="backward_escape", x_mm=self.config["numerical_boundaries"]["upstream_exit_x_mm"], vx_mm_us=-1)
                if mutation=="position": rows[-1]["x_mm"]-=0.01
                elif mutation=="velocity": rows[-1]["vx_mm_us"]=1
                elif mutation=="missing": self.config.pop("numerical_boundaries")
                elif mutation=="event":
                    rows[-1]["event"]="transfer"
                    rows[-1]["t_us"]=self.config["baseline"]["schedule"]["transfer_end_us"]
                self.write_events(rows)
                if mutation is None:
                    self.assertEqual(functional.analyze(self.run)["terminal_reasons"]["backward_escape"],1)
                else:
                    with self.assertRaisesRegex(ValueError,"upstream"):
                        functional.analyze(self.run)

    def test_prepare_exploration_freezes_selected_profile_and_source(self) -> None:
        project, vendor = self.make_prepare_fixture()
        functional.prepare(self.run, project, vendor, source_profile="exploration")
        schema = Path("common/contracts/schemas/simion_batch_continuation.schema.json")
        self.assertEqual((self.run / "inputs/code" / schema).read_bytes(),
                         (PROJECT.parents[1] / schema).read_bytes())
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

    def test_analyze_preserves_timeout_unknown_and_observed_escape_separately(self) -> None:
        rows = event_fixture(self.config)
        replacements = {1: "timeout", 2: "solver_stop", 3: "unknown", 4: "radial_escape"}
        selected = []
        for row in rows:
            particle = row["particle_id"]
            if particle in replacements and row["event"] == "extraction_exit":
                continue
            if particle == 4 and row["event"] not in {"source", "terminal"}:
                continue
            if particle in replacements and row["event"] == "terminal":
                row = {**row, "reason": replacements[particle],
                       "t_us": 20 if particle == 4 else self.config["baseline"]["schedule"]["terminal_us"],
                       "y_mm": self.config["baseline"]["geometry"]["boundary_radius_mm"] + 1 if particle == 4 else 0,
                       "z_mm": 0, "vx_mm_us": 0, "vy_mm_us": 0, "vz_mm_us": 0}
            selected.append(row)
        self.write_events(selected)
        result = functional.analyze(self.run)
        with (self.run / "results/particle_state.csv").open(encoding="utf-8", newline="") as stream:
            canonical = list(csv.DictReader(stream))
        terminal = {int(row["particle_id"]): row for row in canonical if row["event"] == "terminal"}
        self.assertEqual([terminal[i]["status"] for i in range(1, 6)],
                         ["timeout", "unknown", "unknown", "lost", "transmitted"])
        self.assertEqual([terminal[i]["terminal_reason"] for i in range(1, 5)],
                         ["timeout", "solver_stop", "unknown", "radial_escape"])
        self.assertEqual(len(terminal), self.config["source"]["particle_count"])
        self.assertTrue(all(row["status"] == "alive" for row in canonical if row["event"] == "source"))
        self.assertEqual(result["actual_particle_count"], 100)
        self.assertEqual(result["capture_fraction"], .99)
        self.assertEqual(result["extraction_fraction"], .96)
        self.assertEqual(result["terminal_reasons"]["solver_stop"], 1)

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


class NativeFieldReferenceTests(unittest.TestCase):
    def test_source_projection_and_child_publication_reference_owner_without_payload_rereads(self) -> None:
        from common.contracts import verify_run_manifest, write_run_manifest
        from projects.dual_pressure_rectilinear_ion_processor.analysis import batching
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / "20261029_120000__test__simion__field-owner-fixture"
            child = root / "20261029_120001__test__simion__field-consumer-fixture"
            model = {"native_projection": {"electrode_ids": list(range(1, 16))},
                     "numerics": {"refine_convergence_v": 1e-5}}
            for run in (parent, child):
                for directory in ("inputs", "simion", "logs"):
                    (run / directory).mkdir(parents=True, exist_ok=True)
                (run / "simion/processor.gem").write_text("inert geometry fixture\n", encoding="utf-8")
            functional.write_json(parent / "inputs/resolved_model.json", model)
            functional.write_json(parent / "inputs/numerics.json", model["numerics"])
            (parent / "logs/refine.log").write_text("Fast adjust Refining completed\n", encoding="utf-8")
            family = [parent / "simion" / ("processor.pa" + suffix)
                      for suffix in ["#", *map(str, range(16)), "-surf"]]
            for path in family:
                path.write_bytes(b"inert native payload fixture")
            functional.write_json(parent / "run_config.json", dict(run_id=parent.name, project=functional.PROJECT,
                mode="native_electrode_functional", inputs={str(index): str(parent / relative) for index, relative in
                enumerate(("inputs/resolved_model.json", "inputs/numerics.json", "simion/processor.gem"))}))
            write_run_manifest.publish_run_manifest(parent / "run_config.json", "success",
                output_paths=[*family, parent / "logs/refine.log"])
            actual_hash = write_run_manifest.file_sha256
            actual_subprocess = functional.subprocess.run

            def no_payload_hash(path: Path) -> str:
                self.assertNotIn(Path(path).resolve(), family, "PA identity was read outside its immutable owner guard")
                return actual_hash(path)

            def projected_verifier(arguments: list[str], **options: object) -> subprocess.CompletedProcess:
                self.assertFalse(any(str(path) in arguments for path in family), "projection reselected the guarded payload")
                return actual_subprocess(arguments, **options)

            with patch.object(functional, "file_sha256", side_effect=no_payload_hash), \
                 patch.object(functional.subprocess, "run", side_effect=projected_verifier), \
                 patch.object(write_run_manifest, "file_sha256", side_effect=no_payload_hash):
                external = functional._native_field_binding(child, copy.deepcopy(model), parent, PROJECT.parents[1])
                self.assertEqual(set(external), {"native_field_manifest", "native_field_consumption"})
                consumption = json.loads((child / "inputs/native_field_consumption.json").read_text())
                self.assertEqual(len(consumption["family_records"]), len(family))
                self.assertEqual(consumption["payload_validation"], "launcher_immutable_source_guard_required_before_native_use")
                functional.write_json(child / "run_config.json", dict(run_id=child.name, project=functional.PROJECT,
                    mode="native_electrode_functional", inputs=external))
                manifest = batching.publish_manifest(child, "success")
                self.assertFalse({Path(record["path"]).resolve() for record in manifest["inputs"].values()} & set(family))
                with patch.object(sys, "argv", ["verify_run_manifest", str(child / "run_manifest.json"),
                        "--require-status", "success", "--require-project", functional.PROJECT]):
                    verify_run_manifest.main()
            (parent / ".run_terminal_publication.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(subprocess.CalledProcessError):
                functional._native_field_binding(child, copy.deepcopy(model), parent, PROJECT.parents[1])


if __name__ == "__main__":
    unittest.main()
