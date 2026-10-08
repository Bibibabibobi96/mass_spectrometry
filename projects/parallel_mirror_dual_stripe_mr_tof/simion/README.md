# MR-TOF SIMION 实施说明

本页说明 SIMION 入口、输入和独立验收；当前工作点、资格、运行证据及开放任务见
[项目状态](../docs/PROJECT.md)，其他软件入口见[项目导航](../README.md)。
输入版本见[输入权威](../docs/PROJECT.md#输入权威与物理定义)，当前执行顺序见
[开放动作与关闭条件](../docs/PROJECT.md#开放动作与关闭条件)。
命令从仓库根 `simulation_repo/` 执行；尖括号为必须替换的占位路径。
工具版本、商业执行及资源准入统一遵守[操作指南](../../../docs/OPERATIONS.md)。

## 按任务查阅

| 任务 | 本页入口 |
|---|---|
| 确认几何、坐标与组件责任 | [输入与装配](#输入与装配) |
| 选择 native 或 COMSOL 场消费 | [场输入与碰撞](#场输入与碰撞) |
| 构建 native bank、重载 IOB 或保留 GUI | [构建与独立验收](#构建与独立验收) |
| 发布源、完整飞行和 P/S 调节 | [源与运行入口](#源与运行入口) |
| 断点续接或 N>1 批次恢复 | [恢复与资源](#恢复与资源) |
| 解释返回、碰撞及峰宽结果 | [事件与分析](#事件与分析) |
| 追溯旧工作台、结果和迁移过程 | [历史与来源](#历史与来源) |

## 输入与装配

[候选合同](../config/simion_candidate_two_zone.json)提供 MR 物理输入和机械约束，
[resolved_geometry.py](../analysis/resolved_geometry.py)生成求解器无关的毫米几何；
[native_system_geometry.py](../analysis/native_system_geometry.py)及
[native_corridor_geometry.py](../analysis/native_corridor_geometry.py)只派生 SIMION 副本。
GEM、PA、IOB 和 GUI 不持有下一轮可调几何真值；旧 PA 不因源码修复自动恢复有效性。

坐标固定为 `z` 快速反射、`y` 慢漂移、`x` 横向聚焦。`z=0` 是中央注入／第一时间焦点
交接面，不代表最终质量焦点或必然的空间束腰。活动完整返回使用静态 P1/P2 和关于
`z=0` 的非重合镜像去回程；离子在 `z>0` 沿 `-z` 命中朝 `+z` 的探测面。
首次安全离开加速器后禁止重入；回程不进入 P1，不切换棱镜电压。

四块 Stripe 的物理电压分组为 `(11,12)→S1`、`(13,14)→S2`，曲线来自合同 B-spline。
Stripe、中央接地件和棱镜屏蔽由完整实体扣除有限槽，保留真实端部连接材料；
不能另加桥接盒或因离散化改变孔槽。接地件使用物理 ID18/20，旧拆分 ID19/21 已退役。
`geometry_receipt` 绑定 resolved 几何、单位、坐标、电极 ID 和孔槽。

加速器局部理论、几何、PA 和电压由独立 OA provider 拥有；MR 通过
[accelerator_dependency.json](../config/accelerator_dependency.json)及
[run_accelerator_component_provider.ps1](run_accelerator_component_provider.ps1)消费统一
`mrtof_runtime_receipt.json`。出口、grid1、repeller 沿更大的 `+z` 排列，出射沿项目 `-z`。
OA PA 以 `x=0` 为镜像面，只存半域；实例原点必须保留镜像面，重载检查 `3dplanar[x]`。

加速器全局 y 由 `accelerator.focus_y_anchor.project_y_mm` 决定。装配读取 provider 的
实际 PA 原点及实体包络，并与 resolved Prism2 屏蔽件、Stripe 检查净间隙；
数值 PA 包络可为优先级而重叠，导体实体不得相交。位姿不属于独立 PA 的生成输入时，
只新建飞行身份并重新评估残差，不据此重建 corridor family。

## 场输入与碰撞

完整飞行复用四个 Workbench 角色，优先级为
`global_fallback → native_corridor → accelerator → detector`。
保存后必须重载并用实际重叠区 `wb:find_at` 检查，不能只相信合同表或显示顺序。

| 消费方式 | 场的来源 | 输入与限制 |
|---|---|---|
| native Fast Adjust | 已发布全走廊 response-bank，加独立 OA/detector PA | `-NativeCorridorBankRunPath` 与 `-NativeSystemRuntimeBundlePath` 配套；电压表按实际 bank 通道映射 |
| COMSOL 标量场 | 已封存标量 V、valid mask 及有序局窗，通过原生 `field_array` 消费 | `-FieldBindingPath`；完整电压、几何、网格及装配身份必须相符，不可只改 Fast Adjust 代替更新外场 |

native 路径中 corridor 承担可调分析器场，global fallback 提供低优先级完整几何。
COMSOL 路径使用独立碰撞 PA；其电极标签、Workbench 场查询和事件 `ion_volts`
不代表实际 COMSOL 电势。外场、碰撞几何和 detector 命中必须分别验证。

探测器 GEM 使用 ID25 建立物质掩码；[build_component_pa.lua](build_component_pa.lua)
在 `INITIALIZE=0` 时置零电势并保留电极标志，不把 ID25 当成 25 V。
该数值终止面不等同于已验证的物理探测器，原生终止与事件面须逐次核对。

### COMSOL 标量、响应组合与固定点物化

本节 COMSOL 功能属于 mesh3 工程候选，配套源码仍待整链验收；本次文档收缩不发布这些代码变更。
复用以下命令前，须确认对应候选版本的模块与 runner 参数齐备。
`analysis/static_field_binding.py`解析已封存场，`simion/scalar_field_adapter.lua`只在有效支撑内查询。
局窗按有序列表、包含边界、首个匹配窗口接管；必须保留梯度支撑 halo。
窗内未知值不回退基场、不补零；覆盖越界、未知 mask 或非有限值是数值失败。

S1/S2 仿射组合在既有 binding 内声明同锚基场、两单因素场及目标电压；
系数由实际电压差派生，逐项保持网格、mask、sheet、窗口和固定物理身份。
场线性不代表轨迹线性；新电压必须通过同一完整飞行入口检验。
固定点物化复用公共 standalone composer，输出新标量 PA，保留原 mask 和所有局窗。
两种组合表示均明确标为探索性；实际对照、速度、内存及资格见
[电场表示与数值资格](../docs/PROJECT.md#电场表示与数值资格)，不由文件存在推定。

以下命令只验证／解析 binding，或生成物化计划；不会运行 COMSOL、SIMION 或写 PA。
物化计划必须由受管运行执行和封存，再消费其 manifest；不得覆盖输入 PA。

```powershell
.\.venv\Scripts\python.exe -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding --binding '<binding.json>'
.\.venv\Scripts\python.exe -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.static_field_binding `
  --binding '<response-binding.json>' --composition-plan '<run>/inputs/composition-plan.json' `
  --composition-output-directory '<run>/simion'
```

同模块支持配对查询请求：`--compare-binding`、`--samples`、`--sampling-request`、
`--comparison-output` 必须成组提供，不能与物化计划混用；它只生成请求，不提供实际场对照。
GUI 对等不能由 `efield_adjust` 回调推定，最终交付仍须满足实际所用表示的独立验收。

## 构建与独立验收

[run_native_corridor_response_bank.ps1](run_native_corridor_response_bank.ps1)组织 native bank
生成，调用公共 PA transaction 完成 Refine、inventory、封存和发布。
底层 transaction 编排见 [run_native_corridor_qualification.ps1](run_native_corridor_qualification.ps1)。
[native_corridor_identity.py](../analysis/native_corridor_identity.py)定义项目 family 身份；
物理到局部 ID 映射和响应数量来自冻结 plan，不在本文固定某次 bank 的数量。

响应成员遵守原生 Fast Adjust 的 `10000 V` 参考归一化，不能把 1 V 文件当原生 `.paN`。
发布前在精确私有 family 上验证非零电压表及关闭／重开，最终 inventory 绑定持久字节和验证证据。
公共 transaction 是 payload、scratch、发布指针和容量账本的唯一 owner；
项目不维护第二份 PA 生命周期。缓存命中不得再做 GEM、Refine 或大 PA 复制。

[build_native_corridor_iob.lua](build_native_corridor_iob.lua)仅装配已封存四角色，
检查位姿、网格、对称性及真实重叠优先级。先保存 IOB，再做 Fast Adjust，
避免 Workbench 保存尝试回写脏 PA；日志中的保存错误即使进程 exit0 也判失败。
原生电压更新一次提交完整通道表，不逐区合成或保存 published PA。

`-RetainGuiWorkbench` 在共享 native runtime checkpoint 语境下保留
`simion/gui_workbench/` 的 IOB、Fly2、Lua 和小型收据，飞行后绑定稳定只读 PA。
没有要求的共享 checkpoint 时不得为 GUI 重建整套 family；实际模式限制以入口校验为准。
GUI 重载通过只证明装配可检查，不能代替场精度、飞行或性能资格。

[单中心步长对照](../analysis/run_single_center_timestep_convergence.ps1)要求三份 success
run 的几何、PA、电压、源、程序、脉冲和自然回程身份相同，仅最大 trajectory step 不同。
分析报告目标 K、回程转折及 detector 的相空间差，不自行设置通过阈值。
静态入口 [verify_project.ps1](../verify_project.ps1) 不启动商业软件；真实 SIMION、
GUI 重载及正式资格属于不同验证层，不能互相替代。

## 源与运行入口

所有入口消费本次冻结合同、源及 PA／field 身份；参数全集见各脚本 `param`。
下面标为飞行、建场或调焦的入口会运行商业软件；分析、源发布及计划生成不运行 SIMION。

| 任务 | 入口 | 必需输入与输出范围 |
|---|---|---|
| OA 组件验收 | [run_accelerator_component_provider.ps1](run_accelerator_component_provider.ps1) | provider 请求／receipt；不授予整机资格 |
| N=1 或 N>1 完整飞行 | [run_two_prism_trial.ps1](run_two_prism_trial.ps1) | 几何、镜、Stripe、OA receipt、P1/P2 电压及一种场消费输入 |
| 束团源发布 | [run_publish_bunch_source.ps1](../analysis/run_publish_bunch_source.ps1) | `-SourceDefinitionPath`、`-GeometryContractPath`、`-AcceleratorProviderReceiptPath`；发布 CSV/Fly2/receipt |
| P/S 四列单步审计 | [run_downstream_fixed_grid_workpoint.ps1](../analysis/run_downstream_fixed_grid_workpoint.ps1) | baseline 与四个独立单轴扰动 manifest，输出有界电压提议 |
| P/S 自动重闭合 | [run_downstream_workpoint_iteration.ps1](../analysis/run_downstream_workpoint_iteration.ps1) | 唯一初始工作点、seed 或 continuation；独立 child 飞行及控制器记录 |
| native 束团筛选 | [run_native_corridor_bunch_screening.ps1](../analysis/run_native_corridor_bunch_screening.ps1) | 同一 checkpoint、冻结静态 cohort；受控小样本不提供正式峰宽 |
| native Candidate／TE1 链 | [run_native_candidate_chain.ps1](../analysis/run_native_candidate_chain.ps1) | 已接受中心工作点、common 源及相同前缀的 baseline/调焦比较 |
| K/y campaign | [run_native_candidate_campaign.ps1](../analysis/run_native_candidate_campaign.ps1) | [工况表](../config/native_candidate_campaign_k_y_scan.json)；发布统一 comparison |
| 源 z／能量／末段时序分析 | [run_source_z_energy_timing_diagnostic.ps1](../analysis/run_source_z_energy_timing_diagnostic.ps1) | 完整 success flight；只读诊断，无新飞行 |
| 固定关断时钟冻结 | [run_freeze_bunch_pulse_schedule.ps1](../analysis/run_freeze_bunch_pulse_schedule.ps1) | 同源完整静态 pilot，发布 schedule；不证明脉冲已真实执行 |

P/S 单步审计的五个 manifest 参数为 `-BaselineManifest`、`-Stripe1PerturbationManifest`、
`-Stripe2PerturbationManifest`、`-Prism1PerturbationManifest`、`-Prism2PerturbationManifest`。
单轴场与轨迹须按该入口合同保持共同冻结问题；边界、尺度、信赖步及停机规则由
`downstream_fixed_grid_workpoint_profile` 派生，不从命令行另设一套数值。
提议不是通过资格，必须真实飞行检验。

自动迭代的 `-InitialWorkpointManifest`、`-SeedTrialManifest`、`-ContinuationRunManifest`
三选一。native 模式使用 bank/bundle；COMSOL 模式使用 `-FieldProviderRequestPath` 和冻结
`-CenterSourceReceiptPath`，不得混入 native family/checkpoint 或 OA pulse。
同目标已完成场可通过 `-CompletedFieldProviderManifest` 显式复用；
`-ResponseFieldBindingPath` 声明探索性 S 响应，不能据此外推其他未声明电压。
静态 seed 分阶段提取 P 前闭合、同锚 S 响应及完整返回；阶段通过不等于整机通过，
下游缺事件不补零，不把旧轨迹 Jacobian 当新锚点已验证导数。

native Candidate 链的受控焦点对及回退区间只供导数，不混入正式体积源峰宽。
实际 cohort、收集门槛和有限回退规则来自冻结合同；达到退出条件即停止该工况。
同一母队列前缀比较收集率、TOF 和 FWHM，不删损失、不去趋势、不凭单次最佳结果晋升。
活动任务的样本、TE1 范围及源参数见
[真实源与束团证据](../docs/PROJECT.md#真实源与束团证据)，不从历史配置推定。

解析电压链使用 [run_target_operating_point_chain.ps1](../analysis/run_target_operating_point_chain.ps1)，
从同一合同串接镜 exact-K 与双 Stripe 反演。P1/P2 分段射击继续使用
[coverage](../analysis/run_two_prism_segmented_coverage.ps1)、
[continuation](../analysis/run_two_prism_segmented_continuation.ps1)及
[operating-point 审计](../analysis/run_two_prism_operating_point.ps1)：continuation 只追踪
冻结的单一事件签名，理论覆盖点不能直接称为真实三维工作点。

### 源身份与诊断源

源表、Fly2、合同粒子数、预期 ID 及 SHA 在输入 manifest 中绑定；
母粒子数不能从已记录终态反推。改变释放分布只改变源／飞行身份，不重建 PA family。
正式体积源不夹受控参考粒子；Gaussian 的能量标准差、非正动能处理及共同母序列
由源合同和既有 publisher 定义，不在本文复制本次源数值。

| manifest source key | 诊断范围 |
|---|---|
| `mirror_internal_diagnostic_center_fly2`／`mirror_internal_diagnostic_bunch_fly2` | 分析器内释放，绕过 OA/P1/P2，只隔离镜／Stripe |
| `accelerator_focus_center_fly2`／`accelerator_focus_bunch_fly2` | 第一区由静止释放，检查加速器第一时间焦点，不能代替脉冲源 |
| `first_prism_entry_center_fly2` | 两区焦面处释放，只供首棱镜三维射击 |
| `full_mrtof_center_fly2` | 按审计工作点生成的完整源到 detector 链，N=1 与 N>1 使用同一事件定义 |

不同具名源不能合并统计。整机源位置须按 MR 装配与 OA provider release 合同派生；
位置、物种、速度、ID 和共同出生时刻原样继承。旧 schema 只能解释旧证据，不能补造新资格。

## 恢复与资源

完整束团仍由 `run_two_prism_trial.ps1 -BunchSourceReceiptPath ...` 执行；
receipt、状态表和 Fly2 必须是同一成功源 run 的唯一输出。
公共调度器选择资源和 batch，项目不设独立并发门槛；详见
[公共调度与恢复](../../../common/simion/README.md#调度与恢复)。

每批是连续全局 ID 区间，SIMION 内局部编号 `1..n`；合并仅用计划的
`simion_particle_id_offset` 还原，拒绝缺失／重叠，保留全部非完成日志，
只生成一个全局 Fly-completion。各批共用冻结场及 IOB，不逐批构建或 Refine。
`-BunchParticleIdMin/-BunchParticleIdMax` 只选冻结源连续区间，结果属于源选择诊断。

每个自然完成 batch 发布 manifest-bound checkpoint。新 run 使用
`-BatchContinuationRunPath` 导入连续完整批次前缀；未完成批次整批重放，
不更改原 run 身份、物理输入或调度规则。screening 的 pilot/cohort 分别传其恢复入口。
父 P/S workflow 恢复使用新 `RunId`。只有首个成功 child 时，可单独传
`-ResumeSuccessfulChildManifest`；后续轮须与 `-ResumeParentCheckpoint` 配对，
指定连续链末端。bootstrap 恢复使用父 checkpoint，不接受任意 child 覆盖。
恢复沿原状态机核对冻结输入、电压、观察和已完成 child，不扫描目录猜测可用结果，
不重飞已确认完成的步骤；精确参数组合由入口失败关闭。

native bank 的 `-TransactionCacheKey` 只恢复／复用指定事务；已发布 family 只读。
`-RecoverMembers` 指定失败成员；`-RecoverRetainedInventoryMembers` 和
`-CorrectPublishedInventoryMember` 仅处理有原 journal 证明的 inventory 问题，
不得借此重写物理输入、重建发布成员或伪称新求解验证。
公共 owner 负责单写者、库存、封存及退休；身份不符保留证据并停止，不静默重建。
运行中断保留受管 checkpoint，恢复复用仍有效的 payload 身份和容量记录。

长 PA 输入复用[公共短路径支持](../../../common/simion/short_pa_path_support.ps1)；
先查[已关闭的长路径结论](../../../docs/SIMION_REFERENCE.md#长pa输入路径)，
不要另建项目私有实现。只读、Junction、硬链接或复制本身不保证 native family 写隔离。
published PA 不是 runtime 写目标；私有 family、standalone PA 的具体装配与封存由公共机制负责。
不反复复制／哈希已由受管只读机制保护的重型资产；容量、保留和清理由其唯一 owner 处理。

## 事件与分析

[mrtof_candidate.lua](mrtof_candidate.lua)及[mirror_cycle_counter.lua](mirror_cycle_counter.lua)
以 P2 后正镜转折定义快相位原点，后续每次真实镜转折增加半周期。
目标 K 与返回镜侧来自 `target_drift_period_ratio/fast_path_symmetry`，不在代码中固定数值。
中央 `z=0` 或提前 `y=0` 穿越仅作诊断；目标镜转折才产生严格相位返回。
返回应经 P2、必要的正镜转折后沿 `v_z<0` 命中 detector；只有解析镜区可以令 `v_z` 反号。

碰撞、程序拓扑拒绝、未知场支撑失败和未到达须分别报告，不能按终态坐标猜测部件。
缺 target-K 或完整返回的观察不得补造有效 Jacobian；完整通过与阶段观察分开保留。
`sim_segment_global=1` 用于捕获 PA 外终态，仍须逐粒子核对唯一结束和日志完整性。
[run_iob_flight.lua](run_iob_flight.lua)要求同名 Program/Fly2/operating-point/voltage-map/
mirror-cycle-counter 伴随文件，实际源必须匹配冻结字节；zero-exit 错误日志仍判失败。

```powershell
.\.venv\Scripts\python.exe -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis `
  '<run>/stdout.log' '<run>/event_analysis.json' `
  --input-manifest '<run>/simion/prototype_input_manifest.json' `
  --source-key mirror_internal_diagnostic_bunch_fly2
```

示例 source key 仅适用于对应镜内诊断源；必须换成本次实际源。
目标 K 只从冻结 derived 合同读取。源身份变化、无唯一完成记录、计数不符、
缺失／重复／未知 ID 或截断事件均拒绝 PASS；完整性失败时性能字段为 null，CLI 返回 FAIL/1。
完整性通过返回 PASS/0 只代表该层检查，不自动授予分辨率资格。

镜像非重合支路诊断只对精确返回且内部 fast-turn 数为 `2K-1` 的事件首尾配对；
报告 y、`z_return+z_outbound` 及速度反向残差，未收敛前不臆定物理容差。
源 z／能量／末段时序分析的出口统计包含全部冻结粒子，下游配对只使用真实完整事件，
损失继续进入终态统计。斜率、相关和增量贡献是描述性诊断，不等于因果归因。
FWHM、分辨率和统计资格使用[统一验证口径](../../../docs/OPERATIONS.md#通用验证口径)。

### 积分与脉冲边界

积分设置由 `trajectory_profiles` 派生；`-TrajectoryProfileId` 选择具名 profile，
`-TrajectoryStepScale` 或 screening 的 `-TrajectoryStepScaleOverride`
只能缩小最大步长作数值敏感性比较，不改变源、场或调度。
底层 `static`、仅 N=1 的 `initial_exit_triggered_single_center`、
`fixed_global_time` 三种模式互斥；静态场消费不能接受 OA pulse。

固定时钟通过 `-AcceleratorPulseSchedulePath` 读取身份收据；
`tstep_adjust` 落到计划边界，记录计划与实际时刻，电极实体和碰撞保留。
schedule 冻结要求全部粒子唯一负 z 安全出口，按 `max(exit)+guard` 派生；
`guard_us` 显式给定且覆盖 pilot 的最大步长，绑定 source cohort 和 solver problem。
源发布和 schedule 生成不证明真实脉冲已执行，也不授予整机性能资格。

## 历史与来源

旧局域五区／八实例、旧拓扑、逐轮 Jacobian、native 缓存修复和旧束团结果均为只读历史，
不能恢复为活动入口。完整整理前原文见
[场响应工程里程碑归档](../docs/history/20261008__field-response-engineering-milestone.md)；
其他历史入口由[项目导航](../README.md#历史补充索引)集中索引。
官方 API 与已验证公共边界见[SIMION 参考](../../../docs/SIMION_REFERENCE.md)；
本次结果只从实际冻结 manifest 和原始日志读取。
