# oa-TOF COMSOL实施与验证

本文只记录COMSOL入口、模型树和独立验收。当前项目资格、跨求解器结论与开放任务只见
[`PROJECT.md`](PROJECT.md)；2026-07-28以前的实现时间线和诊断数值冻结在
[`history/20260728__pre-document-consolidation-comsol.md`](history/20260728__pre-document-consolidation-comsol.md)。

## 活动入口

- 具名生产入口：`../comsol/run_oatof_model.m`
- 模型树构建器：`../comsol/ms_oaTOF_two_stage_ringstack_reflectron.m`
- MATLAB单元：`../tests/comsol/run_oatof_matlab_unit_tests.m`
- Formal写入合同：`../tests/comsol/run_oatof_formal_write_contract_tests.m`
- N=100候选功能：`../tests/comsol/run_n100_candidate_functional.ps1`
- 几何同步：`../workflows/formal_reference/verify_geometry_contract.ps1`

版本、启动、连接复用、重试和失败分类只采用根README与`common/comsol/README.md`。项目任务不自行
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
- 固定粒子释放按mm读取，逐粒子到达事件统一由项目提取器处理；MATLAB不重复FWHM或bootstrap分析。
- 可组合理想场替换只用于原因隔离，不形成Formal性能声明。

## GUI与验收

适用的候选或Formal模型必须：

1. 保存后由COMSOL Desktop重开；
2. 核对resolved参数、几何、选择集、网格及GUI可见物理节点；
3. 核对`std1/std2`与`sol1/sol2`附着，禁止GUI Compute生成新solver显示旧解；
4. 由Study Compute等价复算静电和粒子研究；
5. 复核固定粒子表、唯一terminal事件分类、输出列和manifest；terminal是事件终态，不是探测面别名；
6. 几何改变时同步SolidWorks，并由PROJECT更新资格。

当前项目处于`formal_revalidation_pending`。旧Formal MPH和2026-07-20结果可追溯，但不能替代当前拆层
合同下的vNext重验证。

## 兼容限制

COMSOL 6.4的极小粒子数不稳定由同源N=100承载前缀绕行；除PROJECT列出的重启条件外不再扫描。
已关闭的场替换扫掠、局部网格、分段时间性能、极小N调查和生产入口故障链全部从同日history快照
及来源manifest追溯。
