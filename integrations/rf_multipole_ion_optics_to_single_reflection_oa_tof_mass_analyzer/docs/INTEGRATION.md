# RF 多极杆—单反射 oaTOF 集成

本目录定义从 RF 多极杆交接状态到单反射 oaTOF 单飞运行的活动集成边界。它是当前架构入口，不记录
历史性能叙事、已退役 campaign 或逐次调试结论；这些材料位于 [`HISTORY.md`](HISTORY.md)。
参数的唯一 authority、消费者和失效域见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

## 所有权与入口

- 多极杆项目拥有杆内几何、RF 驱动、源粒子与 `handoff` 状态；oaTOF 项目拥有下游几何、脉冲和分析。
- 本集成只拥有跨组件状态绑定、活动 campaign 的生命周期、单飞适配与运行证据链。
- [`workflows/family_source_closure/prepare.py`](../workflows/family_source_closure/prepare.py) 只准备并验证已授权输入；
  [`execute.ps1`](../workflows/family_source_closure/execute.ps1) 只执行生命周期注册表明确允许的 campaign。
  未注册、退役或历史 campaign 必须失败关闭。
- [`runtime/run_single_flight.ps1`](../runtime/run_single_flight.ps1) 是单飞 SIMION 的唯一运行入口；项目或分析脚本
  不得复制其 PA cache、FLY2、粒子重编号或资源预算实现。

已冻结的单飞 campaign 默认执行`particle_flight`。仅 C3 的
`program_axis_field_export`可替代它：该模式仍由同一入口构建五实例 PA/IOB、
复现冻结脉冲后的电压并导出总轴场。它对每个采样点按冻结 Program 的`instance_adjust`边界先选择实际 PA，
再将该 PA 的冻结 post-pulse electrode table 显式传给 SIMION 的`instance:field_wc`/`potential_wc` API；
不得把重叠 PA 场相加。
它不启动粒子、不会产生批处理或粒子物理结论；它要求一个
冻结三区 Candidate，且只可作为独立轴场积分器的输入。

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
- 上游 PA 只含多极杆、接地连接器端板/套筒和加速器入口的局部接地屏蔽；独立主 PA 含三区加速器主体，
  仅中间零厚度栅可由 0.05 mm 小型 overlay 精化。四个矩形孔高由主加速器 PA 的 0.1 mm 轴向网格离散；
  粗全局 PA 的孔光栅化不具有权威性，不因主体 PA 分离而改变。
- 两段细域不在连接器中重叠、不“拼接”、不把场值相加；中段由同一个粗 bridge PA 覆盖。粗 PA 可采用更
  粗的网格（当前注册 `0.5 × 0.5 × 0.5 mm`），仅为细 PA 提供远端 electrode-basis Dirichlet 边界；每个
  细 PA 在 refine 前获得其全部电极基底的边界值。SIMION 的优先级只用于让细 PA 替换背景粗 PA，绝不允许
  两个实例的 field 或 potential 相加为总场。
- 分域实现只有在验收后才能替换整体路径：在每个交接面报告电势连续性和法向电场跳变，并用相同的冻结
  电压、粒子 ID、脉冲时刻和完整母 cohort 做整体 PA 与分域 PA 的配对粒子比较。验收至少覆盖到达时间、
  命中/损失分类和入口附近轨迹；仅有 PA refine 成功、边界电势相等或峰宽单值改善均不足以证明可替代。

`gap > 0`的分域拓扑现已由同一冻结 bridge contract 驱动 IOB、Program、cache 和 manifest，并已完成
真实 SIMION N=1 贯通；该 smoke 仅证明执行链可用。主加速器细 PA 的 basis 边界复制使用六个互不重叠的
外表面循环，逐点读取同一粗 bridge basis 后以 SIMION 官方默认 refine 收敛；它替代旧的逐点字符串去重，
但不以“接地面”为捷径，因为每个 electrode basis 的远端 Dirichlet 值都可能非零。对相同 0.9 mm 几何，
优化前后 PA/GEM 的逐文件 SHA-256 一致，main-basis 阶段由 1043.390 s 降为 587.634 s。

对于 detector-blind 的 pre-pulse，运行器构建 `pre_pulse_reachable_v1` IOB：只加载粗前端、上游细域、
主加速器和中间 overlay。反射器、下游飞行管和探测器 PA 不物化到 runtime，也不绑定到 IOB；SIMION 必需的
六槽容器仅在槽 2/4 保留小型占位结构。Program 的 pre-pulse contract 只验证四个可达角色，且该轻量模式不能
用于全程飞行或总轴场导出；run manifest 明确记录该模式及省略角色。
N=5000 预脉冲筛选及跨整体 PA 的配对验收仍是物理/性能结论的必要前提。

仓库级 [`common/simion/resource_scheduler.py`](../../../common/simion/resource_scheduler.py) 仅为已授权请求
规划 RF/静电批次：它综合粒子数、公共的每批 CPU 策略、当前可用内存、已观测的同资源身份峰值及并发上限。
没有匹配历史时，运行器把第一个正式粒子批次作为至少45秒的资源识别批次；该进程不因观察结束而终止，
并必须自然完成，以记录穿过全部 PA 家族后的完整内存峰值；其结果直接保留。随后只对尚未执行的粒子重新
分批，并由公共调度器错峰启动、持续监控；不再生成
`RESOURCE_CALIBRATION_ONLY`探针或重复首批。
同一机制也调度已证明相互独立的静电 PA 工作项：例如完整边界 basis 写入后，各电极的 overlay refine
以一个正式电极作45秒首批观测，余下电极只按公共CPU/内存准入错峰启动；basis 写入本身仍串行，
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

