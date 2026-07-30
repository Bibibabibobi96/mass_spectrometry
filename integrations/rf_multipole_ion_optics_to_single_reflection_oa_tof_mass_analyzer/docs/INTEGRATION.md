# RF多极杆离子光学到单次反射oaTOF质量分析器集成

## 当前身份与边界

本目录是四、六、八极杆离子光学到单次反射正交加速TOF质量分析器的唯一连接实例层。
[`connection_profiles.json`](../config/connection_profiles.json)是连接拓扑的唯一机器权威；调用者必须显式提供
`ConnectionProfileId`。解析后的 connection 决定刚性位姿、连接器、公共电位、时钟和场责任区，运行器不得再消费
connector case 或由间隙推断拓扑。

迁移等价workflow保留两个四极杆冻结profile：

- `rf_quadrupole_grounded_connector_gap_1mm`；
- `rf_quadrupole_direct_mating_gap_0mm`。

多极杆族同源闭合workflow使用三个无加速全尺寸直接对接profile：

- `rf_quadrupole_no_acceleration_full_length_direct_mating_gap_0mm`；
- `rf_hexapole_no_acceleration_full_length_direct_mating_gap_0mm`；
- `rf_octupole_no_acceleration_full_length_direct_mating_gap_0mm`。

两个workflow的声明边界和公开入口不同。迁移等价只使用
[`execute_integration.ps1`](../execute_integration.ps1)；多极杆族同源闭合只使用
[`workflows/family_source_closure/execute.ps1`](../workflows/family_source_closure/execute.ps1)。
后者要求显式提供`ConnectionProfileId`和`SourceBranchId`。`SourceBranchId=comsol|simion`只选择冻结的
上游多极杆粒子源分支，不是接口求解器选择器；两种分支进入完全相同的固定下游链：
COMSOL `pre_pulse_interface_transport`、COMSOL `pulse_capture`、SIMION
`analyzer_transport`。内部phase不构成独立公开入口或资格声明。

同一公开入口还接受可选`SourceRevisionId`，默认值`baseline`保持上述六分支原绑定。
[`family_source_revision_registry.json`](../config/family_source_revision_registry.json)是修订选择的机器权威；
每个修订必须冻结自己的预注册、预算、runtime binding、允许的profile与source branch，不能覆盖
`baseline`记录或把任意路径作为运行参数注入。

两个公开入口都冻结resolved connection、composition plan、runtime binding和工程预算，并复用
[`runtime/run_transfer.ps1`](../runtime/run_transfer.ps1)及同一组三个stage。family workflow的每个
profile/source branch只授权冻结同源N=100母样本的compact功能运行；预算耗尽记为
`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`，自动重试固定为零。

## 多极杆族同源闭合状态与声明边界

三个family profile及其COMSOL/SIMION上游source branch已经完成机器合同、runtime binding、源状态和
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

当前source-revision发布器使用schema v2：每个profile必须显式绑定旧COMSOL、混合COMSOL和旧SIMION
三个父run，并发布三个`right_minus_left`有向pair、共同/差异粒子ID、局部加速器出口与探测器事件集合。
同一profile的三条series使用共同尺度和固定bin绘图，figure JSON、PNG及终态summary均进入manifest；
发布过程始终保留`interrupted`、`failed`或`success`之一作为当前权威终态。上述
`20260730_234500__analysis__cross__hybrid-source-revision__n100`仍是不可变schema v1历史artifact；
读取器保持兼容，但不会把它重写为schema v2，也不得把新的方向命名倒灌到历史结果。

## 迁移等价结论

[`migration_oracles.json`](../config/migration_oracles.json)是只读的迁移前证据索引，保留当时的术语、路径、
run ID 和 census。它不定义活动 profile、执行步骤或拓扑。
`migration_equivalence_preregistration.json`继续作为读取结果前冻结的`BLOCKED/NOT_RUN`预注册快照，
不得事后改写。

2026-07-29，两个profile均以冻结的同源N=100输入完成首次真实COMSOL→SIMION重跑。集成runtime和三个
phase迁入integration所有权、父运行统一采用仓库run ID合同后，2026-07-30再次通过公开入口完整重跑。
当前独立analysis run
`20260730_113401__analysis__cross__rf-oatof-migration-equivalence`核对源身份、五级census和四组逐粒子
离散事件集合，两个profile均为精确`PASS`，因此零物理变化的功能迁移在当前实现下保持闭合。结果
SHA-256为`90321241BCF6C5CE2F13E1B7D036682539E3F94C9D23303FA2733D095BA4B078`。首次结果仍按原
run身份保留，仅用于追溯。

adapter仍只发布轻量integration父运行；大型COMSOL/SIMION资产由三个子运行拥有，并按compact合同保留。
连续相空间保持`NOT_EVALUATED`；本结论不声明场、分辨率、数值收敛、Candidate、Formal或整机资格。

## 开放实现任务

当前若干被三个family profile共同消费的pulse/analyzer阶段分析脚本仍位于
`projects/rf_quadrupole_ion_optics/analysis/`，并由各family依赖合同显式冻结。它们不是第二套stage或
第二套统计实现，但所有权仍偏向四极杆项目。待当前真实同源闭合链完成后，应把确属本连接实例的脚本迁入
本integration的`analysis/`，同步更新三份依赖合同及runtime SHA；oaTOF项目专属的正式资产校验继续留在
oaTOF项目，不为迁移制造同义CLI或配置字段。

## 静态门禁

[`verify_integration.ps1`](../verify_integration.ps1)只运行无求解器的合同测试：profile 唯一性、公共解析、
非空transfer composition step、adapter registry SHA、预算冻结SHA、source branch身份传播、父运行发布
fixture、source revision注册与失败关闭、paired analysis失败关闭、迁移等价PASS/FAIL fixture与显式授权边界。它不运行COMSOL、SIMION、
MATLAB、CAD，也不替代真实迁移等价复验或family六分支真实运行。
