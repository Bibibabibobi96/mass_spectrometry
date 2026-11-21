# 2026-09-11 CAD 审计上下文冻结

DOC_STATUS: ARCHIVED_READ_ONLY

本页冻结原 `docs/CAD_AUDIT_20260902.md` 的 2026-09-02/03 审计叙述，保留其坐标演变、否定结果与
源身份清单。原文中的“当前”“Candidate”均按原记录时点解释，不代表归档日的模型或资格。
标题层级及返回 PROJECT 的相对链接已适配归档位置；原 CAD、JSON、STL 和 run 均未移动或改写。

原文反复引用 scratch，且文末明确要求提取证据另行发布为受管 run/archive。此次冻结仅保存文字，
不补造或替换缺失的 manifest，也不把这些 scratch 引用升级为当前发布证据。
当前坐标和几何由项目机器合同决定；CAD 使用边界见[CAD 说明](../CAD.md)，当前资格见[PROJECT](../PROJECT.md)。

原文来源 SHA-256（按本次读取字节）：`93ebf77e236b7f1199274b6c4b4c2196cf9cadd2e4bcb1320ef2c9f2c5b33dd5`。

## 2026-09-02 CAD read-only audit

Status (updated 2026-09-03): **native curve, finite-slot and composed-pose
evidence recovered for the Candidate; not a complete CAD/field qualification**.
The final whole-body reconstruction below supersedes earlier bounding-box,
synthetic bridge and serial-translation assumptions. Instrument status and
remaining release gates are maintained in [PROJECT.md](../PROJECT.md).

The archived source was opened read-only with SolidWorks 2022 (`30.5.0`). No
archived CAD file was saved, repaired, or otherwise changed. The run-local JSON
evidence is under
`artifacts/projects/parallel_mirror_dual_stripe_mr_tof/scratch/20260902__cad-audit/`.

### Initial assembly-reference result (before working-copy recovery)

| source | open result | component count | missing references | use in Candidate |
| --- | ---: | ---: | ---: | --- |
| `两套反射电极装配组件.SLDASM` | error 2 | 66 | 27 | do not use as a placement authority |
| `单套反射电极装配组件.SLDASM` | clean open | 85 | 0 | local mirror-part envelope evidence only |
| `离子箔装配组件.SLDASM` | error 2 | 58 | 12 | do not use as a stripe/prism placement authority |

The two broken assemblies retain absolute references to the former
`C:\\Users\\LX\\Desktop\\...` workstation. The archive does contain files named
`离子箔组件-ion foil 1/2/3.SLDPRT` and `离子箔组件-grounded 2.SLDPRT`, but opening each
of the three ion-foil files directly in the archive initially returned error 2.

### Ion Foil recovery, 2026-09-02

The source archive remains unchanged. A run-local copy containing its 119 CAD
files was made under
`artifacts/projects/parallel_mirror_dual_stripe_mr_tof/scratch/20260902__ion-foil-recovery/working_cad/`.
With the user opening Ion Foil 1, 2, and 3 in the existing SolidWorks GUI, the
project audit script `analysis/solidworks_ion_foil_audit.py` read those open
documents without opening, saving, rebuilding, or closing any document. Its
machine-readable result is
`foil_1_2_3_open_documents_geometry.json` in that recovery directory.

| part | local extent (mm) | recovered curve evidence |
| --- | ---: | --- |
| Ion Foil 1 | 392.000 x 24.000 x 109.801 | 4 B-spline traces |
| Ion Foil 2 | 392.000 x 24.001 x 138.903 | 14 B-spline traces |
| Ion Foil 3 | 392.000 x 24.000 x 137.083 | 8 B-spline traces |

The JSON records the B-spline order, knots, and local control points in metres,
as supplied by the SolidWorks API. This is sufficient to preserve the measured
local curve shape during reconstruction. At that initial stage the *assembly*
transforms were unresolved; the subsequent composed-pose recovery below
supersedes that limitation. Local part coordinates must never be substituted
for project-frame coordinates.

#### Assembly pose recovery

The working-copy `离子箔装配组件.SLDASM` then opened silently and read-only with
58 components, error code 0, warning code 0. The project script
`analysis/solidworks_ion_foil_assembly_audit.py` saved the eleven relevant
Ion-Foil, grounded, and prism instances, their local boxes, and their complete
SolidWorks rigid-transform arrays to
`ion_foil_assembly_global_pose.json` beside the local-curve evidence.

