# RF多极杆离子光学到单次反射oaTOF质量分析器集成

## 当前身份与边界

本目录是四、六、八极杆离子光学到单次反射正交加速TOF质量分析器的唯一连接实例层。
[`connection_profiles.json`](../config/connection_profiles.json)是连接拓扑的唯一机器权威；调用者必须显式提供
`ConnectionProfileId`。解析后的 connection 决定刚性位姿、连接器、公共电位、时钟和场责任区，运行器不得再消费
connector case 或由间隙推断拓扑。

多极杆族到oaTOF的活动workflow使用三个模式中性的直接对接profile：

- `rf_quadrupole_oatof_shield_terminal_direct_mating_gap_0mm`；
- `rf_hexapole_oatof_shield_terminal_direct_mating_gap_0mm`；
- `rf_octupole_oatof_shield_terminal_direct_mating_gap_0mm`。

当前唯一公开入口为
[`workflows/family_source_closure/execute.ps1`](../workflows/family_source_closure/execute.ps1)。
调用者只选择一份[`experiment_campaign.json`](../config/experiment_campaign.json)和其中的
`ExperimentId`；每行冻结上游run及其manifest、粒子状态、母样本和元数据，并选择一个模式中性的
连接profile。上游家族、COMSOL/SIMION来源、实际多极杆工况、母样本规模和resolved design均从冻结的
source run证据派生，不能在入口重复声明或由静态无加速配置回填。当前标准母样本规模为N=100或
N=1000，行内`particle_count`可以选择其非空子集，但不得伪装成新的母样本规模。

每个静态连接profile只声明`source_run_resolved_design`端口绑定；prepare阶段必须从该source run读取
resolved design，在父run中冻结`resolved_source_contract.json`和
`upstream_resolved_design.json`，再物化实际component port并解析连接。活动runtime binding只保存稳定
机制合同、家族handoff发布合同、source adapter和execution policy，不保存某个工况、求解器或N的
静态source/design。两个run-local输入及其SHA是下游三个阶段的必填冻结身份，不存在optional override、
repository fallback或无加速特例。

所有工况复用同一固定下游链：COMSOL `pre_pulse_interface_transport`、COMSOL `pulse_capture`、
SIMION `analyzer_transport`。内部phase不构成独立公开入口或资格声明。执行策略当前为compact、串行
商业求解器、失败即停、零自动重试；预算耗尽记为
`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`。稳定dependency inventory和implementation registry只描述
代码机制，粒子源与设计作为run-local科学输入单独冻结。

这些repository-text身份由`runtime/refresh_family_repository_bindings.py`单向编译。稳定合同、连接、
依赖、实现或source adapter变化后只运行一次该入口，不手改下游SHA；`--check`由静态测试失败
关闭。编译和运行时校验统一使用UTF-8/LF规范文本身份，因此Windows CRLF与GitHub LF checkout不会
产生不同仓库身份；artifact、run输入和求解器结果仍使用原始字节SHA，不改变历史证据语义。

## 多极杆族同源闭合状态与声明边界

以下2026-07-30至2026-08-02记录是迁移前source-revision工作流的历史诊断证据，不再描述活动入口。
当时三个family profile及其COMSOL/SIMION上游source branch完成机器合同、runtime binding、源状态和
母样本身份的预注册。2026-07-30，六个真实分支均通过同一公开入口和固定
COMSOL pre-pulse → COMSOL pulse-capture → SIMION analyzer链，并各自发布轻量父run：

|profile|COMSOL上游父run census|SIMION上游父run census|
|---|---|---|
|quadrupole|`20260730_135651__sim__cross__rf-quadrupole-source-comsol-gap0__n100`：`100→86→30→30→6→6`|`20260730_141137__sim__cross__rf-quadrupole-source-simion-gap0__n100`：`100→86→35→33→7→7`|
|hexapole|`20260730_141642__sim__cross__rf-hexapole-source-comsol-gap0__n100`：`100→83→49→49→14→14`|`20260730_142201__sim__cross__rf-hexapole-source-simion-gap0__n100`：`100→74→47→47→12→12`|
|octupole|`20260730_142640__sim__cross__rf-octupole-source-comsol-gap0__n100`：`100→58→36→36→16→16`|`20260730_143256__sim__cross__rf-octupole-source-simion-gap0__n100`：`100→60→43→43→5→5`|

