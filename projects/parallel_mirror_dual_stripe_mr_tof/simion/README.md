# MR-TOF Candidate SIMION 路径

本页说明活动 SIMION 实现与操作边界；当前资格、有效证据和开放任务以
[项目状态](../docs/PROJECT.md)为准。项目只保留一条可执行整机路径：静态 P1/P2、关于 `z=0` 的非重合
镜像去回程，以及离子在 `z>0` 沿 `-z` 命中朝 `+z` 的探测面。首次安全离开加速器后禁止重入；旧的
沿 `+z` 穿过加速器命中、棱镜电压切换、回程进入 P1 和旧中央差分调压入口均已删除。旧 PA/IOB 不因
源码修复自动恢复有效性。

## 输入、坐标与几何

原生 response-bank 的下游工作点提议由
[`run_downstream_fixed_grid_workpoint.ps1`](../analysis/run_downstream_fixed_grid_workpoint.ps1)
消费五个 success manifest：`-BaselineManifest`、`-Stripe1PerturbationManifest`、
`-Stripe2PerturbationManifest`、`-Prism1PerturbationManifest`、`-Prism2PerturbationManifest`。
四个扰动必须各自只增加对应电压，并保持同一几何、源、镜、加速器、网格范围、时钟和目标 K。
界限、尺度和信赖步由 baseline 的 `downstream_fixed_grid_workpoint_profile` 派生，秩阈值复用
`dual_stripe_l0.determination_numerics`，命令行不接受数值覆盖。入口只读取并冻结观测和物化记录的
轻量消费投影，不重复哈希无关大 PA；发布完整 run 三件套及满秩、有界的四电压提议。
提议必须用已有 response 场重跑中心离子确认，既不触发 Refine，也不要求重建几何。

[`run_downstream_workpoint_iteration.ps1`](../analysis/run_downstream_workpoint_iteration.ps1)
把上述单步提议、已发布的 native response-bank 与 [`run_two_prism_trial.ps1`](run_two_prism_trial.ps1)
组成受管闭环。入口从一个已验证的 `downstream_fixed_grid_workpoint` manifest 和 native system runtime
bundle 开始；每轮只在 Fast Adjust 表中更新 S1/S2/P1/P2，执行一个真实中心粒子飞行，再由
[`downstream_workpoint_iteration.py`](../analysis/downstream_workpoint_iteration.py)解析四残差并选择只更新
P1/P2 或只更新 S1/S2。每个飞行都是独立 child run 和 manifest；父 workflow 保存前一 manifest、当前
child manifest、观测、native runtime bundle 身份和决策哈希链。每轮复用同一已封存 PA bank，不创建
局域工作台或 operating-PA cache。闭环只接受真实 target-K phase 样本及完整静态 detector
return；碰壁／错误拓扑、缺少 target phase、连续无改善、两点循环、振荡、步长过小、迭代上限、电压
边界或 solver 失败都会形成具名终态。循环上限、阻尼、接受门槛和停机控制只来自合同的
`downstream_fixed_grid_workpoint_profile.automatic_iteration`，命令行不能覆盖；该入口没有 Refine 路径。
若父 workflow 在一个 child 已发布 success manifest 后失败，必须使用新父 `RunId` 显式恢复。只有首轮 child
时可单独传 `-ResumeSuccessfulChildManifest`；任意后续轮则成对传入 `-ResumeParentCheckpoint`（旧父 run 路径或
manifest）和作为连续第 N 轮的 `-ResumeSuccessfulChildManifest`。恢复器不信任旧父散落的 decision，而是逐字节
核对冻结 proposal/Jacobian、合同和初始 manifest，再从连续的 1..N success child manifests 重放控制器并核对
已有 decision、物化电压、cache evidence 与 fixed-response 模式。新父从 N+1 开始，不重飞 1..N；同时继承最新
capacity baseline，并用最新 cache 的精确 retirement authorization 走增量容量快路。正常运行每次接受 continue
后立即写 lineage/history 并刷新 checkpoint manifest，旧父 run 保持原终态不变。

[候选合同](../config/simion_candidate_two_zone.json)提供物理输入和机械约束，
[resolved_geometry.py](../analysis/resolved_geometry.py)生成求解器无关的毫米几何，
[native_system_geometry.py](../analysis/native_system_geometry.py)派生 MR 静态角色的几何投影；full-corridor GEM 由[native_corridor_geometry.py](../analysis/native_corridor_geometry.py)直接派生。
项目坐标固定为：`z`是快速反射方向、`y`是慢漂移方向、`x`是横向聚焦方向；
`z=0`是中央注入／第一时间焦点交接面，不是最终质量焦点或必然的空间束腰。

加速器全局 y 位置由 `accelerator.focus_y_anchor.project_y_mm` 单独配置；它是 MR 装配变量，
不进入 OA provider PA identity，也不触发任一 PA 的构建、复制或 Refine。每次装配从 provider plan
读取实际局部 PA 原点和实体 y 外包络，再把该变量投影到 Workbench，并以 resolved Prism2 屏蔽件和
Stripe 几何失败关闭地检查净间隙。当前初值为 `-45 mm`：r3 加速器实体 y 上边界为 `-33 mm`，
Prism2 屏蔽件下边界为 `-32 mm`，保留合同要求的 `1 mm` 间隙；数值 PA 包络可重叠以支持优先级，
但导体实体不得相交。
已有 native corridor checkpoint 的复用身份只由该 PA family 的 cache key、generation 和成员哈希决定；
加速器或其他独立静态 PA 的 Workbench 位姿不是 corridor PA 的生成输入，因此改变 y 后必须新建 flight
身份和新算残差/Jacobian，但不得据此重建 corridor family。

