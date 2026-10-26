"""Preparation consumes frozen providers and the complete original birth source."""

from __future__ import annotations

import csv
import copy
import io
import json
import math
import os
import shutil
import stat
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common.contracts.particle_physics import AMU_KG, ELEMENTARY_CHARGE_C
from common.integration.resolve_assembly import compile_assembly_layout
from common.contracts.write_run_manifest import file_record
from common.contracts.verify_run_manifest import record_path, verify_record
from common.multipole.particle_source_preflight import validate_source
from common.ion_release import cylinder
from integrations.tests.test_single_reflection_geometry import candidate_300mm_fixture, inputs, reframe_parent
from integrations.runtime.single_flight_source import GLOBAL_COLUMNS, SOURCE_COLUMNS, published_producer_input
from integrations.workflows.single_reflection_flight.geometry import compile_frontend_geometry
from integrations.workflows.single_reflection_flight.prepare import prepare


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


def fixture(root, *, source=None, source_rows=None, source_metadata=None, clock_bytes=None, epoch_bytes=None, entrance_refinement=False):
    author = root / "author"
    author.mkdir()
    run = root / "run"
    (run / "inputs").mkdir(parents=True)
    if source is None:
        from common.multipole.compile_design_request import compile_design_request

        raw = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "projects/rf_octupole_ion_optics/config/requests/through_exit.json"
            ).read_text()
        )
        source = compile_design_request(raw, expected_identity=raw["identity"])
    oatof = candidate_300mm_fixture()
    kw = inputs(source, oatof)
    z0 = oatof["accelerator_topology"]["planes_global_z_mm"]["repeller"] - 40.0
    kw["numerical_domains"]["parent"]["pa_bounds_mm"].update(z_min=z0, z_max=z0 + 350.0)
    if source["segmentation"]["segmented_rod_array"] is not None:
        kw["electrode_bindings"]["multipole"] = {key: key for key in range(1, 11)}
        kw["electrode_bindings"]["oatof"] = dict(
            grounded_shield_id=11,
            accelerator_repeller_id=12,
            accelerator_grid1_id=13,
            accelerator_intermediate2_id=35,
            accelerator_grid2_id=34,
            accelerator_ring_ids=list(range(14, 34)),
        )
    if source_rows is None:
        speed = math.sqrt(
            2 * source["particle_source"]["energy_model"]["kinetic_energy_eV"] * ELEMENTARY_CHARGE_C / (100 * AMU_KG)
        )
        rows = [
            dict(
                particle_id=i,
                birth_time_s=i * 1e-6,
                x_mm=0.01 * i,
                y_mm=-0.005 * i,
                z_mm=source["interfaces_mm"]["entrance"]["release_plane_z_mm"],
                vx_m_s=speed * 0.1,
                vy_m_s=speed * 0.2,
                vz_m_s=speed * math.sqrt(0.95),
                mass_amu=100,
                charge_state=1,
            )
            for i in range(1, 101)
        ]
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=SOURCE_COLUMNS, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
        source_rows = b"\xef\xbb\xbf" + stream.getvalue().encode()
    (author / "source.csv").write_bytes(source_rows)
    metadata = source_metadata if source_metadata is not None else validate_source(author / "source.csv", source)
    for name, document in (
        ("multipole", source),
        ("oatof", oatof),
        ("parent_plan", kw.pop("composition_plan")),
        ("metadata", metadata),
    ):
        write_json(author / (name + ".json"), document)
    epoch_path = author / "epoch.json"
    epoch_path.write_bytes(epoch_bytes if epoch_bytes is not None else b'{"instrument_time_us": 0.0}\r\n')
    clock = dict(
        schema_version=1,
        role="canonical_clock_authority",
        clock_epoch_id="instrument_clock_epoch_v1",
        instrument_time_unit="us",
        canonical_time_basis="instrument_epoch_absolute_time",
        authority=dict(
            path="inputs/instrument_epoch.json", sha256=file_record(epoch_path)["sha256"], field="instrument_time_us"
        ),
        solver_local_time_basis="elapsed_time_from_zero_us",
        adapter_materialization="instrument_time_us_equals_authority_epoch_plus_solver_elapsed_once",
        handoff_policy="preserve_instrument_time_us_and_clock_epoch_id",
        legacy_new_campaign_allowed=False,
    )
    (author / "clock.json").write_bytes(
        clock_bytes if clock_bytes is not None else (json.dumps(clock) + "\r\n").encode()
    )

    def record(name):
        return file_record(author / name, recorded_path=Path(name))

    domains = kw.pop("numerical_domains")
    convergence = dict(carrier_off=0.001, rf_reference=0.002, pulse_delta=0.003)
    domains['parent']['refine_convergence_v'] = dict(convergence)
    if entrance_refinement:
        repeller = oatof['accelerator_topology']['planes_global_z_mm']['repeller']
        domains['entrance_refinement'] = dict(cell_mm_xyz=dict(x=.15,y=.125,z=.05),
            pa_bounds_mm=dict(domains['parent']['pa_bounds_mm'], y_min=-21.5,y_max=21.5,
                              z_min=repeller-19.,z_max=repeller+23.),
            refine_convergence_v=dict(convergence),guard_cells=2)
    request = dict(
        schema_version=9,
        pulse_voltage_policy_id="all_accelerator_electrodes_zero_before_pulse_v1",
        # Inert test inputs only; these are not approved production numerics.
        numerics=dict(boundary_policy="native_zero_neumann", rf_reference_voltage_v=10000.,
                      frontend_domains=domains),
        role="instrument_assembly_single_reflection_preparation_request",
        composition_plan=record("parent_plan.json"),
        providers=dict(instances={key: dict(resolved_design=record(key+".json"), electrode_bindings=value,
            **(dict(geometry=dict(accelerator_variant=kw["accelerator_variant"])) if key=="oatof" else {}))
            for key,value in kw["electrode_bindings"].items()}),
        source=dict(
            kind="recorded_birth",
            instance_id="multipole",
            frame_id=source["coordinate"]["coordinate_id"],
            particle_source=record("source.csv"),
            metadata=record("metadata.json"),
            clock_authority=record("clock.json"),
            instrument_epoch=record("epoch.json"),
        ),
    )
    request_path = author / "request.json"
    write_json(request_path, request)
    return request_path, run, request


def release_fixture(root, *, instance_id="oatof", local=False):
    path, run, request = fixture(root)
    recipe = json.loads((path.parent / "parent_plan.json").read_text())["recipe"]
    pose = next(item["transform"] for item in recipe["instances"] if item["instance_id"] == instance_id)
    oatof = json.loads((path.parent / "oatof.json").read_text())
    center = (
        [3.5, 1.25, oatof["accelerator_topology"]["planes_global_z_mm"]["repeller"] + 2.75]
        if instance_id == "oatof"
        else [0.125, -0.25, 5.0]
    )
    spec = dict(
        schema_version=1,
        role="repository_ion_release",
        frame_id=pose["from_frame_id"],
        particle_count=100,
        mother_particle_count=100,
        common_time_of_birth_s=42.125e-6,
        geometry=dict(shape="cylinder", center_mm=center, axis="z", radius_mm=0.05, height_mm=0.1),
        species=dict(mass_amu=524.0, charge_state=1),
        sampling=dict(
            strategy="center_first_halton_cylinder_v1",
            kinetic_energy=dict(center_ev=2.0, full_width_ev=0.2),
            nominal_direction=[1.0, 2.0, 3.0],
            angular_full_width_deg=5.0,
        ),
    )
    write_json(path.parent / "release_spec.json", spec)
    request["source"] = dict(
        kind="release_spec",
        instance_id=instance_id,
        release_spec=file_record(path.parent / "release_spec.json"),
        **{key: request["source"][key] for key in ("clock_authority", "instrument_epoch")},
    )
    if local:
        request['local_scope'] = dict(instance_ids=['oatof'], research_scope='OA and TOF with an OA-local birth population',
            boundary_assumptions='Omit multipole metal and fields; retain the same open side aperture and explicit outer numerical boundary')
        request['providers']['instances'].pop('multipole')
        del request['numerics']['rf_reference_voltage_v']
        del request['numerics']['frontend_domains']['parent']['refine_convergence_v']['rf_reference']
    write_json(path, request)
    return path, run, request, spec


def rename_recipe_instances(recipe):
    """Rename both test instances and reverse author order without changing physics."""
    names = {"multipole": "guide_a", "oatof": "tof_b"}
    for instance in recipe["instances"]:
        instance["instance_id"] = names[instance["instance_id"]]
    recipe["instances"].reverse()
    for endpoint in ("upstream", "downstream"):
        row = recipe["connections"][0][endpoint]
        row["instance_id"] = names[row["instance_id"]]
    return names


def rename_author_instances(path, request):
    """Update only a test author's recipe/source/local names and recipe record."""
    reference = request["composition_plan"]["path"]
    plan_path = path.parent / reference
    plan = json.loads(plan_path.read_text())
    names = rename_recipe_instances(plan["recipe"])
    plan = compile_assembly_layout(plan["recipe"], {names[key]: value for key,value in plan["components"].items()})
    write_json(plan_path, plan)
    request["composition_plan"] = file_record(plan_path, recorded_path=Path(reference))
    request["providers"]["instances"] = {names[key]: value for key,value in request["providers"]["instances"].items()}
    request["source"]["instance_id"] = names[request["source"]["instance_id"]]
    if "local_scope" in request:
        request["local_scope"]["instance_ids"] = [names[name] for name in request["local_scope"]["instance_ids"]]
    write_json(path, request)


def frontend_field_source_fixture(root: Path, request_path: Path, request: dict, *, fine: bool = True) -> tuple[Path, Path]:
    """Small publication fixture only; no PA, solver or physical claim."""
    producer = root / "producer" / "20261024_094111__sim__simion__full-single-reflection-oatof-n100"
    inputs = producer / "inputs"
    inputs.mkdir(parents=True)
    config = producer / "run_config.json"
    write_json(config, dict(schema_version=2,run_id=producer.name,project="instrument_assembly"))
    domains=[]
    records={}
    for name in (["parent","entrance_refinement"] if fine else ["parent"]):
        path=inputs/("frontend_"+name+"_cache_identity.json")
        write_json(path,dict(domain_id=name,source="pure_publication_fixture"))
        record=file_record(path)
        records[name]=record
        domains.append(dict(domain_id=name,cache_identity_record={**record,
            "path":str(root/"expired_execution_alias"/"inputs"/path.name)},
            generation_directory=str(root/"never_read_generation"/name),
            working_points=[dict(kind=kind,path=str(root/(kind+".pa")),bytes=10**10,sha256="A"*64)
                for kind in ("carrier_off","rf_reference","pulse_delta")]))
    receipt=inputs/"frontend_working_field_stage_receipt.json"
    write_json(receipt,dict(schema_version=2,role="single_reflection_frontend_working_fields",status="success",
        domains=domains,field_bank_record=dict(path=str(root/"never_read_bank.json"),bytes=123,sha256="B"*64)))
    records["stage_receipt"]=file_record(receipt)
    manifest=producer/"run_manifest.json"
    write_json(manifest,dict(schema_version=2,role="simulation_run_manifest",status="failed",run_id=producer.name,project="instrument_assembly",
        run_config=file_record(config),inputs=records,outputs=[]))
    request["providers"]["frontend_fields"]=file_record(receipt)
    write_json(request_path,request)
    return receipt,manifest


