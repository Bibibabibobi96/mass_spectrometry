"""Default English electrode sections and bounded recorded-state clouds."""
from pathlib import Path
import csv
import hashlib
import json
import math
import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt
from matplotlib.patches import Rectangle, Circle
from matplotlib.lines import Line2D
NAMES = {1: 'Octupole RF A', 2: 'Octupole RF B', 3: 'HP vertical RF', 4: 'HP transverse RF', 5: 'LP pull', 6: 'LP push', 7: 'LP upper side', 8: 'LP lower side', 9: 'HP corner auxiliary', 10: 'LP outer auxiliary', 11: 'LP inner auxiliary', 12: 'Entrance lens', 13: 'Exit lens', 14: 'LP shield', 15: 'HP shield'}
STATE = {'alive': ('#0069A8', 'o', 'Alive'), 'extracted': ('#00845A', 's', 'Extracted (last position)'), 'lost': ('#B42532', 'x', 'Lost / timeout (last position)')}

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def world_bounds(shape, origin_z_mm: float):
    a, b = (shape['min_mm'], shape['max_mm'])
    return ([-b[2], a[0], origin_z_mm - b[1]], [-a[2], b[0], origin_z_mm - a[1]])

def section(shape, view, value, origin_z_mm: float):
    """Exact plane intersection; rectangles or circle, in project coordinates."""
    h, v, f = {'long': (1, 2, 0), 'top': (1, 0, 2), 'cross': (0, 2, 1)}[view]
    if shape['shape'] == 'box':
        a, b = world_bounds(shape, origin_z_mm)
        if not a[f] <= value <= b[f]:
            return None
        return ('rect', (a[h], a[v], b[h], b[v]))
    assert shape['shape'] == 'cylinder_x'
    cx, cz = (-shape['center_z_mm'], origin_z_mm - shape['center_y_mm'])
    r = shape['radius_mm']
    if view == 'cross':
        if shape['x_min_mm'] <= value <= shape['x_max_mm']:
            return ('circle', (cx, cz, r))
        return None
    delta = value - (cz if view == 'top' else cx)
    if abs(delta) >= r:
        return None
    half = math.sqrt(r * r - delta * delta)
    center = cx if view == 'top' else cz
    return ('rect', (shape['x_min_mm'], center - half, shape['x_max_mm'], center + half))

def subtract(rect, cut):
    a, b, c, d = rect
    e, f, g, h = cut
    x0, y0, x1, y1 = (max(a, e), max(b, f), min(c, g), min(d, h))
    if x0 >= x1 or y0 >= y1:
        return [rect]
    return [r for r in [(a, b, x0, d), (x1, b, c, d), (x0, b, x1, y0), (x0, y1, x1, d)] if r[2] > r[0] and r[3] > r[1]]

def parts(electrode, view, value, origin_z_mm: float):
    cuts = [section(s, view, value, origin_z_mm) for s in electrode['cutouts']]
    result = []
    for solid in electrode['solids']:
        item = section(solid, view, value, origin_z_mm)
        if item is None:
            continue
        if item[0] == 'circle':
            assert not any(cuts)
            result.append(item)
            continue
        rects = [item[1]]
        for cut in cuts:
            if cut is None:
                continue
            assert cut[0] == 'rect', 'Circular transverse aperture requires explicit polygon Boolean support'
            rects = [p for r in rects for p in subtract(r, cut[1])]
        result.extend((('rect', r) for r in rects))
    return result

