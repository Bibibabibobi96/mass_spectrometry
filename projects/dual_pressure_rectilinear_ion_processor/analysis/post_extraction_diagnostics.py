"""Recorded z=0 crossing ensemble and bounded common-time packet; no propagation."""
from pathlib import Path
import csv
import hashlib
import json
import math
from typing import NamedTuple
from bisect import bisect_left
import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt
import numpy as np

from common.contracts.particle_physics import kinetic_energy_ev
VARS=('x_mm','y_mm','z_mm','vx_mm_us','vy_mm_us','vz_mm_us')
def sha(p):
    with p.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def table(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:
        for raw in csv.DictReader(stream):
            assert None not in raw and all(v is not None for v in raw.values())
            yield raw
def numeric(raw):
    row={k:float(raw[k]) for k in ('t_us',*VARS)}
    assert all(math.isfinite(v) for v in row.values())
    return dict(particle_id=int(raw['particle_id']),**row)
def statistics(values):
    a=np.asarray(values,dtype=float)
    return dict(n=len(a),mean=float(a.mean()),std_population=float(a.std()),min=float(a.min()),max=float(a.max()),median=float(np.median(a)))
def write_csv(path,rows,fields=None):
    with path.open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields or list(rows[0]));writer.writeheader();writer.writerows(rows)

class PacketObservation(NamedTuple):
    """Bounded common-time states, selected instrument time, availability and derivation."""
    states: list[dict]
    time_us: float | None
    status: str
    selection: dict


def common_packet(tracks: dict, crossings: dict, limit: float) -> PacketObservation:
    """Select the latest pre-arrival observation from this run's cadence, not a clock constant."""
    intervals=[]
    for pid,track in tracks.items():
        times=sorted(track)
        if len(times)>1:
            gap=times[-1]-times[-2]
            if 0<gap<=limit:intervals.append(gap)
    if not intervals:return PacketObservation([],None,'No valid recorded sampling intervals',{})
    interval=float(np.median(intervals))
    first=min(r['t_us'] for r in crossings.values())
    lower=max(min(track) if track else math.inf for track in tracks.values())
    if not lower<first:return PacketObservation([],None,'No common recorded interval before the first arrival',{})
    # Half one actual sample interval before first arrival; clamp into shared recorded support.
    tref=max(first-.5*interval,.5*(lower+first))
    packet=[]
    for pid,track in sorted(tracks.items()):
        track=dict(track);track[crossings[pid]['t_us']]=crossings[pid]
        times=sorted(track);index=bisect_left(times,tref)
        if index==0 or index==len(times):return PacketObservation([],tref,f'Missing common-time bracket for ion {pid}',{})
        a,b=track[times[index-1]],track[times[index]]
        gap=b['t_us']-a['t_us']
        if not 0<gap<=limit+1e-12:return PacketObservation([],tref,f'Common-time gap exceeds contract for ion {pid}',{})
        u=(tref-a['t_us'])/gap
        packet.append(dict(particle_id=pid,t_us=tref,**{k:a[k]+u*(b[k]-a[k]) for k in VARS},bracket_start_us=a['t_us'],bracket_end_us=b['t_us'],bracket_gap_us=gap,upper_is_acceptance=b['t_us']==crossings[pid]['t_us']))
    return PacketObservation(packet,tref,'available',dict(algorithm='first_arrival_minus_half_measured_record_interval_v1',first_arrival_us=first,measured_record_interval_us=interval,common_support_start_us=lower,first_arrival_margin_us=first-tref))

