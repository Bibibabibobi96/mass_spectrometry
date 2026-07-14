function result = ms_oaTOF_two_stage_ringstack_reflectron(mass_amu, label, solver_mode, field_mode, d1_mm, n_rings2, mesh_hmax_refl_mm, bore_r_mm, ring_thickness_mm, n_particles, n_rings1)
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
    d1_mm = 120;
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
    n_rings2 = 5;
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
    mesh_hmax_refl_mm = 15;
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
    bore_r_mm = 250;
end
% !!! ring_thickness_mm (per explicit request to scan ring electrode
% thickness alongside ring count, to test whether thicker/more numerous
% stage2 rings close the real-vs-ideal field gap identified via
% field_mode='ideal_stage2'): optional 9th argument, defaults to the
% established 5mm baseline. Previously a hardcoded literal.
if nargin < 9 || isempty(ring_thickness_mm)
    ring_thickness_mm = 5;
end
if nargin < 10 || isempty(n_particles)
    n_particles = 1000;
end
% !!! n_rings1 is the stage-1 ring count (11th optional argument).  It is
% kept after n_particles for backward compatibility with the established
% ten-argument signature; n_rings2 remains the 6th argument.
if nargin < 11 || isempty(n_rings1)
    n_rings1 = 10;
end
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
d2_margin_frac = 1.0;
U0_eV = 2000; L_total_m = 1.2; d1_m = d1_mm/1000;
if ~(d1_m > 0 && d1_m < L_total_m/4)
    error('d1_mm=%g violates 0<d1<L/4=%gmm', d1_mm, L_total_m/4*1000);
end
U1_V = 2*U0_eV*(L_total_m+2*d1_m)/(3*L_total_m);
E1_Vpm = U1_V/d1_m;
E2_Vpm = 12*U0_eV*(sqrt(3)*sqrt(L_total_m)+sqrt(L_total_m-4*d1_m)) / ...
    (sqrt(3)*L_total_m^1.5 + 8*sqrt(3)*sqrt(L_total_m)*d1_m + 3*L_total_m*sqrt(L_total_m-4*d1_m));
d2min_mm = ((U0_eV-U1_V)/E2_Vpm)*1000;
d2_mm = d2min_mm*(1+d2_margin_frac);
V_mirror_V = U1_V + E2_Vpm*(d2_mm/1000);
fprintf('[d1 scan] d1=%gmm -> U1(V_mid)=%.4fV, E1=%.4fV/m, E2=%.4fV/m, V_mirror=%.4fV, d2_min=%.2fmm, d2(adaptive,+%.0f%%)=%.2fmm\n', ...
    d1_mm, U1_V, E1_Vpm, E2_Vpm, V_mirror_V, d2min_mm, d2_margin_frac*100, d2_mm);
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
componentRoot = fileparts(fileparts(mfilename('fullpath')));
addpath(componentRoot);
paths = oatof_paths();
addpath('D:\COMSOL 6.4\COMSOL64\Multiphysics\mli');
t_mphstart_start = tic;
mphstart(2036);
t_mphstart = toc(t_mphstart_start);
import com.comsol.model.*
import com.comsol.model.util.*

