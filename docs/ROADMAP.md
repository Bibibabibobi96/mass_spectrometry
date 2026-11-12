# 质谱仪设计与仿真平台路线图

本文把[长期愿景](VISION.md)拆成能力建设主线，维护跨项目优先顺序、依赖与完成条件。
阶段按证据完成，不承诺日历日期；当前能力和短期任务查项目 PROJECT 或 integration INTEGRATION，
精确参数与成熟度字段查机器合同。本文的示例和未来模块名称不构成执行入口。

## 规划原则

先形成可靠的规格、器件功能和证据链，再扩大优化规模与自治程度。项目与 mode 的划分、公共代码
提升和单向依赖按[仓库架构](REPOSITORY_ARCHITECTURE.md)执行，工作流与配置分层按
[开发标准](DEVELOPMENT_STANDARDS.md)执行，不在路线图另建规则副本。

各阶段的完成条件只适用于该阶段声明，不能由功能贯通推定优化完成、跨求解器等价或 Formal 资格。
跨项目任务在参与方的当前文档登记进入条件与关闭条件，已完成运行退出本页。

部件可复用、接口可连接、物理链可验证是贯穿各主线的优先目标；不要求先完成自动优化或自然语言
自治才开展组装。下文各能力主线按真实需求和依赖选择推进，不构成所有项目必须
依次完成的流水线。只承诺本次选定物理范围的结果；缺失能力先明确登记，再按相称证据扩展。

## 早期成熟度路径

新器件或连接可按风险采用下列递进路径；各层仍消费求解器中立的几何、粒子、端口、时钟和事件合同。

| 阶段 | 目的 | 进入下一层前的证据 |
|---|---|---|
| SIMION 工程贯通与筛选 | 检查几何、注入、孔径、端口与事件漏斗 | 可追溯功能结果及明确简化范围 |
| COMSOL 物理补证 | 覆盖连续场、边缘场、材料或场重叠等所需物理 | 该求解器独立的网格、时间离散和物理证据 |
| 同源双求解器闭合 | 比较同一冻结输入与观察事件 | 事前判据下的配对结果和独立晋升门禁 |

第一层不授予 COMSOL、收敛、Candidate 或 Formal 资格。复杂连续场、强耦合、碰撞、空间电荷或材料
响应可能使低成本筛选失真，应尽早补相应物理，也可直接进入双求解器实施；跳过阶段不降低验收要求。

## 平台改进的进入条件

统一离子、束流、束团及谱峰诊断的阶段实施与复审见
[验收记录](history/20261028__unified-diagnostics-review-acceptance.md)。当前支持范围以各项目PROJECT和公共README为准；
阶段验收不授予新的求解器、GUI或Formal资格。

平台专项可由明确批准的架构需求启动，或在重复维护/运行成本已有证据、收益可验收且预算明确时启动；保护在途器件功能链。
优先采用现有公共入口；当前实现查邻近 README，不能把下表视为尚未实现能力的清单。

| 改进方向 | 启动依据 | 完成条件 |
|---|---|---|
| 求解器执行协议与适配器 | 多个项目重复同一生命周期机制 | 减少重复入口，保持冻结输入、失败收尾与 GUI 行为 |
| Schema、版本迁移与类型化加载 | 同一合同变化需要同步多个入口 | 单一权威、明确迁移及行为回归 |
| 组件 API 与依赖边界 | 新连接族或跨器件复用 | 显式端口、坐标、时钟和粒子身份；遵循[连接架构](COMPONENT_CONNECTION_ARCHITECTURE.md) |
| 工具链、CI 与执行恢复 | 预检或等待成本影响日常工作 | 可复现环境与相称检查；运行终态和恢复可追溯 |
| 粒子并行与异构执行 | 独立分片存在明确收益与资源余量 | 无损合并，事件、时钟、相位和统计等价；不虚构 GPU 能力 |
| artifact 索引与读取成本 | 清单扫描成为主要等待 | 可从 manifest 重建，不引入第二结果权威 |
| 大型旧运行器分解 | 可独立输入/输出的职责和净收益已证明 | 逐项目保持数值、GUI 和 artifact 回归 |

