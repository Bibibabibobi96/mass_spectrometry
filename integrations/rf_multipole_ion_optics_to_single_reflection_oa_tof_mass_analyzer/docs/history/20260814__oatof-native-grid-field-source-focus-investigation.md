# oaTOF原生栅网、场、源与短长焦调查（2026-08-14）

DOC_STATUS: ARCHIVED_READ_ONLY

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

## 官方FLY2直接速度的表示界限与冻结门限

`pre_pulse_restart`不再使用ION的KE/azimuth/elevation间接表示，而只使用SIMION官方individual-particle
FLY2：`coordinates=0`、`tob=0`、质量/电荷/cwf/color、位置和`velocity=vector(...)`；连续前端ION路径
保持不变。N=1 smoke r01证明`sim_segment_global=1`使PA实例外的`segment.initialize`真实执行；r02进一步
证明FLY2直接速度在SIMION装载时仍发生内部speed-KE-speed数值往返。r02冻结目标速度为
`(4392.8416580436106, 0, -2.9323518410018137) m/s`，actual `source_release`为
`(4392.8416576899174, 0, -2.9323518407657133) m/s`：最大分量误差`3.53693e-7 m/s`，由实际速度经公共
particle-physics派生的能量误差`1.61032e-9 eV`；位置与canonical clock误差为0。SIMION原生`ion_ke`
仅记作diagnostic，不是能量第二权威；未采用数值预补偿。

因此正式合同在查看N=1000结果前冻结为：位置`1e-9 mm`、速度分量`1e-6 m/s`、canonical clock
`1e-9 us`、实际速度派生物理能量`5e-9 eV`，ordered IDs/N/SHA exact且禁止postselection。该调整只覆盖
官方FLY2表示界限，不改变源目标、加速/反射场、时钟、总体或分辨率门。

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

## 2026-08-15：direct baseline r02失败与r03 cohort语义修复

`pulse_resolution_direct_baseline_v5_r02`使用当前官方零宽透明栅网路径完成一次N=100真实SIMION输运，
但在baseline分析阶段失败关闭。源释放仍是同一有序ID 1--100，源表、canonical初态和固定脉冲时刻均
闭合；实际输运观察到`source_release/handoff/pre_pulse/pulse_eligible/outside=100/62/52/52/0`，而
旧D46986 checkpoint记录的是`100/75/66/50/16`。差异已在脉冲前、多极杆交接处形成，不是batch合并、
粒子ID映射、脉冲时钟或反射器结果筛选造成。旧checkpoint来自迁移前的frontend/Program实现，包含
`surface=fractional`及有厚度栅片；当前路径为官方一行零宽栅和`surface=none`。现有证据不能把差异
唯一归因到某一片栅网，但足以否定旧四层cohort作为当前官方路径的严格运行权威。

r02 parent run为
`20260815_160000__sim__cross__pulse-direct-real-rr__n100__r02`，失败manifest SHA-256为
`D9220D63AB56B4A607668652A55730DD09CDB0BC26A06D007A24666BA5C3106C`；campaign SHA-256为
`E43CAA2987BE0A5D7EA2FA9131B2892FF77F06EE89E9E91495AEED3D1C3361CE`。它保持失败历史证据，不能晋升
baseline result。该次官方构建已按内容身份发布frontend/overlay cache，键分别为
`01c205c64fc144710678bf823e3ed3852c28ea2992c6c14064ca2a53f4515309`和
`4dd7151d698f812ca60009c6e6434801ace6a247a8b6ff6e3c088aee25f12738`。

r03只修复身份和cohort权威语义，科学输入不变，PA策略恢复`require_existing`并预期精确命中上述已发布
cache。`pulse_resolution_execution_mode`是唯一控制权威：baseline派生
`establish_observed_authority`，resolved population只预先冻结`population_count=100`，不得预填
pre-pulse/eligible/outside分母；分析结果从当前日志发布四组有序ID、count、SHA及独立handoff，并由
self-SHA闭合。candidate派生`require_frozen_baseline_authority`，只能从已验证baseline receipt取得四组
成员并逐组精确复用。D46986仅以`rf_oatof_historical_migration_reference`保留，baseline只用它验证
未变化的source-release 100、源身份和固定脉冲合同，不再验证旧`66/50/16`。

