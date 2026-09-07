# RF 多极杆—单反射 oaTOF 集成

本目录定义从 RF 多极杆交接状态到单反射 oaTOF 单飞运行的活动集成边界。它是当前架构入口，不记录
历史性能叙事、已退役 campaign 或逐次调试结论；这些材料位于 [`HISTORY.md`](HISTORY.md)。
参数的唯一 authority、消费者和失效域见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

## 所有权与入口

- 多极杆项目拥有杆内几何、RF 驱动与经过其作用后的 `handoff` 状态；离子源只发布冻结的粒子相空间快照，oaTOF 项目拥有下游几何、脉冲和分析。后续运行器只消费该统一粒子表，不依赖其是体积源、平面源还是历史外部表的生成方式。
- 本集成只拥有跨组件状态绑定、活动 campaign 的生命周期、单飞适配与运行证据链。
- 加速器独立理论和部件构建由 `orthogonal_accelerator` 项目提供；oaTOF 继续拥有整机布局、反射器耦合和原 Formal 资产。`family_runtime_dependencies.json` 显式声明新项目的源码与组件合同，COMSOL 保留 oaTOF 参数适配器，SIMION 两区构建器及两／三区分段 CSG 直接引用新项目。各 staged 消费者按原依赖机制冻结源码；single-flight 额外冻结其实际声明的加速器 provider 源文件和精确依赖 `common/simion/gem_primitives.py`，并在输入生成后复核源 SHA。该快照是来源证据，不宣称 single-flight 的全部 Python 执行已经与工作树隔离；已运行的冻结包、科学数值及脉冲时序不改写。
- [`workflows/family_source_closure/prepare.py`](../workflows/family_source_closure/prepare.py) 只准备并验证已授权输入；
  [`execute.ps1`](../workflows/family_source_closure/execute.ps1) 只执行生命周期注册表明确允许的 campaign。
  未注册、退役或历史 campaign 必须失败关闭。
- [`runtime/run_single_flight.ps1`](../runtime/run_single_flight.ps1) 是单飞 SIMION 的唯一运行入口；项目或分析脚本
  不得复制其 PA cache、FLY2、粒子重编号或资源预算实现。
- 在启动带电场的 post-pulse 或连续全流程孔径扫描前，
  [`runtime/verify_single_flight_pa_cache_readiness.py`](../runtime/verify_single_flight_pa_cache_readiness.py)
  只读检查带场 campaign 中显式解析 execution profile 的八个 shape×aperture row、current cache generation、局部 PA 对主 PA 的
  Dirichlet/replacement 绑定及所需 PA family 成员；默认报告全部缺口为 warning，`--require-ready` 才因
  带电场运行不能安全开始而失败关闭。continuous pre-pulse 也解析同一个带场 execution profile，复用
  main family 的缓存身份与入口 local family；运行时不 materialize 约 300 mm 的 main payload，但 local 的
  Dirichlet 来源仍必须绑定该 main cache。该检查不读取或哈希 PA 二进制，也不启动 SIMION。

已冻结的单飞 campaign 默认执行`particle_flight`。仅 C3 的
`program_axis_field_export`可替代它：该模式仍由同一入口构建五实例 PA/IOB、
复现冻结脉冲后的电压并导出总轴场。它对每个采样点按冻结 Program 的`instance_adjust`边界先选择实际 PA，
再将该 PA 的冻结 post-pulse electrode table 显式传给 SIMION 的`instance:field_wc`/`potential_wc` API；
不得把重叠 PA 场相加。
它不启动粒子、不会产生批处理或粒子物理结论；它要求一个
冻结三区 Candidate，且只可作为独立轴场积分器的输入。
compact handoff 后继发布入口可显式选择 `--execution-mode program_axis_field_export`，默认仍为
`particle_flight`。PA+ 导出仅传 mode 编号；普通 PA 才传物理电极编号，避免六 mode 投影后把已移除的
杆编号重新混入查询表。理论 CSV 仍止于出口；出口至主 PA 下游边界的逐网格电势另记于日志，
不把这层诊断样本混入理论比较区间。独立查询与 Fly 内查询均使用官方支持的接口，Fly 中返回 nil
不构成“回调禁止查询”的证据；出口势垒修复的真实对照见下文。
同一后继发布入口接受互斥的 `--compact-receipt` 或 `--materialization-manifest`：前者消费紧凑
handoff，后者消费已经发布的单时刻 restart；均保留原状态、源ID与母群分母，派生当前主域配置和
脉宽策略。复用冻结数据不意味着旧上游实现与当前实现等价；固定窗口与自然全程 pulse 搜索、不同
时间网格或未验证的碰撞域变化不得混为孔径控制变量比较。manifest记录实际消费的证据角色。

源分布加权的受约束到达时间聚焦候选池也可走同一单飞入口；每一项必须保留同一候选池请求哈希、
候选 ID 和完整母cohort。runtime只核验其物理身份与派生几何的一致性，绝不在此处读取峰宽、传输
或选择结果；加权/未加权的选择仍由项目侧的 detector-blind 分析合同完成。

