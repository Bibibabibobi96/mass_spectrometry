# RF四极杆离子光学：COMSOL实施与验证

本文只说明COMSOL模型入口、模型树边界、当前数值限制和GUI验收。跨求解器状态与开放任务只见
[`PROJECT.md`](PROJECT.md)；2026-07-28以前的完整诊断过程冻结在
[`history/20260728__pre-document-consolidation-comsol.md`](history/20260728__pre-document-consolidation-comsol.md)。
多极杆各轴向实体与事件面只采用
[`../../../common/multipole/README.md`](../../../common/multipole/README.md)的统一术语。

## 活动入口

| 科学问题 | 入口 |
|---|---|
| 接口就绪输运 | `../workflows/interface_readiness/run_comsol.ps1` |
| 无碰撞部件回归 | `../workflows/no_collision_transport/run_comsol.ps1` |
| RF+DC质量过滤 | `../workflows/mass_filter_reference/run_comsol.ps1` |
| release构造诊断 | `../comsol/interface_readiness/run_release_construction_gate.m` |
| 四、六、八极杆同源功能闭合 | [`integration/workflows/family_source_closure/execute.ps1`](../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/workflows/family_source_closure/execute.ps1) |

所有任务通过仓库统一R2025b/COMSOL入口建立连接，不自行`mphstart`。版本、启动、重试及
`EXECUTION_ENVIRONMENT_BLOCKED`分类只采用根README和`common/comsol/README.md`。
integration入口内部顺序调用COMSOL/SIMION stage；内部stage不是可独立运行或取得资格的公开入口。

## 模型与合同

接口就绪、质量过滤和旧同求解器比较只消费具名profile冻结的resolved、科学mode、粒子bundle和
`../config/comsol_solver_numerics.json`。普通接口profile固定使用`baseline`数值身份；
`time_refined_160`只允许预注册的same-solver实验。MATLAB不选择profile，也不从环境或源码回退
物理/数值默认值。

公共多极杆L3传输的三种typed电气模式及其N=100数值三档只由`../config/runtime_profiles.json`绑定
`../config/multipole_transport_comsol_solver_numerics.json`。它不属于上述专用workflow，专用workflow
也不得读取该合同；两种作用域都不允许wrapper暴露自由design/numerics profile。

共享求解实现`../comsol/solve_deterministic_rf_quadrupole_particles.m`只负责几何、场、求解器release节点、轨迹
和状态导出，不按workflow名称选择科学问题。接口准备任务负责验证RF-only、无碰撞、无静态端场；
质量过滤任务显式建立差分RF/DC与静态公共偏置；轴向加速走公共multipole模型入口。

标准输出为canonical逐粒子事件表、稀疏轨迹、原始 solver metadata、Python 生成的 solver summary 及
run 三件套。MPH 是否终态保留由运行前冻结的[保留合同](../../../docs/LIFECYCLE.md)决定。
MATLAB/COMSOL 只导出原始状态、事件和求解器元数据；传输率、出口 RMS、输出能量均值/标准差
及其他发布的聚合统计均由Python从canonical状态生成。求解器专属终点表不是新运行的稳定接口。

## 数值与物理边界

- 网格、RF 步数与最长时间来自具名数值合同；生产入口不接受标量覆盖。
- 当前模型无碰撞。轴向加速由公共多极杆模型消费冻结电势合同。
- 生产粒子释放仍采用逐粒子 `ReleaseFromDataFile`；隔离向量化试验未证明等价，不能作为生产入口。
- 已完成的空间／时间敏感性、资源中断和 release 诊断见
  [历史记录](history/20260911__solver-sensitivity-and-retired-interface.md)；当前资格见 [PROJECT](PROJECT.md)。
- oa-TOF 连接归 integration；本软件文档不维护下游场、运行阶段或整机资格。

## GUI验收

适用的COMSOL候选必须：

1. 保存MPH后由Desktop重开；
2. 核对几何、选择集、网格、物理、Study/Solver、数据集与结果节点；
3. 核对`std1/std2`和`sol1/sol2`附着关系；
4. 由GUI `Study → Compute`等价重算；
5. 按冻结粒子表复核`ReleaseFromDataFile`节点、源释放面、出口孔穿越面、规范交接面、
   近接口统计面、输出列与manifest；
6. 不用旧解、残留报告或第二次启动覆盖首次失败。

release构造Gate只验证完整N=100输入下100个GUI可见`ReleaseFromDataFile`节点、文件与breadcrumb
闭包；这里的release是COMSOL求解器节点，不是粒子源合同或带孔接口板。Gate不运行
粒子Study，也不能产生传输或资格结论。历史`rel065`调查、Unicode报告修复和runner收尾过程只从
同日history快照追溯。

## 当前限制

连续量接受尺度、资源受限的加速模式以及机械交付仍有限制，具体状态与关闭条件统一见
[PROJECT](PROJECT.md#资格边界)。软件入口可执行不等于 Candidate 或 Formal 验收通过。
