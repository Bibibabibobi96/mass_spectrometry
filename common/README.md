# 公共机制与维护入口

本目录维护跨项目复用的运行、数据和软件机制。器件几何、物理参数、科学工作流及资格由所属项目或
集成维护；执行命令与工具链先查[操作指南](../docs/OPERATIONS.md)，知识归属见
[仓库架构](../docs/REPOSITORY_ARCHITECTURE.md)。本页导航公共实现，并说明根级门禁和资源调度的维护边界。

## 按任务定位

| 要做的事 | 实现与说明 |
|---|---|
| 排查L1/L2选了哪些阶段、失败退出或日志 | [门禁编排](#门禁编排)、[唯一目录](gate_catalog.json)、[并行调用器](parallel_gate_support.ps1) |
| 排查资源等待、进程归属、阶段切换和释放 | [主机资源实现](#主机资源实现)、[PowerShell入口](host_execution_lease.ps1)、[调度器](host_resource_scheduler.py) |
| 创建run、冻结输入、发布manifest或维护容量 | [机器合同与生命周期API](contracts/README.md) |
| 发现项目、校验设计请求与预览执行计划 | [项目发现与规划](contracts/README.md#项目发现) |
| 连接组件、解析完整配方与局部范围 | [公共连接合同](integration/README.md) |
| 构造母群、释放与粒子身份 | [离子释放](ion_release/README.md) |
| 计算峰宽、比较场或配对粒子数据 | [公共分析](analysis/README.md) |
| 维护COMSOL启动器与共享小模型 | [COMSOL实现](comsol/README.md) |
| 维护SIMION执行、PA缓存、批次与恢复 | [SIMION实现](simion/README.md) |
| 维护STEP导入、SolidWorks生成和引用检查 | [SolidWorks桥接](solidworks/README.md) |
| 定位源码与artifact路径 | [路径机制](paths/README.md) |

只进入本次涉及的实现边界。文档结构与链接由`verify_documentation.ps1`和`documentation_links.py`检查；
跨语言实现规则由`verify_development_standards.py`检查；受管文本字节由`verify_repository_text_bytes.py`检查。
这些门禁的统一调度仍由下述目录负责，不在本页维护第二份阶段名单。

开发标准门禁默认只执行决定PASS／FAIL的硬检查，消费者审计报告`NOT_REQUESTED`，不把未扫描写成零候选。
显式`--audit-consumers`审计Python顶层私有函数：正式入口模块可达的引用、仅测试可达的引用、
CLI／回调用途待核实、无静态引用候选；同时传`--show-review`时列出位置、符号及已知消费者模块。
单独`--show-review`只列复杂度提示，不启动消费者审计。
显式审计复用同次硬检查解析的AST，不保存跨运行身份缓存。提交钩子从Git索引读取检查器及受管源码，
检查实际暂存内容；工作树中的未暂存修改不能掩盖暂存版本的错误。L1和提交钩子的文件内硬规则只检查明确改动的受管源码；
规则自身、配置、未知路径或源码删除扩大到完整集合，FullScope／L2及直接无参数调用仍全量检查。
`--path <path>`可重复指定；L1用任务内临时路径清单传输，摘要保留实际路径，检查结束即清理该清单。
显式消费者审计始终全量，不能与局部路径或暂存检查混用。
审计使用execution profiles与门禁目录中的显式入口、字面`-m`命令及Python导入／符号引用；
它是包含未执行分支的模块级静态证据，不证明函数实际执行。字符串、装饰器和动态调用保留不确定性，
Lua／MATLAB／PowerShell的引用亦不会被当作无用；未解析的嵌套或动态入口仍需人工核实。
无静态引用只产生待复核候选，不能据此自动删除；退役仍须核对真实入口、声明依赖、独立CLI与冻结用途。

## 门禁编排

`common/gate_catalog.json`是L1路径路由、依赖等级、阶段前置关系和L2成员身份的唯一机器目录；项目或
integration新增公开门禁时必须注册，目录与文件系统不一致即失败。集成route通过
`runtime_dependencies_path`引用已有运行依赖库存；公共catalog读取器将其`source_repo_path`展开为精确匹配，
新增依赖不再手抄第二份路由表。缺失库存、未知版本／身份或缺失来源文件在规划时失败。
需要补充或精确选择测试的owner在同一目录声明`test_selection`。明确的新增／修改测试模块进入实际
执行集合；生产与测试混合改动保留原owner门禁。删除、重命名旧路径、共享fixture、包初始化及未知
测试目录变化扩大到所属owner发现，并报告选择原因。Git差异保留重命名两端，不能只看到新路径。
模块集合由项目入口合并去重；Core的成功不能替代未运行测试的证据。
显式Python测试命令保留目录声明的发现根作为临时导入路径，并在返回时恢复调用者环境，
使既有目录级导入与未知子目录的模块枚举同时成立。
仓库只保留
`common/verify_changed.ps1`这一个L1入口，不提供旧名称兼容脚本。`.github/workflows/lightweight-gate.yml`
在push只运行L1；L2仅可由`workflow_dispatch`人工启动，不对pull request自动运行全仓回归。
L1可能包含完整integration回归，CI预算须覆盖环境安装和整轮门禁，不能只按单个Core检查的耗时估计；
当前执行预算读取[GitHub工作流](../.github/workflows/lightweight-gate.yml)。门禁超时不等同于科学求解失败。
两个CI job在门禁前将后续步骤的`TEMP/TMP`设为[官方`RUNNER_TEMP`](https://docs.github.com/en/actions/reference/workflows-and-actions/variables)的规范绝对路径，
通过[`GITHUB_ENV`](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#setting-an-environment-variable)传递，避免Windows用户目录短别名与长路径在测试夹具中混用。

L1的`-PlanOnly`使用同一目录先给出`stdlib`或`locked`依赖等级；GitHub对只需标准库的文档和门禁
合同范围跳过完整科学Python环境安装，任何未明确分类、项目注册表、Python lint、项目/集成、依赖声明或
FullScope均失败关闭为`locked`。本地并发默认为`min(8, logical_processors)`，可用
`-MaxConcurrency 1..32`显式覆盖；GitHub托管runner固定为2。这是门禁组内的并发上限，实际阶段还须通过
下述机器级资源准入；提高该值不会绕过预算。并行阶段即时报告进程启动与完成，启动行的`LOG_PATH`
指向执行中逐行刷新、可直接读取的阶段日志；完成后仍按稳定顺序回放完整日志，不在内存缓存整个阶段。
成功组清理临时目录；失败组保留阶段日志、请求JSON和`group_failure.log`，输出
`GATE_DIAGNOSTICS=RETAINED`及精确清理命令。串行fallback也写入同一阶段日志，不能只有控制台错误。
复核完成后沿[操作指南](../docs/OPERATIONS.md#分层门禁)清理，不按年龄自动删除失败证据。
两个根入口均输出`GATE_SUMMARY_PATH`：默认是系统临时目录中的独立小JSON，可用`-SummaryPath`指定
不存在的目标文件。摘要保留选中原因、实际命令、依赖、环境、阶段状态、耗时、退出码和日志保留情况，
成功清理详细日志后仍保留摘要。计划先落盘，阶段完成即更新；可捕获的失败或中断按实际状态收尾，
硬杀或断电后的`PENDING/RUNNING`只表示未完成，不能解释为通过。日志路径标为未保留时不可用。
CI使用[官方artifact action](https://github.com/actions/upload-artifact)在`always()`步骤上传摘要和本次保留的门禁诊断。
摘要是观测记录，不是跳过后续验证或跨改动复用PASS的凭证。
文档检查保持独占；随后短检查先进入同一执行器，其余阶段按catalog顺序稳定排队。
只有`requires_stages`全部PASS的阶段才可启动，失败前置的后继即时标为`BLOCKED`；
前置缺失、未选择或无法取得ready阶段也明确阻塞，不挂起等待不存在的工作。
L1首个失败后停止派发待队阶段，已启动阶段自然收尾；L2在环境及目录初始化成功后继续独立检查，
包括文档检查失败之后的独立诊断，最后汇总失败。无日志与sidecar的既有串行fallback先取得实际结果，
才允许依赖它的阶段启动。资源许可、嵌套预算与进程数上限保持原公共入口。
`queue_seconds`从本执行组开始到派发，含组预热、依赖及并发槽等待；`resource_wait_seconds`单独测量
host许可等待，`execution_seconds`只测Action，`cleanup_seconds`测许可释放与环境恢复。
`launch_seconds`只测`Start-Process`调用，不能解释为全部子PowerShell初始化；`process_elapsed_seconds`
从该调用开始到父进程确认退出，包含轮询观察延迟。原`elapsed_seconds`仍是stage wrapper总计时，
整轮摘要从建立摘要到收尾计时，均不是整个根PowerShell进程墙钟；这些范围不能相加推算另一范围。
未实际观测的阶段字段为null，测试数量与skip不从退出码猜测。
当前没有同时绑定测试集合、执行环境和可比工作量的历史耗时authority，因此不采用自动最长任务优先，
也不依据stage总耗时或文件长度拆分MR／assembly模块。保留现有owner测试单元及确定性顺序，
减少错配样本和新增调度维护成本；代价是本轮不优化最长任务对整轮结束时间的影响。
历史耗时测量见[门禁审计](../docs/history/20260802__gate-system-audit.md)；
L2用于显式全仓审计，纯文档提交不默认运行L2。
L1/L2共用命令调用器直接绑定函数脚本块；仅冻结每项路由参数，不对调用器本身建立动态闭包，
避免其捕获旧的`LASTEXITCODE`而把失败报告为成功。公共回归实际执行成功及非零退出探针。
公共预算阶段执行期间将控制台输出编码设为UTF-8，退出时恢复原编码，嵌套阶段同样遵守；
避免隐藏Windows宿主的CP936经Python传给子PowerShell，导致中文错误日志解码失败并掩盖原始错误。

改动范围Ruff检查沿锁定版本的[官方参数文件](https://docs.astral.sh/ruff/configuration/#argfile-support)
传递原文件集合，保持逐文件范围及非零退出语义；阶段结束时清理临时参数文件。
这样避免大量绝对路径超过[Windows CreateProcessW的32,767字符上限](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw)，
不另建分批启动器，也不以缩短路径或修改UTF-8日志语义规避进程限制。

## 主机资源实现

粒子拆批与默认并发遵循[开发标准](../docs/DEVELOPMENT_STANDARDS.md#独立粒子与耦合求解的调度)，
随机重复运行的验收遵循[验证方法](../docs/science/VALIDATION_METHODS.md#随机碰撞与重复运行)。
PA等昂贵阶段复用及中断恢复遵循[统一复用与恢复规则](../docs/DEVELOPMENT_STANDARDS.md#昂贵阶段复用与中断恢复)。

本机门禁与SIMION/COMSOL运行通过[`host_execution_lease.ps1`](host_execution_lease.ps1)
进入同一[`主机调度器`](host_resource_scheduler.py)。当前默认账本位于工作区同级产物根的
`artifacts/common/host_resources.sqlite3`；同一父目录中的工作树共用该默认值，跨父目录不能假定自动共用。
准入和status按显式绝对路径、`MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH`、默认路径的顺序选择；
不同工作树必须显式部署到同一绝对账本，不能各建一份而重复分配资源。环境路径只用于受控部署或隔离测试，
生产调用不得用它绕过正在运行的申请。切换部署路径前必须等待原账本的owner、后代和等待者全部结束，
不能复制活跃SQLite或让两个账本并行准入。资源配置、已分类阶段及测量依据只维护在
[`host_resource_policy.json`](host_resource_policy.json)，不在项目脚本复制容量阈值。

CIM不可用时，原生观测每轮只用一次
[Toolhelp进程快照](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/nf-tlhelp32-createtoolhelp32snapshot)
建立父PID表，循环查表，不跨事务缓存。
[PROCESSENTRY32W](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/ns-tlhelp32-processentry32w)
只有PID／父PID，不提供创建身份；创建时间继续由.NET或
[GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes)
读取。抓表后才创建的同PID身份不能绑定旧父关系，进入既有unknown处理；缺少父项仍按原parent=0语义。
这是基于Windows官方API的仓库实现，资料核验日期2026-10-25；不把进程名当身份或console豁免依据。

阶段通过`Enter-HostResourceStage`申请CPU核数、内存字节、批量I/O槽位及具名独占资源，取得许可后
才能启动工作；相同独占资源名不能同时授予两个活动阶段。预算是准入声明，不是操作系统强制限额，
也不修改科学参数或求解器精度。中央策略只区分重任务与轻任务：只有阶段名单列出的PA refine、离子飞行、求解及理论计算
占用唯一重任务许可，重任务之间串行。所有未列入名单的阶段默认轻任务，包括`SIMION/COMSOL`角色，采用中央声明
额度，不要求先完成峰值测量；声明额度不代表测得的占用上界，已有测量的检查可使用较小额度。
PA输入准备、GEM转PA、缓存物化与纯IOB组装默认按轻任务准入，不因属于PA工作流而整段判重；
原生refine以及已知内部调用refine的Lua操作须在重阶段执行，结束后可回到轻准备阶段。
重任务身份与I/O标记相互独立：SIMION飞行仍持有唯一重任务许可；会批量读写的阶段以非零`io_slots`
标记启用目标卷实时压力检查。当前没有可复现基准支持固定并发流数，因此主机`io_slots=0`明确表示
telemetry-only，不执行静态槽位求和，也不会因猜测的槽数误报`io_budget_full`；若将来用吞吐基准启用正数
容量，它才表示所有活动阶段的并发I/O权重上限。CPU、内存、重任务互斥和实时I/O压力始终独立生效。
轻任务可与重任务或其他轻任务并行；实际CPU加上
轻任务预计核占用、累计预算、可用内存及I/O压力必须允许新增工作。观测不完整时停止新增准入，不能把缺少
观测解释为资源空闲。实际反复表现为高负载的普通任务应在中央策略标为重任务，不在项目复制分类规则。
排队公平性按重、轻同类约束；等待重任务不会仅因轻任务多次通过而阻挡后续轻任务，资源不足仍需等待。

L1/L2按实际阶段申请预算，已持有父token的嵌套组在父预算内串行，不能重复申请或增加嵌套并发。
COMSOL公共入口已支持准备、求解和后处理边界，具体调用见
[COMSOL主机资源阶段](comsol/README.md#主机资源阶段)。本次服务器完全退出后的`COMSOL/postprocess`
显式使用普通轻任务策略；`COMSOL/solver`列为重任务，准备和未分类阶段默认轻任务。入口调用
`Enter-HostExecutionLease -Role <角色> -Stage <阶段>`按中央名单解析；省略`Stage`时为`unclassified`轻任务。
`unknown_peak`只表示峰值未知，不授予重任务许可。自定义预算不能覆盖中央阶段分类。
此入口不再获取旧mutex；内层阶段继承
父申请不会自动缩减其全程预算。当前接入不表示所有项目或内部求解阶段都已经完成资源细分。

SIMION公共执行器在原生refine/fly启动或进入内部飞行批次调度前通过`Assert-HostResourceHeavyStage`核验同一父许可；
已知内部调用refine的Lua由调用入口设置重阶段，不能仅按Lua命令名判断其开销。
内部worker仍由既有SIMION规划器按实时CPU和内存准入，不逐worker申请主机许可，也不传递第二套动态额度文件。
重任务许可不代表包下所有空闲资源；轻任务及其他系统进程的实际占用仍进入内部启动判断。

阶段切换用`Update-HostResourceStage`重新准入，同时显式声明仍需保留的内存；账本保留观测到的
存活进程内存，不能因进入等待或传入零值就视为已释放。仍有本次工作子进程存活时禁止切换阶段；先完成
子进程清理并确认退出，才可降级资源，避免释放仍在使用的服务器或具名独占资源。入口登记本次子进程并在正常、失败或中断
路径调用`Exit-HostResourceStage`。若工作子进程仍存活，释放请求不会撤销其占用；父进程崩溃后也按
PID与创建时间继续识别后代，确认相关进程退出才回收。状态可通过`Get-HostResourceStatus`查询。
同一PID曾对应多个已登记创建身份时，调度器保留各自身份并按相容父身份判断后代，
既保留旧父退出后仍活的孤儿，也拒绝未登记的新PID实例的无关后代；工作后代使用同一判据。
调度器不杀进程；排查无用占用须结合命令、归属、日志和实际进展，不能仅凭低CPU利用率终止
可能正在I/O、等待许可证或保存结果的工作。观测失败不清空既有预约。
并发事务使准入或阶段切换的采样过期时，入口退避后重新采样并报告等待；正常竞争不算工作失败，陈旧观测不能用于准入。
释放不申请新资源：若当前账本与传入快照都确认该租约没有非owner、非系统console的存活后代，
且owner创建身份有效、相关身份观测完整，公共事务只释放该租约，不推进全局观测水位、不重新准入
或回收其他租约。这样无关排队轮询不能让较慢的正常释放无限饥饿；任一观测仍有后代或身份未知时继续保留。
唯一的子进程例外是可执行路径精确匹配 Windows 系统映像的`conhost.exe`：它不阻止阶段切换或显式
释放，实际内存仍进入系统观测，活动预约期间仍记录其身份与内存。普通工作后代不享有此例外。

旧Windows mutex与新账本没有双轨兼容。切换前须确认旧入口持有者及其子进程已结束，再从当前
公共入口启动新任务；已启动的旧PowerShell不会因工作树文件更新而自动迁移。不得删除账本或
另设账本来释放仍在运行的任务。

真实求解器入口在发布终态 manifest 后，向共享租约报告 `success`、`failed` 或 `interrupted`；仅持有
`SIMION`或`COMSOL`租约的顶层运行因此播放一次本机系统提示音（成功为三音上行完成提示，其余为 Hand）。提示不属于科学
输入、run identity 或证据，声卡不可用不能改变终态；设置进程环境变量 `SIMULATION_COMPLETION_SOUND=off`
可静默。阶段切换、批次、45 秒资源观测、重试、门禁和继承租约不得单独提示。

数值探索参数可在活动项目的声明范围内自由修改：L1只校验该项目的参数schema、单位/范围、resolved合同和
必要输入生成，不自动启动商业求解器，也不检查无关项目。若改变几何、电压、粒子源、网格、RF相位或跨项目
接口，旧Candidate/Formal证据不再适用；只有在要声明新结果时才运行该项目相应的L3物理链。

### 进程观测与预算

单进程观察器`Invoke-ResourceBudgetedProcess`只接收调用者在冻结边界解析的`-Limits`对象，
观察收据记录完整limits；`Complete-ResourceUsage`只读取已有usage收据收尾，不重新解析预算。
Python向PowerShell传递派生预算可使用任务临时JSON，解析后由调用者finally清理；冻结的工程预算仍是输入权威。

墙钟、目录体积、进程树工作集或可用内存预算越限，每类只写一次`RESOURCE_BUDGET_WARNING`，
不据此停止健康进程。低CPU、暂时无输出或采样空洞也不是停止依据。原生进程明确失败时停止启动同批新工作，
已经运行的健康同级自然结束。只有持续低于中央策略的物理内存危险保留量才进入受管停止，并记录危险原因。

`New-RepositoryProcessObservation`和`Update-RepositoryProcessObservation`供包装器和COMSOL入口复用观测；
它们不启动进程、调度、重试或发布科学终态。物理危险阈值只来自[主机策略](host_resource_policy.json)，
无Limits时不写usage；目录或usage写入失败只告警，不能遮蔽已经确认的物理危险。