GEM、PA、IOB和Workbench GUI只读地接受冻结输入，不持有下一轮可调几何真值。
`geometry_receipt`记录resolved几何哈希、坐标、单位、电极ID和孔槽；各组件必须来自同一合同。
五电极镜保留30-mm束槽、有限长槽及内侧开槽／外侧闭合盖板。四块Stripe对应两套电压组：
`(11,12) -> v1`、`(13,14) -> v2`；曲线由合同中的B-spline参数生成。
Stripe、中央接地件及棱镜屏蔽由完整实体扣除有限矩形槽，端部连接材料自然保留，不能另加任意桥接盒。
`grounded-1`为单一`e(18)`、`grounded 2`为单一`e(20)`；旧人工拆分ID19/21已退役。

加速器局部理论、几何、PA 和电压由独立的
`orthogonal_accelerator` provider 独占。MR 的
[accelerator_dependency.json](../config/accelerator_dependency.json)只声明接口需求；完整飞行只
消费 provider `mrtof_runtime_receipt.json`。离子从 exit grid 沿项目 `-z` 离开，出口、grid1、
repeller 依次位于更大的 `+z`；OA profile 派生局部外形、焦距和网格，MR 只选择独立 PA 的全局刚体 y
站位并执行装配净间隙门禁，不选择端部、环、壳体或孔径拓扑。

## Native runtime 的四个角色

活动轨迹场由同一 native system runtime bundle 组装，优先级固定为
`global_fallback → native_corridor → accelerator → detector`。它只复用封存输入，不能构建或
改写 PA。

|角色|来源|运行时用途|
|---|---|---|
|global fallback|MR 合同派生的只读分析器 PA|完整几何的低优先级兜底|
|native corridor|MR 全走廊八通道 response-bank|唯一可调的 S1/S2/P1/P2 Fast Adjust 场|
|accelerator|OA provider receipt|独占的两区 `-z` 加速场|
|detector|MR detector PA|数值终止面|

候选合同仍是 MR 自有几何、镜、Stripe、棱镜和 detector 的机器权威；native corridor 的网格与
范围直接由 resolved geometry 派生。加速器 provider profile 当前使用实心正 `z` 接地后盖与 repeller、
负 `z` 理想出口栅，以及紧凑的两区结构。MR 只声明 `r=1 mm/h=1 mm` 圆柱束团、两区时间聚焦、
`y/z` 紧凑化、数值包络和刚体站位；release 动力学只进入 flight，不进入 PA identity。

探测器GEM先用稳定ID25建立物质掩码；[build_component_pa.lua](build_component_pa.lua)在
`INITIALIZE=0`时以`pa:potential(x,y,z,0)`把所有节点电势置零、保留电极标志并保存原始PA。
因此原始ID值不会被当成25 V，且没有静电求解数组。它不是已验证的物理探测器；
原生终止与事件面的一致性必须随每次飞行检查；当前 N=1 证据见项目状态。

## 构建与重新加载检查

`run_native_corridor_response_bank.ps1` 是 MR 唯一的 PA 生成入口：它从 resolved geometry 生成
完整 corridor 的八通道 response-bank，并由公共 transaction 执行 Refine、最终 inventory、封存和发布。
`build_native_corridor_iob.lua` 只组装已封存的四个角色，在保存/重载时验证角色、位置、网格和优先级。
OA accelerator 从 provider receipt 读取，MR 没有 accelerator GEM、PA family、build staging 或缓存路径。

### Single full-flight corridor (current migration authority)

The detached bank runner `run_native_corridor_response_bank.ps1` can continue
an already-started bank with `-TransactionCacheKey <key>`. It retains that
transaction's frozen identity only while it is `building` without verification
or a generation. The current frozen inputs, SIMION identity and all PA-producing
builders must match; only the response receipt implementation may differ, and
both identities are retained in the continuation receipt. This exception ends
at publication and never permits changing physical inputs under an old key.
After publication, the same explicit key can be reused read-only with matching
frozen scientific inputs; recovery options are rejected and no build or full
PA scan is performed. Run finalization still applies the normal retention contract.
`-RecoverMembers <explicit names>` submits receipt/inventory mismatches to the
common owner through `advance-transaction --member-recovery`; the owner journals
the request and invalidates only those members and the dependent receipt.
Unchanged arrays remain in place. The normal missing-member build path then
rebuilds native members or re-exports detached members as needed, writes the
receipt from persisted bytes, seals and verifies the bank before publication.
Capacity admission initially counts the resident payload once and reserves the
missing bytes after owner invalidation; it does not request a second full bank.
New builds and explicit member recovery now pass a response-receipt recipe to
the existing common transaction owner. The owner flushes and hashes PA data
once under its lock, makes it read-only, derives the receipt from that same
inventory, and hashes only the small receipt afterward. Legacy transactions
already carrying a receipt continue their existing seal; they are not restarted
to adopt this optimization. SIMION format/response verification remains required.
Large Windows PA inventories now use the explicit unbuffered SHA reader after
producer completion and flush, rather than the stale buffered view encountered
on this host. If retained members disagree with an older valid inventory,
`-RecoverRetainedInventoryMembers <names>` invokes the common owner's narrowly
scoped inventory repair: only unchanged members in the original recovery
journal qualify, each must reproduce its old identity through a read-only `/J`
snapshot, and only inventory records are updated atomically. No PA/receipt is
deleted, rewritten or refined; this mode refuses to enter the build path.

