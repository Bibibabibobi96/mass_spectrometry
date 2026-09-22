# 机器合同与设计请求

本目录保存跨项目的机器合同 Schema、语义校验器和可追溯规划工具。JSON Schema只判断字段、类型、
单位是否完整；Python语义层判断项目选择、能力成熟度、模式、指标、设计变量和约束是否成立。
二者不能互相取代。

## 运行身份与生命周期

`canonical_clock_authority.py`与同名Schema定义跨项目事件链唯一instrument clock权威：求解器局部时钟
从零累计，adapter仅一次物化`epoch + elapsed`，handoff保留时间戳；新run不得使用legacy相对时钟旁路。

`artifact_project.py`统一artifact项目根索引，`particle_state.py`统一SIMION/COMSOL适配后的粒子事件字段、
身份、三维位置/速度、全局时间和RF相位校验；`run_artifact_support.ps1`统一PowerShell运行器创建目录、
冻结输入、失败收尾和三件套manifest。它们不得内置器件参数，项目包装器只允许保留兼容入口。
`Copy-VerifiedRunInput`默认保持单次严格复制；对数百MB至GB级solver数组，调用方可显式设置
`-VerificationAttempts 3`，每次都要求复制前源、复制后源和目标SHA-256三方完全一致；首轮普通复制
失败后，后续轮次使用8-MiB显式流、write-through和磁盘flush。该选项只容忍可重试的本机大文件复制
抖动，不会把持续变化的源或坏副本降级为成功。
需要规避 Windows 路径深度的外部运行器可在`New-RunPackage`显式选择`-UseShortExecutionPath`。公共层会从
`MASS_SPECTROMETRY_EXECUTION_ROOT`（未设置时`C:\tmp\ms`）创建一次性短 junction 指向最终
`artifacts/.../runs/<run_id>`；运行器把短路径仅作为进程工作路径，并在终态后调用
`Remove-RunPackageExecutionAlias`清理它。实际文件从未搬离最终run，Python manifest解析 junction 后记录真实
artifact路径，因此run ID、输入/输出身份、SHA和历史引用不变。不能以复制后回迁或只缩短某个求解器子目录
替代该合同。该 junction 仅指向本次可写 run；SIMION 外部只读 PA 输入另用[已验证普通副本机制](../../docs/SIMION_REFERENCE.md#长pa输入路径)，不得用此别名暴露不可变 PA 源。
`file_identity.py`是SHA-256身份的唯一共享实现，固定返回大写十六进制。`file_sha256`按原始字节标识
manifest、正式资产和外部artifact；`repository_text_sha256`只用于Git治理的文本依赖，先把行尾规范为
LF，从而使Windows工作树与干净checkout得到同一身份。调用者仍负责路径范围、字节数和证据资格。

大PA的owner可显式调用`file_sha256_unbuffered`，默认`file_sha256`不变。该入口仅支持Windows 8+，
以只读且仅share-read的`CreateFileW`句柄、`FILE_FLAG_NO_BUFFERING`、实际存储扇区信息和对齐的
`VirtualAlloc`缓冲区顺序读取一次；尾块请求按扇区向上取整，只哈希`ReadFile`实际返回的文件字节。
无临时全文件副本、无源写入或flush，API/短读/未知对齐失败不回退普通读取。调用者必须先确认求解器
已经完成且无活动映射写入者；不同视图的哈希不一致仍是身份失败，不能选一个能匹配旧清单的值当成功。
这只绕过Windows系统数据缓存，不保证硬件缓存已持久化，也不把无缓冲结果自动升级为发布资格。

官方接口核查（Microsoft Win32，Windows 8+/Server 2012+；查阅2026-09-21）：
[File buffering](https://learn.microsoft.com/en-us/windows/win32/fileio/file-buffering)定义无缓冲尺寸、地址对齐和硬件缓存边界；
[CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)定义只读/share-read打开；
[FILE_STORAGE_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_storage_info)及
[GetFileInformationByHandleEx](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getfileinformationbyhandleex)提供同一文件句柄的扇区信息；
[VirtualAlloc](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-virtualalloc)提供可显式对齐的内存；
[ReadFile](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-readfile)定义同步读和跨EOF尾读。
这是基于官方API的项目SHA-256实现，用于显式核对异常的大文件缓存视图；不支持这些接口的存储失败关闭。

`verify_run_manifest.py`默认且在发布时始终复核run config、全部输入、全部输出和适用的保留合同。已经冻结的
历史run若有不再被下游读取的大型记录丢失或损坏，下游可用具名`--consumer-projection-id`，并逐项提供
`--consumed-input NAME PATH`／`--consumed-output PATH`；入口仍复核manifest状态、run config、项目／模式等
约束，并把每个实际消费路径唯一绑定到manifest记录后核对字节数和SHA-256。投影不得用于发布或宣称整个
上游run仍完整有效；消费run必须在自己的run config记录投影ID、记录名、路径以及未断言其余记录。选择器
缺少投影ID、空投影、路径不一致、重复记录或消费记录漂移均失败关闭。

`recorded_file_removal.py`只负责已预检清单的逐文件身份重验、删除及可刷新落盘的JSON记录，不扫描或
选择待删对象。容量、run retention和solver-review退休各自决定准入并先发布pending；迭代器每删除一项
返回该记录，由调用方保存原有进度和终态语义。目录收尾、缺失容忍和退休续做仍在各自生命周期边界。

`artifact_retention.json`和`artifact_retention.py`实现[生命周期](../../docs/LIFECYCLE.md)的run产物保留合同。迁移到manifest v2的
入口必须显式启用公共生命周期retention，启用后的默认类是`compact`；`qualification/solver_review`
必须在运行前给出理由。终态前`apply`只清除本次未闭合run中策略禁止的可重建文件并写
`retention_actions.json`，不会处理既有最终run。manifest schema v2记录保留类和每项输出角色；
writer/verifier同时扫描未列出的重型文件，防止通过漏报output绕过。schema v1只承担历史兼容，不因
新增合同而失效；未迁移入口由测试中的具名棘轮清单约束，新建或实质修改时必须退出该清单。

`reconcile_artifact_capacity.py`与`artifact_capacity_policy.json`实现日常容量治理，只有三项职责：
启动检查、生命周期登记和维护清理。唯一权威状态是[`capacity_ledger.py`](capacity_ledger.py)维护的
`capacity_ledger.json`及[`capacity_protection.py`](capacity_protection.py)维护的公共租约，不存在第二套项目级门禁。

台账只使用三类对象：`light_evidence`保留必要证据，`published_cache`保存公共可复用重型资产，
`rebuildable_payload`保存可重建载荷。对象状态只使用`writing/ready/retirement_pending/retired`；pin必须说明理由，
发布缓存必须绑定SHA-256代际。`writing`必须登记`owner/recovery_reason/review_deadline`，可列出消费者；到期后
startup失败关闭并报告精确对象，不能自动删除，也不能无限期成为未知垃圾。完整台账不允许未分类对象。

所有生产`New-RunPackage`调用都必须启用`CapacityLedgerLifecycleEnabled`：创建时登记精确run目录为
`rebuildable_payload/writing`；终态retention完成后，只有不含求解器原生二进制、稠密轨迹或大型可选文件且不超过
统一light-evidence预算的run，才能按实际大小登记为`light_evidence/ready`；否则保持writing并列出问题文件。
公共缓存发布入口负责把唯一缓存代际登记为
`published_cache/ready`，run只保存身份和轻量结果。

跨“构建→发布→装配→飞行”的工作流只持有一个由`Enter-ArtifactWorkflowCapacitySession`建立的租约；
子步骤用`Update-ArtifactWorkflowCapacitySession`扩展输入保护并更新“从当前时刻起仍可能新增的峰值字节”，
最后一个消费者结束后由`Exit-ArtifactWorkflowCapacitySession`释放。输入保护和新增空间承诺分别记录，
共享输入只计一次。调用方不得传裸`KnownMeasuredBytes/MaximumNewArtifactBytes/RequiredHeadroomBytes`，也不得覆盖
`TargetGiB/MinimumFreeGiB`。

startup只查询磁盘空闲并读取台账、当前租约和全部活动承诺；不遍历artifact、run或缓存，不哈希PA，
不做历史清理。缺失/损坏台账、当前租约scope不完整、未知承诺、影响当前输入或使容量不可判定的writing复核逾期、
以及空间不足都明确失败关闭；无关逾期writing只报告warning。
正常目标为5秒；超过5秒或60秒只发性能warning，不改变安全结论。历史发现只由显式一次性`legacy_capacity_calibration.py --workspace-root <simulation_repo>`
执行，不能从日常路径隐式触发。它同时登记artifact根与仓库`scratch/`、`generated/`两个外部
受管范围；二者只在校准时计量，启动仅使用冻结的台账数值。`legacy_capacity_backfill.py`
只承担历史恢复，不能提供日常准入或容量水位覆盖。

maintenance先处理`ready`、未pin且无租约保护的`rebuildable_payload`。`published_cache`不会进入通用删除队列；
已开始的退休优先续做；同类可重建载荷按字节数降序选择，达到容量目标即停止，避免为很小的空间缺口
逐项重写上千次全量账本。published cache 仍沿用最近使用时间顺序，所有身份与保护检查保持不变。
维护仅向其固定owner manager请求精确代际退休，manager在同一决策锁内提交owner终态和sealed disposition后，
删除器才按该唯一清单执行。`light_evidence`不参与自动删除。删除与消费仅在短决策锁内复核身份、租约和退休状态，
大型删除在锁外执行并增量更新固定处置记录；中断只重放同一记录，不重新扫描或重复哈希整棵对象树。
已发布代际禁止原位修改；Refine、Fast Adjust和其他写操作只能
使用独立工作副本。日常维护不依赖旧`compact/solver_review/L1-L3`分类，这些旧语义只留在迁移工具中。

失败PA事务若已无任何payload或scratch文件，可由其唯一[PA owner](../simion/pa_family_cache.py)通过
`advance-transaction --abandon-empty-transaction <request.json>`显式收尾：绑定owner、原事务SHA、inventory及
失败producer证据，拒绝已有publication、实际pin、活动租约或消费者引用；任何残留载荷均保留并拒绝。
事务真实转为`retired`，保留原事务全文、verification和失败原因；同路径容量对象按证据实际字节登记为
`light_evidence/ready`。同请求可重放owner已落盘而台账未落盘的中断；`physical_bytes_removed=0`明确表示仅
纠正失准占用，不能报告为物理释放，也不授权非空事务退休或删除。

当前工作站的受管产物目标和物理空闲底线只由[`artifact_capacity_policy.json`](artifact_capacity_policy.json)配置。前者允许原生 SIMION PA family 在
旧代际完成等价验证前短期共存，后者仍为系统盘、求解器暂存和其他已登记工作流保留硬余量。该水位不授权
调用方省略完整峰值预算：大型 family 必须采用同卷原子发布，GUI/solver 可写副本应延迟到旧代际退休后
物化；若活动承诺后的预测空闲低于该配置底线，startup仍须失败关闭。不得把空闲底线设为零来绕过容量规划。

用户明确要求较低清理目标时，可在同一维护入口使用
`reconcile_artifact_capacity.py --execution-mode maintenance --maintenance-target-gib 600`。
该目标只作用于本次维护，必须为有限正数且不高于公共policy目标；不得与租约操作或startup并用。
项目生产调用仍不得覆盖全局准入水位，物理空闲底线和policy文件保持不变。

公共 JSON 原子落盘在 Windows 替换遇到错误 5/32/33 时，复用已刷盘临时文件最多尝试五次，累计
等待不超过 0.75 秒；持续失败仍抛出原异常，保留旧目标并清理此次临时文件，不修改权限。
[Windows 官方错误码](https://learn.microsoft.com/zh-cn/windows/win32/debug/system-error-codes--0-499-)
分别定义拒绝访问、共享冲突和锁冲突；错误 5 不保证是瞬态，上述有界重试是本项目策略。

增量台账由本入口及既有发布/删除/终态收尾入口维护，而不是新建第二套治理工具。台账最小记录为：
`artifact_root`身份、对象路径/角色、字节数、不可变代际身份、状态、最后一次成功发布/删除收据、活动峰值承诺
和待核对标记；台账缺失、版本不符或存在待核对标记时，startup只能阻塞并请求maintenance校准。台账不能用
文件大小或时间戳冒充内容验证，也不能在发布、删除或运行收尾之外自行推断外部写入；首次建立或发现不一致时
才做一次完整扫描，之后按收据增量更新。

`reconcile_interrupted_compact_runs.py --run-dir <exact-run>`提供单run plan/apply；只接受正规终态且
manifest/summary一致的`failed`或`interrupted` compact run。apply必须持有共享`HostExecutionLease`；
无关SIMION进程不再形成全机禁令。入口按规范化结构字段识别指向目标run内具体文件的活动消费者：被引用的
重型文件逐项跳过并报告，指向保留轻量证据的引用不阻塞其他重载；只删除manifest未记录并由retention合同
判为可重建的重型文件。checkpoint不能由该入口推断终态。

`artifact_identity_archive.py`只读解析已经完成的行政改名归档：它校验冻结的逐文件身份、归档包装、
裁剪journal和唯一活动位置，并把旧manifest中的绝对路径按精确前缀映射到归档payload。仓库不再提供
迁移、回滚或裁剪命令；现有归档保持不可变，`archived_verified`也不提供旧顶层路径fallback。

### solver_review 被取代后的重型载荷退休

`solver_review_retirement.py`是既有完整terminal `success`或`failed`的 `solver_review` run 被明确更新成功运行取代后，退休其可重建
求解器原生载荷的唯一公共入口。它不是普通容量清理：默认只生成plan；apply必须通过
`invoke_solver_review_retirement.ps1`取得共享 `HostExecutionLease`，并逐个精确给出target、replacement
和人工审阅后的兼容性说明，并逐项声明本设计线判定兼容所需的同名输入角色；历史角色改名则用
`TARGET_ROLE=REPLACEMENT_ROLE`逐项映射，两端manifest记录的字节数和SHA-256必须相同。入口失败关闭检查
target为一致的success/failed终态、replacement为success、两端均非Formal、replacement更新、项目与mode一致、
两端均具备调用者声明的角色、target没有活动下游run_config引用，且不受活动容量保护租约
覆盖；两端完整manifest记录与config/summary/输入绑定必须通过字节数和SHA验证，apply前再次复核。
Git Markdown中的历史run引用只进入plan/receipt审计，不等于对其重型载荷的活动依赖。旧run若具有精确的初始化
checkpoint summary模板而manifest已是success，允许仅对target使用该兼容形状；replacement仍必须是summary/
manifest一致、证据完整的success。
下游扫描只把manifest缺失或非终态run中结构化配置值精确指向target run、路径或manifest的依赖作为活动阻塞；
活动run_config无法解析时失败关闭。已经终态的相同引用只写入plan/receipt历史审计，不永久钉住被取代重载，
apply会重新执行同一分类。
对于非终态run，若run_config无法解析，退休入口先用有效manifest中绑定的本地
`run_config`字节数和SHA-256核对实际文件：身份已损坏时只记录
`corrupt_run_config_reference_unavailable`审计项，并继续检查manifest自身的结构化引用；身份仍匹配而仅解析失败时，
仍按`run_config_unreadable_reference_uncertain`失败关闭。这样损坏的旧引用不会锁死所有target，真正不可判定的配置仍不会被忽略。
只删除`solver_native_binary`和`dense_trajectory`，不删除轻量IOB、报告或三件套。

apply前先在target内原子写入pending receipt，逐文件验证原始SHA-256后删除，最后写成
`superseded_payload_retired`。receipt保存原完整逐文件清单、被删/保留集合、原manifest身份和替代run绑定。
原`run_manifest.json`保持不可变，但删除后不再代表当前磁盘完整性，也不得交给普通manifest verifier或
下游消费者；只能用`--verify <retired-run>`验证“历史终态身份 + 明确被取代 + 重型载荷已退休”的新语义。
pending receipt表示中断处置，必须人工恢复，不能当作完成或重新自动删除。

## 阶段复用

`stage_reuse.py`提供跨项目、单父run的阶段续跑合同。它不是缓存或DAG调度器，也不定义项目阶段顺序。
未来原生runner只可用`write_stage_receipt`为summary中明确标为`success`的阶段写
`stage_receipts/<stage_id>.json`，随后在父run最终manifest中冻结该receipt、summary、全部阶段输出及
`inputs/source/solver`三类上下文文件。历史上没有原生receipt的run不得事后补写或通过共享层兼容；
需要时重新完成一次全流程运行，建立首个可续跑父run。
原生runner在运行期间仍须保留`status=interrupted`的 provisional manifest。项目只有在该manifest与
同run的`interrupted/running` summary身份一致时，才可显式允许共享入口写receipt或provenance；每次
写入后立即刷新provisional manifest。最终`success/failed/interrupted` manifest仍禁止任何续写。

子run先在自己的run目录冻结三类上下文，并由`run_config.inputs`逐文件声明这些上下文以及将生成的
`inputs/stage_reuse_provenance.json`，再调用唯一发布入口`validate_and_write_stage_reuse`。父子run
目录和run ID必须不同，且已有最终manifest的子run不得续写。该入口
复核父run config、父manifest、summary与manifest相同的`success/failed`终态、summary阶段状态、
receipt和全部相关SHA-256，将当前上下文与父阶段逐键比较，并直接写
`inputs/stage_reuse_provenance.json`。缺键、增键、内容变化、项目/run身份不一致及
`interrupted/superseded`父run均失败关闭；父run整体可以是`failed`，但只能复用其独立成功阶段。
provenance冻结单一`parent_run_id`及父manifest的bytes/SHA，不保存个人绝对路径，并须纳入子run
manifest。旧manifest若记录绝对路径，只有仍位于原路径且全部哈希可复核时才可作为父run；工作区迁移
后必须先按artifact迁移合同重建身份，不能靠路径猜测。

公共层不复制大文件、不解释器件参数或物理判据，也不允许不同父run拼接。项目层仍负责声明可复用阶段、
把实际文件映射为三类上下文、执行未复用阶段并完成本项目最终验收。

## 粒子状态与坐标

粒子状态分为两个不同边界。`particle_state.py`验证单个多极杆组件内部的17列
`source/rod_exit/handoff/terminal`事件账本，其轴向/横向字段仍表达该组件局部坐标。这四个值是事件
角色而不是四个可互换平面：`source`记录从粒子源合同在源释放面产生的初始事件，`rod_exit`记录杆端
事件，`handoff`记录跨组件交接事件，`terminal`记录求解器终止、撞壁、超时等最终分类。公共事件
角色不定义任何器件表面；具体技术域必须在本域机器合同和README中定义事件绑定的物理对象。多极杆
绑定只按[`../multipole/README.md`](../multipole/README.md#统一术语)解释。
`component_particle_state.py`及
[`schemas/component_particle_state.schema.json`](schemas/component_particle_state.schema.json)
定义跨组件转移使用的version 1 canonical状态：每个粒子一行，严格按Schema中的
`x-csv-column-order`保存identity、`species_id`、正的`particle_weight`、组件和事件、frame、clock
epoch、年龄/出生时刻、谱系、质量/电荷、三维位置/速度、派生质荷比/动能，以及可选的具名相位。
入口为：

```powershell
python -m common.contracts.component_particle_state --state <canonical.csv>
```

version 1不允许重排列、缺列或追加项目列。新的公共必需字段必须增加Schema版本并提供显式迁移；
项目专用状态、损失分类和求解器诊断应写入以`particle_id`关联的独立表。组件ID、事件名、frame ID、
clock epoch ID、species ID和phase reference ID是开放的受控标识，不在公共层维护器件枚举。
`phase_reference_id`与`phase_rad`必须同时为空或同时有值；因此无周期驱动器件不必伪造RF相位。
所有新生产者统一调用`write_component_particle_state_csv`按Schema列序写出并立即校验；生产者仍负责
事件选择、坐标变换和状态构造，不得在项目内复制canonical CSV序列化规则。

`mass_amu`、`charge_state`和三维速度是物理主字段；`mass_to_charge_Th`与`kinetic_energy_eV`只是便于
交换和审计的派生字段。validator使用`particle_physics.kinetic_energy_ev`中的唯一非相对论公式和冻结容差
复算它们，矛盾即失败，但不重算或覆盖文件。它还校验有限值、唯一身份、谱系父子关系和时钟恒等式，
并复用`rigid_transform.PhaseSpaceState`校验具名frame中的三维状态。它不推进粒子、不推导相位，也不
实施坐标变换。生产者必须先由实际求解器得到物理状态；跨frame位置/速度只调用
`rigid_transform.py`，clock epoch与谱系推进由组件链编排合同负责。时钟epoch之前的绝对时刻允许为负，
但年龄和组件内elapsed time必须非负。

RF→oaTOF现有含`source_rf_phase_rad`的25列项目表是legacy输入，不是公共version 1的别名，也不得静默
当作兼容格式。迁移器必须从冻结的源粒子身份显式绑定`species_id`与`particle_weight`，将旧RF相位映射
为具名`phase_reference_id`/`phase_rad`对，再验证输出；缺少绑定应失败。已冻结运行保持原字节不变，
新生产运行才使用迁移后的公共合同。任何未来公共字段变更都提升版本并保留显式、可测试的迁移路径。

`rigid_transform.py`是求解器无关的空间注册语义。版本1刚体合同显式保存`from_frame_id`、
`to_frame_id`、有限右手正交`rotation`和`translation_mm`。点按`R @ r + t`变换；free、polar和
axial向量都显式标记种类，并在当前仅允许`det(R)=+1`的旋转下按`R @ v`变换；二阶张量和3D协方差按
`R @ T @ R.T`变换；按`(position[3], velocity[3])`排列的6D协方差按`diag(R,R)`做合同变换。
`PlaneSurface`统一接口面的中心、单位法向和正向穿越语义，`PhaseSpaceState`统一粒子位置、速度和共享
仪器时间。空间标量与时间保持不变，所有变换都禁止隐式单位换算。`RigidTransform.then`表示先执行
当前变换、再执行参数变换；`relative_transform`只从两个指向同一参考frame的组件pose派生相对变换。

`spatial_registration.py`把项目提供的版本化组件pose和定向面编译成唯一resolved发布，固定记录输入文件
SHA-256、组件到仪器frame的pose、唯一source-to-target相对变换，以及每个面的声明frame和仪器frame
表示；`write_or_check_release`以逐字节确定性序列化实现`--write`与stale失败。电压、频率等标量不参与
坐标变换，但发布器可保留其值、单位、来源JSON pointer、来源文件身份和电极绑定，并明确禁止单位换算。

项目继续负责具体pose输入、接口尺寸和验收阈值。项目解析器必须从当前resolved几何和电气合同生成上述
发布；COMSOL、SIMION和CAD只能读取、序列化并校验它，不得再次推导坐标关系，也不得把IOB角点、
Euler顺序或器件参数反写到公共刚体语义。供应商局部坐标映射可以留在薄适配器，但不能成为跨组件pose
或粒子状态的第二权威。

`particle_count_policy.json`是[操作指南的粒子数口径](../../docs/OPERATIONS.md#通用验证口径)对应的机器合同。它约束Candidate和Formal
基线，不限制探索运行的正整数样本量；本目录不重复定义正式档位，项目也不得复制后修改该规范。

## 项目发现

项目身份和能力的权威源是各项目`config/project.json`。根`config/project_registry.json`是生成索引，
禁止手改：

```powershell
.\.venv\Scripts\python.exe common\contracts\build_project_registry.py
.\.venv\Scripts\python.exe common\contracts\build_project_registry.py --check
```

## 从自然语言到计划

当前边界是“Agent理解自然语言，确定性工具验证合同”：Agent先把需求翻译成`design_request` JSON，
保留为`proposed`，由使用者批准后才能请求formal证据。校验结果固定为`READY`、
`NEEDS_CLARIFICATION`、`NEEDS_PROJECT_COMPLETION`、`NEEDS_NEW_PROJECT`或`UNSUPPORTED`，不会因为
项目目录存在就假定能力已经完成。

```powershell
.\.venv\Scripts\python.exe -m common.contracts.validate_design_request <request.json>
.\.venv\Scripts\python.exe -m common.contracts.plan_design_request <request.json> `
  --run-id 20260720_120000__analysis__repo__design-request `
  --output-dir <new-run-directory>
```

规划器只写`design_plan.json`和`run_config.json`，不启动商业求解器、不宣称满足指标，也不把
`formal_gate_passed`设为真。后续执行器必须继续使用项目门禁、summary和manifest闭合实际证据。

## 执行dry-run

各项目在`config/execution_profiles.json`中声明现有入口实际支持的工况、目标指标、变量、约束、产物和命令链。
执行编译器只生成命令预览，没有执行开关：

```powershell
.\.venv\Scripts\python.exe -m common.contracts.compile_execution_plan <design_plan.json>
```

结果为`EXECUTION_READY`、`AWAITING_APPROVAL`、`NEEDS_RUNTIME_INPUTS`或`NEEDS_IMPLEMENTATION`。
`EXECUTION_READY`只表示需求已批准且现有入口能够消费声明字段并评价所请求的目标指标；它不表示
求解已经运行或指标已经满足。只完成结构构建的runner不得把分辨率等未评价目标列为支持。
需要显式粒子表、RF幅值等运行绑定的profile使用`--bind key=value`提供预览值。编译器会验证入口文件、
生成受命名合同约束的子run ID，并保留项目profile的限制说明，但不会创建artifact运行目录。

## 正式结果与来源运行

每次运行的`run_config.json`、`summary.json`和`run_manifest.json`只描述来源run；通过正式门禁后，选出的
模型、CAD和结果进入稳定`formal/`，但不改变来源三件套。`formal/asset_manifest.json`是当前正式发布
的唯一资产清单，记录来源run三件套、Git内正式验证合同及各正式资产的相对路径、字节数和SHA-256：

```powershell
python common/contracts/write_formal_asset_manifest.py `
  --project-root <artifacts-project-root> --repository-root <repository-root> `
  --project <project_id> --source-run-id <run_id> `
  --validation-contract <formal-validation-json> `
  --asset formal_results_manifest=results/SHA256SUMS.csv
```

结构门禁默认不读取大二进制；正式发布或资产变更后再运行
从仓库根运行`python -m common.contracts.verify_artifact_layout <artifacts-projects-root> --verify-hashes`
做完整哈希复核。正式结果本体不复制回
来源run；为便于独立交付，可在结果包保留三份小型来源JSON快照，但它们不能替代原始run或正式清单。
只复核当前正式发布而不审计旧run命名时使用`--formal-only --repository-root <repository-root>`。

优化变量的“项目能力声明”和“现有执行入口可消费”是两层事实。一个变量可以属于未来设计空间，但在
候选参数编译器尚未把它单向派生到baseline/resolved和全部求解器/CAD前，dry-run必须报告
`NEEDS_IMPLEMENTATION`，不得调用固定模型冒充优化。

## 候选参数编译

项目可以用`config/design_variables.json`声明变量类型、静态安全范围、JSON指针和重建影响，并用独立
`config/optimization_envelope.json`限制一轮优化的总体包络。正式baseline是当前验收设计，不是永远
不可扩大的宇宙上限；envelope可经明确审查扩大，扩大本身也不会自动改写或转正baseline。

项目候选编译器必须把获批提案写入隔离run，验证请求/提案身份、单位、变量范围、项目硬约束和当前
envelope，并输出可审阅的候选合同与差异。它不得修改正式baseline、运行求解器或创建正式资产。
具体包络策略、候选文件名和编译入口属于消费项目，不在公共合同README维护第二份说明。
