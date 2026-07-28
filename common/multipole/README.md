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
- `interfaces_mm`端板、连接器和粒子面；
- `drive`的waveform、RF/DC、common mode、频率和相位；
- `segmentation`及可选分段杆阵列；
- request/catalog/envelope哈希与canonical `resolved_sha256`。

受Git管理的publication以仓库根为`provenance_root`，只记录经过containment校验的repo-relative POSIX路径；
run内编译以`inputs/`为root，只记录run-relative冻结路径。绝对路径、`..`逃逸、缺失源或哈希不符均失败。
`validate_resolved_design`仅用于publication复核：它必须取得原request与source root，重新编译并要求完整
canonical相等。它不是runner的resolved导入口。

## 几何和拓扑闭合

enclosure必须显式声明职责：

- `full_length_grounded_shield`用于圆柱全长屏蔽，必须包络杆、工作区和孔径；入口/出口endcap不得穿入杆段；
- `downstream_local_reference_enclosure`用于四极杆下游局部参考外壳，只约束其局部真空、孔径和连接结构，
  不伪称包络整段杆。

所有闭合比较只使用`1e-12 mm`处理同一解析表达式的浮点舍入；真实越界不通过扩大容差接受。连接器长度、
端板位置、观察面和分段电势均只由request编译，runner没有override。

## 粒子源和证据边界

公共solver core的`ParticleSourcePath`指向canonical CSV，列顺序固定为：

```text
particle_id,birth_time_s,x_mm,y_mm,z_mm,vx_m_s,vy_m_s,vz_m_s,mass_amu,charge_state
```

`particle_source_preflight.py`在启动商业软件前统一验证列/单位语义、N=100或1000策略、连续唯一ID、有限值、
非负clock、release plane、统一质量、电荷，以及由速度和质量复算的动能与resolved source约束。它输出绑定
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
`static_electrodes_V`。矩形参考拓扑显式绑定入口板/连接器、出口罩/连接器与检测器电压；圆柱拓扑
显式绑定屏蔽/入口端盖/连接器和出口端盖/连接器电压。质量过滤器的0/-100/-1500 V因此不再来自
项目旧mode或求解器默认值。SIMION
Lua对`sine`与`cosine`显式分支，未知波形失败；两组电压保持
`common_mode ± (DC + RF waveform)`。分段设计的两个功能arm保持同一几何和RF，只改变axial scale。

runner创建run目录后立即写并验证`interrupted` manifest；所有编译、复制、预检和求解都在同一失败收尾
边界内。终态只写一次，失败时递归收集现存inputs/results/logs/SIMION文件，避免负结果被第二次空manifest
覆盖。实际Python、MATLAB、Lua及公共依赖冻结到`inputs/code/`，生成逐文件SHA-256 inventory，后续执行
从冻结副本加载。

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
Program/Fly2。圆柱投影还在权威检测面生成一网格厚的GUI可见数值吸收片，与oa-TOF detector marker
一样保证粒子在PA内部终止并触发`segment.terminate`，不依赖旧vendor IOB的隐含数组尺寸。没有第二套
identity生命周期，不允许`TemplateIob`覆盖或vendor示例回退。登记不refine、不Fly、不加载Program，
也不授予Candidate或Formal资格。

该路径已由六极杆N=100双工况run
`20260728_004500__sim__simion__rf-hexapole-shared-template__n100__r05`商业复核：manifest success且25项
输出复核通过；`axial_acceleration_rf_on`和`zero_axial_drop_rf_on`均为
`100 source / 100 handoff / 100 terminal / 100 transmitted`。该run没有evidence contract，资格仍为
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
governed profile/compiler、canonical source preflight和resolved `endplate_potential_step` topology覆盖。
旧ION11转换/生成CLI也已删除，canonical CSV是公共L3唯一粒子入口。

Phase 4项目wrapper必须改为profile入口；旧`Adapter`、`FieldScreenRunId`、
`AxialAccelerationContractPath`、connector length、RF/DC/common/phase/frequency、`ParticleMassAmu`和
`ResolvedDesignPath`参数均应视为破坏性移除，不建立兼容翻译层。
