# oaTOF脉冲相对分辨率筛选收尾（2026-08-14）

> `DOC_STATUS: ARCHIVED_READ_ONLY`

## 目标与统一口径

本快照冻结截至2026-08-14的N=100筛选、解析闭合、detector-blind脉冲窗和损失归因。它不修改项目
baseline、Candidate或Formal状态；粒子级真值仍以各run的manifest、summary和结果表为准。

唯一分辨率时钟为`t_TOF = t_detector - t_pulse,effective`。绝对仪器时钟只作调度和诊断，不得用于
oaTOF分辨率声明。筛选使用冻结N=1000母样本的确定性N=100前缀；pulse-eligible由脉冲时刻的上游
相空间和几何定义，不使用探测结果。N=100只回答机制问题，不能替代完整N=1000、五批聚合、bootstrap
或最终双门资格。

## 有效SIMION筛选证据

下表均使用同一冻结前缀、pulse-effective时钟和eligible配对总体；R为直接KDE FWHM质量分辨率。

|物理臂|run ID|eligible命中|direct FWHM (ns)|R|结论|
|---|---|---:|---:|---:|---|
|真实束、全真实场baseline|`20260812_210000__sim__cross__pulse-resolution-baseline__n100`|50/50|3.10729|5015.88|单峰，仅登记baseline|
|真实束、局部一级理想hard-mask|`20260813_133000__sim__cross__pulse-real-ideal-s1-real-s2-refl__n100`|50/50|4.15100|3754.67|配对拒绝|
|真实束、局部一级和二级理想hard-mask|`20260813_140000__sim__cross__pulse-real-ideal-s1s2-real-refl__n100`|50/50|3.90269|3993.65|配对拒绝|
|真实束、Arm8全域理论场|`20260814_000000__sim__cross__pulse-real-arm8-global-theory__n100`|50/50|3.90282|3993.51|配对拒绝|

baseline完整census为100 launched、75 multipole handoff、66 pre-pulse alive、56 detector crossing，其中
50粒子pulse-eligible且50/50命中。Arm8全域理论场虽有57个总探测粒子，固定eligible仍为同一50个；
相对baseline的direct FWHM和样本sigma分别恶化25.60%和21.55%，因此promotion receipt明确为
`reject`。相关绝对证据目录为
`C:\Users\Liao\mass_spectrometry\artifacts\projects\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\runs\20260814_000000__sim__cross__pulse-real-arm8-global-theory__n100`。

上述局部hard-mask只是在真实PA上替换限定区域力场的反事实，不是可制造场、候选几何或最终物理臂；
旧“真实束+加速器/反射器全理想”的hard-mask实现已经deprecated并被合同禁止执行。其预留run ID
`20260813_150000__sim__cross__pulse-real-all-ideal__n100`不构成结果，不得引用为物理结论。

## Arm8解析与SIMION闭合

求解器无关解析receipt位于run
`20260813_151500__analysis__python__axial-ideal-arm8-closure`。最终SIMION闭合run为
`20260813_223000__sim__simion__arm8-solver-closure-n101-interpolated-r04`：101/101粒子通过十个有序事件，
脉冲相对峰为单峰，direct FWHM `0.328160 ns`、`R=47493.49`；最大时间、位置、出口能量和转向深度误差
分别为`0.149972 ns`、`0.003351 mm`、`0.034273 eV`和`0.003351 mm`，均通过预声明容差。

这证明解析公式、统一时钟、分段场边界和SIMION事件插值能在轴上纵向理想臂闭合，并越过窗口
`R>=30000`的停止门；它不是真实束结果、横向三维闭合或Formal资格。真实束接入同一全域理论场反而
退化，因而限制已从“一维公式是否成立”转向真实上游六维相空间及其与入口几何的联合问题。

## z-vz离线归因与上游损失

