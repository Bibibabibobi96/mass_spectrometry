# RF多极杆离子光学到单次反射oaTOF集成

本文件是四、六、八极杆到单次反射oaTOF连接的当前状态权威。器件设计与资格仍由各项目
`docs/PROJECT.md`拥有；机器精确值、完整运行表、失败链和被取代方案不在本文重复。

## 当前身份与入口

- integration ID：`rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer`。
- 唯一公开执行入口：[`workflows/family_source_closure/execute.ps1`](../workflows/family_source_closure/execute.ps1)。
- 调用者只选择campaign和`ExperimentId`；源项目、求解器、母样本、resolved design及数值设置从
  冻结source run派生，不在CLI重复声明。
- 当前结果均为功能或诊断证据，不授予连续相空间、数值收敛、优化、Candidate或整机Formal资格。

| 职责 | 机器权威 |
|---|---|
| 连接拓扑与端口 | [`connection_profiles.json`](../config/connection_profiles.json) |
| 声明式实验 | [`experiment_campaign.json`](../config/experiment_campaign.json) |
| 脉冲分辨率当前证据 | baseline [`pulse_resolution_direct_baseline_successor_r09_campaign.json`](../config/pulse_resolution_direct_baseline_successor_r09_campaign.json)；candidate [`pulse_resolution_direct_candidate_successor_r03_campaign.json`](../config/pulse_resolution_direct_candidate_successor_r03_campaign.json) |
| 执行适配 | [`execution_adapter_profiles.json`](../config/execution_adapter_profiles.json) |
| 单流程布局 | [`single_flight_layout_profiles.json`](../config/single_flight_layout_profiles.json) |
| runtime bindings | [`config/`](../config/)中的`*_runtime_binding.json` |
| 单飞数值与空间窗口 | [`simion_single_flight.json`](../config/simion_single_flight.json) |
| 线性相空间匹配 | [`accelerator_phase_space_match.json`](../config/accelerator_phase_space_match.json) |
| oaTOF变量及包络 | [项目config](../../../projects/single_reflection_oa_tof_mass_analyzer/config/) |

repository-text SHA由`runtime/refresh_family_repository_bindings.py`单向刷新；campaign source SHA由
`workflows/family_source_closure/refresh_campaign_source_bindings.py`冻结。终态manifest不得改写。

## 执行策略和粒子语义

| 策略 | 物理流程 | 适用边界 |
|---|---|---|
| `staged_three_stage` | COMSOL接口运输 → COMSOL脉冲捕获 → SIMION分析器 | 既有分阶段campaign |
| `simion_single_flight` | 单次Fly连续完成多极杆、连接器、脉冲加速、漂移、反射和检测 | 当前整体前端 |

`multipole_handoff`、`pre_pulse_state`和`local_accelerator_exit`是同一轨迹的checkpoint，不是重新释放或
时间清零。`continuous_injection_full_population`从多极杆入口释放全部声明母样本，不得先按脉冲可提取性
筛选；`pulse_eligible_conditional`仅用于带selection receipt的条件诊断。空间窗口只做detector-blind
分组统计，不修改轨迹。

schema-v3 pre-pulse single-flight 执行采用两条单权威链：campaign 中显式的
`single_flight_pulse_schedule_policy`只经`derive_pulse_schedule`编译为resolved pulse schedule，runner
只读取其中的`pulse_effective_time_us`；`single_flight_population`只经resolved population编译器冻结
总体模式、源表绑定、N、有序ID哈希、分母和bootstrap设置，adapter、runner、analyzer只消费该合同。
staged `local_accelerator_exit` restart则禁止pulse schedule/time进入schema、prepare、adapter、runner、
run config或SIMION CLI，并按下游分析范围跳过pulse eligibility与injection validation；其唯一population/
source identity来自canonical 28列staged table及producer manifest，旧upstream source只允许作为显式
`connection_lineage_only`连接谱系。无overlay必须从instance 3启动，有overlay必须从instance 5启动，
两个方向均失败关闭。源表和轨迹观测只能交叉校验，不能补默认值或覆盖合同；有序eligible集合使用合同
冻结的`expected_particle_ids`，不得假定ID连续。campaign SHA和实验行SHA在`SolverAuthorized`分支之前
复核。schema-v1/v2仍可读，但single-flight的`SolverAuthorized`执行会失败关闭并要求schema-v3 successor。
完整实现、29行successor及验证收据见
[schema-v3单权威收口记录](../../../docs/history/20260814__rf-oatof-schema-v3-resolved-pulse-population-authority.md)。

joint single-flight run package由integration ID拥有；`run_config.project`与终态manifest的
`project`都必须是integration ID。多极杆项目ID只作为`upstream_project_id`和源输入lineage，不能再
决定joint output路径。`staged_three_stage`的stage输出仍归对应upstream project；未知执行策略失败
关闭。2026-08-15之前已经发布在upstream项目目录中的single-flight run保持逐字节只读兼容，reader
只能依据冻结manifest/run_config中的显式legacy ownership与upstream source identity读取，禁止按目录
形状猜测，也禁止新writer继续写入该legacy位置。

single-flight frontend不拥有第二套rod GEM primitive。四/六/八极杆resolved design中的
`segmented_rod_array`由`common/multipole/simion_geometry.py`统一验证并生成官方SIMION `cylinder`/
`locate` primitive；integration只声明local-z→global-x的刚体placement、组合PA电极namespace及connector。
当前三族均为四个轴向segment、显式rod basis IDs `1..8`，但物理rod primitive分别为16/24/32条；frontend
不得再用“固定四段八极杆”推断primitive数量。single-flight现通过显式电极拓扑注册表发布两种映射：
既有双区`two_zone_frontend_v1`保持总电极`0..19`逐字不变；三区
`three_zone_frontend_v1`只新增`accelerator_intermediate2_id=20`，总basis为`0..20`。活动
layout/profile/GEM仍全部是双区，只有消费冻结三区拓扑的后继才能选用ID 20；注册表存在不等于frontend
已经具有真实第三栅。

single-flight不得维护第二套RF公式。`common/multipole/simion_rf_drive.lua`是独立多极杆与integration
Program共用的纯Lua drive kernel；它经`family_runtime_dependencies.json`注册，并在每个joint run的
`inputs/simion_rf_drive.lua`冻结后嵌入生成Program。kernel不读取SIMION时钟；integration唯一传入
`birth + ion_time_of_flight`，杆电压先写入，再由唯一`fast_adjust`callback按既有顺序写加速器pulse。
`rf_steps_per_period`只来自已选single-flight numerics profile，并同时控制kernel timestep cap；Program
不得另设固定值。完整收口与回归收据见
[公共RF drive kernel记录](../../../docs/history/20260815__multipole-common-simion-rf-drive-kernel.md)。

