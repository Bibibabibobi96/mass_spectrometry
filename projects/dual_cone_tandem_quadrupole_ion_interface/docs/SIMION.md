# SIMION 最小实现与边界

本文维护 SIMION 的活动入口、表示与验收；当前资格见 [PROJECT](PROJECT.md)。
研究 wrapper 的命令从仓库根执行；安装包入口使用显式路径和部署 context。尖括号内容须替换为
显式冻结输入或符合命名合同的新 run ID。

本项目的离子轨迹推进权威是 SIMION。Python 只编译 GEM、校验输入、序列化粒子源和整理证据，不能
积分离子运动。

## 当前能力与验证边界

当前数值合同和 GEM 使用 fractional 表面增强，`.pa-surf` 与原始场族保护继续保持。
`msplatform.workflows.dual_cone_transport.run_gas_assisted_transport` 已实现 fresh 管理链；
`msplatform.workflows.dual_cone_stages` 提供 `build_geometry`、`prepare_model`、`solve_fields` 和
`track_fields` 的软件实现。它们组合现有公共 owner，不复制已发布场族、不隐藏重求场，也不通过
无表面增强或假粒子绕过约束。已退役的四个旧 wrapper 和旧执行 profile 不恢复。

软件实现与成功原生验收分开：当前 fresh 的首次原生尝试停在 raw checker，修正后的一次停在 IOB
创建；两次失败及其修复事实保留于 [PROJECT](PROJECT.md)。尚无本轮成功 Fly 或独立阶段原生
验收，不授予碰撞、精度、GUI 或 Formal 资格。COMSOL 气流与离线场读取有各自证据，不能转授
离子输运资格。下面的纯准备接口仍可独立使用。

## Installed pure preparation

Use `msplatform.backends.simion.dual_cone_transport.prepare_transport` or its installed CLI
`python -I -m msplatform.backends.simion.dual_cone_transport --help`. Supply the resolved geometry,
SIMION numerics, ion-transport science, gas interface, gas science and release specification explicitly.
`trajectory.sample_interval_us` is the explicit positive finite observation cadence in SIMION numerics;
it changes sampling output only, not RF stepping or maximum integration time.
Gas preparation additionally selects either a published `gas_field` reference (CSV/metadata/original
contracts read through the canonical reader) or an explicit validated runtime manifest. Official SDS's
five files are supplied by an explicit installation directory, with no installation finder or checkout
fallback. The research `prepare.ps1` transports these paths to the installed CLI only.

The Program and RF kernel come from canonical installed resources. Particle serialization is owned by
`msplatform.backends.simion.source`; release sampling by `msplatform.ion_release.release`. The Program
uses official `SDS.init` to bind the explicitly requested collision gas mass, diameter and diffusion switch
before official initialization. Source/code migration and inert initialization do not authorize native
Fly or qualify the seven-electrode fractional native chain. See PROJECT for the reproduced
prior unused-knob behavior and vendor API evidence.

当前源圆柱半径为 `1.5 mm`，位于半径 `5 mm` 的上游储气腔内。源可以宽于第一锥 `1 mm` 孔半径；
运行器保留这些离子，并让锥孔电极几何和一致的 COMSOL 流体支持边界代理决定其能否进入下游。

当前两段 RF 均为 `570 kHz` 正弦波，电极组 1/2 分别为 `+300 sin(omega t)` 与
`-300 sin(omega t)` V；因此每组对地峰值为 `300 V`，对置组之间为 `1200 Vpp`。`570 kHz` 是用户
给定 `550–590 kHz` 范围的标称中点，不代表频率扫描已经完成。

## Explicit spatial placement

The independent workflow operations accept `placement`, a canonical proper
`RigidTransform` from the resolved device frame to the selected workbench frame.
Tracking additionally accepts `source_to_device` when the source frame differs;
this is a tracking/source input, never a geometry-only requirement. The pure
preparation CLI uses explicit `--placement <JSON>` and `--source-to-device <JSON>`.
Omitting both selects the historical translation-only input shape. Fixed C0
smoke accepts device placement but rejects a supplied source registration, since
it does not consume a sampled release. Existing gas-assisted source files can be reused with a declared registration, without rewriting or
resampling them. Actual transformed particles must remain inside the local
upstream plenum and PA extent. One PA, unit scale, seven native electrode IDs and
all frozen-family safeguards remain in force.