def downstream_field_source_fixture(root: Path, request_path: Path, request: dict, *, oatof_record: dict | None = None) -> tuple[Path, Path]:
    """Sealed small I/O fixture; its explicit dummy PA bytes are never native inputs."""
    from integrations.workflows.single_reflection_flight.downstream_fields import plan_downstream_fields

    producer = root / "producer" / "20261024_094111__sim__simion__full-single-reflection-oatof-n100"
    (producer / "inputs").mkdir(parents=True,exist_ok=True)
    config=producer/"run_config.json"
    if not config.exists():
        write_json(config,dict(schema_version=2,run_id=producer.name,project="instrument_assembly"))
    provider=producer/"inputs/components/oatof/resolved_design.json"
    provider.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(record_path(oatof_record or request['providers']['instances']['oatof']['resolved_design'],base_dir=request_path.parent),provider)
    provider_record=file_record(provider)
    manifest=producer/'run_manifest.json'
    document=json.loads(manifest.read_text()) if manifest.exists() else dict(schema_version=2,
        role="simulation_run_manifest",status="failed",run_id=producer.name,project="instrument_assembly",
        run_config=file_record(config),inputs={},outputs=[])
    # Both fixture stages belong to the same construction; seal after staging.
    if manifest.exists(): write_json(manifest,{**document,'status':'checkpoint'})
    geometry_path=producer/'inputs/frontend_geometry.json'
    parent=json.loads(record_path(request['composition_plan'],base_dir=request_path.parent).read_text())
    write_json(geometry_path,dict(composition_plan=compile_assembly_layout(parent['recipe'],parent['components'],local_scope=request.get('local_scope'))))
    planned=plan_downstream_fields(dict(role="single_reflection_geometry_preparation",
        input_records=dict(instance_design__oatof=provider_record),outputs=dict(frontend_geometry=file_record(geometry_path))),producer,snapshot_root=Path(__file__).resolve().parents[2])
    plan_path=Path(planned['plan_record']['path'])
    plan=json.loads(plan_path.read_text())
    alias=root/"expired_downstream_execution_alias"
    assets=[]
    for asset in plan['assets']:
        paths=asset['family_paths'] or [asset['carrier_path']]
        records={}
        for value in paths:
            path=Path(value)
            path.write_bytes(b'PURE_TEST_DUMMY_PA_NOT_A_NATIVE_MODEL\n'+path.name.encode())
            path.chmod(path.stat().st_mode & ~stat.S_IWRITE)
            record={**file_record(path),'read_only':True}
            record['path']=str(alias/path.relative_to(producer))
            records[value]=record
        assets.append(dict(role=asset['role'],representation=asset['representation'],
            carrier_record=records[asset['carrier_path']],
            family_records=list(records.values()) if asset['family_paths'] else []))
    command_record=file_record(plan_path)
    receipt=plan_path.with_name('downstream_field_preparation.json')
    write_json(receipt,dict(schema_version=1,role="single_reflection_downstream_field_preparation",status="success",
        native_family_origin="generated_in_producer_run",run_directory=str(alias),oatof_resolved_record=provider_record,
        assets=assets,command_plan_record={**command_record,'path':str(alias/'simion/downstream_fields/command_plan.json')}))
    small=[file_record(receipt),command_record]
    document['inputs'].update(downstream_publication=small[0],downstream_command_plan=small[1],oatof=provider_record)
    document['outputs'].extend(small)
    for asset in assets:
        for row in asset['family_records'] or [asset['carrier_record']]:
            original=plan_path.parent/Path(row['path']).name
            document['outputs'].append({**row,'path':str(original)})
    write_json(manifest,document)
    request['providers']['downstream_fields']=file_record(receipt)
    write_json(request_path,request)
    return receipt,manifest


