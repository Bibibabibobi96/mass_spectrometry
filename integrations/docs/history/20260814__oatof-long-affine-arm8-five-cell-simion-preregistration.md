# oaTOF长焦AFFINE Arm8五格SIMION矩阵事前登记（2026-08-14）

DOC_STATUS: ARCHIVED_READ_ONLY

> `DOC_STATUS: ARCHIVED_READ_ONLY`

## 登记身份、时点与相邻计划

本文在五格矩阵的任何SIMION求解启动前，独立冻结实验问题、五个cell、执行资源、结果身份、指标、
判据和结论边界。本文不包含求解结果，不授权修改oaTOF Formal、baseline、理论参数或既有证据资格；
运行后只允许在新的日期化history中报告结果，不得按观察值回写本文。

本文与既有
[`oaTOF 2.2 mm有限区间高阶时间像差验证预注册`](20260814__oatof-2p2mm-higher-order-preregistration.md)
并列而不互相取代。既有计划的主cohort是`true-zero-vz`、固定ZERO-MATCH结构和真实PA场；本文的唯一
cohort是`AFFINE z-vz`、固定长焦2.2 mm匹配结构和全域理想场。本文只回答固定结构内的宽度响应是否
稳定存在，以及该响应是否可由本矩阵所覆盖的时间积分和trajectory quality变化解释；不得把本文结果
冒充既有计划的阶段A、八宽度主扫描或真实场组件隔离结果。

机器campaign唯一身份为
[`canonical_long_affine_arm8_width_numerics_n1000_campaign`](retired_campaigns/canonical_long_affine_arm8_width_numerics_n1000_campaign.json)。
本文冻结时该合同状态为`PENDING_PREREGISTRATION`，求解器执行被失败关闭；本文通过独立审阅后，只有
责任workflow显式完成状态迁移并重新校验完全相同的五格语义，才可启动SIMION。激活后的完整campaign
SHA和每行row SHA必须进入各run config。本文中的显示名只映射机器身份，不参与缓存或结果身份判断。

## 科学问题与冻结假设

在同一套长焦2.2 mm匹配几何、电压和全域理想分段场中，仅把规范`AFFINE z-vz`源的轴向全宽从
1.0 mm扩大至1.5 mm、2.2 mm时，检测时间展宽是否单调且远大于两个受支持数值设置变化造成的展宽。

- `H-WIDTH`：固定结构内满足`1.0 < 1.5 < 2.2 mm`的population sigma严格单调关系，且2.2/1.0 mm
  sigma比至少为5；这支持完整2.2 mm有限区间存在强非线性宽度响应。
- `H-NUMERICS`：在2.2 mm端点，分别把`dt160`改为`dt320`或把`tqual_8`改为`tqual_108`造成的
  sigma变化，都不超过1.0至2.2 mm主宽度效应的10%；这排除当前受控时间积分和trajectory quality是
  该宽度效应主因。
- `H-ALT`：若源、时钟、PA、manifest、粒子census任一闭合失败，或数值变化达到上述宽度效应的10%，
  本矩阵不能作高阶有限区间归因，只能报告`INVALID`或`INCONCLUSIVE_NUMERICAL`。

本文中的“强非线性宽度响应”不等于唯一识别二阶、三阶或更高某一阶。三点宽度的log slope只能作为
与既有探索区间`2.7–3.3`是否兼容的描述性量，不能单独成为物理阶次判据。

## 规范配置注册表

五格共同结果身份按下表冻结；任一维度漂移都构成不同结果身份，不得沿用本登记名称。