r03 campaign为`pulse_resolution_direct_baseline_v5_r03`，run为
`20260815_160000__sim__cross__pulse-direct-real-rr__n100__r03`，campaign SHA-256为
`AFA49EE4D055C11B705CC43E06AAE0B9A1B4CDA476591982BE8410A34F95B1A6`。solver-free联合target为
74/74 PASS；integration全套为378/378 PASS；正式`ValidateOnly`通过source binding、prepare、composition
plan和integration validation，且临时目录自动清理。本阶段未运行r03 SolverAuthorized或SIMION，因此
没有新分辨率结果，也尚未把r03 observed cohort晋升为候选配对权威。

### r03/r04执行失败与r05恢复

唯一一次r03 `SolverAuthorized`在8.1 s内失败于single-flight runner的solver前preflight。parent/child
manifest均为`failed`，SHA-256分别为
`B35AAB6BF95B43EA2CF9E42CDD685B7E8D7D65CDD53BDEA221AD493A25A40FFE`和
`346C1E06111325955343D618CC77B7563E156F0E3CB1D74226B6FD1716D2AED6`。PowerShell StrictMode直接读取
baseline按合同合法缺省的`paired_cohort_authority`属性，因属性不存在而终止；失败发生在cache lookup、
SIMION Fly、build和refine之前，没有产生observed authority或baseline receipt。r03身份永久封存，不得
原样重试。

最小修复改为通过`PSObject.Properties`检查可选属性：`establish_observed_authority`必须不含paired
cohort，`require_frozen_baseline_authority`必须含paired cohort；baseline的eligible denominator保持
缺省，不回填占位值。r04 campaign/run只将r03身份改为r04，全部科学源、场、几何、时钟、数值、N、
cache策略和cohort语义均不变；campaign SHA-256为
`3A883CBBD8C098B350D2A6123D831438E85FD8E3C791B03BC8811562747441FD`。

r04公开`PrepareOnly`通过prepare、composition和adapter，但按现有架构在adapter退出，不进入runner或
cache lookup。没有为本缺陷新增CLI或第二执行路径。精确PowerShell回归绑定r03 frozen population SHA
`1D8D54EEEA5BB9B98A6BF631825AF0FE383523259444A3F6C95A9CE92794FC36`，在StrictMode下验证缺省paired
cohort与eligible denominator合法。官方`Test-RfReusableCacheEntry`以`preserve`模式逐文件验证frontend
`01c205c64fc144710678bf823e3ed3852c28ea2992c6c14064ca2a53f4515309`和overlay
`4dd7151d698f812ca60009c6e6434801ace6a247a8b6ff6e3c088aee25f12738`的manifest、role、project、key、
文件大小和SHA，二者均PASS；该只读harness验证cache完整性，但不冒充完整runner preflight或Fly。

随后唯一一次r04 `SolverAuthorized`在8.2 s内同样于single-flight runner的solver前preflight失败。
parent/child manifest SHA-256分别为
`AE7EA2BDF83B26C4B515209E287C73A1068DCBB8B989958E20F8D9F86A19E1C6`和
`C62C237CB0DC2F7FEF43CA7066B6BEFC463D91E9731220BA31557762451D250A`；child明确记录
`frozen_input_snapshot_completed=false`且两项cache disposition仍为`pending`，故这次也没有cache lookup、
SIMION Fly、build或refine。根因是registration-source组装处仍用点属性访问合法缺省的
`paired_cohort_authority`，与r03属于同一可选字段的第二个访问点。r04身份永久封存，不得原样重试。