固定eligible队列的离线配对分析显示，真实束保留强而非线性的`z-vz`结构；仅替换一级、一级加二级，
乃至用Arm8全域理论场替换下游场，都没有压窄最终峰。baseline的分段时间与入口`vz`高度相关，且
Arm8全域场仍比baseline宽约0.796 ns。这些证据支持把真实`z-vz`残差及横向/角度交叉项作为下一阶段
传递模型输入，但不支持通过删除尾粒子、收窄post-hoc窗口或继续孤立调电压来制造改善。

detector-blind终态census还显示100个启动粒子中34个在观测窗开始前已native splat。将这些ID与
handoff/terminal状态和编译几何配对后，损失集中在当前`1.0 x 0.9 mm`法兰入口及紧随的连接罩clear
envelope；不是检测器筛选造成。其原始终态表为
`C:\Users\Liao\mass_spectrometry\artifacts\projects\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\runs\20260814_020000__sim__simion__pulse-window-observability-n100\results\pulse_window_terminals.csv`。
该归因足以把上游孔径列为首选A/B诊断变量，但尚未证明扩大孔径会改善R或达到70%覆盖。

## detector-blind脉冲窗

run `20260814_020000__sim__simion__pulse-window-observability-n100`在加速器保持脉冲前电位、保留真实时变
RF且不产生detector trace的条件下，于`31.313670–32.313670 us`预声明181个等间隔采样点。结果为66个
粒子完成窗口、34个在窗口前损失；最大alive覆盖66%，最大eligible覆盖64%，故70%接受窗门在当前
上游几何下不可达，禁止通过继续缩窗绕过。

按预声明的“eligible不少于baseline后，最小Arm8解析direct FWHM”规则冻结的三个候选为：

|排名|仪器时刻 (us)|eligible|解析direct FWHM (ns)|解析R|
|---:|---:|---:|---:|---:|
|1|32.0303365381|57|3.78865|4113.89|
|2|32.1692254270|60|3.79589|4106.05|
|3|32.0358920937|57|3.79602|4105.90|

这些是detector-blind上游观测加Arm8解析预测，不是候选solver结果；64%是当前观测到的覆盖上限，不是
可接受的70%窗口。由联合理论生成的四个种子也只保留为待运行候选，未获得SIMION、COMSOL或晋级资格。

## 失败关闭与未完成边界

以下类别全部保留为工程证据，不得作物理结论：合同尚未开放时被adapter拒绝的run；时钟偏置、事件
日志缺失或边界插值未修复的Arm8前置run；SIMION启动/路径/权限失败；被中断、timeout或solver failure
的COMSOL retrace；没有完整manifest/summary/粒子身份闭合的临时分析。尤其Arm8的center smoke和
`20260813_210000`、`20260813_213000`、`20260813_220000`等前置迭代只用于修复实现，最终物理口径只取
`20260813_223000...r04`。

本轮COMSOL移植尚未开始；此前中断的理想源COMSOL run保持`interrupted`，不作为物理结果。完整
N=1000 pulse-eligible总体、五批聚合、5000次bootstrap、最终局部网格收敛、完整束`R>=20000`门和
detector-blind窗口`R>=30000`门均未完成，因此SIMION winner、handoff receipt、COMSOL复现和最终双门
均不存在。

## 下一步入口与限制

首选下一步是上游法兰/连接罩几何A/B，而不是继续飞oaTOF detector：冻结同一N=100 IDs和真实RF/
上游场，以原`1.0 x 0.9 mm`入口为baseline，只把法兰入口及紧随clear envelope扩大到覆盖当前母样本
detector-blind terminal/handoff包络并加小工程裕量。尺寸必须在运行前由上游状态预声明，不得读取
detector结果；外部仪器半径不变，其他几何、电压和PA冻结，只有相关frontend PA因几何变化而重建。
先比较handoff、window alive/eligible、terminal分类和`z-vz`统计；若覆盖仍低于70%，不得以缩窗补偿。
只有该A/B确认上游覆盖改善且未引入新的相空间恶化后，才恢复oaTOF N=100筛选，再考虑四个理论联合
种子、N=1000资格和COMSOL handoff。
