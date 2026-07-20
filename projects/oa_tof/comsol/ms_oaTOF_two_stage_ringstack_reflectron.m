function result = ms_oaTOF_two_stage_ringstack_reflectron(mass_amu, label, solver_mode, field_mode, d1_mm, n_rings2, mesh_hmax_refl_mm, bore_r_mm, ring_thickness_mm, n_particles, n_rings1, accel_bore_half_mm, fixed_particle_table, fine_tstep_ns, mesh_hmax_accel_mm, drift_tstep_ns, output_model_path, contract_path)
projectRoot = fileparts(fileparts(mfilename('fullpath')));
addpath(projectRoot);
if nargin < 18
    contract_path = '';
end
contract = load_oatof_contract(contract_path);
geometryMm = contract.geometry_mm;
acceleratorDesign = contract.geometry_derivation.accelerator;
reflectronDesign = contract.geometry_derivation.reflectron;
sourceDesign = contract.particle_source;
voltageV = contract.electrodes_V;
ringDesign = contract.rings;
% !!! d1_mm (doc §7.49, per explicit request -- corrected from an
% earlier d2-scan plan to a d1 scan): optional 5th argument, the
% reflectron's stage1 physical depth in mm (default 120, matching the
% current formal-model baseline). UNLIKE d2 (a pure geometric constraint that
% doesn't appear in the focusing equations at all -- see doc's §6),
% d1 DIRECTLY determines E1/E2/U1 via the closed-form solution:
% U1=2*U0*(L+2*d1)/(3*L), E1=U1/d1, and a more complex E2 formula
% involving sqrt(L-4*d1) -- all recomputed dynamically below for
% whatever d1_mm is passed in. Constraint: 0<d1<L/4=300mm (L_total=
% 1200mm for the current 600mm-field-free design) -- this is d1's own
% real constraint (see doc's §11 design flow / §7's derivation), NOT
% d2's (d2 only has a LOWER bound, d2>=d2_min=U1/E2, no upper bound).
% d2 stays FIXED at the established 300mm baseline throughout this scan.
if nargin < 5 || isempty(d1_mm)
    d1_mm = geometryMm.L_stage1;
