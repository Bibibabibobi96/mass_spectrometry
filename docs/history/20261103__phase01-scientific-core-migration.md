# Phase 01 科学核心迁移与软件门禁必要审计

DOC_STATUS: ARCHIVED_READ_ONLY

证据快照：2026-11-03。本记录说明 V4 P1 科学核心迁移的软件验收与交付范围；R01–R20整体责任仍按路线图推进，不授予新的原生求解、GUI／CAD或科学资格。
本记录绑定下列源码、发行与运行身份；只归档必要迁移事实、失败及验收边界。0cecf及380的远端失败保留；最终473680ec的Changed、本机完整和远端完整均已实际通过并独立复核。
规范导航按目标位置 `docs/history/20261103__phase01-scientific-core-migration.md` 解析：
[公共API与兼容桥](../../common/README.md)、[迁移责任路线图](../ROADMAP.md#科学核心与平台边界迁移)、
[架构](../REPOSITORY_ARCHITECTURE.md)、[开发标准](../DEVELOPMENT_STANDARDS.md)、
[操作与完成判据](../OPERATIONS.md)、[生命周期](../LIFECYCLE.md#history-冻结条件)。
正文所列外层证据文件名是本机证据身份说明，不是仓库相对链接；不随本文复制为虚构的仓库载荷。

## 版本、完整结果与当前交付边界

| 对象 | 已确认状态 | 适用范围 |
|---|---|---|
| 起点 | `18afd1fe5368bf1c1542b7d75db977051ed44af9` | 原始软件基线；当时完整门禁失败，不作成功速度基准 |
| 科学迁移与资源发布修复 | `5ff18cec0faf86567e7fb1e7ee6a41ccbab8af18` | 已取得该精确提交的完整远端软件 PASS |
| 5ff 完整 CI | [41449589106](https://github.com/Bibibabibobi96/mass_spectrometry/actions/runs/41449589106)，SUCCESS；49 PASS／12 NOT_APPLICABLE | summary 内部3885.060430秒；公开命令外层3886.785380秒 |
| 5ff 覆盖观察 | 6326唯一测试ID，较基线6291为+35／−0 | 含条件skip可能，不能写6326个测试全部实际执行通过 |
| a8 本机完整验收 | 普通wheel、完整24锁依赖、显式8路；49 PASS／12 NA、exit0 | 内部2068.372626秒／外层2070.549008秒；6336唯一ID较基线+45／−0，raw汇总21项skip；只覆盖a8及35项原差异 |
| 676 本机完整验收 | 普通v5 wheel、完整24锁依赖、显式8路；49 PASS／12 NA、exit0 | 内部1930.587224秒／外层1932.2784481秒；6337唯一ID、21项skip，退出后2552文件身份全同；不含后继fixture修复 |
| 0cecf 本机完整验收 | 普通v5 wheel、24锁依赖、显式8路；49 PASS／12 NA、exit0 | 内部1921.546543秒／外层1923.2358443秒；6339唯一ID较基线+48／−0，21项skip；退出后2552文件无变化／增删，含受保护35原差异 |
| 380 已终态 | 本机8路完整PASS：49 PASS／12 NA、6339唯一ID、21skip、外墙1809.3350065秒 | 远端Changed与完整各有独立FAIL，不能作为最终完成版本 |
| 最终代码 | `473680ec388dd7d52d4c2dea4bc90aa6622a54dc`，两项夹具修复已提交推送 | 科学核心57payload与v5相同，代码及包交付身份分别记录 |
| 473 本机完整 | 49 PASS／12 NA、exit0，显式8路；6339唯一ID、21项skip | 内部1799.126825秒／外层1800.7282891秒；前后2553文件无变化／增删，含保护的35原差异 |
| 473 远端完整 | [41517777976](https://github.com/Bibibabibobi96/mass_spectrometry/actions/runs/41517777976)，SUCCESS，49 PASS／12 NA，4路 | 内部3601.484388秒／外层3603.1305534秒；6342计时记录／6339唯一ID，226skip，与本机ID集合相同 |
| 473 Changed | [41517678968](https://github.com/Bibibabibobi96/mass_spectrometry/actions/runs/41517678968)，SUCCESS，6 PASS／33 NA | 两模块40唯一ID，零报告skip；内部145.727235秒／外层146.9184655秒，范围不等同完整Repository |

最终两端完整证据分别由 `repository-473680ec-local8-acceptance-review.md/.json` 与 `ci-473680ec-acceptance-review.md/.json` 实读核查；5ff的早期复核另存 `full-ci-acceptance-review.md`。成功子日志清理不等于零skip，各轮只绑定自己的源码与结果。

## 实际迁移、消费者与科学边界

规范实现实迁至`src/msplatform`：源策略／状态／物化、完整与局部布局、峰形数学、刚体变换、
粒子物理及普通文件摘要。最终普通发行保留在v5，57payload与c0cb9dc8及sdist重建wheel逐字节相同，直接依赖／文件SHA／命令在distribution-manifest.json和SHA256SUMS.txt。676以后的failure-drain及多轮fixture修复只改测试；最终473680ec的57payload与原v5未变，`final-473680ec-environment-proof.json`在实际HEAD重核普通安装来源、57payload与24锁依赖，环境未重装。核心不反向包装`common`、项目或运行owner；发行是单一
`mass-spectrometry-analysis 0.2.0`，适用Python3.11，38个schema仅保留一份规范资源。
科学格式、schema ID／引用、原方法身份及资格语义保持；此次不是仅给旧实现增加可安装外壳。

### 发行载荷身份

以下均在本机任务交付目录`v5/`保留；可由固定源码及锁文件重建。原wheel与sdist重建wheel的ZIP摘要不同，已比较的57项实际包载荷相同，不称归档文件逐字节一致。

| 文件 | bytes | SHA-256 |
|---|---:|---|
| `mass_spectrometry_analysis-0.2.0-py3-none-any.whl` | 101420 | `4dd2ce81c68e8ab11a3397fe8b4ee1165186d779e3b07fab827281b8003d762e` |
| `mass-spectrometry-analysis-0.2.0.tar.gz` | 72896 | `2bf6f4ca992b1d39804cc2d2cf4e7e7cd2c15d5179961e42218c881cd08eebf6` |
| `rebuilt/mass_spectrometry_analysis-0.2.0-py3-none-any.whl` | 101420 | `9caefa12b5a065a5fde645cd898d9fcbb707bd19cd3968687f601a341423ce79` |

| 真实消费边界 | 已有行为证据 | 不由此证明 |
|---|---|---|
| RF `core/ideal_transport.source_particles` | 直接规范API；固定完整源输出、历史序列、单位和ID回归 | 新RF原生飞行或传输性能 |
| OA `analysis/component_focus_simion_source.materialize` | 完整粒子位置／速度／时间投影、输出hash、receipt／campaign绑定 | 新三维场或完整OA科学资格 |
| `common/integration/resolve_connection`文件适配器 | 直接规范布局；完整父／局部、坐标／法向／1mm间隙与父不变 | 任意拓扑、相交或场消费均已验收 |
| MR `analysis/simion_event_analysis` | 直接真实KDE、单位／均值／时间等效结果与非法输入拒绝 | 质量标定、整机分辨率或Formal资格 |

安装probe实际使用同一RF提供者的两个实例。另有集成几何回归同时消费真实RF
`build_assembly_interface`和OA`resolve_assembly_interface`并接规范布局，经兼容别名进入；
它是有限真实提供者证据，与上述四条直接新API消费者区分，不能冒充新装配求场／飞行资格。

wheel及sdist重建后的wheel在干净venv、工作树外`-I`实际执行，记录`site-packages`来源；
后端／PowerShell可执行PATH被隐藏时核心源、布局与分析仍可计算。发行不包含运行器、测试、
商业二进制或求解载荷；没有发布PyPI，仓库未声明开源LICENSE，不能冒称新增许可授权。
38个schema及310个本地引用有安装实调证据，不靠网络fallback。

T5、300mm及C3-J3 publisher曾误把安装资源要求为工作区源码。现沿既有`freeze_file`和私有staging
把实际安装schema按原字节冻结到`inputs/schemas/`，原输入key绑定本地相对路径、bytes及SHA。
项目源码的工作区归属检查保留；五点family、父输入不变、失败原子清理及非Formal边界另有实测。

新快照显式冻结规范源码与资源，以自身`src`／flat根运行并核对实际origins；缺核心／schema时拒绝
宿主安装或当前checkout补洞。旧flat快照继续消费自己的实现，不改写历史run／receipt／manifest。
有限单向桥与具名生产／跨语言消费者、P4退出条件只查[公共机制说明](../../common/README.md)；尚未完成整体桥退休，
也没有证明任意历史快照或全部外部消费者可恢复。仓库`REPO_ROOT`上下文与纯科学实现区分。

11个科学模块及源导出入口规范化AST、普通SHA函数体、38个schema原字节与真实投影／原生文本回归，
支持有限科学不变结论。源RNG／prefix、物种、ID、出生时间、单位、数值原生输入、驱动／电极／网格及
恢复状态机未借迁移改变。独立参考为三角峰FWHM=1、均值10μs、样本sigma约65.57438524301996ns，
保留ddof=1、正等权限制及metadata。数学／软件PASS不授予新Fly、COMSOL、收敛、统计、GUI／CAD或Formal资格。

R01–R20各自首次／整体关闭阶段、责任和出口**唯一引用**[ROADMAP责任表](../ROADMAP.md#科学核心与平台边界迁移)；本文不复制、重分配或以“不支持”删除那些要求。

## A01–A30逐项验收证据

“证据具备”均限所列P1边界，不能由单项相加替代最新精确版本的完整验收。
外层证据文件 `independent-final-acceptance-review.md` 的独立原审时间切片
由本稿已取得的完整CI终态更新；它不是独立重跑所有发行、全仓或商业链的证明。

| 项 | 当前证据与关闭限制 |
|---|---|
| A01 | 起点失败、原35差异、12个混合文件审阅及整合／字节证据保留。最早部分作者归属无法独立重建，不能据临时目录标签宣称clean Git或作者归属；有记录的原差异保留不夹带。 |
| A02 | ROADMAP逐R列首次阶段、整体关闭阶段、责任和出口；仅引用该唯一责任表。 |
| A03 | 架构／开发／操作／生命周期、公共入口、catalog及持续边界随实迁同步；当前API导航、路线图状态、审计索引与本冻结记录保持各自权威。 |
| A04 | 规范包持有实际实现，不倒挂`common/projects/owner`；普通摘要与平台保护职责分离。 |
| A05 | src隔离、单发行、算法与I/O边界有架构依据；不是namespace转发包装。 |
| A06 | 公共enumerate处理显式资源、父初始化和排除；38schema／310本地ref及持续正反边界、缺资源拒绝已实测。 |
| A07 | 0.2导入迁移明确，科学格式／方法／schema ID保持；桥单向无失败回退，具名P4退出，不声称所有外部用户已迁移。 |
| A08 | wheel／sdist重建与生产清单实核；仅规范能力与小资源，无运行器／测试／商业载荷，不新增许可证主张。 |
| A09 | 干净venv、树外`-I`实调及普通安装origins具备；三publisher另修正editable掩盖的资源归属缺口。 |
| A10 | 隐藏供应商／PS执行PATH仍运行核心计算；只证明核心独立，不证明backend能力。 |
| A11 | 源黄金序列、prefix、物种／出生时间／ID及RF／OA完整实输出保持。 |
| A12 | CSV列／单位／顺序与receipt输出hash／身份绑定保持；不同输出路径的receipt不要求同hash。 |
| A13 | 完整父、局部、选全部仍local、切边、不读失效祖先路径与文件适配器行为具备。 |
| A14 | 已审合同域中未知策略、非有限、frame／法向／实例／范围错误拒绝；不是所有合法研究请求均已支持的承诺。 |
| A15 | RF两实例安装probe与另一个真实RF＋OA几何回归分开计证；经兼容别名的集成调用不冒充四直接消费者。 |
| A16 | 独立FWHM／均值／sigma、ddof=1、等权拒绝、单位与metadata通过，数学结果不升级科学资格。 |
| A17 | RF、OA、布局文件适配与MR四实际入口直接调用规范API；有实输出及禁止旧桥导入控制。 |
| A18 | 原迁移的规范化AST、普通SHA函数体、38schema及原生投影保持。随后cylinder清理明确例外：仅删未用形参与唯一local实参两个节点，其余全AST精确相等；不得继续宣称当前12模块raw AST全等。新PS处理来源运输，publisher仅冻结schema身份，不改候选科学值。 |
| A19 | 本轮未改网格／电极／驱动／科学数值；无新增商业、GUI／CAD资格。此为有限“不触发新原生”判断，不是通用豁免。 |
| A20 | 已审快照的src／资源／roots／origins及缺失拒绝具备；MR study、RF独立runner、SFI重分析漏项已修，不推断未知旧run全部可恢复。 |
| A21 | 已触及的Unicode／长路径／空格／cwd／argv／alias回归保留；cp1252双向路径及manifest CLI UTF8修复有真实远端反例。 |
| A22 | 科学run发布状态机未改。主机准入有限等待／失败清理已改，保留专属deadline、transition、释放、未知身份／活后代、父token与原错误保持回归；不以运行状态机未改豁免新租约路径。writer／恢复幂等及真实interface CLI终态证据另保留。 |
| A23 | 最终473680ec的Changed、本机8路完整及远端4路完整均真实通过并独立复核；两端6339唯一ID集合相同、较原6291基线+48／−0。允许的skip及历史失败照实保留，不拼接旧版PASS代替最终版本。 |
| A24 | 所有失败、原预算、覆盖、内外wall与官方CLOC保留；本机30.012分钟、远端公共门禁60.052分钟，原15分钟目标未达，继续归R17／P4。Owner366.040秒也仍超过5分钟；六项2／4／8窄诊断与旧新Owner比较不冒充稳定性能达标。 |
| A25 | API／单位／安装／限制与兼容桥导航由最近说明维护；common README、ROADMAP、AUDITS及本记录同步，受影响文档执行提交前路径／链接／字节检查。完整时间线只归本记录。 |
| A26 | imports、CSV、父offset、publisher五点及原子失败等行为保证保留；最终对基线6291观察ID新增48／移除0。两端完整skip分别21／226，非verbose日志不能逐方法归因；40项新修复的窄Changed无报告skip。 |
| A27 | 有限六桥及生产／跨语言消费者与P4退出清单具备；仓库上下文单独保留，整体推广和实际删桥未完成。 |
| A28 | 多Agent实际完成需求、核心边界、科学保持及夹具独立复核；最终两端summary／raw／源身份由非主执行路径核查。不声称每位审阅者独立重跑全部CI或商业链；cooled作者与Agent1代码审阅职责分开。 |
| A29 | 工具／安全与完整24锁依赖记录具备，未购软件／发布PyPI／新增许可；环境重试成本保留，未测模型账单，不把token折成费用。 |
| A30 | P1核心、四真实消费者、可安装发行、冻结与旧实现退出证据按本阶段交付；R01–R20整体及P2–P5、桥退休和性能目标仍有路线图责任，不把P1软件完成当平台或原生资格完成。 |

## 完整CI覆盖、条件skip与失败保留

5ff完整轮的6326唯一ID比基线新增35、移除0；ID包含失败／skip可能，不等于实际执行PASS总数。
本机standard8曾观察6329、+38／−0，其中多出3个是临时a／b／c模块的`Probe.test_value`，
不是新增正式回归，见`final-coverage-fixture-id-reconciliation.json`；原始观察不删除。

完整轮226个skip来自workflow全文16段汇总，成功子日志清理后没有逐方法原因清单：

| stage | skip | stage | skip |
|---|---:|---|---:|
| common/contracts 02／03 | 1／2 | workspace_paths | 1 |
| integration 01／02 | 23／8 | integration 03／04 | 4／15 |
| MR 01／02 | 28／33 | MR 03／04 | 21／28 |
| SFI 03／04 | 6／2 | SIMION公共 | 26 |
| RF domain | 3 | IP | 25 |
| **总量** | **226** | | |

源码条件包括Lua／官方SIMION CLI、Windows／pwsh、历史PA／源／manifest与可选receipt；这解释类别，
不能把226逐一归为某原因，也不能用本机旧21个可用日志skip列表解释云端全部skip。
核心安装有实际wheel／venv／数值／来源输出；持续边界、UTF8、四消费者中的关键无skip目标，
有完整模块选择、阶段成功及源码守卫依据。不能据同片skip数量猜那些无skip目标也跳过，
也不能给所有guarded方法逐一盖章。详见完整独立审，而非将全部durationID当执行。

5ff Changed 41449588921另为14 PASS／33 NA，外层1682.278365秒；其六集成／SFI片共1145项、58skip。
该Changed没有选择全部核心安装、RF／OA／MR和路径边界，不代替完整轮；它的58skip不与226互换。

| 重大轮次／问题 | 原结果或成本 | 已处理边界与仍有限制 |
|---|---|---|
| 起点Repository | FAIL，1992.039886秒、6291唯一ID | 原RF标准差异与早期安装断言／版本切片问题保留；不是有效成功速度基线 |
| 早期本地完整与冻结漏项 | 各`repository-v4-*-summary.json`保留FAIL | src／桥／资源、PS bootstrap和旧schema定位按真实负例修复，不以focused覆盖原终态 |
| 第六轮完整 | FAIL，2433.259496秒；46 PASS／2 FAIL／12 NA | SFI两90秒子工况与RF120秒超时；原临时stderr未保留，根因未知 |
| 原预算独立重放 | SFI43.084秒、RF12.615秒PASS | 未放宽90／120秒预算；通过不证明旧超时原因解决 |
| 本机旧内容并发2完整 | PASS，5235.260940秒；48 PASS／12 NA、6311ID | 41e内容加35原差异，不代替5ff，不与其它并发／环境称纯提速 |
| CI41434132988 | FAIL，839.6419828秒；10 PASS／1 FAIL／30 BLOCKED／11 NA | cp1252中文路径输出失败；UTF8路径／manifest专项随后通过，原失败不改写 |
| CI41438756700／41438833571 | 均FAIL；2415.366513／4278.403782秒 | 普通安装T5 schema归属缺口；独立审又发现300mm／C3同类生产问题，随后实修 |
| 三publisher普通安装 | T5：10项2.476秒，9 PASS＋1可选receipt skip；另两模块14项8.266秒PASS | 八核心模块来自site-packages；五点输出／父不变／资源身份／原子清理，不授予新原生资格 |
| 5ff本机standard8完整 | FAIL；45 PASS／4 FAIL／12 NA；外层1945.303103秒 | **环境准备错误**：只用`-c`约束核心依赖，未用`-r`安装全锁，遗漏ruff／pywin32 |
| 完整环境纠正及Changed | 24适用锁版本、pip check／全库Ruff通过；Changed10 PASS／33 NA、257记录、325.500793秒 | 四受影响完整模块补验不是Repository PASS；不改在途旧环境掩盖失败 |
| 精确5ff完整CI | SUCCESS，49 PASS／12 NA，外层3886.785380秒 | 该提交完整软件PASS；226skip限制及原失败均保留 |
| a8远端41477191576 | FAIL，46 PASS／3 FAIL／12 NA，外层3668.4654428秒；6336唯一ID、226skip | failure-drain派发计数与RF两个AnalyzeOnly 300／180秒超时；后继修复不改写该失败，原RF子输出不足，未定根因 |

standard8原文字“all locked dependencies installed offline”不准确：`-c`不会安装requirements-lock的全部工具。
Agent0明确承担准备错误；原日志、FAIL与纠正记录并存。云端实际`-r requirements-lock.txt`不受本机遗漏影响。
原15分钟完整反馈目标未降低或达成；新增覆盖、构建／安装、锁依赖、重试及环境纠正均属真实成本。
没有同范围、同环境、同规则依据时不计算普适提速；模型账单未测，不给出虚构金额。

## 原超时的2／4／8窄诊断与观测限制

外层证据文件 `sfi-concurrency-evidence-review.md` 实读原summary、timing、process JSONL与日志。
三轮均在旧policy上顺序运行，13 PASS／33 NA、相同497ID；不是完整Repository或新规则验收。

| 指标 | cap2 | cap4 | cap8 |
|---|---:|---:|---:|
| 公共命令外层wall，秒 | 1625.214 | 1207.280 | 1001.179 |
| 所有PASS阶段queue之和，秒 | 2492.163 | 878.408 | 71.435 |
| resource_wait之和，秒 | 26.266 | 27.207 | 33.007 |
| execution之和，秒 | 2644.979 | 2688.219 | 2969.439 |
| 目标整个方法，秒 | 42.575 | 43.839 | 73.556 |
| CIM所见同时stage进程峰值 | 2 | 4 | 8 |

外墙钟下降伴随槽位queue总量下降，但resource_wait和execution总量反而增加；不能说所有方法变快或等待消失。
阶段计时互相重叠，queue＋wait＋execution总和不能当wall；stage进程包含准入等待／收尾，不是同时占CPU数。
目标整个方法73.556秒也不是其某个90秒subprocess的同一计时区间，不能用两者差值解释旧超时余量。

| 采样覆盖指标 | cap2 | cap4 | cap8 |
|---|---:|---:|---:|
| CIM query累计秒 | 100.260 | 74.400 | 65.547 |
| 树CPU秒增量下界 | 1570.109 | 1635.938 | 1828.609 |
| 树WorkingSet求和峰GiB | 1.358 | 2.233 | 3.479 |
| 整机available RAM最小GiB | 28.805 | 28.310 | 27.373 |
| ReadTransfer增量GiB下界 | 7.025 | 6.887 | 7.466 |
| WriteTransfer增量GiB下界 | 1.084 | 1.090 | 1.092 |

查询wall约各轮6.17%／6.16%／6.55%，不是观察器CPU占用，不能从gate wall直接扣除；未做无观察器对照。
CPU／IO按PID＋CreationDate累计max−min，短命和采样外区间会漏，不能当完整消耗；WorkingSet共享页会重计。
Transfer计数可能含cache／非磁盘I/O，不是设备吞吐、队列或锁证据；可用RAM快照不能排除瞬态／预算约束。
CIM非原子、2秒漏短进程、cache顺序未随机化、其它host活动未受控；无采集error也不代表无盲点。
目标fixture还有私有ledger，outer wait不覆盖其内部全部等待；旧SFI／RF失败阶段窗并未互相重叠。
本轮没有复现原超时，原小进程stderr缺失仍限制追因，不认定95% CPU、CIM、磁盘或某个锁为唯一根因。
RF旧规则2／4／8三轮均PASS（13 PASS／28 NA），555唯一测试ID集合相同。外层墙钟分别885.1619194／748.6380123／863.3950062秒，目标整个方法11.353087／12.390455／14.897612秒。该组4路最快，8路更慢；不能由此推断所有范围最优并发。三轮execution阶段总和1538.397／1658.126／1993.759秒，resource_wait总和27.987／26.756／82.445秒。此为原预算有限重放，六轮均未复现旧90／120秒超时，不能以通过宣称根因解决。详见 rf-concurrency-evidence-review.md 与 timeout-boundary-review.md。

## 最新统一GATE规则、独立审查与小组证据

用户最新指令覆盖早先hosted-only／opt-in设计：**本机和远端普通软件GATE统一默认4**，可显式2、8、
1..32、auto／旧0；auto保留`min(8, logical_processors)`。不再保留Shared／GitHubHostedCI双policy或hosted资格门。
普通非heavy GATE的CPU压力／核预算只观测；内存、IO、独占、依赖、清理及嵌套继承防倍增保留。
SIMION／COMSOL及heavy GATE仍走原重资源保护，不把软件吞吐规则扩成商业求解豁免。
新普通GATE资源等待默认1800秒、正数可配；deadline不提高测试90／120秒预算，不强杀健康科学worker。
只清理本次queue／grant，活后代或身份未知保留保护；继承父token不误释放，次级清理错误不替换主错。
旧冻结policy缺新字段时保留旧行为，新字段存在而≤0则拒绝。CIM／OS返回后复查deadline，不声称毫秒级强制抢占。

外层证据文件 `dedicated-ci-independent-review.md` 未发现新的确定阻断，允许提交与真实Owner比较，
不是新完整PASS。62 scheduler项3.540秒、64小组34.138秒、116项公共Changed及最终deadline／transition／
summary／正等待policy小组均有实际结果；Changed摘要131.782411秒。64项原transcript漏native stderr的限制保留，
后续raw小组日志补足，不把该transcript冒充完整原始输出，也不把这些不同source切片相加当a60全套。

同一workflow复用Owner路径，普通安装＋完整`-r`锁、来源／模块／实际方法multiset、CPU／RAM、wait、
外墙clock和always失败证据保留。旧5ff2与新a604比较跨policy代码，不能称同代码纯worker因果对照；
需实核实际checkout、相同SFI完整Owner集合及skip／失败，不用空plan或上限数字冒充真实执行。
历史a60 workflow仅为具名5ff基线记录`legacy_wait_unbounded`；该一次性分支已在676退出，当前正式入口统一传入有限wait参数，历史源码和对照证据保留。

远端旧Owner基线[41470687853](https://github.com/Bibibabibobi96/mass_spectrometry/actions/runs/41470687853)
已SUCCESS：SFI Owner9 PASS／34 NA，676个timed方法、74个模块，外层531.6734636秒，实际日志6＋2共8个条件skip。
已读`ci-41470687853`的settings／timing／inventory：**实际被测源码为5ff，workflow源码为a60**，不能混作a60代码PASS。
该runner为4逻辑核、Python3.11.9，wait明确为`legacy_wait_unbounded`，新wait参数未传入旧CLI。
模块multiset SHA：`aa6702411b4903fa21abdebf2e3c051e29b2319ea046854644e8c9546c1888c9`；
方法multiset SHA：`ed80de740abf1b890268f7a81325033a2ff68ade2ceaec26a5c8c1f4320edb46`。
新a60 Owner4 [41472656425](https://github.com/Bibibabibobi96/mass_spectrometry/actions/runs/41472656425)已SUCCESS，9 PASS／34 NA，外层366.0398211秒。两侧74模块、676方法multiset SHA与锁文件相同，均8项条件skip。本次配对观察外墙缩短约31%；阶段区间峰值2→4包含wait／cleanup，不能直接当CPU并行。系统CPU时间加权均值58.70%→62.51%，采样峰值95.51%→100%，两侧最低可用物理内存均超过12GB；只归本次独立VM观测，不能声称纯worker因果或通用稳定提速。

a60广范围Changed [41470642851](https://github.com/Bibibabibobi96/mass_spectrometry/actions/runs/41470642851)实际FAIL：内部1202.718172秒，13 PASS／1 FAIL／28 BLOCKED／11 NA。失败集中在两个既有分片测试夹具的三个子场景：PlanOnly冻结默认4而执行显式3，入口正确拒绝修改上下文，尚未生成被测试摘要。原失败保留；夹具已在a8同步显式计划3并增加覆写拒绝回归，真实roots／exit7／完整分片和失败传播断言保留，完整37项221.870秒通过。随后676仅调整已完成一次性工作流能力的测试与共享正文定位，完整38项parallel加wrapper共39项另验通过，不能用局部结果抹去a60失败或代替676完整回归。

## 本机完整成本与P4反馈目标

三轮同机显式8路完整Repository外墙为2070.549008、1932.278448、1923.235844秒，分别观察6336／6337／6339唯一ID，均移除0、raw汇总21skip。锁依赖、v4／v5 payload、测试增补、后台活动与cache条件有差异，不作受控因果benchmark。0cecf约32.054分钟，仍比15分钟目标多1023.236秒；目标未下调，R17责任仍由路线图P4承担。

| 0cecf阶段 | queue秒 | execution秒 | 本轮事实 |
|---|---:|---:|---|
| integration测试分片04 | 29.123 | 1046.465 | 最长执行分片，约17.44分钟；不是最终结束的阶段 |
| RF领域 | 1452.221 | 443.174 | 最晚结束，summary起点后1920.001秒完成 |
| IP | 1534.801 | 256.649 | 较晚派发，summary起点后1815.805秒完成 |

queue含并发槽和依赖等待，不等于CPU等待；execution含内层子进程、复制、私有准入和收尾，不是CPU秒。stage区间重叠，累计queue42747.294、resource_wait126.536、execution13112.191、cleanup95.848秒均不能相加成整轮wall。RF／IP无显式requires_stages，但摘要不足细分所有晚派发原因，不能直接归因为某个锁或CPU阈值。

现有证据的P4排查优先级是：验证及RF／IP owner核查ready顺序与晚尾部；integration owner分解313.493秒field-design、212.164秒完整母群回放等整方法fixture成本；发行owner保留166.143秒普通wheel＋sdist树外调用保证，核构建／启动分量。只共享不可变准备结果，保留真实消费者及失败行为，不以少跑测试、editable、改预算或新增无证据缓存达标。完整top5阶段、top10方法、计时边界及输入SHA在证据文件 `final-local-gate-cost-profile.md`／`.json`；本次没有新测试或额外采样。

## 原始归属、清理与真正未完成项

35个原有工作树差异以保留patch、逐文件字节及快进证据保护；初始归属不能完全独立重建的限制不抹去。
380阶段根树快进时，36个其它dirty文件整合前后字节相同；473680ec快进及最终临时资产清理后，38个dirty文件字节全部相同（final-race-repairs-root-integration-after.json、final-cleanup-root-preservation-proof.json）。与本组重叠的common／RF两文件原hunk按保存patch重放，除base blob与行号外内容一致，见`shared-fixture-root-integration-after.json`；此前0cecf的37文件字节保持与RF空白重放证据另存`fixture-repairs-root-integration-after.json`。这保留原35项差异与3份文档纠正，不将其归为本次纯提交内容。分片夹具修复已提交、推送；37项完整模块测试通过，未修改生产规则或删减覆盖。历史失败、原manifest和数据不重写。
已清理两套可重建标准环境780904340逻辑字节／24884文件；卷free变化832458752字节受并发写影响，
不当作精确释放量。wheel／wheelhouse／锁文件及必要小证据保留；不与其它清理重复累计。
`diagnostic-env`曾用于普通wheel的本机完整验收；473本机终态后，其任务用途已结束并按下面的精确清理收据退役。六项超时诊断终结后，一次性monitor已按精确路径删除，9339字节；原始采样、摘要和校准证据保留，处置记录为 timeout-monitor-cleanup.json。

## 活跃代码内部冗余清理及局部验收

用户补充要求覆盖活跃脚本中的冗余，而非只删除无消费者文件。审计分科学核心、公共运行机制和CI工作流三个边界，逐项核实调用及生命周期。隔离树已删除 cylinder._position 不读取的 radius 形参及唯一实参，保留实际径向计算和全部随机调用顺序；断言模块来源为隔离树后，完整 cylinder 21项测试通过（0.539秒，无skip）。该主题提交c0cb9dc8，已随676整合入根树；此前a8完整结果不覆盖清理后代码。

既有完整发行测试1项通过（161.756秒，无skip；测试命令外墙163.0876518秒，不含公共准入／释放），真实普通wheel和sdist重建wheel在临时site-packages执行，38schemas／310refs、源和TOF实际输出与来源均核验；临时builder和consumer按原测试清理。原diagnostic-env未修改。

公共路径首次绝对路径校验结果已复用，完整8项路径模块通过（3.264秒，无skip），原冻结分支与错误顺序保留。资源释放三处相似块因异常语义不同未硬抽；公开lease.owner_pid字段不因本仓未读擅自删除。

CI一次性source_ref／旧5ff等待API例外和未读变量已退出，两job用单一YAML run标量共享观测正文；正常Changed／Owner／Repository、实际来源SHA、collection hash、CPU／内存采样、外墙、实时输出与失败artifact保持。完整parallel模块加初版wrapper共39项318.211秒通过，无skip；补回Repository覆盖及两个投影各missing／badJSON后，只重跑同一wrapper方法，1项10.460秒通过（7执行／4拒绝子场景）。两轮重叠，不能称40项不同测试。独立审查通过；该主题提交676754c8并推送，676远端完整轮41483522762已SUCCESS：49 PASS／12 NA、6337唯一ID、226skip，内部2061.180436秒／外层2062.6196764秒；0cecf新轮另行绑定，不覆盖该旧轮。仍具名消费的P4桥与有效失败清理不作为死代码删除。

活跃源码两项清理主题的官方CLOC比较为 a8f9226cfe35257c1c5071f44ba977cbe60f2691 → c0cb9dc890a51e59d7d31b9997cfa1b0cee1041a，CLOC 2.10，total／production／tests 的 files、blank、comment、code 及全部语言 delta 均为0：本次删除的是同一行内多余参数／调用，并非整行。完整数值和过滤口径保存在 cloc-active-core-path-cleanup.txt，不能用净行数0否认实际冗余已删除，也不将其说成缩短整仓代码行数。

## 后继软件fixture修复：实际保证与验证切片

修复簇85119f5e＋0cecf只修改测试／test-support，不改生产scheduler、商业资源策略或科学实现。

failure-drain旧fixture依赖sleep竞争；它的云端计数失败不能证明生产父在观察失败后仍派发。
新fixture用实际父Set-GateStageResult完成原FAIL记录之后的事件区分早／晚失败：早失败严格FAIL／PASS／BLOCKED／BLOCKED、starts=a/b；
晚失败严格FAIL／PASS／PASS／BLOCKED、starts=a/b/c，且b.done<c.start<a.done<父观察<c.done。已启动健康工作自然排空、未派发工作阻断。
原60秒总timeout、实际imports／全选不重复、ruff一次、依赖／preflight与失败返回断言保留。
真实负控制只在临时副本关闭StopOnFailure，8.685秒得到starts a/b/c/d/e并在严格BLOCKED计数断言失败，属于EXPECTED_RED，不是无关import或事件超时。
focused两方法24.799秒PASS；完整模块32项297.661秒PASS、无skip，开／结束源码SHA一致。
证据文件 `failure-drain-fixture-independent-review.md`、`selected-ps-failure-sync-full-module.log`、`selected-ps-fail-fast-mutation-red.log` 保留。

RF两超时路径私有ledger仍读取整机CPU；COMSOL/postprocess原2核／95%规则在4核时有CPU>45%即headroom等待的可达路径，
但旧现场子stderr／ledger不足，不能认定它是a8实际根因。仅在系统Temp、仓库外的精确临时副本控制snapshot的CPU返回值；
真实CIM、PID／创建身份、内存、IO、COMSOL角色及独立token／released事实保持。非法真实CPU原值不被0覆盖，控制输入拒bool／非数／非有限／越界，失败写前后生产与目标字节核验。
实际高CPU NoWait给出cpu_pressure／cpu_headroom等待，低CPU同token获准后运行真实managed Python、核验PID／exit／真实released；CPU控制不替换被测分析的实际输出。
接口合成parent仍保持非继承COMSOL release；负科学结果、父字节、源／offset／origins、Resume不重算与未知writer保护均保留。
纯软件冷提取fake launcher亦仅控制自身临时副本，正／负真实release与原模型不变均验证；未启动真实COMSOL／MATLAB／SIMION。
原300／180秒预算不变，TimeoutExpired只先保存partial stdout／stderr后原样raise；未删商业／heavy CPU、内存或独占保护。

RF首轮focused3项95.602秒PASS；两完整模块18项210.114秒PASS对应较早source；后加输入guard的唯一方法15.177秒PASS，
再加fake冷提取接线的实际方法11.666秒PASS。三份source SHA清单分别为 `rf-controlled-cpu-full-source-sha.json`、
`rf-controlled-cpu-guard-source-sha.json`、`rf-controlled-cpu-final-source-sha.json`；轮次重叠，不能称最终hash整18项已重跑。
独立审文件 `rf-controlled-cpu-independent-review.md` 绑定最终三文件hash，最终0cecf本机整库验收已通过，远端FAIL，后继处置另列。
短Python观测原 `RESOURCE_OBSERVATION_WARNING=metrics_failed`／找不到“Sum”属性的警告保留，不宣称CPU／RSS峰值量化完整。
上述修复解决已确认的fixture竞争／非目标CPU输入依赖，保留真实科学、进程与收尾责任；不声称旧超时根因已全部证明。

## 0cecf远端失败：完整普通准备的惰性边界夹具

0cecf远端41492547577实际FAIL，48 PASS／1 FAIL／12 NA、6339唯一ID／226skip，外层3621.1485869秒。唯一失败stage为RF quadrupole测试分片02；`test_comsol_owner_finalization.test_normal_public_prepare_and_optional_family_reach_only_inert_native_boundary` 的family=False／True均触发原300秒TimeoutExpired。该方法未在先前三文件RF控制范围内，未捕获partial child输出，不能据此认定CPU为旧现场唯一原因。此前a8三个失败职责stage本轮均PASS，但这不抵消新失败。

已核调用链：该临时副本确实进入COMSOL/prepare的普通2核／2GiB主机准入，再到只写native_started=false并抛错的惰性原生边界。bare工程合同16GiB进程上限／8GiB可用量属于后继native观察限制，当前不分配native进程；不得为变绿降低该工程合同。已集中核对所有RF及其他测试的同类无native临时副本准入边界，完成清单、380204be修复与定向／完整模块验证，现冻结重做完整验收，不改真实COMSOL/SIMION政策、不扩大超时、不据单次PASS宣称历史因果已证。

## 380204be集中修复与活跃代码去重

0cecf失败后先做实际调用链清单，新增边界仅RF normal prepare的两个family场景、公共workflow父独立SIMION/flight准入、SFI纯软件heavy pool bridge。生产CPU／内存／IO／独占／PID／释放规则不变；原90／180／300秒预算不扩大。共享测试helper位于`common/contracts/test_support/host_cpu.py`，删除RF旧36行实现及未用导入，无转发副本；仅在仓库外系统Temp的完整原字节副本控制合法CPU输入，非法真实观测继续失败关闭。共享helper单路径的公共Changed PlanOnly实核覆盖common四分片、SFI四分片、RF三variant及保守消费者，规划不冒充执行PASS。

公共workflow只控制父首次准入，子进程继续真实继承／PID／退出／父释放与过期拒绝；SFI仅在真实freeze调用期间将host source_id指向受控作者输入，编译器正常计算原始与Python绑定后hash，再实际验证closure。没有修改冻结文件后手补身份。RF保留工程16GiB／8GiB、源／family身份、非零退出与native_started=false惰性边界；新增partial超时输出后原样raise。

RF三项定向96.372秒PASS、完整owner模块五项73.701秒PASS；公共／SFI两目标51.596秒PASS、两完整模块79项288.249秒PASS，均无skip。轮次包含重复方法，不能相加声称89项唯一测试。Ruff、开发标准、LF、diff与独立复核通过，证据为`shared-software-cpu-fixture-independent-review.md`、`software-cpu-consumers-validation.md`及对应四份原日志。本组是测试确定性修复，不证明历史超时唯一CPU根因。

提交`380204befa3b772e38ae32b5a1b670de99b29ba2`已推送任务分支。根树快进后，36个其他dirty文件逐字节不变，两重叠文件原hunk除Git坐标／blob身份外完全一致，见`shared-fixture-root-integration-after.json`。普通v5 wheel57payload及24锁包、具名Ruff／pywin32入口再次核验，未重装环境。`final-380204be-environment-proof.json`在实际380 HEAD重新核验正式安装来源及pip check；此前`shared-fixture-environment-proof.json`仍保留其真实0cecf＋冻结WORKTREE时点，不回填历史身份。新本机8路完整已PASS，49 PASS／12 NA，6339唯一ID与0cecf集合完全相同，较基线+48／−0，21skip；内部1807.695383秒／外层1809.3350065秒，退出后2553文件无变化／增删。独立复核`repository-380204be-local8-acceptance-review.md/.json`已实读原日志、summary、原改动保护及环境证明。该轮[远端完整4路](https://github.com/Bibibabibobi96/mass_spectrometry/actions/runs/41508165176)后来FAIL，48 PASS／1 FAIL／12 NA，具体worker事实发布问题见后节。本机期间另有官方CLOC只读比较进程，因此该轮墙钟不作为独立无干扰性能基线。

活跃代码清理已包括：c0cb删除规范圆柱采样私有函数未使用参数及唯一路径调用冗参、复用原路径校验结果消除同值重复验证；676删除CI未用source_ref及过期兼容分支、共享YAML步骤正文；380删除旧RF重复helper。仍有具名消费者的六类科学桥未被误删，其最迟P4退出条件另列。删除依据是实际职责和消费者，净CLOC增加不等于未做清理，也不以降行数替代科学覆盖。

## 380 Changed失败：三轮缓存恢复的原60秒边界

[41508003929](https://github.com/Bibibabibobi96/mass_spectrometry/actions/runs/41508003929)终态FAIL，实际source／workflow均380204be、4worker：14 PASS／1 FAIL／10 BLOCKED／26 NA，内部1958.627011秒、公开外墙1960.0706139秒。唯一失败为integration分片02的`test_cooled_frontend_execute.CooledFrontendExecuteTests.test_ordinary_cache_resumes_only_missing_fields_then_hit_without_native`，原60秒TimeoutExpired，方法60.418742秒；该分片145项846.849秒、errors1／skip8。后继十个BLOCKED不能写已验收通过。

首次live失败在19:31:26 UTC，19:48:13是最终日志重播，不当作第一次超时。旧helper没有保存partial stdout／stderr，私有cache／锁／进程树现场不在artifact；只有整机CPU／内存采样，不能据此认定具体child阻塞或历史CPU单因。证据为`ci-380204be-changed-failure-review.md/.json`、`ci-380-changed-log-failed.txt`及原artifact。

实际只提取PS字段缓存函数，host budget／stage更新／容量／native均为stub；真实边界是三轮中断／resume／HIT、七个成员、静态47次Python冷启动和真实公共cache事务（17＋21＋9）、每key原OS锁。它不走RF类型真实CPU准入，不能盲套CPU控制。先追加原Name／start／end／exit计时及超时partial后原raise，定向核查累计启动与锁；生产实现、科学输入、原60秒和原七成员保持，尚未给出因果结论或修复PASS。该时点完整41508165176尚在运行；后来它亦有独立FAIL。本机380完整PASS不抵消Changed FAIL，故当时没有关闭A23／A30。

## 380完整远端失败与473680ec集中夹具修复

[380完整远端41508165176](https://github.com/Bibibabibobi96/mass_spectrometry/actions/runs/41508165176)已FAIL：48 PASS／1 FAIL／12 NA、6339唯一ID／6342计时记录、226skip，内部2546.206261秒／外层2547.3052042秒。唯一失败为`livelink_resource_stages_tests`的真实惰性进程归属清理场景owned，读取worker事实时没有pid；31项133.605秒、failures1。缓存测试本轮PASS，不抵消同提交Changed中的原60秒失败。首次live失败19:53:32 UTC，19:58:38为重播；原worker JSON字节未留，不能证明现场确切内容。`ci-380204be-acceptance-review.md/.json`保留实际终态和缺口。

实际源码有可达发布竞争：子进程直接向final JSON路径Set-Content，父只等Test-Path再立刻解析。修复仅测试事实发布：完整写入同目录临时文件、关闭、Move到唯一ready路径。owned场景确定性暂停半写临时JSON，父验证它确不完整且final尚不可见，释放后再读完整真实PID／创建ticks。真实祖先、stale／orphan／observation_failure和foreign sibling不杀原断言、10／20／30秒原期限与生产Stop均保留。原失败Visible方法四场景7.890秒PASS；共享hidden及Visible的完整31项100.003秒PASS，无skip。有限同类JSON握手清单未发现额外确定缺陷，未把plain marker或已Wait完成后读误列同类。

缓存定位先在原47冷启动／原60秒下追加观测：单独22.873秒PASS，47调用累计20.727023秒；与三个实际窗口代表方法的四路近似cohort，全部四项PASS、组100.833535秒，目标28.325秒、47调用累计25.745609秒。未复现旧60秒失败，调用累计包含真实cache计算／IO，不能全部命名冷启动开销，也不能定CPU或锁唯一因果。不同本机16核与远端4核、历史时窗阶段换槽及样本锚点限制都保留在诊断报告。

随后仅在同一测试的已有Invoke-FrontendRuntimePython替身边界复用一个选定解释器，47个原argv代码块和真实缓存事务、17／21／9三阶段、七成员与原60秒功能边界保留；生产仍走原入口。每请求新exec命名空间／sys.argv、还原测试patch的原函数，保留真实stdout／stderr和请求失败。正常操作另验证请求exit7及坏JSON拒绝；请求状态不冒充worker OS退出码。父实际handle守护独立于EOF及正在执行请求，验证正常／父异常／worker活动中父Exit19时实际Python及venv launcher两PID均消失；正常实际OS码0有独立handle事实。非Windows后备守护保留但未本机实测，不冒称跨平台验证。

早两次worker握手RED暴露Windows venv redirector PID与实际Python PID不同，记录后改为真实父launcher边及实际PID校验，未放松selected exe／cwd来源。首5.912秒focused不等同最终source全模块；最终冻结源码完整九项20.099秒PASS、无skip，47真实请求累计1.556189秒（仍包含cache／IO）、两个协议负例和三生命周期六PID退出证据具备。`380-final-fixture-repairs-independent-review.md`已独立实读两个完整模块、最终SHA及原科学缓存断言，代码没有审阅阻断；原两个CI FAIL不被覆盖。

代码按两个主题提交54316fdb、473680ec，最终`473680ec388dd7d52d4c2dea4bc90aa6622a54dc`已推任务分支。根快进前后38个dirty文件字节全部不变，见`final-race-repairs-root-integration-after.json`；核心57payload／24锁包与普通安装再次实核，见`final-473680ec-environment-proof.json`，未重装环境。新[完整远端41517777976](https://github.com/Bibibabibobi96/mass_spectrometry/actions/runs/41517777976)已SUCCESS，49 PASS／12 NA，内部3601.484388秒／外层3603.1305534秒，实际4worker，6342计时记录／6339唯一ID；与本机集合完全相同，16段汇总226skip。独立ci-473680ec-acceptance-review已核普通安装／锁、四消费者／安装隔离／UTF8／冻结资源拒绝的实际选择。resource wait累计117.290396秒、active区间peak4含等待与收尾，不当作四CPU计算或因果提速证据；本机8路完整session85840已exit0、49 PASS／12 NA、6339唯一ID与380集合完全相同，21skip；内部1799.126825秒／外层1800.7282891秒，退出后2553文件无变化／增删。独立repository-473680ec-local8-acceptance-review.md/.json已实核覆盖、条件skip、原38dirty保护、实际普通安装环境与来源；官方CLOC均先于本机计时结束，但单次约30.012分钟仍不冒称稳定性能基准。[Changed41517678968](https://github.com/Bibibabibobi96/mass_spectrometry/actions/runs/41517678968)已独立实核SUCCESS：6 PASS／33 NA，实际LiveLink31项122.508秒＋cooled九项33.066秒，共40唯一ID、无报告skip，内部145.727235秒／外层146.9184655秒。原inventory模块表为空，其empty-list摘要不被采信用于模块同一性；用实际summary命令和40方法ID证明范围。该范围较窄，不与380共享helper的宽Changed直接比较速度。两项修复均只在测试，生产／科学代码未变；最终两端完整验收与用途清理均已具备原始证据。

## 本任务临时资产的最终处置

473本机完整终态且无后继本机科学测试消费者后，核对两固定绝对路径在本工作区内、根及子目录无reparse、实际PID可执行文件／命令行无消费者、工作树干净且相同473提交保留于根与任务分支。辅助树的173个忽略文件仅161个Python字节码及12个带实际Ruff标记的缓存，无唯一输入／日志／原生资产。通过Git标准worktree remove退役辅助树，再仅删除任务专用diagnostic-env；没有改动其他已注册工作树、原开发`.venv`、原科学资产或用户配置。

实际移除15721文件／631714928逻辑字节；卷可用空间观察增加665821184字节，包含并发OS／用户写入，不当作精确物理释放量。`final-temporary-assets-cleanup.json`、正确重做的precheck和ignored inventory保留；首轮可执行文件过滤表达式作用域错误的无删除预检已标记superseded，不作为删除依据。清理后38个dirty文件原字节均同、三个v5发行摘要再核相同，见`final-cleanup-root-preservation-proof.json`。正常安装环境验证结果仍绑定它真实运行时的路径；必要复现依v5、锁及保留wheelhouse重建、重新规划，不把历史plan当现成可执行输入。

另将系统Temp内八份必要基线文件1823112字节按原SHA复制至本机`baseline-retained/`，原FAIL／6291唯一ID及旧0.1轮子身份不改，后者仅为历史证据；当前发行仍是v5／0.2。`final-baseline-evidence-preservation.json`记录逐文件bytes／SHA，原Temp文件及wheelhouse未删除。后续文档检查使用既有开发环境，不能替代已完成的普通wheel隔离证据。

## 最终交付与验证边界

代码终态绑定473680ec；后续提交只同步文档。两个完整范围及Changed真实通过、安装／科学／依赖／冻结／路径证据、原失败和skip事实均在上文及具名原始记录保留。当前规范、API导航与阶段责任分别由其唯一权威维护，AUDITS提供本记录入口。文档变更使用既有开发环境执行实际受影响路径的公开Changed门禁，命令、summary和原始日志为`phase01-final-documentation-*`；这不替代先前普通wheel及sdist隔离证据。

本机完整覆盖35项保留的原有差异；远端是干净473提交，不能称两端工作树逐字节相同。清理前后原38个dirty文件及v5摘要同一性另有收据；最终文档只提交本任务六条明确路径，不夹带其余35个原差异。受验代码与文档提交的边界由Git差异及任务证据核对，不把文档后提交伪称已重跑整库。

原全仓15分钟及复杂Owner5分钟目标没有下调；科学／原生／数值／GUI资格与本次软件通过分开。后续动作从ROADMAP的P2–P5及R01–R20责任表进入，兼容桥最迟P4退出。软件门禁默认4、显式1..32及auto的既定规则保持；本机本轮明确8、远端明确4，CPU观测不抹除内存、独占、依赖、嵌套及重计算的原保护。

## 附：完整CLOC、分类与过滤

以下为精确提交比较，不含35项原差异或3份任务文档纠正，由仓库官方入口生成。原始输出为`cloc-v4-473680ec.txt`，完整表为同名`.md`；unclassified files/code均0。单独两夹具主题380→473见`cloc-final-fixture-repairs.txt/.md`：total/tests code各+67、production0、blank+2/comment+138；按官方CLOC对内嵌脚本的统计口径报告，不以物理diff行数替代。前序完整CLOC也保留原报告，不回写旧结果。


BASELINE=18afd1fe5368bf1c1542b7d75db977051ed44af9

RESULT=473680ec388dd7d52d4c2dea4bc90aa6622a54dc

CLOC_VERSION=2.10

CLASSIFIER_SHA256=d3365e7f02e66a775ec8eb3b12fb7b7bfa1bf34b87009543768a8e36bb4db749

LANGUAGE_DEFINITION_SHA256=985e60f06bd8981c36966a0895cccfccd182fd625c79eb6ae94b65a12c5508a6

FILTER=extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|tests_boundary/*_fixtures.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked


### total

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| JSON | 256 → 256 (+0) | 0 → 0 (+0) | 0 → 0 (+0) | 35476 → 35537 (+61) |
| Lua | 100 → 100 (+0) | 369 → 369 (+0) | 749 → 749 (+0) | 11425 → 11425 (+0) |
| MATLAB | 160 → 160 (+0) | 1016 → 1016 (+0) | 1983 → 1983 (+0) | 17783 → 17783 (+0) |
| PowerShell | 146 → 146 (+0) | 1114 → 1118 (+4) | 1195 → 1392 (+197) | 47241 → 47312 (+71) |
| Python | 935 → 957 (+22) | 25996 → 26155 (+159) | 31359 → 32016 (+657) | 305899 → 307542 (+1643) |
| SIMION GEM | 10 → 10 (+0) | 26 → 26 (+0) | 54 → 54 (+0) | 214 → 214 (+0) |
| TOML | 1 → 1 (+0) | 4 → 8 (+4) | 0 → 2 (+2) | 24 → 37 (+13) |
| YAML | 2 → 2 (+0) | 6 → 8 (+2) | 6 → 15 (+9) | 247 → 437 (+190) |
| SUM | 1610 → 1632 (+22) | 28531 → 28700 (+169) | 35346 → 36211 (+865) | 418309 → 420287 (+1978) |

### production

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| JSON | 253 → 253 (+0) | 0 → 0 (+0) | 0 → 0 (+0) | 35054 → 35115 (+61) |
| Lua | 81 → 81 (+0) | 299 → 299 (+0) | 639 → 639 (+0) | 9524 → 9524 (+0) |
| MATLAB | 96 → 96 (+0) | 496 → 496 (+0) | 1399 → 1399 (+0) | 10812 → 10812 (+0) |
| PowerShell | 138 → 138 (+0) | 1055 → 1059 (+4) | 1162 → 1359 (+197) | 45552 → 45623 (+71) |
| Python | 440 → 459 (+19) | 13745 → 13786 (+41) | 9727 → 9796 (+69) | 153467 → 153615 (+148) |
| SIMION GEM | 10 → 10 (+0) | 26 → 26 (+0) | 54 → 54 (+0) | 214 → 214 (+0) |
| TOML | 1 → 1 (+0) | 4 → 8 (+4) | 0 → 2 (+2) | 24 → 37 (+13) |
| YAML | 2 → 2 (+0) | 6 → 8 (+2) | 6 → 15 (+9) | 247 → 437 (+190) |
| SUM | 1021 → 1040 (+19) | 15631 → 15682 (+51) | 12987 → 13264 (+277) | 254894 → 255377 (+483) |

### tests

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| JSON | 3 → 3 (+0) | 0 → 0 (+0) | 0 → 0 (+0) | 422 → 422 (+0) |
| Lua | 19 → 19 (+0) | 70 → 70 (+0) | 110 → 110 (+0) | 1901 → 1901 (+0) |
| MATLAB | 64 → 64 (+0) | 520 → 520 (+0) | 584 → 584 (+0) | 6971 → 6971 (+0) |
| PowerShell | 8 → 8 (+0) | 59 → 59 (+0) | 33 → 33 (+0) | 1689 → 1689 (+0) |
| Python | 495 → 498 (+3) | 12251 → 12369 (+118) | 21632 → 22220 (+588) | 152432 → 153927 (+1495) |
| SUM | 589 → 592 (+3) | 12900 → 13018 (+118) | 22359 → 22947 (+588) | 163415 → 164910 (+1495) |

### unclassified

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| SUM | 0 → 0 (+0) | 0 → 0 (+0) | 0 → 0 (+0) | 0 → 0 (+0) |
