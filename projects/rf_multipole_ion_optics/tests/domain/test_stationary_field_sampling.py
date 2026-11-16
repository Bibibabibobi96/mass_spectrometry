"""Tests for solver-neutral multipole stationary-field sampling."""

from __future__ import annotations

import csv
import json
import math
import tempfile
import unittest
from pathlib import Path
from typing import Any

from msplatform.components.rf_multipole.stationary_field_sampling import (
    FIELD_OUTPUT_COLUMNS,
    StationaryFieldContractError,
    compare_stationary_field_outputs,
    generate_stationary_field_sample_rows,
    load_stationary_field_output_csv,
    validate_stationary_bvp,
    validate_stationary_output_authority,
)
from msplatform.workflows.rf_stationary import main


def _resolved_design() -> dict[str, Any]:
    rods = []
    for index in range(6):
        angle = index * math.pi / 3
        rods.append(
            {
                "center_x_mm": 6.0 * math.cos(angle),
                "center_y_mm": 6.0 * math.sin(angle),
                "radius_mm": 2.0,
                "electrode_group": index % 2 + 1,
            }
        )
    return {
        "schema_version": 3,
        "role": "multipole_resolved_design_do_not_edit",
        "units": {"length": "mm"},
        "coordinate": {
            "coordinate_id": "multipole_canonical_xyz",
            "axial_axis": "+z",
        },
        "geometry_mm": {
            "inscribed_radius_r0": 4.0,
            "rod_z_min": 0.0,
            "rod_z_max": 10.0,
            "rod_array": {"rods": rods},
            "enclosure": {"model":"bare"},
            "numerical_domain": {"radius_mm":12.0,"z_min_mm":-1.0,"z_max_mm":12.0,"working_region_radius_mm":3.0},
            "observations": {"release_plane_z_mm":-1.5,"handoff_plane_z_mm":11.,"census_plane_z_mm":11.5,"acceptance_radius_mm":3.},
        },

    }


def _sampling_plan() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "role": "multipole_stationary_field_sampling_plan",
        "coordinate_id": "multipole_canonical_xyz",
        "units": {
            "length": "mm",
            "potential": "V",
            "electric_field": "V/m",
        },
        "axial_sampling": {
            "uniform_range": "rod_span",
            "uniform_sample_count": 3,
            "named_plane_ids": [
                "canonical_handoff_plane",
                "source_release_plane",
                "rod_exit",
            ],
        },
        "cross_section_sampling": {
            "rod_inward_clear_radius_fractions": [0.0, 0.5, 0.9],
            "azimuth_count": 4,
        },
        "bvp": {
            "domain": "resolved_design.geometry_mm.numerical_domain",
            "exterior": "zero_normal_electric_field",
            "electrode_voltages_v_by_group": {
                "differential": {"1":100.0,"2":-100.0},
                "static": {"1":0.0,"2":0.0},
            },
        },
        "potential_reference": "zero_mean_conductor_voltage",
    }


