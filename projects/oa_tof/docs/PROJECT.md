# oa-TOF 当前项目状态

本文件只保存当前权威状态、关键验收结果和开放任务。人工设计以
[`../config/baseline.json`](../config/baseline.json)为准，程序读取自动生成的
`../config/resolved_geometry.json`并按`../config/modes/`运行；精确性能、资产身份和分析定义分别以
`../config/formal_validation.json`、`../config/simion_stable_entry.json`和
`../config/analysis_contract.json`为机器权威。详细诊断过程只进入`docs/history/`，不得反向覆盖本文件。

## 当前正式状态

- 方案：524 amu、+1电荷的正交加速TOF，双级环栈反射镜，一级10环、二级5环；初始能量
  `5±0.4 eV`，负能量重采样。
- 统一坐标：检测器有效面中心与精确一阶时间焦点为`z=0`，`+z`从加速器指向反射器；COMSOL与CAD
  直接使用此坐标，SIMION局部PA必须通过IOB变换映射到同一坐标。
- `baseline → resolved → COMSOL/SIMION/CAD`是唯一参数链。现有软件文件、网格坐标和GUI显示不能
  反向修改baseline；候选覆盖不能改写正式参数。
- baseline表示“当前已批准的正式设计”，不是每次需求的优化输出，也不是永远不可演进。每次需求先
  生成隔离`candidate_baseline`；候选通过验收后仍不自动修改baseline。仅当所有候选门禁通过且所有者
  明确批准其取代当前正式设计时，才在独立晋升运行中原子更新baseline、resolved和全部formal资产；
  一次性交付或未批准候选均保持现行baseline不变。
- 正式COMSOL MPH、SIMION四实例自包含交付和SolidWorks 2022的25组件装配均已建立并通过各自
  资产门禁。SIMION正式PA顺序为`shield 1 < reflectron 2 < accelerator 3 < detector 4`。
- 当前只完成oa-TOF分析器本体；尚未与RF四极杆正式连接。

2026-07-20 RF项目新增了指向本项目当前源中心的求解器无关handoff draft及静态派生器。它保留跨任意
上游部件累计的全局仪器时间、根粒子谱系年龄、当前粒子年龄、末组件耗时和谱系身份，并可从RF
handoff状态派生现有固定ION格式；
两份归档N=100 RF数据的只读格式转换均通过。该工作没有修改本项目baseline、正式粒子源、COMSOL MPH、
SIMION包或CAD，也尚未形成oa-TOF外部handoff运行入口。RF轴0 V到本项目高压出生区的电气参考、真实
间隙/孔径/注入光学和下游功能接受度仍未闭合，因此本项目的`contracts.interface`继续为`null`，正式状态
不变。候选详情以RF项目`config/rf_to_oatof_handoff.json`为当前实例来源；只有本项目实际消费验证后才
评估形成共享接口代码。

## 物理与几何基线

紧凑三栅加速器保持对称等间距：`d1=3.0 mm`、`d2=16.8 mm`，五环中心间距均为`2.8 mm`。
repeller/grid1/grid2全局z为`-19.92918680341103/-16.92918680341103/
-0.12918680341103 mm`；释放体为`1×1×1 mm³`，轴向范围
`-18.92918680341103...-17.92918680341103 mm`。加速器平移量和焦点位置来自解析式，不得按显示
精度手工取整。

反射器一级长度`120 mm`、二级工程长度`86.8328 mm`，总反射区`206.8328 mm`；工程长度保留四位
小数。屏蔽罩内半径`350 mm`，侧壁和端盖厚度`10 mm`。加速器出口的`30×30 mm`理想透明栅网是
独立器件，不是屏蔽罩端盖。

SIMION日常加速器网格为`xy=0.25 mm,z=0.05 mm`，`z=0.025 mm`只作轴向收敛参考；轨迹质量为8。
检测器数值PA半径`40 mm`、有效面`z=0`、槽位与GUI优先级均为4。其0.1 mm吸收层只负责数值终止，
不等于COMSOL/CAD中的机械检测器厚度。

反射器长度、电压及所有派生坐标的完整公式和精度规则位于baseline及`docs/theory/`。修改加速器或
反射器前必须先重算理论，再同步三个软件和CAD，不得在本文件另建公式副本。

## 当前验证结论

