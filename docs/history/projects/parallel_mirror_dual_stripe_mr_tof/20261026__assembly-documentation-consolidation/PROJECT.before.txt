# 开放路径平行镜双条带 MR-TOF 项目状态

返回[项目导航](../README.md)。推导见[理论索引](theory/index.md)，机械交付见[CAD](CAD.md)。
本页只维护当前决策、有效证据和未完成动作；具名运行的冻结输入才是参数权威。
已完成矩阵、恢复与退役记录归[边界输入隔离里程碑](history/20261015__boundary-input-isolation.md)；更早过程由项目README导航。

分析模块统一使用公共分块文件身份函数，保留各自既有摘要大小写。
IP–P1诊断表已从三次磁盘读取收敛为一次原始字节快照：解析、文件身份及逐行证据消费同一载荷，
原BOM／换行字节、行号、摘要大小写和科学筛选保持；三项定向回归通过，不新增第二套读取框架。
交接、实测源物化与分析复用[公共canonical状态loader](../../../common/contracts/component_particle_state.py)
的typed行与报告，删除校验后重读及项目内类型转换。注册状态逐字段精确比较允许实数字段的等值词法，
标识字符串仍严格匹配；原始输入副本及manifest字节身份校验保持不变。
质心控制器的发布后分析也直接使用同一typed loader，删除先校验再重读及对源模块私有CSV读取函数的依赖；
实际质心分析回归通过，保留缺失PA时仅消费冻结元数据的行为。
接口、联合飞行准备、工作点与孔口诊断直接使用[公共小文件冻结API](../../../common/contracts/frozen_inputs.py)，
原项目私有复制实现和转发依赖已删除；依赖选择、运行伴随文件命名及孔口source／frozen记录仍由相应消费者维护。
IP与MR实际准备消费回归及冻结闭包检查已通过，验证范围为无商业求解器的输入准备与身份检查。
实测源物化复用同次已读状态、已绑定时钟文件与验证后的来源身份，仅执行一次粒子投影；
独立centroid／slice消费仍核验自己的输入，物理状态、母群、时钟及收据形状不变。
已准备联合飞行从冻结JSON解析Q及最大步长，超时复用原MR公式；参考materialization在准备边界冻结，
后继trial不再访问原MR运行或从Lua提取这三个数值，物理reference Lua保留一份。
合同身份、回归与原生验收边界见[直属集成状态](../../../integrations/docs/INTEGRATION.md#已准备ipmr联合飞行)。
单中心步长比较复用同次已验证 manifest 输出记录，不再为 summary、trial、observation 和原始飞行日志
各重复全文哈希；batch/trial 的源区间解析直接调用源合同模块，删除兼容转发函数。
IP 替换装配从历史冻结源派生当前 seed 时，只剔除九个退役解析场字段；保留原生电压/几何参数，
不反写来源证据。coarse-raw producer 仍用于 native response bank 的粗父几何重建；PA family 的
独立私有运行表示用于防止发布资产被 SIMION 回写。

## 统一组装迁移任务

统一组装迁移已进入实施，依赖[统一组装计划M1/M3/M4](../../../docs/ROADMAP.md#统一组装迁移计划)；
职责与在途保护见[组装规范](../../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md#统一组装目标)。已准备IP→MR
联合飞行及OA／IP准备的实际执行主体、调用及新run身份已切换至
[直属工作流](../../../integrations/docs/INTEGRATION.md#oaip接口准备与绑定)；旧准备公开入口与PreparedJoint分支已删除。
普通OA飞行主体也已迁至[直属OA→MR入口](../../../integrations/workflows/oa_mr/execute.ps1)，旧trial入口已删除。

### OA→MR 运行组装合同

直属入口、staged workpoint、cohort screening及自动候选链均要求作者显式给出`CompositionPlanPath`；
可选`LocalScopePath`只是在同一完整冻结父 plan 上派生局部范围，不能以裁剪 plan 代替父 plan。当前两区配方为
[`oa_mr_two_zone_gap30_plan.json`](../../../integrations/config/recipes/oa_mr_two_zone_gap30_plan.json)：它连接 OA 的
`axial_exit` 与 MR 的`accelerator_entry`。运行冻结这两个输入后，源释放仍是 OA 本地参数，位置由该连接的直接
位姿投影；不再从`focus_y`或历史 placement 推导第二个位姿。

当前 renderer 通过公共`relative_transform`从两个直接位姿投影OA到MR局部，只要求该相对旋转为identity；
MR在父装配中可以整体平移或旋转。MR几何、PA网格、源、工作台和科学诊断保持提供者局部frame，
父装配映射仍由完整冻结plan中的MR实例直接位姿唯一表达，不旋转或复制已有PA。
额外被选组件、未知端口或接口漂移明确拒绝。冻结计划的端口截面、电极身份会与实际 OA/MR provider 编译结果核对，
OA PA IOB origin由OA到MR的相对平移减其已编译`local_to_pa_translation`得到。
实际提供者／端面和源出口reference回归已覆盖共同平移、共同旋转及不支持的真实相对旋转拒绝；
完整物化的字节对照仍待验证。它不构成新版完整 PA 求解、原生飞行或 GUI
资格，后者仍须由相同冻结输入的实际运行取得。
实际准备路径现将同一已解析`direct_pose`传入几何出口参考；以085317冻结静态场重建的1.5 mm端面间隙配方已通过纯准备，源FLY2、工作点Lua和IOB位姿与原运行相同，但不验证上述30 mm配方或新版原生飞行。
IP设计解析、注册后几何和装配探测器渲染已归直属准备工作流，旧MR函数已删除；本项目仅保留实际原生
场消费者所需的CSG及屏蔽操作，迁移对照和脱仓依赖验证见上述直属集成状态。
共享测试夹具现从IP提供者直接导入`native_projection`，不再依赖MR模块的退役转发；
24项几何／提供者回归通过，包括原GEM字节对照。此修复不恢复生产兼容接口或改变冻结物理输入。
无生产调用的`run_recover_completed_bunch_flight.ps1`已退役删除；完成飞行后的新分析归直属工作流的正常阶段，
不保留旧owner专用恢复状态机或复制旧分析合同。历史运行与GUI证据保持只读。
`mrtof_batch_continuation.py`已由直属OA→MR入口消费，作为公共完整批续算API的科学适配器；直属`prepared_joint`
也以公共whole-unit计划消费显式冻结的前驱manifest。它只复用manifest绑定、原生完整终态的固定源行批次；不完整批整批重跑，
不扫描祖先、复制PA／日志或把新run表述为执行了借用的Fly。
复用批的log、receipt和FLY2作为新run的显式冻结输入登记，因此B→C只沿B的manifest绑定继续复用，不重新规划批次或扫描A。
同一绑定还登记固定的dispatch request、resource profiles和dispatch plan；恢复只消费这些记录的路径与身份，缺任一记录即失败。
后续接入须遵循[昂贵阶段复用与中断恢复](../../../docs/DEVELOPMENT_STANDARDS.md#昂贵阶段复用与中断恢复)
及[公共SIMION续算API](../../../common/simion/README.md#调度与恢复)，由直属runner冻结父run及完整批证据，
而不新增MR专用计划权威。
MR几何、匹配与执行科学合同、场提供者及父工作点控制器仍归本项目。新owner的OA终态发布复验及
既有97粒子IP联合飞行的独立分析已闭合，见[直属验收状态](../../../integrations/docs/INTEGRATION.md#已准备ipmr联合飞行)
及[IP分析记录](../../../integrations/docs/INTEGRATION.md#oaip接口准备与绑定)；不因此恢复已暂停的IP碰撞调查或改变物理资格。

IP机械连接已改为显式作者配方，几何和实测源消费同一直接位姿；原锚点反推及内部造配方已退出。
几何与源的实例身份均从该配方连接取得，不再将IP／MR项目名当作实例名；schema 3 handoff保留同一绑定，
MR按实际提供者、端口、方向、场和时钟验收，不因此支持任意多IP或多MR拓扑。
IP matching schema 3已引用完整冻结父plan并从中派生实际范围；geometry核对所选提供者接口，
父2→3→4时选中IP／MR的四份GEM及handoff状态／母群字节不变。当前仅有无商业软件回归，
不授予新版联合求场、飞行或GUI资格；其他装配迁移边界仍见直属集成状态。
OA的IOB位姿也已收回唯一trial receipt，运行器不再二次解析；实际格式和限制见直属集成状态。
MR提供者现发布`complete_mr_analyzer`完整组件视图，从实际resolved镜组、Stripe、Prism、屏蔽与detector对象
归并20个真实电极身份，闭合镜共享原物理对象；E18机械端面保持，公共接地编号由同一提供者常量投影。
接口、镜组收敛和原几何指纹13项回归通过；三实例父装配的实际准备与共同父位姿物化两个消费者
经公共GATE重验通过。原共享toy夹具缺少完整电极及一次误写测试类名的失败记录保留，不放宽生产要求。
OA→MR及IP／prepared_joint已按实际相对位姿消费，MR几何／网格／源／诊断保持提供者局部坐标；
IP三完整模块39项及最终frame拒绝单节点1项均经公共GATE通过。当前CSG保留固定native相对轴置换限制，
共同平移和精确共同旋转有实际GEM／状态／时钟对照，任意角父姿态不在本轮通过范围。
仍待完成实际驱动绑定与相称原生验收；机械端面或完整电极表不冒充全部接口迁移。本项目保留Prism、镜组、Stripe、
系统布局约束、匹配与工作点闭合、整机验收；现有IP装配中的专属屏蔽／轮廓调整不能整体上移common。
先明确这些变化的物理权威，再由提供者或连接专用适配生成实际几何。

关闭条件是OA与IP分别在冻结输入下完成装配、场投影及相称行为对照，逐项标明相交／净距检查范围，
调用、注册和产物身份同步切换后再退出旧生产副本。IP分支保留实测出口六维state handoff、母群损失和
绝对时钟；`pulse_held_rf_zero`不升级成全程动态RF／碰撞耦合。局部多极杆→OA继续由现有integration
负责，不为迁移增加MR私有传输入口；既有MR物理限制与资格均保持。

IP measured joint flight在准备阶段即校验已声明的峰形合同：必须绑定实际来源的共同提取脉冲、
clock及timing记录；OA的共同零出生时间合同不能用于IP峰形分析。20261022_215610新owner运行
已完成97颗原生终态与批次合并，但自动诊断因沿用旧OA峰形合同失败，原失败证据保持封存。
这属于分析声明缺口，不能通过伪造零脉冲、逐粒子扣除交接时刻或重新飞行掩盖；同一 `mrtof_batch_flight analyze-joint` 接受显式 `--analysis-contract`：只许改变原冻结trajectory的
`peak_analysis`，其余科学、数值和记录字段逐值不变；收据登记post-hoc合同与原合同身份。
它消费原preparation、完整merge及原生日志，不重写源run或重复Fly；上述独立分析已完成发布。
新524 Da多极杆→IP→MR的`20261023_103822`已完成并封存ready／success：100母群由19个上游未交接、
61个下游损失及20个检测组成，下游timeout为0；9＋72两批自然exit 0，完整manifest的181项输出核验通过。
该工况的功能状态／时钟链已闭合，IP原0.81捕获／提取结果的性能门限failed保持不变；
不授予整体性能、GUI或Formal资格。详细证据见[真实状态交接](../../../integrations/docs/INTEGRATION.md#真实多极杆ip状态交接)。
MR 分析中的原生完成事实统一解析已实测的 SIMION 2020 `Fly completed` 行；它只提供 splat 数与可选耗时，
不替代各分析器对 TRACE、粒子 ID、绝对时钟或科学终态的既有判据，也不新增物理资格。

## 当前决策与完成边界

电压映射的只读审查发现非单位`nonaccelerator_scale`定义尚不一致：Python静态场匹配将20电极向量整体缩放，
Lua运行映射只缩放镜组／Stripe，P1／P2使用实际电压。活动候选scale=1不受这一差异影响，
但不能据此接受非1工况；这不是新原生运行结论。下一步先明确该参数的科学定义，再统一实际电压投影。
Python已复用同次构造的20电极向量，保留冻结场authority覆盖。
原生通道分组只从本run冻结的detached bank manifest中
`identity.basis_namespace.response_recipe.response_recipes`派生，不回读活动trajectory或上游旧family身份。
materialize生成同目录的`native_corridor_priority_contract.lua`并绑定输入／产物身份；仓库静态模板已删除。
mapper明确提供`physical_voltages`及`corridor_voltages`两个函数，不保留旧callable API。
native消费两者，static只消费物理电压、只发布四角色，不生成或校验无用途的八组；measured分支仍不加载mapper。
原生可调场的GUI调压与变化检测保留，冻结标量场继续拒绝与场authority不同的电压，原WB overlap probes不变。
完整物化模块66项回归、三个普通Lua回归及四个完整Python模块通过，后者共31项、其中1项原生opt-in跳过。
这些是无供应商验证，不授予新原生飞行、GUI或Formal资格。上述非单位scale定义差异仍待关闭。

2026-10-21 用户将工作转向同源八极导引接 OA，IP 碰撞调查暂停，不启动修正后的 IP N=100 或透镜优化。
静态查询已排除已知 ID3 点的坐标映射错误：往返误差约 7.1e−15 mm，所在单元 8 角中 6 角为金属，
原生 `find_at` 为 false；小型擦边点的 0.1／0.05 mm 网格为 false、0.02 mm 为 true，支持边界网格敏感性。
它不证明全部穿越或 vendor 碰撞算法失效。首个 OFF 飞行在初始化因 PA 锁定命令失败并退出，其余 9 臂未启动，
因此没有完成 Fly 碰撞矩阵。证据见
[静态核查与未完成飞行记录](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261021_084457__analysis__python__collision-grid-static-closure/results/report.md)。
候选首接触修正仍为未完成原生验证的 WORKTREE，不替换现有默认资产。两次失败探针的私有大 PA 副本已按公共
机制退役，保留小型场、IOB、查询及全部失败证据，原源和 GUI 资产未改动。OA 接入工作归既有多极杆→OA
集成流程，保留二区／三区选择，不另建 MR 专用传输运行器。

双透镜的分段相空间机制与加大间距N100验证已完成，理论、校准、负结果及数值边界见
[双透镜局部验证里程碑](history/20261021__doublet-phase-space-and-wide-spacing-validation.md)。
原D与旧双透镜保留；新大间距配置不替换默认方案。此前内部调压、对称几何、旧双透镜及五方案回放见
[三路线里程碑](history/20261020__d-routes-theory-local-validation-and-replay.md)。
这里只研究IP及第一Prism局部场，未恢复大型联合模拟、未操作GUI，OA／IP可选接口不变。

### 双透镜的取舍与当前结论

旧双透镜的x角收益被第二镜大幅抵消：完整96群在Q1后σθx约0.395991°，Q2后回到约0.628665°。
到P1，同92群相对零偏的x／y角宽下降1.44%／17.71%，y束宽增加12.45%。
该位置的空间—角度协方差决定准直收益；增加电压或镜距不保证两轴同时改善。
实际离轴场已显示尾部偏离轴上线性模型，不能只用轴上梯度和平均束宽选择透镜。

| P1原生到达群 | 原生计数／100母群 | σθx／σθy（°） | σy（mm） |
|---|---:|---|---:|
| 旧细网格零偏，同92群 | 92 | 0.543005／0.238967 | 0.448543 |
| 旧细网格偏置，同92群 | 92 | 0.535202／0.196635 | 0.504406 |
| 新大间距偏置，完整93群 | 93 | 0.511554／0.740764 | 1.144974 |

新配置Q1／Q2中心z=−18／−30mm、长度5／3mm、电压+85／−95V，内接半径1.4mm、圆杆半径0.2mm。
它同时改变位置和电压，只是整体候选对照。所有行均为人口SD，θx／θy为全局xz／yz投影角。
完整100母群／96实测六维源和绝对时钟不变；新配置恢复ID2，旧全部92颗均保留。
固定相同92颗与旧偏置比较，x角下降6.318%，y角增加278.669%，y束宽增加128.206%，明确不满足三目标。
[同群比较与相空间图](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261021_013853__analysis__python__wide-doublet-final-comparison/results/report.md)
保留全部ID、实际场／模型残差和时间能量；同92群P1 σt为12.486172ns，旧偏置为12.074818ns。

主要失配来自存活的ID11：首镜y散焦经较长漂移放大，它到第二镜入口已绕到y正侧杆外侧，
不再处于轴模型假设的中央聚焦区；到P1约9.541°，贡献完整群约95.25%的y角方差。
它不能被删除后用剩余群宣布改善。中央68%／90%与IQR也不一致，不概括为核心均改善。
减小首镜散焦、缩短漂移或重新设计孔径／杆轮廓仍是有物理依据的方向，但尚无可推荐的三目标参数。

### 数值、诊断与复现边界

实际新场与半时间步控制见
[原生局部结果](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261021_012415__sim__simion__wide-doublet-85-m95-n100/summary.json)。
[0.1,0.1,0.1]mm、Q8、0.001／0.0005μs两步长均93到达，全部96终态reason及损失ID一致；
138面同ID最大时间差约0.006073ns、x差0.00012423mm、y差0.00229062mm。
上游24／64／80／99及局部33／34／67全部保留，局部终止位于下游x约+2mm通道。
该稳定性不能替代电场网格、连续圆杆碰撞、统计或MR分辨率资格；既有网格敏感性仍有效。
连续圆杆核查还发现存活ID3的实际保存点进入Q2杆内约0.029mm，最近PA节点为电极，半步长仍存在。
所以93只是原生到达计数，不代表已验证的物理收集率；默认回放一致也会复现这项缺陷。
[后继碰撞资格更正](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261021_014916__analysis__python__wide-doublet-collision-qualification/results/report.md)
明确物理收集率未获资格，不改写已封存原始计数或旧分析。
[连续几何、原始行与实际节点证据](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261021_014526__analysis__python__wide-doublet-loss-node-evidence__r02/results/report.md)
分开保存原生状态、严格CSG成员与含端帽SDF，具体碰撞／离散归因仍未闭合。
自动诊断包括穿面相空间、时间／能量、同时刻云分布、全程空间演化及全部损失母群。

[新配置独立加载包](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261021_014200__build__simion__wide-doublet-private-replay/summary.json)
的`simion/case_01/local.iob`用于复现这项负结果；旧五方案包保持。
手动Fly前完整复制case到独立可写目录，再加载IOB；不要原位改写封存模板。
[全新进程默认Fly证明](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261021_014119__test__simion__wide-doublet-default-private-replay/results/exact_state_comparison.json)
在无Program／Q／粒子覆盖条件下，events／samples共195,213行全字段零差异、两个CSV字节完全相同。
这证明默认文件回放一致，不代替用户GUI人工验收，也不使负结果成为推荐参数。

## B/C/D局部研究的有效边界

此前B／C／D轮廓、实际局部时间焦点、孔口筛选及独立默认回放已完成，详见
[局部聚焦与回放里程碑](history/20261020__ip-bcd-local-focus-and-replay.md)。
D保留较高收集率，但未同时占优于两轴角宽和最小时宽；当前三路线以D为固定基线，不能混用不同轮廓的出口。
原研究的厂家未知尺寸、连续孔口碰撞偏差及局部网格／步长资格边界继续有效，不能由新透镜单轴对照覆盖。
旧183935独立B／C／D细场用户包保持；默认文件回放证明来自194300记录，不作为本轮五方案的新回放证明。
171512的B／C原PA及surface已退役，不能把这些旧路径当作仍存在的donor；183935保留对应场和工作台，继续保护。
190305失败私有回放的六份副本此前已公共退役；本次原owner复核全部保留证据后完成容量收尾，剩余80文件102,825,043 B。
公共收尾明确记录旧账相对退役前完整库存少2,000 B，并按实际剩余量修正登记；没有新删PA、改原科学文件或改写失败终态。
手动Fly应先完整复制所选case到独立可写目录，避免修改封存模板。

## 加速器接口与整机暂停边界

加速器接口可选`orthogonal_accelerator`或`dual_pressure_rectilinear_ion_processor`，默认OA保留；入口见[操作说明](../simion/README.md#加速器选择与接口准备)。
IP独立器件GUI已由用户验收；下游采用冻结出口六维状态交接，不是同一Fly内连续积分HP捕获／冷却到MR。
实测源来自152536独立N100：100母群、97出口，上游损失ID24/64/80；原ID、时钟及速度保持，不以缩放源补匹配。
能量只报告差异、不判定达标；默认自动输出各时刻空间位置、Prism相空间及全部损失原始证据。

零交叉实测源的整机重新闭合已按用户2026-10-20指示停止，先进行理论分析与小型模型验证；
父研究为`20261019_140157__analysis__python__ip-zero-joint-study`，不自动恢复大型响应求解或联合N100。
来源为IP的`20261019_132354__sim__simion__rf-zero-crossing-n100`：100母群、97出口，保留24／64／80上游损失。
设计140454显式保持来源4480.043790844389V抬升、LP61.5mm及全部源／几何／数值配置，
不重新调IP电压或缩放出口速度；新屏蔽狭缝需要独立场与响应，不复用旧算子闭合。
141617五层场虽收到原生Refine完成状态，但完整载荷检查拒绝中央和正／负镜的NaN电势；父场与IP细窗全节点有限。
中央五个实际Dirichlet外面均有限；约7万节点的四臂小域对照均未复现，不能归因于贴节点的1mm狭缝。
证据见父研究的`results/rejected_field_payload_audit.json`、`rejected_central_boundary_audit.json`及`small_field_reproduction_summary.json`。
新185918数值对照仅改官方`skipped_point=false`，保持几何、电压、五层网格、fractional及1e−5V停止条件。
五层场共4,027,608,345节点全量有限，完整manifest校验通过；父研究`results/complete_native_numerical_control_result.json`
绑定实际producer的`results/pa_payload_validation.json`，另保留中央Refine前／后全量检查。
NaN在本次完整域对照中未再现，不授予几何／场离散收敛资格。
准备接口显式记录`skipped_point`策略变化，并核对新场各层数值身份；convergence与其他物理／数值字段仍严格保持。
实际工作台准备在185918完整场加载时发现：完整fresh生产器误写未消费、未封存且不存在的source_binding提示，尚未发生新Fly。
新生产器已去除该提示；对本次已启动且冻结的完整fresh运行，仅在已封存request／plan证明无真实来源依赖时恢复读取，
不改写已发布plan、PA或manifest；有文件／seal或派生、响应、组合来源仍严格核验。新运行不再产生该恢复条件。
真实185918 binding加载及19阶段L1已通过；随后r04准备暴露源驱动控制仅查outputs的遗漏：
三个控制文件实际已封存在inputs，16个PA在outputs。审计改为按完整路径合并两类封存记录并拒绝身份冲突，
控制仍全量身份校验后冻结，PA保留原封存身份／当前尺寸和只读保护，不取其他batch的同名文件。
实际062030工作台准备已通过；062400质心在P191工况接触P1屏蔽槽y=−35mm，未获得P2／clean拓扑。
后续新P1响应先因主机重启、再因用户缩小范围而中断；两次均如实封存interrupted并沿公共入口
退役未发布的部分PA，保留冻结输入和全部轻证据。有效185918场、源和旧可加载工作台保留。
这些准备尚不构成新闭合、透过率或分辨率结果。共同提取脉冲峰分析的声明与自动输出见SIMION操作说明。

小型机制研究`20261020_083400__analysis__python__ip-reduced-phase-space`沿公共资源门禁消费全部97出口，
不重采样、缩放或筛掉尾部；表中并列总体与样本SD，以下使用总体SD。
理想单次90°Prism仅在相同入口／出口电势下重新分配yz动能，平均方向调至约2.008°后，
σθy由0.189964°变为0.191738°，σEy约1.03140eV；该模型保留能量—角度协方差及全部母ID，
不提供实际P1／预反射／P2电压建议、空间传输或分辨率。
后续三点对照固定同97个实际出口，理想偏压为0／0.5／1倍参考值153.319276V：
σθy为0.189964／0.190585／0.191738°，最大增宽0.934%；vx及相对yz合速度的真正横向倾角不变，
xz投影角宽仅变约0.065%。此范围支持理想Prism主要改变平均方向，不能据此忽略实际有限场的透镜作用。
历史132248的P2入口z=−26mm／出口z=+26mm，同61个通过ID的σθx由0.008099增至0.066495°，
σθy由0.167671降至0.126720°；64个入口中的16／37／81未通过，全部100母群结局另存。
该段包含Prism、屏蔽边缘与背景场，未隔离Prism电极单独贡献，且不是零交叉新源的真实P2验证。
[Prism对照证据](../../../../artifacts/projects/dual_pressure_rectilinear_ion_processor/runs/20261020_090200__analysis__python__prism-auxiliary-angle-study/results/prism/report_zh.md)
保留同ID配对、能量／角度协方差、发射度及英文图；不把投影角宽变化等同于冷却或完整六维发射度变化。
现有IP装配的E14下游实体唇z=+6.3mm、P1屏蔽前沿z=+5.3mm，沿−z的机械间隙为1mm；
OA支撑／屏蔽前沿为−0.5／−1.5mm，同样1mm。IP的z=0观察面位于开放屏蔽通道内，
不是OA合同中的出口一阶时间焦。名义y=−55mm处，P1离轴侧电极投影近端z=−52.828mm，
距IP观察面约52.8mm、距E14唇约59.1mm；该离轴投影不等于实际场入口或轴上金属面。
零交叉97出口的自由漂移协方差估计x／y束腰在下游14.47／16.62mm，σx可由0.10676减至0.07680mm，
y变化较弱；下游没有进一步时间压缩，σt在0／10／20／50mm约2.163／2.781／3.533／6.073ns。
这些是忽略残余／Prism边缘场的估计，不能把约15mm当成新的机械间隙或已验证放置位置。
机械1mm先保持，后续用实际6D对照IP到P1作用区的位置；若缩短目前长漂移，须同步调整屏蔽延长段，
先做小域耦合场与相空间匹配，不直接塞入原通道、不靠移动参考平面伪造聚焦。
[位置与焦点证据](../../../../artifacts/projects/dual_pressure_rectilinear_ion_processor/runs/20261020_090200__analysis__python__prism-auxiliary-angle-study/results/scientific_report.md)
区分当前冻结装配、历史实飞、实测出口、数学漂移估计和未执行的几何候选；该次分析未移动部件或恢复整机飞行。

IP具有时间聚焦的设计自由度，不能将“当前z=0未建立时焦”说成器件没有焦点。
Stewart JASMS 2024 printed p77图7在50mm下游MCP处，通过HV1/HV2及10keV/q加速栈实现第一时间焦点；
524Da、RF1000Vpp的图估读实测FWHM约2.9ns，扣除1.25ns探测器响应后约2.6ns。
本项目零交叉出口2.16334ns是人口SD；高斯代理FWHM约5.09428ns，不可直接与上述图7比较。
以OA参考约764.216μs计，R=100000要求最终总FWHM≤3.82108ns，因此当前出口宽度不经后续压缩不能保证十万。
实际终端由t–E及位置–角度协方差共同决定；不得把相关宽度逐段独立平方相加，或把去趋势宽度冒充真实焦平面峰宽。
Stewart图8的6σ=2.4mm是沿阱轴空间宽度；所核对Stewart、Crowd Control、Grinfeld三文没有直接给出本出口定义的双向角RMS。
[原页、定义与分辨率预算](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261020_095100__analysis__python__ip-prism-distance-design/results/literature_widths/report_zh.md)
明确图估读、10keV测试装置和整机结果的边界；历史19粒子检测R≈24280不是零交叉新源的结果。

原电压的理想Berdnikov单镜近轴映射det≈0.99999938、相位进动86.668°；
投影97源的线性σx由0.106759mm变为2.453506mm，但五个实测边缘粒子的非线性回程明显偏离线性预测。
这只支持检查发射度、匹配和有限幅度像差，不能用中心稳定性或线性束宽代替实际4mm屏蔽孔接受度。
实际出口与OA的比较、逐ID表和英文诊断图保存在该研究results；原始97出口是逐粒子z=0穿越事件，
不是同时刻离子团。二维探针、有限模型范围和未完成的三维资格以该研究机器摘要为准。
二维适配直接消费185918已封存的实际几何，不用OA专属扩展解析器重新生成IP装配；
P191点缺少规定的正z向P2通过，历史P369／P2−212.5V初猜只完成到首次正侧Stripe通过，
正镜转折y／P2切线残差为+0.153572mm／+0.000764765，仍未闭合。两点实算约12.75s，
最大记录Hamiltonian残差约3.96μV。内部411次传播返回含根定位探针，不是振荡圈数或连续物理轨迹；
诊断使用公共API接受的阶段状态，原定位证据另行标注保留，不据此宣称完整返回或N100性能。

172646已按原P→S／返回相位→P及完整返回通过，S2接地；原OA实际慢转折目标340mm，运行名称y360不是参数权威。
第17候选／055实飞通过完整工作点；
S1=−26.988823505V、P1=369.183763535V、P2=−212.537230795V。
P位置／action残差为+0.083549981mm／+0.008216214eV/q；慢转折／返回相位残差为−0.020811814／+0.008540326mm，
四项最大归一化残差0.835499809，S阶段为0.208118140。原判据及源保持，累计17候选／55计划、54次实飞。
最新132248联合N100完整处理97颗交接粒子：检测19、下游损失78、超时0；母群检测率19%，已交接群19.587629%。
父研究`results/historical_ip_peak_reference`按全部19个实际检测离子及该旧源共同提取脉冲7500.135135135135μs复算：
平均TOF763.240624μs、Gaussian KDE直接FWHM15.717136ns、时间等价R=24280.525；未裁尾或扣除逐离子交接时间。
这是有限幸存样本的工程对照，不是零交叉新工况结果或Formal性能资格。
78颗中76为原生接触终止、79／95为非碰撞的返回拓扑拒绝；81份逐离子证据含上游24/64/80，全部保留。
原生P2参考事件（z33mm）仅61颗到达，角度2.016908±0.126771°，Ey标准差0.681418eV；
均为到达子群统计，不代表97颗整束。质心闭合通过，整束匹配和时间聚焦资格仍未取得。
默认生成7个实际事件／寿命决定时刻的空间图、Prism能量分配图和母群损失图。
本轮闭合、负结果、自动调度、发布与退役见[联合母群里程碑](history/20261017__ion-processor-closure-and-joint-population.md)；
此前软件恢复、输入运输和治理异常见[恢复里程碑](history/20261017__ion-processor-original-controller-recovery.md)。
最终L1与完整MR Static通过（1430项、10项跳过及三个纯Lua回归）；L2原失败与分组重验见下述里程碑。
源码门禁不替代束团性能资格。

[005908冻结目标](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261017_005908__analysis__python__ip-centroid-target-authoring/results/target_authoring/target_authority.json)
能量参考保留Ws=5.374387143eV/q、K=24.5；clean参考Ez=4359.320021、Ey=5.213248eV/q。
慢转折目标以[171041修订权威](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261017_171041__analysis__python__ip-original-mr-target-authoring/results/target_authority.json)的340mm为准。
0.01°映射0.0524898eV/q只用于质心P控制，不是N100能量验收阈值；有效慢势与实际静电势分开记账。
003000扩域场的同点及实际轨迹接口审计支持原约11.47V跳变已消除，不授予全轨迹离散收敛资格。

当前可加载IP包为[132106 joint.iob](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261018_132106__analysis__python__ip-collision-overlay-workbench/results/joint_workbench/runtime/joint.iob)。
它保留最终055电场、电极实体、电压及原四实例，追加0.05mm同CSG碰撞占据patch；五实例保存重载、
原三项及新增14项优先级探针、98点接口场审计通过，patch持久不可Refine。97颗FLY2、时钟与132248实飞相同，Q8／最大步长2ns。
包复现上述19%母群检测结果，不授全束匹配资格。Agent未操作GUI；OA默认四实例选择仍保留。

当前78颗损失中76颗原生接触均有部件分类，另有79／95的非碰撞返回旁路；部件分类不等于接触位置收敛。
33颗早期损失均完成负镜预反射，不能把`turns=0`解释为未反射。全97颗的z=−110mm双向诊断截面中，
出镜|x|>2mm的集合恰好等于这33颗，随后约0.075μs接触4mm内屏蔽槽。
全束源vx与出镜x相关系数−0.998844；源／入镜／真实转折／出镜的σx为0.060895／0.445932／0.313116／1.928858mm，
σvx为190.182／148.030／462.275／11.529m/s。镜的角度压缩伴随位置展宽，现有四项质心闭合不授全束接受度。
三臂同源验证（4ns、2ns、2ns细碰撞）均保持19检测／78下游损失及逐ID终止身份。
ID11的粗网格真空假接触已消除，但它继续0.620160μs后真实接触Stripe1的y=−2mm面，检测率未改善。
另27颗接触状态也改变，ID13终点z差20.334mm；4→2ns时ID54接触位置亦差3.557mm。
因此结果支持当前样本的传输身份稳定，不授全场、全程或接触定位收敛。
原始损失及逐ID配对、恢复和退役记录见[束团接受度与碰撞网格里程碑](history/20261018__ion-processor-beam-acceptance-and-collision-grid.md)。

[最新13站IP/OA比较](../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261018_135731__analysis__python__ip-oa-station-phase-space__r04/results/report.md)
保留全部母ID、到达群与最终检测子群、位置／速度／有定义的角度／动能／时间宽度及协方差。
IP出口σx=0.060895mm虽小于OA的0.246597mm，σθx却为0.271991°，OA约0.0000312°；
P2后IP σx=0.952154mm、σθy=0.126771°，OA分别约0.1272mm、0.0290／0.0374°。
目标49处IP仅41颗、σy=11.745743mm，OA各100颗、σy=1.380179／1.907217mm。
这些是不同源、装配、Prism电压与步长的工程对比；OA零初始角宽，不能据此判硬件本征优劣。
现有0.1mm／0.01°等中心闭合容差不是束宽上限；整束发射度、角宽、能散及最低透过率阈值尚未定义。
下一物理方向为横向相空间与慢轴返回匹配，不以缩源、裁尾或只调平均出射能量替代。
当前仅做IP独立器件的辅助电压灵敏度与小型Prism分析，整机响应求解、优化及联合N100未恢复。

主线为对称会聚双镜＋五次项偏置Stripe＋保留实体的接地线性Stripe；K=24.5、加速器y=−55 mm。
原生SIMION自动闭合、响应组合和束团飞行已经可用；COMSOL进行同几何、同电压固定场复现，
尚无新场上的空间闭合或高斯束团性能，两条链资格分开。

原生细档高斯σEy=0.15／0.2 eV的N100分别为R≈101399／80929、98%／95%，均为有限工程结果。
COMSOL各次完整受控N13均0/13检测器命中，尚未获得收敛或性能复现资格。
匹配控制及局部细化后，相对计时差缩小，空间返回仍敏感；跨来源慢向场差部分已存在于原始场及继承边界。
五面边界单因素对照已显著缩小已测单镜的慢向位置／速度差，时间及横向差未同步缩小。
同网格直接父场与组合场的25点一致性已通过，但慢向跨源差仍在；下一决策是受控区分停止因素、
继承边界与内部离散，不继续盲目加密或投入高斯N100。

## 输入权威与物理定义

下表为保留OA分支的[冻结闭合候选][native-anchor]；IP分支使用本页当前决策中的独立闭合电压。
完整电压、几何和消费者按各自冻结运行输入重放。

| 部件／参数 | 当前值 |
|---|---|
| P1 / P2 | +191.69798504788915 / −186.47253641442782 V |
| 五次项Stripe（11/12） | −26.98736945139317 V |
| 线性Stripe（13/14） | 0 V；实体仍保留 |
| 两侧镜A–E | 0 / −5929.660769425788 / −2568.4173725265146 / +4162.7537535912525 / +6003.305171198471 V |
| 单镜倾角 | 0.025688744787259285°；两镜会聚角为其两倍 |
| 正镜旋转枢轴／负镜 | [0,0,102] mm／关于z=0镜像；正镜Rx=−θ、负镜Rx=+θ |
| K及目标事件 | 24.5；49个快速半周期，不是任意终止计数 |
| 当前TE1标量坐标 | −34.10982644173019；后续增量从当前坐标出发，不能重复施加绝对值 |

倾斜的是平面镜电极，不是将其改成曲面；正负镜与Stripe保持设计镜像，整机OA、Prism及检测器并非z镜像。
OA位置变换只施加一次；P1接地罩按原截面延长至OA出口前1 mm，不改变P1/P2尺寸及其绝缘间隙。
镜外侧E盖板保持E电位，不接地；不同电位实体不能接触。当前结构不是论文装置的完全复制。

C0为指定工程假设：完整内表面x∈[−162.5,162.5]、y∈[−242,558]、z∈[−425,425] mm。
半模型五个外面接地0 V，x=0为对称面而非接地壁；相关OA接地罩、理想网格、出口及检测器纳入装配。
C0不是已经确认的机械腔体；省略它的开放BEM与该边界模型不同，尚未证明对性能可忽略。

两区加速器使用线性场，理论出口z=0为初始时间聚焦设计面；实际束团仍需诊断，不因理论目标自动通过。
TE1控制局部释放z一阶时间响应，不自动校正Ey、横向偶响应、宽幅z或接受度；改镜后须自动重闭合P/S。
种子周期与实际镜周期区分记录，不在每次TE1中静默重定义几何或用旧轨迹Jacobian跨锚外推。

## OA真实源与束团证据

源中心[0,−56.05182899425077,32] mm，沿+y释放；圆柱高度1 mm、半径0.5 mm；质量524 Da、电荷+1、共同出生时刻。
慢向动能均值5.374387143093758 eV。高斯σ是释放事件处动能标准差，不是速度sigma；
当前σ=0.2为主条件，0.15为对照，0.3为压力测试。位置与标准化能量取同一1000颗母样本的前100颗，
不重新居中有限样本均值、不裁尾、不缩源。角宽仍为零，空间电荷、真实出生时间宽和制造／探测器影响未覆盖。

纯体积N100与受控N13分别报告：N13含中心、z±0.1、Ey±0.05、x±0.1、y±0.5、x±0.5、z±0.5 mm参考。
受控ID1为名义中心；高斯ID1是体积样本，不能误称源中心。共同幸存者仅用于配对诊断，不能替代完整源性能。
σ0.15和0.2的母样本身份、相关性与实际有限样本均值分别见[源收据15][source15]和[源收据20][source20]。

以下均为同一候选电压、镜区z=0.02 mm场、4 ns/Q8、common KDE；损失全部保留。

| 高斯σEy/eV | 平均TOF/μs | KDE FWHM/ns | R | 命中／释放 |
|---|---:|---:|---:|---:|
| 0.15 | 764.216444815 | 3.768379855 | 101398.541848 | 98/100 |
| 0.20 | 764.216316535 | 4.721538636 | 80928.736944 | 95/100 |

原始结果分别为[细档σ15][fine15]和[细档σ20][fine20]。σ15损失49/98于P2接地件；σ20另损失7/21/56于P2接地件，
49于五次Stripe12、98于接地线性Stripe14；这些结果不等于所有尾部均有接受裕量。
镜区z=0.04→0.02 mm后，两组峰宽分别改变−0.005991/−0.005196 ns，命中及损失身份不变；
同粒子相对高斯ID1的检测器时间最大变化0.029653/0.029147 ns。平均公共TOF漂移约+0.094 ns，单列而不算作峰宽。

同源σ0.2历史平行镜78%／R19217与会聚候选95%／R79987有明显差别，但几何、电压、场表示和步长同时变化，
不能把全部改善独立归因于镜倾斜。[配对证据][parallel-pair]保留恢复20颗、新增损失3颗及共同命中75颗。
历史均匀Ey全宽0.1 eV、σ≈0.0289 eV的结果不是高斯σ0.1或0.2的性能资格，不跨采样／峰宽口径精细排名。

## 活动原生场与消费合同

静态场 provider 的资源限额直接由已编译 plan 传给同进程公共观察器，不再另写 composition、各 occupancy
或各 field level 的 `*_resource_budget.json`；完整 plan 和 usage 内的 limits 仍冻结，预算和数值不变。

MR 的 SIMION response worker、IP→Prism 局部 worker 与 COMSOL corridor provider 对时间、目录、工作集和可用内存观测只发出一次警告；父失败停止新启动并等待已启动健康求解器的自然终态，绝不因这些观察单独终止。只有入口明示硬超时或公共调度器确认的持续物理内存危险才允许停止。

当前源码入口为[直属OA→MR飞行](../../../integrations/workflows/oa_mr/execute.ps1)、[原staged](../analysis/run_downstream_workpoint_iteration.ps1)、
[自动候选链](../analysis/run_native_candidate_chain.ps1)；场由`simion/run_native_static_field_provider.ps1`
和`analysis/static_field_binding.py`接入，不另建手工闭合器。直属入口的新owner真实飞行尚未验证。
固定场binding、外场消费、原trial接线、标准诊断及staged／候选自动链源码统一纳管。
运行仍须提供对应冻结资产；源码发布不授予其他输入的闭合、束团性能或Formal资格。
分块PA组合器及专属测试已作为项目模块纳管并推送ed745b07；算法字节未变、无公共兼容入口。
Prism路径身份统一使用`two_prism_topology_signature`；已删除无人调用的私有兼容转发，不改变转折分支判定。
相关导入／冻结路径已同步，28项组合器focused测试及MR Core/L1通过。
固定场消费另运行七模块300项回归：298通过、2项因旧A父PA已退役而跳过，约108.8 s；
活动launcher合同、Lua穿面事件及Python静态检查通过。三路独立审查未发现普通消费路径发布阻断。
真实证据仍以细档native高斯N100和mesh4受控N13为准；纯测试不授响应、物化或COMSOL改压重建资格。

| 场层 | 求解范围／布局（mm） | 各轴网格间距（mm） |
|---|---|---|
| C0父场 | 完整半外壳及相关装配 | 0.50 / 1.00 / 1.00 |
| 中央局域场 | [0,−100,−325]至[22.5,390,325] | 0.25 / 0.25 / 0.10 |
| 正负镜局域场 | x=0..2，y=−65..360，z=90..324及−324..−90 | 0.04 / 0.20 / 0.04（工作）或0.02（细档z） |

局域五面边界继承相同电压下父场；镜域先完整求解后裁剪存储x≤1.28 mm，实际启用x≤1 mm。
“完整域求解后裁剪”不等于在裁剪面重新Refine；多层优先级及碰撞载体按冻结binding，而非普通GUI云图推定。
新规则网格间距均为0.01 mm正整数倍，最小0.01 mm；历史非整数档冻结保留，不静默取整。

工作场[163135][native-field]复用父场与中央场、两镜Refine约553 s，建场/refine/裁剪约717 s；
含排队总时2031 s。细档[032031][fine-field]两镜Refine约1637 s，总2018 s，约13.14 GB，峰值内存约22.04 GiB。
032031细档仍为当前可用资产。163135旧粗档已在IP新场准备期间沿公共owner机制退役PA／surface，
其冻结输入、轨迹和网格比较指标保留；历史IOB须重建场后才能重放。
同轮还退役043210旧平行前驱及073134早期会聚前驱场，三组释放41,611,748,008 B。
当前134039中央场、032031细镜、7515开头的OA响应缓存及用户GUI包全部保留。
退役同时检查当前、下一消费者及GUI引用，不按文件年龄删除。

所有层显式Refine convergence=1e−5 V、fractional表面；默认0.005 V是指导值，不能恢复成项目硬约束。
同网格历史默认→严格产生重要响应变化；1e−5→1e−6在旧档检测器相对时间最大变化约0.025 ns，
仍不是当前所有轨迹的总误差界。实际Delta/迭代记录继续保留，不把停止参数直接等同于真实场误差。

正常最大步长4 ns、Q8；已测N13的4→2 ns相对检测器变化约0.00154 ns，时间210.6→384.7 s。
该历史证据支持当前工程默认，不自动授当前高斯尾部完整积分资格；最终候选仍检查返回状态和终止身份。

响应组合复用已有`analysis/static_field_binding.py`与`simion/scalar_field_adapter.lua`。
电势对电压线性、轨迹不线性；负权重允许，记录误差放大指标G但不将其当误差界。
当前S1 y360响应兼容163135；旧P1/P2/TE1响应仍含y350边界，不能绕过兼容检查接入新y360，
细档z0.02也不能直接套z0.04响应。只补实际闭合所需成员，不以响应库重建取代物理决策。

自动链先P再S；当前converging_clean_phase_energy使用首次正镜位置及清洁状态慢向能量，旧P2角度保留诊断。
P位置0.1 mm、能量0.0523430183 V/q、S两位置各0.1 mm；S1/P1/P2约束联合修正，接地S2不放开。
可信预测可取100%预测步；实测不符才有界回退，缺事件不造Jacobian，有明确有限停止条件。
当前中心四项通过，但P位置约+0.099999 mm贴近容差边缘，不等于稳健孔径裕量或跨网格闭合资格。

批次恢复按实际场模式绑定小输入：静态native／COMSOL使用场binding及adapter，不再要求无关的Fast Adjust bank／bundle。
[真实中断资产计划验收][static-recovery]已复用完整首批2颗、识别剩余11颗需重放，14项冻结输入匹配，
没有加载PA或重新飞行。两种静态模式的正常复用与binding变更拒绝回归已覆盖；
该证据只关闭恢复规划缺口，不代表11颗续飞、GUI重装配或完整自动链已经验收。

## 电场表示与数值资格

原生细档的已测高斯峰宽及损失身份接近，但N13慢转折最大差仍约1.203 ns、慢返回y=0约1.083 ns，
不能宣布全轨迹收敛。约0.2 ns是十万目标的总体初始工程预算，不是探索硬门槛、单环节预算或严格误差界。
共同TOF平移、端点响应和相邻档差均不能直接当作FWHM；事件必须按身份、方向和返回分支配对。

COMSOL现在是完整C0装配独立求场，不再继承SIMION donor；实际消费为标量电势→规则PA→
SIMION求导、插值和窗口选择→原trial。两来源复用调度、碰撞和诊断，不另建追迹／闭合系统。
普通GUI场查询不等于外场回调，保留IOB不授云图对等资格。网格、求解停止、导出、积分及事件误差分别管理。

### 有效场与固定输入对照

当前[mesh4][mesh4-longest]为30697694四面体、Q2、CG＋AMG、rhob40000、sol4/dset1；
runAll约1564 s、完整运行1880 s、峰值约41.83 GiB。参数不是误差界；mesh3同控制冷重求的40点可重复，
不等于停止误差关闭。旧混控制或组装失败档不能串成收敛序列，完整过程归[里程碑](history/20261015__boundary-input-isolation.md)。
COMSOL不升级；厂商材料保留未发送，不继续无新假设的大模型重试。

[mesh4四窗导出][mesh4-export]约1971 s／5.199 GB：
base间距0.25/0.25/0.10 mm，正负镜0.04/0.20/0.04 mm，慢返回三轴0.10 mm；
优先级正镜→负镜→慢返回→base。基础窗5664未知节点保留无效，另三窗全有效；
必须按真实轨迹支撑检查，不能补零或将未知查询计作物理碰撞。

同源[mesh4 N13][mesh4-n13]全部出现target49，0/13检测器命中，10碰撞＋3拓扑拒绝；
中心target49 y残差+10.694 mm。没有检测器峰宽／R，不运行高斯N100来补造性能。
[配对][mesh4-pair]的FEM间15项、跨源9项控制一致，当前结果为：
单镜原始出口见[mesh3][segment3]、[mesh4][segment4]及[native][segment-native]，不与整程终点混用。

| 固定输入比较 | 最大相对中心ΔTOF/ns | 最大Δy/mm | 解释 |
|---|---:|---:|---|
| mesh2→3，target49 | 0.601675 | 1.878743 | 匹配求场控制，尚改变返回 |
| mesh3→4，target49 | 0.211393 | 1.006036 | 差异缩小，ID9碰撞部件改变 |
| native细档→mesh4，target49 | 7.342627 | 15.095070 | 跨来源未一致，不按命中多选真值 |
| mesh3→4，同入口单正镜五颗 | 0.028632 | 0.013904 | 同出口，最大Δvy=0.0018746 mm/μs |
| mesh4→native，同入口单正镜五颗 | 0.037722 | 0.071485 | 同出口，最大Δvy=0.0091949 mm/μs |

单镜入口六维状态与原时钟完全继承，五颗覆盖中心、Ey及全幅x对。小单段计时差伴随慢向状态差，
不能乘49或授整程资格；[同场放大试验][amplification3]已见入口y差0.027424扩大至0.622397 mm。
target49的Ey斜率在mesh3／mesh4／native为17.44775／17.69162／2.46446 ns/eV；
全幅Cx为2.559779／2.556643／2.324758 ns，均不是检测器性能。

### 当前已隔离的差异与下一决策

[40点消费分层][mesh4-consumer]显示，所查正镜转折点的消费场−原始FEM慢向分量最大差0.08308 V/m，
native−消费仍约7.58514 V/m；主要跨源慢向差已存在于原始场，不支持盲细导出。
但z=97 mm所查点的桥接向量差仍约13.883 V/m，不能授整条桥接资格。
局部镜坐标Ry=Ey−tanθ·Ez仅用于诊断，不是纯Stripe场，也不能扣除后修轨迹。

冻结几何与完整电压逐字段一致，未发现漏OA、C0不同或二次旋转；原生细镜五面却继承中央及父场，
而FEM求整个C0。当前倾镜／电压没有独立父边界资格，旧平行镜证据不能继承。
[25点边界输入][boundary-input]中x=2 mm面原生−FEM电势均值−0.488858 V、变化范围0.017444 V，
沿y差商对应2.623–7.294 V/m；这不是纯常数偏置，也尚未证明它解释了束内差异。

[边界单因素飞行][boundary-flight]固定完整正镜域、0.04/0.20/0.02 mm、几何、电压、fractional、1e−5 V及五颗同入口，
只将五面输入换成[mesh4 donor][boundary-donor]；x=0仍对称，物理电极不覆盖。三组均5/5到同一出口，无碰撞或缺失。
相对FEM的最大y差由0.071485降至0.002356 mm、vy差由0.009195降至0.000770 mm/μs，约缩小30／12倍。
相对中心TOF差却由0.037722变为0.038963 ns，横向亦未同步改善；这证明边界影响此段慢向空间状态，非整程收敛。
donor的25点表示及原始完整矩阵、耗时／故障与处置记录已归[本里程碑](history/20261015__boundary-and-parent-consistency-isolation.md)。

父层固定25点矩阵已结束，完整结果与耗时归[父场隔离里程碑](history/20261015__parent-axis-field-isolation.md)。
当前0.50/1.00/1.00 mm父层已含慢向跨源差；中央层又改变该差，不能解释为同一常数电势偏移。
同U直接父场与组合场最大电势差1.70e−11 V；1e−5→1e−6停止增量也仅8.42e−11 V，
均不足解释所查跨源慢向差，不因此授整个场或其他响应库资格。

| 四中心实际API慢向电场增量 | 范围，V/m |
|---|---:|
| 父层仅z：1.00→0.50 mm | +3.485–3.517 |
| 父层仅y：1.00→0.50 mm | +0.0341–0.0467 |

已测z敏感性不是仅由电势差商定义造成；但z向梯度的两种查询模板仍有2.09–3.80 V/m差别。
平均电势更接近FEM不代表梯度更准确；没有一种场被指定为真值。
API为25点无局窗父层诊断投影，没有联动局域重建或飞行，不能推导峰宽、R或全轨迹收敛。

## 剩余时间响应与设计线索

倾斜候选的局部Ey敏感性已明显下降，但尚未得到独立大样本下完整宽平台／十万资格。
当前两组高斯共同95颗的沿程ΔTOF/ΔEy约为：OA出口≈0、首次P2后1.61、target49 3.25、
回程P2入口3.50、P2出口−9.52、检测器−9.38 ns/eV。入口位置亦随Ey变化约−12.14 mm/eV。
P2短段位置扰动显示时间对入口y约1.077 ns/mm敏感，说明入口状态差经返回传输转换，
不是只看“时间差在P2出口增大”就认定误差产生于P2或P2网格。

工作场受控x±0.5 mm偶响应Cx≈2.362 ns、宽幅z响应及y端差仍存在；x奇项为零只支持左右对称，
不能排除偶像差或对称数值误差。正负镜段的不同状态、上游匹配和Stripe耦合需按同粒子同事件分析，
不能仅按单段最大差认定某一电极原因，也不能把各项端点差相加当完整FWHM。

S1单独−0.1 V对Ey响应改善很弱，却使空间相位偏约−0.915 mm，未成为新候选；不重复该小扫描。
下一有效方向应来自当前低压模型的镜倾角／Stripe／注入联合响应，兼顾空间返回、尾部和孔径裕量；
不恢复无工程资格的千伏Stripe，不按TE2名称预设解法，不以缩小σ替代主条件达标。
自动N100后处理复用已有分段及源状态分析，回归仅作定位线索；大幅因果判断仍需受控实际响应。

## 开放动作与关闭条件

1. 边界单因素、父场组合／停止、y／z拆轴及实际API查询已完成；所查父层慢向变化主要对z敏感。
   已获批的中央单阶段对照000829正在执行：仅以z=0.50 mm父场替换边界，完整中央网格及物理输入不变，
   容量承诺9,817,256,922 B已准入；预计80–95分钟，完成后只查原25点，不自动建正镜或飞行。
   新父身份绑定实际222113封存PA及网格，不消费其中旧parent_level投影；旧中央为物化、新中央为直接解，比较仅作传递诊断。
   不绕过中央层冒充原传递链；仍需检验实际轨迹影响，
   不按更接近FEM选择真值。余下横向／计时差仍待解释。
   不将FEM donor伪装成原生祖先，不以单镜改善替代整程或束团资格，不逐场调压冒充数值收敛。
2. 冻结场消费与自动闭合源码／配置统一纳管；各模式资格仍按具名运行分别验证。
   通用COMSOL改压provider已有多窗编译与发布校验，但求解readback仍绑定sol1/std1，
   不授当前mesh4的sol4重建或改压资格；普通冻结场重放不执行该求场作者。
3. 代表射线支持后才做冻结高斯N100复现，统一KDE、全部损失、峰形及不确定性；
   数值比较固定电压，调焦后的性能比较另做。未支持时交付已量化差异与下一设计决策，不宣称十万达标。

两条链的当前场、响应库、GUI和CAD继续保护；已结束无人消费的载荷只沿公共owner退役。
旧mesh1／mesh2／mesh3四窗PA及旧平行镜181800物化场已公共退役，原MPH、小证据及必要重建来源保留；
历史IOB需重新物化／重装配，当前会聚场、GUI／CAD不受影响。处置字节与收据见[处置记录](history/20261015__boundary-and-parent-consistency-isolation.md#保留与清理)，
更早退役代码和运行恢复见[原里程碑](history/20261015__boundary-input-isolation.md)，
不靠运行终态自动判删除，也不将清理或门禁通过当物理资格。
203103边界因果试验的完整镜PA／surface也已公共退役，释放10,151,390,124 B；27份冻结输入、五射线结果及donor保留。
其收尾CLI退出码−1073741819，但账本已提交ready/light_evidence且两文件已删除；不重复删除或为取PASS重跑发布，保留该退出异常边界。

当前[STEP交付][cad-delivery]为40个独立电极STEP、6个C0参考面及装配概览；保留倾镜、精确曲线、去全部安装孔。
仅真实连接同电位组件合并。5 μm为交换精度，不是场／制造精度；尚未完成对方软件消费验收。
给Pulsar Physics的[英文交接包][pulsar-handoff]已精简为2页，包含倾镜STEP、完整电压、离子初态及真实逐步轨迹叠加STEP边线图；
不展示分辨率目标或内部收敛过程。配套英文邮件保留会议五问并补充RF／脉冲、空间电荷、质谱应用与数据导出，由用户自行发送。
代表离子采用040845源ID1同输入[重放][pulsar-trajectory]，213706条原始回调记录、350条旧事件逐字段完全一致；
检测时刻仍为764.217930877 μs。原生terminal同状态回调的微小时钟回退原样保留，不排序或改值；不授予新束团性能资格。
记录功能39项focused及真实N1通过；改动仍依赖工作区时钟／ID适配，未单独发布。
旧四实例源码断言已按OA／IP分支合同修正；2026-10-16真实联合包闭环后22路径L1通过，
包括MR Core42项及普通Lua回归、IP Static161项。该源码门禁不授予新装配联合飞行或GUI资格。
旧平行镜53件说明不作配套；唯一活动CAD入口为
[run_resolved_cad_export](../analysis/run_resolved_cad_export.ps1)。

以下链接指向具名小证据，不复制全部manifest；资产保留期限以公共pin/lease与实际消费者为准。

[native-anchor]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_134039__sim__simion__converging-te1-trusted-fullstep-resume-stage-013/summary.json
[source15]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_224500__analysis__python__gaussian-ey-sigma0p15-volume-n100/results/bunch_source_receipt.json
[source20]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_144730__analysis__python__mrtof-gaussian-ey-sigma0p2-volume-n100/results/bunch_source_receipt.json
[fine15]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_040845__sim__simion__converging-y360-z002-gaussian-ey-sigma0p15-n100/summary.json
[fine20]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_044251__sim__simion__converging-y360-z002-gaussian-ey-sigma0p2-n100/summary.json
[parallel-pair]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_011744__analysis__python__parallel-tilted-gaussian-paired-reference/summary.json
[native-field]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_163135__build__simion__converging-mirror-y360-field/results/field_binding.json
[fine-field]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_032031__build__simion__converging-y360-mirror-z002-field/results/field_binding.json
[cad-delivery]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261014_163154__build__cad__mrtof-tilted-step-publication-recovery/summary.json
[pulsar-handoff]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261016_140921__build__python__pulsar-trajectory-handoff/summary.json
[pulsar-trajectory]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261016_142700__sim__simion__pulsar-representative-id1__r02/summary.json
[mesh4-longest]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_164500__analysis__comsol__positive-turn-mesh4-longest__r02/summary.json
[mesh4-export]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_174000__analysis__comsol__mesh4-coherent-beam-tube-export/summary.json
[mesh4-n13]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_181000__sim__simion__mesh4-fixed-u-controlled-n13/summary.json
[mesh4-pair]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_182403__analysis__python__mesh4-controlled-n13-pairing/summary.json
[mesh4-consumer]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_185431__analysis__simion__mesh4-fixed40-consumer-field-layers/summary.json
[boundary-donor]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_194413__analysis__cross__fem4-boundary-donor-representation/summary.json
[boundary-flight]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_203103__sim__simion__fem4-boundary-only-positive-mirror/summary.json
[boundary-input]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_191649__analysis__cross__native-mirror-boundary-input-check/summary.json
[static-recovery]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_193228__analysis__python__native-static-batch-continuation-acceptance/summary.json
[segment3]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_161302__sim__simion__matched-mesh3-same-entry-mirror/summary.json
[segment4]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_183100__sim__simion__mesh4-same-entry-positive-mirror/summary.json
[segment-native]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_183200__sim__simion__fine-native-same-entry-positive-mirror/summary.json
[amplification3]: ../../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_162423__sim__simion__mesh3-entry-in-mesh3-return/summary.json

固定镜到 Stripe 的 `load_fixed_grid_mirror_point` 只核验实际消费的 run_config 与四份镜电压、
周期及原生 L1/probe 证据，保留其角色、互相身份绑定和全部物理门槛。下游合同身份不同时，仍核验
原 run 邻接冻结 source contract 的 SHA 及允许的物理差异；同身份分支不新增历史文件要求。
无关轴场比较、日志、资源／容量收据的缺失或损坏不阻止这项消费，不代表原完整 run 通过重新验收。
