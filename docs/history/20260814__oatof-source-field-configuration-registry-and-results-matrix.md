# oaTOF源、场与结构配置注册表及结果矩阵（2026-08-14）

> `DOC_STATUS: ARCHIVED_READ_ONLY`

## 文档职责与命名规则

本快照是同日
[`原生栅网、场、源与短长焦调查`](20260814__oatof-native-grid-field-source-focus-investigation.md)
的补充与命名勘误。原快照已经冻结，不回写；本文件把其中同一源、cohort、结构、栅网、场、数值和时钟
配置赋予唯一注册名，并按这些注册名重列结果。后续引用本轮数据时必须同时写注册名和必要的cohort，不能
只写“理想源”“真实场”“短焦”“长焦”或“RR”。

旧文档中的`actual/real field`统一解释为“真实SIMION PA加速场”，不是实验测量场；`ideal field`统一
解释为“解析分段均匀加速场”，不是“加速器和反射器均理想”。本矩阵所有反射器均为真实SIMION PA
反射器场。`RR/IR/RI/II`的两个字母只表示加速器Stage1/Stage2，依次为Real或Ideal；它们不编码反射器。

## 统一配置注册表

### 离子源与cohort

|注册名|唯一显示名|定义与身份边界|
|---|---|---|
|`SRC-REAL-OCT-SHA302C`|真实八极杆整机母束（SHA302C）|从多极杆入口连续释放的有序N=1000母束，完整SHA-256为`302C03DC...D5320D`|
|`SRC-REAL-RESTART-N806`|历史冻结真实八极杆restart束（N806）|短焦源替换A/B中冻结的806粒子观察源；不与整机母束注册名互换|
|`SRC-IDEAL-SHORT-Z10`|短焦1.0 mm理想线性z–vz源族|只用于没有稳定源SHA的历史N77结果；身份由对应run和cohort共同冻结|
|`SRC-IDEAL-SHORT-Z10-SHA446332`|短焦1.0 mm理想线性z–vz源（SHA446332）|N1000源文件`rf_oatof_short_focus_ideal_linear_z_vz_entry_n1000.csv`，完整SHA-256为`446332EFF94EA3C65BC5E79FCEC458E7681DF8E235AE28B5039F801590AD22D5`|
|`SRC-IDEAL-SHORT-Z10-SHA5AABC`|短焦理想线性z–vz确定性分层子源（SHA5AABC）|由SHA446332母源按global ID分层抽取的N100，完整SHA-256为`5AABC891DDAE7E77716F1842052E11CBBA066DF8B415D16EE807F51B4289605A`|
|`SRC-IDEAL-Z22-AXIAL`|2.2 mm理想轴向有限区源|2.2 mm轴向区间的理论源族；短焦N77与长焦N70不是同一cohort|
|`SRC-IDEAL-LONG-HIST-70FA`|历史冻结1.0 mm理想线性z–vz源（SHA70FA）|长焦method comparator使用的同一pre-pulse N835源；完整SHA-256为`70FA718C...9F71A`|
|`SRC-IDEAL-CUBE-1MM`|独立1 mm理想立方源（vz=0）|N806源替换诊断中的反事实源；不保持真实束的z–vz相关性|

|cohort注册名|来源|精确定义|
|---|---|---|
|`COHORT-SHORT-Z10-N77`|`SRC-IDEAL-SHORT-Z10`|短焦N77场A/B的同一粒子cohort|
|`COHORT-SHORT-Z10-N1000-SHA446332`|`SRC-IDEAL-SHORT-Z10-SHA446332`|短焦2×2与dz诊断的同一N1000 cohort|
|`COHORT-LONG-Z22-AB-N70`|`SRC-IDEAL-Z22-AXIAL`|长焦N70真实/理想加速场A/B的同一cohort|
|`COHORT-Z22-SHORT-N77`|`SRC-IDEAL-Z22-AXIAL`|2.2 mm源进入短焦结构的N77 cohort|
|`COHORT-Z22-LONG-N70`|`SRC-IDEAL-Z22-AXIAL`|2.2 mm源进入长焦结构的N70 cohort；不与上一行逐粒配对|
|`COHORT-LONG-HIST-N835`|`SRC-IDEAL-LONG-HIST-70FA`|method comparator A/B/C冻结的同一835粒子|
|`COHORT-OCT-MECH-N695`|`SRC-REAL-OCT-SHA302C`|pulse时位于Stage1轴向开区间且xy位于±5 mm孔径内的共同695 IDs；仅为机械接受cohort|
|`COHORT-OCT-LONG-ALL-N737`|`SRC-REAL-OCT-SHA302C`|长焦全部探测命中737粒子|
|`COHORT-OCT-SHORT-ALL-N739`|`SRC-REAL-OCT-SHA302C`|短焦全部探测命中739粒子|
|`COHORT-TQUAL-STRAT-N100-SHA5AABC`|`SRC-IDEAL-SHORT-Z10-SHA5AABC`|按global ID确定性分层抽取的N100，含global ID 715|

