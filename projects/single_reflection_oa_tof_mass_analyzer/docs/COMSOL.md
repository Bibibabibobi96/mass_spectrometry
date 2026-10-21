# 单次反射正交加速飞行时间质量分析器：COMSOL实施与验证

本文只记录COMSOL入口、模型树和独立验收。当前项目资格、跨求解器结论与开放任务只见
[`PROJECT.md`](PROJECT.md)；2026-07-28以前的实现时间线和诊断数值冻结在
[`history/20260728__pre-document-consolidation-comsol.md`](history/20260728__pre-document-consolidation-comsol.md)。

## 活动入口

- 具名生产入口：`../comsol/run_oatof_model.m`
- 模型树内部实现：`../comsol/oatof_build_model_core.m`，不作为位置参数公开入口
- MATLAB单元：`../tests/comsol/test_support/run_oatof_matlab_unit_tests.m`
- Formal写入合同：`../tests/comsol/test_support/run_oatof_formal_write_contract_tests.m`
- N=100候选功能：`../tests/comsol/run_n100_candidate_functional.ps1`
- 几何同步：`../workflows/formal_reference/verify_geometry_contract.ps1`

版本与启动采用[仓库操作指南](../../../docs/OPERATIONS.md)，连接复用、重试和失败分类见
[公共 COMSOL 入口](../../../common/comsol/README.md)。项目任务不自行
`mphstart`。普通构建不得写Formal路径；只有获批promotion事务中角色与目标精确匹配时才允许。

## 模型与合同

生产入口只消费`../config/resolved_geometry.json`或上层显式冻结的Candidate resolved；
`../config/formal_solver_numerics.json`是网格、分段时间输出和solver设置的唯一权威。Candidate
`ContractPath`必须贯穿顶层入口、底层构建器和时间窗口，不能由理论默认值覆盖。

模型树按加速器、反射器、检测器、漂移区、栅网、网格、粒子物理和结果节点分责。影响结果的参数、
选择集、材料、网格、物理、Study/Solver、数据集和图必须持久化到MPH并可由Desktop查看与Compute。

## 当前实现边界

- 当前批准几何为闭合加速器屏蔽，没有RF注入侧孔；`interfacePort`只用于隔离候选，不属于Formal。
- 正式数值合同以加速器`hmax=1 mm`为日常值、`0.5 mm`为收敛参考；反射器无需无目标全域加密。
- 分段时间输出必须以全局细时间格对齐；求解器只存合同规定的窗口与状态。
- `solver_steps` 与 `times_to_store` 从 resolved 数值合同消费。构造和重追踪共用
  `oatof_cpt_solver_policy`，按活动 GA/BDF/DP5 选择对应步策略键并回读；同步核验走同一边界的只读模式。
  项目当前只支持 `times_to_store=tlist`，不继承未声明的内部步抽样设置。存量 MPH 的旧设置须独立核验，
  源码修复本身不更新其资产身份或资格。
- 固定粒子释放按mm读取，逐粒子到达事件统一由项目提取器处理。COMSOL/MATLAB只导出带终态分类的原始事件CSV及Python分析请求；FWHM、R、均值/标准差、KDE、bootstrap和源映射拟合只由`analysis/analyze_comsol_detector_events.py`经`reference_analysis`发布。
- 检测器提取区分三维静止尾段和近面运动：空间容差仅判断平台是否靠近检测面，静止判断只容许浮点表示余量。
  零及微小正负冻结平台从平台前下降段回推；无有效接近段，或外推早于所用接近段终点、晚于首个确认平台点时不给有效到达。
  冻结附近查询坐标可能仍有插值过渡，最后变化查询点不能作为真实到达时间的下界；这种回推仍须通过独立数值收敛门槛。
  真正穿越须有局部正负侧证据；全零静止、触面后返回和跨缺口数据不冒充到达。输出保留所用原始采样行号供复核。
  既有重追迹诊断可在求解前启用状态存储并读取 `cpt.st`；当前默认关闭，事后开启不能恢复未存状态。
  [官方状态与边界定义](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_math.06.02.html)
  及 [Freeze 语义](https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_math.06.38.html)
  说明停止时间与冻结后保留的撞壁速度；不能用非零速度否定冻结，也不能把数值停止时间直接当作精确真值。
  已测常速平面小模型中，DP5 的稀疏输出可使 `mphparticle` 回读的冻结位置留在面前，即使原生停止时间准确。
  此时提取器拒绝事件是有效的失败关闭，不能扩大空间容差或把查询平台点当作精确碰壁位置；
  原生停止时间仍须结合目标边界身份和独立收敛验证，不能直接替换整机检测器判定。
- 可组合理想场替换只用于原因隔离，不形成Formal性能声明。

## GUI与验收

适用的候选或Formal模型必须：

1. 保存后由COMSOL Desktop重开；
2. 核对resolved参数、几何、选择集、网格及GUI可见物理节点；
3. 核对`std1/std2`与`sol1/sol2`附着，禁止GUI Compute生成新solver显示旧解；
4. 由Study Compute等价复算静电和粒子研究；
5. 复核固定粒子表、唯一terminal事件分类、输出列和manifest；terminal是事件终态，不是探测面别名；
6. 几何改变时同步SolidWorks，并由PROJECT更新资格。

当前 MPH 身份、验证结果与 GUI evidence 只查 [PROJECT](PROJECT.md) 和
[`formal_validation.json`](../config/formal_validation.json)；当前源码路径不自动重验历史资产。

## 兼容限制

COMSOL 6.4的极小粒子数不稳定由同源N=100承载前缀绕行；除PROJECT列出的重启条件外不再扫描。
已关闭的场替换扫掠、局部网格、分段时间性能、极小N调查和生产入口故障链全部从同日history快照
及来源manifest追溯。
