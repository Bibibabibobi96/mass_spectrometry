# oaTOF真实反射器轨迹质量配对检查（2026-08-14）

> `DOC_STATUS: ARCHIVED_READ_ONLY`

## 目标与冻结口径

本快照记录真实反射器场RR winner在官方SIMION轨迹质量`T.Qual=8`与`T.Qual=108`之间的最小配对数值
诊断。它只回答既有RR结果是否可能受轨迹积分质量影响，不改变电场、PA、几何、时间步、RF、脉冲或
离子母样本，也不回答PA空间离散误差是否已经收敛。

冻结物理配置为`theory_source_z10_d1_3`、`frontend_isotropic_020_accelerator_overlay_z005`
（native accelerator PA `dz=0.05 mm`）、`oatof_reflectron_z010_r100`、真实加速器PA、真实反射器PA和
零RF周期脉冲偏置。数值变量只能通过受治理常量profile选择：`tqual_8=8`或`tqual_108=108`；campaign
不能自由传入数值。SIMION调用仍使用官方`--trajectory-quality`及同值adjustable，没有改变`tstep`或场。

## 样本算法与配对流程

母样本为`common/multipole/sources/rf_oatof_short_focus_ideal_linear_z_vz_entry_n1000.csv`。确定性N=100
样本由全局顺序分位点、脉冲前`z`极值/中位数、脉冲前`vz`极值/中位数及`xy`开放孔径边缘裕量
极值/中位数组成，并显式包含已知敏感粒子global ID 715。派生源SHA-256为
`5AABC891DDAE7E77716F1842052E11CBBA066DF8B415D16EE807F51B4289605A`；完整local/global ID映射在
`integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/diagnostics/short_focus_rr_tqual_n100_sample_receipt.json`。

q8不重跑，直接从既有RR run
`20260813_170000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03`的manifest-bound checkpoints按同一
global ID提取。唯一新求解预留为q108 run
`20260814_010000__sim__cross__short-rr-tqual108-stratified__n100__r01`。预声明配对门为焦面平均时间绝对偏移
不超过`0.03378871363500548 ns`，且焦面配对差值样本sigma不超过同值；不得在见到q108结果后改门。

## 当前执行结果与证据

campaign、schema、prepare和adapter已经允许且只允许上述两个常量profile。q108 campaign通过
`CAMPAIGN_SOURCE_BINDINGS=PASS`、`FAMILY_SOURCE_CLOSURE_PREPARE=PASS`、`COMPOSITION_PLAN=PASS`和
`INTEGRATION_EXECUTION=VALIDATED`；PrepareOnly产物位于
`C:\Users\Liao\mass_spectrometry\artifacts\projects\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\scratch\short_focus_rr_tqual108_stratified_n100`。
组成计划冻结N=100源SHA、布局、真实场profile和`single_flight_trajectory_quality_profile_id=tqual_108`。
相关workflow/runtime合同单测24项通过。

随后完成的唯一q108 solver run为
`20260814_010000__sim__simion__rf-oatof-single-flight-gap0__n100__r01`，100/100粒子在全部八个比较
checkpoint闭合。机器数值权威不是`resolved_geometry`内继承的几何基线值8，而是受治理
`tqual_108=108`配置和stdout中的`TRACE ... trajectory_quality=108`；派生receipt显式记录上述路径与SHA。

manifest-bound配对结果位于
`C:\Users\Liao\mass_spectrometry\artifacts\projects\rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer\runs\20260814_030000__analysis__python__rr-tqual8-vs108-paired-n100__r03`。
q8探测器时钟采用canonical receipt导出的`rr_canonical_checkpoints.csv`（SHA-256
`FCB931C9E67C268CBA038CAE9D37D057FD593108949FD7317EBF8A654D233612`），避免旧detector-blind
reanalysis的非canonical探测器绝对钟。

焦面配对平均偏移为`+0.002292507 ns`，通过`0.033788714 ns`门；配对差值sigma为
`0.038452739 ns`，超过门值，故预声明主门**FAIL**。该sigma是已知`dz=0.05→0.025 mm`效应
`0.0399346 ns`的`0.963`倍、Stage2场效应`0.337887 ns`的`0.114`倍。焦面时间分布q8/q108的
sigma为`0.068034/0.052539 ns`、direct FWHM为`0.182043/0.154840 ns`，均为单峰；这些是焦面
时间分布诊断，不是最终质量峰。

canonical detector的pulse-effective peak中q8/q108的sigma为`0.287708/0.284371 ns`、direct FWHM为
`0.488781/0.518692 ns`、质量R为`33043.15/31137.60`，均为双峰。此前由绝对instrument clock得到的
`79492/74908`只允许作为absolute-clock diagnostic，并明确`forbidden_for_resolution_claim`。探测器配对平均偏移、差值sigma、RMS和
最大绝对偏移分别为`+0.002159/0.038472/0.038340/0.074833 ns`。R和FWHM变化不推翻主门：本诊断
以冻结焦面配对门为主，而且N=100双峰R只是次级描述量。

## 资格状态与结论范围

|门|状态|原因|
|---|---|---|
|Functional|**PASS**|q108真实solver成功，100/100全checkpoint闭合且manifest/TRACE权威闭合|
|Formal|**FAIL**|没有完整run manifest、结果和既定Formal双门证据|
|数值收敛|**FAIL**|焦面配对sigma超过预声明门；且两点T.Qual检查不是PA网格或联合收敛序列|

允许的结论是：保持物理输入不变时，官方SIMION `T.Qual=8→108`引起的焦面粒子级差异已达到既有
`dz`效应同量级，并使预声明轨迹质量门失败；因此q8不能作为已证明轨迹积分稳定的数值基线。该结果仍
不能把误差归因于grid穿越、PA空间离散或真实场物理偏差；这些需要独立PA空间网格序列及场模型A/B。

## 失败教训

首次Validate被campaign schema拒绝，因为新增profile字段尚未进入additional-properties白名单。修复采用
明确枚举`tqual_8/tqual_108`，而不是开放任意数值override，随后重新刷新绑定并通过严格Validate/Prepare。
这次失败没有启动solver，也没有产生可引用的物理结果。另一个边界是q8 checkpoints来自既有N=1000 RR
run，比较时必须使用receipt中的global ID映射，不能把派生源local ID直接与q8粒子号相配。
