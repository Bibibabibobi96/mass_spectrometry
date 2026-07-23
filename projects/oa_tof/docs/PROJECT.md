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
- 正式网格构建器已调用根`common/comsol/`局部Size原语；具体选择、hmax值和收敛资格仍由本项目合同
  与后续网格专项决定，公共函数不改变现有数值结论。
- CAD读取入口已用运行`20260722_121500__test__cad__load-only`对当前正式MPH完成真实只读冒烟：25个
  manifest特征和25个可导出实体均可解析，未求解、未导出STEP、未修改Formal。该结果只分层证明
  LiveLink与CAD模型读取，不替代SolidWorks同步或Formal门禁。

RF→oaTOF连接功能已经由RF项目收口。接口阶段、连接器几何、共享时钟脉冲、粒子漏斗、资格边界和
恢复条件只以RF项目[`PROJECT.md`](../../rf_quadrupole_collision_cooling/docs/PROJECT.md)及其机器合同
为权威，本项目不复制运行数字或阶段状态。本项目只维护下游格式适配和对Formal分析器的只读消费；
这些功能证据没有修改本项目baseline、正式粒子源、COMSOL MPH、SIMION包或CAD，也没有把整机连接
提升为Formal。当前Formal加速器仍是闭合屏蔽结构，没有沿RF注入方向的正式物理入口。

2026-07-20完成 oa-TOF 理论重写文档及代码审查。三份 Markdown 已取代旧 DOCX 成为活跃理论入口，
三份求解器无关 Python 已接入静态测试；原始投稿包及 SHA 已冻结在
`docs/history/20260720__oatof-theory-refactor-review/`，同名审查清单为
`docs/history/20260720__oatof-theory-refactor-review.md`。活跃理论文档的展示公式已统一使用 GitHub
官方支持的 fenced `math` 语法，避免多行公式中的行首`+`、`-`、`#`被 Markdown 误解析。
独立数值积分、有限差分、根求解及当前参数回归确认核心公式成立。审查发现旧 Formal baseline 的
`1600/2400 V`反射镜只满足局部反射镜二阶聚焦，没有补偿加速器在一阶焦面处的二阶时间曲率。
耦合纵向候选随后按完整空间能量包络和既有100%穿透深度裕量生成，N=100全链路及同源N=1000
COMSOL/SIMION比较均通过；所有者批准后已于2026-07-20原子晋升为当前 Formal baseline。旧 Formal
资产未删除，归档在
`artifacts/projects/oa_tof/archive/20260720_204500__superseded__cross__pre-coupled-baseline/`。

## 物理与几何基线

紧凑三栅加速器保持对称等间距：`d1=3.0 mm`、`d2=16.8 mm`，五环中心间距均为`2.8 mm`。
repeller/grid1/grid2全局z为`-19.92918680341103/-16.92918680341103/
-0.12918680341103 mm`；释放体为`1×1×1 mm³`，轴向范围
`-18.92918680341103...-17.92918680341103 mm`。加速器平移量和焦点位置来自解析式，不得按显示
精度手工取整。

反射器一级长度`120 mm`、二级工程长度`96.1563 mm`，总反射区`216.1563 mm`；一级压降
`1628.8001 V`，背板电位`2531.1999 V`。这些值由加速器—反射器耦合一、二阶条件和
`1920--2080 V`完整空间能量包络派生，工程长度和电压只在最终输出保留四位小数。屏蔽罩内半径
`350 mm`，侧壁和端盖厚度`10 mm`。加速器出口的`30×30 mm`理想透明栅网是独立器件，不是屏蔽罩端盖。

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
| 平均TOF (us) | 71.35283799 | 71.35358448 |
| 直接质量FWHM (Da) | 0.01235942211 | 0.01071535523 |
| 质量分辨率R | 42396.80 | 48901.79 |

