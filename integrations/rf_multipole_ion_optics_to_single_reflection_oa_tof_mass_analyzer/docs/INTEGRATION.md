# RF多极杆离子光学到单次反射oaTOF集成

本文件是四、六、八极杆到单次反射oaTOF连接的当前状态权威。器件设计与资格仍由各项目
`docs/PROJECT.md`拥有；机器精确值、完整运行表、失败链和被取代方案不在本文重复。

## 当前身份与入口

- integration ID：`rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer`。
- 唯一公开执行入口：[`workflows/family_source_closure/execute.ps1`](../workflows/family_source_closure/execute.ps1)。
- 调用者只选择campaign和`ExperimentId`；源项目、求解器、母样本、resolved design及数值设置从
  冻结source run派生，不在CLI重复声明。
- 当前结果均为功能或诊断证据，不授予连续相空间、数值收敛、优化、Candidate或整机Formal资格。

| 职责 | 机器权威 |
|---|---|
| 连接拓扑与端口 | [`connection_profiles.json`](../config/connection_profiles.json) |
| 声明式实验 | [`experiment_campaign.json`](../config/experiment_campaign.json) |
| 脉冲分辨率优化 | [`pulse_resolution_optimization_campaign.json`](../config/pulse_resolution_optimization_campaign.json) |
| 执行适配 | [`execution_adapter_profiles.json`](../config/execution_adapter_profiles.json) |
| 单流程布局 | [`single_flight_layout_profiles.json`](../config/single_flight_layout_profiles.json) |
| runtime bindings | [`config/`](../config/)中的`*_runtime_binding.json` |
| 单飞数值与空间窗口 | [`simion_single_flight.json`](../config/simion_single_flight.json) |
| 线性相空间匹配 | [`accelerator_phase_space_match.json`](../config/accelerator_phase_space_match.json) |
| oaTOF变量及包络 | [项目config](../../../projects/single_reflection_oa_tof_mass_analyzer/config/) |

repository-text SHA由`runtime/refresh_family_repository_bindings.py`单向刷新；campaign source SHA由
`workflows/family_source_closure/refresh_campaign_source_bindings.py`冻结。终态manifest不得改写。

## 执行策略和粒子语义

| 策略 | 物理流程 | 适用边界 |
|---|---|---|
| `staged_three_stage` | COMSOL接口运输 → COMSOL脉冲捕获 → SIMION分析器 | 既有分阶段campaign |
| `simion_single_flight` | 单次Fly连续完成多极杆、连接器、脉冲加速、漂移、反射和检测 | 当前整体前端 |

`multipole_handoff`、`pre_pulse_state`和`local_accelerator_exit`是同一轨迹的checkpoint，不是重新释放或
时间清零。`continuous_injection_full_population`从多极杆入口释放全部声明母样本，不得先按脉冲可提取性
筛选；`pulse_eligible_conditional`仅用于带selection receipt的条件诊断。空间窗口只做detector-blind
分组统计，不修改轨迹。

## 单流程PA、屏蔽和参数重构

单流程的四个Workbench槽位依次为flight tube、reflectron、combined frontend和detector。combined
frontend把多极杆、连续接地屏蔽、连接器和oaTOF加速器放在同一PA；其电极1–8为八极杆，9为接地
屏蔽与连接器，10–17为加速器功能电极，18为入口参考套筒，19为入口板。每次run生成的
`single_flight_frontend_contract.json`才是编号和几何权威。

布局profile的`design_overrides`只能引用oaTOF变量目录：连续量受安全包络和实验包络约束；整数是离散
拓扑量；焦面、平移、反射器和罩体等理论派生量禁止直接指定；网格和时间步属于数值profile。省略输入
即继承活动layout/base resolved。编译链固定为：

```text
layout profile + design overrides
→ candidate baseline
→ theory closure
→ resolved geometry
→ run-local PA rebuild plan
```

加速器对相邻组件只发布外包络端点；屏蔽罩、无场区和反射器边界从该端点派生，不重复维护内部尺寸或
绝对坐标。范围校验只证明可编译；几何、电压或拓扑改变后仍须重新验证PA贯通、电极映射、真实Fly和
数值敏感性。

## 脉冲分辨率优化能力与边界

