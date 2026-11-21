# oaTOF规范矩阵的高阶时间像差续篇（2026-08-14）

DOC_STATUS: ARCHIVED_READ_ONLY

> `DOC_STATUS: ARCHIVED_READ_ONLY`

## 职责与证据边界

本文续接同日冻结的
[`oaTOF源、场与结构配置注册表及结果矩阵`](20260814__oatof-source-field-configuration-registry-and-results-matrix.md)，
记录随后完成的规范N=1000矩阵证据和由此产生的高阶时间像差解释。原矩阵不回写。本文使用原矩阵的
`ARCH-SHORT-Z10-R100`、`ARCH-LONG-Z22-R100`、`GRID-NATIVE-ONE-ROW`、`ACC-II`、
`REFL-REAL-FORMAL025`、`NUM-WHOLE-Z005-FORMAL025-Q8`和`CLOCK-PULSE-EFFECTIVE`注册名；两个
字母仍只编码加速器Stage1/Stage2，反射器场必须另列。

名称一致性适用于完整结果身份，而不只适用于源：同一机器身份的source、cohort、geometry、
accelerator field、reflector field、grid、solver numerics和clock在本文所有注册表、结果矩阵、正文与
successor映射中均沿用同一个规范注册名；任一维度身份不同则使用不同名称。“同上”只表示同一表内
沿用上一行完全相同的已注册身份，不构成别名或第二份配置定义。

这里的高阶分析不是从三个宽度点拟合出的唯一根因。首次归档前又用两个既有解析物理API完成了四行
精确组合诊断；它把2.2 mm的主矛盾收敛到全理想解析模型内已经存在的有限宽度高阶残差，并把真实PA/
下游实现的配对新增量收窄到约7%。但该组合尚无受治理receipt，所以仍是强诊断，不能替代SIMION实验或
晋升为Candidate/Formal证据；本文也不创建活动campaign。

## 规范affine z-vz cohort

本续篇按既有结果身份规则补登本轮两个稳定源；不得再用旧历史源族
`SRC-IDEAL-SHORT-Z10`或`SRC-IDEAL-Z22-AXIAL`代指它们：

|源注册名|稳定显示名|机器profile id|cohort与内容身份|
|---|---|---|---|
|`SRC-CANON-IDEAL-LINEAR-ZVZ-1MM-N1000-SHA0E900A`|规范1.0 mm理想线性z–vz源（N1000，SHA0E900A）|`canonical_ideal_linear_z_vz_1mm_n1000`|`COHORT-CANON-IDEAL-LINEAR-ZVZ-1MM-N1000-SHA0E900A`；有序IDs 1..1000；SHA-256 `0E900A152C1F70D7F2D5DACFCBD8ABCF67A3F26B00A5F604C5C929F36FC8E152`|
|`SRC-CANON-IDEAL-LINEAR-ZVZ-2P2MM-N1000-SHADE5A76`|规范2.2 mm理想线性z–vz源（N1000，SHADE5A76）|`canonical_ideal_linear_z_vz_2p2mm_n1000`|`COHORT-CANON-IDEAL-LINEAR-ZVZ-2P2MM-N1000-SHADE5A76`；有序IDs 1..1000；SHA-256 `DE5A76C159F0045FA4F0BAC45D94D493B453A64B652FD225926315EAB00B59D7`|

同一宽度的短、长行材料化源CSV具有相同SHA和有序粒子身份；resolved坐标变换把它们放到各自结构的
全局脉冲中心。源身份相同不等于结构、场或全局坐标身份相同。

在脉冲有效时刻，以加速器局部轴向坐标写成

$$
z=z_c+\xi,\qquad \xi\in[-W/2,W/2],\qquad
v_z=\bar v_z+\kappa\xi .
$$

本轮1.0 mm与2.2 mm理想源共享同一个affine相空间定义，只改变全宽`W`：

|量|规范值|
|---|---:|
|局部中心 `z_c`|1.498375640839315 mm|
|平均轴向速度 `v̄_z`|-2.9323518410018137 m/s|
|斜率 `κ`|228.80604377795845 m/s/mm|
|全宽 `W`|1.0 mm或2.2 mm|
|质量、荷态、总注入动能|100 u、+1、10 eV|
|短焦全局中心|−68.45815512803617 mm|
|长焦全局中心|−65.85199245578829 mm|

源宽是实验因子；`z_c`、`v̄_z`和`κ`来自各编译结构的resolved finite-interval theory，并在当前短、
长结构中数值相同。2.2 mm包络内`v_z`约从−254.62到+248.75 m/s，横向速度按
`v_x^2+v_z^2=2E/m`补足，因此不能把它改写成“固定`v_x`再额外叠加`v_z`”的第二个源定义。

## 沿cohort的泰勒展开

令`T(z,v)`为从脉冲有效时刻到选定检查面或检测面的飞行时间。在`(z_c,v̄_z)`处定义沿affine cohort
的方向微分算子

$$
D=\partial_z+\kappa\partial_v .
$$

则

$$
T(z_c+\xi,\bar v_z+\kappa\xi)
=T_0+(DT)_0\xi+\frac{(D^2T)_0}{2}\xi^2
+\frac{(D^3T)_0}{6}\xi^3+\frac{(D^4T)_0}{24}\xi^4+O(\xi^5).
$$

前四阶系数显式为

$$
\begin{aligned}
DT={}&T_z+\kappa T_v,\\
D^2T={}&T_{zz}+2\kappa T_{zv}+\kappa^2T_{vv},\\
D^3T={}&T_{zzz}+3\kappa T_{zzv}+3\kappa^2T_{zvv}+\kappa^3T_{vvv},\\
D^4T={}&T_{zzzz}+4\kappa T_{zzzv}+6\kappa^2T_{zzvv}
       +4\kappa^3T_{zvvv}+\kappa^4T_{vvvv}.
\end{aligned}
$$

因此，只把纯位置导数`T_z,T_zz`调到零，并不等于把沿真实cohort的`DT,D²T`调到零；`T_zv`等混合
导数会通过已冻结的`κ`进入。当前resolved coupled solution给出的focus一、二阶残差接近数值零，但
`accelerator_third_derivative_at_focus`和`total_third_derivative`均为JSON `null`。`null`表示当前求解器
没有计算或声明该导数，绝不能解释为三阶导数等于零，更不能外推成所有高阶项为零。

## 理想均匀场为什么仍天然含高阶项

均匀电场并不会使飞行时间成为`z`和`v`的有限次线性或二次多项式。以一段长度`L`、恒加速度`a`为例，

$$
t_{\rm acc}=\frac{\sqrt{v_0^2+2aL}-v_0}{a},\qquad
t_{\rm drift}=\frac{L_d}{\sqrt{v_0^2+2aL}}.
$$

两式都含平方根或倒平方根。双级均匀场反射器的时间还含`\sqrt{E}`和`\sqrt{E-U_1}`及其与场强的
比值。即使电势在各段严格线性，只要在非零包络上展开，这些非多项式函数就自然产生三阶、四阶和更高
阶；在段边界联合匹配一阶、二阶，只消去了被求解条件显式约束的导数组合。

