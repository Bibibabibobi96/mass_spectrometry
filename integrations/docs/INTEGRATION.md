# 统一装配实施状态

返回[集成入口](../README.md)。本页维护直属装配的有效入口、证据边界和未完成动作；组件自身资格归各PROJECT。
阶段过程已冻结为[迁移与公共执行机制证据](history/20261026__assembly-migration-execution-evidence.md)。
本页记录2026-10-26最近已核验的状态；运行随后发生的事实以其受管记录为准。

## 当前边界

用户确认的14项目标仍未完成。跨项目工作流已迁到根`integrations/`，多条真实链已有执行和恢复证据，
但适用GUI／CAD及最终门禁、审查与交付尚未全部闭合。N2完整飞行／默认回放、当前OA→MR、strict共同场／有限脉冲及保存CPT导出恢复已完成声明范围的功能验证。
成功执行、数值等价、物理性能和Formal资格分别判断；负结果与原运行身份不因迁移而改写。

多实例原生验收按用户更新后的目标只要求同项目两个实例；N2严格栅格链已完整通过。
这里N3仅表示三个多极杆实例的复用验证：当前冻结配方实际为三个八极杆→OA→单反射TOF，
不是经典Q1→q2→Q3三重四极杆。用户已明确本次只验证多实例功能，不实施三重四极杆配方或专用工作流。
以下N2前驱保留故障与恢复边界：115004已发布全部三个前端场，随后在reflectron调压访问冲突。
隔离验证后已将该调用替换为官方PA API；130533续接三个前端场全部hit且未Refine，
反射器构建、调压、standalone导出及下游原生审计均通过；随后工作台重开因两个静态电极占据检查失败而终止，未进入Fly。
`parent:static_e9`与`parent:static_e44`的整数PA节点标志为电极、选中实例为3，但工作台点查询报告非电极。
132337小裁域原生查询已确认两原点处在离散金属cell下游面：原点／回投点均非内部，向金属侧查询均为电极。
现已修正验收语义：保留原点、节点与优先级检查，真实金属另须有相邻完整金属cell；世界点占据单独记录，不从节点标志推导。
134240沿相同作者科学输入和预算续接，显式复用130533下游发布及公共前端场；三批工作台重开均通过94点检查，
基线与默认回放各100粒子均自然完成，比较差异为空，run已发布success。公共调度实测18.45 GiB／worker后准入两路。
held-OFF工况100个终态均为`non_detector_splat_instance_3`、探测器命中0；这是完整母群与回放一致性证据，不是正向物理性能资格。
N3的143032小型原生预检发现当前网格下两处有限厚金属仅剩单层节点、无完整金属cell；尚未启动四个大场。
仅改变网格原点的候选虽改善这两处，却把风险转移到其他薄片，不能采用局部凑点作为正式修复。
后继改为复用既有parent＋入口Dirichlet细域：细域覆盖全部多极杆及真实侧孔穿墙窗口，guard后的active范围须包含真实包络，
不要求入口数值patch覆盖整个OA横截面。细域格距为0.25／0.5／0.05 mm，父域只向负Z扩0.1 mm以保留guard净空。
六份原源／投影／clock／epoch／配方文件及两域中的严格器件body逐字节相同，电压工作点保持不变。
[151945原生小裁域](../../../artifacts/projects/instrument_assembly/runs/20261026_151945__test__simion__n3-refinement-crop/summary.json)
覆盖三个多极杆各自的两端盖、两孔板与屏蔽壁，共15项：原节点ID和相邻完整金属cell均通过（每点4或8个cell）。
共2625个复制节点、405个邻域节点及75次工作台查询；无Refine／Fly／GUI，清理31份临时PA共16,447,084 bytes。
实际公开准备已通过，八个工作场的飞行数组下限为38,177,428,440 bytes（35.556 GiB）；40 GiB预算仅为有余量的未知峰候选。
局部样点采样同时改为真实三维金属交集，取整后不得落入guard代替交集节点；172项联合回归265.065秒、Ruff、绑定与开发标准通过。
[154405初次完整运行](../../../artifacts/projects/instrument_assembly/runs/20261026_154405__sim__simion__single-reflection-n3-fine-n100/summary.json)
在首个carrier发布前遭遇主机非正常关机，原owner与SIMION进程均已消失，末写usage为全零；没有已完成N3场或飞行可复用。
现已通过公共失败收尾发布interrupted、精确释放该停止owner租约，并用公共seal-stopped-payload封存原6,657,406,766 bytes。
首场handoff原先无条件要求尚不存在的前端发布收据，现已按显式field transaction路径修复；39项准备模块回归41.770秒通过。
[160951新身份续接](../../../artifacts/projects/instrument_assembly/runs/20261026_160951__sim__simion__single-reflection-n3-reboot-resume-n100/run_config.json)
已由既有公共producer_handoff将同一building事务交给新producer；10份实际科学文件与154405逐字节相同。
独立实测审查22项通过，公共事务仍为building、generation为空；这不是求解器checkpoint续算，也不冒称N3场已完成。
160951已完成carrier求场及standalone导出，随后在`static_e10`原始ID审计失败，run已failed并封存。
165832同源小裁域确认原点位于相邻端盖共同接触面，实际ID为44；六个内部孔板与三个屏蔽体中段候选均为原预期ID且metal=true。
静态样点改按实际角色选取长屏蔽体或内部孔板，保留原失败证据；不改尺寸、位姿、电压或期望ID。
新续接准备与160951两份GEM、几何、源、时钟及父配方逐字节相同，四个父工作场身份不变；
公共building事务保留6,571,660,856 bytes carrier，后继须重新审计，不重复Refine，也不提前视为ready。
171811新身份续接已完成carrier原生重新审计与公共发布，没有重新Refine该成员；当前继续缺失的独立RF响应场。
随后用户取消三个实例的额外原生验收，已按精确PID与启动时间沿公共停止函数停止首个RF构建；
原owner自然发布failed并封存，未执行N3工作台／Fly。独立范围取消收据保留原因，不把它当作科学或健康失败。
不再续接N3；其已完成carrier、原失败点和轻量回归证据保留。锚点／恢复修改的93项回归250.340秒通过，
Ruff、绑定新鲜度与开发标准通过；本轮L1已通过，其中integration为584项测试／1549.064秒。
首场事务恢复允许上下游尚无发布收据，普通飞行批次恢复仍要求两份发布来源。
已有TOF发布继续显式复用。重启中断的L2不计通过；后继`migration_l2_after_reboot_recovery_20261026.log`
已自然结束并记录`REPOSITORY_INTEGRATION_GATE=PASS`，覆盖本轮锚点修改之前的快照。
前驱103316因容量下限少计元数据而失败，其两个已发布场也由115004成功消费。
共同场链042142及后处理075124的已完成证据继续有效；缺失阶段执行和完整批次复用均不是求解器checkpoint续算。
GUI按用户明确决定暂缓；其缺口不由headless点检、默认回放或源码测试代替。

