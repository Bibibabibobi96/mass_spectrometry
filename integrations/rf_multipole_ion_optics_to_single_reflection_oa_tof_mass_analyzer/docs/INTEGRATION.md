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

## 已关闭迁移

旧四极杆S2/S3迁移等价workflow已在功能等价闭合后退出活动树；专用profile、执行器、adapter、
oracle/prereg配置和schema均不再是当前入口。完整处置、保留边界和当时结果索引见
[2026-08-01 活动兼容层退役](../../../docs/history/20260801__active-compatibility-retirement.md)。当前只保留
family source closure；连接级pulse/analyzer分析统一位于本integration的`analysis/`，不提供四极杆旧路径wrapper。

## 静态门禁

[`verify_integration.ps1`](../verify_integration.ps1)只运行无求解器的合同测试：模式中性profile、run-local
端口物化、公共解析、非空transfer composition step、单一dependency inventory、活动发布SHA、campaign
行身份、source/design强制冻结、父运行发布和campaign comparison失败关闭。它不运行COMSOL、SIMION、
MATLAB或CAD，也不替代真实求解器运行、数值收敛或物理资格验证。