`COHORT-OCT-MECH-N695`的“接受”不表示电场均匀性筛选，也不是看过探测结果后的筛选；短、长结构最终
比较使用完全相同的695个global IDs。`COHORT-Z22-SHORT-N77`与`COHORT-Z22-LONG-N70`只共享源族定义，
不共享粒子身份，因此跨结构差异只能作描述性证据。

### 结构、栅网、场、数值与时钟

|类别|注册名|唯一显示名与定义|
|---|---|---|
|结构|`ARCH-SHORT-Z10-R100`|短焦1.0 mm理论结构；`theory_source_z10_d1_3`，紧凑反射器35/70/100 mm、8/15环、厚2 mm|
|结构|`ARCH-LONG-Z22-R100`|长焦2.2 mm有限区结构；`symmetric_10ev_source_z22_finite_interval_theory`，同紧凑反射器族|
|栅网|`GRID-NATIVE-ONE-ROW`|SIMION官方原生一行零grid-unit厚透明栅，PA `surface=none`；grid1/grid2/entgrid/midgrid均无teleport|
|栅网|`GRID-LEGACY-EPSILON`|历史epsilon/teleport实现；只作只读方法对照，禁止用于新实现|
|加速场|`ACC-RR`|Stage1真实SIMION PA＋Stage2真实SIMION PA|
|加速场|`ACC-IR`|Stage1解析理想＋Stage2真实SIMION PA|
|加速场|`ACC-RI`|Stage1真实SIMION PA＋Stage2解析理想|
|加速场|`ACC-II`|Stage1＋Stage2均为解析理想分段均匀场|
|反射场|`REFL-REAL-R100`|紧凑结构真实SIMION PA反射器场，`oatof_reflectron_z010_r100`：轴向0.1 mm、径向1.0 mm|
|反射场|`REFL-REAL-FORMAL025`|真实SIMION PA反射器场，`oatof_formal_mesh`：轴向0.25 mm、径向1.0 mm|
|数值|`NUM-ACC-DZ005-Q8`|加速器overlay `dz=0.05 mm`，SIMION `T.Qual=8`；未证明收敛|
|数值|`NUM-ACC-DZ0025-Q8`|仅把加速器overlay改为`dz=0.025 mm`，其余与dz005配对|
|数值|`NUM-ACC-DZ005-Q108`|`dz=0.05 mm`，受治理SIMION `T.Qual=108`|
|数值|`NUM-METHOD-FORMAL025`|method comparator：frontend各向同性0.2 mm、无accelerator overlay、反射器轴向0.25 mm/径向1.0 mm|
|数值|`NUM-WHOLE-Z005-FORMAL025-Q8`|whole-stage：accelerator overlay `dz=0.05 mm`、反射器轴向0.25 mm/径向1.0 mm、`T.Qual=8`、RF每周期160步|
|数值|`NUM-RUNBOUND-SHORT-N77`|历史短焦N77 run-bound单点数值配置；无稳定独立配置SHA，不可外推或与新native数值身份混用|
|数值|`NUM-RUNBOUND-LONG-N70`|历史长焦N70 run-bound单点数值配置；无稳定独立配置SHA|
|数值|`NUM-RUNBOUND-Z22-SHORT-N77`|历史2.2 mm源进入短焦的run-bound单点数值配置|
|数值|`NUM-RUNBOUND-Z22-LONG-N70`|历史2.2 mm源进入长焦的run-bound单点数值配置|
|时钟|`CLOCK-PULSE-EFFECTIVE`|`t_TOF=t_detector-t_pulse,effective`；本矩阵R的唯一合法时钟|
|时钟|`CLOCK-ABS-DIAGNOSTIC`|absolute instrument timestamp；只用于调度、事件排序和配对，禁止计算或声明R|

