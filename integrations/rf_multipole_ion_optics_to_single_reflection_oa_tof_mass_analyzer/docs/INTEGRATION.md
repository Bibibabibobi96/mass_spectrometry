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
