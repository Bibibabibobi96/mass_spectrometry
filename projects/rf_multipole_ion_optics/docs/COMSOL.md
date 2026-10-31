# RF多极杆离子光学：COMSOL实施与验证

本页覆盖统一多极杆项目的COMSOL入口，并区分四极杆专属workflow与四／六／八极共同typed模式。
三变体共用的设计、输入冻结与投影机制见[实现与运行合同](IMPLEMENTATION.md#求解器投影)；
下表中的无碰撞传输支持三变体；接口就绪和质量过滤保留四极杆范围，不由家族名称扩大资格。
本文只说明COMSOL模型入口、模型树边界、当前数值限制和GUI验收。跨求解器状态与开放任务只见
[`PROJECT.md`](PROJECT.md)；2026-07-28以前的完整诊断过程冻结在
[`retired_projects/rf_quadrupole_ion_optics/docs/history/20260728__pre-document-consolidation-comsol.md`](history/retired_projects/rf_quadrupole_ion_optics/docs/history/20260728__pre-document-consolidation-comsol.md)。
多极杆各轴向实体与事件面只采用
[实现与运行合同](IMPLEMENTATION.md)的统一术语。

## finite 原 CLI 的收尾恢复

finite 科学配置写入保留 `New-RunPackage` 已建立的容量生命周期元数据；不从当前策略补造或覆盖原包授权。
`test_comsol_owner_finalization` 在真实配置写入后验证成功和失败收尾，避免只测试完整公共包而漏掉项目重写边界。

新 finite run 在原生启动前调用公共 PowerShell owner，冻结 execution request、实际 capacity session，
并将小 Result 保存在 run 外。正常成功、源／求场／分析失败统一交给该 owner 处理 retention、manifest、容量和执行别名。
COMSOL launcher 的 CompletionPath 提供原生 PID／起始时间／退出和真实 host release；
仅有 resource_usage 的 known 状态不能代替这些事实。未知 writer／release 保留原保护，不发布成功。

沿同一正常无碰撞入口只恢复收尾，不要求 profile、campaign 或源输入：

```powershell
./projects/rf_multipole_ion_optics/workflows/no_collision_transport/run_comsol.ps1 `
  -ResumeFinalization -RunId <original-run-id> [-ResultPath <original-result.json>] `
  [-ArtifactRootPath <artifact-root>] [-PythonExe <python.exe>]
```

ArtifactRootPath 是公共 artifact 根，不是项目目录；默认 Result 沿该根的项目 scratch/workflow_results 定位。
恢复只读取原 request／session／completion，零原生启动，不重新解析科学配置或改写输入。
已完成收尾的原科学失败继续返回失败；收尾完成不等于科学通过。缺少这些事前冻结事实的历史 run 不自动收养，
不得凭当前默认值补造 request、receipt 或小 Result，也不手工重建已删除的 alias。

### 已解数据重分析与冷提取

同一无碰撞 CLI 创建新的分析 run，预算采用已有工程合同，科学定义来自父 run 的冻结证据：

```powershell
./projects/rf_multipole_ion_optics/workflows/no_collision_transport/run_comsol.ps1 `
  -AnalyzeOnly [-ReextractFromModel] -ParentManifestPath <parent/run_manifest.json> `
  -EngineeringBudgetPath <new-analysis-budget.json> -RunId <new-run-id> `
  -RetentionClass solver_review -RetentionReason <reason> -PythonExe <python.exe>
```

省略 ReextractFromModel 只读原 CSV，不调用商业工具；显式指定时才加载原 MPH，调用正常求解后使用的同一分窗导出实现。
原两组解、保存事实及完整 release 映射必须充分绑定；缺映射不猜测粒子顺序，未知 writer 不启动恢复。
冷提取不调用求解、不保存父 MPH、不复制或重新哈希原模型；实际进程、预算、路径准备与收尾沿公共 owner。
提取后的新 CSV 可再次 AnalyzeOnly，后续分析失败不必重新加载模型；发布未完成则使用原 Result 的 ResumeFinalization。
支持格式、实测时耗及科学限制见[项目状态](PROJECT.md#当前结论)，其他 COMSOL workflow 不自动继承该能力。

## 活动入口

| 科学问题 | 入口 |
|---|---|
| 接口就绪输运 | `../workflows/interface_readiness/run_comsol.ps1` |
| 四／六／八极无碰撞传输 | `../workflows/no_collision_transport/run_comsol.ps1` |
| RF+DC质量过滤 | `../workflows/mass_filter_reference/run_comsol.ps1` |
| release构造诊断 | `../comsol/interface_readiness/run_release_construction_gate.m` |
| 四、六、八极杆同源功能闭合 | [统一集成单反射工作流](../../../integrations/workflows/single_reflection_flight/run.ps1) |

所有任务通过仓库统一MATLAB/COMSOL入口建立连接，不自行`mphstart`。版本、启动及
`EXECUTION_ENVIRONMENT_BLOCKED`分类见[操作指南](../../../docs/OPERATIONS.md#工具链与执行入口)与
[公共COMSOL入口](../../../common/comsol/README.md)。
integration入口内部顺序调用COMSOL/SIMION stage；内部stage不是可独立运行或取得资格的公开入口。

## 模型与合同

有限三维 COMSOL 的实际 source preflight 显式选择 `--solver comsol`，按 resolved 的 numerical_domain
检查原始源位置；圆柱使用实际半径与轴向范围，旧矩形参考使用实际 box 半宽，不用 working region 代替物理域界。
越界在商业启动前报粒子 ID、位置与边界，不平移或删除粒子。体积 receipt 合法不等于源位于求解域内。
该检查不代替电极占据、接收面或科学接受判据；未选择 COMSOL 的原源校验语义保持。

接口就绪、质量过滤和旧同求解器比较只消费具名profile冻结的resolved、科学mode、粒子bundle和
`../variants/quadrupole/config/comsol_solver_numerics.json`。普通接口profile固定使用`baseline`数值身份；
`time_refined_160`只允许预注册的same-solver实验。MATLAB不选择profile，也不从环境或源码回退
物理/数值默认值。

三变体L3传输的typed电气模式与具名数值档只由`../config/runtime_profiles.json`绑定
`../config/comsol_solver_numerics.json`。它不属于上述专用workflow，专用workflow
也不得读取该合同；两种作用域都不允许wrapper暴露自由design/numerics profile。

共享求解实现`../comsol/solve_deterministic_rf_quadrupole_particles.m`只负责几何、场、求解器release节点、轨迹
和状态导出，不按workflow名称选择科学问题。接口准备任务负责验证RF-only、无碰撞、无静态端场；
质量过滤任务显式建立差分RF/DC与静态公共偏置；轴向加速走本项目多极杆模型入口。

标准输出为canonical逐粒子事件表、稀疏轨迹、原始 solver metadata、Python 生成的 solver summary 及
run 三件套。MPH 是否终态保留由运行前冻结的[保留合同](../../../docs/LIFECYCLE.md)决定。
MATLAB/COMSOL 只导出原始状态、事件和求解器元数据；传输率、出口 RMS、输出能量均值/标准差
及其他发布的聚合统计均由Python从canonical状态生成。求解器专属终点表不是新运行的稳定接口。

## 数值与物理边界

- 网格、RF 步数与最长时间来自具名数值合同；生产入口不接受标量覆盖。
- 当前模型无碰撞。轴向加速由本项目多极杆模型消费冻结电势合同。
- 生产粒子释放仍采用逐粒子 `ReleaseFromDataFile`；隔离向量化试验未证明等价，不能作为生产入口。
- 已完成的空间／时间敏感性、资源中断和 release 诊断见
  [历史记录](history/retired_projects/rf_quadrupole_ion_optics/docs/history/20260911__solver-sensitivity-and-retired-interface.md)；当前资格见 [PROJECT](PROJECT.md)。
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
该诊断保留用于正式接口构建链在 `ReleaseFromDataFile` 节点初始化阶段中断、节点数量或输入绑定
异常时，以同一冻结 N=100 输入隔离重现，不用于性能筛选或替代粒子求解。退出条件是正式构建链已有
覆盖相同 release 节点、粒子初始化及失败证据的行为验证，且该诊断不再有独立消费者；届时连同入口、
专属测试和登记一并退役。当前仍满足独立诊断用途，保留活动实现。


## 当前限制

连续量接受尺度、资源受限的加速模式以及机械交付仍有限制，具体状态与关闭条件统一见
[PROJECT](PROJECT.md#资格边界)。软件入口可执行不等于 Candidate 或 Formal 验收通过。

### 显式粗网格开发档

接口就绪现有 COMSOL 入口可显式选择 `-SolverNumericsProfileId core_flow_development_coarse`，
并使用 `-NumericalExperimentId core_flow_development` 和官方 quadrupole 数值合同。
该档只把 global auto level 从 1 改为 9，不开启 hmax override；RF 每周期 80 步、80 µs 时窗、
源、几何与接受条件保持。默认 `baseline` 不变；缺授权或非官方合同仍拒绝。
这是流程与源构造开发档，不授予场精度、传输或科学资格；实际网格仍须通过原门禁。
现有 `-ReleaseConstructionGate` 包括几何、网格和真实 stationary 求解，随后仅验证源构造，
不能称为零求解或完整飞行／GUI验收；原生成本与预算须由本次显式运行另行记录。