装配、源与波形职责只按[连接与驱动标准](../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md)；
健康求解的告警／处置和昂贵阶段恢复只按[开发标准](../../docs/DEVELOPMENT_STANDARDS.md#昂贵阶段复用与中断恢复)。
容量目标与最低空闲保护只读取[唯一机器政策](../../common/contracts/artifact_capacity_policy.json)，
不沿历史预案复制阈值或把磁盘空闲等同容量准入。

## 装配与公共机制

[配方解析](../README.md#配方解析)冻结完整父配方与组件直接位姿；默认运行所选冻结配方全部实例，
局部范围必须显式派生。新增器件不改变历史实验，不自动选择最新整机。当前plan的`layout_only`
不意味着各求解器已支持任意器件；不支持的选中组件明确拒绝。

提供者发布完整几何、电极和物理端口，装配只绑定实际实例；几何与源使用提供者局部工作frame，
父plan保留直接位姿，不要求OA或MR位于父原点。源绑定实例和局部frame，保留原6D、ID、母群、
出生时间、上游损失、RF相位和唯一仪器时钟；换范围不重新投影已记录状态或重新采样源。

| 目标项 | 已实现范围 | 尚未闭合的边界 |
|---|---|---|
| 1 组件与装配权威 | 完整OA／IP／MR接口、逐实例电极映射、独立驱动及实际脱仓准备；同项目N2场、工作台、N100 Fly及默认回放通过 | 用户要求的双实例功能验收已闭合；三实例只保留已有轻量回归 |
| 2 冻结范围稳定 | 冻结父配方、默认全部／显式local、父配方增长及直接位姿回归；声明链路已有原生证据 | 不授予任意相对角或任意拓扑资格 |
| 3 源与唯一时钟 | 公共实录源选择与Cartesian表示；N100 CPT完整初态、原ID／母群／clock及1600个原生状态 | 声明链路的源／frame／clock证据已闭合；适用GUI仍暂缓 |
| 4 公共波形 | 公共RF、矩形半开脉冲、已有三次过渡及边沿限步；IP／MR实际消费者冻结数学依赖，科学时序留在工作流；strict同BVP有限脉冲对照已执行 | 跨后端数值等价未获，不能以对照完成升级资格 |
| 5 独立工作场 | 成员级PA复用、实际电极电压、COMSOL显式消费投影 | strict原生采样及分阶段失效复用已验证；不因此授予数值等价或物理资格 |
| 6 阶段与整批恢复 | 公共事务、完整批、已解场与CPT导出复用；首场handoff、两代零Fly恢复和保存CPT实际重开导出均已通过 | 不冒称求解器中途积分checkpoint续算 |
| 7 执行与观测 | 公共调度、完成事实、终态发布、失败收尾及目标进程树观测；真实COMSOL正常完成与清理 | 最终全局门禁待完成；真实商业危险停止未触发，不能冒称实测 |
| 8 冻结与上游消费 | 明确consumer闭包、按需上游记录、脱仓回归及后继真实消费 | 最终全局门禁待完成 |
| 9 粒子与批次 | 公共typed读取、源行批映射及合并；声明链路已核对，科学分母留在项目 | 不将未解析停止改写为物理碰撞 |
| 10 回放差异 | 公共粒子事件分组／配对已接局部前端、共同脉冲及单反射回放，保留原字段顺序及科学判据 | 默认回放通过；跨后端数值等价未获 |
| 11 统计与场对照 | 公共峰宽、同定义样点配对／残差及总体二阶矩；IP／MR消费者已替换重复计算 | 不同统计定义保持独立，共同BVP数值等价未获 |
| 12 碰撞生命周期 | IP与冷却共用HS1加载／冻结／复位适配 | 不据文本迁移取得碰撞物理资格 |
| 13 真实链与验收 | 声明冻结链路、双实例、分段、strict跨后端及恢复证据已闭合；负结果保留 | 适用GUI／CAD仍按用户决定暂缓 |
| 14 删除与交付 | 旧入口、重复缓存／运输／解析及无消费者测试持续退役；8909e310、CI预算6b99467e、依赖规划399dc5a8及Windows夹具路径dba47b0e已推送 | 本轮590项integration及5个权限失败阶段复验通过，CLOC已刷新；最终整合L2、GUI／CAD及交付审查待完成 |

N2／N3已有当前schema作者准备包和独立尺寸、DC、RF频率／相位回归。N2早期父carrier几何审计失败已修复；
当前三个前端场均已发布，134240已完成N2完整飞行与默认回放；N3父carrier已审计发布，其他独立场及飞行仍未完成。
N3细域薄金属表示已通过局部原生预检，完整场／工作台验收未完成且不再作为本次关闭条件；N2已完成覆盖数组、下游与进程开销的首批观测；
不改网格、源、母群或物理范围来凑旧N1预算。准备包只证明机制，不是三重四极杆物理运行资格。
两个冻结请求均为`held_off`，现已从原科学mode派生实际场依赖，省略恒0的脉冲响应构建／加载，
完整carrier仍保留真实金属mask；timed及discover保留整个工作流所需脉冲响应，不新增成员配置。
实际N2／N3重新准备通过，前端场分别为3／4个；保留成员cache key、GEM、几何、原始母群、投影与clock字节不变。
加共享下游后，公共数组下限分别为19,742,567,290／32,864,387,290 bytes；这不是完整进程峰值，
N3当前held-OFF作者由公共几何／场编译器重新核算为四场，821,203,200节点：构建数组内存下限
16,424,064,000 bytes，飞行数组下限32,848,128,000 bytes，冷构建磁盘下限39,417,753,600 bytes。
32 GiB飞行预算仅余1,511,610,368 bytes供下游场及进程开销，不能据数组下限判定足够；
该只读预检记录于`n3_resource_readiness_20261026.json`，未原生执行或读取大型PA。
可按公开政策审定初始预算并标记`unknown_peak`，首个保留正式批次完善实测画像，
不要求先有峰值才能首飞。省略分支已通过focused合同、owner回归及最新完整L2；N2原生完成，N3额外原生按用户范围决定取消。
N2完整四阶段工程预算已审定：field／workbench／Fly与默认回放分别24／16／32／32 GiB，磁盘64 GiB。
[080512尝试](../../../artifacts/projects/instrument_assembly/runs/20261026_080512__sim__simion__single-reflection-n2-held-off-n100/summary.json)
在冻结准备阶段因resolved schema的enclosure治理引用缺少`multipole_design_request.schema.json`而失败并封存，
未启动原生求场或Fly。库存已有该schema，现已补single-reflection consumer；原冻结快照的真实N2／N3均复现失败，
修复后实际冻结、脱仓准备均通过。标准脱仓回归亦覆盖该治理分支，Ruff、绑定新鲜度与开发标准通过。
后继081510越过prepare，但因显式094111下游场的六个builder／GEM版本与当前快照不同而在规划阶段失败，仍无原生执行。
已知110745仅复用同一旧源，不能重标为当前发布；新作者显式走当前builder构建约13 MB小下游，原请求保留，
其余源、clock、配方、物理和数值输入逐值不变。完整冻结、脱仓及场身份预检已通过，不放宽资源身份保护。
原100粒子、尺寸、RF幅值／频率／相位和clock保持；该N2作者group DC与common offset均0，不冒称原生覆盖非零DC。

[082551原生运行](../../../artifacts/projects/instrument_assembly/runs/20261026_082551__sim__simion__single-reflection-n2-held-off-n100/summary.json)
已完成GEM转PA、carrier求场与导出，随后在`parent_carrier_off_audit`的`static_e10`原始电极ID检查失败，
owner已退出并发布failed，不能以残留阶段usage的running状态视为仍在求解。物理端面直接位姿未改，
当前调查聚焦真实接触面附近栅格占用；不能删除审计点、改期望ID或引入补偿间隙制造通过。
未发布的carrier及工作PA仍在原公共事务下受保护，不冒充ready资产；审计或GEM变化的复用资格分别判断。
后继小型原生栅格探针曾被严格容量账本拒绝：唯一旧对象的`class`键损坏，已完成收据的raw备份能认证原记录。
公共单键恢复已通过独立审查、22项主树测试及真实dry-run，随后发布complete恢复收据；仅一个原始字节改变，
resident仍为650,291,472,910 bytes。没有初始化、重校准、扫描科学载荷或私改账本绕过准入。
后继小探针只判断接触附近栅格占用，不能替代整域求场审计、Fly或多实例物理验收。
[095935探针](../../../artifacts/projects/instrument_assembly/runs/20261026_095935__test__simion__n2-gem-crop/summary.json)
的六项原生GEM转换均完成；原接触节点GU170／87／525在`surface=none`普通`within`下被后绘制端盖写为44，
同源严格包含填充及fractional对照均为预期10，邻接GU169／170／171分别为0／10／44。
端盖独占环带节点三个变体均为10。原审计点、直接位姿、器件尺寸及期望编号均未改。
探针在终态误用retention参数而failed；公共失败收尾已保留六份CSV并删除40,280 bytes临时PA／surface，
不能把该run称为success。结果仅证明栅格填充差异；正式修复仍须核对供应商表面语义和完整场审计。
[101223自动表面探针](../../../artifacts/projects/instrument_assembly/runs/20261026_101223__test__simion__n2-gem-auto/summary.json)
已完成18次原生调用及两种实际普通PA导出的独立重开，均自然退出且无surface附属文件，
但`surface=auto`在原接触节点仍得到10／44／44，未修复原问题，整体正确保留failed。
孔边及零厚sheet检查、两种导出各637节点及三个非网格点的V／E逐值对照通过；这不能抵消接触判据失败。
因此不部署auto候选，不把供应商一般推荐替代本机真实验证；后继只考虑已证明有效的严格填充表示。

正式修复仅在`render_frontend_domain`将受控body的普通正填充改为`within_inside_or_on`，
全部孔操作、提供者body、独立fractional导出及none header保持。106项几何／场／准备／提供者回归及Ruff通过；
原历史几何对照只规范化这一指令差异，仍逐字节检查尺寸、位姿、孔和源／时钟。
N2／N3实际公共冻结、脱仓准备和场计划通过：生产GEM分别只有100／137处指令变化，
六份源／时钟／几何载荷保持，场分别选择3／4成员，identity差异仅GEM，新key不接受旧场。
N2八份TOF资源及投影与082551相同；N3原请求仍指版本不同的094111来源，保留拒绝，
后继优先显式引用N2当前TOF发布，不重复求同一场。
[102930实际生产GEM探针](../../../artifacts/projects/instrument_assembly/runs/20261026_102930__test__simion__n2-gem-strict/summary.json)
四crop、8次原生调用全部完成、节点差异0，success及32项输出的完整manifest复核通过；没有Refine／Fly。
该小证据只证明局部栅格。临时PA清理20,608 bytes，冻结后一次性脚本清理13,566 bytes；
N2／N3离线准备及runtime副本共清理169,710,028 bytes，小报告与GEM差异保留。

用户再次明确授权后，[103316完整N2输入](../../../artifacts/projects/instrument_assembly/runs/20261026_103316__sim__simion__single-reflection-n2-strict-n100/run_config.json)
沿原100粒子、clock、尺寸、位姿和已审定四阶段预算提交公共队列。
严格carrier及第一个独立RF响应已完成原生求场，并分别通过93个物理样点审计，越过082551失败点。
103316在开始RF02前因剩余承诺少6233 bytes而failed，未进入Fly；这是把裸数组下限当精确承诺造成的误阻，
差额来自两个PA文件头、manifest及pointer，不是64 GiB工程预算不足。
现有公共容量更新已用于在实际阶段下限不足时补额再准入，不加猜测padding、不扩大工程预算。
新增三项及完整field-stage 38项（174.730 s）、Ruff、PS AST和开发标准通过。
[115004续接输入](../../../artifacts/projects/instrument_assembly/runs/20261026_115004__sim__simion__single-reflection-n2-resume-n100/run_config.json)
科学作者及预算保持不变；实际probe确认carrier与RF01均hit、RF02 miss，只补缺失场，不重新求前两场。
RF02已发布generation `3381B5C2DA396FAB3494324984EA353CC4D5346137DFF988625720F2779A51CB`，
三个场的发布引用进入`results/single_reflection/field_receipt.json`。
随后下游reflectron阶段自然失败，usage为process_failed、3.83秒、无warning或limit_name；
`downstream_execution_records.json`保留原生退出码−1073741819（0xC0000005）。
日志记录Refine完成，但Fast Adjust没有完成标记；具体触发原因仍待隔离验证。
失败run已封存183,221,168 bytes／248文件，
不得改写其终态；后继新身份复用三个有效前端场。未完成Fly或回放，不能据单个场成功宣称N2完整通过。

[045007原生隔离](../../../artifacts/projects/instrument_assembly/runs/20261026_045007__test__simion__reflectron-api-isolation/summary.json)
运输原21份已refined反射器family到独立私有副本，不重新Refine。原builder的adjust-only再次以
0xC0000005失败；官方PA API完成调压、保存和独立进程重开，19电极及8个场样点核对通过。
总run以failed保留CLI负证据，未Fly／GUI。最小替换方案及官方依据归[提供者状态](../../projects/single_reflection_oa_tof_mass_analyzer/docs/PROJECT.md#当前状态)；
当前源码已替换，38项提供者／下游回归7.245秒通过，Ruff与开发标准检查通过。
[130533续接](../../../artifacts/projects/instrument_assembly/runs/20261026_130533__sim__simion__single-reflection-n2-api-resume-n100/run_config.json)
沿同一作者与预算，三个前端场均`refine_performed=false`；实际反射器调压、导出及下游审计通过。
该运行随后在首批工作台重开占据检查失败，已封存5,512,729,193 bytes／260文件，未进入Fly／默认回放。
两个失败点的原始节点、坐标及工作台查询事实保留；新下游发布可供后继显式复用，不能提前判N2整链成功。

[132337小裁域](../../../artifacts/projects/instrument_assembly/runs/20261026_132337__test__simion__n2-occupancy-crop/summary.json)
使用同一严格GEM、原格距及两原始点，54节点／12工作台查询均完成，无Refine／Fly／GUI。
e9相邻节点为9／9／vacuum，e44为10／44／vacuum；两case向金属侧查询true、真空侧false，未发现位姿漂移或金属体积缺失。
该run因一次性owner清理参数误用而failed封存，不能改称run success；原生日志、节点和查询表仍为有效诊断证据。
当前surface=none验收新增相邻8角点均为电极的cell检查，允许跨ID，不要求理想零厚网格具有体积；
孤立单层、错误节点及错误优先级仍失败。主树79项相关回归103.606秒、Ruff和开发标准检查通过。
原GEM、尺寸、位姿、源、时钟及三个parent缓存键保持，不通过挪点、改厚度或重求场消除此验收误判。
[134240续接](../../../artifacts/projects/instrument_assembly/runs/20261026_134240__sim__simion__single-reflection-n2-topology-resume-n100/run_config.json)
只新增显式130533下游来源绑定，八份下游资源及提供者身份预检相同，预检未读取或哈希大型载荷。
实际三批IOB均完成94点验证，e9／e44原world查询仍false、相邻完整金属cell均4且节点／实例正确；未改查询点。
公共调度首个正式10粒子批自然exit0，45秒观测后按10／50／40三批、最多两路完成基线与默认回放。
`replay_comparison.json`记录`passed=true`、100个continued及空differences；summary为success，6个原生批次、0复用飞行批。
本轮前端与下游场均复用、没有重新Refine；保留6,116,188,843 bytes／289文件。
N3的`20261026_143032__test__simion__n3-phase-crop`诊断run成功封存，但原作者的入口端盖与孔板均为零完整cell，物理拓扑检查失败。
四个小裁域无Refine／Fly，原始尺寸、位姿与源未改；临时PA已退役。后继细域与取消决定见本页当前边界，不再提交N3大场。
旧D6未发布事务中的两个错误栅格PA已沿既有公共取消流程退役，实际删除10,520,697,852 bytes，
原事务、失败输入和重建证据保留。旧台账仅记3128 bytes，保留journal后为11210 bytes；
这次ledger对象增8082 bytes，与物理释放必须分开报告，不虚报为台账减少10.52 GB。
该差异暴露失败事务停写收尾未刷新实际驻留量的问题。现有`advance-transaction --record-stage-only`
已增加同owner／producer的building事务记账：只统计该事务实际字节，不哈希PA、不推进状态、不seal或publish。
原生失败收尾调用一次；prepared／published不重复登记。若记账本身失败，同一内部defer字段使外部owner
保留容量承诺与保护租约，发布原科学failed及次要记账说明，延后容量封存，不先将承诺归零。
focused九项及三个相关完整模块160项（231.905 s）、Ruff、三个入口PS AST和开发标准通过；
这只验证故障机制，不改在途103316的冻结owner，也不借之前启动的主L1充当本题整轮验收。

## 单反射整机

[公开owner](../workflows/single_reflection_flight/run.ps1)接收`-Request`与`-ExecutionBudgetPath`，
默认执行完整Fly；`-FieldDesignOnly`、`-WorkbenchOnly`显式选择有限阶段。
内部`execute.ps1`由owner调用，不作为另一个公开run入口。当前作者格式见[schema 9](../workflows/single_reflection_flight/schema.json)。

request引用冻结父plan及逐实例提供者，显式数值域与已发布场来源。普通源和实录
`recorded_pre_pulse_state`共用同一装配；未声明`pulse_decision`时消费全部实际timed pre-state，
声明时严格保留原选择、顺序与绑定。完整批恢复通过显式前驱manifest进入既有公共机制，
不拼接中断粒子片段，不扫描最新run或重复求场。

当前原生证据为
[110745运行](../../../artifacts/projects/instrument_assembly/runs/20261025_110745__sim__simion__single-reflection-flight/summary.json)：
六工作场、完整N=100 Fly、保存IOB默认回放及终态发布已完成，回放差异为空。
**探测器命中为0**，100个终态为`non_detector_splat_instance_5`，未到达反射器；
不能由实例编号推断真实碰撞实体或宣称整机物理链通过。同closure重复Fly已有后继证据，详细身份见历史。

后继原生点检已闭合104个有判据点和97个源节点，700个终态邻域点只观察。
这区分理想栅节点、电极占用和世界坐标选择；不证明整个空间、动态场或数值外边界连续性。
长期canonical路径的IOB独立重开已通过，GUI参数页及适用几何验收仍开放。

## 共同场与有限脉冲

[共同静态场owner](../workflows/paired_accelerator_static_field/execute.ps1)消费同一OA-only冻结实体、
ON电压、边界、数值box和样点。`-Request -DryRun`仅准备；原生另须`-SolverAuthorized`和显式预算。
`-ComsolSourceManifest`明确选择已保存prepared或solved来源：prepared只补缺失solve，solved只导出，
两者都不重建几何／mesh；不是中途积分checkpoint。PA沿公共事务消费，来源与模型仍只有一个owner。

235338已完成真实COMSOL网格、prepared保存、静态求解、solved保存和115点比较；
原owner因终态重复retention失败。[011244恢复](../../../artifacts/projects/instrument_assembly/runs/20261026_011244__sim__cross__paired-accelerator-static-field/summary.json)
已成功复用原MPH／PA、重开导出并发布，采样CSV与原run逐字节相同，无MPH副本或重复求解。
共同BVP功能及已解场恢复成立，**数值等价仍未获得**。
014055更严格Refine诊断只作敏感性证据，其派生PA不替代当前原发布基线。

[有限脉冲owner](../workflows/paired_accelerator_pulse/execute.ps1)只接受显式静态场producer、实录源、
绝对观察时刻和numerics；脉冲、物种、原母群与OFF电压从原权威派生。
`-PredecessorManifest`复用完成事实绑定的阶段和完整批次，已发布CSV直接分析；
保存模型只用于缺失导出，不把初态重演称为续算。完整输出按原ID与声明时刻外配对，缺态／错时明确保留，
只发布`diagnostic_only`差值，不增设物理容差或宣称数值等价。

| 实际运行 | 当前有效事实 | 限制 |
|---|---|---|
| 040326 | 原N=100 SIMION基线和保存工作台默认回放passed，差异为空 | 100个停止原因均unknown；同run CPT未Compute成功 |
| 041645 | 全部SIMION已复用；CPT配置回读失败证据保留 | 不形成可用粒子解 |
| [042142](../../../artifacts/projects/instrument_assembly/runs/20261026_042142__sim__cross__paired-accelerator-pulse/summary.json) | 从041645二次恢复只补CPT，raw模型保存、初态／轨迹导出、比较及终态发布success | 只证明声明OA范围功能；跨后端数值等价、GUI及Formal未获 |
| [075124](../../../artifacts/projects/instrument_assembly/runs/20261026_075124__sim__cross__paired-accelerator-pulse/summary.json) | 新身份复用042142粒子解／导出和SIMION基线／回放，只做分析及发布success | `native_executed=false`；不证明缺失CSV时的MPH重开导出 |

042142保留原100 Da／+1的100粒子及绝对时钟，16时刻共1600个COMSOL有限状态，初态完整，实际／存储时刻一致。
SIMION仅609个观察可配对，991个缺失记录明确保留；位置最大绝对差x／y／z为2.67443／0.13337／7.39137 mm。
比较仍为`diagnostic_only`，不据有限状态数量判断存活；COMSOL Freeze可保留停止后的状态，SIMION停止后不再有后续观察。
原始模型10,377,020,699 bytes及完整差异表均已封存，未对缺失轨迹插值、删粒子或重新定义母群。
075124沿同一公开owner及显式前驱完成真实后处理恢复；四项复用均true，没有再次求场、飞行或重哈希科学PA／MPH。
新增容量仅承诺64 MiB，终态共21,061,407 bytes；大型原始模型保持原owner，仅以冻结来源引用。
独立复核确认差异CSV的已发布字节身份不变，比较JSON除本次输出路径外逐值相同。
固定源码闭包仍运输公共seed占位PA；这不等于加载科学场，但不能表述为没有任何PA文件复制。
当前源码的离线公共准备／加载核对已确认：共同场GEM相对011244只有26处严格正填充变化，
其余字节保持；COMSOL BVP投影仍接受235338已保存的解。历史042142重新准备后，公共恢复API实际
返回CPT模型、导出、SIMION基线及回放四项可复用，没有读取或哈希大型PA／MPH。
011244及同类静态export-only consumer的来源接线已实现：加载器核验其已绑定的原COMSOL producer及同BVP，
模型来源记录中的plan／MPH始终归原producer，pulse另从所选static manifest冻结该consumer自己的plan／PA发布。
重复export保持同一原模型来源，不递归搜索祖先；static owner沿已有容量保护加入实际借用模型路径。
依赖清单补齐static对既有来源模块的消费。主树42项回归62.224秒、Ruff、绑定新鲜度和开发标准检查通过，
实际011244→235338小元数据加载通过且无原生载荷读取；候选纯准备已确认042142四阶段可复用。
这些不代替新strict PA或缺失导出的原生恢复验收，不复制MPH或重复Compute。
新strict PA发布后再按实际成员身份决定SIMION批次是否失效，不预断必须重飞；原负结果不改写。
原运行的worker profile仅记首批低峰值，不能作为模型真实峰值；后继公共发布已改用实际较高worker测量，
历史profile不改写。042142服务工作集超过原规划阈值已告警；不能把单服务观测伪装成完整进程树预算保护。
后继COMSOL入口已接公共持续预算及critical处置；042142未热替换该实现，健康耗时或日志静默本身不触发强停。

完整oaTOF的GeometryOnly共用现有建模入口，在`geom1.run`后保存早退；CAD已支持实际20环和反射器环动态发现。
[075441提供者运行](../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261026_075441__test__comsol__geo/summary.json)
已完成18项MATLAB Unit、真实保存、独立进程重开及headless STEP：45域、40物理对象，physics／mesh／study均空，
重开清单一致，导出STEP AP203／mm整包及40个独立部件。两次公共COMSOL入口、终态发布和容量收尾均成功。
新MPH为2,774,497 bytes，run共4,695,098 bytes；未重建场或飞行，原110745几何、电压投影及侧孔不变。
公共观测的build／reopen阶段分别73.798／55.735 s、进程树峰值2,885,009,408／2,619,592,704 bytes；
两次均正常完成，无告警，全部商业进程及公共租约已退出。不能把小几何峰值用于CPT或多实例PA准入。
该证据只覆盖完整oaTOF组件，不包含上游多极杆实体，也不是SolidWorks／GUI或Formal几何资格。
几何／CAD仍归oaTOF提供者项目，后续装配引用它，不借integration owner绕过项目路径保护。

## 局部前端执行与复核

[裸导引入口](../workflows/local_frontend/execute.ps1)和[冷却入口](../workflows/cooled_frontend/execute.ps1)
各自接收schema 3请求；冻结完整父plan，默认full或显式local，不复制组件内部几何。
从仓库根替换路径运行；以下最后一条会启动商业求解，须有对应科学运行授权及显式预算：

```powershell
& integrations/workflows/local_frontend/execute.ps1 -Request "<request.json>" -ValidateOnly
& integrations/workflows/local_frontend/execute.ps1 -Request "<request.json>" -PrepareOnly -OutputDirectory "<managed-run>"
& integrations/workflows/local_frontend/execute.ps1 -Request "<request.json>" -ExecutionBudgetPath "<budget.json>" -SolverAuthorized
```

`PrepareOnly`只写调用方已建立的受管run，不能用任意空目录或改变owner。二区／三区分别消费真实提供者，
不能把旧八模式整机场当作裸导引场；位置、机械孔与数值carve分别处理，源保持全部原ID和唯一时钟。

三区[165815迁移对照](../../../artifacts/projects/instrument_assembly/runs/20261022_165815__sim__simion__local-bare-guide-oa/summary.json)
已完成N=100、源与规范事件逐值对照、69出口／31损失及新进程默认回放，差异字段0。
只证明冻结局部工况迁移一致，不授予MR接受、整机分辨率或Formal资格。
冷却[220720运行](../../../artifacts/projects/instrument_assembly/runs/20261024_220720__sim__simion__cooled-frontend-population/summary.json)
复用当前公共七场，原100 ID闭合为32出口、36 timeout、32未解析停止，实际峰值并发13；未Refine或复制PA。
其`saved_controls_only`检查不包含第二次完整Fly，不能写为逐轨迹默认回放；未解析停止不归为碰撞实体。

## OA／IP接口准备与绑定

[accelerator_interface入口](../workflows/accelerator_interface/execute.ps1)拥有跨项目准备与绑定；
OA、IP和MR分别拥有自身设计与科学约束。IP设计必须显式提供schema 3 `-MatchingRequestPath`；
`-FinalizeJointWorkbench`只消费设计run已冻结的父plan、matching request及实际源／场，不回读活动默认。
它会建立／重开IOB和做场审计，**不执行Fly**。完整输入参数以该入口为准。

完整MP／IP／MR父plan可派生IP／MR局部范围；同一完整IP接口同时发布guide_inlet与extraction_exit。
MR-local几何、原IP→MR直接位姿和唯一clock保持，不按锚点反算放置。真实115429准备已完成81粒子源的
IOB保存／独立重开及接口场审计；审计完成不等于物理匹配或边缘场截断资格。

## 已准备IP→MR联合飞行

[prepared_joint入口](../workflows/prepared_joint/execute.ps1)消费明确的准备包和观测合同：
`-PreparedJointWorkbenchRunPath "<prepared-run>" -ContractPath "<contract.json>"`。
同入口`-AnalyzeRunPath`只从已封存原生日志建立新分析run，不重飞、不复制PA或改写旧run。
显式前驱恢复以固定完整批为单位，只执行缺失批，来源记录和借用控制文件继续绑定原owner。

[oa_mr入口](../workflows/oa_mr/execute.ps1)要求冻结`-CompositionPlanPath`及可选`-LocalScopePath`；
当前支持唯一OA轴向出口→MR入口及相对identity rotation，MR可在父装配共同平移／旋转。
原085317工况100终态闭合、98检测命中、2电极碰撞及成功封存；后续当前父plan／真实1.5 mm接口接线
已有纯准备对照，不能拿旧工况替代本次接线的原生Fly、GUI或任意相对姿态资格。
173057真实准备发现旧候选仍把MR声明为单个入口框；当前提供者已是完整分析器。
新候选从同一冻结提供者重编，只更新MR的variant及20电极清单；recipe、端口、直接位姿、1.5 mm间距、
17科学字段、原FLY2、工作点Lua、IOB pose及场记录保持一致。源收据显式引用原producer，不能以scratch副本路径冒充归属。
173601已自然成功并发布：100唯一终态、98检测、2电极碰撞、无timeout；实际10＋90两批，复用原静态场，不Refine、不复制PA。
原summary的复用批数−1是用初始一批计划减实际两批造成的统计错误，原记录保留；现按最终批计划计数。
新checkpoint使用永久批计划路径，前驱输入由manifest显式角色定位；公共完整单元恢复接受success前驱，用于不重飞的分析／发布。
71项公共／MR／owner回归通过；183641和184345两代公开恢复均为0执行／2复用、100唯一终态、98检测／2碰撞。
184345的恢复plan永久路径在执行alias释放后仍存在，新增2项永久路径／计数回归通过；不重建IOB、不Fly、不Refine。

IP→MR的093701工况保留100母群／97交接，23检测、74下游损失和3上游未交接；
该轮原生曾有载体隐式Refine，不能称为零Refine。修复预载入后，192240复用115429准备和原81交接群成功：
100母群中20检测、61下游损失、19上游未交接；无自动Refine，原ID／clock及终态发布闭合。
97群和81群是不同冻结来源，不互换资格。幸存者峰宽不能代表整束性能。
当前分段祖先复核25项通过、28份小记录身份一致：084802真实八极杆100机械出口→095324 IP→115429准备→192240 MR，
100→81→20检测／61下游损失／19上游未交接的原ID集合互斥闭合；源表、母群、ordinal、clock及epoch跨准备／飞行保持。
完整父plan与显式IP／MR局部范围逐字节一致，绝对时间精确相等，初态6D仅有既有序列化口径内的末位差。
这关闭声明的分段功能、身份与时钟验收，无需重复N100；原IP门限failed保留。
交接面明确为`recorded_stop_plane_not_physical_port`，不能据此声称多极杆边缘场或真实物理孔面之间连续场／轨迹等价。

## 真实多极杆→IP状态交接

[multipole_ip入口](../workflows/multipole_ip/execute.ps1)只准备真实出口到接收方的状态交接，
schema 2请求显式引用来源／接收manifest、冻结父plan与可选local。保留原6D、物种、出生／到达时钟及母群；
接收方设计与驱动继续归IP，不以旧出口分布或冷却前端代替真实多极杆源。

100 Da原工况213053：100终态完整，74进入HP、0捕获、0提取，接受检查未通过，无出口群所以未执行MR。
不能把`solver_stop`或径向边界直接命名为实物撞壁，具体机制与联合边缘场仍未获物理资格。
独立524 Da工况095324完成100原ID，81捕获／转移／提取，19未提取；原捕获／提取性能门限仍未通过。
103822及后继192240使用其全部81个真实出口闭合MR交接，保留IP负结果，不重定义母群或改标签为100 Da成功。

## 依赖冻结与门禁

[运行依赖清单](../config/runtime_dependencies.json)和[现有冻结器](../runtime/dependencies.ps1)
按明确owner／consumer冻结实际代码与资源；上游只核验实际消费记录。阶段恢复、终态发布及资产归属沿
已有公共机制，不复制缓存协议、恢复状态机或万能runner。跨父目录执行必须显式部署到同一公共调度账本。

前一阶段的完整L1为`migration_l1_shared_observation_final_20261026_r02.log`，
`CHANGED_GATE=PASS`、Python 3.11、980 changed paths，公共及全部适用项目和integration阶段退出0。
它覆盖公共观察／清理和冻结闭包修复，早于后继`held_off`省略，不能充当该新分支的最终整轮结果。
此前夹具／cwd失败日志保留，修复与通过记录不覆盖原失败。

公共ancestry重构已在上述L1覆盖。主机准入与预算采样共用Toolhelp父表，
目标完整性只受本运行的可能后代影响；无关protected进程不再污染目标结果，未知中间父节点仍保留后代候选。
7项focused回归16.611 s通过，包含真实父子进程、PID身份及未知节点边界；不据此宣称整轮L1通过。
COMSOL持续预算与critical保护已接线，在途042142仍使用其冻结入口。
最终11项focused回归68.384 s通过；实际惰性父子进程验证普通越限自然完成、瞬时危险恢复、持续危险仅停本次进程、
无关sentinel存活及计量故障不遮蔽科学失败，2项25.890 s通过。受限权限下停止测试进程失败的负结果保留，
上述成功来自受支持的Windows执行上下文，不等于商业COMSOL原生验收。
三处实际冻结消费者的预算脚本依赖已补齐，沿原复制机制运行。新一轮L1早期因3处新增测试缺显式cwd失败，
修复后的focused及实际开发标准检查已通过；整轮已按`migration_l1_shared_observation_final_20261026_r02.log`重跑。
独立审查发现的服务器差集归属缺口已修复：4条收尾复用已观测PID／创建身份和公共父子关系，名称只筛选角色；
critical删除重复清理，旧差集函数及专属测试退役。独立复核通过；公共COMSOL完整41项201.973 s通过，
包含真实惰性owned／无关同角色候选、旧创建身份、orphan及清理观测故障；失败分类、实际开发标准和语法检查通过。
真实CPT的只读公共采样已确认10个归属进程、原服务器在内、未知父子关系为空；不等于给冻结owner热装新保护器。
该轮完整integration阶段2061.634 s退出0，其他适用阶段亦退出0，中央owner已发布全轮PASS。
后继`held_off`七模块首轮183项1244.972 s出现3 failure／1 error，均为旧负例／预算／惰性field-stage夹具仍假设必有pulse；
修复后preflight及真实owner的held-off工作台／Fly合同共10项41.764 s通过，Ruff、开发标准、PS解析通过。
focused结果不拼成首轮183项全通过；后继干净整轮结果见下一段。
之后`held_off_full_integration_20261026.log`整轮自然完成：567项1333.859 s通过，Ruff与公共阶段退出0。
owner检查发现进程已退出，未执行停止；该PASS覆盖held-off实现，早于080512暴露的schema消费者修复。
修复后扩展的实际脱仓回归首轮因fixture相对路径失败，改用公共record_path后1项6.135 s通过；
实际N2／N3原快照失败与修复快照成功的四组诊断闭合，未访问科学PA／MPH。
完整L2日志`held_off_full_l2_after_schema_closure_20261026.log`已终止并返回失败：30阶段中28通过，
MR两项旧夹具、四极杆一项局部变量名断言失败；integration 567项通过。
三项夹具已修复，focused三项及Ruff通过；后继完整L2结果见下文，原失败记录保留。

公共事件配对、总体二阶矩及电压数学已替换实际消费者。事件模块保留原ID／事件顺序，
46项公共及消费者测试通过，另10项冻结依赖／冷却准备测试通过；四个实际冻结消费者脱仓导入通过，
缺少公共模块时均拒绝，不回读活动仓库。总体二阶矩的112项公共／IP／MR回归及17项集成依赖／分析回归通过，
保持总体分母、空样本与常量样本语义；部分浮点末位变化沿原容差判断，不声称全部逐字节相等。
波形数学沿已有公共Lua模块提供矩形门及三次过渡，IP驱动由调用方显式注入冻结模块，
MR投影及审计消费同一选定来源的驱动与数学记录。109项实际消费者回归、175,355个二进制浮点对照及
实际冻结接口投影通过；这些focused证据不等于后继整轮门禁或真实跨后端数值资格。

独立缓存退役主题已提交并普通推送`caf05adf`：项目`simion_pa_basis`沿同一精确owner批准入口，
pin、消费者及库存检查保持。16项合同测试通过，精确三个文件的干净checkout完整L1通过。
该提交不包含尚未闭合的N2修复，也不表示总迁移完成。
公共单键恢复主题`686dadcf`亦已完成干净五文件完整L1、22项主树回归和真实恢复后普通推送。
主树`migration_l1_after_strict_frontend_20261026.log`已自然失败：multipole阶段一项惰性worker测试在25秒外层期限
触发TimeoutExpired，integration 568项（3126.024 s）中三项旧轮次field-stage夹具JSON解析错误。
该轮启动早于后继记账修正，不能作为当前源码的最终整轮证明。当前完整field-stage 38项已通过，仍须稳定整轮复验。
后继`migration_l1_frozen_source_20261026.log`已自然完成`CHANGED_GATE=PASS`，Python 3.11、991 changed paths；
integration 573项1493.046秒通过，上轮三个JSON解析错误对应的恢复用例均通过，其他适用阶段亦通过。
该稳定整轮早于后继反射器API及共同场来源接线修复；前者38项回归及原生隔离通过，后者42项回归通过。后继`migration_l2_after_source_topology_20261026.log`已自然退出0，
`REPOSITORY_INTEGRATION_GATE=PASS PYTHON=3.11`，覆盖来源接线、反射器API及节点／连续金属拓扑修复。
测试等待调整60秒，不改变生产预算或放宽CPU、并发、内存判据。资源模块56项首次复验中55项通过，
另一个受限权限终止惰性测试进程失败；正确权限下两项针对性复验25.698 s通过，原负日志保留。
上述针对性结果不拼成原整轮通过。

旧integration arm编排3份生产文件、consumer和13项专属测试已退役，不保留旧CLI转发。
保留9项源测试与新pulse联合32项25.017 s通过；完整仪器的项目`run_fixed_particle_retrace.m`仍活动。
源／时钟、Cartesian reader、CPT策略及实际消费者保留，未删除历史模型或以窄OA CPT替代完整仪器资格。
另已删除仅供测试调用的完成校验函数，数量拒绝直接覆盖真实collector；脉冲runtime 15项9.098 s通过。

同基线CLOC 2.10最新快照为2026-10-26 11:59:14 UTC：`6f37fbdc23ed8f9ba6dbfa33dc011222d7d38bff → WORKTREE`，
总代码424,137→374,190（−49,947）、生产284,736→240,492（−44,244）、测试139,401→133,698（−5,703），
未分类0，脚本1,256→1,208（−48）。该快照覆盖严格栅格、容量补额、失败事务记账、公共机制、来源接线及占据拓扑修复；完整语言、
脚本数及过滤口径在`final_scope_after_ci_path_cloc_20261026.log`。报告器显式使用固定官方CLOC 2.10
脚本处理长路径，不使用其他计数口径。后继源码若变更，交付前须用公共报告器刷新，
行数、脚本数下降不能代替正确性、原生或GUI／CAD验收。
独立提交`6f37fbdc → caf05adf`采用两个已提交快照经同一公共CLOC 2.10入口核验，
总计+3、生产+1、测试+2，文件与脚本数不变。
第三个独立提交`bd9f52ef`已通过干净两文件L1后普通推送：quiet计数出现stderr时保留诊断并失败，
即使工具exit0及JSON完整也不再接受漏计。主树八项回归（含实际官方PL）通过；干净树七项中一项本机工具可用性检查skip。
三个已推送修复的稳定快照`6f37fbdc → bd9f52ef`为总计+163、生产+21、测试+142，完整语言／过滤口径见
`committed_public_fixes_cloc_20261026.log`；该范围不包括尚未提交的主体迁移和几何修复，不能与整个WORKTREE混算。
深层验证工作树曾因计数工具长路径读取失败给出虚假的额外下降；该结果不用于规模结论，
已提交快照的短路径结果与实际三文件改动一致，不能把漏计解释为真实删除。

## 实施与退出条件

共同静态场已接入已完成COMSOL导出复用：显式来源的BVP、原采样库存、CSV及native facts均匹配时，
直接借用原owner输出，不读取／哈希MPH、不生成MATLAB任务，也不启动COMSOL。采样变化或导出未完成时
仍走现有保存模型重开路径；已声明的损坏输出不静默回退。原facts保持原路径，summary分别记录导出复用与COMSOL原生执行。
011244真实115点小输入预检通过，22项静态owner回归65.724秒通过；182314已实际完成strict PA构建、115点采样及诊断，
summary明确COMSOL导出复用、COMSOL原生执行false。新PA成员与旧成员SHA不同，仅有限脉冲的SIMION阶段失效；
原CPT模型及1600状态导出仍可复用，原100粒子／时钟不变；后继脉冲及导出恢复由下述两轮实际运行闭合。
这不替代独立的saved-CPT原生重开／导出验收。

184444已完成strict有限脉冲：原CPT解和导出均复用，仅补SIMION基线与默认回放；默认回放passed、differences为空。
本轮共同问题诊断为COMSOL 1600状态可用、SIMION 500可用／1100缺失，最大位置差约6.7608 mm（X）及5.90176 mm（Z），
不再沿用旧609／991数据，也不声称数值等价或性能资格。
190255已实际重开原保存CPT模型并仅导出：100粒子×16时刻=1600状态严格比较差异0，NoCompute／NoGUI／NoMPHcopy，
原模型和母群未改。185405只在商业软件启动前因冻结目录的Python定位失败，已封存；后继通过公共Python／共享账本参数修复并完成。

1. 同一共同场有限脉冲链已取得原生CPT、诊断、仅后处理恢复及保存CPT实际重开导出证据；
   不重复SIMION、CPT或ES，不把功能完成及跨后端差异误写为数值／物理资格。
2. 新COMSOL公共观察接线的适用原生验证及本轮L1各阶段已闭合；保留原wrapper权限失败和5阶段复验记录。
   最终整合L2仍待执行，不因常规耗时、低CPU或静默强停健康求解。
3. 按用户更新后的范围，以已完成N2原生独立场／驱动、N100飞行和默认回放验收多实例功能；不再运行N3额外大模型。
4. 完整oaTOF组件已完成GeometryOnly保存／独立重开、18项M Unit及同源headless STEP；
   含上游部件的适用装配CAD及SolidWorks／GUI仍开放，GUI继续按用户暂缓决定处理。
5. 逐项复核其余真实链的父配方、分段与跨求解器边界；保留100 Da／524 Da及零检测等负结果，不擅自扩成性能优化。
6. 完成替换后删除剩余低价值重复实现，更新同基线CLOC和实际维护点，完成稳定门禁、最终审查与相称提交。
   全部必需工作闭合前不完成总goal；历史门禁、纯准备、小探针或成功缓存命中均不能代替这些退出条件。
