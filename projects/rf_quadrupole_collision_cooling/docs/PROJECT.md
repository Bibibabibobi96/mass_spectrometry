# RF 四极杆项目状态

## 当前结论

`transport_no_collision` 候选已在 COMSOL 6.4 与 SIMION 2020 闭合并通过 GUI 资产复验。它证明的是
RF-only 径向约束和轴向传输，不是碰撞冷却或质量过滤，也还不是需要 SolidWorks 同步的机械正式模型。
2026-07-17 新单一运行配置与manifest链已用SIMION固定25粒子复验，25/25命中、传输率1.0。

统一参数分为共享硬件、共享粒子源和功能模式三层：`../config/baseline.json`、
`../config/official_particle_source.json`、`../config/modes/*.json`；程序统一读取自动生成的
`../config/resolved_geometry.json`，全项目门禁为`../verify_project.ps1`。以后在集成仪器中，传输四极杆与质量
过滤四极杆实例化同一硬件模板，分别绑定 `transport_no_collision` 与 `mass_filter_reference` 配置和空间
变换；不复制两套近似几何。质量过滤配置目前只冻结官方参考值，尚未验证。

## 权威基线

- 几何：SIMION 2020 `examples/quad/quad_monolithic.gem`；总长 95.2 mm、杆段 79.6 mm、
  `r0=4 mm`、圆杆半径 4.592 mm、PA 单元 0.2 mm、入口孔半径 1.2 mm、出口/检测器半径 3.6 mm。
- 粒子：固定 25 个 100 amu、+1 离子；birth 0--0.909091 us、横向位置 ±0.05 mm、
  1.8--2.2 eV、绕 workbench +x 的填充 5° 圆锥，源表为 `../config/particles/official_fixed_25.ion`。
- IOB 实测位置坐标：PA x→workbench z、PA y→workbench −y、PA z→workbench x。Fly2
  `standard_beam` 的 `az/el` 在 IOB 放置前按其局部束流基向量解释；逐轨迹斜率审计表明，若
  `vSim=(v cos(el)cos(az), v cos(el)sin(az), v sin(el))`，则 COMSOL 速度必须为
  `(-vSim_y,-vSim_z,vSim_x)`，而不能机械套用位置的逆变换。
- 传输波形：两组对置杆 `±139.81792 V peak`、1.1 MHz、0 V DC/轴偏置；入口、出口、检测器均 0 V；
  无碰撞、无阻尼、无背景气体，Mathieu `q=0.7060233`。
- 收敛数值：COMSOL mesh auto level 1、80 RF 步/周期；SIMION quality 10、40 RF 步/周期。

## 验证结果（2026-07-17）

| 求解器 | N | 命中 | 传输率 | 平均检测时间 (us) | 最大杆区半径 (mm) |
|---|---:|---:|---:|---:|---:|
| COMSOL | 25 | 25 | 1.00 | 50.1155 | 0.5414 |
| SIMION | 25 | 25 | 1.00 | 49.7386 | 0.4729 |

传输率绝对差为 0，平均 TOF 相对差为 0.755%，两端最大杆区半径均远小于 `r0=4 mm`；跨求解器
门禁 PASS。速度映射修正前的所有 COMSOL 收敛扫描、候选 MPH、CSV、图像和报告均已删除，不能再
作为收敛证据。修正后 mesh1 的 80→160 RF 步/周期复核均为 25/25，平均 TOF 变化 0.058%、最大
杆区半径变化 0.47%，故 80 步/周期的时间积分已重新确认。空间复核显示较粗 mesh2 相对 mesh1
的平均 TOF 变化 0.98%、最大杆区半径变化 4.26%；显式更细的 `hmax=0.5 mm` 候选相对 mesh1 的
平均 TOF 变化 0.356%、最大杆区半径变化 13.4%。因此 mesh2 不可作为替代，mesh1 的渐近空间收敛
仍未闭合；不得依据与 SIMION 的接近程度选择网格。SIMION 的几何、PA 与固定粒子源未受此速度映射错误影响。

同一公共真空格点上的 COMSOL 自身场比较表明，mesh1 与显式 `hmax=0.5 mm` 的独立 FEM 单位场在
207706 个公共点的矢量相对 RMS 差为 0.446%，杆区 175959 点为 0.271%。因此 mesh1 的杆区电场已
接近更细网格；端点轨迹的更大差异应作为 RF 相位累积敏感性处理，不能直接视作场未收敛。

