# RF多极杆离子光学：COMSOL实施与验证

本页覆盖统一多极杆项目的COMSOL入口，并区分四极杆专属workflow与四／六／八极共同typed模式。
三变体共用的设计、输入冻结与投影机制见[实现与运行合同](IMPLEMENTATION.md#求解器投影)；
下表中的无碰撞传输支持三变体；接口就绪和质量过滤保留四极杆范围，不由家族名称扩大资格。
本文只说明COMSOL模型入口、模型树边界、当前数值限制和GUI验收。跨求解器状态与开放任务只见
[`PROJECT.md`](PROJECT.md)；2026-07-28以前的完整诊断过程冻结在
[`retired_projects/rf_quadrupole_ion_optics/docs/history/20260728__pre-document-consolidation-comsol.md`](history/retired_projects/rf_quadrupole_ion_optics/docs/history/20260728__pre-document-consolidation-comsol.md)。
多极杆各轴向实体与事件面只采用
[实现与运行合同](IMPLEMENTATION.md)的统一术语。

## 活动入口

| 科学问题 | 入口 |
|---|---|
| 接口就绪输运 | [原 CLI](../workflows/interface_readiness/run_comsol.ps1) |
| 四／六／八极无碰撞传输 | [原 CLI](../workflows/no_collision_transport/run_comsol.ps1) |
| RF+DC质量过滤 | [原 CLI](../workflows/mass_filter_reference/run_comsol.ps1) |
| release构造诊断 | 接口 CLI 的 `-ReleaseConstructionGate`；[原任务](../comsol/interface_readiness/run_release_construction_gate.m) |
| 四、六、八极杆同源功能闭合 | [统一集成单反射工作流](../../../integrations/workflows/single_reflection_flight/run.ps1) |

所有任务通过仓库统一MATLAB/COMSOL入口建立连接，不自行`mphstart`。版本、启动及
`EXECUTION_ENVIRONMENT_BLOCKED`分类见[操作指南](../../../docs/OPERATIONS.md#工具链与执行入口)与
[公共COMSOL入口](../../../common/comsol/README.md)。
集成入口按本次冻结计划调用适用的 COMSOL／SIMION stage；内部 stage 不是独立公开入口或科学资格。

## interface readiness 的预算与收尾恢复

正常入口的源表、paired bundle、源家族与分布必须属于同一已验证源；数值合同与具名 profile 显式选择：

```powershell
./projects/rf_multipole_ion_optics/workflows/interface_readiness/run_comsol.ps1 `
  -RunId <new-run-id> -ParticleTablePath <source.ion> `
  -ParticleBundleMetadataPath <paired_particle_bundle.json> `
  -SourceFamilyPath <source-family.json> -ParticleDistributionPath <distribution.json> `
  -SolverNumericsContractPath <quadrupole-numerics.json> -SolverNumericsProfileId <profile-id> `
  -OperatingPoint <operating-point-id> -LimitsPath <limits.json> -PythonExe <python.exe>
```

LimitsPath 序列化公共启动器既有 Limits：`wall_clock_seconds`、`transient_run_directory_bytes`、
`process_tree_working_set_bytes`、`minimum_system_available_memory_bytes` 均须为正整数，按本次工作量声明。
启动次数默认 1；开发粗网格 profile 还须提供其声明的 `-NumericalExperimentId` 授权。
`-ReleaseConstructionGate` 只停止在 release 构造验收：它包含真实网格与静电求解，不执行粒子推进或完整 GUI 验收。
正常完整入口仍执行本工作流声明的 GUI Compute，实际重求次数计入结果，不能当作纯重开。

沿原入口恢复仅收尾，使用运行前已持久化的原 Result：

```powershell
./projects/rf_multipole_ion_optics/workflows/interface_readiness/run_comsol.ps1 `
  -ResumeFinalization -ResultPath <original-result.json> -PythonExe <python.exe>
```

恢复不接受新的科学或运行参数，不改原执行终态。入口接线、真实求解与科学资格的当前验收分别见[项目状态](PROJECT.md#当前结论)。

同一接口 CLI 的 `-AnalyzeOnly -ParentManifestPath <parent-manifest> -LimitsPath <new-limits> -RunId <new-run-id>`
创建新的后继分析 owner，复用充分完成的原 native 输出，不执行新的求场或 GUI Compute。checkpoint 父须显式提供
实际 `-StoppedReceiptPath`；已终态来源沿原保护核验，不另造停止收据。源／科学参数只取父冻结输入，原终态不变。

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

## 既有 campaign 的后端与几何授权

既有 `octupole_simion_transport_campaign_engineering` 保留原身份，其实际 tools／模型交付现在同时声明
SIMION 与 COMSOL；既有 `runtime/run_simion_transport_campaign.ps1` 按显式 experiment.solver 调用同一项目 launcher，
历史文件名不再表示固定 SIMION dispatch。原 One／All／Status／Diff／DryRun 与 SIMION analysis 行为保留，
SimionExe／case_set 仅传给 SIMION 行，不创建第二 campaign runner 或 profile。

COMSOL 的 design_variable_authorization 仅开放既有 `vacuum_z_min`，单位 mm；仍须通过原设计变量目录、窄请求范围、
既有 envelope、结构变体／实际 backend profile 及真实设计 compiler。其源 phase／transform、PA basis、
analysis_requests 及其他 SIMION 专属策略继续拒绝；不增加新物理模型或科学资格。声明可同时支持两模型的 profile
不代表每个行会运行两 backend；实际 scope.allowed_solvers 只包含所选 backend。
本次设计请求的变量也必须属于实际行已授权的变量集合；COMSOL 行不能借 profile 的支持集合承诺消费 RF 电气变量。
行显式选择非 compact 保留时，共用 launcher 将冻结的 campaign／experiment 身份和 claim_limit 传为保留原因；已有显式 RetentionReason 优先，仍执行原保留政策校验。

冻结 runtime 仍绑定原 campaign 字节与所选行的 backend／run ID，沿同一 snapshot 进入预算和准备，不重新解析缺失的作者目录。
上游 numerical_domain 改动生成新的 resolved 身份，两 backend 的场都须重新判断有效性；不能把相同源 CSV 当成场可复用证明。

## 模型与合同

有限三维 COMSOL 的实际 source preflight 显式选择 `--solver comsol`，按 resolved 的 numerical_domain
检查原始源位置；圆柱使用实际半径与轴向范围，旧矩形参考使用实际 box 半宽，不用 working region 代替物理域界。
越界在商业启动前报粒子 ID、位置与边界，不平移或删除粒子。体积 receipt 合法不等于源位于求解域内。
该检查不代替电极占据、接收面或科学接受判据；未选择 COMSOL 的原源校验语义保持。

接口就绪、质量过滤和旧同求解器比较只消费具名profile冻结的resolved、科学mode、粒子bundle和
`../variants/quadrupole/config/comsol_solver_numerics.json`。普通接口profile固定使用`baseline`数值身份；
`time_refined_160`只允许预注册的same-solver实验。
`core_flow_development_coarse`通过同一数值编译器显式选择，并要求`NumericalExperimentId=core_flow_development`；
当前条目采用全局 auto9、显式 hmin0.2mm，working hmax override 仍关闭；RF 每周期80步与80µs窗口保持，
默认 `baseline` 不变。这是已授权流程／源构造开发档，不代表网格精度或科学资格。
这与finite合同的`core_flow_development_coarse_8us`是不同数值角色，不可互相替代。
MATLAB不选择profile，也不从环境或源码回退物理/数值默认值。

三变体有限三维传输的typed电气模式与具名数值档只由`../config/runtime_profiles.json`绑定
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
- 两个生产 solver 使用精确同 birth／release 属性分组的 `ReleaseFromDataFile`；不同 birth 不合并，
  unique-birth 源仍有 N 个节点。旧不等价向量化试验不作为生产入口；分组、映射及验收范围见下节。
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

release构造 Gate 验证完整 N=100 输入的实际分组节点、每组文件及 breadcrumb 闭包；
按 group_index／source_rows／birth_s 核对完整母群，而非要求100个节点。同 birth 可少于100组，
unique-birth 时仍为100组。这里的 release 是 COMSOL 求解器节点，不是粒子源合同或带孔接口板。Gate不运行
粒子Study，也不能产生传输或资格结论。历史`rel065`调查、Unicode报告修复和runner收尾过程只从
同日history快照追溯。
该诊断保留用于正式接口构建链在 `ReleaseFromDataFile` 节点初始化阶段中断、节点数量或输入绑定
异常时，以同一冻结 N=100 输入隔离重现，不用于性能筛选或替代粒子求解。退出条件是正式构建链已有
覆盖相同 release 节点、粒子初始化及失败证据的行为验证，且该诊断不再有独立消费者；届时连同入口、
专属测试和登记一并退役。当前仍满足独立诊断用途，保留活动实现。

## 当前限制

连续量接受尺度、资源受限的加速模式以及机械交付仍有限制，具体状态与关闭条件统一见
[PROJECT](PROJECT.md#资格边界)。软件入口可执行不等于 Candidate 或 Formal 验收通过。

## 精确同 birth 分组与有界提取

有限三维 `solve_finite_3d_transport.m` 与四极 `solve_deterministic_rf_quadrupole_particles.m`
实际复用项目 `comsol/plan_rf_exact_birth_releases.m`。只有精确 SI birth 和 release 属性相同的粒子才共享
多行 `ReleaseFromDataFile`；ID、完整6D、物种及已有权重保持，不量化 birth 或重置 RF 相位。完整母群保存在
原生解／MPH，提取依据 `native_order` 映回原 source 行；原生导出须与 `release_source_mapping.json` 一起解释。
ION11 的 cwf／颜色保留为来源事实；缺完整权重时不补造等权统计。

release-construction result／breadcrumb 使用现有 schema_version=2 的 group_index／source_rows／birth_s；
schema1 仅作历史只读，活动 Gate 不回退。Gate 在粒子 Study 前停止，不能代替传输或完整 GUI Compute。
确定性四极构造还在官方 `disableUpdates` 作用域内延迟更新，正常／异常恢复原更新状态；构造计时包含最终刷新。
它不减少 unique-birth 的节点数，不能把局部构造段减少直接写成完整命令收益。

两 solver 均在后处理前保存必要原生解，再由同一项目 extractor／visitor 读取原解库存时刻和完整母群。
逻辑窗口保持256点及原跨窗邻接；已知 N100、库存不超过7119时刻时，API 可一次读取两个逻辑窗口，
原采样、记录和终态判据不变。其他／未知 N、其他逻辑大小或更长库存保留原 API 窗口，未外推到 N1000／5000。
API批量不是积分步长或时间降采样；实际返回内存及进程／临时盘仍受本次 owner 预算约束。

本轮两个消费者各自预先声明的 N100 工作量已有正常公开命令收益证据；
finite 的同 birth 入口段与四极 unique-birth 接口正常链具有不同范围，不互相冒充。
此前四极延迟更新实验“构造段减少、完整命令变慢”的负结果仍保留；后来的正常 K1／K2 正配对不抹去它。
最终 finite 冷提取也已从原071000受保护模型验证当前 K2 消费与原七份 CSV 一致，零新 Compute／父保存。
实际规模、命令、计时和限制只见[项目状态](PROJECT.md#当前结论)，不在本操作页重复长表。
这些证据不声明通用较大 N 收益、native 精确 birth 初态独立 echo、积分精度或 Formal 资格；
较大 N 未覆盖也不自动成为新的未授权运行要求。

## 普通无碰撞COMSOL的campaign请求

finite入口从公共`Resolve-WorkspacePaths`取得本次源码、产物、执行与主机资源上下文，
将同一上下文传给`New-RunPackage`，不再从源码父目录硬编码产物根。
非默认产物根和共享主机状态路径使用[已有配置](../../../common/paths/README.md)；
本次 run 冻结后不随环境默认值改变。仅分析／冷提取及收尾恢复分别使用上文原 CLI 分支，不把路径接线本身当作恢复资格。

MATLAB源起点消费同一份已冻结的canonical预检元数据：显式体积快照必须具有既有receipt authority，
平面源仍执行原释放面检查；不改源、birth、物种或极性。体积、时钟与能量接受条件仍由原Python owner校验。
冻结收尾闭包包含retention实际调用的`common/simion/native_completion.py`，不因此启动SIMION。

原`workflows/no_collision_transport/run_comsol.ps1`支持具名`-RuntimeProfileId`，或互斥的`-CampaignPath <data.json> -ExperimentId <row>`；复用同一launcher、解析与预算机制，不提供COMSOL inline numerics。campaign只开放现有resolved无碰撞传输，SIMION专用源变换、dispatch、case_set或分析声明明确拒绝。一次解析的数值、源、volume receipt与保留政策传到实际prepare，不由wrapper重新选择默认。volume snapshot receipt核验后冻结进inputs，并由正式源preflight消费；缺失、篡改或冲突不进入求解。

`core_flow_development_coarse_8us`是显式开发数值档（auto9、working hmax2mm、原quadratic/mumps/RF80），不是生产精度或全程传输资格。具体Goal开发请求须另行冻结原source/receipt、研究窗、固定新runID与不抬高的预算，原authorized=false合同不变。8us入口段性能/母群数据结果不能当作已到handoff或census。API保存模型、冷重开与GUI Compute分别报告；正常COMSOL目前不支持SIMION的NativeFieldRunPath场复用参数。

### 网格失败诊断保留

有限三维入口的网格接受条件保持不变。失败断言同时报告全局与真空选择的 empty、has_problems、complete 和真空元素数；原报告保留已有网格统计与 problem 消息。公共 LiveLink 启动器只在 RUNNING 开始新 attempt 时清空报告，终态追加到同一报告，避免异常传播覆盖阶段诊断。`hasproblems` 包括 COMSOL warning 节点，不能仅凭总断言推断具体网格缺陷；按报告中的实际条件与 problem 消息定位，不自动放宽门禁。

Campaign 的既有 `stop_stage` 对 COMSOL 支持 `transport` 或 `mesh_build`。后者仅构造几何和网格，在场物理/研究和粒子求解前停止；相同 campaign 行的解析快照、预算及正常 launcher 使用同一停止阶段。SIMION 仍只允许 `transport`，campaign 不开放 `field_solve`。网格诊断不是传输或科学资格通过。

开发条目 `core_flow_development_coarse_8us` 明示 `mesh.minimum_element_size_mm=0.2`，用于保留 auto9/hmax2mm 的薄区域网格机制试验；它不是通用默认、精度推荐或资格结论。现有 campaign resolver→budget→launcher→finite 数值文件冻结相同值，实际 MATLAB 同时施加到全局与工作区 Size。省略字段的原数值条目行为不变。报告保留 typed raw Size 参数与问题实体；其他控制若随 custom/hmin 写入发生漂移则失败。旧冻结 run/树不改，变化的数值定义要求新身份和新网格证据，两臂比较必须使用同一新数值。

Mesh-build 报告校验按冻结数值的实际 strategy 分支，策略必须唯一且匹配；缺省为既有 selected_region_free_tetrahedral。两种策略都验证原非空、无 problems、正元素数、正真空体积/选择数/真空最小质量及零场/粒子创建终态。selected 保持原 MATLAB 的 global complete；hybrid 保持原 rod size/分区覆盖门禁，不新增 global/vacuum complete 或 global minimum quality 硬条件。vacuum complete 与 global quality 继续为诊断。

050000 mesh-only 实际已证实 hmin 写读保持其他 Size 控制，原生 mesh PASS（45706/28272 元素、无 problems），但当时公开 run 因旧解析器误要求 hybrid 字段而 failed。修复后只读校验旧封存报告不能改其终态，也不是重新求解/科学资格。原 CLI ResumeFinalization 只恢复收尾，不能重跑分析；若需持久新分析结论，须沿受管新 analysis run 引用原证据，不能手改父 run 或为补解析重构 mesh。

Finite 单 run 出口状态图显式使用 `--allow-no-exit`：默认 `load_exit_state` 与比较绘图仍要求有效支持出口；仅该单序列可选分支在源字段、6D/时间数值和粒子 ID/归属有效且没有支持出口时写 `status=not_applicable`/具体 reason，figure=null，不创建 PNG、不新增源大载荷 hash，也不推断损失或科学通过。坏源、未知 ID、坏出口数值及其他分析/发布错误继续失败。正常有出口时保持原绘图并记录 status=created。finite summary 保存 exit_state_plot_status/reason，只有 created 才要求 PNG。

8µs 不保证每粒子一定无出口；有无出口以本次实际记录为准。该正常零出口／时间截断分支不改变推进窗、源、场或物理接受条件，
也不把未观测到出口推断为物理损失。

Finite 末态使用当前实际原生时间库存的观测事实：extractor 保留最后库存 index/time、最后有限 index/time、末库存是否有完整有限 6D、有限轨迹是否已结束。有限末样本不等于 native alive，有限轨迹消失也不证明电极碰撞。两个实际 exporter 共用项目纯分类器：保留原 census/rod/接受包络谓词，只有原接受条件为真才 transmitted；其他情况为 unknown，分别记录 time_window_end 或 ended_without_loss_evidence。实际观测到的接受拒绝另以 acceptance_status/reason 两列记录，可与时间截断同时存在，不混成物理 loss。源状态/ID/权重/时间和6D不改。

Python 正常分析调用现 particle_census 关闭全母群 terminal 分区，独立输出接受拒绝 ID/原理由及 unknown 观测原因；源完整权重未在 canonical CSV 记录时，权重指标明确不可计算。旧格式未记录接受列时标 unavailable；旧 finite 默认 lost/electrode 不是原生损失证据，在新分析中归 unknown/loss_evidence_unavailable，同时保留原 reported ID/status/reason。原记录不改，不用旧默认值继续伪称已证实损失。transmission_fraction 明确只表示记录窗口内已观察接受比例，未知不是 1-transmission 的物理损失。