@plt.rc_context({"font.family":"DejaVu Sans","font.size":10,"svg.fonttype":"none"})
def export_post_extraction(run: Path, output_directory: Path) -> dict:
    """Export recorded exit-plane and automatic common-time evidence to fresh files.

    Positions are project mm, velocities mm/us and times absolute us. No propagation
    or original-run mutation occurs. Invalid state tables or existing outputs raise.
    A cohort without extraction produces explicit unavailable evidence and headers.
    """
    RUN=Path(run).resolve();OUT=Path(output_directory).resolve()
    OUT.mkdir(parents=True,exist_ok=True)
    names=['post_extraction_packet.png','post_extraction_packet.svg','post_extraction_packet.metadata.json','post_extraction_statistics.json','post_extraction_plane_states.csv','post_extraction_common_time_states.csv']
    if any((OUT/name).exists() for name in names):raise FileExistsError('Fresh diagnostic output required; refusing to replace evidence')
    paths=[RUN/p for p in ('inputs/resolved_model.json','inputs/diagnostics.json','simion/events.csv','simion/samples.csv','results/particle_state.csv')]
    hashes={str(p):sha(p) for p in paths}
    config=json.loads(paths[0].read_text(encoding="utf-8-sig"));contract=json.loads(paths[1].read_text(encoding="utf-8-sig"))
    mass=config['source']['species']['mass_amu'];crossings={};terminal={};sources=set()
    for raw in table(RUN/'simion/events.csv'):
        pid=int(raw['particle_id'])
        if raw['event']=='source':sources.add(pid)
        if raw['event']=='terminal':terminal[pid]=(raw['reason'],numeric(raw))
        if raw['event']=='extraction_exit':
            assert pid not in crossings
            crossings[pid]=numeric(raw)
    ids=sorted(crossings);assert set(terminal)==sources and set(ids)<=sources
    omitted=sorted(sources-set(ids))
    count=len(ids);source_count=len(sources)
    if not ids:
        fig,ax=plt.subplots(figsize=(12,6));ax.axis('off')
        ax.text(.05,.75,f'Post-extraction diagnostics unavailable\nSource ions: {source_count}\nNo recorded extraction_exit events in this run.\nNo old figure or downstream extrapolation is used.',fontsize=17,va='top')
        outputs=[]
        for ext in ('png','svg'):
            path=OUT/f'post_extraction_packet.{ext}';fig.savefig(path,dpi=210);outputs.append(dict(path=str(path),sha256=sha(path)))
        plt.close(fig)
        status=dict(status='no_extracted_ions',packet_status='no_extracted_ions',source_count=source_count,extracted_count=0,source_run=str(RUN))
        (OUT/'post_extraction_statistics.json').write_text(json.dumps(status,indent=2)+'\n', encoding="utf-8")
        write_csv(OUT/'post_extraction_plane_states.csv',[],['particle_id','t_us',*VARS,'Ex_eV','Ey_eV','Ez_eV','Etotal_eV'])
        write_csv(OUT/'post_extraction_common_time_states.csv',[],['particle_id','t_us',*VARS,'bracket_start_us','bracket_end_us','bracket_gap_us','upper_is_acceptance'])
        metadata=dict(role='post_extraction_recorded_state_diagnostics',source_run=str(RUN),source_records=[dict(path=str(p),sha256=hashes[str(p)]) for p in paths],outputs=outputs,producer=dict(path=str(Path(__file__)),sha256=sha(Path(__file__))),cohort=status,new_simulation=False,qualification='diagnostic_only')
        (OUT/'post_extraction_packet.metadata.json').write_text(json.dumps(metadata,indent=2)+'\n', encoding="utf-8")
        assert all(sha(p)==hashes[str(p)] for p in paths)
        print('No extracted ions: explicit diagnostic figure generated.');return status
    for pid,row in crossings.items():
        reason,end=terminal[pid];assert reason=='acceptance_surface'
        assert row==end and abs(row['z_mm'])<1e-10 and row['vz_mm_us']<0
    pulse=config['native_timing']['pulse_start_us']
    tracks={pid:{} for pid in ids};sample_rows=0
    for raw in table(RUN/'simion/samples.csv'):
        sample_rows+=1;pid=int(raw['particle_id']);t=float(raw['t_us'])
        if pid in tracks and pulse<=t<=crossings[pid]['t_us']:
            row=numeric(raw);tracks[pid][t]=row
    packet,tref,packet_status,selection=common_packet(tracks,crossings,contract['max_extraction_bracket_us'])
    exit_rows=[]
    for pid in ids:
        row=dict(crossings[pid])
        components=[]
        for index,axis in enumerate('xyz'):
            v=[0.,0.,0.];v[index]=row['v'+axis+'_mm_us']*1000
            energy=kinetic_energy_ev(mass,*v);components.append(energy);row['E'+axis+'_eV']=energy
        total=kinetic_energy_ev(mass,*(row['v'+axis+'_mm_us']*1000 for axis in 'xyz'))
        assert abs(sum(components)-total)<1e-9
        row['Etotal_eV']=total;exit_rows.append(row)
    center=config['baseline']['geometry']['lp_center_mm']
    stats=dict(plane_z_mm=0,packet_time_us=tref,source_count=source_count,extracted_count=count,not_extracted_ids=omitted,packet_status=packet_status,time_selection=selection,
               observed_crossing={k:statistics([r[k] for r in exit_rows]) for k in ('t_us',*VARS,'Ex_eV','Ey_eV','Ez_eV','Etotal_eV')},
               common_time_packet={k:statistics([r[k] for r in packet]) for k in VARS} if packet else {},
               interpolation=dict(maximum_gap_us=max((r['bracket_gap_us'] for r in packet),default=None),acceptance_event_upper_brackets=sum(r['upper_is_acceptance'] for r in packet)),
               sample_csv_rows_read=sample_rows,energy_definition='Ei = 0.5 * mass * vi^2; axis energies are nonnegative and retain any bulk drift. Acceleration is -z.',
               scope='Extracted ions conditional on this run source. Common time is automatically selected before the first z=0 arrival. No packet is propagated past termination.')
    for name,rows in [('post_extraction_plane_states.csv',exit_rows),('post_extraction_common_time_states.csv',packet)]:
        path=OUT/name
        if path.exists():raise FileExistsError(path)
        fields=['particle_id','t_us',*VARS,'bracket_start_us','bracket_end_us','bracket_gap_us','upper_is_acceptance'] if not rows else None
        write_csv(path,rows,fields)
    (OUT/'post_extraction_statistics.json').write_text(json.dumps(stats,indent=2)+'\n', encoding="utf-8")
    fig=plt.figure(figsize=(18,14.5))
    grid=fig.add_gridspec(3,3,left=.065,right=.965,top=.89,bottom=.12,hspace=.5,wspace=.32)
    x=np.array([r['x_mm'] for r in packet]);y=np.array([r['y_mm']-center for r in packet]);z=np.array([r['z_mm'] for r in packet])
    ex=np.array([r['x_mm'] for r in exit_rows]);ey=np.array([r['y_mm']-center for r in exit_rows]);t=np.array([r['t_us'] for r in exit_rows]);dt=(t-t.mean())*1000
    if packet:
        ax=fig.add_subplot(grid[0,0],projection='3d')
        ax.scatter(x,y,z,c=z,cmap='viridis',s=18,depthshade=False)
        ax.set(xlabel='x / mm',ylabel=f'y - {center:g} / mm',zlabel='z / mm')
        ax.set_title(f'(a) Simultaneous packet (automatic time)\nt = {tref:.6f} us',fontsize=12)
        ax.set_box_aspect((max(np.ptp(x),.01),max(np.ptp(y),.01),max(np.ptp(z),.01)))
        ax=fig.add_subplot(grid[0,1]);sc=ax.scatter(y,z,c=x,cmap='coolwarm',s=23,edgecolors='none')
        ax.set(xlabel=f'y - {center:g} / mm',ylabel='z / mm',title='(b) Packet side view at the same time')
        fig.colorbar(sc,ax=ax,label='x / mm',fraction=.045,pad=.03)
        ax.text(.03,.03,f'sigma(z) = {z.std():.4f} mm\nsigma(y) = {y.std():.4f} mm',transform=ax.transAxes,fontsize=9)
    else:
        for col in (0,1):
            ax=fig.add_subplot(grid[0,col]);ax.axis('off');ax.text(.05,.8,'Common-time packet unavailable:\n'+packet_status,wrap=True)
    ax=fig.add_subplot(grid[0,2]);sc=ax.scatter(ey,ex,c=dt,cmap='viridis',s=26,edgecolors='none')
    ax.set(xlabel=f'y - {center:g} / mm',ylabel='x / mm',title='(c) Exit footprint at z = 0 mm')
    fig.colorbar(sc,ax=ax,label='Arrival - mean / ns',fraction=.045,pad=.03)
    ax.text(.03,.03,'Different arrival times; not a simultaneous cloud',transform=ax.transAxes,fontsize=8)
    for col,axis in enumerate('xyz'):
        ax=fig.add_subplot(grid[1,col]);values=np.array([r['E'+axis+'_eV'] for r in exit_rows])
        scale=1000 if axis=='z' else 1;unit='keV' if scale==1000 else 'eV'
        ax.hist(values/scale,bins=14,histtype='step',linewidth=1.5,color='#0069A8')
        ax.set(xlabel=f'E{axis} / {unit}',ylabel='Ion count',title=f'({chr(100+col)}) {axis}-direction kinetic energy at z = 0')
        ax.text(.97,.96,f'mean = {values.mean()/scale:.5g} {unit}\nsigma = {values.std()/scale:.4g} {unit}',transform=ax.transAxes,ha='right',va='top',fontsize=10)
    ax=fig.add_subplot(grid[2,0]);total=np.array([r['Etotal_eV'] for r in exit_rows])
    ax.hist(total/1000,bins=14,histtype='step',linewidth=1.5,color='#0069A8')
    ax.set(xlabel='Total kinetic energy / keV',ylabel='Ion count',title='(g) Total energy: Ex + Ey + Ez')
    ax.text(.97,.96,f'mean = {total.mean()/1000:.6f} keV\nsigma = {total.std():.3f} eV',transform=ax.transAxes,ha='right',va='top')
    ax=fig.add_subplot(grid[2,1]);ax.hist(dt,bins=14,histtype='step',linewidth=1.5,color='#0069A8')
    ax.set(xlabel='Arrival time - mean / ns',ylabel='Ion count',title='(h) Arrival-time distribution at z = 0')
    ax.text(.97,.96,f'sigma = {dt.std():.3f} ns\nrange = {np.ptp(dt):.3f} ns',transform=ax.transAxes,ha='right',va='top')
    ax=fig.add_subplot(grid[2,2]);ax.axis('off')
    packet_text=(f'Automatic common time: {tref:.6f} us\n  z range: {z.min():.4f} to {z.max():.4f} mm\n  sigma(x): {x.std():.4f} mm\n  sigma(y): {y.std():.4f} mm\n  sigma(z): {z.std():.4f} mm' if packet else 'Common-time packet: unavailable')
    text=(f'(i) Cohort and measurement definition\n\nSource: {source_count} ions | Extracted: {count}\nNot extracted: '+(', '.join(map(str,omitted)) or 'none')+f'\n\n{packet_text}\n\nExit surface: z = 0 mm, vz < 0\n  sigma(x): {ex.std():.4f} mm\n  sigma(y): {ey.std():.4f} mm\n\nEi = (1/2) m vi^2 (includes mean drift)\nNo downstream extrapolation.')
    ax.text(0,1,text,ha='left',va='top',fontsize=10.5,linespacing=1.35)
    fig.suptitle('Post-extraction ion packet | Spatial shape and directional energy',fontsize=20)
    fig.text(.065,.93,f'{count} extracted ions from {source_count} source ions. Exit surface: z=0 mm; acceleration direction: -z.',fontsize=12)
    fig.text(.065,.055,f'(a-b) Automatic time: first arrival minus half this run\'s measured record interval; bounded interpolation only, capped by acceptance events.\n(c-h) Crossing ensemble: each ion at its own z=0 arrival time, using recorded runtime crossing interpolation. Axes have independent scales.\nHistograms show all {count} extracted ions, without fitting or smoothing. A common-time packet beyond the terminal plane is not recorded.',fontsize=10,color='#444')
    assert all(not any('\u4e00'<=c<='\u9fff' for c in text.get_text()) for text in fig.findobj(matplotlib.text.Text))
    outputs=[]
    for ext in ('png','svg'):
        path=OUT/f'post_extraction_packet.{ext}'
        if path.exists():raise FileExistsError(path)
        fig.savefig(path,dpi=210,facecolor='white');outputs.append(dict(path=str(path),sha256=sha(path)))
    plt.close(fig)
    for path in paths:assert sha(path)==hashes[str(path)]
    metadata=dict(role='post_extraction_recorded_state_diagnostics',source_run=str(RUN),source_records=[dict(path=str(p),sha256=hashes[str(p)]) for p in paths],outputs=outputs,producer=dict(path=str(Path(__file__)),sha256=sha(Path(__file__))),cohort=stats,new_simulation=False,qualification='diagnostic_only',crossing_scope='Runtime recorded crossing interpolation at z=0; not every integration-step bracket is retained in samples.csv',common_time_scope='Automatic common time from this run first arrival and recorded cadence; no post-terminal samples used')
    (OUT/'post_extraction_packet.metadata.json').write_text(json.dumps(metadata,indent=2)+'\n', encoding="utf-8")
    print(json.dumps(stats),flush=True)
    return stats