`RR`以后只能写为`ACC-RR`，或展开为“Stage1真实＋Stage2真实”；不能把它理解为“真实加速器＋真实
反射器”。结果表不采用隐含默认值：每行必须显式给出源/cohort、结构、栅网、加速场、反射场、数值和
时钟身份。

## 统一结果矩阵

### 源、加速场与结构主结果

R统一保留3位，时间FWHM统一保留6位。多峰数来自direct KDE模式计数。

|源注册名／cohort|结构|栅网|加速场|反射场|数值|时钟|N|R|FWHM (ns)|模式|证据与解释|
|---|---|---|---|---|---|---|---:|---:|---:|---:|---|
|`SRC-IDEAL-SHORT-Z10`／`COHORT-SHORT-Z10-N77`|`ARCH-SHORT-Z10-R100`|`GRID-LEGACY-EPSILON`|`ACC-RR`|`REFL-REAL-R100`|`NUM-RUNBOUND-SHORT-N77`|`CLOCK-PULSE-EFFECTIVE`|77|15,028.088|1.074719|1|run `20260813_162500...n77`冻结源与数值身份|
|`SRC-IDEAL-SHORT-Z10`／`COHORT-SHORT-Z10-N77`|`ARCH-SHORT-Z10-R100`|`GRID-LEGACY-EPSILON`|`ACC-II`|`REFL-REAL-R100`|`NUM-RUNBOUND-SHORT-N77`|`CLOCK-PULSE-EFFECTIVE`|77|81,182.600|0.198941|1|同cohort场A/B|
|`SRC-IDEAL-Z22-AXIAL`／`COHORT-LONG-Z22-AB-N70`|`ARCH-LONG-Z22-R100`|`GRID-LEGACY-EPSILON`|`ACC-RR`|`REFL-REAL-R100`|`NUM-RUNBOUND-LONG-N70`|`CLOCK-PULSE-EFFECTIVE`|70|10,975.323|1.468338|1|run `20260813_163500...n70`冻结源与数值身份|
|`SRC-IDEAL-Z22-AXIAL`／`COHORT-LONG-Z22-AB-N70`|`ARCH-LONG-Z22-R100`|`GRID-LEGACY-EPSILON`|`ACC-II`|`REFL-REAL-R100`|`NUM-RUNBOUND-LONG-N70`|`CLOCK-PULSE-EFFECTIVE`|70|9,794.285|1.645369|1|不能由末端R单独判定真实场优于理想场|
|`SRC-IDEAL-Z22-AXIAL`／`COHORT-Z22-SHORT-N77`|`ARCH-SHORT-Z10-R100`|`GRID-LEGACY-EPSILON`|`ACC-II`|`REFL-REAL-R100`|`NUM-RUNBOUND-Z22-SHORT-N77`|`CLOCK-PULSE-EFFECTIVE`|77|10,385.740|1.555085|—|与下一行非逐粒配对|
|`SRC-IDEAL-Z22-AXIAL`／`COHORT-Z22-LONG-N70`|`ARCH-LONG-Z22-R100`|`GRID-LEGACY-EPSILON`|`ACC-II`|`REFL-REAL-R100`|`NUM-RUNBOUND-Z22-LONG-N70`|`CLOCK-PULSE-EFFECTIVE`|70|10,345.193|1.557749|—|与上一行仅差约0.39%，为描述性结构证据|
|`SRC-IDEAL-LONG-HIST-70FA`／`COHORT-LONG-HIST-N835`|`ARCH-LONG-Z22-R100`|`GRID-LEGACY-EPSILON`|`ACC-RR`|`REFL-REAL-FORMAL025`|`NUM-METHOD-FORMAL025`|`CLOCK-PULSE-EFFECTIVE`|835|3,948.519|4.082080|2|历史方法A；A→B是实现bundle|
|`SRC-IDEAL-LONG-HIST-70FA`／`COHORT-LONG-HIST-N835`|`ARCH-LONG-Z22-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-RR`|`REFL-REAL-FORMAL025`|`NUM-METHOD-FORMAL025`|`CLOCK-PULSE-EFFECTIVE`|835|87,941.400|0.183250|1|官方原生方法B，835/835|
|`SRC-IDEAL-LONG-HIST-70FA`／`COHORT-LONG-HIST-N835`|`ARCH-LONG-Z22-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-II`|`REFL-REAL-FORMAL025`|`NUM-METHOD-FORMAL025`|`CLOCK-PULSE-EFFECTIVE`|835|199,314.100|0.080853|5|官方原生方法C；高R但多峰|
|`SRC-REAL-OCT-SHA302C`／`COHORT-OCT-MECH-N695`|`ARCH-LONG-Z22-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-RR`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|695|8,470.653|1.902422|1|695/695探测命中|
|`SRC-REAL-OCT-SHA302C`／`COHORT-OCT-MECH-N695`|`ARCH-SHORT-Z10-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-RR`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|695|8,410.717|1.920195|2|同一695 IDs；较长焦低约0.713%|
|`SRC-REAL-OCT-SHA302C`／`COHORT-OCT-LONG-ALL-N737`|`ARCH-LONG-Z22-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-RR`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|737|8,381.230|1.922720|—|全部探测命中粒子|
|`SRC-REAL-OCT-SHA302C`／`COHORT-OCT-SHORT-ALL-N739`|`ARCH-SHORT-Z10-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-RR`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|739|8,284.432|1.949471|—|全部探测命中粒子|

