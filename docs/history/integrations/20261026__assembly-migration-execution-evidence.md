# 统一装配迁移与公共执行机制阶段证据

> DOC_STATUS: ARCHIVED_READ_ONLY
> 归档日期：2026-10-26（北京时间）；状态截点：2026-10-25 21:41 UTC。
> 当前入口：[统一集成状态](../INTEGRATION.md)、[集成导航](../../README.md)。
> 归档范围：状态页收缩前的完整实施过程；不是总goal完成报告或新的执行规范。

本次里程碑是直属装配入口、共同场复用／恢复及首轮OA局部有限脉冲SIMION执行已经形成可追溯链，
将反复尝试、旧门禁和失效操作叙述移出当前页。下列原文中的“当前”“下一步”和旧CLI均只按各段
记录时点解释；后续执行应回到当前入口，退役源码不恢复为活动能力。原始负结果、run身份和资格边界保留。

截至截点，14项目标尚未完成。040326已完成原N=100 SIMION基线及保存工作台默认回放，100个停止
原因仍为unknown；042142沿041645二次恢复只补CPT，没有新Fly、ES、mesh或Refine，仍为RUNNING，
尚无已保存raw粒子MPH，不能报告CPT成功或可用checkpoint。GUI已由用户明确暂缓。
共同静态场235338完成原生求解及115点比较，011244重开恢复成功；数值等价未获，014055诊断PA不替代原基线。

截点门禁补充：`migration_l1_pulse_runtime_cad_geometry_20261026.log`整轮为failed，唯一失败阶段为
多极杆458项中的package夹具缺`artifact_run_dir/result_dir`；修复后focused 6.310 s通过。
integration 572项及oaTOF 453项各自通过，不把它们拼成L1 PASS。其后公共ancestry重构不在该轮全覆盖：
共用Toolhelp父表已有回归，非相关protected进程unknown污染目标完整性的问题仍在窄修；
COMSOL持续预算／critical保护缺口只是审清，尚未接线。

旧arm编排3份生产文件、consumer与13项专属测试已退役；保留的9项源测试及新pulse联合32项
25.017 s通过，项目`run_fixed_particle_retrace.m`仍有完整仪器消费者。GeometryOnly与动态20环CAD
API已实现，M Unit、真实几何保存／重开及CAD未运行；18文件纯作者闭包准备不是长期科学证据。

归档前正文共2545行；规范化LF文本SHA-256为`2AB98E2C32EFACFDBA27B87C03351A7D89C6924DE45D3C04DAD27D80EFBCFCEF`。下面保留全部正文，
只将原一级标题改为归档节标题，并重定位本地Markdown链接；原文自链接仍指向本快照相同节。
正文中的旧CLOC是2026-10-25 20:56:33 UTC快照，早于上述ancestry及arm退役，不能冒充最新规模。

## 归档前状态页原文