这条实现依据 SIMION 官方 Multiple PAs 文档（2026-08-26检索，适用 API 从8.1起）：粒子只看包含该点的
最高优先级电静 PA，`instance:field_wc(..., voltage_table)`可显式复现`fast_adjust`的电压表；本机SIMION 2020
自带`bradbury_nielsen_grid`例程实际使用相同的兼容 API。Program的`instance_adjust`可抑制原始最高优先级 PA，
因此导出器必须重放其空间谓词，不能仅读取静态 IOB 优先级。
官方 Field I/O 文档同时明确`wb:efield`/`wb:epotential`会忽略时变`efield_adjust`，故不能作为该独立参考。
来源：[Multiple PAs](https://simion.com/info/multiple_pas.html)、[Field I/O](https://simion.com/info/field_io.html)。

## 运行边界

商业求解器默认按 campaign 串行调度。粒子相互独立、无碰撞、无空间电荷且 campaign 显式授权时，单个
SIMION 运行可调用共享批处理；批内结果必须恢复全局粒子 ID 并合并为一个来源 run。不得在外层 campaign
并发之上再启动嵌套并发。

连接器是集成拥有的固定接地屏蔽续段：其截面必须继承上游多极杆屏蔽，而不是另行指定半径、法兰或缩径。
当且仅当`gap > 0`，连接器入口生成一块接地圆盘；圆盘外半径等于连接器内半径，孔可在活动连接器合同中
选择圆形半径或矩形宽高。方形加速器的`gap = 0`是多极杆屏蔽端面直接对接加速器屏蔽开口，连接器、套筒和
带孔端板均不存在。圆形加速器则使用具名的`grounded_circular_to_cylindrical_sideport_v1`：零长度套筒的
带孔接地 collar 从已注册的对接平面开始，并在圆壳的**当前派生壁厚**内与其正体积重叠（当前几何为
4 mm，但 collar 厚度直接绑定`accelerator_shield_wall`）；它是下游圆形侧口几何，
不是零 gap 连接器。该 collar 的唯一孔仍由 1.0 mm × 受控高度的矩形 aperture 合同定义。加速器屏蔽的
矩形开口不能反向定义上游连接器端板孔，也不能以旧源端孔径约束。
当扫描高度为 0.9、1.5、2.0 与 2.5 mm 时，前端 PA 的加速方向网格必须为 0.1 mm 或更细，使各高度均为
整数个轴向单元；`frontend_acceleration_z010_accelerator_two_local_z005`保留现有的两处 0.05 mm 局部三区
场覆盖，并只改变前端的轴向离散。0.2 mm 前端网格产生的相同行不得作为这些标称孔高的比较证据。

### 长 gap 的分域 PA 路径

`gap = 0`继续使用整体前端 PA 路径：多极杆端面直接接到加速器屏蔽开口，不能因为引入分域能力而改变
这一已验证几何或场边界。`gap > 0`的长连接器可使用统一分域路径，以避免让一个高分辨率 PA 同时覆盖
长的连接器方向跨度和 300 mm 加速器轴向跨度：

- 当前受控初值是连接器总长至少 50 mm；上游细域止于带孔端板后 10 mm，主加速器细域从加速器小孔向
  连接器内延伸 10 mm。因此最短合格连接器留下 30 mm 的粗网格接地套筒，而不是细域重叠区。该数值是
  带 1.5 mm 孔接地端板的屏蔽初始约定，不是“场为零”的宣称；
  小于 50 mm 的正 gap 不得伪造分域结果，仍走整体路径。
- 上游 PA 只含多极杆、接地连接器端板/套筒和加速器入口的局部接地屏蔽；独立主 PA 含完整三区加速器主体，
  第二栅直接由主 PA 的 0.1 mm 轴向网格表达，不再建立 intermediate2 精细 overlay。四个实际孔径由入口局部
  替换 PA 表达；
  粗全局 PA 的孔光栅化不具有权威性，不因主体 PA 分离而改变。
- 两段细域不在连接器中重叠、不“拼接”、不把场值相加；中段由同一个粗 bridge PA 覆盖。粗 PA 采用
  `1.0 × 1.0 × 1.0 mm` 网格，仅为细 PA 提供远端 electrode-basis Dirichlet 边界；每个
  细 PA 在 refine 前获得其全部电极基底的边界值。SIMION 的优先级只用于让细 PA 替换背景粗 PA，绝不允许
  两个实例的 field 或 potential 相加为总场。
- 20 环、300 mm 的孔径扫描固定主 PA 与其粗 Dirichlet 边界为同一 `1.0 mm × 1.0 mm` 参考孔；所有
  1.0/1.5/2.0/2.5 mm 的实际开口一律由入口局部替换 PA 完整表达。因缺少局部 PA 会把参考孔误作物理孔，
  所以带电场的完整飞行、handoff 后飞行与 continuous pre-pulse 对此失败关闭。pre-pulse 以实际孔径的
  入口 local PA 覆盖零场第一区碰撞载体；不 materialize 约 300 mm 的主 PA，但必须复用其 cache 身份及由它
  建成的 local family，不允许另建旧 0.25 mm pre-pulse 场合同。
- 完整母群的八臂连续全流程固定使用
  `frontend_xy025_z010_coarse100_full_bore_main_local_xy050_z010`；其主域和入口局部域均为
  0.5 × 0.5 × 0.1 mm，而上游细域保持 0.25 × 0.25 × 0.1 mm；主域是
  `full_accelerator_v1`，不能退回仅覆盖横向核心的 `coarse_boundary_supported_full_axial_core_v1`。后者只可
  用于明确声明横向包络已被其覆盖的诊断，不能代表体积源完整母群。
- 连续全程 IOB 使用七个真实实例，并按重叠场优先级排布：`1=飞行管`、`2=粗 bridge`、
  `3=主加速器细 PA`、`4=上游细 PA`、`5=反射器`、`6=入口局部替换 PA`、`7=探测器`。槽号不是
  轴向物理顺序；SIMION 在重叠处采用较高实例号，因此宽范围飞行管必须低于粗域，粗域必须低于两个
  互不重叠的细域，slot 6 又必须高于主 PA 以完整替换参考孔局部。不得保留空槽或以 intermediate2
  overlay 占用该位置。
- handoff 后的 post-pulse IOB 只连续保留五个真实实例：`1=飞行管`、`2=反射器`、`3=主加速器`、
  `4=探测器`、`5=入口局部替换 PA`。该顺序与实际 builder 和 Program 一致；不能按正文列举顺序猜槽号。
  运行器连上游细 PA、粗 bridge PA 的缓存构建与运行目录 materialization 都跳过；它只从冻结
  frontend identity 派生主 PA cache key。若所需主 PA 缓存尚不存在，必须先走上游/pre-pulse 链构建，
  而不能在 post-pulse 中用零边界或重建替代。
- 分域实现只有在验收后才能替换整体路径：在每个交接面报告电势连续性和法向电场跳变，并用相同的冻结
  电压、粒子 ID、脉冲时刻和完整母 cohort 做整体 PA 与分域 PA 的配对粒子比较。验收至少覆盖到达时间、
  命中/损失分类和入口附近轨迹；仅有 PA refine 成功、边界电势相等或峰宽单值改善均不足以证明可替代。

`gap > 0`的分域拓扑现已由同一冻结 bridge contract 驱动 IOB、Program、cache 和 manifest；最小五实例
post-pulse IOB 已在真实 SIMION N=1 贯通（`20260902_192456__sim__cross__ideal-acceptance-300mm-sq-post-pulse-smoke-n1-v2__n1`，
单粒子到达探测器），但该结果仅关闭链路功能，不构成统计或场精度结论。主加速器细 PA 与入口局部替换 PA 使用同一个 PA+ 解空间：
现有三区 Program 已将 20 个环的电压定义为四个区端平面电压之间的线性插值，因此只构建 8 个独立 mode
（八极杆的共模/差模、四个三区端点及两个入口电极），而不是为八根杆和每个已从属的环重复构建
physical-electrode basis。每个
mode 的 Dirichlet 边界由六个互不重叠的外表面循环从其源 basis 线性投影写入，且不再逐点读回校验；随后
完全采用 SIMION 官方默认 refine 收敛。不以“接地面”为捷径，因为任一独立 mode 的远端 Dirichlet 值都可能非零。
组合前，运行器以原 `.pa#` 为物理电极权威，对运行副本的 PA+ basis 恢复六面边界标记：仅清除
原几何非电极而 basis 为电极的合成 Dirichlet 标记，保留真实电极和已求解电势，不再 refine。
此操作通过官方 `pa:electrode(x,y,z,false)` 完成（SIMION2020 自带
`examples/magnetic_potential/current_sphere_3dp.lua`，2026-09-04 查阅）；只修改普通复制的运行文件，
不改 cache generation。逐 mode 修改数与策略写入 `*_boundary_mask_restoration.json`，与来源缓存身份
共同说明运行副本并非原缓存字节。零场 pre-pulse 不执行此操作。真实场对照已确认出口后
0.1 mm 的虚假势垒从约7314.945 V消失至约0 V，3001点内部轴线CSV逐字节不变；
同源N=1已正常通过焦面和反射器并返回，最终横向漂移后撞飞行管端壁，探测器仍为0/1。
这关闭出口异常反弹，不证明母群探测效率或分辨率；
[完整对照与CLOC](history/20260904__pa-plus-boundary-mask-recovery.md)记录范围。
PA+ family 将八根杆的严格共同/交替差分电压子空间压缩为两个 rod mode，并保留四个三区端点与两个入口
电极的独立 mode，因此完整 family 为 8 mode；其 `three_zone_linear_ring_octupole_symmetry_pa_plus_v2` 内容身份
与原 14-mode generation 不同，旧 generation 保持只读可追溯。post-pulse Program 虽只施加其中六个非杆 mode 的电压，SIMION 2020 的已 refine PA+ 控制器仍会在
`fast_adjust` 时打开它创建时所登记的完整 solution-array family；因此运行器必须 materialize 已冻结的全 8-mode
family，再由 Program 选择六个物理有效 mode。不得为“只复制六个文件”重写 PA+ 控制器：那会令 SIMION 重新 refine
一个新的 solution family，既不节省总求解工作，也违反 PA 不重复 refine 的复用约束。
完整磁盘 family 不等于全部 mode 常驻内存。初始化使用官方 `pa:fast_adjust()` 从磁盘组合已有解；
随后 `segment.fast_adjust` 仅写当前实际驱动的 mode，SIMION 才会把这些解保留在内存。
依据为 [RAM and Memory](https://simion.com/info/ram_and_memory.html) 的 fast-adjust 内存说明
（2026-09-04 查阅，所述 API 自 SIMION 8.1 支持，适用于本机 SIMION 2020）。
因此资源画像必须区分电压加载策略：同为五实例 IOB，旧全 14-mode 动态驱动的峰值不能用于
`pre_pulse_restart_zero_rod_modes_v1` 的六 mode 驱动。既有 14-mode 画像实测峰值为
36,420,456,448 bytes（33.919 GiB），不能把加安全系数后的十进制 GB 数字写作 GiB。
当前同缓存六-mode N=1（`20260904_105816__sim__simion__rf-oatof-single-flight-gap102p4__n1`）
已完成真实飞行，墙钟 26.242 s、观测峰值 16.18 GiB。粒子穿过三区并进入反射器，但探测器命中为 0/1，
不能作为整条物理链贯通证据。其冻结脉宽为 1 us；由相同初态和 Candidate 场调用现有三区精确飞行公式，
持续开启到加速器出口需 5.998658 us，理想出口总能量为 1998.853533 eV，而实际为 525.855970 eV。
该旧脉宽负结果已由下述持续时间策略复验；不得挑选命中粒子代替同源检查。
新的 handoff 后继编译器声明 `frozen_restart_ideal_focus_envelope_v1` 持续时间策略：所有冻结 restart 行的
实际 z、带符号 vz、逐粒子质量和电荷共同进入现有三区精确时间公式，取到已冻结 accelerator focus 平面的
最长时间作为脉宽，并保留作者 `pulse_width_us` 作为不缩短的下限。focus 与出口之间的已设计漂移段提供
明确的关断观察位置，不添加任意安全倍数。该策略在所有 schedule 来源分支汇合后执行，只替换消费者
持续时间，不改变 producer 脉冲起点、canonical clock、源状态或母群分母；派生输入与结果记录在 schedule
的 `pulse_duration_derivation`。它仅是理想场持续时间估计，不保证真实边缘场中的全体粒子已退出，必须用
同一冻结粒子复验。第一区之外或理想回转会撞 repeller 的状态不能套用该公式，明确报告而不静默删行。
相同 ID 46 已恢复约1998.853677 eV出口能量；其出口虚假势垒已按上述边界标记修复并经同源飞行复验。
[持续时间阶段证据](history/20260904__post-pulse-duration-n1.md)保留修复前负结果。
下一步核对方形完整母群与可复用handoff，再推进孔径扫描；N=1的0/1损失不能用于母群效率推断。
已复用历史h100自然碰壁母群的50粒子handoff完成条件post-pulse飞行（145.105s，无refine）。
restart在官方initialize回调按冻结行恢复三维速度；全部50条实际释放状态的位置、速度、时钟和
公共重算能量误差均为0，分析发布通过，未放宽容差。数值detector标记的前向误截获及回程
分类现已同源复验修复：40粒子全部完成反射返回（此前36），4粒子真正回程命中；无refine。
该历史条件群仅4个命中，不支持分辨率统计或当前八孔径效率比较；下一步统一当前完整母群
与八孔径的上游/pulse合同，再进行连续对照。[回程标记复验](history/20260904__return-detector-marker-validation.md)
保留前向误计的根因、修复方法和同粒子结局，Formal冻结资产未修改。
当前矩阵已找到9月3日四方形及圆形1mm的同母群自然轨迹；方形1mm已从其30粒子handoff完成
post-pulse，25个反射返回、6个回程命中（母分母5000），主/入口局部PA全部复用。
方形1.5mm的39粒子后继也已完成，31个反射返回、7个回程命中；主PA复用，只补建小入口PA。
1.0/1.5mm源的z全宽5.920/6.319mm均超过4mm，不能以较小P95−P05替代接受度判据；
仅6/7个命中不足以确认分辨率改善。[1.5mm与1mm比较](history/20260904__square-h150-handoff-comparison.md)
保存k与各阶残差。方形2.0/2.5的49/56粒子后继现已完成，各5个命中，主PA均复用；
但同ID审查发现，孔径逐级扩大时部分共有粒子的冻结速度改变超过3000m/s，差异已存在于旧handoff，
并非本轮restart引入。官方Python PA接口已读回原h100零场入口PA：实体点实际为9/10/11V，
真空为0V；构建仅gem2pa、运行又跳过slot3调压，故零场声明不成立。当前孔径矩阵仅保留为缺陷诊断，
暂停性能结论及圆形扩展；生成器已对入口碰撞域和连接器碰撞域显式使用e(0)、保留碰撞标记，
组合138项测试通过；新PA中央面110316点均为0V，逐点实体标记不变。
修正后同ID61的1.0/1.5mm自然飞行均成功发布，4299条轨迹逐字节一致且正常撞壁；
旧1mm在比较时刻约2438m/s的异常vz恢复为25.579m/s。这关闭该成员的伪电势缺陷复现，
不恢复旧母群矩阵资格；仍须重建受影响的pre-pulse/handoff，并由新群计算pulse时刻。
带场300mm主PA不因该缺陷而重建。
归零后的方形1mm、5000粒子Fly已完成，观测数据选择的pulse为91.75us，29粒子handoff的z全宽
2.6154mm；compact父发布缺陷已由新analysis重放闭合，原failed父run只读保留。
终态审计发现4597个碰撞回调及403个只有最后存活观测的粒子；后者位于PA覆盖出口，
不得误判为碰撞。每粒子一行的真实终态或最后观测已恢复，5000行仅862808 bytes，
handoff和pulse选择文件逐字节不变；物理终态census.complete仍为false。
自然pre-pulse现在从冻结schema-v7 trace policy派生启用SIMION全局回调，在PA外继续原生RF时间格
观测，直到Workbench原生结束；不在首次离域时强制splat，不新增PA或改场。
PA外原生终止单列`outside_pa_termination`，不归为碰壁；`complete`只表示全部母粒子的终止事件
已被观测，不表示全部碰壁。ID61真实N=1复验4299行轨迹与全局回调启用前逐字节一致。
同一5000母群的补算已完成，父子manifest均success并复核通过：4597个几何碰撞、403个PA外
原生终止、未知0。与原观测相比，4597个碰撞终态及29个选中粒子速度不变，但pulse由91.75us
变为89.4772727273us。旧排序的横向bore人数和质心/展宽使用全部alive，故新增域外观测会影响
排序；两次选中29个ID相同不等于时刻或handoff状态相同。该结果仅完成观测闭合，不证明时刻最优。
用户已要求改进选时；旧排序派生的post-pulse未启动，新后继应消费下述已复验的新handoff。

改进的捕获目标按严格优先级处理：先最大化第一区可提取人数，再最小化这些粒子的归一化三维
RMS展宽，再最小化其质心到第一区中心的归一化距离，完全并列取较早时刻。只比较完整eligible群，
不丢弃离群粒子、不使用detector结果、不以ballistic seed决定并列。归一化来自第一区机械几何：
x/y为bore半宽或半径，z为repeller到第一栅网距离的一半；旧provisional source-region窗口只作
诊断，不再作为捕获评分尺度。圆形bore使用径向范围，不能按外接方形纳入角部粒子。
该策略已完成合同、两条selector、compact收据及同母群N=5000真实复验：仍是相同29粒子，
pulse为72.9318181818us，归一化三维RMS展宽下降25.60%，z全宽由2.49135降至1.58826mm。
母源、初态、映射和5000终态CSV逐字节不变；没有refine。代价是质心更偏离中心，最靠入口粒子
距bore边界仅约0.00812mm，三次拟合后随机残差RMS也由0.000997811增至0.001561248mm/us。
因此只接受“同人数、空间更集中”，不宣称提取更好或分辨率更高，不加任意安全裕量或删粒子。
该新handoff的方形1mm后继 `20260904_152231__sim__simion__rf-oatof-single-flight-gap102p4__n29`
已完成：29粒子通过第一栅、28粒子完成反射返回、19粒子回程命中；完整母群传输率为19/5000（0.38%），
而非条件群19/29。释放位置、速度、时钟和能量误差均为0；实际IOB为五个连续实例，PA缓存复用、无refine。
直接质量FWHM为1.20604Da，R为82.916，1000次bootstrap的95%区间为[70.541,172.510]；
仅19命中使峰宽不确定性很大，不构成统计资格或相对旧选时的性能优势。
复核发现该run终态表的旧`terminal_elapsed_us`混用了detector局部时间与撞壁全局时间；
checkpoint的canonical时间和上述峰宽不受影响。分析器现改为显式instrument与pulse-relative两个字段，
成功run可通过现有分析CLI的`--published-analysis-run-dir`发布独立重分析，绑定原始日志、输入、
时刻、容差及诊断profile，冻结新分析代码；不覆盖原run、不启动求解器。56项分析测试通过。
`20260904_155037__analysis__python__terminal-clock-reanalysis__n29` 已从原日志发布并复核，
29个终态时钟闭合，census、transmission、峰值及bootstrap与原summary完全相同。
之前154843重分析误带两个非原始profile而未输出峰值，保留为不同诊断选项的记录，不作对等证据；
新入口已拒绝这种profile漂移。
完整选时比较和CLOC见[人数优先与集中度复验](history/20260904__eligible-pulse-concentration.md)。
当前归零矩阵的方形1.5mm预脉冲也已完成（`20260904_153649__sim__simion__rf-oatof-single-flight-gap102p4__n5000`），
父子manifest复核通过、三套pre-pulse PA全部cache hit、无refine。与1mm使用逐字节相同的母源/初态/ID映射，
同在72.9318181818us选中38/5000粒子；z全宽2.166392mm、k=0.035696807/us，线性/二次/三次残差RMS分别
为0.001900913/0.001896557/0.001895686mm/us。相对1mm捕获增加31.03%，但展宽和残差均增加，
不能把捕获增益当成探测增益。两臂完整母群源诊断已发布为
`20260904_154637__analysis__python__square-h100-h150-compact-prepulse`。
38粒子的下游 `20260904_155628__sim__simion__rf-oatof-single-flight-gap102p4__n38` 已完成并复核父子manifest：
38通过第一栅、37通过第二栅、36完成反射返回、23回程检测；母群传输23/5000（0.46%）。
直接质量FWHM1.444090Da、R69.247761，bootstrap95%区间[56.206984,129.566910]；
相对1mm的19检测/0.38%出现命中增多但峰变宽的趋势，仅19/23命中及宽区间不支持稳定优劣结论。
38条restart位置、速度、时钟和能量误差全为0，主PA与1mm同一cache generation，局部PA实际1×1.5mm并最高优先级覆盖。
所有PA复用、无refine；真实飞行161.733s，波次163.842s。主机租约已释放。
独立源复核确认1mm的29 IDs为1.5mm的38 IDs严格子集，同pulse下公共29完整handoff行逐值相同；
新增9粒子原先撞入口，扩大孔后通过。完整终态总分类仍为4597碰撞/403域外终止，但12粒终点改变，
故自然终止分类总数不变不等于pulse捕获率不变；未按公共子集重算性能。
连续对照author/prepare现已接入v2 compact authority：当前稳定入口
[`square_h100_handoff_continuous_control_n5000.json`](../config/explorations/square_h100_handoff_continuous_control_n5000.json)
绑定恢复后 pre 父 `20260904_172457`、完整5000母表及成功 post 父 `20260904_173401` 的冻结时刻
72.88636363636364us、脉宽6.718280132082808us和场配置，直接生成 ready-verified schedule，不重新选时。
恢复范围的独立 Python 报告为 `20260904_174100__analysis__python__square-h100-restored-upstream-prepulse__n5000` 与
`20260904_174120__analysis__python__square-h100-restored-upstream-postpulse__n5000`；后者仅报告35/5000检测、
FWHM171.3429513ns、R78.2634644及其不确定性，不构成连续全流程对照。
连续真实飞行尚未执行：旧主缓存14-mode历史峰值33.92GiB不能用于新的8-mode family，也不能套用
6-mode post-pulse的16.15GiB画像；新增上游后的内存可容纳性仍须在新family refine后实测，不能把配置校验或
post-pulse结果当作handoff误差验证。
两臂完整母群post-pulse比较已发布并验证manifest：
`20260904_162039__analysis__python__square-h100-h150-mother-cohort-comparison`。
分区为未入选pulse、入选后检测、入选后损失；未入选者的零场自然未来终态仅作诊断，不充当pulse-on损失。
方形2.0mm的 `20260904_160822__sim__simion__rf-oatof-single-flight-gap102p4__n5000` 已完成且父子manifest通过：
同5000母源、同72.9318181818us选中46粒，包含1.5mm全部38粒且公共状态逐值相同；
z全宽2.509061mm、k=0.035098601/us，线性/二次/三次残差RMS为0.001895488/0.001889552/0.001826216mm/us。
完整自然终态仍为4597几何碰撞与403域外终止。三臂源诊断已发布并验证manifest：
`20260904_162115__analysis__python__square-three-aperture-compact-prepulse`；尚非八臂完整矩阵。
2.0mm后继 `20260904_161926__sim__simion__rf-oatof-single-flight-gap102p4__n46` 已完成且父子manifest通过：
30/46检测，完整母群30/5000（0.60%）；直接质量FWHM1.869682Da、R53.485035，
1000次bootstrap的95%区间[43.722853,95.414266]。真实飞行178.133s，波次179.194s，租约已释放。
三臂完整母群比较已发布为 `20260904_162615__analysis__python__square-three-aperture-mother-cohort-comparison`；
检测增多与峰变宽仅为当前小命中样本的探索趋势，不声明分辨率优劣或八臂完成。
方形2.5mm pre-pulse `20260904_162717__sim__simion__rf-oatof-single-flight-gap102p4__n5000` 已完成，
父子manifest验证通过；同一pulse选中53/5000粒子，包含2.0mm全部46粒且公共状态逐字段相同。
z全宽3.361384mm，线性k=0.035557072/us；四方形源诊断已发布并验证manifest：
`20260904_163720__analysis__python__square-pre-pulse-aperture-comparison__n5000`。
四孔径均满足当前4mm全宽阈值，但这是detector-blind源接受诊断，不等于检测率或分辨率通过。
2.5mm后继 `20260904_163737__sim__simion__rf-oatof-single-flight-gap102p4__n53` 已完成，父子manifest通过：
检测33/53，即完整母群33/5000（0.66%）；直接质量FWHM2.050140Da、R48.777154，
1000次bootstrap的95%区间[37.886339,82.076427]；真实飞行202.028s，波次204.120s，租约已释放。
四方形完整母群比较已发布且manifest复核通过：
`20260904_164420__analysis__python__square-handoff-full-flight-aperture-comparison__n5000`。
独立复核确认2.5mm的53粒restart位置/速度/时钟/能量误差为0，33检测与20主加速器实例损失闭合，
33个检测均按反射器进入、回程出口、检测顺序发生；2.0mm全部30个检测保留，额外检测844/3137/4030。
主PA与1.0mm相同cache generation，2.5mm local命中既有缓存，无refine；未以共有检测子群重算性能。
圆形当前无匹配的主/四local缓存。切换前先完成方形连续对照，避免当前容量门禁将未来仍需的方形缓存
作为非活动cache清除；成功run引用只更新最近使用顺序，不构成跨运行硬保护。
范围审查发现：已运行方形upstream fine为x=[-200.41362184380705,-190.41362184380705]mm。
进一步核对实际GEM修正了初次审计的端面解释：右端是连接器入口及端板上游面，真实4mm板体位于
[-190.41362184380705,-186.41362184380705]mm。初次“端板前6mm+板厚4mm”的解释不成立；
旧fine没有覆盖板体及板后连接器，板体由粗PA表达。旧split的terminal_end字段命名错误是这一误读的来源。
这与早先“从多极杆至端板后10mm”的范围不一致，不能把当前探索结果声明为该范围的完成证据。
用户已确认恢复覆盖完整多极杆并延伸到端板下游10mm。分域与连接器细域几何已修正，原入口DC/RF接线完整，
无需增加模式。恢复后的 N=1 父、子 manifest
`20260904_171734__sim__cross__zero-field-geometry-member61-square-h100__n1` 与
`20260904_171734__sim__simion__rf-oatof-single-flight-gap102p4__n1` 均为 `success`：真实 SIMION
detector-blind pre-pulse IOB 为连续三个实例 `coarse_frontend`、`upstream_bridge`、
`accelerator_entrance_zero_field`，并按实际端板后10mm范围构建。
该 N=1 只关闭恢复后的构建、IOB 组合与自然飞行功能；单粒子在64.1818181818us后发生几何碰撞，
不支持传输率、pulse、场精度或分辨率结论。四方形既有 post-pulse 仍保留原冻结输入，
仅代表旧端板附近细域模型。
新范围需重建受影响上游fine并重新生成pre-pulse，不得继承旧handoff冒充新几何；未变化的主/local及TOF缓存
须按实际生成身份核查复用，不因上游修正一概重建。当前冻结输入纯编译得到新fine范围
[-273.91362184380705,-176.41362184380705]mm，覆盖真实端板并向下游延伸10mm。
连接器总长含4mm板厚，中间粗域为102.4-4-10-10=78.4mm；不再使用漏减板厚的82.4mm解释。
恢复后的方形h100 N=5000 `20260904_172457` 与 post-pulse `20260904_173401` 父、子 manifest 均成功并经复核：
pre-pulse 全5000粒子终态闭合，pulse为72.8863636363636us、handoff为49粒子；粗前端、上游细域和零场入口域
均为 cache hit、无 refine。post-pulse 检测为35/5000。方形h150 pre-pulse `20260904_174511` 同样成功，
同pulse选中61/5000；其 post-pulse `20260904_175408` 成功，检测44/5000、损失17、真实飞行226.089s。
方形h200 pre-pulse `20260904_180022` 已成功，pulse同为72.88636363636364us、handoff为82/5000；
其 post-pulse `20260904_180900` 父、子 manifest 均成功，检测57/5000（1.14%）、损失25、
真实飞行287.702s。82条restart的位置、速度、时钟和能量误差均为零，57个检测的反射顺序已独立复核。
三臂恢复后 post-pulse 分析 `20260904_182020__analysis__python__square-three-aperture-restored-upstream-postpulse__n5000`
已发布并 verify PASS：h200的FWHM278.5538267ns、R48.10941415、bootstrap 95% CI
[41.73913225,76.85005730]。这只是当前新范围的3/8臂证据；新 handoff不得与旧范围混用，h250
pre-pulse `20260904_181945` 父、子 manifest 已成功并经复核：同pulse选中98/5000、z全宽
3.691752811mm，且h200的公共82条状态完全相同。四方形pre-pulse报告
`20260904_182830__analysis__python__square-four-aperture-restored-upstream-prepulse__n5000` 已 verify PASS；
h250 post-pulse `20260904_182846` 父、子 manifest 已成功并经复核：检测70/5000（1.40%）、
28个 `non_detector_splat_instance_3` 损失、真实飞行334.646s；98条restart的位置、速度、时钟和能量误差均为零，
70个检测的反射返回顺序已独立复核。四方形post-pulse比较
`20260904_183705__analysis__python__square-four-aperture-restored-upstream-postpulse__n5000` 已 verify PASS：
h250的FWHM340.2628726ns、R39.39611882、bootstrap 95% CI [34.43179147,58.37783504]。因此当前带场
post-pulse完成4/8臂。圆形h100 pre-pulse `20260904_182515` 已通过 ValidateOnly，但尚未启动solver。
连续 full-flight control 已于 `20260904_174533` 通过 ValidateOnly，但尚未运行；其内存风险及是否允许为
新的8-mode family已获一次官方默认 refine 的授权；当前仅完成合同与缓存身份接线，尚未启动构建或 refine。
连续与handoff重放的诊断由 [`compare_handoff_replay.py`](../analysis/compare_handoff_replay.py) 比较母群source ID，
而非批内行号。两侧必须提供canonical checkpoint表和Program build receipt；receipt中的`instance_roles`
直接来自生成Program的同一布局映射，损失按物理角色比较，不比较不同IOB的原生槽号。
旧receipt缺少角色图时不能猜测或回写原run，须另行形成有来源绑定的构建证据。
工具报告两侧完整检测ID集合、额外/缺失检测，以及共有检测粒子的canonical instrument/pulse-relative到达时间和
三维落点逐粒绝对差；共有粒子仅用于误差诊断，不用于重算性能。`PASS`范围只含脉冲状态与检测/损失结局，
不包含轨迹数值等价。轨迹误差预算缺失时明确`not_assessed_no_trajectory_tolerance_contract`，
不得把初始化容差用作轨迹收敛标准；双方零检测也不构成到达时间等价证据。当前只有无求解器回归，
仍须真实连续N=5000与对应post-pulse对照，不能以该工具或已有四方形结果替代。
官方依据为[SIMION FAQ全局segments](https://simion.com/info/faq.html#my-initialize-and-terminate-user-programming-segments-are-not-executed)：
接口自8.2-EA20170210提供，本机SIMION2020的本次N=1已验证可用；这是官方接口的项目接线，
不是新增物理模型或真实域外电场验证。
[紧凑发布与终态恢复](history/20260904__compact-prepulse-terminal-publication.md)保存范围及证据。
[归零修复与验证边界](history/20260904__zero-field-collision-grounding.md)记录官方语法依据及回归。
四组全宽及残差、损失和耗时见[四孔径诊断与开放疑点](history/20260904__square-four-aperture-flight-audit.md)。
圆形其余三孔仍缺当前自然轨迹；连续全流程对照与pulse确认仍未完成。
[当前矩阵与方形1mm证据](history/20260904__current-square-h100-handoff-flight.md)记录来源和后续顺序。
[初始化与复验证据](history/20260904__restart-velocity-n50-validation.md)记录该专项结果。
[来源审计与失败证据](history/20260904__frozen-handoff-n50-reuse.md)区分该历史上游配置与当前孔径矩阵。
该压缩不支持逐环任意调压；若研究逐环补偿或非线性梯度，必须声明新 voltage-control policy 并重新构建其
独立 mode family，不能复用当前 `three_zone_linear_ring_octupole_symmetry_pa_plus_v2` cache。

对于 detector-blind 的 continuous pre-pulse，运行器构建连续四实例 IOB：`1=粗前端`、`2=上游细域`、
`3=零场第一区碰撞载体`、`4=入口局部替换 PA`。slot 4 以最高优先级使用与七实例 continuous full-flight
完全相同的 active bounds、PA+ family，并在脉冲前投影入口电极 33/34 的静态 8 V；slot 3 只补足 local
边界之外的无场碰撞走廊。它不 materialize 主加速器、反射器、下游飞行管或探测器 PA，也不保留空实例。
粗前端、上游细域、主 PA cache identity 与入口 local family 均复用 full-flight 的当前
`0.5 × 0.5 × 0.1 mm` main/local profile；只有零场载体为无需 refine 的 raw PA。旧 0.25 mm pre-pulse
合同失败关闭。历史三实例 compact 结果只保留为缺失入口局部静态边缘场的缺陷证据，不能与连续全程作严格配对。
长 gap 的连续体积源默认使用合同模式 `natural_trajectory_compact_handoff_v1`，在临时执行目录中传播到实际入口碰撞几何，
保持原生 RF 时间步。完成后，紧凑扫描器流式比较 detector-blind 候选时刻，并第二遍仅提取被选中的
`pre_pulse_compact_handoff.csv`。正式产物为该 handoff、选择摘要和 receipt；逐粒子、逐原生 RF 时间格 TRACE
不发布为轨迹档案，容量治理会在扫描完成后清除它。只有合同显式声明
`natural_trajectory_native_rf_grid_v1` 与 `rebuildable_trajectory_payload`，才发布完整可重算轨迹；该模式的
大文件同样受容量治理。更换 pulse 排名算法时，默认紧凑模式需要重新执行上游 pre-pulse 传播。
SIMION 2020 没有可用的公开 Lua 实例删除接口，因此运行器冻结一个仅含三个实例的版本受控二进制种子；加载时
先用同名临时 PA 满足种子，再立即替换为上述三个真实角色。该种子只表达 Workbench 实例数，不表达电场、几何
或科学输入；最终 IOB 只序列化真实角色 PA。此轻量模式不能用于全程飞行或总轴场导出；run manifest 明确记录
模式及省略角色。
独立体积源没有可继承的多极杆 handoff pulse 时刻：其首个筛选网格由冻结母群在注册后的全局`x`位置、
出生时刻、`v_x`与实际 bore 两侧边界计算，以全母群同时位于 bore 内人数最大的交叠区作为采样范围，
并量化到该 run 的原生 RF 步。历史 handoff 的平均速度不得作为这种源的 seed。此计算只确定真实 SIMION
detector-blind screen 的采样范围；最终 pulse 仍按真实 PA 轨迹的完整母群 bore eligibility 排名，不由该弹道预测直接指定。
N=5000 预脉冲筛选及跨整体 PA 的配对验收仍是物理/性能结论的必要前提。

仓库级 [`common/simion/resource_scheduler.py`](../../../common/simion/resource_scheduler.py) 仅为已授权请求
规划 RF/静电批次：它综合粒子数、公共的每批 CPU 策略、当前可用内存、已观测的同资源身份峰值及并发上限。
资源身份还包含实际 IOB 工作负载拓扑；三实例 pre-pulse、五实例 post-pulse/轴场导出和七实例全程飞行
各自建立画像，禁止以重型链路峰值压低轻量链路的并发。
没有匹配历史时，运行器把第一个正式粒子批次作为至少45秒的资源识别批次；该进程不因观察结束而终止，
并必须自然完成，以记录穿过全部 PA 家族后的完整内存峰值；其结果直接保留。随后只对尚未执行的粒子重新
分批，并由公共调度器错峰启动、持续监控；不再生成
`RESOURCE_CALIBRATION_ONLY`探针或重复首批。
同一机制也调度已证明相互独立的静电 PA 工作项：完整边界 basis 写入后，主细域、入口局部替换 PA 和
legacy overlay 的各电极 refine 都以一个正式电极作45秒首批观测，余下电极只按公共CPU/内存准入错峰启动；basis 写入本身仍串行，
不得把它与后续 refine 混为可并发工作。
该策略属于公共调度器而非 campaign、功能或科学合同；这些合同只能提供资源身份，不得覆盖CPU、内存、
安全系数、并发或危险处置。CPU满载只暂停新启动；普通内存暂缓也只是不满足“1 GiB系统保留量加下一
进程动态峰值预算”的启动条件，条件恢复后可随时再次准入，不计尝试次数。动态峰值取每个SIMION进程
的驻留工作集与私有提交量中较大者，避免Windows暂时修剪工作集后低估下一路的内存需求。仅当可用内
存低于0.5 GiB持续15秒，执行器才逐个回收最晚启动的批次并置于待启动队列最前；这样被打断的通道会先恢复，
不会被尚未启动的平衡补偿批次插队。每次回收后必须连续45秒满足下一
条通道的1 GiB准入和动态峰值预算，才可恢复试开一个通道。至多进行两次这样的危险恢复；第三次同类
危险将失败关闭该运行，以免Windows长时间资源抖动。普通资源波动、墙钟和目录采样不终止健康进程；但
任一同波 SIMION 子进程以非零状态退出时，该波已不具备完整母cohort资格，调度器立即停止该波其余
子进程并取消待启动批次，保留原始日志供父运行记录失败原因。
探索的 inline 网格或 trajectory-quality 覆盖使用**已解析数值**而非原 profile ID 匹配画像；因此旧 profile
的峰值不会为不同离散量授权并发，新的组合由首个正式批次建立自己的观测。

运行器在把分片外部 ION 表交给 SIMION 前，以本次**最大实际分片**设置官方
`--default-num-particles` 的 IOB ion-list 容量；这不是调度器的批量上限，也不改变分片。容量超过
10,000 时只记录运行时警告，仍照原计划执行。这样不会因继承 SIMION 的默认 1,000 容量而漏读后续离子，
同时不把 50,000 一类固定容量常驻到所有运行中。

每个 run 必须冻结 `run_config.json`、`summary.json` 和 `run_manifest.json`。
终态容量检查测量并保护真实 `artifact_run_dir`，不依赖已经移除的短执行别名。
缓存只用于完全相同的冻结身份，且不可替代来源 run。v3 PA cache 在私有 staging 时逐文件全量哈希、原子发布并设为只读；普通复用只复核
当前 generation pointer、manifest、角色/键、文件清单和字节数，避免每个消费者重复读取数十 GiB 不变 PA。
发现非 current generation 与显式 artifact 审计仍执行全量字节哈希。功能成功不自动证明数值收敛、跨求解器
等价、参数最优或 Formal 资格。

哈希只用于已发布输入、来源 cohort、缓存 generation 和 immutable receipt 的身份绑定；它们证明重放时读取的
确是同一对象。作者 campaign、普通探索和资源策略不以文件哈希作为日常维护门槛：探索只在冻结输出记录实际
身份，资源不足首先暂停新工作并报告 warning，只有会覆写证据、混入不同 cohort、损坏 cache 或触及用户设定的
500 GiB 容量下限时才失败关闭。

若SIMION批次已经全部完成、但**只**在受治理的预脉冲TRACE物化步骤失败，或仍停留在该阶段前
的 durable `checkpoint` manifest，
[`recover_completed_pre_pulse_screening.py`](../workflows/family_source_closure/recover_completed_pre_pulse_screening.py)
可从 manifest-verified 原始日志建立一个新的 analysis recovery run。`checkpoint` 仅在每个 TRACE 都有
原生 `Fly completed.` 终态时可进入此路径；缺批仍必须走 batch continuation。它逐一绑定来源 manifest、原始
run-config、run-local冻结合同、粒子映射和全部批日志；不得改写失败run、不得重跑求解器，也不得把恢复结果升级为
分辨率或Formal证据。若该恢复run以`selected_pulse_handoff_only_v1`成功发布完整母表、detector-blind compact
receipt及handoff，连续全流程作者可直接把这份成功恢复manifest作为pre-pulse producer；author与prepare会共同
复核恢复receipt、未重跑求解器、原failed/interrupted/checkpoint child及compact输出身份。该复用不改变原child
终态，也不把条件handoff升级为完整母群传输、分辨率或Formal资格。

若一个或多个 SIMION 逻辑通道在预脉冲粒子飞行中断，下一次带 `__rNN` 身份的
预脉冲恢复由仓库共享的[`batch_continuation.py`](../../../common/simion/batch_continuation.py)与本项目的
[`pre_pulse_batch_continuation.py`](../runtime/pre_pulse_batch_continuation.py) TRACE适配器建立批级 continuation plan：
每个批独立核验 predecessor `failed/interrupted` manifest、run-config、冻结 time-series 合同、母源、initial-global-state、
row-map、原始 stdout SHA-256 与终态 TRACE；新 run 的上述三个 cohort 输入必须逐项同 SHA。完整批可直接导入；未完成批只能导入从该批起点开始、逐 ID 连续且无重复的终态
前缀，SIMION 只重跑其余后缀。不同通道已完成的独立粒子结果不会因为另一个通道中断而丢弃；但任一
SHA 漂移、跳号、重复/畸形 TRACE、禁止的下游事件或伪 `Fly completed` 标记都失败关闭。导入日志与
continuation plan 冻结到新的 run，旧 run 永不改写；连续多次中断时，前一轮导入日志继续由其 plan 中的
SHA-256 绑定。该机制是执行恢复，不改变45秒资源观测、通道准入、母 cohort、物理输入或统计口径。

连续全流程也使用同一共享 continuation 骨架，但以
[`full_flight_batch_continuation.py`](../runtime/full_flight_batch_continuation.py)解释其原生 stdout。
只有同时覆盖整批 `source_release`、每粒子唯一 `handoff_terminal_raw`，且最后一条非空记录是原生
`Fly completed.` 的批次才可导入；其他 `TRACE:` 辅助事件及非 TRACE stdout 原样保留，不得为恢复而裁剪
诊断证据。恢复前逐项核验同一母 cohort、canonical clock、几何/场/Program 合同以及各 PA generation key；
任何漂移都拒绝拼接。导入和重算仍写入新的 immutable run，分析器按原 batch 顺序自动合并两类 stdout。
若所有批次均已完成，新 run 可只做合并与分析而不启动 SIMION。对 `execution_pending` 动态 run，family
adapter 会跨执行时间戳搜索同一 `campaign_id`、`experiment_id` 与 `experiment_row_sha256` 的历史
`failed`/`interrupted`/`checkpoint` 父 run，再精确派生其 child；它选择最近一个确有完整 stdout 批或已绑定
continuation plan 的 child。固定 run 及 `__rNN` 也走同一发现逻辑；预脉冲恢复入口及语义保持独立不变。
runner 在首次容量清理前即把当前 canonical run 与已传入的 pre-pulse/full-flight predecessor 组成统一
protected-path 集合，并在 startup、每次 PA cache publication 及 terminal reconciliation 全程传递。前驱路径
必须是本项目 `artifacts/.../runs` 的直接子目录，且其 manifest 身份和 terminal 状态先通过轻量校验；随后仍须
通过对应 continuation planner 的完整输入、日志和哈希校验。普通非恢复 run 的集合只含当前 run，任意外部路径
不能借恢复参数绕过容量治理。
正式首批的45秒观测若把预备 batch plan 改写为自适应计划（例如500+4500），后续分析必须重新绑定该
最终计划的逐批 count，不能继续使用观测前的单批计数。若两批粒子已自然完成而后处理失败，完整的
`simion__batch*.stdout.log` 与 pre-pulse TRACE 同为失败发布可保留的恢复证据：stdout 要求位于 run-local
`logs/` 且末行匹配原生 `Fly completed.*`，manifest/checkpoint 仍逐文件绑定其 SHA。此类 checkpoint 可由
`FinalizeOnly` 建立新的 analysis recovery run，或由下一次 full-flight continuation 全批导入；两者都不重飞粒子。
`FinalizeOnly` 从失败父运行冻结的 workspace 相对路径解析作者 campaign，并在恢复父 manifest 中同时绑定
原父运行全部冻结输入、冻结 experiment、原父 manifest、恢复子 manifest 与 recovery receipt；若 `__r01`
已存在则依次选择首个未占用的 `__rNN`，绝不覆盖已生成的分析或父运行。

运行器在求解期间以及每个已完成 TRACE batch 后发布 `checkpoint` manifest：这只表示输入与已完成
原始工作可恢复，**不是**资源中断或失败。只有运行器实际退出并进入失败收尾时才将其替换为 terminal
`failed/interrupted`；正常完成并成功扫描后则先删除临时 TRACE，再替换为 `success`。若扫描或物化失败，
compact retention 只允许由 `retention_actions.json` 逐项登记、位于 run-local `logs/`、带原生完成哨兵且
字节数一致的 batch TRACE 作为恢复例外；其余大型文件照常删除。writer 与 verifier 都复核这项例外，
失败发布自身若再出错也必须保留原始扫描/物化错误。容量治理不得把 `checkpoint` 当作可清理的 interrupted run。

若子运行已经成功物化预脉冲时间序列、但父发布仅因其后的活动 exploration authoring 文件发生 SHA 漂移而失败，
`publish_run.py --pre-pulse-selection-replay-source-parent-manifest` 可建立一个新的 immutable
`analysis/python` replay run。它只读取失败父 run-local 冻结 campaign、resolved 合同和成功子 manifest，
不重跑求解器、不改写失败父 run，并且只发布探测器盲候选时刻；其声明固定为
`FUNCTIONAL_SCREEN_ONLY`，不支持 detector、resolution、optimization、Candidate 或 Formal 结论。

对于已成功的、单一冻结时刻的 `pulse_disabled` time-series，
`runtime/materialize_pre_pulse_time_series.py` 还提供 manifest-bound restart materialization：它只能把该
run 已记录的存活状态重编号为 canonical `pre_pulse_restart` 表，并逐行核对时间、ID、质量/电荷与由速度重算的
能量。receipt 同时绑定原始全母群分母及终端损失 census，因此 conditional restart 绝不能被表述为全人口传输。
它当前仅授权同源的 inherited-vs-`z-vz` working-point `DEVELOPMENT_ONLY` 复现；不得用 CSV 转换替代新的
脉冲搜索、上游传播、锁定测试或真实场源分布加权聚焦结论。

`workflows/family_source_closure/run_time_series_successor.py` 将这一物化结果与一条**预注册**的 pulse-on
消费者行绑定。它在调度前逐项拒绝 connection、layout/cross section/aperture、three-zone candidate SHA、上游
source identity 或完整 restart population 的漂移；仅允许从 producer 的 `pulse_disabled=true` 转换为 consumer 的
正常脉冲。已绑定的 materialization manifest 可直接复用；不会为同一 consumer 重写一个 receipt 不同的
等价状态。它不生成或改写 campaign；`--execute` 时仍只委托唯一的、持有主机租约的 `execute.ps1`。

活动 runtime binding v4 只冻结连接专属的物理/运行合同；共享的
`family_runtime_implementation.json` 由运行时统一解析。authorized/Formal 路径校验每个实现脚本 SHA；
exploration 仅允许实现内容与注册表漂移，并把期望与实际 SHA 写入 run config/receipt，仍关闭角色、路径、
哈希格式和所有物理/输入合同。故一次共享实现更新不再要求逐连接复制同一 implementation binding 或改写其
物理合同；新 prepared plan 仍冻结所选 binding 的原始 SHA。
归档 v2/v3 binding 仅用于历史证据读取，不是活动 authoring 输入。

三区 N=1 路径 smoke 只证明已冻结路径可贯通；其授权 receipt 绑定一个具名后继行的完整行 SHA、
科学身份、粒子顺序摘要和实际粒子数。新合同可授权任意正整数人口，旧 `N100` receipt 仍只授权其原
`N=100` 后继。两者都不构成分辨率、工程资格或 Formal 声明。

## 配置、验证与历史

活动配置位于 [`config/`](../config/)；公共 schema 和文件身份工具位于
[`common/contracts/`](../../../common/contracts/README.md)。修改活动运行器、合同、资源策略或 campaign 后，应运行
项目门禁及仓库级集成门禁。历史文档中的数字、状态和链接均不构成活动授权。

活动 campaign 只由 v7
[`rf_multipole_oatof_experiment_campaign.schema.json`](../config/schemas/rf_multipole_oatof_experiment_campaign.schema.json)
校验；它只接受最小 authored 合同。prepare 随后展开并以
[`rf_multipole_oatof_resolved_experiment_campaign.schema.json`](../config/schemas/rf_multipole_oatof_resolved_experiment_campaign.schema.json)
校验仅存在于本次冻结输出的完整行。v1–v6 的旧结构只由同目录 `archive/` 下的归档读取 schema 校验，供历史证据审阅与回归使用；
它不被执行入口、活动发现或 resolved-plan 编译器接受。

当前唯一活动 campaign 是 `connector_gap_field_matrix_compact_auto_replay_v3.json`。此前 23 个已发布的逐 gap/field
合同保留原始字节和 receipt，但已退出 lifecycle registry：它们由该 compact replay 完整替代，且不应因后续运行
policy（内存、并发、超时或保留）更新而重新成为可执行 authority。

活动单飞来源仅接受 `continuous_frontend` 与 `pre_pulse_restart`。已归档的 staged Grid2 合同及其逐粒子证据
仍可按归档索引校验，但不再是现行 schema 或运行器可重放的输入。

预脉冲时间序列可使用历史的冻结前 `N=100` 前缀，也可使用与冻结母表等长的完整有序人口；后者仍先
物化为 run-local 的确定性表，因而不会以“共同幸存粒子”替换母 cohort。所有来源损失继续由原上游
manifest 和这份完整分母共同报告。

当同一冻结母 cohort 的两个或更多 detector-blind 预脉冲 arm 均成功时，
[`publish_pre_pulse_aperture_comparison.py`](../analysis/publish_pre_pulse_aperture_comparison.py) 发布一个新的
immutable analysis run。它冻结各 arm 的 manifest、resolved config、初始母表、time-series states 与终态
census，报告完整母群分母下的传输、损失、`z--vz` 拟合/残差和加速方向 full-width。300 mm 孔径筛选将
full-width 的 4.0 mm 阈值、实测值和 pass/fail 一并写出；该 artifact 始终是
`DETECTOR_BLIND_SOURCE_ONLY`，不输出 detector peak、分辨率或 Formal 结论。
每个 arm 还必须绑定其 detector-blind pulse-timing candidate receipt，并使用该 receipt 的胜出
`sample_index` 读取 natural time-series state；自然轨迹的最后一个 sample 仅是归档终点，不能作为比较时刻。

五环 300 mm 几何的 detector-blind 筛选、连续全程失败和轴场误差均已冻结为
[`五环诊断快照`](history/20260831__five-ring-prepulse-and-field-diagnostics.md)。它们解释为何旧结构不能进入正式
全程扫描，但不构成当前方/圆、孔径或 20 环候选的结论。

当前 20 环、300 mm 三区候选仍是 `CANDIDATE_ONLY`：必须先以冻结理论合同完成总轴场导出和逐区比较，再以 N=1
贯通验证；只有两者通过，才能重启 N=5000 全程。这不是孔高扫描的负物理结论。

为避免完整细网格外壳使每个 PA mode 达到 8.86 GiB，活动物理链使用
`coarse_boundary_supported_full_axial_core_v1`：它沿完整 300 mm、20 环三区加速器轴向保留细网格，横向只保留
位于 bore 内的核心。远端环、侧壁和出口栅没有被删除，而是通过同一形状专属 1 mm 粗 PA 的逐电极 Dirichlet basis
施加在核心的六个外表面。核心 extent 由冻结数值 profile 声明，必须位于物理 bore 内并落在粗网格节点上。旧
`directed_kinematic_corridor_v1`只保留给入口诊断，不是该物理链的主 PA。这个分区不是场等价的预先声明；每个
新几何仍须以总轴场导出和 N=1 轨迹验证。

带入口局部替换 PA 的总轴场导出不需要也不得等待连续全程的七槽 seed：它使用五个连续实例
`飞行管、反射器、主加速器、探测器、入口局部 PA`，并重放 Program 的局部优先级与电压表；分域导出不传入
旧单块 `OATOF_ACCELERATOR_PA_OVERRIDE`，因此不会覆盖已装载的主 PA。它只导出静态场，
不启动粒子；连续七槽 seed 仍专用于完整母 cohort 飞行。

八个完整 full-flight arm 成功后，
[`publish_full_flight_aperture_comparison.py`](../analysis/publish_full_flight_aperture_comparison.py) 才可发布方形/圆形
与四个孔高的可比结果。它要求每臂都绑定同一完整 N=5000 母表，拒绝 restart、条件幸存群和共同命中筛选；
结果按完整母群分母报告传输及互斥损失、4 mm 入口宽度、`z--vz` 线性斜率 k、线性/二次/三次及三次拟合后
点残差、直接 detector peak 的 FWHM/分辨率、尾部和 bootstrap CI。

[`author_full_flight_campaign_from_pre_pulse.py`](../workflows/family_source_closure/author_full_flight_campaign_from_pre_pulse.py)
是该筛选后的唯一 campaign authoring 边界：它为每一个 full-flight row 绑定相应成功 producer 的既有
`pulse_timing_transition_authority`；若 producer 是合法的 pulse-disabled 筛选而尚无 transition，它只接受
manifest-bound receipt、完整连续母表和有序 ID/SHA，并把公开 pulse discovery → transition → confirmation
留给执行路径。两种情形都会在进入求解器前复核 layout、connection、Candidate、网格、场、source 与完整
有序人口。带compact post-pulse对照时，pre-pulse producer可以是普通成功父run，也可以是上述成功analysis
recovery run；两者由同一manifest-leaf解析器归一化并保持现有comparator authority格式。生成行必须继续使用
`continuous_frontend`的完整母 cohort，禁止用`pre_pulse_restart`或共同
detector-hit 人口；其唯一允许的 cache-miss 时间格是当前已登记的 native-dt 范围或与 producer 匹配的 RF40
单快照。

需要对已经冻结的完整连续 N=5000 campaign 作运行链烟测时，只能使用
[`author_continuous_functional_smoke_campaign.py`](../workflows/family_source_closure/author_continuous_functional_smoke_campaign.py)。
它固定选取冻结文件顺序的 ID 1，写出单行 N=1 continuous campaign，同时保留原 N=5000 母 cohort 的
authority、SHA 与分母；它只可写入本 integration 的 `config/explorations`，不接受运行时粒子数或 ID
覆写，也不产生 restart、传输或科学结论。
例如：`python -m integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.author_continuous_functional_smoke_campaign --source-campaign integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/explorations/square_h100_handoff_continuous_control_n5000.json --experiment-id ideal_acceptance_300mm_square_accelerator_port_h100_full_flight_n5000 --output integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/explorations/square_h100_continuous_functional_smoke_n1.json --campaign-id square_h100_continuous_functional_smoke_n1 --workspace <workspace>`。作者只接受行内已绑定的完整 N=5000 comparator，并将它投影为专用 smoke pulse authority；prepare 因而精确复用冻结起点/脉宽，状态为 `ready_verified`，不进行 N=1 pulse discovery。该现有来源仅用于功能烟测的接线；最终 N=5000 连续对照必须由新的 8-mode post-pulse producer 重新 author，不能复用该历史来源作为 8-mode 物理证据。

活动 resolved source contract 仅接受 family v2：它显式按 `comsol` 或 `simion` 记录来源 branch，且运行时只
消费所选 branch。早期 v1 source contract 与其 adapter 仅是历史证据格式，不在活动 schema 或重放入口中保留兼容分支。

实验 campaign 使用最小扁平 authoring：`experiments.shared` 声明共同控制，
`variation_axes` 列出允许变化的原生字段，`rows` 的每行只写稳定的 `experiment_id` 与 `values`。
作者文件不写顺序、派生量或 run ID：准备阶段按行顺序派生 `sequence`，实际执行时生成 run ID，随后冻结完整
resolved row、来源身份和 execution receipt。活动入口不接受 array、`sequence`、`run_id` 或 `overrides`；旧格式仅由 archive
读取。任何未声明的字段变化仍失败关闭。这样同一合同可顺序执行多个 gap 或
其他已授权参数点，而不会复制共享输入。

已发布 campaign 保持为只读历史证据；不再以旧 raw campaign SHA 或 `published_authoring_identity` 使其成为新运行的
可执行输入。对相同科学矩阵的后续运行建立新的、最小 authoring campaign 身份；prepare 为该新身份冻结 resolved row、
来源身份和 execution receipt。这样历史证据仍可审阅，而旧 run ID、行顺序和作者文件字节不再成为未来执行的参数权威。

对已注册 campaign，`execute.ps1 -AllExperiments` 按展开后的 `sequence` 逐行调用同一单实验入口；它不在
campaign 层并行商业求解器，任一行失败即停止。`PrepareOnly` 仍要求逐行显式审阅目录，避免覆盖审阅产物。

## 审查与 dry-run

公开入口可用 `execute.ps1 -ExperimentId BEFORE -SemanticDiffAgainst AFTER` 比较同一 campaign 的两条**已展开**实验行；
它内部调用 `prepare.py --semantic-diff-experiment-json`，输出稳定 JSON：
每个字段的旧/新值及其审查类别（物理/场、数值/资源、采样、资格、运行控制或证据）。这是读操作，不参与
schema 验证、cache 命中、handoff 兼容性或资格决策；这些仍由已冻结的 resolved contract 与实际执行边界决定。
只读差异允许审阅仓库内的非活动 campaign，但不接受仓库外派生 campaign，也不能与执行模式组合。
这不恢复历史输入的执行授权；`ValidateOnly`、准备和求解仍经过原生命周期与探索准入检查。
诊断目录本身不授予权限：标为 `exploration` 的 campaign 不进入活动授权注册表。
在不启动求解器的情况下，可用 `execute.ps1 -ValidateOnly` 对某一行生成并校验其完整 resolved connection 与
composition plan。

普通探索不必预先登记为活动 authority：将 repository-managed campaign 标为 `"status": "exploration"`，并显式传入
`-Exploration -ValidateOnly`、`-Exploration -PrepareOnly -OutputDirectory ...`，或在准备完可审阅合同后使用
`-Exploration -SolverAuthorized` 执行非正式模拟。该路径仍执行 schema、来源 artifact、单位/frame/clock、粒子和
composition-plan 校验；它不以活动 campaign SHA 或 source-binding 刷新拒绝新的参数组合。探索运行保留普通的缓存、
SHA、manifest 与失败记录，但不能 `FinalizeOnly`、发布正式结果或产生资格结论。

探索的粒子数没有 schema 人为上限；它必须是正整数，并与冻结 source、ordered particle IDs 和分析分母一致。
实际并发由资源调度器按粒子数、CPU 和可用内存决定，不改变 handoff 的科学身份。

下游网格、反射区 cell、trajectory quality 与每周期 RF 步数可选择任一已登记的
`single_flight_*_profile_id`。探索合同还可在
`single_flight_numerical_overrides` 中直接给出正的 `trajectory_quality`、`rf_steps_per_period`，以及
前端/overlay/reflectron 的 cell；prepare 会把最终数值冻结进 `ResolvedExecutionProfile`。这不会修改默认
profile、上游 handoff 或正式资格；正式 campaign 仍以其预登记 profile 为准。

探索若复用一个已冻结的 post-pulse restart source，仍须验证该 source 的 manifest、checkpoint、pulse schedule、
粒子身份和所声明的变化轴；但不必为了只扫描加速场 profile 而附带正式资格专用的 source `z--vz` 理论工作点。
该理论闭合仍是 active/authorized restart 的失败关闭要求。

## 开放任务

- **Windows 路径容量治理（跨工作流）**：公共 `New-RunPackage` 已为采用短 execution junction 的外部求解器
  入口生成结构化容量报告，并在创建 artifact 前以 Windows 传统 API 的 259 字符兼容上限检查 package 核心路径和调用方
  明确声明的预期相对路径；超限 fixture 给出可操作诊断。该上限是兼容性基线，不是对 SIMION、COMSOL 或 MATLAB 的
  未证实专属限制。下一步应逐入口登记深层生成输入/输出，报告其实际绝对路径与已证实的工具限制。短根只能改变进程
  看到的路径表示，不能改变 `run_id`、冻结的相对 artifact 引用、manifest 的真实目标路径、SHA 或科学身份。关闭条件是：
  在启用 Windows 与 Git 长路径支持的干净工作站上，活动 campaign 和至少一个非单飞外部工具入口通过同一公共 preflight；
  各入口不再各自创建未登记的临时 junction、复制或缩短科学/证据文件名。
