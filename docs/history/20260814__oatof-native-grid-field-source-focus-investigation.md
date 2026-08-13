# oaTOF原生栅网、场、源与短长焦调查（2026-08-14）

> `DOC_STATUS: ARCHIVED_READ_ONLY`

## 目标、权威与统一口径

本快照汇总2026-08-13至14日从栅网实现、时钟和数值控制，到源/场分解、局部网格、轨迹质量及整机
短长焦比较的完整调查链。唯一分辨率时钟是
`t_TOF=t_detector-t_pulse,effective`；absolute instrument clock只用于事件排序与配对，禁止形成R声明。
粒子比较优先冻结同一母源、global ID、脉冲、几何与PA，仅改变预声明因素。所有R均为direct KDE FWHM
质量分辨率；小N、双/多峰结果只作诊断。

原生理想栅网的实现依据是SIMION本机例证`examples/geometry/parallel_plate_capacitor_2d.gem`及
`simion.com/info/grid.html`所示零grid-unit厚的一行raw electrode和PA `surface=none`语义。加速器
grid1/grid2及反射器entgrid/midgrid不再由Lua epsilon跳转、越层或TOF补偿。新single-flight链的
canonical clock由冻结source birth authority加solver-local elapsed只物化一次；RF时间离散冻结为
`rf_steps_per_period=160`，轨迹质量只能选受治理常量profile。

## 调查时间线与流程

1. 先以独立smoke重建PA并验证四个原生一行栅网的raw row、穿越次数和最终命中，隔离“栅网表示是否
   可运行”。
2. 在历史旧grid-teleport证据上完成真实源/理想源及短长焦理论源的场A/B，识别源宽、场形和结构因素；
   这些旧run只保留物理诊断，不给新原生栅网资格。
3. 对短焦紧凑RR winner统一canonical detector clock，以同N=1000完成加速一级/二级真实-理想`2x2`
   粒子级主效应和交互分析。
4. 只把accelerator overlay `dz=0.05→0.025 mm`，保持源、脉冲、几何、反射器网格、T.Qual和RF步数
   不变，执行配对局部空间网格检查。
5. 再用确定性分层N=100、同global IDs比较SIMION官方`T.Qual=8→108`，避免把轨迹积分误差误写成
   场或PA误差。
6. 最后以同一真实八极杆N=1000母源、原生栅网、全真实场和detector-blind共同eligible IDs比较整机
   短长焦，检验局部理论结论在真实六维束上的外推范围。

## 正式结果矩阵

