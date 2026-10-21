# COMSOL 电场网格、收敛与原生离子追踪性能调研

DOC_STATUS: ARCHIVED_READ_ONLY

本报告冻结 **2026-10-21 完成的资料调研**，面向本机有限资源下的 MR-TOF、多极杆、OA 和 IP。
它整合官方文献、仓库合同和已有运行证据，补做场求解、粒子积分、RF/脉冲、墙事件、原生插值与输出的小模型真实COMSOL验证，
并只读回查冻结oa-TOF正式MPH的活动设置；本次未重跑各仪器模型或改变生产参数。
下文明确区分官方支持的方法、项目已有实证和待验证建议；完成调研不等于建议已获数值资格。

本次开始时 HEAD 为 `0631080c102bac2f40cfd3d90c1fc2a8ac4cd8d8`；部分项目状态页已有其他任务的未提交
进展，按当日可见内容读取，未修改或纳入本次提交。历史数字应沿各表的证据链接追溯原 run，
未来当前状态仍以各项目 PROJECT 为准。本报告属于日期化跨项目调研快照，放入 history，避免把尚未
在两个项目验证的建议提升为根级通用规则。已有权威是[验证方法](../VALIDATION_METHODS.md)、
[操作指南](../OPERATIONS.md)、[COMSOL API](../COMSOL_API.md)和[排错指南](../COMSOL_DEBUGGING.md)。

阅读顺序：