独立源替换诊断使用同一806粒子底板：`SRC-REAL-RESTART-N806`为
`R=9,227.424, FWHM=1.689096 ns, 1 mode`；
`SRC-IDEAL-CUBE-1MM`为`R=5,762.252, FWHM=2.704860 ns, 2 modes`。它证明“空间更窄且vz=0”不等于
更匹配的源，因为替换丢失了真实束中有利的z–vz相关性。

### 短焦N1000加速区2×2归因

本表统一使用`SRC-IDEAL-SHORT-Z10-SHA446332`／`COHORT-SHORT-Z10-N1000-SHA446332`、`ARCH-SHORT-Z10-R100`、
`GRID-NATIVE-ONE-ROW`、`REFL-REAL-R100`、`NUM-ACC-DZ005-Q8`。两个字母只表示加速器Stage1/Stage2。

|臂|加速场注册名|R|FWHM (ns)|模式|焦面sigma (ns)|
|---|---|---:|---:|---:|---:|
|RR|`ACC-RR`|44,805.570|0.360465|2|0.061034|
|IR|`ACC-IR`|62,185.180|0.259723|2|0.057767|
|RI|`ACC-RI`|28,033.040|0.576145|2|0.003808|
|II|`ACC-II`|27,691.310|0.583252|3|0.020389|

焦面Stage1、Stage2及交互的平均效应分别为`-0.050745/+0.337887/-0.015788 ns`。这只说明在该短焦
理想源、该单一数值设置的焦面上，Stage2是主要场敏感区；末端R受多峰和反射传播影响而不单调。它不
覆盖早期真实束粗PA链中Stage1/grid1数值边界层的主要限制。

三检查面的Stage1/Stage2/交互平均效应为：grid1
`+0.369827/+0.001455/-0.001455 ns`，加速器出口
`+0.092296/+0.322395/-0.010552 ns`，焦面
`-0.050745/+0.337887/-0.015788 ns`。三者使用同一半差分约定，不能与单臂总FWHM直接相加。

### 数值敏感性结果

