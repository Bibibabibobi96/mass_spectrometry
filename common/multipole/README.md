# 多极杆公共参考实现

本目录是四、六、八极杆共享的求解器无关设计编译、COMSOL/SIMION投影、粒子源预检和传输指标边界。
项目参数、项目证据阈值、专用耦合物理和Formal资格不属于本目录。

当前调用方：

- `projects/rf_quadrupole_ion_optics`
- `projects/rf_hexapole_ion_optics`
- `projects/rf_octupole_ion_optics`

## 唯一物理设计入口

公共solver core只接受`ProjectId + DesignProfileId`，不接受项目目录、resolved文件或单个物理标量。
`design_profile.py`从根`config/project_registry.json`定位唯一canonical项目，再从项目
`config/design_profiles.json`解析具名profile。每个profile以文件SHA-256和不可变身份绑定：

- 完整`multipole_design_request`；
- 对该request全部JSON Pointer有效的design-variable catalog；
- 引用该request文件哈希的optimization envelope；
- enclosure role和segmentation topology。

`compile_design_request.py`是三合同到`multipole_resolved_design_do_not_edit`的唯一生产编译器。它在派生
前校验catalog类型、单位、上下界、envelope request哈希和constraint pointers，再调用本目录既有纯函数
生成杆阵列、轴向接口和分段电极。输出统一冻结：

- 项目/极数身份；
- `geometry_mm.rod_array`及显式enclosure；
- `interfaces_mm`带孔接口板、连接器及各具名物理面；
- `drive`的waveform、RF/DC、common mode、频率和相位；
- `segmentation`及可选分段杆阵列；
- request/catalog/envelope哈希与canonical `resolved_sha256`。

受Git管理的publication以仓库根为`provenance_root`，只记录经过containment校验的repo-relative POSIX路径；
run内编译以`inputs/`为root，只记录run-relative冻结路径。绝对路径、`..`逃逸、缺失源或哈希不符均失败。
`validate_resolved_design`仅用于publication复核：它必须取得原request与source root，重新编译并要求完整
canonical相等。它不是runner的resolved导入口。

### 下游终端组合

活动`multipole_typed_operating_mode_registry` v2只保存杆入口、杆出口相对真实下游终端的电位差；
项目编译器以机械base现有输出参考派生绝对杆电位，旧v1绝对电位registry只用于既有历史重建。
下游终端不是三个多极杆项目的设计副本：唯一profile由integration拥有，并按
[`multipole_downstream_terminal_profiles.schema.json`](../contracts/schemas/multipole_downstream_terminal_profiles.schema.json)
登记。

[`downstream_terminal.py`](downstream_terminal.py)的`compose_downstream_terminal`把一个已验证resolved
design与integration选定profile确定性组合。组合结果直接提供`downstream_terminal`几何、所有权和
`axial_dc`实体电位；`owner=downstream`固定禁止重复上游末端电极。求解器适配器不得再按mode名称推导
电位，也不得把保留在未组合机械base中的旧出口板faces解释为活动集成实体。

已执行的统一终端campaign、数值结果和声明边界只在日期化报告中保存：
[`../../docs/history/20260731__multipole-oatof-shield-terminal-h15-n100.md`](../../docs/history/20260731__multipole-oatof-shield-terminal-h15-n100.md)；
公共实现文档不复制结果表或项目状态。

## 几何和拓扑闭合

enclosure必须显式声明职责：

- `full_length_grounded_shield`用于圆柱全长屏蔽，必须包络杆、工作区和接口孔；入口/出口
  **外壳封闭端盖**不得穿入杆段；
- `downstream_local_reference_enclosure`用于四极杆下游局部参考外壳，只约束其局部真空、孔径和连接结构，
  不伪称包络整段杆。

所有闭合比较只使用`1e-12 mm`处理同一解析表达式的浮点舍入；真实越界不通过扩大容差接受。连接器长度、
接口板位置、具名平面和分段电势均只由request编译，runner没有override。

### 轴向部件与物理面术语