这里的census依次为RF出口、oaTOF入口、脉冲时active、局部加速器出口、探测面crossing和hit。三个
COMSOL上游都冻结2026-07-28的`no_acceleration_full_length_n100_temporal_refined`源：global auto
level 6、工作区最大单元0.35 mm、160 steps/RF period，且`mesh_convergence=false`；它们不是后来
六极杆混合网格场pilot产生的粒子源。

统一paired analysis run为
`20260730_144531__analysis__cross__paired-family__n100`，结果SHA-256为
`A0A064641297E1A679BA1FEDB0BDAF1553E08431FF76D3F3A82E50FEBB3789AB`。两种上游源共享同一
N=100母样本SHA，但局部出口粒子集合和探测hit集合均不完全相同：

|profile|共同局部出口粒子|位置RMS距离 / mm|速度RMS距离 / m/s|时间RMS差 / µs|能量RMS差 / eV|
|---|---:|---:|---:|---:|---:|
|quadrupole|23|1.4250|2457.4|0.21313|91.16|
|hexapole|30|1.6579|2657.6|0.02394|99.43|
|octupole|21|0.9630|1812.5|0.09089|78.23|

analysis run及六个父run均保持`FUNCTIONAL_SCREEN_ONLY / INCONCLUSIVE_DIAGNOSTIC_ONLY`。当前没有
预注册接受阈值，N=100也不足以作分布资格判定，因此这些结果证明六分支真实链、身份和统一分析
已经贯通，但**不授予**逐粒子跨求解器等价、连续相空间等价、收敛、分辨率、优化、Candidate或Formal
资格。后续若比较混合网格粒子源，必须建立显式source revision对照，不能改写本次基准。

2026-07-30在读取新下游结果前预注册六极杆`hexapole_hybrid_reference`修订；其首次A/B满足冻结的
扩展规则后，又在读取四、八极杆结果前分别预注册`quadrupole_hybrid_reference`和
`octupole_hybrid_reference`。三个修订都只改变上游COMSOL source revision；下游三阶段、0 mm
connection profile、N=100母样本和compact预算不变。对应轻量父run为：

- 四极杆`20260730_232500__sim__cross__rf-quadrupole-hybrid-source-comsol-gap0__n100`；
- 六极杆`20260730_223347__sim__cross__rf-hexapole-hybrid-source-comsol-gap0__n100`；
- 八极杆`20260730_232501__sim__cross__rf-octupole-hybrid-source-comsol-gap0__n100`。

正式source-revision分析run为
`20260730_234500__analysis__cross__hybrid-source-revision__n100`，结果SHA-256为
`16645FD1C5478AC1456CD633E0F0BB958359F87592B44BC3B84CE18F80599574`。表中census仍依次为RF出口、
oaTOF入口、脉冲时active、局部加速器出口、探测面crossing和hit；括号内为混合源减旧COMSOL源：

|profile|混合源census（逐级差）|共同局部出口粒子|位置RMS / mm|速度RMS / m/s|时间RMS / µs|能量RMS / eV|
|---|---|---:|---:|---:|---:|---:|
|quadrupole|`100→86→30→30→7→7`（`0,0,0,0,+1,+1`）|30|0.2606|469.6|0.03649|17.36|
|hexapole|`100→67→39→39→9→9`（`0,-16,-10,-10,-5,-5`）|18|2.0564|3589.5|0.03558|141.35|
|octupole|`100→46→34→34→10→10`（`0,-12,-2,-2,-6,-6`）|15|1.1674|2357.1|0.07206|107.56|

这证明混合网格源会实质改变下游功能结果，尤其六、八极杆；它不证明新结果更准确。三个源参考run仍缺
空间/时间收敛闭合，N=100下游也没有预注册接受阈值，因此分析固定为
`INCONCLUSIVE_DIAGNOSTIC_ONLY`，不授予分辨率、优化、Candidate或Formal资格。任何加速多极杆实验
必须作为新的单变量预注册活动，不能把本次无加速source revision差异与加速电压效应混在同一结论中。