if nargin<1, mass_amu = 100; end
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
% !!! field_mode: 'real' (default) uses the actual FEM-solved 'es' field
% everywhere (the true discrete ring-stack field, with its ~1-2%
% deviation from ideal linear after bore_r narrowing). 'ideal' replaces
% ONLY the reflectron region's (entgrid to backplate) field with the
% mathematically perfect piecewise-constant E1/E2 (per the dual-stage
% solver's theory), while KEEPING the accelerator's real field unchanged
% (already validated as essentially perfect via the tGrid2=0-variance
% measurement) -- a diagnostic to test whether the ~1-2% real-field
% deviation in the reflectron is what's still capping resolution, before
% investing more effort into physically improving the ring-stack's field
% accuracy.

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
p.set('KE_in_eV', '5[V]', 'Ion energy entering the pusher (from RF quadrupole cooling guide)');
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
p.set('V_repeller', '2240[V]', 'U1 in the three-grid focusing design (KE0=2000eV, dKE=80eV, dx0=1mm, d1=3mm)');
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
p.set('V_grid1', '1760[V]', 'U2 in the three-grid focusing design -- forms E1=160V/mm bracket with repeller(U1), release cube centered at u0=d1/2=1.5mm gives KE0=2000eV, dKE=+-80eV');
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
p.set('V_mirror', sprintf('%.4f[V]', V_mirror_V), 'Reflectron backplate -- derived from the dual-stage closed-form solution (U1+E2*d2), L_total=1200mm (L1=L2=600mm), d1 from the d1_mm function argument (doc §7.49)');
% !!! L_accel now derived from the three-grid focusing solution:
% d1+d2=3+16.83=19.83mm, with D=0 (no extra drift needed for
% first-order time focus -- ion focuses exactly at grid2/field-free
% boundary).
p.set('L_accel', '19.83[mm]', 'Acceleration region depth (repeller to grid2) = d1(3mm)+d2(16.83mm), D=0 per the three-grid focusing solution');
% !!! Extended 10x (300->3000mm) per explicit request to test whether a
% longer flight path improves mass resolution -- for a system where the
% dominant timing spread comes from geometric/spatial effects that don't
% scale with distance (not a genuine energy-focusing defect the
% reflectron should fix), resolution R=t/(2*sigma_t) should improve
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
p.set('L_flight', 'L_accel+600[mm]', 'Entrance-grid z-position (accelerator origin to reflectron entrance) -- set so true field-free length L1=L_flight-L_accel=600.00mm exactly (doc §7.49, was 500mm)');
% !!! Added a named parameter for the detector's z-position, instead of
% only setting it inline in the geometry command -- the detection
% z-threshold in the post-processing code below previously used a bare
% hardcoded number (20.5) that silently matched the OLD detector
% position by coincidence and would have gone stale/wrong the moment
% the detector moved (exactly what happened during the §7.41 L1/L2
% asymmetry test). Both the geometry and the detection logic now read
% this SAME parameter, so they can never drift apart again.
p.set('detector_z', 'L_accel', 'Detector z-position -- exactly L_accel gives L2=L_flight-detector_z=500.00mm exactly (matching L1). Referenced by BOTH the detector geometry and the detection z-threshold below (was two independent hardcoded values before, a latent bug found during the §7.41 L1/L2 asymmetry test)');
p.set('L_refl', sprintf('%g[mm]', d1_mm+d2_mm), 'Ring-stack reflectron total length (d1 from the d1_mm function argument + adaptive d2 from the turnaround-depth calculation; geometrically this is the entrance-grid to backplate distance)');
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
p.set('V_mid', sprintf('%.4f[V]', U1_V), 'U1 = 2*U0*(L+2*d1)/(3*L), the dual-stage solver''s closed-form solution (U0=2000eV, d1 from the d1_mm function argument, L=1200mm exactly -- L1=L2=600mm, doc §7.49)');
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
p.set('x_refl_center', '0[mm]', 'Reflectron bore axis x-offset -- unified with the accelerator/flight-tube axis (x=0) now that bore_r comfortably exceeds the ion''s off-axis drift');
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
p.set('ring_outer_r', '300[mm]', 'Ring outer radius -- fixed default, decoupled from bore_r so bore scans change only the aperture radius');
% !!! Flight tube redesigned as a hollow CYLINDER (was a square Block),
% per explicit request: entgrid/grid2 (flight-tube boundary grids) are
% circular, matching the cylinder; grid1/accelring_k (INSIDE the
% accelerator's own square shield) stay square. flight_tube_r is sized
% comfortably larger than both the electrodes it contains (ion's real
% drift path reaches ~80mm off-axis) AND the charged grids (entgrid/
% grid2 themselves), giving genuine vacuum clearance between the tube's
% own grounded wall and anything at a different potential inside it.
p.set('flight_tube_r', 'ring_outer_r+50[mm]', 'Flight tube (field-free drift region) inner radius -- larger than ring_outer_r so grid2/entgrid have clearance from the tube wall');
% !!! Added an EXPLICIT solid wall for the flight tube (doc §7.43), per
% explicit request -- previously accelflightbox's own outer surface was
% just an implicit grounded boundary condition (selb_outerwall), no
% actual wall material modeled. Now a real annular Cylinder-Cylinder
% shell (radius flight_tube_r to flight_tube_r+flight_tube_wall) wraps
% around it, grounded (0V), matching the same technique used for the
% accelerator's own shield.
p.set('flight_tube_wall', '10[mm]', 'Flight tube wall thickness (explicit solid shell around the vacuum, minimum 10mm per explicit request)');
% !!! Added for doc §7.44, per explicit request: the flight tube's own
% shield is extended to ALSO enclose the reflectron region (previously
% only wrapped the field-free drift section) -- both ends of this now-
% longer shield are closed. flight_tube_r=ring_outer_r+50mm already
% gives 50mm radial clearance from the rings/backplate; shield_axial_gap
% enforces a 50mm minimum axial clearance in the current scan
% clearance in the AXIAL direction between the backplate's own far face
% and the new far-end cap.
p.set('shield_axial_gap', '50[mm]', 'Minimum axial clearance between the flight-tube shield''s end caps and the nearest internal component (backplate), per current scan request');
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
p.set('x_accel_center', '-48.80[mm]', 'Accelerator assembly x-offset (symmetric placement, doc §7.50): -v_x*(T/2), so the ion''s release point and detection point sit symmetrically about the flight tube''s true axis (detector at +48.80mm)');
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
p.set('accel_shield_half', '35[mm]', 'Accelerator square shield tube half-width; formal COMSOL/SIMION baseline has a 70 mm inner opening');
p.set('accel_shield_wall', '4[mm]', 'Accelerator shield wall thickness (thickened from 2mm to 4mm, per explicit request for more realistic/robust shield walls)');
p.set('accel_ring_gap', '2[mm]', 'Vacuum gap between accelerator ring electrodes and the shield inner wall (different-voltage conductors must not touch)');
p.set('accel_ring_bore_half', '15[mm]', 'Accelerator ring electrode bore half-width (30 mm square clear aperture)');
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
p.set('accel_shield_back_extra', '10[mm]', 'How far the accelerator shield extends behind the repeller''s own back face (was flush with it, now wraps around it with margin)');
% !!! Widened from 3mm to 20mm (doc §7.50, per explicit request).
p.set('endcap_gap', '20[mm]', 'Vacuum gap between the flight-tube end cap (opposite the acceleration direction) and the (extended) accelerator shield''s own back edge -- kept separate even though both are grounded (0V), per the "different objects need a real gap" discipline used throughout this design');

%% Solid electrodes (repeller, rings, backplate) -- unchanged technique
% (Difference: outer solid minus bore, auto Form Union with a vacuum
% envelope). These are real solid objects the ion never passes through
% (repeller: ion starts near it and moves away; rings: ion flies through
% the empty bore, never touching the annulus material; backplate: a
% plain full disk, no bore at all -- see its own feature below for why).
% !!! Changed from a circular Cylinder (r=100mm) to a rectangular Block:
% per explicit request, since the ion's initial distribution is only a
% 1mm cube and it barely drifts in x/y during the (very brief, ~14ns)
% acceleration crossing (~0.04mm of x-drift at vx=3106m/s), the repeller
% doesn't need to be anywhere near as large as the old "radius >> gap"
% sizing -- a few tens of mm is plenty. 40x40mm chosen (2x the 20mm
% accel gap, comfortably still in the "large plate" regime for a beam
% that stays this close to the axis).
% !!! RESIZED (doc §7.47, per explicit request) from a fixed 40mm to
% match the accelerator ring electrodes' own OUTER profile exactly:
% 2*(accel_shield_half-accel_ring_gap) = 66mm. This gives repeller the
% SAME accel_ring_gap(2mm) clearance from the shield's inner bore that
% the ring electrodes already have -- consistent sizing across all the
% accelerator's charged solid electrodes.
geom1.feature.create('repeller', 'Block');
geom1.feature('repeller').label('Repeller (pulses 0->V_repeller, solid, rectangular, ion never passes through it)');
geom1.feature('repeller').set('size', {'2*(accel_shield_half-accel_ring_gap)', '2*(accel_shield_half-accel_ring_gap)', '1'});
geom1.feature('repeller').set('pos', {'x_accel_center-(accel_shield_half-accel_ring_gap)', '-(accel_shield_half-accel_ring_gap)', '-1'});

% !!! Square shield tube around the accelerator (repeller to grid2): a
% thin grounded square-annular wall (Block-minus-Block, same technique
% as the reflectron rings but square instead of cylindrical), validated
% in isolation via test_square_shield_accel.m (see notes above). Spans
% the accelerator z-range (bracket + second stage) so grid1/grid2 can
% both sit flush against its bore.
% !!! Doc §7.47 (per explicit request): merged the separate 'repback'
% plate INTO this same single Difference, exactly the same "one big
% block minus one smaller block" technique used for the flight-tube
% shield (§7.46) -- accelshieldO now extends accel_shield_wall FURTHER
% back than accelshieldH's own back face, so the "extra" solid material
% left behind automatically forms an integrated back cap, with no
% separate feature needed. (An earlier attempt removed the back-sealing
% plate entirely, assuming repeller's new, smaller ring-sized gap
% wouldn't need it -- wrong: repeller sits at the very FRONT of the
% shield tube with open buffer vacuum directly behind it, unlike the
% rings which are fully surrounded by vacuum on both sides within the
% sealed bore. Even a small 2mm gap around repeller's edge reconnects to
% that buffer vacuum and leaks field forward -- confirmed: field-free
% residual rose to 0.16V/m without any back seal, vs 0.0016V/m with the
% old separate repback. This integrated-cap version achieves the same
% seal without a second Difference feature.) The shield's FORWARD end
% still ends exactly at z=L_accel (grid2's position), unaffected.
geom1.feature.create('accelshieldO', 'Block');
geom1.feature('accelshieldO').label('Accelerator shield outer solid (includes integrated back cap)');
geom1.feature('accelshieldO').set('size', {'2*(accel_shield_half+accel_shield_wall)', '2*(accel_shield_half+accel_shield_wall)', 'L_accel+1[mm]+accel_shield_back_extra+accel_shield_wall'});
geom1.feature('accelshieldO').set('pos', {'x_accel_center-(accel_shield_half+accel_shield_wall)', '-(accel_shield_half+accel_shield_wall)', '-1[mm]-accel_shield_back_extra-accel_shield_wall'});
geom1.feature.create('accelshieldH', 'Block');
geom1.feature('accelshieldH').label('Accelerator shield bore (stops accel_shield_wall short of the outer solid''s back face, leaving the integrated back cap)');
geom1.feature('accelshieldH').set('size', {'2*accel_shield_half', '2*accel_shield_half', 'L_accel+1[mm]+accel_shield_back_extra'});
geom1.feature('accelshieldH').set('pos', {'x_accel_center-accel_shield_half', '-accel_shield_half', '-1[mm]-accel_shield_back_extra'});
geom1.feature.create('accelshield', 'Difference');
geom1.feature('accelshield').label('Accelerator shield (grounded, one-piece: side walls + integrated back cap)');
geom1.feature('accelshield').selection('input').set({'accelshieldO'});
geom1.feature('accelshield').selection('input2').set({'accelshieldH'});

% !!! Flight-tube shield (doc §7.46, simplified per explicit request):
% REMOVED the separate 'endcap'/'endcap2'/'flighttubewall' three-feature
% design (which had a real geometric OVERLAP between endcap and
% flighttubewall's own end -- both occupied the same z-range at radius
% [flight_tube_r, flight_tube_r+flight_tube_wall]). Replaced with a
% SINGLE Difference (one big outer Cylinder minus one smaller inner
% Cylinder, both ends automatically closed by construction, no overlap
% possible) -- see 'flighttubewallO/H/flighttubewall' below, built right
% after accelflightbox so the bore dimensions are defined in one place.

% !!! 5 intermediate graded square ring electrodes between grid1 (z=3mm)
% and grid2 (z=L_accel): maintains field linearity across the 16.83mm
% gap (comparable to the 35mm shield half-width, so 2 endpoints alone
% would fringe -- same reasoning as the reflectron's own ring-stack).
% Each ring needs a REQUIRED vacuum gap from the shield wall (different-
% voltage conductors cannot touch -- see doc §7.32 for the hard-won
% lesson from the cylindrical attempt).
accelringtags = {};
for k = 1:5
    tagk = sprintf('accelring_%d', k);
    zk_expr = sprintf('3[mm]+%d*(L_accel-3[mm])/6', k);
    Vk_expr = sprintf('V_grid1*(1-%d/6)', k);
    outer_half = 'accel_shield_half-accel_ring_gap';
    geom1.feature.create([tagk 'O'], 'Block');
    geom1.feature([tagk 'O']).label(sprintf('Accelerator ring %d outer solid', k));
    geom1.feature([tagk 'O']).set('size', {['2*(' outer_half ')'], ['2*(' outer_half ')'], '1[mm]'});
    geom1.feature([tagk 'O']).set('pos', {['x_accel_center-(' outer_half ')'], ['-(' outer_half ')'], [zk_expr '-0.5[mm]']});
    geom1.feature.create([tagk 'H'], 'Block');
    geom1.feature([tagk 'H']).label(sprintf('Accelerator ring %d bore', k));
    geom1.feature([tagk 'H']).set('size', {'2*accel_ring_bore_half', '2*accel_ring_bore_half', '1[mm]'});
    geom1.feature([tagk 'H']).set('pos', {'x_accel_center-accel_ring_bore_half', '-accel_ring_bore_half', [zk_expr '-0.5[mm]']});
    geom1.feature.create(tagk, 'Difference');
    geom1.feature(tagk).label(sprintf('Accelerator ring %d (V=%s)', k, Vk_expr));
    geom1.feature(tagk).selection('input').set({[tagk 'O']});
    geom1.feature(tagk).selection('input2').set({[tagk 'H']});
    accelringtags{end+1} = tagk; %#ok<AGROW>
end
z_mid_expr = 'L_flight+L_stage1';
ringtags = {};
for k = 1:n_rings1
    tagk = sprintf('ring1_%d', k);
    % Equal center pitch from entgrid to midgrid.  With equal thickness,
    % this also makes all axial solid-to-solid gaps equal.
    zk_expr = sprintf('L_flight+%d*L_stage1/(N_rings1+1)', k);
    Vk_expr = sprintf('%d*V_mid/(N_rings1+1)', k);
    % !!! FIXED center-alignment bug: COMSOL's Cylinder 'pos' is the
    % BASE (bottom face) center, not the ring's own center -- with
    % pos.z=zk_expr and h=1mm, the ring actually spanned [zk,zk+1mm],
    % true center at zk+0.5mm, while Vk_expr's theoretical linear
    % voltage was computed AT zk. This systematic offset (half the ring
    % thickness -- was 0.5mm out of a ~33-50mm ring pitch, ~1-1.5%, now
    % 2.5mm since ring_thickness=5mm) matters given the Mamyrin theory's
    % second-order sensitivity to field precision. Shifted pos.z by
    % -ring_thickness/2 so the ring's true center lands exactly at zk
    % (matching the accelerator's own rings, which already did this
    % correctly via Block's pos being a corner, not base-center).
    geom1.feature.create([tagk 'O'], 'Cylinder');
    geom1.feature([tagk 'O']).label(sprintf('Stage1 ring %d outer solid', k));
    geom1.feature([tagk 'O']).set('r', 'ring_outer_r');
    geom1.feature([tagk 'O']).set('h', 'ring_thickness');
    geom1.feature([tagk 'O']).set('pos', {'x_refl_center' '0' [zk_expr '-ring_thickness/2']});
    geom1.feature.create([tagk 'H'], 'Cylinder');
    geom1.feature([tagk 'H']).label(sprintf('Stage1 ring %d bore', k));
    geom1.feature([tagk 'H']).set('r', 'bore_r');
    geom1.feature([tagk 'H']).set('h', 'ring_thickness');
    geom1.feature([tagk 'H']).set('pos', {'x_refl_center' '0' [zk_expr '-ring_thickness/2']});
    geom1.feature.create(tagk, 'Difference');
    geom1.feature(tagk).label(sprintf('Stage1 ring %d (annulus electrode, V=%s)', k, Vk_expr));
    geom1.feature(tagk).selection('input').set({[tagk 'O']});
    geom1.feature(tagk).selection('input2').set({[tagk 'H']});
    ringtags{end+1} = tagk; %#ok<AGROW>
end
for k = 1:n_rings2 % N_rings2
    tagk = sprintf('ring2_%d', k);
    % Equal center pitch from midgrid to the solid backplate.  In
    % particular, the last-ring/backplate gap equals the ring-to-ring gap;
    % d2 and the backplate-to-shield clearance remain unchanged.
    zk_expr = sprintf('L_flight+L_stage1+%d*(L_refl-L_stage1)/(N_rings2+1)', k);
    Vk_expr = sprintf('V_mid+%d*(V_mirror-V_mid)/(N_rings2+1)', k);
    % !!! Same center-alignment fix as stage1 rings above.
    geom1.feature.create([tagk 'O'], 'Cylinder');
    geom1.feature([tagk 'O']).label(sprintf('Stage2 ring %d outer solid', k));
    geom1.feature([tagk 'O']).set('r', 'ring_outer_r');
    geom1.feature([tagk 'O']).set('h', 'ring_thickness');
    geom1.feature([tagk 'O']).set('pos', {'x_refl_center' '0' [zk_expr '-ring_thickness/2']});
    geom1.feature.create([tagk 'H'], 'Cylinder');
    geom1.feature([tagk 'H']).label(sprintf('Stage2 ring %d bore', k));
    geom1.feature([tagk 'H']).set('r', 'bore_r');
    geom1.feature([tagk 'H']).set('h', 'ring_thickness');
    geom1.feature([tagk 'H']).set('pos', {'x_refl_center' '0' [zk_expr '-ring_thickness/2']});
    geom1.feature.create(tagk, 'Difference');
    geom1.feature(tagk).label(sprintf('Stage2 ring %d (annulus electrode, V=%s)', k, Vk_expr));
    geom1.feature(tagk).selection('input').set({[tagk 'O']});
    geom1.feature(tagk).selection('input2').set({[tagk 'H']});
    ringtags{end+1} = tagk; %#ok<AGROW>
end

% !!! backplate REVERTED back to a real solid disk (per explicit
% request): the idealized-zero-thickness-boundary version (doc §6.11)
% fixed the ideal_stage2 gap, but that fix was solving a real-field-
% accuracy problem, not a particle-transparency one -- the "must be an
% idealized boundary" rationale used for entgrid/grid2/midgrid/grid1
% applies ONLY because ions actually pass THROUGH those grids' full
% cross-section. No ion ever physically reaches backplate (it turns
% around ~35-50mm short of it, well inside d2's margin), so it never
% needed particle transparency in the first place -- a real solid full
% disk (same technique as detector/repeller: implicit CPT stop via
% exclusion from sel_vac, no dedicated Wall/Freeze feature) is simpler
% and behaves like every other solid electrode in this design.
% !!! Sized/gapped per explicit request to match the OTHER electrodes it
% sits behind, not re-derive a new gap: radius=ring_outer_r, giving it
% the SAME 50mm gap to flight_tube_r that every ring in stage1/stage2
% already uses (no special-cased smaller gap the way the idealized
% version needed). Positioned so its ion-facing front face (smaller z,
% Cylinder's 'pos' is the base/bottom-face anchor) sits exactly at the
% theoretical z=L_flight+L_refl -- the same location the zero-thickness
% plane used to occupy, i.e. where the field theoretically reaches
% V_mirror -- and extends ring_thickness further out in +z, away from
% the ion path (harmless: nothing back there but the shield's own end
% cap, which z1_bore above keeps shield_axial_gap clear of backplate's
% new, thicker far face).
geom1.feature.create('backplate', 'Cylinder');
geom1.feature('backplate').label('Reflectron backplate (V_mirror, solid disk, ion never reaches it)');
geom1.feature('backplate').set('r', 'ring_outer_r');
geom1.feature('backplate').set('h', 'ring_thickness');
geom1.feature('backplate').set('pos', {'x_refl_center', '0', 'L_flight+L_refl'});

% Detector: a REAL solid object (must actually stop/detect the ion, not
% be transparent like the grids). Placed far out of the beam path for
% now -- repositioned once trajectories with the new grid design are
% measured (same "perfect condition" approach used throughout: verify
% the core physics is clean before introducing anything that could
% perturb it).
geom1.feature.create('detector', 'Cylinder');
geom1.feature('detector').label('Detector (grounded, solid, real physical stop)');
% !!! Widened from 10mm to 25mm: the first large-N resolution test
% (N=3000) showed R=22.5, MUCH worse than the earlier short-flight-tube
% result -- root cause was NOT the longer flight path itself, but an
% unintended coupling: ions have a real vx spread (from the 5+-1eV
% Gaussian energy), so at the extended flight length their x-spread at
% the detector's z-level grew large (172.9-188.6mm) relative to the old
% 10mm-radius window. Since the detector is a REAL SOLID object, an ion
% only gets absorbed once it geometrically enters this window -- ions
% with off-nominal vx need extra/less lateral drift TIME to reach a
% narrow window, contaminating the measured arrival time with an
% x-drift effect that has nothing to do with the mass-dependent
% z-direction TOF. Widening the window so ALL ions enter it at
% essentially the same z-crossing (regardless of their individual vx)
% decouples this.
% !!! Widened from 25mm to 40mm (doc §7.49): the detector now physically
% intercepts the ion (Wall/Freeze condition), and the upcoming d2 scan
% will shift the arrival time (and hence the ion's x-drift at impact)
% somewhat from point to point -- a larger radius gives comfortable
% tolerance across the scan range without needing to recompute the
% detector's exact x-position for every d2 value.
geom1.feature('detector').set('r', '40[mm]');
geom1.feature('detector').set('h', '1[mm]');
% !!! Repositioned to the measured landing spot (x=27.45-28.05mm at
% z~22mm, measured directly after the accelflightbox/reflvac gap fix --
% the ion now genuinely completes a clean round trip). r=10mm centered
% at x=28 spans x=[18,38], comfortably covering the tight measured
% footprint while excluding x=0 (the outbound pass's position at this
% z, avoiding the earlier "blocks the outbound pass" bug).
% !!! TEMPORARILY moved far away for re-measurement diagnostic (per the
% "perfect condition" methodology): the 10x longer L_flight means total
% round-trip x-drift will be roughly 10x larger too, so the old x=28mm
% position is almost certainly wrong now -- measure the real landing
% spot first, unobstructed, before repositioning the detector.
% !!! Repositioned to the re-measured landing spot for the extended
% L_flight=3000mm (x=173.5-190.2mm, mean 183.2mm -- ~6.5x farther out
% than the old 300mm-flight-tube landing spot, since total round-trip
% x-drift scales with the ~10x longer total TOF).
% !!! TEMPORARILY moved far away for re-measurement diagnostic (per the
% "perfect condition" methodology): L_flight dropped drastically
% (3000->320mm), so the old x=183mm calibration is almost certainly
% wrong now -- measure the real landing spot first, unobstructed.
% !!! Repositioned to the re-measured landing spot for the compact
% redesign (L_flight=320mm): return xEnd measured at x=26.6-28.7mm.
% !!! Repositioned to the re-measured landing spot: return xEnd measured
% at x=172-175mm (mean 173mm) for the 200/500/500mm design.
% !!! CORRECTED: the earlier x=173mm estimate came from a stale/wrong
% measurement. Direct unrestricted-crossing check at z=25 (just past the
% detector plane) measured x tightly clustered at 79.4-80.6mm -- using
% that value instead recovered 100% detection (was 25/50) and R=396.7
% (was 91.5, itself an artifact of the miscalibrated narrow window).
% !!! TEMPORARILY moved far away for re-measurement diagnostic (within
% the 800x800mm domain's x range of [-400,400]).
% !!! Moved closer to the field-free boundary (grid2, z=L_accel): the
% Mamyrin dual-stage theory's L2 (reflectron-to-detector drift) is
% measured from z=L_accel, not from wherever the detector happened to
% sit.
% !!! Per explicit request, z moved to EXACTLY L_accel (was L_accel+
% 0.3mm) so L2=L_flight-L_accel=500.00mm holds EXACTLY, matching L1
% exactly too (both now precisely 500mm, L_total=1000mm exactly, no
% 0.3mm residual). This reintroduces the geometric conflict the old
% +0.3mm offset was created to avoid (detector's flat face exactly
% !!! MOVED (doc §7.48, per explicit request) from x=420mm (parked off
% to the side, avoiding any overlap with grid2's disk) to x=94.93mm --
% the ion's ACTUAL x-position at detection time, so the detector sits
% exactly where the returning ion hits, "parallel to the accelerator
% exit" (same z as grid2/L_accel, matching L2=500mm exactly). Derived
% from x=v_x*t: v_x=3106.2 m/s (the 5eV transverse entrance speed,
% constant throughout the whole flight since there's no x-direction
% force) times the measured mean detection time (~30.56-30.57us) =~
% 94.93mm. This value is mass-independent: v_x scales as 1/sqrt(m) for
% fixed 5eV transverse KE, while total flight time scales as sqrt(m) for
% fixed accelerating voltage -- the two dependencies cancel, so the same
% x-position is correct regardless of which ion mass is simulated.
% Detector (solid, 0V) now spatially overlaps grid2's disk (also 0V,
% zero-thickness) at their shared z -- same-voltage overlap, matching
% the established benign pattern used throughout this design (verify
% empirically after this change, same as always).
% !!! FIXED (per explicit request): the ion returns traveling in the -z
% direction (coming back from the reflectron at large z, heading toward
% the source at small z), so it strikes the detector's TOP face (the
% +z-facing surface) FIRST, not the bottom face. Cylinder's 'pos' is the
% BASE (bottom, smaller-z) center -- with pos.z=detector_z directly, the
% detector spanned z=[detector_z, detector_z+h], meaning its ion-facing
% TOP surface sat at detector_z+h (1mm PAST the intended L2=500mm
% position), not AT detector_z where L2 is actually measured from. Moved
% back by h so the TOP (ion-striking) face lands exactly at detector_z.
% !!! x updated to +48.80mm (doc §7.50, per explicit request): the
% accelerator (and hence the ion's release point) is now shifted to
% x_accel_center=-48.80mm, and the detector sits at the MIRROR position
% +48.80mm=-x_accel_center, so the ion's release point and detection
% point are symmetric about the flight tube's true cylindrical axis
% (x=0) -- rather than the ion starting exactly on-axis and drifting
% one-sided to an off-axis detector as before. Detector radius kept at
% 40mm for tolerance margin.
geom1.feature('detector').set('pos', {'48.80' '0' 'detector_z-1[mm]'});

%% Vacuum envelope: ONE continuous cylinder spanning accel+drift, plus
% the ring-stack's own envelope (auto Form Union merges everything, same
% technique used throughout this project for the quadrupole rods).
% !!! CHANGED from a square Block to a circular Cylinder ("flight tube"
% is a hollow cylinder, per explicit request) -- radius=flight_tube_r,
% comfortably larger than both the electrodes inside it (ion's real
% drift path reaches ~80mm off-axis) and ring_outer_r (so the tube's own
% grounded wall has real clearance from anything at a different
% potential, e.g. the reflectron rings/backplate it borders). The
% accelerator's own SQUARE shield (accelshield, small radius
% accel_shield_half) sits NESTED inside this larger cylinder for the
% z<L_accel portion -- two different cross-section shapes sharing the
% same vacuum, connected via the shared grid2 boundary at z=L_accel.
% !!! Bore z-range (doc §7.46): the flight tube's own vacuum interior,
% shared exactly by accelflightbox (the vacuum) and flighttubewallH (the
% "hole" subtracted from the shield's outer solid, below). Defining both
% ends here ONCE avoids the two features drifting out of sync.
% z0_bore: endcap_gap(3mm) past the (extended) accelerator shield's own
% back edge (z=-1-accel_shield_back_extra). z1_bore: shield_axial_gap
% (50mm) past backplate's own far face.
% !!! Extended by accel_shield_wall (doc §7.47): the accelerator shield
% now has an INTEGRATED back cap (built into the same accelshieldO/H
% Difference, see above) whose own back face is at -1-
% accel_shield_back_extra-accel_shield_wall -- z0_bore (where the flight
% tube's own vacuum bore begins) must stay behind THAT, or flighttubewallO
% (a full disk before flighttubewallH's hole starts) would overlap the
% accelerator shield's new back cap at the same z.
z0_bore = '-1[mm]-accel_shield_back_extra-accel_shield_wall-endcap_gap';
% !!! backplate is a real solid disk again (front face at L_flight+
% L_refl, extending ring_thickness further out in +z, see the backplate
% feature below) -- z1_bore must stay shield_axial_gap clear of its own
% FAR face, i.e. past L_flight+L_refl+ring_thickness, not just
% L_flight+L_refl itself.
z1_bore = 'L_flight+L_refl+ring_thickness+shield_axial_gap';
geom1.feature.create('accelflightbox', 'Cylinder');
geom1.feature('accelflightbox').label('Flight tube (accelerator drift-out + field-free flight tube + reflectron, hollow cylinder)');
geom1.feature('accelflightbox').set('r', 'flight_tube_r');
geom1.feature('accelflightbox').set('h', [z1_bore '-(' z0_bore ')']);
geom1.feature('accelflightbox').set('pos', {'0', '0', z0_bore});

% !!! Flight-tube shield (doc §7.46, simplified per explicit request):
% ONE Difference -- a single outer Cylinder (radius flight_tube_r+
% flight_tube_wall, spanning the bore's z-range EXTENDED by
% flight_tube_wall at EACH end) minus a single inner Cylinder (radius
% flight_tube_r, EXACTLY matching the bore z-range z0_bore..z1_bore,
% same as accelflightbox above) -- this gives walls AND both end caps
% in one Boolean operation, with wall/cap thickness uniformly
% flight_tube_wall everywhere and NO possibility of internal overlap
% (previously a separate endcap+flighttubewall+endcap2 three-feature
% design had a real overlap: endcap's z-range fell inside
% flighttubewall's own z-range at the same radius band). The inner
% Cylinder's z-range matches accelflightbox's bore EXACTLY, so the
% vacuum and the shield's own hole share one common boundary with no gap
% and no overlap.
geom1.feature.create('flighttubewallO', 'Cylinder');
geom1.feature('flighttubewallO').label('Flight tube shield outer solid (spans bore + both end-cap thicknesses)');
geom1.feature('flighttubewallO').set('r', 'flight_tube_r+flight_tube_wall');
geom1.feature('flighttubewallO').set('h', [z1_bore '-(' z0_bore ')+2*flight_tube_wall']);
geom1.feature('flighttubewallO').set('pos', {'0', '0', [z0_bore '-flight_tube_wall']});
geom1.feature.create('flighttubewallH', 'Cylinder');
geom1.feature('flighttubewallH').label('Flight tube shield bore (matches accelflightbox exactly)');
geom1.feature('flighttubewallH').set('r', 'flight_tube_r');
geom1.feature('flighttubewallH').set('h', [z1_bore '-(' z0_bore ')']);
geom1.feature('flighttubewallH').set('pos', {'0', '0', z0_bore});
geom1.feature.create('flighttubewall', 'Difference');
geom1.feature('flighttubewall').label('Flight tube shield (grounded, one-piece shell with both ends closed -- encloses field-free tube + reflectron)');
geom1.feature('flighttubewall').selection('input').set({'flighttubewallO'});
geom1.feature('flighttubewall').selection('input2').set({'flighttubewallH'});

% !!! REMOVED 'reflvac' (doc §7.47, per explicit request to check for
% redundant entities): it spanned z=[L_flight+1, L_flight+L_refl-1] at
% radius=ring_outer_r(350mm) -- entirely a SUBSET of accelflightbox's
% own region, which (since §7.44/§7.46) already spans z0_bore..z1_bore
% (comfortably containing reflvac's whole z-range with margin on both
% sides) at a LARGER radius (flight_tube_r=350mm by default). Both features
% supplied the exact same material (vacuum) over the exact same 3D
% region -- reflvac was pure redundancy left over from when the
% reflectron had its own separate, smaller vacuum envelope (before
% accelflightbox was extended to cover it too).

geom1.feature.create('relvol', 'Block');
geom1.feature('relvol').label('Release volume (ion entering pusher at 5eV, 1mm cube)');
geom1.feature('relvol').set('size', {'1' '1' '1'});
geom1.feature('relvol').set('pos', {'x_accel_center-0.5' '-0.5' '1'});
geom1.feature('relvol').set('selresult', 'on');

for t = [{'repeller','detector','accelshield','flighttubewall','backplate'}, ringtags, accelringtags]
    geom1.feature(t{1}).set('selresult','on');
end

%% Idealized mesh grids: FULL 800x800mm interior boundaries (no aperture
% needed at all -- the ion passes through anywhere), embedded via
% Union+intbnd into the vacuum. Four grids now: grid1 (accelerator,
% forms a weak bracket field with repeller for low KE spread), grid2
% (accelerator exit, always grounded, marks the field-free interface),
% entgrid (reflectron entrance, always grounded), midgrid (reflectron
% stage1/stage2 boundary, V_mid).
% !!! SIMPLIFIED per explicit request: removed gridA/gridB/accelmid
% entirely. New accelerator: repeller(z=0)->grid1(z=3mm)->grid2(z=6mm=
% L_accel). Ion releases between repeller and grid1 (z0 in [1,2]mm,
% unchanged) -- repeller+grid1 form the SAME "weak bracket field" role
% that gridA/gridB used to serve, just using the accelerator's own two
% real electrodes instead of a separate dedicated pair. grid1's voltage
% (V_grid1, set above) is derived from the desired initial KE and KE
% spread, NOT chosen arbitrarily. grid1 and grid2 have no direct
% relationship (per explicit statement) -- just spatially separated by
% another 3mm.
% !!! grid1/grid2 sized to match the square shield's bore EXACTLY
% (2*accel_shield_half=70mm) -- flat idealized interior boundaries can
% safely sit FLUSH against the shield's bore (validated in
% test_square_shield_accel.m: selb_g1/selb_g2 boundary count=1, no
% overlap issue) since they're not separate solid conductors, unlike the
% ring electrodes which need an actual gap.
% !!! entgrid/midgrid UNIFIED with accelflightbox's own (now
% ring_outer_r-derived) sizing: changed from a fixed, unrelated 800mm to
% 2*(ring_outer_r+20mm), EXACTLY matching accelflightbox above. This is
% a hard TOPOLOGY requirement, not just a style preference: a WorkPlane
% cutting through a vacuum block to form an interior boundary must span
% the block's FULL cross-section at that z, or a "frame" of vacuum
% around its edges is left uncovered, breaking the interior-boundary
% topology. First attempt sized entgrid/midgrid to ring_outer_r+10mm
% while accelflightbox was still the OLD fixed 800mm -- smaller than the
% box, leaving exactly this kind of uncovered frame, and corrupting the
% field-free drift region (previously exact -0.0000 V/m everywhere,
% became -0.17 to +0.45 V/m) even though selection-count diagnostics
% alone might have looked passable. Fixed by narrowing accelflightbox to
% match instead of just shrinking entgrid/midgrid independently -- both
% now derive from the SAME ring_outer_r+20mm expression.
% !!! Shapes per explicit request: grid1 (inside the accelerator's own
% SQUARE shield) stays a square Rectangle. grid2 (shared accelerator-
% exit/flight-tube-entrance grid) and entgrid (flight-tube-exit/
% reflectron-entrance grid) are now CIRCLES matching the (now
% cylindrical) flight tube -- sized to flight_tube_r exactly, since
% both are at 0V, the SAME potential as the flight tube's own grounded
% wall (no short-circuit concern, and exact match is REQUIRED for
% topology: a WorkPlane cutting through a vacuum domain must span that
% domain's full cross-section, see the accelflightbox-narrowing lesson
% above). midgrid (entirely inside the reflectron, bordered by reflvac
% on both sides) is also a circle, matching ring_outer_r exactly --
% same reasoning as the rings/backplate already touching reflvac's own
% edge safely (reflvac isn't a charged conductor).
% !!! Explicit x-center column added (5th column): grid2/entgrid (flight
% tube boundary grids) are centered on the ACCELERATOR's own axis (x=0),
% matching accelflightbox. midgrid sits BETWEEN the stage1/stage2 rings,
% which are centered on x_refl_center -- it must match THEM, not
% default to the workplane's own origin (0,0). Previously midgrid's
% Circle was created with no explicit 'pos', silently defaulting to
% (0,0) instead of x_refl_center -- a real axis-misalignment bug (only
% harmless by coincidence if x_refl_center happened to be 0). Now that
% x_refl_center is ALSO reset to 0 (see below, unifying the whole
% system on one axis), this is currently a no-op numerically, but is
% fixed explicitly so a future non-zero x_refl_center won't silently
% reintroduce the same misalignment.
% !!! grid2 REVERTED from the large shared circle (flight_tube_r) back
% to a small square, per the end-cap redesign (doc §7.42): the end cap
% is now at z=0 (the flight tube's OTHER end, opposite the reflectron),
% NOT at z=L_accel -- so grid2, at z=L_accel, has nothing to do with the
% end cap's hole sizing at all. It goes back to sealing ONLY the
% accelerator's own aperture, no longer coupled to flight_tube_r or the
% end cap in any way.
% !!! TRIED (first attempt) shrinking grid1/grid2/entgrid ALL by a gap
% from their shield's own bore -- broke the field-free region badly
% (residual jumped to -8.07V/m at z=25mm). REFINED understanding (doc
% §7.48, per explicit request): the BOUNDARY grids that mark the
% transition between "inside a sealed grounded enclosure" and "the
% exterior field-free region" (grid2 at the accelerator's exit, entgrid
% at the flight-tube/reflectron transition) MUST fully seal (touch their
% shield exactly) -- shrinking THESE is what caused the leak, since it
% opened a path to the exterior. But grid1 and midgrid sit ENTIRELY
% INSIDE an already-sealed enclosure (grid1: inside accelshield's tube,
% with grid2 sealing the only exit; midgrid: inside the flight-tube
% shield, which is now one continuous grounded shell with both ends
% closed per §7.46) -- any small gap they leave stays CONTAINED within
% that sealed box and cannot leak to the exterior. So: grid1 shrunk to
% match repeller/ring size (2*(accel_shield_half-accel_ring_gap)=66mm,
% same accel_ring_gap discipline as every other charged accelerator
% electrode); grid2/entgrid kept at full size (still the sealing
% boundaries); midgrid (charged, V_mid) shrunk to a real gap from the
% flight-tube shield instead of touching flight_tube_r directly.
% !!! midgrid radius CHANGED from flight_tube_r-10mm (10mm gap) to
% ring_outer_r (per explicit request, to match the SAME 50mm gap to
% flight_tube_r that the ring stack/backplate already use) -- midgrid
% sits entirely inside the already-sealed flight-tube shield (same as
% before), so this is purely a "make the gap consistent across all of
% the reflectron's charged internal components" change, not a topology
% fix; §4.5's "sealed enclosure contains internal leakage" reasoning
% still applies unchanged.
% !!! grid1/grid2 (accelerator-internal grids) now centered at
% x_accel_center too, matching repeller/accelring_k/accelshield's own
% shift (doc §7.50) -- entgrid/midgrid stay on the true flight-tube axis
% (x=0/x_refl_center=0), unchanged: by the time the ion reaches entgrid
% (roughly the flight's halfway point), its x-drift from x_accel_center
% has carried it back to ~0, matching the reflectron's own true-axis
% centering -- the symmetric design is self-consistent at this crossing
% point.
gridspecs = {
    'wp_grid1',     '3[mm]'         'square'  '2*(accel_shield_half-accel_ring_gap)'  'x_accel_center'
    'wp_grid2',     'L_accel'       'square'  '2*accel_shield_half'  'x_accel_center'
    'wp_entgrid',   'L_flight'      'circle'  'flight_tube_r'         '0'
    'wp_midgrid',   z_mid_expr      'circle'  'ring_outer_r'          'x_refl_center'
};
for gi_ = 1:size(gridspecs,1)
    wptag = gridspecs{gi_,1};
    zexpr = gridspecs{gi_,2};
    wshape = gridspecs{gi_,3};
    wsize = gridspecs{gi_,4};
    wxc = gridspecs{gi_,5};
    wp = geom1.feature.create(wptag, 'WorkPlane');
    wp.set('quickplane', 'xy');
    wp.set('quickz', zexpr);
    if strcmp(wshape, 'square')
        wp.geom.feature.create('r1', 'Rectangle');
        wp.geom.feature('r1').set('size', {wsize, wsize});
        wp.geom.feature('r1').set('pos', {[wxc '-(' wsize ')/2'], ['-(' wsize ')/2']});
    else
        wp.geom.feature.create('c1', 'Circle');
        wp.geom.feature('c1').set('r', wsize);
        wp.geom.feature('c1').set('pos', {wxc, '0'});
    end
end
geom1.feature.create('uni_grids', 'Union');
geom1.feature('uni_grids').label('Embed all 4 idealized grids as interior boundaries (backplate is a real solid again, handled via soliddoms)');
geom1.feature('uni_grids').selection('input').set({'accelflightbox', ...
    'wp_grid1','wp_grid2','wp_entgrid','wp_midgrid'});
geom1.feature('uni_grids').set('intbnd', true);

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
    'selb_grid1',     '3[mm]'            '0.5[mm]'    'accel_shield_half'                                       'x_accel_center'
    'selb_grid2',     'L_accel'          '0.2[mm]'    'accel_shield_half+accel_shield_wall+endcap_gap+5[mm]'    'x_accel_center'
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

t_mesh_start = tic;
mesh1 = comp1.mesh.create('mesh1');
mesh1.label('Mesh (hauto=6, refined at relvol + ring stack)');
mesh1.feature('size').set('hauto', 6);
sz1 = mesh1.feature.create('sz1', 'Size');
sz1.label('Fine mesh on release volume');
sz1.selection.geom('geom1', 3);
sz1.selection.named('geom1_relvol_dom');
sz1.set('custom', 'on');
sz1.set('hmaxactive', true);
sz1.set('hmax', '0.1[mm]');
% Fine mesh on the gridA/gridB bracket region (z=0 to 3mm): the field
% here is now a weak gradient sandwiched between two much steeper
% transitions (repeller->gridA, gridB->accelmid) all within a few mm --
% needs finer resolution than the general hauto=6 default to be resolved
% accurately.
% !!! Widened from the old [0,3]mm (gridA/gridB bracket only) to [0,6]mm
% (the WHOLE new accelerator: repeller-grid1 bracket AND grid1-grid2
% gap), since the grid1-grid2 segment now has a steep field
% (~1477 V/mm) needing fine mesh resolution too.
comp1.selection.create('selbracket', 'Box');
comp1.selection('selbracket').label('Accelerator region (repeller-grid1-grid2, for mesh refinement)');
comp1.selection('selbracket').set('xmin', -50); comp1.selection('selbracket').set('xmax', 50);
comp1.selection('selbracket').set('ymin', -50); comp1.selection('selbracket').set('ymax', 50);
comp1.selection('selbracket').set('zmin', 0); comp1.selection('selbracket').set('zmax', 20);
comp1.selection('selbracket').set('condition', 'inside');
szbracket = mesh1.feature.create('szbracket', 'Size');
szbracket.label('Fine mesh on accelerator region (repeller-grid1-grid2)');
szbracket.selection.geom('geom1', 3);
szbracket.selection.named('selbracket');
szbracket.set('custom', 'on');
szbracket.set('hmaxactive', true);
szbracket.set('hmax', '0.3[mm]');
comp1.selection.create('selreflregion', 'Cylinder');
comp1.selection('selreflregion').label('Ring-stack region (geometric, for mesh refinement)');
% !!! Changed from a hardcoded 210 (already smaller than ring_outer_r=
% 350mm) to a parameter EXPRESSION tied to ring_outer_r, so the fine-
% mesh region always tracks the ring stack's actual size instead of
% needing manual re-tuning. A fixed attempt at 700 (to safely cover a
% 650mm ring_outer_r test) blew the mesh up to 3.66M elements (was
% ~170-260K) and timed out -- applying fine mesh over a fixed 700mm
% radius wastes enormous effort when ring_outer_r is much smaller.
comp1.selection('selreflregion').set('r', 'ring_outer_r+10[mm]');
comp1.selection('selreflregion').set('rin', 0);
% !!! Was hardcoded [41.2 0 500] (matching the OLD, now-removed
% x_refl_center=41.2mm reflectron-axis offset). Recomputed from the
% CURRENT parameter values (x_refl_center is now 0, unified axis, see
% doc §7.38) rather than left stale -- this selection type takes a
% plain numeric array, not string expressions, so the values are
% evaluated here in MATLAB instead of passed as parameter names.
comp1.selection('selreflregion').set('pos', [p.evaluate('x_refl_center','mm') 0 p.evaluate('L_flight','mm')]);
comp1.selection('selreflregion').set('axis', [0 0 1]);
% !!! FIXED: 'top' for a Cylinder selection is the ABSOLUTE z-coordinate
% of the far end (not a height delta) -- was hardcoded to 502, which
% with pos.z=500 only covered a 2mm sliver right at the reflectron
% entrance, leaving the remaining ~498mm of the ring stack on the
% coarser default mesh (hauto=6). This was found via a fine-resolution
% field-precision scan: on-axis Ez deviation from theory was NOT the
% ring-discretization ripple expected, but a smooth ~0.06%->0.58%
% monotonic trend across each stage, worst right at each stage's
% "settling" boundary (entgrid/backplate) and best near the shared,
% flat midgrid -- a pattern consistent with under-refined mesh over
% most of the ring stack, not an inherent field/geometry limitation.
% Fixed to properly span the whole reflectron (z=500 to z=1000+2mm
% margin) via a parameter expression, so it stays correct if L_flight/
% L_refl change later instead of needing manual re-tuning again.
% !!! Extended by +ring_thickness (per the backplate solid-disk revert
% above): backplate's own solid domain now extends ring_thickness past
% L_flight+L_refl, so the fine-mesh region must reach that far too, or
% part of backplate's volume would silently fall back on the coarser
% default mesh.
comp1.selection('selreflregion').set('top', 'L_flight+L_refl+ring_thickness+2');
comp1.selection('selreflregion').set('condition', 'inside');
szrefl = mesh1.feature.create('szrefl', 'Size');
szrefl.label('Finer mesh on ring-stack region (resolve the graded field)');
szrefl.selection.geom('geom1', 3);
szrefl.selection.named('selreflregion');
szrefl.set('custom', 'on');
szrefl.set('hmaxactive', true);
szrefl.set('hmax', sprintf('%g[mm]', mesh_hmax_refl_mm));
% Layered local refinement for field diagnostics: uniformly setting the
% full r=ring_outer_r cylinder to 5mm creates millions of elements and
% makes every particle scan prohibitively expensive. The useful field
% curves are controlled by the ring inner edge. A connected vacuum volume
% cannot be partially selected as a domain. Do NOT select the whole bore
% boundary either: it touches large connected vacuum faces and becomes as
% expensive as global refinement. Select only the narrow physical inner
% cylindrical walls of the annular rings; FreeTet then grades their
% adjacent vacuum cells locally.
local_rim_hmax_mm = max(3, mesh_hmax_refl_mm/3);
% The narrow boundary method is retained as an opt-in experiment. On the
% current connected-vacuum geometry it was still too expensive for a
% routine particle scan; enable only after a mesh-only convergence run by
% setting the environment variable OATOF_LOCAL_EDGE_MESH to a nonempty
% value. It is disabled by default for all ordinary calls.
use_local_edge_refinement = ~isempty(getenv('OATOF_LOCAL_EDGE_MESH'));
if use_local_edge_refinement
    comp1.selection.create('selreflrimmesh', 'Cylinder');
    comp1.selection('selreflrimmesh').label('Reflectron ring-inner-edge boundaries (local mesh)');
    comp1.selection('selreflrimmesh').set('entitydim', '2');
    comp1.selection('selreflrimmesh').set('r', 'bore_r+1.5[mm]');
    comp1.selection('selreflrimmesh').set('rin', 'bore_r-1.5[mm]');
    comp1.selection('selreflrimmesh').set('pos', [p.evaluate('x_refl_center','mm') 0 p.evaluate('L_flight','mm')]);
    comp1.selection('selreflrimmesh').set('axis', [0 0 1]);
    comp1.selection('selreflrimmesh').set('top', 'L_flight+L_refl+ring_thickness+2');
    comp1.selection('selreflrimmesh').set('condition', 'intersects');
    szreflrim = mesh1.feature.create('szreflrim', 'Size');
    szreflrim.label(sprintf('Fine mesh at reflectron ring inner edge (%.3gmm)', local_rim_hmax_mm));
    szreflrim.selection.geom('geom1', 2);
    szreflrim.selection.named('selreflrimmesh');
    szreflrim.set('custom', 'on');
    szreflrim.set('hmaxactive', true);
    szreflrim.set('hmax', sprintf('%g[mm]', local_rim_hmax_mm));
end
mesh1.feature.create('ftet1', 'FreeTet');
mesh1.run;
mi = mphmeshstats(model, 'mesh1');
fprintf('mesh: isempty=%d iscomplete=%d, Nelem=%d\n', mi.isempty, mi.iscomplete, mi.numelem(2));
if mi.isempty || ~mi.iscomplete, error('mesh failed'); end
t_mesh = toc(t_mesh_start);
fprintf('[TIMING] mesh (mesh1.run + mphmeshstats): %.2fs\n', t_mesh);

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
L_accel_mm = p.evaluate('L_accel','mm');
v_x_ffcheck = sqrt(2*5*1.602176e-19/(mass_amu*1.66054e-27));
v_push_ffcheck = sqrt(2*2000*1.602176e-19/(mass_amu*1.66054e-27));
zcheck = [25 100 200 300 400 480];
for zc = zcheck
    coord = [x_accel_center_mm_ffcheck + v_x_ffcheck*(zc-L_accel_mm)/v_push_ffcheck; 0; zc];
    Ez = mphinterp(model, 'es.Ez', 'coord', coord, 'dataset', 'dset1', 'matherr', 'off');
    fprintf('  z=%5.0fmm: Ez=%.4f V/m\n', zc, Ez);
end
fprintf('--- Accelerator field check (bracket region z=0-3mm: target 160 V/mm between repeller/grid1; grid1-grid2 z=3-19.83mm: target 104.57 V/mm) ---\n');
% !!! x updated from 0 to x_accel_center (doc §7.50): the whole
% accelerator assembly moved off-axis, so querying at x=0 now probes
% the field-free flight tube (correctly showing ~0), not the
% accelerator's own internal field. Must query at the accelerator's
% OWN axis to see its real internal field.
x_accel_center_mm = p.evaluate('x_accel_center','mm');
for zc = [0.2 0.5 1.0 1.5 2.0 2.5 2.8 4 8 12 16 19.5]
    coord = [x_accel_center_mm; 0; zc];
    Ez = mphinterp(model, 'es.Ez', 'coord', coord, 'dataset', 'dset1', 'matherr', 'off');
    fprintf('  z=%5.2fmm: Ez=%.2f V/m\n', zc, Ez);
end

t_diag = toc(t_diag_start);
fprintf('[TIMING] field diagnostic queries (mphinterp x18): %.2fs\n', t_diag);

t_cptsetup_start = tic;
%% CPT
m_kg = mass_amu*1.66054e-27;
cpt = comp1.physics.create('cpt', 'ChargedParticleTracing', 'geom1');
cpt.label(sprintf('Charged Particle Tracing: oa-TOF ring-stack %s', label));
cpt.selection.named('sel_vac');
cpt.feature('pp1').label(sprintf('Particle properties: %gamu +1 ion', mass_amu));
cpt.feature('pp1').set('mp', sprintf('%.6e[kg]', m_kg));
cpt.feature('pp1').set('Z', '1');

% !!! Explicit Wall/Freeze condition on the detector's own boundary, per
% explicit request: previously the ion stopped at the detector only
% because it physically left 'sel_vac' (the CPT domain) upon reaching
% the detector's solid material -- an IMPLICIT side-effect of the
% domain selection, not a deliberately configured particle-wall
% interaction. Making it explicit (a real Wall feature with Freeze)
% is the correct, robust way to model "detector absorbs the ion on
% impact" rather than relying on the CPT solver's default behavior when
% a trajectory exits the tracked domain.
wall_det = cpt.create('wall_det', 'Wall', 2);
wall_det.label('Detector wall (freeze on impact)');
wall_det.selection.named('selb_detector');
wall_det.set('WallCondition', 'Freeze');

% !!! No dedicated wall_backplate CPT feature: backplate is a real solid
% again (per explicit request, see the geometry comment above), so it's
% excluded from sel_vac (the CPT domain) just like repeller/detector/the
% rings -- an off-nominal ion that ever reached it would get the same
% implicit domain-boundary stop those electrodes already rely on, no
% explicit Wall/Freeze needed (that was only added while backplate was an
% idealized zero-thickness boundary an ion could otherwise pass through).

v_in = sqrt(2*5*1.602176e-19/m_kg);
fprintf('\n5eV entrance speed (x-direction): %.4e m/s\n', v_in);
rel1 = cpt.create('rel1', 'Release', 3);
rel1.label('Release: Gaussian energy (5eV mean) along x (from RF quadrupole cooling guide)');
rel1.selection.named('geom1_relvol_dom');
% !!! Gaussian (Normal) energy spread around the 5eV mean, per explicit
% request, to test dispersion with a large particle count. COMSOL's
% InitialKineticEnergy property turned out to be a MODE-SELECTOR enum
% ("Expression"/"ConstantSpeedSpherical"/etc.), NOT a free expression
% field -- attempting a Gaussian formula there errors with "Invalid
% parameter value". The v0 (velocity) property, by contrast, IS a free
% expression field (already proven with plain numeric values throughout
% this project) -- so the Gaussian is embedded directly there instead,
% converting a Normal-distributed energy (mean 5eV, stdev 1eV) to speed
% via KE=0.5*m*v^2. randnormal(seed) is COMSOL's built-in standard-normal
% (mean 0, stdev 1) sampler; SamplingFromDistribution='Random' makes each
% released particle draw an independent sample (not the same value
% repeated for all).
rel1.set('SamplingFromDistribution', 'Random');
p.set('E_mean_eV', '5[V]', 'Mean ion kinetic energy entering the pusher');
p.set('E_std_eV', '1[V]', 'Ion kinetic energy spread (Gaussian stdev)');
% !!! randnormal() is NOT a recognized COMSOL function (confirmed via
% solve-time error "Unknown function or operator: randnormal") -- built a
% standard-normal sample manually via the Box-Muller transform using
% COMSOL's random() (uniform [0,1]) instead, which IS a known, documented
% CPT expression function for exactly this per-particle-randomization
% purpose.
rel1.set('v0', {sprintf('sqrt(2*abs(E_mean_eV+E_std_eV*sqrt(-2*log(random(1)))*cos(2*pi*random(2)))*1.602176e-19[C]/%.6e[kg])', m_kg) '0' '0'});
% !!! Default InitialPosition='MeshBased' with N=1 released particles
% from mesh vertices/elements directly (giving exactly 6, tied to
% relvol's own mesh density, not a deliberately chosen count).
% InitialPosition='Density' with N=<count> gives an explicit, requested
% total particle count instead, sampled within the release domain.
% Raised to 500 to test dispersion statistics with a large ensemble.
rel1.set('InitialPosition', 'Density');
rel1.set('N', num2str(n_particles));

% !!! Simplified per explicit request: no pulsing needed anymore -- ALL
% electrodes (reflectron rings/grids AND the accelerator's repeller/
% accelmid/gridA/gridB) are now combined into the SINGLE static 'es'
% solve, each at its own real, always-on voltage. The CPT force is just
% a direct reference to this one field, no unit-field scaling or sigmoid
% time-gating required.
ef1 = cpt.create('ef1', 'ElectricForce', 3);
ef1.label('Electric Force: combined static field (reflectron + accelerator, all electrodes always on)');
ef1.selection.named('sel_vac');
ef1.set('E_src', 'userdef');
% !!! field_mode now supports independent per-zone theory overrides (doc
% §7.52, per explicit request to localize the resolution bottleneck to
% ONE of: accelerator / field-free drift / stage1 reflectron / stage2
% reflectron): 'real' (everything from the solved FEM field), 'ideal'
% (everything theoretical), 'ideal_accel', 'ideal_drift', 'ideal_stage1',
% 'ideal_stage2' (each replaces ONLY that one zone with its closed-form
% theory value, all other zones stay real -- isolates that zone's own
% contribution to R), and 'ideal_reflectron' (both stage1+stage2
% replaced, accelerator+drift stay real -- kept for backward
% compatibility with §7.35/7.50 runs). Built by choosing, per z-region,
% whether to use the real es.E* or the ideal piecewise-constant theory
% value.
% !!! SIGN: the accelerator region has V DECREASING with z (repeller
% high -> grid2 low), so Ez=-dV/dz is POSITIVE there (pushing the
% positive ion forward, +z) -- confirmed against the real solved
% field's own measured sign (z=0.2mm: Ez=+159532 V/m). The reflectron
% region has V INCREASING with z (entgrid 0 -> backplate high) as the
% ion decelerates, so Ez=-dV/dz is NEGATIVE there.
Ez_accel_ideal = ['if(z<3[mm],(V_repeller-V_grid1)/3[mm],V_grid1/(L_accel-3[mm]))'];
Ez_drift_ideal = '0';
Ez_stage1_ideal = '-V_mid/L_stage1';
Ez_stage2_ideal = '-(V_mirror-V_mid)/(L_refl-L_stage1)';
use_ideal_accel  = any(strcmpi(field_mode, {'ideal','ideal_accel'}));
use_ideal_drift  = any(strcmpi(field_mode, {'ideal','ideal_drift'}));
use_ideal_stage1 = any(strcmpi(field_mode, {'ideal','ideal_reflectron','ideal_stage1'}));
use_ideal_stage2 = any(strcmpi(field_mode, {'ideal','ideal_reflectron','ideal_stage2'}));
if use_ideal_accel || use_ideal_drift || use_ideal_stage1 || use_ideal_stage2
    if use_ideal_accel, accel_piece = Ez_accel_ideal; else, accel_piece = 'es.Ez'; end
    if use_ideal_drift, drift_piece = Ez_drift_ideal; else, drift_piece = 'es.Ez'; end
    if use_ideal_stage1, stage1_piece = Ez_stage1_ideal; else, stage1_piece = 'es.Ez'; end
    if use_ideal_stage2, stage2_piece = Ez_stage2_ideal; else, stage2_piece = 'es.Ez'; end
    Ez_ideal = sprintf('if(z<L_accel,%s,if(z<L_flight,%s,if(z<L_flight+L_stage1,%s,if(z<L_flight+L_refl,%s,es.Ez))))', ...
        accel_piece, drift_piece, stage1_piece, stage2_piece);
    % Ex/Ey: zero within whichever region(s) use the ideal (pure-1D)
    % theory; real es.Ex/es.Ey everywhere else.
    ex_conditions = {};
    if use_ideal_accel,  ex_conditions{end+1} = 'z<L_accel'; end
    if use_ideal_drift,  ex_conditions{end+1} = '(z>=L_accel&&z<L_flight)'; end
    if use_ideal_stage1, ex_conditions{end+1} = '(z>=L_flight&&z<L_flight+L_stage1)'; end
    if use_ideal_stage2, ex_conditions{end+1} = '(z>=L_flight+L_stage1&&z<L_flight+L_refl)'; end
    ex_cond_str = strjoin(ex_conditions, '||');
    Ex_ideal = sprintf('if(%s,0,es.Ex)', ex_cond_str);
    Ey_ideal = sprintf('if(%s,0,es.Ey)', ex_cond_str);
    ef1.set('E', {Ex_ideal, Ey_ideal, Ez_ideal});
else
    ef1.set('E', {'es.Ex', 'es.Ey', 'es.Ez'});
end

% !!! Distance estimate updated to match the extended L_flight=3000mm
% (was hardcoded 0.36m = 0.3+0.03 margin for the old 300mm flight tube;
% now 3.0+0.03=3.03m, same ~9% margin factor as before).
v_push_speed = sqrt(2*2000*1.602176e-19/m_kg);
% !!! Distance estimate updated for the new, much shorter L_flight=320mm
% (was 3.30m for the old 3000mm design; new: L_flight+L_refl/2+margin
% =320+45=365mm, *1.09 margin factor=~0.40m).
% !!! Distance estimate updated for L_flight extended to 600mm (doc
% §7.49, was 500mm): +100mm added to the previous 1.1m estimate.
t_flight_oneway = 1.2/v_push_speed;
fprintf('push-direction speed at 2000eV: %.4e m/s\n', v_push_speed);
fprintf('estimated one-way flight time: %.3fus, round trip ~%.3fus\n', t_flight_oneway*1e6, 2*t_flight_oneway*1e6);

% !!! Widened margin further (4.0->8.0): with the idealized-grid rebuild
% (zero field leakage, full ideal field strength), the ion's z_max
% stopped exactly at 300.00mm (the reflectron entrance) -- it hadn't even
% penetrated the reflectron yet when Tsim ran out, let alone completed a
% round trip. The much cleaner/stronger field changes the flight-time
% profile enough that the old margin (already generous for the leaky
% design) is no longer sufficient.
% !!! Two-phase adaptive Tsim (doc §6.14): a live in-solver StopCondition
% ("stop once all particles have reached the detector") was investigated
% extensively and found to be architecturally blocked -- every
% particle-aggregation mechanism in COMSOL's Particle Tracing Module
% (ParticleCounter.Nsel, BoundaryAccumulator's built-in globals, and the
% module's own built-in cpt.max/min/sum(...) per-particle couplings) only
% evaluates post-hoc via mphparticle, never live inside StopCondition's
% own expression evaluator ("Unknown function or operator"/"Undefined
% variable" every time, confirmed on this exact production model, not a
% naming issue). The working alternative: solve first with a SHORT,
% physics-based margin (1.5x estimated round-trip time, not the blanket
% 8x), then
% check completeness post-hoc with plain mphparticle; only fall back to
% the full 8x margin (re-solving from scratch) in the rare case the short
% one wasn't enough. Verified: R and detection times come out
% bit-identical whether the short margin succeeds directly or falls back
% to the full margin (deterministic particle release seed), so this has
% zero accuracy impact -- it only ever removes wasted tail computation
% for parameter combinations where the short margin already suffices.
Tsim_short = 2*t_flight_oneway*1.5 + 1e-6;
Tsim_full = 2*t_flight_oneway*8.0 + 1e-6;
Tsim = Tsim_short;
std2 = model.study.create('std2');
std2.label(sprintf('Time-dependent: oa-TOF ring-stack %s', label));
tstep = std2.create('time1', 'Transient');
tstep.label('Transient solver');
% !!! Post-pulse grid coarsened 10x (50ns->500ns): with L_flight
% extended 10x, Tsim is also ~10x longer, so the OLD 50ns step would
% store ~10x more time points per particle than before -- combined with
% a large particle count, this is exactly the kind of avoidable data
% volume that caused the N=50000 mphparticle() OOM crash. The fine 5ns
% grid during the pulse (0-1us) is kept as-is since that resolution is
% needed for solver accuracy on the fast pulse rise/fall, not just
% output sampling.
% !!! Reverted to the memory-efficient coarsened OUTPUT tlist now that
% 'tstepsbdf'='free' (see below) lets the solver internally integrate
% with as fine a step as accuracy demands, independent of this output
% grid -- the earlier bug was 'strict' forcing the SOLVER's own internal
% steps to match this coarse grid, not the output density itself.
% !!! FIXED root cause of the compact-design resolution failure: the
% reflectron TRANSIT (entry, decelerate, turnaround, re-accelerate, exit
% -- all within the short 10-90mm reflectron) happens in only a few us
% for this compact design (one-way flight ~t_flight_oneway), much faster
% than the OLD 3000mm design's slow transit. The previous 500ns-post-1us
% coarsening was fine for the old design but FAR too coarse here --
% verified (N=5, uniform 5ns tlist) that it silently made ions overshoot
% into the backplate (integration error, not a real physics/field issue:
% z_max=409mm/backplate at 500ns resolution vs z_max=362mm matching
% theory at 5ns resolution). Fix: keep 5ns resolution through a window
% safely bracketing the reflectron transit (0 to 3*t_flight_oneway,
% covering approach+transit+return-start), coarsen only AFTER that
% (500ns), where motion is simple field-free drift needing no fine
% resolution. This avoids both the integration-accuracy bug AND the
% N=50000-scale OOM risk from fine-sampling the WHOLE round trip.
% !!! N=10000 mphparticle() OOM (GPU test: CPT solve succeeded in 351s,
% but retrieving the full qx+qy+qz trajectory ran out of SERVER memory
% during serialization) is now fixed differently: instead of risking
% accuracy by further coarsening this validated tlist (an attempted
% coarse-fine-coarse rework WRECKED accuracy, R dropped 1033.7->266.8 at
% N=20, because 1us steps couldn't resolve the accelerator's own fast
% 0.545us transit even with tstepsbdf='free') -- the fix is instead to
% reduce what's PULLED from the server: fetch only 'qz' (not qx,qy,qz)
% for the full statistics population, which cuts the transferred data
% volume 3x on its own (see the mphparticle call below). Reverted to
% this original, validated tlist (fine 5ns through 3*t_flight_oneway,
% covering the full round trip incl. accelerator + reflectron transit
% with margin; coarse 500ns after).
% !!! Set to 1ns per explicit request after the ring-center-alignment
% fix (see doc §7.33/7.34): confirms whether the fix's effect is real
% physics or just changes how much is masked by 5ns quantization noise.
% !!! Speed optimization: the OLD tlist kept 1ns resolution across the
% ENTIRE 0-to-3*t_flight_oneway window (~53us), including the "boring"
% constant-velocity drift from the accelerator exit (t~0.5us) out to the
% reflectron entrance (t~8-9us) -- a stretch where the ion feels NO
% force at all, so fine resolution there buys nothing but cost. New
% 4-segment tlist: fine(1ns) only for 0-2us (covers the accelerator's
% own fast ~0.545us transit with margin) and 6-33us (covers the
% reflectron approach/transit/return/detection, with generous margin
% around the measured ~29.7us mean detection time); coarse(500ns)
% elsewhere, where the ion is just drifting at constant velocity with
% no field. This roughly HALVES the total stored timesteps (~53580 ->
% ~27500) without touching resolution anywhere the ion is actually
% under a force -- validated by confirming R is unchanged vs the old
% uniform-1ns tlist (see doc §7.37).
% !!! Fine window extended from 33us to 39us (doc §7.49): L_flight
% extended by 100mm (500->600mm) adds ~3.2us to the round-trip time
% (estimated from the extra 200mm total drift / v_push_speed), pushing
% the expected mean detection time to ~33-34us -- the old 33us cutoff
% would now clip the actual detection event. 39us keeps a healthy margin.
% !!! Speed optimization ATTEMPTED ("fix B", per explicit request) and
% REVERTED: tried narrowing this fine 1ns window adaptively (fine_start=
% 0.5*t_flight_oneway, fine_end=2.5*t_flight_oneway, ~24us instead of
% 33us) on the theory that 'tstepsbdf'='free' fully decouples solver
% accuracy from the OUTPUT tlist's density, so a shorter requested-output
% window should only cut solve time, not accuracy. Measured result
% CONTRADICTED that theory: CPT solve time did drop (128.4s->98.1s,
% ~24%), but R dropped too (14988.6->9099.5, detTime std nearly doubled
% 0.66ns->1.09ns) -- a real, reproducible accuracy regression, NOT
% sampling noise (particle release is deterministically seeded here, two
% separate unmodified re-runs gave bit-identical R/detTimes). The exact
% mechanism isn't fully understood (mean detection time sat >10us inside
% the new window's fine_end, nowhere near the boundary, so simple
% edge-clipping doesn't explain it -- 'free' tstepsbdf evidently does NOT
% fully insulate result precision from the output tlist's shape the way
% the existing doc comments assumed). Given the explicit "must not affect
% resolution" requirement, this trade was rejected and the window
% reverted to the original, previously-validated 6us/39us literals.
% Speeding up the CPT solve itself needs a different lever than shrinking
% this output window -- left as a genuinely open problem, do not retry
% this exact approach without first understanding why 'free' didn't
% decouple accuracy from tlist density here.
fine_start = 6e-6;
fine_end = 39e-6;
tstep.set('tlist', sprintf('range(0,1e-9,2e-6) range(2e-6+500e-9,500e-9,%.9g) range(%.9g+1e-9,1e-9,%.9g) range(%.9g+500e-9,500e-9,%g)', fine_start, fine_start, fine_end, fine_end, Tsim));
tstep.setEntry('activate', 'es', false);
tstep.setEntry('activate', 'cpt', true);
cpt.feature('pp1').set('StudyStep', 'std2/time1');
rel1.set('StudyStep', 'std2/time1');

soltags = cell(model.sol.tags());
es_sol_tag = soltags{1};
model.sol.create('sol2');
model.sol('sol2').label(sprintf('Solution: oa-TOF CPT ring-stack %s', label));
model.sol('sol2').study('std2');
model.sol('sol2').createAutoSequence('std2');
model.sol('sol2').feature('v1').set('notsolmethod', 'sol');
model.sol('sol2').feature('v1').set('notsol', es_sol_tag);
% Attach the configured solver so the Study's GUI Compute reuses sol2
% instead of creating a default zero-field CPT solver.
model.sol('sol2').attach('std2');
% !!! FIXED root cause of the compact-design resolution failure: 'strict'
% forces the BDF solver to use EXACTLY the tlist steps as its OWN
% internal integration steps (not just for output) -- with the old
% 3000mm design's slow, gentle dynamics this was fine even at 500ns
% steps, but the new compact design's fast reflectron transit (full
% deceleration+turnaround over ~10-90mm in a few us) needs much finer
% resolution to integrate accurately. 'strict' at 500ns silently
% produced wrong (too-deep) turnaround points, causing many ions to
% overshoot into the backplate. 'free' lets the solver adaptively
% refine its internal steps for accuracy while still only OUTPUTTING at
% the requested tlist points -- verified (N=5) to fix the turnaround
% (z_max=362mm matching theory almost exactly, was 409mm/backplate) and
% recover R=75.6 (was 14.7) with 100% detection (was 80.7%).
model.sol('sol2').feature('t1').set('tstepsbdf', 'free');
% !!! FIX for the N>=20 crash ("NaN or Inf found when solving linear
% system using GMRES", t=6.38us, deterministic regardless of N):
% inspection showed the Time-Dependent solver's FullyCoupled nonlinear
% solver (fc1) uses the Iterative linear solver (i1, GMRES-based) by
% default. Switching to the Direct solver (dDef, e.g. MUMPS/PARDISO)
% should be far more numerically robust against whatever ill-conditioned
% situation a specific particle's trajectory triggers (GMRES can fail to
% converge on a hard step; a direct solve doesn't have that failure
% mode).
model.sol('sol2').feature('t1').feature('fc1').set('linsolver', 'dDef');
% !!! Configure the ACTUAL underlying direct-solver engine used by
% 'dDef' (mumps/pardiso on CPU, or cudss on GPU) per solver_mode --
% distinct from the 'linsolver'='dDef' setting above, which just tells
% fc1 to use the dDef FEATURE (as opposed to the iterative i1 feature
% that caused the N>=20 crash).
if strcmpi(solver_mode, 'gpu')
    model.sol('sol2').feature('t1').feature('dDef').set('linsolver', 'cudss');
else
    model.sol('sol2').feature('t1').feature('dDef').set('linsolver', 'pardiso');
end
t_cptsetup = toc(t_cptsetup_start);
fprintf('[TIMING] CPT setup (physics/release/study/solver config, before solve): %.2fs\n', t_cptsetup);
t_cpt_start = tic;
model.sol('sol2').runAll;
t_cpt = toc(t_cpt_start);
fprintf('[%s] SUCCESS: oa-TOF ring-stack CPT solved (%s, %.2fs for N=%s particles, Tsim=%.4gus short margin).\n', ...
    label, upper(solver_mode), t_cpt, rel1.getString('N'), Tsim*1e6);

% Two-phase completeness check (doc §6.14): confirm all released particles
% actually reached the detector within the short margin; if not, extend to
% the full 8x margin and re-solve from scratch. qz is already in
% geom1.lengthUnit ('mm'), NOT SI meters -- do not rescale (this bit us
% once during development: rescaling qz by 1e3 on top of an already-mm
% value caused a false "0/N detected" and an unnecessary retry every time).
pdset_check = model.result.dataset.create('pdset_check', 'Particle');
pdset_check.set('solution', 'sol2');
N_total_check = str2double(rel1.getString('N'));
qzcheck = mphparticle(model, 'dataset', 'pdset_check', 'expr', {'qz'});
zfinal_check = qzcheck.d1(end,:);
detector_z_val_mm = mphevaluate(model, 'detector_z', 'mm');
n_detected_check = sum(abs(zfinal_check - detector_z_val_mm) < 2);
fprintf('[%s] two-phase check: %d/%d particles reached detector (z=%.4gmm) within short margin.\n', ...
    label, n_detected_check, N_total_check, detector_z_val_mm);
if n_detected_check < N_total_check
    fprintf('[%s] short margin insufficient -- re-solving with full 8x margin (Tsim=%.4gus).\n', label, Tsim_full*1e6);
    Tsim = Tsim_full;
    tstep.set('tlist', sprintf('range(0,1e-9,2e-6) range(2e-6+500e-9,500e-9,%.9g) range(%.9g+1e-9,1e-9,%.9g) range(%.9g+500e-9,500e-9,%g)', fine_start, fine_start, fine_end, fine_end, Tsim));
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

% !!! ATTEMPTED to reduce the N=10000 mphparticle() OOM (server ran out
% of memory serializing the full qx,qy,qz trajectory) by requesting only
% 'qz' via the 'expr' option -- but verified this does NOT actually
% reduce transferred data: pd_z.p still comes back as [ntime x nP x 3]
% regardless (checked directly: size stayed [11086 50 3] instead of
% shrinking to 2D). So 'expr' only affects what MATLAB is TOLD to look
% at, not what the server sends -- the real fix has to be reducing N or
% timesteps instead. Extracting the z-component explicitly here (index
% 3) since the array is still 3D despite requesting just 'qz'.
pd_z = mphparticle(model, 'dataset', 'pdset1');
t = pd_z.t;
z = squeeze(pd_z.p(:,:,3));
% !!! Per explicit speed-optimization request: also keep x/y here (were
% previously discarded -- only z was extracted from this same pd_z.p
% array) so the trajectory-plot section below can reuse this ALREADY-
% SOLVED data instead of re-running the entire CPT solve a second time
% just to get x/y. See the trajectory-plot section for why a second
% solve is still needed when nP is large.
x_full = squeeze(pd_z.p(:,:,1));
y_full = squeeze(pd_z.p(:,:,2));
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
    label, penetration_max_mm, penetration_stage2_max_mm, nP, d2min_mm, d2_mm, d2_margin_frac*100);
fprintf('[%s] stage2 penetration_max vs d2_min: diff=%.3fmm (%.2f%% of d2_min)\n', ...
    label, penetration_stage2_max_mm-d2min_mm, 100*(penetration_stage2_max_mm-d2min_mm)/d2min_mm);

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
wasup_thresh = p.evaluate('detector_z','mm') * 2;
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
    wasUp = false;
    wasUpIdx = NaN;
    detected = false;
    for k = 1:numel(zi)
        if isnan(zi(k)), break; end
        if zi(k) > wasup_thresh && ~wasUp, wasUp = true; wasUpIdx = k; end
        if wasUp && zi(k) < det_z_thresh
            detTimes(i) = interp_crossing_time(t, zi, k, detector_z_exact);
            detected = true;
            break;
        end
    end
    if ~detected && wasUp
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
        near_det = find(abs(zi(wasUpIdx:end) - detector_z_exact) < det_freeze_tol, 1, 'first');
        if ~isempty(near_det)
            k2 = wasUpIdx + near_det - 1;
            detTimes(i) = interp_crossing_time(t, zi, k2, detector_z_exact);
        end
    end
end
meanT = mean(detTimes,'omitnan'); stdT = std(detTimes,'omitnan');
nDet = sum(~isnan(detTimes));
fprintf('[%s] detected on detector plate: %d/%d, arrival time: mean=%.5fus, std=%.5fus\n', label, nDet, nP, meanT*1e6, stdT*1e6);
% Mass resolution R=m/dm=t/(2*sigma_t) (standard TOF convention).
R_resolution = meanT/(2*stdT);
fprintf('[%s] mass resolution R=t/(2*sigma_t) = %.1f\n', label, R_resolution);

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
    'detTimes', detTimes, 'meanT', meanT, 'stdT', stdT, 'nDet', nDet, ...
    'penetration_max_mm', penetration_max_mm, 'd2min_mm', d2min_mm, 'd2_mm', d2_mm);

resultsDir = paths.comsolResultsDir;
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
m_app = mass_amu*(detected_t/meanT).^2;
mass_sigma = std(m_app);
mass_grid = linspace(mean(m_app)-4*mass_sigma, mean(m_app)+4*mass_sigma, 201);
mass_bandwidth = max(1.06*mass_sigma*numel(m_app)^(-1/5), 1e-6);
mass_density = mean(exp(-0.5*((mass_grid(:)-m_app(:).')/mass_bandwidth).^2), 2) ./ (sqrt(2*pi)*mass_bandwidth);
mass_intensity = mass_density * numel(m_app) * mean(diff(mass_grid));
plot(mass_grid, mass_intensity, '-');
xlabel('apparent mass [Da]'); ylabel('intensity [counts]'); grid on;
title(sprintf('mass peak (Gaussian KDE, R=%.0f, N=%d)', R_resolution, nDet));

% !!! Title now includes N (statistical sample size, nP -- NOT the N_plot=50
% trajectory-rendering subset) and field_mode, per doc convention (always
% show sample size so a reader can't mistake an N=100 result for N=1000,
% see COMSOL_调试方法�?md 统计陷阱一�?. Also dropped the hardcoded
% "V_mirror=4551.15V" that was stale (V_mirror is now computed dynamically
% per d1_mm/d2_margin_frac and no longer a fixed literal) in favor of the
% actual computed value.
sgtitle({sprintf('oa-TOF two-stage ring-stack reflectron: %s (N=%d, field_mode=%s)', label, nP, field_mode), ...
    sprintf('%gamu +1 ion, 5eV in x, three-grid accelerator (KE0=2000eV), d1=%gmm, V_mirror=%.2fV, R=%.1f', mass_amu, d1_mm, V_mirror_V, R_resolution)}, 'Interpreter','none');
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
t_resultplots_start = tic;
try
    cpl_y0 = model.result.dataset.create('cpl_y0', 'CutPlane');
    cpl_y0.label('y=0 cross-section (r-z profile)');
    cpl_y0.set('quickplane', 'zx');
    cpl_y0.set('quicky', '0');
    fprintf('[%s] SUCCESS: shared y=0 CutPlane dataset (cpl_y0) created.\n', label);
catch ME
    fprintf('[%s] WARNING: CutPlane dataset creation failed (%s) -- field heatmaps below will be skipped.\n', label, ME.message);
end

% Full-device theoretical target, independent of field_mode. This fixes
% the old diagnostic's blind spot at z<L_flight: both accelerator stages
% and the zero-field drift are now included with the two reflectron stages.
Ez_ideal_full_expr = sprintf(['if(z<0||z>L_flight+L_refl,NaN,' ...
    'if(z<L_accel,%s,if(z<L_flight,%s,' ...
    'if(z<L_flight+L_stage1,%s,%s))))'], ...
    Ez_accel_ideal, Ez_drift_ideal, Ez_stage1_ideal, Ez_stage2_ideal);
Ez_diff_full_expr = sprintf('es.Ez-(%s)', Ez_ideal_full_expr);
Ez_signedlog_expr = 'sign(es.Ez)*log10(1+abs(es.Ez)/(1[V/m]))';
Ez_diff_signedlog_expr = sprintf('sign(%s)*log10(1+abs(%s)/(1[V/m]))', ...
    Ez_diff_full_expr, Ez_diff_full_expr);
Eres_drift_log_expr = ['if(z<L_accel||z>L_flight,NaN,' ...
    'log10(1+sqrt(es.Ex^2+es.Ey^2+es.Ez^2)/(1[V/m])))'];
try
    % (1) Full-domain real-ideal difference. Signed-log compression keeps
    % weak leakage visible beside strong edge fields and retains its sign.
    pg_field_diff = model.result.create('pg_field_diff', 'PlotGroup2D');
    pg_field_diff.label(sprintf('1 Field error, full domain, signed log: %s', label));
    pg_field_diff.set('data', 'cpl_y0');
    pg_field_diff.set('titletype', 'manual');
    pg_field_diff.set('title', 'signed log10(1+|Ez(real)-Ez(ideal)|/1V/m), full device; sign retained');
    sf_diff = pg_field_diff.create('sf_diff', 'Surface');
    sf_diff.label('signed-log full-domain Ez error');
    sf_diff.set('expr', Ez_diff_signedlog_expr);
    pg_field_diff.run;
    fprintf('[%s] SUCCESS: full-domain signed-log field-error heatmap created.\n', label);
catch ME
    fprintf('[%s] WARNING: field leakage diagnostic heatmap failed (%s).\n', label, ME.message);
end
try
    % (2) Full-domain actual Ez with the same signed-log convention.
    pg_field_full = model.result.create('pg_field_full', 'PlotGroup2D');
    pg_field_full.label(sprintf('2 Actual Ez, full domain, signed log: %s', label));
    pg_field_full.set('data', 'cpl_y0');
    pg_field_full.set('titletype', 'manual');
    pg_field_full.set('title', 'signed log10(1+|Ez|/1V/m), full device; sign retained');
    sf_full = pg_field_full.create('sf_full', 'Surface');
    sf_full.label('signed-log actual Ez');
    sf_full.set('expr', Ez_signedlog_expr);
    pg_field_full.run;
    fprintf('[%s] SUCCESS: full-domain signed-log actual-field heatmap created.\n', label);
catch ME
    fprintf('[%s] WARNING: full-domain field heatmap failed (%s).\n', label, ME.message);
end
try
    % (3) Total residual magnitude in the nominally field-free drift. This
    % catches transverse shield/end leakage that an Ez-only plot misses.
    pg_field_drift = model.result.create('pg_field_drift', 'PlotGroup2D');
    pg_field_drift.label(sprintf('3 Drift residual field magnitude, log: %s', label));
    pg_field_drift.set('data', 'cpl_y0');
    pg_field_drift.set('titletype', 'manual');
    pg_field_drift.set('title', 'log10(1+|E|/1V/m), nominally field-free drift only');
    sf_drift = pg_field_drift.create('sf_drift', 'Surface');
    sf_drift.label('log residual total field in drift');
    sf_drift.set('expr', Eres_drift_log_expr);
    pg_field_drift.run;
    fprintf('[%s] SUCCESS: drift residual-field heatmap created.\n', label);
catch ME
    fprintf('[%s] WARNING: drift residual-field heatmap failed (%s).\n', label, ME.message);
end
try
    % (4) Quantitative axial profiles at five radii. They deliberately
    % cover only the reflectron: the off-axis accelerator has a different
    % physical axis, so a single fixed-x full-device line is misleading.
    % Stay 0.1 mm off the grids/plate to avoid material-boundary samples.
    Lf_mm_plot = p.evaluate('L_flight', 'mm');
    Lr_mm_plot = p.evaluate('L_refl', 'mm');
    bore_mm_plot = p.evaluate('bore_r', 'mm');
    xr_mm_plot = p.evaluate('x_refl_center', 'mm');
    zprof_mm = linspace(Lf_mm_plot+0.1, Lf_mm_plot+Lr_mm_plot-0.1, 801);
    rfrac = [0, 0.2, 0.4, 0.6, 0.8];
    dEz_prof = NaN(numel(zprof_mm), numel(rfrac));
    for ir = 1:numel(rfrac)
        coord_prof = [repmat(xr_mm_plot+rfrac(ir)*bore_mm_plot, 1, numel(zprof_mm)); ...
                      zeros(1, numel(zprof_mm)); zprof_mm];
        dEz_prof(:,ir) = mphinterp(model, Ez_diff_full_expr, 'coord', coord_prof, ...
            'dataset', 'dset1', 'matherr', 'off').';
    end
    % es.Ez is the derivative of the finite-element potential and is not
    % continuous across first-order tetrahedron faces. Dense line samples
    % therefore expose element-scale sawteeth even though V is continuous.
    % A 9-point Savitzky-Golay window spans only ~2.1 mm here, far below
    % the shortest ring pitch (~14.5 mm): it removes mesh-face jitter but
    % retains the physically meaningful ring-stack ripple. Preserve the
    % unfiltered samples in a separate native table for audit/convergence.
    dEz_prof_raw = dEz_prof;
    dEz_prof = smoothdata(dEz_prof, 1, 'sgolay', 9);
    tbl_fieldprof_raw = model.result.table.create('tbl_fieldprof_raw', 'Table');
    tbl_fieldprof_raw.label(sprintf('RAW reflectron axial Ez-error profiles: %s', label));
    tbl_fieldprof_raw.comments('Unsmoothed FEM-gradient samples for mesh-convergence audit [V/m]');
    tbl_fieldprof_raw.setTableData([zprof_mm(:), dEz_prof_raw]);
    tbl_fieldprof_raw.setColumnHeaders({'z [mm]', 'r/bore=0', 'r/bore=0.2', ...
        'r/bore=0.4', 'r/bore=0.6', 'r/bore=0.8'});
    tbl_fieldprof = model.result.table.create('tbl_fieldprof', 'Table');
    tbl_fieldprof.label(sprintf('Reflectron axial Ez-error profiles: %s', label));
    tbl_fieldprof.comments('SG-smoothed (~2.1mm window) dEz at r/bore = 0, 0.2, 0.4, 0.6, 0.8 [V/m]; raw samples in tbl_fieldprof_raw');
    tbl_fieldprof.setTableData([zprof_mm(:), dEz_prof]);
    tbl_fieldprof.setColumnHeaders({'z [mm]', 'r/bore=0', 'r/bore=0.2', 'r/bore=0.4', ...
        'r/bore=0.6', 'r/bore=0.8'});
    pg_fieldprof = model.result.create('pg_fieldprof', 'PlotGroup1D');
    pg_fieldprof.label(sprintf('4 Reflectron axial Ez error at five radii: %s', label));
    pg_fieldprof.set('titletype', 'manual');
    pg_fieldprof.set('title', 'Ez(real)-Ez(ideal) versus z at five radii (SG display smoothing; raw table retained)');
    pg_fieldprof.set('xlabel', 'z [mm]');
    pg_fieldprof.set('ylabel', 'Ez(real)-Ez(ideal) [V/m]');
    tg_fieldprof = pg_fieldprof.create('tg_fieldprof', 'Table');
    tg_fieldprof.label('Five axial Ez-error profiles');
    tg_fieldprof.set('table', 'tbl_fieldprof');
    tg_fieldprof.set('plotcolumninput', 'manual');
    tg_fieldprof.set('xaxisdata', '1');
    tg_fieldprof.set('plotcolumns', '2,3,4,5,6');
    % Multi-curve plots must carry an explicit, physically meaningful
    % legend (COMSOL defaults this Table Graph to legend=off and generic
    % generic column labels, which violates the project plotting rules).
    tg_fieldprof.set('legend', 'on');
    tg_fieldprof.set('legendmethod', 'manual');
    tg_fieldprof.set('legends', {'r/bore=0', 'r/bore=0.2', 'r/bore=0.4', ...
        'r/bore=0.6', 'r/bore=0.8'});
    tg_fieldprof.set('showwidth', 'on');
    tg_fieldprof.set('linewidth', '2');
    pg_fieldprof.run;
    fprintf('[%s] SUCCESS: five-radius axial Ez-error profile plot created.\n', label);
catch ME
    fprintf('[%s] WARNING: five-radius axial field-error profile failed (%s).\n', label, ME.message);
end
try
    % (5) Complementary radial profiles at three depths in each stage.
    % This makes the z-dependence explicit without mixing z and r on one
    % horizontal axis. Normalize r by bore_r so future bore scans remain
    % directly comparable; stop at 0.8*bore_r per the selected useful
    % aperture and to avoid edge singularities.
    L1_mm_plot = p.evaluate('L_stage1', 'mm');
    L2_mm_plot = Lr_mm_plot-L1_mm_plot;
    stage1frac = [0.25, 0.50, 0.75];
    % Formal maximum stage-2 penetration is 51.07mm = 58.8% of L2, so
    % stage2 75% is never sampled by an ion and is intentionally omitted.
    stage2frac = [0.25, 0.50];
    zslice_mm = [Lf_mm_plot+stage1frac*L1_mm_plot, ...
        Lf_mm_plot+L1_mm_plot+stage2frac*L2_mm_plot];
    rn_prof = linspace(0, 0.8, 301);
    dEz_radial = NaN(numel(rn_prof), numel(zslice_mm));
    for iz = 1:numel(zslice_mm)
        coord_radial = [xr_mm_plot+rn_prof*bore_mm_plot; ...
                        zeros(1, numel(rn_prof)); ...
                        repmat(zslice_mm(iz), 1, numel(rn_prof))];
        dEz_radial(:,iz) = mphinterp(model, Ez_diff_full_expr, 'coord', coord_radial, ...
            'dataset', 'dset1', 'matherr', 'off').';
    end
    dEz_radial_raw = dEz_radial;
    % Seven radial samples span ~4.0mm, still far below ring pitch and
    % small compared with bore_r; preserve raw values in a separate table.
    dEz_radial = smoothdata(dEz_radial, 1, 'sgolay', 7);
    radial_legends = {'stage1 z/L1=0.25', 'stage1 z/L1=0.50', 'stage1 z/L1=0.75', ...
        'stage2 z/L2=0.25', 'stage2 z/L2=0.50'};
    tbl_fieldradial_raw = model.result.table.create('tbl_fieldradial_raw', 'Table');
    tbl_fieldradial_raw.label(sprintf('RAW reflectron radial Ez-error profiles: %s', label));
    tbl_fieldradial_raw.comments('Unsmoothed FEM-gradient samples for mesh-convergence audit [V/m]');
    tbl_fieldradial_raw.setTableData([rn_prof(:), dEz_radial_raw]);
    tbl_fieldradial_raw.setColumnHeaders([{'r/bore'}, radial_legends]);
    tbl_fieldradial = model.result.table.create('tbl_fieldradial', 'Table');
    tbl_fieldradial.label(sprintf('Reflectron radial Ez-error profiles at five z positions: %s', label));
    tbl_fieldradial.comments('SG-smoothed (~4.0mm radial window) dEz at ion-accessible stage depths [V/m]; raw samples in tbl_fieldradial_raw');
    tbl_fieldradial.setTableData([rn_prof(:), dEz_radial]);
    tbl_fieldradial.setColumnHeaders([{'r/bore'}, radial_legends]);
    pg_fieldradial = model.result.create('pg_fieldradial', 'PlotGroup1D');
    pg_fieldradial.label(sprintf('5 Reflectron radial Ez error at five z positions: %s', label));
    pg_fieldradial.set('titletype', 'manual');
    pg_fieldradial.set('title', 'Ez(real)-Ez(ideal) versus r/bore at five ion-accessible depths (SG display smoothing)');
    pg_fieldradial.set('xlabel', 'r/bore');
    pg_fieldradial.set('ylabel', 'Ez(real)-Ez(ideal) [V/m]');
    tg_fieldradial = pg_fieldradial.create('tg_fieldradial', 'Table');
    tg_fieldradial.label('Five z-position radial Ez-error profiles');
    tg_fieldradial.set('table', 'tbl_fieldradial');
    tg_fieldradial.set('plotcolumninput', 'manual');
    tg_fieldradial.set('xaxisdata', '1');
    tg_fieldradial.set('plotcolumns', '2,3,4,5,6');
    tg_fieldradial.set('legend', 'on');
    tg_fieldradial.set('legendmethod', 'manual');
    tg_fieldradial.set('legends', radial_legends);
    tg_fieldradial.set('showwidth', 'on');
    tg_fieldradial.set('linewidth', '2');
    pg_fieldradial.run;
    fprintf('[%s] SUCCESS: five-z-position radial Ez-error profile plot created.\n', label);
catch ME
    fprintf('[%s] WARNING: five-z-position radial field-error profile failed (%s).\n', label, ME.message);
end
try
    tbl_ms = model.result.table.create('tbl_massspec', 'Table');
    tbl_ms.label(sprintf('Mass spectrum data: %s', label));
    tbl_ms.comments(sprintf('%s: Gaussian-KDE apparent-mass intensity, R=%.1f, N=%d, bandwidth=%.6gDa', label, R_resolution, nDet, mass_bandwidth));
    tbl_ms.setTableData([mass_grid(:), mass_intensity(:)]);
    pg_ms = model.result.create('pg_massspec', 'PlotGroup1D');
    pg_ms.label(sprintf('Mass spectrum: %s', label));
    pg_ms.set('titletype', 'manual');
    pg_ms.set('title', sprintf('Mass spectrum (apparent mass, R=%.1f, N=%d)', R_resolution, nDet));
    pg_ms.set('xlabel', 'apparent mass [Da]');
    pg_ms.set('ylabel', 'intensity [counts]');
    tg_ms = pg_ms.create('tg_ms', 'Table');
    tg_ms.label('Mass spectrum (Table Graph)');
    tg_ms.set('table', 'tbl_massspec');
    tg_ms.set('plotcolumninput', 'manual');
    tg_ms.set('xaxisdata', '1');
    tg_ms.set('plotcolumns', '2');
    pg_ms.run;
    fprintf('[%s] SUCCESS: mass spectrum table plot (pg_massspec) created.\n', label);
catch ME
    fprintf('[%s] WARNING: mass spectrum table plot failed (%s).\n', label, ME.message);
end
t_resultplots = toc(t_resultplots_start);
fprintf('[TIMING] native Result plots (5 field diagnostics + mass spectrum table): %.2fs\n', t_resultplots);

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
if strcmpi(strtrim(label), 'Final')
    modelsDir = paths.comsolFormalDir;
else
    modelsDir = paths.comsolScratchDir;
end
if ~exist(modelsDir, 'dir'), mkdir(modelsDir); end
model.save(fullfile(modelsDir, sprintf('MS_oaTOF_TwoStageRingStackReflectron_%s.mph', strrep(label,' ','_'))));
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
phase_names = {'mphstart (connect to server)', 'geometry (params+features+geom1.run)', ...
    'selections+materials+ES physics setup', 'mesh (mesh1.run+mphmeshstats)', ...
    'electrostatics solve (sol1)', 'field diagnostic queries', ...
    'CPT setup (before solve)', sprintf('CPT solve (N=%d, statistics population)', nP), ...
    'full-population extraction+post-processing', sprintf('trajectory-plot data (N=%d, reuse or re-solve)', nP_plot), ...
    'MATLAB figure (PNG)', 'native Result plots (field diag+mass spectrum table)', ...
    'first model.save', 'native 3D plot (pg1.run)+re-save'};
phase_times = [t_mphstart, t_geom, t_sel, t_mesh, t_es, t_diag, t_cptsetup, t_cpt, t_extract, t_replot, t_matlabplot, t_resultplots, t_save1, t_native];
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