RF母样本到oaTOF全局粒子状态及SIMION方向角的投影由integration
`runtime/rf_handoff_adapter.py`唯一拥有。该模块只负责solver-row与particle ID顺序闭合、oaTOF全局
速度与SIMION加速器PA方向角互转，以及速度/动能一致性；位置与instrument time由邻接的
`publish_family_source_bundle.py`和`single_flight_source.py`校验。连续single-flight、pre-pulse/analyzer
staged transport及counterfactual分析共同消费这一API；连接状态投影边界不得依赖oaTOF项目内同义
adapter。oaTOF项目只发布required port、resolved几何及分析器组件，不保存RF→oaTOF连接专用副本；
integration继续允许调用oaTOF项目发布的理论和设计编译API。

single-flight Program由一个integration assembler唯一声明Workbench和九类`segment.*`callback。项目
Candidate analyzer component只拥有oaTOF实例、基础场、静态电压和detector行为；integration pulse/
frontend hooks只拥有规范instrument clock、RF→pulse编排和基于SIMION官方callback机制的项目落面hook；resolved-region
hook按冻结profile执行base→override。四个Lua组件必须先冻结到run `inputs/`再由builder读取，并经统一
纯边界校验，禁止从活动仓库回退读取。历史Formal/旧pulse仍由staged `analyzer_transport`冻结使用，
但不再进入`single_flight_transport`活动路径。timeout、return-plane及detector crossing显式使用
solver-local `elapsed_us`；只有pulse、RF和跨系统checkpoint使用`birth + elapsed`，分析器负责从
detector local elapsed与冻结birth构造instrument time。

理论/理想源合同必须另外声明`source_state_epoch`和`source_state_locus`，两者与坐标基、规范时钟、
有序粒子ID和目标状态共同构成源身份。若SIMION因连续轨迹要求在目标epoch之前写入`.ion`，该文件只算
`release_implementation_state`；profile中的目标宽度、均值或斜率仍指向声明checkpoint，不能由release
行直接冒充。运行前必须冻结逐粒子checkpoint验收容差；运行后receipt至少保存目标/观察epoch与plane、
到达ID、位置和速度残差、能量一致性、终止分类及PASS/FAIL。只有实际checkpoint在预声明容差内闭合，
该run才能沿用理论/理想源注册名。

旧profile未提供上述epoch/plane与checkpoint receipt时，只能解释为具名`AT-RELEASE`诊断。若源在
编译PA中创建失败、未到达目标checkpoint或残差越界，runner/分析必须失败关闭；结果降级为
`release aperture incompatibility`或相应实现态失败证据，不计算分辨率、不进入理论源性能矩阵，也
不得用裁剪、筛选、重定位或事后放宽容差维持原声明。该规则只收紧证据语义；新增机器字段及门禁须复用
现有source materialization与checkpoint receipt链，不建立第二套源物理实现或执行入口。

本轮规范pulse-state源的locus固定注册为
`accelerator_stage1_interior_fixed_transverse_finite_local_z_interval`：它是Stage1内部、固定横向坐标并沿
`z_local`占有限区间的region/manifold，不是`global_x`平面。正式restart合同唯一冻结逐行位置
`1e-9 mm`、逐行速度分量`1e-6 m/s`、时钟`1e-9 us`和由实际速度派生的物理能量`5e-9 eV`绝对容差；prepare只把同一合同身份
传到adapter、runner和analyzer，消费者不得另设默认阈值。actual SIMION `source_release`必须覆盖全部
有序ID并逐行闭合，summary引用同一validation-contract SHA。

该restart表示采用SIMION支持的原生粒子与Program机制，不是项目自建轨迹搬运。官方依据于
`2026-08-14`按本机目标版本SIMION 2020核查如下：

