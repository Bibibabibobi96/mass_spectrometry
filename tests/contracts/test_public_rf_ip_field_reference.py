"""Original RF-IP field-family admission with inert records, no native solver."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from msplatform.backends.simion.rf_field_execution import _domain_labels, plan_rf_fields, require_rf_reuse, rf_spatial_identity
from msplatform.io.manifest_records import file_record
from msplatform.recipes import load_recipe
from msplatform.workflows.native_tracing import compile_simion_model
from tests.contracts.test_support.rf_ip_native_recipe import write_rf_ip_recipe_fixture


def original_field_fixture(root: Path):
    """Construct explicit owner-bound family and software-only process receipts."""
    author=write_rf_ip_recipe_fixture(root/'author');recipe=load_recipe(author).to_dict()
    model=compile_simion_model(recipe);document=model.document;geometry=document['geometry']['frontend_geometry']
    numerics=recipe['study']['document']['numerics']['fields']
    plan_rf_fields(model,numerics=numerics)
    family=root/'family';family.mkdir();records={}
    def put(key,name,payload):
        path=family/name;path.write_bytes(payload if isinstance(payload,bytes) else json.dumps(payload).encode())
        records[key]=file_record(path,'required_evidence')
    put('compiled_model','compiled_model.json',document);put('field_numerics','field_numerics.json',numerics)
    for name in ('instrument_clock_authority_v1.json','instrument_epoch_v1.json'):
        put('clock_authority' if name.startswith('instrument_clock') else 'instrument_epoch',name,
            (Path(__file__).resolve().parents[2]/'src/msplatform/examples'/name).read_bytes())
    names=[]
    for suffix in ['.pa#','.pa0','.pa-surf',*('.pa'+str(i) for i in _domain_labels(geometry,'parent'))]:
        name='rf_ip'+suffix;put(name,name,b'INERT_NOT_SIMION_PA');names.append(name)
    put('witness','witness.csv',b'INERT_NOT_SIMION_WITNESS')
    source=SimpleNamespace(model=model,native_assets={'parent':dict(raw_record=records['rf_ip.pa#'],
                                                                  surface_records=[records['rf_ip.pa-surf']])})
    identity=rf_spatial_identity(source,numerics=numerics,
        tool_identity=dict(bytes=5,sha256='A'*64),auditor_identity=dict(bytes=5,sha256='B'*64))
    put('spatial_identity','spatial_identity.json',identity)
    put('field_native_receipts','field_native_receipts.json',[dict(operation_id='refine_parent',
        observation=dict(exit_confirmed=True,returncode=0,process_id=1,process_started_at_utc_ticks=1))])
    put('field_audit','field_audit.json',dict(role='simion_rf_fractional_field_audit',status='success',
                                             checked_domains=['parent'],fixture='INERT_ONLY'))
    meta=dict(backend='simion',field_status='available',source_status='not_requested',
        field_representation='producer_owned_rf_ip_fractional_family',spatial_identity=identity,
        model_identity_sha256=document['model_identity_sha256'],clock=document['drive']['clock'],
        native_assets={'parent':dict(carrier='rf_ip.pa0',family=names,surface_witnesses='witness')},
        qualification='inert_test_not_native')
    manifest=family/'run_manifest.json';manifest.write_text(json.dumps(dict(schema_version=2,role='simulation_run_manifest',
        status='success',inputs={},outputs=list(records.values()),products={'fields':dict(schema_version=1,
            kind='field_bundle',status='complete',metadata=meta,data=records)})),encoding='utf8')
    return dict(manifest=file_record(manifest,'required_evidence'),product_id='fields'), identity, geometry, model, numerics


class PublicRfIpFieldReferenceTests(unittest.TestCase):
    def test_original_family_and_missing_or_changed_members(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);reference,identity,geometry,model,numerics=original_field_fixture(root)
            from msplatform.workflows.simion_field_reference import admit_simion_field_reference
            recipe=load_recipe(root/'author/author.toml').to_dict()
            clock=json.loads((Path(__file__).resolve().parents[2]/'src/msplatform/examples/instrument_clock_authority_v1.json').read_text(encoding='utf8'))
            admitted=admit_simion_field_reference(recipe['study']['document'],reference=reference,
                clock_authority=clock,expected_model=model,field_numerics=numerics)
            self.assertEqual(admitted.reference['manifest']['sha256'],reference['manifest']['sha256'])
            _,_,assets=require_rf_reuse(reference,identity=identity,geometry=geometry)
            self.assertEqual(set(assets),{'parent'})
            wrong=copy.deepcopy(identity);wrong['numerics']={'refine_policy':'vendor_default'}
            with self.assertRaisesRegex(ValueError,'spatial operator'):
                require_rf_reuse(reference,identity=wrong,geometry=geometry)
            manifest=Path(reference['manifest']['path']);document=json.loads(manifest.read_text(encoding='utf8'))
            document['products']['fields']['metadata']['native_assets']['parent']['family'].pop()
            missing=manifest.with_name('missing_manifest.json');missing.write_text(json.dumps(document),encoding='utf8')
            with self.assertRaisesRegex(ValueError,'fractional closure'):
                require_rf_reuse(dict(manifest=file_record(missing,'required_evidence'),product_id='fields'),identity=identity,geometry=geometry)
            Path(assets['parent']['family_records'][0]['path']).write_bytes(b'tampered')
            with self.assertRaises((ValueError,AssertionError)):
                require_rf_reuse(reference,identity=identity,geometry=geometry)

    def test_original_refine_receipt_must_report_real_success(self):
        with tempfile.TemporaryDirectory() as directory:
            reference,identity,geometry,_,_=original_field_fixture(Path(directory))
            manifest=Path(reference['manifest']['path']);document=json.loads(manifest.read_text(encoding='utf8'))
            product=document['products']['fields'];old=product['data']['field_native_receipts']
            receipt=Path(old['path']);receipt.write_text(json.dumps([dict(operation_id='refine_parent',
                observation=dict(exit_confirmed=True,returncode=1,process_id=1,process_started_at_utc_ticks=1))]),encoding='utf8')
            changed=file_record(receipt,'required_evidence');product['data']['field_native_receipts']=changed
            document['outputs']=[changed if record==old else record for record in document['outputs']]
            manifest.write_text(json.dumps(document),encoding='utf8')
            with self.assertRaisesRegex(ValueError,'successful actual Refine'):
                require_rf_reuse(dict(manifest=file_record(manifest,'required_evidence'),product_id='fields'),identity=identity,geometry=geometry)

    def test_strict_admission_rejects_forged_clock_spatial_and_borrowed(self):
        from msplatform.workflows.simion_field_reference import admit_simion_field_reference
        from msplatform.io.file_identity import canonical_json_sha256
        for mutation in ('clock','spatial_hash','domains','bindings','borrowed','numerics'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);reference,_,_,model,numerics=original_field_fixture(root)
                recipe=load_recipe(root/'author/author.toml').to_dict()
                clock=json.loads((Path(__file__).resolve().parents[2]/'src/msplatform/examples/instrument_clock_authority_v1.json').read_text(encoding='utf8'))
                manifest=Path(reference['manifest']['path']);document=json.loads(manifest.read_text(encoding='utf8'))
                metadata=document['products']['fields']['metadata'];spatial=metadata['spatial_identity']
                if mutation=='clock':metadata['clock']['phase_reference_instrument_time_us']+=1
                elif mutation=='spatial_hash':spatial['identity_sha256']='0'*64
                elif mutation in ('domains','bindings'):
                    spatial['numerical_domains' if mutation=='domains' else 'electrode_bindings']={}
                    spatial['identity_sha256']=canonical_json_sha256({k:v for k,v in spatial.items() if k!='identity_sha256'})
                elif mutation=='borrowed':metadata['family_producer_reference']=reference
                else:
                    spatial['numerics']={'refine_policy':'vendor_default'}
                    spatial['identity_sha256']=canonical_json_sha256({k:v for k,v in spatial.items() if k!='identity_sha256'})
                manifest.write_text(json.dumps(document),encoding='utf8')
                bad=dict(manifest=file_record(manifest,'required_evidence'),product_id='fields')
                with self.assertRaises(ValueError):
                    admit_simion_field_reference(recipe['study']['document'],reference=bad,
                        clock_authority=clock,expected_model=model,field_numerics=numerics)