def _field_rows(
    potential_scale: float = 1.0,
    field_scale: float = 1.0,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    points = (
        ("p0", "entrance_aperture_plate_downstream_face", 0.0, 0.0, 0.0),
        ("p1", "rod_span_uniform", 1.0, -1.0, 5.0),
    )
    for field_case in ("differential", "static"):
        case_scale = 1.0 if field_case == "differential" else 2.0
        for index, (point_id, region, x_mm, y_mm, z_mm) in enumerate(
            points, start=1
        ):
            rows.append(
                {
                    "sample_id": point_id,
                    "region": region,
                    "field_case": field_case,
                    "x_mm": str(x_mm),
                    "y_mm": str(y_mm),
                    "z_mm": str(z_mm),
                    "potential_V": str(
                        potential_scale * case_scale * index
                    ),
                    "Ex_V_per_m": str(field_scale * case_scale * index),
                    "Ey_V_per_m": str(
                        field_scale * case_scale * (index + 1)
                    ),
                    "Ez_V_per_m": str(
                        field_scale * case_scale * (index + 2)
                    ),
                }
            )
    return rows


class StationaryFieldSamplingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def _write_rows(
        self,
        name: str,
        rows: list[dict[str, str]],
        columns: tuple[str, ...] = FIELD_OUTPUT_COLUMNS,
    ) -> Path:
        path = self.root / name
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_generation_is_deterministic_and_inside_clear_radius(self) -> None:
        first = generate_stationary_field_sample_rows(
            _resolved_design(), _sampling_plan()
        )
        second = generate_stationary_field_sample_rows(
            _resolved_design(), _sampling_plan()
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 6 * (1 + 4 + 4))
        self.assertEqual(tuple(first[0]), (
            "sample_id", "region", "x_mm", "y_mm", "z_mm"
        ))
        self.assertEqual(
            [row["region"] for row in first][::9],
            [
                "rod_span_uniform",
                "rod_span_uniform",
                "rod_span_uniform",
                "source_release_plane",
                "rod_exit",
                "canonical_handoff_plane",
            ],
        )
        self.assertEqual(len({str(row["sample_id"]) for row in first}), len(first))
        for row in first:
            self.assertLess(
                math.hypot(float(row["x_mm"]), float(row["y_mm"])), 4.0
            )

    def test_plan_rejects_unknown_alias_and_boundary_fraction(self) -> None:
        plan = _sampling_plan()
        plan["cross_section_sampling"]["radius_fractions"] = [0.0]
        with self.assertRaisesRegex(
            StationaryFieldContractError, "fields differ"
        ):
            generate_stationary_field_sample_rows(_resolved_design(), plan)
        plan = _sampling_plan()
        plan["cross_section_sampling"][
            "rod_inward_clear_radius_fractions"
        ] = [0.0, 1.0]
        with self.assertRaisesRegex(StationaryFieldContractError, r"\[0, 1\)"):
            generate_stationary_field_sample_rows(_resolved_design(), plan)

    def test_bvp_requires_actual_exterior_reference_and_conductor_voltages(self):
        for case in ("missing", "exterior", "reference", "voltage", "grounded"):
            plan = _sampling_plan()
            resolved = _resolved_design()
            if case == "missing": plan.pop("bvp")
            elif case == "exterior": plan["bvp"]["exterior"] = "ground"
            elif case == "reference": plan["potential_reference"] = "outer_shell"
            elif case == "voltage": plan["bvp"]["electrode_voltages_v_by_group"]["differential"]["1"] = 1.0
            else: resolved["geometry_mm"]["enclosure"]["model"] = "cylindrical_grounded_shell"
            with self.subTest(case=case), self.assertRaises(StationaryFieldContractError):
                validate_stationary_bvp(resolved, plan)

    def test_authority_binds_common_points_and_rejects_native_tamper(self):
        resolved_path = self.root/"resolved.json"; plan_path = self.root/"plan.json"; points_path = self.root/"points.csv"
        resolved_path.write_text(json.dumps(_resolved_design()), encoding="utf-8")
        plan_path.write_text(json.dumps(_sampling_plan()), encoding="utf-8")
        self.assertEqual(main(["generate","--resolved-design",str(resolved_path),"--sampling-plan",str(plan_path),"--output",str(points_path)]),0)
        authority_path = self.root/"authority.json"
        self.assertEqual(main(["authorize","--resolved-design",str(resolved_path),"--sampling-plan",str(plan_path),
            "--points",str(points_path),"--source-id","pure-fixture","--output",str(authority_path)]),0)
        authority = json.loads(authority_path.read_text(encoding="utf-8"))
        self.assertEqual(authority["bvp_by_case"]["differential"]["electrode_voltages_v_by_group"],{"1":100.0,"2":-100.0})
        self.assertEqual(authority["potential_reference"],"zero_mean_conductor_voltage")
        with points_path.open(encoding="utf-8",newline="") as stream: points=list(csv.DictReader(stream))
        rows=[]
        for field_case in ("differential","static"):
            for point in points:
                rows.append(dict(point,field_case=field_case,potential_V="0",Ex_V_per_m="0",Ey_V_per_m="0",Ez_V_per_m="0"))
        output=self._write_rows("authorized.csv",rows)
        validation=self.root/"validation.json"
        self.assertEqual(main(["validate","--input",str(output),"--output",str(validation),"--authority",str(authority_path)]),0)
        candidate=json.loads(json.dumps(authority));candidate["source"]["source_id"]="independent-fixture"
        candidate_path=self.root/"candidate-authority.json";candidate_path.write_text(json.dumps(candidate),encoding="utf-8")
        comparison_authority=self.root/"comparison-authority.json"
        self.assertEqual(main(["comparison-authority","--reference-authority",str(authority_path),
            "--candidate-authority",str(candidate_path),"--coordinate-tolerance-mm","0","--output",str(comparison_authority)]),0)
        compared=self.root/"compared.json"
        self.assertEqual(main(["compare","--reference",str(output),"--candidate",str(output),
            "--comparison-authority",str(comparison_authority),"--output",str(compared)]),0)
        result=json.loads(compared.read_text(encoding="utf-8"))
        self.assertEqual(result["field_cases"]["differential"]["paired_valid_count"],len(points))
        candidate["bvp_by_case"]["static"]["exterior"]="ground"
        candidate_path.write_text(json.dumps(candidate),encoding="utf-8")
        with self.assertRaisesRegex(StationaryFieldContractError,"bvp_by_case"):
            main(["comparison-authority","--reference-authority",str(authority_path),
                "--candidate-authority",str(candidate_path),"--coordinate-tolerance-mm","0","--output",str(comparison_authority)])
        rows[0]["x_mm"]="12345"
        tampered=self._write_rows("tampered.csv",rows)
        with self.assertRaisesRegex(StationaryFieldContractError,"identity|coordinates"):
            validate_stationary_output_authority(authority,tampered)

    def test_installed_backend_resources_replace_project_stationary_duplicates(self):
        import msplatform.components.rf_multipole.stationary_field_sampling as component
        import msplatform.workflows.rf_stationary as workflow
        from msplatform.backends.simion.resources import native_resource_path
        root=Path(__file__).resolve().parents[2]
        repo=root.parents[1]
        self.assertTrue(Path(component.__file__).resolve().is_relative_to(repo/"src"))
        self.assertTrue(Path(workflow.__file__).resolve().is_relative_to(repo/"src"))
        self.assertEqual(native_resource_path("export_stationary_field_samples.lua").name,
                         "export_stationary_field_samples.lua")
        self.assertTrue((repo/"src/msplatform/backends/comsol/matlab/export_comsol_stationary_field_samples.m").is_file())
        self.assertFalse((root/"analysis/stationary_field_sampling.py").exists())
        self.assertFalse((root/"comsol/export_comsol_stationary_field_samples.m").exists())
        self.assertFalse((root/"simion/export_stationary_field_samples.lua").exists())

    def test_installed_preregistration_binds_authorities_and_implementation(self):
        import hashlib
        from msplatform.workflows.rf_stationary import validate_preregistration
        repo=Path(__file__).resolve().parents[4]
        project=repo/"projects/rf_multipole_ion_optics"
        budget=self.root/"budget.json";budget.write_text("{}",encoding="utf-8")
        plan=project/"config/contracts/stationary_field_sampling_plan.json"
        digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest().upper()
        implementation=[repo/"src/msplatform/workflows/rf_stationary.py",
            repo/"src/msplatform/components/rf_multipole/stationary_field_sampling.py",
            repo/"src/msplatform/backends/comsol/matlab/export_comsol_stationary_field_samples.m",
            repo/"src/msplatform/backends/simion/resources/export_stationary_field_samples.lua"]
        authorities={"runtime_profiles_sha256":project/"config/runtime_profiles.json",
            "engineering_budget_sha256":budget,"particle_source_profiles_sha256":project/"config/particle_source_profiles.json",
            "design_profiles_sha256":project/"config/design_profiles.json",
            "simion_solver_numerics_sha256":project/"config/simion_solver_numerics.json"}
        tokens=["CHECKPOINT=MESH_COMPLETE","CHECKPOINT=STATIONARY_FIELDS_COMPLETE",
            "CHECKPOINT=STATIONARY_FIELD_SAMPLES_COMPLETE","STOP_STAGE=field_solve",
            "PARTICLE_PHYSICS_CREATED=0","PARTICLE_STUDIES_CREATED=0",
            "FIELD_SOLVE_DIAGNOSTIC=PASS","STATUS=PASS"]
        document={"schema_version":2,"role":"multipole_simion_field_solver_isolation_preregistration",
            "status":"authorized_not_run","project_id":"rf_multipole_ion_optics","preregistered_before_run":True,
            "authorization":{"maximum_commercial_run_count":1,"automatic_retry_count":0,"planned_run_id":"fixture",
                "runtime_profile_id":"fixture-profile","design_profile_id":"fixture-design",
                "particle_source_profile_id":"fixture-source","simion_solver_numerics_profile_id":"fixture-numerics",
                "stop_stage":"field_solve","retention_class":"solver_review"},
            "frozen_identity":{"expected_run_parent_resolved_design_sha256":"A"*64,
                **{key:digest(path) for key,path in authorities.items()}},
            "frozen_implementation":{"files":[{"path":str(path.resolve()),"sha256":digest(path)} for path in implementation]},
            "field_sampling":{"role":"multipole_stationary_field_sampling","expected_point_count":1,"expected_row_count":2,
                "field_cases":["differential","static"],"plan_path":str(plan),"plan_sha256":digest(plan)},
            "required_report":{"tokens":tokens,"forbidden_checkpoints":["PRIMARY_PARTICLE_CASE_COMPLETE","CONTROL_PARTICLE_CASE_COMPLETE"]}}
        arguments=dict(solver="simion",run_id="fixture",runtime_profile_id="fixture-profile",
            design_profile_id="fixture-design",particle_source_profile_id="fixture-source",
            solver_numerics_profile_id="fixture-numerics",retention_class="solver_review",
            expected_resolved_sha256="A"*64,authority_paths=authorities,implementation_paths=implementation)
        self.assertEqual(validate_preregistration(document,**arguments)["authorization"]["planned_run_id"],"fixture")
        with self.assertRaisesRegex(ValueError,"identity or authorization"):
            validate_preregistration(document,**dict(arguments,solver="comsol"))
        budget.write_text("changed",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"authority hash"):
            validate_preregistration(document,**arguments)

    def test_installed_saved_comsol_action_reaches_frozen_export_invocation(self):
        import sys
        from msplatform.io.manifest_records import file_record
        from msplatform.workflows.rf_stationary import execute_saved_comsol
        resolved_path=self.root/"saved-resolved.json";plan_path=self.root/"saved-plan.json"
        resolved_path.write_text(json.dumps(_resolved_design()),encoding="utf-8")
        plan_path.write_text(json.dumps(_sampling_plan()),encoding="utf-8")
        model=self.root/"parent.mph";model.write_bytes(b"inert-saved-model")
        class Session:
            def __init__(session):
                session.expected_operation_ids=("export_saved_stationary",)
                session.input_dir=self.root/"saved-inputs";session.result_dir=self.root/"saved-results"
                session.log_dir=self.root/"saved-logs";session.run_dir=self.root/"saved-run";session.run_id="inert-saved"
                session.artifact_run_dir=session.run_dir
                session.context=type("Context",(),{"workspace":self.root,"python_executable":Path(sys.executable),
                    "host_state_path":self.root/"host.sqlite3","policy_path":self.root/"policy.json",
                    "powershell_executable":Path(sys.executable),
                    "tools":{"comsol_launcher":model,"matlab_root":self.root}})()
                session.invocations=[]
            def declare_file(session,path,role):
                path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);return path
            def canonical_path(session,path):return Path(path)
            def add_input(session,name,record):pass
            def run_process(session,operation,**kwargs):
                session.invocations.append((operation,kwargs))
                task=Path(kwargs["arguments"][kwargs["arguments"].index("-TaskScript")+1])
                text=task.read_text(encoding="utf-8")
                if "read_rf_saved_stationary_solution(request)" not in text:
                    raise AssertionError("canonical saved export invocation was not reached")
                with (session.input_dir/"stationary_field_sample_points.csv").open(encoding="utf-8",newline="") as point_stream:
                    points=list(csv.DictReader(point_stream))
                samples=session.result_dir/"stationary_field_samples.csv"
                with samples.open("w",encoding="utf-8",newline="") as stream:
                    writer=csv.DictWriter(stream,fieldnames=FIELD_OUTPUT_COLUMNS);writer.writeheader()
                    for field_case in ("differential","static"):
                        for point in points:
                            writer.writerow(dict(point,field_case=field_case,potential_V="0",
                                Ex_V_per_m="0",Ey_V_per_m="0",Ez_V_per_m="0"))
                (session.result_dir/"saved_stationary_export.json").write_text(json.dumps({
                    "native_solves":0,"parent_model_saved":False,"stationary_field_row_count":2*len(points)}),encoding="utf-8")
                (session.log_dir/"saved_stationary.bootstrap.log").write_text("STATUS=PASS\n",encoding="utf-8")
                (session.log_dir/"saved_stationary.launcher.json").write_text(json.dumps({
                    "schema_version":1,"role":"comsol_launcher_completion","run_id":session.run_id,
                    "operations":[{"observation":{"exit_confirmed":True,"returncode":0,"process_id":1,
                        "process_started_at_utc_ticks":1}}],
                    "host_release":{"inherited":True,"error":None}}),encoding="utf-8")
        session=Session()
        result=execute_saved_comsol(session,parent_manifest={},model_record=file_record(model,"solver_native_binary"),
            resolved_source=resolved_path,plan_source=plan_path,limits={},source_id="inert-saved")
        self.assertEqual(result["summary"]["native_solves"],0)
        self.assertFalse(result["summary"]["parent_model_saved"])
        self.assertEqual(len(session.invocations),1)
        self.assertEqual(json.loads((session.result_dir/"stationary_field_sample_validation.json").read_text(encoding="utf-8-sig"))["status"],"PASS")

    def test_installed_simion_action_samples_and_validates_without_iob_or_fly(self):
        from msplatform.workflows.rf_stationary import execute_simion_samples
        resolved_path=self.root/"resolved.json";plan_path=self.root/"plan.json"
        resolved_path.write_text(json.dumps(_resolved_design()),encoding="utf-8")
        plan_path.write_text(json.dumps(_sampling_plan()),encoding="utf-8")
        controller=self.root/"controller.pa0";controller.write_bytes(b"inert-pa")
        class Session:
            def __init__(session):
                session.expected_operation_ids=("sample_differential","sample_static")
                session.input_dir=self.root/"inputs";session.result_dir=self.root/"results"
                session.run_dir=self.root;session.log_dir=self.root/"logs";session.operations=[]
                session.artifact_run_dir=self.root
                session.context=type("Context",(),{"tools":{"simion":controller}})()
            def declare_file(session,path,role):
                path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);return path
            def canonical_path(session,path):return Path(path)
            def add_input(session,name,record):pass
            def run_process(session,operation,**kwargs):
                session.operations.append(operation)
                arguments=kwargs["arguments"];output=Path(arguments[6]);field_case=arguments[7]
                with open(arguments[5],encoding="utf-8",newline="") as point_stream:
                    points=list(csv.DictReader(point_stream))
                with output.open("w",encoding="utf-8",newline="") as stream:
                    writer=csv.DictWriter(stream,fieldnames=FIELD_OUTPUT_COLUMNS);writer.writeheader()
                    for point in points:
                        writer.writerow(dict(point,field_case=field_case,potential_V="0",
                            Ex_V_per_m="0",Ey_V_per_m="0",Ez_V_per_m="0"))
        session=Session()
        request={"resolved_design":str(resolved_path),"sampling_plan":str(plan_path),
            "controller_pa":str(controller),"origin_mm":[0,0,0],"cell_mm":[1,1,1],
            "electrode_ids_by_group":{"1":[1],"2":[2]}}
        result=execute_simion_samples(session,request=request,limits={},source_id="inert-simion")
        self.assertEqual(session.operations,["sample_differential","sample_static"])
        self.assertEqual(result["status"],"success")
        self.assertEqual(result["summary"]["fly_calls"],0)
        self.assertEqual(result["summary"]["iob_calls"],0)
        samples=self.root/"results/stationary_field_samples.csv"
        self.assertTrue(samples.is_file())
        self.assertEqual(json.loads((self.root/"results/stationary_field_sample_validation.json").read_text(encoding="utf-8-sig"))["status"],"PASS")
        self.assertFalse((self.root/"simion/quad_monolithic.iob").exists())

    def test_simion_sampling_resource_uses_no_save_pa_double_and_canonical_units(self):
        import shutil
        import subprocess
        lua=shutil.which("lua") or shutil.which("lua5.1")
        if lua is None: self.skipTest("portable Lua unavailable")
        from msplatform.backends.simion.resources import native_resource_path
        resource=native_resource_path("export_stationary_field_samples.lua")
        points=self.root/"native-points.csv"
        points.write_text("sample_id,region,x_mm,y_mm,z_mm\np0,vacuum,0,0,0\np1,vacuum,1,2,3\n",encoding="utf-8")
        output=self.root/"native.csv";stub=self.root/"pa_double.lua"
        stub.write_text("simion={pas={}} function simion.pas:close() end function simion.pas:open(path) "
            "assert(path=='inert.pa0');local p={} function p:fast_adjust(v) assert(v[1]==100 and v[2]==-100) end "
            "function p:inside_vc(x,y,z) return true end function p:potential_vc(x,y,z) return x+y+z end "
            "function p:field_vc(x,y,z) return 1,2,3 end function p:close() end return p end",encoding="utf-8")
        script="dofile("+repr(stub.as_posix())+")\n"+resource.read_text(encoding="utf-8")
        combined=self.root/"combined.lua";combined.write_text(script,encoding="utf-8")
        result=subprocess.run([lua,str(combined),"inert.pa0",str(points),str(output),"differential","10,10,10","1,1,1","1=100","2=-100"],
            cwd=self.root,capture_output=True,text=True,encoding="utf-8",timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        records=load_stationary_field_output_csv(output)
        self.assertEqual(len(records),2)
        self.assertEqual((records[0].Ex_V_per_m,records[0].Ey_V_per_m,records[0].Ez_V_per_m),(1000.,2000.,3000.))
        self.assertNotIn(":save",resource.read_text(encoding="utf-8"))

    def test_load_and_compare_valid_outputs(self) -> None:
        reference = load_stationary_field_output_csv(
            self._write_rows("reference.csv", _field_rows())
        )
        candidate = load_stationary_field_output_csv(
            self._write_rows(
                "candidate.csv",
                _field_rows(potential_scale=1.5, field_scale=2.0),
            )
        )
        result = compare_stationary_field_outputs(reference, candidate)
        self.assertEqual(result["status"], "INCONCLUSIVE_DIAGNOSTIC_ONLY")
        self.assertFalse(result["acceptance_thresholds_applied"])
        self.assertEqual(result["total_sample_count"], 4)
        differential = result["field_cases"]["differential"]
        self.assertEqual(differential["sample_count"], 2)
        self.assertEqual(
            tuple(differential["regions"]),
            (
                "entrance_aperture_plate_downstream_face",
                "rod_span_uniform",
            ),
        )
        self.assertEqual(
            differential["regions"]["rod_span_uniform"]["sample_count"], 1
        )
        self.assertGreater(
            differential["potential"]["rms_absolute_difference_V"], 0
        )
        self.assertGreater(
            differential["field_vector"][
                "maximum_difference_norm_V_per_m"
            ],
            0,
        )
        for component in ("Ex", "Ey", "Ez"):
            self.assertGreater(
                differential["field_components"][component][
                    "rms_absolute_difference_V_per_m"
                ],
                0,
            )

    def test_load_rejects_missing_column(self) -> None:
        columns = tuple(
            column
            for column in FIELD_OUTPUT_COLUMNS
            if column != "Ez_V_per_m"
        )
        rows = [
            {key: value for key, value in row.items() if key in columns}
            for row in _field_rows()
        ]
        path = self._write_rows("missing.csv", rows, columns)
        with self.assertRaisesRegex(
            StationaryFieldContractError, "columns or column order"
        ):
            load_stationary_field_output_csv(path)

    def test_load_rejects_duplicate_id(self) -> None:
        rows = _field_rows()
        rows[1]["sample_id"] = rows[0]["sample_id"]
        rows[1]["field_case"] = rows[0]["field_case"]
        path = self._write_rows("duplicate.csv", rows)
        with self.assertRaisesRegex(
            StationaryFieldContractError, "must be unique"
        ):
            load_stationary_field_output_csv(path)

    def test_load_rejects_nan(self) -> None:
        rows = _field_rows()
        rows[0]["Ex_V_per_m"] = "NaN"
        path = self._write_rows("nan.csv", rows)
        with self.assertRaisesRegex(StationaryFieldContractError, "must be finite"):
            load_stationary_field_output_csv(path)

    def test_compare_rejects_coordinate_difference(self) -> None:
        reference = load_stationary_field_output_csv(
            self._write_rows("reference.csv", _field_rows())
        )
        rows = _field_rows()
        for row in rows:
            if row["sample_id"] == "p0":
                row["x_mm"] = "0.0000001"
        candidate = load_stationary_field_output_csv(
            self._write_rows("coordinate.csv", rows)
        )
        with self.assertRaisesRegex(
            StationaryFieldContractError, "coordinates differ"
        ):
            compare_stationary_field_outputs(reference, candidate)

    def test_near_zero_reference_normalization_is_null_not_infinite(
        self,
    ) -> None:
        reference = load_stationary_field_output_csv(
            self._write_rows(
                "near_zero.csv",
                _field_rows(potential_scale=1e-320, field_scale=1e-320),
            )
        )
        candidate = load_stationary_field_output_csv(
            self._write_rows("finite.csv", _field_rows())
        )
        result = compare_stationary_field_outputs(reference, candidate)
        differential = result["field_cases"]["differential"]
        self.assertIsNone(
            differential["potential"]["reference_normalized_rms"]
        )
        self.assertIsNone(
            differential["field_vector"]["reference_normalized_rms"]
        )
        for component in ("Ex", "Ey", "Ez"):
            self.assertIsNone(
                differential["field_components"][component][
                    "reference_normalized_rms"
                ]
            )

    def test_single_public_utility_boundary_generates_validates_and_compares(
        self,
    ) -> None:
        resolved_path = self.root / "resolved.json"
        plan_path = self.root / "plan.json"
        points_path = self.root / "points.csv"
        resolved_path.write_text(json.dumps(_resolved_design()), encoding="utf-8")
        plan_path.write_text(json.dumps(_sampling_plan()), encoding="utf-8")
        self.assertEqual(
            main(
                [
                    "generate",
                    "--resolved-design",
                    str(resolved_path),
                    "--sampling-plan",
                    str(plan_path),
                    "--output",
                    str(points_path),
                ]
            ),
            0,
        )
        with points_path.open(encoding="utf-8", newline="") as handle:
            point_rows = list(csv.DictReader(handle))
        self.assertEqual(
            tuple(point_rows[0]),
            ("sample_id", "region", "x_mm", "y_mm", "z_mm"),
        )

        field_path = self._write_rows("field.csv", _field_rows())
        validation_path = self.root / "validation.json"
        self.assertEqual(
            main(
                [
                    "validate",
                    "--input",
                    str(field_path),
                    "--output",
                    str(validation_path),
                ]
            ),
            0,
        )
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        self.assertEqual(validation["point_count"], 2)
        self.assertEqual(validation["row_count"], 4)

        comparison_path = self.root / "comparison.json"
        self.assertEqual(
            main(
                [
                    "compare",
                    "--reference",
                    str(field_path),
                    "--candidate",
                    str(field_path),
                    "--output",
                    str(comparison_path),
                ]
            ),
            0,
        )
        comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
        self.assertEqual(comparison["status"], "INCONCLUSIVE_DIAGNOSTIC_ONLY")


if __name__ == "__main__":
    unittest.main()