长路径与 PA 隔离先查[SIMION 长 PA 输入路径](tools/SIMION_REFERENCE.md#长pa输入路径)，运行环境与现有
公共入口查[操作指南](OPERATIONS.md)。已经验证的公共能力直接复用；剩余项目迁移由消费者文档跟踪。

旧复杂度台账、具体并发实验及其未裁决候选保存在
[整治快照](history/20260911__reference-documentation-consolidation.md#原-roadmap-台账)。
归档不等于关闭：未来重启这些专项时须先核对当前消费者与行为证据，不沿用历史计数。

## 科学核心与平台边界迁移

2026-11-02按用户批准的V4目标启动；**P1已在声明的有限边界内验收**，证据与限制见
[P1迁移验收记录](history/20261103__phase01-scientific-core-migration.md)。R01–R20整体仍保持开放，
后续P2–P5责任、P4原15分钟反馈目标及具名兼容桥退出条件不变。
P1/P2任务分支尚未合入master。2026-11-03按V5进入P2，实施起点为已核对后继`24eedd7b`，
同日按V6继续，命名复核基线`2de6385c`；不重开P1或回退正确成果。
**P2已在声明的提供者／后端解耦与公共命名边界内验收**，固定代码、逐项出口、成本和限制见
[P2迁移验收记录](history/20261104__phase02-provider-backend-migration.md)。
2026-11-04按V7承接有界纠正D01：中立request4的分段表不含native编号，零间隙旧检查仍有两处
`electrode_id`依赖。RF提供者现拥有实际端面截面，集成只变换位姿和判断接触；新请求的公共准备
正反例及补充组合已通过，公共受影响范围与环境失败的具名复验见
[当前集成状态](../integrations/docs/INTEGRATION.md#当前边界)。该纠正不改写P2冻结验收，也不重开P1/P2。
后续P3除共同钟、接续和恢复外，还必须交付真实RF→OA／单反射链的普通安装公共API切片：
geometry-only、求场、源、飞行、分析分别调用；不能依赖作者checkout或以假源满足几何输入。
D01已固定并推送`bf19145c`；当前按V7.2 Goal继续P3。首个几何编译安装切片已实迁RF、OA／完整TOF、
SIMION纯编译及必要执行基础，公共API与普通wheel／sdist树外实际调用已有证据，当前范围见
[集成状态](../integrations/docs/INTEGRATION.md#当前边界)。后继已取得普通安装的无GUI STEP、未求解模型独立求场、
同场同源三档连续／接续共九个轨迹产品、无商业工具重分析及独立审查者教程的有界证据。
The selected P3 delivery is accepted at code `f283b752`, with its evidence and
29 Goal / 54 C / 20 R / 8 U mapping in the
[milestone](history/20261105__phase03-installed-pipeline.md).
Complete ordinary-SDK23 Repository acceptance at `a8815a81` used eight workers:
50 PASS / 12 NA, 6804 parents (6783 success / 21 skip), 7710 successful subtests
and six native Dirichlet successes; public wall 2445.9804041 seconds, with all
2792 source paths/bytes and clean HEAD/status unchanged. The small later gate
repair separately passed the complete affected module at the final code bytes:
49 parents / 46 subtests, all successful, zero skips. No full f283 result is claimed.
SDK23's 235-payload/54-lock/245-source joins remain exact; no scientific package
or 3D rebuild was needed for the gate-only successor. Original failures and
unproved historical causes remain. Current capability, qualification and later
responsibilities have one authority in the [integration status](../integrations/docs/INTEGRATION.md#当前边界).
User clarification on 2026-11-05: correct 3D file generation and independent geometry checks are the
current CAD acceptance scope. SolidWorks repair and refinement are deferred, without blocking this goal;
historical native failures and Formal publication requirements remain unchanged.
V7.2增加同一完整Assembly的独立STEP与PreparedModel首批出口（U07／U08）：CAD／后端并列生成，
默认不开GUI且不求场／Fly，保存后分别冷打开和继续求场。所选SIMION模型、场及传播链已有普通安装原生证据；
STEP的实际生成／独立几何校验、历史SolidWorks查看与本次延期范围，均由集成正文分别记录。
P4 retains the remaining approved designs and named COMSOL capabilities. P5 tests the same user’s fresh environment and actual new needs; it requires no colleague and cannot absorb unfinished P4 migration or performance targets.
2026-11-06按V8.1启动唯一P4 Goal，实际起点为本地及`origin/master`共同的`40a13e78`，初始工作区干净，
公共主机资源账本无活动记录；工作在`task/phase04-platform-rollout`分支推进。W0只读盘点覆盖1852个跟踪源码／配置文件，
其静态引用与桥候选只用于导航，不作为完整动态消费者或删除证明。当前`rf_oatof_functional_v1`已通过原公共API完成
组件解析、完整装配和SIMION纯几何编译基线，无原生求解；P3及旧CI证据仍只绑定各自源码与环境，不冒充P4后继验收。
本Goal内依次闭合领域接口、活动消费者、独立器件与具名后端、部署、性能、退役和安装验收，不另开P4子Goal。
当前迁移任务图如下；它只记录本阶段对象归属和退出责任，不复制架构规范或授予新能力资格。

V8.7 is the active P4 scope. Its single goal continues the existing task branch and preserves
all retained scientific, installation, recovery and performance obligations. Eight domain
baselines share the existing stages and execution owner; they are not eight new runners.
First establish each physical geometry family's canonical authority, then deliver a usable
complete-component continuous SFI replacement. Generic static-field comparison, MR fixed-design
numerics and lower-cost installation feedback can proceed independently. The named MP-to-IP,
complete MP-to-OA, OA/IP-to-MR and FullJoint/prepared-joint tasks require continuous propagation
from an explicit original source; cross-model survivor relaunch is not their replacement.
Local frontend and cooled exclusive features are withdrawn, including their dedicated recipes,
policies and tests. Their dedicated local product is retired in `1ec0f843`; this is a scope change, not scientific implementation acceptance.
The user's 2026-11-12 SFI clarification prioritizes the current complete multipole plus
complete OA/TOF and public continuous flight. Do not add multipole aperture plates merely
to reproduce the historical SFI geometry: OA already supplies its aperture. The historical
plate-reconstruction draft remains private and is excluded from this SFI delivery; existing
plate capabilities with other genuine research consumers are retained. Acceptance checks
the selected current geometry, field coverage, original births/full cohort, clock and drive
continuity, installed execution and applicable native behavior. Historical metal/PA or
trajectory equality is not an extra SFI completion condition, and history remains unchanged.
Existing independent sources, historical state readers, neutral transforms and genuine recovery
remain. Keep the existing segmented MP-to-IP production path until its verified continuous
replacement can retire it in the same slice. A new public gas-property database is deferred
beyond P4; existing IP/HS1 and dual-cone/SDS migration and correctness remain P4 obligations.
Formal reusable implementations and necessary scientific strategies belong to
`src/msplatform`; research inputs, history, tests and development tools remain outside that
production tree. Existing completed slices are retained. Independent RF raw geometry/model,
independent two-/three-zone OA geometry and Wehnelt build-only operations have source-bound
ordinary-install/native evidence in their project status pages; these are not field/Fly or
scientific qualifications. SFI preparation/pulse, field planning, downstream publication,
workbench runtime, collection, continuation planning and their source/result adapters are installed;
remaining PowerShell native orchestration and other workflows' legacy seed closure still require migration. Explicit deployment
capacity policy and selected failed-output preservation use the existing owner and ledger.
The [integration status](../integrations/docs/INTEGRATION.md#installed-single-reflection-preparation)
and project status pages own the detailed evidence. Full Repository, the original 15-minute
software target and owner budgets remain OPEN; pending/cancelled CI is not acceptance.
The earlier diagnostic full Repository baseline, `778e7015`, ended with 38 PASS, 12 FAIL
and 12 NOT_APPLICABLE stages: 7,006 parents (6,838 success, 21 skip, 56 failure, 91 error),
plus one loader error; 7,996 subtests (7,894 success, 59 failure, 43 error). Its summary
elapsed time was 3,243.832287 seconds, not a separately retained external command wall.
Overlapping private validation makes this a correctness diagnosis rather than a controlled
performance baseline. Successor repairs and focused checks do not turn that failed run green.
Manifest/retention ownership, the formerly selected local frontend preparation/runtime, the initial-state CSV reader,
SFI field planning/downstream/runtime and the explicit OA closed-focus plan have now been committed
with scoped software validation. Their retired root bodies are absent. Runtime composition exposed
an empty-package freeze declaration and a stale DAG node; those were corrected without relaxing
source enumeration, and the failed run and successful targeted successor remain separate evidence.
Those scoped checks did not establish composed installation or full regression;
the latest combined installation evidence is recorded below. Full regression and
performance targets stay OPEN.

The latest retained full Repository diagnostic is the uncommitted candidate based on
`abd983b8`, recorded as `v85-composed-repository-root-r2`: 8 PASS, 30 FAIL,
12 BLOCKED and 12 NOT_APPLICABLE. The run lacked host-inspection permissions and recorded
process-identity admission failures and CLOC temporary-directory failures; three independent MR selection
expectations also conflicted with the actual Core-plus-consumer routing. The repaired
selection, CLOC and execution modules subsequently passed all 188 parents and 616 subtests
in the correct host context with the candidate unchanged. That focused successor does not
close the full Repository failure or establish the root cause of older incidents.
The earlier `4576fa69` full failure remains historical evidence.
The composed Wehnelt/OA receipt/TOF census/MR provider candidate passed the complete
ordinary wheel and sdist-rebuilt-wheel software witness in 1,072.112 seconds, with
520 runtime payloads in each arm and the source/checkout guards unchanged. The prior
MR measured-source import failure was exercised successfully in both arms. Before
committing the census, two redundant EOF blank lines were removed; its 19 focused
tests and 20 subtests passed afterward. These installation and consumer checks do
not close Repository, native acceptance or the original 15-minute software budget.
The retained reader, original recorded-birth source and opt-in generic static-field consumers
passed a frozen combined focused witness: 140 parents and 283 subtests, all successful,
in 302.033 seconds. Their complete direct-wheel and sdist-rebuilt-wheel software witness
passed in 1,006.453 seconds with 2,913 source paths and checkout bytes unchanged.
The reader, static comparison and recorded-source implementations were subsequently saved in
`9db67d02`, `17411690` and `ea4138b8`; these earlier source epochs are not final V8.7 acceptance.
The separate stage composition remains private. Full SFI policy/recovery replacement,
downstream relocated execution and an authenticated non-OA static-field comparison remain OPEN.
The V8.7 withdrawal, original-source SFI consumer (`673f6bb6`) and OA physical-policy slice
(`a3c7b804`) passed a frozen combined ordinary wheel/sdist witness in 1,098.821 seconds,
with 2,919 source records and checkout unchanged. Integrated software checks passed
134 parents/545 subtests and then 125 parents/392 subtests for their declared scopes;
the exact MR selector failures were exercised and saved separately in `0aa58a37`.
After the installation snapshot, three new Python files were normalized from CRLF to required LF
with identical ASTs. The separate committed-version GitHub run `43190854989` at `42b710db`
subsequently passed the full ordinary installed-core method in 1,524.318 seconds, including
both SFI helper arms and the original MR provider/interface selector tests. The run as a whole
failed on a different bare-frontend route expectation that omitted its real OA owner; that
expectation was repaired in `77af37b0`, with the failed method and four adjacent route checks
passing in 16.449 seconds. The failed run is not reported as successful. This remote-machine
duration is not a same-machine performance comparison with the earlier local installation.
The IP fixed-physical-CSG slice was saved in `23cd7a42`: its selection is declared in the
frozen scientific baseline and consumed by the normal configuration-directory preparation
path, recorded studies and receiver layout. The authority run passed 186 of 187 tests;
correcting the remaining new fixture's missing declaration passed 41 affected tests and
50 subtests in 17.903 seconds. Its two targeted ordinary installation arms passed in
84.891 seconds with unchanged source/checkout guards and exact frozen-input/payload joins.
Full Repository, final combined-version installation, the native continuous combinations
and performance budgets remain OPEN.
The new segmented MP producer-verification extraction was withheld under V8.7;
the existing MP-to-IP production path remains until its continuous replacement is verified.
At committed `569a017f`, GitHub run `43152720040` completed with Changed successful
and Repository skipped. This was independently checked from run/jobs metadata, not a
downloaded test artifact; it does not close the historical Repository failures.
The original combined installed-core test passed on the composed pulse/preparation
source in 266.575 seconds: all 454 runtime package payloads match the frozen
source, actual build source, direct wheel, sdist and rebuilt
wheel, with both outside-checkout consumer arms successful. This is installation
evidence for those source bytes, not native or whole-Repository acceptance. The
tracking-fixture correction changes only tests, with no package payload changes.
OA analysis, neutral gas sampling/compilation, retained IP/HS1 and dual-cone/SDS
bindings have canonical owners. V8.5 withdraws the entire cooled feature, including
its dedicated design, geometry, Program, preparation, tests and native obligations.
This is a user scope change, not scientific failure or same-function optimization;
original commits and run data remain interpretable. V8.7 also withdraws local frontend exclusive
features; its historical delivered slices are not current product obligations. Retained historical state analysis,
MR/IP neutral/backend boundaries, TOF roots/acceptance, RF finite-length kernels,
remaining actual workflows, ordinary installation and final Repository/native/performance
closure remain P4 work. No unfinished retained obligation moves to P5.

The installed RF metric assembler and IP scientific input compiler now replace their root
implementations. IP source compilation needs no vendor, seed or field; explicit unsolved
input materialization preserves the original HS1 adapter and four native Lua resources.
Native path projection/context and the single-flight Program renderer also have installed
owners and actual migrated consumers. Their scoped checks do not close the remaining
root native orchestration, current composed installation, complete regression or native acceptance.


The following is the single active P4 worklist. All rows remain OPEN until their stated
consumer and acceptance boundaries close; earlier delivered sub-capabilities are inherited,
not rebuilt. Shared interfaces, the gate catalog, installation fixtures and Git have one
integrator. Detailed domain evidence remains in the linked project and integration states.

| Task | Current responsibility and dependencies | Consumer and exit boundary |
|---|---|---|
| B00 | Integrator: candidate identity, local/cooled withdrawal and precise failure follow-up | Remove exclusive active consumers while preserving shared functions; actual successor failures pass without claiming full acceptance |
| B01 | SFI replacement; after B00 | Real SFI request through existing public stages, then retire replaced execution bodies |
| B02 | Generic static-field comparison; after B00 | OA and a real non-OA static-field consumer; preserve separate pulse and sampling responsibilities |
| B03 | Unique complete geometry and continuous-field boundaries; after B00 | Canonical OA/RF physical families across standalone/TOF/MR; real member/port/parameter and instance tests, justified connected field coverage |
| B04 | Complete IP and continuous MP-to-IP; after B00/B03 | Complete guide/HP/LP/exit and HS1, original source through both full components; install/native evidence before retiring segmented production |
| B05 | Complete MR combinations and fixed-design numerics; after B00/B03 | Inherit the delivered catalog provider; avoid duplicate internal OA, separate physical gap2 from representation and close renderer/field/continuous tracking |
| B06 | RF/OA/TOF capabilities and scientific strategies; after B01 | Real native and ideal paths remain separately identified; unique methods and consumers retained |
| B07 | Dual-cone/EI/Wehnelt; after B00 | Existing staged and build-only operations, resources, cold reopen and applicable native checks |
| B08 | Complete continuous composition; after B01/B03/B04/B05 | MP-to-OA, MP-to-IP, OA/IP-to-MR and FullJoint/prepared-joint reuse the same complete model/field stages and execution owner; no survivor relaunch or local product |
| B09 | Research campaign strategies; after B01/B02 | Retained radial, compensation, spectrum and finite-length tasks share execution and recovery |
| B10 | Retained gas chains; after B00 | IP/HS1 and dual-cone/SDS preserve G01–G18 and their distinct models/vendor evidence |
| B11 | Installation and feedback cost; after B00 | Selectable real probes and immutable builds; full wheel/sdist coverage and original budgets retained |
| B12 | Resources, obsolete bridges and current documentation; follows affected capability rows | One production tree and parameter authority; protect history and in-flight writers |
| B13 | Integrator: final closure; after B01–B12 | One candidate, complete Repository/install/native and requirement/cost accounting; unfinished work stays OPEN |

The existing ownership inventory below describes implemented boundaries, not another task
status table or a promise to preserve each historical workflow as a permanent package.

| 当前对象／职责 | 规范所有者与活动消费者 | 本阶段退出条件 |
|---|---|---|
| `StudyDefinition`／示例展开 | `examples`；包内例子、教程和安装测试 | 数据视图与副作用分离，旧总控入口退出 |
| `ResolvedComponent`／provider 分派 | `components.model`／`components.catalog`；RF、OA、TOF及独立器件测试 | 完整设计与接口同源，无纯模型到provider的反向依赖 |
| `Assembly`／装配／端口 | `assembly.model`与具名factory；完整／局部装配和集成测试 | 父设计、位姿和scope保持，旧总控装配入口退出 |
| 出生源与释放实现 | `ion_release`；源、传播及母群测试 | ID／权重／clock／随机序列不变，无后端反向依赖 |
| SIMION纯编译与原生操作 | `backends.simion`具名入口；当前P3链和后续独立器件 | 编译与副作用分层，唯一执行owner不变 |
| 既有COMSOL操作 | `backends.comsol`具名入口；真实项目工作流与原生证据 | 只迁移实际能力，不以脚本或假模型冒充完成 |
| STEP导出／冷读 | `exporters`；CAD和独立几何检查 | 与后端并列消费完整Assembly，无默认GUI |
| 结果读取／分析／比较 | `results`组合中立I/O与纯`analysis`；离线消费者 | 无隐藏重算／owner，缺失和篡改失败关闭 |
| Independent OA model/field/tracking | Installed SIMION model, field and shared tracking owners; explicit drive, source/clock and original protected family | Source and ordinary-install software slices delivered; actual OA native field/Fly and coupled-field qualification stay OPEN. Detailed evidence belongs to the OA project state. |
| OA accelerator-only theory and closed-focus source | `components.orthogonal_accelerator.three_zone_ideal_theory` and `backends.simion.oa_focus_source`; actual contracts, CLI and frozen consumers | Old bodies retired with scientific definitions unchanged; current v2 authority refresh preserves historical v1 bytes/refusal. The closed-focus plan, recorded analysis and protocol-2 FastAdjust decisions are installed with explicit mesh/profile authority and frozen consumers. Remaining native orchestration and native acceptance stay OPEN. |
| Paired RF source and sampled response | `ion_release.paired_mass_scan` and `analysis.mass_response`; actual RF preparation/evaluation and three frozen PS consumers | Both old bodies retired, explicit mass/input/criteria preserved; ordinary source epochs and main scoped checks delivered. Remaining root RF workflows and final composed-source acceptance remain OPEN. |
| RF finite-SIMION metrics | `analysis.rf_transport_metrics`; all four actual finite-transport CLI modes and frozen consumers | The complete old assembler is retired, with original denominators, handoff counting and UNQUALIFIED limits unchanged. Scoped software and ordinary-wheel evidence delivered; remaining RF algorithms/orchestration and composed acceptance stay OPEN. |
| IP scientific source/input preparation and HS1 resources | `workflows.ion_processor.preparation`, `backends.simion.collision_hs1` and four installed `ip_*.lua` resources; IP, accelerator and MR consumers | Seven original validators and byte-identical native resources migrated. Explicit research files and supplied values must agree. Installed source/materialization checks do not imply an IOB, field, Fly or qualification. Root snapshot, field adoption, seed binding, analysis and native orchestration remain OPEN. |
| Native execution path projection/context | `execution.run_paths` and its selected installed/frozen PowerShell resource; actual native consumers | Root projection/context bodies retired; explicit execution roots, canonical identity, shared ledger and existing junction/writer guards retained. Repository DEV root discovery remains outside the package. No new native or general historical-path portability claim. |
| Named SFI preparation/pulse/field planning/downstream/runtime/collection/continuation | `workflows.single_reflection_flight`; canonical source/results/backend consumers, actual PS CLI and freezer selections | Root Python bodies retired; scoped consumers, missing-resource and cache/reuse checks delivered. Installed four/five-slot seed materialization no longer consumes legacy large PA inputs. Remaining PS orchestration, composed installation and native seed/reopen acceptance stay OPEN. |
| Withdrawn local frontend; retained initial-state CSV | Local exclusive preparation/runtime/policies/resources/tests await removal; `backends.simion.source.load_initial_state` remains where actual retained consumers require it | User withdrawal is not PASS. Check SFI/IP/shared consumers before removing mixed resources; historical inputs and results remain unchanged. |
| Manifest and retention policy | `io.manifest_records`, execution verification/retention and explicit native policy; actual Python/PS publishers and freezers | Root production facades retired after policy closure, including candidate failure/finalization paths. Existing writer, capacity and historical evidence protections remain. |
| MP-to-IP preparation | `workflows.multipole_ip.prepare` and `backends.simion.rf_observations`; active callers/frozen providers migrated, old Python bridge/schema retired | Ordinary-install preparation and real-owner software checks delivered; IP flight/native and remaining interface workflows stay OPEN |
| Dual-cone SIMION input preparation | `backends.simion.dual_cone_transport` and canonical source serializers; Program resource/callers migrated, old preparation/source/Program copies retired | Ordinary installation and explicit observation cadence delivered; actual seven-electrode field/ion-flight integration stays OPEN |
| 环境、恢复与原生查看 | `execution`／`applications`；运行owner与故障矩阵 | 一次部署、单一owner；历史action仅作数据语义读取 |
| 能力查询 | 各规范操作的校验与显式声明；调用和查询共用分派 | 不再以私有planner签名建立第二套合同 |

首个完整切片已交付`examples.load_example → components.resolve_component → assembly.assemble → backends.simion.compile_geometry`，
同步迁移测试、冻结选择、教程并删除被替代总控符号；公开factory保留设计／接口／源同源校验及canonical父布局拒绝。
最终Changed门禁16 PASS／32 NA，1937个父方法中1936成功、1项因未配置`OATOF_THREE_ZONE_T5_RECEIPT`明确跳过，
3141个子测试全部成功，公共墙钟2698.441秒；普通wheel／sdist／重建wheel安装验收5项通过。
这些是当前软件与纯科学证据，不是原生、数值或Formal资格；完整15分钟及owner性能目标仍未关闭。
独立OA两／三区provider、component3、多实例／局部scope和同源STEP冷读已接通；包内`oa_two_three_geometric_v1`
显式保存requirements／profile内容，项目profile加载适配不复制算法。定向51项回归及普通安装5项测试通过，
实际OA STEP含25个物理实体和5个显式理想面排除；这不是独立OA原生、GUI或Formal资格。
最终Changed门禁18 PASS／30 NA，1821个父测试成功、1项既定receipt缺失跳过，2626个子测试成功，
公共墙钟1886.016秒；历史schema 1／2保留原profile标签，新component3拒绝未消费标签。
该旧轮不覆盖后续修正：直接Assembly现已与工厂同等执行提供者同源校验，圆柱侧孔贯穿曲面内壁，
10 mm环厚负例及真实STEP离轴探针通过；方形字节投影保持，五项圆柱哈希按实际几何纠正更新。
纯RF多实例／局部scope现可由公共SIMION入口生成独立PA GEM，覆盖四／六／八极及显式科学组映射；
`component_domains`逐实例冻结网格，完整父设计保留。公共原生构建后继现已接通真实独立RF几何，
单器件无需虚构父装配，四／六／八极原生及普通安装冷重开范围见[RF项目状态](../projects/rf_multipole_ion_optics/docs/PROJECT.md#independent-rf-geometry-build)。
现有项目Refine／Fly仍在原工作流，其余SDK推广保持开放。此前编译切片的完整Changed门禁22 PASS／26 NA，2458个父测试成功、
2项明确skip（既定T5 receipt未配置及opt-in SIMION N1），3155个子测试成功，公共墙钟2065.079秒。
机器配置现由`execution.load_environment`唯一加载，直接返回显式ExecutionContext；旧`api.execution_context`
及全部活动调用已迁移，构造不探测工具或创建工作区，普通安装探针同步覆盖。
EI与Wehnelt现有合同解析／检查及后者几何派生已迁入各自安装包组件，项目Static和冻结运行器直接消费，
旧resolver退役；resolved JSON字节、电子质量／负电荷与build-only边界不变。普通安装探针实际重建两合同，
46项跨边界测试通过；未新增COMSOL、求解或轨迹资格。
双锥几何、GEM、真实COMSOL场校验／运行Lua和均匀400Pa对照编译已迁入安装包；31项项目测试与Static通过，
resolved/GEM/两类Lua字节保持。显式路径替代作者默认，普通安装13项边界与交付测试实际覆盖几何、GEM和均匀场；
prepare的冻结、源、SDS与Program仍属项目owner，未把准备或场编译称为碰撞轨迹能力。
MR既有候选科学、场binding、COMSOL同网格改压／导出与退役读取已按component/backend/execution职责实迁，
MATLAB与Lua资源进入普通发行，integration及冻结来源直接切换且无旧转发桥。普通wheel/sdist探针实际调用纯电压投影并读取原生资源；
完整Static为1785项（1773成功、12既定skip），3483条记录中3471成功、12 skip，未运行商业求解器或新增科学资格。
IP真实15电极中性CSG、轮廓、guide入口／E14孔面和GEM已分迁component与SIMION backend，四份旧实现退役；
185项定向及364项项目Static通过，几何字段和GEM字节不变，integration/MR消费者与冻结准备同步切换。
普通wheel/sdist树外实际生成15电极及GEM，13项边界／安装检查通过；本切片不授予IP源、Refine、Fly或接续资格。
截至`efd2e8ac`，以40a13e78→HEAD逐文件选择完成联合Changed：30 PASS／18 NA，5045个父测试成功、
14项明确skip，5876个子测试成功，公共墙钟3357.404秒；这是当前迁移范围的联合软件证据，不是全仓Repository或P4收口。
单反射OA-only静态COMSOL构建／采样及四份真实几何MATLAB闭包已迁入安装后端资源，paired运行器与依赖清单直接消费；
22项paired及路由定向通过，普通安装读取实际资源；未启动MATLAB/COMSOL或生成新MPH。
paired Python纯准备现已迁入COMSOL backend，旧workflow prepare退役；22项准备与22项执行回归通过，
四类输出新旧字节一致，普通wheel/sdist实际生成相同完整plan，仍不创建PA或求解。
paired SIMION静态采样器与脉冲回调Lua也已迁入安装SIMION backend，缓存、Program与dispatch直接消费；
旧manifest绑定位置仅保留只读复用，项目副本退役。两份资源原字节及SHA保持，未新增原生求解资格。
paired COMSOL主脚本、Cartesian释放读取与CPT步策略helper亦迁入安装COMSOL backend；
普通构建、Candidate冻结源码、同步、重追踪及MATLAB测试同步使用安装目录，三份MATLAB字节保持，未启动原生求解。
单反射飞行管、反射镜和检测器variant Lua的三份旧项目转发桥现已删除；smoke、冻结依赖、集成及真实Lua测试直接消费安装实现，
不再保留重复冻结条目或到期别名。
`api.open_artifact`纯转发别名现已退役，生产内部调用、测试及教程直接消费`results.open_artifact`；
manifest绑定、搬迁resolver、文件身份复核和失败关闭不变，其余仍有独立职责的staged入口未因此删除。
Read-only products now belong to `results`; exact records, incomplete-publication checks and existing
Windows closed-file identity share the neutral `io` owner. Execution keeps journal publication/replay,
writer locks and lifecycle control. Old execution reader/record/identity modules and active references
are removed; backend collection, mother/clock validation and scientific interpretation remain backend duties.
The original 102-parent reader/identity/publication/analysis/comparison/STEP/boundary matrix passed;
actual frozen consumers and new-path Changed routing bring focused coverage to 118 distinct parents.
Both ordinary installed-product probe rounds completed successfully with a fresh reader process that
rejects execution/repository imports. The outer standalone unittest summary was not retained, so a
complete current-source joint gate remains required rather than inferring its exit or wall time.
出生源request校验及`ReleaseRealization`已迁入`msplatform.ion_release`；只读轨迹分析公开入口迁入
`msplatform.backends.simion`，旧`api.sample_release`与`api.analyze`均退役，科学语义与安装实际调用保持。
`build_geometry`的实际stage/owner编排也已迁入SIMION backend，旧API入口删除；29项定向测试通过，
原生预算、发布与独立RF拒绝不变，未因此新增真实SIMION执行证据。
`prepare_model`的几何、驱动、时钟权威及owner编排也已迁入SIMION backend，旧API入口删除；
28项定向测试及5项真实wheel/sdist树外探针通过，未求解模型语义不变。
`solve_fields`的显式复用、预算和发布编排已迁入SIMION backend，旧API入口删除；27项定向测试
及真实安装探针通过，冷求场／复用仍属软件owner证据，未启动真实SIMION求解。
`track`的源／时钟／恢复规划和唯一owner编排已迁入SIMION backend，旧API入口删除；完整母群、原ID、
共同钟、状态重发射、完整单元复用与零handoff无原生调用语义不变，定向测试通过但未新增真实Fly证据。
STEP导出编排与独立冷读检查已迁入`msplatform.exporters`，旧`api.export_cad`／`api.inspect_cad`删除；
同源Assembly、身份复核、无默认GUI／求解及显式预算语义不变。
显式SIMION／SolidWorks模型查看已迁入`msplatform.applications`，旧`api.open_model`删除；唯一owner、
自有进程、原关闭与配置恢复保证不变，本切片仅做软件回归，不启动GUI。
停止后收尾已迁入`execution.resume_run`并要求显式传入原操作completion policy，旧API入口删除；
不再由execution反向导入后端猜测策略，原Result、容量、manifest和只读重复调用保证不变。
纯能力查询已迁入`msplatform.capabilities`，仍直接复用规范provider／compiler／planner；总控`api.py`及其
活动引用全部退役，普通安装负例明确拒绝旧模块。历史快照与reader不因当前源码入口删除而改写。
`common/contracts/artifact_cache_contract.py`单向桥已退役；结构校验、容量校准与候选冻结直接使用安装执行合同，
缓存角色和根映射不变，历史资产不迁移。
`common/simion/gem_primitives.py`旧桥已删除；RF/OA/MR及integration消费者、测试和Changed路由直接使用安装SIMION实现，
数值序列化与GEM字节不变，MR冻结来源记录实际安装位置。
`common/simion/native_completion.py`旧桥已退役；各项目、integration、公共PowerShell内嵌调用及当前冻结声明直接
使用安装解析器。Fly完成行、TRACE／stdout分类、批次receipt与失败关闭语义不变，历史运行证据不改写。
`common/contracts/recorded_file_removal.py`旧桥已退役；公共生命周期、项目运行器、PowerShell内嵌调用和当前
冷快照直接使用安装原子写／记录删除实现，共享globals、有限重试、保护清单与缺资源失败关闭不变。
`common/simion/cache_generation.py`旧桥已删除；缓存身份、快照物化、退役读取、MR消费者及测试patch直接
使用安装执行实现，CLI与哈希边界不变，候选闭包继续由规范包枚举提供该模块。
`common/simion/immutable_pa_parity.py`旧桥已删除，结构校验与测试直接消费安装实现；manifest／parity身份不变。
`common/simion/standalone_pa_response_set.py`旧桥已删除；OA／MR／integration、退役读取、CLI和测试patch直接
消费安装实现，sealed receipt、源保护及失败语义不变。
`common/simion/pa_family_cache.py`旧桥已删除；OA／MR／integration、公共生命周期、原生CLI和测试patch直接
消费安装实现。`common.simion.pa_family_cache`仍只作为资产owner身份，不改为源码导入路径。
`common/simion/batch_continuation.py`旧桥已删除；IP／RF／MR／OA及integration整批恢复直接使用`execution.recovery`，
完整单元复用、未完成整批重放、原ID／母群／时钟与失败证据不变。
`common/simion/resource_scheduler.py`旧桥已删除；各项目、integration、原生CLI和测试直接使用`execution.simion_dispatch`，
唯一调度器、失败停新、资源准入、drain与恢复语义不变。
`common/contracts/canonical_clock_authority.py`旧桥已删除；各准备／上游入口及测试直接使用安装时钟权威，
epoch、authority SHA、单位与basis失败关闭语义不变。
`common/contracts/artifact_naming.py`旧适配器已删除；各发布、运行器、CLI与测试直接使用安装命名合同，
run/archive/task ID、时间格式与manifest身份不变。
`common/contracts/frozen_inputs.py`旧适配器已删除；各运行器、源码枚举、冻结输入和当前测试直接使用`execution.inputs`，
原始字节、导入根、来源SHA和缺资源拒绝不变，历史快照不重写。
`common/contracts/run_capacity_lifecycle.py`旧适配器已删除；各生命周期CLI、封存、恢复和测试直接使用安装实现，
writer、容量、容量lease与manifest保护不变。锁内退休核验复用同一lease快照，owner保留原分类器回调。
Repository-specific misplaced-run recovery remains with `common.contracts.legacy_owner_disposition`,
where its full repository manifest verifier is available; installed lifecycle code does not import that owner.
The duplicate repository solver-review retirement implementation is retired. The existing PowerShell
resource wrapper and repository reconciliation call the canonical execution owner; receipts, leases,
writer proofs and retirement identities remain unchanged. Its original common and IP/MR regression
scope passed 283 of 284 parent methods, with one existing retired-historical-PA skip. Actual cold
retirement imports and the nine-path Changed routing check passed separately after consumer migration.
PA cache、continuation、dispatch、frozen-input与artifact-naming的包级导入、冻结source、CLI及fixture残留同步迁移；
OA acceptance snapshots bind the actual package initializers and neutral identity implementation;
cold-reader checks reject missing frozen code even with a competing installed package.
RF隔离分析阻止editable安装finder接管冻结来源。
The stdlib scheduler no longer loads JSON Schema engines during package initialization; actual schema
validation still requires them. This closes a reproduced startup mechanism, not the unknown historical pipe cause.
The 2026-11-09 takeover started at `d8bcfc36` with 76 modified tracked paths, no untracked files,
and no active native solver. The original diff was preserved before changes. Four common-contract shards
passed against `7cb8007e` plus the reviewed migration, including ordinary wheel/sdist installation;
the joint Changed run remained FAIL (14 PASS, 5 FAIL, 13 BLOCKED, 20 NA; 1863.396 seconds public wall,
eight workers). Frozen import bootstrap order and the active three-zone CLI authority remain separate
corrections; blocked project stages are not accepted by the common result. The canonical retirement reader
now receives its explicit classifier, including the exact frozen IOB seed context; role-less large evidence,
actual lifecycle resealing, tamper refusal and lock-held verification retain their original guarantees.
Saved deployment/profile loading now reads one explicit machine document, selects engineering overrides
through the existing stage-policy validator and freezes their provenance in the existing run owner. The
24 platform tests and real wheel/sdist outside-tree probe passed (143.242 seconds for installation).
Results reading now has its own read-only domain; remaining result-interface consolidation,
native rollout and the original performance targets remain OPEN.
No new COMSOL/SIMION, GUI or Formal qualification is claimed by this takeover. MATLAB R2025b rejected
the migrated helper directory named `resources` before executing tests. The eleven byte-identical sources
now use the canonical `matlab` directory, with selectors, wheel metadata, callers, frozen declarations
and original tests migrated together. Three helper classes passed all 38 MATLAB cases with exact function
origins; the original path/folder and public GATE lease were restored. Complete installed acceptance
then passed all five tests (142.756 seconds), including ordinary wheel and sdist-rebuilt-wheel consumers
using the installed MATLAB directory. These are helper/software and delivery checks, not native model solves.
科学事件CSV writer已从`common/simion`迁入安装SIMION backend；IP、OA、MR、联合飞行及测试直接冻结新位置，
原1688字节及SHA保持，运行内相对别名、列、精度、flush与错误拒绝语义不变。
公共`voltage_waveforms.lua`与`rf_drive.lua`旧转发器现已删除，真实Lua消费者、RF路由及原冻结消费者直接绑定安装实现；
规范资源字节与科学公式不变，旧路径拒绝负例继续保留。
integration中的`single_flight_frontend_hook.lua`与`single_flight_pulse_hook.lua`旧转发器亦已删除；
真实Lua回调、原冻结消费者及普通安装直接读取安装实现，原回调顺序和字节身份不变。
单反射前／下游场审计旧Lua转发器亦已删除；真实审计测试直接读取安装实现，原冻结条目退出且不新增重复声明。
单反射`build_iob`实际路径投影迁入安装SIMION backend，`build_iob_core`旧桥退役；
当前构建直接消费安装路径及core helper，历史continuation仍按父run原冻结资源读取，不重写旧资产。
`common/paths/native_run_path.lua`旧桥现已删除，真实执行别名测试与全部原冻结消费者直接使用`execution.resources`规范实现；
安装包、进程内路径投影及历史资产语义不变。
公共Dirichlet构建、standalone导出及detached导出三份旧Lua转发器已删除；真实参数合同、候选发布和冻结依赖直接消费既有安装实现。
`api.compare_trajectories`旧别名现已退役；调用方先分别打开显式manifest引用，再直接调用SIMION比较owner。
母群、场、模型、共同钟、选择／方法输入与科学资格语义不变。
实际占据率脉冲选择已迁入`msplatform.analysis.pulse_selection`，local与单反射消费者直接使用规范实现；
旧`integrations/runtime/pulse_selection.py`已退役，候选排序、生命周期、归一化几何和无支持候选负结果保持。
普通PA读取、分块校验及仿射组合已迁入安装SIMION backend，MR场provider及IP/Prism消费者直接调用；
旧项目实现退役，普通格式、sidecar、源保护与失败语义不变，不新增原生求场或轨迹资格。
母群census旧桥已删除，MR实测源／分析、local与RF冻结消费者直接使用安装实现；完整母群、权重和未知终态语义不变。
峰形、刚体变换与中立粒子状态旧桥均已退役；全部活动消费者、测试、冻结来源与门禁路由直接使用canonical实现，
不改算法、科学协议字符串、原ID／母群、坐标／旋转算序或历史资产。
纵向拟合已迁入`msplatform.analysis.longitudinal_fit`；接受域消费者、publisher冻结来源和门禁路由直接绑定新实现，旧公共文件退役。
粒子物理旧桥已删除，各项目与integration直接消费安装实现；常量、公式、单位、ID／母群及科学资格不变。
机器合同旧桥已退役；JSON/schema与ContractError直接使用安装实现，真实仓库根统一归`common.paths.repository_root`，不迁入科学核心。
保存模型读取器按manifest唯一绑定位置识别历史／新资源，23项保存复用与真实历史脉冲负例通过，未改写历史SHA。
Formal静态资源枚举补入实际闭合接口生成器；其后稳定资产验收仍报告SIMION目录55文件／manifest54，
不删文件或改计数，该项不作通过。
IP bare-guide projection and shared CSG sections remain canonical component behavior;
SIMION IP rendering remains in its backend. Dedicated cooled design and execution were
withdrawn in V8.5; the earlier seven-electrode migration evidence is historical only.
IP真实上游状态准入及schema已迁SIMION backend，保留原ID／母群／权重／出生到达钟与零出口／科学负结果；
22项定向和IP Static通过，25项integration／边界与wheel/sdist验收通过。
IP坐标映射与component_exit现已分迁component／SIMION backend，continuation保护归execution；155项定向、
364项Static及84项integration回归通过。保留原始停止、母群／权重和唯一时钟，未重新Fly。
IP原生仪器时序及15电极Lua驱动已分迁component／SIMION backend，项目、MR及冻结integration直接消费新实现与新资源；
旧函数和Lua文件退役且无转发。默认时序仍为7500／7500.135135135135微秒，Lua保持2061字节及原SHA-256；
普通wheel/sdist两轮树外实际读取、比较并执行其余安装探针通过，未启动SIMION或新增飞行资格。
其后首轮全迁移联合Changed的integration第4分片仍有1项schema预期失败，原轮不追记PASS；
已按实际core及backend schema闭包补齐预期，并显式固定该Unicode JSON测试的PowerShell UTF-8输出，定向复验通过。
截至`3f2d3e14`及paired Lua迁移，40a13e78→HEAD联合Changed后继验收30 PASS／18 NA，
5045个父测试成功、14项既定skip、5879个子测试成功，公共墙钟3320.701秒，进程零退出；
该范围不冒充完整Repository或原15分钟／owner预算验收。
同机Python 3.11／PowerShell 7.6.9、公共受管单并发、同一双模块范围的3轮前后对照中，
原始场冷建／复用方法中位数179.578秒，受控主机快照夹具后127.760秒（−51.818秒）；
公共墙钟357.576→297.150秒。批失败恢复60.337→59.745秒，成功恢复26.085→27.190秒，后者变慢而非提速。
夹具保留真实进程、scheduler、SQLite acquire/inherit/release、14个原生涯件操作及全部原断言；
只替代重复CIM压力采样，不改生产等待、科学/缓存/恢复合同，也不是生产求解性能结论。真实CIM故障回归仍由其他既有测试承担。
其后批失败用例的三轮同机顺序实测为18.354／17.816／17.722秒，中位数较59.745秒减少41.929秒；
仅输入计划观察窗口由45改为1秒，真实OS进程、独立SIMION准入、replan、失败停新、guard与释放断言不变，
生产默认值及replan输出的45秒策略不变。首轮夹具误要求replan输出也改为1秒而失败，该FAIL保留，
修正测试期望后才形成上述PASS轮；此项不是原生SIMION求解性能证据。
That one-second controlled-window measurement does not qualify the original default-duration failure
case. The original method identity and actual 45-second observation were restored without adding a
duplicate test or changing production budgets. The public GATE run passed in 67.781 seconds: the healthy
software payload waited 45.515 seconds for a validated replan, the failing payload exited 7, pending work
never started, immutable protection held, and the independent SIMION and GATE leases released. This
restores the original OS failure-window combination; the complete performance targets remain OPEN.
Earlier takeover acceptance at `70cddb63` plus test-only field timing completed the full Repository
scope with eight workers: 46 PASS, 4 FAIL, 12 NOT_APPLICABLE; 6,833 distinct parent tests
(6,808 success, 21 skip, one failure, three errors) and 7,774 successful subtests. Public wall was
2,807.993174 seconds. All stages drained; six native Dirichlet tests actually succeeded. The four
failures were the retired MR cache-path expectation, Candidate journal-constant reference, RF frozen
fixture's deleted physics bridge and its full-inventory mutation timeout. The exact-HEAD remote
Changed run separately ended with 20 PASS, 2 FAIL and 11 BLOCKED, also exposing the normal-interpreter
dependency-path assumption in the publisher probe. Both failed runs remain failed evidence.
The original default-duration failure method passed in 69.000129 seconds in this Repository run.
Field-owner timing passed in 198.273739 seconds: model 1.667571, cold 150.273922 and reuse 44.865038;
the eight cold and eight reuse process boundaries summed to 145.771629 and 41.334603 seconds.
Cold frontend/downstream calls dominated at 124.970290 seconds. These boundaries include nested
inert OS operations and cache work; their residuals do not establish publication, CPU, lock or CIM
causes. Child usage files were temporary, so a finer split was not retained. No speedup ratio or
15-minute/owner-budget closure follows from these measurements.
The earlier RF diagnostic-decoding failure remains historical failed evidence; all 15 COMSOL
analysis-recovery software tests succeeded in the current Repository run. No new COMSOL solve was run.
其余器件／后端、结果、部署、两个性能热点和旧桥退出继续在同一Goal内关闭。
新电极组字段为`electrode_group_id`，component3／plan5／binding2与request10明确升版，旧格式原义保持；
RF/OA真实消费者、必要状态／母群、三区理论量纲／坐标和新峰结果metadata已迁移。
真实三区N100的映射A/B与显式回放、有限GUI及18次独立非粒子场查询已有相称证据；
其具体范围、原N100八桶仍INCONCLUSIVE及NOT_QUALIFIED等限制只归
[集成状态](../integrations/docs/INTEGRATION.md#当前边界)，不授予全空间精度、收敛或Formal资格。

固定源码`b7e30447`完整Repository验收两端均50 PASS／12 NOT_APPLICABLE：本机8路公开2029.189秒，
远端4路公开3422.007秒。两端6473个父方法定位键和源文件SHA一致，本机6452成功／21跳过，
远端6251成功／222跳过；子测试本机7012成功，远端6745成功／9跳过。
远端Dirichlet六项实际skip，本机同源六项实际成功，阶段PASS不替代原生执行事实。
完整差异、安装／冻结和源码身份见P2验收记录；文档后继不另产生代码验收。
R0按有界UNKNOWN裁决闭合取证、归属清理、失败保全与测试身份子包，
不宣称已查明全部历史超时根因或根治生产求解器；原FAIL与缺证据UNKNOWN保持。
多轮失败、后继修复和原计数可从
[B7固定路线图](https://github.com/Bibibabibobi96/mass_spectrometry/blob/b7e3044710e003af8183d897d9fd0753e1e151ff/docs/ROADMAP.md#科学核心与平台边界迁移)
追溯，不继续在当前视图堆积重试时间线。原15分钟反馈目标仍未达，P4责任不下调；
不同主机、Python和可选依赖的8路／4路结果不作为受控加速比。
改造按完整需求和长期职责选择保留、提取、替换或重写；不得用最小diff、旧目录或旧规范缩减目标。
稳定所有权与依赖规则归[仓库架构](REPOSITORY_ARCHITECTURE.md)，本节只维护需求、责任阶段和出口。
P1–P5为平台改造批次，与下述组装M0–M4及项目科学资格分别管理。

| 批次 | 责任与出口 |
|---|---|
| P1 | 公共核心：冻结目标边界，实迁源、布局、峰形及必要科学基础；RF/OA、布局适配、MR直接消费规范实现，取得真实提供者布局、wheel/sdist、依赖/资源/冻结/路径证据，退出被替代算法。 |
| P2 | 器件提供项目与integration：同源几何、驱动和后端编译，真实不同提供者/结构、多实例及位姿；本批公共命名、OA角色与显式版本闭合；必要状态、母群和方法元数据；相称原生与工程证据。 |
| P3 | integration与运行机制所有者：分段接续和联合连续两种飞行、共同钟/母群、可解释复用及分级故障恢复；交付选定真实链的可安装分阶段公共API、geometry-only、同一完整Assembly的独立STEP与带驱动PreparedModel出口及独立教程验收；同场同源比较，不以拼接冒充连续积分。 |
| P4 | 各活动消费者及公共验证所有者：全域推广、有限兼容桥退出、导航/控制面及命名一致性收敛；发行身份有证据裁决，同机同范围完成原反馈时间目标验收。 |
| P5 | 实际新增需求所属项目与integration：真实器件/源/后端压力测试，逐项回查全部需求；未实现、未验证或环境阻断不得作为满足。 |

以下需求目前均保持开放；P1/P2只关闭各自已证切片，不能关闭后续阶段责任。接口支持、原生功能、
数值/物理与GUI/CAD资格分别报告；后续重排不得删项或无主延期。

| ID／需求 | 首次落实 → 整体关闭 | 责任与必需证据 |
|---|---|---|
| R01 职责独立和可组合 | P1 → P1/P4 | 公共核心：无项目/owner反向依赖、安装外调用、真实消费者。 |
| R02 同源几何与离散化 | P1/P2 → P2/P4 | 提供项目/integration：参数扰动、真实提供者、多实例与几何投影。 |
| R03 完整和局部装配 | P1 → P2/P4 | 装配核心/integration：完整父对象、显式位姿及切边、真实接口。 |
| R04 独立源与粒子群 | P1 → P1/P4 | 源核心/消费者：策略、母群前缀、ID/物种/时间、RF/OA完整输出。 |
| R05 状态交接与时钟 | P1/P3 → P3 | 合同/integration：出生、快照、穿面、checkpoint区分和不同dt共同钟。 |
| R06 两种飞行 | P1/P3 → P3/P4 | integration/后端：同一冻结设计与源的分段和联合原生链。 |
| R07 场、驱动与耦合 | P1/P2 → P2/P5 | 提供项目/后端：驱动与数值分开、自洽反馈及权重语义。 |
| R08 后端能力边界 | P1/P2 → P2/P5 | 后端适配：科学请求、原生编译/运行/读取、版本及能力限制。 |
| R09 观测与重分析 | P1 → P1/P3 | 分析核心/项目：独立oracle、真实MR、样本/分母/资格由项目拥有。 |
| R10 研究灵活性 | P1/P2 → P2/P4 | 请求编译器/项目：合法候选可进入流程，技术/物理/资格判断分开。 |
| R11 运行与恢复 | P1/P3 → P3/P4 | 运行owner：原始/次级异常、writer、资源、发布和分级恢复证据。 |
| R12 Windows路径运输 | P1 → P1/P3 | 路径/执行边界：长、Unicode、空格、cwd、argv和别名清理。 |
| R13 缓存及失效 | P1/P3 → P3/P4 | 冻结/缓存owner：分维身份、变更矩阵、篡改/缺失拒绝及自洽例外。 |
| R14 科学与工程证据 | P1 → P1–P5 | 各资格所有者：如实区分软件、原生、数值、实验、GUI/CAD。 |
| R15 API和可安装交付 | P1 → P1/P3/P4/P5 | 公共发行：P1科学核；P3首次真实安装执行、逐资源交付、STEP／PreparedModel及各出口跨进程重开；P4全域推广；P5: this user validates a fresh environment and actual new needs; unfinished P4 work does not transfer. |
| R16 文档与规范适应 | P1 → P1/P4 | 各唯一权威：同步规范/检查器/代码/导航，冻结历史不追改。 |
| R17 覆盖与反馈时间 | P1 → P4 | 验证owner：有效保证不减、固定环境范围计时，原预算不下调。 |
| R18 真实扩展压力 | P2 → P2/P5 | 新需求提供者/适配：真实替换、局部修改及所需数值/功能证据。 |
| R19 迁移与退役 | P1 → P1/P4 | 各迁移所有者：唯一活动算法、消费者直接切换、具名桥及退出条件。 |
| R20 工具和Agent成本 | P1 → P1/P4 | 开发工具所有者：工具与科学环境分开、实际定位/读取/返工成本及数据安全。 |

P1已将科学实现迁至`src/msplatform/`规范核心根，保持单主发行单元；该名称没有本机已安装冲突，
不表示已对外注册或发布。选择理由是安装与源码搜索路径可分离、科学API所有权明确，优于继续
把有限发行文件混在通用`common`运行树。规范实现不反向包装旧树；旧入口仅单向转接至新实现，
具名消费者与不晚于P4的退出条件见[公共迁移说明](../common/README.md)。当前API、资源与冻结映射
已落地；P1实际关闭切片与完整软件验收见[P1迁移验收记录](history/20261103__phase01-scientific-core-migration.md)，
不代替上表各需求的整体关闭证据。

## 统一组装迁移计划

2026-10-22批准固定`integrations/`直属入口与声明式配方路线，取消无独立职责的`instrument_assembly/`源码层。规范正文见
[统一组装目标](COMPONENT_CONNECTION_ARCHITECTURE.md#统一组装目标)，产物规则见
[生命周期](LIFECYCLE.md#统一组装产物归属)。用户随后批准代码迁移；M1实施状态及其当前限制归
[统一集成状态](../integrations/docs/INTEGRATION.md)。各阶段须按以下证据关闭，不能把布局编译当作物理贯通。

总goal是从当前工作树及真实运行证据出发，完成跨项目装配和既有物理工作流向根`integrations/`的完整迁移，
交付单一权威、低复杂度、稳定、可复现且容易排错的体系；以未来演进时不静默改变实验语义为稳定性判据。
采用“配方显式声明器件、实验显式选配方、
默认执行所选配方全部实例、局部范围显式包含”的目标；验收以每次冻结的实际输入为准，
不以随项目演进变化的“完整”称呼作为执行、复用或资格依据。以下是持续推进中的完成条件，不代表现已完成。

1. 完成提供者接口与统一装配消费，组件清单、直接位姿和连接只有一个权威，不在集成层重画器件。
   支持同一提供项目的多实例分别绑定不同尺寸、变体和工作点；以Q1／q2／Q3三实例检验身份隔离，
   允许复用局部电极名而不混用电压／RF驱动、位姿和场。区分布局能力、逐实例驱动能力及真实仪器验证，
   不将三实例布局通过表述为三重四极杆已经可运行，也不为每个实例复制项目或runner。
2. 落实显式选配方、默认其全部实例、局部范围显式派生的运行语义；用拓扑扩展、重复实例及重排验收，
   确认新配方切换不改变历史run的范围含义，不要求实验重复维护完整清单。覆盖旧小装配作为自身完整配方、
   同一实例集合在新父配方下作为局部范围的差别；不按full标签授予物理资格。
   核验实例重排不改变绑定，同一项目的多个实例不混用源或电极；新增拓扑必须主动切换配方，
   不能通过修改被引用配方的器件清单让既有实验自动扩容。默认范围只从所选配方派生一次。
3. 贯通独立于装配范围的源、粒子身份、母群与单时钟；验证OA内源跨完整／局部范围的正确投影，
   区分完整几何与真实上游经历，不裁剪、重采样或抹去上游损失来获得成功。
4. 验收接口／frame／驱动变更、局部边界、场复用失效、数值分域与容量不足、冻结执行及中断后的正常处理；
   覆盖源实例删除、同项目多实例替换、未知组件拒绝、无效局部声明及物理范围与数值分域分离。
   区分历史输入可追溯与当前工具可执行；不兼容时给出具体原因，不静默补件、降精度、改变物理或切换
   当前输入。验收只补真实合同边界，不预建未来插件与兼容系统，也不以保存旧运行要求永久兼容旧执行分支。
   同时覆盖新增部件引起的物理耦合变化、分段失败不发布完整成功，以及跨年代结果不能仅凭full标签比较；
   默认全部实例带来的成本由显式局部研究、数值分域与预算处理，不能自动删部件或改变源。
   核验解析、容量准入、资产选择和执行使用同一冻结计划，活动输入在准备期间变化不影响该run；
   覆盖源实例存在但必要观测器件、驱动或模型接受条件缺失的明确拒绝，不把源绑定有效当作研究可执行。
5. 完成多极杆→OA→单反射TOF、OA→MR、IP→MR及真实多极杆→IP→MR，
   并完成所需分段与跨求解器验证；保留负结果，明确实现、数值与物理原因，不以替代源或布局成功关闭链路。
6. 切换真实调用者后删除被替代的入口、实现、配置、注册和无价值测试；沿用公共冻结、缓存和生命周期机制，
   减少重复参数、哈希、复制与求场，报告真实代码量和复杂度变化。
7. 保护在途仿真、必要资产和历史证据，完成联合门禁、文档及相称提交；逐项区分已实现、已验证和待完成，
   不以增加防御层、配置副本或测试数量作为稳定性完成条件。区分功能贯通、数值验证、GUI/CAD
   与正式资格。最后按实际消费者复查流程是否最简、容易排错，检查重复或不必要的物化、哈希、验证、
   兼容、复制及其他操作，确认被替代的冗余代码已完全退役；复查无误且上述条件逐项满足后才关闭总goal。
   不用尚未完成的迁移宣称架构或物理验收通过。

运行语义和演进规则的唯一正文见[范围与粒子源标准](COMPONENT_CONNECTION_ARCHITECTURE.md#完整装配粒子源与局部求解范围)
及[失效边界](COMPONENT_CONNECTION_ARCHITECTURE.md#演进时的稳定性与失效边界)。本计划登记实施和验收范围，不另建规范副本。

| 阶段 | 依赖与工作范围 | 关闭条件 |
|---|---|---|
| M0 规范冻结 | 明确目录、配方、工作流、组件接口、产物与参与方任务 | 唯一权威可检索，各侧登记任务；不宣称代码迁移 |
| M1 接口与装配合同 | 盘点OA、IP及仪器真实消费者；扩展现有port／composition合同及薄适配 | 多实例、电极、驱动、坐标／时钟和连接模式有无求解器回归；不复制器件拓扑 |
| M2 首条消费迁移 | M1后先迁现有局部多极杆→OA；cooled按V8.5用户决定完整退役 | 冻结输入下几何、驱动、母群、时钟、默认回放及相称真实行为对照成立，当前在途依赖不受影响 |
| M3 第二消费者与整机覆盖 | 用IP→MR验证同一组装机制，并逐项覆盖OA→MR及原多极杆→单反射整机流程 | 保留各链物理模式和限制；共享机制不含器件专属决策，差异由配方／提供者表达 |
| M4 入口与身份切换 | 对已完成验证且依赖允许切换的workflow分别实施 | 调用、注册、门禁、产物解析和文档同步切换；无在途依赖后退出旧生产副本，历史身份保持 |

M2/M3按workflow闭合后可分别进入M4，不等待无关物理优化。当前入口、完成范围和剩余物理边界统一见
[集成状态](../integrations/docs/INTEGRATION.md)；多极杆→IP已具有声明范围内的分段状态交接，连续边缘场及
其他工况不自动获得资格。公共机制的提升仍须满足实际复用条件，不将MR专属几何调整、匹配或工作点闭合整体搬入common。

参与方任务入口：[OA](../projects/orthogonal_accelerator/docs/PROJECT.md#统一组装迁移任务)、
[IP](../projects/dual_pressure_rectilinear_ion_processor/docs/PROJECT.md#统一组装迁移任务)、
[MR](../projects/parallel_mirror_dual_stripe_mr_tof/docs/PROJECT.md#统一组装迁移任务)、
[单反射TOF](../projects/single_reflection_oa_tof_mass_analyzer/docs/PROJECT.md#统一组装迁移任务)、
[直属集成](../integrations/docs/INTEGRATION.md)。
真实多极杆提供方由[多极杆项目](../projects/rf_multipole_ion_optics/README.md)按四／六／八极结构变体
分别发布接口和验证范围。本页维护阶段依赖，局部事实与
关闭证据只回写上述状态页，不在路线图复制运行结果。

## 设计族与未来项目

| 设计族 | 边界与后续方向 |
|---|---|
| TOF 质量分析器 | 分析器与加速器项目拥有各自物理设计、接口和独立证据；跨组件装配与联合执行归integration。不同反射拓扑按独立设计线评估；同一拓扑的尺寸和电压变化进入候选。 |
| RF 多极杆 | [统一设计项目](../projects/rf_multipole_ion_optics/README.md)维护四／六／八极结构变体、领域理论与实现；各变体的配置、能力和证据独立。后续功能按实际设计与接口选择mode、workflow或新项目，不按杆数自动增加项目。 |
| 离子源与电子枪 | 先完成参数链与独立部件验收，再发布可追溯接口分布；工作点变化不自动新建项目。 |
| 接口与集成 | 组合坐标、电位、孔径、压力、相空间、时钟和机械接口；独立功能器件与连接编排分别归属项目和 integration。 |
| 气体与真空 | 从实际部件的气体条件与边界出发，按需求补充压力、流动、分子流及耦合能力；区分给定背景、求解气体输运与联立耦合，分别验证。 |

活动项目由[项目注册表](../config/project_registry.json)发现，不在本页维护第二份项目身份或资格清单。
上述方向不要求预建项目；参考书与文献提供知识来源，不能代替实际需求、独立责任和验证条件。

## 需求与项目注册

目标是把自然语言目标变成可审阅而非直接执行的结构化规格。

主要能力：

- 建立项目注册信息，显式记录`project_id`、`family_id`、结构类型、主要功能、正式能力和适用接口；
- 定义需求字段、单位、硬约束、优化目标、优先级、容差、证据等级和未决问题；
- 将自然语言解析结果冻结为候选规格，要求人工或规则门禁批准后才能创建求解run；
- 区分目标示例、已批准目标、当前baseline和正式验收结果。

完成门禁：至少单次反射oa-TOF和当前RF四极杆离子光学能够从同一规格框架产生可追溯run config，
且含糊或冲突需求
会在求解前被拒绝。

## OA-TOF性能驱动闭环

`single_reflection_oa_tof_mass_analyzer`作为首个端到端性能设计示范。输入可以是质量、电荷态、
目标分辨率和尺寸/电压限制，也可以是
部分冻结几何；系统自动建立候选、运行多保真度模拟并依据诊断调整参数。

这是有明确性能目标时的建设方向，不是所有部件或组装任务的默认要求；功能贯通不等待该优化闭环完成。

设计空间逐步覆盖：加速区、漂移区、反射器和检测器位置；环电极数量、厚度、宽度、间距和电压；
孔径、端盖、屏蔽壳和开口；局部场分量、边缘场、飞行时间聚焦、传输率和落点分布。轴对称圆形
加速器候选属于这一阶段的具体结构分支。

类似“500 Da、单电荷、分辨率30000”只在批准后成为目标规格；优化器必须同时报告传输、鲁棒性、
数值收敛和制造约束，不能只优化单一R值。

完成门禁：从批准规格到正式COMSOL、SIMION、CAD、结果和manifest的闭环至少完成一次；未达标时
能够输出可复验的瓶颈与不可行性证据。

## 多极杆功能设计

在统一多极杆设计内按明确结构变体和功能逐步扩展，领域实现共享机制但不共享未经验证的资格。
各设计配置分别从解析参考、圆杆场、有限三维功能和接口合同进入Candidate／Formal门禁；
任何阶段的当前完成状态只查项目注册信息和相应变体状态。独立功能或接口确需另行演进时再评估新项目。

建议顺序：

1. 六极杆、八极杆离子导引：建立参数化接口、外部注入/输出、相空间合同、下游匹配和Candidate门禁；
2. 四极杆质量过滤：依次建立L0/L1参考、双求解器功能扫描、稠密质量扫描、峰位、分辨率、网格/数值
   一致性和入口/出口边缘敏感度资格；
3. 四极杆或六极杆碰撞单元：传输、冷却、碎裂、能量和碰撞统计；
4. 部件专属理想场、几何和分析留在多极杆项目；不属于该设计的机制按[共享职责](REPOSITORY_ARCHITECTURE.md#跨项目知识提升条件)提升到公共层。

完成门禁：功能要求能够选择合适的结构变体、设计配置和工作流，完成至少两种不同功能或杆数的独立正式
设计，并证明共享实现没有把某一变体的假设或资格推广到其他变体。

## 离子源与电子枪自动化

为开孔长管电子轰击离子源和横置螺旋灯丝Wehnelt电子枪建立
`baseline → resolved → solver/CAD`链，定义发射、束流、能量、
空间电荷、热、磁场、离化效率和机械约束等适用指标。先完成独立部件验证，再允许它们向下游输出
冻结接口状态。

完成门禁：至少一个源项目能从批准规格生成正式资产和接口分布；另一项目实际复用相同规格或验证
基础设施后，才提升跨项目源设计能力。

## 部件集成与仪器级优化

本主线从已有部件持续推进，与各部件能力建设相互验证。
建立所需部件之间的接口合同与组合门禁。两端独立相空间可以送入同一冻结下游模型；
不要求随机碰撞后的逐粒子轨迹重合，但必须验证接口接受率和最终功能。

在明确授权的目标下，优化可从单部件扩展为系统目标：总体尺寸、电压和压力预算，传输、分辨率、灵敏度、鲁棒性、制造与计算
成本。部件不能为了改善局部指标而破坏上下游接口。

完成门禁：至少两类正式部件在冻结接口下组成可复验系统，系统级正式结果能够追溯到全部来源项目、
版本、变换和运行manifest。

跨项目网格建设与计算量控制统一遵循[`VALIDATION_METHODS.md`](science/VALIDATION_METHODS.md#网格建设与计算量控制)。
公共网格合同、适配器和 manifest 扩展须由实际复用与验证驱动；各器件先区分屏蔽结构与功能电极，
再按自身电气语义接入连接合同，不能把某一连接的电位规则推广到所有器件。

## 受控自然语言自治

在前述规格、项目注册、优化、验证和正式化能力均稳定后，形成面向使用者的自然语言工程入口。系统
能够提出必要澄清、解释设计选择、管理长时间运行、根据失败证据调整候选，并在达到门禁后准备正式
发布；涉及目标变更、不可逆资产晋升和重大范围扩张时仍需明确批准。

- 未来建立统一求解器包装器（例如`tools/run_solver.py`），由一个版本化JSON执行合同和统一CLI分派到
  COMSOL、SIMION及以后实际引入的GPT等适配器；调用方只提交项目、solver、config、粒子数和run id。
  适配器保留各软件专用MATLAB/Lua/输入文件与验证逻辑，但统一产生`inputs/`、`logs/`、可选`raw/`、
  `results/`以及根`run_config.json/summary.json/run_manifest.json`。这是未来平台任务，不是当前已具备
  的单一运行入口；在各项目包装器和输出语义稳定前不提前抽象实现。

完成门禁：多个不同部件族能够从自然语言需求走完同一受控生命周期；重复运行可复现，失败不会被
隐藏，正式资产不会绕过参数、GUI、CAD和跨求解器门禁。

## 暂不提前固化的内容

- 不把未实施的目标架构写成当前能力，也不为它预建空实现。经用户批准、明确标记状态、适用边界和
  迁移门禁的跨项目决策文档可以先冻结职责与依赖方向；实现后的稳定接口再由邻近代码和README记录。
- 不为未来项目预建空目录、空formal或无验证的通用代码。
- 不给阶段承诺日期；具体优先级和资源变化时更新本路线图，各项目当期工作只更新其`PROJECT.md`。
- 不从设计族名称、配方布局或愿景推定任何未验证功能；已有能力以当前项目／集成状态及其证据为准。
