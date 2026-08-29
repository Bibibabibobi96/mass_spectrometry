# 多极杆公共参考实现

本目录维护四、六、八极杆共享的求解器无关设计编译、COMSOL/SIMION投影、粒子源预检和传输分析。
项目参数、当前结果、项目阈值、专用耦合物理和Formal资格仍由各项目或integration拥有。

当前调用方：

- [RF四极杆](../../projects/rf_quadrupole_ion_optics/README.md)
- [RF六极杆](../../projects/rf_hexapole_ion_optics/README.md)
- [RF八极杆](../../projects/rf_octupole_ion_optics/README.md)

## 设计合同

公共入口只接受`ProjectId + DesignProfileId`。[`design_profile.py`](design_profile.py)从项目注册表定位
项目并解析具名profile；[`compile_design_request.py`](compile_design_request.py)把以下三类输入单向编译
为`multipole_resolved_design_do_not_edit`：

1. 完整机械request；
2. design-variable catalog；
3. 绑定request SHA的optimization envelope。

编译器验证类型、单位、范围、JSON Pointer、约束、enclosure role和segmentation topology，再发布杆
阵列、接口、屏蔽、RF/DC、分段、电位和来源SHA。solver runner不得接受任意resolved文件或物理标量，
COMSOL/SIMION也不得反向改写设计。

typed operating-mode registry只声明同一机械base上的电气差异。当前三个规范模式为：
`no_acceleration_full_length`、`segmented_rod_axial_acceleration`和
`exit_aperture_plate_acceleration`。模式名不能用来偷偷改变几何、源或数值设置。

## 下游终端组合

下游终端profile由对应integration拥有，不在三个项目复制。
[`downstream_terminal.py`](downstream_terminal.py)把已验证resolved design与选定profile确定性组合，
输出唯一`downstream_terminal`几何、所有权和`axial_dc`电位。`owner=downstream`时禁止上游重复
末端电极。屏蔽罩、连接器和外部参考外壳必须精确为`0 V`。

公共接地圆套筒—矩形法兰primitive由[`grounded_shield.py`](grounded_shield.py)生成；具体尺寸和是否
启用由integration profile决定。开孔离散、贯通列与孔外guard遵循
[`common/simion/README.md`](../simion/README.md)。

## 统一术语

下列对象即使坐标重合，也不能互换名称或证据职责：

| 术语 | 职责 |
|---|---|
| 外壳封闭端盖 | 封闭接地外壳的实体端面 |
| 带孔接口板 | 定义接口孔和可选静电势阶跃的实体板 |
| 源释放面 | canonical粒子初态所在轴向位置 |
| 出口孔穿越面 | 判断粒子是否真实穿过出口接口孔 |
| 规范交接面 `handoff` | 发布跨部件canonical状态；跨求解器主评价面 |
| 近接口统计面 | 描述器件紧邻下游的传输与发散 |
| 数值终止标记 | GUI可见的一网格吸收对象，不是机械探测器 |

`source`是粒子集合与分布；`release`是求解器放置动作；`terminal`是撞壁、超时或数值终止等事件。
SIMION无场投影terminal与COMSOL继续解析边缘场的terminal不得混入跨求解器能量或发散结论。

## 粒子源与runtime profile

canonical CSV列固定为：

```text
particle_id,birth_time_s,x_mm,y_mm,z_mm,vx_m_s,vy_m_s,vz_m_s,mass_amu,charge_state
```

[`particle_source_preflight.py`](particle_source_preflight.py)在商业软件启动前验证列、单位、ID、有限值、
时钟、释放面、质量、电荷和动能，并绑定CSV与resolved SHA。四、六、八极杆家族共同使用N=1000母样本
及其精确N=100前缀；精确路径和SHA由项目`particle_source_profiles.json`绑定。

默认源仍必须位于唯一的规范释放面并满足设计的单能源模型。唯一受支持的例外是由
[`continuous_axial_volume_source.py`](sources/continuous_axial_volume_source.py)生成、且其receipt与CSV
哈希互相绑定的连续轴向体积快照：它表示离子源内部的一个同一时刻圆柱体状态，位置与三向速度独立采样，
不预设`z-vz`相关；它不能被解释为已经通过多极杆后的出口束流。

公开生产wrapper只接受`RuntimeProfileId`。runtime profile一次绑定design、particle source、
solver numerics、资源预算和保留类；CLI不得覆盖几何、RF/DC、源能量或网格物理语义。

家族SIMION campaign入口为：

```powershell
.\common\multipole\run_simion_transport_campaign.ps1 `
  -CampaignPath <campaign.json> (-ExperimentId <id> | -All)