该记录来自`20260720_191743__sim__cross__coupled-baseline-validation__n1000`，并已自包含发布到
`artifacts/projects/oa_tof/formal/results/`。该目录只保留当前baseline：跨求解器目录含峰形、探测落点
和源映射PNG，顶层保留两端粒子CSV、新理论比较、求解器摘要及源运行manifest；18个包内文件由
独立SHA256清单冻结。旧理论和老新baseline晋升比较只保留在源run及archive，不属于当前Formal。
当前平均TOF差
`0.74648 ns`、逐粒子TOF RMS差`1.00860 ns`、落点RMS差`0.29408 mm`；标准化KDE重叠为
`0.69227`。5000次配对bootstrap的绝对R差异2.5%/中位数/97.5%分位为
`5.017%/13.234%/21.660%`。这仍是两种离散场和轨迹积分实现的跨求解器差异，不能为追平单一R值而
分别调网格、时间步、quality或场参数。

本次升级按三条主比较线验收：

| 主比较 | COMSOL | SIMION |
|---|---:|---:|
| 老baseline R → 新baseline R | 38909.36 → 42396.80（+8.96%） | 44509.11 → 48901.79（+9.87%） |
| 老理论预测均值 / 老baseline模拟均值 (us) | 71.99006613 / 71.99021389 | 71.99006613 / 71.99101518 |
| 老理论均值偏差、绝对RMSE (ns) | +0.1478，0.6745 | +0.9491，1.4029 |
| 新理论预测均值 / 新baseline模拟均值 (us) | 71.35335283 / 71.35283799 | 71.35335283 / 71.35358448 |
| 新理论均值偏差、绝对RMSE (ns) | −0.5148，0.5519 | +0.2316，0.6186 |

老、新baseline使用同一N=1000粒子表及相同分析合同，两端均保持1000/1000命中。分辨率提升的配对
bootstrap 95%区间在COMSOL约为`0.754%--16.268%`、SIMION约为`0.536%--24.662%`，下界均为正。
新理论在新COMSOL上的中心化RMSE为`0.1987 ns`、逐粒子相关系数`0.9595`；在SIMION上均值预测仍准，
但`0.1265`的逐粒子相关表明细小空间映射已被离散场/积分残差主导。把新理论套到老baseline只保留为
辅助归因，不代替“老理论↔老baseline”和“新理论↔新baseline”两组自洽验证。

当前524 amu GUI理论中心为`71.353388 us`，精细输出截至`71.8534 us`，粒子终止时间
`72.8534 us`，约为理论中心的`1.021×`，不存在活动的三倍飞行时间余量。相对旧Formal终止时间约
`73.49 us`，时间轴只缩短约`0.64 us`（约0.9%）。本轮COMSOL N=1000粒子阶段实测约`952 s`，旧Formal
记录约`760 s`，因此不能声称墙钟时间已经节省；更长几何、求解器动力学和运行波动超过了时间轴缩短的
理论收益。以后若缩窄精细窗口或尾段，必须先做专门的步长/窗口收敛，不能仅凭解析中心删余量。

旧Formal的原因定位表明：反射器内部独立场相对RMS差约`0.000528%`，主要差异来自加速区纵向场和
z-to-TOF映射。COMSOL加速器`hmax=1 mm`是日常档，`0.5 mm`是收敛参考；后者改善横向梯度伪影，
但没有消除纵向焦点差。SIMION fractional surface使静电场基本不受网格相位影响，但固定距离越过
透明数值栅网会放大粒子TOF差；当前加速器和反射器跳转均为`0.0001 mm`。

已关闭的纵向差异归因、源接受度截断、五质量候选、粒子数墙钟缩放和场分量实验均已移出当前状态
正文；需要追溯时从项目README的history清单进入。当前性能与资产身份只认本节上述
`config/formal_validation.json`记录，不以历史小样本、旧Formal或机器计时覆盖。

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

### 2026-07-23 生产入口功能与写入边界回归