[`pulse_resolution_optimization_campaign.json`](../config/pulse_resolution_optimization_campaign.json)已在
既有campaign Schema和`family_source_closure`准备入口内注册，没有建立第二套CLI、物理模型或运行树。
它预声明SIMION优先、COMSOL复现的阶段顺序、冻结母样本与确定性筛选前缀、八臂理想场归因、晋级、
局部网格收敛、受约束候选、理论接受窗、双重验收、bootstrap和handoff规则。精确阈值、字段与禁止变量
只认该机器合同，不在本文复制。

当前八个归因臂均标记为`planning_only_until_adapter_support`。现有准备入口会在读取artifact或启动求解器
前拒绝执行该campaign；这表示声明、Schema、语义校验和失败关闭已经实现，不表示场mask、理想源、优化
候选或双重验收已经跑过。只有既有adapter能逐臂消费所声明的源与场模式、冻结每行身份并通过N=100
当前只解除第 1 臂“真实束 + 全真实场”的确定性 N=100 基线登记门禁。prepare 从已冻结且
SHA 验证的 N=1000 母样本按文件顺序取前 100 行，并把具名前缀与 SHA 绑定到父 run plan；
runner 仅在专用登记开关、全真实场 profile、arm/mode/seed 和 plan 同目录路径均一致时接受它。
成功终态为 `baseline_registered_not_candidate`：receipt 保存完整 100 个 ID、census、pulse-effective
指标、时钟和源哈希，但不调用配对 promotion gate，也不授权候选臂或 N=1000 资格运行。
其余 7 臂仍为 planning-only，须完成静态/配对回归后再逐臂解除门禁。

现另开放一个严格配对的 N=100 筛选行：`pulse_resolution_real_beam_ideal_stage1_real_stage2_real_reflectron_n100`，
完整工况是“同一冻结真实多极杆粒子束 + 理想一级加速场 + 真实二级加速场 + 真实反射器场”。
它复用基准的 ordered particle IDs、pulse-effective 时钟和 PA，仅启用既有一级理想场开关；不得启用
qualification、N=1000、COMSOL 或其余六项。验证/准备命令为：
`pwsh integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/workflows/family_source_closure/execute.ps1 -Campaign integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/pulse_resolution_optimization_campaign.json -ExperimentId pulse_resolution_real_beam_ideal_stage1_real_stage2_real_reflectron_n100 -ValidateOnly`。

SIMION单飞分析现以`detector_time_minus_pulse_effective_time`为唯一分辨率时钟；absolute instrument
clock只保留诊断语义，不能形成分辨率声明。输出分别保留完整pulse-eligible队列的峰与传输、冻结理论窗
的覆盖和条件结果、固定seed bootstrap，以及焦面后的反射器入口、中间栅、转向点和出口common-cohort
分段诊断。窗口定义接口不接受检测时刻或命中标签，窗外粒子继续计入完整束；这些字段和算法已通过
求解器无关测试，但尚未由本campaign的新真实SIMION运行产生资格证据。

生产编排仍未把两项资格能力接入上述planning-only campaign：一是同时含两方向角度边界的冻结理论
接受窗，二是按机器合同执行固定seed的5000次bootstrap并据区间宽度作门禁。当前空间窗口runner仍只
覆盖既有位置轴profile，单飞分析入口虽能计算可配置bootstrap，现有campaign/adapter并未传入资格参数。
因此不得把纯分析函数、默认关闭的CLI能力或既有位置窗输出解释为角度接受窗或bootstrap资格已经执行。

六维二阶局部传递模型及理论接受窗冻结机制也已实现为求解器无关分析边界：固定粒子ID划分训练/验证，
包含完整一阶、平方和交叉项，并预测焦面时间、探测时间、探测半径与命中状态。接受窗由合成相空间和
理想场—真实场的预测时间误差构建，再对完整pulse-eligible队列检查覆盖；真实检测结果不能参与窗定义。
环电压候选生成器只接受端点固定、单调且位于理论能量包络内的少量基函数候选，并声明复用PA。这些能力
目前只证明合同和纯分析实现闭合，不证明其代理精度、物理最优性或门槛可达。

## COMSOL retrace边界