完整逐项审计runner、adapter、analyzer和registrar中的`paired_cohort_authority`后，唯一剩余不安全访问
改为复用runner前部取得的`PSObject.Properties`对象：baseline省略该键，只有
`require_frozen_baseline_authority`候选才写入。r05 campaign/run只将r04身份改为r05，全部科学源、场、
几何、时钟、数值、N、cache策略和cohort语义不变；campaign SHA-256为
`10EB3DAE1998403F2DC158B1CFDD18C8BCADE806A4290ADF24FE880080776B95`。精确r04 frozen-plan动态harness在
PowerShell StrictMode下走到registration-source组装，并调用官方`Test-RfReusableCacheEntry -InvalidEntryAction preserve`
验证上述frontend/overlay条目，结果均PASS。该harness仍不冒充实际runner或Fly；r05尚未执行
`SolverAuthorized`，因此目前没有新的observed cohort、baseline receipt或分辨率结果。

### r05 cache完整性失败与r06安全复用修复

r05唯一一次`SolverAuthorized`在16.7 s内被`require_existing`完整性门禁阻断，未进入SIMION Fly、build或
refine。parent/child manifest SHA-256分别为
`EA0455460DAF33E8D9DD9CB20133F4FB63BEE4D88F43903BF0F6BB55276C588B`和
`490C92EC707B7DE15AB72EB93410A43FBB22116FCEC5B092DD4333C894351A10`。frontend cache
`01c205...`仅`frontend.pa19`偏离manifest：期望`88CE8E...EA446`，实际`82B7A8...6189`，尺寸不变；
全族其余文件和overlay `4dd715...`均通过逐文件SHA。坏文件与另一受验证副本仅一个8-byte对齐位置的一字节
不同。现有证据高度支持overlay basis构建时供应商PA API直接打开不可变frontend cache原件产生副作用，
同时排除了frontend/overlay当前共享NTFS inode；不把未记录写入者提升为绝对因果结论。

r06使所有SIMION消费者只打开`run/simion/frontend_cache_copy`中的普通物理副本，overlay/downstream
cache与runtime/publish staging之间也统一使用`Copy-Item`，runner不再含PA hardlink。overlay cache身份改为
绑定完整frontend cache key，而非仅绑定`pa0` SHA；构建期SIMION访问结束后、Fly前调用既有官方全payload
verifier复核源frontend cache。r06相对r05只改变campaign/run身份和PA policy
`require_existing -> build_and_publish_if_missing`，campaign SHA-256为
`1720764541ADCDC65C808CAA81282BC5A3EE967179AE83A9C427E9663CDC8921`。solver-free target、相关integration
分别`68/68`、`32/32` PASS，公开`ValidateOnly` PASS；尚未运行r06 `SolverAuthorized`。损坏frontend和
tainted-provenance overlay两个旧cache的永久删除仍等待针对具体目录的明确批准。

## 2026-08-15：N=100 direct field matrix正式登记结果

本节只登记功能与预注册promotion结果，不增加物理解释。四行使用同一真实八极杆源、r09 observed cohort、
pulse-effective时钟、官方零宽透明栅网、真实反射器合同和N=100 ordered prefix；四行均为
source/handoff/pre-pulse/eligible/outside/detector=`100/62/52/52/0/52`，eligible到detector为`1.0`。
frontend/overlay分别命中`01c205c64fc144710678bf823e3ed3852c28ea2992c6c14064ca2a53f4515309`和
`f1b4d3fc449c8f350faa9a33615156249f97588f797d9686ff7fce046f92fa40`，没有build/refine。

