"""Public, solver-independent reflectron study analysis and author compilation."""

from contextlib import contextmanager
import copy
import math
import json
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from msplatform.analysis.reflectron_compensation import compare_resolutions, compile_compensated_study
from msplatform.analysis.reflectron_voltage_fit import compile_fit_parameters


class ReflectronCompensationAnalysisTests(unittest.TestCase):
    def test_retired_compensation_controllers_are_absent(self):
        import importlib.util
        self.assertIsNone(importlib.util.find_spec('msplatform.workflows.oa_candidate.run_compensation'))
        self.assertIsNone(importlib.util.find_spec('msplatform.backends.simion.optimize_reflectron_ring_voltages'))

    def test_compensated_study_changes_only_verified_ring_drives(self):
        study = {"drive": {"groups": {"tof": {
            "reflectron_midgrid": {"kind": "static", "voltage_v": 20.0},
            "reflectron_backplate": {"kind": "static", "voltage_v": 40.0},
            "reflectron_stage1_ring_1": {"kind": "static", "voltage_v": 10.0},
            "reflectron_stage2_ring_1": {"kind": "static", "voltage_v": 30.0}}}},
            "release": {"particle_ids": [1, 2]}}
        fit = {"role": "oatof_reflectron_monotone_axis_field_voltage_fit", "status": "success",
            "fixed_endpoints_V": {"entrance": 0, "midgrid": 20, "backplate": 40, "shield": 0},
            "stage1_count": 1, "stage2_count": 1,
            "baseline_stage1_ring_voltages_V": [10.0], "baseline_stage2_ring_voltages_V": [30.0],
            "stage1_ring_voltages_V": [11.0], "stage2_ring_voltages_V": [31.0]}
        before = copy.deepcopy(study)
        result = compile_compensated_study(study, instance_id="tof", fit=fit)
        self.assertEqual(study, before)
        self.assertEqual(result["release"], before["release"])
        groups = result["drive"]["groups"]["tof"]
        self.assertEqual(groups["reflectron_stage1_ring_1"]["voltage_v"], 11.0)
        self.assertEqual(groups["reflectron_stage2_ring_1"]["voltage_v"], 31.0)
        self.assertEqual(groups["reflectron_midgrid"], before["drive"]["groups"]["tof"]["reflectron_midgrid"])
        for key, bad in (("stage1_ring_voltages_V", [21]), ("baseline_stage2_ring_voltages_V", [29])):
            broken = copy.deepcopy(fit); broken[key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                compile_compensated_study(study, instance_id="tof", fit=broken)

    def test_public_compensation_author_resolves_real_study_and_preserves_cohort(self):
        from msplatform.recipes import load_recipe
        from msplatform.workflows.reflectron_compensation import write_compensated_author
        examples = Path(__file__).resolve().parents[2] / "src/msplatform/examples"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("oa_split_tof_native_small_v1.toml", "oa_split_tof_native_small_v1.json"):
                (root / name).write_bytes((examples / name).read_bytes())
            original = load_recipe(root / "oa_split_tof_native_small_v1.toml").to_dict()
            document = original["study"]["document"]
            groups = document["drive"]["groups"]["tof"]
            fit = {"role": "oatof_reflectron_monotone_axis_field_voltage_fit", "status": "success",
                "fixed_endpoints_V": {"entrance": 0, "shield": 0,
                    "midgrid": groups["reflectron_midgrid"]["voltage_v"],
                    "backplate": groups["reflectron_backplate"]["voltage_v"]}}
            for stage, count in ((1, 10), (2, 5)):
                values = [groups[f"reflectron_stage{stage}_ring_{i}"]["voltage_v"] for i in range(1, count + 1)]
                fit[f"stage{stage}_count"] = count
                fit[f"baseline_stage{stage}_ring_voltages_V"] = values
                fit[f"stage{stage}_ring_voltages_V"] = [values[0] + 1, *values[1:]]
            result = write_compensated_author(root / "oa_split_tof_native_small_v1.toml", instance_id="tof", fit=fit,
                                              recipe_name="compensated.toml", study_name="compensated.json")
            new = load_recipe(result["recipe_path"]).to_dict()
            self.assertNotEqual(new["recipe_id"], original["recipe_id"])
            self.assertEqual(new["study"]["document"]["release"], document["release"])
            self.assertEqual(new["study"]["document"]["drive"]["clock"], document["drive"]["clock"])
            self.assertEqual(json.loads(Path(result["study_path"]).read_text(encoding="utf-8")),
                             new["study"]["document"])
            with self.assertRaises(FileExistsError):
                write_compensated_author(root / "oa_split_tof_native_small_v1.toml", instance_id="tof", fit=fit,
                                         recipe_name="compensated.toml", study_name="compensated.json")
            from msplatform.results.artifacts import OpenedArtifact
            from msplatform.workflows.native_tracing import compile_simion_model
            from msplatform.workflows.reflectron_compensation import prepare_compensated_author
            model_id = compile_simion_model(original).document['model_identity_sha256']
            reference = {"manifest": {"path": str(root / "axis_manifest.json")}, "product_id": "axis"}
            def sample(identity):
                return OpenedArtifact(kind="axis_response_samples", product_id="axis", reference=reference,
                    metadata={"binding": {"model_identity_sha256": identity, "field_reference": {"id": "fixture"}}},
                    records={}, paths={}, producer={})
            @contextmanager
            def guard(_reference, **_kwargs):
                yield selected[0]
            selected = [sample("WRONG")]
            with patch("msplatform.execution.native_source_guard.guard_native_source", guard), \
                 patch("msplatform.backends.simion.reflectron_response_binding.fit_sampled_axis", return_value=fit):
                with self.assertRaisesRegex(ValueError, "model differs"):
                    prepare_compensated_author(root / "oa_split_tof_native_small_v1.toml", selected[0],
                        instance_id="tof", recipe_name="verified.toml", study_name="verified.json",
                        context=SimpleNamespace(workspace=root), artifact_store=object())
                selected[0] = sample(model_id)
                verified = prepare_compensated_author(root / "oa_split_tof_native_small_v1.toml", selected[0],
                    instance_id="tof", recipe_name="verified.toml", study_name="verified.json",
                    context=SimpleNamespace(workspace=root), artifact_store=object())
                evidence = json.loads(Path(verified["fit_provenance_path"]).read_text(encoding="utf-8"))
                self.assertEqual(evidence["original_model_identity_sha256"], model_id)
                self.assertEqual(evidence["axis_samples_reference"], reference)
                cases = load_recipe(verified["recipe_path"]).to_dict()["recording"]["field_interventions"]
                self.assertEqual(cases, [{"id":"compensated","selector":"real"},
                                         {"id":"ideal_reflectron","selector":"ideal:reflectron.full"}])
                resolved_verified = load_recipe(verified["recipe_path"]).to_dict()
                self.assertIn("compensation_provenance.json", resolved_verified["resource_snapshots"])
                provenance_path = Path(verified["fit_provenance_path"])
                provenance_path.write_text("tampered", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "provenance differs"):
                    load_recipe(verified["recipe_path"])

    def test_recorded_comparison_requires_complete_observation_and_same_births(self):
        from msplatform.workflows.reflectron_compensation import compare_compensated_runs
        initial = [{"particle_id": i, "species_id": "ion", "time_s": 0.0, "weight": 1.0} for i in range(1, 21)]
        def recorded(scale):
            return {"execution_status": "succeeded", "data_integrity": {"status": "complete",
                    "detector_observation": {"status": "complete"}}, "initial_states": initial,
                    "metadata": {"frame_id": "frame", "clock": {"basis": "experiment_relative"}},
                    "events": [{"particle_id": i, "event_kind": "detector", "surface_id": "detector",
                                "time_s": (50 + ((i % 7) - 3) * scale) * 1e-6} for i in range(1, 21)]}
        rows = {"before": recorded(1), "after/cases/0000": recorded(0.5), "after/cases/0001": recorded(0.25)}
        class Store:
            def __init__(self, _root): pass
            def run_status(self, _id): return {"publication_status": "ready"}
            def inspect_run(self, run_id): return Path(run_id)
        kwargs = dict(artifact_root="unused", baseline_run_id="before", compensated_run_id="after",
                      species_id="ion", detector_surface_id="detector", nominal_mass_da=100.0)
        collection = {"summary": {"cases": [{"id": "compensated", "selector": "real"},
                         {"id": "ideal_reflectron", "selector": "ideal:reflectron.full"}]}}
        with patch("msplatform.storage.ArtifactStore", Store), \
             patch("msplatform.workflows.tracing.inspect_results", return_value=collection), \
             patch("msplatform.results.particle_data.read_particle_data", side_effect=lambda key: rows[Path(key).as_posix()]):
            result = compare_compensated_runs(**kwargs)
            self.assertGreater(result["resolution_gain_ratio"], 1)
            ideal_events = rows["after/cases/0001"]["events"]
            rows["after/cases/0001"]["events"] = []
            no_ideal = compare_compensated_runs(**kwargs)
            self.assertGreater(no_ideal["resolution_gain_ratio"], 1)
            self.assertIsNone(no_ideal["remaining_gap_ratio_to_ideal_reflectron"])
            rows["after/cases/0001"]["events"] = ideal_events
            saved_events = rows["after/cases/0000"]["events"]
            for count in (0, 1):
                rows["after/cases/0000"]["events"] = saved_events[:count]
                limited = compare_compensated_runs(**kwargs)
                self.assertIsNone(limited["resolution_gain_ratio"])
                self.assertEqual(limited["compensated"]["status"], "unavailable")
                self.assertEqual(limited["compensated"]["detected_particles"], count)
            rows["after/cases/0000"]["events"] = saved_events
            rows["after/cases/0000"]["data_integrity"]["detector_observation"]["status"] = "unavailable"
            with self.assertRaisesRegex(ValueError, "complete native detector observation"):
                compare_compensated_runs(**kwargs)

    def test_recovery_uses_explicit_native_stage_without_invoking_flight(self):
        from msplatform.workflows.reflectron_compensation import recover_compensation_stage
        store, context = object(), object()
        with patch("msplatform.execution.owner.recover_managed_native_store_stage", return_value=True) as recover:
            result = recover_compensation_stage(artifact_store=store, native_stage_asset_id="asset123", context=context)
            recover.assert_called_once_with(store, "asset123", context=context)
        self.assertTrue(result["recovered"])
        with self.assertRaisesRegex(ValueError, "exact native stage"):
            recover_compensation_stage(artifact_store=store, native_stage_asset_id="", context=context)

    def test_study_orchestration_calls_public_runner_after_author_preflight(self):
        from msplatform.workflows.reflectron_compensation import run_compensation_study
        store = SimpleNamespace(root=Path("store"), high=10000, low=5000, safety=100,
                                run_status=lambda _id: {"publication_status": "ready"},
                                inspect_run=lambda _id: Path("baseline"))
        options = dict(baseline_run_id="baseline", instance_id="tof", recipe_name="new.toml", study_name="new.json",
                       species_id="ion", detector_surface_id="detector", nominal_mass_da=100,
                       context=object(), artifact_store=store, reserve_bytes=1024)
        baseline = {"execution_status": "succeeded", "data_integrity": {"status": "complete",
                    "detector_observation": {"status": "complete"}}, "initial_states": [{"species_id": "ion"}]}
        with patch("msplatform.results.particle_data.read_particle_data", return_value=baseline), \
             patch("msplatform.workflows.reflectron_compensation.prepare_compensated_author",
                   return_value={"recipe_path": "new.toml", "fit_provenance_sha256": "fixture"}) as author, \
             patch("msplatform.workflows.tracing.run_recipe", return_value={"run_id": "newrun"}) as run, \
             patch("msplatform.workflows.reflectron_compensation.compare_compensated_runs",
                   return_value={"resolution_gain_ratio": 1.2}) as compare:
            result = run_compensation_study("old.toml", object(), **options)
            self.assertEqual(result["comparison"]["resolution_gain_ratio"], 1.2)
            run.assert_called_once_with("new.toml", artifact_root=store.root, high_water_bytes=10000,
                                        low_water_bytes=5000, safety_bytes=100, reserve_bytes=1024,
                                        source_revision=None, context=options["context"])
            self.assertEqual(compare.call_args.kwargs["baseline_run_id"], "baseline")
            self.assertEqual(compare.call_args.kwargs["compensated_run_id"], "newrun")
            self.assertEqual(author.call_count, 1)
        bad = dict(options, reserve_bytes=0)
        with self.assertRaisesRegex(ValueError, "reservation"):
            run_compensation_study("old.toml", object(), **bad)

    def test_ideal_full_selector_keeps_axial_selector_distinct(self):
        from msplatform.contracts.field_intervention import resolve_field_selector
        self.assertEqual(resolve_field_selector("ideal:reflectron.ez"), {"A": 0, "D": 0, "S1": 1, "S2": 1})
        self.assertEqual(resolve_field_selector("ideal:reflectron.full"),
                         {"A": 0, "D": 0, "S1": 0, "S2": 0, "S1_FULL": 1, "S2_FULL": 1})
        with self.assertRaises(ValueError):
            resolve_field_selector("ideal:reflectron.full+drift.ez")

    def test_three_arm_resolution_and_unavailable_metrics(self):
        def arms(a, b, c):
            return {name: {"canonical_peak_metrics": {"mass_resolution": value}} for name, value in
                    zip(("baseline", "compensated", "ideal_reflectron"), (a, b, c), strict=True)}
        self.assertEqual(compare_resolutions(arms(10, 15, 20)),
                         {"scientific_result": "resolution_gain", "resolution_gain_ratio": 1.5,
                          "remaining_gap_ratio_to_ideal_reflectron": 0.25})
        self.assertEqual(compare_resolutions(arms(10, 10, 20))["scientific_result"], "no_resolution_gain")
        for values in ((None, 1, 2), (0, 1, 2), (1, math.nan, 2), (1, 2, 0)):
            with self.subTest(values=values):
                result = compare_resolutions(arms(*values))
                self.assertEqual(result["scientific_result"], "INCONCLUSIVE")
                self.assertIsNone(result["resolution_gain_ratio"])
                self.assertIsNone(result["remaining_gap_ratio_to_ideal_reflectron"])

    def test_fit_uses_only_frozen_geometry_and_explicit_regularization(self):
        contract = {"rings": {"stage1_count": 2, "stage2_count": 3},
                    "geometry_mm": {"L_stage1": 25, "L_stage2": 30},
                    "electrodes_V": {"midgrid": 3000, "backplate": 5000}}
        before = copy.deepcopy(contract)
        result = compile_fit_parameters(contract, 0.125)
        self.assertEqual(result, {"stage1_count": 2, "stage2_count": 3, "stage1_length_mm": 25.0,
                                  "stage2_length_mm": 30.0, "midgrid_voltage_v": 3000.0,
                                  "backplate_voltage_v": 5000.0, "regularization": 0.125})
        self.assertEqual(contract, before)
        for changed in (0, -1, 1.5, True):
            invalid = copy.deepcopy(before)
            invalid["rings"]["stage1_count"] = changed
            with self.subTest(count=changed), self.assertRaises(ValueError):
                compile_fit_parameters(invalid, 0.125)
        for changed in (-1, math.nan, math.inf, True):
            with self.subTest(regularization=changed), self.assertRaises(ValueError):
                compile_fit_parameters(before, changed)
        for section, key, invalid_value in (("geometry_mm", "L_stage1", 0),
                                            ("geometry_mm", "L_stage2", math.inf),
                                            ("electrodes_V", "midgrid", math.nan)):
            invalid = copy.deepcopy(before)
            invalid[section][key] = invalid_value
            with self.subTest(section=section, key=key), self.assertRaises(ValueError):
                compile_fit_parameters(invalid, 0.125)
        del contract["electrodes_V"]["midgrid"]
        with self.assertRaises(KeyError):
            compile_fit_parameters(contract, 0.125)


if __name__ == "__main__":
    unittest.main()