- SIMION官方[FLY2 File](https://simion.com/info/fly2_file.html#individual-particles)的
  “Individual Particles”明确允许把每个粒子写成独立`standard_beam`，并直接使用
  `position=vector(...)`与`velocity=vector(...)`；同页说明这种表示加载效率低于ION，但数千粒子仍属
  合理范围。本项目只用它表达N=1000 pulse-state restart，不把它扩展成新的源动力学算法。
- SIMION官方[SIMION 8.2 (2020)](https://simion.com/info/simion82.html)把
  `sim_segment_global`列为8.2正式reserved variable：置1后，粒子位于任何PA instance之外时Program
  segment仍会被调用。本机官方`SIMION-2020/examples/mfield_adjust/README.html`给出的组合正是紧随
  `simion.workbench_program()`声明`simion.early_access(8.2)`与`sim_segment_global=1`。本项目原样采用
  该已安装版本示例组合，但只对带冻结validation contract的`pre_pulse_restart`启用；连续前端仍走原
  ION路径，避免把全局segment调度无条件扩散到其他workflow。

FLY2载入仍可能把速度经过内部表示往返，官方格式支持不等于逐位无误差。因此实际
`source_release`必须按同一冻结合同逐粒子验收位置、速度、时钟与由实际速度派生的物理能量；不得以
“官方格式”跳过误差门禁或增加数值预补偿。

`staged_grid2_restart`复用上述官方individual-particle FLY2与唯一single-flight runner，但源权威收紧为
`canonical_component_particle_state_v1`精确28列的`local_accelerator_exit/oatof_global`状态；旧11列
SIMION TRACE不得直接成为restart源。兼容历史证据时，只允许既有`materialize_simion_grid2_state`作为
受控桥：prepare同时冻结template、TRACE与独立characterization receipt，重建结果必须逐字节命中已声明
canonical SHA。桥接receipt明确记录位置/时间为grid2穿越线性插值、速度仍是当前solver step而非穿越时刻
插值、`ax/ay`非权威、能量经质量和速度校验后重算，因此该桥只能支持功能迁移，不能支持物理等价或
分辨率结论。

restart上下文必须显式声明event、frame、clock basis/epoch、无位置投影及起始instance；旧N=34 oracle
固定从instance 3进入，禁止猜测overlay。SIMION局部粒子行号通过冻结row map映射回非连续canonical ID，
分析器不得以行号代替源ID。该模式跳过RF frontend、pulse和accelerator运行时写入，保留analyzer静态
初始化、downstream base→override电场顺序以及`canonical restart time + solver local elapsed`的探测器
绝对时钟。当前未发布successor的claim严格为`FUNCTIONAL_MIGRATION_ONLY`；旧runner在真实SIMION物理
parity完成前保持只读可用。

## 单流程PA、屏蔽和参数重构

单流程的四个Workbench槽位依次为flight tube、reflectron、combined frontend和detector。combined
frontend把多极杆、连续接地屏蔽、连接器和oaTOF加速器放在同一PA；当前活动双区layout中电极1–8为
八极杆，9为接地屏蔽与连接器，10–17为加速器功能电极，18为入口参考套筒，19为入口板。三区注册
身份保留这些ID并预留新增中间边界ID 20，但当前GEM/PA尚未物化该电极。每次run生成的
`single_flight_frontend_contract.json`及冻结的`frontend_electrode_topology.json`才是编号和几何权威。

布局profile的`design_overrides`只能引用oaTOF变量目录：连续量受安全包络和实验包络约束；整数是离散
拓扑量；焦面、平移、反射器和罩体等理论派生量禁止直接指定；网格和时间步属于数值profile。省略输入
即继承活动layout/base resolved。编译链固定为：

```text
layout profile + design overrides
→ candidate baseline
→ theory closure
→ resolved geometry
→ run-local PA rebuild plan
```

canonical finite-interval layout中的`midgrid/backplate`明确禁止作为独立扫描轴。它们只能由理想源条件、
加速器理论解和耦合反射器方程整体派生；`ACC-RR/IR/RI/II`共享各自layout的这套理论派生电压。派生链
不得读取反射器入口的实测粒子状态、检测器时间/FWHM/分辨率，也不得用经验扫描反调电压。本轮反射器
电压扫描已取消，没有新增实验；后续若权威理论输入发生变化，仍必须回到上述完整编译链重新派生。

finite-interval整机设计编译的代码所有权属于oaTOF项目公共
`analysis/finite_interval_design_compiler.py`：integration只传四个物理相空间量、源宽和一级长度，项目
API原子返回几何、电压、反射器耦合、shield与rebuild plan。profile路径、run/checkpoint/cohort/粒子数
等provenance只进入integration自己的`finite_interval_input_provenance`收据，不得进入项目request或
项目理论派生树。integration不得复制公式或逐字段改写`midgrid/backplate`。2026-08-15迁移对全部9个
活动finite profile执行旧结构重构校验，证明resolved物理量、port及derived values逐字等价；外层
canonical SHA因provenance结构迁移而显式换版。没有修改GEM/PA、场、dt、资源、入口或Formal资产。

finite-interval数值政策只由oaTOF项目的`FINITE_INTERVAL_COMPILER_POLICY`发布。活动integration
`accelerator_phase_space_match.json`不再重复电压降边界、采样数或电压容差；counterfactual分析同样
直接读取项目政策。旧provisional theory-order campaign保持逐字不变，活动诊断使用显式绑定去重配置
及项目政策文件的`zero_match_long_all_ideal_theory_order_stage_v2_successor`。

三区后继从“可编译、可失败关闭”继续闭合到了真实SIMION PA的Functional执行证据。oaTOF项目
[`three_zone_t5_simion_candidate.py`](../../../projects/single_reflection_oa_tof_mass_analyzer/analysis/three_zone_t5_simion_candidate.py)
可从hash绑定的成功T5 receipt/report唯一读取`frozen_primary`和冻结branch root，输出
`CANDIDATE_ONLY`的`three_zone_accelerator_ideal_v1` plane/potential mapping；integration
region-field schema v2分别以显式ideal和real-PA profile消费同一mapping；real-PA profile在全域返回
native PA base field，不把双区`FULL_DOMAIN_PIECEWISE_IDEAL_FIELD`静默三区化。

冻结三区四平面为repeller/I1/I2/exit，位置
`-62.992615/-59.742615/-54.642615/-42.742615 mm`；ID 20是I2真实一行透明栅。5个整形环不再把
17 mm合并等距，而按二区5.1 mm与三区11.9 mm分别布置为1+4：中心
`-57.192615/-52.262615/-49.882615/-47.502615/-45.122615 mm`，1 mm环厚下最小栅—环边缘
间隙为`1.88 mm`。旧双区和旧三区profile保持不变。

source合同继续复用唯一2.2 mm affine N=1000母样本。N=1冻结母ID 500；最终N=100用
`ID(k)=1+round(k*999/99)`、`k=0..99`，母ID从1到1000，实际global-z端点
`-62.5942398207/-60.3942398207 mm`，完整覆盖2.2 mm。物化后SIMION行重新编号1..100，其SHA与
母ID映射分别由population合同和subset receipt绑定。旧file-order前100行只覆盖0.218018 mm，已保留为
窄源诊断，不得作为2.2 mm结果。

v5 N=1父run `20260817_235800__sim__cross__three-zone-segmented-rings-real-pa-n1__n1`发布PASS
authorization receipt；全宽N=100父run
`20260817_235900__sim__cross__three-zone-segmented-rings-real-pa-full-width__n100`及其SIMION
child均通过manifest验证。100/100粒子各自穿过I1、I2、exit、反射器并到达探测器；pulse-relative
`sigma=0.2035735674 ns`、直接`FWHM=0.2338558848 ns`、质量`R=66988.23`、单峰。该结果只授予
Functional/CANDIDATE_ONLY真实PA证据；不授予工程资格、COMSOL等价或Formal变更。最终N=100的
frontend、overlay与flight-tube均为cache hit，没有再次Refine。

### 经验纵向非线性、能谱与横向六维敏感性

在上述真实PA和同一全宽分层N=100 ID集合上，投影从成功的996行observed pulse-state authority逐ID
恢复经验`z-vz`、逐粒子能谱和横向六维状态，只把旧源中心共同平移到当前三区源中心并采用当前pulse
epoch；clock差不解释为连续物理飞行。四个artifact名称是
`affine_zvz_fixed_10eV_transverse_collapsed`、`observed_zvz_fixed_10eV_transverse_collapsed`、
`observed_z_vz_energy_transverse_collapsed`和`full_observed_6d`。前两个严格共享经验`z`点、10 eV
总能量和塌缩横向状态，只把`vz`从当前affine规律替换为observed非线性关系，并在同一能量壳内联动
正向`vx`；后两步再依次恢复observed逐粒子能谱和完整横向位置/速度方向。

每个N=1机制门均1/1探测并分别授权同臂N=100；四个N=100均100/100探测。按上述顺序，pulse-relative
`sigma/FWHM/R`为`0.0919962629/0.1201946242/130335.42`、
`0.8197245483/2.4711425665/6339.43`、`0.8197190662/2.4714356728/6338.67`和
`0.8542897552 ns/2.5829468539 ns/6065.03`。以首尾总退化为分母，非线性`z-vz`残差、能谱和完整
横向状态的顺序份额在sigma上为`95.46563%/-0.00072%/4.53509%`，在直接FWHM上为
`95.46019%/0.01190%/4.52791%`。能谱项接近零且sigma符号为负，只能按本次单一N=100数值实现解释。
detector-blind残差审计显示，重新匹配affine均值/斜率后仍有`95.7478586%`的原残差均方；2—6阶
多项式只捕获剩余non-affine/stochastic scatter的`0.92%—1.14%`，不能把本轮现象简化成光滑三阶项。

该比较明确是冻结三区设计下的`FUNCTIONAL_ONLY`敏感性，不证明经验非线性不可通过重新编译源模型并
联合求解加速器、场和反射器来补偿。observed状态移植也不是连续真实handoff轨迹。完整公式、经验源
统计、冻结身份、run/manifest及理论升级问题集中见oaTOF项目的
[`20260817__three-zone-zvz-nonlinearity-fixed-energy-source-sensitivity.md`](../../../projects/single_reflection_oa_tof_mass_analyzer/docs/history/20260817__three-zone-zvz-nonlinearity-fixed-energy-source-sensitivity.md)。
canonical顺序比较run为
`20260817_235946__analysis__python__three-zone-source-sequential-attribution__n100`，manifest SHA-256
`C7E4E7C86AA5B249F690EF1CA439B46506593CDC5EC131CB822FEA259B2C1E8E`并已验证。focus到detector的
checkpoint分解表明下游会显著放大并重映射observed-affine残差，横向步骤的FWHM/R符号也会改变；
因此上述detector份额是固定顺序、固定checkpoint的描述量，不是顺序无关factorial effect。完整数值与
closure只在链接的history和canonical artifact保存，本节不建立第二份清单。

栅面机制只沿用2026-08-13已验收的SIMION官方一行raw-PA理想透明电极路径；本轮没有增加自建跨栅、
epsilon越层、粒子位移或TOF补偿。N=1→N=100机器门已按真实checkpoint、manifest和全科学身份闭合；
schema、注册表或测试通过本身仍不能替代上述solver evidence。

加速器对相邻组件只发布外包络端点；屏蔽罩、无场区和反射器边界从该端点派生，不重复维护内部尺寸或
绝对坐标。范围校验只证明可编译；几何、电压或拓扑改变后仍须重新验证PA贯通、电极映射、真实Fly和
数值敏感性。

单流程frontend、accelerator overlay、flight tube与reflectron四类PA性能缓存均使用根README注册的
schema-v2内容身份：key同时绑定角色、输入/构建代码、SIMION产品版本与可执行文件SHA-256以及完整关键
选项；命中前由公共artifact verifier逐文件复核bytes/SHA，损坏或不完整的schema-v2 entry只允许精确
重建。每次使用的cache manifest冻结进该run inputs；它只说明本次复用了哪组可重建PA，不能替代run
manifest或Formal资产。旧schema entry在单独清理前只保留布局可识别性，运行时一律视为MISS。
2026-08-14引用审计后只物理保留当前实验所需的10个legacy PA entry（33,919,321,596 bytes）；这些
entry也不获得运行时复用资格，首次需要时必须由冻结输入重建并发布为schema-v2。

同日完成旧分析证据的正式successor收口：短/长checkpoint FWHM当前分别引用
`20260814_163500__analysis__cross__short-checkpoint-fwhm-2x2-republish-n1000`和
`20260814_163600__analysis__cross__long-checkpoint-fwhm-2x2-republish-n1000`；legacy stage-field当前引用
`20260814_164400__analysis__cross__legacy-stage-field-2x2-fail-closed-republish-n1000`。短/长postselection、
q8/q108与三份ZERO-MATCH source当前依次引用`20260814_184000__analysis__cross__oct-whole-short-long-republish__n1000`、
`20260814_184100__analysis__python__rr-tqual8-vs108-republish__n100`、
`20260814_184200__analysis__cross__zero-match-short1-source-v2__n1000`、
`20260814_184300__analysis__cross__zero-match-long1-source-v2__n1000`和
`20260814_184400__analysis__cross__zero-match-long2p2-source-v2__n1000`。ZERO-MATCH source三件套与
旧`174000/174100/174200`逐字节相同；这些successor只补齐v2 campaign、manifest和精确输出失败关闭，
没有重跑SIMION或改变科学值。旧`20260813_151500__analysis__python__axial-ideal-arm8-closure`现由
`20260814_165300__analysis__python__axial-ideal-arm8-closure-republish`正式接管：`8,459-byte` receipt
逐字节相同，当前campaign只绑定`evidence_revision=2` successor，并仅在`supersedes`保留旧身份。
旧`scratch/r03-winner-post-selection`则由
`20260814_185300__analysis__python__r03-winner-postselection-republish__n1000`接管，四份科学文件逐字节
相同；source solver terminal status仍为failed，因此只保留成功detector-blind reanalysis/postselection
声明。完整旧→新ID、summary/manifest/receipt SHA统一查
[高阶时间像差续篇](../../../docs/history/20260814__oatof-canonical-matrix-high-order-continuation.md#后续正式successor与当前证据绑定)。
该续篇的名称一致性覆盖source、cohort、geometry、accelerator field、reflector field、grid、solver
numerics和clock全部结果身份维度，不只覆盖离子源；同一机器身份在结果表和successor引用中沿用同一
规范注册名，不用简写另造第二配置名称。

本轮清理已永久删除七批共`274,407,951,175 bytes`：第一批`550,005`、59个非当前legacy PA cache
`179,406,313,439`、4个run内未由manifest引用的PA副本`90,227,338,032`、8个失败/中断/无终态或
已被成功recovery/Formal完整取代的目录`4,765,128,506`、旧`151500` receipt `8,459`、47个invalid
scratch `6,741,298`和正式successor接管后的最后2个scratch `1,871,436`。删除不可恢复。继续保留10个当前cache
（`33,919,321,596 bytes`）、全部Formal发布物、成功manifest逐文件冻结资产及唯一结果/不可重构输入；
清理不改变33行矩阵、ZERO-MATCH结果、资格状态或后续复现入口。

## 真实场pulse时刻自动选择与复用

gap 3.2 mm的detector-blind held-off time-series已在同一N=100、同一三区real-PA、同一RF与数值身份下
冻结321个原生采样时刻；自动选择得到`47.45133445865456 us`。随后唯一
`family_source_closure`入口以该候选完成一次完整pulse-on确认：
`100→95 handoff→81 pre-pulse→80 intermediate2→69 exit→69 detector`，parent/child run分别为
`20260818_232300__sim__cross__three-zone-pulse-confirmation-gap3p2__n100`和同时间戳的SIMION child。
该结果只授权相同内容身份的功能复用，不声称时刻全局最优、分辨率最优、Candidate或Formal资格。

resolved pulse schedule仍是runner唯一时刻输入。prepare按源、人口、有序ID、connection/gap、三区几何、
场、RF、数值和selector规则计算内容身份；命中已验证receipt时直接复用上述时刻，缺失或身份变化时保留
原schedule派生路径。用户不填写标量pulse时间，也不新增runner CLI；time-series、候选选择、pulse-on确认
和后续复用均由同一公开workflow及manifest/receipt链承载。verified cache只是可删除加速层，确认child
manifest仍是证据权威。

## 脉冲分辨率优化能力与边界

当前baseline证据由
[`pulse_resolution_direct_baseline_successor_r09_campaign.json`](../config/pulse_resolution_direct_baseline_successor_r09_campaign.json)
发布，三行candidate完成证据由
[`pulse_resolution_direct_candidate_successor_r03_campaign.json`](../config/pulse_resolution_direct_candidate_successor_r03_campaign.json)
发布。两者以及此前失败的baseline r01–r07、candidate r01–r02均保持原字节；唯一既有
[`family_source_closure_legacy_attribution_migration.json`](../config/family_source_closure_legacy_attribution_migration.json)
按内容SHA登记外部终态和不可执行处置。入口在source binding、prepare及任何输出之前，对已登记终态
campaign的`ValidateOnly`、`PrepareOnly`和`SolverAuthorized`统一拒绝，避免文件内历史`authorized`
状态成为第二活动权威。`pulse_resolution_direct_candidate_campaign.json`仍为
`PENDING_PREREGISTRATION`模板；没有建立第二套CLI、物理模型、registry或运行树。

baseline不再把迁移前D46986的`66/50/16`作为当前官方输运权威。prepare只冻结同一source-release
N=100、源身份和pulse clock，并由既有`pulse_resolution_execution_mode`派生
`establish_observed_authority`；resolved population只预先含`population_count=100`。baseline分析从本次
日志发布source-release、pre-pulse、pulse-eligible和outside-transverse-bore四组有序ID/count/SHA，handoff
单列，并以self-SHA闭合。旧checkpoint只保留为`historical_migration_reference`。候选未来只有在campaign级
`pulse_resolution_baseline_evidence`冻结该receipt路径和文件SHA后才能预注册；prepare与registrar复用同一
纯验证函数，派生`require_frozen_baseline_authority`并要求receipt self-SHA有效、
`solver_execution_performed=true`、四组成员及digest逐组精确复用。当前pending模板不含该证据，也不授权任何候选、N=1000、COMSOL、
qualification或promotion运行。

当前r09/r03已经发布终态证据，不得复用原run identity重跑；下一次执行必须形成新的campaign和run身份，
再经同一`family_source_closure`入口校验与执行。

SIMION单飞分析现以`detector_time_minus_pulse_effective_time`为唯一分辨率时钟；absolute instrument
clock只保留诊断语义，不能形成分辨率声明。输出分别保留完整pulse-eligible队列的峰与传输、冻结理论窗
的覆盖和条件结果、固定seed bootstrap，以及焦面后的反射器入口、中间栅、转向点和出口common-cohort
分段诊断。窗口定义接口不接受检测时刻或命中标签，窗外粒子继续计入完整束；这些字段和算法已通过
求解器无关测试，但尚未由本campaign的新真实SIMION运行产生资格证据。

生产编排仍未把两项资格能力接入上述planning-only campaign：一是同时含两方向角度边界的冻结理论
接受窗，二是按机器合同执行固定seed的5000次bootstrap并据区间宽度作门禁。当前空间窗口runner仍只
覆盖既有位置轴profile，单飞分析入口虽能计算可配置bootstrap，现有campaign/adapter并未传入资格参数。
因此不得把纯分析函数、默认关闭的CLI能力或既有位置窗输出解释为角度接受窗或bootstrap资格已经执行。

六维二阶局部传递模型及理论接受窗冻结机制也已实现为求解器无关分析边界：固定粒子ID划分训练/验证，
包含完整一阶、平方和交叉项，并预测焦面时间、探测时间、探测半径与命中状态。接受窗由合成相空间和
理想场—真实场的预测时间误差构建，再对完整pulse-eligible队列检查覆盖；真实检测结果不能参与窗定义。
环电压候选生成器只接受端点固定、单调且位于理论能量包络内的少量基函数候选，并声明复用PA。这些能力
目前只证明合同和纯分析实现闭合，不证明其代理精度、物理最优性或门槛可达。

## COMSOL retrace边界

COMSOL侧已把一次性retrace分支收敛到一个声明式arm校验器和通用执行边界：handoff receipt冻结SIMION
winner、几何、电压、场模式、粒子ID、时钟和理论接受窗；粒子释放使用共享全局笛卡尔速度，并在启动前
检查序列化误差和逐粒子身份。`source`及`field_mask`变化只规划粒子解，`voltage`变化规划静电场与粒子
解；`geometry`和`mesh`变化由retrace入口明确拒绝，必须回到受治理model builder。终态census为每个
输入粒子保留`hit`、`wall`、`escape`、`timeout`或`solver_failure`，不得删除慢粒子或失败粒子。精确
复用分类和速度门槛只查源码与优化campaign机器合同。

上述COMSOL边界目前只完成合同、静态测试和供应商侧任务脚本；runner仍在修正receipt身份冻结、run
三件套、retention和失败/中断终态等lifecycle闭合，当前不得执行为受治理retrace。本次没有启动COMSOL、
没有生成新的真实retrace结果，也没有完成GUI重开Compute、连接开口/接地罩边界对等、局部网格收敛或
单会话N=1000。因此它不能作为SIMION/COMSOL一致性、性能、Candidate或Formal证据。

## 当前物理结论

本节保留调查过程中形成的自由简称；2026-08-14本轮源、cohort、短/长结构、原生栅网、加速场、反射场、
数值设置和时钟的唯一结果注册名及完整矩阵，统一查
[源/场配置注册表及结果矩阵](../../../docs/history/20260814__oatof-source-field-configuration-registry-and-results-matrix.md)。
后续不得脱离该注册表用“理想源”“真实场”“RR”或“理想接受区”指代本轮结果。

### 稳态束与源相空间

- 1.5 mm入口参考套筒、10 eV目标注入的N=1000连续基准为
  `1000→968→950→948→948`，总检测传输94.8%；脉冲前能量为`10.01783±0.05134 eV`。
  handoff加速方向角度σ为`1.81390°`，脉冲前σz为`0.54583 mm`。高传输和目标能量已闭合，
  角度及z展宽未闭合。
- 全量N=2000同网格运行得到`2000→1919→1873→1706→1617`，整体效率80.85%；脉冲瞬间1623粒子
  位于一级接受区，条件效率99.63%，单峰`R=23390.46`。1623粒子条件运行不能替代2000粒子整机分母。
- 标准N=1000前缀的同网格自然释放为`1000→957→938→852→806`、`R=22562.21`。真实束脉冲前
  z–vz相关系数约0.886；把同一粒子改成独立均匀位置且令加速方向速度为零，反而降为双峰
  `R=14183.86`。因此当前相关性总体参与聚焦，不能把“vz=0的独立立方源”预设为理想答案。
- detector-blind窗口表明，1 mm加速方向窗口的分辨率高于全队列，三维1 mm盒进一步提高；z展宽是
  最强单变量，但横向相空间和随机残差仍不可忽略。目标源应匹配相空间椭圆，而不是只压窄z或去相关。

### 2.2 mm有限区间与线性理论

当前有限区间设计保持两个均匀加速场，二级内部环线性分压。`d1=3.0 mm`、`d2=16.8 mm`的理论解
可覆盖2.2 mm源宽，派生焦距约45.36 mm，焦面保持全局`z=0`；现有5环和不小于1 mm的制造净间隙
已经满足理论实现，不需为“实体容纳”增加一级间距、二级长度或环数。精确公式只查
[线性z–vz理论](../../../projects/single_reflection_oa_tof_mass_analyzer/docs/theory/z_vz_linear_phase_space_coupling.md)。

理论几何重构在真实场中提高了传输，却形成双峰且`R≈8494`，不能晋升。理想分段场的人造线性源在
修正栅面时间步截断后能在焦面闭合，证明公式、源映射和焦面坐标有效。这里“真实PA与理想两段均匀场
的差异是主要限制”只描述2026-08-12里程碑所用历史源、cohort与单点数值配置，不能外推到本轮规范
N=1000矩阵；后者已把完整2.2 mm有限区间的高阶残差识别为主导，而真实场/downstream bundle只贡献
约7.3%的附加sigma。详细诊断和代表run见
[2026-08-12里程碑](../../../docs/history/20260812__oatof-finite-interval-focus-diagnostics.md)。

### 规范1 mm affine四臂的焦后交互

统一33行表派生分析现已完成短/长`ACC-RR/IR/RI/II`的严格IDs 1..1000检查点配对。检测面直接FWHM
析因中，Stage2理想化主效应为短/长`-0.113562236/-0.101770972 ns`，明显大于Stage1的
`-0.003474939/+0.005925899 ns`，因此Stage2仍是规范1 mm源的主要直接改善方向。完整FWHM
difference-in-differences从反射器入口到检测面，短焦由`+0.044723597`变为`+0.072874903 ns`，长焦
由`-0.036653286`翻转为`+0.031748199 ns`；固定downstream/真实反射器bundle确实改变非加性interaction。

该结论不能拆成纯反射器电压失配：现有真实场输出没有受支持的detector-blind一、二阶导数识别入口。
RR与II检测峰还分别出现2模及3/4模，且当前无bootstrap、无数值收敛；因此只允许确定性描述，不授予
统计显著、普适或Formal结论。四臂原值、mean interaction、run与SHA统一见
[高阶时间像差续篇的派生受控交互分析](../../../docs/history/20260814__oatof-canonical-matrix-high-order-continuation.md#33行统一表的派生受控交互分析)。

### 真实八极杆束的焦距、一级间隙与径向结构配对

2026-08-13以同一冻结N=100八极杆源、同一0.05 mm局部一级加速PA、同一70粒子pulse-eligible
cohort和`detector_time_minus_pulse_effective_time`时钟完成实际场配对。大径向结构
`bore/ring/shield=250/300/350 mm, 10/5 rings, t=5 mm`下，1 mm短焦距为
`R=7626.26, FWHM=2.1178 ns`，2.2 mm长焦距为`R=7059.05, FWHM=2.2829 ns`，后者低
7.44%；两者均`100→95→82`，因此差异不是传输或横向接受变化。共同脉冲前相空间为
`σx=2.24 mm, σy=0.48 mm, σz=0.49 mm, σvz=0.13 mm/µs, corr(z,vz)=0.88`；长焦距
峰的偏度/超额峰度由`0.096/0.220`升至`0.715/2.288`，表明同一z–vz束被实际一级场映射成更强
非高斯时间尾。

把长焦距一级长度由3 mm改为4 mm时，加速器电压、轴向平移及反射器电压均按联合一阶/二阶理论
自动重解；结果为`R=5721.04, FWHM=2.8387 ns`，相对3 mm再降18.95%。70个合格粒子仍全部
到达，额外探测损失发生在非合格背景。因此当前证据否定“简单扩大d1即可减弱边缘场并提高长焦距
分辨率”，不继续机械扫描5 mm。

紧凑径向结构`35/70/100 mm, 8/15 rings, t=2 mm`的严格交叉得到：短焦距
`R=8057.25, FWHM=2.0045 ns`，长焦距`R=6871.80, FWHM=2.3451 ns`，两者均77/100到达。
紧凑结构相对大径向结构使短焦距提高5.65%，使长焦距降低2.65%；紧凑结构内长焦距比短焦距低
14.71%。所以半径缩小不是当前主要限制，最佳N=100组合是紧凑反射器加1 mm短焦距。历史100 mm
N=1000运行的绝对时钟`R=22562`不得直接引用为分辨率；用保留日志离线按当前时钟重算为单峰
`R=9165.96, FWHM=1.7004 ns`，但其源样本和设计代不同，不是本轮2×2因果对照。

理想上限必须分板报告：轴向理想源+解析理想场oracle为`R=77093.87`；SIMION分段理想场solver
closure为单峰`R=47493.49`；既有实际场理想源Formal结果中，COMSOL单峰为`R=39938.06`，SIMION
虽报`R=47662.02`但有两个显著KDE峰，不能作为单峰最高值。这些源、质量和架构与本轮真实八极杆束
不同，只用于量级上限，不能把差值全部归因于实际场。

2026-08-13又在紧凑`35/70/100 mm, 8/15 rings, t=2 mm`结构完成两类严格诊断。首先，在历史
N=1000紧凑真实束run的同一806粒子、同一实际PA和同一pulse-effective时钟上，restart真实束为单峰
`R=9227.40, FWHM=1.6891 ns`；把源替换为独立`1×1×1 mm`、零`vz`的理想立方源后变为双峰
`R=5762.27, FWHM=2.7049 ns`。真实束的`σx/σy/σz=2.020/0.525/0.486 mm`、
`σvz=121.3 m/s, corr(z,vz)=0.886`，立方源虽缩至约`0.289/0.283/0.286 mm`且`vz=0`，仍因丢失
有利z–vz匹配而恶化；因此历史紧凑理想源`R=107739.8`与当前100 Da、10 eV真实束不是单一源变量的
可比对照，不能用其差值声称多极杆展宽单独造成全部损失。对应run为
`20260813_162000__sim__simion__r100-real-vs-ideal-source__n806`。

其次，以紧凑短/长焦距各自冻结PA为底板，分别使用注册源`SRC-IDEAL-SHORT-Z10`或
`SRC-IDEAL-Z22-AXIAL`比较`ACC-RR`（Stage1/2真实PA）与`ACC-II`（Stage1/2解析理想分段均匀场）
加速场。短焦距同一77粒子在理想场达到单峰`R=81182.51, FWHM=0.19894 ns`，实际场为单峰
`R=15028.11, FWHM=1.07472 ns`，即实际场只保留18.51%的分辨率、FWHM扩大5.40倍，确认短焦距
理论本身有效而当前实际一级/二级场形明显限制它。长焦距同一70粒子在理想场仅为单峰
`R=9794.16, FWHM=1.64537 ns`，实际场反而为单峰`R=10975.44, FWHM=1.46834 ns`；直接FWHM下
实际场高12.1%，但样本小且两者均有明显非高斯性。故长焦距低分辨率首先是理论线性源与完整紧凑
oaTOF在有限2.2 mm区间的高阶等时未闭合，尚不能只用末端FWHM评价实际加速场好坏，也不能说短、
长两套实际场同样好。
四个run依次为`20260813_162500__sim__simion__r100-short-ideal-source-real-accel__n77`、
`20260813_163000__sim__simion__r100-short-ideal-source-ideal-accel__n77`、
`20260813_163500__sim__simion__r100-long-ideal-source-real-accel__n70`和
`20260813_164000__sim__simion__r100-long-ideal-source-ideal-accel__n70`。这些均是单一数值设置的N≤100
诊断，不是数值收敛、Candidate或Formal证据。

随后用轴上理论线性源完成源宽—结构交叉，排除了“长焦距漏改电压”这一解释。短、长两份冻结
resolved均保持`d1=3.0 mm、d2=16.8 mm`；长结构不是只改源宽，而是把加速器整体向焦面移动
`2.60616 mm`，使grid2后漂移由`50.15653 mm`变为`47.55037 mm`。编译器同时把
repeller/grid1由`2154.81956/1844.84477 V`重解为`2157.36821/1842.29059 V`，并把反射器
midgrid/backplate由`1600.89675/2487.29204 V`重解为`1603.67513/2491.61696 V`；不存在沿用
短结构电压的证据。

注册源族`SRC-IDEAL-Z22-AXIAL`和`ACC-II`进入`ARCH-SHORT-Z10-R100`、`ARCH-LONG-Z22-R100`时分别
得到`R=10385.74`与`R=10345.19`，仅差
`0.39%`；长结构按耦合导数重新求反射器后电压只改变约微伏且结果不变。故此前短结构1 mm源
`R=81182.51`与长结构2.2 mm源`R≈10k`的主要差异不是结构平移、紧凑半径、漏改加速器电压或
漏改反射器电压，而是源宽。在短结构内把宽度由1 mm增至2.2 mm，理想加速焦面时间σ由
`0.01980 ns`增至`0.10985 ns`，约5.55倍，接近未消除二阶项随宽度平方增长的4.84倍尺度；最终
FWHM由`0.19894 ns`增至`1.55509 ns`。短结构2.2 mm源换实际场后焦面σ进一步变为
`1.57592 ns`，但探测器端因高阶偶然补偿得到`R=11714.78`，说明必须联合检查焦面与探测器，不能
以末端R略高推断实际场更好。以上均为同一单数值设置、N=77轴上诊断，不是统计或数值收敛证据。

### 一级场归因与局部细PA

本小节的一级场结论只适用于当时真实八极杆束、局部细PA和对应历史cohort/单点数值配置：该隔离曾把
主要误差定位到一级加速区，并显示只理想化二级不足以恢复该历史工况的分辨率。轴向基函数显示该源窗口
内电势主要由repeller/grid1决定，0.2 mm整体PA的关键误差来自透明栅网附近的数值边界层，不是宏观
屏蔽泄漏。简单改端点电压会同时改变二级场和总能量，不能替代场形修正。它不覆盖上面的规范1 mm
affine N=1000四臂矩阵；该严格配对矩阵的检测面FWHM主效应已显示Stage2是主要直接改善方向，当前结论
应按源、cohort、结构和数值配置分别引用。

当前有效修复保持0.2 mm多极杆整体PA，使用六面Dirichlet基函数边界耦合局部0.05 mm加速器PA，并在
出口人工边界前以重叠保护区回退粗PA。方法合同只由
[跨项目连接架构](../../../docs/COMPONENT_CONNECTION_ARCHITECTURE.md#simion粗全局pa与局部细pa耦合)维护。
N=100同网格身份对照的探测TOF配对RMS为0.0160 ns，未发现PA分解造成的系统偏移。

加速器grid1/grid2与反射器entgrid/midgrid现统一由Formal GEM及run-local frontend声明为SIMION官方
零grid-unit厚度的一行理想透明电极点；Program对四面均不得执行epsilon越层、粒子位移或TOF补偿。
项目Candidate SIMION门禁会隔离重建加速器/反射器PA，以官方PA API写四栅单行raw-PA receipt，并要求
冻结单粒子按`1/1/2/2`原生穿越四栅后命中探测器。真实丝网仍是未来独立几何/profile；旧PA与既有run
不会被改写。该门禁已由`20260813_160656__gate__simion__native-ideal-grid__smoke`真实PASS：四栅raw row为
`260/596/0/480`，原生穿越`1/1/2/2`后命中探测器；该证据只闭合官方一行理想栅Candidate功能路径，
不授予集成链、数值收敛、N=100/1000传输、分辨率或Formal资格。

最新N=1000自然注入得到`1000→961→817`（接口→探测器）。在同一冻结808粒子、同几何和同电压的
A/B中，局部细PA把焦面时间σ从4.431降至1.472 ns，焦面z斜率从+6.419降至+1.921 ns/mm，单峰
分辨率从`R=8427`提高到`R=20883`，接近“仅一级理想”的`R=21792`。这证明局部细化是当前有效
数值修复；它仍是单一数值设置诊断，不构成收敛或生产默认声明。

## 证据路由

- [当前10 eV与1.5 mm套筒基准](../../../docs/history/20260805__octupole-terminal-15mm-sleeve-single-flight-n1000.md)
- [入口套筒与加速器内能量](../../../docs/history/20260805__octupole-15mm-sleeve-accelerator-energy.md)
- [前端网格与旧理想场诊断](../../../docs/history/20260810__oatof-frontend-grid-and-ideal-field.md)
- [Formal场归因](../../../docs/history/20260811__oatof-resolution-formal-field-attribution.md)
- [有限区间、理想场与局部PA里程碑](../../../docs/history/20260812__oatof-finite-interval-focus-diagnostics.md)
- [RR轨迹质量q8/q108配对检查准备](../../../docs/history/20260814__oatof-rr-trajectory-quality-paired-check.md)
- [原生栅网、源/场、数值与短长焦全过程](../../../docs/history/20260814__oatof-native-grid-field-source-focus-investigation.md)
- [源、cohort、场与短长焦统一配置注册表及完整结果矩阵](../../../docs/history/20260814__oatof-source-field-configuration-registry-and-results-matrix.md)
- [规范矩阵、高阶像差与33行统一表的派生交互分析](../../../docs/history/20260814__oatof-canonical-matrix-high-order-continuation.md)

## 全理想轴向PROVISIONAL解析报告

[`affine_axial_ideal_report.py`](../analysis/affine_axial_ideal_report.py)提供独立的PROVISIONAL解析入口，由
[`canonical_affine_axial_all_ideal_report_campaign.json`](../config/diagnostics/canonical_affine_axial_all_ideal_report_campaign.json)
选择短/长结构、1.0/2.2 mm以及affine/zero-vz profile。它失败关闭地绑定resolved geometry、source
profile定义、materialization receipt与source release CSV SHA，并校验release行数、有序粒子ID、receipt
粒子数和`continuous_injection_full_population`。逐粒子只组合既有加速器时间、静电出口能量、通用初始
轴向动能和反射器时间API；summary复用规范peak metrics并区分sample/population sigma。报告还按resolved
耦合反射器能量包络标出外推。该入口不调用SIMION/COMSOL、不接入活动run/hash链、不自称receipt，结果固定
为`PROVISIONAL`，不能晋升Candidate或Formal。

## 开放任务

1. 当前不建立`ACC-RR/IR/RI`反射器电压扫描；只有未来出现受支持的新理论输入时，才允许回到完整
   canonical编译链整体重派生。不得用入口实测粒子或检测面FWHM反向拟合`midgrid/backplate`，也不得
   把downstream交互直接写成纯电压失配。
2. 只在归因确认的Stage2及downstream限制区域完成SIMION局部网格收敛；随后以固定ID划分验证传递模型和少量受约束候选，
   冻结detector-blind理论接受窗。窗口覆盖不达机器合同门槛时必须改善场或上游束，不能继续缩窗。
3. 对规范1 mm四臂的检测面多模峰完成预注册bootstrap和峰形稳定性复核；关闭前现有DID仍是确定性
   描述，不是统计显著、数值收敛、生产优化或Formal结果。
4. SIMION稳定通过后生成唯一handoff receipt，再用通用retrace runner完成COMSOL N=100同粒子理想场
   分解、边界对等和局部网格收敛；通过后才在单一商业求解器会话运行N=1000并比较两端结果。
5. COMSOL真实链还须验证全局笛卡尔速度、完整终态census、慢粒子求解、GUI重开Compute和连接开口/
   接地罩边界；这些检查以及机器合同中的跨求解器差异门槛全部通过后，才能关闭复现任务。

## 静态门禁

### 时钟权威与历史隔离

新single-flight run只接受`canonical_instrument_time_us`：冻结source state的`instrument_time_us`是唯一
birth authority，SIMION `.ion`局部时钟固定从0开始，Lua只物化一次`birth + elapsed`，后续analyzer与
五批aggregate纯透传该时间。单位、basis、authority SHA缺失或冲突均在preflight失败；新campaign不得
选择legacy relative/absolute兼容模式。history audit中仍出现的legacy resolution-attribution枚举只用于
解释既有run，不得被活动campaign或single-flight runner调用。原23-arm第二CLI及其合成counterfactual实现
已退出活动代码；仍受支持的detector-blind pre-pulse `z-vz`能力由唯一`family_source_closure`执行人口、
规范checkpoint CSV和campaign直接source/field profile声明承载，不再通过第二runner改写粒子。oaTOF
canonical→ION11/row-map渲染已并入同一family source publisher，旧输入writer已删除；23个旧arm的精确
supported/retired处置及现有authority绑定由
[`family_source_closure_legacy_attribution_migration.json`](../config/family_source_closure_legacy_attribution_migration.json)
冻结，迁移须保持原evidence字节与解释结果。

[`verify_integration.ps1`](../verify_integration.ps1)只验证连接、端口、profile、冻结身份和失败关闭逻辑；
不运行商业求解器，也不替代物理资格。

径向因素的预注册矩阵由
[`radial_factor_attribution_matrix.json`](../config/radial_factor_attribution_matrix.json)维护。它在同一真实多极杆
源身份、pulse-effective时钟、完整pulse-eligible cohort、电压/前端和0.1 mm反射器轴向网格下，分别锁定
shield 100/180/350 mm、电极径向bundle 35/70与250/300 mm、r100拓扑`10/5 t5 → 8/15 t5 →
8/15 t2`及large anchor；晋级后才允许按0.2/0.1/0.05 mm做局部网格收敛。该合同保持
planning-only，复用既有radial-compaction入口，不新建CLI，也不授予求解、排行榜或证据晋升权限。

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
