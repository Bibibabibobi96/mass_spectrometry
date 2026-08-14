# oaTOF 2.2 mm有限区间高阶时间像差验证预注册（2026-08-14）

> `DOC_STATUS: ARCHIVED_READ_ONLY`

## 预注册身份与边界

本文在读取本轮新增分析或求解器结果之前冻结实验问题、矩阵、指标、判据和停止规则。它只是一份
预注册，不包含新结果，不授权修改oaTOF Formal、baseline、阈值或现有证据资格。后续结果必须写入新的
日期化history，本文不得按观察值回写；如因实现或物理原因必须改变设计，须先建立新的日期化预注册并
明确取代范围，已经运行的数据仍按本计划判读。

本计划只使用仓库既有官方支持边界：理想pulse-state源使用SIMION官方individual-particle FLY2和实际
`source_release`逐行验收；透明栅使用`GRID-NATIVE-ONE-ROW`；真实PA使用SIMION Refine与正式
`fast_adjust`电压入口。禁止teleport、epsilon越层、粒子位移、TOF补偿、自建穿栅算法、经验反调
反射器电压或根据检测器/FWHM选择场参数。全理想求解器对照只有在既有注册的官方SIMION Program场
路径能够覆盖完整2.2 mm包络并通过当前adapter合同后才允许执行；否则该阶段停止为`INCONCLUSIVE`，
不得临时建立第二套场实现。

主要问题是：在源、横向状态、结构、理论派生电压、真实反射器、栅网、数值设置和时钟冻结后，源轴向
全宽从1.0 mm扩大到2.2 mm造成的时间展宽，是否主要由一阶匹配之后剩余的二阶及更高阶有限区间时间
映射贡献，而不是释放误差、粒子损失、真实PA、透明栅、反射器、z–vz关联、横向束流或数值离散造成。

预注册主假设为：

- `H-HO`：在固定`ZERO-MATCH-LONG-2P2MM`设计中，2.2 mm检测时间方差的大部分来自相对最佳一阶
  时间映射的非线性剩余，并可由二至四阶项稳定重构；宽度响应显著超出一阶尺度。
- `H-ALT`：观察到的宽度效应可由数值离散、实际场/反射器bundle、释放或损失、横向状态、特定
  z–vz关联或峰指标算法解释，因而不能作高阶主导归因。

“高阶”在本文只表示沿冻结源流形的二阶及以上时间映射贡献，不预先指定为三阶，也不预先归因给
Stage1、Stage2或反射器中的某一个组件。

## 已有证据与允许复用的端点

完整既有矩阵、数值和身份以
[`oaTOF规范矩阵的高阶时间像差续篇`](20260814__oatof-canonical-matrix-high-order-continuation.md)
为准。本文只冻结与新实验判读直接有关的端点，不把既有结果伪称为本计划运行后才得到的验证。

|用途|规范配置与既有结果|现有run身份|
|---|---|---|
|主对照，long contained 1.0 mm true-zero-vz|`PSTATE-ZERO-MATCH-LONG-1MM-ZEROVZ-N1000-SHAE89709`；`ZERO-MATCH-LONG-2P2MM + ACC-II + REFL-REAL-ZERO-MATCH-LONG-2P2MM-FORMAL025 + GRID-NATIVE-ONE-ROW + NUM-WHOLE-Z005-FORMAL025-Q8 + CLOCK-PULSE-EFFECTIVE`；1000/1000，sigma `0.07815522183833873 ns`，R `220804.91383808578`|`20260814_175100__sim__cross__zero-match-long1-ii__n1000`|
|主对照，long full 2.2 mm true-zero-vz|`PSTATE-ZERO-MATCH-LONG-2P2MM-ZEROVZ-N1000-SHA0AFDA7`；除宽度及其source内容身份外与上行同一设计、场、栅、数值和时钟；1000/1000，sigma `0.8514291390090949 ns`，R `22548.02787260909`|`20260814_175200__sim__cross__zero-match-long2p2-ii__n1000`|
|辅助affine 1.0 mm|`PSTATE-LONG-1MM-AFFINE-N1000-SHA22ADAC + ARCH-LONG-Z22-R100 + ACC-II + REFL-REAL-FORMAL025 + GRID-NATIVE-ONE-ROW + NUM-WHOLE-Z005-FORMAL025-Q8 + CLOCK-PULSE-EFFECTIVE`；sigma `0.0778904324189579 ns`，R `203938.282389667`|`20260814_165200__sim__cross__pulse-long1-affine-ii__n1000__r03`|
|辅助affine 2.2 mm|`PSTATE-LONG-2P2MM-AFFINE-N1000-SHA75DF52`；与上一行同一long affine设计bundle；sigma `0.851702852099132 ns`，R `22595.6353545471`|`20260814_165400__sim__cross__pulse-long2p2-affine-ii__n1000__r03`|
|既有long affine `ACC-II`原生单飞端点|规范1.0/2.2 mm源、真实正式反射器、官方原生栅；R `195762.801/21150.666`|`20260814_123000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03`；`20260814_135000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03`，位于`rf_octupole_ion_optics` artifact项目|
|官方原生栅结构与穿越smoke|四栅各一raw-PA row，冻结单粒子穿越`1/1/2/2`并命中检测器|`20260813_160656__gate__simion__native-ideal-grid__smoke`|