质量分辨率统一定义为`R=m/FWHM_m`；窄峰时间域等价式为`R=T/(2*FWHM_t)`。只有近似高斯时才可
用`2.3548×sigma`代替直接半高宽。求解器无关分析由Python 3.11参考实现执行。

`config/formal_validation.json`冻结的同源N=1000正式比较为：

| 指标 | COMSOL | SIMION |
|---|---:|---:|
| 命中 | 1000/1000 | 1000/1000 |
| 平均TOF (us) | 71.99021389 | 71.99101518 |
| 直接质量FWHM (Da) | 0.01346719723 | 0.01177287159 |
| 质量分辨率R | 38909.36 | 44509.11 |

该记录由`20260718_172003__sim__cross__formal-validation__n1000`直接加载当前正式MPH和当前正式SIMION包重算，平均TOF差
`0.80130 ns`、逐粒子TOF RMS差`1.09302 ns`、落点RMS差`0.14351 mm`。标准化KDE重叠为
`0.72556`；5000次配对bootstrap的绝对R差异2.5%/中位数/97.5%分位为
`0.963%/12.824%/24.101%`。下限接近零，说明直接FWHM差异对多模态重采样仍敏感；不能把单一R差
解释为确定的场误差，也不能为追平它而调网格、时间步、quality或场参数。

现有原因定位表明：反射器内部独立场相对RMS差约`0.000528%`，主要差异来自加速区纵向场和
z-to-TOF映射。COMSOL加速器`hmax=1 mm`是日常档，`0.5 mm`是收敛参考；后者改善横向梯度伪影，
但没有消除纵向焦点差。SIMION fractional surface使静电场基本不受网格相位影响，但固定距离越过
透明数值栅网会放大粒子TOF差；当前加速器和反射器跳转均为`0.0001 mm`。

2026-07-19复用保存数据完成纵向归因闭合。当前正式N=1000逐粒子`SIMION-COMSOL TOF`差与初始z
相关系数为`0.97150`，z二次项解释`94.9506%`差值方差，加入能量/x/y仅增至`94.9564%`。释放区
COMSOL电势导数与直接`es.Ez`的RMS差仅`7.206 V/m`，是同坐标跨求解器Ez RMS差
`1344.091 V/m`的`0.536%`。因此COMSOL梯度读取和横向源变量均不是主因；统一契约又排除了有意
几何/电压参数差。剩余差异归类为两端栅网/边界局部场的数值表示差异经z-to-TOF映射放大，但不把
现有证据延伸成对某个闭源内部插值实现的断言。该项无需新增昂贵网格对照。

先前严格聚焦staging比较与当前直接重算的平均TOF差、逐粒子TOF RMS差和落点RMS差分别为
`0.84220/1.12383 ns/0.14466 mm`与`0.80130/1.09302 ns/0.14351 mm`，结构一致。前者现只作为
提升过程证据；当前权威只引用新版`formal_validation.json`及其直接运行产物。

2026-07-18用同一正式N=1000配对结果完成后处理接受度诊断。`4--6 eV`只删除17/1000个粒子；
在统一保留粒子数的200次无放回重采样中，能量窗和检测器有效半径收紧均未改善峰宽。全部落点
仍位于约13.5 mm半径内，远小于40 mm正式有效半径。共享轴向释放宽度从`1.0 mm`收紧到
`0.4 mm`、保留429/1000粒子时，匹配样本FWHM中位数由COMSOL/SIMION的
`0.01430/0.01375 Da`降到`0.00634/0.00375 Da`。因此当前宽肩主要来自释放区轴向位置到TOF的
映射，不是极端能量或远轴命中；该结果表示以57.1%源接受度损失换取窄峰，不能写成无代价的
分析器分辨率提升。结果位于
迁移前证据冻结在`artifacts/projects/oa_tof/archive/20260719_212436__migration-snapshot__repo__pre-v2-layout/legacy-layout/results/cross_solver/truncation/current_assets_n1000_20260718/`，未改变
正式模型或`formal_validation.json`。

2026-07-18五点宽质量标定候选已完成：`m/z=10/100/500/1000/2000`各40粒子，COMSOL按质量
分批复用正式`sol1`静电场，SIMION一次混合飞行；两端均为每种40/40、总计200/200命中。质心结果为：

