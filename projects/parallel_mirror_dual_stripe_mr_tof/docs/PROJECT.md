# 开放路径平行镜双条带 MR-TOF 项目状态

本页维护MR分析器的当前设计、资格、有效证据和开放动作。操作由[项目入口](../README.md)导航，
推导见[理论索引](theory/index.md)。完整接口迁移、已完成研究、实现修复及原始证据链接冻结在
[文档收口里程碑](history/20261026__assembly-documentation-consolidation.md)，历史语气不作为当前执行指令。

项目门禁由[verify_project.ps1](../verify_project.ps1)进入，逐测试输出耗时并保留失败传播；
不同门禁等级和实际选择范围仍以该入口为准，不把软件门禁通过当作求解或科学资格。
The remaining P4 study/provider callers and their frozen tests use the canonical installed lifecycle
and dispatch owners. The affected RF/MR software modules ran 134 tests successfully with three skips;
the original IP/prism-distance module separately passed all 30 tests. These checks do not rerun native
fields, Fly or historical assets, and do not establish a complete MR/Repository acceptance result.
The native-corridor runner test now checks the canonical cache module in its actual `-m` invocation.
The full-response inventory, probe ordering, physical mapping, capacity and cleanup assertions remain;
this corrects a retired-path expectation, not a native geometry or field result.
Joint-flight and IP/prism preparation now read structural IOB containers from the installed SIMION
resource owner. Frozen dependency declarations follow that same owner while retaining the original
template bytes and PA placeholders; opt-in native tests remain separately reported.

局域 S 模型恢复的软件夹具将八个隔离场景合并到一次 PowerShell／生产 AST 读取；40 次真实 Python controller 请求保持。
每个场景以 JSONL 即时返回并断言，stderr 独立保存；已启动子进程自然排空。真实非零退出、缺／重复行及首错即时传播有行为验证。
同机单次受控对照外层墙钟39.8168→32.4221秒（约−18.57%），不代表完整MR或Repository提速；
隔离当前提交的同一方法另通过33.422秒，八场景均保留。本项仅改变软件夹具，不修改生产恢复或物理资格。

工作点批处理夹具现以同一单调期限覆盖stdin写入、首行／下一行等待及收尾，修正旧实现先阻塞读stdout、
因此无法进入`communicate(timeout=...)`的问题。断言失败后健康夹具仍在原测试预算内自然排空；
只有明确超时的本次合成进程树才被回收，不给正常原生求解添加强杀时限。真实主异常与清理失败分别保留，
生成器关闭也不能吞掉清理错误。checkpoint20场景、compose30调用、S-local八场景／40次真实controller请求、
原恢复行为与科学断言保持；117个原方法均保留，新增四个超时／排空／错误传播回归。
两个旧实现挂起均由独立20秒watchdog才结束；修复后首行前及一行后测试分别在5.156／10.129秒内完成超时和
所属根／子进程退出校验（原预算为每例5秒，后一测试有两例），不是科学性能提速。七个定向方法通过。
超时修复版的Changed实际执行162项，其中旧policy-adoption的`replace`场景因PowerShell子进程CLR访问冲突失败；
新增超时回归通过，原失败记录保留，不能因后续定向通过追认为整轮通过。

同一测试方法内的policy adoption十一案及prepared checkpoint十三案继续复用上述隔离helper，
直接PowerShell宿主启动24→2；每案目录、module作用域、`LASTEXITCODE`、真实controller及科学断言保留。
两消费者显式保留旧仓库根cwd，原有消费者的项目根默认不变。PS仅复用本批真实解析的AST和输出JSON运输，
不跨测试共享状态；原逐案启动／退出控制由helper的真实宿主退出和stderr检查替代。
同机同资源单次对照，两方法unittest合计24.841→12.239秒；逆序24案及逐single24案的原断言也全部通过。
这只是局部测试工作减少，不外推完整MR或Repository性能。本版Changed的162项通过，公开外层413.683秒，
复杂反馈五分钟目标仍未达；此前CLR崩溃根因未定，最终提交的完整Repository验收仍待取得。
[测试证据](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/scratch/20261101__runner-fixture-cost/agent5/READOUT.md)
保留RED、GREEN、原失败和异常优先级记录。本项不改变生产控制器、资源准入或科学资格。

checkpoint恢复20场景及compose回收30调用在各自原测试方法内共享PowerShell宿主与一次生产AST读取，
50次宿主启动降为20次；每例使用独立动态module脚本作用域、目录、provider与容量状态，并保存／重置／恢复
全局`LASTEXITCODE`。真实Python controller请求、原始字节身份验证和resume第二次真实reclaim保持。
原115方法及全部原断言保留，另用两个小行为测试保护正序／逆序／单案隔离及首行后的真实非零失败传播。
同机同租约串行对照的20个原消费方法套件墙钟56.027→32.798秒（约−41.46%）；
这不是完整MR／Repository公开命令的性能结果，也不增加原生求解或科学资格。
50例的正序／逆序／逐单案对照按JSON语义比较；各次原始byte身份仍由真实校验器检查，
不将不同临时根目录或PowerShell hashtable键顺序形成的不同合法字节哈希误判为状态泄漏。
正式MR selected-module入口另通过117/117；与独立Changed并发的266.817秒仅作行为验收记录，不用于前后提速比较。

工作点迭代的五个PowerShell夹具显式接收当前Python解释器，真实controller仍通过该解释器执行，
不依赖checkout存在`.venv`；JSON与源码读取显式使用UTF-8。无`.venv`的隔离checkout中，
CI失败涉及的七个方法通过，测试103.159秒、公开Python命令外层103.379秒。
此前CI `41075311439`仍保留失败；该修复不改变生产控制器、容量门槛、科学判据或数值容差，
也不代表完整MR、Repository或原生求解验收。

controller-state夹具的两个配置读取显式使用UTF-8；campaign夹具经现有`PythonExe`参数传入当前解释器，
不要求CI checkout自带`.venv`。历史prepared-owner单测只在可信Git版本查询边界提供受控小夹具，
仍验证完整owner字节绑定、来源目录、聚合完成证据、缺失历史及篡改拒绝；生产查询和恢复判据保持。

## 科学核心 P1 接线

`analysis/simion_event_analysis.py` 直接调用 `msplatform.analysis.peak_metrics`；
回归在拒绝旧峰形桥导入时执行真实 KDE，保持原适配及拒绝行为。
`config/ion_processor_dependency.json` 的 `state_schema` 指向唯一规范资源
`src/msplatform/contracts/schemas`，不恢复旧目录资源副本。
`provider_voltage_schedule` 现同样直接指向安装SIMION backend的`resources/native_drive.lua`；
电压投影、IP/Prism距离研究与冻结integration均校验并冻结该同一资源，不再读取已退役项目Lua副本。
时序编译直接使用安装IP component；原仪器时钟、15电极顺序及冻结输入内相对路径不变。
联合与分段研究的科学事件CSV writer现直接冻结安装SIMION backend资源，原运行内别名与记录语义不变。
本轮跨 RF、OA、布局适配和 MR 的 78 项行为测试通过（7.326 秒）；
其后 joint-flight、依赖及路径相关 16 项测试通过（7.465 秒）。
这些结果验证软件接线与来源，未新增飞行、场求解或科学资格。
普通PA的头部读取、分块校验与仿射组合现已迁到`msplatform.backends.simion.standalone_pa_composition`；
原生场provider、IP/Prism诊断、距离研究和PowerShell冻结路径直接消费该实现，旧项目模块已退役。
普通`.pa`格式、电极标志、sidecar与失败语义保持；此迁移不启动SIMION，也不授予场精度或科学资格。
IP交接、实测源及实测分析现直接调用`msplatform.analysis.particle_census`；旧公共census桥退役，
92项相关回归覆盖完整ID、权重、未知终态与RF冻结缺件拒绝，未新增原生或科学资格。
峰形、刚体变换与中立状态消费者均直接调用安装canonical实现；三份旧公共桥删除，门禁仍覆盖原消费者范围。

IP/Prism 距离研究的 `freeze_code` 显式冻结规范核心与 schema，并保留实际仍调用的
`resolve_assembly`、`release`；调度职责已由 `msplatform.execution.simion_dispatch` 承担，
生命周期职责直接使用 `msplatform.execution.run_capacity_lifecycle`，相关旧桥均已退出。
机器合同校验直接使用安装实现，仓库路径边界与科学校验保持分离。
runner 使用公共导入根，并在每次 Python 调用前校验核心及目标模块来自本次快照；
缺少冻结核心时拒绝宿主安装补齐。上述桥随具名调用迁移退出，最迟 P4 删除。
MR 距离研究整模块 30 项及 IP 隔离 probe 1 项通过（17.414 秒），包括真实冻结源码、
核心来源、缺文件拒绝及原 source/clock/velocity 断言；这是软件验收，没有重跑旧局部物理。

### COMSOL corridor 操作边界

同网格改压 provider 的 `compile_request`、准备、已完成 provider 解析与收尾现由安装包
`msplatform.backends.comsol.corridor_field` 实现；项目 `comsol/run_corridor_field_provider.ps1`
仍是唯一原生执行入口，显式传入仓库根、runner 路径和安装资源目录。四个 MATLAB 文件
`candidate_field.m`、`update_corridor_workpoint_voltages.m`、`export_corridor_scalar_field.m`、
`classify_corridor_conductor_voltage.m` 唯一保存在 `msplatform/backends/comsol/matlab`；
旧项目 Python 与同份 MATLAB 副本已退役，不保留转发。