已有全理想解析诊断给出long 1.0/2.2 mm population sigma
`0.074573062249/0.848057671713 ns`，而对应`ACC-II + REFL-REAL-FORMAL025`为
`0.084258179/0.909681180 ns`。它支持高阶假设并把真实bundle新增量缩小到约7.3%，但没有独立受治理
run/manifest，因此只能作为先验诊断，不能替代本预注册要求的求解器和数值对照。

现有证据已经排除但未证明严格为零的替代解释如下：同一官方栅在1.0 mm达到约20万，否定其构成普遍
低分辨率上限；同一`ZERO-MATCH-LONG-2P2MM`设计的1.0/2.2 mm true-zero-vz源固定相同横向位置、
横向速度、10 eV、pulse时刻与真实反射器，否定横向展宽和affine关联是该配对的唯一原因；两行均
1000/1000且通过实际source-release验收，否定损失或释放误差造成该数量级差异。尚未排除的是宽度相关
数值误差、真实PA/栅附近场/孔径/反射器的交互份额，以及具体二、三、四阶的分配。

## 冻结主结构、cohort与宽度矩阵

所有主分析只使用`ZERO-MATCH-LONG-2P2MM`，不把短焦2.2 mm纳入因果矩阵。短焦2.2 mm有546个粒子
超出其1.0 mm设计能量包络，只保留为既有描述性证据。主矩阵冻结如下：

|身份维度|冻结值|
|---|---|
|geometry|`ZERO-MATCH-LONG-2P2MM`|
|source family|pulse-effective true-zero-vz；有序ID `1..1000`；固定质量100 u、+1、总动能10 eV|
|横向状态|`position_x_mm=-69.013621843807044`、`position_y_mm=0`、`velocity_x_m_s=4392.8426367593293`、`velocity_y_m_s=0`、`velocity_z_m_s=0`|
|source center|全局`z=-59.5476440793136 mm`；每个宽度关于该中心对称、等间距物化|
|accelerator field|`ACC-II`|
|reflectron field|`REFL-REAL-ZERO-MATCH-LONG-2P2MM-FORMAL025`；只用同一次ZERO-MATCH理论闭合派生电压|
|grid|`GRID-NATIVE-ONE-ROW`|
|solver numerics|主扫描固定`NUM-WHOLE-Z005-FORMAL025-Q8`|
|clock|`CLOCK-PULSE-EFFECTIVE`，即`t_detector-t_pulse,effective`|
|观察事件|`accelerator_focus_forward`为共同上游聚焦面；`reflectron_entrance_forward`为下游交互诊断；`detector_crossing`为主要终态|
|统计合同|N=1000；禁止postselection；同一canonical peak metrics与direct KDE FWHM实现；5000次固定seed bootstrap仅用于预注册区间|

宽度唯一允许轴为
`W={0.50, 0.75, 1.00, 1.25, 1.50, 1.75, 2.00, 2.20} mm`。1.00和2.20 mm必须优先复用上表
既有run；只有manifest、source SHA、resolved结构、场、网格、数值、时钟和指标合同逐项一致时才算命中。
其余六个宽度在任何solver启动前各自物化并冻结独立source机器ID、完整SHA和run ID；不得以本文中的
宽度标签代替最终source身份，也不得因中心、宽度以外任一源量发生变化继续称为单变量宽度扫描。

ID配对以相同规范化位置

$$
u_i=-\frac12+\frac{i-1}{999},\qquad z_i=z_c+W u_i,qquad i=1,\ldots,1000
$$

定义。各宽度共享有序ID和`u_i`，但由于宽度是受控干预，物理`z_i`不同；逐粒子比较必须表述为
规范化位置配对，不得声称干预前位置相同。每行实际release必须继续满足现有位置、速度、时钟和派生
能量容差；任何一行失败即停止后续solver行且不计算该行分辨率。

