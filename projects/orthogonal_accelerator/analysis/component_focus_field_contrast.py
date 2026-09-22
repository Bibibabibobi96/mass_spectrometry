"""Reduce native and runtime-idealized OA field arms into one diagnostic."""
from __future__ import annotations
import argparse, json, math
from pathlib import Path

class FieldContrastError(ValueError): pass

def load(path: Path) -> float:
    try: value=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,json.JSONDecodeError) as exc: raise FieldContrastError('analysis is unreadable') from exc
    try: p=float(value['focus_metrics']['peak_to_peak_t_ns'])
    except (KeyError,TypeError,ValueError) as exc: raise FieldContrastError('analysis lacks peak-to-peak time') from exc
    if not math.isfinite(p): raise FieldContrastError('peak-to-peak time is invalid')
    return p

def reduce(native: Path, zone1: Path, zone2: Path, full: Path) -> dict:
    arms={'native':load(native),'zone1_ideal':load(zone1),'zone2_ideal':load(zone2),'full_ideal':load(full)}
    reductions={name:arms['native']-value for name,value in arms.items() if name!='native'}
    z1,z2=reductions['zone1_ideal'],reductions['zone2_ideal']
    dominant='zone2_finite_field' if z2>z1+0.05 else 'zone1_finite_field' if z1>z2+0.05 else 'distributed_or_indeterminate'
    recommendation={'zone2_finite_field':'increase_zone2_ring_count_before_expanding_y_or_mesh','zone1_finite_field':'inspect_grid1_repeller_transition_before_changing_zone2_ring_count','distributed_or_indeterminate':'inspect_both_zone_boundaries_before_geometry_change'}[dominant]
    return {'schema_version':1,'role':'orthogonal_accelerator_two_zone_ideal_field_contrast','status':'diagnostic','same_pa_release_voltage_and_numerics':True,'peak_to_peak_t_ns':arms,'native_reduction_toward_ideal_ns':reductions,'dominant_finite_field_region':dominant,'recommended_next_geometry_action':recommendation}
def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--native',required=True,type=Path);p.add_argument('--zone1-ideal',required=True,type=Path);p.add_argument('--zone2-ideal',required=True,type=Path);p.add_argument('--full-ideal',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
 try: result=reduce(a.native,a.zone1_ideal,a.zone2_ideal,a.full_ideal)
 except (OSError,ValueError) as e: print(f'ACCELERATOR_COMPONENT_FIELD_CONTRAST=FAIL ERROR={e}');return 1
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(f"ACCELERATOR_COMPONENT_FIELD_CONTRAST=PASS DOMINANT={result['dominant_finite_field_region']}");return 0
if __name__=='__main__': raise SystemExit(main())
