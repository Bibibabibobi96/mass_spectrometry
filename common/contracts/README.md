# 机器合同与设计请求

本目录保存跨项目的机器合同 Schema、语义校验器和可追溯规划工具。JSON Schema只判断字段、类型、
单位是否完整；Python语义层判断项目选择、能力成熟度、模式、指标、设计变量和约束是否成立。
二者不能互相取代。

## 按任务导航

只读本次任务对应的章节；本页说明公共 API，生命周期政策仍以[生命周期](../../docs/LIFECYCLE.md)为准。

| 任务 | 入口 |
|---|---|
| 创建 run、冻结输入、发布或消费 manifest | [初始化与冻结](#运行初始化与输入冻结)、[文件身份](#文件身份与读取)、[manifest](#manifest发布与消费) |
| 配置终态保留、申请容量或维护台账 | [终态保留](#运行终态保留)、[容量准入与维护](#容量准入与维护)、[登记与租约](#容量登记租约与退休) |
| 恢复精确旧载荷、账本或停止的 run | [精确恢复](#精确恢复与旧载荷处置)、[停止载荷收尾](#异常账本与停止载荷收尾)、[中断与旧身份](#中断与旧身份) |
| 退役 solver_review 重型载荷 | [唯一退休入口及适用模式](#solver_review-被取代后的重型载荷退休) |
| 复用已完成阶段 | [阶段复用](#阶段复用) |
| 交接粒子、注册坐标或仪器时钟 | [粒子状态与坐标](#粒子状态与坐标)、[时钟与运行初始化](#运行初始化与输入冻结) |
| 发现项目、把需求变为可执行计划 | [项目发现](#项目发现)、[需求规划](#从自然语言到计划)、[执行预览](#执行dry-run) |
| 编译候选或发布正式资产 | [候选参数](#候选参数编译)、[正式发布](#正式结果与来源运行) |

## 运行身份与生命周期

### 运行初始化与输入冻结

`canonical_clock_authority.py`与同名Schema定义跨项目事件链唯一instrument clock权威：求解器局部时钟
从零累计，adapter仅一次物化`epoch + elapsed`，handoff保留时间戳；新run不得使用legacy相对时钟旁路。

`artifact_project.py`统一artifact项目根索引，`particle_state.py`统一SIMION/COMSOL适配后的粒子事件字段、
身份、三维位置/速度、全局时间和RF相位校验；`run_artifact_support.ps1`统一PowerShell运行器创建目录、
冻结输入、失败收尾和三件套manifest。它们不得内置器件参数；项目入口保留科学与结果语义，复用公共运行机制。
其中`Write-RunJson`保持调用方的JSON类型：空数组和单元素数组仍写作数组，不经PowerShell管道解包，
以免单批日志路径被下游误读为字符串。
`Copy-VerifiedRunInput`默认保持单次严格复制；对数百MB至GB级solver数组，调用方可显式设置
`-VerificationAttempts 3`，每次都要求复制前源、复制后源和目标SHA-256三方完全一致；首轮普通复制
失败后，后续轮次使用8-MiB显式流、write-through和磁盘flush。该选项只容忍可重试的本机大文件复制
抖动，不会把持续变化的源或坏副本降级为成功。
复制身份校验失败的异常`Data`保留`source_path`、`destination_path`、`source_sha256`和`frozen_sha256`，
适配器可复用这些实测身份生成诊断，无需额外哈希。
需要规避 Windows 路径深度的外部运行器可在`New-RunPackage`显式选择`-UseShortExecutionPath`。公共层会从
`MASS_SPECTROMETRY_EXECUTION_ROOT`（未设置时使用工作区的`artifacts/common/execution_aliases/`）创建一次性短 junction 指向最终
`artifacts/.../runs/<run_id>`；运行器把短路径仅作为进程工作路径，并在终态后调用
`Remove-RunPackageExecutionAlias`清理它。实际文件从未搬离最终run，Python manifest解析 junction 后记录真实
artifact路径，因此run ID、输入/输出身份、SHA和历史引用不变。不能以复制后回迁或只缩短某个求解器子目录
替代该合同。该 junction 仅指向本次可写 run；SIMION 外部只读 PA 输入另用[已验证普通副本机制](../../docs/tools/SIMION_REFERENCE.md#长pa输入路径)，不得用此别名暴露不可变 PA 源。
`Write-RunManifest`通过UTF-8标准输入向`write_run_manifest.py --output-list-json -`传递输出路径，
避免大量文件路径超过Windows进程命令行长度；列表严格为字符串数组，不再落盘临时运输文件。
原Python入口的重复`--output`仍可使用，两种输入共同进入同一manifest校验和身份计算。
保留原生载荷的owner可对`Write-VerifiedRunManifest`／`Complete-FailedRun`显式使用
`-DeferCapacityFinalization`：仍验证保留合同并原子发布manifest，随后由owner释放其保护租约、调用公共
`seal-stopped-payload`完成容量交接。此选项只延后容量收尾，不跳过输入、输出或终态验证；普通小证据入口
继续默认`finalize-ready`。封存后出现的容量错误不得重写已经发布的科学终态。
`Complete-FailedRun`在修改配置、摘要或保留文件前读取同run的manifest身份与状态；已有终态时告警并保留，
不把这次小文件检查称为重新核验全部产物。未发布或checkpoint仍沿原失败收尾；调用者继续报告原始异常。

运行初始化统一使用`New-RunPackage`；原仅由测试调用的初始化包装和无调用的依赖复制包装已移除。
writer与verifier共用保留策略入口，独立消费时仍重新验证完整内容，不维护两份同义导入逻辑。
冻结执行快照中的公共IOB占位模板属于必需输入，所有已引用槽位均须保留；该分类不适用于运行目录中
同名的普通求解PA。它们的来源与用途见[模板说明](../simion/assets/iob_instance_seeds/README.md)。

### 文件身份与读取

`strict_json.py`提供机器JSON的公共表示检查：`load_json_object`读取UTF-8（可带BOM）对象，
拒绝任意层级的重复键、NaN／Infinity及浮点溢出；`require_number`拒绝bool、数值字符串和非有限值，
超大整数的浮点转换失败也归为`StrictJsonError`。边界值只由调用方显式传入，不推断单位、物种或科学资格。
MR实测源与共同场有限脉冲准备已复用同一入口，原有文件身份、物理约束和CSV解析仍由各自owner负责。
表示检查与现有EI／电子枪真实消费回归见`test_strict_json.py`及两项目`test_resolve_contract.py`。

`file_identity.py`是SHA-256身份的唯一共享实现，固定返回大写十六进制。`file_sha256`按原始字节标识
manifest、正式资产和外部artifact；`repository_text_sha256`只用于Git治理的文本依赖，先把行尾规范为
LF，从而使Windows工作树与干净checkout得到同一身份。调用者仍负责路径范围、字节数和证据资格。

[`frozen_inputs.freeze_file(source, destination)`](frozen_inputs.py)冻结显式选定的小配置、源码或观测文件：
以源文件的原始字节记录核验副本，返回目的文件record及`source_path`；缺源、目的已存在或副本身份不符均失败。
每次只读取一次源身份和一次目的身份；调用方负责输入选择、目的目录与命名。IP和MR准备入口直接消费此API，
沿原有源码闭包冻结公共模块；PA／MPH等求解器载荷继续使用各自owner机制。

manifest writer 与 verifier 分别只在本次调用内复用重复文件的 `(bytes, SHA)`；复用键绑定解析后的实际路径、
真实读取函数、大小与修改时间，普通读取和大 PA 无缓冲读取不能混用。每条声明仍独立检查路径、字节数、
SHA 和保留角色；虚拟终态文档不进入磁盘身份复用。`file_record`／`verify_record` 默认仍逐次读取，
发布、复核和下游消费之间不保留此临时字典；大小与修改时间仅判断本次已读身份是否可复用。

大PA的owner可显式调用`file_sha256_unbuffered`，默认`file_sha256`不变。该入口仅支持Windows 8+，
以只读且仅share-read的`CreateFileW`句柄、`FILE_FLAG_NO_BUFFERING`、实际存储扇区信息和对齐的
`VirtualAlloc`缓冲区顺序读取一次；尾块请求按扇区向上取整，只哈希`ReadFile`实际返回的文件字节。
无临时全文件副本、无源写入或flush，API/短读/未知对齐失败不回退普通读取。调用者必须先确认求解器
已经完成且无活动映射写入者；不同视图的哈希不一致仍是身份失败，不能选一个能匹配旧清单的值当成功。
这只绕过Windows系统数据缓存，不保证硬件缓存已持久化，也不把无缓冲结果自动升级为发布资格。

manifest的`file_record`对Windows上读取角色为`solver_native_binary`且至少8 MiB的载荷，
直接使用上述无缓冲读取一次。Windows上至少8 MiB且未显式声明`retention_role`的真实文件通过既有`classify_file`确定读取角色，
因此PA输入和输出采用同一策略；此分类不向输入record添加保留元数据。小文件和非Windows读取不引入分类策略依赖。writer与verifier复用同一入口，不在失败后切换读法。
8 MiB沿用既有大PA库存读取档位，仅区分I/O路径，不是科学参数。小文件、普通记录和非Windows
保持普通读取，SHA仍标识原始完整字节；API失败或与原记录不匹配继续失败关闭。
producer须在发布前关闭写入和映射，不通过这项读取选择刷新或修改已经封存的输入。

官方接口核查（Microsoft Win32，Windows 8+/Server 2012+；查阅2026-09-21）：
[File buffering](https://learn.microsoft.com/en-us/windows/win32/fileio/file-buffering)定义无缓冲尺寸、地址对齐和硬件缓存边界；
[CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)定义只读/share-read打开；
[FILE_STORAGE_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_storage_info)及
[GetFileInformationByHandleEx](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getfileinformationbyhandleex)提供同一文件句柄的扇区信息；
[VirtualAlloc](https://learn.microsoft.com/en-us/windows/win32/api/memoryapi/nf-memoryapi-virtualalloc)提供可显式对齐的内存；
[ReadFile](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-readfile)定义同步读和跨EOF尾读。
这是基于官方API的项目SHA-256实现，用于显式核对异常的大文件缓存视图；不支持这些接口的存储失败关闭。

### manifest发布与消费

producer关闭载荷后，writer CLI计算全部身份并检查保留合同，拒绝缺失输出和未完成的终态journal；
原子写入后读回小型manifest与内存记录完整比对，公共发布器不再另起verifier重复全文读取同批载荷。
这是同次发布的工作复用，不是跨消费边界缓存。`build_run_manifest`纯构建API仍可记录缺失输出，
供虚拟文档/失败证据构建；它本身不提供CLI的完整发布保证。
`verify_run_manifest.py`作为独立消费入口仍默认复核run config、全部输入、全部输出和适用的保留合同。已经冻结的
历史run若有不再被下游读取的大型记录丢失或损坏，下游可用具名`--consumer-projection-id`，并逐项提供
`--consumed-input NAME PATH`／`--consumed-output PATH`；入口仍复核manifest状态、run config、项目／模式等
约束，并把每个实际消费路径唯一绑定到manifest记录后核对字节数和SHA-256。投影不得用于发布或宣称整个
上游run仍完整有效；消费run必须在自己的run config记录投影ID、记录名、路径以及未断言其余记录。选择器
缺少投影ID、空投影、路径不一致、重复记录或消费记录漂移均失败关闭。

### 精确恢复与旧载荷处置

普通owner通过`solver_review_retirement.py`精确选择重型文件后，可在后续需求结束时继续退役另一个不相交子集。
首份`solver_review_retirement_receipt.json`保持原字节；后续使用`solver_review_retirement_receipt_0002.json`等
顺序收据，绑定上一份收据身份、同一原manifest及owner。上一批须完成并通过`seal-stopped-payload`精确收尾后
才允许新批次；pending只能恢复原选择，不创建下一批。planner、apply、verifier和容量reseal共用同一收据选择器。
验证按收据链核对历次合法移除与当前剩余文件；容量只在公共锁内按实际剩余库存（含全部收据）更新一次。
原manifest、科学终态及旧收据不改写；runtime、prepared GUI和supersession退役仍使用原单批合同。

历史元数据消费者可调用同一`verify_retirement(run_dir, consumed_paths=[...])`，显式列出仍保留的规范run-relative路径。
投影仍检查收据链、owner、终态、准确退役成员及其不存在事实，只核验实际消费的保留文件字节，
结果标记`scope=consumer_projection`；省略参数仍执行完整验证。空、重复、非规范或已退役路径拒绝。
该投影不证明其他保留载荷完整，不能授权已退役场重新使用；当前实际加载的PA及surface仍须沿其封存记录核验。

`recorded_file_removal.py`只负责已预检清单的逐文件身份重验、删除及可刷新落盘的JSON记录，不扫描或
选择待删对象。容量、run retention和solver-review退休各自决定准入并先发布pending；迭代器每删除一项
返回该记录，由调用方保存原有进度和终态语义。目录收尾、缺失容忍和退休续做仍在各自生命周期边界。

容量账本出现唯一对象的`path`或`class`键损坏时，可显式调用公共入口
`reconcile_artifact_capacity --restore-ledger-object-key-receipt <completed-recovery-receipt>`，并提供
`--expected-ledger-sha256`、`--expected-receipt-sha256`。`path`仅允许退役、未pin、0字节且载荷未重现的对象，
`class`仅允许ready对象。对象须恰缺这两个受支持键之一、恰有一个未知替代键；纠正后的全部字段必须
与已完成恢复收据认证的原始raw中唯一记录完全相同，不猜测字段名、类别或容量。
恢复只替换唯一原始键token，其余raw字节、resident/status/pin/bytes均保持，并完整校验候选账本。
默认dry-run，`--apply`仍要求HostExecutionLease；复用原raw备份和pending journal，原子发布后可严格重放。
历史完成恢复收据仍可认证原raw。其他损坏或完整账本拒绝，不重新校准、不扫描载荷。

已完成退役的solver-review run若保留的普通PA出现缓冲／无缓冲读取分叉，owner可显式使用
`invoke_solver_review_retirement.ps1 -RepairPreservedFile <relative.pa> -RepairEvidenceRun <audit-run>`，
同时提供原manifest／退役收据SHA及`-ConfirmWritingStopped`；这不是自动读取重试或持续损坏恢复。
audit须为同项目规范run、`mode=owned_payload_view_repair`、solver_review保留类且启用容量生命周期。
公共入口申请3倍载荷预算，两个独立`/J`快照均须经两种读取匹配原SHA，才隔离旧文件对象并以同字节
新对象替换；原清单不变，旧对象和第二快照保留。pending journal支持两个rename边界重放；
源只读、禁止源写入／flush，修复后两种读取仍不一致则失败关闭。仅限Windows、至少8 MiB、
原成功run中已封存且唯一保留的`solver_native_binary`；Formal、原生family、未结束写入及其他消费者冲突拒绝。
依据（Microsoft Win32、Windows 8+，2026-10-18查阅）：
[CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)的
`GENERIC_READ`和`FILE_SHARE_READ|FILE_SHARE_DELETE`允许只读保护下rename、禁止writer；
[MoveFileExW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw)定义同卷替换限制。
这是基于官方接口的仓库owner恢复协议，复用既有`snapshot_immutable_file`，不声称厂商推荐该恢复算法。

`New-RunPackage`在创建前要求受管`ArtifactRoot`精确指向`artifacts/projects/<Project>`。
历史误传导致的`projects/<owner>/runs/runs/<run-id>`轻证据包，可显式用
`run_capacity_lifecycle --action retire-misplaced-light-run --artifact-root <root> --run-config <original-config> --backup-manifest <backup-manifest> --owner <project>`预检。
备份须为同项目规范run、模式`misplaced_light_run_backup`，其完整manifest绑定
`results/misplaced_run_backup_receipt.json`及`inputs/misplaced_run_snapshot/`下全部原始文件副本。
原包必须为无租约／消费者的ready light证据，且保留原错误账本owner=`runs`；不改身份或分类。
增加`--apply`须持有HostExecutionLease，沿精确清单journal和原删除器支持中断重放，扣除实际字节；
这不是一般light证据自动清理入口。

`capacity_ledger.approve_published_cache_retirement`亦接收显式`expected_project_owner`：只允许
`projects/<actual-owner>/cache/<registered-integration-role>/<SHA256-key>`下未设置manager、未pin且无消费者的
完整ready缓存。owner必须在同一锁内回调核对库存并先封存实际匹配的重建输入；默认PA-manager路径不变。
批准仍由公共维护执行已封存disposition，owner入口本身不删除，也不将旧项目缓存冒充公共PA-family缓存。
`simion_pa_basis`项目基场缓存沿同一入口执行相同的owner、pin、消费者和库存检查，不另设退役协议。

### 运行终态保留

`artifact_retention.json`和`artifact_retention.py`实现[生命周期](../../docs/LIFECYCLE.md)的run产物保留合同。迁移到manifest v2的
入口必须显式启用公共生命周期retention，启用后的默认类是`compact`；`qualification/solver_review`
必须在运行前给出理由。终态前`apply`只清除本次未闭合run中策略禁止的可重建文件并写
`retention_actions.json`，只复核精确路径、常规文件类型和字节数，不读取待丢弃内容；不会处理既有最终run。
manifest schema v2记录保留类和每项输出角色；
writer/verifier同时扫描未列出的重型文件，防止通过漏报output绕过。schema v1只承担历史兼容，不因
新增合同而失效；未迁移入口由测试中的具名棘轮清单约束，新建或实质修改时必须退出该清单。

`Complete-FailedRun`只传递调用方的`PreserveRawOutputs/PreserveRawOutputPaths`声明；
`Apply-RunArtifactRetention -FailedRun`由同一Python保留入口处理未显式保留的批次日志。
保留声明仅适用于schema v2，必须在任何删除或收据写入前通过
[SIMION日志完成校验](../simion/README.md#原生完成事实)；畸形或未完成日志不能取得恢复豁免。
已有终态的run先退出，不覆盖其日志、summary或manifest；原生完成不代表科学成功。
PowerShell入口使用精确RepoRoot上下文。独立writer/verifier的直接文件入口仍受支持，
所需SIMION适配器只从同一源码树加载，冻结闭包必须包含该文件，缺失时不搜索活动仓库补齐。

### 容量准入与维护

`reconcile_artifact_capacity.py`与`artifact_capacity_policy.json`实现日常容量治理，只有三项职责：
启动检查、生命周期登记和维护清理。唯一权威状态是[`capacity_ledger.py`](capacity_ledger.py)维护的
`capacity_ledger.json`及[`capacity_protection.py`](capacity_protection.py)维护的公共租约，不存在第二套项目级门禁。
artifact布局检查接受该精确台账文件并复用台账校验器；租约目录的既有decision lock由公共租约读取器识别，
它是内核互斥所用的保留文件，不是JSON证据。其他未登记common文件仍拒绝。
公共租约按解析后的路径身份比较保护范围，保留父／子覆盖和未创建子路径的保护；不改写已有租约路径表示或key保护。
公共PA布局检查复用owner的只读事务校验入口，接受严格事务元数据及具名key锁；未完成的非空payload、
build-scratch或未知文件仍不能作为干净缓存布局通过，不调用会修改台账的maintenance审计。

维护的容量判据与startup一致：`resident_bytes + committed_new_bytes <= target_bytes`，并满足
`free_bytes >= minimum_free_bytes + committed_new_bytes`。apply结束时重新读取承诺，不能以规划时的旧租约
宣布成功。未带`--apply`的维护只读；带`--apply`时先检查HostExecutionLease，再执行登记、续做和删除。
默认报告按owner、类别、状态汇总全部受管占用，并单列缺少已注册退休manager的缓存；不得把它们报告成
“容量需要时即可删除”。可重建范围的删除仅核对批准范围、路径、类型和字节数，不为待丢弃载荷新增全文哈希。

相同代际在不同缓存根可产生相同 disposition ID。若该 ID 的既有处置收据身份匹配、已经 complete、但
对应另一个绝对目标，维护仅为新目标使用带规范路径摘要的独立收据名；旧收据不变，普通无冲突命名不变。
pending、损坏收据和目标专属收据的身份/目标冲突仍失败关闭；摘要只编码路径，不读取 PA 载荷。

容量达标与生命周期闭合是不同判据。`satisfied=true`只表示本次容量判据通过，不表示所有历史`writing`
已恢复、所有缓存已有退休入口或工作区外部范围均已实时计量。当前仍需补齐的闭环是：由既有run/PA/review
owner入口根据真实证据产生可重放的收尾决定，由同一maintenance消费；文字`recovery_task`不是可执行规则。
新增重型产物必须在写入前绑定owner、已注册的收尾能力及有限恢复期限，并在发布前复核，不得靠文档承诺。
历史checkpoint不自动改写为失败；活动消费者与已封存证据仍须保护。验收须覆盖中断重放、缺owner或处置能力
拒绝新建、未知路径拒绝准入、单对象失败后继续独立对象，以及保留期到期后的实际处置；仅缩减台账占用
或输出行动清单不能视为这一闭环完成。不新增第二份台账、通用任务调度器或平行删除入口。

### 异常账本与停止载荷收尾

若账本仅有一个已退休对象的处置文件路径损坏，可显式沿同一CLI使用
`--restore-retired-disposition-receipt <原complete处置收据>`、`--expected-ledger-sha256 <坏账本SHA>`及
`--expected-receipt-sha256 <原收据SHA>`预览恢复；增加`--apply`须持有原HostExecutionLease。
它只从同目标、owner、代际和逐文件字节数均匹配的原完成收据恢复一条已损坏路径；合法路径、其他字段、
活动对象和有效账本覆盖均拒绝。原容量锁内先保全坏字节与pending收据，核对原SHA后原子发布并完整复验；
同一pending可按原／候选SHA续做。全部对象、pin、owner、外部范围、租约和resident保持，
不扫描载荷、不重新校准、不删除文件，也不将该动作计作释放容量。

已停止写入且只剩轻量证据的 checkpoint 可由 owner 显式调用
`python -m common.contracts.run_capacity_lifecycle --action seal-checkpoint --artifact-root <root> --run-config <run_config.json> --owner <project> --confirm-writing-stopped`。
owner 必须先确认本次写入进程及子进程已结束，并承诺续算使用新 run；本动作不自动探测未登记进程。
它沿用 run 的轻量预算及文件角色判据，在容量决策锁内检查保护租约并登记实际字节为 `light_evidence/ready`，
不改 manifest 的 checkpoint 状态，不写删 run 文件，不改变 pin 或外部 PA 引用。`ready` 仅表示固定 resident，
不表示科学任务完成；重复调用可重放，原 run 不得重新 register-writing。
租约没有读写区别，任何重叠均暂缓；非空 consumers 因现有 ready 合同不能保留该字段而明确拒绝，不静默移除引用。
含 PA 等重型角色、超预算、无精确登记或不属于该 owner 的范围不接受封存，仍交原 owner 处理。

已停止写入但仍须保留 PA/MPH 等重载荷的已登记 run，可由同一 owner 显式调用同一入口的
`--action seal-stopped-payload --artifact-root <root> --run-config <run_config.json> --owner <project> --confirm-writing-stopped --retention-reason "<保留用途>"`。
它复用原锁、精确 owner、consumer/租约检查和实际文件大小 inventory，只将容量对象登记为
`rebuildable_payload/ready` 并 pin；不修改 manifest、run 状态、任何文件字节或既有内容身份，不重哈希重载荷。
只接受原 `success/failed/interrupted/checkpoint` 状态及一致的 config/manifest/run 目录身份；
非空 consumers、活动租约、未确认 writer/子进程停止或不同 owner 均拒绝。`ready` 仅固定已保留占用，
不代表科学成功，也不授权删除；后续消费可沿既有保护机制登记，原 run 不得重新 register-writing。
相同 owner 决定可幂等重放；已有 ready 范围的 resident 大小变化必须由 owner 排查，不静默重计。
若同一 owner 的完整 `solver_review` 退役收据已通过原验证器（具名 owner completion 或未飞行 prepared GUI supersession），
且原库存恰好分成互斥的已删除与保留两组、删除字节数精确一致，
现库存恰为保留文件加退役收据自身，则可沿同一
`seal-stopped-payload` 动作重新登记剩余占用，调用时须沿用原保留理由。它保留原 `ready/pinned`、owner、保留理由和复核期限；
锁内按实际剩余总量减原登记字节更新 resident，计入收据新增字节，不直接扣 removed_bytes。
若旧登记总量偏离退役前完整库存，首次修正的CLI收据额外报告 `accounting_reconciliation`：
`old_registered_bytes`、`original_inventory_bytes` 和 `accounting_drift_bytes`（旧登记减原库存，可正可负）。
这只纠正已完整核验范围的会计漂移，不设置容差；重入不再返回该修正字段，也不再次扣减，普通无漂移路径返回不变。
不受 light-evidence 预算约束，也不将剩余 CSV
改称轻量证据。未完成、身份不符或不能精确解释差额的收据仍拒绝；不重做删除、不改原科学三件套。

同一 owner 的 completed-experiment 退役可用重复 `--selected-heavy-path <run-relative-path>`
（PowerShell 包装器为 `-SelectedHeavyPaths`）选择原封存 manifest 中非空、唯一的重载荷子集。
plan/apply 重新核对同一选择及完整保留库存，收据沿用原格式并记录 `selected_heavy_paths`；
默认仍退役全部重载荷。子集模式不调用 `finalize-ready`，会提示公共容量 reseal 尚待完成；
owner 随后沿用原 owner、保留理由和 pin，通过上述 `seal-stopped-payload` 登记剩余重载荷。
所有下游引用、活动 consumer 与租约保护保持原判据，子集选择不绕过这些检查。

退役读取配置中的完整`file_record`（`path/exists/bytes/sha256`，可选`source_path`来源说明）时，
要求其路径及身份与已验证manifest的input或output记录一致；来源说明不作为第二个消费文件。
普通输入集合仍逐路径严格检查，不改写原封存配置或manifest，也不因这项解析额外扫描PA。

maintenance 以固定顺序调用 owner continuation；某一历史 owner 的 JSON 或处置失败只记录该 action 的
错误，仍继续其他彼此独立的 run、PA、scratch 与别名续做。终态历史 run 若已经逐项登记、总量在轻量
证据预算内且不含重型角色，可从真实 terminal manifest 收敛为一个 `ready` light-evidence range；有完整
compact retention receipt 时使用该 receipt，没有旧 retention 合同时也只允许这一无删除的轻量收敛。
有效 ledger 旁、超过原子发布重试窗口的截断 ledger 临时文件由 capacity owner 以 pending receipt 续做退休；
它只核对精确路径、字节数和租约，不读取或哈希该临时内容。
PA cache 的锁、build-lock 与 staging 目录则是可复用 runtime state：PA owner 将其登记为 ready 的轻量范围，
不把锁文件错误当成待恢复 PA payload，也不会删除它们。

维护摘要将历史`writing`分为三类：有**当前租约明确覆盖**的消费者、唯一`current_*`已收据的 GUI
检查包，或被该 GUI 收据直接引用的 source run 是正常受管保留，并给出租约关闭或 owner 处置的退出路径；已有 sealed owner disposition 的已放弃
范围进入既有自动退休队列；其余 checkpoint、历史引用、失效合同和缺少 producer 证据的范围列为 owner
决策或恢复对象。历史配置中的路径引用本身不是活动消费者，不能无限期保护载荷；当前 GUI 收据也不表示
检查已经完成。该投影只读取小型 JSON 和租约，不打开或全文哈希 PA payload。

### 容量登记、租约与退休

台账只使用三类对象：`light_evidence`保留必要证据，`published_cache`保存公共可复用重型资产，
`rebuildable_payload`保存可重建载荷。对象状态只使用`writing/ready/retirement_pending/retired`；pin必须说明理由，
发布缓存必须绑定SHA-256代际。`writing`必须登记`owner/recovery_reason/review_deadline`，可列出消费者；到期后按下文startup规则判断：影响当前输入或使容量不可判定时失败关闭，无关对象保留占用并报告精确路径warning；
不能自动删除，也不能无限期成为未知垃圾。完整台账不允许未分类对象。

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
startup与maintenance均报告总耗时和分段耗时；正常目标为5秒，超过5秒或60秒只发性能warning，不改变安全结论。历史发现只由显式一次性`legacy_capacity_calibration.py --workspace-root <simulation_repo>`
执行，不能从日常路径隐式触发。它同时登记artifact根、仓库`scratch/`、`generated/`和工作区`scratch/`三个外部
受管范围；前两项只在校准时计量，工作区`scratch/`若尚未登记则由maintenance做一次范围计量，之后启动仅使用冻结的台账数值。`legacy_capacity_backfill.py`
只承担历史恢复，不能提供日常准入或容量水位覆盖。

缺少现行事务而已被明确放弃的历史范围，只能由其目标项目 owner 在
`artifacts/common/capacity_calibration/owner_dispositions/`提供一次性、代际绑定的范围处置记录。显式校准只复核
该记录所列完整路径和字节数及已封存的代际/manifest 路径，不重新读取或哈希 PA payload；仅在该元数据不一致
时才升级为受影响成员的身份诊断。随后复用既有 sealed disposition、处置收据和重放路径；日常启动与维护不扫描
这些范围，也不会为它们推断 owner、终态或删除资格。

历史仓库 source `scratch/` 的删除只能使用`historical_source_scratch_retirement.py`：它要求
校准外部范围、owner批准证据及其SHA-256，并在证据中逐项列出规范化的`retirement_targets`直接子范围（文件或目录）。入口拒绝
重叠目标、符号链接、活动消费者和受保护路径；先冻结这些目标的路径/字节清单及可续做收据，随后才可用`--apply`。
它只哈希小型授权证据，不为可重建大 payload 进行删除前或删除时的内容扫描。
它绝不删除未列出的兄弟目录；所有记录子范围完成后，才可移除已为空的`scratch/`根。台账保留外部范围记录并只扣除已处置字节。
将这类已批准证据放入`common/capacity_calibration/scratch_dispositions/`后，日常maintenance会复用同一入口完成处置并删除已消费的授权文件；没有批准证据的范围只在维护报告中保留，不会被推断删除。

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

PowerShell 的 `Invoke-ArtifactCapacityGate` 与 `Enter-ArtifactWorkflowCapacitySession` 必须满足公共
容量判据；startup 与 maintenance 均失败关闭，不提供容量 warning 放行选项。空间不足时先沿既有
maintenance 清理机制恢复容量，再重新准入；startup 本身不删除载荷。会话提高新增空间承诺时也须
重新准入，历史会话中的 warning 字段不能绕过。容量工作耗时的性能 warning 不改变该硬判据，
CPU、内存和时间的运行策略由各自既有边界管理，不与容量准入混用。

maintenance 默认只返回聚合 receipt：`resident_bytes`、`free_bytes`、`capacity_gap_bytes`及
`removed.bytes/object_count`；PowerShell 适配器直接消费这些字段。逐项处置清单仍由 owner 收据保存，
只有显式审计才使用 `--detailed-output`，不为启动或失败报告展开全部删除记录。

公共 JSON 原子落盘在 Windows 替换遇到错误 5/32/33 时，复用已刷盘临时文件最多尝试五次，累计
等待不超过 0.75 秒；持续失败仍抛出原异常，保留旧目标并清理此次临时文件，不修改权限。
[Windows 官方错误码](https://learn.microsoft.com/zh-cn/windows/win32/debug/system-error-codes--0-499-)
分别定义拒绝访问、共享冲突和锁冲突；错误 5 不保证是瞬态，上述有界重试是本项目策略。

增量台账由本入口及既有发布/删除/终态收尾入口维护，而不是新建第二套治理工具。台账最小记录为：
`artifact_root`身份、对象路径/角色、字节数、不可变代际身份、状态、最后一次成功发布/删除收据、活动峰值承诺
和待核对标记；台账缺失、版本不符或存在待核对标记时，startup只能阻塞并请求maintenance校准。台账不能用
文件大小或时间戳冒充内容验证，也不能在发布、删除或运行收尾之外自行推断外部写入；首次建立或发现不一致时
才做一次完整扫描，之后按收据增量更新。

### 中断与旧身份

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
已通过完整身份核验并绑定为input的外部来源manifest，包括冻结到本run `inputs/`的副本，
仅作为provenance保留，不继承其引用的载荷。相同路径若也绑定为output，仍执行严格的本地child身份与owner校验。

同一入口也接受已结束成功或失败实验的 owner 明确退出：`-Owner <project>` 与
`-OwnerAbandonmentReason "<完成用途及无人继续消费的具名原因>"`。此模式与 replacement/compatibility
参数互斥，普通模式仅接受非Formal、manifest与summary一致的封存success/failed/interrupted solver_review；
中断仅允许owner明确退出，superseded模式仍只接受success/failed；仍检查租约、活动下游依赖和精确载荷清单，
保留全部小证据，不将实验退出冒称为被新run取代。待删除的本地重型文件继承manifest已封存身份，
核对路径、类型和大小而不重复全文哈希；小证据仍校验内容。
同run的局域子manifest仅在父manifest已封存该严格本地后代时继承；子终态、owner和小证据仍须一致，
不从目录搜寻未封存manifest，子PA同样不重复全文哈希。已完整核验的外部input manifest仅作为来源记录保留，
不继承其重载荷；外部output manifest仍拒绝，不能冒充本run的局域子运行。
完成receipt标为`completed_experiment_payload_retired`，保留实际`target_terminal_status`，不将失败改为成功；由原`--verify`入口验证，原superseded模式及旧receipt语义不变。

已停止的compact checkpoint私有原生PA族仅可在同一owner入口显式提供
`-RuntimeCheckpoint <manifest已封存的族清单> -ConfirmWritingStopped`后退出；普通checkpoint仍拒绝。
族成员继承该小清单的既有身份，核对精确路径、大小和保护，不重哈希PA、不改原科学三件套。
若用户已明确放弃仍引用此族的历史checkpoint，可用`-ApprovedStoppedConsumers <精确run数组>`逐项声明；
owner须确认其writer及子进程均已停止，plan/receipt冻结各自小证据，apply及verify复核同一清单。
该批准仅适用于本次目标；未列消费者、新消费者、身份漂移、租约和当前GUI继续阻塞。
历史IOB保留但标为需重装配，不能将其称为仍可直接使用的交付。
此checkpoint退役后以完整`--verify`通过的receipt沿原`seal-checkpoint`收尾实际light-evidence占用，
仅该明确范围可解除原stopped-payload保留pin；不将checkpoint改为科学终态，也不放宽普通finalize-ready。

终态run经`invoke_solver_review_retirement.ps1 -Apply`退役且启用容量生命周期时，wrapper在同一租约内自动调用
原`run_capacity_lifecycle --action finalize-ready`收尾；直接调用Python退役API时仍须显式收尾。
收尾失败将非零退出并说明载荷已删、账本待恢复，此时只恢复容量收尾，不重复删除；checkpoint仍按上述专用`seal-checkpoint`路径处理。
仅当普通`retention_actions.json`不存在时，
该入口允许以原验证器通过的完整solver_review退役receipt作为处置完成证据；已有但损坏或未完成的普通receipt不得被替代。
后续实际inventory、轻证据预算及无重载荷检查不变，不补造普通receipt，不改原科学终态或manifest。

已明确停止写入、被更新 GUI 准备包取代的未飞行 `solver_review` checkpoint 可在同一
`solver_review_retirement.py` plan/apply 入口显式提供 `--prepared-gui-checkpoint
--confirm-writing-stopped`。默认为 supersession：两端必须是 `checkpoint` manifest、
`gui_replay_prepared` summary，以及具名 `native_gui_replay`、私有 Refine/IOB 未飞行合同；
GUI Fly 和轨迹一致性标记必须为 false。两端须保留绑定的 GEM、IOB、连续编号 PA family 和
冻结科学 source manifest 的身份，新包更新且项目/mode及声明兼容角色符合原合同。
目标的重载荷沿用封存身份和精确大小，不为删除重新扫描 PA 内容；替代包仍完整复核。
所有轻量文件、原三件套保留，普通下游依赖、容量租约和 current GUI source 保护继续适用。
apply 仍必须在公共 HostExecutionLease 内执行；原 terminal 和 compact runtime 模式不接受此 summary 别名。
同一 owner 也可在此显式 prepared GUI scope 下提供 `--owner` 和非空 `--owner-abandonment-reason`，
明确放弃已停止且未飞行的准备包；此时不得提供 replacement 或兼容性声明，不推断替代包存在。
目标仍须通过同一非 Formal、未飞行、停写、冻结库存与全部消费者/租约保护检查；仅删除原生重载荷，
三件套、轻量证据和重建输入保留。收据沿用 `completed_experiment_payload_retired`，原科学状态保持 checkpoint。
余量沿前述 `seal-stopped-payload` 原 owner/原保留理由闭合，不把 checkpoint 或 GUI 准备状态改称成功。

apply前先在target内原子写入pending receipt，再按精确清单复核路径、常规文件类型和字节数后删除；
重型载荷沿用已封存身份，不在删除时重复全文哈希。完成状态按上述模式写为`superseded_payload_retired`
或`completed_experiment_payload_retired`；receipt保存完整清单、被删/保留集合、原manifest及适用的替代run绑定。
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
绑定只按[多极杆术语](../../projects/rf_multipole_ion_optics/docs/IMPLEMENTATION.md#统一术语)解释。
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
需要消费状态的入口调用[`load_component_particle_state_csv`](component_particle_state.py)，一次读取、解析和校验后
返回按原行序的typed `rows`及原有`report`；整数、实数与可空字段按Schema解析，标识字符串不转数值。
`validate_component_particle_state_csv`复用同一入口并仅返回报告；读取不会重写输入字节。

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
两个完整pose相同时直接返回该局部frame的精确单位变换，不做矩阵往返，避免给原本已在目标frame的源引入舍入位移。

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

项目合并通过`retired_project_descriptors`绑定原字节冻结的旧描述符：仓库相对路径、字节数、SHA-256及
来源commit必须明确，旧owner和其更早aliases仍使用原artifact位置、记录身份及资格边界。
[`artifact_identity_archive.py`](artifact_identity_archive.py)只读展开这些身份；旧capabilities不进入活动项目注册，
行政改名的`legacy_identities`也不因合并改写为新的归档owner。
`New-RunPackage`在创建目录和登记容量前调用同一身份检查，拒绝明确退休owner及其aliases创建新run；
其他项目、`instrument_assembly`及未声明退休的既有调用边界保持不变。历史读取与验证继续允许，
发现旧描述符字节、路径或只读策略不符时失败关闭，不重写manifest或晋级原结果。

## 从自然语言到计划

当前边界是“Agent理解自然语言，确定性工具验证合同”：Agent先把需求翻译成`design_request` JSON，
保留为`proposed`，由使用者批准后才能请求formal证据。校验结果固定为`READY`、
`NEEDS_CLARIFICATION`、`NEEDS_PROJECT_COMPLETION`、`NEEDS_NEW_PROJECT`或`UNSUPPORTED`，不会因为
项目目录存在就假定能力已经完成。

`target.structural_variant_id`显式选择项目描述符声明的结构变体，并仅使用该变体的能力、指标和资格等级。
同一功能存在多个结构候选而未指定时返回`NEEDS_CLARIFICATION`，不会按成熟度或某个目标指标代选结构；未知变体返回
`UNSUPPORTED`，不回退其他变体。没有结构变体的既有项目仍按原功能合同校验。
公共变体登记只定义`variant_id`、`display_name`和`capability_ids`及能力归属，不要求每种器件提供多极杆字段。
OA的二区／三区和RF的四／六／八极使用同一选择语义；极数、区数与设计身份的一致性由所属项目合同校验。
具名设计注册使用`design_profiles.schema.json`的v3 `project_design_profile_registry`：公共层验证来源身份、
变量指针与范围、包络引用和能力归属；项目编译选项放在`project_options`并由项目schema与解析器验证。
物理请求、拓扑和单位仍由提供者解释，通用登记通过不表示任意项目已具备参数编译或求解能力。
显式`target.mode`先在所选结构内筛选对应能力，再判断其成熟度；未知模式不能回退同结构的其他能力。

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
该文件使用统一`project_execution_profiles`合同，供公共编译器发现已有入口；资源预算和项目运行配置由
项目的runtime配置持有，不冒充公开执行能力。具体profile的物种、输入、目标与资格限制仍查项目入口和合同。
执行编译器只生成命令预览，没有执行开关：

```powershell
.\.venv\Scripts\python.exe -m common.contracts.compile_execution_plan <design_plan.json>
```

结果为`EXECUTION_READY`、`AWAITING_APPROVAL`、`NEEDS_RUNTIME_INPUTS`或`NEEDS_IMPLEMENTATION`。
`EXECUTION_READY`只表示需求已批准且现有入口能够消费声明字段并评价所请求的目标指标；它不表示
求解已经运行或指标已经满足。只完成结构构建的runner不得把分辨率等未评价目标列为支持。
需要显式粒子表、RF幅值等运行绑定的profile使用`--bind key=value`提供预览值。编译器会验证入口文件、
生成受命名合同约束的子run ID，并保留项目profile的限制说明，但不会创建artifact运行目录。
需要项目解析的profile通过可选`runtime_binding`声明项目内Python `entrypoint`及其`required_bindings`子集。
入口固定实现`resolve_execution_binding(repo_root, project_id, bindings)`，只接收声明的selector，返回且仅返回
`project_id`、`structural_variant_id`、`authorized_run_id`；最后一项为合法run ID或`None`。公共编译器校验
声明路径、selector归属、回包字段和类型、项目身份及能力的唯一结构归属，仅注入已校验的运行身份。
项目解析器拥有科学输入、注册选择和运行身份的来源解释；公共层不读取项目私有预算结构。
缺少selector时保留缺失输入的预览；selector齐全但其他输入缺失时仍验证该选择。未知、空值、跨结构选择、
调用者覆盖受保护上下文以及完整绑定后未展开的命令占位符均被拒绝。无声明的profile沿用原有直接绑定。
预览中的`authorized_run_id`只记录项目解析出的运行身份；商业执行授权仍由项目runner与预算合同验证。

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
