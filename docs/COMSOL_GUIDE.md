# COMSOL 路线、精度与成本选择指南

本页按实际任务导航已有实现和证据，不定义第二套参数、项目资格或验收阈值。项目当前状态只认各
PROJECT，数值只认其具名合同；下表中的历史案例只证明其冻结范围。先判断路线，再分配功能预算，
最后比较达到同一精度的完整成本。

## 先选实际计算路线

| 对象 | 在仓库中如何使用 COMSOL | 应进入的实现与状态入口 | 不可直接套用的经验 |
|---|---|---|---|
| 单反射 OA-TOF | 静电 FEM、保存场、原生 CPT、检测事件导出，再由 Python 分析 | [项目入口](../projects/single_reflection_oa_tof_mass_analyzer/README.md)、[当前边界](../projects/single_reflection_oa_tof_mass_analyzer/docs/PROJECT.md#已知兼容边界) | 同一 FEM 上的时间参考一致性不能授予电场网格收敛；诊断 DP5 配置不自动成为 Formal |
| MR-TOF | 完整装配独立静电 FEM，导出标量电势为规则 PA，再由 SIMION 求导、插值和追踪 | [项目入口](../projects/parallel_mirror_dual_stripe_mr_tof/README.md)、[电场表示](../projects/parallel_mirror_dual_stripe_mr_tof/docs/PROJECT.md#电场表示与数值资格) | 此路线的场求解、转换或返回失败不能归因于 COMSOL 原生 CPT |
| RF 四／六／八极杆 | 有限三维场与原生粒子传输；不同科学 workflow 分别与独立 SIMION 比较 | [公共入口](../common/multipole/README.md)、[四极](../projects/rf_quadrupole_ion_optics/README.md)、[六极](../projects/rf_hexapole_ion_optics/README.md)、[八极](../projects/rf_octupole_ion_optics/README.md) | 功能传输、连续相空间等价、质量过滤及下游 TOF 资格不能互相替代 |
| Ion Processor | 当前生产为 SIMION 场、动态 RF/DC/脉冲及 HS1 碰撞；COMSOL 对照尚未建立 | [项目入口](../projects/dual_pressure_rectilinear_ion_processor/README.md)、[当前范围](../projects/dual_pressure_rectilinear_ion_processor/docs/PROJECT.md) | 不能将 OA 的无碰撞时间门或原生 CPT 配置当成已验证的 IP 方法 |

表中只列本轮重点项目。其他器件从[项目导航](../README.md#项目导航)进入，不根据文件名或软件目录
存在推断物理能力。共享最小测试也不是某一仪器的独立模型资格。

## 把功能要求变成配置选择

精度有四个不同层次：目标功能、可观测量的允许误差、实际数值设置、验证结果。能够自动计算的是
给定假设下的误差分配；`rtol`、最大内部步长和局部网格仍须通过受控比较选择。通用方法只引用
[验证方法](VALIDATION_METHODS.md#网格时间步与误差预算)和[TOF 查表与计算](TOF_ERROR_BUDGET.md)。

| 使用情形 | 先找到什么要求 | 比较什么结果 | 本仓库实例与缺口 |
|---|---|---|---|
| TOF 分辨率／质量偏差 | 有效 T、参考峰与其来源、最低 R、外标质量偏差限、未计入展宽 | 同一粒子事件集合、直接 FWHM、峰形、共同漂移、逐粒子差及参考重复差 | OA 已有 N100 时间参考和重复；仍需功能预算。[OA 选型实例](../projects/single_reflection_oa_tof_mass_analyzer/docs/COMSOL.md#精度与数值配置的使用顺序)区分规划和验收 |
| MR 长程返回 | 正确返回分支、目标圈数、孔径裕量及束团接受度，再分配计时预算 | 全程事件身份、损失位置、共同与相对时间、实际检测峰 | [MR 状态](../projects/parallel_mirror_dual_stripe_mr_tof/docs/PROJECT.md#电场表示与数值资格)中的约 0.2 ns 为总体初始工程预算，不是场、导出或积分单项误差界 |
| RF 部件出口传输／相空间 | 具名下游孔径、观察面、允许半径／发散／能量／相位及最小有效改善 | handoff 共同 ID、全部损失、连续位置／速度／能量及其传播后影响 | [六极接受合同](../projects/rf_hexapole_ion_optics/config/qualification/dispersion_acceptance.json)明确缺少物理／下游预算；不得从功能 PASS 推出连续量合格 |
| IP 储存、冷却与脉冲引出 | 捕获／引出事件、能量和接受度、气体／碰撞模型及统计要求 | 传输、束斑、发射度、尾部、碰撞与电场作用；保持全部粒子 | [IP 当前边界](../projects/dual_pressure_rectilinear_ion_processor/docs/PROJECT.md)尚无 COMSOL 对照，不能填写已验证的 COMSOL 数值档 |

实际选档记录应能回答：哪一项需求产生阈值、哪一份源／场／几何被固定、哪一个数值因素被改变、
参考自身是否稳定、指标是否达标、成本是否在预算内。缺少需求时可以发布差异与成本，不能输出
“自动推荐合格配置”。机器参数继续写在原有项目配置，不在本页建立另一套默认值。

## 先定位慢在哪一阶段

“COMSOL 比 SIMION 慢”必须绑定同一物理、精度、源、终止条件及统计目标。下列案例来自不同
工作流，不能按秒数互相排序，也不能据此推导两软件固有速度比。

| 阶段 | 已有案例支持什么 | 首个决策 |
|---|---|---|
| 几何／选择／释放构造 | [RF 四极释放记录](../projects/rf_quadrupole_ion_optics/docs/history/20260911__solver-sensitivity-and-retired-interface.md)的 N1000 预算中断发生在 release 构造，尚未开始粒子 Study；单节点向量化也未通过等价门 | 查已建节点数、源与物种／相位映射；不能靠改积分器解决构造阶段成本 |
| 建网／装配／静电求解 | RF 加速空间档曾触资源帽；[MR 场案例](../projects/parallel_mirror_dual_stripe_mr_tof/docs/PROJECT.md#电场表示与数值资格)是大型独立 FEM 成本 | 先查失败阶段、实际网格／阶次／DOF 和资源记录；预算受限不是物理 FAIL，不自动重跑更细全局网格 |
| 原生粒子求解 | [OA 完整流程](../projects/single_reflection_oa_tof_mass_analyzer/docs/history/20261021__oatof-cpt-fixed-policy-reference-and-full-flow.md)中 std2 占本次完整流程约九成，原生日志还能定位积分活动的时间区间 | 应继续隔离力、场评价、拒步或事件成本；这些计数尚不能证明某一内部机制是主要耗时根因 |
| 数据读取／指标／输出 | 同一 OA 案例的合并读取减少 API 成本，但整体收益远小于局部读取比值 | 保持字段、采样及事件不变；报告完整流程，不能把 API 比值称为生产总加速比 |
| 排队／启动／恢复／封存 | OA 某些参考运行包含资源排队或容量恢复，与普通成功臂计时口径不同 | 先统一起止点、资源干扰与是否重算，再决定能否进入性能排序 |

该 OA 配对的冻结观测为：主链 API 59.4113→21.5030 s，完整流程 1780.9614→1730.6505 s；
全流程进程族采样峰值 5.4782→5.2370 GiB。两臂均通过原参考门；本次整体缩短约 2.82%，
但求解自身也波动，只有一对运行，不能宣称稳定整体收益。内存为每个受管进程
`max(working_set, private)` 求和的采样峰值，含包装／观察进程，不是连续峰值或唯一物理页。
原数据、精确口径、失败候选和复现步骤统一查上述完成记录，本页不另维护计时合同。

## 事件、接口和故障证据从哪里查

- 原生粒子事件：先查[OA 实施说明](../projects/single_reflection_oa_tof_mass_analyzer/docs/COMSOL.md)，
  区分输出时刻、保存的解时刻、原生停止状态和目标检测事件。Freeze 后保留的速度不能单独否定冻结。
  [五案小模型](../projects/single_reflection_oa_tof_mass_analyzer/docs/history/20261022__native-event-readback-and-counter-validation.md)
  已闭合本例的 StoreExtra 查询作用与 Counter 输出敏感性；明确保留稀疏 Counter 漏计，不能直接推广整机。
- 关键 API 与验证成熟度：查[API 参考](COMSOL_API.md)和[共享测试](../common/comsol/README.md)。
  官方语义、属性可设置、真实 Compute、保存重开、GUI Compute、仪器功能是不同证据层。
- 已知失败的第一检查动作：查[案例定位](COMSOL_DEBUGGING.md#仓库案例定位)，再进入对应项目证据。
- 旧调研与失败日志按归档日期理解；当前配置／资格仍从项目入口读取，不能执行已删除的历史 scratch 路径。

## 哪些结论仍需要新证据

| 问题 | 可以怎样推进 | 当前不能宣布的结论 |
|---|---|---|
| 其他物理／壁面下的原生事件读取 | 复用已验证查询思路，另验目标边界身份、重复穿越及输出敏感性 | 本次平面小模型通过就保证曲面、多壁面、脉冲、碰撞或任意读取路径准确 |
| 替代 release 是否保留身份、物种、逐粒子时刻／相位 | 最小源语义对照，再与既有 RF 状态门比较；旧负结果保留 | 向量化释放已经等价或更快 |
| 内部拒步／场评价是否为 OA 主要根因 | 固定精度与场的分段受控诊断；需把计数与实际耗时对应 | 九成在 std2 就等于九成在 FEM 点定位 |
| 线程、GPU、装配模式是否减少仪器总成本 | 先核对当前版本支持及小模型语义，再按真实目标模型预登记匹配重复 | 小模型接口通过就代表大型模型更快、内存更低 |
| 哪一档网格／积分配置满足生产要求 | 绑定项目功能预算，完成各自空间／时间收敛、目标样本与适用 GUI 验收 | 1 ps 参考通过就意味着电场和整机绝对误差小于 1 ps |

这里没有默认授权大型求解。小模型验证能够关闭接口语义问题；真实三维长程场误差、碰撞统计、
目标样本扩展和稳定整体性能收益仍需对应项目的独立证据。