The initial ion-foil-subassembly mapping must not be confused with the final
top-level frame. The active `config/cad_to_theory_frame.json` uses the composed
top-level map `x=Z-86`, `y=-X-158`, `z=Y` (mm), as described below. Positions
receive the full rigid transform; velocities receive only its rotation.

For the Candidate's fixed four-electrode/two-bias contract, the mirrored Ion
Foil 1 pair is assigned to Stripe set 1 (`11`, `12`) and the mirrored Ion Foil
3 pair to Stripe set 2 (`13`, `14`). The centred Ion Foil 2 is retained as the
central-ground candidate (`15`), with the two `grounded` components recorded as
additional grounded hardware. This remains a Candidate electrical assignment;
the source archive does not provide a verified wiring/netlist.

#### Physical Stripe edge evidence and rejected envelope inference

`analysis/solidworks_stripe_profile_audit.py` additionally reads the long
body-edge B-splines, after both the assembly and CAD-to-theory transforms. Its
run-local result `stripe_long_bspline_profiles.json` contains the actual
project-frame (z(y)) control curves for every physical Stripe. The long axis
is approximately 390 mm in project `y`, as expected for the slow-drift
coordinate.

The early inference that overlapping global `z` envelopes proved overlapping
conductors was incorrect. Curved bodies must be compared at the same `y` with
their complete composed poses. The manufactured Foils and central grounded
part fit between the mirrors; no extra serial `z` translation is justified by
their bounding boxes. The active geometry retains the recovered curves and
poses, and checks their actual local widths and clearances.

The former provisional GEM represented all four Stripe profiles as `extrude_yz`
project-frame solids and moved Foil 1/3 into a serial arrangement. GUI review
later rejected that geometry: it did not preserve the CAD Ion-Foil bodies or
their positions. It remains diagnostic evidence only, not a Candidate geometry
source. The replacement must retain actual CAD-body curves and placements.

The read-only body-edge audit subsequently composed `Ion-Foil-2` through the
top-level transform and wrote
`20260902__two-mirror-pose-audit/ion_foil_body_bspline_project_frame.json`.
Its selected long B-spline edges (19/20/21/23) recover the central part's
long-curve boundary. The `x=[-12,-2]` and `[2,12] mm` sections describe the
material beside the slot, not two disconnected conductors extending through
both `y` ends. The final reconstruction is one whole body minus finite
rectangular openings, including the short cubic and terminal window documented
below. Curve evidence alone does not qualify voltages, fields or flight.

### Direct part-envelope evidence

SolidWorks `GetPartBox(True)` values below are local part boxes in mm. They are
not project-frame placements and must not be treated as the documented
`(x, y, z)` frame. A spline/control-point box is not a solid boundary or proof
of collision; in particular it cannot determine an STL export translation.

| part | local bounding box, mm |
| --- | --- |
| mirror electrode C | `[-300, -65, -13.5]` to `[300, 60, 13.5]` |
| mirror electrode D | `[-300, -65, -12.5]` to `[300, 60, 12.5]` |
| mirror electrode A cover | `[-300, -65, -2.5]` to `[300, 60, 2.5]` |
| mirror electrode B | `[-300, -65, -28.5]` to `[300, 60, 28.5]` |
| mirror electrode E cover | `[-300, -60, -2.5]` to `[300, 60, 2.5]` |
| mirror electrode E | `[-300, -65, -14.5]` to `[300, 60, 14.5]` |
| mirror electrode A | `[-300, -65, -27.5]` to `[300, 60, 27.5]` |
| grounded part | `[-22, -24, 0]` to `[22, 12, 70]` |
| prism 0 | `[-14.447527, 0, -24.099375]` to `[10.552473, 10, 25.900625]` |
| prism 1 | `[-18.863373, 0, -13.281274]` to `[1.136627, 10, 26.718726]` |

### Consequence for the Candidate

The initial `provisional_not_cad_audited` placement restriction was resolved by
the composed-pose and native-feature recovery below. This qualifies the stated
mechanical inputs only, not the entire Candidate or its electric fields. The
source archive remains immutable; reference recovery and read-only extraction
were performed on a separate working copy.

### Rejected provisional SIMION geometry, 2026-09-02