`-CorrectPublishedInventoryMember <exact name>` requests a separate owner
correction for a published inventory error proven against the original retained
member journal. It cannot be combined with member rebuilding. The runner passes
the active capacity lease and preserves the owner's correction proof in its run;
it must never enter PA construction or reopen published native members in SIMION.
The prior real format verification is retained as prior evidence, not reported
as a new solver run. The owner must provide the corrected successor before this
runner can report success.

`run_two_prism_trial.ps1` consumes a published native bank together with its
`-NativeSystemRuntimeBundlePath`. The bundle binds the global fallback,
accelerator, and detector by their verified manifest identities without PA
copying or rehashing. `native_corridor_runtime_support.ps1` constructs the
private controller and streams the eight native responses. The four-instance
IOB uses accelerator instance 3.

`analysis/run_native_corridor_bunch_screening.ps1` reopens the checkpointed
native runtime once for the N=100 static pilot and, only after its collection
gate passes, the N=1000 fixed-clock cohort. A hard-stop first runs the bounded
theory Stripe pair; if neither candidate clears the gate, it automatically runs
two independent reverse S-axis probes from the same accepted anchor. P1/P2 stay
fixed, all completed candidate manifests are reused, and the stage plans,
ranked observations, and selections remain manifest-bound evidence. Only an
event-valid candidate above the hard collection minimum can reach the clock and
N=1000 stages. This continuation does not rebuild, copy, Refine, or materialize
the native PA family.

The existing `analysis/run_downstream_workpoint_iteration.ps1` accepts the same
bank parameter. Supply either a same-bank `-InitialWorkpointManifest` or
`-SeedTrialManifest`: the latter reuses only the seed voltage vector, launches a
new native baseline and four positive single-axis perturbations, then calls the
existing fixed-grid audit and iteration controller automatically. Its named
consumer projection verifies and freezes only the voltage materialization and
run metadata; unused historical seed PA files are not inputs to this workflow.
Stencil steps
come from `downstream_fixed_grid_workpoint_profile.forward_stencil_steps_v`,
initially 0.1 V per axis as used by the successful historical r2 audit. A failed
child stops the stencil; native bank key/generation bind the Jacobian, children,
and checkpoint. N100/N1000 source, pulse and batch continuation are not yet
automatically connected to this parent; the checkpointed bunch-screening
consumer is the separate continuation boundary.

