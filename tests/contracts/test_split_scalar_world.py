"""Scientific slot planning for a split scalar world; no native execution."""
import copy

from msplatform.backends.simion.split_scalar_workbench import project_split_scalar_world, WORLD_SLOTS
from tests.contracts.test_split_scalar_binding import SplitScalarBindingTests


class SplitScalarWorldTests(SplitScalarBindingTests):
    def _owner_field_fixture(self):
        """Build tiny sealed test-only producers; no bytes are native solver evidence."""
        import json
        from msplatform.backends.simion.field_bank import field_bank
        from msplatform.backends.simion.resources import native_resource_path
        from msplatform.execution.terminal_publication import publish_terminal_state
        from msplatform.io.manifest_records import file_record
        base = self.helper.root
        original = base / 'ground-original'
        derived = base / 'ground-derived'
        original.mkdir(); derived.mkdir()
        records = {}
        def put(name, data):
            path = original / name
            path.write_bytes(data)
            return file_record(path)
        def encoded(value): return json.dumps(value, allow_nan=False).encode('utf-8')
        records['compiled_model'] = put('model.json', encoded(self.model.document))
        design = {'domains': [{'domain_id': 'parent'}], 'working_points': []}
        records['field_design'] = put('field-design.json', encoded(design))
        records['field_bank'] = put('field-bank.json', encoded(field_bank(design, ['parent'])))
        records['parent'] = put('parent.pa', b'test-only')
        for role in ('flight_tube', 'detector'):
            for suffix in ('pa#', 'pa0', 'pa1', 'pa-surf'):
                records[role+'_'+suffix] = put(role+'.'+suffix, b'test-only '+suffix.encode())
        records['reflectron'] = put('reflectron.pa', b'test-only')
        builders = {}
        for name in ('build_flight_tube_variant.lua', 'build_detector_variant.lua', 'gem2pa_geometry.lua'):
            data = native_resource_path(name).read_bytes()
            record = put(name, data)
            records['resource_'+name] = record
            builders[name] = record['sha256']
        native_assets = {role: {'carrier': role+'_pa0', 'family': [role+'_'+suffix for suffix in ('pa#','pa0','pa1','pa-surf')]}
                         for role in ('flight_tube', 'detector')}
        native_assets['reflectron'] = {'carrier': 'reflectron', 'family': []}
        metadata = {'backend':'simion', 'field_status':'available', 'source_status':'not_requested',
            'model_identity_sha256': self.model.document['model_identity_sha256'], 'clock':self.model.document['drive']['clock'],
            'downstream_identity': {'builder_identities': builders}, 'native_assets':native_assets,
            'frontend_members': {'parent': {'carrier_off': {'data_key':'parent'}}}}
        def publish(root, meta, data, inputs, outputs, mode='test_only'):
            manifest = {'schema_version':2,'role':'simulation_run_manifest','run_id':root.name,
                'project':'instrument_assembly','mode':mode,'status':'success','inputs':inputs,'outputs':outputs,
                'products':{'fields':{'schema_version':1,'kind':'field_bundle','status':'complete','metadata':meta,'data':data}}}
            publish_terminal_state(root, {'status':'success'}, manifest)
            return {'manifest': file_record(root/'run_manifest.json'), 'product_id':'fields'}
        origin = publish(original, metadata, records, {}, list(records.values()))
        ground = copy.deepcopy(metadata)
        ground.update(ground_representation='analytic_zero_on_native_geometry',ground_source_reference=origin,
                      ground_boundary_condition='ground_dirichlet_zero_outer_homogeneous_neumann',
                      ground_refine_calls=0,ground_fly_calls=0)
        data = dict(records)
        for role in ('flight_tube','detector'):
            for suffix in ('pa','pa-surf'):
                path=derived/(role+'.'+suffix);path.write_bytes(b'test-only grounded carrier')
                data[role+'_analytic_'+suffix]=file_record(path)
            ground['native_assets'][role]={'carrier':role+'_analytic_pa','family':[role+'_analytic_pa-surf']}
        request_dir=derived/'inputs';request_dir.mkdir(exist_ok=True)
        (request_dir/'execution_request.json').write_text(json.dumps({'payload': {'action':'prepare_grounded_runtime_fields','fields':origin}}),encoding='utf8')
        for role in ('flight_tube','detector'):
            for operation in ('build','verify'):
                key='analytic_ground_'+operation+'_'+role+'_log'
                path=derived/(key+'.txt');path.write_text('ANALYTIC_ZERO_GROUND_'+operation.upper()+'=PASS',encoding='utf8')
                data[key]=file_record(path)
        owned=[data[key] for key in data if '_analytic_' in key or key.startswith('analytic_ground_')]
        borrowed={key:record for key,record in records.items() if key not in {
            role+'_'+suffix for role in ('flight_tube','detector') for suffix in ('pa#','pa0','pa1','pa-surf')}}
        data={**borrowed,**{key:data[key] for key in data if '_analytic_' in key or key.startswith('analytic_ground_')}}
        source=publish(derived,ground,data,{**borrowed, 'ground_source_manifest':origin['manifest'],
            'execution_request':file_record(request_dir/'execution_request.json')},owned,mode='fields_only')
        return source, origin

    def test_admission_authenticates_ground_origin_and_rejects_old_family_or_tamper(self):
        from unittest.mock import patch
        from msplatform.backends.simion.split_scalar_workbench import _admit_world
        source, origin = self._owner_field_fixture()
        selection = {'geometry_artifact': self.geometry, 'samples': self.samples}
        binding = self.resolve()
        with patch('msplatform.backends.simion.split_scalar_binding.resolve_split_scalar_basis', return_value=binding):
            opened, _, _, carriers = _admit_world(source, selection)
            self.assertEqual(opened.metadata['ground_source_reference'], origin)
            self.assertTrue(carriers['flight_tube']['path'].endswith('flight_tube.pa'))
            with self.assertRaisesRegex(ValueError, 'derived analytic ground'):
                _admit_world(origin, selection)
            manifest = __import__('pathlib').Path(origin['manifest']['path'])
            saved = manifest.read_bytes()
            manifest.write_bytes(saved + b' ')
            with self.assertRaises((AssertionError, ValueError, OSError)):
                _admit_world(source, selection)
            manifest.write_bytes(saved)
            manifest.unlink()
            with self.assertRaises((AssertionError, ValueError, OSError)):
                _admit_world(source, selection)

    def test_real_model_world_projection_and_rejections(self):
        binding = self.resolve()
        carriers = {role: {"path": str(self.helper.root / (role + ".pa")), "bytes": 10, "sha256": "0" * 64}
                    for role in ("flight_tube", "reflectron", "accelerator", "detector")}
        def project(value):
            return project_split_scalar_world(self.model, value, carriers=carriers,
                                              background_path=self.helper.root / "background.pa")
        result = project(binding)
        from msplatform.backends.simion.native_plans import plan_split_scalar_world_build
        from msplatform.backends.simion.resources import structural_seed_path, STRUCTURAL_SEEDS
        from msplatform.execution.resources import resource_path
        run = self.helper.root / "world"
        planned = project_split_scalar_world(self.model, binding, carriers=carriers,
                                              background_path=run / "simion/world/background.pa")
        size, digest = STRUCTURAL_SEEDS[5]
        stage = plan_split_scalar_world_build(planned, run_directory=run,
            seed_record={"path": str(structural_seed_path(5)), "bytes": size, "sha256": digest},
            native_path_resource=resource_path("native_run_path.lua"))
        canonical = self.helper.root / "canonical-world"
        canonical_stage = plan_split_scalar_world_build(planned, run_directory=run,
            seed_record={"path": str(structural_seed_path(5)), "bytes": size, "sha256": digest},
            native_path_resource=resource_path("native_run_path.lua"), canonical_run_directory=canonical)
        canonical_spec = canonical_stage.materializations[str(run / "inputs/world_iob.lua")]
        self.assertIn("preserve_canonical_output=true", canonical_spec)
        self.assertIn("preserve_canonical_instances=true", canonical_spec)
        self.assertIn(str(canonical / "simion/world/world.iob").replace("\\", "\\\\"), canonical_spec)
        self.assertEqual([row["operation_id"] for row in stage.operations],
                         ["background_build", "background_verify", "collision_iob_build", "collision_iob_verify"])
        self.assertTrue(all(row["stage"] == "prepare" for row in stage.operations))
        self.assertIn("split_scalar_world_iob_build", stage.materializations[str(run / "inputs/world_iob.lua")])
        from msplatform.backends.simion.native_plans import plan_split_scalar_world_tracking
        source_row = {"position_x_mm": "0", "position_y_mm": "0", "position_z_mm": "0",
                      "velocity_x_m_s": "0", "velocity_y_m_s": "0", "velocity_z_m_s": "1",
                      "mass_amu": "100", "charge_state": "1"}
        tracking = plan_split_scalar_world_tracking(planned,
            world_iob_record={"path": str(run / "simion/world/world.iob"), "bytes": 1, "sha256": "0" * 64},
            program="return {}", native_source_rows=[source_row], run_directory=run / "flight",
            native_path_resource=resource_path("native_run_path.lua"))
        self.assertEqual([row["operation_id"] for row in tracking.operations], ["build_tracking_iob", "verify_tracking_iob"])
        self.assertEqual(len(tracking.input_copies), 1)
        canonical_tracking = plan_split_scalar_world_tracking(planned,
            world_iob_record={"path": str(run / "simion/world/world.iob"), "bytes": 1, "sha256": "0" * 64},
            program="return {}", native_source_rows=[source_row], run_directory=run / "flight",
            native_path_resource=resource_path("native_run_path.lua"), canonical_run_directory=canonical)
        tracking_spec = canonical_tracking.materializations[str(run / "flight/inputs/tracking_world_iob.lua")]
        self.assertIn("preserve_canonical_output=true", tracking_spec)
        self.assertIn("preserve_canonical_instances=true", tracking_spec)
        self.assertEqual(canonical_tracking.input_copies[0]["source_record"]["sha256"], digest)
        self.assertEqual(tracking.input_copies[0]["source_record"]["bytes"], size)
        self.assertIn("split_scalar_world_tracking_iob", tracking.materializations[str(run / "flight/inputs/tracking_world_iob.lua")])
        invalid_slots = copy.deepcopy(planned)
        invalid_slots["slots"][0]["priority_number"] = 2
        with self.assertRaisesRegex(ValueError, "priority"):
            plan_split_scalar_world_tracking(invalid_slots,
                world_iob_record={"path": str(run / "simion/world/world.iob"), "bytes": 1, "sha256": "0" * 64},
                program="return {}", native_source_rows=[source_row], run_directory=run / "flight",
                native_path_resource=resource_path("native_run_path.lua"))
        self.assertEqual(result["role_slots"], WORLD_SLOTS)
        self.assertEqual([row["role"] for row in result["slots"]], list(WORLD_SLOTS))
        self.assertEqual([row["priority_number"] for row in result["slots"]], [1,2,3,4,5])
        self.assertEqual(result["grid"], self.grid)
        for change in (lambda b:b["bases"]["on"]["grid"]["dimensions"].__setitem__(0, 4),
                       lambda b:b["bases"]["off"]["grid"].__setitem__("frame_id", "other"),
                       lambda b:b.__setitem__("model_identity_sha256", "0" * 64)):
            invalid = copy.deepcopy(binding)
            change(invalid)
            with self.assertRaises(ValueError):
                project(invalid)
        wrong = copy.deepcopy(carriers)
        wrong.pop("detector")
        with self.assertRaises(ValueError):
            project_split_scalar_world(self.model, binding, carriers=wrong, background_path=self.helper.root / "background.pa")

    def test_public_action_reaches_managed_owner_with_all_source_references(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from unittest.mock import patch
        import sys
        from msplatform.backends import simion
        binding = self.resolve()
        def reference(name):
            return {"manifest": {"path": str(self.helper.root / (name + ".json")), "bytes": 1, "sha256": "0" * 64},
                    "product_id": name}
        field, geometry = reference("field"), reference("geometry")
        binding["geometry_reference"] = geometry
        for name in ("off", "on"):
            binding["bases"][name]["reference"] = reference(name)
            binding["bases"][name]["field_solution_reference"] = reference(name + "_solution")
        carriers = {role: {"path": str(self.helper.root / (role + ".pa")), "bytes": 10, "sha256": "0" * 64}
                    for role in ("flight_tube", "reflectron", "accelerator", "detector")}
        origin = reference("origin")
        source = SimpleNamespace(reference=field, data_records={}, metadata={"ground_representation": "analytic_zero_on_native_geometry",
                                                            "ground_source_reference": origin})
        stage = {"limits": {"transient_run_directory_bytes": 1}, "artifact_retention": {}}
        context = SimpleNamespace(tools={"simion": __import__("pathlib").Path(sys.executable)},
                                  workspace=self.helper.root, execution_root=self.helper.root / "exec")
        selection = {"geometry_artifact": geometry, "samples": {"off": reference("off"), "on": reference("on")}}
        with patch("msplatform.execution.stage_policy.read_stage_policy", return_value=(stage, {})), \
             patch("msplatform.execution.native_source_guard.guard_native_source", side_effect=lambda *a, **k: nullcontext(source)), \
             patch("msplatform.backends.simion.split_scalar_workbench._admit_world", return_value=(source,self.model,binding,carriers)), \
             patch("msplatform.execution.owner.run_managed_stage", side_effect=RuntimeError("INERT_WORLD_OWNER")) as owner:
            with self.assertRaisesRegex(RuntimeError, "INERT_WORLD_OWNER"):
                simion.prepare_split_scalar_world(field, scalar_field_basis=selection, context=context)
        call = owner.call_args.kwargs
        self.assertEqual(call["expected_operation_ids"], ("background_build", "background_verify", "collision_iob_build", "collision_iob_verify"))
        self.assertEqual(len(call["source_references"]), 7)
        self.assertIn(origin["manifest"], [row["manifest_record"] for row in call["source_references"]])

    def test_captured_basis_original_owners_protected_until_success_or_failure(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from unittest.mock import patch
        import sys
        from pathlib import Path
        from msplatform.backends import simion
        from msplatform.backends.simion.model_execution import _protected_source
        from msplatform.io.manifest_records import file_record
        binding = self.resolve()
        def ref(name):
            return {'manifest':{'path':str(self.helper.root/(name+'.json')),'bytes':1,'sha256':'0'*64}, 'product_id':name}
        field, origin, geometry = ref('field'), ref('origin'), ref('geometry')
        binding['geometry_reference']=geometry
        for name in ('off','on'):
            binding['bases'][name]['reference']=ref(name)
            binding['bases'][name]['field_solution_reference']=ref(name+'_solution')
        carriers={role:{'path':str(self.helper.root/(role+'.pa')),'bytes':10,'sha256':'0'*64}
                  for role in ('flight_tube','reflectron','accelerator','detector')}
        source=SimpleNamespace(reference=field,metadata={'ground_representation':'analytic_zero_on_native_geometry',
                                                         'ground_source_reference':origin})
        roots=[];records=[]
        for name in ('original_failed','original_prepared'):
            root=self.helper.root/name;root.mkdir();path=root/'run_manifest.json';path.write_text(name,encoding='utf8')
            (root/'member.dat').write_text('protected',encoding='utf8')
            roots.append(root);records.append(file_record(path,'required_evidence'))
        context=SimpleNamespace(tools={'simion':Path(sys.executable)},workspace=self.helper.root,
                                execution_root=self.helper.root/'exec')
        selection={'geometry_artifact':geometry,'samples':{'off':ref('off'),'on':ref('on')}}
        stage={'limits':{'transient_run_directory_bytes':1},'artifact_retention':{}}
        session=SimpleNamespace(artifact_root=self.helper.root,capacity_session={'status':'active',
            'protected_paths':[str(path) for path in roots],'source_protection_leases':[]})
        def consumed(manifest,**kwargs):
            return {'run_directory':str(Path(manifest['path']).parent)}
        should_fail=[True]
        def run_owner(*args,**kwargs):
            authorities=[value['manifest_record'] for value in kwargs['source_references']]
            for record,root in zip(records,roots,strict=True):
                self.assertIn(record,authorities)
                _protected_source(session,record,required_paths=[root/'member.dat'])
                with self.assertRaises(PermissionError):Path(record['path']).write_text('mutate')
            if should_fail[0]: raise RuntimeError('inert owner failure')
            return {'manifest':{'path':'inert'}}
        with patch('msplatform.execution.stage_policy.read_stage_policy',return_value=(stage,{})), \
             patch('msplatform.execution.native_source_guard.guard_native_source',side_effect=lambda *a,**k:nullcontext(source)), \
             patch('msplatform.backends.simion.split_scalar_workbench._admit_world',return_value=(source,self.model,binding,carriers)), \
             patch('msplatform.backends.simion.split_scalar_workbench._basis_original_owner_refs',return_value=records), \
             patch('msplatform.backends.simion.model_execution.resolve_consumed_run_capacity_owner',side_effect=consumed), \
             patch('msplatform.execution.owner.run_managed_stage',side_effect=run_owner), \
             patch('msplatform.results.artifacts.open_artifact',return_value='inert published'):
            with self.assertRaisesRegex(RuntimeError,'inert owner failure'):
                simion.prepare_split_scalar_world(field,scalar_field_basis=selection,context=context)
            for record in records:
                with Path(record['path']).open('ab'): pass
            should_fail[0]=False
            self.assertEqual(simion.prepare_split_scalar_world(field,scalar_field_basis=selection,context=context),
                             'inert published')
        for record in records:
            with Path(record['path']).open('ab'): pass
        with patch('msplatform.backends.simion.model_execution.resolve_consumed_run_capacity_owner',side_effect=consumed):
            session.capacity_session['protected_paths']=[]
            with self.assertRaisesRegex(ValueError,'no active owner protection'):
                _protected_source(session,records[0],required_paths=[roots[0]/'member.dat'])

    def test_real_capacity_owner_protects_and_releases_both_source_roots(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from msplatform.execution.capacity_ledger import initialize_capacity_ledger
        from msplatform.execution.capacity_protection import load_capacity_protection_leases
        from msplatform.execution.capacity_session import create_capacity_session, exit_capacity_session
        from msplatform.backends.simion.model_execution import _protected_source
        from tests.contracts.test_cross_root_protection import CrossRootProtectionTests
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);factory=CrossRootProtectionTests()
            run1,ref1=factory.source(base/'failed-original')
            run2,ref2=factory.source(base/'prepared-original')
            target=base/'consumer';target.mkdir();initialize_capacity_ledger(target,objects=[])
            run=target/'world';run.mkdir()
            for fail in (False,True):
                session=create_capacity_session(target,run,owner='inert-world',committed_new_bytes=0,
                                                source_references=[ref1,ref2])
                context=SimpleNamespace(artifact_root=target,capacity_session=session)
                try:
                    for origin,ref in ((run1,ref1),(run2,ref2)):
                        _protected_source(context,ref['manifest_record'],required_paths=[origin/'run_config.json'])
                        view=load_capacity_protection_leases(origin.parents[3])
                        self.assertTrue(view['audit'])
                    if fail: raise RuntimeError('inert failure')
                except RuntimeError:
                    self.assertTrue(fail)
                finally:
                    exit_capacity_session(session)
                for root in (base/'failed-original',base/'prepared-original'):
                    leases=load_capacity_protection_leases(root)
                    self.assertEqual(leases['audit'],[])

    def test_normal_solution_declared_prepared_owner_and_forgery_rejection(self):
        from types import SimpleNamespace
        from msplatform.backends.simion.split_scalar_workbench import _basis_original_owner_refs
        from msplatform.execution.terminal_publication import publish_terminal_state
        from msplatform.io.manifest_records import file_record
        root=self.helper.root;prepared_root=root/'prepared-owner';prepared_root.mkdir()
        prepared_doc={'role':'simulation_run_manifest','status':'success','products':{'model':{
            'kind':'prepared_model','status':'complete','metadata':{'backend':'comsol'}}},'inputs':{},'outputs':[]}
        publish_terminal_state(prepared_root,{'status':'success'},prepared_doc)
        prepared=file_record(prepared_root/'run_manifest.json','required_evidence')
        meta={'scope':'single_stationary_workpoint'}
        def make_source(bound=True):
            solution_root=root/('single-solution' if bound else 'unbound-solution');solution_root.mkdir()
            manifest={'role':'simulation_run_manifest','status':'success','inputs':{'prepared':prepared} if bound else {},
                'outputs':[],'products':{'solution':{'kind':'field_solution','status':'complete',
                'metadata':meta,'data':{'prepared_manifest':prepared}}}}
            publish_terminal_state(solution_root,{'status':'success'},manifest)
            path=solution_root/'run_manifest.json'
            return SimpleNamespace(metadata=meta,data_records={'prepared_manifest':prepared},manifest_location=path,
                reference={'manifest':file_record(path,'required_evidence'),'product_id':'solution'})
        source=make_source()
        self.assertEqual(_basis_original_owner_refs(source),[prepared])
        bad=copy.deepcopy(source.data_records);bad['prepared_manifest']['sha256']='0'*64
        altered=SimpleNamespace(metadata=meta,data_records=bad,manifest_location=source.manifest_location,reference=source.reference)
        with self.assertRaisesRegex(ValueError,'binding differs'):_basis_original_owner_refs(altered)
        prepared_bytes=(prepared_root/'run_manifest.json').read_bytes()
        (prepared_root/'run_manifest.json').write_text('{}',encoding='utf8')
        with self.assertRaises(AssertionError):_basis_original_owner_refs(source)
        (prepared_root/'run_manifest.json').write_bytes(prepared_bytes)
        with self.assertRaisesRegex(ValueError,'binding differs'):_basis_original_owner_refs(make_source(bound=False))
        self.assertEqual(_basis_original_owner_refs(SimpleNamespace(metadata=meta,data_records={})),[])

    def test_captured_owner_chain_reads_real_records_and_refuses_tamper(self):
        import json
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from msplatform.backends.simion.split_scalar_workbench import _basis_original_owner_refs
        from msplatform.io.manifest_records import file_record
        path=Path(r'C:\Users\Liao\mass_spectrometry\artifacts\batch_b_comsol_split_small_20261127\artifacts\assemblies\instrument_assembly\runs\20261127_023910__analysis__comsol__basis-recovery-e7a42a44d31e\run_manifest.json')
        if not path.is_file(): self.skipTest('local recovered basis absent')
        doc=json.loads(path.read_text(encoding='utf8'));product=doc['products']['background']
        source=SimpleNamespace(metadata=product['metadata'],data_records=product['data'],manifest_location=path,
            reference={'manifest':file_record(path,'required_evidence'),'product_id':'background'})
        owners=_basis_original_owner_refs(source)
        self.assertEqual([Path(value['path']).parent.name for value in owners],
            ['20261127_015508__sim__comsol__pulse-basis-fd136b758ffa',
             '20261127_012811__build__comsol__assembly-model-1339a08c0e14'])
        with patch('msplatform.backends.comsol.assembly_field_export.resolve_model_source_manifests',return_value=(source.reference['manifest'],None)):
            with self.assertRaisesRegex(ValueError,'failed original owner'):_basis_original_owner_refs(source)
        other=SimpleNamespace(metadata={'scope':'single_stationary_workpoint'},data_records={})
        self.assertEqual(_basis_original_owner_refs(other),[])
        bad=copy.deepcopy(product['data']);bad['prepared_manifest']['sha256']='0'*64
        altered=SimpleNamespace(metadata=source.metadata,data_records=bad,manifest_location=path,reference=source.reference)
        with self.assertRaises((AssertionError,ValueError)):_basis_original_owner_refs(altered)

    def test_worker_publishes_borrowed_lineage_with_inert_owner(self):
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        import sys
        from msplatform.backends.simion.split_scalar_workbench import execute_split_scalar_world
        from msplatform.io.manifest_records import file_record
        base = self.helper.root
        binding = self.resolve()
        manifest = base / "inert-manifest.json"
        manifest.write_text("inert", encoding="utf-8")
        reference = {"manifest": file_record(manifest), "product_id": "field"}
        binding["geometry_reference"] = reference
        for name in ("off", "on"):
            binding["bases"][name]["reference"] = reference
            binding["bases"][name]["field_solution_reference"] = reference
        data = base / "inert-data.json"
        data.write_text("inert", encoding="utf-8")
        record = file_record(data)
        source = SimpleNamespace(reference=reference, manifest_location=manifest, metadata={"backend": "simion", "ground_source_reference": reference},
                                 data_records={"compiled_model": record}, data_locations={"compiled_model": data})
        carriers = {}
        for role in ("flight_tube", "reflectron", "accelerator", "detector"):
            path = base / (role + ".pa")
            path.write_bytes(b"inert")
            carriers[role] = file_record(path)
        root = base / "run"
        root.mkdir()
        class InertSession:
            run_dir = root
            artifact_run_dir = root
            input_dir = root / "inputs"
            log_dir = root / "logs"
            context = SimpleNamespace(tools={"simion": Path(sys.executable)})
            expected_operation_ids = ("background_build", "background_verify", "collision_iob_build", "collision_iob_verify")
            @staticmethod
            def canonical_path(path): return Path(path).resolve()
            @staticmethod
            def declare_file(path, role): pass
            @staticmethod
            def add_input(name, record): pass
            @staticmethod
            def add_inputs(rows): list(rows)
            def run_process(self, operation, **kwargs):
                index = self.expected_operation_ids.index(operation) + 1
                self.log_dir.mkdir(parents=True, exist_ok=True)
                marker = {"background_build": "NUMERICAL_CARRIER_REOPEN=PASS",
                          "background_verify": "NUMERICAL_CARRIER_COLD_REOPEN=PASS",
                          "collision_iob_build": "SINGLE_REFLECTION_GEOMETRY_IOB=PASS",
                          "collision_iob_verify": "SPLIT_SCALAR_WORLD_PRIORITY=PASS"}[operation]
                (self.log_dir / f"operation_{index:04d}.stdout.log").write_text(marker, encoding="utf-8")
                if operation == "background_build":
                    (root / "simion/world/background.pa").write_bytes(b"inert")
                if operation == "collision_iob_build":
                    (root / "simion/world/world.iob").write_bytes(b"inert")
                    (root / "simion/world/world.fly2").write_bytes(b"inert")
        with patch("msplatform.backends.simion.split_scalar_workbench._admit_world", return_value=(source,self.model,binding,carriers)), \
             patch("msplatform.results.artifacts.open_artifact", return_value=source), \
             patch("msplatform.backends.simion.model_execution._protected_source"):
            result = execute_split_scalar_world(InertSession(), fields_reference=reference, scalar_field_basis={}, limits={})
        product = result["manifest_extra_fields"]["products"]["fields"]
        self.assertEqual(product["metadata"]["collision_source_reference"], reference)
        self.assertEqual(product["metadata"]["world_slots"]["detector"], 5)
        self.assertEqual(product["metadata"]["field_source"], "comsol_off_on_scalar_samples")
        self.assertEqual(product["metadata"]["refine_calls"], 0)
        self.assertEqual(product["metadata"]["fly_calls"], 0)

    def test_lua_core_rejects_swapped_world_priority_before_native_open(self):
        from pathlib import Path
        import subprocess
        lua = Path("C:/Program Files/SIMION-2020/lua.exe")
        if not lua.is_file():
            self.skipTest("standalone Lua unavailable")
        root = self.helper.root
        control = root / "empty.fly2"
        control.write_text("particles{coordinates=0,}", encoding="ascii")
        from msplatform.backends.simion.resources import native_resource_path
        from msplatform.backends.simion.source import lua_value
        roles = ["flight_tube", "background", "reflectron", "accelerator", "detector"]
        spec = {"schema_version": 1, "role": "split_scalar_world_iob_build",
                "instances": [{"role": role, "instance_index": i, "priority_number": i}
                              for i,role in enumerate(roles,1)],
                "output_iob": str(root / "out.iob"), "seed_iob": str(root / "seed.iob"),
                "empty_particle_control": str(control)}
        harness = root / "reject-world.lua"
        harness.write_text("local spec=" + lua_value(spec) + "\n" +
            "assert(loadfile(" + lua_value(str(native_resource_path("iob_core.lua"))) + "))()(spec,'build_geometry',function(s) return s end)\n", encoding="utf-8")
        result = subprocess.run([str(lua), str(harness)], cwd=root, capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("IOB role/order differs", result.stderr)