两端分辨率加密给出更严格的区域结论：SIMION 0.2→0.1 mm PA 的入口/杆区/出口自身场差为
3.396%/0.0467%/0.280%，COMSOL mesh1→`hmax=0.5 mm` 为 1.945%/0.271%/3.239%。细 FEM 与
0.2 mm PA 的杆区/出口差为 0.0521%/0.384%，与 0.1 mm PA 为 0.0289%/0.359%；杆区和出口随
加密闭合。入口的细网格交叉差仍为 4.466%，且两端自身都敏感，故不能把入口误差只归因于官方
0.2 mm PA。该测试只用于误差定位，不把细候选提升为生产基线。

对 SIMION PA 与 COMSOL FEM 的分量比较，杆区 `Ex/Ey/Ez` RMS 差分别为 32.58、30.19、35.43 V/m；
在杆中点 `z=45.6 mm,y=0` 的 `Ex` 横向梯度分别为 −12532.07 与 −12535.72 V/m/mm，相对差仅
0.0291%。这直接闭合了近轴四极杆聚焦梯度；现有轨迹末端差异不能归因于该局部场强度。

COMSOL MPH 重开后，`std1`/`std2` 通过 Study GUI Compute 路径复算仍为 25/25，Solver 标签保持
`sol1,sol2`。SIMION IOB 重开确认单实例、变换 `(az=-90, el=0, rt=180)`、PA 为
`39×39×477`、单元 `0.2 mm`，项目本地 Lua/Fly2 生效。

终点诊断图由 `analysis/plot_terminal_distribution.py` 生成到
`artifacts/.../results/cross_solver/transport_no_collision_terminal_distribution.png`：上排两栏使用同一
PA/COMSOL 横向坐标与颜色尺度，虚线圈表示 3.6 mm 探测器口径，圆点是探测器命中、叉号是非探测器
终止，颜色表示终止轴向位置；下排按相同粒子 ID 给出 SIMION→COMSOL 终点差矢量和逐粒子横向差。
当前两端均为 25 个命中；未来撞杆、出口壳体或超时离子会保留在同一图中。

轴向诊断由 `analysis/plot_transport_trajectory_diagnostics.py` 读取两端统一 PA/COMSOL 坐标下的逐粒子
轨迹 CSV，输出 `transport_no_collision_r_vs_z.png`、`transport_no_collision_delta_r_vs_z.png` 和
`transport_no_collision_delta_time_vs_z.png` 和 `transport_no_collision_key_plane_distributions.png`。
它们分别显示 25 条 `r(z)` 包络、同 ID 的 `|r_COMSOL-r_SIMION|`（均值/P95）、同 z 的时间差、
以及入口 0.2 mm、杆中点 45.6 mm、杆出口 85.4 mm、检测器前 94.8 mm 的并列束斑。经速度映射
斜率修正后，入口横向距离均值从 0.0166 mm 降至 `8.6e-8 mm`；当前最大均值/P95 径向差为
0.3455/0.6568 mm，终端均值距离为 0.9698 mm。COMSOL 160 步与 SIMION 80 步的独立候选给出
0.3370/0.6492 mm 和 0.9784 mm，未实质降低差异；这排除了当前时间步长作为主因。两端在同一
`e1=+100 V,e2=-100 V` 单位场、同一真空采样格点上各自独立求场后，全部 208050 点的矢量相对 RMS
差为 0.515%，杆区 175959 点为 0.266%（`unit_rf_field_comparison.json`）。该比较没有把 PA 场导入
COMSOL 或把 FEM 场导入 SIMION，证明两场在杆区已数值闭合；剩余逐粒子轨迹终点差仍需作为 RF 相位敏感
的轨迹积分问题独立收敛和解释。诊断用于定位局部求解器差异，不替代传输率、TOF 和约束门禁。

`analysis/plot_transport_phase_diagnostics.py` 进一步在相同轴向位置比较到达时间、RF 相位和同 ID 横向
距离。入口处平均时间差为 `-8.9e-9 us`、平均横向距离 `8.5e-8 mm`，确认粒子释放仍对齐；杆中点的
平均时间差为 `91.5 ns`（平均包裹相位差 `36.2°`），杆出口为 `186.9 ns`，说明两端的轴向运动会逐步
产生 RF 相位漂移。但杆区 9975 个配对样本中，绝对包裹相位差与横向距离的 Pearson 相关仅 `r=0.095`，
故不能把横向差归结为一个可调的全局 RF 相位偏移；该图仅作诊断，未改写任一求解器的场或轨迹。

## 轨迹差原因审计

