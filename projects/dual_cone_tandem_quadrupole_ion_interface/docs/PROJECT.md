# 双锥串联四极杆离子传输接口项目状态

## Program-owned state at repeated run initialization

Plain-Lua execution of the actual Program reproduced a lifecycle defect: loading
the Program once and calling initialize_run twice with sparse IDs [1,7,101]
produced three final rows in the first run and none in the second. Independent
fresh-load controls each produced all three rows. The Program now clears only
its next-sample, terminal-code, coverage-loss and final-recorded tables at
initialize_run. Existing callback order, once-per-run seed and once-per-load
SDS installation remain unchanged; no supplier state or random stream is reset
by this fix. The frozen Program source record is its implementation identity.

The actual Program regression compares first/second final and trajectory bytes
with fresh controls, including first-run coverage loss, terminal classification
and duplicate terminate calls. This is software wiring/lifecycle evidence with
an inert SDS interface, not actual repeated native Fly, supplier collision
physics, arbitrary repartition equivalence or a collision checkpoint guarantee.

## Installed SIMION input preparation

Masked gas-field samples now require NaN in every declared gas field; positive
and negative infinity are rejected rather than treated as unavailable data.
The real CSV/metadata validator regression covers all seven required fields in
masked and fluid rows, retaining the original source hashes, grid and minimum
fluid-count checks. The eight gas-flow contract tests passed; this correction
does not imply that historical exports contained infinity or grant native
collision or CFD qualification.

The pure preparation implementation is `msplatform.backends.simion.dual_cone_transport.prepare_transport`;
its Program is an installed SIMION resource. Explicit transport/release/interface contracts remain research
inputs. The public operation can consume a published gas-field reference using its original frozen data and
contracts; producer geometry and gas science must match the selected transport inputs. It does not interpret
gas pressure as an electric field or perform PA refinement/Fly. Uniform-gas runtime preparation remains a
separate explicitly identified control. The old project implementation and serializer bridge are retired.

A reproduced pre-existing defect accepted a COMSOL runtime manifest made for different producer geometry;
the migrated preparation now rejects that mismatch. An inert direct-Program initialization test also
showed that the Program did not consume its declared nitrogen mass/diameter and diffusion settings;
that invocation used vendor air defaults. The installed Program now binds those three explicit values
through official `SDS.init` before mass-data completion. This correction concerns direct invocation,
not the physics of historical runs. In particular, the preserved `simion_fly.log` from
`20260914_162400__sim__simion__dual-cone-comsol-field-n100` explicitly reports gas mass
28.0134 u, diameter 0.364 nm and diffusion enabled. Its original results and qualification remain
unchanged; they must not be described as an air-default run or inherited as a new native PASS.