每个 run 必须冻结 `run_config.json`、`summary.json` 和 `run_manifest.json`。缓存只用于完全相同的冻结身份，
且不可替代来源 run。v3 PA cache 在私有 staging 时逐文件全量哈希、原子发布并设为只读；普通复用只复核
当前 generation pointer、manifest、角色/键、文件清单和字节数，避免每个消费者重复读取数十 GiB 不变 PA。
发现非 current generation 与显式 artifact 审计仍执行全量字节哈希。功能成功不自动证明数值收敛、跨求解器
等价、参数最优或 Formal 资格。

若SIMION批次已经全部完成、但**只**在受治理的预脉冲TRACE物化步骤失败，
[`recover_completed_pre_pulse_screening.py`](../workflows/family_source_closure/recover_completed_pre_pulse_screening.py)
可从失败run的manifest-verified原始日志建立一个新的 analysis recovery run。它逐一绑定失败manifest、原始
run-config、run-local冻结合同、粒子映射和全部批日志；不得改写失败run、不得重跑求解器，也不得把恢复结果升级为
分辨率或Formal证据。

若一个或多个 SIMION 逻辑通道在预脉冲粒子飞行中断，下一次带 `__rNN` 身份的
预脉冲恢复由仓库共享的[`batch_continuation.py`](../../../common/simion/batch_continuation.py)与本项目的
[`pre_pulse_batch_continuation.py`](../runtime/pre_pulse_batch_continuation.py) TRACE适配器建立批级 continuation plan：
每个批独立核验 predecessor `failed/interrupted` manifest、run-config、冻结 time-series 合同、母源、initial-global-state、
row-map、原始 stdout SHA-256 与终态 TRACE；新 run 的上述三个 cohort 输入必须逐项同 SHA。完整批可直接导入；未完成批只能导入从该批起点开始、逐 ID 连续且无重复的终态
前缀，SIMION 只重跑其余后缀。不同通道已完成的独立粒子结果不会因为另一个通道中断而丢弃；但任一
SHA 漂移、跳号、重复/畸形 TRACE、禁止的下游事件或伪 `Fly completed` 标记都失败关闭。导入日志与
continuation plan 冻结到新的 run，旧 run 永不改写；连续多次中断时，前一轮导入日志继续由其 plan 中的
SHA-256 绑定。该机制是执行恢复，不改变45秒资源观测、通道准入、母 cohort、物理输入或统计口径。

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
正常脉冲。它不生成或改写 campaign；`--execute` 时仍只委托唯一的、持有主机租约的 `execute.ps1`。

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

活动 campaign 只由 v6
[`rf_multipole_oatof_experiment_campaign.schema.json`](../config/schemas/rf_multipole_oatof_experiment_campaign.schema.json)
校验。v1–v6 的旧结构只由同目录 `archive/` 下的归档读取 schema 校验，供历史证据审阅与回归使用；
它不被执行入口、活动发现或 resolved-plan 编译器接受。

当前唯一活动 campaign 是 `connector_gap_field_matrix_compact_auto_replay_v2.json`。此前 23 个已发布的逐 gap/field
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
有序人口。生成行必须继续使用`continuous_frontend`的完整母 cohort，禁止用`pre_pulse_restart`或共同
detector-hit 人口；其唯一允许的 cache-miss 时间格是当前已登记的 native-dt 范围或与 producer 匹配的 RF40
单快照。

活动 resolved source contract 仅接受 family v2：它显式按 `comsol` 或 `simion` 记录来源 branch，且运行时只
消费所选 branch。早期 v1 source contract 与其 adapter 仅是历史证据格式，不在活动 schema 或重放入口中保留兼容分支。

实验 campaign 可继续使用完整行，也可用扁平 authoring：`experiments.shared` 声明共同控制，
`variation_axes` 列出允许变化的字段，`rows` 只列行身份和 `overrides`。准备阶段先展开为完整冻结行，
再执行既有 schema 与授权校验；任何未声明的字段变化都失败关闭。这样同一合同可顺序执行多个 gap 或
其他已授权参数点，而不会复制共享输入。

已发布 campaign 如仅改变 authoring 布局，可用 `published_authoring_identity` 保留旧 receipt 的 raw 文件 SHA；
它同时冻结完整的、已展开 campaign 科学语义 SHA。只有二者严格匹配时才接受该旧 SHA；物理、数值、资格或
已注册 campaign 的任一展开行变化都会使 source-binding 检查失败。执行策略另由 runtime binding 和每次 run receipt 冻结，
不属于 campaign 科学身份。这不是通用兼容或结果复用 fallback。

对已注册 campaign，`execute.ps1 -AllExperiments` 按展开后的 `sequence` 逐行调用同一单实验入口；它不在
campaign 层并行商业求解器，任一行失败即停止。`PrepareOnly` 仍要求逐行显式审阅目录，避免覆盖审阅产物。

## 审查与 dry-run

公开入口可用 `execute.ps1 -ExperimentId BEFORE -SemanticDiffAgainst AFTER` 比较同一 campaign 的两条**已展开**实验行；
它内部调用 `prepare.py --semantic-diff-experiment-json`，输出稳定 JSON：
每个字段的旧/新值及其审查类别（物理/场、数值/资源、采样、资格、运行控制或证据）。这是读操作，不参与
schema 验证、cache 命中、handoff 兼容性或资格决策；这些仍由已冻结的 resolved contract 与实际执行边界决定。
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