Wiley与McLaren的双场空间聚焦给出了位置展宽的经典低阶校正框架；reflectron用能量相关的穿透深度
补偿飞行时间差。后续离子光学文献明确以二阶、三阶及更高阶像差描述均匀场源和反射器，并指出初速度
分布会限制仅提高空间聚焦阶数所能获得的分辨率。可核验来源见
[Wiley & McLaren, 1955, DOI 10.1063/1.1715212](https://doi.org/10.1063/1.1715212)、
[Wollnik, 1993, DOI 10.1002/mas.1280120202](https://doi.org/10.1002/mas.1280120202)、
[Chernushevich et al., 2001, DOI 10.1016/S1387-3806(00)00314-6](https://doi.org/10.1016/S1387-3806(00)00314-6)
及
[Yildirim et al., 2010, DOI 10.1016/j.ijms.2009.12.014](https://doi.org/10.1016/j.ijms.2009.12.014)。
原始mass-reflectron论文可由同行评审期刊档案核验：
[Mamyrin et al., Sov. Phys. JETP 37 (1973) 45–48](https://jetp.ras.ru/cgi-bin/dn/e_037_01_0045.pdf)；
其后续综述为
[Mamyrin, 2001, DOI 10.1016/S1387-3806(00)00392-4](https://doi.org/10.1016/S1387-3806(00)00392-4)。

## 宽度缩放与本轮数值

若cohort保持自相似，即`ξ=Wu`且`u`的分布不变，则第`n`阶时间项的尺度为`W^n`。从1.0 mm放大到
2.2 mm时，二、三、四阶的纯尺度因子分别为

$$
2.2^2=4.84,\qquad 2.2^3=10.648,\qquad 2.2^4=23.4256\approx23.426.
$$

当前`ACC-II + REFL-REAL-FORMAL025`配对结果为：

|结构与检查面|1.0 mm population sigma (ns, ddof=0)|2.2 mm population sigma (ns, ddof=0)|比值|邻近的纯阶尺度|
|---|---:|---:|---:|---:|
|`ARCH-LONG-Z22-R100`加速器理论焦面|0.019277737|0.085277916|4.42365|二阶4.84|
|`ARCH-LONG-Z22-R100`检测面|0.084258179|0.909681180|10.796|三阶10.648|
|`ARCH-SHORT-Z10-R100`检测面|0.082730793|0.888355115|10.738|三阶10.648|

长焦焦面比值接近二阶尺度，而两个结构的检测面比值都接近三阶尺度。这种相近性说明“焦后传播放大
高阶残差”是值得检验的假设，却不是三阶项已经被唯一识别：检测面仍使用`REFL-REAL-FORMAL025`，真实
PA的有限环、孔径边缘场、栅附近场形和离轴传播都可产生与源宽相关的非线性；不同阶项之间也可能相消
或共同贡献。

对应N=1000证据为1.0 mm短/长`ACC-II` runs
`20260814_122000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03`、
`20260814_123000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03`，以及2.2 mm短/长`ACC-II` runs
`20260814_134000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03`、
`20260814_135000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03`。四行均为
`GRID-NATIVE-ONE-ROW`，不混用旧epsilon/teleport方法。

## 全理想精确解析四行诊断

首次归档前，使用仓库中两个既有权威API直接组合每个粒子的轴向飞行时间，未新建物理实现：

- `projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_time_focus.time_to_fixed_plane_s`：按带符号
  初始`vz`精确计算Stage1、Stage2恒加速度运动及到加速器理论焦面的漂移；
- `projects.single_reflection_oa_tof_mass_analyzer.analysis.reflectron_dual_stage_solver.flight_time_s`：按双级理想
  反射器和总场自由长度精确计算焦面到反射器、转向及返回检测面的时间。

逐粒子只作如下既有API组合：

$$
t_j=t_{\rm acc}(z_j,v_{z,j};L_{\rm focus},m/q)
 +t_{\rm refl}(W_j,m/q;L_{\rm up}+L_{\rm down},U_1,F_1,F_2),
$$

$$
W_j=(V_{\rm rep}-V_{\rm exit})-E_1z_j
 +\frac{1}{2}(m/q)_{\rm SI}v_{z,j}^{2},\qquad
z_j=z_c-\frac{w}{2}+\frac{wj}{N-1},\quad
v_{z,j}=\bar v_z+\kappa(z_j-z_c),\qquad j=0,\ldots,N-1.
$$

其中`w`、`N`、`v̄z`、`κ`来自源profile，`z_c`来自materialization receipt的目标合同，`m/q`由源
质量与电荷合同通过通用粒子物理API派生；短、长结构分别使用其resolved几何和联合求得的反射器场。输入身份绑定为：短焦1.0 mm
`20260814_122000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03`、长焦1.0 mm
`20260814_123000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03`、短焦2.2 mm
`20260814_134000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03`、长焦2.2 mm
`20260814_135000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03`。这些run id只提供冻结输入身份；
下表数值是本次解析组合诊断，不是这些SIMION run中新生成的receipt字段。

|结构|源|全理想平均TOF (µs)|全理想population sigma (ns, ddof=0)|全理想span (ns)|最大转向深度 (mm)|`ACC-II + REFL-REAL-FORMAL025` population sigma (ns, ddof=0)|真实场bundle相对全理想新增|绝对差 (ns)|
|---|---|---:|---:|---:|---:|---:|---:|---:|
|`ARCH-SHORT-Z10-R100`|`SRC-CANON-IDEAL-LINEAR-ZVZ-1MM-N1000-SHA0E900A`|32.301157905355|0.072364789713|0.381638926065|48.899909312|0.082730793|14.324%|0.010366003287|
|`ARCH-LONG-Z22-R100`|`SRC-CANON-IDEAL-LINEAR-ZVZ-1MM-N1000-SHA0E900A`|32.230207417131|0.074573062249|0.393231584653|48.605964347|0.084258179|12.987%|0.009685116751|
|`ARCH-SHORT-Z10-R100`|`SRC-CANON-IDEAL-LINEAR-ZVZ-2P2MM-N1000-SHADE5A76`|32.301041505908|0.828024536219|4.376726535078|55.628002600|0.888355115|7.286%|0.060330578781|
|`ARCH-LONG-Z22-R100`|`SRC-CANON-IDEAL-LINEAR-ZVZ-2P2MM-N1000-SHADE5A76`|32.230090789443|0.848057671713|4.475702572691|55.432857520|0.909681180|7.266%|0.061623508287|

表中百分比统一用population sigma定义为
`(sigma_REAL - sigma_IDEAL) / sigma_IDEAL`。四行在同一只读Python进程内总耗时小于1 s；短、长结构
resolved Stage2长度均为96.1563 mm，最大转向深度55.6281 mm，故四行都满足轴向转向深度安全边界。

这组诊断改变了主次顺序：2.2 mm全理想解析结果本身已经达到`0.8280/0.8481 ns`，长焦比短焦高
2.419%，没有出现“长焦应显著优于短焦”；切换到`ACC-II + REFL-REAL-FORMAL025`后仅再增加约7.3%。
因此当前主矛盾是2.2 mm affine z–vz有限区间在全理想加速器与全理想反射器中的高阶时间像差，真实PA、
漂移残余场、真实反射器及其边界实现bundle是次级新增量。1.0 mm行的相对新增量约13%–14%，但绝对值
只有约0.010 ns。上述配对不能把约7.3%越权解释为“纯反射器误差”，因为两侧还同时改变了真实PA/
漂移残余场和全域理想边界实现。

本次四行数值生成时没有受治理CLI为这一非零`vz`的精确组合签发receipt：
`oatof_oaaccelerator_coupling.py --write-samples`只物化位置并假设`vz=0`，
`verify_axial_ideal_closure.py`会拒绝非零初始轴向速度。因此四行只能标记为Functional/diagnostic强诊断，
不得写入正式结果矩阵、不得晋级、不得替代求解器实验。首次提交前已增加薄wrapper
`affine_axial_ideal_report.py`及八行声明式合同：它绑定resolved几何、源profile、materialization
receipt和source release CSV SHA，只组合既有加速器时间、静电出口能量、通用初始轴向动能与反射器
时间API，输出`PROVISIONAL`解析报告。报告与聚焦测试闭合不等于已发布受治理run/manifest。

报告汇总复用`compute_peak_metrics`，其中sample sigma使用`ddof=1`；为保持旧四行可比性，另保留明确命名
的population sigma（`ddof=0`）。同一wrapper/profile语义下增加的zero-vz四行不是求解器结果：它只把
profile中的`mean_velocity_z_m_per_s`和`velocity_z_slope_m_per_s_per_mm`同时置零，目标中心、宽度、
粒子数、resolved结构、反射器和source release CSV均保持配对。

|结构|宽度/profile|population sigma (ns)|sample sigma (ns)|direct FWHM (ns)|R|KDE模式|耦合设计能量包络 (V)|观察能量 (V)|包络外粒子|
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
|短焦|1.0 mm affine|0.072364790|0.072400999|0.060175919|268389.56|1|1948.337535–2051.662465|1948.343974–2051.669599|1|
|长焦|1.0 mm affine|0.074573062|0.074610377|0.062014600|259859.96|1|1884.471540–2115.528460|1947.493503–2052.520071|0|
|短焦|2.2 mm affine|0.828024536|0.828438859|0.689123978|23436.60|1|1948.337535–2051.662465|1886.374644–2113.691019|546|
|长焦|2.2 mm affine|0.848057672|0.848482019|0.705947385|22827.81|1|1884.471540–2115.528460|1884.503606–2115.562056|1|
|短焦|1.0 mm zero-vz|0.597943385|0.598242582|1.994488080|8097.58|2|1948.337535–2051.662465|1948.337535–2051.662465|0|
|长焦|1.0 mm zero-vz|0.585235675|0.585528513|1.948148130|8271.98|2|1884.471540–2115.528460|1947.487064–2052.512936|0|
|短焦|2.2 mm zero-vz|0.810862839|0.811268575|0.721890984|22372.52|2|1948.337535–2051.662465|1886.342578–2113.657422|546|
|长焦|2.2 mm zero-vz|0.776338839|0.776727300|0.698310684|23077.18|2|1884.471540–2115.528460|1884.471540–2115.528460|0|

包络权威是resolved geometry中的
`accelerator.finite_interval_theory.coupled_reflectron.energy_min_v/energy_max_v`。短焦1 mm affine仅上端
超出`0.007135 V`，长焦2.2 mm affine仅上端超出`0.033596 V`，均明确标成
`diagnostic_extrapolation`；短焦2.2 mm在两端各超出约`62 V`，有546个粒子在设计包络外，属于实质外推。
因此短焦2.2 mm不能作为其1 mm耦合设计的包络内性能声明。zero-vz并不普遍改善结果：1 mm两结构都由
单峰变为双峰且R降到约8.1k；2.2 mm中zero-vz只小幅改变宽度，说明原affine z-vz相关在1 mm内承担了
一阶时间聚焦，而2.2 mm残差主要仍是有限宽度高阶项。

## ZERO-VZ-AT-RELEASE SIMION定义域检查

随后只复用官方受支持的`resolved_layout_pulse_ideal_linear_z_vz`源材料化入口，检查把release文件中的
轴向速度置零会发生什么。该旧入口没有为这些run签发理论脉冲epoch/plane的逐粒子checkpoint闭合receipt，
因此两条成功行只能命名为`ZERO-VZ-AT-RELEASE`诊断，不能称为理论zero-vz源。为避免“同名异物”或
“异名同物”，本节统一注册整套配置，而不只注册源：

|配置维度|本节注册名|机器配置|
|---|---|---|
|1.0 mm release诊断源|`SRC-ZEROVZ-AT-RELEASE-1MM-N1000-SHAD4C515`|legacy机器ID `canonical_ideal_zero_vz_1mm_n1000`；有序IDs 1..1000；release CSV SHA-256 `D4C515829F1C28C712FB935612940E039DB3B56D24D56589DB4F5D6FDEAD844B`|
|2.2 mm release诊断源|`SRC-ZEROVZ-AT-RELEASE-2P2MM-N1000-SHA779D63`|legacy机器ID `canonical_ideal_zero_vz_2p2mm_n1000`；有序IDs 1..1000；release CSV SHA-256 `779D6311C397EAA8B7B92D96699296912E75BF496B5BE74D4DC17C5AB76193B6`|
|短/长结构|`ARCH-SHORT-Z10-R100` / `ARCH-LONG-Z22-R100`|`theory_source_z10_d1_3` / `symmetric_10ev_source_z22_finite_interval_theory`|
|加速器场|`ACC-II`|`accelerator_ideal_stage1_stage2_real_reflectron`中的Stage1/Stage2理想解析场|
|反射器场|`REFL-REAL-FORMAL025`|同一profile中的真实正式0.25 mm轴向PA；不得用`ACC-II`名称隐含反射器|
|网格/数值|`NUM-WHOLE-Z005-FORMAL025-Q8`|`frontend_isotropic_020_accelerator_overlay_z005_parallel2` + `oatof_formal_mesh` + `tqual_8`|
|时钟|`CLOCK-PULSE-EFFECTIVE`|`canonical_instrument_time_us`，分辨率使用`detector_time_minus_pulse_effective_time`|

两行1.0 mm正式run成功；源、加速场、反射场、结构、数值profile、脉冲偏移和时钟均按上表冻结：

|结构|源|census（launch→pre-pulse→detector）|平均TOF (µs)|sample sigma (ns)|直接FWHM (ns)|R|KDE模态|
|---|---|---:|---:|---:|---:|---:|---:|
|`ARCH-SHORT-Z10-R100`|`SRC-ZEROVZ-AT-RELEASE-1MM-N1000-SHAD4C515`|1000→868→868|32.301065570728|0.329845077|0.300049525|53,826.277|2|
|`ARCH-LONG-Z22-R100`|`SRC-ZEROVZ-AT-RELEASE-1MM-N1000-SHAD4C515`|1000→868→868|32.230123767502|0.315016668|0.283039677|56,935.772|2|

2.2 mm两行均为`release aperture incompatibility`：在编译后的SIMION体积中于粒子创建阶段失败，故
没有分辨率，也不得填入2×2性能表或称为理论zero-vz实验。
短焦run `20260814_162000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03`与长焦run
`20260814_163000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03`都通过了合同、PA/IOB、源和程序生成，
随后由SIMION报告`No particles created; Particle 1 terminated in electrode or beyond volume`。短焦首粒全局
z为−69.558155128036 mm，长焦首粒为−66.951992455788 mm；两者都等于各自中心减1.1 mm。
resolved结构虽然分别声明1.0/2.2 mm有限区间理论设计，但当前前端实际源释放开口合同仍为1.0 mm。

这不是资源失败：失败批次记录的最小系统可用内存约31.95 GB（约29.76 GiB），高于8 GiB门槛。它也不能通过裁剪、筛选
或自行重定位粒子修补，因为那会改变冻结cohort并引入非官方实现。对应affine 2.2 mm长焦成功run
`20260814_135000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03`的释放面z范围仅约
−65.848855到−65.829638 mm；其非零线性`v_z(z)`与脉冲前传播共同形成该释放状态。把`v_z`置零后，
材料化源直接铺满2.2 mm，因此“只把mean/slope归零”已经超出当前编译机器的可执行定义域。解析表中的
长焦2.2 mm zero-vz（sample sigma 0.776727300 ns，R 23,077.18）仍只是既有受治理物理API组合的
`PROVISIONAL`诊断；不能冒充求解器结果，也不能与affine `ACC-II + REFL-REAL-FORMAL025`的
population sigma 0.909681180 ns作正式求解器配对差值声明。

证据身份：成功短焦run manifest/summary SHA-256分别为
`67E6062E10494CF97C17F65EAF18598BC21EF50D165B513A8AA198D894133A7B`/
`B807D9BC165B28B372CE9896E989093BD2728C2023332DB2D36D91D1C5D14E38`；成功长焦分别为
`D7E22FE7275A04D221C0AB409D8D95CFBF65B860F7866EDE0FCA89DCC77A700F`/
`D338CC6C67BEA9ADF20C96550D9D5267774C0DE4283494493EAA4AEAA159C307`。失败短/长manifest SHA-256
分别为`3B254EFF0B97D81676EF18D16DB5070D749BD0A49C544F3E6B5348E8BF906734`和
`27CB044A4713CA23250F96BD915F71A4FC209F4545CE328ADA0FEA43F2E626E2`；共同失败summary SHA-256为
`10A683843E23C4D3EB18EDB575E1B54AD6580EDA519C30D94F7DC9D16AED3917`。

## 真实八极杆母束的八臂N=1000矩阵

本节补登同一campaign随后完成的八个`r04`真实SIMION run。八行统一使用
`SRC-REAL-OCT-SHA302C`、`GRID-NATIVE-ONE-ROW`、`REFL-REAL-FORMAL025`、
`NUM-WHOLE-Z005-FORMAL025-Q8`和`CLOCK-PULSE-EFFECTIVE`；短、长结构分别为
`ARCH-SHORT-Z10-R100`和`ARCH-LONG-Z22-R100`。`ACC-RR/IR/RI/II`仍只表示Stage1/Stage2，
不编码反射器。所有run均从1000粒子完整母束连续注入，没有预先按加速器接受或探测结果截断。

### 每臂自身cohort的原生summary结果

下表严格照录各child `summary.json`的`pulse_effective_peak`。这里的`N峰`是该臂自身
`pulse_eligible_population_count`且已探测的粒子数；因为Stage1场模式会改变脉冲前存活及合格身份，
`ACC-RR/RI`为695，而`ACC-IR/II`为706。该表适合审计每个原生run，不能直接当作八臂严格配对析因。

|结构|加速场|连续census：发射→handoff→pre-pulse→grid1→加速器出口→探测|N峰|平均TOF (µs)|sigma (ns)|FWHM (ns)|R|模式|
|---|---|---|---:|---:|---:|---:|---:|---:|
|`ARCH-SHORT-Z10-R100`|`ACC-RR`|1000→967→916→916→759→739|695|32.300651872|0.784323017|1.920194588|8,410.717|2|
|`ARCH-LONG-Z22-R100`|`ACC-RR`|1000→967→916→916→758→737|695|32.229709681|0.788601082|1.902421940|8,470.653|1|
|`ARCH-SHORT-Z10-R100`|`ACC-II`|1000→967→936→935→772→762|706|32.301120033|0.715189050|1.887925686|8,554.610|1|
|`ARCH-LONG-Z22-R100`|`ACC-II`|1000→967→936→936→768→755|706|32.230179679|0.715692925|1.870324061|8,616.160|1|
|`ARCH-SHORT-Z10-R100`|`ACC-IR`|1000→967→936→935→770→750|706|32.300585529|0.846513618|2.030656684|7,953.200|1|
|`ARCH-LONG-Z22-R100`|`ACC-IR`|1000→967→936→936→769→748|706|32.229644063|0.846183977|2.003488284|8,043.348|1|
|`ARCH-SHORT-Z10-R100`|`ACC-RI`|1000→967→916→916→762→752|695|32.301213682|0.693170264|1.803288117|8,956.145|1|
|`ARCH-LONG-Z22-R100`|`ACC-RI`|1000→967→916→916→757→744|695|32.230263158|0.693377804|1.784378062|9,031.177|1|

### 两种跨臂cohort口径

|cohort注册名|定义|N|有序particle-ID SHA-256|用途与边界|
|---|---|---:|---|---|
|`COHORT-REALOCT-ALL8-ELIGIBLE-DETECTED-N693`|八臂`pre_pulse_state`中均为`eligible`且八臂均有`detector_crossing`的交集|693|`7ADB146D7CD42A10A4B4E7590C044FC81C9E894FEECD5D0ECE71677F5D3B4FBB`|唯一主析因cohort；用于下述八行严格2×2表|
|`COHORT-REALOCT-ALL8-DETECTED-N733`|八臂全部`detector_crossing` ID的交集，不要求八臂均pulse-eligible|733|`D69A39638B44FCE1381EB217B6510C7FB0BC22B2D21858D5E5B026AE5F2DEB91`|仅作探测交集敏感性；不得与N693主表混用或替代其因果口径|

两个SHA统一由升序十进制particle ID逐行UTF-8/LF序列化，并保留末尾LF后计算。身份直接来自下节八份
manifest绑定的`single_flight_particle_checkpoints.csv`；当前没有仓库级成功campaign结果registry或
cohort receipt Schema，故这里只冻结人类可审计的派生身份和上游机器证据链接，不新建第二套Schema，
也不把只适用于“child成功、parent发布失败”的recovery receipt误用于本轮成功run。

### 严格N693主cohort结果与2×2析因

|结构|加速场|sigma (ns)|FWHM (ns)|R|模式|
|---|---|---:|---:|---:|---:|
|`ARCH-SHORT-Z10-R100`|`ACC-RR`|0.782762812|1.920723575|8,408.401|2|
|`ARCH-SHORT-Z10-R100`|`ACC-IR`|0.841979997|2.002806026|8,063.789|1|
|`ARCH-SHORT-Z10-R100`|`ACC-RI`|0.692191385|1.803451090|8,955.333|1|
|`ARCH-SHORT-Z10-R100`|`ACC-II`|0.711372052|1.869171567|8,640.437|1|
|`ARCH-LONG-Z22-R100`|`ACC-RR`|0.786942886|1.903207936|8,467.151|1|
|`ARCH-LONG-Z22-R100`|`ACC-IR`|0.841694942|1.974803885|8,160.174|1|
|`ARCH-LONG-Z22-R100`|`ACC-RI`|0.692183069|1.784806045|9,029.012|1|
|`ARCH-LONG-Z22-R100`|`ACC-II`|0.712030942|1.851729890|8,702.674|1|

效应方向统一定义为把指定Stage从Real切到Ideal（`I−R`）；Stage1、Stage2主效应取跨另一Stage的
平均半差，交互为完整difference-in-differences。正的sigma/FWHM效应表示变宽，正的R效应表示提高：

|结构|指标|Stage1 `I−R`|Stage2 `I−R`|Stage1×Stage2交互|
|---|---|---:|---:|---:|
|`ARCH-SHORT-Z10-R100`|sigma (ns)|+0.039198926|−0.110589686|−0.040036517|
|`ARCH-SHORT-Z10-R100`|FWHM (ns)|+0.073901464|−0.125453472|−0.016361974|
|`ARCH-SHORT-Z10-R100`|R|−329.754|+561.790|+29.716|
|`ARCH-LONG-Z22-R100`|sigma (ns)|+0.037299965|−0.112211908|−0.034904183|
|`ARCH-LONG-Z22-R100`|FWHM (ns)|+0.069259897|−0.120737943|−0.004672105|
|`ARCH-LONG-Z22-R100`|R|−316.658|+552.180|−19.361|

两种结构给出同方向、近同量级效应：理想化Stage1单独使峰稍宽，理想化Stage2使峰明显变窄；交互小于
Stage2主效应。四个对应field cell中短、长R差均小于1.2%，而短焦平均TOF相对长焦整体平移约
`+70.94 ns`。因此在这一真实八极杆共同cohort与冻结反射器下，结构选择主要改变绝对到达时刻，并未
造成早期理想源比较中的数量级分辨率差。上述结论仍是单一数值设置的Functional/diagnostic析因，不能
越权解释为Stage2的几何或电场已经优化，也不能把固定真实反射器与加速场的交互从Stage效应中剥离。

### 八行parent/child证据绑定

下表路径均相对工作区`C:/Users/Liao/mass_spectrometry/`，内容为完整路径而非省略号简称。每个parent
manifest均为`success`并把对应child manifest登记为输入；每个child manifest均为`success`并把对应
summary登记为`required_evidence`。parent summary只承担集成census与运行状态，峰指标以child summary
为权威。

|结构/场|parent manifest（SHA-256）|parent summary（SHA-256）|child manifest（SHA-256）|child summary（SHA-256）|
|---|---|---|---|---|
|短/`ACC-RR`|`artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260814_144000__sim__cross__matrix-realoct-short-rr__n1000__r04/run_manifest.json`<br>`1E46DBB2240608C0B8764C47AC2AAABFC9D5EA42BC3F6D4244F793D990D618E0`|`artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260814_144000__sim__cross__matrix-realoct-short-rr__n1000__r04/summary.json`<br>`727294A5A16E41A1660C2120A339E9B0FCA958A8A73E8E88A84C27CE5E69DDC5`|`artifacts/projects/rf_octupole_ion_optics/runs/20260814_144000__sim__simion__rf-oatof-single-flight-gap0__n1000__r04/run_manifest.json`<br>`D116FD8ABC3246C06902D010F4247AC622BC6CDACC11528C23F060692E999202`|`artifacts/projects/rf_octupole_ion_optics/runs/20260814_144000__sim__simion__rf-oatof-single-flight-gap0__n1000__r04/summary.json`<br>`4E393594802E13B23C501BE360F08E6307B72BBDA24FFFF9DF2E7D7D2DA8130C`|
|长/`ACC-RR`|`artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260814_145000__sim__cross__matrix-realoct-long-rr__n1000__r04/run_manifest.json`<br>`16CADDB6D937F0451B54A7023FD385394B1F5BC69313050EF6EA1A66215AA726`|`artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260814_145000__sim__cross__matrix-realoct-long-rr__n1000__r04/summary.json`<br>`3B3B389EC88042F230882F43C2B5F3D84FC954BD7CCC6BC3CBD347C876E5528F`|`artifacts/projects/rf_octupole_ion_optics/runs/20260814_145000__sim__simion__rf-oatof-single-flight-gap0__n1000__r04/run_manifest.json`<br>`A5599A25F3CEE98CD439AA1FBFC2C01670F5AE84FDA2A7BA88D4B2F9E446AABC`|`artifacts/projects/rf_octupole_ion_optics/runs/20260814_145000__sim__simion__rf-oatof-single-flight-gap0__n1000__r04/summary.json`<br>`3B1275F55A7600EE3CCF1CC9DFDF2B484616DB445AAA9D3055D023CF2E37DC83`|
|短/`ACC-II`|`artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260814_150000__sim__cross__matrix-realoct-short-ii__n1000__r04/run_manifest.json`<br>`6EFA4B748405F032DBF540EFB24409BC9C717734FB372B6E29D739CAD8F9AC69`|`artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260814_150000__sim__cross__matrix-realoct-short-ii__n1000__r04/summary.json`<br>`2ED1FD670B486912818EE2DC8991E37621239DC932D919D3EF6DEF36EECAAA22`|`artifacts/projects/rf_octupole_ion_optics/runs/20260814_150000__sim__simion__rf-oatof-single-flight-gap0__n1000__r04/run_manifest.json`<br>`4EF87E027EF6D0083793F9F361055EE80BE671206A4FB089231C6619B5451789`|`artifacts/projects/rf_octupole_ion_optics/runs/20260814_150000__sim__simion__rf-oatof-single-flight-gap0__n1000__r04/summary.json`<br>`589A7F3ADB8D7C91D72D9BDBAEBC39D5F71D84676FC63410D8BE62EA12D57121`|
|长/`ACC-II`|`artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260814_151000__sim__cross__matrix-realoct-long-ii__n1000__r04/run_manifest.json`<br>`4FCDC0FFF7CDBD69826D240B8F642C987AE51C2821FC5CDB329AD9388DE976B6`|`artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260814_151000__sim__cross__matrix-realoct-long-ii__n1000__r04/summary.json`<br>`81A0D22607940D1ECB3FBDB2230D9A925656843D9E267C1BED41DF6E0F586B28`|`artifacts/projects/rf_octupole_ion_optics/runs/20260814_151000__sim__simion__rf-oatof-single-flight-gap0__n1000__r04/run_manifest.json`<br>`DE6A9D292903B306006BA54848CD99E8F14B50F9ECF0788F87304FF06B507228`|`artifacts/projects/rf_octupole_ion_optics/runs/20260814_151000__sim__simion__rf-oatof-single-flight-gap0__n1000__r04/summary.json`<br>`92E0133405776BC19E293800FF1C04E73986938C83E7FAA6E69394F511987FCA`|
|短/`ACC-IR`|`artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260814_152000__sim__cross__matrix-realoct-short-ir__n1000__r04/run_manifest.json`<br>`716D777F210E8EED113740975B42F33D01596278C30A04588F8653B2859B7F3C`|`artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260814_152000__sim__cross__matrix-realoct-short-ir__n1000__r04/summary.json`<br>`FBFEFB0698363F8E9078DD9441158493F5BDBB56C9E6D46D3CC904DB4EC5EA00`|`artifacts/projects/rf_octupole_ion_optics/runs/20260814_152000__sim__simion__rf-oatof-single-flight-gap0__n1000__r04/run_manifest.json`<br>`1B7268C1FC7617857316CE925546DD234F922F7BEB4BB34F5D0E58605840209E`|`artifacts/projects/rf_octupole_ion_optics/runs/20260814_152000__sim__simion__rf-oatof-single-flight-gap0__n1000__r04/summary.json`<br>`2F06FE29656EA2DEEA9FF3EDCEE1A8B1C307A16D714A3AFDAF57AF331F582444`|
|长/`ACC-IR`|`artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260814_153000__sim__cross__matrix-realoct-long-ir__n1000__r04/run_manifest.json`<br>`ECC1CF4FDEDBCDCDD0D3141CE768C55CBEF8D4B7CFB058F2EDA3CE42118AFF57`|`artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260814_153000__sim__cross__matrix-realoct-long-ir__n1000__r04/summary.json`<br>`2011520BD216E242CC07404636DD16BCBEF8737F6A82221D27FFB65FBB55F0A3`|`artifacts/projects/rf_octupole_ion_optics/runs/20260814_153000__sim__simion__rf-oatof-single-flight-gap0__n1000__r04/run_manifest.json`<br>`D305C51F19CB9ED7EE96426538077A0CDE0E71E6FCA52FCA3AFCEA27D26F74DA`|`artifacts/projects/rf_octupole_ion_optics/runs/20260814_153000__sim__simion__rf-oatof-single-flight-gap0__n1000__r04/summary.json`<br>`9089CBC39C22BDAB87D922550EF363683B1D98980AB5EBD254EFB542F93A9927`|
|短/`ACC-RI`|`artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260814_154000__sim__cross__matrix-realoct-short-ri__n1000__r04/run_manifest.json`<br>`85D2146D5BBABA83506BBE6F05F56E245BE8DE947577B70D920016775A0D1E57`|`artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260814_154000__sim__cross__matrix-realoct-short-ri__n1000__r04/summary.json`<br>`08F9EC93DD07C5AAB7275DBC325C6CC14DFFD658E877CFAB8808B41142A423D8`|`artifacts/projects/rf_octupole_ion_optics/runs/20260814_154000__sim__simion__rf-oatof-single-flight-gap0__n1000__r04/run_manifest.json`<br>`E800BEB5BF1B2C6E846B014946696719C2164B4092D0C307581E38C3B6D201F5`|`artifacts/projects/rf_octupole_ion_optics/runs/20260814_154000__sim__simion__rf-oatof-single-flight-gap0__n1000__r04/summary.json`<br>`FB60E5BD8DB0E17680BEFDF4FA62E866249A72E2CB4ADBE8B02C6E2F4241F36E`|
|长/`ACC-RI`|`artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260814_155000__sim__cross__matrix-realoct-long-ri__n1000__r04/run_manifest.json`<br>`42851968F778D3F7BD75373F8C0D9E548124C3D7CD4DDA463384DF11754F2FF9`|`artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260814_155000__sim__cross__matrix-realoct-long-ri__n1000__r04/summary.json`<br>`E8008517B3DF3B9C10554BF287DDBB8DF2229D68E6A54917D614B4DF8845FE59`|`artifacts/projects/rf_octupole_ion_optics/runs/20260814_155000__sim__simion__rf-oatof-single-flight-gap0__n1000__r04/run_manifest.json`<br>`2D09BC69D8B3EE1B146E0C6215030C85DF0ED4DB52865C7439A4456101E8E955`|`artifacts/projects/rf_octupole_ion_optics/runs/20260814_155000__sim__simion__rf-oatof-single-flight-gap0__n1000__r04/summary.json`<br>`91D751EEB1471D439CD9EC8397E6219C05958E35E734EF731EF36F2B8505777F`|

## 反射器电压与冻结关系

短、长架构没有误用对方的反射器工作电压。每个结构分别保存其联合一、二阶求解得到的工作点：

|结构|entgrid (V)|midgrid (V)|backplate (V)|Stage2理想场 (V/mm)|
|---|---:|---:|---:|---:|
|`ARCH-SHORT-Z10-R100`|0|1600.8967499896587|2487.292040697606|9.218275772964926|
|`ARCH-LONG-Z22-R100`|0|1603.6751257114397|2491.616961413765|9.234359430451514|

短焦10个Stage1环电压为
`145.536068181, 291.072136362, 436.608204543, 582.144272724, 727.680340904, 873.216409085,
1018.752477266, 1164.288545447, 1309.824613628, 1455.360681809 V`；5个Stage2环电压为
`1748.629298441, 1896.361846892, 2044.094395344, 2191.826943795, 2339.559492246 V`。

长焦10个Stage1环电压为
`145.788647792, 291.577295584, 437.365943376, 583.154591168, 728.943238960, 874.731886752,
1020.520534544, 1166.309182336, 1312.097830128, 1457.886477919 V`；5个Stage2环电压为
`1751.665431662, 1899.655737612, 2047.646043563, 2195.636349513, 2343.626655463 V`。

`midgrid/backplate`不是独立扫描轴。每套canonical finite-interval layout的理想源条件、加速器理论解与
耦合反射器方程构成一个不可拆分的派生链，电压只能由该链整体求得；短、长之间仍是各自联合匹配结构的
bundle，不能把电压差单独解释为焦距效应。在每个layout内部，1.0/2.2 mm实验以及
`ACC-RR/ACC-IR/ACC-RI/ACC-II`全部共享该layout理论派生的同一套`REFL-REAL-FORMAL025`几何和电压。

该权威不读取各field arm在反射器入口的实测粒子状态，也不读取检测器时间、FWHM或分辨率；禁止用入口
实测粒子、检测器结果或经验电压扫描反向调整`midgrid/backplate`。因此当前四臂效应包含加速场变化与
固定理论派生反射器的交互，但不是一次“逐臂重新匹配”实验。本轮曾讨论的反射器电压扫描已经取消，
没有新增campaign、run或统一33行表中的实验行。

## 后续治理顺序与条件性Arm8验证

PROVISIONAL report wrapper及八行声明式合同已经实现；这些报告不自称受治理receipt，也不签发
run/manifest。只有当解析报告与真实场配对差超过运行前声明的阈值，或研究
问题明确需要横向动力学、栅附近场、孔径损失或求解器步进证据时，才泛化并运行既有机器profile
`arm8_closed_global_piecewise_theoretical_field`。

若触发Arm8，必须先闭合当前短、长resolved结构及最大2.2 mm affine z–vz包络，并预声明配对改善、
焦面不变、宽度阶数和转向深度判据。旧campaign中的
`accelerator_ideal_stage1_stage2_ideal_reflectron`局部臂不允许用于本矩阵，其预留结果不可引用；本文
不据此声称机器profile本身已经删除或失效。`ACC-II + REFL-REAL-FORMAL025`到Arm8的差仍同时包含
`REFL-REAL-FORMAL025`、漂移残余场以及局部加速理想场与全域理论场边界的实现差异；若合同不能保持
这些边界同构，结论必须写成“真实PA/下游场实现bundle”，不能缩写为“纯反射器误差”。

## 资格边界

- 本文是Functional/diagnostic历史快照，不晋升Candidate或Formal。
- sigma比值与整数阶尺度接近不是阶数拟合；只有两个宽度，无法稳定分离二、三、四阶系数。
- resolved third derivative为`null`，不是零。
- 所有R和检测面时间统计继续使用`CLOCK-PULSE-EFFECTIVE`；absolute instrument time只用于调度和事件
  排序。
- 当前八行全理想解析数值尚无受治理run/manifest，只作强诊断；逐行发布闭合前不得晋级或写入正式
  结果矩阵。
- 若条件性触发Arm8正式泛化，必须先为短、长结构各自建立覆盖最大2.2 mm affine z-vz包络的
  解析/SIMION闭合；不得把旧zero-vz、旧布局closure冒充为当前四行的权威。

## 官方FLY2脉冲态六行控制（N1000）

### 唯一配置名称

本节禁止用“理想源”“理想场”“真实反射器”“短焦”或“长焦”单独标识一行。下表是六行控制的
唯一词汇；正文、结果表和artifact索引均使用同一注册名。机器ID只用于回查实现，不另立第二套显示名。

|类别|唯一注册名|机器ID或冻结定义|
|---|---|---|
|结构|`ARCH-SHORT-Z10-R100`|layout `theory_source_z10_d1_3`；generation `short_focus_1mm_theory_v1`|
|结构|`ARCH-LONG-Z22-R100`|layout `symmetric_10ev_source_z22_finite_interval_theory`；generation `finite_interval_2p2mm_matched_voltage_v1`|
|脉冲态源|`PSTATE-SHORT-1MM-AFFINE-N1000-SHA960547`|短焦、1.0 mm、pulse-effective affine z–vz；目标CSV SHA-256 `960547F7...C77F2`|
|脉冲态源|`PSTATE-SHORT-1MM-ZEROVZ-N1000-SHAE2E49C`|短焦、1.0 mm、pulse-effective真零vz；目标CSV SHA-256 `E2E49C3B...E3BE1`|
|脉冲态源|`PSTATE-LONG-1MM-AFFINE-N1000-SHA22ADAC`|长焦、1.0 mm contained-subinterval、pulse-effective affine z–vz；目标CSV SHA-256 `22ADAC66...0539`|
|脉冲态源|`PSTATE-LONG-1MM-ZEROVZ-N1000-SHAEA8E62`|长焦、1.0 mm contained-subinterval、pulse-effective真零vz；目标CSV SHA-256 `EA8E6294...19FB`|
|脉冲态源|`PSTATE-LONG-2P2MM-AFFINE-N1000-SHA75DF52`|长焦、2.2 mm matched interval、pulse-effective affine z–vz；目标CSV SHA-256 `75DF5222...3D4E`|
|脉冲态源|`PSTATE-LONG-2P2MM-ZEROVZ-N1000-SHA387DEF`|长焦、2.2 mm matched interval、pulse-effective真零vz；目标CSV SHA-256 `387DEF1C...989E`|
|栅网|`GRID-NATIVE-ONE-ROW`|四个SIMION官方原生一行零grid-unit厚透明栅；无teleport|
|加速场|`ACC-II`|profile `accelerator_ideal_stage1_stage2_real_reflectron`中的Stage1＋Stage2解析理想分段均匀加速场；profile ID尾部的`real_reflectron`不改变`ACC-II`只编码加速器两级的规则|
|反射场|`REFL-REAL-FORMAL025`|每个结构自己的真实SIMION PA反射器场；profile `oatof_formal_mesh`，轴向0.25 mm、径向1.0 mm|
|数值|`NUM-WHOLE-Z005-FORMAL025-Q8`|frontend 0.2 mm；accelerator overlay `accelerator_overlay_z005`、dz=0.05 mm；reflectron 0.25/1.0 mm；`tqual_8`|
|时钟|`CLOCK-PULSE-EFFECTIVE`|唯一分辨率口径：`t_detector-t_pulse,effective`|
|执行|`EXEC-SERIAL-BATCH3-MINMEM4G`|顶层commercial solver串行；N1000五批最多三批并发（3+2）；`single_flight_transport`系统可用内存门禁4 GiB；不改变物理或数值配置|

源profile `canonical_ideal_linear_z_vz_1mm_n1000`等描述生成族，不能代替上表的脉冲态源身份。尤其短、
长结构中的1.0 mm affine目标CSV具有不同global坐标和不同SHA，结果表不得把二者都简写成同一个
“1 mm ideal source”。六行共同使用`ACC-II + REFL-REAL-FORMAL025 + GRID-NATIVE-ONE-ROW +
NUM-WHOLE-Z005-FORMAL025-Q8 + CLOCK-PULSE-EFFECTIVE + EXEC-SERIAL-BATCH3-MINMEM4G`。

### 正式检测结果

campaign为`canonical_pulse_state_source_acc_ii_n1000`。六行均使用SIMION官方individual-particle FLY2
`velocity=vector(...)`、`pre_pulse_restart`和实际SIMION `source_release`逐行验收；有序IDs 1..1000、
位置/速度/时钟/实际速度派生能量分别以`1e-9 mm / 1e-6 m/s / 1e-9 us / 5e-9 eV`为门限，禁止
postselection。每行`source_release=PASS`，位置和时钟最大误差均为0；affine行速度/能量最大误差为
`3.53694304067176e-7 m/s / 1.61032254197835e-9 eV`，真零vz行分别为
`3.53692485077772e-7 m/s / 1.61031010748047e-9 eV`。

|脉冲态源|结构|到达检测器|平均TOF (µs)|sigma (ns)|direct FWHM (ns)|R|KDE modes|
|---|---|---:|---:|---:|---:|---:|---:|
|`PSTATE-SHORT-1MM-AFFINE-N1000-SHA960547`|`ARCH-SHORT-Z10-R100`|1000/1000|32.3011158522315|0.076702496121416|0.0894152264336867|180624.273877801|5|
|`PSTATE-SHORT-1MM-ZEROVZ-N1000-SHAE2E49C`|`ARCH-SHORT-Z10-R100`|1000/1000|32.3010863877152|0.596070284859800|1.98572637233241|8133.29534177336|2|
|`PSTATE-LONG-1MM-AFFINE-N1000-SHA22ADAC`|`ARCH-LONG-Z22-R100`|1000/1000|32.2301744214535|0.0778904324189579|0.0790194333788463|203938.282389667|5|
|`PSTATE-LONG-1MM-ZEROVZ-N1000-SHAEA8E62`|`ARCH-LONG-Z22-R100`|1000/1000|32.2301454270540|0.582935800494474|1.93895347366890|8311.20055272751|2|
|`PSTATE-LONG-2P2MM-AFFINE-N1000-SHA75DF52`|`ARCH-LONG-Z22-R100`|1000/1000|32.2300596789509|0.851702852099132|0.713201023813781|22595.6353545471|1|
|`PSTATE-LONG-2P2MM-ZEROVZ-N1000-SHA387DEF`|`ARCH-LONG-Z22-R100`|1000/1000|32.2300307103916|0.772289352583595|0.697181848934747|23114.5282503920|2|

所有R都是direct KDE mass FWHM；本控制campaign的bootstrap为0，因此`formal_gate_passed=false`。表中数据
是机器发布成功的Functional控制结果，不是5000-resample Formal qualification。多峰行的direct FWHM
只描述主峰半高宽，必须与sigma和mode一起阅读，不能按R单列排名。

### 焦平面与焦后演化

下表用同一canonical `compute_peak_metrics`处理各成功child manifest绑定的
`single_flight_particle_checkpoints.csv`中`accelerator_focus_forward`事件；这是确定性派生诊断，不是
另一个solver run或独立Formal receipt。

|脉冲态源|焦面平均TOF (µs)|焦面sigma (ns)|焦面direct FWHM (ns)|焦面R|焦面modes|检测面sigma/FWHM (ns)|
|---|---:|---:|---:|---:|---:|---:|
|`PSTATE-SHORT-1MM-AFFINE-N1000-SHA960547`|1.40395280460640|0.0197891307814687|0.0631570782916313|11114.8036629225|1|0.076702496121416 / 0.0894152264336867|
|`PSTATE-SHORT-1MM-ZEROVZ-N1000-SHAE2E49C`|1.40392334106270|0.656630926343538|2.26418951038121|310.052693255621|2|0.596070284859800 / 1.98572637233241|
|`PSTATE-LONG-1MM-AFFINE-N1000-SHA22ADAC`|1.35985765707370|0.0195383858512397|0.0517642678383723|13135.1546219728|2|0.0778904324189579 / 0.0790194333788463|
|`PSTATE-LONG-1MM-ZEROVZ-N1000-SHAEA8E62`|1.35982866967710|0.648008539826016|2.22089557764593|306.169565010811|1|0.582935800494474 / 1.93895347366890|
|`PSTATE-LONG-2P2MM-AFFINE-N1000-SHA75DF52`|1.35989806512210|0.0816781142366251|0.0765343074333735|8884.14331657004|3|0.851702852099132 / 0.713201023813781|
|`PSTATE-LONG-2P2MM-ZEROVZ-N1000-SHA387DEF`|1.35986944636640|1.37563543563089|4.64335756346590|146.453790481407|2|0.772289352583595 / 0.697181848934747|

1.0 mm affine两行在焦面已经形成约`0.0195–0.0198 ns`的窄sigma，而同结构真零vz焦面sigma约
`0.648–0.657 ns`，所以真零vz并未形成对应的一级时间聚焦。affine行从焦面到检测器sigma增宽到约
`0.077 ns`，反射器/焦后传播没有保留焦面全部窄度；但最终仍显著优于真零vz。真零vz两行从焦面到
检测器略收窄，说明下游存在补偿，但无法追回缺失的pulse-state z–vz关联。2.2 mm affine焦面sigma已增至
`0.0817 ns`且3 modes，到检测器sigma进一步增至`0.8517 ns`，显示有限宽区间的高阶残差与下游传播
共同主导。2.2 mm真零vz的direct FWHM从焦面到检测器大幅缩小，同时sigma仍为`0.7723 ns`且2 modes；
这是峰形重排，不应写成整个总体获得了与1.0 mm affine相同的时间聚焦。

因此本六行控制支持以下有限结论：在共同`ACC-II + REFL-REAL-FORMAL025`下，1.0 mm affine
pulse-state关联使R相对真零vz提高约22–25倍；短/长焦同源宽差异只有约13%，远小于源相空间关联效应。
把长焦源宽从1.0 mm扩大到2.2 mm后，affine R从`203938`降到`22596`，证明1.0 mm contained-subinterval
的最高分辨率不能外推到完整2.2 mm接受区。2.2 mm中affine与真零vz的direct R接近，且sigma/mode行为
不同；现有两种源不能据此唯一分离高阶加速场、固定真实反射器工作点与焦后传播的各自贡献。

### 成功证据与失败链

|脉冲态源|成功parent run|成功child manifest SHA-256|成功child summary SHA-256|
|---|---|---|---|
|`PSTATE-SHORT-1MM-AFFINE-N1000-SHA960547`|`20260814_165000__sim__cross__pulse-short1-affine-ii__n1000__r07`|`2501A16222A53F1E391B48FA042C19076B03A2E2B45EEBAB23ECF0283CAA0410`|`1DE134DC600C71E62C36EF746640B4D659077EDCCA66A704116A18E42BBC1CA4`|
|`PSTATE-SHORT-1MM-ZEROVZ-N1000-SHAE2E49C`|`20260814_165100__sim__cross__pulse-short1-zero-ii__n1000__r03`|`DD64948AD15F78D7D8BF3EF962C6128D2F5329886C76947CAF9DC0920549EE74`|`8C5CCE7C2C4913D924EB2B7D782F708DD76F7A38FC0684CC33C0A76646F3BC3F`|
|`PSTATE-LONG-1MM-AFFINE-N1000-SHA22ADAC`|`20260814_165200__sim__cross__pulse-long1-affine-ii__n1000__r03`|`DA5FCE38D1E910FF38918B5F193EAD758BB239A872B63D15DABB3993349AA9CB`|`69684D140140F04A60C09C28EE59E0CC02265BF5E922419BF3EA6EDC6641EBD3`|
|`PSTATE-LONG-1MM-ZEROVZ-N1000-SHAEA8E62`|`20260814_165300__sim__cross__pulse-long1-zero-ii__n1000__r03`|`403EA31442403B275BBE715FCD39B5DFC8C355FBE177B9C4368C1B3FEDFAD291`|`5C0004B7E8AA9B01A61DE0B12B9C2A2AB59EB6A8C1701923DE6F86FFC669A47F`|
|`PSTATE-LONG-2P2MM-AFFINE-N1000-SHA75DF52`|`20260814_165400__sim__cross__pulse-long2p2-affine-ii__n1000__r03`|`ABD7E2EF8C693B35084247D541CF808AE3BD28D68BDE8252531D1365A4465F94`|`6314A81894C256EBAC6759BF47CFAD00B8447435D1046E150988D6386DD43D53`|
|`PSTATE-LONG-2P2MM-ZEROVZ-N1000-SHA387DEF`|`20260814_165500__sim__cross__pulse-long2p2-zero-ii__n1000__r03`|`C126313B22C479004A2EF4B77D098E53DF6B58BC9BC8C62250D805BFEE8B90FC`|`15B0A8BF43D16FEC53A5DD420AC8AE3518A121FBB4C892DD73418F12DE983200`|

`r05/r06`的child solver与analysis曾成功，但parent发布失败，均不得当作正式行引用。根因不是物理或
SIMION：`prepare.py`冻结campaign时使用换行中性的`repository_text_sha256`，而`publish_run.py`曾用
字节级`file_sha256`复验；Windows CRLF使同一仓库文本得到不同身份。终态统一由
`repository_text_sha256`负责campaign文本身份，binary/artifact仍用`file_sha256`。CRLF/LF等价且不同
内容不等价的回归测试已通过；仓库没有适用于family-source parent发布的官方recovery入口，现有COMSOL
completed-solver recovery不适用，因此没有自建恢复旁路。`r07`是该源唯一正式成功行。

## ZERO-MATCH官方求解器与三行结果

为分离“真零vz源不匹配旧affine设计”与实际场误差，现有
`match_finite_phase_space_interval`原生接收`mean_vz=0`、`dvz/dz=0`，不新增公式或手抄电压权威。
两套唯一结构名为`ZERO-MATCH-SHORT-1MM`（profile `zero_match_short_1mm`、generation
`zero_match_short_1mm_v1`）和`ZERO-MATCH-LONG-2P2MM`（profile `zero_match_long_2p2mm`、generation
`zero_match_long_2p2mm_v1`）；后者同时承载1.0 mm contained-subinterval和完整2.2 mm源，因此没有
独立`LONG-1MM`结构求解。

ZERO-MATCH的反射场配置按理论解和结构分别注册，不能继续借用普通affine结构的
`REFL-REAL-FORMAL025`名称：

|类别|注册名|唯一显示名与定义|
|---|---|---|
|反射场|`REFL-REAL-ZERO-MATCH-SHORT-1MM-FORMAL025`|`ZERO-MATCH-SHORT-1MM`结构的真实SIMION `oatof_formal_mesh` PA反射场；`midgrid/backplate`只取该结构同一次ZERO-MATCH理论闭合派生的电压|
|反射场|`REFL-REAL-ZERO-MATCH-LONG-2P2MM-FORMAL025`|`ZERO-MATCH-LONG-2P2MM`结构的真实SIMION `oatof_formal_mesh` PA反射场；1.0 mm contained与2.2 mm full-width两行共享该结构同一次ZERO-MATCH理论闭合派生的电压|

两者只改变resolved理论电压身份，不新建反射器几何或经验调压轴；加速场仍统一注册为`ACC-II`。

求解器同一次输出负责repeller/grid1、三个整数网格对齐平面、焦面以及midgrid/backplate。反射器PA0
几何基底复用，运行时通过SIMION正式`r:fast_adjust(reflectron_voltages)`消费resolved
`electrodes_V`；`design_compilation.reflectron_voltage_application`记录`pa0_basis_reused=true`、
`official_simion_runtime_fast_adjust_v1`和`electrodes_V`单权威。回归测试同时闭合root electrodes、
`finite_interval_theory.coupled_reflectron`、`geometry_derivation.reflectron`能量包络和生成Lua，不重建
反射器几何。

独立PrepareOnly campaign为`canonical_zero_match_source_bootstrap_n1000`，只生成源，不授权solver或
分辨率声明。相同物理源继续使用相同source profile名；结构、场、网格、数值和时钟仍使用各自唯一配置名。

|脉冲态源准备身份|结构|宽度 (mm)|中心z (mm)|目标CSV SHA-256|receipt SHA-256|
|---|---|---:|---:|---|---|
|`PSTATE-ZERO-MATCH-SHORT-1MM-ZEROVZ-N1000-SHA5DA80C`|`ZERO-MATCH-SHORT-1MM`|1.0|-61.5412046249842|`5DA80C61C214676BA0B59BBAF9220D3DF954F137419DE3951245B25620E10E73`|`4C48811AB1D4994CD554BE7C6838D9A7501BE7C6EFD1F633153B702169CD6F82`|
|`PSTATE-ZERO-MATCH-LONG-1MM-ZEROVZ-N1000-SHAE89709`|`ZERO-MATCH-LONG-2P2MM`|1.0|-59.5476440793136|`E897097FBF32782DD4CEB913D4803C333BC584D34B4BE47A3B905E3780BA29D2`|`EFFD2A1ED43DAC00508BEE8EB14D85C76628D6AF6CAD576AF0A893C90703E4D7`|
|`PSTATE-ZERO-MATCH-LONG-2P2MM-ZEROVZ-N1000-SHA0AFDA7`|`ZERO-MATCH-LONG-2P2MM`|2.2|-59.5476440793136|`0AFDA722235AA0AB4383193C8FFB231499A2F60FEC9C20BB557268C536507B8C`|`13177ECEA524E7F6CA31E0BF42A8029B5DDE57C7837F967D7E9F44E2D7EAFF54`|

三行pulse-effective时间均为`45.4167939656417 us`且N=1000。正式solver campaign为
`canonical_zero_match_acc_ii_n1000`；顶层严格串行，各行内部五批最多三批并发，4 GiB可用内存门禁和
4 h hard timeout保持不变。三行均由实际SIMION `source_release`逐行验收后才接受并启动下一行：位置和
时钟最大误差均为0，速度与实际速度派生能量最大误差均为
`3.536924850777723e-7 m/s / 1.6103101074804727e-9 eV`，检测器均为1000/1000。

|脉冲态源|结构|检测器|平均TOF (µs)|sigma (ns)|direct FWHM (ns)|R|KDE modes|
|---|---|---:|---:|---:|---:|---:|---:|
|`PSTATE-ZERO-MATCH-SHORT-1MM-ZEROVZ-N1000-SHA5DA80C`|`ZERO-MATCH-SHORT-1MM`|1000/1000|32.1900878653503|0.07681153384431534|0.07932223689266493|202907.1689376217|3|
|`PSTATE-ZERO-MATCH-LONG-1MM-ZEROVZ-N1000-SHAE89709`|`ZERO-MATCH-LONG-2P2MM`|1000/1000|32.1340952963443|0.07815522183833873|0.07276583324511421|220804.91383808578|3|
|`PSTATE-ZERO-MATCH-LONG-2P2MM-ZEROVZ-N1000-SHA0AFDA7`|`ZERO-MATCH-LONG-2P2MM`|1000/1000|32.133981327295395|0.8514291390090949|0.7125762642559152|22548.02787260909|1|

|行|成功parent run|child manifest SHA-256|child summary SHA-256|
|---|---|---|---|
|short 1.0 mm|`20260814_175000__sim__cross__zero-match-short1-ii__n1000`|`7B65AA26876BB30441079DD8A9CA961CF46F3E27725FA4A8E571C62493B24F0F`|`21BECEF56C57B531809705C46FC5CD4C6D1D871D0DE08A99EA6507821CEAFA1C`|
|long contained 1.0 mm|`20260814_175100__sim__cross__zero-match-long1-ii__n1000`|`EED6440622B673BD71AE8D4A9C993C17A2555F7EAE240CDE609C8997D8B65012`|`D7E7E785357C45BFC2BD0197774001D0BCD4A13D87036895D4B63ED659F74583`|
|long full 2.2 mm|`20260814_175200__sim__cross__zero-match-long2p2-ii__n1000`|`0385D3D9303FE1C003588786359BCE09E0362866546EC84774D0E2ED309DC183`|`ABED1EB63735D516D71582C0D1E4DD751EFCA6B26DBB1276F078FB885AC1D80A`|

与旧结构上的真零vz控制相比，重新匹配0/0源条件使1.0 mm short的R从`8133`升到`202907`，long
contained从`8311`升到`220805`，恢复到对应affine旧设计的约`180624/203938`量级。这证明此前1.0 mm
真零vz低分辨率主要是“源相空间条件与加速器设计不匹配”，不是透明栅数值边界层导致的普遍上限。
完整2.2 mm源即使使用自己的ZERO-MATCH long设计，R仍为`22548`，与旧long 2.2 mm affine/zero的
`22596/23115`接近；其sigma约`0.851 ns`，说明完整接受宽度的高阶残差仍是主要限制。三行bootstrap为0，
故`formal_gate_passed=false`；这些是机器发布成功的Functional控制结果，不是5000-resample Formal资格结论。

## 统一实验总表与证据结论

下表把本轮三组机器证据压到同一列语义。加速场逐行使用`ACC-RR/IR/RI/II`完整注册名，其中两个字母
只表示Stage1/Stage2使用Real PA场或解析Ideal场；反射器始终单独列出，避免把`ACC-II`误读成全仪器
理想场。`N/cohort`为实际用于峰指标的人数：规范affine
和pulse-state/zero-match为完整N1000；real-oct为各field cell预声明的峰cohort，因此Stage1为Real时是
695、为Ideal时是706。所有FWHM和R均为pulse-effective direct KDE主峰口径；多峰行必须同时阅读modes。

|Panel|source|source–design relation|architecture|grid|accelerator field|reflectron field|numerics|clock|N/cohort|FWHM (ns)|R|modes|evidence status|
|---|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---|
|24格/affine|`SRC-CANON-IDEAL-LINEAR-ZVZ-1MM-N1000-SHA0E900A`|short 1 mm matched|`ARCH-SHORT-Z10-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-RR`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.208361907|77511.380|2|published Functional screen|
|24格/affine|同上|long 2.2设计内的1 mm contained|`ARCH-LONG-Z22-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-RR`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.178164547|90449.726|2|published Functional screen|
|24格/affine|同上|short 1 mm matched|`ARCH-SHORT-Z10-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-IR`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.168449517|95876.826|1|published Functional screen|
|24格/affine|同上|long 2.2设计内的1 mm contained|`ARCH-LONG-Z22-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-IR`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.168216346|95798.840|1|published Functional screen|
|24格/affine|同上|short 1 mm matched|`ARCH-SHORT-Z10-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-RI`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.058362220|276730.461|1|published Functional screen|
|24格/affine|同上|long 2.2设计内的1 mm contained|`ARCH-LONG-Z22-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-RI`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.060519476|266280.058|1|published Functional screen|
|24格/affine|同上|short 1 mm matched|`ARCH-SHORT-Z10-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-II`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.091324733|176847.621|3|published Functional screen|
|24格/affine|同上|long 2.2设计内的1 mm contained|`ARCH-LONG-Z22-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-II`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.082319474|195762.801|4|published Functional screen|
|24格/affine|`SRC-CANON-IDEAL-LINEAR-ZVZ-2P2MM-N1000-SHADE5A76`|over-width vs short 1 mm design|`ARCH-SHORT-Z10-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-RR`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.896141732|18022.348|1|published Functional screen|
|24格/affine|同上|long 2.2 mm matched|`ARCH-LONG-Z22-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-RR`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.930615839|17316.618|1|published Functional screen|
|24格/affine|同上|over-width vs short 1 mm design|`ARCH-SHORT-Z10-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-IR`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.920858414|17538.576|1|published Functional screen|
|24格/affine|同上|long 2.2 mm matched|`ARCH-LONG-Z22-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-IR`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.936484971|17208.054|1|published Functional screen|
|24格/affine|同上|over-width vs short 1 mm design|`ARCH-SHORT-Z10-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-RI`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.732687179|22043.200|1|published Functional screen|
|24格/affine|同上|long 2.2 mm matched|`ARCH-LONG-Z22-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-RI`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.750478211|21473.398|1|published Functional screen|
|24格/affine|同上|over-width vs short 1 mm design|`ARCH-SHORT-Z10-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-II`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.745340145|21668.893|1|published Functional screen|
|24格/affine|同上|long 2.2 mm matched|`ARCH-LONG-Z22-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-II`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.761926936|21150.666|1|published Functional screen|
|24格/real-oct|`SRC-REAL-OCT-SHA302C`|measured beam; not affine-matched|`ARCH-SHORT-Z10-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-RR`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|695|1.920194588|8410.717|2|published Functional; declared peak cohort|
|24格/real-oct|同上|measured beam; not affine-matched|`ARCH-LONG-Z22-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-RR`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|695|1.902421940|8470.653|1|published Functional; declared peak cohort|
|24格/real-oct|同上|measured beam; not affine-matched|`ARCH-SHORT-Z10-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-IR`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|706|2.030656684|7953.200|1|published Functional; declared peak cohort|
|24格/real-oct|同上|measured beam; not affine-matched|`ARCH-LONG-Z22-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-IR`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|706|2.003488284|8043.348|1|published Functional; declared peak cohort|
|24格/real-oct|同上|measured beam; not affine-matched|`ARCH-SHORT-Z10-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-RI`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|695|1.803288117|8956.145|1|published Functional; declared peak cohort|
|24格/real-oct|同上|measured beam; not affine-matched|`ARCH-LONG-Z22-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-RI`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|695|1.784378062|9031.177|1|published Functional; declared peak cohort|
|24格/real-oct|同上|measured beam; not affine-matched|`ARCH-SHORT-Z10-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-II`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|706|1.887925686|8554.610|1|published Functional; declared peak cohort|
|24格/real-oct|同上|measured beam; not affine-matched|`ARCH-LONG-Z22-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-II`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|706|1.870324061|8616.160|1|published Functional; declared peak cohort|
|pulse ablation|`PSTATE-SHORT-1MM-AFFINE-N1000-SHA960547`|matched affine pulse state|`ARCH-SHORT-Z10-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-II`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.089415226|180624.274|5|published Functional; source_release PASS|
|pulse ablation|`PSTATE-SHORT-1MM-ZEROVZ-N1000-SHAE2E49C`|0/0 source on affine-matched design|`ARCH-SHORT-Z10-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-II`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|1.985726372|8133.295|2|published Functional; source_release PASS|
|pulse ablation|`PSTATE-LONG-1MM-AFFINE-N1000-SHA22ADAC`|contained affine pulse state|`ARCH-LONG-Z22-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-II`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.079019433|203938.282|5|published Functional; source_release PASS|
|pulse ablation|`PSTATE-LONG-1MM-ZEROVZ-N1000-SHAEA8E62`|0/0 source on affine-matched design|`ARCH-LONG-Z22-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-II`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|1.938953474|8311.201|2|published Functional; source_release PASS|
|pulse ablation|`PSTATE-LONG-2P2MM-AFFINE-N1000-SHA75DF52`|full-width affine matched|`ARCH-LONG-Z22-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-II`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.713201024|22595.635|1|published Functional; source_release PASS|
|pulse ablation|`PSTATE-LONG-2P2MM-ZEROVZ-N1000-SHA387DEF`|0/0 source on affine-matched design|`ARCH-LONG-Z22-R100`|`GRID-NATIVE-ONE-ROW`|`ACC-II`|`REFL-REAL-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.697181849|23114.528|2|published Functional; source_release PASS|
|ZERO-MATCH|`PSTATE-ZERO-MATCH-SHORT-1MM-ZEROVZ-N1000-SHA5DA80C`|0/0 source matched by solver|`ZERO-MATCH-SHORT-1MM`|`GRID-NATIVE-ONE-ROW`|`ACC-II`|`REFL-REAL-ZERO-MATCH-SHORT-1MM-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.079322237|202907.169|3|published Functional; source_release PASS|
|ZERO-MATCH|`PSTATE-ZERO-MATCH-LONG-1MM-ZEROVZ-N1000-SHAE89709`|1 mm contained in 0/0 long design|`ZERO-MATCH-LONG-2P2MM`|`GRID-NATIVE-ONE-ROW`|`ACC-II`|`REFL-REAL-ZERO-MATCH-LONG-2P2MM-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.072765833|220804.914|3|published Functional; source_release PASS|
|ZERO-MATCH|`PSTATE-ZERO-MATCH-LONG-2P2MM-ZEROVZ-N1000-SHA0AFDA7`|full-width 0/0 matched|`ZERO-MATCH-LONG-2P2MM`|`GRID-NATIVE-ONE-ROW`|`ACC-II`|`REFL-REAL-ZERO-MATCH-LONG-2P2MM-FORMAL025`|`NUM-WHOLE-Z005-FORMAL025-Q8`|`CLOCK-PULSE-EFFECTIVE`|1000|0.712576264|22548.028|1|published Functional; source_release PASS|

### 33行统一表的派生受控交互分析

本节不增加原始实验行。它只对统一表中规范1.0 mm affine源的短/长`ACC-RR/IR/RI/II`八行作同一
IDs 1..1000的派生受控分析。时间均值效应沿用既有`effect_vectors`尺度：主效应为平均high-minus-low，
interaction为完整差中之差的一半；FWHM按`VALIDATION_METHODS`使用完整差中之差
`FWHM_II+FWHM_RR-FWHM_IR-FWHM_RI`，不除以2。所有值都是确定性描述，不含bootstrap。

|结构|检查面|Stage1 mean effect (ns)|Stage2 mean effect (ns)|mean interaction (ns，半DID)|
|---|---|---:|---:|---:|
|短焦|`accelerator_focus_forward`|-0.054576032500|0.333978354400|-0.012050161300|
|短焦|`reflectron_entrance_forward`|-1.763575238350|0.504584585250|-0.060232764050|
|短焦|`detector_crossing`|-0.052033325050|0.333746940250|-0.012006205650|
|长焦|`accelerator_focus_forward`|-0.043525938300|0.338970500500|-0.013386252300|
|长焦|`reflectron_entrance_forward`|-1.737363783100|0.551365958400|-0.067069425300|
|长焦|`detector_crossing`|-0.040859689450|0.338626199850|-0.013294851850|

从反射器入口到检测面的mean interaction增量，短焦为`+0.048226558400 ns`，长焦为
`+0.053774573450 ns`。这说明固定downstream/真实反射器bundle改变了加速器四臂入口束团的非加性时间
关系；它不是“反射器电压失配”的单变量估计。

|结构与检查面|RR FWHM/modes|IR FWHM/modes|RI FWHM/modes|II FWHM/modes|Stage1 FWHM main (ns)|Stage2 FWHM main (ns)|完整FWHM DID (ns)|
|---|---:|---:|---:|---:|---:|---:|---:|
|短焦入口|253.563312324 / 1|253.212555431 / 1|253.729089458 / 1|253.423056162 / 1|-0.328395095|+0.188138933|+0.044723597|
|短焦检测面|0.208361907 / 2|0.168449517 / 1|0.058362220 / 1|0.091324733 / 3|-0.003474939|-0.113562236|+0.072874903|
|长焦入口|257.657433637 / 1|257.372610210 / 1|257.893588319 / 1|257.572111606 / 1|-0.303150070|+0.217828039|-0.036653286|
|长焦检测面|0.178164547 / 2|0.168216346 / 1|0.060519476 / 1|0.082319474 / 4|+0.005925899|-0.101770972|+0.031748199|

完整FWHM DID从入口到检测面的变化为短焦`+0.028151305848 ns`、长焦`+0.068401485201 ns`；长焦
由`-0.036653285939 ns`翻转为`+0.031748199262 ns`。检测面Stage2理想化的FWHM主效应为
`-0.113562236/-0.101770972 ns`，绝对量明显大于Stage1的`-0.003474939/+0.005925899 ns`，所以在
规范1 mm affine源上，Stage2仍是主要直接改善方向。RR和II检测峰分别出现2模及3/4模，故较小FWHM
不能脱离modes解释成整体峰形改善。

|派生分析|run id|summary SHA-256|manifest SHA-256|
|---|---|---|---|
|短焦mean interaction|`20260814_153000__analysis__cross__short-affine-stage-field-2x2-n1000__r02`|`357D1F924B8146B9679EC35567C1143E5413F486DDA53EC1F49903E12A4406C9`|`D6366A38D85F80DF22E8162F747B3B1A5552A233C570CD9A7619DD37F9E99D7F`|
|长焦mean interaction|`20260814_153100__analysis__cross__long-affine-stage-field-2x2-n1000__r02`|`1D166EEE123745E1153126791A8C58BCD8C3ED32FF94A2F6B460FA7DA567FBF5`|`E85D552B7AEC30847744E9E9BBC2D9C3585C6B61F5DCDAD2343A1F849F1B2CB6`|
|短焦checkpoint FWHM|`20260814_163500__analysis__cross__short-checkpoint-fwhm-2x2-republish-n1000`|`6B1D8BCD2F2CD1B5FACB1DAC52FA2240692E757B0EAC5696AE15B9F2D6E684A8`|`F9FC578C0F171221C182EE5E4F2F4EB0BF935481FF1FA53907BD54D56D93E1B0`|
|长焦checkpoint FWHM|`20260814_163600__analysis__cross__long-checkpoint-fwhm-2x2-republish-n1000`|`EA474C8C614F3E4B065BF809A65E6A7BCC1C48BC3EF1796E37EDB6D92B4124BD`|`B73CD4F1B47167A85EA6E0010D14E76C8D62B94F4D21BAD305AA2D0D51DBD6F6`|

强结论限定如下：downstream bundle确实改变非加性FWHM interaction，且长焦发生符号翻转；Stage2
理想化仍是规范1 mm源的主要直接FWHM改善。现有真实场输出没有受支持的detector-blind一、二阶导数
识别入口，因而不能把该交互进一步归因成纯反射器电压失配。多模、无bootstrap和无数值收敛共同禁止
统计显著性、普适性、Formal资格及单组件误差百分比声明。

### 仅由控制变量证据支持的强结论

1. **证实：1.0 mm源–设计匹配是约20万分辨率的必要控制量。** 同一0/0 pulse-state在旧affine设计上
   只有`R=8133/8311`，经现有官方solver为0/0条件重新匹配后达到`R=202907/220805`；三行均使用同一
   native grid方法并通过actual source-release验收。因而“1 mm真零vz天然只能达到约8k”被否定。
2. **否定：透明栅数值边界层构成当前所有工况约8k的普遍分辨率上限。** ZERO-MATCH在未更换
   `GRID-NATIVE-ONE-ROW`的情况下达到约20万。该证据否定“普遍上限”，但不证明栅附近误差严格为零。
3. **证实：完整2.2 mm接受宽度的损失在当前设计族中稳定存在。** 2.2 mm affine的四个field cell仅
   `R=17.2k–22.0k`；全宽0/0经专门匹配后仍为`R=22.55k`，而同一long设计内1 mm contained达到
   `R=220.8k`。因此1 mm contained结果不能外推到完整2.2 mm接受区。
4. **证实：Stage2理想化是real-oct与规范1 mm affine源共同指向的主要直接改善方向，且短/长结构不是
   数量级差异来源。**
   严格配对析因中，Stage2 `R→I`使FWHM平均减少约`0.121–0.125 ns`，Stage1 `R→I`反而增加约
   `0.069–0.074 ns`；规范1 mm affine源的检测面Stage2 FWHM主效应为
   `-0.113562236/-0.101770972 ns`，Stage1仅为`-0.003474939/+0.005925899 ns`。同一field cell的
   短/长R差小于约1.2%。这只是在当前冻结真实反射器工作点上的组合效应，不等于Stage2几何已被单独优化。
5. **证实：固定downstream/真实反射器bundle改变非加性FWHM interaction，长焦发生符号翻转。** 短焦
   完整DID由入口`+0.044723597 ns`变为检测面`+0.072874903 ns`；长焦由`-0.036653286 ns`变为
   `+0.031748199 ns`。该证据不能拆成纯电压失配；多模、无bootstrap和无数值收敛禁止统计或Formal外推。
6. **证实：real-oct束的展宽远大于规范1 mm affine源，但当前24格不是严格的纯source配对。** real-oct
   各cell为`R≈8.0k–9.0k`，规范1 mm affine为`R≈77.5k–276.7k`；然而real-oct的峰cohort随Stage1模式
   为695/706，故可以确认结果关联和工程优先级，不能把全部差值唯一归为某一个源相空间矩。
7. **未能归因：真实场bundle相对理想解析场的剩余差，不能在现有证据中拆成“PA真实场形”与“grid
   离散误差”。** 本轮没有在同一冻结粒子、同一电势函数下做独立网格收敛序列；真实反射器、有限环、
   孔径边缘、栅附近场形和离轴运动仍共同变化。因此只能否定grid是普遍上限，不能给出grid误差百分比。
8. **未能归因：2.2 mm损失的三阶、四阶及反射器份额尚未唯一分离。** 宽度缩放和全理想解析诊断支持
   “高阶有限区间残差”解释，但现有求解器没有声明三阶导数，且ZERO-MATCH同时更新加速器与耦合反射
   电压；不得把全部损失单独写成Stage1、Stage2、反射器或某一阶像差。

以上所有行均为`formal_gate_passed=false`的published Functional证据；表中“证实/否定”只在对应控制
范围内成立，不升级为Formal qualification。

## 非法analysis根合规重发布映射

早期六个分析目录直接位于项目`analysis/`根，不满足当前`runs/<run_id>`、schema-v2 retention、公共
manifest writer和独立verify合同。它们的证据已按原冻结输入合规重发布到三个`activity=analysis、
scope=cross`的v2 compact run。该操作只迁移和复核既有证据，不是新实验、不增加统一33行实验表的行，
也不产生新的物理或数值结论。

|旧analysis根目录|后续权威run|映射状态|
|---|---|---|
|`20260813_215500__analysis__cross__rr-canonical-clock-n1000`|A：`20260814_155700__analysis__cross__rr-canonical-clock-republish-n1000`|canonical checkpoint与receipt逐字节相同|
|`20260813_215500__analysis__rr-canonical-clock__n1000`|A：同上|旧重复目录由A统一取代|
|`20260813_220000__analysis__stage-field-2x2-canonical__n1000`|B：`20260814_155800__analysis__cross__legacy-stage-field-2x2-republish-n1000`|数值字段相等，两张CSV逐字节相同|
|`20260813_215000__analysis__stage-field-2x2__n1000`|B：同上|早期结果由B的新证据取代，不再作为解释权威|
|`20260813_220000__analysis__cross__stage-field-2x2-n1000`|B：同上|cross副本由B的新证据取代，不再作为解释权威|
|`20260813_224000__analysis__cross__rr-accelerator-dz-convergence-n1000`|C：`20260814_155900__analysis__cross__rr-accelerator-dz-republish-n1000`|数值字段相等，两张CSV逐字节相同|

### A：canonical clock重发布

|文件|字节|SHA-256|
|---|---:|---|
|`run_manifest.json`|4,071|`E42BECB214751C85AE2F0B1D03E5C395A3B5EB02E5675A74B41150577CF9F053`|
|`summary.json`|480|`5F5E618E57EE877894C3A6CAD6C749CA5E4CE66DA2ECBF8278CFCEB409CC67B8`|
|`rr_canonical_checkpoints.csv`|1,792,129|`FCB931C9E67C268CBA038CAE9D37D057FD593108949FD7317EBF8A654D233612`|
|`rr_canonical_clock_receipt.json`|666|`E4B73DB769CC3F9F552401F3BFB8D5660BE8243C35EB89D47F52F377FE33A270`|

A的checkpoint和receipt与旧`215500 cross`目录对应文件字节数、SHA-256均相同；这里没有重新计算
粒子时钟或更改CSV。

### B：legacy stage-field 2×2重发布

|文件|字节|SHA-256|
|---|---:|---|
|`run_manifest.json`|7,345|`28968F9ED012F5B63083AA6CF8419AAA756F80F83629100BA69E07372DC91A47`|
|`summary.json`|1,038|`A9DC57309D32DFCEA47F2C1E0109B0F73830AFC7FB1D40004BB02E2ED4B218A5`|
|`stage_field_2x2_attribution.json`|27,439|`3E91D4023E43B00B844697DD542C762EB94A2017DAC3A68AAB55A7248A2473FB`|
|`checkpoint_arm_statistics.csv`|2,553|`E193F23B257CFC5C0C8C669E0C8EA75B1319A396FAFBCB80BCC311CCC4449C03`|
|`checkpoint_paired_deltas.csv`|3,497|`C3294BD4321A11DAAABB1E531A2175C337461BF9F4A6B315FDC38C452630956E`|
|`stage_field_2x2_diagnostics.png`|168,462|`E2B15CC81EE652A2ABF76F2FA7AF3CE3014872359289777A5D1E91C754523723`|

B逐字段复核`paired_particle_count`、有序ID SHA、factor coding、首个非零事件、全部checkpoint
effects、detector peak metrics和bootstrap均与旧canonical结果相等；两张CSV逐字节相同。JSON因合规
来源绑定和当前输出结构而不要求整文件字节相同，数值等价声明只限上述已审计字段。

### C：accelerator dz重发布

|文件|字节|SHA-256|
|---|---:|---|
|`run_manifest.json`|6,888|`25CCC6CFBDA7F9B8F0015507F874F28C53CF25E90A04E5A119810852F5389ADF`|
|`summary.json`|1,225|`22C3E5480B2F7582A1F56423264BEFD50AFE4A492B42829FDB4655C60E7A77B5`|
|`accelerator_dz_convergence.json`|5,473|`D0BE83170819B5D77F69E151128D6C86C9148D950CD31D7002CC5FB0E542898A`|
|`checkpoint_paired_convergence.csv`|1,374|`07B058563E5134231DD8120DE1EE36AF908BA8908B717A481175C02F34CA265A`|
|`checkpoint_arm_spreads.csv`|1,134|`1A6B4EDD4D8E6F49EC48683A4E5C2C9C003205AD0E9FB5B98EFD2BEB9A0ECEC2`|
|`accelerator_dz_convergence.png`|215,126|`24EB9068251E540D5D0E4C32EB0063C23036363760A54A4A52C694C1E2FE7CDA`|

C逐字段复核paired count、有序ID、identity gate、checkpoint统计、focus decision、detector metrics、
判据与置信区间均相等；两张CSV逐字节相同。原结论保持为焦面mean差
`0.00108932160002587 ns`、paired sigma `0.0399346146469428 ns`、primary decision `false`。

已冻结的
[`原生栅网、源/场、数值与短长焦全过程`](20260814__oatof-native-grid-field-source-focus-investigation.md)
和
[`源、场与结构配置注册表及结果矩阵`](20260814__oatof-source-field-configuration-registry-and-results-matrix.md)
不回写旧路径；从本节发布后，凡解释其中canonical clock、legacy stage-field或dz证据，均以上述A/B/C
映射及其v2 manifest为准。旧六目录可以在映射、SHA和文档门禁复核后删除，不再承担唯一证据职责。

## 后续正式successor与当前证据绑定

在上节A/B/C重发布后，剩余旧schema、非完整输出绑定和prepare-only campaign身份也已用正式
schema-v2 run收口。以下操作全部复用冻结输入或既有输出，只补齐manifest、精确output path/bytes/SHA、
下游v2 campaign或失败关闭receipt；没有重新运行SIMION，没有新增统一33行实验表中的科学行，全部
粒子数、FWHM、R、峰模态和控制变量结论保持不变。

|旧run|当前权威successor|等价或失败关闭边界|
|---|---|---|
|`20260814_003500__analysis__cross__oct-whole-short-long-postselection__n1000`|`20260814_184000__analysis__cross__oct-whole-short-long-republish__n1000`|同一695粒子短/长postselection比较；只重发正式manifest和输出绑定|
|`20260814_030000__analysis__python__rr-tqual8-vs108-paired-n100__r03`|`20260814_184100__analysis__python__rr-tqual8-vs108-republish__n100`|同一N=100 q8/q108配对判据；仍为paired sigma FAIL、非Formal|
|`20260814_174000__analysis__cross__zero-match-short1-source__n1000`|`20260814_184200__analysis__cross__zero-match-short1-source-v2__n1000`|source三件套逐字节相同；改用下游v2 prepare-only campaign|
|`20260814_174100__analysis__cross__zero-match-long1-source__n1000`|`20260814_184300__analysis__cross__zero-match-long1-source-v2__n1000`|source三件套逐字节相同；改用下游v2 prepare-only campaign|
|`20260814_174200__analysis__cross__zero-match-long2p2-source__n1000`|`20260814_184400__analysis__cross__zero-match-long2p2-source-v2__n1000`|source三件套逐字节相同；改用下游v2 prepare-only campaign|
|`20260814_160000__analysis__cross__short-checkpoint-fwhm-2x2-n1000`|`20260814_163500__analysis__cross__short-checkpoint-fwhm-2x2-republish-n1000`|原公式与全部数值字段等价；精确输出绑定失败关闭|
|`20260814_160100__analysis__cross__long-checkpoint-fwhm-2x2-n1000`|`20260814_163600__analysis__cross__long-checkpoint-fwhm-2x2-republish-n1000`|原公式与全部数值字段等价；精确输出绑定失败关闭|
|`20260814_155800__analysis__cross__legacy-stage-field-2x2-republish-n1000`|`20260814_164400__analysis__cross__legacy-stage-field-2x2-fail-closed-republish-n1000`|在B的数值等价基础上补齐RR receipt和精确output path/bytes/SHA失败关闭|
|`20260813_151500__analysis__python__axial-ideal-arm8-closure`|`20260814_165300__analysis__python__axial-ideal-arm8-closure-republish`|解析closure receipt逐字节相同并独立科学重算等价；当前campaign仅绑定revision 2 successor，旧路径只留在`supersedes`|
|`scratch/r03-winner-post-selection`|`20260814_185300__analysis__python__r03-winner-postselection-republish__n1000`|四份科学文件逐字节相同；source solver run仍为failed，本successor只发布成功的detector-blind reanalysis/postselection证据|

当前successor的终态证据为：

|run|summary SHA-256|manifest SHA-256|
|---|---|---|
|`20260814_163500__analysis__cross__short-checkpoint-fwhm-2x2-republish-n1000`|`6B1D8BCD2F2CD1B5FACB1DAC52FA2240692E757B0EAC5696AE15B9F2D6E684A8`|`F9FC578C0F171221C182EE5E4F2F4EB0BF935481FF1FA53907BD54D56D93E1B0`|
|`20260814_163600__analysis__cross__long-checkpoint-fwhm-2x2-republish-n1000`|`EA474C8C614F3E4B065BF809A65E6A7BCC1C48BC3EF1796E37EDB6D92B4124BD`|`B73CD4F1B47167A85EA6E0010D14E76C8D62B94F4D21BAD305AA2D0D51DBD6F6`|
|`20260814_164400__analysis__cross__legacy-stage-field-2x2-fail-closed-republish-n1000`|`45663498BA37346BA890794FF6945E66119DF5658A0ACA3AFDBF8E61279B76C6`|`38C1A7484277F46E1F9F674B2895E2ACD71B26389F7D99BC43C10FF29B927C0C`|
|`20260814_184000__analysis__cross__oct-whole-short-long-republish__n1000`|`07DE442FEB7D3F59ECED7B0C2A9BFCD47100690150465B5D61581AE484F95A8C`|`1E7AF674D0267803881F911BD87BA71C2628B4551C14AC3763DE335D3F09679C`|
|`20260814_184100__analysis__python__rr-tqual8-vs108-republish__n100`|`5A12A6D89CA510F188934CB1B78D2500ECEBB26E9F37EB0F9D1D121847C7A5F3`|`FF6559E4CA816CCFB8BF3B5EAE938A2C05FFDB14A49F6306F314784874E078D7`|
|`20260814_184200__analysis__cross__zero-match-short1-source-v2__n1000`|`AA1411FDBDB33418E84F590B14F30777E0C3C219BFE5F968AED88ABE4AA595A4`|`C8104BEE04E706B373075F614485B1A489190996056425ABB8B83FEAA2C967AF`|
|`20260814_184300__analysis__cross__zero-match-long1-source-v2__n1000`|`1684AE1D576267D8C90F34C8A17AB9675585F3FD19B074A21A06B2909E555550`|`27D2E0377130A503D64231B97199B9D1279BE07BE7C8B08E1FA57359E88DD235`|
|`20260814_184400__analysis__cross__zero-match-long2p2-source-v2__n1000`|`7C279B858FE1E2E3065103863F6174DD55BB5F7F293EC4B17CEF6AA6BE0CD7D4`|`DD08A02BDE759706532F751E47FF7D711C2ECC387B0684FBD51A2760780EA4B7`|
|`20260814_165300__analysis__python__axial-ideal-arm8-closure-republish`|`C78678B316A61B81FD310F643B2BE95FCCC138BCFE28A5ED5372AC13A93F629F`|`53226503784609AA06DC0D0045B9C6A539D86DA8A4487E10CA745BDCD996121E`|
|`20260814_185300__analysis__python__r03-winner-postselection-republish__n1000`|`140E37D57D1EDA3DFBB2897DBF46C4BF50FB3D4BDE7F99C090373157607BDE95`|`4CC2C4DD1874E53E7757E91B44F5F0A74F479F14AEC65646C746226BE4AB8E93`|

ZERO-MATCH三份successor分别冻结`materialized source / pulse target state / materialization receipt`三件套；
其目标态SHA仍为`5DA80C...E10E73`、`E89709...29D2`、`0AFDA7...07B8C`，receipt仍为
`4C4881...6F82`、`EFFD2A...E4D7`、`13177E...EAFF54`。三件套与各自旧run逐字节相同，v2只改变
campaign和证据生命周期身份，不授权新的solver结果或分辨率声明。

Arm8解析closure successor中的`8,459-byte` receipt与旧`151500` receipt逐字节相同，SHA-256均为
`9AA2773255B4DC83F3208B7620DDAA8423C4F6B78650E156F75847424D6D883B`。当前campaign把该证据作为
`evidence_revision=2`的唯一权威，并在`supersedes`中保留旧路径和同一SHA；这不建立双重权威，也未
重跑SIMION。r03 winner successor的`checkpoints.csv`、`summary.json`、
`winner_detector_peak_metadata.json`和`winner_detector_peak.png`与旧scratch逐字节相同，SHA-256依次为
`8B746358A36D0D4F16EF7FAE0F198C4918E790D3EBB0E4049F9A8961072FE605`、
`4346C49CF27D7844C2121A9062E2D54454D31F7C2483D872E008F591C2F4D900`、
`ECF34C7D2550A36E8B8F05F207EEFF871FE48831BC06BCED915AD7629FF5EC5D`和
`627CC56F658AD0EA16A964BE2EEA5765A11F06D6D60801FF7EE899D95D9C56A1`；它不改变原科学结果或Formal边界。

## 2.2 mm高阶假设的分层证据

本节统一使用`SRC-IDEAL-ZERO-VZ`、`ARCH-LONG-Z22-R100`、`ACC-II`、
`REFL-REAL-FORMAL025`、`CLOCK-PULSE-EFFECTIVE`和population sigma（`ddof=0`）。其中“fixed-affine”指
沿同一冻结affine匹配参数改变源宽；“per-width rematch”指每个源宽重新解匹配参数。两类探索均为全理想
一维解析证据，不是新增SIMION场求解，也不能单独归因某一真实电极区域。

### fixed-affine与per-width rematch探索

fixed-affine八点宽度序列为`0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.8, 2.2 mm`，每点
`N=1001`。其中1.0、1.5、2.2 mm的population sigma分别为`0.0745728367`、`0.2568393848`、
`0.8480549797 ns`；八点幂律拟合得到`p=3.0325769184`、`R²=0.9999551795`。因此在该冻结匹配附近，
展宽随源宽近似三次增长是强数值事实，但“近似三次”仍不是某个组件三阶导数的唯一归因。

per-width rematch下，0.5、1.0、2.2 mm的population sigma分别为`0.0089176617`、
`0.0726383715`、`0.8458712749 ns`；相邻有效幂指数分别为`3.02599448`和`3.11351507`。重新匹配可显著
降低窄源绝对展宽，却没有消除随宽度约三次放大的趋势。2.2 mm探索性局部拟合中，三次项解释
`95.935793%`的高阶SSE，三次与四次联合解释`99.631405%`，联合残差RMS为`6.0712%`；只看四次项会给出
错误归因。D1/D2的低阶RMS比为`1.423294e-11`，高阶比约为1，支持“低阶匹配已消去、剩余由高阶形状
控制”的工作假设。由于这些拟合未预注册且只使用全理想一维模型，它们只能作为设计下一轮受控实验的
PROVISIONAL证据，不能发布为Formal物理结论。

### ZERO-MATCH Stage A停止判据

`zero_match_long_higher_order_stage_a_v1`对保留的1.0与2.2 mm官方SIMION checkpoint作只读五折重建；
没有启动新求解器。其正式状态为`PARTIAL_STOP_RULE / PARTIAL_NOT_COMPLETE_STAGE_A`。2.2 mm检测面全局M1
残余方差分数为`0.1967574277804951`，低于预注册阈值`0.70`，故唯一允许结论是
`GLOBAL_M1_RESIDUAL_THRESHOLD_NOT_PASSED`。M2--M4探索性模型解释了M1残差的
`0.9989891722287125`，且每折M4均优于M1，但该结果未参与停止决定，也不能把全局多项式次数解释为局部
泰勒阶数或组件归因。

配置中的`0.16`是对“均匀对称z上纯`z³`时间映射”的解析参考：全局线性M1会吸收`z³`的线性投影，
所以即使数据是纯三次映射，该指标的M1残余方差分数也只有`0.16`。因此观察值`0.196757...`未达到
`0.70`不能排除局部三次或其他高阶行为；它只说明原先选定的全局M1阈值不适合完成该归因。预注册的
M5/M6过拟合敏感性、奇偶分解、预测sigma重建和后续新宽度求解均按停止规则未执行。

### 旧五格SIMION的实际态诊断与失效边界

旧`canonical_long_affine_arm8_width_numerics_n1000`五格在连续前端模式下均完成N=1000 census，但
脉冲时刻实际源态没有逐行复现预注册affine目标，故整个矩阵永久标记为
`INVALID_IDENTITY_OR_CENSUS`；下列数值只允许作`AT-ACTUAL-PULSE-STATE`诊断。名义1.0、1.5、2.2 mm
三格的population sigma分别为`0.0886925266`、`0.2818017283`、`0.9113334962 ns`，局部有效幂指数为
`2.851116`、`3.064566`，端点指数为`2.954799`，五点OLS为`2.953786`且`R²=0.999566`。

目标态为`x=-69.01362184 mm`、`z=-65.85199246 mm`、平均`vz=-2.932352 m/s`、
`dvz/dz=228.806044 (m/s)/mm`及`10 eV`；三格实际脉冲态的平均x约为`-68.66748`、`-68.66715`、
`-68.66645 mm`，平均z约为`-65.84417 mm`，平均vz约为`-1.096 m/s`，斜率约为
`228.939/228.937/228.933 (m/s)/mm`，平均动能为`10.37281/10.37317/10.37392 eV`，实际全宽为
`1.017731/1.526218/2.237280 mm`。这解释了为什么“全数到达”不能代替身份闭合，也禁止把该五格直接与
理想目标态解析曲线作Formal差值。

在实际态口径内，三格相对fixed-affine解析sigma高`18.934%/9.719%/7.462%`，平均TOF差为
`-0.014903/-0.019996/-0.036752 ns`。2.2 mm数值控制的population sigma为base
`0.91133350 ns`、`dt=320`时`0.91133727 ns`（`+0.000414%`）、`q=108`时`0.91124953 ns`
（`-0.009214%`）；直接FWHM为`0.773014/0.764588/0.762527 ns`。最大sigma数值变化只占1.0到2.2 mm
增量`0.822641 ns`的`0.01021%`，所以在这个失效矩阵的实际态内部，观察到的宽度增长不能由这两项数值
设置解释；但身份失败仍阻止其承担预注册物理结论。

所有上述R只允许来自`pulse_effective_peak`，即`detector_time_minus_pulse_effective_time`。旧五格base、
`dt=320`、`q=108`的诊断R依次为`20846.996`、`21076.734`、`21133.712`；
`instrument_clock_peak`只保留为诊断字段，禁止作为resolution authority。

### 官方restart修正版五格最终结果

修正版预注册采用SIMION官方FLY2粒子/Program路径，以`pre_pulse_restart`和冻结
`pre_pulse_source_state`逐行复现脉冲有效时刻目标态；旧连续前端五格继续保持
`INVALID_IDENTITY_OR_CENSUS`，不得承担exact-pulse合同。五格统一使用长焦
`finite_interval_2p2mm_matched_voltage_v1`结构和规范场名`FULL_DOMAIN_PIECEWISE_IDEAL_FIELD`；活动配置中的
`arm8_closed_global_piecewise_theoretical_field`只是该场在本轮运行时遗留的profile ID，`Arm8`不得再作为
新文档、配置或接口的规范场名。分辨率唯一时钟是`CLOCK-PULSE-EFFECTIVE`，即
`detector_time_minus_pulse_effective_time`。

三份源身份冻结如下。每份均为有序ID 1..1000，三个数值控制格复用2.2 mm同一源；五个child summary的
`pre_pulse_restart_source_release_validation.status`均为`PASS`，位置最大逐行误差为0，速度最大逐行误差
不超过`3.537e-7 m/s`，能量最大逐行误差不超过`1.611e-9 eV`。

|规范源名|活动profile ID|目标态CSV SHA-256|materialization receipt SHA-256|
|---|---|---|---|
|`SRC-CANON-IDEAL-LINEAR-ZVZ-1MM-N1000`|`canonical_ideal_linear_z_vz_1mm_n1000`|`22ADAC66F610064AD73E78FC9B17AB850A8FA59B3D6175EE0B5F10357FBC0539`|`A59E16B3783DCDE7930070286C58D5BA6BA8DC0B9756DE61B410A07975672B5B`|
|`SRC-CANON-IDEAL-LINEAR-ZVZ-1P5MM-N1000`|`canonical_ideal_linear_z_vz_1p5mm_n1000`|`2411F2BB62939E1CA74F627ABD567937C698848AB0E332A67784B0F2F8405624`|`7A8FFC4D6E2A4D9B67560592B7401A72984137ACC8AE6F79388275DA494927C2`|
|`SRC-CANON-IDEAL-LINEAR-ZVZ-2P2MM-N1000`|`canonical_ideal_linear_z_vz_2p2mm_n1000`|`75DF5222C32846CA16F7594404067020AEFD1CFCB2577FC8E86BF18A08493D4E`|`7B1D722A9E73635938847EC31DEF0B45824098E1F44D4A7A1B036F6CF02392E6`|

下表直接来自五个保留的child `summary.json`；population sigma按`ddof=0`从同一N=1000
`pulse_effective_peak`总体重算，FWHM和R取同一对象。五个parent/child manifest均为`success`，五格均
1000/1000到达检测器，但仍只是预注册范围内的`FUNCTIONAL_SCREEN_ONLY`，不是Formal资格结果。

|源全宽 / 数值设置|population sigma (ns)|direct FWHM (ns)|pulse-effective R|source release|parent manifest SHA-256|child manifest SHA-256|
|---|---:|---:|---:|---|---|---|
|1.0 mm / q8, dt160|0.0870116832|0.1589231269|101401.832|PASS|`4ED22A0E43766240FEA7E329AB789F5C00A5A1DDB1CC47091D95ED69F50C68FC`|`ED0601D0B0C72C2B124C28CD000626D73D23BB185B76D014FE659A060A4CBEE2`|
|1.5 mm / q8, dt160|0.2625339891|0.2601069240|61955.722|PASS|`C1EE474A2A5981BCF583361CE7B397CBA8C2A6749DC67169C580FD134439777A`|`73D92B17C0F0D2C20CB5EBB2B29EC5E5139DA3F15A6F7EEAE39F4CCAFF392632`|
|2.2 mm / q8, dt160|0.8534370813|0.7258778739|22201.028|PASS|`4C5E69F79FE501E278CDA01E5B67EE98CC9B4C7FED4A023D142F6EF84B206507`|`B6F7D784C9E455BBA9E917A2DC569EF9BB33D0005F57C23B88726BAFCA912CFB`|
|2.2 mm / q8, dt320|0.8526321871|0.7158241088|22512.822|PASS|`BB55DB3F1049E6BF43F0B536B2B2E34F52780CDD53D9B9B5548C61B667D7B59B`|`37628F364FB41A7A47E8BD75A41A33C26B5A4ABDD40F369456505B6F51E2F285`|
|2.2 mm / q108, dt160|0.8528413401|0.7131096958|22598.543|PASS|`DCFDA488EFE78FAD58DC3183B3E0243363890F42A18B24270FDB78AA339C8BA4`|`F3175BEBF885C406434D95F5CBC3B651BF01576F7F389AA0A6E62F0310ABCBEE`|

宽度主对照的sigma比为`1.5/1.0=3.017227`、`2.2/1.5=3.250768`、
`2.2/1.0=9.808304`；相邻有效指数为`2.723633`和`3.078107`，三点预注册OLS描述斜率为
`2.894136`。`Delta_width=sigma(2.2)-sigma(1.0)=0.7664253981 ns`。dt320相对base的绝对sigma变化
为`0.0008048942 ns`，仅为`Delta_width`的`0.105019%`；q108变化为`0.0005957412 ns`，仅为
`0.077730%`。两者均远低于预注册`10% * Delta_width=0.0766425398 ns`数值门，因此本轮强结论是：
在同一长焦、同一全域理想分段场和已逐行闭合的affine源身份下，1.0到2.2 mm的强非线性展宽不是
dt160或q8数值设置主导。

与前节同一fixed-affine全理想解析结果`0.0745728367/0.2568393848/0.8480549797 ns`相比，SIMION三点
分别高`16.6801%/2.2172%/0.6346%`；解析相邻指数为`3.050015/3.118848`。随宽度接近2.2 mm时两条
独立路径在绝对sigma和近三次宽度响应上收敛，支持“低阶匹配后有限区间高阶残差是2.2 mm主矛盾”。
这个结果仍不把高阶唯一指定为三阶，也不证明任意更宽源在重新适配后必然失败；验证后一命题必须为每个
新增宽度独立重解加速器及理论耦合反射器，再做预注册宽度序列，不能把2.2 mm电压原样外推。

`20260814_234500__analysis__python__long-arm8-affine-width-numerics__n1000`的数值与上述raw evidence一致，
但其`summary.json`错误写入`formal_gate_passed=true`；同一文件的`threshold_result_eligible=true`只表示
预注册阈值可评价，不授予Formal资格。该run manifest正确写入`formal_eligible=false`，五个parent/child
run config及manifest也均为非Formal。因此该assessment永久标记为
`NON_AUTHORITATIVE_FORMAL_FIELD_ERROR`，旧artifact不修改且禁止作为Formal证据。科学结论不依赖该错误字段，而直接绑定
上表五对parent/child manifest和独立只读审计：审计重新计算每个manifest SHA，逐项核对status、N=1000
census、source-release validation、pulse-effective指标，并独立计算population sigma、ratio、斜率和
dt/q门；所有数值与上表一致。

### 弃用审计与统一入口后续计划

本轮只记录审计，不在五格运行期间修改共享运行链。审计确认活动实现仍同时存在旧stage-field布尔flag、
Lua adjustable、环境变量和Arm8专用field contract；它们会形成字段默认值、双权威和同义profile风险。
已经移除的deprecated理想反射器hard-mask、resolution-attribution双时钟选择及已判定无效的连续前端
exact-pulse路径不得恢复；全域理想能力由`FULL_DOMAIN_PIECEWISE_IDEAL_FIELD`保留。

五格完成后的原子迁移必须一次覆盖配置、Schema、prepare、adapter、runner、Program builder、runtime
binding、活动campaign和测试：由campaign field-profile ID编译唯一run-local
`resolved_region_field_contract`，完整声明加速器两段、漂移区、反射器两段和域外行为；prepare冻结一次
SHA，adapter只验这一份，runner只传这一份，builder只把合同编译为Lua字面量。迁移同时删除旧field
flags、field env、adjustable默认值、Arm8运行时第二权威和物理同义profile，不保留兼容shim或双路径。
实现前还必须关闭透明栅/真实PA所需的bore横向谓词、漂移边缘场、instance 3/5坐标缩放及域外真实场
语义，并按官方SIMION Program/PA实例机制复核；在完整原子测试通过前不得把半迁移状态投入新求解。

## 永久清理与保留边界

2026-08-14完成七批不可恢复的物理删除，均在删除前用manifest、文件metadata和必要SHA审计确认不属于
当前科学矩阵的唯一证据：

|批次|删除内容|字节|
|---|---|---:|
|第一批|已批准的零散旧/无用文件|550,005|
|第二批|59个非当前legacy PA cache entry|179,406,313,439|
|第三批|4个旧成功run内未由manifest引用的可重构PA副本|90,227,338,032|
|第四批|8个失败、interrupted、无终态或已被成功recovery/formal完整取代的目录|4,765,128,506|
|第五批|已由revision 2 successor逐字节接管的旧`151500` receipt|8,459|
|第六批|47个无合法run终态、无唯一科学证据的invalid scratch目录|6,741,298|
|第七批|正式successor逐字节接管后剩余的2个scratch目录|1,871,436|
|合计|永久删除|274,407,951,175|

这些删除不可恢复；需要旧布局时必须从仍保留的代码、冻结输入与正式入口重新构建，不能假定cache命中。
物理保留边界为：当前33行矩阵、ZERO-MATCH及近期严格复现直接依赖的10个PA cache entry
（`33,919,321,596 bytes`）、全部项目Formal发布物，以及仍由成功manifest逐文件冻结或属于唯一结果/
不可重构原始输入的资产。旧run只在本节保存映射和解释来源，不再作为活动路径；当前引用一律使用上表
successor。清理没有启动SIMION或COMSOL，也没有改变任何科学值、结果表行数或资格边界。
