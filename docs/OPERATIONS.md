# 工具链与仓库操作

返回[仓库入口](../README.md)。从仓库根`simulation_repo/`执行本页命令；项目输入和资格见项目README与PROJECT。命令中的尖括号是必须替换的占位符。

## 通用验证口径

独立粒子轨迹项目的正式证据统一使用三档粒子数：N=100是功能检查、日常回归和Candidate功能证据的最低标准档；
N=1000是峰形、尾部、束斑/发散分布、损失分布与标准分辨率统计档；N=5000是高统计档。机器权威为
[`common/contracts/particle_count_policy.json`](../common/contracts/particle_count_policy.json)，实现必须在昂贵
求解前调用其校验器。探索运行可使用任意正整数粒子数，并必须在输入与结果中记录实际数目；较小标准样本必须是同一种子较大母样本的前缀，不能分别抽样。低于100的粒子数不得成为新项目或新模式的功能、Candidate或Formal基线；专项收敛或集体效应研究可以通过版本化项目合同
增加具名粒子数，但不能改写这些档位的含义。历史小N运行只保留为历史证据，不构成当前入口。

质量分辨率统一为 `R=m/FWHM_m`；窄峰时间域等价式是 `R=T/(2*FWHM_t)`。`2.3548×sigma`
只有在峰形近似高斯时才可作为 FWHM 代理。比较 COMSOL 与 SIMION 时至少统一几何、粒子表、
有效检测面、命中定义、FWHM 算法和样本量，并分别检查网格收敛与统计不确定度。详细方法写入
`docs/VALIDATION_METHODS.md`，项目数值写入项目 PROJECT。

## 工具链与执行入口

PowerShell Core 7（`pwsh`）是仓库唯一受支持的PowerShell运行时。公开根入口必须通过公共preflight
失败关闭地验证当前宿主为Core 7，禁止回退到Windows PowerShell 5.1。Python等非PowerShell边界启动
PowerShell时必须使用`pwsh`；PowerShell脚本内部继承当前宿主，不得另行选择或启动第二套PowerShell。

### 分层门禁

所有门禁使用Python 3.11；本机默认使用`.venv`，GitHub Workflow注入干净运行器的Python路径。门禁不执行
商业求解器、CAD或正式资产门禁。项目发现、设计请求校验和求解器中立规划入口见
[`common/contracts/README.md`](../common/contracts/README.md)。

| 层级 | 入口 | 使用条件 |
|---|---|---|
| L1 改动范围 | `common/verify_changed.ps1` | 每次提交、push及日常参数探索 |
| L2 仓库集成 | `common/verify_repository_integration.ps1` | 门禁、注册表、机器语义、共享运行或跨项目接口改变 |
| L3 项目证据 | 项目 `verify_project.ps1` 的 Candidate/Formal 级别 | 资格、promotion或真实物理资产变化 |

L1 始终先查仓库卫生与受管文本字节。纯 Markdown 改动运行文档检查后走
`DOCUMENTATION_ONLY` 快速路径；其余只运行活动项目、直接公共依赖和必要静态合同，报告 RUN/SKIP 原因。
四极杆或其直接公共依赖变化时先查生成物 Freshness，再复用前置结果执行无求解器 Core 合同。

L2 在长测试前检查四极杆 Freshness，然后覆盖全部活动项目、integration 和公共静态回归；四极杆
Static 复用该前置检查。纯文档和规则文字调整不触发 L2，GitHub 仅手动触发。
L3 才核验商业求解、GUI/CAD、冻结输入、manifest 和物理证据链。


`common/gate_catalog.json`是L1路径路由、依赖等级、阶段前置关系和L2成员身份的唯一机器目录；项目或
integration新增公开门禁时必须注册，目录与文件系统不一致即失败。仓库只保留
`common/verify_changed.ps1`这一个L1入口，不提供旧名称兼容脚本。`.github/workflows/lightweight-gate.yml`
在push只运行L1；L2仅可由`workflow_dispatch`人工启动，不对pull request自动运行全仓回归。

L1的`-PlanOnly`使用同一目录先给出`stdlib`或`locked`依赖等级；GitHub对只需标准库的文档和门禁
合同范围跳过完整科学Python环境安装，任何未明确分类、项目注册表、Python lint、项目/集成、依赖声明或
FullScope均失败关闭为`locked`。本地并发默认为`min(8, logical_processors)`，可用
`-MaxConcurrency 1..32`显式覆盖；GitHub托管runner固定为2。这是门禁组内的并发上限，实际阶段还须通过
下述机器级资源准入；提高该值不会绕过预算。并行阶段即时报告进程启动与完成，随后按
稳定顺序回放完整日志。历史耗时测量见[门禁审计](history/20260802__gate-system-audit.md)；
L2用于显式全仓审计，纯文档提交不默认运行L2。