| m/z | COMSOL平均TOF (us) | SIMION平均TOF (us) | SIMION-COMSOL (ns) |
|---:|---:|---:|---:|
| 10 | 9.945116571 | 9.945159136 | 0.042565 |
| 100 | 31.449056286 | 31.449351207 | 0.294921 |
| 500 | 70.322221527 | 70.322886490 | 0.664962 |
| 1000 | 99.450632533 | 99.451579703 | 0.947170 |
| 2000 | 140.644885589 | 140.645772733 | 0.887144 |

按`sqrt(m/z)=slope*TOF+intercept`分别标定，COMSOL/SIMION质量残差RMS为
`0.00273689/0.00000297421 Da`，最大绝对残差为`0.00475197/0.00000540759 Da`。该经济样本只证明
五点峰位、标定、100%传输率和跨求解器质心闭合，不作精确FWHM或分辨率声明。结果位于
迁移前证据冻结在本项目archive迁移快照的`legacy-layout/results/cross_solver/mass_spectrum/wide_mz_candidate_20260718_n40_recovered/`；
可复算manifest及原始运行证据位于对应的`runs/mass_spectrum/`目录。候选不改变524 Da正式分辨率
基线或正式资产。

2026-07-19以运行时粒子数覆盖完成五质量各N=1000候选，两端均为每种1000/1000、总计5000/5000
命中。主质量谱图改为2×3布局：五个面板分别在局部`calibrated m/z-nominal`轴上用公共分箱叠加
COMSOL/SIMION密度、均值和TOF标准差，第六面板汇总跨质量质心差：

| m/z | COMSOL平均TOF (us) | SIMION平均TOF (us) | SIMION-COMSOL (ns) | TOF σ C/S (ns) |
|---:|---:|---:|---:|---:|
| 10 | 9.945088309 | 9.945181292 | 0.092984 | 0.197/0.097 |
| 100 | 31.449072630 | 31.449421303 | 0.348673 | 0.376/0.307 |
| 500 | 70.322248656 | 70.323043227 | 0.794572 | 0.740/0.686 |
| 1000 | 99.450602949 | 99.451801364 | 1.198415 | 1.042/0.970 |
| 2000 | 140.644830772 | 140.646086209 | 1.255437 | 1.456/1.372 |

COMSOL/SIMION五点质量残差RMS为`0.00255117/0.00000294964 Da`，最大绝对残差为
`0.00425147/0.00000536345 Da`。N=1000图已能显示两端峰宽和尾部差异，故本候选只把峰形作为后续
数值/物理解释入口，`resolution_claim_allowed=false`，不以视觉重合代替正式FWHM门禁。结果位于
迁移前证据冻结在本项目archive迁移快照的`legacy-layout/results/cross_solver/mass_spectrum/wide_mz_candidate_20260719_n1000/`，原始
运行、有效N=1000模式和manifest位于对应`runs/mass_spectrum/`目录。

同一批已保存轨迹随后以统一非参数口径补算逐质量峰形；标准化KDE重叠在
`m/z=10/100/500/1000/2000`依次为`0.81183/0.77942/0.73584/0.71477/0.71268`，KS距离依次为
`0.116/0.128/0.168/0.199/0.218`。差异随质量总体增大，且峰带肩、并非稳定单高斯，因此当前不增加
叠加高斯拟合；KDE重叠与KS负责表达整体峰形差异，直方图负责显示局部宽度和尾部。纯后处理通过
`-ReanalyzeOnly`完成，没有重新运行COMSOL或SIMION。重建后的manifest收录27项输出，包括五份
独立ION、COMSOL逐物种CSV/报告、SIMION日志/CSV和分析结果；历史运行中已被同名覆盖的四份COMSOL
释放中间表无法倒推，今后释放表按物种CSV stem和N唯一命名。

同一批N=1000逐粒子数据新增五质量检测器落点图：2×3布局中每个质量单独成图，同一面板叠加
COMSOL实心点、SIMION空心点和两端质心，全部面板使用相同检测器局部坐标范围。五个质量的COMSOL
RMS半径均约`4.0127 mm`，SIMION均约`4.0018 mm`，跨求解器质心距离为`0.0742--0.0746 mm`，
最远落点约`13.2 mm`，远小于40 mm有效半径。空间分布在当前精度下基本与质量无关，符合相同电荷、
初始能量和静电几何下质量主要缩放飞行时间而不改变位置轨迹的预期。后处理同时修正了五质量SIMION
CSV的坐标语义：原始`XMm/YMm`为全局坐标，必须按统一`detector_x=48.8 mm`转为检测器局部坐标后
才能与COMSOL叠加。新图`mass_detector_landing_comparison.png`及更新后的summary/metrics已进入同一
N=1000运行manifest；没有重新运行求解器。