The first monolithic SIMION diagnostic is rejected as a CAD geometry source.
GUI review found that its Ion-Foil solids/placements and accelerator were not
faithful to the opened CAD, and its five mirror electrodes were only envelope
boxes with an attempted rectangular subtraction rather than measured
through-channel bodies.  Its PA/IOB must not be used for any flight,
transmission, focal-plane or resolution claim.

The mechanical opening invariants are fixed from CAD: every mirror beam slot
is **30 mm** wide and every Ion-Foil beam slot is **4 mm** wide.  The current
machine contract rejects any other values. Rectangular cuts are valid where
they represent the measured native slot features; the rejected assumption was
using whole bounding boxes or unbounded cuts in place of those features.

`Astral加速器.SLDASM` was read from the immutable working copy using SolidWorks
2022 `OpenDoc6(silent|read-only)`.  Its 19-component baseline is
`accelerator_assembly_mechanical_baseline.json` in the same recovery directory.
It is explicitly nonfocusing.  The user subsequently selected an independent,
theory-derived two-zone focusing accelerator; Astral therefore remains only a
mechanical evidence record and is not copied into the active Candidate.

### Geometry authority, 2026-09-02

For the existing manufactured instrument, the active Candidate uses the
**CAD-defined five-electrode mirror geometry** as a fixed mechanical
constraint, not as a source of voltages.  Theory optimizes its voltages and
working point.  Only a separately named future redesign may alter the mirror
axial geometry.  CAD also supplies the 30 mm mirror and 4 mm Ion-Foil slots,
recovered Stripe curve scale, prism size, and the separate no-focus accelerator
baseline.  Theory still defines the electrostatic operating point, central
`z=0` interface, and the new focusing accelerator; CAD contains no authority
for those voltages.

### Two-mirror top-level pose recovery, 2026-09-02

The repaired working-copy `两套反射电极装配组件.SLDASM` subsequently opened
silently and read-only with zero open errors/warnings.  Its transform evidence
is saved in
`scratch/20260902__two-mirror-pose-audit/two_mirror_audit.json`; a matching
read-only audit of the shared single-mirror subassembly is
`single_mirror_local_audit.json` in that directory.

This resolves the *local* manufactured stack without inventing a voltage:
electrode A is at local stack coordinate 0 mm, B at -61 mm, C at -108 mm, D at
-139 mm, E at -171 mm, and the closed E cover at -188 mm.  The A cover is at
+30 mm.  Those coordinates reproduce the CAD thicknesses and the four 5-mm
gaps.  The two top-level mirror instances have translations
`(+134.5,+86,+86)` and `(-134.5,+86,+86)` mm in the top-level SolidWorks frame,
with their recorded rigid rotations retained in the JSON.

The local and parent transforms have now been composed, using the SolidWorks
row-vector convention `p_parent = p_local R + t`, by
`analysis/compose_top_level_cad_pose.py`.  Its machine-readable evidence is
`scratch/20260902__two-mirror-pose-audit/composed_top_level_cad_pose.json`.
The A-cover centres resolve to top-level `Y=+104.5` and `Y=-104.5` mm; their
midpoint is exactly `Y=0`.  Thus top-level CAD `Y` is the required fast
reflection coordinate, mapped to project `z`, and its midpoint is project
`z=0`.  The top-level `X` long direction maps (reversed) to project slow drift
`y`; top-level `Z=86 mm` maps to project transverse `x=0`.  The frozen map is
now in `config/cad_to_theory_frame.json` and has a round-trip regression test.

Applying this map to the composed Ion-Foil records produces
`top_level_project_envelopes.json`: all four physical Foils occupy the expected
project `x≈[-12,12] mm` and `y≈[-390,2] mm` corridor.  The CAD position is
therefore supported by the composed-pose evidence. It does **not** validate a
mirror voltage set, field, L0/L1 optics, PA, IOB or flight; current operating
and release gates are recorded in PROJECT.

### Theory-resolved geometry compilation

The replacement Candidate geometry is compiled by
`analysis/resolved_geometry.py` from
`config/simion_candidate_two_zone.json`; `analysis/full_candidate_geometry.py`
is only its SIMION legacy-GEM adapter.  The resolved contract now carries the
five measured mirror thicknesses/gaps and envelope, bounded 30-mm mirror
slots, native knot/control parameters for the long B-spline Stripe curves,
and the finite 4-mm Ion-Foil slot/end topology below. It does not consume the
superseded 25-point edge tables or add a serial `z` translation. It
keeps the physical mirror pairs and physical Stripe IDs, while assigning
`(11,12)` and `(13,14)` to the two independently adjustable response bases.

