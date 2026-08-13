"""Create a derived RR checkpoint table with canonical detector clock."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import pandas as pd
from common.contracts.file_identity import file_sha256

def main() -> None:
    p=argparse.ArgumentParser(); p.add_argument('--checkpoints',type=Path,required=True); p.add_argument('--source',type=Path,required=True); p.add_argument('--manifest',type=Path,required=True); p.add_argument('--output',type=Path,required=True); a=p.parse_args()
    cp=pd.read_csv(a.checkpoints); src=pd.read_csv(a.source).set_index('particle_id').birth_time_s.astype(float)
    detector=cp.event.eq('detector_crossing'); ids=cp.loc[detector,'particle_id'].astype(int)
    if len(ids)!=1000 or set(ids)!=set(range(1,1001)) or set(src.index.astype(int))!=set(range(1,1001)): raise ValueError('canonical clock authority requires the same 1000 IDs')
    cp['checkpoint_provenance']=cp['checkpoint_provenance'].astype(object)
    cp.loc[detector,'instrument_time_us']=cp.loc[detector,'instrument_time_us'].astype(float).to_numpy()+src.loc[ids].to_numpy()*1e6
    cp.loc[detector,'checkpoint_provenance']='derived_canonical_instrument_time_us=source_birth_time_s*1e6+solver_local_elapsed_us'
    a.output.mkdir(parents=True,exist_ok=False); out=a.output/'rr_canonical_checkpoints.csv'; cp.to_csv(out,index=False)
    receipt={'schema_version':1,'role':'manifest_bound_rr_canonical_detector_clock_reanalysis','status':'success','source_run_manifest_sha256':file_sha256(a.manifest),'source_checkpoint_sha256':file_sha256(a.checkpoints),'source_particle_sha256':file_sha256(a.source),'derived_checkpoint_sha256':file_sha256(out),'particle_count':1000,'detector_clock_formula':'source_birth_time_s*1e6 + solver_local_elapsed_us','old_source_files_modified':False}
    (a.output/'rr_canonical_clock_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print('RR_CANONICAL_CLOCK_REANALYSIS=PASS PARTICLES=1000')
if __name__=='__main__': main()