The automatic parent owns one private native runtime family across its baseline,
stencil and iteration children. The family lives inside its owner run; the common
execution alias supplies its short SIMION path. Nine read-only file handles stay
open during the workflow. Each child builds its small IOB/companions and applies
the complete voltage table in memory during flight. The IOB builder validates
all eight finite voltage entries and reloads the saved IOB for geometry/priority
checks; it does not perform an unused adjustment before the flight repeats it.
Save the IOB before Fast Adjust: SIMION
Workbench save can otherwise attempt to write dirty PAs even with exit code zero.
The runner rejects the corresponding error log as a failed stage.
The native flight callback submits the eight-channel voltage table only on its
first call or when a value changes; a new Fly run resets this comparison. This
keeps interactive voltage changes and the accelerator field gate active without
resubmitting unchanged native voltages at every integration callback. Actual
submissions report `MRTOF_NATIVE_FAST_ADJUST begin/complete`.
The trial runner drains both solver output streams while running and flushes
every line to the stage log. The console shows loading, adjustment, turn and
terminal milestones, plus a 30-second heartbeat with elapsed time, CPU time and
the latest important event. Routine trajectory records remain in the complete
log; zero-exit solver error messages still fail the stage.
Lua flushes output after actual adjustment milestones and each mirror-turn
event group, using the [standard Lua interface](https://www.lua.org/manual/5.1/manual.html#pdf-io.flush)
supported by [SIMION](https://simion.com/issue/486); it does not flush each integration step.

Execution failure retains the family under a nonterminal parent checkpoint,
records actual bytes through the existing capacity owner, and releases handles,
alias and lease. The remaining allocation excludes the registered resident
family. Recovery uses a new parent RunId and `-ResumeParentCheckpoint`; native
seed bootstrap can recover before its first successful child. The original owner
path remains protected, without another copy. Recovery checks bank identity,
the two family-generating Lua scripts, SIMION binary and all nine member hashes
under read-only guards. IOB code and voltage changes do not invalidate the family.
Subsequent children in that active session do not repeat the payload hash scan.
An identity mismatch preserves the payload and stops; it never silently rebuilds.
After consumption finishes, the owner cleans the family before terminal retention.
The Jacobian audit inherits the workflow capacity session. Published bank members
are never runtime targets, and no hard links are used.

The earlier five-cropped-region native experiment is not a valid production
family: an individual crop can omit physical adjustable IDs.  The only new
candidate is therefore one full-flight corridor family whose controller
contains real local IDs 1..8.  `derive_native_corridor_plan` derives its
preferred box from the resolved patch envelopes; the current candidate is
`x=[-20,20] mm, y=[-147,463] mm, z=[-330,330] mm`.  The wider
`x=[-29,29] mm` union is retained only as a probe/comparison profile.

The family is exactly `mrtof_analyzer_corridor.pa#`, `pa0`, and `pa1..pa8`.
`run_native_corridor_qualification.ps1` is the sole workflow orchestrator.  It asks the common
PA-family transaction for its next action, emits the physical-ID GEM from the
resolved geometry, remaps it to local IDs 1..8, and writes only the reported
missing members through deterministic transaction scratch before atomic member
placement.  The transaction owns the payload, scratch, inventory, parity,
publication pointer, capacity-ledger handoff, and cleanup; the project runner
does not delete or retain a second PA copy.

Physical geometry and the controller remain dependency-ordered serial steps.
Each missing `pa1..pa8` response then uses its own deterministic scratch
subdirectory and its own public `SIMION/dirichlet_response_refine` admission;
all workers may queue together, while the repository host scheduler alone
decides how many actually run.  A worker atomically moves only its completed
member into the common transaction payload, so later retries reuse completed
members and never rebuild the whole family after one sibling fails.

The common transaction has only `building`, `prepared`, `published`, and
`retired` states.  Every response member is normalized to the native SIMION
Fast Adjust reference of `10000 V`; a `1 V` response file is not a valid native
`.paN` member.  The runner first exercises two nonzero eight-electrode voltage
tables, including close/reopen, on the exact private family.  It then creates
the final persisted inventory, seals the members read-only, binds that inventory
to the verification evidence, and atomically publishes the generation.  The
family is deterministic and reconstructible from the frozen geometry and
coarse response identity, so it uses the common `none_reconstructible` recovery
policy rather than keeping an additional XOR payload.  Final inventory is the
single full-byte publication read; publication itself checks exact names,
lengths and sealed state without hashing the same multi-gigabyte files again.
The published generation is pinned with reason `MR-TOF native adjustable
analyzer PA family; rebuild only on frozen geometry identity change`.
Repeating the same frozen identity automatically resumes partial building,
verification, publication, or pointer/ledger completion.  One OS-exclusive
per-key writer handle spans a cache-miss transaction and is released
automatically if the process exits; a published cache hit does not acquire it.
The project carries no second lifecycle metadata, random staging name, or
manual recovery parameter.

`build_native_corridor_iob.lua` uses the four-instance seed with the explicit
priority contract `global_fallback → native_corridor → accelerator → detector`.
The contract table is not treated as proof of GUI priority: after save/reopen,
the builder probes real overlapping AABBs through `wb:find_at` for
global∩corridor, corridor∩accelerator, and global∩detector.  SIMION 2020 has no
documented writable `instance.priority` field in the supported Lua API; if no
candidate field is exposed, the probe result is the authoritative check.
The corridor receives the complete Fast Adjust table for IDs 1..8 in one
operation; no per-crop scalar adjustment, PA save, or Refine is allowed.
The old five-region handoff and fixed-operating executables have been atomically
retired.  Historical evidence remains under `docs/history` and prior run records;
no active entry point can select those paths.

The runner consumes one frozen input directory containing the common-cache
identity, derived plan, coarse-basis recipe, and freeze manifest.  On a cache
hit it performs no GEM, basis, Refine, or PA copy.  On a miss it retains only a
small SIMION verification log and ordinary run evidence; all reusable heavy
bytes remain under the one common transaction/generation authority.

The first corrected 10-kV-reference Candidate was published as cache key
`C4F9B280FD7D748BF1AEBC528C038D76FA0E66A142F0D6246B1D7D6AED480BDE`,
generation
`6DD407E10A03E4B85BC5775A3351942D9E81CCE4C56D1E8915778942D88735F3`.
Its 27-probe and two-voltage-table SIMION verification passed.  This establishes
native-family construction and Fast Adjust semantics only; materialized IOB
equivalence and flight qualification remain Candidate work.

活动入口只使用 full-corridor native response bank。历史 pilot 组装器及其独立暂存路径已删除；原生
family 由受据保护的 native runtime 在私有工作目录创建，已发布 generation 从不被 SIMION 原位写入。

原生 response-bank 的唯一项目 identity 入口是
[`native_corridor_identity.py`](../analysis/native_corridor_identity.py)。它只描述完整八通道
native corridor family；内容寻址、最终 inventory 和原子发布均由公共 PA
transaction 执行。加速器不属于此缓存：运行时只消费 OA provider receipt。新的 IOB 只由
`build_native_corridor_iob.lua` 从已封存的 global fallback、native corridor、provider accelerator
和 detector 组成四实例系统，并在保存/重载时验证角色、位置、网格与重叠优先级。它不会保存、
复制、Refine 或重新哈希已发布 PA。

GUI 审查包由 native system runtime bundle 生成，并绑定上述四个冻结输入；不再发布局域五区或
三组件工作台。

`run_two_prism_trial.ps1 -RetainGuiWorkbench` 以 `solver_review` 在本次受管 run 的
`simion/gui_workbench/` 写入 IOB 与所有非 PA 伴随文件。IOB 在飞行后重绑到已发布的稳定只读
PA，临时 PA 投影随即删除；收据只复用 runtime／provider 身份，不为 GUI 包递归枚举或
重哈希 PA。N=100 和 N=1000 串团飞行默认开启此开关，因此不再随运行时临时目录丢失小型 GUI 审查包。
GUI 关闭后由该 run 的 owner disposition 路由退休。

单中心时间步三档对照由
[single_center_timestep_convergence.py](../analysis/single_center_timestep_convergence.py) 及受管入口
[run_single_center_timestep_convergence.ps1](../analysis/run_single_center_timestep_convergence.ps1) 完成。
分析器要求三个 success run 的几何、PA、电压、源、程序、脉冲和自然回程身份完全相同，只允许最大
trajectory step 不同；它报告目标 K 返回、正镜回程转折和最终探测终态的完整相空间差值，不自行设置
通过阈值。当前三档结果见项目状态页。

## 粒子来源与事件分析

materializer在schema3的`prototype_input_manifest.json`中为每份具名诊断Fly2分别冻结
`source_profile_id`、`particle_count`、`particle_count_contract_key`、`expected_particle_ids`及其SHA-256，
并绑定Fly2和derived合同的SHA-256。ID由单个standard beam的合同粒子数派生为`1..N`；
分析不能从已记录终态数反推母粒子数。

|manifest source key|生成的Fly2|当前用途|
|---|---|---|
|`mirror_internal_diagnostic_center_fly2`|`mrtof_mirror_internal_diagnostic_center.fly2`|分析器内直接释放的4-keV单粒子；只隔离诊断mirror/Stripe|
|`mirror_internal_diagnostic_bunch_fly2`|`mrtof_mirror_internal_diagnostic.fly2`|同一镜内诊断态的固定合同小束团；不是整机源|
|`accelerator_focus_center_fly2`|`mrtof_accelerator_focus_center.fly2`|第一区release平面的零KE中心粒子|
|`accelerator_focus_bunch_fly2`|`mrtof_accelerator_focus.fly2`|第一区内零KE轴向释放位置表；用于检验第一时间焦点|
|`first_prism_entry_center_fly2`|`mrtof_first_prism_entry_center.fly2`|两区焦面处的4-keV中心粒子；仅首棱镜有限三维射击诊断|
|`full_mrtof_center_fly2`|由已审计P1/P2工作点按run局部生成|完整源→P1→负镜预反射→P2→P2后参考截面→正镜转折(`y=0`)→Stripe→静态自然回程→探测器；N=1/N>1均走同一完整三维事件链，仍不授予性能资格|

当前首轮物种为524 Th／+1，中心源N=1、小束团N=100。加速器设计合同把可接受的加速轴
`z`完整释放宽度冻结为`accelerator.design_source_acceptance.axial_full_width_mm=2.0 mm`，即当前6-mm
第一区内以3-mm释放点为中心的`2..4 mm`。加速器焦点束团把该完整宽度均匀离散成100个确定释放位置，
每个位置各用一个`n=1` standard beam，避免SIMION随机圆盘分布掩盖轴向导数。实际整机束团则由独立
source-definition文件声明`x/y/z`、能量、角度、粒子数和共同出生时刻；改变这些源分布只重建粒子表和
必要时的脉冲收据，不改变PA-family缓存。若理论重新选择加速器电压，只生成由响应基底线性组合的
新operating PA缓存，也不重新Refine几何响应族。
此前100 Th输入仍属独立回归/历史证据，不与新首轮束团混合统计。
镜内两种源绕过加速器和P1/P2，仅保留为部件隔离诊断，不能用于整机传输、探测TOF或分辨率。
加速器焦点两种源是静态电压下
从第一区由静止释放的独立诊断；轴向N=100源可测量有限宽度的一阶斜率、二阶曲率和时间极差，
但不代表真实脉冲源分布。
所有具名源不能合并统计或彼此替代；schema2旧名称仅供既有run只读分析。

有实际飞行日志后，从仓库根使用[simion_event_analysis.py](../analysis/simion_event_analysis.py)：

```powershell
python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis `
  '<run>/stdout.log' '<run>/event_analysis.json' `
  --input-manifest '<run>/simion/prototype_input_manifest.json' `
  --source-key mirror_internal_diagnostic_bunch_fly2
```

路径应指向本次实际冻结文件；`--source-key`必须与实际飞行源相符。目标K只从已校验的derived合同读取，
不再接受独立`--target-k`默认值。源文件／合同身份改变、无唯一Fly完成记录、完成计数不符、
缺失／重复／未知粒子ID或截断事件都会拒绝PASS。保留原始诊断计数与到达时间，完整性失败时
检测率、目标K比例、FWHM和分辨率为`null`，CLI返回`FAIL/1`；只有完整性通过才返回`PASS/0`。
旧schema日志只能只读诊断，不能通过补造新source manifest恢复当前运行资格。
精确目标K相位返回时，事件分析另将两个端点之间的`2K-1`个内部`fast_turn`首尾配对，输出
`mirrored_nonretracing_branch_turn_diagnostics`：同一y残差、`z_return+z_outbound`及速度反向残差。
它验证关于`z=0`的两条非重合镜像支路；未精确返回或内部转折数不是`2K-1`时拒绝配对，数值收敛前不赋容差。

## 飞行与求根入口

所有入口从已审计 run 消费冻结合同、源与 PA 身份；参数说明直接查看对应脚本的 `param` 定义。
以下入口具有不同资格，不能互相替代。仅以代码格式出现而没有链接的名称尚未随当前 Git 修订发布，
不能作为当前可调用入口。

| 任务 | 受管入口 | 结果范围 |
|---|---|---|
| provider-owned N=100 两区组件飞行 | [run_accelerator_component_provider.ps1](run_accelerator_component_provider.ps1) | 只请求并消费 provider 的统一 receipt；不构成 P1/P2、整机返回或分辨率资格 |
| N=1 或 N>1 完整飞行 | [run_two_prism_trial.ps1](run_two_prism_trial.ps1) | 四残差与 `P2 → 正镜 → z>0,v_z<0` 静态回程观测 |
| N=100 冻结束团源发布 | [run_publish_bunch_source.ps1](../analysis/run_publish_bunch_source.ps1) | 只生成 CSV/Fly2/receipt，不运行 SIMION |
| N=100 全局关断时钟冻结 | [run_freeze_bunch_pulse_schedule.ps1](../analysis/run_freeze_bunch_pulse_schedule.ps1) | 消费同源 static pilot 的完整安全出口队列，不运行 SIMION |
| N>1 源 z—能量—末段时序诊断 | [run_source_z_energy_timing_diagnostic.ps1](../analysis/run_source_z_energy_timing_diagnostic.ps1) | 只读消费完整 success flight，不启动 SIMION；输出 compact Candidate 诊断 |

源 z 诊断入口复用飞行 manifest、冻结源表、原生事件解析、公共容量和 retention 合同；末段只比较实际发出的正镜转向和沿 `-z` detector plane 事件，不依赖已退役的五区 patch-interface 交接。单日志与按 receipt
重编号的 batch 日志均须完整覆盖 `1..N`。安全出口时间和轴向动能统计使用全部冻结粒子；target-K、
P2 前后、额外正镜转折和探测器的配对时序只使用具有完整事件链的全部探测命中。碰撞粒子继续进入终态
计数和事件覆盖，不允许删尾、源筛选、峰筛选或把缺失下游事件补零。输出的斜率、相关、FWHM 和有符号
增量贡献仅是描述性 Candidate 诊断，不构成因果归因、去趋势许可或分辨率资格。

## 事件与脉冲合同

[mrtof_candidate.lua](mrtof_candidate.lua)与[mirror_cycle_counter.lua](mirror_cycle_counter.lua)以 P2 后正镜
转折定义快相位原点；每个后续真实镜转折增加半个周期。baseline 的
`target_drift_period_ratio` 与 `fast_path_symmetry` 唯一派生目标半周期数和返回镜侧，不在 Lua 或 Python
中固定某个 K。当前 25.5 自动对应 51 个半周期和负镜返回；改为另一正半整数不需要修改代码。
解析电压链使用 `analysis/run_target_operating_point_chain.ps1`，从同一 baseline 自动串接镜 exact-K
工作点和双 Stripe 反演；SIMION 只消费其后 materialize 的电压 receipt，不另存几何或 K 参数。
P1/P2 继续复用已有的
`analysis/run_two_prism_segmented_coverage.ps1`、`analysis/run_two_prism_segmented_continuation.ps1` 和
`analysis/run_two_prism_operating_point.ps1`。coverage 可直接消费固定三维镜/可变慢能 Stripe manifest，
默认从 baseline 读取初始有符号电压域；continuation 只追踪 coverage 冻结的单一事件签名；真实三维
trial 的两个单轴扰动和后续迭代由 operating-point 审计检查秩与共同冻结输入。不得为当前镜点另写第二套
P1/P2 搜索器，也不得把理论覆盖点直接称为三维工作点。
中央 `z=0` 穿越及提前出现的 `y=0` 只报告诊断，达到目标负镜转折才产生严格相位返回事件。实际坐标
残差与相位返回分开报告，目标事件不切换棱镜电压。
P1/P2 始终保持注入态；trial runner 已删除棱镜提取态与切换时刻公开参数，Lua 与分析器仍会对旧 receipt/sidecar 中非空切换字段失败关闭。
目标负镜转折后，离子以 `v_z>0` 自然通过 P2，再由必要的正镜转折把方向变为 `v_z<0`，随后直接朝
正 z 半空间内、法向为 `+z` 的检测面飞行；P1 只属于注入支路。Stripe、P1/P2 和漂移区不得改变
`v_z` 符号；只有
已解析的镜区转折可以反号。

删除旧拓扑入口后的真实 SIMION 2020 回归
`20260915_223500__sim__simion__mrtof-single-current-only-path-n1-r26` 已通过：中心离子达到
`K=25.5`，自然通过回程 P2，经正镜转折后在 `z=97 mm`、`v_z<0` 命中检测器，TOF 为
`789.250482694 us`；未出现回程 P1、加速器重入或棱镜电压切换。飞行入口现在只生成
`complete_three_dimensional_static_return`，旧截断和 x 对称约束字段不再接受为当前收据。

同一入口的当前代码 N=100 复核
`20260915_231500__sim__simion__mrtof-bunch-current-only-path-n100-r27` 完成 100/100 粒子并保持
100/100 目标 `K=25.5`、88/100 探测命中、12/100 真实电极碰撞。`-BunchParticleIdMin` 与
`-BunchParticleIdMax` 只允许从一份已验证冻结源收据选取连续区间作诊断；它不建立第二 runner，局部 SIMION
ID 在日志合并时严格恢复为原全局 ID，结果标记为非 Formal 的 source-selection diagnostic。
`-TrajectoryStepScale` 只可在 `(0,1]` 内缩小合同具名 profile 的最大步长。临界 ion 97/98 已分别以
`0.002 us`（r28）和 `0.001 us`（r29）复核，均保持 97 在 electrode-20 的 `z=-97 mm` 孔唇碰撞、
98 通过；因此后续应改善返回包络，不改动已加工孔径或过滤源粒子。

加速器有 `static`、仅 N=1 的 `initial_exit_triggered_single_center` 和 `fixed_global_time` 三种互斥模式。
固定时钟必须通过 `-AcceleratorPulseSchedulePath` 消费冻结收据，在共同 `tob=0` 的 `ion_time_of_flight`
上关闭 standalone 加速器实例的电场；`tstep_adjust` 落到计划边界，事件记录实际与计划时刻。电极实体与
碰撞几何始终由同一 PA 保留。禁止用裸时间参数替代身份收据。
[bunch_source_and_schedule.py](../analysis/bunch_source_and_schedule.py)提供求解器无关的确定性母束团前缀、
逐粒子唯一 `accelerator_safe_exit` 检查、`max(exit)+guard` 推导和 N 粒子共同关断事件校验。
[candidate_bunch_source_n100.json](../config/candidate_bunch_source_n100.json)冻结当前 Candidate 束团：
母队列 `N=1000`，前 `100` 行作为完全相同的 pilot 前缀；圆柱轴为项目 `y`，高度 `1.0 mm`，
`x-z` 截面半径 `0.5 mm`。能量为固定镜/Stripe exact-K handoff 选择的
`4.961131692 eV` 慢能中心及 `0.1 eV` 全宽、角度 `0.2 deg`；源中心相对加速器机械轴的
`y=-1.710934847 mm` 偏移来自真实出口慢向速度割线和独立出口验证。该源定义及其展宽与 PA/cache
身份完全解耦，改变粒子分布不触发 Refine。
物种为 `524 Th/+1`、共同 `tob=0`。schema-4 源定义不保存绝对释放坐标或三维偏移魔数；它声明
`resolved_provider_accelerator_release_position`及具物理校准依据的 y 偏移。发布入口从 MR 几何合同解析
全局 y 位姿，从同次 OA provider receipt 解析 `repeller_to_exit-release_position` 的 z 释放位置，并写入收据。
源定义及其采样状态不参与PA-family或operating-PA缓存身份。
[run_publish_bunch_source.ps1](../analysis/run_publish_bunch_source.ps1)把完整定义、MR 几何合同和 OA provider
receipt 复制为 run-local 输入并发布 N=1000 CSV、逐粒子 Fly2 与 receipt，全程不运行 SIMION。N=100 pilot
只选择该母队列的前缀。历史较小源已由唯一完整飞行入口通过公共
资源调度器执行 static pilot：100/100 粒子安全出射并达到目标 `K=25.5`，88/100 命中检测器，12 粒子发生
真实电极碰撞；这只证明静态 Candidate 束团链和事件完整性，不是固定时钟或分辨率资格。
[run_freeze_bunch_pulse_schedule.ps1](../analysis/run_freeze_bunch_pulse_schedule.ps1)是后续 static pilot 的
独立冻结边界：它完整验证 source/pilot 两份 manifest，要求 trial receipt 和原始日志确属 pilot 输出，
再对 N 个粒子的唯一负 `z` 安全出口逐一对账。`guard_us`没有脚本默认值，必须由调用者显式给定并写入
run config；其值至少覆盖 pilot 的一个冻结最大轨迹步。输出 schema-2 schedule 同时绑定 source cohort、
solver problem identity 与 `max(exit)+guard`，但本入口本身不飞行，也不证明固定时钟已在 SIMION 中执行。

`sim_segment_global=1`用于覆盖 PA 外终态；仍须逐粒子对账、唯一成功终止和原始日志完整性。
[run_iob_flight.lua](run_iob_flight.lua)要求 IOB 同名 Program、Fly2、operating-point、voltage-map 和
mirror-cycle-counter 伴随文件；实际源必须与冻结 Fly2 字节一致。旧不完整日志不能补造资格。

## 数值执行边界

积分设置只由候选合同的 `trajectory_profiles` 派生；入口选择 ID，不接受游离时间步。
原生 corridor response-bank 是分析器的唯一可调场输入。它与冻结的加速器和探测器 PA 由系统运行时 bundle
一起验证和投影；电压调整只复用已发布响应，不重新构建局域分区或合成五份 operating PA。

## 缓存、短路径与发布

原生 corridor response-bank 是唯一的工作点场缓存；私有 runtime family 仅从其已封存响应装配，
不再合成或发布五区 standalone operating PA。

只读、Junction、硬链接以及完整复制后的 family 都不是 SIMION family 写入的隔离边界。长路径输入通过
[公共 short_pa_path_support.ps1](../../../common/simion/short_pa_path_support.ps1)生成 manifest-bound、可丢弃且
无 `.paN` family 语义的独立短路径副本。原生 family 操作仅允许在新建 family 的一次性 build staging 中发生；
已发布 cache 及其物化副本中的 `.paN` 均不得由 SIMION 打开。interface/portal convergence 也只逐项复制
standalone response 与中性名 raw mask，绝不把 generation 路径或目录别名交给 SIMION。每次复制都携带 manifest
的 `bytes/sha256`；Windows 大 PA 以 `/J` 私有目标核验，普通缓冲源哈希只作诊断，不作为持久字节权威。
同 key 重建后从 `current_generation.json` 解析当前 generation，不修改旧 run 收据，也不依赖其失效的物理目录。

容量预检和终态门禁保护所有使用中的 generation 与 cache key，清理规则只由公共层维护；见
[公共 SIMION](../../../common/simion/README.md)与[运行规范](../../../docs/OPERATIONS.md)。
长 PA 输入和缓存回归只证明执行路径，不授予任何物理性能。

该链的真实闭环证据为：r135 成功发布/命中 reviewed source generations；r137 从同一 15 件受保护输入完成
`mirror_turn_negative, scale=0.5` 的 Refine 与发布；r138 直接命中同一局域 cache；r140 又经 batch 入口完成
同一区命中，未复制源、未调用 SIMION 或 Refine。r133 的空电极 19 导出错误和 r134 的 retention 输入错误均为
已修正的失败证据，不得写成成功。当前 r51 的 22 件 native family 只读复核为 22/22 与冻结记录一致；先前瞬时
读差异没有已确认写者，也不能归因于 SIMION。r41 继续作为本链可靠完成验证的 provider。

### 已退役的八实例工作台（冻结历史）

以下记录仅保留历史 PA 隔离与输入链证据。对应五局域／八实例组装器和运行入口已删除，不能用于
当前 native corridor 工作流。

当前受管重建链为 r88--r90 的三个逐字节复现 generation、r91/r92 的两个 cache-hit provider，以及工作台
`20260917_010000__build__simion__mrtof-local-r55-detached-r94`。r94 的 IOB 仍只含全局分析器、五局域替代、
独立加速器和独立探测器八个运行 PA；原路径和长 artifact 路径检查均通过，且在检查后删除十个仅用于载入
seed 的 placeholder `.pa0`，共 `164034040 bytes`，清理收据保存在 run config/summary。此前工作台
`20260916_231000__build__simion__mrtof-local-r55-detached-r85` 和飞行
`20260916_235000__sim__simion__mrtof-r55-detached-flight-r87`。r87 的 compact IOB 只在临时目录绑定八个
短路径副本，飞行后删除；其 success manifest 保留上游 standalone PA 身份、实际日志、观测和本次 sidecar。
已封存 r85 不做原位修改。

## 历史与来源

旧几何审查、r50 首次自然命中、已删除的棱镜切换支路、局域网格试探和逐轮 Jacobian 记录统一见
整治前两页原文快照候选 `20260911__project-and-simion-status-freeze.md`；该快照尚未随当前 Git 修订发布。
官方 API 用法查[SIMION 参考](../../../docs/SIMION_REFERENCE.md)；执行结果只从本次受管 manifest 与日志读取。
### N>1 automatic single-wave dispatch

跨项目并行规则统一见 [SIMION Fly'm 粒子并行规范](../../../docs/SIMION_REFERENCE.md#flym-粒子并行规范)；
本节只记录 MR-TOF 映射和物理门禁。

`run_two_prism_trial.ps1 -BunchSourceReceiptPath ...` remains the only full-flight
runner.  It verifies that the receipt, state table, and full Fly2 are unique
outputs of one successful source-run manifest.  The repository resource
scheduler consumes historical exact-identity profiles when available; otherwise
the first ten percent of the cohort is retained as formal work, observed for the
repository 45-second window, allowed to finish, and used to replan the remaining
single wave.  No project-local worker count or CPU floor exists.

Each planned batch is one contiguous global particle-ID interval and keeps the
source's common `tob=0`.  SIMION sees local IDs `1..n`; merge uses only the
planner's `simion_particle_id_offset`, rejects incomplete/overlapping coverage,
retains every non-completion line, and emits exactly one global Fly-completion
sentinel before the ordinary cohort analysis.  All workers reuse one read-only
IOB with the same four roles: global fallback, native corridor, provider
accelerator and detector.  A worker differs only by its `--particles` Fly2
slice; no batch copies, composes or Refines PA, and no batch rebuilds an IOB.
Capacity is reserved once for the protected runtime family.  The run manifest
binds the source manifest, scheduler request/profile/plan, particle-batch plan,
resource usage, merge receipt and retained raw logs.