|比较|源/cohort与场|基准R / FWHM (ns)|变化点R / FWHM (ns)|预声明主门|
|---|---|---|---|---|
|`NUM-ACC-DZ005-Q8`→`NUM-ACC-DZ0025-Q8`|`SRC-IDEAL-SHORT-Z10-SHA446332`／`COHORT-SHORT-Z10-N1000-SHA446332`，`ACC-RR`，`REFL-REAL-R100`，`CLOCK-PULSE-EFFECTIVE`|44,805.570 / 0.360465|47,345.609 / 0.341127|焦面均值`+0.001089 ns` PASS；paired sigma`0.039935 ns` FAIL|
|`NUM-ACC-DZ005-Q8`→`NUM-ACC-DZ005-Q108`|`SRC-IDEAL-SHORT-Z10-SHA5AABC`／`COHORT-TQUAL-STRAT-N100-SHA5AABC`，`ACC-RR`，`REFL-REAL-R100`，`CLOCK-PULSE-EFFECTIVE`|33,043.150 / 0.488781|31,137.600 / 0.518692|焦面均值`+0.002293 ns` PASS；paired sigma`0.038453 ns` FAIL|

dz比较在探测器面的配对均值/sigma为`+0.003546/0.039869 ns`。T.Qual比较在canonical detector面的
配对均值/sigma/RMS/最大绝对偏移为`+0.002159/0.038472/0.038340/0.074833 ns`；两端均为双峰，R只作
次级描述量。

早期真实束、整体`0.2 mm`粗PA到局部加速器`dz=0.05 mm`的同808粒子诊断，R由`8,427`提高至
`20,883`，焦面sigma由`4.431 ns`降至`1.472 ns`，接近仅Stage1理想场的`R=21,792`。该结果定位了
Stage1/grid1附近数值边界层的重要性，但它属于旧teleport时期单点，不是收敛证明，不能与上述原生栅
N1000 2×2互相覆盖。

### 真实八极杆整机census与配对量

|结构|连续census|机械接受cohort|平均TOF (us)|时间sigma (ns)|R / FWHM (ns) / 模式|
|---|---|---|---:|---:|---|
|`ARCH-LONG-Z22-R100`|1000→967 handoff→916 pre-pulse→758反射器→737探测|`COHORT-OCT-MECH-N695`，695/695探测|32.229709681|0.788601|8,470.653 / 1.902422 / 1|
|`ARCH-SHORT-Z10-R100`|1000→967 handoff→916 pre-pulse→759反射器→739探测|同一`COHORT-OCT-MECH-N695`，695/695探测|32.300651872|0.784323|8,410.717 / 1.920195 / 2|

在共同695 IDs上，短焦减长焦的平均TOF为`+70.942192 ns`，配对差值sigma为`0.059273 ns`，两臂相关
系数为`0.99717`。结构变化是源宽、位置、电压、布局和反射器匹配的bundle，不能把该延迟或R差单独归因
于几何焦距。

## 影响总结

1. **源宽及源—结构匹配。** `SRC-IDEAL-SHORT-Z10`历史N77 cohort在短焦`ACC-II`下达到`R=81,182.600`；改用
   `SRC-IDEAL-Z22-AXIAL`后短焦降至`R=10,385.740`。短焦焦面时间sigma由`0.01980 ns`增至
   `0.10985 ns`，约5.55倍。因此早期1.0 mm短焦与2.2 mm长焦的数量级差异主要混入源宽，不能归因于
   焦距。
2. **短焦与长焦结构。** 在同一`SRC-IDEAL-Z22-AXIAL`源族和`ACC-II`下，短/长结构R只差约0.39%；
   在同一`COHORT-OCT-MECH-N695`和`ACC-RR`下只差约0.713%。当前证据不支持“长焦结构天然差一个
   数量级”。前者不是同cohort，只能描述；后者才是同global IDs配对整机比较。
3. **真实束。** `SRC-REAL-OCT-SHA302C`即使限制到机械接受cohort，R仍约8,400；横向相空间、位置—
   速度—时间相关和非高斯尾没有被“位于孔径内”消除。独立立方源结果进一步说明去掉z–vz相关性可能
   恶化而不是改善。
4. **真实与理想加速场。** 同一`COHORT-LONG-HIST-N835`、官方原生栅下，`ACC-RR`为`R=87,941.400`，
   `ACC-II`为`R=199,314.100`，说明真实PA场形仍是重要限制；但后者有5个模式，不能只按R排序。