下表是四、六、八极杆活动合同与文档的统一术语。不同对象即使在零长度连接器等特殊几何中坐标重合，
也不得互换名称、字段或证据职责。

| 统一术语 | 英文/活动字段语义 | 唯一职责 | 不得混同 |
|---|---|---|---|
| 外壳封闭端盖 | outer enclosure endcap；`geometry_mm.enclosure.entrance_outer_endcap_*_face_z_mm`和`exit_outer_endcap_*_face_z_mm` | 封闭接地外壳的实体端面 | 带孔接口板、出口孔穿越面 |
| 带孔接口板 | apertured interface plate；`interfaces_mm.<side>.aperture_plate_*_face_z_mm` | 定义接口孔和可选静电势阶跃的实体板 | 外壳封闭端盖、数值终止标记 |
| 源释放面 | source release plane；`interfaces_mm.entrance.release_plane_z_mm` | canonical粒子初始状态的轴向位置 | 粒子源合同、COMSOL release节点、入口板表面 |
| 出口孔穿越面 | exit aperture crossing plane；`interfaces_mm.exit.aperture_crossing_plane_z_mm` | 判断粒子真实穿过出口接口孔 | 杆出口、交接面、统计面 |
| 规范交接面 | canonical handoff plane；`interfaces_mm.exit.handoff_plane_z_mm` | 跨部件输出canonical状态；等于连接器下游端面 | 出口板下游面、统计面 |
| 近接口统计面 | near-interface census plane；`interfaces_mm.exit.census_plane_z_mm` | 当前器件紧邻下游的传输/发散统计 | 远场检测面、规范交接面 |
| 数值终止标记 | SIMION numerical census marker；`numerical_census_marker` | 在统计面提供GUI可见的一网格数值吸收/终止对象 | 机械探测器、接口板、统计面本身 |

杆入口/出口仍分别是`rod_z_min/rod_z_max`。入口源释放面由`release_offset_mm`派生，近接口统计面由
`census_offset_mm`派生；带孔接口板和连接器各自保留上游/下游实体面。规范交接面固定为连接器下游
端面；正长度连接器不得把出口孔穿越面冒充交接面。当前零长度连接器可使两者坐标相同，但语义仍分离。

“source”指粒子集合、分布及其机器合同；“release”只指把该集合置于源释放面的求解器动作或节点。
“terminal/termination”指粒子事件终态，可由数值标记、撞壁、超时或其他终止条件产生，不是任何一个
物理面的别名。“census”是指定统计面上的观察语义；成功粒子可在SIMION数值终止标记处终止，但不能
因此把统计面称为detector。活动多极杆文档禁止用无限定的`endcap/endplate/detector/particle plane`
代替上表术语。

配对加速与跨求解器连续比较统一使用规范`handoff`事件。`terminal/census`只有在两个求解器从
handoff到统计面解析完全相同的场域和终止机制时才可比较；当前SIMION的无场投影terminal与COMSOL
继续解析近接口场的terminal只能作各自求解器内诊断，不得混入跨求解器能量或发散结论。

## 粒子源和证据边界

公共solver core的`ParticleSourcePath`指向canonical CSV，列顺序固定为：

```text
particle_id,birth_time_s,x_mm,y_mm,z_mm,vx_m_s,vy_m_s,vz_m_s,mass_amu,charge_state
```

`particle_source_preflight.py`在启动商业软件前统一验证列/单位语义、N=100或1000策略、连续唯一ID、有限值、
非负clock、源释放面、统一质量、电荷，以及由速度和质量复算的动能与resolved source约束。它输出绑定
CSV SHA-256和parent resolved hash的metadata；MATLAB和SIMION投影只消费通过的冻结CSV/metadata。
两个L3 runner可选同时接收`SourceFamilyPath + OperatingPointId`，用于显式绑定命名源工况；两者必须
成对提供。runner把合同复制到run inputs，冻结其SHA-256与point ID，并把preflight返回的
`operating_point_binding`写入run config。没有该绑定时仍严格使用resolved source能量约束，不允许
5 eV等命名工况隐式绕过官方1.8–2.2 eV范围。