|问题与证据|总体|pulse-effective结果|结论|
|---|---:|---|---|
|原生栅网smoke `20260813_160656__gate__simion__native-ideal-grid__smoke`|1粒子|raw rows `260/596/0/480`，穿越`1/1/2/2`并hit|Candidate功能PASS；无R、非收敛/Formal|
|短焦实际场源A/B `20260813_162000__sim__simion__r100-real-vs-ideal-source__n806`|806|真实观察源`R=9227.424, FWHM=1.689096 ns, 1 mode`；独立1 mm立方`vz=0`源`R=5762.252, 2.704860 ns, 2 modes`|任意“更理想”的独立源未必保留真实`z-vz`补偿|
|短焦1 mm理论线性源场A/B `20260813_162500...n77` / `20260813_163000...n77`|77|真实场`R=15028.088, 1.074719 ns`；全理想加速场`R=81182.600, 0.198941 ns`，均单峰|短焦理论有效，实际加速场形是强限制|
|长焦2.2 mm理论线性源场A/B `20260813_163500...n70` / `20260813_164000...n70`|70|真实场`R=10975.323, 1.468338 ns`；理想场`R=9794.285, 1.645369 ns`，均单峰|长焦损失不是简单“真实场更差”；小N且非高斯|
|同2.2 mm轴上源、理想加速场跨结构|短焦77/长焦70|长焦`R=10345.193, FWHM=1.557749 ns`；短焦`R=10385.74`，相差约0.39%|非逐粒配对，仅描述性支持结构影响小；早期`81182`与约`10k`差异主要来自源宽|
|长焦method comparator A/B/C|835|旧epsilon真实场`R=3948.519`；native真实场`R=87941.400`；native理想加速场`R=199314.100`但5 modes|实际冻结1 mm历史线性源、长焦架构名义接受宽2.2 mm；A→B是实施bundle，B→C才是同资产场A/B|
|短焦场`2x2` analysis `20260813_220000__analysis__stage-field-2x2-canonical__n1000`|1000|焦面Stage1/Stage2/交互平均效应`-0.050745/+0.337887/-0.015788 ns`|只在该短焦理想源2x2焦面中Stage2主导；paired deltas有效|
|accelerator `dz` analysis `20260813_224000__analysis__cross__rr-accelerator-dz-convergence-n1000`|1000|焦面均值偏移`+0.001089 ns`、paired sigma`0.039935 ns`；探测器`+0.003546/0.039869 ns`|均值门PASS、sigma门FAIL；`0.05 mm`未证明空间收敛|
|T.Qual analysis `20260814_030000__analysis__python__rr-tqual8-vs108-paired-n100__r03`|100|焦面`+0.002293/0.038453 ns`；detector q8/q108 `R=33043.15/31137.60`|轨迹质量主门FAIL；差值与dz效应同量级|
|whole-stage `20260814_003500__analysis__cross__oct-whole-short-long-postselection__n1000`|共同eligible 695|长焦`R=8470.653,1.902422 ns,1 mode`；短焦`R=8410.717,1.920195 ns,2 modes`|真实束整机下两者接近；不支持焦距单因果解释|

`2x2`原artifact把absolute instrument clock代入质量换算，所列旧R只允许作为legacy diagnostic，明确
`forbidden_for_resolution_claim`。按共同pulse-effective时钟重算的RR/IR/RI/II正式诊断R依次为
`44805.57/62185.18/28033.04/27691.31`；FWHM与场的粒子级paired deltas不受该绝对钟换算错误影响。
对应焦面sigma为`0.061034/0.057767/0.003808/0.020389 ns`：Stage2 ideal使RR→RI强改善，Stage1 ideal
的RR→IR几乎不变。该结论严格限定于短焦理想线性源N=1000的焦面，不覆盖早期真实束粗PA链中
Stage1/grid1数值边界层的主要限制；四臂终端均为多峰，pulse-effective R在后续反射器补偿下不单调。

whole-stage比较冻结母源SHA
`302C03DC29737CE9D46EB1A8D258DB2A8D3C0F8B6A53F7702A33B1ECF9D5320D`、原生一行栅网、真实加速器/
反射器场、overlay `dz=0.05 mm`、RF步数、T.Qual及`+0.0625 RF`脉冲。短/长焦detector-blind
eligible为完全相同695 IDs；短减长平均TOF为`70.942192 ns`，paired sigma为`0.059273 ns`。

## 证据、receipts与失败链

正式机器入口包括：

- `config/diagnostics/short_focus_winner_field_region_attribution_n1000_campaign.json`与analysis
  `stage_field_2x2_attribution.json`；RR原solver manifest失败，但canonical receipt
  `20260813_215500__analysis__cross__rr-canonical-clock-n1000/rr_canonical_clock_receipt.json`将保留日志绑定为
  SHA验证的canonical checkpoints，IR/RI/II正式run分别为`20260813_212000...r03`、`213000...r01`、
  `214000...r01`。
- `config/diagnostics/short_focus_rr_accelerator_dz_convergence_n1000_campaign.json`及设计receipt；细网格
  `20260813_223000__sim__cross__short-rr-accel-dz0025__n1000__r03`成功，r01/r02为失败尝试，不得混用。
- `config/diagnostics/short_focus_rr_tqual108_stratified_n100_campaign.json`、
  `short_focus_rr_tqual_n100_sample_receipt.json`及q108 run `20260814_010000...n100__r01`；正式派生只取r03，
  r01/r02为被取代的分析尝试。
