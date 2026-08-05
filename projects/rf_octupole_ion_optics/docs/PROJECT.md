# RF八极杆离子光学项目状态

## 当前结论

2026-07-28起，八极杆三种传输/轴向加速工况已改为一个机械base、一个变量目录、一个优化包络和一个
typed operating mode registry。三个规范profile由公共编译器在内存中只施加电气模式，机械实体、
接口、RF和粒子源保持严格相同。当前三个N=100 baseline均已完成COMSOL与SIMION真实运行并以
100/100及相同交接粒子身份闭合功能分类；连续数值、Candidate和Formal资格仍未闭合。

四、六、八极杆共同的临时下游工程方向由
[`engineering_progression_acceptance.json`](../../../common/multipole/engineering_progression_acceptance.json)
统一记录；本项目只声明适用性，不复制阈值、状态或判定。后续先复用现有SIMION状态并只补最小相邻
加密臂；任何工程PASS都不得改称数值收敛或求解器等价。

旧的design/runtime alias `baseline_finite_3d`和`exit_aperture_plate_acceleration_reference`已经退役；
solver numerics内的`baseline_finite_3d`仍保留为数值档身份，不构成额外实验arm。

## 机械与电气合同

- 八极杆：`radial_order_n=4`，8根圆柱杆，`r0=4 mm`，杆半径比`0.5`。
- 杆轴向范围：`0..79.6 mm`。
- 四个导体段：`[0,19.6]`、`[20.0,39.6]`、`[40.0,59.6]`、
  `[60.0,79.6] mm`；三个间隙均为`0.4 mm`。
- 释放面：`z=-1.5 mm`。
- 入口带孔接口板：`z=-1.0..-0.5 mm`。
- 出口带孔接口板：`z=80.1..80.6 mm`。
- 规范交接面：`z=80.6 mm`；近接口统计面：`z=81.1 mm`。
- `no_acceleration_full_length`：四段`0/0/0/0 V`，出口板`0 V`。
- `segmented_rod_axial_acceleration`：四段`0/-1/-2/-3 V`，出口板`-3 V`。
- `exit_aperture_plate_acceleration`：四段`0/0/0/0 V`，出口板`-3 V`。

RF为1.1 MHz余弦、每组零到峰值139.81792 V；源为100 amu、+1、2 eV。碰撞、空间电荷、磁场、
支撑、公差和真实下游器件仍未进入本机械base。

## 数值预登记

每个规范mode使用相同N=100源和三个runtime层级：

|层级|COMSOL局部最大单元|COMSOL步/周期|SIMION cell|SIMION步/周期|
|---|---:|---:|---:|---:|
|baseline|0.5 mm|80|0.4 mm|40|
|spatial refined|0.35 mm|80|0.3 mm|40|
|temporal refined|0.35 mm|160|0.3 mm|80|