多极杆生产薄wrapper再加一层`runtime_profile.py`治理：公开入口只接受`RuntimeProfileId`，
由项目`runtime_profiles.json`绑定design、particle-source和solver-numerics profile。四、六、八极杆
项目入口通过内部`project_transport_launcher_support.ps1`复用一次解析和COMSOL/SIMION参数映射；
该support不是第二CLI，不保存profile目录、项目默认值或物理参数，公开入口及其项目身份保持不变。
需要跨四、六、八极杆连续执行多个SIMION工况时，家族级公开入口为
[`run_simion_transport_campaign.ps1`](run_simion_transport_campaign.ps1)：它从
`campaigns/`内一张受schema约束的表选择`-ExperimentId`或按表顺序执行`-All`，逐行绑定项目、设计、
粒子源、完整数值设置、资源硬帽和唯一run ID。该入口只预检并串行调用既有单工况runner，不复制物理
或求解器逻辑，不并行商业求解器；每个run仍独立冻结resolved snapshot、campaign SHA和标准产物。
同一入口的`-Status`只读逐文件验证各行manifest，并保守报告`NOT_STARTED`、非终态目录或已验证终态；
目录存在不等于成功。跨行出口汇总统一使用`campaign_analysis.py`，图仍由`exit_state_plot.py`以共享
坐标和固定分箱生成；两者只发布事后工程描述，不授予收敛或资格。
schema v4 campaign还可通过`analysis_requests`引用
[`analysis_capabilities.json`](analysis_capabilities.json)中的版本化能力ID。能力目录是消费者模块、输入
角色、一致性条件、开放参数包络、固定输出角色和声明边界的唯一机器权威；campaign不得写模块、脚本、
命令或任意路径。所引用实验全部形成已验证success manifest后，同一入口自动创建标准analysis run；
`-Status`只读报告分析请求的`PENDING/COMPLETE/FAILED`，不会为补齐输入而写文件。未知能力、外表实验、
越界参数、混合事件/轴面/源ID或不完整输出均失败关闭。v1--v3合同保持原有语义，不因新增能力被事后
解释为预注册分析。schema v5只扩展同一公共入口的受治理初始粒子源变换：campaign逐行声明目标
单能初始能量，公共派生器保持粒子ID、位置、速度方向、出生时刻和N=100/N=1000前缀关系，仅按正标量
缩放三维速度；源预检和SIMION投影以冻结的派生metadata显式验证目标能量。该字段属于初始条件，不是
电极设计变量，不复制三个项目的execution profile，也不得用来改写项目baseline。
圆柱家族实验共同使用`rf_multipole_family_mother_sample_v1_1000.csv`及其精确
`rf_multipole_family_mother_sample_v1_100.csv`前缀；生成算法、seed、分布、消费者和SHA由同目录
`rf_multipole_family_mother_sample_v1.json`冻结；这是当前四/六/八极杆家族实验的唯一粒子源入口。
四极杆旧官方源只供oa-TOF oracle，不是新家族实验源。求解器数值profile保持项目独立，以允许后续
收敛结果分化。

SIMION空间离散的规范表示为`cell_mm_xyz.{x,y,z}`；旧profile中的标量`cell_mm`只在解析边界被
等轴展开，运行快照不再保存第二份标量真相。各向异性比较把`x=y`作为径向因子、`z`作为轴向因子，
并分别登记`spatial_radial`、`spatial_axial`和`spatial_isotropic`，不得把方向矩阵压成单一
“空间收敛”序列。生产runner在启动SIMION前从生成的唯一`pa_define`回读`nx/ny/nz`，将
`simion_grid_audit.json`冻结为run input，并执行预登记的PA点数硬上限。