|身份维度|冻结规范名或机器身份|
|---|---|
|source|`canonical_ideal_linear_z_vz_{1mm,1p5mm,2p2mm}_n1000`；`AFFINE z-vz`；100 u、+1、10 eV；`phase_space_authority=config/accelerator_phase_space_match.json`|
|cohort|每格N=1000有序粒子；完整分母；禁止postselection、删除端点或按峰选择cohort|
|geometry|`symmetric_10ev_source_z22_finite_interval_theory` + `finite_interval_2p2mm_matched_voltage_v1`；固定长焦2.2 mm匹配结构|
|accelerator/reflectron field|`arm8_closed_global_piecewise_theoretical_field` + `resolved_geometry_piecewise_theoretical_field`；覆盖加速器、无场漂移区及反射器；`real_pa_field_blending_allowed=false`|
|PA作用|`frontend_isotropic_020_accelerator_overlay_z005` + `oatof_formal_mesh`对应真实PA只提供官方SIMION几何/电极碰撞、数值终止标记和实例边界；不得贡献或混合静电场|
|grid|正式几何中的四个栅均为`GRID-NATIVE-ONE-ROW`：SIMION官方节点对齐、零grid-unit厚度、一行raw-PA电极点、PA级`surface=none`；禁止teleport、epsilon越层、粒子位移和TOF补偿|
|source release|`source_release_mode=continuous_frontend`；使用SIMION官方ION粒子输入和连续前端路径；实际pulse-state必须按同一源合同逐粒子验收|
|trajectory numerics|`tqual_8`为主设置；仅第五格改为既有受支持的`tqual_108`|
|time integration|`dt160`为主设置，即`rf_steps_per_period=160`；仅第四格改为`dt320`，即320；不存在第二个默认时步或行内隐式覆盖|
|clock|唯一分辨率时钟为`detector_time_minus_pulse_effective_time`；每个粒子`pulse_effective_time_us=0`，`fallback_allowed=false`；absolute instrument/birth clock不参与分辨率|
|statistics|population sigma为主指标；direct KDE FWHM、`R=T/(2*FWHM_t)`、central80、span及KDE modes使用同一冻结分析入口|
|retention/status|`compact`；每格独立run三件套；成功只表示预登记Diagnostic执行完成，不授予Candidate或Formal资格|

全域理想场的边界电位、分段斜率、平面位置和反射器转向深度只由同一个resolved长焦2.2 mm理论解
编译；五格禁止重调电压、源中心、pulse时刻、焦面或反射器。真实PA只作为几何碰撞/终止承载，因此
本矩阵不能测量“真实PA场相对理想场”的效应。

## 冻结五格矩阵

|顺序|规范cell|唯一变化|run ID|
|---:|---|---|---|
|1|`long_arm8_affine_1mm_q8_dt160_n1000`|宽度`W=1.0 mm`；主数值设置|`20260814_210000__sim__cross__long-arm8-affine-1mm-q8-dt160__n1000`|
|2|`long_arm8_affine_1p5mm_q8_dt160_n1000`|仅宽度改为`W=1.5 mm`|`20260814_211000__sim__cross__long-arm8-affine-1p5mm-q8-dt160__n1000`|
|3|`long_arm8_affine_2p2mm_q8_dt160_n1000`|仅宽度改为`W=2.2 mm`；数值对照基准|`20260814_212000__sim__cross__long-arm8-affine-2p2mm-q8-dt160__n1000`|
|4|`long_arm8_affine_2p2mm_q8_dt320_n1000`|相对第三格仅`dt160 -> dt320`|`20260814_213000__sim__cross__long-arm8-affine-2p2mm-q8-dt320__n1000`|
|5|`long_arm8_affine_2p2mm_q108_dt160_n1000`|相对第三格仅`tqual_8 -> tqual_108`|`20260814_214000__sim__cross__long-arm8-affine-2p2mm-q108-dt160__n1000`|

第一至第三格构成固定结构的三点宽度响应；第三至第四格只检验时间积分；第三至第五格只检验
trajectory quality。禁止把第四格同时换成`tqual_108`，也禁止把第五格同时换成`dt320`，因为那会
失去单变量配对。

## 官方路径、资源与PA复用

每个cell使用同一SIMION 2020单飞入口：官方ION连续前端释放，官方Program场，官方原生透明栅和
GUI可检查PA/IOB实例。全域理想电势只复用既有`full_domain_piecewise_field_lua`渲染路径；不得新增
第二物理公式、第二时钟、场拼接、teleportation或其他自建求解路径。

每个N=1000 cell固定拆为5个批次；缓存预热后批次并发上限为3，调度波次固定为`3+2`。五个矩阵cell
本身按顺序串行，自动重试为0，首个失败后停止尚未启动cell。`single_flight_transport`启动门禁要求系统
可用内存至少`4 GiB = 4,294,967,296 bytes`；低于该值只记资源门禁未通过，不得归因为物理或SIMION
求解失败。

五格必须复用同一内容身份的frontend、accelerator overlay、flight tube、reflectron和detector PA；
不同宽度、`dt`或`tqual`不授权重建几何、Refine新电场或调整fast-adjust电压。运行时只允许从已注册
schema-v2内容寻址缓存命中并逐文件复核bytes/SHA-256；合法MISS只能用同一冻结输入精确重建，然后在
任何cell启动前重新冻结缓存manifest。每个run的`run_config.json`必须记录campaign row SHA、源profile
及其物化文件SHA、resolved geometry SHA、Arm8 field-contract SHA、Program/ION SHA、各PA cache
manifest SHA和数值profile；`run_manifest.json`必须逐项记录输入/输出路径、bytes和SHA-256并由公共
verifier复核。身份或哈希不闭合的结果不得进入五格比较。