空间比较只改变空间离散；时间比较在已选细网格上保持空间离散不变，只改变每RF周期步数，符合根
`docs/VALIDATION_METHODS.md`的顺序门禁。没有物理、下游或误差预算支持
时不得发明百分比作为PASS阈值，结果固定为`INCONCLUSIVE`。无加速N=100 baseline双求解器pilot
和空间敏感性pair已经完成，各档两边均为RF 100/100、zero-RF 21/100且粒子身份一致；当前只授权
固定0.35/0.3 mm的时间敏感性pair也已完成；SIMION时间RMS半径变化约`0.0033%`，COMSOL约
`2.19%`，最终跨求解器RMS半径/发散角差约`3.85%/4.62%`。功能传输闭合，连续结果仍为
`INCONCLUSIVE`，不得增加第四档。最大实测为572.776 s、1.047 GB瞬态目录和8.673 GB进程树内存；
2026-07-31无加速定向跟进完成SIMION A/R/Z/I/T五臂和COMSOL局部0.20 mm的160→320步时间pair。
SIMION径向/轴向RMS半径变化为`3.066%/0.309%`，I→T为`0.000133%`且只在固定分箱下稳定；
COMSOL时间变化为`3.980%`且仍跨固定分箱。功能保持100/100，连续结论为
`INCONCLUSIVE_NUMERICAL_CONVERGENCE_NOT_ESTABLISHED`；机器身份见
[`followup_result.json`](../config/qualification/no_acceleration_followup/followup_result.json)。
分段杆轴向加速N=100 baseline已在两求解器保持100/100传输和精确粒子身份；SIMION空间档也
保持100/100，RMS半径、发散角和平均能量相对baseline分别变化约`2.39%`、`7.98%`和`0.196%`。
COMSOL空间档在`MESH_COMPLETE`后以19.180 GB超过17.180 GB进程树帽，记为
`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`，不重跑、不抬帽。
出口孔板加速N=100 baseline已在两求解器保持100/100传输和精确粒子身份；SIMION空间档也
保持100/100，RMS半径、发散角和平均能量相对baseline分别变化约`0.67%`、`6.72%`和`0.80%`。
COMSOL空间档在`MESH_COMPLETE`后以17.181 GB超过17.180 GB进程树帽，记为
`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`，不重跑、不抬帽。时间档和完整N=1000资格矩阵仍未授权；
2026-08-04仅执行一个分段加速N=1000 oaTOF孔径诊断，不扩展其资格。出口孔板功能能量增益使用下游terminal/census状态；跨求解器
连续诊断使用规范handoff状态，两者不得混作同一观察面。出口孔板身份和资源结论登记在
`../config/qualification/n100_exit_aperture_plate_acceleration_qualification.json`。
完整身份登记在
`../config/qualification/n100_no_acceleration_qualification.json`。
分段杆轴向加速身份和资源结论登记在
`../config/qualification/n100_segmented_rod_axial_acceleration_qualification.json`。
2026-07-31声明式SIMION H15 N=100三模式对照中，出口孔板加速相对无加速把中心化空间/角RMS降低
`0.0995 mm/0.6912°`；相对分段加速，空间RMS低`0.1563 mm`，但角RMS高`0.6438°`。它避免了同一
H15条件下分段加速空间RMS略增的信号；统一九臂证据见
[`../../../docs/history/20260731__multipole-three-mode-h15-n100.md`](../../../docs/history/20260731__multipole-three-mode-h15-n100.md)。
该结果只用于工程取舍，不改变数值资格。统一图组和机器摘要已发布为成功analysis run
`20260731_223000__analysis__python__multipole-three-mode-h15-n100`，不再依赖scratch。
同日另以当前ACTIVE六指标工程合同正式评价无加速T→H15相邻横向加密：质心位置、中心化空间展宽、
平均方向、中心化角展宽、平均能量和中心化能量展宽差依次为`0.003254 mm`、`0.017724 mm`、
`0.161877°`、`0.017208°`、`0.001544 eV`和`0.009394 eV`，机器结论为`PASS`；analysis run为
`20260731_223300__analysis__python__oct-simion-t-to-h15`。它只允许工程推进，数值收敛仍为
`DEFERRED_NOT_WAIVED`。包含本项目在内的家族18项既有比较也已按ACTIVE合同重分析为18/18 PASS，
统一记录见
[`../../../docs/history/20260731__multipole-engineering-reanalysis-18-comparisons.md`](../../../docs/history/20260731__multipole-engineering-reanalysis-18-comparisons.md)。
随后统一oaTOF屏蔽罩终端H15 campaign完成9/9；八极杆无加速/分段/终端阶跃的handoff分别为
`59/41/70`，穿过4 mm厚矩形孔后的terminal分别为`43/34/62`。终端阶跃同时给出本项目最高terminal
透射`62/100`、最高terminal/handoff`88.6%`和最小handoff中心化空间RMS`0.3215 mm`；分段模式的
中心化角RMS更小，为`2.1969°`。完整对照见
[`../../../docs/history/20260731__multipole-oatof-shield-terminal-h15-n100.md`](../../../docs/history/20260731__multipole-oatof-shield-terminal-h15-n100.md)。
这是新矩形厚孔拓扑下的N=100事后工程结果，不可与旧独立末端板H15表作仅模式变化的配对比较，也不
改变数值资格。