证据阈值不是物理设计，也不藏在resolved或numerics中。runner可显式接受版本化
`EvidenceContractPath`；`evaluate_transport_evidence.py`只对已产生metrics评分。未给证据合同时仍可完成
求解和metrics输出，但`qualification_status=UNQUALIFIED`；给出后身份或阈值不匹配会失败关闭。
无加速方向follow-up的内部工程分辨率由
[`no_acceleration_followup_resolution.json`](no_acceleration_followup_resolution.json)冻结；它只允许
发布固定分箱下的工程稳定性和配对数值敏感性，不授予绝对精度或求解器优越性。

L2 `analyze_round_rod_screen.py`同样只报告每个输入ratio的场谐波指标与score，不输出
`selected_candidate`，不派生杆半径/中心或决定L3几何。L2商业入口同样要求
`ProjectId + DesignProfileId`，在run内解析profile并编译唯一resolved design；二维求解器只从该resolved
读取多极阶数、电极数和`r0`，筛选合同仅定义候选采样与数值参数。

## 资格合同与状态路由

共享功能验收合同为
[`functional_transport_acceptance.json`](functional_transport_acceptance.json)。四、六、八极杆的当前
完成状态、数值结果和开放任务只查各项目`docs/PROJECT.md`；日期化跨家族比较只查根`docs/history/`。
旧身份证据只从项目描述符的`archived_verified`位置读取，公共层不搜索迁移前顶层路径，也不复制或
改写历史manifest。公共合同的PASS范围不得扩展为碰撞冷却、轴向加速、RF+DC质量过滤、机械、
Candidate或Formal资格。

### 暂时工程推进指标

[`engineering_progression_acceptance.json`](engineering_progression_acceptance.json)记录四、六、八极杆
共同的临时下游工程推进方向。空间必须分别比较束流质心和围绕各自质心的展宽；角度必须分别比较平均
束流方向和围绕各自平均方向的发散；能量必须分别比较平均能量和围绕平均能量的展宽。普通的轴线RMS
半径或非负偏轴角RMS可保留为历史诊断，但不能代替上述分解指标。

阈值、激活状态和缺失指标处置只以该JSON为机器权威，本节不复制数值或状态。能量中心与能量展宽须
等待真实下游接受预算；合同未激活时不得产生工程PASS。新数值活动先从低成本SIMION相邻加密臂开始；
达到工程稳定或发现方向敏感性后停止，再选择少量COMSOL对照。

未来激活的工程PASS还必须同时通过[`functional_transport_acceptance.json`](functional_transport_acceptance.json)，
并验证同一冻结源、物理mode、规范handoff面、透射粒子身份集和观测定义。该PASS只允许推进下一阶段
工程模拟，不回写既有`INCONCLUSIVE`数值收敛结论，也不代表求解器等价、绝对准确度、Candidate或
Formal资格。质心分量、p95/p99尾部、时间中心/展宽及位置—角度相关量必须同时报告；无批准阈值时不
擅自判PASS。

### 三模式粒子分散方法

[`three_mode_dispersion_contract.json`](three_mode_dispersion_contract.json)冻结同一多极杆硬件的三arm
分散实验方法：`no_acceleration_full_length`、`segmented_rod_axial_acceleration`和
`exit_aperture_plate_acceleration`。三个arm必须绑定同一轴向几何identity、同一N=100/N=1000母样本
前缀、同一求解器与除电压模式外的数值设置；公共层不保存项目电压值或验收阈值。

已执行三模式campaign的结果、运行身份和图路径只保存于
[`../../docs/history/20260731__multipole-three-mode-h15-n100.md`](../../docs/history/20260731__multipole-three-mode-h15-n100.md)。

[`three_mode_dispersion.py`](three_mode_dispersion.py)只读取既有canonical component particle-state
CSV。它保留完整源ID集合和各arm损失ID；传输以全源集合统计，半径、角发散、能量和TOF的配对连续量
只在两个arm的共同幸存ID上计算。状态从规范交接面按`vz>0`作无场弹道投影，报告近接口统计面及
`+5/+20/+50 mm`；不创建第二粒子格式或把数值统计面称为探测器。

