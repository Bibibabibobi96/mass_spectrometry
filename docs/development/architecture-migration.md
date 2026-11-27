# 架构迁移执行记录

本页是架构迁移的唯一进度入口；最新接续见[当前批次 C 检查点](#当前批次-c-检查点)。批次 A/B 完成不等于全仓迁移。输入为用户提供的
`ms_agent_execution_20261126` 执行包（start_agent、review_resolutions、implementation_plan、review_decisions）。
原评阅 145 同意、20 修改、2 不同意、29 处具体意见保持原意；技术实施选择不回写为原表批准。

## 当前批次 C 检查点

C 已按用户 2026-11-27 指令实际启动；用户随后更新整个执行包并清除原Goal，现已用新版`goal_prompt_C.md`原文重新设置同一C任务Goal，绑定完整`implementation_plan_C.md`和新增`architecture_convergence_C.md`。当前合同为C-r2、C0–C7/CA01–CA19。追加决定`user_decisions_C.md`（D-C01–04）优先于冻结附件旧建议；用户本会话的C0“报告残差即可，不设置阈值”决定继续优先。A/B正文保留为当时执行记录；本包独立验收对B的结论是带整改项接收，不能沿用下文旧交付的无条件BA闭合措辞。

- 开工 HEAD 与包审计相同：`78144e456f6141374853233e958b2b91723ea54f`；B代码`90d6d5e8`。分支`task/architecture-migration-20261126`跟踪同名origin任务分支，远端为Bibibabibobi96/mass_spectrometry。无审计后代码增量，不reset；21个已有tracked M实际diff为空，原未跟踪artifacts保留。
- Agent 0集成/共享合同/命名/迁移页/Git；Agent 1 C0-01真实仪器V/E；Agent 2 particle_release与三类Species/参考冷读；Agent 3 C0-02/03；Agent 4 C0-04；Agent 5气体冲突/唯一数据导出；Agent 6不可达旧生产体退役。共享文件单owner，Git串行。C0-02/03闭合前不扩大native并发。
- C0正在实施；两个原存储probe只作旧缺陷证据，新复现另存外部C证据根，不覆盖recorded结果。B0四项不重做。真实点验只复用已求OFF/ON资产，不重算整场、不改pulse/birth追命中。
- 气体统一允许有依据的科学输入修正，独立版本/缓存影响与纯改名分开；IP proxy不能证明独立物种，HS1示例截面不冒充N2标定。正/负离子与电子身份独立，不靠电荷符号或小质量猜类型。
- C0-02/03/04已实修并定向验证；C0-01按用户后续“报告残差即可，不设置阈值”决定交付实测，不授场精度资格。其余CA继续按实际实施/证据闭合，尚不称C全部完成。未启动M06–M08或大型研究，不合并主线。

### C-r2 更新接续与实际工作区

已重读更新后的所有根文档、三份冻结审计、probe源码及证据说明；全部26文件只读加载，JSON/日志程序化核对，manifest列出的25件bytes/SHA均相符。外部读取凭据为`C:/Users/Liao/msplatform-artifacts/architecture-c-20261127/c-r2-package-reread.json`；Goal SHA `df877b996e68660d82d0b531975bcaeb1833b562046b2075cd5f6633f59df7e2`、主计划SHA `dd9a131f82571265bbb6eabe3fec281c58cc64d2d744e7f2c366bb37aee782aa`、新退出细则SHA `27ae4fe2220732d854be5d08a40919fb5e4ede0e8a50434abaaa322cfe056f24`。旧175次调用/22skip仍只属于B独立验收；两个旧probe未覆盖、未当修复PASS、未原地执行。

此次更新时HEAD为已普通push的`095f9a05`，此前C提交依次为`1b77f612`（guard后死体）、`6ba108fd`（C0软件）、`a3681dfc`（两失效PS退出）、`b407afcf`（修正提交边界）、`095f9a05`（host完成验证归owner及C0点验记录）。`a3681dfc`暂存时误夹带在途sweep的两处测试路径，`b407afcf`已恢复已提交旧路径；工作树新版路径完整保留供其完整主题提交，不reset或覆盖在途实现。C-r2生效后这些早期拒绝壳/旧owner过渡保护均不得称最终退役。

当前在途代码包括：particle_release/三类Species及参考schema3、native schema2显式registry；唯一电子/N2/HS1/SDS数据与GasEnvironment/IP消费者；project/request/profile/plan v2退出总等级；Store原位native stage与真实进程保护；recorded v13及IP/MR旧支路收口；诊断source认证拆入execution。各自已有定向软件证据，但尚无C最终普通发行/Repository/新整合native证据，不能写全C验收通过。原有研究资产、冻结历史及其他工作全部保留。

### C-r2 旧职责接管与删除状态（滚动对账）

| 旧位置/表面与实际能力 | 唯一目标职责/实际新入口 | 当前切换与已删除项 | 仍有引用及理由/退出条件 | 证据边界与状态 |
|---|---|---|---|---|
| ion_release包/函数/role/schema/资源；源采样与身份 | particle_release、contracts.species、规范结果reader | 物理包与tests已移；外部完整imports、精确动作符号/NAME token、作者spec及schema/资源在途切换；无旧活动包别名 | 精确schema1 receipt/原CSV只读decoder，不能调用旧sampler；部分当前fixture/冻结资源仍待同步 | 三类非零E独立解析/冷读及源定向已测；双发行尚未测，未闭合 |
| single_reflection_flight总包；recorded源认证/追踪与后端序列化 | particle_release源、Recipe冻结、backend适配、公共native_tracing | v13显式kind仅过渡；Agent4开始直接接公共Recipe，不调用旧包 | prepare/recorded_birth及registry/PS仍活，成熟源码须拆给真实owner后整包/脚本退出 | v13与旧版本软件测试不是CA19；未闭合 |
| prepared_joint/FullJoint/accelerator_interface；准备、局部源、连续演化/分析 | Assembly/场准备、particle_release局部源、tracing、results/analysis | 跨组件终态重释支路已在途删除/拒绝；已有原出生IP/MR后端为实际复用基础 | 旧PS/profile、准备/研究/import仍活；不以guard、prepare-only或历史标签豁免 | 公共Recipe观察/HS1/原出生接线正在实做，未闭合 |
| oa_candidate/oa_formal；局部whole-Fly、响应/补偿、验证/发布/恢复 | OA领域算法、公共Study/tracing、analysis、Store/execution | grade v2合同在途完成；diagnostic source认证已拆到execution.diagnostic_inputs，两个PS直接使用 | 其余旧controller、runtime/validator/publisher、命令/profile仍活；Agent1/6分职责拆并删除，不能整体换名 | 旧Verify/Publish/Recover软件通过仅表能力保持，不是新owner接管；未闭合 |
| execution旧native容量/产物管理及source桥；登记/发布/回收/恢复 | ArtifactStore与保留的通用execution进程/host机制 | 新scope稳定路径原位stage、claim/binding/真实短OS进程；历史sourceguard已移除旧ledger调用，纯原manifest及OS文件句柄只读保护 | 默认旧owner/ledger/retention/恢复仍活；21生产模块调用需切换后删管理体，只保留精确历史文件读取 | 基础原位crash续发已测，真实native产品闭包/全部caller未整合；未闭合 |
| tests中两坏producer与有用场诊断sweep | 公共Study；analysis诊断+execution认证/当前Store | 两坏PS已删；有用sweep/旧矩阵共用新source认证，不复制第二算法 | normal native仍待当前Store接线、旧runtime私有引用必须退出；不能为拒绝测试复活已删脚本 | AnalyzeOnly正反/0hit null软件证据已测，normal/native未测；未闭合 |

表中目标不是一对一新包装；所有CLI/API、schema/registry/profile、动态资源/生成器、安装包、测试与当前文档均须同步。精确历史/第三方例外只解释/返回数据，不得启动旧producer、调度或旧登记/发布/恢复/GC。当前任何未解释的旧活动路径均为未通过CA19；上述在途表不代替实际整改。

### C3 原位 native stage 与历史只读保护基础

`ArtifactStore.inplace_asset`在最终稳定asset路径登记publishing并持writer/claim，原生manifest内绝对路径不因发布重命名失效。现有`execution.owner.managed_native_store`作用域将每个stage claim与父run原claim/reservation一起交既有进程binding；不为此新建host调度或第二GC。Store scope下RunSession不取得旧容量lease，PowerShell仍逐条独立核验immutable_input_records并持OS不可改/删句柄。真实落盘后沿C0同一account回调减少remaining；成功/失败分别seal，未知writer保持publishing且不可当成功缓存。

失联恢复只通过同一execution owner验证原request/config/terminal/完成回执与binding，取得writer OS锁后重放Store原子终态；成功不降级、真实失败保留原因并非缓存，两次无新增副作用。仅父锁释放但无绑定/原生完成事实不允许猜停止。已删除任意reason直接标失败的试制恢复入口，避免成功terminal到seal之间崩溃后回退。

历史`native_source_guard`不再调用`capacity_decision_lock`/`resolve_consumed_run_capacity_owner`，不创建历史根锁；先持原manifest的精确OS句柄，再逐config/product原record取得并验证句柄，最后验证terminal/product。缺件、篡改或删除竞争失败关闭，读取前后原目录字节/清单不变。Store产品使用唯一claim；明确`ground_source_reference`外借payload须逐路径/bytes/SHA等于已保护来源，未知外借闭包拒绝。

实际软件验证：Store+历史sourceguard完整29 PASS/7.885s；必要成功/失败terminal到seal崩溃与活/未知writer4 PASS/2.546s（有重复方法，不另当全新覆盖）；真实Windows短child+OS输入不可写保护PASS/10.272s，真实invalid-image未启动→failed证据PASS/6.483s；四项stage/source组合PASS/17.583s；显式旧源借用保护PASS/1.159s。命令结果来自本轮工具记录，没有虚构独立stdout日志。Ruff/diff PASS；未新增商业原生运行。默认旧owner、旧retention执行及全部生产caller仍待接管/删除，C3/CA19未完成；此基础提交不是最终退役结论。

### C1 唯一物性数据与电子质量修正基础

数据唯一权威为`physics/data/{reference,electron,nitrogen,hs1_example_assumption,sds_model}.json`，中性导出在`contracts.particle_physics/gas_species/gas_environment`，`physics`公开同一对象；旧`physics/reference.py`实际删除，无同义species壳。N₂采用NIST WebBook相对分子质量28.0134，kg/mol由现有u和精确Avogadro常量推导。IP proxy指压力场，归同一`n2`身份；0.370/0.364 nm均实际用于有效气体直径近似，不能以COMSOL/SDS名字不同豁免，统一选NIST-hosted来源的0.364 nm。旧0.370→0.364的Kn/MFP比例变化为(0.370/0.364)^2，属授权科学输入变化，须数据版本/SHA改变缓存；气体真实消费者仍逐个接线，尚不称全部统一已验。

HS1的2.27e-18 m²保留为原SIMION helium/~200u例子的未标定粒子对假设，不再命名为N₂固有截面；不是N₂/524u或电子碰撞资格。电子kg值沿用CODATA2022，u由仓库冻结2018u推导，0.0005485799090441→0.0005485799098091511 u；电子枪作者、profile和resolved实际修正并更新来源版本，原run不改。独立科学输入改变与纯软件改名分别记录。完整来源notes外部`gas-unification/source-notes-working.md`，机器JSON含直接来源与适用限定，最近电子枪PROJECT写入该修正。

新数据加载必须闭合真实冻结运行：`execution.inputs.enumerate_python_sources`静态读取各模块literal `FROZEN_PACKAGE_RESOURCES`，将其唯一JSON加入原source closure，不执行模块、不建第二数据表；冷隔离导入、缺件与篡改负例已覆盖。reference数据SHA由同次捕获bytes导出`REFERENCE_DATASET_SHA256`，不改B的CONSTANTS序列化/版本；后续消费者须校冻结record与实际导入数据身份，不能把第二次读取的新源与旧内存值混绑。IP/双锥环境与native views不在此基础验收内；当前WIP尚未最终安装/原生验证。 本单元按独立暂存源码树`756722d39dc0a397d384be8dc055f302f2968de1`验证，实际从仓库外源码快照运行：物性/数据/冻结/电子枪48 PASS（35.091s），注册表/科学边界35 PASS（14.815s），未夹带C4 schema2与组件命名WIP；这是源码测试而非普通发行安装。

### C-r2 OA 跨求解器历史验证器实际退出

原`workflows/oa_formal/verify_formal_validation.py`已删除，不保留CLI/转发。精确v1–v5历史格式由`results.cross_solver_history.read_cross_solver_record(config_path, artifact_root)`校验原输入/来源身份；逐字段metric一致性比较真实拆入`analysis.cross_solver_validation.validate_cross_solver_metrics`。既有`verify_reference_analysis.ps1`直接调用新reader，结果仅证明历史记录一致，不重新授Candidate/Formal总等级或仪器误差资格。未知schema失败关闭，原1e-10/1e-12只用于记录内metric表示一致，未改变C0不设阈值决定。

Agent1定向新旧消费者16 PASS（11.302s），最后未知版本拒绝补验3 PASS；新模块无producer/owner调度。安装副本检查不等于最终普通wheel/sdist；旧OA其他publisher、recovery、补偿与大型资产暂未因此被宣称退役。新增依赖绑定复用现有machine-contract职责，不增另一阶段。

`78144e45→00c6d23c`规范CLOC 2.10已完成：total code 618524→618732（+208），production 303823→303458（-365），tests 314701→315274（+573），unclassified 0；完整各语言files/blank/comment/code、功能表和过滤口径在外部`c3-store-cloc-C-locale.log`。首轮Perl因继承的C.UTF-8 locale产生warning而失败，未算PASS；第二次仅对子进程设C locale重跑相同口径PASS，未改过滤或实现。

### C-r2 组件规范身份与公共运行职责拆分（WORKTREE）

规范命名主题采用`2823fa42`的独立源码快照，仅抽取命名/路径/安装声明/生成registry及历史身份必要变更；未把工作区的气体science v2、粒子schema3、旧工作流分解和各Agent其它在途补丁混入。实际原样移动3个component与其component/assembly测试共8目录；当前作者请求另存`ip_mr_current_requests.json`，原LP60历史夹具不改。独立快照48项合同初次47 PASS/1 FAIL：漏更新包内new-run identity派生JSON；用现有生成函数更新后该唯一失败方法PASS（0.028s），不改物理校验；新增IP历史选择方法PASS（0.015s），默认当前continuation不借用旧身份、显式history只读原字节。完整普通安装留到最终必要节点，此命名单元不称CA19退休完成。 随后Changed selector两方法中一项暴露已提交C1删除`physics/reference.py`后遗留的过期测试路径；改为实际中性常量owner并补同一catalog精确依赖后，两项针对性检查PASS（2.377s），未恢复旧wrapper。独立源码快照文档gate初次因无Git metadata无法枚举，补临时验证库metadata/longpaths后StructureOnly PASS（322 files，0 errors）；该临时库不属于任务tracking分支、无remote。

三组件与对应测试目录已实际迁到`multi_reflection_tof`、`ion_processor`、`dual_cone_tandem_quadrupole`；当前源码、跨语言资源、配置、机器registry/profile、打包和文档的完整旧ID按精确映射切换。原生模型的实际双压力区、平行镜双条带等结构未删除或捏造为新variant。3份原`00c6d23c`之前的版本化project描述符以原字节冻结到`docs/history/projects/<规范名>/retired_projects/<原ID>/config/project.json`，当前描述符严格绑定原commit/bytes/SHA；原旧history与研究资产不搬动。旧身份仅可历史读取，不注册能力、不作为新run别名。历史README仅修可变导航链接，冻结报告/manifest/old_witness/原LP60请求字节未改。外部精确改动备份与映射为`component-names/mapping.json`。

公共`recipes.__init__`现在独占`SimulationRecipe/load_recipe/validate_recipe/assembly_name`与一次外部TOML读取；`recipes.reference`只负责编译/核验参考科学输入，不再兼任native总路由。公共`workflows.tracing.run_recipe/inspect_results`接同一已捕获author bytes，按实际schema选择native或reference实现；`reference_tracing.run_loaded_recipe`只保参考缓存/数值工作，跨backend批结果合并体实际移到已有`results.model.merge_trace_batches`。CLI及当前调用方同步，不留旧通用函数转发壳。

真实验证：project registry生成成功，8个当前项目；registry/历史身份/科学边界联合47 PASS（17.183s），新增3组件当前发现/旧包不可import/旧身份新run拒绝同一方法PASS（3.623s）；公共入口拆分后的参考作者/参考运行/三类Species/科学边界32 PASS（22.104s），含单次author读取后外部改变、独立解析数值与冷读既有反例。文档StructureOnly首次发现9个导航断链，修可变索引后PASS（322 current files，0 errors）；失败不改写为首次通过。Ruff/diff-check PASS。普通wheel/sdist和新组合native尚未执行；这些WORKTREE结果不是CA19完成。共同冻结后再进行必要发行和Repository，避免每阶段重跑。

C3基础已提交并普通push`00c6d23c`（后续OA reader退出`a7c1e018`、唯一物性/电子修正基础`2823fa42`也均已推同任务分支）；其最终复验Store/历史guard29 PASS（8.454s）、终态seal成功/失败恢复2 PASS（1.745s），与之前方法有重复。其后新增formal v1精确OS只读保护覆盖材料化复制，软件fixture通过；仍未把真实大PA重新hash或启动商业native。Agent1继续OA数值/历史reader和response编译实际拆分，Agent2补粒子自有名/发行probe，Agent3迁旧发布恢复能力到Store，Agent4整合recorded/IPMR/diagnostic公共链，Agent5双锥唯一环境消费者，Agent6历史mass分析与旧执行退役；以上各单元未完成不得等同全C完成。

### 2b82237e 后的恢复接续（在途，不是最终交付）

当前已提交/普通push HEAD=`2b82237e492fbd36fee34a5444f4609282778b72`，local/remote同一任务分支已核对；Git index已清空，全部其余工作区改动保留。规范命名主题以独立暂存源码快照验证，未夹带科学输入/公共schema/Store下一单元。`78144e45→2b82237e`规范CLOC 2.10：total code 618524→622121（+3597），production 303823→303844（+21），tests 314701→318277（+3576），unclassified=0；完整各语言files/blank/comment/code与过滤口径见外部`canonical-components-cloc.log`。测试口径包括新增当前作者JSON及原历史夹具，不用排除静态夹具掩盖增长。

- Agent 0：已完成新版26文件只读核对与C-r2唯一Goal；当前集成、Git与catalog/唯一迁移页继续由0负责。公共Recipe/参考运行实拆32项与native分派7项通过；Agent2独立公共入口检查已增加旧公共名不可导入与当前包资源一致性反例。最终普通wheel/sdist、完整必要Repository及同码native尚未开始，不授CA18/19完成。
- Agent 1：纯反射器拟合/比较归analysis，历史跨solver reader已提交；当前`reflectron_response_binding`、独立response生产/审计、`sample_response_axis`与`axis_response_samples`、新Study作者/已发布run比较在途。实际tiny SIMION为11×11×1、两电极、一次Refine后逐个native_copy导出独立PA，冷读242节点最大差0 V/金属mask差0，证据`reflectron-standalone-probe/`；Store父run succeeded、4绑定complete/exit0/正式host release、reservations/claims/writers均0。它不证明OA仪器场/补偿效果。19响应的原owner+inert worker定向151.663s PASS；最初未冻结完整field-action失败原因仍未单独定位。新API多组23项左右定向存在重复，以外部逐命令日志为准；真实新axis stage/新model完整FieldBundle/补偿Fly未验。前端仍依赖旧PA cache，是实际阻断；旧controller/CLI不能据纯规划删除，0/1 hit比较已明确unavailable与null gain。
- Agent 2：particle_release/Species/安装probe继续；IP/MR连接、几何与历史读取实拆。首次将IP凸体算法放assembly导致反向依赖FAIL，已按真实职责分为`assembly.geometry_primitives`、`components.ion_processor.assembly_geometry`、`components.multi_reflection_tof.interface_clearance`及SIMION IO，错误assembly模块删除；边界16 PASS、几何/局部研究+namespace41 PASS。三旧profile已移出registry，但`prepared_joint.source/trial/flight`与两PS、downstream Prepared iteration仍活，必须接显式原出生单MR后实际删除。单MR当前只有真实Assembly+显式birth与neutral SI采集fixture，未有受认证场/真实轨迹；旧OA混species伪realization测试已FAIL，须两明确species批次保原总母群，不能弱化Species合同。
- Agent 3：当前`standalone_native_store`复用既有Store run/writer/预算/binding/发布，已接COMSOL geometry/EI/Wehnelt model、SIMION geometry和CAD的显式Store/父scope准入；无Store不静默回退。COMSOL prepared/field小manifest与原geometry/model完整闭包递归持权，缺件不得浅guard或误cache。failed MPH恢复保持failed源状态，不复制大MPH、不伪ready；稳定源码下真实短inert进程失败→新run恢复→冷读/错state/活绑定/缺completion/源篡改定向37.030s PASS，sourceguard8项PASS。多数source型caller及无Store旧分支仍待迁；原default capacity/retention/cache管理体尚未全删，C3/CA19未完成。握手前错误现在保留原stderr/cause与未绑定语义，未把未验证receipt当停止证明。
- Agent 4：公共recorded出生已接SIMION native与原有COMSOL→SIMION scalar分支，严格重构冻结cohort并比较；Store字段引用/缺源局部miss及气体数据SHA进入trace key。IPMR285.389s inert field/preflight发生在最后gas键修正前，只作链定位；当前定向25项及gas/cache小检查通过，不混称同码全链。诊断单case与多case已进同公共Recipe：每case独立SI子目录，collection重读核原cohort/species/frame/clock，不合并重复particle_id；真实Store/inert叶子正反通过，尚无Fly。scalar renderer曾先替理想场后被完整采样值覆盖，已改先采样再替换，真实Lua四/五槽数值开关4例通过；此前字符串测试不作为物理生效证据。单MR/双锥dispatch仍与2/5协作，normal sweep PS未退役。
- Agent 5：IP唯一作者→typed环境→native view已核实际Lua回调；双锥统一environment、N₂/transport/constants数据SHA与CFD/SDS views，正离子SDS范围显式拒负离子/电子，125/0 Pa prototype能力保留。新增300K N₂输运数据保原数值/常数近似，其他温度不授资格；baseline/environment按捕获bytes解析/归档，源后变不偷换本run。COMSOL完整8项、共享source记录/owner7项、CFD→SDS惰性消费等相称软件通过；旧历史schema1只读不改字节。两套重复transport测试已收组件唯一测试+test_support，公开Recipe仅pure helper开始，真实CFD→GasEnvironment/源与五资源冻结/Store stage/SI尚未闭合；不冒称旧workflow已被替代，公共预检仍须失败关闭。
- Agent 6：新`historical_mass_analysis`、analysis/results/中性signed charge与execution worker已接Store；旧mass study/worker/PS/SIMION fly/COMSOL retrace及MATLAB资源已删除，旧专属测试迁实际新边界。112.742s真实深路径observer曾PASS，之后worker版本来源、immutable输入和Store父生命周期已改，最终安装必须重验。历史sweep新`historical_field_diagnostic.analyze_recorded_field_sweep`只读成功封存源，精确OS guard/冻结manifest/config/共享ION/log，发布冷读/0hit null/篡改/预算失败相称测试通过；failed/interrupted明确拒绝并保留源。旧PS AnalyzeOnly分支真删，normal仍由4迁。mass与sweep实际PASS/FAIL/中止/重复及未验见外部`retirement/historical-*-software-evidence.json`，不是最终两发行证明。6现在独占frontend `field_worker/pa_family_cache/field_audit/capacity_maintenance`迁现有Store cache，与1/3协调；旧legacy缓存/容量支路阻断真实field producer，不能加字段骗过门禁。

后续优先：Store前端PA缓存与COMSOL恢复/剩余caller→单MR真实原出生与旧重释控制删除→双锥公共数据/结果/owner→多case真实native与normal PS退出→补偿新FieldBundle实际生产与旧controller退出。新公共安装probe已把历史mass/sweep、三类粒子、旧模块缺席与资源边界纳同一wheel/sdist两臂；目前只语法/共享import/摘取软件段通过，尚未重建发行。所有代码/fixture在测试开始前冻结，执行中源码有变的长测只作定位，不重复无关全矩阵。最终CA01–CA19、真实总调用/重复/skip/wall及完整CLOC仍待同码验收；当前任何一项未完不标Goal complete。

### C3 Store 身份、剩余预算与历史发布单元

在`e61322dd`之后完成本单元，未夹带各链在途科学/schema改动。`execution.owner.standalone_native_store`统一父run/writer/reservation/发布，`run_managed_stage`复用同一协议；`store_growth_accountant`按实际解析路径高水位去重，RunSession在进程完成/失败及回执落盘边界扣减remaining。未知未来预算不归零，不新增实时扫描平台；原异常优先于清理/记账二次异常。Store的`asset_status`提供只读状态，native stage原run ID跨并发、失败和GC仍不可重用。旧数据库只在首次新native写入时持既有GC/原writer锁升级，冲突回滚并保留原证据；未留下证据的旧已删身份不能凭空恢复。

`guard_formal_v1`仅精确读取既有v1角色/bytes/SHA并持OS只读句柄；`guard_failed_store_evidence`核failed状态、原完成/进程/host释放证据，不提升为ready。`publish_historical_release_evidence`/`read_historical_release_evidence`由唯一execution owner发布小引用并在冷读时重新取得源保护，格式decoder归`results.release_evidence`。递归来源的真实Store资产闭包进入required refs；未被选择的历史大载荷不全量复制或重新读取。这里不新增全仓等级，也不恢复旧producer。

Agent0从暂存树`cbd0bb74ee48e11beb9af0939bc1863efa7ce432`导出离仓源码快照，运行`python -m unittest tests.contracts.test_artifact_store tests.contracts.test_store_run_identity tests.contracts.test_release_evidence tests.execution.test_native_source_guard -q`：39 PASS、0 skip、9.997s；本单元全部Python Ruff PASS。这是源码/真实OS文件锁合同，不是普通wheel安装或商业求解。Agent3另有短Python子进程的别名去重、两个worker完成/失败、其他reservation不变、父run失败和standalone成功/失败/中断证据，见外部逐命令记录；不把这些重复覆盖再计作独立完整矩阵。

尚未退休的默认旧capacity/retention/cache分支及其调用仍为C3/CA19欠项；Agent6正迁operating/paired/OA缓存，Agent3继续合法COMSOL源消费者，Agent1/4闭合新补偿公开链。新补偿field是可回收缓存，GC后只要求原required源与最终自含SI/summary仍可读；不能以测试要求永久pin所有中间场。最终同码双发行、Repository、native和CLOC总对账仍待收敛。

本单元最终代码`71e7ae1f8e778ea8dbc1fba5a83c45f4f2e9f56f`已普通push，local/tracking HEAD相同。首次commit hook指出新身份测试的短子进程缺显式cwd，未创建提交；补cwd后该4项复验PASS（0.966s）、development standard PASS再提交。文档工作区首轮5个断锚失败由当前ASSEMBLY职责导航修复后StructureOnly PASS（322 current files、0 error）；独立源码文档检查两次启动分别缺参数文件/缺Git库存，不能计通过。`78144e45→71e7ae1f`规范CLOC 2.10 PASS：total code 618524→623232（+4708）、production 303823→304390（+567）、tests 314701→318842（+4141）、unclassified=0；完整语言files/blank/comment/code、功能表和固定过滤在外部`store-owner-core-cloc.log`，未混入在途工作树。

Agent0已补现有catalog中的Store owner/identity/accounting/release与公共CLI/Recipe实际依赖，并修正几何职责拆分后的路径；定向选测正反例与既有reference选测2 PASS（3.616s），无重复module、无关peak_metrics不触发新增覆盖，Ruff PASS。该catalog仍随旧链退役继续更新，未将Changed空范围或过期计划当最终Repository。

### OA 工程派生核验与旧等级授权退出（WORKTREE）

Agent0核对剩余`oa_formal`两叶职责：`verify_geometry_derivation`的实际耦合公式/工程舍入校验迁入`components.single_reflection_oa_tof.geometry_derivation.verify_geometry_derivation(contract)`，返回核验数值，不再以Formal workflow或另CLI拥有科学算法。既有`verify_geometry_contract.ps1`直接调用该纯API，原几何、电压、能量与工程位数一致性条件原样保留，不是新增仪器误差预算。旧`prepare_formal_promotion`仅由两项旧测试调用，生成Candidate/Formal自授权事务、没有实际原生生产消费者，按C-r2退出总等级决定实际删除，未把它包装成新权限入口；这两项旧等级专属测试同步删除，其他科学设计/路由断言保留。

新组件3项正反例PASS（0.025s）：当前baseline通过且输入不变、几何/电压/能量metadata冲突拒绝、两旧叶模块缺席；既有candidate_design剩余22项PASS（5.984s），Ruff与PS parser PASS，无求解器。`oa_formal`其余staging/publisher删除与当前reader/materialization仍在其它待整合单元，暂未将整个包标已退役；最终发行还需断言两旧模块缺席及新科学入口确实来自安装包。

本单元最终代码`6a597017`已普通push；独立暂存树`ff859b6f3264c6f8cee55a5b0a044f33a569e2e8`离仓源码25项PASS（5.821s），不依赖在途新schema/新producer。迁移后的PS调用保持既有入口，无另建CLI。Agent1继续同步最近OA正文，完整最终发行与跨链验收仍待共同冻结。

### 历史质量谱职责接管（WORKTREE）

历史v1源选择、completion/原母群/ID/原geometry认证归`results.historical_mass_spectrum`；校准、峰形/传输统计与绘图完整归已有`analysis.mass_spectrum`，不在reader中隐藏分析执行体。`execution.historical_mass_spectrum_worker`只执行已冻结分析源码/geometry、核输入与原始source哈希和实际Python版本；`workflows.historical_mass_analysis.analyze_recorded_mass_spectrum`通过现有RunSession/Store/OS source guard编排。没有retrace/Fly或旧容量owner调用，原大型MPH/PA与历史bytes不改。signed integer charge词法解析实移中性`contracts.particle_identity`，旧ION文件reader直接复用同一实现，不因历史ion字段推断electron。

Agent0发现reader仍有分析/绘图主体后按上述实际职责再次拆分；未改公式/容差。定向11项PASS（7.105s），覆盖独立解析校准、原polyfit结果、退化/非法输入、完整分析输出、显式geometry、超母群/未知物种、源缺件/篡改/失败/非终态、冻结源码/geometry身份和failed parent不发布成功；Ruff PASS。原112.742s深路径结果早于worker relocation等后续变化，只作历史定位；最终两发行节点须实际重验当前深路径，不能沿用旧结果标最终PASS。

本单元提交`cfd6b848`已普通push。独立暂存树`210f2a8e7aafe512c099349d90363d1557a1198c`离仓源码15项PASS（8.781s），是上述11项与原执行退役定向补集，存在重复覆盖，不另作15项全新能力。旧owner专属13方法与旧study模拟夹具退出，其源篡改/母群/实际geometry/原始ID/冻结实现/失败收尾断言分别在当前历史reader/worker、peak metrics、Store owner与安装probe继续；没有恢复旧PS凑测试。

### C3 已发布 scalar 样本的原位派生（WORKTREE）

`backends.comsol.assembly_field_export.derive_world_scalar_support`现在要求显式Store或现有父scope，持续持原场与可选prepared support保护直到派生stage结束；合法派生不再落旧容量owner。精确原始sample lineage校验实移`results.scalar_sample_lineage`，SIMION边界复用实际校验，execution guard不反向导入backend。只允许已知`original_samples_reference`和COMSOL raw→field→model→geometry闭包；原始bytes/SHA/role及实际路径逐字段相同，缺件/篡改拒绝。借用大payload原地保留，通过required refs保护，不全量复制或新增GC。

Agent3实际惰性原样本→派生→再派生→prepared support复用与错身份拒绝1项PASS（48.982s），真实OS句柄阻删4次、原源不变，无商业COMSOL；随后修raw guard局部变量遮蔽，source guard全9项PASS（2.791s）、prepared scalar全11项PASS（5.059s）、Ruff PASS，未无理由重跑49秒链。两个原始COMSOL采样公开入口仍待显式Store接管，这里只完成原样本派生，不能写全部scalar生产已迁。

本单元提交`47409f1b`已普通push；Agent0独立暂存树`1b3f20f3eb94b4ff2579f23c5c4f7c08f5706e61`离仓源码20项PASS（7.573s）与Ruff PASS，覆盖与前述20项重复，非另一次商业链。

### C3 指定 run 发布恢复（WORKTREE）

`ArtifactStore.recover_run_publication(run_id)`复用同一发布状态机，仅处理指定run；先GC锁、原writer token OS锁，再短事务核对发布状态/原records及native绑定。活writer/active binding/缺锁证据/双份或改动payload失败关闭；ready重读后幂等False。publishing保留原token直到可证明收尾，原failed/cancelled状态与reason不被manifest成功覆写；全Store管理恢复同步使用同一payload实现，不新增owner或全库自动扫描。该接口供新补偿等明确阶段恢复使用，不恢复旧Result/producer，不启动分析/Fly。

Agent3真实短子进程活writer拒绝→强制结束→恢复→再恢复，以及failed原因/active binding/缺证据与原admin覆盖4项PASS（1.526s）；受影响Store全28项PASS（10.305s）、Ruff PASS。两次测试进程因夹具在强杀后错误通知Event卡住，由创建Agent停止；删除该测试通知后通过，生产代码未因此放宽退出证明。尚无商业求解新增，该单元不代替全C生命周期交付。

### 3eb5e8fc 后接续检查点（WORKTREE，非最终交付）

最后已提交并普通push代码为`3eb5e8fca35b8ecc69f8f570937545389116841d`，local/tracking HEAD相同；其后工作区增量全部保留，没有reset。新版26文件/25件manifest核对与唯一C-r2 Goal继续有效，退出表仍为CA01–CA19，C0只报残差不设阈值。下述软件证据不等于商业数值资格；最终普通wheel/sdist重建wheel、离仓参考及必要Repository仍未开始。B0四项未重做，没有启动完整2D/3D、AMR、自洽或新调度平台。

- Agent0：质量谱再次纠正职责边界，`results.historical_mass_spectrum.read_mass_spectrum_inputs`只解码文件/归一表及源hash；`analysis.mass_spectrum.analyze_mass_spectrum`只接规范表，不再反向导入results，worker显式连接两者。数学/geometry/原母群/冻结源11项PASS（6.200s），与前轮重复；原全域边界16项1 FAIL/11.452s只剩历史COMSOL报告的2个Store类型注解反向引用，已由1删，2定点扫描四个原错文件为空，尚未当新全域PASS。RF旧workflow parser/main已实移唯一`msplatform.cli`，两个workflow不保CLI别名，实际PS caller同步；17项PASS、1原有skip（1.384s），原BVP冲突仍以CLI退出2/原错误文本拒绝。原生producer CLI真实status=failed不会转成功（CLI注入/错误边界3项PASS1.772s）；新工程tracking_execution CLI承载尚在集成。catalog仍由0更新，旧已删测试映射已清，但新增选择测试误把“父预检+完整分片”当仅预检，原失败保留，必须补核分片真实全集而非改门禁为空范围。
- Agent1：新OA proposal纯体归组件；CSV reader/峰形/图像分别归results/analysis，历史COMSOL CSV Store报告已有原v4 metrics完全一致/spectra字节一致和OS阻写测试。当前正保留原0-solve MPH冷提取能力，新增精确`historical_detector_export`和backend初稿仅有模拟Session正反0.161s，真实managed/旧无save_state但有完整completion分支未验，不能删旧postprocess或称完成。`run_compensation`/旧PS/optimizer CLI及两旧controller专属测试已真删，原fit数学和新三case/源/恢复/安装资源29项PASS14.868s；full ideal与Ez selector分开，未改原轴向语义。三臂商业Fly未验。
- Agent2：particle_release/Species/参考三类及系统映射继续；clock纯合同与IO分离，execution旧clock模块真删；历史完整6D/母群/clock只读归results，prepared_joint.source/flight、测量重释/centroid产粒体真删，部分trial/accelerator旧入口还暂拒，不能把拒绝壳标退休。原历史analysis21项PASS4.500s、diagnostics19 PASS/1 native opt-in skip72.363s，fixture改用冻结bytes和标明INERT元数据，没有调用旧producer造历史；首次诊断7个夹具缺件错误保留。MR信赖域/状态/SVD/Jacobian/棱镜纯体已实迁组件/analysis并改真实调用，旧PS/controller与若干旧producer测试仍待迁，单MR尚无当前模型FieldBundle/真实Fly。RF-IP原出生renderer、每原ID独立seed、单unit显式ordinal子集与最终完整母群验收已有真实Lua/collector/SI软件证据，不是商业RNG等价。installed probe持续更新而未重装，不能称已安装验收通过。
- Agent3：COMSOL scalar两个原始采样入口也已接显式Store/源guard，单grid四情形真实惰性owner59.779s PASS；multi-grid仅入口/参数seam，商业未验。scope来源保留区分standalone必要源与可回收native cache，guard成功后才登记真实闭包，GC/缺源局部重算定向通过，不一律pin中间PA。RF stationary三个合法API已迁Store，CLI由0接；旧未登记RF失败run缺证明不可自动接管。RF-IP model/field/track实际复现旧ledger误认Store路径，逐个改为同一真实claim/OS guard；原family借用要求原producer/全部成员/Refine物理证据，未知外借不放宽。新增`guard_stopped_store_evidence`精确支持真实owner可产生的failed/interrupted封存状态，单ExitStack先持index再持manifest唯一绑定记录；failed9.639s、interrupted及缺件/活binding/checkpoint等负例8.888s PASS，unit语义仍由inspector核。旧failed-only接口语义保留。
- Agent4/5：SDS公共Recipe→真实CFD解析/guard→四现有owner→规范SI/Store发布冷读及repeat全复用已通过真实public dispatch惰性测试23.862s，独立guard复核及未列路径/篡改负例合并重跑22.195s；版本/供应商进程叶替身，非商业求解。actual_callback_samples如实保存实际时刻，不冒充均匀/指定点；无detector不造命中。RF-IP统一GasEnvironment含原有显式outer_state，request只含空间域，去掉第二P/T作者；真实Study/model、原出生+clock、Store四owner首跑/repeat0新调用以及unit_size=1/N3真实OS组正式public dispatch60.004s PASS，非商业或RNG逐位资格。原family reference正在无seam整链复验；partial failed-unit恢复需新stopped guard，尚未完整验。execution unit_size/recovery/dispatch控不塞Study，runtime字典/归档/严格适用范围已接，CLI待0；scalar/discovery/SDS等未接组合早拒。旧multipole_ip连续producer/PS仍待完整恢复与映射后删。
- Agent6：paired旧静态PS/runtime与镜像旧owner测试已真删，科学电压/一ULP样点/BVP和pulse合同保留；新Store fresh/saved/已完成sample及可信failed/interrupted prepared分别通过受管惰性软件测试，旧failed资产不转成功、不复制大MPH。77.803s failed接续和10.052s interrupted小例、96.238s原位saved与51.236s无MPH samples各自适用版本见外部`retirement/paired-saved-model-evidence.json`，不拼成商业验收。成功flat历史借用链逐源OS guard、未知/循环/不可信失败来源拒绝；实际235338 failed旧run缺writer证明，约6.7GB MPH未重hash/改动。registry独占旧consumer/11资源由2删，共享保留，新资源以实际Store owner冻结为准不造假registry。当前focus只有controller Store叶和小策略修复，旧flight/workflow/fast-adjust/contrast/cache交易仍活；须公共standalone OA源/exit/focus/terminal完整事件链接通后退，不另建producer。

气体审计完整SHA/来源/各消费及限制在外部`gas-unification/active-gas-audit-working.json/.md`；唯一数据还包括`physics/data/nitrogen_transport_300k.json`，保原300K黏度/热导/cp/gamma常数近似，其他温度不授资格。未发现新的活动28u/0.370nm独立赋值；HS1 He/~200u未标定粒子对假设与EI电离截面是不同物理过程，未假并入N2固有量。原旧source bytes保留。

已完成规范CLOC 2.10：`78144e45→6a597017` total code618524→623147(+4623)、production303823→304319(+496)、tests314701→318828(+4127)；`→cfd6b848` total621542(+3018)、production303647(-176)、tests317895(+3194)，两者unclassified0。完整各语言files/blank/comment/code、用途分表及固定过滤分别在外部`oa-geometry-owner-cloc.log`、`historical-mass-owner-cloc.log`，不代表后续未提交代码；最终全口径与调用/唯一检查/重复/skip/wall仍待归并。恢复后从本检查点继续：0先完成质量谱边界修正提交、CLI/cost-catalog与完成主题整合；1冷提取、2旧MR/controller及安装probe、3停止单位恢复/源guard、4/5 RF-IP恢复/原field与standalone OA、6 focus实际迁移。C7前全体共同冻结，再一次必要发行与Repository，不因微小局部变化重复全库或大模拟。

### 57e36e7b 后接续：停止证据与仍未闭合链（WORKTREE）

`57e36e7b0adde952ff34ca76e77a380035084710` 已普通push任务tracking分支；其质量谱单元仅规范表分析/reader/worker边界，未宣称全部C完成。新版包全部26文件的既有重读/manifest收据与C-r2唯一Goal继续适用，退出表CA01–CA19，C0按用户决定只报残差。原审计后增量与所有科研资产保留。

Agent3 将group attempt/member/host验证从Store提交方法抽为同一只读 `execution.native_artifact_controls.validate_native_group_completion`，提交和失败证据读取共用；停止guard逐组验证完整attempt集，选每operation最终attempt，再严格比对原manifest writer completion和唯一host release。保留真实失败RF-IP资产 `rf-ip-recovery-16uzeopm` 的原index仍为 `[true,true,false]`，新guard只读通过；缺/重attempt负例及原真实quick/mixed组合同PASS38.366s。Agent0独立暂存树 `4c93108fd4202762c7df7ae17fe389dba1d01995` 验证16项PASS52.440s，包含因fixture TestCase顶层导入而额外发现的13项原Owner重复测试；已将测试import改成module限定以免后续隐含扩大范围，此次额外调用如实保留。该事实不等于partial恢复通过。worker仍有旧ledger来源保护调用，3/4正迁同一个中立持权helper，未跳过检查；5前轮实际replay失败记录保留，不覆盖旧probe为修复PASS。

Agent0 的工程tracking CLI明确读取一次严格JSON并交公共dispatch，重复键/非object/NaN在启动前拒绝；单CLI→中立io方向允许、io→CLI仍拒绝。定向5项PASS1.611s，Ruff PASS，仅软件派发边界；公开算法仍判定适用组合，不把engineering controls塞科学作者。catalog新增实际反射补偿选择方法已核父预检加完整owner分片，1 PASS17.192s；先前误把合法分片当空检查的失败保留，未改中央verifier或缩空范围。

Agent1 冷COMSOL成功历史/Store提取/报告17项PASS15.900s（启动器completion替身及真实Python进程，不是商业COMSOL）；发现历史detector不足仍有完整100-ID CSV的合法失败分析，正在保留failure outputs及可信停写验证，旧caller未贸然删除。Agent2/6 核实focus旧场为mirror-X半域/surface=none，与当前full-domain/fractional不同；将明确原数值设置、编译mode和缓存身份，不把旧controller包装成等值FieldBundle。原负向首次穿越、焦点主动终止和正电荷理想对照各按真实范围迁移；此时公共focus链与商业验证仍未完成。最终安装/Repository/全口径成本和CLOC仍待真正完成集成后一次必要验证。 新停止证据主题已提交并普通push `9fe3caef`；规范CLOC2.10按审计 `78144e45→9fe3caef` PASS：total618524→621973(+3449)、production303823→303802(-21)、tests314701→318171(+3470)、unclassified0，完整各语言/用途/files/blank/comment/code及过滤在外部 `stopped-core-cloc.log`。当前科学域全16项PASS10.182s，含CLI→IO允许及反向禁止；不是安装或商业native验收。

### C3 原始标量导出与必要来源保留（独立暂存验收）

`backends/comsol/assembly_field_export.export_world_scalar` / `export_world_scalar_grids` 公开入口要求显式ArtifactStore或同Store父scope，先真实claim/OS guard持field_solution及prepared support完整来源，再进入既有导出执行体；没有新owner或商业采样体。standalone发布将已成功guard的真实必要source闭包登记required refs；普通native cache scope默认不强pin全部PA，失败guard不污染保留集。大MPH/PA原位读取，未知源/错Store/缺原件明确拒绝，既有source lineage与有资格cache的GC/缺件局部重算维持。

Agent0隔离暂存树 `8353030928dbf7966c16f14d52dba921a0e10b93`（`scalar-retention-index-check-04328a88`）9项source guard正反例PASS3.986s、Ruff PASS；同树真实managed owner单方法四种惰性导出情形PASS61.191s。原Agent3同软件范围59.779s属重复验证，次数/时间分别保留，不以不同范围计算加速。供应商MATLAB/COMSOL导出叶由惰性Python替代，非商业场采样资格；multi-grid只有公开参数与guard入口接线，不冒充多grid原生验证。独立提交只包含该导出/retention闭包，不混未完成focus/cold/MR或RF worker。

RF-IP public partial replay另已PASS194.901s：实际失败index `[true,true,false]`、第三unit exit7，后续新run只启动1个Fly group member，前2单位实际复用，最终succeeded与完整N3冷读。证据外部 `rf-ip-recovery-bjcr1mj3`；原失败资产、前轮160.094s ERROR及旧probe原状态保持。真实IOB/Fly为Python惰性子进程，非SIMION数值或RNG逐位资格；原field复用/partial恢复软件合同已闭合，可据此退旧consumer，当前未把C2/C3/CA19整阶段写PASS。

### C3 显式模型查看：退出旧容量 owner（Agent0）

实际依赖审计发现 `applications.operations.open_model` 的SIMION/SolidWorks查看仍消费旧capacity owner；本单元公开API要求显式ArtifactStore或匹配的父scope，同一 `run_managed_stage` 管理私有副本、原进程和发布。`applications/model_execution.py` 在读STEP/report前持 `guard_native_source`；`backends/simion/model_view_preparation.py` 在解码/准备原model前持同一真实product guard，不再调用旧 `_protected_source` / `run_capacity_lifecycle`。公开查看图、模板设置/恢复、零粒子、禁止隐式Compute/Refine/Fly/保存及GUI生命周期均不改变；历史自定义路径resolver仍可只读解码，不能凭伪lease执行新view。

工作区实际受管软件证据：SolidWorks惰性文档两情形1方法PASS40.652s（有/无限定检查，真实Python子进程），SIMION惰性4操作与GUI前hook拒绝1方法PASS66.335s；原模板/STEP或模型、副本OS保护、原PID终态与正式host release保留，角色为GATE，绝不称真实供应商GUI。日志分别外部 `viewer-store-inert.log` / `simion-viewer-store-inert.log`。公开dispatch两项PASS2.137s、missing/不同Store拒绝PASS0.288s、只读relocation与无owner执行拒绝PASS2.071s；属于同范围追加/重复验证，不与不同环境算加速比。

独立暂存树 `97badb93c68a222ada62a41219d32266c5246716` / `viewer-store-index-check-96174402` 的上述4项低成本API/解码合同PASS3.185s及Ruff PASS；选择性暂存排除 `test_platform_api.py` 中尚未整体提交的particle/其他consumer迁移。受管惰性执行证据来自当时工作区同一三个view实现，未为该暂存树重复107秒完整惰性流程；最终发行/离仓/GUI验收边界保持未完成，未借源码证据冒称installed通过。最近 `docs/SOLIDWORKS.md` 与操作示例同步实际Store要求。

此前标量导出主题已普通push `0df3adaa5150b0b54694d153e261208492f5c92d`；规范CLOC2.10 `78144e45→0df3adaa` PASS：total618524→622059(+3535)、production303823→303841(+18)、tests314701→318218(+3517)、unclassified0，完整各语言用途/blank/comment/code及过滤见外部 `scalar-retention-cloc.log`。

### fc6eb8bb 后工作区接续检查点（非最终验收）

最后普通push代码为 `fc6eb8bb4d5c6ce9ab2910927133588c07c8ec18`，对应显式viewer Store迁移；后续工作区与原科研artifacts保留，无reset/force/主线合并。规范CLOC2.10 `78144e45→fc6eb8bb` PASS：total618524→622083(+3559)、production303823→303847(+24)、tests314701→318236(+3535)、unclassified0，完整各语言/用途/files/blank/comment/code/过滤在外部 `viewer-store-cloc.log`。C-r2 Goal持续active，仍CA01–CA19；已有26文件重读和manifest证据沿用，不另设任务。

- Agent0：viewer主题已推；CLI strict engineering JSON/失败与interrupted返回非零仍在工作区（5项PASS0.473s；先前interrupted反例真实FAIL0.098s保留）。catalog正迁实际公共RF/IP测试与删除旧continuous后的完整owner回退；修正测试误读deleted路径，1 PASS6.288s，原NoneType ERROR2.177s保留，不改中央verifier。精确移除旧continuous registry/dependency条目，保其他旧prepare consumer直到合法能力接管；能力视图1 PASS1.328s。CAD export显式Store接口为既有WIP，尚未本主题独立整合。
- Agent1：真实failed OA `215019→231000` 双guard与新报告已实际读原100行，73 detector_hit、7 freeze_without_approach_segment、20 freeze_extrapolation_outside_interval；27未确认探测不当物理损失。新run `b513ec359e714f5f91919359fe0ccf76` 保expected100/raw100/observed73/unobserved27与原source failed。原129857881B MPH唯一必要受锁SHA验证PASS0.460s，未打开COMSOL、未复制/改写。新 extraction 与报告分开记录原failed/新success，内层launcher退出/host release用公共内核，真实owner惰性两链2 PASS26.334s；历史0/1/2 hit发布null/unavailable、保原文，报告7 PASS7.213s。direct postprocess CLI/旧直接owner已实际删除，whole Candidate/phase/CAD/SIMION复用仍未退。新标准SI detector峰及final-run小plan/contract归档→GC删native stage→冷读分析由1/4接通惰性fixture；仅单batch，非商业资格。旧resolved→两组件物理投影及开启工作点校验3 PASS1.348s，明确不认证waveform/clock/release/numerics、不猜新Study。精确历史legacy_projection保留为只读物理转换，不是生产owner。
- Agent2/4/6：focus镜像模式保原半域/none surface和原作者电压，真实GEM独立几何对照已有软件证据；TestPlane来自显式SIMION相邻官方example，原bytes/key/immutable冻结，实际Lua库定步1 PASS0.107s，不是Fly。同步stop candidate→真实terminate endpoint/bracket→collector→SI冷读、首action/同面/反向/回滚/篡改等软件合同通过，TestPlane/Fly多数为INERT；负ion可load/sample/planner，电子在load_recipe的native `_build` 拒绝，原文 `SIMION native electron tracing is not yet validated`，不是已执行preflight，也不影响reference电子。4的真实Store隔离整链首轮92.711s FAIL（worker重复planner拒自己派生面，已修并精确重入/伪面短例通过），次轮110.336s FAIL（测试harness未declare，被生产守卫正确拒），修fixture外置后待复验。readiness gate仍关，不宣称public/native通过。6的Store SI焦点分析已真实出版/冷读/强制发布中断恢复两次及packet/母群篡改负例通过，纯构造SI含1/100有两面事件；fast-adjust数学/残差实迁component，原13项PASS1.661s。旧flight/workflow/fast-adjust/contrast/MRreceipt仍需真实consumer替代后删除；单独历史receipt reader只读，不能将历史candidate状态变资格。
- Agent3：MR历史数学/文件读取正实际拆职责：`analysis.mr_trajectory_diagnostics`、`analysis.mr_population`、`analysis.peak_metrics` 与 `results.historical_joint_source` / `mr_peak_output` 承接原母群/时钟/权重/KDE/峰与流式轨迹/图形，无第二实现。原measured/event 69项PASS5.979s、原diagnostics20项/1既有skip69.266s、loss8项PASS1.180s及后续精确小反例通过；各轮迁移错误与重复调用保留，不合并成未运行总矩阵。一次误切唯一文件后以5的损坏前snapshot4逐函数AST核保既有WIP：9个未迁函数一致，4个迁出计算经命名归一一致，reader只读record角色更严；21项PASS4.370s。严格历史writer guard有真实短GATE原PID/creation/host证明9.029s PASS；实际20261030跨run旧batch祖先缺完成证明，明确拒绝，不凭旧ledger/年龄认停止。尚无新完整historical joint Store API，旧PS与分析编排仍在，不称退役。
- Agent5：RF-IP完整partial194.901s已PASS（INERT vendor叶），连续旧CLI/PS/schema/专属测试已真删，隐式test/probe caller迁现public操作，registry精确删除由0执行；旧segmented prepare仍在核真实非法handoff producer与合法history职责。neutral Store整链暴露真实旧source guard，field/generic tracking/IP-MR/RF入口逐个接完整product/manifest闭包；63 products/405 records的hash绑定不等于完整语义guard，补全COMSOL geometry→prepared→solution→sample及field guard短链PASS12.198s。完整尝试依次保留296.837s（1三组件preflight PASS、neutral无scope ERROR）、134.273s（旧production guard ERROR）、134.967s（fixture缺stationary source ERROR）、212.779s（fixture同Species混mass/charge FAIL）、255.536s（fixture clock basename ERROR），均未冒充tracking成功。原负离子200u/-2/ID91/weight4另建显式typed packet实际planner/collector1 PASS1.822s；新同种100u/+1 fixture不宣称原混排等价、不改原实验。现已对保留真实field执行完整纯admission/clock/packet/vacuum+HS1 planner短验证，不再百秒跑到下一个格式缺口；后续tracking复验未完成。全部用隔离快照，主树无全局冻结。

恢复后先读本节并核最新HEAD/工作区与各owner消息：0整合成熟主题/公共C1大原子改名依赖；1whole Candidate职责逐链退、2/4focus真实Store与必要native、3historical joint真实Store及旧执行删除、5neutral/旧multipole prepare、6focus/MR原birth consumer。新包是执行合同，不复制为长期规范；C7普通wheel及sdist重建wheel、离源码公共链、必要Repository、最终CA逐条/总调用与唯一重复skip/wall全口径仍未完成。不把软件实现/未验native写为全部通过。

### CAD 导出显式 Store（独立索引主题）

`exporters.export_cad`现把调用者选定的ArtifactStore交给既有managed-stage owner；无显式Store且没有受保护父scope时，在启动owner前拒绝。STEP作者、几何来源、命名/保留规则及原CLI不变；这是公共生命周期接线，不是真实CAD/GUI资格。代码提交`9dc8a87e`只含四个索引文件；索引与隔离快照`cad-store-index-check-69f21ce5`逐字节一致，34 tests／84回执PASS（13.514s），含Store转发与无owner拒绝。其他未暂存/未跟踪在途内容未混入。

### RF–IP 连续接管后的测试与路由退役（WORKTREE）

只读调用链复核确认：当前 RF–IP 从 `msplatform run` 经公共 Recipe、`native_tracing` 和 SIMION operations 执行，旧 `multipole_ip` continuous/prepare Python、PowerShell、schema 与专属 registry 路由已删除；独立 IP 的 `-InjectedSource` 只读消费历史 MP→IP 包，不是旧跨组件 producer。没有恢复 segmented 重释放，也没有新增转发壳。

本单元把仍有真实验证对象的 `test_ip_compiler`、`test_selected_ip_provider` 原样迁到 `tests/assembly/rf_ip`，同步全部当前 imports、安装夹具和 owner 映射；删除 continuous/managed/prepare 三个已失去验证对象的测试文件。`pyproject.toml` 删除不存在包的 package-data；catalog 删除已删 prepare 测试及计时，IP preparation 改选真实 `test_upstream_admission`，RF event_table 改选直接 `test_rf_event_original_witness`。注册表移除 `multipole_ip_continuous`、`rf_ip_mr_continuous` 和旧 segmented `ip_mr_chain`；runtime dependencies 不再登记 multipole_ip 或其脚本。仅测试使用的 `multipole_ip_mr_y_minus55_plan.json` 原字节移到 `tests/contracts/fixtures/rf_ip_mr_y_minus55_plan.json`，不作为生产配置发行。现行 INTEGRATION/ROADMAP/IP PROJECT 的“segmented 尚须保留”表述已改成当前公共原出生链，历史日志与迁移时点记录不改写。

首轮 36 个父测试共 60 条回执：57 success、1 failure、2 error；32 个迁移装配/上游准入父测试全部成功。失败为 event/axis 门禁仍期待已删 prepare/compensation 测试，修正到实际 RF witness 与当前补偿合同后，6 个受影响选择器父测试／12 条回执全部成功（50.658s）。新增公共 Recipe、场引用、Store、HS1 与恢复七模块共11个父测试／19条回执PASS（213.833s），迁为测试 fixture 的 RF–IP–MR 装配计划经真实冻结闭包1个父测试／7条回执PASS（18.196s）。Ruff、JSON、`git diff --check` 和文档 StructureOnly（321 files、0 errors）通过。此前 11 文件组合轮在 300s 工具预算中止，其中 Store fixture 的 3 个既有错误及 OA 路由失败不冒充本单元 PASS；本单元不是普通双安装、真实耦合场/HS1 Fly 或 CA14/CA19 最终验收。

Agent 7 将几何和场两个原 Store 错误修到定向 PASS；组合用例随后暴露恢复 manifest 对同一记录 inputs+outputs 双登记的误拒。`guard_tracking_recovery` 现接受 `(1,1)` 的相同身份，同时拒绝重复登记及同路径 bytes/SHA/retention 冲突，原路径和防写保护不变。原 RF 恢复方法PASS（38.608s），guard 2父测试／7回执PASS（27.805s）；`test_platform_api` 的真实几何分派夹具补显式 Store 后27父测试／71回执PASS（10.407s）。这些都是 inert/软件生命周期证据，不是原生 Fly。两个完整选择器模块并行复验均在300s工具预算中止：实际已出25个成功父测试（选择器）和55成功／1失败（Changed合同），没有把它们记成完整通过；唯一失败为另一在途 SFI/paired 路由对账，留对应主题继续。

候选索引快照 `C:/Users/Liao/msplatform-artifacts/architecture-c-20261127/rf-ip-index-check-20261128T012347` 完成同一72个父测试：160条记录为158 success／2个既有Lua环境skip，discovery 72/72、无漏回执，runner 318.029s／命令323.716s。此前多轮索引失败均保留为定位证据；本轮通过依赖闭包补齐，不删除失败断言。这是候选定向软件验收，不是最终Repository、双安装或真实native签收。

RF–IP 候选代码提交为 `0ff4a4b1b200f616f6c06c2b8fea9198d6ec2c0a`。规范 CLOC 2.10 `1ca24c23→0ff4a4b1` PASS：total code 622096→626537（+4441），production 303852→307111（+3259），tests 318244→319426（+1182），unclassified=0；各语言 files/blank/comment/code 与完整过滤口径在外部 `rf-ip-0ff4a4b1-cloc.log`，其 WORKTREE_DIRTY=true 仅描述运行报告时仍有其他在途文件，不污染以两个提交快照计算的差值。

### OA Formal 空包最终退出（WORKTREE）

`oa_formal` 的科学派生核验、历史跨 solver reader、运行时物化和历史发布证据已分别归组件、results、SIMION runtime_materialization 与 execution owner；本单元只删除最后剩下的 `workflows/oa_formal/__init__.py` 空包说明及生成 `__pycache__`，不删除仍有真实消费者的 oa_candidate 或 focus 链。退休测试现直接断言父包不可导入，不再让缺失父包在子模块 `find_spec` 中变成异常；安装探针同时检查父包及两个旧子模块，并纠正先前误写成 backends.simion 的两条旧命名空间。

`test_cross_solver_validation`、`test_geometry_derivation`、`test_stage_formal_simion_runtime` 共16个父测试／22条回执PASS（0.892s），保留几何冲突、未知历史版本、运行时缺件/篡改和仓外物化检查。首次删除仅移除 `__init__.py` 后两例因目录残留形成 namespace package 而FAIL，清除生成缓存并移除空目录后复验通过；没有商业求解或Candidate/Formal资格授予。

OA代码提交为 `3cafdf7db7b9b0267d3a3382807aa6ed1e3948cb`；精确索引快照 `oa-formal-index-check-20261128T013658` 复验同一16父测试／22回执PASS（1.092s）。CLOC 2.10 `a5d10669→3cafdf7d` PASS：total code -1155、production -1208、tests +53、unclassified=0；完整各语言基线/结果/差值和过滤口径在外部 `oa-formal-3cafdf7d-cloc.log`。这些提交仍不构成C最终验收。

变更选择器对账另修复一项真实旧期望：`test_field_plan_dependency_uses_actual_selected_consumers_without_duplicates` 对已删除的 `test_paired_accelerator_static_field_execute.py` 现要求完整 Assembly owner 回退，而不是把已删路径加入窄集合；原其他来源、混合变更、Owner/Repository 断言保留。定向1父测试／9条回执PASS（25.398s），未扩大为完整模块通过或原生证据。

### 当前 Assembly 导航与远端首错

公开 Changed `7878647c`（run 46044367921）在文档阶段报告两条旧 `multipole_ip*.ps1` 坏链，22.477s，后续功能测试未执行。现行 `docs/ASSEMBLY.md` 已收敛到 `msplatform run`/公共 Recipe，删除旧 FullJoint、SFI、paired-static 和 multipole_ip 的活动命令；历史语义只读保留。这里不把文档通过当作真实 native 或完整 Repository 通过。后续 `8f9559a8`（run 46045620021）仍有一处指向尚未入库 Store 模块的链接，现改为 INTEGRATION 的现有锚点；不把该模块提前提交或把文档修复当作其功能验收。

完整 Changed 合同复验实际得到108个成功父测试、1个路由失败，无 error。`build_and_export_paired_accelerator_field.m`、`oatof_build_accelerator_geometry.m`、`oatof_build_grid_geometry.m` 在 paired-static 退役后只选择实际 TOF owner，不再错误要求 Assembly；其余七个登记路径仍必须选择 Assembly。定向1父测试／12条回执PASS（25.085s）。该结果不替代后续同一SHA完整门禁。

C5 对账中曾试改“删除源仍沿用映射”，但既有真实负例证明这会复用失效叶；该过宽改动已撤回，继续保留删除权限的完整 owner 回退。实际修复是移除已删 `prepared_joint/source.py` 的活动消费者断言、按全部 MR/TOF 分片对账，并移除已删 mass-spectrum admission 测试；现存 Candidate/peak 消费者保持。相关定向2父测试／11回执PASS（27.631s），SFI 正常入口1父测试／5回执PASS（1.522s），反射拟合的现存直接消费者与删除旧 optimizer 的完整 owner 回退分别核对。完整选择器轮实际75成功、2 failure、2 error；其中 Prepared 语法错误由其在途 owner 修复，其余逐项定位，不把该轮写成通过。

修正后完整 Changed 合同109父测试／460条记录全部成功（687.375s），完整选择器67父测试／322条记录全部成功（536.488s），均无 skip、无漏回执。公开 `8a12f424` Changed（run 46048308486）也已成功。上述是不同的中间代码身份和软件范围，不拼接为最终同一 SHA 验收。

### Prepared 旧飞行与重释放链退出（WORKTREE）

Agent 8 将 prepared_joint_execute 的完整 Flight 参数、两种 source mode、SIMION 参数和不可达旧 Flight 主体实际删除；仅保留 `-AnalyzeRunPath` 历史分析与 `-ResumeFinalization` 原 run 收尾。下游 workpoint 迭代移除 Prepared/centroid 获取、重锚和专用恢复，真实 trial runner 只选当前 OA–MR 入口。`prepared_joint/trial.py` 删除 prepare/materialize/protection producer 与 CLI，保留轨迹等价和历史 probe 分析；新飞行仍由公共 `msplatform run`／`native_tracing` 原出生链承担，没有恢复跨组件重释放。

直接消费者同步删除已删 API 的调用，历史 component-exit 原 ID/clock/母群及篡改负例保留，Assembly prepare-only 与 finalization 保留。MR SIMION 文档移除 Prepared P/S 新运行命令。定向结果：退役首错3 PASS、legacy 同类8 PASS、trial+iteration 104 PASS、iteration runner 111 PASS（214.164s）、prepared execute 8 PASS（399.001s）、历史 component-exit 2 PASS、accelerator interface 13 PASS（51.430s），均0 skip；公共 IP–MR preflight 在补私有 host-state 后PASS（195.585s），退役 PowerShell 负例3 PASS。无商业求解或最终 Repository/双安装声明。

### C1 particle_release 收口与参考三类物种（候选索引）

现行作者、原生/参考消费者、安装探针与 gate catalog 已统一切换到既有 `particle_release` 和显式 `contracts.species`；旧 `ion_release` 生产包及其重复测试命名空间删除，不保留导入别名。源生成 PowerShell、双锥源配置和 RF 冻结快照按同一新所有者同步；历史科学 ID、原冻结字节与只读历史证据不改写。参考 Recipe 升级为 schema 3，物种表提供质量/电荷，初始粒子引用规范物种；公共 Recipe/追踪继续独立持有通用入口，reference 模块不再兼任通用调度。

同时完成已实拆的 IP–MR 连接与几何来源收口：`assembly.ip_mr_connection` 只负责选定 Assembly 连接，`assembly.geometry_primitives`、组件几何和 SIMION IO 各保留实际职责；旧 `prepared_joint.ip_mr_connection`、`prepared_joint.ion_processor_assembly` 与 `accelerator_interface.geometry` 删除。该删除不代替剩余 Prepared/OA 活跃职责退役。

首次精确索引只含旧包差异，4 个新增合同测试未被收入而产生4个收集 error；补齐后逐轮暴露参考 schema、通用追踪与 Assembly 新文件依赖并纳入同一候选。`c1-index-check-20261128T031610` 的56父测试／107回执全部成功（3.511s），含三类独立参考解析、负粒子/电子身份、源采样与旧模块缺席。RF 源预检另发现回执读取仍期待 schema 1、当前测试仍作者旧 role，已分别改为实际 schema 2/`repository_particle_release` 并显式 `species_kind=ion`；`c1-rf-index-check-20261128T032640` 的16父测试／31回执全部成功。SFI 当前 prepare/zero-gap 新粒子请求在 `c1-sfi-index-check-20261128T034344` 为52父测试、240 success／1既有环境skip（60.478s），只证明当前输入合同，不宣称旧 SFI 包已退役。补齐组件 v2 描述符、当前 schema、OA 诊断与 recorded-birth 反例后，`c1-combined-index-check-20261128T042129` 合并147父测试，425 success／1既有skip（80.858s）。双锥组件迁移另由 Agent 1 完成：组件目录109父测试、合同目录53父测试中，除两个明确要求正式公共 GATE 的宿主上下文用例外均通过；这两例及合并范围由后续正式门禁复验，不将裸跑环境错误算作生产 FAIL 或 PASS。最终组件索引 `c1-components-final-index-check-20261128T042407` 的187父测试／381回执全部成功（321.748s），Ruff 与 diff-check 通过。公共双锥 Changed 首轮因未配置 Lua 在安装预检失败；以实际 `C:/Program Files/SIMION-2020/lua.exe` 重跑后，安装夹具又暴露重复气体字段删除后的 `species_id` 读取，现改从唯一 `NITROGEN` 数据集取身份/质量，等待复验。后续安装夹具补齐实际 API 所需的环境/几何及记录，不再传独立 composition；公共 `c1-dual-public-gate-final.log` 仍FAIL，安装分片在 MR fixture 固定 SHA 断言停止，另一分片66父测试为200 success／7 failure／1 error，含旧 Store 作用域与 IP–MR 错误文本夹具；这些真实失败保持未关闭，不用前置索引绿灯覆盖。上述均不是商业 native、普通双安装或全 C 验收；完整变更测试索引复验及最终同 SHA 门禁继续执行。C1 候选提交/普通 push 为 `0b5a472d12cca3dc3610afaeb503ab3875b0ddc5`，local/remote 相同；规范 CLOC 2.10 `667f62db→0b5a472d` PASS：total code +1150、production +896、tests +254，unclassified=0，完整各语言 files/blank/comment/code 与过滤在外部 `c1-0b5a472d-cloc.log`。

### Prepared 控制器传输职责退出（WORKTREE）

旧 `prepared_joint.controller_state` 仅是 MR 纯组件的 stdio/CLI 适配，已移为 `workflows.mr_design.workpoint_controller`；原科学计算仍唯一来自 `components.multi_reflection_tof.workpoint_controller_state`，没有复制算法或旧名转发。实际 PowerShell 调用、测试、catalog 和 SIMION 文档同步切换，旧模块路径零现行引用。

直接模块30父测试／72回执全部成功（5.010s）；同命令中 path::method 写法不被 runner 支持，另以点分方法名复验路由。首次路由复验因新位置命中既有 `mr_design` 前缀而暴露5个额外实际测试，已更新对账而非缩范围；修正后1父测试／6回执PASS。精确索引首轮31父测试为77 success／1 failure；非法参数用例沿实际 import 发现 `prism_trial` 仍从旧 OA workflow 取已迁移函数，同步到组件 owner 后复验31父测试／78回执全PASS（11.968s），没有改错误门槛。该单元保留最终门禁欠项，不代表 Prepared 其他容器已经退役。提交/普通 push 为 `c734366a`；规范 CLOC 2.10 `0b5a472d→c734366a` PASS：total code +4、production +0、tests +4，unclassified=0，完整口径在外部 `mr-controller-c734366a-cloc.log`。

### Store 输入前置与离仓宿主边界（WORKTREE）

公共双锥 Changed 的失败已逐项定位：实际 Lua 5.1.5 通过 `SIMION_LUA_EXE` 显式选择；安装夹具改用唯一气体/环境/几何来源及记录；MR 当前组件和轴响应资源绑定实际字节；错误文本中的乱码统一恢复为规范 IP–MR/OA–MR/RF–IP/OA–TOF。`execute_fields` 在任何 Store/文件/进程操作前完成预算、I/O、materializer 与 artifact-reference 结构校验，保持原错误语义。

离仓历史质量谱曾因父级 token 泄漏而无法取得非继承 owner。公共进程适配现在仅清除 token、owner PID 和 role，保留显式状态库与 Python，原保护握手仍严格要求独立 owner；回归同时核原宿主错误/退出码保留。相关 Store/IPMR 正反例、原生资产与完整响应绑定模块均PASS；独立索引4父测试／9回执全PASS。公共离仓运行中历史质量谱/场读取、参考三类物种和记录出生已PASS；最终仍在历史 IP 旧 source schema 处失败，需只读事件解码，不能重新采样冒充历史，故未标最终通过。

### C 活跃消费者对账（开工定位，未闭合）

| 实际入口 → workflow/API | component/schema与科学输入 | 资产/进程owner与结果消费者 | C新路径/当前状态 |
|---|---|---|---|
| msplatform run → native_tracing/scalar_tracing | B split OA+TOF、schema2 Study、冻结clock/birth/OFF/ON | ArtifactStore规范结果；既有native owner保护原始PA/MPH | 保留B，C0补真实V/E、not_started与remaining；未闭合 |
| mr_verify及mr_design/oa_mr/prepared_joint | 现MR provider、候选几何/驱动与数学分区 | 原run/field owner及MR分析reader | multi_reflection_tof；准备与追踪分开迁移，未闭合 |
| ip_functional → ion_processor.functional | 现IP provider、source/numerics、HS1/HP-LP输入 | SIMION batch/GUI-replay owner、IP results | ion_processor与唯一N2/模型数据；未闭合 |
| dual_cone阶段 → dual_cone_stages/COMSOL gas-flow/SIMION transport | 独立双锥provider、气流/SDS/碰撞来源 | 原气流/PA/transport owner与轨迹诊断 | dual_cone_tandem_quadrupole，保留真实能力范围；未闭合 |
| multipole_ip_continuous → multipole_ip.continuous | RF variants/IP/MR完整场、原birth/clock/HS1 | 既有whole-unit track owner、REC/分析 | 复用连续实现接公共入口/结果/owner；未闭合 |
| accelerator_interface -FullJoint / prepared_joint_execute | assembly_registry的ip_mr_chain及下游准备源 | 原准备与joint-field owner、handoff/analysis | 关闭跨组件重新释放，区分合法局部/prepare-only；未闭合 |
| single_reflection_flight RF recorded-birth | schema12/plan6、RF→OA→TOF真实母群 | split track owner、规范终态/事件 | 补有声明的新连续native小例；未闭合 |
| oa_candidate/oa_formal/compensation及历史mass reanalysis | 本地whole-Fly/response basis、历史分析/认证 | 原local run/验证发布owner、历史reader | 合法研究保留、总等级退出、不可达producer删除；C0-04先修observer |
| EI/Wehnelt现有组件入口/execution_profiles | 当前真实geometry/model能力与源/常量 | 既有COMSOL/运行owner、各产品合同 | 公共输入/能力/owner按实际范围接入；未闭合 |

### C4 首个实修单元：删除旧 COMSOL retrace 不可达体

Agent 6沿真实调用确认`backends/comsol/oatof_retrace.py`的completion读取/物种认证仍供历史分析使用，保留其唯一实现及原执行拒绝；删除拒绝后的37行Python死体。`backends/comsol/matlab/run_fixed_particle_retrace.m`保留既有冻结资源身份和明确错误边界，删除其后329行不可达旧producer。不是恢复composite；后续对应活跃caller退出后再核资源去留。最近PROJECT已区分历史说明和当前可用范围。

`python -m unittest tests.contracts.test_retired_comsol_execution -v`：3 PASS/0 skip，0.767 s；包括执行前拒绝、历史认证成功和错误检测数/run ID/host release未知反例。Ruff、diff与文档StructureOnly PASS。另一组合命令内历史旧测试因缺`MASS_SPECTROMETRY_HOST_CONTEXT_JSON`而ERROR（42.688 s），未计为PASS，保留原日志/临时失败目录；未执行MATLAB或新增native资格。此单元不授C0/C4整阶段PASS。10个PA种子仍有native_plans/rf_tracking/安装的实际消费者及独立实例需求，暂保留；三个tests生产PS的去留正在逐项处理。

已提交并普通push `1b77f612201cba6604d146ae22afb22976bdbc4d`。规范CLOC 2.10按`78144e45→1b77f612`实际PASS，完整total/production/tests各语言与过滤口径见外部`C:/Users/Liao/msplatform-artifacts/architecture-c-20261127/c4-retrace-cloc.log`，计数以提交为输入，不把并行WIP混入；累计C最终再以最后代码身份报告一次。

### C0-02/03/04：启动失败、remaining 与有效深路径观察

未启动证明只由`resource_process_support.ps1`的实际OS Start-Process失败分支触发，`process_owner.ps1`持久化nonce/binding/operation及原错误；Python核对ACK/host/私有work身份、无worker登记、原host账本文件身份和同token正式释放，Store按既有控制锁幂等关闭binding。缺证据、错身份、活worker/登记失败均不放权；外层仍持有的claim/reservation不删除、不清零。不是以缺worker文件/PID/超时推断退出，group协议不外推单worker未启动证明。

`native_tracing._growth_accountant`在新Store引用/冻结输入/科学输出的真实写入边界更新`reservation_written(reservation, remaining)`；仅计本任务私有目录的新增增长，高水线避免同文件重复扣量，不扫描共享旧PA/MPH、不把已存在共享载荷计入增量，不抹去未知未来增长。超出声明预算明确失败，真实free准入保持。受控例free20/P10→写6/free14/R4后第二任务P5可准入，失败释放与重复调用有回归。

`RunSession.run_process`继续用既有短execution alias作为cwd与实际stdout/stderr路径，持久角色/manifest仍canonical。原测试改在当前`processes._invoke_process_owner`的真实请求边界观察并断言observer触发，保留深路径、流alias、context恢复、来源字节不变、completion不变和host/capacity释放断言。有效observer修前1 test FAIL（111.118s，输出流实际深路径）；修后1 PASS/0 skip（138.413s，0 native）。旧90秒FAIL仍保留；不是性能无退化结论。worker120s预算保持；外层覆盖源码冻结与worker的240s预算有实际阶段依据，不靠只增加原90s蒙混通过。

Agent 3的实际定向命令均为仓库`.venv` Python、显式src环境：`tests.repository.test_native_artifact_controls`的两个not_started方法分别1 PASS/6.169s和1 PASS/6.092s；同模块四项父死子活/精确身份/quickexit/活登记失败4 PASS/27.353s；`tests.contracts.test_native_workflow tests.contracts.test_artifact_store -q`26 PASS/10.385s（含remaining），预算细例另重复1 PASS/0.209s。上述加deep测试共34个调用/33个唯一方法、0 skip；wall分项不相加成端到端历时。Ruff/diff PASS。C04的前后observer与日志在`C:/Users/Liao/msplatform-artifacts/architecture-c-20261127/c0-deep-reanalysis/`；C02/03命令结果来自本轮工具执行记录，未伪造单独stdout日志。外部Linux存储probe直接复制到新C目录在Windows无法按shebang启动，exit1不是重现成功或修复PASS，原recorded JSON未改。C0-01实际点验仍在运行，C0整体验收未完成。

上述C0软件单元已普通push为`6ba108fd53a06fe27997190800ab15183984deec`；暂未混入particle_release包移动，跨包命名另主题提交。

### C0-01 实际 V/E 有限点位记录与用户追加决定

用户在本轮明确回复：“报告残差即可，不设置阈值。” 该决定覆盖执行包CA01的事先误差阈值退出条件；本项按真实测量/来源/误差记录交付，不因没有阈值阻塞，也不授予仪器场精度、网格收敛或跨后端等价资格。

比较前冻结frame=oatof_global的5点（mm）：world(200,200,400)、birth(-14,0,-20)、grid1(5,5,-7)、intermediate2(5,5,30)、exit(5,5,270)，分别OFF/ON。原COMSOL MPH独立mphinterp查V/三分量，SIMION8.2实际scalar_field_adapter查绑定窗口；两状态共10组插值支撑均核原始FEM mask全有效。0 Compute、0 Refine，不改源/脉冲/网格；点集冻结SHA为`87F6D968EE98ECA9A012EC6E908E46DAA925B88D6E11503ABF21ABE929196F55`。

| 记录量 | 最大绝对残差 | 所在点/状态 |
|---|---:|---|
| V | 0.1652609324 V | grid1 / ON |
| Ex | 5.701606175 V/m | grid1 / ON |
| Ey | 33.00130575 V/m | grid1 / ON |
| Ez | 55.00354663 V/m | grid1 / ON |

OFF的5点均为零；ON逐点原值、窗口/support与分量残差在外部`C:/Users/Liao/msplatform-artifacts/architecture-c-20261127/c0-field-validation/{point-comparison.json,support-evidence.json,evidence.md}`。COMSOL首次外部诊断因返回单位数组形状断言失败，修形状无关严格校验后原生query exit0/bootstrap PASS并保存10行结果，但Python诊断owner又因标记检查错误最终failed；这些结果按失败owner中的实际成功原生operation证据引用，未改写owner为成功。随后单独SIMION查询owner success/complete/writers_confirmed、容量释放。所有失败原run保留，未第三次冷开MPH；COMSOL runtime自动产生的recovery副本归本任务临时写入，不修改原3.08GB MPH。

### C4 两条失效生产脚本退出

旧`tests/.../comsol/run_n100_candidate_functional.ps1`在StrictMode下先用未赋值Python且调用已退役composite；`run_extreme_particle_count_case.ps1`同样依赖退休retrace和失效旧project路径。反向调用核查只剩活动导航/镜像脚本形状测试，无合法独立生产调用，已删除这两入口，导航改到公共Study及历史只读；删无适用对象的镜像测试和失效清单项，不恢复旧运行凑绿。历史owner迁移映射原字节保留。

`tests.components.single_reflection_oa_tof_mass_analyzer.analysis.test_governed_run_entrypoints`与`tests.contracts.test_retired_comsol_execution`组合6 PASS/0 skip，0.869s，包含重复的3个退休合同（非6个全新检查）。场理想化sweep仍有真实消费者，正在迁现有workflow并修其明确路径/owner缺口，不因位于tests就一并删除；该生产链尚未授予安装/native/C3闭合。

## 当前批次 B 检查点

批次B按本页声明的BA01–BA15范围交付；最终代码为`90d6d5e8b67e5b0bfe3e823b0130c30c266eea2b`，本次随后提交仅更新交付记录。最终结果见[最终交付记录](#b-最终交付记录2026-11-27)。不启动C/M06–M08，不授全仓门禁或仪器物理资格。

- 三格新链实际native成功：SSA e95/ee0、CC e95、CS08；同版本复用、N3/N2多电荷、缺件局部重算、合格GC、原pulse N1独立解析基准均已有证据。0 hit/unknown归属和仪器ON/场精度未验证范围不改写。
- ee0正式聚焦Changed已PASS（7阶段/28 tests/0 skip，1820.198s），含完整普通双发行父方法1794.208s；原08广Changed仍保留9 PASS/2 FAIL/15 BLOCKED，不拼成全绿。
- 原15 blocked消费者已逐项执行完：11 PASS、4 FAIL、0 BLOCKED，前后40输入SHA一致。实际故障、过时旧执行正例和历史inert fixture逐项修复；根87项定向回归285.105s PASS，Ruff/文本字节PASS。
- 深路径旧ReanalyzeOnly原90秒测试仍FAIL，旧observer在a9之前即失配；后代自然analysis success/complete，0native、source认证/不变、错误context拒绝/正确context恢复与资源释放均已实证。具体cwd/alias断言仍未验证，作为明确C/P4遗留，不改变timeout、不推断无性能回归、不称整catalog PASS。
- 两个本轮临时worktree已备份全部11个改动字节/patch并验证属于现有任务提交，普通移除，无force/reset主工作树。可重建解包源码清理及原日志/归档保留；研究PA/MPH、原始数据和此前被自动审批拒绝的三个Temp保持不动。
- 最终代码普通wheel、sdist重建wheel两臂离仓参考验收PASS（360.732s），含B预检、mass_scan及installed continuation正反例；b6独立安装同一最终wheel，公共CLI运行`6394fada38644e33b63a84a940f652ae` ready/succeeded，科学结果与b5相同、3374项原生清单不变。最终CLOC已完成；下一步仅按用户后续授权进入C，深路径旧测试仍按具体条件留C/P4。

## 开工事实与边界

- 开工 checkout HEAD：`260c354d8beeeed26a40fdc7c7602e45f06d8934`；实际实现/审计基线
  `b94e0818a4823102425b6ad77327106b07143250`。
- 用户确认旧目标分支已经合入 master；本次从当前 HEAD 创建 `task/architecture-migration-20261126`。
  用户随后授权本地分支及 GitHub 推送；不合并、不改写远端历史。
- 开工仅有未跟踪 `artifacts/`，保持不动。提交图复核确认开工 checkout 是 master 的祖先；
  已暂停所有 Agent 写入、仅暂存本任务两个依赖文件、快进合入 master，再恢复本任务改动，无冲突。
  最初将差异方向误记为审计后增量，现已纠正。master 已含 common/projects/integrations 目录迁移，
  门禁是 `tools/repository/verify.ps1`，普通安装测试是 `tests.contracts.test_installed_scientific_core`。
  master 与执行包审计提交完全相同，无需额外审计后增量分析。
- 本轮正式功能：配方/物性、静态解析 E/B 的数值 tracing、受管结果、CLI/API、复用与安全缓存 GC。
  长期验证：独立解析对照、安装验收和生命周期行为测试。B/C 与 M06–M08 不自动实施。

## 合同与 ownership（实现中）

Agent 0：CLI、工作流、Parquet/HDF5 结果、文档与联合验收。
Agent 1：`physics/`、`recipes/`、根参考 TOML；Agent 2：`fields/`、`tracing/`；
Agent 3：`storage/`；Agent 4：只读评阅映射与旧消费者核查。Git 写操作由 Agent 0 串行完成。

公共结果使用 SI + float64、int64 粒子 ID、实验相对时钟；常量冻结现有质量值，CODATA 升级独立。
场显式声明 E 与 B（零也须声明）；仅静态给定场，时变、碰撞、自洽等未支持组合失败关闭。
初态、事件、终态和轨迹独立；物理结果、停止原因、完整性、执行成功分轴。
新根由唯一 ArtifactStore 管理，禁止新旧账本共同管理。旧链暂不接管。

## 工作单元与验证

### A0：启动审查与公共合同

已读规则、执行包和 JSON 覆盖规则；具体否决优先于泛化同意。
新 CLI 为 `msplatform`，动作统一 tracing；无 transport_mode/友好解析别名。
下一步：实现参考闭环并以真实数值和生命周期行为确认 AC01–AC14。

### A1/A2：配方、单位与真实 tracing

已实现 `physics/reference.py`、`recipes/reference.py`、`fields/__init__.py`、`tracing/__init__.py`。
根 `recipes/reference/` 的四份 TOML 是唯一作者正文。参考单元明确是解析参考几何，不假装真实仪器 provider。
公共常量冻结既有 u=`1.66053906660e-27 kg`、e=`1.602176634e-19 C`；OA 历史兼容值不改。
Decimal 前缀转换一次舍入，0.9 mm 与 0.0009 m 身份一致，label 不影响 recipe/assembly 身份。
装配生成器支持规范串接序列含重复项，执行仅支持实际验证的 reference_cell；图结构明确拒绝。

独立闭式 oracle 与实际 DOP853 在 31 个相同实验时刻比较（含非零初时刻、负电荷、交叉 E/B）：

| 算例 | 最大位置分量误差 m |
|---|---:|
| 无场 | 4.86e-17 |
| 均匀 E | 1.39e-17 |
| 均匀 B | 2.08e-17 |
| 交叉 E/B 负离子 | 6.94e-18 |

最大速度分量误差 ≤1.10e-11 m/s。仅证明参考静态场范围，不证明 RF、商业后端或空间电荷。
事件使用平面根定位；步内多次穿越/切触可能漏检，必须选择合适 max_step，不能宣称任意几何完备。

### A3：存储与真实链初次集成

`storage/store.py` 为新根的唯一 owner；短 SQLite 事务协调 publishing/ready/delete_pending/deleted，
payload I/O 在外，独立 JSON manifest 与 SQL 记录均校验；claim_key/put_asset_claimed 消除获取/发布与GC竞争窗口。
新受管根必须在所有 Git 工作树之外；外层 workspace 本身也有 `.git`，因此实际验收根使用
`C:\Users\Liao\msplatform-artifacts\architecture-a-20261126`，不在旧账本树下。
失联 claim 保守保留；自动验证进程树后释放未实现，不用 TTL 猜测释放。

`workflows/reference_tracing.py` 接通配方→预检→场资产→完整粒子批→独立表/轨迹→发布→重读统计，
`cli.py` 与 `__main__.py` 共用实现。运行自含科学证据，缓存仅 provenance，不变为永久 pin。
缓存键含真实科学输入、相关实现摘要和 NumPy/SciPy/常量版本；无关 label/仓库文档不失效。
失去一个粒子批文件只重算该批，其他批与场保持命中；软水位自动回收后历史 run 仍可重读。

联合针对验证：2026-11-26 `python -m unittest tests.contracts.test_reference_workflow
tests.contracts.test_reference_recipe tests.contracts.test_reference_tracing tests.contracts.test_artifact_store -q`，
22 项 PASS，6.838 s；对应新主链 Ruff PASS。包含真实发布/重读、int64 大于2^53的ID、缺件局部重算、
label/物理变化、自动GC、0命中、取消和注入的求解器失败诊断保真。故障注入不冒充真实物理成功。
初次开发树 run 已完成，但安装后验收尚待执行，不据此关闭 AC13。

## 官方路径与版本

查阅日期 2026-11-26，使用官方库API，无自建文件编码器：
[Python 3.11 TOML](https://docs.python.org/3.11/library/tomllib.html) 的 parse_float=Decimal；
[SciPy solve_ivp](https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.solve_ivp.html)
的 DOP853、分量atol、事件根定位（在线文档1.18，锁定1.17.1，本轮测试验证实际安装行为）；
[Arrow write_table](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.write_table.html)
26.0.1 的显式schema读写；[h5py datasets](https://docs.h5py.org/en/stable/high/dataset.html)
3.16.0 的float64/int64分块数据集；
[SQLite事务](https://docs.python.org/3.11/library/sqlite3.html#transaction-control)、
[os.replace](https://docs.python.org/3.11/library/os.html#os.replace)、
[shutil.rmtree](https://docs.python.org/3.11/library/shutil.html#shutil.rmtree)。
Parquet/HDF5 为本次用户指定公开数据合同，取代旧“先证明CSV性能瓶颈才引入”的前置限制；
未借此迁移无关旧结果。新增 pyarrow=26.0.1、h5py=3.16.0 纳入发行与锁文件。

## 剩余消费者与下一批

旧 SIMION tracking/state relaunch、FullJoint 分段分支、Candidate/Formal 资格路径及旧容量账本
仍存在；按真实连续生产链接管进入 B/C，不将新参考链通过当作其退役证据。
具体文件清单、验收数值和交付 HEAD 在各工作单元完成后补录。

## A2/A3 补齐与隔离验证

首次 Changed 门禁运行期间，逐条验收复核发现了物性资源、事件标识和运行控制的实际缺项。
为保护正在消费的源码快照，后续修正置于临时隔离 checkout；原工作树和已有产物保持冻结。
临时 checkout 不创建另一条任务分支，最终由当前任务分支接入同一代码提交。

已补齐：`physics/data/reference.json` 随包发布唯一的新链常量/真空/none 数据，旧版本常量值不变；
初态 `parent_particle_id=null`、`lineage_status=unavailable_initial_snapshot` 明确未知谱系，
初态只是快照，不伪造真实 birth/次级事件。事件有每粒子连续 `event_sequence` 和法向速度符号方向；
磁场下同一观测面的重复穿越保留独立事件。public tracer 与 CLI 均拒绝未知科学字段、非公共常量、
非真空及未实现组合；真实有限输入数值溢出报告 numerical_failure，诊断经发布/重读保留。

`begin_run/mark_running/run_status/finish_run` 将执行状态与 publication 状态分轴，运行前即有固定
run_id/月桶和冻结输入；容量不足保留 queued 及原因，不伪造启动。当前无后台调度器。
`recover_controls` 在持有精确 token 的 OS 锁后才释放失联 claim/预留，无 TTL 猜测。
当前参考 tracer 只在本进程计算；后续 native/独立消费者必须自行持有使用保护，不能根据父进程退出
推断全部后代退出。Windows junction 和多硬链接载荷拒绝，外部目标保持不变。
软水位统计包含登记 run 的占用；只清合格 cache。工作流按本 run 新增字节减少未落盘预留。

来源记录单列 `repository_source`：显式传入完整 SHA 时记 declared，否则诚实记 unavailable；
不会从 cwd 猜来源，也不将整仓 SHA 用作科学缓存键。author.toml 与 resolved.json 均冻结在 run 内。

隔离开发验证：49 项 PASS，26.665 s；包括 6 配方、6 tracing、15 storage、5 完整工作流、
16 科学边界和 1 旧门禁缺陷定向复验。Ruff 与 diff-check PASS。局部验证设置源码路径，
**不作为安装后证据**。旧缺陷是 `test_adapter_uses_real_facade_with_isolated_ledger` 强选
`sys._base_executable`，使虚拟环境任务误用未装包的系统 Python；已仅改两处为当前 `sys.executable`，
不在全局安装包、不修改生产 facade。先前 PATH 重试仍失败的事实保留在验收记录。

### 29 处具体意见的落实表

“原状态”来自评阅表，下面的实现细节属于执行包选择；不把它们回写为新增同意。

| ID | 原状态 | 本轮落实 / 后续边界 |
|---|---|---|
| A02 | 同意 | 版本化严格合同、公共能力预检、依赖摘要；新组合仍须独立验证 |
| A10 | 修改 | 规范 single_reflection_tof 不含 OA、无 alias；真实拆分 B |
| A11 | 修改 | Assembly 物理内容与 SimulationRecipe 分工；真实仪器 B |
| A13 | 修改 | 新链仅连续 tracing；旧重发射 B/C 按链退出 |
| A15 | 同意 | 自洽未实现且明确拒绝；M06 独立 |
| A20 | 修改 | SI/float64、Decimal 边界、分量容差、冻结常量；不混入 CODATA 升级 |
| A24 | 修改 | 独立 ArtifactStore、SQLite/OS锁、预留/GC/恢复；旧 owner 收敛 C |
| N02 | 修改 | msplatform CLI 与 python -m 同实现 |
| N04 | 修改 | SR-TOF 仅显示；真实 provider B |
| N05 | 修改 | RF-MP 仅显示；现有 RF 变体保留 |
| N06 | 修改 | MR-TOF 仅显示；规范名 multi_reflection_tof |
| N07 | 修改 | MR 不设空 variant；真实模型/注册对齐 C |
| N09 | 修改 | IP 不设空 variant；真实模型/注册对齐 C |
| N13 | 不同意 | 不注册 reflectron 子部件；内部几何语义保留 |
| N14 | 不同意 | 不注册 drift_region 子部件；内部几何语义保留 |
| N15 | 修改 | 单一名称生成器、无友好解析 alias；真实 OA 组合 B |
| N16 | 修改 | 同一生成规则；真实 RF/OA/TOF 配方 B/C |
| N17 | 修改 | 同一生成规则；真实 IP/MR 配方 B/C |
| N21 | 同意 | 通用 mass_scan 的自由物种/数量及分析条件进入 B，不本轮扩展 |
| N24 | 修改 | 新链无 segmented；旧生产执行链 B/C 完整退役 |
| N26 | 修改 | 公共 ParticleTracer/particle_tracer/tracing 一致 |
| N27 | 修改 | 新合同不含 transport_mode，也无单值替代枚举 |
| N43 | 同意 | 结局/停止分轴、参考面归属、原生不可用显式 null；真实映射 B |
| N54 | 同意 | 新主题拆至 TRACING/ARTIFACT_STORE/index；旧原生正文其余 C |
| N58 | 修改 | 双锥独立 dual_cone_tandem_quadrupole，覆盖泛化 DCI 旧提案 |
| P07 | 同意 | E/B 显式声明、能力边界；时变/自洽未实现 |
| P08 | 修改 | 新公共领域 tracing；旧自有 tracking 逐链 B/C |
| P24 | 修改 | 新 Store 固定 runs/YYYY/MM/run_id，UTC 元数据 |
| G04 | 同意 | 耗时优化项与正确性失败分开，不按理想分钟数伪报通过 |

### 活动旧消费者与退役入口

以下路径均在 `src/msplatform/` 下，仍可执行，不因参考链完成自动改写；历史产物 owner/状态保持。

| 旧消费者/字段 | 当前 owner | 目标 / 批次 | 退出或保留条件 |
|---|---|---|---|
| assembly/handoff.py 的 HandoffResult；backends/simion/operations.py 消费 | assembly + SIMION | 连续完整母群/时钟合同，B | 先抽出正确校验；对应连续链接管后退役执行支路，历史只读 |
| backends/simion/tracking_execution.py 的 segmented_upstream/state_relaunch；tracking_collection/program writer | SIMION | tracing adapter，B/C | 连同 writer/默认值/门禁退出；保留原 ID 完整批分与真正检查点 |
| contracts/schemas/assembly_registry.schema.json 的 segmented_handoff | assembly registry | 连续链注册，B | 随真实消费者迁移，不只删除字符串 |
| workflows/resources/accelerator_interface.ps1 的 FullJoint 范围/重释放分支 | 原工作流 | 连续实际替代，B | 确认物理场范围/实验时钟后逐分支退役 |
| workflows/single_reflection_mass_spectrum*.py 的 candidate_mass_spectrum、固定五质量/命中约束 | 旧质量谱工作流 | mass_scan，B；等级收敛 C | 校准条件回归具体分析，不限制通用追踪；历史保留原名 |
| components/registry.py、examples/rf_oatof_functional_v1.json 的 single_reflection_oa_tof | 原 provider/示例 | OA 与 SR-TOF，B | 不重写已经复用的 OA 物理；按真实几何与源/场对照 |
| MR/IP 旧长包名和注册；双锥长 package ID | 各组件 | multi_reflection_tof/ion_processor；独立双锥，C | 按真实 provider 迁移，不把项目ID、组件ID、显示名混同 |
| execution/artifact_retention.py、capacity_session、reconcile_artifact_capacity | 旧生命周期 owner | 按根接管，C/剩余M03 | 新旧 owner 不同时管理对象；新 Store 不读取这些目录进行删除 |
| Candidate/Formal 旧 Schema、目录与政策 | 各原生生产链 | 执行/验证/保留/基线分轴，C | 只读历史保留原意；不能整体字符串替换 |

物性/单位的剩余活动消费者：

| 路径 | 当前来源与迁移边界 |
|---|---|
| components/single_reflection_oa_tof/reflectron_dual_stage_solver.py | 使用公共 LEGACY_OA_TOF_ATOMIC_MASS_CONSTANT_KG；B 先冻结旧版本，再单独评估数值升级 |
| backends/comsol/matlab/oatof_configure_particle_model.m、oatof_build_saved_particle_solution.m | 内嵌 u/kg、e/C 换算；B 随 OA/COMSOL 先复现后迁移 |
| backends/comsol/matlab/configure_oatof_segmented_output.m | 质量/电荷表达式；其中 segmented 为采样策略，不按名字自动当跨组件重发射删除 |
| components/dual_cone_tandem_quadrupole_ion_interface/config/ion_transport_science.json → backends/simion/resources/dual_cone_gas_assisted_transport.lua | SDS 气体质量/直径来自配置，Lua 不重复硬编码；B/C 从公共物性与研究环境生成，保留直径定义 |
| components/dual_pressure_rectilinear_ion_processor/config/baseline.json → gas_regions.py / backends/simion/resources/rf_ip_tracking_hs1.lua | 独立气体质量/HS1 截面，现有 placeholder 适用性不伪装已校准；B 迁移且不与 SDS 直径混同 |
| components/dual_cone_tandem_quadrupole_ion_interface/config/gas_flow_science.json → backends/comsol/matlab/build_and_solve_axisymmetric_gas_flow.m | SI 物性与 kB；C 按冻结值生成视图。backends/simion/gas_runtime.py 已复用公共 kB，不误报重复权威 |

下一批 B 的入口依次为 OA/SR-TOF 拆分、现有原生后端公共端口、自由 mass_scan、对应分段链退役；
C 处理剩余消费者/生命周期 owner/总等级/命名和文档收敛。两批均须另行启动，M06–M08 不混入。

### 必要门禁的首轮事实

原工作树的首轮 Changed 门禁使用显式 37 个本任务路径，排除开工已有 artifacts，
摘要位于外部 `architecture-a-gate.json`。完整普通 wheel + sdist 安装验收 PASS，2090.848 s；
machine_contracts 的另外两个分组 PASS（约 780/736 s），静态/文档/Ruff PASS。
总门禁仍为 FAIL：machine_contracts__tests_04 中仅旧 facade 夹具误选系统解释器；
修正后的同一方法已定向 PASS，不把失败的原调用改写成成功。
instrument_assembly 四个分组按首错策略 BLOCKED，尚需补跑；没有据此声称其通过。

末次物性/事件/存储变化仅影响新参考域及其安装资源；原生实现未变化。
`InstalledScientificCoreTests.verify_reference_delivery` 是显式窄验收入口，复用同一父方法的
wheel/sdist 构建、inventory、sdist 重建和相同参考探针，在昂贵旧夹具前选择实际受影响范围。
普通全量测试默认行为保留。窄入口另核验 HEAD/index/status/冻结输入字节、两臂 offline 源树与模块 origin，
子进程清除 PYTHONPATH 并使用隔离解释器。它不替代旧原生能力验收。
最终候选的该窄安装与尚未执行的装配范围将在候选提交后运行；目前未记作 PASS。

## 批次 A 最终验收

科学代码提交：`8ba6a4e91c86df8b68913b2209e12dc552363c4a`，基线为 `b94e0818a4823102425b6ad77327106b07143250`。
已将隔离候选快进接入本地 `task/architecture-migration-20261126`；原有未跟踪 artifacts 保持不动。
本节替代上一节“尚待运行”的状态；上一节保留首轮事实，不回写失败为通过。
最终文档提交仅补证据，不改变该科学代码与安装资源。

### 实际安装运行与复现

最终候选普通 wheel 和 sdist 重建 wheel 的显式窄验收 PASS：430.867 s（外层墙钟431.600 s），
两臂均运行公共 console 与 `python -I -m msplatform`、API、独立 E 解析 oracle、冷读和真实复用。
两棵源码树临时 offline，installed module origin PASS，冻结输入 3206 项，清单摘要
`85e1b47ed06c4a66bfd380d80fea08797ebe917a40c6c0f2d46234b3e5628731`，HEAD/index/status 对照通过。
命令为：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.contracts.test_installed_scientific_core.InstalledScientificCoreTests.verify_reference_delivery
```

另外用普通 wheel 在全新虚拟环境通过 pip 安装实际声明依赖（配套锁约束，无 editable、无源码路径注入），
保留了用户可直接运行的交付目录：
`C:\Users\Liao\msplatform-artifacts\architecture-a-delivery-8ba6a4e9`。
其中 `distribution/` 有 wheel、sdist 与锁，`env/` 为已安装环境，`study/` 保存原 TOML 及实际命令 JSON，
`store/` 为唯一 ArtifactStore 根。可复制运行：

```powershell
$delivery = 'C:\Users\Liao\msplatform-artifacts\architecture-a-delivery-8ba6a4e9'
$cli = Join-Path $delivery 'env\Scripts\msplatform.exe'
$recipe = Join-Path $delivery 'study\uniform_e.toml'
$store = Join-Path $delivery 'store'
& $cli --help
& $cli validate $recipe
& $cli run $recipe --artifact-root $store --source-revision 8ba6a4e91c86df8b68913b2209e12dc552363c4a
& $cli results inspect c9f03dc2ac9d44379918f1c5dde92738 --artifact-root $store
```

| 实际对象/唯一变化 | 结果 |
|---|---|
| 首次普通安装运行 `c9f03dc2ac9d44379918f1c5dde92738` | succeeded；完整母群1、终态1、检测1、101个float64采样 |
| 初态100 u/+e、vx=10000 m/s、E=(2000,0,0) V/m、B=0；x=0.01 m检测平面 | 事件时刻 `9.185857056658535e-7 s`；physical_outcome=detected、stop_reason=normal |
| 对独立匀加速闭式解，使用同一物理采样时刻 | 最大位置分量误差 `8.673617379884035e-18 m`；检测时刻误差 `1.1540919197546408e-16 s` |
| 同一输入第二个 run | field.reused=true；particle batch.reused=true |
| 通过已安装 CLI 执行 GC | 实际释放39,490字节合格缓存；不删除run科学证据 |
| GC 后运行 `9b5b03d63ce14fe8b4111bb2c120554a` | 场与批均MISS并真实重算成功；首次run再次冷读成功 |
| 缺件局部重算（两个完整独立粒子批的行为fixture） | 缺一批终态缓存文件后仅该批重算，另一批及场HIT；label不失效，物理输入变更失效 |

`study/first.json`、`reused.json`、`gc.json`、`rebuilt.json`、`retained.json` 是实际命令结果；
run 内冻结 author/resolved/provenance/execution/summary/manifest、三张 Parquet 和 HDF5。
GC 删除的是明确可回收的性能层，原结果自含科学证据；不是删除唯一载荷后补造结果。

### AC01–AC14 对账（仅批次 A 声明范围）

| AC | 证据与结论 |
|---|---|
| AC01 | 29意见表、唯一规范修订与B/C清单；原145/20/2及否决不改写，实施选择单列 |
| AC02 | 新CLI/端口统一tracing；6配方/6tracing测试与已安装能力预检，未知科学字段和不支持组合拒绝 |
| AC03 | assembly物理指纹、生成名、recipe_id、owner、label、run_id独立；重复运行新ID且科学缓存不受label影响 |
| AC04 | Decimal单位边界、分量容差、非零实验初时刻、公共常量冻结；无常量数值升级 |
| AC05 | 已安装physics/data资源实际加载；本轮真空/none/常量单源，六类旧消费者逐项列出 |
| AC06 | 4种独立闭式oracle与实际DOP853、重复磁场穿面；安装后E链另有实测误差，未宣称时变/RF验证 |
| AC07 | 发布后三表/HDF5冷读，母群闭合、权重独立、int64大ID大于2^53仍精确 |
| AC08 | 0命中/截断可成功，取消/真实溢出/受控solver失败/缺记录分别表达，诊断经序列化保留 |
| AC09 | 参考平面精确component/electrode/surface归属；未知native信息显式null/不可用，不从终点猜测 |
| AC10 | 15项storage验证包含共享必要引用、原子获取/删除竞争、发布/删除中断恢复、真实短进程死亡控制恢复 |
| AC11 | run占用也计软水位；软超限可继续，实际free不足先GC并保留queued原因，保护对象不删 |
| AC12 | 首/次运行、相关输入变更、label、缺件单批重算、真实GC后重算均有行为证据 |
| AC13 | 最终普通wheel/sdist窄验收与独立交付环境真实全链通过；软件门禁的旧基线失败另表保留，未冒充全仓PASS |
| AC14 | A已实现/验证范围与下列旧链正确性欠项、未实现能力、耗时优化分开；B/C和M06–M08未开展 |

### 软件门禁结果与旧链正确性欠项

| 检查 | 实际结果 | 范围/限制 |
|---|---|---|
| 最终针对测试 | 49 PASS，26.665 s | 单位、数值、数据、存储、依赖边界及旧解释器夹具定向修复；开发树验证 |
| 完整原普通安装验收 | PASS，2090.848 s | 首轮冻结源码；不冒充末次资源/字段修改后的证据 |
| 最终候选参考安装 | PASS，430.867 s | 普通wheel和sdist重建；只关闭受影响参考链 |
| 静态/文本字节/Ruff/文档 | PASS | staged标准、Owner前置和文档结构；不是商业或GUI资格 |
| Changed首轮 | FAIL，约2149 s | 单个旧测试强选base Python；修正后同方法定向PASS，原FAIL保留 |
| instrument_assembly Owner | FAIL，约697 s | 01/03/04分组PASS；02组193测试仅1个历史资产兼容ERROR |

Owner 唯一失败为
`tests.workflows.paired_accelerator.test_paired_accelerator_pulse_preparation.PairedPulsePreparationTests.test_actual_110745_all_100_states_use_original_235338_common_field`。
原因是历史 schema2 plan 的 `grounded_shield_id`、其他角色键及环ID列表与当前消费者硬取 `common_ground`
等键不兼容。这是实际旧链正确性缺陷，**不是性能项，也不是PASS**。
用独立 b94 checkout 和同一235338 manifest/plan只读调用即可重现；相关消费者与基线字节完全一致，
故不归因于A参考实现。按本轮不混入B的边界，保留为B的明确入口；不能修改旧manifest使其通过。

可复制只读基线复现（运行后退出1并报告common_ground，无模拟/无产物写入）：

```powershell
$env:PYTHONPATH='C:\Users\Liao\mass_spectrometry\.tools\p4-composed-candidate-r1\src'
Set-Location 'C:\Users\Liao\mass_spectrometry\.tools\p4-composed-candidate-r1'
& 'C:\Users\Liao\mass_spectrometry\simulation_repo\.venv\Scripts\python.exe' -c "import json; from pathlib import Path; from msplatform.backends.comsol.paired_static_model import load_paired_static_model_source; p=Path(r'C:\Users\Liao\mass_spectrometry\artifacts\projects\instrument_assembly\runs\20261025_235338__sim__cross__paired-accelerator-static-field'); plan=json.loads((p/'inputs/bvp/paired_accelerator_static_field_plan.json').read_text(encoding='utf-8-sig')); print(__import__('msplatform.backends.comsol.paired_static_model',fromlist=['']).__file__); load_paired_static_model_source(p/'run_manifest.json',p/'run_manifest.json',expected_plan=plan)"
```

该历史 manifest SHA256=`10862ABF99C5D20A094E6FE40277D81D115059153F4FCE9D6E3DECAC1EAECE83`，
plan=`26EDF6019898507E5A74C3792AF465FB3096816893F07AF1D70D2336E13EA49D`；
`backends/comsol/paired_static_model.py` 文件SHA256=`078DA8AFE33EBD263101A5AB72D3B4E6A6DE55B707430069794EC6C94B70D9B4`，
`workflows/paired_accelerator_pulse/prepare.py`=`80841BDBC0050964F670805E342BBF71F117D860D3955D2321C219036A9CCC12`，当前与b94一致。
修复入口是明确版本/形状的只读映射、环列表及电压/几何语义校验和最小行为fixture，不重写原科学历史。

未实现/未验证：真实仪器组件迁移、SIMION/COMSOL新端口、RF时变、自洽、真实birth/次级生成、
native内部checkpoint、完整索引重建、后台自动派发、全3D/AMR/丰富可视化。它们不被本轮参考链证明。
耗时优化：原完整安装约35分钟、窄参考安装约7分钟、Owner约12分钟，均未作为科学或软件PASS替代。
未为追求理想时间重跑完整回归或大型模拟；只有实际受影响的安装范围和原先BLOCKED范围补验。

提交后在原工作树对同一49项重新核验 PASS，23.256 s，使用当前已安装开发环境，无源码路径注入。
该次绑定已接入的8ba代码，覆盖最终junction测试的明确cwd/timeout。它是小型针对性核验，不是全仓回归。

临时隔离 checkout 已确认路径和干净状态后经 `git worktree remove` 删除，移除文件逻辑大小
221,673,169字节（约211MiB），可从8ba提交完整重建。开工已有 artifacts、基线checkout及历史manifest未动。
成功安装验收的临时环境由既有验收框架清理；两次失败门禁的诊断保留用于B旧链复核。
独立交付环境、发行文件、真实run证据与早期小型开发诊断保留在Git树外；不删除必要科学结果。

### CLOC 明细

CLOC 2.10，基线 b94e0818a4823102425b6ad77327106b07143250 → 代码提交 8ba6a4e91c86df8b68913b2209e12dc552363c4a。最终证据文档不改变以下代码计数。

命令：tools/repository/report_cloc_delta.ps1 -Base b94e0818a4823102425b6ad77327106b07143250 -Current 8ba6a4e91c86df8b68913b2209e12dc552363c4a -ClocExe <workspace>/.tools/cloc/2.10/cloc.exe。首次本机Perl locale不支持C.UTF-8，改用LC_ALL/LC_CTYPE/LANG=C后原工具通过，未替换计数口径。

每格：baseline → result (delta)。未分类为0，无静默归类。

| Scope | Language | Files | Blank | Comment | Code |
|---|---|---:|---:|---:|---:|
| total | JSON | 281 → 282 (1) | 0 → 0 (0) | 0 → 0 (0) | 125984 → 126022 (38) |
| total | Lua | 119 → 119 (0) | 413 → 413 (0) | 828 → 828 (0) | 13219 → 13219 (0) |
| total | MATLAB | 186 → 186 (0) | 1066 → 1066 (0) | 2053 → 2053 (0) | 19701 → 19701 (0) |
| total | PowerShell | 150 → 150 (0) | 1100 → 1100 (0) | 1195 → 1195 (0) | 46113 → 46113 (0) |
| total | Python | 1419 → 1435 (16) | 32657 → 32905 (248) | 42260 → 42461 (201) | 394041 → 396011 (1970) |
| total | SIMION GEM | 10 → 10 (0) | 26 → 26 (0) | 51 → 51 (0) | 214 → 214 (0) |
| total | TOML | 1 → 5 (4) | 10 → 43 (33) | 2 → 2 (0) | 58 → 219 (161) |
| total | YAML | 2 → 2 (0) | 8 → 8 (0) | 20 → 20 (0) | 506 → 506 (0) |
| total | SUM | 2168 → 2189 (21) | 35280 → 35561 (281) | 46409 → 46610 (201) | 599836 → 602005 (2169) |
| production | JSON | 258 → 259 (1) | 0 → 0 (0) | 0 → 0 (0) | 42302 → 42340 (38) |
| production | Lua | 99 → 99 (0) | 333 → 333 (0) | 703 → 703 (0) | 11141 → 11141 (0) |
| production | MATLAB | 118 → 118 (0) | 526 → 526 (0) | 1462 → 1462 (0) | 12164 → 12164 (0) |
| production | PowerShell | 138 → 138 (0) | 1037 → 1037 (0) | 1149 → 1149 (0) | 44012 → 44012 (0) |
| production | Python | 673 → 685 (12) | 16622 → 16796 (174) | 11480 → 11588 (108) | 181604 → 182893 (1289) |
| production | SIMION GEM | 10 → 10 (0) | 26 → 26 (0) | 51 → 51 (0) | 214 → 214 (0) |
| production | TOML | 1 → 5 (4) | 10 → 43 (33) | 2 → 2 (0) | 58 → 219 (161) |
| production | YAML | 2 → 2 (0) | 8 → 8 (0) | 20 → 20 (0) | 506 → 506 (0) |
| production | SUM | 1299 → 1316 (17) | 18562 → 18769 (207) | 14867 → 14975 (108) | 292001 → 293489 (1488) |
| tests | JSON | 23 → 23 (0) | 0 → 0 (0) | 0 → 0 (0) | 83682 → 83682 (0) |
| tests | Lua | 20 → 20 (0) | 80 → 80 (0) | 125 → 125 (0) | 2078 → 2078 (0) |
| tests | MATLAB | 68 → 68 (0) | 540 → 540 (0) | 591 → 591 (0) | 7537 → 7537 (0) |
| tests | PowerShell | 12 → 12 (0) | 63 → 63 (0) | 46 → 46 (0) | 2101 → 2101 (0) |
| tests | Python | 746 → 750 (4) | 16035 → 16109 (74) | 30780 → 30873 (93) | 212437 → 213118 (681) |
| tests | SUM | 869 → 873 (4) | 16718 → 16792 (74) | 31542 → 31635 (93) | 307835 → 308516 (681) |

完整过滤口径（由原工具报告，以下仅格式化其数值，未自行计行）：

```text
FILTER=extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|tests_boundary/*_fixtures.py|tests/**/__init__.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked
```


## B 前收尾（2026-11-26，本轮不启动 B）

对照交付 `dad49d1c9049a5c3ba349003af4998d50ec9082e`；开工 HEAD 与此相同，分支
`task/architecture-migration-20261126` 跟踪同名 origin 分支，无后续提交。
原有未跟踪 `artifacts/` 保留；开工时要求不改历史研究资产、不合并、不推送（后续推送授权见最终交付）。本节是本轮接续入口，
上文 A/P4 的原始结果保持原义，不能把本轮定向复验外推成 Owner/P4 全门禁通过。

### 1. 计算写入者失联

已完成：`storage/store.py:run_writer/recover_interrupted_runs` 使用原 OS 文件锁机制，
`reference_tracing.run_recipe` 从 running 前到发布/异常收尾持锁。只有取得原随机 token 锁且
尚无 publishing/ready 记录的 running 才变为 failed，原因明确为 writer interrupted before publication。
原 ID、冻结输入、部分 work 字节保留，`run_status.work_path` 可查询；不生成终态、不发布成功缓存。
无 token 的旧 running 保守保留待调查。claim/预留经原 recover_controls 释放；活 writer、已发布结果不变。
已校验的 publishing 恢复可消除此前发布 I/O 异常留下的 failed 状态，以 manifest 的真实状态收尾。

验证：`.venv/Scripts/python.exe -m unittest tests.contracts.test_artifact_store -q`，17 项 PASS（3.735 s）；
真实 spawn 短子进程在写入后/发布前被 terminate，死/活 writer 对照、清单及 SHA-256 不变、无捏造终态、
精确控制释放、再次 reserve、ready 不回退、二次恢复无变化及原 publishing 恢复均通过。
`.venv/Scripts/python.exe -m unittest tests.contracts.test_reference_workflow -v`，5 项 PASS（5.657 s）；
正常发布/失败/取消、queued 准入失败、复用、GC、缺件局部重算接线仍通过。
Store 两个改动文件 Ruff PASS。测试临时根自动清理；未触碰真实研究产物。

剩余旧消费者仍为上文旧 owner/原生链清单，本轮只接入 reference_tracing；
下一步处理同一次运行的 TOML 单次读取，再处理有证据支持的旧资产读取边界。


### 2. 作者配方单次读取

第 1 项代码/证据已提交 `c656c647`。本单元在现有 `recipes.reference.load_recipe(path)` 中单次
`read_bytes`，用该快照解析十进制 TOML，返回 SimulationRecipe.source_bytes；resolved-only 构造没有来源快照。
`reference_tracing.run_recipe` 用该份字节归档，provenance 哈希来自这份冻结文件，不再重读外部作者路径。
科学身份仍来自原 resolved 投影，来源字节不进入 task key；label-only 仍命中科学缓存。

`.venv/Scripts/python.exe -m unittest tests.contracts.test_reference_recipe tests.contracts.test_reference_workflow -v`：
12 项 PASS（6.794 s），其中可控 read_bytes hook 在首次外部读取后将 E 从 2000 改为 4000 V/m，
确认首次只读一次且计算/归档/来源 SHA 全为旧值；下一次运行才使用新值。
两次轨迹事件均由独立匀加速公式核对（位置误差 <1e-10 m），后次实际更早到达，场缓存正确失效。
Ruff 四个改动 Python 文件 PASS，diff --check PASS。
已增强原安装验收的参考片段，核对 installed CLI 的 author/resolved/provenance 与来源字节，
并输出数值误差；直接 wheel 和 sdist 重建 wheel 的离仓验收留到第 3 项之后、同一最终代码提交运行。

剩余旧消费者与上文清单相同；下一步只做已取证的历史 common_ground 读取边界修复，不启动 B。


### 3. 历史 common_ground：已修并复验

第 2 项代码/证据提交 `55144d39`。旧基线的 KeyError 仍是原始失败事实；本轮新增的技术选择是：
仅在 `backends/comsol/paired_static_model.py` 的旧资产读取边界，按嵌套 composition plan 3
解释六键 renderer 绑定，现行 plan 5 保持规范角色；外层 plan 2 本身不能区分格式。
映射依据为现有 `backends/simion/tof_electrode_mapping.py` 的版本化前端协议与冻结 electrical ON 表，
grid2 明确为 exit grid，不是第二中间网格。仅适用 three_zone_square 的 OA-only 域，
不宣称整个装配 ground 等价，不支持无证据的 plan 4。

源 plan 和 export consumer plan 即使无 expected_plan 也校验：五角色、接地、环 ID 顺序/长度、
唯一正整数、完整有限电压与冻结 electrical 严格一致。缺字段、新旧混合、角色冲突、环列表不匹配、
未知版本均拒绝。新 writer 未增加旧格式，不改历史 manifest，不放宽物理校验，不恢复旧生产框架。

5 项定向测试 PASS（7.447 s）：新旧等价/拒绝夹具、原 saved-model BVP 测试、
`PairedPulsePreparationTests.test_actual_110745_all_100_states_use_original_235338_common_field`、
export-only 及平铺来源漂移。原失败方法现通过，100 个原始状态完整绑定原 235338 公共场；
测试禁止读取 MPH/PA，未运行 COMSOL/SIMION。改动文件 Ruff 和 diff --check PASS。
历史小证据复验 SHA-256 未变：235338 manifest
`10862ABF99C5D20A094E6FE40277D81D115059153F4FCE9D6E3DECAC1EAECE83`，plan
`26EDF6019898507E5A74C3792AF465FB3096816893F07AF1D70D2336E13EA49D`。

原 Owner-02 失败报告保留，本轮定向通过不能改写为完整 Owner 门禁通过。
剩余 P4 与旧消费者仍按原清单；B 前不再受该已复现 KeyError 阻塞。
下一步仅在固定最终代码提交运行两发行离仓参考链，再登记结果与 CLOC。


### 4. 最终代码与离仓交付

最终代码提交 `991feedb805fc8278394fc5cc036983c162601cf`，此前两个独立修复提交为
`c656c647`、`55144d39`。随后用户明确授权“从现在开始远端一直保持和本地一致”；
三个修复提交已普通推送到同名 origin 任务分支，远端 SHA 与本地代码 SHA 相同。
本节为后续纯证据文档提交，不改变通过验收的代码；完成后同样普通推送。
未合并 master、未改写远端历史。开工与验收结束的已有未跟踪 `artifacts/` 保持不动。

| 验证 | 结果 | 判据与范围 |
|---|---|---|
| Store | 17 PASS，3.735 s | 真实强杀、活进程、ready、控制释放、重复恢复、publishing 恢复 |
| 配方/参考 workflow | 12 PASS，6.794 s | 单次外部读取、突变后当前/下次隔离、独立匀加速 oracle、原正反例 |
| 历史 OA reader | 5 PASS，7.447 s | 新旧等价/拒绝、原 110745/235338 方法、saved model/export/flat provenance |
| 最终两发行离仓参考验收 | PASS，346.964 s | 同一代码提交的直接 wheel、sdist 重建 wheel；普通安装，非 editable |
| Ruff / staged 开发标准 / diff --check | PASS | 实际改动范围；不代替完整 Owner/P4 或科学资格 |

直接 wheel run `bf126413427e49b096e094c68ed4b397`；sdist 重建 wheel run
`f0855480c289496b80c020bcaac2b15e`。两臂均 N=1、detected=1、101 样本，succeeded + complete，
公共 CLI 冷读统计一致、第二次运行场和批次实际复用，author/resolved/provenance 对账通过。
共同作者 SHA-256 为 `D8CC1F3B06C0F394D04D110591AB806166176E6904953584406A010CEF97CD1F`。
事件时间均 `9.185857056658535e-7 s`；独立匀加速解析解事件误差 `1.1540919197546408e-16 s`，
轨迹最大位置误差 `8.673617379884035e-18 m`（既有判据分别 <5e-15 s、<1e-10 m，未放宽）。
源树离线、已安装模块 origin、清除 PYTHONPATH/PYTHONHOME、隔离解释器均通过；
HEAD/index/status 和 3206 文件清单不变，清单 SHA-256
`d94593eec2bd34a7d60b4f7c0ba8daa33eb8b7d99bd6bfb5f23b0fbf6eec1003`。

实际运行的复现入口（仓库根、锁定环境；安装验收内部在仓库外执行公共 CLI/API）：

```powershell
.venv/Scripts/python.exe -m unittest tests.contracts.test_artifact_store -q
.venv/Scripts/python.exe -m unittest tests.contracts.test_reference_recipe tests.contracts.test_reference_workflow -v
$readerTests = @(
  'tests.workflows.paired_accelerator.test_paired_accelerator_static_field_execute.PairedStaticExecutionTests.test_versioned_oa_voltage_projection_rejects_ambiguous_inputs',
  'tests.workflows.paired_accelerator.test_paired_accelerator_static_field_execute.PairedStaticExecutionTests.test_saved_solution_requires_bound_completion_bvp_and_backend',
  'tests.workflows.paired_accelerator.test_paired_accelerator_pulse_preparation.PairedPulsePreparationTests.test_actual_110745_all_100_states_use_original_235338_common_field',
  'tests.workflows.paired_accelerator.test_paired_accelerator_pulse_preparation.PairedPulsePreparationTests.test_export_only_source_flattens_original_model_and_binds_own_simion_plan',
  'tests.workflows.paired_accelerator.test_paired_accelerator_pulse_preparation.PairedPulsePreparationTests.test_export_source_rejects_bvp_or_flat_origin_drift'
)
.venv/Scripts/python.exe -m unittest @readerTests -v
.venv/Scripts/python.exe -m unittest tests.contracts.test_installed_scientific_core.InstalledScientificCoreTests.verify_reference_delivery -v
```

测试保留证据位于主机 Git 树外 `msplatform-artifacts/architecture-a-closeout-20261126/`：
`991feedb-installed.log`、`991feedb-cloc.log`、`991feedb-verification.json` 和
`991feedb-acceptance/acceptance.json`（含来源清单与三个发行文件摘要）。
临时安装工作区 `installed-scientific-core-yxmty_pg` 已由测试正常清理，可由上述入口重建；
释放字节数未测量。此前 A 独立交付环境及真实研究产物未清理。

本轮第 1、2 项验收完成，第 3 项为**已修并复验**。未执行完整 Changed/Owner/Repository/P4，
未重跑无关门禁、大型模拟、商业求解、GUI/CAD或 Formal 验证；原失败记录与其他 P4 残项保留。
剩余旧消费者和 B/C 入口仍见上文“活动旧消费者与退役入口”，M06–M08 未开始。
本轮三项没有未决实施选择；B 开工仍须另行授权，沿执行包既定默认方案和上述真实消费者清单推进。
若 B 将引入 queued 重新派发或原生后代执行，须在那个边界先处理相应合同：
当前 writer 登记后、mark_running 前被杀仍属 queued，旧 writer 行不会被本恢复入口清理并续用；
没有 writer token 的历史 running 也不能据 PID/超时自动判死。原生消费者须各自持权，
不能外推当前同步参考进程的锁保护。`recover_publications` 仍要求管理员确认 writer 停止并独占操作。

### 本轮 CLOC 对账

CLOC 2.10：`dad49d1c9049a5c3ba349003af4998d50ec9082e` →
`991feedb805fc8278394fc5cc036983c162601cf`。证据文档提交只改 Markdown，代码计数不变。
实际命令（LC_ALL/LC_CTYPE/LANG=C）：

```powershell
tools/repository/report_cloc_delta.ps1 -Base dad49d1c9049a5c3ba349003af4998d50ec9082e -Current 991feedb805fc8278394fc5cc036983c162601cf -ClocExe <workspace>/.tools/cloc/2.10/cloc.exe
```

原工具 CLOC_DELTA=PASS；未分类 0。每格为 baseline → result (delta)，数值直接格式化自原工具，不另行计行。

| Scope | Language | Files | Blank | Comment | Code |
|---|---|---:|---:|---:|---:|
| total | JSON | 282 → 282 (0) | 0 → 0 (0) | 0 → 0 (0) | 126022 → 126022 (0) |
| total | Lua | 119 → 119 (0) | 413 → 413 (0) | 828 → 828 (0) | 13219 → 13219 (0) |
| total | MATLAB | 186 → 186 (0) | 1066 → 1066 (0) | 2053 → 2053 (0) | 19701 → 19701 (0) |
| total | PowerShell | 150 → 150 (0) | 1100 → 1100 (0) | 1195 → 1195 (0) | 46113 → 46113 (0) |
| total | Python | 1435 → 1435 (0) | 32905 → 32921 (16) | 42461 → 42493 (32) | 396011 → 396258 (247) |
| total | SIMION GEM | 10 → 10 (0) | 26 → 26 (0) | 51 → 51 (0) | 214 → 214 (0) |
| total | TOML | 5 → 5 (0) | 43 → 43 (0) | 2 → 2 (0) | 219 → 219 (0) |
| total | YAML | 2 → 2 (0) | 8 → 8 (0) | 20 → 20 (0) | 506 → 506 (0) |
| total | SUM | 2189 → 2189 (0) | 35561 → 35577 (16) | 46610 → 46642 (32) | 602005 → 602252 (247) |
| production | JSON | 259 → 259 (0) | 0 → 0 (0) | 0 → 0 (0) | 42340 → 42340 (0) |
| production | Lua | 99 → 99 (0) | 333 → 333 (0) | 703 → 703 (0) | 11141 → 11141 (0) |
| production | MATLAB | 118 → 118 (0) | 526 → 526 (0) | 1462 → 1462 (0) | 12164 → 12164 (0) |
| production | PowerShell | 138 → 138 (0) | 1037 → 1037 (0) | 1149 → 1149 (0) | 44012 → 44012 (0) |
| production | Python | 685 → 685 (0) | 16796 → 16804 (8) | 11588 → 11609 (21) | 182893 → 182981 (88) |
| production | SIMION GEM | 10 → 10 (0) | 26 → 26 (0) | 51 → 51 (0) | 214 → 214 (0) |
| production | TOML | 5 → 5 (0) | 43 → 43 (0) | 2 → 2 (0) | 219 → 219 (0) |
| production | YAML | 2 → 2 (0) | 8 → 8 (0) | 20 → 20 (0) | 506 → 506 (0) |
| production | SUM | 1316 → 1316 (0) | 18769 → 18777 (8) | 14975 → 14996 (21) | 293489 → 293577 (88) |
| tests | JSON | 23 → 23 (0) | 0 → 0 (0) | 0 → 0 (0) | 83682 → 83682 (0) |
| tests | Lua | 20 → 20 (0) | 80 → 80 (0) | 125 → 125 (0) | 2078 → 2078 (0) |
| tests | MATLAB | 68 → 68 (0) | 540 → 540 (0) | 591 → 591 (0) | 7537 → 7537 (0) |
| tests | PowerShell | 12 → 12 (0) | 63 → 63 (0) | 46 → 46 (0) | 2101 → 2101 (0) |
| tests | Python | 750 → 750 (0) | 16109 → 16117 (8) | 30873 → 30884 (11) | 213118 → 213277 (159) |
| tests | SUM | 873 → 873 (0) | 16792 → 16800 (8) | 31635 → 31646 (11) | 308516 → 308675 (159) |

完整过滤口径：

```text
FILTER=extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|tests_boundary/*_fixtures.py|tests/**/__init__.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked
```


## 批次 B（2026-11-27）：B0–B6 同一 Goal 连续实施

### 开工与输入

用户明确启动批次 B。开工 HEAD `a9d76aa4dcdbaf8099c9ce5aa0585d6fce18c3be` 与 B 执行包审计一致，
无相关后续增量；任务分支 `task/architecture-migration-20261126` 跟踪同名 origin，远端同步授权继续。
只有原有未跟踪 `artifacts/`，保留不动。禁止 reset、主线合并和历史改写。

已按顺序读取外部 `ms_phase_b_execution_20261126/start_agent_B.md`、acceptance_report_A.md、
implementation_plan_B.md、verification_evidence.json，再读 goal_prompt_B.md；证据索引全部文件大小/哈希核对通过。
只创建一个 active Goal：完整 goal_prompt_B 原文加完整计划路径绑定；工具目标字段最多4000字符，
15181字符的完整计划不能直接拼入目标字段，已全文读取且 B0–B6/BA01–BA15 全范围适用，不削减任务。
Goal与执行提示词是同一项工作；不只完成B0就结束，不自动加入C/M06–M08。

| 外部输入 | SHA-256 |
|---|---|
| start_agent_B.md | 6dff4ab3eea14aa574dc8372178ea47401ddc7e72fa3ce7f4df187bdeabc3664 |
| goal_prompt_B.md | 19a71f5ddbecc040f3da92fc6067f0e2ad7370db77818607a715b175b8235733 |
| implementation_plan_B.md | 102488c5782cde85e0068b0851e76ed77c4072185d3693565085519bffc6ddb7 |
| acceptance_report_A.md | 62d592da32ed98fbc9885125ffdf129d04555ef32235f35ac62e49c24f579fb8 |
| verification_evidence.json | d16c619816445cea65e2b8a6d03e73451abcf762a250a2de05c0f065732ba62b |

A独立审计的37 unittest/36 PASS/1 Linux junction SKIP及四个B0反例是输入事实，不能当本轮修复PASS。
原三项A收尾已经解决，不重新立项；原评阅状态与本轮技术选择分别保留。

Agent 0：Goal、公共合同/CLI/workflow整合、迁移记录、Git串行与最终验收；
Agent 1：B0电荷/共面终止面；Agent 2：B0干净构建说明；Agent 3：B0存储；
Agent 4：只读B2/原生移植闭包。共同文件均明确唯一写入者；原生资源执行统一协调。

### B0-03：失败 GC 候选不阻塞后续准入

已实现 `storage/store.py:collect` 单次pass冻结候选身份，每个候选最多尝试一次；pending优先，
ready转pending仍在短事务复核pin/claim/必要引用。失败保留delete_pending与原因、不虚计释放、继续其他候选。
`reserve` 继续在回收后重读实际free决定准入；没有新GC或账本。

`.venv/Scripts/python.exe -m unittest tests.contracts.test_artifact_store -q`：19 PASS（4.584 s）。
新增可控 A删除失败/B足量成功后准入、pin/claim保护、全部失败每轮只尝试一次且零释放。
free是受控观测（0→6 B，准入需求5 B），不是对真实卷释放量的测量。原writer/publishing恢复仍通过。
对应两文件Ruff PASS。临时夹具自动清理，没有删除真实研究数据。

剩余：B0-01/02/04正在独立实施；之后立即进入B1公共合同、B2拆分/B3场源、B4原生链、B5 mass_scan、
B6旧执行退役/交付。当前旧消费者清单仍见上文，不声称B或BA01完成。CLOC将在该主题提交后按实际SHA核对。


### B0-01/02：电荷精确表示归一和共面竞争

已复核 `physics.normalize_charge_c`：保留既有binary64整数×e规范值和科学身份，精确接受该表示或
同一冻结十进制常量精确相乘后一次舍入的表示，不采用通用ULP窗口/相对容差。
±3的作者辅助charge_c=±4.806529902e-19 C归一到旧规范值±4.806529901999999e-19 C；
常量数值未升级，真实矛盾拒绝。author/resolved/tracer使用同一函数，实际输出初态采用规范值。

`tracing.preflight` 拒绝相同axis/精确位置的竞争终止面，与声明顺序无关；共面observation合法。
求解前将非终止observation排在terminal前，确保同根处的合法观测不会被终止截掉，两种作者顺序均验证。
不扩展为任意三维角点/切触算法改写；CLI validate/run均在昂贵执行前走同一预检。

`.venv/Scripts/python.exe -m unittest tests.contracts.test_reference_recipe tests.contracts.test_reference_tracing tests.contracts.test_reference_workflow -v`：
20 PASS；±1/±3的author/resolved/tracer/output，真实矛盾、竞争两顺序、合法观测两顺序及原参考闭环均通过。
Ruff与diff --check PASS。初版测试曾误认为terminal具有charge_c而得到4个KeyError，已按实际合同
核对initial电荷与终态一致性后通过，初版错误不作为生产失败或PASS。旧审计探针只作观察，不代替回归。
tracer实现摘要改变已进入现有批缓存键；物理规范值和版本化常量保持不变。

B0-03已提交/推送 `0873971a`；B0-04干净构建正在验证独立backend进程的可靠命令，尚未计通过。
下一步立即推进B1的既有Study/Assembly接线；B2只读闭包已确认OA本来只复用一次，不能重写第三套OA。


### B0-04：干净构建说明已验证；B0退出

`docs/TRACING.md` 改为固定已提交快照的git archive、干净Python3.11 venv、pyproject声明的
setuptools65.5.0/wheel0.38.4，并分别在两个独立Python backend进程构建wheel和sdist。
不再假定锁文件安装了build frontend。固定源 `a9d76aa4` 干净构建PASS：wheel5706249 B、
sdist4851908 B；主机小证据 `.tools/b0-04-build-evidence-20261127/build-evidence.json` 含来源/版本/摘要。
初次同进程连续调用退出0却将sdist写入source/bdist_wheel，已纠正文档并用全新快照重验；
初次部分构建不作为PASS。此项仅构建可复制性验证，不冒充本轮最终安装/native验收。

自动批准审查拒绝递归清理本次临时目录 `msplatform-b0-04-997974f7bbbc433abe14f3264bc55430`，
仅报告blocked by policy，无更具体原因；没有重试或换方式绕过。约1081448135 B逻辑文件仍保留，
未声称释放；都是本次可重建源码/venv/发行产物，不涉及既有研究数据。清理限制不是B原生资格PASS。

B0-01/02已提交/推送 `f0febc9e`；四项B0现在闭合，BA01只声明其实际验收范围。
B1共同合同沿现有StudyDefinition(component_requests/recipe/drive/physics/release/numerics)、
components.resolve_component和assembly.assemble，不另造第二Study/Assembly或CLI。
同一load_recipe将以版本化native作者配置绑定完整自包含Study JSON的path+SHA，单次读字节、冻结/归档依赖；
运行时不重读可变科学源。预检区分实现/主机/证据，不以parse成功代替native支持。

B2取证已确认实际仪器OA开口与standalone第一隙约束不同，必须由OA owner表达受验证的仪器机械输入；
OA↔下游连接须由真实端面/开口和位姿推导验证，不能伪造port、空连接或按同电位合并ground身份。
剩余旧消费者与原清单一致，B1–B6/BA02–BA15均在推进、尚未验收；下一步公共配方和独立组件合同。


### B1/B2 首个实体单元：版本化包含关系与真正下游 provider

已实现 `assembly/containment.py`、recipe2/plan6和interface4；旧recipe1/plan3–5、interface1–3原义保留。
ports为空只用于没有实际机械对接面的新接口；显式containment把实际成员AABB经刚体变换核验到
provider派生圆柱包络内，检查关系唯一/无环/连通和scope边界，不伪造端口/接触面。
`assembly/electrode_binding.py` 已允许group身份相同的interface3/4，仍以instance+group为唯一科学键，
OA ground与下游ground不合并。包络只证明包含，不表示无障碍、joint field正确或native资格。

独立 `components/single_reflection_tof` 只拥有飞管、双级reflectron与detector的真实下游输入；
下游公式从旧geometry_contract真实提取，旧复合reader委托同一owner，未复制第二套活跃物理公式。
OA仪器机械输入复用已存在的受版本/producer/壁开口校验的instrument投影，原standalone第一隙校验未放宽。
source→resolved→interface独立重算，伪造bounds拒绝。registry/依赖图/source_closure已同步。

独立oracle来自 `d55198ff7b4387ba54807906a23b96cd2c5bcb88` 的原geometry_contract源码，
源SHA256 `0b28054be43cd0b98feacfa01efd3c7b136873654a89bb641975c7d553c091c6`，
冻结于 `tests/contracts/fixtures/split_tof_legacy_projection.json`，非新实现自比。
45条电极完整属性/电压、detector面及局部范围逐值相等。原已有detector/OA屏蔽重叠
在点 `[58,0,-0.5] mm` 精确查询均interior；保持原几何，限制已写新组件PROJECT，未宣称无碰撞。

最终本单元命令：`.venv/Scripts/python.exe -m unittest tests.contracts.test_split_tof_provider
 tests.assembly.test_containment_layout tests.contracts.test_geometry_members
 tests.components.single_reflection_oa_tof_mass_analyzer.analysis.test_installed_geometry_provider
 tests.components.orthogonal_accelerator.analysis.test_bare_three_zone_component -q`：30 PASS（4.405 s）。
原assembly22项先前PASS；独立5项containment含变换/负例/版本隔离/电极scope。
对应生产/测试Ruff PASS。Agent5只读复核发现的v4电极绑定缺口和原同实现自比夹具均已修复。
B1配方/结果/native保护桥仍为未提交的独立单元，不把它们夹进本主题；真正compiler/source/drive/native
消费者闭包和BA03/04整体验收尚未结束。

主机工具预检：首次未提供Python选择而启动拒绝（不是工具/物理失败）；随后
`$env:SIMULATION_PYTHON_EXE=(Resolve-Path .venv/Scripts/python.exe).Path;
 pwsh -NoProfile -File tools/repository/verify_toolchain.ps1 -SkipSolidWorksProbe`
PASS，实际MATLAB R2025b探测True；SolidWorks文件基线检查、COM运行探测SKIPPED，未做CAD/GUI资格。
后续COMSOL仍须正式6.4/R2025b launcher与实际资源准入。

剩余：SIMION完整frontend/prepared/track正在迁移，三格native均未验证；COMSOL既有全仪器CPT为static ON，
OA-only gate不可套整仪器关掉常开反射场。新路径必须同模型保存OFF/ON两解，再组合背景+OA脉冲差场；
不能把独立MPH的withsol引用误当共同解，也不能用reader fixture冒充原生完成。B4实际host与Store prelaunch
接线、B5 mass_scan、B6旧执行退役继续，不停止Goal。


### B4 结果格式单元：原生出生与旧初态快照分开

`results/model.py:TraceResult` 成为同一 solver-neutral 结果对象；`tracing.TraceResult` 保持同一公开对象。
`results/particle_data.py` 增加显式 schema2/native_birth_verified，初态 primary_birth 与 schema1 的
unavailable_initial_snapshot 分离；没有把旧快照升级成出生证据。Parquet/HDF5/execution 的版本、frame、
clock、出生依据交叉核验；次级谱系仍明确不支持。真实出生须由各 native adapter 从实际初始化记录核验，
reader fixture 的显式标记不是原生资格。

定向命令 `.venv/Scripts/python.exe -m unittest tests.contracts.test_native_particle_data
 tests.contracts.test_reference_workflow tests.contracts.test_reference_tracing tests.contracts.test_native_recipe
 tests.contracts.test_reference_recipe -q`：27 PASS（10.717 s），包括合成schema2读写/篡改负例及原参考链。
本次结果主题只提交结果对象/格式、原公开重导出和相应边界声明；配方/后端/保护桥继续独立实施。
B3/4三格原生仍未执行，不把格式往返计为BA08。下一步接实际源/终态与同一公共CLI。

Agent3已修复尚未提交的native完成回执过早删除活holder控制问题，继续真实process-owner prelaunch绑定。
其临时测试目录 `C:/Users/Liao/AppData/Local/Temp/tmphou0uqsj` 清理同样被自动批准审查拒绝，仅有blocked
by policy，已停止重试；未声称释放容量。保留已知窗口的保守保护，不用裸PID/超时自动释放。


### B1 配方冻结单元

结果格式主题已提交/推送 `19c2d0ce`。`recipes/reference.py:load_recipe` 同一入口新增schema2 native作者配置，
`recipes/native.py` 只读一次显式path+SHA绑定的完整Study JSON；resolved内嵌原字节和来源哈希，并冻结小型clock/epoch资源。
validate仅从冻结bytes重编译现有components.resolve_component/assembly.assemble，不重读可变科学源。
assembly可读名由同一assembly_name生成器生成，名称、内容assembly_id和recipe_id分别表达；作者label/来源路径不入科学身份。
常量版本与vacuum在作者输入显式选择，resolved冻结public constants/gas dataset；不支持旧常量隐式升级、碰撞或自洽。
COMSOL数值采用其真实CPT控制maximum_step_us/relative_tolerance/absolute_tolerance，非把采样输出间隔冒作积分步长。

定向 `.venv/Scripts/python.exe -m unittest tests.contracts.test_native_recipe tests.contracts.test_reference_recipe -q`，
以及对应Ruff通过；此前结果/配方/reference联合27项PASS（10.717s），加入公共入口声明后boundary等27项PASS（18.904s）。
测试覆盖外部Study一次读取/变更后本run不变、SHA/冻结内容篡改拒绝、label/path身份稳定、缺显式数值/clock/源拒绝。
这里只交付解析冻结，不把parse成功当native支持；公共capability报告、真正运行、三组合新证据仍在整合。

旧消费者：原复合OA–TOF公开native入口的跨组件HandoffResult/state_relaunch/segmented_upstream仍需合并本轮守卫；
IP–MR及其他C链的合法续传和历史reader不全局禁用。下一步合并独立编译、实际birth源示例及同一CLI执行。


### B2/B3/B4 SIMION 软件消费者闭包与原始出生

配方冻结主题已提交/推送 `1d12e480`。分体模型现在由 `backends/simion/split_compiler.py` 编译，
`operations.build_geometry/prepare_model/solve_fields` 复用既有owner，`fields/native_plans/field_execution`
按真实独立OA/RF/TOF实例准备carrier_off、可选rf_reference和pulse_delta；同一parent域中的真实电极见证、
下游3PA优先级/电压/探测器面保持。原parent域z_max的5.7e-14 mm舍入差采用既有32ULP边界规则，
原118×76×3201网格不变，实际缩域0.1mm仍拒绝。包络及准备通过不是joint场/无碰撞资格。

`tracking_execution/program/collection` 消费独立组件与实际首个RF（无RF时OA）的原birth和真实位姿；
保留全局实验时间，不在OA重新释放。旧复合与新split真实OA–TOF scope均拒绝HandoffResult（空也拒）、
state_relaunch及segmented_upstream；独立RF和C的IP–MR合法续传不变。统一结果适配在实际collection后，
从initialize/terminate/有限圆面观测核验原始ID/6D/记录；未证明detector面交叉不冒充detected，缺件明确incomplete。
trajectory product声明5个schema2科学数据文件，版本证据取实际Windows executable固定资源并核对文件身份。

官方依据：SIMION [global segment](https://simion.com/info/workbench_program_extensions.html#sim-segment-global)、
[time](https://simion.com/info/time.html)、[roadmap](https://simion.com/info/roadmap.html)，2026-11-27查阅，
本机8.2.0.11；ion_time_of_flight包含TOB，age另减birth，不能再次加birth；segment_global适用8.2。
此次仍未执行SIMION Refine/Fly，Lua/合成日志只证明声明的软件边界。

`ion_release/dotnet_box.py` 注册box策略并直接复用旧唯一 .NET RNG/ION11 generator；保留.8E实际输入精度，
原generator文件未改。显式选择public u/e转换为canonical速度，尚未证明与SIMION initialize速度等值；
旧OA兼容u和旧COMSOL舍入e没有偷偷替换为新值。两/三组件作者例已冻结原几何、域/网格、V(t)、clock；
OA N=3是原算法N1000的确定前缀，原ION11三行CRLF SHA256 47dead2ebc4d21dfd87244bbc3c24baa1ea22ecdd0e63f16d620594c5cb5a757；
RF N=3为原100母群前缀。小N与新组合是本轮技术选择，不是原评阅批准或旧native资格。

本单元联合 `.venv/Scripts/python.exe -m unittest tests.contracts.test_split_tof_simion
 tests.contracts.test_split_tof_tracking tests.contracts.test_simion_particle_data
 tests.contracts.test_split_native_example tests.contracts.test_native_workflow -q`：20 PASS（6.291s）；
其中native_workflow公共入口尚为独立未提交整合，其他17项验证本主题的软件入口与负例。
对应生产/测试Ruff PASS；旧ION11四项PASS，原SIMION compiler/native-plan兼容15项曾PASS。
未启动商业软件，不把上述结果计为BA06/08/09整体验收。

实际COMSOL独立几何候选已由正式6.4/R2025b launcher完成build+冷开+owner发布：run_id
`20261127_012417__build__comsol__geometry-b9b8d5258ade`，manifest SHA256
50948D07CCD42623117A05AAB9CBD6D51EAB7D4A457B7E39B0F17413224FE4A5；来自冻结的WORKTREE源，
不伪称HEAD已验证。45 member/43电压group/5理想片；未求场、未CPT，owned_scope_unknown资源观测警告保留。
源记录位于本轮原生owner run。后续提交冻结后需按实际影响复验。

下一步B4：先补实际旧载荷跨阶段及原生后代防删保护，再启动SIMION公共链；原TTL/terminal读锁不能独自证明GC安全。
B5 mass_scan纯原语已测试，公共多物种执行仍未接入；COMSOL三格新求场/飞行与普通安装仍未完成。


### B 累计 CLOC（至SIMION软件闭包）
CLOC 2.10：`a9d76aa4dcdbaf8099c9ce5aa0585d6fce18c3be` → `7091001768b8852f687af5b99b5d8fd4e358d3a6`，PASS，unclassified=0。
实际命令：`tools/repository/report_cloc_delta.ps1 -Base a9d76aa4dcdbaf8099c9ce5aa0585d6fce18c3be -Current 70910017 -ClocExe C:/Users/Liao/mass_spectrometry/.tools/cloc/2.10/cloc.exe`；LC_ALL/LC_CTYPE/LANG=C。
结果来自指定提交；执行时WORKTREE有并行未提交改动，未将其计入指定SHA。表格直接格式化工具输出。

| Scope | Language | Files | Blank | Comment | Code |
|---|---|---:|---:|---:|---:|
| total | JSON | 282 → 288 (6) | 0 → 0 (0) | 0 → 0 (0) | 126022 → 129000 (2978) |
| total | Lua | 119 → 119 (0) | 413 → 413 (0) | 828 → 828 (0) | 13219 → 13219 (0) |
| total | MATLAB | 186 → 186 (0) | 1066 → 1066 (0) | 2053 → 2053 (0) | 19701 → 19701 (0) |
| total | PowerShell | 150 → 150 (0) | 1100 → 1100 (0) | 1195 → 1195 (0) | 46113 → 46113 (0) |
| total | Python | 1435 → 1456 (21) | 32921 → 33131 (210) | 42493 → 42597 (104) | 396258 → 398704 (2446) |
| total | SIMION GEM | 10 → 10 (0) | 26 → 26 (0) | 51 → 51 (0) | 214 → 214 (0) |
| total | TOML | 5 → 7 (2) | 43 → 45 (2) | 2 → 2 (0) | 219 → 251 (32) |
| total | YAML | 2 → 2 (0) | 8 → 8 (0) | 20 → 20 (0) | 506 → 506 (0) |
| total | SUM | 2189 → 2218 (29) | 35577 → 35789 (212) | 46642 → 46746 (104) | 602252 → 607708 (5456) |
| production | JSON | 259 → 264 (5) | 0 → 0 (0) | 0 → 0 (0) | 42340 → 44385 (2045) |
| production | Lua | 99 → 99 (0) | 333 → 333 (0) | 703 → 703 (0) | 11141 → 11141 (0) |
| production | MATLAB | 118 → 118 (0) | 526 → 526 (0) | 1462 → 1462 (0) | 12164 → 12164 (0) |
| production | PowerShell | 138 → 138 (0) | 1037 → 1037 (0) | 1149 → 1149 (0) | 44012 → 44012 (0) |
| production | Python | 685 → 698 (13) | 16804 → 16929 (125) | 11609 → 11668 (59) | 182981 → 184350 (1369) |
| production | SIMION GEM | 10 → 10 (0) | 26 → 26 (0) | 51 → 51 (0) | 214 → 214 (0) |
| production | TOML | 5 → 7 (2) | 43 → 45 (2) | 2 → 2 (0) | 219 → 251 (32) |
| production | YAML | 2 → 2 (0) | 8 → 8 (0) | 20 → 20 (0) | 506 → 506 (0) |
| production | SUM | 1316 → 1336 (20) | 18777 → 18904 (127) | 14996 → 15055 (59) | 293577 → 297023 (3446) |
| tests | JSON | 23 → 24 (1) | 0 → 0 (0) | 0 → 0 (0) | 83682 → 84615 (933) |
| tests | Lua | 20 → 20 (0) | 80 → 80 (0) | 125 → 125 (0) | 2078 → 2078 (0) |
| tests | MATLAB | 68 → 68 (0) | 540 → 540 (0) | 591 → 591 (0) | 7537 → 7537 (0) |
| tests | PowerShell | 12 → 12 (0) | 63 → 63 (0) | 46 → 46 (0) | 2101 → 2101 (0) |
| tests | Python | 750 → 758 (8) | 16117 → 16202 (85) | 30884 → 30929 (45) | 213277 → 214354 (1077) |
| tests | SUM | 873 → 882 (9) | 16800 → 16885 (85) | 31646 → 31691 (45) | 308675 → 310685 (2010) |

完整过滤口径：

```text
FILTER=extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|tests_boundary/*_fixtures.py|tests/**/__init__.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked
```
classifier SHA256=d3abfc94e920066445561b696c76131b43eab9713a0cbcb9e2c1270ba7136952；language definition SHA256=985e60f06bd8981c36966a0895cccfccd182fd625c79eb6ae94b65a12c5508a6。
日志存本轮外部证据根 `70910017-cloc.log`。后续native生命周期/公共运行/COMSOL主题尚未计入，最终交付按最终实际SHA再累计。


### B4 跨阶段原生资产读取保护

`execution/native_source_guard.py:guard_native_source` 按显式真实owner root和expected_kind，
在既有terminal共享锁/容量decision锁的建立窗口冷读原manifest与owner，再对manifest/run_config/产品data逐文件
使用既有guarded_file_identity，持防写/防删OS句柄至context退出；不引入第二GC/TTL租约，也不接管旧payload删除权。
terminal共享锁本身不能挡旧GC：已真实子进程证明同时仍可取capacity decision锁；不能误称它是PA保护。
正常跨阶段保护与native后代保护不同，后者仍需PS owner自行持有完整不可变输入句柄。
既有source lease仍避免账本先标pending的管理争用，遇pending不猜测修账，失败关闭或按原owner重算。

`.venv/Scripts/python.exe -m unittest tests.execution.test_native_source_guard -q` 两项PASS；
真实Windows小fixture子进程对manifest/run_config/payload写入/删除，以及原remove_recorded_files删除均被拒绝，
context退出后允许；错root/kind/散列拒绝。生产/测试Ruff PASS。
加入公共workflow/mass_scan/reference定向联合18项PASS（11.248s），仍无商业工具调用。
helper首次保护包含原reader与guard的两次大文件hash，尚未测性能，未为优化放松信任边界。
下一步同一CLI运行将持此guard直到下游接管和SI结果复制完成；原native子进程持权接线由Agent3继续独立验证。


### B5 物种母群与归并单元（公共原生执行仍在整合）

`workflows/mass_scan.py` 复用唯一sample_release：canonical_mass_scan_request仅组合非空species_requests，
质量/电荷/N/分布仍来自各原release_spec，不复制第二套物种权威。物种唯一，同epoch，显式粒子ID全局唯一；
缺省/None ID按物种顺序避开所有显式ID确定分配，权重局部映射冻结为全局映射，样本N与物理权重分开。
`recipes/native.py` 同Study release入口接受该版本化集合，每个源/clock/显式控制分别校验；
COMSOL原生出生比较的SI容差必须作者显式声明，不用输出采样间隔替代积分控制。

merge_mass_scan只归并已成功完整批、保留真实ID与各6D/事件/轨迹，拒绝缺终态/外来身份/重复/混合谱系；
analyze_mass_scan独立报告各species原始和加权检测率，0-hit和1-hit可作为完整科学负结果，
峰统计/标定不足给not_applicable，不将分析准入倒灌成追踪失败，也未假称实际拟合已执行。
实际失败/缺件不能用零命中掩盖。各批frame/clock由运行owner在归并前验证，TraceResult本身没有伪造元数据。

mass_scan定向5项及Ruff PASS，含单物种、不等N、同mass +1/+2、权重、null/显式ID、混合clock、
0/1-hit、缺件/重复与schema2冷读；native_recipe+native_workflow联合16项PASS（5.622s）。
其中nativeworkflow新公共调度仍未提交，本主题软件原语不代表真实+1/+2原生完成或BA12全通过。
下步同一run_recipe按物种完整批运行，共享实际场依赖、缺批局部重算，之后以真实小N+1/+2闭合。

COMSOL后续工程probe（WORKTREE源）固定几何/5mm mesh实际6,277,920元素；已知5m工程守卫在求场前拒绝，
run `20261127_013605__sim__comsol__pulse-basis-baa1c658928b`，peak快照约4,927,029,248 B，
owned_scope_unknown限制仍保留。没有OFF/ON解，没有CPT；mesh元素不是节点或DOF，不拿默认二阶推断冒实测。


### B4 当前接线与原生运行恢复入口（继续Goal）

当前已提交/推送到 `7b48a0fe`，前一读取保护提交为 `d0c7cbbf`，未合并主线。
原有artifacts保留。以下是进行中事实，不作为批次完成：

- Agent3单worker真实host prelaunch ACK/worker登记/持久completion已冻结；父controller被杀仍保护，
  正常/非零退出/登记前死亡/nonce错拒绝均实际小进程测试；新增public recover_controls自动重读原私有work回执，
  recover_interrupted_runs可收尾，坏回执原因可查询且保护保留。Store19 PASS；native首次8/9的唯一错误文案断言已修，
  对该真实10.600s用例单独重验PASS，另一登记前死亡用例PASS，不重复无关完整suite。
  PS现在即便有Python immutable_input_session仍自行持原source防删句柄；真实父死后源PA不能unlink，worker结束后可删。
  sourceguard/前端field精确读输入已补，working/refine私有写目标不误加immutable。
  原生group尚失败关闭，未验group副本留工作区外.tools/native-group-wip-20261127，不能把单worker外推group。
- Agent2/5双基场适配现使用两个真实OFF/ON解，Eoff+gate*(Eon−Eoff)保留常开反射场；共享reader验证同MPH的两个
  独立solution/dataset/request/coldread/mesh/vacuum/真实producer product，18项软件合同PASS。
  五槽世界background PA未闭合，public scalar admission仍拒绝，不让PA联集之外静默零场；Agent4正在复用原neutral机制。
  split模型native_drive_rows的JSON顺序漂移已规范排序并重编译精确等值，尚待独立提交。
- 新native_tracing同一CLI/run_recipe的schema2公共执行仍WORKTREE，单次作者bytes/冻结Study/clock、分阶段Store小引用缓存、
  原owner exact product文件guard、全母群schema2重读、多物种批及分析准入已接，18项workflow/mass/reference/sourceguard联合PASS。
  增强preflight实际走tracking planner，拒绝无RF装配中的RF专属数值；新增cache kind必填/完整性/clock资源/原生资源字节身份。
  新CLI还没有真实完成run，COMSOL helper已新增且正在整合；不宣称BA02/06/09/12/15全通过。
- COMSOL独立几何与未求解模型真实冷开PASS；100万/500万工程mesh上限两次均在Compute前停止，第二次实测6,277,920元素。
  固定5mm网格、阶次/BVP不变的7m上限新run `20261127_014602__sim__comsol__pulse-basis-82a20bcf1fb3` 已通过mesh守卫，
  mesh_facts独立事实文件先关闭保存，仍在求场。最新单点COMSOL14.24GiB/MATLAB1.26GiB/系统可用8.16GiB，接近16GiB树预算，
  原owner保留守卫；曾出现owned_scope_unknown，未证明全程资源观测完备，不扩大预算或伪称求场成功。
  若明确越限且owner未行动，须沿受管取消/drain保留失败；不得裸杀Python后声称native已停。

恢复后先核对上述7m native实际状态/证据与当前Git差异，接Agent3冻结单元、COMSOL公共helper，补完整世界carrier再跑SIMION。
不重新做全仓P4，不重复已完成A/B0，不自动启动C/M06–M08。后续CLOC按实际提交累计（上一完整表至70910017）。


### 预算语义纠正与单worker原生生命周期单元

Agent0此前将16GiB工程工作集观测预算误认为硬停止条件，指示过早结束7m run。
已重新完整核对 DEVELOPMENT_STANDARDS 6节与 REPOSITORY_OPERATIONS 资源观察：预算越限只告警，
健康原生进程应自然完成，只有中央策略确认持续物理危险才可危险停止。原资源代码和期望测试没有改成硬停。
`20261127_014602__sim__comsol__pulse-basis-82a20bcf1fb3` 实际由Agent人为中断，
owner随后确认writers_stopped/正式host release；17,417,613,312B峰值是同时观测值，
但该越工程预算不构成模型/solver失败或发布禁令。旧记录原样保留，不能改写为物理失败或PASS。
本次没有合格field，无CPT；未确认recovery不用于伪checkpoint。纠正性同网格/BVP/阶次/精度新run
`20261127_015508__sim__comsol__pulse-basis-fd136b758ffa` 已启动，不因预算告警/unknown杀健康solver。

本单元实现入口：storage/store.py 的claim_token/bind_native_controls/record_native_worker/complete_native_controls，
execution/native_artifact_controls.py 的scope与真实持久receipt验证，原processes/process_owner/resources以及
RunSession的明确operation_id接线。native启动前原host grant+nonce ACK、启动后登记确切creation identity并ACK；
controller死亡不放行未启动工作，已启动工作保护延续至原owner/drain/非inherited release正式证明。
原work中留host/ACK/worker/receipt事实；public recover_controls/interrupted_runs自动只查已登记私有work并幂等对账，
坏回执不释放、native_recovery_issues可查询。complete不删活holder跨stage控制，holder最终退出/OS token才释放。
没有超时/裸PID失联判死，没有新调度器/daemon/第二资产owner。

PS即便接到Python immutable session，也自行用原Protect-ImmutablePaSource持精确输入防写/防删句柄，
到native后代drain结束才释放；field_worker与field workbench补全既有owner的真实source输入清单。
原始raw/parent保护，工作私有PA保持可写。controller正常跨阶段由已提交guard_native_source补足。

验证：Store19 PASS（5.366s）；native单worker9项首次8 PASS，仅坏nonce文案断言过严失败，
修正后对应真实controller强杀/自动恢复10.600s用例PASS；另一登记前死亡自动恢复已PASS。
此前单worker/Store/原process联合29 PASS（48.538s）、非零exit3真实例13.482s PASS；
最新field输入+session父死源防删+future geometry四项12.235s PASS；相关Ruff PASS。
独立静态审查未发现被guard源PA同阶段原生写回，未把静态审查当Refine/Fly证据。
此前直接field suite无enclosing GATE且文件编辑中得到1 ERROR，不作为当前验收；必要GATE后续相称补跑。

限制：本提交只单worker和原生文件生命周期，scope下group明确未实现，副本保留外层.tools待下一主题；
不是BA09全部闭合。SIMION真实Refine/Fly、COMSOL真field/CPT、wheel/sdist新链离仓仍待完成。

### B 原生求场事实与失败收尾修复（80f0164d → 本主题提交）

纠正性 run `20261127_015508__sim__comsol__pulse-basis-fd136b758ffa` 的 OFF/ON 两次原生
Compute 均实际完成：6,277,920 mesh elements、各9,363,200 DOF，共存 MPH 3,082,205,877 B。
Python 后验拒绝 MATLAB JSON 的精确整数浮点表示 `6.27792E+6`；这不是原生求解失败，原失败 manifest 不改写。
后续恢复只捕获现存输出身份并冷开校验，捕获时点显式记为失败 Python 校验之后；不能倒称旧输出已经发布封存。
工程 BVP 为有限外箱0 V、真空εr=1、mesh auto5/electrode_hmax5 mm，是新增 probe 技术选择，
不是 SIMION Neumann 同边值问题或数值收敛资格。owned_scope_unknown 的观测限制仍保留。

一次恢复因旧 verifier 只接受单 study 而原生退出1；期间 Agent1修改原 action 源，导致最终化又受阻。
这两项诊断均保留。新 owner 修复：确认真实 writer 停止后，源改变成为明确失败事实而不掩盖原异常；
`RunSession.declare_file` 原子保存明确角色日志。`owner.recover_failed_finalization` 只接受该既存
reopen_pulse_basis 失败状态、冻结 action/完整文件角色/配置/真实 process 与 launcher/原 host release 证据，
仍走原 `_finalize`，不运行 action、不启动原生、不产生科学成功产品。缺证据保持保护。
实际35个 run 文件与35个配置输入（20外部）逐项核对后，原 hold 已收尾 failed/complete，
capacity lease 已释放，3.08 GB 源 MPH 未复制或改写；失败终态 manifest SHA256
`2B31B84B149073F0753E277D8D4B96936A822B73C9BE3B83B20EBD4F47E49F38`。

本主题命令：`.venv/Scripts/python.exe -m unittest tests.contracts.test_owner_action_freeze tests.contracts.test_owner_failed_recovery -q`，
11 PASS（9.908 s）；相关 Ruff PASS。覆盖真实动作源改变后的失败关闭和缺件/角色/身份/release 反例，
不将 inert fixture 当成原生求场验证。下一次冷开 run
`20261127_023910__analysis__comsol__basis-recovery-e7a42a44d31e` 正执行0 Compute校验，
整个 action/native/owner 闭包保持冻结直到最终化返回；尚未宣称该次成功或 basis 合格。

当前 HEAD 在本主题前为80f0164d，任务跟踪分支普通推送同步；原有 artifacts 与所有其他并行改动保留。
剩余旧消费者：旧复合新执行入口退役、plan6 recorded-birth 读取与准备仍在定向迁移；
SIMION Refine/Fly、COMSOL CPT、桥接实际采样/Fly、普通安装及 BA01–BA15 最终对账尚未完成。
后续主题包括group生命周期与公共三组合调度；当前不代表批次B完成，不启动C。

### B4 group 原生控制基线（7082d495 → 本主题提交）

冻结group operation集合，原PS owner登记每个实际worker的PID+creation identity并取得精确ACK，
在原句柄逐一drain和非继承host正式释放后才对账Store；未启动集合必须明确证明，缺件/nonce错/身份冲突保留保护。
quick-exit直接读取原Process句柄退出事实，不伪造host live登记；坏live登记不能回退为quick-exit。
实现为既有 store/native_artifact_controls/processes 及两个PS owner，不新增调度器或TTL。

隔离代码树实际16项原生短子进程测试PASS（188.200s），Store19及Ruff PASS。
main接线后，使用共享主机账本环境变量
`MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=C:/Users/Liao/mass_spectrometry/artifacts/platform/host_resources.sqlite3`，
运行 `tests.repository.test_native_artifact_controls` 的
`test_single_quick_exit_receipt_covers_success_and_failure` 与
`test_group_controller_death_preserves_all_workers_and_automatically_recovers`，2 PASS（36.344s）；
边界16 PASS（8.639s）。首次main尝试漏该必需环境变量而在worker启动前失败，修正后复验，不记为通过。

限制：中央持续物理危险可能停止并重新调度同一operation；当前operation→单身份不能自动闭合多attempt，
仍保守留权。Agent3已按真实scheduler路径只读确认，下一主题保留冻结operation集合，为每次实际启动增加身份与ACK，
不改预算/调度策略或强制单worker；不能把本基线称为BA09全通过。
测试临时目录 `C:/Users/Liao/AppData/Local/Temp/tmpft8zbwq3` 已确认无活进程，精确清理被自动策略拒绝，
保留原目录且未换路径/命令绕过。未清理任何真实研究产物。

### B3 显式原生资产的唯一配方快照

`recipes/native_assets.py` 扩展同一load_recipe：可显式冻结COMSOL共存OFF/ON manifest；桥接时同时冻结
原SIMION source-free FieldBundle作为碰撞载体，并要求作者显式world/windows采样。只读各小manifest一次，
不复制或在配方解析时读取PA/MPH；实际owner/几何/物理/采样覆盖由消费者另行验证。
`recipes/native.py` 冻结验证只读snapshot；科学身份纳入manifest内容身份与采样，不纳入路径或label。
错product/kind/未绑定产品/递归world碰撞源/非有限或下溢采样/错误策略均拒绝。

`.venv/Scripts/python.exe -m unittest tests.contracts.test_native_assets tests.contracts.test_native_asset_recipe tests.contracts.test_native_recipe -q`
14 PASS（3.420s），相关Ruff PASS。真实公开解析集成覆盖首次读取后外部manifest变化、冻结验证不重读、
路径/label不失效以及采样/碰撞内容变更失效。不是场解或原生追踪验收；桥接导出与实际Fly待下一主题。

### B3 COMSOL 双解与原生追踪软件闭包

`backends/comsol/assembly_particle_tracing.py` 与 MATLAB `solve_assembly_pulse_basis.m` 在同一模型保存
两个独立stationary解，原静态场保留，OA按原pulse切换；`trace_assembly_particles.m` 实际CPT入口消费
同一原birth、统一实验时间、显式积分控制与现有public物性。`particle_data.py` 输出schema2完整SI母群/终态/事件/轨迹；
缺失或无法归属的原生状态保持不完整，不能补成成功。`workflows/comsol_tracing.py` 编译同一冻结Study，
显式basis reference分支保护background/on并逐项比较实际projection与两组request，可跳过Compute直接追踪。
目前该CPT和reference编排只通过软件测试，未运行真实粒子，不能认定BA06/07/08/12通过。

`assembly_native_scope.py` 按真实manifest-bound run_config与geometry来源重建project身份，
旧复合project的新geometry/model/solve/basis/CPT执行明确拒绝；历史read/export/0Compute恢复保留。
不凭实例名猜物理角色。两项旧inert transport fixture不具备provenance，明确mock该独立scope检查，
另有真实冻结链与错误/不一致projection正反例，不把mock当owner科学证明。

设置共享host账本环境后，运行COMSOL scope/workflow/particle_tracing/world_scalar_contract/
assembly_electrostatic_model_managed/stationary_managed_failure 六模块，23 PASS（98.623s），相关Ruff PASS。
新增projection mismatch负例单独PASS。真实冷开脚本为外部workspace `recover_basis.py`，最终run
`20261127_023910__analysis__comsol__basis-recovery-e7a42a44d31e` 已success、writers_stopped=true、host released、
workspace workflow leases=0，background/on产品发布；manifest SHA256
`E2F7AC36D7854589C72C0C5DD375D8F90323154688709F447463194066030CB2`。
本次compute_calls=0，比较两solution/dataset、43组电压、mesh与真空均与真实Compute report一致。
借用原MPH SHA256 `02179DB42E4A25922315A13B4AAF8347C8B18C3BD9C291EF952FB3A72FEFA031`，
3,082,205,877 B、solver_native_binary；身份是Python失败之后新捕获。无新的Compute或收敛资格。
下一步固定已安装代码，从离仓同一公共CLI引用此basis跑真实小N CPT；新场与追踪证据分开报告。

### B2/B3 SIMION 连续追踪与显式双解世界载体（软件闭包）

`split_scalar_binding.py`/`scalar_sample_binding.py` 绑定真实同模型OFF/ON与独立solution/dataset、冷读和物理request，
Lua `split_scalar_field.lua` 使用 Eoff+gate*(Eon−Eoff)，常开反射场不丢失；两域支持均须有效，无静默零场。
`split_scalar_workbench.py`、native_plans和iob_core复用原managed owner生成五槽world，
background为最低优先级槽1，原四个碰撞载体为2..5；不调用Refine或Fly，不复制大PA。
world IOB仅在该owner run内冷开验证；后续track必须从已评阅五槽seed重建，不能引用已释放短路径别名。
当前仅支持OA原生坐标与assembly坐标identity pose；其他pose明确拒绝，未宣称通用旋转world。

`tracking_execution/program/units` 使用实际8.2.0.11可执行文件身份与原生出生/6D/母群/有限检测面事件，
保留源birth和实验epoch，drive phase不替代实验时间；无跨组件重新释放。Lua `%d` 已实际证明32-bit边界，
当前SIMION adapter在实际planner拒绝particle ID >2^31−1，公共存储仍int64，不隐式截断。
split模型native_drive_rows按(instance,group)规范排序，JSON往返后重编身份一致。

公开SIMION compile/build/prepare/solve/track 及旧mass-spectrum新执行入口拒绝旧复合OA/TOF，
历史纯compiler和analysis读取保留；新的owner正例全部迁真实plan6 RF/OA/TOF，原预算/clock/分批/拒绝断言保留。
范围不是IP/MR/C的全仓退役。plan6 recorded-birth preparation/reader作为独立下一单元，仍在软件验收。

同一main代码联合运行 split_scalar_binding/world/tracking、split_tof_tracking、simion_particle_data、
split_tof_simion、platform_api、legacy_composite_retirement 八模块，64 PASS（23.318s），SIMION相关Ruff PASS。
首次联合失败为legacy负例错误消息已被更早退休guard改变，精确区分legacy/split后通过；
另一次新测试在patch时首次导入造成mock污染，修复测试导入顺序，不放宽生产校验。
上述均不是实际Refine/Fly证据，三个原生组合及已安装链仍须运行。

### B2/B5 同一公共CLI调度、分阶段复用与worker证据

`workflows/reference_tracing.run_recipe` 单次load后把同一source_bytes交`native_tracing.run_loaded_recipe`，
CLI沿同一validate/run接显式ExecutionContext。原生输入、分阶段小引用、每物种完整独立批和发布均走既有Store；
PA/MPH仍由原owner删除，不移交给第二GC。`scalar_tracing` 仅显式导出既存OFF/ON和支持域、world、连续原birth追踪，
无Compute/Refine回退；源geometry/prepared/field与collision的每个真实manifest受同一owner root防写删保护。
跨workspace源明确预检拒绝；不复制manifest或扩root伪装保护。

只读审查修复scalar tracer帧选择、共享/跨backend实现缓存身份及same-run命中即时落盘。
场缓存不纳入workflow/label/粒子N，追踪缓存纳入原母群与数值；桥接摘要包括真实双backend/shared代码。
`native_evidence.summarize_native_workers` 冷读四份owner回执，记录每个原PID+creation及整数退出码；
缺件/未知为unavailable，不以stage_productions推断真实solver调用。发布证据路径改为run内相对路径。
实际Compute/Fly次数仍须按真实原生报告及新owner运行列表另行对账。

native_workflow/scalar_workflow/scientific_core_boundaries/native_evidence联合29 PASS（15.301s），Ruff PASS；
首次25项中边界一项发现scalar具名workflow缺配方依赖声明，按现有具名workflow边界补齐并复验，未给所有workflow开放。
外部安装venv已按requirements-lock完成普通依赖安装，尚未安装本主题wheel或实际运行native。
下一步从提交快照构建发行，先COMSOL→COMSOL引用真实已发布basis跑CPT，再闭合SIMION及桥接真实小N。

### B 安装后发现的两个执行前缺陷（cd1f2156候选）

cd1f2156普通wheel已从git archive固定快照构建，独立venv按requirements-lock普通安装。
仓外 `-I` 确认msplatform来自installed/Lib/site-packages，COMSOL和SIMION配置validate均PASS，
但两条实际run均在原生追踪/Refine之前失败，不能称安装链通过。

COMSOL首次Store位于外层mass_spectrometry Git worktree，既有安全边界在创建前拒绝；
仅部署改为 `C:/Users/Liao/msplatform-artifacts/architecture-b-20261127/comsol-installed-store`。
随后raw run `20261127_025248__sim__comsol__pulse-48595d495340` failed、writers_stopped=true、operations=[]：
epoch record缺retention_role，且其product路径原本会引用稍后移动的Store work文件。
修复为保留原epoch身份并冻结小JSON到native owner input，产品只引用该稳定副本，原输入和副本均受子进程guard；不复制MPH。

SIMION安装版run和同一公共API诊断均报large unclassified record，traceback定位 `_execute` 的可执行文件身份记录：
真实SIMION exe 10,106,136 B超过8MiB tier，需要明确evidence role。修复只显式声明可执行文件身份为required_evidence，
不改原生载荷分类/阈值/预算。两次均未启动Refine/Fly。

定向运行large executable回归+COMSOL particle/workflow，15 PASS（1.846s），Ruff PASS；
epoch测试覆盖无role原记录、删原work后副本仍可读及源变化拒绝。下一候选重新普通安装后重跑受影响链。
外部诊断位于 `batch_b_comsol_small_cli_20261127/installed-run*.log` 与
本轮外部证据根 `simion-installed-study/installed-api-diagnostic.log`，原失败运行保留，不补造轨迹。

### B2 plan6 recorded-birth 消费者迁移

`single_reflection_flight/prepare.py` 新request_v12.schema.json分支只接已发布plan6 FieldBundle，
冻结原CSV/RF metadata/完整顺序ID/clock authority/epoch并对真实model及drive身份；实际tracking planner验证源frame/pose。
`recorded_birth.py` 对同一preparation manifest与FieldBundle重读核对，再交原母群给公共连续track。
没有选粒、重编号或跨组件重新释放。旧schema保持历史读取，不为旧复合重新开执行入口。

审查发现新CSV不能继承旧preparation的零时间偏移假设；schema12现要求作者显式有限instrument_origin_us，
prepare/reader同值，source_time_mapping入provenance，不重复加epoch。非零7.5us正例和缺值/bool/NaN/Inf拒绝已测试。
当前真实metadata验证器只支持RF源，OA-only recorded明确拒绝；不猜等值或放宽源校验。

schema12与历史preparation联合46 PASS（72.066s）；该次后新增原点字段仅影响schema12，
对应最终单项复验PASS（3.106s），Ruff PASS。原生owner在fixture中mock，尚无recorded-source实际Fly，
不把软件迁移视为三格native或完整仪器资格。下一步真实已发布FieldBundle可按同一新合同验收；
当前并行的安装链为fresh source，不能冒称它验证了本recorded路径。

### B4 中央危险停止后的多attempt保护闭合

既有scheduler可在确认持续物理危险后停止一个worker并重新排同一operation。
`native_group_attempts` 在同一Store记录每次真实(operation,attempt,PID,creation)，
PS worker登记和ACK都含完整attempt身份，不复用上一次operation ACK。
最终receipt逐一保留原Process句柄drain的真实整数退出码（危险停止的null观察不能转成0），
正式host release后对账所有已启动attempt及明确未启动集合，才能解除原claim/预留。
不覆盖旧身份，不改scheduler/预算，不强制单worker；缺/错/重复证据保权，恢复两次幂等。
旧单次group读取仅在原证据确有一次attempt时解释，旧版单独兼容回归未运行，不外推已验证。

真实短子进程、测试owner内可控中央危险采样（无商业软件）：原受管危险停止→保留sibling→稳定后重启
PASS（22.493s）；第二次ACK前/后父死及旧/新attempt分别篡改拒绝、回执修复后恢复两次PASS（2项49.549s）；
quick成功/非零、mixed failure/未启动集合PASS（31.503s）。Store19 PASS（5.434s）、Ruff/diff-check PASS。
worker证据汇总同步按attempt保留pressure victim与后续成功，不拿最终成功覆盖早前停止。
native_evidence与科学依赖边界联合21 PASS（10.349s），无新科学solver证据。

本单元补的是同一生命周期真实attempt证明，不声明整个BA09已通过；商业原生跨阶段/合格缓存自动回收、
缺批局部重算仍需实际链对账。当前运行中的398ba7b0安装快照未被修改，之后最终发行需包含本修复。

### B SIMION 实际几何失败后的工程限额修正

398ba7b0已安装CLI真实run `20261127_025726__build__simion__geometry-23e1b95e6a77` 在operation3退出1：
`build_detector_variant.lua` 原公式 nx×ny×nz×8×3.25/1024² 给165×165×126探测器PA集合估算85.057354MiB，
而两份示例Study显式detector.max_mib=64。不是host工程监测强停，resource_budget_exceeded=false，
owner已failed/writers_stopped=true/host released；未Refine/Fly。

新增工程选择采用既有oaTOF参考builder的128MiB限额；两示例只改此max_mib与TOML Study SHA，
测试按原字节替回64可还原原Study SHA，证明网格、几何、source、N、pulse、时钟和精度未改变。
`downstream.compile_downstream_specs` 对split的已推导真实网格提前执行同一Lua估算，
不放宽Lua校验、不改宿主准入。64与估算相邻更小值在纯预检拒绝，恰好估算/128通过。
split_detector_budget/native_workflow/split_tof_simion 12 PASS（5.776s），相关Ruff PASS。
此选择为本轮新增工程修正，不是原评阅同意或物理变更；下一安装候选须真实重跑。

并行COMSOL rawrun `20261127_025800__sim__comsol__pulse-363a967be681` 已原生启动，
bootstrap在CPT边界集合互斥/完备断言失败（trace_assembly_particles.m:60），无粒子结果；
owner已failed、writers_stopped=true、exit1、host released、无workflow lease。
实际集合调查继续，不能宣称CPT通过，也不能删除严格物理校验来凑绿。

### B6 旧执行对账与保留的C边界

真实调用审查发现旧COMSOL完整composite的直接旁路：Formal Validate、oatof_retrace.run_species_retrace、
安装资源run_fixed_particle_retrace，以及run_oatof_model/底层builder的默认particle-flight模式。
新执行现明确拒绝并指向公共Study，不是因为segmented-output字样而删除COMSOL时间采样。
geometry-only/field-design-only组件研究保留；历史Verify/Publish/Recover仍须原封存证据，不降低资格门槛。
同一公共新链没有继承Candidate/Formal总等级。

Python API与真实pwsh Validate无路径/无owner早拒绝两项PASS（0.777s），Ruff PASS。
MATLAB guard仅完成静态审阅，未运行MATLAB正反例，不报native已验证；未保留镜像源代码字符串的脆弱单元测试。

| 旧入口/消费者 | 本轮路径与owner | 处置/下一批 |
|---|---|---|
| 完整OA–TOF handoff/分段scope及旧复合执行 | public Study → native_tracing → SIMION operations/tracking_execution、COMSOL assembly_native_scope | 本轮明确拒绝，连续birth路径真实组合验收仍在进行 |
| 旧mass-spectrum/COMSOL整机retrace/Formal Validate | public Study/mass_scan → 同一native owner | 旧新执行拒绝；历史读保留 |
| plan6 RF recorded birth | schema12 preparation/recorded_birth → public simion.track | 软件迁移；真实recorded Fly未验证，OA-only recorded拒绝 |
| registry ip_mr_chain / accelerator_interface FullJoint / prepared_joint_execute | IP provider、MR参考和manifest-bound producer身份检查 | IP–MR活跃旧链交C，本轮不删 |
| accelerator_interface普通OA→MR接口准备 | prepare_interface，仅准备与验证接口 | 不是粒子传播，保留 |
| assembly/handoff.py | 母群/时钟/坐标与原始源校验 | IP/MR等仍消费，保留中性职责 |
| 历史manifest/record reader、COMSOL时间输出分段 | 只读证据与原数值采样语义 | 保留，不宣称全仓segmented清零 |

当前COMSOL0Compute边界诊断已启动，SIMION新工程预算候选正在独立构建/安装；
没有将本退休软件检查冒充BA06/08/10/11/12/15全部通过。

### B COMSOL 面集合失败的实际根因与最小修复

两次新managed只读诊断均0 Compute、不保存原MPH、源闭包冻结至owner终态。
第一run `20261127_030559__analysis__comsol__boundary-546ef21fcef2` manifest SHA256
`D187E68A8B80D6890642561A46486250647FE344995C24CACFBEFA78D04EFACD`；
第二run `20261127_030937__analysis__comsol__boundary-b5413d7f1527` manifest SHA256
`7EB344C7824AE449811013926C1741A7A2AF5CC5DCCDCEB2B9F251A4CCC1AFED`。
`results/boundary_sets.json` 逐45member记录真实面ID与每项布尔，不采纳先前同组metal/sheet重叠猜测。

实际vacuum427、metal416、sheet5、outer6，三种交集均空，uncovered/extra均空。
CPT内存创建前后均相同；vacuum size=[1,427]，metal=[416,1]，sheet=[1,5]、outer=[1,6]，assigned=[427,1]。
原isequal(sort(assigned),sort(vacuum))=false，但双方(:)后=true；错误是数组方向，不是物理集合。
生产MATLAB只在最终完整覆盖isequal两侧各加(:)，保留三个互斥和逐member非空及全部面ID检查。
COMSOL particle/workflow14 PASS，Ruff PASS；真正修后CPT尚未运行，不用诊断替代轨迹证据。

SIMION c8479985实际几何IOB冷开4实例PASS（Fly/Refine均false），geometry与prepared model两owner success/writers_stopped，
求场run `20261127_031207__sim__simion__fields-9cb9e717bba3` 正运行，尚无Refine/Fly成功声明。

### B4 成功对账后保留真实worker证据

只读验收设计发现原processes成功reconcile后会删host/ack/worker，
而公共workflow在稍后汇总四文件，导致真实worker观察不可用。
现只清理临时worker-ack，原host/ack/worker/receipt四份证据随Store work正常发布，不建第二回执权威。
原nonce/进程创建身份/原owner drain/release校验与保权不变。

真实短进程：single1个和group3个worker在发布前均available且真实returncode=0；发布后inspect_run及再次汇总通过，
原controller强杀恢复仍通过。三项57.367s PASS，Ruff/diff-check PASS。
正在运行的c8479985安装快照未包含此修复；其实际调用数必须用原owner运行清单/回执对账，不能声称其Store观察完整。
最终发行应验证四文件发布及缓存/缺件链；本修复不代表Compute/Fly计数或科学native已成功。

### B15 既有安装验收增加B配方片段

仅扩展既有 `test_installed_scientific_core.py` 的INSTALLED_PROBE与source inventory，
同一wheel/sdist重建wheel两安装臂及原reference_only窄验收都走B片段，不另建安装framework。
从installed purelib读取两组split schema2 TOML/JSON，与本次source快照SHA核对；
public CLI、`-I -m msplatform`和API实际preflight一致，旧复合compile/旧mass Fly在native前拒绝。
implemented/host条件与native_verified=false明确区分，不mock commercial运行。

c8479985普通已安装venv的仓外只读抽取片段实际PASS：
`INSTALLED_B_NATIVE_PREFLIGHT=PASS schema2=1 split_oa_tof=1 rf_split=1 retired_execution=1 native_run=0`。
首次抽取调用参数不足IndexError，纠正后PASS，未改live安装环境。现有shared-import与author-tree guard两项
最终定向PASS（1.504s），AST/Ruff PASS。完整最终两发行安装尚未执行，native证据仍分别绑定实际候选SHA。

### B5 可复制双物种作者小例（尚待native）

`examples/oa_split_tof_mass_scan_small_v1.json/.toml` 是同一public recipe的最小mass_scan：
第一species完整保留原N3请求；第二同mass100、charge_state2、N2、稳定species_id=m100_charge2、IDs4/5、权重各0.5。
Study除release外和原单物种逐字段相同，TOML只变label与Study路径/hash。
几何/场/drive/pulse/source分布与seed/clock/numerics/recording均未调优。
Study SHA256 `A7D75ED3EAB3E198D4196868B9CE1AA9A787554DC83CEA5088C545B81EACB9E6`。

公开load与实际planner检查完整5母群、3/2不等N、同mass双电荷、独立权重；
新例两项与installed shared-import/author-tree guard联合4 PASS（5.536s），Ruff/diff-check PASS。
既有两发行安装probe/inventory同步加入该第三组资源，但当前活跃c847安装不含新例，未冒称通过新例安装或native。
下一步复制这两作者文件到仓外并用现有public CLI，共用已求场依赖，验证原批复用与新增+2批、同输入零native增量和缺批局部重算。

### B4 检测观测覆盖与未知结果统计（c7801608 后，提交见 Git）

已实现独立于轨迹完整性的版本1 `data_integrity.detector_observation` 合同，入口
`results/detector_observation.py`、`results/particle_data.py`、`workflows/mass_scan.py`。
四种状态绑定原母群ID；参考 tracer、SIMION reader 显式声明能力，当前 COMSOL reader 明确 unavailable，
不再将空事件表与 unknown 终态当成检测效率0。多物种保留每批覆盖，完整观测的真实零命中仍可统计；
旧结果先核验原摘要，再返回 legacy_unqualified 与原 stored_summary，不重写历史。
执行失败、缺终态、整体 incomplete 在 species 统计前即拒绝；新公共 native 检测请求的轨迹缓存只准入完整检测观测。

实际命令 `.venv/Scripts/python.exe -m unittest tests.contracts.test_mass_scan tests.contracts.test_simion_particle_data tests.contracts.test_reference_workflow tests.contracts.test_comsol_particle_tracing tests.contracts.test_native_workflow -q`
本轮38 PASS（11.022s）；软件夹具含 COMSOL CSV→Parquet/HDF重读、混合物种、真实零命中语义、legacy ready重读和native缓存准入。
这些软件测试不替代原生检测器证据。当前 COMSOL CPT 三粒子已有真实6D，但未采集可归属的探测事件；
后续 native 辅助变量与有限面验证仍是 BA06/BA08 未关闭项，旧 COMSOL reader 仍是剩余消费者。

本主题实际 Changed 入口调用7个显式生产路径（见 `evidence/obs-gate-plan.json`），并非空Changed或全仓P4重验。
首次执行 repository_text_bytes 因26个本轮路径的CRLF工作区字节失败；仅机械转为其声明的LF，不改语义。
纠正后 `obs-gate-lf.log` 已越过字节检查，但已有完整安装测试
`test_wheel_and_sdist_install_and_compute_outside_worktree` 因未配置 `SIMION_LUA_EXE`/PATH Lua失败，
其余阶段按fail-fast阻塞或等待已启动阶段结束。不能报告完整Changed PASS；本轮定向38项的软件结果单独成立。
最终安装仍按B交付的普通wheel及sdist重建wheel、仓外参考链与B资源准入执行，不把该环境失败冒充科学失败。

### B4 无completion的CPT失败证据收尾（e95f6705 后）

现有 `execution.owner.recover_failed_finalization` 增加受限trace分支，原basis分支保留。
仅接受明确trace action/退出回执、原journal完整角色和恰五个新增SCI证据，借用MPH仍是原solver_native_binary，
不改其删除owner。无原成功completion时只生成failed completion，无products，不补造科学成功。
五输出、冻结/installed action及native源的Windows禁写句柄覆盖最终发布；源/输出均注明停止后新捕获，
不把run_config中的路径称为原native SHA seal。原result/journal完整字节与身份快照保留。

`.venv/Scripts/python.exe -m unittest tests.contracts.test_owner_trace_recovery tests.contracts.test_owner_additional_evidence -q`
11 PASS（2.950s），Ruff PASS。新fixture实际经过_finalize/_publish/retention/terminal publication，
仅capacity和test run ID检查替身；原角色、五输出与原字节快照均检查。Agent1独立审查未发现实际阻断。
真实原run043646收尾实际PASS（失败语义保留）：failed/complete/writers_confirmed=true/resume_action=null，
manifest SHA256 `53E1B213FF192579D395B322328DC4843AB454BB0D98C948D8260E2B1A71F810`，无products；
五输出实际摘要逐一匹配，原ValueError保留，borrowed model记录与原basis两产品精确相等。
capacity released/source_protection_leases=[]、原lease文件不存在、host无原活动token。
总收尾7.942s，含既有公共publication/file_record必要输入SHA核验；没有复制模型或建立哈希旁路。
可审原输入/结果/实际handler源码快照位于
`C:/Users/Liao/msplatform-artifacts/architecture-b-20261127/evidence/c439-trace-role-recovery-input.json`、
`c439-trace-role-recovery-result.json`、`c439-recovery-owner.py`。
此收尾不关闭CC原生成功交付项；固定代码后公共CLI复验仍待执行。

### B3 实际ground派生的借用记录绑定修复（6c59b402 后）

普通8a8f wheel=5,867,925字节，SHA256 `CFDFD556C7164F93104E674E6E25DE57CA49B82CCB5D310B90E2F1A3D898504B`，
安装于仓外 `installed-standalone-b1`；沿同一public CLI、原显式field source和新工程profile执行
`20261127_051111__sim__simion__ground-a365aeb095c1`。
六原生操作实际全部PASS：flight_tube 239,343节点/11,132金属/11个FSS节点；
detector 3,430,350节点/2,028,181金属/54,035个FSS节点，build和独立verify一致、Refine0/Fly0。
原owner为success/complete、capacity released、source_protection_leases=[]，但product随后被open_artifact拒绝：
`artifact data member is not bound by the run manifest: resource_build_flight_tube_variant.lua`。
这是发布合同失败，不能当可消费场或已Fly；公共Store此次为failed，无活动native binding或reservation。
旧manifest/载荷保持原样，不补改历史manifest。

修复 `grounded_runtime._bind_retained_field_inputs` 把保留的原FieldBundle data records逐项登记为本run借用输入，
原path/retention_role/owner均不变，不复制大PA；source-free条件显式保持。
真实 `publish_terminal_state`→`open_artifact` 小文件合同验证登记后可重读、未绑定对照被拒；
analytic_ground_tracking/split_scalar_world16 PASS（6.921s），Ruff PASS。
下一安装候选只需重做6个几何/零势步骤，不重Refine；尚未把该修复标为真实完整追踪通过。

### B4 实际CPT发布角色缺陷与修复（8a8f27d0 后）

冻结c439安装的实际run `20261127_043646__sim__comsol__pulse-6a98fcb94ac5` 已完成native计算，
真实native faces=[382,436]、flag全部0，三粒子Freeze停止于22.373134802670766、23.603974615275654、
21.232021467610377us（均早于80.051373us首脉冲采样）。原CSV及SI重读为母群3/终态3、观测complete、0/3检测、
3 unknown，无补猜实体；但owner在生成completion之前因未声明initial_states.parquet角色失败。
五SCI文件虽已写出并重读，内存产品记录未持久化，`execution_completion.json`不存在，
最终为failed/finalization/inspect_writer_completion，不是已发布成功或合格缓存。

修复 `assembly_particle_tracing._declare_particle_outputs` 在write_particle_data之前预声明五SCI文件，
后续FileRecord与product路径复用声明结果，原数值/source/pulse/场保持。
实际RunSession classifier回归验证声明前拒绝、声明后真实写入/分类；
COMSOL particle/workflow17 PASS（2.259s），Ruff PASS。未把离线完整统计补造成原success completion。
原run由现有owner审计后以failed证据收尾；源和输出只能按停止后的新捕获注明，
run_config.native输入持久化的是路径，不是当时的SHA，不能宣称原native seal。
固定代码后另一次普通安装public CLI验证完整发布链是必要正确性验证，仍复用原场，0新增field Compute；
不为节省这一轮追踪另造科学导入或平行缓存权威。

### B3/B4 独立ground载体及canonical IOB候选（6412f4e4 后）

新增技术实施选择（不改写原评阅状态）：旧已发布flight_tube/detector PA0族不交供应商重开；
新 `backends/simion/grounded_runtime.py` 复用现有owner、调度、公共source guard及 `raw_collision_pa.lua`，
验证冻结原builder/tool/model/零电极与齐次Neumann边界，在新私有generation只重建两几何，
构造全新普通零势PA并逐节点/电极/FSS独立冷开，6个原生操作、Refine0/Fly0。
原frontend/reflectron借用原owner，derived metadata明确analytic而非原求解器生产；
`verified_ground_origin`认证请求、原来源、实际build/verify日志及借用记录，两个owner在实际Fly全程受保护。
原source字段中旧PA族仅作为科学/重建证据保留；低层原生track拒绝未转换的split源，不恢复旧生产框架。

`native_tracing.py` 对同一public CLI/API自动安排该运行载体阶段，cache key绑定源field identity、
实际converter/plan/owner与exe身份；无须作者另写科学配方或重Refine。COMSOL→SIMION world同样认证derived及原producer。
部署新工程profile `C:/Users/Liao/msplatform-artifacts/architecture-b-20261127/simion-engineering-standalone/stages.json`
显式新增prepare_grounded_runtime_fields预算（沿原build_geometry、async_io=false），旧profile不修改。

真实小IOB已证明canonical保存后经alias重开会按alias拼写解释相对PA，从而missing；
不是Windows文件不存在。四槽/五槽现都使用canonical IOB保存、verify、Fly，原公共alias仍作working directory，
五槽自有background也保持canonical。seed使用受审空structural seed，不先打开旧field IOB再覆盖其PA。
旧PA长路径输入的公共防写/独立短副本规则保持，未另造运输/哈希协议。

软件验证：ground/scalar/world/真实RF渲染25 PASS（root复跑16.337s）；public explicit-field workflow14 PASS（13.963s），
Ruff PASS。真实SIMION小native测试在公共host lease下验证3D/cylindrical零势+FSS、非零BC拒绝、
canonical冷开与alias负例、五槽production build_geometry_iob/iob_core priority读回；临时小PA按测试生命周期清理，
没有持久化科学run证据，不拿它代替实际仪器链。
原fixture迁移另25 PASS；共享准入3例中large-exe failure与canonical Fly协议PASS，4-unit replay例仍被旧空observation拒绝；
该fixture已改用同一split planner的真实detector面，正定向重验，其后行为不提前标PASS。
迁移同时发现并修复实际RF→OA连接查找和杆件计数旧字段缺陷；既有RF field observer仅迁到同槽布局的plan6，未扩world/noRF。

后续重验到all-reused分支又发现真实SI publisher仍读取本机SIMION版本，导致无工具完整复用失败。
现完整复用从已认证直接父complete trajectory metadata继承版本，并核对其单元index的原exe bytes/SHA；
缺失、unknown或冲突拒绝新SI发布，新/部分重算仍核验实际选中exe。没有拿Python版本冒充SIMION。
最后在共享host ledger下运行
`test_simion_tracking_units.TrackingUnitPlanTests.test_reused_version_comes_only_from_completed_matching_parent`
与 `TrackingUnitOwnerTests.test_original_owner_four_units_out_of_order_partial_replay_then_zero_calls`
2 PASS（239.523s）；含5个版本正反子例、完整100母群/4单元、乱序、部分重放6调用、完整重放0调用。
该测试明确 `native_qualification=false`，版本seam为 `inert_fixture_not_simion`；是真owner/子进程/保护协议的软件验证，
不能当SIMION仪器Fly。先前2个large-exe failure/canonical Fly协议正例已通过，故原3个共享准入待验项均已定向处理。

尚待：新普通安装后真实原fields受管派生、tracking wrapper/Fly、COMSOL→SIMION完整域、复用/GC/缺批及最终门禁。
本条是可审阅候选与相称验证事实，BA06等真实链未完成，B Goal继续active。

### B 执行检查点（c4398e9c 后）

已普通提交并推送：检测覆盖 `7761a3a4`；真实失败证据收尾 `8e4020b4`；
显式SIMION场引用 `ffc819cb`；COMSOL detector候选 `c4398e9c`。
原有未跟踪artifacts及无文本差异的工作区状态保留，不reset、不合并主线、不改写远端。

冻结 `c4398e9c` 用git archive建立独立仓外source，普通PEP517隔离构建wheel，
wheel=5,860,818字节、SHA256 `6A98178E4AD4DE6CA22CBEE79AB8E7B81DB806A96F9AEC0FBA8A61BC74FE1D89`，
安装在 `C:/Users/Liao/msplatform-artifacts/architecture-b-20261127/installed-c4398e9c`。
最初no-build-isolation尝试因本地缺bdist_wheel失败，随后使用声明的隔离build依赖成功；未改pyproject或共享venv。
实际仓外已安装 `python -I -m msplatform run` 沿原COMSOL作者/场启动
`20261127_043646__sim__comsol__pulse-6a98fcb94ac5`；本记录时仍运行，不把启动或preflight当PASS。
完整命令、部署和日志位于 `.../comsol-installed-c4398e9c/environment.json`、`native-run.log`，
输入仍是原 `batch_b_comsol_small_cli_20261127/oa_split_tof_comsol_small_reused_v1.toml`。
最终同代码双发行离仓验收尚未执行；当前安装只用于该候选的真实CPT，不冒称BA15完成。

### B3 生产理想pulse与线性PA组合原生探针

普通c847已安装Python `-I split-linear-pulse-probe/run_probe.py --environment <simion-installed-c8479985/environment.json> --workspace <原共享workspace> --profile small_native --execute`
运行 `20261127_042546__analysis__simion__split-pulse-490bd1400a1d` 成功，manifest
SHA256 `4C0BE663B1ABEC67B7AA722AA7F9E900248398DBDD719CFEEDFD9A91F5EB5D39`；
真实generate_pa/probe两操作，Compute0/Refine0/Fly0；新建9³合成线性PA，未改原仪器源/场。
production pulse hook、model_drive/waveforms、adapter/composer均来自该固定安装，SHA绑定于
`C:/Users/Liao/msplatform-artifacts/architecture-b-20261127/split-linear-pulse-probe/frozen.json`
（SHA256 `E60916B233AC4EE747FBBF4AAED48DE7877C08F22D69789FC396D00F5F5CCE7A`）。
原Study pulse start80.0513730009902us、width7.2727272727272725us、epoch0us保持。
独立 `validate_probe.py <owner>/results/pulse-cases.tsv study.json epoch.json` 再次PASS5点：
start−ε关、start开、中点开、end关、end+ε关，原OA全部static/pulse组电压与合成PA梯度匹配。
这是实际生产理想gate/模型电压及两标量基底选择机制，epoch+elapsed由探针显式映射；
不是仪器E/V精度、真实particle flight、solver运行时clock callback或非理想波形资格。

### B4 COMSOL检测器生产候选（ffc819cb 后，待真实CPT）

`backends/comsol/assembly_particle_tracing.py` 从同一Assembly冻结作者有效面/变换/组件身份，
原OFF/ON几何投影和geometry_validation必须一致，不从其他solver或粒子坐标猜观察面。
`matlab/trace_assembly_particles.m` 在实际守护模型上检查propagated detector∩vacuum的完整三角面网格，
使用原冻结1e-6mm/normal_abs阈值判定平面、有限半径和法向；所选面Wall Freeze+辅助标记，
其余metal/outer/ideal原互斥全覆盖合同不变，原source/pulse/field/mesh不变。
`backends/comsol/particle_data.py` 仅在新合同及标记存在时提供检测观测，使用原生stop-time/Freeze6D生成事件；
旧CSV仍unavailable，缺标记为incomplete，不能补猜。
实测官方完整版本串 `COMSOL Multiphysics 6.4 (Build: 293)` 现被严格接受，release预声明并保留失败输出。

`.venv/Scripts/python.exe -m unittest tests.contracts.test_comsol_particle_tracing tests.contracts.test_comsol_workflow -q`
17 PASS（2.086s），Ruff PASS；含已监测0-hit、命中事件Parquet重读、缺标记/无合同拒绝及旧CSV。
同一public `msplatform validate` 对原仓外COMSOL作者和已恢复OFF/ON场预检通过，留存
`evidence/comsol-detector-candidate-preflight.json`；native_verified=false仍明确保留。

完整面网格0Compute只读run `20261127_042330__analysis__comsol__boundary-e6dbd2af84c3` owner成功，
manifest SHA256 `CD89FA7095715AF07565897FB1456F837CCACFD2E1909ECBA6B15E8C34116AFA`，未保存原模型。
候选382/436分别181/375三角、112/215顶点，平面误差0、最大半径40.000000000000014mm、无退化；
其余8候选平面偏差1mm被拒。旧Cylinder采样只选382，不足以全覆盖，因此生产从现场网格求集合而非硬编码ID。
独立盒子v3的32,438网格元素及真实mesh1绑定、三粒子6D/stop/flag解析结果已独立复核。
这些均不冒充仪器CPT新代码已通过；下一步从本主题冻结安装候选，使用原作者/场和新运行身份实际复验。

Changed汇总现已结束：FAIL（357.728s），5阶段通过、3失败、15阻断。
除1个缺Lua安装测试外，22个field worker/transport/tracking软件fixture仍使用已退役composite，
在进入测试主体前被guard拒绝；其后行为未验证。Agent2正按split公共输入迁移fixture，不放宽退役守卫。

### B2 显式SIMION场引用与只读科学准入（8e4020b4 后，提交见 Git）

`recipes/native_assets.py` 复用已有source-free FieldBundle机器合同冻结小manifest；
`workflows/simion_field_reference.py::admit_simion_field_reference` 从冻结Study独立重编完整模型，
校验field numerics/design/bank、成员载荷、downstream空间身份、clock与owner，不另建配方权威。
`native_tracing.py` 接入预检与全生命周期原生source guard；选择引用时跳过geometry/model/solve，
缺件无回退。原field producer与当前trace实现分别记账，路径不进入科学身份。

实际命令 `.venv/Scripts/python.exe -m unittest tests.contracts.test_simion_field_reference tests.contracts.test_native_workflow tests.contracts.test_native_asset_recipe -q`
14 PASS（12.187s），Ruff与diff-check PASS。执行图夹具断言track期间guard仍持有且三个构建入口均不调用；
该夹具不是真实native轨迹。
真实发布场 `20261127_031207__sim__simion__fields-9cb9e717bba3` 的manifest SHA256
`FEEE0346CDED73BFE8E950FE191AB1C9401915D51D3EFFBD1BDE18F9D4CDBA80`，
60项实际数据与完整科学合同只读准入PASS；原生操作0，不改原manifest/载荷。
留存的可复制命令 `.venv/Scripts/python.exe C:/Users/Liao/msplatform-artifacts/architecture-b-20261127/explicit-simion-source-study/verify_readonly.py`，
同目录保留作者TOML、原Study/clock字节及 `readonly-admission.json`。
首次外部作者误用绝对manifest path被现有公开规则拒绝；改成作者相对路径后通过，未放宽解析规则。
此准入仅证明科学源可复用，旧flight_tube/detector PA0 family不可直接供应商重开；
下一步使用原owner受管派生新的standalone零势载体，保留原PA族及其原删除owner，不重复昂贵Refine。

### B4 真实CPT失败证据收尾（7761a3a4 后，提交见 Git）

入口 `execution/owner.py::resume_failed_evidence_finalization` 限定已审阅的
`20261127_032027__sim__comsol__pulse-8cca4fee9218` 及冻结action/MATLAB/task/completion身份；
不会从文件后缀推测角色，也不会升级科学结果。三份native输出的Windows禁写/禁删句柄覆盖身份核验至最终发布。
恢复证据保存原result/journal字节及摘要，注明停止后捕获而非原始native seal；原completion不改写。

首次真实调用因未显式传原生保留completion policy在写审计证据后停止；未删除或回滚证据。
新增受限partial接续验证原始外部evidence及精确journal差异，使用原
`backends.comsol.assembly_particle_tracing._comsol_batch_completion_api` 完成同一终态收尾。
实际 `evidence/cpt-failed-evidence-recovery-input.json`、`...-result.json` 位于
`C:/Users/Liao/msplatform-artifacts/architecture-b-20261127`，可重现原审阅身份。
最终 `status=failed, stage=complete, writers_confirmed=true, resume_action=null`，
manifest SHA256 `D4CD9B619465668BE590A2CA7E83FC0507417E4D447BED58909AC91038F65ECC`；无products。
release/facts/CSV/recovery各一条required_evidence输出，实际摘要独立重算匹配；
completion仍为 `BA43206EABDED23C9E316F433AB07F22B016C1AB85D8E1BB92BBF819B6E54D5B`。
capacity released、source_protection_leases=[]、原lease文件不存在、共享host DB无原token活动记录。

`.venv/Scripts/python.exe -B -m unittest tests.contracts.test_owner_additional_evidence -q`
6 PASS（1.783s）及Ruff PASS；测试实际调用_finalize/_publish/retention并复现缺policy后接续，
终端发布与capacity在该软件测试使用替身，完整账本证据来自上述真实收尾，二者不混淆。
尚未把失败CPT归为合格缓存；下一步用新实现与新运行身份执行native检测器链。

### B3 原生解析探针与负结果（不等于仪器精度资格）

真实 SIMION 8.2.0.11 受管分析 run `20261127_040451__analysis__simion__split-linear-358b84377f9f`
成功发布，manifest SHA256 `FE0EF84C142724BACF69FAB689474EE1C2C8488904D2189D26FEA646899246A1`。
脚本位于 `C:/Users/Liao/msplatform-artifacts/architecture-b-20261127/split-linear-probe`；
实际 `generate_pa` 与 `probe` 两操作，21项包括非零原点、非等距网格、两线性电势独立解析梯度、窗口边界、
超支持域与坏mask拒绝。预置机器舍入容差 V=1.0800249583553523e-11 V，E=2.1600499167107046e-11 V/mm。
composer 的时间门在此探针中是局部测试函数 `[1,2)`，因此只证明原生SDK采样和两基底组合运算，
不将其冒称为原仪器 V(t) pulse/epoch 的验证，也不是 COMSOL→SIMION 插值精度资格。

COMSOL 零力辅助变量探针 run `20261127_040750__analysis__comsol__detector-aux-5e61e6437d3c`
owner成功发布，manifest SHA256 `9ED5CBEF63E2400A658EC86A3AC3ADFA1EAFE0D5E64D975F5DFD138FE6711D80`；
但实际 `validate_probe.py <run>/results/probe_results.json` 失败：三粒子坐标、速度、hitflag为null、fs=0，
独立直线解析检查不通过，不能据owner成功报告物理或检测能力通过。
外部探针位于 `C:/Users/Liao/mass_spectrometry/artifacts/batch_b_comsol_detector_probe_20261127`，
保留原输入和失败证据，下一步排查释放设置并用新身份验证；原仪器source/pulse保持原义。
独立零Compute几何面检查已按共享调度启动，结果待核；不据其启动宣称有限面归属已完成。

v2 (`041926__analysis__comsol__detector-aux-039d2f62ddc1`) 显式激活cpt/求解序列后仍有相同null结果；
实际study绑定 `geom1, nomesh`。新v3仅为独立合成盒显式建立小网格并检查绑定，未改仪器网格或原输入。
真实run `20261127_042239__analysis__comsol__detector-aux-28a1f7c0a5fb` owner成功，manifest
SHA256 `66987517181E2187D6D7B543971D1B749BF06D6A40902664B3AB9BA715E840F4`；
使用同一原始 `validate_probe.py` 独立检查实际6D、stop time与辅助标记，PASS：target1/other0/not_arrived0，容差仍1e-6。
该结果只证明零力盒子的真实Wall Freeze+辅助标记机制，不替代仪器有限面归属、实际电场或探测效率资格。

### B 当前接续检查点（3ae2a0bf 后，Goal 继续）

- Agent 0 核对 HEAD `3ae2a0bfcfe4c4758f612fbf7e79185bc37d1bd0`，任务 tracking branch 已普通 push；保留已有工作与 artifacts，不回退审计提交。
- 已安装 e95f6705 的 SIMION→SIMION 公共 CLI 成功：Store `52dde608d07245b99185f77da95c9a17`；原 owner ground `20261127_052420__sim__simion__ground-e80d5922d785`、track `20261127_052524__sim__simion__track-152081d324db`。真实 Fly，0 新 Refine/场 Compute；母群/终态/检测观测均 3，检测 0，unknown 3，分析不适用，不能解释成已归因物理损失。
- 同安装版本的 `native-reuse-acceptance/acceptance.py` 已完成 first/repeat/k2/damage/repair/gc。K2 为同质量100 Da、电荷+1的3粒子权重1和+2的2粒子权重0.5，完整母群5、总权重4、0 hit。缺件只删专属Store中443 B `reference.json`，只重算原trace，场和另一物种trace保留。准入自动GC删除登记215153 B的合格候选；未持久化 released_bytes，不能声称独立测得物理释放量。完整事实/命令见外部 `C:/Users/Liao/msplatform-artifacts/architecture-b-20261127/native-reuse-acceptance/acceptance-summary.md`、config/state及各阶段log。
- 补充实际公共库 API `run_recipe` 重放成功：`installed-standalone-b1/Scripts/python.exe -I ./api_repeat.py`（离仓工作目录为上述 acceptance 目录）；Store run `cc1fee3193224eb08caed33742482dc1`，ready/succeeded/complete。`api-repeat-before.json` 与 `api-repeat-after.json` 均32个原 owner目录且逐项相等，`stage_productions=[]`、无native控制记录，保留完整前后清单。原six-stage脚本repeat/gc仅有增量记录，不能回填为各自均独立保存清单。
- COMSOL→COMSOL 固定 e95f6705 安装的 `20261127_054319__sim__comsol__pulse-cf4b85430700` 仍在真实CPT计算，原场复用；不修改其 b1安装环境，不把旧失败CPT当通过。
- COMSOL→SIMION 首次已安装CLI实际失败于 `field solution borrowed model binding differs`，在export前退出，未新Compute。023910恢复产品是 captured_model/captured_compute_report 的共驻双解，不是旧borrowed_solution。Agent 1 在唯一现有 `assembly_field_export.resolve_model_source_manifests` 增补该明确恢复合同：恢复request、双产品模型/报告一致、冷重开、原失败producer completion的角色与writer退出/释放证据；保留 after-stop identity，未把MPH捏造成原producer输出，未重哈大型MPH。
- 根复跑 `python -m unittest tests.contracts.test_comsol_world_scalar_contract tests.contracts.test_comsol_scalar_multigrid tests.contracts.test_assembly_scalar_owner_fill tests.contracts.test_simion_prepared_model -q`：35 tests，7.107s，PASS。Agent 1 的26 scalar tests/Ruff PASS；fixture补明确product_id，不放宽生产校验。真实023910 background/on只读解析通过，不等于export/Fly通过。
- 下一步：独立复核、提交解析修复后建新的普通wheel和隔离env2继续CS；b1保持冻结。最终代码仍须普通wheel/sdist重建wheel离仓验收、实际Changed必要门禁、最终CLOC和BA逐项对账。本节不能作为整批B完成声明，不启动C。

### B6 旧资格入口的精确边界（ad385834 后只读对账）

Agent 4 沿真实入口复核，BA14 的结论是**新链不继承 Candidate/Formal 总等级**，不能写成全仓旧 Candidate 已全部退役。一次性调用栈证据在 `C:/Users/Liao/msplatform-artifacts/architecture-b-20261127/evidence/b-retirement-final.md`。

| 旧入口 | 本轮状态／剩余入口 |
|---|---|
| SIMION `tracking_execution` segmented_upstream/state_relaunch、operations HandoffResult、OA–TOF相关registry/schema | 本轮新执行拒绝跨组件出口再释放；原始母群/坐标/clock与合法分批保留。公共连续入口为`msplatform run`、native_tracing、simion.track。 |
| 固定五质量single_reflection_mass_spectrum_study / simion.mass_spectrum | 旧新运行及续跑拒绝，历史结果只读；新mass_scan以显式物种/母群运行。 |
| COMSOL旧composite粒子求解、Formal Validate/retrace/旧MATLAB粒子builder | 对应新求解拒绝；geometry-only/field-only及历史Verify/Publish/Recover按原证据门槛保留；未做MATLAB guard原生正反例，不能宣称这一层真实通过。 |
| oa_candidate.run_candidate → candidate_simion_stage → run_n100_transport.ps1 | **仍可达的C旧实验**：当前源码以生成N100 ion为本地显式初态做一次整体Fly，未发现消费上游跨组件出口再释放的依据。不能说已全部退役，也不能将旧OATOF_CANDIDATE=PASS作为新链等级。默认COMSOL粒子模式被旧composite guard阻断，完整旧Candidate当前可用性不宣称通过。 |
| oa_candidate.run_compensation / execute_oatof_compensation.ps1 | 原source.ion三臂独立实验，保留C旧owner；未发现跨组件出口重释依据，不因名称一刀切删除。 |
| IP–MR registry、accelerator_interface -FullJoint、prepared_joint/trial、assembly/handoff readers | 未迁C活跃链／历史母群、坐标和时钟读取；本轮不能声称全仓segmented清零。普通OA→MR prepare_interface只准备接口。 |
| RF schema12 recorded-birth | 编译/源/clock/完整母群合同已迁，真实RF recorded Fly未验证。BA06三组合的SSA小N使用原OA源，不等于RF整机native验证；本轮不新增RF研究。 |

门禁事实继续保留：ad385834首轮repository_text_bytes失败于未显示为语义diff的一处CRLF，机械LF后通过；第二轮documentation发现下游新provider README缺根README导航，已补实际链接。第三轮实际完整installed测试仍构造schema11/SFI旧composite正例，被退役guard拒绝。Agent 2仅更新这段验收为owner/native前明确拒绝，保留独立历史reader和RF-IP/IP-MR/offline_scalar，不能为绿灯更改三基场物理或恢复旧框架。该轮gate尚非PASS，最终证据待后续记录。

解析修复提交已为 `ad385834ec8aefb0266c5636b17007ca3806bfd8` 并普通push；其普通wheel已从git archive构建，SHA256 `908f124ec150b757e68ea98b580e8f2c9acd199caeb4c156c016904a995ad2a5`，独立b2安装成功。CS公共CLI新raw `20261127_060451__analysis__comsol__assembly-scalar-c873ceeda982` 已越过旧失败，五网格输入冻结；账本证实因CPT `heavy_stage_active`等待COMSOL重阶段，不能以已创建运行当导出成功。b1 CPT环境未更动。

### B 原生CC通过、CS仍待修复（ad385834 后最新接续）

- **COMSOL→COMSOL已实际通过声明的小N闭环**。固定e95f6705/b1公共CLI运行 `20261127_054319__sim__comsol__pulse-cf4b85430700`；Store `28234aa32d4e45bdb3da93a4883a0167` 为 succeeded/ready。Agent 3用安装后的公开 read_particle_data/summarize_particle_data/analyze_mass_scan 重读，20个发布文件的manifest/SHA闭合，3母群/3初态/3终态/12轨迹样本完整。3个冻结birth的SI位置、速度、质量、电荷、权重与原算法重新采样逐项一致。原OFF/ON场explicit-reference复用，仅生产1个trace，未新求场。
- 原生worker PID9988/creation与Store观测相同，exit0，host released；仅核对CC自身3 claims、reservation、binding/writer、workflow容量lease均已结束，不要求正使用同源的CS释放其合法保护。usage最后running/1649.538s是陈旧快照，不作当前活性或最终耗时依据。3.08GB MPH只对原record/manifest身份，不重新读取或哈希。
- 检测面382/436，观测complete，0 hit，总权重3；native status2的三个终态为unknown，停止时刻22.373134803、23.603974615、21.232021468 us。原pulse开始80.051373 us，**全部早于ON停止**；每粒子的0、80.051、90、100 us采样中，停止后的坐标/速度为Freeze保留状态，不能当仍在飞行或据此授予ON响应验证。峰形/校准not_applicable；不改birth来制造命中。证据 `C:/Users/Liao/msplatform-artifacts/architecture-b-20261127/evidence/cc-installed-acceptance.json` / `.md`。
- **CS仍未通过**。ad385834/b2新raw `20261127_060451__analysis__comsol__assembly-scalar-c873ceeda982` 已成功原生导出OFF五grids，0 Compute；CLI随后在本地support分类失败：grid1索引195007，world `[56,-37,-0.929186803411028]` mm同时属于 `oa/grounded_shield` 和 `tof/common_ground` 实体内部，原FEM mask0。原shape_query严格拒绝不同group interior，不能选一个owner绕过。world/birth已形成support，grid1失败，尚无ON导出/Fly，不能以raw成功代替整链成功。
- Agent 1确认上述两组OFF/ON均精确0 V；原COMSOL真空由outer扣全部solid（keepsubtract/propagatesel），两组外露边界20/35面、交集为空。新技术选择仅为**多组同电位导体内部填值**：保留完整group集合，每一工作点全部电位严格相等才填；不同或未知继续拒绝；boundary/unsupported不晋升；默认唯一owner查询保持拒绝。prepared CSV labels升级版本2并绑定identity，每次ON复用重新校验全部组电位，不用OFF相等偷偷合并owner。这不改几何/BVP/原电压，不等于原评阅额外批准。
- 为保护仍在自然收尾的失败Changed gate，在 `C:/Users/Liao/msplatform-artifacts/architecture-b-20261127/overlap-worktree`（detached ad385834）隔离实现；主repo生产与b1/b2安装保持冻结。Agent 1负责3个fill/query/export生产文件及相应v2测试；Agent 5仅负责两个COMSOL recovery fixture（真实8组RF Assembly/provenance与inert launcher），不改生产guard。Agent 2修旧SFI正例为明确拒绝，保留历史pure oracle、reader和IP/MR合法消费者；最终普通双发行验收等新candidate整合后再运行，避免已知非最终版本重复安装。所有未通过门禁保留原log/summary，不能称仅环境问题。
- 当前矩阵：SSA真实通过、CC真实通过、CS正确性失败待以上最小修复/再验；Goal继续。最终BA01–BA15、必要门禁、普通wheel/sdist重建wheel、完整CLOC、提交和远端同步尚待收尾。不启动C或额外RF研究。

### B3 同电位重叠支持实现验证（隔离候选，待native）

Agent 1在隔离worktree交付六文件：shape_query、assembly_scalar_fill、assembly_field_export及shape_query/scalar_fill/prepared_support测试。Agent 0独立运行shape/scalar/support/owner_fill/multigrid共50项，8.676s PASS；新增world_scalar_contract 8项由Agent 1运行PASS，Ruff/LF PASS。Agent 3独立只读复核未发现阻断正确性缺口。真实point OFF/ON完整双组0V、改变一组拒绝的脚本/结果在 `C:/Users/Liao/msplatform-artifacts/architecture-b-20261127/overlap-point-evidence/check_point.py` 与 `result.json`；不读/哈希MPH。

默认查询继续拒绝多组，显式prepared-query选项只报告完整集合，不授权单一owner。strict interior全参与组电位每工作点精确相等才填；boundary/unsupported保守不填。CSV `index,group_ordinals_v2`严格排序/唯一完整组序号，复用时重查各节点完整几何组和当前电位；support identity绑定v2标签与查询版本，拒绝活动v1复用。保留历史v1原文件只读，不回写。

现有COMSOL实现身份同时进入raw export和support的cache key；本次代码升级将保守使原raw stage miss，需要再次冷导出但仍0场Compute，不为省这次重导出新增作者权威或缓存框架。既有同版本SSA缺件局部/0native复用事实不因此改写。隔离候选先冻结六文件做b3真实CS，主repo仍供原失败gate健康分片自然收尾；等该轮结束后安全快进整合并普通push，不在活跃源闭包下热改。此处软件PASS不能代替CS native PASS。

### B 原生脉冲解析基准与最新CS阻断（0a4b7651 / 9d1556d4）

- 原instrument N3不改birth。另用synthetic N1做受管真实Fly，冻结原pulse起止、0.001us最大步长、100 Da/+1e、10 V/m线性ON场及独立SI分段常加速度解；五个开前／中／关后采样PASS，最大位置误差1.6791164e-8 mm、速度误差3.130741e-6 m/s，均在事先固定的0.0002 mm/0.02 m/s与time 1e-7 us内。0 Refine、0 COMSOL Compute，SIMION8.2.0.11。完整成功run `20261127_062747__analysis__simion__pulse-fly-30ed2c9dc75e`，manifest SHA `419AA7BEDC71B7D02EB9D8512AF40B1946A58D7DB49A2F4703D39162B9C5C3B6`，writers_confirmed、stage complete；原公共canonical IOB/production scalar/pulse回调，无新PA路径。外部 `C:/Users/Liao/msplatform-artifacts/architecture-b-20261127/split-linear-fly-probe/README.md`、run_fly.py、validate.py及authority.json载明精确命令/参数/来源。这只是ON回调机制和数值基准，不是仪器场准确度、命中或Formal资格。
- 首个微型run `20261127_062623__analysis__simion__pulse-fly-4227fdd7e6ca` native与解析也完成，但漏声明私有IOB seed，retention失败。后续只读核查明确：**已有原success completion**、四worker exit/release，result failed/finalization、manifest checkpoint，容量lease仍active；不得当作无completion失联、覆盖原completion或私改ledger释放。seed由冻结build_iob.lua创建3×3×3，不是复制16MB安装placeholder；与第二run的同生成器/388B seed事后字节完全相等，仅说明after-stop身份，不能称v1原native封存。Agent3在外部recovery-v1做严格只读评估，是否可用原正常_finalize恢复原publication尚待完整审查；目前没有执行维护，没有将v1算合格。v2独立成功保持原记录。
- overlap实现冻结提交 `0a4b7651986facd1956cf9aaa2c17d811bc7c63f`（六文件），CLOC2.10实际PASS日志 `C:/Users/Liao/msplatform-artifacts/architecture-b-20261127/0a4b7651-cloc.log`。隔离b3普通wheel安装成功，CLI实际已完成OFF/ON五网格原生导出与全部支持派生，原grid1重叠点在两工作点均成功通过；派生requested native_operations=0。
- b3随后**未进入Fly**，失败 `co-resident computed and cold-reopened native evidence differs`。Agent1逐项核对10个字段及路径均相等；真实MATLAB JSON用 `6.27792E+6`/`7.0E+6`，解析成精确整数值的float6277920/7000000，SIMION COMSOL-source reader仍额外要求Python int，拒绝了合法表示。已限定复用COMSOL现有_native_exact_count的严格正整数、有限、<=2^53检查；不改报告、mesh限额、字段相等性或源manifest，不放宽科学校验。修复候选尚待验证，b4暂不盲跑已知同错。
- 同时发现0a输出policy字串仍旧unique语义；独立候选 `9d1556d4607c56678d954f167e29e03c27fa36b5` 已统一两producer和active consumer为 `equipotential_dirichlet_solid_interiors_v2`，历史artifact读不变、旧活动policy拒绝。根独立26 tests 10.828s PASS，Ruff PASS；b3环境不热改。仅metadata候选还缺上述native整数表示修复，不能称最终CS通过。
- 主任务分支仍为ad385834且与origin同步，保持正在自然收尾的旧Changed源闭包；上述两个隔离候选待该轮结束后安全快进整合/普通push。Agent2已修旧entry拒绝/纯历史fixture、7个capabilities split正例，Agent5已修真实8组RF几何provenance recovery与public dispatch fixtures，各自定向PASS，尚待最终代码双发行和相称门禁。当前SSA/CC声明范围真实通过，CS仍正确性失败；Goal未完成。

### B 接续：来源保护与最终软件复验准备（2026-11-27 07时）

- 旧广Changed已自然完整结束，正式结果仍FAIL：PASS7、FAIL4、BLOCKED23、NOT_APPLICABLE19；四machine_contracts分片失败，不把blocked当通过。原 `evidence/final-changed-ad385834-docs.log` 与 `-summary.json`保留。源读取冻结已释放，主分支已安全快进隔离候选链至 `3398c72d7ac49a17668e4be3ae9a036994a00fba` 并普通push，原本地WIP不覆盖。
- 新source计数修复为 `57152517cacea2e6784fa93eda09a417df9121f5`，根26 tests 10.182s PASS。其普通wheel SHA `80d9d08a19d72df54286dd4b6520d8c3c374947eb04c71451e6d963c0354efdd`，安装b4后实际越过计数检查：OFF raw `20261127_064653__analysis__comsol__assembly-scalar-a79a821798e1`、ON raw `20261127_065051__analysis__comsol__assembly-scalar-37d391b62445` 与十个v2 supports完成。COMSOL源场依旧复用，未新Compute。
- b4尚未Fly：`20261127_065525__sim__simion__world-8450b7246601` 在进程启动前正确拒绝 `model geometry member has no active owner protection`。两个缺失直接owner为原015508 pulse-basis与012811 prepared-model；顶层恢复product保护不传递。该run summary/manifest/completion均failed、operations/releases为空，实际lease已释放、ledger ready、无b4活动进程；capacity_session日志的active是旧快照。Agent1隔离修复显式核验原来源再加入source_references，原保护guard不动；首轮23个world/binding tests根独立11.550s PASS，随后补审正常来源显式prepared依赖，尚待最终交付/原生重试。
- 旧gate失败对应fixture已分项处理：COMSOL geometry/prepared/field Source改真实8组RF或真实split Assembly/manifest provenance；recovery两项166.729s PASS、electrostatic8项/root2.175s PASS、stationary11项PASS、geometry7项PASS。publisher补真实非空expected ops与身份负例，5项PASS；Lua empty-surface六场景为末位gsub多返回参数污染，括号取单值后原全部正反例PASS，生产参数未改。SQLite owner-failure fixture明确事务后close，模块2项PASS且本次Temp cleanup成功；原gate唯一持有者未证明，未归因生产子进程或删除残留。
- Agent2保持历史pure reader/basis/窗口/renderer/oracle，旧schema11/SFI真实复飞及recovery正例改明确guard+owner0；entry3、tracking8（17.993s）、refinement3（13.810s）定向PASS。真正RF-IP场景清除借用split fixture的TOF观察污染，原Lua/HS1/输入反例保留；capabilities7项5.225s PASS。installed probe迁当前split执行、旧路径明确拒绝，并保留RF/IP/MR及历史读；完整发行尚未运行，不以开发树抽取片段冒充installed PASS。
- 微型v1 benchmark已按原success completion完成一次性私有维护，原completion SHA `E99575C91BBC472D481AA33C7B2BB4874F14A6A29808B1932885D9AB688CB7E5`及字节不变，无产品、physical_qualification仍not_granted。新增seed/audit均入manifest，retention removed=[]，ledger ready/pin/310659 B、原lease消失、result complete/released、公共resume再执行无副作用。原result/journal/completion字节在外部及run audit保全；seed身份仍after-stop对比。不是新增公共恢复能力，不改写首次retention失败历史，不启动vendor、不删文件。外部 `split-linear-fly-probe/recovery-v1/maintenance.py` 与记录保留。
- 最终验证决定：完成来源保护并冻结最终candidate后，仅运行一次公共实际增量Changed（`ad385834 → final_sha`非空路径），执行目录所选完整适用阶段，内含普通wheel/sdist重建wheel两臂；不另重复full installed、不跑Owner/Repository或大型研究。旧PASS可以作为各自原代码证据，不能拼成官方Changed PASS。最终CLOC/BA对账/实际CS成功仍待完成，Goal保持active。

### B4 显式原owner保护补齐（556303d5 后）

`split_scalar_workbench._basis_original_owner_refs` 仅提取成功field_solution中真实manifest-bound的prepared_manifest；明确依赖才保护，无依赖不扩权。已审captured共驻源继续经原resolver及原recovery request核对failed/prepared双来源，不把顶层保护当传递。原manifest禁写句柄持续到native owner结束，两个原owner显式进入source_references；worker `_protected_source` 原样保留，不复制MPH、不改删除归属。

根在整合后的主工作树运行 `python -m unittest tests.contracts.test_split_scalar_world tests.contracts.test_split_scalar_binding -q`：24 tests，11.147s PASS；真实惰性capacity lease验证消费时受保护、正常/异常结束释放，缺/篡改/未绑定原manifest拒绝，普通明确prepared依赖可用、无依赖不扩权；Ruff PASS。该单元尚待公共已安装b4重试，预期COMSOL原采样/support按真实key复用，必须以实际阶段与worker记录证明；不预先称0native或整链通过。

### B 用户入口合同同步（1868fc2c 后）

`docs/TRACING.md`与`docs/COMSOL_BACKEND.md`已同步等电位多组支持/v2标签、保守未知边界、逐工作点重核及不授物理owner/精度；`docs/tools/COMSOL_API.md`记录实际MATLAB JSON精确网格计数的格式与唯一验证helper。参考初态snapshot的version1/lineage与已验证原生birth的version2/primary_birth在用户入口明确分开。下游provider README补仓库README导航。此单元只维护当前合同与导航；实际native/gate通过范围仍由本页对应证据记录，不因文档更新提升资格。

### B3 world成功后的显式selection接线（3e2c52f1 后）

de88重试重新采样OFF/ON（原场0 Compute），其world `20261127_072142__sim__simion__world-cfea186ecb50` 四项实际exit0、summary/manifest/completion success、writer stopped；27个显式source refs已含原015508与012811，证明保护修复越过原失败。track `20261127_072417__sim__simion__track-fda5a79a70e5` 在启动native前失败，原因为workflow未传现有scalar_field_basis参数；0 operations且正常failed/已释放，未补造SCI或Fly。

`workflows.scalar_tracing.run_scalar_stages` 现将用于world的同一selection显式传入simion.track，不从metadata另建authority、不取消guard。spy回归核对完整geometry、OFF/ON及两个有序窗口一致。根执行scalar_workflow/split_scalar_binding/split_tof_tracking共17项，7.315s PASS；Ruff/LF PASS。该接线仍须用新安装版本真实Fly验证。bridge_source整体身份会保守使已完成采样/world阶段失效，实际重算须据回执报告，不声称代码升级零重算；不因此扩大缓存重构。

### B4 三个原生组合闭合（08eab366代码快照）

COMSOL→SIMION 已由普通wheel安装的公共CLI完成，Store `b3bac2eedb3340318a6d8531f8e5e8f5` 为 succeeded/ready；原SIMION owner `20261127_074232__sim__simion__track-fe43712319cc` 完成 build_tracking_iob、verify_tracking_iob、track_fly 三项操作且均exit0，包含一次实际Fly，不是三次Fly。原geometry/prepared/field/collision五个资产阶段复用；OFF/ON冷采样、支持、world、trace二十二阶段本次新做，原COMSOL场0 Compute。源码变化保守使采样键失效的事实保留，不把升级运行标为0native复用。

公开SCI重读为3初态、3终态、0事件、3个birth轨迹样本；后续请求采样时刻已晚于原生停止，不补造轨迹。detector观测complete、0/3命中、总权重3、unknown归属3，arrival/峰拟合/校准不适用。停止时刻23.00、24.27、21.83 us，均早于原pulse起点80.051373 us；未改变birth制造命中。此新链功能证据与真实N1 ON回调解析基准相互独立，不能据此授予仪器ON响应、跨后端数值等价或统计精度。

| field_source → particle_tracer | 实际版本与本机条件 | 已安装公共新链小N事实 |
|---|---|---|
| SIMION→SIMION | e95f6705/b1；SIMION8.2.0.11 | Store 52dde608d07245b99185f77da95c9a17，3/3终态、complete 0 hit、unknown3；1 Fly、无新Refine/场求解；后续N3/N2多电荷和局部重算实证见前节。 |
| COMSOL→COMSOL | e95f6705/b1；COMSOL6.4 Build293、MATLAB R2025b | Store 28234aa32d4e45bdb3da93a4883a0167，3/3终态、12记录样本（停止后Freeze）、complete 0 hit、unknown3；1 CPT、原OFF/ON场复用。 |
| COMSOL→SIMION | 08eab366/b4；同COMSOL/MATLAB及SIMION | Store b3bac2eedb3340318a6d8531f8e5e8f5，3/3终态、complete 0 hit、unknown3；OFF/ON五网格各冷采样0 Compute、支持/世界完成、1 Fly。 |

三格均为明确外部给定场、真空/B=0、已声明几何/源/时钟/脉冲的受管小N技术验收，不是任意Assembly、RF、碰撞或自洽能力。COMSOL有限外框Dirichlet与SIMION Neumann不是相同BVP，不以终态时间接近声称等价。原生字段无法给出物理接触归属时保持unavailable，不按末位置猜电极。

CS普通wheel SHA256 `6257E0064C2240788172DCE9AEAEE3360440046056D96789FE233F01BA0AF527`；作者SHA `646D263200FEA2C2733241E6841773FA1654B16BF7FC7BEA762FB024D803C5A9`、resolved SHA `BB37B6AACF2CA68D629B0F557AAE33836EEC127C191D7C3547122323187810F3`。完整manifest身份/窗口/软件版本在`scalar-installed-study/cs-final-matrix-evidence-08eab366.json`，同版本重放证据在`scalar-installed-study/repeat-08eab366/evidence.json`。

CS有效域与掩码：每工作点world675783点/原FEM有效639620、birth11475/11475、grid1 252450/229024、intermediate2 252450/236930、exit252450/244978。FEM无效点不是一律填零：只对语义几何证明严格导体内部且本工作点全部参与组电位精确相等者生成v2支持；world原36163个FEM无效节点中35279个严格导体内部填值、884个边界保持无效；其余boundary/unsupported保持拒绝。实际原生调用证明选定窗口与support可消费，不替代全仪器插值收敛。独立SDK线性场、真实N1分段常加速度和COMSOL零力解析基准的事先容差及实测误差见相应前节，未看结果后放宽容差。

主要逐字节/运行证据位于 `C:/Users/Liao/msplatform-artifacts/architecture-b-20261127/`：`scalar-installed-study/result-evidence-08eab366.json`、`evidence/cc-installed-acceptance.json`、`native-reuse-acceptance/acceptance-summary.json`，作者/resolved、环境、源码身份与原owner引用均保留；旧失败原run不改写为成功缓存。

### B 最终验收对账（随最终交付记录更新）

| 验收 | 当前事实与限制 |
|---|---|
| BA01 | B0四项定向实修通过；原A writer/source_bytes/历史reader修复保留，未重立项。 |
| BA02 | 共同Recipe/CLI/API、独立field_source/tracer、预检拒绝和三格实际入口通过。 |
| BA03–04 | 独立OA/不含OA下游、注册/编译/geometry/drive/source消费闭合；冻结旧45电极oracle及原源/驱动/clock核对。RF recorded-birth已有软件迁移，未执行RF原生Fly，不外推。 |
| BA05 | 原V(t)/epoch保留；SDK原pulse和实际N1 Fly独立解析验证通过；仪器N3均早于ON停止，仪器ON效果未验证。 |
| BA06 | 三格实际已安装小N新链成功，详见上表，不授仪器物理资格。 |
| BA07–08 | 各格SI/母群/初终态/事件/轨迹与unknown边界已记录；mask/support单位及独立可解释基准通过，未测仪器COMSOL→SIMION独立点值/梯度holdout残差，不声称仪器网格收敛。 |
| BA09–10 | 真实worker生命周期/原owner保护与正常失败收尾，受控父退出/子仍活/取消恢复合同，阶段预算与唯一删除owner；实际reserve触发合格GC。未把登记215153B说成独立测得释放字节。 |
| BA11 | SSA真实repeat/API重放无新增native、K2只增N2、缺443B受控缓存只重算N3trace、GC保留历史SCI；CS同版本重放8448b694e34f486aba0a783744a32d2f ready/succeeded、27/27 stage复用；原生根前后3266项path/size清单完全一致、无新增owner/receipt；无native-control记录的worker计数为null而非伪称实测0。两个run公开读取的数据/分析逐项一致。 |
| BA12 | K1及K2 N3/N2、100Da的+1/+2、权重总和4、完整0hit/分析不适用、母群归并与失败负例通过。 |
| BA13–14 | B链跨组件重释入口拒绝；合法分批/观测及历史reader保留；新链无Candidate/Formal总等级。旧Candidate/compensation的本地初态实验及历史owner、IP/MR等列C；MATLAB guard原生正反例未执行。 |
| BA15 | 声明范围内PASS：ee0聚焦Changed、90d6d5e8定向87项/meta10项及最终双发行离仓验收、最终b6公共CLI、规范CLOC均有实际证据。原08广Changed仍FAIL；原15消费者11 PASS/4 FAIL，修复后按影响定向复验，未重称全catalog绿灯；深路径旧90秒测试仍FAIL并有明确C/P4条件。最终代码与后续docs-only交付身份分开。 |

### B 可复制的已安装命令

下列命令在已有已封存原生资产及授权工具环境重放；路径含该主机环境。重新冷建场/大型研究不是这些命令的隐含前置。完整能力选择/作者冻结/预算由所指作者及environment承担，不以source-revision参数替代真实安装代码身份。

```powershell
$deliveryRoot = 'C:/Users/Liao/msplatform-artifacts/architecture-b-20261127'
$nativeWorkspace = 'C:/Users/Liao/mass_spectrometry/artifacts/batch_b_comsol_split_small_20261127'
$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH = 'C:/Users/Liao/mass_spectrometry/artifacts/platform/host_resources.sqlite3'
# SSA，同质量+1/+2，N3/N2；原作者和场manifest必须仍存在
& "$deliveryRoot/installed-standalone-b1/Scripts/python.exe" -I -m msplatform run "$deliveryRoot/native-reuse-acceptance/authors/oa_split_tof_mass_scan_small_v1.toml" --artifact-root "$deliveryRoot/native-reuse-acceptance/store" --reserve-bytes 1073741824 --execution-environment "$deliveryRoot/simion-installed-standalone-b1/environment.json" --profile small_native --workspace $nativeWorkspace --source-revision e95f6705cfe1544c269bab66504a046f5daae759
# CC，原birth/原OFF/ON；一次真实CPT可能耗时，已有缓存按实际阶段复用
& "$deliveryRoot/installed-standalone-b1/Scripts/python.exe" -I -m msplatform run 'C:/Users/Liao/mass_spectrometry/artifacts/batch_b_comsol_small_cli_20261127/oa_split_tof_comsol_small_reused_v1.toml' --artifact-root "$deliveryRoot/comsol-installed-store" --reserve-bytes 1073741824 --execution-environment "$deliveryRoot/comsol-installed-e95f6705/environment.json" --profile trace_existing_field --workspace $nativeWorkspace --source-revision e95f6705cfe1544c269bab66504a046f5daae759
# CS，08eab366已安装冻结包与相同作者/窗口
& "$deliveryRoot/installed-standalone-b4/Scripts/python.exe" -I -m msplatform run "$deliveryRoot/scalar-installed-study/scalar_recipe.toml" --artifact-root "$deliveryRoot/scalar-installed-store" --reserve-bytes 1073741824 --execution-environment "$deliveryRoot/scalar-installed-study/environment-08eab366.json" --profile scalar_native --workspace $nativeWorkspace --source-revision 08eab3660225ca48382333a4c56068533afd8a22
```

上面是运行/重放命令；有意删除单个缓存和调整GC水位的六阶段验收已执行，不应当作日常命令反复执行。公共API重放脚本 `native-reuse-acceptance/api_repeat.py` 保留完整前后native目录清单与公开读取事实。

### B 临时构建副本清理

确认十二个 `distribution-<sha>/source` 目录均在本任务外部根内、无reparse、无活动进程引用，并保留每份source.tar及SHA、wheel、build/install日志后，使用PowerShell原生Remove-Item仅删除重复解包树。逻辑文件字节合计4,850,159,822 B，未独立测定并发门禁期间物理释放量；可由保留归档/原Git提交重建。证据 `evidence/extracted-build-source-cleanup.json`。不删除原生PA/MPH、科学Store、已安装环境、原研究产物或门禁Temp。此前自动审批拒绝的三个Temp清理目标保持原状，未重试或绕过。

### B 最终增量复验发现的问题（08eab366轮，原轮已结束）

本轮普通双发行离仓父测试已实际PASS（1951.566 s），两臂参考链包含真实DOP853、独立电场解析对照、重读/复用/作者快照，B配方预检/退役拒绝亦PASS；不是新的厂商native。安装后36个选中路径的bytes/SHA、HEAD和status不变。

完整Changed为FAIL，不能以安装通过掩盖：`test_scalar_pa_fill.PaFillTests.test_conflict_never_publishes` 的科学guard正确拒绝不同电位，旧断言文案未迁；`test_scientific_core_boundaries` 发现 simion_field_reference 对recipes的实际逆向依赖。后一项不是测试误报，修复职责上移至现有native_tracing，不放宽boundary白名单。原两个失败分片及其他健康分片均已自然结束，原log/summary保留。原发行身份在 `evidence/final-changed-08eab366-distribution-hashes.json`，不冒充后续新代码安装证据。最终修复、影响范围验证与BA15仍待闭合。

### B 门禁发现的职责修复（08eab366后，本主题提交）

最终08轮实际9 PASS/2 FAIL/15 BLOCKED/27 NOT_APPLICABLE，3337.056s，机器分片01 506、02 474、03 772、04 648合计2400 tests；1项symlink创建权限skip、2 failure。两个失败分别为PA填充负例仍要求旧shape-query错误文本，以及field-reference helper对recipes的实际逆向依赖。原轮不回写PASS。

`native_tracing._validated_simion_field_reference`复用唯一validate_recipe/validate_collision_reference，在源guard前核验冻结引用；`_admit_simion_field_reference`由已验证snapshot解码时钟并调用低层。`simion_field_reference.admit_simion_field_reference`接收Study/reference/clock，保留独立重编全模型及场numerics/design/bank/member/downstream/clock验证，不导入recipes、不新增recipe权威或豁免边界。预检和实际执行统一走同一包装，实际源guard作用域不缩短。测试保留完整原模型/字段/引用篡改与保护负例，新增snapshot篡改在guard前拒绝；PA测试精确匹配不同电位冲突的新错误，未改生产guard。

根实际执行 `python -m unittest tests.contracts.test_scientific_core_boundaries tests.contracts.test_simion_field_reference tests.contracts.test_scalar_pa_fill tests.contracts.test_native_workflow tests.contracts.test_native_asset_recipe -q`：42 tests，22.074s PASS；四文件Ruff与git diff --check PASS。log为外部 `evidence/boundary-fix-targeted.log`。本单元尚未取得新SHA普通双发行/已安装native资格；原08及e95原生结果保持各自代码身份，不自动提升为本提交证据。

验证选择：没有合法public Resume/failed-only门禁；PlanPath是同checkout冻结选择，不能修改后消费旧计划。后续采用公共窄Changed验证真实变动测试、原15 blocked消费者的原catalog命令逐项补检，以及最终代码完整普通双发行父方法；所有结果按项记录，不拼出一次原完整Changed PASS。不重复未受影响的2400项或冷求场。最终必要检查失败则继续按实际原因处理。


### B 最终受影响已安装原生复验（ee0bb140）

最终代码为 `ee0bb140d425ec9fa727a149808ed2bc60cc40ca`。普通隔离构建wheel SHA256 `A38BC2D33E53035BC13DA6F323A66C4BB3B026D26B3D3D60141E2AE6E2D28E57`，安装到独立b5，不升级b1/b4。最终安装测试wheel与b5 wheel的1345个msplatform/成员逐字节完全一致（归档metadata不混比），证据`evidence/ee0-native-and-installed-wheel-payload-comparison.json`。

保持原作者、原Study、源birth、原031207 sealed fields和原环境策略，仅将Python/policy_path指向b5。首次Store `8fa83f03944b4516ac5c3fb13f41cfc6`和同版本重复 `5d76749d7f4048b4876fa14e1be937c7`均succeeded/ready。新增成功ground `20261127_085349__sim__simion__ground-61a274793a36`的6项操作和track `20261127_085504__sim__simion__track-f06eab9768c4`的3项操作均exit0，包含一次Fly；无新Refine/COMSOL Compute，不将9个worker误称9次Fly。所有9条native binding complete，两个原owner lease文件已消失，Store claims/reservations=0。

重复运行stage_productions=[]、无新增native-control证据，worker_count为null/unavailable（不是实测计数0）；3374项原生路径/size及小receipt/manifest SHA前后完全不变。公共read_particle_data/summarize/analyze的初态/终态/事件/轨迹/分析逐项一致。3母群完整，complete 0 hit、unknown归属3、轨迹仅各birth样本，不授仪器精度或动态ON资格。完整记录`final-simion-ee0bb140/acceptance.json`及before/after-first/after-repeat、first/repeat日志。

本次职责移动仅在显式SIMION引用分支；COMSOL原生/采样分支与原物理、vendor接口未改，42项边界/场引用/原生workflow定向复验通过。CC/CS真实新链资格仍绑定各自e95/08代码，不自动贴ee0新标签；不重复未受影响的昂贵原场/CPT/冷采样。

可复制的最终SSA命令（工作目录任意；所有外部原资产须保留）：

```powershell
$deliveryRoot = 'C:/Users/Liao/msplatform-artifacts/architecture-b-20261127'
$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH = 'C:/Users/Liao/mass_spectrometry/artifacts/platform/host_resources.sqlite3'
& "$deliveryRoot/installed-standalone-b5/Scripts/python.exe" -I -m msplatform run "$deliveryRoot/explicit-simion-source-study/oa_split_tof_native_small_v1.toml" --artifact-root "$deliveryRoot/final-simion-ee0bb140/store" --reserve-bytes 1073741824 --execution-environment "$deliveryRoot/final-simion-ee0bb140/environment.json" --profile small_native --workspace 'C:/Users/Liao/mass_spectrometry/artifacts/batch_b_comsol_split_small_20261127' --source-revision ee0bb140d425ec9fa727a149808ed2bc60cc40ca
```

同质量+1/+2的真实N3/N2 mass_scan与局部重算/GC仍见此前e95专项命令及证据，不把最终单物种重复冒充重新做了整个六阶段试验。


### B 最终普通发行与聚焦门禁（ee0bb140）

公共命令 `tools/repository/verify.ps1 -Scope Changed -PythonExe ./.venv/Scripts/python.exe -ChangedPath tests/contracts/test_installed_scientific_core.py,tests/contracts/test_simion_field_reference.py,tests/contracts/test_scalar_pa_fill.py -SummaryPath <external>`（PowerShell调用时ChangedPath传真实数组）实际PASS：7 PASS、37 NOT_APPLICABLE，1820.198s。三个unittest分片分别11/6/11项，共28 tests、0 skips。完整普通双发行父方法1794.208s PASS；wheel与sdist重建wheel各自离仓执行真实DOP853/独立解析/重读/复用/作者快照及B公开配方预检/退役拒绝，B probe明确native_run=0，与上述b5实际native证据分开。

日志/summary及input/post记录在外部 `evidence/final-focused-ee0bb140*`。结束时HEAD、三个选中路径bytes/SHA一致，staged/unstaged实际diff为空；不是利用空Changed选择取得PASS。该scope仅声明实际列明检查，未重跑08轮2400项，也不把旧广Changed FAIL改成PASS。原15 blocked消费者的完整原命令另行逐项补检，最终结果见后续对账。

最终发行SHA256：普通wheel `605D9A444600DC307FC6483A724F401AE566869B885F274364D81160473830FF`；sdist `290A6A9FEFFE07AEF5B048070D5B29D85AC0FD0DA5B27690EA4230A510B231D7`；sdist重建wheel `697773C8AE5636EFD57D93349149FB0FB48CF4B438D60570A793EF9517EF9F3E`。完整文件大小与路径在 `evidence/final-focused-ee0bb140-distribution-hashes.json`；测试自身按既有临时生命周期清理发行Temp，native b5独立普通wheel保留。

### B 原 blocked 消费者补检（ee0bb140 原始结果）

由最终checkout的未修改官方PlanOnly逐项对照原command/modules/requires/resource后执行，15项前后40输入SHA均一致。以下是原始结果，不因后续修复回写PASS。tests_run按completed invocation统计，包含阶段间重复，不将subtest outcome数冒充测试数。

| stage | 原结果 | tests_run | skips |
|---|---|---:|---:|
| simion_backend | PASS | 371 | 7 |
| rf_multipole_domain_tests | PASS | 524 | 2 |
| instrument_assembly__tests_01 | PASS | 123 | 0 |
| instrument_assembly__tests_02 | PASS | 156 | 0 |
| instrument_assembly__tests_03 | PASS | 238 | 0 |
| instrument_assembly__tests_04 | FAIL | 217 | 0 |
| parallel_mirror_dual_stripe_mr_tof_static | PASS | 142 | 1 |
| single_reflection_oa_tof_mass_analyzer_static | PASS | N/A（静态前置） | 0 |
| single_reflection_oa_tof_mass_analyzer_static__tests_01 | FAIL | 84 | 0 |
| single_reflection_oa_tof_mass_analyzer_static__tests_02 | FAIL | 232 | 2 |
| single_reflection_oa_tof_mass_analyzer_static__tests_03 | PASS | 159 | 0 |
| single_reflection_oa_tof_mass_analyzer_static__tests_04 | FAIL | 304 | 0 |
| rf_multipole_quadrupole_static | PASS | 338 | 0 |
| rf_multipole_hexapole_static | PASS | 18 | 0 |
| rf_multipole_octupole_static | PASS | 18 | 0 |

完整命令、原日志、逐个skip名称和原因见 `evidence/focused-ee0-blocked-detailed-report.json`。其中portable Lua单例后来以局部PATH实际PASS（1 test，0.408s，`evidence/portable-lua-recheck-ee0bb140.log`）；原RF suite skip不删除。需显式native授权/lease、retained native-97、历史source snapshot与OATOF_THREE_ZONE_T5_RECEIPT的其他跳过保持未验证。

深路径ReanalyzeOnly旧测试原90秒FAIL继续保留；其observer早于B即已失配，超时后真实Python分析自然完成3 species/0native，source通过11exports认证且两次resume前后字节不变，错误context拒绝、正确context恢复PASS，host/capacity均释放。具体cwd/alias断言未由旧observer证明，留C/P4；未比较B前耗时，不推断无性能回归。证据 `evidence/deep-reanalysis-diagnostic/evidence.md` / `.json`，独立范围审计 `evidence/b-exit-scope-independent-audit.md`。不得将该历史case或整catalog称PASS。

### B6 消费者补检后的最小收尾（ee0bb140后，本主题提交）

唯一生产变化是 `workflows/single_reflection_flight/continuation.py::render_legacy_iob_builder` 两条当前locator完整字面值。继续要求调用总数5、各项唯一、已知header/CLI包络和整段字节比对；未知/旧表达式及额外locator拒绝。B canonical IOB已加入preserve_canonical_instances，原变换器未同步，确属保留whole-batch历史兼容路径的软件回归。没有恢复旧composite新执行或改动物理/求解器/源/clock。

测试同步分别是：旧recorded-birth composite正例改实际ContractError+owner0，保留模型/几何/clock/源篡改；当前plan6 RF的粒子、clock、model与producer绑定另由现有v12/tracking实际公开调用测试覆盖。旧mass run/resume不可再用来生成新母资产，七个旧producer成功/故障断言替为两个具名API/真实PS入口拒绝测试，owner/native0；历史reanalysis/来源篡改/终结恢复独立fixture和方法保留。新mass_scan的N3/N2、多电荷、局部重算、失败和重读由新链独立证据验证，不称旧producer仍通过。

reflectron compensation本轮未迁入split生产：测试改用现有旧author→resolved→Assembly→private纯compiler的历史inert oracle，完整旧合同/源/clock保留，不拼接/重命名split字段、不伪称真实native；五项原正负basis断言均保留。ideal source package fixture补真实single_reflection_tof依赖，原mutate/missing-executor反例保留；权限测试分别验证退休mass/Formal Validate不创建owner/lease，其他合法入口的permission/release保持。原项目Formal Verify/Publish/Recover和resume_finalization不被退休。

既有安装probe新增从purelib内实际读取iob_core并执行严格continuation lowering/未知locator拒绝，marker为`INSTALLED_B_CONTINUATION=PASS current_locator=1 unknown_rejected=1`。同一marker加入reference_only和完整两臂父断言；此时仍待本提交实际安装，不能把开发树或外部候选PASS冒充installed。

根主工作树实际87 tests、285.105s、0 skips PASS（whole continuation/recorded-birth consumer、边界、RF绑定、退休API/PS、compensation及两个package/permission病例）；Ruff、git diff --check、repository_text_bytes PASS。原命令选择逐行保留在外部`evidence/final-consumer-fixes-tests.txt`，log为`evidence/final-consumer-fixes-targeted.log`。不重复已完成的2400项、20分钟Candidate全模块或无关完整32分钟RF/IP安装；最终实际ordinary两发行参考/B/新reader验收仍将执行。

```powershell
# 在simulation_repo根运行；这是定向软件回归，不启动商业求解器
$env:SIMION_LUA_EXE = 'C:/Program Files/SIMION-2020/lua.exe'
$env:MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH = 'C:/Users/Liao/mass_spectrometry/artifacts/platform/host_resources.sqlite3'
$tests = Get-Content 'C:/Users/Liao/msplatform-artifacts/architecture-b-20261127/evidence/final-consumer-fixes-tests.txt'
& ./.venv/Scripts/python.exe -m unittest @tests -q
```

历史deep case的原始失败与后续实际功能证据分轴记录，依据独立范围审计留C/P4：若需声明该深路径cwd/stream alias合同或要求相关旧Owner全绿，必须先重建有效observer，再按明确预算核验；不能从本次晚于90s的成功推断此前性能或每时刻保护。本轮BA09依靠独立生命周期合同和真实native保护证据，不用此单一诊断冒充。

清理：此前12个解包source逻辑字节4,850,159,822 B；本次普通移除两个已提交/备份的临时worktree（225,725,941 B及223,228,025 B）和distribution-ee0/source（404,358,497 B）。只统计删除内容的逻辑文件字节，未独立测得并发期间物理释放。完整raw备份/补丁在`evidence/worktree-backups/`，清理审计`evidence/final-worktree-cleanup.json`。所有对应Git提交/source.tar/wheel/log仍可重建；不动研究PA/MPH和真实Store，三个原自动审批拒绝Temp保持不动。


### B 累计 CLOC（08eab366代码快照）

规范工具实际PASS；原日志 `C:/Users/Liao/msplatform-artifacts/architecture-b-20261127/code-08eab366-cloc.log`。每格为 基线 → 结果（delta）；只统计指定提交，不把未跟踪产物或WIP算入。

#### total

| Language | Files | Blank | Comment | Code |
|---|---:|---:|---:|---:|
| JSON | 282 → 291 (+9) | 0 → 0 (+0) | 0 → 0 (+0) | 126022 → 130154 (+4132) |
| Lua | 119 → 120 (+1) | 413 → 416 (+3) | 828 → 830 (+2) | 13219 → 13273 (+54) |
| MATLAB | 186 → 188 (+2) | 1066 → 1068 (+2) | 2053 → 2067 (+14) | 19701 → 20023 (+322) |
| PowerShell | 150 → 150 (+0) | 1100 → 1101 (+1) | 1195 → 1195 (+0) | 46113 → 46242 (+129) |
| Python | 1435 → 1499 (+64) | 32921 → 33761 (+840) | 42493 → 43073 (+580) | 396258 → 407993 (+11735) |
| SIMION GEM | 10 → 10 (+0) | 26 → 26 (+0) | 51 → 51 (+0) | 214 → 214 (+0) |
| TOML | 5 → 9 (+4) | 43 → 46 (+3) | 2 → 2 (+0) | 219 → 283 (+64) |
| YAML | 2 → 2 (+0) | 8 → 8 (+0) | 20 → 20 (+0) | 506 → 506 (+0) |
| SUM | 2189 → 2269 (+80) | 35577 → 36426 (+849) | 46642 → 47238 (+596) | 602252 → 618688 (+16436) |
#### production

| Language | Files | Blank | Comment | Code |
|---|---:|---:|---:|---:|
| JSON | 259 → 267 (+8) | 0 → 0 (+0) | 0 → 0 (+0) | 42340 → 45539 (+3199) |
| Lua | 99 → 100 (+1) | 333 → 336 (+3) | 703 → 705 (+2) | 11141 → 11195 (+54) |
| MATLAB | 118 → 120 (+2) | 526 → 528 (+2) | 1462 → 1476 (+14) | 12164 → 12486 (+322) |
| PowerShell | 138 → 138 (+0) | 1037 → 1038 (+1) | 1149 → 1149 (+0) | 44012 → 44131 (+119) |
| Python | 685 → 714 (+29) | 16804 → 17255 (+451) | 11609 → 11933 (+324) | 182981 → 189466 (+6485) |
| SIMION GEM | 10 → 10 (+0) | 26 → 26 (+0) | 51 → 51 (+0) | 214 → 214 (+0) |
| TOML | 5 → 9 (+4) | 43 → 46 (+3) | 2 → 2 (+0) | 219 → 283 (+64) |
| YAML | 2 → 2 (+0) | 8 → 8 (+0) | 20 → 20 (+0) | 506 → 506 (+0) |
| SUM | 1316 → 1360 (+44) | 18777 → 19237 (+460) | 14996 → 15336 (+340) | 293577 → 303820 (+10243) |
#### tests

| Language | Files | Blank | Comment | Code |
|---|---:|---:|---:|---:|
| JSON | 23 → 24 (+1) | 0 → 0 (+0) | 0 → 0 (+0) | 83682 → 84615 (+933) |
| Lua | 20 → 20 (+0) | 80 → 80 (+0) | 125 → 125 (+0) | 2078 → 2078 (+0) |
| MATLAB | 68 → 68 (+0) | 540 → 540 (+0) | 591 → 591 (+0) | 7537 → 7537 (+0) |
| PowerShell | 12 → 12 (+0) | 63 → 63 (+0) | 46 → 46 (+0) | 2101 → 2111 (+10) |
| Python | 750 → 785 (+35) | 16117 → 16506 (+389) | 30884 → 31140 (+256) | 213277 → 218527 (+5250) |
| SUM | 873 → 909 (+36) | 16800 → 17189 (+389) | 31646 → 31902 (+256) | 308675 → 314868 (+6193) |
#### unclassified

| Language | Files | Blank | Comment | Code |
|---|---:|---:|---:|---:|
| SUM | 0 → 0 (+0) | 0 → 0 (+0) | 0 → 0 (+0) | 0 → 0 (+0) |

#### 输入身份与完整过滤口径

```text
BASELINE=a9d76aa4dcdbaf8099c9ce5aa0585d6fce18c3be
RESULT=08eab3660225ca48382333a4c56068533afd8a22
CLOC_VERSION=2.10
CREATED_UTC=2026-11-26T23:31:17.5907223+00:00
CLASSIFIER_SHA256=d3abfc94e920066445561b696c76131b43eab9713a0cbcb9e2c1270ba7136952
LANGUAGE_DEFINITION_SHA256=985e60f06bd8981c36966a0895cccfccd182fd625c79eb6ae94b65a12c5508a6
INPUT_IDENTITY SNAPSHOT=baseline FILES=2234 SHA256=2e9c89b9e7a4ddd9d2d2e95a292cfbe15ca5b439965fa762bd82c4277fa07818
INPUT_IDENTITY SNAPSHOT=result FILES=2314 SHA256=c362a78247cf671b52190e0b2ac8f5dcc3c4d40617dcd1bf4f744742832948f9
FILTER=extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|tests_boundary/*_fixtures.py|tests/**/__init__.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked
CLASSIFICATION_DETAIL SNAPSHOT=baseline CATEGORY=production REASON=active_powershell_entrypoint FILES=53
CLASSIFICATION_DETAIL SNAPSHOT=baseline CATEGORY=production REASON=execution_profile_entrypoint FILES=17
CLASSIFICATION_DETAIL SNAPSHOT=baseline CATEGORY=production REASON=non_test_source FILES=1246
CLASSIFICATION_DETAIL SNAPSHOT=baseline CATEGORY=tests REASON=test_filename FILES=842
CLASSIFICATION_DETAIL SNAPSHOT=baseline CATEGORY=tests REASON=test_support_path FILES=76
CLASSIFICATION_DETAIL SNAPSHOT=result CATEGORY=production REASON=active_powershell_entrypoint FILES=53
CLASSIFICATION_DETAIL SNAPSHOT=result CATEGORY=production REASON=execution_profile_entrypoint FILES=17
CLASSIFICATION_DETAIL SNAPSHOT=result CATEGORY=production REASON=non_test_source FILES=1290
CLASSIFICATION_DETAIL SNAPSHOT=result CATEGORY=tests REASON=test_filename FILES=876
CLASSIFICATION_DETAIL SNAPSHOT=result CATEGORY=tests REASON=test_support_path FILES=78
```

功能分类完整输出保留在原日志。

### B 累计 CLOC（至 f216a7af，不含后续改动）

基线 `a9d76aa4dcdbaf8099c9ce5aa0585d6fce18c3be` → 结果 `f216a7afd0a3b27be21402915209defa9964d78e`；CLOC 2.10；源日志 `C:/Users/Liao/msplatform-artifacts/architecture-b-20261127/f216a7af-cloc.log`。

生成时间：`2026-11-26T19:00:42.8870293+00:00`；分类器 SHA-256 `d3abfc94e920066445561b696c76131b43eab9713a0cbcb9e2c1270ba7136952`；语言定义 SHA-256 `985e60f06bd8981c36966a0895cccfccd182fd625c79eb6ae94b65a12c5508a6`。

以下每格为 基线 → 结果（变化），直接转录日志。

#### Total

| Language | Files | Blank | Comment | Code |
|---|---:|---:|---:|---:|
| JSON | 282 → 290 (+8) | 0 → 0 (+0) | 0 → 0 (+0) | 126022 → 129542 (+3520) |
| Lua | 119 → 120 (+1) | 413 → 416 (+3) | 828 → 830 (+2) | 13219 → 13257 (+38) |
| MATLAB | 186 → 188 (+2) | 1066 → 1066 (+0) | 2053 → 2065 (+12) | 19701 → 19951 (+250) |
| PowerShell | 150 → 150 (+0) | 1100 → 1100 (+0) | 1195 → 1195 (+0) | 46113 → 46229 (+116) |
| Python | 1435 → 1487 (+52) | 32921 → 33596 (+675) | 42493 → 42932 (+439) | 396258 → 405297 (+9039) |
| SIMION GEM | 10 → 10 (+0) | 26 → 26 (+0) | 51 → 51 (+0) | 214 → 214 (+0) |
| TOML | 5 → 8 (+3) | 43 → 45 (+2) | 2 → 2 (+0) | 219 → 267 (+48) |
| YAML | 2 → 2 (+0) | 8 → 8 (+0) | 20 → 20 (+0) | 506 → 506 (+0) |
| SUM | 2189 → 2255 (+66) | 35577 → 36257 (+680) | 46642 → 47095 (+453) | 602252 → 615263 (+13011) |

#### Production

| Language | Files | Blank | Comment | Code |
|---|---:|---:|---:|---:|
| JSON | 259 → 266 (+7) | 0 → 0 (+0) | 0 → 0 (+0) | 42340 → 44927 (+2587) |
| Lua | 99 → 100 (+1) | 333 → 336 (+3) | 703 → 705 (+2) | 11141 → 11179 (+38) |
| MATLAB | 118 → 120 (+2) | 526 → 526 (+0) | 1462 → 1474 (+12) | 12164 → 12414 (+250) |
| PowerShell | 138 → 138 (+0) | 1037 → 1037 (+0) | 1149 → 1149 (+0) | 44012 → 44128 (+116) |
| Python | 685 → 711 (+26) | 16804 → 17189 (+385) | 11609 → 11881 (+272) | 182981 → 188154 (+5173) |
| SIMION GEM | 10 → 10 (+0) | 26 → 26 (+0) | 51 → 51 (+0) | 214 → 214 (+0) |
| TOML | 5 → 8 (+3) | 43 → 45 (+2) | 2 → 2 (+0) | 219 → 267 (+48) |
| YAML | 2 → 2 (+0) | 8 → 8 (+0) | 20 → 20 (+0) | 506 → 506 (+0) |
| SUM | 1316 → 1355 (+39) | 18777 → 19167 (+390) | 14996 → 15282 (+286) | 293577 → 301789 (+8212) |

#### Tests

| Language | Files | Blank | Comment | Code |
|---|---:|---:|---:|---:|
| JSON | 23 → 24 (+1) | 0 → 0 (+0) | 0 → 0 (+0) | 83682 → 84615 (+933) |
| Lua | 20 → 20 (+0) | 80 → 80 (+0) | 125 → 125 (+0) | 2078 → 2078 (+0) |
| MATLAB | 68 → 68 (+0) | 540 → 540 (+0) | 591 → 591 (+0) | 7537 → 7537 (+0) |
| PowerShell | 12 → 12 (+0) | 63 → 63 (+0) | 46 → 46 (+0) | 2101 → 2101 (+0) |
| Python | 750 → 776 (+26) | 16117 → 16407 (+290) | 30884 → 31051 (+167) | 213277 → 217143 (+3866) |
| SUM | 873 → 900 (+27) | 16800 → 17090 (+290) | 31646 → 31813 (+167) | 308675 → 313474 (+4799) |

#### Unclassified

| Language | Files | Blank | Comment | Code |
|---|---:|---:|---:|---:|
| SUM | 0 → 0 (+0) | 0 → 0 (+0) | 0 → 0 (+0) | 0 → 0 (+0) |

#### 输入快照与分类统计

```text
WORKTREE_DIRTY=true
WORKTREE_TRACKED_DIRTY_COUNT=10
WORKTREE_UNTRACKED_COUNT=15
INPUT_IDENTITY SNAPSHOT=baseline FILES=2234 SHA256=2e9c89b9e7a4ddd9d2d2e95a292cfbe15ca5b439965fa762bd82c4277fa07818
INPUT_IDENTITY SNAPSHOT=result FILES=2300 SHA256=85dff72c8bee7d4bb94fee1bbcc63a8e92c582a1092dff0f2f8119e9698c63be
CLASSIFICATION_DETAIL SNAPSHOT=baseline CATEGORY=production REASON=active_powershell_entrypoint FILES=53
CLASSIFICATION_DETAIL SNAPSHOT=baseline CATEGORY=production REASON=execution_profile_entrypoint FILES=17
CLASSIFICATION_DETAIL SNAPSHOT=baseline CATEGORY=production REASON=non_test_source FILES=1246
CLASSIFICATION_DETAIL SNAPSHOT=baseline CATEGORY=tests REASON=test_filename FILES=842
CLASSIFICATION_DETAIL SNAPSHOT=baseline CATEGORY=tests REASON=test_support_path FILES=76
CLASSIFICATION_DETAIL SNAPSHOT=result CATEGORY=production REASON=active_powershell_entrypoint FILES=53
CLASSIFICATION_DETAIL SNAPSHOT=result CATEGORY=production REASON=execution_profile_entrypoint FILES=17
CLASSIFICATION_DETAIL SNAPSHOT=result CATEGORY=production REASON=non_test_source FILES=1285
CLASSIFICATION_DETAIL SNAPSHOT=result CATEGORY=tests REASON=test_filename FILES=868
CLASSIFICATION_DETAIL SNAPSHOT=result CATEGORY=tests REASON=test_support_path FILES=77
```

#### 过滤及分类口径

```text
extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|tests_boundary/*_fixtures.py|tests/**/__init__.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked
```

源日志同时记录功能分类；本摘要仅转录指定两个提交快照，未重新运行 CLOC，WORKTREE 状态仅为日志运行时环境信息。

### B 累计 CLOC（至 c4398e9c，后续未提交改动不计）

基线 `a9d76aa4dcdbaf8099c9ce5aa0585d6fce18c3be` → 结果 `c4398e9c4aeb2b4449cbb99a3338606ae743e6aa`；CLOC 2.10；原日志 `C:/Users/Liao/msplatform-artifacts/architecture-b-20261127/c4398e9c-cloc.log`。
生成时间 `2026-11-26T20:40:03.0906419+00:00`；classifier SHA256 `d3abfc94e920066445561b696c76131b43eab9713a0cbcb9e2c1270ba7136952`；语言定义 SHA256 `985e60f06bd8981c36966a0895cccfccd182fd625c79eb6ae94b65a12c5508a6`。
以下每格为 基线 → 结果（delta），直接由规范工具输出转录；不以工作区增量冒充提交快照。

#### total

| Language | Files | Blank | Comment | Code |
|---|---:|---:|---:|---:|
| JSON | 282 → 291 (+9) | 0 → 0 (+0) | 0 → 0 (+0) | 126022 → 130154 (+4132) |
| Lua | 119 → 120 (+1) | 413 → 416 (+3) | 828 → 830 (+2) | 13219 → 13257 (+38) |
| MATLAB | 186 → 188 (+2) | 1066 → 1068 (+2) | 2053 → 2067 (+14) | 19701 → 20023 (+322) |
| PowerShell | 150 → 150 (+0) | 1100 → 1101 (+1) | 1195 → 1195 (+0) | 46113 → 46232 (+119) |
| Python | 1435 → 1494 (+59) | 32921 → 33677 (+756) | 42493 → 43025 (+532) | 396258 → 406641 (+10383) |
| SIMION GEM | 10 → 10 (+0) | 26 → 26 (+0) | 51 → 51 (+0) | 214 → 214 (+0) |
| TOML | 5 → 9 (+4) | 43 → 46 (+3) | 2 → 2 (+0) | 219 → 283 (+64) |
| YAML | 2 → 2 (+0) | 8 → 8 (+0) | 20 → 20 (+0) | 506 → 506 (+0) |
| SUM | 2189 → 2264 (+75) | 35577 → 36342 (+765) | 46642 → 47190 (+548) | 602252 → 617310 (+15058) |

#### production

| Language | Files | Blank | Comment | Code |
|---|---:|---:|---:|---:|
| JSON | 259 → 267 (+8) | 0 → 0 (+0) | 0 → 0 (+0) | 42340 → 45539 (+3199) |
| Lua | 99 → 100 (+1) | 333 → 336 (+3) | 703 → 705 (+2) | 11141 → 11179 (+38) |
| MATLAB | 118 → 120 (+2) | 526 → 528 (+2) | 1462 → 1476 (+14) | 12164 → 12486 (+322) |
| PowerShell | 138 → 138 (+0) | 1037 → 1038 (+1) | 1149 → 1149 (+0) | 44012 → 44131 (+119) |
| Python | 685 → 713 (+28) | 16804 → 17218 (+414) | 11609 → 11904 (+295) | 182981 → 188785 (+5804) |
| SIMION GEM | 10 → 10 (+0) | 26 → 26 (+0) | 51 → 51 (+0) | 214 → 214 (+0) |
| TOML | 5 → 9 (+4) | 43 → 46 (+3) | 2 → 2 (+0) | 219 → 283 (+64) |
| YAML | 2 → 2 (+0) | 8 → 8 (+0) | 20 → 20 (+0) | 506 → 506 (+0) |
| SUM | 1316 → 1359 (+43) | 18777 → 19200 (+423) | 14996 → 15307 (+311) | 293577 → 303123 (+9546) |

#### tests

| Language | Files | Blank | Comment | Code |
|---|---:|---:|---:|---:|
| JSON | 23 → 24 (+1) | 0 → 0 (+0) | 0 → 0 (+0) | 83682 → 84615 (+933) |
| Lua | 20 → 20 (+0) | 80 → 80 (+0) | 125 → 125 (+0) | 2078 → 2078 (+0) |
| MATLAB | 68 → 68 (+0) | 540 → 540 (+0) | 591 → 591 (+0) | 7537 → 7537 (+0) |
| PowerShell | 12 → 12 (+0) | 63 → 63 (+0) | 46 → 46 (+0) | 2101 → 2101 (+0) |
| Python | 750 → 781 (+31) | 16117 → 16459 (+342) | 30884 → 31121 (+237) | 213277 → 217856 (+4579) |
| SUM | 873 → 905 (+32) | 16800 → 17142 (+342) | 31646 → 31883 (+237) | 308675 → 314187 (+5512) |

#### unclassified

| Language | Files | Blank | Comment | Code |
|---|---:|---:|---:|---:|
| SUM | 0 → 0 (+0) | 0 → 0 (+0) | 0 → 0 (+0) | 0 → 0 (+0) |

#### 输入快照、分类与过滤

```text
WORKTREE_DIRTY=true
WORKTREE_TRACKED_DIRTY_COUNT=39
WORKTREE_UNTRACKED_COUNT=19
INPUT_IDENTITY SNAPSHOT=baseline FILES=2234 SHA256=2e9c89b9e7a4ddd9d2d2e95a292cfbe15ca5b439965fa762bd82c4277fa07818
INPUT_IDENTITY SNAPSHOT=result FILES=2309 SHA256=856d824220941b383f47236321c85877e28bf65d46503503ef69b1443621db3b
FILTER=extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|tests_boundary/*_fixtures.py|tests/**/__init__.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked
CLASSIFICATION_DETAIL SNAPSHOT=baseline CATEGORY=production REASON=active_powershell_entrypoint FILES=53
CLASSIFICATION_DETAIL SNAPSHOT=baseline CATEGORY=production REASON=execution_profile_entrypoint FILES=17
CLASSIFICATION_DETAIL SNAPSHOT=baseline CATEGORY=production REASON=non_test_source FILES=1246
CLASSIFICATION_DETAIL SNAPSHOT=baseline CATEGORY=tests REASON=test_filename FILES=842
CLASSIFICATION_DETAIL SNAPSHOT=baseline CATEGORY=tests REASON=test_support_path FILES=76
CLASSIFICATION_DETAIL SNAPSHOT=result CATEGORY=production REASON=active_powershell_entrypoint FILES=53
CLASSIFICATION_DETAIL SNAPSHOT=result CATEGORY=production REASON=execution_profile_entrypoint FILES=17
CLASSIFICATION_DETAIL SNAPSHOT=result CATEGORY=production REASON=non_test_source FILES=1289
CLASSIFICATION_DETAIL SNAPSHOT=result CATEGORY=tests REASON=test_filename FILES=873
CLASSIFICATION_DETAIL SNAPSHOT=result CATEGORY=tests REASON=test_support_path FILES=77
```
规范工具分别统计total/production/tests，unclassified=0；完整功能分类保留在原日志。

### B 最终交付记录（2026-11-27）

Agent 0完成整合/Git/交付；Agent 1完成独立物理与退出范围审查；Agent 2完成软件/两发行安装；Agent 3完成实际native与复用验收；Agent 4完成旧消费者补检/历史失败诊断；Agent 5完成fixture审查。各流已结束，本轮止于B。B0四缺口、B1公共配置、B2拆分消费、B3/B4原生矩阵、B5通用mass_scan、B6退役/安装的实际结果见上文；BA01–BA15以对账表的声明范围和限制为准。原评阅状态与本轮技术选择保持分离。

最终生产/测试代码`90d6d5e8b67e5b0bfe3e823b0130c30c266eea2b`已普通push至`origin/task/architecture-migration-20261126`；此后交付提交仅改本页，其确切身份由包含本节的Git提交确定。未合并或推送master、未改写历史。原状态缓存M无实际diff、原未跟踪artifacts保持。下列证据根统一为`C:/Users/Liao/msplatform-artifacts/architecture-b-20261127`。

#### 最终安装与实际公共运行

最终代码调用既有`tests.contracts.test_installed_scientific_core.InstalledScientificCoreTests.verify_reference_delivery`，1 test PASS，360.732s；不是重跑完整RF/IP安装probe。直接wheel和sdist重建wheel两臂均使用普通安装、离仓工作目录、`-I`，证实purelib来源/源树不可访问；真实DOP853参考链、完整读回/复用/作者快照、B拆分预检/旧执行拒绝、mass_scan 3+2母群与+1/+2及严格continuation正反例全部通过。B部分`native_run=0`，不冒称新的商业求解。两臂参考事件时间9.185857056658535e-7 s，独立解析时间误差1.1540919197546408e-16 s、最大位置误差8.673617379884035e-18 m。前后3273 tracked文件SHA、HEAD和工作区状态相同；日志与源树前后证据在`evidence/final-reference-90d6d5e8*`，保留发行在`final-reference-90d6d5e8/`。

| 发行 | SHA256 |
|---|---|
| distribution/mass_spectrometry_analysis-0.4.0-py3-none-any.whl | 92376530440EDD7872824F03F54EFC3C8B75CF9CDBFF6D031932FEDF1F881588 |
| distribution/mass-spectrometry-analysis-0.4.0.tar.gz | 172C30B2E7C9F18A54F3141F9B1E711F1B92CAF331007E4CBD4F50EF65EC9DB4 |
| rebuilt/mass_spectrometry_analysis-0.4.0-py3-none-any.whl | 58FF85C188B39ABC5076BA8DE630291C1BBAFE38220CE2CD77F8C68902471A7A |

最终wheel与ee0真实native b5 wheel的1345个msplatform成员逐字节比较：无新增/删除，唯一差异是历史strict continuation定位器，其余1344相同；证据`evidence/final-reference-90d6d5e8-native-payload-comparison.json`。这不是自动补做所有组合的冷求解资格。

b6隔离环境普通安装最终wheel并实际执行以下公共CLI，成功得到run `6394fada38644e33b63a84a940f652ae`、ready/succeeded。公开read_particle_data/summarize/analyze的初态/终态/事件/轨迹/summary/analysis与b5一致；stage_productions=[]，原生3374项path/size及小receipt/manifest哈希清单无增删改，claims/reservations=0。无新增native-control记录时worker_count为null，不能写成观测到0个worker。此命令是合格缓存复用；不是新的冷Fly/Refine/Compute。

```powershell
$taskRoot = 'C:/Users/Liao/msplatform-artifacts/architecture-b-20261127'
$pythonB = "$taskRoot/installed-standalone-b6/Scripts/python.exe"
& $pythonB -I -m msplatform run "$taskRoot/explicit-simion-source-study/oa_split_tof_native_small_v1.toml" --artifact-root "$taskRoot/final-simion-ee0bb140/store" --reserve-bytes 1073741824 --execution-environment "$taskRoot/final-simion-ee0bb140/environment-b6.json" --profile small_native --workspace 'C:/Users/Liao/mass_spectrometry/artifacts/batch_b_comsol_split_small_20261127' --source-revision 90d6d5e8b67e5b0bfe3e823b0130c30c266eea2b
& $pythonB -I -m msplatform results inspect 6394fada38644e33b63a84a940f652ae --artifact-root "$taskRoot/final-simion-ee0bb140/store"
```

实际命令/安装/公共API对账见`final-simion-ee0bb140/b6-run.log`、`b6-install.log`、`b6-evidence.json`及b6-before/after.json。CC/CS原命令、环境、输入和冻结来源保留于上文及逐格证据；不把不同源码身份混称同一次运行。

| field_source → tracer | 实际installed native证据 | 物理/数据边界 |
|---|---|---|
| SIMION → SIMION | ee0 b5：8fa83f03944b4516ac5c3fb13f41cfc6，真实新ground/track、1 Fly；同版重复5d76749d7f4048b4876fa14e1be937c7；最终90代码b6复用见上 | N3初终态齐全，0 hit、unknown3，轨迹只有birth样本 |
| COMSOL → COMSOL | e95 b1：28234aa32d4e45bdb3da93a4883a0167，实际CPT；cc-installed-acceptance.json | N3初终态齐全，12轨迹点，Freeze后行不解释为继续运动；0 hit、unknown3 |
| COMSOL → SIMION | 08 b4：b3bac2eedb3340318a6d8531f8e5e8f5，真实1 Fly；同版重复8448b694e34f486aba0a783744a32d2f | N3初终态齐全，3 birth样本，0 hit、unknown3；OFF/ON场域mask保留 |

三格仪器粒子均在原80.051373 us脉冲前停止，未验证仪器ON效果/命中性能/网格收敛/跨后端等价或Formal。ON机制另有真实synthetic N1 Fly与独立分段解析解（最大dx=1.6791164e-8 mm、dv=3.130741e-6 m/s，事先容差内），及SDK线性场与COMSOL零力独立基准。仪器COMSOL→SIMION点值/梯度holdout残差未测。不能把unknown填成丢失、命中或物理通过；完整0-hit的分析明确不适用。

#### 必要验证与保留失败

| 对象/实际代码 | 实际结果 | 解释 |
|---|---|---|
| 08广Changed | FAIL；9 PASS/2 FAIL/15 BLOCKED/27 N_A；2400 tests、1 skip，3337.056s | 原科学边界逆向依赖与guard消息断言错误已修，保留原失败记录 |
| ee0聚焦Changed | PASS；7 PASS/37 N_A、28 tests/0 skip，1820.198s | 含完整双发行父方法1794.208s；不是最终90的完整重跑 |
| ee0原15 blocked消费者逐项补检 | 11 PASS/4 FAIL/0 BLOCKED | 40个输入前后SHA相同；原阶段失败不改写，逐阶段完整表在evidence/final-consumer-table.md |
| 90最小修复定向回归 | 87 tests PASS/0 skip，285.105s | 严格converter、旧执行拒绝、compensation历史basis、真实provider/host保护等；evidence/final-consumer-fixes-targeted.log与tests.txt |
| 90安装meta | 10 tests PASS，3.507s | evidence/final-installation-meta-90d6d5e8.log |
| 90最终双发行reference_delivery | PASS，1 test/360.732s | 真实参考+安装B软件合同，见上；不代替三格native证据 |
| Lua可移植资源定向 | 1 test PASS，0.408s | 实际Lua5.1.5 PATH；原suite skip记录仍保留，其他11个opt-in/native97等skip未外推验证 |
| 历史深路径ReanalyzeOnly测试 | 原90秒测试仍FAIL；cwd/stream alias断言仍未验证 | 见下，不能报告全catalog绿灯或无性能回归 |

深路径旧observer在baseline a9已零匹配，本轮未改原测试或延长timeout。诊断后代自然结束、实际analysis success/complete且0 native、source认证/哈希不变、错误context拒绝/正确context恢复和资源释放均有证据；这些事实不证明原observer的cwd/alias断言或每一时刻保护，也不能证明90秒问题是B引入或早于B。`evidence/deep-reanalysis-diagnostic/evidence.json`、evidence.md及独立`evidence/b-exit-scope-independent-audit.md`记录原失败、进程身份和completion不变。若C/P4需声明该历史深路径合同或旧Owner全绿，必须先修正有效observer，再在明确预算下验证；本轮不扩成P4性能整改。B生命周期判据由独立合同和真实native保护证据支持。

Ruff、本轮文本字节与diff检查已通过；最终交付文档StructureOnly PASS（322文件、0链接错误）、文本字节PASS（2497文件）及git diff --check PASS。追加文档时的CRLF/EOF检查失败已规范化为LF并复验通过。不无理由重复完整回归、大型模拟或已通过的完整RF/IP安装。最终代码之后仅docs-only记录不触发科学重跑。

#### 旧消费者与C的明确入口

| 旧路径/owner | B实际处理或替代 | C/剩余条件 |
|---|---|---|
| composite SIMION / HandoffResult / segmented_upstream / state_relaunch | 新公共连续native链拒绝跨组件重新释放；中性母群/clock/历史读取保留 | assembly/handoff.py历史reader与其他链依赖继续逐链迁移 |
| 旧固定5物种mass run/resume | 执行拒绝，改公共mass_scan；历史analyze/resume_finalization保留 | 深路径observer/cwd验证按上节C/P4条件 |
| COMSOL composite/retrace/Formal Validate及MATLAB粒子builders | 旧粒子执行guard；合法geometry/field-only和历史Verify/Publish/Recover保留 | MATLAB guard原生正反例未执行，不宣称旧Owner全绿 |
| Candidate本地初态→单次whole Fly | 没有全量退役；未发现跨组件export/relaunch；默认COMSOL模式guard | 本地N100能力/旧等级不可继承为新链资格，C另审 |
| compensation source.ion三臂 | 只保留历史/独立response basis软件消费者 | C的旧生产消费者，不接回新split链、不做native调优 |
| IP–MR / accelerator_interface -FullJoint / prepared_joint | 仍为C试验入口；普通OA→MR prepare只是接口 | 尚未迁移真实粒子链 |
| RF schema12/plan6 recorded-birth | 编译/source/clock/母群软件消费者已迁 | 真实RF recorded Fly未验证，不扩本轮独立RF研究 |

合格缓存自动GC实际删登记215153 B的可回收资产，缺443 B引用只重算N3批、N2/场保留；非研究二进制破坏。任务内可重建解包源码及两个任务worktree在字节备份、归属/依赖/无活进程检查后普通移除，逻辑文件字节合计5,703,472,285 B，不冒称实测物理磁盘释放。归档、wheel、日志、环境、真实PA/MPH/Store及被自动审批拒绝的三个Temp保留；审计见evidence/extracted-build-source-cleanup.json与evidence/final-worktree-cleanup.json。下一批不自动启动，全仓迁移仍未完成。
### B 累计 CLOC（最终代码90d6d5e8）

规范工具实际PASS；原日志 `C:/Users/Liao/msplatform-artifacts/architecture-b-20261127/code-90d6d5e8-cloc.log`。下表直接转录规范输出，每格为 baseline → result（delta）；以指定Git提交为输入，未跟踪研究产物、状态缓存M和随后docs-only提交不混入。


**total**

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| JSON | 282 → 291 (+9) | 0 → 0 (+0) | 0 → 0 (+0) | 126022 → 130154 (+4132) |
| Lua | 119 → 120 (+1) | 413 → 416 (+3) | 828 → 830 (+2) | 13219 → 13273 (+54) |
| MATLAB | 186 → 188 (+2) | 1066 → 1068 (+2) | 2053 → 2067 (+14) | 19701 → 20023 (+322) |
| PowerShell | 150 → 150 (+0) | 1100 → 1101 (+1) | 1195 → 1195 (+0) | 46113 → 46242 (+129) |
| Python | 1435 → 1499 (+64) | 32921 → 33773 (+852) | 42493 → 43096 (+603) | 396258 → 407829 (+11571) |
| SIMION GEM | 10 → 10 (+0) | 26 → 26 (+0) | 51 → 51 (+0) | 214 → 214 (+0) |
| TOML | 5 → 9 (+4) | 43 → 46 (+3) | 2 → 2 (+0) | 219 → 283 (+64) |
| YAML | 2 → 2 (+0) | 8 → 8 (+0) | 20 → 20 (+0) | 506 → 506 (+0) |
| SUM | 2189 → 2269 (+80) | 35577 → 36438 (+861) | 46642 → 47261 (+619) | 602252 → 618524 (+16272) |

**production**

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| JSON | 259 → 267 (+8) | 0 → 0 (+0) | 0 → 0 (+0) | 42340 → 45539 (+3199) |
| Lua | 99 → 100 (+1) | 333 → 336 (+3) | 703 → 705 (+2) | 11141 → 11195 (+54) |
| MATLAB | 118 → 120 (+2) | 526 → 528 (+2) | 1462 → 1476 (+14) | 12164 → 12486 (+322) |
| PowerShell | 138 → 138 (+0) | 1037 → 1038 (+1) | 1149 → 1149 (+0) | 44012 → 44131 (+119) |
| Python | 685 → 714 (+29) | 16804 → 17261 (+457) | 11609 → 11935 (+326) | 182981 → 189469 (+6488) |
| SIMION GEM | 10 → 10 (+0) | 26 → 26 (+0) | 51 → 51 (+0) | 214 → 214 (+0) |
| TOML | 5 → 9 (+4) | 43 → 46 (+3) | 2 → 2 (+0) | 219 → 283 (+64) |
| YAML | 2 → 2 (+0) | 8 → 8 (+0) | 20 → 20 (+0) | 506 → 506 (+0) |
| SUM | 1316 → 1360 (+44) | 18777 → 19243 (+466) | 14996 → 15338 (+342) | 293577 → 303823 (+10246) |

**tests**

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| JSON | 23 → 24 (+1) | 0 → 0 (+0) | 0 → 0 (+0) | 83682 → 84615 (+933) |
| Lua | 20 → 20 (+0) | 80 → 80 (+0) | 125 → 125 (+0) | 2078 → 2078 (+0) |
| MATLAB | 68 → 68 (+0) | 540 → 540 (+0) | 591 → 591 (+0) | 7537 → 7537 (+0) |
| PowerShell | 12 → 12 (+0) | 63 → 63 (+0) | 46 → 46 (+0) | 2101 → 2111 (+10) |
| Python | 750 → 785 (+35) | 16117 → 16512 (+395) | 30884 → 31161 (+277) | 213277 → 218360 (+5083) |
| SUM | 873 → 909 (+36) | 16800 → 17195 (+395) | 31646 → 31923 (+277) | 308675 → 314701 (+6026) |

**unclassified**

| language | files | blank | comment | code |
|---|---:|---:|---:|---:|
| SUM | 0 → 0 (+0) | 0 → 0 (+0) | 0 → 0 (+0) | 0 → 0 (+0) |

```text
CLOC_DELTA=PASS
BASELINE=a9d76aa4dcdbaf8099c9ce5aa0585d6fce18c3be
RESULT=90d6d5e8b67e5b0bfe3e823b0130c30c266eea2b
CLOC_VERSION=2.10
CLASSIFIER_SHA256=d3abfc94e920066445561b696c76131b43eab9713a0cbcb9e2c1270ba7136952
LANGUAGE_DEFINITION_SHA256=985e60f06bd8981c36966a0895cccfccd182fd625c79eb6ae94b65a12c5508a6
INPUT_IDENTITY SNAPSHOT=baseline FILES=2234 SHA256=2e9c89b9e7a4ddd9d2d2e95a292cfbe15ca5b439965fa762bd82c4277fa07818
INPUT_IDENTITY SNAPSHOT=result FILES=2314 SHA256=e24f7bc6d5c442be4609c186ff615342a618950c2cf4325852b9e011c90164f6
FILTER=extensions=.py,.m,.ps1,.lua,.gem,.fly2,.json,.toml,.yml,.yaml,.c,.h,.cc,.cpp,.cxx,.hpp,.cs,.java,.js,.jsx,.ts,.tsx,.go,.rs,.rb,.php,.swift,.kt,.kts,.sh,.bash,.zsh,.bat,.cmd;excluded_components=.git,.venv,.tmp,artifacts,generated,vendor,vendors,third_party,third-party,thirdparty,run,runs;excluded_lifecycle_paths=any/docs/history/**|root/scratch/**|artifacts/projects/<project>/(archive|scratch)/**;language_overrides=.m:MATLAB|.fly2:Lua|.gem:SIMION_GEM;production=execution_profile_entrypoint|run_*.ps1|verify_*.ps1|tests/support(non-test-named);tests=fixture|test_support|testing_support_path|test_*.(py|ps1|m|lua)|*_test.py|tests_boundary/*_fixtures.py|tests/**/__init__.py|*Test.m|*.Tests.*;unclassified=other_code_below_test_or_tests_path;worktree_source=git_tracked_plus_nonignored_untracked
```