2026-08-04分段杆轴向加速N=1000 SIMION诊断得到459/1000 canonical handoff；固定该459粒子群比较
oaTOF接口孔后，1.0×0.9 mm与0.5×0.5 mm分别有396和90粒子穿过接口并全部到达检测器，总传输率为
39.6%和9.0%。规范direct-KDE FWHM分别为2.195和3.549 ns，R分别为6979和4317；小孔没有改善
分辨率。完整空间分布、理想N=1000基线对照、限制和运行索引见integration文档及analysis run
`20260804_132000__analysis__cross__oct-aperture-comparison__n1000`。该单样本、单网格、两孔径结果保持
`INCONCLUSIVE_DIAGNOSTIC_ONLY`，不闭合数值资格或下游接受尺度。

同日新增的SIMION整体前端单流程把八极杆、屏蔽过渡和oaTOF加速器合并为一个PA，并在同一个粒子飞行
中继续使用正式飞行管、反射器和探测器。后续几何复核发现旧PA的圆罩到方罩过渡没有真正封闭，且使用
了已取消的3 V屏蔽边界；该run及以下数字只保留为被取代诊断。N=1000曾得到`571→491→491`，总检测传输49.1%；相对
当前分阶段`459→396→396`增加112个handoff和95个检测粒子。共同检测粒子368个，检测时刻RMS差
2.332 ns、检测面xy位置RMS差0.754 mm。共同脉冲原点下direct-KDE结果为单流程2.702 ns/R=5769，
分阶段1.549 ns/R=10063；旧分阶段2.195 ns/R=6979使用grid2重启`TofUs`，不与前者混用。完整合同、
限制和证据见integration文档及analysis run
`20260804_143000__analysis__cross__single-vs-staged__n1000`。当前代码已改用公共0 V圆套筒+带孔法兰闭合
连接器；旧49.1%/R=5769不得转用于新连接器，当前结果只取自下述同母样本重跑。

新0 V闭合连接器的同母样本四PA单流程已完成。1.0×0.9 mm与0.5×0.5 mm分别得到
`1000→583→495→495`和`1000→261→200→200`（handoff、脉冲前、检测），总检测传输49.5%和20.0%。
小孔200个检测粒子全部属于大孔495个检测粒子；大孔全体/小孔全体R为12841/14042，但大孔中同一
200粒子群已有R=14088，因此9.36%的表观改善来自粒子选择，小孔对共同粒子的净场效应为R降低0.32%。
两峰仍为双模态、右偏诊断峰。机器结果和六面板图见integration analysis run
`20260804_182000__analysis__cross__single-flight-aperture-comparison__n1000`；该单样本、单离散结果仍为
`INCONCLUSIVE_DIAGNOSTIC_ONLY`，不改变本项目数值资格。

2026-08-05在相同N=1000母样本、接地闭合连接器和单一`+3 V`入口参考套筒下继续测试0.5×0.2 mm孔。
真实SIMION重试run `20260805_100000__sim__simion__rf-oatof-single-flight-gap0__n1000__r02`得到
`1000→0→0→0→0`，全部粒子在连接端面终止，因而没有TOF峰或分辨率结果。该PA的0.2 mm cell恰好
等于孔高；两条孔边落在相邻整数z网格节点而孔中心位于半格，`notin`减除没有留下内部开孔节点。
只读PA截面探针确认法兰首个内部截面的孔邻域为`OPEN=0`，因此零传输来自当前离散PA把孔封闭，不能
解释为机械孔物理截止。共享SIMION开孔入口随后改用不改变机械尺寸的`notin_inside_or_on`，同时把
小于一格的孔失败关闭、非整数倍/边缘未对齐写为机器警告，并要求实际精炼PA在Fly前通过贯通列和孔外
接地guard审计。修复后的同网格run
`20260805_100000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03`在0.2 mm cell下得到PA贯通列
`6/6`、guard PASS，census为`1000→261→201→201→201`，证明假开孔缺陷已解除，无需用0.1 mm网格
作为功能修复。201个检测粒子的direct FWHM为2.511 ns、R=14089，但孔宽2.5格且y边缘未对齐，仍须
相邻网格验证后才能作精度、孔径优劣、Candidate或Formal结论；`r02`保留为明确负证据。

