from __future__ import annotations

import sys
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from msplatform.execution.retention import file_record
from msplatform.execution.inputs import python_import_roots
from msplatform.backends.simion.particle_batching import plan_single_wave_batches
from msplatform.backends.simion.optimize_reflectron_ring_voltages import render_lua_profile
import msplatform.workflows.oa_candidate.run_compensation as study


FIT = {"schema_version": 1, "stage1_count": 2, "stage2_count": 2,
       "stage1_ring_voltages_V": [100.0, 200.0], "stage2_ring_voltages_V": [300.0, 400.0],
       "fixed_endpoints_V": {}, "fit": {}}
CONTRACT = {"rings": {"stage1_count": 2, "stage2_count": 2}, "geometry_mm": {"L_stage1": 20.0, "L_stage2": 30.0},
            "electrodes_V": {"midgrid": 200.0, "backplate": 500.0}}


class ReflectronVoltageCompensationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, path: Path, value: dict) -> None:
        study._write_json(path, value)

    def terminal(self, run: Path, inputs: list[Path], outputs: list[Path]) -> None:
        self.write(run / "run_config.json", {"run_id": run.name, "mode": "reflectron_voltage_compensation"})
        self.write(run / "run_manifest.json", {"schema_version": 2, "role": "simulation_run_manifest", "project": study.PROJECT,
            "run_id": run.name, "mode": "reflectron_voltage_compensation", "status": "failed",
            "run_config": file_record(run / "run_config.json"), "inputs": {str(i): file_record(p) for i, p in enumerate(inputs)},
            "outputs": [file_record(p) for p in outputs]})

    def fixture(self, name: str) -> Path:
        run = self.root / name
        (run / "inputs").mkdir(parents=True)
        self.write(run / "inputs/candidate_resolved_geometry.json", CONTRACT)
        (run / "inputs/source.ion").write_text("\n".join(str(i) for i in range(1000))+"\n", encoding="ascii")
        builder = run / "inputs/code/src/msplatform/backends/simion/resources/build_formal_iob.lua"
        builder.parent.mkdir(parents=True)
        builder.write_text("actual-builder", encoding="utf-8")
        assembly = run / "inputs/code/src/msplatform/backends/simion/resources/assemble_native_fast_adjust_family.lua"
        assembly.parent.mkdir(parents=True, exist_ok=True)
        assembly.write_text("actual-assembly", encoding="utf-8")
        (run / "results").mkdir()
        (run / "logs").mkdir()
        (run / "results/axis_basis.csv").write_text("fixture", encoding="utf-8")
        source = self.root / "published.pa0"
        if not source.exists():
            source.write_bytes(b"native-source-bytes")
        plan = {"runtime_files": [], "producer": {"component_plan": {"components": [{"role": "reflectron", "identity": {"geometry": "fixture"}, "operating_voltages_v": {"1": 100}}]}},
                "source": file_record(run / "inputs/source.ion"), "simion_executable": {"path": "simion.exe", "sha256": "C"*64},
                "source_manifest": {"path": "source-manifest"},
                "trajectory_quality": 8, "regularization": 1e-4, "particle_count": 1000, "predecessor_manifest": None}
        self.write(run / "inputs/compensation_plan.json", plan)
        return run

    def fit(self, run: Path) -> dict:
        with patch.object(study, "_load_basis", return_value=([], [])), patch.object(study, "optimize", return_value=FIT), \
                patch.object(study, "render_program", return_value="science-program"):
            return study.fit_and_plan(run)

    def parent(self, complete: set[int]) -> Path:
        run = self.fixture("20261030_120000__sim__simion__compensation-parent")
        self.fit(run)
        partition = plan_single_wave_batches(1000, 5)
        outputs = []
        for label in study.LABELS:
            self.write(run / f"results/{label}.batch_plan.json", partition)
            # Materialize from the complete frozen partition, not a new bootstrap.
            dispatch = study._load(run / f"results/{label}.dispatch_plan.json")
            dispatch["waves"][0].update(batches=partition["batches"], batch_count=5, coverage="complete_population")
            self.write(run / f"results/{label}.dispatch_plan.json", dispatch)
            cases = study.materialize_batches(run, label)["batches"]
            outputs.append(run / f"results/{label}.batch_plan.json")
            for case in cases:
                if case["batch"]["index"] not in complete:
                    continue
                Path(case["stdout_path"]).write_text("status,Fly completed. 200 splats, 1 seconds\n", encoding="utf-8")
                study.complete_batch(run, label, case["batch"]["index"], {"completed": True, "exit_code": 0})
                outputs.extend([Path(case["stdout_path"]), run / f"results/native_batch_completion/{case['name']}.json"])
        self.terminal(run, [run / "inputs/flight_identity.json"], outputs)
        return run

    def child(self, parent: Path) -> Path:
        run = self.fixture("20261030_120001__sim__simion__compensation-recovery")
        plan = study._load(run / "inputs/compensation_plan.json")
        plan["predecessor_manifest"] = file_record(parent / "run_manifest.json")
        self.write(run / "inputs/compensation_plan.json", plan)
        return run

    def test_complete_units_reuse_without_native_or_runtime_materialization_and_parent_unchanged(self) -> None:
        parent = self.parent({1, 2, 3, 4, 5})
        before = {p: p.read_bytes() for p in parent.rglob("*") if p.is_file()}
        child = self.child(parent)
        with patch.object(study, "producer_specification") as native_prepare:
            result = self.fit(child)
            self.assertFalse(result["native_fly_required"])
            for label in study.LABELS:
                batches = study.materialize_batches(child, label)["batches"]
                self.assertEqual(len(batches), 5)
                self.assertTrue(all(c["reused"] for c in batches))
                self.assertEqual([c["batch"]["count"] for c in batches], [200]*5)
            native_prepare.assert_not_called()
        self.assertFalse((child / "simion").exists())
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_partial_failed_parent_keeps_original_larger_units_and_completed_first_batch(self) -> None:
        parent = self.parent({1, 4})
        child = self.child(parent)
        result = self.fit(child)
        self.assertTrue(result["native_fly_required"])
        for mode in result["modes"]:
            self.assertEqual(mode["reused_batch_indices"], [1, 4])
            dispatch = study._load(Path(mode["dispatch_plan"]))
            self.assertTrue(dispatch["estimation"]["recovered_missing_observation"])
            self.assertEqual(dispatch["estimation"]["replay_batch_indices"], [2, 3, 5])
            batches = study.materialize_batches(child, mode["label"])["batches"]
            self.assertEqual([c["batch"]["index"] for c in batches if not c["reused"]], [2, 3, 5])
            self.assertEqual(sum(c["batch"]["count"] for c in batches), 1000)

    def rebind_parent(self, parent: Path) -> None:
        manifest = study._load(parent / "run_manifest.json")
        self.terminal(parent, [Path(r["path"]) for r in manifest["inputs"].values()],
                      [Path(r["path"]) for r in manifest["outputs"] if Path(r["path"]).is_file()])

    def test_recovery_after_first_batch_replan_failure_preserves_completed_prefix(self) -> None:
        parent = self.parent({1})
        path = parent / "results/baseline.batch_plan.json"
        original = study._load(path)
        self.write(path, dict(original, batches=original["batches"][:1], batch_count=1, coverage="formal_observation"))
        self.rebind_parent(parent)
        child = self.child(parent)
        self.fit(child)
        cases = study.materialize_batches(child, "baseline")["batches"]
        self.assertEqual(cases[0]["batch"], original["batches"][0])
        self.assertTrue(cases[0]["reused"])
        self.assertEqual([c["batch"]["index"] for c in cases if not c["reused"]], [2, 3, 4, 5])
        self.assertEqual(sum(c["batch"]["count"] for c in cases), 1000)

    def test_arms_not_started_before_failure_get_fresh_plans_without_losing_other_units(self) -> None:
        parent = self.parent({1})
        (parent / "results/compensated.batch_plan.json").unlink()
        (parent / "results/native_batch_completion/compensated__0001.json").unlink()
        self.rebind_parent(parent)
        child = self.child(parent)
        result = self.fit(child)
        modes = {m["label"]: m for m in result["modes"]}
        self.assertEqual(modes["baseline"]["reused_batch_indices"], [1])
        self.assertEqual(modes["compensated"]["reused_batch_indices"], [])
        self.assertFalse(modes["compensated"]["all_reused"])
        dispatch = study._load(Path(modes["compensated"]["dispatch_plan"]))
        self.assertEqual(dispatch["estimation"]["kind"], "formal_first_batch_observation")

    def test_missing_or_tampered_completion_is_not_silently_reused(self) -> None:
        parent = self.parent({1})
        log = parent / "logs/simion__batch__baseline__0001.stdout.log"
        log.write_text(log.read_text()+"tamper", encoding="utf-8")
        child = self.child(parent)
        with self.assertRaisesRegex(ValueError, "hash differs"):
            self.fit(child)

    def test_changed_actual_fly_input_rejects_reuse_before_native(self) -> None:
        parent = self.parent({1})
        child = self.child(parent)
        plan = study._load(child / "inputs/compensation_plan.json")
        plan["trajectory_quality"] = 9
        self.write(child / "inputs/compensation_plan.json", plan)
        with self.assertRaisesRegex(ValueError, "Fly inputs differ"):
            self.fit(child)
        self.assertFalse((child / "simion").exists())

    def test_completion_requires_observed_exit_and_exact_original_count(self) -> None:
        run = self.fixture("20261030_120002__sim__simion__compensation-completion")
        self.fit(run)
        cases = study.materialize_batches(run, "baseline")["batches"]
        case = cases[0]
        with self.assertRaisesRegex(ValueError, "natural exit"):
            study.complete_batch(run, "baseline", 1, {"completed": False, "exit_code": 0})
        with self.assertRaisesRegex(ValueError, "natural exit"):
            study.complete_batch(run, "baseline", 1, {"completed": True, "exit_code": 3})
        Path(case["stdout_path"]).parent.mkdir(exist_ok=True)
        Path(case["stdout_path"]).write_text("status,Fly completed. 99 splats, 1 seconds\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "whole batch"):
            study.complete_batch(run, "baseline", 1, {"completed": True, "exit_code": 0})

    def published_source(self, name: str | None = None) -> tuple[Path, Path]:
        case = self.root / (name or "20261030_120004__sim__simion__compensation-source")
        runtime = case / "simion"
        runtime.mkdir(parents=True)
        self.write(case / "contracts/candidate_resolved_geometry.json", CONTRACT)
        source = runtime / "oatof_comsol_524amu_gaussian_N100.ion"
        source.write_text("0,524,1,0,0,0,0,0,5,1,0\n"*100, encoding="ascii")
        names = ("oatof_ideal_grounded.iob", "oatof_ideal_grounded.con", "oatof_ideal_grounded.fly2", "oatof_resolved.lua",
                 "reflectron.pa0", "accelerator.pa0", "flight_tube_ground.pa0", "detector_ground.pa0")
        for name in names:
            (runtime / name).write_bytes(b"software-fixture")
        self.write(runtime / "resolved_geometry.json", CONTRACT)
        self.write(case / "logs/build_completion.json", {"role": "oatof_component_build_completion", "exception": None,
            "operations": [{"observation": {"exit_confirmed": True, "returncode": 0}}]})
        self.write(runtime / "simion_runtime_receipt.json", {"role": "oatof_simion_private_runtime", "status": "verified",
            "canonical_iob_verified": True, "files": [file_record(runtime / name) for name in names if ".pa" in name]})
        # An unrelated report is neither a native input nor an identity dependency.
        (runtime / "unconsumed-report.txt").write_text("report", encoding="utf-8")
        self.terminal(case, [], [p for p in case.rglob("*") if p.is_file()])
        executable = self.root / "simion.exe"
        executable.write_bytes(b"software-fixture-executable")
        return case, executable

    def product_manifest(self, run: Path, product_id: str, kind: str, metadata: dict,
                         records: dict[str, dict]) -> Path:
        self.write(run / "run_config.json", {"run_id": run.name, "mode": "field_fixture"})
        self.write(run / "run_manifest.json", {"schema_version": 2, "role": "simulation_run_manifest",
            "project": "instrument_assembly", "run_id": run.name, "mode": "field_fixture", "status": "success",
            "run_config": file_record(run / "run_config.json"), "inputs": {}, "outputs": list(records.values()),
            "products": {product_id: {"schema_version": 1, "kind": kind, "status": "complete",
                                      "metadata": metadata, "data": records}}})
        return run / "run_manifest.json"

    def historical_inert_basis_model(self):
        """Build the existing historical read-only oracle; no native execution."""
        import copy
        from importlib.resources import files
        from msplatform import assembly as assembly_api, components as component_api, examples as example_api
        from msplatform.backends.simion.compiler import compile_geometry
        from msplatform.backends.simion.model import PHYSICS, compile_prepared_model, project_resolved_drive
        from msplatform.execution.clock_authority import validate_clock_authority

        case = example_api.load_example('rf_oatof_functional_v1')
        parts = {key: component_api.resolve_component(value) for key, value in case.component_requests.items()}
        instrument = assembly_api.assemble(case.recipe, parts)
        geometry_numerics = copy.deepcopy(case.geometry_numerics)
        geometry_numerics['geometry_build']['detector']['max_mib'] = 128.0
        compiled = compile_geometry(dict(composition_plan=instrument.composition_plan,
            components_resolved=instrument.components_resolved), numerics=geometry_numerics)
        clock_root = Path(str(files('msplatform.examples')))
        clock_path = clock_root / 'instrument_clock_authority_v1.json'
        authority = validate_clock_authority(clock_path, clock_root)
        clock = dict(clock_epoch_id=authority['clock_epoch_id'], authority_sha256=authority['authority_sha256'],
                     **case.drive['clock'])
        drive = project_resolved_drive(compiled, compiled.components_resolved, pulse=case.drive['pulse'], clock=clock)
        model = compile_prepared_model(compiled, compiled.components_resolved, drive=drive, physics=PHYSICS)
        numerics = dict(frontend_domains=geometry_numerics['frontend_domains'], rf_reference_voltage_v=10000.,
            downstream_convergence_v=dict(flight_tube=.001, detector=.001, reflectron=.001))
        for domain in numerics['frontend_domains'].values():
            domain['refine_convergence_v'] = dict(carrier_off=.001, rf_reference=.001, pulse_delta=.001)
        return model, numerics, clock_path, clock_root

    def public_basis(self, executable: Path) -> tuple[Path, dict, dict]:
        """Publish synthetic historical basis records for the read-only consumer."""
        from msplatform.backends.simion.downstream_fields_worker import DOWNSTREAM_RESOURCES
        from msplatform.backends.simion.field_closure import downstream_identity
        from msplatform.backends.simion.model import model_geometry
        from msplatform.backends.simion.resources import native_resource_path
        model, numerics, clock_path, clock_root = self.historical_inert_basis_model()
        serial = getattr(self, "public_serial", 0) + 1
        self.public_serial = serial
        document = model.document
        contract = next(row for row in document["components_resolved"].values()
                        if row.get("role") == "oa_tof_resolved_contract_do_not_edit")
        prepared = self.root / ("public-prepared-" + str(serial))
        prepared.mkdir()
        records = {}
        def put(run: Path, target: Path, key: str, data: bytes, records: dict, role="required_evidence"):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            records[key] = file_record(target, role)
        put(prepared, prepared / "model.json", "compiled_model", json.dumps(model.document).encode(), records)
        epoch = study._load(clock_path)["authority"]["path"]
        put(prepared, prepared / "clock.json", "clock_authority", clock_path.read_bytes(), records)
        put(prepared, prepared / Path(epoch).name, "instrument_epoch", (clock_root / epoch).read_bytes(), records)
        native = {}
        for role in ("parent", "flight_tube", "reflectron", "detector"):
            key = role + "_raw"
            put(prepared, prepared / (role + ".pa#"), key, b"raw-" + role.encode(), records, "solver_native_binary")
            native[role] = {"raw_geometry": key}
            if role in {"flight_tube", "detector"}:
                surface = role + "_surface"
                put(prepared, prepared / (role + ".pa-surf"), surface, b"surface-" + role.encode(), records, "solver_native_binary")
                native[role]["fractional_surface"] = surface
        metadata = dict(backend="simion", drive_configured=True, geometry_materialized=True,
            field_status="not_solved", source_status="not_requested", native_assets=native)
        prepared_manifest = self.product_manifest(prepared, "model", "prepared_model", metadata, records)
        raw_assets = {}
        for role in ("flight_tube", "reflectron", "detector"):
            binding = native[role]
            raw_assets[role] = dict(raw_record=records[binding["raw_geometry"]], surface_records=
                [records[binding["fractional_surface"]]] if "fractional_surface" in binding else [])
        fields = self.root / ("public-fields-" + str(serial))
        fields.mkdir()
        data = {}
        put(fields, fields / "model.json", "compiled_model", json.dumps(model.document).encode(), data)
        put(fields, fields / "source_model.json", "source_model_manifest", prepared_manifest.read_bytes(), data)
        put(fields, fields / "numerics.json", "field_numerics", json.dumps(numerics).encode(), data)
        builders = {}
        for name in DOWNSTREAM_RESOURCES:
            key = "resource_" + name
            put(fields, fields / name, key, native_resource_path(name).read_bytes(), data)
            builders[name] = data[key]["sha256"]
        executable_record = file_record(executable)
        tool = dict(release="SIMION 2020", executable_bytes=executable_record["bytes"],
                    executable_sha256=executable_record["sha256"])
        spatial = downstream_identity(model, raw_assets=raw_assets,
            convergence_v=numerics["downstream_convergence_v"], tool_identity=tool, builder_identities=builders)
        geometry = model_geometry(model, downstream_drive=True)
        spec = next(row for row in geometry.downstream_specs if row["role"] == "reflectron")
        instance, variables = spec["native_instance"], spec["template_variables"]
        grid = dict(nx=instance["nx"], ny=instance["ny"], nz=instance["nz"],
            dx_mm=variables["mmgu_axial"], dy_mm=variables["mmgu_radial"], dz_mm=variables["mmgu_radial"])
        maximum = 4 + int(contract["rings"]["stage1_count"]) + int(contract["rings"]["stage2_count"])
        responses = []
        bindings = []
        for response_id in range(1, maximum + 1):
            key = "reflectron_response_" + str(response_id)
            put(fields, fields / ("reflectron.pa" + str(response_id)), key,
                b"authenticated-response-" + str(response_id).encode(), data, "solver_native_binary")
            responses.append(dict(data[key], response_id=response_id))
            bindings.append(dict(response_id=response_id, data_key=key))
        basis = dict(schema_version=1, model_identity_sha256=document["model_identity_sha256"],
            downstream_identity=spatial, grid=grid, symmetry="2dcylindrical", responses=bindings)
        metadata = dict(model_identity_sha256=document["model_identity_sha256"],
            downstream_identity=spatial, reflectron_response_basis=basis)
        manifest = self.product_manifest(fields, "fields", "field_bundle", metadata, data)
        return manifest, contract, {"responses": responses, "spatial": spatial, "grid": grid}

    def test_public_response_basis_authenticates_against_case_and_public_documents(self):
        _case, executable = self.published_source()
        manifest, contract, expected = self.public_basis(executable)
        basis = study._inspect_response_basis(manifest, contract, executable)
        self.assertEqual([row["response_id"] for row in basis["responses"]],
                         list(range(1, len(expected["responses"])+1)))
        self.assertEqual(basis["downstream_identity"], expected["spatial"])
        self.assertEqual(basis["grid"], expected["grid"])
        self.assertEqual(basis["reference"]["product_id"], "fields")

    def public_compensation_plan(self, use_basis: bool):
        serial = getattr(self, "public_serial", 0) + 1
        self.public_serial = serial
        case, executable = self.published_source("public-case-" + str(serial))
        manifest, contract, evidence = self.public_basis(executable)
        self.write(case / "contracts/candidate_resolved_geometry.json", contract)
        self.write(case / "simion/resolved_geometry.json", contract)
        self.terminal(case, [], [p for p in case.rglob("*") if p.is_file()
                                and p.name not in {"run_manifest.json", "run_config.json"}])
        return study.inspect_source(case, executable, 8, 1e-4, particle_count=100,
            response_basis_manifest=manifest if use_basis else None), evidence

    def test_public_basis_is_frozen_with_manifest_product_and_ordered_response_inputs(self):
        plan, _ = self.public_compensation_plan(True)
        run = self.root / "public-basis-frozen"
        self.write(run / "inputs/compensation_plan.json", plan)
        study.freeze_inputs(run)
        binding = study._load(run / "inputs/response_basis_binding.json")
        self.assertEqual(binding["reference"], plan["response_basis"]["reference"])
        self.assertEqual(binding["frozen_reference"]["product_id"], "fields")
        self.assertEqual([row["response_id"] for row in binding["frozen_responses"]],
                         list(range(1, plan["maximum_electrode"]+1)))
        specification = study.export_specification(run)
        self.assertEqual(Path(specification["argument_list"][4]), run / "inputs/response_basis/reflectron")
        for row in binding["frozen_responses"]:
            self.assertEqual(Path(row["record"]["path"]).read_bytes(),
                             Path(plan["response_basis"]["responses"][row["response_id"]-1]["path"]).read_bytes())
        default, _ = self.public_compensation_plan(False)
        other = self.root / "historical-basis-frozen"
        self.write(other / "inputs/compensation_plan.json", default)
        study.freeze_inputs(other)
        self.assertEqual(Path(study.export_specification(other)["argument_list"][4]),
                         other / "simion/reflectron")

    def test_public_basis_rejects_missing_reordered_tampered_wrong_model_and_grid_before_native(self):
        _case, executable = self.published_source()
        manifest, contract, evidence = self.public_basis(executable)
        original = manifest.read_bytes()
        for case in ("missing", "reordered", "wrong_model", "wrong_grid", "wrong_case"):
            changed = json.loads(original)
            basis = changed["products"]["fields"]["metadata"]["reflectron_response_basis"]
            actual_contract = contract
            if case == "missing":
                changed["products"]["fields"]["metadata"].pop("reflectron_response_basis")
            elif case == "reordered":
                basis["responses"].reverse()
            elif case == "wrong_model":
                basis["model_identity_sha256"] = "F" * 64
            elif case == "wrong_grid":
                basis["grid"] = dict(basis["grid"], nx=basis["grid"]["nx"] + 1)
            else:
                actual_contract = dict(contract, geometry_mm=dict(contract["geometry_mm"], L_stage1=-1))
            if case != "wrong_case":
                self.write(manifest, changed)
            with self.subTest(case=case), self.assertRaises((ValueError, AssertionError)):
                study._inspect_response_basis(manifest, actual_contract, executable)
            manifest.write_bytes(original)
        response = evidence["responses"][0]
        path = Path(response["path"])
        before = path.read_bytes()
        path.write_bytes(before + b"tampered")
        with self.assertRaises((ValueError, AssertionError)):
            study._inspect_response_basis(manifest, contract, executable)
        path.write_bytes(before)
        self.assertEqual(manifest.read_bytes(), original)

    def test_public_and_historical_basis_produce_identical_axis_fit_and_lua_bytes(self):
        outputs = []
        for kind in ("historical", "public"):
            plan, evidence = self.public_compensation_plan(kind == "public")
            run = self.root / ("equivalent-" + kind)
            self.write(run / "inputs/compensation_plan.json", plan)
            study.freeze_inputs(run)
            specification = study.export_specification(run)
            root = Path(specification["argument_list"][4])
            if kind == "historical":
                for response in evidence["responses"]:
                    target = run / ("simion/reflectron.pa" + str(response["response_id"]))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(Path(response["path"]).read_bytes())
            for response in evidence["responses"]:
                self.assertEqual((root.parent / (root.name + ".pa" + str(response["response_id"]))).read_bytes(),
                                 Path(response["path"]).read_bytes())
            contract = study._load(run / "inputs/candidate_resolved_geometry.json")
            n1, n2 = contract["rings"]["stage1_count"], contract["rings"]["stage2_count"]
            l1, l2 = contract["geometry_mm"]["L_stage1"], contract["geometry_mm"]["L_stage2"]
            mid, back = contract["electrodes_V"]["midgrid"], contract["electrodes_V"]["backplate"]
            stage1 = [mid * i / (n1 + 1) for i in range(1, n1 + 1)]
            stage2 = [mid + (back - mid) * i / (n2 + 1) for i in range(1, n2 + 1)]
            total = sum(stage1) + sum(stage2) + mid + back
            active = {2+i for i in range(n1)} | {3+n1+i for i in range(n2)} | {2+n1, 3+n1+n2}
            xs = [l1*.25, l1*.75, l1+l2*.25, l1+l2*.75]
            lines = ["x_mm," + ",".join("basis_"+str(i) for i in range(1, 5+n1+n2))]
            for x in xs:
                target = mid*x/l1 if x <= l1 else mid+(back-mid)*(x-l1)/l2
                values = [format(target/total*10000 if i in active else 0., ".17g") for i in range(1, 5+n1+n2)]
                lines.append(format(x, ".17g") + "," + ",".join(values))
            (run / "results").mkdir(exist_ok=True)
            (run / "results/axis_basis.csv").write_text("\n".join(lines)+"\n", encoding="utf-8", newline="\n")
            plan["producer"] = {"component_plan": {"components": [{"role": "reflectron",
                "identity": {"fixture": "unchanged-flight"}, "operating_voltages_v": {}}]}}
            plan["native_source_status"] = "supported"
            self.write(run / "inputs/compensation_plan.json", plan)
            with patch.object(study, "render_program", return_value="same-existing-program"):
                study.fit_and_plan(run)
            outputs.append(tuple((run / path).read_bytes() for path in ("results/axis_basis.csv",
                "results/monotone_voltage_fit.json", "inputs/reflectron_voltage_profile.lua",
                "inputs/oatof_ideal_grounded.lua")))
        self.assertEqual(outputs[0], outputs[1])

    def test_public_basis_complete_predecessor_reuse_remains_zero_native_and_parent_unchanged(self):
        parent = self.parent({1,2,3,4,5})
        basis, _ = self.public_compensation_plan(True)
        plan = study._load(parent / "inputs/compensation_plan.json")
        plan["response_basis"] = basis["response_basis"]
        self.write(parent / "inputs/compensation_plan.json", plan)
        before = {p: p.read_bytes() for p in parent.rglob("*") if p.is_file()}
        child = self.child(parent)
        plan = study._load(child / "inputs/compensation_plan.json")
        plan["response_basis"] = basis["response_basis"]
        self.write(child / "inputs/compensation_plan.json", plan)
        with patch.object(study, "producer_specification") as native:
            self.assertFalse(self.fit(child)["native_fly_required"])
            native.assert_not_called()
        self.assertFalse((child / "simion").exists())
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_inspect_consumes_only_selected_metadata_and_does_not_hash_published_pa(self) -> None:
        case, executable = self.published_source()
        original = study.verify_record
        calls = []
        def check(name, record, **kwargs):
            path = Path(record["path"])
            self.assertNotIn(".pa", path.name)
            calls.append(path.name)
            return original(name, record, **kwargs)
        with patch.object(study, "verify_record", side_effect=check):
            plan = study.inspect_source(case, executable, 8, 1e-4, particle_count=100)
        self.assertEqual(plan["particle_count"], 100)
        self.assertEqual(len([r for r in plan["runtime_files"] if r["pa"]]), 4)
        self.assertNotIn("unconsumed-report.txt", calls)
        self.assertNotIn("unconsumed-report.txt", [r["relative_path"] for r in plan["runtime_files"]])

    def test_explicit_numerics_uses_manifest_mode_independent_of_request_directory(self) -> None:
        case, executable = self.published_source()
        mode = case / "inputs/mode.json"
        self.write(mode, {"science": "original-frozen-mode"})
        self.write(case / "contracts/candidate_baseline.json", {"baseline": "original"})
        contract = {**CONTRACT, "inputs": {"mode_sha256": file_record(mode)["sha256"]}}
        self.write(case / "contracts/candidate_resolved_geometry.json", contract)
        self.write(case / "simion/resolved_geometry.json", contract)
        outputs = [p for p in case.rglob("*") if p.is_file() and p.name not in {"run_manifest.json", "run_config.json"}]
        self.terminal(case, [], outputs)
        manifest = study._load(case / "run_manifest.json")
        manifest["inputs"]["mode"] = file_record(mode)
        self.write(case / "run_manifest.json", manifest)
        for directory in ("request-a", "request-b"):
            numerics = self.root / directory / "numerics.json"
            self.write(numerics, {"numerics": "same-explicit-request"})
            self.write(numerics.with_name("candidate_science_mode.json"), {"science": "unrelated-neighbor"})
            with patch.object(study, "resolve_contract_documents", side_effect=RuntimeError("resolved frozen mode")) as resolve:
                with self.assertRaisesRegex(RuntimeError, "resolved frozen mode"):
                    study.inspect_source(case, executable, 8, 1e-4, particle_count=100, numerics_path=numerics)
            self.assertEqual(resolve.call_args.args[1], {"science": "original-frozen-mode"})
        mode.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(AssertionError, "byte count changed"):
            study.inspect_source(case, executable, 8, 1e-4, particle_count=100, numerics_path=numerics)

    def test_published_native_family_is_rejected_before_native_or_capacity_entry(self) -> None:
        case, executable = self.published_source()
        response = case / "simion/reflectron.pa1"
        response.write_bytes(b"published-native-family")
        receipt_path = case / "simion/simion_runtime_receipt.json"
        receipt = study._load(receipt_path)
        receipt["files"].append(file_record(response))
        self.write(receipt_path, receipt)
        self.terminal(case, [], [p for p in case.rglob("*") if p.is_file() and p.name not in {"run_manifest.json", "run_config.json"}])
        before = {p: p.read_bytes() for p in case.rglob("*") if p.is_file()}
        with self.assertRaisesRegex(ValueError, "standalone provider"):
            study.inspect_source(case, executable, 8, 1e-4, particle_count=100)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_frozen_scientific_module_imports_its_real_dependencies_without_native_or_pa_copy(self) -> None:
        case, executable = self.published_source()
        plan = study.inspect_source(case, executable, 8, 1e-4, particle_count=100)
        run = self.root / "project/runs/20261030_120006__sim__simion__compensation-frozen"
        (run / "inputs").mkdir(parents=True)
        self.write(run / "inputs/compensation_plan.json", plan)
        result = study.freeze_inputs(run)
        code = Path(result["frozen_code_root"])
        # Explicit input does not depend on the authoring default resource.
        self.assertNotIn("regularization_authoring_source", plan)
        self.assertFalse((code / "src/msplatform/backends/simion/resources/reflectron_voltage_fit_authoring.json").exists())
        command = ("import sys,json;from pathlib import Path;sys.path[:0]=json.loads(sys.argv.pop(1));import "+study.MODULE+
                   " as m;assert Path(m.__file__).resolve()==Path(sys.argv[1])/'src/msplatform/workflows/oa_candidate/run_compensation.py';"
                   "assert all(Path(v.__file__).resolve().is_relative_to(Path(sys.argv[1])/'src') for k,v in sys.modules.items() if k.startswith('msplatform') and getattr(v,'__file__',None));"
                   "spec=m.export_specification(Path(sys.argv[2]));"
                   "assert spec['name']=='reflectron_axis_basis';"
                   "assert Path(spec['argument_list'][3])==Path(sys.argv[1])/m.AXIS_EXPORTER_SOURCE")
        subprocess.run([sys.executable, "-I", "-B", "-c", command,json.dumps(python_import_roots(code)), str(code), str(run)], cwd=code, timeout=60,
                       check=True, capture_output=True, text=True, encoding="utf-8")
        exporter = code / study.AXIS_EXPORTER_SOURCE
        self.assertTrue(exporter.is_file())
        self.assertEqual(Path(study.export_specification(run)["argument_list"][3]), exporter)
        self.assertFalse((code / study.HISTORICAL_AXIS_EXPORTER_SOURCE).exists())
        original = exporter.read_bytes()
        exporter.unlink()
        with self.assertRaisesRegex(ValueError, "frozen candidate source changed"):
            study.export_specification(run)
        for replacement in (None, original + b"tampered"):
            if replacement is not None:
                exporter.write_bytes(replacement)
            rejected = subprocess.run([sys.executable, "-I", "-B", "-c", command, json.dumps(python_import_roots(code)), str(code), str(run)],
                                      cwd=code, timeout=60, capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("frozen candidate source changed", rejected.stderr)
            if replacement is not None:
                with self.assertRaisesRegex(ValueError, "frozen candidate source changed"):
                    study.export_specification(run)
        exporter.write_bytes(original)
        self.assertEqual(Path(study.export_specification(run)["argument_list"][3]), exporter)
        self.assertTrue(result["basis_export_required"])
        self.assertFalse((run / "simion").exists())

    def test_authoring_resource_is_bound_and_frozen_tamper_is_rejected(self) -> None:
        from msplatform.workflows.oa_candidate.candidate_source_closure import verify_candidate_source_closure

        case, executable = self.published_source()
        value, resource, digest = study.load_authoring_default()
        plan = study.inspect_source(case, executable, 8, value, particle_count=100)
        plan["regularization_authoring_source"] = file_record(resource)
        self.assertEqual(plan["regularization_authoring_source"]["sha256"].lower(), digest)
        run = self.root / "project/runs/20261030_120010__sim__simion__compensation-authoring"
        self.write(run / "inputs/compensation_plan.json", plan)
        study.freeze_inputs(run)
        frozen = run / "inputs/code/src/msplatform/backends/simion/resources/reflectron_voltage_fit_authoring.json"
        self.assertEqual(frozen.read_bytes(), resource.read_bytes())
        closure = study._load(run / "inputs/source_closure.json")
        verify_candidate_source_closure(closure)
        frozen.write_bytes(frozen.read_bytes() + b" ")
        with self.assertRaises((ValueError, AssertionError)):
            verify_candidate_source_closure(closure)

    def test_missing_selected_authoring_source_rejects_freeze(self) -> None:
        case, executable = self.published_source()
        plan = study.inspect_source(case, executable, 8, 0.0001, particle_count=100)
        resource = self.root / "selected-authoring.json"
        resource.write_text("selected", encoding="utf-8")
        plan["regularization_authoring_source"] = file_record(resource)
        resource.unlink()
        run = self.root / "project/runs/20261030_120011__sim__simion__compensation-missing"
        self.write(run / "inputs/compensation_plan.json", plan)
        with self.assertRaises((FileNotFoundError, ValueError, AssertionError)):
            study.freeze_inputs(run)

    def test_formal_first_batch_source_is_retained_after_adaptive_partition(self) -> None:
        from msplatform.execution.simion_dispatch import plan_adaptive_followup
        run = self.fixture("20261030_120005__sim__simion__compensation-first")
        self.fit(run)
        first = study.materialize_batches(run, "baseline")["batches"][0]
        ion = Path(first["ion"])
        allocation = first["argument_list"][first["argument_list"].index("--default-num-particles") + 1]
        self.assertGreaterEqual(int(allocation), 100)
        self.assertEqual(len(ion.read_text(encoding="ascii").splitlines()), first["batch"]["count"])
        before = (ion.read_bytes(), ion.stat().st_mtime_ns)
        dispatch = study._load(run / "results/baseline.dispatch_plan.json")
        followup = plan_adaptive_followup(dispatch, 20*1024**3, first_batch_completed=True)
        study._write_json(run / "results/baseline.dispatch_plan.json", followup)
        cases = study.materialize_batches(run, "baseline")["batches"]
        self.assertEqual(cases[0]["batch"], first["batch"])
        self.assertEqual((ion.read_bytes(), ion.stat().st_mtime_ns), before)
        self.assertEqual(sum(c["batch"]["count"] for c in cases), 1000)

    def test_predecessor_bytecode_evidence_is_derived_separately_from_current_code(self) -> None:
        import py_compile
        from msplatform.workflows.oa_candidate.candidate_source_closure import verify_candidate_source_closure

        case, executable = self.published_source()
        plan = study.inspect_source(case, executable, 8, 1e-4, particle_count=100)
        parent = self.root / "parent"
        self.write(parent / "inputs/compensation_plan.json", plan)
        study.freeze_inputs(parent)
        source = parent / "inputs/code/src/msplatform/io/file_identity.py"
        py_compile.compile(str(source), doraise=True)
        self.terminal(parent, [p for p in (parent / "inputs").rglob("*") if p.is_file()], [])
        before = {p: p.read_bytes() for p in parent.rglob("*") if p.is_file()}
        with self.assertRaisesRegex(ValueError, "extra files"):
            verify_candidate_source_closure(study._load(parent / "inputs/source_closure.json"))
        child = self.root / "child"
        self.write(child / "inputs/compensation_plan.json", {**plan, "predecessor_manifest": file_record(parent / "run_manifest.json")})
        study.freeze_inputs(child)
        evidence = child / "inputs/predecessor_source_closure"
        derived = study._load(evidence / "source_closure.json")
        verify_candidate_source_closure(derived)
        verify_candidate_source_closure(study._load(child / "inputs/source_closure.json"))
        self.assertEqual(len(study._load(evidence / "derivation.json")["validated_bytecode"]), 1)
        self.assertEqual(Path(derived["code_root"]), evidence / "code")
        self.assertFalse(list((evidence / "code").rglob("*.pyc")))
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_historical_declared_exporter_reuses_manifest_bound_basis(self) -> None:
        case, executable = self.published_source()
        plan = study.inspect_source(case, executable, 8, 1e-4, particle_count=100)
        parent = self.root / "historical-parent"
        self.write(parent / "inputs/compensation_plan.json", plan)
        study.freeze_inputs(parent)
        closure_path = parent / "inputs/source_closure.json"
        closure = study._load(closure_path)
        code = Path(closure["code_root"])
        current = code / study.AXIS_EXPORTER_SOURCE
        historical = code / study.HISTORICAL_AXIS_EXPORTER_SOURCE
        historical.parent.mkdir(parents=True, exist_ok=True)
        current.replace(historical)
        record = next(item for item in closure["sources"] if item["source_id"] == study.AXIS_EXPORTER_SOURCE)
        record["source_id"] = study.HISTORICAL_AXIS_EXPORTER_SOURCE
        self.write(closure_path, closure)
        basis = parent / "results/axis_basis.csv"
        basis.parent.mkdir(parents=True, exist_ok=True)
        basis.write_bytes(b"historical-basis")
        self.terminal(parent, [p for p in (parent / "inputs").rglob("*") if p.is_file()], [basis])
        before = {p: p.read_bytes() for p in parent.rglob("*") if p.is_file()}
        child = self.root / "historical-child"
        (child / "results").mkdir(parents=True)
        self.write(child / "inputs/compensation_plan.json", {**plan, "predecessor_manifest": file_record(parent / "run_manifest.json")})
        self.assertFalse(study.freeze_inputs(child)["basis_export_required"])
        self.assertEqual((child / "results/axis_basis.csv").read_bytes(), b"historical-basis")
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        original = historical.read_bytes()
        for name, replacement in (("missing", None), ("tampered", original + b"tampered")):
            if replacement is None:
                historical.unlink()
            else:
                historical.write_bytes(replacement)
            rejected = self.root / ("historical-child-" + name)
            self.write(rejected / "inputs/compensation_plan.json", {**plan, "predecessor_manifest": file_record(parent / "run_manifest.json")})
            with self.assertRaises((FileNotFoundError, ValueError, AssertionError)):
                study.freeze_inputs(rejected)
            historical.write_bytes(original)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        historical.write_bytes(original + b"-- different historical exporter\n")
        identity = file_record(historical)
        record.update(bytes=identity["bytes"], sha256=identity["sha256"], source_sha256=identity["sha256"])
        self.write(closure_path, closure)
        self.terminal(parent, [p for p in (parent / "inputs").rglob("*") if p.is_file()], [basis])
        different = self.root / "historical-child-different"
        self.write(different / "inputs/compensation_plan.json", {**plan, "predecessor_manifest": file_record(parent / "run_manifest.json")})
        with self.assertRaisesRegex(ValueError, "axis basis exporter differs"):
            study.freeze_inputs(different)

    def test_predecessor_exporter_identity_requires_one_declared_source(self) -> None:
        closure = {"schema_version": 2, "role": "candidate_execution_source_closure", "code_root": str(self.root), "sources": []}
        with self.assertRaisesRegex(ValueError, "exactly one"):
            study._predecessor_axis_exporter(closure)
        closure["sources"] = [{"source_id": name} for name in (study.AXIS_EXPORTER_SOURCE, study.HISTORICAL_AXIS_EXPORTER_SOURCE)]
        with self.assertRaisesRegex(ValueError, "exactly one"):
            study._predecessor_axis_exporter(closure)

    def test_real_compensation_analysis_consumes_detector_census(self) -> None:
        run = self.root / "census-consumer"
        ion, log = run / "inputs/source.ion", run / "logs/flight.log"
        ion.parent.mkdir(parents=True)
        log.parent.mkdir(parents=True)
        ion.write_text("0,524,1,0,0,0,0,0,5,1,0\n" * 3, encoding="ascii")
        log.write_text("".join(
            f"TRACE: detector_crossing ion={i} t={t} x=0 y=0 z=0 r=0 zmax=4\n"
            for i, t in ((1, 9), (2, 10), (3, 11))), encoding="utf-8")
        self.write(run / "inputs/compensation_plan.json", {"particle_count": 3, "source": {}})
        self.write(run / "results/monotone_voltage_fit.json", {"fixed_endpoints_V": {}, "fit": {}})
        batch = {"simion_particle_id_offset": 0}
        for label in study.LABELS:
            name = label + "-unit"
            self.write(run / f"results/{label}.batches.json", {"batches": [
                {"name": name, "batch": batch, "stdout_path": str(log), "ion": str(ion)}]})
            self.write(run / f"results/native_batch_completion/{name}.json",
                       {"batch": batch, "natural_exit": True, "exit_code": 0})
        result = study.analyze(run)
        for label in study.LABELS:
            self.assertEqual(result["modes"][label]["hit"], 3)
            self.assertEqual(result["modes"][label]["batches"][0]["HitParticleIds"], [1, 2, 3])
            self.assertTrue((run / f"results/{label}_particles.csv").is_file())
        self.assertEqual(result["qualification"], "study_only; no geometry, grid, step or resolution qualification promoted")

    def test_analysis_failure_leaves_complete_native_units_reusable(self) -> None:
        parent = self.parent({1, 2, 3, 4, 5})
        before = {p: p.read_bytes() for p in parent.rglob("*") if p.is_file()}
        with patch.object(study.detector_census, "analyze_simion_log", side_effect=ValueError("analysis failure")):
            with self.assertRaisesRegex(ValueError, "analysis failure"):
                study.analyze(parent)
        child = self.child(parent)
        result = self.fit(child)
        self.assertFalse(result["native_fly_required"])
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_n100_first_batch_keeps_ten_source_rows_with_supported_native_capacity(self) -> None:
        run = self.fixture("20261030_120009__sim__simion__compensation-small-first")
        plan = study._plan(run)
        plan["particle_count"] = 100
        self.write(run / "inputs/compensation_plan.json", plan)
        source = run / "inputs/source.ion"
        source.write_text("\n".join(source.read_text(encoding="ascii").splitlines()[:100])+"\n", encoding="ascii")
        self.fit(run)
        first = study.materialize_batches(run, "baseline")["batches"][0]
        self.assertEqual(first["batch"]["count"], 10)
        self.assertEqual(len(Path(first["ion"]).read_text(encoding="ascii").splitlines()), 10)
        arguments = first["argument_list"]
        self.assertEqual(arguments[arguments.index("--default-num-particles")+1], "100")

    def test_missing_case_fails_before_private_execution(self) -> None:
        with patch.object(sys, "argv", ["run_compensation", "--case-dir", str(self.root)]), patch("msplatform.execution.process_observation.run_observed_process") as native:
            with self.assertRaises(FileNotFoundError):
                study.main()
        native.assert_not_called()

    def test_help_does_not_start_a_process(self) -> None:
        with patch.object(sys, "argv", ["run_compensation", "--help"]), patch("msplatform.execution.process_observation.run_observed_process") as native:
            with self.assertRaises(SystemExit) as exited:
                study.main()
        self.assertEqual(exited.exception.code, 0)
        native.assert_not_called()

    def test_profile_renderer_preserves_scientific_counts_and_voltages(self) -> None:
        profile = render_lua_profile(FIT)
        self.assertIn("stage1_count = 2", profile)
        self.assertIn("stage1_ring_voltages_V = {100, 200}", profile)
        self.assertIn("stage2_ring_voltages_V = {300, 400}", profile)

    def test_safe_producer_spec_uses_actual_owner_session_original_ion_and_same_host_parameters(self) -> None:
        run = self.fixture("20261030_120007__sim__simion__compensation-producer")
        plan = study._plan(run)
        plan["producer"]["source_gui_seed"] = 17
        plan["protected_cache_keys"] = ["ABC"]
        self.write(run / "inputs/compensation_plan.json", plan)
        session = run / "results/capacity.json"
        self.write(session, {"schema_version": 1, "role": "artifact_workflow_capacity_session", "status": "active",
                             "protected_paths": [str(run)], "protected_cache_keys": ["abc"]})
        with patch.object(study, "prepare_consumers") as prepare:
            specification = study.producer_specification(run, session, "A"*64)
        prepare.assert_called_once_with(run / "inputs/candidate_resolved_geometry.json", run / "inputs/producer_text", particle_source_seed=17, science_root=study.PROJECT_ROOT)
        self.assertEqual(specification["parameters"]["SourceIonPath"], str(run / "inputs/source.ion"))
        self.assertEqual(specification["parameters"]["CapacitySessionPath"], str(session.resolve()))
        self.assertTrue(specification["parameters"]["DeferRunFinalization"])
        self.assertTrue(specification["script_path"].endswith("build_formal_delivery.ps1"))
        self.write(session, {"role": "artifact_workflow_capacity_session", "status": "active", "protected_paths": [], "protected_cache_keys": ["abc"]})
        with patch.object(study, "prepare_consumers") as prepare, self.assertRaisesRegex(ValueError, "protected capacity"):
            study.producer_specification(run, session, "A"*64)
        prepare.assert_not_called()

    def test_safe_producer_completion_binds_actual_controls_original_source_and_writer(self) -> None:
        run = self.fixture("20261030_120008__sim__simion__compensation-producer-completion")
        self.fit(run)
        plan = study._plan(run)
        plan["producer"]["component_plan"]["components"][0]["cacheable"] = False
        self.write(run / "inputs/compensation_plan.json", plan)
        runtime = run / "simion"
        runtime.mkdir()
        iob = runtime / "oatof_ideal_grounded.iob"
        iob.write_bytes(b"producer-verified-original-template-new-field-bindings")
        iob.with_suffix(".lua").write_bytes((run / "inputs/oatof_ideal_grounded.lua").read_bytes())
        ion = runtime / "oatof_comsol_524amu_gaussian_N1000.ion"
        ion.write_bytes((run / "inputs/source.ion").read_bytes())
        self.write(runtime / "simion_runtime_receipt.json", {"role": "oatof_simion_private_runtime", "status": "verified",
            "run_id": run.name, "context_sha256": "A"*64, "canonical_iob_verified": True,
            "published_native_members_opened": False, "iob": {"path": str(iob)}, "source_ion_reused": True,
            "source_ion": file_record(ion), "components": [{"role": "reflectron", "source": "fresh_frozen_fractional_gem"}]})
        managed = {"schema_version": 1, "role": "repository_managed_python_completion", "exit_code": 0,
            "worker_process_id": 42, "worker_started_at_utc_ticks": 77,
            **{k: True for k in ("ownership_confirmed", "worker_exit_confirmed", "launcher_exit_confirmed", "stdout_drained", "stderr_drained")}}
        self.write(run / "results/field_provider_completion.json", {"schema_version": 1, "role": "oatof_component_build_completion",
            "run_id": run.name, "context_sha256": "A"*64, "exception": None,
            "operations": [{"operation_id": "build", "observation": {"exit_confirmed": True, "returncode": 0}, "managed_process_completion": managed}]})
        result = study.producer_completion(run, "A"*64)
        self.assertIsNone(result["failure_reason"])
        self.assertTrue(result["writers_stopped"])
        self.assertTrue(result["iob_ready"])
        self.assertEqual(result["control_binding"], {"iob_path": str(iob), "program_path": str(iob.with_suffix(".lua")), "source_ion_path": str(run / "inputs/source.ion")})
        self.assertEqual(result["writer_completion"]["operations"][0]["observation"]["process_id"], 42)
        self.assertEqual((runtime / "reflectron_voltage_profile.lua").read_bytes(), (run / "inputs/reflectron_voltage_profile.lua").read_bytes())
        iob.with_suffix(".lua").write_text("wrong-program", encoding="utf-8")
        failed = study.producer_completion(run, "A"*64)
        self.assertTrue(failed["writers_stopped"])
        self.assertFalse(failed["iob_ready"])
        self.assertIn("Program/profile differs", failed["failure_reason"])

    def test_missing_producer_completion_keeps_writer_unknown_without_iob_claim(self) -> None:
        run = self.fixture("20261030_120009__sim__simion__compensation-producer-unknown")
        result = study.producer_completion(run, "A"*64)
        self.assertFalse(result["writers_stopped"])
        self.assertFalse(result["iob_ready"])
        self.assertFalse(result["writer_completion"]["operations"][0]["observation"]["exit_confirmed"])


class CompensationAuthoringBoundaryTests(unittest.TestCase):
    def test_inspect_records_default_and_preserves_explicit_zero(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        with tempfile.TemporaryDirectory() as directory:
            resource = Path(directory) / "authoring.json"
            resource.write_text("test-authoring", encoding="utf-8")
            record = file_record(resource)
            base = ["compensation", "--action", "inspect", "--case-dir", directory]
            for option, value in (([], 0.0001), (["--regularization", "0"], 0.0),
                                  (["--regularization", "0.25"], 0.25)):
                with (self.subTest(option=option), patch.object(sys, "argv", base + option),
                      patch.object(study, "load_authoring_default",
                                   return_value=(0.0001, resource, record["sha256"].lower())) as load,
                      patch.object(study, "inspect_source", return_value={}) as inspect,
                      redirect_stdout(StringIO()) as output):
                    study.main()
                self.assertEqual(inspect.call_args.args[3], value)
                parsed = json.loads(output.getvalue())
                if option:
                    load.assert_not_called()
                    self.assertNotIn("regularization_authoring_source", parsed)
                else:
                    load.assert_called_once()
                    self.assertEqual(parsed["regularization_authoring_source"]["sha256"], record["sha256"])

    def test_inspect_missing_authoring_resource_fails_closed(self) -> None:
        with (patch.object(sys, "argv", ["compensation", "--action", "inspect"]),
              patch.object(study, "load_authoring_default", side_effect=FileNotFoundError("missing")),
              patch.object(study, "inspect_source") as inspect):
            with self.assertRaises(FileNotFoundError):
                study.main()
            inspect.assert_not_called()

    def test_new_continuation_resolves_current_omitted_authoring(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        with tempfile.TemporaryDirectory() as directory:
            resource = Path(directory) / "authoring.json"
            resource.write_text("authoring", encoding="utf-8")
            digest = file_record(resource)["sha256"].lower()
            predecessor = Path(directory) / "run_manifest.json"
            args = ["compensation", "--action", "inspect", "--case-dir", directory,
                    "--resume-from", str(predecessor)]
            with (patch.object(sys, "argv", args),
                  patch.object(study, "load_authoring_default", return_value=(0.0001, resource, digest)) as load,
                  patch.object(study, "inspect_source", return_value={}) as inspect,
                  redirect_stdout(StringIO()) as output):
                study.main()
            load.assert_called_once()
            self.assertEqual(inspect.call_args.args[3:5], (0.0001, predecessor))
            self.assertEqual(json.loads(output.getvalue())["regularization_authoring_source"]["sha256"].lower(), digest)

    def test_frozen_fit_action_does_not_resolve_current_authoring(self) -> None:
        with (patch.object(sys, "argv", ["compensation", "--action", "fit", "--run", "."]),
              patch.object(study, "load_authoring_default", side_effect=AssertionError("unexpected authoring read")),
              patch.object(study, "fit_and_plan", return_value={}) as fit,
              patch("builtins.print")):
            study.main()
            fit.assert_called_once()

    def test_inspect_rejects_changed_authoring_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            resource = Path(directory) / "authoring.json"
            resource.write_text("changed", encoding="utf-8")
            with (patch.object(sys, "argv", ["compensation", "--action", "inspect"]),
                  patch.object(study, "load_authoring_default",
                               return_value=(0.0001, resource, "0" * 64)),
                  patch.object(study, "inspect_source") as inspect):
                with self.assertRaisesRegex(ValueError, "changed during resolution"):
                    study.main()
                inspect.assert_not_called()

    def test_finalization_does_not_load_authoring_resource(self) -> None:
        def complete(command, **kwargs):
            kwargs["stdout"].write_text("", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0), None

        with (patch.object(sys, "argv", ["compensation", "--resume-finalization", "--run-id", "existing"]),
              patch.object(study, "load_authoring_default") as load,
              patch("msplatform.execution.process_observation.run_observed_process", side_effect=complete) as launch):
            study.main()
            load.assert_not_called()
            self.assertIn("-ResumeFinalization", launch.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