class SectionDiagnostics:
    """One run-local rendering context; exports never share mutable model or particle state."""

    def draw_geometry(self, ax, view='long', value=0, numbered=False):
        for electrode in self.ELECTRODES:
            eid = electrode['electrode_id']
            for kind, p in parts(electrode, view, value, self.origin_z_mm):
                style = dict(facecolor='#C99736' if eid == 9 else '#D9DDE1', edgecolor='#84601C' if eid == 9 else '#666E75', linewidth=0.65, zorder=1)
                if kind == 'rect':
                    ax.add_patch(Rectangle((p[0], p[1]), p[2] - p[0], p[3] - p[1], **style))
                else:
                    ax.add_patch(Circle(p[:2], p[2], **style))
        if view == 'long' and value == 0:
            self.draw_e9_projection(ax)
        ax.spines[['top', 'right']].set_visible(False)
        ax.set_xlabel('y / mm (slow drift)' if view in {'long', 'top'} else 'x / mm (transverse)')
        ax.set_ylabel('x / mm' if view == 'top' else 'z / mm')

    def draw_e9_projection(self, ax):
        e9 = next((e for e in self.ELECTRODES if e['electrode_id'] == 9))
        footprints = set()
        for solid in e9['solids']:
            a, b = world_bounds(solid, self.origin_z_mm)
            footprints.add((a[1], a[2], b[1], b[2]))
        for a, b, c, d in sorted(footprints):
            ax.add_patch(Rectangle((a, b), c - a, d - b, facecolor='#C99736', edgecolor='#84601C', linewidth=0.35, alpha=0.8, zorder=2))

    def callout(self, ax, eid, target, text, detail=''):
        ax.annotate(f'E{eid}  {NAMES[eid]}{detail}', xy=target, xytext=text, fontsize=8.5, ha='left', va='center', bbox=dict(facecolor='white', edgecolor='none', pad=1), arrowprops=dict(arrowstyle='-', color='#333333', lw=0.7, connectionstyle='angle3'), zorder=10)

    def region_labels(self, ax):
        for left, right, label in [(0, 30, 'Octupole'), (30, 130, 'HP capture / cooling'), (130, 210, 'LP bunching / extraction')]:
            ax.text((left + right) / 2, 14.45, label, ha='center', va='bottom', fontsize=8, color='#42484E')
        ax.set(xlim=(-5, 215), ylim=(-0.5, 15.6))

    def plot_states(self, ax, rows, local=False):
        for state, (color, marker, label) in STATE.items():
            selected = [r for r in rows if r['status'] == state and r['y_mm'] and r['z_mm']]
            if not selected:
                continue
            kw = dict(color=color, marker=marker, s=16 if local else 11, zorder=5, alpha=0.8)
            if state == 'extracted':
                kw = dict(edgecolors=color, facecolors='none', marker=marker, s=23 if local else 16, zorder=5, linewidths=0.8)
            ax.scatter([float(r['y_mm']) for r in selected], [float(r['z_mm']) for r in selected], **kw)

    def state_legend(self, fig):
        handles = [Line2D([], [], color=color, marker=marker, linestyle='none', label=label, markerfacecolor='none' if state == 'extracted' else color) for state, (color, marker, label) in STATE.items()]
        fig.legend(handles=handles, loc='lower center', bbox_to_anchor=(0.5, 0.005), ncol=3, frameon=False)

    def save(self, fig, name, extra):
        assert all((not any(('一' <= c <= '鿿' for c in text.get_text())) for text in fig.findobj(matplotlib.text.Text))), 'Non-English figure text'
        outputs = []
        for ext in ('png', 'svg'):
            path = self.OUT / f'{name}.{ext}'
            if path.exists():
                raise FileExistsError(path)
            fig.savefig(path, dpi=210, facecolor='white')
            outputs.append(dict(path=str(path), sha256=sha(path)))
        paths = [self.RUN / p for p in ('inputs/resolved_model.json', 'inputs/diagnostics.json', 'simion/events.csv', 'simion/samples.csv', 'results/particle_state.csv')]
        metadata = dict(role='read_only_section_diagnostic', source_run=str(self.RUN), source_particle_count=len({r['particle_id'] for r in self.SNAPSHOTS}), sources=[dict(path=str(p), sha256=sha(p)) for p in paths], recorded_state_table=dict(path=str(self.SNAPSHOT_PATH), sha256=sha(self.SNAPSHOT_PATH)), producer=dict(path=str(Path(__file__)), sha256=sha(Path(__file__))), outputs=outputs, geometry='Frozen CSG plane intersections, with electrode-specific cutouts subtracted; not a PA-grid image. Solid gray section; amber E9 isolated footprints are projected, not a central section.', particle_display='All source IDs retained in the snapshot table; all transverse x positions projected onto y-z. Gray geometry slice is x=0 mm; amber E9 is its explicit longitudinal projection; particles need not lie on this slice. This overlay cannot establish electrode impact.', coordinate_frame=self.C['coordinate_transform']['to_frame_id'], new_simulation=False, **extra)
        (self.OUT / f'{name}.metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        plt.close(fig)

    def atlas(self):
        fig = plt.figure(figsize=(19, 13))
        grid = fig.add_gridspec(3, 3, height_ratios=[0.8, 0.8, 1.4], left=0.08, right=0.98, top=0.92, bottom=0.08, hspace=0.55, wspace=0.28)
        ax = fig.add_subplot(grid[0, :])
        self.draw_geometry(ax)
        ax.set(xlim=(-5, 215), ylim=(5.5, 15.5))
        ax.set_title('Center section x = 0 mm + amber E9 projection (the corners are off-plane)', loc='left', fontsize=12)
        for eid, xy, txt in [(1, (15, 12.4), (1, 15)), (12, (29.75, 11.8), (26, 15)), (3, (75, 12.05), (64, 15)), (15, (110, 13.05), (103, 15)), (6, (155, 12.05), (143, 15)), (14, (194, 13.05), (179, 15)), (13, (210.25, 12.5), (199, 10.2))]:
            self.callout(ax, eid, xy, txt)
        ax = fig.add_subplot(grid[1, :])
        self.draw_geometry(ax, 'top', self.origin_z_mm)
        axial_end = self.G['guide_length_mm'] + self.G['hp_length_mm'] + self.G['lp_length_mm']
        ax.set(xlim=(-5, axial_end + 5), ylim=(-4, 5))
        ax.set_title(f'Equatorial longitudinal section | z = {self.origin_z_mm:g} mm: outer and inner auxiliary lengths', loc='left', fontsize=12)
        center = self.G['lp_center_mm']
        extents = []
        for index, eid in enumerate((5, 6, 7, 8, 10, 11, 14)):
            electrode = next(e for e in self.ELECTRODES if e['electrode_id'] == eid)
            bounds = [world_bounds(s, self.origin_z_mm) for s in electrode['solids']]
            start, stop = min(a[1] for a, b in bounds), max(b[1] for a, b in bounds)
            extents.append(dict(electrode_id=eid, name=electrode['name'], y_start_mm=start, y_end_mm=stop, length_y_mm=stop-start))
        for eid, target, text in [(10, (center-15, 2.2), (center-32, 4.2)), (11, (center, 1.5), (center+6, .5))]:
            extent=next(e for e in extents if e['electrode_id']==eid)
            detail=f"\ny = {extent['y_start_mm']:g}-{extent['y_end_mm']:g} mm; L = {extent['length_y_mm']:g} mm"
            self.callout(ax,eid,target,text,detail)
        ax.text(self.G['guide_length_mm']+10,0,'E7/E8 are off this equatorial plane; see the LP cross-section.',fontsize=9,color='#555555')
        for col, y, title in [(0, self.G['guide_length_mm']/2, 'Octupole cross-section'), (1, self.G['guide_length_mm'] + self.G['hp_length_mm'] / 2, 'HP cross-section'), (2, self.G['lp_center_mm'], 'LP extraction cross-section')]:
            ax = fig.add_subplot(grid[2, col])
            self.draw_geometry(ax, 'cross', y)
            ax.set(xlim=(-7, 7), ylim=(4.6, 15.1))
            ax.set_aspect('equal')
            ax.set_title(f'{title} | y = {y:g} mm', fontsize=11)
            if col == 0:
                self.callout(ax,1,(0,12.4),(-6.6,14))
                self.callout(ax,2,(1.84,11.64),(1.6,13.4))
            elif col == 1:
                for eid, xy, txt in [(3, (0, 12.05), (-6.6, 14.3)), (4, (2.25, 9.8), (2.7, 11.3)), (15, (3.25, 8.5), (2.7, 6.2))]:
                    self.callout(ax, eid, xy, txt)
                e9 = next((e for e in self.ELECTRODES if e['electrode_id'] == 9))
                quadrants = {}
                for kind, p in parts(e9, 'cross', y, self.origin_z_mm):
                    assert kind == 'rect'
                    x, z = ((p[0] + p[2]) / 2, (p[1] + p[3]) / 2)
                    quadrants[x > 0, z > 9.8] = (x, z)
                assert len(quadrants) == 4
                for x, z in quadrants.values():
                    ax.annotate('E9', xy=(x, z), xytext=(x + (-0.9 if x < 0 else 0.6), z + (0.7 if z > 9.8 else -0.7)), fontsize=9, color='#84601C', arrowprops=dict(arrowstyle='-', color='#84601C', lw=0.7))
                ax.text(-6.6, 5.2, 'Amber: E9 HP corner auxiliaries', fontsize=9, color='#84601C')
            else:
                for eid, xy, txt in [(6, (0, 12.05), (-6.6, 14.3)), (5, (0.75, 7.55), (1.3, 5.3)), (7, (-2.25, 9.1), (-6.8, 8)), (8, (-2.25, 10.5), (-6.8, 11.8)), (10, (2.1, 9.8), (2.7, 11.2)), (11, (-1.5, 9.8), (-6.8, 10)), (14, (3.25, 8.2), (2.7, 6.5))]:
                    self.callout(ax, eid, xy, txt)
                ax.annotate('-z extraction\n0.8 mm slit', xy=(0, 6.0), xytext=(0, 8.8), ha='center', fontsize=9, color='#0069A8', arrowprops=dict(arrowstyle='->', color='#0069A8', lw=1.2))
        fig.suptitle('Electrode atlas | Actual sections and explicit HP corner-electrode projection', fontsize=18)
        fig.text(0.055, 0.025, 'Gray: intersected electrode solid. Amber: E9 corner auxiliary. White: vacuum / aperture. E labels are SIMION electrode groups.\nFrozen simplified CSG model; cross-sections have equal axis scales, longitudinal views do not. E9 projected footprints are shown explicitly, not as central-section solids.', fontsize=10, color='#444')
        self.save(fig, 'structure_sections', dict(planes=dict(longitudinal_x_mm=0, equatorial_z_mm=self.origin_z_mm, cross_section_y_mm=[self.G['guide_length_mm'] + self.G['hp_length_mm'] / 2, self.G['lp_center_mm']]), electrode_y_extents=extents, e9_display='Frozen E9 solids projected in the whole-apparatus side view only; four corners resolved in the HP cross-section'))

    def clouds(self):
        fig, axes = plt.subplots(math.ceil(len(self.LABELS) / 3), 3, figsize=(16, 3.4 * math.ceil(len(self.LABELS) / 3)), squeeze=False)
        fig.subplots_adjust(left=0.06, right=0.98, top=0.9, bottom=0.12, hspace=0.6, wspace=0.22)
        for ax, label in zip(axes.flat, self.LABELS):
            rows = [r for r in self.SNAPSHOTS if r['snapshot'] == label]
            time = float(rows[0]['t_us'])
            self.draw_geometry(ax)
            self.region_labels(ax)
            self.plot_states(ax, rows)
            n = {s: sum((r['status'] == s for r in rows)) for s in STATE}
            ax.set_title(f"t = {time:g} μs  |  Alive {n['alive']} / Extracted {n['extracted']} / Lost {n['lost']}", fontsize=9)
            if time >= self.C['native_timing']['primary_quench_us']:
                for r in rows:
                    if r['particle_id'] in self.RETAINED_IDS and len(self.RETAINED_IDS) <= 8 and (r['status'] == 'alive'):
                        shift = -2 if sorted(self.RETAINED_IDS).index(r['particle_id']) % 2 == 0 else 2
                        ax.annotate(r['particle_id'], (float(r['y_mm']), float(r['z_mm'])), xytext=(0, shift * 6), textcoords='offset points', fontsize=8, ha='center', color='#0069A8')
        for ax in list(axes.flat)[len(self.LABELS):]:
            ax.set_visible(False)
        count = len({r['particle_id'] for r in self.SNAPSHOTS})
        fig.suptitle(f'N = {count} | Time-resolved ion positions', fontsize=18)
        fig.text(0.06, 0.935, 'Gray: center section. Amber: E9 corner-electrode projection. Ion color: state only.', fontsize=11)
        self.state_legend(fig)
        fig.text(0.06, 0.062, 'Ions: all x positions projected onto y-z. Gray geometry: x=0 section; amber E9: projection. Overlap does not establish impact.\nRecorded states and bounded display interpolation; axes not to scale. Up to 8 retained ions are labeled by ID; the full cohort is always plotted.', fontsize=10, color='#444')
        self.save(fig, 'timed_clouds_sections', dict(snapshot_labels=self.LABELS, selected_particle_ids='all source IDs, no outcome filtering'))

    def extraction(self):
        quench = self.C['native_timing']['primary_quench_us']
        labels = [label for label in self.LABELS if float(next((r['t_us'] for r in self.SNAPSHOTS if r['snapshot'] == label))) >= quench]
        fig, axes = plt.subplots(math.ceil((len(labels) + 1) / 3), 3, figsize=(16, 4.5 * math.ceil((len(labels) + 1) / 3)), squeeze=False)
        fig.subplots_adjust(left=0.06, right=0.98, top=0.88, bottom=0.16, hspace=0.5, wspace=0.24)
        for ax, label in zip(axes.flat, labels):
            rows = [r for r in self.SNAPSHOTS if r['snapshot'] == label]
            t = float(rows[0]['t_us'])
            self.draw_geometry(ax)
            ax.set(xlim=(160, 180), ylim=(-0.5, 13.7))
            self.plot_states(ax, rows, True)
            alive = [r for r in rows if r['status'] == 'alive']
            outside = sum((not (160 <= float(r['y_mm']) <= 180 and -0.5 <= float(r['z_mm']) <= 13.7) for r in alive))
            ax.set_title(f'RF quench +{t - quench:g} μs\nAlive {len(alive)}, outside view {outside}', fontsize=11)
        ax = axes.flat[-1]
        self.draw_geometry(ax)
        ax.set(xlim=(160, 180), ylim=(-0.5, 13.7))
        ax.set_title('Structure reference (x=0 section)', fontsize=11)
        for eid, xy, txt in [(6, (162, 12.05), (163, 13.2)), (5, (162, 7.55), (160.3, 9.2)), (14, (178, 6.55), (172.5, 5.3))]:
            self.callout(ax, eid, xy, txt)
        ax.annotate('Acceleration / extraction (-z)', xy=(170, 0.4), xytext=(170, 8.9), ha='center', fontsize=10, color='#0069A8', arrowprops=dict(arrowstyle='->', color='#0069A8', lw=1.4))
        ax.text(160.2, 3, 'E7 / E8 / E10 / E11 are off-plane\nSee the LP cross-section in the atlas', fontsize=9, color='#555')
        fig.suptitle('LP extraction | Ion packet and physical apertures', fontsize=18)
        fig.text(0.06, 0.923, 'Solid gray sections retain the real apertures. The view includes both edges of the extraction slit.', fontsize=11)
        self.state_legend(fig)
        pulse_offset = self.C['native_timing']['pulse_start_us'] - self.C['native_timing']['primary_quench_us']
        fig.text(0.06, 0.085, f'All ion x positions projected onto y-z; gray geometry is the x=0 section. Outside ions remain in the full view.\nAcceleration pulse begins {pulse_offset:.5f} us after RF quench. Last positions are not live ions; axes are not to scale.', fontsize=10, color='#444')
        self.save(fig, 'extraction_clouds_sections', dict(snapshot_labels=labels, view_bounds_mm=dict(y=[160, 180], z=[-0.5, 13.7])))

    def verify_sections(self):
        """Pointwise cross-check section subtraction against original 3D CSG."""
        import random
        rng = random.Random(42)
        checked = 0

        def inside(s, p):
            if s['shape'] == 'box':
                return all((a <= v <= b for a, b, v in zip(s['min_mm'], s['max_mm'], p)))
            return s['x_min_mm'] <= p[0] <= s['x_max_mm'] and (p[1] - s['center_y_mm']) ** 2 + (p[2] - s['center_z_mm']) ** 2 <= s['radius_mm'] ** 2
        for view, value in [('long', 0), ('top', self.origin_z_mm), ('cross', self.G['guide_length_mm'] / 2), ('cross', self.G['guide_length_mm'] + self.G['hp_length_mm'] / 2), ('cross', self.G['lp_center_mm'])]:
            for e in self.ELECTRODES:
                shapes = parts(e, view, value, self.origin_z_mm)
                for _ in range(1500):
                    h = rng.uniform(-5, 215) if view in {'long', 'top'} else rng.uniform(-4, 4)
                    z = rng.uniform(-4, 4) if view == 'top' else rng.uniform(self.origin_z_mm-4, self.origin_z_mm+4)
                    world = (z, h, value) if view == 'top' else ((value, h, z) if view == 'long' else (h, value, z))
                    local = (world[1], self.origin_z_mm - world[2], -world[0])
                    expected = any((inside(s, local) for s in e['solids'])) and (not any((inside(s, local) for s in e['cutouts'])))
                    observed = any((p[0] <= h <= p[2] and p[1] <= z <= p[3] if k == 'rect' else (h - p[0]) ** 2 + (z - p[1]) ** 2 <= p[2] ** 2 for k, p in shapes))
                    assert expected == observed, (view, value, e['electrode_id'], world)
                    checked += 1
        (self.OUT / 'section_validation.json').write_text(json.dumps(dict(status='pass', point_membership_comparisons=checked, method='Frozen 3D CSG Boolean membership versus drawn 2D plane intersections; random points avoid boundary ambiguities', geometry_sha256=sha(self.MODEL)), indent=2) + '\n', encoding='utf-8')
        print('Section membership PASS', checked, flush=True)

    @plt.rc_context({'font.family': 'DejaVu Sans', 'font.size': 10, 'svg.fonttype': 'none'})
    def export(self, run, output_directory, snapshot_table=None):
        self.RUN = Path(run).resolve()
        self.OUT = Path(output_directory).resolve()
        self.MODEL = self.RUN / 'inputs/resolved_model.json'
        self.C = json.loads(self.MODEL.read_text(encoding='utf-8-sig'))
        self.ELECTRODES = self.C['native_projection']['electrodes']
        self.G = self.C['baseline']['geometry']
        self.origin_z_mm = self.C['coordinate_transform']['translation_mm'][2]
        source_paths = [self.RUN / p for p in ('inputs/resolved_model.json', 'inputs/diagnostics.json', 'simion/events.csv', 'simion/samples.csv', 'results/particle_state.csv')]
        before = {str(p): sha(p) for p in source_paths}
        with (self.RUN / 'simion/events.csv').open(newline='', encoding='utf-8-sig') as stream:
            self.RETAINED_IDS = {r['particle_id'] for r in csv.DictReader(stream) if r['event'] == 'terminal' and r['reason'] != 'acceptance_surface'}
        self.SNAPSHOT_PATH = Path(snapshot_table).resolve() if snapshot_table else self.OUT / 'diagnostic_snapshots.csv'
        with self.SNAPSHOT_PATH.open(newline='', encoding='utf-8-sig') as stream:
            self.SNAPSHOTS = list(csv.DictReader(stream))
        self.LABELS = list(dict.fromkeys((row['snapshot'] for row in self.SNAPSHOTS)))
        self.OUT.mkdir(parents=True, exist_ok=True)
        self.verify_sections()
        self.atlas()
        self.clouds()
        self.extraction()
        assert all((sha(p) == before[str(p)] for p in source_paths))
        print('PASS: 3 figures exported; original recorded evidence hashes unchanged.', flush=True)

def export_sections(run: Path, output_directory: Path, snapshot_table: Path | None=None) -> None:
    """Export English frozen-CSG sections and recorded clouds to fresh output files.

    Input positions are project mm and timestamps absolute us. The frozen run is
    read-only. Invalid CSG intersections or an existing figure fail rather than
    overwrite evidence. Each call owns a separate rendering context.
    """
    SectionDiagnostics().export(run, output_directory, snapshot_table)