同一1.0×0.9 mm基准随后以495个脉冲前/检测器共同粒子完成七臂受控理想条件反事实。restart control
相对连续链的逐粒子检测时刻RMS差0.01981 ns、FWHM差−0.288%；只把全局z分布匹配到理想源使
direct-KDE FWHM从2.7474降至2.2155 ns（−19.36%），只匹配x/y为2.7542 ns（+0.25%），去除脉冲前
能散为2.7469 ns（−0.02%）。当前z--vz线性相关为0.8515；在保持vz均值和标准差时消除该相关反而使
FWHM增至3.8820 ns（+41.30%），说明它主要提供补偿而不是制造展宽。把z/vz同时压到均值的非工程化
上限得到0.02868 ns，只支持“主要剩余敏感性位于加速方向高维相空间及其非线性结构”，不能作为可实现
分辨率。机器证据为run
`20260804_210300__sim__simion__rf-oatof-resolution-counterfactual__n1000__r02`；方法、完整七臂表和
声明边界见integration文档。结论保持`CONTROLLED_COUNTERFACTUAL_DIAGNOSTIC_ONLY`，不闭合数值、
统计、Candidate或Formal资格。

2026-08-05把2 eV源的分段轴向电位降从`3→0 V`提高到`8→0 V`，N=1000八极杆handoff平均能量
达到9.9885 eV。1.0×0.9 mm、0.2 mm cell的连续四PA联合链得到
`1000→711→612→612→612`，相对5 eV对照`1000→583→495→495→495`把总检测传输从49.5%提高到
61.2%。全队列handoff正交加速方向角度σ从1.4417°降到1.1546°，脉冲前σz从0.49365降到
0.46245 mm；固定共同检测的271粒子群中两者分别从1.0262°降到0.6679°、从0.48702降到
0.27697 mm，确认纵向增能降低角度并在脉冲面降低空间展宽。direct-KDE FWHM只从2.7554降到
2.7299 ns，脉冲参考R仅从5656.7升到5709.4；共同群R也只提高1.54%，因此没有得到“分辨率明显
提高”。共享连接profile、状态派生脉冲、run索引、失败重试和完整限制见
[`../../../docs/history/20260805__octupole-10ev-single-flight.md`](../../../docs/history/20260805__octupole-10ev-single-flight.md)。
本结果保持`INCONCLUSIVE_DIAGNOSTIC_ONLY`；绝对instrument-clock R会随脉冲提前改变，不作为oaTOF
分辨率结论。

2026-08-03补齐同一终端和H15设置下的无加速5 eV初始源后，八极杆末端加速相对分段加速把
handoff透射提高0.29、空间RMS降低`0.0464 mm`，但角RMS增加`0.6952°`；单纯提高初始能量使透射
从0.59降至0.39，未形成准直收益。完整12臂对照见
[`../../../docs/history/20260803__multipole-four-mode-source-energy-h15-n100.md`](../../../docs/history/20260803__multipole-four-mode-source-energy-h15-n100.md)。
COMSOL/SIMION分别受1200/720 s、2 GiB瞬态目录、16 GiB进程树内存、8 GiB最低
可用内存、25 MiB compact保留和零自动重试约束；其他runtime由
[`../config/qualification/engineering_budget.json`](../config/qualification/engineering_budget.json)
失败关闭。

N=100 baseline runtime key直接使用三种完整mode ID；加密key分别追加`_n100_spatial_refined`和
`_n100_temporal_refined`。三个N=1000统计runtime追加`_n1000`并绑定同一母样本的N1000档。
solver numerics ID与四/六极杆统一为`baseline_finite_3d`、`n100_spatial_refined`和
`n100_temporal_refined`。

另有独立的无加速混合网格粒子收敛预登记：
`../config/qualification/comsol_hybrid_no_acceleration_particle_convergence_preregistration.json`。
它登记`0.25 mm/160`参考、`0.20 mm/160`空间加密和`0.25 mm/80`时间粗档，使用独立工程预算。
六极杆混合源下游A/B在2026-07-30满足预注册扩展规则后，只授权首个参考arm用于生成八极杆
oaTOF source revision。参考run
`20260730_231701__sim__comsol__oct-noacc-hybrid-exit025-t160__r01`为100/100传输；接入固定oaTOF链后
得到`100→46→34→34→10→10`，相对旧COMSOL源为`0,-12,-2,-2,-6,-6`。15个共同局部出口粒子的
位置、速度、时间、能量RMS差分别为1.1674 mm、2357.1 m/s、0.07206 µs和107.56 eV。空间和时间arm仍
未授权，且不继承六极杆结果或收敛结论；当前差异只支持source revision敏感性诊断。

