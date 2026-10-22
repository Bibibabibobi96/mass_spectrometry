# RF多极杆到单反射oa-TOF当前集成状态

本页只维护当前设计、资格、限制和待办。操作见[RUNNING](RUNNING.md)，参数与失效域见
[ARCHITECTURE](ARCHITECTURE.md)，历史见[HISTORY](HISTORY.md)。各项结论只适用于明确列出的运行证据，不自动晋升资格。

## 统一组装迁移任务

状态为规范已批准、实现待迁移。目标职责见[统一组装规范](../../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md#统一组装目标)，
依赖与阶段见[迁移计划](../../../docs/ROADMAP.md#统一组装迁移计划)。本目录及唯一公开入口目前继续活动；
本轮不改源码、配置、运行或资产，不将整个目录提前标成只读，也不把计划登记当作新物理运行授权。

| 现有消费范围 | 待迁移动作 | 关闭条件 |
|---|---|---|
| `local_frontend`裸导引→二区／三区OA | 首条配方消费，引用OA及实际导引提供者，保留变体选择 | 同冻结输入的实际几何、电极、RF／脉冲、母群、时钟与默认回放对照成立 |
| `cooled_frontend`冷却前端→OA | 单独workflow与配方，复用IP物理提供者和既有公共机制 | 当前在途依赖安全闭合后验证HP、聚束／门、气体及驱动绑定，不借裸导引结果宣称冷却通过 |
| 原多极杆→单反射整机的分段三链与连续单飞 | 明确配方、耦合模式和工作流对应关系，复用原分析器接口 | 源与restart、完整母群、绝对时钟、场角色／优先级、恢复及联合分析的声明保持可追溯 |

目标是每种组合增加配方而非复制运行器；原共享core按真实复用边界提取。各workflow完成等价验证和
注册／调用／产物切换后，新请求转入`integrations/`直属入口；无在途依赖后才退出被替代副本。
未切换workflow仍走本目录。旧run、PA来源、GUI包及历史integration身份按原归属保留；迁移不关闭本页
尚未取得的收敛、完整链或Formal资格。

## 所有权

- 上游项目拥有器件几何、RF驱动和canonical输出；源以冻结粒子表发布，不能因源的生成方式另立输入权威。
- 独立[加速器项目](../../../projects/orthogonal_accelerator/README.md)拥有局部理论与构建，
  [oa-TOF](../../../projects/single_reflection_oa_tof_mass_analyzer/README.md)拥有整机布局、反射器、耦合和Formal资产。
- integration拥有连接器、端口绑定、单飞适配、campaign生命周期、联合分析和集成证据。
- 唯一公开执行入口为[execute.ps1](../workflows/family_source_closure/execute.ps1)；
  [run_single_flight.ps1](../runtime/run_single_flight.ps1)是其内部SIMION运行边界。

## 当前配置与入口

### 同源八极导引接入与二区／三区复用

局部工作流通过同一公开入口的 `-FrontendRequest` 选择，复用 OA 器件提供者、RF／脉冲运行器、
公共 PA 缓存、自动批调度和完整母群分析，不包含反射器或 MR 联合飞行。裸导引接入已实现
canonical 二区和显式 sectioned 三区；旧二区／三区整机路径保留。两种局部结构分别冻结实际电极、
平面、侧口和装配身份，不能只换变体名或复用另一结构的场资格。

同源对象是 IP 的原始 100 行释放及其裸八极导引：29 mm 实体杆长、内切半径 2 mm、圆杆半径
0.6 mm，3.7 MHz、每极 1000 Vpp、导引段真空。源为半径 1 mm、全高 5 mm、524 Da／+1，
纵向能量高斯参数 5±1 eV、横向 300 K。具体字节和参数由冻结源合同核验，保留全部 ID、质量、电荷、
出生时钟和六维状态，不重采样；不得以 IP 出口幸存者或旧 OA 零横向速度源替代出生母群。

所有几何、GEM、PA、IOB、源和诊断直接使用 `mrtof_global_cartesian`：慢漂移 +y、引出 -z，
观察变换为单位阵，没有仅供显示的 Workbench 旋转。二区通过提供者 requirements schema 2 显式侧入口
选择实际封闭端 profile；三区通过 `orthogonal_accelerator_bare_three_zone_requirements` schema 1
完整声明已有 sectioned 几何，由提供者渲染，四个实际平面为 repeller、grid1、intermediate2 和 exit。
三区不套用二区支撑框或孔径，也不套用旧含入口板／参考套筒的八模式结构。器件 API 与几何边界见
[OA 当前能力](../../../projects/orthogonal_accelerator/docs/PROJECT.md#当前能力)。

裸导引二区使用五个 PA+ 模式，三区使用六个：两项导引杆共模／差模响应，加各自三个／四个加速电位
端点响应。实际环位置和 ON／OFF 电压通过同一显式线性模型合成；改变运行电压、RF 驱动或出生时钟
不单独触发 Refine。缓存仍绑定真实电极、孔、装配、网格、PA 包络、GEM 和构建依赖；源包络改变
实际 PA 范围时也改变身份。零厚理想栅面贡献求场电位但允许粒子穿越，不代表实际丝网或实体网格透过率。

当前二区功能性作者采用 1 mm 杆端间隙、3 × 2.8 mm 侧孔，MR 孔壁 y=-67…-66 mm、中心
(0,-66.5,32) mm；它不是历史孔径研究已证明的合适工作点。孔径离散 schema 3 根据真实法向、世界中心
和各轴 cell 记录警告：当前 x/z=0.1 mm、y=0.2 mm。尺寸或边缘不对齐只告警，不改机械几何；
实际 PA 的贯通节点及孔外 guard 仍是飞行门禁。
两实现分别为 4+30 mm 与 4+15+15 mm；主平面电压相同，三区中间面位于下游线性压降的中点。
它们还分别使用 44／34 mm 屏蔽 x 外宽、1／0.5 mm 环厚、25×26／26×26 mm 开口及不同栅支撑，
孔边界沿用各提供者的 `inside_only`／`inside_or_on` 语义。因此相同机械侧孔不保证相同有效网格通道，
必须分别读取编译后的孔拓扑；侧孔无 warning 也不代表整机网格已经收敛。

二区／三区已分别完成原生场、孔拓扑、完整 N=100 discovery／extraction 和严格终态分析。
两者保存 IOB 的全量默认回放均已通过。出口 z=0 的各自条件群如下，
全部标准差均为人口 SD（ddof=0），母群分母始终是原始 100 个离子。

| 指标 | 二区 | 三区 |
|---|---:|---:|
| 到达出口／母群 | 70/100 | 66/100 |
| 原生提前停止／超时 | 30/0 | 34/0 |
| σx／σy（mm） | 1.702776／3.734962 | 1.730299／3.538753 |
| σθx／σθy（°） | 0.239963／0.980397 | 0.274469／1.096548 |
| 到达时间 σt（ns） | 19.049654 | 18.007098 |

`native_stop_unresolved` 只确认原生提前停止，尚未逐一归因于具体电极或数值机制。
这是两个功能性工作点，不证明时间焦点、数值收敛或 MR 接受度；几何对照也不是只改变区数的单变量实验。
独立对照还保留共同出口 62 个 ID 的配对统计：二区／三区 σt 为 15.014281／16.606567 ns，
与各自幸存群的变化方向不同，不能据表中 σt 宣称三区聚焦更好。
两套 IOB、修正后的检查面图、自动选择时刻的空间图和逐离子损失入口统一收录在
[完整对照报告](../../../../artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20261021_165805__analysis__python__local-oa-design-comparison/results/scientific_report.md)；
运行身份、缺陷闭合、验证范围及保留记录见[本轮冻结记录](history/20261021__same-source-local-multipole-oa-n100.md)。

局部分析自动保留源、孔前／孔后首次正向穿越、各实际加速检查面、出口、全部损失及共同绝对时刻
空间图。孔面按 +y 穿越，方向分量角为 atan2(vx,|vy|)、atan2(vz,|vy|)；加速出口按 -z，分量角为
atan2(vx,|vz|)、atan2(vy,|vz|)。这些是有符号横向分量角，传播正反向另由穿越事件判定。各分量角与空间宽度使用完整声明口径的人口 SD（ddof=0）；
孔前后同时保留各自到达群和配对 ID 对照，不能把幸存筛选后的变窄当作无损冷却。穿面分布与同刻
空间快照分别输出，旧整机 `oatof_global_cartesian` 的轴名不可直接作为 MR 分量比较。

共享时刻 census 保留诊断缺口：二区旧记录在 6.25 µs 有 12 个超出 32 ULP 的早到样点；三区
有 ID16／ID36 的 6 个域外采样空缺，位于最后域内轨迹和真实 `instance=0` 终态之间。三区已发出的
2,345 个共享样点均满足 32 ULP。两类缺口分别解释，不补值、不计为额外损失；出口条件群统计不受影响。

孔面 checkpoint 与出口采用同一原生步内的时间及六维状态线性插值，明确标注为插值状态，
不宣称它是无误差的积分器采样。每次孔面事件保留 `step_before → step_after → checkpoint` 三联
TRACE；分析复核同粒子、同载体和同日志来源、正向包围、时间及六维插值值，原生端点不改写。
没有有效包围的零步确认仅接受原生前后状态相同且实际孔面位置满足 32 ULP 序列化容差，不外推。
`distance/velocity` 限步在 RF 非匀速场中仍可能微越面；旧直接记录落步状态的运行必须保留失败证据并
以新冻结 Program 重跑，不能放宽孔面容差或将该分析拒绝计为离子损失。

默认可加载 IOB、显式轨迹质量和轨迹保留使用同一生成链；每次局部执行还自动启动新进程，以保存的
IOB 默认设置 Fly，并对照调度飞行的全母群原始记录。二区／三区分别在新进程通过 100 个原始 ID、
61,816／61,502 个事件的逐值一致性检查，控制文件未改动；不使用脚本 `--programs`／Q 覆盖推断默认等价。
该证据不替代手动 GUI 验收。操作与恢复见 [RUNNING](RUNNING.md#审查与-dry-run)。

审查未发现需要重建调度器或逐成员重新 Refine 的依据；继续保留现有共享机制。零 transmitted 的 handoff
续飞入口仍会拒绝启动，这是待完善的零收集结果发布边界，不应通过构造空 Fly 或删去母群损失绕过。

| 对象 | 权威来源与范围 |
|---|---|
| 连接、端口与位姿 | [connection profiles](../config/connection_profiles.json)及两端port合同 |
| 活动campaign发现 | [lifecycle registry](../config/diagnostics/lifecycle_registry.json)；普通探索按显式exploration准入 |
| 单飞布局 | [layout profiles](../config/single_flight_layout_profiles.json) |
| 300 mm孔径矩阵 | [pre-pulse合同](../config/explorations/ideal_acceptance_300mm_terminal_aperture_height_axialgrid010_pre_pulse_n5000.json) |
| 当前来源 | `continuous_frontend`或`pre_pulse_restart`；后者不能冒充完整母群连续传输 |
| 准备输出 | authored最小行单向展开为resolved plan/source/budget并冻结到run-local |

当前20环三区候选为`CANDIDATE_ONLY`，不改变原Formal。完整母群使用
`frontend_xy025_z010_coarse100_full_bore_main_local_xy050_z010`与`full_accelerator_v1`。
上游细域、主域与local网格来自冻结profile，不由文档数值表另行定义。
旧横向core、零场碰撞载体与旧pre-pulse优先级均不能成为当前完整母群路径。

连接器继承上游屏蔽截面。正gap时有带孔端板，方形零gap不另造套筒或端板；圆形侧口由具名
对接合同派生。长gap分域由冻结bridge合同控制，粗PA提供Dirichlet来源、细PA按优先级替换，
不叠加场。孔径由入口local表达；缺少local或主family身份不闭合时不能飞行。

单飞及分段analyzer入口已在外层区分轻准备、refine重计算、飞行重计算和轻后处理；
[阶段运行边界](RUNNING.md#主机资源阶段)说明适用范围。此次改动不改变既有内部并发、观测和断点续算，
也不增加真实求解或物理资格结论。
`single_flight_transport`会把加速器理论源码及其实际导入的`common/contracts/particle_physics.py`一并冻结到
run-local快照，并以脱离仓库的导入回归检查依赖闭包；这只证明执行源码闭包完整，不构成求解器或物理资格证据。

## 活动代码精简边界

活动入口审查已移除四个无注册、无调用、无当前文档或测试消费者的独立 CLI：固定 2.2 mm/100 Da/10 eV
有限区间源生成、固定 winner 图、独立 time-series restart campaign 作者及独立恢复 pulse-selection 发布。
当前时序后继仍由 `run_time_series_successor` 调用既有 restart 物化与 prepare；当前 pre/post-pulse 派生、
恢复和分析发布继续使用 RUNNING 中的具名入口。既有 run、冻结快照和历史证据未改写，旧源码可由 Git 追溯。
同时移除未调用的通用验证器、旧全量 states CSV writer 与旧 N=1 manifest reader；保留 callback-neutral
Lua 校验和当前 streaming CSV writer；原先仅由测试调用的全量内存 parser 及 StateRow 已删除，
其时钟 ULP、非法采样时刻和终态分类测试改为验证实际 streaming 输出。冻结输入、完整母群、cache generation 及终态 manifest 的身份校验
均有实际消费者，本次保留；未执行商业求解，不新增物理或资格结论。

selected-source 人口数量只由 prepare 生成的 state-SHA 绑定 receipt 派生；runtime 验证 receipt 的来源、
数量和区分大小写的 selector，并复核原 state 字节身份，不再为相同 state 另起 Python 计数和临时 JSON。
launched-source CSV 计数仍保留。adapter 的源合同/上游设计路径与 SHA 检查统一由紧接的 runtime resolver
执行；runner 冻结输入副本及其身份校验继续保留。单飞路径每次解析省一次 selected-state 扫描、一次 Python
进程及一次临时 JSON 写读删除；标准 adapter+runner 路径共省两套，分段三阶段路径共省五套。

阶段资源限额在冻结并校验原始 engineering budget 后直接以内存 limits 对象传给进程与容量边界，
不再另写 `resolved_resource_budget__<stage>.json` 或为该派生副本计算、登记 SHA。原始 run-local budget、
其 source identity 与 PA cache policy 继续冻结，实际进程限额由各次 usage 的完整 limits 记录。
共享启动器消费公共调度器冻结的单进程CPU下限；依赖发布经既有binding刷新器更新，未改变集成物理输入或资格。

分域选择直接消费冻结 connection/provider 的间隙、端区跨度与终端厚度，不再另写无人读取的
`domain_split_runtime_contract.json` 或维护只为该副本设置的 `required_pa_roles`。实际分域模式、
IOB角色与优先级仍由现有构建、Program receipt及其行为回归核验。

## 当前资格与有效证据

| 范围 | 当前判定 | 证据与限制 |
|---|---|---|
| 单粒子分域路径、restart与局部缺陷修复 | 已有专项功能证据 | [历史索引](HISTORY.md)，不证明统计、场收敛或八臂完成 |
| 旧零场／旧细域孔径比较 | 仅历史诊断 | 几何、电势或上游细域改变后，不能复用其handoff与当前结果混表 |
| 9月11日第一组三链对照 | 物理资格失效 | RF对象作用域错误导致脉冲前RF未更新；匹配的检测数字也不能恢复资格 |
| 修复RF后的第二组三链对照 | 对照失败 | pre-pulse IOB优先级与continuous不一致，producer状态集合不闭合 |
| 当前修复后的方形h100 | 仍需重跑闭合 | 重建pre-pulse证据，再派生post-pulse与同钟continuous；不重复refine相同family |
| 圆形四孔径与完整八臂 | 未完成 | 缺当前场family及完整三阶段证据，不宣称孔径优劣或分辨率提升 |
| Formal与跨求解器等价 | 本轮无新增资格 | 不能由局部命中、单点峰宽或文档整理取得 |

两组三链的精确run身份、数字、失败原因及整治前叙述保留在
[失效对照与文档快照](history/20260911__single-flight-documentation-and-invalidated-comparisons.md)。本页依据已有源码及记录收窄冲突声明，
没有重新核验全部外部manifest。运行前核对所用修订、冻结输入和对应验证收据；文档中的实现描述、
工作区文件存在或代码已提交均不能单独证明该入口已通过真实运行或取得物理资格。

单飞运行从冻结的 `resolved_population_contract.json` 经既有 Python 校验后直接接收 stdout 投影，
不再另存 `resolved_single_flight_population.json` 或把其作为下游存在标记。family parent 的成功/失败
manifest 直接调用现有公共 writer，保留原有输入、输出和状态语义，省去 Python 子进程运输。

## 限制与判定边界

完整母群分母始终保留。post-pulse条件群的检测率不能代替母群传输，少量命中不能证明峰宽优劣。
离散检测/损失一致、脉冲状态一致、轨迹数值等价与场收敛分别验证；一次PASS不能覆盖其他层级。
修复后的四槽pre-pulse必须与continuous保持同一PA角色优先级；所有旧数字只在对应冻结实现下解释。

来源快照只证明实际记录的依赖身份；尚不宣称全部Python运行与工作树彻底隔离。
恢复只能消费核验过的来源，建立新run；外部输入缺失、源或时钟不一致时不能凭历史文件名猜测。

## 开放任务

| 动作 | 进入条件 | 关闭条件 |
|---|---|---|
| 方形h100修复后全链对照 | RF作用域与IOB角色修复已通过相称静态回归 | 新pre/post/continuous冻结同母群、时钟和场；状态/终态与误差判据独立核验 |
| 完成其余方形并扩展圆形 | 前一阶段完整且缓存来源可核验 | 八臂完成，发布完整母群比较与不确定度，不使用共同命中子群 |
| 分域与整体场比较 | 同几何、源、电压、时刻和数值预算 | 电势/场交接及配对粒子差异满足预登记判据 |
| 扩充跨工具路径preflight | 使用已有公共短路径和run package机制 | 各入口声明深层路径与实测限制；PA完整性错误不混同MAX_PATH |

既有SIMION只读standalone长PA输入已由[公共参考](../../../docs/SIMION_REFERENCE.md#长pa输入路径)闭合，
不再列为待开发能力。原生family仅在一次性构建staging中操作，运行消费已发布standalone表示；
具体输入边界按该公共参考核对。尚未迁移的入口不能沿用旧family物化步骤启动供应商进程。
跨工具preflight待办不代表公共长路径能力尚未实现。