N=100只用于功能和工程检查；N=1000在项目acceptance允许时才形成统计分散证据。bootstrap seed和
resample数没有公共默认值，必须随项目合同在运行前冻结。每次实验还必须在运行前绑定项目级
acceptance、effect-resolution和engineering-budget合同的路径与SHA，并使用`compact`保留类。公共输出
固定为`UNQUALIFIED_ANALYSIS_ONLY`：95%配对bootstrap区间是测量不确定度，不是接受阈值。预算耗尽时
遵循[`numerical_qualification.json`](numerical_qualification.json)的工程stop policy，报告
`INCONCLUSIVE`，不得放宽标准或继续暴力加密。

正式统计分析的方法和三份项目合同必须在运行前预登记；包含真实handoff文件及其SHA的正式binding只能
在对应run完成后发布。正式binding分别记录`analysis_plan_preregistered_before_run=true`和
`published_after_real_runs=true`，不得把运行后才知道的输出哈希伪称为运行前已冻结。
四、六、八极杆统一调用[`publish_three_mode_binding.py`](publish_three_mode_binding.py)，传入各项目
预注册合同及三份同求解器run manifest；项目内不得建立同职责发布器。该入口只把公共17列handoff事件
映射为跨组件canonical状态、核对三arm共同身份并发布binding，不运行求解器、不实施项目专用坐标变换。

既有run若缺少事前统计设置，只能走独立
[`three_mode_dispersion_posthoc_binding.schema.json`](../contracts/schemas/three_mode_dispersion_posthoc_binding.schema.json)
入口。该binding固定写明`analysis_plan_preregistered_before_run=false`、
`recorded_after_runs=true`和`analysis_class=POSTHOC_DESCRIPTIVE`；分析器只报告传输率、总体点估计、
共同幸存粒子的配对点差和无场投影，不计算bootstrap区间，不读取事后验收阈值，也不输出等价、
优化、Candidate或Formal判定。正式与事后入口复用同一发布器、canonical状态和指标内核，项目不得
复制私有发布器。

三份项目合同分别使用role `multipole_dispersion_acceptance_contract`、
`multipole_dispersion_effect_resolution_contract`和`multipole_engineering_budget_contract`，并包含
非空的`acceptance_criteria`、`effect_resolution`和`pilot_authorization`对象。具体数值、依据、适用
project/solver/N和批准状态属于项目权威；公共层只验证身份、预注册标记和冻结SHA，不提供fallback。

两个商业求解器入口还必须消费runtime profile绑定的engineering-budget合同。预算预检在创建run
package前严格核对project、design、source、粒子数、solver numerics和retention；运行中监测累计墙钟、
本次进程树working set、系统可用内存和run目录体积。越界只终止本次子进程树，manifest记为
`interrupted / resource_budget_exceeded`，自动重试固定为零。`pilot_authorization.limits`还可仅对
COMSOL `mesh_build` runtime profile声明正整数`maximum_mesh_cells`；旧预算不声明时保持原行为，
声明后不得在其他solver或普通transport profile中静默忽略。

## 求解器投影

两个L3入口为：

```powershell
.\common\multipole\run_finite_3d_transport.ps1 `
  -ProjectId <id> -DesignProfileId <profile> -ParticleSourcePath <canonical.csv> `
  [-SourceFamilyPath <source-family.json> -OperatingPointId <point-id>]

.\common\multipole\run_simion_finite_3d_transport.ps1 `
  -ProjectId <id> -DesignProfileId <profile> -ParticleSourcePath <canonical.csv> `
  [-SourceFamilyPath <source-family.json> -OperatingPointId <point-id>]

.\common\multipole\run_simion_transport_campaign.ps1 `
  -CampaignPath <campaign.json> (-ExperimentId <id> | -All)

.\common\multipole\run_simion_transport_campaign.ps1 `
  -CampaignPath <campaign.json> -Status

.\common\multipole\run_round_rod_field_screen.ps1 `
  -ProjectId <id> -DesignProfileId <profile>