For stored trajectory plots, pass the frozen placement JSON with `--placement`,
or explicitly select `--historical-translation-only` for original offset-only
data. The plot and terminal distribution use device-local positions; raw stored
workbench coordinates and time are retained. Current software/native evidence
and the separate CAD/provider gap are recorded only in [PROJECT](PROJECT.md#device-placement-and-source-frame-binding-p11).

## 几何范围

单体 PA 使用电极 `1/2` 表示两锥，`3` 表示末端孔板，`11/12` 表示椭圆杆两相，`21/22` 表示圆杆两相。设备坐标到
PA 数组的嵌入平移记录在 `simion_solver_numerics.json`；新的显式工作台位姿与它组合一次。单体 GEM 由
`msplatform.backends.simion.dual_cone_geometry` 编译，杆几何直接复用
`msplatform.backends.simion.rf_geometry.render_grouped_rod_array_gem`，项目不复制圆杆或椭圆杆公式。

The declared CAD profile follows the resolved conical upstream cut; its
implementation and limits are described in [CAD](CAD.md). The existing C0
approximation below is unchanged and is not claimed shape-equivalent to that STEP.

当前 C0 GEM 把椭圆杆入口暂时截为 `z=4.6 mm` 平面。真实“沿第二锥面切削”仍需项目级、经拓扑
测试的 CSG mask；在它完成前，C0 只证明 GEM/PA 电极命名和粗几何可编译，不证明入口边缘场。

低压圆柱壳因壁厚和端部结构未知而未虚构为导体；泵口、两段间透镜和出口透镜同样未建模。

## 气体场接口

The component `gas_field` module constructs explicit accepted CFD or cylindrical
prescribed input; `msplatform.backends.simion.gas_runtime` is the single compiler
and materializer. `build_gas_runtime.ps1` uses these same bodies. Current interface
and compiled ABI version2 provides only `sample(x_mm,y_mm,z_mm,frame_id)`, returning
status, Pa, K and Cartesian m/s velocity together. Both old component emitters
and their scalar runtime APIs are retired; historical frozen bytes are unchanged.

The explicit legacy CFD profile preserves `.9g` values, `.17g` axes/domain,
8192-entry chunks, fluid-corner renormalization and raw radial values at axis
nodes; only the queried Cartesian radial vector is zero at r=0. Strict G1 axis
regularity remains the default. The named uniform control preserves signed ur,
z=rear ownership and its 1e-6 mm padded envelope. Nonzero inner-radius uniform
requests select the versioned annular successor: the old emitter ignored rmin.

The ordinary `collision_sds_binding.lua` installs official SDS callbacks from
joint samples without cross-callback caching. Program retains lexical SDS.init
and import, run-level seed, PA coordinate/orientation conversion and terminal
ownership. Velocity is m/s with rotation only; pressure uses760/101325 to Torr.
No-data and uniform-envelope loss emit final code3 before safe fallback; strict
CFD outside-domain remains an error. Code3 is gas coverage loss, not independently
qualified wall-collision physics.

禁止外推；整个 `z=-5..120 mm, r=0..23.5 mm` 域必须覆盖。圆四极杆在 `z=108.00 mm` 结束，孔板位于 `z=110.22..110.72 mm`，板后保留 `9.28 mm` 观察段；为防止 SDS 在终止步越过气体场，离子终止采样面设在 `z=119.75 mm`。后续飞行 Program 必须通过官方
`collision_sds.lua` 注入这些函数，并通过共享 RF kernel 驱动电极；不得用 Python 阻尼积分器替代。
Cut cells continue to interpolate using renormalized valid-fluid corner weights.
For CFD queries inside the governed domain, `no_data` causes the Program to
flush terminal code 3 and stop the ion. A prescribed uniform field uses the
same code when its declared coverage is left. Under the existing strict CFD
outside-domain policy, `outside_domain` raises the original error; it is not
converted to code 3. No-data and coverage loss do not independently establish
a physical wall collision. Their interpretation remains limited by the 0.1 mm
gas grid, 0.5 mm PA grid and unconfirmed aperture rounding.

The trajectory projection separates terminal-plane arrival (1), time limit (2),
gas-support loss (3), and unknown termination (0 or missing terminal record).
The existing codes do not separately prove physical wall loss. The plot counts
only particles with trajectory samples and reports terminal records without
tracks; it is not a complete mother cohort or transmission-rate estimate.

原型粒子数和当前资格见 [PROJECT](PROJECT.md#当前资格)，束斑统计与原记录的限制见
[原型历史记录](history/20260911__empty-enclosure-gas-transport-prototype.md)。

[返回项目状态](PROJECT.md)


## Fresh managed transport implementation

The public scientific entry is
`msplatform.workflows.dual_cone_transport.run_gas_assisted_transport`. It takes
explicit resolved geometry, SIMION numerics, ion transport science, gas interface,
gas science and source-spec paths, a published gas-field reference, the official
five-file SDS directory, and the existing deployment ExecutionContext. The explicit
engineering stage policy must define `dual_cone_transport`; no RF or gas-solve
budget is silently inherited.

This entry composes fresh geometry build, Refine, field audit, IOB build/reopen and
Fly under one RunSession. Tracking cannot trigger a hidden Refine. The public result
is an existing manifest-bound `trajectory_result`; final CSV and metrics can be
read through its explicit data members, or analyzed by
`msplatform.analysis.terminal_plane.analyze_terminal_plane` with the declared full
source count and axis. The family is unpublished until writer closure; there is no
published-family copy or cache-open path.

Software wiring and native qualification are separate. Native execution of this
new path is pending its reviewed request and budget; independent stage publication,
saved-field reuse, GUI and scientific qualification remain OPEN. See PROJECT for
the numerical-cap correction and preserved historical results.

The current compiled ABI2 also binds `_sample_sds`, an internal numeric channel
projection used only by the ordinary SDS adapter. Public `sample` still returns
the complete joint state. Both use one stencil/query implementation and retain
all field, rotated-velocity and EOS validity checks on every actual callback.
The projection avoids unused result/metadata allocations; the four-field CFD
sum loop keeps the original per-field corner/product/sum order. No sample cache,
channel-skipped validation, vendor reset or RNG/callback change is introduced.

Explicit prescribed-pressure studies use the existing constructor and preparation path;
see the single [study contract](PROJECT.md#explicit-prescribed-pressure-studies).