| 候选原因 | 检验结果 | 判定 |
|---|---|---|
| 初始位置、速度、出生时间 | 首个公共面横向均值差 `8.5e-8 mm`、时间差 `-8.9e-9 us`；出生覆盖同一 RF 周期 | 排除 |
| RF 幅值、频率、符号、相位零点 | 两端均为 `sin(2πft)`、±139.81792 V peak、1.1 MHz；单位场符号和中点梯度一致 | 排除 |
| 入口/出口边缘场 | 基线入口/杆区/出口场差 3.46%/0.266%/3.22%；双端加密后杆区/出口降至 0.0289%/0.359%，入口仍 4.466% | 主要证据支持 |
| 时间积分步长 | COMSOL 80→160 步的 TOF/杆区半径变化 0.058%/0.47%；SIMION 40→80 为 `1.05e-6`/0.030% | 排除主因 |
| 单一全局 RF 相位偏移 | 杆区相位差与横向距离相关仅 `r=0.095` | 排除 |
| 探测面或终止插值 | 横向均值差在出口壳体前/探测器前已达 0.506/0.883 mm，比较面为 0.970 mm | 排除主因 |
| 推进器算法差异 | 两端各自时间加密均稳定；z=20 mm 杆内释放至 z=70 mm 的平均横向差仅 0.000990 mm | 排除杆内主因 |

基线横向差从入口边缘开始：均值在 `z=5.0 mm` 首次超过 0.01 mm，杆入口已为 0.0305 mm，随后在
杆内随 RF 相位漂移累积，并在出口边缘进一步放大。为隔离入口，将同一粒子源仅沿轴向平移到
`z=20 mm`，两端仍用各自独立场和推进器：首个公共面 `z=20.2 mm` 的均值差为 0.000096 mm，杆中点
0.000642 mm，`z=70 mm` 仅 0.000990 mm；至杆出口才升为 0.02764 mm，预探测器处为 0.4355 mm，
0.01 mm 阈值首次出现在 `z=84.4 mm`。这直接证明杆内场和积分高度一致，基线差主要由入口边缘注入，
而内部释放后的剩余差主要在出口边缘放大。边缘差来自两端边界离散表示，不能只归罪于 0.2 mm PA；
该定位不要求、也不允许共享求解器场。

## 后续功能的闭合判据

按用户 2026-07-17 的决定，跨求解器的同编号单粒子轨迹或落点高度重合不作为通用硬门禁；边缘场仍须
按其对目标功能的影响验证，不能因当前传输通过而永久忽略，也不得为追平另一求解器而调参或选网格。

- 无碰撞传输以传输率、TOF、杆区约束、出口束斑/角度/能量和接口接受率为主；仅当孔径、下游接受率
  或损失位置对端部敏感时，继续做边缘场局部加密与结构复核。
- 碰撞冷却采用足够样本量的统计闭合，比较传输率、冷却时间、出口能量与径向分布、停留时间和碰撞
  统计；随机碰撞后不要求逐粒子对应。
- 质量过滤必须重新验证入口捕获和出口释放的边缘场影响，以质量扫描峰位、峰宽/分辨率、透过率、
  稳定区边界及相位/初始能量敏感度闭合为准，不以探测器单粒子落点一致代替质量响应闭合。
- 多部件集成以接口相空间和下游功能接受率验收。若功能指标已收敛，单粒子落点差只作为诊断量；若
  功能指标对边缘离散仍敏感，则必须先完成相称的空间网格/PA分辨率收敛，才能提升为对应功能基线。

## 产物与边界

- COMSOL 候选：`artifacts/.../models/comsol/candidates/rf_quadrupole_transport_no_collision_simion_reference.mph`
- SIMION 候选：`artifacts/.../models/simion/candidates/quad_transport/`
- 闭合证据：`artifacts/.../results/cross_solver/transport_no_collision_closure.json` 与 paired CSV
- 轨迹诊断证据：`artifacts/.../results/cross_solver/transport_no_collision_trajectory_diagnostics.json`
  及上述三张 PNG；原始稀疏轨迹 CSV 位于 `results/comsol/` 与 `results/simion/`。
- 独立场闭合证据：`results/simion/unit_rf_field_pa_grid.csv`、
  `results/comsol/unit_rf_field_fem_grid.csv`、`results/cross_solver/unit_rf_field_comparison.json` 与中面图。
  两场只比较、不互相导入；先前 150 mm 简化直杆 MPH 已删除，历史 `test3` 碰撞模型也不能证明本结论。
- 相位--轨迹诊断证据：`results/cross_solver/transport_no_collision_phase_diagnostics.json` 与同名 PNG。
- 分辨率与内部释放证据：`results/cross_solver/unit_rf_field_resolution_convergence.json`、
  `transport_no_collision_internal_z20_diagnostics.json` 与同名 PNG；大体积加密 PA/MPH 和原始诊断 CSV
  在结论归档后按可再生临时产物清理。
- 本阶段未选定机械正式几何，因此没有触发 SolidWorks 同步；若以后提升为正式组件，必须同任务完成 CAD/装配同步。