```

可选参数只包含网格、cell size、时间步、最大时间、轨迹质量、工具路径、run identity和证据合同。
COMSOL与SIMION消费同一resolved hash、杆阵列、enclosure、interfaces、segmentation、完整drive和
`static_electrodes_V`。矩形参考拓扑显式绑定入口/出口带孔接口板、连接器及局部参考外壳电势；圆柱
拓扑显式绑定全长屏蔽、入口/出口外壳封闭端盖、带孔接口板和连接器电势。所有包含屏蔽罩或外部参考
外壳的组合字段必须精确为`0 V`；Schema、编译器和下游终端组合器均拒绝非零值，设计变量目录也不再
开放屏蔽电位。杆体common mode、独立功能板和物理探测器仍是不同电极，不由接地规则代替。SIMION
Lua对`sine`与`cosine`显式分支，未知波形失败；两组电压保持
`common_mode ± (DC + RF waveform)`。分段设计的两个功能arm保持同一几何和RF，只改变axial scale。

公共连接件`grounded_circular_to_rectangular_shield_v1`由
[`grounded_shield.py`](grounded_shield.py)生成接地圆套筒和带矩形孔的接地法兰，用于闭合圆形多极杆罩与
方形下游罩。具体实验仍由integration的connection profile/campaign显式选择；未选择单流程策略时不改变
既有分阶段工作流。其开孔离散与编译PA贯通判据不在多极杆层私有实现，而统一服从
[`../simion/README.md`](../simion/README.md)的仓库级SIMION连接开孔入口。

COMSOL数值profile必须显式声明`electric_potential_element_order`，当前活动四/六/八极杆profile统一
使用`quadratic`，不得依赖供应商默认阶次。稳态线性求解器由同一公共runner选择`mumps`、`pardiso`
或`cg_amg`；只有`cg_amg`额外消费唯一的`stationary_iterative_solver`对象，不建立第二CLI或同义字段。
迭代路径必须从模型树回读CG、AMG、容差、最大迭代数、误差检查和详细收敛日志，并从COMSOL原生
progress日志取得每个稳态场的正`LinIt`与有限`LinRes`。缺失、零迭代或配置回读不一致均在success
manifest前失败关闭；原生日志保留在本次run的`logs/solver_progress/`。

新的field-only诊断还冻结
[`stationary_field_sampling_plan.json`](stationary_field_sampling_plan.json)，由
[`stationary_field_sampling.py`](stationary_field_sampling.py)从canonical resolved生成唯一
`sample_id/region/x_mm/y_mm/z_mm`点表；项目wrapper不得增加同义采样字段或第二套transport CLI。
COMSOL通过
[`export_comsol_stationary_field_samples.m`](export_comsol_stationary_field_samples.m)在同一批坐标上
显式绑定`differential/static`解，输出V与Ex/Ey/Ez。Python重新校验两场具备相同点身份、region和
坐标，所有值有限且单位列固定；不同run的比较只发布
`INCONCLUSIVE_DIAGNOSTIC_ONLY`误差量，不在缺少物理误差预算时伪造PASS阈值。采样CSV与校验摘要
必须在retention前纳入manifest。

runner创建run目录后立即写并验证`interrupted` manifest；所有编译、复制、预检和求解都在同一失败收尾
边界内。终态只写一次，失败时递归收集现存inputs/results/logs/SIMION文件，避免负结果被第二次空manifest
覆盖。实际Python、MATLAB、Lua及公共依赖冻结到`inputs/code/`，生成逐文件SHA-256 inventory，后续执行
从冻结副本加载。

两个L3入口继承根README的统一产物保留合同，默认`RetentionClass=compact`：保留冻结输入、metrics、
canonical粒子终态/事件、必要日志和轻量图，终态前移除可重建MPH、SIMION PA解阵列和完整轨迹并记录
`retention_actions.json`。普通及中间数值收敛点仍使用compact，并以轨迹提取后的states/metrics完成比较；
只有预注册最终参考点选择`qualification`，确需GUI/网格重开时选择`solver_review`，两者都必须在运行前
提供`RetentionReason`。这项存储选择不改变物理输入、判据或资格。

成功的COMSOL/SIMION L3传输run还统一调用
[`exit_state_plot.py`](exit_state_plot.py)，从本次canonical状态自动发布
`results/exit_state_diagnostics.png`及figure manifest。单run图固定包含横向空间、半径、发散角、动能、
到达时间和半径—发散关系；缺失、空集或非有限状态失败关闭。跨run比较必须在一次调用中提供全部
`--series`，由程序从合并样本冻结共享坐标范围和固定24分箱，不能分别自动缩放后再横向比较。
固定分箱概率以bin center折线发布，不作KDE平滑；综合图legend置于绘图区外。自动样式最多支持10条
series，并保证其高对比颜色和marker分别不重复；超过容量必须拆分为多个共享contract图组，不能静默
循环颜色或形状。
figure manifest记录源状态SHA、run ID、单位、筛选事件、共享范围、bin edges和Git身份；图是诊断产物，
不自行授予收敛、精度或资格。

COMSOL既有runner还可由受治理的薄wrapper传入单一`mesh_build` stop stage。该阶段只在几何和网格生成后
输出选择、体积、覆盖/重叠、mesh feature及质量诊断，并在拓扑断言后停止；它从模型树实际报告零
field physics、field Study、field solution、particle physics和particle Study，launcher验证这些终态及
必需网格report token后才能发布success。它不是第二CLI、第二schema或场/粒子运行入口，必须由项目
runtime profile、工程预算和预注册单独授权。新的field-only授权采用schema v2，并额外冻结公共采样
plan、生成器、COMSOL exporter及准确点数；schema v1只记录已关闭历史运行，不得重新执行。
field-only预检还必须在创建run目录和启动商业工具前完整验证`required_report`的成功tokens与禁入粒子
checkpoints；缺字段、空值、重复项或缺核心终态均立即失败，不得把报告合同延迟到求解后才发现。
真实`mesh_build`报告以`MESH_GLOBAL_ELEMENTS`记录`mphmeshstats`返回的全局总单元数。若预算声明
`maximum_mesh_cells`，runner要求该token恰好出现一次、值为正整数且不超过硬帽；缺报告、缺token、
非法值或超帽均在success manifest前失败关闭，其中超帽归类为`resource_budget_exceeded`。

局部敏感区mesh必须遵守COMSOL尺寸继承：域级细网格自然传递到相邻边界，不得再在同一操作中为这些
边界声明更粗Size；扫掠操作也不把边界级Size作为独立控制轴。公共helper因此只在非局部模式保留显式
杆边界Size，局部模式由`outer/core/sensitive`域级Size和轴向Distribution控制。建网后runner以
`mphmeshstats.hasproblems`作为网格有效性的唯一机器判据；逐feature的`MESH_PROBLEM_*`消息只是统计
之后的best-effort诊断。当前COMSOL客户端不暴露详细问题API时，runner输出`UNAVAILABLE`但不阻断
核心统计，也不因此放宽或替代`hasproblems`判据。

## 单PA GUI模板登记

四、六、八极杆共用一个不含器件物理的单PA Workbench容器，沿用oa-TOF已经验证的
“结构登记run → 生产prepare校验并冻结”机制。最小源由
[`build_simion_layout_placeholder.ps1`](build_simion_layout_placeholder.ps1)从
[`multipole_layout_placeholder.gem`](multipole_layout_placeholder.gem)生成；用户在SIMION 2020 GUI
建立唯一PA实例并保存、关闭、重开后，由
[`register_simion_layout_template.ps1`](register_simion_layout_template.ps1)执行一次无粒子结构检查。
[`inspect_simion_layout_template.lua`](inspect_simion_layout_template.lua)固定验证单实例、相对PA、
`5×5×5 @ 1 mm`占位阵列、`(0,0,0,-90,0,180,1)`变换和`+z/-y/+x`轴向。

当前活动登记由[`simion_layout_template.json`](simion_layout_template.json)绑定到
`20260727_232047__build__simion__multipole-layout-template`的manifest、IOB/CON SHA及2026-07-27人工GUI
复核。该登记run仍按`rf_quad_rename_20260728`映射，并以recorded project ID
`rf_quadrupole_collision_cooling`验证；resolver从当前provider descriptor的
唯一location合同解析迁移前旧根或复核后的archive，并同时复核
legacy mapping、旧run config/manifest身份与文件SHA。新登记入口仍只向
`artifacts/projects/rf_quadrupole_ion_optics/`写入新run，不复用旧身份。
[`simion_layout_template.py`](simion_layout_template.py)只执行与oa-TOF
`prepare_candidate_run`等价的校验和解析；所有多极杆生产SIMION入口将登记manifest、注册表和IOB/CON
复制进本次run后才构建项目物理PA。[`build_simion_runtime_iob.lua`](build_simion_runtime_iob.lua)严格
复用oa-TOF `build_formal_iob.lua`的顺序：重绑run-local PA、更新实例尺寸、保存IOB，再恢复完整同名
Program/Fly2。圆柱投影还在近接口统计面生成一网格厚、GUI可见的
`numerical_census_marker`（数值终止标记），保证成功粒子在PA内部产生明确终态并触发
`segment.terminate`；它不是机械探测器、带孔接口板或统计面本身，也不依赖旧vendor IOB的隐含数组尺寸。没有第二套
identity生命周期，不允许`TemplateIob`覆盖或vendor示例回退。登记不refine、不Fly、不加载Program，
也不授予Candidate或Formal资格。

该路径已由六极杆N=100双工况run
`20260728_004500__sim__simion__rf-hexapole-shared-template__n100__r05`商业复核：manifest success且25项
输出复核通过；`axial_acceleration_rf_on`和`zero_axial_drop_rf_on`当时记录的事件计数均为
`100 source / 100 handoff / 100 terminal / 100 transmitted`。其中source、handoff和terminal分别是
源事件、规范交接事件和终态事件计数，不是三个同义物理面。该run没有evidence contract，资格仍为
`UNQUALIFIED`；它只证明共享模板重绑、真实PA、Program/Fly2和检测终止链闭合。

两项非阻断开放任务保留：当前SIMION 2026 `.wgem`路线因许可证年份不足而以SIMION 2020
GEM+Workbench受控流程绕过；只有确有新版能力需求且许可证更新、官方示例状态机复验成功后才关闭，
不得把绕过解释为供应商问题已根治。跨机可移植性则须把一个登记成功run复制到不同工作区路径，在不依赖
来源绝对路径的条件下复核manifest及IOB/CON/PA重开；三个RF项目都记录迁移验证通过后才关闭。

## 公共遗留兼容边界

旧finite-3D resolver、项目`finite_3d_transport.json`快照、独立轴向加速mode快照，以及
`round_rod_geometry.py`和`axial_acceleration.py`的独立CLI已经退出。活动测试和family门禁直接消费
governed design profile、机械request、typed operating mode、resolved design与solver-numerics
profile；公共模块只保留compiler和求解器实际调用的纯`build_round_rod_array`、
`resolve_axial_acceleration`与`segment_rod_array`。

旧family operating resolver、quadrupole输入准备器和独立endplate resolver已经删除；对应生产入口分别由
governed profile/compiler、canonical source preflight和resolved
`exit_aperture_plate_potential_step` topology覆盖。“endplate acceleration”只作为历史检索词，
活动profile、合同和文档统一称“出口带孔接口板加速”。
旧ION11转换/生成CLI也已删除，canonical CSV是公共L3唯一粒子入口。

Phase 4项目wrapper必须改为profile入口；旧`Adapter`、`FieldScreenRunId`、
`AxialAccelerationContractPath`、connector length、RF/DC/common/phase/frequency、`ParticleMassAmu`和
`ResolvedDesignPath`参数均应视为破坏性移除，不建立兼容翻译层。