当时的source-revision发布器使用schema v2：每个profile显式绑定旧COMSOL、混合COMSOL和旧SIMION
三个父run，并发布三个`right_minus_left`有向pair、共同/差异粒子ID、局部加速器出口与探测器事件集合。
同一profile的三条series使用共同尺度和固定bin绘图，figure JSON、PNG及终态summary均进入manifest；
活动仓库内的实现、lock和预登记合同先逐字节冻结到`inputs/repository_snapshot/`。该专用发布器、
静态source/revision配置和对应schema现已由campaign-only入口取代并退出活动树；旧Git提交与artifact
保留原始实现和结果，不为其维持活动兼容代码。上述
`20260730_234500__analysis__cross__hybrid-source-revision__n100`仍是不可变schema v1历史artifact，
不得重写或作为新的派生run输入。

2026-07-31已用schema v2发布只读三源横向图组
`20260731_030000__analysis__cross__source-triangle__n100`，状态保持
`POSTHOC_DESCRIPTIVE / INCONCLUSIVE_DIAGNOSTIC_ONLY`。同日新增的上游无加速离散跟进臂没有冻结
新的`SourceRevisionId`、runtime binding或下游预登记，因此未接入本集成、未启动新的oaTOF商业运行；
不得用现有triangle替代这些新源的下游证据。

2026-08-02证据审计确认上述paired、source-revision与triangle旧分析run曾把活动仓库文件直接列为
manifest输入，因后续代码演进已不能逐字节复核这些记录。其数值只保留原有历史诊断边界，不得作为新
资格或派生run输入；完整异常清单与未来发布器闭合见
[`活动run与campaign证据审计`](../../../docs/history/20260802__run-campaign-evidence-audit.md)。

## 2026-08-03 当前工况接口求解器诊断

旧接口诊断曾把COMSOL的数值域下游边界`grid2 + 5 mm - 0.001 mm`与SIMION物理`grid2`面直接比较；
因此旧run `20260803_235000__sim__simion__oct-oatof-interface-timed__n41`和
`20260803_235100__sim__simion__quad-oatof-interface-timed__n94`中的212--224 eV差值不再是有效的
同面求解器证据。活动合同现把`local_accelerator_exit`唯一绑定到物理`accelerator_grid2`，禁止用数值
计算域边界替代。修正后的两条family链逐行确认COMSOL出口z均为`-0.12918680341103 mm`，随后使用
SIMION 2020真实矩形侧端口、同一脉冲时钟和同一接口PA重新独立运输。

新接口run为`20260803_235600__sim__simion__oct-oatof-interface-grid2__n41`和
`20260803_235700__sim__simion__quad-oatof-interface-grid2__n94`。表中差值均为SIMION减COMSOL，并在
同一个物理`grid2`面统计：

|源工况|入口 / SIMION出口 / COMSOL出口 / 配对|质心x差 / mm|质心y差 / mm|质心RMS半径差 / mm|平均x角差 / °|角度RMS差 / °|平均能量差 / eV|能量标准差之差 / eV|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|八极杆分段加速|`41 / 34 / 33 / 33`|-0.5956|+0.0143|-0.3365|-2.4013|-1.7663|+275.1783|+9.0710|
|四极杆无加速5 eV|`94 / 34 / 35 / 34`|-0.2671|+0.0464|-0.4966|-1.9905|-2.4197|+262.8350|+16.0413|

物理面不一致缺陷已经由合同、代码和真实双工况运行共同关闭，但同面结果仍明显超过当前多极杆家族
工程推进参考量0.2 mm、1°和0.2 eV，接口运输仍**没有闭合**。两种源的同向差异说明下一步应检查
SIMION与COMSOL的电极边界、理想栅网处理和脉冲电位时序；不能把任一求解器称为更准确，也不能据此
授予收敛、优化、Candidate或Formal资格。

修正后的family父run为`20260803_234000__sim__cross__oct-segmented-oatof-grid2__n41`和
`20260803_234100__sim__cross__quad-noacc-5ev-oatof-grid2__n94`；统一分析run
`20260803_235901__analysis__cross__grid2-aligned-current__n100`发布横向比较图及每个工况的六面板检查点
图。分析保持`POSTHOC_DESCRIPTIVE / INCONCLUSIVE_DIAGNOSTIC_ONLY`，不用于工况性能排序。

## 2026-08-04 中间求解器差异向oaTOF传播实验