本轮只验证生产入口、输出合同和失败收尾，不建立新的数值精度或Formal性能结论。MATLAB R2025b
单元测试为`11/11`通过；普通COMSOL/CAD入口向Formal目标写入均被拒绝，只有目的地与获批事务中
`comsol_model`或`cad_root`精确一致时才获得授权，非精确目的地仍被拒绝。

| 软件/生命周期 | 运行或证据 | 当前结论 |
|---|---|---|
| COMSOL | `20260723_135235__test__comsol__oatof-candidate-functional__n100` | N=100为100/100唯一detector分类；10/5环数和6个分段时间窗口token通过合同检查；平均TOF为`71.352937 us` |
| COMSOL失败收尾 | `20260723_135035__test__comsol__oatof-candidate-functional__n100` | 缺少`OATOF_RUNTIME_DIR`被明确拒绝，失败run仍完整保存配置、摘要和manifest三件套 |
| SIMION | `20260723_143116__test__simion__oatof-source-build-track__n100` | reflectron、flight-tube、detector三个构建器均拒绝缺参调用；源码构建交付含53个清单文件且临时GEM残留为0；100/100命中，平均TOF为`71.353597 us` |
| 生命周期故障注入 | 共享run三件套合同 | 失败注入后的配置、摘要和manifest完整收口并通过复核 |

以上均为功能/合同证据；本轮没有修改baseline、Formal MPH、SIMION正式包、CAD装配或Formal结果。
各软件入口和判据分别由`COMSOL.md`、`SIMION.md`和`CAD.md`维护，本文件不复制实现步骤。

## 场方向归因实例

可组合场替换的通用定义、实验顺序和因果边界只见根
[`docs/VALIDATION_METHODS.md`](../../../docs/VALIDATION_METHODS.md)。“区域×分量”选择器在本项目
落地为COMSOL全分量能力和SIMION区域Ez能力；两端只在能力交集上比较，不用局部PA导数冒充全局
横向分量。具体COMSOL语法、GUI参数和SIMION兼容模式见各自软件文档。

本项目已验证该选择器可在COMSOL和SIMION能力交集上产生可区分响应；它只证明方法可行，不形成
正式分辨率声明。SIMION旋转二维PA不能独立暴露全局Ex/Ey，因此只支持Ez能力交集。关闭实验的数值、
运行路径和因果限制从项目README的history清单追溯；跨项目方法成熟度只由根验证方法文档记录。

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
2. **RF→oaTOF连接功能已收口，不自动进入下一阶段。** 阶段状态、恢复条件、资格指标和失败边界
   只以RF项目PROJECT及其机器合同为权威。本项目继续保持Formal分析器资产只读；只有所有者另行批准
   恢复接口资格、性能优化或整机晋升时，才按RF项目冻结的下一阶段执行。
3. **按需发布复现ZIP。** 从正式自包含目录生成不含日志、收敛参考和临时轨迹的ZIP及独立SHA；发送后
   ZIP可删除，源码构建链和正式目录继续保留。

以下未来任务按当前决定暂缓，不进入本轮程序/分析故障清理：

- **轴对称圆形加速器候选。** 将当前方形横向包络、接地屏蔽和理想栅网/支撑边界改为绕加速轴
  旋转对称的圆筒与圆形结构。第一阶段保持轴向位置、间距、电压和粒子源不变，只隔离“方形改圆形”
  的物理几何影响；候选须重新闭合解析焦点、三维场、传输率、峰形、网格收敛和跨求解器结果。
  物理圆形改型与二维轴对称数值降维是两个独立决策；若候选转正，必须同步COMSOL、SIMION及
  SolidWorks零件/装配，不得只修改某一软件。
- 真实丝网局部单元。
- 制造与装配误差预算。
- RF→oaTOF性能资格、优化或Formal整机晋升，以及二维轴对称COMSOL混合模型。