Official API evidence: SIMION-2020 `examples/collision_sds/collision_sds.lua`, version
`8.1.2.7.20140407`, user-init documentation near line807 and initialize_run before massdata completion
near1349, reviewed2026-11-09; [vendor collision-model overview](https://simion.com/info/ion_gas_collisions.html).
The five official SDS files remain explicitly provided installation resources frozen by identity, never
vendored into Git. Plain-Lua initialization tests are not ion Fly or CFD qualification. The trajectory observation interval is explicitly selected by `trajectory.sample_interval_us` in the
current research SIMION numerical input (1 microsecond for the existing case). Preparation requires a
positive finite value; no implicit fallback is applied. Historical frozen inputs and results remain unchanged.
Native dual-cone
seven-electrode fractional field/transport integration remains OPEN; the installed RF-specific family
operation does not by itself support this geometry. Prototype, uncalibrated gas and GUI/Formal limits remain.


Integrated acceptance passed 28 focused transport/source/routing tests and five ordinary
wheel/sdist-rebuilt-wheel parents. All 376 package payloads match main source and
both wheels exactly. The installed probe exercised explicit 1/2-microsecond preparation,
site-packages resource origins and frozen Program/RF bytes without PA creation or Fly.
The three source serializer algorithms remain AST-identical to their retired owner.


Full-data preparation exposed the existing Windows 8 MiB file-identity boundary:
the 12,146,449-byte compiled gas runtime lacked a classification. Its freeze now
supplies contextual `required_evidence` through the existing API; the global tier,
solver-native read policy and four-field receipt identity remain unchanged. A valid
large-Lua public-input regression and the original missing/tamper tests passed;
main affected modules passed 22 tests in 6.119 seconds.

A fresh ordinary 376-payload wheel, SHA-256
`3882563b48fdf8686a539ab71e57f4cd33d669f4cda116ead7d79d689798f599`,
then prepared both original 295,236-row gas products listed below. Both produced
identical 12,146,449-byte runtime data and retained the full 100-particle source,
IDs, equal weights, birth clock and six-dimensional source values. Standalone Lua
queries verified the declared Pa/K/m/s units, radial projection, coordinate offsets
and Pa-to-Torr conversion at four explicit grid points per product. Original gas
data, contracts, MPH and the five official SDS files remained unchanged. All 376
installed payloads matched the accepted wheel before and after the check.
The original classification failure and a separate diagnostic audit error are
retained; the final check changed no science input, grid, particle count or tolerance.
These are data/preparation checks: no commercial application, Refine, ion Fly or GUI
ran, and no CFD accuracy or ion-transport qualification is granted. The earlier
full wheel/sdist suite belongs to the preceding source epoch; it was not rerun for
this one-call classification repair.


## Fresh SIMION transport restoration under software validation

The new fresh workflow composes explicit geometry build, Refine, fractional
family readback, source-bearing IOB build/reopen and Fly through one existing
RunSession. Its native family remains unpublished in that producer run until all
writers close. It neither consumes a copied published family nor introduces a
second cache/owner. The independent operations below now have managed software
implementations; their separate native validation remains OPEN. The first fresh
native attempt stopped at raw validation and the corrected attempt at IOB creation,
as recorded below. No successful current Fly or scientific qualification is claimed.

Pure regression reproduced two existing parameter defects: GEM emitted a fixed
51 mm transverse span despite a legal changed enclosure radius, and the Program
ignored the declared trajectory.maximum_step_us. The sole geometry compiler now
derives GEM and audit grid from the same request; the current default GEM bytes
are unchanged. The Program consumes the explicit maximum step and caps it together
with the existing RF bound. Historical native inputs/results are unchanged and
must not be described as having applied this previously omitted cap.

The existing RF-named Refine/audit Lua resources are shared native family utilities
in this slice; their retained markers do not assign RF component or product
identity to dual-cone geometry. Their neutral naming is deferred until the pending
RF integration permits one coordinated change, without rewriting historical receipts.

Official method review (2026-11-09): SIMION2020 docs/simion.chm simion.pas API;
[online abridged API](https://simion.com/info/lua_simion.pas.html) documents integer
point iteration. The existing generic raw builder uses actual native electrode
IDs and node witnesses, then its original surface_info witness algorithm; it does
not duplicate cone CSG or adjust the grid when a thin feature lacks a witness.
The optional scan reports visited nodes and CPU seconds; native scan cost remains
unmeasured pending the separately reviewed execution budget. Native mesh accuracy,
GUI, collision qualification and Formal status remain ungranted.

### Device placement and source-frame binding (P11)

The one-PA, unit-scale adapter accepts an explicit canonical `RigidTransform`
from the resolved device frame to a named workbench frame. Geometry-only and
model-only stages do not require a source frame or gas input. The existing
numerical offset embeds device coordinates in the PA array; it is not an extra
world translation. IOB placement composes its inverse with the device pose, so
positions use Rr+t once and free vectors use Rv. The existing RF stable Euler
conversion is now the sole IOB representation helper for both adapters.

Tracking accepts an optional `source_to_device` canonical rigid transform. It is
required when a newly posed request uses a differently named source frame; when
frame IDs already match, identity registration is sufficient. Source CSV bytes,
IDs, species and birth times remain unchanged. The registered cohort is checked
in device/PA-local coordinates before transport. Placement and registration do
not enter local geometry, gas or spatial field-basis identities. A differently
placed/driven model can explicitly reuse the original compatible guarded basis.

Omission of both spatial inputs retains the historical translation-only input
shape and its original source-label interpretation. It does not rename the
historical `multipole_cartesian_z_axis_v1` source frame. New posed requests must
bind that frame explicitly rather than silently relabeling it. Historical frozen
records and hashes are unchanged.

The Program uses official `instance:wb_to_pa_coords` for inverse point queries
(GU converted by actual pitch, then subtracting PA embedding) and
`instance:pa_to_wb_orient` for device gas velocity in m/s. It retains the existing
Pa/Torr conversion and SDS physics. The terminal plane and transverse metrics
are evaluated in device-local coordinates; raw world CSV remains unchanged.
The active projection tool requires either `--placement` with the frozen pose or
`--historical-translation-only`, so it never guesses an offset for posed data.

Official evidence: SIMION2020 installed `docs/simion.chm`, `lua_simion.wb` methods;
[official instance API](https://simion.com/info/lua_simion.wb.html). Installed
`examples/collision_sds/collision_sds.lua` version `8.1.2.7.20140407` documents
workbench-mm callback inputs and workbench-oriented m/s velocity function output
(lines238,278,1004 and1164). Scalar pressure/temperature do not rotate; velocity
does. The removed `velocity_coordinates` option is not used.

The bounded software set passed 71 parents / 163 outcomes in 88.520 s with no skips,
including the original RF near-gimbal tests and actual shared IOB Lua guards.
The original and posed public-owner inert publications retain original-family
protection and reuse; source tests retain all 100 rows, signed charge and birth.
A subsequent precise C0 registration guard passed six pose/source tests. C0
smoke has a fixed device-local source, so it rejects `source_to_device` before
creating output; explicit device placement itself remains supported.

Ordinary wheel and sdist-rebuilt-wheel acceptance passed five parents / 16 outcomes
in 139.046 s before that two-line guard. All 382 package payload members matched
both wheels and their actual frozen build source. After the guard, a fresh
ordinary wheel's targeted installed consumer passed unchanged C0 default, posed
C0, no-output C0 registration rejection and registered gas-source preparation,
with author trees denied; all 382 final payload members match that build/source.
The complete five-method suite was not rerun for the guard. Native IOB/Refine/Fly,
pose-qualified transport, stochastic trajectory equality, mesh precision,
GUI and Formal evidence remain unperformed in this slice. The separate CAD/provider implementation
and its declared projection limits are recorded below; an IOB pose alone does not implement CAD.

### Declared same-source CAD/provider

The installed `dual_cone_tandem_quadrupole` provider derives its complete neutral
interface and eleven metal members from the explicit source baseline. The existing
Assembly/STEP pipeline applies a proper device pose once, without a PA embedding.
Two conical shells, four ellipse rods, four round rods and the apertured plate
retain seven groups identical to the existing prepared-model drive rows. The
initial adapter's extra `rf` group-name token was a software identity mismatch;
the corrected provider uses the original group identities, without changing drive
values or geometry. Real aperture ports are derived from the first cone and
outlet plate; no enclosure, flange, pump or unknown mechanical dimension is invented.
The cones use the already-declared computational radial truncation, not a confirmed
manufacturing outer diameter.

The declared first-stage cone-following cut is fully specified by resolved
`upstream_end_surface`; CAD represents it as a rod/cone intersection. Existing GEM
C0 retains its flat upstream approximation. The component owns the shell profile,
while the GEM renderer consumes that same profile with three exact unchanged
text goldens. This is one author-design source with an explicit projection
approximation, not a claim that STEP and C0 PA solids are equal.

The final-group CPU managed export and separate cold reader passed with eleven
valid solids, eleven XCAF product labels, fifteen analytic aperture/metal/cut
probes and the existing serialization bound. The bounded software set passed
41 parents / 119 outcomes in 38.030 s with no skips. No commercial solver,
SolidWorks or GUI was invoked, and no manufacturing, field or Formal qualification
is granted. A separate ordinary wheel built from the current production tree plus
these exact CAD hunks passed actual managed export and a fresh cold reader with
all 407 payload members matching source/build/site-packages before and afterward.
Startup audit guards denied the author/build trees in the actual worker and reader;
all recorded scientific module origins were site-packages. Removing the new member
module in a separate negative installation rejected the component, without author
fallback, and the exact fixture bytes were restored. These installed CPU checks
are not a full Repository gate or commercial-solver acceptance.
An earlier nested-GATE invocation failed owner finalization after its worker
exported STEP; its failed result and held capacity lease are preserved, not
rewritten as a successful published export. The corrected managed export is a
distinct run using the actual outer workspace and its own GATE admission.
See [CAD usage](CAD.md) for the profile and normal installed entrypoints.

### Independent managed stages and saved-field consumption

`msplatform.workflows.dual_cone_stages` exposes `build_geometry`, `prepare_model`,
`solve_fields` and `track_fields`. Each calls the existing managed owner and
RunSession with its actual operation graph; no second result/lease/cache owner is
introduced. Geometry and model require zero gas, SDS or sampled-source inputs.
They save/reopen the canonical source-free IOB with an empty native particle-format
control, not a one-particle fallback. Models bind all seven drive groups, the
actual clock authority/epoch and the existing external-linear field physics.
The canonical timing adapter currently permits phase anchor instrument time zero;
other anchors and general instance poses are not silently accepted.

The shared clock-authority validator accepts this workflow's explicit clock-only
projection without requiring a frontend geometry snapshot. Full RF–IP models
still require their zero instrument epoch; byte, path and clock-identity checks
remain unchanged. This restores the retained dual-cone caller contract.

Field generation materializes only the unsolved raw PA#/fractional surface/witness
closure through the existing guarded payload transport, then Refines and audits
an independent producer family. Field identity excludes source, gas, observation
cadence and RF drive values, while binding geometry, seven IDs, boundary physics,
refinement and actual tool/refiner/auditor records. A changed drive creates a new
PreparedModel; `solve_fields(..., reuse_fields_reference=...)` explicitly validates
and audits a compatible original basis without copying its PA family or Refine.
The new published field reference keeps the new model and the original producer.

Saved-field `track_fields` protects both selected and original producer manifests
and consumes all eleven original family/witness records directly. Its graph is
only IOB build, closed reopen and Fly. Gas/SDS/source preparation has no GEM output,
geometry build or Refine dependency. The Program consumes the selected model's
canonical seven-group drive configuration; source/cadence changes do not rebuild
fields. Actual clock/data records and native control bytes remain guarded.

Actual-owner inert tests exercise all four public operations, changed-drive basis
reuse, changed source/observation consumption, complete N100 identity and original
family hashes. Public missing/unknown-writer/tampered-source checks stop before
owner launch. Actual plain-Lua tests cover selected model-drive wiring and the
existing frame/unit/source guarantees. These software fixtures are not vendor
execution, native family qualification, GUI or scientific qualification.
Ordinary installation evidence is tied to each separately recorded frozen epoch.
Independent native build/save/reopen/Refine/Fly and P11 pose adaptation remain
required OPEN P4 work until their actual scoped acceptance; this source migration
does not move them to P5.

## Installed gas-flow ownership migration

The existing axisymmetric gas builder/task now reside in the installed COMSOL MATLAB directory and
receive explicit science, numerics, geometry, output and optional resume-model paths. The public
`solve_axisymmetric_gas_flow` operation uses the canonical managed owner and launcher. The old project
PowerShell file is research/profile transport only, with explicit deployment/workspace/profile bindings.
The source contracts remain research inputs; none were copied into a second package default.

Published gas data is read through `msplatform.results.gas_field`, including the explicit historical
successful-manifest format and its original frozen scientific records. Missing historical inputs do not
fall back to current project defaults. The gas product excludes MPH from offline data consumption;
explicit model reexport instead requires published model identity and native writer/release closure.
The source migration and the separately frozen installed native acceptance below are distinct epochs; neither grants scientific qualification.


本文件是当前参数解释、物理链、资格和开放任务的唯一权威。多极杆通用理论见
[多极杆理论](../../rf_multipole_ion_optics/docs/theory/index.md)，碰撞模型分级见
[碰撞模型](../../rf_multipole_ion_optics/docs/theory/collisions.md)。

Dual-cone geometry and gas-source projection are installed in
`msplatform.components.dual_cone_tandem_quadrupole_ion_interface`; exported gas data validation is owned by `msplatform.components.dual_cone_tandem_quadrupole_ion_interface.gas_field_validation`. The joint gas runtime compiler/materializer is `msplatform.backends.simion.gas_runtime`; the published-product workflow composes the existing projection and materializer. Fractional GEM compilation is installed in
`msplatform.backends.simion.dual_cone_geometry`。杆数组与杆 GEM 分别直接复用
`msplatform.components.rf_multipole.round_rod_geometry` 和 `msplatform.backends.simion.rf_geometry`，
旧项目内五个对应模块已退役且无转发桥。resolved JSON、GEM 与均匀场 Lua 已逐字节对照；
来源哈希、理想气体密度、质量守恒、400 Pa 对照及失败关闭语义不变。该早期迁移未运行 COMSOL/SIMION，
未改变当时气流或轨迹资格；其后准备能力与原生尝试分别见上文和下文。
规范组件和backend不保存项目根、默认配置文件或checkout定位逻辑；纯函数与CLI均要求显式输入路径，
原项目默认体验只由项目verify、prepare和工作流脚本接线提供。
气流后处理现通过同一运行root机制消费本次`repository_snapshot`；气体轴、坐标容差及密度输入拒绝非有限值，
零坐标容差保持合法。定向软件回归通过，未运行COMSOL或SIMION。
项目prepare现直接使用`msplatform.contracts.particle_physics`，不再经旧公共桥；源质量、能量和失败语义不变。

## 部件判断

该结构最可能是三重四极杆 Q1 之前的“差分抽气双锥采样接口 + 两级高压 RF 四极杆离子导引组件”，
不是 Q1/Q2/Q3 质量分析杆本体。其拓扑与 SCIEX QJet/Q0 类前端接近，但公开资料尚未证实本项目的
`8.6 × 3.76 mm` 椭圆杆、`2.39 mm` 圆杆和 `52.2 mm` 长度来自某一具体型号，因此当前项目不使用
商标身份。

排除项：Waters StepWave 和常见 ion funnel/S-lens 使用叠环电极；SCIEX D Jet 首级公开为十二极，均
与本项目明确的四根纵向杆不符。

查阅资料（2026-09-08）：

- SCIEX, *4500 Series of Instruments System User Guide*：QJet 位于 orifice plate 与 Q0 之间，QJet
  聚焦但不质量过滤，Q0 在进入 Q1 前再次聚焦：
  <https://collateral.sciex.com/manuals/4500-system-user-guide-en/4500-system-user-guide-en.pdf>
- SCIEX, *Enabling new levels of quantification*：常规 QJet 是单级四极导引器，D Jet 首级为十二极：
  <https://sciex.com/tech-notes/technology/enabling-new-levels-of-quantification>
- Waters, *StepWave*：该结构基于 stacked-ring ion guide，而不是四根纵杆：
  <https://www.waters.com/nextgen/en/products/mass-spectrometry/mass-spectrometry-technologies/stepwave.html>

## 当前机器解释

精确值只认 [`baseline.json`](../config/baseline.json) 与其生成的
[`resolved_geometry.json`](../config/resolved_geometry.json)。当前暂定解释为：

- `z = 0 mm` 和 `z = 3 mm` 分别是第一、第二锥的虚拟尖点/孔口基准面；两个角均按全顶角解释。
- `8.6 mm` 与 `3.76 mm` 按椭圆全轴长解释；对置杆内表面间距按 `7.48 mm` 解释，短半轴沿径向。
- `5.64 mm` 按相邻圆杆中心距解释，得到杆中心半径约 `3.988 mm`、理想场半径约 `1.598 mm`。
- 低压区的 `105 mm` 从第二锥孔口基准面量到下游端；圆杆段与下游端齐平。其上游面反推后，椭圆杆
  平面端再上游 `2 mm`。
- 椭圆杆入口端用“第二锥理论表面沿 z 正向偏置 `1.6 mm`”近似锥切；它不是已确认的真实法向净距。
- 两段四极导引器均采用反相正弦 RF；用户确认每组杆对地峰值 `300 V`，即对置杆组间
  `600 V` 峰值、`1200 Vpp`。用户给出的工作频率范围为 `550–590 kHz`，当前标称计算点取中值
  `570 kHz`；两个频率端点尚未扫描。
- 当前 N=100 原型源由仓库公共 `msplatform.ion_release` 的 seeded-Gaussian cylinder 合同物化：在第一锥上游、中心 `z=-1 mm`、长 `1.5 mm` 的圆柱体积内均匀取样，并独立采样速度；用户指定
  源半径为 `1.5 mm`。它大于第一锥 `1 mm` 孔半径但小于 `5 mm` 上游储气腔半径，超出孔径的离子
  不在源生成阶段预先剔除；后续由 SIMION 实体几何或 COMSOL 流体支持边界代理判定损失。

这些解释只用于生成一致坐标和发现冲突，不等于机械尺寸已确认。

## 当前权威物理链

物理路线由以下两种职责组成。SIMION fresh 输运及独立阶段已有受管软件实现；其当前原生 Fly 与科学资格仍开放：

1. COMSOL 使用 [`gas_flow_science.json`](../config/gas_flow_science.json) 与
   [`comsol_solver_numerics.json`](../config/comsol_solver_numerics.json) 建立轴对称可压缩气流筛选。
   当前模型只覆盖无杆、无偏置泵口的空包络轴对称近似；它的声明边界是
   `prototype_axisymmetric_empty_enclosure_gas_flow`。
2. SIMION 几何编译器从同一 resolved 几何生成电极表示；气体场准备消费显式发布的成功 COMSOL
   气体场引用或已编译 runtime，核对原始冻结来源、SHA-256、frame 和单位。canonical `r-z` 气体场
   至少包含压力、温度、径向与轴向气速以及有效域和插值边界语义。

COMSOL 气流成功只证明上游场计算完成，不证明离子传输。SIMION 消费 COMSOL 场意味着两者是依赖链，
不得表述为跨求解器轨迹等价。若未来需要独立闭合，必须另建 COMSOL charged-particle workflow，并使
两个轨迹求解器分别消费同一冻结气体场、源、电极和事件合同。

项目保留 COMSOL 求解、场编译、SIMION 科学输入准备及 Fly Lua。COMSOL 空包络气流保留已登记
执行 profile；原 SIMION 原生运行器及均匀 `400 Pa`／COMSOL 场 wrapper 已退役，现由安装包中的
fresh 输运和独立几何、模型、场、轨迹阶段组合现有受管 owner。原 fractional PA 隔离缺口不再是
“没有软件实现”的表述：后继实现及其软件验证见上文，独立原生验收仍开放。两次 fresh 原生尝试
分别止于 raw 校验和 IOB 创建，当前尚无成功 Fly。只有 COMSOL 最终 `400 Pa`、合同明确记录的终态
参数解通过独立场校验，并由下游运行冻结全部来源哈希后，才可形成 Prototype 证据；任意中间
continuation 解或裸 CSV 都不是可执行证据入口。

## 已退役模型

项目建立时的 `pressure_drag_screening_v1` 使用规定压力、规定气速、低场迁移率阻尼和理想近轴 RF 场。
它已退出活动 mode 和 execution profile，相关 Python 积分器不再属于生产主链。其两次历史 run、原
声明边界和可恢复源码身份冻结在
[`20260908__superseded-python-pressure-drag-screening.md`](history/20260908__superseded-python-pressure-drag-screening.md)。
旧 run 继续按原 manifest 保留，但不得作为 COMSOL 气体场或 SIMION 轨迹资格输入。

## 当前资格

2026-10-24 历史缓存边界审查：当时 GEM 使用 `surface=fractional`，而公共 standalone 响应导出明确拒绝 `.pa-surf`。原冷启动分支使用已退出公共 CLI 的 `ensure/publish`，不能发布受管资产；原命中分支把原生 `.paN` 交给供应商，不能满足缓存写隔离。因此整体退役四个不可执行原生入口（C0、共享输运及两个气场 wrapper）和专属死测试，撤下 SIMION transport 执行 profile，不保留旧名转发、阻断 stub 或不可达执行体。纯准备、GEM 编译、源、RF、fractional 数值合同与 COMSOL 气流入口保留；历史成功 run 身份及科学结果不变。

该审查当时要求保留 fractional 表面信息、支持真实电极集合 `1,2,3,11,12,21,22`，并接入公共事务与受管保护；当时未完成真实 SIMION 验证。后继 fresh 与独立阶段现已实现，软件检查覆盖显式 basis 复用和原始 family 保护，详见上文；它们不把当时的退役入口复活，也不替代独立原生 build/save/reopen/Refine/Fly 验收。两次后继原生尝试及其停止点见下文。

| 层级 | 状态 |
|---|---|
| 几何与合同 Static | 可执行 |
| COMSOL 轴对称空包络气流 | 受管 run `20260914_154800__sim__comsol__dual-cone-gas-flow` success，bootstrap、项目报告、独立字段验证及full manifest均PASS；仍仅为无杆、无孔板、无泵口的Prototype |
| canonical COMSOL→SIMION 气体场 | 上述成功run已由下游按full manifest、字段SHA-256和冻结三份源合同消费；未提升为Candidate/Formal资产 |
| SIMION 几何编译 | 纯 GEM 与受管 fresh/独立阶段软件实现可用；历史 `gem2pa/refine` Prototype 证据保留。后继第二次原生尝试完成 geometry、Refine 和 fractional-family audit，随后止于 IOB；独立原生阶段验收仍开放 |
| SIMION 气体辅助轨迹 | fresh 与 saved-field 轨迹阶段已有软件实现，当前原生 Fly 及资格 OPEN；历史 COMSOL场受管run `20260914_162400__sim__simion__dual-cone-comsol-field-n100` success且full manifest PASS，N=100中58个到达末端；均匀400 Pa控制run为0/100，但不是自然压降模型 |
| 独立轨迹跨求解器闭合 | 未建立 |
| Declared CAD STEP / cold BREP | CPU managed and eleven-solid readback passed; profile limits below |
| GUI / Candidate / Formal | BLOCKED |

已完成的气流失败链、质量守恒与粒子统计保存在
[原型记录](history/20260911__empty-enclosure-gas-transport-prototype.md)。

上述快速对照使用规定的后端均匀 `400 Pa`、`300 K`、`100 m/s` 氮气场，不是 COMSOL 压力/速度分布。
其 0% 只说明该控制场在 570 kHz、每组对地峰值 300 V、半径 1.5 mm 源下未传到终止面；不得替代“上游大气储气腔到后端 400 Pa”的自然压降结果，也不得解释为实机绝对传输率。

### 新旧轨迹结果的判定

旧 scratch 运行 `20260914_090618__dual-cone__source-r1p5-n100-r03` 与受管对照运行
`20260914_104709__sim__simion__dual-cone-uniform-400pa-n100` 使用相同的 Fly2 离子源、PA0 几何、
570 kHz 正弦 RF、每组杆对地峰值 300 V、N=100 源及随机种子。前者有 60 个粒子到达终止面，后者为
0 个；该差异由气体输入改变导致，不是电场、几何或离子源回归：

- 旧运行消费空包络 COMSOL 场。轴线上游约为大气压，锥后形成约 `232–625 m/s` 的高速射流；后段压力
  接近 `400 Pa`，但温度约 `57–119 K`。
- 新运行在 `z < 3 mm` 不提供流体支持，在 `z >= 3 mm` 规定恒定 `400 Pa`、`300 K`、`100 m/s` 轴向
  气速。粒子主要在第一段导引器末端附近损失。

因此，对“上游大气储气腔经双锥自然降压至后端 400 Pa”这一科学问题，COMSOL 场驱动的旧路线是正确
模型类别，均匀场新运行只是一项快速控制，不能作为物理答案。但旧运行也不能直接作为定量正确结果：
其气流是无杆、无孔板、无泵口的空包络近似，最大 Mach 数约 `4.52`、孔口最大 Knudsen 数约 `0.034`，
采用人工各向同性扩散，且尚未完成网格与稳定化敏感性复核。当前可接受结论是“差异来源已定位；旧路线
相关、新结果仅作控制；60% 与 0% 均不是实机绝对传输率”。

当前受管COMSOL场把这一判断重新闭合：气流run的最大Mach为`4.5192`、最大孔径Kn为`0.03424`、进出口
质量守恒相对误差为`0.843%`，随后SIMION success run得到`58/100`。同一成功气体场、源合同、RF和PA
配置的一次发布失败复验曾得到`60/100`；两次气体运行时Lua哈希相同，但粒子终态不完全相同。现有seed
字段尚不能证明Fly2源生成与官方SDS碰撞链可以逐粒子位复现，因此`58`与`60`应视为N=100随机实现的
重复波动，而不是气压场或电场再次改变。当前可引用值是manifest成功run的`58/100`；它与旧路线约60%
相容，但样本太小，仍不能给出精确传输率或实机定量结论。

## 开放任务

1. 确认两个锥角定义、朝向、实体孔口面、厚度、外径、孔筒和 `3 mm` 的机械测量对象。
2. 确认椭圆杆有效长度、中心坐标、轴向方向、`7.48 mm` 的杆对定义，以及 `1.6 mm` 是轴向还是法向净距。
3. 确认 `5.64 mm` 是相邻还是对置中心距、两组杆是否同轴，以及 `2 mm` 间是否存在 IQ0/孔板/绝缘板。
4. 对当前受管空包络CFD完成网格／稳定化敏感性复核，再决定是否发布全局current场；均匀400 Pa不能代替。
   孔板仍排除，除非科学问题明确要求板前积压、孔内射流或板后膨胀。
5. 给出各锥、壳体和出口件的 DC，以及目标离子、源分布、迁移率或 CCS；两段 RF 的幅值口径与频率
   范围已经确认，但仍需决定是否扫描 `550 kHz` 和 `590 kHz` 端点。
6. 补充气体场依赖、RF/DC 参数、SIMION GUI 可检查性和损失事件复核；通过后再开放 Candidate。
7. 建立端部、绝缘、支撑、馈通和泵口机械细节，并完成 COMSOL GUI、SIMION GUI 与 SolidWorks 同步后
   才开放 Formal。

## 产物边界

活动产物位于 `artifacts/projects/dual_cone_tandem_quadrupole_ion_interface/`。COMSOL 气流和 SIMION
轨迹各自使用独立 run 三件套；下游 SIMION run 按所选输入冻结上游 manifest、源合同与编译 runtime
身份，并保留所引用已发布气体场的原始记录。旧 Python run 只读保留，不因旧路径退役而删除或改写。

## 普通执行计划

`axisymmetric_gas_flow_screening_static`保留既有profile身份，普通计划不再先运行整套`static_gate`；独立软件验证、原COMSOL气流／资源／输出准入及Prototype边界保持。
公共profile删除未消费的虚假binding，固定`geometry_baseline`、`resolved_geometry`、`gas_flow_science`和`comsol_solver_numerics`四项。编译结果保存同一小JSON定义，经`ResolvedInputsPath`显式交安装操作校验和冻结；缺baseline的旧bundle要求重新编译，不用当前默认补造旧resolved来源。
安装操作调用同一规范geometry解析器，对显式baseline/resolved进行原逐字节新鲜度检查；输入／派生物失配在商业调用前失败。隔离回归核对本次规范包来源，不借作者checkout补缺。气流成功不代表离子传输或新资格。

早期纯准备的[树外冻结回归](../tests/test_simion_layer.py)通过公共源码枚举交付当时规范核心，并保留项目prepare、配置和Program快照；隔离解释器`-I`下核对真实模块来源，缺少原生映射模块时明确拒绝，不借作者路径补洞。该证据只覆盖当时的两种无PA准备模式。后继完整准备实现已迁至安装包，fresh 与独立阶段另有软件实现；这些证据均不代替当前原生 Fly 或科学资格。

## 机器能力与解析输入

gas-flow profile 的 baseline 与 resolved geometry 传入原 runner；prepare 冻结原 resolver 和输入并核对新鲜度，失配在下游原生调用前失败。
能力查询与执行编译见[公共合同](../../../common/contracts/README.md#执行dry-run)；READY 仅描述声明条件。

### Gas-field data contract ownership

`msplatform.contracts.gas_field` owns recorded r-z data structure and provenance;
the component's `gas_field_validation` owns the original study policy and CLI.
Producers, the runtime compiler and scientific execution boundaries apply that
policy explicitly. The offline results reader retains strict manifest, hash and
terminal checks without component, backend or execution imports; readable data
does not by itself grant study acceptance. The current typed result and policy
split are described below. Frozen native gas-flow operations are unchanged.

The earlier validator relocation passed 25 focused boundary/reader/producer/contract tests
and the original five-method ordinary wheel/sdist acceptance (including offline
reader origin and missing-validator rejection in both installed rounds). No new
COMSOL/SIMION solve or scientific qualification was performed. Those results
retain their original source versions; they are not current split acceptance.

### Installed gas-flow native acceptance (2026-11-09)

An ordinary 365-payload wheel, SHA-256
`defe92f298459e0697fa207fb3ee520baaf695d072fcd0e53c189c8b5107ba54`,
completed build `20261109_195300__sim__comsol__p4-gas-installed-build-r1`
and separate model reexport `20261109_200643__sim__comsol__p4-gas-installed-reexport-r1`.
Their manifests are respectively
`64895B2CBF78C49038F0961906FD68CBBD8811EF1ED5D91338D56DE78878656D` and
`BA815D8690BE81E1A2ED8FF0F9536D4AB86DF92F87D464BFE534EAE4BB702F7D`.
Both native operations returned zero with known writer births, confirmed exits and
released shared-host resources; capacity ledger closure and absent protection leases
were checked independently. The 11,541,539-byte original MPH retained SHA-256
`680BECB779F0261AC7873DD661F5DBAB8BC57CC4F6F0DDA508E11BB3593900D4`
through reexport. No source, frozen contract or installed payload was changed.

Both field exports validated 295,236 rows (236,104 fluid), mass-balance relative
error 0.008456419398312964, maximum Mach 4.51920108889889 and maximum Knudsen
0.0342367589765737; terminal artificial diffusion remained 0.1. These are the
existing empty-enclosure prototype contract results, not calibration, convergence,
ion transport or Formal qualification. The provisional engineering profile was
3600 seconds, 8 GiB process memory, 1 GiB files, 1 GiB available-RAM reserve and
zero retries; these were user-selected limits, not measured solver requirements.
Usage telemetry retained its last running samples rather than a final maximum;
sampled build/reexport peaks were about 3.516/3.276 GB. Final process/resource
closure is established by completion receipts and live ledger/process checks,
not by those stale usage snapshots.

A separate ordinary-installed offline reader passed with execution imports and
MPH opens forbidden. The later contracts-owner source also reopened both original
published data products with component/backend/execution imports and MPH access
forbidden. That read proves current data interpretation; it does not relabel the
365-payload native source as the later package epoch. Gas-assisted ion Fly, GUI,
scientific qualification and complete P4 software/performance acceptance remain open.

The fresh workflow binds its audited eleven family/witness identities through IOB
creation, closed reopen and Fly. Original prepared source/configuration, gas-runtime,
RF-kernel and five SDS records are verified before binding; copied Program/FLY2
identities are fixed before IOB creation, verified after that writable save boundary,
and guarded with the newly created IOB for reopen and Fly. This corrects a static
Fly guard omission; it is not evidence of an earlier physical-result defect. Real
inert process regressions deny basis/control write and delete attempts and reject
a changed original identity before payload launch; unknown-writer protection retains
its existing generic regression. No dual-cone vendor Fly has run in this epoch.

The fresh operation accepts only the existing engineering runtime field
`simion_allow_asynchronous_io` (explicit boolean). Its selected value reaches all
six native operations, including Fly, through the canonical verified native-I/O
prelude; omitted mode keeps vendor-default behavior. A native request on this
Windows host selects false explicitly. Inert public-owner checks cover false, true,
omitted and malformed selections; no new native result is inferred from them.

The first installed fresh native attempt stopped at raw namespace validation,
before Refine or Fly. GEM compilation and PA save succeeded. A read-only scan
using installed official PA.py found exactly all seven declared raw metal labels
(1, 2, 3, 11, 12, 21, 22); the original PA hash remained unchanged. The failure
was the builder's use of fast-adjustable electrode metadata on raw PA#. The
successor validates every raw metal point against the declared set and captures
its first physical witness, with missing and late extra labels rejected. It keeps
the same geometry, grid, source, surface validation and no-witness default branch.
This correction has software regressions; it is not a successful native rerun.

The corrected raw-checker native epoch completed geometry build, Refine and
fractional-family audit, then stopped at IOB creation. Its caller had serialized
a canonical bootstrap path while the canonical writer projected the seed into
the process-local execution alias; the strict seed-local invariant correctly
rejected that mismatch. The caller now declares canonical file roles but supplies
owned bootstrap and Fly IOB/FLY2 execution spellings consistently. Core assertions,
seed data, original PA family and scientific inputs are unchanged. A regression
feeds the actual public action's materialized spec and the actual native path
projector through canonical Lua build/reopen, with missing/wrong bootstrap controls
rejected before native writes. This is software proof; no subsequent native Fly
or transport qualification is implied by the correction.

Callback completeness: the installed Program now explicitly enables official SIMION global callbacks, retaining outside-PA terminal states as unknown code 0 and existing SDS support-loss code 3 with per-particle deduplication. The actual-Lua dispatcher regression reproduces missing coverage before the fix and complete terminal census after it. SDS8.1.2.7 excludes instance 0 from collision acceleration/diffusion; no external electric/magnetic field is supplied. This software proof is not native Fly qualification; the two earlier native failures remain unchanged.

A scoped T3 standalone-Lua regression exercised twelve combinations of first
pressure, temperature or velocity callback, `no_data` or `outside_domain`, and
`coverage_loss` or `error` policy through the actual generated field, Program
and SDS binding with an inert supplier. Coverage loss flushed one code-3 final
row during the callback and remained latched at a verified supported gas point;
the strict outside-domain case raised and did not publish that terminal row.
The focused software gate passed. This establishes callback wiring and declared
seed/install calls, not vendor collision physics, native Fly, step crossing or
random-stream equivalence.


### Explicit PA grid authority

Current numerical inputs explicitly select pa.grid_points_xyz and cell_mm_xyz. Actual spans are (N-1)*cell; numerical array embedding is independent of world placement. Symmetric margins and exact span/cell tiling are not required. Default103/103/245 preserves default GEM bytes. Full metal containment is checked; source/observation coverage belongs to consumption stages. Counts/cell/embedding bind geometry/model/basis identities, while source/cadence remain independent. Missing counts reject without supplementation. Historical inputs/results remain unchanged; no native qualification is inferred.

### Explicit target composition

`msplatform.workflows.dual_cone_stages.plan_to(target=..., request=..., available=...)`
and `run_to(plan, context=...)` compose the existing geometry/model/fields/trajectory
stages. Request groups use those same stage arguments without context or predecessor
references. `available` explicitly selects published products; absent prerequisites
are built only from supplied request groups, while missing, changed or conflicting
references fail rather than selecting another run or silently recomputing fields.
Explicit saved geometry, model and field products must also agree on their device-to-world
placement and named frames, including the established default embedding when placement is
omitted. Equal local PA geometry does not erase a conflicting saved world pose. An explicit
new model request still permits the existing deliberate model/basis rebind path.

Geometry/model/fields do not require source, gas or SDS. A trajectory from saved
fields calls only the existing tracking-model build/reopen and Fly; changed drive
uses the existing model binding and explicit basis-reuse audit, whose actual tool
compatibility is checked by the backend at execution. A plan is not native proof.
Planning acquires no lease or tool; execution revalidates products and the selected
small request-file authorities before invoking the unchanged stage owners.

An explicitly supplied complete trajectory can be selected with no context or
solver only when no competing new scientific request is supplied. This does not
claim a general trajectory-compatibility comparator. Historical results are unchanged.
The new software tests use inert outputs through the actual managed owners; the
independent native multi-process chain and scientific qualification remain OPEN.

The composed target/boundary modules passed 27 parents and 180 successful records
in 95.039 seconds. The independently reviewed R3 private source also passed both
ordinary wheel/sdist-rebuilt installation arms (96.094 seconds, 440 exact payloads,
source-root denial and missing-module rejection). Main adds public type annotations
with every delivered function body unchanged; that private package proof is not
retagged as a combined successor installation or native result.

### Gas export structure and explicit study quality

`msplatform.results.gas_field.read_gas_field` now returns an `OpenedGasField`:
`.artifact` retains the original published records, metadata and locations, while
`.data` contains the actual neutral structural scan. Recorded CSV hashes, source
hashes, finite values, axes, row order and NaN mask semantics remain enforced.
Reading data requires no COMSOL, execution owner or component import and does not
grant the dual-cone study's scientific acceptance.

The sole project policy and five-path validation CLI are in the component's
`gas_field_validation` module. Producers validate before publication; scientific
planning and preparation explicitly apply the same policy to the scanned data.
This preserves positive fluid values, the original recorded EOS, minimum sample
count, mass balance, outlet pressure, terminal stabilization and continuum-use
qualification. Same-scan policy checks perform no file reads. Existing separate
public planning, owner-freeze and preparation integrity boundaries remain; this
ownership slice does not claim to remove their pre-existing repeated reads.

The data snapshot retains immutable numeric columns and a mask, not raw CSV
strings or a second artifact cache. Original record identities and owner guards
still govern later file consumption. Historical producer bytes and formats are
unchanged. A readable result that fails study quality remains readable for
inspection but is rejected by the original scientific execution boundaries.

The selected 20261109_195300 published CFD export has 1,251 fluid axis rows;
194 have nonzero radial velocity, at most 1.48174396448725e-14 m/s. This split
preserves those actual source scalars and does not instantiate the stricter G1
axisymmetric representation, zero values, or add an epsilon. Explicit versioned
legacy axis projection and canonical Lua/SDS adoption remain separate work.
No new CFD or ion Fly, native equality or scientific qualification is claimed.

The annotated composed successor passed 32 parents and 262 records in 66.268
seconds, without skips: original export/producer/reader contracts, architecture,
actual public bad-quality rejection and all three Changed routing cases.
Independent review accepted the original policy and 278 retained assertions.
The private pre-annotation source passed focused direct-wheel/sdist-rebuilt
acceptance in 98.943 seconds with 446 exact payload joins per arm. That source
excludes the later cooled addition; its installation evidence is not retagged as
the composed annotated package. Final combined installation remains due.
On the unchanged 295,236-row CFD source, one instrumented baseline/candidate
observation returned identical quality summaries: 36.681/34.835 seconds and
330,510,444/364,722,767 bytes of peak traced Python allocations. The new data
result retains 16,828,452 bytes of numeric columns and mask. These are not RSS
measurements; cache order, shared load and tracing overhead prevent a speedup claim.

### One joint gas compiler and explicit SDS callback binding

Current source construction belongs to component `gas_field`; actual Lua
compilation/materialization belongs to backend `gas_runtime`. Both previous
component emitters are retired with their live callers. The current interface
and compiled manifest use version 2 and a joint `sample` ABI, with source-specific
interpolation/outside-domain policy instead of the misleading common bilinear
label for prescribed gas. No scalar API bridge or old compiled-source fallback
is provided. Historical CSV/metadata and original compiled artifacts are not
rewritten or completed from today's package.

The typed `axisymmetric_piecewise_uniform` representation preserves constant
cylindrical p/T/ur/uz and the actual rear discontinuity without a fake grid or
Cartesian reinterpretation. Uniform source composition is supplied explicitly
from existing selected science; CFD composition metadata derives from its
recorded species/molar-mass convention. Actual SDS mass, diameter and diffusion
remain the selected transport-science values. The named 400 Pa case remains a
component restriction, not a universal gas restriction.

Legacy CFD explicitly retains raw axis ur values and returns zero radial
Cartesian vector only at the queried axis. Strict G 1 regularity remains the
default. CFD and prescribed legacy profiles retain sqrt radius, actual valid
corner support, `.9g`/`.17g` and 8192 chunks. Annular domains preserve CFD rmin.
The original uniform rmin=0 control retains its 1e-6 mm envelope; honoring nonzero
uniform rmin is a separately selected annular successor correction, because the
old emitter ignored that parameter. No new epsilon, physical model or random
policy is introduced.

The ordinary SDS binding resource assigns the official pressure/temperature/
velocity callbacks and installs once. It receives each actual callback's joint
sample independently, never caches by time/particle, and converts Pa to Torr
and local m/s to workbench orientation exactly once. Program keeps official
import, lexical adjustable initialization, once/run seed and terminal/mother
ownership. No-data and uniform outside coverage emit final code 3 before fallback;
strict CFD outside coverage raises. Program-run bookkeeping reset is the
separate lifecycle correction above, not evidence of a vendor hidden-state
reset, native repeated Fly equality, repartition equivalence or checkpointing.

Software, ordinary installation, lookup cost and actual native qualification
remain separately evidenced. This section does not grant new CFD accuracy,
successful current ion Fly, integrator crossing precision or Formal status.

B/C software evidence is private source `208e1185` plus the separately accepted
four-table lifecycle reset. The original 98-parent consumer round retained
three failures (two incomplete harness configs and the original axial error
message); only those three were rerun after repair and passed. Two additional
source-lineage parents passed, including actual direct records and explicit
malformed/missing/mismatched producer negatives. The selected 295236-row CFD
raw scalar columns/mask and 194 nonzero radial-axis values were preserved.
Archived/new emitted Lua agreed numerically at all selected CFD and signed
uniform queries (zero ULP); two equal-valued textual zero spellings differed.
Six annular CFD queries also agreed exactly. Uniform nonzero-rmin behavior is
an explicitly selected correction, not a legacy-equivalence claim.

Actual fixed-old/new Program inert-SDS harnesses produced byte-identical
first/repeated-run trajectory and final CSVs for sparse IDs 1,7,101, with one
install and one seed per run. This does not qualify vendor hidden state or
native integration. Focused ordinary direct/sdist-built wheels each joined
all 447 selected runtime files to source/site-packages, with physical missing
component/binding negatives and both retired emitters absent (81.018 seconds).
The earlier task-only negative harness failure is retained. This is not a
complete installed-test or native qualification claim.

A bounded ordered Lua CPU observation of 10000 loaded callback triplets found
old/new CFD 0.038/0.440 seconds and uniform 0.092/0.217 seconds. The new joint
state computes all fields/EOS independently per actual supplier callback;
this added cost is explicit. It is not a controlled whole-run performance
comparison. No cache, callback merging, RNG change or numerical shortcut was
introduced. Current native Fly equivalence and the whole-software 15-minute
budget remain open.

The 81.018-second installation observation above is the pre-projection epoch,
retained separately. A conservative successor removes transient result tables
and fuses the same four CFD sums without changing per-field corner/product/sum
order. Every callback still validates all four fields, velocity rotation and
EOS; public joint sample output and all extreme-value failures remain checked.
The final fused epoch passed a fresh focused direct/sdist installation in 89.699
seconds, with 447 exact runtime payload joins in each arm and actual missing
component/binding/vendor negatives. Original full consumer failures are retained:
the optimized 46-parent round had 45 successes and one source-shape assertion
using the previous local variable name; the exact corrected parent passed.
A subsequent 48-parent gas/runtime/boundary round passed; these are distinct
rounds, not a fabricated single all-green 98-parent rerun.

The final actual fixed-old/current Program callback observation used 10000
triplets and inert supplier installation: CFD 0.050/0.211 CPU seconds, uniform
0.083/0.104. Checksums were identical. Allocation-only measurements 0.074/0.331
and the earlier direct-sample measurements have different epochs/scopes and are
not controlled speedup evidence. Remaining CFD cost is explicit: all four fields
and runtime validity checks are computed for every actual supplier query. No
skip, cache or error-semantic relaxation hides it. Native/vendor equivalence
and whole-software budget remain open.

The composed G3 B/C successor passed 132 software parents and 538 records in
181.489 seconds, including the actual Changed route into the existing seven
backend consumers and project owner. Fresh focused direct-wheel and rebuilt-
sdist consumers passed in 95.245 seconds: all 457 runtime payloads joined source,
actual build source, both distributions/installations and sdist. They exercised
the actual preparation, emitted Lua and Program with inert SDS, source denial
and missing-resource/module refusal; they did not execute SIMION or qualify SDS
physics. The earlier complete installed-core acceptance predates this gas slice.
The named 400 Pa constructor remains constrained here; general prescribed-study
pressure freedom requires its separately validated successor. CFD callback cost,
final combined installation, Repository and native acceptance remain open.

### Explicit prescribed pressure studies

The recorded `uniform_400pa_plug_flow_prototype_v1` retains its 400 Pa constraint
and unchanged compiled golden. A different explicit nonempty `model_id` selects
another study through the same `prepare_uniform_rear_gas_field` constructor;
it accepts finite nonnegative rear pressure, with zero an explicit vacuum
control. The same role, explicit source/interface records, temperature/velocity,
composition, sampling profile and materializer/public preparation remain.
No default request, source file or historical result is changed. Blank or
non-string study IDs, invalid pressures and altered source identities reject.
Actual stock-Lua Program/SDS callback tests are software wiring evidence, not
native or vendor collision qualification.

The composed explicit-study successor passed 28 software parents and 127 records
in 3.013 seconds. Fresh direct-wheel and sdist-rebuilt consumers passed in
91.307 seconds, including actual 125 Pa and zero-pressure preparation/Program
wiring, invalid/source negatives and the unchanged original 400 Pa Lua golden.
All 457 runtime payloads joined source/distributions/installations; only the
component constructor changed from the preceding gas package. This closes the
identified software pressure-selection gap, not native collision or RNG physics.
