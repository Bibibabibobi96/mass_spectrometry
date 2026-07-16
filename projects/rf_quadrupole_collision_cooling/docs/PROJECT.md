# RF 四极杆项目状态

## 当前结论

`transport_no_collision` 候选已在 COMSOL 6.4 与 SIMION 2020 闭合并通过 GUI 资产复验。它证明的是
RF-only 径向约束和轴向传输，不是碰撞冷却或质量过滤，也还不是需要 SolidWorks 同步的机械正式模型。

统一参数分为共享硬件、共享粒子源和功能模式三层：`../config/baseline.json`、
`../config/official_particle_source.json`、`../config/modes/*.json`。以后在集成仪器中，传输四极杆与质量
过滤四极杆实例化同一硬件模板，分别绑定 `transport_no_collision` 与 `mass_filter_reference` 配置和空间
变换；不复制两套近似几何。质量过滤配置目前只冻结官方参考值，尚未验证。

## 权威基线

- 几何：SIMION 2020 `examples/quad/quad_monolithic.gem`；总长 95.2 mm、杆段 79.6 mm、
  `r0=4 mm`、圆杆半径 4.592 mm、PA 单元 0.2 mm、入口孔半径 1.2 mm、出口/检测器半径 3.6 mm。
- 粒子：固定 25 个 100 amu、+1 离子；birth 0--0.909091 us、横向位置 ±0.05 mm、
  1.8--2.2 eV、绕 workbench +x 的填充 5° 圆锥，源表为 `../config/particles/official_fixed_25.ion`。
- IOB 实测坐标：PA x→workbench z、PA y→workbench −y、PA z→workbench x；COMSOL 的位置和速度
  均按这个完整三轴关系映射。
- 传输波形：两组对置杆 `±139.81792 V peak`、1.1 MHz、0 V DC/轴偏置；入口、出口、检测器均 0 V；
  无碰撞、无阻尼、无背景气体，Mathieu `q=0.7060233`。
- 收敛数值：COMSOL mesh auto level 1、80 RF 步/周期；SIMION quality 10、40 RF 步/周期。

## 验证结果（2026-07-17）

| 求解器 | N | 命中 | 传输率 | 平均检测时间 (us) | 最大杆区半径 (mm) |
|---|---:|---:|---:|---:|---:|
| COMSOL | 25 | 25 | 1.00 | 50.1673 | 0.4944 |
| SIMION | 25 | 25 | 1.00 | 49.7386 | 0.4729 |

传输率绝对差为 0，平均 TOF 相对差为 0.858%，两端最大杆区半径均远小于 `r0=4 mm`；跨求解器
门禁 PASS。完整三轴对齐后，COMSOL 80→160 步平均 TOF 变化 0.05%、最大杆区半径变化 0.89%；
mesh2→mesh1 的对应变化为 0.28% 和 9.82%，命中均为 25/25。SIMION 20→40 步平均 TOF 变化
0.00030%，最大杆区半径变化 0.051%。

COMSOL MPH 重开后，`std1`/`std2` 通过 Study GUI Compute 路径复算仍为 25/25，Solver 标签保持
`sol1,sol2`。SIMION IOB 重开确认单实例、变换 `(az=-90, el=0, rt=180)`、PA 为
`39×39×477`、单元 `0.2 mm`，项目本地 Lua/Fly2 生效。

终点诊断图由 `analysis/plot_terminal_distribution.py` 生成到
`artifacts/.../results/cross_solver/transport_no_collision_terminal_distribution.png`：上排两栏使用同一
PA/COMSOL 横向坐标与颜色尺度，虚线圈表示 3.6 mm 探测器口径，圆点是探测器命中、叉号是非探测器
终止，颜色表示终止轴向位置；下排按相同粒子 ID 给出 SIMION→COMSOL 终点差矢量和逐粒子横向差。
当前两端均为 25 个命中；未来撞杆、出口壳体或超时离子会保留在同一图中。

## 产物与边界

- COMSOL 候选：`artifacts/.../models/comsol/candidates/rf_quadrupole_transport_no_collision_simion_reference.mph`
- SIMION 候选：`artifacts/.../models/simion/candidates/quad_transport/`
- 闭合证据：`artifacts/.../results/cross_solver/transport_no_collision_closure.json` 与 paired CSV
- 先前 150 mm 简化直杆 MPH 保留为失效候选，不进入门禁；历史 `test3` 碰撞模型也不能证明本结论。
- 本阶段未选定机械正式几何，因此没有触发 SolidWorks 同步；若以后提升为正式组件，必须同任务完成 CAD/装配同步。