控制实验固定同一份多极杆canonical handoff、连接合同、绝对脉冲时钟和物理`accelerator_grid2`面；
SIMION与COMSOL分别完成“连续接地屏蔽接口+脉冲加速器”运输。两个grid2状态随后都停止并重新释放到
同一套Formal oaTOF SIMION PA、IOB/Lua、trajectory quality和分析代码中，因而下游唯一物理输入差异
是grid2相空间。SIMION旧11列诊断输出由冻结的materializer按`particle_id`与原始canonical状态连接，
恢复为经过schema、时钟、派生能量和身份校验的完整grid2 canonical状态；没有沿用接口诊断run中grid2
之后的连续轨迹。

|源工况|中间求解器|handoff→grid2|grid2→检测器命中|handoff→检测器命中|检测器质心RMS半径 / mm|到达绝对时间标准差 / us|
|---|---|---:|---:|---:|---:|---:|
|八极杆分段加速|SIMION|34/41 = 82.93%|34/34 = 100.00%|82.93%|3.6670|0.001701|
|八极杆分段加速|COMSOL|33/41 = 80.49%|11/33 = 33.33%|26.83%|19.9551|0.161391|
|四极杆无加速5 eV|SIMION|34/94 = 36.17%|34/34 = 100.00%|36.17%|8.9632|0.017383|
|四极杆无加速5 eV|COMSOL|35/94 = 37.23%|3/35 = 8.57%|3.19%|15.7506|0.284719|

在grid2共同粒子上，八极杆/四极杆的配对位置向量RMS差为0.6768/0.5718 mm，速度向量RMS差为
5494/5502 m/s，能量RMS差为279.53/271.50 eV，绝对时间RMS差为0.02054/0.02267 us。传播到
共同检测命中粒子后，落点向量RMS差扩大到27.53 mm（11粒子）和24.60 mm（3粒子），绝对到达
时间RMS差为0.2013和0.3031 us。两工况中COMSOL命中的粒子均为SIMION命中集合的子集。

最终共同下游run为`20260804_095200__sim__cross__oct-comsol-grid2-common-oatof__n33`、
`20260804_094500__sim__cross__oct-simion-grid2-common-oatof__n34`、
`20260804_095000__sim__cross__quad-comsol-grid2-common-oatof__n35`和
`20260804_095100__sim__cross__quad-simion-grid2-common-oatof__n34`；配对分析run为
`20260804_100000__analysis__cross__middle-solver-grid2-propagation__n100`。结果说明当前中间求解器差异
足以主导oaTOF接受度和到达时间分布，但不能据此判定哪个求解器更准确。N不大、未做网格/时间步收敛，
且SIMION grid2事件速度取自事件步末、共同下游采用grid2重启；因此结论保持
`INCONCLUSIVE_DIAGNOSTIC_ONLY`。下一步必须用步长敏感性与“SIMION连续运输减grid2重启”回归量化这两项
边界误差，再检查电极边界、理想栅网和脉冲电位实现。

四条共同下游分支另由分析run
`20260804_100300__analysis__cross__four-grid2-oatof-six-panel__n100`分别发布六子图，固定显示grid2
横向状态、角度状态、能量分布、检测器落点、命中粒子分析器飞行时间以及粒子census。按
`R=t_mean/(2*2.35482*sample_sigma_tof)`得到的高斯FWHM代理如下；它使用oaTOF分析器飞行时间而不是
绝对仪器时钟：

|源工况|中间求解器|命中数|平均分析器TOF / us|样本σ / ns|高斯FWHM代理 / ns|R代理|
|---|---|---:|---:|---:|---:|---:|
|八极杆分段加速|SIMION|34|30.628606|2.3976|5.6458|2712.50|
|八极杆分段加速|COMSOL|11|30.476488|156.7572|369.1349|41.2810|
|四极杆无加速5 eV|SIMION|34|30.613046|26.3348|62.0138|246.825|
|四极杆无加速5 eV|COMSOL|3|30.410402|277.1785|652.7055|23.2957|

这些数值只是样本标准差对应的高斯FWHM代理，不是由收敛峰形直接测得的FWHM。尤其四极杆COMSOL
只有3个命中，R代理对单个粒子极敏感；所有四项均保持`UNQUALIFIED_DIAGNOSTIC_ONLY`，不得用于
Candidate、Formal或仪器分辨率声明。

### 理想源与实际加速器内分布造成的分辨率差距

