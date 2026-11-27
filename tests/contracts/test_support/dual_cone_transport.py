"""Shared dual-cone transport test inputs and inert terminal records."""
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "src/msplatform/components/dual_cone_tandem_quadrupole/config"
LUA = Path(shutil.which("lua") or shutil.which("lua5.1") or "C:/Program Files/SIMION-2020/lua.exe")


def request():
    names = dict(resolved="resolved_geometry", numerics="simion_solver_numerics", science="ion_transport_science",
                 environment="gas_environment", source_spec="cylindrical_particle_source")
    return {name: json.loads((CONFIG / (filename + ".json")).read_text()) for name, filename in names.items()}


def native_request():
    values = request()
    from msplatform.components.dual_cone_tandem_quadrupole.gas_environment import (
        project_dual_cone_transport_science, resolve_dual_cone_conditions,
    )

    values["science"] = project_dual_cone_transport_science(
        values["science"], resolve_dual_cone_conditions(values["environment"], values["resolved"])
    )
    return values


def write_published_gas_fixture(root, *, cover_transport_domain=False, mass_balance_relative_error=None,
                                grid_size=(10, 10), artifact_root=None):
    """Publish an inert current gas product through the actual input/schema owners."""
    import csv
    import hashlib
    from msplatform.backends.comsol.gas_flow import resolve_gas_flow_request
    from msplatform.io.manifest_records import file_record
    from tests.components.dual_cone_tandem_quadrupole.test_gas_flow_contract import _write_fixture

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    source_request = resolve_gas_flow_request(*(CONFIG / name for name in (
        "baseline.json", "resolved_geometry.json", "gas_flow_science.json",
        "comsol_solver_numerics.json", "gas_environment.json")))
    inputs = {}
    for name, original in source_request["inputs"].items():
        target = root / "inputs" / (name + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(original["path"]).read_bytes())
        inputs[name] = file_record(target, "required_evidence")
        if inputs[name]["sha256"].upper() != original["sha256"].upper():
            raise ValueError("inert gas fixture input identity differs: " + name)
    science = root / "inputs" / "science_resolved.json"
    science.write_text(json.dumps(source_request["projected_science"], ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8", newline="\n")
    csv_path, metadata_path = _write_fixture(root, science_path=science, grid_size=grid_size)
    if cover_transport_domain or mass_balance_relative_error is not None:
        with csv_path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            names = reader.fieldnames
            rows = list(reader)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if cover_transport_domain:
            interface = json.loads((CONFIG / "gas_field_interface.json").read_text(encoding="utf-8"))
            domain = interface["runtime_artifact_contract"]["domain"]
            radii = [domain["minimum_radius_mm"] + (domain["maximum_radius_mm"] - domain["minimum_radius_mm"]) * i / (grid_size[0] - 1)
                     for i in range(grid_size[0])]
            axial = [domain["minimum_z_mm"] + (domain["maximum_z_mm"] - domain["minimum_z_mm"]) * i / (grid_size[1] - 1)
                     for i in range(grid_size[1])]
            for row in rows:
                row.update(r_mm=radii[int(row["r_index"])], z_mm=axial[int(row["z_index"])])
            metadata["grid"] = {"r_values_mm": radii, "z_values_mm": axial}
        if mass_balance_relative_error is not None:
            metadata["solution_summary"]["mass_balance_relative_error"] = mass_balance_relative_error
        with csv_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=names)
            writer.writeheader()
            writer.writerows(rows)
        metadata["field_csv_sha256"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    records = dict(inputs)
    records["science"] = file_record(science, "required_evidence")
    records["science_author"] = inputs["science"]
    records["field_csv"] = file_record(csv_path, "required_evidence")
    records["field_metadata"] = file_record(metadata_path, "required_evidence")
    inputs["science_resolved"] = records["science"]
    identity = dict(project="dual_cone_tandem_quadrupole", run_id=root.name, mode="axisymmetric_gas_flow_screening")
    if artifact_root is not None:
        identity["capacity_ledger_lifecycle"] = dict(
            schema_version=1, enabled=True, artifact_root=str(Path(artifact_root).resolve()), light_evidence_budget_bytes=1
        )
    run_config = root / "run_config.json"
    run_config.write_text(json.dumps(identity), encoding="utf-8")
    manifest = root / "run_manifest.json"
    manifest.write_text(json.dumps(dict(
        schema_version=2, role="simulation_run_manifest", status="success", **identity,
        run_config=file_record(run_config, "required_evidence"),
        inputs=inputs, outputs=[records["field_csv"], records["field_metadata"]],
        products={"gas_field": dict(schema_version=1, kind="gas_field", status="complete",
            metadata={"backend": "comsol", "claim_scope": "inert_fixture_not_native"}, data=records)},
    )), encoding="utf-8")
    return dict(reference=dict(manifest=file_record(manifest, "required_evidence"), product_id="gas_field"),
                csv_path=csv_path, metadata_path=metadata_path, source_request=source_request)


def terminal_log(particle_ids, native_run, *, increment_time=False):
    from tests.contracts.test_terminal_evidence import row, wire

    lines = []
    for ion, particle_id in enumerate(particle_ids, 1):
        elapsed = 10. + (ion - 1 if increment_time else 0)
        values = dict(particle_id=particle_id, ion=ion, native_run=native_run, ion_run=1,
                      raw_birth_us=3., source_origin_us=3., raw_step_us=None,
                      x_mm=25.5, y_mm=25.5, z_mm=121.75, vx_mm_per_us=0., vy_mm_per_us=0., vz_mm_per_us=1.)
        lines.append(wire(row("initialize", 1, **values, raw_tof_us=0., pipeline_clock_us=3., instrument_time_us=3.)))
        lines.append(wire(row("terminate", 2, **values, raw_tof_us=elapsed, pipeline_clock_us=3. + elapsed, instrument_time_us=3. + elapsed)))
    return lines