```

它串行调用现有单工况runner，不复制求解器逻辑。analysis request只能引用
[`analysis_capabilities.json`](analysis_capabilities.json)中的具名能力，不能嵌入任意模块或路径。

## 证据和资格

[`functional_transport_acceptance.json`](functional_transport_acceptance.json)只评价共享功能传输。
[`engineering_progression_acceptance.json`](engineering_progression_acceptance.json)只允许工程推进；
其PASS不代表数值收敛、求解器等价、绝对精度、Candidate或Formal。

三模式分散方法由[`three_mode_dispersion_contract.json`](three_mode_dispersion_contract.json)冻结。
三个arm必须使用同一机械、母样本、求解器和非变化数值。正式统计需要在运行前冻结bootstrap、接受尺度、
effect resolution和预算；缺少这些设置的既有run只能发布`POSTHOC_DESCRIPTIVE`点估计。

公共分析始终保留全源ID、各arm损失ID和共同幸存者。传输用全源统计，配对连续量只在共同幸存者上
统计；无批准阈值时输出`UNQUALIFIED`或`INCONCLUSIVE`。

项目当前状态只查各项目`docs/PROJECT.md`，跨器件状态只查
[integration当前文档](../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/docs/INTEGRATION.md)。

## 求解器投影

两个L3入口为：

```powershell
.\common\multipole\run_finite_3d_transport.ps1 `
  -ProjectId <id> -DesignProfileId <profile> -ParticleSourcePath <canonical.csv>

.\common\multipole\run_simion_finite_3d_transport.ps1 `
  -ProjectId <id> -DesignProfileId <profile> -ParticleSourcePath <canonical.csv>
```

两端消费同一resolved hash、杆阵列、接口、屏蔽、segmentation和完整drive。数值profile与物理设计分层；
SIMION使用`cell_mm_xyz`，COMSOL显式声明电势单元阶次。普通收敛点默认`compact`，只有事前授权的
最终参考或GUI复核可保留重型求解器资产。

SIMION杆电压只由[`simion_rf_drive.lua`](simion_rf_drive.lua)计算。该纯Lua kernel不拥有Workbench、
segment callback、PA实例或时钟；调用者必须显式传入唯一instrument time。独立多极杆Program传
`ion_time_of_flight`，连续single-flight Program传规范`birth + ion_time_of_flight`。kernel统一验证并
计算sine/cosine、`phase_rad`、RF幅值与scale、两组DC、逐电极common-mode与scale，并发布每周期步数
导出的timestep cap。每个Program只保留一个`fast_adjust`和`tstep_adjust`包装，drive在
`initialize_run`编译一次，飞行热路径不重新解析配置。

生产run必须先把kernel复制为run-local受校验输入，再由Program加载冻结路径；不得在运行时读取仓库
活动文件，也不得在项目wrapper或integration中保留另一份内联RF公式。纯数学回归使用SIMION官方
`simion.exe --nogui --noprompt lua`入口执行[`test_simion_rf_drive.lua`](test_simion_rf_drive.lua)，不加载
Workbench/PA，不refine、不Fly。

运行器统一发布canonical状态、metrics、轻量诊断图、summary和manifest。SIMION与COMSOL的传输率、出口
RMS、输出能量统计、成对差和指标JSON均由Python分析器从canonical状态/事件生成；MATLAB仅输出原始
求解器元数据、状态和事件。PowerShell只编排已冻结的输入与外部进程。跨run图必须共享坐标与分箱；
图和工程metrics本身不授予资格。资源越界时停止本次进程树并报告
`INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED`，不自动重试。

## 单PA GUI模板

四、六、八极杆共用一个不含器件物理的SIMION单PA Workbench模板：

- 构建占位：[`build_simion_layout_placeholder.ps1`](build_simion_layout_placeholder.ps1)
- GUI登记：[`register_simion_layout_template.ps1`](register_simion_layout_template.ps1)
- 当前登记：[`simion_layout_template.json`](simion_layout_template.json)

生产run通过 simion_layout_template_support.ps1 一次解析并冻结注册表、登记manifest、IOB和CON，再重绑run-local PA、更新实例尺寸并恢复Program/Fly2。登记不refine、
不Fly，也不授予Candidate或Formal。SIMION 2026 `.wgem`在许可证和隔离复验完成前不是活动路线。

## 理论与项目状态

通用解析理论见[多极杆理论索引](../../docs/multipoles/index.md)，出口评价见
[出口相空间控制](../../docs/multipoles/exit_phase_space_control.md)。理论文档不得保存项目当前首选参数；
公共实现文档也不复制运行表或故障时间线。