COMSOL侧已把一次性retrace分支收敛到一个声明式arm校验器和通用执行边界：handoff receipt冻结SIMION
winner、几何、电压、场模式、粒子ID、时钟和理论接受窗；粒子释放使用共享全局笛卡尔速度，并在启动前
检查序列化误差和逐粒子身份。`source`及`field_mask`变化只规划粒子解，`voltage`变化规划静电场与粒子
解；`geometry`和`mesh`变化由retrace入口明确拒绝，必须回到受治理model builder。终态census为每个
输入粒子保留`hit`、`wall`、`escape`、`timeout`或`solver_failure`，不得删除慢粒子或失败粒子。精确
复用分类和速度门槛只查源码与优化campaign机器合同。

上述COMSOL边界目前只完成合同、静态测试和供应商侧任务脚本；runner仍在修正receipt身份冻结、run
三件套、retention和失败/中断终态等lifecycle闭合，当前不得执行为受治理retrace。本次没有启动COMSOL、
没有生成新的真实retrace结果，也没有完成GUI重开Compute、连接开口/接地罩边界对等、局部网格收敛或
单会话N=1000。因此它不能作为SIMION/COMSOL一致性、性能、Candidate或Formal证据。

## 当前物理结论

### 稳态束与源相空间

- 1.5 mm入口参考套筒、10 eV目标注入的N=1000连续基准为
  `1000→968→950→948→948`，总检测传输94.8%；脉冲前能量为`10.01783±0.05134 eV`。
  handoff加速方向角度σ为`1.81390°`，脉冲前σz为`0.54583 mm`。高传输和目标能量已闭合，
  角度及z展宽未闭合。
- 全量N=2000同网格运行得到`2000→1919→1873→1706→1617`，整体效率80.85%；脉冲瞬间1623粒子
  位于一级接受区，条件效率99.63%，单峰`R=23390.46`。1623粒子条件运行不能替代2000粒子整机分母。
- 标准N=1000前缀的同网格自然释放为`1000→957→938→852→806`、`R=22562.21`。真实束脉冲前
  z–vz相关系数约0.886；把同一粒子改成独立均匀位置且令加速方向速度为零，反而降为双峰
  `R=14183.86`。因此当前相关性总体参与聚焦，不能把“vz=0的独立立方源”预设为理想答案。
- detector-blind窗口表明，1 mm加速方向窗口的分辨率高于全队列，三维1 mm盒进一步提高；z展宽是
  最强单变量，但横向相空间和随机残差仍不可忽略。目标源应匹配相空间椭圆，而不是只压窄z或去相关。

### 2.2 mm有限区间与线性理论

当前有限区间设计保持两个均匀加速场，二级内部环线性分压。`d1=3.0 mm`、`d2=16.8 mm`的理论解
可覆盖2.2 mm源宽，派生焦距约45.36 mm，焦面保持全局`z=0`；现有5环和不小于1 mm的制造净间隙
已经满足理论实现，不需为“实体容纳”增加一级间距、二级长度或环数。精确公式只查
[线性z–vz理论](../../../projects/single_reflection_oa_tof_mass_analyzer/docs/theory/z_vz_linear_phase_space_coupling.md)。

理论几何重构在真实场中提高了传输，却形成双峰且`R≈8494`，不能晋升。理想分段场的人造线性源在
修正栅面时间步截断后能在焦面闭合，证明公式、源映射和焦面坐标有效；真实PA与理想两段均匀场的差异
才是该长焦距设计的主要限制。详细诊断和代表run见
[2026-08-12里程碑](../../../docs/history/20260812__oatof-finite-interval-focus-diagnostics.md)。

### 真实八极杆束的焦距、一级间隙与径向结构配对

2026-08-13以同一冻结N=100八极杆源、同一0.05 mm局部一级加速PA、同一70粒子pulse-eligible
cohort和`detector_time_minus_pulse_effective_time`时钟完成实际场配对。大径向结构
`bore/ring/shield=250/300/350 mm, 10/5 rings, t=5 mm`下，1 mm短焦距为
`R=7626.26, FWHM=2.1178 ns`，2.2 mm长焦距为`R=7059.05, FWHM=2.2829 ns`，后者低
7.44%；两者均`100→95→82`，因此差异不是传输或横向接受变化。共同脉冲前相空间为
`σx=2.24 mm, σy=0.48 mm, σz=0.49 mm, σvz=0.13 mm/µs, corr(z,vz)=0.88`；长焦距
峰的偏度/超额峰度由`0.096/0.220`升至`0.715/2.288`，表明同一z–vz束被实际一级场映射成更强
非高斯时间尾。

