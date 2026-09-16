# 单飞集成操作与恢复

本页从[项目入口](../README.md)进入；当前资格和待办见[INTEGRATION](INTEGRATION.md)，
参数权威与失效域见[ARCHITECTURE](ARCHITECTURE.md)。以下命令是操作模板，需替换显式路径，
从仓库根使用[规定工具链](../../../docs/OPERATIONS.md)。`-SolverAuthorized`会启动商业求解器，
必须先有已审阅输入和该次科学运行授权；文档整理不授予运行授权。

执行前先核对[PA输入边界](../../../docs/SIMION_REFERENCE.md#长pa输入路径)：原生family只在一次性
build staging中操作，已发布family及其副本不能被供应商进程打开。下文的“复用family”指冻结场身份
与已发布standalone表示的复用；若所选入口仍加载原生缓存family，先完成该入口迁移和回归，再执行模板。

## 主机资源阶段

`run_single_flight.ps1`和`run_analyzer_transport.ps1`在同一主机许可上切换阶段，分类及准入条件以
[中央调度策略](../../../docs/OPERATIONS.md#主机资源调度)为准：

| 阶段 | 运行边界 |
|---|---|
| `prepare` | 普通输入准备、缓存复用、GEM转换、IOB构建和不启动粒子的场采样使用轻许可 |
| `pa_refine` | 实际refine调用使用重许可；含refine的复合Lua调用也整段持有，包括名称为`initialize-only`但内部仍refine的构建器 |
| `flight` | 粒子飞行使用重许可，正式首批观测与后续完整波次位于同一阶段 |
| `postprocess` | 工作进程退出后的合并、分析和发布使用轻许可 |

refine操作或波次结束后回到准备阶段；纯缓存命中及已完成批次的恢复不制造新的计算工作。
此次调整只改变外层许可边界，保留既有45秒观测、自动并发、5秒增发及断点续算机制；不修改粒子、
数值或缓存算法。嵌套调用继承父许可，轻父不能被子入口静默升级为重许可；外层必须安排相应边界。
单次复合Lua调用中的轻准备与refine尚未进一步拆开，不能把该调用全程描述为轻任务。

## 审查与 dry-run

公开入口可用 `execute.ps1 -ExperimentId BEFORE -SemanticDiffAgainst AFTER` 比较同一 campaign 的两条**已展开**实验行；
它内部调用 `prepare.py --semantic-diff-experiment-json`，输出稳定 JSON：
每个字段的旧/新值及其审查类别（物理/场、数值/资源、采样、资格、运行控制或证据）。这是读操作，不参与
schema 验证、cache 命中、handoff 兼容性或资格决策；这些仍由已冻结的 resolved contract 与实际执行边界决定。
只读差异允许审阅仓库内的非活动 campaign，但不接受仓库外派生 campaign，也不能与执行模式组合。
这不恢复历史输入的执行授权；`ValidateOnly`、准备和求解仍经过原生命周期与探索准入检查。
诊断目录本身不授予权限：标为 `exploration` 的 campaign 不进入活动授权注册表。
在不启动求解器的情况下，可用 `execute.ps1 -ValidateOnly` 对某一行生成并校验其完整 resolved connection 与
composition plan。

普通探索不必预先登记为活动 authority：将 repository-managed campaign 标为 `"status": "exploration"`，并显式传入
`-Exploration -ValidateOnly`、`-Exploration -PrepareOnly -OutputDirectory ...`，或在准备完可审阅合同后使用
`-Exploration -SolverAuthorized` 执行非正式模拟。该路径仍执行 schema、来源 artifact、单位/frame/clock、粒子和
composition-plan 校验；它不以活动 campaign SHA 或 source-binding 刷新拒绝新的参数组合。探索运行保留普通的缓存、
SHA、manifest 与失败记录，可按入口的显式条件使用 `FinalizeOnly` 建立恢复run，但不能发布正式结果或产生资格结论。

探索的粒子数没有 schema 人为上限；它必须是正整数，并与冻结 source、ordered particle IDs 和分析分母一致。
实际并发由资源调度器按粒子数、CPU 和可用内存决定，不改变 handoff 的科学身份。

下游网格、反射区 cell、trajectory quality 与每周期 RF 步数可选择任一已登记的
`single_flight_*_profile_id`。探索合同还可在
`single_flight_numerical_overrides` 中直接给出正的 `trajectory_quality`、`rf_steps_per_period`，以及
前端/overlay/reflectron 的 cell；prepare 会把最终数值冻结进 `ResolvedExecutionProfile`。这不会修改默认
profile、上游 handoff 或正式资格；正式 campaign 仍以其预登记 profile 为准。

探索若复用一个已冻结的 post-pulse restart source，仍须验证该 source 的 manifest、checkpoint、pulse schedule、
粒子身份和所声明的变化轴；但不必为了只扫描加速场 profile 而附带正式资格专用的 source `z--vz` 理论工作点。
该理论闭合仍是 active/authorized restart 的失败关闭要求。


## 当前 8-mode 孔径矩阵的逐阶段执行与判定

以下命令必须从 PowerShell 7 执行。它们先完成一种截面再切换另一种截面；不得对混合方形/圆形的源 campaign
直接使用 `-AllExperiments`。`$PreOuter`、`$PostOuter` 和 `$ContinuousOuter` 必须填写对应阶段刚刚发布成功的
family-source-closure **父 run** 目录，不能填写其 child stage 目录或历史 producer。

```powershell
$Repo = (Get-Location).Path  # 先切换到仓库根 simulation_repo
$Workspace = Split-Path -Parent $Repo
$Py = Join-Path $Repo '.venv\Scripts\python.exe'
$Integration = Join-Path $Repo 'integrations\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer'
$Execute = Join-Path $Integration 'workflows\family_source_closure\execute.ps1'
$PreCampaign = Join-Path $Integration 'config\explorations\ideal_acceptance_300mm_terminal_aperture_height_axialgrid010_pre_pulse_n5000.json'
$Runs = Join-Path $Workspace 'artifacts\projects\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\runs'

# 方形先按 h100 -> h150 -> h200 -> h250；圆形随后按同一孔径顺序。
$SquarePreIds = @(
  'ideal_acceptance_300mm_square_accelerator_port_h100_pre_pulse_n5000',
  'ideal_acceptance_300mm_square_accelerator_port_h150_pre_pulse_n5000',
  'ideal_acceptance_300mm_square_accelerator_port_h200_pre_pulse_n5000',
  'ideal_acceptance_300mm_square_accelerator_port_h250_pre_pulse_n5000'
)
$CirclePreIds = @(
  'ideal_acceptance_300mm_cylindrical_accelerator_port_h100_pre_pulse_n5000',
  'ideal_acceptance_300mm_cylindrical_accelerator_port_h150_pre_pulse_n5000',
  'ideal_acceptance_300mm_cylindrical_accelerator_port_h200_pre_pulse_n5000',
  'ideal_acceptance_300mm_cylindrical_accelerator_port_h250_pre_pulse_n5000'
)

# 每一臂的 detector-blind pre-pulse/handoff；先单独执行方形 h100。
$PreId = $SquarePreIds[0]
& $Execute -Campaign $PreCampaign -ExperimentId $PreId -Exploration -SolverAuthorized
```

每个 pre 父 run 的 `run_config.json.stage_runs[0].path` 是相对 workspace 的 child 路径，可这样解析；随后只从这个
成功父/child 组合派生 post-pulse，不手工编辑 pulse 时刻：

```powershell
$PreOuter = 'C:\absolute\path\to\successful\pre-parent-run'
$PreConfig = Get-Content (Join-Path $PreOuter 'run_config.json') -Raw | ConvertFrom-Json -Depth 100
$PreChild = Join-Path $Workspace ([string]@($PreConfig.stage_runs)[0].path)

$DerivedRunId = "$(Get-Date -Format yyyyMMdd_HHmmss)__analysis__python__derived-post-pulse"
$DerivedRun = Join-Path $Runs $DerivedRunId
& $Py -m integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.publish_derived_post_pulse_campaign `
  --repo-root $Repo `
  --parent-manifest (Join-Path $PreOuter 'run_manifest.json') `
  --compact-receipt (Join-Path $PreChild 'results\pre_pulse_compact_handoff_receipt.json') `
  --output-run-dir $DerivedRun
$DerivedCampaign = Join-Path $DerivedRun 'results\derived_post_pulse_campaign.json'
$PostId = "${PreId}_post_pulse"
& $Execute -Campaign $DerivedCampaign -ExperimentId $PostId -Exploration -SolverAuthorized
```

同钟连续全流程不能运行未绑定新 producer 的通用 full-flight campaign，也不能复用历史 8-mode author 文件。
它必须由本轮成功的 pre/post **父 run** 映射重新 author，生成的 full-flight experiment ID 是把
`_pre_pulse_` 替换为 `_full_flight_`：

```powershell
$PostOuter = 'C:\absolute\path\to\successful\post-parent-run'
$ProducerMap = 'C:\absolute\path\to\versioned-pre-producer-map.json'
$PostMap = 'C:\absolute\path\to\versioned-post-producer-map.json'
# 两份map的键均是pre-pulse experiment_id，值分别为成功pre/post父run绝对路径。
# 预先核对；不要覆盖冻结run。为本轮指定全新、具名且未存在的campaign ID。
$ContinuousId = 'REPLACE_WITH_NEW_CONTINUOUS_CAMPAIGN_ID'
$ContinuousCampaign = Join-Path $Integration "config\explorations\${ContinuousId}.json"
& $Py -m integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.author_full_flight_campaign_from_pre_pulse `
  --source-campaign $PreCampaign --producer-map $ProducerMap `
  --post-pulse-producer-map $PostMap --output $ContinuousCampaign `
  --campaign-id $ContinuousId `
  --workspace $Workspace
$FullId = $PreId.Replace('_pre_pulse_', '_full_flight_')
& $Execute -Campaign $ContinuousCampaign -ExperimentId $FullId -Exploration -SolverAuthorized
```

其余方形三臂依次重复 pre -> derived post；再用包含三组成功父 run 的 producer/post JSON map author 一个三臂
continuous campaign，并在该**仅含方形三臂**的新 campaign 上执行 `-AllExperiments -Exploration -SolverAuthorized`。
全部方形闭合后，再对 `$CirclePreIds` 四臂执行相同步骤，并 author 一个仅含圆形四臂的 continuous campaign。

判定清单如下；任何一项缺失都不能把配置校验、post-pulse 或局部命中结果升级为完整母群结论：

- 每阶段父/child 的 `summary.json`、`run_manifest.json` 均为 success，且父 `run_config.json.stage_runs[0].path`
  指向被核验的 child。
- pre child 必须含 `results/pre_pulse_compact_handoff_receipt.json`、
  `results/pre_pulse_compact_handoff.csv` 和 `results/pre_pulse_particle_terminal_states.csv`；完整自然终态分类闭合 5000。
- post child 必须含 `inputs/canonical_pulse_restart_target_state_validation.json`、
  `inputs/resolved_single_flight_pulse_schedule.json` 与 `results/single_flight_particle_checkpoints.csv`。
- continuous child 必须含 `inputs/mother_particle_source.csv`、`inputs/resolved_single_flight_pulse_schedule.json` 与
  `results/single_flight_particle_checkpoints.csv`；summary 中 launched/source-release 为 5000、全母群终态分类闭合，
  不得使用共同命中筛选。author/prepare 会核验冻结源表 SHA、粒子数与顺序以及同一 pulse schedule。
- detector-blind 孔径比较使用
  `python -m integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.publish_pre_pulse_aperture_comparison`
  发布 `results/pre_pulse_aperture_comparison.json`；全母群连续结果使用对应的
  `analysis.publish_full_flight_aperture_comparison` 发布 `results/full_flight_aperture_comparison.json`。后者只有八臂齐全时
  `matrix_complete=true`。
- handoff/restart 与 continuous 的同钟状态核验已有
  `analysis.compare_handoff_replay`，输入两边 batch TRACE、row map、batch plan、program build、checkpoint 以及 restart
  validation/state；它当前只写诊断 JSON，不发布 immutable analysis run，因此不能单独充当可引用验收证据。

缓存预期是：同一截面的四孔径共享同一 8-mode 主 PA family，每个新孔径只新增小型入口 local family；pre 复用
粗前端、上游细域、主 PA 和 local，post 不加载粗前端/上游细域，continuous 复用全部已发布 family。方形与圆形
主 PA 不互相复用；跨截面的上游缓存是否命中必须以实际 cache identity/manifest 为准，不能只因几何看似相同而承诺。


## IOB与场边界

四槽pre-pulse和七槽连续飞行共享同一重叠优先级：`coarse < accelerator_main < upstream_bridge < local`。
槽号只是运行表示，消费者按Program build receipt中的物理角色比对；当前构建器是
[pre-pulse IOB](../runtime/build_single_flight_pre_pulse_iob.lua)。不从旧报告复制槽表。
post-pulse只物化其实际使用的主域、local和下游family，不以零场替代缺失来源。

独立轴场导出使用`program_axis_field_export`模式，重放`instance_adjust`空间谓词和冻结电压表，
PA+传mode编号，普通PA传物理电极编号；不叠加重叠PA。它不飞粒子，不给出粒子资格。
官方来源及已验证范围见[公共SIMION参考](../../../docs/SIMION_REFERENCE.md)。

主域/local的几何与全部响应必须按冻结身份配对。构建阶段的PA+控制器依赖完整solution family，即使
Program只动态驱动其中部分mode也不能裁剪构建输入。运行表示必须采用与该冻结身份绑定的standalone
响应或工作点，不能据此把已发布原生family重新交给SIMION。缓存隔离及长输入统一复用
[公共实现](../../../common/simion/README.md)与[长PA输入规则](../../../docs/SIMION_REFERENCE.md#长pa输入路径)。

资源策略由[公共调度器](../../../common/simion/resource_scheduler.py)拥有；项目只传冻结工作负载。
pre-pulse、post-pulse与连续全程分别匹配实际IOB和数值身份，不能交叉套用历史峰值。
每批ION容量按最大实际分片传给SIMION，不把软件默认容量当成粒子上限。

## 恢复失败与中断

| 观察到的状态 | 唯一操作边界 | 保留的声明限制 |
|---|---|---|
| 粒子批全部原生完成，TRACE物化失败 | [预脉冲恢复](../workflows/family_source_closure/recover_completed_pre_pulse_screening.py) | 新analysis run，逐项绑定原日志和冻结输入，不重飞、不覆盖旧run |
| 部分预脉冲批完成 | [预脉冲continuation](../runtime/pre_pulse_batch_continuation.py) | 只导入核验过的完整批或连续终态前缀，其余在新run重算 |
| 连续全程批部分完成 | [全程continuation](../runtime/full_flight_batch_continuation.py) | 完整source release、唯一终态、原生完成哨兵及来源哈希必须闭合 |
| 子run成功，父发布失败 | 公开`execute.ps1 -FinalizeOnly`的显式恢复条件 | 新身份关联原父/子manifest；exploration恢复不取得正式资格 |
| 冻结单时刻pulse-disabled状态 | [时间序列后继](../workflows/family_source_closure/run_time_series_successor.py) | 只消费预注册后继，核对源、布局、时钟和完整人口；条件群不冒充母群 |

`checkpoint`仅表示原始工作可恢复，不等于失败或中断。恢复前核对终态、冻结合同、完整母群和日志哈希；
不导入不完整或身份漂移数据。原run不改写，恢复结果写新的run并保留来源关系。
全部批次完成而后处理失败时可只恢复分析；不能为后处理方便改原始日志或放宽物理判据。

## 发布结果

[预脉冲孔径比较](../analysis/publish_pre_pulse_aperture_comparison.py)只给出detector-blind源诊断。
[全程孔径比较](../analysis/publish_full_flight_aperture_comparison.py)要求八臂同一完整母群，禁止共同命中筛选。
[handoff对照](../analysis/compare_handoff_replay.py)核对冻结状态和检测/损失身份；共有粒子只用于误差诊断。
无独立轨迹误差预算时明确未评估，不把初始化序列化容差当轨迹收敛标准。

脉冲后持续时间由冻结restart状态、质量/电荷与既有理想场公式派生，保留作者下限；这是持续时间估计，
需真实场复验，不证明全体粒子都已退出。完整指标由Python分析与analysis receipt发布。