- [先决定把计算量花在哪里](#先决定把计算量花在哪里)
- [本机资源与项目差异](#本机资源与项目差异)
- [历史失败教训](#历史失败教训)
- [网格如何设置](#网格如何设置)
- [代数求解与内存](#代数求解与内存)
- [怎样证明高精度收敛](#怎样证明高精度收敛)
- [COMSOL 原生离子追踪与速度差](#comsol-原生离子追踪与速度差)
- [本次小模型实测](#本次小模型实测)
- [追加快速验证](#追加快速验证)
- [快速未知项闭合](#快速未知项闭合)
- [结论状态与大型模型边界](#结论状态与大型模型边界)
- [建议的最小验证顺序](#建议的最小验证顺序)
- [官方资料及采用边界](#官方资料及采用边界)

## 先决定把计算量花在哪里

1. **先证明局部设置真实生效，再增加规模。** 检查选择集、操作顺序、实际单元/DOF和敏感区覆盖；
   仓库已有“GUI 显示 1 mm，实际网格没变”的反例。
2. **高精度应由需要可信的输出量定义。** 传输身份、出口发散、慢向返回、检测器峰宽分别验收；
   残差很小、100% 传输、等势图光滑均不能替代这些证明。
3. **优先局部、定向细化。** 杆中段的横向与轴向、孔口与远场、转折点与均匀漂移区分别分配自由度；
   不默认将最小间隙尺度铺满全模型。
4. **有限内存下先做建网和场 pilot。** MR 已有约 41.83 GiB 的受管进程树监测峰值，接近本机容量；
   再全域加密之前，应先查停止误差、边界误差、网格过渡和场表示。
5. **追踪慢需要独立诊断。** 仓库已有复用静电场后 COMSOL 原生粒子 Study 仍约为 SIMION Fly
   26 倍的案例；本次正式MPH回读还发现活动Generalized-α/Strict与163,970点输出列表。
   不能将全部差距解释为“COMSOL 多求了一次场”，也不能由闲置的BDF/Free字段判断实际策略。
6. **预算用尽且精度不足时改变方法。** 保留负结果，换分区、方向、求解策略或验证问题；
   不以放宽误差门槛、删除损失粒子或事后选最接近另一求解器的结果取得 PASS。

## 本机资源与项目差异

### 资源快照如何使用

2026-10-21 只读查询 `Win32_ComputerSystem`、`Win32_Processor`、`Win32_OperatingSystem`
及文件系统卷得到：

| 对象 | 当日观测 | 对计划的含义 |
|---|---|---|
| CPU | Intel Core i9-9900K，8 物理核、16 逻辑线程 | 16 线程不代表 16 倍求解或追踪吞吐 |
| 物理内存 | 51,457,728,512 B，约 47.92 GiB | 通常所称的约 48 GB 机器；报告要区分 GB/GiB |
| 当时可用物理内存 | 约 31.89 GiB | 随其他任务变化，不能作为未来固定可用额度 |
| C 盘当时可用空间 | 约 361 GiB | 大场导出、MPH和临时分解文件仍需另计容量及 I/O |

快照不是压力测试，也没有测磁盘吞吐或 GPU。不要从磁盘剩余容量推断 out-of-core 会快。
主机预算与重任务串行继续由[中央资源策略](../../common/host_resource_policy.json)和
[COMSOL 启动器](../../common/comsol/README.md#主机资源阶段)管理。
中央准入保留量不是求解过程的操作系统硬限额；本报告不另设一套全局内存百分比。

对新网格，应先测同物理、同阶次、同求解器的两至三个较小档位，记录**整个受管进程树峰值**
与 COMSOL 自报值，并保留各自口径。以这些点粗估下一级内存/时间，不用“每百万单元固定几 GB”。
官方也建议从小模型的 DOF 与内存建立预测关系，但这种外推不是上界保证。[S01]

建议在运行计划中分别登记建网、矩阵装配/预条件、场求解、粒子求解、导出/保存的预算。
下一档若已接近可用内存、登记墙钟或磁盘预算，就先改变策略。清除已无用的内存解、减少保存的中间解
须经本次 run 的保留合同处理；不要终止用户 GUI 或移除仍被引用的资产。

### 各项目的精度重点不同

下表是调查日定位摘要，不是新的参数权威或可直接执行的配置。

| 项目 | 已读合同/状态与已知边界 | 优先检查区域与输出 |
|---|---|---|
| MR-TOF | mesh4 为 30,697,694 四面体、42,804,889 DOF、二阶电势、CG+AMG；峰值约 41.83 GiB；固定 N13 尚无检测器命中，不能给出检测器 FWHM/R | 双镜快反射、慢向转折/返回、条带和镜槽/间隙；逐事件配对位置、速度、相对中心 TOF及终止身份 |
| 四/六/八极杆家族 | 四段杆，各段 19.6 mm，段间 0.4 mm；工作区 `hmax` 0.5→0.35 mm 是已有数值档，连续相空间资格仍不充分 | 横截面场、段间隙、端孔和 handoff；RF相位、横向速度、束半径、发散及能量 |
| 单次反射 oa-TOF | 当前合同反射区 15 mm、加速器 1 mm，0.5 mm为加速器参考；Formal资格只按冻结合同解释 | 加速器横向非均匀、栅/孔边、反射转向及检测器事件；峰形与配对到达时间 |
| 独立 OA | 已拆出二区/三区理论与器件构建；不继承 oa-TOF 整机 Formal，尚无独立全链资格 | 平行间隙、有限环场、侧入口/边缘漏场、脉冲切换和时间聚焦 |
| IP | 已有 SIMION 简化实体、15单位响应及 RF/DC/脉冲/碰撞链；当前0.1 mm、Refine 0.001 V尚不构成收敛；尚无 COMSOL 对照资格 | 0.8 mm 狭缝、开孔唇边、分段端部、数值外边界；提取能散、发散、真实接触与切换事件 |

证据入口：
[MR PROJECT](../../projects/parallel_mirror_dual_stripe_mr_tof/docs/PROJECT.md)、
[四极杆 PROJECT](../../projects/rf_quadrupole_ion_optics/docs/PROJECT.md)、
[六极杆 PROJECT](../../projects/rf_hexapole_ion_optics/docs/PROJECT.md)、
[八极杆 PROJECT](../../projects/rf_octupole_ion_optics/docs/PROJECT.md)、
[oa-TOF PROJECT](../../projects/single_reflection_oa_tof_mass_analyzer/docs/PROJECT.md)、
[独立 OA PROJECT](../../projects/orthogonal_accelerator/docs/PROJECT.md)、
[IP PROJECT](../../projects/dual_pressure_rectilinear_ion_processor/docs/PROJECT.md)。

四极杆尤其有两个作用域：家族三模式用
[multipole_transport_comsol_solver_numerics.json](../../projects/rf_quadrupole_ion_optics/config/multipole_transport_comsol_solver_numerics.json)，
专用接口/质量过滤用
[comsol_solver_numerics.json](../../projects/rf_quadrupole_ion_optics/config/comsol_solver_numerics.json)。
不能把不同合同的 auto level、局部尺寸或轨迹控制拼成同一条收敛序列。
COMSOL 自动等级数字也不是毫米值或精度等级；参数 `hmax` 是最大单元尺寸设置，
实际覆盖与边长仍须查询，不能据设置值推断所有单元尺寸。
MR资源数字来自[mesh4冻结summary][mr-mesh4-summary]；同run原生日志另报物理内存33.24 GB、
虚拟内存42.13 GB。它们与受管进程树41.83 GiB口径不同，不宜直接相减或换名。

## 历史失败教训

| 已读案例 | 可以得出的结论 | 不应得出的结论 |
|---|---|---|
| oa-TOF 选择框、Size执行及覆盖顺序曾使1 mm设置无效，实际仍为274,576单元 | 先核实选择范围与网格树执行顺序 | 改了GUI数字就已完成细化 |
| oa-TOF 反射区15→5 mm，约33万→307万单元，场求解约10→59 s，R几乎未变 | 该历史工况的均匀反射区加密收益低，应找敏感区 | 所有新反射器均可固定15 mm |
| 四极杆全器件 swept、imprint替代在拓扑过渡失败；均匀中段可扫掠 | 在可扫掠段内部切分，端部/孔板用独立过渡网格 | swept一概不可用，或四/六/八极共享一组固定层数 |
| hex D2以884,643单元建网成功；直接求解器后续超预算；CG-AMG可完成场 | 拓扑、建网、装配/分解和收敛是不同阶段 | 网格合法就有资源完成求解，或场完成就已高精度 |
| quad空间档进程树17.752 GB超过17.180 GB；提高预算后的替代仍超限 | 历史资源帽确实阻断过，须改策略并重新估计 | 将原失败当物理FAIL，或无限抬高帽值 |
| MR同mesh3改变停止控制并冷重求，某点变化317.067 V/m，同时矩阵状态也变化 | 旧网格序列混有求解状态变量，需先隔离 | 把全部变化唯一归因网格，或唯一归因误差因子 |
| MR组装阶段`xmodel_assem.cpp`断言，未进入CG；另有预检属性错误和容量拒绝 | 分别登记组装、配置、准入失败 | 这些行都是“新一档未收敛场解” |
| oa-TOF极小N在已存静电场上发生particle solution-mesh/提取原生崩溃，仍有23–35 GB可用 | 这是已关闭的原生兼容问题；独立粒子可沿现有N100前缀绕行 | 静电场网格OOM，或N30永远安全 |
| quad N1000在7200 s边界仅构造746个release节点 | 模型/释放构造可先于积分成为瓶颈 | 7200 s是1000粒子积分耗时 |

前三类案例的细节分别见
[oa-TOF网格构建器保留说明](../../projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_build_mesh.m)、
[oa-TOF旧项目过程](../../projects/single_reflection_oa_tof_mass_analyzer/docs/history/PROJECT_HISTORY.md)、
[四极杆网格筛查](../../projects/rf_quadrupole_ion_optics/docs/history/20260722_rf-mesh-strategy-screen.md)。
其余见[hex混合网格里程碑](../../projects/rf_hexapole_ion_optics/docs/history/20260729__closed-hybrid-mesh-campaigns.md)、
[hex退役总结](../../projects/rf_hexapole_ion_optics/docs/history/20260802__retired-comsol-qualification-campaigns.md)、
[quad资源/敏感性历史](../../projects/rf_quadrupole_ion_optics/docs/history/20260911__solver-sensitivity-and-retired-interface.md)、
[MR求解状态隔离](../../projects/parallel_mirror_dual_stripe_mr_tof/docs/history/20261015__fixed-field-reproduction-and-solve-state.md)、
[MR边界输入隔离](../../projects/parallel_mirror_dual_stripe_mr_tof/docs/history/20261015__boundary-input-isolation.md)、
[极小N调查关闭](../../projects/single_reflection_oa_tof_mass_analyzer/docs/history/COMSOL_EXTREME_N_CRASH_CLOSURE_20260719.md)。
历史 GB 保持原十进制口径，不改标成 GiB；这些数字属于原几何/原run，不代表今日重新测得。
N100承载后只分析前缀的办法限于无空间电荷、库仑或其他粒子间反馈的独立粒子问题；
增加粒子会改变集体物理时，不可使用该办法声称原小N问题等价。

## 网格如何设置

### 先明确求解域、边界和评价区域

理想等势金属通常用电极表面的电势条件表示，只在真空/需要求场的介质中分配电势自由度。
官方 Einzel Lens 即采用这一方式，并局部细化产生聚焦的边缘场。有限电导、介质极化、空间电荷或
耦合物理另行判断，不能为节省网格删除真实间隙、狭缝和屏蔽结构。[S07]

把真空划分为能被选择的数值区域：束流走廊、孔/槽/间隙、入口出口、转折区、远区。
仅添加一个选择框不会自动把贯通真空切成独立域；必要的 Partition 应保留物理连续性，
不增加虚假墙面/电势条件。检查粒子 Wall 选择是否误包含数值分区内部面。

几何与电压均满足对称时才使用半模型/二维。多极杆中段二维截面可以验证横向场，
不能覆盖有限长度边缘场；不同电极基场可能具有不同的对称/反对称条件。真实接地腔壁不能换成
开放边界；人为外盒应另做外域尺寸测试。无穷元适用于静电这类问题，PML不是默认替代物。[S12][S13]

### 建立可解释的局部尺寸序列

下面是**设计pilot的方法，不是已验证的配置或验收阈值**：

1. 以局部间隙 `g`、曲率尺度 `r`、束路离壁距离和场变化长度选择初档；记录每个量来自哪个几何实体。
   例如狭缝厚度方向试3、5、8层，只是辨别是否欠解析的试验序列，不能宣布“8层一定足够”。
2. 先固定外区尺寸、几何阶次、场阶次和求解器，仅改变一个区域或一个方向。可用
   `h0、h0/1.3、h0/1.7` 这样的温和序列，避免第一步全域减半；正式档位仍写回项目数值合同。
3. 每档检查实际局部边长/层数、选择实体数、单元分布、DOF和质量位置，不能只记录预设尺寸。
4. 把局部细区适当延伸至电极边界及邻近过渡区，再渐粗。MR已有“束轴细、槽壁附近粗”的实证，
   电场是边值问题，不能只把轨迹轴线附近做细就假定边界影响已精确。
5. 每次只推进影响目标量的区域；与目标无关的细化即使改善全局云图也不必保留。

在近似均匀三维域中，全部方向尺寸减半通常意味着单元数量约乘8；这是几何尺度估算，
不是求解内存或时间必为8倍。高阶DOF、稀疏分解填充和预条件器都会改变资源增长。
正式网格收敛按[既有方法](../VALIDATION_METHODS.md#网格建设与计算量控制)执行。[S02]

### 扫掠、阶次和自适应分别解决什么问题

| 手段 | 在本仓库的合适候选 | 需要检查的限制 |
|---|---|---|
| 横截面精细＋轴向swept | 多极杆均匀中段；IP长直段；OA平行间隙 | 端孔、段间隙、非恒截面与转向区独立处理；拉长方向场必须足够平缓 |
| 局部free tetrahedral | 孔边、槽端、曲面过渡及复杂反射区 | 避免不必要的薄片、小边和突变尺寸；检查曲面单元和实际覆盖 |
| 二阶电势上的h细化 | 现有二阶项目的第一比较轴 | 不同时改变求解停止、几何表示或粒子步长 |
| 二阶/三阶p比较 | 光滑真空束路的独立交叉检查 | 升阶增加DOF和场查询成本；不能靠降成一阶后仅按单元数声称同精度 |
| 自适应误差细化 | 可微场积分/束路加权目标的研究 | 计数、碰撞分类、直方图FWHM不是可直接套用的可微目标；还要做最终轨迹验证 |

官方四极质谱示例明确将端部 fringe fields 与长直段区分，并使用 swept；这是本仓库多极杆最直接的
参考案例。[S06] 薄隙定向扫掠的官方例子也说明，复杂区域与规则区域可以混合建网。[S05]

自适应不能无限运行：预先设置适应轮数/元素数并估计峰值内存。共享多电极基场的网格不能只对
最后一个解做自适应就认为所有激励都充分。6.4 的 Rebuild mesh 对 mapped/swept 结构通常不能
合适细化，Longest edge对含非单纯形单元的模型也较不适合；混合网格要查看实际生成结果。[S09][S10]

默认二阶不等于电场二阶精度。电场来自电势梯度，跨单元导数与曲面表示都可能影响离子。
形函数阶次、几何阶次、局部尺寸与后处理平滑应分别记录。6.4静电势默认二阶有官方依据，
具体模型仍应回读。[S03][S30]

### 不用理想锐角的最大场作为通用停止量

理想尖角处的电势可以有定义，而场强峰值随加密持续增大。此时“max(E)仍在变”可能是奇异性，
不是求解器未正常工作。关注真实峰值/击穿时需由实际圆角几何建模；不能任意倒角改物理问题。
关注束流时应预先固定评价区域和离壁距离，同时保留可达高场区域，而非事后排除坏点。[S04]

网格质量也没有一条适合全部模型的通用数值阈值。记录质量定义、最差单元位置、分布及曲面
Jacobian问题。MR局部细化曾使最差质量从约`3.47e-4`降至`4.83e-5`但仍求解完成；
这既不证明低质量无害，也不能反过来把已有失败全部归因该数值。[S08]

## 代数求解与内存

### 先分清当前网格上的求解误差

纯真空静电势是标量椭圆边值问题。约束充分且形成实对称正定系统时，可以试 CG 配合合适的
对称正定预条件器；AMG适合标量椭圆问题。浮置电势、弱约束、耦合或装配方式可能改变矩阵性质，
不能仅凭物理名称强制CG。CG不适用时，选择与实际矩阵相容的GMRES等方法。[S15][S16]

中等规模先用直接法形成比较参考；内存紧张时评估迭代法。在同一网格、同一初值/清解路径下比较
势、弱场分量和代表轨迹，再接受省内存方案。直接法也不消除网格误差，迭代法也不必然降低精度。
实际采用者由活动 `linsolver` 引用和日志确定，不能根据树上存在 MUMPS 节点判断。[S15]

COMSOL 的线性停止涉及相对残差、预条件与误差因子 `rhob`。
`stol=1e-9` 不等于物理电场误差为 `1e-9`；增大 `rhob` 是加严误差估计，不能把它调小当性能捷径。
应固定网格单独加严停止控制，比较实际关注量；再固定这些控制做网格实验。
MR当前 `rhob=40000` 是该运行身份的一部分，不是各项目通用推荐值。[S16][S17]

### 内存不足时按阶段选择措施

| 内存峰值位置 | 可验证的措施 | 不能承诺的事情 |
|---|---|---|
| 建网 | 减少无用求解域、重新分区、定向扫掠、修复非物理小实体 | 更换线性求解器能修建网拓扑错误 |
| 组装 | 检查全局耦合是否稠密化；减少无必要耦合；受支持的装配设置做单变量试验 | out-of-core LU能消除装配峰值或修复原生断言 |
| LU分解 | 中等档直接法参考后试CG/GMRES+多重网格；必要时评估out-of-core | RAM不足仅靠增大页面文件即可保持速度 |
| AMG/GMG | 记录粗层大小、迭代次数及预条件器峰值，调结构而非只抬迭代上限 | 迭代法没有内存峰值 |
| 多解/导出/粒子结果 | 按保留合同减少中间解、分块提取与分段输出 | 减少文件内容自动保持事件/峰宽算法等价 |

官方区分组装与求解两类峰值；非局部耦合还能破坏稀疏结构。[S18]
PARDISO/MUMPS的out-of-core把部分LU因子放到磁盘，是速度换内存；其内存参数不是COMSOL整进程硬限额。
Reuse preordering也可能提高峰值。采用前应同时计入临时盘容量与总时间。[S14]

当前启动器已暴露 `AssemblyScalabilityMode`。本次真实启动确认本机6.4.0.293拒绝`on`，
原生日志列出`off/matrix/vector/all`；公开6.4手册及当前入口仍列`on`，存在版本/接口不一致。
`auto`和`matrix`均已启动并完成小模型；这只关闭入口可用性问题，尚未证明降低大型模型装配峰值，
更不能写成已修复MR组装断言。细节见[快速未知项闭合](#快速未知项闭合)。
cuDSS主要改变线性系统求解，不等于给粒子场查询或整个CPT自动GPU加速。
在没有本项目基准前，不把GPU、线程数、allocator或out-of-core设成默认提速答案。

BEM/FEM–BEM可以作为大空域静电候选：BEM减少体网格，但有常系数/物理适用限制；
直接法的稠密矩阵与大量边界自由度可能反而昂贵。应比较相同观察量、完整场评价成本和资源，
不能把“只网格化表面”当作必然低内存结论。COMSOL的BEM默认使用迭代法与远场近似，
可避免显式构建完整稠密矩阵；比较时应记录这一差异。[S11][S29]

## 怎样证明高精度收敛

### 建立完整误差链

```mermaid
flowchart LR
    A["几何、边界与激励"] --> B["FEM尺寸、阶次、质量"]
    B --> C["代数停止与求解状态"]
    C --> D["原生场评价或导出插值"]
    D --> E["粒子积分、开关和墙事件"]
    E --> F["检测器统计与功能指标"]
```

上图表示误差传播关系，不表示每次必须重新执行全部阶段。先在固定网格上排除明显代数误差，
再做空间收敛；随后固定选定场做时间收敛，最后比较独立场求解器。细化导出网格不等于细化FEM，
在COMSOL场上用SIMION飞行也不等于两个场求解器独立闭合。

每档至少保存以下小证据，字段归现有项目合同，不新建第二套机器权威：

| 类别 | 建议记录 |
|---|---|
| 身份 | 几何/材料/边界/电压、cohort、场来源、网格、求解设置、观察事件及代码身份 |
| 网格 | 各局部选择/尺寸/层数、阶次、实际元素/DOF、质量定义与位置、外域边界 |
| 求场 | 活动求解器、冷/热初始化、残差与误差估计、迭代、失败阶段 |
| 场验证 | 固定共同坐标的V、Ex/Ey/Ez；弱场绝对差、工作场归一化差、入口/端部/转折分别统计 |
| 粒子 | 实际内部步控制、输出点、RF/开关、终态ID与原因、同事件位置/速度/TOF |
| 成本 | 建模、建网、场、追踪、提取、保存分别计时；进程树峰值、输出及临时空间 |

### 用输出预算反推精度，避免无依据百分比

时间域分辨率近似关系沿[仓库定义](../VALIDATION_METHODS.md#分辨率与峰形)：

```math
R=\frac{T}{2W_t},\qquad W_t=\mathrm{FWHM}_t .
```

作为**说明性算例**，若目标 `T=1 ms、R=100000`，对应峰宽为5 ns。
若研究设计另行给数值误差分配峰宽的10%，则是0.5 ns；这个10%是算例假设，不能自动成为MR、
OA或任何项目门槛。应由目标效应/接口裕量/实验误差确定实际预算及组合方式。

配对时间差要同时报告共同漂移 `mean(Δt)` 和去共同漂移后的分布。
整群平移不等于峰宽增大，少数尾部变化也可能不体现在均值中。
若命中ID改变，先报告全部终止分类，再报告共同命中子集；不能删除丢失粒子后只展示变窄的峰。

MR尤其需要同一编号的快反射、慢转折、慢返回、检测器事件分别比较。
当前mesh3→4在同入口单正镜五颗的最大相对时间差约0.028632 ns，
而整程target49为0.211393 ns、y差1.006036 mm；
另一同场传播对照的入口y差0.027424 mm放大到0.622397 mm。
这些证据说明状态误差会传播和放大，但不能把单镜误差简单乘49当作整程严格误差界。
target49也不等于检测器到达。证据见[MR项目状态](../../projects/parallel_mirror_dual_stripe_mr_tof/docs/PROJECT.md)。

另一个[父边界隔离案例](../../projects/parallel_mirror_dual_stripe_mr_tof/docs/history/20261015__boundary-and-parent-consistency-isolation.md)
保持同一细网格，改变五个外面的边界输入，相对mesh4的单镜出口最大慢向（y）位置差
从0.071485降至0.002356 mm，缩小约30倍；横向与相对计时差未同步改善。
这是“先查边界，再决定是否加网格”的实证，证明边界输入影响慢向状态，
不证明mesh4是真值或整体精度提高30倍。

### 至少区分三种结论

- **当前网格求解完成：** 方程解和输出存在，满足该求解器的停止规则。
- **相邻档对指定观察量稳定：** 在控制一致的比较中，指定量变化落入事前有来源的预算。
- **项目资格成立：** 除离散外，输入、事件、统计、GUI/CAD及声明范围也满足项目合同。

局部、非均匀或不同拓扑网格没有一个天然统一的 `h`；
MR的regular/longest-edge混合序列不能直接套固定比率Richardson外推。
若结果非单调，检查网格质量、求解状态、插值/事件、损失身份与统计噪声，
不要只选最好看的两个点。三个档位也不是数学上自动证明收敛。

## COMSOL 原生离子追踪与速度差

本节与后续试验建议一起讨论原生CPT；COMSOL导出场后由SIMION飞行是另一条路径，
不能用其速度作为COMSOL原生追踪的测量。

### 仓库证据说明确实慢在哪里

**oa-TOF已有可信的“实际工作流时间差”，尚无精度和输出负担完全对齐的“积分器效率比”。**
同一i9-9900K、524 Da、同源N=1000的冻结资产复测如下：

| 测量边界 | COMSOL | SIMION | 可以解释的范围 |
|---|---:|---:|---|
| 粒子阶段 | 657.306935 s | Fly 25.35 s | 时间比25.93；COMSOL复用静电场，但两端存储负担不同 |
| 外层启动至任务/Fly完成 | 847.989884 s | 26.130090 s | 含各自启动和外围工作，不能全归因积分器 |

COMSOL的657 s只包粒子Study运行，不含后续`mphparticle`提取；静电和建网时间均为0。
它占COMSOL外层时间约77.5%，所以“主要只是启动慢”不成立。
剩余190.68 s没有进一步分阶段证据，不能武断归为LiveLink、Java、模型加载或I/O。
COMSOL保存分段输出，SIMION不保留完整轨迹，故25.93不能推广为同精度、同输出的固有速度比。
本次重读了[benchmark summary][oa-perf-summary]；详细计时口径见[run config][oa-perf-config]和
[COMSOL报告][oa-perf-log]。两端使用各自冻结场，不是同一个数值场。

**MR另有更强的单步成本信号。** 单ID6、仅3 μs的原生CPT诊断继承已保存约2084万四面体场：
没有重求ES、没有重网格；时间积分1031 s，runAll 1128.349 s，完整运行1215.243 s。
实际采用`NewtonianFirstOrder / Dormand–Prince 5`，仅6个运动DOF＋3个内部DOF，
最终3133步、22078次残差评价、21次时间步失败（日志Tfail），保存3001点。
由此推得平均每个接受步约0.329 s，含多次右端评价、失败尝试和运行期处理，
**不是一次纯插值调用耗时**。这个实例已经是显式DP5，不能靠“把BDF换成RK”解释或保证解决。
证据：[summary][mr-cpt-summary]、[solver log][mr-cpt-log]、
[历史冻结正文](../../projects/parallel_mirror_dual_stripe_mr_tof/docs/history/20261008__field-response-engineering-milestone.md)。

MR尚没有同N、同3 μs区间、同输出和精度目标的SIMION计时对照，不能为其计算可靠速度倍率。
当前MR的mesh4求场1564 s和场图导出1971 s也都不是CPT计时。

### 原生CPT应怎样组织

原生Charged Particle Tracing求解离散粒子的运动方程，可从先前计算的场或解析表达式取得力；
它并非每走一步必然重求整个FEM电场。官方支持静态、谐波、周期场及多个力场叠加。[S19][S20]

对于固定几何、线性材料、没有需要反馈求解的空间电荷的准静电模型，可以先求电极响应，
再在粒子研究中按电压波形叠加：

```math
V(\mathbf x,t)=V_{\mathrm{fixed}}(\mathbf x)+\sum_k U_k(t)\phi_k(\mathbf x),
\qquad
\mathbf E(\mathbf x,t)=-\nabla V(\mathbf x,t).
```

这里`φk`是对应单位电极电压的响应，其他驱动与固定项必须按同一边界定义处理，避免重复计入DC。
它是线性方程下的叠加推论；几何改变、非线性介质、自洽空间电荷或不再适合准静态时不能照用。
RF单位场乘波形是保留RF周期运动，不等于用赝势代替真实RF。官方四极质谱示例采用分开的DC/AC场
与粒子研究；具体电压幅值约定和相位仍须与项目合同一致。[S06]

原生模型树应能检查以下内容：

1. 场Study只求相应电场，CPT Study只推进需要的粒子变量。
2. `Electric Force`引用正确的冻结场；未求解变量显式继承对应Solution，不能仅停用ES。
3. 释放节点读取冻结初态与出生时刻；粒子ID、RF相位、脉冲时间原点保持。
4. Wall/出口/检测器选择和终止行为符合实际事件；数值分区面不成为错误碰撞面。
5. 时间求解器的**实际活动分支**、容差、变量尺度、最大步、输出策略可读回；保存后GUI Compute一致。

当前oa-TOF和多极杆已实现冻结场复用，oa-TOF也已用单个`ReleaseFromDataFile`承载全部粒子。
所以不能将“每步重求场”或“每离子建一个节点”当作oa-TOF慢26倍的现成解释。
多极杆则确有逐粒子release节点和不同出生时刻，需另行看构造阶段。
实现依据为[oa-TOF CPT构建器](../../projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_configure_particle_model.m)、
[公共多极杆求解器](../../common/multipole/solve_finite_3d_transport.m)及
[已有场继承API](../COMSOL_API.md#studysolver与初值复用)。

### 为什么可能比SIMION慢

建议按下面的分解定位，不能把“可能机制”写成已经证明的根因占比：

```math
T_{\mathrm{total}}=
T_{\mathrm{load/build}}+T_{\mathrm{field}}+
T_{\mathrm{advance}}+T_{\mathrm{extract/save}},
\quad
T_{\mathrm{advance}}\approx
N_{\mathrm{eval}}c_{\mathrm{field+force}}+
T_{\mathrm{events}}+T_{\mathrm{solver}}+T_{\mathrm{store}}.
```

上式只是性能诊断框架，各项必须实际计时；每次场/力评价可能涉及整个活动粒子集合。

| 因素 | 为什么可能产生差距 | 仓库证据及需要的对照 |
|---|---|---|
| 场表示与查询 | 本仓库三维FEM需在离散网格上取得粒子位置的场/梯度；SIMION专为PA场表示与飞行设计。规则索引与FEM评价的成本结构不同；FEM也可采用swept等规则结构 | MR很少运动DOF却每步昂贵，值得查；未有底层profile，不知道定位、插值、力表达式各占多少 |
| 时间算法和实际精度 | 方法、误差范数、尺度与限步不同；一个平台的rtol不能直接换算为另一平台的T.Qual | MR已用DP5，排除“必因隐式”说法；两边需达到同一终态误差预算 |
| 共同推进和难粒子 | 使用共同步进的模型可能被少数强加速、近墙或碰撞粒子限制；SIMION也有Grouped模式同类问题 | 只在无粒子间耦合时比较等价分组；不保证COMSOL线程随N线性加速 |
| 输出与状态保存 | 全体粒子×时间点×变量的存储/插值与稀疏终态记录不同 | oa-TOF两端输出不等，现有约26倍需保留此限制 |
| 模型构造 | 节点/API操作与编译不是粒子积分 | quad N1000在CPT前已耗到7200 s；oa-TOF单文件release不属于该情况 |
| 额外物理 | 粒子间库仑、场反馈、气体碰撞、次级粒子、累加变量增加工作量 | 必须先查节点及实际DOF，不能用关闭所需物理后的速度称等价提速 |

COMSOL官方说明粒子沿体网格传播，并与边界网格相交，而不是直接与精确参数化CAD面相交。[S23]
这支持将曲面离散和网格上的评价过程纳入诊断，**不提供“搜索是O(N单元)”或固定速度倍率的依据**。
SIMION官方也明确时间步、RF限步、绘图、记录及每步用户程序会改变飞行成本；SIMION并非无条件快。[S24][S25]

另外，CPT使用`Accumulator`时可按域/边界单元增加未知量；“只有1000粒子”不能单独确定问题规模。
直接两两库仑求和通常具有随N平方增长的配对数，而自洽粒子—场模型另有场迭代代价。
这是物理/算法区别，不能通过偷偷去掉空间电荷取得速度优势。[S26][S28]

### 提速措施的优先顺序和边界

| 优先项 | 建议操作 | 需要保持的正确性 |
|---|---|---|
| 先分阶段计时 | 分开load/build、release、compile、ES、CPT、extract、plot/save；同时记录实际步数、评价数、Tfail及峰值 | 不把包装器计时当积分器计时；不把失败输出剔除 |
| 复用同一冻结场 | 同几何线性问题先求基场，CPT显式继承；检查模型更新是否意外重建mesh/ES | 当前已实现的项目不用重复开发；改模型后不能普遍跳过更新 |
| 控制保存/提取 | 保留关键事件、必要细窗和少量代表轨迹；关闭不必要的求解中绘图；复用已有稀疏/窗口提取，必要时验证分块方案 | 全体canonical终态与失败分类仍保留；验证事件插值、FWHM及ID不变 |
| 核对积分器 | 非刚性电场轨迹可对照一阶Newtonian+DP5与现有方法；刚性/强骤变另评估 | 不是所有模型都默认BDF；比较误差相同条件下的耗时 |
| 调整步长与尺度 | 看实际活动方法的max-step/rtol/atol/变量尺度，按输出误差预算做一轴变化 | 不盲用1e−12，也不直接放宽未闭合的精度要求 |
| 场恢复PPR对照 | 固定网格与粒子比较raw梯度/PPR、步数、评价数和终态 | PPR改变受力场表示，既可能增加单次成本，也可能减少步数；不是纯绘图开关 |
| 合理组织release/批次 | 相同出生时刻且无耦合时研究原生文件release或可验证分组；复用模型减少构造 | 保持出生时刻、ID、波形绝对时钟、随机流与事件；不要复活已不等价的向量化方案 |
| 最后考虑硬件/替代场表示 | 相同精度比较线程、GPU、预采样场或局部场模型的端到端成本 | 本机COMSOL会话仍按公共入口串行；预采样场需单独收敛，不能删几何/墙事件 |

单个输出矩阵的成本已可能很大：说明性规模`1000粒子×100000时刻×6个double`约4.8 GB，
尚未计入索引、状态、复制、求解器和MPH。因此减少无用输出有价值，但不能用“只保存最终时间”
代替已经消失/撞墙粒子的实际到达事件。

6.4官方区分二阶Newtonian与一阶Newtonian，默认搭配分别为Generalized-α和Dormand–Prince 5；
后者对合适的非刚性问题可能有利，强加速度突变等情况不能保证更稳健。[S21]
oa-TOF当前源码有free/tlist、线性后端设置，但未完整显式冻结/回读CPT的方法与全部容差。
本次对2026-07-29冻结MPH的只读回查实际确认Newtonian二阶、Generalized-α/Strict，
详见[追加验证](#追加快速验证)；当前源码不能替代冻结资产的实际身份。
不要用旧代码注释中的“BDF”补造实测配置；MR summary里同时出现`timemethod=bdf`和
`rkmethod=dopri5`时也须以活动日志为准。

### 输出时间和内部步长必须分开核对

COMSOL支持Free、Intermediate、Strict等时间策略。**Strict要求某些内部步落在输出时刻，
仍可插入额外步，不等于只按列表固定步长前进。** Free下输出通常通过插值产生；
稀疏输出仍可能损害外部事件提取，所以“free”不保证任意改输出表都保持最终指标。
修改时应读回实际活动积分器的设置；DP5不应只检查BDF分支字段。[S22]
6.4 Time API分别列出`odesolvertype`、`timemethodexp`和`rkmethod`；
应由本机属性列表确认名称，再判断活动分支。支持`reacf`的活动分支可能在请求输出时刻增加残差装配，
因此Free下增加输出的耗时不一定只是写盘；但6.4明确不支持在Runge–Kutta中计算该反力选项，
不能把DP5中回读到`reacf=true`当作实际启用或提速机会。[S22][S31]
官方还提醒输出列表可能影响自动初始步；公开资料未给出DP5自动最大步与输出间隔的明确公式。
因此Free不等于“任意修改输出列表后内部步序列保证不变”。要隔离输出密度影响，
可固定起止时间、初始步与显式最大步，再核对原生日志。[S33]

源码审查和本次小模型已明确其区别：
多极杆`rf_steps_per_period`当前用于`dt=1/f/steps`后生成Study的`tlist`，
不能仅凭字段名把80/160写成“已强制内部每周期至少80/160步”。
自动生成的求解器还需要回读步进策略、最大步和容差；若默认Strict生效，它会约束输出节点，
若Free生效，则不能据输出表证明内部采样。这里记录实现边界，本次不修改合同或既有资格。

合理限步应同时考虑RF周期、脉冲边沿、场变化长度/速度和真实墙/检测事件。
在一档已选空间网格上逐步缩短活动max-step或收紧容差，比较相同事件状态；
不能只增加导出时刻个数就称为时间收敛。转折点速度接近零时，仅用“单元长度/速度”估步不充分，
还需考虑加速度、RF相位及返回分支。

IP的碰撞更不能只照搬真空模型：官方CPT碰撞的常规算法要求步长足够短于平均自由时间；
null-collision方法有自己的假设，包括高能粒子条件，不能为提速无条件替换低能缓冲气冷却模型。[S27]
切换/脉冲必须保留原波形及绝对时钟；需要事件对齐或分段重启时，先证明与连续参考状态等价。

### 已有提速与失败对照能教什么

| 已有证据 | 值得复用的认识 | 不能推广的结论 |
|---|---|---|
| oa-TOF旧N100参数化、相位对齐分段输出，粒子阶段约1.77倍提速并通过当时配对 | 将细输出集中于加速/反射/检测敏感区已有实证 | 任意缩窄窗口都无损；该速度比自动适用当前全部模式 |
| 另一旧细窗缩窄使128.4→98.1 s，但R从14988.6→9099.5，被撤销 | 提速必须检查分析指标，不能只看Free或终点图 | 保存策略一定不影响科学结论 |
| 旧`tout=tlist→tsteps`：103.351→100.007 s，提取约12.54 s不变 | 有些存储开关几乎无收益，先测实际输出量 | 单次约3%即可宣称稳健加速 |
| 旧N100 GPU粒子时间162–236 s，CPU106–117 s | 小问题GPU不必更快 | GPU永远无效，或换GPU能直接解决MR场查询 |
| MR旧20 μs对照DP5+PPR约291 s，raw约1887 s，同时轨迹/能量改变 | 平滑场表示可能改变积分负担，值得受控验证 | 已证明6.5倍同精度收益 |
| MR同旧半域逐步收紧rtol，45→56→87→144 s，横向状态未一致收敛 | 容差有成本，场/事件问题不一定靠收紧积分消失 | 选最快的容差就满足工程要求 |
| oa-TOF旧N10000在CPT完成后`mphparticle`序列化OOM | 解、提取和发布分层处理；复用当前稀疏/窗口提取 | 需要重新细化场或再次盲跑CPT |

证据见[oa-TOF数值验证史](../../projects/single_reflection_oa_tof_mass_analyzer/docs/history/NUMERICAL_VALIDATION_20260716_18.md)、
[oa-TOF旧项目过程](../../projects/single_reflection_oa_tof_mass_analyzer/docs/history/PROJECT_HISTORY.md)、
[CPT构建器保留说明](../../projects/single_reflection_oa_tof_mass_analyzer/comsol/oatof_configure_particle_model.m)、
[MR场响应里程碑](../../projects/parallel_mirror_dual_stripe_mr_tof/docs/history/20261008__field-response-engineering-milestone.md)。
这些旧工况不是可横向拼接的性能排行榜。
PPR官方说明只支持其邻域场恢复机制，不能把其他后处理模块的评价耗时倍率移植成CPT倍率。[S20]

### 本次小模型实测

为核对不确定设置，首轮使用统一R2025b入口运行COMSOL **6.4.0.293**，该轮未读取正式仪器MPH。
这是组件诊断，产物由oa-TOF项目容器承载，不构成oa-TOF整机验证。
物理、数值与case顺序冻结于[probe config][probe-config]，实际属性、误差和计时见
[probe summary][probe-summary]，原生日志计数见[log metrics][probe-metrics]。

**试验对象：** 10 mm立方体真空，所有外面施加解析电势
`V=-100[V/m]*x`；二阶电势，4,879个四面体。固定100个40 Da、+1离子，
从`x=-4 mm`、`y/z∈[-1,1] mm`的10×10阵列释放，初速`(1000,0,0) m/s`，
传播1 μs，无墙接触、碰撞或空间电荷。用匀加速解析解核对终态；
FEM只求一次，后续CPT显式继承，试验后单元数未变。

**先读默认，再做对照。** 一阶Newtonian之后自动生成的Time节点实际读回：

| 项目 | 覆盖前默认读回 |
|---|---|
| 活动方法 | `odesolvertype=explicit; timemethodexp=rk; rkmethod=dopri5` |
| DP5步进 | **`tstepsdopri5=strict`** |
| 同树闲置字段 | `timemethod=bdf; tstepsbdf=free` |
| 控制/误差/最大步 | `control=time; rtol=1e-5; maxstepconstraintdopri5=auto` |
| 输出附加量 | `tout=tlist; reacf=true; storeudot=true` |

这验证了“看到bdf/free字段不代表实际采用BDF/Free”。**通用Time API表列默认值不能替代
物理接口生成的序列。** 本次并未回读所有正式仪器模型，因此不能由此断定它们当前全是Strict。
默认`maxstepdopri5=0.1`在`auto`分支闲置，不能将它解释为实际0.1 s上限。

随后明确设`control=user`、DP5、`rtol=1e-8`、scaled全局绝对容差因子0.1、
初始步1 ns、最大步50 ns；`reacf/storeudot/plot`关闭、probes禁用。
场模式与Free/Strict、输出点数是下表声明的变化。先做一次解析场预热；
三种场模式各重复2次，稠密输出Free/Strict各1次。每case重新生成粒子Study/Solver，
计时包含`runAll`内部编译/初始化，单列提取；不是底层力评价的微基准。

| 模式 | 输出点 | 接受步／残差评价／Tfail | runAll（s，按顺序） | 提取（s） |
|---|---:|---|---|---|
| 解析均匀力，Free | 101 | 22／154／0，两次相同 | 0.855、0.534 | 0.291、0.282 |
| FEM raw，Free | 101 | 23／161／0，两次相同 | 1.864、0.537 | 0.250、0.267 |
| FEM PPR，Free | 101 | 22／154／0，两次相同 | 0.859、0.691 | 0.267、0.203 |
| FEM raw，Free | 1001 | 23／161／0 | 0.625 | 0.617 |
| FEM raw，Strict | 1001 | 1000／7000／0 | 3.724 | 0.657 |

所有case实际N=100，终态仍活动且不触壁。最大终点位置误差：解析力约`4.44e-16 mm`，
FEM raw约`5.17e-7 mm`，PPR约`4.19e-7 mm`；FEM raw最大速度误差约
`9.71e-4 m/s`。场求解采用自动序列，释放点FEM各分量最大误差不超过
`4.71e-4 V/m`，未另做代数/网格收敛；不能把这些数值当作仪器精度认证。
完整函数执行31.91 s，其中所有场/粒子`runAll`累计11.95 s，未超180 s累计求解预算；
不含商业软件启动等待。该预算在case之间检查，并非每个求解调用的硬超时。

可用结论和限制：

- **Free输出加密不等于积分加密。** 本次101→1001点仍为23步、161次评价，终态数值相同；
  提取工作增加。日志会省略部分中间步行，未保存全部内部步序列，故不宣称逐步字节一致。
- **Strict可能引入大量额外积分。** 同样1001点时由23步增至1000步，单次runAll约增加到5.96倍。
  本例Free和Strict终态位置均接近解析解；无墙/脉冲/RF事件，不能据此取消仪器所需的事件对齐，
  也不能把5.96倍当作MR或oa-TOF的已验证收益。
- **不能据此宣布PPR必然提速。** raw首次1.864 s、第二次0.537 s波动明显，
  PPR还改变了步数和受力表示。两次重复、固定顺序、数千单元不足以估计长期吞吐或分配底层开销。
  均匀场也没有MR的大规模非均匀场问题。
- **无需把首轮错误归为物理失败。** [首轮记录][probe-failed]在读取属性时，
  因本机返回`Boolean`而探针未处理该类型，停止于粒子求解前；静电已完成。
  按实际类型调用官方getter后，新run保持同一科学配置完成全部case。

本次保存轻量输入、属性快照、解析误差、原始日志与manifest；不保存MPH或完整粒子轨迹。
临时诊断实现与启动脚本在发布后删除，源文件SHA留于run config；重建使用冻结物理/数值配置、
上述模型树设置及官方API。没有新增生产入口、调参分支或Formal资格。

### 追加快速验证

随后依用户要求补查三个能在短时间回答的问题。仍使用COMSOL 6.4.0.293与公共启动入口串行执行。
本节所有误差都是观测结果，没有把任意误差阈值当作仪器资格。

**自动步长与方程形式。** 使用同一N100初态、10 mm立方体及解析常力，不求FEM场；
前三例设一阶Newtonian，只将自动生成Time的控制改为user、DP5步进改为Free，
保留默认`rtol=1e-5`、自动初始步/最大步及输出附加量。第四例保持二阶Newtonian全部默认。
每例新建小模型，结果与日志见[追加CPT结果][followup-cpt]、[计数][followup-metrics]。

| 方程/实际策略 | 输出点数 | 接受步／Res／Tfail | runAll（s） | 提取（s） |
|---|---:|---|---:|---:|
| 一阶／DP5 Free，自动步长 | 11 | 1／7／0 | 0.916 | 0.510 |
| 一阶／DP5 Free，自动步长 | 101 | 1／7／0 | 0.408 | 0.246 |
| 一阶／DP5 Free，自动步长 | 1001 | 1／7／0 | 0.442 | 0.749 |
| 二阶默认／Generalized-α Strict | 1001 | 1000／1986／0 | 1.522 | 0.635 |

三组Free都以一个1 μs步完成；本例**未观察到输出密度改变自动步长**，但不能推导自动最大步
公式或保证所有模型均如此。全部保存时刻/粒子的最大分量位置误差：一阶不超过
`1.78e-15 mm`，二阶`3.89e-10 mm`；状态均活动且未触壁。二阶同时改变了方法和步进策略，
没有重复计时，因此不是等条件的积分器性能比较。四例完整诊断耗时17.17 s，
低于120 s的case间墙钟检查预算，不含商业软件启动，也不是单次求解硬超时。

**固定网格下，场误差是否先受停止条件限制。** 同样的解析线性电势、二阶形函数，
固定4,879四面体、1,021顶点、7,292 DOF；在`x=-4/-2.9 mm`各取10×10点，合计200个固定点。
每例`clearSolutionData()`后从`V=0`初值求解，回读网格数据完全相同；未恢复PPR。
此处清解保留求解器树，不代表重启进程或清除所有缓存。[S36]

| 唯一控制变化/对照 | 实际后端与有效stol | LinIt | 最大电势误差（V） | 最大电场分量误差（V/m） |
|---|---|---:|---:|---:|
| 自动默认 | CG，rhob=400，1e-3 | 3 | 5.30e-7 | 4.71e-4 |
| 仅加严停止容差 | 同CG/rhob，1e-9 | 6 | 2.95e-13 | 5.76e-10 |
| 另换直接法参考 | PARDISO，1e-9 | 不适用 | 5.55e-16 | 1.08e-12 |

误差为全部采样点相对解析解的最大绝对值；电场列取三个分量最大值，不是向量范数。
原始采样值、初值、活动引用、控制读回和计时见[场诊断结果][followup-field]。
默认/加严两例中`fc1→i1(CG)`不变；直接参考改为`fc1→dfield(PARDISO)`，旧i1已不活动。
自动树的`control=stat`使Study控制容差，因此通过Study的`usestol/stol`加严；
求解后Stationary读回也为1e-9。若控制为user，才直接改求解器stol。[S34][S35]

该解析线性电势可以被本例形函数表达，因而很适合暴露代数停止误差。
结果支持“固定网格先排除停止误差”，不证明MR网格已收敛、所有问题都该用1e-9、
或直接法在大模型更好。三次runAll为1.429/0.823/0.885 s，包含编译且顺序固定，
不能据此声称加严容差更快。没有完整展开更深层AMG配置，记录也不是所有求解器参数的全量备份。

**正式oa-TOF资产实际用了什么。** 只读加载2026-07-29冻结MPH，
文件986,349,231 B，SHA256
`9F4C3DCE51791B41B4A7649500F74C29366BAC431111E79AF6CE5399ECA72A4D`，
与正式资产登记一致，读取后再次完整hash未变。加载约5.00 s、读取总计5.49 s；
没有生成求解器、Compute、提取完整轨迹或保存模型。详见[实际属性快照][followup-readback]。

| 实际对象 | 读回结果与含义 |
|---|---|
| CPT | `Newtonian`二阶 |
| 活动Time | `sol2/t1; control=time1; odesolvertype=implicit; timemethod=genalpha` |
| 活动步进 | **`tstepsgenalpha=strict`**；`tstepsbdf=free`是闲置分支 |
| 误差与限步 | rtol=1e-5；scaled绝对容差因子0.1；自动初始步和最大步 |
| 输出配置 | tout=tlist；163,970个递增时刻，0至72.8534 μs；其中163,163个间隔为0.2 ns |
| 输出附加量 | reacf=true、storeudot=true、plot=off、probesel=all |
| 冻结场继承 | sol2/v1：notsolmethod=sol、notsol=sol1、notsolnum=auto；std2只开CPT、停用ES |

这里163,970是**配置的输出点数**，不是本次测得的实际存储数或内部接受步数；本次没有飞行。
Strict需要命中这些时刻，也可插入额外步。这使“活动Strict＋稠密时刻表”成为明确的优先诊断项，
但尚不能将历史26倍差距全部分配给它，也不能声称切Free或DP5后已经保持峰形精度。
下一次应对同冻结初态/场做活动Generalized-α下的Free/Strict配对，再单独比较方程形式，
保留检测事件、身份和时间误差预算。

三个Int/IntArray属性未解码并在快照中明确标为unsupported：两个Variables的notlistsolnum，
以及Time的tstepsstore；当前分别选择auto与tout=tlist，因此不影响上述活动分支判断。
不能把备用`atolglobal=1e-3`解释为活动绝对容差，也不能把自动分支下的
`maxstepgenalpha=0.1`或`initialstepgenalpha=0.001`当作实际步长。

追加轮中CPT四例完成后，场探针读取不存在的`meshInfo.numvtx`字段失败，尚未求场；
该父run按[failed终态][followup-failed]保留，不能因CPT完成而改成success。
修正为按`meshData.vertex`尺寸计数后，新run保持场/回读输入字节不变，只继续剩余两项，
[恢复run][followup-recovery]完成并通过manifest全量校验。两轮均保留冻结配置、来源SHA、
属性、日志与轻量误差证据；一次性源码发布后删除，不新增正式工作流。

### 下一次原生性能试验怎样得到明确答案

以同一冻结粒子集和一个代表传播段做受控pilot：oa-TOF沿已有N100承载方式，
避免重开极小N兼容调查；MR先沿已成功的单ID6短段估价，再加入少量离轴代表粒子，
不默认用N100启动昂贵追踪。
一次只改变一项，并以同一终态误差预算验收：

1. **原配置重复：** 记录实际活动方法、步数、评价数、Tfail、场/粒子DOF和阶段时间，分开冷启动与重复。
2. **同方法/同精度、仅输出变化：** 保持内部步控制并检查实际内部步序列是否改变；
   减少非关键输出，检测事件与原算法配对。输出时刻可能触发附加计算，不先假定全是存储成本。
3. **同场、仅积分控制变化：** 做max-step/容差轴；若方法适用，再比较DP5与现有方法。
4. **同网格、仅场恢复变化：** raw/PPR分别做精度—耗时比较，不以能量或图像单一指标取代事件。
5. **解析力诊断：** 在同几何/同粒子框架中用受控简单力定位框架开销；它改变物理，只用于定位，
   不算等价加速，也不能单独把全部时间差分配给FEM搜索。
6. **与SIMION比较：** 统一物理段、粒子、终止/输出负担和各自收敛后的误差目标；两边都单列求场。

若需要在CPT内部用预采样的规则场替代原FEM评价，优先评估原生Interpolation function配合
Electric Force的受支持组合，作为另一个场表示候选。采样步距、插值、外推、窗界/空值及
`E=-∇V`的一致性都要验证；预采样不天然守恒，也不能替代原几何壁面。
原生Interpolation→Electric Force→CPT路线已在本次小模型实际贯通，并核验坐标单位、
范围外报错及解析轨迹；详见[快速未知项闭合](#快速未知项闭合)。大型FEM替代的收益仍需实际模型，
不能预先承诺赶上SIMION。[S20][S32]

### 快速未知项闭合

第三轮专门检查能在小模型或只读回查中回答的问题，仍通过公共入口串行执行。
粒子小模型沿用10 mm立方体、4,879个四面体、100个40 Da单正电离子，
出生位置x=−4 mm、y/z各10点覆盖±1 mm，初速(1000,0,0) m/s，最后的非步点墙复验改为1170 m/s。
除墙测试10 μs外，积分区间均为1 μs；无空间电荷、碰撞或粒子反馈。
解析受力测试没有静电场求解，不拿它代替仪器场精度验证。

#### 脉冲、RF与墙事件

使用一阶Newtonian/DP5、`rtol=1e-8`、1,001个等间隔输出时刻。
以下误差为全部保存时刻、全部粒子的最大值，不能和只看终点的误差混用，也不是连续时间误差上界。
完整冻结配置、每例日志和原始误差见[时间/事件诊断][closure-time]。

脉冲为`Ex=100 V/m`、仅在0.45≤t<0.46 μs开启，解析速度增量2.412133304 m/s：

| 控制 | steps / Res / Tfail | 终点速度增量 (m/s) | 最大位置误差 (mm) | 最大速度误差 (m/s) |
|---|---:|---:|---:|---:|
| Free，自动初始/最大步 | 1 / 7 / 0 | 0 | 1.31461e−3 | 2.41213 |
| Free，最大步2 ns | 508 / 3717 / 23 | 2.406924016 | 2.83149e−6 | 5.20929e−3 |
| Strict，1 ns输出网格 | 1006 / 7168 / 18 | 2.412136539 | 1.75693e−8 | 1.75692e−3 |

自动Free完整漏掉10 ns脉冲，稠密输出没有补回受力，`Tfail=0`不能证明正确。
2 ns限步显著改善，但速度增量仍低约0.216%，不能称已收敛。
Strict终点增量误差约3.23e−6 m/s，与边沿附近的全程最大速度误差不同；边沿仍发生拒步。

RF为`Ex=100 cos(2π·10 MHz·t) V/m`，初始步自动、Free，区间恰为10个周期：

| 最大步 | steps / Res / Tfail | 最大位置误差 (mm) | 最大速度误差 (m/s) |
|---|---:|---:|---:|
| 自动 | 77 / 679 / 15 | 1.00802e−7 | 7.24720e−3 |
| T/20=5 ns | 201 / 1407 / 0 | 1.42791e−9 | 8.86074e−5 |
| T/40=2.5 ns | 401 / 2807 / 0 | 8.95537e−11 | 5.59174e−6 |

后两例终点速度增量已接近零，周期内最大误差却不同。因此RF资格至少检查相位内状态，
不能只比较整数周期终点；T/20或T/40都不是通用精度保证。
本次反例证明：**Free输出密度、内部步控制和波形解析是三件事。**
实际脉冲应采用能分辨边沿的活动限步、受支持的事件/分段方案并做减半比较；
这里没有把简单`if`方波的结果推广为所有Events功能的性能结论。

墙测试关闭电场，1000 m/s自由飞行，x=+5 mm壁面采用原生Freeze；精确撞壁时刻9 μs。
固定Free最大步50 ns，分别保存12点（不含9 μs）和1,001点：两例均200步、1400次Res、
Tfail=0、100/100粒子冻结，`cpt.st`距解析时刻最大差约3.73e−20 s，壁面x误差为0；
Freeze保存撞壁时的1000 m/s速度。它证明停止信息不必落在输出点上，
但9 μs恰与50 ns内部网格吻合，故单凭这组数据不能证明任意非步点的定位精度。
`cpt.fs`是最终状态信息，不可把它按每个输出时刻解释成当时的活跃状态。
此例开启了`StoreParticleStatusData`以取得停止时刻，与外部从离散轨迹插值检测面的算法不同。[S38][S39]

为排除与内部步点碰巧重合，又保持两种输出网格、几何和求解控制不变，只将初速改为1170 m/s。
解析撞壁时刻7.692307692 μs既不在50 ns内部网格上，也不在12点或1,001点输出表上。
两例仍为200步/1400次Res/Tfail=0，100/100冻结，x误差为0，停止时间最大误差2.03e−20 s，
保留入射速度1170 m/s。[非步点墙复验][closure-wall]
这进一步确认此简单平面匀速例中的原生事件定位可独立于普通步点及输出点；
舍入量级误差不能推广成曲面、近切向、复杂电场或整机检测时刻的精度保证。

#### 输出附加量及速度通道

统一100 V/m常力、初始步1 ns、最大步50 ns、1,001个输出时刻，
`rtol=1e-8`、scaled绝对容差factor=0.1；二阶Generalized-α的`rhoinf=0.75`。
每例同时读取默认`mphparticle`的p/v及显式
`qx/1[mm]`、`qy/1[mm]`、`qz/1[mm]`、`cpt.vx/1[m/s]`等6通道。
实测所有例的默认p数值与显式mm位置一致，默认p再乘1000会错；应以明确单位表达式建立消费合同。
数据与原生日志见[输出控制复验][closure-output]。

| 活动方法/策略 | reacf / storeudot | steps / Res | 最大位置误差 (mm) | 默认v最大误差 (m/s) | 显式cpt.v最大误差 (m/s) |
|---|---|---:|---:|---:|---:|
| 二阶Generalized-α/Free | on / on | 25 / 50 | 7.53792e−5 | 1.25442e−9 | 1.25442e−9 |
| 二阶Generalized-α/Strict | on / on | 1000 / 1999 | 3.89279e−10 | 7.77842e−7 | 7.77842e−7 |
| 一阶DP5/Free | on / on 或 off / on | 22 / 154 | 3.55271e−15 | 1.60185e−10 | 4.77485e−12 |
| 一阶DP5/Free | on / off 或 off / off | 22 / 154 | 3.55271e−15 | 0.120607 | 4.77485e−12 |
| 二阶Generalized-α/Free | on / off | 25 / 50 | 7.53792e−5 | 6.03033 | 6.03033 |

七例Tfail均为0；关闭storeudot的配对位置数组完全相同，速度后处理却发生变化。
因此位置一样、步数一样、Tfail=0都不能替代速度精度验收。
一阶形式的显式`cpt.v`在此例未受关闭storeudot影响，而默认v仍受影响；
二阶形式即使改成显式表达式也不能恢复缺少导数存储后的速度精度，终态速度误差亦有2.89456 m/s。
官方说明存储时间导数有助于时间导数后处理准确度，但本实验不声称已解析其内部闭源实现。[S22]
结论是按实际物理形式和消费通道决定是否关闭，不将该选项列为无损通用加速开关。

Generalized-α/Free减少内部步，但在插值输出处的位置误差明显大于Strict；
不能把其步数减少直接写成同精度收益。本表不是积分器性能排行。
DP5四组reacf切换没有改变步数或结果，与官方“RK不支持该反力计算”的限制一致；
不能靠字段存在或布尔读回证明该功能实际参与运算。[S22]
Free的最后内部步可以超过请求终点再插值，本例GA为1.013 μs、DP5为1.011 μs，
保存数据仍截止1 μs，不应据此误判为越时失败。

#### COMSOL原生插值场路线及真实单位陷阱

建立`Interpolation(source=file, struct=grid, interp=linear, extrap=none)`，
通过Electric Force的用户定义表达式`field_interp(x,y,z)`在COMSOL内部查询，无逐步MATLAB回调。
用90个规则节点表示`Ex=100+10000x` V/m（x以m计），轨迹可用双曲函数解析解核对。
该外加仿射场有非零散度，作为接口诊断，并非无电荷真空Laplace解或生产场。[S37]

首次运行只有导入前的`argunit=mm,mm,mm`设置：`importData()`后实际回读为空，
本应60 V/m的x=−4 mm处得到99.96 V/m，最大位置偏差0.0440280 mm、速度偏差83.7344 m/s。
求解器仍正常返回，因此[该run][closure-failed]明确标为failed，不能用“运行成功”掩盖消费单位错误。
当时所谓越界点也因坐标缩放仍落在表内，不构成外推错误证据。

新run保持科学配置和网格文件相同，**导入后逐项重设单位并核对实际值**：
再次记录到导入前mm→导入后空单位→重设后mm，因果链可复查。
修正后5个含非节点的场采样误差为0，x/y/z三个真正越界点均返回
`Interpolation function is out of range`；解析表达式与插值场两例的保存时刻最大误差相同：
位置6.34790e−11 mm、速度1.03844e−8 m/s。[插值复验][closure-interpolation]

这关闭了本机原生插值场能否驱动CPT、单位怎样处理和禁止外推是否生效的问题。
它没有证明任意三维表的数据排列、非线性插值误差、实际FEM导出守恒性或大型MR场查询收益。
生产接入仍应对真实场各分量和坐标方向做共同点验证，保持原几何壁面。

#### 正式资产的额外只读核验与启动兼容性

同一冻结oa-TOF MPH再次只读载入并回查：`UsePPR=0`、`StoreExtra=0`、
`StoreParticleStatusData=0`；全部12个`ideal_*`参数为0，Electric Force三分量最终消费
`es.Ex/Ey/Ez`原始有限元场。正式文件完整SHA在回读前后相同，未Compute、未保存。
因此不能把PPR或额外墙状态存储当作该资产已经开启的耗时来源；若要使用上述`cpt.st`路线，
需要明确启用并验收相应状态数据。[正式受力回查][closure-formal]

装配模式`on`使启动器的两次干净启动均在MATLAB任务前退出，原生stdout明确拒绝该枚举，
列出`off/matrix/vector/all`；这与当前入口和官方6.4 Windows命令页列`on`不一致。[S40]
父run的终态记录形成时尚未归因，保持原记录不改；其原始stdout在最终复验run中作为输入冻结。
默认`auto`完成17例诊断，随后`matrix`完成上述2项共9例粒子复验，接口可用性已实际确认。
未用大型静电装配压力试验，故“matrix修复MR断言/节省多少内存”仍无结论。
当前共享入口不接受`all`，本次未修改入口或绕开它启动商业软件。

各次恢复保留原失败，不覆盖证据：此轮父run启动失败；r02完成各诊断但插值单位不符，
终态failed；r03只重做插值和输出双通道，终态success。r03两项任务本体合计约31.17 s，
不含启动/退出；这仅说明诊断成本小，不能用来和历史大型CPT作速度对比。
各run保留冻结输入、源码SHA、属性回读、原生日志和轻量结果，经过保留策略与manifest全量核验；
一次性源码随后删除，无新增MPH或正式工作流。[恢复记录][closure-recovery]

### 结论状态与大型模型边界

| 原问题 | 本次明确结论 | 还需要真实仪器模型的部分 |
|---|---|---|
| 更细网格是否必然更准确 | 否；同网格加严停止可将可表示线性场的误差降多个数量级，必须隔离代数与空间误差 | 各仪器目标量的空间收敛及足够的局部尺寸 |
| COMSOL是否都在用BDF | 否；小模型一阶DP5、二阶Generalized-α，冻结oa资产实为后者/Strict | 不能补造缺少字段的旧MR运行身份 |
| 稠密输出是否保证RF/脉冲解析 | 否；Free完整漏脉冲，RF限步减半改变周期内误差 | 实际波形、端部场、碰撞下的合格步长 |
| Strict→Free能否直接无损提速 | 不能保证；同方法对照已见位置插值误差变化 | oa实际检测器事件、R与同精度耗时 |
| 关闭反力/导数存储是否通用安全 | 否；RK不支持前者，后者影响速度且依赖形式和消费通道 | 实际提取链可否删、能省多少时间/内存 |
| 原生墙事件必须有输出点命中吗 | 本例不需要；稀疏输出下停止时刻仍准确 | 实际曲面、孔边、检测器及多次事件 |
| 原生规则表能否驱动CPT | 可以；单位回读/导入顺序和禁止外推已实测 | 真实非线性三维场采样收敛、守恒性及速度 |
| oa当前是否PPR/额外壁面状态拖慢 | 回读显示均关闭；场仍是原始FEM，Strict与稠密输出确实存在 | 各成本的定量占比与可消除的同精度差距 |
| 装配参数能否启动 | 本机on失败；auto和matrix实际成功 | MR装配断言、压力下内存收益与稳定性 |
| COMSOL比SIMION慢约26倍是否已解释完 | 已定位实测差距、方法/输出差异及结构性候选；不是多求了一次静电场 | 同精度、同输出、代表规模的配对profiling，不能由小模型分摊26倍 |

官方支持的线性叠加、局部/扫掠网格、直接/迭代法等原理已有明确适用条件，不另列为未知。
尚未执行的模型分区、BEM、硬件/线程或场表示方案是候选工程方案，不是已承诺的收益。
需要保留的大模型问题集中于：**整机功能精度、实际规模的耗时/内存收益、失败模型能否恢复**。
本次没有用小模型的成功替这些问题作结论，也没有启动新的大型campaign。

## 建议的最小验证顺序

本报告只提出可审阅的后续研究顺序，不启动新的campaign，不改写当前Formal资产。
使用项目已有入口和[公共多极杆机制](../../common/multipole/README.md)，避免另造运行器。

| 顺序 | 固定什么、只变什么 | 能回答的问题 |
|---|---|---|
| 1 | 冻结现有几何/源/场/观察量，拆分各阶段计时 | 当前资源究竟耗在建模、求场、飞行还是保存 |
| 2 | 同一网格固定其它控制，只加严代数停止，必要时冷重求 | 是否应先解决停止误差/状态混杂 |
| 3 | build-only检查分区/尺寸/质量；field-only检查共同点 | 新网格策略是否合法、是否在预算内改善目标场 |
| 4 | 同一已可信场，只改变粒子积分或输出/提取轴 | 原生CPT速度差的可消除部分及准确度代价 |
| 5 | 同几何和粒子，分别细化最敏感空间方向 | 主要场与功能指标是否趋稳 |
| 6 | 固定选定场再做内部时间步、开关、墙事件验证 | 积分是否足够，输出是否仍准确 |
| 7 | 冻结合格设置，用合同规定样本做最终复核 | 资格、峰形/尾部、跨求解器比较和成本是否同时满足 |

项目优先级建议：

- **MR：** 先固定求解状态与场消费方式，检查槽壁—间隙—束路、慢向小场与父边界；用同入口单镜定位，
  再做全程。当前mesh4已昂贵，不能默认继续全域加密。原生CPT先做每步场评价成本诊断。
- **多极杆：** 先复用均匀段swept＋端部tet的分区思想，对段隙和handoff局部细化；
  将RF输出采样与实际积分控制分开核对。hex旧campaign已退役，不能直接恢复为活动资格矩阵。
- **oa-TOF：** 优先审查原生追踪和结果提取；沿已有分段输出经验保持事件精度。
  先对本次确认的Generalized-α/Strict与稠密输出表做单变量配对，勿只设置闲置的tstepsbdf。
  原加速器0.5 mm参考仍有旧N100的R变化6.63%记录，不把“更接近SIMION”作为选档标准。
- **独立OA：** 先验证器件模型与脉冲/边缘场，不继承整机Formal。
- **IP：** 先建立原生COMSOL静电基场和小范围狭缝/端域对照，再引入RF/脉冲/碰撞；
  0.1 mm SIMION场网格附近的微米级接触判定不能自动成为真实边界证据。

所有提速比较应保持相同物理及声明精度。能降低成本但尚未有配对证据的结果记为候选；
预算耗尽但未辨别精度的结果记为不确定。一个小段快、一个子集通过，均不能推广为整机提速倍数。

## 官方资料及采用边界

下列原文均于2026-10-21在线查阅。优先使用COMSOL 6.4手册与官方应用案例；
较早博客只借用明确的数学/建模原则，不照搬旧版界面、默认值和许可说明。
SIMION滚动在线手册的页眉版本不等于本机许可证版本，新功能须以本仓库实际环境重新核验。

| 标记 | 官方原文 | 本报告采用的范围 |
|---|---|---|
| S01 | [Error: Out of memory][S01] | 从小模型估计资源；避免固定单元数容量传说 |
| S02 | [Performing a Mesh Refinement Study][S02] | 按关注量比较逐级网格 |
| S03 | [Understanding and Changing the Element Order][S03] | 阶次、精度与资源之间的关系 |
| S04 | [Fillet Away Your Electromagnetic Field Singularities][S04] | 理想尖角场奇异及圆角的物理含义 |
| S05 | [Improving Your Meshing with Swept Meshes][S05] | 规则薄区与复杂区分区建网 |
| S06 | [Quadrupole Mass Spectrometer, 6.4][S06] | 端部场、swept、DC/AC和粒子研究 |
| S07 | [Einzel Lens, 6.4][S07] | 真空求场、边缘场细化、PPR示例 |
| S08 | [How to Inspect Your Mesh][S08] | 质量统计、位置和不同质量定义 |
| S09 | [Error Estimation, 6.4][S09] | 可微functional的误差估计 |
| S10 | [Adaptive Mesh Refinement, 6.4][S10] | 资源上限、多解及结构化网格限制 |
| S11 | [Electrostatics, Boundary Elements, 6.4][S11] | BEM物理适用域及替代候选 |
| S12 | [Using Symmetries, 6.4][S12] | 几何和激励共同满足对称 |
| S13 | [Infinite Elements, PMLs, and Absorbing Layers, 6.4][S13] | 静电无穷域与波动吸收域的区别 |
| S14 | [Direct, 6.4][S14] | LU内存、out-of-core和reuse |
| S15 | [Choosing the Right Linear System Solver, 6.4][S15] | 直接/迭代和正定条件 |
| S16 | [The Iterative Solvers, 6.4][S16] | 残差、预条件器和停止误差 |
| S17 | [Iterative, 6.4][S17] | 误差因子和迭代设置 |
| S18 | [Out of Memory During Assembly][S18] | 装配与求解峰值、非局部稠密耦合 |
| S19 | [Particle Tracing Module][S19] | 原生轨迹、外场及多种积分器能力 |
| S20 | [Electric Force, 6.4][S20] | 冻结/谐波/周期场和PPR |
| S21 | [Choosing a Formulation, 6.4][S21] | 一阶/二阶默认方法 |
| S22 | [Time-Dependent Solver, 6.4][S22] | 输出、容差及Free/Strict等活动方法设置 |
| S23 | [Geometry and Mesh Settings, 6.4][S23] | 粒子与体/边界网格及曲面几何阶次 |
| S24 | [SIMION Calculation Time][S24] | 飞行步数、显示/记录和用户程序成本 |
| S25 | [SIMION Trajectory Programming Techniques][S25] | T.Qual、Grouped、RF限步和输出时刻 |
| S26 | [Accumulators, 6.4][S26] | 粒子之外的网格相关未知量 |
| S27 | [Collisions, 6.4][S27] | 碰撞算法与时间分辨要求 |
| S28 | [Charged Particle Tracing, 6.4][S28] | 单向/双向耦合及粒子间相互作用复杂度 |
| S29 | [Theory for the Boundary Elements PDE, 6.4][S29] | 常系数、稠密矩阵及默认迭代/远场近似 |
| S30 | [The Electrostatics Interface, 6.4][S30] | 电势默认二阶形函数 |
| S31 | [Time API, 6.4][S31] | 活动积分分支、DP5步进属性、输出附加计算 |
| S32 | [Defining Model Settings Using External Data File, 6.4][S32] | 原生Interpolation函数及插值/外推设置 |
| S33 | [Controlling the Time Dependent Solver Timesteps][S33] | 输出点、自动初始步及内部时间步区别 |
| S34 | [Stationary Solver API, 6.4][S34] | control=user下stol的意义 |
| S35 | [Stationary Study API, 6.4][S35] | Study的usestol/stol控制 |
| S36 | [SolverSequence API, 6.4][S36] | clearSolutionData及只读解序列检查 |
| S37 | [model.func API, 6.4][S37] | 原生文件插值、导入及函数属性 |
| S38 | [Wall, 6.4][S38] | Freeze及壁面相互作用语义 |
| S39 | [Mathematical Particle Tracing, 6.4][S39] | 状态/停止时间数据的存储与含义 |
| S40 | [COMSOL Commands on Windows, 6.4][S40] | 装配模式公开枚举；本机兼容性以实际日志为准 |

[S01]: https://www.comsol.com/support/knowledgebase/1030
[S02]: https://www.comsol.com/support/knowledgebase/1261
[S03]: https://www.comsol.com/support/learning-center/article/Understanding-and-Changing-the-Element-Order-47301
[S04]: https://www.comsol.com/blogs/fillet-away-your-electromagnetic-field-singularities/
[S05]: https://www.comsol.com/blogs/improving-your-meshing-with-swept-meshes/
[S06]: https://doc.comsol.com/6.4/doc/com.comsol.help.models.particle.quadrupole_mass_spectrometer/quadrupole_mass_spectrometer.html
[S07]: https://doc.comsol.com/6.4/doc/com.comsol.help.models.particle.einzel_lens/einzel_lens.html
[S08]: https://www.comsol.com/blogs/how-to-inspect-your-mesh-in-comsol-multiphysics
[S09]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_solver.36.179.html
[S10]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_solver.36.160.html
[S11]: https://doc.comsol.com/6.4/doc/com.comsol.help.acdc/acdc_ug_electric_fields.07.037.html
[S12]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_modeling.19.040.html
[S13]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_definitions.21.133.html
[S14]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_solver.36.173.html
[S15]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_solver.36.144.html
[S16]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_solver.36.149.html
[S17]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_solver.36.185.html
[S18]: https://www.comsol.com/support/knowledgebase/1186
[S19]: https://www.comsol.com/particle-tracing-module
[S20]: https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_acdc.07.22.html
[S21]: https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_modeling.05.09.html
[S22]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_solver.36.139.html
[S23]: https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_modeling.05.10.html
[S24]: https://simion.com/info/calculation_time.html
[S25]: https://simion.com/info/trajectory_programming.html
[S26]: https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_modeling.05.17.html
[S27]: https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_acdc.07.04.html
[S28]: https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_modeling.05.04.html
[S29]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_equationbased.32.053.html
[S30]: https://doc.comsol.com/6.4/doc/com.comsol.help.acdc/acdc_ug_electric_fields.07.002.html
[S31]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_solver.51.51.html
[S32]: https://doc.comsol.com/6.4/doc/com.comsol.help.llmatlab/llmatlab_ug_model.6.32.html
[S33]: https://www.comsol.com/support/knowledgebase/1254
[S34]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_solver.51.47.html
[S35]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_solver.51.79.html
[S36]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/api/com/comsol/model/SolverSequence.html

[S37]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_general.47.34.html
[S38]: https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_math.06.04.html
[S39]: https://doc.comsol.com/6.4/doc/com.comsol.help.particle/particle_ug_math.06.02.html
[S40]: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_ref_running.38.31.html

[closure-time]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_104700__test__comsol__quick-unknown-closure__r02/results/time_events_summary.json
[closure-output]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_104700__test__comsol__quick-unknown-closure__r03/results/output_controls_summary.json
[closure-interpolation]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_104700__test__comsol__quick-unknown-closure__r03/results/interpolation_summary.json
[closure-formal]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_104700__test__comsol__quick-unknown-closure__r02/results/formal_force_summary.json
[closure-failed]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_104700__test__comsol__quick-unknown-closure__r02/summary.json
[closure-recovery]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_104700__test__comsol__quick-unknown-closure__r03/summary.json
[closure-wall]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_104700__test__comsol__quick-unknown-closure__r04/results/time_events_summary.json

[oa-perf-summary]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20260810_121500__benchmark__cross__cpu-formal-n1000/summary.json
[oa-perf-config]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20260810_121500__benchmark__cross__cpu-formal-n1000/run_config.json
[oa-perf-log]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20260810_121500__benchmark__cross__cpu-formal-n1000/logs/comsol_report.txt
[mr-cpt-summary]: ../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261007_135633__analysis__comsol__mrtof-id6-slow-return-raw-cpt__r02/summary.json
[mr-cpt-log]: ../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261007_135633__analysis__comsol__mrtof-id6-slow-return-raw-cpt__r02/logs/solver_progress.log
[mr-mesh4-summary]: ../../../artifacts/projects/parallel_mirror_dual_stripe_mr_tof/runs/20261015_164500__analysis__comsol__positive-turn-mesh4-longest__r02/summary.json
[probe-config]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_101009__test__comsol__uniform-field-cpt-probe__r02/inputs/probe_config.json
[probe-summary]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_101009__test__comsol__uniform-field-cpt-probe__r02/results/probe_summary.json
[probe-metrics]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_101009__test__comsol__uniform-field-cpt-probe__r02/results/log_metrics.json
[probe-failed]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_101009__test__comsol__uniform-field-cpt-probe/summary.json
[followup-cpt]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_102831__test__comsol__field-and-cpt-followup/results/probe_summary.json
[followup-metrics]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_102831__test__comsol__field-and-cpt-followup/results/log_metrics.json
[followup-field]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_102831__test__comsol__field-and-cpt-followup__r02/results/field_followup_summary.json
[followup-readback]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_102831__test__comsol__field-and-cpt-followup__r02/results/oatof_readback_summary.json
[followup-failed]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_102831__test__comsol__field-and-cpt-followup/summary.json
[followup-recovery]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_102831__test__comsol__field-and-cpt-followup__r02/summary.json