把长焦距一级长度由3 mm改为4 mm时，加速器电压、轴向平移及反射器电压均按联合一阶/二阶理论
自动重解；结果为`R=5721.04, FWHM=2.8387 ns`，相对3 mm再降18.95%。70个合格粒子仍全部
到达，额外探测损失发生在非合格背景。因此当前证据否定“简单扩大d1即可减弱边缘场并提高长焦距
分辨率”，不继续机械扫描5 mm。

紧凑径向结构`35/70/100 mm, 8/15 rings, t=2 mm`的严格交叉得到：短焦距
`R=8057.25, FWHM=2.0045 ns`，长焦距`R=6871.80, FWHM=2.3451 ns`，两者均77/100到达。
紧凑结构相对大径向结构使短焦距提高5.65%，使长焦距降低2.65%；紧凑结构内长焦距比短焦距低
14.71%。所以半径缩小不是当前主要限制，最佳N=100组合是紧凑反射器加1 mm短焦距。历史100 mm
N=1000运行的绝对时钟`R=22562`不得直接引用为分辨率；用保留日志离线按当前时钟重算为单峰
`R=9165.96, FWHM=1.7004 ns`，但其源样本和设计代不同，不是本轮2×2因果对照。

理想上限必须分板报告：轴向理想源+解析理想场oracle为`R=77093.87`；SIMION分段理想场solver
closure为单峰`R=47493.49`；既有实际场理想源Formal结果中，COMSOL单峰为`R=39938.06`，SIMION
虽报`R=47662.02`但有两个显著KDE峰，不能作为单峰最高值。这些源、质量和架构与本轮真实八极杆束
不同，只用于量级上限，不能把差值全部归因于实际场。

2026-08-13又在紧凑`35/70/100 mm, 8/15 rings, t=2 mm`结构完成两类严格诊断。首先，在历史
N=1000紧凑真实束run的同一806粒子、同一实际PA和同一pulse-effective时钟上，restart真实束为单峰
`R=9227.40, FWHM=1.6891 ns`；把源替换为独立`1×1×1 mm`、零`vz`的理想立方源后变为双峰
`R=5762.27, FWHM=2.7049 ns`。真实束的`σx/σy/σz=2.020/0.525/0.486 mm`、
`σvz=121.3 m/s, corr(z,vz)=0.886`，立方源虽缩至约`0.289/0.283/0.286 mm`且`vz=0`，仍因丢失
有利z–vz匹配而恶化；因此历史紧凑理想源`R=107739.8`与当前100 Da、10 eV真实束不是单一源变量的
可比对照，不能用其差值声称多极杆展宽单独造成全部损失。对应run为
`20260813_162000__sim__simion__r100-real-vs-ideal-source__n806`。

其次，以紧凑短/长焦距各自冻结PA为底板，分别使用各自理论线性理想源比较实际加速场与理想分段
加速场。短焦距同一77粒子在理想场达到单峰`R=81182.51, FWHM=0.19894 ns`，实际场为单峰
`R=15028.11, FWHM=1.07472 ns`，即实际场只保留18.51%的分辨率、FWHM扩大5.40倍，确认短焦距
理论本身有效而当前实际一级/二级场形明显限制它。长焦距同一70粒子在理想场仅为单峰
`R=9794.16, FWHM=1.64537 ns`，实际场反而为单峰`R=10975.44, FWHM=1.46834 ns`；直接FWHM下
实际场高12.1%，但样本小且两者均有明显非高斯性。故长焦距低分辨率首先是理论线性源与完整紧凑
oaTOF的整机匹配未闭合，尚不能用该对照评价实际加速场好坏，也不能说短、长两套实际场同样好。
四个run依次为`20260813_162500__sim__simion__r100-short-ideal-source-real-accel__n77`、
`20260813_163000__sim__simion__r100-short-ideal-source-ideal-accel__n77`、
`20260813_163500__sim__simion__r100-long-ideal-source-real-accel__n70`和
`20260813_164000__sim__simion__r100-long-ideal-source-ideal-accel__n70`。这些均是单一数值设置的N≤100
诊断，不是数值收敛、Candidate或Formal证据。