### 主机资源调度

本机门禁与SIMION/COMSOL运行通过[`host_execution_lease.ps1`](../common/host_execution_lease.ps1)
进入同一[`主机调度器`](../common/host_resource_scheduler.py)。默认账本为
`%ProgramData%/MassSpectrometry/host_resources.sqlite3`；不同工作树必须使用同一个机器级账本，不能
各建一份而重复分配资源。`MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH`只用于显式受控部署或隔离测试，
生产调用不得用它绕过正在运行的申请。资源配置、已分类阶段及测量依据只维护在
[`host_resource_policy.json`](../common/host_resource_policy.json)，不在项目脚本复制容量阈值。

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
[COMSOL主机资源阶段](../common/comsol/README.md#主机资源阶段)。本次服务器完全退出后的`COMSOL/postprocess`
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
调度器不杀进程；排查无用占用须结合命令、归属、日志和实际进展，不能仅凭低CPU利用率终止
可能正在I/O、等待许可证或保存结果的工作。观测失败不清空既有预约。
并发事务使采样过期时，入口退避后重新采样并报告等待；正常竞争不算工作失败，陈旧观测不能用于准入。
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

### 文档结构检查

仅审查文档结构时运行 `common/verify_documentation.ps1 -StructureOnly`：检查活动本地链接、中文与页内锚点、格式和历史归档完整性，不取得主机执行租约、不运行外部工作区卫生。默认模式与 L1 仍执行完整卫生检查并遵守租约。

`.\.venv\Scripts\python.exe -m common.documentation_links --inventory-json`输出逐文件行数、字符数与诊断。
字符数基于UTF-8解码、换行规范化后的文本，不是token数。既有只读历史的失效链接只诊断，新历史断链仍阻断。
长文、重复段落、无入链、表格列数不齐和空单元格是人工审查提示；合法空值不能仅凭检查器判断为遗漏。
相对artifact路径允许外部载荷不在当前机器上，远程文献和科学结论需另行核验。
结构PASS不证明新旧指令一致或阅读范围完整；文档升级还按[任务检索验收](REPOSITORY_ARCHITECTURE.md#按任务读取与局部检索)
核对当前答案、必需约束和失效路径。

### artifact结构门禁

清理时先运行卫生门禁检查源码与工作区顶层，再按[生命周期](LIFECYCLE.md#保留与清理策略)盘点产物、
活动引用和相关系统临时目录。`reconcile_artifact_capacity.py --artifact-root ..\artifacts`只执行
ledger-only日常startup/maintenance；历史全盘扫描必须显式调用`legacy_capacity_backfill.py`。
未核对候选不得追加`--apply`。清理收据统一放在
`artifacts/common/capacity_disposal_receipts/`，不留在工作区顶层。主机资源许可不替代容量保护租约，
调用与保护参数见[公共容量合同](../common/contracts/README.md#运行身份与生命周期)。

本机存在artifacts时运行：

```powershell
.\.venv\Scripts\python.exe -m common.contracts.verify_artifact_layout ..\artifacts\projects
```

它检查目录合同、`run_id/archive_id`、三件套和manifest身份；项目 artifact 默认不读取大二进制，
但已注册的公共 SIMION PA-family cache 会对其当前 generation 的完整 payload 做字节级验证。因此它适合
每次产物整理后运行，但不放进不具备本机artifacts的GitHub Workflow。命名合同单元测试仍属于轻量门禁。

公共 PA-family generation 是发布介质，不是求解器工作目录。SIMION 不得直接接收 generation 路径、
Junction、硬链接或原生 `.paN` 的物化副本；运行时只消费按 manifest `bytes + SHA-256` 建立的独立
standalone 私有副本。公共 `New-ShortPaCopy` 对父目录含 `cache_manifest.json` 的来源强制要求这两项身份，
缺少任一项即失败。Windows 大 PA 若普通缓冲读取与 `/J` 持久读取分叉，不得对发布源 ReadWrite/Flush；
应先用 manifest-bound `/J` 快照验证，并把旧文件对象隔离后以同字节的新对象原子替换，禁止原位修补。

### COMSOL R2025b 执行入口

本机 MATLAB R2025b 与 COMSOL 6.4 的长期入口是：

```powershell
.\common\comsol\run_comsol_r2025b.ps1 -TaskScript <任务脚本.m> -ReportPath <报告.txt>
```

入口通过 `common/comsol/livelink_r2025b/comsolstartup.m` 连接官方 LiveLink/Java API。首次使用
新的直连脚本先做最小测试。临时连接工具不能替代正式项目脚本和项目专属后处理判据。
连接生命周期只由该入口管理：任务脚本不得再次调用`mphstart`。一次相关任务在同一连接内完成
加载、Compute、保存和轻量节点检查；容易触发大内存传输的粒子结果读取可放入第二个干净任务。
入口对未创建任务报告的启动失败做有限干净重试；若报告已创建，只对白名单中的首次模型打开
`mphload/mphopen + Not connected to a server`连接瞬态重试，并先归档失败报告。进入配置、Study
Compute或求解器后的错误不自动重算。

### 正式工具链基线

自2026-07-15起，所有项目的新建、修改、验证和交付均只使用**MATLAB R2025b**与
**SolidWorks 2022**。MATLAB/COMSOL任务必须通过上述R2025b入口运行；凡涉及STEP导入、
零件、装配或CAD保存的任务必须使用`common/solidworks/`中的SolidWorks 2022桥接。不得启动、
调用或为兼容而降级到MATLAB R2022或SolidWorks 2013。历史文档中出现的旧版本仅用于解释当时
结果，不构成可用入口或复现环境。

每次涉及MATLAB或SolidWorks的正式变更前，运行：

```powershell
.\common\verify_toolchain.ps1
```

该门禁验证R2025b可执行文件和SolidWorks 2022 PIA/COM revision；项目默认继承本节，不在每个
README重复声明。它不重写或重存已有的MPH、SLDPRT或SLDASM。若Live COM探测失败，门禁可用
`FILE_VERSION_FALLBACK`确认安装版本与PIA基线，但这不证明CAD可编辑或可保存；任何实际CAD
变更仍必须通过项目SolidWorks导出与装配门禁。

自2026-07-16起，求解器无关分析固定使用**64位Python 3.11**。MATLAB R2025b官方支持
Python 3.9至3.12；本机默认Python 3.14和旧Python 3.8均不得作为本仓库正式运行时。依赖由根目录
`pyproject.toml`声明、`requirements-lock.txt`冻结，并安装在不入Git的`.venv/`。跨目录Python入口从
仓库根使用`python -m <module>`运行，禁止由各脚本重复修改`sys.path`。单次反射oa-TOF入口见
`projects/single_reflection_oa_tof_mass_analyzer/analysis/README.md`。

## Git 规则

仓库根是 `simulation_repo/`，远程公开仓库为
`https://github.com/Bibibabibobi96/mass_spectrometry.git`。提交只包含一个可审阅主题；使用明确
路径或 `git add -p`，不习惯性执行 `git add .`。提交前运行：

```powershell
git status --short --branch
git diff --check
git diff --stat
.\common\verify_changed.ps1
```

确认没有 MPH、PA/IOB、结果、日志或一次性脚本进入暂存区。不得强制推送、改写远程历史或
覆盖/夹带任务开始前的无关改动；Agent何时自主提交和推送只由[`AGENTS.md`](../AGENTS.md)定义。

每个提交都使用简洁、可检索的标题，并提供与改动复杂度和风险相称的正文；不再允许只有标题的提交。
正文至少说明修改目的、关键结果或行为变化、实际验证，以及必要的限制或未完成事项，使未来维护者
无需查阅聊天记录即可理解提交。正文不逐文件复述diff，也不以无信息量模板凑长度；不设机械字数下限。

## 任务完成定义

一次变更只有在源码、机器契约、最近的权威文档、路径引用和相称测试一致后才算完成。验证证据必须
足以还原目标、输入、唯一变量、结果、判据和产物，但不保存无关常规日志；正式几何还必须满足
COMSOL [GUI和SolidWorks同步门禁](REPOSITORY_ARCHITECTURE.md#gui-与-cad-门禁)。Agent面向用户的报告顺序与篇幅只由[`AGENTS.md`](../AGENTS.md)定义。

文档变更还应运行`common/verify_documentation.ps1`，检查唯一H1、标题层级、相对链接、历史归档
标记和项目入口完整性。自动门禁只验证可机器判断的结构；技术结论是否放在正确权威层仍需审阅。