分析run `20260804_101000__analysis__cross__ideal-actual-resolution-gap__n1000`把正式oaTOF理想源、两个
COMSOL脉冲左极限粒子群、四个grid2分支及检测TOF放在同一张六面板图中。理想基线为524 u、1000粒子、
同步释放的1 mm立方源和约5 eV初始能量；当前链为100 u多极杆输出在同一个绝对时刻脉冲抽取。

|脉冲时粒子群|N|σx / mm|σy / mm|σz / mm|平均初能 / eV|初能σ / eV|处于理想1 mm源体积|
|---|---:|---:|---:|---:|---:|---:|---:|
|理想源|1000|0.2876|0.2839|0.2887|5.00|0.42|100%（定义）|
|八极杆实际群|33|0.9305|0.5335|0.5354|5.11|0.04|2/33 = 6.06%|
|四极杆实际群|35|0.7943|1.2586|0.9742|5.00|0.06|0/35 = 0%|

当前群的平均初能与理想值相同且能散更小，所以初始5 eV能散不是主因。主要差异首先是抽取瞬间空间和
角度条件：八极杆σx约为理想的3.2倍，四极杆σy/σz约为理想的4.4/3.4倍；八极杆已有8/41粒子在
脉冲前撞失，四极杆为59/94。实际群的横向速度也不是理想输入的零角度条件：八极杆vy/vz样本σ约
84/84 m/s，四极杆约204/159 m/s。

该错配经过脉冲加速后转化为grid2角度和能量差。SIMION中间段的平均x角约2.85--2.90°，但角度σ仅
0.06--0.11°；COMSOL平均x角约4.89--5.25°且σ为1.39--1.69°，四极杆COMSOL的y角σ达到2.33°。
理想设计能量包络为1920--2080 eV；SIMION出口均值为2005/1937 eV，而COMSOL为1730/1674 eV，
已整体离开设计包络。位置依赖的抽取能量、非零入射角和更大的相空间相关性因此不能被只针对理想小源
优化的一阶/二阶时间聚焦同时补偿。

正式理想链1000/1000命中，直接KDE FWHM为0.893/0.749 ns，R为39938/47662；当前链的高斯FWHM
代理为5.65--652.71 ns，R代理为23.3--2712.5。差距还有三项次要但必须分离的因素：100 u当前离子的
TOF约30.5 us而524 u理想离子约71.35 us，同样的绝对时间宽度会给出更低R；当前COMSOL仅11或3个
命中，幸存者选择和小样本使峰宽极不稳定；理想值使用直接KDE，而当前值使用高斯样本σ代理，估计器并不
等价。因此图和数值证明“实际入口相空间严重偏离理想接受条件”，但尚不能把全部差距定量归因于源空间，
也不能用它判定SIMION或COMSOL哪一个更准确。

### 八极杆 N=1000 的 oaTOF 接口孔径诊断

分析run `20260804_132000__analysis__cross__oct-aperture-comparison__n1000`固定同一批八极杆
`segmented_rod_axial_acceleration` N=1000母样本、同一459粒子handoff、同一绝对脉冲时刻和同一
正式oaTOF下游，只替换接口孔径。1.0×0.9 mm分支为`459→396→396`，接口条件传输率86.27%，相对
母样本总检测传输率39.6%；0.5×0.5 mm分支为`459→90→90`，对应19.61%和9.0%。小孔检测传输仅为
标准孔的22.73%，未出现以传输损失换取峰宽改善的结果。

两条实际分支与正式SIMION理想基线均使用规范direct-KDE FWHM估计器。理想524 Da、N=1000基线为
0.749 ns、R=47662；100 Da实际链中，1.0×0.9 mm为2.195 ns、R=6979，0.5×0.5 mm为3.549 ns、
R=4317。小孔相对标准孔的直接KDE峰宽增加61.7%，分辨率降低38.1%。空间对照采用共同handoff状态到
脉冲左极限的无场弹道投影：全部459粒子的σx/σy/σz为0.943/0.568/0.527 mm，标准孔幸存群为
0.944/0.516/0.466 mm，小孔幸存群为0.951/0.437/0.395 mm；理想1 mm立方源为
0.288/0.284/0.289 mm。小孔缩窄横向y/z分布，但没有缩窄纵向x分布，并对能量/相位相关子群产生选择，
因而本次分辨率反而变差。