- whole-stage长/短子分析分别为`20260813_233000...postselection__n1000`和
  `20260814_003000...postselection__n1000`，最终comparison manifest绑定JSON/CSV/PNG及其SHA。

另一个早期但有定位价值的局部PA A/B为
`20260813_080000__sim__simion__rf-oatof-stage1-overlay-ab__n1000__r01`：同808粒子由整体`0.2 mm`
PA的`R=8427`提高到局部accelerator `dz=0.05 mm`的`R=20883`，焦面sigma由`4.431`降至
`1.472 ns`，接近仅Stage1理想场`R=21792`。它发生在旧teleport时期且只有单点，能定位局部PA重要性，
不能证明收敛。

主要失败教训是：不得把旧solver manifest的失败等同于其后manifest-bound canonical reanalysis失败；
也不得直接把失败run中的临时输出晋升。schema未开放T.Qual profile时Validate正确拒绝；细网格r01/r02、
q派生r01/r02及method-comparator早期r03/r04均保持superseded。绝对instrument clock可用于配对，但不能
用于R；源local ID必须通过receipt映射global ID；见到结果后不得改配对门或eligible总体。

method comparator的A为历史旧epsilon/teleport实现，B/C正式native child为
`20260813_183000__sim__simion__rf-oatof-single-flight-gap0__n835__r05`和
`20260813_183100__sim__simion__rf-oatof-single-flight-gap0__n835__r05`；早期r03/r04失败并被取代。
A/B/C实际冻结pre-pulse源是1.0 mm linear `z-vz` N=835（SHA-256前缀`70FA`）；2.2 mm只表示长焦
architecture的名义接受/full width，不是该比较器的实际源宽。
A/B/C的pulse-effective FWHM和mode依次为`4.082080 ns/2`、`0.1832504 ns/1`、
`0.0808527 ns/5`。各summary内absolute-clock R `9528.83/212248/481052`均禁止用于分辨率声明；两个
native parent只获得`FUNCTIONAL_SCREEN_ONLY`，paired analysis未运行。

以下旧结果明确不可替代本矩阵：524 Da/5 eV Formal COMSOL/SIMION `R=39938.06/47662.02`使用不同质量、
源和架构；解析oracle `R=77093.87`与Arm8轴上solver closure `R=47493.49`使用全理论场/理想反射器；
历史`R=107739.8`同样不同源、质量和架构。旧absolute-clock `R=22562`无效；canonical重算约`9165.96`
仍属另一设计代。pulse hard-mask baseline/Arm8真实束`R=5015.88/3993.51`属于另一前端筛选链；预留
`20260813_150000`旧all-ideal run从未产生结果且已deprecated。

## 结论范围、资格与后续

- 原生一行栅网证明官方表面语义下的功能链闭合，但没有证明真实丝网、PA空间收敛或整机性能。
- 短焦1 mm线性源显示理想加速场可达很窄峰；长焦2.2 mm的高阶有限区间残差使理想场本身不再显著优于
  真实场。因此“短长焦巨大差异”首先是源宽/源-结构匹配问题，不能归结为焦距或漏改电压。
- 短焦理想源`2x2`把该总体的焦面主要场敏感性定位到Stage2；但`dz`和T.Qual均未过预声明sigma门，现有q8/dz0.05
  结果不能称数值收敛。两类数值效应与场效应必须分开报告。
- whole-stage同真实束的短长焦R相近，说明局部轴上理论优势没有直接转化为真实六维束整机优势。
- 当前Functional证据可用；数值收敛、Candidate性能、Formal、SIMION/COMSOL一致性和最终优化资格均为
  **FAIL/未完成**。下一步需以受治理T.Qual和RF时间步序列配合PA空间网格序列，使用同global IDs、
  canonical pulse-effective clock及预声明门；数值稳定后才允许N=1000多批、bootstrap和COMSOL handoff。