### 一级场归因与局部细PA

同一最新几何的分段理想场隔离把主要误差定位到一级加速区；仅理想化二级不能恢复分辨率。轴向基函数
显示源窗口内电势主要由repeller/grid1决定，0.2 mm整体PA的关键误差来自透明栅网附近的数值边界层，
不是宏观屏蔽泄漏。简单改端点电压会同时改变二级场和总能量，不能替代场形修正。

当前有效修复保持0.2 mm多极杆整体PA，使用六面Dirichlet基函数边界耦合局部0.05 mm加速器PA，并在
出口人工边界前以重叠保护区回退粗PA。方法合同只由
[跨项目连接架构](../../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md#simion粗全局pa与局部细pa耦合)维护。
N=100同网格身份对照的探测TOF配对RMS为0.0160 ns，未发现PA分解造成的系统偏移。

最新N=1000自然注入得到`1000→961→817`（接口→探测器）。在同一冻结808粒子、同几何和同电压的
A/B中，局部细PA把焦面时间σ从4.431降至1.472 ns，焦面z斜率从+6.419降至+1.921 ns/mm，单峰
分辨率从`R=8427`提高到`R=20883`，接近“仅一级理想”的`R=21792`。这证明局部细化是当前有效
数值修复；它仍是单一数值设置诊断，不构成收敛或生产默认声明。

## 证据路由

- [当前10 eV与1.5 mm套筒基准](../../../docs/history/20260805__octupole-terminal-15mm-sleeve-single-flight-n1000.md)
- [入口套筒与加速器内能量](../../../docs/history/20260805__octupole-15mm-sleeve-accelerator-energy.md)
- [前端网格与旧理想场诊断](../../../docs/history/20260810__oatof-frontend-grid-and-ideal-field.md)
- [Formal场归因](../../../docs/history/20260811__oatof-resolution-formal-field-attribution.md)
- [有限区间、理想场与局部PA里程碑](../../../docs/history/20260812__oatof-finite-interval-focus-diagnostics.md)

## 开放任务

1. 为既有adapter实现并验证八臂源/场模式映射；先以同一冻结母样本的N=100确定性前缀完成归因矩阵，
   严格执行第八臂解析闭合停止规则和晋级门槛，再解除campaign的planning-only状态。
2. 只在归因确认的限制区域完成SIMION局部网格收敛；随后以固定ID划分验证传递模型和少量受约束候选，
   冻结detector-blind理论接受窗。窗口覆盖不达机器合同门槛时必须改善场或上游束，不能继续缩窗。
3. 最佳候选用冻结N=1000母样本、五批PA复用和全部pulse-eligible粒子完成双重验收与bootstrap；关闭前
   现有局部PA结果仍只是单一数值设置诊断，不是生产、收敛或优化结果。
4. SIMION稳定通过后生成唯一handoff receipt，再用通用retrace runner完成COMSOL N=100同粒子理想场
   分解、边界对等和局部网格收敛；通过后才在单一商业求解器会话运行N=1000并比较两端结果。
5. COMSOL真实链还须验证全局笛卡尔速度、完整终态census、慢粒子求解、GUI重开Compute和连接开口/
   接地罩边界；这些检查以及机器合同中的跨求解器差异门槛全部通过后，才能关闭复现任务。

## 静态门禁

[`verify_integration.ps1`](../verify_integration.ps1)只验证连接、端口、profile、冻结身份和失败关闭逻辑；
不运行商业求解器，也不替代物理资格。

径向因素的预注册矩阵由
[`radial_factor_attribution_matrix.json`](../config/radial_factor_attribution_matrix.json)维护。它在同一真实多极杆
源身份、pulse-effective时钟、完整pulse-eligible cohort、电压/前端和0.1 mm反射器轴向网格下，分别锁定
shield 100/180/350 mm、电极径向bundle 35/70与250/300 mm、r100拓扑`10/5 t5 → 8/15 t5 →
8/15 t2`及large anchor；晋级后才允许按0.2/0.1/0.05 mm做局部网格收敛。该合同保持
planning-only，复用既有radial-compaction入口，不新建CLI，也不授予求解、排行榜或证据晋升权限。