该结果是单个N=1000母样本、单网格和两点孔径的`INCONCLUSIVE_DIAGNOSTIC_ONLY`。理想参考质量数与
实际质量数不同，三个峰形样本量也分别为1000、396和90；它不授予孔径收敛、数值收敛、Candidate或
Formal分辨率声明。459粒子的直接COMSOL轨迹臂超过1200 s预算并按
`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`封存；这里使用COMSOL双基场发布加SIMION粒子运输，未把
资源超限臂当作物理失败或成功证据。

### 八极杆整体前端 SIMION 单流程

`family_source_closure`现支持逐实验选择`execution_strategy=simion_single_flight`；缺省值仍为
`staged_three_stage`，原三阶段入口和结果合同不变。单流程仍使用正式oaTOF的四个workbench实例：第3槽
不再载入独立加速器PA，而是载入“八极杆杆体+屏蔽筒+接口孔+脉冲加速器”的整体前端PA；飞行管、反射器
和探测器继续复用正式PA。因此没有第五个PA实例，也没有handoff或grid2处的粒子重新释放。

整体前端机器合同固定1.0×0.9 mm矩形孔、杆体末端至加速器屏蔽罩外端面1.000 mm，并保证这1 mm
过渡段径向被屏蔽结构包围。campaign所选connection profile必须声明公共
`grounded_circular_to_rectangular_shield_v1`：它生成0.500 mm接地圆套筒及与oaTOF罩壁同厚的带孔接地
法兰，并将多极杆罩、连接件和加速器罩合并为同一个0 V电极9；功能电极仍为10至17，不再建立电极18。
任何一侧或连接profile声明非0 V屏蔽都会在GEM/Program生成前失败关闭。

旧子run `20260804_142000__sim__simion__rf-oatof-single-flight-gap0__n1000`使用已被取代的3 V/0 V
边界和未闭合圆方过渡，仅保留为诊断证据；其从同一N=1000母样本连续
飞行，得到`1000→571`（多极杆/加速器交界）`→491`（grid2）`→491`（探测器），总检测传输率49.1%。
与当前1.0×0.9 mm分阶段链的`1000→459→396→396`相比，单流程多112个handoff和95个检测粒子；
共同粒子分别为437、368和368。逐粒子残差中，handoff时间中位绝对差12.90 ns、位置RMS差
139.44 µm、速度RMS差19.73 m/s；grid2为1.320 ns、189.81 µm、405.54 m/s；检测时刻中位差
+1.242 ns、RMS差2.332 ns，检测面xy位置RMS差754.05 µm。证据见analysis run
`20260804_143000__analysis__cross__single-vs-staged__n1000`。

使用共同脉冲时刻作为飞行时间原点、相同direct-KDE估计器时，单流程491粒子的FWHM为2.702 ns、
R=5769；分阶段396粒子的FWHM为1.549 ns、R=10063。此前发布的分阶段R=6979使用grid2重启后的
`TofUs`，不能与单流程从母样本出生计算的总驻留时间直接比较，因此在新分析中作为非等价诊断单列，
没有改写旧结果。上述数值不得作为新接地闭合连接器的当前性能；新连接器必须重新生成PA并以同一
N=1000母样本重跑后，才能恢复逐粒子和分辨率比较。

当前0 V闭合连接器已用同一N=1000母样本完成两个四PA单流程真实SIMION分支。1.0×0.9 mm基准run
`20260804_174200__sim__simion__rf-oatof-single-flight-gap0__n1000`的
`release→handoff→pre-pulse→grid2→detector`为`1000→583→495→495→495`；加入物理接地
`grounded_rectangular_aperture_reducer_v1`的0.5×0.5 mm run
`20260804_180100__sim__simion__rf-oatof-single-flight-gap0__n1000`为
`1000→261→200→200→200`。总检测传输由49.5%降至20.0%，小孔保留大孔检测数的40.40%。

