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
- 两段四极导引器均采用反相正弦 RF；用户确认每组杆对地峰值 `300 V`，即对置杆组间
  `600 V` 峰值、`1200 Vpp`。用户给出的工作频率范围为 `550–590 kHz`，当前标称计算点取中值
  `570 kHz`；两个频率端点尚未扫描。
- 当前 N=100 原型源在第一锥上游、中心 `z=-1 mm`、长 `1.5 mm` 的圆柱体积内均匀取样；用户指定
  源半径为 `1.5 mm`。它大于第一锥 `1 mm` 孔半径但小于 `5 mm` 上游储气腔半径，超出孔径的离子
  不在源生成阶段预先剔除；后续由 SIMION 实体几何或 COMSOL 流体支持边界代理判定损失。

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

当前已有项目级 COMSOL 求解、场编译和复用同一核心的真实 SIMION Fly 入口；execution profile 已登记
COMSOL 空包络气流与 COMSOL 场驱动 SIMION 的计划级受管 runner。均匀 `400 Pa` runner 仅作为显式
对照入口保留，不是登记的主物理链。只有 COMSOL 最终 `400 Pa`、合同明确记录的终态参数解通过独立场校验，并由下游运行冻结全部
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
| COMSOL 轴对称空包络气流 | 受管 run `20260914_154800__sim__comsol__dual-cone-gas-flow` success，bootstrap、项目报告、独立字段验证及full manifest均PASS；仍仅为无杆、无孔板、无泵口的Prototype |
| canonical COMSOL→SIMION 气体场 | 上述成功run已由下游按full manifest、字段SHA-256和冻结三份源合同消费；未提升为Candidate/Formal资产 |
| SIMION 几何编译 | Prototype；本机 `gem2pa/refine` 已通过 |
| SIMION 气体辅助轨迹 | COMSOL场受管run `20260914_162400__sim__simion__dual-cone-comsol-field-n100` success且full manifest PASS，N=100中58个到达末端；均匀400 Pa控制run为0/100，但不是自然压降模型 |
| 独立轨迹跨求解器闭合 | 未建立 |
| CAD / GUI / Candidate / Formal | BLOCKED |

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
4. 对已通过的空包络 CFD 做网格/稳定化敏感性复核；孔板仍从 CFD 排除，除非后续科学问题明确要求板前积压、孔内射流或板后膨胀。
5. 对当前受管COMSOL场做网格/稳定化敏感性复核后，再决定是否发布为全局current artifact；均匀`400 Pa`对照不能代替此场。
6. 给出各锥、壳体和出口件的 DC，以及目标离子、源分布、迁移率或 CCS；两段 RF 的幅值口径与频率
   范围已经确认，但仍需决定是否扫描 `550 kHz` 和 `590 kHz` 端点。
7. 补充气体场依赖、RF/DC 参数、SIMION GUI 可检查性和损失事件复核；通过后再开放 Candidate。
8. 建立端部、绝缘、支撑、馈通和泵口机械细节，并完成 COMSOL GUI、SIMION GUI 与 SolidWorks 同步后
   才开放 Formal。

## 产物边界

活动产物位于 `artifacts/projects/dual_cone_tandem_quadrupole_ion_interface/`。COMSOL 气流和 SIMION
轨迹各自使用独立 run 三件套；下游 SIMION run 冻结上游 manifest 和气体场副本。旧 Python run 只读
保留，不因主链退役而删除或改写。