## 分阶段分析和实验

### 阶段A：既有2.2 mm轨迹的高阶映射识别

先只读复用`20260814_175200__sim__cross__zero-match-long2p2-ii__n1000`的冻结粒子与检查点，不启动
SIMION。对三个预注册观察事件分别以`xi=z-z_c`拟合`T(xi)`；训练/验证固定为5折
`particle_id mod 5`，依次比较一至四阶多项式。五、六阶只作过拟合敏感性，不参与主判据。报告每阶
held-out RMSE、系数、残差、奇偶分量、预测sigma及全体1000粒子的实际sigma；禁止在观察结果后改变
折分、阶数、中心或删除端点。

定义最佳一阶残差`r1=T-(a0+a1*xi)`，四阶残差`r4=T-P4(xi)`，以及

$$
f_{nonlinear}=\frac{Var(r_1)}{Var(T)},\qquad
f_{captured,2:4}=1-\frac{SSE(P_4)}{SSE(P_1)}.
$$

方差和SSE均在各fold的held-out集合计算后按预注册样本数加权汇总。`f_nonlinear`定义“一阶匹配后
非线性剩余是否主导”，`f_captured,2:4`定义该剩余能否由二至四阶稳定解释；不得把任一单个系数非零
直接写成对应阶独占根因。

### 阶段B：固定设计的N=1000宽度扫描

仅当阶段A越过下述继续条件时，按宽度从小到大运行尚缺的六行。每行独立run三件套，顶层SIMION
默认串行、自动重试0；PA、反射器电压和时钟不随宽度重算。宽度扫描同时报告三个观察事件的census、
平均TOF、population/sample sigma、direct FWHM、R、KDE modes、全体终止分类和源验收误差。

对`W>=1.00 mm`的检测面sigma拟合冻结形式

$$
\log \sigma_T=b_0+p_{eff}\log W.

$$

用固定seed的5000次ID bootstrap给出`p_eff`区间。该指数只量化有限区间总体尺度，不等同于某一个
泰勒阶数；即使接近3，也不得单凭指数声称三阶独占。

### 阶段C：替代解释对照

阶段C按以下顺序进行，不合并成一个同时变化多项因素的run：

1. **全理想场对照。** 只比较long 1.0与2.2 mm端点，保持各自冻结source、ID、结构、时钟和指标合同；
   加速器与反射器理想场必须由既有已注册、覆盖完整2.2 mm包络且通过adapter的官方SIMION Program
   profile提供。真实反射器端点电压仍来自同一理论解，不得扫描。若该profile未闭合，停止此项并报告
   `INCONCLUSIVE_FIELD_COMPONENT_ISOLATION`。
2. **空间离散。** 固定主物理配置和轨迹积分设置，只将加速器轴向PA从`dz=0.05 mm`加密到仓库既有
   `dz=0.025 mm`收敛参考；1.0与2.2 mm都运行。不得同时改变横向网格、几何、场模式或电压。
3. **轨迹积分。** 只在已选细PA上固定所有空间离散，比较既有受支持的`tqual_8`与`tqual_108`；不得
   用输出采样间隔冒充内部积分设置。
4. **affine辅助对照。** 只复用既有long 1.0/2.2 mm affine端点，必要时补`W=1.50 mm`一行；它用于
   检查结论是否只在true-zero-vz成立，不参与主结构的高阶份额估计。

数值对照必须使用相同source SHA与有序ID。真实/全理想场对照改变的是预注册field bundle，只能报告
bundle效应，除非另有完整析因cell，不得把差异拆成纯Stage1、Stage2、栅或反射器百分比。

## 主指标、辅助指标与冻结判据

主要响应不是单独的direct FWHM或R，而是：

1. 检测面`population sigma(T)`及宽度效应；
2. 阶段A的`f_nonlinear`与`f_captured,2:4`；
3. 阶段B的`p_eff`及5000次bootstrap区间；
4. 1.0/2.2 mm在加速器焦面与检测面的配对演化。

辅助响应为sample sigma、direct FWHM、R、KDE modes、平均TOF、span、偏度、尾部分位数、各检查点
census、检测传输和终止分类。FWHM或R与sigma排序冲突、多模或明显尾部时，结论以完整峰形和主要
sigma指标为准，不得选择较有利的单一指标。