5. **栅网方法。** `GRID-LEGACY-EPSILON`到`GRID-NATIVE-ONE-ROW`的A→B变化很大，但同时改变完整实现
   bundle，不能把全部差异归为穿栅计算误差；B→C才是同原生资产下的加速场A/B。
6. **数值误差。** dz和T.Qual的paired sigma门均FAIL且量级接近。当前只能说透明栅附近同时存在真实
   边缘场、PA空间离散和轨迹积分敏感性，不能断言全是grid设置错误，也不能断言全是真实场物理。

## 资格边界

- 本矩阵是Functional/diagnostic历史证据，不晋升Candidate性能或Formal。
- N77、N70和N100结果是小样本或分层数值诊断；N1000的2×2仍只有单一空间网格基线。
- `dz=0.05→0.025 mm`与`T.Qual=8→108`均未通过预声明paired-sigma门，数值收敛状态为**FAIL**。
- 多峰结果必须同时报告mode count；`R=199,314.100`不是“最高单峰分辨率”。当前矩阵内最高单峰诊断
  是method comparator B的`R=87,941.400`；不同源、结构和cohort之间不能据此建立性能排行榜。
- `CLOCK-ABS-DIAGNOSTIC`不得计算R。旧absolute-clock R `9,528.830/212,248/481,052`、2×2旧
  `107,789/149,599/67,439/66,617`、dz旧`107,789/113,900`及q旧`79,492/74,908`全部禁止用于分辨率声明。
- 这里的“理想接受区”统一更名为`COHORT-OCT-MECH-N695`，避免误读为电场均匀区。

## Evidence run IDs

|证据组|有效run或analysis ID|
|---|---|
|官方一行栅smoke|`20260813_160656__gate__simion__native-ideal-grid__smoke`|
|真实观察源/独立立方源|`20260813_162000__sim__simion__r100-real-vs-ideal-source__n806`|
|短焦N77 `ACC-RR/ACC-II`|`20260813_162500__sim__simion__r100-short-ideal-source-real-accel__n77`; `20260813_163000__sim__simion__r100-short-ideal-source-ideal-accel__n77`|
|长焦N70 `ACC-RR/ACC-II`|`20260813_163500__sim__simion__r100-long-ideal-source-real-accel__n70`; `20260813_164000__sim__simion__r100-long-ideal-source-ideal-accel__n70`|
|长焦method comparator原生B/C|`20260813_183000__sim__simion__rf-oatof-single-flight-gap0__n835__r05`; `20260813_183100__sim__simion__rf-oatof-single-flight-gap0__n835__r05`|
|短焦2×2 solver|RR canonical receipt `20260813_215500__analysis__cross__rr-canonical-clock-n1000`; IR `20260813_212000__sim__cross__short-winner-ideal-stage1__n1000__r03`; RI `20260813_213000__sim__cross__short-winner-ideal-stage2__n1000__r01`; II `20260813_214000__sim__cross__short-winner-ideal-stage1-stage2__n1000__r01`|
|短焦2×2分析|`20260813_220000__analysis__stage-field-2x2-canonical__n1000`|
|dz细点与配对分析|`20260813_223000__sim__cross__short-rr-accel-dz0025__n1000__r03`; `20260813_224000__analysis__cross__rr-accelerator-dz-convergence-n1000`|
|T.Qual q108与正式配对|`20260814_010000__sim__simion__rf-oatof-single-flight-gap0__n100__r01`; `20260814_030000__analysis__python__rr-tqual8-vs108-paired-n100__r03`|
|whole-stage长/短与比较|`20260813_233000__analysis__cross__oct-whole-native-pulse-p00625-postselection__n1000`; `20260814_003000__analysis__cross__oct-whole-short-p00625-postselection__n1000`; `20260814_003500__analysis__cross__oct-whole-short-long-postselection__n1000`|
|旧粗PA/局部细PA|`20260813_080000__sim__simion__rf-oatof-stage1-overlay-ab__n1000__r01`|

2.2 mm源跨结构的N77/N70结果由同日原调查及其绑定的结构/源宽比较receipt追溯；它不是逐粒run pair，
因此本表不为其补造一个不存在的共同run ID。
