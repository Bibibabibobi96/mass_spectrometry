# 双锥串联四极杆离子传输接口项目状态

本文件是当前参数解释、模型边界、资格和开放任务的唯一权威。多极杆通用理论见
[`docs/multipoles/index.md`](../../../docs/multipoles/index.md)，碰撞模型分级见
[`docs/multipoles/collisions.md`](../../../docs/multipoles/collisions.md)。

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

这些解释只用于生成一致坐标和发现冲突，不等于机械尺寸已确认。

## 首版物理模型

当前入口为 `pressure_drag_screening_v1`：

- 只追踪已脱溶剂化的单价正离子，不模拟 Taylor cone、液滴蒸发或离子化过程。
- 气体为 `N2, 300 K`；压力在第一孔前为 `101325 Pa`，两孔之间的末值取两端压力的几何平均，第二孔
  后再以对数线性方式降到 `400 Pa`。气流速度使用显式暂定轴向锚点。
- 阻尼由低场约化迁移率 `K0` 和 `K = K0(p0/p)(T/T0)` 给出；积分采用隐式阻尼的确定性牛顿方程。
  不计算布朗扩散或离散碰撞，输出的 drag exposure integral 不是实际碰撞数。
- 两段杆区使用公共 RF 电压约定和理想近轴四极场；真实椭圆/圆杆边缘场只通过硬几何碰撞近似。
- 锥体只实施孔口穿越判据；没有厚度、圆角和外径前，不虚构完整实体碰撞面。
- 忽略空间电荷、离子化学、非弹性碰撞、壁面反弹、磁场以及真实泵口。

该模型低于高压接口定量结论所需的 C4（可压缩流 + 三维场 + 经验证碰撞/迁移率 + 必要耦合）证据，
只允许用于坐标、孔径、杆碰撞、RF 聚焦趋势和代码链路筛选。任何传输率或出口能量都不得标成实机预测。

暂定工况集中在 [`science.json`](../config/science.json)：`500 Da, z=+1`、`K0=1.5 cm²/(V·s)`、
两段 `1 MHz / 100 V zero-to-peak per group`、轴向 `100 V/m`。这些数值不是用户确认的 baseline。

## 当前资格

| 层级 | 状态 |
|---|---|
| 几何与合同 Static | 可执行 |
| 低阶 N=100 筛选 | Prototype；不授予 Candidate |
| 可压缩气流、真实三维边缘场与碰撞 | 未建立 |
| COMSOL / SIMION | 未建立 |
| CAD / GUI / Formal | BLOCKED |

## 开放任务

1. 确认两个锥角定义、朝向、实体孔口面、厚度、外径、孔筒和 `3 mm` 的机械测量对象。
2. 确认椭圆杆有效长度、中心坐标、轴向方向、`7.48 mm` 的杆对定义，以及 `1.6 mm` 是轴向还是法向净距。
3. 确认 `5.64 mm` 是相邻还是对置中心距、两组杆是否同轴，以及 `2 mm` 间是否存在 IQ0/孔板/绝缘板。
4. 给出各锥、壳体、两段杆及出口件的 DC；两段 RF 的频率、幅值口径、相位和第二段是否带质量选择 DC。
5. 给出中间级和两杆区压力测点、气体组成与温度、泵口几何/有效抽速；随后建立轴对称可压缩流筛选和
   含杆/泵口的三维 CFD 资格路线。
6. 给出目标离子 `m/z`、电荷、极性、N2 迁移率或 CCS、源空间/速度分布和离子流；再决定迁移率模型、
   能量相关 Monte Carlo 碰撞与空间电荷等级。
7. 从同一 resolved 几何建立 COMSOL/SIMION/CAD；完成网格、时间步、随机种子、GUI/CAD 和跨求解器门禁
   后，才讨论 Candidate 或 Formal。
