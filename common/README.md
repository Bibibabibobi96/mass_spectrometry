# 公共机制与维护入口

本目录维护跨项目复用的运行、数据和软件机制。器件几何、物理参数、科学工作流及资格由所属项目或
集成维护；执行命令与工具链先查[操作指南](../docs/OPERATIONS.md)，知识归属见
[仓库架构](../docs/REPOSITORY_ARCHITECTURE.md)。本页导航公共实现，并说明根级门禁和资源调度的维护边界。

## 按任务定位

| 要做的事 | 实现与说明 |
|---|---|
| 排查软件验证选了哪些阶段、失败退出或日志 | [门禁编排](#门禁编排)、[唯一目录](gate_catalog.json)、[并行调用器](parallel_gate_support.ps1) |
| 排查资源等待、进程归属、阶段切换和释放 | [主机资源实现](#主机资源实现)、[PowerShell入口](host_execution_lease.ps1)、[调度器](host_resource_scheduler.py) |
| 创建run、冻结输入、发布manifest或维护容量 | [机器合同与生命周期API](contracts/README.md) |
| 发现项目、校验设计请求与预览执行计划 | [项目发现与规划](contracts/README.md#项目发现) |
| 连接组件、解析完整配方与局部范围 | [公共连接合同](integration/README.md) |
| 构造母群、释放与粒子身份 | [离子释放](ion_release/README.md) |
| 计算峰宽、比较场或配对粒子数据 | [公共分析](analysis/README.md) |
| 维护COMSOL启动器与共享小模型 | [COMSOL实现](comsol/README.md) |
| 维护SIMION执行、PA缓存、批次与恢复 | [SIMION实现](simion/README.md)；批次协调使用 `Invoke-SimionBatchPhase`，科学物化和接受条件由调用方提供 |
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
检查实际暂存内容；工作树中的未暂存修改不能掩盖暂存版本的错误。Changed范围和提交钩子的文件内硬规则只检查明确改动的受管源码；
只有检查器或规则本身变化才扩大文件局部硬规则扫描；配置、未知路径及源码删除不自动扫描全库。
Repository、Changed FullScope及显式无参数检查仍执行其声明的完整软件范围。
`--path <path>`可重复指定；Changed范围用任务内临时路径清单传输，摘要保留实际路径，检查结束即清理该清单。
显式消费者审计始终全量，不能与局部路径或暂存检查混用。
审计使用execution profiles与门禁目录中的显式入口、字面`-m`命令及Python导入／符号引用；
它是包含未执行分支的模块级静态证据，不证明函数实际执行。字符串、装饰器和动态调用保留不确定性，
Lua／MATLAB／PowerShell的引用亦不会被当作无用；未解析的嵌套或动态入口仍需人工核实。
无静态引用只产生待复核候选，不能据此自动删除；退役仍须核对真实入口、声明依赖、独立CLI与冻结用途。

## 门禁编排

`common/gate_catalog.json`是改动路径路由、依赖等级、阶段前置关系和Repository成员身份的唯一机器目录；项目或
integration新增公开门禁时必须注册，目录与文件系统不一致即失败。集成route通过
`runtime_dependencies_path`引用已有运行依赖库存；公共catalog读取器将其`source_repo_path`展开为精确匹配，
新增依赖不再手抄第二份路由表。缺失库存、未知版本／身份或缺失来源文件在规划时失败。
专用`oatof_*`和`multipole_*` schema由catalog中的精确owner匹配声明；读取器据此从公共合同目录的
保守fallback中排除这些已知文件，保留实际runtime消费者与统一schema元校验。
例如`oatof_three_zone_stage_report`的真实owner是单反射项目；它的改动不再触发无关RF、电子枪或EI门禁。
未登记的新schema、公共validator、生命周期和注册语义仍沿保守路由扩大，不按文件名前缀猜测新归属。
OA提供者的普通tests变更留在OA owner；跨项目生产目录依赖不包含该测试子树。
集成夹具实际导入的`test_bare_three_zone_component.py`及其测试包初始化仍精确触发集成回归；
OA生产代码与runtime库存声明的真实消费者依赖保持原路由。
需要补充或精确选择测试的owner在同一目录声明`test_selection`。明确的新增／修改测试模块进入实际
执行集合；生产与测试混合改动保留原owner门禁。删除、重命名旧路径、共享fixture、包初始化及未知
测试目录变化扩大到所属owner发现，并报告选择原因。是否仅为测试变更按该owner实际路由影响计算；
其他owner测试和文档不迫使全量发现，SIMION公共测试也使用同一选择机制。
Git差异保留重命名两端，不能只看到新路径。
模块集合由实际owner选择；原expected-values、gate、CLOC、dependency及schema元校验触发关系
归入公共合同owner的`test_selection.dependencies`，不再维护covered专属路由和去重分支。
短分析模块逻辑上独立选择，按stdlib／locked分别合为unittest执行批次，逐测试计时及失败保持。
Core的成功不能替代未运行测试的证据。
当前Repository实际规划39阶段：4个全局职责、33条逻辑route去掉9条分析独立进程、1个
integration纯Ruff preflight和1个公共合同父进程，再加2个分析批次、8个MR／integration测试分片
及3个公共合同分片。相比4058基线45阶段减少6；逻辑route由37减为33是四条covered归回公共合同选择，不能再算一次任务减少。
九个短分析模块按依赖分为stdlib四模块、locked五模块，保留标准库范围无需安装科学环境的能力，
因此是九进程收敛为二，而非混装成一个。该数量是当前选择结果，不是未来配额或实际native进程计数。

公共合同沿现有分片机制按模块分为三组，覆盖集合保持完整且各模块恰执行一次。
Owner别名回归核对实际unittest模块与catalog所属发现集合（包括重复数量），
不以是否存在未分片的阶段名称判断完整覆盖。
权重来自2026-10-30完整运行的52模块、899测试逐项计时（合计855.085秒），只用于排队；
三组各约285秒是权重估算，不能作为实测提速。父级已完整选择的模块直接传给分片，
子进程消费已编译请求；仅改指定测试时不展开完整owner。部分root的扩展不冒充完整scope。

显式Python测试命令保留目录声明的发现根作为临时导入路径，并在返回时恢复调用者环境，
使既有目录级导入与未知子目录的模块枚举同时成立。
软件验证父入口只解析一次catalog、实际模块与分片；子阶段通过同轮`InternalRequestPath`消费已解析命令，
不重新规划所有route或枚举全部测试。前置仍由父级依赖准入保护，子阶段仍调用原计时、GATE资源和失败传播入口。
该请求只运输执行计划，不保存PASS，也不提供跨提交缓存；Ruff和改动范围标准检查的长参数列表由同一调用器临时文件传递并清理。
`common/verify.ps1 -Scope Changed|Owner|Repository`是唯一软件验证入口；Owner范围必须提供`-Owner`。
普通命令自动规划、执行并汇总，`-PlanOnly`用于可选预览。Changed的`-FullScope`保留原Core／Static
选择，不等于Repository。原两个驱动已移除，活动消费者统一使用此入口。
`.github/workflows/lightweight-gate.yml`在push运行Changed，Repository由`workflow_dispatch`启动。
Changed可能包含完整integration行为回归；CI预算包括环境安装与整轮验证，不能按单个Core检查估算。
两个CI job在门禁前将后续步骤的`TEMP/TMP`设为[官方`RUNNER_TEMP`](https://docs.github.com/en/actions/reference/workflows-and-actions/variables)的规范绝对路径，
通过[`GITHUB_ENV`](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#setting-an-environment-variable)传递，避免Windows用户目录短别名与长路径在测试夹具中混用。

`-PlanOnly`使用同一目录先给出`stdlib`或`locked`依赖等级；GitHub对只需标准库的文档和门禁
合同范围跳过完整科学Python环境安装，任何未明确分类、项目注册表、Python lint、项目/集成、依赖声明或
FullScope均失败关闭为`locked`。本地并发默认为`min(8, logical_processors)`，可用
`-MaxConcurrency 1..32`显式覆盖；GitHub托管runner固定为2。这是门禁组内的并发上限，实际阶段还须通过
下述机器级资源准入；提高该值不会绕过预算。并行阶段即时报告进程启动与完成，启动行的`LOG_PATH`
指向执行中逐行刷新、可直接读取的阶段日志；完成后仍按稳定顺序回放完整日志，不在内存缓存整个阶段。
unittest 测试完成时报告耗时，首个异常发生时增量回显 traceback；其他已启动阶段自然收尾。摘要在阶段完成时保存已观测的逐测试耗时，非 unittest 阶段没有该数据。成功组清理临时目录；失败组保留阶段日志、请求JSON和`group_failure.log`，输出
`GATE_DIAGNOSTICS=RETAINED`及精确清理命令。串行fallback也写入同一阶段日志，不能只有控制台错误。
复核完成后沿[操作指南](../docs/OPERATIONS.md#软件验证与科学证据)清理，不按年龄自动删除失败证据。
改动选择器回归中的八个mini场景在同一PowerShell host内调用真实PlanOnly与InternalStage委托，
逐例检查RED/GREEN；MR和RF两个真实owner仍各自通过独立CLI核对非零退出传播。
相同十场景的PowerShell启动数由20降至5，不减少selector或测试执行，不新增生产缓存。
唯一入口输出`GATE_SUMMARY_PATH`：默认是系统临时目录中的独立小JSON，可用`-SummaryPath`指定
不存在的目标文件。摘要保留选中原因、实际命令、依赖、环境、阶段状态、耗时、退出码和日志保留情况，
成功清理详细日志后仍保留摘要。计划先落盘，阶段完成即更新；可捕获的失败或中断按实际状态收尾，
硬杀或断电后的`PENDING/RUNNING`只表示未完成，不能解释为通过。日志路径标为未保留时不可用。
CI使用[官方artifact action](https://github.com/actions/upload-artifact)在`always()`步骤上传摘要和本次保留的门禁诊断。
两个CI公开调用步骤用现有Python环境的单调时钟包围实际`pwsh`根命令，继承stdout／stderr以保持首错即时可见；
另上传`*_gate_command_timing.json`记录命令、环境、退出码、scope和完整命令墙钟，保留原summary文件及其计时口径。
安装、队列及此前独立scope规划不计入该公开命令墙钟。
摘要是观测记录，不是跳过后续验证或跨改动复用PASS的凭证。
文档检查保持独占；随后短检查先进入同一执行器，其余阶段按catalog顺序稳定排队。
只有`requires_stages`全部PASS的阶段才可启动，失败前置的后继即时标为`BLOCKED`；
前置缺失、未选择或无法取得ready阶段也明确阻塞，不挂起等待不存在的工作。
Changed／Owner首个失败后停止派发待队阶段，已启动阶段自然收尾；Repository在环境及目录初始化成功后继续独立检查，
包括文档检查失败之后的独立诊断，最后汇总失败。无日志与sidecar的既有串行fallback先取得实际结果，
才允许依赖它的阶段启动。资源许可、嵌套预算与进程数上限保持原公共入口。
`queue_seconds`从本执行组开始到派发，含组预热、依赖及并发槽等待；`resource_wait_seconds`单独测量
host许可等待，`execution_seconds`只测Action，`cleanup_seconds`测许可释放与环境恢复。
`launch_seconds`只测`Start-Process`调用，不能解释为全部子PowerShell初始化；`process_elapsed_seconds`
从该调用开始到父进程确认退出，包含轮询观察延迟。原`elapsed_seconds`仍是stage wrapper总计时，
整轮摘要从建立摘要到收尾计时，均不是整个根PowerShell进程墙钟；这些范围不能相加推算另一范围。
公开命令的端到端墙钟由调用者使用单调时钟，从启动公开命令前测至根进程实际退出，并另记命令、退出码、
环境和实际范围；例如现有Python调用环境的`time.perf_counter()`包围`subprocess.run(...)`。
原summary／stage计时保持原义，用于区分规划、准入、测试和收尾，不改名为端到端时间。
未实际观测的阶段字段为null，测试数量与skip不从退出码猜测。
Repository的MR静态测试与instrument assembly集成测试分别按原owner完整模块集合分为四组，随后每组独立申请
既有GATE资源预算；任一组失败仍使Repository失败。目录中的权重取自2026-10-29同机L2逐测试耗时，
未测模块使用保守调度估计，权重仅决定分组次序，不决定覆盖或通过。MR保留一次PS／Lua前置，
纯Ruff的integration前置任务已撤销；中央唯一Ruff承担实际选中范围，项目委派仅表示父级汇总职责，
不冒充项目lint已PASS。中央注册表PASS供MR前置复用，RF Freshness承担一次整树PS解析，变体各验科学合同。
分片结果不等于完整owner门禁；项目直接入口默认完成其全部必要检查。
集成分片权重来自同机完整L2 r3逐测试耗时按模块聚合；所有已发现模块恰好执行一次，权重仅用于调度。
Changed选择的命令与同一catalog中的完整owner命令语义相同时，复用上述分片及实际必要前置；
只改测试模块仍只运行所需模块，普通MR `Core`不会扩大为`Static`。覆盖去重按实际选中分片的模块并集判定，
任一必要preflight或分片失败仍使所选范围失败。权重样本中的单反射执行模块约688秒，不据分片接线推称L1已达目标。
2026-10-30同机宽L1为24/24阶段通过、摘要区间1337.500秒；热点为common contracts 1301.851秒及集成分片01 1113.187秒。
完整软件L2主体摘要区间1578.351秒，44/45阶段通过；唯一RF阶段修正后以正式quadrupole Static完整复验298.011秒通过，
原失败整轮摘要仍为FAIL。此前同机完整L2 r3为2064.248秒；本轮增加恢复用例，不能当作同冻结工作量的加速倍数。
宽L1的10分钟、软件L2首轮15分钟目标均未达到；普通单owner L1未独立计时，不宣称已达1–3分钟。
历史耗时测量见[门禁审计](../docs/history/20260802__gate-system-audit.md)；
Repository用于显式全仓软件验证，纯文档提交不默认运行Repository。
三个scope共用命令调用器直接绑定函数脚本块；仅冻结每项路由参数，不对调用器本身建立动态闭包，
避免其捕获旧的`LASTEXITCODE`而把失败报告为成功。公共回归实际执行成功及非零退出探针。
公共预算阶段执行期间将控制台输出编码设为UTF-8，退出时恢复原编码，嵌套阶段同样遵守；
避免隐藏Windows宿主的CP936经Python传给子PowerShell，导致中文错误日志解码失败并掩盖原始错误。

改动范围Ruff检查沿锁定版本的[官方参数文件](https://docs.astral.sh/ruff/configuration/#argfile-support)
传递原文件集合，保持逐文件范围及非零退出语义；阶段结束时清理临时参数文件。
这样避免大量绝对路径超过[Windows CreateProcessW的32,767字符上限](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw)，
不另建分批启动器，也不以缩短路径或修改UTF-8日志语义规避进程限制。

最新路径主题 `1eb7fedd` 的 [CI](https://github.com/Bibibabibobi96/mass_spectrometry/actions/runs/41066360221) 保留为 FAIL：
cooled 路径夹具在较短 CI TEMP 下未达到原生长度边界，却要求 alias；六个恢复负例在目标故障前触发生产磁盘余量。
修正仅加深测试路径，并让恢复夹具实际消费自己的 64 MiB／零 minimum-free 策略及代码副本；生产策略不变。
相对该提交的隔离副本中，两测试方法（含原六个恢复场景）通过，测试区间 79.280 秒；这不是整轮 CI 通过。

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

软件验证按实际阶段申请预算，已持有父token的嵌套组在父预算内串行，不能重复申请或增加嵌套并发。
COMSOL公共入口已支持准备、求解和后处理边界，具体调用见
[COMSOL主机资源阶段](comsol/README.md#主机资源阶段)。本次服务器完全退出后的`COMSOL/postprocess`
显式使用普通轻任务策略；`COMSOL/solver`列为重任务，准备和未分类阶段默认轻任务。入口调用
`Enter-HostExecutionLease -Role <角色> -Stage <阶段>`按中央名单解析；省略`Stage`时为`unclassified`轻任务。
`unknown_peak`只表示峰值未知，不授予重任务许可。自定义预算不能覆盖中央阶段分类。
此入口不再获取旧mutex；内层阶段继承
父申请不会自动缩减其全程预算。当前接入不表示所有项目或内部求解阶段都已经完成资源细分。

Python重阶段通过[`host_resource_python.py`](host_resource_python.py)现有request/result通道执行；
`run_heavy_function`的成功值仍使用原Path/tuple编码，失败仍向父调用者抛`RuntimeError`，同时保留worker的
异常类型、消息、notes及其明确提供的`observed_process_exit_confirmed`/`observed_process_returncode`。
缺失、损坏的结果或成功结果后的bridge非零退出均标为退出未确认，不能据此封存科学输出。
父进程通信异常不会主动杀死健康的PowerShell owner；它关闭请求输入、排空输出并等待同一进程句柄自然退出，
再抛原异常。二次中断或等待故障保留未确认状态及必要IPC目录；清理次错只附加说明，不覆盖主错。
`bridge_process_exit_confirmed`只证明直接bridge根进程；worker携带的观测状态也只覆盖它原来声明的进程，
均不替代既有主机owner对后代退出的判据，不构成求解成功或物理资格。尚未确认停止的写入者不得进入retention或终态封存。
`Exit-HostResourceStage -PassThru`原样返回本次释放事务；默认控制台输出与环境恢复不变，继承调用不返回
释放结果。bridge在同一个call结果中附加`host_release`，保留`inherited`、token、原事务`result`及释放
`error`；只有非继承、无释放错误且同token的`released`响应才确认owner释放，仍保留的预约不能报告成功。
`run_heavy_function(..., completion_receipt=空字典)`将本次bridge根退出和host释放事实写入调用者提供的
独立容器，正常返回值类型不变；失败异常也带`host_release`与`host_release_confirmed`，释放次错不替换worker主错。
继承的直接调用只报告继承身份，没有owner释放证明；每次调用须使用新的空容器，避免复用旧证明。
host释放不能覆盖worker明确报告的原生退出未知，也不替代局部PA guard所需的实际写入进程退出证据。
CLI reentry在原前台输出流报告释放结果，释放未确认时非零退出，不另建结果文件。

受控Python helper使用`common.host_resource_python.await_managed_process_start()`作为首个操作，随后才能
导入项目或启动native工作。公共`Invoke-RepositoryManagedPythonProcess`以同一stdio完成nonce、实际worker
PID与创建身份的READY／ACK握手；Python调用方使用`run_managed_python_process`沿既有内部bridge访问它。
两入口均不申请、继承核验或释放资源许可，不设置heavy reentry；科学入口仍负责既有准入。
父端确认worker属于本次launcher后持有其实际进程句柄，等待worker退出并将两条输出流按原始字节排空到日志。
因此`.venv`启动器退出、或worker先写completion后继续写stderr，都不能使日志提前封存。
返回的`repository_managed_python_completion`分别报告ownership、worker／launcher退出与两流drain；Python异常的
`managed_python_completion`或PowerShell异常Data中的同名值保留失败时已确认的事实。
`ack_attempted`在发送ACK之前置true；发送错误可能发生在worker已收到ACK之后，不能解释为工作从未启动。
此收据只证明实际worker与launcher退出及日志排空，不声明任意后代退出。初始归属未确认或错误ACK不得
启动受控工作。项目另核对实际native根的原生终态；native未知不得发布或执行retention，保留run及容量保护，
不能声称PowerShell退出后其FileShare句柄仍保持。
当前受控SIMION脚本使用同进程的`simion.command()`／PA API，没有主动外部fork；
依据[官方CLI说明](https://simion.com/info/command_line_interface.html)，由直接Popen根writer的完成事实判定本地PA写入结束。
该合同不覆盖任意程序派生独立写入者，适用的host释放判据仍由原调度器负责。
创建时间沿用现host接口的.NET UTC ticks（D19），通过Windows
[`GetCurrentProcess`](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getcurrentprocess)和
[`GetProcessTimes`](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes)
读取，并按[`FromFileTimeUtc`](https://learn.microsoft.com/en-us/dotnet/api/system.datetime.fromfiletimeutc)相同epoch转换，
不经浮点Unix时间舍入。官方API核验于2026-10-28；这是基于官方API的受控worker归属协议，不是任意进程树捕获保证。

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

合法运行参数探索与源码／合同语义改动的验证边界见[操作指南](../docs/OPERATIONS.md#软件验证与科学证据)：
同一实现内的合法参数探索不默认执行软件测试；项目入口继续承担必要输入、支持域、资源与输出检查。

### 进程观测与预算

并行执行器每轮有活动worker时，由`Get-RepositoryProcessSnapshot`统一枚举一次`Get-Process`和
`Win32_Process`；CIM失败时同轮只抓一次原生父PID表。`Get-ManagedSolverProcessSample -ProcessSnapshot`
复用该轮枚举，各family仍分别复核创建身份、投影可能归属的父链并读取工作集、private、两者最大值及CPU。
快照不跨轮保存，标量读取也不构成全机同一时刻的原子测量。独立调用省略快照时仍按进程枚举、创建身份
复核、父关系枚举的原顺序执行；无关进程的未知身份不会扩大为其他family的失败。
受管Python的READY/ACK使用`Test-ManagedProcessLaunchAncestry`证明选定worker到原launcher的父链：
每步创建身份必须已知，父进程不能晚于子进程，首尾身份精确匹配且链不能成环。
Windows父PID可能已复用，其他旧分支的未知身份不否定这条已证明的链；
完整family的`ancestry_complete`和未知列表仍原样保留，不因此推断其他writer已停止或授权清理。
父PID复用与创建时刻判别的官方说明见[Microsoft说明](https://devblogs.microsoft.com/oldnewthing/20150403-00/?p=44313)。
2026-10-29在i9-9900K／16逻辑处理器、PowerShell 7.6.9上，最终冻结双臂重测保全完整源码与18个
交替样本。BASE为80,292 B混合工作树快照，不是Git 3005980；NEW为82,265 B的当前实现。
1、4、8个worker各三对采样的中位数分别为397.6261→456.7082 ms（+14.86%）、
2787.6528→1023.5216 ms（−63.28%）及4766.7381→2379.6709 ms（−50.08%）。全机进程与CIM枚举
均从每轮N次降至一次，六类完整返回字典相同；单worker没有改善，健康进程和危险处理策略不变。
本次采样合计37.6740721 s，外层127.286349 s包含准入等未细分开销，且同时有L2背景负载，不能据此
宣称求解或整个调度器提速。旧轮57.0983365 s调度观测中的长退出间隔未完整分段，也不计入采样收益。

单进程观察器`Invoke-ResourceBudgetedProcess`接收调用者在冻结边界解析的`-Limits`对象，
观察收据记录完整limits；没有项目工程预算的入口可显式传`-Limits $null`，仍跟踪进程身份、退出及公共物理危险，
不生成usage或虚构预算。`Complete-ResourceUsage`只读取已有usage收据收尾，不重新解析预算。
启动后的身份或采样异常先沿同一实际Process句柄等待根进程自然退出，再抛回原ErrorRecord；
异常Data中的`observed_process_exit_confirmed`／`observed_process_returncode`仅证明该直接根进程；
`observed_process_id`／`observed_process_started_at_utc_ticks`保留同一handle实际取得的身份，未取得启动时刻则为null。
等待自身失败时明确为未确认，并把次错保留在`observed_process_wait_error`；调用者不能据此释放
仍可能被使用的输入保护或执行载荷清理。这不替代host owner释放，也不证明任意后代进程已经停止。
Python向PowerShell传递派生预算可使用任务临时JSON，解析后由调用者finally清理；冻结的工程预算仍是输入权威。

墙钟、目录体积、进程树工作集或可用内存预算越限，每类只写一次`RESOURCE_BUDGET_WARNING`，
不据此停止健康进程。低CPU、暂时无输出或采样空洞也不是停止依据。原生进程明确失败时停止启动同批新工作，
已经运行的健康同级自然结束。只有持续低于中央策略的物理内存危险保留量才进入受管停止，并记录危险原因。

`New-RepositoryProcessObservation`和`Update-RepositoryProcessObservation`供包装器和COMSOL入口复用观测；
它们不启动进程、调度、重试或发布科学终态。物理危险阈值只来自[主机策略](host_resource_policy.json)，
无Limits时不写usage；目录或usage写入失败只告警，不能遮蔽已经确认的物理危险。