2026-07-19又以500 Da、同源种子和正式静电场完成单质量粒子数时间标定。COMSOL每档独立启动一次，
SIMION每档独立Fly三次；COMSOL墙钟包含MATLAB/LiveLink启动、载入、求解和导出，粒子时间只包含
`std2`，SIMION墙钟不含日志分析：

| N | COMSOL墙钟 (s) | COMSOL粒子 (s) | SIMION墙钟中位数 (s) |
|---:|---:|---:|---:|
| 100 | 444.240 | 316.004 | 4.056 |
| 300 | 518.625 | 390.247 | 10.077 |
| 1000 | 774.917 | 635.909 | 31.297 |
| 5000 | 2135.133 | 1996.048 | 151.444 |

包含N=5000的四点工程拟合给出COMSOL墙钟约`418.02+0.34388*N s`、纯粒子阶段约
`287.40+0.34197*N s`；SIMION十二个重复样本拟合约`1.088+0.030113*N s`。当前粒子数合同收敛为
N=100检查档和N=1000统计档：前者用于日常检查、质心和传输率，后者用于峰形、尾部、FWHM、
分辨率及正式跨求解器统计。N=40、N=300不再用于新日常运行，N=5000只保留给明确的性能或统计
收敛专项；已有N=1000轨迹可确定性截取前100个粒子复用为检查档。COMSOL每档
只有一次且按N递增运行，拟合只用于当前机器容量规划，不作为跨机器性能基准。证据位于
`artifacts/projects/oa_tof/runs/performance/single_mass_scaling/mz500_scaling_20260719_n100_300_1000/`
和对应迁移快照中的原`results/performance/`目录；新基准统一写入`runs/<run_id>/results/`。

统一合同落地后，SIMION正式Fly2已由N=5000改为N=1000；重建候选与更新前冻结正式包使用同一
N=1000 ION完成场、逐粒子TOF、落点和标准化峰形等价门禁，全部PASS，随后只提升粒子数合同与
文本清单，PA、IOB、Program和ION均保持字节相同。证据及manifest位于
`artifacts/projects/oa_tof/runs/simion_source_build_promotion/n1000_policy_20260719_1108/`。

## 正式资产与门禁

- COMSOL：`artifacts/projects/oa_tof/formal/comsol/oa_tof__model.mph`；GUI重开后几何、选择集、
  网格、Study/Solver、数据集和绘图组必须可检查并可由Study Compute等价复算。
- SIMION：`artifacts/projects/oa_tof/formal/simion/`中的IOB、四套PA、Lua、Fly2、
  ION、SHA和manifest；整个目录可作为同事复现包。
- CAD：正式SolidWorks装配为25个零件/25组件；几何变更必须同任务重建并检查版本、变换、保存错误
  和警告。
- 门禁：`verify_project.ps1 -Level Static|Candidate|Formal`。完整N=100/1000粒子重算和SolidWorks
  重建由相应物理、数值或几何变更触发，不塞入每次Formal身份检查。

候选只有在共享几何契约、同源粒子比较、差异解释或收敛、COMSOL GUI Compute以及SolidWorks同步
全部通过后才能转正。模型或CAD没有改变时，不为形式主义重复重建昂贵资产。

## 场方向归因实例

可组合场替换的通用定义、实验顺序和因果边界只见根
[`docs/VALIDATION_METHODS.md`](../../../docs/VALIDATION_METHODS.md)。“区域×分量”选择器在本项目
落地为COMSOL全分量能力和SIMION区域Ez能力；两端只在能力交集上比较，不用局部PA导数冒充全局
横向分量。具体COMSOL语法、GUI参数和SIMION兼容模式见各自软件文档。