返回[集成入口](../../README.md)。本页只记录直属`integrations/`能力的实施状态；组件自身物理结论归各PROJECT，
既有链路证据在完成切换前仍归原状态页。阶段依赖见[迁移计划](../../../docs/ROADMAP.md#统一组装迁移计划)。

## 当前边界

当前总目标按用户确认的14项执行，完成条件包括多实例真实场与驱动、冻结范围与源／时钟分离、
公共波形、独立工作场复用、阶段／完整批恢复、执行收尾、冻结闭包、粒子表与批次、回放差异定位、
同义统计与场对照、碰撞生命周期、真实链及适用GUI／CAD验收，以及替换后删除和最终门禁／提交。
公共化只处理有实际消费者且语义相同的实现；科学时序、阈值和资格留在工作流。以下局部通过不表示总目标完成。
2026-10-25独立只读审查已核对公共RF／边沿、冻结闭包、标准粒子读取及批次合并、场样点配对和HS1生命周期的实际消费者，
未发现这几项尚需新增的高收益阻断提炼。剩余回放对象、直方图／KDE峰宽和空群统计语义有实际差异，
不为减少表面重复强行合并；该审查不关闭原生、多实例、跨后端及GUI／CAD验收。

适用几何验收已专项核对：本次新增OA侧孔及改过的CAD消费者仍须沿
[oaTOF候选CAD链](../../../projects/single_reflection_oa_tof_mass_analyzer/docs/CAD.md)完成同源候选MPH／STEP／SolidWorks对照，
不能仅以未Formal免除。共同边值问题还须相同候选MPH的原生保存重开及适用GUI Compute检查；
旧封闭OA／25组件的GUI和CAD证据保持有效于原资产，不能覆盖新孔。此任务不自动晋升Formal或要求为全部N2／N3尺寸新增制造基线。

公共L1／L2阶段日志已改为沿唯一文件逐行写入并刷新，START行直接给出LOG_PATH，
删除整个阶段的内存文本缓存，完成后有序回放及资源准入保持。完整真实子进程模块9项64.957 s通过，
覆盖首行可在进程仍活时读取、成功／异常输出、writer关闭、实际child路径和既有编码／失败收尾。
该改动不重启门禁或求解；已加载旧函数的L1随后按原行为自然通过，不能把它当作新实时日志的运行证据。

公共SIMION执行器已修复`warn_single_worker`绕过持续critical危险保护的问题；首批观测及批执行共用原危险计时，
普通压力仍只告警，瞬时恢复重置计时，处置沿原有owned进程、有限恢复与失败收尾。
完整资源模块52项180.843 s中51项通过；唯一新owned停止节点实际已终止目标，但测试清理已退出进程使宿主隐式返回1。
仅修正测试收尾后该节点3.057 s复验通过，Ruff及PowerShell AST通过；不将定向复验拼称整组重跑。
日志为`multi_instance_phase_author_20261025/critical_memory_protection_{focused,module,owned_recheck}.log`；
首轮受限权限下taskkill拒绝也保留。这是受控遥测及真实睡眠子进程证据，不是实际求解器内存危险实验。
随后L1中的完整多极杆公共回归457项328.445 s全部通过，包含当前资源模块；公共合同696项262.503 s也通过。
本轮L1 `migration_l1_after_owned_jvm_archive_20261025.log`已自然结束为failed，仅oaTOF阶段失败：447项中两项旧保存顺序断言失败和一次Candidate子进程失败，
其余阶段通过，包括完整直属集成534项1495.420 s；不能将这些局部通过称为L1通过。后者在单节点、同发现上下文及完整Candidate模块71项142.865 s中均未复现，
没有依据补依赖或猜测根因；完整日志为`candidate_module_stderr_diagnosis_20261026.log`。
L1结束后，原compiler非零分支已补实际exit code／路径／末4 KiB stderr；两个旧断言按prepared及solved真实分支检查，
保留求解前prepared保存、求解后solved保存及仅导出的约束。Candidate与adapter两完整模块77项97.997 s通过，
日志`candidate_and_paired_stage_modules_public_gate_20261026.log`；没有加依赖或擅自认定原偶发编译错误已修复。
公共COMSOL启动器也已收敛本次已退出launcher的新增JVM日志运输；不扫描、不重哈希、不改字节，不覆盖旧证据。
完整资源阶段模块35项56.393 s、原分类器、Ruff及AST通过，日志`owned_jvm_log_public_transport_module_20261026.log`。
普通及hidden模式用真实受控子进程验证日志收尾，不冒充供应商崩溃复验；该改动仅对后继入口生效，235338仍消费原已加载入口。
后继完整L1 `migration_l1_after_real_field_recovery_20261026.log`已自然通过：
`CHANGED_GATE=PASS PYTHON=3.11 CHANGED_PATHS=954 FULL_SCOPE=False`，含直属集成535项1801.756 s。
它覆盖上述日志运输、Candidate错误呈现、原生计数及retention／显式模型消费修复；不是FullScope、L2或商业资格。
paired owner完整模块18项49.721 s及真实011244恢复owner也已越过修复点；本轮未重复求解已完成的大型模型。
该轮之后又修改了源路径解析、共享时钟／Lua格式器、IOB验证回调及新增窄脉冲工作流；上述L1不覆盖这些后续源码。
后续针对性回归见下文，最终稳定L1／L2、适用GUI／CAD与提交仍须完成。

大型模拟按用户2026-10-25要求逐条推进并闭合：110745单反射N=100链已完成缺失场、Fly、
默认回放及成功发布，同closure原生重复Fly也已另行闭合；GUI按用户最新决定暂缓，缺口保留。
后继192240的81粒子IP→MR也已成功闭合；共同场SIMION求场及审计恢复已由220837完成，该轮COMSOL在主机重启时中断。
后继233735复用发布PA后在COMSOL几何／电位设置阶段遇到原生JVM崩溃，已正常failed／ready封存；
经235103同输入构造诊断自然通过后，235338已完成真实建网、prepared保存、静态求场、solved保存及115点比较；
该owner仅在终态发布因重复retention失败。修复后011244已成功复用原已解MPH／PA并完成重新导出和发布，
两份采样表均与原run逐字节一致；共同场功能与已解模型重开恢复已闭合，数值等价仍未获得。其他代码收敛、合同检查、输入准备、预算核对、
只读审查和文档整理可以并行；准备步骤若会触发新求场或大型Fly，则按大型模拟顺序执行。
同一链内的独立粒子批次仍由公共调度器按实测资源并发，不人为串行。准备与门禁同样接受公共资源准入，
不以全并行为目标；复用已有PA和有效证据，不为并行准备重复求场或制造无必要的载荷副本。

单反射生成Program的同closure重复初始化已修复：响应spec保留首次打开的RF／pulse PA引用，
每run重建实例路由并沿用已有四类粒子／诊断状态复位，不再次打开同一响应；现有RAM网格匹配检查保留。
parent／fine两项真实Lua回调回归14.211 s通过，覆盖引用与open次数不变、原ID77／birth 2.5 μs及速度恢复、
RF不变、第二次终态重新记录且不重复发出，以及cached PA形状不符拒绝而不另开文件。
这轮是生成Program在Lua夹具中的生命周期证据；后继191009已完成下述N10原生Repeat Fly，GUI仍未完成。
110745消费旧冻结生成器，此修改不反向授予该run重复Fly资格。

后继`20261025_191009__test__simion__repeat-fly-n10`已沿公共准入完成当前正常编译Program的原生同closure重复Fly，
使用原110745首批10个ID、原FLY2字节、几何、场、时钟及科学控制；另90个母群成员本探针未执行，不记为新损失。
同一官方`segment.flym`连续两次`run()`均返回，各有完整10次出生与原生终态；
原生整次命令记录20 splats／110.62 s，不补造逐轮vendor完成行。公共事件／终态比较passed，differences为空，
沿原32 ULP序列化口径；冷启动5份PA、首轮结束9份、第二轮开始及结束均为同9条路径。
userdata相等仅记录为附加观察，不作为供应商未承诺的对象身份判据。
build及独立reopen也通过声明点核验；未复制PA、Refine或Fast Adjust，全部九份工作场与六份seed在消费期间受护。
进程树峰值15,142,125,568 B，公共观测115.309 s，无预算告警，运行已封存ready／success，保留29,624,338 B。
资格仅为原10个执行ID的同closure生命周期及重复运行一致性，不增加N100、GUI、边界场连续性或物理性能资格。
两份一次性脚本已与run输入逐字节身份匹配后删除scratch原件；冻结源码、两轮原始日志及重建输入保留。

原生优先级／占用验收已接入既有独立IOB reopen，沿官方`wb:find_at`逐点记录结果，
取点来自冻结物理采样和数值域；原终态及相邻格点仅观测，不凭instance编号命名碰撞实体。
WorkbenchOnly与实际批次Fly前共用同一完成事实解析；缺失、重复、截断或数量不符的标记失败关闭。
原笼统`actual_field_overlap_validated`已替换为范围明确的`native_priority_occupancy_validation`，
只表示声明点的原生选择与占用，不表示动态RF／pulse、连续性或整个空间正确。
首轮失败复核发现空checks的`.Sum`遮蔽原marker拒绝，现显式保留0计数与failed状态；
最终公共GATE 13项77.605 s通过，覆盖实际Lua脚本的API夹具行为及两个执行入口的失败收尾、资源释放和未Fly。
日志为`direct_pa_iob_mechanism_20261025/diagnostic_priority_occupancy_final_public_gate.log`，
先前两轮失败日志保留，夹具回归不代替原生点检。

新`20261025_171910__analysis__simion__single-reflection-priority-points`已只读重开110745保存的五实例IOB，
沿公共准入及八份源文件保护执行804点查询；未复制PA、Refine、Fast Adjust或Fly，原生耗时8.96 s、
进程树峰值4,516,696,064 B，无预算告警。104个带预期点中4点失败：parent的grid1、intermediate2、grid2及
entrance_refinement的grid1；700个终态及邻格点只作观测。原生stdout／stderr完整保留，run已封存ready／failed。
失败集中于零厚度栅面及parent最后节点，仍须区分整数PA节点采样、世界坐标查询和域边界选择语义；
不通过移动几何、扩大容差或删除异常点制造PASS，不据此把100个终态归因于真实机械遮挡。
提供者的零厚理想栅明确为参与求场的电极节点且原生允许粒子透过，不能把整数GU节点flag与
世界坐标连续碰撞占用视为同一事实。
`20261025_172729__analysis__simion__single-reflection-priority-points`补录官方双向变换、源节点及
`inside_wc`，未改变原判据，仍以同四点失败封存。四个原整数GU节点的电极flag均为true；
intermediate2世界坐标反变换为1612.0000000000002 GU，grid2为父PA最后节点6350 GU，
该出口点inside_source=true而Workbench选中instance 1，不能由包含关系直接假设选择父实例3。
诊断增强的完整FourSlotIobTests沿公共GATE完成8项4.206 s，日志为
`direct_pa_iob_mechanism_20261025/native_source_node_diagnostic_public_gate.log`。
随后正式采样编译将零厚栅标为`ideal_sheet`，全部97个样点显式声明源整数节点电极判据；
内部实体与透明理想栅分别核验世界碰撞占用，数值边界保留世界查询观察且不凭包含关系伪造实例选择。
source-node失败与世界判据共同决定同一个point结果；边界点仍必须通过源节点检查，未删除样点或移动GU。
公共GATE首轮14项5.245 s中13项通过，一处缺点输入fixture顺序修复后精确节点1项1.648 s通过；
日志为`direct_pa_iob_mechanism_20261025/native_source_node_semantics_public_gate.log`及
`native_source_node_semantics_recheck_public_gate.log`，原失败保留。
`20261025_173617__analysis__simion__single-reflection-priority-points`已以新冻结实现只读重开原110745 IOB，
104个带判据点、97个源节点全部通过，700个终态邻域点仍仅观察，run已成功封存ready。
新审计设计由原冻结组件及request重编；按发布JSON表示逐字段比较，仅上述四个样点的kind改变，
GEM身份继承原冻结记录，不重建几何、场或源；电压、网格、ID及原GU严格不变。
本次无PA复制、Refine、Fast Adjust、Fly或GUI，不授予外边界场连续性、动态RF／pulse或具体终止对象资格。
后继`20261025_175629__analysis__simion__single-reflection-gui-review`沿公共轻阶段及八份源保护启动已安装SIMION，
准备直接只读加载原工作台；两套受支持电脑控制工具均捕获超时，索引点击因缺少坐标几何未执行。
只取得空工作台、0 MB PA RAM的可访问文本，没有加载原IOB、Refine、Fly、Fast Adjust或保存。
GUI已通过正常退出确认关闭，公共进程等待、失败封存及源／资源释放完成，run为ready／failed；
具体工具错误和未完成检查保存在`results/gui_observations.json`，不把进程启动或空界面算作GUI验收。
一次性owner已冻结进run输入并删除scratch原件；该时点GUI／Repeat Fly尚未完成，后继191009仅关闭N10重复生命周期缺口，GUI继续开放。
后继`20261025_181159__analysis__simion__single-reflection-gui-review`沿同一冻结owner和公共源保护重试，
通过SIMION官方Command加载原IOB、进入真实View；PAs页列出原五份相对路径，显示可编辑的首实例位姿，
PA RAM为5552.849 MB。按本机官方geometry_optimization示例的`simion.printer`／`simion.print_screen()`
取得`results/gui_view.png`；这是供应商真实图形导出，未自建系统截屏，也不代表已检查全部参数页。
打印长绝对名称被拒、相对名称打开失败后，仅采用已核验指向同一新run结果目录的Windows原生短名称拼写，
没有建立链接、复制PA、修改旧IOB或临时切换其工作目录。实际IOB和GUI路径另由`gui_paths.txt`记录。
后续电脑控制工具无法激活该窗口，未完成纵向／3D视图及Program／FLY2参数页检查；本轮仍封存ready／failed，
保留上述部分证据与`gui_observations.json`。正常关闭请求未使会话退出后，仅清理精确PID／创建时刻匹配的本任务只读查看器，
其间未Fly、Refine、Fast Adjust或保存科学编辑；源保护和主机许可由owner在进程结束后释放。
退出后600 s阈值告警不是清理原因，`logs/owned_gui_cleanup.json`记录了失去UI控制后的查看器清理。
后续GUI重试在进程创建前被自动审批拒绝，没有产生新run或查看器；用户随后明确选择暂缓GUI、继续其他验收。
上述GUI缺口仍保持开放，不以原生点检、默认回放或同closure重复Fly代替；总迁移goal继续执行。
另核对110745三份冻结Program及原生日志：观察窗口关闭、terminate_after_pulse=0、pre_pulse_time_series=0；
100个终态年龄50.655049～51.555376 μs，均远小于200 μs主动年龄上限，发生在原脉冲开启后0.842149～1.020945 μs。
日志无timeout／window_complete／screening_terminal，三批原生分别闭合10／50／40 splats；
因此排除上述Program主动窗口／年龄停止误记为non_detector，仍未识别具体碰撞对象或供应商细分停止原因。

OA→MR恢复分支已沿实际PS阶段、公共完整单元恢复、guard、日志合并及终态writer完成六分支回归，
覆盖零待飞、只执行缺失批次、全新运行、clock变化、显式GUI缺PA及待飞缺PA；1项16.871 s通过。
完整runner模块40项59.803 s中38项通过、两项旧fixture失败；补齐native分支变量并对三个实际vendor入口
检查进程登记后，两个失败节点定向重验0.999 s通过。生产行为未因夹具修改而改变。
日志为`iob_path_probe_20261024/oa_recovery_fixture_recheck_20261025.log`、
`oa_recovery_complete_runner_20261025.log`及`oa_recovery_complete_runner_fixture_final_20261025.log`；
vendor边界使用惰性替身，不授予完整owner、真实Fly或GUI资格。

原生场元数据与实际载荷消费边界的最终公共GATE为59项113.760 s通过、2项历史PA退役跳过，
覆盖完整provider模块及精确退役节点；日志为`iob_path_probe_20261024/native_provider_fixture_final_public_gate.log`。
真实97粒子保留结果另经1项49.492 s验证：在精确PA／surface路径不可用时，实际分析仍完成，
`prism_phase_space.csv`与`timed_spatial_clouds.csv`逐字节一致；真正原生消费验证仍拒绝缺失PA。
该测试以路径访问故障注入保护旧run，不移动或删除源PA，不模拟科学分析，也不宣称全部分析输出均逐字节对照。
日志为`iob_path_probe_20261024/real_native_97_postprocessing_public_gate.log`；全仓L1／L2仍需最终稳定版本验证。

OA→MR布局消费已去除MR必须位于父装配原点的假设：现有公共`relative_transform`把两实例的直接位姿
投影为OA→MR，现有求解器只约束支持的相对identity rotation；MR几何、场网格、源及诊断仍在提供者局部frame。
完整父plan保留MR→assembly直接位姿，不增加同义metadata或另一份输出表。两个focused回归70.679 s通过，
覆盖实际提供者／IOB原点、完整源出口reference在共同平移和精确90°共同旋转下序列化一致、父plan不改、
非精确共同旋转的binary64表示误差及真实相对180°旋转拒绝。该轮直接运行，未先进入公共GATE；
原预计短回归在当前负载下耗时较长，后续完整物化验证须经公共准入，不以本轮替代完整门禁。
完整物化FLY2／operating Lua字节对照已由公共GATE完成，1项15.577 s通过并正常释放租约；
日志为`iob_path_probe_20261024/oa_mr_relative_pose_materialization_public_gate.log`。
IP及prepared_joint随后也已去除MR父装配原点假设：同一公共相对变换解析IP→MR，
实际CSG、field registration、handoff、finalize和联合飞行准备统一消费MR-local；父plan仍保留原直接位姿。
三个完整模块经公共GATE完成39项23.693 s，覆盖真实完整提供者的GEM、97粒子源伴随文件、母群、
clock及实际finalize绑定在共同平移／精确90°共同旋转下不变。
末次MR-local目标frame拒绝检查在该轮导入后补入，另沿公共GATE单独补验1项0.803 s通过；未重复全组。
原39项结果在工具输出，`ip_mr_relative_frame_public_gate.log`仅记录准入与释放；
单节点完整输出为`ip_mr_local_frame_boundary_test.log`，不把transcript冒充完整unittest日志。
当前真实CSG仍只接受固定native相对轴置换；非精确共同旋转的binary64残差及不支持相对姿态明确拒绝，
没有钳零、补偿位姿或PA旋转／复制。以上不增加原生Fly、任意父姿态或GUI资格。

单反射及共同OA场准备也已移除OA必须位于父原点／固定父frame名的限制：父plan保持原位姿，
派生`native_frame_id`取OA提供者局部frame，几何、物理场采样、普通源及Program交接面共用公共相对变换。
recorded pre-pulse源额外冻结成功winner唯一绑定的`source_provenance.json`，明确核对实际状态frame及clock，
不再要求父frame名或OA绝对位姿相同，不明来源仍拒绝，不对原状态另做变换。
公共GATE首轮69项40.351 s中68项通过，新增Program回归捕获父frame交接点直接当native点的真实缺陷；
改为提供者局部机械端口直接投影后，完整Program模块及原失败节点20项9.437 s通过。
同轮已覆盖完整193652真实提供者、100母群、双GEM、场设计、普通／已记录源、时钟及全体平移／精确90°旋转。
原父plan各自保留，native载荷相同；几何JSON因新增派生frame及父plan差异不宣称字节相同，也不据此重求场。
Agent 0另用191009冻结helper重编原真实首批，原Program SHA／metadata／FLY2严格不变，0.623 s通过；
日志`frame_actual_original_program_identity_20261025.log`，无PA读取或新的Fly。
公共相对变换对两个完全相同pose直接返回精确单位变换，避免已在OA-native的源经矩阵往返产生舍入位移；
实际非整角复现及完整15项数学回归0.002 s通过，Ruff通过，日志`common_relative_self_identity_20261025.log`。
这些源码回归不扩大为任意相对转角、任意巨大浮点平移或新GUI资格；后继变更仍须新的联合门禁。

公共Complete-FailedRun已在任何写入／保留处置前核对现有manifest身份，已有终态则告警保留，
checkpoint和未发布运行仍正常失败关闭；不重复核验大型载荷或按异常字符串猜发布状态。
完整PowerShell支持测试24.716 s通过，真实覆盖success发布后容量异常、坏／错身份manifest拒绝、
checkpoint及未发布失败；相关Python失败发布模块5项4.564 s通过。测试临时范围与执行alias已清理。

2026-10-25冷却前端的入口关闭／释放两处边沿限步直接消费既有公共`cap_before_edge`，
Program通过已有回调传入同一波形模块，删除本地重复减法和min计算；没有新增波形引擎或冻结依赖。
两个完整模块35项22.906 s通过，覆盖边沿前／恰在／边沿后及注入结果实际消费，保留HS1、core、边沿的
调用顺序、粒子种子和唯一时钟。该项减少算法维护点，不单独宣称总代码量下降或新的原生资格。

活动波形消费者后续只读审查未发现值得新增公共API的重复数学：有界矩形`[on,end)`仅在既有
`single_flight_pulse_hook.state_at`实现，local／cooled／full已经共用；IP的`u²(3−2u)`抬升只有一个实际消费者。
MR固定时刻或逐粒子退出触发的场门控与有界电压脉冲语义不同；冷却及IP的单个`time>=edge`比较也不值得另造包装。
这些器件时序保留原边界，不为提炼增加调用、配置或冻结依赖；正弦／余弦RF与公共边沿限步继续沿已有实现。
该审查不授予跨后端波形、有限边沿或新的原生Repeat Fly资格，适用验收仍须分别闭合。

共同样点一一配对及RMS归一化已从oaTOF移至`common/analysis/field_comparison.py`，三个仪器分析消费者和
成对静态场工作流直接调用，旧项目模块及仅有镜像测试消费者的`convergence_decision`删除，无兼容转发。
两个纯函数与原实现算法相同；四个分析模块23项3.599 s、成对静态场完整11项34.413 s通过，含真实脱仓准备。
样本选择、单位及资格阈值继续归科学合同；成对工作流仍消费OA静态采样合同，未宣称完全消除器件分析依赖。
回放比较器经审查暂不整体合并：各自按事件、终态、表行或日志配对，容差与科学含义不同，统一会增加分支。
主要FWHM消费者已使用公共peak_metrics，直方图诊断与KDE定义不同，不为统一而改变指标。

2026-10-25 HS1生命周期适配收敛至`common/simion/collision_hs1.py`；从IP functional原样迁移函数，
IP和冷却前端直接调用公共实现，冷却源码闭包删除IP functional依赖，公共模块沿现有依赖清单冻结。
无新runner、碰撞模型或种子协议。小fixture及095324保留的官方完整原文两例适配输出逐字节相同，
IP functional与cooled frontend两个完整模块55项22.751 s通过；Ruff、绑定及差异检查通过。
追加真实Freeze→脱仓准备回归1项7.362 s通过，明确核对冷却snapshot含公共collision_hs1.py且不含IP functional.py。
上述逐字节对照只证明迁移不改变适配文本；没有新原生飞行或GUI资格。
完整L1的公共host scheduler、adapter、LiveLink进程阶段及SIMION公共回归已各自exit0；common_contracts为
689项176.478 s、11 failures和1 skip，失败均为已登记冻结依赖未路由到直属集成门禁，不能宣称全套通过。
依赖清单与catalog重复维护是已确认根因：现由catalog的runtime_dependencies_path引用已有schema 2清单，
公共Read-GateCatalog展开309项来源及清单本身为精确匹配，删除24个重复exact和重复有限正则，保留其余必要路由。
当前L1另发现multipole公共夹具1 failure／1 error，以及八极杆两项过时机械variant预期，均保留原失败证据；
生产资源／物理阈值不因此放宽，分别作夹具边界与新profile预期修复。
资源夹具4项最终定向回归17.210 s通过：真实采样发现worker后才释放launcher，并凭精确PID／创建时刻等待自然结束，
保留原1.5 s断言；完成调用夹具使用真实UsagePath并补phaseDirectory，不改生产观察或预算。
八极杆完整35项18.438 s通过，精确纳入既有双端贯通机械variant并实际核对端面／法向／壁厚及驱动／源不变。
IP完整门禁原309项94.466 s有5个error，实际根因为源码按模块名重复冻结同一test_diagnostics.py。
准备器现按解析后的源码路径去重，排除明确测试文件，既有公共freeze_file语义不改；新增别名准备回归后完整310项98.812 s通过。
完整test_verify_changed 38项126.829 s通过；真实PS解析与PlanOnly覆盖整个库存、原遗漏路径、新增fixture依赖，
缺失／未知库存或缺来源失败。Ruff、PS解析与差异检查通过。
原`migration_l1_full_ip_interface.log`已终态exit1，失败仅common_contracts、multipole_common、八极杆及IP四阶段；
其余包括完整instrument assembly integration阶段均exit0。以上相应修复完成后，当前稳定源码已重新提交唯一公共L1，
日志为`migration_l1_public_mechanisms_revalidated.log`，不把定向重验或原轮其他阶段通过当作最新完整L1通过。
该轮现已结束：集成498项1067.027 s全部OK，但随后租约释放因保留进程PID12588的创建身份不可读而失败；
公共合同691项192.712 s另有3项CLOC测试因执行上下文不能写C:/tmp失败、1项明确跳过。
其余已执行阶段exit0；完整L1仍为失败，不修改调度保护或放宽测试。公共合同在正常权限上下文沿同一catalog
阶段重验，证据写入`common_contracts_normal_context_recheck.log`，结果另行核实。
该正常权限重验在字段比较模块移动而依赖库存尚未同步的中间窗口失败（653项、仅catalog初始化错误），
不作为稳定快照结论。库存稳定后同一公共阶段重验691项182.582 s通过、1项明确跳过，租约正常释放；
证据为`common_contracts_stable_inventory_recheck.log`，原3项CLOC权限失败未再出现。

2026-10-25本轮重新核实013824运行时，原生PID 91160、owner PID 101200及工具会话2478均已不存在；
原公开runner日志仍停在pa_refine准入，run_manifest／summary仅有初始化checkpoint，没有完成事实。
完整L1原日志仍停在等待3752 s，当前未检出原进程，不能继续表述为已确认在途或已通过。
本轮未重启、重飞、重求场，也未改写这些run；现有PA和中间产物保留，后续须先沿公共机制核查事务与恢复身份。
只读核查该pulse父场事务D9BA906D…：仍为building、无inventory或published generation，payload为空；
仅build-scratch/working.pa0保留3,559,100,596 bytes。它不是完成PA或已证实的求解器checkpoint，不能直接当作可复用场发布。
后续正常权限进程观测再次确认原PID和绑定精确run／alias／事务的进程均不在；沿公共owner
`seal-stopped-payload`封存013824，科学manifest／summary仍为checkpoint、不回写failed，原文件不改。
ledger为ready/rebuildable_payload并pin，3,644,945,168 B／204文件；停止观测与公共seal返回值保存在
`field_recovery_20261025/`，新运行须显式冻结这些小证据。四个已发布carrier／RF成员继续复用，两个pulse须重建；
跨运行事务producer交接正在现有公共advance边界实现，未因此把partial冒称已完成资产或启动新Refine。
公共producer handoff已沿原advance实现，保留旧owner／producer并登记新责任，partial仍返回build，
并发接管及账本更新中断重放通过；没有第二缓存、runner或恢复状态机。实际旧checkpoint的初始化配置记录
与后来正常补齐的run_config不同；当前完整cfg仍精确匹配原事务producer的SHA7FA37C…，不是任意漂移。
公共停止收据现绑定停止时run_config；原manifest／summary保持原字节，普通终态来源继续沿manifest核验。
两完整公共模块154项46.675 s通过，含停止后cfg漂移拒绝及旧manifest不改。实际013824已幂等再seal取得新收据，
没有写入旧run；整机初态恢复作者直接引用原100行CSV，其字节身份与原物化收据一致，不再生成随机源。
现有continuation已显式冻结stopped receipt和按domain/member路由的事务record，只首次begin向公共advance运输handoff；
后续verify／publish沿新owner正常执行，不重复handoff。公共层独享状态与责任交接，工作流没有另建恢复状态机。
两个完整准备／场阶段模块61项187.722 s通过，公开PrepareOnly冻结闭包及原脱仓／失败路径另2项25.576 s通过。
正常准备将receipt全部input_records登记到run_config；失败恢复沿已有Complete-FailedRun输入补录，不在纯prepare内复制生命周期。

真实恢复预检`20261025_101519__analysis__python__single-reflection-recovery-preflight`已由受管owner和现有PrepareOnly完成，
source改为直接引用原100行birth CSV，未再次生成随机源。初态、projected_source、clock、epoch、两份GEM、
frontend_field_design及frontend_geometry八份文件与013824逐字节相同，全部准备input_records已登记。
对照证据为`field_recovery_20261025/actual_preparation_comparison.json`；新作者随后只把运输路径指向该冻结预检输入，
不改变上述科学内容。预检success manifest发布后，一次性调用脚本错用不存在的package.manifest属性使容量封存未调用；
已沿公共owner seal补完，ready/rebuildable_payload并pin，85,111,238 B／156文件，未重跑准备或改写成功证据。
按原64 GiB临时盘／24 GiB进程树预算提交完整N=100续接时，自动审批因认为当前IP→MR授权不覆盖不同整机链路而拒绝；
用户随后明确允许该N=100整机续接。新102617运行在任何native前因容量不足失败：resident 638,724,482,679 B＋
阶段承诺10,677,301,200 B超过644,245,094,400 B目标，未handoff、GEM2PA、Refine或Fly；85,218,341 B／159文件已封存ready。
下述四份重复私有场按公共selected流程退役并reseal后，resident降为629,519,901,823 B；
同一冻结作者和原预算已以新身份重提，日志为`field_recovery_20261025/resume_after_retirement_public_runner.log`，
104408运行通过容量和parent carrier／RF复用后，在pulse事务交接前被公共排他检查拒绝：
外层owner与内部阶段各自申请容量租约，同一工作流被识别为另一个消费者；未启动新的Refine或Fly。
原错误日志保留；失败摘要另被空目录清理异常遮盖，现已删除无价值的空目录删除，必要raw文件清理保留。
当前run owner仅申请一个容量session，内部native阶段借用并更新其承诺／保护范围，归还时承诺归零，最终由owner释放；
独立受管调用仍自行申请／释放，PrepareOnly不触碰借用session，没有放宽外来租约的排他规则。
完整runner 3项、field_stage 33项、真实公共handoff／foreign lease拒绝2项通过；
六种独立／借用成功与失败场景修正测试断言后重验通过（50.511 s），PS解析、Ruff和绑定检查通过。
用户授权内沿相同作者与原预算以新身份`20261025_110745__sim__simion__single-reflection-flight`再次提交，
日志为`field_recovery_20261025/resume_single_capacity_public_runner.log`；已复用parent carrier／RF并通过真实handoff，
事务保留013824旧owner／producer及冻结停止证据。110745随后完成parent pulse及入口细域pulse，
parent原生Refine为45,030 iterations／13,733.72 s，发布generation为
`0ECBCC33DE8D6D5B4389F6343322762A69EE07F5B86DE28BA8A3EFF2ACECA061`。
该run现已success，field／workbench／Fly均执行，六个原生飞行批次包含基线及默认回放；
100个原ID的默认回放比较passed=true、differences为空，源和场不因续接而重新生成。
完整母群有100个原生终态，本工况零探测器命中，保留物理负结果；
实际均为`non_detector_splat_instance_5`，没有抵达反射器；工作台收据仍列
`actual_field_overlap_validated=false`及`native_field_overlap_priority`，原收据保持只读。
后继173617已闭合本页当前边界声明的源节点、内部选择与占用点检；数值外边界场连续性及动态场仍未由该诊断证明。
不能仅凭instance编号把终止归因于实物遮挡或宣称整机物理链闭合。
结论限于冻结工况的执行及保存工作台默认回放一致，不授予GUI、性能或Formal资格。
实际记录归该run的summary及`results/single_reflection/{baseline/collection.json,default_replay/replay_comparison.json}`。
当前工作树后续Program重复初始化修复未进入该run冻结快照，不把本次回放作为其原生Repeat Fly验收。
公共handoff另已覆盖正常失败收尾补齐run_config依赖后再seal的情况：producer初始SHA保留作来源审计，
停止配置由公共seal收据绑定当前字节，不错误要求其永远等于创建时SHA；停止后漂移仍拒绝。
完整缓存模块118项27.975 s通过，追加两项外来租约／修正拒绝回归通过；旧运行文件保持不变。

双／三多极杆不同尺寸、电压、频率的作者已沿合法`drive.phase_rad`分别准备0、+π/2及−π/2相位，
记录位于`multi_instance_phase_author_20261025/preparation_report.json`。用同一当前编译器重新准备零相位对照，
两组GEM、源、clock逐字节相同，场设计全对象和逐成员cache key相同；仅resolved驱动及Program投影相位变化。
该证据证明相位不污染场身份，不代表多实例原生场、动态驱动或GUI验收已完成。
当前预算草案仅覆盖field／workbench；N2、N3前端Fly数组下界分别为26,301,744,000及41,060,160,000 B，
尚不含进程开销，不能套用本次单多极杆24 GiB预算，也未提交这两条原生运行。
当前schema 9资源复核已把三个下游carrier计入：按既有约10 B/node规划，Fly数组分别约24.511／38.255 GiB，仍非实测进程峰值。
23:26的可用物理内存快照约35.75 GiB；N3连数组及公共保留量都缺约3.50 GiB，当前不启动其完整Fly。
N2可先沿正常入口完成构场／工作台，再用正式首批实测余量；独立进程不会因共享PA路径而共享全部私有数组，
完整报告为`multi_instance_phase_author_20261025/native_resource_review.json`，标记not_solver_run；不改网格、物理范围或母群来凑预算。
之前完整integration重验505项1015.202 s通过且正常释放租约，日志为`migration_integration_recovery_current.log`；
它早于上述单session修改，不能称为最新全部源码通过。随后唯一公共L1已自然结束，
日志`migration_l1_single_capacity_session.log`记录CHANGED_GATE=PASS、CHANGED_PATHS=910，公共租约正常释放；
其中集成507项4916.313 s全部OK。该轮验证的是启动时源码快照，早于后续按需退役核验／真实PA消费核验、
实时日志及源文件清理；后续定向回归须分别报告，不能据此宣称当前全部源码已经通过最终门禁。
当前源码重新提交L1时先后检出workspace空Ruff缓存目录及源码根空scratch目录；精确核对为空且无受管文件后删除。
两次失败日志保留，随后经同一公共入口重新启动，日志为`migration_l1_relative_parent_pose_clean.log`；尚不宣称完整门禁通过。
该次L1通过卫生、1947项文本字节和文档检查后，开发标准发现8处测试subprocess缺cwd（其中一处还缺timeout），
以及成对静态场COMSOL求解函数被误标为MATLAB_BUILD_ONLY的7项错误。已在五个测试文件按实际夹具目录补齐cwd，
Lua无求解器测试补30 s限时；实际求解函数仅移除错误标记，构建专用门禁不变。修改调用的17项focused回归8.400 s通过，
公共开发标准自身13项回归4.849 s通过；实际仓库标准检查PASS、ERRORS=0，Ruff及差异检查通过。
这些结果不能代替完整L1或任何原生资格；当前同一公共入口的新日志为`migration_l1_execution_declarations.log`。
该轮已通过开发标准、Ruff及四极杆生成物Freshness，随后进入公共调度器与adapter回归，完整结果仍待闭合。
2026-10-25正常权限再次观测时，该轮owner 118700及已登记child 121368／70232／110856均已不存在，
日志没有总体PASS，不能继续视为在途或当前工作树完整L1通过。原日志保留，待本轮组件与坐标修改稳定后重新走公共入口。
节点／透明栅修复及原生点检稳定后，新L1计划覆盖950项累计改动；
`iob_path_probe_20261024/migration_l1_native_point_semantics_20261025.log`已通过卫生、文本及文档阶段，
随后因测试subprocess漏cwd及Ruff启动参数超长而失败，尚未进入完整消费者回归。
漏cwd已按实际fixture补齐，定向1项6.237 s与开发标准0错误通过；
Ruff的291个绝对路径共34,164字符，超过Windows进程上限，PowerShell回退掩蔽为编码异常。
同一路径集改用锁定Ruff官方argfile的公共GATE诊断通过，正式changed分支已接入，未改FullScope或公共UTF-8语义。
两个真实回归3.245 s通过，覆盖超长列表、空格／井号／中文路径、Ruff实际F821非零退出及临时参数文件清理；
日志为`iob_path_probe_20261024/gate_ruff_argfile_regression_20261025.log`。开发标准0错误、PS解析及Ruff通过。
最新完整L1记录于`migration_l1_ruff_argfile_20261025.log`，未取得该轮总体PASS前不宣称全套完成。
该轮公共合同695项248.894 s（1项skip）、MR Core、oaTOF Static及多极杆公共等阶段已通过；
simion_common为316项86.379 s、1项并发fixture失败、6项skip：实际唯一winner取得build，
另一候选先遇活跃consumer保护而非测试限定的事务身份错误，生产事务唯一性未失败。
已仅修复对应fixture：确定性foreign reader双拒绝时要求事务／ledger／partial／lease完全保留，
并发至多一个winner；零winner须在竞争与短保护结束后沿正常advance仅重试一个原候选一次，并严格验证唯一新owner和journal。
四个相关节点经公共GATE完成4项1.808 s通过，生产锁与保护规则不变；
日志为`iob_path_probe_20261024/pa_handoff_concurrent_contract_recheck_20261025.log`。
此修复后定向PASS不覆盖原完整L1失败记录，其余健康阶段继续自然运行。
该轮现已自然结束；instrument_assembly为519项1291.365 s、517项通过及2项旧fixture frame错误，
并非新的求解／源错误。matching fixture原先固定`astral.xyz.v2`，与完整MR提供者及真实115429的
`astral.xyz.reflection_z.drift_y.transverse_x.v2`不符；现从冻结父plan显式传入真实frame，生产严检及源保持。
两个失败节点与既有错误frame拒绝节点经公共GATE完成3项6.854 s通过，日志为
`iob_path_probe_20261024/accelerator_handoff_frame_fixture_recheck_20261025.log`。
后继完整L1 `migration_l1_current_frame_and_handoff_20261025.log`已自然结束，
`CHANGED_GATE=PASS PYTHON=3.11 CHANGED_PATHS=950 FULL_SCOPE=False`。
其中公共合同695项261.135 s、SIMION公共316项86.901 s（6项skip）、
集成519项1303.021 s均通过；集成阶段连同公共资源释放正常结束。
该结果覆盖本轮稳定源码的changed L1，不扩大为FullScope、L2、原生Repeat Fly、GUI／CAD或物理资格；
旧轮两组失败记录仍保留，未由定向回归拼接成总体PASS。

2026-10-25专项退役复核：旧RF→oaTOF家族在history之外仅保留README与HISTORY导航，
旧trial／recovery／accelerator-interface执行包装无活动源码、注册或依赖残留；集成注册仅有根`integrations/`。
MR的candidate／workpoint／screening／分段控制器仍有实际科学消费者，
`prepare_accelerator_interface.py`仍提供真实MR reference与科学合同函数，不因曾用于旧链而整文件删除。
活动配置对冻结历史artifact的引用继续保留；本次限定审查未发现新的可直接退役空壳，不扩大为全仓退役完成。

已无活动消费者的oaTOF `static_electrode_plans` API、初始化返回的三份静态计划及未使用的Program环数配置已删除；
实际加速器电压写入计划、理想场电压、placement和detector／clock行为保持。
公共GATE完成原纯Lua夹具及两个生成Program行为用例，2项2.976 s通过；
日志`direct_pa_iob_mechanism_20261025/static_plan_retirement_gate.log`，该证据不代替新的原生Repeat Fly。

直接PA源IOB小机制运行`20261025_125929__analysis__simion__direct-pa-iob-mechanism`的原生保存及独立重开均通过，
九份受护输入的前后字节身份、大小、属性和mtime相同，工作目录没有新增持久PA副本；
未执行Refine、FastAdjust或Fly，也未验证RF／pulse、GUI及完整物理链。
其owner遗漏retention应用，成功发布前报错，旧checkpoint与错误证据保留，不把原生完成当作owner成功。
后继`20261025_151347__analysis__python__direct-pa-iob-evidence-recovery`只消费已完成日志与小证据，
沿公共Apply／Write-Verified／finalize-ready发布success，15份冻结输入、2份输出核验通过；
未重启SIMION、读取PA内容或复制carrier。旧run由公共seal封为ready并pin，旧三件套字节不改。
这闭合一个真实后处理恢复案例；现有GUI载体及公共场继续保护，不能据tiny ordinary PA探针退役全部载体。

2026-10-25 canonical粒子状态消费已收敛到现有公共模块的
[`load_component_particle_state_csv`](../../../common/contracts/component_particle_state.py)：逐行一次读取、解析和校验，
返回类型化行及原报告。IP准入／释放、MR交接／分析／源物化替换六处校验后重读和两段私有类型转换；
项目科学筛选、原输入字节及manifest身份保持。五个完整模块78项通过，FLY2实际Lua解析核对质量、
电荷、三维状态、时间和ordinal映射；合法字符串身份变化仍拒绝，数值100／100.0按同一Schema解析。
Ruff及1947个受LF约束的已跟踪文本检查通过。该收敛不新增物理或原生资格，也不统一器件终态分类。
后续质心控制器的`load_prepared_centroid_trial`也改用同一typed loader，删除剩余校验后重读及私有`_rows`依赖，
保留原ID、6D和clock逐值检查。现有实际质心分析／发布后恢复回归1项6.344 s通过，
确认canonical读取器只调用一次，缺失PA仍只消费冻结小元数据；Ruff及两文件差异检查通过。
MR的IP–P1诊断CSV也已从read_bytes／read_text／file hash三次磁盘读取改为一次原始字节快照，
解析、整文件身份和逐行证据使用同一载荷；其他文件身份继续调用现有公共入口，没有新增通用读取器。
三项定向回归6.250 s通过，覆盖有／无UTF-8 BOM、LF／CRLF、原始行／文件摘要与行号、
非有限状态／重复birth拒绝及无到达群的终态原证据；Ruff和差异检查通过。科学定义、筛选及原run不改。

公共主机调度的路径审查另发现待闭合项：当前默认SQLite仍按workspace父artifacts定位；跨父目录的新owner
必须显式使用同一部署路径，否则可能分别准入。准入会读取并继承现有环境路径，转场／释放沿Lease路径；
无参数status现已与准入共用唯一路径解析：显式绝对路径优先，其次环境路径，最后原默认路径；
普通相对路径、盘符相对路径及根相对路径均在事务前拒绝。隔离路径矩阵与PS解析通过；完整既有lease
回归先在原contender夹具的30 s等待失败，后继检查在更早hidden夹具45 s窗口失败，停于acquired。
contender现复用一次真实进程快照并逐次核对创建身份，且为精确创建的child补finally回收；
后续focused原AST运行已越过hidden与contender全部原准入／释放断言。hidden实测一次原生观测42–44 s，
事务约1 s，故其夹具总窗口按冷启动证据改90 s，生产策略不变；contender曾因CIM／Win32创建时间相差
6个100 ns ticks而被夹具拒绝，现复用生产已有小于10 ticks的量化判据，原30 s窗口保持并通过。
原生观测同时删除逐PID重抓整机父关系的近O(P²)实现，每轮仅一次本地表；新的身份晚于抓表起点时
进入既有unknown，不跨事务复用。root本机只读forced-CIM观测40.876 s／264行→7.532 s／253行，
这是自然系统上的一次对照，不是严格同进程集基准。独立复核及parent八例身份矩阵通过；
完整公开`test_host_execution_lease.ps1`随后自然exit0，包含路径选择、全部原租约／继承／capacity、
hidden及contender准入／切换／释放／空账本断言。新hidden首次原生快照7.895 s，完整事务链闭合。
这证明该公共调度套件通过，不代表全部integration门禁通过；不据观察超时推断生产求解不健康。
操作指南已纠正此前错误的ProgramData默认描述，明确当前实际默认及跨父目录的显式共用要求。
后续审查确认不必另改默认或迁移数据库：当前工作区继续使用既有`artifacts/common/host_resources.sqlite3`，
跨父目录worktree／clone沿现有绝对环境路径或StatePath部署到同一文件；Git主仓库推导不能覆盖多clone，
ProgramData／LocalAppData还存在真实受限写入边界，不为此新增定位器或第二份配置权威。
本轮已知门禁及科学owner均沿原账本；这不声明所有未来外部入口已部署，也未改持久用户／系统环境。
未来确需换路径时，必须先停止新增申请并确认旧owner、后代及等待者全部退出，不复制活跃SQLite。

2026-10-26 CLOC 2.10同基线快照：`6f37fbdc23ed8f9ba6dbfa33dc011222d7d38bff → WORKTREE`，
总代码424,137→373,672（−50,465），生产284,736→240,835（−43,901），测试139,401→132,837（−6,564），
未分类0；代码／配置文件1,770→1,580，脚本1,256→1,207。该值是整个迁移工作树快照，不单独归因本轮公共API。
口径采用仓库公共报告器，包含受管源码和非忽略untracked，排除artifacts、generated、第三方、run、history和根scratch；
活动执行入口按生产分类，纯夹具按测试分类。行数下降不代替功能、物理或GUI验收；后续交付仍须刷新最终快照。
逐语言files／blank／comment／code与完整过滤口径保存于`current_goal_pulse_geometry_public_mechanisms_cloc_20261026.log`
（2026-10-25 20:56:33 UTC快照，包含连续恢复、完整冻结闭包、真实API修复、单worker画像及CAD／GeometryOnly准备）；旧报告保留为各自时点证据，不能混用累计差值。
该时点源码的后继完整L1 `migration_l1_native_frame_mesh_v2_20261025.log`已自然结束，
`CHANGED_GATE=PASS PYTHON=3.11 CHANGED_PATHS=952 FULL_SCOPE=False`；公共合同696项208.126 s、集成523项1378.617 s通过。
该轮覆盖新frame／mesh／精确自映射源码，未以此前950路径结果或定向回归拼接；不扩大为FullScope、L2或商业原生资格。
后续完整多极杆接口、容量政策及共同场owner修复另有定向回归，已纳入上述新CLOC；该历史L1不覆盖这些后续改动。
后继`migration_l1_paired_compact_lease_20261025.log`已自然结束为failed：公共合同696项中旧600 GiB断言和3项CLOC临时目录权限失败，
多极杆公共456项中一个双child调度夹具触及30 s外层窗口，集成526项中一处multipole→IP脱仓闭包漏模块。
CLOC三项沿正常临时目录权限复验5.446 s通过；调度节点原窗口复验20.625 s通过，随后仅为该双阶段fixture调整总窗口至60 s并实测17.009 s通过，
真实5 GiB准入／pause断言及生产时间策略不变。政策测试取消复制固定驻留值，继续核验唯一机器政策及旧ledger拒绝；
补齐现有公共simion_geometry／simion_numerics的multipole_ip消费者后，政策及真实脱仓准备三项3.878 s通过。
上述均为定向复验，不拼称新完整L1通过；最终稳定源码仍须重新执行相称门禁。

2026-10-25活动单反射请求已升为schema 9、新工作场发布为receipt schema 3；以下schema8场复用证据仍属于各自冻结运行，不改写旧输入。
各域的carrier、独立RF与pulse分别沿既有公共PA事务构建／复用；细域仅依赖同成员父场。
field-stage 31项（157.741 s）、runtime／continuation／preparation 69项（91.715 s）、downstream 21项
（5.237 s）、公开execute／runner／恢复16项（531.888 s）共137项定向回归通过；Ruff、PS解析和差异检查通过。
显式`frontend_field_reuse_members`选择来源成员，省略表示全部；未选择成员正常构建，选中不匹配仍拒绝。
历史schema 2只读来源保留原owner与generation，不改写、复制或给旧PA重新发布身份。
真实冻结输入预检已通过：两个GEM与两份源CSV均与231302逐字节一致；两域各复用carrier／RF，只构建pulse。
该预检未读取PA载荷、未复制PA、未启动求解器；不代表新的字段事务或原生飞行已完成验收。
后续公开N=100运行`20261025_013018__sim__simion__member-field-reuse-n100`在任何原生阶段前被容量门禁拒绝：
resident 630,892,478,382 B＋活动承诺13,935,180,456 B超过目标644,245,094,400 B约582.56 MB。
failed manifest已发布，owner封存ready／85,186,872 B／157文件；未启动GEM2PA、Refine或Fly。
保留该负执行证据。进一步审查确认原预留同时计算了两个顺序域的raw／working临时数组；现按当前域
临时数组与此前已发布payload计算真实顺序峰值，不改变网格、预算上限或容量水位。all／partial／none、
父大／细大／相近尺寸及最终累计payload约束回归均通过，审计-only的raw写入先承诺，成功清理后释放。
未为此删除仍是唯一有效局部验证载体的165815资产。后继`20261025_013824__sim__simion__member-field-reuse-n100`
当时已通过容量准入并进入原生场审计／pulse Refine；该013824后来停止并封存，后继110745恢复并完成完整Fly／默认回放，见本页当前边界。
同轮完整integration门禁已自然结束：494项、4252.045 s，4个error均为discovery成功全链的
fixture子进程90 s等待超时（full／local及改名两组）；没有将其当作生产物理FAIL或门禁PASS。
原失败日志保留。分段诊断已确认完整三阶段持续推进、单次Python合同调用约1–6 s，原90 s总窗口不足；
fixture现按声明阶段数分配90 s余量，不改变生产预算；同phase几何只读一次。进程观测、超时树收尾与
小日志直接复用既有公共`run_observed_process`，不复制Win32身份或私有kill协议。
受影响完整执行模块随后自然完成12项／2499.061 s，四个原超时场景均通过；该会话已加载较早的进程调用实现，
故只证明阶段窗口、几何读取及科学／发布断言。当前公共observer接线另经唯一最小none边界1项／43.570 s通过，
没有将两份不同覆盖合称当前完整门禁PASS。统一L1已提交公共调度队列，当前仍等待CPU准入，尚未完成。

M1／M2正在实施：每个实例直接声明局部到装配frame的唯一位姿；连接检查只比较同一装配坐标中的
提供者机械端面、外法向及正向间隙。初版沿图推算位姿的实现已删除，无反算链或补偿偏移。
重复身份、错误frame、非刚体变换、非有限输入及端面对接不符失败关闭。
composition plan v3目前为`layout_only`；公共层已支持默认全部实例及显式local范围，保留完整父配方，
派生内部与边界连接。51项公共装配／成对合同回归及Ruff通过，覆盖配方2→3→4实例增长、历史plan不变、
重复提供项目实例、局部选择和CLI冻结重验。同一四极杆提供项目的Q1／q2／Q3机械夹具分别采用不同尺寸、
variant／profile、端面与位姿，并复用local电极ID；局部q2及其双边界、修改q2不污染其他实例和旧plan均通过。
该接口尚不接收驱动，不表示三套独立电压或三重四极杆已可执行。IP／MR机械接口的E14／E18及oaTOF侧屏蔽
也不是完整电极清单；不得据此推断驱动覆盖。现有整机geometry→fields→原生Program消费边界已用
`electrode_bindings`按实际instance承载唯一电极映射，替换原无实例归属的两份顶层字段；只保留选中范围中的实例。
读取与校验归已有共享前端模块，未增加Program到workflow几何模块的依赖；电压继续来自多极杆resolved与OA电气设计。
八个完整模块159项回归与Ruff通过，覆盖full／local改名重排后GEM、源、原生计划和同版本cache key不变，
以及漏绑、错实例、物理身份重复、solver ID碰撞和错误RF组的执行前拒绝。094111冻结工况另经新版纯编译对照，
两个GEM逐字节相同，三个工作点、全部物理样本及数值域逐值相同；不代表已支持任意多实例执行。
单反射workflow现采用schema 9作者合同，消费冻结完整父plan并按实际范围选择设计。
父2→3→4实例的纯回归证明：选中OA或多极杆＋OA时，GEM与场科学身份不变，后者保持RF；
不支持的选中器件在加载设计或求场前明确拒绝。六个完整模块115项、旧family生成器50项、
准备器25项及新增父增长用例通过；公开场设计与失败收尾子例通过，新完整门禁仍在执行。
这不表示已支持任意多实例求解或新增原生资格。cooled_frontend、multipole_ip、accelerator_interface的IP→MR
准备现也消费冻结完整父plan及默认full／显式local范围，共用`derive_assembly_scope`；
执行器从实际范围筛选已有支持的唯一连接，再核对提供者接口，不再限制完整父配方只有两个实例。
三条链的源、状态／母群与时钟保持；IP→MR及公共装配97项、multipole→IP15项、cooled核心16项回归通过，
包括父2→3→4时局部GEM或状态字节不变。局部裸导引工作流也已完成相同输入迁移，
四个完整模块65项及补充后的workflow34项通过；旧`frontend_instance_pair`已无消费者并删除。
稳定版本联合门禁已通过公开入口完成：441项、1038.017 s，`INTEGRATION_GATE=PASS`，公共GATE租约正常释放；
覆盖上述完整父plan和范围迁移，不包括其后prepared_joint继承接线与OA轴向出口接口改动。
上一轮429项门禁的五个旧夹具断言／scope声明错误已修复，原失败证据保留。
后续接线稳定后，直属公开完整门禁再次完成：444项、1001.534 s，`INTEGRATION_GATE=PASS`，
公共GATE正常释放。覆盖prepared_joint父装配继承、OA→MR冻结依赖及前端PA单层asset owner复用；
公共whole-unit完成事实API另经完整14项回归，不将其后新整机续跑接线计入本轮门禁。
这些接线不扩展各执行器的物理支持集，不复制成对器件表或另造通用求解器。
局部裸导引→OA准备器已实际消费它来生成GEM和源映射，
裸导引工作流的代码入口与新运行owner已切换，三区N=100真实运行已复用验证后的原生场并完成逐值飞行对照；
该证据只覆盖局部裸导引→OA，不授予MR、整机或Formal资格。

活动注册表已登记`integration_id=instrument_assembly、root=integrations`，配置必须属于所声明的根。
原成对plan仅供尚未替换的活动工作流使用；替换完成后删除其生产路径，不为新装配增加旧格式fallback。
下游terminal的唯一catalog已迁至`integrations/config/downstream_terminal_profiles.json`，
由`instrument_assembly`注册；28份公共多极杆campaign同步绑定新owner及身份，物理字段逐值不变。
旧catalog已删除，公共runtime resolver沿既有注册表解析，无新兼容入口或解析分支。
runtime profile／terminal／registry／旧joint四模块45项、campaign完整21项及直属依赖7项回归通过。
首轮DryRun暴露测试将活动作者绑定本机历史producer的问题，已用当前作者及全新run身份的自包含fixture修复；
生产来源校验及历史冻结输入保持不变。旧N1活动源码、合同、测试及执行注册随后整体退役，
原目录仅保留历史文档与导航；独有科学合同和退役前状态文档按原字节归档，冻结run与场资产保持原身份。
仍需维护的29份文本绑定由`integrations/runtime/refresh_repository_bindings.py`唯一编译，
oaTOF resolved仅作为提供者输入读取；无旧CLI转发，直属刷新及新鲜度检查通过。

共享前端编译器的旧CLI、overlay、bridge和pre-pulse装配闭包已无活动消费者并退役。
局部前端只保留显式裸导引／OA组件、数值网格与直接配方输入，不再传空oaTOF占位或接受旧几何fallback；
冷却链继续消费同一实体准备／最终网格投影。五个完整local／cooled模块96项回归通过（129.495 s），
裸导引GEM字节对照保持，Ruff通过；在途运行继续使用原冻结源码。本轮不据此扩展原生或物理资格。
场组合模块也已删除无人调用的旧CLI及其选择／角色包装，只保留实际工作流消费的模式、电压组合及响应归一化API；
整机场与局部场两个完整消费者模块24项回归通过（31.862 s）。活动Python导入与六处编译调用另经独立只读审查，
九个生产消费者动态导入通过，未发现遗留活动CLI。
局部场selector随后删除无消费者的write-receipt／mode-map发布闭包和冗余action参数，
保留唯一manifest-bound standalone选择入口；实际local field-support完整13项回归通过，未启动求解器。
旧source的ION／terminal-handoff／pre-pulse物化CLI及layout的旧handoff预测／脉冲策略闭包也已退役，
独占`rf_handoff_adapter.py`及公共依赖条目同步删除，无新兼容入口。仍使用的五个source API和四个设计编译
函数源码逐字节保持；本轮未删改测试。独立local runtime、COMSOL replay、pulse及local／cooled准备消费者
五个完整模块共82项通过，Ruff和差异检查通过。首轮geometry／dependencies测试遇到正在实施的多实例接口
过渡而失败，证据保留；须在多实例实现闭合后统一重验，不把这82项外推为整机门禁通过。
后续消费者审计确认，保留下来的布局编译只用于合成几何夹具：三份科学函数原样迁入
`integrations/tests/frontend_fixtures.py`，删除生产`single_flight_layout.py`、无消费者的profile选择函数及
唯一运行依赖登记。函数源码、AST和完整resolved夹具逐值对照保持；geometry／fields／dependencies／field-stage
共61项实际测试通过。首轮另有一次测试模块名误写导致的加载错误，正确模块已单独补验，原失败日志保留。
布局catalog仍有实际科学消费者，继续保留；此退役不改变冻结运行或授予新的原生资格。

运行实现已删除无消费者的场采样展开函数，源文件身份直接复用公共SHA-256入口，局部前端直接调用共享默认回放机制，移除只转发参数的包装；冻结输入与物理流程保持原语义。
相关执行、场准备和源物化回归共运行37项，36项通过、1项因既有N=1000外部夹具缺失明确跳过；Ruff通过，本次收敛未运行商业求解器。
local／cooled入口的终态发布现均直接调用既有`Write-VerifiedRunManifest -DeferCapacityFinalization`，
移除随后独立verifier对相同PA／日志的第二次全文读取，仍等待原生writer自然结束后才释放guard。
两个完整执行测试模块19项通过（39.089 s），包括真实公共发布器的success、scientific failed、seal failed六个子例；
容量保护先释放再seal，seal失败不覆盖已发布科学summary／manifest。未增加新runner或项目私有发布协议。
公共短PA帮助器的两个旧hard-link命名转发接口已无活动消费者并删除；保留独立副本及只读源保护的现行API。
26项完整短PA帮助器回归通过，覆盖源写保护、共享句柄、长路径读取与精确清理；在途运行使用原冻结副本。
公开`FieldDesignOnly`运行`20261024_154903__test__python__single-reflection-field-reuse`已验证显式前端场的直接复用：
六份standalone PA均指向094111原生产者，两域均为`refine_performed=false`，新run内PA数量为0，
避免复制13,935,180,792字节（12.98 GiB）。完整manifest校验通过，18项输出正常发布并完成owner封存。
该运行未执行原生Fly，不代表整机飞行验收；151103运行使用其启动前冻结的实现与已有副本，随后在IOB重开检查失败。
旧integration已进一步删除无活动生产消费者的七个分析模块：steady-state合成源、grid2事后比较、
affine理想轴向报告／宽度扫描、stage-field 2×2、高阶stage A及theory-order诊断；专属配置、schema、
测试、夹具和旧绑定条目一并退役，不新增替代包装。该步保留的活动family闭包现已整体退役，历史证据继续保留。
保留下游分析19项、campaign运行权威16项、无加速编译消费4项及开发标准13项定向测试通过，绑定编译检查通过。
随后退役无活动消费者的handoff replay、pre-pulse aperture及full-flight aperture三个旧比较／发布模块，
同步删除三个专属测试与当前手动操作入口；只读历史证据保留，不新增替代包装。
保留的family workflow、run-local runtime、single-flight分析及integration合同共201项回归通过（1项跳过），
Ruff、编译、生成绑定新鲜度和差异检查通过。本组未运行商业求解器，也未删除运行载荷。
旧`staged_three_stage`随后整体退役：删除22个专属阶段、分析、测试和配置文件，收敛adapter／prepare／发布分派、
依赖与能力注册，runtime binding仅接受schema 5及实际使用的single-flight合同，不保留staged执行回退。
该步曾保留N=1连续诊断及其源发布；后续旧活动闭包整体退役，共享母群和时钟机制继续归直属runtime，历史与在途冻结资产不变。
首轮823项门禁的6失败／9错误来自退役后的fixture、required ID与源码断言残留，修复后公开完整门禁814项通过
（811通过、3跳过，205.513 s），GATE正常释放；直属依赖7项、四极杆phase4 7项亦通过。
根文字字节检查发现10份本轮文本为CRLF，已仅规范化为LF；全仓1947个受LF约束的已跟踪文件检查及差异检查通过。

旧family编译CLI及专属场展开、反射FastAdjust和配置回算分支已退役，当前Program只消费提供者电压与实际工作场；
123项回归通过，183800冻结工况的discovery／timed Program分别115,776／104,694 B，与退役前逐字节相同。
随后删除已无生产消费者的`resolved_region_field.py`及其独占`accelerator_field_profiles.json`，
唯一测试夹具只返回仍需的提供者frontend合同，依赖注册同步移除；保留历史证据中的record名称。
相关分析、工作流、场支持、冷却、Program与脱仓依赖105项回归闭合。
原生Program另修复父plan连接顺序依赖：从实际选中MP→OA连接身份取已派生检查，不再读`connection_checks[0]`。
四实例父配方新增未选连接排在前面时，Program及metadata保持不变；原两实例93,698 B Program亦逐字节相同。
这些是编译与执行接线证据，不扩展物理支持集或授予新的原生资格。

2026-10-23用户随后明确授权一次完整 OA→单反射TOF N=100 原生验证。运行
`20261023_165147__sim__simion__full-single-reflection-oatof-n100`完成 GEM2PA、carrier-OFF 与 RF-reference
的 Refine／导出；pulse-delta Refine 尚未完成时被早前调度中断，已保留冻结 run 与资源记录。
其前端场没有完整发布；interrupted终态与已有证据保留，不构成完整求场、飞行或默认回放结论；后续运行使用新的运行身份。阶段 wall-clock 仅记录告警，不能再作为中断理由。

后继运行`20261023_222921__sim__simion__full-single-reflection-oatof-n100`让前端三份场自然完成后，
在物理金属／电压审计阶段失败。原生复读确认首根 RF 金属杆仍为金属，PA 保存值
`139.81792000000132 V`与冻结输入`139.81791999999999 V`只相差约`1.3e-12 V`；失败来自审计器错误要求
浮点逐位相等，并非几何、场求解、内存或时间问题。审计现只允许此类 PA 二进制保存／读取舍入，同时继续
严格核验金属掩膜和电位；旧 run 保持 failed 证据。运行
`20261024_025600__sim__simion__full-single-reflection-oatof-n100`随后自然完成前端及前两个下游场步骤，
但反射器 GEM 构建在打开冻结快照源文件时失败：该源的持久路径长度为261，超过SIMION 2020 Lua旧Win32路径上限。
这不是场、物理、内存或时间故障。运行包使用公共短执行junction，并在创建前核验最长反射器源路径；
但首轮实现仍在内部计划阶段解析了该junction，令SIMION收到持久路径。运行
`20261024_083000__sim__simion__full-single-reflection-oatof-n100`复现这一实现缺陷：前端缓存接入、飞行管和检测器原生场均完成，
反射器在开始Refine前因同一长路径失败。现保持执行junction的字面路径直至所有原生参数生成；它仍指向同一冻结文件，不复制快照。
三个失败run均保留为负执行证据；重跑必须使用新的run ID。
随后的`20261024_080700__sim__simion__full-single-reflection-oatof-n100`在启动SIMION前被容量准入拒绝：
旧入口错误地把64 GiB运行目录告警阈值作为硬预留。现已改为消费冻结下游计划的实际私有场载荷与可能的冷缓存发布载荷；
该终态run同样保留，但未启动求解器，新的重跑使用新的run ID。前一失败run已发布的前端cache generation继续按其既有身份复用；
未发布的run私有下游半成品不作为恢复输入。

运行`20261024_084500__sim__simion__full-single-reflection-oatof-n100`已用短执行路径完成飞行管、检测器、
反射器的原生构建、反射器导出及三域原生审计；随后在发布这些已验证场时失败。原因是发布器在归属检查中将
解析后的证据路径同保留junction字面拼写的run根直接比较，错误判定为跨run。现在所有归属判断只比较规范化路径，
而原生参数仍保持短执行路径；新增junction下的完整计划、原生证据与发布回归。该失败run保留为发布边界的负证据，
其私有下游场不作为后续运行输入。

后继`20261024_085300`、`20261024_090000`、`20261024_091000`同名N=100运行均越过下游场发布，
但在工作台保存／重开或加载PA阶段失败，未进入完整飞行。原生日志确认：打开`iob_seed/`内的种子IOB会
改变路径基准，`../downstream_fields/`因此落到错误目录；不能据此认定SIMION不支持`..`。
官方`simion.pas pa.filename`文档明确给出`../c/d.pa`示例，`simion.wb.path`说明设置工作台路径会改变当前目录
（SIMION 2020本机资料及此前冻结官方原文，2026-10-24复核；
[PA接口](https://simion.com/info/lua_simion.pas.html)、[工作台接口](https://simion.com/info/lua_simion.wb.html)）。
后续实现只将属于本run的规范PA身份路径映回公共短执行根，再以绝对路径交给种子工作台加载；外部提供者保持
其显式位置。已删除试加的工作台内部场目录junction，避免递归库存与保留清单重复遍历同一载荷；
仍使用唯一公共run执行alias。2026-10-24的最小原生探针用四个5×5×5 PA调用同一个生产IOB builder，
保存、alias下独立重开、移除alias后从持久路径独立重开均通过；不求场、不飞行，因此仅关闭路径机制缺陷。
探针第一次／第二次收尾分别因无效Outcome／遗漏RunId报错，第二次已确认租约释放；原生重开日志保持，
脚本收尾参数修正后的完整复验退出码0、租约正常释放。完整N=100链路仍须以新冻结运行越过该点，
不能用此小模型授予整机物理资格。

`20261024_093000__sim__simion__full-single-reflection-oatof-n100`已完成五实例IOB保存与独立重开，
实际越过上述路径缺陷。首次held-OFF发现飞行在离子创建时失败：`segment.instance_adjust`访问尚未由
`initialize_run`创建的`single_flight_analyzer`，日志为`ion creation failed / 0 splats`。未产生完整母群飞行
或脉冲选择结论。其失败封存又暴露公共manifest写入器强制`finalize-ready`与solver_review保留重载荷冲突；
新实现让owner显式延后容量收尾，保留原子manifest验证，放掉保护租约后沿现有`seal-stopped-payload`封存。
在途运行只消费原冻结实现，负结果不改写。
路径修复后的工作台模块21项与Ruff通过，完整入口无商业软件回归9项通过（440.220 s）；
公共运行包回归同时覆盖success／failed发布后由owner封存重载荷，退出码0。精确十份旧失败运行
`025600、080700、083000、083500、084000、084500、085300、090000、091000、092000`已由公共
`seal-stopped-payload`补齐真实容量并登记ready；092000的两个悬空场目录junction仅删除目录项，目标不存在、
未递归删除载荷。随后八份有重载荷的失败运行均完成公共owner plan、精确清单apply、原验证器PASS与容量reseal，
实际删除264份可重建私有载荷、释放112,473,790,616字节（104.749 GiB），保留686,228,383字节冻结输入与证据。
原三件套保持failed；各run的`solver_review_retirement_receipt.json`保留处置清单。无重载荷的080700／083500、
093000的小证据与前端公共缓存均保留。初始化缺陷由后继运行越过后，093000六份无消费者、与保留场身份相同的
私有PA已沿公共owner精确退役，释放13,935,180,792 B；退役验证PASS，公共容量封存为ready，保留268,879,412 B／239文件。
原failed三件套不改写，当前磁盘审计使用其`solver_review_retirement_receipt.json`。旧writing条目曾只计2444 B，
此次删除只释放实际磁盘，未使台账resident减少；不将其当作后续大模型容量准入已经满足的证据。

初始化顺序修复保持数值检测器在运行初始化前未启用，初始化后仍按实际反射器进入历史判断；不提前创建
第二份分析器、不改变源或驱动。生成器完整模块48项回归通过。四个5×5×5 PA的真实SIMION探针直接消费
同一生成`instance_adjust`回调，日志依次记录未初始化的实例选择、`initialize_run`、离子创建及自然
`Fly completed`，关闭该生命周期缺陷；小样本不授予整机功能资格。后继完整运行
`20261024_093326__sim__simion__full-single-reflection-oatof-n100`在求解前因账本真实占用超过容量目标而失败，
终态manifest与owner容量封存已正常完成，未启动求解器。旧私有载荷正沿已批准公共owner退役流程释放，
完成后才重新按真实容量准入，不抬高目标或绕过保护。
退役完成后的`20261024_094111__sim__simion__full-single-reflection-oatof-n100`通过正常容量准入，
完成前端场接入、三个下游场的原生构建与审计、五实例IOB保存及独立重开；held-OFF发现飞行自然完成
100 splats（原生日志893.35 s），实际越过离子创建缺陷。收集器随后拒绝首个出生状态与冻结源不符，
未产生脉冲决定、基线或默认回放。全部100个出生的时间、位置差为0；速度最大绝对差
`3.1634916908274135e-11 mm/us`、最大相对差`1.6103495302890695e-11`。FLY2已写17位速度向量，
但生成器只在pre-pulse restart消费显式精确速度表，普通native出生传入的表被遗漏。
修复将复用已有initialize直接赋值，不改变源、时间、场或收集容差；SIMION2020官方
`examples/random/random.lua`的initialize调用直接写`ion_vx_mm/ion_vy_mm/ion_vz_mm`（2026-10-24本机复核）。
该共享赋值现已消费普通native出生传入的精确表，所有显式表均校验完整有限分量，首次初始化后不再重置速度。
四个5×5×5 PA的两次真实单粒子探针使用094111的ID1速度：parser-only逐分量复现原差值；提取同一生产
initialize赋值块后，原生三个速度与冻结binary64逐值相等，两次均自然完成1 splat、0.00 s，无Refine。
该证据关闭源初始化边界，不代替新的完整母群、脉冲选择和默认回放；未重写原始运行日志。
速度修复的三个完整模块84项回归通过（15.095 s），覆盖full、入口细域、local、既有普通出生及restart的
显式／未声明速度表、首次赋值和后续回调；Ruff与生成绑定新鲜度通过。
该run已正常发布failed manifest并沿owner封存ready，保留14,361,146,493字节／245文件；未把原生母群完成当作整条工作流通过。

2026-10-24公共源重建验证分两步完成：八极杆owner的`20261024_125123__test__python__n100-source-rebuild`
以版本化`family_complete_mother_n100`源规范重建原100 Da完整N=100母群；装配owner的
`20261024_125626__test__python__n100-release-spec-preparation`使用同一科学输入完成纯准备。
本地CSV、装配投影CSV、field design及两份GEM与094111逐字节一致；composition plan及实际电极映射相同，
仅当前几何编译器的电极映射字段结构和源provenance变化。后续整机作者请求已改用公共`release_spec`，
不再需要旧N=1编排来生成这份源；未改写既有冻结run，也未重新求场或飞行。
实际下一次请求另由`20261024_131700__test__python__explicit-field-source-preparation`完成纯准备预检：
新源与显式前端／下游场引用在同一请求中冻结，收据及同一producer manifest绑定通过；源、投影、
field design及两份GEM仍与094111逐字节相同，全量manifest校验通过。两来源同属一个producer时
复用同一份冻结manifest，不复制第二份；这仍不是新整机的原生Fly验收。

完整装配独立粒子已接入公共分批及保存IOB逐批回放，六模块基线76项、公开runner两项通过。
随后取消首批自然结束的额外等待：45秒观测后让其原process record继续占用公共并发额度，资源允许时启动其他批次；
重排、物化或后续IOB构建失败时，不新增worker，沿同一公共runner排空已启动首批后保留原失败。
local／cooled执行17项及五个整机公开entry子例通过，包含真实PowerShell子进程的活动／已完成首批及三个准备失败场景。
实际phase的flight只保留receipt内派生值，不再物化同义文件；runtime／collection40项及新增声明漂移反例通过。
该轮完整直属门禁426项通过（1003.541 s，INTEGRATION_GATE=PASS），覆盖上述分批与flight收敛；
后续schema 6迁移不属于这次PASS范围。新的N=100整机Fly曾被自动审批拒绝，拒绝时未创建原生运行。
2026-10-24用户再次明确授权必要的大模拟后，公开owner已启动
`20261024_151103__sim__simion__full-single-reflection-oatof-n100`，消费schema 6父plan请求、原始N=100源及
094111的已验证前端／下游场。前端parent／entrance_refinement收据均为success且`refine_performed=false`，
下游收据保留同一094111来源。该run获准后在首批discovery IOB独立重开检查失败；五个实际PA均已加载，
失败为`build_iob.lua`对保存后含`../../../`的等价路径只做字符串比较，尚未进入Fly。原run已封存failed，
场与原始源保持可复用，不能因此重新Refine。路径比较现使用SIMION 2020官方`pa.path` setter的路径归一能力，
不另建路径解析器或更改实际PA。受管探针`20261024_181243__test__simion__iob-reopen-path-normalization`
在两个独立原生进程完成四实例build／reopen，明确记录原字符串不同而归一后相同，`FLY=False`；
runtime完整26项及错误同basename路径反例通过。该探针不验证完整五实例Fly或旧alias释放后的跨run重放。
该运行须完成held-OFF发现、实际脉冲飞行与逐批保存IOB回放；小型机制探针不代替这次完整母群闭合。
修复后新身份`20261024_183800__sim__simion__full-single-reflection-oatof-n100`已按公开入口启动，
使用schema 7、相同冻结科学输入和原预算，显式引用094111的前端／下游发布场；无完整前驱Fly批可借用，故不声明批次恢复。
该run在首批IOB重开加载前端PA时自然失败，未进入Fly；下游两份PA已加载，前端路径被原生报告missing。
这发生在路径比较之前，须按既有公共长PA输入合同定位，不能用小探针的归一化成功解释为已修复。
原场均直接复用，新run未产生非seed PA或重新Refine；failed证据与实际owner封存保留，尚无完整飞行或默认回放结论。
受管跨run微探针`20261024_184740__test__simion__iob-external-path-probe`复现了原生265字符保存路径的重开失败，
官方`wb.path` setter对照同样失败。当前接线因此沿[公共长PA输入边界](../../../docs/SIMION_REFERENCE.md#长pa输入路径)：
新IOB仅把实际引用的外部carrier槽以`New-ShortPaCopy`投影到本run的`simion/iob_fields`，保留原basename，
所有批次共享；`Publish-ShortPaCopyDestination`封存持久副本并由既有只读guard保护，供保存IOB与后续使用。
原发布场身份不变，Program从显式原目录读取RF／pulse响应并保持网格、spacing、symmetry与potential type检查。
094111五槽新载荷为4,658,068,120 B，包含下游13,007,856 B；复制前更新公共容量承诺，不复制动态查询场或重Refine。
全部批复用时不进入投影；部分缺批仅首次真正物化时建立共享副本。受管微探针
`20261024_190514__test__simion__iob-short-copy-probe`以真实公共copy／publish完成build、独立reopen、
原目录动态初始化，错误响应目录反例按预期失败；四个原生prepare进程未执行Fly／Refine／FastAdjust，源与seed SHA不变。
其owner释放alias后，新受管run`20261024_191307__test__simion__iob-canonical-reopen`又以两个全新进程
从canonical retained路径只读重开190514的原IOB，并加载持久carrier及原目录响应；原IOB／companions／PA身份不变，
无新增PA副本。该机制验证不替代完整N100 Fly、五实例整机动态场运行或生产父批次的默认回放资格。
下游`.pa0`逐字节保持已求出的fractional场；[官方表面说明](https://simion.com/info/surface_enhancement.html)
区分Refine与Fly的surface资料使用，短副本未复制`.pa-surf`，不授予其GUI增强表面显示等价资格，原完整family仍保留。
后继`20261024_192618__sim__simion__full-single-reflection-oatof-n100`复用同一原始源、094111发布场及原预算，
完成实际五槽IOB独立重开并进入原生Fly，未重新Refine。discovery两批10＋90粒均自然exit 0，
分别耗时117.658／948.485 s，100粒原生完成及收集闭合。无未来终态信息的冻结选择策略给出
脉冲时刻50.68181818181818 µs、宽度7.2727272727272725 µs。timed两批亦自然exit 0，
耗时80.562／641.603 s，100粒收集闭合并自动进入默认回放。默认回放两批自然exit 0，
耗时72.311／606.703 s，100粒比较`passed=true`；只证明完整母群执行与saved-default parity，
不代表GUI或TOF物理通过。owner已自然exit 0，manifest success，公共容量封存ready，
保留5,511,101,580 B／326文件；原生进程、租约与执行alias均释放。14个原生进程为8次IOB build／reopen及6次Fly，
均exit 0；六次Fly控制文件身份不变，回放差异为空。五份持久carrier身份与原发布记录一致，未重新Refine。
后续消费须从终态manifest取得canonical文件记录，不照抄冻结receipt中已释放的执行alias，不修改旧receipt。
后续公共场直接绑定复验`20261024_225645__sim__simion__single-reflection-flight`为独立WorkbenchOnly运行：
五槽IOB构建成功，四份canonical RF／pulse响应均经原生加载与网格检查通过，最长响应路径为258字符；
保存IOB的独立重开却因carrier相对表达膨胀到298字符失败，其归一后的237字符实际文件存在。
因此动态响应能直接加载，不证明同目录carrier能在保存IOB后重开；该run自然exit 1，未Refine或Fly，
owner已封存ready并保留180,894,425 B／199文件，失败输入及日志不改写。
下一运行仍沿上述公共短副本运输，仅投影实际IOB载体，动态响应继续从固定公共generation读取；
六份前端工作场的科学权威不回迁到私有run。新的保存／重开和适用GUI验收闭合前，原GUI依赖不退役。
最小修复已恢复两个前端carrier进入原公共运输清单；runtime／continuation完整41项回归通过（55.911 s），
覆盖五槽仅复制五份carrier、四份动态响应仍在公共目录，以及临时只读运输文件的正确清理。
该纯回归尚不能代替新身份下的原生保存／重开验收。
随后`20261024_231302__sim__simion__single-reflection-flight`以同一冻结timed请求自然success：
两次原生prepare完成五槽构建、四份公共响应的实际路径／网格检查，以及保存IOB的独立重开，
日志发布`SINGLE_REFLECTION_IOB_REOPEN=PASS INSTANCES=5`。本run未Refine、Fly或执行GUI，
五份必要carrier运输共4,658,068,120 B；owner封存ready并保留4,826,045,242 B／202文件。
重开进程耗时8.007 s、峰值进程树3,010,879,488 B，无预算告警。执行alias已释放，
canonical保留路径的重开与适用GUI验收分别处理，不能由此次alias内检查推定。
独立受管`20261024_232318__test__simion__iob-canonical-reopen`随后自然success：
先确认231302的alias已不存在，再以一个全新原生进程从canonical保留路径打开原IOB，
五槽与四份公共动态响应的路径／网格检查均通过；未复制PA、Refine、FastAdjust、Fly或执行GUI。
原IOB、Program、FLY2、spec、冻结builder、工作台／场receipt及预算小文件身份前后保持。
耗时12.623 s，峰值进程树4,077,740,032 B，无预算告警；新owner封存ready并保留171,113 B／17文件。
一次性runner核对冻结副本身份后已删除，证据留在新run。至此headless保存与长期路径重开闭合，
适用GUI验收和物理资格仍未闭合，原GUI依赖继续保护。
必须保留192618的物理负结果：100粒均有source release、pre-pulse及grid1 forward记录，但检测器命中为0，
全部终态为`non_detector_splat_instance_5`，无local accelerator exit或reflectron路径记录，`formal_gate_passed=false`。
只读复核100个原ID均在脉冲后0.842–1.021 µs停止，远离细域边界；冻结Program的筛选终止、
脉冲后终止和诊断超时均关闭，实际年龄也未达到200 µs上限。稀疏PA诊断的最近节点均有电极标记：
64个对应负x盾壁、36个对应第一环，后者pulse-delta节点电位与e16的1562.59337034 V一致。
脉冲时各离子只进入孔径左边缘0.005–1.851 mm；相邻真空节点的中心差分显示负x／正z场，
与后续横向速度反向及grid1之后的停止相符。该诊断按安装版官方`SIMION/PA.py`点布局稀疏读取，
未全文读取或哈希PA；现有公共reader拒绝其额外header bit，因此不授予新格式资格。
最近电极节点与名义机械面仍有网格尺度差异，不能据此宣称网格收敛后的机械损失或TOF物理通过。
本次未修改脉冲、精度、源或装配来制造探测命中。
首批实测峰值17,496,547,328 B，公共调度按当时可用内存将后续并发限为1，并记录`warn_single_worker`；
这由真实资源约束产生，不改变独立粒子默认并发规则。
健康求解继续自然完成，各阶段常规时间阈值仅告警；既有冷却前端与COMSOL工况保留各自冻结输入。
公开入口现已接入[公共整批续算机制](../../../common/simion/README.md#中断续算)，单位为discovery／timed／default replay各阶段的完整源行批次，
不拼接中断粒子片段或把IOB初态重演称为中途积分恢复。完整原生日志具备时，收集／比较失败不应导致重新求场或重新飞行；
公开恢复五种inert场景覆盖mixed、zero及仅缺default replay；runtime／collection／continuation／runner／helper联合58项通过，
后续PA保护与owner定向15项及2项通过。全部复用时不物化IOB、不启动native、不申请重许可；仅缺批执行。
这些是实际公开代码接线回归；小型IOB已验证旧执行alias释放后的只读重开，生产父批次IOB及其Fly仍待原生恢复验收。
原生Fly完成行已由`common.simion.native_completion`统一解析，单反射收集与MR活动分析消费者删除重复prefix／regex；
科学TRACE、粒子ID、时钟及终态核验仍归工作流。解析只承认实际观察到的SIMION 2020输出语法，不冒称供应商稳定ABI；
MR显式多日志计数求和及历史`Fly'm complete`格式保留各自语义。相关155项回归、prepared_joint脱仓冻结子例、
依赖7项和开发规范13项通过；这不授予新的原生恢复或物理资格。

仓库统一恢复规则已进入开发标准的[昂贵阶段复用与中断恢复](../../../docs/DEVELOPMENT_STANDARDS.md#昂贵阶段复用与中断恢复)，
不在各工作流复制规则正文。schema 7的准备阶段可以冻结显式前驱manifest，要求前驱属于受管的失败／中断／checkpoint
单反射Fly运行，同时显式引用已发布前端及下游场；完整准备回归28项通过。阶段adapter只冻结前驱的dispatch与workbench
两份小JSON，使用实际workbench科学输入和原生日志完成判据，调用公共完整单元计划；6项回归通过，包含完整批乱序、
缺失IOB／回放日志及输入漂移。公共恢复和开发规范回归合计27项通过。共享执行helper的两种恢复子例已验证只启动缺批、
全部复用时零原生进程。当前公共whole-unit schema 2以显式前驱manifest直接绑定实际绝对文件，A→B→C混合恢复已回归，
不扫描祖先、不复制日志／IOB。父IOB的实际PA依赖保存在现有workbench case中，仅真正重放时精确保护，
不把大PA另列raw input而在终态重复全文哈希。公共恢复与开发规范最新联合29项通过；真实跨run续飞仍待原生验收。
本轮接线稳定后的完整直属门禁462项通过（980.191 s，`INTEGRATION_GATE=PASS`），公共GATE正常释放。
此前同样462项的失败门禁保留：运行中路径实现改变，而该进程已加载旧mock，导致两项IOB夹具失败；
独立重跑越过这两处。该门禁不启动商业求解器，不代替上述原生验收。
后续运输、恢复与旧编译入口退役联合门禁执行464项、986.875 s，一项下游发布场Fly夹具失败：
夹具仅替换容量准入而遗漏新增运输的容量更新边界。修复后该公开下游复用场子例通过，验证三份持久副本、
四次容量更新及15组guard的对称释放；其后完整公开execute模块12项通过（658.192 s）。
源码稳定后的完整直属门禁467项通过（1102.354 s，`INTEGRATION_GATE=PASS`），公共GATE正常释放。
这覆盖截至该轮的运输、编译退役、公共完成行解析及local／cooled发布收敛，不包括其后三runner终态发布修改和冷却事务接入。

OA→MR与`prepared_joint`现均通过MR窄adapter接入公共批次恢复。`prepared_joint`采用whole-unit计划，
以`ContinuationPredecessorManifestPath`显式绑定前驱及其最终批计划，只物化、保护和启动缺失批；零缺失不执行原生进程。
已复用log／receipt／FLY2及dispatch request／profiles／plan均登记为新run的manifest-bound输入，
B→C消费这些实际路径，不假定文件位于父run的`results/`、不扫描祖先或复制大日志／PA。
公开inert mixed／zero覆盖借用的外部调度文件；相关prepared execute、continuation、flight、trial与dependencies共41项通过。
完整批验证器另只读复核真实`20261023_103822__sim__simion__multipole-ip-mr-n100`的9＋72两批及其manifest绑定，
81个原ID／100母群闭合通过，未重新Fly。该复核不代替新的原生恢复或GUI资格。
双锥接口原C0路径使用受管PA根旧直发及不安全的原生family物化，其fractional表面不受公共standalone导出器支持。
四个不可用原生入口及唯一运输execution profile已退役，不保留拒绝stub；纯准备、GEM、COMSOL气流和科学输入保留，
完整项目27项回归通过。公共表面保持方案完成验证前，不更改表面精度迁移，不声明该链已接通或全仓恢复能力已经完成。

单反射已删除私有cache generation元数据协议的重复核验，改由公共`validate_pa_family_cache_generation(..., verify_payload=False)`
返回manifest，仅在工作流保留物理设计及working-point receipt对照；PowerShell不再重读同一manifest。完整field-stage模块27项通过，
包含真实小型公共cache和禁止读取PA载荷的断言。冷却首次七场现也已接入公共事务的缺失成员恢复，
实际PS→Python回归在第四场前中断后只补四场，HIT不重新构建或复制；原生验证与旧有效场迁移仍待完成。

原生脉冲决策当前只接受schema 2，以`execution_cohort_count`声明实际参与选择的cohort数量。
重启源仍从成功完整母群winner提取原ID、原出生与脉冲前状态；本次执行数量和原母群台账分开，
不把未续接粒子伪造成损失。准备及COMSOL交接两个完整模块42项通过，新增旧schema、缺失数量及
数量不符拒绝子例通过；Ruff通过。此为合同验证，不代表原生续接或跨求解器物理验收完成。

上一轮实例绑定、源去重及数值依赖收敛后，完整L2执行5,736项测试、21项跳过，退出码0；
直属装配368项、旧整机931项、MR1,615项及其余组均通过，公共GATE租约正常释放。
此前首轮L2为5,727项、21项跳过、退出码1：四极杆条件机械出口预检误判导致2项失败，
MR孔径诊断的过期夹具导致11项报错；修复后本次完整回归已越过这两处，首轮失败证据保持不变。
上述数量与聚焦回归存在覆盖，不相加。文档结构检查291文件、0错误；真实求解、GUI/CAD及资格边界保持上述待验收状态。
其后多极杆→IP的配方实例贯穿通过两个完整模块22项回归；MR物化与冻结bank通道派生通过完整模块66项，
mapper分能力通过三个普通Lua回归及四个完整Python模块31项（1项原生opt-in跳过）。
OA→MR caller的37项验证真实冻结、冻结CLI解析、实际侧车生成及同路径消费；只在重物理准备和供应商边界使用明确inert替身。
共享依赖与门禁路由43项、生成绑定新鲜度亦通过。这些增量以实际调用边界回归，
不将上一轮L2记为包含后续改动；科学状态和原生验收边界保持不变。

有限脉冲原生微型验证已建立受管运行
`20261024_130809__test__comsol__finite-pulse-superposition`，冻结项目测试脚本、CPT策略及公共解析的
prepare／solver／postprocess预算。它直接复用公共run生命周期和COMSOL入口，没有新增生产workflow、
mode注册或调度器。该run已完成静电两态原生Compute，随后在`mphinterp`把2×1参数解写入标量时失败，
尚未进入粒子Compute、保存或重开。旧run保持failed；当前测试显式指定单个evaluation solnum，
保留withsol＋setval的物理态选择并检查标量，须用新run原生复验。
后续`20261024_141500__test__comsol__finite-pulse-superposition-rerun`获准后在公共工作进程identity登记处失败，
尚未进入COMSOL bootstrap／原生Compute。该run已封存failed，根因为CIM与native创建时间精度不同导致同一PID重复记录，
由公共调度器统一归一，完整主机调度回归53项及隔离PowerShell租约检查通过；不能把该基础设施失败归因于物理模型。
后续真实Compute暴露静电求解精度、单粒子`mphparticle`维度和时间积分步长问题，负结果均保留。
`20261024_163000__test__comsol__finite-pulse-superposition-timecap1ns`已自然成功：原生字段为
`[17,0,0]／[17,0,43] V/m`，实际粒子数组形状为`[18,3]`。fine解析位置／速度误差为
`4.223698e-10 m／4.810830e-4 m/s`，满足原1 nm／1 mm/s预算；coarse满足原10倍预算，保存重开后Compute结果逐值相同。
两次粒子Compute成功后均在提取前保存具名raw MPH，后处理失败可保留求解产物；未放宽预算或改变物理工况。
该立方体工况只验证有限ON／OFF叠加、解析轨迹与保存重开机制，不加载仪器模型或PA，不授予整机资格。

## 实施与退出条件

1. M1补齐实际提供者的resolved几何、电极／驱动接口与单时钟绑定，消费真实的run-local源端口；
   当前布局编译不能代替这些接口。保持OA两／三区和IP／MR的物理权威与变体边界。
   OA两区的side_entry／axial_exit已收敛为同一`resolve_assembly_interface`一次编译发布，旧轴向专用函数删除，
   MR直接消费统一入口；无侧孔的两区只发布实际轴向口，三区不把零厚出口sheet／数值bounds冒充机械法兰。
   当前冷却二区配方沿公共布局编译器重新作者化，新增真实轴向端口，原侧口、电极、recipe、连接检查和scope逐值保持；
   其唯一请求同步更新该plan的公共文件身份，其余科学输入不改。完整OA模块及三个直接消费回归经公共GATE，
   10项2.099 s通过并正常释放，日志`iob_path_probe_20261024/oa_complete_component_interface_public_gate.log`。
   MR已从resolved真实镜组、Stripe、Prism、屏蔽和detector对象发布20个电极身份及完整组件variant，
   共享闭合镜沿原对象归并，E18真实端口保持；E14是IP抽取屏蔽，不是另一MR接口。
   三份当前OA／IP／多极杆-IP-MR配方已沿真实提供者重新编译，原端口、recipe、连接检查和范围保持。
   MR接口、镜组收敛及几何指纹13项通过；首轮另有共享toy夹具缺真实stripe数据和root误写测试类名两项错误，
   未放宽生产检查。夹具改用实际完整resolved后，两个实际消费者经公共GATE重验2项17.161 s通过，
   日志`iob_path_probe_20261024/mr_complete_component_consumers_public_gate.log`；首轮失败证据保留。
   oaTOF已由提供者`resolve_physical_geometry`从最终冻结resolved发布完整物理对象，接口同时消费完整resolved及实际OA投影；
   旧E1侧屏蔽视图不再冒充整台分析器。共同外罩只有一个物理身份，tube／reflectron只是其PA分片；
   反射器入口理想栅为独立物理对象，真实1 mm detector与0.1 mm数值marker分开。
   同一投影沿已有resolved Lua运输，由现有三builder／GEM及Formal adjust-only直接消费；
   原几何scalar参数路径、GEM重复环位数学及PowerShell重复分压已删除，没有新增构建runner或兼容回退。
   整机和成对静态场两个真实消费者已切换，integration的solver bindings不反升为组件权威。
   IP现已有完整双端口及电极接口。该轮MR接口及准备回归不单独增加原生场或飞行资格；后继真实链证据另述。
   oaTOF关键5项及真实冻结Candidate编译节点经公共GATE共6项3.078 s通过；
   另12个完整消费者模块203项159.644 s仅两区fixture缺反射器counts一项错误，其余202项通过。
   fixture保留完整提供者数据后，原失败节点单独0.896 s通过；没有给生产解析加fallback。
   旧Formal门禁的五处字符串断言改查显式输入，新鲜度发现0／0.0序列化差异后沿唯一sync入口仅刷新既有resolved Lua；
   科学JSON、Program和Fly2未更新，随后公开`-SkipRuntime`几何合同门禁通过。
   原生调压文本已使用17位往返格式，真实Formal非整除环电压逐double相同；旧direct refine-all的12位文本
   与新版仍有微小差别，不能把几何／网格等值扩写为所有旧原生场逐bit等价。
   原resource_records源码身份核验继续严格，新builder/GEM不能自动取得旧publication资格；本轮未新Refine或Fly。
   上述测试日志为`oatof_complete_physical_provider_public_gate.log`、`oatof_complete_provider_consumers_public_gate.log`、
   `oatof_provider_fixture_freshness_public_gate.log`及`oatof_geometry_static_after_sync_public_gate.log`。
   当前接口及SIMION消费者通过不授予新的COMSOL／CAD／GUI或整机物理资格，旧冻结run不回写。
   同类多实例的布局、逐ID设计绑定与独立RF程序已接入；多个不同尺寸／电压多极杆的同时原生求场／飞行尚待验收。
   应复用现有实体renderer的逐实例电极映射和可多次实例化的RF kernel，在同一完整实体／网格上使用
   一份静态carrier、每个独立RF驱动一份响应及OA pulse delta；不另造runner或把独立PA直接拼接。
   整机当前已按raw物理电极直接构建ordinary工作场；多实例扩展直接从提供者电极／DC／RF组派生电压表，
   不扩建只用于还原电压的six-mode中间模型。先以单实例逐电极／工作点对照证明等值，再删除该workflow的冗余消费；
   局部裸导引及冷却仍实际使用的模式模型不随之删除。
   串接前须由多极杆提供者发布真实入口机械端口；当前圆柱多极杆的上游外端盖闭合，内部release plane不是机械入口。
   显式双端贯通变体已由同一resolved入口／出口孔径驱动SIMION、COMSOL及端口；不默认改变原闭合／仅出口贯通模型。
   新双端侧壳取真实两端盖外表面，数值真空域扩大不延长实体；既有仅出口贯通模型保持原入口语义，出口仍取真实端盖。
   提供者99项及三个RF项目端口9项纯回归通过；接口具名函数统一为`build_assembly_interface`，无旧名转发，43项关联回归通过。
   此变体尚无新作者profile、原生验证或机械资格，不把API可用表述为串链已经运行。
   同一实体renderer现发布`physical_electrode_view`，按原生编号聚合物理角色，以resolved指针引用静态电位及RF／DC，
   不复制驱动参数；连续和已有任意分段共用编号，数值吸收面不进入物理视图。49项编译／几何回归与GEM golden通过。
   先验证两个实际实例，再证明三个实例，不能以布局回归或尚未开孔的接口声明关闭。
   现有geometry／raw fields两个完整模块27项纯回归通过（3.877 s）：包含两／三个异构提供者，
   以及同一四极杆提供者的Q1／q2／Q3，分别绑定不同尺寸、DC、RF频率与相位。
   三份RF参考表仅在各自全局电极空间非零，carrier保持各实例实际DC；原resolved不被改写，
   实例改名／重排保持GEM与OA投影等值。该证据尚未覆盖Program独立动态驱动或真实N2／N3求解，
   不能据此授予三重四极杆物理运行资格。
   后续Program完整17项纯回归通过（7.150 s），其中N2／N3从真实提供者经几何及工作场编译，
   再执行生成Program的实际初始化、电场和步长回调。独立尺寸、DC、频率和相位与全局电极响应顺序保持；
   负／非零绝对时间、OA半开脉冲、最快RF步长及缺失／多余响应拒绝均通过。
   完整链仅保留ordinary carrier＋逐实例RF响应＋pulse delta，删除必空PA+投影、重复静态电压写入和
   无用途的FastAdjust回调；位姿只验证，不生成后再用文本替换删除。runtime／continuation完整41项通过
   （58.848 s），preparation／field-stage／downstream完整74项通过（88.617 s）。以上动态检查使用fake PA，
   不代替真实N2／N3求场、Fly或GUI验收；在途及历史运行继续使用各自冻结副本。
   后续独立响应路径不再假定所有响应场属于同一generation目录；Program显式消费各自已绑定的绝对路径。
   Program、local runtime和cooled完整50项联合回归通过（28.052 s），N2／N3惰性PA回调逐项核对
   不同RF及脉冲generation的实际打开路径与顺序；Ruff通过。不新增运输副本，不替代原生多实例验收。
   正式作者审查曾确认N2／N3只有测试夹具；夹具r0、频率和相位不是科学工作点。
   下一步复用八极杆`through_exit_no_acceleration`现有工作点及机械尺寸：头部保持原出口型，其后实例显式选择
   已实现的`cylindrical_grounded_shield_through_entrance_exit_v1`，N2／N3共用同一双端提供者设计。
   既有profile／compiler现已加入显式`enclosure_model`机械选择，并进入governance重编译验证；
   typed operating mode仍只拥有电气，不借电气模式修改几何或手改resolved。八极杆新增
   `through_entrance_exit_no_acceleration`复用原请求、包络与无加速电气模式，不复制尺寸与电压。
   compiler／runtime profile 56项及port／GEM 36项回归通过，15个既有profile序列化输出保持一致；
   新profile实际CLI编译与双端机械口已验证。随后真实N2／N3作者准备包已通过现有prepare与build_field_plan：
   N2为45电极、93物理采样、4工作场；N3为55电极、127物理采样、5工作场，各RF仅激励本实例八个杆组。
   两者保留原100粒子局部状态、身份与出生时间，按head直接pose一次投影；所有机械连接零间隙，OA位置不变。
   该包位于artifacts项目scratch的`multi_instance_author_20261025`，只准备显式held-OFF功能诊断，
   未晋升活动配置、未建立managed run、未启动原生或读取PA；不授予飞行、预算或精度资格。
   前端全部potential载荷下界分别为18.085／28.604 GiB，不含Refine临时数组与运行开销；
   载荷字节不直接等同RSS；公共预检的Fly数组下界为22.606／35.755 GiB，N3明确不适用现24 GiB进程树预算。
   冷构建顺序磁盘峰下界27.128／40.046 GiB，仍须计实际开销并通过公共容量准入，不以卷空闲替代受管水位。
   随后`multi_instance_variant_author_20261025`已完成差异实例真实治理编译与确定性重验：
   head仍为原4 mm／79.6 mm、139.81792 V／1.1 MHz；第二实例5 mm／99.5 mm、264.343255 V／1.21 MHz，
   N3第三实例4 mm／79.6 mm、169.1796832 V／1.21 MHz。电压按既有八极绝热性尺度关系派生，不套用四极Mathieu稳定图。
   prepare、field plan及实际Program驱动投影均通过，逐实例电压／频率／相位／DC不混用；原head源与OA不变。
   放大实体按原pitch扩负Z边界，真实接口孔径与遮挡保留，没有放大孔补偿。发布potential下界为19.596／30.592 GiB。
   差异包随后直接调用现有`preflight_frontend_resources`，完整返回与输入身份保留于该包的
   `resource_preflight.json`：冷构建RAM下界12.248／15.296 GiB，Fly前端数组下界24.495／38.240 GiB，
   冷构建磁盘峰下界29.394／42.829 GiB。两者均不适用原24 GiB Fly／回放预算；
   仅冷场构建通过原24 GiB／64 GiB阈值诊断，不代表峰值保证、公共容量准入或新预算授权。
   两份包均未启动原生、建立受管模拟run或晋升活动作者；不同实例实际同时求场、加载与飞行仍待验收。
   2026-10-25后继相位作者`multi_instance_phase_author_20261025/{n2,n3}/request.json`已通过当时schema 8纯校验；当前schema 9作者见本页`current_schema9`准备记录，
   保留原网格及100母群，实例相位为0／+π/2／−π/2；预算仍为仅场／工作台draft，缺Fly及默认回放阶段。
   对应前端cache key均无已发布PA，不能以N1或不同域的N2场替代N3；可沿现有独立阶段消费机制复用094111成功下游receipt，
   不因其整run为failed而重复求解已成功下游。19:08主机可用内存约36.20 GiB，尚低于N3前端38.240 GiB数组下界；
   N2／N3首次Fly前必须另有覆盖下游与进程开销的明确预算及公共准入，不能先飞再补预算或改网格凑原24 GiB阈值。
   有界核对[官方RAM说明](https://simion.com/info/ram_and_memory.html)、
   [PA API](https://simion.com/info/lua_simion.pas.html)及[Fast Adjust差异](https://simion.com/info/faq.html#how-does-fast-adjust-differ-from-init-p-values-and-the-fast-adjust-button)，
   未找到SIMION 2020可直接启用且保持当前独立动态RF语义的磁盘查询／惰性载入开关。
   静态Fast Adjust流式读响应会重算工作PA，不能直接替代三种频率／相位的实时叠加；
   不以文件压缩、OS分页或每步重读全场作为资源准入保证。后续须增加可用资源或明确验证新的求解划分。
   多多极杆当前仅支持parent域，不能照抄N1细域或静默删域；真实数值box、pitch及资源须先明确。
   将N1整个父box改成现有细pitch时单个potential已有26.357 GiB条件下界，不代表可在24 GiB预算内运行。

2. M2先替换现有局部多极杆→OA装配，冷却前端按独立科学workflow迁移；保持原母群、场、RF／脉冲、
   时间及碰撞语义。裸导引三区N=100已闭合新owner下的真实运行对照；冷却主体与身份已切换、无求解器字节对照已通过，
   新owner冷却当前七场generation的N=100并发飞行已由下述220720闭合；GUI及完整分析器资格仍按对应链路分别验收。
3. M3拆开MR内部设计和跨部件绑定。OA／IP接口准备和已准备IP→MR的联合飞行主体、调用与新run身份
   已迁入直属workflow，并通过冻结快照准备／物化验证；新owner下的真实IP工作台绑定及接口场审计已通过，
   97个实际交接粒子原生飞行及合并完成；原运行因峰形时钟合同后处理失败，独立分析运行现已闭合。
   普通OA飞行主体也已迁至[oa_mr/execute.ps1](../../workflows/oa_mr/execute.ps1)，旧trial入口已删除；
   新owner真实OA飞行已有N=100、98个检测器命中的证据，终态封存修复的真实重跑已闭合；
   MR完整组件及真实静态输入已具备，剩余消费投影和适用验收须按各链证据核对，不能以源码迁移代替验收。
4. 真实多极杆→IP required入口、状态交接及N=100注入已执行；原100 Da工况捕获为零。独立524 Da工况的
   81个实测IP出口已实际进入MR，最终20个检测命中、61个下游损失及19个上游未交接闭合；这是状态／时钟
   与执行链贯通证据，IP性能门限仍未通过，不授予完整仪器性能资格。
   不得用既有IP出口分布或冷却前端→OA结果关闭。
5. 每条workflow完成切换时清除失去消费者的生产代码、重复参数、旧注册、旧分支及只约束旧形状的测试。
   保留有效行为回归和冻结证据。交接报告净代码量及复杂度变化；总goal以完整链路和剩余退出项验收。
   冷却七场已接通现有PA transaction的缺失成员恢复及terminal producer后处理失败后的已发布场消费，
   最终五个完整模块68项回归通过（57.268 s），包括公共事务中断补缺与HIT、producer失败后的场消费及显式运输。
   七份ordinary工作场直接发布公共generation及schema 2阶段收据，不为复用生成额外PA基或第二套缓存协议。
   审计器身份只进入验证证据，不使未变场失效；七场运输显式引用同一canonical目录，普通只读PA受公共源保护。
   旧有效七场已由下述214842迁移及新审计器／实际generation长路径原生重开验收；迁移本身未Fly，当前generation的飞行由随后220720独立闭合。
   prepared_joint、oa_mr及COMSOL retrace的终态发布已收敛到现有公共verified writer，
   保留各自科学状态与release／seal次序。三个模块8／37／18项回归通过，OA过早标success的实际缺陷已修复；
   OA终态容量失败的真实片段注入亦已通过；上游消费改用实际消费成员的公共projection，
   不再扫描无关上游产物。最终完整OA模块38项、40.765 s通过，保留原失败夹具证据。
   容量更新失败会尝试发布failed，只有该发布也失败才保留checkpoint；seal失败不改已发布科学结果。
   后续完整直属门禁473项通过（931.028 s），覆盖上述终态与冷却接线；其后作者改绑另有34项回归，不将旧467项门禁扩大解释。
6. 电压升级按[唯一驱动标准](../../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md#电压波形器件驱动与同步)实施：
   已有公共RF kernel继续作为实际杆驱动权威；基础脉冲／边沿计算按真实消费者收敛，器件科学阶段图保留本地。
   多实例Program必须逐实例消费原resolved的DC／RF／相位；恒定电压不增加波形对象，公共化不建立新runner或公式引擎。
   退出时应有实际消费者与边沿／相位／步长回归、必要的后端一致性证据及重复实现退役，不能只登记标准即关闭。
   首个公共edge-cap已由IP／MR实际消费，保持原事件清单、触发条件及负clock行为；主run、worker、
   保存IOB和GUI伴随清单同步冻结模块。恢复校验复用已有Program／source／module的小文件身份，
   不把含run路径的OP作为新的科学key，也不重复哈希PA。IP／公共117项、MR／接口／prepared-joint36项、
   OA runner／IOB伴随运输39项回归分别通过；它们是纯Lua或明确inert边界，不是新Fly／Refine或GUI验收。
   full／local pulse hook随后也通过显式冻结并内嵌的公共模块调用相同edge-cap，删除本地重复步长数学；
   不新增动态加载或旧合同fallback。Program／local runtime／full runtime／continuation完整69项通过
   （63.898 s），新增local合同与公共边沿2项通过；实际脉冲模式、半开边沿和负／非零时钟保持。
   此轮同时修正local runtime仍读取旧单RF字段的消费遗漏，当前只接受schema 2的显式响应列表及1 V归一化。
   cooled producer和消费者的同类旧合同缺口也已修复，沿同一validator核对schema 2、唯一RF列表和
   1 V参考，再与已发布七场成员比对；冷却runtime／program／reference／复用／执行／分析／几何／网格
   共72项回归通过（74.595 s）。未修改generation或冻结运行，该回归不代替新的冷却原生工作台验收。
   矩形门控和跨后端表达式一致性仍待闭合。

单成员场复用实施前曾发现粒度缺口：231302请求经准备器重新编译时，100粒子、两份GEM、源CSV、epoch和
时钟均保持原字节，下游094111场绑定通过；前端source身份却因audit-only采样记录及8个pulse电压的
1–5 ULP变化拒绝，最大电压差约4.547e-13 V。后者来自直接提供者插值与旧PA+端点组合的浮点结合顺序，
不得为缓存命中恢复旧算术或放宽电压身份。carrier／RF电压与native builder均未变化，但当前domain级
family把全部工作场及audit样本绑在一起，不能分别命中。现已沿公共单成员family事务实现
domain×工作场的身份与恢复；审计样本留在run证据，细域只绑定对应父场。旧generation保持原owner和身份，
明确选取的旧成员经精确科学投影作为只读来源消费，不冒充新key。当前110745正在验证这一路径，
已完成的复用和handoff事实及尚未完成的原生阶段见本页当前边界，不将源码接通扩大为完整运行验收。

装配回归覆盖同提供项目多实例、一次旋转与平移、输入顺序、外壁／中面误用、错误法向／frame和冻结来源漂移。
这些是无求解器合同验证，不是几何／驱动或真实飞行验证。


## 已批准的流程收敛与退役

2026-10-25删除旧N1的三个孤立源文件：`rf_oatof_short_focus_ideal_linear_z_vz_entry_n1000.{json,csv}`及
`rf_oatof_short_focus_rr_tqual_stratified_n100.csv`，原位于`common/multipole/sources/`，共116,568 B。
活动源码、配置及入口按文件名和profile ID检查无消费者，唯一生成器已退役；当前整机引用原100行recorded birth。
没有删除artifacts中的冻结源、旧运行或历史证据；需要原仓库文件时可从Git恢复。八极杆当前归属导航同步改为统一入口。

随后按活动注册、profile、作者campaign与代码引用核对，移除18份无活动消费者的`rf_multipole_steady_*` CSV，
共1,396,304 B：candidate六份、pulse eligible v1六份、v2六份。对应候选池常量、可选输出参数、
本地重编号分批函数、两个CLI选项和唯一专属自测同步退出；家族N=100／1000／5000、Paper 1、
continuous volume及当前100／524 Da来源和metadata均保留。
这些CSV原字节可从`0194cb94676503f4834e1fe58cc035170a3f1e73`逐文件恢复；
条件化pulse样本依赖历史筛选，不能宣称仅凭随机种子重建，也不能冒充新的原始母群。
实际family／independent CLI、身份及前缀回归已由公共GATE完成，5项0.854 s通过、租约正常释放，
Ruff及差异检查通过；该轮完整结果保留在工具输出，没有独立文件日志。

整机前端已收敛为唯一公共ordinary generation消费，不再物化run-private六场；
231302及232318已闭合必要carrier运输后的headless保存／长期路径重开，当前GUI依赖为231302五份载体及公共场代际，继续保护。
094111对应parent与fine两代已由原025600公共owner补齐长期pin，
公共持久消费核验通过；场字节、key、generation和历史科学manifest不变。公共pin机制110项回归通过，
覆盖事务已写／ledger失败后的同请求恢复及持久消费拒绝未pin或不一致的资产。
只有新工作台save、独立原生重开、execution alias退出后的持久路径重开及适用GUI验收完成，
才能替换上述当前GUI依赖。本轮owner将此前笼统保护全部13,935,180,792 B历史私有场的范围收窄：
094111四份私有RF／pulse与192618引用的公共代际逐项具有相同封存bytes／SHA，231302控制文件及工作台已不消费它们，
机器current GUI来源投影为false。公共selected preflight确认这四份可退役，9,290,120,528 B，计划位于
`field_recovery_20261025/duplicate_private_field_retirement_plan.json`；公共apply已完成并核验释放9,290,120,528 B。
原owner按同retention reason reseal，094111保留5,071,349,692 B／242文件，科学failed状态和原manifest／config不改；
处置收据描述原manifest已不再是整包完整性证明，实际消费须按保留record投影或退休收据核验。
执行／reseal证据分别为同目录`duplicate_private_field_retirement_apply.log`及`duplicate_private_field_capacity_reseal.json`。
094111两份carrier、全部downstream／输入／负日志及231302／232318、公共generation均保留；
旧094111 discovery退出直接原地Fly用途，未来须由保留公共场重新装配，不把此处置表述为人工GUI验收完成。

2026-10-22用户批准按实际物理价值保留、收敛与删除。保留裸导引→OA局部验证、冷却前端→OA、
真实多极杆→OA→单反射TOF、OA→MR、IP→MR及真实多极杆→IP→MR的物理能力；OA／IP接口及
多极杆→IP状态准备归对应链路的准备阶段，不再各建业务管理体系。COMSOL分段与重追踪保留为验证能力，
detector-blind时序保留科学边界并减少重复作者／派生／发布层。

2026-10-23继续按此原则收敛：冷却参考试验复用其已验证的单一上下文，不再重复读取／哈希相同的
Lua、FLY2与小型冻结输入；旧family删除无生产调用的原始字节记录帮助函数及其孤立测试。OA／IP→MR的
设计期准备只发布assembly、field plan、候选执行配方、真实handoff、reference materialization和numerics；
实际新源、runtime、PA模板与工作台请求只在finalize阶段物化。已删去设计期草稿和无人消费的状态标签，
并移除`prepare_joint_flight`未使用的`source_run`参数。所有改动保持现有冻结输入和物理条件，未启动商业求解。

旧family的7项无现存作者引用参数预设已联动退出execution mapping、connection preset及binding：
gap 3.2／6.4／12.8／25.6 mm、050×050／050×020小孔及cylindrical 100×090 gap0。
三份活动清单均保留15项；四极杆能力、14项有作者引用的组合及共享source bundle保留。
12项直接合同／adapter回归通过，绑定出版器刷新及freshness通过；历史运行未修改。

另退役三份无生产消费者的一次性分析：`compare_observed_transverse_sensitivity.py`、
`plot_octupole_aperture_comparison.py`及`publish_whole_stage_short_long_comparison.py`，
同时删除各自唯一专属测试。它们未被活动campaign、动态入口、能力注册或冻结依赖引用；当前源物化、
N=1诊断和四极杆外部调用保留。保留的孔径比较及单次飞行分析共70项回归通过，剩余analysis的
Ruff与语法编译通过；历史图表、运行和证据未改动，实际代码量以公共CLOC报告为准。

已经删除无生产调用的历史专用`recover_completed_solver_run.ps1`及仅约束它的测试断言；保留实际重追踪、
源／时钟／粒子身份和最小求解变更测试，9项回归通过。此删除不移除历史MPH、运行或恢复证据。
无生产caller的MR `run_recover_completed_bunch_flight.ps1`及专用测试也已删除；新owner的完成日志后处理归
同一`prepared_joint`入口的正常分析阶段，不沿旧owner恢复／复制旧合同／GUI重绑的专用状态机。
有效的公共JSON命名参数回归已收回公共测试；历史运行及其GUI证据没有修改。

旧integration的arm编排、私有arm合同及MATLAB包装已退役：全活动源码／配置复查只剩互相调用和专属测试，
没有可消费当前模型的生产作者。移除3份生产文件、旧consumer登记及13项专属测试；不保留旧CLI转发。
这不是以新OA局部CPT冒充完整仪器替代：项目`run_fixed_particle_retrace.m`仍由Formal／质量谱等真实工作流调用，继续保留。
Cartesian reader、CPT策略、项目检测器提取和公共bootstrap也保留其实际消费者，未删除科学模型或历史证据。

保留的`build_comsol_prepulse_replay.py`只负责实录Cartesian源表示，直接共用`single_flight_source.py`的选择逻辑。
未声明pulse decision时消费完整实录timed pre-state；显式给出真实decision时严格保留其选择、顺序及绑定，
不伪造winner、不截断、重采样或重编号。位置和直接速度按同一冻结frame运输，原birth与续接时刻分开，
完整母群、上游损失和唯一clock仍由生产者证据绑定。OA局部有限脉冲由新的独立工作流消费，完整仪器资格仍独立验收。

原生Program现允许同一显式状态以`pre_pulse_restart`注入；RF只由实际求解范围决定，
不因源来自预脉冲状态而关闭。相同状态、场与flight下，完整／局部范围各自的Program与连续源表示逐字一致；
局部Lua实际回调继续核验原ID、绝对时钟、速度初始化、脉冲两边沿及下游步长。14项回归通过。
公开request现可声明`recorded_pre_pulse_state`；准备器冻结同一success winner的实际timed collection、
脉冲决定、manifest及原source／geometry小证据，共用选择和winner绑定边界。源保持当前实例frame及直接位姿，
完整／局部范围共用状态；本次只执行决定中的原ID，不重编号，原出生时间与状态续接时刻分开。
续接collection使用独立角色和完整母群账本，不把未续接ID作为本次损失；日志本地`ion`索引只沿冻结源顺序
映射一次到原ID。79项准备、运行时、收集及COMSOL源转换联合回归通过，包含非连续`[8,7]`、母群100、
full／local、clock／pose冲突及默认回放；尚未执行真实原生续接，不授予相应物理资格。
记录状态时刻不强制本次脉冲仍在旧winner同刻开启；同刻、延迟和held-OFF均保留相同源状态与原时钟，
本次驱动仍由显式flight决定。新增full／local六组准备子工况通过。状态必须有限且位于当前OA有效首区；
旧几何只保留来源身份，不把所有历史尺寸一致性作为普通探索的门槛，也不继承旧资格。
准备器删除了对已冻结collection／decision／manifest及原source／geometry的五次重复身份读取，
只在冻结目标验证一次；winner记录成员绑定继续复用已验证身份，不扫描重型载荷。

当前尚无匹配新零间隙完整仪器的COMSOL模型。现行oaTOF Formal冻结二区OA，不能覆盖新的三区OA及侧孔。
110745冻结工况的OA加速跨度为300 mm、OA环数20，飞行管长度仍为600 mm，反射器两段分别10／5环，
另含真实八极杆；加速跨度与OA环数不能误写为飞行管长度和反射器环数，原Formal与新装配不能互相替代。COMSOL几何入口现已接入提供者的三区几何、实际环位／ON电压及显式机械侧孔，
二区／三区共用实体和零厚栅构造，旧二区专名builder已删除；当前只是源码与无商业软件回归，尚无对应新MPH。
具名入口现可显式`FieldDesignOnly`，完成单次静电求解并保存已配置的Cartesian粒子源，不进入粒子求解或其fallback。
冻结构建的显式产物根由公共路径解析器消费，检测器位置直接读取resolved坐标；MATLAB19项及Python28项定向回归通过。
匹配192618源的首次构建`20261024_210625__sim__comsol__192618-oatof-local-static-on-field`在公共容量准入被拒，
未启动COMSOL；failed运行与owner封存保留。该未执行提案为32 GiB磁盘承诺／24 GiB内存预算，
不能通过降低预算或抬高容量目标绕过准入。后续只退役已确认无消费者的旧私有载荷。
实物源码审查另确认：该COMSOL提案的人工外真空边界设为0 V，SIMION前端父域为零法向场，
局部COMSOL还明确排除多极杆金属／DC／RF。因此当前提案不能用于整机或同边界求解器一致性判定；
其原生提交暂停，先从同一父配方建立显式OA-local static-ON成对参考，核对数值box、域内实体、
人工边界、栅表达及共同真空样点。只统一边界类型仍不足以证明域和实体相同；不能把这些模型差异算作求解器误差。
局部静态场比较不代替全前端RF、有限脉冲、轨迹或命中等价。匹配输入与比较范围冻结后，才以新运行身份执行。
上述OA-only静态比较现由直属`paired_accelerator_static_field/execute.ps1`唯一编排，准备器仅为库函数，
旧项目准备路径与独立CLI已删除，无转发兼容。SIMION实际使用公共PA事务；有效HIT不复制PA。
显式COMSOL来源在任何原生阶段前核对，已解模型重开只导出；新求解先保存MPH及完成事实，再导出。
77文件冻结闭包包括两后端、Schema、公共运行器与宿主依赖。完整专属23项回归通过（36.314 s），
最终脱仓冻结执行1项通过（5.899 s），覆盖公开DryRun、失败封存、seal异常不改写科学终态、
公共小缓存及生成Lua的惰性PA调用；Ruff和PS解析通过。
独立审查随后发现导出失败时catch未把已保存COMSOL文件加入manifest，现已沿公共AdditionalOutputs补齐。
完整owner模块11项通过（41.834 s），真实catch／公共writer的惰性后端回归证明：保存后导出失败，
failed manifest仍绑定模型和原生完成事实，另一个consumer可显式复用；未改公共发布或另建恢复协议。
上述证据不包含原生SIMION求场、COMSOL建模／保存重开或数值等价，不能据此关闭跨求解器验收。
2026-10-25真实作者预检发现旧231302／110745前端嵌入的OA接口仍是单电极side-shield视图，
当前完整提供者为45电极`three_zone_square`，准备器正确拒绝；旧纯预检通过不再表示该作者当前可执行。
`paired_static_native_preflight_20261025/current_author_110745_complete_provider`已用当前提供者、公共配方解析器及正常prepare纯执行通过，
公共GATE耗时9.575 s。原100粒子投影、原源／metadata、clock／epoch及两份GEM逐字节相同，
几何差异仅组件variant与电极接口完整性；新场设计与173617已接受审计设计全等。
当前paired投影、box、ON电压及OA-only GEM也保持；没有读PA、求场或改写旧run。
后继`20261025_193652__analysis__python__current-parent-preparation`已沿公共GATE、容量与正常prepare CLI真实执行成功，
全部准备输入／输出及frontend_geometry、oaTOF resolved均由实际manifest绑定，轻量封存ready；没有PA读取、复制或商业求解。
原源、clock和两份GEM再次按原110745已发布身份核对一致；一次性owner已与冻结输入匹配后删除scratch原件。
新请求据该manifest绑定，从提供者repeller／三栅／20环位置之间的23个轴向中面各取中心及半孔半径四轴点，
115点全部通过共同孔内真空及净距检查，保留原数值box／边界／ON电压，不宣称全空间或收敛覆盖。
公开`execute.ps1 -DryRun`已实际完成`20261025_194231__test__python__paired-accelerator-static-field`，
success且native_executed=false；日志为`paired_static_native_preflight_20261025/current_parent_bore115_public_dryrun.log`。
初始单点作者仅保留为机制记录；尚缺明确数值接受范围及原生对照，全真空hmax=0.5 mm的24 GiB内存提案也尚未证明可行。
当前活动网格合同已改为明确v2：全真空使用作者声明的全局自动档位，实际电极边界并集使用局部hmax和增长率，
沿已有公共Size helper，在完整`sel_vac`上FreeTet；没有拆域、改变几何／电压／边界或按旧缓存选择网格。
显式设置、真实选择集及Size／FreeTet顺序回读不符则在ES前失败；automatic hmin仅记录原始表达式和实际几何单位，
不为无单位审计表达式求值制造额外失败。SIMION场身份仍排除FEM网格及样点，COMSOL复用继续核对数值域及backend。
三个完整模块经公共GATE完成27项32.610 s通过，含真实脱仓准备、非法／旧合同拒绝及缓存身份不变；
单位审计小修正另有1项公共回归通过，日志分别为`paired_mesh_v2_public_gate.log`、`paired_mesh_v2_audit_units_public_gate.log`。
旧194231仍为schema 1冻结准备证据，不改写；新网格属于新的数值作者，未继承全域0.5 mm资格，实际tet规模／内存与残差尚待原生验证。
原生提交前已沿公共退役流程删除三组无消费者的重复载荷：084909修复run的quarantine／snapshot_2 collision PA，
以及192618和094111两run各自的旧大域／入口细域carrier副本，共6份、12,845,612,256 B。
原owner的精确退役收据、修复journal、重建输入和负结果保留；当前110745／231302载体、IP／MR场与094111下游场受保护。
各组已按原保留理由重新封存并公共核验；084909第一次重新封存因理由与原封存不一致而拒绝，改用原理由后成功，未重复删除或手改账本。
记录为`iob_path_probe_20261024/retire_completed_repair_duplicates*`、`retire_192618_duplicate_carriers*`及
`retire_094111_duplicate_carriers_batch2*`。094111核验中的累计退役数含更早批次，不能与本次释放量重复相加。
清理后600 GiB目标仍仅余15.92 GiB额度；用户明确授权后，唯一容量政策的驻留目标改为700 GiB，
最低空闲保护和原64 GiB临时盘／24 GiB进程树预算保持。政策3项回归通过，原生运行仍沿公共准入。
`20261025_210836__sim__cross__paired-accelerator-static-field`已实际执行GEM→原始PA，
但在切换Refine阶段时因漏传公共必需参数`RetainedMemoryBytes`失败；未进入Refine或COMSOL，不构成场比较结果。
failed manifest与原生日志均已封存；scratch中的原始PA不冒充已发布工作场。
owner两处切换现明确传0，表示上个原生子进程已结束、不保留子进程内存；完整owner模块12项33.124 s通过，
新增回归直接绑定公共函数真实参数签名并执行两处owner调用，无商业执行或资源事务。
日志为`iob_path_probe_20261024/paired_stage_transition_fix_gate_20261025.log`；跨run恢复仍须沿公共producer handoff建立新运行身份。
该接入新增显式停止收据参数，以当前真实容量租约调用既有公共handoff，不另建恢复状态。
新owner按run config的真实run_id命名，避免短执行别名形成随机owner；前驱事务、manifest及公共停止收据冻结进新inputs。
公共小事务回归已验证终态producer交接、缺收据／不同身份拒绝、短junction身份及普通advance重放；
旧scratch保留但不视为完成场。脱仓回归发现公共freeze_file漏列入依赖库存，现补入同一消费闭包，不复制冻结实现。
完整owner模块该轮13项中10项通过、3项因这一闭包遗漏失败；修复后原3项28.289 s通过，
不将定向复验拼称整模块重跑。后继`20261025_212418__sim__cross__paired-accelerator-static-field`
在启动接管Python前遇PowerShell `StandardOutputEncoding`重定向错误，未接管事务、未启动任何原生阶段，已封存failed。
入口现沿既有前端调用模式直接重定向Python stdout／stderr到日志，再解析JSON，不增加进程或恢复框架。
但后继212817仍在Python启动前遇同错，证明仅改变重定向没有解决原因；未接管事务或执行原生步骤。
根因是调用把含startup_gate报告的整个容量会话序列化进命令行，而公共handoff只消费租约ID和owner。
真实PowerShell 7.6.8以120,000字符参数准确复现同一启动错误；现在仅传这两个字段，不增加运输文件或新协议。
正式回归提取owner实际投影赋值，用含120k报告的会话确认命令参数仅含两字段且小于512字符，再由真实Python读取，
保留Unicode、顺序及非零退出双日志／抛错检查；公共GATE 1项3.807 s及Ruff通过，原公开DryRun节点亦已通过。
后继`20261025_213138__sim__cross__paired-accelerator-static-field`已由公共handoff成功接管98A5…2D47原事务，
新owner为真实run_id，已完成GEM编译、原生Refine及standalone导出，不能据此宣称共同场比较通过。
运行日志为`paired_static_native_preflight_20261025/paired_bore115_mesh_v2_compact_lease_native_public_runner.log`；
原生Refine为9750次迭代、Delta 0.005 V、224.64 s；这是安装默认停止条件记录，不是场误差上界。
随后115点采样已执行，但Python键覆盖校验失败并正常封存failed，COMSOL未启动；工作PA已在公共事务封存inventory，不能重新求场。
只读复核确认115个ID及全部坐标经标准binary64解析逐位相同；pandas默认CSV解析把IDs46–50、86–90的native z坐标读低1 ULP，
分别涉及`89.944342608353708`、`201.42669554953019`。双侧使用`float_precision='round_trip'`后键差异为零，
无需放宽容差、移动样点、修改Lua或Refine。只读诊断当时尚未接入解析及sealed-inventory修复；后继源码与真实恢复结果如下。
事务仍为building但inventory非空，下一次正常advance应返回verify；公共producer handoff只适用于空inventory构建，不能再次接管封存成员。
原失败运行及诊断日志保留；该轮没有完成场发布、COMSOL模型或比较，后继分别记录阶段结果。
解析与恢复修复现已接入：runtime双读表及三个实际场分析入口均用精确round-trip解析，公共严格配对及原容差不变。
完整owner模块16项35.478 s通过，含等价真实十进制、真实1 ULP拒绝、空库存交接及封存库存新run验证发布；三分析12项5.456 s通过完整CLI输出。
后继`20261025_220837__sim__cross__paired-accelerator-static-field`已实际复用213138的2,277,181,528 B PA，
重新采样后公共发布generation `DFE5FE778A31784D8A3E0B3528C44094C43F6921EE60C3DB44EF45DB6F5B7571`，
原inventory与资产owner保持，没有GEM／Refine／Fast Adjust或PA副本；随后进入原COMSOL solver阶段。
23:13沿正常权限复核原owner、COMSOL及MATLAB进程均已不存在，旧执行句柄不可用，
Windows报告主机最后启动时间为22:48:43；该run仍为checkpoint，bootstrap残留RUNNING，不代表求解仍在执行。
run的COMSOL目录没有已保存MPH，尚无模型完成或比较结论。旧run已沿公共失败发布器记为interrupted，
精确遗留64 GiB租约已释放，停止载荷封存为ready（1,776,509 B／111文件），该run的junction已按精确目标移除，原科学输入与PA发布来历保留。
恢复须使用新run，沿已发布PA命中继续；未完成COMSOL解不能冒充可续算checkpoint。
另在本机官方恢复目录发现`MPHRecovery820date_Oct_25_2026_10-10_PM.mph`目录，
recoveryid精确绑定原服务器PID21824；26文件共943,597,672 B，末写22:44:57，包含几何、模型与solution二进制。
小型模型元数据的mesh设置及电极电压与本次冻结输入一致，但这些文件不能证明完整解或可续算状态。
COMSOL 6.4官方[ModelUtil.loadRecovery](https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_general.47.15.html)
已由新受管run `20261025_232014__analysis__comsol__owned-recovery-inspection`实际执行，
返回`Folder contains no recovery model`，未进入mesh／solver查询或MPH保存，也未Compute／Continue。
该run已正常failed／ready封存，保留943,715,498 B／38文件，容量租约、主机许可和junction均已收尾。
原目录与冻结副本经含隐藏项的精确清单／大小核对一致；原供应商目录不操作，失败栈及完整恢复闭包保留。
本次没有已证明可复用的COMSOL模型／mesh／求解checkpoint；不改目录结构或重包文件来制造恢复。
共同场工作流已补充完整mesh／std1／sol1保存后的阶段恢复点，沿同一原生事实文件区分`prepared_saved`与`solved_saved`。
同run先保存prepared模型再求解，解后覆盖同一MPH及事实；显式来源分别只补求场或只导出，不重建几何／mesh，不称为供应商中途积分续算。
实际junction回归先复现任务中的短路径在junction删除后失效；现任务生成边界直接解析最终路径，
不维护别名兼容表。完整对应模块17项38.957 s、Ruff与PowerShell AST通过，日志`paired_prepared_model_canonical_module_public_gate_20261025.log`。
该回归使用公共manifest及实际任务生成，但MPH是身份夹具；真实保存／重载及保留网格后补求场仍待原生验收，不能以轻量测试关闭。
后继`20261025_233735__sim__cross__paired-accelerator-static-field`已沿原预算和同一请求进入COMSOL原生阶段，
公共PA事务返回published／complete，继续使用同一generation；SIMION仅采样4.38 s，没有GEM、Refine或Fast Adjust。
日志为`paired_static_native_preflight_20261025/paired_mesh_v2_prepared_checkpoint_native_public_runner.log`。
该run在23:38:56、服务器启动约41.13 s时发生Temurin21.0.7+6／G1的`GC Thread#5`访问违规，问题帧为`jvm.dll+0x359148`；
LiveLink随后在`add_potential`的电位设置处报告NullPointerException，未进入mesh／solve／prepared保存，不能把此轮记为恢复点验收。
原始JVM日志已沿公共输入复制、保留及manifest发布归档到`20261025_234258__analysis__comsol__owned-jvm-crash-evidence/logs/hs_err_pid11568.log`，
归档run只声明证据保全成功，源科学run仍为failed；根日志在身份核验及发布后移除，不改源失败manifest。
此次L1 `migration_l1_prepared_field_memory_danger_20261025.log`在卫生阶段因该根日志停止，未执行后续测试；不能记作源码回归失败或通过。
当前仅核对供应商支持路径，不更换JVM、修改安装或把TBB allocator处理当作此GC崩溃修复。
后续`20261025_235103__analysis__comsol__paired-construction-diagnostic`沿原failed manifest的具名消费投影核验82项小输入，
只在冻结builder中加入逐电极标记和建网前停止点；两处源码变换可精确反向还原，未重画或修改实体／电压。
原生25个V0全部设置成功，50条前后标记完整，实际表达式解析后与原25电压逐值相同；
保存2,169,489 B的geometry／physics MPH，未建网或求解，未重开，也不认定JVM故障已修复。
run已自然success／ready封存（3,815,399 B／96文件），进程、许可、容量租约和junction均已收尾；
验收为`paired_construction_native_audit_20261025.json`，JVM只读诊断及官方出处为`owned_jvm_gc_diagnosis_20261025.json`。
据此继续原验证的新run为`20261025_235338__sim__cross__paired-accelerator-static-field`，同一PA generation再次published／complete命中，
原预算、请求、几何及电压保持，未新增Refine；日志为`paired_static_native_preflight_20261025/paired_mesh_v2_after_construction_audit_native_public_runner.log`。
235338已自然完成31,037,688个四面体的网格；00:28:04保存prepared MPH及原生阶段事实，00:40:43覆盖为
6,732,101,289 B的solved MPH，随后导出115点并完成比较。该run仅在terminal_publication阶段第二次应用retention时失败，
已沿公共收尾封存failed／ready，模型、网格、解和原始结果保留，不改写为success。
当前owner删除不必要的早期retention调用，仅在终态应用一次；原failed收尾仍用公共完成器，未增加幂等兼容层。
原生事实把四面体数写为`3.1037688E+7`；接收边界现接受正的整数型或整数值浮点，仍拒绝bool、分数和非有限值，
不舍入或降低校验。对应完整模块17项41.082 s通过。

显式`ComsolSourceManifest`表示消费冻结模型：不因当前未执行的构造helper或SIMION网格pitch／栅格孔表示变化重建COMSOL，
但必须匹配实际物理孔的中心／形状／尺寸、几何、电极角色电压、边界、box及COMSOL网格设置，验证来源模型／阶段事实与producer记录。
当前导出代码仍冻结进新run，不强制其与旧producer文本相同；prepared来源沿当前冻结求解代码补求场。
26个公共消费夹具情景及完整owner模块18项49.721 s通过，报告为`comsol_explicit_source_consumption_counter_audit_20261026.json`；
早期建议给四个未执行构造helper追加哈希的解释已撤回，不增第二套完整性协议或物理文件拆分。

新`20261026_011244__sim__cross__paired-accelerator-static-field`已沿原请求和预算显式消费235338，
同一PA命中，重开原solved MPH后只重新导出及比较，最终success／ready封存；未建网、求解、Refine或复制大型模型。
两份采样CSV分别12,009 B／12,030 B，均与235338逐字节一致；指标仅来源路径不同，数值相同，新run无MPH副本。
这关闭已解模型重开、导出和终态恢复功能；prepared保存已实测，但跨run重开prepared后仅补求解尚未特意执行，
不为制造中断证据主动杀死健康求解，也不称为真正求解器checkpoint续算。

115点的差值RMS为Ex 129.642、Ey 219.970、Ez 272.560 V/m；Ez相对COMSOL RMS约1.81954%，弱横向分量差异更大。
没有获批的数值等价容差，故仅为共同边值静态诊断，不授予数值、粒子或Formal资格。
只读对称性核查发现：冻结BVP关于y=0镜面对称且y=0正好节点75，69个面内点的Ey RMS在COMSOL为1.99644、SIMION为219.310 V/m；
23对±30 mm的Ey奇对称残差RMS分别4.99716、340.021 V/m。
官方PA外边界一侧梯度规则不能直接解释距离该边界75 gu的内部面；当前不能归因于插值或Refine。
报告`paired_finite_pulse_preparation_20261025/paired_field_symmetry_review.json`保留负结果；下一步只读少量原PA节点势／flag及邻点梯度，
先定位储存电势或梯度问题，不移动点、强制对称、平均镜像或放宽容差。
只读原生审计`20261026_012556__analysis__simion__paired-field-symmetry-probe`已封存success／ready：
144个真空节点、64组镜像对的势差最大21.252337 V、RMS 11.443392 V；flag均为false且镜像一致。
中心差分与field_vc的非零Ey接近，说明不对称至少已存在于存储电势，不能仅用梯度插值解释；不证明全域金属mask。
原生产日志确认9750迭代、Delta=0.005 V、224.64 s，随后native_copy正常完成；该Delta是停止变化量，不是实际场误差。

`20261026_014055__analysis__simion__ordinary-pa-refine-diagnostic`已沿原64 GiB／24 GiB预算在一份受管可写副本上
继续普通Refine，显式convergence=0.0005 V；未重建GEM、COMSOL或修改发布源。
细化前115点与原SIMION输出逐值相同；14020次迭代后返回0.000451555678 V，原生耗时573.18 s，
保存、关闭、重开后完成同点采样，无预算告警。8个金属样点镜像相等、前后不变；声明电压残差0～1.393e−11 V仅如实记录，不新增资格容差。
镜像势差最大值21.252337→5.243705 V、RMS 11.443392→2.834472 V，y=0面Ey RMS 219.310390→62.387883 V/m；
对同一COMSOL的Ex／Ey／Ez差RMS分别129.642194→39.125557、219.970252→63.986940、272.559682→71.942117 V/m。
这证明继续细化明显影响当前结果，残余不对称仍存在；冷／热初态与默认跳点迭代工作也不同，不能将改善全归因于convergence，
更不构成收敛或数值等价。未追加扫描，后续先明确数值验收边界，不用小探针或CPT成功掩盖此限制。
派生PA归014055，封存2,277,444,524 B／28文件，无旧cache身份复签；实际消费用manifest的canonical记录。
其两个描述性参数仍含已释放alias路径，不作为资产权威，不修改封存记录或沿无效路径重建副本。
两次诊断的临时源码均在与冻结输入核对后清理，完整原始结果和重建输入保留。

`20261026_002112__analysis__simion__paired-ideal-grid-occupancy`还已只读核验同一PA：162个raw节点检查确认三理想栅各仅一层电极，
电压符合冻结输入；58个世界查询中理想栅透明、实金属及侧孔对照符合声明。原面到节点偏差−0.020813196589 mm属于实际离散记录，
不补偿坐标或移动物理几何。未Refine、Fly、Fast Adjust或复制PA；仅为声明样点的占用／电压证据，不证明全空间或有限脉冲轨迹。
运行日志为`paired_static_native_preflight_20261025/paired_bore115_mesh_v2_sealed_recovery_native_public_runner.log`。
该结果证明本次采样审计失败后的真实场恢复；不扩大为所有求解器checkpoint、完整后处理恢复或物理资格。
各向异性电场单位已由本机SIMION2020（8.2.0.11）两个官方随附示例核对：
`examples/molecular_beam/aa_deflector_stark_build.lua:27–28`及`examples/octupole/octupole_ideal_build.lua:71–72`
均将field_vc各分量除以各自pitch得到V/mm；当前再乘1000导出V/m，未为此新增求场或探针。
并行准备已核验110745原100个ID的birth／pre-pulse／native pulse状态，预脉冲时刻与6D逐值相同，前脉冲损失0，epoch=0。
原脉冲为显式timed区间`[50.68181818181818,57.95454545454545) us`，没有winner decision；当时winner-only选择器不能表达该源，不能伪造自动搜索决定绕过。
该准入限制现已移除：当前schema9使用`producer_manifest`，未声明decision时同一selector消费全部实录pre-state，
声明真实decision时保留原detector-blind子集选择、顺序及绑定验证；不接受旧winner_manifest字段，不兼容新作者schema8。
原母群births、ID、状态、clock与first-gap／原实例frame核验保持，source provenance明确记录selection_basis；整机严格retrace仍要求其原科学decision。
两完整模块首轮52项中51项通过，唯一历史193652请求复制测试未升级新作者版本而失败；仅升级该测试新副本至9后原节点1.435 s复验通过，
不改历史输入或拼称完整重跑。真实110745的100态及full/local／父坐标变更源字节不变量已通过，日志`explicit_timed_source_modules_20261025.log`与`explicit_timed_source_author_recheck_20261025.log`。
当前源准备及pre-pulse replay两完整模块已在上述修复与Cartesian扩展后重新联跑，55项54.456 s全部通过，相关六文件Ruff通过；
日志为`timed_source9_complete_modules_final_20261025.log`。此轮关闭这两个模块的完整回归缺口，不代表全仓L1／L2或原生CPT已通过。
现有Cartesian源导出器也已支持可省decision，同一selector导出全部实录状态，并记录母群、原birth map和仅源准备的claim。
完整对应模块22项22.050 s通过，含真实110745原100amu／+1、100 ID的实际CLI及逐ID6D／clock／birth对照；
仍不代替CPT原生或不同场问题的轨迹比较，日志`paired_finite_pulse_preparation_20261025/cartesian_optional_decision_public_gate.log`。
通用selector／producer错误文案随后去除不适用的winner术语，真正decision分支保留；5个既有相关节点0.218 s及Ruff通过，逻辑和容差不变，日志`timed_source_terminology_public_gate_20261025.log`。
25个ON电压与当前共同BVP全等、25个OFF电压全0；仅此OA-only、无RF、无电荷且真空介电常数为1的问题可依据线性唯一性使用零OFF场。
后续需显式timed状态准入和窄OA-only CPT接线，复用公共粒子表／时钟及已有Cartesian源读取；现有整机retrace的detector／12场掩码不能直接套用。
跨后端须另执行同BVP的SIMION局部timed飞行；110745整机仅提供源及来历，不充当不同场问题的轨迹精度基准。
实际record身份与最小接线审查保存于`paired_finite_pulse_preparation_20261025/real_input_review.json`，标记review_only_not_executed。
100个原状态均在冻结数值box内；此前按120 mm环bore计算的IDs75／76余量0.00515／0.01921 mm，
并不代表实际近壁：全部状态z为−20.441759～−16.976939 mm，严格位于repeller与grid1之间、首环之前，
该段实际自由横截面由140 mm屏蔽内孔确定，横向净距至少10.005151 mm、轴向至少1.487428 mm。
场采样专用0.2 mm clearance及未使用的通用粒子标签均不能成为这份既有10列Cartesian源的假阻断；
不移动、裁剪或补造源。首次实际CPT仍须核对sel_vac、100个原生初态及唯一绝对释放时间，不能由解析准备推定原生准入已通过。
窄有限脉冲已实现为[独立工作流](../../workflows/paired_accelerator_pulse/execute.ps1)。
作者只声明静态场producer、实录源、绝对观察时刻及数值控制；脉冲、物种、25个OFF电压和完整母群从原生产者派生。
恒定OFF为零、ON直接使用同一已解场，不增加OFF场、差场或补偿变换；SIMION仍使用原发布PA，014055诊断PA不替换基线。
COMSOL只在原模型增加CPT，Compute成功先保存唯一粒子MPH与完成事实，再读取轨迹；后处理失败可重开导出。
恢复沿公共完整批机制执行缺失阶段；完整CSV已经发布时直接分析，不重开MPH、不重飞。
跨次恢复平铺绑定原CPT生产者，保持原模型唯一归属，不递归搜索历史。原生完成事实、原ID和声明时刻完整配对；
缺态、非有限值和错时分别报告，没有获批误差预算时只发布诊断差值，不授予数值等价。

当前无求解器回归：准备8项8.989 s、runtime／恢复20项11.180 s、比较4项0.108 s通过，分别覆盖最小作者合同、
冻结路径运输、实际110745的100态、平铺多次恢复及完整时刻外配对。共享源路径修复两模块55项40.851 s、
Lua格式器实际消费者三模块78项35.798 s、COMSOL提供者局部位姿两模块16项2.967 s通过。
IOB验证回调收回具体工作流，公共执行器只调用显式after_build／after_first_fly阶段；已完成相关失败收尾与恢复回归。
这些结果不代替新脉冲原生求解；完整入口最后整合仍须复核。
真实MATLAB输入合同运行`20261026_022056__test__comsol__paired-pulse-input-contracts`已通过12项，
未打开模型或Compute。真实作者经新owner冻结DryRun为
`20261026_034435__test__python__paired-accelerator-pulse`，success／ready、N=100、native_executed=false。
其显式最大步长为1 ns、相对／缩放绝对容差均1e−8、SIMION Q=10，16个绝对观察时刻包含源及ON／OFF边沿，
末时刻65.22727272727272 us；这些是本次诊断数值输入，不是仓库默认或精度资格阈值。
后续原生仍须确认真实sel_vac准入、100个初态、释放属性、边界选择、粒子数组及保存重开行为。
最终owner完整5项30.080 s通过，含49文件闭包的worker／analysis／恢复导入；开发标准及PS AST通过。
首次原生`20261026_034904__sim__cross__paired-accelerator-pulse`在PA元数据核验前发现PS内嵌Python调用漏冻
`pa_family_cache`，failed／ready封存；未执行Fly、Refine或COMSOL。实际模块及传递依赖已补入同一consumer，
冻结库存收敛为55文件，实际覆盖公共PA模块的顶部传递导入，排除本次不调用的退役工具。
最终55文件脱仓回归直接从owner内嵌Python提取导入并执行，1项11.980 s及Ruff通过；
原有求场及源证据不受影响，不把启动失败视作物理负结果。
后继`20261026_035550__sim__cross__paired-accelerator-pulse`已实际直接载入原发布PA并保存单实例IOB，
未复制PA或Refine；独立重开在Q核验处失败，因此尚未Fly或启动COMSOL。原生日志保留，
该核验已按本机官方`examples/collision_rs/test.lua:15–19`和现有正式builder收敛到Program cfg及load／initialize_run挂接，
不读取或改写命令上下文Q；14项回归4.202 s通过，实际Q数值仍为10。
后继`20261026_035956__sim__cross__paired-accelerator-pulse`已越过构建／重开，执行首批10粒子，
原生报告10 splats／0.13 s；但终态记录在`terminate`读取不可用的`ion_splat`而失败，不能作为完成批次复用。
原始轨迹与错误已封存。修复后emit由允许的回调显式传入raw status，terminate传空，不沿用上一回调状态或推断实体；
禁止终态读取该变量的真实Lua回归及收集／回放共14项4.452 s通过，Ruff通过。
后继`20261026_040326__sim__cross__paired-accelerator-pulse`已完整执行原N=100基线及保存工作台默认回放，
逐粒子比较passed且differences为空；全部100个原生停止保留unknown，不据此推断碰撞实体或性能资格。
调度计划上限14，实测峰值并发1，5 s启动间隔长于约2.4 s进程时长；不能把计划并发当成实测。
同wave动态采样已看到单worker约2.875 GB并用于准入，但该次持久profile仅记首批约18.5 MB；公共发布缺口现已修复，后续从实际已完成worker保存峰值及其准确工作量／PID身份，
仅峰值更高时替换首批测量，不混用不同worker的CPU。12项公共回归21.641 s、Ruff和PS解析通过，历史profile保持原样；
不得把该首批值当作模型真实峰值，现有运行无内存危险事件，不为测量重飞。
COMSOL同run已加载原ES模型并越过原100源的sel_vac及边界分区检查；在WallCondition错误token处failed，未Compute CPT。
本机6.4合法token为`Pass`，现已修正且5项专属回归／Ruff通过，物理透明内栅语义未改。
恢复预检发现原回放日志嵌入短alias，而同producer已发布永久路径；仅日志按冻结bytes／SHA投影到唯一已绑定记录，
不重建alias或扫描目录。真实040326只读预检已确认baseline／replay可复用，CPT未完成；15项恢复回归4.752 s通过。
新owner回放日志改写canonical位置，五种恢复子情形4.088 s通过；多次consumer借用日志通过同producer明确completed_parent_*输入引用闭合，同路径去重而异路径同身份拒绝；
16项完整恢复模块5.731 s及新增去重断言0.976 s通过，Ruff通过。
实际后继041645已跳过全部SIMION，COMSOL配置回读因Z表达式属性被当作double而failed、未Compute；
现沿原属性表达式求值，原+1电荷不变，6项回归通过。后继042142已沿041645再次恢复，只补CPT；没有新SIMION Fly／PA加载、Refine、网格或ES求解。
当前CPT尚未报告完成，raw粒子MPH尚未保存，不声称有可用粒子checkpoint。
单服务工作集已超过原24 GiB树规划阈值，已告警；04:34观察时系统仍约11 GiB可用，未因阈值或日志静默中断。
该观察只代表原生服务，不伪装成完整进程树测量；公共COMSOL预算观测边界另行核对。
并行源码L1为`migration_l1_pulse_runtime_cad_geometry_20261026.log`，尚未结束；多极杆458项仅一个新入口package夹具缺字段，
补齐真实artifact_run_dir／result_dir后定向6.310 s通过。保留整轮阶段失败，不拼称完整L1已通过。

完整oaTOF几何／CAD准备已改为共用原实际feature tags，OA环与反射器环统一自然排序，删除固定五OA环及重复帮助函数。
8项CAD MATLAB Unit已准备但未执行；GeometryOnly API在原geom1.run后保存并早退，10个ArtifactContext方法尚待真实MATLAB执行，
静态／开发标准通过。这些不授予几何保存重开、CAD、GUI或Candidate资格。
后续作者输入位于oaTOF项目scratch的`20261026_044500__comsol__geometry-only-preparation/geometry_cad_request.json`；
18文件公共freeze_file脱仓快照及Python模块原点检查通过，一次性脚本和TEMP已清理；实际几何run等待本链闭合。
该产物归完整oaTOF部件，不覆盖上游多极杆，不能借integration owner绕过提供者路径保护。

RF相位可沿已绑定频率、初相和唯一时钟派生；species、权重及谱系所需标签仍须在源作者投影中显式绑定原始证据，不以静默默认补齐。
真实N3小输入的公共GATE纯投影另核验原5个cache key及六组扰动：频率／初相及审计标签／样点均不使场失效，
第二实例DC只影响carrier，pulse工作电压只影响pulse，共用RF数值参考幅值影响全部三个RF响应。
细域只绑定对应parent成员；这不代替N2／N3原生独立场与驱动验收。实际输入身份、扰动及结果为
`multi_instance_phase_author_20261025/field_identity_audit_20261025.json`，标记not_solver_run。
N2／N3后继作者位于`multi_instance_phase_author_20261025/current_schema9/{n2,n3}/request.json`，已沿正常prepare／compile纯执行通过。
新作者将release_spec改为直接引用旧冻结100行CSV的recorded_birth，不重新物化或采样；两案GEM、geometry、field_design、raw／projected源、clock／epoch字节保持，
原4／5个key、Program、FLY2和instances也全等。build_metadata仅下游小receipt的新inputs路径不同，bytes／SHA及内容相同；
报告为同目录`preparation_report.json`，原CSV及提供者仍是必要依赖，不能随旧临时目录一起删除。此为作者／准备证据，N2／N3原生验收仍开放。
后续从同一父配方派生oaTOF实例局部范围，核验真实三栅拓扑、选择集、侧孔及电位并保存重开，
复用既有oaTOF ES／CPT及重追踪边界，避免为本次验证另建完整RF整机MPH或第二套出口观察协议。
源须消费真实完整链发布的预脉冲状态交接，保留粒子身份、母群及唯一时钟；在相应SIMION成功结果和
匹配的几何／电压／模型证据齐备前，不生成可冒充验收通过的arm，不授予跨求解器资格。
新SIMION实际驱动仅在`[t0,t0+width)`叠加前端`pulse_delta`，RF及下游静态场各保持自身角色；
现有COMSOL／retrace仍是静态ON，不能据此关闭有限脉冲对等。后续须显式冻结相同开关及时间原点，
实现ON／OFF准静态场的时序消费，或以逐粒子真实场差及科学预算证明声明窗口内静态表示足够；
没有该证据时不能靠“粒子通常已经离开OA”、延长脉冲或修改源替代验收。
有限脉冲原生验证脚本为oaTOF项目的
`tests/comsol/test_finite_pulse_field_superposition.m`：同网格OFF／ON场、独立静态场、非整齐开关时刻，
以两档容差对照解析轨迹，并检查保存重开后的默认Compute。它属于长期数值回归，首次真实运行仅完成静电两态后失败；
后继`20261024_163000__test__comsol__finite-pulse-superposition-timecap1ns`已完成原生微例程，具体误差和保存重开证据归oaTOF项目PROJECT。
该微例程证明实际solution绑定、strict边沿与1 ns内部步长的声明范围，不能代替真实OA几何／100粒子CPT或跨后端比较。

16项实际装配共享核已移至`integrations/runtime/`，空间绘图移至`integrations/analysis/`，旧17处源码删除，
无转发。root local／cooled不再冻结旧family目录，也不再加载旧cache／binding大包装；旧整机实际caller已改为
消费同一新位置。公开绑定由唯一出版器刷新，不手工改SHA。共享核回归与脱仓检查通过。
共享核迁移时的直属集成251项测试及Ruff通过（267.106 s）；旧整机与新Program的52项、提供者普通Lua回归及
八极杆配置7项另通过，存在覆盖重叠，不相加声称总数。旧family的最新静态门禁926项通过，
3项明确跳过，8项商业检查已移出默认发现；这次重跑覆盖删除无消费者的N=1作者工具后的全部默认发现。
文档结构检查291文件、0错误；生成绑定已由唯一编译器刷新并通过新鲜度检查。
最新直属公共门禁执行422项，出现7项MR共享测试夹具的旧转发导入错误；夹具现已直接导入IP提供者，
7项几何与17项提供者测试在修复后联合通过，不恢复转发。该轮全量门禁仍记failed，不能把定向修复
当作已经取得新的完整门禁PASS；后续整机分批接线稳定后统一重跑。
OA–TOF布局catalog已移回提供者的`config/single_flight_layout_profiles.json`；所有实际caller只读该唯一位置，
无转发或副本。布局编译不再隐式读取旧`accelerator_phase_space_match.json`，有限区间profile使用自己显式声明的参数；
该历史相空间拟合合同仅供仍实际消费它的源／理论工作流保留。两个活动theory campaign的仓库引用均由原出版器刷新，freshness通过。
29项focused回归覆盖有限区间、300 mm／20环、原affine源和真实公共冻结后的脱仓编译；
三种既有布局的派生数值保持，仅删除无人消费的历史profile路径元数据。

审计确认剩余15份成对binding仍由公开入口的具名exploration或活动campaign实际消费，不能仅因未列入默认发现而删除；
旧N=1烟雾campaign本身仍是注册诊断，待其真实消费者替换后再退出。其无消费者的独立作者工具、四项专属测试、
MR→OA纯参数转发脚本和三项无人读取的MR接口描述字段已删除；直接调用OA提供者入口，真实编译／人口行为测试保留。
不复制旧缓存fallback或父子恢复状态机到新架构，不为退役过程增加空registry兼容层。旧owner的历史artifact身份
与缓存处置责任保留，活动源码迁移不能改写历史证据。

旧缓存入口已删除扁平schema 2校验／fallback、两个固定builder SHA的跨key替换及失用参数；
活动缓存manifest只接受schema 3。保留精确key下的current命中、有效非current generation恢复及公共构建／发布、
锁、lease和owner退役。148项回归通过，另1项因本机缺少R03历史population证据跳过；历史receipt和科学schema 2未改。
无生产调用的`Test-RfReusableCacheEntry`布尔包装已删除，相关行为测试改用实际resolver并移除重复步骤，
本切口净删50物理行；正式CLOC另行统计。6项回归通过，覆盖命中、损坏拒绝保留、MISS、历史generation
恢复和并发锁只构建一次；生产缓存机制及人工owner退役入口保持，未删除任何载荷。

无生产调用的`Request-RfFineCacheRetirement`转运函数及其专属测试已删除；操作说明直接链接
既有Python owner API。科学重建证据审批及其两项行为测试保留，公共维护仍是唯一删除器；
两项owner语义与三项缓存发布／损坏拒绝／私有副本回归通过，未删除PA或改变科学输入。

本轮继续移除实际重复工作：单反射准备器不再另外写出无人消费的`composition_plan.json`，
完整计划仅保留在原有`frontend_geometry.json`内；18项聚焦回归通过。冷却参考物化复用本次调用
已验证的上下文，场读取／身份核验从两次减为一次，独立调用仍核验场身份；19项回归通过，
Lua及FLY2与原路径逐字节一致。两项均未改变几何、母群、驱动、碰撞或时钟。
整机runtime正常物化不再在CLI与物化函数间重复读取／核验场设计，纯`--check-flight`仍独立验证；
IOB控制核验复用刚验证的record，首次绑定仍计算身份，路径错绑及内容漂移仍拒绝。
完整runtime模块19项回归通过（7.565 s），未削弱跨进程或PA边界。
冷却几何准备现复用单向的实体准备→最终网格／孔离散说明→GEM包装；每次OA投影、主体渲染和GEM包装
由两次减为一次，旧编译API及被丢弃的中间GEM已删除，无兼容包装。原canonical场域也不再为取得网格
生成空主体GEM。父CSG仍按明确的源几何网格渲染，裁剪只改变数值域，原扩界及对齐顺序保持。
同时修正局部网格诊断的孔离散说明：原先保留裸域原点，现取最终PA的原点及网格。实际原生孔检查本来
使用正确的顶层网格，不能据此宣称旧场或原生检查错误。二区／三区的完整域及裁剪域四工况对照中，
GEM字节及其他合同字段全部不变，仅两个裁剪工况的孔离散说明更新；完整域说明不变。
首次比较脚本忽略公共孔合同既有的12位小数序列化，修正比较口径后通过，未改生产精度或校验。
五个完整准备／网格／场设计／裸前端模块120项通过（13.978 s），六个共享依赖／脱仓冻结／消费模块
52项通过（56.895 s），均无跳过；Ruff及生成绑定新鲜度通过，公共GATE正常释放。该轮生产代码净增8行、
测试净增22行，不以调用次数减少宣称已测得运行加速；未执行原生求场、飞行或改写冻结资产。
本轮补充L1在上述runtime末次减量前通过2,536项、5项明确跳过；随后旧包装删除的5项及runtime的19项
相称回归分别通过。上述均无商业求解，不授予完整新OA→TOF原生或GUI验收。

## 首条消费的实施过程与接口边界

本节保留首次接入的实施边界；其中准备／纯测试证据不覆盖其后真实运行。当前整机Fly与回放以本页192618记录为准，数值／物理及GUI／CAD资格仍分别验收。

现有[局部前端准备器](../../workflows/local_frontend/prepare.py)
已改为schema 3作者输入，取消独立registration、connection及组件内transform；仅从冻结完整父plan
派生本次范围、直接位姿和间隙，再投影到现有GEM／PA+接口。源到guide的坐标映射仅由IP提供者发布。
二区／三区的准备器回归保留完整母群、网格、场基和驱动行为；新owner下已闭合三区N=100的实际运行对照。

准备阶段只解析一次原始母群，复用唯一状态变换生成canonical输入；不再生成被丢弃的ION数据或无人读取的
准备态Fly2、重复组件／场基／诊断JSON。来源身份首检后直接用于生产者绑定，冻结副本各核验一次；
删除准备器的全目录输出哈希和无消费者源码哈希。实际原生缓存构建器身份与终态manifest仍由原发布边界负责。

- [IP guide提供者](../../../projects/dual_pressure_rectilinear_ion_processor/analysis/guide_interface.py)已发布统一机械接口，
  保留八根实体杆与两个电气组的区别；它不是HP／LP或真实上游多极杆的等价物。
- OA两／三区由现有编译器发布真实矩形外壁侧口和组件电极身份；不复制CSG、不混入局部PA编号。
- 单反射oaTOF的实际加速器尺寸、环位置和侧孔投影已收回提供者的唯一解析；原二区、三区及300 mm候选GEM
  字节保持，78项相关回归通过。提供者另发布窄`accelerator_side_shield`机械视图，直接读取renderer使用的同一
  projection；实际局部孔与粗参考孔分别保留，不把参考孔径当机械孔。该视图不枚举整机电极，尚未构成新整机消费。
- 新配方不复用旧成对端口的“圆孔＋单一面电位＋接地套筒”假设，不虚构RF开口面`0 V`。
  几何接口不发布clock或handoff；电极驱动和唯一instrument clock仍须按科学输入明确绑定。
- 准备器冻结导引与OA提供者机械接口和composition plan，源时钟仍由冻结科学输入传递。
  两／三区既有fixture已用于几何、GEM、PA+、电压及完整源状态回归；三区的真实运行对照见下文，
  二区尚无迁移后独立飞行证据。

原连续整机编译器仍从旧handoff端面定位多极杆屏蔽，并在装配层重画shield／sleeve／terminal；
新贯通出口设计不能直接替换输入后宣称几何一致。下一步由独立与整机renderer共用同一提供者实体投影，
装配层仅应用显式位姿与电极映射。连续整机必须消费原始出生表及canonical clock，不能用出口表再次重飞上游。
多极杆公共renderer现已提取同一native frame的物理实体输出，独立renderer共用原生成器；
48项纯回归及6份standalone GEM基准保持。装配输出不含PA原点或数值吸收面，真实贯通出口端盖／孔仍保留；
新整机消费及其真实飞行尚待完成。实际历史run的GEM与当前renderer内容相同，但换行不同，不宣称原始文件SHA相同。
初版`single_reflection_flight/geometry.py`直接组装提供者实体时，仅接受明确零间隙、multipole完整Z→X循环旋转、
oaTOF原frame单位位姿及作者数值域；后继已改用OA-local工作frame及公共相对变换，父装配整体位姿不再受该初版限制，受支持相对姿态限制仍保留。
真实端面经公共layout校验，实体只有一次pose，PA原点留在最外层。
物理body只渲染一次，PA包装仅添加数值网格与原点；不同域可复用完全相同的body，不再次调用提供者。
15项几何行为回归通过，原300 mm夹具GEM与metadata逐字节保持，真实intermediate2与全部20环仍在。
这组回归只验证渲染边界分离，覆盖多极杆与内嵌加速器前端，不授予完整分析器飞行或电压资格。
后续多域规划、父场边界耦合与下游工作台的实现和验证边界见下文。
300 mm候选的square与活动kinematic envelope物理尺寸不同；准备测试的开孔、数值盒及源位姿不是生产默认，
不得把独立夹具、某次准备测试或旧N=1选后母群当作新整机科学作者输入。
提供者现已将SIMION实例和场采样点收敛为同一`derive_simion_geometry`，最终布局更新后重新派生，
不再保留候选修改前的陈旧位置；baseline序列化逐字节保持，27项相关纯回归通过。
新root几何准备同时从同一最终resolved发布flight-tube／reflectron／detector的下游PA实例描述，
不读取旧Formal IOB或旧derived表；detector明确为数值marker。前端GEM字节保持，18项相关纯回归通过。
这些实例描述尚未生成新的PA或完成完整N=100整机飞行，旧运行时的二次placement覆盖仍待退出。
真实through-exit分段杆的电气准备已接入同一几何metadata：四／六／八极的16／24／32个杆段实体
均保留四轴段的8个杆电气组；连同两组原生静态边界和20环三区OA，当前各为35组物理电极，
以6个独立电压模式表达当前驱动子空间。实体数量由提供者派生，不将八极的32片作为通用准入条件。
ground 9／10／11保持独立身份；非零接地、组内冲突或超出杆两模的分段DC直接拒绝。
123项新几何及原frontend／Program纯回归通过；实际Program投影现支持32片去重、原ID／绝对时钟RF kernel及完整35组动态系数，
63项相关纯回归通过。当前电气数学用于派生三个实际工作场，不再为新整机发布六份归一化响应；
四／六／八极真实提供者的完整prepare、Program和43／51／59点普通Lua PA API审计已通过首轮20项回归；
本次数量派生修改前后，八极GEM、geometry、field design、投影源、Program及metadata六项字节一致。
这不是真实原生金属采样；数值验证、场库与完整飞行仍待闭合。

新[整机运行入口](../../workflows/single_reflection_flight/run.ps1)默认`Fly`，也支持显式`FieldDesignOnly`或`WorkbenchOnly`；它创建、封存并以`solver_review`保留唯一受管run。
内部`execute.ps1`仍支持`PrepareOnly`、`FieldDesignOnly`、`WorkbenchOnly`或`Fly`及已有受管run，只由run owner调用；不复制旧整机生命周期或建立隐藏资源预算。FieldDesignOnly以明确预算进入原公共容量、资源与场阶段。
当前执行顺序是冻结准备、预算／母群校验、前端资源下限与纯下游计划预检，再准入前端及下游原生调用；
预算必须声明`stage_limits.instrument_field_design`，覆盖整段而非只覆盖前端。
每个前端数值域发布三个实际工作场，父域与可选入口细域分别使用现有公共cache事务；改变细网格不重求父场。
父域零Neumann求解，细域每个kind只从同kind公共父PA采样Dirichlet边界，复用公共ordinary builder。
令父／细节点数为P／L（无细域时L=0），三个工作场的公共payload下限为`24(P+L)` B；
构建RAM下限为`max(20P,10(P+L),20L)` B，运行场RAM下限为`30(P+L)` B。
预算必须高于不含header／进程开销的下限；通过只代表未被下限否决，不承诺峰值可行。
容量准入直接消费冻结下游计划：承诺包含下游已知阵列、必要IOB载体运输及冷缓存时必须发布的前端场载荷。
未声明场来源时不预先假定缓存命中，也不把运行目录告警阈值当作第二份磁盘预留；不再预留或物化六份私有前端工作场。
header、日志与进程开销不在上述下限内，不能由准入通过推定峰值可行。
候选实现允许request的`providers.frontend_fields`显式引用已封存生产run中的成功前端场receipt。
prepare仅冻结receipt、生产run的manifest和各域小型identity记录；即使生产run后来在飞行阶段失败，
成功场阶段仍可作为来源。执行时比较实际GEM、网格、工作电压、父域边界、SIMION及原生构建器身份，
保留原生产key并只读取receipt指定的generation；编排器自身修改不伪装为原生产代码身份。receipt中的
短期execution alias不是长期身份：消费者绑定receipt显式声明的公共ordinary generation，
比较原key、generation身份、成员清单及小型发布元数据，不重复全文哈希PA，不把`.paN`/cache family交给SIMION。
实际Workbench／缺失批次物化前，公共入口还校验该generation的持久publication pin；
运行期只读guard与公共容量保护持续至最后一次IOB重开／默认Fly回放结束。
必要载体运输与工作场科学权威分离，不建立第二套场库。声明的来源缺失或不匹配直接失败，
不搜索最新代际、不回退重求。公开执行模块12项回归通过（462.247 s），
包含来源容量准入及既有完整／局部、发现／回放和失败收尾。完整Fly与默认回放后来由上文192618闭合；必要IOB载体运输另见上文运输记录。
来源分支通过实际PowerShell双域回归：公共事务先以明确inert原生边界发布小型fixture，
再显式消费同一代际；当前来源分支直接引用公共普通PA，不建立六份副本，
也不得probe、开启事务或调用原生求解器。移除所声明代际的manifest会明确失败，不转为重求。
实际094111生产证据另经纯准备／计划／代际元数据预检：保留父／细两域原key，两个GEM及投影源逐字节不变，
未读取、复制PA或启动求解器；后续192618实际消费同源场，原运行不改写。
若成功场receipt本身来自借用者，下一消费者仍冻结该receipt及其直接生产者manifest，保留真实工作流来源；
小型identity按该manifest中的内容身份唯一定位。旧`asset_owner`记录不再赋予run私有PA的资产权威，
也不递归读取前代receipt或要求后续请求改选原始receipt；真正场资产始终绑定显式公共generation。
单层owner接线的四模块首轮110项仅一项失败：无借用owner时重复校验同一producer的config。
已收敛为同一producer只冻结／校验一次；完整准备模块及链式复用相关32项复验通过，
其余执行、工作台runtime和下游模块的本轮通过结果保留，不重复运行。链式夹具覆盖借用者重命名identity及过期alias，
按固定owner manifest中的内容身份唯一绑定实际小identity，不依赖借用者文件名或递归前代receipt。
下游显式复用已接入：`providers.downstream_fields`引用成功的原生发布receipt，prepare冻结其manifest及
command plan；来源可与前端独立选择。同一producer的前后端来源共用一份冻结manifest与一次config校验。
规划器比较完整oaTOF提供者身份及八项原生构建资源，复用现有运行时投影预检九个文件的路径／大小／发布身份，
返回零native构建步骤；前端新建场与必要IOB运输副本分别按实际新增字节预留。缺失或漂移在前端昂贵操作前失败，不回退重求。
原receipt的execution alias仅作为原transport根；每个PA取原根下的相对路径，直接映射到生产run，
再与冻结manifest的精确output路径及身份比较，不按basename搜索。运行时沿原immutable源guard直接消费，
保护生产run，场复用不建立新cache或PA副本；IOB运输按上文记录单独处理。原IOB构建／重开已在这些PA的保护句柄持续持有时通过；
构建器只保存IOB，静态下游不参与前端Fast Adjust。
23项准备测试、40项下游／运行时测试及新增公开完整母群＋默认回放来源工况通过；后者供应商边界明确为inert替身。
实际094111的三资产九文件另经同源前后端纯预检通过：零原生构建步骤、只冻一份manifest、GEM和源不变，
未读取或复制PA；后续真实整机复验见上文192618。
原公开进程包装器在每步保留独立日志／usage，并以冻结预算准入资源；wall-clock 超限只记录告警，
不终止健康求解器、不缩减后续阶段限制，也不阻止正常发布。失败仍登记已有证据并释放host与容量许可。
schema 2根预算的每个stage只接受`solver`、五项正资源限额及`automatic_retry_count=0`；未知字段在唯一预算入口拒绝，
不再允许项目级“某一限额才告警”或未消费的采样间隔配置。告警与终止语义仍由公共执行标准唯一规定。
公开边界回归覆盖成功、前端／下游失败、母群冲突、wall-clock 告警、旧预算缺阶段及缺冻结GEM，最后一项证明尚未进入前端native或资源准入。最终聚焦回归与PS解析通过；
测试供应商边界为明确inert替身，不构成真实求场证据。
双域场阶段的17项回归已通过（41.761 s）：父命中／细未命中只构建细场，guard变化不改变两域求场key，
细域中途失败按正常事务重入，已有私有父PA沿公共身份入口重新准入，fresh路径不新增全文hash。
cache容量仅扣exact key发布前后的元数据字节正差，已存在generation再次返回complete不重复扣；
该差额不承担任意并发writer的归属证明，继续受公共owner／锁和供应商串行约束。
14项资源／下游回归及公开入口两个新场景通过，核验全run阵列预留、六场Fly预算拒绝、同网格双域的
完整母群收集与默认回放接线；它们没有实际执行商业求解器。
下游计划另在创建staging前检查提供者网格、容量上限及必要几何关系；检测器网格舍入已收回提供者唯一派生，
与原生Lua一致，不在集成层用第二份公式补偿。18项相关纯回归覆盖半cell网格、精确／不足容量及非法输入，
baseline完整resolved字节保持；尚无新真实下游PA或Fly证据。
准备阶段冻结独立consumer代码闭包，
只从快照执行Python。它按[作者schema](../../workflows/single_reflection_flight/schema.json)消费最终resolved提供者、配方、
已记录出生母群或公共release spec及canonical clock／epoch，原字节冻结所有外部输入，按唯一pose完整投影一次。
后续消费者使用返回的冻结输入路径；改变外部作者文件不改变准备结果，重复准备与终态run拒绝覆盖。
当前作者schema 7显式引用完整父`composition_plan`，执行时从其冻结recipe及components派生实际范围，
不重读父plan记录的活动来源。`providers.instances`恰好绑定所选实例，设计冻结于
`inputs/components/<instance_id>/resolved_design.json`，小文件身份以`instance_design__<instance_id>`登记；
没有固定multipole／oatof路径别名或schema 5 fallback。侧口尺寸与中心只读取父OA端口，
实例仅声明电极映射与OA渲染变体。当前执行能力仍限单个三区oaTOF或多极杆＋三区oaTOF；其他选中器件明确拒绝。
作者schema 7与场设计schema 3将数值项统一归入`numerics.frontend_domains`：必需parent、可选
entrance_refinement各自声明网格、范围和实际工作场的Refine收敛值，细域另声明guard_cells。
局部范围包含多极杆时仍须RF；仅oaTOF时不加载未选中设计。该迁移的联合回归正在进行，尚无新版原生资格。
`20261024_141512__test__python__schema6-field-source-preparation`的纯准备对照已确认原始源
13612 B、投影源16051 B及两个GEM分别7378／7381 B与094111及131700逐字节相同，
两数值域的场科学输入也逐值相同；未读PA／MPH或运行求解器。该run因一次性owner误用轻证据
容量收尾而保持failed，不能写成整包成功；其科学对照报告保留，不为取得绿色终态重复生成相同输入。
完整前端使用三个工作场；无杆的局部OA只用OFF及脉冲差分两场，不声明RF参考幅值
或RF步数。共享电压表及OA全零OFF策略只保留一份，不兼容旧native schema。
同一body只按parent cells渲染一次，parent／fine GEM只改变数值包装；父GEM与投影源字节保持。
细域目前必须完整包含上游机械包络及OA全X，Y覆盖OA轴与实际接合区，不支持任意CSG裁剪。
该范围保留环和未开孔正X墙的代表截面，OA金属样点从真实Z交集重选，不能过滤域外代表点或把有交集却
未被网格表示的金属静默丢弃。
37项几何／准备／场设计回归通过（7.614 s）；74项Program／workbench与原hooks回归通过（12.077 s），
包含普通Lua五槽保存重开、细域有效范围回退、检测器优先、同ID／单时钟／RF及不叠加父场的行为。
同网格普通Lua与inert PA证明接线，真实parent→fine场连续性和完整母群精度仍待原生验收。
双域接线的联合L1已完成：直属集成327项通过（647.976 s），原集成族932项通过、3项跳过
（220.547 s），Ruff及公开冻结入口同时通过。这是源码与无商业求解器验证，不扩大真实场或飞行资格。
新整机已在同一入口消费从同一父配方派生的下游oaTOF局部范围：
内联`local_scope`选择配方中该实例的实际ID并声明研究范围与边界假设，
保留父提供者和唯一位姿，仅移除未选多极杆实体／驱动，使用实际OA电极及OFF／脉冲差分两场，不发布零RF场。
当前只接受默认完整范围或这个局部集合；局部源必须绑定该选中实例，数值域只允许parent。实际OA电极保留11–35号；
原生电压参数前10个零槽只是索引填充，不生成杆金属。场身份省略RF字段，沿用同一公共缓存事务。
实例绑定现由配方的唯一连接贯穿几何、源、场采样和Program，不限定`multipole`／`oatof`字面名称，
也不依赖实例数组顺序；提供者角色键及物理端口名称保持原义。完整范围仍严格覆盖本次配方全部实例，
不支持的额外实例明确拒绝；这不是任意多器件物理求解能力。`recorded_birth`必须绑定实际多极杆上游，
`release_spec`可绑定选中的任一实例及其提供者局部frame。局部范围不得移动或重新采样同一OA源。
裸导引、冷却前端及单反射前端共用公共父plan范围解析；各执行器只校验自己支持的连接，不维护第二份器件表。
本轮几何／场／准备／Program／runtime五完整模块79项、裸导引／冷却两完整模块41项通过；
覆盖改名及倒序后的GEM、源、时钟和场定义不变，以及真实冻结后脱仓准备，未执行商业求解。
公开执行入口、依赖冻结及既有共享前端／Program五完整模块另138项通过（412.196 s，0跳过），
覆盖改名倒序后的full／local discover、同OA源CSV／clock／epoch字节相同、默认回放、失败收尾及脱仓依赖。
供应商边界为明确inert替身，不构成真实求场或飞行证据；Ruff、生成绑定新鲜度通过，公共GATE正常释放。
该早期切口相对其上一轮CLOC报告生产代码净增3行、测试净增219行，当时迁移总量仍净增；
这是历史阶段数值，不能替代上文最新同基线累计快照。
42项几何／准备／场设计回归通过，完整前端GEM、源及field design与修改前逐字节一致；94项新旧Program／
runtime及提供者普通Lua验证通过。公开入口局部完整母群／默认回放接线通过（17.451 s，inert vendor），
23项资源与完整母群收集回归通过（7.584 s）。这不是局部真实场、IOB或飞行验收。
扩展联合L1发现公共资源测试提取新入口收尾调用时，夹具缺少`$OutputDirectory`；440项中439项通过，
该项在真正调用helper前失败。现将夹具变量绑定同一临时run目录，原提取、实际helper及usage／limit断言不变；
先复现再单项重验通过（6.452 s）。生产收尾逻辑未修改，不将该单项复验表述为整轮L1已通过。
提供者发布ON电压，
不由源参数推算电压。场准备从同一几何为每个杆段、环、端点及接地件生成实际采样点；当前八极／20环工况为59点，
逐片验证物理组、一次位姿、数值节点和真实金属内部。零厚度面不在网格节点时在原生求场前拒绝，不能修改实体补偿。
raw PA#电极ID与普通工作场的metal标志及实际电压分开核验，不猜测unity归一幅值；完整采样声明替代旧8杆硬编码。
几何只保存于`frontend_geometry.json`，field design不再重复内嵌；共享场规划从PS抽出，4份重复工具复制已删除。
三工作场准备的14项聚焦回归通过，GEM、几何JSON、投影母群及原始源CSV四份文件与修改前逐字节一致。
新整机已移除PA+产物、354条展开响应采样及重复模式模型；真正的公开冻结／脱仓准备、预算和失败释放继续由联合回归验收。
这不是真实Refine或完整整机飞行验收，原生数值域和预算仍待明确验证。
现有整机Program生成器已消费该field design及独立几何输入，支持四个物理角色及可选第五入口细域，
不再在此新路径猜测套筒／入口板或覆盖提供者反射器、检测器位姿；位置不符直接拒绝。
52项新旧Python回归和提供者原有普通Lua回归通过，覆盖非零反射器轴、检测器位置、动态场叠加及原ID／非零出生时钟。
此处只是生成器与回调验证；新公开入口尚未完成下游场构建、四／五槽IOB、完整Fly和默认回放的真实验收。
下游提供者命令计划与发布器已复用原flight-tube、reflectron和detector构建器／GEM；飞行管和检测器保留
fractional原生family及其surface伴随文件，反射器导出实际工作点ordinary PA，不以省略surface简化场。
发布要求逐步原生退出、独立日志／资源证据和网格／电势审计，5项纯回归通过；夹具字节不是科学场。
workbench准备器按实际数值域选择公共四／五槽seed，消费当前场发布receipt schema 2及唯一field bank，
保持投影源不再变换、不再复制粒子CSV；
19项相关回归及7项修订后回归通过，仍显式标记非Fly-ready，原生重开／优先级及完整飞行验收未闭合。
该consumer按统一依赖库存冻结实际源码与资源；脱仓回归完成下游命令规划，删除冻结GEM后明确拒绝，
不回退活动仓库，也没有执行商业求解器。
源以`recorded_birth`或`release_spec`明确区分真实输入语义：前者保留原始multipole出生母群及提供者metadata身份，
后者可绑定实际multipole或oatof实例，frame只取spec，使用公共采样器物化一次并由消费者解析一次。
frame、clock、实例及几何纯检查先于物化；不支持的源形状、母N不符或伪handoff／restart明确拒绝。
15项准备／场／公开入口聚焦回归及补充缺实例反例通过，实际210633原始CSV／clock保持，
切换源时几何及场定义保持不变。局部执行仅支持前述下游oaTOF切片，其他局部集合尚未接线，不能宣称任意局部均可Fly。
早期20项几何／准备回归包含真实210633源及完整编译的合成300 mm夹具，不能将夹具当作历史批准候选。
真实候选`B25EEF7E…BC7B77F`及当前kinematic-envelope profile已另核对身份并通过提供者完整编译，尚未求场。
旧`ideal_acceptance_300mm_continuous_frontend_n1.json`声明102.4 mm连接间隙、1×1 mm侧口和旧母群选出的N=1，
不能作为当前贯通出口零间隙N=100装配的等价作者输入。新物理配置仍须明确配方、实际侧口和源，不能由测试夹具补缺。
源回归中原N=100身份、出生时间、源SHA和clock字节保持，未写PA或启动粒子。实际新公开入口的受管run创建→公共冻结→
脱仓准备→run_config输入登记回归已通过，删除快照中真实提供者模块后明确失败，无活动仓库回退；终态run拒绝覆盖。
输出仍为`geometry_preparation_only`，不包含新场、脉冲选择、飞行或资格。

工作台准备API消费冻结request中的单一`flight`输入：`pulse`、`maximum_flight_us`、
`maximum_step_us`和`trajectory_quality`；只有实际含RF的范围要求`rf_steps_per_period`。
`pulse`支持显式timed、held_off或discover；held_off不允许时间或宽度字段，discover先生成实际OFF发现阶段，
再由其全部原生批次的状态生成唯一脉冲决策并接续timed阶段。
新native不保留原标量脉冲格式的兼容分支。脉冲时刻使用canonical绝对时间，
最大飞行时长使用各粒子的实际年龄，不因出生或实例切换重置。绝对时刻可为负，时长／步长须正。
实际phase的flight从冻结request和适用的脉冲决策派生，直接记录于工作台receipt；不再逐批物化同义`flight.json`或重复哈希它。
收集时核对所有case声明一致并重新对照冻结权威；缺项或非法值仍在生成产物前拒绝。
新Program不再用0／1微秒脉冲与TQual 8占位，也不另接一份RF步数权威。四槽均消费最大步长和年龄；
原生碰撞及完整末步观察优先，无终态的粒子才按年龄超时。旧90微秒观察窗在此路径显式关闭，无补偿上界
或另一套检测器命中逻辑，仍由原生marker及提供者`terminate`判定检测。
84项新旧Program／runtime及实际local／cooled消费者回归、provider与hooks普通Lua回归通过；
覆盖非零／负出生与脉冲时刻、脉冲边缘、四槽切换、年龄截止同一步发生原生检测器碰撞及重复终态处理。
这些是无商业求解器行为证据；`fly_ready=False`，没有新IOB重开或Fly的真实验收资格。
真正held-OFF复用同一pulse kernel，不生成虚构脉冲时刻、边缘、ON事件或脉冲相对日志；RF和完整出生钟仍生效。
提供者仅在观察窗显式关闭时接受无脉冲相对时间。87项Program／runtime及既有消费者回归、普通Lua提供者与hooks
通过；这仍不是实际OFF到达发现。前端场缓存的科学身份已收窄到真实GEM、域、样点和场条件，不绑定无关下游
位置元数据；writer与消费端复用同一投影。仅移动检测器或反射器时，前端输入不变便不重复求场；下游资产仍独立核验。
该复用限当前独立Neumann前端模型，未来若下游实际进入其耦合边界，须将相应物理输入纳入场身份。

新公开入口的`-Fly`默认保持所选完整装配，按原冻结源行复用公共资源调度进行独立粒子分批；
每批保存IOB并独立重开核验，再以其默认值在新进程回放。不存在额外完整母群串行Fly；后继110745已完成实际N100分批及默认回放，保持零检测命中的负结果。
同一冻结预算预先要求field、workbench、flight及default replay各阶段；discover另要求发现阶段预算。
飞行预算预检消费实际所有域的三／六场RAM下限，明确不含下游阵列和进程开销，不能把能构建场当作能加载全部场。
保存IOB／Program／FLY2在每次Fly前后核验，flight声明对照冻结request及脉冲决策；准备成功而飞行失败时分别记录阶段，不将已完成的IOB准备改写为失败。
调用者继续拥有run终态，任一Fly、收集或回放比较失败都不能发布完整成功；PA保护及容量／host许可沿同一finally释放。

收集边界直接消费直属 `single_reflection_flight/census.py` 的唯一原生事件解析与终态 census，旧整机统计分析也复用此实现；
不执行峰形、bootstrap或旧owner发布CLI，不再导入旧family分析器。先核验真实出生记录，
禁止从初始表补造出生满足完整性。保留每ID实际raw6D终态及原生步内插值checkpoint，将其与提供者检测面投影区分。
源、出生钟、完整母群终态和逐ID规范事件均参加默认回放比较；32ULP只沿用既有binary64表示误差许可。
回放消费baseline阶段实际返回的`collection.json`发布记录，核验该小文件后直接比较；不重新解析或哈希baseline原始日志，
不随当前控件重新构造基线，也不新增中间文件。原始日志继续保留并由首次collection记录其身份。
held-OFF没有脉冲捕获资格；timed在全损失、无pre-pulse样本时仍可收集真实完整census，不靠假样本绕过。

新native已移除旧环境变量对源行偏移、PA路径及外部trace／load report的覆盖，完整母群只读冻结源表。
复用实际外壁handoff，新增侧壁内面和OA中心的X正向跨面观察；位置直接取实际几何，保留前后原生步时间与X括号，
对完整状态作括号内插估计。出生在下游、反向或重复跨越不补造首次到达，且不改变RF、步长、源或场。
这些观察不是精确落面或已通过孔传输的证明。58项Program／普通Lua回归已通过；新的实际OFF到达、完整Fly、
母群收集与新进程回放仍须在真实工况验收，不能把纯测试的合成日志或inert PA当作物理证据。
分析／既有局部消费者联合93项回归通过；最终收集器8项与公开Fly的11个场景共9项测试通过（125.908 s），
覆盖两种pulse输入、缺预算、三场RAM下限、原生失败及同时控制漂移、缺哨兵和逐粒子回放差异。
独立复核进一步复现终态接受步的日志精度缺陷：`42.48966792789`被12位打印舍入到稍晚时间，
会被既有32ULP生命周期检查拒绝。新native检查点、脉冲和终态分类现统一17位打印，未放宽容差；
旧消费者保持原表示。数量派生与该精度修复的96项联合回归通过（26.005 s），包含普通Lua真实生成Program
在四个Z平面终态同一步的held-OFF及timed反例；八极Program仅因日志精度改变，其几何、场设计及源字节保持。
此前公开准备／Fly的28场景功能回归通过，但普通权限下host收尾无法核验在途进程，未把该包装器报为成功；
沿公共调度入口以正常进程权限复核后仅保留真实SIMION预约，最终聚焦门禁正常释放，没有清除在途保护。

同一公开入口的`WorkbenchOnly`已接入冻结request中的可选inline `flight`，在首个原生调用前要求该输入及
`instrument_field_design`、`instrument_workbench_preparation`两段预算；预算只冻结一次，从同一文档选择阶段。
它顺序消费已发布场、调用实际runtime、保护返回的只读PA、构建IOB，并由新进程重开核对四槽实际路径、网格、
提供者位姿、声明优先级顺序及Program／FLY2身份。验证实际绝对路径使用官方`pa.path`，不将只返回basename的
`pa.filename`与完整路径相比较，也不增加猜测fallback。同一工作台收据记录执行／验证终态和执行证据；
失败保留日志并释放PA保护、host及capacity，run终态仍归调用者发布。
四个直接模块共23项测试通过（138.628 s），含真实公共冻结后的脱仓runtime、两次明确inert供应商边界、
缺flight／预算、build／重开失败及输入／控制漂移；未启动商业软件。此处核对顺序不等于实际重叠区场选择验证，
`fly_ready=False`且实际重叠及完整母群飞行仍待验收。
上述held-OFF与前端身份修正整合后，准备／公开执行／工作台runtime／场阶段四模块共32项回归通过
（172.243 s），覆盖新held-OFF公开冻结与脱仓准备；仍使用明确inert原生边界，不授予真实IOB或Fly资格。

真实300 mm候选、活动kinematic profile及210633 through-exit的完整包络已重新核算；原6201层未覆盖
多极杆外壳最低面，不应作为该完整工况的规划域。直接铺满`.25/.25/.05 mm`单域，哪怕不加数值留白，
仍需`932×593×6351`节点；按SIMION官方8 B/点磁盘、约10 B/点RAM估算，单PA约26.15 GiB，
三工作场构建的双数组RAM下限约65.38 GiB，三运行场约98.07 GiB RAM。这是几何下界估算，不是实测峰值或获批执行预算；
完整构建还需中间载荷、工作点及隔离副本。依据为[官方内存说明](https://simion.com/info/ram_and_memory.html)，
2026-10-23核对其8.1／64位适用说明，不把后续版本能力用于SIMION 2020。
完整物理装配因此不冻结为四槽或单一细PA架构；实现已接同一实体派生的显式父／入口细域，真实数值资格仍待验收。
新整机已将准备、场阶段及Program消费切到OFF、RF参考幅值与ON−OFF三个工作场，
复用现有普通工作点发布与公共缓存事务，替代该消费者的六响应求解、归一化及再次组成；
其他真实消费者仍使用的六基底机制保持。这不解决上述均匀域的单阵列及运行内存规模，不能代替分域与精度设计。
只读规划另评估`.25/1/.05 mm`各向异性父域：原Y phase虽覆盖包络，却把真实外壳中点采到外表面，
实际physical-sample校验明确拒绝。从真实壳中点派生Y phase、向外覆盖至−74.5～74.5 mm后，
`932×150×6351`节点及59个实际金属采样通过；单PA／双数组构建RAM／三运行场RAM下限分别约
6.62／16.54／24.81 GiB。这里仅移动数值网格，不改变机械位姿、实体或母群；它仍是未授予精度的数值候选，
不能由采样通过推定原生开孔、间隙、拓扑或边界场已验证，也不能替代细域与母群对照。
直接场阶段执行36项测试，2项真实SIMION检查明确跳过、其余通过；覆盖缓存命中零原生调用、
导出半文件只留scratch、正常事务重入及prepared发布后的容量扣减。公共缓存及实际消费者104项回归通过，
既有基底key保持；Program／runtime及原消费者79项回归通过，验证RF只按显式参考幅值缩放一次、
OFF工作场不再被FastAdjust清零，脉冲差场不缩放。公开执行及冻结依赖8项回归通过。
这些检查使用明确的inert供应商边界或普通Lua PA替身，不是原生求场、数值收敛或完整母群飞行证据。
资源规划进一步收敛到同一实体的一个完整父域与一个入口耦合细域：父域`.5/1/.05 mm`、
`467×150×6351`节点，细域`.25/.25/.05 mm`、`933×173×841`节点。细域覆盖整个上游机械包络及
实际OA入口耦合区，不按源或轨迹裁剪；完整OA及后续环仍由父域保留。父域59项金属采样通过；
细域不能简单删除域外代表点，须从同一实体与数值域的交集生成实际金属采样。
六个运行工作PA的前端RAM下限约16.22 GiB，父／细构建下限约8.29／5.41 GiB；冷构建缓存与
私有副本新增磁盘下限约25.96 GiB。以上不含下游、进程及Refine额外开销，不是执行预算或精度保证。
该具体数值配置仍为未验收候选，机械输入采用下述既有案例侧孔；必须完成原生同网格实例选择对照、交界场及细化验收，
不能凭内存估算宣称完整链路已通过。
当前新版API已对该真实候选作只读重编：两域物理body完全相同，完整上游body逐字匹配，fine网格改变不影响parent GEM。
parent为59个金属样点、fine为38点；细域保留32杆片、两个原生接地件、OA repeller／grid1／第一环及正X墙，
各节点通过原金属与孔的逆投影检查。四个真实端点在parent Z节点350／490／1612／6350，intermediate2未省略。
此次未填写RF参考幅值或Refine收敛值，未发布design3、author或run，也未生成PA；不把纯编译当作原生几何或场资格。
本机官方`simion.chm::neumann_boundary_conditions.html`及`accuracy.html`（2026-10-23核对）说明：
原PA#求解的非金属外边界使用零Neumann，PA#的Refine停止objective按10000 V归一尺度理解；
普通PA停止值是实际电压量。不得照搬冷却工作点的零Dirichlet边界，或对±1 V单位场沿用同一停止数值。
实际实现须冻结数值参考幅值、各工作场收敛设置与原生边界，Program显式按参考幅值缩放真实RF系数；
停止objective不构成场误差上界，仍需同网格场对照及完整母群数值验收。
局部patch才消费同kind父场在裁面上的Dirichlet值，并检查非物理裁面不会变成粒子碰撞金属。
本机SIMION 2020官方`docs/simion.chm::multiple_pas.html`与`lua_simion.wb.html`、
`examples/field_emission/refinelib.lua::copy_boundary`已于同日只读核查：重叠场按最高优先级选择，不自动叠加。
旧coarse前端省略真实intermediate2面，旧正间隙分域依赖长接地套管；均不能直接作为当前零间隙完整链路的
父场或资格。域网格、真实薄面表示、边界场差、碰撞面覆盖及完整母群配对仍须显式设计和验证，
不恢复已退为诊断的轨迹core、不按源裁域、不静默降低精度或删去组件。

真实完整链路的作者来源已核到`B25EEF7E…BC7B77F`候选及活动
`three_zone_ideal_acceptance_300mm_square_kinematic_envelope_v1`，上游采用成功
`20261022_210633__sim__simion__octupole-through-exit-n100`的resolved、100 Da／+1／2 eV原始N=100出生表、
metadata及canonical clock；不使用其出口表或旧N=1选后母群。内存编译证实四个真实薄面间距为
7／56.1／236.9 mm，可用同一0.05 mm Z网格及一个phase表示，未调整机械面来迁就网格。
先前按半径3.6 mm圆出口提出的7.2×7.2 mm方侧孔不作为采用输入。用户2026-10-23要求优先沿用已有案例，
并允许比较二区尺寸；现二区`two_zone_field_seed`的实际侧孔半宽／半高为1.5／1.4 mm，与已成功三区
`20261022_165815`及`20261023_002647`冻结请求的3.0×2.8 mm矩形侧孔一致。因此新候选沿用3.0×2.8 mm，
当前负X壁宽沿Y、高沿Z；孔中心由本次提供者外壁与第一间隙派生，不能照搬旧三区frame中的[-17,0,2]。
侧孔只切接地壳，板和理想grid完整保留；圆出口到较小矩形孔的真实遮挡和损失必须保留，不能假设无损。
该尺寸来自已有模拟机械输入，尚非实物测量或新完整链路的原生验收。脉冲必须在同源、同场及同RF条件下通过
真实held-OFF到达观测确定，不能沿用旧正间隙脉冲或把ON时刻推到观察窗外冒充held-OFF。
真实候选采用3.0×2.8 mm后已只读重编，零间隙端面中心为
`[-88.01362184380704,0,-18.429186803411028]`（oatof_global），实际壁厚4 mm；7 mm首区内孔上下各余2.1 mm。
父／细网格和59／38个金属样点保持，两域仍共用完整实体body。
真实作者准备`20261023_090229__build__python__single-reflection-author`已封存并通过完整manifest核验：
原100 Da／+1／2 eV母群及出生钟保持；冻结编译器在脱离活动仓库的进程中逐值重现provider、端口与布局。
父／细域分别为444,887,550／135,744,969节点，已登记625个OFF候选及8个RF周期的探索脉宽。
五阶段工程预算预检通过，但没有PA、IOB或原生飞行结果。IOB模板保留缺陷已从该真实封存中定位并修复：
规则原先只保护第01槽，现保护冻结公共模板目录中全部已引用槽；25项保留回归通过。
误删的02–05模板已从原仓库来源恢复，原删除及恢复证据均保留。准备包85,083,451 B按公共owner路线
封存为受保护可重建载荷，不提高轻量证据上限；后续原生执行必须新建run。
新入口已接入同母群的实际占据发现阶段：作者`flight.pulse.mode=discover`显式提供
`candidate_times_us`和`width_us`，派生held-OFF工作台只记录这些绝对时刻的原生状态；
候选排序只消费实际出生、寿命、同步状态及本次OA首间隙，不读取后续检测器命中或终止原因。
实际状态保留自己的时间，不插值；仍存活而缺测的粒子计为`numerical_unsupported`，该候选不得参与排序。
没有可支持候选时先保存负`pulse_decision.json`再失败，不生成timed后继。
成功时接续一次timed完整母群Fly及一次保存IOB默认回放；OFF发现不另做默认回放。
各阶段共用已发布的场、原始源及仪器时钟，不复制PA或重采样母群；发现阶段单独要求
`instrument_pulse_discovery`预算，原生飞行、采集和评分累计使用同一壁钟。
两次工作台准备共用`instrument_workbench_preparation`总预算。采集13项、运行器及Program生成28项
聚焦回归通过；这些合成原生日志和普通Lua检查不构成新full真实Refine、原生几何审计或精度证据。
本轮联合L1通过直属集成361项、多极杆公共440项及旧整机集成932项（3项跳过），
覆盖新发现阶段、冻结依赖及先前资源预算夹具修复；它仍是不启动商业软件的改动范围门禁。

共享前端缓存已切换当前schema 2 response receipt／recipe，5／6模新代际仅保留ordinary响应、归一化与小收据。
原生PA#／PA0／PA模式成员只用于该事务构建；owner先保存实际来源身份与保留库存，再清理自己的scratch，
中断沿同一事务重入，不另设恢复入口。新活动入口不接受旧格式fallback，既有generation不原地改写。
OA／MR实际使用的raw载荷继续保留；这些生产者及旧family同步绑定当前公共收据合同身份，避免误命中旧key。
完整受影响162项纯回归通过，末次补充的15项response-set回归通过，包括未保留source、已保留source三元身份冲突
以及中断后清理／发布。此处减少长期载荷与消费时无用的源PA读取，不代表前述大均匀域的首次构建峰值已可接受。

局部前端从显式IP producer manifest中唯一选择其声明的`inputs/clock_authority.json`和
`inputs/instrument_epoch.json`，使用公共canonical clock校验器核对authority与epoch内容身份，
再原字节冻结两份输入并继承`clock_epoch_id`。不增作者时间字段；缺少声明、来源漂移、epoch与
resolved guide冲突均在写入前拒绝。当前科学边界仍只支持零epoch；完整母群的`birth_time_s`
仅按原有规则换算一次为`instrument_time_us`，空间位姿不改变出生时间。
原生零TOB及Program恢复出生时间的序列化规则只保存在`source_identity.native_clock_projection`，
不再另写`source_clock.json`。这些输入绑定不改变`layout_only`计划的职责，也不授予新的物理资格；
既有run保持只读，缺少canonical声明的旧生产者不得作为新运行的fallback。

## 依赖冻结与门禁

OA→MR不再冻结仓库priority模板：native把已冻结的`native_corridor_bank_cache_manifest.json`交给现有materialize，
由真实场通道身份生成本run侧车；static不传bank且不虚构通道组。构建、留存及续接继续绑定同一侧车路径。
旧模板及其依赖／路由记录已删除；提供者接口与数值边界见[MR当前状态](../../../projects/parallel_mirror_dual_stripe_mr_tof/docs/PROJECT.md#当前决策与完成边界)。

此前直属静态门禁272项通过。旧family全量复验发现并修正两处迁移回归：正gap测试不再引用已退役的小间隙
预设，保留有真实作者的51.2 mm几何／冻结绑定验证；绑定刷新器退出误加的历史theory-order campaign登记，
恢复其原始字节及输入身份，活动successor仍正常刷新。新增回归验证历史文件不进入刷新目标且writer不修改其字节，
不通过更新固定SHA掩盖历史漂移。修复后旧family全量931项通过、3项明确skip，host许可正常释放；
直属272项和共享缓存／实际消费者162项回归亦已通过，覆盖范围不相加。上述均为无商业求解器门禁，
不授予新场、完整Fly或GUI资格。

显式脉冲、完整母群Fly／默认回放收集和新native环境隔离整合后的联合L1已通过：直属303项
（556.539 s），旧family932项（214.704 s，3项明确跳过），Ruff及冻结依赖门禁通过，host许可正常释放。
这覆盖前端准备、场阶段、公开冻结执行、收集与原消费者回归；原生调用使用明确inert边界，
不授予真实新场、IOB重开或完整Fly资格。后续提供者数量派生和数值分域修改须重新验收受影响边界。
公共ordinary patch构建器已修复父场Dirichlet路径遗留的非物理六面碰撞标志：沿原raw六面恢复真金属，
保持求得电势；zero-Dirichlet原行为不变，zero-Neumann不进入恢复分支。公共工具、冷却mesh-check及
执行入口共23项测试中21项通过、2项商业检查明确跳过，含父场坐标采样、一次Refine及电势／金属不变的
普通Lua行为回归。未改写既有PA或在途快照；新路径的原生patch求场及飞行审计仍待完成。

冷却前端主体与测试已迁至`integrations/workflows/cooled_frontend/`及直属测试目录，旧family入口的冷却
参数与转发已删除。新作者输入只声明cooler与accelerator的直接位姿，真实出口栅与OA侧口由公共配方
检查；无伪空隙装配或补偿偏移。共享前端仅提取原有几何编译职责，冷却物理仍归IP提供者。
当前作者schema 3引用完整父plan，默认执行该plan全范围，局部范围显式派生；先复制、核验并读取
冻结父plan，再核对实际提供者接口。三区场种子与参考实验共用同一`cooled_oa_three_zone_plan.json`，
二区使用独立`cooled_oa_two_zone_plan.json`，均放在`config/recipes/`；已删除仅名称不同的重复三区plan。
改变释放工况不再复制装配。三份真实作者ValidateOnly及核心16项回归通过；不据此改写旧原生资格。
真实N=100作者ValidateOnly以及新mesh校验已通过：新GEM、七端点field plan与旧封存场源逐字节相同，
出口栅`[0,33.5,32]`到OA外壁`[0,34.5,32] mm`，正向间隙1 mm。
新owner首次参考运行`20261022_232029__sim__simion__cooled-frontend-reference`在Fly前发现冻结闭包遗漏，
未启动粒子飞行；failed完整manifest核验通过，19,825,447 B／159文件沿公共owner流程封存ready。
遗漏的现有reference_support、reference及mesh_check模块已补齐，真实冻结后的加载与禁止仓库回退测试通过。
随后`20261022_232734…`在Fly前暴露junction别名与真实路径混用；现只对同一个module路径resolve一次，
真实Windows junction调度准备及16项纯回归通过，原失败包保持只读。

`20261022_233346__sim__simion__cooled-frontend-reference`已完成两次单粒子原生参考飞行，worker均自然exit 0，
两次均无唯一OA出口，未产生公共脉冲decision，也未启动N=100母群或压力对照。完整manifest的81项输出通过，
102,586,740 B／289文件按failed封存ready。静态估计给出1551.846035／1563.464752 µs，
实际pulse位置分别为y=29.328243／37.125689 mm，目标为51.5 mm；第二次真实入腔后孔面通过时刻为1562.276208 µs。
独立复核未发现源、field receipt、clock或drive绑定错配；静态轴线积分排除了真实RF演化，不能当作已观测的native bracket。
当前先明确held-OFF参考发现的实际窗口，再在有限次数内验证，不外推或扫描，不改变物理电压／源。
负结果已改为带真实phase/pulse及终态证据明确停止，不再KeyError或继续下一试验；
参考receipt中无人消费的完整事件list重复JSON已删除，原始日志、小型终态和出口证据保留，14项相关纯回归通过。
held-OFF发现现已替换静态初始窗口：显式关闭OA，核对实际pre/post入孔及同一正向中心穿越，
用原生中心时刻与提供者理想引出时长派生两个候选，再以出口残差验证，至多一次secant原生复验。
全过程最多4次单参考飞行；无支撑或无有效出口bracket时保留负结果并停止，不伪造生产decision。
104项相关纯回归通过，冷却runtime另删3份重复源码物化。首次重试曾被容量startup无条件全局阻断；
公共入口现按既有规范只阻断涉及当前输入的逾期writing，无关对象保留原状态、字节与告警，
195项容量／生命周期回归通过、1项既有跳过，未修改历史对象、复核日期或容量阈值。

新运行`20261023_002647__sim__simion__cooled-frontend-reference`已成功完成4次原生单参考飞行：
OFF实际中心穿越1573.97382667974 µs，两个脉冲试验出口y为51.4963376393／53.1788662880 mm，
一次secant原生复验得到共同pulse=1572.7503928277122 µs，出口中心残差3.26772764e-5 mm。
154项输出完整manifest核验通过，success按公共owner流程封存ready，49,624,256 B／364文件。
该结果只证明参考标定；未授予N=100母群捕获、冷却、宽度、MR接受度或数值收敛资格。

原始母群真空运行`20261023_003153__sim__simion__cooled-frontend-population`在首批10粒子的第二ID启动时
触发`unfinished collision stream interleaved`，未完成N=100；43项输出核验通过，failed封存ready，
113,613,917 B／237文件。根因是碰撞流等待`terminate`才关闭，而[官方流程图](https://simion.com/info/_images/fig-prg-flow.pdf)
规定全部粒子结束后才逐粒子调用该回调。现以core或原生splat的明确终止信号关闭逐ID流，真实终态仍由原生
延迟`terminate`记录；保留未完成交错拒绝及原ID种子，32项相关纯回归和延迟回调Lua回归通过。
新运行`20261023_004408__sim__simion__cooled-frontend-population`使用该failed run的同一冻结request重跑，
14批100粒子全部自然exit 0，0失败批次，总批次耗时1189.9 s；随后完整母群分析在
`_validate_lifetimes`拒绝`native state follows terminal`。本次保持failed，227项输出完整manifest通过，
公共owner封存ready为6,962,496,946 B／422文件。尚未确定是回调状态还是分析合同问题，不丢弃异常记录；
默认重放及1 Pa臂均未启动，不能将原生批次完成当作本工作流成功。
14个超时粒子的最后共享样点在停止请求前发布，而原生终态回退到前一已接受状态；首个ID1为1700与
1699.9998918904264 µs。停止判断现已移到所有科学观察之前，保持阈值／步长和原生终态；
68项Program／分析回归及1项冷却RNG回归通过，历史冲突仍严格拒绝，错误补充ID及原文行号。
该修复尚待新真实运行复验。

本次14份批次`trj*.tmp`共6,900,300,000 B，已沿公共owner精确部分退役并通过receipt验证；
原failed状态／manifest不改，源、全部科学日志、共享PA与未飞行GUI包保留。公共容量重新封存为
62,760,443 B／409文件；显示缓存可由冻结GUI／源重新Fly生成，不能再用旧完整manifest作当前磁盘验证。
依据[官方计算时间说明](https://simion.com/info/calculation_time.html#trajectory-calculation-time)、
[官方8.1扩展](https://simion.com/info/workbench_program_extensions.html)及本机SIMION 2020
`examples/tune/tune.lua:38,86`／`examples/multiprocess_zmq/tune_series.lua:79`（2026-10-23核对），
`sim_trajectory_image_control=0`会强制显示并保留磁盘轨迹，覆盖现有批次`--retain-trajectories 0`。
现删除两处强制覆盖，显示保留只由原生CLI／IOB决定，启动日志记录实际control值；未增加环境开关或第二份Program。
默认GUI／默认重放仍按其原生设置，不能把批次不保留缓存当作GUI已验证。

先前3.5 GB承诺低于实测单份完整显示缓存。真空组运行时的显式作者预算为7.1 GB，依据已测6.9003 GB
完整母群缓存另留0.1997 GB用于现有科学日志、源、分析及重放日志；这是下一次容量承诺估计，
不是实际占用上界或数值资格，也不改科学输入、时间步、场或自动重试。后续真实GUI缓存与目录占用仍需核验。
旧`003153`失败运行的单份75,240,000 B批次显示缓存也已通过同一公共部分退役、验证及容量收尾，
两次合计释放6,975,540,000 B，不影响它仍可读取的冻结request／源及失败日志。
新运行`20261023_014142__sim__simion__cooled-frontend-population`已用同一冻结request及新显式预算启动，
pressure_scale仍为0，复用原只读场；首批原生日志实际control为1且未生成`trj*.tmp`。
首批10粒子自然exit 0（758.949 s）；14批100粒子现全部自然完成，0失败批次，后续wave耗时1163.716 s。
完整母群严格分析已越过原终态／采样错误：0个OA出口、14个timeout、86个native_stop_unresolved，
连接孔前后各5个同ID穿越，shared_unsupported_count为0。原生停止原因尚未确定，不能统称为碰撞或冷却成功。
同一保存工作台的全母群默认新进程回放已自然完成（100个终态，6333.77 s），
75,611条规范事件与调度运行逐值完全一致、0差异，IOB／Lua／FLY2控制文件身份保持。
该run已发布success终态manifest；这是保存默认设置的headless回放对等，未执行手工GUI或完整分析器飞行。
1 Pa对照`20261023_042013__sim__simion__cooled-frontend-population`的14批100粒子均自然exit 0，
首个10粒子批次1283.327 s，后续wave1874.677 s；完整分析得到31个OA出口、35个timeout及34个
native_stop_unresolved，孔前后各38个同ID穿越，shared_unsupported_count为0。原生未决停止仍不能归为碰撞。
总请求保持原N=100母群；冻结request与作者输入字节相同，复用同一七场及脉冲决定，不重新求场或重采样。
该历史运行把正式飞行分成14个调度批次，再用一个完整母群IOB在新进程回放；两臂执行分组不同。
其回放虽自然完成（100个原生终态，12720.80 s），逐值对照仍有192,779／192,954条规范事件、
31／34个OA出口和856,698个字段不一致。run已按failed发布267项输出并通过完整manifest核验；它是保留的历史负证据，
不构成新拓扑的物理验证，也不能把31个局部出口视为迁移通过。

受管纯分析`20261024_141151__analysis__python__cooled-n100-history-frozen`重新核验上述历史证据：
14批覆盖原ID 1–100，实际终态仍为31／35／34；34个未分类停止来自原生terminate时的真实六维TRACE，
不是最后采样点推算，也未推断其物理原因。保存controls检查只证明控制与来源完整，没有重新Fly或GUI重开。
21项冻结科学输入与101218对照：19项字节相同，另两项仅run路径不同。实际分析脚本与156项依赖均冻结，
从该run的runtime_snapshot执行，完整manifest核验通过；未读PA／MPH或启动求解器。
早先134530缺少分析编排脚本，140843依赖活动代码；两包保持原sealed状态，由141151取代当前分析依据。
此分析只映射历史1 Pa冷却前端→局部OA功能证据，不证明当前工作树已原生执行，也不授予MR或性能资格。

2026-10-24按仓库[独立粒子调度](../../../docs/DEVELOPMENT_STANDARDS.md#独立粒子与耦合求解的调度)和
[随机重复验收](../../../docs/VALIDATION_METHODS.md#随机碰撞与重复运行)收敛：当前模型只有给定背景气体的
HS1碰撞，没有粒子间耦合，新运行恢复公共资源调度器分批并发。随机碰撞轨迹差异是诊断结果，不能仅凭它
判为物理失败；历史failed身份及原始比较仍保留，不事后改写。冻结代码复核已确认历史1 Pa两臂同样使用逐原始ID
重置／播种，所以不能用seed相同要求不同分组逐轨迹重现。
有实际碰撞的工况默认只验证已保存完整母群IOB／Lua／FLY2及源身份，不再追加一次完整母群串行Fly；
receipt明确`scope=saved_controls_only`、`native_fly_performed=false`，不冒称GUI或原生重开通过。
无碰撞工况仍走确定性默认回放。两者复用同一公共实现；单完整母群专用物化／运行及重复回放函数已删除。
完整母群覆盖、原ID、时钟、实际状态／终态和损失分析继续执行，未降低数据完整性要求。

2026-10-24的直属静态门禁发现完整母群物化器遗漏导入冷却专用Program构建器，调用该路径会在启动原生求解前
发生`NameError`。现已在该唯一调用点直接导入构建器；新增回归确认完整GUI基线使用冷却场／碰撞Program，Ruff通过。
后续完整集成门禁已通过473项（931.028 s）；不把静态门禁表述为新的原生冷却飞行证据。

新运行`20261024_101218__sim__simion__cooled-frontend-population`已由同一公开入口启动，冻结
`042013/inputs/request.json`的N=100、pressure_scale=1物理输入及当前作者预算，复用封存场与共同脉冲决定。
此前ValidateOnly及公共预算解析通过；原生基线和独立进程默认回放均自然完成，分别100 splats、13520.96／14171.51 s。
该run冻结旧单路及随机轨迹逐值比较合同，最终因比较不同而failed；没有健康超时终止，也未重求场或重采样。
新分析`20261024_181303__analysis__python__cooled-n100-replay-evidence`使用完整原始日志，确认两次原ID 1–100出生／终态闭合，
23个共享时刻无缺失；出口21／30、timeout 46／40、未解析原生停止33／30。随机差异本身不构成功能失败，
但未解析停止仍须保留，不能据此宣称整体性能通过。保存控制复核为`saved_controls_only`，未追加Fly。
分析的两份科学报告已绑定manifest且检查通过；其owner因初始化summary检查错误而failed，不能冒称整个分析run成功。
旧运行例外在封存后结束，不作为当前并发入口的原生资格；不使用含已退役预算字段的历史预算直接执行。
真空工况仍为负引出结果；1 Pa局部出口不授予完整分析器、统计优化或Formal资格。
上述真空run已封存并核验，显示缓存`trj2dc9.tmp`经公共部分退役释放6,904,920,000 B，
科学日志、完整母群诊断、控制文件及来源保留；公共容量reseal核对剩余145,211,789 B，保持success与原pin。
中断准备`20261022_164740__sim__simion__local-bare-guide-oa`的三份私有PA也已由公共owner退役，
合计1,043,595,504 B；其既有manifest身份与后续成功`165815`三份PA完全相同，且没有待用消费者。
保留中断三件套、冻结输入和全部错误／组成日志，成功run及其GUI资产未改；不把中断准备称为场或粒子验证。
后续1 Pa不能直接沿用仅覆盖早停真空组的7.1 GB估计：该组实际终态时间总和88,680.85342155969 us，
按实测显示字节数线性外推至100×1700 us，约需13,236,638,516 B显示载荷。
当前作者预算明确改为16 GB，为该估计及现有日志留出余量；压力、母群、场、步长、脉冲和重试次数均不变。
这是规划估计，不是碰撞工况的显示步数或实测峰值保证；仍按原生进程预算监测，不因容量不足改变科学输入。
准入前还沿原owner公共收尾纠正了旧MR私有回放已退役范围的账面占用；当前库存及退役证明均完整核验，
没有新增删除IP／MR生产场或保留的B/C/D工作台包，具体资产边界见[MR当前状态](../../../projects/parallel_mirror_dual_stripe_mr_tof/docs/PROJECT.md)。

七场一次性迁移运行
[`20261024_214842__migration__simion__cooled-seven-field-cache`](../../../../artifacts/projects/instrument_assembly/runs/20261024_214842__migration__simion__cooled-seven-field-cache/summary.json)
已成功发布当前schema 2阶段收据及保留的校准脉冲决定。旧GEM逐字节相同、七工作点逐项相同，
保留真实旧builder身份；只迁移七份普通PA共1,568,749,168 B到公共generation，未Refine或Fly。
新审计器的网格、金属和电位检查通过；保存IOB后由独立原生进程从canonical generation路径重开七场通过。
原源100粒子保持，实际模拟数为0；这只证明七场迁移、原生载入与保留决定的绑定，不是新校准、冷却、并发或GUI资格。
公共owner已封存ready，运行证据38,517,420 B，场由公共缓存独立拥有。
三份活动作者配置已改绑该终态owner与generation，删除旧profile来源绑定；reference、mesh及gas预检、
实际runtime.context消费和两个完整模块34项回归通过（21.252 s），新gas准备的100粒子源与101218逐字节相同。
五个完整冷却模块68项回归及后续完整集成473项门禁通过；当前generation的N=100气体飞行随后由下述运行闭合；
小型载入验证本身不代替该原生执行，也不替代未完成的完整仪器链与GUI／CAD验收。
当前generation的
[`20261024_220720__sim__simion__cooled-frontend-population`](../../../../artifacts/projects/instrument_assembly/runs/20261024_220720__sim__simion__cooled-frontend-population/summary.json)
已由公开入口自然完成，owner exit 0、summary／manifest为success。保持原N=100、pressure_scale=1、源、
七场和共同脉冲决定，未Refine、未复制PA。首批45 s观测后继续原进程，公共调度器依据1.85 GiB单进程峰值
与当时空闲资源规划13批，实测峰值并发13；所有批次自然exit 0，无重启或终止。首批2295.190 s，
后续wave收据2228.5 s，两者起点不同，不相加或冒充相同计时范围。
原ID 1–100恰好覆盖一次，32个OA出口、36个timeout、32个native_stop_unresolved；孔前／后各39个同ID穿越，
出口32行与损失68行完整闭合。未解析停止仍不能归为碰撞或冷却成功，不授予捕获性能、MR接受或分辨率资格。
`saved_controls_only`检查通过且`native_fly_performed=false`，未追加第二份完整母群Fly；GUI未执行。
聚合工作集峰值21,488,877,568 B、managed峰值25,879,556,096 B，最低系统可用5,505,404,928 B；
作者8 GiB阈值不是整次并发总内存硬封顶，不把健康完成描述为没有预算告警。
owner封存ready+pin，保留264,748,242 B／459文件，执行与容量租约释放。七场仍由公共owner独立持有，
该精确generation随后沿公共补pin动作建立长期工作台保留保护，未改变两个run的科学manifest或场内容。
该运行闭合当前公共七场的局部完整母群并发执行验收；GUI／CAD及完整分析器资格仍按各自边界验收。

[依赖清单](../../config/runtime_dependencies.json)声明直属工作流的实际源码与资源；
[共享冻结器](../../runtime/dependencies.ps1)统一按显式owner与consumer选择、展开并冻结依赖一次。
schema 2作者清单按provider分组，每文件只声明稳定id、来源路径与consumers；run input名称和快照目标路径固定派生，
七个工作流不再各自加载／筛选同一库存。切换前后七个consumer实际冻结记录逐字段一致，38项相关回归通过。
新增整机准备使用同一冻结器登记第八个consumer，只冻结其实际最终resolved准备所需49项代码／资源；
不把提供者尚未调用的候选编译配置加入该闭包。
局部前端runtime已删除5份`local_program_sources`重复源码副本，直接消费实际执行模块所在源码根；
正式入口仍从冻结snapshot执行。14项相关测试通过，含脱仓快照；状态字节不变，Program／FLY2仅临时路径归一化后一致。
旧整机保留仍有实际消费者的flat执行合同，新root不接受旧作者格式；integration提供者按注册表root核验，
不再从目录名推断owner。冻结合同和每份依赖核对源／副本SHA；代码库存记录owner、消费方和明确文件。

工程预算初始化唯一实现已移至`integrations/runtime/engineering_budget.ps1`，local／cooled及尚未迁出的
实际分段消费者共用；旧定义删除。入口真实PowerShell加载与预算冻结行为测试覆盖缺失函数、错误身份及非法预算，
预算身份直接复用公共复制器的验证结果。新目录依赖闭包包含该模块，不加载旧family大包装来获得一个函数。

纯测试已验证新区／旧区provider边界、错误owner与路径拒绝、OA及冷却依赖导入，以及直属二区／三区
准备器脱离仓库后的真实快照编译；删除关键schema或提供者后会失败关闭。这些验证不启动求解器。
[直属门禁](../../verify_integration.ps1)检查直属runtime、analysis、workflows、tests及其测试发现；
原整机测试仍由旧集成门禁拥有，冷却测试归直属门禁。共享runtime与空间绘图变动同时路由实际消费它们的两个门禁。
L1／L2发现和依赖路由统一由
[门禁目录](../../../common/gate_catalog.json)登记。

## OA／IP接口准备与绑定

[accelerator_interface/execute.ps1](../../workflows/accelerator_interface/execute.ps1)接管OA需求准备、IP设计准备
及实际场／工作台绑定；新run owner为`instrument_assembly`、mode为`accelerator_interface_preparation`。
原MR公开准备脚本与CLI已删除，MR模块只保留其参考核验、执行科学合同、纯设计约束、物理几何与场适配。
跨项目组装物化归直属`geometry.py`；已删除MR旧组装编排与手写平移合成。
IP设计解析、注册后几何生成和装配探测器渲染也已收回该模块；MR不保留转发副本，
仍由原模块提供其原生CSG、屏蔽及场构建所用的底层操作，避免器件提供者反向依赖集成工作流。
迁移前后seed、CSG和GEM对照一致；场计划与报告排除临时fixture路径及其派生身份后科学值一致。
真实依赖冻结后的OA准备、IP状态交接和已准备联合源物化三项脱仓回归通过；没有为此重新求场或飞行。
本次几何／装配24项、IP／Prism局部几何19项和静态绑定90项回归通过；原生静态场提供者模块
执行56项，其中2项原生opt-in跳过，其余通过。此处是无商业求解器回归，不增加真实飞行或GUI资格。
IP几何、原生电压和出口仍由IP提供，MR保持匹配需求、Prism／镜／Stripe和专属屏蔽调整的权威。
准备器复用已解析来源、请求、轨迹和返回seed配置；IP的GEM renderer仅接受已解析native projection，
不再重读这些输入或重复编译。76项接口／物理回归、57项准备／绑定回归已通过；
真实冻结后脱仓执行覆盖机械plan与GEM，四份GEM与拆分前字节一致。这些证据不包含新的联合飞行。

IP实例身份已从冻结recipe进入实际CSG，再由现有field authority继承，静态绑定直接与同一recipe核对；
删除无生产消费者且重复电压的`namespace_map`，未另加receipt实例表。接口几何7项与静态绑定90项回归、
Ruff及语法检查通过。现有solver namespace／ID、15路电压和GEM保持原语义；适用范围仍为单IP、
`pulse_held_rf_zero`静态投影及接地detector 25，未授予多IP动态驱动或新的原生飞行资格。

设计准备阶段只冻结可审查的设计输入和候选执行合同；不得提前物化未来新IP源、运行Lua／FLY2、PA模板、
priority或workbench请求。`-FinalizeJointWorkbench`才在冻结设计输入上创建实际源和运行输入，随后才建立场／IOB。
这样一次设计准备不会产生会被finalize重新创建的草稿，也不会把未来物理输入误当成已验收运行输入。

从仓库根使用显式来源：

```powershell
& integrations/workflows/accelerator_interface/execute.ps1 `
  -AcceleratorProvider orthogonal_accelerator -ReferenceMrRunPath "<reference-MR-run>"
& integrations/workflows/accelerator_interface/execute.ps1 `
  -AcceleratorProvider dual_pressure_rectilinear_ion_processor `
  -ReferenceMrRunPath "<reference-MR-run>" -IonProcessorRunPath "<complete-IP-run>" `
  -MatchingRequestPath "<explicit-schema-3-request.json>"
```

`-FinalizeJointWorkbench`要求同一参考MR、新owner的`-PreparedInterfaceRunPath`、实际新IP源及MR拥有的
`-JointFieldRunPath`；此阶段调用SIMION建立／重载IOB并做只读场审计，不执行Fly。
完整物理边界与候选来源仍见[MR接口说明](../../../projects/parallel_mirror_dual_stripe_mr_tof/simion/README.md#加速器选择与接口准备)。

每条准备与飞行workflow独立选择冻结消费闭包；已删除私有动态Python加载和逐份源码复制，场审计直接
使用冻结模块，不再物化另一份实现。新准备包只从manifest唯一记录核验消费文件，不挖掘run_config的
第二份文件记录；同一调用内复用已读manifest。输入复制只计算源身份和目标核验各一次。
两个Python写入CLI均先核对目的run owner、mode和目录run ID，错误身份在物化前拒绝。

IP设计现在必须显式给出schema 3的`MatchingRequestPath`；`composition_plan`只声明完整父plan路径，
不手填字节数或SHA。父plan进入run时由既有冻结入口建立身份，再由公共解析器派生显式local范围或默认full。
finalize仅消费design manifest绑定的请求、父plan、selection与dependency，不回读活动默认。
现有[父plan](../../config/recipes/ip_mr_y_minus55_plan.json)由183839实际装配报告的冻结recipe／components
重编译为v3，代表明确的y=−55 mm工况，不是自动适用所有参考MR的默认。原独立recipe副本已退役。

IP与MR分别发布真实E14出口屏蔽外端面和E18入口框端面；先解析科学匹配要求，再由直属geometry消费
父plan的IP native→MR直接位姿，并逐值核对实际提供者接口，不在执行中替换父组件或重新造配方。
handoff schema 3及其resolved请求保留同一实际范围；改变父装配不会重新投影或裁剪源。
已删除按MR锚点减源出口中心反推位姿及内部制造配方。
接口范围仅为IP出口屏蔽到MR入口框，实例ID由所选配方连接决定，不代表全仪器电极绑定；当前只支持已接线的native方向、
MR identity及一条`monolithic_joint_solve`连接，不支持的范围／方向／耦合直接拒绝。
实际P1间隙只由配方声明；MR保留最低净距约束，LP对中央屏蔽的最低净距不随P1实际间隙混用。

CSG直接消费plan的native位姿。源先使用冻结provider坐标合同解析其现有表示，再与同一native位姿合成，
一次投影完整位置和速度；不是另一份装配位姿或补偿。原ID、物种、出生、到达、epoch及全部母群损失保留，
已在MR frame中的handoff状态不能再次套用装配位姿。

上述显式配方与源映射的11个完整回归模块共127项通过，覆盖公共冻结后的脱仓准备与finalize、完整6D及
母群／时钟保持、实际间隙独立变化和非法耦合拒绝；四份既有GEM字节保持。这是无商业求解的接口回归，
新显式配方尚未经过原生联合求场／飞行复验。

schema 3真实纯准备`20261024_144917__analysis__python__accelerator-interface-ip-2475088f`已由公开入口完成，
38项输出完整manifest核验通过；仍使用183839原IP源`20261016_121423…`及原MR参考`20261015_040845…`，
未执行Refine、Fly或IOB，也未读PA／MPH。四份场计划GEM及collision／detector／IP seed三份GEM均与183839
字节相同，baseline／native_operating_point／numerics、直接pose及电压seed保持。完整census仍为100／97／3且字节相同；
97行handoff仅source／target组件列由项目名改为实际实例`ip_exit_shield／mr_entry_frame`，其余26列逐值相同。
整体JSON中的运行路径与当前plan身份变化不是物理变化；该证据关闭本次输入迁移的纯准备对照，不授予新的联合飞行资格。

IP出口API 2由调用方显式传入本次实例对，不再预选MR项目；component出口采用schema 2，MR handoff采用schema 3，
canonical CSV仍为v1。root只解析一次冻结配方连接，几何与handoff共用；真实`source_project`／`source_run`
来源另行保留，MR继续核验实际提供者、端口、方向、场及clock。独立source／centroid消费沿同一冻结绑定验收，
不把项目名当成实例名，也不复制另一份路由表。旧活动出口／handoff收据明确拒绝，历史冻结快照不改写。
7个完整模块81项通过；补充消费者发现一处共享fixture仍写旧实例名，修正后4个完整相关模块49项通过，
与前轮存在覆盖，不相加。验证包含实例改名后GEM字节不变、100母群／81实测出口／19损失及科学failed保持，
并通过公共冻结后的脱仓完整交接；未执行新的原生求场或飞行。
实测源物化进一步复用同次已读粒子行、已绑定clock／epoch路径与验证后的时钟身份，投影由两次减为一次；
独立centroid／slice及公共时钟权威核验保留，不增加缓存、跳检开关或中间文件。44项完整源／分析／诊断
回归通过，FLY2、Lua、canonical、census及映射等七份小产物字节保持。失用的provider／consumer支持模块
清单已从专有依赖描述中删除，实际消费闭包只由现有runtime dependency库存维护。

真实入口验证：新owner的
[`20261022_173402__analysis__python__accelerator-interface-oa-d6ddcd43`](../../../../artifacts/projects/instrument_assembly/runs/20261022_173402__analysis__python__accelerator-interface-oa-d6ddcd43/summary.json)
已完成OA需求准备及success发布，保持参考轴向能量每电荷4372.010347796 V、y=−55 mm和MR原frame名称；
没有启动求场或飞行。IP准备运行`20261022_173455__analysis__python__accelerator-interface-ip-e771b207`
在新候选配置校验处失败并封存：历史源的baseline未显式声明独立屏蔽出口孔宽，而当前作者合同要求显式声明。
修复已在物理源→当前作者seed的编译边界实施：始终从已发布E14矩形cutout取得显式孔宽，
本工况为0.8 mm；已有作者宽度与实体冲突时在建立输出前拒绝。不改历史源、不使用当前默认或Pull孔宽，
也不放宽当前作者校验。17项回归覆盖0.8／1.2 mm、源字节保持及完整原生CSG一致。

[`20261022_174324__analysis__python__accelerator-interface-ip-d54518ec`](../../../../artifacts/projects/instrument_assembly/runs/20261022_174324__analysis__python__accelerator-interface-ip-d54518ec/summary.json)
已从原设计真正的原始源`20261016_121423__sim__simion__ion-processor-thermal-n100-auto`和原冻结请求完成
新owner设计准备及success发布。与原设计`20261016_141429__analysis__python__mrtof-accelerator-interface-ip-f38b8fc3`
比较，`assembly_geometry.json`、父场`assembly.gem`和IP seed `processor.gem`三份文件字节完全相同，
抬升候选仍为4480.043790844389 V。只将原实体孔宽显式写入当前作者配置，没有改变实体或运行优化。
原设计三份消费记录分别核验其manifest，新运行由公共发布边界核验。

此前`20261022_174122__analysis__python__accelerator-interface-ip-6775aa40`证明新入口可执行设计准备，
但输入选的是已匹配源`20261016_152536…r02`，原公式因而得到4487.407003119315 V的另一个未验证候选；
它没有用于求场／飞行，也不作为迁移等价对照。后续绑定必须消费与当前显式seed相符的新实测IP源及真实场资产，
不放宽原有精确匹配。当前结果仍是准备／字节对照，不是IP→MR联合飞行PASS。

新的提供者实飞源
`20261022_204654__sim__simion__ip-assembly-source-n100`已由IP公共入口完成并封存：消费直属准备包
`20261022_183839__analysis__python__accelerator-interface-ip-6523e335`的明确seed，复用相同原生几何与电压的
已封存IP场；100个原始ID全部闭合，97个提取、3个未提取，出口平均总能量4360.006878195222 eV。
完整manifest的195项输出校验通过。该结果仍属于IP提供者的简化原生电极功能范围，尚不是新owner的
IP→MR联合飞行，也不证明真实上游多极杆注入。后续绑定必须消费这份实际源，不能换回历史出口分布。

`20261022_215101__analysis__python__accelerator-interface-ip-b0f3ad17`已消费该实际IP源和明确的MR场，
完成新owner工作台绑定：四个PA实例重载后的优先级探针正确，98个接口场样点审计通过；未Refine或回写PA。
源为独立524 Da分支，不是下文未捕获的100 Da上游注入工况。小IOB模板只在私有运行目录暂存必要的PA别名，
终态保留唯一冻结模板资源并清除临时别名，不复制大场或在冻结快照中增加文件。
其后继`20261022_215610__sim__simion__ip-mr-migration-n100`已完成两批97／97粒子原生飞行及日志合并，
全部worker exit 0。自动诊断发现沿用的OA共同零出生峰形合同不适用于IP提取时钟，因此运行按failed封存，
完整manifest的212项输出核验通过，189,540,912 B证据保持只读。失败不抹去原生结果，也不能当成联合分析通过。
源头准备边界现已在飞行前拒绝这种错误合同。独立分析运行
`20261022_225514__analysis__python__ip-mr-native-diagnostics`已成功发布，完整manifest的113项输出校验通过；
分析显式引用实际IP源的`native_timing.json`及`ion_processor_epoch_zero_v1`，只改变峰形分析声明。
物理、数值和原日志保持不变，100母群中97个终态、23个检测器命中及3个上游损失全部保留；
相对实际提取脉冲的经验峰宽为20.0371921169 ns，时间域等价分辨率为19045.6276。
原failed运行不回写；原生运行与独立分析共同证明该524 Da冻结功能工况贯通，不授予Formal或数值收敛资格。

## 已准备IP→MR联合飞行

实际执行主体已从MR的`run_two_prism_trial.ps1`迁至
[prepared_joint/execute.ps1](../../workflows/prepared_joint/execute.ps1)，旧PreparedJoint参数、函数和分派已删除，
没有转发入口。MR工作点控制器的两个实际调用及子运行查找均已切换；父控制器与场提供者仍由MR拥有。
OA→MR现在由`materialize_trial`在原trial receipt发布唯一`resolved_iob_pose`，运行器直接消费，
删除独立`poseCode`与static分支重拼。等价输入复用已解析几何；reviewed／trajectory／accelerator确实不同时
保留各自原有投影与净距检查，不把不同authority强行视为相同。154项相关纯回归通过，三种模式的
FLY2／operating Lua及两份provider GEM共8份输出字节保持；未执行本轮原生重开或Fly。

当前OA→MR接线进一步改为显式冻结完整`CompositionPlanPath`及可选`LocalScopePath`，
从同一父plan选择唯一OA `axial_exit`→MR `accelerator_entry`连接。
源坐标、出口位置及IOB origin共同消费该直接位姿；不再以旧focus参数重新推导第二套放置。
二区OA出口由提供者实际电极派生，示例配方为`oa_mr_two_zone_gap30_plan.json`，仅适用于其声明的组件接口；
当前renderer仅支持OA/MR identity rotation、MR原点和选中范围内这两个器件，其他情况明确拒绝。
更新后OA→MR入口完整37项回归通过；下游工作点控制器111项通过。
脱仓执行回归曾暴露OA提供者的传递依赖遗漏，现已补齐唯一依赖catalog，关联依赖完整7项回归通过。
修改的五个PowerShell入口AST解析、直属Ruff及生成绑定新鲜度检查通过。
下述N=100运行属于此前接线版本，不能替代本次父plan接线的原生重开、Fly及GUI验收。

2026-10-25以085317冻结真实输入准备当前父plan时，公共接口检查拒绝上述gap30示例：
该工况MR真实入口为z=−1.5 mm，示例声明z=−30 mm。新scratch作者
`oa_mr_current_plan_author_20261025`保留OA／MR直接位姿及源，以提供者真实接口编译具名1.5 mm配方，
不移动器件补偿间隙、不改旧配方。实际准备另暴露出口参考调用漏传`direct_pose`，已直接透传已有结果；
完整相关模块66项／40.768 s通过。修复后真实`materialize_trial`成功，FLY2及工作点Lua与原输入逐字节相同，
17项科学字段、完整出口参考、IOB origin／网格及静态场记录保持；仅stat原12个PA／surface引用，没有复制或求场。
Program包含后续公共波形与电压映射变更，不能宣称字节等同；当前原生重开与飞行仍待验收，亦未授予30 mm设计资格。

普通OA飞行主体另已迁至[oa_mr/execute.ps1](../../workflows/oa_mr/execute.ps1)，旧trial入口已删除，
其新owner运行`20261022_224026__sim__simion__oa-mr-migration-n100`已完成N=100实际飞行：
两批worker exit 0，100个终态完整，98个命中检测器，2个实际碰撞P2接地屏蔽，收集率0.98，收集门禁accepted。
原生飞行、日志合并和自动分析通过；随后普通compact分支误用轻证据finalize-ready，
因必要冻结模板与原始日志使证据包超轻量上限而失败，旧异常收尾又将manifest写为interrupted。
公共owner已释放本run残留的零承诺保护租约并封存36,060,746 B／201文件，完整manifest的48项输出校验通过。
原interrupted科学状态和所有日志保持只读；这不是成功终态发布PASS，也不以重跑或改状态掩盖生命周期缺陷。
直属owner终态已统一为科学manifest发布后再封存停止载荷；封存失败不再覆写科学状态，
容量收尾失败不覆写已发布的科学状态；终态发布本身也失败时保留checkpoint、不执行封存。45项OA／trajectory纯回归通过。修复后的真实复验
`20261023_085317__sim__simion__oa-mr-terminal-seal-n100`已完成两个自然exit 0批次，100个终态闭合，
98个检测器命中及2个电极碰撞保持；完整manifest的24项输出核验通过，38,126,638 B／201文件已由owner
封存为ready且pin。该结果关闭普通OA→MR入口的科学终态发布及容量收尾缺口，不授予GUI或Formal资格。
跨项目飞行的新run归`instrument_assembly`，已准备IP飞行mode为`prepared_joint`，
OA飞行mode为`oa_mr`；不改写既有MR运行。

从仓库根使用显式的已封存准备包与观测合同：

```powershell
& integrations/workflows/prepared_joint/execute.ps1 `
  -PreparedJointWorkbenchRunPath "<prepared-run>" -ContractPath "<observation-contract.json>"
& integrations/workflows/prepared_joint/execute.ps1 `
  -AnalyzeRunPath "<sealed-native-run>" -ContractPath "<explicit-analysis-contract.json>"
```

同一入口的Analysis参数集不启动SIMION，不复制PA或原始重日志；它冻结新的分析合同和来源绑定，
从已封存完整原生日志发布独立分析run，mode为`prepared_joint_analysis`。只允许峰形分析声明变化，
其他科学、数值、源与时钟身份必须保持一致；不接受通过后处理改写飞行。

工作流从唯一依赖清单选择`prepared_joint`消费闭包，后续Python在冻结snapshot下运行。局部前端也只选择
自己的闭包，不附带MR源码。MR继续提供其物理准备、Program、场适配器与诊断；其余已准备`joint.*`侧车
从准备包的manifest绑定来源冻结，不重画内部几何或复制另一套物理实现。

新prepared联合飞行继承准备包已经冻结的完整v3父plan及schema 3 matching request，沿同一公共解析器
派生原request声明的full／local范围，不新增第二份作者范围或重新读取活动配方。trial绑定父plan、
matching request的本次冻结副本与派生scope，实际核对实测源实例路由、IP场注册及MR在场坐标系中的
identity位姿；不重新物化整份派生plan。缺少当前冻结合同的历史准备包明确拒绝新执行，原运行保持只读。

2026-10-25真实输入复核发现实例路由名混入场几何／电压authority，导致物理相同的旧场不能被新父plan消费。
现将路由归当前设计与父plan，场自身继续严格核验冻结CSG、实际registration、IP15电压、工作点、网格及全部细域；
finalize在冻结／导出新输入前核对当前scope、源配置和实际pose，同次绑定复用已核验结果。
仅顶层历史`ion_processor_instance_id`不参与科学CSG比较，没有旧schema执行fallback或新的field owner。
原055优化MR电压及额外IP细域必须保留，不能换成040845参考场。联合准备两处canonical调用也已改用公共typed loader；
六个完整模块149项／550.937 s通过，含脱仓准备、当前finalize→trial、实例路由与IP电压／工作点／lift／basis漂移拒绝。
首轮148项曾有1个failure及45个error，涉及旧实例名断言、过小stub及上述真实typed调用遗漏，均已在该重验闭合；
没有以修改时钟或阈值消除类型错误。源码回归不构成真实场准入或原生验收。

真实144917设计＋055场的预检越过原路由阻断后，公共退役验证曾拒绝实际消费的r02
`simion/collision/collision.pa`（1,777,745,864 B）：普通读取身份不符；单独一次公共无缓冲读取与原冻结SHA一致。
原负证据保留于`ip_mr_current_plan_preflight_20261025/collision_persistent_identity_20261025.json`，没有更改预期SHA。
最初预案`20261025_041405__analysis__python__ip-collision-view-repair`因5,333,237,592 B承诺超过
2,590,122,329 B余量，仅封存为8,119 B轻checkpoint。后来旧承诺按租约规则过期，只读余量13,267,417,825 B，
新MR owner审计`20261025_084909__analysis__python__ip-collision-view-repair-apply`沿既有公共流程取得资源与容量准入，
完成双独立快照、两种读法核验及同字节对象替换。原manifest／退役receipt不改，旧对象与独立snapshot保留；journal状态complete。
首次审计发布遗漏retention receipt，错误收尾又误用了SIMION批次专用PreserveRawOutputs；保留失败summary后补公共retention，
无文件删除、无重复repair。success manifest已验证发布后，默认light finalization拒绝3.56 GB原生审计载荷；
沿既有`seal-stopped-payload`闭合为ready/rebuildable_payload并pin，3,555,511,023 B／10文件。
后续从源重新准备须新run；本次没有重新求场、飞行或改变冻结源。修复只关闭资产读视图，不授予物理或完整三组件资格。修复后实际144917设计＋原055场＋204654实测源的
`_joint_binding_inputs`预检21.324 s通过，报告为`ip_mr_current_plan_preflight_20261025/post_repair_actual_input_preflight.json`；
保持原CSG、registration、优化MR工作点及所有细域，没有新求场或源变更。该通过仅为冻结输入与物理场绑定准入。

三实例父plan的真实设计准备`20261025_090904__analysis__python__accelerator-interface-ip-f3a137ee`
已由公开入口完成；IP／MR显式local范围沿同一完整MP／IP／MR父装配派生。与144917的原CSG（仅排除旧路由元数据）、
baseline、numerics、工作点、坐标变换及源定义逐值相同，见`ip_mr_shared_parent_20261025/design_identity_comparison.json`。
首次finalize的091246在原生阶段前暴露缺失`common.simion.native_completion`冻结依赖，已补实际消费者及脱仓回归；
091545完成IOB保存、重开和98点场审计后，在容量收尾因77个非必要pycache使证据包超过25 MiB轻量类别上限而失败。
旧错误路径又覆写了已发布success；该failed负证据及26,444,505 B／292文件保持只读，owner已沿公共机制封存ready并pin。
入口现用`-B`禁止生成字节码，并把科学终态发布与容量收尾顺序分开；容量错误不再重写已发布终态。
完整入口模块10项15.547 s通过，含真实公共writer／adapter的发布前失败、发布后失败和成功路径。

新身份`20261025_092535__analysis__python__accelerator-interface-ip-611a291c`已由相同公开入口完成，
success、light_evidence/ready，23,040,969 B且无pycache；保存／重开／4实例优先级检查及98点审计执行通过，
没有Refine或Fly。审计报告仅为reported，energy acceptance未声明、physical matching未授予；
去常数电势最大残差0.127649 V及最大场差276.799891 V/mm不能表述为物理等价或数值收敛通过。
后继公开联合飞行092919在启动SIMION前因冻结闭包遗漏assembly_recipe Schema失败，已正常发布failed并封存ready，
保留4,276,307 B／146文件。现有依赖清单已补prepared_joint三个装配Schema；实际三组件父plan的脱仓解析回归
通过，逐个缺少resolver、machine_contracts、rigid_transform及三个Schema均由新进程拒绝。
完整依赖模块9项46.718 s、Ruff和绑定检查通过；不得手工补旧快照或复用旧run ID。
后续新身份提交被自动审批拒绝，理由认为存在更近的不启动大型模型限制；已请求用户针对该97粒子／100母群运行
确认。用户随后明确允许提交该IP→MR验证，新身份已沿公开入口提交公共队列，
日志为`ip_mr_shared_parent_20261025/joint_frozen_closure_public_runner.log`；未绕过审批。
新运行`20261025_093701__sim__simion__ip-mr-joint-841cccc2`已开始97个原交接粒子／100母群验证。
公共调度器首批10粒子观测45 s后规划剩余87粒子；观测峰值40.91 GiB、当时可用6.52 GiB，
内存容量只允许一个worker，CPU容量为14，故本轮串行来自实际内存限制，不是随机碰撞或私有单发策略。
首批仍继续时只告警，不因日志静默或耗时中断。
该原生日志另暴露加载`ip_collision.pa`和`detector.pa`时隐式Refine：首批2.77／0.04 s，第二批2.83／0.01 s，
两批合计5.65 s；不能称为零Refine。
两源均在实际Read/FileShare.Read保护列表中，launcher及Program没有save；全部有效实例的电场由静态adapter覆盖，
载体非电极势不作为科学工作场，电极mask与源不变。缺口是既有预载入只覆盖粗碰撞PA及可选overlay，漏掉两载体。
修复沿同一官方RAM `refinable=false`预载入循环投影实际occupancy路径，不修改运行中的冻结副本；后继192240已完成下述原生验收。
当前源码已补IP碰撞及detector路径运输投影，沿原循环在Fly前驻留并设置RAM nonrefinable，规范化路径去重；
没有save／refine／close或新的载体副本。官方依据为SIMION 2020本机
`examples/field_array/comsol_to_pa.lua:136`（2026-10-25核对）。两个完整模块77项32.344 s通过，
覆盖冷／暖／全部驻留／重复路径及ambiguous拒绝，普通OA回归保持；实际sidecar保持scalar／corridor场绑定、
97状态、母群、epoch和IOB。此轮仅为无商业软件回归；后继192240以原81交接群完成原生无自动Refine验证，不替换97群原科学证据。
093701已完成两个自然exit0批次，实际10＋87 splats，公共合并／诊断及终态发布通过，run与manifest均success。
owner封存ready/rebuildable_payload并pin，358,623,044 B与实际相等。原97 ID为1–100排除24／64／80，
源CSV、census和上游clock与092535逐字节相同；100母群由3个上游not_transferred、23 detected和74 downstream loss闭合，timeout为0。
绝对epoch为7500.63364160348 μs，birthclock差0；KDE以共同提取脉冲7500.135135135135 μs为时间参考，
23个存活者FWHM为20.037192116888036 ns、时间等效R为19045.627632155698，仅survivor-conditioned。
这些计数及声明指标与225514逐值相同，不扩大为全轨迹逐值相同、数值收敛、完整动态RF／碰撞、GUI或Formal资格。
该实测关闭当前三父装配派生IP／MR局部链的功能接线；新预载入避免自动Refine的原生缺口由后继192240关闭，见下文。
本轮修复与重试未重复求场或飞行；新准备仍会保存绑定自身路径的IOB，不能宣称IOB阶段恢复或求解器checkpoint续算。
完整三实例父plan及两段显式local的原生飞行验收仍未闭合，不能以冻结旧分段链替代。

另用095324真实多极杆注入后的81粒子群、090904设计、同055场及103822冻结trajectory合同准备新工作台，
`20261025_111457__analysis__python__accelerator-interface-ip-60652ef7`在Python准备阶段失败并发布failed；
未构建IOB、Refine或Fly。实际栈在055场的历史operator ancestry，经r02退役owner的全量验证，报告
`preserved evidence identity differs: simion/collision/collision.pa`；不是源CSV或81粒子母群失败。
该碰撞载体仍被下游实际引用，不能简单豁免；正在核对实际消费校验与祖先整包重读边界。
旧收据、PA和084909修复证据不改，不以先前成功或一次普通读取失败证明当前载体字节结论。
该次预审时110745单反射整机链不依赖这份r02载体，81链仅做准备诊断，尚未提交大型Fly；后继状态见下文115429／192240。

对应修复沿公共`verify_retirement`的显式保留文件投影核验祖先小元数据，准确退役成员、owner、
终态和来源身份保持；默认整包验证不变。旧仅有测试消费者的人工joint资产格式已删除，
`static_field_binding.verify_joint_asset_records`直接核验当前实际native字段与实例记录，按路径及内容身份去重。
工作台入口在取得原只读guard和准备许可后核验一次；待飞批次入口在实际需要原生工作时同样核验一次。
metadata解析、候选比较、worker物化和分析不重复核大载荷，全批复用也不进入guard／原生核验分支。
真实PS消费边界及损坏载荷拒绝、最终候选选择、全复用缺guard路径等focused回归通过。
最终稳定五模块230项948.912 s通过（公共107、static93、joint11、接口11、prepared8），
Ruff、两PS解析、绑定及差异检查通过。该轮为直接unittest，未先进入公共GATE，是执行准入缺口；
不把它表述为L1。结果仅存工具会话27187，长输出有截断，没有可声称完整全文的日志文件；
最终公共门禁仍须在相称准入下保留完整结果。源码在该稳定轮开始后保持不变。
055当前实际消费集合为15个唯一PA／surface／载体，封存大小合计34,969,150,420 B；没有为此复制或生成PA。
新`20261025_115429__analysis__python__accelerator-interface-ip-81ed4b78`已沿同一81粒子源和合同完成轻量finalize，
实际消费边界`JOINT_NATIVE_ASSETS=PASS`，原生四实例IOB保存／独立重开及82点接口场审计通过，run成功发布。
日志为`ip_mr_shared_parent_20261025/measured81_consumed_assets_finalize_public_runner.log`；
未Refine、回写PA或Fly，readiness仅为配置与场身份，不授予6D匹配、time focus、GUI或Formal资格。
该实际运行关闭111457的祖先整包重读阻断，原失败证据保留；不代表所有COMSOL mask／response表示均已覆盖。

单反射原生验收结束且用户决定暂缓GUI后，正常公开入口已启动
`20261025_192240__sim__simion__ip-mr-joint-04e5b6ad`，消费115429成功准备及原103822 trajectory合同。
本轮实际执行81个原交接ID，保留100母群和19上游未交接；Q8、最大步长0.002 μs、0.1 μs观察及2 GiB输出预算不变。
不传历史等价参考或continuation，必须真实越过当前IP／detector RAM nonrefinable预载入，不能靠复用旧Fly关闭该缺口。
日志`ip_mr_shared_parent_20261025/measured81_current_preload_joint_public_runner.log`现已记录完整成功终态；
两批9／72粒子自然exit0，原生分别9 splats／180.15 s、72 splats／1193.87 s，合并、自动分析及公共发布通过。
run与manifest均success，owner封存ready／rebuildable_payload并pin，319,759,751 B／346文件。
原15份PA／surface直接受护消费，无复制或重新求场；两批完整日志均无`status,Refining`，实际IP／detector等三载体预载入存在，
该结果关闭当前预载入避免隐式Refine的原生缺口，不把RAM裁剪的`refine=false`诊断混作求场记录。
母群100由19上游未交接、20 detected及61 downstream loss闭合，timeout=0；81个出生clock实际核验通过，最大绝对差0。
检测存活群FWHM为18.32076721359499 ns，时间等效R为20829.938083638204；仅survivor-conditioned，
不宣称完整全轨迹等价、上游IP性能达标、六维匹配、time focus、数值收敛、GUI或Formal资格。
公共调度实测后按内存容量使用一个worker，内存告警保留健康进程；无危险终止或自动重试，未以随机碰撞作为串行理由。

全批复用与仅分析现已在同一绑定接口分开冻结小元数据及实际PA使用：native operator／overlay元数据
不再读取PA header，实际vendor边界在原guard下核验所消费的当前PA／surface。完整provider及退役回归、
真实97粒子仅分析，以及OA零待飞／部分待飞行为证据见本页当前边界；这些证据不等于完整owner原生恢复资格。
非IP历史collision plan仍有实际网格／footer读取需求，不能泛化为全部表示均无PA依赖；
不得全局放宽普通`_record`或新增恢复状态机／模式开关来绕过真实输入核验。

真实多极杆→IP的同父装配准备`20261025_095420__analysis__python__multipole-ip-preparation`
已由正常权限公开入口成功封存，10项输出record核验通过，light_evidence/ready、895,962 B。
父plan包含MP／IP／MR，显式local为MP／IP，边界为ip_to_mr；100个原出口ID、母群census／fates、clock及epoch保留。
与091221准备及095324冻结注入逐字段对照，唯100行position_x_mm因父坐标表达组合出现2.842170943040401e−14 mm最大差，
其余字段精确相同，母群和时钟文件逐字节相同；不钳零、不补偿，不声称状态CSV字节相同。
095420只证明real exit mapping，没有重飞IP或授予入口截断／独立场资格。此前094705因沙箱无法观测其他正常权限预约的
PID2064创建身份在capacity_startup失败，未进入冻结／准备，3,932 B轻证据已封存；同输入正常权限重验如上，不放宽调度保护。

无求解器验证覆盖实际runner的成功、分析失败与封存失败路径，使用公共manifest写入和核验；错误child
owner／mode被拒绝。真实冻结快照在清除仓库PYTHONPATH后生成批次，保持原粒子ID、源Fly2和Program字节。
MR回归保留100母群／97 handoff、绝对时钟及上游损失；`pulse_held_rf_zero`边界不变。历史MR飞行仅能作为
明确身份绑定的只读equivalence证据，新运行不接受旧身份。上述原生飞行及独立分析已闭合524 Da功能工况；
MR完整组件接口已发布真实20电极身份（1…18、20、25），不是端口代理；E19为无实物合同槽，E15等共享接地有真实依据。
CSG、冻结静态电压及GEM／CAD消费者已有唯一提供者，不能为“补完整接口”重画MR或复制驱动权威。
剩余M3消费投影及适用GUI／数值／真实父装配分段验收仍按各条实际证据闭合，不由接口回归自动授予资格。

已准备联合飞行的Q及最大步长改为直接解析冻结JSON合同；准备边界冻结参考materialization，
核对其实际compiler主合同身份、profile与相位，超时复用原MR公式及nominal源合同。
独立trajectory合同可以具有不同文件身份；执行时仍只接受原规则允许的合同变化。
finalize及trial消费准备包中的冻结参考，不再回查原MR运行或从Lua提取这三个数值。
唯一生成器将它们显式写入工作点，物理reference Lua保留一份；不再复制随后覆盖的priority或核验不消费的旧wrapper。
源、场、时钟和裁剪数学保持原有边界。五个完整模块52项回归通过，最终清理后的两个完整模块23项通过，
包括原参考运行不可访问时的准备与分析；这是无求解器验证，不代替新工况原生验收。

## 真实多极杆→IP状态交接

源端SIMION运行器已区分科学负结果与执行错误：有效evaluation的预期FAIL继续正常封存完整
`failed`、原checks及`native_execution_complete`，finally释放后仍返回退出码1；PASS返回0。
执行、解析、资源及发布错误仍走原异常收尾。准备器和IP admission共用同一提供者结果判据；旧通用failed
或未完成状态不借历史fallback准入。接受科学负结果仍须通过实际出口6D、原生步括号、完整母群和clock校验，
阈值不变。仅实际注入路径加载此领域校验，不给普通OA／冷却路径增加多极杆设计依赖。
68项完整受影响回归、2项failed冻结脱仓及2项最终CLI收尾行为通过；这些是纯回归，不是新的原生失败工况验收。

[准备入口](../../workflows/multipole_ip/execute.ps1)消费[显式N=100工况](../../config/experiments/multipole_ip_through_exit_n100.json)，
作者配方将multipole真实机械出口直接贴合IP裸导引入口，`gap_mm=0`、`state_handoff`。既有作者配方的IP
采用native frame与identity位姿；准备器从冻结父配方的两端直接位姿调用公共`relative_transform`，
将实测出口状态一次投影到IP局部坐标，不要求父装配以IP为原点，也不改写父配方。准备器不传播间隙、不把粒子吸附到入口、不按IP
自由包络裁剪母群，也不重采样。IP提供者真实guide inlet来自八根实体杆端，不是下游HP入口透镜孔。

真实准备运行`20261022_211536__analysis__python__multipole-ip-preparation`已成功发布；消费八极杆提供者
`20261022_210633…`的100个实际外出口状态，以及IP提供者`20261022_204654…`的真实几何。
公共canonical状态、原ID、100 Da／+1、原出生、绝对到达时间、clock及全部母群fate已冻结，
只有一次空间投影，后续IP接收这些实测状态。零出口明确发布null状态引用并保留完整fate，不能制造空表实飞。
8项行为测试包含真实Freeze→脱仓准备→IP接收包校验。
本准备器从唯一配方连接贯穿两端实例身份，组件映射、直接位姿、状态CSV及IP接收包使用同一连接。
不再限定实例名或依赖实例数组顺序；实际执行范围仍只接受两个选中实例、指定真实提供者、零间隙及指定端口；IP求解状态采用其native frame，父装配位姿不受此限制。
作者schema 2现显式引用完整v3父plan；local范围从同一父plan派生，不要求父配方只有这两个实例。
当前作者plan由211536冻结旧plan的原recipe／components重新编译，并与实际两端resolved接口逐值核对；
旧run不改写。15项完整回归验证新增父部件不改变局部状态、fate、census及clock，也明确拒绝不支持的full范围。
两个完整模块22项回归通过：改名与倒序后真实冻结脱仓准备及接收保持六维、物种、出生／到达时刻，
clock／epoch／fate／census字节相同；零出口仍保留null状态和完整母群。不增加schema、selector或兼容分支。

2026-10-25已移除准备器对父frame及IP原点的额外限制，直接复用公共相对变换；没有新增坐标字段或补偿位姿。
完整准备器及公共坐标模块30项回归通过，包含整体非单位旋转／平移、显式local及父配方新增未选中实例：
IP状态CSV、母群fate／census和clock／epoch字节保持，父recipe原样冻结；既有脱仓冻结与接收测试仍通过。
该轮同基线CLOC完整按语言报告见产物根`instrument_assembly/scratch/iob_path_probe_20261024/public_mechanisms_and_repair_cloc.log`；最新累计值见本页当前快照。
初轮16项中两项失败分别为作者plan的旧CRLF字节record和类型化loader的空相位断言；已核对旧record恰好匹配
同一plan的CRLF表示，沿公共file_record刷新当前LF作者引用，并将空值断言改为Schema的null；没有改变几何或源。
这只关闭多极杆→IP准备适配器的父frame限制，不等于已完成三组件真实父装配或新的原生飞行。
2026-10-25已闭合两份IP接口阻断：唯一提供者同时发布guide_inlet和extraction_exit，
沿用原生具名电极集合及其驱动组；删除guide-only公开API，不保留旧variant兼容。
实际204654与524 Da注入095324的完整native_projection、baseline、numerics、native_operating_point及
coordinate_transform此前逐值核对相同，无须另建接收版IP。15个电极集合不是390个独立CSG电极；
接口ID不按渲染分块重新枚举，完整尺寸与实际电压继续由原有投影／场绑定负责。
两份活动成对作者plan由公共compiler重编译，原直接位姿及connection_checks逐值相同；MP/IP请求身份沿公共file_record刷新。
新增`config/recipes/multipole_ip_mr_y_minus55_plan.json`为显式三组件父装配，保留原MR坐标、IP注册与MP/IP相对位姿；
默认full含三个实例，两种local范围均从它派生，未将它自动替换为既有成对实验的最新整机。
提供者接口完整5项回归通过；MP/IP、accelerator geometry/interface及MR assembly/handoff五模块67项25.403 s通过，
另有新活动三组件作者派生检查1项0.951 s通过。新测试实际调用两端准备器：三组件父recipe保留，IP局部状态／
母群／clock字节相同，四份MR准备GEM与原基准字节相同；未消费端口或电气组漂移也拒绝，既有脱仓冻结测试仍通过。
这证明同父装配准备机制；新三组件父配方下的原生接续、资产视图修复及适用验收仍待闭合。
此前L1日志无终态且原owner／末尾工作PID均已不存在；没有据此报告通过。稳定源码已提交新的公共L1，
日志为`migration_l1_full_ip_interface.log`，已通过卫生、文本、文档、开发标准、Ruff及Freshness，当前公共host回归仍在执行。

真实后继`20261022_213053__sim__simion__multipole-injected-ip-n100`已由IP唯一公开入口执行并以failed封存；
100个原始ID和全部终态闭合，74个进入HP、0个捕获、0个提取，既有acceptance六项均未通过。
完整manifest的198项输出校验通过；终态原样保留1个backward_escape、18个radial_escape和81个solver_stop。
输入仍是实际100 Da／+1，原出生0.006616368～0.875827777 µs与到达42.4896679278～43.6467650702 µs分别保留。
独立复核未发现接入映射、物种、出生／到达时钟或场／驱动消费错误：raw出口到root状态逐项相同，
root到IP冻结CSV逐行相同，100个worker beams及原ID种子完整；Fly2与source事件最大位置／速度差仅
1.78e−15 mm／2.27e−13 m/s，另核对了实际首个native sample未清零时间。当前输入在1500 µs捕获检查前
已全部终止，74个曾进入HP，其中20个后返guide；不能将solver_stop或径向接受边界当作已证实的金属撞壁。
这证明当前冻结state_handoff工况未实现捕获，具体机制及联合边缘场影响尚未确定。无出口群，因而不执行MR；
不调参、放宽阈值或借用524 Da源闭合该链。
独立场在贴合面处的边缘场截断仍未取得物理资格，也没有联合场、GUI或Formal验收。

公共多极杆入口现已支持具名`release_spec`生成run-local源，使用现有公共采样器；
runtime／预算只验证声明N，冻结后在原source preflight中采样一次，完整与分批投影消费同一CSV／receipt。
87项直接回归及真实脱仓物化验证通过；原CSV真实消费者不变，campaign／COMSOL未接入此模式时明确拒绝。
提供者现已完成[独立524 Da共同工况](../../../projects/rf_octupole_ion_optics/docs/PROJECT.md#524da-多极杆ip共同工况)的真实上游出口运行，
7项项目配置回归通过，包括一次物化源的身份／相空间对照，以及已选源或步数漂移拒绝、无关profile追加允许。
原N=100全部实际通过机械外出口，结果与资格边界由提供者记录。
无solver准备`20261023_091221__analysis__python__multipole-ip-524da-preparation`已通过公开入口及完整manifest的
10项输出核验；`ip_injected_source.json`保留原ID1–100、524 Da／+1、原出生及97.3575570518～98.6864420794 µs
实测到达时间，继承epoch=0。仅源manifest与物种声明切换到真实524 Da工况，零间隙配方及receiver保持。
后续IP原生执行必须使用该包、`204654/inputs`配置及真正求场donor`20261016_152536…r02`，不能把场借用者
204654当作本地PA提供者。
真实后继`20261023_095324__sim__simion__multipole-524da-injected-ip-n100`已完成11批100个原ID，
全部自然exit 0，wave耗时381.816 s；84个进入HP，81个捕获、转移并提取，19个未提取（1个radial_escape、
18个solver_stop）。实测平均出口总能量4357.602877340418 eV；原捕获／提取门限均未通过，其他四项通过，
科学状态保持failed，不修改阈值或重新定义母群。205项输出完整manifest核验通过，238,126,829 B／436文件
已由公共owner封存ready且pin。终态核验曾暴露公共PA输入无角色时误走普通读取；现复用既有分类器选择
与输出相同的持久读取，28项回归通过，不刷新旧SHA、不修改PA或重跑物理。
随后L1的脱仓检查发现两个工作流漏冻保留策略，已在唯一依赖清单补齐；小文件及非Windows普通读取
不再为无用分类加载保留模块。修复后28项manifest回归、两个真实冻结脱仓用例及三个完整相关模块的22项回归通过；
不以这些结果代替全部集成门禁。
提供者出口导出已按[数据与性能边界](../../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md)分离实测状态有效性与整体性能判定，
保留原failed、六项checks及upstream_incomplete；完整原生终态、母群闭合、身份与非零出口仍须有效。
绑定器保留实际设计、驱动、数值及物种约束，移除源抽样定义与设计seed全等的错误限制；22项回归通过。
`20261023_102431__analysis__python__multipole-ip-mr-binding-n100`已消费全部81个实测出口，
完成原生四实例IOB保存／独立重开及82点接口场审计；55项输出完整核验通过，未执行Fly。
独立逐行复核确认原ID、质量／电荷、出生及绝对时间保留，只应用一次IP→MR平移，100母群／81交接／19损失闭合；
冻结执行合同保持Q8、0.002 µs、0.1 µs和2 GiB预算。后继
`20261023_103822__sim__simion__multipole-ip-mr-n100`已完成9＋72两批自然exit 0，81个原ID终态、
合并及自动诊断通过；100母群中20个检测命中、61个下游损失、19个上游未交接完整保留，无下游timeout。
完整manifest的181项输出核验通过，319,573,281 B／329文件已由公共owner封存ready且pin。
按共同实际IP脉冲计算，20个检测幸存者的直接FWHM为18.3207672136 ns；该有限幸存群指标不能代表整束性能。
此结果关闭该524 Da冻结工况的实际状态／时钟交接、原生执行及终态发布，不改变IP性能负结果或授予GUI／Formal资格。
不能将既有100 Da历史源改标签或据此关闭原负结果。
资源回归另修正非交互worker夹具和被吞掉的原生终止失败；4项正确权限下的实际进程回归通过，
仍遵循既有观察式wall time策略，不因慢运行强杀健康求解器。多批wave尚未传递stage目录预算warning，
当前resource profile PASS仅指调度观测闭合，不能解释为未超过所有作者预算。

## 已批准缓存退役

2026-10-24公共owner精确部分退役151103失败运行中未进入Fly的六份重复前端PA，释放13,935,180,792 B。
新整机显式消费094111原发布场；151103的预算、源、GEM、IOB和负证据保留，原failed manifest不改写。
`151103/solver_review_retirement_receipt.json`公共核验PASS；重新封存为ready／pin，剩余168,166,284 B／202文件。
容量收据为`artifacts/common/capacity_disposal_receipts/20261024__151103-frontend-copy-reseal.json`；
原manifest不再代表全部原载荷仍在磁盘，历史消费须核对退役收据，不能将其当完整场源。

2026-10-24沿用户既有退役授权，公共PA owner取消两个已被094111场产物取代、无消费者／租约的未发布事务：
旧165147的key `88136758057DF2B46A17F7DEB9E4B20AD03DBA50BECC99913B7F02B28860FE83`删除14,236,421,706 B，
旧222921的key `448D1B69F0851C32C46390769A775505DB276BF9A13DBFFD274DB352CD4BD30D`删除17,795,522,162 B，
合计32,031,943,868 B（29.83 GiB）。两transaction均为retired／abandonment complete，原事务文本和逐文件删除收据保留，
取消请求位于`artifacts/common/capacity_disposal_receipts/20261024__cancel-unpublished-pa-<key>.json`。
原运行、重建输入及失败日志未删除；222921的failed manifest完整核验通过，并由公共owner封存为ready＋pin
（85,265,307 B／185文件），封存收据为同目录`20261024__seal-stopped-single-reflection-222921.json`。
退役依据是已被替代且无消费者，不是年龄或复核期限；该次退役保留094111、IP／MR场源及当时在途的101218。

2026-10-22用户明确批准后，公共容量退役流程已删除缓存
`7515B0E29014DCE3633FA17569992EB9B2CF1537F67B457ABF546474A86FBC24`和
`3CFD9E448429C40AA40EB5BB3FB32FE646D022775974F694A17E3FC61B341834`，
合计6,875,764,491 B；无失败。处置收据保留在`artifacts/common/capacity_disposal_receipts/`，
运行证据、重建输入和受保护的IP／MR／冷却场源保留。下文暖缓存预审是该次实际运行的历史条件，
当前重跑不能继续假定命中这两份缓存；冷构建必须按公共预算重新准入，不能降低容量承诺绕过。

2026-10-23又经公共owner精确部分退役4文件，共19,527,612,512 B：冷却failed运行042013的单份可重建
显示缓存12,061,500,000 B，MR旧私有回放192700的一份重复PA 5,967,264,224 B，以及旧局部准备134437的
两份重复粗场1,498,848,288 B。三份退役收据均验证通过，原科学manifest及failed状态不改，剩余证据分别
398,081,084／55,423,278／6,021,004,218 B。保留用户GUI包、真实日志／源和待用场；原267项输出的全量核验
是退役前证据，当前缺失显示缓存须用公共退役收据解释，不能再宣称旧全量磁盘清单仍完整。
本任务诊断scratch的10份临时文件247,796 B也已清除；准备器及实际控制已在新诊断run冻结，可重建。

后续两批owner部分退役又删除5份PA共14,182,800,880 B：140336的case01／02／03／06重复PA，及134437
未飞行failed case05的独有PA。原收据及manifest逐字保持；新编号收据核验通过，科学状态仍failed，
两run分别保留124,710,877 B／314文件及54,106,339 B／253文件，重建输入、日志、GUI和生产donor均保留。
追加退役机制的141项回归通过，规划不重读封存PA，链验证只核验一次当前剩余载荷。

六份已无当前消费者的缓存已另经原owner批准及公共maintenance精确退役，合计22,490,940,557 B：
四份旧多极杆basis、旧frontend317722及原始几何F41D。小型重建输入、实际GEM、清单和批准材料已在
`20261023_112032__analysis__python__legacy-cache-owner-retirement`封存，50项输出完整核验通过，
797,605 B／52文件为ready轻证据；公共处置无失败。9C45来源旧run_config漂移如实保留，
其实际重建所需GEM／resolved／numerics／code_inventory单独核验通过，不宣称原来源run仍完整有效。
缓存可按保留输入重建；旧frontend不等价于新零间隙场，F41D只为未Refine原始几何，均不授予新物理资格。

## 实际冻结工况预审

[三区功能工况](../../config/experiments/guide_oa_three_zone_functional.json)保持原身份
`20261021_190350__sim__simion__local-bare-guide-oa`的完整IP母群N=100、全部三区
几何／驱动、数值及detector-blind脉冲策略；新配方直接沿用原两实例位姿，机械间隙仍为1 mm。
无求解器预审确认frontend、guide、registration、numerics和pulse plan逐值相同，实际GEM字节相同。
导引端面为`(0,-68,32) mm`，OA外壁端面为`(0,-67,32) mm`，外法向相对。
配方中的位置／角度容差仅用于名义布局的浮点一致性检查，不是制造或物理接受度。

[运行预算](../../config/experiments/guide_oa_three_zone_functional_budget.json)明确绑定新workflow；
43,483,139节点、六模式的冷缓存节点载荷下限约8.00 GB。首次9 GiB承诺被实时容量台账拒绝，
未创建run或启动求解器。随后逐项核对实际GEM、PA+、原生可执行文件及全部五个构建器身份，
确认对应既有缓存key为`3CFD9E448429C40AA40EB5BB3FB32FE646D022775974F694A17E3FC61B341834`。
该工况预算恢复为原暖缓存承诺3,258,188,016 B，覆盖约3.13 GB节点载荷下限；没有调整全局容量水位。
执行仍由公共缓存消费边界核验完整代际库存，不能凭目录存在使用PA，也不能据此声称冷构建容量充分。
该预审没有启动求解器，也没有生成新owner下的成功飞行证据。

新owner首次实际运行`20261022_163725__sim__simion__local-bare-guide-oa`在求场阶段停止并封存
failed/full，完整manifest核验及容量封存已通过；未开始粒子飞行。适配器曾把已验证位姿重新导出为浮点，
使`0`与`0.0`等JSON表述改变了严格缓存身份，误入冷构建。现已删除这次多余转换，原声明位姿直接传给
原生投影，间隙复用装配器的解析值；没有加补偿变换、旧缓存别名或更改缓存校验规则。
新增冻结工况回归按实际序列化字段比较，修复后精确缓存键恢复为上述既有key。
停止产生的`B85A4AE846492218DD39951C4BCACEBA1EBF7D48594979A5F364626B40B5A368`未发布事务保留原始
失败证据；其私有构建载荷须沿缓存owner退役入口收尾，不直接删除或冒充已发布场源。

## 三区N=100迁移对照

新owner运行
[`20261022_165815__sim__simion__local-bare-guide-oa`](../../../../artifacts/projects/instrument_assembly/runs/20261022_165815__sim__simion__local-bare-guide-oa/summary.json)
已通过公开入口完成场缓存消费、孔贯通、held-OFF发现、完整母群引出、自动诊断和全新进程默认Fly回放。
与原工况`20261021_190350__sim__simion__local-bare-guide-oa`相比，唯一迁移因素为作者装配／运行结构；
完整母群、几何、场、驱动和数值设置保持原值，没有重新优化脉冲或筛掉损失粒子。

| 对照量 | 原运行 | 新owner运行 |
|---|---:|---:|
| 完整母群 | 100 | 100 |
| held-OFF规范事件行 | 137,928 | 137,928，逐ID逐值一致 |
| 引出规范事件行 | 61,150 | 61,150，逐ID逐值一致 |
| 无检测器脉冲时刻（μs） | 27.793500142888146 | 27.793500142888146 |
| 出口／损失 | 69／31 | 69／31 |
| 新进程默认回放 | 61,150行 | 61,150行，差异字段0 |

逐值比较只排除批次本地`ion`和原始日志定位字段`raw_line、raw_line_number、raw_log_path`，
其余CSV规范字段全部参与；原运行两份消费CSV分别核验其manifest记录，新运行完整manifest核验494项输出。
原生场复用上述`3CFD…1834`已发布代际，没有因迁移重建相同场。终态为success，容量owner已封存
ready，保留2,345,430,233 B；真实进程已结束，原运行与其他在途仿真未改写。

这证明该冻结三区局部功能工况迁移前后一致；未执行人工GUI验收，不证明MR接受度、整机分辨率、
碰撞资格或Formal性能。直属静态门禁95项通过。此前运行`20261022_164740__sim__simion__local-bare-guide-oa`
因执行上下文丢失中断，未复用其run ID；已沿公共入口封存interrupted并释放本次租约，保留失败证据。

## 局部前端执行与复核

从仓库根运行以下命令，替换显式路径；`RepoRoot`自动定位仓库，`Python`默认使用锁定的`.venv`：

```powershell
& integrations/workflows/local_frontend/execute.ps1 -Request "<request.json>" -ValidateOnly
& integrations/workflows/local_frontend/execute.ps1 -Request "<request.json>" -PrepareOnly -OutputDirectory "<managed-run>"
& integrations/workflows/local_frontend/execute.ps1 -Request "<request.json>" -ExecutionBudgetPath "<budget.json>" -SolverAuthorized
```

`ValidateOnly`不写运行产物。`PrepareOnly`要求公共run package已建立的目录，并从其`run_config.json`
读取run ID与project身份；它不能用任意空目录或改变已有owner。Python准备接口只有写output时才需要
`--run-id`；只校验请求不需要运行身份。原生执行始终创建新run，owner为`instrument_assembly`，
产物位于`artifacts/projects/instrument_assembly/runs/`；不改写原身份的运行。
`inputs/integration_identity.json`按schema 2记录owner、workflow与run ID，仅引用实际写出的composition plan；
配方和组件实例身份由该plan唯一拥有，不在多个JSON中平行维护。

科学request冻结完整源producer manifest／原始释放、提供者几何、电压、直接位姿及独立数值设置；
直属预算使用engineering-budget schema 2：`integration_id=instrument_assembly`、`workflow_id=local_frontend`，
不再用connection profile代指工作流；其余资源字段和`stage_limits.single_flight_transport`保持现有语义，
保留类别为`solver_review`。共享预算校验器也服务尚未迁移的成对链路，但直属入口不接受其schema 1。`-SolverAuthorized`会启动商业求解器，
须先有已审阅输入和该次科学运行授权。三区N=100已取得下述新owner局部运行证据，不能据此扩大资格范围。

裸导引请求当前只接受schema 3，`role=instrument_assembly_local_frontend_request`：引用完整父`composition_plan`
file record，默认full或显式`local_scope`。各实例的直接局部→装配位姿只来自父plan的嵌入recipe，
不接受顶层registration／connection或组件内transform；配方合同与检查入口见
[统一配方解析](../../README.md#配方解析)。准备先冻结并只读取`inputs/parent_composition_plan.json`，
再派生实际scope到`inputs/composition_plan.json`，选中的两个提供者接口、端面与法向逐值核对。
当前作者plan由165815已发布plan的原recipe／components重新编译，并重新核对当前提供者；
它不扩大已实现物理范围，也不代替真实联合飞行或新的物理资格。

`accelerator_component.variant_id` 选择 `two_zone` 或 `three_zone`；二区显式侧口由提供者
requirements schema 2 编译，三区使用完整 sectioned 几何 requirements schema 1。两者共用
`compile_frontend`、源物化、Program、场阶段和诊断入口，分别输出五／六模式模型和真实检查面。
作者必须给出实际几何、局部电极映射、ON 电压及零 OFF 策略，不能把旧整机八模式 family 当作裸导引三区。
准备只生成物理 cache 输入；执行发现真实 SIMION 身份后按公共机制求键，缓存命中必须核验完整库存。
单位响应参考电压由原生采样记录并归一化，不假定供应商 basis 文件本来就是 1 V。
合成前由公共 PA 输入入口一次创建每个响应的受保护短副本，三项工作场共享该组副本；供应商退出后
核验并清理。预算包含这组临时副本，不能只计算最终保留的 PA。run 自有的三项工作场在孔拓扑、
批次飞行及默认回放期间持有公共禁止写入／删除句柄，不按粒子批复制。
响应场路径使用实际 Workbench 载体的 `instance.pa.path` 所在目录；`filename` 仅用于冻结的 basename
核验，不作为完整路径，也不回退到当前工作目录。缺目录或载体文件名不符时在生成离子前拒绝。
局部动态场回调先用实际 carrier 的 `wb_to_pa_coords` 和 `pa:inside_vc` 检查查询点；PA 外只跳过
响应查询，不钳制坐标、不扩展或补造场，也不修改梯度或 `ion_splat`。积分试探点不等同已接受轨迹点，
所以首次域外查询只记为 `FIELD_QUERY_OUTSIDE` 的 query-only 诊断；最终损失仍由原生终态与实际状态记录。
依据为 SIMION 2020 本机 `docs/simion.chm` 的 `lua_simion.pas.html`（`inside_vc`／`field_vc`）、
`lua_simion.wb.html`（`wb_to_pa_coords`）及官方 `examples/dielectric/resistive_2dp.lua:26–28`
的“坐标转换→域内检查→场查询”顺序（2026-10-21核对）；不采用该示例的额外单位换算。
局部 Program 使用官方 `sim_segment_global=1` 保留离开 PA 后的实际 `terminate` 状态；
`tstep_adjust` 和 `other_actions` 在 `ion_instance=0` 时立即返回，场回调保留域内检查，
源初始化仍要求位于真实 carrier 内。PA 外终态可能位于 Workbench 边界，不能称为首次离开 PA 的位置。
离开 PA 到真实终态之间不继续生成固定时刻快照；这段仍存活但无原生共享观测的区间保留为
`numerical_unsupported`，须结合最后域内状态、query-only 记录和真实终态解释，不补造域外轨迹。
依据为同一 CHM 的 `workbench_program_extensions.html`；该开关作用于整 Program，
不存在本实现另行假定的逐回调注册接口。出口同时记录原生步前／步后及插值状态，
覆盖 `ion_splat` 前的原生值单独保存为非 TRACE 诊断，不能据此替代实际终态。
科学出口观察面与数值停止面分开：负 z 出口仍为提供者声明的实际平面，停止面由该平面与 PA 下游
边界的中点派生，必须严格处于既有 PA 留白内。出口穿面只记录一次，继续到停止面才请求结束，
避免在穿面回调立即停止时，SIMION 返回的前一步终态早于穿面插值。该延迟不增加电极或改变场；
出口相空间和到达时间始终取科学观察面，数值停止面不能解释为器件出口或焦面。
出口之后的步长另受四分之一留白长度与当前轴向速度限制；该约束不影响出口之前的积分，
也不是空间判定容差。停止判断在本步轨迹／共享时刻输出之前执行，真实终态仍由 `terminate` 记录。

源先使用 IP 提供者声明的 source→guide 映射，再消费配方中的唯一 guide→assembly 位姿，保持全部粒子与出生时钟。
FLY2 的 TOB=0 是原生局部启动时钟；Program 必须按 `source_identity.native_clock_projection` 从冻结表恢复绝对 instrument time。
真实慢轴为 +y，引出为 -z；`observer_to_mr` 是单位阵。孔拓扑参数使用真实 `normal_axis`、壁两面、
世界中心及两横向尺寸，schema 3 的离散警告不允许自动放大孔或移动边界。

执行依次冻结依赖／输入、建立或复用场、核验响应与孔贯通、held-OFF 实际占据发现、无检测器信息的
脉冲选择、完整母群引出和自动诊断；首批自然结束后由公共调度器重规划后续并发。
SIMION 的 `--default-num-particles` 仅预分配 ion-list 容量，沿用已有运行器的 `max(100, batch_count)`；
实际 FLY2 仍严格保留调度批次的粒子，例如首批 10 个和后续剩余 90 个，不补齐物理粒子。
共有时刻由冻结的全飞行期限、出生时间、导引／捕获／脉冲标记和提供者理想出射估计派生，理想时间只决定显示采样，
不能代替实际出口事件。真实孔前后、栅面／三区 intermediate2、出口及所有终态必须独立记录；
零出口仍作为完整母群负结果发布，不以筛选或伪造空 Fly 掩盖损失。
自动诊断同时输出各检查面的时间标准差和完整出口群相对平均到达时刻的经验累积分布；各检查面
使用自身到达群，不能把筛选后的展宽变化直接解释为无损时间聚焦。
共享时刻采用与分析器一致的 binary64 32 ULP 判据；提前且超出该范围的状态不会消耗待采样时刻，
下一原生步仍受该时刻限步。原生实际时间和请求时间分别保留，无法支持的记录继续标为 unsupported，
不补造状态，也不计为额外损失。空间图最多展示五个时刻：存在全母群终态时刻时，从有有效存活样点的
已记录时刻中均匀按索引选最多四个，再保留晚于最后活跃／缺测时刻的首个全母群终态；否则最多选五个
活跃时刻。未出生或缺测不能作为全终态。绘图按已核验样点的 `requested_time_us` 分组，实际时钟和
位置不变，图中人数仍必须与 census 严格一致。展示子集不能代替完整时序 CSV。

全量可加载 case 在同一次执行中组装。Program 在 load／initialize_run 设置显式 Q；轨迹保留由原生CLI／IOB设置控制，
随后自动在新进程中加载保存的 IOB 执行默认 Fly，不加 Program、Q、粒子或脉冲覆盖，再与调度飞行
逐粒子对照。原始日志、所有损失及差异均保留；默认回放未通过时不能发布“用户直接 Fly 等价”。
这项无 GUI 的默认一致性门禁不替代用户 GUI 验收，也不授予 MR 接受度或分辨率资格。
原身份的局部验证记录见[旧链退役历史](../../rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/history/20261024__legacy-family-retirement.md)；
当前状态以本页对应工作流为准。
用户加载同次成功 run 下的 `simion/extraction/gui_full_population/local.iob` 后即可 Fly；需保留整个
run 的相对目录和 PA 文件，不能只复制 IOB。检查面诊断位于 `results/local_frontend/extraction/`：
`checkpoint_evolution.png` 汇总角分散、束宽和穿面到达时间，`shared_time_distributions.png` 显示
共同绝对时刻的空间分布，`all_losses.csv` 与原始日志保留全部损失。历史 run 如需修正诊断，建立新分析
run 并引用原数据，不能改写已验证的 IOB／Program 或旧证据；具体恢复图入口由集成状态页指定。