三模式发散实验的方法来自`common/multipole/three_mode_dispersion_contract.json`。本项目已登记
acceptance、effect-resolution、engineering-budget和三份电压合同，但前两者尚无可辩护尺度；它们
只防止事后挑阈值，不授予资格。项目preregistration不是公共正式binding：只有真实solver run已发布
三份canonical handoff-state并冻结对应numerics SHA后，才生成一个solver专属正式binding；缺少真实
状态固定`FAIL_CLOSED_NO_FORMAL_BINDING`。
现有preregistration没有在这些run之前冻结bootstrap seed与resample数，因而不得把运行后选择的
bootstrap设置伪称为预注册。公共正式发布入口对此固定失败关闭。2026-07-29已另行发布COMSOL和
SIMION两份`POSTHOC_DESCRIPTIVE` binding和报告：只含点估计，不计算bootstrap、不评价资格。若未来
需要统计分散证据，必须先完成包含bootstrap设置的新预注册，再执行对应的新run。

## 权威入口

- [`../config/requests/mechanical_base.json`](../config/requests/mechanical_base.json)
- [`../config/design_variables.json`](../config/design_variables.json)
- [`../config/optimization_envelope.json`](../config/optimization_envelope.json)
- [`../config/operating_modes.json`](../config/operating_modes.json)
- [`../config/design_profiles.json`](../config/design_profiles.json)
- [`../config/runtime_profiles.json`](../config/runtime_profiles.json)
- [`../config/particle_source_profiles.json`](../config/particle_source_profiles.json)
- [`../config/comsol_solver_numerics.json`](../config/comsol_solver_numerics.json)
- [`../config/simion_solver_numerics.json`](../config/simion_solver_numerics.json)
- [`../config/qualification/n100_convergence_preregistration.json`](../config/qualification/n100_convergence_preregistration.json)
- [`../config/qualification/comsol_hybrid_no_acceleration_particle_convergence_preregistration.json`](../config/qualification/comsol_hybrid_no_acceleration_particle_convergence_preregistration.json)
- [`../config/qualification/three_mode_dispersion_preregistration.json`](../config/qualification/three_mode_dispersion_preregistration.json)
- [`../../../common/multipole/engineering_progression_acceptance.json`](../../../common/multipole/engineering_progression_acceptance.json)
- [`../analysis/run_finite_3d_transport.ps1`](../analysis/run_finite_3d_transport.ps1)
- [`../analysis/run_simion_finite_3d_transport.ps1`](../analysis/run_simion_finite_3d_transport.ps1)
- [`../verify_project.ps1`](../verify_project.ps1)

旧的baseline/no-acceleration/exit-aperture-plate request及其专属catalog/envelope已在活动消费者
归零后退出；当前三模式只使用单一`config/requests/mechanical_base.json`与typed operating-mode
registry。旧finite-3D快照及resolver已在消费者迁移到current合同后退出。
`config/resolved_design_no_acceleration_full_length.json`是无加速规范profile的具名发布视图；其他模式
在runtime解析时由同一base和typed registry生成。L1/L2/L3统一通过current resolver/compiler取值，
历史baseline和无模式名的重复resolved发布物已经退出；旧格式reader仅用于历史记录复核。

## 未决

1. 出口准直筛选按[通用出口相空间方法](../../../docs/multipoles/exit_phase_space_control.md)执行：以既有
   `segmented_rod_axial_acceleration`为首选基线，在固定总电位差和非变化合同下优化分段电位分配；
   canonical handoff为主评价面，杆端只作边缘场诊断，terminal传输和损失作为硬约束。候选通过该筛选
   后才运行完整oaTOF链。
2. 为接受尺度绑定真实下游器件的孔径/相空间预算，或建立可审查的项目误差预算；此前只能报告
   `INCONCLUSIVE`。
3. 若批准混合网格粒子收敛活动，严格按预登记的参考、空间、时间顺序执行；任一资源或结构门禁失败即停止。
4. 若推进连续量数值资格，为资源受限的加速模式建立有依据的新预算或替代离散策略；不得事后抬帽。
5. 若推进Candidate/Formal，再建立机械制造基线、GUI/CAD同步和N=1000统计证据。
6. 碰撞冷却和真实下游连接保持独立workflow，不由无碰撞三模式结果代替。
