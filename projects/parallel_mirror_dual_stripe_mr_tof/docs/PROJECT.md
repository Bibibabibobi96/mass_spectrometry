# 开放路径平行镜双条带 MR-TOF 项目状态

本页维护MR分析器的当前设计、资格、有效证据和开放动作。操作由[项目入口](../README.md)导航，
推导见[理论索引](theory/index.md)。完整接口迁移、已完成研究、实现修复及原始证据链接冻结在
[文档收口里程碑](history/20261026__assembly-documentation-consolidation.md)，历史语气不作为当前执行指令。

项目门禁由[verify_project.ps1](../verify_project.ps1)进入，逐测试输出耗时并保留失败传播；
不同门禁等级和实际选择范围仍以该入口为准，不把软件门禁通过当作求解或科学资格。

局域 S 模型恢复的软件夹具将八个隔离场景合并到一次 PowerShell／生产 AST 读取；40 次真实 Python controller 请求保持。
每个场景以 JSONL 即时返回并断言，stderr 独立保存；已启动子进程自然排空。真实非零退出、缺／重复行及首错即时传播有行为验证。
同机单次受控对照外层墙钟39.8168→32.4221秒（约−18.57%），不代表完整MR或Repository提速；
隔离当前提交的同一方法另通过33.422秒，八场景均保留。本项仅改变软件夹具，不修改生产恢复或物理资格。

工作点迭代的五个PowerShell夹具显式接收当前Python解释器，真实controller仍通过该解释器执行，
不依赖checkout存在`.venv`；JSON与源码读取显式使用UTF-8。无`.venv`的隔离checkout中，
CI失败涉及的七个方法通过，测试103.159秒、公开Python命令外层103.379秒。
此前CI `41075311439`仍保留失败；该修复不改变生产控制器、容量门槛、科学判据或数值容差，
也不代表完整MR、Repository或原生求解验收。

## 当前决策与完成边界

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

prepared-joint与IP局部诊断的PNG／SVG保存复用[公共图形导出](../../../common/analysis/figure_export.py)，
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
`downstream_workpoint_iteration --controller-request - --output -`传输。层级与正反列次序、
候选缩放、声明边界、L∞步长下限、候选／飞行预算和终态在同一请求返回；PowerShell继续
核验冻结身份、写入pending checkpoint及调用实际飞行。普通回合只增加一次完整规划请求；
仅累计拒绝触发局域模型重置时，先发prepare请求并保存，再读取新科学decision并规划trial，
保持原先的恢复次序。完成trial的接受判定仍使用原有`complete_staged_trial`请求。
transport seed 的整批有序候选、bootstrap 四步长与重试比例、已验证 centre observation
的物理通过判定也由该纯决策模块提供；PowerShell 保留完整 manifest verifier、身份核验与
逐次保存/执行次序。物理 gate 每份实际 observation 使用一次完整反馈请求，未将完整
manifest 验证缩成 record 子集。其他 stencil/recovery 状态转移仍按原入口执行，尚未据此
宣称全部 PowerShell 科学决策迁移完成。
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
