# 双锥串联四极杆离子传输接口项目状态

本文件是当前参数解释、物理链、资格和开放任务的唯一权威。多极杆通用理论见
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

## 当前权威物理链

当前路线由两个独立 workflow 组成：

1. COMSOL 使用 [`gas_flow_science.json`](../config/gas_flow_science.json) 与
   [`comsol_solver_numerics.json`](../config/comsol_solver_numerics.json) 建立轴对称可压缩气流筛选。
   当前模型只覆盖无杆、无偏置泵口的空包络轴对称近似；它的声明边界是
   `prototype_axisymmetric_empty_enclosure_gas_flow`。
2. SIMION 几何编译器从同一 resolved 几何生成电极表示；Fly runner 只消费由成功 COMSOL run 导出、复制进本次 run 且
   通过 SHA-256 和 frame/单位检查的 canonical `r-z` 气体场。气体场至少包含压力、温度、径向与轴向
   气速以及有效域和插值边界语义。

COMSOL 气流成功只证明上游场计算完成，不证明离子传输。SIMION 消费 COMSOL 场意味着两者是依赖链，
不得表述为跨求解器轨迹等价。若未来需要独立闭合，必须另建 COMSOL charged-particle workflow，并使
两个轨迹求解器分别消费同一冻结气体场、源、电极和事件合同。

当前已有项目级 COMSOL 场编译入口和复用同一核心的真实 SIMION Fly 入口；execution profile 仍只登记
计划和静态门禁。只有 COMSOL 最终 `400 Pa`、合同明确记录的终态稳定化参数解通过独立场校验，并由下游运行冻结全部
来源哈希后，才可形成 Prototype 证据；任意中间 continuation 解或裸 CSV 都不是可执行证据入口。

## 已退役模型

项目建立时的 `pressure_drag_screening_v1` 使用规定压力、规定气速、低场迁移率阻尼和理想近轴 RF 场。
它已退出活动 mode 和 execution profile，相关 Python 积分器不再属于生产主链。其两次历史 run、原
声明边界和可恢复源码身份冻结在
[`20260908__superseded-python-pressure-drag-screening.md`](history/20260908__superseded-python-pressure-drag-screening.md)。
旧 run 继续按原 manifest 保留，但不得作为 COMSOL 气体场或 SIMION 轨迹资格输入。

## 当前资格

| 层级 | 状态 |
|---|---|
| 几何与合同 Static | 可执行 |
| COMSOL 轴对称空包络气流 | Prototype；`20260910_z120_empty_cfd_comsol` 已到 `400 Pa` 并通过 `0.848%` 质量守恒门禁 |
| canonical COMSOL→SIMION 气体场 | Prototype run 内已校验并编译为带源合同哈希的 manifest；尚未登记全局 current artifact |
| SIMION 几何编译 | Prototype；本机 `gem2pa/refine` 已通过 |
| SIMION 气体辅助轨迹 | Prototype；`20260910_z120_empty_cfd_simion_n100` 使用 COMSOL 场和官方 SDS 完成 N=100，80 个到达 `z=119.75 mm` |
| 独立轨迹跨求解器闭合 | 未建立 |
| CAD / GUI / Candidate / Formal | BLOCKED |

已完成的气流失败链、质量守恒与粒子统计保存在
[原型记录](history/20260911__empty-enclosure-gas-transport-prototype.md)。

## 开放任务

1. 确认两个锥角定义、朝向、实体孔口面、厚度、外径、孔筒和 `3 mm` 的机械测量对象。
2. 确认椭圆杆有效长度、中心坐标、轴向方向、`7.48 mm` 的杆对定义，以及 `1.6 mm` 是轴向还是法向净距。
3. 确认 `5.64 mm` 是相邻还是对置中心距、两组杆是否同轴，以及 `2 mm` 间是否存在 IQ0/孔板/绝缘板。
4. 对已通过的空包络 CFD 做网格/稳定化敏感性复核；孔板仍从 CFD 排除，除非后续科学问题明确要求板前积压、孔内射流或板后膨胀。
5. 决定是否把本次合格 COMSOL 场发布为全局 current artifact；均匀 `400 Pa` 对照不能代替此场。
6. 给出各锥、壳体、两段杆及出口件的 DC、两段 RF 频率/幅值口径/相位，以及目标离子、源分布、迁移率
   或 CCS；快速原型 Fly runner 已可执行，这些参数确认后再替换当前暂定值。
7. 补充气体场依赖、RF/DC 参数、SIMION GUI 可检查性和损失事件复核；通过后再开放 Candidate。
8. 建立端部、绝缘、支撑、馈通和泵口机械细节，并完成 COMSOL GUI、SIMION GUI 与 SolidWorks 同步后
   才开放 Formal。

## 产物边界

活动产物位于 `artifacts/projects/dual_cone_tandem_quadrupole_ion_interface/`。COMSOL 气流和 SIMION
轨迹各自使用独立 run 三件套；下游 SIMION run 冻结上游 manifest 和气体场副本。旧 Python run 只读
保留，不因主链退役而删除或改写。
