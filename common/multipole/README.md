# 多极杆公共参考实现

本目录是四、六、八极杆共享的求解器无关设计编译、COMSOL/SIMION投影、粒子源预检和传输指标边界。
项目参数、项目证据阈值、专用耦合物理和Formal资格不属于本目录。

当前调用方：

- `projects/rf_quadrupole_collision_cooling`
- `projects/rf_hexapole_ion_guide`
- `projects/rf_octupole_ion_guide`

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

六/八极杆的生产薄wrapper再加一层`runtime_profile.py`治理：公开入口只接受`RuntimeProfileId`，
由项目`runtime_profiles.json`绑定design、particle-source和solver-numerics profile。六/八极杆当前
完全相同的固定N=100源只保留
`sources/hex_oct_baseline_fixed_100.csv`一份，各项目通过独立profile与同一SHA绑定；四极杆官方源
语义不同，不参与该共享。求解器数值profile保持项目独立，以允许后续收敛结果分化。

证据阈值不是物理设计，也不藏在resolved或numerics中。runner可显式接受版本化
`EvidenceContractPath`；`evaluate_transport_evidence.py`只对已产生metrics评分。未给证据合同时仍可完成
求解和metrics输出，但`qualification_status=UNQUALIFIED`；给出后身份或阈值不匹配会失败关闭。

L2 `analyze_round_rod_screen.py`同样只报告每个输入ratio的场谐波指标与score，不输出
`selected_candidate`，不派生杆半径/中心或决定L3几何。L2商业入口同样要求
`ProjectId + DesignProfileId`，在run内解析profile并编译唯一resolved design；二维求解器只从该resolved
读取多极阶数、电极数和`r0`，筛选合同仅定义候选采样与数值参数。

## 当前功能数值资格

2026-07-28，四、六、八极杆的`no_acceleration_full_length`均以真实COMSOL和SIMION、同一项目内冻结
N=100源完成五项矩阵：COMSOL空间加密、COMSOL时间加密、SIMION空间加密、SIMION时间加密，以及两边
各自收敛解之间的跨求解器比较，全部`PASS`。机器结果位于
`artifacts/projects/<project_id>/results/numerical_qualification/20260728_functional_transport/`，验收合同为
[`functional_transport_acceptance.json`](functional_transport_acceptance.json)。

该闭合只证明无碰撞RF传输分类、透射粒子ID和正工作半径裕量稳定；连续束斑、发散、TOF、能量及逐粒子
相空间差异只是诊断输出，不在这项PASS内。它也不授予碰撞冷却、轴向加速、RF+DC质量过滤、机械、
Candidate或Formal资格。

## 求解器投影

两个L3入口为：

```powershell
.\common\multipole\run_finite_3d_transport.ps1 `
  -ProjectId <id> -DesignProfileId <profile> -ParticleSourcePath <canonical.csv> `
  [-SourceFamilyPath <source-family.json> -OperatingPointId <point-id>]

.\common\multipole\run_simion_finite_3d_transport.ps1 `
  -ProjectId <id> -DesignProfileId <profile> -ParticleSourcePath <canonical.csv> `
  [-SourceFamilyPath <source-family.json> -OperatingPointId <point-id>]

.\common\multipole\run_round_rod_field_screen.ps1 `
  -ProjectId <id> -DesignProfileId <profile>
```

可选参数只包含网格、cell size、时间步、最大时间、轨迹质量、工具路径、run identity和证据合同。
COMSOL与SIMION消费同一resolved hash、杆阵列、enclosure、interfaces、segmentation、完整drive和
`static_electrodes_V`。矩形参考拓扑显式绑定入口/出口带孔接口板、连接器及局部参考外壳电势；圆柱
拓扑显式绑定全长屏蔽、入口/出口外壳封闭端盖、带孔接口板和连接器电势。质量过滤器的
0/-100/-1500 V因此不再来自
项目旧mode或求解器默认值。SIMION
Lua对`sine`与`cosine`显式分支，未知波形失败；两组电压保持
`common_mode ± (DC + RF waveform)`。分段设计的两个功能arm保持同一几何和RF，只改变axial scale。

runner创建run目录后立即写并验证`interrupted` manifest；所有编译、复制、预检和求解都在同一失败收尾
边界内。终态只写一次，失败时递归收集现存inputs/results/logs/SIMION文件，避免负结果被第二次空manifest
覆盖。实际Python、MATLAB、Lua及公共依赖冻结到`inputs/code/`，生成逐文件SHA-256 inventory，后续执行
从冻结副本加载。

两个L3入口继承根README的统一产物保留合同，默认`RetentionClass=compact`：保留冻结输入、metrics、
canonical粒子终态/事件、必要日志和轻量图，终态前移除可重建MPH、SIMION PA解阵列和完整轨迹并记录
`retention_actions.json`。普通及中间数值收敛点仍使用compact，并以轨迹提取后的states/metrics完成比较；
只有预注册最终参考点选择`qualification`，确需GUI/网格重开时选择`solver_review`，两者都必须在运行前
提供`RetentionReason`。这项存储选择不改变物理输入、判据或资格。

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
复核。[`simion_layout_template.py`](simion_layout_template.py)只执行与oa-TOF
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

本节只登记`common/multipole/`自身仍有活动引用的兼容边界；三个项目各自的退出任务只在对应PROJECT
维护。下列旧实现不再是生产入口，但仍被公共测试或项目专项诊断引用，删除前必须按`AGENTS.md`取得
用户确认并完成引用审计：

- `resolve_finite_3d_contract.py`：由request接口编译替代；
- `round_rod_geometry.py`中的legacy CLI/field-screen selection输入：保留纯`build_round_rod_array`；
- `axial_acceleration.py`的独立CLI：保留compiler调用的纯resolver/segment函数。

旧family operating resolver、quadrupole输入准备器和独立endplate resolver已经删除；对应生产入口分别由
governed profile/compiler、canonical source preflight和resolved
`exit_aperture_plate_potential_step` topology覆盖。“endplate acceleration”只作为历史检索词，
活动profile、合同和文档统一称“出口带孔接口板加速”。
旧ION11转换/生成CLI也已删除，canonical CSV是公共L3唯一粒子入口。

Phase 4项目wrapper必须改为profile入口；旧`Adapter`、`FieldScreenRunId`、
`AxialAccelerationContractPath`、connector length、RF/DC/common/phase/frequency、`ParticleMassAmu`和
`ResolvedDesignPath`参数均应视为破坏性移除，不建立兼容翻译层。