配对analysis run
`20260804_182000__analysis__cross__single-flight-aperture-comparison__n1000`确认小孔各检查点粒子集合
均为大孔对应集合的子集；检测面共同粒子为200，大孔独有295，小孔独有0。大孔全体/小孔全体的
direct-KDE FWHM为2.755/2.520 ns，R为12841/14042，看似改善9.36%。但在大孔几何中只取同一批200
共同粒子时已得到2.511 ns和R=14088；小孔对相同粒子的场/轨迹扰动使R轻微降低0.32%。因此本次
分辨率变化主要是孔径的粒子身份选择，不是小孔电场提高时间聚焦。共同粒子从handoff到检测面的
位置向量RMS差由0.000065 mm增至0.0931 mm，检测时刻RMS差仅0.0310 ns；这说明几何扰动可测但不是
全体峰宽变化的主要来源。两峰仍有2个显著KDE模态且明显右偏，结果保持
`INCONCLUSIVE_DIAGNOSTIC_ONLY`。新analysis run还发布了图例正确的0.5×0.5 mm空间六子图；既有
求解器run未被原地改写。

2026-08-05继续用同一N=1000母样本、同一接地闭合连接器和单一`+3 V`入口参考套筒测试
0.5×0.2 mm矩形孔。重试run
`20260805_100000__sim__simion__rf-oatof-single-flight-gap0__n1000__r02`真实完成四PA连续飞行，
但census为`1000→0→0→0→0`；全部粒子在连接端面终止，未形成可计算的TOF峰。该run的PA cell为
0.2 mm，恰好等于孔高。孔高两边落在相邻整数z网格节点106/107，孔中心在半格106.5；`notin`布尔
减除后两边之间没有可删除的内部电极节点。对refine前`frontend.pa#`的只读截面探针确认，法兰首个内部
x截面417在孔邻域221个采样点中`OPEN=0`，而上游相邻截面416为`OPEN=221`。因此零传输已定位为
当前0.2 mm离散PA把孔封闭，不是实际束流的机械截止；该run保留为负证据。

开孔能力现由仓库级`common/simion`统一治理，不限定于本integration：任一机械孔宽或高小于一个cell
即在GEM前失败关闭；非整数cell倍数或边缘未落网格节点时保留机械尺寸并输出机器警告；减材固定使用
`exclude_shape_inside_or_on_v1`，不以epsilon扩大孔径；编译或缓存PA必须在Fly前通过全壁厚贯通列和
四侧孔外接地guard审计。当前前端两层重叠接地材料都消费同一离散合同，避免一层开孔后被另一层重新
封住。

同一0.2 mm网格、同一机械0.5×0.2 mm孔的修复run
`20260805_100000__sim__simion__rf-oatof-single-flight-gap0__n1000__r03`对实际精炼`frontend.pa0`审计得到
候选贯通列`6`、开放列`6`、guard PASS，随后四PA连续飞行census为
`1000→261→201→201→201`（释放、handoff、脉冲前、局部加速器出口、检测器），总检测传输20.1%。
201个检测粒子的direct-KDE FWHM为2.511 ns、R=14089；该峰仍为双模态、右偏诊断峰。孔宽为2.5 cell
且y边缘不在网格节点，机器合同已记录两项离散警告；因此本run只关闭“假开孔”功能缺陷，不证明孔型
连续几何精确或网格收敛，也不授予Candidate/Formal资格。

### 加速前相空间的受控理想条件反事实