只有同时满足以下全部条件，后续结果文档才允许写
`SUPPORTED_HIGHER_ORDER_DOMINANT_WITHIN_ZERO_MATCH_LONG`：

1. 阶段A检测面`f_nonlinear>=0.70`，且5折汇总`f_captured,2:4>=0.80`；四阶模型在每一个fold均优于
   一阶模型，五/六阶不得把held-out RMSE再改善超过四阶相对值的20%。
2. 阶段B的`p_eff` 95% bootstrap下界严格大于1.0，且四阶映射对各宽度sigma的预注册预测相对误差
   不超过10%。
3. 1.0与2.2 mm每行实际source-release均PASS、检测器均为1000/1000；如有任何宽度相关损失，强结论
   停止，只能在披露全分母和共同命中cohort后报告`NONLINEAR_WITH_SELECTION_CONFOUNDING`。
4. 全理想场中2.2/1.0 mm检测面sigma比仍不小于5，同时定义
   `Delta_width=sigma(2.2)-sigma(1.0)`；真实bundle相对全理想2.2 mm的绝对sigma差不超过
   `0.25*Delta_width`。未完成受治理全理想SIMION时，不满足本条。
5. 最后两个空间级及最后两个时间积分级引起的2.2 mm sigma变化，各自均不超过主配置
   `Delta_width`的10%，并且不改变“2.2 mm明显宽于1.0 mm”的方向。未达到时不得用延长refine或放宽
   阈值宣布PASS，而应进入数值误差调查。
6. affine辅助端点仍显示2.2/1.0 mm sigma比不小于5；若不满足，只能把结论限制为true-zero-vz流形，
   不得声称与z–vz关系无关。

阈值`0.70`把“主导”明确为一阶拟合后剩余至少占总时间方差70%；`0.80`要求二至四阶解释该非线性
剩余的大部分；5倍宽度比、25% bundle上限和10%数值上限均远小于既有约10.9倍sigma宽度效应，用于
阻止次级场或离散变化被误写成主因。这些是本实验的诊断判据，不授予Formal资格或跨设计普适性。

若只满足阶段A和B而阶段C未闭合，允许的最强结论为
`SUPPORTED_NONLINEAR_WIDTH_RESPONSE_COMPONENT_UNRESOLVED`；若一阶外残差存在但二至四阶不能稳定
重构，则为`NONLINEAR_NONPOLYNOMIAL_OR_NUMERICAL_INCONCLUSIVE`；任何主要判据区间跨过阈值均记为
`INCONCLUSIVE`，不得按点估计取最有利解释。

## 停止规则与禁止事后操作

1. 阶段A若`f_nonlinear<0.70`或`f_captured,2:4<0.80`，不启动新增宽度solver矩阵；否定“二至四阶
   主导”的强版本，并检查观察事件、理论匹配或非多项式机制。
2. 阶段B按宽度递增。任一行source-release失败、ID/census不完整、结构/场/PA/时钟身份漂移或solver
   非success，立即停止尚未启动行；失败run保留原状态，不复用run ID。
3. 若完成`W=1.00、1.50、2.20 mm`三个锚点后`p_eff`区间已不高于1.0，停止其余中间宽度，记录
   `HIGHER_ORDER_SCALING_NOT_SUPPORTED`。1.00与2.20 mm可以复用既有端点，1.50 mm必须使用预冻结新身份。
4. 阶段C空间或时间离散变化超过`0.10*Delta_width`时，暂停场组件归因，先闭合数值误差；不得继续
   扩展物理矩阵掩盖离散不确定度。
5. 全理想官方profile不能覆盖2.2 mm包络、无法由当前adapter消费或需要新建非官方实现时，停止该项；
   解析报告继续只作PROVISIONAL先验，不能冒充求解器对照。
6. 不根据检测时间、FWHM、R、峰模式或检查点结果调整pulse时机、反射器电压、源中心、宽度点、拟合
   阶数、fold、bootstrap seed、阈值或排除粒子。不得在结果后新增“更合适”的主指标、删除端点、改用
   最有利cohort或把辅助分析升级为预注册主要证据。
7. 任何阈值、矩阵或停止规则的变更只对新日期化预注册之后尚未运行的数据生效；既有结果必须继续按
   本文判读并在后续history中同时报告正、负和未完成结果。

本计划的强结论范围仅是`ZERO-MATCH-LONG-2P2MM`、100 u、+1、10 eV、当前官方栅与声明数值范围内的
2.2 mm有限区间；即使全部通过，也不证明任意源条件、任意宽度或其他oaTOF结构都由同一阶次主导。
