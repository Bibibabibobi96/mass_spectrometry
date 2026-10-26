"""Pure frozen-metadata preparation; inert identity fixtures are not solutions."""
from __future__ import annotations

import copy
import csv
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.particle_physics import AMU_KG, kinetic_energy_ev
from common.contracts.write_run_manifest import build_run_manifest, file_record
from integrations.tests import test_paired_accelerator_static_field_execute as static_tests
from integrations.runtime import paired_accelerator_model
from integrations.runtime.single_flight_source import GLOBAL_COLUMNS
from integrations.workflows.paired_accelerator_static_field import runtime
from integrations.workflows.paired_accelerator_pulse.prepare import prepare


ROOT = Path(__file__).resolve().parents[2]


class PairedPulsePreparationTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, dict, Path, Path]:
        static, _ = static_tests.PairedStaticExecutionTests().prepared(root)
        plan = runtime.prepare_run(static)
        model = static / "comsol/paired_accelerator_static.mph"
        model.write_bytes(b"INERT MODEL IDENTITY FIXTURE; NOT A COMSOL MODEL")
        backend = Path("projects") / runtime.PROJECT / "comsol/build_and_export_paired_accelerator_field.m"
        target = static / "inputs/runtime_snapshot" / backend
        target.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / backend, target)
        solution = static / "comsol/comsol_field_solution.json"
        runtime.write(solution, dict(schema_version=1, role="oatof_paired_accelerator_static_field_solution",
            status="solved_saved", solution_present=True, solution_tag="sol1", plan_path=str(static / "inputs/bvp/paired_accelerator_static_field_plan.json"), model_path=str(model)))
        publication = static / "results/simion_field_publication.json"
        runtime.write(publication, dict(status="published", action_required="complete", cache_key="ORIGINAL_FIXTURE_FIELD",
            generation_directory=str(root / "original_public_field")))
        runtime.write(static / "run_config.json", dict(schema_version=1, project="instrument_assembly",
            mode="paired_accelerator_static_field", run_id="20261026_050001__test__python__pulse-static-input",
            inputs=dict(plan=str(static / "inputs/bvp/paired_accelerator_static_field_plan.json"), backend=str(target))))
        runtime.write(static / "run_manifest.json", build_run_manifest(static / "run_config.json", "failed", output_paths=[model, solution, publication]))

        producer = root / "producer"
        inputs = producer / "inputs"
        inputs.mkdir(parents=True)
        geometry = runtime.read(static / "inputs/bvp/paired_accelerator_geometry.json")
        runtime.write(inputs / "frontend_geometry.json", geometry)
        shutil.copyfile(static / "inputs/sources/oatof_resolved.json", inputs / "oatof_resolved.json")
        request = dict(providers=dict(instances={plan["oatof_instance_id"]: dict(resolved_design=file_record(inputs / "oatof_resolved.json"))}))
        runtime.write(inputs / "request.json", request)
        binding = plan["native_geometry_compilation"]["electrode_bindings"][plan["oatof_instance_id"]]
        on = plan["static_on_electrode_voltages_v"]
        runtime.write(inputs / "frontend_field_design.json", dict(accelerator_voltage_states=dict(
            pulse_voltage_policy_id="all_accelerator_electrodes_zero_before_pulse_v1",
            off_voltages_v={key: 0. for key in on}, operating_voltages_v=on)))
        runtime.write(inputs / "instrument_epoch.json", dict(instrument_time_us=0.))
        clock = dict(schema_version=1, role="canonical_clock_authority", clock_epoch_id="instrument_clock_epoch_v1",
            instrument_time_unit="us", canonical_time_basis="instrument_epoch_absolute_time",
            authority=dict(path="inputs/instrument_epoch.json", sha256="", field="instrument_time_us"),
            solver_local_time_basis="elapsed_time_from_zero_us",
            adapter_materialization="instrument_time_us_equals_authority_epoch_plus_solver_elapsed_once",
            handoff_policy="preserve_instrument_time_us_and_clock_epoch_id", legacy_new_campaign_allowed=False)
        clock["authority"]["sha256"] = file_record(inputs / "instrument_epoch.json")["sha256"]
        runtime.write(inputs / "clock_authority.json", clock)
        runtime.write(inputs / "source_provenance.json", dict(role="single_reflection_source_provenance",
            target_frame_id=plan["coordinate_frame"], clock_epoch_id=clock["clock_epoch_id"], instrument_epoch_us=0.,
            source_metadata=dict(particle_count=100, mass_amu=100., charge_state=1)))
        g = plan["accelerator_geometry"]
        z = (g["repeller_front_z_mm"] + g["grid1_z_mm"]) / 2
        template = dict(x_mm=g["axis_x_mm"], y_mm=0., z_mm=z, vx_mm_per_us=1., vy_mm_per_us=0., vz_mm_per_us=0., kinetic_energy_eV=kinetic_energy_ev(100., 1000., 0., 0.))
        rows = [dict(template, particle_id=i, event="source_release", instrument_time_us=i / 1000) for i in range(1, 101)]
        rows += [dict(template, particle_id=i, event="pre_pulse_state", instrument_time_us=10.) for i in range(100, 0, -1)]
        with (inputs / "projected_source.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=GLOBAL_COLUMNS)
            writer.writeheader()
            for row in rows[:100]:
                writer.writerow(dict(particle_id=row["particle_id"], instrument_time_us=row["instrument_time_us"],
                    mass_amu=100., charge_state=1, kinetic_energy_eV=row["kinetic_energy_eV"],
                    **{f"position_{axis}_mm": row[f"{axis}_mm"] for axis in "xyz"},
                    **{f"velocity_{axis}_m_s": row[f"v{axis}_mm_per_us"] * 1000 for axis in "xyz"}))
        collection = dict(schema_version=1, role="single_reflection_complete_mother_collection", phase="full_instrument", native_complete=True,
            clock_epoch_id=clock["clock_epoch_id"], flight=dict(pulse=dict(mode="timed", time_us=10., width_us=2.)), canonical_events=rows)
        for name, filename in (("geometry", "frontend_geometry.json"), ("source", "projected_source.csv"), ("request", "request.json"), ("field_design", "frontend_field_design.json")):
            record = file_record(inputs / filename)
            # Historical embedded locations are provenance only. The shared
            # helper must bind the exact bytes to this producer's canonical input.
            collection[name + "_record"] = {**record, "path": str(root / "removed_execution_junction" / filename)}
        runtime.write(producer / "collection.json", collection)
        runtime.write(producer / "run_config.json", dict(schema_version=1, project="instrument_assembly", mode="single_reflection_flight",
            run_id="20261026_050002__test__python__pulse-source-input",
            inputs={path.name: str(path) for path in inputs.iterdir()}))
        self.publish_producer(producer)
        author = dict(schema_version=1, role="paired_accelerator_pulse_request", static_field_manifest=file_record(static / "run_manifest.json"),
            source=dict(kind="recorded_pre_pulse_state", instance_id=plan["oatof_instance_id"], frame_id=plan["coordinate_frame"],
                pre_pulse_collection=file_record(producer / "collection.json"), producer_manifest=file_record(producer / "run_manifest.json"),
                clock_authority=file_record(inputs / "clock_authority.json"), instrument_epoch=file_record(inputs / "instrument_epoch.json")),
            observation_times_us=[10., 11., 12., 13.], numerics=dict(maximum_step_us=.1, relative_tolerance=1e-5, absolute_tolerance=1e-6, simion_trajectory_quality=10))
        path = root / "pulse_request.json"
        runtime.write(path, author)
        self.assertEqual(len(binding["accelerator_ring_ids"]), 20)
        return path, author, producer, model

    @staticmethod
    def publish_producer(producer: Path) -> None:
        outputs = [producer / "collection.json"]
        if (producer / "pulse_decision.json").is_file():
            outputs.append(producer / "pulse_decision.json")
        runtime.write(producer / "run_manifest.json", build_run_manifest(producer / "run_config.json", "success", output_paths=outputs))

    @staticmethod
    def export_consumer(root: Path, selected_manifest: Path, name: str, *, stale_alias=False) -> Path:
        """Published inert metadata only; no native model is created or solved."""
        consumer = root / name
        own_plan = consumer / "inputs/bvp/paired_accelerator_static_field_plan.json"
        plan = runtime.read(selected_manifest.parent / "inputs/bvp/paired_accelerator_static_field_plan.json")
        # Change only the SIMION artifact identity; the underlying ES BVP stays frozen.
        gem = consumer / "inputs/consumer.gem"
        gem.parent.mkdir(parents=True)
        gem.write_text("INERT SIMION GEM IDENTITY; NOT NATIVE GEOMETRY " + name)
        plan["native_geometry_compilation"]["gem_record"] = file_record(gem)
        runtime.write(own_plan, plan)
        source = paired_accelerator_model.load_paired_static_model_source(selected_manifest, selected_manifest)
        if stale_alias:
            source["manifest"]["path"] = str(root / "removed_alias/comsol_source_manifest.json")
        runtime.write(consumer / "inputs/comsol_source.json", source)
        shutil.copyfile(selected_manifest, consumer / "inputs/comsol_source_manifest.json")
        publication = consumer / "results/simion_field_publication.json"
        runtime.write(publication, dict(status="published", action_required="complete", cache_key="INERT_" + name,
            generation_directory=str(root / ("inert_simion_generation_" + name))))
        config = consumer / "run_config.json"
        runtime.write(config, dict(schema_version=1, project="instrument_assembly", mode="paired_accelerator_static_field",
            run_id="20261026_151000__test__python__" + name, inputs=dict(plan=str(own_plan),
                source=str(consumer / "inputs/comsol_source.json"),
                source_manifest=str(consumer / "inputs/comsol_source_manifest.json"))))
        runtime.write(consumer / "run_manifest.json", build_run_manifest(config, "success", output_paths=[publication]))
        return consumer

    def test_export_only_source_flattens_original_model_and_binds_own_simion_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, author, _, model = self.fixture(root)
            original = model.parent.parent
            consumer = self.export_consumer(root, original / "run_manifest.json", "export1", stale_alias=True)
            original_open = Path.open
            def no_payload(path, *args, **kwargs):
                if path.suffix.lower() in (".mph", ".pa", ".pa0", ".pa#"):
                    raise AssertionError("metadata consumer opened a solver payload")
                return original_open(path, *args, **kwargs)
            with patch.object(Path, "open", no_payload), patch.object(paired_accelerator_model, "verify_record",
                    wraps=paired_accelerator_model.verify_record) as verified:
                for index in range(1, 4):
                    selected = consumer / "run_manifest.json"
                    source = paired_accelerator_model.load_paired_static_model_source(selected, selected)
                    self.assertEqual(Path(source["model"]["path"]), model)
                    self.assertEqual(Path(source["plan"]["path"]), original / "inputs/bvp/paired_accelerator_static_field_plan.json")
                    self.assertEqual(Path(source["manifest"]["source_path"]), original / "run_manifest.json")
                    current = copy.deepcopy(author)
                    current["static_field_manifest"] = file_record(selected)
                    runtime.write(path, current)
                    prepared = prepare(path, root / ("prepared_export" + str(index)))
                    own = consumer / "inputs/bvp/paired_accelerator_static_field_plan.json"
                    self.assertEqual(prepared["static_plan"]["sha256"], file_record(own)["sha256"])
                    self.assertEqual(prepared["model"], source["model"])
                    self.assertEqual(runtime.read(Path(prepared["input_records"]["simion_field_publication"]["path"]))["cache_key"], "INERT_export" + str(index))
                    if index < 3:
                        consumer = self.export_consumer(root, selected, "export" + str(index + 1))
                self.assertNotIn(str(model), [str(call.args[1]["path"]) for call in verified.call_args_list])

    def test_export_source_rejects_bvp_or_flat_origin_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, _, model = self.fixture(root)
            original = model.parent.parent
            consumer = self.export_consumer(root, original / "run_manifest.json", "export1")
            plan_path = consumer / "inputs/bvp/paired_accelerator_static_field_plan.json"
            source_path = consumer / "inputs/comsol_source.json"
            initial_plan, initial_source = runtime.read(plan_path), runtime.read(source_path)
            def publish():
                config = consumer / "run_config.json"
                runtime.write(consumer / "run_manifest.json", build_run_manifest(config, "success",
                    output_paths=[consumer / "results/simion_field_publication.json"]))
            for kind in ("voltage", "geometry", "comsol_mesh", "source"):
                with self.subTest(kind=kind):
                    plan, source = copy.deepcopy(initial_plan), copy.deepcopy(initial_source)
                    if kind == "voltage":
                        identifier = next(iter(plan["static_on_electrode_voltages_v"]))
                        plan["static_on_electrode_voltages_v"][identifier] += 1
                    elif kind == "geometry":
                        plan["accelerator_geometry"]["shield_outer_width_mm"] += .25
                    elif kind == "comsol_mesh":
                        plan["numerical_domain"]["comsol_mesh"]["electrode_boundary_maximum_element_size_mm"] *= 1.1
                    else:
                        source["model"]["sha256"] = "0" * 64
                    runtime.write(plan_path, plan)
                    runtime.write(source_path, source)
                    publish()
                    with self.assertRaisesRegex(ValueError, "BVP differs|original COMSOL model source"):
                        paired_accelerator_model.load_paired_static_model_source(
                            consumer / "run_manifest.json", consumer / "run_manifest.json")
            runtime.write(plan_path, initial_plan)
            runtime.write(source_path, initial_source)
            publish()
            data = runtime.read(consumer / "run_manifest.json")
            data["inputs"] = {key:value for key,value in data["inputs"].items() if key != "source_manifest"}
            runtime.write(consumer / "run_manifest.json", data)
            with self.assertRaisesRegex(ValueError, "manifest-bound"):
                paired_accelerator_model.load_paired_static_model_source(
                    consumer / "run_manifest.json", consumer / "run_manifest.json")

    def test_preserves_all_recorded_states_clock_mother_and_actual_voltage_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, author, producer, model = self.fixture(root)
            author["static_field_manifest"] = {key: author["static_field_manifest"][key] for key in ("path", "bytes", "sha256")}
            for name in ("pre_pulse_collection", "producer_manifest", "clock_authority", "instrument_epoch"):
                author["source"][name] = {key: author["source"][name][key] for key in ("path", "bytes", "sha256")}
            runtime.write(path, author)
            original_open = Path.open

            def no_payload_open(path, *args, **kwargs):
                if path.resolve() == model.resolve() or path.suffix.lower() == ".pa":
                    raise AssertionError("pure preparation opened a native payload")
                return original_open(path, *args, **kwargs)

            with patch.object(Path, "open", no_payload_open):
                plan = prepare(path, root / "prepared")
            self.assertEqual(plan["particle_count"], 100)
            self.assertEqual(plan["selected_particle_ids"], list(range(100, 0, -1)))
            self.assertEqual(plan["original_mother_particle_ids"], list(range(1, 101)))
            self.assertEqual(plan["original_birth_times_us"], {i: i / 1000 for i in range(1, 101)})
            self.assertEqual(plan["mass_kg"], 100. * AMU_KG)
            self.assertEqual(plan["pulse"], dict(on_us=10., off_us=12.))
            self.assertEqual(plan["source_time_us"], 10.)
            self.assertEqual(plan["instrument_epoch_us"], 0.)
            self.assertEqual(len(plan["off_electrode_voltages_v"]), 25)
            self.assertEqual(plan["selection_basis"], "all_recorded_timed_pre_pulse_states")
            self.assertEqual(runtime.read(producer / "collection.json")["geometry_record"]["path"], str(root / "removed_execution_junction/frontend_geometry.json"))
            with Path(plan["source_csv"]["path"]).open() as stream:
                table = list(csv.DictReader(stream))
            self.assertEqual([int(row["particle_id"]) for row in table], plan["selected_particle_ids"])
            selected = [row for row in runtime.read(producer / "collection.json")["canonical_events"] if row["event"] == "pre_pulse_state"]
            for actual, recorded in zip(table, selected, strict=True):
                for axis in "xyz":
                    self.assertEqual(float(actual[axis + "_mm"]), recorded[axis + "_mm"])
                    self.assertEqual(float(actual["v" + axis + "_m_per_s"]), recorded["v" + axis + "_mm_per_us"] * 1000.)
            self.assertEqual(len(list((root / "prepared").glob("source*.csv"))), 1)

    def test_rejects_invalid_author_times_controls_and_unbound_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, author, _, _ = self.fixture(root)
            changes = {
                "old_schema": lambda q: q.update(schema_version=0),
                "boolean_schema": lambda q: q.update(schema_version=True),
                "new_voltage_authority": lambda q: q.update(off_electrode_voltages_v={}),
                "missing_off_edge": lambda q: q.update(observation_times_us=[10., 11., 13.]),
                "duplicated_time": lambda q: q.update(observation_times_us=[10., 10., 12., 13.]),
                "source_time_reset": lambda q: q.update(observation_times_us=[0., 10., 12., 13.]),
                "no_post_off": lambda q: q.update(observation_times_us=[10., 11., 12.]),
                "bad_control": lambda q: q["numerics"].update(maximum_step_us=0.),
                "missing_quality": lambda q: q["numerics"].pop("simion_trajectory_quality"),
                "quality_bool": lambda q: q["numerics"].update(simion_trajectory_quality=True),
                "quality_fraction": lambda q: q["numerics"].update(simion_trajectory_quality=1.5),
                "quality_string": lambda q: q["numerics"].update(simion_trajectory_quality="10"),
                "quality_zero": lambda q: q["numerics"].update(simion_trajectory_quality=0),
                "quality_above_supported": lambda q: q["numerics"].update(simion_trajectory_quality=501),
                "frame_changed": lambda q: q["source"].update(frame_id="different_frame"),
                "instance_changed": lambda q: q["source"].update(instance_id="different_instance"),
                "source_changed": lambda q: q["source"]["pre_pulse_collection"].update(sha256="0" * 64),
                "clock_missing_identity": lambda q: q["source"]["clock_authority"].pop("sha256"),
            }
            for name, change in changes.items():
                with self.subTest(name=name):
                    request = copy.deepcopy(author)
                    change(request)
                    runtime.write(path, request)
                    with self.assertRaises((ValueError, AssertionError)):
                        prepare(path, root / name)

    def test_frozen_relative_author_uses_explicit_original_source_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, author, _, _ = self.fixture(root)
            author["static_field_manifest"]["path"] = str(Path(author["static_field_manifest"]["path"]).relative_to(root))
            for name in ("pre_pulse_collection", "producer_manifest", "clock_authority", "instrument_epoch"):
                author["source"][name]["path"] = str(Path(author["source"][name]["path"]).relative_to(root))
            runtime.write(path, author)
            original = prepare(path, root / "original")
            frozen_request = root / "new_owner/inputs/request.json"
            frozen_request.parent.mkdir(parents=True)
            shutil.copyfile(path, frozen_request)
            moved = prepare(frozen_request, root / "transported", source_base_dir=root)
            self.assertEqual(frozen_request.read_bytes(), path.read_bytes())
            self.assertEqual(Path(original["source_csv"]["path"]).read_bytes(), Path(moved["source_csv"]["path"]).read_bytes())
            for key in ("model", "selected_particle_ids", "source_time_us", "clock_epoch_id"):
                self.assertEqual(original[key], moved[key])
            with self.assertRaises(FileNotFoundError):
                prepare(frozen_request, root / "wrong_base")

    def test_rejects_published_clock_voltage_species_and_source_physics_changes(self):
        for name in ("clock", "frame", "off_voltage", "on_voltage", "charge", "energy_species", "pulse_width", "outside_box", "outside_first_gap", "unpublished_input"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path, author, producer, _ = self.fixture(root)
                collection = runtime.read(producer / "collection.json")
                provenance_path = producer / "inputs/source_provenance.json"
                provenance = runtime.read(provenance_path)
                if name == "clock":
                    collection["clock_epoch_id"] = "different_epoch"
                elif name == "frame":
                    provenance["target_frame_id"] = "different_frame"
                elif name in ("charge", "energy_species"):
                    provenance["source_metadata"]["charge_state" if name == "charge" else "mass_amu"] = 0 if name == "charge" else 1000.
                elif name in ("off_voltage", "on_voltage"):
                    field_path = producer / "inputs/frontend_field_design.json"
                    field = runtime.read(field_path)
                    table = field["accelerator_voltage_states"]["off_voltages_v" if name == "off_voltage" else "operating_voltages_v"]
                    table[next(iter(table))] += 1.
                    runtime.write(field_path, field)
                    record = file_record(field_path)
                    collection["field_design_record"] = {**record, "path": collection["field_design_record"]["path"]}
                elif name == "pulse_width":
                    collection["flight"]["pulse"]["width_us"] = 0.
                elif name == "unpublished_input":
                    pass
                else:
                    row = next(row for row in collection["canonical_events"] if row["event"] == "pre_pulse_state")
                    row["x_mm" if name == "outside_box" else "z_mm"] = (10000. if name == "outside_box" else
                        runtime.read(producer / "inputs/oatof_resolved.json")["geometry_mm"]["accelerator_grid1_z"] + 1.)
                runtime.write(provenance_path, provenance)
                runtime.write(producer / "collection.json", collection)
                self.publish_producer(producer)
                if name == "unpublished_input":
                    manifest = runtime.read(producer / "run_manifest.json")
                    manifest["inputs"]["clock_authority.json"]["exists"] = False
                    runtime.write(producer / "run_manifest.json", manifest)
                author["source"]["producer_manifest"] = file_record(producer / "run_manifest.json")
                author["source"]["pre_pulse_collection"] = file_record(producer / "collection.json")
                runtime.write(path, author)
                with self.assertRaises((ValueError, AssertionError)):
                    prepare(path, root / "prepared")

    def test_model_geometry_evolution_does_not_rewrite_or_rebind_recorded_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, author, producer, model = self.fixture(root)
            original = prepare(path, root / "before")
            for quality in (1, 500):
                author["numerics"]["simion_trajectory_quality"] = quality
                runtime.write(path, author)
                quality_plan = prepare(path, root / f"quality_{quality}")
                self.assertEqual(quality_plan["numerics"]["simion_trajectory_quality"], quality)
                self.assertEqual(Path(original["source_csv"]["path"]).read_bytes(), Path(quality_plan["source_csv"]["path"]).read_bytes())
            author["numerics"]["simion_trajectory_quality"] = 10
            source_identity = file_record(producer / "collection.json")
            static = model.parent.parent
            plan_path = static / "inputs/bvp/paired_accelerator_static_field_plan.json"
            plan = runtime.read(plan_path)
            resolved = runtime.read(producer / "inputs/oatof_resolved.json")
            resolved["unrelated_model_audit"] = "new model input revision"
            runtime.write(static / "inputs/revised_resolved.json", resolved)
            plan["source_records"]["oatof_resolved"] = file_record(static / "inputs/revised_resolved.json")
            plan["accelerator_geometry"]["bore_width_mm"] += 10.
            runtime.write(plan_path, plan)
            model.write_bytes(b"INERT REVISED MODEL IDENTITY; NOT A NATIVE GEOMETRY PROOF")
            runtime.write(static / "run_manifest.json", build_run_manifest(static / "run_config.json", "failed",
                output_paths=[model, static / "comsol/comsol_field_solution.json", static / "results/simion_field_publication.json"]))
            author["static_field_manifest"] = file_record(static / "run_manifest.json")
            runtime.write(path, author)
            changed = prepare(path, root / "after")
            self.assertEqual(file_record(producer / "collection.json"), source_identity)
            self.assertEqual(Path(original["source_csv"]["path"]).read_bytes(), Path(changed["source_csv"]["path"]).read_bytes())
            for key in ("source_time_us", "selected_particle_ids", "original_birth_times_us", "clock_epoch_id"):
                self.assertEqual(original[key], changed[key])

    def test_explicit_published_decision_preserves_order_and_uncontinued_mother(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, author, producer, _ = self.fixture(root)
            collection = runtime.read(producer / "collection.json")
            decision = dict(schema_version=2, role="single_reflection_actual_occupancy_pulse_decision", status="success",
                selection_uses_future_terminal_outcome=False, actual_pulse_time_us=10.,
                selection=dict(status="selected", selected_time_us=10., execution_cohort_count=100, selected=dict(eligible_ids=[77, 7])),
                input_records=dict(request=collection["request_record"], frontend_geometry=collection["geometry_record"]))
            decision_path = producer / "pulse_decision.json"
            runtime.write(decision_path, decision)
            self.publish_producer(producer)
            author["source"]["pulse_decision"] = file_record(decision_path)
            author["source"]["producer_manifest"] = file_record(producer / "run_manifest.json")
            runtime.write(path, author)
            plan = prepare(path, root / "selected")
            self.assertEqual(plan["selected_particle_ids"], [77, 7])
            self.assertEqual(plan["original_mother_particle_ids"], list(range(1, 101)))
            self.assertEqual(plan["uncontinued_mother_particle_ids"], [i for i in range(1, 101) if i not in (77, 7)])
            decision["input_records"]["frontend_geometry"] = {**collection["geometry_record"], "sha256": "0" * 64}
            runtime.write(decision_path, decision)
            self.publish_producer(producer)
            author["source"]["pulse_decision"] = file_record(decision_path)
            author["source"]["producer_manifest"] = file_record(producer / "run_manifest.json")
            runtime.write(path, author)
            with self.assertRaisesRegex(ValueError, "pulse decision does not bind"):
                prepare(path, root / "mixed_decision")

    def test_actual_110745_all_100_states_use_original_235338_common_field(self):
        runs = ROOT.parent / "artifacts/projects/instrument_assembly/runs"
        producer = runs / "20261025_110745__sim__simion__single-reflection-flight"
        static = runs / "20261025_235338__sim__cross__paired-accelerator-static-field"
        if not all((run / "run_manifest.json").is_file() for run in (producer, static)):
            self.skipTest("optional frozen real source/common-field metadata is not installed")
        collection_path = producer / "results/single_reflection/baseline/collection.json"
        collection = runtime.read(collection_path)
        on = collection["flight"]["pulse"]["time_us"]
        width = collection["flight"]["pulse"]["width_us"]
        author = dict(schema_version=1, role="paired_accelerator_pulse_request", static_field_manifest=file_record(static / "run_manifest.json"),
            source=dict(kind="recorded_pre_pulse_state", instance_id="oatof", frame_id="oatof_global",
                pre_pulse_collection=file_record(collection_path), producer_manifest=file_record(producer / "run_manifest.json"),
                clock_authority=file_record(producer / "inputs/clock_authority.json"), instrument_epoch=file_record(producer / "inputs/instrument_epoch.json")),
            observation_times_us=[on, on + width / 2, on + width, on + 2 * width],
            numerics=dict(maximum_step_us=.001, relative_tolerance=1e-5, absolute_tolerance=1e-6,
                simion_trajectory_quality=collection["flight"]["trajectory_quality"]))
        author["static_field_manifest"] = {key: author["static_field_manifest"][key] for key in ("path", "bytes", "sha256")}
        for name in ("pre_pulse_collection", "producer_manifest", "clock_authority", "instrument_epoch"):
            author["source"][name] = {key: author["source"][name][key] for key in ("path", "bytes", "sha256")}
        original_open = Path.open

        def no_native_payload(path, *args, **kwargs):
            if path.suffix.lower() in (".mph", ".pa", ".pa0", ".pa#"):
                raise AssertionError("pure preparation attempted a native payload read")
            return original_open(path, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime.write(root / "request.json", author)
            with patch.object(Path, "open", no_native_payload):
                plan = prepare(root / "request.json", root / "prepared")
            self.assertEqual(plan["particle_count"], 100)
            self.assertEqual(plan["selected_particle_ids"], list(range(1, 101)))
            self.assertEqual(plan["original_mother_particle_ids"], list(range(1, 101)))
            self.assertEqual(plan["uncontinued_mother_particle_ids"], [])
            self.assertEqual(plan["mass_amu"], 100.)
            self.assertEqual(plan["mass_kg"], 100. * AMU_KG)
            self.assertEqual(plan["pulse"], dict(on_us=on, off_us=on + width))
            self.assertEqual(plan["model"]["path"], str(static / "comsol/paired_accelerator_static.mph"))
            publication = runtime.read(Path(plan["input_records"]["simion_field_publication"]["path"]))
            self.assertEqual(publication["cache_key"], "98A5A67296BFC07DD6C78E0D83A38FE27C9B1423F0C32A96FD0C0A7BA9A82D47")
            with Path(plan["source_csv"]["path"]).open() as stream:
                states = list(csv.DictReader(stream))
            original = [row for row in collection["canonical_events"] if row["event"] == "pre_pulse_state"]
            for actual, recorded in zip(states, original, strict=True):
                for axis in "xyz":
                    self.assertEqual(float(actual[axis + "_mm"]), recorded[axis + "_mm"])
                    self.assertEqual(float(actual["v" + axis + "_m_per_s"]), recorded["v" + axis + "_mm_per_us"] * 1000.)