2026-07-19以统一N=100完成方法可行性验证。COMSOL全局分量筛查表明，理想Ez与全理想场的时间
端点一致，而Ex/Ey主要改变落点；区域筛查又表明加速区Ez主导平均TOF响应，漂移区Ez是近零负对照。
加速区与二级反射区组合对峰宽存在明显非加性，因此不能把联合改善拆成简单贡献百分比。SIMION随后
实现同一选择器语义下的区域Ez组合，四个代表案例均100/100到达并产生可区分响应，证明该方法不依赖
单一求解器。由于当前旋转二维PA不能独立暴露全局Ex/Ey，SIMION明确只支持Ez能力交集。

本轮目标是理清脉络、建立工具并验证可行性，不要求两求解器干预后的数值高精度一致，也不形成
N=100正式分辨率声明。COMSOL运行及合并分析位于`artifacts/projects/oa_tof/runs/
field_idealization_sweep/`与`field_idealization_analysis/complete_ez_n100_20260719/`；SIMION证据位于
同一sweep根下`simion_ez_n100_20260719_retry1/`。只有未来设计决策依赖峰宽或交互量时才升级N=1000；
跨项目方法成熟度只由根验证方法文档记录。

## 已知非阻塞限制

COMSOL 6.4 build 293在当前模型的极小求解粒子数路径存在原生不稳定：固定500 Da序列中N=28在
solution-mesh初始化FAIL，N=29两次分别在结果提取和任务配置阶段原生FAIL，N=30全链路PASS；这不是
已证明只由N控制的单调阈值，也没有证据把内部根因收窄到某个闭源实现。该问题不影响当前N=100检查档、
N=1000统计档或已完成的五质量结果，因此定性为可绕开的非致命限制，不再列为开放调查任务。

新运行不得用N<30做COMSOL日常冒烟。确需逻辑小样本且模型仍无空间电荷、粒子间碰撞或其他集体效应时，
统一求解N=100同源承载集合后只分析目标前缀，并同时记录`solver_particle_count`与
`logical_particle_count`。只有出现N>=100同类失败、启用粒子间耦合后仍需小N、生产任务必须直接求解
N<30，或升级COMSOL后需要重新建立兼容边界时，才重新启动调查；详细矩阵和失败证据入口只由项目
README中的history清单提供。

SIMION正式Program以固定`0.0001 mm`距离越过一格厚的透明数值栅网；该值已通过同源N=1000、
GUI重开、正式包和CAD同步门禁，不影响当前100%传输或正式统计。固定距离仍可能把PA网格相位放大为
逐粒子TOF差，因此“自动越过实际数值电极层”保留为非阻塞精度增强，不是当前缺陷。只有项目明确
要求比现有约`1.093 ns`配对TOF RMS更严格的逐粒子闭合、正式PA/栅网表示改变后出现相位敏感或
误splat、或新用途要求跨多个网格相位保持同一判据时，才重新启动；不得为追平单一R继续扫描固定
跳转距离。详细相位与跳转矩阵已经冻结在数值验证history，不重新运行已有组合。

## 下一步

跨TOF设计族的双反射OA-TOF、MR-TOF和自然语言性能设计方向只由根
[`docs/ROADMAP.md`](../../../docs/ROADMAP.md)规划；本节只保留当前`oa_tof`设计线的开放任务。

