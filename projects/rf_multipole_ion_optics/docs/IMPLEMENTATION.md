# 多极杆实现与运行合同

本页解释统一多极杆项目的设计编译、求解器投影、输入冻结和传输分析。四、六、八极共用机制，
专属配置和资格分别声明；入口及变体范围见[项目README](../README.md)，当前结果只见[PROJECT](PROJECT.md)。
联合执行与联合证据由[组装层](../../../integrations/README.md)拥有。

按任务阅读：[设计](#设计合同)、[实体与端口](#simion实体与独立pa)、[术语](#统一术语)、
[源与运行选择](#粒子源与runtime-profile)、[证据](#证据和资格)、[求解器执行](#求解器投影)、[GUI模板](#单pa-gui模板)。

实现按职责分开：`core/`拥有物理模型与设计编译，`runtime/`解析输入并编排运行，`analysis/`发布指标与证据，
`comsol/`、`simion/`做求解器投影；`config/`维护机器合同、预登记campaign和源声明。
这些均属于本项目，通用主机调度、粒子释放、状态合同和缓存仍复用仓库`common/`。

## 设计合同

设计解析入口只接受`ProjectId + DesignProfileId`；本项目的owner为`rf_multipole_ion_optics`。[`design_profile.py`](../runtime/design_profile.py)从项目注册表定位
项目并解析具名profile；[`compile_design_request.py`](../core/compile_design_request.py)把以下三类输入单向编译
为`multipole_resolved_design_do_not_edit`：

1. 完整机械request；
2. design-variable catalog；
3. 绑定request SHA的optimization envelope。

编译器验证类型、单位、范围、JSON Pointer、约束、enclosure role和segmentation topology，再发布杆
阵列、接口、屏蔽、RF/DC、分段、电位和来源SHA。solver runner不得接受任意resolved文件或物理标量，
COMSOL/SIMION也不得反向改写设计。

求解器无关杆阵列由[`round_rod_geometry.py`](../core/round_rod_geometry.py)统一生成和判定。`build_rod_array`
省略`cross_section`时保持既有圆杆输出；椭圆杆必须显式声明长短半轴及长轴为径向或切向，
同一 resolved 杆合同由 SIMION GEM 渲染器和项目 COMSOL 杆生成器消费。COMSOL 圆杆仍使用历史
`Cylinder` 分支，显式椭圆杆使用顶底比例为一的 `ECone`（椭圆柱），
`points_inside_rods`对两种截面提供同一批量点内判定。既有`build_round_rod_array`仍是圆杆兼容入口。
[`ideal_transport.py`](../core/ideal_transport.py)同时提供与标量参考公式一致的NumPy批量RF波形和理想多极场适配，
项目不得另存同义批量公式。

typed operating-mode registry 只声明同一机械 base 上的电气差异。允许模式由对应项目的机器注册表
解析；模式名不能隐式改变几何、源或数值设置，本页不复制模式枚举。

### 变量与长度的共享边界

统一的 `config/design_profiles.json` 是设计选择入口；四／六／八极入口直接定位各自配置，
不另建解析或编译实现。每个 profile 显式绑定变量目录、机械 request、约束包络和结构身份。
变量名称、单位、坐标约定、派生公式及通用校验共用；可调变量集合、范围和实际值属于对应设计域，
资格仍绑定具体设计、模型、求解器与工况。相同数值不自动构成共享配置的理由；只有语义、适用域和
维护责任相同才共用，发生真实差异时利用现有 profile 路径绑定专属目录。

杆长统一定义为 `rod_z_max - rod_z_min`，由端点派生，不再另存可独立改写的同义长度输入。
杆长、外壳长度和装配位姿各有含义；装配层只放置已解析的部件，不替项目改长。
现有家族机械参考的共同杆长是对照设计条件，不是四／六／八极所有设计的固定要求。
需要同长比较时，在该研究的请求与约束中明确绑定；其他设计可在自身合法范围内选择长度。

## SIMION实体与独立PA

[`simion_geometry.py`](../simion/simion_geometry.py)的`render_physical_gem(resolved, cell_mm_xyz, electrode_ids=...)`
与独立器件运行的`render_gem`共用同一实体生成器。前者输出提供者原生局部mm坐标下的杆、屏蔽、端盖、孔、
连接器和入口参考套筒；不包含`pa_define`、PA原点平移或数值吸收面。当前接受明确的圆柱外壳，支持连续及
分段杆；贯通模型保留真实带孔外端盖。旧composed终端和矩形reference模型仍可独立渲染，尚不由该组件API
解释所有权；封闭模型若把侧壁末端绑在PA域而非实体端面，也不能作为组件导出。

`electrode_ids`是完整、互异的原生SIMION电极编号到装配求解器编号映射，省略时保持原编号。
同组多个杆使用一个电气编号，不把它误称为每根杆的机械身份。`cell_mm_xyz`仅沿用原渲染器在金属外延长
布尔减孔的padding，不改变实体表面或成为第二份尺寸权威。装配只在完整原生实体外应用一次显式位姿，
不能再次按杆、端盖或套筒分别重算坐标。

同文件的`physical_electrode_view(resolved)`发布圆柱提供者的完整物理电气组：原生SIMION ID、
科学身份、金属角色及指向resolved的电位／drive来源。连续杆和任意已有分段拓扑共用渲染器的编号，
不把数值census／absorber列为物理电极。同一电气编号的多个金属角色合并，冲突电位明确拒绝；
视图不复制驱动数值，也不代表整机已支持多套独立驱动。

圆柱外壳的`cylindrical_grounded_shield_v1`保持两端闭合，
`cylindrical_grounded_shield_through_exit_v1`只发布真实出口孔；
`cylindrical_grounded_shield_through_entrance_exit_v1`才在同一已解析的入口／出口孔径上贯通两块外端盖，
并可发布真实`mechanical_entrance`和`mechanical_exit`。它是机械/API变体，尚未替代任何项目的原生运行、
数值或Formal资格；内部释放面始终不是机械入口。

2026-10-22核对SIMION 2020随附官方`docs/simion.chm`中的
`gem_geometry_file.html#locate-or-project-project-it-transform`及`rotate_y`、`rotate_z`章节；在线定位见
[官方GEM参考](https://simion.com/info/gem_geometry_file.html#locate-or-project-project-it-transform)。
`locate(x,y,z,scale,az,el,rt)`先按`rt`绕X轴、`el`绕Z轴、`az`绕Y轴旋转，再缩放和平移；嵌套变换由内向外。
第4参数`1`是单位缩放。对于`R=[[0,0,1],[1,0,0],[0,1,0]]`，完整原生实体使用
`locate(tx,ty,tz,1,90,90,0)`；非轴对称点`(2,3,5)`投影为`(5,2,3)+t`。
只写`locate(tx,ty,tz,1,90)`不能表达该完整旋转。已有按杆中心单独投影的helper保持原行为，不据新API
重写其历史科学输出。此处参考向量及实体序列化回归不代替新装配的原生GEM栅格、求场或飞行验证。

## 下游终端组合

下游终端profile由对应integration拥有，不在结构变体中复制。 当前 `oatof_shield_terminal` 的唯一catalog为
[`integrations/config/downstream_terminal_profiles.json`](../../../integrations/config/downstream_terminal_profiles.json)，
由 `instrument_assembly` 注册；项目campaign按该owner绑定，旧N1 family不再提供terminal catalog。
[`downstream_terminal.py`](../core/downstream_terminal.py)把已验证resolved design与选定profile确定性组合，
输出唯一`downstream_terminal`几何、所有权和`axial_dc`电位。`owner=downstream`时禁止上游重复
末端电极。屏蔽罩、连接器和外部参考外壳必须精确为`0 V`。

项目的接地圆套筒—矩形法兰primitive由[`grounded_shield.py`](../core/grounded_shield.py)生成；具体尺寸和是否
启用由integration profile决定。开孔离散、贯通列与孔外guard遵循
[`common/simion/README.md`](../../../common/simion/README.md)。

<a id="轴向部件与物理面术语"></a>

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

[`particle_source_preflight.py`](../runtime/particle_source_preflight.py)在商业软件启动前验证列、单位、ID、有限值、
时钟、释放面、质量、电荷和动能，并绑定 CSV 与 resolved SHA。家族母样本、允许前缀、精确路径与
SHA 由项目 `particle_source_profiles.json` 绑定；粒子数等级由公共机器政策定义。

新平面源可在项目 `particle_source_profiles.json` 的具名profile声明
`{"release_spec":"config/sources/<name>.json"}`，与现有CSV `path/sha256` 形式互斥。
JSON使用公共 `repository_ion_release` 的disk／filled-cone／RF策略，显式声明native coordinate ID、
完整母群N、质量／电荷、释放盘、能量、RF频率、锥角和种子；RF／几何不随质量隐式调整。
runtime和预算只验证请求与声明N，不采样。SIMION runner先冻结该JSON及 `common/ion_release` 执行源码，
再由现有source preflight的 `--materialize-release --release-spec <frozen.json> --release-receipt <receipt.json>`
一次生成run-local canonical CSV和receipt；输入均进入同一manifest。完整与分批投影只消费该CSV，
核验冻结spec、receipt、质量／电荷和时钟，不重新采样。不得与family operating point、volume receipt、
campaign相位／能量派生或外部CSV覆盖组合；COMSOL尚未接入该物化模式并明确拒绝。

RF 家族母样本的随机圆盘位置、filled-cone 方向和 RF 相位出生时间由
[`common/ion_release/mt19937_disk_cone_rf_phase.py`](../../../common/ion_release/mt19937_disk_cone_rf_phase.py)
的受注册 disk 策略生成；本项目的 family builder 只选择冻结参数并发布既有的嵌套 CSV，不能再维护
第二份随机采样实现。

样本生成器提供家族N=100／1000／5000嵌套重建，以及`--output-sample --sample-count --seed`独立母样本入口。
分批消费同一冻结母群并使用公共粒子ID映射；生成器只负责发布母样本。

`ideal_transport.py` 也只投影该公共注册表的
`mt19937_uniform_disk_sqrt_cone_rf_phase_v1` 状态到 SI 传输状态；该策略保留 L1 历史的五次 MT19937
取样序列和 `sqrt(u)` 圆锥角，因此不改变既有理想场对照的粒子序列。

默认源仍必须位于唯一的规范释放面并满足设计的单能源模型。唯一受支持的例外是由
[`common/ion_release/continuous_axial_volume.py`](../../../common/ion_release/continuous_axial_volume.py)生成、且其receipt与CSV
哈希互相绑定的连续轴向体积快照：它表示离子源内部的一个同一时刻圆柱体状态，位置与三向速度独立采样，
不预设`z-vz`相关；它不能被解释为已经通过多极杆后的出口束流。

`load_validated_source` 对同一份 CSV 字节完成哈希、解析和完整物理校验，并把 metadata 与已验证 rows
交给 SIMION 投影；metadata-only 消费者继续调用 `validate_source`。投影不再次读表或重验释放面。
每个独立入口仍验证其实际输入，非法列、ID、能量、释放面和批区间继续拒绝；没有跨调用缓存。
同一次 runtime 解析复用已算出的源与 campaign 哈希，保留配置绑定和陈旧身份拒绝。

普通 runtime profile 与 campaign 共用 `runtime_profile.py` 的源身份、数值注册表和设计序列化实现；
普通 profile 在一次解析中只读一次 runtime 注册表。连续体积源的文件字节身份复用
`common/contracts/file_identity.py`，不另维护哈希算法。

家族测试通过真实 PowerShell wrapper 调用与受控 resolver/runner 边界验证显式profile身份、单次解析、数值传递和非法输入拒绝；
基础合同门禁保留机器数据验证，不再读取 wrapper/support 源码计数或限定等价的调用拼写。

有限三维COMSOL wrapper要求具名`RuntimeProfileId`；SIMION wrapper支持两个互斥参数集：
`RuntimeProfileId`，或`CampaignPath + ExperimentId`。两者都不提供默认极数。runtime选择一次绑定design、
particle source、solver numerics、资源预算和保留类；CLI不得覆盖几何、RF/DC、源能量或网格物理语义。

当前八极杆的平面源—连续轴向体积源成对传输由
[`analyze_source_model_comparison.py`](../analysis/analyze_source_model_comparison.py)分析。它只接受两个
已验证的成功 manifest，要求项目、求解器、设计、数值、下游终端和完整粒子 ID 母队列完全一致，
并且要求两臂的 source authority SHA 不同；输出传输/出口差值、可用的损失原因普查与冻结资源指标。
该分析能力目前只接受八极结构，统一owner不会让四极或六极自动取得此能力。它是描述性来源模型比较，
不授予收敛、探测器、Candidate或Formal资格。

家族 SIMION campaign 从仓库根执行。以下为占位命令模板，先替换路径与实验 ID；`-DryRun`
只生成预检/计划，正式执行会启动 SIMION，应在项目声明的资源范围内进行。

```powershell
.\projects\rf_multipole_ion_optics\runtime\run_simion_transport_campaign.ps1 `
  -CampaignPath "<campaign.json>" -ExperimentId "<id>" -DryRun
```

核对计划后使用同一冻结选择执行；整批选择用 `-All` 替换 `-ExperimentId`，不要把两种参数集混用。

它串行调用现有单工况runner，不复制求解器逻辑。analysis request只能引用
[`analysis_capabilities.json`](../config/contracts/analysis_capabilities.json)中的具名能力，不能嵌入任意模块或路径。

分析修复后使用现有 campaign 分析入口和冻结源输入生成新结果；不再保留无人调用的独立 recovery
发布器。设计校验直接消费已读取的 resolved 对象；编译 CLI 只接受现有治理合同，不暴露始终拒绝的
`--source` 参数。

## 证据和资格

[`functional_transport_acceptance.json`](../config/contracts/functional_transport_acceptance.json)只评价共享功能传输。
[`engineering_progression_acceptance.json`](../config/contracts/engineering_progression_acceptance.json)只允许工程推进；
其PASS不代表数值收敛、求解器等价、绝对精度、Candidate或Formal。

三模式分散方法由[`three_mode_dispersion_contract.json`](../config/contracts/three_mode_dispersion_contract.json)冻结。
三个arm必须使用同一机械、母样本、求解器和非变化数值。正式统计需要在运行前冻结bootstrap、接受尺度、
effect resolution和预算；缺少这些设置的既有run只能发布`POSTHOC_DESCRIPTIVE`点估计。

项目分析始终保留全源ID、各arm损失ID和共同幸存者。传输用全源统计，配对连续量只在共同幸存者上
统计；无批准阈值时输出`UNQUALIFIED`或`INCONCLUSIVE`。

项目当前状态只查[PROJECT](PROJECT.md)，跨器件状态只查
[integration当前文档](../../../integrations/docs/INTEGRATION.md)。

## 求解器投影

原生辅助检查包括[定常求解器 smoke](../tests/domain/test_comsol_stationary_solver_smoke.m)与
[定常场采样测试](../tests/domain/test_export_comsol_stationary_field_samples.m)。前者是公共COMSOL启动器的任务脚本，
后者通过已配置LiveLink的MATLAB测试框架执行；入口自行管理本项目`comsol/`依赖路径。L1/L2不运行这两项原生检查。

单进程资源观察器 `Invoke-ResourceBudgetedProcess` 只接受已解析的 `-Limits` 对象，调用者在冻结预算边界
解析一次并直接传递；观察收据仍记录完整 `limits`。原工程预算输入继续冻结；Python→PowerShell的
派生预算只经临时JSON传递，解析后由现有finally清理，不再另存run内的`resolved_resource_budget.json`。
`Complete-ResourceUsage` 只读取已有 usage 收据收尾，不接收无消费者的预算路径。

单进程观察器不以墙钟、目录体积、进程树工作集或可用内存预算越限判定求解器不健康：每种越限只写一次
`RESOURCE_BUDGET_WARNING`并保留健康受管进程至其自然退出。低CPU、暂时无输出或采样空洞也不是停止依据。
原生进程明确失败时，调度器只阻止同一批次继续启动新工作，已运行的健康同级进程自然结束并留下证据。
只有公共执行机制确认持续低于物理内存危险保留量、继续运行会危及主机时，才走强制停止的受管失败处置；
后者记录其明确的内存危险原因，不能被普通预算观察替代。

`New-RepositoryProcessObservation`与`Update-RepositoryProcessObservation`复用上述预算与物理危险计量，
供单进程包装和公共COMSOL入口消费；它们不启动进程、调度、重试或发布科学终态。
物理危险阈值只来自[主机策略](../../../common/host_resource_policy.json)，无Limits时不写usage；
目录与usage写入失败只告警，不能抹去已确认的物理危险。COMSOL接线与调用边界见[公共入口](../../../common/comsol/README.md#主机资源阶段)。

求解器底层入口为 [COMSOL 传输](../runtime/run_finite_3d_transport.ps1) 和
[SIMION 传输](../runtime/run_simion_finite_3d_transport.ps1)。它们由项目 wrapper 或 campaign 传入冻结的
`ProjectId`、`RuntimeProfileId`、`DesignProfileId`、`ParticleSourcePath` 和 `EngineeringBudgetPath`，
不作为跳过 runtime profile 的手工调参入口。执行后检查 summary 的实际状态与 manifest，不能仅凭退出
码或结果文件存在声明成功。

SIMION在原生状态完整后遇到正式科学判据FAIL，会正常发布`failed`、原checks、资格状态和
`native_execution_complete`；释放运行许可后仍以退出码1告知调用者。PASS为0。执行或发布异常仍走
通用失败收尾，不赋予完整原生声明。`component_port.load_transport_producer_result`沿manifest的唯一
小结果记录区分这些情况，供实际出口准备和IP准入复用；完整科学负结果不自动取得器件资格，
也不豁免真实机械出口、完整母群和时钟校验。旧通用失败无新格式fallback。

两入口同时冻结主机调度 facade、Python 核心、策略和 PowerShell 7 检查四个公共依赖，并向冻结执行链传递已选 Python 路径；预算与继承规则见[主机资源调度](../../../docs/OPERATIONS.md#主机资源调度)。
源码清单以解析后的复制根目录计算相对路径，避免 Windows 8.3 短路径与长路径拼写不同导致依赖项
漏列；文件内容仍按原始 SHA-256 校验，不以路径规范化代替内容身份。

COMSOL 父 runner 先持普通轻任务 `prepare`，在启动冻结公共 launcher 前释放自己的许可并恢复继承环境；
子 launcher 独立管理准备、求解和清理阶段，终态后父 runner 重新申请普通轻任务 `postprocess` 完成校验与发布。
若调用方已持许可，runner 不释放或清除别人的 token；继承轻许可不能启动重求解，必须由调用方正确安排阶段。
原预算计量、失败 summary/manifest 和终态通知继续保留。

SIMION 的输入复制、GEM→PA、已确认仅构建 IOB 的 Lua、cache 物化与发布使用普通轻任务 `prepare`。
仅 `refine` 前将同一租约切至重任务 `pa_refine`，进程结束后回到 `prepare`；所有选定 case 共用一个
重任务 `flight` 阶段，随后重新准入普通轻任务 `postprocess`。轻任务仍遵守现有资源预算与实时压力检查，
未知峰值不作为判重依据。case 间的合并和指标分析保留 flight 许可，避免重复切换。
有 dispatch plan 的单批 flight 也通过公共批执行器检查实时 CPU 和完整内存安全预算，临时不足时等待。
观察时长、启动间隔、内存余量和恢复次数由 `common/simion/resource_scheduler.py` 生成的冻结
dispatch plan 传递；PowerShell 检查合法范围及恢复闭合关系，不另锁定默认数值。资源压力回执记录
实际 critical 阈值和持续时间。
内部批次复用外层重任务许可，不增加 allocation 文件或
逐 case 重规划；首批正式进程只在所属 case 内复用，不能跳过后续 control 的首批。

主工况与控制工况的资源回执各自独立：`resource_usage.json` 记录 primary，
`resource_usage__<case_name>.json` 记录对应 control；`case_name` 和
`measurement_scope=single_transport_case_not_all_run_cases` 标明作用域，不能把其中一份当作整次 run 的资源总量。

六/八极的理想场 Python 传输 CLI [`run_ideal_transport.py`](../runtime/run_ideal_transport.py) 复用
[`host_resource_python`](../../../common/host_resource_python.py) 外层桥接取得并核验重许可，原串行积分和科学参数不变。
许可分类与继承只遵循[主机资源调度](../../../docs/OPERATIONS.md#主机资源调度)；接入不代表新增动态粒子分批能力。

两端消费同一resolved hash、杆阵列、接口、屏蔽、segmentation和完整drive。数值profile与物理设计分层；
SIMION使用`cell_mm_xyz`，COMSOL显式声明电势单元阶次。普通收敛点默认`compact`，只有事前授权的
最终参考或GUI复核可保留重型求解器资产。

SIMION杆电压只消费[公共RF驱动kernel](../../../common/simion/README.md#rf驱动)，生产run冻结
[`rf_drive.lua`](../../../common/simion/rf_drive.lua)后加载，wrapper和integration不另存RF公式。
独立多极杆Program传`ion_time_of_flight`，连续single-flight Program传规范`birth + ion_time_of_flight`；
每个Program只保留一个`fast_adjust`和`tstep_adjust`包装，在`initialize_run`编译一次驱动。
纯数学回归使用SIMION官方`simion.exe --nogui --noprompt lua`入口执行
[`test_simion_rf_drive.lua`](../tests/domain/test_simion_rf_drive.lua)，不加载Workbench/PA，不refine、不Fly。

SIMION 完整 PA basis 的内容寻址、完整字节库存、损坏判定、原子发布及 run-local 物化统一委托
[`common/simion/pa_family_cache.py`](../../../common/simion/pa_family_cache.py)。本项目只声明多极杆的 PA 命名、已冻结
数值身份和 runtime-profile 的复用授权；缓存 generation 不携带 GEM、IOB、Lua 等 run-local sidecar。
损坏 generation 必须失败关闭，不能由运行器删除或覆盖；按保留/容量治理决定后续精确清理。该缓存仍是
可重建性能层，不能替代 run 输入或证据。

运行器统一发布canonical状态、metrics、轻量诊断图、summary和manifest。SIMION与COMSOL的传输率、出口
RMS、输出能量统计、成对差和指标JSON均由Python分析器从canonical状态/事件生成；MATLAB仅输出原始
求解器元数据、状态和事件。PowerShell只编排已冻结的输入与外部进程。跨run图必须共享坐标与分箱；
图和工程metrics本身不授予资格。资源预算告警与健康求解保护遵循上文公共执行边界；
预算越界本身不构成终止理由，不自动重试。

共享SIMION阶段与资源回执已通过一次四极杆N=100主臂/控制臂真实复验：
[运行manifest](../../../../artifacts/projects/rf_quadrupole_ion_optics/runs/20260914_161823__sim__simion__quad-dispatch-acceptance-a-n100/run_manifest.json)
完整验证64项输出，两臂均保留全部100个粒子身份，主臂首批观测与控制臂回执独立。
该运行实际完成refine升降级及CPU压力暂停后继续飞行；仅证明共享执行链贯通，不授予物理收敛或Formal资格。

## 单PA GUI模板

四、六、八极杆共用一个不含器件物理的SIMION单PA Workbench模板：

- 构建占位：[`build_simion_layout_placeholder.ps1`](../runtime/build_simion_layout_placeholder.ps1)
- GUI登记：[`register_simion_layout_template.ps1`](../runtime/register_simion_layout_template.ps1)
- 当前登记：[`simion_layout_template.json`](../config/simion_layout_template.json)

生产 run 通过 [`simion_layout_template_support.ps1`](../runtime/simion_layout_template_support.ps1) 一次解析并冻结注册表、登记manifest、IOB和CON，再重绑run-local PA、更新实例尺寸并恢复Program/Fly2。登记不refine、
不Fly，也不授予Candidate或Formal。SIMION 2026 `.wgem`在许可证和隔离复验完成前不是活动路线。

## 理论与项目状态

共有解析理论见[多极杆理论索引](theory/index.md)，出口评价见
[出口相空间控制](theory/exit_phase_space_control.md)。理论文档不得保存项目当前首选参数；
本页也不复制当前运行表或故障时间线。