class SingleReflectionPreparationTests(unittest.TestCase):
    def test_available_actual_providers_keep_native_payloads_under_parent_references(self):
        from common.multipole.component_port import build_assembly_interface
        frozen = Path(__file__).resolve().parents[3] / ('artifacts/projects/instrument_assembly/runs/'
            '20261025_193652__analysis__python__current-parent-preparation/inputs')
        if not frozen.is_dir():
            self.skipTest('external current-parent complete provider preparation is unavailable')
        results = []
        for change in ({}, dict(translation=(0.,64.,0.)),
                       dict(rotation=((0.,-1.,0.),(1.,0.,0.),(0.,0.,1.)))):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root/'inputs').mkdir()
                request = json.loads((frozen/'request.json').read_text())
                request['schema_version'] = 9  # Author a current request; frozen historical inputs stay unchanged.
                request['providers'] = dict(instances=request['providers']['instances'])
                for key, instance in request['providers']['instances'].items():
                    instance['resolved_design'] = file_record(frozen/'components'/key/'resolved_design.json')
                for key, name in (('particle_source','particle_source.csv'), ('metadata','particle_source_metadata.json'),
                                  ('clock_authority','clock_authority.json'), ('instrument_epoch','instrument_epoch.json')):
                    request['source'][key] = file_record(frozen/name)
                parent = json.loads((frozen/'composition_plan.json').read_text())
                components = copy.deepcopy(parent['components'])
                for instance_id, component in components.items():
                    if instance_id == 'oatof':
                        continue
                    provider = json.loads((frozen/'components'/instance_id/'resolved_design.json').read_text())
                    current = build_assembly_interface(provider,geometry_profile_id=component['geometry_profile_id'])
                    self.assertEqual(current['ports'],component['ports'])
                    components[instance_id] = current
                parent = compile_assembly_layout(parent['recipe'],components)
                if change:
                    parent = reframe_parent(parent, **change)
                write_json(root/'parent.json', parent)
                request['composition_plan'] = file_record(root/'parent.json')
                write_json(root/'author.json', request)
                prepare(root/'author.json', root)
                payloads = tuple((root/'inputs'/name).read_bytes() for name in (
                    'frontend.gem','frontend_entrance_refinement.gem','frontend_field_design.json',
                    'projected_source.csv','clock_authority.json','instrument_epoch.json'))
                results.append(payloads)
                for name in ('frontend.gem','frontend_entrance_refinement.gem','projected_source.csv',
                             'clock_authority.json','instrument_epoch.json'):
                    current = (root/'inputs'/name).read_bytes()
                    if name.endswith('.gem'):
                        self.assertNotIn(b' within {', current)
                        # The historical raster instruction changes; every physical
                        # primitive, pose, hole and numerical grid remains identical.
                        current = current.replace(b' within_inside_or_on {', b' within {')
                    self.assertEqual(current, (frozen/name).read_bytes())
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0], results[2])

    def test_parent_reference_does_not_move_native_geometry_fields_source_or_clock(self):
        for source_kind in ('recorded_birth', 'release_spec'):
            for local in (False, True) if source_kind == 'release_spec' else (False,):
                results = []
                for change in ({}, dict(translation=(0.,64.,0.)),
                               dict(rotation=((0.,-1.,0.),(1.,0.,0.),(0.,0.,1.)))):
                    with self.subTest(source=source_kind, local=local, change=change), tempfile.TemporaryDirectory() as directory:
                        root = Path(directory)
                        if source_kind == 'release_spec':
                            path, run, request, _ = release_fixture(root, local=local)
                        else:
                            path, run, request = fixture(root)
                        plan_path = record_path(request['composition_plan'], base_dir=path.parent)
                        parent = json.loads(plan_path.read_text())
                        if change:
                            parent = reframe_parent(parent, **change)
                            write_json(plan_path, parent)
                            request['composition_plan'] = file_record(plan_path)
                        write_json(path, request)
                        prepare(path, run)
                        geometry = json.loads((run/'inputs/frontend_geometry.json').read_text())
                        self.assertEqual(geometry['composition_plan']['recipe'], parent['recipe'])
                        self.assertEqual(geometry['native_frame_id'], 'oatof_global')
                        provenance = json.loads((run/'inputs/source_provenance.json').read_text())
                        self.assertEqual(provenance['target_frame_id'], 'oatof_global')
                        results.append(tuple((run/'inputs'/name).read_bytes() for name in (
                            'frontend.gem', 'frontend_field_design.json', 'projected_source.csv',
                            'clock_authority.json', 'instrument_epoch.json')))
                self.assertEqual(results[0], results[1])
                self.assertEqual(results[0], results[2])

    def test_field_continuation_freezes_explicit_records_without_changing_science(self):
        for change in (None, "domain", "member", "duplicate", "reused", "missing_stop", "identity", "stop_config"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path, baseline, request = fixture(root)
                frontend_field_source_fixture(root, path, request, fine=False)
                downstream_field_source_fixture(root, path, request)
                request["providers"]["frontend_field_reuse_members"] = ["carrier_off", "rf_reference"]
                write_json(path, request)
                prepare(path, baseline)
                parent = root / "parent"
                parent.mkdir()
                config = dict(schema_version=2, project="instrument_assembly", run_id="parent", mode="single_reflection_fly")
                write_json(parent / "run_config.json", config)
                write_json(parent / "run_manifest.json", dict(schema_version=2, role="simulation_run_manifest",
                    project=config["project"], run_id="parent", mode=config["mode"], status="checkpoint",
                    run_config=file_record(parent / "run_config.json"), inputs={}, outputs=[]))
                config["inputs"] = {"fixture": "config frozen after initialization checkpoint"}
                write_json(parent / "run_config.json", config)
                # Preparation freezes evidence; common owns its transaction/ledger interpretation.
                transaction, stopped = root / "transaction.json", root / "stopped.json"
                write_json(transaction, {"fixture": "transaction source bytes"})
                stop = dict(schema_version=1, role="run_capacity_lifecycle_receipt", action="seal_stopped_payload",
                    status="ready", run_status="checkpoint", run_directory=str(parent.resolve()),
                    run_config=file_record(parent / "run_config.json"))
                if change == "stop_config": stop["run_config"]["sha256"] = "0" * 64
                write_json(stopped, stop)
                entry = dict(domain_id="parent", member_id="pulse_delta", transaction_record=file_record(transaction))
                request["continuation"] = dict(predecessor_run_manifest=file_record(parent / "run_manifest.json"),
                    stopped_receipt=file_record(stopped), frontend_field_transactions=[entry])
                if change == "domain": entry["domain_id"] = "entrance_refinement"
                elif change == "member": entry["member_id"] = "missing_member"
                elif change == "duplicate": request["continuation"]["frontend_field_transactions"].append(copy.deepcopy(entry))
                elif change == "reused": entry["member_id"] = "rf_reference"
                elif change == "missing_stop": del request["continuation"]["stopped_receipt"]
                elif change == "identity": transaction.write_text("{}")
                write_json(path, request)
                run = root / "continuing"
                (run / "inputs").mkdir(parents=True)
                if change is not None:
                    with self.assertRaises((AssertionError, ValueError)):
                        prepare(path, run)
                    self.assertFalse((run / "inputs/frontend_field_design.json").exists())
                    continue
                result = prepare(path, run)
                for name in ("frontend.gem", "projected_source.csv", "frontend_field_design.json"):
                    self.assertEqual((baseline / "inputs" / name).read_bytes(), (run / "inputs" / name).read_bytes())
                for name, original in (("continuation_stopped_receipt", stopped),
                                       ("continuation_field_transaction_001", transaction)):
                    record = result["input_records"][name]
                    self.assertEqual(Path(record["path"]).read_bytes(), original.read_bytes())
                    self.assertTrue(Path(record["path"]).is_relative_to(run / "inputs"))
                    self.assertEqual(record["source_path"], str(original.resolve()))

    def test_continuation_freezes_a_managed_fly_parent_and_requires_published_fields(self):
        for change in (None, "success", "mode", "config", "fields"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path, run, request = fixture(root)
                frontend_field_source_fixture(root, path, request, fine=False)
                downstream_field_source_fixture(root, path, request)
                parent = root / "parent"
                parent.mkdir()
                config = dict(schema_version=2, project="instrument_assembly", run_id="parent", mode="single_reflection_fly")
                write_json(parent / "run_config.json", config)
                manifest = dict(schema_version=2, role="simulation_run_manifest", project=config["project"],
                                run_id="parent", mode=config["mode"], status="failed",
                                run_config=file_record(parent / "run_config.json"), inputs={}, outputs=[])
                if change == "success":
                    manifest["status"] = "success"
                elif change == "mode":
                    manifest["mode"] = config["mode"] = "single_reflection_field_design"
                    write_json(parent / "run_config.json", config)
                    manifest["run_config"] = file_record(parent / "run_config.json")
                elif change == "config":
                    manifest["run_config"]["sha256"] = "0" * 64
                elif change == "fields":
                    del request["providers"]["frontend_fields"]
                write_json(parent / "run_manifest.json", manifest)
                request["continuation"] = dict(predecessor_run_manifest=file_record(parent / "run_manifest.json"))
                write_json(path, request)
                if change is not None:
                    with self.assertRaises((AssertionError, ValueError)):
                        prepare(path, run)
                    self.assertFalse((run / "inputs/frontend_geometry.json").exists())
                else:
                    result = prepare(path, run)
                    record = result["input_records"]["continuation_parent_manifest"]
                    self.assertEqual(record["source_path"], str((parent / "run_manifest.json").resolve()))
                    self.assertEqual((run / "inputs/continuation_parent_manifest.json").read_bytes(),
                                     (parent / "run_manifest.json").read_bytes())

    def test_parent_growth_keeps_local_source_and_geometry_without_loading_excluded_designs(self):
        reference = None
        for count in (2, 3, 4):
            with self.subTest(parent_instances=count), tempfile.TemporaryDirectory() as directory:
                path, run, request, _ = release_fixture(Path(directory), local=True)
                parent_path = record_path(request['composition_plan'], base_dir=path.parent)
                parent = json.loads(parent_path.read_text())
                for number in range(2, count):
                    name = f'extra_{number}'
                    instance = copy.deepcopy(parent['recipe']['instances'][0])
                    instance['instance_id'] = name
                    instance['transform']['translation_mm'][0] -= 1000 * number
                    parent['recipe']['instances'].append(instance)
                    parent['components'][name] = copy.deepcopy(parent['components']['multipole'])
                parent = compile_assembly_layout(parent['recipe'], parent['components'])
                # Provenance paths are not a second authority after freezing.
                parent['input_files'] = {'recipe': dict(path='no_longer_available.json', sha256='A'*64)}
                write_json(parent_path, parent)
                request['composition_plan'] = file_record(parent_path)
                (path.parent / 'multipole.json').unlink()
                write_json(path, request)
                result = prepare(path, run)
                self.assertNotIn('instance_design__multipole', result['input_records'])
                self.assertFalse((run/'inputs/components/multipole').exists())
                actual = tuple((run/'inputs'/name).read_bytes() for name in (
                    'frontend.gem', 'projected_source.csv', 'clock_authority.json', 'instrument_epoch.json'))
                if reference is None:
                    reference = actual
                self.assertEqual(actual, reference)

    def test_downstream_source_freezes_published_small_records_with_duplicate_input_evidence(self):
        for frontend in (False,True):
            with self.subTest(frontend=frontend),tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                path,run,request=fixture(root)
                if frontend: frontend_field_source_fixture(root,path,request)
                receipt,manifest=downstream_field_source_fixture(root,path,request)
                originals={p:p.read_bytes() for p in receipt.parent.iterdir() if p.suffix=='.json'}
                manifest_bytes=manifest.read_bytes()
                with patch('integrations.workflows.single_reflection_flight.prepare.verify_record',wraps=verify_record) as verified:
                    result=prepare(path,run)
                for key,name,source in (
                    ('downstream_fields','downstream_field_source_receipt.json',receipt),
                    ('downstream_fields_manifest','frontend_field_source_manifest.json' if frontend else 'downstream_field_source_manifest.json',manifest),
                    ('downstream_fields_command_plan','downstream_field_source_command_plan.json',receipt.with_name('command_plan.json'))):
                    row=result['input_records'][key]
                    self.assertEqual(Path(row['path']),run/'inputs'/name)
                    self.assertEqual(row['source_path'],str(source))
                    self.assertEqual(Path(row['path']).read_bytes(),source.read_bytes())
                for key in ('downstream_fields','downstream_fields_command_plan'):
                    self.assertEqual(sum(call.args[0]==key for call in verified.call_args_list),1)
                self.assertEqual(sum(call.args[0]=='field source producer run_config' for call in verified.call_args_list),1)
                frozen_manifests=list((run/'inputs').glob('*field_source_manifest.json'))
                self.assertEqual(len(frozen_manifests),1)
                if frontend:
                    self.assertEqual(result['input_records']['frontend_fields_manifest'],result['input_records']['downstream_fields_manifest'])
                    self.assertFalse((run/'inputs/downstream_field_source_manifest.json').exists())
                    another_run=root/'another_run'
                    (another_run/'inputs').mkdir(parents=True)
                    with patch('integrations.workflows.single_reflection_flight.prepare.verify_record',wraps=verify_record) as repeated_verification:
                        repeated=prepare(path,another_run)
                    self.assertEqual(sum(call.args[0]=='field source producer run_config' for call in repeated_verification.call_args_list),1)
                    self.assertNotEqual(repeated['input_records']['frontend_fields_manifest']['path'],
                                        result['input_records']['frontend_fields_manifest']['path'])
                    self.assertEqual(len(list((another_run/'inputs').glob('*field_source_manifest.json'))),1)
                self.assertEqual(manifest.read_bytes(),manifest_bytes)
                self.assertTrue(all(p.read_bytes()==data for p,data in originals.items()))
                self.assertEqual(list(run.rglob('*.pa')),[])
                self.assertFalse((root/'expired_downstream_execution_alias').exists())
                plain=json.loads(path.read_text())
                plain['providers']={key:value for key,value in plain['providers'].items() if key == 'instances'}
                plain_path=path.with_name('without_downstream_fields.json')
                write_json(plain_path,plain)
                plain_run=root/'plain_run'
                (plain_run/'inputs').mkdir(parents=True)
                prepare(plain_path,plain_run)
                for name in ('frontend.gem','projected_source.csv','frontend_field_design.json','frontend_geometry.json'):
                    self.assertEqual((run/'inputs'/name).read_bytes(),(plain_run/'inputs'/name).read_bytes(),name)
                for name in ('frontend.gem','frontend_geometry.json','frontend_field_design.json','projected_source.csv'):
                    self.assertEqual((run/'inputs'/name).read_bytes(),(plain_run/'inputs'/name).read_bytes(),name)

    def test_downstream_source_rejects_nonterminal_unbound_changed_or_wrong_location(self):
        for change in ('checkpoint','journal','missing_manifest','receipt_unbound','plan_unbound','plan_changed',
                       'plan_hash','receipt_failed','receipt_role','receipt_schema','wrong_location','duplicate_output'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                path,run,request=fixture(root)
                receipt,manifest=downstream_field_source_fixture(root,path,request)
                document=json.loads(manifest.read_text())
                stage=json.loads(receipt.read_text())
                if change=='checkpoint': document['status']='checkpoint'
                elif change=='journal': write_json(manifest.parent/'.run_terminal_publication.json',{})
                elif change=='missing_manifest': manifest.unlink()
                elif change=='receipt_unbound': document['outputs']=document['outputs'][1:]
                elif change=='plan_unbound': del document['outputs'][1]
                elif change=='plan_changed': receipt.with_name('command_plan.json').write_text('{}')
                elif change=='plan_hash': document['outputs'][1]['sha256']='A'*64
                elif change=='receipt_failed': stage['status']='failed'
                elif change=='receipt_role': stage['role']='another_publication'
                elif change=='receipt_schema': stage['schema_version']=2
                elif change=='duplicate_output': document['outputs'].append(document['outputs'][0])
                elif change=='wrong_location':
                    other=receipt.with_name('other_receipt.json')
                    shutil.copyfile(receipt,other)
                    request['providers']['downstream_fields']=file_record(other)
                    write_json(path,request)
                if change in ('receipt_failed','receipt_role','receipt_schema'):
                    write_json(receipt,stage)
                    request['providers']['downstream_fields']=file_record(receipt)
                    document['outputs'][0]=file_record(receipt)
                    write_json(path,request)
                if change!='missing_manifest': write_json(manifest,document)
                with self.assertRaises((ValueError,AssertionError,FileNotFoundError)):
                    prepare(path,run)
                self.assertFalse((run/'inputs/projected_source.csv').exists())

    def test_frontend_source_freezes_only_manifest_receipt_and_declared_identity_evidence(self):
        for fine in (False,True):
            with self.subTest(fine=fine),tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                path,run,request=fixture(root)
                receipt,manifest=frontend_field_source_fixture(root,path,request,fine=fine)
                originals={p:p.read_bytes() for p in receipt.parent.iterdir()}
                manifest_bytes=manifest.read_bytes()
                with patch('integrations.workflows.single_reflection_flight.prepare.verify_record',wraps=verify_record) as verified:
                    result=prepare(path,run)
                records=result['input_records']
                self.assertEqual((run/'inputs/frontend_field_source_receipt.json').read_bytes(),receipt.read_bytes())
                self.assertEqual((run/'inputs/frontend_field_source_manifest.json').read_bytes(),manifest_bytes)
                self.assertEqual(records['frontend_fields']['source_path'],str(receipt))
                self.assertEqual(records['frontend_fields_manifest']['source_path'],str(manifest))
                self.assertEqual(sum(call.args[0]=='frontend_fields' for call in verified.call_args_list),1)
                for name in (['parent','entrance_refinement'] if fine else ['parent']):
                    key='frontend_fields_'+name+'_identity'
                    row=records[key]
                    self.assertEqual(Path(row['path']).name,'frontend_field_source_'+name+'_identity.json')
                    self.assertEqual(Path(row['path']).read_bytes(),Path(row['source_path']).read_bytes())
                    self.assertEqual(sum(call.args[0]==key for call in verified.call_args_list),1)
                if not fine:
                    self.assertNotIn('frontend_fields_entrance_refinement_identity',records)
                self.assertEqual(manifest.read_bytes(),manifest_bytes)
                self.assertTrue(all(p.read_bytes()==data for p,data in originals.items()))
                self.assertEqual(list(run.rglob('*.pa')),[])
                self.assertFalse((root/'expired_execution_alias').exists())
                self.assertFalse((root/'never_read_generation').exists())
                self.assertEqual(json.loads((run/'inputs/source_provenance.json').read_text())['input_records'],records)
                plain_request=json.loads(path.read_text())
                del plain_request['providers']['frontend_fields']
                plain_path=path.with_name('without_field_source.json')
                write_json(plain_path,plain_request)
                plain_run=root/'plain_run'
                (plain_run/'inputs').mkdir(parents=True)
                prepare(plain_path,plain_run)

    def test_borrowed_frontend_receipt_binds_its_own_provenance_not_historical_asset_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            a_root=root/'a_request'
            a_root.mkdir()
            request_path,a_run,request=fixture(a_root)
            source_receipt,p_manifest=frontend_field_source_fixture(root,request_path,request,fine=True)
            prepare(request_path,a_run)
            borrowed=json.loads(source_receipt.read_text())
            for domain in borrowed['domains']:
                record=domain['cache_identity_record']
                record['path']=str(a_run/'inputs'/('frontend_field_source_'+domain['domain_id']+'_identity.json'))
            borrowed['asset_owner']=dict(manifest=file_record(p_manifest))
            a_receipt=a_run/'inputs/frontend_working_field_stage_receipt.json'
            write_json(a_receipt,borrowed)
            a_config=a_run/'run_config.json'
            write_json(a_config,dict(schema_version=2,run_id=a_run.name,project='instrument_assembly'))
            write_json(a_run/'run_manifest.json',dict(schema_version=2,role='simulation_run_manifest',status='success',
                run_id=a_run.name,project='instrument_assembly',run_config=file_record(a_config),
                inputs={domain['domain_id']:file_record(a_run/'inputs'/('frontend_field_source_'+domain['domain_id']+'_identity.json'))
                        for domain in borrowed['domains']},
                outputs=[file_record(a_receipt)]))
            # The old producer is no longer needed: its historical owner record
            # remains immutable evidence, not a path to follow for permission.
            p_manifest.unlink()
            b_root=root/'b_request'
            b_root.mkdir()
            b_request,b_run,b_document=fixture(b_root)
            b_document['providers']['frontend_fields']=file_record(a_receipt)
            write_json(b_request,b_document)
            result=prepare(b_request,b_run)
            records=result['input_records']
            self.assertEqual(records['frontend_fields']['source_path'],str(a_receipt))
            self.assertEqual(records['frontend_fields_manifest']['source_path'],str(a_run/'run_manifest.json'))
            self.assertEqual((b_run/'inputs/frontend_field_source_receipt.json').read_bytes(),a_receipt.read_bytes())
            self.assertEqual((b_run/'inputs/frontend_field_source_manifest.json').read_bytes(),(a_run/'run_manifest.json').read_bytes())
            self.assertEqual(list(b_run.rglob('*.pa')),[])

    def test_frontend_source_rejects_unpublished_unbound_or_changed_evidence(self):
        changes=('missing_manifest','wrong_manifest_role','checkpoint','journal','missing_config','missing_config_record','wrong_owner','wrong_run',
            'receipt_unbound','receipt_duplicate','receipt_bytes','receipt_hash','receipt_failed','receipt_schema',
            'identity_unbound','identity_hash','identity_missing','identity_changed','receipt_changed','domains')
        for change in changes:
            with self.subTest(change=change),tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                path,run,request=fixture(root)
                receipt,manifest=frontend_field_source_fixture(root,path,request)
                document=json.loads(manifest.read_text())
                stage=json.loads(receipt.read_text())
                if change=='missing_manifest': manifest.unlink()
                elif change=='wrong_manifest_role': document['role']='another_publication'
                elif change=='checkpoint': document['status']='checkpoint'
                elif change=='journal': write_json(manifest.parent/'.run_terminal_publication.json',{})
                elif change=='missing_config': (manifest.parent/'run_config.json').unlink()
                elif change=='missing_config_record': del document['run_config']
                elif change=='wrong_owner': document['project']='another_project'
                elif change=='wrong_run': document['run_id']='different_run'
                elif change=='receipt_unbound': del document['inputs']['stage_receipt']
                elif change=='receipt_duplicate': document['outputs']=[document['inputs']['stage_receipt']]
                elif change=='receipt_bytes': document['inputs']['stage_receipt']['bytes']+=1
                elif change=='receipt_hash': document['inputs']['stage_receipt']['sha256']='A'*64
                elif change=='receipt_failed': stage['status']='failed'
                elif change=='receipt_schema': stage['schema_version']=1
                elif change=='identity_unbound': del document['inputs']['parent']
                elif change=='identity_hash': document['inputs']['parent']['sha256']='A'*64
                elif change=='identity_missing': Path(document['inputs']['parent']['path']).unlink()
                elif change=='identity_changed': Path(document['inputs']['parent']['path']).write_text('{}')
                elif change=='receipt_changed': receipt.write_text('{}')
                elif change=='domains': stage['domains'][0]['domain_id']='another_domain'
                if change!='missing_manifest': write_json(manifest,document)
                if change in ('receipt_failed','receipt_schema','domains'):
                    write_json(receipt,stage)
                    request['providers']['frontend_fields']=file_record(receipt)
                    document['inputs']['stage_receipt']=file_record(receipt)
                    write_json(manifest,document)
                    write_json(path,request)
                with self.assertRaises((ValueError,AssertionError,FileNotFoundError)):
                    prepare(path,run)
                self.assertFalse((run/'inputs/projected_source.csv').exists())

    def test_ordinary_request_does_not_resolve_a_frontend_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path,run,_=fixture(Path(directory))
            with patch('integrations.workflows.single_reflection_flight.prepare._freeze_frontend_source',
                       side_effect=AssertionError('undeclared frontend source')):
                result=prepare(path,run)
            self.assertNotIn('frontend_fields',result['input_records'])
            self.assertFalse((run/'inputs/frontend_field_source_manifest.json').exists())

    def test_renamed_instances_preserve_complete_source_geometry_and_fields(self):
        for source_role, local, fine in (("recorded",False,True),("multipole",False,False),
                                         ("oatof",False,False),("oatof",True,False)):
            with self.subTest(source=source_role,local=local), tempfile.TemporaryDirectory() as directory:
                outputs = []
                for renamed in (False, True):
                    root = Path(directory)/str(renamed)
                    root.mkdir()
                    if source_role == "recorded":
                        path, run, request = fixture(root,entrance_refinement=fine)
                    else:
                        path, run, request, _ = release_fixture(root,instance_id=source_role,local=local)
                    if renamed:
                        rename_author_instances(path,request)
                    prepare(path,run)
                    outputs.append(run)
                first, second = outputs
                for filename in ("particle_source.csv","projected_source.csv","clock_authority.json","instrument_epoch.json",
                                 "frontend.gem",*(('frontend_entrance_refinement.gem',) if fine else ())):
                    self.assertEqual((first/'inputs'/filename).read_bytes(),(second/'inputs'/filename).read_bytes(),filename)
                for filename in ("frontend_field_design.json",):
                    self.assertEqual(json.loads((first/'inputs'/filename).read_text()),json.loads((second/'inputs'/filename).read_text()))
                provenance = json.loads((second/'inputs/source_provenance.json').read_text())
                self.assertEqual(provenance['source_instance_id'],'tof_b' if source_role=='oatof' else 'guide_a')
                self.assertEqual(provenance['particle_count'],100)

    def test_recorded_birth_cannot_claim_downstream_even_with_its_valid_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            path,run,request = fixture(Path(directory))
            rename_author_instances(path,request)
            request['source'].update(instance_id='tof_b',frame_id='oatof_global')
            write_json(path,request)
            with patch('integrations.workflows.single_reflection_flight.prepare.load_validated_source',
                       side_effect=AssertionError('wrong provider must be refused before reading source')):
                with self.assertRaisesRegex(ValueError,'actual multipole upstream'):
                    prepare(path,run)
            self.assertFalse((run/'inputs/projected_source.csv').exists())

    def test_oatof_local_and_full_keep_identical_source_clock_and_parent_authorities(self):
        outputs = []
        for local in (False, True):
            with self.subTest(local=local), tempfile.TemporaryDirectory() as directory:
                path, run, request, _ = release_fixture(Path(directory), local=local)
                result = prepare(path, run)
                read = lambda name: json.loads((run/'inputs'/name).read_text())
                plan = read('frontend_geometry.json')['composition_plan']
                self.assertNotIn('composition_plan', result['outputs'])
                self.assertTrue((run/'inputs/composition_plan.json').exists())
                self.assertEqual(plan['recipe'], read('composition_plan.json')['recipe'])
                self.assertEqual(set(plan['components']), {'multipole', 'oatof'})
                self.assertEqual(plan['scope']['instance_ids'], ['oatof'] if local else ['multipole','oatof'])
                self.assertEqual(plan['scope']['boundary_connection_ids'], ['entrance'] if local else [])
                if local:
                    self.assertEqual(plan['local_scope'], request['local_scope'])
                self.assertEqual(result['particle_count'], 100)
                provenance = read('source_provenance.json')
                outputs.append((
                    {name:(run/'inputs'/name).read_bytes() for name in
                     ('particle_source.csv','projected_source.csv','clock_authority.json','instrument_epoch.json',
                      'composition_plan.json','components/oatof/resolved_design.json')},
                    {key:provenance[key] for key in ('source_instance_id','source_frame_id','transform',
                         'clock_epoch_id','instrument_epoch_us','particle_count','state_time_semantics')},
                ))
        self.assertEqual(outputs[0], outputs[1])

    def test_invalid_local_scope_rf_or_excluded_source_fails_before_sampling(self):
        changes = {
            'null': lambda r:r.update(local_scope=None),
            'empty': lambda r:r['local_scope'].update(instance_ids=[]),
            'unknown': lambda r:r['local_scope'].update(instance_ids=['missing']),
            'both': lambda r:r['local_scope'].update(instance_ids=['multipole','oatof']),
            'multipole': lambda r:r['local_scope'].update(instance_ids=['multipole']),
            'no_boundary': lambda r:r['local_scope'].pop('boundary_assumptions'),
            'rf_reference': lambda r:r['numerics'].update(rf_reference_voltage_v=100.),
            'rf_convergence': lambda r:r['numerics']['frontend_domains']['parent']['refine_convergence_v'].update(rf_reference=.001),
        }
        for name, change in changes.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path, run, request, _ = release_fixture(Path(directory), local=True)
                change(request)
                write_json(path, request)
                with patch.object(cylinder, 'generate_cylinder_release_states') as sample:
                    with self.assertRaises(ValueError):
                        prepare(path, run)
                    sample.assert_not_called()
                self.assertFalse((run/'inputs/frontend.gem').exists())
                self.assertFalse((run/'inputs/projected_source.csv').exists())
        with tempfile.TemporaryDirectory() as directory:
            path, run, _, _ = release_fixture(Path(directory), instance_id='multipole', local=True)
            with patch.object(cylinder, 'generate_cylinder_release_states') as sample:
                with self.assertRaisesRegex(ValueError, 'selected provider scope'):
                    prepare(path, run)
                sample.assert_not_called()

    def test_parent_and_entrance_freeze_separate_gems_and_preserve_complete_source(self):
        baseline = None
        for entrance in (False, True):
            with self.subTest(entrance=entrance), tempfile.TemporaryDirectory() as directory:
                path, run, request = fixture(Path(directory), entrance_refinement=entrance)
                receipt = prepare(path, run)
                design = json.loads((run/'inputs/frontend_field_design.json').read_text())
                self.assertEqual(design['schema_version'], 3)
                self.assertEqual([d['domain_id'] for d in design['domains']],
                                 ['parent','entrance_refinement'] if entrance else ['parent'])
                current = ((run/'inputs/frontend.gem').read_bytes(), (run/'inputs/projected_source.csv').read_bytes(),
                           design['working_points'], design['domains'][0])
                if baseline is None:
                    baseline = current
                else:
                    self.assertEqual(current, baseline)
                self.assertEqual(receipt['particle_count'], 100)
                for domain in design['domains']:
                    name = 'frontend' if domain['domain_id'] == 'parent' else 'frontend_entrance_refinement'
                    self.assertEqual(domain['gem_sha256'], receipt['outputs'][name]['sha256'])
                    self.assertEqual(domain['refine_convergence_v'],
                        request['numerics']['frontend_domains'][domain['domain_id']]['refine_convergence_v'])
                if entrance:
                    fine = design['domains'][1]
                    self.assertEqual(fine['parent_domain_id'], 'parent')
                    self.assertEqual(fine['boundary_policy'], 'parent_dirichlet')
                    self.assertEqual(len(fine['physical_samples']), 38)
                else:
                    self.assertNotIn('frontend_entrance_refinement', receipt['outputs'])
                    self.assertFalse((run/'inputs/frontend_entrance_refinement.gem').exists())

    def test_entrance_sheet_between_grid_nodes_fails_before_gem_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path, run, request = fixture(Path(directory), entrance_refinement=True)
            bounds = request['numerics']['frontend_domains']['entrance_refinement']['pa_bounds_mm']
            bounds['z_min'] -= .475
            bounds['z_max'] += .525
            write_json(path, request)
            with self.assertRaisesRegex(ValueError, 'ideal-sheet'):
                prepare(path, run)
            self.assertFalse((run/'inputs/frontend.gem').exists())
            self.assertFalse((run/'inputs/frontend_entrance_refinement.gem').exists())

    def test_optional_inline_flight_uses_runtime_validator_without_extra_input_copy(self):
        flight=dict(pulse=dict(mode='timed',time_us=10.,width_us=3.),maximum_flight_us=200.,
                    maximum_step_us=.001,trajectory_quality=17,rf_steps_per_period=80)
        for mutation in ('valid','held_off','off_with_time','missing','nonfinite','unknown'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as directory:
                path,run,request=fixture(Path(directory))
                request['flight']=dict(flight,pulse=dict(flight['pulse']))
                if mutation in ('held_off','off_with_time'):
                    request['flight']['pulse']=dict(mode='held_off')
                    if mutation=='off_with_time': request['flight']['pulse']['time_us']=10.
                if mutation=='missing': request['flight'].pop('maximum_step_us')
                elif mutation=='nonfinite': request['flight']['pulse']['width_us']=float('inf')
                elif mutation=='unknown': request['flight']['unbound_clock']=0
                path.write_text(json.dumps(request),encoding='utf-8',newline='\n')
                if mutation in ('valid','held_off'):
                    prepare(path,run)
                    self.assertEqual((run/'inputs/request.json').read_bytes(),path.read_bytes())
                    self.assertFalse((run/'inputs/flight.json').exists())
                else:
                    with self.assertRaises(ValueError): prepare(path,run)
                    self.assertFalse((run/'inputs/frontend.gem').exists())

    def test_discovery_preserves_author_and_scientific_inputs_for_full_and_local(self):
        for local in (False, True):
            reference = None
            for candidates in ([-2., 5., 8.], [-1., 7., 11.]):
                with self.subTest(local=local, candidates=candidates), tempfile.TemporaryDirectory() as directory:
                    path, run, request, _ = release_fixture(Path(directory), local=local)
                    request['flight'] = dict(
                        pulse=dict(mode='discover', width_us=3., candidate_times_us=candidates),
                        maximum_flight_us=200., maximum_step_us=.001, trajectory_quality=17)
                    if not local:
                        request['flight']['rf_steps_per_period'] = 80
                    write_json(path, request)
                    result = prepare(path, run)
                    self.assertEqual(result['particle_count'], 100)
                    self.assertEqual((run/'inputs/request.json').read_bytes(), path.read_bytes())
                    self.assertEqual(json.loads((run/'inputs/request.json').read_text())['flight'],
                                     request['flight'])
                    self.assertFalse((run/'inputs/flight.json').exists())
                    scientific_inputs = {
                        name: (run/'inputs'/name).read_bytes() for name in (
                            'frontend.gem', 'projected_source.csv', 'frontend_field_design.json',
                            'particle_source.csv', 'clock_authority.json', 'instrument_epoch.json')}
                    if reference is None:
                        reference = scientific_inputs
                    else:
                        self.assertEqual(scientific_inputs, reference)

    def test_discovery_invalid_candidates_fail_before_source_and_geometry_publication(self):
        pulses = [
            dict(mode='discover', width_us=3., candidate_times_us=values)
            for values in ([], None, [1., 1.], [2., 1.], [0., math.nan],
                           [0., math.inf], [True], ['1'])
        ] + [
            dict(mode='discover', width_us=width, candidate_times_us=[1.])
            for width in (0., -1., math.inf)
        ] + [
            dict(mode='discover', width_us=1., candidate_times_us=[1e308]),
            dict(mode='discover', width_us=1e308, candidate_times_us=[1e308]),
            dict(mode='discover', width_us=3., candidate_times_us=[1.], time_us=1.),
        ]
        for local in (False, True):
            for pulse in pulses:
                with self.subTest(local=local, pulse=pulse), tempfile.TemporaryDirectory() as directory:
                    path, run, request, _ = release_fixture(Path(directory), local=local)
                    request['flight'] = dict(pulse=pulse, maximum_flight_us=200.,
                                             maximum_step_us=.001, trajectory_quality=17)
                    if not local:
                        request['flight']['rf_steps_per_period'] = 80
                    write_json(path, request)
                    with self.assertRaises(ValueError):
                        prepare(path, run)
                    for name in ('frontend.gem', 'projected_source.csv', 'particle_source.csv'):
                        self.assertFalse((run/'inputs'/name).exists())

    def test_freezes_raw_inputs_once_and_projects_complete_n100_without_clock_shift(self):
        with tempfile.TemporaryDirectory() as directory:
            request_path, run, request = fixture(Path(directory))
            original_open = Path.open
            csv_reads = []

            def opened(path, *args, **kwargs):
                if path == run / "inputs/particle_source.csv" and (not args or "r" in args[0]):
                    csv_reads.append(path)
                return original_open(path, *args, **kwargs)

            with patch.object(Path, "open", opened):
                result = prepare(request_path, run)
            self.assertEqual(csv_reads, [run / "inputs/particle_source.csv"])
            self.assertEqual(result["particle_count"], 100)
            self.assertEqual(result["stage"], "geometry_preparation_only")
            self.assertNotIn("frontend_pa_plus", result["outputs"])
            self.assertFalse((run / "inputs/frontend.pa+").exists())
            self.assertEqual(
                set(result["input_records"]),
                {
                    "request",
                    "composition_plan",
                    "instance_design__multipole",
                    "instance_design__oatof",
                    "particle_source",
                    "metadata",
                    "clock_authority",
                    "instrument_epoch",
                },
            )
            author = request_path.parent
            original_source_bytes = (author / "source.csv").read_bytes()
            for key, filename in (
                ("request", "request.json"),
                ("particle_source", "source.csv"),
                ("clock_authority", "clock.json"),
                ("instrument_epoch", "epoch.json"),
            ):
                frozen = Path(result["input_records"][key]["path"])
                self.assertEqual(frozen.parent, run / "inputs")
                self.assertEqual(frozen.read_bytes(), (author / filename).read_bytes())
            rows = list(csv.DictReader(io.StringIO((run / "inputs/projected_source.csv").read_text())))
            original = list(csv.DictReader(io.StringIO((author / "source.csv").read_text(encoding="utf-8-sig"))))
            pose = json.loads((author / "parent_plan.json").read_text())["recipe"]["instances"][0]["transform"]
            for raw, actual in zip(original, rows, strict=True):
                self.assertEqual(raw["particle_id"], actual["particle_id"])
                self.assertEqual(float(actual["instrument_time_us"]), float(raw["birth_time_s"]) * 1e6)
                for target, native in zip("xyz", "zxy", strict=True):
                    self.assertEqual(
                        float(actual[f"position_{target}_mm"]),
                        float(raw[f"{native}_mm"]) + pose["translation_mm"]["xyz".index(target)],
                    )
                    self.assertEqual(float(actual[f"velocity_{target}_m_s"]), float(raw[f"v{native}_m_s"]))
                self.assertEqual(float(actual["mass_amu"]), float(raw["mass_amu"]))
            expected_kw = dict(composition_plan=json.loads((author/'parent_plan.json').read_text()),
                electrode_bindings={key:value['electrode_bindings'] for key,value in request['providers']['instances'].items()},
                accelerator_variant=request['providers']['instances']['oatof']['geometry']['accelerator_variant'])
            expected_gem, _ = compile_frontend_geometry(
                {"multipole": json.loads((author / "multipole.json").read_text())},
                json.loads((author / "oatof.json").read_text()),
                numerical_domains=request["numerics"]["frontend_domains"], **expected_kw,
            )
            self.assertEqual((run / "inputs/frontend.gem").read_text(), expected_gem["parent"])
            provenance = json.loads((run / "inputs/source_provenance.json").read_text())
            self.assertEqual(provenance["clock_epoch_id"], "instrument_clock_epoch_v1")
            self.assertEqual(list(rows[0]), GLOBAL_COLUMNS)
            with self.assertRaisesRegex(ValueError, "already exists"):
                prepare(request_path, run)
            (author / "source.csv").write_bytes(b"external source changed after preparation")
            self.assertEqual(
                Path(result["input_records"]["particle_source"]["path"]).read_bytes(), original_source_bytes
            )

    def test_release_spec_uses_one_sampler_and_one_csv_parse_for_either_instance(self):
        for instance_id in ("multipole", "oatof"):
            with self.subTest(instance=instance_id), tempfile.TemporaryDirectory() as directory:
                path, run, request, spec = release_fixture(Path(directory), instance_id=instance_id)
                original_open = Path.open
                parsed = []

                def opened(open_path, *args, **kwargs):
                    mode = args[0] if args else kwargs.get("mode", "r")
                    if open_path == run / "inputs/particle_source.csv" and mode == "r":
                        parsed.append(open_path)
                    return original_open(open_path, *args, **kwargs)

                # The public materializer also reads its CSV once for its own
                # identity receipt. Preparation performs only this one text parse.
                with (
                    patch.object(
                        cylinder, "generate_cylinder_release_states", wraps=cylinder.generate_cylinder_release_states
                    ) as sample,
                    patch.object(Path, "open", opened),
                ):
                    result = prepare(path, run)
                self.assertEqual(sample.call_count, 1)
                self.assertEqual(parsed, [run / "inputs/particle_source.csv"])
                self.assertEqual(result["particle_count"], 100)
                self.assertIn("release_spec", result["input_records"])
                self.assertNotIn("particle_source", result["input_records"])
                self.assertNotIn("metadata", result["input_records"])
                self.assertTrue({"particle_source", "release_receipt"} <= result["outputs"].keys())
                raw = list(csv.DictReader(io.StringIO((run / "inputs/particle_source.csv").read_text())))
                projected = list(csv.DictReader(io.StringIO((run / "inputs/projected_source.csv").read_text())))
                pose = next(
                    item["transform"]
                    for item in json.loads((path.parent / "parent_plan.json").read_text())["recipe"]["instances"]
                    if item["instance_id"] == instance_id
                )
                axes = "zxy" if instance_id == "multipole" else "xyz"
                for before, after in zip(raw, projected, strict=True):
                    self.assertEqual(before["particle_id"], after["particle_id"])
                    self.assertEqual(float(after["instrument_time_us"]), float(before["birth_time_s"]) * 1e6)
                    for index, (target, native) in enumerate(zip("xyz", axes, strict=True)):
                        self.assertEqual(
                            float(after[f"position_{target}_mm"]),
                            float(before[f"{native}_mm"]) + pose["translation_mm"][index],
                        )
                        self.assertEqual(float(after[f"velocity_{target}_m_s"]), float(before[f"v{native}_m_s"]))
                    self.assertEqual(float(after["mass_amu"]), 524.0)
                    self.assertEqual(after["charge_state"], before["charge_state"])
                self.assertEqual([float(raw[0][f"{axis}_mm"]) for axis in "xyz"], spec["geometry"]["center_mm"])
                self.assertNotEqual(float(raw[0]["vx_m_s"]), float(raw[0]["vz_m_s"]))
                provenance = json.loads((run / "inputs/source_provenance.json").read_text())
                self.assertEqual(provenance["source_kind"], "release_spec")
                self.assertEqual(provenance["source_frame_id"], spec["frame_id"])
                self.assertEqual(provenance["clock_epoch_id"], "instrument_clock_epoch_v1")
                self.assertIsNone(provenance["source_metadata"])
                self.assertEqual(provenance["derived_source"]["release_receipt"], result["outputs"]["release_receipt"])

    def test_source_change_does_not_change_geometry_or_field_design(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "recorded").mkdir()
            (root / "release").mkdir()
            old_path, old_run, _ = fixture(root / "recorded")
            new_path, new_run, _, _ = release_fixture(root / "release")
            prepare(old_path, old_run)
            prepare(new_path, new_run)
            for name in ("frontend.gem", "frontend_field_design.json", "frontend_geometry.json"):
                self.assertEqual(
                    (old_run / "inputs" / name).read_bytes(), (new_run / "inputs" / name).read_bytes(), name
                )
            self.assertNotEqual(
                (old_run / "inputs/projected_source.csv").read_bytes(),
                (new_run / "inputs/projected_source.csv").read_bytes(),
            )

    def test_invalid_release_authority_clock_frame_or_geometry_never_samples(self):
        mutations = {
            "mother": lambda request, spec: spec.update(mother_particle_count=101),
            "frame": lambda request, spec: spec.update(frame_id="unrelated_frame"),
            "shape": lambda request, spec: spec["geometry"].update(shape="sphere"),
            "instance": lambda request, spec: request["source"].update(instance_id="missing"),
            "recipe instance": lambda request, spec: None,
            "handoff": lambda request, spec: request["source"].update(kind="handoff"),
            "restart": lambda request, spec: request["source"].update(kind="restart"),
            "schema": lambda request, spec: request.update(schema_version=2),
            "clock": lambda request, spec: request["source"]["clock_authority"].update(sha256="0" * 64),
            "geometry": lambda request, spec: request["numerics"]["frontend_domains"]["parent"]["pa_bounds_mm"].update(x_min=-180.0),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path, run, request, spec = release_fixture(Path(directory))
                mutate(request, spec)
                if name == "recipe instance":
                    plan_path = path.parent / "parent_plan.json"
                    plan = json.loads(plan_path.read_text())
                    plan['recipe']['instances'] = [item for item in plan['recipe']['instances'] if item['instance_id'] != request['source']['instance_id']]
                    write_json(plan_path, plan)
                    request['composition_plan'] = file_record(plan_path)
                write_json(path.parent / "release_spec.json", spec)
                request["source"]["release_spec"] = file_record(path.parent / "release_spec.json")
                write_json(path, request)
                with patch(
                    "integrations.workflows.single_reflection_flight.prepare.materialize_release",
                    side_effect=AssertionError("invalid inputs must not sample"),
                ) as sample:
                    with self.assertRaises((ValueError, AssertionError)):
                        prepare(path, run)
                sample.assert_not_called()
                self.assertFalse((run / "inputs/particle_source.csv").exists())
                self.assertFalse((run / "inputs/particle_source_release_receipt.json").exists())

    def test_bad_source_identity_frame_metadata_clock_or_geometry_fails_without_products(self):
        mutations = {
            "source identity": lambda r, a: r["source"]["particle_source"].update(sha256="0" * 64),
            "frame": lambda r, a: r["source"].update(frame_id="unrelated_frame"),
            "metadata": lambda r, a: replace_document(r, a, "metadata.json", "metadata", dict(particle_count=99)),
            "epoch identity": lambda r, a: r["source"]["instrument_epoch"].update(sha256="0" * 64),
            "clock": lambda r, a: replace_document(
                r,
                a,
                "clock.json",
                "clock_authority",
                dict(authority=dict(path="wrong_epoch.json", sha256="0" * 64, field="instrument_time_us")),
            ),
            "bounds": lambda r, a: r["numerics"]["frontend_domains"]["parent"]["pa_bounds_mm"].update(x_min=-180.0),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                path, run, request = fixture(Path(directory))
                mutate(request, path.parent)
                write_json(path, request)
                with self.assertRaises((ValueError, AssertionError)):
                    prepare(path, run)
                self.assertFalse((run / "inputs/projected_source.csv").exists())
                self.assertFalse((run / "inputs/frontend.gem").exists())

    def test_duplicate_original_ids_are_not_selected_or_repaired(self):
        with tempfile.TemporaryDirectory() as directory:
            path, run, request = fixture(Path(directory))
            source = path.parent / "source.csv"
            payload = source.read_bytes().replace(b"\r\n2,", b"\r\n1,", 1)
            source.write_bytes(payload)
            request["source"]["particle_source"] = file_record(source)
            write_json(path, request)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                prepare(path, run)

    def test_partial_candidate_is_not_a_final_provider_design(self):
        with tempfile.TemporaryDirectory() as directory:
            path, run, request = fixture(Path(directory))
            partial = path.parent / "oatof.json"
            write_json(partial, dict(role="oatof_three_zone_simion_candidate_resolved", accelerator_physics={}))
            request["providers"]["instances"]["oatof"]["resolved_design"] = file_record(partial)
            write_json(path, request)
            with self.assertRaisesRegex(ValueError, "complete final resolved"):
                prepare(path, run)

    def test_epoch_is_a_reference_and_is_not_added_to_original_births(self):
        with tempfile.TemporaryDirectory() as directory:
            path, run, _ = fixture(Path(directory), epoch_bytes=b'{"instrument_time_us": 1000.0}\n')
            prepare(path, run)
            rows = list(csv.DictReader(io.StringIO((run / "inputs/projected_source.csv").read_text())))
            self.assertEqual(float(rows[0]["instrument_time_us"]), 1.0)
            provenance = json.loads((run / "inputs/source_provenance.json").read_text())
            self.assertEqual(provenance["instrument_epoch_us"], 1000.0)

    def test_available_actual_210633_source_preserves_original_clock_and_mother_population(self):
        source_run = (
            Path(__file__).resolve().parents[3]
            / "artifacts/projects/rf_octupole_ion_optics/runs/20261022_210633__sim__simion__octupole-through-exit-n100/inputs"
        )
        if not source_run.is_dir():
            self.skipTest("external actual 210633 run is unavailable in this checkout")
        source = json.loads((source_run / "multipole_resolved_design.json").read_text())
        raw = (source_run / "particle_source.csv").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            path, run, _ = fixture(
                Path(directory),
                source=source,
                source_rows=raw,
                source_metadata=json.loads((source_run / "particle_source_metadata.json").read_text()),
                clock_bytes=(source_run / "clock_authority.json").read_bytes(),
                epoch_bytes=(source_run / "instrument_epoch.json").read_bytes(),
            )
            with patch(
                "integrations.workflows.single_reflection_flight.prepare.materialize_release",
                side_effect=AssertionError("recorded mother must never be regenerated"),
            ):
                result = prepare(path, run)
            self.assertEqual(result["particle_count"], 100)
            self.assertEqual((run / "inputs/particle_source.csv").read_bytes(), raw)
            for name in ("clock_authority.json", "instrument_epoch.json"):
                self.assertEqual((run / "inputs" / name).read_bytes(), (source_run / name).read_bytes())
            mother = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
            actual = list(csv.DictReader(io.StringIO((run / "inputs/projected_source.csv").read_text())))
            self.assertEqual([row["particle_id"] for row in actual], [row["particle_id"] for row in mother])
            self.assertEqual(
                [float(row["instrument_time_us"]) for row in actual],
                [float(row["birth_time_s"]) * 1e6 for row in mother],
            )

    def test_whole_held_off_preserves_original_inputs_and_local_carrier_geometry(self):
        for local in (False, True):
            reference = None
            for mode in ('timed', 'held_off', 'discover', None):
                with self.subTest(local=local, mode=mode), tempfile.TemporaryDirectory() as directory:
                    path, run, request, _ = release_fixture(Path(directory), local=local)
                    if mode is not None:
                        pulse = ({'mode':'held_off'} if mode=='held_off' else
                            {'mode':'timed','time_us':43.,'width_us':3.} if mode=='timed' else
                            {'mode':'discover','candidate_times_us':[43.,44.],'width_us':3.})
                        request['flight'] = dict(pulse=pulse,maximum_flight_us=200.,maximum_step_us=.001,trajectory_quality=10,
                                                 **({} if local else {'rf_steps_per_period':40}))
                        write_json(path,request)
                    original_request = path.read_bytes()
                    prepare(path,run)
                    self.assertEqual(path.read_bytes(),original_request)
                    actual = json.loads((run/'inputs/frontend_field_design.json').read_text())
                    snapshot = [(run/'inputs'/name).read_bytes() for name in
                        ('frontend.gem','particle_source.csv','projected_source.csv','clock_authority.json','instrument_epoch.json')]
                    if reference is None: reference = snapshot
                    self.assertEqual(snapshot,reference)
                    self.assertEqual(any(p['kind']=='pulse_delta' for p in actual['working_points']),mode!='held_off')
                    if mode=='held_off':
                        self.assertNotIn('pulse_delta',actual['domains'][0]['refine_convergence_v'])
                        frozen=json.loads((run/'inputs/request.json').read_text())
                        self.assertIn('pulse_delta',frozen['numerics']['frontend_domains']['parent']['refine_convergence_v'])
                        if local:self.assertEqual([p['kind'] for p in actual['working_points']],['carrier_off'])


def replace_document(request, author, filename, key, updates):
    path = author / filename
    document = json.loads(path.read_text())
    document.update(updates)
    write_json(path, document)
    request["source"][key] = file_record(path)


class RecordedPrePulsePreparationTests(unittest.TestCase):
    def test_published_input_identity_requires_one_successful_producer_input_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'geometry.json'
            path.write_text('small frozen geometry')
            record = file_record(path)
            embedded = {**record, 'path': str(root / 'removed_alias/geometry.json')}
            producer = dict(role='simulation_run_manifest', status='success', inputs=dict(a=record, b=record), outputs=[])
            self.assertEqual(published_producer_input(producer, embedded), record)
            for bad in ('missing', 'outputs_only', 'tamper', 'ambiguous', 'failed'):
                with self.subTest(bad=bad):
                    invalid = copy.deepcopy(producer)
                    if bad == 'missing': invalid['inputs'] = {}
                    elif bad == 'outputs_only': invalid.update(inputs={}, outputs=[record])
                    elif bad == 'tamper': invalid['inputs'] = dict(a={**record, 'sha256': '0' * 64})
                    elif bad == 'ambiguous': invalid['inputs']['b'] = {**record, 'path': str(root / 'other.json')}
                    else: invalid['status'] = 'failed'
                    with self.assertRaises(ValueError): published_producer_input(invalid, embedded)

    @unittest.skipUnless(os.name == 'nt', 'Windows execution junction semantics')
    def test_recorded_source_uses_published_inputs_after_execution_junction_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, producer_run, _, collection_path, _, manifest_path = self._winner(root, all_states=True)
            alias = root / 'execution_alias'
            linked = subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(producer_run)],
                cwd=root, capture_output=True, text=True, check=False, timeout=30)
            self.assertEqual(linked.returncode, 0, linked.stdout + linked.stderr)
            collection = json.loads(collection_path.read_text())
            try:
                for key in ('geometry_record', 'source_record', 'request_record'):
                    record = collection[key]
                    record['path'] = str(alias / Path(record['path']).relative_to(producer_run))
                write_json(collection_path, collection)
            finally:
                os.rmdir(alias)
            producer = json.loads(manifest_path.read_text())
            producer['outputs'] = [file_record(collection_path)]
            write_json(manifest_path, producer)
            (root / 'consumer').mkdir()
            path, run, request = fixture(root / 'consumer')
            request['source'] = dict(kind='recorded_pre_pulse_state', instance_id='oatof', frame_id='oatof_global',
                pre_pulse_collection=file_record(collection_path), producer_manifest=file_record(manifest_path),
                **{key: request['source'][key] for key in ('clock_authority', 'instrument_epoch')})
            write_json(path, request)
            result = prepare(path, run)
            self.assertEqual(result['particle_count'], 100)
            self.assertEqual((run / 'inputs/pre_pulse_source_states.csv').read_bytes(),
                             (producer_run / 'inputs/projected_source.csv').read_bytes())
            self.assertEqual(json.loads((run / 'inputs/pre_pulse_collection.json').read_text()), collection)

    def test_available_actual_110745_recorded_source_prepares_all_100_states(self):
        runs = Path(__file__).resolve().parents[3] / 'artifacts/projects/instrument_assembly/runs'
        producer = runs / '20261025_110745__sim__simion__single-reflection-flight'
        parent = runs / '20261025_193652__analysis__python__current-parent-preparation/inputs'
        if not (producer / 'run_manifest.json').is_file() or not (parent / 'request.json').is_file():
            self.skipTest('optional frozen 110745/193652 source inputs are unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = json.loads((parent / 'request.json').read_text())
            request['schema_version'] = 9
            request['composition_plan'] = file_record(parent / 'composition_plan.json')
            request['local_scope'] = dict(instance_ids=['oatof'], research_scope='recorded OA source path lifetime',
                boundary_assumptions='explicit OA-only source preparation; no native field or flight claim')
            request['providers']['instances'].pop('multipole')
            del request['numerics']['rf_reference_voltage_v']
            del request['numerics']['frontend_domains']['parent']['refine_convergence_v']['rf_reference']
            request['numerics']['frontend_domains'].pop('entrance_refinement', None)
            if 'flight' in request:
                request['flight'].pop('rf_steps_per_period', None)
            request['source'] = dict(kind='recorded_pre_pulse_state', instance_id='oatof', frame_id='oatof_global',
                pre_pulse_collection=file_record(producer / 'results/single_reflection/baseline/collection.json'),
                producer_manifest=file_record(producer / 'run_manifest.json'),
                clock_authority=file_record(producer / 'inputs/clock_authority.json'),
                instrument_epoch=file_record(producer / 'inputs/instrument_epoch.json'))
            path = root / 'request.json'
            write_json(path, request)
            (root / 'consumer/inputs').mkdir(parents=True)
            result = prepare(path, root / 'consumer')
            self.assertEqual(result['particle_count'], 100)
            provenance = json.loads((root / 'consumer/inputs/source_provenance.json').read_text())
            self.assertEqual(provenance['continued_particle_ids'], list(range(1, 101)))
            self.assertEqual(provenance['restart_state_time_us'], 50.68181818181818)
            self.assertEqual((root / 'consumer/inputs/pre_pulse_source_states.csv').read_bytes(),
                             (producer / 'inputs/projected_source.csv').read_bytes())

    def test_recorded_source_rejects_tampered_published_payload_and_wrong_producer(self):
        for bad in ('tampered_payload', 'wrong_producer'):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, producer_run, _, collection_path, _, manifest_path = self._winner(root, all_states=True)
                producer = json.loads(manifest_path.read_text())
                if bad == 'tampered_payload':
                    with (producer_run / 'inputs/projected_source.csv').open('a') as stream:
                        stream.write('tampered')
                else:
                    producer['outputs'] = []
                    write_json(manifest_path, producer)
                (root / 'consumer').mkdir()
                path, run, request = fixture(root / 'consumer')
                request['source'] = dict(kind='recorded_pre_pulse_state', instance_id='oatof', frame_id='oatof_global',
                    pre_pulse_collection=file_record(collection_path), producer_manifest=file_record(manifest_path),
                    **{key: request['source'][key] for key in ('clock_authority', 'instrument_epoch')})
                write_json(path, request)
                with self.assertRaises((ValueError, AssertionError)):
                    prepare(path, run)

    def test_recorded_native_states_survive_changed_parent_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, _, collection, decision, manifest = self._winner(root)
            results = []
            for number, change in enumerate(({}, dict(translation=(0.,64.,0.)),
                    dict(rotation=((0.,-1.,0.),(1.,0.,0.),(0.,0.,1.))))):
                author = root / str(number)
                author.mkdir()
                path, run, request = fixture(author)
                request['source'] = dict(kind='recorded_pre_pulse_state', instance_id='oatof',
                    frame_id='oatof_global', pre_pulse_collection=file_record(collection),
                    pulse_decision=file_record(decision), producer_manifest=file_record(manifest),
                    **{key: request['source'][key] for key in ('clock_authority','instrument_epoch')})
                plan_path = record_path(request['composition_plan'], base_dir=path.parent)
                plan = json.loads(plan_path.read_text())
                if change:
                    write_json(plan_path, reframe_parent(plan, **change))
                    request['composition_plan'] = file_record(plan_path)
                write_json(path, request)
                result = prepare(path, run)
                self.assertIn('pre_pulse_source_provenance', result['input_records'])
                provenance = json.loads((run/'inputs/source_provenance.json').read_text())
                self.assertIsNone(provenance['transform'])
                self.assertEqual(provenance['target_frame_id'], 'oatof_global')
                results.append(tuple((run/'inputs'/name).read_bytes() for name in (
                    'frontend.gem','frontend_field_design.json','projected_source.csv',
                    'clock_authority.json','instrument_epoch.json')))
            self.assertEqual(results[0], results[1])
            self.assertEqual(results[0], results[2])

    def _winner(self, root: Path, *, all_states: bool = False):
        (root / "winner").mkdir()
        path, run, request = fixture(root / "winner")
        request["flight"] = dict(pulse=dict(mode="timed", time_us=10.0, width_us=.1), maximum_flight_us=20., maximum_step_us=.1, trajectory_quality=8, rf_steps_per_period=32)
        write_json(path, request)
        receipt = prepare(path, run)
        geometry = receipt["outputs"]["frontend_geometry"]
        source = receipt["outputs"]["projected_source"]
        with Path(source["path"]).open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        events=[]
        for row in rows:
            pid=int(row["particle_id"]); birth=float(row["instrument_time_us"])
            events.append(dict(particle_id=pid,event="source_release",instrument_time_us=birth,x_mm=float(row["position_x_mm"]),y_mm=float(row["position_y_mm"]),z_mm=float(row["position_z_mm"]),vx_mm_per_us=float(row["velocity_x_m_s"])/1000,vy_mm_per_us=float(row["velocity_y_m_s"])/1000,vz_mm_per_us=float(row["velocity_z_m_s"])/1000,kinetic_energy_eV=float(row["kinetic_energy_eV"])))
        for pid in (range(1,101) if all_states else (8,7)):
            row=rows[pid-1]
            projection=json.loads(Path(geometry["path"]).read_text())["accelerator_projection"]
            events.append(dict(particle_id=pid,event="pre_pulse_state",instrument_time_us=10.,x_mm=projection["axis_x_mm"],y_mm=projection["axis_y_mm"],z_mm=(projection["repeller_front_z_mm"]+projection["grid1_z_mm"])/2,vx_mm_per_us=float(row["velocity_x_m_s"])/1000,vy_mm_per_us=float(row["velocity_y_m_s"])/1000,vz_mm_per_us=float(row["velocity_z_m_s"])/1000,kinetic_energy_eV=float(row["kinetic_energy_eV"])))
        collection=dict(schema_version=1,role="single_reflection_complete_mother_collection",phase="full_instrument",native_complete=True,clock_epoch_id="instrument_clock_epoch_v1",request_record=receipt["input_records"]["request"],geometry_record=geometry,source_record=source,flight=request["flight"],canonical_events=events)
        collection_path=run/"results/collection.json"; collection_path.parent.mkdir(); write_json(collection_path,collection)
        decision=dict(schema_version=2,role="single_reflection_actual_occupancy_pulse_decision",status="success",selection_uses_future_terminal_outcome=False,actual_pulse_time_us=10.,selection=dict(status="selected",selected_time_us=10.,selected=dict(eligible_ids=[8,7]),execution_cohort_count=100),input_records=dict(request=receipt["input_records"]["request"],frontend_geometry=geometry,collection=file_record(collection_path)))
        decision_path=run/"results/pulse_decision.json"; write_json(decision_path,decision)
        manifest=dict(schema_version=2,role="simulation_run_manifest",status="success",inputs=dict(geometry=geometry,source=source,source_provenance=receipt['outputs']['source_provenance']),outputs=[file_record(collection_path),file_record(decision_path)])
        manifest_path=run/"run_manifest.json"; write_json(manifest_path,manifest)
        return path,run,request,collection_path,decision_path,manifest_path

    def test_explicit_timed_source_without_decision_preserves_all_states_mother_and_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            _,_,_,collection,_,manifest=self._winner(root,all_states=True)
            producer=json.loads(manifest.read_text())
            producer['outputs']=[file_record(collection)]
            write_json(manifest,producer)
            results=[];births=[]
            for number,(local,moved) in enumerate(((False,False),(True,False),(False,True),(True,True))):
                author=root/str(number);author.mkdir()
                path,run,request=fixture(author)
                request['source']=dict(kind='recorded_pre_pulse_state',instance_id='oatof',
                    frame_id='oatof_global',pre_pulse_collection=file_record(collection),
                    producer_manifest=file_record(manifest),
                    **{key:request['source'][key] for key in ('clock_authority','instrument_epoch')})
                if local:
                    request['providers']['instances'].pop('multipole')
                    request['local_scope']=dict(instance_ids=['oatof'],research_scope='timed OA source',
                        boundary_assumptions='explicit local scope from parent')
                    del request['numerics']['rf_reference_voltage_v']
                    del request['numerics']['frontend_domains']['parent']['refine_convergence_v']['rf_reference']
                if moved:
                    parent_path=record_path(request['composition_plan'],base_dir=path.parent)
                    write_json(parent_path,reframe_parent(json.loads(parent_path.read_text()),translation=(0.,64.,0.)))
                    request['composition_plan']=file_record(parent_path)
                write_json(path,request)
                receipt=prepare(path,run)
                provenance=json.loads((run/'inputs/source_provenance.json').read_text())
                self.assertEqual(receipt['particle_count'],100)
                self.assertEqual(provenance['continued_particle_ids'],list(range(1,101)))
                self.assertEqual(provenance['original_mother_particle_ids'],list(range(1,101)))
                self.assertEqual(provenance['selection_basis'],'all_recorded_timed_pre_pulse_states')
                self.assertIsNone(provenance['transform'])
                self.assertNotIn('pulse_decision',receipt['input_records'])
                self.assertFalse((run/'inputs/pre_pulse_decision.json').exists())
                results.append(tuple((run/'inputs'/name).read_bytes() for name in (
                    'projected_source.csv','pre_pulse_source_states.csv','clock_authority.json','instrument_epoch.json')))
                births.append(provenance['original_birth_times_us'])
            self.assertTrue(all(value==results[0] for value in results))
            self.assertTrue(all(value==births[0] for value in births))

    def test_restart_freezes_noncontiguous_winner_states_for_full_and_local_scope(self):
        for local,pulse in ((local,pulse) for local in (False, True) for pulse in (
                dict(mode="timed",time_us=10.,width_us=.1),
                dict(mode="timed",time_us=12.,width_us=.1),dict(mode="held_off"))):
            with self.subTest(local=local,pulse=pulse), tempfile.TemporaryDirectory() as directory:
                root=Path(directory); _,_,winner,collection,decision,manifest=self._winner(root)
                (root / "consumer").mkdir()
                path,run,request=fixture(root/"consumer")
                frame=json.loads(Path(json.loads(Path(collection).read_text())["geometry_record"]["path"]).read_text())["composition_plan"]["assembly_frame_id"]
                request["source"]=dict(kind="recorded_pre_pulse_state",instance_id="oatof",frame_id=frame,
                    pre_pulse_collection=file_record(collection),pulse_decision=file_record(decision),producer_manifest=file_record(manifest),
                    clock_authority=request["source"]["clock_authority"],instrument_epoch=request["source"]["instrument_epoch"])
                request["flight"]=dict(pulse=pulse,maximum_flight_us=20.,maximum_step_us=.1,trajectory_quality=8,rf_steps_per_period=32)
                if local:
                    request["providers"]["instances"].pop("multipole")
                    del request["flight"]["rf_steps_per_period"]
                    request["local_scope"]=dict(instance_ids=["oatof"],research_scope="OA continuation",boundary_assumptions="explicit local continuation")
                    del request["numerics"]["rf_reference_voltage_v"]
                    del request["numerics"]["frontend_domains"]["parent"]["refine_convergence_v"]["rf_reference"]
                write_json(path,request)
                result=prepare(path,run)
                with (run/"inputs/projected_source.csv").open(encoding="utf-8", newline="") as stream:
                    states=list(csv.DictReader(stream))
                self.assertEqual([row["particle_id"] for row in states],["8","7"])
                self.assertEqual([float(row["instrument_time_us"]) for row in states],[10.,10.])
                provenance=json.loads((run/"inputs/source_provenance.json").read_text())
                self.assertEqual(provenance["original_mother_particle_count"],100)
                self.assertEqual(provenance["continued_particle_ids"],[8,7])
                self.assertNotEqual(provenance["original_birth_times_us"]["8"],10.)
                self.assertEqual(result["particle_count"],2)
                self.assertEqual(json.loads((run/"inputs/request.json").read_text())["flight"]["pulse"],pulse)

    def test_restart_rejects_clock_unknown_frame_or_invalid_current_release_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); _,_,winner,collection,decision,manifest=self._winner(root)
            for bad in ("clock","unknown_frame","source_outside","missing_provenance"):
                with self.subTest(bad=bad):
                    (root/bad).mkdir()
                    path,run,request=fixture(root/bad)
                    frame=json.loads(Path(json.loads(Path(collection).read_text())["geometry_record"]["path"]).read_text())["composition_plan"]["assembly_frame_id"]
                    request["source"]=dict(kind="recorded_pre_pulse_state",instance_id="oatof",frame_id=frame,pre_pulse_collection=file_record(collection),pulse_decision=file_record(decision),producer_manifest=file_record(manifest),clock_authority=request["source"]["clock_authority"],instrument_epoch=request["source"]["instrument_epoch"])
                    request["flight"]=dict(pulse=dict(mode="timed",time_us=10.,width_us=.1),maximum_flight_us=20.,maximum_step_us=.1,trajectory_quality=8,rf_steps_per_period=32)
                    if bad=="clock":
                        clock_path=path.parent / request["source"]["clock_authority"]["path"]; clock=json.loads(clock_path.read_text()); clock["clock_epoch_id"]="other"; write_json(path.parent/"clock_other.json",clock); request["source"]["clock_authority"]=file_record(path.parent/"clock_other.json")
                    elif bad=="unknown_frame":
                        request['source']['frame_id'] = 'unproven_state_frame'
                    elif bad=="missing_provenance":
                        producer_manifest=json.loads(manifest.read_text())
                        producer_manifest['inputs'].pop('source_provenance')
                        write_json(manifest,producer_manifest)
                        request['source']['producer_manifest']=file_record(manifest)
                    else:
                        native=json.loads(collection.read_text())
                        next(row for row in native["canonical_events"] if row["event"]=="pre_pulse_state")["x_mm"]+=1000
                        write_json(collection,native)
                        producer_manifest=json.loads(manifest.read_text())
                        producer_manifest["outputs"][0]=file_record(collection)
                        write_json(manifest,producer_manifest)
                        request["source"].update(pre_pulse_collection=file_record(collection),producer_manifest=file_record(manifest))
                    write_json(path,request)
                    with self.assertRaises(ValueError): prepare(path,run)


if __name__ == "__main__":
    unittest.main()