1. **完成候选运行编排与逐变量运行时覆盖。** `config/design_variables.json`、可审查扩大的
   `config/optimization_envelope.json`和`analysis/compile_candidate_design.py`已经建立变量分类、候选覆盖、
   理论派生、几何不变量、约束与差异报告。策略固定为：TOF在当前总体包络内紧凑化且内部参数可双向
   重调；加速器尺寸和电压全部双向优化，不受TOF包络约束。超出当前包络返回
   `NEEDS_ENVELOPE_REVIEW`，批准扩大不自动改写正式baseline。静态测试证明零改动精确复现正式参数，
   也能在求解前拒绝缩短后未同步重配而发生的电极重叠；测试数值不构成候选设计建议。
   `config/candidate_consumers.json`和`analysis/prepare_candidate_consumers.py`现已闭合静态输入路由：
   COMSOL显式读取候选resolved合同，SIMION从同一合同生成隔离文本，CAD只消费该候选生成的MPH。
   零改动候选的SIMION文本与正式版本逐字一致，单一非零变量能沿计划传播；这只证明路由可行，未证明
   每个模型特征、PA/IOB或装配都正确变化。当前`config/execution_profiles.json`仍只运行固定五质量和
   524 Da正式复验。`config/candidate_workflow.json`和`analysis/prepare_candidate_run.py`进一步在scratch
   冻结候选计划及COMSOL→SIMION/CAD→跨软件验收依赖，并预声明未来单一run，禁止覆盖、禁止从formal取候选输入、
   禁止自动晋升；COMSOL候选合同构建、SIMION候选文本/合同构建和CAD候选导出入口已就位。
   `analysis/candidate_run_lifecycle.py`已闭合根三件套：在scratch组装完整失效安全运行后原子进入runs，
   success/failed/interrupted均通过artifact布局门禁，success仍只标记接受但未晋升。
   `analysis/run_candidate_workflow.py`现已集成共享N=100粒子表、COMSOL构建/同步、SIMION构建/运行时、
   CAD导出和最终结构合同验收；模拟执行器已闭合成功、失败、中断、后续阶段阻断及共享粒子表SHA门禁。
   2026-07-20零改动真实候选`20260720_111805__test__cross__zero-change-candidate-retry2__n100`已完成：
   COMSOL构建及独立回读、SIMION PA/IOB构建及运行时合同、25组件SolidWorks装配和共享粒子表SHA验收
   全部PASS，根三件套状态为`success/candidate_accepted_not_promoted`。正式baseline SHA与计划冻结值一致，
   formal未修改。该运行只证明`structural_build_and_contract`闭环，明确禁止性能声明和自动晋升；完整的
   两次失败、修复和成功证据已冻结在history。后续候选计划又把设计request/proposal与
   baseline/resolved/diff共同冻结为五项不可变run输入，启动前校验路径、SHA、Schema和身份关系，manifest
   逐项记录，因此清理scratch不再切断新run的设计来源。`design_candidate`模式及
   `validated_structural_candidate` execution profile现已把已验证runner绑定到solver-neutral计划：只有
   获批524 Da、N=100、零变量变化或已验证的`reflectron_midgrid_voltage`变化、仅传输目标且显式提供
   同request/同run_id候选计划时才返回
   `EXECUTION_READY`；缺少绑定返回`NEEDS_RUNTIME_INPUTS`，分辨率、500 Da或任何其他变量仍返回
   `NEEDS_IMPLEMENTATION`。下一步按重建影响选择其他代表性非零变量做小规模运行时覆盖，每项通过后再扩展
   profile，不一次性宣称全部变量可执行。
   代表性非零变量`reflectron_midgrid_voltage=1601 V`已在运行
   `20260720_123942__test__cross__midgrid-voltage-candidate__n100__r01`完成COMSOL、SIMION、25组件CAD和
   结构合同PASS，正式baseline与formal均未修改。该轮同时发现两项消费链缺口：COMSOL显式候选合同曾被
   理论默认电压覆盖，现已改为合同值优先；SolidWorks导入STEP时机器默认零件模板路径失效，运行依赖人工
   选择空模板后才继续。后者已改为桥接器临时绑定已安装空白模板并在结束后恢复用户设置；随后复用同批
   STEP在`20260720_132856__test__cad__blank-template-assembly__n25`完成25零件/25组件无人值守装配复验，
   零件与装配保存均为0错误/0警告且设置恢复回读PASS。因此该
   变量已纳入结构候选运行时覆盖，但本轮没有评价性能目标，也没有转正或修改formal。
2. **按需发布复现ZIP。** 从正式自包含目录生成不含日志、收敛参考和临时轨迹的ZIP及独立SHA；发送后
   ZIP可删除，源码构建链和正式目录继续保留。

以下未来任务按当前决定暂缓，不进入本轮程序/分析故障清理：

- **轴对称圆形加速器候选。** 将当前方形横向包络、接地屏蔽和理想栅网/支撑边界改为绕加速轴
  旋转对称的圆筒与圆形结构。第一阶段保持轴向位置、间距、电压和粒子源不变，只隔离“方形改圆形”
  的物理几何影响；候选须重新闭合解析焦点、三维场、传输率、峰形、网格收敛和跨求解器结果。
  物理圆形改型与二维轴对称数值降维是两个独立决策；若候选转正，必须同步COMSOL、SIMION及
  SolidWorks零件/装配，不得只修改某一软件。
- 真实丝网局部单元。
- 制造与装配误差预算。
- RF接口及二维轴对称COMSOL混合模型。