正式诊断入口
[`workflows/resolution_attribution/execute.ps1`](../workflows/resolution_attribution/execute.ps1)
实现根[`VALIDATION_METHODS`](../../../docs/VALIDATION_METHODS.md#受控理想条件反事实法)定义的
受控理想条件反事实法。它从一个已验证的单流程run冻结脉冲左极限与检测器共同粒子群，先运行不改变
状态的restart control，再在相同四PA、绝对脉冲时刻、数值设置和direct-KDE算法下逐臂替换预登记条件。
当前profile
[`resolution_attribution_counterfactual.json`](../config/resolution_attribution_counterfactual.json)
固定加速方向为全局z、横向为全局x/y，并区分理想边缘分布匹配、z--vz线性协方差消除、单能化、
组合干预和非工程化的相空间坍缩上限。所有臂保留原始粒子身份，不能把不同幸存者造成的峰宽变化写成
聚焦改善。

同一N=1000母样本的1.0×0.9 mm闭合连接器基准在脉冲前有495个共同检测粒子；七臂真实SIMION run
`20260804_210300__sim__simion__rf-oatof-resolution-counterfactual__n1000__r02`保持七臂均495/495命中。
restart control相对连续链的逐粒子检测时刻RMS差为0.01981 ns，direct-KDE FWHM只差−0.288%，说明
本次重启扰动远小于主要反事实效应。

|反事实臂|脉冲前主要变化|direct-KDE FWHM / ns|相对restart control|R|
|---|---|---:|---:|---:|
|restart control|无|2.7474|基准|12878|
|理想加速方向位置|z边缘分布匹配理想源，σz `0.4937→0.2885 mm`|2.2155|−19.36%|15969|
|理想横向位置|x/y匹配理想源，σx/y `0.8210/0.5561→0.2876/0.2838 mm`|2.7542|+0.25%|12846|
|消除加速方向协方差|z、vz均值/标准差不变，只令线性相关`0.8515→0`|3.8820|+41.30%|9114|
|脉冲前单能化|动能σ `0.02535→0 eV`，保持速度方向|2.7469|−0.02%|12880|
|理想z并消除协方差|上述两项组合|3.6855|+34.15%|9600|
|z/vz坍缩上限|z和vz均设为各自均值|0.02868|−98.96%|1233568|

结果确认加速方向相空间是当前TOF峰宽的主导敏感方向，但修正了“现有z--vz相关性本身有害”的猜想：
当前强正相关提供了明显补偿，直接消除会恶化峰宽；把z边缘分布匹配到理想源只能使当前峰宽减少约五分之一，
峰宽，且峰仍为双模态。横向边缘分布和脉冲前能散对固定共同群几乎没有直接影响。非工程化的z/vz
坍缩把峰压到0.02868 ns，只能证明剩余差距主要驻留在加速方向高维相空间及其非线性结构，不能作为
可实现性能或Formal分辨率。脉冲后出口能散仍可作为该相空间经加速产生的中介量，不能与上游z/vz
原因重复计数。本结果是单母样本、单离散的`CONTROLLED_COUNTERFACTUAL_DIAGNOSTIC_ONLY`，不闭合
数值收敛、统计泛化、Candidate或Formal资格。

## 已关闭迁移

旧四极杆S2/S3迁移等价workflow已在功能等价闭合后退出活动树；专用profile、执行器、adapter、
oracle/prereg配置和schema均不再是当前入口。完整处置、保留边界和当时结果索引见
[2026-08-01 活动兼容层退役](../../../docs/history/20260801__active-compatibility-retirement.md)。当前只保留
family source closure；连接级pulse/analyzer分析统一位于本integration的`analysis/`，不提供四极杆旧路径wrapper。

## 开放任务

1. **闭合单流程数值敏感性并继续限定重启效应。** SIMION整体前端单流程和公共连接器已经作为campaign
   可选正式功能接入，三阶段仍为默认且不退役；同母样本1.0×0.9及0.5×0.5 mm接地四PA基准和逐粒子
   孔径效应分解已经完成；0.5×0.2 mm的同网格假开孔已由共享Boolean边界策略和真实PA审计关闭，
   仍须以相邻网格量化非整数宽度/边缘相位造成的有效孔型与传输敏感性。随后继续RF步长敏感性，并独立隔离handoff/grid2
   重启效应；关闭条件是逐粒子残差能被各独立变量解释，且峰宽结论通过相邻数值档。完成前当前传输率
   和R只作单网格诊断，不授予Candidate或Formal资格。
2. **决定是否扩展COMSOL连续前端。** 当前新增策略只在SIMION闭合；若需要跨求解器判断，须另行授权
   同源COMSOL连续域，并与本次SIMION整体前端使用相同几何、绝对时钟、脉冲和逐粒子检查点。
3. **把分辨率归因诊断接入campaign选择。** 当前受控理想条件反事实已有独立正式入口和单样本真实
   SIMION证据；下一步在campaign schema中增加具名diagnostic profile选择，并补相邻数值档或第二母
   样本，预登记不确定度与组合臂策略。关闭条件是campaign只选择能力ID、每臂独立冻结身份与预算，且
   diagnostic结果不能晋升或反写baseline。

## 静态门禁

[`verify_integration.ps1`](../verify_integration.ps1)只运行无求解器的合同测试：模式中性profile、run-local
端口物化、公共解析、非空transfer composition step、单一dependency inventory、活动发布SHA、campaign
行身份、source/design强制冻结、父运行发布和campaign comparison失败关闭。它不运行COMSOL、SIMION、
MATLAB或CAD，也不替代真实求解器运行、数值收敛或物理资格验证。