For historical context only, on 2026-09-02 SIMION 2020 `gem2pa` compiled an
earlier, subsequently rejected coarse candidate at
`4 x 4 x 0.4 mm/gu` without GEM errors.  All 25 stable electrode IDs were
present; the two zero-thickness ideal grids each occupied one raw PA z row
(`23:1116`, `24:1200`).  SIMION then produced `pa#`, `pa0` and the complete
`pa1`--`pa25` basis family.  This is a geometry/compiler and coarse basis-family
check only, not an IOB/GUI review, flight, focusing, transmission or resolution
result.  A headless attempt to instantiate an IOB from an example template was
stopped because `simion.command(<iob>)` entered the template's flight loop;
therefore no IOB has been claimed or retained.  The run-local GEM/PA belongs to
`artifacts/projects/parallel_mirror_dual_stripe_mr_tof/scratch/20260902__theory-resolved-geometry/`.

### Geometry review rejection, 2026-09-02

The resulting GEM/PA/IOB was visually reviewed and rejected.  Its mirror slot
was a synthetic full-width rectangular subtraction rather than the measured
30-mm through-channel; its four Ion-Foil bodies did not consume the recovered
assembly poses and therefore had incorrect `y/z` placement and band topology;
and its two-zone accelerator was an arbitrary box model rather than the
separately audited Astral mechanical baseline plus a documented theory-led
injection interface.  Do not load these derived arrays as an MR-TOF Candidate
for review or fly.  Preserve them only as diagnostic evidence of the rejected
construction.

### Follow-up evidence recovery, 2026-09-02

The recovered `stripe_long_bspline_profiles.json` was used to freeze common-y,
25-node curve samples: Ion-Foil-1 outer curve/straight edges 10/27 and
Ion-Foil-3 outer curves 16/14. This replaced the rejected six-point visual
approximation at that time. Both the 25-point representation and the inferred
serial translation were subsequently superseded by native B-spline parameters
and the complete top-level pose chain. Bounding-box overlap does not imply
physical intersection of these curved bodies.

An attempt to read-only export the recovered single-mirror assembly on the
same date initially used an incorrect `OpenDoc6` option value (`33`, which does
not include the ReadOnly bit) and was correctly rejected.  After correction to
`Silent|ReadOnly = 3`, the recovered single-mirror assembly exported 16 unique
STL parts and 85 instances without writing the source CAD.  User-confirmed CAD
semantics were subsequently corrected by direct STL-face inspection: each
active A--E plate has a **bounded** `580 x 30 mm` slot.  In the part-local
section its long-axis endpoints are 10 and 590 mm and its transverse edges are
50 and 80 mm; it therefore leaves 10-mm metal at each end of the 600-mm body.
Under the frozen project transform this is a centred 580-mm project-`y`
interval, not a `y`-through slot.  The solver geometry must subtract this
local aperture separately from each active electrode and must never use one
global `z`-spanning subtractor.  The full-width-x subtraction remains
prohibited.

### Native whole-body and finite-slot reconstruction, 2026-09-03

All coordinates in this section are project-frame millimetres. Numerical
values remain machine-owned by `config/simion_candidate_two_zone.json`; this
section records their native CAD provenance, not a second editable baseline.
The field-critical simplification retains native curves, stepped body
sections, rectangular slots and triangular clearances. It omits fastener holes
and other non-beam-path engineering detail; it is not a complete manufacturing
solid. Material remaining after a cut must not be replaced by added bridge
boxes or inferred from a whole-part bounding box.

#### Ion-Foil 1/2/3 ends and central grounded body

All three native part types have a 392-mm body from `y=-390` to `y=2`.
The common beam-channel cut is `x=[-2,2]`, `y=[-385,0]`, extending across
the relevant body's `z` profile. Thus the negative end retains 5 mm and the
positive end retains 2 mm of material where the native terminal profile
exists. The earlier `body=[-390,0]`, `slot=[-385,-2]` interpretation misplaced
the positive end by 2 mm. This is a finite `y` slot, not a cut through the
whole 392-mm body.