|序列|规范场配置|run|R|direct FWHM (ns)|mode|promotion|功能/publication|
|---:|---|---|---:|---:|---:|---|---|
|1|`accelerator_real_pa`|`20260815_160000__sim__cross__pulse-direct-real-rr__n100__r09`|4458.135378|3.496136959|1|baseline，不晋级|PASS|
|2|`accelerator_ideal_stage1_real_stage2`|`20260815_160100__sim__cross__pulse-direct-ideal-s1-real-s2-rr__n100__r03`|4343.205166|3.588638942|1|reject|PASS|
|3|`accelerator_ideal_stage1_stage2_real_reflectron`|`20260815_160200__sim__cross__pulse-direct-ideal-s1s2-real-rr__n100__r03`|4545.698265|3.428833509|1|reject|PASS|
|4|`full_domain_piecewise_ideal_field`|`20260815_160300__sim__cross__pulse-direct-full-domain-ideal__n100__r03`|4545.698265|3.428833509|1|reject|PASS|

功能贯通为`3/3 candidate PASS`，promotion为`0/3`。seq2的FWHM/sigma相对改善为
`-2.645834%/-0.686656%`；seq3和seq4均为`1.925080%/1.514362%`，均低于预注册15%双门。

- baseline result文件/self-SHA：`EA4BB4084A754F5442B016B7D3744141A107C291B8DDABA8CCD9C193D759E37E` /
  `B515E431A076E57E00324B80CC1D3FEF031CD8B882CB3B65C2E48531A7B69E7B`；parent/child manifest：
  `06134C747DD095092B8BD053AED7C213A877DA325B34DF0125D13DF156E9B12A` /
  `54E67E3DEC5BA4D8B649929A7EB08FC05E668187F485A99EB132A773F54D0AE5`。
- seq2 result文件/self-SHA：`C7EE0313F74CE8D59BFBD06758873AEC041202F5BFD7499C151052D79204BF90` /
  `1FD9E69AAFD95F5BE44717B90431E758CC7F03D12CBA442B34E9073A3C973C6A`；promotion文件/self-SHA：
  `CDC12B62F4ED5403E3D9913188EF287E0F331FC83DA360C55091BAC5D95DD81B` /
  `B0AED58E93E15F4B1D0EA64FEE16A152F7853A824AAA07385E4255AF43876D8B`；parent/child manifest：
  `2F06062F968AC173C426AA9A85949B10344EA0B2123A49D72038D272D4F1D7C6` /
  `F8C68AE694639312028F16CA4EC3EBA1A070ACDC694070F77CD14AF9409DC278`。
- seq3 result文件/self-SHA：`0DD8A05402A95EF892680977074EA8188F24EB83022001458C48DD776997AAC6` /
  `206256D2864B6177CA6DB8ECB98BE53451C41F796D01E81D93AE69E16E362E09`；promotion文件/self-SHA：
  `99C7505A8850430A21E8B98A1B1B7EDAB30A0E12248380B8CEF45BAB8641CE18` /
  `1EBC04BFB1268519B5BB11F711C9268C7037C8337CCD5661E4381C7644DC945C`；parent/child manifest：
  `73BDBE390D372716AC0C095C9210233CA50194295C9F43C5ACCB347545E1860C` /
  `E30AC6313A2C3EC65D365D4E04DE6A7F9E76E4D837EA1F1DFB6B03D30A0544FB`。
- seq4 result文件/self-SHA：`9CBD04867CE6EA846A09940CCC9097E0AC0980BC3B3A851D537057E52A2318A7` /
  `223F6D2EF03ECA35CFA157E446E29E92F8B42D4D8E5898BFC2E0DE6CDDDCCA95`；promotion文件/self-SHA：
  `023901D41E76B2E8322997F8BA891847A84CCB92CF491A9841BCE1CF230FB3A1` /
  `42AB994A85EE20CCB17FC87EC79DDEF94954CECB78AB46A3AD221211AAC8B903`；parent/child manifest：
  `7E0BAF0B1F241A49225D290ECAA6D9CBC642E75158486CF21EE3B7E7FC1E16DB` /
  `1A3FBF6D60DF99E4051BBEF90114DC897136AC0A56EC55A9A70CFB9D9A3AF971`。

全部result和promotion receipt的claimed self-SHA均与canonical重算一致。