MR owns its physical geometry, electrode authority and scientific constraints.
The installed `msplatform.components.parallel_mirror_dual_stripe_mr_tof` holds the
domain contracts and response authority. SIMION GEM emission, collision-overlay
geometry, native grid validation and ordinary-PA byte forecasts belong solely to
`msplatform.backends.simion.mr_geometry`; their former component implementations
are retired without aliases. Candidate permissions, binding/manifest checks and
historical retention readers remain in the existing COMSOL backend boundary.
The neutral physical resolver consumes explicit OA authority in the MR component;
native layout validation remains in the SIMION backend. Neither migration registers
an empty MR provider or qualifies a new field/Fly.
The ideal first-prism contract, hard-boundary prism mathematics and drift-phase
contract are owned by the installed MR component modules `prism_l0`,
`prism_analytic` and `drift_phase_contract`. Research consumers and source
freezers select these sole implementations; the original reference-only,
face-order, charge and return-phase restrictions remain unchanged.
This ownership move does not qualify finite fields, native transport or full MR.
The segmented prism runners record the complete prism/phase triad in their audited
source inputs. Their existing live-code execution mode remains unchanged; those
audit copies do not constitute execution from a frozen source tree.
The scalar field consumer Lua belongs to `msplatform.backends.simion.resources`;
sampling and the existing source freezers select that same installed body. Its
run-owned companion filenames and sealed record roles remain unchanged. The MR
operating-PA identity and composer ownership are separate remaining work; this
resource move changes neither field mathematics nor native qualification.
旧 `simion_candidate_reference.py`、`static_field_binding.py`、`mirror_geometry_parameters.py`、
`analyzer_candidate_geometry.py` 已退役；所有活动消费者直接使用其新 owner，不保留转发。
backend/component 均无 `projects.*` 或 `common.*` 依赖；
收尾 retention/manifest 与 solver-review 退役生命周期由 `msplatform.execution` 提供，
COMSOL backend 不持有 subprocess、ctypes 或环境生命周期；不使用回调注入或第二 CLI。原生脚本继续核对源 MPH
改压前后电压、活动网格与 solver 控制，只清除所选解数据并单次 `runAll`，随后导出基础窗及
全部有序细分窗；`field_v.pa`、`field_valid.pa`、receipt 与无轨迹资格语义不变。
本轮只迁移纯编译／准备／收尾及原生资源，没有启动 COMSOL、实际 Compute 或新增场／GUI／Formal 资格。
prepare 现沿公共源码冻结机制把 `msplatform` Python 闭包及 JSON／MATLAB 资源写入 `inputs/code`，
并将 plan 的 MATLAB 资源目录改为 run 的 `inputs/`；Child 因而消费已复制的四个项目 MATLAB 文件，
finalize 通过公共导入根从 `inputs/code` 加载 Python，而不是当前 editable 安装。回归实际删除准备时的
原 MATLAB 资源目录，并在隔离 Python 进程中完成冻结代码收尾；准备后原安装移走或更新不会改变该闭包。
公共 PowerShell 启动器、资源／容量入口和 `.venv` 解释器仍由 `repo_root` 提供，故本项不支持整个原仓库移除。
最终完整 Static 为 1785 项、3 failure、20 error、12 skip；这些失败均来自尚未同步的
`integrations` 旧 binding/Lua 引用，由主 Agent 在 integration 边界处理。MR 内定向及完整门禁
未留下其他失败；该结果不冒充完整 Static PASS。

## 当前决策与完成边界

两Prism分段诊断的阶段B只使用`stage_b_p1_exit_to_p2_low_field_reference`；旧的pre-reflection／Stripe入口别名已退役，
实际阶段终点、后续镜转折／Stripe传播算法及序列化字段不变。

无消费者的`write_geometry_receipt`文件写入包装已退役；中立`geometry_receipt`及物理几何指纹保持，现有指纹回归通过。
`select_runtime_response_bank`本轮保留：bank来源身份仍绑定整个模块，直接删包装会使未来昂贵缓存失效；未改既有身份规则或历史资产。

主设计为对称会聚双镜、五次项偏置Stripe及保留实体的接地线性Stripe。
MR拥有Prism、镜组、Stripe、检测、系统布局约束与匹配判据；跨项目装配和联合执行由
[统一集成](../../../integrations/README.md)拥有。独立器件通过不授予MR资格。

| 科学对象 | 当前可支持结论 | 关键限制 |
|---|---|---|
| 原生SIMION候选 | 自动闭合、冻结场消费与高斯N100工程结果可用 | 未取得大样本、全程数值或Formal资格 |
| 同输入COMSOL场复现 | 同几何／电压求场及受控N13已完成 | N13为0/13检测，未获得空间闭合或性能复现 |
| OA／IP组装接口 | 准备及执行主体迁至直属集成，保留提供者物理合同 | 新机械接口、纯回归与任意拓扑支持不能互相替代 |
| IP局部双透镜研究 | 已完成负结果及默认文件重放 | 存在连续几何穿杆疑点，原生到达数不是物理收集率资格 |
| GUI／CAD | 既有加载包及STEP交付保持其原证据 | 不自动覆盖新几何、场或第三方软件验收 |

2026-10-21用户将工作转向同源八极导引接OA，IP碰撞调查暂停。
后续已授权的具名状态交接与迁移验收以集成记录为准，不因它们完成而自动恢复旧IP优化或大型联合研究。

固定硬件Stripe联合试验由[工作点实现](../analysis/dual_stripe_operating_seed.py)的
`_fixed_hardware_joint_trial_at_turn`构造。已删除无活动调用或动态注册的
`_fixed_hardware_joint_trial`；其余转折位置推导与试验构造路径保持原实现，资格仍以上述证据为界。
该清理通过语法、Ruff及82项既有求解器无关回归；没有新增原生求解或GUI／CAD资格。

固定硬件镜点的六字段不可变值型`FixedHardwareMirrorPoint`由既有`mirror_candidate_receipt.py`拥有；
固定网格handoff与Stripe seed共用它，handoff不再反向导入求解器。字段、构造顺序、数值和worker序列化保持，
与携带资格证据的`ManagedMirrorCandidate`仍为不同类型；依赖调整不改变镜点校验或Stripe算法。

## 统一组装迁移任务