| native part / role | recovered end geometry |
| --- | --- |
| Ion-Foil 1 / Stripe set 1, IDs 11/12 | Long curve ends at `y=0`; Sketch14 planar terminal occupies `y=[0,2]`, positive-side `z=[67.8485767191625,96.99627727439764]`. The opposite electrode is the mirrored `z` profile. |
| Ion-Foil 3 / Stripe set 2, IDs 13/14 | Long curve ends at `y=0`; Sketch12 planar terminal occupies `y=[0,2]`, positive-side `z=[47.49141051901597,56.19578793365602]`, with its mirrored counterpart. |
| Ion-Foil 2 / central ground, ID 15 | Long native curves end at `y=-4`; Sketch20 supplies the short cubic continuation over `[-4,0]`. Sketch22/25 supplies the planar end over `[0,2]`, `z=[-34.87141353350277,34.87141353363198]`, with the separate terminal window described below. |

The four Stripe solids are unions of their native long-curve and planar end
sections before the finite rectangular channel is subtracted. Their native
long profiles and absolute poses are unchanged; terminal limits come from
the native sketches composed with the same rigid transforms, not from curve
extrapolation or B-spline control-point boxes.

Ion-Foil 2 is one connected grounded part, represented by the union of its
long-body half-sections, short cubic section and planar terminal section,
then subtracting both native windows. In addition to the common 4-mm channel,
its terminal window is `x=[-12,12]`, `y=[-4,2]`, `z=[-22,22]`. The short
cubic outer boundaries run from approximately `z=±40.1674046` at `y=-4`
to `z=±40.0001069` at `y=0`; their exact knots and controls are in the
contract. Consequently, at `y=[0,2]` the positive-end material is in two
`z` lands outside `[-22,22]`, not a solid full-`z` bridge. A box spanning
the whole terminal `z` envelope would incorrectly close the central window.

#### Accelerator-exit shield: grounded 1

Native grounded Sketch3 defines the triangular clearance; Sketch10 and the
planar faces define the stepped rear section. Its native local-to-project
map, after conversion to mm, is `x=local_y`, `y=55-local_x`,
`z=local_z-100`. The one physical shield (ID 18) is the union of:

- Main section: `x=[-12,12]`, `y=[33,77]`, `z=[-100,-30]`.
- Rear section: `x=[-24,-12]`, `y=[33,70]`, `z=[-100,-30]`, with the
  edge notch `y=[33,52]`, `z=[-77,-53]` absent. It does not extend to `y=77`.

Subtract the exact triangular `y-z` clearance with vertices
`(40,-65), (70,-95), (70,-35)`, and the finite rectangular beam channel
`x=[-2,2]`, `y=[35,75]`, `z=[-100,-30]`. The 2-mm lands at
`y=[33,35]` and `[75,77]` belong to the main body; the rear section has its
own stepped outline. Neither a complete `x=[-24,12]` envelope box nor two
disconnected side plates describe this part. The channel is reflection-axis
through-going but bounded in drift `y`.

#### Central-prism shield: grounded 2

The native face topology and sketches, transformed by `x=30-local_y`,
`y=14-local_x`, `z=local_z` in mm, define one physical shield (ID 20):

- Main section: `x=[-12,12]`, `y=[3,32]`, `z=[-97,97]`.
- Local Stripe-side extension: `x=[-12,12]`, `y=[-3,3]`, **only**
  `z=[-21,21]`. Outside this local extension the Stripe-side edge is `y=3`,
  not `y=-3`.
- Rear sections: `x=[-24,-12]`, `y=[3,32]`, only `z=[-97,-57]` and
  `[57,97]`; the intermediate rear envelope is empty.

