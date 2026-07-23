# 多极杆公共参考实现

本目录是四、六、八极杆共享的求解器无关设计编译、COMSOL/SIMION投影、粒子源预检和传输指标边界。
项目参数、项目证据阈值、专用耦合物理和Formal资格不属于本目录。

当前调用方：

- `projects/rf_quadrupole_collision_cooling`
- `projects/rf_hexapole_ion_guide`
- `projects/rf_octupole_ion_guide`

## 唯一物理设计入口

商业求解runner只接受`ProjectId + DesignProfileId`，不接受项目目录、resolved文件或单个物理标量。
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

`ParticleSourcePath`指向canonical CSV，列顺序固定为：

```text
particle_id,birth_time_s,x_mm,y_mm,z_mm,vx_m_s,vy_m_s,vz_m_s,mass_amu,charge_state
```

`particle_source_preflight.py`在启动商业软件前统一验证列/单位语义、N=100或1000策略、连续唯一ID、有限值、
非负clock、release plane、统一质量、电荷，以及由速度和质量复算的动能与resolved source约束。它输出绑定
CSV SHA-256和parent resolved hash的metadata；MATLAB和SIMION投影只消费通过的冻结CSV/metadata。

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
  -ProjectId <id> -DesignProfileId <profile> -ParticleSourcePath <canonical.csv>

.\common\multipole\run_simion_finite_3d_transport.ps1 `
  -ProjectId <id> -DesignProfileId <profile> -ParticleSourcePath <canonical.csv>

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

## 迁移与删除候选

以下旧实现不再是生产入口；它们仍可能被历史测试或项目专项诊断引用，删除前必须按`AGENTS.md`取得用户
确认并完成引用审计：

- `resolve_finite_3d_contract.py`：由request接口编译替代；
- `round_rod_geometry.py`中的legacy CLI/field-screen selection输入：保留纯`build_round_rod_array`；
- `axial_acceleration.py`的独立CLI：保留compiler调用的纯resolver/segment函数；
- 旧ION11 SIMION source CLI；canonical CSV是公共L3入口。

旧family operating resolver、quadrupole输入准备器和独立endplate resolver已经删除；对应生产入口分别由
governed profile/compiler、canonical source preflight和resolved `endplate_potential_step` topology覆盖。

Phase 4项目wrapper必须改为profile入口；旧`Adapter`、`FieldScreenRunId`、
`AxialAccelerationContractPath`、connector length、RF/DC/common/phase/frequency、`ParticleMassAmu`和
`ResolvedDesignPath`参数均应视为破坏性移除，不建立兼容翻译层。
