# oaTOF 2.2 mm高阶残差与三阶理论推导交接（2026-08-16）

> `DOC_STATUS: ARCHIVED_READ_ONLY`

## 文档职责

本文把截至2026-08-16已经发布的实验事实、当前理论缺口和下一轮三阶推导要求交给后续理论AI。它不是
新的公式权威，不修改项目baseline、resolved design、实验campaign或既有history。当前可执行理论仍只认
[oaTOF理论入口](../../projects/single_reflection_oa_tof_mass_analyzer/docs/theory/README.md)及其链接的公式与
代码；最终实验事实只认
[规范矩阵、高阶像差与统一总表](20260814__oatof-canonical-matrix-high-order-continuation.md)。

后续AI的目标是回答：能否在不牺牲1.0 mm性能、传输和稳健性的条件下，为完整2.2 mm接受宽度增加一个
有物理实现的理论自由度，并由整机三阶条件联合求解，而不是扫描末端分辨率。当前证据支持“低阶匹配后
有限区间高阶残差主导”的工作假设；它不保证新理论一定大幅提高分辨率，也不保证主要剩余项是纯三阶。

## 先给后续AI的直接答案

1. 可以按加速器、漂移、反射器、返回漂移和检测边界分段推导；最终必须把各段组合成同一个从
   `pulse_effective_time`到有效检测面的总时间函数，联合求解全机条件。不能分别把加速器和反射器各自
   调到“局部最优”后再拼接。
2. 加速器和反射器都必须进入三阶推导；`L_up`必须从加速器一阶焦面开始，`L_down`必须终止于有效检测
   面。漂移长度、能量保持关系、反射器入口、折返点和检测面不是可省略的常数尾项。
3. 当前联合求解只闭合总一阶、二阶条件。静止源链能够计算三阶导数作诊断，但不把它作为求解方程；
   affine `z-vz`链只发布`A1/A2`，没有`A3`，所以当前resolved中的三阶字段为`null`，不是零。
4. 当前证据不能称为“纯三阶像差已确认”。近三次宽度标度是强事实，但三阶、四阶、混合项及不同组件
   仍可能共同贡献或相消。
5. 第三个独立自由度必须在看结果前由理论和物理实现共同预声明。禁止随机扫描当前工程`C3`，禁止依据
   detector FWHM、命中粒子或峰位置反向调压。

## 已发布事实与证据身份

### 规范配置语义

- `ACC-RR/IR/RI/II`的两个字母只编码加速器Stage1/Stage2分别采用Real PA场或解析Ideal场；它们不编码
  反射器。下述24格均另用固定真实反射器`REFL-REAL-FORMAL025`。
- 规范透明栅为`GRID-NATIVE-ONE-ROW`，时钟为`CLOCK-PULSE-EFFECTIVE`，即
  `detector_time_minus_pulse_effective_time`；不得恢复epsilon/teleport或absolute instrument clock口径。