end
% !!! n_rings2 (doc §7.53, per explicit request to test whether more
% stage2 ring electrodes reduce the real-vs-ideal field discrepancy
% identified as the resolution bottleneck via the field_mode='ideal_
% stage2' isolation test): optional 6th argument, defaults to the
% established baseline of 5. NOTE: an EARLIER test (5 vs 15 rings) at
% the OLD, much longer d2=300mm found no meaningful difference -- but
% that was at ring pitch~49.5mm (sparse); the CURRENT adaptive/margin-
% corrected d2 is much shorter (~87mm at 100% margin, pitch~14mm), a
% very different regime, so re-testing ring count here is warranted.
if nargin < 6 || isempty(n_rings2)
    n_rings2 = ringDesign.stage2_count;
end
% !!! mesh_hmax_refl_mm (doc §7.53, per explicit request to try methods
% to reduce the real-vs-ideal error in stage2): optional 7th argument,
% defaults to the established 15mm. That value was tuned when the whole
% reflectron (stage1+stage2) spanned ~500mm with ring pitch~33-49.5mm --
% now that the margin-corrected d2 has shrunk stage2 to ~87mm (pitch~
% 14mm), 15mm mesh elements are comparable to/coarser than the ring
% pitch itself, likely under-resolving the inter-ring field gradient
% (the exact failure mode the code's own §7.4x-era comments already
% flagged once before, at the old geometry, for a different reason).
if nargin < 7 || isempty(mesh_hmax_refl_mm)
    mesh_hmax_refl_mm = contract.comsol_runtime.routine_reflectron_hmax_mm;
end
% !!! bore_r_mm (doc §7.53, per explicit request): optional 8th argument,
% defaults to the established 250mm. Prior sessions (§7.31 era, at the
% OLD much-longer L_total/d2 design) extensively scanned this and found
% WIDER bore_r improved R (30mm->23.1 ... 250mm->4070.9, ideal ceiling
% 5780.1), the OPPOSITE of naive aperture-lens-fringe intuition -- but
% that scan predates the current adaptive-d2 fix that shrank stage2 to
% ~87mm. Since ring count and mesh refinement (also tested this session)
% both failed to close the ideal_stage2 gap, re-testing bore_r under the
% NEW short-d2 regime (where the fringe/settling zone from the entgrid/
% midgrid/backplate transitions may now dominate the entire, much
% shorter stage2 depth) is warranted -- the old conclusion may not carry
% over, same as the ring-count finding needed re-validation.
if nargin < 8 || isempty(bore_r_mm)
    bore_r_mm = geometryMm.bore_r;
end
% !!! ring_thickness_mm (per explicit request to scan ring electrode
% thickness alongside ring count, to test whether thicker/more numerous
% stage2 rings close the real-vs-ideal field gap identified via
% field_mode='ideal_stage2'): optional 9th argument, defaults to the
% established 5mm baseline. Previously a hardcoded literal.
if nargin < 9 || isempty(ring_thickness_mm)
    ring_thickness_mm = geometryMm.ring_thickness;
end
if nargin < 10 || isempty(n_particles)
    n_particles = contract.validation_target.particles;
end
% !!! n_rings1 is the stage-1 ring count (11th optional argument).  It is
% kept after n_particles for backward compatibility with the established
% ten-argument signature; n_rings2 remains the 6th argument.
if nargin < 11 || isempty(n_rings1)
    n_rings1 = ringDesign.stage1_count;
end
% Accelerator lateral family: the clear-aperture half-width is the only
% scanned dimension. Ring width, charged-to-ground clearance and wall
% thickness remain fixed and drive every outer width parametrically.
if nargin < 12 || isempty(accel_bore_half_mm)
    accel_bore_half_mm = geometryMm.accelerator_bore_half;
end
if ~(isscalar(accel_bore_half_mm) && accel_bore_half_mm > 0)
    error('accel_bore_half_mm must be positive.');
end
if nargin < 13 || isempty(fixed_particle_table)
    fixed_particle_table = '';
end
use_fixed_particle_table = ~isempty(fixed_particle_table);
if nargin < 14 || isempty(fine_tstep_ns)
    fine_tstep_ns = contract.comsol_runtime.fine_output_step_ns;
end
assert(isscalar(fine_tstep_ns) && fine_tstep_ns > 0, 'fine_tstep_ns must be positive.');
if nargin < 15 || isempty(mesh_hmax_accel_mm)
    mesh_hmax_accel_mm = contract.comsol_runtime.routine_accelerator_hmax_mm;
end
assert(isscalar(mesh_hmax_accel_mm) && mesh_hmax_accel_mm > 0, ...
    'mesh_hmax_accel_mm must be positive.');
if nargin < 16 || isempty(drift_tstep_ns)
    drift_tstep_ns = contract.comsol_runtime.field_free_output_step_ns;
end
if nargin < 17
    output_model_path = '';
end
assert(isscalar(drift_tstep_ns) && drift_tstep_ns > 0, ...
    'drift_tstep_ns must be positive.');
if ~(isscalar(n_rings1) && n_rings1 >= 1 && n_rings1 == fix(n_rings1))
    error('n_rings1 must be a positive integer.');
end
if ~(isscalar(n_rings2) && n_rings2 >= 1 && n_rings2 == fix(n_rings2))
    error('n_rings2 must be a positive integer.');
end
% !!! d2 made ADAPTIVE (doc §7.50, per explicit request): previously a
% fixed 300mm regardless of d1, which is WAY more than the ion's actual
% penetration depth needs. Now computed as d2_min*(1+d2_margin_frac), a
% modest, consistent margin over the theoretical minimum penetration
% depth (docx recommends 20%-50% margin -- 30% picked as a reasonable
% middle value) rather than an arbitrary fixed length.
% !!! d2_min FORMULA CORRECTED (doc §7.51, per explicit user question
% "穿透深度是d1+d2min�?"): the reference docx's own line 48 states
% "d2_min = U1/E2", but this contradicts its OWN line 9, which defines
% U1=E1*d1 as the voltage ABSORBED by stage1, leaving remaining energy
% q(U-U1) for the ion entering stage2 -- physically, the depth needed
% to decelerate that REMAINING energy under field E2 is (U0-U1)/E2, not
% U1/E2 (a basic energy-conservation check: KE=q*E2*depth). Verified
% directly against simulation at d1=120mm: measured stage2-only
% penetration = 50.70mm (170.70mm total - 120mm d1) vs the docx's
% U1/E2=173.67mm (off by 3.4x) vs the corrected (U0-U1)/E2=43.42mm (off
% by only ~17%, plausible real-3D-field vs ideal-1D-field discrepancy).
% This confirms the docx formula (d2_min=U1/E2) is an error; using the
% energy-conservation-correct (U0-U1)/E2 here instead.
d2_margin_fraction = reflectronDesign.stage2_margin_fraction;
reflectron_incident_energy_ev = reflectronDesign.incident_energy_eV;
reflectron_total_drift_m = reflectronDesign.total_field_free_length_mm/1000;
reflectron_stage1_m = d1_mm/1000;
if ~(reflectron_stage1_m > 0 && reflectron_stage1_m < reflectron_total_drift_m/4)
    error('d1_mm=%g violates 0<d1<L/4=%gmm', d1_mm, reflectron_total_drift_m/4*1000);
end
reflectron_midgrid_voltage_v = 2*reflectron_incident_energy_ev* ...
    (reflectron_total_drift_m+2*reflectron_stage1_m)/(3*reflectron_total_drift_m);
reflectron_stage1_field_vpm = reflectron_midgrid_voltage_v/reflectron_stage1_m;
reflectron_stage2_field_vpm = 12*reflectron_incident_energy_ev* ...
    (sqrt(3)*sqrt(reflectron_total_drift_m)+sqrt(reflectron_total_drift_m-4*reflectron_stage1_m)) / ...
    (sqrt(3)*reflectron_total_drift_m^1.5 + 8*sqrt(3)*sqrt(reflectron_total_drift_m)*reflectron_stage1_m + ...
     3*reflectron_total_drift_m*sqrt(reflectron_total_drift_m-4*reflectron_stage1_m));
reflectron_stage2_min_mm = ((reflectron_incident_energy_ev-reflectron_midgrid_voltage_v)/reflectron_stage2_field_vpm)*1000;
% Derive all physical quantities from the unrounded value first.  Only the
% resulting engineering geometry is rounded to baseline.json precision.
d2_raw_mm = reflectron_stage2_min_mm*(1+d2_margin_fraction);
reflectron_backplate_voltage_v = reflectron_midgrid_voltage_v + reflectron_stage2_field_vpm*(d2_raw_mm/1000);
d2_mm = round(d2_raw_mm, reflectronDesign.engineering_length_decimals_mm);
% An explicit resolved contract is authoritative for candidate execution.
% The legacy positional builder historically re-derived reflectron voltages
% and stage-2 length from d1; retaining that behavior without this branch
% silently discarded candidate compensation-voltage overrides.  Use the
% frozen candidate values and recompute the actual fields they imply.
if ~isempty(contract_path)
    d2_mm = geometryMm.L_stage2;
    reflectron_midgrid_voltage_v = voltageV.midgrid;
    reflectron_backplate_voltage_v = voltageV.backplate;
    reflectron_stage1_field_vpm = reflectron_midgrid_voltage_v/reflectron_stage1_m;
    reflectron_stage2_field_vpm = (reflectron_backplate_voltage_v-reflectron_midgrid_voltage_v)/(d2_mm/1000);
    reflectron_stage2_min_mm = ...
        ((reflectron_incident_energy_ev-reflectron_midgrid_voltage_v)/reflectron_stage2_field_vpm)*1000;
end
fprintf('[d1 scan] d1=%gmm -> U1(V_mid)=%.4fV, E1=%.4fV/m, E2=%.4fV/m, V_mirror=%.4fV, d2_min=%.2fmm, d2(adaptive,+%.0f%%)=%.2fmm\n', ...
    d1_mm, reflectron_midgrid_voltage_v, reflectron_stage1_field_vpm, reflectron_stage2_field_vpm, ...
    reflectron_backplate_voltage_v, reflectron_stage2_min_mm, d2_margin_fraction*100, d2_mm);
% oa-TOF two-stage ring-stack reflectron analyzer: orthogonal accelerator (pusher)
% + TOF flight tube + a REALISTIC ring-stack reflectron + appropriately-
% sized detector.
%
% !!! REBUILT to represent every GRID as an idealized fine wire mesh,
% not a solid plate with one big hole. A real grid is many closely-spaced
% (~0.5mm pitch) very thin (~0.02mm) wires -- electrically it behaves
% almost like a solid conducting sheet (minimal field distortion) while
% being >99% open to the ion. Modeling it as "solid disk minus one large
% circular aperture" is a fundamentally different (and much worse)
% physical object: a big hole in a plate lets the field "leak"/soften
% badly near the hole's center (classic aperture-lens effect), which was
% the root cause of a whole chain of field-leakage and divergence
% problems traced through this project (see doc §7.28 for the full
% history). The correct representation, validated with a standalone test
% (compare_ideal_vs_real style check + a dedicated interior-boundary
% test model): a ZERO-THICKNESS INTERIOR BOUNDARY, embedded inside a
% single continuous vacuum domain, carrying a fixed ElectricPotential
% condition (so electrostatics sees an unbroken sheet, matching a fine
% mesh's shielding) but NOT a material/domain boundary (so ChargedParti-
% cleTracing does not treat it as a wall -- the ion passes straight
% through, at any (x,y) position, since there's no hole to speak of).
% Practical upshot: since the ion can pass through ANYWHERE on these
% grids, they no longer need any aperture sizing tradeoff at all -- each
% grid is simply built as a FULL 800x800mm sheet (matching the vacuum
% cross-section), eliminating the whole aperture-lens problem rather than
% trying to balance it. This also makes `grid2` (which existed ONLY to
% give the ion's wider return-path drift a big enough hole to avoid being
% blocked by grid1's small aperture) and the shielding `sleeve` (an
% attempted patch for leakage through a hole that no longer exists)
% unnecessary -- both removed.
%
% !!! IMPORTANT COMSOL GOTCHA uncovered while building this (see doc
% §7.28/§1 for the permanent record): Box/Cylinder selections using the
% 'intersects' condition can silently grab OTHER boundaries that merely
% pass through the selection region (e.g. a thin z-slab meant to isolate
% one flat cap can also catch a side wall that spans the full z-range).
% If two ElectricPotential features end up sharing the same boundary ID
% this way, COMSOL does NOT raise an error -- one of them just silently
% ends up with ZERO effect (its own selection.entities() reports 0, and
% the boundary's actual potential is whatever the OTHER feature set).
% Always use Box selections with 'allvertices' (not 'intersects') and a
% FULLY specified x/y/z range for isolating a specific flat face.
%
% Reflectron: built from a stack of annular ("washer"-shaped, hollow-
% centered) electrodes held at a two-stage graded sequence of potentials
% (0 near the entrance, stepping through V_mid, up to V_mirror at the
% back) -- entrance grid -> stage1 rings -> middle grid -> stage2 rings
% -> solid backplate (no grid needed there; ions never reach it).

% !!! Per-phase timing instrumentation (per explicit request to profile
% where wall-clock time actually goes, ahead of a speed-optimization
% pass): a running struct of tic/toc pairs, printed as a summary table at
% the very end. Does not affect any physics/accuracy, purely diagnostic.
t_total_start = tic;
paths = oatof_paths();
addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
import com.comsol.model.*
import com.comsol.model.util.*

if nargin<1, mass_amu = contract.validation_target.mass_amu; end
if nargin<2, label = sprintf('%gamu', mass_amu); end
if nargin<3, solver_mode = 'cpu'; end
if nargin<4, field_mode = 'real'; end
% !!! solver_mode: 'gpu' uses cudss for BOTH the electrostatics solve
% (sol1) and the CPT time-dependent solve's nonlinear linear solver
% (sol2/t1/fc1); 'cpu' uses COMSOL's default CPU direct solver (pardiso/
% mumps) for both. Originally defaulted to 'gpu' (chosen for a N=10000
% comparison, where GPU plausibly wins on a bigger linear system), but
% at the project's actual typical exploratory scale (N=100), a direct
% controlled A/B test on this machine's GPU (RTX 2060, 4GB VRAM) found
% GPU consistently SLOWER for the CPT solve phase (162-236s across
% several N=100/d1=120mm runs) than CPU (116.98s, same params, same
% server session) -- kernel-launch/PCIe-transfer overhead evidently
% dominates over any parallel-compute benefit at this problem size.
% Default switched to 'cpu' accordingly; 'gpu' remains available and may
% still be worth re-testing for genuinely large-N (5000-10000) runs
% where the linear system is bigger, but has NOT been re-validated as
% better there since this default flip.
% field_mode selects diagnostic idealization without changing the solved
% electrostatic field. 'real' is production. The composable syntax is
% ideal:<region>.<component>[+...], with region accel/drift/stage1/stage2/
% reflectron/all and component ex/ey/ez/all. Legacy ideal_* names remain
% accepted. The selected flags and final E expressions are persisted in
% the Model Builder for GUI inspection and controlled Compute reruns.

t_geom_start = tic;
if any(strcmp(cell(ModelUtil.tags()), 'ModelOATOFRing'))
    ModelUtil.remove('ModelOATOFRing');
end
model = ModelUtil.create('ModelOATOFRing');
comp1 = model.component.create('comp1', true);
geom1 = comp1.geom.create('geom1', 3);
geom1.label('Orthogonal accelerator + RING-STACK reflectron -- idealized mesh grids as interior boundaries');
geom1.lengthUnit('mm');

p = model.param;
p.set('KE_in_eV', sprintf('%.12g[V]', contract.validation_target.initial_energy_mean_ev), ...
    'Ion energy entering the pusher, from baseline.json');
% 3-electrode accelerator: repeller (V_repeller) -> intermediate grid
% (V_accelmid, absorbs most of the drop) -> exit grid (0V, always
% grounded, matches the field-free region). Both repeller and accelmid
% pulse together; the exit grid never pulses.
% !!! REDESIGNED per the "三栅加速器总长度符号推�? document's exact
% first-order time-focusing solution: the three-grid accelerator
% (repeller=grid1_doc, my grid1=grid2_doc, my grid2=grid3_doc/grounded)
% can be designed so the ion focuses (dT/du=0) EXACTLY at the field-free
% boundary (D=0), using: E1=2*dKE/dx0, U1=KE0+dKE*d1/dx0,
% U2=KE0-dKE*d1/dx0, rho*=v3/(v3-v2), E2=E1/rho*, d2=U2/E2*. With
% KE0=2000eV, dKE=80eV, dx0=1mm, d1=3mm (all per explicit request):
% U1=2240V, U2=1760V, d2=16.83mm, L_accel=d1+d2=19.83mm (D=0, no extra
% drift needed -- this is the key fix for the "upstream transit time"
% problem found earlier: the accelerator ITSELF now compensates for the
% z0-dependent timing spread, before the ion even reaches the field-free
% region).
p.set('V_repeller', sprintf('%.12g[V]', voltageV.repeller), ...
    'Accelerator repeller voltage from baseline.json');
% !!! Attempted a Wiley-McLaren "space focusing" scan (per explicit
% request to reduce the z-direction KE spread WITHOUT changing the
% release volume): the accelerator's own two-stage split (repeller->
% accelmid->grid1) is structurally the classic 2-field ion source, so
% tuning the field-strength ratio between the two stages should be able
% to make ions starting at different z0 arrive at the same time (to
% first order) -- this is the standard real-TOF-MS technique for this
% problem, instead of shrinking the source volume. A small-N scan
% (N=50, then N=200) appeared to find an improvement around 3700V
% (R=26.7 vs ~17 at 3500V) -- but a large-N (10000) confirmation showed
% NO real difference (3700V: R=18.9, 3500V: R=19.7, statistically the
% same). The apparent "improvement" was sampling noise from
% SamplingFromDistribution='Random' re-drawing different random
% particles each run, not a genuine physical effect (see doc §7.29 for
% the full account) -- reverted to the simpler round value since 3700V
% provides no real benefit.
% !!! MAJOR SIMPLIFICATION per explicit request: accelmid removed
% entirely. New accelerator has only 3 electrodes: repeller (z=0) ->
% grid1 (z=3mm) -> grid2 (z=L_accel=6mm, grounded, marks the field-free
% interface). Ion releases BETWEEN repeller and grid1 (release cube
% z0 in [1,2]mm, unchanged). repeller+grid1 together form a WEAK,
% uniform "bracket" field (same role as the old gridA/gridB pair) --
% grid1's voltage is NOT arbitrary, it's derived from the DESIRED
% initial KE and KE spread: choosing E_bracket=22.7 V/mm over the 3mm
% gap gives the SAME +-11.35eV half-range spread as the old gridA/gridB
% design (comparable basis for before/after comparison), so
% V_grid1 = V_repeller - 22.7*3 = 4500-68.1 = 4431.9V. grid1 and grid2
% have NO direct relationship (just need to be spatially separated) --
% grid1-to-grid2 gap is ALSO set to 3mm per explicit request, giving
% L_accel=6mm total. K0 (nominal, release cube center z0=1.5mm) =
% V_repeller - 22.7*1.5 = 4465.95V.
p.set('V_grid1', sprintf('%.12g[V]', voltageV.grid1), ...
    'Accelerator first-grid voltage from baseline.json');
% !!! Quick V_mirror scan (N=30 each) found 1.4x gave the best timing
% resolution among tested factors (1.0/1.1/1.2/1.3/1.4 -> R=11.7/24.5/
% 18.2/20.7/28.1). The dominant timing-spread source is a real, accepted
% physics effect (the 1mm release cube's z-extent causes ~+-220eV KE
% spread in the 20mm accelerator gap, correlation(z0,detTime)=0.84) --
% not something this simple 2-stage reflectron fully corrects. Per
% explicit decision, NOT pursuing further multi-parameter optimization
% (V_mid/L_stage1/etc.) -- accepting this resolution level and moving
% focus to large-N trajectory statistics instead.
% !!! REDESIGNED using the proper dual-stage Mamyrin closed-form solution
% (reflectron_dual_stage_solver.py + accompanying derivation doc), which
% solves BOTH the first-order (dT/dU=0) AND second-order (d2T/dU2=0)
% focusing conditions simultaneously for E1 AND E2 together. Previously
% V_mirror was arbitrarily fixed at V_repeller*1.4 and only V_mid (E1)
% was tuned to satisfy the first-order condition alone -- this is why
% all V_mid scans plateaued around R~500: the SECOND-order term was
% never actually zeroed, and that residual curvature is what was
% limiting resolution, not anything V_mid alone could fix.
% For U0=4125eV (measured real entrance KE), d1=200mm, L_total=1000mm:
% solver gives E2=18455.79 V/m; with d2=300mm chosen (comfortable margin
% over the true penetration depth (U0-U1)/E2=14.9mm -- note: the
% document's own "d2_min=U1/E2" formula is inconsistent with its own
% flight_time() function, which correctly uses (U-U1) for v1; verified
% by direct computation), V_mirror = U1+E2*d2 = 3850+18455.79*0.3 =
% 9386.74V.
% !!! Recomputed for the new accelerator (K0=4465.95eV, not 4125eV):
% reflectron_dual_stage_solver.py with U0=4465.95, d1=0.2, L=1.0 gives
% E1=20841.1 V/m, E2=19981.24 V/m, U1=4168.22V; with d2=300mm,
% V_mirror=U1+E2*d2=4168.22+19981.24*0.3=10162.59V.
% !!! L_total for the Mamyrin dual-stage solver is the REAL field-free
% drift (source/accel-exit to reflectron, plus reflectron back to
% detector). Since the ion is released mid-acceleration and only
% reaches full/constant velocity at grid2 (z=L_accel=19.83mm),
% L1=L_flight-L_accel; with the detector sitting at the field-free
% boundary too (see the 'detector' geometry pos below), L2=L_flight-
% (L_accel+0.3mm).
% !!! REDESIGNED per explicit request: L_flight changed from a fixed
% 500mm to L_accel+500[mm] (see the L_flight parameter comment above),
% so that L1=L_flight-L_accel=500.00mm and L2=L_flight-(L_accel+0.3mm)=
% 499.70mm EXACTLY (was 480.17mm/479.87mm before) -- L_total=999.70mm,
% treated as the clean L=1.0m for the closed-form solve (the 0.3mm
% residual from the detector offset is negligible against 1000mm).
% reflectron_dual_stage_solver.py with U0=2000, d1=0.2m, L=1.0m gives
% E1=9333.33 V/m, E2=8948.26 V/m, U1=1866.67V; with d2=300mm,
% V_mirror=U1+E2*d2=1866.67+8.94826*300=4551.15V.
% !!! Recomputed for L_flight extended to give L1=L2=600mm (doc §7.49):
% reflectron_dual_stage_solver.py with U0=2000, d1=0.2m, L=1.2m gives
% Now recomputed dynamically at the top of this function from d1_mm
% (see the d1-scan block above) instead of a fixed literal, to support
% scanning different d1 values (doc §7.49).
p.set('V_mirror', sprintf('%.4f[V]', reflectron_backplate_voltage_v), ...
    'Reflectron backplate derived from the baseline dual-stage design');
% !!! L_accel now derived from the three-grid focusing solution:
% d1+d2=3+16.83=19.83mm, with D=0 (no extra drift needed for
% first-order time focus -- ion focuses exactly at grid2/field-free
% boundary).
p.set('z_accel_origin', sprintf('%.17g[mm]', geometryMm.accelerator_repeller_z), ...
    'Canonical global repeller front from baseline.json');
p.set('accel_stage1_length', sprintf('%.17g[mm]', acceleratorDesign.d1_mm), ...
    'Accelerator repeller-to-grid1 length from baseline.json');
p.set('accel_stage2_length', sprintf('%.17g[mm]', acceleratorDesign.d2_mm), ...
    'Accelerator grid1-to-grid2 length from baseline.json');
p.set('L_accel', 'accel_stage1_length+accel_stage2_length', ...
    'Derived accelerator total length');
p.set('z_accel_grid1', 'z_accel_origin+accel_stage1_length', ...
    'Derived canonical global grid1 plane');
p.set('z_accel_grid2', 'z_accel_origin+L_accel', 'Canonical global grid2 plane');
p.set('source_center_z', sprintf('%.17g[mm]', sourceDesign.center_z_mm), ...
    'Particle-source global z center from baseline.json');
p.set('accel_focus_drift', sprintf('%.17g[mm]', acceleratorDesign.focus_drift_after_grid2_mm), ...
    'First-order focus drift derived by accelerator_time_focus.py');
% !!! Extended 10x (300->3000mm) per explicit request to test whether a
% longer flight path improves mass resolution -- for a system where the
% dominant timing spread comes from geometric/spatial effects that don't
% scale with distance (not a genuine energy-focusing defect the
% reflectron should fix), FWHM resolution R=t/(2*FWHM_t) should improve
% roughly proportionally to flight length, since t grows while sigma_t
% stays close to constant.
% !!! Redesigned per explicit request: search over (drift length,
% stage1/stage2 lengths) for a design achieving R>=2000 (exact non-
% linearized T(K) model) while keeping k1=V_mid/K0<=0.8 (safety margin,
% avoiding the earlier fragility where V_mid was too close to K0). Best
% found: L(drift)=300mm, L_stage1=10mm, L_stage2=80mm, k1=0.6665 (V_mid
% comfortably below K0 -- 1375eV remaining margin for stage2, vs the
% earlier fragile design's 13eV). Predicted R~4.86 million (T(K) flat to
% <3ps over the full +-11.35eV range) -- far exceeding the 2000 target,
% with a much shorter, more compact instrument (was 3000mm, now 320mm
% total flight tube) as a side benefit.
% !!! Redesigned per explicit constraint: each of drift/stage1/stage2
% must be in [200,600]mm. Design-space search (exact 1D T(K) model,
% k1<=0.8 safety cap) found L(drift)=200mm, L_stage1=500mm,
% L_stage2=500mm, k1=0.1051 as the top theoretical candidate (R~1.5M
% predicted). NOTE: the previous "compact" design (300/10/80mm,
% k1=0.6665) predicted R~4.86M theoretically but only achieved R=96.4
% empirically -- corr(z0,detTime) stayed at -0.846 even at the
% "optimal" k1, meaning the 1D theory has a real, unexplained gap from
% the true 3D COMSOL physics. This new large-scale design is a fresh
% attempt with a much safer (smaller) k1, to be empirically fine-tuned
% around this theoretical starting point rather than trusted blindly.
% !!! V_mid scan (100-600V) at L=200/L1=500/L2=500 gave a FLAT R~360-380
% (residual-after-z0-linear-trend implied R~4600 is achievable, but the
% z0-detTime slope barely changed across this V_mid range -- because
% V_mid is small relative to V_mirror=6300V, so stage2's field
% (V_mirror-V_mid)/L_stage2 barely changes as V_mid varies). Switching
% to a DIFFERENT (L,L_stage1,L_stage2) combination from the design
% search to get a genuinely different drift/dwell-time balance.
% !!! FINAL: after extensive search (200/500/500 -> R~360-380 flat vs
% V_mid; 500/400/600 -> R~500-510 flat vs V_mid; 600/200/600 -> crashed
% at N>=50, unstable), the 500/400/600mm design is the best STABLE
% (100% detection at N=200, no solver crashes) configuration found.
% !!! Reverted to the best-found stable design (symmetric 600/200/200mm
% underperformed: R=214-258 vs this design's R=505.7) for a finer V_mid
% scan.
% !!! REDESIGNED using the dual-stage Mamyrin closed-form solver, per
% explicit request: L_total(drift)=1000mm, d1=200mm. The solver's L
% parameter is L1+L2 (source-to-reflectron + reflectron-to-detector);
% with the default symmetric split L1=L2=500mm, this maps directly to
% this model's L_flight=500mm (one-way drift, doubled for the round
% trip in the CPT geometry, matching L1=L2 exactly).
% !!! Despite the name, this is the ABSOLUTE z-COORDINATE of entgrid
% (measured from the repeller at z=0), NOT the field-free length itself
% -- the accelerator eats into the first L_accel=19.83mm of this span
% before the ion reaches constant velocity at grid2. The true field-free
% lengths are L1=L_flight-L_accel (source side) and
% L2=L_flight-(L_accel+0.3mm) (detector side, since the detector sits at
% z=L_accel+0.3mm, not exactly at z=L_accel).
% !!! CHANGED from 500mm to L_accel+500mm=519.83mm, per explicit
% request to make L1=L2=500mm EXACTLY (true field-free lengths, not the
% z-position). This gives L1=L_flight-L_accel=500.00mm exactly, and
% L2=L_flight-(L_accel+0.3mm)=499.70mm (0.3mm short of exactly 500mm,
% from the detector's small offset off grid2's own boundary -- utterly
% negligible against a 500mm drift, kept rather than eliminating the
% offset since that offset itself prevents a real geometry overlap bug,
% see the 'detector' pos comment below). L_total=L1+L2=999.70mm, treated
% as 1000mm for the theoretical reflectron solve (the 0.3mm residual is
% not worth carrying through the closed-form solver).
% !!! Extended from L_accel+500mm to L_accel+600mm (doc §7.49, per
% explicit request): gives true field-free length L1=L_flight-L_accel=
% 600.00mm exactly (detector_z=L_accel unchanged, so L2=600mm too).
p.set('flight_length_from_detector', sprintf('%.17g[mm]', geometryMm.L_flight-geometryMm.detector_z), ...
    'Detector/focus plane to reflectron entrance distance from baseline.json');
p.set('L_flight', 'detector_z+flight_length_from_detector', ...
    'Derived canonical reflectron entrance global z');
% !!! Added a named parameter for the detector's z-position, instead of
% only setting it inline in the geometry command -- the detection
% z-threshold in the post-processing code below previously used a bare
% hardcoded number (20.5) that silently matched the OLD detector
% position by coincidence and would have gone stale/wrong the moment
% the detector moved (exactly what happened during the §7.41 L1/L2
% asymmetry test). Both the geometry and the detection logic now read
% this SAME parameter, so they can never drift apart again.
p.set('detector_z', 'z_accel_grid2+accel_focus_drift', 'Detector active plane is the exact derived first-order time-focus plane and canonical z=0 datum');
p.set('L_refl', sprintf('%.12g[mm]', d1_mm+d2_mm), 'Ring-stack reflectron total length (physics-derived d1+d2, rounded to the shared 0.0001mm engineering precision in baseline.json)');
p.set('L_stage1', sprintf('%g[mm]', d1_mm), 'Stage 1 length (entrance grid to middle grid) = d1, from the d1_mm function argument (doc §7.49, was fixed 200mm)');
% !!! CORRECTED: the first attempt used K0=V_repeller=4500eV, but the
% ion actually enters the REFLECTRON with KE = the LOCAL potential at
% its release z0 within the gridA/gridB bracket (measured directly:
% K0=4125eV at the release cube's center, NOT 4500eV -- the gridA/gridB
% bracket itself absorbs part of the total accelerating voltage before
% the ion even reaches grid1). Using the wrong K0=4500 gave
% V_mid=4474V, which is actually GREATER than the ion's real K0=4125eV
% -- meaning the ion never even reached stage2, it reflected WITHIN
% stage1 itself, a completely different (and untested-for) regime than
% the Mamyrin dual-stage math assumed. Re-solving with the correct
% K0=4125eV gives k1=V_mid/K0=0.996762, V_mid=4111.64V (still <K0, so the
% ion DOES pass through stage1 into stage2 as intended, with ~13.4eV
% remaining for a shallow stage2 penetration).
% !!! Redesigned value (k1=0.6665, V_mid=0.6665*4125=2749.5V) for the
% new L(drift)=300mm/L_stage1=10mm/L_stage2=80mm geometry -- see the
% L_flight/L_refl comment above for the full search description. This
% k1 leaves 1375eV of margin before the ion would fail to clear stage1
% (vs the earlier fragile design's 13eV margin), directly satisfying the
% "V_mid <= 0.8*K0" safety constraint with room to spare.
p.set('V_mid', sprintf('%.4f[V]', reflectron_midgrid_voltage_v), ...
    'Dual-stage reflectron midgrid voltage derived from baseline physical inputs');
% !!! Ring count reduced from 15 to 5 per stage, per explicit request.
% !!! Tested 15 rings vs 5: field deviation and R were essentially
% UNCHANGED (~1.3-2% swing either way, R=820 vs 834 -- within N=10
% noise). Ring count is NOT the limiting factor -- reverted to 5 for
% faster mesh/solve.
p.set('N_rings1', num2str(n_rings1), 'Stage 1 ring electrodes -- parametrized (11th function argument)');
p.set('N_rings2', num2str(n_rings2), 'Stage 2 ring electrodes -- parametrized (doc §7.53) to test ring-count vs field-discretization-error tradeoff at the shorter, margin-corrected d2');
% !!! Reflectron ring geometry is parameterized consistently for both
% stages: common annular thickness ring_thickness, common bore radius
% bore_r (inner diameter = 2*bore_r), and independent stage ring counts
% N_rings1/N_rings2. Ring centers are uniformly spaced between the two
% bounding grids/backplate, so equal thickness gives equal solid-to-solid
% axial gaps, including the final stage2-ring/backplate gap.
p.set('ring_thickness', sprintf('%g[mm]', ring_thickness_mm), 'Reflectron ring electrode thickness -- parametrized (per explicit request) to scan alongside N_rings2');
% !!! Re-measured for the extended L_flight=3000mm: 10x longer flight
% time means ~10x more x-drift accumulates before the ion reaches the
% reflectron. Direct trace (N=10, wide temporary bore) measured the
% apex at x=89.4-90.8mm (mean 90.1mm), vs the old 33mm for L_flight=300mm.
% !!! Re-measured for the new L_flight=320mm (much shorter drift, so
% much less x-drift accumulates): direct trace (N=10, wide temporary
% bore) measured the apex at x=13.4-16.0mm (mean 14.66mm), vs the old
% 90mm for L_flight=3000mm.
% !!! Re-measured for the new 200/500/500mm geometry: apex x=40.8-41.6mm
% (mean 41.2mm), vs the old 14.7mm for the compact 320/10/80mm design.
% !!! RESET to 0: per explicit request to check/fix model symmetry --
% the flight tube (accelflightbox, now a cylinder) and the accelerator's
% own axis are both at x=0,y=0, but the reflectron (rings/backplate/
% reflvac) was on a SEPARATE axis at x=41.2mm (historically centered on
% the ion's measured trajectory apex, back when the flight tube was a
% square Block without a well-defined single axis). With bore_r=250mm
% now comfortably larger than the ion's ~41mm off-axis drift, there's no
% remaining reason for a SEPARATE reflectron axis -- unifying everything
% on x=0 makes the whole accelerator+flight-tube+reflectron system
% share one consistent axis of symmetry.
p.set('x_refl_center', sprintf('%.17g[mm]', contract.coordinate_convention.reflectron_axis(1)), ...
    'Reflectron global x-axis from baseline.json');
% Rings are STILL solid annulus electrodes (ions fly through the empty
% bore, not through conductor material) -- the interior-boundary
% technique doesn't apply to them, only to the flat grids. bore_r/
% ring_outer_r sizing is a separate, still-open question (aperture-lens
% effects on the RING STACK's own near-axis field strength) to revisit
% after this grid rebuild is validated -- parked at the last isolated
% test values.
% !!! TEMPORARILY widened for re-measurement diagnostic: the 10x longer
% L_flight means ~10x more x-drift accumulates before the ion reaches the
% reflectron, so the old 80mm bore (tuned for the old, much shorter
% drift) would likely miss the ion entirely or trigger the aperture-lens
% instability. Widen generously, re-measure the true apex position with
% a small N, then narrow back down once x_refl_center is recalibrated.
% Narrowed back to the validated good-field-strength size now that
% x_refl_center is properly centered on the measured apex (residual
% offset near 0), matching the earlier proven ratio (bore/outer=0.4).
% !!! TEMPORARILY widened for re-measurement: L_flight dropped from
% 3000mm to 320mm (much shorter drift), so accumulated x-drift before
% reaching the reflectron will be much smaller than the old x_refl_
% center=90mm calibration assumed. Widen generously, re-measure, then
% narrow back down (same methodology used earlier in this project).
% Narrowed back to the validated good-field-strength size now that
% x_refl_center is properly centered on the measured apex.
% !!! TEMPORARILY widened for re-measurement: geometry changed
% drastically (L_flight 320->200mm, L_refl 90->1000mm), so the old
% x_refl_center=14.7mm calibration is almost certainly wrong now.
% !!! Widened from the old 80/200mm: the much longer round-trip time for
% this 200/500/500mm design (~28us vs ~8.6us before) lets the ion's
% x-velocity accumulate much more x-drift while still INSIDE the
% reflectron, causing it to exit the old 80mm bore radius and hit solid
% ring material (0/50 detected, xEnd values 80-128mm scattered instead
% of clustering near the expected 173mm return spot).
% !!! TEMPORARILY widened for re-measurement (new 500/400/600mm design
% has an even longer round trip than the 200/500/500mm one, meaning
% more accumulated x-drift).
% !!! Narrowed from the temporary wide diagnostic values (300/350mm) to
% test whether this fixes the ~8% S-shaped field distortion found in
% stage2 -- ion's measured off-axis excursion is up to ~41.45mm, so
% bore_r=80mm still gives comfortable clearance (validated bore/outer
% ratio=0.4 from earlier in this project).
% !!! Optimization scan result (real field, N=100, after correcting
% L_total=960.34mm): counterintuitively, WIDENING bore_r (not narrowing
% it further) improved R: 30mm->23.1, 60mm->580.4, 80mm(old
% default)->1568.4, 100mm->2262.0, 150mm->3933.3, 250mm->4070.9 (vs the
% ideal-field ceiling of 5780.1 at this design). This REVERSES the
% earlier (pre-L_total-fix) finding that narrowing 300->80mm helped --
% that finding was made against the WRONG L_total=1000mm design, so its
% "sweet spot" doesn't carry over. 400mm tested even higher (4869.2) but
% is UNSAFE: the flat-grid WorkPlanes are only 800x800mm (+-400mm
% half-width, see z_mid_expr/wp_midgrid etc.), so ring_outer_r=500mm
% exceeds the grid's own extent and caused a geometry mismatch (selb_
% midgrid boundary count jumped to 5, should be 2) -- results at that
% size are unreliable. Settled on 250mm/350mm: safely under the 400mm
% WorkPlane half-width, clean boundary counts, and already captures most
% of the available improvement (4070.9 vs the 5780.1 ceiling, ~70%).
% !!! Pushed the scan further (400mm/500mm, 500mm/650mm) after enlarging
% the WorkPlane extent (fixed the earlier geometry-mismatch concern --
% boundary counts came back clean at 400mm: grid1=1,grid2=1,entgrid=2,
% midgrid=2). But cost exploded: mesh went from 172K elements (250mm) to
% 2.2M (400mm) to 3.66M (500mm/650mm, where even electrostatics alone
% took 100s+ and the CPT solve then timed out past 290s). Meanwhile the
% R improvement kept shrinking (150mm->3933, 250mm->4070, 400mm->4869 --
% each further step buys less). Settled back on 250mm/350mm: the best
% cost/benefit point found, already validated at N=5000 (R=2849.2, see
% below), fast (~6s electrostatics, ~2min CPT at N=5000), clean geometry.
% !!! TESTED and REVERTED: tried 300mm/390mm (up from 250mm/350mm) to
% see if the newly diagnosed "boundary settling" effect (smooth
% ~0.06-0.58% deviation, worst near entgrid/backplate where the field
% jump is largest, best near midgrid where it's smallest -- NOT a
% ring-discretization ripple, confirmed identical before/after a mesh-
% refinement-region fix) would shrink with a larger aperture. N=100
% looked promising but was noise (a 400mm exact-match boundary-overlap
% bug inflated that specific result); at N=1000 (statistically
% meaningful), 300/390mm gave R=5637.7 and quadratic-fit residual
% 0.6386ns -- WORSE than or equal to the 250/350mm baseline (R=6581.6,
% residual 0.6258ns). The "wider bore = better" relationship found in
% §7.31 was established BEFORE the L_total and ring-center-alignment
% fixes; it does not carry over now that those larger errors are gone
% -- with this much smaller remaining error budget, a different
% mechanism (not aperture-scaled boundary settling) may now dominate.
% Reverted to the current fixed-outer-radius baseline: bore_r=250mm,
% ring_outer_r=300mm.
p.set('bore_r', sprintf('%g[mm]', bore_r_mm), 'Ring bore (aperture) radius -- parametrized (doc §7.53) to re-test the bore_r/R relationship under the current, much shorter adaptive-d2 stage2 geometry');
p.set('ring_outer_r', sprintf('%.12g[mm]', geometryMm.ring_outer_r), ...
    'Reflectron ring outer radius from baseline.json');
% !!! Flight tube redesigned as a hollow CYLINDER (was a square Block),
% per explicit request: entgrid/grid2 (flight-tube boundary grids) are
% circular, matching the cylinder; grid1/accelring_k (INSIDE the
% accelerator's own square shield) stay square. flight_tube_r is sized
% comfortably larger than both the electrodes it contains (ion's real
% drift path reaches ~80mm off-axis) AND the charged grids (entgrid/
% grid2 themselves), giving genuine vacuum clearance between the tube's
% own grounded wall and anything at a different potential inside it.
p.set('flight_tube_r', sprintf('%.12g[mm]', geometryMm.flight_tube_r), ...
    'Grounded flight-tube inner radius from baseline.json');
% !!! Added an EXPLICIT solid wall for the flight tube (doc §7.43), per
% explicit request -- previously accelflightbox's own outer surface was
% just an implicit grounded boundary condition (selb_outerwall), no
% actual wall material modeled. Now a real annular Cylinder-Cylinder
% shell (radius flight_tube_r to flight_tube_r+flight_tube_wall) wraps
% around it, grounded (0V), matching the same technique used for the
% accelerator's own shield.
p.set('flight_tube_wall', sprintf('%.12g[mm]', geometryMm.flight_tube_wall), ...
    'Flight-tube and end-cap thickness from baseline.json');
% !!! Added for doc §7.44, per explicit request: the flight tube's own
% shield is extended to ALSO enclose the reflectron region (previously
% only wrapped the field-free drift section) -- both ends of this now-
% longer shield are closed. flight_tube_r=ring_outer_r+50mm already
% gives 50mm radial clearance from the rings/backplate; shield_axial_gap
% enforces a 50mm minimum axial clearance in the current scan
% clearance in the AXIAL direction between the backplate's own far face
% and the new far-end cap.
p.set('shield_axial_gap', sprintf('%.12g[mm]', geometryMm.shield_axial_gap), ...
    'Backplate-to-far-endcap clearance from baseline.json');
% !!! Added for doc §7.50, per explicit request: the ENTIRE accelerator
% assembly (repeller, accelshield, grid1, grid2, accelring_k, relvol)
% is shifted off-axis by -x_accel_center, and the detector by
% +x_accel_center, so BOTH the ion's release point and its detection
% point sit symmetrically about the flight tube's TRUE cylindrical axis
% (x=0, matching flight_tube_r/ring_outer_r's own center) instead of the
% ion starting exactly ON-axis and drifting to a one-sided detection
% point off to the side. x_accel_center = v_x*(T/2), where v_x=3106.2
% m/s is the 5eV transverse entrance speed and T is the established
% total flight time for the current (d1=120mm) design (~31.42246us) --
% over the full flight, the ion's total x-displacement is v_x*T =
% 2*x_accel_center, carrying it from -x_accel_center exactly to
% +x_accel_center, symmetric about the true axis. Per explicit request,
% T is taken from the CURRENT setup's measured flight time (not
% re-derived iteratively for a self-consistent fixed point).
p.set('x_accel_center', sprintf('%.17g[mm]', contract.coordinate_convention.accelerator_axis_x), ...
    'Accelerator global x-axis from baseline.json');
p.set('detector_x', '-x_accel_center', 'Detector x-center linked as the mirror image of the accelerator axis; moving the accelerator cannot leave the detector behind');
p.set('detector_radius', sprintf('%.12g[mm]', geometryMm.detector_radius), ...
    'Physical detector radius from baseline.json');
% !!! TRIED (doc §7.47) shrinking grid1/grid2/entgrid away from their
% shield's own bore, matching the accel_ring_gap discipline used for
% real solid conductors -- but idealized zero-thickness grids MUST span
% the FULL cross-section of the vacuum they divide (§7.37/§7.38), so
% this broke the field-free region (residual jumped to -8V/m). Reverted;
% see the gridspecs comment below for the full explanation. Parameter
% removed as unused (would only be reintroduced if a genuinely different
% construction, e.g. a solid physical grid frame, were modeled later).
% !!! t_trig/t_pulse_width removed: no longer needed since the
% accelerator's field is now always-on (static), not pulsed -- see the
% "es" solve section for the reasoning.
% !!! Corrected an earlier over-broad fix: grid1/grid2 (the
% ACCELERATOR's own idealized grids) do NOT need to span the whole
% simulation domain width (previously enlarged to 1600x1600mm purely to
% chase the REFLECTRON's ring_outer_r scan). A first shield-tube attempt
% used a CYLINDRICAL shield + graded rings (mimicking the reflectron's
% ring-stack) and hit unresolved geometry issues (boundary-count
% anomalies, residual field leakage). Isolated in a standalone minimal
% test model (test_square_shield_accel.m), a SQUARE shield + square
% annular ring electrodes instead gave clean results: selb_g1/selb_g2
% boundary count=1 (no overlap), on-axis field deviation only +-0.03%
% (vs ~4% for the cylindrical attempt) -- squares suit this short/wide
% (16.83mm gap vs 35mm half-width) geometry much better than cylinders,
% since the accelerator's own repeller is already square (no diagonal
% "corner overshoot" concern the way a circular shield had vs the square
% repeller). Integrated below: a square shield tube (accel_shield_half=
% 35mm) around grid1-grid2, with 5 intermediate graded square ring
% electrodes maintaining field linearity in that gap (the bracket region,
% repeller-grid1, doesn't need rings -- its 3mm gap vs 35mm half-width
% ratio already gave clean uniformity even in the failed cylindrical
% attempt).
p.set('accel_ring_width', sprintf('%.12g[mm]', geometryMm.accelerator_ring_width), ...
    'Accelerator square-ring width from baseline.json');
p.set('accel_shield_wall', sprintf('%.12g[mm]', geometryMm.accelerator_shield_wall), ...
    'Accelerator grounded-shield wall from baseline.json');
p.set('accel_ring_gap', sprintf('%.12g[mm]', geometryMm.accelerator_insulation_gap), ...
    'Charged-electrode-to-ground clearance from baseline.json');
p.set('accel_repeller_thickness', sprintf('%.12g[mm]', geometryMm.accelerator_repeller_thickness), ...
    'Accelerator repeller thickness from baseline.json');
p.set('accel_ring_thickness', sprintf('%.12g[mm]', geometryMm.accelerator_ring_thickness), ...
    'Accelerator extraction-ring thickness from baseline.json');
p.set('accel_ring_bore_half', sprintf('%.12g[mm]', accel_bore_half_mm), 'Accelerator square clear-aperture half-width');
p.set('mesh_hmax_accel', sprintf('%.12g[mm]', mesh_hmax_accel_mm), ...
    'Maximum tetrahedral element size in the whole accelerator region');
p.set('accel_shield_half', 'accel_ring_bore_half+accel_ring_width+accel_ring_gap', 'Derived grounded-shield inner half-width');
% !!! Added for the flight-tube end-cap redesign (doc §7.42, simplified
% per follow-up request): the flight tube (accelflightbox, a cylinder)
% has TWO ends -- the reflectron side (z=L_flight, separated by the
% grounded entgrid, unchanged) and the OTHER end, OPPOSITE the direction
% of acceleration (behind the repeller, NOT on the ion's forward path).
% That other end is now a SOLID CLOSED FULL DISK (grounded, no hole at
% all) -- achieved by first EXTENDING the accelerator's own shield
% (accelshieldO/H) further back to fully wrap the repeller (was flush
% with the repeller's own back face at z=-1, extended by
% accel_shield_back_extra=10mm to z=-11mm), then placing the flight
% tube's end cap even further back still (endcap_gap=3mm past the
% shield's own new back edge) -- since the (now-longer) accelerator
% shield tube ends BEFORE reaching the end cap, nothing needs to pass
% through it, so it can be a plain full disk instead of the earlier,
% more complex annular-plate-with-a-hole design (which was ALSO in the
% wrong place, at z=L_accel, squarely on the ion's forward path --
% corrected here to the true "other end" at the back). L1/L2 (source-
% and detector-side field-free lengths) are entirely unaffected: this
% only adds vacuum/structure BEHIND the accelerator, nothing forward of
% z=0 changes.
p.set('accel_shield_back_extra', sprintf('%.12g[mm]', geometryMm.accelerator_rear_clearance), ...
    'Repeller rear-face clearance from baseline.json');
% !!! Widened from 3mm to 20mm (doc §7.50, per explicit request).
p.set('endcap_gap', sprintf('%.12g[mm]', geometryMm.shield_near_endcap_gap), ...
    'Accelerator shield to near flight-tube end-cap clearance from baseline.json');

accelringtags = oatof_build_accelerator_geometry(geom1);
[ringtags,z_mid_expr] = oatof_build_reflectron_geometry(geom1,n_rings1,n_rings2);
oatof_build_detector_geometry(geom1,geometryMm);
oatof_build_drift_geometry(geom1,sourceDesign,ringtags,accelringtags);
oatof_build_grid_geometry(geom1,z_mid_expr);
geom1.run;
gi = mphgeominfo(model, 'geom1');
fprintf('Geometry built. Ndomains=%d\n', gi.Ndomains);
t_geom = toc(t_geom_start);
fprintf('[TIMING] geometry (param setup + feature creation + geom1.run): %.2fs\n', t_geom);

t_sel_start = tic;
%% Selections
% Solid-domain electrodes (still separate material domains).
soliddoms = [{'repeller','detector','accelshield','flighttubewall','backplate'}, ringtags, accelringtags];
soliddomtags = cellfun(@(t) sprintf('geom1_%s_dom', t), soliddoms, 'UniformOutput', false);
comp1.selection.create('sel_vac', 'Complement');
comp1.selection('sel_vac').label('All vacuum (everything except solid electrodes/rings)');
comp1.selection('sel_vac').set('input', soliddomtags);
vac_n = numel(comp1.selection('sel_vac').entities());
fprintf('sel_vac resolves to %d domain(s)\n', vac_n);

mat_vac = model.material.create('mat_vac', 'Common');
mat_vac.label('Vacuum (relpermittivity=1)');
mat_vac.selection.named('sel_vac');
mat_vac.propertyGroup('def').set('relpermittivity', {'1'});
for t = soliddoms
    matk = model.material.create(sprintf('mat_%s', t{1}), 'Common');
    matk.label(sprintf('%s material', t{1}));
    matk.selection.named(sprintf('geom1_%s_dom', t{1}));
    matk.propertyGroup('def').set('relpermittivity', {'1'});
end

for t = soliddoms
    tagb = sprintf('selb_%s', t{1});
    comp1.selection.create(tagb, 'Adjacent');
    comp1.selection(tagb).label(sprintf('%s boundary', t{1}));
    comp1.selection(tagb).set('input', {sprintf('geom1_%s_dom', t{1})});
end

% !!! SIMPLIFIED: gridA/gridB/accelmid removed, only grid1 (z=3mm) and
% grid2 (z=L_accel=6mm) remain in the accelerator. They're 3mm apart,
% so the standard +-1mm window below gives clean, non-overlapping
% [2,4]mm / [5,7]mm windows -- no need for the old tight +-0.1mm
% special-case table.
% Idealized-grid interior boundaries: Box+'allvertices', NOT
% Cylinder/Box+'intersects' (which can silently grab an unrelated
% boundary that merely passes through the thin selection slab -- see the
% header comment for the exact bug this caused).
% !!! grid1 needs a TIGHTER window (+-0.5mm instead of the standard
% +-1mm): grid1 is at z=3mm, but relvol's own upper boundary sits at
% z=2mm -- a +-1mm window ([2,4]mm) would overlap that edge exactly,
% silently grabbing relvol's boundary too (confirmed: selb_grid1 showed
% boundary count=2 instead of 1, and the "bracket region" field readings
% were garbage/inconsistent as a result). +-0.5mm gives [2.5,3.5]mm,
% safely clear of z=2mm.
% !!! selb_grid2 narrowed from +-1mm to +-0.2mm: after moving the
% detector's near face to L_accel+0.3mm (to align the Mamyrin theory's
% L2 with the field-free boundary, per user request), the old +-1mm
% window ([L_accel-1,L_accel+1]=[18.83,20.83]mm) overlapped the
% detector's near face (20.13mm) -- confirmed via "selb_grid2 boundary
% count: 2" (should be 1). Benign in this case since both grid2 and the
% detector are grounded (0V), so no conflicting potentials resulted, but
% narrowed anyway for structural correctness (same overlap pattern as
% the earlier grid1/relvol bug).
% !!! grid1 xy half-width matched to accel_shield_half (35mm), same as
% its WorkPlane size above. grid2 REVERTED (doc §7.42) to match its own
% small square WorkPlane size (accel_shield_half+accel_shield_wall+
% endcap_gap), now that it only seals the accelerator's own aperture,
% not the whole flight tube. entgrid still uses flight_tube_r+10mm
% (unchanged, still the reflectron-side large shared grid). midgrid's
% selection box half-width is left at flight_tube_r (comfortably larger
% than midgrid's own circular radius, now ring_outer_r -- see the
% gridspecs comment above -- so 'allvertices' still isolates only
% midgrid's own boundary, same as before this radius change).
% !!! Added an explicit x-center column (doc §7.50): grid1/grid2's
% selection boxes were still centered at x=0, but the grids THEMSELVES
% moved to x_accel_center when the whole accelerator assembly was
% shifted off-axis -- without this, the boxes no longer contained the
% (now off-center) grids at all (confirmed: boundary count dropped to 0
% for both, and the accelerator field went completely wrong as a
% result, since the ElectricPotential condition had nothing to act on).
gridsel = {
    'selb_grid1',     'z_accel_grid1'    '0.5[mm]'    'accel_shield_half'                                       'x_accel_center'
    'selb_grid2',     'z_accel_grid2'    '0.05[mm]'   'accel_shield_half+0.01[mm]'    'x_accel_center'
    'selb_entgrid',   'L_flight'         '1[mm]'      'flight_tube_r+10[mm]'                                     '0'
    'selb_midgrid',   z_mid_expr         '1[mm]'      'flight_tube_r'                                            '0'
};
% !!! selb_backplate is NOT listed here: backplate is a real solid again
% (see the geometry feature above), so its boundary selection is created
% automatically by the soliddoms loop below (comp1.selection.create(
% 'selb_backplate','Adjacent',...)), same as repeller/detector/rings --
% listing it here too would create a duplicate/conflicting selection tag.
for gi_ = 1:size(gridsel,1)
    seltag = gridsel{gi_,1};
    zexpr = gridsel{gi_,2};
    zhalf = gridsel{gi_,3};
    xyhalf = gridsel{gi_,4};
    xc = gridsel{gi_,5};
    comp1.selection.create(seltag, 'Box');
    comp1.selection(seltag).label([seltag ' (idealized grid interior boundary)']);
    comp1.selection(seltag).set('xmin', [xc '-(' xyhalf ')']); comp1.selection(seltag).set('xmax', [xc '+' xyhalf]);
    comp1.selection(seltag).set('ymin', ['-(' xyhalf ')']); comp1.selection(seltag).set('ymax', xyhalf);
    comp1.selection(seltag).set('zmin', [zexpr '-' zhalf]); comp1.selection(seltag).set('zmax', [zexpr '+' zhalf]);
    comp1.selection(seltag).set('condition', 'allvertices');
    comp1.selection(seltag).geom('geom1', 2);
    fprintf('%s boundary count: %d\n', seltag, numel(comp1.selection(seltag).entities()));
end

comp1.selection.create('sel_vac_allbnd', 'Adjacent');
comp1.selection('sel_vac_allbnd').label('All vacuum boundaries (before exclusion)');
comp1.selection('sel_vac_allbnd').set('input', {'sel_vac'});
allbnd_ents = comp1.selection('sel_vac_allbnd').entities();
elecbnd_ents = [];
for t = soliddoms
    elecbnd_ents = [elecbnd_ents; comp1.selection(sprintf('selb_%s', t{1})).entities()]; %#ok<AGROW>
end
for gi_ = 1:size(gridsel,1)
    elecbnd_ents = [elecbnd_ents; comp1.selection(gridsel{gi_,1}).entities()]; %#ok<AGROW>
end
elecbnd_ents = unique(elecbnd_ents);
comp1.selection.create('sel_relvol_bnd', 'Adjacent');
comp1.selection('sel_relvol_bnd').label('Release volume boundary (excluded from grounding)');
comp1.selection('sel_relvol_bnd').set('input', {'geom1_relvol_dom'});
relvolbnd_ents = comp1.selection('sel_relvol_bnd').entities();
outerwall_ents = setdiff(allbnd_ents, [elecbnd_ents; relvolbnd_ents]);
fprintf('Outer walls: %d boundary/boundaries found\n', numel(outerwall_ents));
comp1.selection.create('selb_outerwall', 'Explicit');
comp1.selection('selb_outerwall').label('Outer walls (grounded, both physics)');
comp1.selection('selb_outerwall').geom('geom1', 2);
comp1.selection('selb_outerwall').set(outerwall_ents);

%% Electrostatics
% es: reflectron field only (entrance grid 0V, middle grid V_mid, stage1/
% stage2 rings graded, backplate V_mirror; repeller/detector/accelmid/
% grid1 grounded in this solve)
es = comp1.physics.create('es', 'Electrostatics', 'geom1');
es.label('Electrostatics: two-stage ring-stack reflectron (graded field)');
es.selection.named('sel_vac');
% !!! Simplified per explicit request: no time-varying/pulsed field
% needed. The accelerator's electrodes (repeller/grid1) are ALWAYS ON at
% their real target voltages, just like the reflectron's own rings/
% grids -- the ion is released somewhere within this already-static
% parallel field and naturally accelerates from wherever it starts, with
% no "off then suddenly on" timing needed. This is safe for the
% RETURNING ion too: the detector sits just past grid2 (z=L_accel=6mm)
% on the FIELD-FREE FLIGHT-TUBE side -- the ion never needs to re-enter
% the accelerator's field zone (z<L_accel) to reach it, so a static
% (always-on) accelerator field can't trap/decelerate the returning ion
% before detection.
DCmap0 = struct('repeller','V_repeller','detector','0','accelshield','0','flighttubewall','0');
for t = {'repeller','detector','accelshield','flighttubewall'}
    tagb = sprintf('selb_%s', t{1});
    potk = es.create(sprintf('pot_%s', t{1}), 'ElectricPotential', 2);
    potk.label(sprintf('%s DC potential (reflectron solve)', t{1}));
    potk.selection.named(tagb);
    potk.set('V0', DCmap0.(t{1}));
end
% !!! SIMPLIFIED: gridA/gridB/accelmid removed. grid1 (z=3mm) now forms
% the weak bracket field with repeller directly; grid2 (z=L_accel=6mm)
% is the new name for the old "grid1" (accelerator exit, grounded,
% marks the field-free interface).
gridDC0 = struct('grid1','V_grid1','grid2','0','entgrid','0','midgrid','V_mid','backplate','V_mirror');
for t = {'grid1','grid2','entgrid','midgrid','backplate'}
    tagb = sprintf('selb_%s', t{1});
    potk = es.create(sprintf('pot_%s', t{1}), 'ElectricPotential', 2);
    potk.label(sprintf('%s DC potential (reflectron solve)', t{1}));
    potk.selection.named(tagb);
    potk.set('V0', gridDC0.(t{1}));
end
% !!! Intermediate accelerator rings (grid1-grid2 gap), linearly graded
% V_grid1*(1-k/6) for k=1..5 -- same closed-form as the geometry
% z-position spacing above.
for k = 1:5
    tagk = sprintf('accelring_%d', k);
    tagb = sprintf('selb_%s', tagk);
    potk = es.create(sprintf('pot_%s', tagk), 'ElectricPotential', 2);
    potk.label(sprintf('Accelerator ring %d graded potential (V_grid1*(1-%d/6))', k, k));
    potk.selection.named(tagb);
    potk.set('V0', sprintf('V_grid1*(1-%d/6)', k));
end
for k = 1:n_rings1
    tagk = sprintf('ring1_%d', k);
    tagb = sprintf('selb_%s', tagk);
    potk = es.create(sprintf('pot_%s', tagk), 'ElectricPotential', 2);
    potk.label(sprintf('Stage1 ring %d graded potential (%d/6 of V_mid)', k, k));
    potk.selection.named(tagb);
    potk.set('V0', sprintf('%d*V_mid/(N_rings1+1)', k));
end
for k = 1:n_rings2
    tagk = sprintf('ring2_%d', k);
    tagb = sprintf('selb_%s', tagk);
    potk = es.create(sprintf('pot_%s', tagk), 'ElectricPotential', 2);
    potk.label(sprintf('Stage2 ring %d graded potential (V_mid + %d/(N_rings2+1) of remaining)', k, k));
    potk.selection.named(tagb);
    potk.set('V0', sprintf('V_mid+%d*(V_mirror-V_mid)/(N_rings2+1)', k));
end
pot_wall_es = es.create('pot_wall', 'ElectricPotential', 2);
pot_wall_es.label('Outer walls grounded (reflectron solve)');
pot_wall_es.selection.named('selb_outerwall');
pot_wall_es.set('V0', '0');

t_sel = toc(t_sel_start);
fprintf('[TIMING] selections + materials + ES physics (electrode potentials) setup: %.2fs\n', t_sel);

[mesh1,mi,t_mesh] = oatof_build_mesh(model,comp1,p,mesh_hmax_refl_mm,mesh_hmax_accel_mm);

std1 = model.study.create('std1');
std1.label('Stationary: reflectron + accelerator (repeller/grid1/grid2)');
std1.create('stat1', 'Stationary');
model.sol.create('sol1');
model.sol('sol1').label('Solution: ES (reflectron+accelerator)');
model.sol('sol1').study('std1');
model.sol('sol1').createAutoSequence('std1');
% Persist the customized ES solver as the Study's GUI Compute sequence.
% Without attach(), std1.run creates sol3 after reopening the MPH while
% sol2 still references the stale sol1 electrostatic field.
model.sol('sol1').attach('std1');
% !!! GPU (cuDSS) enabled for the electrostatics linear solve, per
% explicit request to fold GPU into the large-particle-count test. Per
% the already-established finding (doc §7.29), this only affects the
% FEM electrostatics solve (independent of particle count) -- COMSOL has
% no GPU path for the CPT particle-tracing step, so this doesn't speed
% up the large-N part below, but is included since it's essentially free
% and doesn't hurt.
if strcmpi(solver_mode, 'gpu')
    model.sol('sol1').feature('s1').feature('dDef').set('linsolver', 'cudss');
else
    model.sol('sol1').feature('s1').feature('dDef').set('linsolver', 'pardiso');
end
t_es_start = tic;
model.sol('sol1').runAll;
t_es = toc(t_es_start);
fprintf('SUCCESS: electrostatics solved (%s, %.2fs).\n', upper(solver_mode), t_es);

%% "Perfect condition" check: is the field-free drift region ACTUALLY
% field-free, and does the accelerator/reflectron reach their IDEAL field
% strength? Now just one static 'es' field (no unit-field combination
% needed), so this simplifies to a direct query.
t_diag_start = tic;
fprintf('\n--- Perfect-condition check: field-free drift region (should be ~0) ---\n');
% !!! Updated (doc §7.50) to trace the ion's REAL x(z) trajectory during
% the field-free forward drift, now that the accelerator (and the ion's
% release point) sits at x_accel_center instead of x=0: x(z) =
% x_accel_center + v_x*(z-L_accel)/v_push_speed, using the established
% transverse speed (v_x=3106.2 m/s) and axial push-direction speed
% (v_push_speed, computed just below) to convert the z-distance traveled
% into elapsed time and then into x-displacement. This replaces the old
% hardcoded '41.2*zc/500' formula (which assumed the ion started at x=0
% and only worked for the pre-§7.50 one-sided placement).
x_accel_center_mm_ffcheck = p.evaluate('x_accel_center','mm');
L_accel_mm = p.evaluate('z_accel_grid2','mm');
v_x_ffcheck = sqrt(2*5*1.602176e-19/(mass_amu*1.66054e-27));
v_push_ffcheck = sqrt(2*2000*1.602176e-19/(mass_amu*1.66054e-27));
zcheck = [25 100 200 300 400 480];
for zc = zcheck
    coord = [x_accel_center_mm_ffcheck + v_x_ffcheck*(zc-L_accel_mm)/v_push_ffcheck; 0; zc];
    Ez = mphinterp(model, 'es.Ez', 'coord', coord, 'dataset', 'dset1', 'matherr', 'off');
    fprintf('  z=%5.0fmm: Ez=%.4f V/m\n', zc, Ez);
end
fprintf('--- Accelerator field check in canonical coordinates: repeller->grid1 target 160 V/mm; grid1->grid2 target 104.76 V/mm ---\n');
% !!! x updated from 0 to x_accel_center (doc §7.50): the whole
% accelerator assembly moved off-axis, so querying at x=0 now probes
% the field-free flight tube (correctly showing ~0), not the
% accelerator's own internal field. Must query at the accelerator's
% OWN axis to see its real internal field.
x_accel_center_mm = p.evaluate('x_accel_center','mm');
z_accel_origin_mm_diag = p.evaluate('z_accel_origin','mm');
for zc = z_accel_origin_mm_diag + [0.2 0.5 1.0 1.5 2.0 2.5 2.8 4 8 12 16 19.5]
    coord = [x_accel_center_mm; 0; zc];
    Ez = mphinterp(model, 'es.Ez', 'coord', coord, 'dataset', 'dset1', 'matherr', 'off');
    fprintf('  z=%5.2fmm: Ez=%.2f V/m\n', zc, Ez);
end

t_diag = toc(t_diag_start);
fprintf('[TIMING] field diagnostic queries (mphinterp x18): %.2fs\n', t_diag);

particle = oatof_configure_particle_model(model,comp1,p,paths,contract,mass_amu,label, ...
    use_fixed_particle_table,fixed_particle_table,n_particles,field_mode, ...
    fine_tstep_ns,drift_tstep_ns,solver_mode);
cpt = particle.cpt; rel1 = particle.rel1; tstep = particle.tstep;
Ez_accel_ideal = particle.Ez_accel_ideal; Ez_drift_ideal = particle.Ez_drift_ideal;
Ez_stage1_ideal = particle.Ez_stage1_ideal; Ez_stage2_ideal = particle.Ez_stage2_ideal;
Tsim = particle.Tsim; Tsim_full = particle.Tsim_full; timing = particle.timing;
expected_tof = particle.expected_tof; fine_tstep = particle.fine_tstep;
fine_end = particle.fine_end; t_cptsetup = particle.t_cptsetup;
t_cpt_start = tic;
model.sol('sol2').runAll;
t_cpt = toc(t_cpt_start);
fprintf('[%s] SUCCESS: oa-TOF ring-stack CPT solved (%s, %.2fs for N=%s particles, Tsim=%.4gus short margin).\n', ...
    label, upper(solver_mode), t_cpt, num2str(n_particles), Tsim*1e6);

% Two-phase completeness check (doc §6.14): confirm all released particles
% actually reached the detector within the short margin; if not, extend to
% the full 8x margin and re-solve from scratch. qz is already in
% geom1.lengthUnit ('mm'), NOT SI meters -- do not rescale (this bit us
% once during development: rescaling qz by 1e3 on top of an already-mm
% value caused a false "0/N detected" and an unnecessary retry every time).
pdset_check = model.result.dataset.create('pdset_check', 'Particle');
pdset_check.set('solution', 'sol2');
N_total_check = n_particles;
% Only the final position is needed here.  Without an explicit `t`,
% mphparticle returns every stored time step; at sub-nanosecond output
% spacing that unnecessary payload can exhaust the MATLAB client JVM.
qzcheck = mphparticle(model, 'dataset', 'pdset_check', 'expr', {'qz'}, ...
    't', Tsim, 'dataonly', 'on');
zfinal_check = qzcheck.d1(end,:);
detector_z_val_mm = mphevaluate(model, 'detector_z', 'mm');
n_detected_check = sum(abs(zfinal_check - detector_z_val_mm) < 2);
fprintf('[%s] two-phase check: %d/%d particles reached detector (z=%.4gmm) within short margin.\n', ...
    label, n_detected_check, N_total_check, detector_z_val_mm);
if n_detected_check < N_total_check
    fprintf('[%s] short margin insufficient -- re-solving with full 8x margin (Tsim=%.4gus).\n', label, Tsim_full*1e6);
    Tsim = Tsim_full;
    p.set('cpt_t_end', sprintf('%.12g[s]', Tsim), ...
        'Extended GUI-visible end time after completeness gate retry');
    tstep.set('tlist', timing.tlist);
    t_cpt_retry_start = tic;
    model.sol('sol2').runAll;
    t_cpt_retry = toc(t_cpt_retry_start);
    fprintf('[%s] full-margin retry took an extra %.2fs (total CPT solve time now %.2fs).\n', label, t_cpt_retry, t_cpt + t_cpt_retry);
    t_cpt = t_cpt + t_cpt_retry;
end

t_extract_start = tic;
pdset1 = model.result.dataset.create('pdset1', 'Particle');
pdset1.label(sprintf('Particle dataset: oa-TOF ring-stack %s', label));
pdset1.set('solution', 'sol2');

% COMSOL 6.4 documents that dataonly='on' suppresses the default p/v
% trajectory payload and that the `t` property limits evaluation to an
% explicit time vector.  Both are required here: requesting every stored
% time at sub-nanosecond spacing can exhaust the client JVM even for N=100.
% Keep a sparse whole-flight trace for penetration/plot diagnostics and the
% exact fine output spacing in a generous window around the expected return.
% The latter preserves detector-crossing interpolation and therefore the
% direct FWHM, while omitting output points irrelevant to detector arrival.
arrival_half_window = 200e-9;
arrival_times = (expected_tof-arrival_half_window):fine_tstep: ...
    (expected_tof+arrival_half_window);
trajectory_times = linspace(0, Tsim, 2001);
extract_times = unique([trajectory_times, arrival_times, Tsim]);
pd_z = mphparticle(model, 'dataset', 'pdset1', ...
    'expr', {'qx','qy','qz'}, 't', extract_times, 'dataonly', 'on');
t = pd_z.t;
z = squeeze(pd_z.d3);
% !!! Per explicit speed-optimization request: also keep x/y here (were
% previously discarded -- only z was extracted from this same pd_z.p
% array) so the trajectory-plot section below can reuse this ALREADY-
% SOLVED data instead of re-running the entire CPT solve a second time
% just to get x/y. See the trajectory-plot section for why a second
% solve is still needed when nP is large.
x_full = squeeze(pd_z.d1);
y_full = squeeze(pd_z.d2);
nP = size(z,2);
fprintf('[%s] ions released: %d\n', label, nP);

zEnd = z(end,:);
zmax = max(z,[],1);
fprintf('[%s] z_max reached: %.2fmm (entrance grid at %gmm, backplate at %gmm)\n', label, max(zmax), p.evaluate('L_flight','mm'), p.evaluate('L_flight','mm')+p.evaluate('L_refl','mm'));
fprintf('[%s] final z: mean=%.3fmm\n', label, mean(zEnd,'omitnan'));

% --- Verify the deepest ACTUAL penetration INTO STAGE 2 ONLY (over all
% nP simulated ions) matches the corrected THEORETICAL d2_min=(U0-U1)/E2
% (doc §7.51 -- the depth at which the ion's remaining axial KE after
% stage1, q(U0-U1), reaches exactly zero under field E2). Stage2 begins
% at the mid-grid, z=L_flight+d1_mm (NOT at the entrance grid), so the
% comparison must subtract d1_mm from the total penetration depth first.
L_flight_mm_pen = p.evaluate('L_flight','mm');
penetration_total_mm = zmax - L_flight_mm_pen; % per-ion depth past the entrance grid (stage1+stage2)
penetration_stage2_mm = penetration_total_mm - d1_mm; % per-ion depth past the MID grid (stage2 only)
penetration_max_mm = max(penetration_total_mm);
penetration_stage2_max_mm = max(penetration_stage2_mm);
fprintf('[%s] reflectron penetration: total max=%.3fmm, stage2-only max=%.3fmm, over %d ions (theory d2_min=(U0-U1)/E2=%.3fmm, adaptive d2=%.3fmm [+%.0f%% margin])\n', ...
    label, penetration_max_mm, penetration_stage2_max_mm, nP, reflectron_stage2_min_mm, d2_mm, d2_margin_fraction*100);
fprintf('[%s] stage2 penetration_max vs d2_min: diff=%.3fmm (%.2f%% of d2_min)\n', ...
    label, penetration_stage2_max_mm-reflectron_stage2_min_mm, ...
    100*(penetration_stage2_max_mm-reflectron_stage2_min_mm)/reflectron_stage2_min_mm);

% !!! Detection logic simplified to z-only (no x,y window check): this
% was already validated earlier in this project to give IDENTICAL
% results to the windowed check for this design (100% detection either
% way) -- the windowed check was only ever needed to rule out spatial
% miscalibration, not because it changes the physics.
% !!! Detection z-threshold now computed dynamically from the
% 'detector_z' parameter (was a bare hardcoded 20.5, which only matched
% by coincidence when the detector sat at L_accel+0.3mm=20.13mm -- a
% latent bug that would silently break detection for any detector
% reposition, e.g. the L1/L2 asymmetry test in §7.41). Using
% detector_z+0.5mm as the crossing threshold (0.5mm past the detector's
% own z, matching the same "just past the physical position" margin
% the old 20.5 vs 20.13 relationship had). The "wasUp" check (has the
% ion definitely passed deep into the flight tube/reflectron before
% counting a later downward crossing as the real detection) uses
% detector_z*2 as a generous, geometry-relative "definitely past
% halfway" marker instead of the old hardcoded 400.
% !!! Detection logic updated (doc §7.48): the detector was moved to
% the ion's ACTUAL x-position (94.93mm), so it now physically sits IN
% the ion's real return path -- unlike before (parked at x=420mm, purely
% a time-marker never actually touched), the ion now genuinely collides
% with detector's solid material and CPT stops tracking it there (its
% z-trajectory freezes at the collision point rather than continuing
% past the old z-threshold). The old logic only recognized a clean
% downward CROSSING of det_z_thresh -- a frozen trajectory that never
% actually crosses (stops just short of the threshold) went undetected
% (confirmed: 0/100 with the old logic after the detector's reposition).
% Now recognizes EITHER a clean crossing (kept for robustness/backward
% compatibility) OR the trajectory ending (freezing) within
% det_freeze_tol of the detector's own z -- the latter is the actual
% physical-collision case that now applies.
det_z_thresh = p.evaluate('detector_z','mm') + 0.5;
det_freeze_tol = 2; % mm, how close the frozen final z must be to detector_z
% !!! Per explicit request: analyzed "shrink the tlist step further" vs
% "interpolate between existing samples" as two ways to fix the
% mass-spectrum histogram showing 3-4 separated peaks instead of one
% smooth peak -- root cause was detTimes snapping to the DISCRETE tlist
% output grid (1ns steps in the fine 6-39us window) via `t(k)`, and the
% true timing jitter (std~0.7-0.85ns) is comparable to that 1ns step, so
% many particles' true arrival times collapsed onto the same handful of
% grid points. Interpolation wins on both counts: shrinking the tlist
% step (e.g. 10x, to 0.1ns) would multiply the CPT solve's dominant cost
% (output point count, see doc §6.16/the "CPT solve cost is dominated by
% tlist output points" finding) for a problem that 'tstepsbdf'='free'
% already doesn't need finer OUTPUT sampling to solve accurately -- the
% already-computed trajectory between two adjacent 1ns samples is
% already accurate, interpolating it costs nothing extra and removes the
% quantization entirely instead of just shrinking it. detector_z_exact
% (the real physical detector surface position) is the interpolation
% target, computed once here.
detector_z_exact = p.evaluate('detector_z','mm');
detTimes = nan(1,nP);
for i = 1:nP
    zi = z(:,i);
    lastValid = find(isfinite(zi), 1, 'last');
    if isempty(lastValid), continue; end
    [~, turnIdx] = max(zi(1:lastValid));
    detected = false;
    % The physical detector event is the first downward crossing after
    % the trajectory's maximum-z turning point.  This definition is
    % invariant under any rigid global-coordinate translation and cannot
    % confuse the outbound accelerator pass with the return detection.
    for k = turnIdx+1:lastValid
        if zi(k) < det_z_thresh
            detTimes(i) = interp_crossing_time(t, zi, k, detector_z_exact);
            detected = true;
            break;
        end
    end
    if ~detected
        % Trajectory never cleanly crossed det_z_thresh -- COMSOL
        % doesn't set z to NaN after a physical collision, it FREEZES
        % the last valid position for all remaining timesteps (confirmed
        % by a first attempt using find(~isnan(...),1,'last'), which
        % just grabbed the very last simulated timestep of the ENTIRE
        % run for every particle -- meanT=284us, std=0.0000, obviously
        % wrong). Search only from wasUpIdx onward (the ion ALSO passes
        % near z=detector_z much earlier, right after leaving the
        % accelerator on its way OUT -- searching the whole trajectory
        % would wrongly grab that early forward pass instead of the
        % later return-and-collide event) for the first timestep where z
        % has already reached near the detector (the actual moment of
        % collision, not the tail end of the frozen plateau).
        near_det = find(abs(zi(turnIdx:end) - detector_z_exact) < det_freeze_tol, 1, 'first');
        if ~isempty(near_det)
            k2 = turnIdx + near_det - 1;
            detTimes(i) = interp_crossing_time(t, zi, k2, detector_z_exact);
        end
    end
end
meanT = mean(detTimes,'omitnan'); stdT = std(detTimes,'omitnan');
nDet = sum(~isnan(detTimes));
fprintf('[%s] detected on detector plate: %d/%d, arrival time: mean=%.5fus, std=%.5fus\n', label, nDet, nP, meanT*1e6, stdT*1e6);
% Parameter-link gate: actual events must remain safely inside the predicted
% fine windows. This catches future mass/voltage/length/source changes that
% invalidate the one-dimensional reference formulas instead of silently
% degrading resolution in a coarse output segment.
L_accel_gate_mm = p.evaluate('z_accel_grid2', 'mm');
L_flight_gate_mm = p.evaluate('L_flight', 'mm');
t_accel_gate = nan(1,nP);
t_refl_entry_gate = nan(1,nP);
t_refl_exit_gate = nan(1,nP);
for i = 1:nP
    zi = z(:,i);
    accel_idx = find(zi >= L_accel_gate_mm, 1, 'first');
    refl_entry_idx = find(zi >= L_flight_gate_mm, 1, 'first');
    [~, turn_idx] = max(zi);
    refl_exit_rel = find(zi(turn_idx:end) <= L_flight_gate_mm, 1, 'first');
    if ~isempty(accel_idx), t_accel_gate(i) = t(accel_idx); end
    if ~isempty(refl_entry_idx), t_refl_entry_gate(i) = t(refl_entry_idx); end
    if ~isempty(refl_exit_rel)
        t_refl_exit_gate(i) = t(turn_idx+refl_exit_rel-1);
    end
end
assert(all(isfinite(t_accel_gate)) && all(isfinite(t_refl_entry_gate)) && ...
    all(isfinite(t_refl_exit_gate)) && nDet == nP, ...
    'Event-window gate could not identify every accelerator/reflectron/detector event.');
assert(max(t_accel_gate) < timing.t_accel_end_s-0.1e-6, ...
    'Accelerator exit is too close to/outside the fine-window end.');
assert(min(t_refl_entry_gate) > timing.t_refl_start_s+0.25e-6, ...
    'Reflectron entry is too close to/outside the fine-window start.');
assert(max(t_refl_exit_gate) < timing.t_refl_end_s-0.25e-6, ...
    'Reflectron return exit is too close to/outside the fine-window end.');
assert(min(detTimes) > timing.t_detector_start_s+0.1e-6 && ...
    max(detTimes) < timing.t_detector_end_s-0.1e-6, ...
    'Detector arrivals are too close to/outside the fine detector window.');
fprintf(['[%s] event-window gate PASS: accel exit <=%.4fus; reflectron ' ...
    'entry %.4f-%.4fus, exit %.4f-%.4fus; detector %.4f-%.4fus.\n'], ...
    label, max(t_accel_gate)*1e6, min(t_refl_entry_gate)*1e6, ...
    max(t_refl_entry_gate)*1e6, min(t_refl_exit_gate)*1e6, ...
    max(t_refl_exit_gate)*1e6, min(detTimes)*1e6, max(detTimes)*1e6);
% Unified mass resolving-power convention (2026-07-15): R=m/FWHM_m.
% Since m is proportional to t^2, the narrow-peak TOF-equivalent form is
% R=t/(2*FWHM_t), with FWHM_t=2*sqrt(2*ln(2))*sample_std(t).
fwhm_factor = 2*sqrt(2*log(2));
fwhmT = fwhm_factor*stdT;
R_resolution = meanT/(2*fwhmT);
fprintf('[%s] arrival-time FWHM = %.6f ns (2*sqrt(2*ln(2))*sigma)\n', label, fwhmT*1e9);
fprintf('[%s] mass resolution R_FWHM=m/FWHM_m=t/(2*FWHM_t) = %.1f\n', label, R_resolution);

% !!! Safety check for the "fix B" adaptive fine_end window (per explicit
% speed-optimization request): if any detected ion's arrival landed close
% to fine_end, its recorded timestamp may have snapped to the COARSE
% (500ns) post-window grid instead of the fine 1ns grid, silently adding
% quantization noise to that ion's timing precision. Warn loudly rather
% than let a future scan (different d1/mass/margin) silently lose
% precision on its slowest ions.
if nDet > 0
    latest_det = max(detTimes, [], 'omitnan');
    margin_to_fine_end = fine_end - latest_det;
    if margin_to_fine_end < 2e-6
        fprintf('[%s] !!! WARNING: latest detection (%.3fus) is within %.3fus of fine_end (%.3fus) -- the adaptive tlist fine window may be too tight for this parameter combination, some ions'' timing precision may be degraded. Consider raising the 2.5x margin factor on fine_end.\n', ...
            label, latest_det*1e6, margin_to_fine_end*1e6, fine_end*1e6);
    end
end

% !!! Diagnostic: is the residual timing spread actually explained by
% z0 (hence KE, hence the Mamyrin/accelerator theory)? Must run BEFORE
% the N_plot re-solve below overwrites sol2's full-population data.
z0_diag = z(1,:);
valid_diag = ~isnan(detTimes);
if sum(valid_diag) > 10
    cc = corrcoef(z0_diag(valid_diag), detTimes(valid_diag));
    fprintf('[%s] DIAG corr(z0,detTime) = %.6f\n', label, cc(1,2));
    p1d = polyfit(z0_diag(valid_diag), detTimes(valid_diag), 1);
    resid1 = detTimes(valid_diag) - polyval(p1d, z0_diag(valid_diag));
    p2d = polyfit(z0_diag(valid_diag), detTimes(valid_diag), 2);
    resid2 = detTimes(valid_diag) - polyval(p2d, z0_diag(valid_diag));
    fprintf('[%s] DIAG std(detTime)=%.4fns, std(resid after linear z0 fit)=%.4fns, std(resid after quadratic)=%.4fns\n', ...
        label, std(detTimes(valid_diag))*1e9, std(resid1)*1e9, std(resid2)*1e9);
end
t_extract = toc(t_extract_start);
fprintf('[TIMING] full-population extraction (mphparticle N=%d) + detection/R/DIAG post-processing: %.2fs\n', nP, t_extract);

result = struct('label', label, 'mass_amu', mass_amu, 'nP', nP, 'zEnd', zEnd, ...
    'detTimes', detTimes, 'meanT', meanT, 'stdT', stdT, 'fwhmT', fwhmT, ...
    'R_fwhm_sigma_proxy', R_resolution, 'nDet', nDet, ...
    'penetration_max_mm', penetration_max_mm, ...
    'd2min_mm', reflectron_stage2_min_mm, 'd2_mm', d2_mm, ...
    'field_idealization', particle.field_idealization);

resultsDir = getenv('OATOF_RESULTS_DIR');
if isempty(resultsDir)
    if strcmpi(strtrim(label), 'Final')
        resultsDir = fullfile(paths.formalRoot, 'results');
    elseif ~isempty(output_model_path)
        modelDir = fileparts(char(output_model_path));
        resultsDir = fullfile(fileparts(modelDir), 'results');
    else
        error('OATOF_RESULTS_DIR or OutputModelPath is required for non-formal runs.');
    end
end
if ~exist(resultsDir,'dir'), mkdir(resultsDir); end

% !!! Speed optimization (per explicit request, "fix A"): the trajectory
% plot only needs x/y/z for a small subset of particles -- previously
% this was ALWAYS obtained by changing rel1's N and re-running the ENTIRE
% CPT time-dependent solve a SECOND time, discarding the first solve's
% own x/y data (only z was ever extracted from it) purely to get x/y back
% for a smaller N. Measured cost: this redundant second solve took
% 137.95s (42.5% of total wall time), MORE than the original N=100 solve
% itself (126.89s) -- CPT solve cost is dominated by the number of
% forced tlist output points, not particle count, so a smaller N barely
% saves anything here while paying the full solve cost again.
% Fix: when nP is small enough that x_full/y_full/z (already fully
% extracted above from the FIRST solve's pd_z) comfortably fit in memory,
% just take the first N_plot columns of that ALREADY-COMPUTED data --
% zero additional solving, and R/statistics are completely unaffected
% either way since they only ever used the first solve's data. Only fall
% back to a genuine second small-N re-solve when nP is large enough that
% holding the FULL trajectory array for plotting purposes would be a real
% memory concern (the original justification for this re-solve, per the
% comment history) -- that threshold is set well above the project's
% typical N=100-1000 exploratory runs, only kicking in for the large-N
% (5000-10000) statistical-confirmation runs mentioned throughout this
% project's docs.
t_replot_start = tic;
PLOT_RESOLVE_THRESHOLD = 2000; % particles; above this, re-solve at small N to cap MATLAB memory
if nP > PLOT_RESOLVE_THRESHOLD
    % --- Small dedicated re-solve (N_plot particles) for full 3D
    % trajectories, reusing the same static 'es' field -- keeps memory
    % bounded when the statistics population itself is large.
    N_plot = min(50, nP);
    rel1.set('N', num2str(N_plot));
    model.sol('sol2').runAll;
    pdset_plot = model.result.dataset.create('pdset_plot', 'Particle');
    pdset_plot.label(sprintf('Particle dataset (plot subset, N=%d): %s', N_plot, label));
    pdset_plot.set('solution', 'sol2');
    pd_plot = mphparticle(model, 'dataset', 'pdset_plot');
    t_plot = pd_plot.t;
    x_plot = squeeze(pd_plot.p(:,:,1)); y_plot = squeeze(pd_plot.p(:,:,2)); z_plot = squeeze(pd_plot.p(:,:,3));
    nP_plot = size(x_plot,2);
    plot_dataset_tag = 'pdset_plot';
    fprintf('[%s] trajectory-plot subset solved (nP=%d > threshold=%d): N_plot=%d\n', label, nP, PLOT_RESOLVE_THRESHOLD, nP_plot);
else
    % Reuse the FIRST solve's already-extracted x_full/y_full/z directly
    % -- no second CPT solve, no second mphparticle call.
    nP_plot = min(50, nP);
    t_plot = t;
    x_plot = x_full(:,1:nP_plot); y_plot = y_full(:,1:nP_plot); z_plot = z(:,1:nP_plot);
    plot_dataset_tag = 'pdset1';
    fprintf('[%s] trajectory-plot subset REUSED from full-population solve (nP=%d <= threshold=%d, no re-solve): N_plot=%d\n', label, nP, PLOT_RESOLVE_THRESHOLD, nP_plot);
end
t_replot = toc(t_replot_start);
fprintf('[TIMING] trajectory-plot data acquisition (re-solve or reuse): %.2fs\n', t_replot);

t_matlabplot_start = tic;
fh = figure('Visible','off');
subplot(1,3,1);
hold on;
for i = 1:nP_plot
    plot(x_plot(:,i), z_plot(:,i), '-');
end
xlabel('x [mm]'); ylabel('z [mm]'); grid on;
title(sprintf('ion trajectory (N=%d subset): x vs z', nP_plot));
subplot(1,3,2);
hold on;
for i = 1:nP_plot
    plot(t_plot*1e6, z_plot(:,i), '-');
end
xlabel('t [\mus]'); ylabel('z [mm]'); grid on;
title('z position vs time');

% --- Intensity vs apparent-mass curve: since t (TOF) scales as
% sqrt(mass) at fixed accelerating voltage, each detected ion's arrival
% time maps to an "apparent mass" m_app = mass_amu*(t/meanT)^2. A
% histogram of m_app over all DETECTED ions (from the full nP
% population, not just the N_plot subset) is the mass-spectrum peak
% this design would produce for a single-mass ion population -- its
% width directly visualizes the resolution R computed above.
subplot(1,3,3);
detected_t = detTimes(~isnan(detTimes));
assert(~isempty(detected_t), ...
    'No detector hits are available for mass-spectrum/FWHM analysis.');
detected_t = double(detected_t(:));
m_app = double(mass_amu*(detected_t./meanT).^2);
m_app = m_app(:);
mass_sigma = std(m_app);
mass_min = min(m_app);
mass_max = max(m_app);
mass_span = mass_max - mass_min;
mass_padding = double(max([0.20*mass_span; 4*mass_sigma; 1e-6]));
assert(isscalar(mass_min) && isscalar(mass_max) && isscalar(mass_padding), ...
    'Mass-spectrum bounds must be scalar (sizes: min=%s max=%s padding=%s).', ...
    mat2str(size(mass_min)), mat2str(size(mass_max)), mat2str(size(mass_padding)));
mass_grid = linspace(mass_min-mass_padding, mass_max+mass_padding, 1001);
mass_bandwidth = max(1.06*mass_sigma*numel(m_app)^(-1/5), 1e-6);
mass_density = mean(exp(-0.5*((mass_grid(:)-m_app(:).')/mass_bandwidth).^2), 2) ./ (sqrt(2*pi)*mass_bandwidth);
mass_intensity = mass_density * numel(m_app) * mean(diff(mass_grid));
peak_index = find(mass_intensity == max(mass_intensity), 1, 'first');
half_max = mass_intensity(peak_index)/2;
left_index = find(mass_intensity(1:peak_index) < half_max, 1, 'last');
right_offset = find(mass_intensity(peak_index:end) < half_max, 1, 'first');
assert(~isempty(left_index) && ~isempty(right_offset), 'Direct FWHM could not be bracketed on mass grid.');
right_index = peak_index + right_offset - 1;
left_mass = interp1(mass_intensity(left_index:left_index+1), mass_grid(left_index:left_index+1), half_max, 'linear');
right_mass = interp1(mass_intensity(right_index-1:right_index), mass_grid(right_index-1:right_index), half_max, 'linear');
mass_fwhm_direct = right_mass - left_mass;
R_direct = mass_amu/mass_fwhm_direct;
fprintf('[%s] direct KDE mass FWHM = %.9g Da; R=m/FWHM_m = %.6g\n', label, mass_fwhm_direct, R_direct);
result.mass_fwhm_direct_Da = mass_fwhm_direct;
result.R_fwhm_direct = R_direct;
plot(mass_grid, mass_intensity, '-');
xlabel('apparent mass [Da]'); ylabel('intensity [counts]'); grid on;
title(sprintf('mass peak (direct FWHM R=%.0f, N=%d)', R_direct, nDet));

% !!! Title now includes N (statistical sample size, nP -- NOT the N_plot=50
% trajectory-rendering subset) and field_mode, per doc convention (always
% show sample size so a reader can't mistake an N=100 result for N=1000,
% see COMSOL_调试方法�?md 统计陷阱一�?. Also dropped the hardcoded
% "V_mirror=4551.15V" that was stale (V_mirror is now computed dynamically
% per d1_mm/d2_margin_frac and no longer a fixed literal) in favor of the
% actual computed value.
sgtitle({sprintf('oa-TOF two-stage ring-stack reflectron: %s (N=%d, field_mode=%s)', label, nP, field_mode), ...
    sprintf('%gamu +1 ion, baseline source when selected, d1=%gmm, V_mirror=%.2fV, direct R=%.1f', ...
    mass_amu, d1_mm, reflectron_backplate_voltage_v, R_direct)}, 'Interpreter','none');
print(fh, fullfile(resultsDir, sprintf('ms_oaTOF_ringstack_reflectron_%s.png', strrep(label,' ','_'))), '-dpng', '-r150');
fprintf('[%s] SUCCESS: trajectory + mass-spectrum plot saved.\n', label);
t_matlabplot = toc(t_matlabplot_start);
fprintf('[TIMING] MATLAB figure (trajectory+mass-spectrum PNG): %.2fs\n', t_matlabplot);

% !!! Native in-model field diagnostics are deliberately limited to FIVE
% plots: (1) signed-log full-domain Ez, (2) signed-log full-domain
% real-ideal Ez, (3) log residual |E| in the nominally field-free drift,
% (4) real-ideal Ez versus z at five radii, and (5) real-ideal Ez versus
% radius at five ion-accessible z positions inside the reflectron. The
% apparent-mass spectrum remains a separate result plot. All are wrapped
% in try/catch because visualization is not required for the core solve.
% !!! CutPlane dataset API validated empirically against a live COMSOL
% session before use here (a throwaway test model, not guessed from
% memory): 'quickplane'/'quicky' are the correct property names for a
% CutPlane DATASET -- 'quickynumber' (used by the Slice PLOT FEATURE
% inside a 3D scene, which is a different thing) errors with "Unknown
% property" on a CutPlane dataset. One shared y=0 CutPlane dataset feeds
% all three heatmaps below (same physical cross-section, equivalent to an r-z
% profile for this axisymmetric-like ring-stack since x=r for x>0 and the
% mirror x<0 side reflects the same profile) -- only the Surface plot's
% expr differs between the two.
t_resultplots = oatof_create_result_nodes(model,p,label,Ez_accel_ideal,Ez_drift_ideal, ...
    Ez_stage1_ideal,Ez_stage2_ideal,R_resolution,nDet,mass_bandwidth,mass_grid,mass_intensity);

t_save1_start = tic;
pg1 = model.result.create('pg_traj', 'PlotGroup3D');
pg1.label(sprintf('oa-TOF (ring-stack): %s trajectory', label));
pg1.set('data', plot_dataset_tag);
pg1.set('titletype', 'manual');
pg1.set('title', sprintf('Orthogonal accelerator + ring-stack reflectron: %gamu +1 ion', mass_amu));
trj1 = pg1.create('trj1', 'ParticleTrajectories');
trj1.label('oa-TOF ion trajectory (ring-stack reflectron)');
col_time = trj1.create('col_time', 'Color');
col_time.set('expr', 't');
col_time.set('descr', 'Time');
col_time.set('unit', 's');
col_time.set('colortable', 'Thermal');
col_time.set('colorlegend', 'on');

% !!! Reordered (per repeated crash pattern this session): the native
% 3D trajectory rendering (pg1.run) has repeatedly crashed MATLAB/COMSOL
% AFTER the CPT solve completed but BEFORE model.save() was reached,
% losing an otherwise-valid, already-computed result. Model is now saved
% FIRST (guaranteeing the result survives even if the plot rendering
% crashes), and the plot is attempted afterward as a best-effort step.
if ~isempty(output_model_path)
    modelPath = char(output_model_path);
    modelsDir = fileparts(modelPath);
else
    if strcmpi(strtrim(label), 'Final')
        modelsDir = paths.comsolFormalDir;
    else
        error('OutputModelPath is required for every non-formal run.');
    end
    modelPath = fullfile(modelsDir, 'oa_tof__model.mph');
end
if ~exist(modelsDir, 'dir'), mkdir(modelsDir); end
model.save(modelPath);
result.model_path = modelPath;
t_save1 = toc(t_save1_start);
fprintf('[%s] SUCCESS: model saved.\n', label);
fprintf('[TIMING] first model.save (.mph write): %.2fs\n', t_save1);
t_native_start = tic;
% pg1.run mutates the stored particle solution to the plot subset in
% batch mode. Keep the N-statistics solution intact; Desktop renders this
% already-configured plot group on demand.
t_native = toc(t_native_start);
fprintf('[%s] native trajectory plot configured for GUI rendering; batch render skipped to preserve N=%d statistics solution.\n', label, nP);

t_total = toc(t_total_start);
fprintf('\n===== [TIMING SUMMARY: %s, N=%d] =====\n', label, nP);
phase_names = {'geometry (params+features+geom1.run)', ...
    'selections+materials+ES physics setup', 'mesh (mesh1.run+mphmeshstats)', ...
    'electrostatics solve (sol1)', 'field diagnostic queries', ...
    'CPT setup (before solve)', sprintf('CPT solve (N=%d, statistics population)', nP), ...
    'full-population extraction+post-processing', sprintf('trajectory-plot data (N=%d, reuse or re-solve)', nP_plot), ...
    'MATLAB figure (PNG)', 'native Result plots (field diag+mass spectrum table)', ...
    'first model.save', 'native 3D plot (pg1.run)+re-save'};
phase_times = [t_geom, t_sel, t_mesh, t_es, t_diag, t_cptsetup, t_cpt, t_extract, t_replot, t_matlabplot, t_resultplots, t_save1, t_native];
for pi_ = 1:numel(phase_names)
    fprintf('  %-45s %8.2fs  (%5.1f%%)\n', phase_names{pi_}, phase_times(pi_), 100*phase_times(pi_)/t_total);
end
fprintf('  %-45s %8.2fs\n', 'SUM OF PHASES', sum(phase_times));
fprintf('  %-45s %8.2fs\n', 'TOTAL (t_total_start to here)', t_total);
fprintf('=====================================================\n');
end

% !!! Local helper (per explicit request): sub-nanosecond-precision
% arrival-time interpolation, replacing the old "just take t(k)" snap-to-
% grid that quantized detTimes to the tlist's 1ns output spacing (see the
% detTimes computation above for the full analysis of why interpolation,
% not a finer tlist, is the right fix). Given the sample AT index k
% (zi(k), t(k)) and its immediate predecessor (zi(k-1), t(k-1)) -- which
% brackets or closely neighbors the target z, since k was found via a
% threshold/tolerance check on zi(k) itself -- linearly interpolates (or,
% if the target lies just beyond the (k-1,k) pair, extrapolates) for the
% time at which z would equal target. Valid because the underlying
% trajectory is already solved accurately between adjacent output
% samples ('tstepsbdf'='free' decouples solver accuracy from the output
% tlist's density), so a local straight-line fit over a ~1ns gap is an
% excellent approximation of the true continuous crossing time. Falls
% back to the raw t(k) if k=1 (no predecessor) or the two samples have
% identical z (would divide by zero -- e.g. already deep in a frozen
% plateau).
function tc = interp_crossing_time(t, zi, k, target)
if k > 1 && zi(k-1) ~= zi(k)
    frac = (target - zi(k-1)) / (zi(k) - zi(k-1));
    tc = t(k-1) + frac*(t(k) - t(k-1));
else
    tc = t(k);
end
end