The exact triangular clearance has `y-z` vertices `(0,0), (26,-26),
`(26,26)`. The cross aperture is the **union**, not the intersection, of
these two rectangular cuts:

| cut | x | y | z |
| --- | --- | --- | --- |
| Reflection-through branch | `[-2,2]` | `[6,28]` | `[-97,97]` |
| Drift-through branch | `[-2,2]` | `[-3,32]` | `[-40,40]` |

The 22-mm opening `[6,28]` leaves 3 mm to the effective Stripe-side main
edge `y=3` and 4 mm to the far edge `y=32`. The 80-mm opening `z=[-40,40]`
leaves 57 mm to each `z` end of the 194-mm body. These dimensions apply to
their respective branch; they do not authorize filling the whole local
extension or rear bounding box. In particular `(x,y,z)=(4,0,60)` is outside
the native body, whereas `(4,0,10)` is within the local extension. The
drift-through branch is intentional inside the central 80-mm `z` window;
it does not mean that the entire shield is split into disconnected halves.

#### Mirror aperture and evidence boundary

The manufactured mirror remains unchanged: 600-mm body length centred at
`y=-158`, hence `y=[-458,142]`; each 580-mm main slot is
`y=[-448,132]`, `x=[-15,15]`. The inner grounded A cover is 5 mm thick
with its own 4-mm slot. The outer 5-mm closed cover is at E potential,
not ground; its inner surface is at `|z|=320`, outer surface at `325`.
Every cut is local to its own plate; neither the main slot nor the cover
opening is a full-`y` or whole-stack-`z` subtraction.

The 2026-09-03 native geometry regression reported by the main task passes
five tests, including shield sections, Foil ends and preservation of the
30-mm mirror aperture. This is sampled native-geometry evidence, not a
complete solid comparison, GUI acceptance, field convergence or flight test.
This documentation update opened no commercial application and changed no
native CAD, code or machine parameter.

### Source identities for the final native-feature audit

SHA-256 below was rechecked from existing bytes during this documentation
update. Native files belong to the immutable initial-user-design archive
identified in PROJECT; names retain the `离子箔组件-` prefix and `.SLDPRT`
suffix. Extracted JSON/STL files are identified here for audit matching only:
they still require publication in a managed run/archive with a verified
manifest before being used as a release evidence package. This update neither
promotes the existing scratch directories nor moves or rewrites their files.

| native part stem | SHA-256 |
| --- | --- |
| `ion foil 1` | `b073a055b0c3cb827c55f5729e4b14f570f47cbcc098c49531eca3c1fa40c7bd` |
| `ion foil 2` | `9dbcccd3e077f416dc8a3c3f88814de4baaf130667b00a8e3e62cdbc87d5ebad` |
| `ion foil 3` | `ea0ba01a73a6965ad7f754c60da0bf9e7f6a3010f0edca3e172ca6e8eab3c49a` |
| `grounded` | `b6c0d9d6e08867a82351ab8e9a6ae4c2deecc95111791a3a94ff091f70742cdc` |
| `grounded 2` | `6186aa9d6f5fdbaad2011c32968005bd47706f35c4e057a86d7c4e09fbe25b2f` |

| extracted evidence | SHA-256 |
| --- | --- |
| `grounded_face_topology.json` | `6a0cecffbe548f266edd49cefa0e198dbdbdd733702de1d49aea5f5efde7e76f` |
| `grounded_part_sketches.json` | `cb071192bb7f613cb94680e6a023239b2ee9368f498043951e179c5eac324ea9` |
| `foil_1_2_3_open_documents_geometry.json` | `a61162464b5fb2a3360bfa9c277b9f6ad2cd928c55ecf6758bec4f47795c059b` |
| `composed_top_level_cad_pose.json` | `f7a11f83283f947b6a8b10f608fd9712da903434256165c2aa61a20eea045c34` |
| `-ion_foil_1__4a78eed7db7b.STL` | `31cb23a608b38f0c311fecd4caa2b2240ce3a7682436d8b54306589635845ccc` |
| `-ion_foil_2__38f1a7ece908.STL` | `d38c34e821297364ff935998f9185db6ea1d2860e641fc8419e29d2a73a93f06` |
| `-ion_foil_3__a3f38b5c12b5.STL` | `e30c2724c6a4b9c26e861963f43089d31dd1747836fc8077594028d517c24ba5` |
| `-grounded__f770aaaa4a7c.STL` | `29402f7e64f08aa707c195c030b5b2c77c439ed9655068a7e8144c975d3f678d` |
| `-grounded_2__40a5aab6e9a3.STL` | `856a2a4b324a63ab826608a04903358fe27486c4b95aaaf0d7cb186bdd844016` |

Native API sketch/control coordinates use metres; the listed exported STL
coordinates actually use millimetres with an export translation, despite
legacy manifest wording claiming part-local metres. For grounded 1,
`p_STL=p_local+(22,24,0)`; for grounded 2, `p_STL=p_local+(18,0,97)` (mm).
Remove that translation before the corresponding local-to-project transform.
For the Foils, register against native feature endpoints, not `GetPartBox`
minima: spline control-point bounds can exceed the actual surface. The
reconstructed terminal values above come directly from native sketches and
composed poses, not from an inferred mesh-box alignment.