- 1.0 mm与2.2 mm规范affine源共享中心、均速与斜率，只改变全宽。规范定义和SHA见
  [canonical history的源注册表](20260814__oatof-canonical-matrix-high-order-continuation.md#规范affine-z-vz-cohort)。
- 短结构上的2.2 mm行是超出1 mm设计宽度的stress control；匹配2.2 mm性能只看
  `ARCH-LONG-Z22-R100`或重新闭合的宽度专用结构。

### 1.0/2.2 mm与四种加速场

以下24行逐项转录自
[统一实验总表](20260814__oatof-canonical-matrix-high-order-continuation.md#统一实验总表与证据结论)，
固定配置为`GRID-NATIVE-ONE-ROW`、`REFL-REAL-FORMAL025`、
`NUM-WHOLE-Z005-FORMAL025-Q8`和`CLOCK-PULSE-EFFECTIVE`。规范affine行的N/cohort均为完整N1000；
real-oct行使用各field cell预声明峰cohort，所以Stage1为Real时N=695、为Ideal时N=706。表中状态均为
`published Functional`且`formal_gate_passed=false`。

|panel/source|architecture / source-design relation|ACC|N/cohort|direct FWHM (ns)|R|modes|evidence status|
|---|---|---|---:|---:|---:|---:|---|
|1.0 mm affine `SRC-CANON-IDEAL-LINEAR-ZVZ-1MM-N1000-SHA0E900A`|`ARCH-SHORT-Z10-R100` / short 1 mm matched|`ACC-RR`|1000|0.208361907|77,511.380|2|published Functional screen|
|同上|`ARCH-LONG-Z22-R100` / long设计内1 mm contained|`ACC-RR`|1000|0.178164547|90,449.726|2|published Functional screen|
|同上|`ARCH-SHORT-Z10-R100` / short 1 mm matched|`ACC-IR`|1000|0.168449517|95,876.826|1|published Functional screen|
|同上|`ARCH-LONG-Z22-R100` / long设计内1 mm contained|`ACC-IR`|1000|0.168216346|95,798.840|1|published Functional screen|
|同上|`ARCH-SHORT-Z10-R100` / short 1 mm matched|`ACC-RI`|1000|0.058362220|276,730.461|1|published Functional screen|
|同上|`ARCH-LONG-Z22-R100` / long设计内1 mm contained|`ACC-RI`|1000|0.060519476|266,280.058|1|published Functional screen|
|同上|`ARCH-SHORT-Z10-R100` / short 1 mm matched|`ACC-II`|1000|0.091324733|176,847.621|3|published Functional screen|
|同上|`ARCH-LONG-Z22-R100` / long设计内1 mm contained|`ACC-II`|1000|0.082319474|195,762.801|4|published Functional screen|
|2.2 mm affine `SRC-CANON-IDEAL-LINEAR-ZVZ-2P2MM-N1000-SHADE5A76`|`ARCH-SHORT-Z10-R100` / over-width stress control|`ACC-RR`|1000|0.896141732|18,022.348|1|published Functional screen|
|同上|`ARCH-LONG-Z22-R100` / long 2.2 mm matched|`ACC-RR`|1000|0.930615839|17,316.618|1|published Functional screen|
|同上|`ARCH-SHORT-Z10-R100` / over-width stress control|`ACC-IR`|1000|0.920858414|17,538.576|1|published Functional screen|
|同上|`ARCH-LONG-Z22-R100` / long 2.2 mm matched|`ACC-IR`|1000|0.936484971|17,208.054|1|published Functional screen|
|同上|`ARCH-SHORT-Z10-R100` / over-width stress control|`ACC-RI`|1000|0.732687179|22,043.200|1|published Functional screen|
|同上|`ARCH-LONG-Z22-R100` / long 2.2 mm matched|`ACC-RI`|1000|0.750478211|21,473.398|1|published Functional screen|
|同上|`ARCH-SHORT-Z10-R100` / over-width stress control|`ACC-II`|1000|0.745340145|21,668.893|1|published Functional screen|
|同上|`ARCH-LONG-Z22-R100` / long 2.2 mm matched|`ACC-II`|1000|0.761926936|21,150.666|1|published Functional screen|
|real-oct `SRC-REAL-OCT-SHA302C`|`ARCH-SHORT-Z10-R100` / measured, not affine-matched|`ACC-RR`|695|1.920194588|8,410.717|2|published Functional; declared peak cohort|
|同上|`ARCH-LONG-Z22-R100` / measured, not affine-matched|`ACC-RR`|695|1.902421940|8,470.653|1|published Functional; declared peak cohort|
|同上|`ARCH-SHORT-Z10-R100` / measured, not affine-matched|`ACC-IR`|706|2.030656684|7,953.200|1|published Functional; declared peak cohort|
|同上|`ARCH-LONG-Z22-R100` / measured, not affine-matched|`ACC-IR`|706|2.003488284|8,043.348|1|published Functional; declared peak cohort|
|同上|`ARCH-SHORT-Z10-R100` / measured, not affine-matched|`ACC-RI`|695|1.803288117|8,956.145|1|published Functional; declared peak cohort|
|同上|`ARCH-LONG-Z22-R100` / measured, not affine-matched|`ACC-RI`|695|1.784378062|9,031.177|1|published Functional; declared peak cohort|
|同上|`ARCH-SHORT-Z10-R100` / measured, not affine-matched|`ACC-II`|706|1.887925686|8,554.610|1|published Functional; declared peak cohort|
|同上|`ARCH-LONG-Z22-R100` / measured, not affine-matched|`ACC-II`|706|1.870324061|8,616.160|1|published Functional; declared peak cohort|

四格场改变结果，却没有把完整2.2 mm恢复到1.0 mm量级；同一field cell内短、长差异也不是数量级差异。
因此结构焦距或单个真实加速场区不是2.2 mm总损失的充分解释。Stage2是规范1 mm和真实八极杆束共同
指向的主要直接改善区，但这不等于Stage2已经独立优化，见
[控制变量强结论第4项](20260814__oatof-canonical-matrix-high-order-continuation.md#仅由控制变量证据支持的强结论)。

代表性1.0/2.2 mm `ACC-II`求解器run为
`20260814_122000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03`、
`20260814_123000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03`、
`20260814_134000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03`和
`20260814_135000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03`。完整行、SHA和其他field cell只从
canonical history追溯，不在本文建立第二份run注册表。

### 全理想、ZERO-MATCH与宽度控制

|控制|关键结果|排除或保留的解释|
|---|---|---|
|全理想轴向精确组合|1.0 mm短/长population sigma为0.07236/0.07457 ns；2.2 mm为0.82802/0.84806 ns|2.2 mm主展宽在理想加速器和理想反射器内已经存在；真实PA、漂移残余场、真实反射器及边界bundle只在该配对上再增加约7.3%，不能把这7.3%叫纯反射器误差|
|旧affine设计上的zero-vz消融|1.0 mm短/长仅R=8,133/8,311|这是源—设计失配，不是zero-vz物理极限，也不是native grid普遍8k上限|
|官方ZERO-MATCH|1.0 mm短/长contained达到R=202,907/220,805；完整2.2 mm仍为R=22,548|重新闭合均速/斜率为0的理论后，1 mm恢复高R；完整宽度损失仍存在|
|fixed-affine解析宽度序列|0.25/0.5/0.75/1.0/1.25/1.5/1.8/2.2 mm，每点N=1001；1.0/1.5/2.2 mm sigma为0.0745728367/0.2568393848/0.8480549797 ns；`p=3.0325769184`、`R²=0.9999551795`|近三次增长是强数值事实，不是纯三阶组件归因；canonical叙事未逐点列出其余五个sigma，复判时不得插值冒充原值|
|per-width rematch解析序列|0.5/1.0/2.2 mm sigma为0.0089176617/0.0726383715/0.8458712749 ns；有效指数3.02599448和3.11351507|按宽度重匹配降低窄源展宽，但没有消除宽区近三次增长|

全理想四行、包络边界和公式组合见
[全理想精确解析四行诊断](20260814__oatof-canonical-matrix-high-order-continuation.md#全理想精确解析四行诊断)。
这两组宽度探索是全理想一维解析证据，无SIMION grid和solver numerics；canonical段落冻结
`ARCH-LONG-Z22-R100`、`ACC-II`、`REFL-REAL-FORMAL025`、`CLOCK-PULSE-EFFECTIVE`和population sigma
`ddof=0`语义，同时正文称其为“全理想一维解析”。该反射器标签与“全理想”措辞的层级不能由本文重写；
后续AI若需逐项复算，必须回到该解析调用的resolved输入，而不能据显示名自行猜测场实现。

同一2.2 mm探索性局部拟合中，三次项解释高阶SSE的95.935793%，三次与四次联合解释99.631405%，
联合残差RMS为6.0712%；`D1/D2`低阶RMS比为`1.423294e-11`，高阶比约为1。这进一步支持低阶已闭合、
高阶形状控制的假设，但仍不能把三次拟合项等同于某个组件的局部三阶导数。预注册Stage A又得到全局
M1残余方差分数0.1967574，未过0.70停止门；纯对称`z^3`映射的该指标理论上也只有0.16，所以这次FAIL
不能排除局部三阶。探索性M2--M4解释M1残差的0.998989，但未参与停止决定。后续AI必须保留这个负结果，
不得把Stage A写成“已经证明三阶”。

ZERO-MATCH成功run依次为
`20260814_175000__sim__cross__zero-match-short1-ii__n1000`、
`20260814_175100__sim__cross__zero-match-long1-ii__n1000`和
`20260814_175200__sim__cross__zero-match-long2p2-ii__n1000`，其源身份、反射器身份及SHA见
[ZERO-MATCH官方求解器与三行结果](20260814__oatof-canonical-matrix-high-order-continuation.md#zero-match官方求解器与三行结果)。

### Pulse ablation与ZERO-MATCH完整九行

以下九行均固定`GRID-NATIVE-ONE-ROW`、`ACC-II`、`NUM-WHOLE-Z005-FORMAL025-Q8`、
`CLOCK-PULSE-EFFECTIVE`和N=1000；均由actual source-release验收，状态为published Functional、
`formal_gate_passed=false`。普通pulse ablation使用`REFL-REAL-FORMAL025`；ZERO-MATCH使用表中各自专用的
理论闭合反射器电压身份。

|panel/source|architecture / source-design relation|reflectron|FWHM (ns)|R|modes|evidence status|
|---|---|---|---:|---:|---:|---|
|pulse `PSTATE-SHORT-1MM-AFFINE-N1000-SHA960547`|`ARCH-SHORT-Z10-R100` / matched affine|`REFL-REAL-FORMAL025`|0.089415226|180,624.274|5|published Functional; source_release PASS|
|pulse `PSTATE-SHORT-1MM-ZEROVZ-N1000-SHAE2E49C`|`ARCH-SHORT-Z10-R100` / 0/0 on affine design|`REFL-REAL-FORMAL025`|1.985726372|8,133.295|2|published Functional; source_release PASS|
|pulse `PSTATE-LONG-1MM-AFFINE-N1000-SHA22ADAC`|`ARCH-LONG-Z22-R100` / contained affine|`REFL-REAL-FORMAL025`|0.079019433|203,938.282|5|published Functional; source_release PASS|
|pulse `PSTATE-LONG-1MM-ZEROVZ-N1000-SHAEA8E62`|`ARCH-LONG-Z22-R100` / 0/0 on affine design|`REFL-REAL-FORMAL025`|1.938953474|8,311.201|2|published Functional; source_release PASS|
|pulse `PSTATE-LONG-2P2MM-AFFINE-N1000-SHA75DF52`|`ARCH-LONG-Z22-R100` / full-width affine matched|`REFL-REAL-FORMAL025`|0.713201024|22,595.635|1|published Functional; source_release PASS|
|pulse `PSTATE-LONG-2P2MM-ZEROVZ-N1000-SHA387DEF`|`ARCH-LONG-Z22-R100` / 0/0 on affine design|`REFL-REAL-FORMAL025`|0.697181849|23,114.528|2|published Functional; source_release PASS|
|ZERO-MATCH `PSTATE-ZERO-MATCH-SHORT-1MM-ZEROVZ-N1000-SHA5DA80C`|`ZERO-MATCH-SHORT-1MM` / 0/0 matched|`REFL-REAL-ZERO-MATCH-SHORT-1MM-FORMAL025`|0.079322237|202,907.169|3|published Functional; source_release PASS|
|ZERO-MATCH `PSTATE-ZERO-MATCH-LONG-1MM-ZEROVZ-N1000-SHAE89709`|`ZERO-MATCH-LONG-2P2MM` / 1 mm contained|`REFL-REAL-ZERO-MATCH-LONG-2P2MM-FORMAL025`|0.072765833|220,804.914|3|published Functional; source_release PASS|
|ZERO-MATCH `PSTATE-ZERO-MATCH-LONG-2P2MM-ZEROVZ-N1000-SHA0AFDA7`|`ZERO-MATCH-LONG-2P2MM` / full-width 0/0 matched|`REFL-REAL-ZERO-MATCH-LONG-2P2MM-FORMAL025`|0.712576264|22,548.028|1|published Functional; source_release PASS|

### 官方restart与数值控制

官方FLY2 restart修正版逐行闭合脉冲有效时刻的目标态，五格均1000/1000到达。固定身份为
`ARCH-LONG-Z22-R100`、`GRID-NATIVE-ONE-ROW`和`CLOCK-PULSE-EFFECTIVE`；场只使用一个规范身份
`FULL_DOMAIN_PIECEWISE_IDEAL_FIELD`，其区域合同同时覆盖加速器Stage1/Stage2、漂移和反射器Stage1/Stage2，
所以本表不能再拼出第二个反射器场名。旧运行时profile中的`Arm8`只作lineage，不是规范场名。五行均为
`FUNCTIONAL_SCREEN_ONLY`、非Formal。

|source / 全宽|numerics|N/cohort|population sigma (ns)|direct FWHM (ns)|R|modes|evidence status|
|---|---|---:|---:|---:|---:|---:|---|
|`SRC-CANON-IDEAL-LINEAR-ZVZ-1MM-N1000` / 1.0 mm|q8, dt160|1000|0.0870116832|0.1589231269|101,401.832|未登记|FUNCTIONAL_SCREEN_ONLY|
|`SRC-CANON-IDEAL-LINEAR-ZVZ-1P5MM-N1000` / 1.5 mm|q8, dt160|1000|0.2625339891|0.2601069240|61,955.722|未登记|FUNCTIONAL_SCREEN_ONLY|
|`SRC-CANON-IDEAL-LINEAR-ZVZ-2P2MM-N1000` / 2.2 mm|q8, dt160|1000|0.8534370813|0.7258778739|22,201.028|未登记|FUNCTIONAL_SCREEN_ONLY|
|同上 / 2.2 mm|q8, dt320|1000|0.8526321871|0.7158241088|22,512.822|未登记|FUNCTIONAL_SCREEN_ONLY|
|同上 / 2.2 mm|q108, dt160|1000|0.8528413401|0.7131096958|22,598.543|未登记|FUNCTIONAL_SCREEN_ONLY|

`Delta_width=sigma(2.2)-sigma(1.0)=0.7664254 ns`；dt320和q108变化只占该增量的0.105%和0.078%。
因此，在这个冻结身份和已测数值范围内，dt160或q8不是宽度增长的主导原因。对应lineage run依次为
`20260814_230000__sim__cross__long-arm8-restart-affine-1mm-q8-dt160__n1000`、
`20260814_231000__sim__cross__long-arm8-restart-affine-1p5mm-q8-dt160__n1000`、
`20260814_232000__sim__cross__long-arm8-restart-affine-2p2mm-q8-dt160__n1000`、
`20260814_233000__sim__cross__long-arm8-restart-affine-2p2mm-q8-dt320__n1000`和
`20260814_234000__sim__cross__long-arm8-restart-affine-2p2mm-q108-dt160__n1000`。manifest SHA、旧`Arm8`
命名的弃用边界及错误Formal字段隔离见
[2.2 mm高阶假设的分层证据](20260814__oatof-canonical-matrix-high-order-continuation.md#22-mm高阶假设的分层证据)和
[官方restart修正版五格最终结果](20260814__oatof-canonical-matrix-high-order-continuation.md#官方restart修正版五格最终结果)。

### 旧N77/N70与legacy grid弱证据

下表逐项来自
[源、场与结构配置注册表的历史小N矩阵](20260814__oatof-source-field-configuration-registry-and-results-matrix.md)。
它们统一使用`CLOCK-PULSE-EFFECTIVE`，但使用`GRID-LEGACY-EPSILON`和run-bound单点数值配置，不是
`GRID-NATIVE-ONE-ROW`规范矩阵；N77、N70又不是同一cohort。因此只允许帮助提出假设，不能与上面的
N1000规范矩阵混算效应或用于三阶阶次确认。

|source/cohort|architecture|ACC|reflectron|numerics|N|FWHM (ns)|R|modes|evidence status|
|---|---|---|---|---|---:|---:|---:|---:|---|
|`SRC-IDEAL-SHORT-Z10` / `COHORT-SHORT-Z10-N77`|`ARCH-SHORT-Z10-R100`|`ACC-RR`|`REFL-REAL-R100`|`NUM-RUNBOUND-SHORT-N77`|77|1.074719|15,028.088|1|historical small-N diagnostic|
|同上|`ARCH-SHORT-Z10-R100`|`ACC-II`|`REFL-REAL-R100`|`NUM-RUNBOUND-SHORT-N77`|77|0.198941|81,182.600|1|historical paired A/B diagnostic|
|`SRC-IDEAL-Z22-AXIAL` / `COHORT-LONG-Z22-AB-N70`|`ARCH-LONG-Z22-R100`|`ACC-RR`|`REFL-REAL-R100`|`NUM-RUNBOUND-LONG-N70`|70|1.468338|10,975.323|1|historical small-N diagnostic|
|同上|`ARCH-LONG-Z22-R100`|`ACC-II`|`REFL-REAL-R100`|`NUM-RUNBOUND-LONG-N70`|70|1.645369|9,794.285|1|historical paired A/B diagnostic|
|`SRC-IDEAL-Z22-AXIAL` / `COHORT-Z22-SHORT-N77`|`ARCH-SHORT-Z10-R100`|`ACC-II`|`REFL-REAL-R100`|`NUM-RUNBOUND-Z22-SHORT-N77`|77|1.555085|10,385.740|未登记|historical cross-structure description|
|`SRC-IDEAL-Z22-AXIAL` / `COHORT-Z22-LONG-N70`|`ARCH-LONG-Z22-R100`|`ACC-II`|`REFL-REAL-R100`|`NUM-RUNBOUND-Z22-LONG-N70`|70|1.557749|10,345.193|未登记|historical cross-structure description|

前四行run依次为
`20260813_162500__sim__simion__r100-short-ideal-source-real-accel__n77`、
`20260813_163000__sim__simion__r100-short-ideal-source-ideal-accel__n77`、
`20260813_163500__sim__simion__r100-long-ideal-source-real-accel__n70`和
`20260813_164000__sim__simion__r100-long-ideal-source-ideal-accel__n70`。这些旧结果曾提示：短焦实际场
显著限制1 mm理想源，而长焦2.2 mm末端R不能简单按“真实场一定更差”解释；但规范N1000、官方grid和
全理想宽度序列已取代它们作为当前高阶主判断的依据。

同日还有一组连续前端legacy五格。它虽然完成N=1000 census，却没有在pulse时刻逐行复现预注册affine
目标，永久状态为`INVALID_IDENTITY_OR_CENSUS`；只能按`AT-ACTUAL-PULSE-STATE`读取，不能承担规范源
结论。其固定字段沿用当时long/full-domain lineage、pulse-effective时钟和旧运行合同：

|actual-state行|实际全宽 (mm)|population sigma (ns)|FWHM (ns)|R|evidence status|
|---|---:|---:|---:|---:|---|
|名义1.0 mm / base|1.017731|0.0886925266|未登记|未登记|INVALID_IDENTITY_OR_CENSUS diagnostic|
|名义1.5 mm / base|1.526218|0.2818017283|未登记|未登记|INVALID_IDENTITY_OR_CENSUS diagnostic|
|名义2.2 mm / q8, dt160|2.237280|0.91133350|0.773014|20,846.996|INVALID_IDENTITY_OR_CENSUS diagnostic|
|名义2.2 mm / q8, dt320|同一实际态控制|0.91133727|0.764588|21,076.734|INVALID_IDENTITY_OR_CENSUS diagnostic|
|名义2.2 mm / q108, dt160|同一实际态控制|0.91124953|0.762527|21,133.712|INVALID_IDENTITY_OR_CENSUS diagnostic|

这组实际态的端点幂指数约2.954799、五点OLS约2.953786且`R²=0.999566`；dt/q最大sigma变化只占
1.0→2.2 mm增量的0.01021%。它只能作为“身份失败后仍观察到近三次宽度响应”的敏感性证据。官方restart
五格已解决源身份问题，当前判断必须以前者的正式修正版表为主。

## 已排除、未排除与禁止越界

### 在当前控制范围内已排除

- 规范源没有在pulse时刻实现：官方restart已逐粒子闭合位置、速度、时钟和派生能量。
- dt160或q8是1.0→2.2 mm展宽主因：两个控制变化远小于宽度增量。
- native one-row透明栅把所有工况限制在约8k：同方法下ZERO-MATCH 1 mm已达到约20万。
- 仅仅漏改长焦加速器或反射器电压：宽度专用理论重匹配和ZERO-MATCH仍保留完整2.2 mm损失。
- 单独改短/长焦结构即可恢复数量级：四种加速场下短、长2.2 mm都在约17k–22k。
- 真实PA或真实反射器是2.2 mm主展宽的必要条件：全理想轴向模型已经出现约0.83–0.85 ns sigma。

### 仍未排除或尚未唯一分离

- 三阶、四阶及更高阶的独立份额，以及它们在有限区间内的相消或增强；现有近三次标度不能唯一回答。
- 加速器Stage1、Stage2、漂移、反射器各段和检测边界对总三阶项的独立份额。
- affine主流形与随机残差、横向位置/速度、能量散布之间的二变量或多变量混合项。
- 真实PA场形与grid离散误差的精确百分比；尚无同一冻结电势函数、同一粒子的独立网格收敛序列。
- RR/II多模峰对direct FWHM排序的稳定性；现有核心表没有完成预注册bootstrap和数值收敛。
- 一维轴向三阶修正迁移到三维真实场后是否仍有效，及是否会牺牲传输、孔径、折返深度或质量范围。
- 固定真实反射器/downstream bundle的非加性交互；它已经被观测到，但不能改写成纯电压失配。

所以目前不能称“2.2 mm由纯三阶主导”，不能保证加入第三阶闭合后R会大幅提高，也不能把剩余损失唯一
归因于反射器、加速器或grid。

## 当前理论闭合到哪里

令归一化整机时间为

$$
\tau_{\rm total}(\mathcal W)=\tau_A+\tau_{\rm drift,up}
+\tau_{R1}+\tau_{R2}+\tau_{\rm drift,down},
$$

并在名义实际能量`W_c`处定义原始导数（不是多项式系数）

$$
A_n=\left.\frac{d^n\tau_A}{d\mathcal W^n}\right|_c,
\quad
R_n=\left.\frac{d^n(\tau_{\rm drift,up}+\tau_{R1}+\tau_{R2}+\tau_{\rm drift,down})}
{d\mathcal W^n}\right|_c,
\quad D_n=A_n+R_n.
$$

当前[整机纵向耦合理论](../../projects/single_reflection_oa_tof_mass_analyzer/docs/theory/oatof_oaaccelerator_coupling.md)
用反射器的两个独立场自由度联合解`D1=0`和`D2=0`。静止源路径已有解析`A3`，因此可返回`D3`诊断，
但不解`D3=0`。当前
[线性z-vz理论](../../projects/single_reflection_oa_tof_mass_analyzer/docs/theory/z_vz_linear_phase_space_coupling.md)
只把affine链的`A1/A2`传给同一耦合求解器，没有发布`A3`；因此affine resolved中的
`accelerator_third_derivative_at_focus`和`total_third_derivative`为`null`。这正是下一轮首先要补的理论缺口。

## 给后续AI的符号与A3推导检查单

### 一维affine主流形

沿加速器局部坐标`x`定义

$$
v_z(x)=v_c+\kappa(x-x_c),\qquad
\chi(x)=\chi_c+\beta(x-x_c),
$$

$$
\chi_c=v_c\sqrt{\frac{m/q}{2}},\qquad
\beta=\kappa\sqrt{\frac{m/q}{2}},\qquad
\mathcal W(x)=V_R-E_1x+\chi(x)^2.
$$

在中心点记

$$
p=\mathcal W'_c=-E_1+2\chi_c\beta,\qquad
q=\mathcal W''_c=2\beta^2,\qquad r=\mathcal W'''_c=0.
$$

把固定`chi`时的能量导数记为`B1/B2/B3`。现有`B1/B2`定义保持不变；待核对的第三个因子为

$$
B_3=\frac{3}{4E_1(\mathcal W-V_G)^{5/2}}
+\frac{3}{4E_2}\left[\mathcal W^{-5/2}-(\mathcal W-V_G)^{-5/2}\right]
-\frac{15D_A}{8\mathcal W^{7/2}}.
$$

由现有时间函数直接对`x`求导，应得到

$$
\tau_x=pB_1-\frac{2\beta}{E_1},\qquad
\tau_{xx}=qB_1+p^2B_2,
$$

$$
\tau_{xxx}=rB_1+3pqB_2+p^3B_3
=3pqB_2+p^3B_3.
$$

任意单调`W(x)`的三阶换元公式是

$$
A_3=\frac{\tau_{xxx}}{p^3}
-\frac{3\tau_{xx}q}{p^4}
+\frac{3\tau_xq^2}{p^5}
-\frac{\tau_xr}{p^4}.
$$

对本affine链`r=0`，候选等价式应化为

$$
A_{3,\rm lin}
=\frac{\tau_{xxx}p^2-3\tau_{xx}pq+3\tau_xq^2}{p^5}
=B_3-\frac{24\beta^5}{E_1p^5}.
$$

这两式是交接给后续AI进行符号证明、量纲检查、退化检查和高精度有限差分核验的候选，不因写入本文而
成为公式权威。至少检查：`beta→0`退化为静止源`B3`；不同差分步长收敛；直接对精确时间函数求导与
等价式一致；`p`接近零时必须失败关闭而非放大数值噪声。

### 二变量`u/eta`混合项

不能只沿一条完美affine直线做三阶闭合。用无量纲、中心化变量定义

$$
x=x_c+h u,\qquad
v_z=v_c+\kappa h u+s_v\eta,
$$

其中`h`是源半宽，`u∈[-1,1]`；`s_v`是预先冻结的残差速度尺度，`eta`的cohort、分布和与`u`的相关性
必须来自detector-blind源合同。定义方向算子

$$
\mathcal L_u=h(\partial_x+\kappa\partial_v),\qquad
\mathcal L_\eta=s_v\partial_v.
$$

总时间到三阶必须保留全部混合项：

$$
\begin{aligned}
\Delta T={}&T_u u+T_\eta\eta
+\frac12(T_{uu}u^2+2T_{u\eta}u\eta+T_{\eta\eta}\eta^2)\\
&+\frac16(T_{uuu}u^3+3T_{uu\eta}u^2\eta
+3T_{u\eta\eta}u\eta^2+T_{\eta\eta\eta}\eta^3)+O(4),
\end{aligned}
$$

其中例如`T_uueta=(L_u^2 L_eta T)_0`。即使主流形的`T_uuu`被压低，`u²eta`、`u eta²`或纯`eta³`
仍可能限制真实束；后续理论不得以完美affine一维结果替代真实源的混合项预算。

### factorial convention、检查面和自由度计数

- 本文及后续公式中的`A_n/R_n/D_n/T_ijk`均指原始导数。泰勒系数为导数除以阶乘：
  `D3`对应`D3*deltaW^3/3!`；若拟合多项式直接写`c3*deltaW^3`，则`D3=6c3`。所有JSON、表和测试必须
  显式记录`raw_derivative`或`polynomial_coefficient`，禁止混用。
- 预声明检查面至少包括：pulse-state源中心、grid1前后、grid2/加速器出口、理论一阶焦面、反射器入口、
  Stage1/Stage2边界、名义折返点、反射器返回入口、有效检测面。分段导数相加前必须统一能量变量、方向、
  坐标、时钟和参考面。
- 若所有几何和加速器参数被冻结，当前反射器只有两个独立自由度，刚好闭合`D1/D2`，没有第三个自由度
  可再闭合`D3`。一般计数必须满足`独立原生自由度数 - 额外物理约束数 >= 3`，才能同时解三个总导数；
  固定总能量、焦面位置、单调电位、转向深度、机械长度和检测面等都是约束，不能漏计。

## 第三自由度的治理要求

后续AI先提交“候选自由度—派生关系—物理实现—约束—退化极限”表，获批一种后再求解。可论证的候选
族包括：

1. 在保持总能量与硬件包络的条件下，把加速器电压分配或焦距相关的一个原生设计量纳入全机联合解；
   由此改变的焦面、漂移和反射器电压必须全部重派生，不能只改一个电压。
2. 使用有明确电极实现和单调约束的第三反射场自由度，例如预声明的独立第三场区或独立偏置环组；必须
   先证明它是SIMION/COMSOL/CAD均可实现的真实自由度，而不是连续场中的抽象系数。
3. 仅当机械设计允许时，把一个场自由路径或有效检测面位置作为设计自由度；它必须同步进入几何、检测
   合同和CAD，不能在后处理里移动检测面。

现有线性理论中的`DeltaV=C3 f(1-f)(2f-1)`明确把`C3`称为工程校正量而非理论派生量，因此当前不能直接
作为第三自由度扫描。如果未来选择这一族，必须先从电极边界值问题建立`C3→D3`的可验证映射，再由
`D1=D2=D3=0`和物理约束一次求解；不得随机取`C3`、按detector峰宽挑赢家或依据探测粒子反调。

## 分阶段验证与预注册成功判据

### 阶段T：符号与一维理论

1. 复现现有`D1/D2`和静止源`D3`，再证明affine `A3`的两种等价式及`beta→0`退化。
2. 对每个候选自由度做Jacobian秩与条件数检查；若`D1/D2/D3`对三个自由度不满秩或病态，立即停止，
   不用更大扫描掩盖不可辨识。
3. 在固定宽度序列0.25/0.5/0.75/1.0/1.25/1.5/1.8/2.2 mm上比较旧设计和三阶设计，输出每个检查面的
   `D1/D2/D3/D4`、population sigma、span和能量/折返包络。D4必须报告，防止把三阶压低后由四阶接管。
4. 用冻结的`u/eta`网格或求积报告纯项和混合项预算，不以单一端点或只沿`eta=0`的曲线宣称真实束改善。

### 阶段I：全域理想场与官方restart

复用现有唯一family-source workflow、官方FLY2逐粒子restart、`FULL_DOMAIN_PIECEWISE_IDEAL_FIELD`、
`GRID-NATIVE-ONE-ROW`与`CLOCK-PULSE-EFFECTIVE`。先跑N=100功能检查，再跑同源N=1000的1.0/1.5/2.2 mm
宽度对照；第三自由度以外的source、cohort、几何身份、数值和分析合同必须冻结。不得新增第二CLI、
teleport或自建粒子搬运。

### 阶段R：真实场与组件归因

理想场成功后才进入真实PA。用同一冻结粒子和同一理论派生电压重做`ACC-RR/IR/RI/II`，反射器身份另列；
若需要区分真实场与grid误差，再增加同一电势函数下的独立局部网格收敛序列。组件归因必须以检查面和
配对ID为基础，不能从末端R反推某个电极区域。

### 建议在看新结果前冻结的成功门

以下是交接建议，不是已批准阈值；后续campaign必须在求解前冻结最终数值：

- 主门：2.2 mm长焦匹配源的population sigma至少降低50%，direct FWHM至少降低30%，且R、sigma、FWHM
  三者方向一致；若峰变多，不能仅凭主峰FWHM判PASS。
- 非劣门：1.0 mm同结构的population sigma和direct FWHM恶化均不超过10%，KDE模式不增加；同时报告
  50%、90%、95%稳健时间宽度，防止只优化窄主峰。
- 传输门：理想场保持1000/1000；真实场不低于配对baseline预注册非劣界，并报告全终态census，禁止
  postselection。
- 数值门：dt和trajectory-quality变化对关键改善量的影响小于改善量的10%；随后按风险决定是否补局部
  网格序列。
- 物理门：所有粒子进入所声明反射级且不穿底；电压单调、间隙合法、源与检查面在合法域内；第三自由度
  的实际电极映射与理论变量一致。
- 稳健门：改善至少在1.5和2.2 mm两点保持，并在预声明的小电压/几何扰动下不出现符号翻转或传输崩溃。

即使这些门全部通过，结果仍先是Functional/Candidate级证据；bootstrap、数值收敛、跨求解器和GUI/CAD
门禁完成前不得升级Formal。

## 来源分层

### 项目事实与公式权威

- [规范矩阵、高阶像差与统一总表](20260814__oatof-canonical-matrix-high-order-continuation.md)：最终实验表、
  控制变量强结论、宽度/数值证据和限制。
- [线性z-vz相空间理论](../../projects/single_reflection_oa_tof_mass_analyzer/docs/theory/z_vz_linear_phase_space_coupling.md)：
  当前affine `A1/A2`及工程`C3`边界。
- [整机纵向耦合理论](../../projects/single_reflection_oa_tof_mass_analyzer/docs/theory/oatof_oaaccelerator_coupling.md)：
  焦面、`L_up/L_down`、静止源三阶诊断及联合`D1/D2`。
- [官方restart五格机器合同](../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/diagnostics/canonical_long_affine_arm8_width_numerics_restart_n1000_campaign.json)：
  lineage run、冻结源和数值变量；`Arm8`仅是历史profile命名，不是新规范场名。

### 外部primary sources

- Wiley & McLaren, 1955：双场TOF空间聚焦的原始论文，
  [DOI 10.1063/1.1715212](https://doi.org/10.1063/1.1715212)。
- Mamyrin et al., 1973：mass-reflectron原始论文，
  [Soviet Physics JETP 37, 45–48](https://jetp.ras.ru/cgi-bin/dn/e_037_01_0045.pdf)。
- Stein, 1974：TOF空间—速度聚焦原始分析，
  [DOI 10.1016/0020-7381(74)80008-2](https://doi.org/10.1016/0020-7381(74)80008-2)。
- V. M. Doroshenko与R. J. Cotter, 1999, *Ideal velocity focusing in a reflectron time-of-flight mass
  spectrometer*, JASMS 10(10), 992--999，
  [DOI 10.1016/S1044-0305(99)00067-7](https://doi.org/10.1016/S1044-0305(99)00067-7)。文献事实是：作者对
  任意上游场、下游场和反射器已知减速段给出一维理想反射器场的解析构造；这支持本项目按完整
  source-to-detector总时间联合求解，但不证明当前有限电极、三维孔径或2.2 mm源一定能实现该理想曲场。
- R. J. Cotter与V. M. Doroshenko, 2002, *Method and apparatus for correction of initial ion velocity in a
  reflectron time-of-flight mass spectrometer*,
  [US6365892B1](https://patents.google.com/patent/US6365892B1/en)。专利把总时间明确分成上游、下游、反射器
  已知段和待求曲场段，并让待求镜场依赖完整初始能量区间；这进一步支持“可分段计算、必须全机闭合”，
  但专利的一维无限阶速度聚焦不是本机三维真实场性能保证。
- M. L. Vestal, 1992, *Time-of-flight analyzer and method*,
  [US5160840A](https://patents.google.com/patent/US5160840A/en)。文献事实是：额外独立反射场以及源/探测器至
  反射器距离被联合调节，以修正源区、加减速场和透镜引入的时间差；对本项目的推断仅是第三自由度可以
  位于反射器或路径几何，不能由该专利断言哪一个自由度适合当前硬件。
- 1999, *Orthogonal electron impact source for a time-of-flight mass spectrometer with high mass resolving
  power*, IJMS 185--187, 221--226，
  [DOI 10.1016/S1387-3806(98)14152-0](https://doi.org/10.1016/S1387-3806(98)14152-0)。原始oaTOF实验将
  反射器描述为从源的McLaren空间焦面成像至探测器，并可补偿该空间焦点的高阶误差；这支持源与反射器
  的控制变量耦合，不足以把本项目近三次宽度响应唯一归因于反射器或加速器。
- 2014, *Time-of-flight mass spectrometer*,
  [US8772708B2](https://patents.google.com/patent/US8772708B2/en)。专利事实是：总`T(E)`按能量展开，双级
  反射器闭合一、二阶能量导数后通常仍有三阶及更高阶项；对本项目只能推出必须显式报告`D3/D4`，不能
  把能量三阶项等同于源坐标三阶项或混合项。
- A. A. Makarov等, 2012, *Charged Particle Analysers and Methods of Separating Charged Particles*,
  [US20120091332A1](https://patents.google.com/patent/US20120091332A1/en)。专利把初始能量、位置和角度的
  时间聚焦并列为高分辨要求；这支持本文保留`u/eta`及横向混合项，但不直接给出当前单反射oaTOF的
  第三自由度或电压解。
- A. A. Makarov等, 2007, *Multi-reflecting time-of-flight mass spectrometer with isochronous curved ion
  interface*, [EP1866951A2](https://patents.google.com/patent/EP1866951A2/en)。专利用`T|k`、`T|kk`、
  `T|kkk`及空间、角度和交叉映射项区分能量聚焦与完整等时性，并指出注入/正交加速器仍可限制整机；
  该多反射结构的具体电极解不能直接移植到本项目，但其映射变量和阶次区分适用。
- J. M. Brown、M. R. Green与D. J. Langridge, 2013--2017, *Mass Spectrometers Comprising Accelerator
  Devices*, Micromass UK专利族
  [WO2013064842A3](https://patents.google.com/patent/WO2013064842A3/en)、
  [EP2774172A2](https://patents.google.com/patent/EP2774172A2/en)。可核验文本给出完整oa-reflectron布局的
  `V1...V5`、`L1...L5`实例，并称其对1 mm束实现三阶空间聚焦、理论FWHM分辨率约30,000；这证明加速器
  侧可以提供三阶空间聚焦自由度，但该实例包含完整漂移/反射/检测几何，且美国分案页面访问不稳定，
  因而不能据此声称存在脱离下游布局的通用加速器独立解，也不把未逐式复核的专利公式写入本项目理论。
- SIMION官方[FLY2 Individual Particles](https://simion.com/info/fly2_file.html#individual-particles)与
  [SIMION 8.2 (2020)](https://simion.com/info/simion82.html)：只支持官方restart/Program机制的实现事实，
  不支持三阶物理归因。

这些论文和专利支持低阶空间/速度聚焦、反射器补偿、加速器侧空间聚焦自由度，以及“分段推导、全机
联合闭合”的理论背景；它们不直接证明本机2.2 mm损失由某个三阶组件造成，也不支持“一般理论无法
聚焦更宽源”的结论。近三次标度、7.3%真实bundle新增量、ZERO-MATCH和dt/q排除均是本项目证据与项目
推断，不能倒写成文献事实。

## 最终交接边界

后续AI应先补全并独立核验affine `A3`，再完成自由度计数和全机`D1/D2/D3`方程；在第三自由度获批前
不得进入电压扫描。理论成功后按“全理想解析→官方restart理想场→真实场配对→独立数值收敛”的顺序
验证。任何阶段若只改善2.2 mm主峰却恶化1.0 mm、传输、多模、稳健宽度或物理包络，都不能称为解决。