OA／IP准备、普通OA→MR飞行及prepared-joint执行已切换到直属
[集成状态](../../../integrations/docs/INTEGRATION.md#oaip接口准备与绑定)对应入口，旧公开准备／trial入口已删除。
MR继续提供真实几何、场、匹配与执行科学合同，不保留第二套跨器件组装器。

IP替换场计划接受成功封存的`instrument_assembly/accelerator_interface_preparation`准备结果，
同时保留原MR owner的合法历史准备资产；准备receipt及各实际消费记录仍按原封存合同验证。
该接线修复不代表已求场、飞行或取得科学资格。

实测IP→MR源和分析复用公共粒子源的六维速度投影与母群census。原ID、时钟与转交状态继续保留；
完整母群权重可得时分别报告全链与转交条件下的加权效率，历史缺失母群权重时全链加权结果不可计算。
未知权重或未知终态不推断为单位权重或物理损失；软件诊断完成不授予整束性能或Formal资格。

prepared-joint组件及工作点采集消费接口准备记录时，直接调用公共manifest的唯一记录校验，不再导入integration准备CLI。
仍要求原instrument_assembly／accelerator_interface_preparation成功身份，以及实际消费路径的唯一记录、字节数和SHA；
不把MR旧参考入口允许的interrupted状态或run-config内记录混入这一合同。
新进程回归在禁止加载该integration CLI时实际导入组件并校验记录；此依赖调整不改变场、粒子或恢复判据。

### OA→MR 运行组装合同

作者显式给出完整`CompositionPlanPath`；`LocalScopePath`只能从同一冻结父plan派生局部范围。
几何、源与IOB消费同一直接位姿，局部源只变换一次；不从历史focus或实例名称再推导位姿。
MR几何、网格、源和科学诊断保持提供者局部frame，父装配映射由实例直接位姿表达。

原生候选campaign入口[`run_native_candidate_campaign.ps1`](../analysis/run_native_candidate_campaign.ps1)
同样要求显式`CompositionPlanPath`，可选`LocalScopePath`；不按条件、历史run或默认文件猜装配输入。
两份小型输入经公共校验复制到checkpoint旁的`.d`目录，checkpoint记录源路径、冻结路径、字节数和SHA-256。
默认condition收到这组冻结路径，再复制到自身`inputs/`并登记到run config；后续已有组装与工作点入口消费
该副本，plan/scope的科学关系仍由现有组装校验负责。

恢复及下一条件启动前核对上述身份，源文件或冻结副本缺失、内容变化、路径切换，以及scope有无变化均停止，
不会递增新attempt或用新输入续接旧条件。缺少装配输入身份的旧checkpoint不能自动补写或追认；需用显式输入
建立新campaign，保留原记录。完成／中断／重试、精确K的OA provider复用及原有工作点恢复规则继续生效。
轻量回归运行真实默认condition至输入冻结边界，并在首个物理阶段前停止；这不新增原生飞行或Formal资格。

OA→MR旧renderer的`native_system_geometry.resolve_accelerator_iob_origin`显式请求OA component1，
校验已部署plan3中的原整数电极表；OA当前component3默认保持，混版与未知版本继续拒绝。
该具名旧消费边界由MR所有者最迟P4随MR科学组／后端迁移退出，不转换或改写旧父plan。
本次软件修复保留原端面、frame、相对旋转、间隙及输入字节检查，不新增原生或几何资格。

当前OA renderer要求OA相对MR的旋转为identity；父装配共同平移／旋转的支持范围按实际冻结对照判定。
IP路径保留native轴置换限制，不能据共同刚体回归声称任意相对角、任意多IP／MR拓扑可用。
真实端面、截面及电极表来自提供者；MR完整组件视图包含镜、Stripe、Prism、屏蔽和detector的20个物理电极身份，
不以PA编号、数值marker或机械端面替代完整驱动与场验收。

OA→MR的原生功能与两代完整批恢复已有证据，结果统一见
[联合飞行状态](../../../integrations/docs/INTEGRATION.md#已准备ipmr联合飞行)。
旧173601及恢复run的manifest未完整登记父plan／local-scope，不能追认其配方身份已完整绑定；
当前owner已补齐永久输入角色及篡改拒绝。恢复不改写原记录，也不以重复Fly修复统计或发布问题。

关闭条件是OA与IP各自在冻结输入下完成几何／驱动／场及相称原生行为对照，明确相交和净距检查范围。
`pulse_held_rf_zero`不升级成全程动态RF／碰撞耦合；原ID、母群损失、实际6D与绝对时钟始终保留。
接线与迁移进展只查[直属集成状态](../../../integrations/docs/INTEGRATION.md)。

实测源`measured_component_source.py`的JSON读取与有限实数表示检查现复用公共`strict_json`，
删除同义私有读取器与质心目标的finite helper；重复键、非有限字面量和溢出输入失败关闭，仍接受UTF-8 BOM。
物种、单位、实际能量账本、原ID、母群及绝对时钟的科学校验不变。纯分析同输入对照中，
质心目标完整结果相等，实测源receipt及11个生成文件逐字节相等；实际入口的非法输入与BOM回归
见`tests/analysis/test_measured_component_source.py`。此结果不新增原生运行或Formal资格。

实测源测试曾将原样复制的母群CSV绑定到Windows默认CRLF的固定SHA；同值LF夹具会误报失败。
现将交接夹具默认字节明确为LF，复制件按实际输入字节和SHA核对，四个生成文件仍保留原固定SHA。
LF／CRLF两臂均通过真实handoff→materializer入口，母群字节及身份保持，六份生成／状态文件逐字节相同；
冻结后仅改换行仍在创建输出前被拒绝。两测试模块38项通过（0失败／0跳过，12.450秒），Ruff通过；
生产源码、复制策略和SHA验证未改，未运行商业求解器或新增物理资格。

消费者审计另确认`prepare_accelerator_interface.py`私有`_write`没有活动调用或回调，已删除该函数，
保留仍被实际接口消费者使用的整个模块与独立入口。此删除不改变冻结历史源码或输出；
不能把仅测试引用、独立CLI或动态用途不确定的其他符号一并退役。

复审进一步确认`mirror_fixed_grid_voltage_point.py`的产物具有真实消费者：
`mirror_real_field_period.py`、`fixed_grid_mirror_stripe_handoff.py`及
`mirror_fixed_grid_voltage_correction.py`读取`mrtof_fixed_grid_mirror_voltage_point` receipt。
因此保留该独立准备CLI，职责是把受限修正提议物化为待验证点；它不启动求解或授予工作点资格。
仅在这三条receipt消费路径共同迁移或退役后，才能移除该生产者。

固定网格电压修正要求来源显式声明既有gamma operator，并与实际one-point／chord输入身份一致；
未知、缺失、部分native或矛盾身份不再默认按sampled解释。PowerShell端点选择消费同一Python校验器，
合法native／sampled及原权威gamma保留；旧证据不足时须从原冻结测量输入重建修正分析，不自动求场或改父记录。
现有模块19项回归通过（公开墙钟10.197秒），包含真实PS参数装配及错误传播；未新增原生或科学资格。

原`analysis/cad_pose_contract.py`实际只服务机械坐标回归，没有生产调用或CLI，现迁到
`tests/test_support/cad_pose_contract.py`，唯一测试导入同步切换；不保留生产转发。
仅模块说明改为独立测试参考，去除该说明后AST相同，变换计算未改。
`config/cad_to_theory_frame.json`及CAD证据保持，机械中面映射与逆变换仍由独立参考验证。
这明确其长期验证归属，不把测试实现当作当前CAD生成入口。

## 加速器接口与整机暂停边界

独立加速器可选OA或IP，器件来源与实际父plan均须显式绑定。IP使用实测出口状态交接，
不是在同一次Fly内连续积分HP捕获／冷却到MR，也不能用缩放速度补能量匹配。
IP峰形必须绑定真实共同提取脉冲，不能沿用OA零出生时钟、逐粒子扣除交接时刻或伪造零脉冲。

| 具名历史链 | 已有结果 | 结论边界 |
|---|---|---|
| 原97出口IP联合链 | 100母群含3上游损失，19检测、78下游损失；旧源脉冲相对KDE FWHM 15.717136 ns、R≈24280.5 | 质心闭合不等于整束匹配；不是零交叉新源或Formal性能 |
| 524 Da真实多极杆→IP→MR | 100母群为19上游未交接、61下游损失、20检测，timeout为0 | 状态／时钟链功能闭合；IP原0.81捕获／提取门限failed保持 |

前者见[联合母群里程碑](history/20261017__ion-processor-closure-and-joint-population.md)，后者见
[真实状态交接](../../../integrations/docs/INTEGRATION.md#真实多极杆ip状态交接)。不同源、场、工作点与母群不能混并。

零交叉实测源的大型重新闭合研究按2026-10-20用户决定暂停。185918完整场对照未复现先前NaN，
但仅证明该具名数值设置下全量有限；不是几何／场收敛。被冻结的部分失败、中断与准备工作不当作完整飞行。
IP后续方向是实际横向相空间与慢轴返回匹配，不能只调平均能量、缩源或裁尾代替。

## B/C/D局部研究的有效边界

轮廓、局部时间焦点、孔口筛选及默认回放见
[局部里程碑](history/20261020__ip-bcd-local-focus-and-replay.md)与
[三路线里程碑](history/20261020__d-routes-theory-local-validation-and-replay.md)。
D保持较高原生到达计数，但未同时优于两轴角宽和最小时宽；各路线必须使用各自冻结出口。
厂家未知尺寸、连续孔口碰撞及局部离散限制仍有效，不由新增透镜覆盖。

prepared-joint与IP局部诊断的PNG／SVG保存复用[公共图形导出](../../../src/msplatform/io/figure_export.py)，
分别保留180／200 DPI、白底、文件名及原文件记录／科学metadata。SVG沿公共字节流写LF，记录实际SHA，
不改写旧产物。图形仍由项目创建和关闭；
目标已存在时拒绝覆盖，格式保存失败只清理该次导出创建的文件，成功或失败均关闭图形。
此调整不改变绘图数据、数值诊断或资格，metadata写入失败不回滚已完成的图形文件。

### 双透镜的取舍与当前结论

新大间距配置Q1／Q2中心z=-18／-30 mm、长度5／3 mm、电压+85／-95 V，作为整体候选比较。
同92颗P1到达群相对旧偏置，x角宽降低6.318%，y角宽增加278.669%，y束宽增加128.206%，未满足三目标。
ID11绕到第二镜杆外侧并贡献完整群约95.25%的y角方差，不能删除后宣布改善。
没有可推荐的同时满足三目标的参数；完整数据、轴模型残差和保留负结果见
[双透镜里程碑](history/20261021__doublet-phase-space-and-wide-spacing-validation.md)。

### 数值、诊断与复现边界

两档时间步均93原生到达、全部96终态身份一致，支持该样本的时间步稳定性；
但存活ID3保存点进入连续Q2杆内约0.029 mm，半步长仍存在，不能把93作为已验证物理收集率。
小型静态查询支持碰撞边界网格敏感性，未证明全部穿越或vendor算法失效；首个OFF探针初始化失败，
十臂Fly碰撞矩阵未完成。候选首接触修正未完成原生验收，不替换默认资产。

新进程默认文件重放的events／samples共195,213行逐字段及字节一致，只证明文件回放一致，
不代替用户GUI确认或修复物理缺陷。手动Fly前完整复制case到独立可写目录，不原位改写封存模板。

## 输入权威与物理定义

参数权威是具名运行的冻结几何、源、数值、场binding与工作点合同；下表只识别保留OA候选，
不能用来覆盖IP分支或重建任意新run。机器身份与当前活动合同由[项目README](../README.md)导航。

| 对象 | OA候选识别性摘要 |
|---|---|
| P1／P2 | +191.69798504788915／-186.47253641442782 V |
| 五次Stripe／线性Stripe | -26.98736945139317／0 V；接地线性实体保留 |
| 镜A–E | 0／-5929.660769425788／-2568.4173725265146／+4162.7537535912525／+6003.305171198471 V |
| 单镜倾角 | 0.025688744787259285°；正负镜设计镜像 |
| K／目标 | 24.5／49个快速半周期 |
| TE1坐标 | -34.10982644173019；增量从当前坐标出发 |

倾斜对象是平面镜电极，不是曲面镜；OA、Prism和detector不具有镜组的全部对称性。
C0为指定外边界假设，完整内表面x=[-162.5,162.5]、y=[-242,558]、z=[-425,425] mm；
半模型五个外面接地，x=0为对称面。它不是已确认机械腔体，省略C0的开放BEM是另一问题。
镜E盖板保持E电位，不接地；不同电位实体不能接触。两区理论出口时间焦不自动证明实际束团聚焦。

## OA真实源与束团证据

冻结源为524 Da、+1，共同出生时刻，沿+y释放的圆柱高1 mm、半径0.5 mm，角宽为零。
位置和标准化能量取同一1000母样本前100，不重居中、不缩源或裁尾；真实出生时间宽、空间电荷、
制造及探测器响应未覆盖。高斯sigma是释放动能标准差，不是速度sigma。

以下同一候选电压、镜区z=0.02 mm场、4 ns／Q8与common KDE，完整来源见
[会聚场及性能里程碑](history/20261015__converging-field-and-performance-milestone.md)及
[收口前证据索引](history/20261026__assembly-documentation-consolidation.md)。

| 高斯sigma(Ey)，eV | 平均TOF，μs | KDE FWHM，ns | R | 检测／母群 |
|---|---:|---:|---:|---:|
| [0.15原run](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_040845__sim__simion__converging-y360-z002-gaussian-ey-sigma0p15-n100/summary.json) | 764.216444815 | 3.768379855 | 101398.541848 | 98／100 |
| [0.20原run](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_044251__sim__simion__converging-y360-z002-gaussian-ey-sigma0p2-n100/summary.json) | 764.216316535 | 4.721538636 | 80928.736944 | 95／100 |

主条件sigma=0.2未达十万，0.15的名义结果不能替代主条件或大样本资格。
镜z网格0.04→0.02 mm时峰宽改变约-0.006／-0.005 ns，损失身份不变；公共TOF漂移单列，
不作为峰宽。历史平行／会聚比较同时改变几何、电压、表示和步长，不能将全部差异归因于倾镜。
受控N13含中心及具名扰动，与纯体积N100不同；高斯ID1不是名义源中心。

## 时间峰结果与方法身份

当前活动峰合同使用`common_gaussian_kde_time_v2`，两个MR分析器共用公共纯时间KDE入口；
source-z比较、原生候选链和campaign排名同时要求当前方法及一致的冻结合同。旧v1结果留在原run中
只读解释，活动峰计算请求拒绝v1和未知方法，不重写旧receipt、历史峰数或既有Formal身份。
时间宽度及`mean_tof/(2*FWHM)`保留原数值定义；`mass_resolution_t_over_2fwhm`仍是既有摘要的时间等效投影，
不表示经过质量标定。v2的`significant_time_kde_modes`取时间密度；v1的旧同名峰数实际来自名义质量密度，
两者不能直接比较。公共metadata随结果和图表metadata保留方法、设置、单位、ddof=1、观测数、权重和及资格边界。

非`formal_volume`的原生受控诊断不请求KDE；其历史或未知方法合同仅保留为来源，峰结果明确为
`unavailable_controlled_or_unclassified_cohort`，不可计算metadata不声称已验证方法、设置或时钟。
这使既有单中心run的静态返回／出口诊断可独立重分析，不新增旧峰算法或把旧方法改标v2。
合法v2的所有角色仍走原设置校验与metadata路径；正式束团的v1／未知方法继续失败关闭。
真实`20261006_030113__sim__simion__mrtof-comsol-p1-plus1-center`历史输入的回归保留原残差和出口失败
断言，原文件只读，不将中心返回功能贯通解释为几何出口或Formal资格通过。

OA零出生路径仍要求具名共同零出生合同。实测component路径继续验证共同instrument epoch和冻结提取
时序，对全部detector hit扣同一个pulse，不按每颗交接时刻重居中；母群census和损失保持完整。
canonical `particle_weight`显式传入KDE，当前只接受正有限等权；非等权不会被忽略。
纯时间结果不再附带无需求的名义质量谱；source/检测条件和`detector_survivor_conditioned_time_equivalent_only`
限定保持，不从数值可计算推导Formal或仪器性能资格。

legacy `mass_th`的历史Th命名与实现直接作为SIMION质量及AMU动能因子的用法并不构成任意电荷态的
一致合同。新结果只在已知+1时标注数值相容的`mass_amu/charge_state/mass_to_charge_Th`；未知或非+1
的legacy输入保留原物理运行值，质量派生明确不可计算。已验证canonical状态沿用其三个独立字段，
不把该身份传递测试解释成新的多电荷运行资格。

本轮十个focused模块共333项，330通过；两项因隔离checkout无外部历史证据跳过，一项显式
native-97历史后分析未启用。覆盖公共数值、项目适配的合成参考、源/时钟拒绝以及真实PowerShell
方法门禁，另两份修改PS脚本语法检查通过。
公共旧质量入口对12组合法样本的完整metrics和全部spectra数组与改动前逐值一致。
未重跑历史资产或商业求解器，不称为历史golden重放；Core门禁不能代替这些消费者回归。

辅助直方图现由同一`histogram_half_height_bin_span`实现发布，方法为
`sqrt_count_histogram_half_height_bin_span_v1`：保留原sqrt(N)分箱及所有半高以上bin的首尾包络，
即使中间有空bin也不将它解释成插值FWHM。结果记录原单位、样本数、bin数／宽度、规则及不足8、
零方差或可计算状态，并明确禁止detector resolution解释。target-K摘要改用
`target_k_handoff_histogram_half_height_bin_span_us`及其descriptor；普通分布使用
`histogram_half_height_bin_span`，旧含混字段不作为活动fallback。真实时间plane继续发布v2直接KDE宽度，
短出口试验同步将该辅助量标为不适用，未删除返回位置／能量／角度诊断。

TE1比较的z=0与detector两平面现在都验证当前方法、各自结果／合同设置以及共同零出生时间参考，
z=0合同还须与本次detector一致；缺方法、旧／未知方法、不一致设置和时钟不会进入辅助分辨率比值。
两个MR峰适配器的不可计算分支保留输入数、实际相对权重和、有效样本数、ddof、单位及状态；
缺峰合同时方法／设置和时间参考仍未指定，不由可用的到达时间自行赋予时钟资格或虚构峰值。

该收尾的四个既有测试模块182项通过，另三项真实PowerShell方法／排名门禁通过。
改动前后内存对照中，3组原生与3组实测主峰完整结果相等、21个谱数组逐值相等，
8组辅助直方图数值完全保留；新增回归覆盖断开的半高bin、退化状态、新字段消费、
z=0方法／设置／时钟拒绝及真实当前producer输出消费。仅证明分析合同与数值迁移，
没有运行商业求解器、重写历史产物或新增Formal资格。

## 工作点控制决策职责

staged工作点的一整次trial规划由既有`workpoint_controller_state.py`纯决策实现，经
`workpoint_controller_state --controller-request - --output -`传输，不再为纯状态请求加载数值分析栈。
数值分析仍由`downstream_workpoint_iteration`承担；旧隐藏controller分支已删除。层级与正反列次序、
候选缩放、声明边界、L∞步长下限、候选／飞行预算和终态在同一请求返回；PowerShell继续
核验冻结身份、写入pending checkpoint及调用实际飞行。普通回合只增加一次完整规划请求；
仅累计拒绝触发局域模型重置时，先发prepare请求并保存，再读取新科学decision并规划trial，
保持原先的恢复次序。完成trial的接受判定仍使用原有`complete_staged_trial`请求。
transport seed 的整批有序候选、bootstrap 四步长与重试比例、已验证 centre observation
的物理通过判定也由该纯决策模块提供；PowerShell 保留完整 manifest verifier、身份核验与
逐次保存/执行次序。物理 gate 每份实际 observation 使用一次完整反馈请求，未将完整
manifest 验证缩成 record 子集。其他 stencil/recovery 状态转移仍按原入口执行，尚未据此
宣称全部 PowerShell 科学决策迁移完成。
同机Python 3.11、公共2CPU／2GiB租约的串行对照中，三个原工作点恢复测试合计
129.613→27.713秒，原5／8／2组场景、请求和预算断言保持；两个新增行为回归覆盖真实stdio
非法输入拒绝及PowerShell错误传播。该局部测量不代表完整项目或Repository提速，也不新增科学资格。
bootstrap stencil 每次调用另用一次完整计划返回五个轴组的有序候选；保留原
`direction * forward_step * step_scale` 两次乘法。旧记录的重复身份、signed step及SHA
仍在该候选实际被消费时核验，不因预先规划而提前拒绝未来候选或改变前序checkpoint。
显式导入的 Stripe 列在原身份校验后，每列用一次完整请求计算 tier、signed step 与
flight debit，随后原位调用完成逻辑；不预读后列，两项原始decision仍先加入history，
正常checkpoint仍由整次导入完成后的外层保存。
局域 S 恢复按每次实际 probe 的完整状态选择候选、扣费和回合结束动作；已有列不重飞，
优先方向被拒后使用实际接受的反向列。模型完成后的缩步、预算补回、终态及最终半径的
provisional 判定归同一纯决策模块，保持原政策；PowerShell 仍先保存准备状态，逐次保存
started／实测结果，并在必要模型改写后才计算其实际 SHA。每次 probe 的计划和模型完成
分别使用完整请求，不把有 I/O 依赖的反馈提前到前一保存点。
已存列的 stage 资格在原 lineage／SHA 核验后按整组请求一次；主飞行次数预算在原
循环前判定，只有实际循环耗尽时才追加结束判定，不预先发布未来终态。canonical 轴名与
inactive S2 的冻结身份校验仍由 PowerShell 执行；这不更改历史恢复输入的表示规则。

Candidate chain 的源直径焦点预算、受控对 fallback 配方、焦点收敛／严格最佳候选选择、
z=0 诊断分类与最终资格优先级由现有 `source_z_energy_timing_diagnostic.py` 提供。
centre 残差容差判定复用工作点控制模块，已发布 collection receipt 的接受判定归原束团 gate；
PowerShell 继续核验实际身份并保留读取、执行和保存顺序，最佳候选携带其原场与工作点引用。
反馈经现有分析入口按完整决策包传输，不建立常驻解释器或新的科学 mode；z=0 仍只作诊断。
campaign 在原顺序读取各条件及诊断后，以一次请求投影完整比较并排名；旧方法不取得当前资格，
原 compact JSON 合同表示的键顺序仍参与共同峰设置身份，空值及并列排序规则不变。
迁移增加短 Python 反馈进程成本，职责统一不作为运行加速结论；验收限于求解器无关参考与真实入口夹具。

恢复方向随原有`prepare_recovery_state`请求一并返回，持久拓扑损失也由同一Python决策模块
投影。History传入整个字典时保持现有默认`[1,1]`，再由触发记录和有效显式提示依次覆盖；
不会暗中改成遍历`history.decisions`。冻结策略、数值阈值、浮点运算次序和已有probe扣费／重试
合同不变。迁移验收使用旧PowerShell实执行参考向量与真实runner软件夹具，不新增商业求解或
物理资格，也不改写历史checkpoint。

## 活动原生场与消费合同

跨项目飞行从[直属OA→MR入口](../../../integrations/workflows/oa_mr/execute.ps1)进入；
MR专属staged工作点及候选控制仍从[操作说明](SIMION.md)选择。
场由现有native static provider与`static_field_binding.py`提供，不能另建手工闭合器。
`static_field_binding.py`是 native／scalar 固定 field-family metadata 投影的唯一 owner；
`downstream_fixed_grid_workpoint.py`只叠加 canonical centre source 与完整布局的科学语义。
响应 metadata 不再反向导入工作点模块，也不读取 PA 全文；此次调整不代表整个 provider
依赖图已完成清理。
运行必须冻结对应实际资产；源码接入和纯回归不授予新原生、GUI或Formal资格。

| 场层 | 冻结布局 | 网格，mm |
|---|---|---|
| C0父场 | 完整半外壳和相关装配 | 0.50／1.00／1.00 |
| 中央局域场 | [0,-100,-325]至[22.5,390,325] mm | 0.25／0.25／0.10 |
| 镜局域场 | x=0..2，y=-65..360，z=±90..±324 mm | 0.04／0.20／0.04，细档z=0.02 |

五面边界继承同电压父场，镜域先完整求解再裁剪存储，裁剪不是重新Refine。
实际优先级、碰撞载体及有效域按binding判定。新规则网格遵守[项目约束](../README.md#项目边界)，
旧冻结资产不静默取整。显式1e-5 V停止参数不是场误差界；历史1e-6对照不授予所有轨迹资格。
电势对电压线性、轨迹不线性；响应组合仍核验几何、网格及边界身份，不用旧y350或粗档响应冒充新y360细场。

`nonaccelerator_scale`非1时，Python静态与Lua运行的电极缩放定义尚不一致；当前scale=1不受影响，
其他值须先明确科学定义再统一投影。完整批续算由公共API按冻结前驱manifest绑定，不搜索未声明来源、
复制旧日志或把复用Fly说成新run执行；不完整批整批重跑。

## 电场表示与数值资格

COMSOL对完整C0独立求场，经标量电势→规则PA→SIMION求导／插值／窗口后追迹，
两来源复用事件与诊断，不是两个独立轨迹求解器的等价验证。场求解、导出、窗口、积分和事件误差分别管理。
原生细档峰宽较稳定不代表全部慢转折、尾部和返回事件收敛；约0.2 ns只是十万目标的总体初始工程预算。

### 有效场与固定输入对照

当前mesh4有30,697,694四面体、Q2、CG+AMG、rhob40000、sol4/dset1；参数和可重复性不等于误差界。
四窗导出基础窗有5664未知节点，需检查真实轨迹支撑，不能补零或当碰撞。
固定输入的mesh4 N13全部有target49，0/13检测，10接触终止＋3拓扑拒绝；无检测峰宽或R。

| 固定输入比较 | 最大相对中心ΔTOF，ns | 最大Δy，mm |
|---|---:|---:|
| mesh2→3，target49 | 0.601675 | 1.878743 |
| mesh3→4，target49 | 0.211393 | 1.006036 |
| native细档→mesh4，target49 | 7.342627 | 15.095070 |
| mesh3→4，同入口正镜五颗 | 0.028632 | 0.013904 |
| mesh4→native，同入口正镜五颗 | 0.037722 | 0.071485 |

同入口单段继承原6D及时钟，不能把局部差乘49当整程误差或性能。
准确冻结输入、场来源及run映射见[匹配比较](history/20261015__matched-solve-and-trajectory-comparison.md)
和[边界隔离](history/20261015__boundary-input-isolation.md)。

### 当前已隔离的差异与下一决策

消费分层支持主要慢向跨源差已存在于原始场，不能靠盲目细化导出消除。
五面边界单因素试验把所查正镜空间／速度差缩小约30／12倍，但相对计时与横向差未同步缩小，
仅证明该段慢向状态受边界影响，不授整程资格或指定FEM为真值。
父层同U直接／组合场及停止对照不足以解释跨源差，父z方向的实际查询敏感性明显高于y方向。
详见[边界与父场](history/20261015__boundary-and-parent-consistency-isolation.md)及
[父场拆轴](history/20261015__parent-axis-field-isolation.md)。

原文曾写“正在执行”的中央层`20261016_000829__build__simion__zparent-full-central`已由
[终态summary](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261016_000829__build__simion__zparent-full-central/summary.json)
记录success、5106.1064271秒、Refine完成；未Fly、COMSOL或crop，qualification仍false。
它只用z=0.50 mm父场重建中央层并查询原25点，旧中央为物化、新中央为直接解；
不能把该终态当作纯全局误差界、镜重建或束团资格。

## 剩余时间响应与设计线索

同95颗的分段响应显示P2入口状态可通过P2转换成明显到达时间差，不能仅按差异增大的区段归因。
宽幅z、横向偶响应、Ey和孔径尾部仍需联合解释，不能把各段最大差相加当完整FWHM。
S1单独-0.1 V对Ey改善弱且空间相位变差，保留负结果，不重复同一小扫描。
后续设计依据镜倾角／Stripe／注入联合响应，保持主源条件和全部损失，不恢复未有依据的千伏Stripe。

## 开放动作与关闭条件

1. 先审阅已完成中央层25点结果并核对其输入／输出身份，再决定是否有必要进行镜重建或实际轨迹对照；
   单段、边界、父场、停止与内部离散分别判断，不能靠分别调压冒充固定输入收敛。
2. 代表射线支持后才考虑冻结高斯N100复现，统一KDE、全损失及不确定性；否则交付量化差异与下一物理决策。
3. COMSOL改压provider的readback仍绑定sol1/std1，不授mesh4的sol4重建资格；普通冻结场重放不调用该求场作者。
4. 新组装按实际冻结plan完成驱动、场和原生行为验收；IP碰撞调查及旧大型研究保持上述暂停边界。
5. 非单位scale先统一科学定义，真实几何碰撞疑点关闭前不得将原生到达数发布为物理收集率。

当前场、响应库、GUI和CAD按公共owner及实际消费者保护；旧场退役、容量异常及重建路径见
[收口前记录](history/20261026__assembly-documentation-consolidation.md)，不得由运行终态推断可删除。
prepared joint 续跑按冻结 Fly 依赖判断批次复用；已验证的 v1 峰分析合同可在新 run 中
切换为完整验证的 v2 分析合同，历史合同和结果保留原身份。已完成批次须有 owner 的退出
证据；历史成功批仅在现有终态、聚合 usage 和已核验的原 owner 版本共同支持时兼容。
IP→MR 新场工作流在求场前验证设计绑定的真实 handoff、粒子绝对时钟与共同脉冲；
预检不代表求场或科学资格通过。
OA→MR 和 prepared joint 共用 MR `Protect-MrtofContinuationEvidence`：沿显式 manifest 绑定投影多代来源，
先追加容量保护，再对实际文件持 share-read 防写锁并复核投影，直至 writer 停止；仅直接前驱不能代表全部祖先。
固定原批区间续飞时，已知资源画像须覆盖最大缺批；否则实际观测最大缺批并以原分区单 lane 续跑。
`run_native_corridor_response_bank.ps1`新建receipt recipe使用schema 2及显式`source_location=payload`；
其声明库存同时保留raw、8个原生response、8个standalone和receipt。已有v1响应库按公共严格版本reader读取，
仍要求原source的manifest身份、publication pin及冻结bank身份；不会用当前编译器输出冒用旧cache key。
显式transaction续跑／member recovery若已登记recipe，由公共owner沿原journal重放，不提交新recipe或旁路重写receipt。
保留的[IP联合加载包](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261018_132106__analysis__python__ip-collision-overlay-workbench/results/joint_workbench/runtime/joint.iob)
复现原97出口／19检测链，含0.05 mm碰撞占据patch；它不是524 Da新链的GUI验收。
手动Fly须使用独立可写的工作台控制／日志目录并核对永久PA绑定；未变大PA按封存身份只读复用。
当前 launcher 的 `load-workbench` 与批处理 Fly 共用碰撞 PA 预载，打开同一 IOB／Program／Fly2，
保持 RAM 中的不可 Refine 标志；使用方法和官方依据见[SIMION说明](SIMION.md#事件与分析)。
这补齐代码中的装载状态差异，不追认旧包已人工打开，也不使普通 PA 查询等于程序回调场。
[STEP交付](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_163154__build__cad__mrtof-tilted-step-publication-recovery/summary.json)
含40独立电极、6个C0参考面及装配概览；5 μm交换精度不是场或制造精度，第三方消费未验收。
[Pulsar英文交接包](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261016_140921__build__python__pulsar-trajectory-handoff/summary.json)
与待用户发送的邮件保持原发布身份。

## 机器能力与解析输入

`native_condition`指向原条件runner，显式消费ConditionPath、ContextPath与CompositionPlanPath，不猜latest资产。`analysis/execution_binding.py`从本次release/context小合同核对实际质量／电荷，物种不匹配不能READY；无结构变体时返回null。Candidate／Formal请求须符合真实支持域，不能静默降级。现公开profile的100／524 Da、+1条件仅表示输入适用范围，不代表科学资格。
编译结果绑定小定义并持续保护，原owner从同一定义准备／冻结／执行；能力查询不生成GEM、不读大PA。OA几何与IOB pose消费纯几何提供者，新机械exit-origin与合法旧PA frame显式转换；未知frame拒绝，旧plan只读，世界布局不变。查询与执行入口见[公共合同](../../../common/contracts/README.md#执行dry-run)，READY不代表科学资格。

## Installed prepared-joint recorded analysis

`msplatform.workflows.prepared_joint.diagnostics analyze-joint` owns the complete recorded-data
analysis CLI. `measured_population` closes the original source census and `loss_acceptance` supplies
the existing diagnostics; the sole SIMION recorded-event/trajectory adapter is
`msplatform.backends.simion.mrtof_observations`. CSV iteration and PNG/SVG export are installed neutral
I/O. Their former project/common implementations and moved CLI operations are retired; the remaining
native materializer, controller and research operations retain their current owners.

The operation consumes explicit preparation, merge, source, timing, field-binding metadata and declared
observations. It does not discover Git or invoke a supplier, need PA payloads, or create a run owner.
Posthoc peak-method changes preserve the native/nonpeak contract; relative timing records are resolved
against the explicitly supplied analysis contract directory. Original mother IDs, birth/absolute clocks,
repeated/reverse events, unknown loss and declared trajectory choices remain authoritative. Missing or
changed declared data fails; completed raw data can be analyzed independently after a native or analysis
failure. Structured merge records now include the actual closed-log byte count required by the existing
strict bound reader, alongside the unchanged SHA; historical records are not rewritten.

Software validation and installed legacy/CSV reanalysis are recorded separately from native execution.
This ownership migration does not grant field convergence, Fly, GUI or Formal qualification.

## 结构化科学记录

正常试验／批次物化器冻结公共CSV写入器、私有事件和可选轨迹位置；收据、归并、恢复及保留GUI
工作台携带同一来源。原进程日志保留进度、错误和完成事实。新原生程序直接写字段，删除旧整串格式化
再解析及无声明stdout科学记录旁路；既有事件12位、轨迹和原生contact诊断17位分别保持。
软件回归通过实际Lua发射、探测面插值与拓扑拒绝分支及公共CSV writer验证科学字段和I/O失败传播，
不再要求活动程序出现旧stdout格式文本；旧日志读取适配保持。这些受控状态回调不代替原生轨迹验收。
三条plain-Lua回归使用安装的SIMION Lua运行时；加载实际Program的两条夹具声明公共CSV writer与私有临时输出，
原穿面、方向、计时、phase及flush检查保持，科学字段从真实CSV读取，进度仍从stdout读取；不启动Fly或Refine。
ID以十进制字符串保留；Lua数值运输拒绝非有限、非整数及超出连续safe-double整数范围的ID，
避免Lua5.1的%d在大ID上截断。公共canonical整数合同不因此增加全局上限。

读取完整保留原ID、原始绝对时钟／方向／穿越次序及母群；权重仍只消费原有源／census权威，
未知权重不补等权。声明CSV缺失、损坏或不符冻结身份即失败，旧log仅作为历史读取适配，父记录不改。
日志身份与原生完成在同次读取取得，旧归并不再全文驻留或另读日志哈希。
实测组件分析直接沿该读取器取得事件／完成事实并调用唯一的`_close_event_rows`闭合母群；
已删除无消费者的整串`_close_events`包装及其专属导入。终态、ID、绝对时钟及历史log读取判据不变。
20项实测组件分析及1项prepared-joint实际分析消费者回归通过；未新增原生求解或科学资格。
`mrtof_batch_flight.merge_rebased_event_logs`的逐批科学声明与完整批一一对应；显式`None`仅表示已核验的
历史log单元，可与新CSV单元共同归并为本次结构化事件。OA→MR只为公共恢复计划已确认可复用的旧单元
传此声明，新批或已经声明但缺失的CSV继续拒绝。归并保持原完整ID及终态覆盖，不双写科学stdout，父记录不变。

软件覆盖真实Lua5.1.5写入、稀疏ID、混合精度、IO失败、实际冻结／批次／恢复／分析消费者。
明确的20261006单中心历史50,885B／353事件重分析与本主题HEAD分析器的整个JSON逐字节相同，
不据此升级原资格。完整生产程序的小型原生记录边界见下节；正常集成入口代表性链验收另行记录，被动记录不改步长、电压或终止判据。

实测源与轨迹回调夹具同样绑定真实事件／轨迹CSV及ID编码完整闭包；IOB companion复制夹具消费实际builder的路径函数。
三模块17项回归中15项通过、2项显式原生opt-in跳过；保留完整状态／时钟、被动记录与封存失败传播判据，不代表新增Fly。

### 小型完整MR Program科学CSV原生边界

现有`test_native_corridor_runtime_support`的显式原生用例追加完整当前`mrtof_candidate.lua`，
通过项目既有builder保存四槽IOB，再由两个独立原生进程从同一保存IOB Fly，分别写私有CSV并由原MR reader校验。
它复用11³八响应fixture；可选pitch默认1不变，第二个pitch0.2族仅提供2mm的test-only加速器槽。
两族共18次极小Refine，非生产MR场、N100、joint、GUI或精度资格。源位于(5,5,5)，全零电压，
Q8／0.002us与显式0.02us截止只定义该小机制问题，不改变生产默认物理或终止规则。
完整Program及波形／周期计数／电压映射／writer原样冻结，小来源记录绑定实际文件；不以摘录helper代替生产回调。
先做纯生成与惰性Lua接口验收，真实保存／Fly／冷重开结果需单独记录，不把计划写为已完成。

2026-10-31 真实SIMION 2020小机制验收：完整当前MR程序经原builder保存IOB，两个独立进程各Fly一次，
18次11³ Refine调用，外层约11.81秒；观测峰值RSS191,463,424字节。每次事件CSV1,089字节／轨迹CSV780字节，
原ID1，出生／step／terminal齐全；两次CSV逐字节相同。显式test-only零电压域，N1，Q8／最大步长0.002µs；
0.02µs停止触发对应原生终态0.018µs，不声称精确截止或探测成功。非GUI、N100联合链、场精度或科学资格。

实际反例发现停止试探步可在terminate前回退（0.020→0.018µs）。结合真实回调与
[SIMION停止调度说明](https://simion.com/info/trajectory_programming.html)，step仅在未发出终止请求时记录，
terminal仍记录供应商最终状态；ion_splat、步长、电压和接受条件均不变。真实前后事件CSV完全相同，
轨迹仅去掉最后未接受的试探步（12行→11行），没有删除粒子。新增真实回调负例保护这一边界。
早先五轮失败原样保留：隔离缺种子配套、夹具缺x镜面、同名程序导致提前加载、8电极与9槽请求不匹配、
终止试探步记录反例。只修资源／夹具与被动记录，不放宽生产校验。usage最后采样status仍为running，
仅用于观测峰值；终态由公共过程观测exit0、测试及host释放证明，不把旧采样当成完整终态。
证据在instrument_assembly scratch的20261031__mr-csv-native-fixture/agent2/root_native_attempt_01..06及比较记录。

### 原生 IOB 构建行为回归

已删除锁定旧 `wb:save(output)` 拼写的源码断言；当前构建器实际通过路径投影保存和重开。
既有 Lua 行为夹具保留四／五角色、完整电压及错误输入拒绝、保存重开和优先级检查，
并显式断言先加载输入、只保存一次、再重开同一输出；不依赖调用文本或参数包装形式。
三项既有行为方法通过1.194秒；新增顺序断言的方法通过0.578秒。
CI 41181531874 的失败记录仍保留，本修正不是完整软件性能或原生求解资格验收。

MR analytical and native-geometry callers now import the installed OA two-zone renderer. Existing source inventories also retain its three canonical backend files; geometry/voltage semantics and historical runs remain unchanged. This migration does not establish new MR native or frozen-execution qualification.

## Installed prepared-joint analysis admission

`msplatform.workflows.prepared_joint.analysis_inputs.prepare_analysis_inputs` admits
one explicit terminal prepared-joint source and freezes only its manifest and the
author's analysis contract. It uses the existing canonical capacity ledger and
manifest verification with the existing retention classifier; no new owner exists.
Original native logs, batch receipts, FLY2, preparation and protected source paths
remain at their producer locations. Complete original-ID merge, mother/launched
counts, clock epoch, ready owner and failed-analysis stage checks are unchanged.
Earlier failed native flights are not newly admitted; their existing continuation
path remains separate. Admission does not perform scientific analysis or native Fly.

The sole recording validator and query CLI are now
`msplatform.contracts.trajectory_recording` (`python -m ... --contract <path>`).
Original every-step/fixed-interval choices, positive explicit output budget,
solver-review retention/reason and default-off behavior remain unchanged. The old
multipurpose recording-config command and root admission module are retired.
Full prepared-joint diagnostics and trajectory extraction remain explicit P4 work;
this slice does not claim them installed or change cohort/clock/event/loss semantics.

The bounded admission migration passed the original six-scenario public post-hoc
analysis fixture with its 45-second/process/outcome assertions preserved, focused
source/policy/boundary regressions, frozen OA/MR provider origin checks and the
original five-method ordinary wheel/sdist acceptance. Plain-Lua launcher fixtures
are software checks; no new SIMION Fly/Refine or COMSOL solve was performed.

### Installed batching dependency

Active batching callers now consume the sole installed
`msplatform.backends.simion.particle_batching` implementation. Existing batch
plans, ID rebasing, emission ordering and project-owned scientific checks are
unchanged. This migration provides no new native or scientific qualification.

### IP/prism placeholder source ownership

IP/prism preparation keeps the structural IOB under the canonical installed
SIMION resource owner and copies its required PA placeholder from the explicit
repository fixture at `common/simion/assets/iob_instance_seeds/iob_seed_placeholder_01.pa0`.
It no longer assumes that this PA is adjacent to the relocated IOB. The original
`inputs/workbench_seed.iob` and `inputs/iob_seed_placeholder_01.pa0` locations and
input records remain unchanged; no PA fixture is added to the package or cache.
The eight original preparation/replay error cases and one missing-original-source
regression passed (9 tests, 2.830 seconds). The copied placeholder's size and SHA
match its original authority and its existing run-input record is retained.
The integrated complete distance-study module then passed 31 tests in 14.660 seconds.
Other modules were not rerun for this path repair. It performs no native load,
Refine or Fly and does not add geometry or scientific qualification.

### Canonical verifier and detached MR fixtures

The bootstrap and corridor software fixtures now exercise the canonical manifest-verifier command,
including its status/project/mode selectors. The detached exact-K fixture includes the real installed
retention policy; the scientific event writer fixture loads canonical run_paths. Production execution,
scientific constraints and all 845 existing assertions remain unchanged.
The four complete modules passed 188 parent tests (15 existing record-level skips) in 367.863 seconds
in the normal Windows process context. On the composed P4 successor, the five original failed parents
passed again in 24.460 seconds (29 successful records). A prior restricted-context cleanup failure remains
a separate failed run. These checks add no native Fly, field, GUI or Formal qualification; final Repository
acceptance remains open.

### Exact-K record-validation provenance

The Exact-K research runner records the actual canonical retention/manifest-record
validation closure and its single `artifact_retention.json` policy alongside the
existing analytic source inventory. It compares current sources with their
run-owned copies before and after computation and publishes those copies as
manifest inputs. This is provenance capture, not execution from a frozen tree:
the runner still uses its explicitly selected current Python environment and
research source root. Historical snapshots remain unchanged. Retention-policy
and audit-source identities do not become numerical Refine/Fly cache keys.
The complete fixed-grid handoff module passed all 18 parents (39 successful records, no skips)
on the composed successor in 7.214 seconds, including actual source-table extraction, isolated
canonical module origins and the missing-policy negative. The private checkout's earlier 14
historical-evidence skips remain a separate run; no native solver or new scientific qualification
was exercised by this repair.

### Standalone Lua provider selection

Software-only joint preparation accepts the pinned standalone `lua5.1.exe` provider
alongside `lua`/`lua.exe`; discovery tries `lua`, then `lua5.1`, before the existing
local standalone fallback. The selected interpreter must exist and have an accepted
standalone name. Missing binaries and `simion.exe` remain rejected before voltage
projection. Voltage schedules, frozen resources and native qualification are unchanged.
All thirteen original joint-preparation parents passed on the composed successor
in 5.074 seconds (45 successful records, no skips), including missing-interpreter
and inert solver-name rejection. Final Repository acceptance remains open.


### Software Lua kernel discovery

The four IP-prism collision-fixture, distance-runner, finite-lens-contact and
local-callback test modules now try PATH lua5.1 after lua and before their
original local standalone fallback. The same selected global LUA still controls
the original skip guard and subprocess. No solver executable or vendor-adjacent
library is selected by this software-only change.

All37 original parents passed without skips (8.460seconds unittest,
9.475seconds harness), preserving110 assertion ASTs, five subprocess call ASTs
and every test method. A transparent task-only process observer captured42 actual
Lua calls, all to the pinned portable Lua5.1.5 executable with the recorded SHA.
Twelve actual-selector priority cases and Python lint passed. Inert PA/workbench
and callback fixtures, analytic contact vectors, original clocks and output
checks remain unchanged. These are plain-Lua/preparation proofs, not native
collision/trajectory/field results or scientific qualification.

The measured-source, prepared-trial and scientific-event/trajectory software checks
also discover `lua5.1` after `lua`, preserving the existing local vendor fallback.
This changes test interpreter selection only; source/cohort/clock/event identities,
historical-data skips and native qualification boundaries remain unchanged.
The combined ten modules passed all 143 parents and 274 records on the composed
successor in 71.140 seconds, with no skips. All 792 original assertions and test
identities are retained; this is software evidence, not native execution or the
complete MR/Repository gate.


### Software PA-interface Lua discovery

Five PA-interface/corridor/crop/static-binding/trial test modules now try PATH
lua/lua5.1 before their original local standalone fallback. Their existing
selected-variable guards and actual subprocess arguments remain paired. The two
real corridor/workbench native checks retain their exact SIMION_EXE opt-in guards
and bodies; a portable interpreter does not authorize either native check.

The original Lua-dependent round passed23 parents in2.550seconds. The complete
five-module round then passed183 executed parents with two explicit native skips
(185discovered;231.122seconds unittest,232.190seconds harness). All784 assertion
ASTs,31subprocess call ASTs and185test identities remain unchanged. Each software
round captured46 actual Lua process paths/hashes, all using the pinned portable
Lua5.1.5 provider. Forty selector priority cases and Python lint passed. An earlier
task-only observer setup failed before tests imported; that failure is retained,
not a production failure or a result retag. PA queries/crop/save/refine/workbench
methods remain existing inert fixtures. No solver/GUI, solved family copy, native
propagation or scientific qualification is implied.
The composed successor passed the 23 actual Lua-dependent MR parents together
with the three RF/TOF modules: 38 parents and 87 successful records in 2.808 seconds,
without skips. The other MR parents retain the private full-module evidence above;
neither of the native opt-in checks was enabled by this run.

### 完整装配 CAD 部件计划的规范归属

完整 MR＋OA／探测器／C0 的纯 `rectangle`、镜体／槽投影和 `compile_parts` 归
`msplatform.exporters.mr_cad_parts`，原 CAD 生成器只作具名调用，不保留同体或转发别名。
原二十槽电压、独立实体、冻结倾镜多边形、OA 位移和零厚参考面语义不变；
这不新增 MR-only catalog／通用 STEP 支持或商业 CAD 资格。
实际源选择、verified copy 和 live 执行审计见 [CAD 实施说明](CAD.md#唯一活动生成入口)。
剩余原生 CAD／原始曲线证据／发布生命周期仍在根入口，本切片不宣称其已完整迁入安装树。
软件、普通安装、原生及科学证据分别验收，源码提案不继承原运行 PASS。

## Explicit neutral MR geometry authority

`msplatform.components.parallel_mirror_dual_stripe_mr_tof.resolved_geometry` owns the physical
resolver and curve helpers. Geometry construction requires the selected complete OA requirements,
physical profile and profile ID; it does not search the OA project or import a SIMION layout.
The research input reader selects an explicit component-contract file and records its bytes.
Native MR construction separately calls the existing OA layout validator through
`msplatform.backends.simion.mr_geometry.resolve_mr_geometry`, retaining PA span, pitch, margin
and mirrored-grid alignment checks before generating output. Resolved MR geometry now uses
schema 2 and a physical OA view; its fingerprint intentionally differs from the former
PA-translated layout snapshot.

Current construction contexts use schema 2 and freeze the OA authority. Coverage transports that
same authority to continuation; new workpoint/screening children consume their selected frozen
record. Saved schema-1 data and unchanged fixed-field reads retain their original interpretation.
New mirror geometry from schema-1 sources without complete original OA authority is rejected;
no profile is guessed from old extents, and no historical record is rewritten or supplemented.
The existing P1 extension uses canonical physical support solids and one explicit rigid transform;
its supported relative rotation remains identity. This migration does not qualify new native
fields, arbitrary rotations, old-source mirror upgrades, TE1 or fine-domain changes.

### Installed neutral MR assembly interface

The complete resolved MR entry-face/electrode publisher is owned by
`msplatform.components.parallel_mirror_dual_stripe_mr_tof.assembly_interface`.
Accelerator-interface composition and the retained native-system geometry adapter call
that same pure implementation. It consumes explicit resolved physical geometry, retains
the actual E18 rectangular slot, shared closure/ground identities and existing topology
guards, and neither reads a project profile nor performs a native operation. The root
interface body is retired without an alias. Current physical resolution uses the explicit
OA authority described above; native PA validation remains a separate backend operation.
Retained workflow, installation and native evidence remain separate closure obligations;
the publisher does not register an empty provider or establish field or flight support.


## Recorded-study canonical provider snapshots

The IP/prism recorded-study source freezer selects its actually imported canonical
package and four policy resources, including an ordinary installation outside the
research checkout. It verifies the selected bytes into the existing logical
src/msplatform layout; it never substitutes checkout copies for absent installed
code/resources. Loaded research/common code remains bound to the explicit research
tree. Existing owned staging overwrite, scientific inputs, CSV/math, resource
policies and runner missing-core refusal are preserved. This repair changes source
binding only; its external regular-package fixture is a source harness, not new
ordinary wheel, native or scientific qualification.

The source-harness regression verifies distinct selected source/four-policy
bytes, logical snapshot paths, owned staging overwrite and missing/corrupted-input
refusal. Original failure evidence remains separate from successor acceptance.

## Installed ideal-mirror L0 ownership

The ideal planar five-electrode mirror kernel and its fixed-geometry voltage
solve are owned by `msplatform.components.parallel_mirror_dual_stripe_mr_tof.mirror_l0`.
The explicit global search, deterministic restart list and process-pool family
selection are owned by `msplatform.workflows.mr_design`. Research inputs and
contract selection remain explicit in the hardware-candidate author entry.
The original first-upward turning-point rule, terminal-image convention,
three local period slopes, bounds, seeds and selection status are preserved.
L1 screening and native finite-thickness/slotted-field qualification remain
separate; installed L0 mathematics does not qualify a native mirror.
The existing PowerShell research runner records checked live source snapshots;
it does not claim to execute those snapshots as a separate frozen environment.

The restart workflow preserves caller-supplied values for its four numerical-library
thread controls; missing values retain the original one-thread defaults and the
selected values are recorded. This grants no host or tool-path discovery.
Both the ordinary wheel and sdist-rebuilt wheel execute the kernel and an actual
bounded ProcessPool restart outside checkout. The installed checks verify parent
and worker module origins, original numerical vectors and missing-module refusal.
This is installed software evidence, not full-MR, native or scientific qualification.


## Stripe L0 scientific ownership

The sole Stripe L0 mathematics is now the installed MR component
`msplatform.components.parallel_mirror_dual_stripe_mr_tof.dual_stripe_l0`.
Its pure response analyzer resolves the same explicit contract and OA physical
requirements/profile once. Native operating-seed consumers call
`msplatform.workflows.mr_design.analyze_native_dual_stripe_l0`, retaining the
original bias/energy → native OA envelope → physical widths → mapping order.
The backend import is lazy; ideal quadrature, spatial-return roots and narrow
verified converging-target analysis do not acquire native authority requirements.
Four research runners retain their original audited-live execution and flat
source-copy identities: the Stripe row changes owner and mr_design is appended.
This ownership move does not qualify finite fields, native transport or scientific
precision; source, installation and native evidence remain separately scoped.
The retired root body has no alias.


## Standalone PA representation ownership

The sole schema2 standalone operating-PA identity/cache adapter is
`msplatform.backends.simion.operating_pa_cache`, delegating the unchanged existing
PA-family cache. The byte-identical native composer is selected through the
existing SIMION backend resource resolver. Component voltage/TE1 science, the
binary PA composer, scalar adapter and long-path/immutable-source owners remain
unchanged. Local field preparation freezes the same selected backend Lua.

Completed materialized-response readback verifies the original small plan record
and reconstructs its scientific commands with the recorded generator location and
SHA. It neither opens a retired generator nor substitutes current code; all other
source/member/coefficient/support/output checks remain. New planning resolves and
hashes the actual current resource. Focused cache/readback, actual stock-Lua,
cold-snapshot and dependency-freezer checks cover this boundary. Both ordinary
wheel and sdist-rebuilt wheel clients verify the installed owner/resource and
missing-resource refusal. The unchanged retained original tiny fixture reads
back with its complete original result and cache key, without generator lookup.
These are software and installation evidence; no new native composition, field,
flight, GUI or scientific qualification is claimed. Original failure evidence
remains separate from successor acceptance.


### Prepared-joint field consumer ownership

The prepared-joint field crop, candidate binding and native projection now use the
installed SIMION prepared-field adapter, which consumes the existing COMSOL binding owner. The shared collision topology
projection uses the canonical SIMION structural seed resource. The trial lifecycle
remains in its existing research entry; this slice does not establish full prepared-joint
installation, native field or flight qualification.

The SIMION collision-occupancy header and coverage checks are owned by
`msplatform.backends.simion.collision_overlay`. The native static-field provider
and installed COMSOL asset verifier consume that implementation; the verifier
no longer imports a nonexistent COMSOL-local provider. Mode -1/-2, planar
symmetry, bit-28 and coverage rules retain their existing meanings. Synthetic
asset-verifier tests stub source materialization explicitly and do not qualify
complete field materialization or native assets. The native-static PowerShell
runner still executes from its repository context; its recorded source copies
are audit evidence, not proof of frozen execution. That remaining lifecycle
boundary stays open within P4.

### Interface field coverage ownership

The first-match IP fine-field coverage and native gradient-halo check used by
interface audit preparation is owned by the SIMION prepared-field backend. The
root audit preparation remains its consumer; this does not qualify a native field,
flight, or physical match.

### Installed measured-source preparation

The measured population, constructed centroid and scheduler ordinal slice are prepared
by `msplatform.workflows.prepared_joint.source`; IP/MR source binding and connection
policy are owned by `msplatform.workflows.prepared_joint.ip_mr_connection`. The
source runtime is an installed SIMION resource. The real accelerator-interface and
prepared-joint consumers use these implementations; the remaining trial lifecycle
continues in its original entry. This does not establish native flight or qualification.


### Explicit MR component provider and mechanical composition

The selected Candidate `accelerator.gap_2_mm` is a physical design input. Contract
validation preserves it when the numerical mesh changes, retaining the compact
acceptance bound, reference-voltage and downstream-focus checks. Calling
`derive_compact_accelerator_acceptance_design` without an explicit selected gap
still performs the original mesh-aligned design selection; that is a new design
choice, not a fixed-geometry convergence result. Historical quantization records
and saved designs remain unchanged. The Candidate scalar and the separately
selected canonical OA profile are distinct authorities and are not equated.
The isolated old/new software witness retained the exact original strategy,
focus and placement, and passed four parents and seven subtests in 35.215 seconds
with source, checkout and overlays frozen. This does not qualify off-grid native
representation, new fields or trajectories. After integration, the complete
assembly-interface module, fixed-design regressions, focus case and actual Changed
selector passed 12 parents and 34 subtests in 92.644 seconds with all 2,914 source
paths and checkout unchanged. Ordinary-install and broader regression for this
successor remain pending.

The MR provider resolves the complete selected candidate contract and explicit OA physical
requirements and profile into one full physical design and schema-3 mechanical interface.
Four Stripe bodies remain separate physical groups; the existing two paired voltage-drive
settings do not assert physical wiring. Mirror closures, physical grounds, prism shields,
detector and the actual entry aperture remain in the resolved design. The component group
names do not assert native electrode numbering. The current plan-5 OA-to-MR mechanical
consumer re-resolves the selected authorities and compares the complete physical geometry;
plan-3 source and interface interpretation is retained. The backend retains the existing
OA support and PA placement checks. This mechanical slice does not create a complete native
electrode-binding artifact or qualify fields, Fly, CAD, historical runs or full MR.

For a static-field overlay, plan 5 requires the complete selected field geometry to
equal the explicitly re-resolved provider design, including nonphysical metadata. A
difference is refused; no historical geometry is reconstructed or supplemented.
Existing schema-1 field geometry was used with the retained plan-3 path, which does
not establish its equivalence to a new plan-5 source. Use plan 3 for that historical
interpretation, or select a field with a compatible complete plan-5 authority.

The complete-cohort collection gate is implemented by `msplatform.workflows.oa_mr.collection_gate`.
The OA–MR executor verifies the frozen helper and package before invoking that module in isolation;
missing or changed frozen code cannot fall back to the author checkout. The migrated scientific body
and cohort/flight evidence are unchanged, and the old project implementation has been removed.
Six focused Main tests passed (18 successful records; 18.357 seconds), including the actual public
freezer, executor boundary and missing/tampered dependency refusals. Direct-wheel and sdist-rebuilt
wheel probes passed outside the checkout (84.453 seconds; 518 runtime payloads per arm), checking
installed origin, accepted/invalid cohorts, missing-module refusal and unchanged installed payloads.
Both test runs retained frozen source/index identities. These are selected software/installation
checks, not full ordinary-install, Repository, native flight or scientific qualification.