## 指标与事前判据

五格均在`mechanical_detector_crossing`上用完整1000粒子计算。主要指标是pulse-effective TOF的
population sigma；同时无选择地报告sample sigma、mean TOF、direct KDE FWHM、R、central80、span、
KDE modes、各checkpoint census、源验收误差及全部终止分类。单峰或多峰都必须如实报告；多峰不能
改换峰、缩窄cohort或只选较有利FWHM。

令主数值设置下三个宽度的population sigma分别为
`sigma_1.0`、`sigma_1.5`和`sigma_2.2`，主宽度效应为

$$
\Delta_\mathrm{width}=\sigma_{2.2}-\sigma_{1.0}.
$$

宽度响应判据固定为

$$
\frac{\sigma_{2.2}}{\sigma_{1.0}}\ge 5,
\qquad
\sigma_{1.0}<\sigma_{1.5}<\sigma_{2.2}.
$$

数值稳健性判据固定为

$$
\max\left(
|\sigma_{\mathrm{dt320}}-\sigma_{2.2}|,
|\sigma_{\mathrm{q108}}-\sigma_{2.2}|
\right)
\le 0.10\,\Delta_\mathrm{width}.
$$

对central80和span分别报告完全相同形式的绝对变化与其各自`0.10*Delta_width`比较，但它们是次要
峰形诊断，不覆盖population sigma主判据。三宽度点可拟合
`log(sigma_T)=b0+p_eff*log(W)`并报告`p_eff`及其是否落入既有探索区间`2.7–3.3`；三点斜率没有足够
信息唯一识别某个泰勒阶次，因此不作为PASS/FAIL门。

## 排除规则、停止规则与允许结论

每格必须同时满足以下身份门，才能进入物理比较：

1. `source_release`覆盖全部有序ID并逐粒子通过位置、速度、派生能量和pulse-effective clock验收；
2. 全部1000粒子按预登记事件顺序到达机械检测面，即`1000/1000`，且没有postselection；
3. source、cohort、geometry、field、grid、PA、numerics和clock与该cell登记身份一致；
4. run config、summary、manifest、campaign row和全部输入/输出bytes/SHA-256闭合；
5. PA仅用于几何碰撞和数值终止，全域理想field contract继续满足`real_pa_field_blending_allowed=false`。

任一项失败，该cell标为`INVALID_IDENTITY_OR_CENSUS`，立即停止后续SIMION，既有失败/中断run保留其
原状态且不复用run ID。若身份门通过但宽度响应判据失败，结论为
`FIXED_LONG_AFFINE_HIGHER_ORDER_WIDTH_RESPONSE_NOT_SUPPORTED`。若宽度响应通过而数值稳健性失败，
结论为`INCONCLUSIVE_NUMERICAL_WITHIN_TESTED_PROFILES`。只有身份、宽度和数值判据全部通过，才允许写
`SUPPORTED_STRONG_NONLINEAR_WIDTH_RESPONSE_IN_FIXED_LONG_AFFINE_ARM8`。

即使最强结论成立，它也只适用于100 u、+1、10 eV、`AFFINE z-vz`、固定长焦2.2 mm匹配结构、
`W=1.0–2.2 mm`和本登记两个数值对照。它能够排除本矩阵覆盖的`dt160/dt320`与`tqual_8/tqual_108`
差异是主因，并证明强宽度效应在无真实PA电场的全域理想场中仍存在；它不能：

- 验证每个宽度分别重新匹配加速器/反射器后是否仍有同样展宽；
- 检验或外推`W>2.2 mm`，也不能区分更宽源的接受孔径、能量包络与高阶像差；
- 唯一判定二阶、三阶或其他单独阶次，更不能只用三点log slope声称“三阶主导”；
- 分配Stage1、Stage2、反射器或真实栅附近场各自贡献；
- 代表true-zero-vz、多极杆真实束、短焦结构、真实PA场、其他质量/能量或Formal性能。

若后续需要验证per-width rematch或`W>2.2 mm`，必须在任何新增求解前另建日期化预注册，重新冻结
对应理论派生结构、电压、能量/孔径接受包络和独立数值对照；不得向本五格矩阵临时追加cell。
