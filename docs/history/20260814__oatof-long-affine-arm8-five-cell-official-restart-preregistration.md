# oaTOF长焦AFFINE Arm8五格官方restart修正版事前登记（2026-08-14）

> `DOC_STATUS: PREREGISTERED_PENDING_INDEPENDENT_REVIEW`

## 身份与修正边界

本登记在修正版五格的任何SIMION求解启动前冻结。它是
`canonical_long_affine_arm8_width_numerics_restart_n1000`的唯一事前登记，不修订、不覆盖原
`canonical_long_affine_arm8_width_numerics_n1000`。原五格虽然1000/1000到达且显示强宽度响应，
但其`continuous_frontend`实际pulse-state没有逐粒子复现登记的AFFINE目标，因此按原登记停止规则
永久分类为`INVALID_IDENTITY_OR_CENSUS`，只保留为`AT-ACTUAL-PULSE-STATE`诊断，不能用于本登记结论。

修正版相对原五格的唯一科学变化是：

- `source_release_mode: continuous_frontend -> pre_pulse_restart`；
- 通过SIMION官方FLY2 individual-particle `standard_beam(position=vector(...), velocity=vector(...))`
  在唯一`pulse_effective_time`直接释放完整有序N=1000源；
- 每行绑定由既有官方`materialize_ideal_linear_source`生成的pulse-target CSV及receipt，并对实际
  `source_release`逐行验收。

不得引入teleport、epsilon位移、TOF补偿、第二时钟、第二物理公式或非官方粒子重启路径。

## 冻结共同配置

五格保持原登记的固定长焦2.2 mm匹配结构
`symmetric_10ev_source_z22_finite_interval_theory` /
`finite_interval_2p2mm_matched_voltage_v1`，保持全域Arm8理想分段场
`arm8_closed_global_piecewise_theoretical_field` /
`resolved_geometry_piecewise_theoretical_field`，真实PA只承担SIMION官方几何、电极碰撞和终止边界，
`real_pa_field_blending_allowed=false`。四个栅继续使用官方节点对齐、零grid-unit厚度、一行raw-PA
电极点和PA级`surface=none`的`GRID-NATIVE-ONE-ROW`做法。

source是100 u、+1、10 eV、严格AFFINE z-vz、完整有序N=1000：
`canonical_ideal_linear_z_vz_{1mm,1p5mm,2p2mm}_n1000`。1.0与2.2 mm CSV已经被既有canonical
pulse-state实验逐行验证；1.5 mm CSV由原五格prepare阶段用同一个受支持物化器和同一个长焦resolved
layout/pulse schedule生成。三份CSV均由manifest绑定；原五格求解结果无效不使其求解前、独立哈希绑定的
物化输入失效。每行仍须用1e-9 mm位置、1e-6 m/s速度分量、1e-9 us时钟和5e-9 eV派生能量容差
验收实际SIMION source_release，任一失败即停止。

唯一分辨率时钟为`detector_time_minus_pulse_effective_time`，absolute instrument/birth clock不参与
分辨率。所有cell复用相同内容身份的frontend、overlay、flight-tube、reflectron和detector PA；
source CSV、dt和tqual不进入PA cache key，不授权refine或重建。每格五批，最多三批并发，4 GiB最小
可用内存门禁，自动重试为0；五格顺序执行，失败即停。

## 冻结五格

|顺序|cell|唯一变量|新run ID|
|---:|---|---|---|
|1|`long_arm8_restart_affine_1mm_q8_dt160_n1000`|W=1.0 mm|`20260814_230000__sim__cross__long-arm8-restart-affine-1mm-q8-dt160__n1000`|
|2|`long_arm8_restart_affine_1p5mm_q8_dt160_n1000`|仅W=1.5 mm|`20260814_231000__sim__cross__long-arm8-restart-affine-1p5mm-q8-dt160__n1000`|
|3|`long_arm8_restart_affine_2p2mm_q8_dt160_n1000`|仅W=2.2 mm|`20260814_232000__sim__cross__long-arm8-restart-affine-2p2mm-q8-dt160__n1000`|
|4|`long_arm8_restart_affine_2p2mm_q8_dt320_n1000`|相对3仅dt160->dt320|`20260814_233000__sim__cross__long-arm8-restart-affine-2p2mm-q8-dt320__n1000`|
|5|`long_arm8_restart_affine_2p2mm_q108_dt160_n1000`|相对3仅q8->q108|`20260814_234000__sim__cross__long-arm8-restart-affine-2p2mm-q108-dt160__n1000`|

## 指标、判据与结论边界

在机械检测面用完整1000粒子、pulse-effective TOF计算population sigma为主指标，同时无选择报告
sample sigma、mean、direct KDE FWHM、R、central80、span、modes、全部checkpoint census和终止分类。

宽度判据冻结为`σ1.0 < σ1.5 < σ2.2`且`σ2.2/σ1.0 >= 5`。令
`Delta_width = σ2.2 - σ1.0`，数值稳健性冻结为
`max(|σdt320-σ2.2|, |σq108-σ2.2|) <= 0.10*Delta_width`。三点log slope仅描述，不唯一识别阶次。

先验身份门要求：每行实际source_release逐行PASS；所有登记checkpoint和检测面1000/1000；无
postselection；campaign row、source CSV/receipt、单时钟、resolved geometry、Arm8 contract、Program/ION、
PA cache manifest和run manifest全部bytes/SHA闭合。失败则`INVALID_IDENTITY_OR_CENSUS`；宽度不通过则
`FIXED_LONG_AFFINE_HIGHER_ORDER_WIDTH_RESPONSE_NOT_SUPPORTED`；宽度通过而数值不通过则
`INCONCLUSIVE_NUMERICAL_WITHIN_TESTED_PROFILES`；全部通过才允许
`SUPPORTED_STRONG_NONLINEAR_WIDTH_RESPONSE_IN_FIXED_LONG_AFFINE_ARM8`。

最强结论仍只适用于固定长焦2.2 mm结构、W=1.0--2.2 mm、AFFINE源和本登记数值对照；不能证明
某一唯一泰勒阶、不能证明所有可想象理论均无法适配，也不能替代per-width rematch、W>2.2 mm、真实PA
场分区或多极杆束实验。任何扩大源宽并同步重匹配加速器/反射器的实验必须另行事前登记。
